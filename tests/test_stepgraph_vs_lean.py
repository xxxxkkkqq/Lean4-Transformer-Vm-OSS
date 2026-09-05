"""Phase 2 M2 test: the ALM step graph (via StepDriver) vs the real Lean
4.33.1 binary — the actual acceptance oracle. M2 scope = succ/pred/add/
sub/beq/ble (+ the main-loop mechanics they exercise: delta/zeta/beta/
walk). mul/pow/div/mod cases are expected divergences until M3.

Run: python3 tests/test_stepgraph_vs_lean.py   (CPU, ~1 min)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import MVar
from expr.tokens import Encoder, decode_closure
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference import lean_ref
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_LEAN_DEFS, CORPUS

M3_PENDING = set()


def main() -> int:
    n_pass = 0
    fails = []
    sources = [src for (_, src, _) in CORPUS]
    oracle = [payload for (_, payload) in
        lean_ref.run_oracle(TOY_LEAN_DEFS, sources)]

    for (cid, src, our_term), oracle_json in zip(CORPUS, oracle):
        expected = lean_ref.json_to_expr(oracle_json)
        if isinstance(expected, MVar):
            fails.append((cid, "oracle left an mvar (elaboration bug)"))
            continue
        graph, outputs = build_step_graph()
        enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        driver = StepDriver(enc.b, graph, outputs)
        try:
            gp, genv = driver.run(enc.encode_term(our_term))
            got = decode_closure(enc.b, gp, genv)
        except Exception as e:
            got = f"{type(e).__name__}: {e}"
        if got == expected:
            n_pass += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        elif cid in M3_PENDING:
            n_pass += 1
            print(f"  [XFAIL-M3] {cid}")
        else:
            fails.append((cid, f"\n         graph ={got!r}\n         lean  ={expected!r}"))

    n_total = len(CORPUS)
    print(f"\n=== step graph vs Lean 4.33.1: {n_pass}/{n_total} "
          f"({len(M3_PENDING)} pinned M3-pending) ===")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
