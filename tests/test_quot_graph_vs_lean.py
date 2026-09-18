"""WP4 (quot): the C-group Quot reduction in the ALM step graph vs the real
Lean 4.33.1 binary (the acceptance oracle).

Spec: docs/KERNEL_COVERAGE.md section 4 (WP4) and the C-group table rows C1-C5
(lines 87-93).  Authority (read-only): /home/xkq/lean4/src/kernel/quot.h,
quot.cpp, inductive.h, type_checker.cpp (4.35 master).

What is verified
----------------
The graph's data-driven quot path (build_vm.py ``fire_quot`` / ``quot_go`` /
``quot_stuck_r`` / ``quot_sd``) reduces ``Quot.lift`` / ``Quot.ind`` applied to a
``Quot.mk`` exactly as ``quot_reduce_rec`` does (quot.h:39-70):

  * the head is a Quot constant recognised from its WP1 metadata
    (``T_ENV_META.V1 == CK_QUOT`` + ``T_ENV_QUOTVAL`` quot_kind, not a cid) --
    the four Quot constants carry unique quot_kinds (declaration.h:388), which is
    the token-VM equivalent of the kernel's name test (quot.h:45-53);
  * the reduction is gated on the is_quot_initialized surrogate (the token env
    carries a CK_QUOT constant), mirroring ``reduce_recursor``'s
    ``env().is_quot_initialized()`` gate (type_checker.cpp:394, environment.cpp:66,
    mark at quot.cpp:102);
  * ``quot_reduce_rec`` runs FIRST, before ``inductive_reduce_rec``
    (type_checker.cpp:393-407): Quot.lift/Quot.ind are ``quotInfo`` constants
    (quot.cpp:90-101), never recursors, so only the quot branch can reduce them;
  * ``Quot.lift`` uses mk_pos=5 / arg_pos=3, ``Quot.ind`` uses mk_pos=4 /
    arg_pos=3 (quot.h:45-50); the major must whnf to ``Quot.mk`` applied to
    EXACTLY 3 args (quot.h:59-61), else the application is stuck -- the
    observable meaning of ``quot_is_stuck`` (quot.h:76-95) and of the kernel
    whnf returning the unreduced spine.

Every environment constant, its ConstantInfo metadata and every expected verdict
come from the real binary: metadata via ``reference.olean_export.dump_env``
(``Environment.find?``), verdicts via ``reference.lean_ref.run_oracle_mixed``.
Nothing is hand-written.

Sections
--------
A  quot_val metadata (C4) + is_quot_initialized surrogate (C3): every Quot
   constant decodes as CK_QUOT (declaration.h:426) with the kernel quot_kind
   (declaration.h:388: Type=0, Mk=1, Lift=2, Ind=3); >=1 CK_QUOT present.
B  reduction + stuck corpus vs real lean (C1, C2, C5):
     - lift_id_whnf   @Quot.lift Nat QREL Nat (fun x=>x) QH (@Quot.mk Nat QREL 5)
                      whnf -> 5
     - lift_succ_whnf same but f = fun x => Nat.succ x   -> whnf 6 (arg_pos=3 is f)
     - ind_true_whnf  @Quot.ind Nat QREL (fun _=>True) (fun a=>True.intro) (mk 7)
                      whnf -> True.intro (discriminating: an unfired spine keeps
                      head Quot.ind; Quot.ind only eliminates into Prop
                      (quot.cpp:100), so a DEFEQ would be masked by
                      proof-irrelevance -- the structural WHNF is the check)
     - lift_id_true   defeq 5  -> True   (the reduction is real)
     - lift_id_false  defeq 6  -> False  (still reduces to the RIGHT value only)
     - lift_qmk_true  major is (@Quotient.mk Nat QSET 5), which whnf-delta
                      unfolds to a 3-arg Quot.mk before the arity test fires
                      (quot.h:59, the ``whnf(args[mk_pos])`` step) -> defeq 5 True
     - lift_stuck_false  major is the axiom QAX (whnf-stuck, head not Quot.mk)
                      -> defeq 5 False (quot_is_stuck / no reduction)
C  arity guard (quot.h:61, graph-only): the major is ``@Quot.mk Nat QREL`` with
   2 args.  In the real kernel a well-typed quotient is always a 3-arg ``Quot.mk``,
   so this branch is unreachable for the oracle (an under-applied Quot.mk is not a
   Quot and will not elaborate as lift's major).  It is exercised directly on the
   graph, which is ill-typed-tolerant: whnf must return the unchanged spine.
Run: setsid nohup env OMP_NUM_THREADS=4 taskset -c 0-3 python3 -u \
        tests/test_quot_graph_vs_lean.py > /tmp/quot_graph.log 2>&1 < /dev/null &
"""
from __future__ import annotations

import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import (
    App, Const, Lam, LitNat, BVar, BI_DEFAULT, MData, Let, Pi, Proj,
)
from expr.tokens import Encoder, decode_closure, decode_env_meta, CK_QUOT
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference import lean_ref
from reference.olean_export import dump_env, const_meta_for
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_LEAN_DEFS

NAT = Const("Nat")
QUOT = Const("Quot")
QUOT_MK = Const("Quot.mk")
QUOT_LIFT = Const("Quot.lift")
QUOT_IND = Const("Quot.ind")
QREL = Const("QREL")
QSET = Const("QSET")
QH = Const("QH")
QHS = Const("QHS")
QAX = Const("QAX")
EQ = Const("Eq")
TRUE_I = Const("True.intro")

# ── real-lean declarations the corpus elaborates against ────────────────────
QUOT_DEFS = r'''
def QREL : Nat → Nat → Prop := fun x y => x = y
theorem QH : ∀ a b : Nat, QREL a b → (fun x => x) a = (fun x => x) b :=
  fun a b hab => hab
theorem QHS : ∀ a b : Nat, QREL a b → (fun x => Nat.succ x) a = (fun x => Nat.succ x) b :=
  fun a b hab => congrArg Nat.succ hab
axiom QAX : Quot QREL
def QSET : Setoid Nat :=
  { r := QREL,
    iseqv := { refl := fun _ => rfl, symm := fun h => h.symm,
               trans := fun h1 h2 => h1.trans h2 } }
'''.lstrip()

DEFS = TOY_LEAN_DEFS + "\n" + QUOT_DEFS

# Roots: the four Quot constants, the Quotient wrapper (whose .mk whnf-unfolds
# into Quot.mk), the user defs/axiom, and the Nat/Eq/True supply the minors use.
# Every one resolves to a real ConstantInfo through the transitive closure.
ROOTS = [
    "Quot", "Quot.mk", "Quot.lift", "Quot.ind",
    "Quotient", "Quotient.mk",
    "QREL", "QH", "QHS", "QAX", "QSET",
    "Nat", "Nat.succ", "Eq", "Eq.refl", "True", "True.intro",
]

# Each legitimate case is < 30 micro-steps; a runaway loops to TimeoutError.
GRAPH_MAX_STEPS = 400


def _A(f, *xs):
    for x in xs:
        f = App(f, x)
    return f


def _canon(e):
    """Semantic comparison form: erase binder names, strip MData, drop Const
    universe levels.  Quot reduction (like iota/delta) does not observe binder
    names, mdata, or the universe levels that ``decode_closure`` omits but the
    oracle's serializer keeps, so both sides are normalised identically before a
    WHNF structural compare (extends the iota test's ``_erase_names``)."""
    if isinstance(e, MData):
        return _canon(e.child)
    if isinstance(e, App):
        return App(_canon(e.fn), _canon(e.arg))
    if isinstance(e, (Lam, Pi)):
        return type(e)("", e.binfo, _canon(e.domain), _canon(e.body))
    if isinstance(e, Let):
        return Let("", _canon(e.domain), _canon(e.value), _canon(e.body),
                   e.nondep)
    if isinstance(e, Proj):
        return Proj(e.sname, e.idx, _canon(e.child))
    if isinstance(e, Const):
        return Const(e.name, ())
    return e


def build_env():
    toy_names = [n for n, _, _ in TOY_CONSTS]
    toy_dump = dump_env(TOY_LEAN_DEFS, toy_names)
    quot_dump = dump_env(DEFS, ROOTS)
    merged = dict(toy_dump)
    merged.update(quot_dump)
    toy_set = set(toy_names)
    extra = sorted(n for n in quot_dump if n not in toy_set)
    consts = list(TOY_CONSTS) + [(n, quot_dump[n]["ty"], quot_dump[n]["val"])
                                 for n in extra]
    meta = const_meta_for(consts, merged)
    return consts, meta, quot_dump, extra


# ── graph terms (application args in the kernel @-spine order) ──────────────
# Quot.lift binder order is α, r, β, f, h, q (quot.cpp:90): arg_pos=3 is f,
# mk_pos=5 is q.  Quot.ind is α, r, β, motive, q (quot.cpp:100): arg_pos=3 is
# the motive, mk_pos=4 is q.  Positions are the kernel's fixed constants
# (quot.h:45-50); the graph reads them, never a cid.
_idf = Lam("x", BI_DEFAULT, NAT, BVar(0))                 # (fun x : Nat => x)
_succf = Lam("x", BI_DEFAULT, NAT, App(Const("Nat.succ"), BVar(0)))
_truei = Lam("a", BI_DEFAULT, NAT, TRUE_I)                # (fun a => True.intro)
_mk5 = _A(QUOT_MK, NAT, QREL, LitNat(5))
lift_id = _A(QUOT_LIFT, NAT, QREL, NAT, _idf, QH, _mk5)
lift_succ = _A(QUOT_LIFT, NAT, QREL, NAT, _succf, QHS, _mk5)
# Quot.ind: β (index 2) is never inspected by quot_reduce_rec, so a placeholder
# suffices; only args[3] (motive) and args[4] (major) matter.
ind7 = _A(QUOT_IND, NAT, QREL, NAT, _truei, _A(QUOT_MK, NAT, QREL, LitNat(7)))
# major reached via Quotient.mk, which whnf-delta-unfolds to a 3-arg Quot.mk
# before the arity test fires (quot.h:59-61).
_qmk5 = _A(Const("Quotient.mk"), NAT, QSET, LitNat(5))
lift_qmk = _A(QUOT_LIFT, NAT, QREL, NAT, _idf, QH, _qmk5)
# stuck major: the axiom QAX (whnf-stuck, head not Quot.mk).
lift_stuck = _A(QUOT_LIFT, NAT, QREL, NAT, _idf, QH, QAX)

# (id, kind, src_a, src_b, expr_a, expr_b)
CASES = [
    ("lift_id_whnf", "WHNF",
     "@Quot.lift Nat QREL Nat (fun x => x) QH (@Quot.mk Nat QREL 5)", None,
     lift_id, None),
    ("lift_succ_whnf", "WHNF",
     "@Quot.lift Nat QREL Nat (fun x => Nat.succ x) QHS (@Quot.mk Nat QREL 5)",
     None, lift_succ, None),
    ("ind_true_whnf", "WHNF",
     "@Quot.ind Nat QREL (fun _ => True) (fun a => True.intro) "
     "(@Quot.mk Nat QREL 7)", None, ind7, None),
    ("lift_id_true", "DEFEQ",
     "@Quot.lift Nat QREL Nat (fun x => x) QH (@Quot.mk Nat QREL 5)", "(5 : Nat)",
     lift_id, LitNat(5)),
    ("lift_id_false", "DEFEQ",
     "@Quot.lift Nat QREL Nat (fun x => x) QH (@Quot.mk Nat QREL 5)", "(6 : Nat)",
     lift_id, LitNat(6)),
    ("lift_qmk_true", "DEFEQ",
     "@Quot.lift Nat QREL Nat (fun x => x) QH (@Quotient.mk Nat QSET 5)",
     "(5 : Nat)", lift_qmk, LitNat(5)),
    ("lift_stuck_false", "DEFEQ",
     "@Quot.lift Nat QREL Nat (fun x => x) QH QAX", "(5 : Nat)",
     lift_stuck, LitNat(5)),
]

# C. arity guard (graph-only, ill-typed): Quot.mk with 2 args at mk_pos.
_ARITY_TERM = _A(QUOT_LIFT, NAT, QREL, NAT, _idf, QH, _A(QUOT_MK, NAT, QREL))


def _warm_prefix(consts, meta, graph, outputs):
    """Evaluate the (env-only) token prefix ONCE and snapshot the incremental
    evaluator's causal state so each case can resume from it instead of
    recomputing the whole O(N^2) env prefix.

    ``IncrementalGraphEvaluator.sync`` is append-only and causal: a position's
    computed values depend on earlier positions ONLY through ``lookup_history``
    (the (pos, kx, ky, values) hardmax entries), never through their ``vals``
    dicts, and ``sync`` returns ``vals[-1]``.  Seeding a fresh evaluator with the
    warm ``vals`` list (to fix the resume index and the returned last dict) and a
    per-case copy of ``lookup_history`` therefore reproduces a from-scratch run
    bit-for-bit; only the case's own appended term/machine tokens are computed.
    """
    enc0 = Encoder(consts, is_ctor=TOY_CTORS, const_meta=meta)
    drv0 = StepDriver(enc0.b, graph, outputs)
    env_len = len(drv0.names)               # env tokens, before any term
    drv0._eval.sync(drv0.names)             # causal warm-up, once
    warm_vals = drv0._eval.vals             # list of env_len position dicts
    warm_hist = drv0._eval.lookup_history   # dict id -> list of history tuples
    return env_len, warm_vals, warm_hist


def _run_graph(consts, meta, graph, outputs, ca, cb, kind, warm):
    env_len, warm_vals, warm_hist = warm
    enc = Encoder(consts, is_ctor=TOY_CTORS, const_meta=meta)
    drv = StepDriver(enc.b, graph, outputs)
    # resume the evaluator from the shared warm env prefix (identical positions)
    drv._eval.vals = list(warm_vals)
    drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
    assert len(drv.names) == env_len, "env prefix diverged from warm-up"
    t0 = time.perf_counter()
    if kind == "WHNF":
        p, e = drv.run(enc.encode_term(ca), max_steps=GRAPH_MAX_STEPS)
        res = _canon(decode_closure(enc.b, p, e))
    else:
        v = drv.run_defeq(enc.encode_term(ca), 0, enc.encode_term(cb), 0,
                          max_steps=GRAPH_MAX_STEPS)[0]
        res = bool(v)
    if os.environ.get("QUOT_TIME"):
        print(f"    [time] case run={time.perf_counter()-t0:.1f}s "
              f"steps={drv.steps}", flush=True)
    return res, drv.steps


def main() -> int:
    n_fail = 0
    fails: list[str] = []

    consts, meta, quot_dump, extra = build_env()
    print(f"env: {len(consts)} constants ({len(extra)} quot-closure)")

    # ── A. quot_val metadata (C4) + is_quot_initialized surrogate (C3) ──────
    b = Encoder(consts, is_ctor=TOY_CTORS, const_meta=meta).b
    n_meta = 0
    for name in extra:
        rm = quot_dump[name]["meta"]
        if int(rm.get("kind", -1)) != CK_QUOT:
            continue
        n_meta += 1
        dm = decode_env_meta(b, b.cids[name])
        if dm["kind"] != CK_QUOT:
            fails.append(f"[A {name}] decoded kind {dm['kind']} != CK_QUOT")
        if dm["quot_kind"] != int(rm["quotKind"]):
            fails.append(f"[A {name}] decoded quot_kind {dm['quot_kind']} != "
                         f"real {rm['quotKind']}")
    EXPECT = {"Quot": 0, "Quot.mk": 1, "Quot.lift": 2, "Quot.ind": 3}
    for name, want in EXPECT.items():
        if name not in b.cids:
            fails.append(f"[A] {name} absent from the environment")
            continue
        qk = decode_env_meta(b, b.cids[name])["quot_kind"]
        if qk != want:
            fails.append(f"[A {name}] quot_kind {qk} != kernel {want}")
    if n_meta < 1:
        fails.append("[A] no CK_QUOT constant: is_quot_initialized surrogate "
                     "cannot be true")
    print(f"A  quot_val metadata: {n_meta} Quot constants (kind + quot_kind "
          f"agree with the real dump; Type=0 Mk=1 Lift=2 Ind=3)")

    _g0 = time.perf_counter()
    graph, outputs = build_step_graph()
    warm = _warm_prefix(consts, meta, graph, outputs)
    if os.environ.get("QUOT_TIME"):
        print(f"    [time] build_step_graph + warm prefix "
              f"(env_len={warm[0]})={time.perf_counter()-_g0:.1f}s", flush=True)

    # ── B. reduction + stuck corpus vs real lean (C1, C2, C5) ───────────────
    if os.environ.get("QUOT_SKIP_B"):
        print("B  corpus: skipped (QUOT_SKIP_B set)")
        n_pass = 0
    else:
        entries = [(k, a, bb) for (_, k, a, bb, _, _) in CASES]
        _o0 = time.perf_counter()
        oracle = lean_ref.run_oracle_mixed(DEFS, entries)
        if os.environ.get("QUOT_TIME"):
            print(f"    [time] oracle(run_oracle_mixed)={time.perf_counter()-_o0:.1f}s "
                  f"({len(oracle)} verdicts)", flush=True)
        n_pass = 0
        for (cid, kind, sa, sb, ea, eb), oval in zip(CASES, oracle):
            try:
                got, steps = _run_graph(consts, meta, graph, outputs,
                                        ea, eb, kind, warm)
            except Exception as ex:                       # noqa: BLE001
                got = f"{type(ex).__name__}: {ex}"
                steps = -1
            if kind == "WHNF":
                exp = _canon(lean_ref.json_to_expr(oval[1]))
            else:
                exp = oval[1]
            if got == exp:
                n_pass += 1
                print(f"  [PASS] {cid} ({kind}, {steps} micro-steps)")
            else:
                fails.append(f"[B {cid}] graph={got!r} lean={exp!r}")
        print(f"B  reduction/stuck corpus vs real lean: {n_pass}/{len(CASES)}")

    # ── C. arity guard (quot.h:61), graph-only (unreachable for the oracle) ──
    try:
        enc_c = Encoder(consts, is_ctor=TOY_CTORS, const_meta=meta)
        drv_c = StepDriver(enc_c.b, graph, outputs)
        drv_c._eval.vals = list(warm[1])
        drv_c._eval.lookup_history = {i: list(h) for i, h in warm[2].items()}
        p, e = drv_c.run(enc_c.encode_term(_ARITY_TERM),
                         max_steps=GRAPH_MAX_STEPS)
        got_c = _canon(decode_closure(enc_c.b, p, e))
        stuck_c = (got_c == _canon(_ARITY_TERM))
        csteps = drv_c.steps
    except Exception as ex:                               # noqa: BLE001
        got_c = f"{type(ex).__name__}: {ex}"
        stuck_c = False
        csteps = -1
    if not stuck_c:
        fails.append(f"[C arity] 2-arg Quot.mk should stay stuck; got {got_c!r}")
    print(f"C  arity guard (Quot.mk arity 2 != 3): stuck={stuck_c} "
          f"({csteps} micro-steps)")

    for msg in fails:
        print(f"  [FAIL] {msg}")
    ok = not fails
    corpus = "skipped" if os.environ.get("QUOT_SKIP_B") \
        else f"{n_pass}/{len(CASES)}"
    print(f"\n=== WP4 Quot reduction: {corpus} corpus, A={n_meta} meta, "
          f"C-stuck={'y' if stuck_c else 'n'}, {len(fails)} failures === "
          f"{'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
