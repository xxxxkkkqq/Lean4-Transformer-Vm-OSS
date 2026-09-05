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

        attn = torch.softmax(scores, dim=-1)
        out = torch.matmul(attn, v)  # (B, H, T, dh)
        out = out.transpose(1, 2).contiguous().view(B, T, H * dh)
        result = out @ self.out_weight.t()  # (B, T, D)
        return result, None


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

        for li in range(self.n_layers):
            # ── Erase slots before attention (stale values from previous layers) ──
            if li < len(self.attn_erase) and self.attn_erase[li]:
                for slot in self.attn_erase[li]:
                    if 0 <= slot < D:
                        x[..., slot] = 0.0

            # Attention sublayer (causal)
            attn_out, _ = self.attn_layers[li](x, x, x, attn_mask=causal_mask)
            x = x + attn_out

            # FFN sublayer (ReGLU): read first, then erase stale slots, then write
            gate_out = self.ff_in[li](x)  # read phase
            gate, val = gate_out.chunk(2, dim=-1)
            act = torch.relu(gate) * val
            # Prevent ReGLU overflow: when gate and val both read from large
            # hidden state values, their product can be enormous (e.g., 133*133=17689).
            # Clamp each neuron's output to a reasonable range.
            act = torch.clamp(act, min=-1000.0, max=1000.0)

            # ── Erase reused slots AFTER read, BEFORE write ──
            if li < len(self.ffn_erase) and self.ffn_erase[li]:
                for slot in self.ffn_erase[li]:
                    if 0 <= slot < D:
                        x[..., slot] = 0.0

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

        for li in range(self.n_layers):
            if li < len(self.attn_erase) and self.attn_erase[li]:
                for slot in self.attn_erase[li]:
                    if 0 <= slot < D:
                        x[..., slot] = 0.0

            attn_out, _ = self.attn_layers[li](x, x, x, attn_mask=causal_mask)
            x = x + attn_out

            gate_out = self.ff_in[li](x)
            gate, val = gate_out.chunk(2, dim=-1)
            act = torch.relu(gate) * val
            act = torch.clamp(act, min=-1000.0, max=1000.0)

            if li < len(self.ffn_erase) and self.ffn_erase[li]:
                for slot in self.ffn_erase[li]:
                    if 0 <= slot < D:
                        x[..., slot] = 0.0

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

    Uses lifetime information (birth = producer phase, death = max consumer
    phase + 1) to reuse slots across layers when dimensions have non-overlapping
    lifetimes. The +1 in death ensures no same-layer slot reuse, which avoids
    the erase-timing issue: the erase happens at the sublayer boundary *after*
    the read phase and *before* the write phase, so stale values from a previous
    layer are cleared before the new sublayer reads.

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

    # Non-input dims: death = max TRANSITIVE consumer phase + 1
    # The +1 ensures no same-layer slot reuse. We must consider TRANSITIVE
    # consumers because a dim's value must survive until ALL downstream
    # consumers (direct or transitive) have read it. For a chain
    # A→B→C→D, A's value must survive until D reads it, not just until B reads it.
    if consumers is not None:
        # Build transitive consumer map: for each dim, find all transitive consumers
        transitive_consumers: Dict = {}
        for d in all_dims:
            if isinstance(d, InputDimension) or d in protected_slots:
                continue
            # Compute transitive closure of consumers
            visited = set()
            stack = list(consumers.get(d, set()))
            all_cons = set()
            while stack:
                c = stack.pop()
                if c in visited:
                    continue
                visited.add(c)
                all_cons.add(c)
                # Add c's consumers
                for cc in consumers.get(c, set()):
                    if cc not in visited:
                        stack.append(cc)
            transitive_consumers[d] = all_cons

        for d in all_dims:
            if isinstance(d, InputDimension) or d in protected_slots:
                continue
            all_cons = transitive_consumers.get(d, set())
            if all_cons:
                max_consumer_phase = -1
                for c in all_cons:
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
                    # death = max transitive consumer phase + 1 (safe cross-layer reuse)
                    death[d] = max_consumer_phase + 1
                else:
                    death[d] = birth.get(d, 0)  # never consumed → no lifetime
            else:
                death[d] = birth.get(d, 0)  # never consumed → no lifetime

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

    # ── 3c3. Extend death of all transitive dependencies of output dims ──
    # If an output dim lives until the end, all dims it depends on (transitively)
    # must also live until the end, otherwise their slots could be reused and
    # their values lost before the output is computed.
    if output_dims and consumers is not None:
        # Build forward dependency map: dim -> set of dims it directly depends on
        fwd_deps: Dict = {}
        for d in all_dims:
            if isinstance(d, ReGLUDimension):
                deps = set()
                for expr in (d.a_expr, d.b_expr):
                    if isinstance(expr, Expression):
                        for td in expr.terms:
                            deps.add(td)
                if deps:
                    fwd_deps[d] = deps
            if isinstance(d, PersistDimension):
                if isinstance(getattr(d, 'expr', None), Expression):
                    deps = set(d.expr.terms.keys())
                    if deps:
                        fwd_deps[d] = deps
            if isinstance(d, LookUpDimension):
                deps = set(d.lookup.dims)
                if deps:
                    fwd_deps[d] = deps

        # For each output dim, walk forward through its dependencies
        # and extend their death to match the output dim's death (P)
        for od in output_dims:
            if od in death:
                od_death = death[od]
                visited = set()
                stack = [od]
                while stack:
                    cur = stack.pop()
                    if cur in visited:
                        continue
                    visited.add(cur)
                    if cur in fwd_deps:
                        for dep in fwd_deps[cur]:
                            if dep in death and death[dep] < od_death:
                                death[dep] = od_death
                            if dep not in visited:
                                stack.append(dep)

    # ── 3c2. Late-stage dims live until the end ──
    # REMOVED: This caused unexpected side effects on slot allocation.

    # ── 3b. Transitive input extension ──
    # REMOVED: This step extended the lifetime of 70%+ of all dims to cover
    # output dim births, preventing slot reuse and inflating d_model from
    # ~300 to ~1200. The output dim slot protection in step 5 is sufficient.

    # ── 4. Greedy interval coloring ─────────────────────────────
    intervals = []
    for d in all_dims:
        if d in protected_slots or d in slot_of:
            continue
        b = birth.get(d, 0)
        de = death.get(d, P)
        if de > b:
            intervals.append((b, de, d))

    intervals.sort(key=lambda x: (x[0], x[1]))

    import heapq
    free_heap = []
    next_slot = 4

    for b, de, d in intervals:
        freed = []
        while free_heap and free_heap[0][0] <= b:
            freed.append(heapq.heappop(free_heap)[1])

        if freed:
            slot = min(freed)
            for s in freed:
                if s != slot:
                    heapq.heappush(free_heap, (b, s))
        else:
            slot = next_slot
            next_slot += 1

        slot_of[d] = slot
        heapq.heappush(free_heap, (de, slot))

    # Assign any remaining dims that were missed
    for d in all_dims:
        if d not in slot_of:
            slot_of[d] = next_slot
            next_slot += 1

    # ── 5. Write-count limiting ──
    # The residual stream accumulates writes per slot.  Interval coloring
    # considers lifetimes non-overlapping as "safe" reuse, but >2 writers
    # per slot on a shared accumulator causes erasure or saturation.
    # Limit each slot to MAX_WRITES_PER_SLOT writers (skip protected 0-3).
    MAX_WRITES_PER_SLOT = 2
    slot_write_count: Dict[int, int] = defaultdict(int)
    for d, slot in slot_of.items():
        slot_write_count[slot] += 1
    for slot, count in list(slot_write_count.items()):
        if count > MAX_WRITES_PER_SLOT and slot >= 4:
            excess_dims = [d for d, s in slot_of.items() if s == slot]
            for d in excess_dims[MAX_WRITES_PER_SLOT:]:
                slot_of[d] = next_slot
                next_slot += 1

    # ── 6. Output dim protection ──
    # Output dims now have death=P (step 3c), so interval coloring already
    # prevents their slots from being reused. No post-processing needed.

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