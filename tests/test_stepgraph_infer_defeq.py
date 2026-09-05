"""Phase 5 M2 differential test: the ALM step graph (StepDriver) vs the
RefVM infer/defeq subset, on the M1 corpus (21 DEFEQ + 16 INFER).
The ref side re-runs ref_vm (not real lean — the ref↔lean equality is
test_ref_infer_defeq.py's job); this pins graph ≡ ref.

DEFEQ comparison: boolean verdict. INFER comparison: decoded closure
equality (MData stripped, as in the M1 test).

M3 corpus cases (binder-identity / proof irrelevance / eta / eta-struct /
proj in DEFEQ_CORPUS after deq_big) are pinned here: RefVM implements them
(M3-ref step) but the step graph does not yet — the graph DEFEQ frames
loop on the new bid/fvar machinery, so they are XFAILed until the M3
graph-frame work lands, then unpinned one by one.

Run: python3 tests/test_stepgraph_infer_defeq.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure
from expr.model import MData, App, Lam, Pi, Let
from lean_vm.ref_vm import RefVM, VMError
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference.toy_env import (
    TOY_CONSTS, TOY_CTORS, TOY_STRUCTS, DEFEQ_CORPUS, INFER_CORPUS,
)

# M3 graph work pending: structural eta (Mechanism D)
M3_PENDING = {
    "deq_eta_lam",       # nested eta: the lam body's spine fn-pair has a
                         # >=1-hop BVar head; whnf-under-marker clobbers its
                         # env to 0 at the spine-end (sp_fin2), so the
                         # marker-vs-marker pair never reaches D_BV3. Needs a
                         # rework of env propagation in the shared spine-peel /
                         # whnf-under-marker path (regression risk to the 46
                         # passing whnf cases) — Phase 6.
}


def strip_mdata(e):
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
    n_pass = 0
    fails = []

    for cid, _, _, our_l, our_r in DEFEQ_CORPUS:
        if cid in M3_PENDING:
            print(f"  [XFAIL-M3] {cid} (graph frames pending)")
            continue
        ref_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        ref_vm = RefVM(ref_enc.b, structures=TOY_STRUCTS)
        lp = ref_enc.encode_term(our_l)
        rp = ref_enc.encode_term(our_r)
        try:
            expected = bool(ref_vm.defeq((lp, 0), (rp, 0)))
        except Exception as e:
            fails.append((cid, f"ref side: {e}"))
            continue
        graph, outputs = build_step_graph()
        g_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        driver = StepDriver(g_enc.b, graph, outputs)
        try:
            gp = g_enc.encode_term(our_l)
            gq = g_enc.encode_term(our_r)
            verdict = bool(driver.run_defeq(gp, 0, gq, 0)[0])
        except Exception as e:
            verdict = f"{type(e).__name__}: {e}"
        if verdict == expected:
            n_pass += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        else:
            fails.append((cid, f"graph={verdict} ref={expected}"))

    for cid, _, our_term in INFER_CORPUS:
        ref_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        ref_vm = RefVM(ref_enc.b, structures=TOY_STRUCTS)
        try:
            tp, tenv = ref_vm.infer(ref_enc.encode_term(our_term), 0)
            expected = strip_mdata(decode_closure(ref_enc.b, tp, tenv))
        except Exception as e:
            fails.append((cid, f"ref side: {e}"))
            continue
        graph, outputs = build_step_graph()
        g_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        driver = StepDriver(g_enc.b, graph, outputs)
        try:
            gp = g_enc.encode_term(our_term)
            tp, tenv = driver.run_infer(gp)
            got = strip_mdata(decode_closure(g_enc.b, tp, tenv))
        except Exception as e:
            got = f"{type(e).__name__}: {e}"
        if got == expected:
            n_pass += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        else:
            fails.append((cid, f"\n         graph={got!r}\n         ref  ={expected!r}"))

    total = len(DEFEQ_CORPUS) + len(INFER_CORPUS)
    print(f"\n=== step graph vs RefVM infer/defeq: {n_pass}/{total} "
          f"({len(M3_PENDING)} pinned M3-pending) ===")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
