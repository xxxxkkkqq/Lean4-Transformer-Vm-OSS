"""Phase 2 M2 test: the ALM step graph (via StepDriver) vs RefVM with nat
ops enabled, on the full corpus. M2 scope = succ/pred/add/sub/beq/ble;
the mul/pow/div/mod cases (and any case whose args contain them) are
expected divergences until M3 — the test pins them explicitly so the
suite is green at M2 and the xfail list shrinks to empty at M3.

Run: python3 tests/test_stepgraph_vs_refvm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure
from lean_vm.ref_vm import RefVM
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference.toy_env import TOY_CONSTS, TOY_CTORS, CORPUS

# M3 complete: all ten nat ops implemented; no pinned divergences left
M3_PENDING = set()


def main() -> int:
    n_pass = 0
    fails = []
    for cid, src, term in CORPUS:
        # reference side: its own bundle (both sides mutate their streams)
        ref_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        ref_vm = RefVM(ref_enc.b, nat_enabled=True)
        try:
            rp, renv = ref_vm.whnf(ref_enc.encode_term(term), 0)
            expected = decode_closure(ref_enc.b, rp, renv)
        except Exception as e:
            fails.append((cid, f"ref side: {e}"))
            continue
        # graph side: fresh encoder per case, shared graph
        graph, outputs = build_step_graph()
        g_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        driver = StepDriver(g_enc.b, graph, outputs)
        try:
            gp, genv = driver.run(g_enc.encode_term(term))
            got = decode_closure(g_enc.b, gp, genv)
        except Exception as e:
            got = f"{type(e).__name__}: {e}"
        if got == expected:
            n_pass += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        elif cid in M3_PENDING:
            n_pass += 1
            print(f"  [XFAIL-M3] {cid}")
        else:
            fails.append((cid, f"\n         graph ={got!r}\n         ref   ={expected!r}"))

    n_total = len(CORPUS)
    print(f"\n=== step graph vs RefVM(nat on): {n_pass}/{n_total} "
          f"({len(M3_PENDING)} pinned M3-pending) ===")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
