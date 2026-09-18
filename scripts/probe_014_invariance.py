"""Card 014 / M2-02: cache-arm verdict-invariance harness (ADR 017).

The cache arms may only REMOVE steps, never change a verdict. This probe
builds BOTH graphs in one process (module switches patched between builds),
judges the same case set under each, and asserts:
  * per-case verdict equality (True/False/rej-code/timeout strings),
  * steps(cache-ON) <= steps(cache-OFF)  (only-down, never-up),
  * cache-ON runs still agree with the LIVE oracle (nothing here trusts a
    fixture: every expectation comes from ~/.elan/bin/lean at run time).

--layer p1 (default, M2): OFF = baseline graph, ON = VM014_CACHE (P1).
--layer p2 (M4): OFF = P1-only graph, ON = P1+P2 (VM014_WMEMO whnf memo).
In layer p2 a case whose OFF verdict is `timeout` at the finite cap and
whose ON verdict EQUALS the live oracle is reported RESCUE, not
VERDICT-DIFF: ADR 017 counts a capped run as the divergence being
narrowed (d6 is exactly that case).

Case set (M6-05 opened + M7-02 closed — the contract hole that let the M5
breach through: the table must cover EVERY verdict-corpus family, every
graph-judged case of it):
  * A / Am / G / brec-nat / brec-lst  (original M2/M4 face — 55 cases);
  * STR  string suite B corpus, ALL 30 cases — 27 CASES (INFER/WHNF/DEFEQ)
    plus the 3 raw-.proj WHNF arms (PROJ_CASES, w5.run_proj_oracle live
    batch) that the M6 pass left out; the family where P2 flipped
    True->reject@341 (ADR 019 mechanism 2);
  * CHK  check_e2e graph face, all 15 verdicts — 12 single decls + the 3
    multi-decl SEQUENCES (the suite's A/B "30" is these 15 judged once by
    the frozen cache-independent RefVM and once by the graph; only the
    graph side is cache-sensitive, so the table lists 15);
  * MUT  mutation_reject part A BASE (8) + part B mutants with localize
    verdict (kind + offending expr — acceptance criterion 2 face);
  * OE-W/OE-D/OE-I  olean_export layer B, ALL 17 — 7 graph WHNF, 4 graph
    DEFEQ (added by M7-02; the M6 pass had only the 6 INFER cases).
STR expectations come from live lean batches taken in this harness.
CHK/MUT/OE-* carry no oracle channel here (their suites pin the OFF
state against lean/RefVM); they are listed as "?" and the table asserts
OFF-vs-ON verdict equality + steps non-increasing for them.  Layer p2 (the whnf memo face) is RESEARCH-ONLY
since ADR 019 withdrew P2; layer p1 (baseline vs default P1) is the
delivered contract.

Run (memory discipline, AGENTS.md — brec d6 is the ~4GB case; the two
layers are SEPARATE processes — never hold >2 big graphs in one run):
  setsid nohup env OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u \
    scripts/run_mem_guarded.py --max-rss-mb 6144 -- \
    scripts/probe_014_invariance.py --layer p2 > $HOME/logs/014/m4_inv_p2.log 2>&1 < /dev/null &
Subset: --cases quick  (defeq legacy arm + lst only; minutes, not tens).
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from expr.tokens import (T_DEFCACHE, T_WHNFCACHE, Encoder,         # noqa: E402
                         decode_closure)
from lean_vm import build_vm                                      # noqa: E402
from lean_vm.step_driver import StepDriver, VMError               # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "brec", ROOT / "tests" / "test_brec_drec_iota_vs_lean.py")
brec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brec)

_spec2 = importlib.util.spec_from_file_location(
    "db", ROOT / "tests" / "test_defeq_branches_vs_lean.py")
db = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(db)


def judge(drv: StepDriver, tp: int, sp: int, cap: int):
    """(verdict_str, steps) for a DEFEQ run, verdict as an opaque string so
    False / reject / timeout are never conflated."""
    try:
        v = drv.run_defeq(tp, 0, sp, 0, max_steps=cap)
        return (bool(v[0]), drv.steps)
    except VMError as ex:
        return (f"rej{ex.code}", drv.steps)
    except TimeoutError:
        return ("timeout", cap)


def judge_check(drv: StepDriver, decls, cap: int):
    try:
        drv.run_check(decls, max_steps=cap)
        return (0, drv.steps)
    except VMError as ex:
        return (ex.code, drv.steps)
    except TimeoutError:
        return ("timeout", cap)


def collect_cases(mode: str):
    """Precompute every graph-independent input once (lean dumps +
    live oracle verdicts), so both phases judge identical streams."""
    jobs = {}

    # ── defeq A group: legacy + meta streams ───────────────────────────────
    imps, rest = db._split_defs(db.DEFS)
    src = db.KDEFEQ_TEMPLATE.format(imports=imps, defs=rest)
    for cid, lsrc, rsrc, *_ in db.CASES:
        src += f"\n#KDEFEQ {cid} ({lsrc}, {rsrc})"
    kern = db.run_lean(src, "kdefeq_inv")
    from reference.olean_export import dump_env, const_meta_for
    meta = const_meta_for(db.CONSTS, dump_env(db.DEFS, db.NAMES))
    jobs["A"] = [("A/" + cid, l, r, kern.get(f"KDEFEQ {cid}", "MISSING") == "true",
                  {})
                 for cid, _, _, l, r, _ in db.CASES]
    jobs["Am"] = [("Am/" + cid, l, r,
                   kern.get(f"KDEFEQ {cid}", "MISSING") == "true",
                   {"const_meta": meta})
                  for cid, _, _, l, r, _ in db.CASES]

    if mode == "quick":
        # quick smoke: legacy A arm only (meta arm is a suite job)
        for k in list(jobs):
            if k != "A":
                del jobs[k]

    # ── brec B/C groups (faithful brecOn DEFEQ, oracle DEFEQ channel) ──────
    srcg = db.KDECL_MSG_TEMPLATE.format(imports=imps, defs=rest)
    for cid, dsrc, *_ in db.G_CASES:
        srcg += f"\n#KDECLMSG {cid} ({dsrc})"
    kdecl = db.run_lean(srcg, "kdecl_inv")
    gjobs = []
    for cid, _, ty, val, _expect, meta_only in db.G_CASES:
        if mode == "quick" or meta_only:
            continue      # G cases / meta-only stream: full mode only
        gjobs.append(("G/" + cid, ty, val, kdecl.get(f"KDECLMSG {cid}", ""),
                      meta_only, meta))
    jobs["G"] = gjobs

    groups = {}
    for label, defs, roots, cases in (
            ("nat", brec.NAT_DEFS, brec.NAT_ROOTS, brec.NAT_CASES),
            ("lst", brec.LST_DEFS, brec.LST_ROOTS, brec.LST_CASES)):
        if mode == "quick" and label != "lst":
            continue
        consts, grp_meta, _dump = brec.build_group(defs, roots)
        oracle = brec.lean_ref.run_oracle_mixed(
            defs, [("DEFEQ", l, r) for _, l, r in cases])
        groups[label] = (defs, consts, grp_meta, cases,
                         {cid: bool(ov) for (cid, _, _), (_k, ov)
                          in zip(cases, oracle)})
    return jobs, groups


def collect_fams(mode: str):
    """M6-05: the four verdict-corpus families that the breach escaped
    through.  Returns (families, expected) — `families` is a list of
    {"name", "setup(graph,outputs)->ctx", "cases": [(cid, fn)]}; each fn
    returns an OPAQUE verdict string + steps + stream (never a fixture:
    STR expectations come from a live lean batch taken here)."""
    fams, expected = [], {}
    import tests.test_string_graph_vs_lean as w5
    from reference import lean_ref
    sconsts, sctors, smeta, _ord = w5.build_env()
    # live oracle for the whole string B corpus (same batch as the suite);
    # skipped in quick mode, which drops the STR family below anyway
    oracle = (lean_ref.run_oracle_mixed(
        w5.TOY_LEAN_DEFS,
        [(k, a, bb) for (_, k, a, bb, _, _) in w5.CASES])
        if mode != "quick" else None)

    def str_case(ca, cb, kind):
        def fn(ctx, graph, outputs):
            env_len, wv, wh = ctx
            enc = Encoder(sconsts, is_ctor=sctors, const_meta=smeta)
            drv = StepDriver(enc.b, graph, outputs)
            drv._eval.vals = list(wv)
            drv._eval.lookup_history = {i: list(h) for i, h in wh.items()}
            try:
                if kind == "WHNF":
                    p, e = drv.run(enc.encode_term(ca),
                                   max_steps=w5.GRAPH_MAX_STEPS)
                    res = repr(w5._canon(decode_closure(enc.b, p, e)))
                elif kind == "INFER":
                    p, e = drv.run_infer(enc.encode_term(ca),
                                         max_steps=w5.GRAPH_MAX_STEPS)
                    res = repr(w5._canon(decode_closure(enc.b, p, e)))
                else:
                    v = drv.run_defeq(enc.encode_term(ca), 0,
                                      enc.encode_term(cb), 0,
                                      max_steps=w5.GRAPH_MAX_STEPS)[0]
                    res = str(bool(v))
            except VMError as ex:
                res = f"rej{ex.code}"
            except TimeoutError:
                res = "timeout"
            return res, drv.steps, enc.b.stream
        return fn

    for (cid, kind, _sa, _sb, ea, eb), (_k, oval) in (
            zip(w5.CASES, oracle) if oracle else []):
        # run_oracle_mixed yields (kind, payload); `oval` IS the payload
        # (bool for DEFEQ, serialized expr dict for WHNF/INFER).  The M6
        # version indexed oval[1] here and died on the first WHNF case —
        # quick-mode smoke (CHK/INF only) never reached this loop.
        if kind == "DEFEQ":
            expected[f"STR/{cid}"] = str(bool(oval))
        else:
            expected[f"STR/{cid}"] = repr(
                w5._canon(lean_ref.json_to_expr(oval)))
    # M7-02: the raw-.proj WHNF arms complete the string B face (27+3=30).
    # Live oracle = the suite's own run_proj_oracle batch (Meta.whnf is
    # `@[extern lean_whnf]`, i.e. the kernel whnf path itself).
    proj_cases = []
    if oracle:                       # full mode only (quick drops STR)
        poracle = w5.run_proj_oracle()
        for (cid, _idx, _s, ea), pval in zip(w5.PROJ_CASES, poracle):
            expected[f"STR/{cid}"] = repr(
                w5._canon(lean_ref.json_to_expr(pval)))
            proj_cases.append((f"STR/{cid}", str_case(ea, None, "WHNF")))
    fams.append({"name": "STR",
                 "setup": lambda g, o: w5._warm_prefix(sconsts, sctors,
                                                       smeta, g, o),
                 "cases": [(f"STR/{cid}", str_case(ea, eb, kind))
                           for (cid, kind, _s1, _s2, ea, eb) in w5.CASES]
                          + proj_cases})

    # ── toy env shared by check_e2e / mutation_reject / olean_export ───────
    from tests.test_check_e2e import CASE, SEQUENCES
    from tests.test_mutation_reject import BASE, MUTANTS
    import tests.test_olean_export as oe
    from reference.olean_export import import_env
    from lean_vm.localize import localize
    consts, ctors, _structs = import_env(oe.TARGET_DEFS, oe.ROOTS)

    def check_case(decls):
        """Graph run_check over one or more (type, value) Expr pairs; the
        verdict is opaque ("OK" / "rej<code>" / "timeout") so a reject code
        is part of the compared string (acceptance criterion 2)."""
        def fn(ctx, graph, outputs):
            enc = Encoder(consts, is_ctor=ctors)
            drv = StepDriver(enc.b, graph, outputs)
            ed = [(enc.encode_term(te), enc.encode_term(ve))
                  for te, ve in decls]
            try:
                drv.run_check(ed)
                res = "OK"
            except VMError as ex:
                res = f"rej{ex.code}"
            except TimeoutError:
                res = "timeout"
            return res, drv.steps, enc.b.stream
        return fn

    # M7-02: the 3 multi-decl SEQUENCES complete the check_e2e graph face
    # (12 singles + 3 sequences = the suite's 15 verdicts; its "A/B 30"
    # double-counts each through frozen RefVM + graph, only the graph side
    # is cache-sensitive).
    fams.append({"name": "CHK", "setup": lambda g, o: None,
                 "cases": [(f"CHK/{cid}", check_case([(te, ve)]))
                           for cid, (_ts, _vs, te, ve) in CASE.items()]
                          + [(f"CHK/{cid}",
                              check_case([(CASE[m][2], CASE[m][3])
                                          for m in members]))
                             for cid, members in SEQUENCES]})
    # M8-01 fix: the M7 bracket placement made each decls element
    # `[(te, ve)]` (a 1-item list); `for te, ve in decls` then died with
    # "not enough values" on the FIRST sequence case (quick smoke never
    # executed the seq bodies).  Suite parity: test_check_e2e:100-106
    # encodes the member pairs of one sequence into a single check run.
    fams.append({"name": "MUTB", "setup": lambda g, o: None,
                 "cases": [(f"MUTB/{cid}", check_case([(te, ve)]))
                           for cid, (_ts, _vs, te, ve) in BASE.items()]})

    def mut_case(te, ve):
        def fn(ctx, graph, outputs):
            enc = Encoder(consts, is_ctor=ctors)
            drv = StepDriver(enc.b, graph, outputs)
            tr, vr = enc.encode_term(te), enc.encode_term(ve)
            steps = 0
            try:
                drv.run_check([(tr, vr)])
                return "ACCEPTED(mutant!)", drv.steps, enc.b.stream
            except VMError as ex:
                res0 = f"rej{ex.code}"
            except Exception as ex:                          # noqa: BLE001
                return f"{type(ex).__name__}", drv.steps, enc.b.stream
            steps = drv.steps
            enc2 = Encoder(consts, is_ctor=ctors)
            d2 = StepDriver(enc2.b, graph, outputs)
            tr2, vr2 = enc2.encode_term(te), enc2.encode_term(ve)
            try:
                inferred = d2.run_infer(vr2)
                focus2 = -1
            except VMError as ex:
                inferred, focus2 = None, ex.focus
            loc = localize(enc2.b, tr2, vr2, inferred=inferred,
                           infer_focus=focus2)
            res = (f"{res0}|{loc['kind']}|"
                   f"{loc.get('offending_expr')!r}")
            return res, steps + d2.steps, enc2.b.stream
        return fn

    fams.append({"name": "MUT", "setup": lambda g, o: None,
                 "cases": [(f"MUT/{m[0]}", mut_case(m[4], m[5]))
                           for m in MUTANTS]})

    def infer_case(expr):
        def fn(ctx, graph, outputs):
            enc = Encoder(consts, is_ctor=ctors)
            drv = StepDriver(enc.b, graph, outputs)
            try:
                gp, genv = drv.run_infer(enc.encode_term(expr))
                res = repr(oe.strip_mdata(decode_closure(enc.b, gp, genv)))
            except VMError as ex:
                res = f"rej{ex.code}"
            except TimeoutError:
                res = "timeout"
            return res, drv.steps, enc.b.stream
        return fn

    fams.append({"name": "INF", "setup": lambda g, o: None,
                 "cases": [(f"INF/{c}", infer_case(e))
                           for (c, _s, e) in oe.INFER_CASES]})

    # ── M7-02: the remaining olean_export graph face (7 WHNF + 4 DEFEQ;
    #     the 3 excluded whnf/deq shapes are P2-gated in the suite itself —
    #     GRAPH_WHNF/GRAPH_DEFEQ already carry that filter) ─────────────────
    def oe_whnf_case(expr):
        def fn(ctx, graph, outputs):
            enc = Encoder(consts, is_ctor=ctors)
            drv = StepDriver(enc.b, graph, outputs)
            try:
                p, e = drv.run(enc.encode_term(expr))
                res = repr(oe.strip_mdata(decode_closure(enc.b, p, e)))
            except VMError as ex:
                res = f"rej{ex.code}"
            except TimeoutError:
                res = "timeout"
            return res, drv.steps, enc.b.stream
        return fn

    def oe_defeq_case(l, r):
        def fn(ctx, graph, outputs):
            enc = Encoder(consts, is_ctor=ctors)
            drv = StepDriver(enc.b, graph, outputs)
            try:
                v = drv.run_defeq(enc.encode_term(l), 0,
                                  enc.encode_term(r), 0)[0]
                res = str(bool(v))
            except VMError as ex:
                res = f"rej{ex.code}"
            except TimeoutError:
                res = "timeout"
            return res, drv.steps, enc.b.stream
        return fn

    fams.append({"name": "OE", "setup": lambda g, o: None,
                 "cases": [(f"OE/{cid}", oe_whnf_case(our))
                           for cid, _src, our in oe.WHNF_CASES
                           if cid in oe.GRAPH_WHNF]
                          + [(f"OE/{cid}", oe_defeq_case(ol, orr))
                             for cid, _s, _t, ol, orr in oe.DEFEQ_CASES
                             if cid in oe.GRAPH_DEFEQ]})
    if mode == "quick":
        fams = [f for f in fams if f["name"] in ("CHK", "INF", "OE")]
    return fams, expected


def phase(name, cache_on, wmemo_on, jobs, groups, fams=()):
    """Run every collected case with the graph built under this switch."""
    build_vm.VM014_CACHE = cache_on
    build_vm.VM014_WMEMO = wmemo_on
    graph, outputs = build_vm.build_step_graph()
    print(f"[{name}] graph built (VM014_CACHE={int(cache_on)} "
          f"VM014_WMEMO={int(wmemo_on)})", flush=True)
    res = {}
    for key in ("A", "Am", "G"):
        for job in jobs.get(key, []):
            t0 = time.perf_counter()
            cid = job[0]
            if key == "G":
                _, ty, val, _cls, _mo, meta = job
                enc = Encoder(db.CONSTS, is_ctor=db.TOY_CTORS,
                              const_meta=meta) if _mo else \
                    Encoder(db.CONSTS, is_ctor=db.TOY_CTORS)
                drv = StepDriver(enc.b, graph, outputs)
                t = enc.encode_term(ty)
                v = enc.encode_term(val) if val is not None else 0
                got = judge_check(drv, [(t, v)], 50000)
            else:
                _, l, r, _exp, kw = job
                enc = Encoder(db.CONSTS, is_ctor=db.TOY_CTORS, **kw)
                drv = StepDriver(enc.b, graph, outputs)
                lp = enc.encode_term(l)
                rp = enc.encode_term(r)
                got = judge(drv, lp, rp, 8000)
            res[cid] = got
            print(f"[{name}] {cid:28s} {got[0]!s:9s} steps={got[1]:5d} "
                  f"({time.perf_counter()-t0:.1f}s)", flush=True)
    for label, (defs, consts, grp_meta, cases, orc) in groups.items():
        warm = brec.warm_prefix(consts, grp_meta, graph, outputs)
        for cid, l, r in cases:
            t0 = time.perf_counter()
            env_len, warm_vals, warm_hist = warm
            enc = Encoder(consts, is_ctor=brec.TOY_CTORS, const_meta=grp_meta)
            drv = StepDriver(enc.b, graph, outputs)
            drv._eval.vals = list(warm_vals)
            drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
            tp = enc.encode_term(brec.Const(l))
            sp = enc.encode_term(brec.Const(r))
            got = judge(drv, tp, sp, brec.GRAPH_MAX_STEPS)
            ncache = sum(1 for tok in enc.b.stream if tok[0] == T_DEFCACHE)
            nwhnf = sum(1 for tok in enc.b.stream if tok[0] == T_WHNFCACHE)
            res[cid] = got + (ncache, nwhnf)
            print(f"[{name}] {label}:{cid:12s} {got[0]!s:9s} "
                  f"steps={got[1]:5d} defcache_toks={ncache:3d} "
                  f"whnfcache_toks={nwhnf:3d} "
                  f"({time.perf_counter()-t0:.1f}s)", flush=True)
    for fam in fams:
        ctx = fam["setup"](graph, outputs)
        for cid, fn in fam["cases"]:
            t0 = time.perf_counter()
            verdict, steps, stream = fn(ctx, graph, outputs)
            ncache = sum(1 for tok in stream if tok[0] == T_DEFCACHE)
            nwhnf = sum(1 for tok in stream if tok[0] == T_WHNFCACHE)
            res[cid] = (verdict, steps, ncache, nwhnf)
            print(f"[{name}] {cid:34s} {verdict!s:40s} steps={steps:5d} "
                  f"defcache_toks={ncache:3d} whnfcache_toks={nwhnf:3d} "
                  f"({time.perf_counter()-t0:.1f}s)", flush=True)
        del ctx
    return res


def report(offs: dict, ons: dict, jobs, groups, fam_expected=None):
    fails = 0
    print("\n=== verdict invariance table (steps may only go DOWN) ===")
    print(f"{'case':34s} {'oracle':30s} {'off':30s} {'on':30s} delta")
    expected = dict(fam_expected or {})
    for key in ("A", "Am"):
        for job in jobs.get(key, []):
            expected[job[0]] = job[3]
    for label, (_d, _c, _m, cases, orc) in groups.items():
        for cid, _, _ in cases:
            expected[cid] = orc[cid]
    for cid in list(offs) + [k for k in ons if k not in offs]:
        ov = expected.get(cid, "?")
        o, n = offs.get(cid), ons.get(cid)
        bad = []
        # RESCUE (layer p2, research-only since ADR 019): OFF timed out
        # under the finite cap and ON lands on the live oracle.
        rescue = (str(o[0]) == "timeout" and ov != "?"
                  and str(n[0]) == str(ov))
        if str(o[0]) != str(n[0]) and not rescue:
            bad.append("VERDICT-DIFF")
        if n[1] > o[1]:
            bad.append(f"STEPS-UP {o[1]}->{n[1]}")
        if ov != "?" and str(o[0]) != str(ov) and str(o[0]) != "timeout":
            bad.append(f"off-vs-oracle {ov}")
        if ov != "?" and str(n[0]) != str(ov) and str(n[0]) != "timeout":
            bad.append(f"on-vs-oracle {ov}")
        d = n[1] - o[1]
        fails += bool(bad)
        print(f"{cid:34s} {str(ov):30s} "
              f"{(str(o[0])+'/'+str(o[1]))[:30]:30s} "
              f"{(str(n[0])+'/'+str(n[1]))[:30]:30s} {d:+d} "
              f"{' '.join(bad) if bad else ('RESCUE' if rescue else 'OK')}")
    print(f"=== {'ALL OK' if fails == 0 else f'{fails} FAILURES'} ===")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="full", choices=["quick", "full"])
    ap.add_argument("--families", default="all",
                    choices=["all", "core", "m6"],
                    help="core: pre-M6 face (A/Am/G/brec); "
                         "m6: the four breach families (STR/CHK/MUT*/INF)")
    ap.add_argument("--layer", default="p1", choices=["p1", "p2"],
                    help="p1: baseline vs default (VM014_CACHE, P1) — the "
                         "DELIVERED contract (ADR 019); "
                         "p2: P1-only vs P1+P2 whnf memo — RESEARCH-ONLY, "
                         "P2 is dormant after ADR 019")
    args = ap.parse_args()
    if args.layer == "p2":
        print("NOTE: layer p2 is research-only — P2 withdrawn from "
              "acceptance by ADR 019 (string-corpus breach, stale-V1/X "
              "mislabeled keys).", flush=True)
    t0 = time.perf_counter()
    jobs, groups = (({}, {}) if args.families == "m6"
                    else collect_cases(args.cases))
    fams, fam_exp = (collect_fams(args.cases) if args.families != "core"
                     else ([], {}))
    print(f"corpora + live oracles collected {time.perf_counter()-t0:.0f}s",
          flush=True)
    if args.layer == "p1":
        offs = phase("off", False, False, jobs, groups, fams)
        gc.collect()   # M5 discipline: phase() locals (graph + last drivers)
        ons = phase("on", True, False, jobs, groups, fams)
    else:
        offs = phase("off", True, False, jobs, groups, fams)
        gc.collect()   # are released on return; the sweep breaks Expression
        ons = phase("on", True, True, jobs, groups, fams)
    gc.collect()       # DAG ref-cycles so two big graphs never coexist in RSS
    fails = report(offs, ons, jobs, groups, fam_exp)
    print(f"total {time.perf_counter()-t0:.0f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
