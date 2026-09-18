"""Reference VM — a plain-Python interpreter of docs/VM_SPEC.md v1.

This is `ref_vm` (the wasm-reference analog *within* the project): it
executes the SAME token stream the ALM graph will consume, with the SAME
mechanisms (Krivine links, digit chains, append-only stream), so that the
Phase-2 ALM graph can be validated against it mechanically.

Deliberate implementation notes (honesty about what is validated where):
  - LINK tokens live in the stream (V2 chain, V1 = depth, X = captured env
    head) exactly as the ALM graph will use them; the Krivine pending-arg
    stack is Python control state here (in the ALM graph it becomes PEND
    tokens with a run-id — Phase 2).
  - Nat ops compute on digit chains decoded to Python ints here; the
    per-digit ALM lookup tables that replace this are validated in
    Phase 2 against this VM (VM_SPEC §5; no NAT_MAX-style caps).
"""
from __future__ import annotations

from typing import Optional

from expr.model import (
    K_BVAR, K_FVAR, K_MVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET,
    K_LIT, K_MDATA, K_PROJ, LIT_NAT,
    KL_ZERO, KL_SUCC, KL_MAX, KL_IMAX, KL_PARAM, KL_MVAR,
    LitNat, Const,
)
from expr.tokens import (
    StreamBundle, T_LINK, T_LIT_DIG, T_PI_CLO, T_ENV_UNIVPARAMS,
    NAT_OPS, NAT_OP_ARITY,
    TASK_WHNF,
)


class VMError(Exception):
    def __init__(self, code: int, detail: str = "",
                 focus: int = -1, env: int = -1):
        super().__init__(f"VM reject {code}: {detail}")
        self.code = code
        # M4.3 error localization: the machine's focus closure (A, B) at the
        # rejecting micro-step, when the driver can supply it. focus=-1 means
        # "not a node focus" (e.g. a verdict-false reject, where A is 0/1).
        self.focus = focus
        self.env = env


# VM_SPEC §7.4 error codes
ERR_TYPE = 1
ERR_MISSING_CONST = 2
ERR_OVERFLOW = 3
ERR_UNSUPPORTED = 4


class RefVM:
    """Krivine-style WHNF machine over the token stream (VM_SPEC §7)."""

    def __init__(self, bundle: StreamBundle, nat_enabled: bool = True,
                 structures: Optional[dict] = None):
        self.nat_enabled = nat_enabled
        self.b = bundle
        # WP2: checked declaration's lparams (nids) for infer_constant's
        # check_level (K/type_checker.cpp:85-91,364-367). None = driver did
        # not supply them (infer_type mode skips the check too,
        # K/type_checker.cpp:360-362).
        self._decl_lparams: Optional[set] = None
        # delta value-instantiation cache (A28): (cid, level-form key) -> value
        # root already specialized at that use-site level vector.
        self._val_inst_cache: dict = {}
        self.cid_op = {}
        if nat_enabled:
            for name, cid in bundle.cids.items():
                if name in NAT_OPS:
                    self.cid_op[cid] = NAT_OPS[name]
        self.cid_zero = bundle.cids.get("Nat.zero")
        self.cid_succ = bundle.cids.get("Nat.succ")
        self.cid_rec = bundle.cids.get("Nat.rec")
        self.cid_true = bundle.cids.get("Bool.true")
        self.cid_false = bundle.cids.get("Bool.false")
        # M3 non-rec structures: {ind_name: (ctor_name, nparams, nfields)}.
        # Keyed by cid for whnf proj reduction (ctor_of_struct) and
        # try_eta_struct (struct_of_ctor).
        self.struct_of_ctor = {}
        self.ctor_of_struct = {}
        for ind, (ctor, nparams, nfields) in (structures or {}).items():
            ci, cc = bundle.cids[ind], bundle.cids[ctor]
            self.struct_of_ctor[cc] = (ci, nparams, nfields)
            self.ctor_of_struct[ci] = (cc, nparams, nfields)
        # P7.2 casesOn recursors: recursor_cid -> (major_idx,
        # [(ctor_cid, nfields), ...] in minor order). Non-recursive case
        # analysis (inductive.h L77): whnf the major to a constructor, apply
        # the matching minor to the constructor's fields. No recursive calls.
        self.caseson = {}
        _cs_nat = bundle.cids.get("Nat.casesOn")
        if _cs_nat is not None:
            self.caseson[_cs_nat] = (0, [(self.cid_zero, 0), (self.cid_succ, 1)])
        _cs_p2 = bundle.cids.get("P2.casesOn")
        if _cs_p2 is not None:
            self.caseson[_cs_p2] = (0, [(bundle.cids.get("P2.mk"), 2)])
        _cs_bool = bundle.cids.get("Bool.casesOn")
        if _cs_bool is not None:
            # minors follow Lean's ctor declaration order: false before true
            self.caseson[_cs_bool] = (0, [(self.cid_false, 0), (self.cid_true, 0)])
        # P7.5c-2: NO brecOn dispatch — Nat.brecOn/Nat.below carry the faithful
        # def-over-rec delta values (toy_env _brec_value/_below_value), so the
        # K_CONST gate above deltas them and the existing rec-iota + proj
        # machinery reduces them (iota = delta + beta + rec + P2-proj).

    # ── environment links (stream-resident, VM_SPEC §6) ─────────────────────
    def _link(self, value_pos: int, value_env: int, head: int,
              flag: int = 0, bid: int = 0) -> int:
        """Push a T_LINK. flag=1 marks a *binder* link (Phase-5 INFER/DEFEQ):
        the value is the binder's domain TYPE closure, so infer(BVar) returns
        it directly and whnf-under-binder treats the variable as the
        fvar-analog (kernel mk_local_decl with the domain as its type).
        bid>0 (flag=1 only) is the binder's unique identity (fvar name
        analog): is_def_eq_binding stamps the t-side and s-side marker of
        each compared binder with the SAME bid, so corresponding BVars
        resolve to equal ids (alpha-equivalence), while distinct binders of
        one comparison carry distinct ids (M3)."""
        depth = self.b.stream[head][2] + 1 if head else 0
        return self.b.push(T_LINK, V0=value_pos, V1=depth, V2=head,
                           X=value_env, E2=flag, F2=bid)

    def _resolve(self, head: int, i: int) -> tuple:
        """bvar(i): walk i links back from the chain head (innermost).
        Tuple layout is (K, V0, V1, V2, X); the link's prev-pointer is V2
        at index 3."""
        cur = head
        for _ in range(i):
            cur = self.b.stream[cur][3]
            if not cur:
                raise VMError(ERR_OVERFLOW, f"bvar {i} beyond env depth")
        return self.b.stream[cur]

    # ── WHNF (VM_SPEC §7.1) ─────────────────────────────────────────────────
    def whnf(self, pos: int, env: int) -> tuple[int, int]:
        """Returns (result_pos, result_env) — a closure. A stuck App spine
        returns the whole original spine (spine root), not the bare head
        (VM_SPEC §10.2, calibrated against real lean)."""
        pend: list[tuple[int, int]] = []   # (arg pos, env at push) — Krivine stack
        spine_root = 0                     # App that opened the current spine
        spine_env = 0                      # env at that App (head resolution
        #   reassigns env via value links / delta — the spine's args live in
        #   the ORIGINAL env, so the stuck return must use this, not env)
        while True:
            K, V0, V1, V2, X = self.b.stream[pos][:5]
            if K == K_APP:
                if not pend:
                    spine_root = pos
                    spine_env = env
                pend.append((V1, env))
                pos = V0
                continue
            if K == K_LAM:
                if pend:
                    a, aenv = pend.pop()
                    env = self._link(a, aenv, env)
                    pos = V1                      # body
                    continue
                return pos, env
            if K == K_CONST:
                if self.b.const_has_value.get(V0):
                    # delta. Kernel unfold_definition_core instantiates the
                    # value at the use-site levels (A28, VM_SPEC §12.3;
                    # K/type_checker.cpp:555-565, instantiate_value_lparams
                    # K/instantiate.cpp:256-264). Without this, an
                    # uninstantiated LParam leaks out of the unfolded value.
                    pos = self._instantiate_value(V0, V1)
                    env = 0                            # constants are closed
                    continue
                op = self.cid_op.get(V0)
                if op is not None and len(pend) >= NAT_OP_ARITY[op]:
                    # pend.pop() yields innermost-first, i.e. application
                    # order (arg1 was pushed last)
                    args = [pend.pop() for _ in range(NAT_OP_ARITY[op])]
                    vals = [self.whnf(a, aenv) for (a, aenv) in args]
                    return self._nat(op, vals), 0
                if V0 in self.caseson:
                    # P7.2 casesOn reduce_recursor (inductive.h L77). Spine
                    # (application order) = [major, motive, alt0, alt1, ...];
                    # major_idx=0. whnf the major to a constructor, apply the
                    # matching minor to its fields; extras stay on the stack.
                    major_idx, ctors = self.caseson[V0]
                    nargs = 2 + len(ctors)          # major + motive + minors
                    if len(pend) >= nargs:
                        args = list(reversed(pend))  # application order
                        mp, menv = args[major_idx]
                        wpos, wenv = self.whnf(mp, menv)
                        m = self._match_ctor(wpos, wenv, ctors)
                        if m is not None:
                            ctor_idx, fields = m
                            minor = args[2 + ctor_idx]
                            extras = args[nargs:]
                            pend[:] = (list(reversed(extras))
                                       + list(reversed(fields)))
                            pos, env = minor
                            continue
                        # major stuck (binder/other) → recursor spine stuck;
                        # fall through to the §10.2 return below
                if V0 == self.cid_rec and len(pend) >= 4:
                    # iota (kernel inductive_reduce_rec, inductive.h L77):
                    # Nat.rec has major_idx 3, nparams 0 → the major premise
                    # is pend[-4] (pend order: [.., maj, s, z, m]).
                    m, z, s, maj = pend[-1], pend[-2], pend[-3], pend[-4]
                    wpos, wenv = self.whnf(maj[0], maj[1])
                    wK, wV0, wV1, *_ = self.b.stream[wpos][:5]
                    pred = None
                    if wK == K_LIT and wV1 == LIT_NAT:
                        v = sum(self.b.stream[wpos + 2 + 2 * i][1]
                                * (10 ** i) for i in range(wV0))
                        if v == 0:
                            del pend[-4:]
                            pos, env = z
                            continue
                        pred = (self._emit_chain(v - 1), 0)  # nat_lit_to_constructor peels ONE succ
                    elif wK == K_CONST and wV0 == self.cid_zero:
                        del pend[-4:]
                        pos, env = z
                        continue
                    elif wK == K_APP:
                        # stuck succ spine (only reachable with nat ops
                        # disabled — the succ nat-op path otherwise never
                        # leaves `succ x` stuck); defensive, mirrors kernel
                        fn = self.b.stream[wpos][1]
                        fK, fV0, *_ = self.b.stream[fn][:5]
                        if fK == K_CONST and fV0 == self.cid_succ:
                            pred = (self.b.stream[wpos][2], wenv)
                    if pred is not None:
                        # succ rule: rec m z s (succ n) ⇒ s n (rec m z s n).
                        # The four closures ride a link chain e4
                        # (BVar 0=n, 1=s, 2=z, 3=m) so the re-emitted spine
                        # is closed under e4. Recursion is LAZY: the loop
                        # continues on rhs; extra args (if any) stay on the
                        # stack and apply to the result (kernel: extras
                        # applied to rhs).
                        e1 = self._link(m[0], m[1], 0)
                        e2 = self._link(z[0], z[1], e1)
                        e3 = self._link(s[0], s[1], e2)
                        e4 = self._link(pred[0], pred[1], e3)
                        b0 = self.b.push(K_BVAR, V0=0)
                        b1 = self.b.push(K_BVAR, V0=1)
                        b2 = self.b.push(K_BVAR, V0=2)
                        b3 = self.b.push(K_BVAR, V0=3)
                        rc = self._emit_const("Nat.rec")
                        r4 = self.b.push(K_APP, V0=rc, V1=b3)
                        r4 = self.b.push(K_APP, V0=r4, V1=b2)
                        r4 = self.b.push(K_APP, V0=r4, V1=b1)
                        r4 = self.b.push(K_APP, V0=r4, V1=b0)
                        a1 = self.b.push(K_APP, V0=b1, V1=b0)
                        rhs = self.b.push(K_APP, V0=a1, V1=r4)
                        del pend[-4:]
                        pos, env = rhs, e4
                        continue
                    # major premise stuck (binder/mvar/other) → the recursor
                    # spine is stuck; fall through to the §10.2 return below
                # stuck head: if args are pending, the result is the whole
                # original spine (in its ORIGINAL env — see spine_env)
                return (spine_root if pend and spine_root else pos), \
                    (spine_env if pend and spine_root else env)
            if K == K_LET:                        # zeta
                env = self._link(V1, env, env)
                pos = X                           # body (X field, §4)
                continue
            if K == K_BVAR:
                link = self._resolve(env, V0)
                if link[5] == 1:
                    # binder marker (fvar analog): a variable is stuck in
                    # whnf, exactly like a kernel fvar without a value —
                    # with pending args the result is the whole original
                    # spine (same §10.2 convention as the K_CONST stuck
                    # head; the pre-P6 head-only return let defeq compare
                    # two marker apps by head bid alone and accept `f 1`
                    # vs `f 2` — caught by deq_fvar_args).
                    return (spine_root if pend and spine_root else pos), \
                        (spine_env if pend and spine_root else env)
                pos, env = link[1], link[4]   # (value pos, captured env)
                continue
            if K == K_MDATA:
                pos = V0                          # kernel ignores mdata
                continue
            if K == K_PROJ:
                # kernel whnf reduces `ctor a_1 ... a_n .idx` to a_idx
                # (reduce_proj_core subset: non-rec structure ctor directly;
                # delta through a struct-valued const handled by the K_CONST
                # case when we whnf the child here).  After selecting the
                # field, KEEP WHNFING it — the kernel's whnf loops
                # (reduceProj feeds back into whnf); the field of a real
                # brecOn below-pair is an un-reduced application, and
                # returning it raw would end whnf in a non-normal form.
                cpos, cenv = self.whnf(X, env)
                st = self._proj_core(cpos, V0, V1)   # (V0=struct nid, V1=idx)
                if st is None:
                    return pos, env               # stuck proj
                pos, env = st, cenv
                continue
            if K in (K_SORT, K_FVAR, K_MVAR, K_LIT, K_PI, T_PI_CLO):
                return pos, env
            raise VMError(ERR_UNSUPPORTED, f"token kind {K} at {pos}")

    def _proj_core(self, cpos: int, s_nid: int, idx: int) -> Optional[int]:
        """`cpos.idx` if cpos is a fully applied ctor application of the
        non-rec structure named by s_nid; else None (stuck)."""
        b = self.b
        head, args = self._spine(cpos, 0)
        hK, hV0, *_ = b.stream[head[0]][:5]
        if hK != K_CONST:
            return None
        # head cid is the CTOR's → ctor→(ind cid, nparams, nfields)
        ent = self.struct_of_ctor.get(hV0)
        if ent is None:
            return None
        ind_cid, nparams, nfields = ent
        # Proj token carries the structure NAME nid; match it to the ctor's
        # inductive cid (kernel: proj_sname == structure of the ctor)
        if b.cids.get(b.id_names[s_nid]) != ind_cid:
            return None
        if len(args) != nparams + nfields:
            return None
        # _spine yields args outermost-first, i.e. LAST field first; kernel
        # proj idx counts fields from the FIRST → index from the spine tail
        return args[len(args) - 1 - idx][0]

    # ── Nat ops (VM_SPEC §7.2) ──────────────────────────────────────────────
    def _chain_value(self, pos: int, env: int) -> int:
        p, e = self.whnf(pos, env)
        K, V0, V1, V2, X = self.b.stream[p][:5]
        if K == K_LIT and V1 == LIT_NAT:
            n = 0
            for i in range(V0):
                d = self.b.stream[p + 2 + 2 * i][1]   # stride-2 (§5)
                n += d * (10 ** i)
            return n
        if K == K_CONST and V0 == self.cid_zero:
            return 0
        raise VMError(ERR_TYPE, f"nat op arg not a literal (kind {K})")

    def _emit_chain(self, value: int) -> int:
        b = self.b
        digits = []
        if value == 0:
            digits = [0]
        else:
            while value:
                digits.append(value % 10)
                value //= 10
        head = b.push(K_LIT, V0=len(digits), V1=LIT_NAT)
        for d in digits:
            b.push(0)                          # stride-2 gap (VM_SPEC §5)
            b.push(T_LIT_DIG, V0=d, V2=head)
        return head

    def _emit_const(self, name: str) -> int:
        return self.b.push(K_CONST, V0=self.b.cids[name])

    def _nat(self, op: str, vals: list[tuple[int, int]]) -> int:
        vs = [self._chain_value(p, e) for (p, e) in vals]
        if op == "succ":
            return self._emit_chain(vs[0] + 1)
        if op == "pred":
            return self._emit_chain(max(0, vs[0] - 1))
        if op == "add":
            return self._emit_chain(vs[0] + vs[1])
        if op == "sub":
            return self._emit_chain(max(0, vs[0] - vs[1]))
        if op == "mul":
            return self._emit_chain(vs[0] * vs[1])
        if op == "pow":
            return self._emit_chain(vs[0] ** vs[1])
        if op == "div":
            # kernel: Nat.div a 0 = 0 (probe 2026-08-30)
            return self._emit_chain(0 if vs[1] == 0 else vs[0] // vs[1])
        if op == "mod":
            # kernel: Nat.mod a 0 = a (probe 2026-08-30)
            return self._emit_chain(vs[0] if vs[1] == 0 else vs[0] % vs[1])
        if op == "beq":
            return self._emit_const("Bool.true" if vs[0] == vs[1]
                                    else "Bool.false")
        if op == "ble":
            return self._emit_const("Bool.true" if vs[0] <= vs[1]
                                    else "Bool.false")
        raise VMError(ERR_UNSUPPORTED, f"nat op {op}")

    # ── entry ───────────────────────────────────────────────────────────────
    def run_whnf(self, term_pos: int) -> int:
        """Run T_WHNF on a closed term; returns the result position."""
        rpos, _renv = self.whnf(term_pos, 0)
        return rpos

    # ── INFER / DEFEQ (Phase 5 M1+M3; kernel type_checker subset) ───────────
    # Scope (docs/VM_SPEC §8): closed terms over a monomorphic env, no
    # universe parameters. M3 adds proof irrelevance, eta expansion,
    # structural eta and structure projections; binder markers carry a
    # unique id (T_LINK.F2) so distinct fvars stay distinct while compared
    # binder pairs share one (kernel fvar-name equality / shared local).
    # Kernel algorithm mapping:
    #   infer_app        → spine peel + per-arg ensure_pi + is_def_eq(arg
    #                      type, domain) + instantiate(body, arg)
    #   infer_lambda/pi  → marker link per binder (fvar analog) + ensure_sort
    #                      on domains + T_PI_CLO result
    #   infer_let        → val-type defeq check + binder marker on the domain
    #   is_def_eq        → quick structural + whnf-both loop (beta/zeta/delta/
    #                      nat ops live in whnf) + proof irrelevance + stuck
    #                      spine compare + eta expansion + structural eta
    def _pi_parts(self, clo: tuple[int, int]) -> tuple[tuple, tuple]:
        """Split a Pi-shaped closure into ((domain), (body)) closures.
        K_PI: both halves share the closure env. T_PI_CLO: X = domain env,
        E2 = body env (the marker-link split produced by infer(Lam))."""
        pos, env = clo
        K, V0, V1, V2, X, E2, F2 = self.b.stream[pos]
        if K == K_PI:
            return (V0, env), (V1, env)
        if K == T_PI_CLO:
            return (V0, X), (V1, E2)
        raise VMError(ERR_TYPE, f"infer_app: not a function (kind {K})")

    def _binder_marker(self, is_clo: bool, dom_pos: int, outer_env: int,
                       body_env: Optional[int],
                       body_pos: int) -> Optional[int]:
        """The binder marker link used for a Pi comparison (kernel
        mk_local_decl on a shared lctx, K/type_checker.cpp:785-791).
        K_PI: always push a fresh marker over its outer env. T_PI_CLO: the
        body closure is (V1, E2). Reuse E2 when it is a flag=1 marker over
        outer_env. When E2 == outer_env the body is a self-contained closure
        (infer returns env 0 for a lambda); its binder marker, if nested
        structures refer to it, is the outer env stored in a T_PI_CLO body
        node (X). Return None when no marker is represented."""
        if not is_clo:
            return self._link(dom_pos, outer_env, outer_env, flag=1)
        if body_env is None:
            return None
        if body_env != outer_env:
            row = self.b.stream[body_env]
            if row[0] == T_LINK and row[5] == 1 and row[3] == outer_env:
                return body_env
            return None
        # body_env == outer_env: self-contained body. A nested inferred Pi
        # stores its outer env in X (T_PI_CLO.V0 root, field index 4).
        if self.b.stream[body_pos][0] == T_PI_CLO:
            cand = self.b.stream[body_pos][4]
            if cand:
                row = self.b.stream[cand]
                if row[0] == T_LINK and row[5] == 1 and row[3] == outer_env:
                    return cand
        return None

    def _soft_whnf(self, pos: int, env: int) -> tuple[int, int]:
        """whnf for the DEFEQ loop: a nat-op arg that won't reduce to a
        literal (kernel: is_nat_expr fails) leaves the term stuck instead of
        raising (kernel lazy_delta_reduction just doesn't fire)."""
        try:
            return self.whnf(pos, env)
        except VMError as e:
            if e.code in (ERR_TYPE, ERR_OVERFLOW):
                return (pos, env)
            raise

    # ── levels (WP2; VM_SPEC §12; kernel K/level.cpp) ───────────────────────
    # Levels live in the stream as KL_* trees (VM_SPEC §12.1); a "level" here
    # is the stream position of its root. The operations below mirror the
    # kernel C++ semantics exactly, with citations. Only the subset needed by
    # the checking path (decode, structural equality D3, smart max/imax
    # D1/D2, equivalent D4, zero predicates D8, explicit/to_offset D9,
    # instantiate D10, get_undef_param D11, expr substitution D13/D14) is
    # implemented; D6/D7 cache ordering is not needed by is_def_eq.

    def _lvl(self, lpos: int) -> tuple:
        return self.b.stream[lpos]

    def _level_kind(self, lpos: int) -> int:
        return self.b.stream[lpos][0]

    def _level_eq(self, p: int, q: int) -> bool:
        """Kernel `operator==` (K/level.cpp:125-150) as pure structural
        recursion: kind equal, then per-kind structural equality. Param/MVar
        compare their name id (K/level.cpp:132-133); Succ compares its child
        (K/level.cpp:134-140); Max/IMax compare both sides (K/level.cpp:141-
        148). hash/depth are only fast paths (K/level.cpp:39-40,44-52)."""
        if p == q:
            return True
        K, V0, V1, _, _ = self.b.stream[p][:5]
        K2, W0, W1, _, _ = self.b.stream[q][:5]
        if K != K2:
            return False
        if K == KL_ZERO:
            return True
        if K in (KL_PARAM, KL_MVAR):
            return V0 == W0
        if K == KL_SUCC:
            return self._level_eq(V0, W0)
        if K in (KL_MAX, KL_IMAX):
            return self._level_eq(V0, W0) and self._level_eq(V1, W1)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _level_is_zero(self, p: int) -> bool:
        """Kernel is_zero: literal Zero (K/level.h zero constructor)."""
        return self.b.stream[p][0] == KL_ZERO

    def _level_depth(self, p: int) -> int:
        """Kernel get_depth for explicit levels (D1; K/level.cpp:40):
        zero=0, succ l=l+1. Callers guard with _level_is_explicit."""
        K, V0, _, _, _ = self.b.stream[p][:5]
        if K == KL_ZERO:
            return 0
        if K == KL_SUCC:
            return 1 + self._level_depth(V0)
        raise VMError(ERR_UNSUPPORTED, f"get_depth: non-explicit level kind {K}")

    def _level_is_explicit(self, p: int) -> bool:
        """D9 is_explicit (K/level.cpp:54-64): Zero true, Param/MVar/Max/IMax
        false, Succ recurses."""
        K, V0, _, _, _ = self.b.stream[p][:5]
        if K == KL_ZERO:
            return True
        if K in (KL_PARAM, KL_MVAR, KL_MAX, KL_IMAX):
            return False
        if K == KL_SUCC:
            return self._level_is_explicit(V0)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _level_to_offset(self, p: int) -> tuple[int, int]:
        """D9 to_offset (K/level.cpp:67-74): peel k outer succs, return
        (base, k). Non-succ base gives (p, 0)."""
        k = 0
        while self.b.stream[p][0] == KL_SUCC:
            p = self.b.stream[p][1]
            k += 1
        return p, k

    def _level_is_one(self, p: int) -> bool:
        """Kernel is_one (K/level.cpp:106-110): structurally `succ zero`."""
        if self.b.stream[p][0] != KL_SUCC:
            return False
        c = self.b.stream[p][1]
        return self.b.stream[c][0] == KL_ZERO

    def _level_is_not_zero(self, p: int) -> bool:
        """D8 is_not_zero (K/level.cpp:160-172): true for every assignment.
        Zero/Param/MVar false, Succ true, Max lhs||rhs, IMax rhs only."""
        K, V0, V1, _, _ = self.b.stream[p][:5]
        if K in (KL_ZERO, KL_PARAM, KL_MVAR):
            return False
        if K == KL_SUCC:
            return True
        if K == KL_MAX:
            return self._level_is_not_zero(V0) or self._level_is_not_zero(V1)
        if K == KL_IMAX:
            return self._level_is_not_zero(V1)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _level_normalizes_to_zero(self, p: int) -> bool:
        """D8 normalizes_to_zero (K/level.cpp:174-187): Zero true,
        Param/MVar/Succ false, Max lhs&&rhs, IMax rhs only. is_prop uses this
        (K/type_checker.cpp:383-389)."""
        K, V0, V1, _, _ = self.b.stream[p][:5]
        if K == KL_ZERO:
            return True
        if K in (KL_PARAM, KL_MVAR, KL_SUCC):
            return False
        if K == KL_MAX:
            return (self._level_normalizes_to_zero(V0)
                    and self._level_normalizes_to_zero(V1))
        if K == KL_IMAX:
            return self._level_normalizes_to_zero(V1)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _level_is_side_of(self, side: int, whole: int) -> bool:
        K, V0, V1, _, _ = self.b.stream[whole][:5]
        return K in (KL_MAX, KL_IMAX) and (
            self._level_eq(side, V0) or self._level_eq(side, V1))

    def _mk_max(self, a: int, b: int) -> int:
        """D1 mk_max (K/level.cpp:81-104), branch-for-branch. Returns an
        existing position when the smart constructor can; otherwise a fresh
        KL_MAX node. `b` is unused after the raw-constructor branch because
        the C++ core also keeps the operand order."""
        if self._level_is_explicit(a) and self._level_is_explicit(b):
            return a if self._level_depth(a) >= self._level_depth(b) else b
        if self._level_eq(a, b):
            return a
        if self._level_is_zero(a):
            return b
        if self._level_is_zero(b):
            return a
        if self._level_is_side_of(a, b):      # is_max b && b == max a _
            return b
        if self._level_is_side_of(b, a):      # is_max a && a == max b _
            return a
        pa, ka = self._level_to_offset(a)
        pb, kb = self._level_to_offset(b)
        if pa == pb:
            return a if ka > kb else b
        return self.b.push(KL_MAX, V0=a, V1=b)

    def _mk_imax(self, a: int, b: int) -> int:
        """D2 mk_imax (K/level.cpp:112-123). The `is_one(l1)` branch is
        kernel-only (Lean-visible Level.mkLevelIMax' lacks it, VM_SPEC §12.2
        D2 note); VM follows the C++ kernel."""
        if self._level_is_not_zero(b):
            return self._mk_max(a, b)
        if self._level_is_zero(b):
            return b
        if self._level_is_zero(a) or self._level_is_one(a):
            return b
        if self._level_eq(a, b):
            return a
        return self.b.push(KL_IMAX, V0=a, V1=b)

    def _mk_succ(self, p: int) -> int:
        """Kernel mk_succ (K/level.cpp:33): raw Succ wrapper, no smart
        simplification."""
        return self.b.push(KL_SUCC, V0=p)

    def _level_normal_form(self, p: int):
        """A canonical, order-insensitive key for D4 is_equivalent. Full D5
        normalize is only needed if two syntactically different level trees
        must compare equal; this project's corpus levels are already in
        mk_* normal form because they come straight from the real kernel, so
        structural equality (D3) short-circuits. The fallback recursively
        sorts max/imax operands by their key, which is sound for the
        associative-commutative reading but deliberately not claimed to be
        the full C++ normalize."""
        K, V0, V1, _, _ = self.b.stream[p][:5]
        if K == KL_ZERO:
            return ("z",)
        if K == KL_PARAM:
            return ("p", V0)
        if K == KL_MVAR:
            return ("m", V0)
        if K == KL_SUCC:
            return ("s", self._level_normal_form(V0))
        if K in (KL_MAX, KL_IMAX):
            a, b = self._level_normal_form(V0), self._level_normal_form(V1)
            if b < a:
                a, b = b, a
            return ("x" if K == KL_MAX else "i", a, b)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _level_is_equivalent(self, p: int, q: int) -> bool:
        """D4 is_equivalent (K/level.cpp:518-521): lhs==rhs or
        normalize(lhs)==normalize(rhs). Structural equality (the common case
        for kernel-normalized declarations) is exact; the canonical key drops
        into the symmetric max/imax fallback."""
        if self._level_eq(p, q):
            return True
        return self._level_normal_form(p) == self._level_normal_form(q)

    def _levels_equivalent(self, h1: int, h2: int) -> bool:
        """Kernel is_def_eq(levels, levels) (K/type_checker.cpp:822-832):
        element-wise D4 on the two K_CONST level-argument chains; different
        lengths are unequal (the nil/non-nil branches)."""
        a = self._const_level_args(h1)
        b = self._const_level_args(h2)
        if len(a) != len(b):
            return False
        return all(self._level_is_equivalent(x, y) for x, y in zip(a, b))

    def _level_has_param(self, p: int) -> bool:
        K, V0, V1, _, _ = self.b.stream[p][:5]
        if K == KL_PARAM:
            return True
        if K in (KL_ZERO, KL_MVAR):
            return False
        if K == KL_SUCC:
            return self._level_has_param(V0)
        if K in (KL_MAX, KL_IMAX):
            return self._level_has_param(V0) or self._level_has_param(V1)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _get_undef_param(self, p: int, allowed_nids: set) -> Optional[int]:
        """D11 get_undef_param (K/level.cpp:289-299): pre-order scan; the
        first Param whose name id is not in `allowed_nids` is returned (its
        nid), else None. Pre-order and early stop match for_each +
        (has_param, r) guards (K/level.cpp:247-259,292-293)."""
        K, V0, V1, _, _ = self.b.stream[p][:5]
        if K == KL_ZERO:
            return None
        if K == KL_PARAM:
            return None if V0 in allowed_nids else V0
        if K == KL_MVAR:
            return None
        if K == KL_SUCC:
            return self._get_undef_param(V0, allowed_nids)
        if K in (KL_MAX, KL_IMAX):
            r = self._get_undef_param(V0, allowed_nids)
            if r is not None:
                return r
            return self._get_undef_param(V1, allowed_nids)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _inst_level(self, p: int, mapping: dict) -> int:
        """D10 instantiate(level, params, levels) (K/level.cpp:317-340):
        substitute Param id -> use-site level by position. Unmatched params
        are returned unchanged (K/level.cpp:334-335). Succ/Max/IMax rebuild
        through mk_succ/mk_max/mk_imax (K/level.cpp:301-315) only when a child
        changed. LMVar has no param (short-circuits in has_param,
        K/level.cpp:320-321)."""
        K, V0, V1, _, _ = self.b.stream[p][:5]
        if K == KL_ZERO or K == KL_MVAR:
            return p
        if K == KL_PARAM:
            return mapping.get(V0, p)
        if K == KL_SUCC:
            c = self._inst_level(V0, mapping)
            return p if c == V0 else self._mk_succ(c)
        if K in (KL_MAX, KL_IMAX):
            a = self._inst_level(V0, mapping)
            b = self._inst_level(V1, mapping)
            if a == V0 and b == V1:
                return p
            return self._mk_max(a, b) if K == KL_MAX else self._mk_imax(a, b)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _const_level_args(self, head: int) -> list[int]:
        """Use-site level-argument roots of a K_CONST: roots chained through
        X (VM_SPEC §12.1; R/expr/tokens.py:229-239). Returns [] for head=0."""
        out: list[int] = []
        p = head
        seen = set()
        while p:
            if p in seen:
                raise VMError(ERR_TYPE, "const level chain cycle")
            seen.add(p)
            out.append(p)
            p = self.b.stream[p][4]           # X = next sibling root
        return out

    def _const_lparam_nids(self, cid: int) -> tuple:
        """Declaration-side ordered lparams names as nids (VM_SPEC §12.1,
        T_ENV_UNIVPARAMS). Prefers the bundle's decoded map; falls back to
        walking the per-cid meta chain for hand-built bundles."""
        lp = self.b.const_lparams.get(cid)
        if lp is not None:
            return lp
        anchor = self.b.const_meta_pos.get(cid)
        if anchor is None:
            return ()
        head = self.b.stream[anchor][3]       # T_ENV_META.V2 = meta chain head
        nids: list[int] = []
        p, seen = head, set()
        while p:
            if p in seen:
                break
            seen.add(p)
            K, V0, V1, _, X = self.b.stream[p][:5]
            if K == T_ENV_UNIVPARAMS and V0 == cid:
                q, s2 = V1, set()
                while q:
                    if q in s2:
                        break
                    s2.add(q)
                    nids.append(self.b.stream[q][2])   # T_ENV_LIST.V1 = nid
                    q = self.b.stream[q][4]            # X = next node
            p = self.b.stream[p][6]            # F2 = next meta token
        return tuple(nids)

    def _expr_has_param_univ(self, p: int) -> bool:
        """Kernel has_param_univ (K/expr.h:157,358; short-circuit in
        instantiate_lparams, K/instantiate.cpp:233)."""
        K, V0, V1, _, X = self.b.stream[p][:5]
        if K == K_SORT:
            return self._level_has_param(V0)
        if K == K_CONST:
            for r in self._const_level_args(V1):
                if self._level_has_param(r):
                    return True
            return False
        if K == K_APP:
            return (self._expr_has_param_univ(V0)
                    or self._expr_has_param_univ(V1))
        if K in (K_LAM, K_PI):
            return (self._expr_has_param_univ(V0)
                    or self._expr_has_param_univ(V1))
        if K == K_LET:
            return (self._expr_has_param_univ(V0)
                    or self._expr_has_param_univ(V1)
                    or self._expr_has_param_univ(X))
        if K == K_MDATA:
            return self._expr_has_param_univ(V0)
        if K == K_PROJ:
            return self._expr_has_param_univ(X)
        return False                          # BVar/FVar/MVar/Lit

    def _rebuild_const(self, cid: int, roots: list[int]) -> int:
        """Emit a fresh K_CONST with a fresh sibling chain over `roots`.
        Roots are copied before their X is repurposed as the next-sibling
        pointer, because a use-site level root may already own an X chain
        and must not be mutated (append-only stream, shared subtrees)."""
        heads = []
        for r in roots:
            K, V0, V1, V2, _ = self.b.stream[r][:5]
            heads.append(self.b.push(K, V0=V0, V1=V1, V2=V2))
        for i, h in enumerate(heads):
            t = self.b.stream[h]
            self.b.stream[h] = (t[0], t[1], t[2], t[3],
                                heads[i + 1] if i + 1 < len(heads) else 0)
        return self.b.push(K_CONST, V0=cid, V1=heads[0] if heads else 0)

    def _inst_expr(self, p: int, mapping: dict) -> int:
        """D13/D14 instantiate_lparams (K/instantiate.cpp:232-246): replace
        only Sort levels and Constant level args; other nodes recurse and are
        rebuilt only if a child changed. Short-circuits Param-free subtrees
        (K/instantiate.cpp:233,238-239)."""
        if not mapping or not self._expr_has_param_univ(p):
            return p
        K, V0, V1, V2, X = self.b.stream[p][:5]
        if K == K_SORT:
            nl = self._inst_level(V0, mapping)
            if nl == V0:
                return p
            return self.b.push(K_SORT, V0=nl)
        if K == K_CONST:
            roots = self._const_level_args(V1)
            new = [self._inst_level(r, mapping) for r in roots]
            if new == roots:
                return p
            return self._rebuild_const(V0, new)
        if K == K_APP:
            f = self._inst_expr(V0, mapping)
            a = self._inst_expr(V1, mapping)
            if f == V0 and a == V1:
                return p
            return self.b.push(K_APP, V0=f, V1=a)
        if K in (K_LAM, K_PI):
            d = self._inst_expr(V0, mapping)
            b = self._inst_expr(V1, mapping)
            if d == V0 and b == V1:
                return p
            return self.b.push(K, V0=d, V1=b, X=X)   # X = binfo
        if K == K_LET:
            d = self._inst_expr(V0, mapping)
            v = self._inst_expr(V1, mapping)
            b = self._inst_expr(X, mapping)
            if d == V0 and v == V1 and b == X:
                return p
            return self.b.push(K_LET, V0=d, V1=v, X=b)
        if K == K_MDATA:
            c = self._inst_expr(V0, mapping)
            return p if c == V0 else self.b.push(K_MDATA, V0=c)
        if K == K_PROJ:
            c = self._inst_expr(X, mapping)
            return p if c == X else self.b.push(K_PROJ, V0=V0, V1=V1, X=c)
        return p

    def _emit_sort_at(self, lpos: int) -> tuple[int, int]:
        """Emit Sort l for the level tree at lpos."""
        return self.b.push(K_SORT, V0=lpos), 0

    def _emit_sort(self, n: int) -> tuple[int, int]:
        lpos = self.b.push(KL_ZERO)
        for _ in range(n):
            lpos = self.b.push(KL_SUCC, V0=lpos)
        return self.b.push(K_SORT, V0=lpos), 0

    def _sort_level_of(self, clo: tuple[int, int]) -> int:
        """ensure_sort (K/type_checker.cpp:62-71): whnf the (type-of-type)
        closure, expect K_SORT, return the stream position of its level."""
        pos, env = self.whnf(*clo)
        K, V0, V1, V2, X = self.b.stream[pos][:5]
        if K != K_SORT:
            raise VMError(ERR_TYPE, f"expected a sort (kind {K})")
        return V0

    def _instantiate_value(self, cid: int, lvl_head: int) -> int:
        """Delta unfolding of a polymorphic constant: instantiate_value_lparams
        (K/instantiate.cpp:256-264; use point K/type_checker.cpp:555-565). The
        result is cached per (cid, use-site level canonical form) so repeated
        whnf of the same use site does not rebuild the value tree."""
        vpos = self.b.const_value_pos.get(cid, 0)
        if not vpos:
            return vpos
        use = self._const_level_args(lvl_head)
        lps = self._const_lparam_nids(cid)
        if not use or not lps or not self._expr_has_param_univ(vpos):
            return vpos
        key = (cid, tuple(self._level_normal_form(u) for u in use))
        cached = self._val_inst_cache.get(key)
        if cached is None:
            if len(use) != len(lps):
                raise VMError(
                    ERR_TYPE,
                    "incorrect number of universe levels parameters for '%s'"
                    % self.b.cid_names.get(cid, cid))
            mapping = {lps[i]: use[i] for i in range(len(lps))}
            cached = self._inst_expr(vpos, mapping)
            self._val_inst_cache[key] = cached
        return cached

    def _infer_const(self, cid: int, lvl_head: int) -> tuple[int, int]:
        """Kernel infer_constant (K/type_checker.cpp:101-123):
          1. length(lparams) == length(const_levels(e)) else kernel_exception
             (K/type_checker.cpp:105-108);
          2. check_level on each use-site level (D11) when checking;
          3. return instantiate_type_lparams(info, ls) (D14,
             K/instantiate.cpp:248-254) — the declared type with LParam(name)
             replaced by the use-site level at the same position.
        The declaration's ordered lparams names come from T_ENV_UNIVPARAMS
        (VM_SPEC §12.1)."""
        if cid not in self.b.const_type_pos:
            raise VMError(ERR_MISSING_CONST, f"cid {cid}")
        use = self._const_level_args(lvl_head)
        lps = self._const_lparam_nids(cid)
        if len(lps) != len(use):
            raise VMError(
                ERR_TYPE,
                "incorrect number of universe levels parameters for '%s', "
                "#%d expected, #%d provided"
                % (self.b.cid_names.get(cid, cid), len(lps), len(use)))
        if self._decl_lparams is not None:
            for l in use:
                bad = self._get_undef_param(l, self._decl_lparams)
                if bad is not None:
                    raise VMError(
                        ERR_TYPE,
                        "invalid reference to undefined universe level "
                        "parameter '%s'" % self.b.id_names.get(bad, bad))
        tpos = self.b.const_type_pos[cid]
        if not use or not lps:
            return tpos, 0
        mapping = {lps[i]: use[i] for i in range(len(lps))}
        return self._inst_expr(tpos, mapping), 0

    def infer(self, pos: int, env: int) -> tuple[int, int]:
        """Kernel infer_type subset (checking mode). Returns the type as a
        closure (type_pos, type_env)."""
        b = self.b
        K, V0, V1, V2, X = b.stream[pos][:5]
        if K == K_BVAR:
            link = self._resolve(env, V0)
            if link[5] == 1:                  # binder marker: type = domain
                return link[1], link[4]
            return self.infer(link[1], link[4])   # value link (post-reduction)
        if K == K_CONST:
            return self._infer_const(V0, V1)
        if K == K_LIT:
            return self._emit_const("Nat"), 0     # lit_type: Nat
        if K == K_SORT:
            # kernel infer_sort (K/type_checker.cpp:345-347): type of Sort l
            # is Sort (succ l), built with the mk_succ smart constructor; the
            # level tree stays symbolic (may contain LParam).
            return self._emit_sort_at(self._mk_succ(V0))
        if K == K_APP:
            args = []
            p, e = pos, env
            while b.stream[p][0] == K_APP:        # peel the spine
                t = b.stream[p]
                args.append((t[2], e))            # V1 = arg
                p = t[1]                          # V0 = fn
            f_type = self.infer(p, e)
            for a_pos, a_env in reversed(args):   # application order
                f_type = self.whnf(*f_type)       # ensure_pi
                dom, body = self._pi_parts(f_type)
                a_type = self.infer(a_pos, a_env)
                if not self.defeq(a_type, dom):
                    raise VMError(ERR_TYPE,
                                  "infer_app: argument type mismatch")
                # instantiate(binding_body(f_type), app_arg): the arg closure
                # is LINKed onto the Pi body env (Krivine type substitution)
                b_pos, b_env = body
                f_type = (b_pos, self._link(a_pos, a_env, b_env))
            return f_type
        if K == K_LAM:
            self._sort_level_of(self.infer(V0, env))   # ensure_sort(domain)
            menv = self._link(V0, env, env, flag=1)    # binder marker
            b_t = self.infer(V1, menv)
            ppos = b.push(T_PI_CLO, V0=V0, V1=b_t[0], X=env, E2=b_t[1])
            return ppos, 0
        if K == K_PI:
            l1 = self._sort_level_of(self.infer(V0, env))
            menv = self._link(V0, env, env, flag=1)
            l2 = self._sort_level_of(self.infer(V1, menv))
            # kernel infer_pi (K/type_checker.cpp:160-165): fold
            # r = mk_imax(us[i], r) from inner binder to outer.
            return self._emit_sort_at(self._mk_imax(l1, l2))
        if K == K_LET:
            # V0=type, V1=value, X=body; kernel: defeq(val_type, type), local
            # decl of the declared type
            val_t = self.infer(V1, env)
            if not self.defeq(val_t, (V0, env)):
                raise VMError(ERR_TYPE, "infer_let: value type mismatch")
            menv = self._link(V0, env, env, flag=1)
            return self.infer(X, menv)
        if K == T_PI_CLO:
            # An inferred Pi type (infer of a lambda). infer_type of a Pi is
            # Sort (imax sort(dom) sort(cod)) (K/type_checker.cpp:160-165);
            # the body half already carries its binder marker env (E2).
            l1 = self._sort_level_of(self.infer(V0, X))
            l2 = self._sort_level_of(self.infer(V1, self.b.stream[pos][5]))
            return self._emit_sort_at(self._mk_imax(l1, l2))
        if K == K_PROJ:
            # kernel infer_proj (type_checker.cpp L247), monomorphic
            # non-rec subset: whnf(child type) must be the structure const
            # matching the proj sname; field type = domain of the
            # (nparams+idx)-th Pi of the ctor's type. Param'd structures
            # (instantiate_type_lparams) and dependent fields (kernel
            # instantiates later domains with mk_proj) are outside it; so
            # is the Prop-guard (is_prop_type && !is_prop(field)).
            s_ty = self.whnf(*self.infer(X, env))
            sK, sV0 = b.stream[s_ty[0]][:2]
            if sK != K_CONST:
                raise VMError(ERR_TYPE, "infer_proj: structure type expected")
            if b.cids.get(b.id_names.get(V0)) != sV0:
                raise VMError(ERR_TYPE, "infer_proj: proj sname != structure")
            ent = self.ctor_of_struct.get(sV0)
            if ent is None:
                raise VMError(ERR_TYPE, "infer_proj: not a structure")
            ctor_cid, nparams, _ = ent
            if nparams:
                raise VMError(ERR_UNSUPPORTED,
                              "infer_proj: structure params unsupported")
            r = self.whnf(*self.infer(self._emit_const(
                b.cid_names[ctor_cid]), 0))
            for _ in range(V1):            # peel earlier fields (non-dep)
                r = self.whnf(*r)
                _, r = self._pi_parts(r)
            r = self.whnf(*r)
            dom, _ = self._pi_parts(r)
            return dom
        raise VMError(ERR_UNSUPPORTED, f"infer: token kind {K} at {pos}")

    def _spine(self, pos: int, env: int) -> tuple[tuple, list]:
        args = []
        while self.b.stream[pos][0] == K_APP:
            t = self.b.stream[pos]
            args.append((t[2], env))              # V1 = arg
            pos = t[1]                            # V0 = fn
        return (pos, env), args

    def _match_ctor(self, wpos: int, wenv: int, ctors):
        """P7.2 casesOn major-premise matcher. `ctors` = [(ctor_cid, nfields)]
        in minor order. Returns (ctor_idx, fields) with fields in application
        order, or None if the major is not one of these constructors (stuck).
        Mirrors the kernel: nat literals are converted to constructor form
        first (nat_lit_to_constructor, inductive.h L94)."""
        K, V0, V1, V2, X = self.b.stream[wpos][:5]
        if K == K_LIT and V1 == LIT_NAT:
            v = sum(self.b.stream[wpos + 2 + 2 * i][1] * (10 ** i)
                    for i in range(V0))
            cid = self.cid_zero if v == 0 else self.cid_succ
            for idx, (cc, nf) in enumerate(ctors):
                if cc == cid:
                    fields = [] if v == 0 else [(self._emit_chain(v - 1), 0)]
                    return idx, fields
            return None
        if K == K_CONST:
            for idx, (cc, nf) in enumerate(ctors):
                if cc == V0 and nf == 0:
                    return idx, []
            return None
        if K == K_APP:
            head, rargs = self._spine(wpos, wenv)   # rargs = reverse app order
            hK, hV0, *_ = self.b.stream[head[0]][:5]
            if hK != K_CONST:
                return None
            fields_app = list(reversed(rargs))       # application order
            for idx, (cc, nf) in enumerate(ctors):
                if cc == hV0 and len(fields_app) >= nf:
                    return idx, fields_app[:nf]
        return None

    def _nat_ctor_value(self, pos: int, env: int):
        """Kernel reduce_nat/is_nat_expr analog (M1 subset): extract the Nat
        value of a closed ctor/literal form — K_LIT, Nat.zero, or a
        Nat.succ spine over an extractable arg. None = not nat-shaped."""
        K, V0, V1, V2, X = self.b.stream[pos][:5]
        if K == K_LIT and V1 == LIT_NAT:
            return self._chain_value(pos, env)
        if K == K_CONST and V0 == self.cid_zero:
            return 0
        if K == K_APP:
            head, args = self._spine(pos, env)
            hK, hV0, *_ = self.b.stream[head[0]][:5]
            cid_succ = self.b.cids.get("Nat.succ")
            if hK == K_CONST and hV0 == cid_succ and len(args) == 1:
                a = self._nat_ctor_value(*args[0])
                if a is not None:
                    return 1 + a
        return None

    def defeq(self, t: tuple[int, int], s: tuple[int, int]) -> bool:
        """Kernel is_def_eq subset (Phase 5 M1+M3): quick structural
        equality, whnf-both loop (beta/zeta/delta/nat all live in whnf),
        then on stuck forms: proof irrelevance, spine compare, eta
        expansion, structural eta."""
        b = self.b
        while True:
            t_pos, t_env = t
            s_pos, s_env = s
            if t_pos == s_pos and t_env == s_env:
                return True
            tT = b.stream[t_pos]
            sT = b.stream[s_pos]
            K, V0, V1, V2, X = tT[:5]
            K2, W0, W1, W2, X2 = sT[:5]

            if K == K2 and K == K_CONST and V0 == W0:
                # kernel is_def_eq_core const case (K/type_checker.cpp:1209-
                # 1211): same name AND is_def_eq(const_levels), where the
                # per-level relation is is_def_eq(level,level) = D4
                # (K/type_checker.h:88; K/type_checker.cpp:814-820,822-832).
                return self._levels_equivalent(V1, W1)
            if K == K2 and K == K_SORT:
                # kernel quick_is_def_eq Sort (K/type_checker.cpp:843-844) ->
                # is_def_eq(level,level) = D4.
                return self._level_is_equivalent(V0, W0)
            if (K == K2 and K == K_LIT and V1 == LIT_NAT and W1 == LIT_NAT):
                return self._chain_value(t_pos, 0) == \
                    self._chain_value(s_pos, 0)
            if K == K2 and K == K_PROJ:
                # kernel: same structure+idx → compare children lazily
                if V0 != W0 or V1 != W1:
                    return False
                t = (X, t_env)
                s = (X2, s_env)
                continue
            if K == K2 and K in (K_LAM, K_PI):
                # is_def_eq_binding: domains first, then ONE binder identity
                # shared by both sides (kernel mk_local_decl on a shared
                # lctx; here F2 = the t-side marker's position)
                if not self.defeq((V0, t_env), (W0, s_env)):
                    return False
                mt = self._link(V0, t_env, t_env, flag=1)
                self._stamp_bid(mt, mt)
                ms = self._link(W0, s_env, s_env, flag=1, bid=mt)
                return self.defeq((V1, mt), (W1, ms))
            if K == K2 and K == T_PI_CLO:
                # dom=(V0,X), body=(V1,E2)
                if not self.defeq((V0, X), (W0, X2)):
                    return False
                return self.defeq((V1, tT[5]), (W1, sT[5]))
            if K == K2 and K == K_BVAR:
                lt = self._resolve(t_env, V0)
                ls = self._resolve(s_env, W0)
                if lt[5] == 1 and ls[5] == 1:
                    if lt[6] and lt[6] == ls[6]:
                        return True     # same fvar (kernel name equality)
                    # distinct fvars: STUCK pair — fall through to the
                    # soft-whnf guard below (bvar markers don't move), which
                    # routes to proof-irrel / eta / stuck compare. (A plain
                    # `continue` here would loop forever: t and s unchanged.)
                else:
                    if lt[5] == 0:
                        t = (lt[1], lt[4])   # beta/zeta value substitution
                    if ls[5] == 0:
                        s = (ls[1], ls[4])
                    continue
            if K == K2 and K == K_MDATA:
                t = (V0, t_env)
                s = (W0, s_env)
                continue
            # cross-kind Pi shapes: K_PI tree vs T_PI_CLO (infer results).
            # Kernel is_def_eq_binding (K/type_checker.cpp:781-794): compare
            # domains in the current context, add ONE shared local decl
            # (mk_local_decl) and compare bodies under it.
            pi_t = K in (K_PI, T_PI_CLO)
            pi_s = K2 in (K_PI, T_PI_CLO)
            if pi_t and pi_s:
                # outer env = X for T_PI_CLO, the closure env for K_PI; the
                # body closure is (V1, E2) for T_PI_CLO (already the env the
                # infer-side body type lives in) and (V1, env) for K_PI.
                clo_t = K == T_PI_CLO
                clo_s = K2 == T_PI_CLO
                dom_env_t = X if clo_t else t_env
                dom_env_s = X2 if clo_s else s_env
                body_pos_t, body_env_t = V1, (tT[5] if clo_t else None)
                body_pos_s, body_env_s = W1, (sT[5] if clo_s else None)
                if not self.defeq((V0, dom_env_t), (W0, dom_env_s)):
                    return False
                # binder marker: K_PI gets a fresh marker over its outer env;
                # T_PI_CLO reuses its existing binder marker when E2 is one
                # marker-link deeper than X (so BVar0 already denotes the
                # binder). Unify the two marker bids (kernel shares the local
                # decl; deq_fvar_args / deq_fvar_swap_no pin that distinct
                # markers must stay distinct).
                mt = self._binder_marker(clo_t, V0, dom_env_t, body_env_t,
                                         body_pos_t)
                ms = self._binder_marker(clo_s, W0, dom_env_s, body_env_s,
                                         body_pos_s)
                if mt is not None and ms is not None:
                    bid = (self.b.stream[mt][6] or self.b.stream[ms][6] or mt)
                    self._stamp_bid(mt, bid)
                    self._stamp_bid(ms, bid)
                elif mt is not None and not self.b.stream[mt][6]:
                    self._stamp_bid(mt, mt)
                elif ms is not None and not self.b.stream[ms][6]:
                    self._stamp_bid(ms, ms)
                if clo_t:
                    env_t = body_env_t
                else:
                    env_t = mt if mt is not None else self._link(
                        V0, dom_env_t, dom_env_t, flag=1)
                if clo_s:
                    env_s = body_env_s
                else:
                    env_s = ms if ms is not None else self._link(
                        W0, dom_env_s, dom_env_s, flag=1)
                return self.defeq((body_pos_t, env_t), (body_pos_s, env_s))

            nt = self._soft_whnf(t_pos, t_env)
            ns = self._soft_whnf(s_pos, s_env)
            if nt == (t_pos, t_env) and ns == (s_pos, s_env):
                # both stuck — proof irrelevance first (kernel order:
                # is_def_eq_proof_irrel precedes app/eta/eta_struct)
                r = self._proof_irrel(nt, ns)
                if r is not None:
                    return r
                if K == K_APP and K2 == K_APP:
                    (tf, ta), (sf, sa) = self._spine(t_pos, t_env), \
                        self._spine(s_pos, s_env)
                    if len(ta) == len(sa) and self.defeq(tf, sf):
                        for (a, ae), (c, ce) in zip(ta, sa):
                            if not self.defeq((a, ae), (c, ce)):
                                break
                        else:
                            return True
                    # fall through: eta/eta_struct may still apply
                # Nat ctor form vs literal: kernel equates Nat.zero /
                # Nat.succ spines with literals via reduce_nat (Nat.zero ≡ 0)
                vt = self._nat_ctor_value(t_pos, t_env)
                vs = self._nat_ctor_value(s_pos, s_env)
                if vt is not None and vs is not None:
                    return vt == vs
                r = self._try_eta(nt, ns) or self._try_eta(ns, nt)
                if r is not None:
                    return r
                r = self._try_eta_struct(nt, ns) or \
                    self._try_eta_struct(ns, nt)
                if r is not None:
                    return r
                r = self._unit_like(nt, ns)
                if r is not None:
                    return r
                return False   # mixed stuck shapes
            t, s = nt, ns

    def check(self, decls) -> tuple[int, int]:
        """Kernel `check` driver loop (Phase 5 M4.2): per declaration,
        infer the value's type and defeq it against the declared type.
        decls: iterable of (type_root, val_root) stream positions, or
        (type_root, val_root, lparams) triples where lparams is the checked
        declaration's universe-parameter names (WP2 check_level, D11). Raises
        VMError(ERR_TYPE) on the first mismatch; returns (1, 0) when every
        declaration is accepted."""
        for i, decl in enumerate(decls):
            if len(decl) == 3:
                type_root, val_root, lps = decl
                self._decl_lparams = {
                    self.b.nid(n) if isinstance(n, str) else int(n)
                    for n in lps}
            else:
                type_root, val_root = decl
                self._decl_lparams = None
            t_pos, t_env = self.infer(val_root, 0)
            if not self.defeq((t_pos, t_env), (type_root, 0)):
                raise VMError(ERR_TYPE, f"decl {i}: value type mismatch")
        self._decl_lparams = None
        return (1, 0)

    def _stamp_bid(self, link_pos: int, bid: int) -> None:
        row = self.b.stream[link_pos]
        self.b.stream[link_pos] = row[:6] + (bid,)

    def _proof_irrel(self, t: tuple[int, int], s: tuple[int, int]):
        """Kernel is_def_eq_proof_irrel: if t's type is a Prop, t ≡ s iff
        their types are defeq. Returns True/False, or None when t is not a
        proof (or its type is outside the infer subset → l_undef)."""
        try:
            t_ty = self.infer(*t)
            # kernel is_prop (K/type_checker.cpp:383-389):
            # normalizes_to_zero(sort_level(ensure_sort(infer_type(e)))).
            ty_sort = self.infer(*t_ty)
            if not self._level_normalizes_to_zero(
                    self._sort_level_of(ty_sort)):
                return None
        except VMError as e:
            if e.code in (ERR_TYPE, ERR_UNSUPPORTED):
                return None
            raise
        s_ty = self.infer(*s)
        return self.defeq(t_ty, s_ty)

    def _try_eta(self, t: tuple[int, int], s: tuple[int, int]):
        """Kernel try_eta_expansion_core: t is a lambda, s is not → compare
        t against eta-expanded s = fun (x : dom) => s x. Returns
        True/False, or None when not applicable."""
        b = self.b
        if b.stream[t[0]][0] != K_LAM or b.stream[s[0]][0] == K_LAM:
            return None
        s_ty = self.whnf(*self.infer(*s))
        if b.stream[s_ty[0]][0] not in (K_PI, T_PI_CLO):
            return None
        dom_s, _ = self._pi_parts(s_ty)
        lamK, d_t, body_t = b.stream[t[0]][:3]
        if not self.defeq((d_t, t[1]), dom_s):
            return False
        # bodies: t's under one fresh marker M; s's side evaluates the
        # synthetic app `BVar(1) BVar(0)` under chain [M', L, t_env] where
        # L is a value link holding the s closure (BVar(1) → s, BVar(0) →
        # the shared binder) and M'.F2 = M (same binder identity)
        M = self._link(dom_s[0], dom_s[1], t[1], flag=1)
        self._stamp_bid(M, M)
        L = self._link(s[0], s[1], t[1], flag=0)
        M2 = self._link(dom_s[0], dom_s[1], L, flag=1, bid=M)
        bvar0 = b.push(K_BVAR, V0=0)
        bvar1 = b.push(K_BVAR, V0=1)
        app = b.push(K_APP, V0=bvar1, V1=bvar0)
        return self.defeq((body_t, M), (app, M2))

    def _try_eta_struct(self, t: tuple[int, int], s: tuple[int, int]):
        """Kernel try_eta_struct_core: s = ctor a_1..a_n fully applied (n =
        nparams+nfields) of a non-rec structure → t ≡ s iff their types are
        defeq and proj(t, i) ≡ a_i fieldwise. None = not applicable."""
        b = self.b
        head, args = self._spine(s[0], s[1])
        hK, hV0, *_ = b.stream[head[0]][:5]
        if hK != K_CONST:
            return None
        # head cid is the CTOR's → ctor→(ind cid, nparams, nfields)
        ent = self.struct_of_ctor.get(hV0)
        if ent is None:
            return None
        ind_cid, nparams, nfields = ent
        if len(args) != nparams + nfields:
            return None
        t_ty = self.infer(*t)
        s_ty = self.infer(*s)
        if not self.defeq(t_ty, s_ty):
            return False
        for i in range(nfields):
            ppos = b.push(K_PROJ, V0=b.nid(b.cid_names[ind_cid]), V1=i, X=t[0])
            # _spine yields args outermost-first: field i sits nfields-1-i
            # slots from the params prefix
            if not self.defeq((ppos, t[1]), args[nparams + nfields - 1 - i]):
                return False
        return True

    def _unit_like(self, t: tuple[int, int], s: tuple[int, int]):
        """Kernel is_def_eq_unit_like (type_checker.cpp L1159): if t's type
        whnf's to a non-rec structure whose single constructor has 0 fields,
        every element is equal → t ≡ s iff their types are defeq. Returns
        True/False, or None when t's type head is not a 0-field structure
        (proof-irrel already handled Prop; this covers Type-level subsingletons
        like `Unit`)."""
        b = self.b
        t_ty = self.infer(*t)
        head, _ = self._spine(*self.whnf(*t_ty))   # get_app_fn of the type
        hK, hV0, *_ = b.stream[head[0]][:5]
        if hK != K_CONST:
            return None
        ent = self.ctor_of_struct.get(hV0)
        if ent is None or ent[2] != 0:             # not a structure, or has fields
            return None
        s_ty = self.infer(*s)
        return self.defeq(t_ty, s_ty)
