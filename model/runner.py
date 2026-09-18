"""WeightRunner (Phase 3): the StepDriver contract executed by real weights.

DEV PROBE ONLY (docs/decisions/005-*.md, 2026-09-14): this runner consumes a
dense torch checkpoint (`model/step_vm.pt`: LeanTransformer + meta with
"output_index"/"field_slots"/"one_slot") that the current graph cannot
produce — dense lowering is ~19GB (docs/HYBRID_ARCH.md §1) and materializing
>1GB checkpoints is barred by AGENTS.md red line 9. No regression or
acceptance path covers this file any more; the weight-side acceptance channel
is `engine/vm_run` + `scripts/verify_engine_vs_refvm.py` on the sparse .sbin.
Do not extend this into a second executor; reviving it as an acceptance
path needs a new ADR.

Same autoregressive loop as lean_vm/step_driver.StepDriver (VM_SPEC §10.3):
each micro-step reads done/result/A..F plus the emission flags off the last
position, appends the emitted tokens in the fixed contract order, then the
next STATE token. The difference is where the per-position values come from:
instead of eval_graph_sequence replay, WeightRunner builds the residual
stream directly — each token's 7 field values go into their compiled slots
(plus one=1.0; position/inv_log_pos/pos² are added by forward_stream) — and
runs LeanTransformer.forward_stream. Output values are read off the head,
whose rows are identity projections onto the output dims' slots.

Token-space note (why no embedding table): a token here is 7 arbitrary
integer fields, not a vocabulary entry, so the runner bypasses
tok_embedding entirely; the head is used only as a linear readout of the
output dims.
"""
from __future__ import annotations

import math

import torch

from compiler.weights import REGLU_CLAMP  # shared clamp constant; importing
# weights.py also pins torch's default dtype to float64 (documented there) —
# the same contract any caller building a LeanTransformer already relies on.
from expr.tokens import (
    T_PEND, T_LINK, T_STATE, T_FRAME, T_LIT_DIG, K_LIT, K_CONST, LIT_NAT,
    T_REJECT, T_HALT, TASK_INFER, TASK_DEFEQ, TASK_CHECK,
)
from lean_vm.ref_vm import VMError


class WeightRunner:
    """Runs the compiled step weights over a growing token stream."""

    def __init__(self, bundle, model, meta: dict, device=None):
        self.b = bundle
        # device=None keeps the Phase-3 CPU default; a device string (e.g.
        # 'cuda') moves the fp64 model there — IEEE fp64 on CUDA is the same
        # precision class as MKL fp64, so the fidelity contract (abs 1e-6 +
        # round-equal) is unchanged by the device.
        self.device = torch.device(device) if device is not None else None
        if self.device is not None:
            model = model.to(self.device)
        self.model = model.eval()
        self.out = meta["output_index"]      # output name -> head row
        self.fs = meta["field_slots"]        # 'k','v0',... -> slot
        self.one_slot = meta["one_slot"]
        self.D = model.d_model
        # Cache one residual row per stream token; the stream only grows by
        # append, so step() stacks a list instead of re-encoding O(T) tokens.
        self._rows = [self._row(t) for t in self.b.stream]
        # Incremental (KV-cache) forward state: positions already pushed
        # through the layers and each layer's cached K/V (H, n, d_head).
        self._kv = None
        self._fwd_pos = 0
        self._last_vals = None
        self._erase_idx = None
        self.steps = 0

    # ── input-row construction ──────────────────────────────────────────

    @staticmethod
    def _fields(t):
        t = tuple(t)
        return t + (0,) * (7 - len(t))

    def _row(self, tok) -> torch.Tensor:
        K, V0, V1, V2, X, E2, F2 = self._fields(tok)
        row = torch.zeros(self.D, dtype=torch.float64,
                          device=self.device or "cpu")
        for name, val in (("k", K), ("v0", V0), ("v1", V1), ("v2", V2),
                          ("x", X), ("e2", E2), ("f2", F2)):
            if val:
                row[self.fs[name]] = float(val)
        # every token populates the `one` slot (build_weights does the same
        # for embeddings; downstream ALM primitives read it)
        row[self.one_slot] = 1.0
        return row

    # ── stream management ───────────────────────────────────────────────

    def init_state(self, A, B=0, C=0, D=0, E=0, F=0):
        # resync cached rows with tokens appended after construction (e.g.
        # the term encoded between WeightRunner construction and init_state;
        # mirrors StepDriver's re-registration logic)
        self._rows = [self._row(t) for t in self.b.stream]
        self._kv = None
        self._fwd_pos = 0
        self._last_vals = None
        self._append(T_STATE, A, B, C, D, E, F)

    def _append(self, K, V0=0, V1=0, V2=0, X=0, E2=0, F2=0):
        self.b.stream.append((K, V0, V1, V2, X, E2, F2))
        self._rows.append(self._row((K, V0, V1, V2, X, E2, F2)))
        return len(self.b.stream) - 1

    # ── micro-step ──────────────────────────────────────────────────────

    def _readout(self, last) -> dict:
        return {name: float(last[idx]) for name, idx in self.out.items()}

    @torch.no_grad()
    def _forward_last(self) -> dict:
        """Logits of the last stream position, incrementally.

        The compiled model is causal and every non-attention op is
        position-wise, so each position's K/V are final once computed; only
        the rows appended since the last call need a forward.  This mirrors
        LeanTransformer.forward_stream exactly (same ops, same order) but
        keeps a per-layer K/V cache, turning a run from O(T^2) forwards
        (forward_stream over the whole prefix each step) into O(T) total.
        New rows are processed as one batch, so a 430-token prefill costs one
        batched pass rather than 430 dispatch-bound single-token passes.

        The non-compact (nn.MultiheadAttention) variant has no K/V cache and
        falls back to the whole-prefix forward.
        """
        m = self.model
        if not getattr(m, "compact_attn", False):
            x = torch.stack(self._rows).unsqueeze(0)
            self._fwd_pos = len(self._rows)
            self._last_vals = self._readout(m.forward_stream(x)[0, -1])
            return self._last_vals

        n_new = len(self._rows) - self._fwd_pos
        if n_new <= 0:
            return self._last_vals

        H, dh = m.n_heads, 2
        scale = math.sqrt(dh)
        C = getattr(m, "tanh_c", 100.0)
        D = self.D
        if self._kv is None:
            self._kv = [None] * m.n_layers
        if self._erase_idx is None:
            # One LongTensor per layer instead of a Python loop per slot:
            # ffn_erase alone lists ~4000 slots across the 98 layers, and a
            # per-slot x[:, slot] = 0.0 cost ~9 s per forward regardless of T.
            dev = self.device or "cpu"
            self._erase_idx = []
            for li in range(m.n_layers):
                a = m.attn_erase[li] if li < len(m.attn_erase) else []
                f = m.ffn_erase[li] if li < len(m.ffn_erase) else []
                self._erase_idx.append((
                    torch.as_tensor(a, dtype=torch.long, device=dev)
                    if a else None,
                    torch.as_tensor(f, dtype=torch.long, device=dev)
                    if f else None))
        # Process new rows in bounded query chunks. A full 2552-token prefill
        # as one batch materializes scores of shape (n_heads, T, T): at
        # n_heads=94, T=2552 that is a ~4.9 GB fp64 tensor per attention layer
        # (plus masked_fill/softmax copies), which both thrashes memory and is
        # cache-hostile. Chunking bounds the scores tensor while computing the
        # same per-query values, so results are unchanged. Only the one-time
        # environment prefill is large; ordinary micro-steps have n_new ~= 1
        # and run a single chunk.
        chunk = 256
        last = None
        live_attn = m._live_attn_layers()
        while self._fwd_pos < len(self._rows):
            p0 = self._fwd_pos
            p1 = min(len(self._rows), p0 + chunk)
            x = torch.stack(self._rows[p0:p1])           # (Tn, D)
            Tn = p1 - p0
            if D >= 4:
                pos = torch.arange(p0, p1, dtype=x.dtype, device=x.device)
                x[:, 1] = x[:, 1] + pos
                x[:, 2] = x[:, 2] + (1.0 / math.log(2.0)
                                     - 1.0 / torch.log(pos + 2.0))
                x[:, 3] = x[:, 3] + pos * pos
            q_idx = torch.arange(p0, p1, dtype=x.dtype, device=x.device)
            k_idx = torch.arange(p1, dtype=x.dtype, device=x.device)
            caus = q_idx[:, None] >= k_idx[None, :]       # (Tn, p1)
            for li in range(m.n_layers):
                attn = m.attn_layers[li]
                a_er, f_er = self._erase_idx[li]
                if a_er is not None:
                    x[:, a_er] = 0.0
                # Attention is skipped entirely when the layer's out_weight is
                # all-zero: the sublayer writes attn @ out_weight.t(), which is
                # identically zero, so the residual stream is unchanged and no
                # K/V needs caching. 89 of 98 layers are dead on the P7.5c
                # graph, and this is the runner's per-step hot path.
                if li in live_attn:
                    q = (x @ attn.q_weight.t()).view(Tn, H, dh).transpose(0, 1)
                    kn = (x @ attn.k_weight.t()).view(Tn, H, dh).transpose(0, 1)
                    vn = (x @ attn.v_weight.t()).view(Tn, H, dh).transpose(0, 1)
                    if self._kv[li] is None:
                        K, V = kn, vn
                    else:
                        K = torch.cat([self._kv[li][0], kn], dim=1)
                        V = torch.cat([self._kv[li][1], vn], dim=1)
                    self._kv[li] = [K, V]
                    scores = (q @ K.transpose(1, 2)) / scale  # (H, Tn, keys)
                    scores = scores.masked_fill(~caus, float("-inf"))
                    if getattr(m, "hard_fetch", True):
                        # LookUpDimension is a discrete fetch, so take the
                        # argmax and gather it exactly instead of approximating
                        # one-hot with a softmax.  A softmax needs the score gap
                        # to dwarf fp error, and the compiler gets that gap by
                        # scaling queries with HARD_K=1e4, which pushes scores to
                        # ~1e9-1e10: representable in fp32/fp64 but overflowing
                        # fp16's 65504 -> inf -> NaN, and quantized to ~1e3
                        # resolution in fp32.  argmax is scale-invariant, so it
                        # needs no exp, no temperature, and no precision margin.
                        idx = scores.argmax(dim=-1)          # (H, Tn)
                        out = V.gather(1, idx.unsqueeze(-1).expand(-1, -1, dh))
                        out = out.transpose(0, 1).reshape(Tn, H * dh)
                    else:
                        a = torch.softmax(scores, dim=-1)
                        out = (a @ V).transpose(0, 1).reshape(Tn, H * dh)
                    x = x + out @ attn.out_weight.t()
                gate, val = m.ff_in[li](x).chunk(2, dim=-1)
                act = torch.clamp(torch.relu(gate) * val,
                                  min=-REGLU_CLAMP, max=REGLU_CLAMP)
                # ffn_erase zeroes residual slots (d_model), not FFN activations
                # (d_ffn) — matches forward_stream: act is read off the pre-erase
                # x, then erased slots drop the FFN output.
                if f_er is not None:
                    x[:, f_er] = 0.0
                x = x + m.ff_out[li](act)
                x = torch.tanh(x / C) * C
            last = x[-1]
            self._fwd_pos = p1
        self._last_vals = self._readout(m.head(last))
        return self._last_vals

    @torch.no_grad()
    def prefill(self):
        """Forward all current rows and return a reusable snapshot.

        The returned ``(kv, n_pos)`` can be passed to run_infer/run_defeq/
        run_check by runners whose stream begins with these same n_pos
        tokens; they then forward only the tokens appended afterwards. The
        snapshot shares the cached K/V tensors read-only (the per-run cache
        update rebinds a copied outer list), so one environment prefill can
        serve many declarations. Returns None when the model has no compact
        K/V path."""
        self._forward_last()
        if self._kv is None:
            return None
        return list(self._kv), self._fwd_pos

    def _apply_prefill(self, prefill) -> None:
        if prefill is not None:
            self._kv = list(prefill[0])
            self._fwd_pos = prefill[1]

    def _val(self, vals, name):
        return int(round(vals[name]))

    def step(self) -> tuple[bool, tuple[int, int]]:
        """One micro-step. Returns (done, (A, B)) — the result closure when
        done."""
        vals = self._forward_last()
        done = self._val(vals, "done")
        A = self._val(vals, "A")
        B = self._val(vals, "B")
        if done:
            return True, (self._val(vals, "result_pos"), B)
        if self._val(vals, "reject"):
            # Mirror StepDriver.step: surface the machine's focus closure at
            # the rejecting micro-step, after emitting T_REJECT/T_HALT so the
            # stream records the verdict.
            code = self._val(vals, "reject_code")
            self._append(T_REJECT, V0=code)
            self._append(T_HALT)
            raise VMError(code, "step graph reject", focus=A, env=B)
        # emission order contract (step_driver.step): raw, pend, link, link2,
        # litdig, frame, frame2, lithead, gap, litdig2, const — then the
        # STATE token.  Link/frame/frame2 carry E2/F2 (binder bid + soft
        # flags) and raw/link2 emissions arrived with P7.5b/c graph work;
        # the Phase-3 runner predated both and diverged on beta/zeta cases.
        if self._val(vals, "em_raw"):
            self._append(self._val(vals, "raw_K"),
                         V0=self._val(vals, "raw_V0"),
                         V1=self._val(vals, "raw_V1"),
                         V2=self._val(vals, "raw_V2"),
                         X=self._val(vals, "raw_X"),
                         E2=self._val(vals, "raw_E2"))
        if self._val(vals, "em_pend"):
            self._append(T_PEND, V0=self._val(vals, "pend_V0"),
                         V2=self._val(vals, "pend_prev"),
                         X=self._val(vals, "pend_env"))
        if self._val(vals, "em_link"):
            self._append(T_LINK, V0=self._val(vals, "link_V0"),
                         V1=self._val(vals, "link_V1"),
                         V2=self._val(vals, "link_prev"),
                         X=self._val(vals, "link_env"),
                         E2=self._val(vals, "link_flag"),
                         F2=self._val(vals, "link_F2"))
        if self._val(vals, "em_link2"):
            self._append(T_LINK, V0=self._val(vals, "link2_V0"),
                         V1=self._val(vals, "link2_V1"),
                         V2=self._val(vals, "link2_prev"),
                         X=self._val(vals, "link2_env"),
                         E2=self._val(vals, "link2_flag"),
                         F2=self._val(vals, "link2_F2"))
        if self._val(vals, "em_litdig"):
            self._append(T_LIT_DIG, V0=self._val(vals, "dig_V0"),
                         V2=self._val(vals, "F"))
        if self._val(vals, "em_frame"):
            self._append(T_FRAME, V0=self._val(vals, "frame_task"),
                         V1=self._val(vals, "frame_V1"),
                         V2=self._val(vals, "frame_V2"),
                         X=self._val(vals, "frame_X"),
                         E2=self._val(vals, "frame_E2"),
                         F2=self._val(vals, "frame_F2"))
        if self._val(vals, "em_frame2"):
            self._append(T_FRAME, V0=self._val(vals, "frame2_task"),
                         V1=self._val(vals, "frame2_V1"),
                         V2=self._val(vals, "frame2_V2"),
                         X=self._val(vals, "frame2_X"),
                         E2=self._val(vals, "frame2_E2"),
                         F2=self._val(vals, "frame2_F2"))
        if self._val(vals, "em_lithead"):
            self._append(K_LIT, V0=self._val(vals, "head_V0"), V1=LIT_NAT,
                         V2=self._val(vals, "head_V2"),
                         X=self._val(vals, "head_X"))
        if self._val(vals, "em_gap"):
            self._append(0)
        if self._val(vals, "em_litdig2"):
            self._append(T_LIT_DIG, V0=self._val(vals, "dig2_V0"),
                         V2=self._val(vals, "F"))
        if self._val(vals, "em_const"):
            self._append(K_CONST, V0=self._val(vals, "const_cid"))
        self._append(T_STATE, A, B, self._val(vals, "C"),
                     self._val(vals, "D"), self._val(vals, "E"),
                     self._val(vals, "F"))
        self.steps += 1
        return False, (A, B)

    def _run_loop(self, max_steps: int) -> tuple[int, int]:
        for _ in range(max_steps):
            done, r = self.step()
            if done:
                return r
        raise TimeoutError(f"no halt after {max_steps} steps")

    def run(self, term_pos: int, max_steps: int = 2000) -> tuple[int, int]:
        """Run T_WHNF on a closed term. Returns the result closure (pos, env)."""
        self.init_state(term_pos)
        return self._run_loop(max_steps)

    def run_infer(self, term_pos: int, env: int = 0,
                  max_steps: int = 10000,
                  prefill=None) -> tuple[int, int]:
        """Run a T_INFER task. Returns the type closure (pos, env).

        ``prefill`` is a snapshot from prefill() covering this runner's stream
        prefix; only tokens appended after it are forwarded."""
        fpos = self._append(T_FRAME, V0=TASK_INFER, V2=0, X=0, E2=1)
        self.init_state(term_pos, env, D=fpos)
        self._apply_prefill(prefill)
        return self._run_loop(max_steps)

    def run_defeq(self, t_pos: int, t_env: int, s_pos: int, s_env: int,
                  max_steps: int = 10000,
                  prefill=None) -> tuple[int, int]:
        """Run a T_DEFEQ task. Returns (verdict, 0)."""
        fpos = self._append(T_FRAME, V0=TASK_DEFEQ, V1=t_pos, X=t_env,
                            E2=s_pos, F2=s_env)
        self.init_state(t_pos, t_env, D=fpos, E=s_pos, F=s_env)
        self._apply_prefill(prefill)
        return self._run_loop(max_steps)

    def run_check(self, decls, max_steps: int = 50000,
                  prefill=None) -> tuple[int, int]:
        """Run the M4.2 CHECK driver loop. decls: list of (type_root,
        val_root) stream positions. CHECK anchor frames (V0=TASK_CHECK,
        V1=declared type, X=value, V2=next anchor) are pushed in reverse so
        the first declaration heads the chain. Returns (1, 0) iff every
        declaration's inferred type is defeq to its declared type; raises
        VMError(ERR_TYPE) on the first mismatch (step() rejects).

        ``prefill`` (see prefill()) lets many single-declaration checks share
        one environment forward."""
        if not decls:
            raise ValueError("run_check: empty declaration list")
        nxt = 0
        for (t_root, v_root) in reversed(decls):
            nxt = self._append(T_FRAME, V0=TASK_CHECK, V1=t_root, V2=nxt,
                               X=v_root)
        self.init_state(decls[0][1], 0, 0, D=nxt)
        self._apply_prefill(prefill)
        return self._run_loop(max_steps)
