"""WP8 regression: the ALM step graph must identify kernel constants from WP1
metadata, not from the toy environment's cids.

The bug: ``lean_vm/build_vm.py`` identified Nat.zero / Nat.succ / Nat.rec /
Nat.pred / the P2 structure / the unit-like head by hardcoded numeric cids that
only line up with ``TOY_CONSTS``' manual ordering.  Any environment whose cids
are assigned differently (name-sorted real exports, or a reordered toy table)
misidentifies every special-cased constant, and the graph then rejects or loops
where RefVM accepts.

This test drives the *step graph* (``StepDriver``) and the reference interpreter
(``RefVM``) over the SAME bundles, in two constant orders, and pins that:

  * the graph agrees with RefVM on every curated case,
  * the verdicts are unchanged when the table is reversed (same names, totally
    different cids), and
  * the reversed table's cids really differ from the toy ones, so a pass cannot
    come from accidentally matching a hardcoded value.

No toy cid is written down here: the environment is built from the *names* in
`reference.toy_env.TOY_CONSTS`, metadata comes from the real lean binary via
`toy_const_meta()`, and only the subset needed by the cases is kept.  Two
subsets are used so the test stays quick: a small one (no recursor metadata
payload) for the nat-ctor / structure / unit-like cases, and one extended with
Nat.rec for the recursor dispatch + succ-rule rebuild cases.

Run: python3 tests/test_datadriven_env.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder
from expr.model import (
    App, Const, Lam, Proj, BVar, LitNat, BI_DEFAULT,
)
from lean_vm.ref_vm import RefVM, VMError
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_STRUCTS, toy_const_meta

NAT = Const("Nat")
UNITT = Const("UnitT")
P2 = Const("P2")
GRAPH_MAX_STEPS = 3000

# Small subset covering Nat.zero/succ detection, the name-keyed header-X scan
# (Nat.pred is the scan target the recursor rebuild also uses), Nat.add, the P2
# structure/eta/projection path, the UnitT unit-like head, and the Bool ctors.
BASE = [
    "Nat", "Nat.zero", "Nat.succ", "Nat.pred", "Nat.add",
    "Bool", "Bool.true", "Bool.false",
    "P2", "P2.mk", "UnitT", "UnitT.mk",
]
# Nat.rec carries the large recursor-rule rhs trees; only the recursor cases
# need it, so it lives in its own slightly slower group.
REC = BASE + ["Nat.rec"]

_REC_MOT = Lam("x", BI_DEFAULT, NAT, NAT)
_REC_SUCC = Lam("n", BI_DEFAULT, NAT, Lam("ih", BI_DEFAULT, NAT,
                                         App(Const("Nat.succ"), BVar(0))))


def _rec(z, s, maj):
    return App(App(App(App(Const("Nat.rec"), _REC_MOT), z), s), maj)


def _succ(t):
    return App(Const("Nat.succ"), t)


def _mk(a, b):
    return App(App(Const("P2.mk"), a), b)


# ("defeq", id, lhs, rhs, expected) / ("check", id, ty, val, expected).
# Every term only references names that are in the group's subset.
BASE_CASES = [
    ("defeq", "zero_lit", Const("Nat.zero"), LitNat(0), True),
    ("defeq", "succ_lit", _succ(Const("Nat.zero")), LitNat(1), True),
    ("defeq", "succ_lit_no", _succ(Const("Nat.zero")), LitNat(2), False),
    ("defeq", "add_zero_succ",
     App(App(Const("Nat.add"), Const("Nat.zero")), _succ(Const("Nat.zero"))),
     LitNat(1), True),
    ("defeq", "proj_fst_snd",
     Proj("P2", 0, _mk(Const("Nat.zero"), _succ(Const("Nat.zero")))),
     Const("Nat.zero"), True),
    ("defeq", "proj_snd",
     Proj("P2", 1, _mk(Const("Nat.zero"), _succ(Const("Nat.zero")))),
     _succ(Const("Nat.zero")), True),
    ("defeq", "unit_like",
     Lam("x", BI_DEFAULT, UNITT, Lam("y", BI_DEFAULT, UNITT, BVar(1))),
     Lam("x", BI_DEFAULT, UNITT, Lam("y", BI_DEFAULT, UNITT, BVar(0))), True),
    ("defeq", "unit_like_no",
     Lam("x", BI_DEFAULT, P2, Lam("y", BI_DEFAULT, P2, BVar(1))),
     Lam("x", BI_DEFAULT, P2, Lam("y", BI_DEFAULT, P2, BVar(0))), False),
    ("defeq", "bool_true", Const("Bool.true"), Const("Bool.true"), True),
    ("defeq", "bool_true_no", Const("Bool.true"), Const("Bool.false"), False),
    ("check", "check_zero", NAT, Const("Nat.zero"), True),
    ("check", "check_succ", NAT, _succ(Const("Nat.zero")), True),
    ("check", "check_bad", Const("Bool"), Const("Nat.zero"), False),
]

REC_CASES = [
    # major 1 keeps the reduction to a single succ-rule turn (the full 0..5
    # unroll is ~345 micro-steps and would dominate the test budget).
    ("defeq", "rec_succ", _rec(LitNat(0), _REC_SUCC, LitNat(1)), LitNat(1),
     True),
    ("defeq", "rec_zero", _rec(LitNat(7), _REC_SUCC, LitNat(0)), LitNat(7),
     True),
    ("defeq", "rec_succ_no", _rec(LitNat(0), _REC_SUCC, LitNat(1)), LitNat(2),
     False),
]

# names whose cids the old code hardcoded; used only to check the reversed
# table really moved them.
TRACKED = ("Nat.zero", "Nat.succ", "Nat.rec", "Nat.pred", "P2", "P2.mk",
           "UnitT")


def _bundle(subset_order, meta_by_name):
    """(consts, ctors, const_meta) for a subset in the given name order; cids
    follow the order exactly (no toy value is assumed or reused)."""
    toy_by_name = {n: (n, t, v) for n, t, v in TOY_CONSTS}
    consts = [toy_by_name[n] for n in subset_order]
    meta = {cid: copy.deepcopy(meta_by_name[n])
            for cid, n in enumerate(subset_order)}
    ctors = {n: True for n in subset_order if n in TOY_CTORS}
    return consts, ctors, meta


def _ref_verdict(ref_vm, ref_enc, kind, a, b):
    try:
        if kind == "defeq":
            return bool(ref_vm.defeq((ref_enc.encode_term(a), 0),
                                     (ref_enc.encode_term(b), 0)))
        ref_vm.check([(ref_enc.encode_term(a), ref_enc.encode_term(b))])
        return True
    except VMError:
        return False


def _run(tag, subset, cases, graph, outputs, fails):
    toy_names = [n for n, _, _ in TOY_CONSTS]
    full = toy_const_meta()
    meta_by_name = {n: full[i] for i, n in enumerate(toy_names)}
    consts, ctors, meta = _bundle(subset, meta_by_name)
    cid = {n: i for i, (n, _, _) in enumerate(consts)}

    ref_enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    ref_vm = RefVM(ref_enc.b, structures=TOY_STRUCTS)
    n_pass = 0
    for kind, cid_, a, b, expected in cases:
        exp = _ref_verdict(ref_vm, ref_enc, kind, a, b)
        if exp != expected:
            fails.append("%s/%s: RefVM expected=%s got=%s"
                         % (tag, cid_, expected, exp))
            continue
        ge = Encoder(consts, is_ctor=ctors, const_meta=meta)
        drv = StepDriver(ge.b, graph, outputs)
        try:
            if kind == "defeq":
                got = bool(drv.run_defeq(ge.encode_term(a), 0,
                                         ge.encode_term(b), 0,
                                         max_steps=GRAPH_MAX_STEPS)[0])
            else:
                drv.run_check([(ge.encode_term(a), ge.encode_term(b))],
                              max_steps=GRAPH_MAX_STEPS)
                got = True
        except VMError:
            got = False
        if got != expected:
            fails.append("%s/%s: graph=%s ref=%s" % (tag, cid_, got, expected))
        else:
            n_pass += 1
    print("  %-9s n=%2d  %2d/%d cases   cids: Nat.zero=%s Nat.succ=%s "
          "Nat.rec=%s P2=%s P2.mk=%s UnitT=%s"
          % (tag, len(consts), n_pass, len(cases), cid.get("Nat.zero"),
             cid.get("Nat.succ"), cid.get("Nat.rec"), cid.get("P2"),
             cid.get("P2.mk"), cid.get("UnitT")))
    return n_pass, cid


def main() -> int:
    fails: list[str] = []
    graph, outputs = build_step_graph()

    n_b1, cid_ident = _run("base", BASE, BASE_CASES, graph, outputs, fails)
    n_b2, cid_rev = _run("base/rev", list(reversed(BASE)), BASE_CASES,
                         graph, outputs, fails)
    n_r1, _ = _run("rec", REC, REC_CASES, graph, outputs, fails)
    n_r2, _ = _run("rec/rev", list(reversed(REC)), REC_CASES, graph, outputs,
                   fails)
    total = len(BASE_CASES) * 2 + len(REC_CASES) * 2
    got_total = n_b1 + n_b2 + n_r1 + n_r2

    # the reversed table must actually change every tracked cid, and each must
    # differ from that name's toy cid (the value the old code compared against),
    # so a pass cannot come from accidentally matching the hardcoded ordering.
    toy_cid = {n: i for i, (n, _, _) in enumerate(TOY_CONSTS)}
    for name in TRACKED:
        a, b = cid_ident.get(name), cid_rev.get(name)
        if a is not None and b is not None and a == b:
            fails.append("reversed table left %s at cid %s" % (name, a))
        if b is not None and b == toy_cid.get(name):
            fails.append("reversed table left %s at its toy cid %s" % (name, b))

    print("\n=== data-driven env: %d/%d cases over 4 name-order/subset runs ==="
          % (got_total, total))
    for f in fails:
        print("  [FAIL] " + f)
    return 0 if (got_total == total and not fails) else 1


if __name__ == "__main__":
    sys.exit(main())
