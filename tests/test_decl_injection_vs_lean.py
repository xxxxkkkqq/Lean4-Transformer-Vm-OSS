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
  g03   unsafe-mode checker arm (card 010 G3): self-reference accepted, later
        safe reference rejected with 7, whole-add rollback, unsafe mutual
        block; app-arg/lam-body self-references were registered known gaps
        until card 016 carried the mode across the ST hops (F2 = cont_id +
        128*mode) — they now accept and left KNOWN_GAPS.
  g04   driver-side run_whnf continuation loop (card 010 G04, ADR016-B plan
        B): G1/a1 carriers (nat/lst/mu/iv/tree) + direct-Proj carriers
        (proj family, rounds>=2/stop coverage, c2) + ctor-major continuation
        carriers (csctor family, card 016) re-launched TASK_WHNF until
        the focus stops advancing; FINAL result diffed verbatim against the
        live #ORACLE WHNF channel (Meta.whnf).  Environments are minimized
        per family (theorem values dropped + extras carrier-root closure;
        nat/proj keep the full toy base) so the
        Python evaluator stays inside the 6GB RSS discipline; delivery mode
        runs one subprocess per family (handoff 006 G04).  iv/eG4IV2 was
        resolved by card 016 (closure seeds + the graph's I_CASE ctor-major
        continuation) and left KNOWN_GAPS.

  g8    card 011 G8 duplicate-name injection: InjectionEnv bookkeeping
        rejects with code 11 (kernel class alreadyDeclared, the dedicated
        constructor — the oracle leg maps 1:1) before any graph pass; accept
        and reject legs on all three kinds, plus the ordering legs (name
        wins over declTypeMismatch / thmTypeIsNotProp).
  g9    card 011 G9 duplicate universe level parameters: graph-side O(n²)
        pairwise scan of the declaration's lparams chain (kernel
        check_duplicated_univ_params, K/environment.cpp:111-121, class
        "other") — new reject code 10, anchor F2 carrier.

Run:  OMP_NUM_THREADS=3 python3 -u tests/test_decl_injection_vs_lean.py
Dev subset (one graph case ≈ 16 s on this box; a full run is canary-class):
  G02_ONLY=guard G02_GUARD_LIMIT=2  python3 -u tests/... (first 2 guard cases)
  G02_ONLY=g8                       python3 -u tests/test_decl_injection_vs_lean.py
  G02_ONLY=g9,g9axm_dup             python3 -u tests/test_decl_injection_vs_lean.py
  G02_ONLY=bcd,thm_nat      python3 -u tests/test_decl_injection_vs_lean.py
  G04_FAMILY=nat            python3 -u tests/... (dev loop: run one G04
                            family IN-PROCESS; unset = delivery mode = one
                            subprocess per family)
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure
from expr.model import (
    Const, App, Pi, Lam, Sort, LitNat, LSucc, LZero, LMax, LIMax, BI_DEFAULT,
    Proj, MData, Let, BVar,
)
from lean_vm.ref_vm import VMError
from lean_vm import step_driver as sd_check
from lean_vm.step_driver import (
    StepDriver, check_e2, CHECK_E2_STRIDE, CHECK_MODE_SAFE,
    CHECK_KIND_UNSPECIFIED, CHECK_KIND_AXIOM, CHECK_KIND_DEFINITION,
    CHECK_KIND_THEOREM, CHECK_KIND_OPAQUE,
)
from reference import lean_ref
from reference.olean_export import import_env, dump_env, const_meta_for
from reference.toy_env import TOY_CONSTS, TOY_LEAN_DEFS
from tests.test_olean_export import TARGET_DEFS, ROOTS
from tests.test_check_e2e import CHECK_CASES, CASE, SEQUENCES
from tests.test_brec_drec_iota_vs_lean import (
    norm, _instantiate_dump, NAT_DEFS, NAT_ROOTS, LST_DEFS, LST_ROOTS)

# reference/lean_ref.py + olean_export write FIXED /tmp paths, so two suites
# running at once clobber each other's oracle files (AGENTS.md, card 004
# note).  This suite's env dump is per-PID, so a pre/post baseline pair can
# run side by side.
DUMP_PATH = os.environ.get("G02_DUMP_PATH",
                           f"/tmp/g02_decl_inj_dump_{os.getpid()}.lean")

# The oracle binary is PINNED to the 4.33.1 toolchain (acceptance rule: the
# oracle is `~/.elan/bin/lean` v4.33.1) because that path floats with the
# elan default and drifted to 4.34.0 on 2026-09-20 (measured; handoff 006
# G06 "环境事实").  run_kdecl_oracle / dump_env both take lean_cmd overrides,
# so reference/ stays frozen.  Every lean invocation below goes through
# LEAN_CMD; the accepted G02 baseline (lead_full_suite.log) ran on 4.33.1.
_LEAN_4331 = (Path.home() / ".elan" / "toolchains" /
              "leanprover--lean4---v4.33.1" / "bin" / "lean")
LEAN_CMD: list[str] | None = ([str(_LEAN_4331)] if _LEAN_4331.exists()
                              else None)

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
# Card 010 G6: a real kernel mutual block (raw addDecl, cross-referencing
# unsafe members — exactly the shape the P1 probe measured as OK) committed
# into the oracle environment, so the "later declaration references a
# committed block member" row (g6v5) has an oracle-expressible form: the
# #KDECL channel adds ONE declaration per case, so the block itself must
# already be in the base env.  The graph env gets the same two constants
# through the dump closure (import_env keeps kind="def" regardless of
# safety, olean_export.py:571), with no meta — the G10-gate interplay of
# unsafe members is G03's surface (VM_SPEC §16.5 known approximation).
RAW_MUTUAL = """\
def injRawMutual : Lean.Declaration := .mutualDefnDecl [{ name := `g06v_f, levelParams := [], type := mkConst ``Nat, value := mkConst `g06v_g, hints := ReducibilityHints.regular 0, safety := DefinitionSafety.unsafe, all := [`g06v_f, `g06v_g] }, { name := `g06v_g, levelParams := [], type := mkConst ``Nat, value := mkNatLit 2, hints := ReducibilityHints.regular 0, safety := DefinitionSafety.unsafe, all := [`g06v_f, `g06v_g] }]
run_cmd do
  liftCoreM <| Lean.addDecl injRawMutual
"""
# Card 010 G03: one preinjected UNSAFE self-referential definition, so the
# "later SAFE declaration references a committed unsafe constant" row
# (g03b_later_ref) has an oracle-expressible form — the #KDECL channel adds
# ONE declaration per case.  The graph leg uses its own InjectionEnv-registered
# unsafe constant (same shape) instead, so the preinjection only feeds the
# oracle base environment (the dump keeps it meta-less, kind="def").
RAW_G03 = """\
def injRawG03 : Lean.Declaration := .defnDecl { name := `g03r_f, levelParams := [], type := mkConst ``Nat, value := mkConst `g03r_f, hints := ReducibilityHints.regular 0, safety := DefinitionSafety.unsafe, all := [`g03r_f] }
run_cmd do
  liftCoreM <| Lean.addDecl injRawG03
"""
# Card 011 G8: three base constants whose NAMES the G8 rows re-add through
# add_{axiom,definition,theorem} — on the oracle side the #KDECL addDecl hits
# environment.cpp check_name (class alreadyDeclared), on the driver side the
# InjectionEnv name table rejects with code 11.  The graph leg must see the
# same base environment, so these ride ALL_DEFS/MY_ROOTS like the G6/G03
# preinjections above.  The base KIND is deliberately irrelevant (check_name
# is a pure name lookup) and must stay `def`: import_env's M4 slice admits
# only def/ctor/ind (reference/olean_export.py:572).
G8_BASE_DEFS = """\
def g8b_a : Nat := 2
def g8b_d : Nat := 2
def g8b_t : Nat := 2
"""
ALL_DEFS = (TARGET_DEFS + "\n" + RAW_DEFS + INJ_DEFS + RAW_MUTUAL + RAW_G03
            + "\n" + G8_BASE_DEFS)
MY_ROOTS = ROOTS + ["injX_imax", "injX_max", "injD_imax", "injD_max",
                    "g06v_f", "g06v_g", "g03r_f", "g8b_a", "g8b_d", "g8b_t"]

# Lean-side declaration constructors.  The name is per case so addDecl never
# sees a duplicate.
_THM = ".thmDecl {{ name := `{}, levelParams := [], type := {}, value := {} }}"
_AXM = ".axiomDecl {{ name := `{}, levelParams := [], type := {}, isUnsafe := false }}"
_DEF = (".defnDecl {{ name := `{}, levelParams := [], type := {}, value := {}, "
        "hints := ReducibilityHints.regular 0, safety := DefinitionSafety.safe }}")
_DEF_UNSAFE = (".defnDecl {{ name := `{0}, levelParams := [], type := {1}, "
               "value := {2}, hints := ReducibilityHints.regular 0, "
               "safety := DefinitionSafety.unsafe, all := [`{0}] }}")
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

# graph reject code ↔ kernel exception class (VM_SPEC §7.4 + WP7-G rows).
# 2/9 are G6 additions: 2 = ERR_MISSING_CONST (unknown_constant at env.get,
# K/environment.cpp:78-85), 9 = mutual well-formedness (driver bookkeeping;
# its oracle class is "other" — CODE_OF_CLASS is NOT extended with "other"
# because that class also carries the unsafe-use message = code 7).
# Card 011 adds: 10 = duplicate universe level parameters (G9, graph arm;
# oracle class "other" again — plain kernel_exception, K/environment.cpp:
# 111-121), 11 = alreadyDeclared (G8, driver bookkeeping; the kernel's
# DEDICATED constructor, K/kernel_exception.h:32-37 → .alreadyDeclared at
# :168-169; message text per src/Lean/Message.lean:896).
CLASS_OF_CODE = {0: "accept", 1: "declTypeMismatch", 2: "unknownConstant",
                 4: "typeMismatch", 5: "typeExpected", 6: "declHasFVars",
                 7: "unsafeConstUse", 8: "thmTypeIsNotProp",
                 9: "mutualWF", 10: "dupUnivParams", 11: "alreadyDeclared"}
CODE_OF_CLASS = {"OK": 0, "typeExpected": 5, "thmTypeIsNotProp": 8,
                 "declTypeMismatch": 1}

# ── KNOWN-GAP xfail registry (card 009 protocol, ADR 018 + ADR 020 B) ───────
# A registered case that still diverges reports [XFAIL-KNOWN-GAP] and does NOT
# fail the run; a registered case that starts AGREEING reports [XPASS] and
# fails the run (the entry must then be removed — no silent drift either way).
KNOWN_GAPS = {
    # G03 (card 010): the anchor E2's mode bit rides the TASK_INFER frames
    # launched by the CHECK chain (kickoff/ck_g1_val) and inside the INFER
    # dispatch (app fn, lam/pi/let domains+values, proj child), but NOT
    # across the ST-continuation hops (I_FN→I_PI, I_LAMDOM→I_LAMSORT,
    # I_LETV→I_LETD): all six ST frame fields are spoken for, so a
    # self-reference reached as an app ARGUMENT or under a lam/let BODY is
    # re-inferred mode-less and the G10 gate false-fires (code 7).  Measured
    # 2026-09-20 (handoff 006 G03 H2): kernel OK / graph 7 at 11 steps.
    # Resolved by card 016 (memo 023 §3, 3-甲): the ST F2 carries
    # cont_id + 128*mode across the hops and the I_PI/I_LAMSORT/I_LETD
    # body/arg infers decode it from the frame's own F2 — both entries
    # removed 2026-09-26 (the remaining registered approximations: the pi
    # codomain chain and the DEFEQ soft emissions still ride mode-less,
    # VM_SPEC §16.6).
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


def _graph_check(consts, ctors, items, kinds, lps=None):
    """One graph run over a declaration list.  items: [(type, value|None)]
    (value None = anchor X = 0, the G5 no-value convention).
    lps (card 011 G9): optional per-declaration lparams name lists — the
    chain heads ride the anchors' F2 slots; `None` keeps the legacy
    byte-exact behaviour (every head 0, the scan arm inert).
    Returns (accepted, reject code (0 when accepted), micro-steps)."""
    build_step_graph, _ = _load_graph_builder()
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors)
    decls = [(enc.encode_term(t), enc.encode_term(v) if v is not None else 0)
             for t, v in items]
    heads = [enc.emit_univparams(lp) if lp else 0
             for lp in (lps or [None] * len(items))]
    drv = StepDriver(enc.b, graph, outputs)
    try:
        drv.run_check(decls, kinds=kinds, lparams=heads)
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
    cls = lean_ref.run_kdecl_oracle(ALL_DEFS, cases, lean_cmd=LEAN_CMD)
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


# ── card 010 G6: mutual blocks ──────────────────────────────────────────────
# Oracle channel (P1 probe, handoff 006 G06): `Declaration.mutualDefnDecl`
# reaches the kernel's add_mutual (K/environment.cpp:225-269) through the SAME
# #KDECL channel as G02.  Well-formedness failures surface as class "other"
# (plain kernel_exception → Kernel.Exception.other, kernel_exception.h:201-203);
# the five message texts were pinned verbatim by the P1 probe run.
# Rollback (P2 probe): after a failed add_mutual the caller's environment is
# unchanged — a later reference of a block member is unknownConstant (probe
# line H1) while the exception payload still carries the registered members
# (H2, K/environment.cpp:253-257 + kernel_exception.h:171-173).  A #KDECL
# case adds ONE declaration, so the rollback's oracle leg is pinned by the
# probe in the handoff, not re-runnable here; the driver leg asserts the
# same shape deterministically (member gone + later reference → code 2).
#
# Driver leg: InjectionEnv (lean_vm/step_driver.py).  W rows reject with
# VMError(9) before any graph pass (bookkeeping the graph cannot express);
# V rows run the two-phase add_mutual (header pass on the old env — the
# kernel checks types before registering anything, :236-251 vs :253-257 —
# then register all, then the body pass; any failure rolls the whole block
# back).  Member safety uses the ENV_FORMAT §2.4 encoding 0/1/2.
#
# Known approximation (VM_SPEC §16.5): the members' unsafe/partial flags
# never reach this suite's encoder (no const_meta channel — the same
# convention as every G02 row), so the G10-gate (code 7) interplay with
# mutual members is G03's differential surface, not exercised here.
G6_ROW_IDS = {"g6w1_dup_name", "g6w2_safe_block", "g6w3_empty_block",
              "g6w4_mixed_safety", "g6w5_lparams", "g6v1_crossref",
              "g6v2_member_fail", "g6v3_dispatch_thm", "g6v4_dispatch_def",
              "g6v5_later_ref"}
# class → graph code for the G6 rows only ("other" means mutual-WF here)
G6_CODE_OF_CLASS = {"OK": 0, "declTypeMismatch": 1, "unknownConstant": 2,
                    "thmTypeIsNotProp": 8, "other": 9}


def _mdv(name, lparams, ty, val, safety, block_all=None) -> str:
    """One DefinitionVal as a #KDECL term splice (mirrors the probe's
    g06DV).  safety is the DefinitionSafety constructor name."""
    lp = ", ".join(f"`{p}" for p in lparams)
    all_splice = ", ".join(f"`{n}" for n in (block_all or [name]))
    return ("{{ name := `{0}, levelParams := [{1}], type := {2}, "
            "value := {3}, hints := ReducibilityHints.regular 0, "
            "safety := DefinitionSafety.{4}, all := [{5}] }}"
            .format(name, lp, ty, val, safety, all_splice))


def _mutual(members_lean) -> str:
    return ".mutualDefnDecl [" + ", ".join(members_lean) + "]"


# (row id, oracle case term).  Names are unique per case; the oracle env
# never persists between cases (the template discards addDecl's result).
G6_ORACLE_CASES = [
    ("g6v1_crossref", _mutual([
        _mdv("g06v1_f", [], E_NAT, "(mkConst `g06v1_g)", "unsafe",
             ["g06v1_f", "g06v1_g"]),
        _mdv("g06v1_g", [], E_NAT, E_TWO, "unsafe",
             ["g06v1_f", "g06v1_g"])])),
    ("g6v2_member_fail", _mutual([
        _mdv("g06v2_ok", [], E_NAT, E_TWO, "unsafe",
             ["g06v2_ok", "g06v2_bad"]),
        _mdv("g06v2_bad", [], E_TRUE, E_TWO, "unsafe",
             ["g06v2_ok", "g06v2_bad"])])),
    ("g6v3_dispatch_thm", _THM.format("g06v3_t", E_NAT, E_TWO)),
    ("g6v4_dispatch_def", _DEF.format("g06v4_d", E_NAT, E_TWO)),
    ("g6v5_later_ref",
     _DEF.format("g06v5_h", E_NAT, "(mkConst `g06v_f)").replace(
         "safety := DefinitionSafety.safe",
         "safety := DefinitionSafety.unsafe")),
    ("g6w1_dup_name", _mutual([
        _mdv("g06w1_dup", [], E_NAT, E_TWO, "unsafe",
             ["g06w1_dup", "g06w1_dup"]),
        _mdv("g06w1_dup", [], E_NAT, E_TWO, "unsafe",
             ["g06w1_dup", "g06w1_dup"])])),
    ("g6w2_safe_block", _mutual([_mdv("g06w2_s", [], E_NAT, E_TWO, "safe")])),
    ("g6w3_empty_block", ".mutualDefnDecl []"),
    ("g6w4_mixed_safety", _mutual([
        _mdv("g06w4_a", [], E_NAT, E_TWO, "unsafe",
             ["g06w4_a", "g06w4_b"]),
        _mdv("g06w4_b", [], E_NAT, E_TWO, "partial",
             ["g06w4_a", "g06w4_b"])])),
    ("g6w5_lparams", _mutual([
        _mdv("g06w5_a", ["u"], "(Lean.mkSort (Lean.Level.param `u))", E_TWO,
             "unsafe", ["g06w5_a", "g06w5_b"]),
        _mdv("g06w5_b", [], "(Lean.mkSort (Lean.Level.zero))", E_TWO,
             "unsafe", ["g06w5_a", "g06w5_b"])])),
]


def build_g6_oracle() -> dict[str, str]:
    cls = lean_ref.run_kdecl_oracle(ALL_DEFS, G6_ORACLE_CASES,
                                    lean_cmd=LEAN_CMD)
    return dict(zip([c for c, _ in G6_ORACLE_CASES], cls))


def _inj_env(consts, ctors) -> "sd_check.InjectionEnv":
    build_step_graph, _src = _load_graph_builder()
    return sd_check.InjectionEnv(consts, ctors, build_step_graph)


def section_g6(fails, lines, consts, ctors):
    """Mutual blocks vs the live #KDECL oracle: well-formedness (code 9),
    register-before-check visibility, whole-block rollback, add_* dispatch."""
    oracle = build_g6_oracle()
    for cid, cls in oracle.items():
        print(f"  oracle[{cid}] = {cls}")

    def want_code(cid):
        cls = oracle.get(cid)
        if cls is None:
            return None
        return G6_CODE_OF_CLASS.get(cls, -1)

    # ── W rows: driver bookkeeping, zero graph passes ────────────────────
    w_rows = [
        ("g6w1_dup_name",
         [("g06w1_dup", [], NAT, LitNat(2), 0),
          ("g06w1_dup", [], NAT, LitNat(2), 0)],
         "duplicate declaration name"),
        ("g6w2_safe_block", [("g06w2_s", [], NAT, LitNat(2), 1)], None),
        ("g6w3_empty_block", [], None),
        ("g6w4_mixed_safety",
         [("g06w4_a", [], NAT, LitNat(2), 0),
          ("g06w4_b", [], NAT, LitNat(2), 2)], None),
        ("g6w5_lparams",
         [("g06w5_a", ["u"], TYPE1, LitNat(2), 0),
          ("g06w5_b", [], TYPE1, LitNat(2), 0)], None),
    ]
    for cid, members, msg_substr in w_rows:
        inj = _inj_env(consts, ctors)
        try:
            inj.add_mutual(members)
            got, detail = 0, "accept"
        except VMError as ex:
            got, detail = ex.code, str(ex)
        want = want_code(cid)
        ok = want is not None and got == want
        note = ""
        if ok and msg_substr and msg_substr not in detail:
            ok = False
            note = " (driver message does not mirror the kernel text)"
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] W {cid}: "
                     f"oracle={oracle.get(cid)} graph=code={got}"
                     f"({CLASS_OF_CODE.get(got, '?')}){note}")
        if not ok:
            fails.append(f"[W {cid}] oracle={oracle.get(cid)} "
                         f"graph=code={got} detail={detail}")

    # ── V rows: graph passes through InjectionEnv ─────────────────────────
    # V1 crossref positive: member 1's VALUE references member 2 — only the
    # register-all phase makes that encodable; then both bodies accept.
    inj = _inj_env(consts, ctors)
    try:
        inj.add_mutual([("g06v1_f", [], NAT, Const("g06v1_g"), 0),
                        ("g06v1_g", [], NAT, LitNat(2), 0)])
        got = 0
    except VMError as ex:
        got = ex.code
    ok = (want_code("g6v1_crossref") == 0 and got == 0
          and inj.contains("g06v1_f") and inj.contains("g06v1_g"))
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] V g6v1_crossref: "
                 f"oracle={oracle.get('g6v1_crossref')} "
                 f"graph={_fmt(got == 0, got, inj.steps_last)}"
                 f" members_registered="
                 f"{inj.contains('g06v1_f') and inj.contains('g06v1_g')}")
    if not ok:
        fails.append(f"[V g6v1_crossref] got code={got}")

    # V2 bad member: member 1 accepts, member 2 rejects declTypeMismatch,
    # and the WHOLE block is rolled back (probe H1 form: a later reference
    # of a member name is unknownConstant on both sides).
    inj = _inj_env(consts, ctors)
    try:
        inj.add_mutual([("g06v2_ok", [], NAT, LitNat(2), 0),
                        ("g06v2_bad", [], TRUE, LitNat(2), 0)])
        got = 0
    except VMError as ex:
        got = ex.code
    rb = None
    try:
        inj.add_definition("g06v2_user", NAT, Const("g06v2_ok"))
        rb = 0
    except VMError as ex:
        rb = ex.code
    rolled_back = (not inj.contains("g06v2_ok")
                   and not inj.contains("g06v2_bad"))
    ok = (want_code("g6v2_member_fail") == 1 and got == 1
          and rolled_back and rb == 2)
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] V g6v2_member_fail: "
                 f"oracle={oracle.get('g6v2_member_fail')} "
                 f"graph=code={got}({CLASS_OF_CODE.get(got, '?')}) "
                 f"rollback(member_absent={rolled_back}, "
                 f"later_ref=code={rb}({CLASS_OF_CODE.get(rb, '?')})) "
                 f"[oracle rollback leg = probe H1, handoff 006 G06]")
    if not ok:
        fails.append(f"[V g6v2_member_fail] code={got} rolled_back="
                     f"{rolled_back} later_ref={rb}")

    # V3/V4 dispatch: theorem routes through the kind-3 anchor (code 8 on a
    # non-Prop type), definition accepts.
    inj = _inj_env(consts, ctors)
    try:
        inj.add_theorem("g06v3_t", NAT, LitNat(2))
        got = 0
    except VMError as ex:
        got = ex.code
    ok = want_code("g6v3_dispatch_thm") == 8 and got == 8
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] V g6v3_dispatch_thm: "
                 f"oracle={oracle.get('g6v3_dispatch_thm')} "
                 f"graph=code={got}({CLASS_OF_CODE.get(got, '?')})")
    if not ok:
        fails.append(f"[V g6v3_dispatch_thm] got code={got}")
    inj = _inj_env(consts, ctors)
    try:
        inj.add_definition("g06v4_d", NAT, LitNat(2))
        got = 0
    except VMError as ex:
        got = ex.code
    ok = want_code("g6v4_dispatch_def") == 0 and got == 0
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] V g6v4_dispatch_def: "
                 f"oracle={oracle.get('g6v4_dispatch_def')} "
                 f"graph={_fmt(got == 0, got, inj.steps_last)}")
    if not ok:
        fails.append(f"[V g6v4_dispatch_def] got code={got}")

    # V5 later reference of a COMMITTED block member: g06v_f/g06v_g are in
    # the base env (RAW_MUTUAL above); the referencing definition must be
    # unsafe itself — a safe checker may not use an unsafe declaration
    # (measured: probe A2/I1, `.other` class = the graph's code-7 surface).
    inj = _inj_env(consts, ctors)
    try:
        inj.add_definition("g06v5_h", NAT, Const("g06v_f"), is_unsafe=True)
        got = 0
    except VMError as ex:
        got = ex.code
    ok = want_code("g6v5_later_ref") == 0 and got == 0
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] V g6v5_later_ref: "
                 f"oracle={oracle.get('g6v5_later_ref')} "
                 f"graph={_fmt(got == 0, got, inj.steps_last)}")
    if not ok:
        fails.append(f"[V g6v5_later_ref] got code={got}")


# ── card 010 G03: the unsafe-mode checker arm (G2-unsafe) ───────────────────
# Kernel semantics (K/environment.cpp:160-190): an unsafe add_definition
# checks the HEADER on the old env and the BODY on the new env, both with an
# UNSAFE-mode checker (:165-169/:172-177), so its self-references are legal;
# a LATER safe declaration referencing the committed constant still throws
# (safe checker + infer_constant's unsafe-use throw, K/type_checker.cpp:
# 110-117 → class "other" = the graph's code 7).  The graph side carries the
# checker mode as DATA: the TASK_CHECK anchor's E2 = kind + STRIDE*mode
# (ENV_FORMAT §2.8), decoded by the G10 gate; InjectionEnv hands the
# declarations' ConstantInfo (kind/safety) to the encoder, which precomputes
# the anchor F2 use_reject bit.  Card 016 (memo 023 §3): the mode now also
# crosses the ST-continuation hops (I_FN→I_PI, I_LAMDOM→I_LAMSORT,
# I_LETV→I_LETD) via the ST F2 = cont_id + 128*mode carrier, so the
# app-argument and lam/let-body self-references (g03g/g03h) accept — the
# registered approximations left: the pi codomain chain and the DEFEQ soft
# emissions still ride mode-less (VM_SPEC §16.6).
G3_ROW_IDS = {"g03a_selfref", "g03b_later_ref", "g03b2_unsafe_ref",
              "g03c_body_fail", "g03e_mutual_xref", "g03g_arg_selfref",
              "g03h_lam_selfref"}
# class → graph code for the G03 rows ("other" means the unsafe-use message
# here — the G6 W rows map the same class to code 9, disambiguated by row).
G3_CODE_OF_CLASS = {"OK": 0, "declTypeMismatch": 1, "other": 7}

G3_ORACLE_CASES = [
    # row 1: the unsafe definition's own body references itself → OK
    ("g03a_selfref", _DEF_UNSAFE.format("g03a_f", E_NAT, "(mkConst `g03a_f)")),
    # row 2: a LATER SAFE declaration references the preinjected unsafe
    # g03r_f → the safe checker throws (class "other" = unsafe use)
    ("g03b_later_ref", _DEF.format("g03b_g", E_NAT, "(mkConst `g03r_f)")),
    # row 2's mode twin: the SAME reference made by an UNSAFE declaration
    # (mode 1) → the unsafe checker allows it
    ("g03b2_unsafe_ref",
     _DEF_UNSAFE.format("g03b2_g", E_NAT, "(mkConst `g03r_f)")),
    # row 3: an unsafe definition whose body fails the type check →
    # declTypeMismatch and the whole add is not adopted
    ("g03c_body_fail", _DEF_UNSAFE.format("g03c_bad", E_NAT, E_TRUE)),
    # row 3': an unsafe MUTUAL block with cross-referencing members → OK
    ("g03e_mutual_xref", _mutual([
        _mdv("g03e_f", [], E_NAT, "(mkConst `g03e_g)", "unsafe",
             ["g03e_f", "g03e_g"]),
        _mdv("g03e_g", [], E_NAT, E_TWO, "unsafe",
             ["g03e_f", "g03e_g"])])),
    # known gaps: kernel OK / graph code 7 (mode bit lost across an ST hop)
    ("g03g_arg_selfref",
     _DEF_UNSAFE.format(
         "g03g_f", E_NAT,
         "(mkApp (mkApp (mkConst ``Nat.add) (mkConst `g03g_f)) (mkNatLit 0))")),
    ("g03h_lam_selfref",
     _DEF_UNSAFE.format(
         "g03h_f", E_ARROW_T,
         "(mkLambda `x BinderInfo.default (mkConst ``Nat) "
         "(mkApp (mkConst `g03h_f) (mkBVar 0)))")),
]


def build_g03_oracle() -> dict[str, str]:
    cls = lean_ref.run_kdecl_oracle(ALL_DEFS, G3_ORACLE_CASES,
                                    lean_cmd=LEAN_CMD)
    return dict(zip([c for c, _ in G3_ORACLE_CASES], cls))


def section_g03(fails, lines, consts, ctors):
    """Unsafe add_definition vs the live #KDECL oracle: mode suppression for
    the declaration's own header/body checks, the G10 gate for later safe
    references, whole-add rollback."""
    oracle = build_g03_oracle()
    for cid, cls in oracle.items():
        print(f"  oracle[{cid}] = {cls}")

    def want(cid):
        cls = oracle.get(cid)
        return None if cls is None else G3_CODE_OF_CLASS.get(cls, -1)

    def run_row(cid, fn):
        inj = _inj_env(consts, ctors)
        try:
            got = fn(inj)
        except VMError as ex:
            got = ex.code
        gap = KNOWN_GAPS.get(cid)
        wantc = want(cid)
        tag, fail = "PASS", None
        if wantc is None:
            tag, fail = "FAIL", f"[{cid}] no oracle line"
        elif got == wantc and gap:
            tag, fail = "XPASS", (f"[{cid}] XPASS: known-gap entry must be "
                                  "removed (graph now agrees with lean)")
        elif got == wantc:
            pass
        elif gap:
            tag = "XFAIL-KNOWN-GAP"
        else:
            fail = (f"[{cid}] graph code={got} but lean class="
                    f"{oracle.get(cid)} (want {wantc})")
        detail = (f"graph=code={got}({CLASS_OF_CODE.get(got, '?')}) "
                  f"steps={inj.steps_last}")
        return tag, detail, fail, inj

    # row 1: self-reference accepted (mode suppression on both passes)
    tag, detail, fail, inj = run_row(
        "g03a_selfref",
        lambda i: (i.add_definition("g03u_f", NAT, Const("g03u_f"),
                                    is_unsafe=True), 0)[1])
    reg = inj.contains("g03u_f")
    ok = tag == "PASS" and reg
    lines.append(f"  [{tag}] A g03a_selfref: oracle={oracle.get('g03a_selfref')} "
                 f"{detail} registered={reg}"
                 + (f"\n      known gap: {KNOWN_GAPS.get('g03a_selfref')}"
                    if tag == "XFAIL-KNOWN-GAP" else ""))
    if fail or (tag == "PASS" and not reg):
        fails.append(fail or f"[A g03a_selfref] registered={reg}")

    # row 2: a later SAFE declaration referencing the registered unsafe
    # constant — the checker is safe (anchor mode 0) → code 7.  This is also
    # the mode=0 invariance leg: identical corpus as row 2's twin, only the
    # mode bit differs.
    tag, detail, fail, _ = run_row(
        "g03b_later_ref",
        lambda i: (i.add_definition("g03u_f", NAT, Const("g03u_f"),
                                    is_unsafe=True),
                   i.add_definition("g03u_g", NAT, Const("g03u_f")))[1])
    lines.append(f"  [{'PASS' if tag == 'PASS' else tag}] B g03b_later_ref: "
                 f"oracle={oracle.get('g03b_later_ref')} {detail}"
                 + (f"\n      known gap: {KNOWN_GAPS.get('g03b_later_ref')}"
                    if tag == "XFAIL-KNOWN-GAP" else ""))
    if fail:
        fails.append(fail)

    # row 2's twin: the same reference under the unsafe checker (mode 1) →
    # accepted; the pair proves the mode bit is consumed (not inert).
    tag, detail, fail, inj = run_row(
        "g03b2_unsafe_ref",
        lambda i: (i.add_definition("g03u_f", NAT, Const("g03u_f"),
                                    is_unsafe=True),
                   i.add_definition("g03u_g", NAT, Const("g03u_f"),
                                    is_unsafe=True), 0)[2])
    reg = inj.contains("g03u_g")
    ok = tag == "PASS" and reg
    lines.append(f"  [{'PASS' if ok else tag}] B g03b2_unsafe_ref: "
                 f"oracle={oracle.get('g03b2_unsafe_ref')} {detail} "
                 f"registered={reg}"
                 + (f"\n      known gap: {KNOWN_GAPS.get('g03b2_unsafe_ref')}"
                    if tag == "XFAIL-KNOWN-GAP" else ""))
    if fail or (tag == "PASS" and not reg):
        fails.append(fail or f"[B g03b2_unsafe_ref] registered={reg}")

    # row 3: failing body → declTypeMismatch, whole add rolled back
    # (kernel: the exception's environment is not adopted; the driver leg
    # asserts member-absent + a later reference → unknownConstant, the
    # probe-H1 form from handoff 006 G06 P2).
    def _bad_body(i):
        try:
            i.add_definition("g03u_bad", NAT, TRUE, is_unsafe=True)
            return 0
        except VMError as ex:
            assert ex.code == 1
            raise
    inj = _inj_env(consts, ctors)
    try:
        got = _bad_body(inj)
    except VMError as ex:
        got = ex.code
    rolled = not inj.contains("g03u_bad")
    try:
        inj.add_definition("g03u_user", NAT, Const("g03u_bad"))
        rb = 0
    except VMError as ex:
        rb = ex.code
    ok = (want("g03c_body_fail") == 1 and got == 1 and rolled and rb == 2)
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] C g03c_body_fail: "
                 f"oracle={oracle.get('g03c_body_fail')} "
                 f"graph=code={got}({CLASS_OF_CODE.get(got, '?')}) "
                 f"rollback(member_absent={rolled}, later_ref=code={rb}"
                 f"({CLASS_OF_CODE.get(rb, '?')}))")
    if not ok:
        fails.append(f"[C g03c_body_fail] code={got} rolled_back={rolled} "
                     f"later_ref={rb}")

    # row 3': unsafe mutual block with cross-referencing members (the mode
    # arm covers the block's own header/body passes, which run with the
    # block's unsafe mode per the G06 two-phase add_mutual)
    tag, detail, fail, inj = run_row(
        "g03e_mutual_xref",
        lambda i: (i.add_mutual([("g03e_f", [], NAT, Const("g03e_g"), 0),
                                 ("g03e_g", [], NAT, LitNat(2), 0)]), 0)[1])
    reg = inj.contains("g03e_f") and inj.contains("g03e_g")
    ok = tag == "PASS" and reg
    lines.append(f"  [{'PASS' if ok else tag}] E g03e_mutual_xref: "
                 f"oracle={oracle.get('g03e_mutual_xref')} {detail} "
                 f"members_registered={reg}"
                 + (f"\n      known gap: {KNOWN_GAPS.get('g03e_mutual_xref')}"
                    if tag == "XFAIL-KNOWN-GAP" else ""))
    if fail or (tag == "PASS" and not reg):
        fails.append(fail or f"[E g03e_mutual_xref] members_registered={reg}")

    # known gaps: kernel OK / graph false code 7 (mode lost across an ST hop)
    for cid, ty, val in [
            ("g03g_arg_selfref", NAT,
             App(App(Const("Nat.add"), Const("g03x_f")), LitNat(0))),
            ("g03h_lam_selfref", Pi("x", BI_DEFAULT, NAT, NAT),
             Lam("x", BI_DEFAULT, NAT, App(Const("g03x_f"), LitNat(0))))]:
        def _row(i, _ty=ty, _val=val):
            i.add_definition("g03x_f", _ty, _val, is_unsafe=True)
            return 0
        tag, detail, fail, _ = run_row(cid, _row)
        lines.append(f"  [{tag}] G {cid}: oracle={oracle.get(cid)} {detail}"
                     + (f"\n      known gap: {KNOWN_GAPS.get(cid)}"
                        if tag == "XFAIL-KNOWN-GAP" else ""))
        if fail:
            fails.append(fail)


# ── card 010 G04: driver-side run_whnf continuation (ADR016-B plan B) ───────
# The kernel's whnf_core feeds every successful proj reduction back into
# whnf_core (K/type_checker.cpp:504-508); the graph's TASK_WHNF delivers the
# raw field and stops (P7.5c-2, VM_SPEC §11.16).  StepDriver.run_whnf moves
# the continuation to the caller: re-launch TASK_WHNF on the delivered
# closure until (pos, env) stops advancing.  No Python semantics: every
# round is one graph task.  Corpus = the G1/a1 raw-field carriers (Nat, Lst,
# mutual MA/MB, indexed IV, nested MyTree — the brec suite's NAT/LST defs +
# the G04_* defs below); every expectation is the live #ORACLE WHNF channel
# (Meta.whnf, 4.33.1 — reference/lean_ref.run_oracle_mixed), nothing
# prebaked (acceptance rule 2).
#
# Environment minimization (stage C, handoff 006 G04): the faithful dump
# closure is cut down by two data-driven rules — theorem VALUES dropped
# (kind is dump data, no name branch; proof trees never enter this
# corpus's reduction path) and dump EXTRAS outside the transitive closure
# seeded at carrier roots (stored ty/val + recursor rule
# rhs/ctor names) pruned.  The nat family additionally keeps the TOY base
# in full: reduction performs dynamic ENV name lookups invisible to the
# stored terms (bisect g04b: adding Nat.pred alone flips d1 from stuck@30
# to the correct halt@122).  Other families must NOT pin the toy base —
# the full faithful Nat.below/brecOn trees inflate the evaluator to
# ~20MB/step and the iv child crossed 6GB (g04b_full3, g04b_ivtrace).
# probe7's full-closure iv env pushed the pure-Python evaluator to
# 8.9-11.9GB RSS (AGENTS.md machine discipline violation); the minimized iv
# env peaks at 3.8GB on the same rows.  Delivery mode = one subprocess per
# family (G04_FAMILY env), so the parent's tree never aggregates two
# families' evaluators; dev loops set G04_FAMILY directly to run one family
# in-process.
#
# rounds>=2 coverage (c2 addendum, handoff 006): the two direct-Proj
# carriers (g04proj_*) fire the loop's second round — the round-2
# no-advance check is what stops them (the graph's raw whnf delivers
# head-normal even here; a plain run() reaches the SAME literal in one
# round, g04b_c2_probe4 RAW lines).  Card 016 (memo 023) resolved the
# IV2 row: the seed fix (Nat.pred/Nat.rec into the iv closure) plus the
# graph's I_CASE ctor-major continuation let it reach LitNat 6 — the
# entry left KNOWN_GAPS.  The proj rows keep the round-2/stop path
# covered while the raw-field delta stays latent; universe-polymorphic
# accessor DEFS (a `PProd.fst …` spine) livelock on the current
# univ_arity=0 encoding (B13/WP1 debt, g04b_c2_probe1.log: 2000 steps
# no halt, 4GB), so proj carriers are encoded as direct Proj nodes in
# the toy P2 convention, the same mapping every brec-era suite uses.
#
# csctor family (card 016 拍 B, memo 023 §2): the I_CASE ctor-major
# continuation rows.  A `Nat.succ <field>` major whose field is a stuck
# leaf survives whnf head-normal (the graph's nat-op decline under NAT
# frames) and the kernel matches the succ rule on the ctor head
# (K/inductive.h:100), passing the field into the rhs — eG4CSC (casesOn,
# direct delivery), eG4RECC (Nat.rec, the 15-step build loop), eG4PRED
# (the `Nat.pred (Nat.succ k) → k` shape rule).  Residual registered
# debt (VM_SPEC §11.7, NOT rowed here): a minor body that ADDS a stuck
# leaf (`fun n => n + 1000`) still diverges — the kernel unfolds
# `Nat.add k 1000` one rec step to `Nat.succ (Nat.add k 999)`, the
# graph's nat-arg gate hard-rejects (the offset/stuck-arg milestone).
G04_CSCTOR_DEFS = r'''
opaque k : Nat
def eG4CSC : Nat := Nat.casesOn (Nat.succ k) 100 (fun _ => 42)
def eG4RECC : Nat := Nat.rec (motive := fun _ => Nat) 100 (fun _ _ => 999) (Nat.succ k)
def eG4PRED : Nat := Nat.pred (Nat.succ k)
'''
G04_MUTUAL_DEFS = r'''
mutual
inductive G04A where
  | base : G04A
  | a : G04B → G04A
inductive G04B where
  | b : G04A → G04B
end

def G04FMA : (t : G04A) → @G04A.below (fun _ : G04A => Nat) (fun _ : G04B => Nat) t → Nat
  | G04A.base, _ => 20
  | G04A.a _, ⟨ih, _⟩ => ih
def G04FMB : (t : G04B) → @G04B.below (fun _ : G04A => Nat) (fun _ : G04B => Nat) t → Nat
  | G04B.b _, ⟨ih, _⟩ => ih

noncomputable def eG4MU1 : Nat := @G04A.brecOn (fun _ : G04A => Nat) (fun _ : G04B => Nat) G04A.base G04FMA G04FMB
noncomputable def eG4MU2 : Nat := @G04A.brecOn (fun _ : G04A => Nat) (fun _ : G04B => Nat) (G04A.a (G04B.b G04A.base)) G04FMA G04FMB
'''
G04_IV_DEFS = r'''
inductive G04I : Nat → Type where
  | v0 : G04I 0
  | v1 (n : Nat) : G04I n → G04I (n + 1)

def G04FIV : (n : Nat) → (t : G04I n) →
    @G04I.below (fun (i : Nat) (_ : G04I i) => Nat) n t → Nat
  | 0, .v0, _ => 5
  | _+1, .v1 _ _, ⟨ih, _⟩ => ih + 1

noncomputable def eG4IV1 : Nat :=
  @G04I.brecOn (fun (i : Nat) (_ : G04I i) => Nat) 0 G04I.v0 G04FIV
noncomputable def eG4IV2 : Nat :=
  @G04I.brecOn (fun (i : Nat) (_ : G04I i) => Nat) 1 (G04I.v1 0 G04I.v0) G04FIV
'''
G04_TREE_DEFS = r'''
inductive G04W where
  | leaf | node (l : G04W) (r : G04W)

def G04FW : (t : G04W) → @G04W.below (fun _ : G04W => Nat) t → Nat
  | .leaf, _ => 2
  | .node _ _, bh => bh.1.1 + bh.2.1

noncomputable def eG4W : Nat :=
  @G04W.brecOn (fun _ : G04W => Nat) (G04W.node (G04W.node G04W.leaf G04W.leaf) G04W.leaf) G04FW
'''
G04_PROJECT_DEFS = (
    "def eG4C2Ref : Nat := (PProd.mk (Nat.add 1 3) Nat.zero).1\n")
_G04_PP = "PProd PProd.mk PProd.casesOn PProd.rec PUnit PUnit.unit"
G04_UPROD_DEFS = r'''
structure UProd (α : Type u) (β : Type u) where
  fst : α
  snd : β
'''
_G04_UPROD_ROOTS = ("UProd UProd.mk UProd.fst UProd.snd UProd.rec "
                    "UProd.casesOn Nat").split()
# Fully-elaborated use sites (`@UProd.fst u Nat Nat …`): the implicit type
# args are real spine entries in the kernel term, so the whnf proj must skip
# the ctor's nparams=2 to reach the field (reduce_proj_core,
# K/type_checker.cpp:420-441) — the shape the graph's accessor-def whnf
# livelocked on at univ_arity=0 (g04b_c2_probe2.log, 2000 steps / 4GB;
# B13/WP1 debt, card 015 component 3).
def _uprod_mk(a, b):
    return App(App(App(App(Const("UProd.mk", (LZero(),)), Const("Nat")),
                       Const("Nat")), a), b)


def _uprod_acc(name, arg):
    return App(App(App(Const(name, (LZero(),)), Const("Nat")), Const("Nat")),
               arg)


# family → (defs, dump roots, [(row id, carrier def name)])
G04_GROUPS = {
    "nat": (NAT_DEFS, list(NAT_ROOTS),
            [("g04nat_d1", "d1"), ("g04nat_d3", "d3"), ("g04nat_d4", "d4")]),
    "lst": (LST_DEFS, list(LST_ROOTS),
            [("g04lst_eL1", "eL1"), ("g04lst_eL2", "eL2"),
             ("g04lst_eL3", "eL3")]),
    "mu": (G04_MUTUAL_DEFS,
           ("Nat G04A G04B G04A.rec G04B.rec G04A.brecOn G04B.brecOn "
            "G04FMA G04FMB eG4MU1 eG4MU2 " + _G04_PP).split(),
           [("g04mu_eG4MU1", "eG4MU1"), ("g04mu_eG4MU2", "eG4MU2")]),
    "iv": (G04_IV_DEFS,
           # Nat.pred rides the roots so the dump carries it: the iota
           # succ-rule build loop synthesizes `Nat.pred` / `Nat.rec` by
           # NAME at reduction time (VM_SPEC §16.7 stage C, memo 023 §1.2
           # D2/D3) — the stored trees never mention them, so the closure
           # walk alone cannot see them (bisect g04b) and the graph's
           # rec_ids_ok gate would false-stick the succ rule.  Seeded into
           # the frontier below instead of pinning the toy base (keep_toy):
           # the faithful Nat.below/brecOn trees inflate the evaluator
           # beyond the 6GB line (g04b_full3).
           ("Nat Nat.pred G04I G04I.rec G04I.brecOn G04FIV eG4IV1 eG4IV2 "
            + _G04_PP).split(),
           [("g04iv_eG4IV1", "eG4IV1"), ("g04iv_eG4IV2", "eG4IV2")],
           ["eG4IV1", "eG4IV2", "Nat.pred", "Nat.rec"]),
    "tree": (G04_TREE_DEFS,
             ("Nat G04W G04W.rec G04W.brecOn G04FW eG4W " + _G04_PP).split(),
             [("g04tree_eG4W", "eG4W")]),
    # direct Proj-node carriers (toy P2 convention, the same mapping every
    # brec-era suite uses for PProd): the raw round delivers the field and
    # round >= 2 must reduce it — the ONLY shapes on the current graph
    # that force the continuation loop (c2 probe evidence, section header).
    "proj": (G04_PROJECT_DEFS,
             ("Nat Nat.add Nat.zero Nat.succ Nat.brecOn Nat.below "
              "PProd PProd.mk PProd.casesOn PProd.rec PUnit PUnit.unit "
              "eG4C2Ref").split(),
             [("g04proj_fst_redex",
               Proj("P2", 0,
                    App(App(Const("P2.mk"),
                            App(App(Const("Nat.add"), LitNat(1)),
                                LitNat(3))),
                        LitNat(0))),
               "(PProd.mk (Nat.add 1 3) Nat.zero).1"),
              ("g04proj_fst_fst",
               Proj("P2", 0, Proj("P2", 1,
                    App(App(Const("P2.mk"), LitNat(0)),
                        App(App(Const("P2.mk"),
                                App(App(Const("Nat.add"), LitNat(4)),
                                    LitNat(5))), LitNat(0))))),
               "(PProd.mk Nat.zero (PProd.mk (Nat.add 4 5) Nat.zero)).2.1")],
             ["eG4C2Ref"]),
    # universe-polymorphic accessor DEFS through the real 2-param ctor app:
    # `UProd.fst (UProd.mk 3 4 : UProd Nat Nat)` whnfs to the field literal 3
    # (oracle #ORACLE WHNF) once I_PROJ extracts args[nparams+idx] of the
    # full ctor spine (kernel reduce_proj_core); before that the proj
    # re-stuck and the accessor whnf diverged (card 015 component 3).
    "uprod": (G04_UPROD_DEFS, list(_G04_UPROD_ROOTS),
              [("g04uprod_fst",
                _uprod_acc("UProd.fst", _uprod_mk(LitNat(3), LitNat(4))),
                "UProd.fst (UProd.mk 3 4 : UProd Nat Nat)"),
               ("g04uprod_snd",
                _uprod_acc("UProd.snd", _uprod_mk(LitNat(3), LitNat(4))),
                "UProd.snd (UProd.mk 3 4 : UProd Nat Nat)")],
              ["UProd.fst", "UProd.snd", "UProd.mk", "Nat"]),
    # card 016 拍 B: I_CASE ctor-major continuation rows (see the csctor
    # header note).  Nat.pred/Nat.rec ride the seeds per C-16.7.x-1: the
    # succ-rule rhs synthesizes them by name at reduction time.
    "csctor": (G04_CSCTOR_DEFS,
               ("Nat Nat.pred Nat.casesOn Nat.rec k eG4CSC eG4RECC eG4PRED "
                + _G04_PP).split(),
               [("g04cs_eG4CSC", "eG4CSC"), ("g04cs_eG4RECC", "eG4RECC"),
                ("g04cs_eG4PRED", "eG4PRED")],
               ["eG4CSC", "eG4RECC", "eG4PRED", "Nat.pred", "Nat.rec"]),
}
G04_ROW_IDS = {r[0] for _grp in G04_GROUPS.values() for r in _grp[2]}
# families that must keep the full TOY base (bisect g04b: the brecOn peel
# of nat carriers dynamically needs Nat.pred; the proj carriers reduce
# Nat.add the same way); others run leaner reach-only envs — see _g04_env.
G04_KEEP_TOY = {"nat", "proj"}


def _g04_strip(e):
    return _g04_strip(e.child) if isinstance(e, MData) else e


def _g04_walk(x, sink):
    """Const names reachable in a stored expr tree (encoder will need a cid
    for every one of them)."""
    if isinstance(x, Const):
        sink.add(x.name)
    elif isinstance(x, App):
        _g04_walk(x.fn, sink); _g04_walk(x.arg, sink)
    elif isinstance(x, (Lam, Pi)):
        _g04_walk(x.domain, sink); _g04_walk(x.body, sink)
    elif isinstance(x, Let):
        _g04_walk(x.domain, sink); _g04_walk(x.value, sink)
        _g04_walk(x.body, sink)
    elif isinstance(x, Proj):
        _g04_walk(x.child, sink)
    elif isinstance(x, MData):
        _g04_walk(x.child, sink)


def _g04_env(defs, roots, carriers, dump_path, keep_toy):
    """Minimized faithful env for one carrier family (stage C, see the
    section header): extras pruned by carrier-root reference closure;
    theorem values dropped.  keep_toy additionally pins the full TOY base
    (and its transitive static refs) — required only for the nat family,
    whose brecOn peel does a dynamic ENV lookup of Nat.pred."""
    dump = dump_env(defs, roots, path=dump_path, lean_cmd=LEAN_CMD)
    _instantiate_dump(dump)
    src = list(TOY_CONSTS)
    toyset = {n for n, _, _ in src}
    for i, (n, t, v) in enumerate(src):
        if n in ("Nat.below", "Nat.brecOn") and n in dump:
            # the brec machinery must be the REAL dumped values, never the
            # pair-free reconstruction (009/P7.5c-3 ban, ADR016 context)
            src[i] = (n, norm(dump[n]["ty"]), norm(dump[n]["val"]))
    consts = src + [(n, norm(dump[n]["ty"]), norm(dump[n]["val"]))
                    for n in sorted(dump) if n not in toyset]
    toy_dump = dump_env(TOY_LEAN_DEFS, sorted(toyset),
                        path=f"/tmp/g04_toy_dump_{os.getpid()}.lean")
    merged = dict(toy_dump)
    merged.update(dump)
    consts = [(n, t, (None if merged[n]["kind"] == "thm" else v))
              for n, t, v in consts]
    meta_by_name = {consts[cid][0]: m for cid, m
                    in const_meta_for(consts, merged).items()}
    # Frontier seeds: the carrier roots AND (for keep_toy) the full toy
    # base — a kept entry whose stored term references a dump extra (e.g.
    # the replaced Nat.brecOn → Nat.brecOn.go) must not dangle
    # (g04b_full2 lst KeyError).
    reach, frontier, seen = set(), [*carriers,
                                    *(toyset if keep_toy else [])], set()
    TBL = {n: (t, v) for n, t, v in consts}
    while frontier:
        n = frontier.pop()
        if n in seen:
            continue
        seen.add(n)
        if n not in TBL:
            continue
        reach.add(n)
        sink = set()
        for part in TBL[n]:
            if part is not None:
                _g04_walk(part, sink)
        m = meta_by_name.get(n) or {}
        for r in (m.get("rules") or []):
            if r.get("rhs") is not None:
                _g04_walk(r["rhs"], sink)
            if isinstance(r.get("ctor"), str):
                sink.add(r["ctor"])
        for key in ("ctors", "all"):
            for s in (m.get(key) or []):
                if isinstance(s, str):
                    sink.add(s)
        if isinstance(m.get("induct"), str):
            sink.add(m["induct"])
        frontier.extend(r for r in sink if r not in seen)
    # The toy base pin (keep_toy) exists because reduction does dynamic
    # ENV lookups the stored terms don't mention — VM_SPEC §11.11 cs_build
    # materializes `Nat.pred t` in the succ-rule rhs.  Bisect g04b: adding
    # Nat.pred alone flips d1 from stuck@30 to the correct halt@122 (=
    # full stage-A result).  Other families must NOT pin it: the full
    # faithful trees (Nat.below/brecOn chains) inflate the evaluator to
    # ~20MB/step and the iv child crossed the 6GB line (g04b_full3,
    # g04b_ivtrace).
    if keep_toy:
        consts = [e for e in consts if e[0] in toyset or e[0] in reach]
    else:
        consts = [e for e in consts if e[0] in reach]
    ctors = {n for n in merged if merged[n]["kind"] == "ctor"}
    return consts, ctors, const_meta_for(consts, merged)


class _G04Drv(StepDriver):
    """Observation-only round counter for run_whnf: _run_loop is the
    per-round primitive run_whnf() calls, so counting its calls counts
    rounds.  No semantic override; run_whnf's signature untouched."""
    def _run_loop(self, max_steps: int):
        self._rounds = getattr(self, "_rounds", 0) + 1
        return super()._run_loop(max_steps)


def _g04_family(fam, want_rows, fails, lines):
    """One family: build env, live #ORACLE WHNF batch, run_whnf per carrier,
    verbatim compare with the KNOWN_GAPS/XPASS protocol.  A row is either
    (cid, def-name) or (cid, term-expr, #ORACLE-source-term)."""
    grp = G04_GROUPS[fam]
    defs, roots, rows = grp[0], grp[1], grp[2]
    seed = grp[3] if len(grp) > 3 else None
    norm = []
    for r in rows:
        cid, carrier = r[0], r[1]
        src = (carrier if isinstance(carrier, str)
               else (r[2] if len(r) > 2 else None))
        if not want_rows or cid in want_rows:
            norm.append((cid, carrier, src))
    if not norm:
        return
    consts, ctors, meta = _g04_env(
        defs, roots,
        seed if seed is not None
        else [c for _c, c, _s in norm if isinstance(c, str)],
        f"/tmp/g04_dump_{fam}_{os.getpid()}.lean",
        fam in G04_KEEP_TOY)
    print(f"  [g04 {fam}] env: {len(consts)} consts")
    oracle = lean_ref.run_oracle_mixed(
        defs, [("WHNF", src, None) for _c, _car, src in norm],
        lean_cmd=LEAN_CMD)
    oj = {src: _g04_strip(lean_ref.json_to_expr(p))
          for (_c, _car, src), (_kind, p) in zip(norm, oracle)}
    build_step_graph, _src = _load_graph_builder()
    graph, outputs = build_step_graph()
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    drv = _G04Drv(enc.b, graph, outputs)
    for cid, carrier, src in norm:
        pos = enc.encode_term(Const(carrier)
                              if isinstance(carrier, str) else carrier)
        drv._rounds = 0
        gap = KNOWN_GAPS.get(cid)
        try:
            res = drv.run_whnf(pos)
            got, err = _g04_strip(decode_closure(enc.b, *res)), ""
        except TimeoutError as ex:
            got, err = f"TimeoutError: {ex}", " TIMEOUT"
        except VMError as ex:
            got, err = f"VMError code={ex.code}", " REJECT"
        expected = oj[src]
        agree = not err and got == expected
        if agree and gap:
            tag = "XPASS"
            fails.append(f"[G04 {cid}] XPASS: known-gap entry must be "
                         f"removed (run_whnf now agrees with lean)")
        elif agree:
            tag = "PASS"
        elif gap:
            tag = "XFAIL-KNOWN-GAP"
        else:
            tag = "FAIL"
            fails.append(f"[G04 {cid}] run_whnf={got}{err} but oracle "
                         f"WHNF={expected}")
        label = carrier if isinstance(carrier, str) else src[:32] + "…"
        lines.append(f"  [{tag}] G04 {fam}/{label}: oracle={expected} "
                     f"run_whnf={got}{err} steps={drv.steps} "
                     f"rounds={drv._rounds}"
                     + (f"\n      known gap: {gap}"
                        if tag == "XFAIL-KNOWN-GAP" else ""))
    del drv, enc, graph, outputs


def section_g04(fails, lines, want_rows):
    fam = os.environ.get("G04_FAMILY")
    if fam or want_rows:
        # in-process: child/single-family dev loop, or a row-level dev subset
        fams = [fam] if fam else list(G04_GROUPS)
        for f in fams:
            _g04_family(f, want_rows, fails, lines)
        return
    # delivery mode: one subprocess per family — the pure-Python evaluator
    # must never aggregate two families' envs in one process (6GB RSS
    # discipline, AGENTS.md; probe7 full-closure aggregate peaked 11.9GB)
    for fam in G04_GROUPS:
        env = dict(os.environ, G04_FAMILY=fam, G02_ONLY="g04")
        try:
            r = subprocess.run([sys.executable, "-u", __file__], env=env,
                               capture_output=True, text=True, timeout=2400)
        except subprocess.TimeoutExpired:
            fails.append(f"[G04 {fam}] child timeout")
            lines.append(f"  [FAIL] G04 {fam}: child timeout after 2400s")
            continue
        done = any(ln.startswith("G04-DONE") for ln in r.stdout.splitlines())
        for ln in r.stdout.splitlines():
            if ln.startswith("  [") and "G04 " in ln:
                lines.append(ln)
            elif ln.startswith("G04X "):
                fails.append(ln[len("G04X "):])
            elif ln.startswith("  [g04"):
                print(ln)
        if not done:
            fails.append(f"[G04 {fam}] child died rc={r.returncode}: "
                         f"{r.stdout[-400:]} {r.stderr[-300:]}")
            lines.append(f"  [FAIL] G04 {fam}: child rc={r.returncode}")


# ── card 011 G8: duplicate-name rejection (driver bookkeeping, code 11) ─────
# Kernel: check_name (K/environment.cpp:102-105) runs inside check_constant_val
# (:128) on EVERY add_* path — BEFORE is_prop (add_theorem :200-202), before
# the value checks, and before check_duplicated_univ_params (:129, G9 below).
# A duplicate name throws the dedicated `already_declared_exception` (class
# alreadyDeclared, K/kernel_exception.h:32-37, catch at :168-169); the Lean-side
# rendering is "constant has already been declared '<n>'"
# (src/Lean/Message.lean:896).  Driver side: InjectionEnv._check_name raises
# VMError(ERR_ALREADY_DECLARED) BEFORE any graph pass — the graph has no name
# space, so like the code-9 mutual-WF family this is environment bookkeeping.
# The oracle environment already carries g8b_a/g8b_d/g8b_t (G8_BASE_DEFS, all
# so a #KDECL re-add hits the kernel's check_name for real.
G8_ROW_IDS = {"g8axm_new", "g8axm_dup", "g8def_new", "g8def_dup",
              "g8def_dup_badbody", "g8thm_new", "g8thm_dup",
              "g8thm_dup_nonprop"}
# class → graph code for the G8 rows (a dedicated class name — no "other"
# ambiguity: alreadyDeclared maps 1:1)
G8_CODE_OF_CLASS = {"OK": 0, "alreadyDeclared": 11}

G8_ORACLE_CASES = [
    # accept legs: fresh names on all three kinds (also the graph-check
    # positive — the driver must still RUN the check for a new name)
    ("g8axm_new", _AXM.format("g8f_ax", E_NAT)),
    ("g8def_new", _DEF.format("g8f_df", E_NAT, E_TWO)),
    ("g8thm_new", _THM.format("g8f_th", E_TRUE, E_TRIVIAL)),
    # reject legs: the three kinds' base names
    ("g8axm_dup", _AXM.format("g8b_a", E_NAT)),
    ("g8def_dup", _DEF.format("g8b_d", E_NAT, E_TWO)),
    ("g8thm_dup", _THM.format("g8b_t", E_TRUE, E_TRIVIAL)),
    # ordering legs: a duplicate name whose payload would ALSO fail
    # independently — the kernel reports alreadyDeclared, not 1/8
    # (measured probe p2/p3, 2026-09-21: name check precedes is_prop and
    # the value check)
    ("g8def_dup_badbody", _DEF.format("g8b_d", E_NAT, E_TRUE)),
    ("g8thm_dup_nonprop", _THM.format("g8b_t", E_NAT, E_TWO)),
]


def build_g8_oracle() -> dict[str, str]:
    cls = lean_ref.run_kdecl_oracle(ALL_DEFS, G8_ORACLE_CASES,
                                    lean_cmd=LEAN_CMD)
    return dict(zip([c for c, _ in G8_ORACLE_CASES], cls))


def section_g8(fails, lines, consts, ctors):
    """Duplicate-name injection vs the live #KDECL oracle."""
    oracle = build_g8_oracle()
    for cid, cls in oracle.items():
        print(f"  oracle[{cid}] = {cls}")

    def want(cid):
        cls = oracle.get(cid)
        return None if cls is None else G8_CODE_OF_CLASS.get(cls, -1)

    # (row id, driver fn, registered name on the accept legs)
    g8_rows = [
        ("g8axm_new", lambda i: i.add_axiom("g8f_ax", NAT), "g8f_ax"),
        ("g8axm_dup", lambda i: i.add_axiom("g8b_a", NAT), None),
        ("g8def_new", lambda i: i.add_definition("g8f_df", NAT, LitNat(2)),
         "g8f_df"),
        ("g8def_dup", lambda i: i.add_definition("g8b_d", NAT, LitNat(2)),
         None),
        ("g8def_dup_badbody",
         lambda i: i.add_definition("g8b_d", NAT, TRUE), None),
        ("g8thm_new",
         lambda i: i.add_theorem("g8f_th", TRUE, TRIVIAL), "g8f_th"),
        ("g8thm_dup", lambda i: i.add_theorem("g8b_t", TRUE, TRIVIAL),
         None),
        ("g8thm_dup_nonprop",
         lambda i: i.add_theorem("g8b_t", NAT, LitNat(2)), None),
    ]
    for cid, fn, reg_name in g8_rows:
        inj = _inj_env(consts, ctors)
        try:
            fn(inj)
            got, detail = 0, "accept"
        except VMError as ex:
            got, detail = ex.code, str(ex)
        wantc = want(cid)
        ok = wantc is not None and got == wantc
        extra = ""
        if ok and reg_name is not None:
            # accept leg: the declaration must actually register
            if not inj.contains(reg_name):
                ok, extra = False, " NOT REGISTERED"
        elif ok:
            # reject leg: pure bookkeeping — zero graph passes, and the
            # driver message mirrors the kernel's text
            if inj.steps_last != 0:
                ok, extra = False, f" (graph ran: steps={inj.steps_last})"
            elif "constant has already been declared" not in detail:
                ok, extra = False, " (message does not mirror the kernel)"
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] G8 {cid}: "
                     f"oracle={oracle.get(cid)} graph=code={got}"
                     f"({CLASS_OF_CODE.get(got, '?')}) steps={inj.steps_last}"
                     f"{extra}")
        if not ok:
            fails.append(f"[G8 {cid}] oracle={oracle.get(cid)} "
                         f"graph=code={got} detail={detail}")


# ── card 011 G9: duplicate universe level parameters (graph arm, code 10) ──
# Kernel: check_duplicated_univ_params (K/environment.cpp:111-121) runs inside
# check_constant_val at :129 — AFTER check_name (:128, G8) and BEFORE
# check_no_metavar_no_fvar (:130) and the type checker (:131-133).  A hit
# throws a plain kernel_exception ("failed to add declaration to environment,
# duplicate universe level parameter: '<p>'") → class .other.  The graph has
# no name space (rule 3): each declaration's lparams ride a
# T_ENV_LIST(role=2) chain (emit_univparams, VM_SPEC §12.1) whose head enters
# on the TASK_CHECK anchor's F2 slot; the O(n²) pairwise scan compares
# interred nids (V1) and rejects with new code 10.  Driver bookkeeping
# (check_name → code 11) runs BEFORE any graph pass, so a duplicate NAME with
# duplicate lparams reports alreadyDeclared, not 10 — kernel order (:128 <
# :129).  The class map is unambiguous per section: every row is either a
# clean accept (OK→0) or a dup-univ declaration (other→10); the "other"→7
# leg belongs to g03 and lives in that section.
_AXM_LP = (".axiomDecl {{ name := `{}, levelParams := [{}], type := {}, "
           "isUnsafe := false }}")
_DEF_LP = (".defnDecl {{ name := `{}, levelParams := [{}], type := {}, "
           "value := {}, hints := ReducibilityHints.regular 0, "
           "safety := DefinitionSafety.safe }}")
_THM_LP = (".thmDecl {{ name := `{}, levelParams := [{}], type := {}, "
           "value := {} }}")

G9_ROW_IDS = {"g9axm_new", "g9axm_dup", "g9def_new", "g9def_dup",
              "g9def_dup_badbody", "g9thm_new", "g9thm_dup",
              "g9thm_dup_nonprop", "g9name_lp"}
G9_CODE_OF_CLASS = {"OK": 0, "other": 10, "alreadyDeclared": 11}

G9_ORACLE_CASES = [
    # accept legs: fresh names with a non-duplicate single lparam
    ("g9axm_new", _AXM_LP.format("g9f_ax", "`u", E_NAT)),
    ("g9def_new", _DEF_LP.format("g9f_df", "`u", E_NAT, E_TWO)),
    ("g9thm_new", _THM_LP.format("g9f_th", "`u", E_TRUE, E_TRIVIAL)),
    # reject legs: the same name twice in levelParams
    ("g9axm_dup", _AXM_LP.format("g9f_ax2", "`u, `u", E_NAT)),
    ("g9def_dup", _DEF_LP.format("g9f_df2", "`u, `u", E_NAT, E_TWO)),
    ("g9thm_dup", _THM_LP.format("g9f_th2", "`u, `u", E_TRUE, E_TRIVIAL)),
    # ordering legs: the dup-univ scan (:129) precedes the value check
    # (:132-133) and is_prop (add_theorem :200-202) — measured probe
    # 2026-09-21: class "other" on all three
    ("g9def_dup_badbody", _DEF_LP.format("g9f_df3", "`u, `u", E_NAT, E_TRUE)),
    ("g9thm_dup_nonprop", _THM_LP.format("g9f_th3", "`u, `u", E_NAT, E_TWO)),
    # ordering leg vs G8: a duplicate NAME (+ duplicate lparams) reports
    # alreadyDeclared — check_name (:128) runs before the dup-univ scan (:129)
    ("g9name_lp", _AXM_LP.format("g8b_a", "`u, `u", E_NAT)),
]


def build_g9_oracle() -> dict[str, str]:
    cls = lean_ref.run_kdecl_oracle(ALL_DEFS, G9_ORACLE_CASES,
                                    lean_cmd=LEAN_CMD)
    return dict(zip([c for c, _ in G9_ORACLE_CASES], cls))


def section_g9(fails, lines, consts, ctors):
    """Duplicate universe level parameters vs the live #KDECL oracle."""
    oracle = build_g9_oracle()
    for cid, cls in oracle.items():
        print(f"  oracle[{cid}] = {cls}")

    def want(cid):
        cls = oracle.get(cid)
        return None if cls is None else G9_CODE_OF_CLASS.get(cls, -1)

    # (row id, driver fn, registered name on the accept legs, must be a
    #  GRAPH reject).  The dup-univ reject is a graph verdict (the scan ran,
    #  steps > 0), unlike G8's pure-bookkeeping rejects — except g9name_lp,
    #  which IS driver bookkeeping (code 11, zero graph passes).
    g9_rows = [
        ("g9axm_new", lambda i: i.add_axiom("g9f_ax", NAT, lparams=["u"]),
         "g9f_ax", False),
        ("g9axm_dup",
         lambda i: i.add_axiom("g9f_ax2", NAT, lparams=["u", "u"]),
         None, True),
        ("g9def_new",
         lambda i: i.add_definition("g9f_df", NAT, LitNat(2), lparams=["u"]),
         "g9f_df", False),
        ("g9def_dup",
         lambda i: i.add_definition("g9f_df2", NAT, LitNat(2),
                                    lparams=["u", "u"]),
         None, True),
        ("g9def_dup_badbody",
         lambda i: i.add_definition("g9f_df3", NAT, TRUE, lparams=["u", "u"]),
         None, True),
        ("g9thm_new",
         lambda i: i.add_theorem("g9f_th", TRUE, TRIVIAL, lparams=["u"]),
         "g9f_th", False),
        ("g9thm_dup",
         lambda i: i.add_theorem("g9f_th2", TRUE, TRIVIAL, lparams=["u", "u"]),
         None, True),
        ("g9thm_dup_nonprop",
         lambda i: i.add_theorem("g9f_th3", NAT, LitNat(2), lparams=["u", "u"]),
         None, True),
        ("g9name_lp",
         lambda i: i.add_axiom("g8b_a", NAT, lparams=["u", "u"]),
         None, False),
    ]
    for cid, fn, reg_name, want_graph in g9_rows:
        inj = _inj_env(consts, ctors)
        try:
            fn(inj)
            got, detail = 0, "accept"
        except VMError as ex:
            got, detail = ex.code, str(ex)
        wantc = want(cid)
        ok = wantc is not None and got == wantc
        extra = ""
        if ok and reg_name is not None:
            # accept leg: the declaration must actually register
            if not inj.contains(reg_name):
                ok, extra = False, " NOT REGISTERED"
        elif ok and got != 0:
            # reject leg: the scan must have actually RUN (graph arm) — except
            # the G8×G9 ordering row, which is driver bookkeeping
            if want_graph and inj.steps_last == 0:
                ok, extra = False, " (graph never ran)"
            if not want_graph and inj.steps_last != 0:
                ok, extra = False, f" (graph ran: steps={inj.steps_last})"
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] G9 {cid}: "
                     f"oracle={oracle.get(cid)} graph=code={got}"
                     f"({CLASS_OF_CODE.get(got, '?')}) steps={inj.steps_last}"
                     f"{extra}")
        if not ok:
            fails.append(f"[G9 {cid}] oracle={oracle.get(cid)} "
                         f"graph=code={got} detail={detail}")


def main() -> int:
    t0 = time.perf_counter()
    only = {s.strip() for s in os.environ.get("G02_ONLY", "").split(",")
            if s.strip()}
    fam = os.environ.get("G04_FAMILY")
    if fam:
        # child protocol: one family, in-process, machine-readable lines
        fails: list[str] = []
        lines: list[str] = []
        _g04_family(fam, set(), fails, lines)
        for ln in lines:
            print(ln)
        for m in fails:
            print("G04X " + m)
        print(f"G04-DONE rc={1 if fails else 0}")
        return 1 if fails else 0
    g2_rows = {c for c in only if c in ROWS_BY_ID or
               c.startswith("chain_")}
    g6_rows = {c for c in only if c in G6_ROW_IDS}
    g3_rows = {c for c in only if c in G3_ROW_IDS}
    g4_rows = {c for c in only if c in G04_ROW_IDS}
    g8_rows = {c for c in only if c in G8_ROW_IDS}
    g9_rows = {c for c in only if c in G9_ROW_IDS}
    want_rows = g2_rows | g6_rows
    fails: list[str] = []
    lines: list[str] = []
    lean_bin = LEAN_CMD[0] if LEAN_CMD else str(lean_ref.LEAN)
    print(f"oracle binary: "
          f"{os.popen(f'{lean_bin} --version 2>&1').read().strip()}")
    print(f"oracle channel: #KDECL → Lean.Kernel.Environment.addDecl "
          f"({lean_bin}); generated file "
          f"/tmp/vm_kdecl_oracle.lean")
    consts, ctors, structs = import_env(
        ALL_DEFS, MY_ROOTS,
        dump=dump_env(ALL_DEFS, MY_ROOTS, path=DUMP_PATH,
                      lean_cmd=LEAN_CMD))
    print(f"graph env: {len(consts)} consts ({len(ctors)} ctors, "
          f"{len(structs)} structs)")
    for nm in ("injX_imax", "injX_max", "injD_imax", "injD_max",
               "g06v_f", "g06v_g"):
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
    if run_all or (only & {"bcd", "b", "c", "d"}) or g2_rows:
        print("bcd   kind gate + threading + level forms vs live #KDECL oracle")
        oracle = build_oracle()
        for cid, cls in oracle.items():
            print(f"  oracle[{cid}] = {cls}")
        section_bcd(fails, lines, consts, ctors, oracle, g2_rows)
    if run_all or "g6" in only or g6_rows:
        print("g6    mutual blocks: well-formedness (code 9), "
              "register-before-check, rollback vs live #KDECL oracle")
        section_g6(fails, lines, consts, ctors)
    if run_all or "g03" in only or g3_rows:
        print("g03   unsafe-mode checker arm: self-reference, later safe "
              "reference, rollback vs live #KDECL oracle")
        section_g03(fails, lines, consts, ctors)
    if run_all or "g04" in only or g4_rows:
        print("g04   driver-side run_whnf (ADR016-B): G1/a1 carriers, "
              "final result vs live #ORACLE WHNF")
        section_g04(fails, lines, g4_rows)
    if run_all or "g8" in only or g8_rows:
        print("g8    duplicate-name injection: code 11 (alreadyDeclared), "
              "three kinds + name-first ordering vs live #KDECL oracle")
        section_g8(fails, lines, consts, ctors)
    if run_all or "g9" in only or g9_rows:
        print("g9    duplicate universe level parameters: graph O(n²) scan "
              "(code 10, anchor F2 carrier) vs live #KDECL oracle")
        section_g9(fails, lines, consts, ctors)
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
