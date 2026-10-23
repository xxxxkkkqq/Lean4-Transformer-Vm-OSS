"""Review finding-1 verification: the succ-shadow source-vs-normalized
divergence class.  Two probe shapes (reviewer's pS1d/pS2d), both sides:
the live #KDECL oracle and the graph via the lvl harness machinery.
Expected AFTER the fix: pS1d REJECT both sides (was graph-ACCEPT), pS2d
ACCEPT both sides (was graph-REJECT)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("G02_ONLY", "lvl")
import tests.test_decl_injection_vs_lean as tdi
from tests.test_decl_injection_vs_lean import (
    LEVEL_ROWS, _lvl_env, _load_graph_builder, CHECK_KIND_DEFINITION,
    _LEVEL_DEF,
)
from expr.tokens import Encoder
from lean_vm.step_driver import StepDriver, VMError
from expr.model import LZero, LSucc, LMax, LIMax, LParam, Sort, Pi, Const, \
    BI_DEFAULT
from reference import lean_ref

U = LParam("u")
Z = LZero()
ONE = LSucc(Z)
TWO = LSucc(ONE)

# (id, declared, value)
ROWS = [
    # declared max 2 (succ u); value's Pi domain Sort (imax u 1):
    # kernel Pi sort = imax(succ(succ(imax u 1))?? -> actually the fold:
    # l1 = sort level of the DOMAIN Sort (imax u 1) = succ(imax u 1);
    # l2 = body Sort 0's level = 1... the reviewer's exact shape:
    ("pS1d", Sort(LMax(TWO, LSucc(U))),
     Pi("x", BI_DEFAULT, Sort(LIMax(U, ONE)), Sort(Z))),
    ("pS2d", Sort(LSucc(LIMax(U, ONE))),
     Pi("x", BI_DEFAULT, Sort(LIMax(U, ONE)), Sort(Z))),
]

# ── oracle leg ──
DEFS = "\naxiom kU.{v} : Sort v\n"
DEFN = (".defnDecl {{ name := `{n}, levelParams := [`u], type := {t}, "
        "value := {v}, hints := ReducibilityHints.regular 0, "
        "safety := DefinitionSafety.safe }}")
def SORT(l): return f"(Lean.Expr.sort {l})"
def SU(l): return f"(Lean.Level.succ {l})"
MX = lambda a, b: f"(Lean.Level.max {a} {b})"
IM = lambda a, b: f"(Lean.Level.imax {a} {b})"
UP = "(Lean.Level.param `u)"; ZL = "Lean.Level.zero"; ONE_S = SU(ZL); TWO_S = SU(ONE_S)
PI = lambda d, b: f"(Lean.Expr.forallE `x {d} {b} Lean.BinderInfo.default)"
cases = [
    ("pS1d", DEFN.format(n="pS1d", t=SORT(MX(TWO_S, SU(UP))),
        v=PI(SORT(IM(UP, ONE_S)), SORT(ZL)))),
    ("pS2d", DEFN.format(n="pS2d", t=SORT(SU(IM(UP, ONE_S))),
        v=PI(SORT(IM(UP, ONE_S)), SORT(ZL)))),
]
oracle = dict(zip([c[0] for c in cases],
                 lean_ref.run_kdecl_oracle(DEFS, cases)))
print("oracle:", oracle, flush=True)

# ── graph leg ──
consts, ctors, const_meta = _lvl_env()
build_step_graph, _ = _load_graph_graph = _load_graph_builder()
print("building graph...", flush=True)
graph, outputs = build_step_graph()
print("graph built", flush=True)
for rid, decl, val in ROWS:
    enc = Encoder(consts, is_ctor=ctors, const_meta=const_meta)
    decls = [(enc.encode_term(decl), enc.encode_term(val))]
    heads = [enc.emit_univparams(["u"])]
    drv = StepDriver(enc.b, graph, outputs)
    rec = []
    orig_step = drv.step
    def rec_step():
        d, ab = orig_step()
        rec.append(ab)
        return d, ab
    drv.step = rec_step
    try:
        drv.run_check(decls, kinds=[CHECK_KIND_DEFINITION], lparams=heads)
        got = f"ACCEPT(steps={drv.steps})"
    except VMError as ex:
        got = f"REJECT(code={ex.code}, steps={drv.steps})"
        print(f"  {rid} tail (A,B):", flush=True)
        def tok(pos):
            if pos <= 0 or pos >= len(drv.b.stream):
                return f"<{pos}>"
            t = drv.b.stream[pos]
            return f"K{t[0]}({t[1]},{t[2]})e2={t[5]}"
        for a, b in rec[-10:]:
            print(f"    A={a} {tok(a)}  B={b} {tok(b)}", flush=True)
        for i in range(max(0, len(drv.b.stream) - 12), len(drv.b.stream)):
            t = drv.b.stream[i]
            print(f"    [{i}] K{t[0]}({t[1]},{t[2]},{t[3]}) e2={t[5]}",
                  flush=True)
        print(f"  {rid} region dump:", flush=True)
        for i in range(238, 272):
            if i < len(drv.b.stream):
                t = drv.b.stream[i]
                print(f"    [{i}] K{t[0]}({t[1]},{t[2]},{t[3]}) e2={t[5]}",
                      flush=True)
    o = oracle.get(rid, "?")
    agree = (o == "OK") == got.startswith("ACCEPT")
    print(f"{rid}: oracle={o}  graph={got}  "
          f"{'AGREE' if agree else '*** DIVERGE ***'}", flush=True)
