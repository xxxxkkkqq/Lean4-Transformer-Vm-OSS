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
open Lean Elab Command Term Meta

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


def run_oracle_mixed(defs: str, entries: list[tuple]) -> list[tuple]:
    """entries: (kind, src_a, src_b_or_None) with kind in
    {"WHNF","DEFEQ","INFER"}. Returns [(kind, payload)] in order, where
    payload is a parsed expr dict for WHNF/INFER and a bool for DEFEQ."""
    body = ORACLE_TEMPLATE.format(defs=defs)
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
    r = subprocess.run([str(LEAN), str(path)], capture_output=True, text=True,
                       timeout=600)
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
        return Lam("", 0, json_to_expr(d["t"]), json_to_expr(d["b"]))
    if k == 8:
        return Pi("", 0, json_to_expr(d["t"]), json_to_expr(d["b"]))
    if k == 9:
        return Let("", 0, json_to_expr(d["t"]), json_to_expr(d["v"]),
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
