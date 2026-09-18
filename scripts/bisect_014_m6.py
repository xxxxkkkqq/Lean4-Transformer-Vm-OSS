"""M6-02 three-state bisect harness for card 014's verdict-invariance breach.

Runs ONE failing corpus case through the Python step graph and prints the
graph verdict + step count + cache-token counts.  The gate switches are
process-level (VM014_CACHE / VM014_WMEMO read at build_vm import), so the
three states are three separate processes on the same command line:

  VM014_CACHE=0 VM014_WMEMO=0 python scripts/bisect_014_m6.py chk_inc_fn  # OFF
  VM014_CACHE=1 VM014_WMEMO=0 python scripts/bisect_014_m6.py chk_inc_fn  # P1
  VM014_CACHE=1 VM014_WMEMO=1 python scripts/bisect_014_m6.py chk_inc_fn  # P2

Invariance criterion = verdict identical to the OFF state (the suites
themselves pin OFF == live lean; no answers are baked in here — the only
expectations quoted below are the 2026-09-17 regression-log observations,
which are graph/refvm readings, not oracle values).

Cases (the breach face, 010-M lead alert):
  deq_oflist_true / deq_proj_vs_oflist_true  (string suite, B group)
  chk_inc_fn                                 (check_e2e, layer B)
  b_inc                                      (mutation_reject, part A BASE)
  m_dbl_bool / m_pairapp_p2                  (mutation_reject, localize)
  inf_hof_app                                (olean_export, layer B INFER)
"""
from __future__ import annotations

import sys
import os
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import Encoder, decode_closure          # noqa: E402
from expr.model import Const, App                        # noqa: E402
from lean_vm.build_vm import build_step_graph, VM014_CACHE, VM014_WMEMO  # noqa: E402
from lean_vm.step_driver import StepDriver               # noqa: E402
from lean_vm.ref_vm import RefVM, VMError                # noqa: E402

T_DEFCACHE = 41
T_WHNFCACHE = 43


def _cache_counts(stream):
    n41 = sum(1 for tok in stream if tok[0] == T_DEFCACHE)
    n43 = sum(1 for tok in stream if tok[0] == T_WHNFCACHE)
    return n41, n43


def _emit(case, got, steps, stream, extra=""):
    n41, n43 = _cache_counts(stream)
    print(f"RESULT case={case} cache={int(VM014_CACHE)} wmemo={int(VM014_WMEMO)} "
          f"got={got!r} steps={steps} defcache={n41} whnfcache={n43} {extra}",
          flush=True)


def run_string(cid):
    """string suite B group case by id: graph run only (no oracle)."""
    import tests.test_string_graph_vs_lean as w5
    consts, ctors, meta, ordered = w5.build_env()
    graph, outputs = build_step_graph()
    warm = w5._warm_prefix(consts, ctors, meta, graph, outputs)
    for (case_id, kind, sa, sb, ea, eb) in w5.CASES:
        if case_id != cid:
            continue
        enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
        drv = StepDriver(enc.b, graph, outputs)
        env_len, warm_vals, warm_hist = warm
        drv._eval.vals = list(warm_vals)
        drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
        t0 = time.perf_counter()
        try:
            if kind == "DEFEQ":
                v = drv.run_defeq(enc.encode_term(ea), 0,
                                  enc.encode_term(eb), 0,
                                  max_steps=w5.GRAPH_MAX_STEPS)[0]
                got = bool(v)
            else:
                raise SystemExit(f"kind {kind} not wired")
        except Exception as ex:                            # noqa: BLE001
            got = f"{type(ex).__name__}: {ex}"
        _emit(cid, got, drv.steps, enc.b.stream,
              extra=f"t={time.perf_counter()-t0:.1f}s")
        return
    raise SystemExit(f"case {cid} not in CASES")


def _toy_env():
    from tests.test_olean_export import TARGET_DEFS, ROOTS
    from reference.olean_export import import_env
    return import_env(TARGET_DEFS, ROOTS) + (TARGET_DEFS, ROOTS)


def run_check(cid):
    """check_e2e layer B: graph run_check of one decl vs RefVM in-process."""
    from tests.test_check_e2e import CASE
    consts, ctors, structs, _td, _rt = _toy_env()
    t_src, v_src, te, ve = CASE[cid]
    enc_r = Encoder(consts, is_ctor=ctors)
    vm = RefVM(enc_r.b, structures=structs)
    try:
        vm.check([(enc_r.encode_term(te), enc_r.encode_term(ve))])
        ref = True
    except VMError:
        ref = False
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    drv = StepDriver(enc.b, graph, outputs)
    t0 = time.perf_counter()
    try:
        drv.run_check([(enc.encode_term(te), enc.encode_term(ve))])
        got = True
    except VMError as ex:
        got = f"reject({ex})"[:120]
    except Exception as ex:                                # noqa: BLE001
        got = f"{type(ex).__name__}: {ex}"
    _emit(cid, got, drv.steps, enc.b.stream,
          extra=f"refvm={ref} t={time.perf_counter()-t0:.1f}s")


def run_base(cid):
    """mutation_reject part A BASE: graph accept/reject of one decl."""
    from tests.test_mutation_reject import BASE
    consts, ctors, structs, _td, _rt = _toy_env()
    _t, _v, te, ve = BASE[cid]
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    drv = StepDriver(enc.b, graph, outputs)
    t0 = time.perf_counter()
    try:
        drv.run_check([(enc.encode_term(te), enc.encode_term(ve))])
        got = True
    except VMError as ex:
        got = f"reject({ex})"[:120]
    except Exception as ex:                                # noqa: BLE001
        got = f"{type(ex).__name__}: {ex}"
    _emit(cid, got, drv.steps, enc.b.stream,
          extra=f"t={time.perf_counter()-t0:.1f}s")


def run_localize(cid):
    """mutation_reject part B: graph reject + localize kind/offending read."""
    from tests.test_mutation_reject import MUTANTS
    from lean_vm.localize import localize
    consts, ctors, structs, _td, _rt = _toy_env()
    mid, base, _ts, _vs, te, ve, _ek, _eo = next(
        m for m in MUTANTS if m[0] == cid)
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    drv = StepDriver(enc.b, graph, outputs)
    tr, vr = enc.encode_term(te), enc.encode_term(ve)
    focus = None
    t0 = time.perf_counter()
    try:
        drv.run_check([(tr, vr)])
        _emit(cid, "ACCEPTED(mutant!)", drv.steps, enc.b.stream)
        return
    except VMError as ex:
        focus = ex.focus
        got0 = f"reject({ex})"[:120]
    except Exception as ex:                                # noqa: BLE001
        _emit(cid, f"{type(ex).__name__}: {ex}", drv.steps, enc.b.stream)
        return
    graph2, outputs2 = build_step_graph()
    enc2 = Encoder(consts, is_ctor=ctors)
    d2 = StepDriver(enc2.b, graph2, outputs2)
    tr2, vr2 = enc2.encode_term(te), enc2.encode_term(ve)
    try:
        ipos, ienv = d2.run_infer(vr2)
        inferred = (ipos, ienv)
        focus2 = -1
    except VMError as ex:
        inferred = None
        focus2 = ex.focus
    loc = localize(enc2.b, tr2, vr2, inferred=inferred, infer_focus=focus2)
    _emit(cid, f"{got0} loc={{'kind': {loc['kind']}, "
          f"'off': {loc.get('offending_expr')!r}}}",
          drv.steps + d2.steps, enc2.b.stream,
          extra=f"t={time.perf_counter()-t0:.1f}s")


def run_infer_case(cid):
    """olean_export layer B INFER: graph run_infer decoded closure."""
    import tests.test_olean_export as oe
    from reference.olean_export import import_env
    consts, ctors, structs = import_env(oe.TARGET_DEFS, oe.ROOTS)
    our = next(e for (c, _s, e) in oe.INFER_CASES if c == cid)
    enc_r = Encoder(consts, is_ctor=ctors)
    vm = RefVM(enc_r.b, structures=structs)
    tp, tenv = vm.infer(enc_r.encode_term(our), 0)
    ref = oe.strip_mdata(decode_closure(enc_r.b, tp, tenv))
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    drv = StepDriver(enc.b, graph, outputs)
    t0 = time.perf_counter()
    try:
        gp, genv = drv.run_infer(enc.encode_term(our))
        got = str(oe.strip_mdata(decode_closure(enc.b, gp, genv)))
    except Exception as ex:                                # noqa: BLE001
        got = f"{type(ex).__name__}: {ex}"
    _emit(cid, got, drv.steps, enc.b.stream,
          extra=f"ref={ref!r} t={time.perf_counter()-t0:.1f}s")


CASES = {
    "deq_oflist_true": lambda: run_string("deq_oflist_true"),
    "deq_proj_vs_oflist_true": lambda: run_string("deq_proj_vs_oflist_true"),
    "chk_inc_fn": lambda: run_check("chk_inc_fn"),
    "b_inc": lambda: run_base("b_inc"),
    "m_dbl_bool": lambda: run_localize("m_dbl_bool"),
    "m_pairapp_p2": lambda: run_localize("m_pairapp_p2"),
    "inf_hof_app": lambda: run_infer_case("inf_hof_app"),
}


def main() -> int:
    ids = sys.argv[1:] or list(CASES)
    for cid in ids:
        try:
            CASES[cid]()
        except Exception:                                   # noqa: BLE001
            traceback.print_exc()
            print(f"RESULT case={cid} HARNESS-ERROR", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
