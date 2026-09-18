"""Analytical weight construction for the Lean 4 kernel transformer.

This module takes a scheduled ALM computation graph and constructs
transformer weights analytically (no gradient descent needed).

Adapted from transformer-vm/model/weights.py.

The weight construction process:
  1. Load the schedule plan
  2. For each layer, compute attention weights (QKV projections)
  3. For each layer, compute FFN weights (ReGLU gating)
  4. For each layer, compute persistence weights (linear projections)
  5. Build input embedding and output head
  6. Save to binary format for C++ inference
"""

from __future__ import annotations
import logging
import math
import struct
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

import torch
import torch.nn as nn

# float64 discipline (transformer-vm parity): analytic weights carry values
# up to BIG=1e20 (clear keys) and pos_sq; float32 would destroy the
# cancellations the construction relies on.
torch.set_default_dtype(torch.float64)

logger = logging.getLogger(__name__)

HARD_K = 1e4  # Temperature for hardmax approximation (matches alm_graph.py)

# ReGLU output clamp of the compiled weight channel. One semantic, three
# mirrors: this constant (used in forward() and forward_stream()),
# model/runner.py (imports this one), and engine/vm.cpp's REGLU_CLAMP
# (C++ mirror — keep byte-for-byte in sync by hand).
# Bounds (docs/decisions/013-reglu-clamp-1e6.md): must exceed every legal
# stream-position read — the step loop emits <= 10 tokens/step and the
# engine harness budget is 3000 steps, so stream <= n0+30001 (largest legal
# read observed: 1003, pow case) — and must stay <= 2^24-1 = 16777215 so
# integer readouts are exact under fp32 storage and llround. 1e6 satisfies
# both. The old +-1000 flattened pow's F readout 1003 -> 1000 and desynced
# the machine (docs/handoffs/002-C-wp6.md C5 step 1.6).
REGLU_CLAMP = 1e6


# ─── Compact Attention ─────────────────────────────────────────────────


class CompactAttention(nn.Module):
    """Memory-efficient attention that only allocates for used heads.

    Instead of nn.MultiheadAttention which always stores (3*D, D) QKV weights,
    this module stores only (H*2, D) where H is the actual number of heads
    needed. Each head uses d_head=2 (2 consecutive residual slots).

    For graphs with D=4418 but max 79 LookUps/layer, this reduces per-layer
    attention params from 58M to ~1M (75x reduction).
    """

    def __init__(self, embed_dim: int, n_heads: int, d_head: int = 2):
        super().__init__()
        self.embed_dim = embed_dim
        self.n_heads = n_heads
        self.d_head = d_head
        self.head_dim = d_head
        self._qkv_dim = n_heads * d_head

        self.q_weight = nn.Parameter(torch.zeros(self._qkv_dim, embed_dim))
        self.k_weight = nn.Parameter(torch.zeros(self._qkv_dim, embed_dim))
        self.v_weight = nn.Parameter(torch.zeros(self._qkv_dim, embed_dim))
        self.out_weight = nn.Parameter(torch.zeros(embed_dim, self._qkv_dim))

    def forward(self, query, key, value, attn_mask=None):
        B, T, D = query.shape

        q = query @ self.q_weight.t()  # (B, T, H*2)
        k = key @ self.k_weight.t()
        v = value @ self.v_weight.t()

        H, dh = self.n_heads, self.d_head
        q = q.view(B, T, H, dh).transpose(1, 2)  # (B, H, T, dh)
        k = k.view(B, T, H, dh).transpose(1, 2)
        v = v.view(B, T, H, dh).transpose(1, 2)

        scale = math.sqrt(dh)
        scores = torch.matmul(q, k.transpose(-2, -1)) / scale

        if attn_mask is not None:
            scores = scores + attn_mask.unsqueeze(0).unsqueeze(0)

        if getattr(self, "hard_fetch", True):
            # LookUpDimension is a discrete fetch: take the argmax and gather
            # it exactly rather than approximating one-hot with a softmax.
            # argmax is scale-invariant, so this needs no HARD_K temperature
            # and no exp — the softmax path's ~1e9-1e10 scores overflow fp16
            # (65504) to inf/NaN and are quantized to ~1e3 in fp32.
            idx = scores.argmax(dim=-1)                  # (B, H, T)
            out = v.gather(2, idx.unsqueeze(-1).expand(-1, -1, -1, dh))
        else:
            attn = torch.softmax(scores, dim=-1)
            out = torch.matmul(attn, v)  # (B, H, T, dh)
        out = out.transpose(1, 2).contiguous().view(B, T, H * dh)
        result = out @ self.out_weight.t()  # (B, T, D)
        return result, None


# ─── Sparse-native build objects (H1/H2) ─────────────────────────────────
#
# The dense lowering allocates 2.4e9 parameters (19.2 GB fp64) to store
# 28,546 nonzeros — it OOMs the 30 GB host.  These objects implement the
# exact subset of the torch tensor surface `build_weights` uses (whole-row
# assignment from `expr_to_tensor`, element set, element `+=`, `zero_()`)
# while storing only nonzeros, so the SAME construction code can drive
# either backend.  Byte-for-byte the emitted CSR matches what
# `save_weights_sparse` would derive from the dense tensors.


class SparseMatrix:
    """Row-major float64 sparse matrix: rows are ``{col: value}`` dicts."""

    __slots__ = ("rows", "cols", "row_data")

    def __init__(self, rows: int, cols: int):
        self.rows = int(rows)
        self.cols = int(cols)
        self.row_data: Dict[int, Dict[int, float]] = {}

    @property
    def data(self):
        """nn.Parameter.data analogue: build_weights reads ``w.data``."""
        return self

    def zero_(self):
        self.row_data.clear()
        return self

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            i, j = int(key[0]), int(key[1])
            v = float(value)
            if v == 0.0:
                row = self.row_data.get(i)
                if row is not None:
                    row.pop(j, None)
                    if not row:
                        self.row_data.pop(i, None)
                return
            row = self.row_data.get(i)
            if row is None:
                row = {}
                self.row_data[i] = row
            row[j] = v
            return

        # Whole-row assignment (mirrors ``tensor[i] = dense_row``).
        i = int(key)
        row: Dict[int, float] = {}
        if value is None:
            pass
        elif isinstance(value, dict):
            for j, v in value.items():
                v = float(v)
                if v != 0.0:
                    j = int(j)
                    row[j] = row.get(j, 0.0) + v
        elif isinstance(value, torch.Tensor):
            nz = value.nonzero(as_tuple=False).reshape(-1)
            vals = value[nz]
            for j, v in zip(nz.tolist(), vals.tolist()):
                v = float(v)
                if v != 0.0:
                    row[int(j)] = row.get(int(j), 0.0) + v
        else:
            for j, v in enumerate(value):
                v = float(v)
                if v != 0.0:
                    j = int(j)
                    row[j] = row.get(j, 0.0) + v
        row = {j: v for j, v in row.items() if v != 0.0}
        if row:
            self.row_data[i] = row
        else:
            self.row_data.pop(i, None)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            i, j = int(key[0]), int(key[1])
            return self.row_data.get(i, {}).get(j, 0.0)
        i = int(key)
        out = [0.0] * self.cols
        for j, v in self.row_data.get(i, {}).items():
            out[j] = v
        return out

    def nnz(self) -> int:
        return sum(len(r) for r in self.row_data.values())


class _SparseLinear:
    def __init__(self, rows: int, cols: int):
        self.weight = SparseMatrix(rows, cols)


class _SparseEmbedding:
    def __init__(self, rows: int, cols: int):
        self.weight = SparseMatrix(rows, cols)


class _SparseAttention:
    """CompactAttention analogue with per-layer head count (H2)."""

    def __init__(self, embed_dim: int, n_heads: int, d_head: int = 2):
        h2 = n_heads * d_head
        self.embed_dim = embed_dim
        self.n_heads = n_heads
        self.d_head = d_head
        self._qkv_dim = h2
        self.q_weight = SparseMatrix(h2, embed_dim)
        self.k_weight = SparseMatrix(h2, embed_dim)
        self.v_weight = SparseMatrix(h2, embed_dim)
        self.out_weight = SparseMatrix(embed_dim, h2)


class SparseLeanModel:
    """LeanTransformer-shaped container backed by SparseMatrix objects.

    Keeps the attribute surface `build_weights` touches (and the header
    fields `save_sparse_native` writes) but allocates only nonzeros.
    ``layer_heads[li]`` is the H_li for that layer; the attention blocks are
    sized 2*H_li, so layers with no lookups carry empty matrices.
    """

    def __init__(self, vocab_size, d_model, n_heads, n_layers, d_ffn,
                 layer_heads, stop_token_id=0):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.d_ffn = d_ffn
        self.layer_heads = list(layer_heads)
        self.stop_token_id = stop_token_id
        self.tok_embedding = _SparseEmbedding(vocab_size, d_model)
        self.attn_layers = [
            _SparseAttention(d_model, h, d_head=2) for h in self.layer_heads
        ]
        self.ff_in = [_SparseLinear(2 * d_ffn, d_model)
                      for _ in range(n_layers)]
        self.ff_out = [_SparseLinear(d_model, d_ffn)
                       for _ in range(n_layers)]
        self.head = _SparseLinear(vocab_size, d_model)
        self.attn_erase: List[List[int]] = []
        self.ffn_erase: List[List[int]] = []
        self.head_tiebreak: List[List[int]] = []
        self.tanh_c = 100.0

    def nnz(self) -> int:
        total = 0
        for a in self.attn_layers:
            total += (a.q_weight.nnz() + a.k_weight.nnz()
                      + a.v_weight.nnz() + a.out_weight.nnz())
        for li in range(self.n_layers):
            total += self.ff_in[li].weight.nnz()
            total += self.ff_out[li].weight.nnz()
        total += self.head.weight.nnz()
        return total

    def nnz_breakdown(self) -> Dict[str, int]:
        d = {"q": 0, "k": 0, "v": 0, "out": 0, "ff_in": 0, "ff_out": 0,
             "head": self.head.weight.nnz()}
        for a in self.attn_layers:
            d["q"] += a.q_weight.nnz()
            d["k"] += a.k_weight.nnz()
            d["v"] += a.v_weight.nnz()
            d["out"] += a.out_weight.nnz()
        for li in range(self.n_layers):
            d["ff_in"] += self.ff_in[li].weight.nnz()
            d["ff_out"] += self.ff_out[li].weight.nnz()
        return d


# ─── Transformer Model Definition ────────────────────────────────────────


class LeanTransformer(nn.Module):
    """Transformer model with hardcoded Lean 4 kernel weights.

    Architecture matches transformer-vm's VanillaTransformer:
      - Standard softmax attention (scaled to approximate hardmax)
      - ReGLU FFN (gated activation: ReLU(b) * a)
      - Residual stream with persistence slots
      - Learnable position encoding (but weights are computed analytically)
    """

    def __init__(
        self,
        vocab_size: int,
        d_model: int,
        n_heads: int,
        n_layers: int,
        d_ffn: int,
        stop_token_id: int = 0,
        compact_attn: bool = True,
    ):
        super().__init__()
        self.stop_token_id = stop_token_id
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.d_ffn = d_ffn
        self.compact_attn = compact_attn

        # Token embedding
        self.tok_embedding = nn.Embedding(vocab_size, d_model)

        # Transformer layers
        if compact_attn:
            self.attn_layers = nn.ModuleList([
                CompactAttention(d_model, n_heads, d_head=2)
                for _ in range(n_layers)
            ])
        else:
            self.attn_layers = nn.ModuleList([
                nn.MultiheadAttention(d_model, n_heads, batch_first=True, bias=False)
                for _ in range(n_layers)
            ])
        self.ff_in = nn.ModuleList([
            nn.Linear(d_model, 2 * d_ffn, bias=False)
            for _ in range(n_layers)
        ])
        self.ff_out = nn.ModuleList([
            nn.Linear(d_ffn, d_model, bias=False)
            for _ in range(n_layers)
        ])

        # Output head (predicts next token)
        self.head = nn.Linear(d_model, vocab_size, bias=False)

        # Erase masks (for slot reuse)
        self.attn_erase: List[List[int]] = []
        self.ffn_erase: List[List[int]] = []

        # Tie-break flags (latest vs average)
        self.head_tiebreak: List[List[int]] = []

        # Soft clamp constant: tanh(x/C)*C. Default 100 for pre-compiled
        # checkpoint compatibility. build_weights() sets 1000 for fresh
        # compilations to preserve input embedding values.
        self.tanh_c: float = 100.0

    def _erase_idx_for(self, li: int, device):
        """(attn, ffn) LongTensor slot indices for layer li, or None.

        attn_erase/ffn_erase are Python slot lists; zeroing them with a
        per-slot ``x[..., slot] = 0.0`` loop costs thousands of dispatches per
        forward (ffn_erase alone lists ~4000 slots over the 98 layers, ~9 s
        per pass regardless of sequence length).  Cached per device.
        """
        cache = getattr(self, "_erase_cache", None)
        if cache is None or cache[0] != device:
            cache = (device, {})
            self._erase_cache = cache
        d = cache[1]
        if li not in d:
            a = self.attn_erase[li] if li < len(self.attn_erase) else []
            f = self.ffn_erase[li] if li < len(self.ffn_erase) else []
            a = [s for s in a if 0 <= s < self.d_model]
            f = [s for s in f if 0 <= s < self.d_model]
            d[li] = (
                torch.as_tensor(a, dtype=torch.long, device=device)
                if a else None,
                torch.as_tensor(f, dtype=torch.long, device=device)
                if f else None,
            )
        return d[li]

    def _live_attn_layers(self) -> set:
        """Layer indices whose attention block can contribute a non-zero value.

        Tested on ``out_weight`` alone: the block writes ``attn @ out_weight.t()``
        into the residual stream, so an all-zero ``out_weight`` makes the whole
        sublayer identically zero no matter what Q/K/V compute. That makes the
        criterion sound (dropping such a layer is provably exact) and
        conservative (a layer kept because its out_weight is non-zero may still
        contribute nothing, which only costs time).

        The scheduler reserves an attention block in every layer but only the
        layers that carry a LookUp get weights written; on the P7.5c build 89
        of 98 layers are dead this way. Scanned once, cached per instance
        (weights never change after build_weights).
        """
        cache = getattr(self, "_live_attn", None)
        if cache is not None:
            return cache
        live = {li for li, a in enumerate(self.attn_layers)
                if a.out_weight.detach().count_nonzero().item()}
        self._live_attn = live
        return live

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through the model.

        x: (batch, seq_len) token indices
        Returns: (batch, seq_len, vocab_size) logits

        Each layer applies causal self-attention then ReGLU FFN. Before the
        first layer we add deterministic position encoding to the residual
        stream (slots 1/2/3 = position / inv_log_pos / position_sq, matching
        the fixed slot assignment in `_assign_slots`).

        Slot reuse via erase: before each sublayer, we zero out slots that
        are about to be overwritten. The `attn_erase[li]` and `ffn_erase[li]`
        lists specify which slots to erase before attention/FFN in layer li.
        This prevents additive contamination when slot reuse is enabled
        (use_erase=True in build_weights).
        """
        x = self.tok_embedding(x)  # (B, T, D)
        B, T, D = x.shape

        # Position encoding written into the position-related slots.
        # These slots are fixed by _assign_slots:
        #   slot 0 = one (set by embedding), slot 1 = position,
        #   slot 2 = inv_log_pos, slot 3 = position_sq
        if D >= 4:
            positions = torch.arange(T, dtype=x.dtype, device=x.device)
            inv_log = (1.0 / math.log(2.0)) - 1.0 / torch.log(positions + 2.0)
            pos_enc = torch.zeros(T, D, dtype=x.dtype, device=x.device)
            pos_enc[:, 1] = positions
            pos_enc[:, 2] = inv_log
            pos_enc[:, 3] = positions * positions
            x = x + pos_enc.unsqueeze(0)

        # Causal mask: position i can only attend to positions <= i.
        causal_mask = None
        if T > 1:
            causal_mask = torch.triu(
                torch.full((T, T), float("-inf"), dtype=x.dtype, device=x.device),
                diagonal=1,
            )

        live_attn = self._live_attn_layers()
        for li in range(self.n_layers):
            a_er, f_er = self._erase_idx_for(li, x.device)
            # ── Erase slots before attention (stale values from previous layers) ──
            if a_er is not None:
                x[..., a_er] = 0.0

            # Attention sublayer (causal); skipped entirely when the layer's
            # QKV/out weights are all zero (the block would add 0).
            if li in live_attn:
                attn_out, _ = self.attn_layers[li](x, x, x, attn_mask=causal_mask)
                x = x + attn_out

            # FFN sublayer (ReGLU): read first, then erase stale slots, then write
            gate_out = self.ff_in[li](x)  # read phase
            gate, val = gate_out.chunk(2, dim=-1)
            act = torch.relu(gate) * val
            # Guardrail against non-halting-path product blow-up (gate and
            # val can both read large hidden values, e.g. 133*133=17689).
            # The bound must not flatten legitimate position reads — see
            # the REGLU_CLAMP definition above and docs/decisions/013.
            act = torch.clamp(act, min=-REGLU_CLAMP, max=REGLU_CLAMP)

            # ── Erase reused slots AFTER read, BEFORE write ──
            if f_er is not None:
                x[..., f_er] = 0.0

            x = x + self.ff_out[li](act)  # write phase

            # Soft clamp: tanh(x/C)*C bounds magnitude while preserving
            # values in the linear range. C is model-specific:
            #   C=100 (default): pre-compiled checkpoints
            #   C=1000: fresh compilations (preserves k=132 from 86.68→131.99)
            C = getattr(self, 'tanh_c', 100.0)
            x = torch.tanh(x / C) * C

        return self.head(x)

    @torch.no_grad()
    def forward_stream(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass with the residual stream supplied directly.

        x: (batch, seq_len, d_model) — the caller builds each position's row
        (input-dim slot values + built-ins) instead of going through the
        token-embedding table. Used by model/runner.py: our token space is
        7 arbitrary integer fields per position, not a fixed vocabulary.

        Returns (batch, seq_len, vocab_size) logits; with output head rows
        built as identity projections (output_tokens = {name: Expression(
        {dim: 1})}) logits[b, t, idx] is exactly the value of output dim idx
        in the residual stream at position t.
        """
        B, T, D = x.shape

        # Position encoding written into the fixed slots (see forward()).
        if D >= 4:
            positions = torch.arange(T, dtype=x.dtype, device=x.device)
            inv_log = (1.0 / math.log(2.0)) - 1.0 / torch.log(positions + 2.0)
            pos_enc = torch.zeros(T, D, dtype=x.dtype, device=x.device)
            pos_enc[:, 1] = positions
            pos_enc[:, 2] = inv_log
            pos_enc[:, 3] = positions * positions
            x = x + pos_enc.unsqueeze(0)

        causal_mask = None
        if T > 1:
            causal_mask = torch.triu(
                torch.full((T, T), float("-inf"), dtype=x.dtype, device=x.device),
                diagonal=1,
            )

        live_attn = self._live_attn_layers()
        for li in range(self.n_layers):
            a_er, f_er = self._erase_idx_for(li, x.device)
            if a_er is not None:
                x[..., a_er] = 0.0

            # Skipped when the layer's QKV/out weights are all zero (the
            # attention block provably contributes nothing).
            if li in live_attn:
                attn_out, _ = self.attn_layers[li](x, x, x, attn_mask=causal_mask)
                x = x + attn_out

            gate_out = self.ff_in[li](x)
            gate, val = gate_out.chunk(2, dim=-1)
            act = torch.relu(gate) * val
            act = torch.clamp(act, min=-REGLU_CLAMP, max=REGLU_CLAMP)

            if f_er is not None:
                x[..., f_er] = 0.0

            x = x + self.ff_out[li](act)

            C = getattr(self, 'tanh_c', 100.0)
            x = torch.tanh(x / C) * C

        return self.head(x)

    @torch.no_grad()
    def generate(self, input_ids: torch.Tensor, max_new_tokens: int = 5000) -> torch.Tensor:
        """Autoregressive generation.

        Uses full forward pass without KV cache.
        """
        device = input_ids.device
        seq = input_ids.tolist()[0]

        for _ in range(max_new_tokens):
            # Build input tensor: (1, seq_len)
            context = seq[-4096:] if len(seq) > 4096 else seq
            x = torch.tensor([context], device=device, dtype=torch.long)

            logits = self.forward(x)
            next_token = logits[0, -1].argmax().item()
            seq.append(next_token)

            if next_token == self.stop_token_id:
                break

        return torch.tensor([seq], device=device)


# ─── Weight Construction ─────────────────────────────────────────────────


def build_weights(
    schedule_plan: Any,
    all_dims: List,
    all_lookups: List,
    input_tokens: Dict[str, Any],
    output_tokens: Dict[str, Any],
    use_erase: bool = True,
    min_d_model: int = 0,
    sparse: bool = False,
) -> Tuple[LeanTransformer, List[str], Dict[str, int]]:
    """Build transformer weights from a schedule plan.

    This function is the main entry point for analytical weight construction.
    It follows transformer-vm's approach but adapted for the Lean kernel graph.

    Args:
      schedule_plan: SchedulePlan from scheduling.
      all_dims: All dimensions in the ALM graph.
      all_lookups: All LookUp operations.
      input_tokens: Input token to expression mapping.
      output_tokens: Output token to expression mapping.
      use_erase: Whether to use erase-based slot reuse.
      sparse: When True, return a SparseLeanModel (SparseMatrix storage,
              per-layer head counts) instead of a dense LeanTransformer.
              Same construction code, only the storage backend changes, so
              the nonzeros are identical — but no dense tensor is ever
              allocated (the 19.2 GB OOM cause).

    Returns:
      (model, all_tokens, tok_to_idx_map)
    """
    from lean_kernel import alm_graph as alm_graph_module
    from lean_kernel.alm_graph import (
        Expression, InputDimension, LookUpDimension, PersistDimension,
        ReGLUDimension,
    )
    # Get current built-in dimensions (reset_graph() creates new ones)
    _one_dim = alm_graph_module._one_dim
    _position_dim = alm_graph_module._position_dim
    _inv_log_pos_dim = alm_graph_module._inv_log_pos_dim
    _position_sq_dim = alm_graph_module._position_sq_dim

    # FIX: post-process schedule to prevent FFN→FFN read-after-write hazards
    # in the same layer.  When a ReGLU reads a PersistDim that is written
    # in the SAME layer, the ReGLU sees the old value because all FFN neurons
    # in a layer compute from the layer input.  Delay such ReGLU ops by one
    # layer by moving them to the next layer's FFN phase.
    _pd_layer = {}  # PersistDim name → its scheduled layer
    for li, layer_info in enumerate(schedule_plan.layers):
        for name in layer_info.get("persist1", []) + layer_info.get("persist2", []):
            _pd_layer[name] = li
        for name in layer_info.get("ffn", []):
            _pd_layer[name] = li

    _reglu_deps = {}  # ReGLU dim → set of PersistDim it depends on
    for d in all_dims:
        if isinstance(d, ReGLUDimension):
            deps = set()
            for expr in (d.a_expr, d.b_expr):
                if isinstance(expr, Expression):
                    for td in expr.terms:
                        if isinstance(td, PersistDimension) and td.name in _pd_layer:
                            deps.add(td.name)
            if deps:
                _reglu_deps[d.name] = deps

    # Move ReGLU ops that are in the same layer as a PersistDim they depend on.
    # Iterate until stable since moving an op may create new conflicts.
    max_iters = 10
    for _ in range(max_iters):
        moved = False
        _pd_layer = {}
        for li, layer_info in enumerate(schedule_plan.layers):
            for name in layer_info.get("persist1", []) + layer_info.get("persist2", []):
                _pd_layer[name] = li
            for name in layer_info.get("ffn", []):
                _pd_layer[name] = li

        _reglu_deps = {}
        for d in all_dims:
            if isinstance(d, ReGLUDimension):
                deps = set()
                for expr in (d.a_expr, d.b_expr):
                    if isinstance(expr, Expression):
                        for td in expr.terms:
                            if isinstance(td, PersistDimension) and td.name in _pd_layer:
                                deps.add(td.name)
                if deps:
                    _reglu_deps[d.name] = deps

        for li in list(range(len(schedule_plan.layers))):
            ffn = schedule_plan.layers[li].get("ffn", [])
            to_move = []
            for name in list(ffn):
                if name in _reglu_deps:
                    for pd_name in _reglu_deps[name]:
                        if _pd_layer.get(pd_name, -1) == li:
                            to_move.append(name)
                            break
            for name in to_move:
                ffn.remove(name)
                if li + 1 < len(schedule_plan.layers):
                    schedule_plan.layers[li + 1].setdefault("ffn", []).append(name)
                else:
                    schedule_plan.layers.append({
                        "layer": li + 1, "attention": [],
                        "persist1": [], "ffn": [name], "persist2": [],
                    })
                    schedule_plan.num_layers += 1
                moved = True
        if not moved:
            break

    # Build consumer map: dimension → set of consumer ops
    # This is needed for proper death computation in _assign_slots.
    _consumers: Dict = {}
    for lu in all_lookups:
        for expr_list in (lu.query_exprs_2d, lu.key_exprs_2d, lu.value_exprs):
            for expr in expr_list:
                if isinstance(expr, Expression):
                    for dim in expr.terms:
                        _consumers.setdefault(dim, set()).add(lu)
        for d in lu.dims:
            _consumers.setdefault(d, set())
    for d in all_dims:
        if isinstance(d, ReGLUDimension):
            for expr in (d.a_expr, d.b_expr):
                if isinstance(expr, Expression):
                    for dim in expr.terms:
                        _consumers.setdefault(dim, set()).add(d)
        if isinstance(d, PersistDimension):
            if isinstance(getattr(d, 'expr', None), Expression):
                for dim in d.expr.terms:
                    _consumers.setdefault(dim, set()).add(d)

    # ---- Determine output dims (dims referenced by output tokens) ----
    # Their slots must not be reused by later-dim writes, because the
    # output head reads the residual stream after ALL layers, not just
    # within the output dim's natural lifetime.
    _output_dims: set = set()
    for expr in output_tokens.values():
        if isinstance(expr, Expression):
            for dim in expr.terms:
                _output_dims.add(dim)

    # Slot assignment (which dimension lives in which residual stream slot)
    slot_of = _assign_slots(all_dims, schedule_plan,
                            all_lookups=all_lookups,
                            consumers=_consumers,
                            output_dims=_output_dims)

    # ---- FIX: protect output-chain dims from slot sharing ----
    # Output dims (is_valid, is_invalid, etc.) and their upstream dependencies
    # (verify_ok, bt_ok, etc.) share slots with earlier dims whose values may
    # leak across layer boundaries when the erase timing is off.
    # Force unique high slots for the output chain to guarantee isolation.
    _output_chain_names = {
        'is_valid', 'is_invalid', 'verify_ok', 'verify_sort_cumul',
        'bt_ok', 'body_ok', 'verify_lam_pi_ok',
        '_vi', '_vd', '_vv',  # split-persist variants
    }
    _max_slot = max(slot_of.values()) if slot_of else 0
    _next_slot = _max_slot + 1
    for d in all_dims:
        if isinstance(d, PersistDimension) and d.name in _output_chain_names:
            # Check if this dim shares its slot with any other dim
            cur_slot = slot_of.get(d)
            if cur_slot is not None:
                sharers = [dd for dd in all_dims if slot_of.get(dd) == cur_slot and dd is not d]
                if sharers:
                    # Give it a unique slot
                    slot_of[d] = _next_slot
                    _next_slot += 1

    # Compute actual d_model from slot assignment
    D = max(slot_of.values()) + 1 if slot_of else schedule_plan.num_slots
    L = schedule_plan.num_layers
    # Enforce minimum d_model to avoid slot cross-talk in large graphs
    if min_d_model > 0 and D < min_d_model:
        D = min_d_model
    # CRITICAL: head writes below assume d_head == 2 (each head occupies
    # exactly two consecutive slots in the d_model output of Q/K/V).
    # With CompactAttention, H only needs to be >= max LookUps per layer
    # (not D//2), saving O(D^2) memory per layer.
    if D % 2 != 0:
        D += 1
    max_attn_per_layer = max(
        (len(l.get("attention", [])) for l in schedule_plan.layers),
        default=1
    )
    # CRITICAL: a lookup with nv values needs ceil(nv/2) heads, so counting
    # lookup ops alone undercounts (our graph has lookups with up to 5
    # values); count heads properly per layer.
    _lu_by_name_h = {f"lookup_{lu.id}": lu for lu in all_lookups}
    _heads_per_layer = []
    for l in schedule_plan.layers:
        _h = 0
        for _lu_name in l.get("attention", []):
            _lu = _lu_by_name_h.get(_lu_name)
            if _lu is not None:
                _h += (len(_lu.value_exprs) + 1) // 2
        _heads_per_layer.append(_h)
    H = max(max(_heads_per_layer, default=1), 1)

    # FFN size: max ReGLU + Persist dims per layer (not total!)
    # Each layer only uses a subset of FFN neurons. Using the per-layer max
    # instead of the total dramatically reduces memory for large graphs.
    max_ffn_per_layer = 0
    for li_info in schedule_plan.layers:
        layer_ffn = (len(li_info.get("ffn", []))
                     + len(li_info.get("persist1", []))
                     + len(li_info.get("persist2", [])))
        if layer_ffn > max_ffn_per_layer:
            max_ffn_per_layer = layer_ffn
    F = max(4, max_ffn_per_layer + 1)

    # Build vocabulary
    all_tokens = sorted(set(input_tokens.keys()) | set(output_tokens.keys()))
    tok_to_idx = {t: i for i, t in enumerate(all_tokens)}
    vocab_size = len(all_tokens)

    # Create model
    if sparse:
        # H2: each layer's attention block is sized by its own head count
        # H_li = _heads_per_layer[li], not the global max.  The per-layer
        # weight loop below only ever writes head indices 0..H_li-1, so no
        # value changes; layers with H_li == 0 carry empty matrices and the
        # engine skips their routing sublayer entirely.
        model = SparseLeanModel(
            vocab_size=vocab_size,
            d_model=D,
            n_heads=H,
            n_layers=L,
            d_ffn=F,
            layer_heads=_heads_per_layer,
            stop_token_id=tok_to_idx.get("halt", 0),
        )
    else:
        model = LeanTransformer(
            vocab_size=vocab_size,
            d_model=D,
            n_heads=H,
            n_layers=L,
            d_ffn=F,
            stop_token_id=tok_to_idx.get("halt", 0),
        )

    # ── Pre-build name→dim indexes for O(1) lookup ──
    _reglu_by_name: Dict[str, Any] = {}
    _persist_by_name: Dict[str, Any] = {}
    _lookup_by_name: Dict[str, Any] = {}
    for d in all_dims:
        if isinstance(d, ReGLUDimension):
            _reglu_by_name[d.name] = d
        elif isinstance(d, PersistDimension):
            _persist_by_name[d.name] = d
    for lu in all_lookups:
        _lookup_by_name[f"lookup_{lu.id}"] = lu

    # Slot assignment (which dimension lives in which residual stream slot)
    def expr_to_tensor(expr) -> torch.Tensor:
        w = torch.zeros(D)  # default dtype = float64 (module-level discipline)
        if isinstance(expr, Expression):
            for dim, coeff in expr.terms.items():
                if dim in slot_of:
                    w[slot_of[dim]] += coeff
        return w

    # Build weights analytically
    with torch.no_grad():
        # ── Embedding layer ─────────────────────────────────
        model.tok_embedding.weight.zero_()
        one_slot = slot_of.get(_one_dim) if _one_dim is not None else None
        for tok_name, expr in input_tokens.items():
            if tok_name in tok_to_idx:
                idx = tok_to_idx[tok_name]
                emb = expr_to_tensor(expr)
                # CRITICAL: every input embedding must populate the `one` slot
                # with 1.0 — downstream ALM primitives (reglu/stepglu/persist
                # using `one_expr`) read this slot. If it's left at 0 the whole
                # network silently computes zeros.
                if one_slot is not None:
                    emb[one_slot] = 1.0
                model.tok_embedding.weight[idx] = emb

        # ── Output head ─────────────────────────────────────
        model.head.weight.zero_()
        for tok_name, expr in output_tokens.items():
            if tok_name in tok_to_idx:
                idx = tok_to_idx[tok_name]
                model.head.weight[idx] = expr_to_tensor(expr)

        # ── Op → scheduled-layer map (stable, post-fixup) ───────────────
        # Used by Fix B (skip passthrough for same-layer ReGLU terms) and
        # Fix C (consumer-aware erase masks). Built AFTER the schedule fixup
        # loop (lines ~245-290), so it reflects the final, well-ordered plan.
        _op_layer: Dict[str, int] = {}
        for _li, _li_info in enumerate(schedule_plan.layers):
            for _name in (_li_info.get("attention", []) + _li_info.get("persist1", [])
                          + _li_info.get("ffn", []) + _li_info.get("persist2", [])):
                _op_layer[_name] = _li

        # ── Layer weights ───────────────────────────────────
        for layer_idx in range(L):
            layer_info = schedule_plan.layers[layer_idx]

            # Zero all weights for this layer unconditionally
            attn_layer = model.attn_layers[layer_idx]
            if hasattr(attn_layer, 'q_weight'):
                # CompactAttention
                attn_layer.q_weight.data.zero_()
                attn_layer.k_weight.data.zero_()
                attn_layer.v_weight.data.zero_()
                attn_layer.out_weight.data.zero_()
            else:
                # Legacy MultiheadAttention
                attn_layer.in_proj_weight.data.zero_()
                attn_layer.out_proj.weight.data.zero_()
            fi = model.ff_in[layer_idx].weight.data
            fo = model.ff_out[layer_idx].weight.data
            fi.zero_()
            fo.zero_()

            # Skip weight population if no operations in this layer
            if not layer_info.get("ffn") and not layer_info.get("attention") and \
               not layer_info.get("persist1") and not layer_info.get("persist2"):
                continue

            # For each LookUp in this layer, set up attention heads
            lookup_names = layer_info.get("attention", [])
            head_idx = 0
            _use_compact = hasattr(attn_layer, 'q_weight')
            if _use_compact:
                qw = attn_layer.q_weight.data
                kw = attn_layer.k_weight.data
                vw = attn_layer.v_weight.data
                ow = attn_layer.out_weight.data
            for lu_name in lookup_names:
                lu = _lookup_by_name.get(lu_name)
                if lu is None:
                    continue
                nv = len(lu.value_exprs)
                for p in range((nv + 1) // 2):
                    if head_idx >= H:
                        break

                    h = head_idx
                    head_idx += 1

                    # QKV projections
                    qx_expr = lu.query_exprs_2d[0]
                    qy_expr = lu.query_exprs_2d[1]
                    kx_expr = lu.key_exprs_2d[0]
                    ky_expr = lu.key_exprs_2d[1]
                    v0_expr = lu.value_exprs[p * 2]

                    sqrt_dh = math.sqrt(2.0)
                    if _use_compact:
                        # CompactAttention: separate q/k/v weights (H*2, D)
                        qw[h * 2] = expr_to_tensor(qx_expr) * HARD_K * sqrt_dh
                        qw[h * 2 + 1] = expr_to_tensor(qy_expr) * HARD_K * sqrt_dh
                        kw[h * 2] = expr_to_tensor(kx_expr)
                        kw[h * 2 + 1] = expr_to_tensor(ky_expr)
                        vw[h * 2] = expr_to_tensor(v0_expr)
                        if p * 2 + 1 < nv:
                            vw[h * 2 + 1] = expr_to_tensor(lu.value_exprs[p * 2 + 1])
                    else:
                        # Legacy MultiheadAttention: (3*D, D) in_proj
                        ip = attn_layer.in_proj_weight.data
                        ip[h * 2] = expr_to_tensor(qx_expr) * HARD_K * sqrt_dh
                        ip[h * 2 + 1] = expr_to_tensor(qy_expr) * HARD_K * sqrt_dh
                        ip[D + h * 2] = expr_to_tensor(kx_expr)
                        ip[D + h * 2 + 1] = expr_to_tensor(ky_expr)
                        ip[2 * D + h * 2] = expr_to_tensor(v0_expr)
                        if p * 2 + 1 < nv:
                            ip[2 * D + h * 2 + 1] = expr_to_tensor(lu.value_exprs[p * 2 + 1])

                    # Output projection
                    d0 = lu.dims[p * 2]
                    if d0 in slot_of:
                        if _use_compact:
                            ow[slot_of[d0], h * 2] = 1.0
                        else:
                            attn_layer.out_proj.weight.data[slot_of[d0], h * 2] = 1.0

                    if p * 2 + 1 < nv:
                        d1 = lu.dims[p * 2 + 1]
                        if d1 in slot_of:
                            if _use_compact:
                                ow[slot_of[d1], h * 2 + 1] = 1.0
                            else:
                                attn_layer.out_proj.weight.data[slot_of[d1], h * 2 + 1] = 1.0

            # FFN weights (ReGLU)
            fi = model.ff_in[layer_idx].weight.data
            fo = model.ff_out[layer_idx].weight.data
            fi.zero_()
            fo.zero_()

            ffn_names = layer_info.get("ffn", [])
            j = 0
            _persist_names_in_layer = set(
                layer_info.get("persist1", []) + layer_info.get("persist2", [])
            )
            for dim_name in ffn_names:
                d = _reglu_by_name.get(dim_name)
                if d is None:
                    continue
                fi[j] = expr_to_tensor(d.b_expr)
                fi[F + j] = expr_to_tensor(d.a_expr)

                if d in slot_of:
                    fo[slot_of[d], j] = 1.0
                # FIX: forward ReGLU output directly to any PersistDim
                # that references this ReGLU AND is in the same layer.
                # This avoids the timing issue where a persist passthrough
                # neuron reads a stale ReGLU value from the layer input.
                # Cross-layer forwarding is NOT needed — the erase mechanism
                # clears stale values before later layers read them.
                # Cross-layer forwarding was causing slot accumulation:
                # multiple ReGLUs in layer 0 all forwarded to the same
                # persist slot, adding their values instead of replacing.
                if layer_idx is not None:
                    for pd_name in _persist_names_in_layer:
                        pd = _persist_by_name.get(pd_name)
                        if pd is not None and d in pd.expr.terms:
                            coeff = pd.expr.terms[d]
                            if pd in slot_of:
                                fo[slot_of[pd], j] += coeff
                j += 1

            # Passthrough neurons (for Persist dimensions)
            # FIX: persist expressions with multiple terms need separate neurons
            # per term. A single neuron would only see dims available at its layer,
            # and if terms come from different ReGLU layers, some may be stale/zero.
            # By creating one neuron per term, each neuron reads exactly one dim,
            # and the output projection (fo) accumulates them into the persist slot.
            #
            # FIX B (compiler fidelity): skip the passthrough neuron for any term
            # that is a ReGLU scheduled in the SAME layer as this PersistDim. The
            # direct-forward block above (lines ~504-520) already writes that
            # ReGLU's contribution into the persist slot correctly (it uses the
            # ReGLU's own neuron j, whose `act` is the fresh ReGLU output). The
            # passthrough neuron here would instead read the term-dim's slot from
            # `ff_in` (line 141) — which at this point still holds the STALE
            # cross-layer occupant of the slot (ffn_erase fires AFTER the read,
            # at line 150-153). So for a same-layer ReGLU term the passthrough
            # neuron is BOTH redundant (direct-forward already did it) AND wrong
            # (it reads stale data), producing an additive double-write that
            # contaminates the persist slot. Skipping it is strictly correct.
            persist_names = layer_info.get("persist1", []) + layer_info.get("persist2", [])
            for pd_name in persist_names:
                d = _persist_by_name.get(pd_name)
                if d is None:
                    continue
                if j >= F:
                    break
                # Expand multi-term expression into one neuron per term,
                # skipping same-layer ReGLU terms (handled by direct-forward).
                terms_to_emit = [
                    (t_dim, t_coeff)
                    for t_dim, t_coeff in d.expr.terms.items()
                    if not (isinstance(t_dim, ReGLUDimension)
                            and _op_layer.get(t_dim.name) == layer_idx)
                ]
                n_terms = len(terms_to_emit)
                need_neurons = max(1, n_terms)
                if need_neurons > 1 and j + need_neurons > F:
                    # Not enough FFN space — fall back to a single neuron
                    # over the full expr (includes same-layer ReGLU terms,
                    # so its `fi` reads the stale slot; but this only
                    # happens under FFN-pressure, where correctness is
                    # best-effort anyway). At minimum, mask out the stale
                    # same-layer ReGLU slots so they read 0.
                    fi[j] = expr_to_tensor(d.expr)
                    for t_dim, _ in d.expr.terms.items():
                        if (isinstance(t_dim, ReGLUDimension)
                                and _op_layer.get(t_dim.name) == layer_idx
                                and t_dim in slot_of):
                            fi[j, slot_of[t_dim]] = 0.0
                    if _one_dim in slot_of:
                        fi[F + j, slot_of[_one_dim]] = 1.0
                    if d in slot_of:
                        fo[slot_of[d], j] = 1.0
                    j += 1
                elif n_terms == 0:
                    # All terms are same-layer ReGLUs — fully handled by
                    # direct-forward. Emit a no-op neuron (gate reads
                    # `one`, value 0) so the slot isn't left unwritten if
                    # direct-forward didn't fire for some reason; this is
                    # a safety net, normally zero-cost.
                    if _one_dim in slot_of:
                        fi[j, slot_of[_one_dim]] = 1.0
                    if d in slot_of:
                        fo[slot_of[d], j] = 0.0
                    j += 1
                else:
                    slot = slot_of.get(d)
                    for t_dim, t_coeff in terms_to_emit:
                        if j >= F:
                            break
                        # Gate: read one term dim (weight 1.0)
                        fi[j] = expr_to_tensor(Expression({t_dim: 1}))
                        # Value = 1.0 (from "one" slot)
                        if _one_dim in slot_of:
                            fi[F + j, slot_of[_one_dim]] = 1.0
                        if slot is not None:
                            fo[slot, j] = t_coeff
                        j += 1

            # ── Generate erase masks for slot reuse ────────────────────
    if use_erase:
        # Build reverse mapping: slot → (layer_idx, phase) of last writer
        slot_last_writer = {}  # slot → (li, phase_kind)

        # Register InputDimension slots as initially written by the embedding
        # phase (layer -1). This ensures that when a PersistDimension or
        # ReGLU reuses an InputDimension slot in a later layer, the erase
        # logic fires to clear the stale InputDimension value before the
        # new write. Without this, e.g. ensure_ok (PersistDim) reusing slot 0
        # (one InputDim) would get 1.0+0=1.0 instead of 0.0.
        for _d in all_dims:
            if isinstance(_d, InputDimension) and _d in slot_of:
                slot_last_writer[slot_of[_d]] = (-1, "input")

        for li in range(L):
            layer_info = schedule_plan.layers[li]
            # Collect slots written in this layer
            written_slots = set()

            # Attention writes LookUp dims
            for lu_name in layer_info.get("attention", []):
                lu = _lookup_by_name.get(lu_name)
                if lu is None:
                    continue
                for p in range((len(lu.value_exprs) + 1) // 2):
                    for vi in range(2):
                        if p * 2 + vi < len(lu.dims):
                            d = lu.dims[p * 2 + vi]
                            if d in slot_of:
                                written_slots.add(slot_of[d])

            # FFN writes ReGLU/Persist dims
            for dim_name in layer_info.get("ffn", []):
                d = _reglu_by_name.get(dim_name)
                if d is not None and d in slot_of:
                    written_slots.add(slot_of[d])

            for pd_name in layer_info.get("persist1", []) + layer_info.get("persist2", []):
                d = _persist_by_name.get(pd_name)
                if d is not None and d in slot_of:
                    written_slots.add(slot_of[d])

            # For each written slot that was written in a PREVIOUS layer,
            # we need to erase it before the sublayer that writes it.
            # CRITICAL: only erase if the previous write was in an EARLIER
            # layer.  Same-layer attention→FFN slot reuse does not need
            # erasing because the FFN read happens after the attention write
            # within the same layer — the read captures the attention output
            # and the subsequent write adds the FFN result on top.
            attn_slots = set()
            ffn_slots = set()

            for lu_name in layer_info.get("attention", []):
                lu = _lookup_by_name.get(lu_name)
                if lu is None:
                    continue
                for p in range((len(lu.value_exprs) + 1) // 2):
                    for vi in range(2):
                        if p * 2 + vi < len(lu.dims):
                            d = lu.dims[p * 2 + vi]
                            if d in slot_of:
                                s = slot_of[d]
                                prev = slot_last_writer.get(s)
                                if prev is not None and prev[0] < li:
                                    attn_slots.add(s)
                                slot_last_writer[s] = (li, "attn")

            for dim_name in layer_info.get("ffn", []):
                d = _reglu_by_name.get(dim_name)
                if d is not None and d in slot_of:
                    s = slot_of[d]
                    prev = slot_last_writer.get(s)
                    if prev is not None and prev[0] < li:
                        ffn_slots.add(s)
                    slot_last_writer[s] = (li, "ffn")

            for pd_name in layer_info.get("persist1", []) + layer_info.get("persist2", []):
                d = _persist_by_name.get(pd_name)
                if d is not None and d in slot_of:
                    s = slot_of[d]
                    prev = slot_last_writer.get(s)
                    if prev is not None and prev[0] < li:
                        ffn_slots.add(s)
                    slot_last_writer[s] = (li, "ffn")

            model.attn_erase.append(sorted(attn_slots))
            model.ffn_erase.append(sorted(ffn_slots))
    else:
        # No slot reuse: empty erase masks
        for _ in range(L):
            model.attn_erase.append([])
            model.ffn_erase.append([])

    one_expr = Expression({_one_dim: 1})
    pos_expr = Expression({_position_dim: 1})

    # Store slot assignment on model for debugging/testing
    model._slot_of = slot_of

    # tanh_c must be >> max(pos_sq) = max_pos^2 to avoid non-linear
    # compression of the position encoding. fetch_by_position uses the
    # quadratic scoring -(p-q)^2 + q^2, which requires pos_sq = p^2 to be
    # uncompressed. With C=10000, tanh(2116/10000)*10000 = 2085 (not 2116),
    # causing nearby positions to outscore the target (e.g., pos=49 beats
    # pos=46 when query=46). C=1e9 makes tanh act as identity for all
    # practical values (10000/1e9 = 1e-5, tanh(1e-5) ~ 1e-5).
    model.tanh_c = 1_000_000_000.0

    return model, all_tokens, tok_to_idx


def _assign_slots(all_dims: List, schedule_plan: Any,
                  all_lookups: Optional[List] = None,
                  consumers: Optional[Dict] = None,
                  output_dims: Optional[set] = None) -> Dict:
    """Assign each dimension to a residual stream slot using interval coloring.

    Uses lifetime information (birth = producer phase, death = last direct
    consumer phase + 1) to reuse slots.  Coloring runs at LAYER granularity:
    writes are additive and erases only fire across layer boundaries, so a
    slot's writers must occupy strictly increasing layers (occupancy =
    closed interval [birth//4, (death-1)//4]); the erase mask machinery
    (build_weights) then clears each slot before every cross-layer rewrite.

    Slots 0-3 are reserved for built-ins (one, position, inv_log_pos,
    position_sq) — these are always alive.
    """
    from lean_kernel.alm_graph import (
        InputDimension, ReGLUDimension, PersistDimension,
        LookUpDimension, LookUp, Expression,
    )

    slot_of: Dict = {}
    protected_slots: set = set()

    # ── 1. Fixed built-in slots ─────────────────────────────────
    fixed_names = {"one": 0, "position": 1, "inv_log_pos": 2, "position_sq": 3}
    for d in all_dims:
        if isinstance(d, InputDimension) and d.name in fixed_names:
            slot = fixed_names[d.name]
            slot_of[d] = slot
            protected_slots.add(slot)

    # ── 2. Build phase map from plan ────────────────────────────
    plan_phases = {}
    for li, layer_info in enumerate(schedule_plan.layers):
        for op_name in layer_info.get("attention", []):
            plan_phases[op_name] = (li, 0)
        for op_name in layer_info.get("persist1", []):
            plan_phases[op_name] = (li, 1)
        for op_name in layer_info.get("ffn", []):
            plan_phases[op_name] = (li, 2)
        for op_name in layer_info.get("persist2", []):
            plan_phases[op_name] = (li, 3)
    P = 4 * schedule_plan.num_layers

    # ── 3. Compute lifetimes (birth, death) ─────────────────────
    birth: Dict = {}
    death: Dict = {}

    # Input dims are born at phase 0 and live forever
    for d in all_dims:
        if isinstance(d, InputDimension):
            birth[d] = 0
            death[d] = P

    # Non-input dims: birth = producer phase
    for d in all_dims:
        if isinstance(d, InputDimension):
            continue
        if isinstance(d, ReGLUDimension):
            producer_name = d.name
        elif isinstance(d, PersistDimension):
            producer_name = d.name
        elif isinstance(d, LookUpDimension):
            producer_name = f"lookup_{d.lookup.id}"
        else:
            continue

        if producer_name in plan_phases:
            li, pi = plan_phases[producer_name]
            birth[d] = 4 * li + pi
        else:
            birth[d] = 0

    # FIX: PersistDims that depend on ReGLU dims in the SAME layer read
    # stale values (all FFN neurons read from the layer INPUT, not each
    # other's outputs). Force birth to be at least 1 layer after ALL
    # ReGLU dependencies to guarantee the ReGLU writes are visible.
    for d in all_dims:
        if isinstance(d, PersistDimension):
            min_birth = birth.get(d, 0)
            for term_dim in d.expr.terms:
                if isinstance(term_dim, ReGLUDimension) or isinstance(term_dim, PersistDimension):
                    dep_birth = birth.get(term_dim, 0)
                    required = dep_birth + 4  # +1 layer = 4 phases
                    if required > min_birth:
                        min_birth = required
            if min_birth > birth.get(d, 0):
                birth[d] = min_birth

    # Non-input dims: death = max DIRECT consumer phase + 1
    # The +1 keeps the dim alive through the phase of its last reader.
    # NOT transitive: in a materialized dataflow chain A→B→C, B's slot
    # captures A's contribution once B's producer fires, so A dies at its
    # last direct consumer; extending A through C (let alone through the
    # output head) left ~98% of dims alive for the whole run and collapsed
    # slot reuse (d_model ≈ num_dims, the pre-M5 compile blew up 4x).
    if consumers is not None:
        for d in all_dims:
            if isinstance(d, InputDimension) or d in protected_slots:
                continue
            max_consumer_phase = -1
            for c in consumers.get(d, set()):
                c_name = None
                if isinstance(c, (ReGLUDimension, PersistDimension)):
                    c_name = c.name
                elif isinstance(c, LookUp):
                    c_name = f"lookup_{c.id}"
                if c_name and c_name in plan_phases:
                    li, pi = plan_phases[c_name]
                    ph = 4 * li + pi
                    if ph > max_consumer_phase:
                        max_consumer_phase = ph
            if max_consumer_phase >= 0:
                death[d] = max_consumer_phase + 1
            else:
                death[d] = birth.get(d, 0)  # never consumed → no lifetime
    else:
        for d in all_dims:
            if isinstance(d, InputDimension) or d in protected_slots:
                continue
            death[d] = P

    # Default for any remaining dims
    for d in all_dims:
        if d not in death:
            death[d] = P

    # ── 3c. Output dims live until the end ──
    # The output head reads the residual stream after ALL layers. Output dims
    # must not have their slots reused, so extend their death to P.
    if output_dims:
        for od in output_dims:
            if od in death:
                death[od] = P

    # ── 3c2. Late-stage dims live until the end ──
    # REMOVED: This caused unexpected side effects on slot allocation.
    #
    # 3c3 (transitive dependencies of output dims extended to P) is also
    # REMOVED: the output head reads only the dims named directly in the
    # output token expressions (protected by 3c). An intermediate dim
    # feeding an output dim through a lookup/Persist chain is captured by
    # that consumer's own slot once it fires; extending it to P was the
    # main driver of the d_model blow-up (see death comment above).

    # ── 3c2. Late-stage dims live until the end ──
    # REMOVED: This caused unexpected side effects on slot allocation.

    # ── 3b. Transitive input extension ──
    # REMOVED: This step extended the lifetime of 70%+ of all dims to cover
    # output dim births, preventing slot reuse and inflating d_model from
    # ~300 to ~1200. The output dim slot protection in step 5 is sufficient.

    # ── 4. Greedy interval coloring (layer granularity) ─────────
    # Writes are additive (x += attn_out / ff_out) and the erase masks only
    # fire when the previous writer of a slot lives in an EARLIER layer, so
    # a slot's consecutive writers must sit in strictly increasing layers.
    # Occupancy is therefore the closed layer interval
    # [birth//4, (death-1)//4]; a slot is free for a writer born in layer
    # L only when its previous occupant died in a layer < L.
    intervals = []
    for d in all_dims:
        if d in protected_slots or d in slot_of:
            continue
        b = birth.get(d, 0)
        de = min(death.get(d, P), P)
        lo = b // 4
        hi = max(lo, (de - 1) // 4)
        intervals.append((lo, hi, d))

    intervals.sort(key=lambda x: (x[0], x[1]))

    import heapq
    free_heap = []
    next_slot = 4

    for lo, hi, d in intervals:
        freed = []
        while free_heap and free_heap[0][0] < lo:
            freed.append(heapq.heappop(free_heap))
        if freed:
            # reuse the lowest-numbered free slot; push the rest back with
            # their ORIGINAL key — re-keying to `lo` would lock them against
            # every same-layer candidate (the churn bug that collapsed
            # reuse to ~1 slot/layer and blew d_model up to ~num_dims)
            _, slot = min(freed, key=lambda ks: ks[1])
            for k, s in freed:
                if s != slot:
                    heapq.heappush(free_heap, (k, s))
        else:
            slot = next_slot
            next_slot += 1

        slot_of[d] = slot
        heapq.heappush(free_heap, (hi, slot))

    # Assign any remaining dims that were missed
    for d in all_dims:
        if d not in slot_of:
            slot_of[d] = next_slot
            next_slot += 1

    return slot_of

    # ── 5/6. (removed) ──
    # Step 5 (MAX_WRITES_PER_SLOT=2) was a blunt anti-corruption guard from
    # the pre-MILP era: with erase masks firing before every cross-layer
    # write (guaranteed by the layer-granularity coloring above), any
    # number of consecutive writers per slot is safe, and the cap collapsed
    # reuse on wide graphs (every 3rd dim got a fresh slot).
    # Step 6 needed no code: output dims have death=P (step 3c), so the
    # coloring already prevents their slots from being reused.

    return slot_of


# ─── Save/Load ───────────────────────────────────────────────────────────


def save_weights(model: LeanTransformer, all_tokens: List[str], path: str):
    """Save model weights as a flat binary file.

    Matches transformer-vm's binary format for compatibility.
    """
    n_layers = len(model.attn_layers)
    with open(path, "wb") as f:
        f.write(struct.pack(
            "<6i",
            len(all_tokens),
            model.d_model,
            n_layers,
            model.n_heads,
            model.d_ffn,
            model.stop_token_id,
        ))
        for t in all_tokens:
            b = t.encode()
            f.write(struct.pack("<I", len(b)))
            f.write(b)

        def W(t):
            f.write(t.detach().contiguous().cpu().to(torch.float64).numpy().tobytes())

        W(model.tok_embedding.weight)
        for li in range(n_layers):
            attn = model.attn_layers[li]
            if hasattr(attn, 'q_weight'):
                # CompactAttention: save q, k, v, out weights
                W(attn.q_weight)
                W(attn.k_weight)
                W(attn.v_weight)
                W(attn.out_weight)
            else:
                # Legacy MultiheadAttention
                W(attn.in_proj_weight)
                W(attn.out_proj.weight)
            W(model.ff_in[li].weight)
            W(model.ff_out[li].weight)
        W(model.head.weight)

        # Erase and tie-break metadata
        has_erase = hasattr(model, "attn_erase") and len(model.attn_erase) > 0
        f.write(struct.pack("<i", 1 if has_erase else 0))
        if has_erase:
            for li in range(n_layers):
                ae = model.attn_erase[li] if li < len(model.attn_erase) else []
                f.write(struct.pack("<i", len(ae)))
                for s in ae:
                    f.write(struct.pack("<i", s))
                fe = model.ffn_erase[li] if li < len(model.ffn_erase) else []
                f.write(struct.pack("<i", len(fe)))
                for s in fe:
                    f.write(struct.pack("<i", s))

        has_tiebreak = hasattr(model, "head_tiebreak") and len(model.head_tiebreak) > 0
        f.write(struct.pack("<i", 1 if has_tiebreak else 0))
        if has_tiebreak:
            H = model.n_heads
            for li in range(n_layers):
                tb = model.head_tiebreak[li] if li < len(model.head_tiebreak) else [0] * H
                for h in range(H):
                    f.write(struct.pack("<i", tb[h] if h < len(tb) else 0))

        # Runner metadata (Phase 4 C++ engine): the head is an identity
        # readout of output persist dims and the input row is the token's
        # 7 fields placed into compiled slots — the engine needs both maps.
        meta = getattr(model, "runner_meta", None)
        f.write(struct.pack("<i", 1 if meta is not None else 0))
        if meta is not None:
            field_items = sorted(meta["field_slots"].items())
            f.write(struct.pack("<i", len(field_items)))
            for name, slot in field_items:
                b = name.encode()
                f.write(struct.pack("<i", len(b)))
                f.write(b)
                f.write(struct.pack("<i", slot))
            f.write(struct.pack("<i", meta["one_slot"]))
            out_items = sorted(meta["output_index"].items())
            f.write(struct.pack("<i", len(out_items)))
            for name, idx in out_items:
                b = name.encode()
                f.write(struct.pack("<i", len(b)))
                f.write(b)
                f.write(struct.pack("<i", idx))

    logger.info("Saved weights to %s", path)


def save_weights_sparse(model: LeanTransformer, all_tokens: List[str],
                        path: str):
    """Save the engine-facing weights as a CSR-sparse binary ("L4SV" v1).

    The analytic construction leaves all but a handful of the model's
    entries exactly 0.0, so the dense file is ~40 GB of zeros on disk that
    the C++ engine re-reads (and re-sparsifies) on every invocation. This
    format stores only the nonzeros — the engine mmaps it and is ready in
    milliseconds. The embedding matrix is omitted (the engine never reads
    it: input fields go straight into residual slots).

    Layout (little-endian):
      magic "L4SV" | int32 version=1
      <6i header: vocab, d_model, n_layers, n_heads, d_ffn, stop_token_id>
      token names: int32 len + bytes, × vocab
      matrices in order q,k,v,out × layers, then ff_in, ff_out × layers,
        then head; each: int32 rows, int32 cols, int64 nnz,
        int64 ptr[rows+1], int32 col[nnz], f64 val[nnz]
      erase / tiebreak / runner-meta tail: identical to save_weights.
    """
    import numpy as np

    def csr_bytes(t: torch.Tensor) -> bytes:
        a = t.detach().contiguous().cpu().to(torch.float64).numpy()
        rows, cols = a.shape
        flat = a.reshape(-1)
        idx = np.flatnonzero(flat)
        nnz = int(idx.size)
        counts = np.bincount(idx // cols, minlength=rows)
        ptr = np.zeros(rows + 1, dtype=np.int64)
        np.cumsum(counts, out=ptr[1:])
        out = struct.pack("<iiq", rows, cols, nnz)
        out += ptr.tobytes()
        if nnz:
            out += (idx % cols).astype(np.int32).tobytes()
            out += flat[idx].astype(np.float64).tobytes()
        return out

    n_layers = len(model.attn_layers)
    parts = [b"L4SV", struct.pack("<i", 1),
             struct.pack("<6i", len(all_tokens), model.d_model, n_layers,
                         model.n_heads, model.d_ffn, model.stop_token_id)]
    for t in all_tokens:
        b = t.encode()
        parts.append(struct.pack("<I", len(b)))
        parts.append(b)
    for li in range(n_layers):
        attn = model.attn_layers[li]
        if not hasattr(attn, "q_weight"):
            raise ValueError("sparse format supports CompactAttention only")
        for m in (attn.q_weight, attn.k_weight, attn.v_weight,
                  attn.out_weight, model.ff_in[li].weight,
                  model.ff_out[li].weight):
            parts.append(csr_bytes(m))
    parts.append(csr_bytes(model.head.weight))

    has_erase = hasattr(model, "attn_erase") and len(model.attn_erase) > 0
    tail = [struct.pack("<i", 1 if has_erase else 0)]
    if has_erase:
        for li in range(n_layers):
            ae = model.attn_erase[li] if li < len(model.attn_erase) else []
            tail.append(struct.pack("<i", len(ae)))
            tail.extend(struct.pack("<i", s) for s in ae)
            fe = model.ffn_erase[li] if li < len(model.ffn_erase) else []
            tail.append(struct.pack("<i", len(fe)))
            tail.extend(struct.pack("<i", s) for s in fe)
    has_tiebreak = (hasattr(model, "head_tiebreak")
                    and len(model.head_tiebreak) > 0)
    tail.append(struct.pack("<i", 1 if has_tiebreak else 0))
    if has_tiebreak:
        H = model.n_heads
        for li in range(n_layers):
            tb = (model.head_tiebreak[li]
                  if li < len(model.head_tiebreak) else [0] * H)
            for h in range(H):
                tail.append(struct.pack("<i", tb[h] if h < len(tb) else 0))
    meta = getattr(model, "runner_meta", None)
    tail.append(struct.pack("<i", 1 if meta is not None else 0))
    if meta is not None:
        field_items = sorted(meta["field_slots"].items())
        tail.append(struct.pack("<i", len(field_items)))
        for name, slot in field_items:
            b = name.encode()
            tail.append(struct.pack("<i", len(b)))
            tail.append(b)
            tail.append(struct.pack("<i", slot))
        tail.append(struct.pack("<i", meta["one_slot"]))
        out_items = sorted(meta["output_index"].items())
        tail.append(struct.pack("<i", len(out_items)))
        for name, idx in out_items:
            b = name.encode()
            tail.append(struct.pack("<i", len(b)))
            tail.append(b)
            tail.append(struct.pack("<i", idx))
    parts.extend(tail)

    with open(path, "wb") as f:
        for p in parts:
            f.write(p)
    logger.info("Saved sparse weights to %s", path)


def _smat_csr_bytes(m: "SparseMatrix") -> bytes:
    """Serialize a SparseMatrix to the CSR blob used in the .sbin format.

    Same encoding as ``csr_bytes``: rows/cols/nnz header, int64 ptr, int32
    col, float64 val; within a row columns ascend (np.flatnonzero order).
    """
    import numpy as np

    ptr = np.zeros(m.rows + 1, dtype=np.int64)
    cols: List[int] = []
    vals: List[float] = []
    for i in range(m.rows):
        row = m.row_data.get(i)
        if row:
            for j in sorted(row):
                cols.append(j)
                vals.append(row[j])
        ptr[i + 1] = len(cols)
    nnz = len(cols)
    out = struct.pack("<iiq", m.rows, m.cols, nnz)
    out += ptr.tobytes()
    if nnz:
        out += np.asarray(cols, dtype=np.int32).tobytes()
        out += np.asarray(vals, dtype=np.float64).tobytes()
    return out


def save_sparse_native(model: "SparseLeanModel", all_tokens: List[str],
                       path: str) -> int:
    """Write a SparseLeanModel straight to an "L4SV" v2 .sbin (H1/H2).

    Unlike ``save_weights_sparse`` (which CSR-ises dense tensors), this
    serializes the analytic construction directly from the SparseMatrix
    dicts — the dense grid is never allocated.  Returns the total nnz.

    v2 adds a per-layer head-count array (int32 × n_layers) immediately
    after the 6-int header; every layer's q/k/v are (2*H_li, D), out is
    (D, 2*H_li).  v1 files stay readable by the engine (global H).
    """
    n_layers = model.n_layers
    parts = [b"L4SV", struct.pack("<i", 2),
             struct.pack("<6i", len(all_tokens), model.d_model, n_layers,
                         model.n_heads, model.d_ffn, model.stop_token_id)]
    for h in model.layer_heads:
        parts.append(struct.pack("<i", int(h)))
    for t in all_tokens:
        b = t.encode()
        parts.append(struct.pack("<I", len(b)))
        parts.append(b)
    for li in range(n_layers):
        attn = model.attn_layers[li]
        for m in (attn.q_weight, attn.k_weight, attn.v_weight,
                  attn.out_weight, model.ff_in[li].weight,
                  model.ff_out[li].weight):
            parts.append(_smat_csr_bytes(m))
    parts.append(_smat_csr_bytes(model.head.weight))

    has_erase = hasattr(model, "attn_erase") and len(model.attn_erase) > 0
    tail = [struct.pack("<i", 1 if has_erase else 0)]
    if has_erase:
        for li in range(n_layers):
            ae = model.attn_erase[li] if li < len(model.attn_erase) else []
            tail.append(struct.pack("<i", len(ae)))
            tail.extend(struct.pack("<i", s) for s in ae)
            fe = model.ffn_erase[li] if li < len(model.ffn_erase) else []
            tail.append(struct.pack("<i", len(fe)))
            tail.extend(struct.pack("<i", s) for s in fe)
    has_tiebreak = (hasattr(model, "head_tiebreak")
                    and len(model.head_tiebreak) > 0)
    tail.append(struct.pack("<i", 1 if has_tiebreak else 0))
    if has_tiebreak:
        H = model.n_heads
        for li in range(n_layers):
            tb = (model.head_tiebreak[li]
                  if li < len(model.head_tiebreak) else [0] * H)
            for h in range(H):
                tail.append(struct.pack("<i", tb[h] if h < len(tb) else 0))
    meta = getattr(model, "runner_meta", None)
    tail.append(struct.pack("<i", 1 if meta is not None else 0))
    if meta is not None:
        field_items = sorted(meta["field_slots"].items())
        tail.append(struct.pack("<i", len(field_items)))
        for name, slot in field_items:
            b = name.encode()
            tail.append(struct.pack("<i", len(b)))
            tail.append(b)
            tail.append(struct.pack("<i", slot))
        tail.append(struct.pack("<i", meta["one_slot"]))
        out_items = sorted(meta["output_index"].items())
        tail.append(struct.pack("<i", len(out_items)))
        for name, idx in out_items:
            b = name.encode()
            tail.append(struct.pack("<i", len(b)))
            tail.append(b)
            tail.append(struct.pack("<i", idx))
    parts.extend(tail)

    with open(path, "wb") as f:
        for p in parts:
            f.write(p)
    logger.info("Saved sparse-native (v2) weights to %s (%d nnz)",
                path, model.nnz())
    return model.nnz()


def load_weights(path: str) -> Tuple[LeanTransformer, List[str], Dict[str, int]]:
    """Load model weights from a binary file."""
    with open(path, "rb") as f:
        vocab, d_model, n_layers, n_heads, d_ffn, stop_token_id = (
            struct.unpack("<6i", f.read(24))
        )

        all_tokens = []
        for _ in range(vocab):
            slen = struct.unpack("<I", f.read(4))[0]
            all_tokens.append(f.read(slen).decode())
        tok_to_idx = {t: i for i, t in enumerate(all_tokens)}

        model = LeanTransformer(
            vocab_size=vocab,
            d_model=d_model,
            n_heads=n_heads,
            n_layers=n_layers,
            d_ffn=d_ffn,
            stop_token_id=stop_token_id,
        )

        def R(shape):
            import numpy as np
            n = 1
            for s in shape:
                n *= s
            data = np.frombuffer(f.read(n * 8), dtype=np.float64)
            return torch.from_numpy(data.copy()).reshape(shape)

        with torch.no_grad():
            model.tok_embedding.weight.copy_(R((vocab, d_model)))
            attn0 = model.attn_layers[0]
            if hasattr(attn0, 'q_weight'):
                # CompactAttention format: q, k, v, out per layer
                for li in range(n_layers):
                    a = model.attn_layers[li]
                    a.q_weight.copy_(R((a._qkv_dim, d_model)))
                    a.k_weight.copy_(R((a._qkv_dim, d_model)))
                    a.v_weight.copy_(R((a._qkv_dim, d_model)))
                    a.out_weight.copy_(R((d_model, a._qkv_dim)))
                    model.ff_in[li].weight.copy_(R((2 * d_ffn, d_model)))
                    model.ff_out[li].weight.copy_(R((d_model, d_ffn)))
            else:
                for li in range(n_layers):
                    model.attn_layers[li].in_proj_weight.copy_(R((3 * d_model, d_model)))
                    model.attn_layers[li].out_proj.weight.copy_(R((d_model, d_model)))
                    model.ff_in[li].weight.copy_(R((2 * d_ffn, d_model)))
                    model.ff_out[li].weight.copy_(R((d_model, d_ffn)))
            model.head.weight.copy_(R((vocab, d_model)))

        # Load metadata
        has_erase = struct.unpack("<i", f.read(4))[0]
        if has_erase:
            model.attn_erase = []
            model.ffn_erase = []
            for _ in range(n_layers):
                ae_len = struct.unpack("<i", f.read(4))[0]
                ae = [struct.unpack("<i", f.read(4))[0] for _ in range(ae_len)]
                model.attn_erase.append(ae)
                fe_len = struct.unpack("<i", f.read(4))[0]
                fe = [struct.unpack("<i", f.read(4))[0] for _ in range(fe_len)]
                model.ffn_erase.append(fe)

        # tiebreak section (written by save_weights; previously unread here)
        has_tiebreak = struct.unpack("<i", f.read(4))[0]
        if has_tiebreak:
            H = model.n_heads
            model.head_tiebreak = []
            for _ in range(n_layers):
                model.head_tiebreak.append(
                    [struct.unpack("<i", f.read(4))[0] for _ in range(H)])

        # runner metadata section (Phase 4 C++ engine)
        has_meta = struct.unpack("<i", f.read(4))[0]
        if has_meta:
            fs = {}
            for _ in range(struct.unpack("<i", f.read(4))[0]):
                nb = struct.unpack("<i", f.read(4))[0]
                name = f.read(nb).decode()
                slot = struct.unpack("<i", f.read(4))[0]
                fs[name] = slot
            one_slot = struct.unpack("<i", f.read(4))[0]
            oi = {}
            for _ in range(struct.unpack("<i", f.read(4))[0]):
                nb = struct.unpack("<i", f.read(4))[0]
                name = f.read(nb).decode()
                idx = struct.unpack("<i", f.read(4))[0]
                oi[name] = idx
            model.runner_meta = {
                "field_slots": fs, "one_slot": one_slot,
                "output_index": oi,
            }

        return model, all_tokens, tok_to_idx


def count_parameters(model: LeanTransformer) -> int:
    """Count total number of trainable parameters."""
    return sum(p.numel() for p in model.parameters())