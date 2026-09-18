#!/usr/bin/env python3
"""H1/H2/H3 verification: sparse-native .sbin v2 through engine/vm_run.

Compares engine output (argmax default and VM_SOFTMAX path) against RefVM
on the full toy CORPUS, and checks known literal results.
Not part of any compiled graph — verification only.
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, "/home/xkq/Lean4-Transformer-Vm-OSS")

from expr.tokens import Encoder, decode_closure
from expr.model import (App, Const, Lam, LitNat, MData, Pi, Let, BVar,
                        BI_DEFAULT)
from lean_vm.ref_vm import RefVM
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_STRUCTS, CORPUS

ROOT = "/home/xkq/Lean4-Transformer-Vm-OSS"
ENGINE = os.environ.get("VM_ENGINE",
                        os.path.join(ROOT, "engine", "vm_run"))
# The artifact under test. Default is the repo-current sparse build; override
# with SBIN= to pin a snapshot (parallel agents may recompile the repo one).
SBIN = os.environ.get("SBIN",
                      os.path.join(ROOT, "model", "step_vm_new_sparse.sbin"))


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


def run_engine(stream, term_pos, softmax=False, max_steps=3000):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write("%d\n" % len(stream))
    for t in stream:
        t7 = tuple(t) + (0,) * (7 - len(t))
        f.write(" ".join(str(int(x)) for x in t7) + "\n")
    f.close()
    env = dict(os.environ)
    env.pop("VM_SOFTMAX", None)
    if softmax:
        env["VM_SOFTMAX"] = "1"
    t0 = time.perf_counter()
    try:
        p = subprocess.run([ENGINE, SBIN, f.name, str(term_pos), str(max_steps)],
                           capture_output=True, text=True, env=env, timeout=1800)
    except subprocess.TimeoutExpired:
        # engine-side hang (known symptom: the pow off-by-one burns all
        # max_steps and its step cost grows with the stream); report it as a
        # per-case failure, never kill the whole harness.
        os.unlink(f.name)
        return None, None, None, time.perf_counter() - t0, "TIMEOUT 1800s"
    dt = time.perf_counter() - t0
    os.unlink(f.name)
    if p.returncode != 0:
        return None, None, None, dt, p.stderr[-300:]
    lines = p.stdout.strip().splitlines()
    n = int(lines[0])
    st = [tuple(int(x) for x in ln.split()) for ln in lines[1:1 + n]]
    verdict = lines[1 + n].split()
    return st, verdict, p.stdout, dt, None


def main():
    # Daily-regression mode: `--skip-cases pow` excludes cases that are known
    # FAILING *and non-halting* under the engine F-channel off-by-one (card
    # 006): the skip is bound to the named verdict exemption, not to taste —
    # the case runs at milestone exit (or without the flag). Skipped cases
    # are reported, never silently dropped.
    skip = set()
    if "--skip-cases" in sys.argv:
        skip = {c for c in
                sys.argv[sys.argv.index("--skip-cases") + 1].split(",") if c}
    known = {
        "add_lits": LitNat(8),
        "delta_two": LitNat(2),
        "delta_beta": LitNat(42),
        "succ_zero": App(Const("Nat.succ"), Const("Nat.zero")),
    }
    n_ok = n_stream_same = n_known_ok = n_skip = 0
    fails = []
    total_argmax = total_softmax = 0.0
    skipped = []
    for cid, src, term in CORPUS:
        if cid in skip:
            n_skip += 1
            skipped.append(cid)
            print(f"  [SKIP] {cid} — named exemption (engine F-channel "
                  f"off-by-one, card 006)", flush=True)
            continue
        # reference
        re = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        rv = RefVM(re.b, nat_enabled=True, structures=TOY_STRUCTS)
        try:
            rp, renv = rv.whnf(re.encode_term(term), 0)
            expected = strip_mdata(decode_closure(re.b, rp, renv))
        except Exception as e:  # noqa
            fails.append((cid, f"ref error {type(e).__name__}: {e}"))
            print(f"  [REFERR] {cid}: {e}", flush=True)
            continue
        enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        tp = enc.encode_term(term)
        pre = list(enc.b.stream)

        st_a, ver_a, _, dt_a, err_a = run_engine(pre, tp, softmax=False)
        st_s, ver_s, _, dt_s, err_s = run_engine(pre, tp, softmax=True)
        total_argmax += dt_a or 0
        total_softmax += dt_s or 0
        if err_a:
            fails.append((cid, f"engine argmax: {err_a}"))
            print(f"  [FAIL] {cid} argmax {err_a}", flush=True)
            continue
        if err_s:
            fails.append((cid, f"engine softmax: {err_s}"))
            print(f"  [FAIL] {cid} softmax {err_s}", flush=True)
            continue

        same = (st_a == st_s)
        if same:
            n_stream_same += 1

        enc.b.stream = list(st_a)
        if ver_a[0] == "DONE":
            got = strip_mdata(decode_closure(enc.b, int(ver_a[1]),
                                             int(ver_a[2])))
        else:
            got = "NOT_DONE"
        ok = (ver_a[0] == "DONE") and (got == expected)
        if ok:
            n_ok += 1
        else:
            fails.append((cid, f"got={got!r} exp={expected!r} (verdict {ver_a})"))
        known_str = ""
        if cid in known:
            kok = (got == known[cid])
            n_known_ok += kok
            known_str = f" known={'OK' if kok else 'BAD exp=%r' % known[cid]}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid:18s} {ver_a[0]:8s} "
              f"steps={ver_a[-1]:>5s} argmax={dt_a:6.2f}s softmax={dt_s:6.2f}s "
              f"stream_same={same}{known_str}", flush=True)

    n = len(CORPUS)
    ran = n - n_skip
    print(f"\n=== H3 engine vs RefVM: {n_ok}/{ran} verdicts correct"
          + (f" ({n_skip} skipped: {','.join(skipped)})" if n_skip else "")
          + " ===")
    print(f"    argmax vs softmax streams identical: {n_stream_same}/{ran}")
    print(f"    known-value checks: {n_known_ok}/{len(known)}")
    print(f"    total engine wall time: argmax {total_argmax:.1f}s, "
          f"softmax {total_softmax:.1f}s")
    for cid, msg in fails:
        print(f"  FAIL {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
