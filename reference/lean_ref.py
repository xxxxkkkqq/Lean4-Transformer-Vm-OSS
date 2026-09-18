"""Lean 4 binary as the WHNF oracle (wasm-reference analog).

Generates a Lean file per batch: toy defs + a #ORACLE command per corpus
case; runs `lean`; parses one JSON-ish line per case. K constants are the
canonical numbers from expr/model.py.

Oracle semantics probed on 4.33.1 (2026-08-30):
  - Meta.whnf beta/zeta/delta-reduces and natively reduces Nat binops
    on literals (incl. GMP-scale), Nat.div 5 0 = 0, Nat.mod 5 0 = 5.
  - Unannotated lambda-bound vars leave elaborator mvars -> corpus
    annotates all binders.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from expr.model import (
    BVar, FVar, MVar, Sort, Const, App, Lam, Pi, Let, LitNat, LitStr,
    MData, Proj, LZero, LSucc, LMax, LIMax, LParam, LMVar,
)

LEAN = Path.home() / ".elan" / "bin" / "lean"

ORACLE_TEMPLATE = """\
import Lean
{imports}open Lean Elab Command Term Meta

{defs}

def serLevel : Level → String
  | .zero => "{{\\"k\\":1}}"
  | .succ l => "{{\\"k\\":2,\\"a\\":" ++ serLevel l ++ "}}"
  | .max a b => "{{\\"k\\":3,\\"a\\":" ++ serLevel a ++ ",\\"b\\":" ++ serLevel b ++ "}}"
  | .imax a b => "{{\\"k\\":4,\\"a\\":" ++ serLevel a ++ ",\\"b\\":" ++ serLevel b ++ "}}"
  | .param n => "{{\\"k\\":5,\\"n\\":\\"" ++ n.toString ++ "\\"}}"
  | .mvar n => "{{\\"k\\":6,\\"n\\":\\"" ++ n.name.toString ++ "\\"}}"

partial def serExpr : Expr → String
  | .bvar i => "{{\\"k\\":1,\\"i\\":" ++ toString i ++ "}}"
  | .fvar n => "{{\\"k\\":2,\\"n\\":\\"" ++ n.name.toString ++ "\\"}}"
  | .mvar n => "{{\\"k\\":3,\\"n\\":\\"" ++ n.name.toString ++ "\\"}}"
  | .sort l => "{{\\"k\\":4,\\"l\\":" ++ serLevel l ++ "}}"
  | .const n ls => "{{\\"k\\":5,\\"n\\":\\"" ++ n.toString ++ "\\",\\"u\\":[" ++
      String.intercalate "," (ls.map serLevel) ++ "]}}"
  | .app f a => "{{\\"k\\":6,\\"f\\":" ++ serExpr f ++ ",\\"a\\":" ++ serExpr a ++ "}}"
  | .lam _ t b _ => "{{\\"k\\":7,\\"t\\":" ++ serExpr t ++ ",\\"b\\":" ++ serExpr b ++ "}}"
  | .forallE _ t b _ => "{{\\"k\\":8,\\"t\\":" ++ serExpr t ++ ",\\"b\\":" ++ serExpr b ++ "}}"
  | .letE _ t v b _ => "{{\\"k\\":9,\\"t\\":" ++ serExpr t ++ ",\\"v\\":" ++
      serExpr v ++ ",\\"b\\":" ++ serExpr b ++ "}}"
  | .lit l => match l with
      | .natVal v => "{{\\"k\\":10,\\"nat\\":" ++ toString v ++ "}}"
      | .strVal s => "{{\\"k\\":10,\\"str\\":\\"" ++ s ++ "\\"}}"
  | .mdata _ c => "{{\\"k\\":11,\\"c\\":" ++ serExpr c ++ "}}"
  | .proj s i c => "{{\\"k\\":12,\\"s\\":\\"" ++ s.toString ++ "\\",\\"i\\":" ++
      toString i ++ ",\\"c\\":" ++ serExpr c ++ "}}"

elab "#ORACLE" e:term : command => do
  let w ← liftTermElabM <| (do
    let e' ← elabTerm e none
    synthesizeSyntheticMVarsNoPostponing
    let e' ← instantiateMVars e'
    Meta.whnf e')
  IO.println ("ORACLE " ++ serExpr w)

elab "#ORACLE_DEFEQ" a:term "=?=" b:term : command => do
  let r ← liftTermElabM <| (do
    let e1 ← elabTerm a none
    let e2 ← elabTerm b none
    -- numerals leave instance mvars; without synthesis isDefEq spuriously
    -- reports false on every reduction case (probe 2026-09-02)
    synthesizeSyntheticMVarsNoPostponing
    let e1 ← instantiateMVars e1
    let e2 ← instantiateMVars e2
    Meta.isDefEq e1 e2)
  IO.println ("DEFEQ " ++ toString r)

elab "#ORACLE_INFER" e:term : command => do
  let w ← liftTermElabM <| (do
    let e' ← elabTerm e none
    synthesizeSyntheticMVarsNoPostponing
    let e' ← instantiateMVars e'
    inferType e')
  IO.println ("INFER " ++ serExpr w)
"""


def run_oracle(defs: str, sources: list[str]) -> list[dict]:
    """Run `lean` on defs+cases; returns one parsed JSON dict per case, in
    order. Raises RuntimeError with lean's stderr on compile errors."""
    entries = [("WHNF", s, None) for s in sources]
    return run_oracle_mixed(defs, entries)


def run_oracle_mixed(defs: str, entries: list[tuple],
                     lean_cmd: list[str] | None = None,
                     cwd: str | None = None) -> list[tuple]:
    """entries: (kind, src_a, src_b_or_None) with kind in
    {"WHNF","DEFEQ","INFER"}. Returns [(kind, payload)] in order, where
    payload is a parsed expr dict for WHNF/INFER and a bool for DEFEQ.
    lean_cmd/cwd target a lake project's binary (e.g. ["lake","env","lean"]
    with cwd=<project> to run the oracle inside a Mathlib environment).
    `import ...` lines inside defs are hoisted to the file top."""
    imps = "".join(ln + "\n" for ln in defs.splitlines()
                   if ln.strip().startswith("import "))
    rest = "\n".join(ln for ln in defs.splitlines()
                     if not ln.strip().startswith("import "))
    body = ORACLE_TEMPLATE.format(defs=rest, imports=imps)
    for kind, a, b in entries:
        if kind == "WHNF":
            body += f"\n#ORACLE {a}"
        elif kind == "DEFEQ":
            body += f"\n#ORACLE_DEFEQ {a} =?= {b}"
        elif kind == "INFER":
            body += f"\n#ORACLE_INFER {a}"
        else:
            raise ValueError(kind)
    path = Path("/tmp/vm_oracle_batch.lean")
    path.write_text(body)
    r = subprocess.run(list(lean_cmd or [str(LEAN)]) + [str(path)],
                       capture_output=True, text=True,
                       timeout=600, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"lean failed:\n{r.stderr}")
    results = []
    for line in r.stdout.splitlines():
        if line.startswith("ORACLE "):
            results.append(("WHNF", json.loads(line[len("ORACLE "):])))
        elif line.startswith("DEFEQ "):
            results.append(("DEFEQ", line[len("DEFEQ "):].strip() == "true"))
        elif line.startswith("INFER "):
            results.append(("INFER", json.loads(line[len("INFER "):])))
    if len(results) != len(entries):
        raise RuntimeError(
            f"expected {len(entries)} results, got {len(results)}; "
            f"stdout:\n{r.stdout}")
    return results


def run_check_oracle(defs: str, cases: list[tuple[str, str]]) -> list[bool]:
    """M4.2 accept/reject oracle: one `lean` invocation per (type_src,
    val_src) case. `example : T := v` elaborates v against expected type T
    (elaborator infer + kernel defeq — exactly the check slice), so exit 0
    iff the real kernel accepts the declaration."""
    results = []
    for t_src, v_src in cases:
        path = Path("/tmp/vm_check_case.lean")
        path.write_text(defs + f"\nexample : {t_src} := {v_src}\n")
        r = subprocess.run([str(LEAN), str(path)], capture_output=True,
                           text=True, timeout=600)
        results.append(r.returncode == 0)
    return results


def json_to_expr(d: dict):
    k = d["k"]
    if k == 1:
        return BVar(d["i"])
    if k == 2:
        return FVar(d["n"])
    if k == 3:
        return MVar(d["n"])          # mvar in oracle output = elaboration bug
    if k == 4:
        return Sort(_jlevel(d["l"]))
    if k == 5:
        return Const(d["n"], tuple(_jlevel(l) for l in d["u"]))
    if k == 6:
        return App(json_to_expr(d["f"]), json_to_expr(d["a"]))
    if k == 7:
        return Lam("", d.get("bi", 0), json_to_expr(d["t"]), json_to_expr(d["b"]))
    if k == 8:
        return Pi("", d.get("bi", 0), json_to_expr(d["t"]), json_to_expr(d["b"]))
    if k == 9:
        return Let("", json_to_expr(d["t"]), json_to_expr(d["v"]),
                   json_to_expr(d["b"]))
    if k == 10:
        if "nat" in d:
            return LitNat(d["nat"])
        return LitStr(d["str"])
    if k == 11:
        return MData(json_to_expr(d["c"]))
    if k == 12:
        return Proj(d["s"], d["i"], json_to_expr(d["c"]))
    raise ValueError(d)


def _jlevel(d: dict):
    k = d["k"]
    if k == 1:
        return LZero()
    if k == 2:
        return LSucc(_jlevel(d["a"]))
    if k == 3:
        return LMax(_jlevel(d["a"]), _jlevel(d["b"]))
    if k == 4:
        return LIMax(_jlevel(d["a"]), _jlevel(d["b"]))
    if k == 5:
        return LParam(d["n"])
    if k == 6:
        return LMVar(d["n"])
    raise ValueError(d)


# ---------------------------------------------------------------------------
# VM_SPEC 12.5(A): #LEVEL pure level-algebra oracle.
#
# Second, ADDITIVE template (ORACLE_TEMPLATE above is untouched). Uses only the
# public Lean.Level predicate API; it deliberately never compares serialized
# `Level.normalize` structures across implementations, because 4.33.1's
# Lean-side normalize orders max args differently from the C++ kernel's
# `is_norm_lt` (VM_SPEC 12.2 D5). The oracle emits per case one line
#   LEVEL <id> <json>
# where json = {"a": <unary>, "b": <unary>, "isEquiv": bool, "geqAB": bool,
# "geqBA": bool, "occursAB": bool, "occursBA": bool} and <unary> =
# {"explicit": bool, "offset": nat, "neverZero": bool, "alwaysZero": bool,
#  "ser": <level>, "norm": <level>, "levelOffset": <level>} with <level> the
# same JSON shape the WHNF oracle uses (k=1..6). Serializations are only ever
# compared against other values from THIS oracle (self-coherence); a later
# package does the VM-side comparison.
#
# Every case is a pair of levels `(a, b)`; unary cases pass the same level
# twice. A pair term is required because Lean's parser would read two adjacent
# `term` arguments as one application.
LEVEL_TEMPLATE = """\
import Lean
{imports}open Lean Elab Command Term Meta

{defs}

def serLvl : Level → String
  | .zero => "{{\\"k\\":1}}"
  | .succ l => "{{\\"k\\":2,\\"a\\":" ++ serLvl l ++ "}}"
  | .max a b => "{{\\"k\\":3,\\"a\\":" ++ serLvl a ++ ",\\"b\\":" ++ serLvl b ++ "}}"
  | .imax a b => "{{\\"k\\":4,\\"a\\":" ++ serLvl a ++ ",\\"b\\":" ++ serLvl b ++ "}}"
  | .param n => "{{\\"k\\":5,\\"n\\":\\"" ++ n.toString ++ "\\"}}"
  | .mvar n => "{{\\"k\\":6,\\"n\\":\\"" ++ n.name.toString ++ "\\"}}"

def unaryJson (l : Level) : String :=
  "{{\\"explicit\\":" ++ toString l.isExplicit
  ++ ",\\"offset\\":" ++ toString l.getOffset
  ++ ",\\"neverZero\\":" ++ toString l.isNeverZero
  ++ ",\\"alwaysZero\\":" ++ toString l.isAlwaysZero
  ++ ",\\"ser\\":" ++ serLvl l
  ++ ",\\"norm\\":" ++ serLvl l.normalize
  ++ ",\\"levelOffset\\":" ++ serLvl l.getLevelOffset ++ "}}"

def evalLvl (e : Expr) : TermElabM Level :=
  unsafe Meta.evalExpr Level (Lean.mkConst ``Level) e

elab "#LEVEL" id:ident "(" a:term "," b:term ")" : command => do
  let (la, lb) ← liftTermElabM <| do
    let ea ← elabTerm a (some (Lean.mkConst ``Level))
    let eb ← elabTerm b (some (Lean.mkConst ``Level))
    let ea ← instantiateMVars ea
    let eb ← instantiateMVars eb
    let la ← evalLvl ea
    let lb ← evalLvl eb
    pure (la, lb)
  let j := "{{\\"a\\":" ++ unaryJson la ++ ",\\"b\\":" ++ unaryJson lb
    ++ ",\\"isEquiv\\":" ++ toString (Level.isEquiv la lb)
    ++ ",\\"geqAB\\":" ++ toString (Level.geq la lb)
    ++ ",\\"geqBA\\":" ++ toString (Level.geq lb la)
    ++ ",\\"occursAB\\":" ++ toString (Level.occurs la lb)
    ++ ",\\"occursBA\\":" ++ toString (Level.occurs lb la) ++ "}}"
  IO.println ("LEVEL " ++ id.getId.toString ++ " " ++ j)
"""


# ---------------------------------------------------------------------------
# VM_SPEC 12.5(B): #KDECL raw-kernel-declaration oracle.
#
# Second ADDITIVE template. Cases are raw `Declaration` terms built with
# mkOracleAxiom / mkOracleDefn / mkSort / Lean.mkConst / Level constructors;
# they are evaluated with Meta.evalExpr and handed to the real C++ kernel via
# `Lean.Kernel.Environment.addDecl` (4.33.1 verified). One line per case:
#   KDECL <id> OK|<exception-class>
# where the class is the `Lean.Kernel.Exception` constructor name.
KDECL_TEMPLATE = """\
import Lean
{imports}open Lean Elab Command Term Meta

{defs}

def classOf : Kernel.Exception → String
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
  | .other _ => "other"
  | .deterministicTimeout => "deterministicTimeout"
  | .excessiveMemory => "excessiveMemory"
  | .deepRecursion => "deepRecursion"
  | .interrupted => "interrupted"

def mkOracleAxiom (name : Name) (lps : List Name) (ty : Expr) : Declaration :=
  .axiomDecl {{ name := name, levelParams := lps, type := ty, isUnsafe := false }}

def mkOracleDefn (name : Name) (lps : List Name) (ty val : Expr) : Declaration :=
  .defnDecl {{ name := name, levelParams := lps, type := ty, value := val,
              hints := .regular 0, safety := .safe, all := [name] }}

def evalDecl (e : Expr) : TermElabM Declaration :=
  unsafe Meta.evalExpr Declaration (Lean.mkConst ``Declaration) e

elab "#KDECL" id:ident d:term : command => do
  let decl ← liftTermElabM <| do
    let e ← elabTerm d (some (Lean.mkConst ``Declaration))
    let e ← instantiateMVars e
    evalDecl e
  let cls := match Kernel.Environment.addDecl (← getEnv).toKernelEnv (← getOptions) decl with
    | .ok _ => "OK"
    | .error e => classOf e
  IO.println ("KDECL " ++ id.getId.toString ++ " " ++ cls)
"""


# ---------------------------------------------------------------------------
# VM_SPEC 12.5(D): #KCHECK raw-kernel declaration-check oracle.
#
# Third ADDITIVE template. It exercises the RAW kernel `type_checker` (via the
# `Lean.Kernel.check` / `Lean.Kernel.isDefEq` externs in Lean/Environment.lean,
# which call `type_checker(...).check` / `.is_def_eq`), NOT the Meta layer the
# `#ORACLE*` commands use. Each case is `(type_src, val_src)`:
#
#   1. elaborate both terms, synthesize/instantiate mvars (input is an
#      elaborated, mvar-free declaration pair);
#   2. reject mvar/fvar terms up front (Kernel.Exception declHasMVars /
#      declHasFVars, mirroring environment.cpp check_no_metavar_no_fvar);
#   3. `Kernel.check` the declared type and require its inferred type is a
#      `Sort` (environment.cpp check_constant_val ensure_sort -> typeExpected);
#   4. `Kernel.check` the value to infer its type;
#   5. raw `Kernel.isDefEq` between inferred value type and declared type;
#      false -> declTypeMismatch (environment.cpp add_definition).
#
# One line per case:
#   KCHECK <id> OK|<exception-class>
# where the class is the `Lean.Kernel.Exception` constructor name (same
# vocabulary as #KDECL via classOf).
KCHECK_TEMPLATE = """\
import Lean
{imports}open Lean Elab Command Term Meta

{defs}

def classOf : Kernel.Exception → String
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
  | .other _ => "other"
  | .deterministicTimeout => "deterministicTimeout"
  | .excessiveMemory => "excessiveMemory"
  | .deepRecursion => "deepRecursion"
  | .interrupted => "interrupted"

elab "#KCHECK" id:ident "(" t:term "," v:term ")" : command => do
  let (tyE, valE) ← liftTermElabM <| do
    let te ← elabTerm t none
    let ve ← elabTerm v none
    synthesizeSyntheticMVarsNoPostponing
    let te ← instantiateMVars te
    let ve ← instantiateMVars ve
    pure (te, ve)
  let env ← getEnv
  let lctx : LocalContext := {{}}
  let verdict ←
    if tyE.hasMVar || valE.hasMVar then pure "declHasMVars"
    else if tyE.hasFVar || valE.hasFVar then pure "declHasFVars"
    else
      match Kernel.check env lctx tyE with
      | .error ex => pure (classOf ex)
      | .ok tySort =>
        match tySort with
        | .sort _ =>
          match Kernel.check env lctx valE with
          | .error ex => pure (classOf ex)
          | .ok valTy =>
            match Kernel.isDefEq env lctx valTy tyE with
            | .error ex => pure (classOf ex)
            | .ok true => pure "OK"
            | .ok false => pure "declTypeMismatch"
        | _ => pure "typeExpected"
  IO.println ("KCHECK " ++ id.getId.toString ++ " " ++ verdict)
"""


def _hoist_imports(defs: str) -> tuple[str, str]:
    """Split leading-of-line `import ...` lines out of defs (as
    run_oracle_mixed does) so the template's own `import Lean` stays first."""
    imps = "".join(ln + "\n" for ln in defs.splitlines()
                   if ln.strip().startswith("import "))
    rest = "\n".join(ln for ln in defs.splitlines()
                     if not ln.strip().startswith("import "))
    return imps, rest


def run_level_oracle(defs: str, cases: list[tuple[str, str, str]],
                     lean_cmd: list[str] | None = None,
                     cwd: str | None = None) -> list[dict]:
    """VM_SPEC 12.5(A). `cases` is [(id, a_src, b_src)] where a_src/b_src are
    Lean terms of type `Level` (unary cases repeat the level). Generates one
    `#LEVEL id (a, b)` per case, runs `lean`, and returns the parsed JSON
    payloads in case order. Raises RuntimeError with lean's stderr on compile
    failure, and if the result count/id order does not match."""
    imps, rest = _hoist_imports(defs)
    body = LEVEL_TEMPLATE.format(defs=rest, imports=imps)
    for cid, a, b in cases:
        body += f"\n#LEVEL {cid} ({a}, {b})"
    path = Path("/tmp/vm_level_oracle.lean")
    path.write_text(body)
    r = subprocess.run(list(lean_cmd or [str(LEAN)]) + [str(path)],
                       capture_output=True, text=True,
                       timeout=600, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"lean failed:\n{r.stderr}")
    results, ids = [], []
    for line in r.stdout.splitlines():
        if line.startswith("LEVEL "):
            _, cid, payload = line.split(" ", 2)
            ids.append(cid)
            results.append(json.loads(payload))
    if ids != [c[0] for c in cases]:
        raise RuntimeError(
            f"LEVEL oracle id mismatch: got {ids}, expected "
            f"{[c[0] for c in cases]}; stdout:\n{r.stdout}")
    return results


def run_kdecl_oracle(defs: str, cases: list[tuple[str, str]],
                     lean_cmd: list[str] | None = None,
                     cwd: str | None = None) -> list[str]:
    """VM_SPEC 12.5(B). `cases` is [(id, decl_src)] where decl_src is a Lean
    term of type `Declaration`. Generates one `#KDECL id (decl_src)` per case,
    runs `lean`, and returns the class strings ("OK" or a
    `Lean.Kernel.Exception` constructor name) in case order. Raises
    RuntimeError with lean's stderr on compile failure, and if the result
    count/id order does not match."""
    imps, rest = _hoist_imports(defs)
    body = KDECL_TEMPLATE.format(defs=rest, imports=imps)
    for cid, src in cases:
        body += f"\n#KDECL {cid} ({src})"
    path = Path("/tmp/vm_kdecl_oracle.lean")
    path.write_text(body)
    r = subprocess.run(list(lean_cmd or [str(LEAN)]) + [str(path)],
                       capture_output=True, text=True,
                       timeout=600, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"lean failed:\n{r.stderr}")
    results, ids = [], []
    for line in r.stdout.splitlines():
        if line.startswith("KDECL "):
            _, cid, cls = line.split(" ", 2)
            ids.append(cid)
            results.append(cls.strip())
    if ids != [c[0] for c in cases]:
        raise RuntimeError(
            f"KDECL oracle id mismatch: got {ids}, expected "
            f"{[c[0] for c in cases]}; stdout:\n{r.stdout}")
    return results


def run_kcheck_oracle(defs: str, cases: list[tuple[str, str, str]],
                      lean_cmd: list[str] | None = None,
                      cwd: str | None = None) -> list[str]:
    """VM_SPEC 12.5(D). `cases` is [(id, type_src, val_src)] where type_src /
    val_src are Lean terms of the declaration's type and value. Generates one
    `#KCHECK id (type_src, val_src)` per case, runs `lean`, and returns the
    verdict strings ("OK" or a `Lean.Kernel.Exception` constructor name) in
    case order. The verdict is produced by the raw kernel `type_checker`
    (`Kernel.check` / `Kernel.isDefEq`), not the Meta layer. Raises
    RuntimeError with lean's stderr on compile failure, and if the result
    count/id order does not match."""
    imps, rest = _hoist_imports(defs)
    body = KCHECK_TEMPLATE.format(defs=rest, imports=imps)
    for cid, t_src, v_src in cases:
        body += f"\n#KCHECK {cid} ({t_src}, {v_src})"
    path = Path("/tmp/vm_kcheck_oracle.lean")
    path.write_text(body)
    r = subprocess.run(list(lean_cmd or [str(LEAN)]) + [str(path)],
                       capture_output=True, text=True,
                       timeout=600, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"lean failed:\n{r.stderr}")
    results, ids = [], []
    for line in r.stdout.splitlines():
        if line.startswith("KCHECK "):
            _, cid, cls = line.split(" ", 2)
            ids.append(cid)
            results.append(cls.strip())
    if ids != [c[0] for c in cases]:
        raise RuntimeError(
            f"KCHECK oracle id mismatch: got {ids}, expected "
            f"{[c[0] for c in cases]}; stdout:\n{r.stdout}")
    return results
