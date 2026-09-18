"""Card 014 / M1-01: DEFEQ-stream trace probe (no graph change).

Records every DEFEQ frame launch and pop (pair fields, verdict, step,
stream position) by diffing the token stream after each StepDriver step,
then answers the cache-design questions empirically:
  * how often does the SAME completed-True (t,s) pair get relaunched
    (the positive-cache hit d6 needs),
  * which key field repeats (t_pos / t_env / s_pos / s_env) — attention
    query key can carry exactly one scalar,
  * shadow rate of a "latest entry whose key-field matches" policy,
  * cache-entry count and probe distances (steps / stream positions).

Usage:
  python3 -u scripts/probe_014_trace.py [--cases d6,d7] [--cap 300]
Run under run_mem_guarded, cores 0-5, log to $HOME/logs/014/.
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
    T_FRAME, T_STATE, TASK_DEFEQ, TASK_INFER, TASK_WHNF, TASK_LEVEL,
    TASK_CHECK,
)
from lean_vm.build_vm import build_step_graph  # noqa: E402
from lean_vm.step_driver import StepDriver  # noqa: E402
from lean_vm.ref_vm import VMError  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "brec", ROOT / "tests" / "test_brec_drec_iota_vs_lean.py")
brec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brec)

FRAME_TASK_NAME = {TASK_WHNF: "WHNF", TASK_INFER: "INFER",
                   TASK_DEFEQ: "DEFEQ", TASK_LEVEL: "LEVEL",
                   TASK_CHECK: "CHECK"}


class Tracer:
    """Per-step stream diff → launch/pop event log for DEFEQ frames."""

    def __init__(self, drv: StepDriver):
        self.drv = drv
        self.events: list[dict] = []       # launches + pops
        self.launches: list[dict] = []
        self.pops: list[dict] = []
        self.steps = 0
        self.prev_head = None              # (pos, V0..F2) of head frame
        self.done = None

    def head_frame(self, state_tok):
        D = state_tok[4]
        b = self.drv.b
        if 1 <= D < len(b.stream):
            k, v0, v1, v2, x, e2, f2 = b.stream[D]
            if k == T_FRAME:
                return (D, v0, v1, v2, x, e2, f2)
        return None

    def run(self, tp, sp, max_steps):
        drv = self.drv
        fpos = drv._append(T_FRAME, V0=TASK_DEFEQ, V1=tp, X=0, E2=sp, F2=0)
        drv.init_state(tp, 0, 0, D=fpos, E=sp, F=0)
        self.record_launch(fpos)
        for _ in range(max_steps):
            L0 = len(drv.b.stream)
            prev = drv.b.stream[-1] if drv.b.stream[-1][0] == T_STATE else None
            try:
                done, r = drv.step()
            except VMError as ex:
                self.done = f"rej{ex.code}"
                return self.done
            if done:
                self.done = f"halt{r}"
                return self.done
            st = drv.b.stream[-1]
            assert st[0] == T_STATE
            for p in range(L0, len(drv.b.stream) - 1):
                k, v0, v1, v2, x, e2, f2 = drv.b.stream[p]
                if k == T_FRAME and v0 == TASK_DEFEQ:
                    self.record_launch(p)
            # pop detection: head BEFORE this step was a DEFEQ frame and the
            # fresh STATE's D moved off it.  STATE token layout:
            # (T_STATE, A, B, C, D, E, F) → A=st[1], D=st[4].
            if prev is not None:
                Dp = prev[4]
                b = drv.b.stream
                if 1 <= Dp < len(b):
                    kp, v0p, v1p, v2p, xp, e2p, f2p = b[Dp]
                    # a POP = D moved exactly onto the frame's caller V2
                    # (D moving to c1/c2 of the same step is a push above
                    # the DEFEQ frame, not a completion)
                    if kp == T_FRAME and v0p == TASK_DEFEQ \
                            and st[4] == v2p and Dp != v2p:
                        self.pops.append(dict(step=self.steps, pos=Dp,
                                              pair=(v1p, xp, e2p, f2p),
                                              verdict=int(st[1] >= 1),
                                              caller=st[4]))
            self.steps += 1
        self.done = f"timeout{max_steps}"
        return self.done

    def record_launch(self, p):
        k, v0, v1, v2, x, e2, f2 = self.drv.b.stream[p]
        self.launches.append(dict(step=self.steps, pos=p,
                                  pair=(v1, x, e2, f2), v2=v2))


def analyze(tr: Tracer) -> dict:
    out = {}
    L = tr.launches
    P = tr.pops
    out["launches"] = len(L)
    out["pops"] = len(P)
    out["pops_true"] = sum(1 for p in P if p["verdict"])
    out["pops_false"] = sum(1 for p in P if not p["verdict"])

    # (a) exact-repeat relaunches: a launch whose pair had an EARLIER
    # completed-True pop → positive-cache hit at launch time
    hit_launches = []
    for la in L:
        for po in P:
            if po["step"] < la["step"] and po["verdict"] and \
                    po["pair"] == la["pair"]:
                hit_launches.append((la, po))
                break
    out["exact_repeat_launches"] = len(hit_launches)
    out["hit_step_savings_sample"] = [
        (la["step"], po["step"], la["step"] - po["step"])
        for la, po in hit_launches[:10]]

    # pair frequency (all launches)
    from collections import Counter
    cf = Counter(str(l["pair"]) for l in L)
    out["top_pairs"] = cf.most_common(8)

    # (b) field-sharing of exact-repeat pairs: for each repeat group,
    # which single field value is shared with OTHER distinct pairs?
    # key-field candidate scoring: a key K is good if entries sharing K
    # are mostly the same pair (latest-shadow = the pair itself).
    entries = []           # (pos, pair, verdict) at True pops
    seen = set()
    for po in P:
        if po["verdict"] and po["pair"] not in seen:
            seen.add(po["pair"])
            entries.append(po)
    out["distinct_true_pairs"] = len(entries)
    shadow = {}
    for ki, kn in enumerate(("t_pos", "t_env", "s_pos", "s_env")):
        bad = 0
        for la in L:
            cand = [e for e in entries if e["pair"][ki] == la["pair"][ki]
                    and e["step"] < la["step"]]
            if cand:
                latest = max(cand, key=lambda e: e["pos"])
                if latest["pair"] != la["pair"]:
                    bad += 1
        shadow[kn] = bad
    out["shadow_by_field"] = shadow

    # (c) growth trace: distinct pairs over time windows (ring evidence)
    out["pop_pairs_seq"] = [(p["step"], p["pair"], p["verdict"]) for p in P]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="d6,d7")
    ap.add_argument("--cap", type=int, default=300)
    args = ap.parse_args()

    t0 = time.perf_counter()
    G = build_step_graph()
    print(f"graph built {time.perf_counter()-t0:.1f}s", flush=True)

    wanted = set(args.cases.split(","))
    jobs = []
    for cid, l, r in brec.NAT_CASES:
        key = cid.split("_")[-1]
        if key in wanted:
            jobs.append(("nat", cid, l, r))
    for cid, l, r in brec.LST_CASES:
        key = cid.split("_")[-1]
        if key in wanted:
            jobs.append(("lst", cid, l, r))

    results = {}
    graph_cache = {}
    for grp, cid, l, r in jobs:
        defs = brec.NAT_DEFS if grp == "nat" else brec.LST_DEFS
        roots = brec.NAT_ROOTS if grp == "nat" else brec.LST_ROOTS
        if grp not in graph_cache:
            t1 = time.perf_counter()
            consts, meta, _ = brec.build_group(defs, roots)
            graph_cache[grp] = brec.warm_prefix(consts, meta, *G)
            graph_cache[grp + "_consts"] = (consts, meta)
            print(f"{grp} warm {time.perf_counter()-t1:.1f}s", flush=True)
        consts, meta = graph_cache[grp + "_consts"]
        enc = brec.Encoder(consts, is_ctor=brec.TOY_CTORS, const_meta=meta)
        drv = StepDriver(enc.b, *G)
        # warm injection (mirrors brec.run_defeq): without this the Python
        # evaluator recomputes the whole env from scratch every step (O(N²),
        # hit the 4GB guard at 60 steps).
        env_len, warm_vals, warm_hist = graph_cache[grp]
        drv._eval.vals = list(warm_vals)
        drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
        tr = Tracer(drv)
        tp = enc.encode_term(brec.Const(l))
        sp = enc.encode_term(brec.Const(r))
        res = tr.run(tp, sp, args.cap)
        a = analyze(tr)
        a["launch_events"] = tr.launches
        a["pop_events"] = tr.pops
        a["result"] = res
        a["wall_s"] = round(tr.steps * 0 + (time.perf_counter() - t0), 1)
        a["steps"] = tr.steps
        results[cid] = a
        print(f"{cid}: {res} steps={tr.steps} launches={a['launches']} "
              f"pops={a['pops']}(T{a['pops_true']}/F{a['pops_false']}) "
              f"exact_repeats={a['exact_repeat_launches']} "
              f"distinct_true={a['distinct_true_pairs']} "
              f"shadow={a['shadow_by_field']}", flush=True)
        for t in a["top_pairs"][:5]:
            print(f"   pair {t[0]} x{t[1]}", flush=True)

    out = Path("/home/xkq/logs/014/trace_result.json")
    out.write_text(json.dumps(results, indent=1, default=str))
    print(f"total {time.perf_counter()-t0:.1f}s → {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
