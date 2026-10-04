"""Card 015 beat-1 probes (lead-run 2026-09-21): oracle-side expectations for
the runtime universe/level channel (docs/plans/015-universe-level-runtime-channel.md).

P1/P3 (#KDECL verdicts for thm_imax / thm_max00 / def_imax on the non-normalized
Sort (imax 1 0) / Sort (max 0 0) types) are produced by the B-section rows of
tests/test_decl_injection_vs_lean.py itself — run with
    G02_ONLY=thm_imax,thm_max00,thm_sortraw_imax,thm_sortraw_max00,def_imax
and read the oracle column (kernel=OK / graph=8 is the recorded divergence).

This file carries:
- P2: universe-polymorphic accessor whnf — the oracle expectation for the
  shape the graph livelocks on at univ_arity=0 (g04b_c2_probe1.log).  The
  kernel whnf must reduce `UProd.fst (UProd.mk 3 4)` to the literal 3.
- P4: symbolic levels are the norm in a Mathlib closure (Level.param presence
  in the M-A dump), i.e. the channel is on the critical path of card 012 M-B.
- P4b: the B13 gap concretely — UProd.fst's stored VALUE carries lam-binders
  and a Proj with universe params, the shape a runtime channel must carry.

Run: L4TVM_LEAN=/home/xkq/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean \\
     /home/xkq/miniconda3/envs/train/bin/python -u tests/probe_015_semantics.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference import lean_ref
from reference import olean_export

LEAN_CMD = [os.environ.get(
    "L4TVM_LEAN",
    "/home/xkq/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean")]

U_PROD = ("structure UProd (α : Type u) (β : Type u) where\n"
          "  fst : α\n  snd : β\n")


def p2_univ_accessor_whnf():
    entries = [("WHNF", "UProd.fst (UProd.mk 3 4 : UProd Nat Nat)", None),
               ("INFER", "UProd.fst", None)]
    out = lean_ref.run_oracle_mixed(U_PROD, entries, lean_cmd=LEAN_CMD)
    print("P2 oracle output (UProd.fst on a constructor app):")
    for kind, payload in out:
        print(f"  {kind}: {payload}")
    return out


def p4_closure_level_shape():
    path = "/home/xkq/logs/012I/closures/Nat_testBit_land/dump.jsonl"
    n = poly = with_param = 0
    for line in open(path):
        line = line.strip()
        if not line.startswith("DUMPCONST"):
            continue
        o = json.loads(line[len("DUMPCONST"):])
        n += 1
        if o.get("up"):
            poly += 1
        if '"k":5,"n"' in json.dumps(o, separators=(",", ":")):
            with_param += 1
    print(f"P4 Mathlib closure Nat_testBit_land: consts={n} "
          f"univ-params={poly} with Level.param-in-tree={with_param}")
    return n, poly, with_param


def p4b_accessor_value_shape():
    dump = olean_export.dump_env(U_PROD, ["UProd", "UProd.fst"],
                                 path="/tmp/p4b_dump.lean", lean_cmd=LEAN_CMD)
    rec = dump["UProd.fst"]
    print("P4b UProd.fst stored type:", repr(rec["ty"])[:300])
    print("P4b UProd.fst stored value:", repr(rec["val"])[:500])
    print("P4b UProd.fst universe params:", rec["up"])
    return rec


if __name__ == "__main__":
    assert os.environ.get("L4TVM_LEAN"), "L4TVM_LEAN must be pinned to 4.33.1"
    p2_univ_accessor_whnf()
    p4_closure_level_shape()
    p4b_accessor_value_shape()
    print("PROBE-015 OK")
