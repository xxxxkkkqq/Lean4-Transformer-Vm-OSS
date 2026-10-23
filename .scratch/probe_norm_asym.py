"""Beat B mechanism probes (card 021 / ADR 026): one-shot normalize
asymmetry claims, tested against the pinned 4.33.1 kernel via the #KDECL
raw-declaration channel (the same channel as the decl-injection corpora).

Static rows: `axiom kU.{v} : Sort v` gives kU.{LB} : Sort LB; declaring
`def pN : Sort LA := kU.{LB}` forces is_def_eq(Sort LB, Sort LA) ->
level is_equivalent(LA, LB) on two STATIC terms.
Fold rows: `axiom kS.{l} : Sort l -> True` with a Pi TERM argument: the
kernel's infer_pi computes Sort (mk_imax chain) at RUNTIME, then checks
the argument against Sort L -> level compare(fold-result, L).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reference import lean_ref

DEFS = """
axiom kU.{v} : Sort v
axiom kS.{l} : Sort l → True
"""

DEFN = (".defnDecl {{ name := `{n}, levelParams := [{lp}], type := {t}, "
        "value := {v}, hints := ReducibilityHints.regular 0, "
        "safety := DefinitionSafety.safe }}")

U = "(Lean.Level.param `u)"
V = "(Lean.Level.param `v)"
W = "(Lean.Level.param `w)"
Z = "Lean.Level.zero"
ONE = f"(Lean.Level.succ {Z})"
SU = lambda l: f"(Lean.Level.succ {l})"
MX = lambda a, b: f"(Lean.Level.max {a} {b})"
IM = lambda a, b: f"(Lean.Level.imax {a} {b})"

SUCC_U = SU(U); SUCC_V = SU(V); SUCC_W = SU(W)
SUCC2_U = SU(SUCC_U); SUCC2_V = SU(SUCC_V); SUCC2_W = SU(SUCC_W)

def SORT(l): return f"(Lean.Expr.sort {l})"
def KU(l): return f"(Lean.mkConst `kU [{l}])"
def KS(l, arg): return f"(Lean.mkApp (Lean.mkConst `kS [{l}]) {arg})"
def PI(dom, body): return f"(Lean.Expr.forallE `x {dom} {body} Lean.BinderInfo.default)"

TYPU = SORT(SUCC_U)   # Type u = Sort (succ u)
TYPV = SORT(SUCC_V)
TYPW = SORT(SUCC_W)
TYP1 = SORT(ONE)      # Type = Sort 1
TRUE = "Lean.mkConst ``True"

# (id, levelParams, declared type, value, predicted)
ROWS = [
    # static level pairs: declared Sort LA vs kU.{LB}
    ("pX1", ["u"], SORT(IM(SUCC_U, ONE)), KU(MX(SUCC_U, ONE)), "REJECT"),
    ("pX2", ["u"], SORT(IM(SUCC_U, ONE)), KU(SUCC_U), "REJECT"),
    ("pX3", ["u"], SORT(MX(SUCC_U, ONE)), KU(SUCC_U), "ACCEPT"),
    ("pX4", ["u"], SORT(MX(ONE, U)), KU(MX(U, ONE)), "ACCEPT"),
    ("pX5", ["u"], SORT(IM(U, ONE)), KU(MX(U, ONE)), "REJECT"),
    ("pX6", ["u"], SORT(IM(U, ONE)), KU(MX(ONE, U)), "REJECT"),
    ("pX7", ["u"], SORT(IM(ONE, U)), KU(U), "ACCEPT"),
    # fold: (x : Type u) -> Type : imax(u+2, 2) -> max_rt(u+2, 2);
    # normalize subsumes explicit 2 by u+2's offset 2 -> u+2
    ("pF1", ["u"], TRUE, KS(SUCC2_U, PI(TYPU, TYP1)), "ACCEPT"),
    ("pF1n", ["u"], TRUE, KS(SUCC_U, PI(TYPU, TYP1)), "REJECT"),
    # fold: (x : Type u) -> (y : Type v) -> Type : 3-arg union, explicit 2
    # subsumed -> survivors max(u+2, v+2)
    ("pF2", ["u", "v"], TRUE,
     KS(MX(SUCC2_U, SUCC2_V), PI(TYPU, PI(TYPV, TYP1))), "ACCEPT"),
    ("pF2n", ["u", "v"], TRUE,
     KS(MX(U, V), PI(TYPU, PI(TYPV, TYP1))), "REJECT"),
    # fold: 3 domains -> 4-arg union, explicit 2 subsumed -> 3 survivors,
    # rebuild right-fold max(u+2, max(v+2, w+2))
    ("pF3", ["u", "v", "w"], TRUE,
     KS(MX(SUCC2_U, MX(SUCC2_V, SUCC2_W)),
        PI(TYPU, PI(TYPV, PI(TYPW, TYP1)))), "ACCEPT"),
    # fold: succ-wrapped max atom (x : Sort (max u v)) -> s1 = succ(max u v)
    # stays an ATOM (kind Max sorts before Param) -> max (succ (max u v)) (u+2)
    ("pF4", ["u", "v"], TRUE,
     KS(MX(SU(MX(U, V)), SUCC2_U),
        PI(SORT(MX(U, V)), PI(TYPU, TYP1))), "ACCEPT"),
    # emission-order pins: the runtime canonical output has a FIXED order
    # (kind-sorted).  A static MAX normalizes order-insensitively, so only
    # an IMAX-path pairwise form (source-order preserving) can pin it:
    # imax (succ (max u v)) (u+2) -> pairwise max(succ(maxuv), u+2) == rt ACCEPT
    ("pF4i", ["u", "v"], TRUE,
     KS(IM(SU(MX(U, V)), SUCC2_U),
        PI(SORT(MX(U, V)), PI(TYPU, TYP1))), "ACCEPT"),
    # imax (u+2) (succ (max u v)) -> pairwise max(u+2, succ(maxuv)) != rt REJECT
    ("pF4j", ["u", "v"], TRUE,
     KS(IM(SUCC2_U, SU(MX(U, V))),
        PI(SORT(MX(U, V)), PI(TYPU, TYP1))), "REJECT"),
]

cases = []
for rid, lps, ty, val, _pred in ROWS:
    lp = ", ".join("`" + p for p in lps)
    cases.append((rid, DEFN.format(n=rid, lp=lp, t=ty, v=val)))

res = lean_ref.run_kdecl_oracle(DEFS, cases)
bad = 0
for (rid, lps, ty, val, pred), r in zip(ROWS, res):
    got = "ACCEPT" if r == "OK" else f"REJECT({r})"
    mark = "MATCH" if got.startswith(pred) else "*** MISMATCH ***"
    if not got.startswith(pred): bad += 1
    print(f"{rid:6s} pred={pred:7s} oracle={got:28s} {mark}")
print(f"\n{len(ROWS)} probes, {bad} mismatches")
