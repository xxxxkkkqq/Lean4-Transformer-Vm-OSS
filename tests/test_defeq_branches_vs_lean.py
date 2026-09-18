"""Card 007 (WP7) differential: is_def_eq remaining branches + decl errors.

Ground truth channels (acceptance rule 1 — oracle only, never a fixture):
  (A) DEFEQ pairs: raw ``Kernel.isDefEq env {} t s`` (the exact
      K/type_checker.cpp:1165 entry the graph models; NOT Meta.isDefEq —
      @[reducible]/@[irreducible] are elaborator concepts, kernel hints are
      only Opaque/Abbrev/Regular, K/declaration.h:244-252).
  (B) G-group decls: ``Kernel.Environment.addDecl`` full exception class
      (K/environment.cpp:87-95,127-133 / K/type_checker.cpp:62-70).

Graph side: the step graph (build_step_graph + StepDriver.run_defeq /
run_check) over a MINIMAL env (toy consts + the handful of WP7 defs —
feedback-loop rule: no big env here; the 4000-const env is the final
regression's job).

Three arms:
  A15/A26/A14/A17 pairs on the legacy stream (rules 3: metadata must not be
     required for correctness);
  the same pairs on the meta=1 stream built from the REAL lean olean dump
     (ENV-driven hints proof: the A17 args fast path only exists on meta —
     h1 must take strictly fewer steps there);
  G cases: graph reject code must equal the kernel category map
     (typeExpected→5, declHasFVars/declHasMVars→6, declTypeMismatch→1,
     OK→accept; docs/VM_SPEC.md §7.4).

Run (memory discipline, AGENTS.md):
  setsid nohup env OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u \
      tests/test_defeq_branches_vs_lean.py > $HOME/logs/defeq_branches.log 2>&1 < /dev/null &
then poll RSS (kill > 6GB).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import (App, Const, FVar, Lam, LitNat, MVar, BVar,
                        BI_DEFAULT, Proj, Pi)
from expr.tokens import Encoder
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver, VMError
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_LEAN_DEFS, NAT, _pi_nat_nat

LEAN = os.path.expanduser("~/.elan/bin/lean")

N = LitNat


def _A(f, *xs):
    for x in xs:
        f = App(f, x)
    return f


# defs shared by oracle and encoder — nothing preseeded, both sides compile
# THIS text (rule 2: expectations come from the live binary at run time).
WP7_DEFS = """
def T_q33 : P2 := P2.mk 3 3
def T_q53 : P2 := P2.mk 5 3
def T_q44 : P2 := P2.mk 4 4
def T_two2 : Nat := 2
@[reducible] def R_dbl : Nat → Nat := fun (x : Nat) => Nat.add x x
@[irreducible] def I_dbl : Nat → Nat := fun (x : Nat) => Nat.add x x
partial def T_part : Nat → Nat := fun (n : Nat) => T_part (Nat.sub n 1)
unsafe def T_uns : Nat := 5
"""

DEFS = TOY_LEAN_DEFS + "\n" + WP7_DEFS

EXTRA = [
    ("T_q33", Const("P2"), _A(Const("P2.mk"), N(3), N(3))),
    ("T_q53", Const("P2"), _A(Const("P2.mk"), N(5), N(3))),
    ("T_q44", Const("P2"), _A(Const("P2.mk"), N(4), N(4))),
    ("T_two2", NAT, N(2)),
    ("R_dbl", _pi_nat_nat(), Lam("x", BI_DEFAULT, NAT,
                                 _A(Const("Nat.add"), BVar(0), BVar(0)))),
    ("I_dbl", _pi_nat_nat(), Lam("x", BI_DEFAULT, NAT,
                                 _A(Const("Nat.add"), BVar(0), BVar(0)))),
    # WP7-G10 mirrors (value never taken as the unfolding source in this
    # test — the graph must reject the REFERENCE before any delta): the real
    # safety flags ride the meta stream from the kernel dump.  T_part itself
    # dumps as OpaqueInfo (4.33.1, see G_CASES comment); the safety=partial
    # data lives on the generated _unsafe_rec shadow.
    ("T_part", _pi_nat_nat(), Lam("n", BI_DEFAULT, NAT,
                                  _A(Const("Nat.sub"), BVar(0), N(1)))),
    ("T_part._unsafe_rec", _pi_nat_nat(), Lam("n", BI_DEFAULT, NAT,
                                              _A(Const("Nat.sub"), BVar(0),
                                                 N(1)))),
    ("T_uns", NAT, N(5)),
]
CONSTS = list(TOY_CONSTS) + EXTRA
NAMES = [n for n, _, _ in CONSTS]

# (id, lhs_src, rhs_src, lhs_ast, rhs_ast, branch)  — WP7 A-group corpus
CASES = [
    # A15 (K:1216-1227 + :1193) — non-committing proj attempts
    ("j1_same_def_diffidx", "T_q33.1", "T_q33.2",
     Proj("P2", 0, Const("T_q33")), Proj("P2", 1, Const("T_q33")), "A15"),
    ("j2_diff_def_sameidx_fieldeq", "T_q53.2", "T_q33.2",
     Proj("P2", 1, Const("T_q53")), Proj("P2", 1, Const("T_q33")), "A15"),
    ("j3_diff_def_sameidx_fieldne", "T_q53.1", "T_q33.1",
     Proj("P2", 0, Const("T_q53")), Proj("P2", 0, Const("T_q33")), "A15"),
    ("j4_ctor_child_no_delta", "T_q33.1", "T_q44.1",
     Proj("P2", 0, Const("T_q33")), Proj("P2", 0, Const("T_q44")), "A15"),
    ("j5_proj_vs_lit_direct", "T_q33.1", "3",
     Proj("P2", 0, Const("T_q33")), N(3), "A15/A30"),
    # A26 (K:1076-1085)
    ("o1_succ_delta_args", "Nat.succ (T_dbl 2)", "Nat.succ (Nat.add 3 1)",
     _A(Const("Nat.succ"), _A(Const("T_dbl"), N(2))),
     _A(Const("Nat.succ"), _A(Const("Nat.add"), N(3), N(1))), "A26"),
    ("o2_succ_lit_chain", "10", "Nat.succ (Nat.succ 8)",
     N(10), _A(Const("Nat.succ"), _A(Const("Nat.succ"), N(8))), "A26"),
    ("o3_succ_vs_lit_fail", "Nat.succ 3", "5",
     _A(Const("Nat.succ"), N(3)), N(5), "A26"),
    # A14 (K:1181-1185)
    ("r1_refl_beq_true", "Nat.beq 4 4", "true",
     _A(Const("Nat.beq"), N(4), N(4)), Const("Bool.true"), "A14"),
    ("r2_refl_delta_arg", "Nat.beq T_two2 2", "true",
     _A(Const("Nat.beq"), Const("T_two2"), N(2)), Const("Bool.true"), "A14"),
    ("r3_refl_false_side", "Nat.beq 4 5", "true",
     _A(Const("Nat.beq"), N(4), N(5)), Const("Bool.true"), "A14"),
    ("r4_refl_swapped", "true", "Nat.beq 4 4",
     Const("Bool.true"), _A(Const("Nat.beq"), N(4), N(4)), "A14"),
    # A17 (K:1032-1045) — h3 pairs the raw-kernel channel (True), NOT Meta
    ("h1_args_fastpath", "T_dbl (Nat.add 3 5)", "T_dbl 8",
     _A(Const("T_dbl"), _A(Const("Nat.add"), N(3), N(5))),
     _A(Const("T_dbl"), N(8)), "A17"),
    ("h2_args_ne", "T_dbl 3", "T_dbl 4",
     _A(Const("T_dbl"), N(3)), _A(Const("T_dbl"), N(4)), "A17"),
    ("h3_mixed_hints", "R_dbl 2", "I_dbl 2",
     _A(Const("R_dbl"), N(2)), _A(Const("I_dbl"), N(2)), "A17"),
    ("h4_red_vs_regular", "R_dbl (T_dbl 2)", "T_dbl 4",
     _A(Const("R_dbl"), _A(Const("T_dbl"), N(2))),
     _A(Const("T_dbl"), N(4)), "A17"),
]

# G corpus: (id, kernel addDecl source, graph type expr, graph value expr,
#            expected category mapping computed at run time, meta_only).
# meta_only cases run the graph arm on the meta=1 stream: their gate is
# ENV-safety-metadata driven and a legacy stream carries no safety data, so
# the kernel category map applies only where the channel has the bits
# (acceptance rule 3 — data absence, not a name/cid branch; VM_SPEC §16.3).
# val=None on the graph side encodes as anchor X=0 = "no value" (axiom
# shape, kernel axiom_val has no value field — WP7-G5).
G_CASES = [
    ("g0_accept_add",
     ".defnDecl { name := `G0x, levelParams := [], "
     "type := Lean.mkConst ``Nat, value := Lean.mkNatLit 4, "
     "hints := .regular 0, safety := .safe, all := [`G0x] }",
     NAT, N(4), {"OK"}, False),
    ("g1_type_lit",
     ".defnDecl { name := `G1x, levelParams := [], "
     "type := Lean.mkNatLit 5, value := Lean.mkNatLit 3, "
     "hints := .regular 0, safety := .safe, all := [`G1x] }",
     N(5), N(3), {"typeExpected"}, False),
    ("g1b_type_lam",
     ".defnDecl { name := `G1bx, levelParams := [], "
     "type := Lean.mkLambda `x .default (Lean.mkConst ``Nat) (Lean.mkConst ``Nat), "
     "value := Lean.mkNatLit 3, "
     "hints := .regular 0, safety := .safe, all := [`G1bx] }",
     Lam("x", BI_DEFAULT, NAT, Const("Nat")), N(3), {"typeExpected"}, False),
    ("g7_fvar_type",
     ".axiomDecl { name := `G7fx, levelParams := [], "
     "type := Lean.mkFVar ⟨.str .anonymous \"p\"⟩, isUnsafe := false }",
     FVar("p"), None, {"declHasFVars"}, False),
    ("g7_mvar_type",
     ".axiomDecl { name := `G7mx, levelParams := [], "
     "type := Lean.mkMVar ⟨.str .anonymous \"m\"⟩, isUnsafe := false }",
     MVar("m"), None, {"declHasMVars"}, False),
    ("g7_mvar_value",
     ".defnDecl { name := `G7mv, levelParams := [], "
     "type := Lean.mkConst ``Nat, value := Lean.mkMVar ⟨.str .anonymous \"m\"⟩, "
     "hints := .regular 0, safety := .safe, all := [`G7mv] }",
     NAT, MVar("m"), {"declHasMVars"}, False),
    ("g7_fvar_value",
     ".defnDecl { name := `G7fv, levelParams := [], "
     "type := Lean.mkConst ``Nat, value := Lean.mkFVar ⟨.str .anonymous \"p\"⟩, "
     "hints := .regular 0, safety := .safe, all := [`G7fv] }",
     NAT, FVar("p"), {"declHasFVars"}, False),
    ("g2_def_mismatch",
     ".defnDecl { name := `G2x, levelParams := [], "
     "type := Lean.mkConst ``Nat, value := Lean.mkConst ``True.intro, "
     "hints := .regular 0, safety := .safe, all := [`G2x] }",
     NAT, Const("True.intro"), {"declTypeMismatch"}, False),
    # WP7-G4: add_opaque's check sequence is LINE-FOR-LINE the safe
    # add_definition sequence (K/environment.cpp:211-223 vs :177-184), so the
    # kernel category for an opaque mismatch must also be declTypeMismatch and
    # the graph reaches it through the same value-infer + defeq arm.
    ("g4_opaque_mismatch",
     ".opaqueDecl { name := `G4x, levelParams := [], "
     "type := Lean.mkConst ``Nat, value := Lean.mkConst ``True.intro, "
     "isUnsafe := false, all := [`G4x] }",
     NAT, Const("True.intro"), {"declTypeMismatch"}, False),
    # WP7-G5: add_axiom checks ONLY the header (K/environment.cpp:152-158):
    # a function type must ACCEPT — the old dummy-value arm rejected it with
    # declTypeMismatch, which is exactly the divergence this case pins.
    # Lean.mkForall is the 4.33.1 constructor (src/Lean/Expr.lean:680).
    ("g5_axiom_funtype_ok",
     ".axiomDecl { name := `G5fx, levelParams := [], "
     "type := Lean.mkForall `n .default (Lean.mkConst ``Nat) (Lean.mkConst ``Nat), "
     "isUnsafe := false }",
     Pi("n", BI_DEFAULT, NAT, NAT), None, {"OK"}, False),
    ("g5_axiom_type_lit",
     ".axiomDecl { name := `G5tx, levelParams := [], "
     "type := Lean.mkNatLit 5, isUnsafe := false }",
     N(5), None, {"typeExpected"}, False),
    # WP7-G10 (K/type_checker.cpp:110-117): safe decl referencing partial /
    # unsafe constant → kernel_exception .other, new graph code 7.
    # 4.33.1 reality (verified live): an elaborated `partial def` is stored
    # as OpaqueInfo (toolchain src Lean/Elab/PreDefinition/Main.lean:20-37
    # rewrites kind:=DefKind.opaque with an inhabitant value), and the real
    # safety=partial constant is the generated `T_part._unsafe_rec` shadow
    # (Elab/PreDefinition/Basic.lean:280-296, Compiler/Old.lean:47-48).
    # Referencing the plain name is ACCEPT (opaque carries no safety);
    # referencing the shadow throws the partial message.
    ("g10_partial_plain_ok",
     ".defnDecl { name := `G10q, levelParams := [], "
     "type := Lean.mkConst ``Nat, "
     "value := Lean.mkApp (Lean.mkConst ``T_part) (Lean.mkNatLit 2), "
     "hints := .regular 0, safety := .safe, all := [`G10q] }",
     NAT, _A(Const("T_part"), N(2)), {"OK"}, False),
    ("g10_partial_use",
     ".defnDecl { name := `G10p, levelParams := [], "
     "type := Lean.mkConst ``Nat, "
     "value := Lean.mkApp (Lean.mkConst `T_part._unsafe_rec) (Lean.mkNatLit 2), "
     "hints := .regular 0, safety := .safe, all := [`G10p] }",
     NAT, _A(Const("T_part._unsafe_rec"), N(2)),
     {"other: invalid declaration, safe declaration must not contain partial"},
     True),
    ("g10_unsafe_use",
     ".defnDecl { name := `G10u, levelParams := [], "
     "type := Lean.mkConst ``Nat, value := Lean.mkConst ``T_uns, "
     "hints := .regular 0, safety := .safe, all := [`G10u] }",
     NAT, Const("T_uns"),
     {"other: invalid declaration, it uses unsafe declaration"}, True),
    # control: the gate must stay closed for safe constants
    ("g10_safe_control",
     ".defnDecl { name := `G10s, levelParams := [], "
     "type := Lean.mkConst ``Nat, "
     "value := Lean.mkApp (Lean.mkConst ``T_dbl) (Lean.mkNatLit 2), "
     "hints := .regular 0, safety := .safe, all := [`G10s] }",
     NAT, _A(Const("T_dbl"), N(2)), {"OK"}, True),
]

# kernel exception class → graph reject code (docs/VM_SPEC.md §7.4)
G_CODE = {"typeExpected": 5, "declHasFVars": 6, "declHasMVars": 6,
          "declTypeMismatch": 1, "unknownConstant": 2}
# .other sub-classes matched by message prefix (kernel builds plain
# kernel_exception strings; K/type_checker.cpp:110-117)
G_OTHER = [("uses unsafe declaration", 7), ("must not contain partial", 7)]

KDEFEQ_TEMPLATE = """\
import Lean
{imports}open Lean Elab Command Term Meta

{defs}

elab "#KDEFEQ" id:ident "(" a:term "," b:term ")" : command => do
  let (ea, eb) ← liftTermElabM <| do
    let ea ← elabTerm a none
    let eb ← elabTerm b none
    synthesizeSyntheticMVarsNoPostponing
    let ea ← instantiateMVars ea
    let eb ← instantiateMVars eb
    pure (ea, eb)
  if ea.hasMVar || eb.hasMVar then
    IO.println ("KDEFEQ " ++ id.getId.toString ++ " HASMVARS")
  else
    let env ← getEnv
    let lctx : LocalContext := {{}}
    match Kernel.isDefEq env lctx ea eb with
    | .ok r => IO.println ("KDEFEQ " ++ id.getId.toString ++ " " ++ toString r)
    | .error _ => IO.println ("KDEFEQ " ++ id.getId.toString ++ " THREW")
"""

KDECL_MSG_TEMPLATE = """\
import Lean
{imports}open Lean Elab Command Term Meta

{defs}

def classHead : Kernel.Exception → String
  | .unknownConstant .. => "unknownConstant"
  | .alreadyDeclared .. => "alreadyDeclared"
  | .declTypeMismatch .. => "declTypeMismatch"
  | .declHasMVars .. => "declHasMVars"
  | .declHasFVars .. => "declHasFVars"
  | .funExpected .. => "funExpected"
  | .typeExpected .. => "typeExpected"
  | .letTypeMismatch .. => "letTypeMismatch"
  | .exprTypeMismatch .. => "exprTypeMismatch"
  | .appTypeMismatch .. => "appTypeMismatch"
  | .invalidProj .. => "invalidProj"
  | .thmTypeIsNotProp .. => "thmTypeIsNotProp"
  | .other m => "other: " ++ m
  | .deterministicTimeout => "deterministicTimeout"
  | .excessiveMemory => "excessiveMemory"
  | .deepRecursion => "deepRecursion"
  | .interrupted => "interrupted"

elab "#KDECLMSG" id:ident d:term : command => do
  let decl ← liftTermElabM <| do
    let e ← elabTerm d (some (Lean.mkConst ``Declaration))
    let e ← instantiateMVars e
    unsafe Meta.evalExpr Declaration (Lean.mkConst ``Declaration) e
  match Kernel.Environment.addDecl (← getEnv).toKernelEnv (← getOptions) decl with
  | .ok _ => IO.println ("KDECLMSG " ++ id.getId.toString ++ " OK")
  | .error ex => IO.println ("KDECLMSG " ++ id.getId.toString ++
      " " ++ classHead ex)
"""


def run_lean(src: str, tag: str) -> dict[str, str]:
    path = f"/tmp/test_defeq_branches_{tag}.lean"
    with open(path, "w") as f:
        f.write(src)
    r = subprocess.run([LEAN, path], capture_output=True, text=True,
                       timeout=600)
    out = {}
    for line in r.stdout.splitlines():
        p = line.split(None, 2)
        if len(p) >= 3 and p[0] in ("KDEFEQ", "KDECLMSG"):
            out[f"{p[0]} {p[1]}"] = p[2]
    if r.returncode != 0:
        print(f"[{tag}] lean rc={r.returncode}")
        print((r.stderr or r.stdout)[:3000])
        raise RuntimeError(f"lean failed on {tag}")
    return out


def _split_defs(text):
    imps = "".join(ln + "\n" for ln in text.splitlines()
                   if ln.strip().startswith("import "))
    rest = "\n".join(ln for ln in text.splitlines()
                     if not ln.strip().startswith("import "))
    return imps, rest


def defeq_graph(enc_cls_kwargs, graph, outputs, cid, l, r):
    enc = Encoder(CONSTS, is_ctor=TOY_CTORS, **enc_cls_kwargs)
    drv = StepDriver(enc.b, graph, outputs)
    lp = enc.encode_term(l)
    rp = enc.encode_term(r)
    got = bool(drv.run_defeq(lp, 0, rp, 0, max_steps=8000)[0])
    return got, drv.steps


def main() -> int:
    fails = 0
    imps, rest = _split_defs(DEFS)

    # ── oracle (A): raw kernel isDefEq on the A-group pairs ────────────────
    src = KDEFEQ_TEMPLATE.format(imports=imps, defs=rest)
    for cid, lsrc, rsrc, *_ in CASES:
        src += f"\n#KDEFEQ {cid} ({lsrc}, {rsrc})"
    kern = run_lean(src, "kdefeq")

    # ── oracle (B): addDecl exception classes on the G corpus ──────────────
    srcg = KDECL_MSG_TEMPLATE.format(imports=imps, defs=rest)
    for cid, dsrc, *_ in G_CASES:
        srcg += f"\n#KDECLMSG {cid} ({dsrc})"
    kdecl = run_lean(srcg, "kdecl")
    print("building graph...")
    graph, outputs = build_step_graph()

    # ── arm 1: legacy stream — verdicts must equal the kernel ─────────────
    legacy_steps = {}
    for cid, _, _, l, r, branch in CASES:
        kv = kern.get(f"KDEFEQ {cid}", "MISSING")
        assert kv in ("true", "false"), f"{cid}: kernel channel {kv}"
        got, steps = defeq_graph({}, graph, outputs, cid, l, r)
        legacy_steps[cid] = steps
        ok = got == (kv == "true")
        fails += (not ok)
        print(f"  [legacy {branch:8s}] {cid:28s} kernel={kv:5s} "
              f"graph={got} steps={steps} {'OK' if ok else '<<< DIVERGE'}")

    # ── arm 2: meta=1 stream from the real olean dump ─────────────────────
    from reference.olean_export import dump_env, const_meta_for
    meta = const_meta_for(CONSTS, dump_env(DEFS, NAMES))
    for cid, _, _, l, r, branch in CASES:
        kv = kern.get(f"KDEFEQ {cid}", "MISSING")
        got, steps = defeq_graph({"const_meta": meta}, graph, outputs, cid, l, r)
        ok = got == (kv == "true")
        fails += (not ok)
        print(f"  [meta   {branch:8s}] {cid:28s} kernel={kv:5s} "
              f"graph={got} steps={steps} {'OK' if ok else '<<< DIVERGE'}")
        if cid == "h1_args_fastpath":
            fast = steps < legacy_steps[cid]
            fails += (not fast)
            print(f"      A17 ENV-gate proof: meta {steps} < legacy "
                  f"{legacy_steps[cid]} {'OK' if fast else '<<< FAIL'}")

    # ── arm 3: G corpus — reject code vs kernel exception class ───────────
    for cid, _, ty, val, expect_cls, meta_only in G_CASES:
        cls = kdecl.get(f"KDECLMSG {cid}", "MISSING")
        base = cls.split(":", 1)[0]
        if base.startswith("other"):
            base = cls  # keep full .other message for reporting
        matched = any(base == e or (e.startswith("other:")
                                    and base.startswith(e))
                      for e in expect_cls)
        assert matched, \
            f"{cid}: kernel live class '{base}' not in declared set {expect_cls}"
        if base == "OK":
            exp_code = 0
        elif base in G_CODE:
            exp_code = G_CODE[base]
        else:
            exp_code = next((c for pref, c in G_OTHER
                             if base.startswith("other") and pref in base), -1)
        assert exp_code >= 0, f"{cid}: unmapped kernel class {cls}"
        if meta_only:
            # G10's data lives only in the meta stream (anchor.F2); the
            # legacy stream has no safety bits to gate on (VM_SPEC §16.3).
            enc = Encoder(CONSTS, is_ctor=TOY_CTORS, const_meta=meta)
        else:
            enc = Encoder(CONSTS, is_ctor=TOY_CTORS)
        drv = StepDriver(enc.b, graph, outputs)
        t = enc.encode_term(ty)
        # val=None: NO value root (axiom shape, anchor X=0 — WP7-G5)
        v = enc.encode_term(val) if val is not None else 0
        code = None
        try:
            drv.run_check([(t, v)], max_steps=50000)
            got = 0
        except VMError as e:
            got = e.code
        ok = got == exp_code
        fails += (not ok)
        print(f"  [G{'m' if meta_only else ' '}     ] "
              f"{cid:20s} kernel={base:46s} expect={exp_code} "
              f"graph={got} steps={drv.steps} {'OK' if ok else '<<< DIVERGE'}")

    print(f"\n=== defeq branches vs lean: {'ALL OK' if fails == 0 else f'{fails} FAILURES'} ===")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
