"""Expr / Level data model — mirrors lean4/src/kernel/{expr.h,level.h} exactly.

Source of truth (local lean4 master, version 4.35, file expr.h:66-85):

    inductive Expr
    | bvar    : Nat → Expr                                -- bound variables
    | fvar    : Name → Expr                               -- free variables
    | mvar    : Name → Expr                               -- meta variables
    | sort    : Level → Expr                              -- Sort
    | const   : Name → List Level → Expr                  -- constants
    | app     : Expr → Expr → Expr                        -- application
    | lam     : Name → BinderInfo → Expr → Expr → Expr    -- lambda abstraction
    | forallE : Name → BinderInfo → Expr → Expr → Expr    -- (dependent) arrow
    | letE    : Name → Expr → Expr → Expr → Bool → Expr   -- let expressions
    | lit     : Literal → Expr                            -- literals
    | mdata   : MData → Expr → Expr                       -- metadata
    | proj    : Name → Nat → Expr → Expr                  -- projection

    enum class expr_kind { BVar, FVar, MVar, Sort, Const, App,
                           Lambda, Pi, Let, Lit, MData, Proj };

level.h:20-26:

    inductive level
    | zero | succ (l) | max (a b) | imax (a b) | param (n) | mvar (n)

    enum class level_kind { Zero, Succ, Max, IMax, Param, MVar };

Conventions:
  - Names are plain strings ("."-joined) — tooling only. The token layer
    (expr/tokens.py) maps names to integer name-ids (nids); kernel VM logic
    never sees strings.
  - Binder info values match the C++ enum order (expr.h:21).
  - Kind constants are 1-based over the C++ enum order and are THE canonical
    token-layer K values used by docs/VM_SPEC.md, expr/tokens.py and
    lean_vm/. Do not renumber them anywhere else.
  - Nodes are frozen dataclasses: structural equality == kernel alpha
    equality for closed terms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# ── Canonical kind constants (token-layer K values) ─────────────────────────
# 1-based over C++ expr_kind enum order (expr.h:84).
K_BVAR = 1
K_FVAR = 2
K_MVAR = 3
K_SORT = 4
K_CONST = 5
K_APP = 6
K_LAM = 7
K_PI = 8
K_LET = 9
K_LIT = 10
K_MDATA = 11
K_PROJ = 12
EXPR_KIND_NAMES = {
    K_BVAR: "bvar", K_FVAR: "fvar", K_MVAR: "mvar", K_SORT: "sort",
    K_CONST: "const", K_APP: "app", K_LAM: "lam", K_PI: "pi", K_LET: "let",
    K_LIT: "lit", K_MDATA: "mdata", K_PROJ: "proj",
}

# 1-based over C++ level_kind enum order (level.h:30).
KL_ZERO = 1
KL_SUCC = 2
KL_MAX = 3
KL_IMAX = 4
KL_PARAM = 5
KL_MVAR = 6
LEVEL_KIND_NAMES = {
    KL_ZERO: "zero", KL_SUCC: "succ", KL_MAX: "max", KL_IMAX: "imax",
    KL_PARAM: "param", KL_MVAR: "mvar",
}

# binder_info enum order (expr.h:21).
BI_DEFAULT = 0
BI_IMPLICIT = 1
BI_STRICT_IMPLICIT = 2
BI_INST_IMPLICIT = 3
BI_REC = 4

# literal_kind (expr.h:24).
LIT_NAT = 0
LIT_STR = 1


# ── Levels ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LZero:
    pass

@dataclass(frozen=True)
class LSucc:
    l: "Level"

@dataclass(frozen=True)
class LMax:
    a: "Level"
    b: "Level"

@dataclass(frozen=True)
class LIMax:
    a: "Level"
    b: "Level"

@dataclass(frozen=True)
class LParam:
    name: str

@dataclass(frozen=True)
class LMVar:
    name: str

Level = LZero | LSucc | LMax | LIMax | LParam | LMVar


# ── Level normalize (faithful port of K/level.cpp, ADR 026) ─────────────────
# Canonical-by-construction boundary for graph-entering level trees: the
# encoder runs every level through this before emission, so the graph holds
# exactly normalize(<kernel-side term>) and deq degrades to structural
# comparison (is_equivalent = lhs == rhs || normalize(lhs) == normalize(rhs),
# K/level.cpp:518-521 — with both sides already normalized the second
# disjunct is the structural one).
#
# FAITHFULNESS CONSTRAINT (ADR 026 review pin, lvl_xc row): normalize is
# ONE-SHOT and path-asymmetric — the IMax base recurses through the smart
# mk_imax/mk_max constructors and never re-enters the max flattening, so
# e.g. normalize(imax (succ u) 1) = max (succ u) 1 (source order, explicit
# NOT absorbed) while normalize(max (succ u) 1) = succ u.  Idealized ACI
# rewriting is a soundness bug here, not a simplification.
#
# `key` maps a Param/MVar name to the graph nid (the encoder's fixed total
# order).  Judgment equivalence is order-key-independent (equal multisets
# sort equal under any fixed total order), but the graph-held FORM must use
# the same key at every boundary so encoder and fold emissions agree.

def _lvl_to_offset(l: Level) -> tuple[Level, int]:
    """K/level.cpp:67-74 to_offset: peel the succ spine."""
    k = 0
    while isinstance(l, LSucc):
        l = l.l
        k += 1
    return l, k


def _lvl_is_explicit(l: Level) -> bool:
    """K/level.cpp:54-61 is_explicit: succ^k(zero)."""
    if isinstance(l, LZero):
        return True
    if isinstance(l, LSucc):
        return _lvl_is_explicit(l.l)
    return False


def _lvl_is_not_zero(l: Level) -> bool:
    """K/level.cpp:160-172 is_not_zero (syntactic, not n2z)."""
    if isinstance(l, (LZero, LParam, LMVar)):
        return False
    if isinstance(l, LSucc):
        return True
    if isinstance(l, LMax):
        return _lvl_is_not_zero(l.a) or _lvl_is_not_zero(l.b)
    if isinstance(l, LIMax):
        return _lvl_is_not_zero(l.b)
    raise TypeError(l)


def _lvl_is_one(l: Level) -> bool:
    """K/level.cpp:106-110 syntactic one (l == mk_level_one())."""
    return isinstance(l, LSucc) and isinstance(l.l, LZero)


def _lvl_depth(l: Level) -> int:
    """get_depth for the explicit-pair rule only: succ-spine length."""
    d = 0
    while isinstance(l, LSucc):
        l = l.l
        d += 1
    return d


def _lvl_mk_succ_n(l: Level, k: int) -> Level:
    """K/level.cpp:449-453 mk_succ(l, k): raw wrap, no smart rules."""
    for _ in range(k):
        l = LSucc(l)
    return l


def _lvl_push_max_args(l: Level, out: list) -> None:
    """K/level.cpp:417-423: split nested top-level maxes."""
    if isinstance(l, LMax):
        _lvl_push_max_args(l.a, out)
        _lvl_push_max_args(l.b, out)
    else:
        out.append(l)


def _lvl_mk_max(l1: Level, l2: Level) -> Level:
    """K/level.cpp:81-104 smart mk_max, rule order verbatim."""
    if _lvl_is_explicit(l1) and _lvl_is_explicit(l2):
        return l1 if _lvl_depth(l1) >= _lvl_depth(l2) else l2
    if l1 == l2:
        return l1
    if isinstance(l1, LZero):
        return l2
    if isinstance(l2, LZero):
        return l1
    if isinstance(l2, LMax) and (l2.a == l1 or l2.b == l1):
        return l2
    if isinstance(l1, LMax) and (l1.a == l2 or l1.b == l2):
        return l1
    b1, k1 = _lvl_to_offset(l1)
    b2, k2 = _lvl_to_offset(l2)
    if b1 == b2:
        # kernel asserts k1 != k2 here: equal bases with equal offsets
        # were caught by the l1 == l2 rule above.
        return l1 if k1 > k2 else l2
    return LMax(l1, l2)


def _lvl_mk_imax(l1: Level, l2: Level) -> Level:
    """K/level.cpp:106-123 smart mk_imax, rule order verbatim."""
    if _lvl_is_not_zero(l2):
        return _lvl_mk_max(l1, l2)
    if isinstance(l2, LZero):
        return l2
    if isinstance(l1, LZero) or _lvl_is_one(l1):
        return l2
    if l1 == l2:
        return l1
    return LIMax(l1, l2)


def _lvl_lt_key(l: Level, key) -> tuple:
    """Total-order key mirroring is_norm_lt (K/level.cpp:393-415): primary
    the succ-peeled base (kind order KL_* preserves the kernel enum, then
    Param/MVar name via `key`, then recursive lhs/rhs for Max/IMax bases),
    secondary the succ offset.  Two terms are key-equal iff structurally
    equal, so tuple comparison is faithful to the kernel comparator."""
    base, off = _lvl_to_offset(l)
    if isinstance(base, LZero):
        bk = (KL_ZERO,)
    elif isinstance(base, LParam):
        bk = (KL_PARAM, key(base.name))
    elif isinstance(base, LMVar):
        bk = (KL_MVAR, key(base.name))
    elif isinstance(base, LMax):
        bk = (KL_MAX, _lvl_lt_key(base.a, key), _lvl_lt_key(base.b, key))
    elif isinstance(base, LIMax):
        bk = (KL_IMAX, _lvl_lt_key(base.a, key), _lvl_lt_key(base.b, key))
    else:
        raise TypeError(base)
    return (bk, off)


def level_normalize(l: Level, key) -> Level:
    """K/level.cpp:454-516 normalize, verbatim port (see module comment for
    the one-shot asymmetry constraint)."""
    base, k = _lvl_to_offset(l)
    if isinstance(base, (LZero, LParam, LMVar)):
        return l
    if isinstance(base, LIMax):
        l1 = level_normalize(base.a, key)
        l2 = level_normalize(base.b, key)
        return _lvl_mk_succ_n(_lvl_mk_imax(l1, l2), k)
    # Max base: flatten, normalize each arg, sort, explicit subsumption,
    # same-base dedup, re-wrap the succ spine onto each survivor (succ
    # distributes over the flattened set — normalize(succ (max u v)) is
    # max (succ u) (succ v), NOT succ (max u v)), right-fold rebuild.
    todo: list = []
    _lvl_push_max_args(base, todo)
    args: list = []
    for a in todo:
        _lvl_push_max_args(level_normalize(a, key), args)
    args.sort(key=lambda x: _lvl_lt_key(x, key))
    rargs: list = []
    i = 0
    if args and _lvl_is_explicit(args[i]):
        # keep only the largest explicit; drop it too when any surviving
        # arg's offset reaches it (K/level.cpp:477-486 + :487-499)
        while i + 1 < len(args) and _lvl_is_explicit(args[i + 1]):
            i += 1
        kk = _lvl_to_offset(args[i])[1]
        j = i + 1
        while j < len(args):
            if _lvl_to_offset(args[j])[1] >= kk:
                break
            j += 1
        if j < len(args):
            i += 1
    rargs.append(args[i])
    p_prev = _lvl_to_offset(args[i])
    i += 1
    while i < len(args):
        p_curr = _lvl_to_offset(args[i])
        if p_prev[0] == p_curr[0]:
            if p_prev[1] < p_curr[1]:
                p_prev = p_curr
                rargs.pop()
                rargs.append(args[i])
        else:
            p_prev = p_curr
            rargs.append(args[i])
        i += 1
    rargs = [_lvl_mk_succ_n(a, k) for a in rargs]
    r = rargs[-1]
    for a in reversed(rargs[:-1]):
        r = _lvl_mk_max(a, r)
    return r


def expr_normalize_levels(e: "Expr", key) -> "Expr":
    """Apply level_normalize to every level subtree of an Expr (Sort levels
    and Const level-arg chains) — the post-beat-B round-trip expectation:
    encode-then-decode reproduces the source term up to this rewrite."""
    if isinstance(e, Sort):
        return Sort(level_normalize(e.level, key))
    if isinstance(e, Const):
        return Const(e.name, tuple(level_normalize(l, key) for l in e.levels))
    if isinstance(e, App):
        return App(expr_normalize_levels(e.fn, key),
                   expr_normalize_levels(e.arg, key))
    if isinstance(e, (Lam, Pi)):
        return type(e)(e.name, e.binfo, expr_normalize_levels(e.domain, key),
                       expr_normalize_levels(e.body, key))
    if isinstance(e, Let):
        return Let(e.name, expr_normalize_levels(e.domain, key),
                   expr_normalize_levels(e.value, key),
                   expr_normalize_levels(e.body, key))
    return e


# ── Expressions ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BVar:
    """De Bruijn index (0 = innermost binder)."""
    idx: int

@dataclass(frozen=True)
class FVar:
    name: str

@dataclass(frozen=True)
class MVar:
    name: str

@dataclass(frozen=True)
class Sort:
    level: Level

@dataclass(frozen=True)
class Const:
    name: str
    levels: Tuple[Level, ...] = ()

@dataclass(frozen=True)
class App:
    fn: "Expr"
    arg: "Expr"

@dataclass(frozen=True)
class Lam:
    name: str
    binfo: int          # BI_* constant
    domain: "Expr"
    body: "Expr"

@dataclass(frozen=True)
class Pi:
    name: str
    binfo: int
    domain: "Expr"
    body: "Expr"

@dataclass(frozen=True)
class Let:
    name: str
    domain: "Expr"      # bound variable type
    value: "Expr"
    body: "Expr"
    nondep: bool = False   # mk_let's Bool (expr.h:224)

@dataclass(frozen=True)
class LitNat:
    value: int          # arbitrary precision (kernel `nat` is GMP-backed)

@dataclass(frozen=True)
class LitStr:
    value: str

@dataclass(frozen=True)
class MData:
    """Kernel reduction ignores mdata wrappers entirely."""
    child: "Expr"

@dataclass(frozen=True)
class Proj:
    sname: str          # structure name
    idx: int            # 0-based constructor field index (expr.h:197)
    child: "Expr"

Expr = (BVar | FVar | MVar | Sort | Const | App | Lam | Pi
        | Let | LitNat | LitStr | MData | Proj)


# ── Helpers ─────────────────────────────────────────────────────────────────

def kind_of(e: Expr) -> int:
    """Canonical K constant of an expression node."""
    return {
        BVar: K_BVAR, FVar: K_FVAR, MVar: K_MVAR, Sort: K_SORT,
        Const: K_CONST, App: K_APP, Lam: K_LAM, Pi: K_PI, Let: K_LET,
        LitNat: K_LIT, LitStr: K_LIT, MData: K_MDATA, Proj: K_PROJ,
    }[type(e)]


def level_kind_of(l: Level) -> int:
    return {
        LZero: KL_ZERO, LSucc: KL_SUCC, LMax: KL_MAX, LIMax: KL_IMAX,
        LParam: KL_PARAM, LMVar: KL_MVAR,
    }[type(l)]


def lit_kind_of(e: "LitNat | LitStr") -> int:
    return LIT_NAT if isinstance(e, LitNat) else LIT_STR


def app_spine(e: Expr) -> tuple["Expr", tuple[Expr, ...]]:
    """(head, args) of an application spine."""
    args: list[Expr] = []
    while isinstance(e, App):
        args.append(e.arg)
        e = e.fn
    return e, tuple(reversed(args))


def is_prop_sort(e: Expr) -> bool:
    """True iff e is literally Sort 0 (structural check; full is_prop is
    infer→whnf→check, orchestrator-level)."""
    return isinstance(e, Sort) and isinstance(e.level, LZero)
