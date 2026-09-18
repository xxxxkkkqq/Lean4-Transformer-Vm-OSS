"""Oracle self-consistency tests for the #LEVEL / #KDECL oracles.

VM_SPEC 12.5(A)/(B) add two real-Lean oracles to reference/lean_ref.py:
`run_level_oracle` (#LEVEL, public Lean.Level predicate API) and
`run_kdecl_oracle` (#KDECL, raw Declaration through the real C++ kernel via
Lean.Kernel.Environment.addDecl).

SCOPE: this file tests the ORACLE ITSELF for self-coherence. The VM-side level
predicate API (expr/level.py) and the VM-vs-oracle comparison of these outputs
are a LATER package (WP2); nothing here compares against a VM.

Expected values are produced by real `lean` (4.33.1, ~/.elan/bin/lean) at test
time, never hand-written. The only pinned facts are structural relations the
test itself asserts, e.g. the §12.5(A) counterexample's `isEquiv` holds while
its serialized normal forms differ, or the §12.5(B) accept/reject shapes map to
the documented Kernel.Exception class names.

Run: python3 tests/test_level_vs_lean.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference import lean_ref


# Level helper definitions shared by every #LEVEL case. Each corpus class
# contains at least one Param, per VM_SPEC 12.5(A).
LEVEL_DEFS = """\
def pu : Level := Level.param `u
def pv : Level := Level.param `v
def pw : Level := Level.param `w
def p1 : Level := Level.one
def pz : Level := Level.zero
"""

# (id, a_src, b_src). Level terms are bare constructors (`Level.max`/`.imax`/
# `.succ`/`.param`/`.zero`), never the mkLevelMax/mkLevelIMax' smart
# constructors (not visible in 4.33.1). Unary cases repeat the level.
LEVEL_CASES: list[tuple[str, str, str]] = [
    # --- D1 max branch (C++ level.cpp:454-516); each branch gets a case ---
    ("d1_max_zero_absorb", "Level.max pu Level.zero", "pu"),
    ("d1_max_equal", "Level.max pu pu", "pu"),
    ("d1_max_comm", "Level.max pu p1", "Level.max p1 pu"),
    ("d1_max_same_off", "Level.max (Level.succ pu) pu", "Level.succ pu"),
    ("d1_max_diff_base", "Level.max pu pv", "Level.max pv pu"),
    # counterexample seed (must be present): binary normalize orders max args
    # differently from C++ is_norm_lt, so its serialized normal forms differ
    # even though isEquiv holds.
    ("d1_max_imax_seed", "Level.max (Level.imax pu pv) pw",
     "Level.max pw (Level.imax pu pv)"),
    # --- D2 imax branch ---
    ("d2_imax_u_zero", "Level.imax pu Level.zero", "Level.zero"),
    ("d2_imax_zero_u", "Level.imax Level.zero pu", "pu"),
    ("d2_imax_one_u", "Level.imax p1 pu", "pu"),
    ("d2_imax_u_u", "Level.imax pu pu", "pu"),
    ("d2_imax_u_one", "Level.imax pu p1", "Level.max pu p1"),
    ("d2_imax_one_zero", "Level.imax p1 Level.zero", "Level.zero"),
    # --- succ/offset propagation ---
    ("d5_succ_max", "Level.succ (Level.max pu pv)",
     "Level.max (Level.succ pu) (Level.succ pv)"),
    ("d9_offset", "Level.succ (Level.succ pu)", "Level.succ pu"),
    # --- D7 geq branches: max / imax / offset / zero ---
    ("d7_geq_max", "Level.max pu pv", "pu"),
    ("d7_geq_imax_rhs", "Level.imax pu pv", "pv"),
    ("d7_geq_offset", "Level.succ pu", "pu"),
    ("d7_geq_zero", "pu", "Level.zero"),
    # --- D10 instantiateParams: hit / miss / nested ---
    ("d10_inst_hit", "Level.instantiateParams (Level.max pu pv) [`u, `v] [p1, pz]",
     "Level.max p1 pz"),
    ("d10_inst_miss", "Level.instantiateParams pu [`v] [p1]", "pu"),
    ("d10_inst_nested",
     "Level.instantiateParams (Level.succ (Level.max pu pv)) [`u] [p1]",
     "Level.succ (Level.max p1 pv)"),
    # --- D11 occurs ---
    ("d11_occurs_yes", "pu", "Level.max pu pv"),
    ("d11_occurs_no", "pw", "Level.max pu pv"),
    # --- D8/D9 unary predicates ---
    ("d9_explicit_zero", "Level.zero", "Level.zero"),
    ("d9_explicit_succ_param", "Level.succ pu", "Level.succ pu"),
    ("d9_explicit_succ_zero", "Level.succ Level.zero", "p1"),
    ("d8_never_zero_succ", "Level.succ pu", "Level.succ pu"),
    ("d8_always_zero_imax", "Level.imax pu Level.zero", "Level.zero"),
]


def _a(r): return r["a"]


def _b(r): return r["b"]


def check_level(cid: str, r: dict) -> None:
    """Assert the documented coherence relations for one #LEVEL payload."""
    if cid == "d1_max_zero_absorb":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["ser"]          # max u 0 normalizes to u
    elif cid == "d1_max_equal":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["ser"]          # max u u normalizes to u
    elif cid == "d1_max_comm":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["norm"]         # max is commutative
    elif cid == "d1_max_same_off":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["ser"]          # max (succ u) u ~ succ u
    elif cid == "d1_max_diff_base":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["norm"]
    elif cid == "d1_max_imax_seed":
        # §12.5(A) seed: isEquiv holds while the serialized forms differ. `a` is
        # in C++ is_norm_lt order, `b` is in 4.33.1 Lean normLt order; binary
        # normalize moves `a` onto `b`.
        assert r["isEquiv"] is True
        assert _a(r)["ser"] != _b(r)["ser"]
        assert _a(r)["norm"] != _a(r)["ser"]
        assert _a(r)["norm"] == _b(r)["ser"]
    elif cid == "d2_imax_u_zero":
        assert r["isEquiv"] is True                    # imax u 0 ~ 0
        assert _a(r)["alwaysZero"] is True
        assert _a(r)["norm"] == _b(r)["ser"]
    elif cid == "d2_imax_zero_u":
        assert r["isEquiv"] is True                    # imax 0 u ~ u
        assert _a(r)["norm"] == _b(r)["ser"]
    elif cid == "d2_imax_one_u":
        assert r["isEquiv"] is True                    # imax 1 u ~ u
    elif cid == "d2_imax_u_u":
        assert r["isEquiv"] is True                    # imax u u ~ u
    elif cid == "d2_imax_u_one":
        assert r["isEquiv"] is True                    # rhs nonzero -> max path
        assert _a(r)["norm"] == _b(r)["norm"]
    elif cid == "d2_imax_one_zero":
        assert r["isEquiv"] is True                    # imax 1 0 ~ 0 (is_prop)
        assert _a(r)["alwaysZero"] is True
    elif cid == "d5_succ_max":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["norm"]
        assert _a(r)["offset"] == 1
    elif cid == "d9_offset":
        assert _a(r)["offset"] == 2
        assert _a(r)["levelOffset"] == _b(r)["levelOffset"]  # both base u
        assert r["isEquiv"] is False
        assert r["geqAB"] is True and r["geqBA"] is False
    elif cid == "d7_geq_max":
        assert r["geqAB"] is True and r["geqBA"] is False
    elif cid == "d7_geq_imax_rhs":
        assert r["geqAB"] is True                      # imax u v >= v (rule 5)
    elif cid == "d7_geq_offset":
        assert r["geqAB"] is True and r["geqBA"] is False
    elif cid == "d7_geq_zero":
        assert r["geqAB"] is True and r["geqBA"] is False
    elif cid == "d10_inst_hit":
        assert r["isEquiv"] is True
        assert _a(r)["norm"] == _b(r)["norm"]
    elif cid == "d10_inst_miss":
        assert r["isEquiv"] is True                    # unbound param unchanged
        assert _a(r)["norm"] == _b(r)["ser"]
    elif cid == "d10_inst_nested":
        assert r["isEquiv"] is True
    elif cid == "d11_occurs_yes":
        assert r["occursAB"] is True
    elif cid == "d11_occurs_no":
        assert r["occursAB"] is False
    elif cid == "d9_explicit_zero":
        assert _a(r)["explicit"] is True
    elif cid == "d9_explicit_succ_param":
        assert _a(r)["explicit"] is False              # succ of a param
    elif cid == "d9_explicit_succ_zero":
        assert _a(r)["explicit"] is True and r["isEquiv"] is True
    elif cid == "d8_never_zero_succ":
        assert _a(r)["neverZero"] is True
    elif cid == "d8_always_zero_imax":
        assert _a(r)["alwaysZero"] is True
        assert r["isEquiv"] is True
    else:
        raise AssertionError(f"no checks for level case {cid}")


# Raw-declaration cases (§12.5(B)). `Ax` is the prerequisite for the
# instantiation shapes, added normally so the #KDECL env has it available.
KDECL_DEFS = "axiom Ax.{u} : Sort u"

KDECL_CASES: list[tuple[str, str]] = [
    ("ax_ok", "mkOracleAxiom `A [`u] (mkSort (Level.param `u))"),
    ("undef_param",
     "mkOracleDefn `Bad1 [] (mkSort (Level.param `u)) (mkSort (Level.param `u))"),
    ("inst_arity",
     "mkOracleDefn `Bad2 [] (mkSort (Level.succ Level.zero)) "
     "(Lean.mkConst `Bool [Level.param `u])"),
    ("def_simple",
     "mkOracleDefn `B [] (mkSort (Level.succ Level.zero)) "
     "(Lean.mkConst `Ax [Level.one])"),
    ("def_imax_1u",
     "mkOracleDefn `C [`u] (mkSort (Level.imax Level.one (Level.param `u))) "
     "(Lean.mkConst `Ax [Level.param `u])"),
    ("def_imax_u1",
     "mkOracleDefn `D [`u] (mkSort (Level.imax (Level.param `u) Level.one)) "
     "(Lean.mkConst `Ax [Level.param `u])"),
    ("def_max_swap",
     "mkOracleDefn `E [`u] (mkSort (Level.max (Level.param `u) Level.one)) "
     "(Lean.mkConst `Ax [Level.max Level.one (Level.param `u)])"),
    # genuine non-sort declaration type: `Bool.true`'s type `Bool` is not a
    # sort, so ensure_sort raises typeExpected (kernel environment.cpp:131-132).
    ("non_sort_type",
     "mkOracleDefn `F [`u] (Lean.mkConst `Bool.true []) (Lean.mkConst `Bool [])"),
    # the shape §12.5(B) suggests for `.typeExpected` (type `Ax.{u}`, value
    # `Bool`). Real 4.33.1 reports `declTypeMismatch`: `Ax.{u}` has a sort
    # *type* (`Sort u`), so ensure_sort passes and the failure is value/type
    # mismatch instead. Kept to pin the actual kernel behaviour.
    ("spec_nonsort",
     "mkOracleDefn `G [`u] (Lean.mkConst `Ax [Level.param `u]) "
     "(Lean.mkConst `Bool [])"),
]

KDECL_EXPECT: dict[str, str] = {
    "ax_ok": "OK",
    "undef_param": "other",
    "inst_arity": "other",
    "def_simple": "OK",
    "def_imax_1u": "OK",
    "def_imax_u1": "declTypeMismatch",
    "def_max_swap": "OK",
    "non_sort_type": "typeExpected",
}


def main() -> int:
    fails: list[str] = []

    level_res = lean_ref.run_level_oracle(LEVEL_DEFS, LEVEL_CASES)
    assert len(level_res) == len(LEVEL_CASES)
    for (cid, _, _), r in zip(LEVEL_CASES, level_res):
        try:
            check_level(cid, r)
        except AssertionError as e:
            fails.append(f"LEVEL {cid}: {e}")
        # shape sanity: every documented key must be present
        for side in ("a", "b"):
            for key in ("explicit", "offset", "neverZero", "alwaysZero",
                        "ser", "norm", "levelOffset"):
                if key not in r[side]:
                    fails.append(f"LEVEL {cid}: missing {side}.{key}")

    kdecl_res = lean_ref.run_kdecl_oracle(KDECL_DEFS, KDECL_CASES)
    assert len(kdecl_res) == len(KDECL_CASES)
    for (cid, _), cls in zip(KDECL_CASES, kdecl_res):
        if cid == "spec_nonsort":
            # spec's suggested shape: assert only that it is rejected, since
            # real lean classifies it as declTypeMismatch (see KDECL_CASES).
            if cls == "OK":
                fails.append(f"KDECL {cid}: expected reject, got OK")
        elif KDECL_EXPECT.get(cid) != cls:
            fails.append(
                f"KDECL {cid}: expected {KDECL_EXPECT.get(cid)!r}, got {cls!r}")

    total = len(LEVEL_CASES) + len(KDECL_CASES)
    n_pass = total - len(fails)
    print(f"level/kdecl oracle self-consistency: {n_pass}/{total}")
    for msg in fails:
        print(f"  FAIL {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
