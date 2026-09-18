"""Card 014 / M2-03 diagnostic: d6 divergence dump (steps window).

Runs one DEFEQ case with warm injection (probe_014_trace pattern) and
dumps, per step in --from/--to, the head STATE (A..F) + D-frame contents,
then prints the tail of the stream and the unresolved frame chain.
Used to compare ON vs OFF behavior around the divergence point.

Usage: python3 -u scripts/probe_014_diag.py [--left d6l --right d6r]
       [--from 460 --to 500] [--cap 500] [--cache 1]
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import (  # noqa: E402
    T_FRAME, T_STATE, TASK_WHNF, TASK_DEFEQ, TASK_INFER, TASK_LEVEL,
    TASK_CHECK, T_DEFCACHE,
)
from lean_vm import build_vm  # noqa: E402
from lean_vm.step_driver import StepDriver, VMError  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "brec", ROOT / "tests" / "test_brec_drec_iota_vs_lean.py")
brec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brec)

TN = {TASK_WHNF: "WHNF", TASK_DEFEQ: "DEFEQ", TASK_INFER: "INFER",
      TASK_LEVEL: "LEVEL", TASK_CHECK: "CHECK"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", default="d6l")
    ap.add_argument("--right", default="d6r")
    ap.add_argument("--frm", type=int, default=460)
    ap.add_argument("--to", type=int, default=500)
    ap.add_argument("--cap", type=int, default=720)
    ap.add_argument("--cache", type=int, default=1)
    args = ap.parse_args()

    build_vm.VM014_CACHE = bool(args.cache)
    t0 = time.perf_counter()
    G = build_vm.build_step_graph()
    consts, meta, _ = brec.build_group(brec.NAT_DEFS, brec.NAT_ROOTS)
    warm = brec.warm_prefix(consts, meta, *G)
    env_len, warm_vals, warm_hist = warm
    enc = brec.Encoder(consts, is_ctor=brec.TOY_CTORS, const_meta=meta)
    drv = StepDriver(enc.b, *G)
    drv._eval.vals = list(warm_vals)
    drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
    tp = enc.encode_term(brec.Const(args.left))
    sp = enc.encode_term(brec.Const(args.right))
    print(f"setup {time.perf_counter()-t0:.1f}s cap={args.cap} "
          f"cache={args.cache}", flush=True)
    fpos = drv._append(T_FRAME, V0=TASK_DEFEQ, V1=tp, X=0, E2=sp, F2=0)
    drv.init_state(tp, 0, 0, D=fpos, E=sp, F=0)
    status = "running"
    for i in range(args.cap):
        try:
            done, r = drv.step()
        except VMError as ex:
            status = f"rej{ex.code}"
            break
        if done:
            status = f"halt{r}"
            break
        if args.frm <= i + 1 <= args.to:
            b = drv.b.stream
            st = b[-1]
            D = st[4]
            fr = (b[D] if 1 <= D < len(b) else None)
            fdesc = "None"
            if fr is not None and fr[0] == T_FRAME:
                fdesc = f"{TN.get(fr[1], fr[1])}(V1={fr[2]},V2={fr[3]},X={fr[4]},E2={fr[5]},F2={fr[6]})"
            nraw = sum(1 for t in b[200:] if t[0] == T_DEFCACHE)
            print(f"s{i+1:03d} A={st[1]} B={st[2]} C={st[3]} D={D} E={st[5]} "
                  f"F={st[6]} | {fdesc} | raw+{nraw}", flush=True)
    print("status:", status, "steps:", drv.steps, flush=True)
    b = drv.b.stream
    print(f"stream len {len(b)}, T_DEFCACHE total "
          f"{sum(1 for t in b if t[0] == T_DEFCACHE)}", flush=True)
    print("tail 25 tokens:")
    for p in range(max(0, len(b) - 25), len(b)):
        print(" ", p, b[p], flush=True)
    # unresolved frame chain from the head STATE's D upward via V2
    st = b[-1]
    D = st[4]
    print("frame chain from head D:")
    seen = 0
    while 1 <= D < len(b) and seen < 12:
        k, v0, v1, v2, x, e2, f2 = b[D]
        if k != T_FRAME:
            print("   D points at non-frame:", D, b[D], flush=True)
            break
        print(f"   pos {D}: {TN.get(v0, v0)} V1={v1} V2={v2} X={x} E2={e2} "
              f"F2={f2}", flush=True)
        D = v2
        seen += 1


if __name__ == "__main__":
    sys.exit(main())
