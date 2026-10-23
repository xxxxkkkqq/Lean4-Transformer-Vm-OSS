#!/usr/bin/env python3
"""Footprint harness for the Python graph evaluator's history storage.

Card 012 M-B acceptance harness (ADR 024 §4 profile numbers, §6-P1
re-measurement): builds the 81-constant iota env (real lean oracle dump),
builds the step graph, prints the static structure, then drives one full
4440-token env warmup through IncrementalGraphEvaluator with per-checkpoint
structure/RSS lines, an internal RSS watchdog, and a teardown report.

History backend: --backend numpy (default, VM012_HISTORY=numpy, preallocated
float64 arrays are the authoritative history) or --backend list (legacy
per-entry (pos, kx, ky, values) tuple records + _mir key mirror). The list
backend run reproduces the ADR 024 §4 baseline (~6.1GB single-case warmup
peak); the numpy backend run is the P1 acceptance measurement.

Run (detached, mem-guarded, cores 14-19; see AGENTS.md machine discipline):

  setsid nohup systemd-run --user --scope -p MemoryMax=6500M \
    -p MemorySwapMax=0 \
    /home/xkq/miniconda3/envs/train/bin/python -u \
    scripts/run_mem_guarded.py --max-rss-mb 6500 --timeout 900 -- \
    env OMP_NUM_THREADS=3 taskset -c 14-19 \
    /home/xkq/miniconda3/envs/train/bin/python -u \
    scripts/profile_evaluator_memory.py --backend numpy \
    > /tmp/profile_eval_memory_<tag>.log 2>&1 < /dev/null &

Interpreter self-check: numpy must import from the pinned conda interpreter
(a bare degraded python3 fails here, not 200s into the warmup). torch is
deliberately NOT imported — this channel never uses it and the import would
pollute the RSS baseline the harness measures. The build_env step spawns the
real lean oracle (~1.6GB transient children RSS is outside this process).
"""
from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
os.chdir(REPO)

try:
    import numpy  # noqa: F401
except ImportError:
    print("FATAL: numpy unavailable — run under the pinned interpreter "
          "/home/xkq/miniconda3/envs/train/bin/python, not a bare python3",
          file=sys.stderr)
    sys.exit(2)

from lean_kernel.alm_p2 import (                       # noqa: E402
    IncrementalGraphEvaluator, _HistStore,
)
from lean_kernel.alm_graph import (                    # noqa: E402
    ReGLUDimension, PersistDimension, LookUpDimension, CumSumDimension,
)
from lean_vm.build_vm import build_step_graph          # noqa: E402
from lean_vm.step_driver import StepDriver             # noqa: E402
from expr.tokens import Encoder                       # noqa: E402
import test_iota_graph_vs_lean as iota_test            # noqa: E402


def _rss_mb() -> int:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return 0


def _hwm_mb() -> int:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) // 1024
    return 0


def _sample_entry_bytes(hist: dict, lookups_sampled: int = 20,
                        per_lookup: int = 50) -> float:
    """Mean deep bytes per history entry (tuple + fields + value floats),
    list backend. _HistStore entries report their array-storage share.
    Sampling strides over ALL lookups in creation order — the first
    lookups are the multi-value metadata ones, so a head-only sample is
    biased high (measured 388B vs ~260B representative, 2026-10-04)."""
    lids = [i for i, h in hist.items() if len(h)]
    if not lids:
        return 0.0
    if isinstance(hist[lids[0]], _HistStore):
        return sum(hist[i].storage_bytes() for i in lids) / \
            sum(len(hist[i]) for i in lids)
    total, n = 0, 0
    stride = max(1, len(lids) // lookups_sampled)
    for i in lids[::stride][:lookups_sampled]:
        h = hist[i]
        entries = h[::max(1, len(h) // per_lookup)][:per_lookup]
        for e in entries:
            s = (sys.getsizeof(e) + sys.getsizeof(e[0])
                 + sys.getsizeof(e[1]) + sys.getsizeof(e[2])
                 + sys.getsizeof(e[3]))
            s += sum(sys.getsizeof(f) for f in e[3])
            total += s
            n += 1
    return total / n if n else 0.0


def _vals_stats(vals: list, sample: int = 40):
    if not vals:
        return 0, 0, 0.0, 0.0
    idx = range(0, len(vals), max(1, len(vals) // sample))
    per_dict = sum(sys.getsizeof(vals[i]) for i in idx) / len(list(idx))
    keys = sum(len(vals[i]) for i in idx) / len(list(idx))
    return len(vals), int(per_dict), keys, per_dict * len(vals) / 2**20


def _gc_top(tag: str):
    cnt: Counter = Counter()
    for o in gc.get_objects():
        t = type(o).__name__
        c = cnt[t]
        cnt[t] = (c[0] + 1, c[1] + sys.getsizeof(o)) if c else \
                 (1, sys.getsizeof(o))
    top = sorted(cnt.items(), key=lambda kv: -kv[1][1])[:10]
    body = "  ".join(f"{k}={v[0]:,}/{v[1]/2**20:.0f}MB" for k, v in top)
    print(f"[{tag}] GC-TOP: {body}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Evaluator history-storage footprint harness "
                    "(card 012 M-B / ADR 024)")
    ap.add_argument("--backend", choices=("numpy", "list"), default="numpy",
                    help="history backend (default numpy = VM012_HISTORY "
                         "unset)")
    ap.add_argument("--checkpoints", default="500,2000,4440",
                    help="comma positions for structure probes")
    ap.add_argument("--chunk", type=int, default=25,
                    help="warmup sync granularity (positions per RSS check)")
    ap.add_argument("--rss-abort-mb", type=int, default=6300,
                    help="internal watchdog: abort the warmup above this "
                         "RSS (external mem-guard is the hard stop)")
    ap.add_argument("--gc-top", action="store_true",
                    help="gc.get_objects() type aggregation at checkpoints")
    args = ap.parse_args()

    if args.backend != "numpy":
        os.environ["VM012_HISTORY"] = args.backend
    elif "VM012_HISTORY" in os.environ:
        del os.environ["VM012_HISTORY"]      # explicit default

    t0 = time.perf_counter()
    print(f"[t] import {time.perf_counter()-t0:.1f}s  "
          f"interpreter={sys.executable}", flush=True)

    t0 = time.perf_counter()
    consts, meta, _dump = iota_test.build_env()
    extra = [n for n, _, _ in consts[len(iota_test.TOY_CONSTS):]]
    print(f"[t] build_env (lean oracle dump) {time.perf_counter()-t0:.1f}s, "
          f"consts={len(consts)} ({len(extra)} custom)", flush=True)

    graph, outputs = build_step_graph()
    by_type: Counter = Counter()
    for d in graph.all_dims:
        by_type[type(d).__name__] += 1
    print(f"graph dims total: {len(graph.all_dims)} by type: "
          f"{dict(by_type)}")
    print(f"graph lookups: {len(graph.all_lookups)}")
    ve = [len(lu.value_exprs) for lu in graph.all_lookups]
    hist_count: Counter = Counter(ve)
    print(f"lookup value_exprs: total {sum(ve)} max {max(ve)} "
          f"mean {sum(ve)/len(ve):.3f}")
    print(f"value-count histogram: {dict(sorted(hist_count.items()))}")
    print(f"persist dims (vals dict keys per position): "
          f"{sum(1 for d in graph.all_dims if isinstance(d, PersistDimension))}")
    print(f"outputs dict entries: {len(outputs)}")

    enc = Encoder(consts, is_ctor=iota_test.TOY_CTORS, const_meta=meta)
    drv = StepDriver(enc.b, graph, outputs)
    names = drv.names
    print(f"[t] Encoder {time.perf_counter()-t0:.1f}s  "
          f"stream N={len(enc.b.stream)} tokens")
    print(f"StepDriver names: {len(names)} input_tokens entries: "
          f"{len(graph.input_tokens)}")
    ops, nslots, _builtins, _pdims = drv._eval._plan
    print(f"eval plan nslots: {nslots} ops: {len(ops)}")

    ev = drv._eval
    backend = ("numpy" if isinstance(next(iter(ev.lookup_history.values())),
                                     _HistStore) else "list")
    print(f"backend: {backend} "
          f"(VM012_HISTORY={os.environ.get('VM012_HISTORY', '(unset)')})",
          flush=True)

    checkpoints = sorted({int(x) for x in args.checkpoints.split(",")
                          if x and int(x) <= len(names)})
    cps = checkpoints + [len(names)] if not checkpoints or \
        checkpoints[-1] != len(names) else checkpoints
    done = 0
    seg_t0 = time.perf_counter()
    peak = _hwm_mb()
    aborted = False
    for cp in cps:
        while done < cp:
            k = min(args.chunk, cp - done)
            ev.sync(names[:done + k])
            done += k
            rss = _rss_mb()
            if rss > args.rss_abort_mb:
                print(f"[{time.perf_counter()-seg_t0:.1f}s] ABORT: RSS "
                      f"{rss}MB > {args.rss_abort_mb}MB (internal watchdog)",
                      flush=True)
                aborted = True
                break
        if aborted:
            break
        wall = time.perf_counter() - seg_t0
        entries = sum(len(h) for h in ev.lookup_history.values())
        nonempty = sum(1 for h in ev.lookup_history.values() if len(h))
        per_entry = _sample_entry_bytes(ev.lookup_history)
        hist_mb = per_entry * entries / 2**20
        vn, per_dict, keys, vals_mb = _vals_stats(ev.vals)
        floats_mb = vn * keys * sys.getsizeof(0.0) / 2**20
        if backend == "list":
            mir_mb = sum(m[0].nbytes + m[1].nbytes
                         for m in ev._mir.values()) / 2**20
            per_entry_s = f"{per_entry:.0f}B"
        else:
            mir_mb = 0.0    # arrays authoritative, counted in hist_total
            per_entry_s = f"{per_entry:.1f}B(arr)"
        print(f"[{wall:.1f}s rss={_rss_mb()}MB] case1@{done}: "
              f"hist entries={entries:,} nonempty_lookups={nonempty} "
              f"per_entry={per_entry_s} hist_total~{hist_mb:.0f}MB "
              f"vals n={vn} per_dict~{per_dict}B vals~{vals_mb:.0f}MB "
              f"(+floats~{floats_mb:.0f}MB) _mir~{mir_mb:.0f}MB "
              f"input_tokens={len(graph.input_tokens)} "
              f"ms/pos={1000*wall/max(1,done):.1f}", flush=True)
        if args.gc_top:
            _gc_top(f"{wall:.1f}s case1@{done}")
        peak = max(peak, _hwm_mb())

    if not aborted:
        print(f"[{time.perf_counter()-seg_t0:.1f}s] case1 warmup complete "
              f"peak_rss={_hwm_mb()}MB", flush=True)
        del drv, enc, ev
        gc.collect()
        print(f"[{time.perf_counter()-seg_t0:.1f}s] after teardown "
              f"gc.collect: rss={_rss_mb()}MB peak={_hwm_mb()}MB",
              flush=True)
    return 0 if not aborted else 1


if __name__ == "__main__":
    sys.exit(main())
