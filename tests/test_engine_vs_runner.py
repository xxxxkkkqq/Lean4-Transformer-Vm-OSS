#!/usr/bin/env python3
"""Phase 4 test: C++ engine vs Python WeightRunner on the full corpus.

Both sides start from the same initial token stream (before init_state).
The C++ binary appends the initial STATE itself and runs the micro-step
loop; the Python side re-runs WeightRunner. We compare:
  - the full final token streams, token by token (strongest possible
    check: the stream is the entire execution trace), and
  - the DONE/NOT_DONE verdict + result closure position.

CPU discipline: 8 threads max, no CUDA.

Run: python3 tests/test_engine_vs_runner.py [--quick]
(--quick skips big_mul / pow, the multi-minute eval-replay cases; the C++
side is fast but the Python side still replays.)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "8")
os.environ.setdefault("MKL_NUM_THREADS", "8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch

torch.set_num_threads(8)

from expr.tokens import Encoder
from model.runner import WeightRunner
from reference.toy_env import TOY_CONSTS, TOY_CTORS, CORPUS

SLOW = {"big_mul", "pow"}
ENGINE = ROOT / "engine" / "vm_run"
WEIGHTS = ROOT / "model" / "step_vm.bin"


def build_engine() -> None:
    if ENGINE.exists() and ENGINE.stat().st_mtime >= (
            ROOT / "engine" / "vm.cpp").stat().st_mtime:
        return
    import subprocess
    subprocess.check_call([
        "g++", "-std=c++17", "-O2", "-o", str(ENGINE),
        str(ROOT / "engine" / "vm.cpp"),
    ])
    print("built engine/vm_run", flush=True)


def dump_stream(path: Path, stream) -> None:
    with open(path, "w") as f:
        f.write(f"{len(stream)}\n")
        for t in stream:
            t7 = tuple(t) + (0,) * (7 - len(t))
            f.write(" ".join(str(int(v)) for v in t7) + "\n")


def run_case(cid, term, model, meta, tmp: Path) -> tuple[bool, str]:
    enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    term_pos = enc.encode_term(term)
    pre_init = list(enc.b.stream)  # before init_state

    sfile = tmp / f"{cid}.txt"
    dump_stream(sfile, pre_init)
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(ENGINE), str(WEIGHTS), str(sfile), str(term_pos), "2000"],
        capture_output=True, text=True, timeout=600)
    t_cpp = time.perf_counter() - t0
    if proc.returncode != 0:
        return False, f"engine exit {proc.returncode}: {proc.stderr[-300:]}"

    lines = proc.stdout.strip().splitlines()
    n_out = int(lines[0])
    cpp_stream = [tuple(int(x) for x in ln.split()) for ln in lines[1:1 + n_out]]
    verdict = lines[1 + n_out].split()
    steps = int(verdict[-1])

    # Python side on the same initial stream (engine ran in a subprocess on
    # a dumped copy, so enc.b.stream is untouched)
    runner = WeightRunner(enc.b, model, meta)
    t0 = time.perf_counter()
    try:
        wpos, wenv = runner.run(term_pos, max_steps=2000)
    except TimeoutError:
        return False, "python runner timed out"
    t_py = time.perf_counter() - t0

    py_stream = [tuple(int(v) for v in t) for t in enc.b.stream]
    if py_stream != cpp_stream:
        for i, (a, b) in enumerate(zip(py_stream, cpp_stream)):
            if a != b:
                return False, (f"stream diverges at {i}: py={a} cpp={b} "
                               f"(len py={len(py_stream)} cpp={len(cpp_stream)})")
        return False, f"stream length differs: py={len(py_stream)} cpp={len(cpp_stream)}"
    if verdict[0] != "DONE":
        return False, f"engine not done: {verdict}"
    if (int(verdict[1]), int(verdict[2])) != (wpos, wenv):
        return False, (f"closure mismatch: cpp=({verdict[1]},{verdict[2]}) "
                       f"py=({wpos},{wenv})")
    return True, f"{steps} steps, cpp {t_cpp:.1f}s / py {t_py:.1f}s"


def main() -> int:
    quick = "--quick" in sys.argv
    build_engine()
    ckpt = torch.load(ROOT / "model" / "step_vm.pt", map_location="cpu",
                      weights_only=False)
    model, meta = ckpt["model"], ckpt["meta"]
    tmp = ROOT / "tests" / "_engine_tmp"
    tmp.mkdir(exist_ok=True)
    n_pass, fails = 0, []
    for cid, src, term in CORPUS:
        if quick and cid in SLOW:
            print(f"  [SKIP] {cid} (--quick)", flush=True)
            n_pass += 1
            continue
        try:
            ok, info = run_case(cid, term, model, meta, tmp)
        except Exception as e:
            ok, info = False, f"{type(e).__name__}: {e}"
        if ok:
            n_pass += 1
            print(f"  [PASS] {cid}: {info}", flush=True)
        else:
            fails.append(cid)
            print(f"  [FAIL] {cid}: {info}", flush=True)
    total = len(CORPUS)
    print(f"\n=== C++ engine vs Python runner: {n_pass}/{total} ===",
          flush=True)
    for cid in fails:
        print(f"  FAIL {cid}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
