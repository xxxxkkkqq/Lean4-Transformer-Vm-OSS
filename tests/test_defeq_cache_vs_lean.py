"""Card 014 (P1+P2) differential: the cache layer vs the real
Lean 4.33.1 binary (acceptance oracle), on the minimal WP7 env.

What this pins (docs/handoffs/010-M-cache.md M2 + M4):
  * every A-group pair judged with the cache arms ON agrees with the live
    `Kernel.isDefEq` result (legacy AND meta=1 streams) — the cache never
    changes a verdict (ADR 017 red line);
  * P1 HIT LIVENESS: a pair that already completed True, re-launched on the
    SAME stream (two run_defeq calls on one driver), completes at the
    dispatch step via its T_DEFCACHE entry — strictly fewer steps than the
    OFF graph's identical second run (which has no cache to hit);
  * FALSE PAIRS NEVER WRITE (kernel `if (r)` asymmetry, K/
    type_checker.cpp:1247-1252): a False verdict repeats with the same
    verdict under both graphs (hit/miss consistency — the cache can only
    shorten via legitimate TRUE-subpair entries);
  * P2 WHNF HIT LIVENESS (--phase whnf): WITHDRAWN from acceptance by
    ADR 019 (2026-09-17, card 014 M6): after two root-cause fixes (hit-
    gate token-kind validation, write-gate clean-exit tightening) the P2
    memo still flipped verdicts on the string corpus (stale-V1/X
    mislabeled keys from spine-walk re-dispatch frames — soundness needs
    cross-beat memory, a redesign, not a gate fix).  VM014_WMEMO now
    defaults to "0" (dormant, code kept); this phase SKIPS with a printed
    reason unless the research opt-in `VM014_ALLOW_P2=1` is set — the
    arm body stays runnable for any follow-up P2 card (019 出路 §4).
  * d6: judged by the P1-ONLY graph against the LIVE oracle (converges
    True@1070 ≤ cap 1100, ADR 019 "d6 绿不损失").  The old P1+P2
    acceptance arm (P2 closing the ring) is likewise withdrawn to the
    same opt-in.  Registry coherence: d6 green while G4_d6 still sits in
    test_brec_drec_iota_vs_lean.KNOWN_GAPS fails this test (XPASS
    protocol — the entry must move in the suite, no silent drift).

Expectations are never fixtures: the oracle channel runs `~/.elan/bin/lean`
at run time (same template as test_defeq_branches_vs_lean).

Run (memory discipline, AGENTS.md).  --phase all runs everything in one
process (graphs are built one at a time; both-graphs-live at the old 720
cap breached the 6GB guard on 09-17):
  setsid nohup env OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u \
    scripts/run_mem_guarded.py --max-rss-mb 6144 -- \
    python3 -u tests/test_defeq_cache_vs_lean.py --phase all \
    > $HOME/logs/014/m4_cache_test.log 2>&1 < /dev/null &
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

# ADR 019: P2 (VM014_WMEMO) is DORMANT on every acceptance path.  The
# P2-specific arms below skip with a printed reason unless this research
# opt-in is set — never a silent removal, never a silently-passed arm.
ALLOW_P2 = os.environ.get("VM014_ALLOW_P2", "0") != "0"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import (T_DEFCACHE, T_WHNFCACHE, TASK_WHNF, T_FRAME,
                         Encoder, decode_closure)  # noqa: E402
from lean_vm import build_vm  # noqa: E402
from lean_vm.step_driver import StepDriver, VMError  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "db", ROOT / "tests" / "test_defeq_branches_vs_lean.py")
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

_spec2 = importlib.util.spec_from_file_location(
    "brec", ROOT / "tests" / "test_brec_drec_iota_vs_lean.py")
brec = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(brec)


def run_pair(graph_outputs, l, r, kw, cap, reps=2):
    """Judge (l,r) `reps` times on ONE stream — the T_DEFCACHE entries of
    run 1 are visible to run 2, which is exactly the cache protocol under
    test. Returns ([(verdict_str, steps_delta)], defcache_token_count)."""
    graph, outputs = graph_outputs
    enc = Encoder(db.CONSTS, is_ctor=db.TOY_CTORS, **kw)
    drv = StepDriver(enc.b, graph, outputs)
    lp = enc.encode_term(l)
    rp = enc.encode_term(r)
    out = []
    for _ in range(reps):
        base = drv.steps
        try:
            v = drv.run_defeq(lp, 0, rp, 0, max_steps=cap)
            out.append((bool(v[0]), drv.steps - base))
        except VMError as ex:
            out.append((f"rej{ex.code}", drv.steps - base))
        except TimeoutError:
            out.append(("timeout", cap))
    ncache = sum(1 for tok in enc.b.stream if tok[0] == T_DEFCACHE)
    return out, ncache


def run_d6(cache_on, wmemo_on):
    """d6 ring on one freshly-built graph, released before the next config
    (both-graphs-live breached the 6GB guard on 2026-09-17).  The step cap is
    brec.GRAPH_MAX_STEPS = 1100 (card 014 lead ruling: d6 converges
    legitimately at 1012/1070 steps with verdict True, see the comment
    there; ADR 019 made the 1070-step P1-only arm the acceptance one)."""
    import gc
    build_vm.VM014_CACHE = cache_on
    build_vm.VM014_WMEMO = wmemo_on
    graph, outputs = build_vm.build_step_graph()
    consts, gmeta, _dump = brec.build_group(brec.NAT_DEFS, brec.NAT_ROOTS)
    env_len, wv, wh = brec.warm_prefix(consts, gmeta, graph, outputs)
    enc = Encoder(consts, is_ctor=brec.TOY_CTORS, const_meta=gmeta)
    drv = StepDriver(enc.b, graph, outputs)
    drv._eval.vals = list(wv)
    drv._eval.lookup_history = {i: list(h) for i, h in wh.items()}
    tp = enc.encode_term(brec.Const("d6l"))
    sp = enc.encode_term(brec.Const("d6r"))
    try:
        v = drv.run_defeq(tp, 0, sp, 0, max_steps=brec.GRAPH_MAX_STEPS)
        res = (bool(v[0]), drv.steps)
    except (VMError, TimeoutError) as ex:
        res = (type(ex).__name__, drv.steps)
    ncache = sum(1 for tok in enc.b.stream if tok[0] == T_DEFCACHE)
    nwhnf = sum(1 for tok in enc.b.stream if tok[0] == T_WHNFCACHE)
    del drv, enc, graph, outputs, consts, gmeta, wv, wh
    gc.collect()
    return res + (ncache, nwhnf)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all",
                    choices=["small", "d6", "whnf", "all"])
    args = ap.parse_args()
    t0 = time.perf_counter()
    fails: list[str] = []

    if args.phase in ("small", "all"):
        main_small(fails)
    if args.phase in ("d6", "all"):
        main_d6(fails)
    if args.phase in ("whnf", "all"):
        main_whnf(fails)

    print(f"\n=== defeq cache vs lean [{args.phase}]: "
          f"{'ALL OK' if not fails else f'{len(fails)} FAILURES'} "
          f"({time.perf_counter()-t0:.0f}s) ===")
    for m in fails:
        print("  [NOTE]", m)
    return 1 if fails else 0


def main_small(fails):
    t0 = time.perf_counter()
    # ── oracle (live binary, nothing pre-baked) ─────────────────────────────
    imps, rest = db._split_defs(db.DEFS)
    src = db.KDEFEQ_TEMPLATE.format(imports=imps, defs=rest)
    for cid, lsrc, rsrc, *_ in db.CASES:
        src += f"\n#KDEFEQ {cid} ({lsrc}, {rsrc})"
    kern = db.run_lean(src, "kdefeq_cache")
    print(f"oracle {time.perf_counter()-t0:.0f}s", flush=True)

    from reference.olean_export import dump_env, const_meta_for
    meta = const_meta_for(db.CONSTS, dump_env(db.DEFS, db.NAMES))

    graphs = {}
    for name, flag in (("off", False), ("on", True)):
        build_vm.VM014_CACHE = flag
        # this arm isolates P1: the whnf memo stays OFF on BOTH graphs
        # (M2 semantics preserved — "off" must be the baseline graph)
        build_vm.VM014_WMEMO = False
        graphs[name] = build_vm.build_step_graph()
    print("graphs built (off/on)", flush=True)

    # ── arms 1+2: verdicts on both streams (cache ON) vs oracle, and on the
    #     legacy arm the second-run hit-liveness comparison vs cache OFF ────
    for stream, kw in (("legacy", {}), ("meta", {"const_meta": meta})):
        for cid, _, _, l, r, branch in db.CASES:
            kv = kern.get(f"KDEFEQ {cid}", "MISSING")
            assert kv in ("true", "false"), f"{cid}: kernel channel {kv}"
            exp = kv == "true"
            got, ncache = run_pair(graphs["on"], l, r, kw, 8000)
            (v1, s1), (v2, s2) = got
            ok = v1 is exp and v2 is exp
            goff = None
            if stream == "legacy":
                goff, _ = run_pair(graphs["off"], l, r, {}, 8000)
                _, so2 = goff[1]
                if exp:
                    ok = ok and s2 < so2 and ncache >= 1
            tag = "OK " if ok else "FAIL"
            if not ok:
                fails.append(f"[{stream} {cid}] {v1}/{v2} lean={exp} "
                             f"steps={s1}->{s2} "
                             f"off2={goff[1] if goff else '-'}")
            print(f"  [{tag} {stream:6s} {branch:8s}] {cid:26s} "
                  f"kernel={kv:5s} on run1={v1}/{s1} run2={v2}/{s2} "
                  f"defcache={ncache}"
                  + (f" off run2={goff[1][0]}/{goff[1][1]}"
                     if goff else ""), flush=True)

    # ── arm 3: False-pair repeat consistency (verdict must not flip; a
    #     False pair itself is never written — only legitimate TRUE-subpair
    #     hits may shorten the second run).
    for cid, _, _, l, r, branch in db.CASES:
        if kern.get(f"KDEFEQ {cid}") != "false":
            continue
        got, _ = run_pair(graphs["on"], l, r, {}, 8000, 2)
        ok3 = got[0][0] is False and got[1][0] is False
        if not ok3:
            fails.append(f"[false-repeat {cid}] {got}")
        print(f"  [{'OK ' if ok3 else 'FAIL'} false-rpt {branch:8s}] "
              f"{cid:26s} run1={got[0]} run2={got[1]}", flush=True)
    print(f"small phase done {time.perf_counter()-t0:.0f}s", flush=True)


def main_d6(fails):
    # ── the d6 growth ring, judged against the LIVE oracle.  ACCEPTANCE
    #     arm = the P1-ONLY graph (True@1070 ≤ cap 1100; M5-02b, ADR 019
    #     "d6 绿不损失").  The old P1+P2 arm (P2 closing the ring) is
    #     WITHDRAWN by ADR 019: the whnf memo flips the string corpus and
    #     its soundness needs a redesign; it runs only under the research
    #     opt-in VM014_ALLOW_P2=1.  A capped (timeout) run IS a divergence
    #     from the kernel per ADR 017.  Memory-lean: graphs never coexist
    #     (built one at a time inside run_d6, 6GB guard breach 09-17).
    oracle = brec.lean_ref.run_oracle_mixed(
        brec.NAT_DEFS, [("DEFEQ", "d6l", "d6r")])
    ov = bool(oracle[0][1])
    print(f"  d6 live oracle: d6l=?=d6r -> {ov}", flush=True)
    p1 = run_d6(True, False)     # P1-only acceptance arm
    print(f"  d6 P1-only={p1}", flush=True)
    if p1[0] is not ov:
        fails.append(f"[d6 vs oracle] P1-only {p1[0]!r} lean={ov}")
    if p1[0] is True and "G4_d6" in brec.KNOWN_GAPS:
        fails.append("[d6 XPASS] G4_d6 registry entry in "
                     "test_brec_drec_iota_vs_lean.py must move per card 014 "
                     "acceptance (010-M M4-03/M5-02b), not silently pass")
    # ADR 019 shipped-state reverse assertion: the DEFAULT graph must never
    # write a T_WHNFCACHE entry (P2 dormant, arm not built at all).  A
    # non-zero count here means VM014_WMEMO leaked into the build path.
    if p1[3] != 0:
        fails.append(f"[d6 whnf-memo leak] P1-only run wrote {p1[3]} "
                     "T_WHNFCACHE entries — shipped graph must be "
                     "whnf-memo inert (ADR 019)")
    if ALLOW_P2:
        p2 = run_d6(True, True)  # research arm, P2 opt-in (ADR 019 §4)
        print(f"  d6 P1+P2={p2}  [VM014_ALLOW_P2 research opt-in]", flush=True)
        if p2[0] is not ov and str(p2[0]) != "TimeoutError":
            fails.append(f"[d6 vs oracle] P1+P2 {p2[0]!r} lean={ov}")
        if str(p1[0]) != str(p2[0]) and not (
                str(p1[0]) == "TimeoutError" and p2[0] is ov):
            fails.append(f"[d6 verdict] P1-only {p1[0]!r} vs P1+P2 {p2[0]!r} "
                         f"(only a timeout->oracle RESCUE is allowed)")
        if p2[0] is ov and p1[0] is ov and p2[1] > p1[1]:
            # both close: the memo may not INCREASE work on this shape
            fails.append(f"[d6 steps-up] P1 {p1[1]} -> P1+P2 {p2[1]}")
        if p2[3] == 0 and p2[1] > 100:
            fails.append(f"[d6 whnf-memo dead] no T_WHNFCACHE written in a "
                         f"{p2[1]}-step run: write arm never fired")
    else:
        print("  d6 P1+P2 arm: SKIP — P2 dormant per ADR 019 "
              "(opt in with VM014_ALLOW_P2=1)", flush=True)


def whnf_twice(graph_outputs, term, cap=4000):
    """Launch TASK_WHNF (term, env 0, hard) twice on ONE stream (root
    frame, caller 0). Run 1 computes (and must write its T_WHNFCACHE entry
    at the delivery beat); run 2 sees the entry at its clean-chain first
    beat and replays it. Returns ([(tag, result_pair, steps) x2],
    n_whnf_tokens, enc) — the encoder is returned so callers can
    CONTENT-compare results across streams (decode_closure; see main_whnf).
    """
    graph, outputs = graph_outputs
    enc = Encoder(db.CONSTS, is_ctor=db.TOY_CTORS)
    drv = StepDriver(enc.b, graph, outputs)
    tp = enc.encode_term(term)
    runs = []
    for _ in range(2):
        base = drv.steps
        fpos = drv._append(T_FRAME, V0=TASK_WHNF, V1=tp, V2=0, X=0,
                           E2=0, F2=0)
        drv.init_state(tp, 0, 0, D=fpos, E=0, F=0)
        try:
            done = False
            r = None
            while not done and drv.steps - base < cap:
                done, r = drv.step()
            runs.append(("ok", tuple(r) if r else None,
                         drv.steps - base if done else "timeout"))
        except VMError as ex:
            runs.append((f"rej{ex.code}", None, drv.steps - base))
    nwhnf = sum(1 for tok in enc.b.stream if tok[0] == T_WHNFCACHE)
    return runs, nwhnf, enc


def main_whnf(fails):
    import gc
    if not ALLOW_P2:
        # ADR 019: this whole arm pins P2 (T_WHNFCACHE) liveness — P2 is
        # DORMANT on acceptance paths after the string-corpus verdict
        # breach (stale-V1/X mislabeled keys, cross-beat memory needed).
        # Skipped with an explicit reason, NOT deleted: the arm body
        # below must keep working for any follow-up P2 card.
        print("whnf phase: SKIP — P2 (VM014_WMEMO) dormant per ADR 019; "
              "research opt-in VM014_ALLOW_P2=1", flush=True)
        return
    t0 = time.perf_counter()
    graphs = {}
    for name, wmemo in (("p1", False), ("p2", True)):
        build_vm.VM014_CACHE = True
        build_vm.VM014_WMEMO = wmemo
        graphs[name] = build_vm.build_step_graph()
    print("whnf-arm graphs built (p1 / p1+p2)", flush=True)

    # every A-group side is a candidate (terms are machine-neutral inputs;
    # whnf results are NOT oracled here — replay consistency + step
    # monotonicity are the contract, the live-lean verdict surface stays
    # with the defeq/d6 arms above and the brec suite)
    cands = []
    for cid, _, _, l, r, branch in db.CASES:
        cands.append((cid + ".l", l))
        cands.append((cid + ".r", r))
    found = 0
    for label, term in cands:
        r2, n2, enc2 = whnf_twice(graphs["p2"], term)
        (t1, p1v, s1), (t2, p2v, s2) = r2
        if t1 != "ok" or t2 != "ok" or not isinstance(s1, int) or s1 < 4:
            continue      # leaf/reject terms are not liveness cases
        found += 1
        ok = (p1v == p2v and s2 <= 3 and n2 >= 1)
        r1, n1, enc1 = whnf_twice(graphs["p1"], term)
        ok = ok and r1[0] == (t1, p1v, s1)      # run1 unaffected by memo
        ok = ok and r1[1][0] == t2 \
            and isinstance(r1[1][2], int) and r1[1][2] > s2  # control reruns
        # CROSS-GRAPH equality is on DECODED CONTENT, never on the raw
        # (pos, env) pair.  A recompute re-materialises its reduction chain
        # as FRESH stream tokens — the control's run2 lands on a later
        # position than the memo's replay of run1's canonical materialization
        # while both hold the same whnf value (measured 2026-09-17 on
        # o1/h1-h4: LitNat(5) at pos 573-replayed vs 613-recomputed, trees
        # decode-equal; the first version of this arm asserted pair identity
        # and mis-flagged 9 liveness cases).  The intra-graph check p1v==p2v
        # (replay == run1, position included) keeps the pointer-level claim
        # where it is sound.
        try:
            e_replay = decode_closure(enc2.b, *p2v)
            e_ctrl = decode_closure(enc1.b, *r1[1][1])
            ok = ok and e_replay == e_ctrl
        except Exception as ex:
            ok = False
            print(f"      [decode FAIL {label}] {type(ex).__name__}: {ex}",
                  flush=True)
        tag = "OK " if ok else "FAIL"
        if not ok:
            fails.append(f"[whnf liveness {label}] p2 {r2} n2={n2} p1 {r1}")
        print(f"  [{tag} whnf {label:26s}] run1={s1} run2={s2} "
              f"p1-run2={r1[1][2]} whnf_toks={n2} res={p1v}/{p2v}",
              flush=True)
    if found == 0:
        fails.append("[whnf liveness] no multi-step whnf candidate "
                     "completed — arm silently dead")
    del graphs
    gc.collect()
    print(f"whnf phase done {time.perf_counter()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
