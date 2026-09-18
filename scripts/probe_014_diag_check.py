"""Card 014 / M6-03 diagnostic: per-beat dump of the CHECK-flow breach.

The bisect (010-M M6-02) pinned the culprit to VM014_WMEMO; the smallest
breach (b_inc / chk_inc_fn) REJECTS AT STEP ~5 with ZERO cache tokens in
the stream — so the divergence cannot be a replay of a written entry.
This probe replays the driver loop by hand and prints, per beat, every
token appended that beat (kind + fields) and the committed head STATE,
so two states can be diffed beat-by-beat to find the FIRST drifting beat.

State is fixed at process start via the env gates VM014_CACHE /
VM014_WMEMO (read by lean_vm.build_vm at import).  Run one state per
process:

  VM014_CACHE=1 VM014_WMEMO=0 python -u scripts/probe_014_diag_check.py b_inc
  VM014_CACHE=1 VM014_WMEMO=1 python -u scripts/probe_014_diag_check.py b_inc
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import (Encoder, T_FRAME, T_STATE, T_PEND, T_LINK,
                         T_LIT_DIG, K_LIT, K_CONST, T_REJECT,
                         T_HALT, TASK_WHNF, TASK_DEFEQ, TASK_INFER,
                         TASK_LEVEL, TASK_CHECK, T_DEFCACHE, T_WHNFCACHE)
from lean_vm.build_vm import build_step_graph, VM014_CACHE, VM014_WMEMO
from lean_vm.step_driver import StepDriver, VMError

TASKN = {TASK_WHNF: "WHNF", TASK_DEFEQ: "DEFEQ", TASK_INFER: "INFER",
         TASK_LEVEL: "LEVEL", TASK_CHECK: "CHECK"}
KINDN = {0: "NULL", T_FRAME: "FRAME", T_STATE: "STATE", T_PEND: "PEND",
         T_LINK: "LINK", T_LIT_DIG: "DIG", K_LIT: "LIT", K_CONST: "CONST",
         T_REJECT: "REJECT", T_HALT: "HALT",
         T_DEFCACHE: "DEFCACHE", T_WHNFCACHE: "WHNFCACHE"}


def tok_name(k):
    return KINDN.get(k, str(k))


def fmt(tok):
    k, v0, v1, v2, x, e2, f2 = tok
    extra = f"{TASKN.get(v0, v0)}," if k == T_FRAME else ""
    return f"{tok_name(k)}({extra}{v0},{v1},{v2},{x},{e2},{f2})"


def main() -> int:
    cid = sys.argv[1] if len(sys.argv) > 1 else "b_inc"
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    from tests.test_check_e2e import CASE
    from tests.test_mutation_reject import BASE
    from tests.test_olean_export import TARGET_DEFS, ROOTS
    from reference.olean_export import import_env
    consts, ctors, structs = import_env(TARGET_DEFS, ROOTS)
    table = BASE if cid in BASE else CASE
    _t, _v, te, ve = table[cid]

    print(f"=== diag {cid} cache={int(VM014_CACHE)} wmemo={int(VM014_WMEMO)} ===")
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    drv = StepDriver(enc.b, graph, outputs)
    tr, vr = enc.encode_term(te), enc.encode_term(ve)
    # mirror run_check's injection exactly
    nxt = 0
    for (t_root, v_root) in reversed([(tr, vr)]):
        nxt = drv._append(T_FRAME, V0=TASK_CHECK, V1=t_root, V2=nxt, X=v_root)
    drv.init_state(vr, 0, 0, D=nxt)
    b = enc.b.stream
    print(f"prefix: env region len={len(b)} (T_NULL@0 = {b[0]})")
    for i in range(cap):
        before = len(b)
        try:
            done, r = drv.step()
        except VMError as ex:
            print(f"s{i+1:03d} REJECT code={ex.code} focus={ex.focus}")
            for p in range(before, len(b)):
                print(f"      + {p} {fmt(b[p])}")
            break
        appended = [f"{p} {fmt(b[p])}" for p in range(before, len(b))]
        st = b[-1]
        D = st[4]
        fr = b[D] if 1 <= D < len(b) else None
        fd = fmt(fr) if fr is not None else "None"
        print(f"s{i+1:03d} A={st[1]} B={st[2]} C={st[3]} D={D} E={st[5]} "
              f"F={st[6]} | frame@D {fd}")
        for a in appended[:-1]:
            print(f"      + {a}")
        if done:
            print(f"s{i+1:03d} HALT done result={r}")
            break
    n41 = sum(1 for t in b if t[0] == T_DEFCACHE)
    n43 = sum(1 for t in b if t[0] == T_WHNFCACHE)
    print(f"stream len {len(b)} defcache={n41} whnfcache={n43}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
