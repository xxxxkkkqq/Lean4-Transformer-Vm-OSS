"""Step driver (VM_SPEC §10.3): autoregressive execution of the step graph.

Phase 2 driver = eval_graph_sequence replay. The Phase 3 runner swaps this
for the real transformer forward pass; the graph is unchanged.

Emission order contract (build_vm docstring): raw, pend, link, link2,
litdig, frame, frame2, lithead, gap, litdig2, const — then the STATE token.
The raw slot (Phase 5 M2) emits an arbitrary token kind (T_PI_CLO, level
chain nodes, the second PEND chain of a spine peel) and is addressed at
POS+1 when present.
"""
from __future__ import annotations

from typing import Dict

from lean_kernel.alm_graph import (
    Expression, InputDimension, PersistDimension,
)
from lean_kernel.alm_p2 import IncrementalGraphEvaluator

from expr.tokens import (
    StreamBundle, T_PEND, T_LINK, T_STATE, T_FRAME, T_LIT_DIG, K_LIT,
    K_CONST, LIT_NAT, T_REJECT, T_HALT, TASK_INFER, TASK_DEFEQ,
)
from lean_vm.ref_vm import VMError


class StepDriver:
    """Runs build_vm's step graph over a growing token stream."""

    def __init__(self, bundle: StreamBundle, graph, outputs):
        self.b = bundle
        self.graph = graph
        self.out = outputs
        self.dims: Dict[str, InputDimension] = {
            d.name: d for d in graph.all_dims if isinstance(d, InputDimension)}
        assert all(isinstance(v, PersistDimension) for v in outputs.values())
        self.names: list[str] = []
        for i, t in enumerate(self.b.stream):
            self.names.append(f"t{i}")
            self.graph.input_tokens[f"t{i}"] = self._tok_expr(*t)
        self.steps = 0
        self._eval = IncrementalGraphEvaluator(graph)

    def _tok_expr(self, K, V0=0, V1=0, V2=0, X=0, E2=0, F2=0):
        e = Expression()
        for name, val in (("k", K), ("v0", V0), ("v1", V1), ("v2", V2),
                          ("x", X), ("e2", E2), ("f2", F2)):
            if val:
                e = e + Expression({self.dims[name]: val})
        return e

    def init_state(self, A, B=0, C=0, D=0, E=0, F=0):
        # register any stream tokens appended after construction (e.g. the
        # proof tree encoded after StepDriver was built)
        for i in range(len(self.names), len(self.b.stream)):
            K, V0, V1, V2, X, E2, F2 = self.b.stream[i]
            self.names.append(f"t{i}")
            self.graph.input_tokens[f"t{i}"] = self._tok_expr(
                K, V0, V1, V2, X, E2, F2)
        self._append(T_STATE, A, B, C, D, E, F)

    def _append(self, K, V0=0, V1=0, V2=0, X=0, E2=0, F2=0):
        # register any stream tokens appended externally (e.g. terms encoded
        # after construction) so names stay aligned with stream indices
        for i in range(len(self.names), len(self.b.stream)):
            k0, v0, v1, v2, x0, e0, f0 = self.b.stream[i]
            self.names.append(f"t{i}")
            self.graph.input_tokens[f"t{i}"] = self._tok_expr(
                k0, v0, v1, v2, x0, e0, f0)
        name = f"t{len(self.names)}"
        self.names.append(name)
        self.graph.input_tokens[name] = self._tok_expr(K, V0, V1, V2, X, E2, F2)
        self.b.stream.append((K, V0, V1, V2, X, E2, F2))
        return len(self.names) - 1

    def _val(self, vals, name):
        return int(round(vals[self.out[name]]))

    def step(self) -> tuple[bool, tuple[int, int]]:
        """One micro-step. Returns (done, (A, B)) — the result closure when
        done."""
        vals = self._eval.sync(self.names)
        done = self._val(vals, "done")
        A = self._val(vals, "A")
        B = self._val(vals, "B")
        if done:
            return True, (self._val(vals, "result_pos"), B)
        if self._val(vals, "reject"):
            code = self._val(vals, "reject_code")
            self._append(T_REJECT, V0=code)
            self._append(T_HALT)
            raise VMError(code, "step graph reject")
        # emission order contract: raw, pend, link, link2, litdig, frame,
        # frame2, lithead, gap, litdig2, const — then the STATE token
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
                  max_steps: int = 10000) -> tuple[int, int]:
        """Run a T_INFER task. Returns the type closure (pos, env)."""
        fpos = self._append(T_FRAME, V0=TASK_INFER, V2=0, X=0, E2=1)
        self.init_state(term_pos, env, D=fpos)
        return self._run_loop(max_steps)

    def run_defeq(self, t_pos: int, t_env: int, s_pos: int, s_env: int,
                  max_steps: int = 10000) -> tuple[int, int]:
        """Run a T_DEFEQ task. Returns (verdict, 0)."""
        fpos = self._append(T_FRAME, V0=TASK_DEFEQ, V1=t_pos, X=t_env,
                            E2=s_pos, F2=s_env)
        self.init_state(t_pos, t_env, D=fpos, E=s_pos, F=s_env)
        return self._run_loop(max_steps)
