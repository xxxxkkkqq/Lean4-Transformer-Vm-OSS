"""Phase 5 M4.1 differential test: .olean-exported env vs real lean.

Layer A — RefVM over the EXPORTED environment (reference/olean_export.py:
real `lean` Environment API dump → prune at toy table → numeral normalize →
validate) vs the real lean oracle, on WHNF/DEFEQ/INFER cases that delta-
expand arbitrary environment constants (E_* defs, a real structure E_pair
with projections, higher-order defs).

Layer B — the ALM step graph (StepDriver) vs RefVM on the same exported
stream. Graph-layer cases avoid Proj/eta-struct on NEW structures (the
graph's proj gate is P2 build-time — VM_SPEC §11.1 M4.1 limits); RefVM
covers them.

Run: OMP_NUM_THREADS=4 python3 tests/test_olean_export.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure
from expr.model import (
    BVar, Const, App, Lam, Pi, Sort, LitNat, LSucc, LZero, BI_DEFAULT,
)
from lean_vm.ref_vm import RefVM, VMError
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference import lean_ref
from reference.olean_export import import_env

TARGET_DEFS = """\
def E_dbl (x : Nat) : Nat := Nat.add x x
def E_two : Nat := 2
def E_four : Nat := Nat.mul E_two E_two
def E_ten : Nat := Nat.add E_four (Nat.add E_four E_two)
def E_inc : Nat → Nat := fun x => Nat.succ x
def E_hof (f : Nat → Nat) : Nat := Nat.add (f 1) (f 2)
structure E_pair where mk :: (a : Nat) (b : Nat)
def E_mk : E_pair := E_pair.mk E_two E_four
def E_sum (p : E_pair) : Nat := Nat.add p.a p.b
def E_let : Nat := let x : Nat := E_four; Nat.mul x x
"""
ROOTS = ["E_dbl", "E_two", "E_four", "E_ten", "E_inc", "E_hof", "E_mk",
         "E_sum", "E_let"]

NAT = Const("Nat")
E_PAIR = Const("E_pair")


def _add(a, b):
    return App(App(Const("Nat.add"), a), b)


# (cid, lean src, our Expr)
WHNF_CASES = [
    ("whnf_dbl", "E_dbl 21", App(Const("E_dbl"), LitNat(21))),
    ("whnf_four", "E_four", Const("E_four")),
    ("whnf_ten", "E_ten", Const("E_ten")),
    ("whnf_let", "E_let", Const("E_let")),
    ("whnf_hof", "E_hof E_dbl", App(Const("E_hof"), Const("E_dbl"))),
    ("whnf_inc", "E_inc 41", App(Const("E_inc"), LitNat(41))),
    ("whnf_mk", "E_mk", Const("E_mk")),
    ("whnf_sum", "E_sum E_mk", App(Const("E_sum"), Const("E_mk"))),
]
# graph layer: whnf_sum needs Proj on E_pair (P2-gated in the graph)
GRAPH_WHNF = {c for c, _, _ in WHNF_CASES} - {"whnf_sum"}

# (cid, lean lhs, lean rhs, our lhs, our rhs)
DEFEQ_CASES = [
    ("deq_four", "E_four", "4", Const("E_four"), LitNat(4)),
    ("deq_dbl_lam", "E_dbl", "(fun (x : Nat) => Nat.add x x)",
     Const("E_dbl"), Lam("x", BI_DEFAULT, NAT, _add(BVar(0), BVar(0)))),
    ("deq_ten_ne_four", "E_ten", "E_four", Const("E_ten"), Const("E_four")),
    ("deq_mk", "E_mk", "E_pair.mk 2 4", Const("E_mk"),
     App(App(Const("E_pair.mk"), LitNat(2)), LitNat(4))),
    ("deq_sum", "E_sum E_mk", "6",
     App(Const("E_sum"), Const("E_mk")), LitNat(6)),
    ("deq_proj_a", "E_pair.a E_mk", "2",
     App(Const("E_pair.a"), Const("E_mk")), LitNat(2)),
    ("deq_proj_a_ne", "E_pair.a E_mk", "4",
     App(Const("E_pair.a"), Const("E_mk")), LitNat(4)),
]
GRAPH_DEFEQ = {c for c, *_ in DEFEQ_CASES} - {"deq_sum", "deq_proj_a",
                                              "deq_proj_a_ne"}

# (cid, lean src, our Expr)
INFER_CASES = [
    ("inf_dbl", "E_dbl", Const("E_dbl")),
    ("inf_sum", "E_sum", Const("E_sum")),
    ("inf_mk", "E_mk", Const("E_mk")),
    ("inf_hof_app", "E_hof E_dbl", App(Const("E_hof"), Const("E_dbl"))),
    ("inf_pair", "E_pair", E_PAIR),
    ("inf_let", "E_let", Const("E_let")),
]
GRAPH_INFER = {c for c, *_ in INFER_CASES}


def strip_mdata(e):
    from expr.model import MData, Let
    if isinstance(e, MData):
        return strip_mdata(e.child)
    if isinstance(e, App):
        return App(strip_mdata(e.fn), strip_mdata(e.arg))
    if isinstance(e, (Lam, Pi)):
        return type(e)(e.name, e.binfo, strip_mdata(e.domain),
                       strip_mdata(e.body))
    if isinstance(e, Let):
        return Let(e.name, strip_mdata(e.domain), strip_mdata(e.value),
                   strip_mdata(e.body), nondep=e.nondep)
    return e


def main() -> int:
    consts, ctors, structs = import_env(TARGET_DEFS, ROOTS)
    n_new = len(consts) - 28  # TOY_CONSTS length
    print(f"exported env: {len(consts)} consts ({n_new} new), "
          f"{len(ctors)} ctors, structs={structs}")

    enc = Encoder(consts, is_ctor=ctors)
    vm = RefVM(enc.b, structures=structs)

    # ── Layer A: RefVM vs real lean ──────────────────────────────────────────
    entries = ([("WHNF", src, None) for _, src, _ in WHNF_CASES]
               + [("DEFEQ", l, r) for _, l, r, _, _ in DEFEQ_CASES]
               + [("INFER", src, None) for _, src, _ in INFER_CASES])
    oracle = lean_ref.run_oracle_mixed(TARGET_DEFS, entries)
    nw, nd, ni = len(WHNF_CASES), len(DEFEQ_CASES), len(INFER_CASES)
    whnf_o = oracle[:nw]
    defeq_o = oracle[nw:nw + nd]
    infer_o = oracle[nw + nd:]

    n_pass, fails = 0, []
    for (cid, _, our), (_, oj) in zip(WHNF_CASES, whnf_o):
        expected = strip_mdata(lean_ref.json_to_expr(oj))
        try:
            pos, env = vm.whnf(enc.encode_term(our), 0)
            got = strip_mdata(decode_closure(enc.b, pos, env))
        except VMError as e:
            fails.append((cid, f"vm error: {e}"))
            continue
        if got == expected:
            n_pass += 1
        else:
            fails.append((cid, f"whnf\n  vm:   {got}\n  lean: {expected}"))

    for (cid, _, _, our_l, our_r), (_, verdict) in zip(DEFEQ_CASES, defeq_o):
        try:
            lp = enc.encode_term(our_l)
            rp = enc.encode_term(our_r)
            got = bool(vm.defeq((lp, 0), (rp, 0)))
        except VMError as e:
            fails.append((cid, f"vm error: {e}"))
            continue
        if got == verdict:
            n_pass += 1
        else:
            fails.append((cid, f"defeq got {got}, lean says {verdict}"))

    for (cid, _, our), (_, oj) in zip(INFER_CASES, infer_o):
        expected = strip_mdata(lean_ref.json_to_expr(oj))
        try:
            tp, tenv = vm.infer(enc.encode_term(our), 0)
            got = strip_mdata(decode_closure(enc.b, tp, tenv))
        except VMError as e:
            fails.append((cid, f"vm error: {e}"))
            continue
        if got == expected:
            n_pass += 1
        else:
            fails.append((cid, f"infer\n  vm:   {got}\n  lean: {expected}"))

    total_a = nw + nd + ni
    print(f"Layer A  RefVM(exported env) vs real lean: {n_pass}/{total_a}")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")

    # ── Layer B: step graph vs RefVM on the same exported stream ─────────────
    n_pass_b, fails_b = 0, []

    for cid, _, our in WHNF_CASES:
        if cid not in GRAPH_WHNF:
            continue
        ref_enc = Encoder(consts, is_ctor=ctors)
        ref_vm = RefVM(ref_enc.b, structures=structs)
        rp, renv = ref_vm.whnf(ref_enc.encode_term(our), 0)
        expected = strip_mdata(decode_closure(ref_enc.b, rp, renv))
        graph, outputs = build_step_graph()
        g_enc = Encoder(consts, is_ctor=ctors)
        driver = StepDriver(g_enc.b, graph, outputs)
        try:
            gp, genv = driver.run(g_enc.encode_term(our))
            got = strip_mdata(decode_closure(g_enc.b, gp, genv))
        except Exception as e:
            got = f"{type(e).__name__}: {e}"
        if got == expected:
            n_pass_b += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        else:
            fails_b.append((cid, f"\n  graph={got}\n  ref  ={expected}"))

    for cid, _, _, our_l, our_r in DEFEQ_CASES:
        if cid not in GRAPH_DEFEQ:
            continue
        ref_enc = Encoder(consts, is_ctor=ctors)
        ref_vm = RefVM(ref_enc.b, structures=structs)
        expected = bool(ref_vm.defeq((ref_enc.encode_term(our_l), 0),
                                     (ref_enc.encode_term(our_r), 0)))
        graph, outputs = build_step_graph()
        g_enc = Encoder(consts, is_ctor=ctors)
        driver = StepDriver(g_enc.b, graph, outputs)
        try:
            verdict = bool(driver.run_defeq(g_enc.encode_term(our_l), 0,
                                            g_enc.encode_term(our_r), 0)[0])
        except Exception as e:
            verdict = f"{type(e).__name__}: {e}"
        if verdict == expected:
            n_pass_b += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        else:
            fails_b.append((cid, f"graph={verdict} ref={expected}"))

    for cid, _, our in INFER_CASES:
        if cid not in GRAPH_INFER:
            continue
        ref_enc = Encoder(consts, is_ctor=ctors)
        ref_vm = RefVM(ref_enc.b, structures=structs)
        tp, tenv = ref_vm.infer(ref_enc.encode_term(our), 0)
        expected = strip_mdata(decode_closure(ref_enc.b, tp, tenv))
        graph, outputs = build_step_graph()
        g_enc = Encoder(consts, is_ctor=ctors)
        driver = StepDriver(g_enc.b, graph, outputs)
        try:
            tp, tenv = driver.run_infer(g_enc.encode_term(our))
            got = strip_mdata(decode_closure(g_enc.b, tp, tenv))
        except Exception as e:
            got = f"{type(e).__name__}: {e}"
        if got == expected:
            n_pass_b += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        else:
            fails_b.append((cid, f"\n  graph={got}\n  ref  ={expected}"))

    total_b = len(GRAPH_WHNF) + len(GRAPH_DEFEQ) + len(GRAPH_INFER)
    print(f"Layer B  step graph vs RefVM (exported env): {n_pass_b}/{total_b}")
    for cid, msg in fails_b:
        print(f"  [FAIL] {cid}: {msg}")

    ok = not fails and not fails_b
    print(f"\n=== M4.1 olean export: A {n_pass}/{total_a}, "
          f"B {n_pass_b}/{total_b} === {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
