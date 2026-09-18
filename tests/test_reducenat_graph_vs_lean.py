"""WP6 (reduce_nat completion + size guards F1-F4/F9): the ALM step graph vs the
real Lean 4.33.1 binary (the acceptance oracle).

Authority (read-only): /home/xkq/lean4/src/kernel/type_checker.cpp —
  infer_lit K:315-321; get_count_arg K:308-313; reduce_bin_nat_op (add/sub/mul,
  check-after-compute) K:644-658; reduce_pow K:660-675 (cap FIRST, then
  base>1 and k!=0 and size(base) > MAX/k); reduce_shiftLeft K:677-690;
  succ K:706-713; gcd/land/lor/xor/shiftRight/pred/beq/ble carry NO size check.
Graph phases: X71-X75 pow guards, X76 result-digit strip scan (see
docs/VM_SPEC.md §WP6-G and docs/handoffs/002-C-wp6.md "尺寸守卫").

Harness rules learned from the real binary (probe evidence in
$HOME/logs/006C3 + docstrings of lean_ref):
  * #ORACLE (Meta.whnf) reduces Nat ops through the UNCHECKED elaborator
    interpreter — it can never surface the kernel guards, so it is only used
    here for ACCEPT values (small, in-limit results, where all three of
    elab-reduce, kernel-reduce and the graph agree).
  * Kernel guards are observable at declaration check time:
    - oversized literal OPERANDS: `example : Nat := Nat.add 10^20 1` throws
      "(kernel) the kernel refused a `Nat` numeral" during arg inference
      (mirrors K:315-321 on the operand — the machine's `rej_o`/`rej_lit`).
    - oversized RESULT of a computed op: the op must appear UN-reduced in a
      kernel-checked type, e.g.
      `theorem t : decide (Nat.mul 10^10 10^15 = 1) = false := by decide`
      — the declaration type stores the written term, the kernel whnfs the
      decEq major and reduce_bin_nat_op/pow/shiftLeft run WITH their checks
      (verified live: "refused a `Nat` numeral" / "refused to evaluate
      `Nat.pow` because the result would exceed the maximum numeral size").
    - exponent/shift beyond 2^32 (class "32-bit unsigned", K:308-313): the
      elaborator never lets the kernel message out — it hits
      exponentiation.threshold/recursion limits or the runtime's shiftl panic
      first.  Real Lean still FAILS the declaration (rc != 0), which is the
      observable accept/reject verdict; the machine's reject (VMError code 1,
      same kernel-exception channel as every other WP) is the K-source
      behaviour.  Marked class "cap-artifact" below.

Band (machine-accept, kernel-reject): results whose limb count strictly
exceeds the digit lower bound L(D) (limbs = L(D)+1 with few leading digits),
i.e. r in [2^64, 10^20) at MAX=8.  By design the graph's guards are sound
(machine-reject ⊆ kernel-reject, never the converse — iron rule: no false
rejects); band values need the exact 10^19-quantized limb counter, which is
unrealizable in-graph at the default MAX.  Band cases are EXCLUDED from this
corpus; see docs/VM_SPEC.md §WP6-G and the ADR.

Every expectation comes from the live oracle (values from its WHNF payloads,
verdicts from its exit status and message class).  Nothing is preseeded.

Run: setsid nohup env OMP_NUM_THREADS=3 taskset -c 14-19 python3 -u \
       tests/test_reducenat_graph_vs_lean.py \
       > $HOME/logs/006C3/test_w6.log 2>&1 < /dev/null &
Iteration subset: WP6_ONLY=1 runs only section B (baked MAX=8, cheap).
"""
from __future__ import annotations

import gc
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import App, Const, LitNat
from expr.tokens import Encoder, decode_closure
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from lean_vm.ref_vm import VMError
from reference import lean_ref
from reference.toy_env import TOY_CONSTS, TOY_CTORS, _pi_nat_nat_nat

MAX_STEPS = 6000

OPS = [("Nat.gcd", _pi_nat_nat_nat(), None),
       ("Nat.land", _pi_nat_nat_nat(), None),
       ("Nat.lor", _pi_nat_nat_nat(), None),
       ("Nat.xor", _pi_nat_nat_nat(), None),
       ("Nat.shiftLeft", _pi_nat_nat_nat(), None),
       ("Nat.shiftRight", _pi_nat_nat_nat(), None)]
CONSTS = list(TOY_CONSTS) + OPS


def _A(f, *xs):
    for x in xs:
        f = App(f, x)
    return f


def _term(op, *args):
    return _A(Const(op), *[LitNat(a) for a in args])


# ── section A: default MAX = 128 MB (LEAN_NAT_MAX_SIZE unset, both sides) ───
# accept: (id, src, term)   — value compared against the oracle WHNF payload
ACC_A = [
    ("add", "Nat.add 20 30", _term("Nat.add", 20, 30)),
    ("sub_hi", "Nat.sub 30 20", _term("Nat.sub", 30, 20)),
    ("sub_lo", "Nat.sub 20 30", _term("Nat.sub", 20, 30)),
    # long-operand borrow chain regression (done_bor = mx+1 fix, K:649-651):
    ("sub_borrow", "Nat.sub 5 10000000000000000001",
     _term("Nat.sub", 5, 10**19 + 1)),
    ("mul", "Nat.mul 12 10", _term("Nat.mul", 12, 10)),
    # in-limit 26-digit product: the X76 strip scan must ACCEPT (kernel too):
    ("mul_big", "Nat.mul 10000000000 1000000000000000",
     _term("Nat.mul", 10**10, 10**15)),
    ("succ", "Nat.succ 41", _term("Nat.succ", 41)),
    ("pred", "Nat.pred 41", _term("Nat.pred", 41)),
    ("pred0", "Nat.pred 0", _term("Nat.pred", 0)),
    ("pow10", "Nat.pow 2 10", _term("Nat.pow", 2, 10)),
    # pow base^0 regression (em_litdig2 fix; oracle pow_b0 probe: whnf = 1):
    ("pow0", "Nat.pow 2 0", _term("Nat.pow", 2, 0)),
    ("pow_zbase", "Nat.pow 0 5", _term("Nat.pow", 0, 5)),
    ("pow1", "Nat.pow 1 20", _term("Nat.pow", 1, 20)),   # base<=1: no guard
    ("pow3", "Nat.pow 3 5", _term("Nat.pow", 3, 5)),
    ("gcd", "Nat.gcd 12 10", _term("Nat.gcd", 12, 10)),
    ("gcd0", "Nat.gcd 0 7", _term("Nat.gcd", 0, 7)),
    ("gcd00", "Nat.gcd 0 0", _term("Nat.gcd", 0, 0)),
    ("land", "Nat.land 12 10", _term("Nat.land", 12, 10)),
    ("lor", "Nat.lor 12 10", _term("Nat.lor", 12, 10)),
    ("xor", "Nat.xor 12 10", _term("Nat.xor", 12, 10)),
    ("xor0", "Nat.xor 7 7", _term("Nat.xor", 7, 7)),
    ("shl", "Nat.shiftLeft 5 2", _term("Nat.shiftLeft", 5, 2)),
    ("shl30", "Nat.shiftLeft 7 30", _term("Nat.shiftLeft", 7, 30)),
    ("shl0", "Nat.shiftLeft 0 9", _term("Nat.shiftLeft", 0, 9)),  # v=0: K:685
    ("shr", "Nat.shiftRight 12 2", _term("Nat.shiftRight", 12, 2)),
    ("shrbig", "Nat.shiftRight 12 100", _term("Nat.shiftRight", 12, 100)),
    ("shr0", "Nat.shiftRight 5 0", _term("Nat.shiftRight", 5, 0)),
]
# reject: (id, kernel_src, term, class) with class in
#   "numeral"  -> expect "(kernel) the kernel refused a `Nat` numeral"
#   "powsize"  -> expect "refused to evaluate `Nat.pow`"
#   "cap-artifact" -> expect rc != 0 with any message (see docstring)
REJ_A = [
    ("r_pow_cap",
     "theorem t : decide (Nat.pow 2 4294967296 = 1) = false := by decide",
     _term("Nat.pow", 2, 4294967296), "cap-artifact"),
    ("r_pow_size",
     "theorem t : decide (Nat.pow 2 100000000 = 1) = false := by decide",
     _term("Nat.pow", 2, 100000000), "cap-artifact"),
    ("r_shl_cap",
     "theorem t : decide (Nat.shiftLeft 5 4294967296 = 0) = false := by decide",
     _term("Nat.shiftLeft", 5, 4294967296), "cap-artifact"),
    # kernel-clean at default MAX: check fires before any allocation (K:687):
    ("r_shl_size",
     "theorem t : decide (Nat.shiftLeft 5 2000000000 = 0) = false := by decide",
     _term("Nat.shiftLeft", 5, 2000000000), "numeral"),
]

# ── section B: LEAN_NAT_MAX_SIZE=8 baked graph + same env for lean ──────────
ACC_B = [
    ("add", "Nat.add 200 30", _term("Nat.add", 200, 30)),
    # 1-limb boundary: 3e18 < 2^64, kernel accepts (8 bytes <= MAX):
    ("mul_lim", "Nat.mul 1000000000000000000 3",
     _term("Nat.mul", 10**18, 3)),
    ("sub_borrow", "Nat.sub 5 10000000000000000001",
     _term("Nat.sub", 5, 10**19 + 1)),
    ("pow_tie", "Nat.pow 2 1", _term("Nat.pow", 2, 1)),   # 8*1*1 == MAX: tie
    ("pow0", "Nat.pow 2 0", _term("Nat.pow", 2, 0)),      # k=0 skips checks
    ("succ_lim", "Nat.succ 10000000000000000002",
     _term("Nat.succ", 10**19 + 2)),
    ("pred", "Nat.pred 10000000000000000001", _term("Nat.pred", 10**19 + 1)),
    ("gcd", "Nat.gcd 12 10", _term("Nat.gcd", 12, 10)),
    ("shr", "Nat.shiftRight 12 2", _term("Nat.shiftRight", 12, 2)),
    ("land", "Nat.land 255 15", _term("Nat.land", 255, 15)),
]
REJ_B = [
    # operand-literal guards (machine rej_o at the d23/dn1 step, 2-4 steps):
    ("r_add_op", "example : Nat := Nat.add 100000000000000000000 1",
     _term("Nat.add", 10**20, 1), "numeral"),
    ("r_succ_op", "example : Nat := Nat.succ 100000000000000000000",
     _term("Nat.succ", 10**20), "numeral"),
    # X76 strip scan: 26-digit product from two 1-limb operands:
    ("r_mul_res",
     "theorem t : decide (Nat.mul 10000000000 1000000000000000 = 1) = false "
     ":= by decide",
     _term("Nat.mul", 10**10, 10**15), "numeral"),
    # pow size guards, X73-X75 (8 > MAX//k with MAX=8):
    ("r_pow_res",
     "theorem t : decide (Nat.pow 2 2 = 4) = true := by decide",
     _term("Nat.pow", 2, 2), "powsize"),
    ("r_pow_cap_tie",
     "theorem t : decide (Nat.pow 2 4294967295 = 1) = false := by decide",
     _term("Nat.pow", 2, 4294967295), "cap-artifact"),
    # shiftLeft size guard, X64-X65 (size(5)+10/8+1 = 10 > 8 = MAX):
    ("r_shl_res",
     "theorem t : decide (Nat.shiftLeft 5 10 = 0) = false := by decide",
     _term("Nat.shiftLeft", 5, 10), "numeral"),
]

CLASS_SUBSTR = {
    "numeral": "refused a `Nat` numeral",
    "powsize": "refused to evaluate `Nat.pow`",
    "cap-artifact": None,   # any rc != 0; kernel message not observable (doc)
}


def oracle_accept(srcs):
    """run_oracle_mixed returns (kind, json dict); convert WHNF payloads to
    exprs (json_to_expr maps k=10 with "nat" to LitNat)."""
    entries = [("WHNF", s, None) for s in srcs]
    return [(k, lean_ref.json_to_expr(p)) for k, p in
            lean_ref.run_oracle_mixed("", entries)]


def oracle_reject(kernel_src, tag):
    path = Path(f"/tmp/vm_reducenat_rej_{tag}.lean")
    path.write_text(kernel_src + "\n")
    r = subprocess.run([str(lean_ref.LEAN), str(path)],
                       capture_output=True, text=True, timeout=600)
    msg = (r.stdout + "\n" + r.stderr).strip()
    return r.returncode, msg[:400]


def machine(graph, outputs, term):
    """Returns ('val', int) on accept, ('rej', code) on VMError."""
    enc = Encoder(CONSTS, is_ctor=TOY_CTORS)
    drv = StepDriver(enc.b, graph, outputs)
    try:
        p, e = drv.run(enc.encode_term(term), max_steps=MAX_STEPS)
        r = decode_closure(enc.b, p, e)
        if not isinstance(r, LitNat):
            return ("bad", repr(r))
        return ("val", r.value)
    except VMError as ex:
        return ("rej", ex.code)


def run_section(tag, graph, outputs, acc, rej):
    fails = []
    srcs = [s for _, s, _ in acc]
    t0 = time.time()
    try:
        results = oracle_accept(srcs)
    except RuntimeError as ex:
        fails.append(f"[{tag}] oracle accept batch died: {ex}")
        results = []
    print(f"[{tag}] oracle accept batch: {len(results)}/{len(acc)} "
          f"({time.time()-t0:.1f}s)")
    for (name, src, term), (kind, payload) in zip(acc, results):
        want = payload.value if isinstance(payload, LitNat) else None
        if want is None:
            fails.append(f"[{tag}/{name}] oracle whnf not a nat literal: {payload!r}")
            continue
        got = machine(graph, outputs, term)
        ok = got == ("val", want)
        print(f"[{tag}] {name:12s} -> {got[0]} {str(got[1])[:24]} "
              f"want {want}  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            fails.append(f"[{tag}/{name}] machine {got} vs oracle {want}")
    for name, ksrc, term, cls in rej:
        rc, msg = oracle_reject(ksrc, f"{tag}_{name}")
        sub = CLASS_SUBSTR[cls]
        orc_ok = rc != 0 and (sub is None or sub in msg)
        got = machine(graph, outputs, term)
        mach_ok = got == ("rej", 1)
        ok = orc_ok and mach_ok
        print(f"[{tag}] {name:14s} oracle rc={rc}{'/'+cls if ok else ' '+msg[:60]} "
              f"machine {got[0]}({got[1]})  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            fails.append(f"[{tag}/{name}] oracle rc={rc} msg={msg[:120]} "
                         f"machine={got}")
    return fails


def main():
    only_b = os.environ.get("WP6_ONLY") == "1"
    fails = []
    g = outs = None
    if not only_b:
        os.environ.pop("LEAN_NAT_MAX_SIZE", None)   # default 128 MB both sides
        print("building default-MAX graph...")
        g, outs = build_step_graph()
        fails += run_section("A", g, outs, ACC_A, REJ_A)
        del g, outs
        gc.collect()

    os.environ["LEAN_NAT_MAX_SIZE"] = "8"           # bakes guard thresholds
    try:
        print("building MAX=8 graph...")
        g, outs = build_step_graph()
        fails += run_section("B", g, outs, ACC_B, REJ_B)
        del g, outs
        gc.collect()
    finally:
        os.environ.pop("LEAN_NAT_MAX_SIZE", None)

    for msg in fails:
        print(f"  [FAIL] {msg}")
    n_a = 0 if only_b else len(ACC_A) + len(REJ_A)
    n_b = len(ACC_B) + len(REJ_B)
    print(f"\n=== WP6 reduce_nat: A={n_a} cases"
          f"{' (skipped)' if only_b else ''}, B={n_b} cases, "
          f"{len(fails)} failures === {'OK' if not fails else 'FAIL'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
