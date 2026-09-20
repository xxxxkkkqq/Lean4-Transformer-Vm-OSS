"""012 M-A — Mathlib proof-closure extractor + kernel round-trip metadata check.

Given real Mathlib theorem names, extract the constant dependency closure out
of the REAL lean binary (v4.33.1, via `lake env lean` in the mathlib project),
encode it into the repo's ENV token format (reusing reference/olean_export.py
without modification), and verify the dump's declaration metadata by a kernel
round trip:

  DUMPCONST JSON (dump_env) -> reconstruct Lean Declaration -> fresh empty
  kernel env -> Kernel.Environment.addDeclWithoutChecking (Lean/Environment.
  lean:307-308, extern lean_add_decl_without_checking) -> env.find? -> re-dump
  with the SAME serializers -> field-by-field compare against the original.

Compare scope (documented, not hidden):
  * `ind.isStruct` / `ind.nf` are skipped: they come from getStructureInfo?
    (elaborator structureExt env extension, Lean/Structure.lean:126), not from
    kernel ConstantInfo (docs/ENV_FORMAT.md §1.5 has no such fields); a pure
    kernel env cannot carry them.  All other fields must match exactly.
  * opaque constants are skipped entirely: the frozen DUMP_TEMPLATE
    (reference/olean_export.py:177-180) serializes `val` only for
    defnInfo/thmInfo, so an opaque's value is absent from the dump and
    reconstructing it would mean inventing data.  Skips are counted and
    reported; any RTMISSING line beyond the skipped opaques is a FAILURE.

This tool only GENERATES and STRUCTURALLY CHECKS.  It never evaluates the
closure through the graph/RefVM (M-A red line: large-env evaluation is
O(N^2*L)) and emits no verdict fields (accept/reject comes from the oracle in
M-C, never pre-seeded here).

Usage:
  python3 scripts/export_mathlib_closure.py --mathlib /home/xkq/mathlib_src \
      --theorem Nat.testBit_land --theorem Vector3.cons_fz \
      --theorem Quot.liftOn_mk --out-dir /home/xkq/logs/012I/closures

The lean channel is `lake env lean` with cwd=<mathlib project> (the project's
lean-toolchain pins v4.33.1; the bare `elan default` may have drifted).
Artifacts per theorem under <out-dir>/<safe name>/: dump.lean, dump.jsonl
(raw DUMPCONST lines, identical bytes to what dump_env parsed), rt.lean,
rt.jsonl (round-trip re-dump).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from expr.tokens import Encoder, decode_env_meta          # noqa: E402
from expr.model import Expr                               # noqa: E402
from reference.lean_ref import LEAN                       # noqa: E402
from reference.olean_export import (                      # noqa: E402
    dump_env, import_env_meta, _const_names,
)

# ── Lean round-trip program (generated verbatim into <out>/rt.lean) ──────────
# Serializers are a byte-for-byte copy of reference/olean_export.py's
# DUMP_TEMPLATE so the re-dump is comparable to the original dump.
RT_TEMPLATE = r'''import Lean
open Lean

/- 012 M-A metadata round trip: DUMPCONST JSON -> Declaration -> fresh empty
kernel env -> Kernel.Environment.addDeclWithoutChecking (Lean/Environment.lean:
307-308, extern lean_add_decl_without_checking) -> env.find? -> re-dump with
the SAME serializers as reference/olean_export.py DUMP_TEMPLATE.
Input via env vars RT_IN / RT_OUT. -/

-- ── serializers: verbatim copy of olean_export DUMP_TEMPLATE ────────────────
partial def serLevel : Level → String
  | .zero => "{\"k\":1}"
  | .succ l => "{\"k\":2,\"a\":" ++ serLevel l ++ "}"
  | .max a b => "{\"k\":3,\"a\":" ++ serLevel a ++ ",\"b\":" ++ serLevel b ++ "}"
  | .imax a b => "{\"k\":4,\"a\":" ++ serLevel a ++ ",\"b\":" ++ serLevel b ++ "}"
  | .param n => "{\"k\":5,\"n\":\"" ++ n.toString ++ "\"}"
  | .mvar n => "{\"k\":6,\"n\":\"" ++ n.name.toString ++ "\"}"

def biNat : BinderInfo → Nat
  | .default => 0 | .implicit => 1 | .strictImplicit => 2 | .instImplicit => 3

partial def serExpr : Expr → String
  | .bvar i => "{\"k\":1,\"i\":" ++ toString i ++ "}"
  | .fvar n => "{\"k\":2,\"n\":\"" ++ n.name.toString ++ "\"}"
  | .mvar n => "{\"k\":3,\"n\":\"" ++ n.name.toString ++ "\"}"
  | .sort l => "{\"k\":4,\"l\":" ++ serLevel l ++ "}"
  | .const n ls => "{\"k\":5,\"n\":\"" ++ n.toString ++ "\",\"u\":[" ++
      String.intercalate "," (ls.map serLevel) ++ "]}"
  | .app f a => "{\"k\":6,\"f\":" ++ serExpr f ++ ",\"a\":" ++ serExpr a ++ "}"
  | .lam _ t b bi => "{\"k\":7,\"bi\":" ++ toString (biNat bi) ++ ",\"t\":" ++ serExpr t ++ ",\"b\":" ++ serExpr b ++ "}"
  | .forallE _ t b bi => "{\"k\":8,\"bi\":" ++ toString (biNat bi) ++ ",\"t\":" ++ serExpr t ++ ",\"b\":" ++ serExpr b ++ "}"
  | .letE _ t v b _ => "{\"k\":9,\"t\":" ++ serExpr t ++ ",\"v\":" ++ serExpr v ++ ",\"b\":" ++ serExpr b ++ "}"
  | .lit l => match l with
      | .natVal v => "{\"k\":10,\"nat\":" ++ toString v ++ "}"
      | .strVal s => "{\"k\":10,\"str\":\"" ++ s ++ "\"}"
  | .mdata _ c => "{\"k\":11,\"c\":" ++ serExpr c ++ "}"
  | .proj s i c => "{\"k\":12,\"s\":\"" ++ s.toString ++ "\",\"i\":" ++
      toString i ++ ",\"c\":" ++ serExpr c ++ "}"

def jstr (s : String) : String :=
  "\"" ++ (s.foldl (fun acc c =>
    if c == '"' then acc ++ "\\\""
    else if c == '\\' then acc ++ "\\\\"
    else acc.push c) "") ++ "\""

def hintKind : ReducibilityHints → Nat
  | .opaque => 0 | .abbrev => 1 | .regular _ => 2
def hintHeight : ReducibilityHints → Nat
  | .regular h => h.toNat | _ => 0
def safetyNat : DefinitionSafety → Nat
  | .unsafe => 0 | .safe => 1 | .partial => 2
def quotKindNat : QuotKind → Nat
  | .type => 0 | .ctor => 1 | .lift => 2 | .ind => 3

def serNames (ns : List Name) : String :=
  "[" ++ String.intercalate "," (ns.map (fun n => jstr n.toString)) ++ "]"

def serRules (rs : List RecursorRule) : String :=
  "[" ++ String.intercalate "," (rs.map (fun r =>
    "{\"ctor\":" ++ jstr r.ctor.toString ++ ",\"nfields\":" ++ toString r.nfields ++
    ",\"rhs\":" ++ serExpr r.rhs ++ "}")) ++ "]"

def metaJson (ci : ConstantInfo) : String :=
  match ci with
  | .axiomInfo a => "{\"kind\":0,\"isUnsafe\":" ++ toString a.isUnsafe ++ "}"
  | .defnInfo d => "{\"kind\":1,\"hints\":" ++ toString (hintKind d.hints) ++
      ",\"height\":" ++ toString (hintHeight d.hints) ++
      ",\"safety\":" ++ toString (safetyNat d.safety) ++
      ",\"isUnsafe\":" ++ toString (safetyNat d.safety == 0) ++
      ",\"all\":" ++ serNames d.all ++ "}"
  | .thmInfo t => "{\"kind\":2,\"all\":" ++ serNames t.all ++ "}"
  | .opaqueInfo o => "{\"kind\":3,\"isUnsafe\":" ++ toString o.isUnsafe ++
      ",\"all\":" ++ serNames o.all ++ "}"
  | .quotInfo q => "{\"kind\":4,\"quotKind\":" ++ toString (quotKindNat q.kind) ++ "}"
  | .inductInfo i => "{\"kind\":5,\"np\":" ++ toString i.numParams ++
      ",\"ni\":" ++ toString i.numIndices ++ ",\"nn\":" ++ toString i.numNested ++
      ",\"isRec\":" ++ toString i.isRec ++ ",\"isUnsafe\":" ++ toString i.isUnsafe ++
      ",\"isRefl\":" ++ toString i.isReflexive ++
      ",\"all\":" ++ serNames i.all ++ ",\"ctors\":" ++ serNames i.ctors ++ "}"
  | .ctorInfo c => "{\"kind\":6,\"induct\":" ++ jstr c.induct.toString ++
      ",\"cidx\":" ++ toString c.cidx ++ ",\"np\":" ++ toString c.numParams ++
      ",\"nfields\":" ++ toString c.numFields ++
      ",\"isUnsafe\":" ++ toString c.isUnsafe ++ "}"
  | .recInfo r => "{\"kind\":7,\"np\":" ++ toString r.numParams ++
      ",\"ni\":" ++ toString r.numIndices ++ ",\"nm\":" ++ toString r.numMotives ++
      ",\"nmin\":" ++ toString r.numMinors ++ ",\"isK\":" ++ toString r.k ++
      ",\"isUnsafe\":" ++ toString r.isUnsafe ++
      ",\"all\":" ++ serNames r.all ++ ",\"rules\":" ++ serRules r.rules ++ "}"

-- ── exact inverse of Name.toString for env-constant names ───────────────────
-- String.toName is NOT exact: hygienic names (<name>._@.(<imported>.<ctx>)*.
-- _hyg.<scopes>, MacroScopesView in Init/Prelude.lean:5659-5700) collapse to
-- [anonymous].  parseLeanName rebuilds the Name per the MacroScopesView
-- grammar: parts between "_@" and "_hyg" are appended in order, trailing
-- numeric components become .num scopes (MacroScopesView.review).

def mkParts : List String → Name → Name
  | [], acc => acc
  | p :: rest, acc =>
    match p.toNat? with
    | some n => mkParts rest (Name.mkNum acc n)
    | none => mkParts rest (Name.mkStr acc p)

def stripGuillemets (p : String) : String :=
  if p.length >= 2 && p.front == '«' && (p.drop (p.length - 1) |>.front) == '»' then
    (p.drop 1 |>.dropEnd 1).toString
  else p

def parseLeanName (s : String) : Name :=
  let comps := s.splitOn "."
  match comps.idxOf? "_@" with
  | none =>
    mkParts (comps.map stripGuillemets) .anonymous
  | some i =>
    match (comps.drop (i+1)).idxOf? "_hyg" with
    | none => mkParts (comps.map stripGuillemets) .anonymous
    | some j =>
      let namePart := (comps.take i).map stripGuillemets
      let mid := ((comps.drop (i+1)).take j).map stripGuillemets
      let scopes := (comps.drop (i+1)).drop (j+1)
      let base := mkParts (namePart ++ ["_@"] ++ mid) .anonymous
      let base := Name.mkStr base "_hyg"
      scopes.foldl (fun acc c =>
        match c.toNat? with
        | some n => Name.mkNum acc n
        | none => Name.mkStr acc c) base

-- ── deserializers (inverse of serLevel/serExpr) ─────────────────────────────
def liftE {α} (e : Except String α) : IO α :=
  match e with
  | .ok a => pure a
  | .error s => throw (IO.userError s)

def jobj (j : Json) (k : String) : Except String Json := j.getObjVal? k
def jnatF (j : Json) (k : String) : Except String Nat := do (← jobj j k).getNat?
def jstrF (j : Json) (k : String) : Except String String := do (← jobj j k).getStr?
def jboolF (j : Json) (k : String) : Except String Bool := do (← jobj j k).getBool?

def jnameArr (j : Json) (k : String) : Except String (List Name) := do
  match ← jobj j k with
  | .arr a => a.toList.mapM (fun x => return parseLeanName (← x.getStr?))
  | _ => throw s!"{k}: expected array"

def jbi (n : Nat) : Except String BinderInfo :=
  match n with
  | 0 => pure .default | 1 => pure .implicit
  | 2 => pure .strictImplicit | 3 => pure .instImplicit
  | k => throw s!"bad binderInfo {k}"

partial def jLevel (j : Json) : Except String Level := do
  match ← jnatF j "k" with
  | 1 => pure .zero
  | 2 => pure (.succ (← jLevel (← jobj j "a")))
  | 3 => pure (.max (← jLevel (← jobj j "a")) (← jLevel (← jobj j "b")))
  | 4 => pure (.imax (← jLevel (← jobj j "a")) (← jLevel (← jobj j "b")))
  | 5 => pure (.param (parseLeanName (← jstrF j "n")))
  | 6 => throw "level mvar in dump (kernel declarations carry no level mvars)"
  | k => throw s!"bad level kind {k}"

def jLevels (j : Json) (k : String) : Except String (List Level) := do
  match ← jobj j k with
  | .arr a => a.toList.mapM jLevel
  | _ => throw s!"{k}: expected array"

partial def jExpr (j : Json) : Except String Expr := do
  match ← jnatF j "k" with
  | 1 => pure (.bvar (← jnatF j "i"))
  | 2 => throw "fvar in dump (kernel constants are closed -- finding)"
  | 3 => throw "mvar in dump (kernel constants are closed -- finding)"
  | 4 => pure (.sort (← jLevel (← jobj j "l")))
  | 5 => pure (.const (parseLeanName (← jstrF j "n")) (← jLevels j "u"))
  | 6 => pure (.app (← jExpr (← jobj j "f")) (← jExpr (← jobj j "a")))
  -- 4.33.1: lam/forallE (binderName) (binderType) (body) (binderInfo)
  | 7 => pure (.lam `_ (← jExpr (← jobj j "t")) (← jExpr (← jobj j "b"))
                 (← jbi (← jnatF j "bi")))
  | 8 => pure (.forallE `_ (← jExpr (← jobj j "t")) (← jExpr (← jobj j "b"))
                 (← jbi (← jnatF j "bi")))
  | 9 => pure (.letE `_ (← jExpr (← jobj j "t")) (← jExpr (← jobj j "v"))
                 (← jExpr (← jobj j "b")) false)
  | 10 => match (jobj j "nat").toOption with
      | some _ => pure (.lit (.natVal (← jnatF j "nat")))
      | none => pure (.lit (.strVal (← jstrF j "str")))
  | 11 => pure (.mdata MData.empty (← jExpr (← jobj j "c")))
  | 12 => pure (.proj (parseLeanName (← jstrF j "s")) (← jnatF j "i")
                 (← jExpr (← jobj j "c")))
  | k => throw s!"bad expr kind {k}"

-- ── declaration reconstruction (4.33.1 Declaration API) ─────────────────────
def mkHints (m : Json) : Except String ReducibilityHints := do
  match ← jnatF m "hints" with
  | 0 => pure .opaque
  | 1 => pure .abbrev
  | 2 => pure (.regular (← jnatF m "height").toUInt32)
  | k => throw s!"bad hints kind {k}"

def mkSafety (m : Json) : Except String DefinitionSafety := do
  match ← jnatF m "safety" with
  | 0 => pure .unsafe
  | 1 => pure .safe
  | 2 => pure .partial
  | k => throw s!"bad safety {k}"

def mkDecl (j : Json) : Except String Declaration := do
  let name := parseLeanName (← jstrF j "n")
  let lps ← jnameArr j "up"
  let ty ← jExpr (← jobj j "ty")
  let mt ← jobj j "meta"
  let kind ← jstrF j "kind"
  match kind with
  | "axiom" =>
    let isU ← jboolF mt "isUnsafe"
    pure (.axiomDecl { name, levelParams := lps, type := ty, isUnsafe := isU })
  | "def" =>
    let v ← jExpr (← jobj j "val")
    let hints ← mkHints mt
    let safety ← mkSafety mt
    let all ← jnameArr mt "all"
    pure (.defnDecl { name, levelParams := lps, type := ty, value := v,
                      hints := hints, safety := safety, all := all })
  | "thm" =>
    let v ← jExpr (← jobj j "val")
    let all ← jnameArr mt "all"
    pure (.thmDecl { name, levelParams := lps, type := ty, value := v, all := all })
  | "opaque" =>
    let v ← jExpr (← jobj j "val")
    let isU ← jboolF mt "isUnsafe"
    let all ← jnameArr mt "all"
    pure (.opaqueDecl { name, levelParams := lps, type := ty, value := v,
                        isUnsafe := isU, all := all })
  | "quot" => pure .quotDecl
  | k => throw s!"mkDecl: unexpected kind {k} (ind handled separately)"

/-- One inductDecl per mutual group; types in `all` order, each with its
ctors (from that inductive's meta.ctors, declaration order). -/
def mkIndDecl (m : NameMap Json) (j : Json) (seen : NameSet)
    : Except String (Declaration × NameSet) := do
  let mt ← jobj j "meta"
  let all ← jnameArr mt "all"
  let mut types : List InductiveType := []
  let mut seen := seen
  for a in all do
    if seen.contains a then continue
    let some aj := m.find? a | throw s!"ind member {a} missing from dump"
    let amt ← jobj aj "meta"
    let aty ← jExpr (← jobj aj "ty")
    let cnames ← jnameArr amt "ctors"
    let mut cs : List Constructor := []
    for cn in cnames do
      let some cj := m.find? cn | throw s!"ctor {cn} missing from dump"
      let cty ← jExpr (← jobj cj "ty")
      cs := { name := cn, type := cty } :: cs
    types := { name := a, type := aty, ctors := cs.reverse } :: types
    seen := seen.insert a
  let lps ← jnameArr j "up"
  let np ← jnatF mt "np"
  let isU ← jboolF mt "isUnsafe"
  pure (Declaration.inductDecl lps np types.reverse isU, seen)

def addD (kenv : Kernel.Environment) (decl : Declaration) (label : String)
    : IO Kernel.Environment := do
  -- pure kernel path: Kernel.Environment.addDeclWithoutChecking
  -- (Lean/Environment.lean:307-308, extern lean_add_decl_without_checking)
  match kenv.addDeclWithoutChecking decl with
  | .ok e => return e
  | .error ex =>
    let msg := match ex with
      | .other m => m
      | .unknownConstant _ n => s!"unknownConstant {n}"
      | .alreadyDeclared _ n => s!"alreadyDeclared {n}"
      | .declHasMVars _ n _ => s!"declHasMVars {n}"
      | .declHasFVars _ n _ => s!"declHasFVars {n}"
      | .declTypeMismatch _ _ _ => "declTypeMismatch"
      | .funExpected .. => "funExpected"
      | .typeExpected .. => "typeExpected"
      | .letTypeMismatch .. => "letTypeMismatch"
      | .exprTypeMismatch .. => "exprTypeMismatch"
      | .appTypeMismatch .. => "appTypeMismatch"
      | .invalidProj .. => "invalidProj"
      | .thmTypeIsNotProp .. => "thmTypeIsNotProp"
      | .deterministicTimeout => "deterministicTimeout"
      | .excessiveMemory => "excessiveMemory"
      | .deepRecursion => "deepRecursion"
      | .interrupted => "interrupted"
    throw (IO.userError s!"RTADDFAIL {label}: {msg}")

/- Generic const-ref walk over the serialized JSON: any {"k":5,"n":...}
object contributes its name; objects/arrays recurse. -/
partial def jsonRefs (j : Json) (acc : NameSet) : NameSet :=
  match j with
  | .obj kv =>
    let acc := match j.getObjVal? "k", j.getObjVal? "n" with
      | Except.ok (.num _), Except.ok (.str n) => acc.insert (parseLeanName n)
      | _, _ => acc
    kv.toList.foldl (fun a p => jsonRefs p.2 a) acc
  | .arr a => a.foldl (fun a x => jsonRefs x a) acc
  | _ => acc

/-- One declaration unit: a mutual inductive group, the quot block, or a
single axiom/def/thm/opaque. -/
inductive RTUnit where
  | ind  (first : String) (members : List String) (decl : Declaration)
  | quot
  | simple (name : String) (decl : Declaration)

def unitNames : RTUnit → List String
  | .ind _ ms _ => ms
  | .quot => [`Quot, `Quot.mk, `Quot.lift, `Quot.ind].map toString
  | .simple n _ => [n]

/-- Refs of a unit = union of member types + member ctor types, minus the
unit's own names (self/mutual-internal references). -/
partial def unitRefs (m : NameMap Json) (u : RTUnit) : Except String NameSet := do
  let mut own : NameSet := {}
  for n in unitNames u do
    own := own.insert (parseLeanName n)
  let mut refs : NameSet := {}
  match u with
  | .ind _ ms _ =>
    for a in ms do
      let some aj := m.find? (parseLeanName a)
        | throw s!"unitRefs: {a} missing from dump"
      let amt ← jobj aj "meta"
      let cnames ← jnameArr amt "ctors"
      refs := jsonRefs (← jobj aj "ty") refs
      for cn in cnames do
        let some cj := m.find? cn
          | throw s!"unitRefs: {cn} missing from dump"
        refs := jsonRefs (← jobj cj "ty") refs
  | .quot => pure ()
  | .simple n _ =>
    let some j := m.find? (parseLeanName n)
      | throw s!"unitRefs: {n} missing from dump"
    refs := jsonRefs (← jobj j "ty") refs
  return refs.filter (fun n => !own.contains n)

/-- DFS topological order over units; a gray hit across units would be a
kernel-level cycle (impossible for real env constants) -> error. -/
partial def topoVisit (m : NameMap Json) (byAny : NameMap RTUnit) (u : RTUnit)
    (st : NameSet × NameSet × List RTUnit)
    : Except String (NameSet × NameSet × List RTUnit) := do
  let some f := (unitNames u).head? | return st
  let (doneU, inProg, out) := st
  if doneU.contains (parseLeanName f) then return st
  if inProg.contains (parseLeanName f) then
    throw s!"cycle across declaration units at {f}"
  let st : NameSet × NameSet × List RTUnit :=
    (doneU, inProg.insert (parseLeanName f), out)
  let refs ← unitRefs m u
  let st ← refs.toList.foldlM (fun st r => do
    let some ru := byAny.find? r | return st
    topoVisit m byAny ru st) st
  let (doneU, inProg, out) := st
  return (doneU.insert (parseLeanName f), inProg.erase (parseLeanName f), u :: out)

def topoOrder (m : NameMap Json) (units : List RTUnit)
    (order : List String) : Except String (List RTUnit) := do
  let mut byAny : NameMap RTUnit := {}
  for u in units do
    for n in unitNames u do
      byAny := byAny.insert (parseLeanName n) u
  let st ← order.foldlM (fun st s => do
    let some u := byAny.find? (parseLeanName s) | return st
    topoVisit m byAny u st) ({}, {}, [])
  return st.2.2.reverse

-- ── re-dump with the identical serializer ───────────────────────────────────
def dumpConst (kenv : Kernel.Environment) (s : String) : IO String := do
  let n := parseLeanName s
  match kenv.find? n with
  | none => return s!"RTMISSING {s}"
  | some ci =>
    let kind := match ci with
      | .axiomInfo _ => "axiom" | .defnInfo _ => "def" | .thmInfo _ => "thm"
      | .opaqueInfo _ => "opaque" | .quotInfo _ => "quot"
      | .inductInfo _ => "ind" | .ctorInfo _ => "ctor" | .recInfo _ => "rec"
    let up := String.intercalate "," (ci.levelParams.map (fun x => jstr x.toString))
    let ty := serExpr ci.type
    let val := match ci with
      | .defnInfo d => serExpr d.value
      | .thmInfo t => serExpr t.value
      | _ => "null"
    -- isStruct/nf come from getStructureInfo? (elaborator structureExt,
    -- Lean/Structure.lean:126) which lives in the Lean.Environment ext
    -- state; a pure kernel env carries no such data -> false/0.  The Python
    -- compare skips these two keys (out of kernel ConstantInfo scope).
    let ind := match ci with
      | .inductInfo i => "{\"ctors\":[" ++ String.intercalate ","
          (i.ctors.map (fun c => jstr c.toString)) ++ "],\"np\":" ++ toString i.numParams ++
          ",\"isStruct\":false,\"nf\":0}"
      | _ => "null"
    return ("DUMPCONST " ++ "{\"n\":" ++ jstr s ++ ",\"kind\":\"" ++ kind ++
      "\",\"up\":[" ++ up ++ "],\"ty\":" ++ ty ++ ",\"val\":" ++ val ++
      ",\"ind\":" ++ ind ++ ",\"meta\":" ++ metaJson ci ++ "}")

def main : IO Unit := do
  let some inPath ← IO.getEnv "RT_IN"
    | throw (IO.userError "RT_IN not set")
  let some outPath ← IO.getEnv "RT_OUT"
    | throw (IO.userError "RT_OUT not set")
  let txt ← IO.FS.readFile inPath
  let mut ents : List (String × Json) := []
  for line in txt.splitOn "\n" do
    if "DUMPCONST ".isPrefixOf line then
      let s := (line.drop 10).toString
      match Json.parse s with
      | .ok j =>
        let nm ← liftE (jstrF j "n")
        ents := (nm, j) :: ents
      | .error e => throw (IO.userError s!"bad json line: {e}")
  -- file order: DUMP_TEMPLATE qsorts names before dumping, so already sorted
  let names := (ents.map (·.1)).reverse
  let mut m : NameMap Json := {}
  for (nm, j) in ents do
    m := m.insert (parseLeanName nm) j
  let mut hasQuot := false
  for (_, j) in ents do
    if (← liftE (jstrF j "kind")) == "quot" then hasQuot := true
  IO.println s!"parsed {ents.length} entries"
  -- fresh kernel env: no oleans, nothing pre-declared
  let env0 ← mkEmptyEnvironment 0
  let mut kenv := env0.toKernelEnv
  -- build declaration units: mutual ind groups / quot block / simple consts
  let mut units : List RTUnit := []
  let mut seen : NameSet := {}
  let mut madeQuot := false
  let mut skippedOpaque := 0
  for s in names do
    let some j := m.find? (parseLeanName s) | throw (IO.userError s!"internal: {s} missing")
    let k ← liftE (jstrF j "kind")
    if k == "ind" then
      if seen.contains (parseLeanName s) then continue
      let (decl, seen') ← liftE (mkIndDecl m j seen)
      seen := seen'
      let mt ← liftE (jobj j "meta")
      let members ← liftE (jnameArr mt "all")
      units := .ind s (members.map toString) decl :: units
    else if k == "quot" then
      if madeQuot then continue
      madeQuot := true
      units := .quot :: units
    else if k == "ctor" || k == "rec" then
      continue  -- derived by the kernel from the inductDecl
    else if k == "opaque"
         && (jobj j "val").toOption == some Json.null then
      -- DUMP_TEMPLATE (reference/olean_export.py:177-180) serializes `val`
      -- only for defnInfo/thmInfo: an opaque's value is not in the dump and
      -- cannot be reconstructed without inventing data.  Counted, excluded
      -- from the kernel reconstruction and from the compare.
      skippedOpaque := skippedOpaque + 1
      continue
    else
      let decl ← liftE (mkDecl j)
      units := .simple s decl :: units
  -- topological order: kernel addInductive derives ctors/recursors from ctor
  -- types, so referenced constants must already be present even "without
  -- checking" (empirical: MPair before Nat failed)
  let ordered ← liftE (topoOrder m units.reverse names)
  for u in ordered do
    match u with
    | .ind f _ decl => kenv ← addD kenv decl f
    | .quot => kenv ← addD kenv .quotDecl "Quot"
    | .simple n decl => kenv ← addD kenv decl n
  -- re-dump every original name
  let mut lines : List String := []
  for s in names do
    lines := (← dumpConst kenv s) :: lines
  IO.FS.writeFile outPath (String.intercalate "\n" lines.reverse ++ "\n")
  IO.println s!"RT-OK names={names.length} skipped_opaques={skippedOpaque}"
'''

TOKEN_BYTES = 10  # K:8 bits + 6 fields x 12 bits = 80 bits (VM_SPEC §2 field ranges)


def lean_env() -> dict:
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = "2"
    env["LEAN_NUM_THREADS"] = "2"
    return env


def _decl_module_check(mathlib: Path, module: str, theorem: str,
                       work: Path, tag: str) -> bool:
    """`import <module>` then read `env.getModuleIdxFor?` for the fully
    qualified name (Lean/Environment.lean:1195 -> const2ModIdx): imports are
    TRANSITIVE, so name resolution cannot identify the declarer; the module
    index can."""
    f = work / f"check_{tag}.lean"
    f.write_text(
        "import Lean\n"
        f"import {module}\n"
        "open Lean Elab Command\n"
        "#eval show CommandElabM Unit from do\n"
        "  let env <- liftCoreM getEnv\n"
        f"  let n := `{theorem}\n"
        "  match env.getModuleIdxFor? n with\n"
        "  | some idx =>\n"
        "      let mod := env.header.moduleNames[idx]!\n"
        f"      if mod == `{module} then pure () else throwError \"declared in {{mod}}\"\n"
        "  | none => throwError \"no module idx\"\n")
    r = subprocess.run(["lake", "env", "lean", str(f)], cwd=str(mathlib),
                       capture_output=True, text=True, timeout=600,
                       env=lean_env())
    return r.returncode == 0


def find_module(mathlib: Path, theorem: str, work: Path,
                module_override: str | None = None) -> str:
    """Locate the declaring module of a fully qualified theorem name.

    Declarations live inside `namespace` blocks, so the SOURCE text carries
    only the leaf name (`theorem liftOn_mk` inside `namespace Quot`); grep by
    leaf, then disambiguate candidates by actually `#check`-ing the fully
    qualified name with each candidate imported."""
    if module_override:
        return module_override
    leaf = theorem.rsplit(".", 1)[-1]
    cands: list[str] = []
    for kw in ("theorem", "lemma"):
        r = subprocess.run(
            ["git", "grep", "-lw", f"{kw} {leaf}", "--", "Mathlib"],
            cwd=str(mathlib), capture_output=True, text=True, timeout=120)
        for l in r.stdout.splitlines():
            # git grep -l prints bare paths; tolerate path:line too
            rel = l.split(":", 1)[1] if ":" in l else l
            mod = rel[:-len(".lean")].replace("/", ".")
            if mod not in cands:
                cands.append(mod)
        if cands:
            break
    if not cands:
        raise SystemExit(f"find_module: no '{leaf}' declaration found under "
                         f"Mathlib/ in {mathlib}")
    if len(cands) == 1:
        return cands[0]
    print(f"  module candidates for {theorem}: {cands}; disambiguating "
          f"via #check")
    good = [m for m in cands
            if _decl_module_check(mathlib, m, theorem, work,
                                  m.replace(".", "_"))]
    if len(good) != 1:
        raise SystemExit(f"find_module: {theorem} resolves in {good} of "
                         f"{cands} (need exactly 1); pass --module")
    return good[0]


def dump_closure(mathlib: Path, theorem: str, module: str, work: Path,
                 timeout: int = 900) -> tuple[dict, Path]:
    """dump_env over the theorem's module; complete the closure if
    import_env_meta's closure invariant finds missing constants (recursor
    rule rhs can reach past `getUsedConstants`)."""
    defs = f"import {module}\n"
    roots = [theorem]
    path = work / "dump.lean"
    lake_cmd = ["lake", "env", "lean"]
    dump = {}
    for attempt in range(5):
        # dump_env hardcodes a 600s lean timeout (reference/olean_export.py)
        dump = dump_env(defs, roots, path=str(path), lean_cmd=lake_cmd,
                        cwd=str(mathlib))
        missing: set[str] = set()
        for name, ent in dump.items():
            refs = _const_names(ent["ty"])
            if ent["val"] is not None:
                refs |= _const_names(ent["val"])
            for r in (ent["meta"] or {}).get("rules") or []:
                rhs = r.get("rhs")
                if rhs is not None:
                    refs |= _const_names(rhs)
            missing |= {r for r in refs if r not in dump}
        if not missing:
            if attempt:
                print(f"  closure completion round {attempt}: "
                      f"+{len(roots) - 1} seeded constants")
            return dump, path
        print(f"  closure incomplete ({len(dump)} consts, {len(missing)} "
              f"missing); re-dumping with seeded roots")
        roots = roots + sorted(missing)
    raise SystemExit(f"closure did not converge for {theorem}")


def raw_jsonl(mathlib: Path, dump_lean: Path, out: Path,
              timeout: int = 900) -> None:
    """Re-run the generated dump file to capture the RAW DUMPCONST JSONL
    (identical bytes to what dump_env parsed)."""
    r = subprocess.run(["lake", "env", "lean", str(dump_lean)],
                       cwd=str(mathlib), capture_output=True, text=True,
                       timeout=timeout, env=lean_env())
    if r.returncode != 0:
        raise SystemExit(f"raw dump re-run failed:\n{r.stderr}")
    lines = [l for l in r.stdout.splitlines() if l.startswith("DUMPCONST ")]
    out.write_text("\n".join(lines) + "\n")


def load_jsonl(p: Path) -> dict[str, dict]:
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("DUMPCONST "):
            d = json.loads(line[len("DUMPCONST "):])
            out[d["n"]] = d
    return out


def round_trip(dump_jsonl: Path, rt_lean: Path, rt_jsonl: Path,
               timeout: int = 900) -> tuple[int, int]:
    """Run the kernel round trip; returns (skipped_opaques, rtmissing)."""
    env = lean_env()
    env["RT_IN"] = str(dump_jsonl)
    env["RT_OUT"] = str(rt_jsonl)
    r = subprocess.run([str(LEAN), "--run", str(rt_lean)],
                       capture_output=True, text=True, timeout=timeout, env=env)
    tail = r.stdout.strip().splitlines()
    tail = tail[-1] if tail else ""
    if r.returncode != 0:
        raise SystemExit(f"round trip failed (rc={r.returncode}):\n"
                         f"{r.stdout}\n{r.stderr}")
    skipped = int(tail.split("skipped_opaques=")[1]) if "skipped_opaques=" in tail else 0
    rtmissing = sum(1 for l in rt_jsonl.read_text().splitlines()
                    if l.startswith("RTMISSING "))
    if rtmissing != skipped:
        raise SystemExit(
            f"RTMISSING ({rtmissing}) != skipped_opaques ({skipped}): "
            "constants missing from the round-trip env beyond the documented "
            "opaque skips:\n" + "\n".join(
                l for l in rt_jsonl.read_text().splitlines()
                if l.startswith("RTMISSING ")))
    return skipped, rtmissing


def compare_dumps(orig_p: Path, rt_p: Path, skipped: int) -> list[str]:
    """Field-by-field compare; skips ind.isStruct/ind.nf (elaborator
    structureExt data, not kernel ConstantInfo) and the skipped opaques."""
    orig = load_jsonl(orig_p)
    rt = load_jsonl(rt_p)
    diffs = []
    for n in sorted(orig):
        if n not in rt:
            if skipped:
                continue   # documented opaque skip (RTMISSING already checked)
            diffs.append(f"{n}: absent from round-trip output")
            continue
        a, b = orig[n], rt[n]
        for k in sorted(set(a) | set(b)):
            if k == "ind":
                ia = {kk: vv for kk, vv in (a[k] or {}).items()
                      if kk not in ("isStruct", "nf")}
                ib = {kk: vv for kk, vv in (b[k] or {}).items()
                      if kk not in ("isStruct", "nf")}
                if ia != ib:
                    diffs.append(f"{n}.ind: {json.dumps(ia)} != {json.dumps(ib)}")
            elif a.get(k) != b.get(k):
                diffs.append(f"{n}.{k}: differs")
    return diffs


def encode_and_stats(dump: dict) -> dict:
    """ENV encoding via the WP1 metadata channel + scale stats."""
    consts, ctors, structs, meta = import_env_meta("", [], dump=dump)
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    kinds: dict[str, int] = {}
    for ent in dump.values():
        kinds[ent["kind"]] = kinds.get(ent["kind"], 0) + 1
    clamped = sum(1 for m in meta.values()
                  if int(m.get("height", 0) or 0) > 4095)
    return {
        "n_consts": len(consts),
        "n_tokens": len(enc.b.stream),
        "env_bytes": len(enc.b.stream) * TOKEN_BYTES,
        "kinds": dict(sorted(kinds.items())),
        "n_ctors": len(ctors),
        "n_structs": len(structs),
        "n_lparams_consts": sum(1 for m in meta.values() if m.get("lparams")),
        "height_clamped": clamped,
        "bundle": enc.b,
        "consts": consts,
        "meta": meta,
        "dump": dump,
    }


def _dec_level(b, pos: int, memo: dict, depth: int = 0) -> "Level":
    from expr.model import (KL_ZERO, KL_SUCC, KL_MAX, KL_IMAX, KL_PARAM,
                            KL_MVAR, LZero, LSucc, LMax, LIMax, LParam)
    if depth > 1000:
        raise ValueError(f"level tree too deep at {pos}")
    t = b.stream[pos]
    K = t[0]
    if K == KL_ZERO:
        return LZero()
    if K == KL_SUCC:
        return LSucc(_dec_level(b, t[1], memo, depth + 1))
    if K == KL_MAX:
        return LMax(_dec_level(b, t[1], memo, depth + 1),
                    _dec_level(b, t[2], memo, depth + 1))
    if K == KL_IMAX:
        return LIMax(_dec_level(b, t[1], memo, depth + 1),
                     _dec_level(b, t[2], memo, depth + 1))
    if K == KL_PARAM:
        return LParam(b.id_names[t[1]])
    if K == KL_MVAR:
        return LParam(b.id_names[t[1]])  # unreachable in env constants
    raise ValueError(f"unknown level kind {K} at {pos}")


def _dec_expr(b, root: int) -> "Expr":
    """Iterative (explicit-stack) structural readback of the expr-token
    layout produced by expr.tokens.Encoder — same contract as
    expr.tokens.decode_expr, but proof terms from real Mathlib theorems can
    be thousands of nodes deep, past Python's recursion limit."""
    from expr.model import (
        K_BVAR, K_SORT, K_CONST, K_APP, K_LAM, K_PI, K_LET, K_LIT, K_MDATA,
        K_PROJ, LIT_NAT, LIT_STR, BVar, Sort, Const, App, Lam, Pi, Let,
        LitNat, LitStr, MData, Proj,
    )
    memo: dict[int, object] = {}
    stack = [root]
    while stack:
        pos = stack[-1]
        if pos in memo:
            stack.pop()
            continue
        K, V0, V1, V2, X, E2, F2 = b.stream[pos]
        if K == K_BVAR:
            memo[pos] = BVar(V0)
            stack.pop()
        elif K == K_SORT:
            memo[pos] = Sort(_dec_level(b, V0, memo))
            stack.pop()
        elif K == K_CONST:
            lvl_pos = []
            r = V1
            while r:
                lvl_pos.append(r)
                r = b.stream[r][4]
            # levels decode inline (small trees); they must NOT enter the
            # expression stack - KL_PARAM's K=5 collides with K_CONST's K=5
            memo[pos] = Const(b.cid_names[V0],
                              tuple(_dec_level(b, p, memo) for p in lvl_pos))
            stack.pop()
        elif K == K_APP:
            f, a = memo.get(V0), memo.get(V1)
            if f is None:
                stack.append(V0)
            if a is None:
                stack.append(V1)
            if f is not None and a is not None:
                memo[pos] = App(f, a)
                stack.pop()
        elif K in (K_LAM, K_PI):
            d, body = memo.get(V0), memo.get(V1)
            if d is None:
                stack.append(V0)
            if body is None:
                stack.append(V1)
            if d is not None and body is not None:
                memo[pos] = (Lam("", X, d, body) if K == K_LAM
                             else Pi("", X, d, body))
                stack.pop()
        elif K == K_LET:
            ty, v, body = memo.get(V0), memo.get(V1), memo.get(X)
            if ty is None:
                stack.append(V0)
            if v is None:
                stack.append(V1)
            if body is None:
                stack.append(X)
            if ty is not None and v is not None and body is not None:
                memo[pos] = Let("", ty, v, body)
                stack.pop()
        elif K == K_LIT:
            if V1 == LIT_NAT:
                value = 0
                for i in range(V0):
                    d = b.stream[pos + 2 + 2 * i][1]
                    value += d * (10 ** i)
                memo[pos] = LitNat(value)
            elif V1 == LIT_STR:
                data = bytes(b.stream[pos + 2 + 2 * i][1] for i in range(V0))
                memo[pos] = LitStr(data.decode("utf-8", "surrogatepass"))
            else:
                raise ValueError(f"unknown literal kind {V1} at {pos}")
            stack.pop()
        elif K == K_MDATA:
            c = memo.get(V0)
            if c is None:
                stack.append(V0)
                continue
            memo[pos] = MData(c)
            stack.pop()
        elif K == K_PROJ:
            c = memo.get(X)
            if c is None:
                stack.append(X)
                continue
            memo[pos] = Proj(b.id_names[V0], V1, c)
            stack.pop()
        else:
            raise ValueError(f"unknown token kind {K} at {pos}")
    return memo[root]


def decode_readback(st) -> list[str]:
    """Structural readback through the expr.tokens decode path (no
    evaluation): the metadata chain per cid via decode_env_meta, plus a full
    iterative readback of every constant's type tree (and value tree for
    def/thm) compared against the source Expr trees from the dump."""
    b = st["bundle"]
    errs = []
    for cid in range(st["n_consts"]):
        try:
            decode_env_meta(b, cid)
        except Exception as e:  # noqa: BLE001 - report and continue
            errs.append(f"cid {cid} ({b.cid_names.get(cid)}): "
                        f"decode_env_meta: {e}")
    for cid, (name, ty, val) in enumerate(st["consts"]):
        try:
            rt = _dec_expr(b, b.const_type_pos[cid])
            if rt != ty:
                errs.append(f"cid {cid} ({name}): type readback mismatch")
        except Exception as e:  # noqa: BLE001
            errs.append(f"cid {cid} ({name}): type readback: {e}")
        if val is not None:
            try:
                rv = _dec_expr(b, b.const_value_pos[cid])
                if rv != val:
                    errs.append(f"cid {cid} ({name}): value readback mismatch")
            except Exception as e:  # noqa: BLE001
                errs.append(f"cid {cid} ({name}): value readback: {e}")
    return errs


def process(mathlib: Path, theorem: str, out_dir: Path,
            module_override: str | None = None) -> dict:
    t0 = time.time()
    work = out_dir / theorem.replace(".", "_")
    work.mkdir(parents=True, exist_ok=True)
    module = find_module(mathlib, theorem, work, module_override)
    print(f"== {theorem}  (module {module}) ==")
    dump, dump_lean = dump_closure(mathlib, theorem, module, work)
    print(f"  closure: {len(dump)} constants ({time.time() - t0:.1f}s)")
    jsonl = work / "dump.jsonl"
    raw_jsonl(mathlib, dump_lean, jsonl)
    rt_lean = work / "rt.lean"
    rt_lean.write_text(RT_TEMPLATE)
    rt_jsonl = work / "rt.jsonl"
    skipped, rtmissing = round_trip(jsonl, rt_lean, rt_jsonl)
    diffs = compare_dumps(jsonl, rt_jsonl, skipped)
    print(f"  round trip: skipped_opaques={skipped}, diffs={len(diffs)}")
    for d in diffs[:20]:
        print(f"    DIFF {d}")
    st = encode_and_stats(dump)
    print(f"  ENV: {st['n_consts']} consts, {st['n_tokens']} tokens, "
          f"{st['env_bytes']} bytes ({st['n_ctors']} ctors, "
          f"{st['n_structs']} structs, lparams consts "
          f"{st['n_lparams_consts']}, height>4095 clamped {st['height_clamped']})")
    print(f"  kinds: {st['kinds']}")
    md_errs = decode_readback(st)
    print(f"  decode readback: {st['n_consts'] - len(md_errs)}/"
          f"{st['n_consts']} cids clean")
    for e in md_errs[:10]:
        print(f"    DECODE {e}")
    return {"theorem": theorem, "module": module, "stats": st,
            "diffs": diffs, "skipped_opaques": skipped, "rtmissing": rtmissing,
            "decode_errs": md_errs, "wall_s": time.time() - t0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mathlib", default="/home/xkq/mathlib_src", type=Path)
    ap.add_argument("--theorem", action="append", required=True)
    ap.add_argument("--out-dir", type=Path,
                    default=Path("/home/xkq/logs/012I/closures"))
    ap.add_argument("--module", action="append", default=[],
                    help="module override per theorem (same order/orderless)")
    args = ap.parse_args()
    if not (args.mathlib / "lean-toolchain").exists():
        raise SystemExit(f"no lean-toolchain under {args.mathlib}")
    mods = dict(zip(args.theorem, args.module)) if args.module else {}
    results = [process(args.mathlib, t, args.out_dir, mods.get(t))
               for t in args.theorem]
    total_c = sum(r["stats"]["n_consts"] for r in results)
    total_d = sum(len(r["diffs"]) for r in results) + \
        sum(len(r["decode_errs"]) for r in results)
    print(f"\n=== {len(results)} theorems, {total_c} constants total, "
          f"{total_d} diffs/decode errors ===")
    return 0 if total_d == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
