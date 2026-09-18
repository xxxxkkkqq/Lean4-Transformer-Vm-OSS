"""Card 009 (F chain): faithful-shape `brecOn` iota vs the real Lean 4.33.1
binary (acceptance oracle), on minimal per-family environments.

Scope and findings this test pins (docs/handoffs/005-F-iota.md):
  * `Nat.drecOn` / `Nat.drec` DO NOT EXIST in the judging binary (E0a): the
    drec half of card 009 collapses to that recorded fact, no cases.
  * `Nat.brecOn` has no primitive iota at all: it is pure
    delta(`brecOn` -> `.1` of `go` -> `Nat.rec` over `PProd` pairs) +
    generic iota + proj (kernel 4.35 `K/inductive.h:77-121` generic iota
    reads only recursor metadata; the `brecOn` value shape is
    `Lean/Meta/Constructions/BRecOn.lean`, dumped live).  Every judgement
    below runs on the GRAPH over faithful ENV values - the P7.5c-3
    pair-free reconstruction (`Nat.brecOn.real`) is deliberately NOT used.
  * The equation compiler leaves two artifacts at the export boundary that
    the ENV normalizer (`norm` below) must discharge, or the chain carries
    garbage into the graph (gap #2, root-caused by F4/F5):
      (a) non-dependent motive redexes inside `HAdd.hAdd` instance spines
          (`((fun _ => Nat) x)` at args 0/2) which `_norm_hbinop` alone
          misses (it only matches the closed form);
      (b) the PProd -> P2 convention mapping must respect the ACTUAL
          @-spine order.  Measured on v4.33.1 (elaborator probes,
          handoffs/005 F5-b02): `@Nat.casesOn` and `@PProd.casesOn`
          serialize as (motive, MAJOR, alts...), params first for PProd.
          `_pprod` therefore emits P2.casesOn in (motive, major, minor)
          and lets `_norm_elim_spine` perform the single swap into the
          toy table order (major, motive, minor); `_norm_elim_spine`
          rebuilds the head without levels, so `_relevel` restores the
          motive level the (toy-compiled) recursors declare.
    Section A asserts this data pipeline WITHOUT touching the graph; it is
    the test-side (route ii) half of gap #2 and must stay green.
  * Sections B/C then judge the faithful chains with the graph and diff
    against the oracle run live.  Historical gap ledger (005-F-iota memos):
    gap #2b (pair-component `UnitT =?= Nat` descent, D3/D4) closed in the
    F chain; gap #3 (stuck-rec Proj restick, D6) lived as the G4_d6
    KNOWN-GAP xfail until card 014 — the whnf memo (P2) plus the cap-1500
    measurement recharacterized it as legitimate-slow (converges True at
    1012 steps); G4_d6 removed per the XPASS protocol, ADR 018 postscript.

Run: setsid nohup env OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u \
       tests/test_brec_drec_iota_vs_lean.py > /tmp/brec_drec.log 2>&1 < /dev/null &
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import (
    App, Const, Lam, Pi, Let, BVar, Proj, Sort, LitNat, LParam, LZero,
    LSucc, LMax, LIMax, BI_DEFAULT,
)
from expr.tokens import Encoder, decode_closure
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from lean_vm.ref_vm import VMError
from reference import lean_ref
from reference.olean_export import (
    dump_env, json_to_expr, const_meta_for, _rewrite, _spine,
    _norm_elim_spine, _norm_num, _norm_hbinop,
)
from reference.toy_env import TOY_CONSTS, TOY_LEAN_DEFS, TOY_CTORS

# 1100 (was 720, was 600): the d4 precedent — 600->720 was set on 005 F8-02's
# linear step table (d4 needs ~700 steps at the fixed op-pace) while the
# engine (no such cap) completes it; same logic, same evidence standard, card
# 014 lead ruling 2026-09-17: d6 is legitimate-slow, NOT an unbounded ring —
# measured at cap 1500 it halts with verdict True (= live oracle): 1012 steps
# on the P1+P2 graph, 1070 on P1-only (/home/xkq/logs/014/
# whnf_result_m4_on_1500.json + m4_d6_{on,p1}_1500.log).  720 cut the trace
# mid-descent.  Cap only bounds the Python harness wall-clock budget; the
# acceptance criterion is verdict agreement with the kernel, never a step
# count.  Consumers read this constant (tests/test_defeq_cache_vs_lean.py
# run_d6; scripts/probe_014_invariance.py brec phase).
GRAPH_MAX_STEPS = 1100

# ── corpora (terms judged via named defs; expectations never pre-baked) ────
NAT_DEFS = r'''
axiom tq : Nat
def F1s : (n : Nat) → @Nat.below (fun (x : Nat) => Nat) n → Nat
  | n, _ => n.succ
def F2s : (n : Nat) → @Nat.below (fun (x : Nat) => Nat) n → Nat
  | 0, _ => 0
  | k+1, ⟨ih, _⟩ => ih + (k+1)
def F3s : (n : Nat) → @Nat.below (fun (x : Nat) => Nat) n → Nat
  | 0, _ => 100
  | 1, _ => 101
  | k+2, ⟨_, ⟨ih, _⟩⟩ => ih
noncomputable def d1 : Nat := @Nat.brecOn (fun (x : Nat) => Nat) 2 F1s
def e1 : Nat := 3
noncomputable def d2f : Nat := @Nat.brecOn (fun (x : Nat) => Nat) 2 F1s
def ef : Nat := 4
noncomputable def d3 : Nat := @Nat.brecOn (fun (x : Nat) => Nat) 2 F2s
def e3 : Nat := 3
noncomputable def d4 : Nat := @Nat.brecOn (fun (x : Nat) => Nat) 4 F3s
def e4 : Nat := 100
noncomputable def d5r : Nat := F1s 2 (@Nat.brecOn.go (fun (x : Nat) => Nat) 2 F1s).2
noncomputable def d6l : Nat := @Nat.brecOn (fun (x : Nat) => Nat) tq F1s
noncomputable def d6r : Nat := (@Nat.brecOn.go (fun (x : Nat) => Nat) tq F1s).1
noncomputable def d7r : Nat := F1s tq (@Nat.brecOn.go (fun (x : Nat) => Nat) tq F1s).2
'''
NAT_ROOTS = ("Nat Nat.below Nat.brecOn Nat.brecOn.go Nat.rec Nat.casesOn "
             "PProd PProd.mk PProd.casesOn PProd.rec PUnit PUnit.unit "
             "F1s F2s F3s tq d1 d2f d3 d4 d5r d6l d6r d7r e1 ef e3 e4").split()

LST_DEFS = r'''
inductive Lst where
  | nil : Lst
  | cons : Nat -> Lst -> Lst
def FLs : (t : Lst) → @Lst.below (fun (x : Lst) => Nat) t → Nat
  | Lst.nil, _ => 1
  | Lst.cons _ _, _ => 2
def FLr : (t : Lst) → @Lst.below (fun (x : Lst) => Nat) t → Nat
  | Lst.nil, _ => 0
  | Lst.cons _ _, ⟨ih, _⟩ => ih + 1
noncomputable def eL1 : Nat := @Lst.brecOn (fun (x : Lst) => Nat) Lst.nil FLs
def eL1R : Nat := 1
noncomputable def eL2 : Nat := @Lst.brecOn (fun (x : Lst) => Nat) (Lst.cons 1 Lst.nil) FLs
noncomputable def eL3 : Nat := @Lst.brecOn (fun (x : Lst) => Nat) (Lst.cons 2 (Lst.cons 1 Lst.nil)) FLr
def eLR : Nat := 2
def eLF : Nat := 3
'''
LST_ROOTS = ("Lst Lst.rec Lst.casesOn Lst.below Lst.brecOn Lst.brecOn.go "
             "FLs FLr eL1 eL1R eL2 eL3 eLR eLF "
             "PProd PProd.mk PProd.casesOn PProd.rec PUnit PUnit.unit "
             "Nat Nat.add").split()

# (id, left def, right def, expectation source)  expectation = live oracle.
NAT_CASES = [
    ("G3_d1_3", "d1", "e1"),        # brecOn 2 F1s = 3          (already supported)
    ("G3_d1_4", "d2f", "ef"),       # brecOn 2 F1s = 4          False control
    ("G3_d1_shadow", "d1", "d5r"),  # brecOn 2 F1s = F1s 2 (go 2 F1s).2
    ("G2_d3", "d3", "e3"),          # pair-destructure F2s      (gap #2/#2b subject)
    ("G2_d4", "d4", "e4"),          # nested-pair F3s           (gap #2/#2b subject)
    ("G4_d6", "d6l", "d6r"),        # gap #3 subject; green since card 014
    ("G4_d7", "d6l", "d7r"),        # mismatched restick        False control
]

# KNOWN-GAP xfail registry (card 009, 005 F15-08, ADR 018): cases the graph
# is known to diverge on, kept in the suite un-deleted.  A mismatched case
# here reports [XFAIL-KNOWN-GAP] and does NOT count as a divergence; an
# unexpected PASS reports [XPASS] and FAILS the run (the entry must then be
# removed — no silent drift in either direction).
KNOWN_GAPS = {
    # (empty — registry kept: the XPASS protocol below must fail a run whose
    # green case is still listed, and a plain FAIL must not silently become
    # xfail.  See ADR 018 postscript 2026-09-17.)
    # G4_d6 REMOVED per XPASS protocol (card 014, M5-02b, 2026-09-17): the
    # graph now agrees with lean.  The entry was registered on the belief
    # that d6 was a non-converging ring at cap 720; card 014 P2 whnf memo +
    # the cap-1500 measurement showed it converges legitimately — halt True
    # at step 1012 (P1+P2 graph) / 1070 (P1-only), verdict = live oracle —
    # and XPASS was proven under the 1100 cap (m5_brec_xpproof.log, run
    # 2026-09-17).  Removal is the registry's prescribed action on an
    # unexpected pass, not an assertion relaxation.
}
LST_CASES = [
    ("G5_eL1", "eL1", "eL1R"),      # non-Nat carrier, bh ignored
    ("G5_eL2", "eL2", "eLR"),       # cons carrier
    ("G5_eL3", "eL3", "eLR"),       # pair-destructure FLr
    ("G5_eL3_neg", "eL3", "eLF"),   # negative control
]

# ── export-boundary normalizer (route (ii): test side, zero graph change) ──

def _spec(l):
    if isinstance(l, LParam):
        # Fold dumped level params to LZero.  DO NOT "fix" this to
        # LSucc(LZero): the spec1 variant (005 F9/F10-02) was a residue of
        # the bvar off-by-one misdiagnosis (WRONG-env artifact retracted by
        # F10-01) and it regressed d6/d7 from fast-False to Timeout@600
        # (F10-03 bisection).  Arbitration f10_p5: lst is 4/4 green under
        # spec0 with identical step counts 118/158/460/458; revert ruled by
        # 005 F10-04, executed F11-01.  The level disagreement is immaterial
        # once the graph-side OP_IOTA extras fix (K/inductive.h:115-118)
        # holds: the x-pi arg comparison the fold used to hit is downstream
        # of the lost application and never fires again.
        return LZero()
    if isinstance(l, LSucc):
        return LSucc(_spec(l.l))
    if isinstance(l, LMax):
        return LMax(_spec(l.a), _spec(l.b))
    if isinstance(l, LIMax):
        return LIMax(_spec(l.a), _spec(l.b))
    return l


def _pprod(e):
    """PProd/PUnit -> toy P2/UnitT convention.  The @-spine order of
    PProd.casesOn is (α, β, motive, major, minor) (measured on v4.33.1);
    emit (motive, major, minor) so the single _norm_elim_spine swap below
    lands on the toy table order (major, motive, minor)."""
    if isinstance(e, Proj):
        return Proj("P2", e.idx, e.child) if e.sname == "PProd" else e
    h, a = _spine(e)
    if isinstance(h, Const):
        n = h.name
        if n == "PProd" and len(a) == 2:
            return Const("P2")
        if n == "PProd.mk" and len(a) == 4:
            return App(App(Const("P2.mk"), a[2]), a[3])
        if n == "PUnit" and not a:
            return Const("UnitT")
        if n == "PUnit.unit" and not a:
            return Const("UnitT.mk")
        if n == "PProd.casesOn" and len(a) >= 5:
            mot, major, minor = a[2], a[3], a[4]
            return App(App(App(Const("P2.casesOn"), mot), major), minor)
    return e


def _occurs(body, d=0):
    if isinstance(body, BVar):
        return body.idx == d
    if isinstance(body, App):
        return _occurs(body.fn, d) or _occurs(body.arg, d)
    if isinstance(body, (Lam, Pi)):
        return _occurs(body.domain, d) or _occurs(body.body, d + 1)
    if isinstance(body, Let):
        return (_occurs(body.domain, d) or _occurs(body.value, d)
                or _occurs(body.body, d + 1))
    if isinstance(body, Proj):
        return _occurs(body.child, d)
    return False


def nondep_beta(e):
    """Reduce App(Lam, arg) whose binder is unused in the body: the
    equation compiler's non-dependent motive instantiations.  Semantics
    preserving; lets _norm_hbinop match its closed form."""
    def go(x):
        if isinstance(x, App) and isinstance(x.fn, Lam) \
                and not _occurs(x.fn.body, 0):
            return x.fn.body
        return x
    return _rewrite(e, go)


def _relevel(e):
    """_norm_elim_spine rebuilds swapped heads as Const(name) with empty
    levels; the recursors it touches (toy-compiled from TOY_LEAN_DEFS) each
    declare exactly one motive lparam."""
    def go(x):
        if isinstance(x, Const) and x.levels == () and x.name in \
                ("P2.casesOn", "Nat.casesOn", "Bool.casesOn"):
            return Const(x.name, (LZero(),))
        return x
    return _rewrite(e, go)


# ── use-site level instantiation of injected polymorphic constants ─────────

def _has_lparam(l):
    if isinstance(l, LParam):
        return True
    if isinstance(l, LSucc):
        return _has_lparam(l.l)
    if isinstance(l, (LMax, LIMax)):
        return _has_lparam(l.a) or _has_lparam(l.b)
    return False


def _subst_lvl(l, m):
    if isinstance(l, LParam):
        return m.get(l.name, l)
    if isinstance(l, LSucc):
        return LSucc(_subst_lvl(l.l, m))
    if isinstance(l, LMax):
        return LMax(_subst_lvl(l.a, m), _subst_lvl(l.b, m))
    if isinstance(l, LIMax):
        return LIMax(_subst_lvl(l.a, m), _subst_lvl(l.b, m))
    return l


def _subst_use(x, m):
    if isinstance(x, Const):
        return Const(x.name, tuple(_subst_lvl(l, m) for l in x.levels))
    if isinstance(x, Sort):
        return Sort(_subst_lvl(x.level, m))
    return x


def _concrete_use_sites(dump, name, arity):
    """Distinct fully-concrete level tuples of `name` across every dumped
    ty/val (user defs carry the elaborator's real use-site levels)."""
    found = set()

    def go(x):
        if isinstance(x, Const) and x.name == name and len(x.levels) == arity \
                and not any(_has_lparam(l) for l in x.levels):
            found.add(x.levels)
        return x
    for d in dump.values():
        for part in ("ty", "val"):
            if d[part] is not None:
                _rewrite(d[part], go)
    return found


def _instantiate_dump(dump):
    """Emulate instantiate_value_lparams (K/instantiate.cpp:248-254): the
    kernel delta-unfolds `c@{lv}` by substituting c's univ params with lv
    INSIDE the value; the graph replays values monomorphically
    (build_vm.py:1273-1284, no level instantiation - D13/D14 only touch
    declared TYPES), so the single instantiation the corpus uses must be
    baked into the ENV value (005 F11-03: d6's go@{0}-vs-@{1} head split).
    An entry is rewritten only when all its concrete use sites agree on one
    tuple; parametric inner uses become concrete by propagation (enclosing
    constants instantiate first).  No/ambiguous instantiation leaves the
    LParams for the _spec fold (adjudicated behavior, unchanged)."""
    todo = sorted(n for n in dump if dump[n]["up"])
    for _ in range(2 * len(todo) + 2):
        changed = False
        for n in todo:
            up = dump[n]["up"]
            tpls = _concrete_use_sites(dump, n, len(up))
            if len(tpls) != 1:
                continue
            m = dict(zip(up, tpls.pop()))
            for part in ("ty", "val"):
                e = dump[n][part]
                if e is None:
                    continue
                ne = _rewrite(e, lambda x: _subst_use(x, m))
                if ne != e:
                    dump[n][part] = ne
                    changed = True
        if not changed:
            return
    raise AssertionError("use-site instantiation did not reach a fixpoint")


def norm(e):
    e = _rewrite(e, lambda x: Const(x.name, tuple(_spec(l) for l in x.levels))
                 if isinstance(x, Const) and x.levels else
                 (Sort(_spec(x.level)) if isinstance(x, Sort) else x))
    e = _rewrite(e, lambda y: _norm_elim_spine(
        _pprod(_norm_hbinop(_norm_num(y)))))
    e = _relevel(e)
    return _rewrite(nondep_beta(e), _norm_hbinop)


# ── env / graph helpers ─────────────────────────────────────────────────────

def build_group(defs, roots):
    dump = dump_env(defs, roots,
                    path=f"/tmp/vm_009_dump_{roots[0]}.lean")
    _instantiate_dump(dump)
    src = list(TOY_CONSTS)
    toyset = {n for n, _, _ in src}
    for i, (n, t, v) in enumerate(src):
        if n in ("Nat.below", "Nat.brecOn") and n in dump:
            src[i] = (n, norm(dump[n]["ty"]), norm(dump[n]["val"]))
    extra = [(n, norm(dump[n]["ty"]), norm(dump[n]["val"]))
             for n in sorted(dump) if n not in toyset]
    consts = src + extra
    toy_dump = dump_env(TOY_LEAN_DEFS, sorted(toyset),
                        path="/tmp/vm_001_dump_toy.lean")
    merged = dict(toy_dump)
    merged.update(dump)
    meta = const_meta_for(consts, merged)
    return consts, meta, dump


def warm_prefix(consts, meta, graph, outputs):
    enc0 = Encoder(consts, is_ctor=TOY_CTORS, const_meta=meta)
    drv0 = StepDriver(enc0.b, graph, outputs)
    env_len = len(drv0.names)
    drv0._eval.sync(drv0.names)
    return env_len, drv0._eval.vals, drv0._eval.lookup_history


def run_defeq(consts, meta, graph, outputs, warm, left, right):
    env_len, warm_vals, warm_hist = warm
    enc = Encoder(consts, is_ctor=TOY_CTORS, const_meta=meta)
    drv = StepDriver(enc.b, graph, outputs)
    drv._eval.vals = list(warm_vals)
    drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
    tp = enc.encode_term(Const(left))
    sp = enc.encode_term(Const(right))
    v = drv.run_defeq(tp, 0, sp, 0, max_steps=GRAPH_MAX_STEPS)
    return bool(v[0])


# ── sections ────────────────────────────────────────────────────────────────

def section_a() -> list[str]:
    """Data pipeline invariants, no graph: the route-(ii) normalization is
    the load-bearing claim; assert it on the live dump."""
    fails = []
    dump = dump_env(NAT_DEFS, NAT_ROOTS, path="/tmp/vm_009_dump_a.lean")
    # the add redex lives on the wrapper F2s; the pair-destructure on
    # F2s.match_1 (equation compiler splits them) — assert per carrier.
    f2s = norm(dump["F2s"]["val"])
    m2s = norm(dump["F2s.match_1"]["val"])
    h = [x for x in _collect_heads(f2s) if x == "HAdd.hAdd"]
    if h:
        fails.append(f"[A redex] F2s keeps {len(h)} HAdd.hAdd spines after norm")
    if not [x for x in _collect_heads(f2s) if x == "Nat.add"]:
        fails.append("[A redex] F2s lost its Nat.add (rewrite did not fire?)")
    if not [x for x in _collect_heads(m2s) if x == "P2.casesOn"]:
        fails.append("[A order] no P2.casesOn application in F2s.match_1")
    seen_caseson = []
    _scan_caseson_spines(m2s, seen_caseson)
    for nargs, lv in seen_caseson:
        if nargs != 3:
            fails.append(f"[A order] P2.casesOn spine has {nargs} args, want 3")
        if lv != (LZero(),):
            fails.append(f"[A level] P2.casesOn head levels {lv}, want (LZero(),)")
    # toy-convention check: first positional arg of each mapped app is the
    # MAJOR (whnf target), never the motive: motive is a Lam in the corpus.
    majors = []
    _scan_majors(m2s, majors)
    for m in majors:
        if isinstance(m, Lam):
            fails.append("[A order] P2.casesOn arg0 is the motive (swap lost)")
    if not majors:
        fails.append("[A order] no complete P2.casesOn spine scanned")
    return fails


def _collect_heads(e):
    out = []

    def go(x):
        if isinstance(x, App):
            h, _ = _spine(x)
            if isinstance(h, Const):
                out.append(h.name)
        return x
    _rewrite(e, go)
    return out


def _scan_caseson_spines(e, sink):
    def go(x):
        if isinstance(x, App):
            h, a = _spine(x)
            if isinstance(h, Const) and h.name == "P2.casesOn":
                if len(a) == 3:
                    sink.append((len(a), h.levels))
        return x
    _rewrite(e, go)


def _scan_majors(e, sink):
    def go(x):
        if isinstance(x, App):
            h, a = _spine(x)
            if isinstance(h, Const) and h.name == "P2.casesOn" and len(a) == 3:
                sink.append(a[0])
        return x
    _rewrite(e, go)


def run_group(label, defs, roots, cases):
    fails, lines = [], []
    consts, meta, _dump = build_group(defs, roots)
    graph, outputs = build_group.G
    warm = warm_prefix(consts, meta, graph, outputs)
    oracle = lean_ref.run_oracle_mixed(defs, [("DEFEQ", l, r)
                                              for _, l, r in cases])
    for (cid, l, r), (_k, ov) in zip(cases, oracle):
        try:
            got = run_defeq(consts, meta, graph, outputs, warm, l, r)
        except VMError as ex:
            got = f"rej code={ex.code}"
        except Exception as ex:
            got = f"{type(ex).__name__}: {ex}"
        ok = (got == bool(ov))
        gap = KNOWN_GAPS.get(cid)
        if ok:
            tag = "XPASS" if gap else "PASS"
            lines.append(f"  [{tag}] D {cid}: {l}=?={r}  "
                         f"oracle={ov}  graph={got}")
            if gap:
                fails.append(f"[{label} {cid}] XPASS: known-gap entry must "
                             f"be removed (graph now agrees with lean)")
        elif gap:
            lines.append(f"  [XFAIL-KNOWN-GAP] D {cid}: {l}=?={r}  "
                         f"oracle={ov}  graph={got}\n"
                         f"      known gap: {gap}")
        else:
            lines.append(f"  [{'PASS' if ok else 'FAIL'}] D {cid}: {l}=?={r}  "
                         f"oracle={ov}  graph={got}")
            fails.append(f"[{label} {cid}] graph={got!r} lean={bool(ov)}")
    return fails, lines


def main() -> int:
    t0 = time.perf_counter()
    fails = []
    print("A  export-boundary normalizer (route ii) invariants")
    fa = section_a()
    fails += fa
    print(f"   {'OK (no redex HAdd left; P2.casesOn toy order + 1 level)'
           if not fa else 'FAIL'}")
    build_group.G = build_step_graph()
    for label, defs, roots, cases in (
            ("B nat", NAT_DEFS, NAT_ROOTS, NAT_CASES),
            ("C lst", LST_DEFS, LST_ROOTS, LST_CASES)):
        print(f"{label}  faithful brecOn DEFEQ vs oracle "
              f"(graph max_steps={GRAPH_MAX_STEPS})")
        try:
            fg, lines = run_group(label, defs, roots, cases)
        except Exception as ex:
            fg = [f"[{label}] group aborted: {type(ex).__name__}: {ex}"]
            lines = [f"  [FAIL] {fg[-1]}"]
        print("\n".join(lines))
        fails += fg
    for m in fails:
        print(f"  [NOTE] {m}")
    ok = not fails
    print(f"\n=== brecOn/drecOn faithful iota vs lean: "
          f"{'OK' if ok else 'FAIL'} ({len(fails)} divergences) "
          f"{time.perf_counter()-t0:.0f}s ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
