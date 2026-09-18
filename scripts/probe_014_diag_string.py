"""Card 014 / M6-03(2): per-beat dump of the string DEFEQ breach.

Same contract as probe_014_diag_check.py but for the WP5 string suite's
B-group DEFEQ cases (run_defeq on the meta-carrying env with the warm
prefix).  State comes from the env gates VM014_CACHE / VM014_WMEMO at
process start.  Prints every beat: committed STATE, tokens appended that
beat, D-frame, plus a tail inventory of all cache tokens (kind 41/43) so
a diverging hit can be matched against the entry it replayed.

  VM014_CACHE=1 VM014_WMEMO=0 python -u scripts/probe_014_diag_string.py deq_oflist_true 330 345
  VM014_CACHE=1 VM014_WMEMO=1 python -u scripts/probe_014_diag_string.py deq_oflist_true 330 345
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import (Encoder, T_FRAME, T_STATE, T_PEND, T_LINK,
                         T_LIT_DIG, K_LIT, K_CONST, T_REJECT, T_HALT,
                         TASK_WHNF, TASK_DEFEQ, TASK_INFER, TASK_LEVEL,
                         TASK_CHECK, T_DEFCACHE, T_WHNFCACHE)
from lean_vm.build_vm import build_step_graph, VM014_CACHE, VM014_WMEMO
from lean_vm.step_driver import StepDriver, VMError

import tests.test_string_graph_vs_lean as w5

TASKN = {TASK_WHNF: "WHNF", 2: "NAT", 3: "WALK", 5: "ST",
         TASK_INFER: "INFER", TASK_DEFEQ: "DEFEQ", TASK_LEVEL: "LEVEL",
         TASK_CHECK: "CHECK"}
KINDN = {0: "NULL", T_FRAME: "FRAME", T_STATE: "STATE", T_PEND: "PEND",
         T_LINK: "LINK", T_LIT_DIG: "DIG", K_LIT: "LIT", K_CONST: "CONST",
         T_REJECT: "REJECT", T_HALT: "HALT",
         T_DEFCACHE: "DEFCACHE", T_WHNFCACHE: "WHNFCACHE"}


def fmt(tok):
    k, v0, v1, v2, x, e2, f2 = tok
    if k == T_FRAME:
        return f"FRAME({TASKN.get(v0, v0)},{v1},{v2},{x},{e2},{f2})"
    return f"{KINDN.get(k, k)}({v0},{v1},{v2},{x},{e2},{f2})"


def main() -> int:
    cid = sys.argv[1] if len(sys.argv) > 1 else "deq_oflist_true"
    frm = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    to = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 9
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else w5.GRAPH_MAX_STEPS
    consts, ctors, meta, _ordered = w5.build_env()
    case = next(c for c in w5.CASES if c[0] == cid)
    assert case[1] == "DEFEQ", cid
    ea, eb = case[4], case[5]

    print(f"=== diag {cid} cache={int(VM014_CACHE)} wmemo={int(VM014_WMEMO)} "
          f"window [{frm},{to}] ===")
    graph, outputs = build_step_graph()
    warm = w5._warm_prefix(consts, ctors, meta, graph, outputs)
    env_len, warm_vals, warm_hist = warm
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    drv = StepDriver(enc.b, graph, outputs)
    drv._eval.vals = list(warm_vals)
    drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
    b = enc.b.stream
    tp = enc.encode_term(ea)
    sp = enc.encode_term(eb)
    # mirror run_defeq's injection
    fpos = drv._append(T_FRAME, V0=TASK_DEFEQ, V1=tp, X=0, E2=sp, F2=0)
    drv.init_state(tp, 0, D=fpos, E=sp, F=0)
    print(f"prefix len={len(b)} t={tp} s={sp}")
    for i in range(cap):
        before = len(b)
        # flags for THIS beat = transition evaluated on the current (input)
        # tokens; sync is incremental, so the following step() reuses them.
        try:
            vv = drv._eval.sync(drv.names)
            fl = " ".join(f"{k}={drv._val(vv, k)}"
                          for k in ("dbg_wchit", "dbg_wcw", "dbg_dchit",
                                    "dbg_dcw"))
        except Exception:
            fl = "flags=n/a"
        try:
            done, r = drv.step()
        except VMError as ex:
            print(f"s{i+1:03d} {fl} REJECT code={ex.code} focus={ex.focus}")
            for p in range(before, len(b)):
                print(f"      + {p} {fmt(b[p])}")
            break
        if frm <= i + 1 <= to:
            st = b[-1]
            D = st[4]
            fr = b[D] if 1 <= D < len(b) else None
            print(f"s{i+1:03d} {fl} A={st[1]} B={st[2]} C={st[3]} D={D} "
                  f"E={st[5]} F={st[6]} | frame@D "
                  f"{fmt(fr) if fr is not None else 'None'} | {fl}")
            for p in range(before, len(b) - 1):
                print(f"      + {p} {fmt(b[p])}")
        if done:
            print(f"s{i+1:03d} HALT done result={r}")
            break
    print(f"stream len {len(b)}")
    print("--- cache token inventory (pos: kind(v0,v1,v2,x,e2,f2)) ---")
    for p, t in enumerate(b):
        if t[0] in (T_DEFCACHE, T_WHNFCACHE):
            print(f"  {p}: {fmt(t)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
