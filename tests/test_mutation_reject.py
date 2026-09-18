"""Phase 5 M4.3 differential test: mutation rejection + error localization.

Part A (the headline "not memorizing" evidence): minimal semantic-breaking
mutations of type-correct declarations. Every ORIGINAL must be accepted and
every MUTANT rejected, with all three layers agreeing — real lean
(`example : T := v` exit code), RefVM.check, and the ALM step graph
(StepDriver.run_check). This is the transformer-vm mutation-testing analog.

Part B (VM_SPEC §7.4 localization): for each rejected mutant, the driver
re-derives the offending subterm from machine state only — the graph's own
run_infer result diffed position-wise against the declared type (type
mismatch), or the graph's reject focus (ill-typed value) — then walks the V2
parent chain to the declaration root. Automatic check: the localized node
equals the mutated subterm and its V2 root is the declared-type root.

Run: OMP_NUM_THREADS=4 python3 tests/test_mutation_reject.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder
from expr.model import (
    Const, App, Pi, Sort, LitNat, LSucc, LZero, BI_DEFAULT,
)
from lean_vm.ref_vm import RefVM, VMError
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from lean_vm.localize import localize
from reference import lean_ref
from reference.olean_export import import_env
from tests.test_olean_export import TARGET_DEFS, ROOTS

NAT = Const("Nat")
BOOL = Const("Bool")
E_PAIR = Const("E_pair")
P2 = Const("P2")
TRUE = Const("Bool.true")
TYPE1 = Sort(LSucc(LZero()))


def _arrow(a, b):
    return Pi("", BI_DEFAULT, a, b)


def _mk(a, b):
    return App(App(Const("E_pair.mk"), a), b)


# (cid, type_src, val_src, type_Expr, val_Expr) — all type-correct (accept)
BASES = [
    ("b_dbl", "Nat", "E_dbl 21", NAT, App(Const("E_dbl"), LitNat(21))),
    ("b_ten", "Nat", "E_ten", NAT, Const("E_ten")),
    ("b_inc", "Nat → Nat", "E_inc", _arrow(NAT, NAT), Const("E_inc")),
    ("b_mk", "E_pair", "E_mk", E_PAIR, Const("E_mk")),
    ("b_let", "Nat", "E_let", NAT, Const("E_let")),
    ("b_hof", "Nat", "E_hof E_inc", NAT, App(Const("E_hof"), Const("E_inc"))),
    ("b_nat", "Type", "Nat", TYPE1, NAT),
    ("b_pairapp", "E_pair", "E_pair.mk 1 2", E_PAIR, _mk(LitNat(1), LitNat(2))),
]
BASE = {c: (t, v, te, ve) for c, t, v, te, ve in BASES}

# (mid, base_cid, type_src, val_src, type_Expr, val_Expr,
#  expect_kind, expect_offending) — each breaks type-correctness (reject)
MUTANTS = [
    # mutate the declared type's head: Nat -> Bool (diff at root)
    ("m_dbl_bool", "b_dbl", "Bool", "E_dbl 21", BOOL,
     App(Const("E_dbl"), LitNat(21)), "type_mismatch", BOOL),
    ("m_ten_bool", "b_ten", "Bool", "E_ten", BOOL, Const("E_ten"),
     "type_mismatch", BOOL),
    ("m_let_bool", "b_let", "Bool", "E_let", BOOL, Const("E_let"),
     "type_mismatch", BOOL),
    # mutate the codomain: Nat -> Nat -> Bool (diff descends Pi body)
    ("m_inc_cod", "b_inc", "Nat → Bool", "E_inc", _arrow(NAT, BOOL),
     Const("E_inc"), "type_mismatch", BOOL),
    # wrong structure: E_pair -> P2 (diff at root)
    ("m_mk_p2", "b_mk", "P2", "E_mk", P2, Const("E_mk"),
     "type_mismatch", P2),
    ("m_pairapp_p2", "b_pairapp", "P2", "E_pair.mk 1 2", P2,
     _mk(LitNat(1), LitNat(2)), "type_mismatch", P2),
    # declared a term type as Bool (Sort vs Const, kinds differ at root)
    ("m_nat_bool", "b_nat", "Bool", "Nat", BOOL, NAT,
     "type_mismatch", BOOL),
    # ill-typed value: 2nd field Bool not Nat -> graph INFER rejects
    ("m_mk_field", "b_pairapp", "E_pair", "E_pair.mk 1 true", E_PAIR,
     _mk(LitNat(1), TRUE), "ill_typed", None),
]


def _lean_verdicts(cases):
    # cases are BASES (5-tuple) or MUTANTS (8-tuple); type_src/val_src at [1]/[2]
    return lean_ref.run_check_oracle(TARGET_DEFS,
                                     [(c[1], c[2]) for c in cases])


def _refvm_verdict(consts, ctors, structs, te, ve):
    enc = Encoder(consts, is_ctor=ctors)
    vm = RefVM(enc.b, structures=structs)
    try:
        vm.check([(enc.encode_term(te), enc.encode_term(ve))])
        return True
    except VMError:
        return False


def _graph_verdict(consts, ctors, structs, te, ve):
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    d = StepDriver(enc.b, graph, outputs)
    try:
        d.run_check([(enc.encode_term(te), enc.encode_term(ve))])
        return True
    except VMError:
        return False


def _graph_localize(consts, ctors, structs, te, ve):
    """Run the graph on the mutant; on reject, localize from machine state."""
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    d = StepDriver(enc.b, graph, outputs)
    type_root = enc.encode_term(te)
    val_root = enc.encode_term(ve)
    try:
        d.run_check([(type_root, val_root)])
        return None, None                # accepted — caller flags the failure
    except VMError as e:
        infer_focus = e.focus
    # fresh machine run: graph INFER of the value (the machine's own step)
    graph2, outputs2 = build_step_graph()
    enc2 = Encoder(consts, is_ctor=ctors)
    d2 = StepDriver(enc2.b, graph2, outputs2)
    tr2 = enc2.encode_term(te)
    vr2 = enc2.encode_term(ve)
    try:
        ipos, ienv = d2.run_infer(vr2)
        inferred = (ipos, ienv)
        focus = -1
    except VMError as e:
        inferred = None
        focus = e.focus
    loc = localize(enc2.b, tr2, vr2, inferred=inferred, infer_focus=focus)
    return loc, tr2


def main() -> int:
    consts, ctors, structs = import_env(TARGET_DEFS, ROOTS)
    fails = []

    # ── Part A: three-layer verdict parity ───────────────────────────────────
    lean_base = _lean_verdicts(BASES)
    n_accept = 0
    for (cid, t, v, te, ve), lv in zip(BASES, lean_base):
        rv = _refvm_verdict(consts, ctors, structs, te, ve)
        gv = _graph_verdict(consts, ctors, structs, te, ve)
        if lv and rv and gv:
            n_accept += 1
        else:
            fails.append((cid, f"BASE not unanimously accepted: "
                               f"lean={lv} ref={rv} graph={gv}"))

    lean_mut = _lean_verdicts(MUTANTS)
    n_reject = 0
    for (mid, bc, t, v, te, ve, _, _), lv in zip(MUTANTS, lean_mut):
        rv = _refvm_verdict(consts, ctors, structs, te, ve)
        gv = _graph_verdict(consts, ctors, structs, te, ve)
        if (not lv) and (not rv) and (not gv):
            n_reject += 1
        else:
            fails.append((mid, f"MUTANT not unanimously rejected: "
                               f"lean={lv} ref={rv} graph={gv}"))

    total_a = len(BASES) + len(MUTANTS)
    n_a = n_accept + n_reject
    print(f"Part A  mutation rejection parity (lean/ref/graph): "
          f"{n_a}/{total_a}  (accept {n_accept}/{len(BASES)}, "
          f"reject {n_reject}/{len(MUTANTS)})")

    # ── Part B: error localization on each mutant ────────────────────────────
    n_b = 0
    for (mid, bc, t, v, te, ve, kind, expect) in MUTANTS:
        loc, tr2 = _graph_localize(consts, ctors, structs, te, ve)
        if loc is None:
            fails.append((mid, "localize: graph accepted a mutant"))
            continue
        ok = loc["kind"] == kind
        if kind == "type_mismatch":
            # offending node is the mutated subterm, and its V2 chain
            # terminates at the declared-type tree root (same stream)
            ok = (ok and loc["offending_expr"] == expect
                  and loc["path"][-1] == tr2)
        if ok:
            n_b += 1
            off = loc["offending_expr"]
            print(f"  [PASS] {mid}: {loc['kind']} -> {off} "
                  f"(path depth {len(loc['path'])})")
        else:
            fails.append((mid, f"localize kind={loc['kind']} exp={kind} "
                               f"off={loc.get('offending_expr')} exp_off={expect}"))

    print(f"Part B  error localization: {n_b}/{len(MUTANTS)}")

    ok = not fails
    print(f"\n=== M4.3 mutation+localize: A {n_a}/{total_a}, "
          f"B {n_b}/{len(MUTANTS)} === {'OK' if ok else 'FAIL'}")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
