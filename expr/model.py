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
