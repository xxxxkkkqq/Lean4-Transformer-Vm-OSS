"""Token-stream encoding per docs/VM_SPEC.md v1.

Stream = list of 5-field tokens (K, V0, V1, V2, X). Positions are stream
indices (0-based); 0 is a legal position (ENV starts there), so NULL is
represented by None on the Python side and by the "absent field" convention
in the spec (V1=0 for "no level args" is disambiguated by kind, not by 0=1).

Token-kind constants here extend expr/model.py's K_* constants; all numbers
are mirrored in VM_SPEC §2-§7.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from expr.model import (
    BVar, FVar, MVar, Sort, Const, App, Lam, Pi, Let, LitNat, LitStr,
    MData, Proj, Expr, Level,
    LZero, LSucc, LMax, LIMax, LParam, LMVar,
    K_BVAR, K_FVAR, K_MVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET,
    K_LIT, K_MDATA, K_PROJ,
    KL_ZERO, KL_SUCC, KL_MAX, KL_IMAX, KL_PARAM, KL_MVAR,
    BI_DEFAULT, LIT_NAT, LIT_STR,
)

# ── Non-expr token kinds (VM_SPEC §2-§7) ────────────────────────────────────

T_LIT_DIG = 13     # Nat digit-chain digit (V0 = 0..9, V2 = chain head)
# Digit-chain layout (stride 2): digit k of a chain with head H lives at
# position H+2+2k. Machine-emitted chains interleave one STATE token per
# micro-step, so digits are never contiguous; encoder/ref chains emit an
# explicit NULL gap token to match the same stride (VM_SPEC §5).
T_NAME = 21        # name-table entry (V0 = nid, V1 = parent nid, 0 = root)
T_ENV = 22         # ENV_HDR (V0=cid, V1=type root, V2=value root, X=flags)
T_ENV_META = 23    # ENV_META (V0 = univ_arity)
T_PEND = 30        # pending arg (Krivine stack; V0=arg, V2=prev, X=env head)
T_LINK = 31        # environment link (V0=value, V1=depth, V2=prev link, X=captured env)
T_FRAME = 32       # frame (V0=task, V1=focus, V2=caller, X=phase)
T_STATE = 33       # machine state (A..F fields; see VM_SPEC §10.1)
T_PI_CLO = 34      # machine-emitted Pi type whose two halves are closures:
                   # V0 = domain root, V1 = body root, X = domain env,
                   # E2 = body env (INFER of Lam pushes one; a plain K_PI at
                   # env e is equivalent to (V0,e),(V1,link(marker,e))).
T_OUT_VAL = 201    # task result (V0 = result pos)
T_ACCEPT = 202
T_REJECT = 203     # V0 = error code (VM_SPEC §7.4)
T_HALT = 204

# T_ENV flags
ENV_F_HAS_VALUE = 1
ENV_F_IS_CTOR = 2
ENV_F_IS_INDUCTIVE = 4
ENV_F_IS_RECURSOR = 8

# tasks (VM_SPEC §7; numbers match lean_vm/build_vm.py)
TASK_WHNF = 1      # whnf control frame (delivery vs halt; E2=1 = soft)
TASK_NAT = 2
TASK_WALK = 3
TASK_ST = 5        # storage/continuation frame (F2 = continuation id)
TASK_INFER = 6
TASK_DEFEQ = 7
TASK_LEVEL = 8     # level-tree int scan (acc in X)
TASK_CHECK = 9

# Nat operations (identified by constant name)
NAT_OPS = {
    "Nat.succ": "succ", "Nat.pred": "pred", "Nat.add": "add",
    "Nat.sub": "sub", "Nat.mul": "mul", "Nat.pow": "pow",
    "Nat.div": "div", "Nat.mod": "mod",
    "Nat.beq": "beq", "Nat.ble": "ble",
}
NAT_OP_ARITY = {"succ": 1, "pred": 1, "add": 2, "sub": 2, "mul": 2,
                "pow": 2, "div": 2, "mod": 2, "beq": 2, "ble": 2}
NAT_OP_CODES = {"Nat.succ": 1, "Nat.pred": 2, "Nat.add": 3, "Nat.sub": 4,
                "Nat.mul": 5, "Nat.pow": 6, "Nat.div": 7, "Nat.mod": 8,
                "Nat.beq": 9, "Nat.ble": 10}


def _digit_chain(value: int) -> list[int]:
    """Little-endian decimal digits of a non-negative int (canonical: no
    leading zeros; value 0 -> [0])."""
    if value == 0:
        return [0]
    out = []
    while value:
        out.append(value % 10)
        value //= 10
    return out


@dataclass
class StreamBundle:
    """A token stream plus its tables."""
    stream: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    name_ids: dict[str, int] = field(default_factory=dict)      # name -> nid
    id_names: dict[int, str] = field(default_factory=dict)      # nid -> name
    cids: dict[str, int] = field(default_factory=dict)          # const -> cid
    cid_names: dict[int, str] = field(default_factory=dict)
    const_type_pos: dict[int, int] = field(default_factory=dict)  # cid -> type root
    const_value_pos: dict[int, int] = field(default_factory=dict) # cid -> value root (or -1)
    const_univ_arity: dict[int, int] = field(default_factory=dict)
    const_has_value: dict[int, bool] = field(default_factory=dict)
    const_is_ctor: dict[int, bool] = field(default_factory=dict)

    def push(self, K, V0=0, V1=0, V2=0, X=0, E2=0, F2=0) -> int:
        self.stream.append((K, V0, V1, V2, X, E2, F2))
        return len(self.stream) - 1

    def nid(self, name: str) -> int:
        if name not in self.name_ids:
            i = len(self.name_ids) + 1
            self.name_ids[name] = i
            self.id_names[i] = name
            self.push(T_NAME, V0=i)
        return self.name_ids[name]


class Encoder:
    """Encodes a toy environment (constant list) and proof terms into a
    StreamBundle per VM_SPEC §3-§5."""

    def __init__(self, consts: list[tuple[str, Expr, Optional[Expr]]],
                 is_ctor: Optional[dict[str, bool]] = None):
        self.b = StreamBundle()
        self.is_ctor = dict(is_ctor) if isinstance(is_ctor, dict) else {}
        # pass 1: NULL token at position 0 (queries keyed 0 match it; all
        # consumers gate on position >= 1), then the ENV_HDR block.
        # Layout (VM_SPEC §3, C-scheme): ALL ENV_HDR tokens occupy positions
        # 1..n_consts so the VM can fetch the header for const cid with a
        # single position-keyed lookup (query = cid + 1). The NAME table and
        # the trees/META follow (names must NOT precede the header block —
        # an earlier version pushed names first and the pass-2 header
        # rewrite clobbered them; the X opcode field was lost, 2026-08-30).
        # The VM reads nat-op code from the header's X field and derives
        # has_value from value_root >= 1.
        self.b.push(0)                      # T_NULL
        for cid, (name, ty, val) in enumerate(consts):
            self.b.cids[name] = cid
            self.b.cid_names[cid] = name
            self.b.push(T_ENV, V0=cid, V1=0, V2=0,
                        X=NAT_OP_CODES.get(name, 0))
        # pass 2: register all names (contiguous NAME table after the ENV
        # block) so tree encoding finds them pre-registered
        for name, ty, val in consts:
            self.b.nid(name)
            self._collect_names(ty)
            if val is not None:
                self._collect_names(val)
        # pass 3: encode type/value trees, then point the headers at them
        for cid, (name, ty, val) in enumerate(consts):
            tpos = self._enc_expr(ty, cid + 1)
            vpos = self._enc_expr(val, cid + 1) if val is not None else 0
            hdr = cid + 1
            X = self.b.stream[hdr][4]
            self.b.stream[hdr] = (T_ENV, cid, tpos, vpos, X, 0, 0)
            self.b.push(T_ENV_META, V0=0)
            self.b.const_type_pos[cid] = tpos
            self.b.const_value_pos[cid] = vpos
            self.b.const_univ_arity[cid] = 0   # v1: monomorphic (§9.2)
            self.b.const_has_value[cid] = val is not None
            self.b.const_is_ctor[cid] = self.is_ctor.get(name, False)

    # -- name collection -----------------------------------------------------
    def _collect_names(self, e):
        if isinstance(e, (FVar, MVar)):
            self.b.nid(e.name)
        elif isinstance(e, Proj):
            self.b.nid(e.sname)
        elif isinstance(e, Const):
            self.b.nid(e.name)
            for l in e.levels:
                self._collect_level_names(l)
        elif isinstance(e, App):
            self._collect_names(e.fn); self._collect_names(e.arg)
        elif isinstance(e, (Lam, Pi)):
            self._collect_names(e.domain); self._collect_names(e.body)
        elif isinstance(e, Let):
            self._collect_names(e.domain); self._collect_names(e.value)
            self._collect_names(e.body)
        elif isinstance(e, (MData,)):
            self._collect_names(e.child)
        # BVar/Sort/Lit*: no names (Sort levels handled below)

    def _collect_level_names(self, l):
        if isinstance(l, (LParam, LMVar)):
            self.b.nid(l.name)
        elif isinstance(l, LSucc):
            self._collect_level_names(l.l)
        elif isinstance(l, (LMax, LIMax)):
            self._collect_level_names(l.a); self._collect_level_names(l.b)

    # -- encoding ------------------------------------------------------------
    def encode_term(self, e: Expr) -> int:
        """Append an expression tree after the ENV region; returns its root
        position."""
        return self._enc_expr(e, None)

    def _enc_expr(self, e: Expr, parent: Optional[int]) -> int:
        b = self.b
        if isinstance(e, BVar):
            return b.push(K_BVAR, V0=e.idx, V2=_p(parent))
        if isinstance(e, FVar):
            return b.push(K_FVAR, V0=b.nid(e.name), V2=_p(parent))
        if isinstance(e, MVar):
            return b.push(K_MVAR, V0=b.nid(e.name), V2=_p(parent))
        if isinstance(e, Sort):
            spos = b.push(K_SORT, V0=0, V2=_p(parent))
            lpos = self._enc_level(e.level, parent_pos=None)
            _fix_parent(b.stream, lpos, spos)
            t = b.stream[spos]
            b.stream[spos] = (t[0], lpos) + tuple(t[2:])
            return spos
        if isinstance(e, Const):
            cpos = b.push(K_CONST, V0=b.cids[e.name], V2=_p(parent))
            if e.levels:
                roots = [self._enc_level(l, parent_pos=cpos) for l in e.levels]
                for i, r in enumerate(roots):
                    nxt = roots[i + 1] if i + 1 < len(roots) else 0
                    t = b.stream[r]
                    b.stream[r] = (t[0], t[1], t[2], t[3], nxt) + tuple(t[5:])
                b.stream[cpos] = (K_CONST, b.cids[e.name], roots[0],
                                  _p(parent), 0, 0, 0)
            return cpos
        if isinstance(e, App):
            fpos = self._enc_expr(e.fn, None)
            apos = self._enc_expr(e.arg, None)
            pos = b.push(K_APP, V0=fpos, V1=apos, V2=_p(parent))
            _fix_parent(b.stream, fpos, pos)
            _fix_parent(b.stream, apos, pos)
            return pos
        if isinstance(e, (Lam, Pi)):
            K = K_LAM if isinstance(e, Lam) else K_PI
            dpos = self._enc_expr(e.domain, None)
            bpos = self._enc_expr(e.body, None)
            pos = b.push(K, V0=dpos, V1=bpos, V2=_p(parent), X=e.binfo)
            _fix_parent(b.stream, dpos, pos)
            _fix_parent(b.stream, bpos, pos)
            return pos
        if isinstance(e, Let):
            tpos = self._enc_expr(e.domain, None)
            vpos = self._enc_expr(e.value, None)
            bpos = self._enc_expr(e.body, None)
            pos = b.push(K_LET, V0=tpos, V1=vpos, V2=_p(parent), X=bpos)
            _fix_parent(b.stream, tpos, pos)
            _fix_parent(b.stream, vpos, pos)
            _fix_parent(b.stream, bpos, pos)
            return pos
        if isinstance(e, LitNat):
            digits = _digit_chain(e.value)
            head = b.push(K_LIT, V0=len(digits), V1=LIT_NAT, V2=_p(parent))
            for d in digits:
                b.push(0)                      # stride-2 gap (VM_SPEC §5)
                b.push(T_LIT_DIG, V0=d, V2=head)
            return head
        if isinstance(e, LitStr):
            raise NotImplementedError("LIT_STR not supported in v1 (VM_SPEC §5)")
        if isinstance(e, MData):
            cpos = self._enc_expr(e.child, None)
            pos = b.push(K_MDATA, V0=cpos, V2=_p(parent))
            _fix_parent(b.stream, cpos, pos)
            return pos
        if isinstance(e, Proj):
            cpos = self._enc_expr(e.child, None)
            pos = b.push(K_PROJ, V0=b.nid(e.sname), V1=e.idx, V2=_p(parent),
                         X=cpos)
            _fix_parent(b.stream, cpos, pos)
            return pos
        raise TypeError(type(e))

    def _enc_level(self, l: Level, parent_pos: Optional[int]) -> int:
        b = self.b
        if isinstance(l, LZero):
            return b.push(KL_ZERO, V2=_p(parent_pos))
        if isinstance(l, LSucc):
            c = self._enc_level(l.l, None)
            pos = b.push(KL_SUCC, V0=c, V2=_p(parent_pos))
            _fix_parent(b.stream, c, pos)
            return pos
        if isinstance(l, (LMax, LIMax)):
            K = KL_MAX if isinstance(l, LMax) else KL_IMAX
            a = self._enc_level(l.a, None)
            c = self._enc_level(l.b, None)
            pos = b.push(K, V0=a, V1=c, V2=_p(parent_pos))
            _fix_parent(b.stream, a, pos)
            _fix_parent(b.stream, c, pos)
            return pos
        if isinstance(l, LParam):
            return b.push(KL_PARAM, V0=b.nid(l.name), V2=_p(parent_pos))
        if isinstance(l, LMVar):
            return b.push(KL_MVAR, V0=b.nid(l.name), V2=_p(parent_pos))
        raise TypeError(type(l))

    def _enc_level_args(self, ty: Expr) -> int:
        """Count Pi binders of the constant's type (universe-param arity
        proxy: v1 toy env uses univ_arity=0 for all constants; the real
        level-arg count comes from the const's own level args, not its type.
        See VM_SPEC §9.2)."""
        n = 0
        while isinstance(ty, Pi):
            n += 1
            ty = ty.body
        return 0  # v1: all toy constants are monomorphic (univ_arity = 0)


def _p(parent: Optional[int]) -> int:
    return parent if parent is not None else 0


def _fix_parent(stream, child: int, parent: int):
    t = stream[child]
    if t[3] == 0:
        stream[child] = (t[0], t[1], t[2], parent) + tuple(t[4:])


# ── Decoding ────────────────────────────────────────────────────────────────

def decode_expr(b: StreamBundle, pos: int, depth: int = 0) -> Expr:
    """Reconstruct an Expr from the stream (de Bruijn decode). Closed terms
    only: bvar indices above the current binder depth indicate an encoding
    bug."""
    K, V0, V1, V2, X = b.stream[pos][:5]
    if K == K_BVAR:
        return BVar(V0)
    if K == K_FVAR:
        return FVar(b.id_names[V0])
    if K == K_MVAR:
        return MVar(b.id_names[V0])
    if K == K_SORT:
        return Sort(decode_level(b, V0))
    if K == K_CONST:
        levels = []
        r = V1
        while r:
            levels.append(decode_level(b, r))
            r = b.stream[r][4]   # sibling chain in X
        return Const(b.cid_names[V0], tuple(levels))
    if K == K_APP:
        return App(decode_expr(b, V0, depth), decode_expr(b, V1, depth))
    if K == K_LAM:
        return Lam("", X, decode_expr(b, V0, depth),
                   decode_expr(b, V1, depth + 1))
    if K == K_PI:
        return Pi("", X, decode_expr(b, V0, depth),
                  decode_expr(b, V1, depth + 1))
    if K == K_LET:
        return Let("", decode_expr(b, V0, depth), decode_expr(b, V1, depth),
                   decode_expr(b, X, depth + 1))
    if K == K_LIT:
        if V1 == LIT_NAT:
            n = V0
            value = 0
            for i in range(n):
                d = b.stream[pos + 2 + 2 * i][1]
                value += d * (10 ** i)
            return LitNat(value)
        raise NotImplementedError("LIT_STR decode not supported in v1")
    if K == K_MDATA:
        return MData(decode_expr(b, V0, depth))
    if K == K_PROJ:
        return Proj(b.id_names[V0], V1, decode_expr(b, X, depth))
    if K == T_LIT_DIG:
        raise ValueError(f"digit token at {pos} outside a chain")
    raise ValueError(f"unknown token kind {K} at {pos}")


def decode_closure(b: StreamBundle, pos: int, env: int = 0,
                   depth: int = 0) -> Expr:
    """Decode a closure (result position + link-chain environment):
    BVar(i) with i < depth is locally bound; i >= depth resolves through
    the LINK chain (i - depth steps back from env)."""
    K, V0, V1, V2, X = b.stream[pos][:5]
    if K == K_BVAR:
        if V0 < depth:
            return BVar(V0)
        cur = env
        steps = V0 - depth
        for _ in range(steps):
            cur = b.stream[cur][3]
            if not cur:
                raise ValueError(f"decode_closure: bvar {V0} beyond env")
        link = b.stream[cur]
        return decode_closure(b, link[1], link[4], 0)
    if K == K_APP:
        return App(decode_closure(b, V0, env, depth),
                   decode_closure(b, V1, env, depth))
    if K == K_LAM:
        return Lam("", X, decode_closure(b, V0, env, depth),
                   decode_closure(b, V1, env, depth + 1))
    if K == K_PI:
        return Pi("", X, decode_closure(b, V0, env, depth),
                  decode_closure(b, V1, env, depth + 1))
    if K == K_MDATA:
        return MData(decode_closure(b, V0, env, depth))
    if K == T_PI_CLO:
        # machine-emitted Pi type: X = domain env, E2 = body env
        return Pi("", 0, decode_closure(b, V0, X, depth),
                  decode_closure(b, V1, b.stream[pos][5], depth + 1))
    if K == K_LET:
        return Let("", decode_closure(b, V0, env, depth),
                   decode_closure(b, V1, env, depth),
                   decode_closure(b, X, env, depth + 1))
    # everything else has no bvar-bearing children affected by env
    return decode_expr(b, pos, depth)


def decode_level(b: StreamBundle, pos: int) -> Level:
    K, V0, V1, V2, X = b.stream[pos][:5]
    if K == KL_ZERO:
        return LZero()
    if K == KL_SUCC:
        return LSucc(decode_level(b, V0))
    if K == KL_MAX:
        return LMax(decode_level(b, V0), decode_level(b, V1))
    if K == KL_IMAX:
        return LIMax(decode_level(b, V0), decode_level(b, V1))
    if K == KL_PARAM:
        return LParam(b.id_names[V0])
    if K == KL_MVAR:
        return LMVar(b.id_names[V0])
    raise ValueError(f"unknown level kind {K} at {pos}")
