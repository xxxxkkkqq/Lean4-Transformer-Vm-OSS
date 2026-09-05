"""WeightRunner (Phase 3): the StepDriver contract executed by real weights.

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

import torch

from expr.tokens import (
    T_PEND, T_LINK, T_STATE, T_FRAME, T_LIT_DIG, K_LIT, K_CONST, LIT_NAT,
)


class WeightRunner:
    """Runs the compiled step weights over a growing token stream."""

    def __init__(self, bundle, model, meta: dict):
        self.b = bundle
        self.model = model.eval()
        self.out = meta["output_index"]      # output name -> head row
        self.fs = meta["field_slots"]        # 'k','v0',... -> slot
        self.one_slot = meta["one_slot"]
        self.D = model.d_model
        # Cache one residual row per stream token; the stream only grows by
        # append, so step() stacks a list instead of re-encoding O(T) tokens.
        self._rows = [self._row(t) for t in self.b.stream]
        self.steps = 0

    # ── input-row construction ──────────────────────────────────────────

    @staticmethod
    def _fields(t):
        t = tuple(t)
        return t + (0,) * (7 - len(t))

    def _row(self, tok) -> torch.Tensor:
        K, V0, V1, V2, X, E2, F2 = self._fields(tok)
        row = torch.zeros(self.D)
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
        self._append(T_STATE, A, B, C, D, E, F)

    def _append(self, K, V0=0, V1=0, V2=0, X=0, E2=0, F2=0):
        self.b.stream.append((K, V0, V1, V2, X, E2, F2))
        self._rows.append(self._row((K, V0, V1, V2, X, E2, F2)))
        return len(self.b.stream) - 1

    # ── micro-step ──────────────────────────────────────────────────────

    def _forward_last(self) -> dict:
        x = torch.stack(self._rows).unsqueeze(0)  # (1, T, D)
        logits = self.model.forward_stream(x)
        last = logits[0, -1]
        return {name: float(last[idx]) for name, idx in self.out.items()}

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
        # emission order contract (build_vm docstring): pend, link, frame,
        # frame2, lithead, litdig, const — then the STATE token
        if self._val(vals, "em_pend"):
            self._append(T_PEND, V0=self._val(vals, "pend_V0"),
                         V2=self._val(vals, "pend_prev"),
                         X=self._val(vals, "pend_env"))
        if self._val(vals, "em_link"):
            self._append(T_LINK, V0=self._val(vals, "link_V0"),
                         V1=self._val(vals, "link_V1"),
                         V2=self._val(vals, "link_prev"),
                         X=self._val(vals, "link_env"))
        if self._val(vals, "em_litdig"):
            self._append(T_LIT_DIG, V0=self._val(vals, "dig_V0"),
                         V2=self._val(vals, "F"))
        if self._val(vals, "em_frame"):
            self._append(T_FRAME, V0=self._val(vals, "frame_task"),
                         V1=self._val(vals, "frame_V1"),
                         V2=self._val(vals, "frame_V2"),
                         X=self._val(vals, "frame_X"))
        if self._val(vals, "em_frame2"):
            self._append(T_FRAME, V0=self._val(vals, "frame2_task"),
                         V1=self._val(vals, "frame2_V1"),
                         V2=self._val(vals, "frame2_V2"),
                         X=self._val(vals, "frame2_X"))
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

    def run(self, term_pos: int, max_steps: int = 2000) -> tuple[int, int]:
        """Run T_WHNF on a closed term. Returns the result closure (pos, env)."""
        self.init_state(term_pos)
        for _ in range(max_steps):
            done, r = self.step()
            if done:
                return r
        raise TimeoutError(f"no halt after {max_steps} steps")
