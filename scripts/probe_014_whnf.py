"""Card 014 / M2-04 (P2 probe): TASK_WHNF frame traffic at the d6 family.

The positive is_def_eq cache (P1) cannot cut d6's ring (M1-01c: 45/49
launches are new keys). The ring's per-layer cost is the below-family
whnf re-derivation — the kernel's answer to exactly that is the `whnf`
memo (K/type_checker.cpp:736-775 m_whnf, and whnf_core :490-491/:554).
This probe measures, empirically, whether a graph-side whnf memo has
anything to hit:

  * every TASK_WHNF frame launch: (focus pos, env root, soft flag) + step,
  * every completion (D moved onto the frame's caller): delivered
    (result pos, result env),
  * exact-duplicate launches = a launch whose input triple had an EARLIER
    completed WHNF frame (same triple) — a memo hit at dispatch,
  * potential step savings per duplicate (launch step − first completion).

Same minimal-env discipline as probe_014_trace (brec NAT/LST defs, warm
injection), run under the memory guard.

Usage:
  python3 -u scripts/probe_014_whnf.py [--cases d6] [--cap 720]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import (  # noqa: E402
    T_FRAME, T_STATE, TASK_WHNF, TASK_DEFEQ, T_WHNFCACHE,
)
from lean_vm.build_vm import build_step_graph  # noqa: E402
from lean_vm.step_driver import StepDriver  # noqa: E402
from lean_vm.ref_vm import VMError  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "brec", ROOT / "tests" / "test_brec_drec_iota_vs_lean.py")
brec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brec)


class WhnfTracer:
    """Stream-diff recorder for TASK_WHNF launch/complete events."""

    def __init__(self, drv: StepDriver, memo_kinds=()):
        self.drv = drv
        self.launches: list[dict] = []
        self.pops: list[dict] = []
        self.writes = []          # T_WHNFCACHE tokens observed (beat, fields)
        self.memo_kinds = memo_kinds
        self.steps = 0

    def run(self, tp, sp, max_steps):
        drv = self.drv
        fpos = drv._append(T_FRAME, V0=TASK_DEFEQ, V1=tp, X=0, E2=sp, F2=0)
        drv.init_state(tp, 0, 0, D=fpos, E=sp, F=0)
        for _ in range(max_steps):
            L0 = len(drv.b.stream)
            prev = drv.b.stream[-1] if drv.b.stream[-1][0] == T_STATE else None
            try:
                done, r = drv.step()
            except VMError as ex:
                return f"rej{ex.code}"
            if done:
                return f"halt{r[0]}"
            st = drv.b.stream[-1]
            assert st[0] == T_STATE
            # launches: fresh WHNF frames appended during this step
            for p in range(L0, len(drv.b.stream) - 1):
                k, v0, v1, v2, x, e2, f2 = drv.b.stream[p]
                if k == T_FRAME and v0 == TASK_WHNF:
                    self.launches.append(dict(
                        step=self.steps + 1, pos=p,
                        triple=(v1, x, e2), caller=v2))
                elif k in self.memo_kinds:
                    # raw-slot cache tokens appended this beat (write arm)
                    self.writes.append(dict(step=self.steps + 1, kind=k,
                                            fields=(v0, v1, v2, x, e2)))
            # completion: prev STATE's D frame (WHNF) → new D == its V2
            if prev is not None:
                Dp = prev[4]
                b = drv.b.stream
                if 1 <= Dp < len(b):
                    kp, v0p, v1p, v2p, xp, e2p, f2p = b[Dp]
                    if (kp == T_FRAME and v0p == TASK_WHNF
                            and st[4] == v2p and Dp != v2p):
                        self.pops.append(dict(
                            step=self.steps + 1, pos=Dp,
                            triple=(v1p, xp, e2p),
                            result=(st[1], st[2])))
            self.steps += 1
        return f"timeout{max_steps}"


def analyze(tr: WhnfTracer) -> dict:
    out = {"launches": len(tr.launches), "pops": len(tr.pops)}
    first_done = {}
    for po in tr.pops:
        key = str(po["triple"])
        if key not in first_done or po["step"] < first_done[key]["step"]:
            first_done[key] = po
    # frame-instance durations: launches and pops pair on the frame token
    # position. A duplicate launch that POPS IN 1 STEP is a memo hit (the
    # replay commit); a long-running duplicate means the memo did NOT absorb.
    pop_by_pos = {}
    for po in tr.pops:
        pop_by_pos.setdefault(po["pos"], po)
    durs = []
    for la in tr.launches:
        po = pop_by_pos.get(la["pos"])
        if po is not None:
            durs.append((la["step"], po["step"] - la["step"], la["triple"]))
    out["launch_durations"] = durs[:80]
    dups = []
    hit_dups = 0
    for la in tr.launches:
        fd = first_done.get(str(la["triple"]))
        if fd is not None and fd["step"] < la["step"]:
            po = pop_by_pos.get(la["pos"])
            d = (po["step"] - la["step"]) if po else None
            dups.append((la["step"], fd["step"], la["triple"], d))
            if d is not None and d <= 1:
                hit_dups += 1
    out["memo_writes"] = len(tr.writes)
    out["dup_hits_1step"] = hit_dups
    out["distinct_triples"] = len({str(l["triple"]) for l in tr.launches})
    out["duplicate_launches"] = len(dups)
    out["dup_examples"] = dups[:20]
    # savings proxy: steps between first completion and relaunch
    out["dup_saved_sample"] = sorted(
        (ls - fs for ls, fs, _t, _d in dups), reverse=True)[:20]
    out["launch_triples_seq"] = [(l["step"], l["pos"], l["triple"])
                                 for l in tr.launches[:80]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="d6")
    ap.add_argument("--cap", type=int, default=720)
    ap.add_argument("--out", default="/home/xkq/logs/014/whnf_result_m4.json",
                    help="M2's recon json is evidence; never overwrite it")
    args = ap.parse_args()

    t0 = time.perf_counter()
    G = build_step_graph()
    print(f"graph built {time.perf_counter()-t0:.1f}s", flush=True)

    wanted = set(args.cases.split(","))
    jobs = [("nat", cid, l, r) for cid, l, r in brec.NAT_CASES
            if cid.split("_")[-1] in wanted]
    jobs += [("lst", cid, l, r) for cid, l, r in brec.LST_CASES
             if cid.split("_")[-1] in wanted]

    results = {}
    cache = {}
    for grp, cid, l, r in jobs:
        defs = brec.NAT_DEFS if grp == "nat" else brec.LST_DEFS
        roots = brec.NAT_ROOTS if grp == "nat" else brec.LST_ROOTS
        if grp not in cache:
            consts, meta, _ = brec.build_group(defs, roots)
            cache[grp] = (brec.warm_prefix(consts, meta, *G), consts, meta)
        warm, consts, meta = cache[grp]
        env_len, warm_vals, warm_hist = warm
        enc = brec.Encoder(consts, is_ctor=brec.TOY_CTORS, const_meta=meta)
        drv = StepDriver(enc.b, *G)
        drv._eval.vals = list(warm_vals)
        drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
        tr = WhnfTracer(drv, memo_kinds=(T_WHNFCACHE,))
        tp = enc.encode_term(brec.Const(l))
        sp = enc.encode_term(brec.Const(r))
        res = tr.run(tp, sp, args.cap)
        a = analyze(tr)
        a["result"] = res
        a["steps"] = tr.steps
        results[cid] = a
        print(f"{cid}: {res} steps={tr.steps} whnf_launches={a['launches']} "
              f"pops={a['pops']} distinct={a['distinct_triples']} "
              f"dups={a['duplicate_launches']} "
              f"memo_writes={a['memo_writes']} dup_hits_1step={a['dup_hits_1step']} "
              f"saved_top={a['dup_saved_sample'][:6]}", flush=True)
        for ls, fs, tri, d in a["dup_examples"][:8]:
            print(f"   dup @launch {ls} (first done {fs}, saved≤{ls-fs}) "
                  f"triple={tri} dur={d}", flush=True)

    out = Path(args.out)
    out.write_text(json.dumps(results, indent=1, default=str))
    print(f"total {time.perf_counter()-t0:.1f}s → {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
