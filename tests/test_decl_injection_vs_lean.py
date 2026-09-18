"""Card 010 G02 differential test: declaration-kind injection + theorem
`is_prop` reject code 8, vs the real Lean 4 kernel.

Oracle = `~/.elan/bin/lean` (v4.33.1) through `reference/lean_ref.run_kdecl_oracle`
(VM_SPEC §12.5(B): `#KDECL` → `Lean.Kernel.Environment.addDecl`, i.e. the real
C++ kernel's `add_{axiom,definition,theorem,opaque}` dispatch — the only
channel that can even *express* a theorem whose type is not a Prop).  Every
expected verdict/class is produced by that live binary at run time; nothing is
precomputed into this file (acceptance rule 2).

Sections
  a0    carrier-layout drift guard: step_driver (writer) vs build_vm (reader).
  guard CARRIER IDLENESS (ADR 020 decision A.3): the TASK_CHECK anchor's E2
        slot must be free.  For the whole test_check_e2e corpus, run every case
        twice — `kinds=None` (E2=0, legacy) vs a non-zero sentinel kind — and
        require verdict, reject code AND micro-step count to match verbatim.
        G02_LEGACY_BUILD_VM=<path> loads a pre-change copy of
        lean_vm/build_vm.py under that module name: that is how the "graph and
        weights untouched" leg of the proof is captured (heartbeat S1 in
        docs/handoffs/006-G-injection.md).
  bcd   kind gate (theorem-only), per-anchor threading over CHECK chains, arm
        order vs code 5, and the non-normalized level forms (ADR 020 decision
        B).  Row set = every judgment surface this beat added.

Run:  OMP_NUM_THREADS=3 python3 -u tests/test_decl_injection_vs_lean.py
Dev subset (one graph case ≈ 16 s on this box; a full run is canary-class):
  G02_ONLY=guard G02_GUARD_LIMIT=2  python3 -u tests/... (first 2 guard cases)
  G02_ONLY=guard                    python3 -u tests/test_decl_injection_vs_lean.py
  G02_ONLY=bcd,thm_nat      python3 -u tests/test_decl_injection_vs_lean.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder
from expr.model import (
    Const, App, Pi, Sort, LitNat, LSucc, LZero, LMax, LIMax, BI_DEFAULT,
)
from lean_vm.ref_vm import VMError
from lean_vm import step_driver as sd_check
from lean_vm.step_driver import (
    StepDriver, check_e2, CHECK_E2_STRIDE, CHECK_MODE_SAFE,
    CHECK_KIND_UNSPECIFIED, CHECK_KIND_AXIOM, CHECK_KIND_DEFINITION,
    CHECK_KIND_THEOREM, CHECK_KIND_OPAQUE,
)
from reference import lean_ref
from reference.olean_export import import_env, dump_env
from tests.test_olean_export import TARGET_DEFS, ROOTS
from tests.test_check_e2e import CHECK_CASES, CASE, SEQUENCES

# reference/lean_ref.py + olean_export write FIXED /tmp paths, so two suites
# running at once clobber each other's oracle files (AGENTS.md, card 004
# note).  This suite's env dump is per-PID, so a pre/post baseline pair can
# run side by side.
DUMP_PATH = os.environ.get("G02_DUMP_PATH",
                           f"/tmp/g02_decl_inj_dump_{os.getpid()}.lean")

NAT = Const("Nat")
TRUE = Const("True")
TRIVIAL = Const("True.intro")
TYPE1 = Sort(LSucc(LZero()))
# un-normalized level forms (kernel normalizes_to_zero accepts both)
SORT_IMAX_10 = Sort(LIMax(LSucc(LZero()), LZero()))
SORT_MAX_00 = Sort(LMax(LZero(), LZero()))

# ── oracle-side inputs ──────────────────────────────────────────────────────
# The frontend normalizes every level written in source, so
# `def d : Sort (imax 1 0) := True` reaches the kernel already stored as
# `Sort zero` (measured 2026-09-19 via reference/olean_export.dump_env:
# ty=Sort(level=LZero())).  To get a constant whose STORED type really is a
# non-normalized sort — which is what `is_prop`/`normalizes_to_zero` keys on —
# the two `injX_*` defs below are built as raw `Expr.sort (Level…)` terms and
# added with Lean.addDecl.  This is an input construction, not a result: the
# verdicts still come from the kernel.  `injD_imax`/`injD_max` are the
# source-written twins kept in the corpus as that normalization evidence.
RAW_DEFS = """\
def injRawImax : Lean.Declaration := .defnDecl { name := `injX_imax, levelParams := [], type := Lean.Expr.sort (Lean.Level.imax (Lean.Level.succ Lean.Level.zero) Lean.Level.zero), value := Lean.mkConst ``True, hints := Lean.ReducibilityHints.regular 0, safety := Lean.DefinitionSafety.safe }
def injRawMax : Lean.Declaration := .defnDecl { name := `injX_max, levelParams := [], type := Lean.Expr.sort (Lean.Level.max Lean.Level.zero Lean.Level.zero), value := Lean.mkConst ``True, hints := Lean.ReducibilityHints.regular 0, safety := Lean.DefinitionSafety.safe }
run_cmd do
  liftCoreM <| Lean.addDecl injRawImax
  liftCoreM <| Lean.addDecl injRawMax
"""
INJ_DEFS = """\
def injD_imax : Sort (imax 1 0) := True
def injD_max : Sort (max 0 0) := True
"""
ALL_DEFS = TARGET_DEFS + "\n" + RAW_DEFS + INJ_DEFS
MY_ROOTS = ROOTS + ["injX_imax", "injX_max", "injD_imax", "injD_max"]

# Lean-side declaration constructors.  The name is per case so addDecl never
# sees a duplicate.
_THM = ".thmDecl {{ name := `{}, levelParams := [], type := {}, value := {} }}"
_AXM = ".axiomDecl {{ name := `{}, levelParams := [], type := {}, isUnsafe := false }}"
_DEF = (".defnDecl {{ name := `{}, levelParams := [], type := {}, value := {}, "
        "hints := ReducibilityHints.regular 0, safety := DefinitionSafety.safe }}")
_OPA = (".opaqueDecl {{ name := `{}, levelParams := [], type := {}, value := {}, "
        "isUnsafe := false }}")
# Lean-side expression splices
E_TRUE = "mkConst ``True"
E_TRIVIAL = "mkConst ``True.intro"
E_NAT = "mkConst ``Nat"
E_TWO = "mkNatLit 2"
E_DBL21 = "(mkApp (mkConst ``E_dbl) (mkNatLit 21))"
E_ARROW = "(mkForall `x BinderInfo.default (mkConst ``Nat) (mkConst ``True))"
E_ARROW_T = "(mkForall `x BinderInfo.default (mkConst ``Nat) (mkConst ``Nat))"
E_INC = "(mkConst ``E_inc)"
E_SORT1 = "(Expr.sort (Level.succ Level.zero))"
E_SORT_IMAX = "(Expr.sort (Level.imax (Level.succ Level.zero) Level.zero))"
E_SORT_MAX00 = "(Expr.sort (Level.max Level.zero Level.zero))"
E_X_IMAX = "(mkConst ``injX_imax)"
E_X_MAX00 = "(mkConst ``injX_max)"

# graph reject code ↔ kernel exception class (VM_SPEC §7.4 + WP7-G rows)
CLASS_OF_CODE = {0: "accept", 1: "declTypeMismatch", 4: "typeMismatch",
                 5: "typeExpected", 6: "declHasFVars", 7: "unsafeConstUse",
                 8: "thmTypeIsNotProp"}
CODE_OF_CLASS = {"OK": 0, "typeExpected": 5, "thmTypeIsNotProp": 8,
                 "declTypeMismatch": 1}

# ── KNOWN-GAP xfail registry (card 009 protocol, ADR 018 + ADR 020 B) ───────
# A registered case that still diverges reports [XFAIL-KNOWN-GAP] and does NOT
# fail the run; a registered case that starts AGREEING reports [XPASS] and
# fails the run (the entry must then be removed — no silent drift either way).
KNOWN_GAPS = {
    # G3 on a non-normalized level (ADR 020 B).  The kernel's
    # normalizes_to_zero (K/level.cpp:174-186) accepts imax(_,0) and max(0,0);
    # the graph reuses the syntactic root-vs-KL_ZERO judge (pl_prop,
    # build_vm.py:4451-4457), so the theorem is falsely rejected with code 8.
    # Universe normalization = matrix D1/D2, card 012.
    "thm_imax": "kernel normalizes_to_zero(imax(succ 0, 0))=true → accept; "
                "graph syntactic KL_ZERO root compare → reject 8 "
                "(D2 gap, card 012; ADR 020 B)",
    "thm_max00": "kernel normalizes_to_zero(max(0,0))=true → accept; graph "
                 "syntactic KL_ZERO root compare → reject 8 "
                 "(D1/D2 gap, card 012; ADR 020 B)",
}

# ── corpus rows ─────────────────────────────────────────────────────────────
# (cid, kind_code, graph type, graph value | None (None = anchor X=0, the
#  G5 no-value/axiom convention), oracle constructor, type splice, value splice)
ROWS = [
    # gate passes on a real Prop — the accept leg of G3
    ("thm_true", CHECK_KIND_THEOREM, TRUE, TRIVIAL, _THM, E_TRUE, E_TRIVIAL),
    # gate fires: Nat : Type 1
    ("thm_nat", CHECK_KIND_THEOREM, NAT, LitNat(2), _THM, E_NAT, E_TWO),
    # gate fires: (Nat → Nat) : Type — a Pi whose BODY is not a Prop
    ("thm_pi_type", CHECK_KIND_THEOREM, Pi("x", BI_DEFAULT, NAT, NAT),
     Const("E_inc"), _THM, E_ARROW_T, E_INC),
    # gate fires and PASSES: `Nat → True` IS a Prop (the kernel closes Prop
    # under dependent product), measured 2026-09-19 — addDecl gets past
    # is_prop and fails on the value instead, so the graph must report the
    # value mismatch and never 8.
    ("thm_arrow", CHECK_KIND_THEOREM, Pi("x", BI_DEFAULT, NAT, TRUE), TRIVIAL,
     _THM, E_ARROW, E_TRIVIAL),
    # gate fires: the declared type is itself a sort (Type : Sort 2)
    ("thm_sort", CHECK_KIND_THEOREM, TYPE1, NAT, _THM, E_SORT1, E_NAT),
    # kinds 1/2/4 on the SAME non-Prop type: gate must NOT fire
    ("axm_nat", CHECK_KIND_AXIOM, NAT, None, _AXM, E_NAT, None),
    ("def_nat", CHECK_KIND_DEFINITION, NAT, LitNat(2), _DEF, E_NAT, E_TWO),
    ("opa_nat", CHECK_KIND_OPAQUE, NAT, LitNat(2), _OPA, E_NAT, E_TWO),
    # kind 2 on a Prop type also accepted (gate is theorem-only, not Prop-only)
    ("def_true", CHECK_KIND_DEFINITION, TRUE, TRIVIAL, _DEF, E_TRUE, E_TRIVIAL),
    # arm order: ensure_sort (5) runs BEFORE is_prop (8) — `2` is not a type,
    # so the kernel reports typeExpected and the graph must NOT report 8
    ("thm_typeexpected", CHECK_KIND_THEOREM, LitNat(2), TRIVIAL, _THM, E_TWO,
     E_TRIVIAL),
    # legacy corpus, now tagged theorem: accept must flip to 8 (data-driven)
    ("thm_dbl_nat", CHECK_KIND_THEOREM, NAT, App(Const("E_dbl"), LitNat(21)),
     _THM, E_NAT, E_DBL21),
    # ADR 020 B: non-normalized level forms
    ("thm_imax", CHECK_KIND_THEOREM, Const("injX_imax"), TRIVIAL, _THM,
     E_X_IMAX, E_TRIVIAL),
    ("thm_max00", CHECK_KIND_THEOREM, Const("injX_max"), TRIVIAL, _THM,
     E_X_MAX00, E_TRIVIAL),
    # control for the two above: same type/value, kind = definition → the rest
    # of the CHECK chain (value infer + defeq) must still accept
    ("def_imax", CHECK_KIND_DEFINITION, Const("injX_imax"), TRIVIAL, _DEF,
     E_X_IMAX, E_TRIVIAL),
    # a raw un-normalized sort used DIRECTLY as the declared type: the kernel's
    # infer(Sort l) normalizes to a non-zero level, so both sides reject
    ("thm_sortraw_imax", CHECK_KIND_THEOREM, SORT_IMAX_10, TRIVIAL, _THM,
     E_SORT_IMAX, E_TRIVIAL),
    ("thm_sortraw_max00", CHECK_KIND_THEOREM, SORT_MAX_00, TRIVIAL, _THM,
     E_SORT_MAX00, E_TRIVIAL),
]
ROWS_BY_ID = {r[0]: r for r in ROWS}
B_ROWS = [c for c, *_ in ROWS if c not in
          ("thm_imax", "thm_max00", "def_imax", "thm_sortraw_imax",
           "thm_sortraw_max00")]
D_ROWS = ["thm_imax", "thm_max00", "def_imax", "thm_sortraw_imax",
          "thm_sortraw_max00"]

# Multi-decl CHECK chains: kinds are per anchor, so a threading bug shows up
# as an accept/reject flip, not merely a code change.
CHAINS = [
    ("chain_ok_mixed", [("def_nat", CHECK_KIND_DEFINITION),
                        ("thm_true", CHECK_KIND_THEOREM)]),
    ("chain_ok_axm_first", [("axm_nat", CHECK_KIND_AXIOM),
                            ("thm_true", CHECK_KIND_THEOREM)]),
    ("chain_reject_second", [("thm_true", CHECK_KIND_THEOREM),
                             ("thm_nat", CHECK_KIND_THEOREM)]),
    ("chain_reject_first", [("thm_pi_type", CHECK_KIND_THEOREM),
                            ("def_true", CHECK_KIND_DEFINITION)]),
]

# sentinel kind for the guard: non-zero (really exercises the slot) and not the
# theorem kind (so it must stay inert).
SENTINEL_KIND = CHECK_KIND_AXIOM

_GRAPH_BUILDER: list = []


def _load_graph_builder():
    """(build_step_graph, source-label), cached; honours G02_LEGACY_BUILD_VM."""
    if _GRAPH_BUILDER:
        return _GRAPH_BUILDER[0], _GRAPH_BUILDER[1]
    legacy = os.environ.get("G02_LEGACY_BUILD_VM")
    if legacy:
        spec = importlib.util.spec_from_file_location("lean_vm.build_vm",
                                                      legacy)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["lean_vm.build_vm"] = mod
        spec.loader.exec_module(mod)
        _GRAPH_BUILDER.extend([mod.build_step_graph, f"legacy copy {legacy}"])
    else:
        from lean_vm.build_vm import build_step_graph
        _GRAPH_BUILDER.extend([build_step_graph, "in-tree build_vm"])
    return _GRAPH_BUILDER[0], _GRAPH_BUILDER[1]


def _graph_check(consts, ctors, items, kinds):
    """One graph run over a declaration list.  items: [(type, value|None)]
    (value None = anchor X = 0, the G5 no-value convention).
    Returns (accepted, reject code (0 when accepted), micro-steps)."""
    build_step_graph, _ = _load_graph_builder()
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    decls = [(enc.encode_term(t), enc.encode_term(v) if v is not None else 0)
             for t, v in items]
    drv = StepDriver(enc.b, graph, outputs)
    try:
        drv.run_check(decls, kinds=kinds)
        return True, 0, drv.steps
    except VMError as ex:
        return False, ex.code, drv.steps


def _fmt(acc, code, steps):
    return (f"accept={acc} code={code}({CLASS_OF_CODE.get(code, '?')}) "
            f"steps={steps}")


def build_oracle() -> dict[str, str]:
    """One live `lean` batch run: one #KDECL per corpus row."""
    cases = []
    for i, (cid, _kind, _t, _v, tmpl, t_splice, v_splice) in enumerate(ROWS):
        name = f"g02s{i}_{cid}"
        if v_splice is None:
            cases.append((cid, tmpl.format(name, t_splice)))
        else:
            cases.append((cid, tmpl.format(name, t_splice, v_splice)))
    cls = lean_ref.run_kdecl_oracle(ALL_DEFS, cases)
    return dict(zip([c for c, _ in cases], cls))


# ── sections ────────────────────────────────────────────────────────────────
def section_a0(fails, lines):
    """Writer/reader layout agreement + check_e2 unit behaviour."""
    from lean_vm import build_vm as bv
    pairs = [("CHECK_E2_STRIDE", bv.CHECK_E2_STRIDE, CHECK_E2_STRIDE),
             ("CHECK_KIND_UNSPECIFIED", bv.CHECK_KIND_UNSPECIFIED,
              CHECK_KIND_UNSPECIFIED),
             ("CHECK_KIND_AXIOM", bv.CHECK_KIND_AXIOM, CHECK_KIND_AXIOM),
             ("CHECK_KIND_DEFINITION", bv.CHECK_KIND_DEFINITION,
              CHECK_KIND_DEFINITION),
             ("CHECK_KIND_THEOREM", bv.CHECK_KIND_THEOREM, CHECK_KIND_THEOREM),
             ("CHECK_KIND_OPAQUE", bv.CHECK_KIND_OPAQUE, CHECK_KIND_OPAQUE),
             ("CHECK_MODE_SAFE", bv.CHECK_MODE_SAFE, CHECK_MODE_SAFE),
             ("CHECK_MODE_UNSAFE", bv.CHECK_MODE_UNSAFE,
              sd_check.CHECK_MODE_UNSAFE)]
    for name, gval, dval in pairs:
        tag = "PASS" if gval == dval else "FAIL"
        lines.append(f"  [{tag}] a0 {name}: graph={gval} driver={dval}")
        if gval != dval:
            fails.append(f"[a0 {name}] layout drift graph={gval} "
                         f"driver={dval}")
    for kind, mode, want in [
            (CHECK_KIND_UNSPECIFIED, CHECK_MODE_SAFE, 0),
            (CHECK_KIND_THEOREM, CHECK_MODE_SAFE, CHECK_KIND_THEOREM),
            (CHECK_KIND_THEOREM, 1, CHECK_KIND_THEOREM + CHECK_E2_STRIDE),
            (CHECK_KIND_AXIOM, 1, CHECK_KIND_AXIOM + CHECK_E2_STRIDE)]:
        got = check_e2(kind, mode)
        tag = "PASS" if got == want else "FAIL"
        lines.append(f"  [{tag}] a0 check_e2(kind={kind}, mode={mode}) = {got} "
                     f"(want {want})")
        if got != want:
            fails.append(f"[a0 check_e2 {kind},{mode}] got {got} want {want}")
    for bad in (-1, 5, "3", True):
        try:
            check_e2(bad)
        except ValueError:
            lines.append(f"  [PASS] a0 check_e2({bad!r}) raises ValueError")
        else:
            lines.append(f"  [FAIL] a0 check_e2({bad!r}) accepted")
            fails.append(f"[a0 check_e2 {bad!r}] accepted, must reject")
    try:
        check_e2(CHECK_KIND_THEOREM, 2)
    except ValueError:
        lines.append("  [PASS] a0 check_e2(mode=2) raises ValueError")
    else:
        lines.append("  [FAIL] a0 check_e2(mode=2) accepted")
        fails.append("[a0 check_e2 mode=2] accepted, must reject")


def section_guard(fails, lines, consts, ctors):
    """CARRIER IDLENESS over the whole check_e2e corpus: the sentinel-kind run
    must match the legacy (kinds=None) run verbatim in verdict, code and
    micro-step count."""
    _, src = _load_graph_builder()
    # CHECK_CASES rows are (cid, type_src, val_src, type_Expr, val_Expr)
    cases = [(cid, [(te, ve)]) for cid, _ts, _vs, te, ve in CHECK_CASES]
    cases += [(cid, [(CASE[m][2], CASE[m][3]) for m in members])
              for cid, members in SEQUENCES]
    limit = int(os.environ.get("G02_GUARD_LIMIT", "0"))
    if limit:
        cases = cases[:limit]   # dev-loop affordance only; deliverable = full set
    for cid, items in cases:
        base = _graph_check(consts, ctors, items, None)
        sent = _graph_check(consts, ctors, items,
                            [SENTINEL_KIND] * len(items))
        tag = "PASS" if base == sent else "FAIL"
        lines.append(f"  [{tag}] guard {cid}: kinds=None {_fmt(*base)} | "
                     f"kinds=[{SENTINEL_KIND}] (E2={check_e2(SENTINEL_KIND)}) "
                     f"{_fmt(*sent)}"
                     + ("" if base == sent else "   <-- CARRIER NOT IDLE"))
        if base != sent:
            fails.append(f"[guard {cid}] carrier E2 not idle: "
                         f"None={base} sentinel={sent}")
    lines.append(f"  (guard: graph from {src}; {len(cases)} corpus cases × 2 "
                 f"runs)")


def _oracle_line(oracle, fails, lines, label, cid):
    cls = oracle.get(cid)
    if cls is None:
        lines.append(f"  [FAIL] {label} {cid}: oracle line missing")
        fails.append(f"[{label} {cid}] no oracle line (lean emitted nothing)")
        return
    _cid, kind, t, v, _tmpl, _ts, _vs = ROWS_BY_ID[cid]
    acc, code, steps = _graph_check(_CTX[0], _CTX[1], [(t, v)], [kind])
    want = CODE_OF_CLASS.get(cls, -1)
    agree = code == want
    gap = KNOWN_GAPS.get(cid)
    if agree and gap:
        lines.append(f"  [XPASS] {label} {cid}: oracle={cls} "
                     f"graph={_fmt(acc, code, steps)}")
        fails.append(f"[{label} {cid}] XPASS: known-gap entry must be removed "
                     f"(graph now agrees with lean)")
    elif agree:
        lines.append(f"  [PASS] {label} {cid}: oracle={cls} "
                     f"graph={_fmt(acc, code, steps)}")
    elif gap:
        lines.append(f"  [XFAIL-KNOWN-GAP] {label} {cid}: oracle={cls} "
                     f"graph={_fmt(acc, code, steps)}\n"
                     f"      known gap: {gap}")
    else:
        lines.append(f"  [FAIL] {label} {cid}: oracle={cls} "
                     f"graph={_fmt(acc, code, steps)} "
                     f"(class→code {cls}->{want}, got {code})")
        fails.append(f"[{label} {cid}] graph code={code} "
                     f"({_fmt(acc, code, steps)}) but lean class={cls}")


_CTX: tuple = ()


def section_bcd(fails, lines, consts, ctors, oracle, want_rows):
    """Kind gate (B), non-normalized level forms (D), chain threading (C)."""
    global _CTX
    _CTX = (consts, ctors)
    # The unspecified kind (0 — what `kinds=None` writes) must keep the gate
    # COMPLETELY inert, proven on the sharpest shape: a non-Prop theorem type
    # is accepted under kind 0 and rejected with 8 under kind 3.
    off = _graph_check(consts, ctors, [(NAT, LitNat(2))],
                       [CHECK_KIND_UNSPECIFIED])
    on = _graph_check(consts, ctors, [(NAT, LitNat(2))],
                      [CHECK_KIND_THEOREM])
    ok = off == (True, 0, off[2]) and on == (False, 8, on[2])
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] B gate_off_kind0: "
                 f"Nat:2 with kind=0 {_fmt(*off)} | with kind=3 {_fmt(*on)}")
    if not ok:
        fails.append(f"[B gate_off_kind0] kind0={off} kind3={on}")
    for cid in B_ROWS + D_ROWS:
        if want_rows and cid not in want_rows:
            continue
        _oracle_line(oracle, fails, lines,
                     "D" if cid in D_ROWS else "B", cid)
    for chain_cid, members in CHAINS:
        if want_rows and chain_cid not in want_rows:
            continue
        items = [(ROWS_BY_ID[m][2], ROWS_BY_ID[m][3]) for m, _k in members]
        kinds = [k for _m, k in members]
        acc, code, steps = _graph_check(consts, ctors, items, kinds)
        want = 0
        for m, _k in members:
            cls = oracle.get(m)
            if cls is None:
                want = -1
                break
            if cls != "OK":
                want = CODE_OF_CLASS.get(cls, -1)
                break
        ok = code == want
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] C {chain_cid}: "
                     f"members={[m for m, _ in members]} kinds={kinds} "
                     f"expected-code={want} graph={_fmt(acc, code, steps)}")
        if not ok:
            fails.append(f"[C {chain_cid}] graph code={code} expected={want}")


def main() -> int:
    t0 = time.perf_counter()
    only = {s.strip() for s in os.environ.get("G02_ONLY", "").split(",")
            if s.strip()}
    want_rows = {c for c in only if c in ROWS_BY_ID or
                 c.startswith("chain_")}
    fails: list[str] = []
    lines: list[str] = []
    print(f"oracle binary: "
          f"{os.popen(f'{lean_ref.LEAN} --version 2>&1').read().strip()}")
    print(f"oracle channel: #KDECL → Lean.Kernel.Environment.addDecl "
          f"({lean_ref.LEAN}); generated file "
          f"/tmp/vm_kdecl_oracle.lean")
    consts, ctors, structs = import_env(
        ALL_DEFS, MY_ROOTS,
        dump=dump_env(ALL_DEFS, MY_ROOTS, path=DUMP_PATH))
    print(f"graph env: {len(consts)} consts ({len(ctors)} ctors, "
          f"{len(structs)} structs)")
    for nm in ("injX_imax", "injX_max", "injD_imax", "injD_max"):
        ent = [c for c in consts if c[0] == nm]
        print(f"  stored type of {nm}: "
              f"{ent[0][1] if ent else '<MISSING FROM EXPORT>'}")
    run_all = not only
    if run_all or "a0" in only:
        print("a0    carrier layout drift guard (writer vs reader)")
        section_a0(fails, lines)
    if run_all or "guard" in only:
        print("guard carrier idleness: TASK_CHECK anchor E2 "
              "(whole check_e2e corpus, verdicts + step counts)")
        section_guard(fails, lines, consts, ctors)
    if run_all or (only & {"bcd", "b", "c", "d"}) or want_rows:
        print("bcd   kind gate + threading + level forms vs live #KDECL oracle")
        oracle = build_oracle()
        for cid, cls in oracle.items():
            print(f"  oracle[{cid}] = {cls}")
        section_bcd(fails, lines, consts, ctors, oracle, want_rows)
    for ln in lines:
        print(ln)
    n_gap = sum(1 for ln in lines if "XFAIL-KNOWN-GAP" in ln)
    print(f"\n=== card 010 G02 decl-injection differential: "
          f"{len(lines) - len(fails)}/{len(lines)} checks pass, "
          f"{n_gap} xfail known-gap, {len(fails)} fail "
          f"({time.perf_counter() - t0:.0f}s) ===")
    for f in fails:
        print(f"  [FAIL] {f}")
    print("=== " + ("OK" if not fails else "FAIL") + " ===")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
