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
    K_CONST, LIT_NAT, T_REJECT, T_HALT, TASK_INFER, TASK_DEFEQ, TASK_CHECK,
    Encoder,
    CK_AXIOM, CK_DEFINITION, CK_THEOREM, CK_OPAQUE,
)
from lean_vm.ref_vm import VMError, ERR_MISSING_CONST

# ── card 010 G02: declaration-kind carrier on the TASK_CHECK anchor frame ────
# The kernel dispatches `add_theorem` / `add_axiom` / `add_definition` /
# `add_opaque` on the declaration's kind (K/environment.cpp:271-284) and only
# `add_theorem` runs `is_prop` (:200-202).  The graph cannot tell those four
# apart from the anchor alone, so the anchor frame's free E2 slot carries the
# kind as DATA (acceptance rule 3 — no name/cid branch).  Layout (ENV_FORMAT
# §2.8): E2 = kind_code + CHECK_E2_STRIDE * check_mode_code, with
#   kind_code  0 = unspecified (legacy path: every kind gate must stay inert)
#              1 = axiom  2 = definition  3 = theorem  4 = opaque
#   mode_code  0 = safe checker (legacy default)  1 = unsafe checker
# This beat writes kind_code only (mode_code is always 0 → E2 == kind_code).
CHECK_E2_STRIDE = 8
CHECK_KIND_UNSPECIFIED = 0
CHECK_KIND_AXIOM = 1
CHECK_KIND_DEFINITION = 2
CHECK_KIND_THEOREM = 3
CHECK_KIND_OPAQUE = 4
CHECK_KIND_MAX = 4
CHECK_MODE_SAFE = 0
CHECK_MODE_UNSAFE = 1              # graph side: card 010 G03 (G2-unsafe)


def check_e2(kind_code: int, mode_code: int = CHECK_MODE_SAFE) -> int:
    """Encode the TASK_CHECK anchor's E2 payload (docs/ENV_FORMAT.md §2.8)."""
    if not isinstance(kind_code, int) or isinstance(kind_code, bool):
        raise ValueError(f"kind code must be an int, got {kind_code!r}")
    if not isinstance(mode_code, int) or isinstance(mode_code, bool):
        raise ValueError(f"check mode code must be an int, got {mode_code!r}")
    if not CHECK_KIND_UNSPECIFIED <= kind_code <= CHECK_KIND_MAX:
        raise ValueError(
            f"kind code {kind_code} outside "
            f"{CHECK_KIND_UNSPECIFIED}..{CHECK_KIND_MAX}")
    if mode_code not in (CHECK_MODE_SAFE, CHECK_MODE_UNSAFE):
        raise ValueError(
            f"check mode code {mode_code} not in "
            f"{(CHECK_MODE_SAFE, CHECK_MODE_UNSAFE)}")
    return kind_code + CHECK_E2_STRIDE * mode_code


# Card 010 G6: driver-side bookkeeping reject code (VM_SPEC §16.5).  The graph
# has no name space and no block concept, so mutual-block well-formedness
# (K/environment.cpp:228-248, plain kernel_exception → .other messages) never
# enters the graph: InjectionEnv raises before any graph pass.
ERR_MUTUAL_WF = 9
# Card 011 G8: name-presence bookkeeping reject code (same channel as 9 — the
# graph has no name space, so check_name (K/environment.cpp:102-105, called
# from check_constant_val :128) is decided by the driver before any graph
# pass.  The kernel class is the dedicated constructor
# `already_declared_exception` (K/kernel_exception.h:32-37 → Kernel.Exception
# .alreadyDeclared, catch at :168-169); the driver message mirrors the
# Lean-side rendering "(kernel) constant has already been declared 'n'"
# (src/Lean/Message.lean:896).  Oracle-confirmed 2026-09-21 (handoff 006 G8/G9
# probe): the name check runs inside check_constant_val BEFORE is_prop /
# value checks, so a duplicate name wins over thmTypeIsNotProp (8),
# declTypeMismatch (1) and the G9 duplicate-univ-param reject (10).
ERR_ALREADY_DECLARED = 11


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
            # M4.3: surface the machine's focus closure at the rejecting step
            # (meaningful for node-level rejects like unsupported-kind; a
            # verdict-false reject leaves A=0, which localize() treats as
            # "no node focus" and falls back to the infer-vs-declared diff).
            raise VMError(code, "step graph reject", focus=A, env=B)
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

    def run_whnf(self, term_pos: int, max_steps: int = 2000,
                 max_rounds: int = 16) -> tuple[int, int]:
        """Card 010 G04 (ADR016-B): caller-side whnf-to-head-normal loop.

        The graph's TASK_WHNF delivers a raw field at a proj (the P7.5c-2
        contract, VM_SPEC §11.16), while the kernel's whnf_core feeds a
        successful proj reduction back into whnf_core
        (K/type_checker.cpp:504-508) — its whnf of `t.fst` is the field
        value reduced on.  Plan B keeps the graph contract frozen and moves
        that loop to the caller: re-launch TASK_WHNF on the delivered
        closure until the focus stops advancing (pos AND env both
        unchanged).

        No Python semantics: every round is one graph task (the same
        init_state/_run_loop primitives run() uses); this method only
        iterates and judges termination.  Budget discipline per ADR016-B:
        a non-advancing focus is the ONLY stop condition (open/stuck terms
        settle instead of spinning); exhausting max_rounds raises
        TimeoutError — the same type _run_loop raises for the per-round
        budget."""
        pos, env = term_pos, 0
        for _ in range(max_rounds):
            self.init_state(pos, env)
            new_pos, new_env = self._run_loop(max_steps)
            if (new_pos, new_env) == (pos, env):
                return new_pos, new_env
            pos, env = new_pos, new_env
        raise TimeoutError(
            f"run_whnf: focus still advancing after {max_rounds} rounds")

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

    def run_check(self, decls, max_steps: int = 50000,
                  kinds=None, check_mode: int = CHECK_MODE_SAFE,
                  lparams=None) -> tuple[int, int]:
        """Run the M4.2 CHECK driver loop. decls: list of (type_root,
        val_root) stream positions. CHECK anchor frames (V0=TASK_CHECK,
        V1=declared type, X=value, V2=next anchor) are pushed in reverse so
        the first declaration heads the chain. Returns (1, 0) iff every
        declaration's inferred type is defeq to its declared type; raises
        VMError(ERR_TYPE) on the first mismatch (step() rejects).

        kinds (card 010 G02): optional per-declaration kernel declaration-kind
        codes (see `check_e2` / docs/ENV_FORMAT.md §2.8) written into each
        anchor's E2 slot, so the graph can apply the theorem-only `is_prop`
        check (K/environment.cpp:200-202).  `kinds=None` leaves every E2 at 0
        = `CHECK_KIND_UNSPECIFIED`, which keeps the legacy behaviour
        byte-for-byte (all kind gates inert).

        check_mode (card 010 G6): checker-mode code encoded into the same E2
        slot as kind_code + CHECK_E2_STRIDE * mode_code (§2.8 layout).  The
        graph decodes the kind mode-independently (add_theorem always uses a
        SAFE checker, K/environment.cpp:196); the mode arm — unsafe checker
        for unsafe add_definition bodies and mutual blocks, K/environment.cpp
        :167-172/:236/:260 — is card 010 G03 and until then no gate consumes
        the bit, so this is faithful data with no behavioural effect.

        lparams (card 011 G9): optional per-declaration stream positions of
        T_ENV_LIST(role=2) universe-parameter chains (heads from
        `Encoder.emit_univparams`), written into each anchor's F2 slot.  The
        graph's duplicate-param scan (K/environment.cpp:111-121, reject code
        10) walks them; `lparams=None`/head 0 leaves the arm inert exactly as
        before."""
        if not decls:
            raise ValueError("run_check: empty declaration list")
        if kinds is None:
            if check_mode != CHECK_MODE_SAFE:
                raise ValueError(
                    "run_check: check_mode requires kinds (the kinds=None "
                    "legacy path must keep every E2 at 0)")
            e2s = [check_e2(CHECK_KIND_UNSPECIFIED)] * len(decls)
        else:
            e2s = [check_e2(k, check_mode) for k in kinds]
            if len(e2s) != len(decls):
                raise ValueError(
                    f"run_check: {len(decls)} declarations but {len(e2s)} kinds")
        if lparams is None:
            f2s = [0] * len(decls)
        else:
            f2s = list(lparams)
            if len(f2s) != len(decls):
                raise ValueError(
                    f"run_check: {len(decls)} declarations but {len(f2s)} "
                    f"lparams chain heads")
        nxt = 0
        for (t_root, v_root), e2, f2 in zip(reversed(decls), reversed(e2s),
                                            reversed(f2s)):
            nxt = self._append(T_FRAME, V0=TASK_CHECK, V1=t_root, V2=nxt,
                               X=v_root, E2=e2, F2=f2)
        self.init_state(decls[0][1], 0, 0, D=nxt)
        return self._run_loop(max_steps)


class InjectionEnv:
    """Card 010 G6: driver-side mirror of the kernel add_* declaration family
    (K/environment.cpp:271-284 dispatch).

    Division of labour: the graph judges single declarations (one TASK_CHECK
    anchor chain per pass).  Everything the kernel decides from environment
    *bookkeeping* — name presence, mutual-block well-formedness — has no
    graph counterpart (no name space, no block concept), so it lives here as
    data over the consts/ctors tables and rejects with
    VMError(ERR_MUTUAL_WF) BEFORE any graph pass; type checking is delegated
    to StepDriver.run_check against the grown environment.  Reference of an
    unregistered name surfaces as VMError(ERR_MISSING_CONST) at encode time,
    mirroring env.get's unknown_constant_exception (K/environment.cpp:78-85).

    consts/ctors use the test-harness shapes: consts is a list of
    (name, type tree, value tree | None), ctors a name collection.
    graph_builder is injected (callable → (graph, outputs)) — this module
    does not import build_vm.  Registration is per-constant bookkeeping only:
    the graph never sees declaration names, and re-adding an existing name is
    rejected with VMError(ERR_ALREADY_DECLARED) (card 011 G8, kernel
    alreadyDeclared, K/environment.cpp:102-105) before any graph pass.

    Per-branch phasing mirrors the kernel exactly:
      add_axiom    check_constant_val only (env.cpp:152-158) — the anchor
                   X=0 no-value shape (G5 convention).
      add_definition(safe)   check old env → register (:179-188).
      add_definition(unsafe) header check → register → body check
                   (:163-178): the self-reference is visible to the body
                   check because registration precedes it.
      add_theorem  check (incl. is_prop → the graph's code 8) old env →
                   register (:192-209); the checker is always SAFE here
                   (:196), so check_mode stays 0.
      add_opaque   check old env → register (:211-223).
      add_mutual   header loop on the OLD env (:236-251, incl.
                   check_constant_val's checker.check(type) :127-132) →
                   register ALL members (:253-257) → body loop on the NEW
                   env (:259-267); any failure rolls the whole block back
                   (measured 2026-09-20, handoff 006 G06 P2: the caller's
                   environment is unchanged, the exception payload carries
                   the would-be env).
    """

    def __init__(self, consts, ctors, graph_builder):
        self._consts = list(consts)
        self._ctors = ctors
        self._graph_builder = graph_builder
        self._names: Dict[str, int] = {
            n: cid for cid, (n, _t, _v) in enumerate(self._consts)}
        # card 010 G03: per-cid ConstantInfo metadata (ENV_FORMAT §2.3/§2.4)
        # for the injected declarations, handed to the Encoder so the G10
        # use_reject bit (anchor F2, K/type_checker.cpp:110-117) reaches the
        # graph.  Base-environment constants carry no metadata — their
        # anchors stay all-zero (F2=0, the gate is inert) exactly as in the
        # G02/G06 corpora.
        self._meta: Dict[int, dict] = {}
        self.steps_last = 0   # micro-steps of the most recent graph pass

    # ── registration bookkeeping ──────────────────────────────────────────
    def contains(self, name: str) -> bool:
        """Registration probe (kernel env.find, K/environment.cpp:74-76)."""
        return name in self._names

    def _append_entry(self, name, ty, val, meta=None) -> tuple[int, tuple]:
        cid = len(self._consts)
        prev = self._names.get(name)
        self._consts.append((name, ty, val))
        self._names[name] = cid
        if meta is not None:
            self._meta[cid] = meta
        return cid, (name, prev)

    def _rollback(self, mark: int, appended) -> None:
        """Undo every append made after `mark` (kernel rollback = the failed
        add's environment object is simply not adopted).  `appended` carries
        each name's previous _names binding so a shadowed base entry is
        restored, not erased.  Metadata is cid-keyed, so dropping every
        entry at or above the mark undoes it exactly."""
        del self._consts[mark:]
        for cid in [c for c in self._meta if c >= mark]:
            del self._meta[cid]
        for n, prev in appended:
            if prev is None:
                self._names.pop(n, None)
            else:
                self._names[n] = prev

    # ── graph passes ──────────────────────────────────────────────────────
    def _check(self, items, kinds, check_mode, lp_lists=None) -> int:
        """One graph pass over the CURRENT environment.  items:
        [(type tree, value tree | None)] (None = anchor X=0, the G5 no-value
        shape).  lp_lists (card 011 G9): optional per-item universe-parameter
        name lists; non-empty entries are emitted as T_ENV_LIST(role=2)
        chains whose head positions ride the anchors' F2 slots for the
        graph's duplicate-param scan.  Returns the micro-step count; raises
        VMError on reject."""
        build = self._graph_builder
        graph, outputs = build()
        # card 010 G03: the injected declarations' ConstantInfo metadata
        # (kind/safety) reaches the encoder, which precomputes the anchor
        # F2 use_reject bit (expr/tokens.py:569-580, ENV_FORMAT §2.3) — the
        # data the graph's G10 gate and its new mode arm key on.
        const_meta = dict(self._meta)
        enc = Encoder(self._consts, is_ctor=self._ctors,
                      const_meta=const_meta or None)
        decls = []
        try:
            for t, v in items:
                decls.append((enc.encode_term(t),
                              enc.encode_term(v) if v is not None else 0))
        except KeyError as ex:
            raise VMError(ERR_MISSING_CONST,
                          f"unknown constant {ex.args[0]!r}") from ex
        # G9 (K/environment.cpp:111-121): per-declaration lparams chains enter
        # on the anchors' F2 slot; the scan compares interred name ids — the
        # graph itself stays name-free (acceptance rule 3).
        heads = [enc.emit_univparams(lp) if lp else 0
                 for lp in (lp_lists or [None] * len(items))]
        drv = StepDriver(enc.b, graph, outputs)
        try:
            drv.run_check(decls, kinds=kinds, check_mode=check_mode,
                          lparams=heads)
        finally:
            self.steps_last = drv.steps
        return drv.steps

    # ── the add_* family (K/environment.cpp:271-284) ──────────────────────
    def _check_name(self, name):
        """G8 (K/environment.cpp:102-105 via check_constant_val :128): a name
        already present in the environment rejects with alreadyDeclared before
        ANY check runs — before type checking, before is_prop, before the G9
        duplicate-univ-param scan.  Driver bookkeeping (the graph has no name
        space), same channel as the code-9 family."""
        if name in self._names:
            raise VMError(ERR_ALREADY_DECLARED,
                          f"constant has already been declared '{name}'")

    def add_axiom(self, name, type_tree, lparams=None) -> int:
        self._check_name(name)
        self._check([(type_tree, None)], [CHECK_KIND_AXIOM], CHECK_MODE_SAFE,
                    lp_lists=[lparams])
        meta = {"kind": CK_AXIOM, "safety": 1}
        if lparams:
            meta["lparams"] = list(lparams)
        return self._append_entry(name, type_tree, None, meta)[0]

    def add_definition(self, name, type_tree, value_tree,
                       is_unsafe=False, lparams=None) -> int:
        self._check_name(name)
        meta = {"kind": CK_DEFINITION,
                "safety": 0 if is_unsafe else 1}
        if lparams:
            meta["lparams"] = list(lparams)
        if is_unsafe:
            # header on the old env (unsafe checker), register, body on the
            # new env; failed body rolls the registration back
            self._check([(type_tree, None)], [CHECK_KIND_DEFINITION],
                        CHECK_MODE_UNSAFE, lp_lists=[lparams])
            cid, ap = self._append_entry(name, type_tree, value_tree, meta)
            try:
                self._check([(type_tree, value_tree)],
                            [CHECK_KIND_DEFINITION], CHECK_MODE_UNSAFE,
                            lp_lists=[lparams])
            except VMError:
                self._rollback(cid, [ap])
                raise
            return cid
        self._check([(type_tree, value_tree)], [CHECK_KIND_DEFINITION],
                    CHECK_MODE_SAFE, lp_lists=[lparams])
        return self._append_entry(name, type_tree, value_tree, meta)[0]

    def add_theorem(self, name, type_tree, value_tree, lparams=None) -> int:
        self._check_name(name)
        self._check([(type_tree, value_tree)], [CHECK_KIND_THEOREM],
                    CHECK_MODE_SAFE, lp_lists=[lparams])
        meta = {"kind": CK_THEOREM, "safety": 1}
        if lparams:
            meta["lparams"] = list(lparams)
        return self._append_entry(name, type_tree, value_tree, meta)[0]

    def add_opaque(self, name, type_tree, value_tree, lparams=None) -> int:
        self._check_name(name)
        self._check([(type_tree, value_tree)], [CHECK_KIND_OPAQUE],
                    CHECK_MODE_SAFE, lp_lists=[lparams])
        meta = {"kind": CK_OPAQUE, "safety": 1}
        if lparams:
            meta["lparams"] = list(lparams)
        return self._append_entry(name, type_tree, value_tree, meta)[0]

    def add_mutual(self, members) -> list:
        """members: [(name, lparams, type tree, value tree, safety)] with
        safety in the ENV_FORMAT §2.4 encoding 0=unsafe / 1=safe / 2=partial;
        the block's checker mode is the HEAD member's safety (env.cpp:230).
        lparams ride each member's header/body anchors (card 011 G9: the
        graph's duplicate-param scan, K/environment.cpp:111-121, runs per
        member inside the check_constant_val graph pass); the
        same-lparams-equality bookkeeping stays in the pre-loop below.

        Known approximations (VM_SPEC §16.5/§16.6): partial blocks run the
        graph passes with the unsafe mode bit (the §2.8 layout has no partial
        value); the kernel interleaves per-member bookkeeping with header
        checks while this implementation books every member first, then
        headers — observable only on multi-defect blocks.  Since card 010
        G03 the members' safety reaches the encoder as const_meta (anchor
        F2 use_reject), and the block's unsafe mode bit suppresses the G10
        gate for the block's own header/body passes; the mode bit does not
        survive across ST-continuation hops (I_PI/I_LAMSORT/I_LETD —
        VM_SPEC §16.6 known gap)."""
        if not members:
            raise VMError(ERR_MUTUAL_WF, "invalid empty mutual definition")
        safety = members[0][4]
        if safety == 1:
            raise VMError(ERR_MUTUAL_WF, "invalid mutual definition, "
                          "declaration is not tagged as unsafe/partial")
        mode = CHECK_MODE_UNSAFE          # block checker: unsafe or partial
        head_lparams = members[0][1]
        found = set()
        for name, lparams, _t, _v, s in members:
            if s != safety:
                raise VMError(ERR_MUTUAL_WF, "invalid mutual definition, "
                              "declarations must have the same safety "
                              "annotation")
            if list(lparams) != list(head_lparams):
                raise VMError(ERR_MUTUAL_WF, "invalid mutual definition, "
                              "declarations must have the same universe "
                              "level parameters")
            if name in found:
                raise VMError(ERR_MUTUAL_WF, "invalid mutual definition, "
                              "duplicate declaration name '" + name + "'")
            found.add(name)
            # G8 (K/environment.cpp:243-247 + check_constant_val :128): the
            # kernel's per-member check_name sees the OLD env (no block member
            # is registered yet), so an already-declared member name is
            # alreadyDeclared; the in-block duplicate check above runs first,
            # exactly the kernel's loop order.
            self._check_name(name)
        # header pass — old environment; the kernel checks every member's
        # header BEFORE registering anything (:236-251 precede :253-257).
        # Card 011 G9: each member's lparams ride the header anchors' F2
        # chains — check_constant_val's duplicate-param scan (per member,
        # kernel :129) runs inside these graph passes.
        n = len(members)
        self._check([(t, None) for _nm, _lp, t, _v, _s in members],
                    [CHECK_KIND_DEFINITION] * n, mode,
                    lp_lists=[m[1] for m in members])
        # register all members, then the body pass on the new environment
        mark = len(self._consts)
        appended = []
        cids = []
        for name, lp, t, v, _s in members:
            meta = {"kind": CK_DEFINITION, "safety": _s}
            if lp:
                meta["lparams"] = list(lp)
            cid, ap = self._append_entry(name, t, v, meta)
            cids.append(cid)
            appended.append(ap)
        try:
            self._check([(t, v) for _nm, _lp, t, v, _s in members],
                        [CHECK_KIND_DEFINITION] * n, mode,
                        lp_lists=[m[1] for m in members])
        except VMError:
            self._rollback(mark, appended)
            raise
        return cids

