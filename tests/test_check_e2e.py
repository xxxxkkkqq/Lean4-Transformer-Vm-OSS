"""Phase 5 M4.2 differential test: end-to-end CHECK vs real Lean 4.

Oracle = `lean` (v4.33.1, elan) via reference/lean_ref.run_check_oracle:
`example : T := v` compiles (exit 0) iff the real kernel accepts the
declaration (elaborator infer + kernel defeq — the check slice).

Layer A — RefVM.check (infer + defeq per decl, M4.1 exported env) vs the
real lean oracle, single declarations and multi-decl sequences.
Layer B — the ALM step graph (StepDriver.run_check, T_CHECK anchor frames +
CK_TY/CK_RES continuations) vs RefVM on the same exported stream.

Run: OMP_NUM_THREADS=4 python3 tests/test_check_e2e.py
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
from reference import lean_ref
from reference.olean_export import import_env
from tests.test_olean_export import TARGET_DEFS, ROOTS

NAT = Const("Nat")
BOOL = Const("Bool")
E_PAIR = Const("E_pair")
TYPE1 = Sort(LSucc(LZero()))


def _arrow(a, b):
    return Pi("", BI_DEFAULT, a, b)


# (cid, type_src, val_src, type_Expr, val_Expr)
CHECK_CASES = [
    ("chk_dbl_nat", "Nat", "E_dbl 21", NAT,
     App(Const("E_dbl"), LitNat(21))),
    ("chk_ten", "Nat", "E_ten", NAT, Const("E_ten")),
    ("chk_dbl_bool", "Bool", "E_dbl 2", BOOL,
     App(Const("E_dbl"), LitNat(2))),
    ("chk_inc_fn", "Nat → Nat", "E_inc", _arrow(NAT, NAT), Const("E_inc")),
    ("chk_inc_fn_bad", "Nat → Bool", "E_inc", _arrow(NAT, BOOL),
     Const("E_inc")),
    ("chk_mk_pair", "E_pair", "E_mk", E_PAIR, Const("E_mk")),
    ("chk_two_pair", "E_pair", "E_two", E_PAIR, Const("E_two")),
    ("chk_let", "Nat", "E_let", NAT, Const("E_let")),
    ("chk_hof_inc", "Nat", "E_hof E_inc", NAT,
     App(Const("E_hof"), Const("E_inc"))),
    ("chk_nat_type", "Type", "Nat", TYPE1, NAT),
    ("chk_type_nat", "Nat", "Type", NAT, TYPE1),
    ("chk_mk_nat", "Nat", "E_pair.mk 1 2", NAT,
     App(App(Const("E_pair.mk"), LitNat(1)), LitNat(2))),
]
CASE = {c: (t, v, te, ve) for c, t, v, te, ve in CHECK_CASES}

# multi-decl sequences (kernel checks each decl independently)
SEQUENCES = [
    ("seq_all_ok", ["chk_dbl_nat", "chk_ten", "chk_inc_fn", "chk_mk_pair",
                    "chk_let", "chk_hof_inc", "chk_nat_type"]),
    ("seq_reject_second", ["chk_dbl_nat", "chk_dbl_bool"]),
    ("seq_reject_first", ["chk_dbl_bool", "chk_dbl_nat"]),
]


def _verdict(fn):
    """Run fn(); True = accepted, False = rejected (VMError ERR_TYPE)."""
    try:
        fn()
        return True
    except VMError:
        return False


def main() -> int:
    consts, ctors, structs = import_env(TARGET_DEFS, ROOTS)

    # ── Layer A: RefVM.check vs real lean ────────────────────────────────────
    oracle = lean_ref.run_check_oracle(
        TARGET_DEFS, [(t, v) for _, t, v, _, _ in CHECK_CASES])
    n_pass, fails = 0, []
    single = {}
    for (cid, t_src, v_src, te, ve), expected in zip(CHECK_CASES, oracle):
        enc = Encoder(consts, is_ctor=ctors)
        vm = RefVM(enc.b, structures=structs)
        tp, vp = enc.encode_term(te), enc.encode_term(ve)
        got = _verdict(lambda: vm.check([(tp, vp)]))
        single[cid] = expected
        if got == expected:
            n_pass += 1
        else:
            fails.append((cid, f"refvm {got}, lean {expected} "
                               f"({v_src} : {t_src})"))

    for cid, members in SEQUENCES:
        enc = Encoder(consts, is_ctor=ctors)
        vm = RefVM(enc.b, structures=structs)
        decls = [(enc.encode_term(CASE[m][2]), enc.encode_term(CASE[m][3]))
                 for m in members]
        expected = all(single[m] for m in members)
        got = _verdict(lambda: vm.check(decls))
        if got == expected:
            n_pass += 1
        else:
            fails.append((cid, f"refvm {got}, expected {expected}"))

    total_a = len(CHECK_CASES) + len(SEQUENCES)
    print(f"Layer A  RefVM.check vs real lean: {n_pass}/{total_a}")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")

    # ── Layer B: step graph run_check vs RefVM ───────────────────────────────
    n_pass_b, fails_b = 0, []

    def graph_check(decls):
        graph, outputs = build_step_graph()
        g_enc = Encoder(consts, is_ctor=ctors)
        gd = [(g_enc.encode_term(te), g_enc.encode_term(ve))
              for te, ve in decls]
        driver = StepDriver(g_enc.b, graph, outputs)
        got = _verdict(lambda: driver.run_check(gd))
        return got, driver.steps

    for cid, t_src, v_src, te, ve in CHECK_CASES:
        enc = Encoder(consts, is_ctor=ctors)
        vm = RefVM(enc.b, structures=structs)
        expected = _verdict(
            lambda: vm.check([(enc.encode_term(te), enc.encode_term(ve))]))
        got, steps = graph_check([(te, ve)])
        if got == expected:
            n_pass_b += 1
            print(f"  [PASS] {cid}: {'accept' if got else 'reject'} "
                  f"({steps} micro-steps)")
        else:
            fails_b.append((cid, f"graph {got}, refvm {expected}"))

    for cid, members in SEQUENCES:
        decls = [(CASE[m][2], CASE[m][3]) for m in members]
        enc = Encoder(consts, is_ctor=ctors)
        vm = RefVM(enc.b, structures=structs)
        edecls = [(enc.encode_term(te), enc.encode_term(ve))
                  for te, ve in decls]
        expected = _verdict(lambda: vm.check(edecls))
        got, steps = graph_check(decls)
        if got == expected:
            n_pass_b += 1
            print(f"  [PASS] {cid}: {'accept' if got else 'reject'} "
                  f"({steps} micro-steps)")
        else:
            fails_b.append((cid, f"graph {got}, refvm {expected}"))

    total_b = len(CHECK_CASES) + len(SEQUENCES)
    print(f"Layer B  step graph vs RefVM: {n_pass_b}/{total_b}")
    for cid, msg in fails_b:
        print(f"  [FAIL] {cid}: {msg}")

    ok = not fails and not fails_b
    print(f"\n=== M4.2 end-to-end check: A {n_pass}/{total_a}, "
          f"B {n_pass_b}/{total_b} === {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
