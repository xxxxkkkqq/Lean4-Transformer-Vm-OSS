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
    StreamBundle, T_LINK, T_LIT_DIG, T_PI_CLO,
    NAT_OPS, NAT_OP_ARITY,
    TASK_WHNF,
)


class VMError(Exception):
    def __init__(self, code: int, detail: str = ""):
        super().__init__(f"VM reject {code}: {detail}")
        self.code = code


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
        self.cid_op = {}
        if nat_enabled:
            for name, cid in bundle.cids.items():
                if name in NAT_OPS:
                    self.cid_op[cid] = NAT_OPS[name]
        self.cid_zero = bundle.cids.get("Nat.zero")
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
        while True:
            K, V0, V1, V2, X = self.b.stream[pos][:5]
            if K == K_APP:
                if not pend:
                    spine_root = pos
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
                    pos = self.b.const_value_pos[V0]   # delta
                    env = 0                            # constants are closed
                    continue
                op = self.cid_op.get(V0)
                if op is not None and len(pend) >= NAT_OP_ARITY[op]:
                    # pend.pop() yields innermost-first, i.e. application
                    # order (arg1 was pushed last)
                    args = [pend.pop() for _ in range(NAT_OP_ARITY[op])]
                    vals = [self.whnf(a, aenv) for (a, aenv) in args]
                    return self._nat(op, vals), 0
                # stuck head: if args are pending, the result is the whole
                # original spine
                return (spine_root if pend and spine_root else pos), env
            if K == K_LET:                        # zeta
                env = self._link(V1, env, env)
                pos = X                           # body (X field, §4)
                continue
            if K == K_BVAR:
                link = self._resolve(env, V0)
                if link[5] == 1:
                    # binder marker (fvar analog): a variable is stuck in
                    # whnf, exactly like a kernel fvar without a value
                    return pos, env
                pos, env = link[1], link[4]   # (value pos, captured env)
                continue
            if K == K_MDATA:
                pos = V0                          # kernel ignores mdata
                continue
            if K == K_PROJ:
                # kernel whnf reduces `ctor a_1 ... a_n .idx` to a_idx
                # (reduce_proj_core subset: non-rec structure ctor directly;
                # delta through a struct-valued const handled by the K_CONST
                # case when we whnf the child here)
                cpos, cenv = self.whnf(X, env)
                st = self._proj_core(cpos, V0, V1)   # (V0=struct nid, V1=idx)
                if st is None:
                    return pos, env               # stuck proj
                return st, cenv
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

    def _level_int(self, lpos: int) -> int:
        """Decode a level token tree to an int (toy env: numeric levels only;
        LParam/LMVar → ERR_UNSUPPORTED)."""
        K, V0, V1, V2, X = self.b.stream[lpos][:5]
        if K == KL_ZERO:
            return 0
        if K == KL_SUCC:
            return 1 + self._level_int(V0)
        if K == KL_MAX:
            return max(self._level_int(V0), self._level_int(V1))
        if K == KL_IMAX:
            a, bb = self._level_int(V0), self._level_int(V1)
            return bb if a == 0 else max(a, bb)
        raise VMError(ERR_UNSUPPORTED, f"level kind {K}")

    def _emit_sort(self, n: int) -> tuple[int, int]:
        lpos = self.b.push(KL_ZERO)
        for _ in range(n):
            lpos = self.b.push(KL_SUCC, V0=lpos)
        return self.b.push(K_SORT, V0=lpos), 0

    def _sort_level_of(self, clo: tuple[int, int]) -> int:
        """ensure_sort: whnf the (type-of-type) closure, expect K_SORT,
        return its level int."""
        pos, env = self.whnf(*clo)
        K, V0, V1, V2, X = self.b.stream[pos][:5]
        if K != K_SORT:
            raise VMError(ERR_TYPE, f"expected a sort (kind {K})")
        return self._level_int(V0)

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
            if V0 not in b.const_type_pos:
                raise VMError(ERR_MISSING_CONST, f"cid {V0}")
            return b.const_type_pos[V0], 0
        if K == K_LIT:
            return self._emit_const("Nat"), 0     # lit_type: Nat
        if K == K_SORT:
            return self._emit_sort(self._level_int(V0) + 1)
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
            # imax over numeric levels (toy env)
            lvl = l2 if l1 == 0 else max(l1, l2)
            return self._emit_sort(lvl)
        if K == K_LET:
            # V0=type, V1=value, X=body; kernel: defeq(val_type, type), local
            # decl of the declared type
            val_t = self.infer(V1, env)
            if not self.defeq(val_t, (V0, env)):
                raise VMError(ERR_TYPE, "infer_let: value type mismatch")
            menv = self._link(V0, env, env, flag=1)
            return self.infer(X, menv)
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
                return True
            if K == K2 and K == K_SORT:
                return self._level_int(V0) == self._level_int(W0)
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
            # cross-kind Pi shapes: K_PI tree vs T_PI_CLO (infer results)
            pi_t = K in (K_PI, T_PI_CLO)
            pi_s = K2 in (K_PI, T_PI_CLO)
            if pi_t and pi_s:
                dom_t, body_t = self._pi_parts(t)
                dom_s, body_s = self._pi_parts(s)
                if not self.defeq(dom_t, dom_s):
                    return False
                # a raw K_PI side has no marker env yet; push one shared-id
                # marker per side so BVar(0) pairs up (a T_PI_CLO side
                # already carries its own marker one link deeper — deeper
                # bvars fall through to the general machinery)
                mt = self._link(dom_t[0], dom_t[1], body_t[1], flag=1)
                self._stamp_bid(mt, mt)
                ms = self._link(dom_s[0], dom_s[1], body_s[1], flag=1, bid=mt)
                return self.defeq((body_t[0], mt), (body_s[0], ms))

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
                return False   # mixed stuck shapes
            t, s = nt, ns

    def _stamp_bid(self, link_pos: int, bid: int) -> None:
        row = self.b.stream[link_pos]
        self.b.stream[link_pos] = row[:6] + (bid,)

    def _proof_irrel(self, t: tuple[int, int], s: tuple[int, int]):
        """Kernel is_def_eq_proof_irrel: if t's type is a Prop, t ≡ s iff
        their types are defeq. Returns True/False, or None when t is not a
        proof (or its type is outside the infer subset → l_undef)."""
        try:
            t_ty = self.infer(*t)
            # kernel is_prop: ensure_sort(infer_type(e)) then level→0
            ty_sort = self.infer(*t_ty)
            if self._sort_level_of(ty_sort) != 0:
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
