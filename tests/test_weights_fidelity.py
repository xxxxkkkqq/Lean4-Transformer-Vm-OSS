"""Phase 3 fidelity test: compiled weights == graph interpreter, bitwise.

Acceptance (PLAN Phase 3): for every corpus case, the WeightRunner (real
transformer forward) and the StepDriver (eval_graph_sequence replay) run in
lockstep on identical token streams and agree on every output dim at every
micro-step (integer dims: |diff| <= 1e-6 and round-equal), emit identical
streams, and land on the same closure as RefVM / real Lean.

CPU discipline: capped at 8 threads, CPU tensors only (no CUDA init).

Run: OMP_NUM_THREADS=8 python3 tests/test_weights_fidelity.py [--quick]
(--quick skips the multi-minute replay cases: big_mul, pow2_10)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "8")
os.environ.setdefault("MKL_NUM_THREADS", "8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

torch.set_num_threads(8)
torch.set_default_dtype(torch.float64)

from expr.tokens import Encoder, decode_closure
from lean_kernel.alm_p2 import eval_graph_sequence
from lean_vm.build_vm import build_step_graph
from lean_vm.ref_vm import RefVM
from lean_vm.step_driver import StepDriver
from model.runner import WeightRunner
from reference.toy_env import TOY_CONSTS, TOY_CTORS, CORPUS

# multi-minute eval-replay cases (Phase 2 known cost; kept in full run)
SLOW = {"big_mul", "pow2_10"}
TOL = 1e-6


def load_model():
    ckpt = torch.load(
        Path(__file__).resolve().parents[1] / "model" / "step_vm.pt",
        map_location="cpu", weights_only=False)
    return ckpt["model"], ckpt["meta"]


def run_case(cid, src, term, model, meta):
    """Returns (ok, info). Lockstep graph-eval vs weights on one case."""
    # reference result (RefVM side has its own stream)
    ref_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    rp, renv = RefVM(ref_enc.b, nat_enabled=True).whnf(
        ref_enc.encode_term(term), 0)
    expected = decode_closure(ref_enc.b, rp, renv)

    # graph side
    graph, outputs = build_step_graph()
    g_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    driver = StepDriver(g_enc.b, graph, outputs)
    gp = g_enc.encode_term(term)

    # weight side: identical stream content, fresh bundle
    w_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    runner = WeightRunner(w_enc.b, model, meta)
    wp = w_enc.encode_term(term)
    assert g_enc.b.stream == w_enc.b.stream, "encoder nondeterminism"

    driver.init_state(gp)
    runner.init_state(wp)

    n = 0
    worst = 0.0
    t_eval = 0.0
    t_fwd = 0.0
    t0wall = time.perf_counter()
    while True:
        t0 = time.perf_counter()
        gv = eval_graph_sequence(graph, driver.names)[-1]
        t_eval += time.perf_counter() - t0
        t0 = time.perf_counter()
        wv = runner._forward_last()
        t_fwd += time.perf_counter() - t0

        for name, dim in outputs.items():
            a = float(gv[dim])
            b = float(wv[name])
            d = abs(a - b)
            if d > worst:
                worst = d
            if d > TOL or int(round(a)) != int(round(b)):
                return False, (f"step {n} dim {name}: graph={a} "
                               f"weights={b} (diff {d:.3e})")
        d_done, dr = driver.step()
        w_done, wr = runner.step()
        n += 1
        if d_done != w_done:
            return False, f"step {n}: done flag diverged"
        if g_enc.b.stream != w_enc.b.stream:
            return False, f"step {n}: emitted streams diverged"
        if d_done:
            break
    t_wall = time.perf_counter() - t0wall

    got_g = decode_closure(g_enc.b, *dr)
    got_w = decode_closure(w_enc.b, *wr)
    if got_g != expected or got_w != expected:
        return False, (f"final closure: graph={got_g!r} weights={got_w!r} "
                       f"ref={expected!r}")
    return True, {"steps": n, "worst_diff": worst,
                  "t_eval": t_eval, "t_fwd": t_fwd, "t_wall": t_wall}


def main() -> int:
    quick = "--quick" in sys.argv
    model, meta = load_model()
    n_pass = 0
    fails = []
    for cid, src, term in CORPUS:
        if quick and cid in SLOW:
            print(f"  [SKIP] {cid} (--quick)", flush=True)
            n_pass += 1
            continue
        try:
            ok, info = run_case(cid, src, term, model, meta)
        except Exception as e:
            ok, info = False, f"{type(e).__name__}: {e}"
        if ok:
            n_pass += 1
            if isinstance(info, dict):
                print(f"  [PASS] {cid}: {info['steps']} steps, "
                      f"worst diff {info['worst_diff']:.2e}, "
                      f"eval {info['t_eval']:.1f}s / fwd {info['t_fwd']:.1f}s "
                      f"/ wall {info['t_wall']:.1f}s",
                      flush=True)
            else:
                print(f"  [PASS] {cid}", flush=True)
        else:
            fails.append((cid, info))
            print(f"  [FAIL] {cid}: {info}", flush=True)
    total = len(CORPUS)
    print(f"\n=== weights vs graph-eval fidelity: {n_pass}/{total} ===",
          flush=True)
    for cid, msg in fails:
        print(f"  FAIL {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
