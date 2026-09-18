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

# P7.5c-1b complete: Nat.brecOn is in the ALM step graph (fire/zero/succ/
# stuck iota + the 5-token build loop), all 5 deq_brec_* unpinned.  The stuck
# case needed one toy-env fix: _pi_natbrecOn's result codomain encoded
# `motive F` instead of `motive t` (de Bruijn App(BVar(1), BVar(0)) →
# App(BVar(1), BVar(2))).  Run 1 (spine infer) never derefs the lazy cod so
# the 4 iota cases stayed green; the stuck case's proof-irrel chain INFERs the
# cod closure → `(fun _ => Nat) minor` → infer(minor's type)=PICLO vs dom=Nat
# → stuck pair → reject 4.  The RefVM masked the same bug: _proof_irrel is
# try/except-wrapped, so its cod-infer threw and fell through to the spine
# compare (same verdict by luck).
# Earlier pins, all resolved: P7.5b Nat.casesOn + P2.casesOn (7 cases), Phase 6
# P6.5 Nat.rec iota (7 cases; fixes: _REC_MOT motive-domain ill-typing,
# _pi_natrec off-by-N de Bruijn motive refs, D_XPI2/D_TPC2 defaulting their
# body-compare frame to WHNF instead of DEFEQ).
M3_PENDING = set()

# P7.5c Route-2 CLOSED: `deq_brec_sum_stuck` (recursive-minor brecOn) now
# halts True on the graph — full DEFEQ corpus 65/65 graph-vs-ref, no regressions.
# The earlier "recursor result-type instantiation bug" diagnosis was WRONG: the
# walk-off at env #752 was legitimate; what was missing is that the graph
# HARD-rejected where the kernel (and RefVM's try/except-wrapped _proof_irrel /
# _unit_like) DECLINES.  Four layers, all in build_vm.py:
#   1. soft bit on UL-chain infer launches.  On TASK_INFER frames E2 is the
#      phase flag; the soft bit is F2 (soft_flag).  The ST_UL and ul_yes infer
#      launches set only E2=1, so the `motive t` codomain infer that falls off
#      the alt-env was hard-rejected (code 4 @~325).  Both now carry F2=One.
#   2./3. decline markers.  A soft infer that fails delivers A=0 to the next UL
#      stage; UL_W would whnf that sentinel (no rule → livelock) and UL_D would
#      DEFEQ against it.  Both stages guard A=0 and return the unit_like
#      verdict-False to the caller, mirroring ul_no (ref: infer raises → not
#      unit-like → stuck chain continues).
#   4. nested-NAT soft-flag read.  Whnf-ing a casesOn scrutinee nests NAT frames
#      (NAT(succ) → NAT(caseson) → WHNF), so the one-hop wpos climb read the
#      intermediate NAT frame's E2 (a node pos) as the soft flag and
#      hard-rejected (code 1 @424).  wpos now climbs one more hop when the
#      parent is itself a NAT control frame (stuck_nat_nested).
P75C_PENDING = set()

# Fail-fast budget for the graph side: the legitimate corpus max is
# deq_brec_sum_stuck @ 1052 micro-steps (next: deq_brec_stuck @ 578, pair-free
# delta; was 1717 under the P2 encoding); 6000 clears it with headroom while
# turning any future runaway into a TimeoutError in ~10 min instead of the
# 10000-step default's ~20 min silent burn.
GRAPH_MAX_STEPS = 6000


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
        if cid in P75C_PENDING:
            print(f"  [XFAIL-P75c] {cid} (Route-A recursive-minor decline-loop; "
                  f"see P75C_PENDING note)")
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
            verdict = bool(driver.run_defeq(gp, 0, gq, 0,
                                            max_steps=GRAPH_MAX_STEPS)[0])
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
            tp, tenv = driver.run_infer(gp, max_steps=GRAPH_MAX_STEPS)
            got = strip_mdata(decode_closure(g_enc.b, tp, tenv))
        except Exception as e:
            got = f"{type(e).__name__}: {e}"
        if got == expected:
            n_pass += 1
            print(f"  [PASS] {cid} ({driver.steps} micro-steps)")
        else:
            fails.append((cid, f"\n         graph={got!r}\n         ref  ={expected!r}"))

    pinned = len(M3_PENDING) + len(P75C_PENDING)
    total = len(DEFEQ_CORPUS) + len(INFER_CORPUS)
    attempted = total - pinned
    print(f"\n=== step graph vs RefVM infer/defeq: {n_pass}/{attempted} "
          f"({pinned} pinned: {len(M3_PENDING)} M3 + {len(P75C_PENDING)} P7.5c) ===")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
