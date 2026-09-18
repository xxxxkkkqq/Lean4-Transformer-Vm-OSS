"""Phase 5 M4.1 — .olean constant-subset export (VM_SPEC §11.1).

Dumps the REAL environment constants a target proof depends on (transitive
closure over type/value Const references) out of the `lean` binary via the
Lean.Environment API, and imports them as a (consts, ctors, structs) triple
that expr/tokens.Encoder + lean_vm/ref_vm.py + lean_vm/build_vm.py consume —
so delta expansion covers arbitrary environment constants, not just the
hand-written TOY_CONSTS mirror.

Pipeline:
  1. dump_env(defs, roots): generate a Lean file (serExpr serializer +
     #DUMP_ENV elab), compile it with the real lean binary, parse one
     DUMPCONST JSON line per constant in the transitive closure.
  2. import_env(...): prune the closure at TOY_NAMES (the toy table models
     the kernel's built-in Nat ops / Bool / True — their real values are
     iota machinery (Nat.brecOn/Nat.rec) that Phase 6 owns); normalize the
     closed-numeral pattern `OfNat.ofNat Nat n (instOfNatNat n)` → LitNat n
     (exactly what the kernel's whnf computes via delta+beta+proj — avoids
     importing the universe-polymorphic OfNat machinery, §9.2 gap); validate
     every remaining constant against the M4 slice (monomorphic, no
     fvar/mvar/LParam/LitStr, Const refs only into toy ∪ included); emit
     (name, type, value) triples in dependency-free order appended AFTER
     TOY_CONSTS so the step graph's hardcoded cids (nat ops, Bool, P2) stay
     valid.

Known M4.1 subset limits (VM_SPEC §11.1):
  - univ_arity must be 0 (universe polymorphism = Phase 6).
  - the step graph's proj reduction + structural eta gate on P2 build-time
    cids, so graph-layer corpora must not exercise Proj/eta-struct on NEW
    structures (RefVM is data-driven and does).

Additive WP1 metadata channel (VM_SPEC §13.7 item 1): `const_meta_entry`,
`const_meta_for`, `import_env_meta` convert a real dump closure — every
ConstantInfo kind, Recursor included — into a constant list plus a cid-keyed
Encoder `const_meta` (ENV_FORMAT §2.4). They do not alter `import_env`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from expr.model import (
    BVar, FVar, MVar, Sort, Const, App, Lam, Pi, Let, LitNat, LitStr,
    MData, Proj, LZero, LSucc, LMax, LIMax, LParam, LMVar, Expr,
)
from reference.lean_ref import LEAN, json_to_expr
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_STRUCTS

TOY_NAMES = {name for name, _, _ in TOY_CONSTS}

# ── Lean-side dumper (API names calibrated against the 4.33.1 binary:
# ConstantVal.levelParams, InductiveVal.numParams/ctors, getStructureInfo?) ──
DUMP_TEMPLATE = """\
import Lean
@@IMPORTS@@
open Lean Elab Command

partial def serLevel : Level → String
  | .zero => "{\\"k\\":1}"
  | .succ l => "{\\"k\\":2,\\"a\\":" ++ serLevel l ++ "}"
  | .max a b => "{\\"k\\":3,\\"a\\":" ++ serLevel a ++ ",\\"b\\":" ++ serLevel b ++ "}"
  | .imax a b => "{\\"k\\":4,\\"a\\":" ++ serLevel a ++ ",\\"b\\":" ++ serLevel b ++ "}"
  | .param n => "{\\"k\\":5,\\"n\\":\\"" ++ n.toString ++ "\\"}"
  | .mvar n => "{\\"k\\":6,\\"n\\":\\"" ++ n.name.toString ++ "\\"}"

def biNat : BinderInfo → Nat
  | .default => 0 | .implicit => 1 | .strictImplicit => 2 | .instImplicit => 3

partial def serExpr : Expr → String
  | .bvar i => "{\\"k\\":1,\\"i\\":" ++ toString i ++ "}"
  | .fvar n => "{\\"k\\":2,\\"n\\":\\"" ++ n.name.toString ++ "\\"}"
  | .mvar n => "{\\"k\\":3,\\"n\\":\\"" ++ n.name.toString ++ "\\"}"
  | .sort l => "{\\"k\\":4,\\"l\\":" ++ serLevel l ++ "}"
  | .const n ls => "{\\"k\\":5,\\"n\\":\\"" ++ n.toString ++ "\\",\\"u\\":[" ++
      String.intercalate "," (ls.map serLevel) ++ "]}"
  | .app f a => "{\\"k\\":6,\\"f\\":" ++ serExpr f ++ ",\\"a\\":" ++ serExpr a ++ "}"
  | .lam _ t b bi => "{\\"k\\":7,\\"bi\\":" ++ toString (biNat bi) ++ ",\\"t\\":" ++ serExpr t ++ ",\\"b\\":" ++ serExpr b ++ "}"
  | .forallE _ t b bi => "{\\"k\\":8,\\"bi\\":" ++ toString (biNat bi) ++ ",\\"t\\":" ++ serExpr t ++ ",\\"b\\":" ++ serExpr b ++ "}"
  | .letE _ t v b _ => "{\\"k\\":9,\\"t\\":" ++ serExpr t ++ ",\\"v\\":" ++ serExpr v ++ ",\\"b\\":" ++ serExpr b ++ "}"
  | .lit l => match l with
      | .natVal v => "{\\"k\\":10,\\"nat\\":" ++ toString v ++ "}"
      | .strVal s => "{\\"k\\":10,\\"str\\":\\"" ++ s ++ "\\"}"
  | .mdata _ c => "{\\"k\\":11,\\"c\\":" ++ serExpr c ++ "}"
  | .proj s i c => "{\\"k\\":12,\\"s\\":\\"" ++ s.toString ++ "\\",\\"i\\":" ++
      toString i ++ ",\\"c\\":" ++ serExpr c ++ "}"

def usedOf (env : Environment) (n : Name) : Array Name :=
  match env.find? n with
  | none => #[]
  | some ci =>
    let base := ci.type.getUsedConstants
    match ci with
    | .defnInfo d => base ++ d.value.getUsedConstants
    | .thmInfo t => base ++ t.value.getUsedConstants
    | .inductInfo i => base ++ i.ctors
    | _ => base

partial def collect (env : Environment) (n : Name) (seen : NameSet) : NameSet :=
  if seen.contains n then seen else
    let seen := seen.insert n
    (usedOf env n).foldl (fun s m => collect env m s) seen

def jstr (s : String) : String :=
  "\\"" ++ (s.foldl (fun acc c =>
    if c == '"' then acc ++ "\\\\\\""
    else if c == '\\\\' then acc ++ "\\\\\\\\"
    else acc.push c) "") ++ "\\""

-- ── full ConstantInfo metadata (ENV_FORMAT §1/§5.2) ────────────────────────
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
    "{\\"ctor\\":" ++ jstr r.ctor.toString ++ ",\\"nfields\\":" ++ toString r.nfields ++
    ",\\"rhs\\":" ++ serExpr r.rhs ++ "}")) ++ "]"

def metaJson (ci : ConstantInfo) : String :=
  match ci with
  | .axiomInfo a => "{\\"kind\\":0,\\"isUnsafe\\":" ++ toString a.isUnsafe ++ "}"
  | .defnInfo d => "{\\"kind\\":1,\\"hints\\":" ++ toString (hintKind d.hints) ++
      ",\\"height\\":" ++ toString (hintHeight d.hints) ++
      ",\\"safety\\":" ++ toString (safetyNat d.safety) ++
      ",\\"isUnsafe\\":" ++ toString (safetyNat d.safety == 0) ++
      ",\\"all\\":" ++ serNames d.all ++ "}"
  | .thmInfo t => "{\\"kind\\":2,\\"all\\":" ++ serNames t.all ++ "}"
  | .opaqueInfo o => "{\\"kind\\":3,\\"isUnsafe\\":" ++ toString o.isUnsafe ++
      ",\\"all\\":" ++ serNames o.all ++ "}"
  | .quotInfo q => "{\\"kind\\":4,\\"quotKind\\":" ++ toString (quotKindNat q.kind) ++ "}"
  | .inductInfo i => "{\\"kind\\":5,\\"np\\":" ++ toString i.numParams ++
      ",\\"ni\\":" ++ toString i.numIndices ++ ",\\"nn\\":" ++ toString i.numNested ++
      ",\\"isRec\\":" ++ toString i.isRec ++ ",\\"isUnsafe\\":" ++ toString i.isUnsafe ++
      ",\\"isRefl\\":" ++ toString i.isReflexive ++
      ",\\"all\\":" ++ serNames i.all ++ ",\\"ctors\\":" ++ serNames i.ctors ++ "}"
  | .ctorInfo c => "{\\"kind\\":6,\\"induct\\":" ++ jstr c.induct.toString ++
      ",\\"cidx\\":" ++ toString c.cidx ++ ",\\"np\\":" ++ toString c.numParams ++
      ",\\"nfields\\":" ++ toString c.numFields ++
      ",\\"isUnsafe\\":" ++ toString c.isUnsafe ++ "}"
  | .recInfo r => "{\\"kind\\":7,\\"np\\":" ++ toString r.numParams ++
      ",\\"ni\\":" ++ toString r.numIndices ++ ",\\"nm\\":" ++ toString r.numMotives ++
      ",\\"nmin\\":" ++ toString r.numMinors ++ ",\\"isK\\":" ++ toString r.k ++
      ",\\"isUnsafe\\":" ++ toString r.isUnsafe ++
      ",\\"all\\":" ++ serNames r.all ++ ",\\"rules\\":" ++ serRules r.rules ++ "}"

elab "#DUMP_ENV" names:ident* : command => do
  let env ← liftCoreM getEnv
  let mut seen : NameSet := {}
  for id in names do
    let n ← resolveGlobalConstNoOverload id
    seen := collect env n seen
  let mut ns := seen.toArray.map toString
  ns := ns.qsort fun a b => a < b
  for s in ns do
    let some ci := env.find? (String.toName s) | continue
    let kind := match ci with
      | .axiomInfo _ => "axiom"
      | .defnInfo _ => "def"
      | .thmInfo _ => "thm"
      | .opaqueInfo _ => "opaque"
      | .quotInfo _ => "quot"
      | .inductInfo _ => "ind"
      | .ctorInfo _ => "ctor"
      | .recInfo _ => "rec"
    let up := String.intercalate "," (ci.levelParams.map (fun n => jstr n.toString))
    let ty := serExpr ci.type
    let val := match ci with
      | .defnInfo d => serExpr d.value
      | .thmInfo t => serExpr t.value
      | _ => "null"
    let ind := match ci with
      | .inductInfo i => "{\\"ctors\\":[" ++ String.intercalate ","
          (i.ctors.map (fun c => jstr c.toString)) ++ "],\\"np\\":" ++ toString i.numParams ++
          ",\\"isStruct\\":" ++ toString (getStructureInfo? env (String.toName s) |>.isSome) ++
          ",\\"nf\\":" ++ match getStructureInfo? env (String.toName s) with
            | some si => toString si.fieldNames.size ++ "}"
            | none => "0" ++ "}"
      | _ => "null"
    IO.println ("DUMPCONST " ++ "{\\"n\\":" ++ jstr s ++ ",\\"kind\\":\\"" ++ kind ++
      "\\",\\"up\\":[" ++ up ++ "],\\"ty\\":" ++ ty ++ ",\\"val\\":" ++ val ++
      ",\\"ind\\":" ++ ind ++ ",\\"meta\\":" ++ metaJson ci ++ "}")

@@DEFS@@

#DUMP_ENV @@ROOTS@@
"""


class ExportError(Exception):
    pass


def dump_env(defs: str, roots: list[str], path: str = "/tmp/vm_dump_env.lean",
             lean_cmd: list[str] | None = None, cwd: str | None = None
             ) -> dict[str, dict]:
    """Compile defs+roots with the real lean binary; return the closure dump
    {name: {kind, up, ty(dict), val(dict|None), ind(dict|None)}}.

    lean_cmd/cwd run the dump inside a lake project (e.g.
    ["lake","env","lean"] + cwd=<mathlib project> for Mathlib roots).
    `import ...` lines inside defs are hoisted to the file top (Lean
    requires imports before any other command)."""
    imps = "".join(ln + "\n" for ln in defs.splitlines()
                   if ln.strip().startswith("import "))
    rest = "\n".join(ln for ln in defs.splitlines()
                     if not ln.strip().startswith("import "))
    body = (DUMP_TEMPLATE.replace("@@IMPORTS@@", imps)
               .replace("@@DEFS@@", rest)
               .replace("@@ROOTS@@", " ".join(roots)))
    Path(path).write_text(body)
    r = subprocess.run(list(lean_cmd or [str(LEAN)]) + [path],
                       capture_output=True, text=True, timeout=600, cwd=cwd)
    if r.returncode != 0:
        raise ExportError(f"lean failed:\n{r.stderr}")
    out: dict[str, dict] = {}
    for line in r.stdout.splitlines():
        if not line.startswith("DUMPCONST "):
            continue
        d = json.loads(line[len("DUMPCONST "):])
        meta = d.get("meta")
        if meta is not None and "rules" in meta:
            for rule in meta["rules"]:
                rule["rhs"] = json_to_expr(rule["rhs"])
        out[d["n"]] = {
            "kind": d["kind"], "up": d["up"],
            "ty": json_to_expr(d["ty"]),
            "val": json_to_expr(d["val"]) if d["val"] is not None else None,
            "ind": d["ind"],
            "meta": meta,
        }
    if not out:
        raise ExportError("no DUMPCONST lines in lean output")
    return out


# ── expr traversal helpers ----------------------------------------------------

def _rewrite(e, fn):
    """Bottom-up structural rewrite."""
    if isinstance(e, App):
        e = App(_rewrite(e.fn, fn), _rewrite(e.arg, fn))
    elif isinstance(e, Lam):
        e = Lam(e.name, e.binfo, _rewrite(e.domain, fn), _rewrite(e.body, fn))
    elif isinstance(e, Pi):
        e = Pi(e.name, e.binfo, _rewrite(e.domain, fn), _rewrite(e.body, fn))
    elif isinstance(e, Let):
        e = Let(e.name, _rewrite(e.domain, fn), _rewrite(e.value, fn),
                _rewrite(e.body, fn), nondep=e.nondep)
    elif isinstance(e, MData):
        e = MData(_rewrite(e.child, fn))
    elif isinstance(e, Proj):
        e = Proj(e.sname, e.idx, _rewrite(e.child, fn))
    return fn(e)


def _norm_num(e):
    """Closed Nat numeral: OfNat.ofNat (u=[0]) Nat n (instOfNatNat n) → LitNat n.
    Mirrors the kernel whnf (delta OfNat.ofNat → beta → proj → delta
    instOfNatNat → OfNat.mk → proj → literal) without importing the
    universe-polymorphic OfNat machinery (§9.2 Phase-6 gap)."""
    head, args = _spine(e)
    if (isinstance(head, Const) and head.name == "OfNat.ofNat"
            and head.levels == (LZero(),) and len(args) == 3
            and args[0] == Const("Nat") and isinstance(args[1], LitNat)
            and isinstance(args[2], App)):
        ih, ia = _spine(args[2])
        if (isinstance(ih, Const) and ih.name == "instOfNatNat"
                and ih.levels == () and len(ia) == 1 and ia[0] == args[1]):
            return args[1]
    return e


_HBIN = {"HAdd.hAdd": ("instHAdd", "Nat.add"),
         "HMul.hMul": ("instHMul", "Nat.mul"),
         "HSub.hSub": ("instHSub", "Nat.sub"),
         "HPow.hPow": ("instHPow", "Nat.pow"),
         "HDiv.hDiv": ("instHDiv", "Nat.div"),
         "HMod.hMod": ("instHMod", "Nat.mod"),
         "HShiftLeft.hShiftLeft": ("instHShiftLeft", "Nat.shiftLeft"),
         "HShiftRight.hShiftRight": ("instHShiftRight", "Nat.shiftRight")}


_ELIM_SWAPS = {           # eliminator → complete-application arg counts
    "Nat.casesOn": (4,),
    "Bool.casesOn": (4,),
    "P2.casesOn": (3,),
}


def _norm_elim_spine(e):
    """Eliminator spine reorder at the export boundary: the kernel stores
    casesOn applications as (motive, major, ...), but the toy table — and
    hence the compiled graph — declares them in (major, motive, ...) order
    (RefVM.caseson major_idx=0, nargs=2+len(ctors)).  Exported real terms
    are re-ordered; the convention itself is baked into the weights, so the
    DATA adapts.  Nat.rec already agrees in (motive, ...) order, and
    Nat.brecOn is NOT swapped — it is redirected to the real def (see
    _norm_pprod), whose binder order already matches the serialization."""
    head, args = _spine(e)
    if (isinstance(head, Const) and head.name in _ELIM_SWAPS
            and len(args) in _ELIM_SWAPS[head.name]):
        # fire only on complete applications: _rewrite visits every partial
        # spine node, and swapping a 2-arg prefix twice cancels out
        new = [args[1], args[0]] + list(args[2:])
        out = Const(head.name)
        for a in new:
            out = App(out, a)
        return out
    return e


def _norm_pprod(e):
    """Structure-convention adaptation at the export boundary (DATA adapts;
    the graph's compiled primitives are the toy's):

    - Proj(sname='PProd') → Proj('P2'): real below-chains are PProd pairs,
      the graph's proj iota is keyed on the toy structure (field order
      agrees: value first, recursive tail second).
    - `PProd α β` (2-arg type former) → Const P2, `PProd.mk α β a b`
      (full 4-arg = params + fields) → P2.mk a b: the toy P2 is the
      0-param monomorphic stand-in (types never whnf; binder domains are
      inert data, toy_env _below_value note).
    - PUnit / PUnit.unit → UnitT / UnitT.mk (toy names).
    - Nat.brecOn → Nat.brecOn.real: the toy's pair-free def-over-rec cannot
      feed real equation-compiled F's (they destruct the below-pair with
      .1/.2); brecOn.real is an injected def (_brecOn_real_value) computing
      the kernel's value via casesOn+rec+P2 pairs — graph primitives only,
      ending on the F application (no top-level Proj)."""
    if isinstance(e, Proj):
        if e.sname == "PProd":
            return Proj("P2", e.idx, e.child)
        return e
    head, args = _spine(e)
    if isinstance(head, Const):
        n = head.name
        if n == "Nat.brecOn":
            # keep the use-site levels: brecOn.real is universe-polymorphic
            # (a dump clone) and gets specialized at that exact vector
            out = Const("Nat.brecOn.real", head.levels)
            for a in args:
                out = App(out, a)
            return out
        if n == "PProd" and len(args) == 2:
            return Const("P2")
        if n == "PProd.mk" and len(args) == 4:
            return App(App(Const("P2.mk"), args[2]), args[3])
        if n == "PUnit" and not args:
            return Const("UnitT")
        if n == "PUnit.unit" and not args:
            return Const("UnitT.mk")
    return e


def _norm_hbinop(e):
    """Nat instance-scaffolding rewrite: HAdd.hAdd Nat Nat Nat (instHAdd Nat
    instAddNat) a b → Nat.add a b — exactly the whnf the kernel produces after
    delta+instance unfolds, so it preserves defeq semantics while keeping the
    universe-polymorphic class machinery (§9.2 Phase-6) out of the M4 slice."""
    head, args = _spine(e)
    if (isinstance(head, Const) and head.name in _HBIN and len(args) == 6
            and head.levels == (LZero(), LZero(), LZero())
            and args[0] == args[1] == args[2] == Const("Nat")):
        cname, target = _HBIN[head.name]
        ih, _ = _spine(args[3])
        if (isinstance(ih, Const) and ih.name.rsplit(".", 1)[-1].startswith(cname)
                and all(isinstance(l, LZero) for l in ih.levels)):
            return App(App(Const(target), args[4]), args[5])
    return e


def _spine(e):
    args = []
    while isinstance(e, App):
        args.append(e.arg)
        e = e.fn
    return e, list(reversed(args))


def _const_names(e, acc=None):
    if acc is None:
        acc = set()
    if isinstance(e, Const):
        acc.add(e.name)
    elif isinstance(e, App):
        _const_names(e.fn, acc); _const_names(e.arg, acc)
    elif isinstance(e, (Lam, Pi)):
        _const_names(e.domain, acc); _const_names(e.body, acc)
    elif isinstance(e, Let):
        _const_names(e.domain, acc); _const_names(e.value, acc)
        _const_names(e.body, acc)
    elif isinstance(e, MData):
        _const_names(e.child, acc)
    elif isinstance(e, Proj):
        _const_names(e.child, acc)
    return acc


def _validate(e, where: str, allowed: set[str]):
    """M4-slice check: no meta vars, no universe params, no string literals,
    Const refs only into toy ∪ included, all with empty level args."""
    def go(x):
        if isinstance(x, (FVar, MVar)):
            raise ExportError(f"{where}: {type(x).__name__} not in M4 slice")
        if isinstance(x, LitStr):
            raise ExportError(f"{where}: string literal not in M4 slice")
        if isinstance(x, Const):
            if x.levels:
                raise ExportError(f"{where}: Const {x.name} has level args (univ poly, §9.2)")
            if x.name not in allowed:
                raise ExportError(f"{where}: unsupported constant {x.name}")
        if isinstance(x, Sort):
            _validate_level(x.level, where)
    _rewrite(e, go)


def _validate_level(l, where):
    if isinstance(l, (LParam, LMVar)):
        raise ExportError(f"{where}: universe param {l.name} (univ poly, §9.2)")
    if isinstance(l, LSucc):
        _validate_level(l.l, where)
    elif isinstance(l, (LMax, LIMax)):
        _validate_level(l.a, where); _validate_level(l.b, where)


def _check_concrete_level(l, where):
    if isinstance(l, (LParam, LMVar)):
        raise ExportError(f"{where}: non-concrete use-site universe {l}")
    if isinstance(l, LSucc):
        _check_concrete_level(l.l, where)
    elif isinstance(l, (LMax, LIMax)):
        _check_concrete_level(l.a, where)
        _check_concrete_level(l.b, where)


def _spec_lv(l, mapping):
    if isinstance(l, LParam):
        return mapping.get(l.name, l)
    if isinstance(l, LSucc):
        return LSucc(_spec_lv(l.l, mapping))
    if isinstance(l, LMax):
        return LMax(_spec_lv(l.a, mapping), _spec_lv(l.b, mapping))
    if isinstance(l, LIMax):
        return LIMax(_spec_lv(l.a, mapping), _spec_lv(l.b, mapping))
    return l


def _spec_expr(e, mapping):
    def go(x):
        if isinstance(x, Const):
            return Const(x.name, tuple(_spec_lv(l, mapping)
                                       for l in x.levels))
        if isinstance(x, Sort):
            return Sort(_spec_lv(x.level, mapping))
        return x
    return _rewrite(e, go)


def _const_refs(e, acc=None):
    """(name, levels) pairs of every Const in e — levels are use-site data,
    which is what makes level specialization of polymorphic auxiliaries
    sound (single concrete instantiation ⇒ monomorphic constant)."""
    if acc is None:
        acc = set()

    def go(x):
        if isinstance(x, Const):
            acc.add((x.name, x.levels))
    _rewrite(e, go)
    return acc


def _brecOn_real_value():
    """Nat.brecOn as a def over casesOn+rec — the same value the kernel's
    `λ mot t F, (go mot t F).1` computes at every level, but ending in an
    F APPLICATION, not a Proj.  Load-bearing for the graph layer: the
    compiled I_PROJ branch honors "a proj reduction ends whnf" for
    TASK_WHNF callers (P7.5c-2 — the raw field is returned; the weights
    bake that contract), so the kernel's value form leaves every real
    equation-compiled F stuck at a raw application head.  Here the casesOn
    iota (nat_lit_to_constructor, both VMs) fires on the literal major and
    delivers `F t (go t)` directly; the P2-projections live only in ARG
    positions, where the graph's pr_arg_target continues with E=0.
    go t = ⟨value at t, below chain at t⟩ over the faithful real pair
    layout (go 0 = ⟨F 0 ⟨⟩, ⟨⟩⟩, go (k+1) = ⟨F (k+1) (go k), go k⟩);
    binder domains are decorative — whnf/iota never validates them
    (toy_env _below_value note)."""
    S1 = Sort(LSucc(LZero()))
    CZ, CS = Const("Nat.zero"), Const("Nat.succ")
    CU = Const("UnitT.mk")
    MK = Const("P2.mk")
    # value body ctx [F, t, mot]
    alt0 = App(App(BVar(0), CZ), CU)                     # F 0 ⟨⟩
    # succ-alt ctx [k, F, t, mot]; go-chain ctx [ih, k2, k, F, t, mot]
    s_body = App(App(MK, App(App(BVar(3), App(CS, BVar(1))), BVar(0))),
                 BVar(0))                                # ⟨F (succ k2) ih, ih⟩
    go_k = App(App(App(App(Const("Nat.rec"), Lam("", 0, Const("Nat"), S1)),
                       App(App(MK, App(App(BVar(1), CZ), CU)), CU)),
                  Lam("", 0, Const("Nat"), Lam("", 0, S1, s_body))),
             BVar(0))
    succ_alt = Lam("", 0, Const("Nat"),
                   App(App(BVar(1), App(CS, BVar(0))), go_k))   # F (succ k) (go k)
    # Fty under ctx [t, mot]; its body ctx [bh, t2, t, mot]
    Fty = Pi("", 0, Const("Nat"),
             Pi("", 0, S1, App(BVar(3), BVar(1))))
    # casesOn emitted in REAL serialization order (motive, major, alts) —
    # _norm_elim_spine swaps it to the toy (major, motive, alts) order
    return Lam("", 0, Pi("", 0, Const("Nat"), S1),
               Lam("", 0, Const("Nat"),
                   Lam("", 0, Fty,
                       App(App(App(App(Const("Nat.casesOn"), BVar(2)),
                                   BVar(1)), alt0), succ_alt))))


# ── import --------------------------------------------------------------------

def import_env(defs: str, roots: list[str],
               dump: dict[str, dict] | None = None
               ) -> tuple[list, set, dict]:
    """Return (consts, ctors, structs) = TOY_* with the validated exported
    subset appended (cids ≥ len(TOY_CONSTS), so the step graph's hardcoded
    cids stay valid).

    M4 slice, plus one generalization: a universe-polymorphic closure
    constant (equation-compiler match_1 combinators, Nat.iterate, …) is
    ACCEPTED when every use site carries the SAME concrete level vector —
    it is specialized at that vector (exactly the instantiation the kernel
    works with for this definition) and enters the table as a monomorphic
    constant; residual params or mixed sites reject the root (§9.2 gap)."""
    if dump is None:
        dump = dump_env(defs, roots)
    # inject the real brecOn def under an export name (Nat.brecOn →
    # Nat.brecOn.real is rewritten by _norm_pprod): the toy Nat.brecOn
    # (pair-free def-over-rec) cannot feed real equation-compiled F's,
    # which destruct the below-pair.  The value is _brecOn_real_value() —
    # the kernel's def re-ended on an F application (graph proj contract).
    if "Nat.brecOn" in dump and "Nat.brecOn.real" not in dump:
        dump = dict(dump)
        dump["Nat.brecOn.real"] = {**dump["Nat.brecOn"],
                                   "val": _brecOn_real_value()}
    norm: dict[str, dict] = {}
    for name, ent in dump.items():
        def nrm(x):
            return _rewrite(x, lambda y: _norm_elim_spine(
                _norm_pprod(_norm_hbinop(_norm_num(y)))))
        norm[name] = {"kind": ent["kind"], "up": ent["up"],
                      "ty": nrm(ent["ty"]),
                      "val": nrm(ent["val"]) if ent["val"] is not None
                      else None,
                      "ind": ent["ind"]}
    included: dict[str, dict] = {}
    sites: dict[str, set] = {}
    for r in roots:
        sites.setdefault(r, set()).add(())

    def visit(name: str):
        if name in TOY_NAMES or name in included:
            return
        if name not in norm:
            raise ExportError(f"constant {name} missing from dump")
        ent = norm[name]
        if ent["kind"] not in ("def", "ctor", "ind"):
            raise ExportError(f"{name}: kind {ent['kind']} not in M4 slice")
        ty, val = ent["ty"], ent["val"]
        if ent["up"]:
            vecs = sites.get(name, set())
            if len(vecs) != 1:
                raise ExportError(f"{name}: universe params {ent['up']} "
                                  f"have {len(vecs)} distinct use-site vectors")
            vec = next(iter(vecs))
            if len(vec) != len(ent["up"]):
                raise ExportError(f"{name}: use-site level arity mismatch")
            for lv in vec:
                _check_concrete_level(lv, name)
            mapping = dict(zip(ent["up"], vec))
            ty = _spec_expr(ty, mapping)
            if val is not None:
                val = _spec_expr(val, mapping)
        included[name] = {"kind": ent["kind"], "ty": ty, "val": val,
                          "ind": ent["ind"]}
        refs = _const_refs(ty)
        if val is not None:
            refs |= _const_refs(val)
        for cn, lv in refs:
            sites.setdefault(cn, set()).add(lv)
        for cn, _ in sorted(refs):
            visit(cn)
        if ent["kind"] == "ind":
            # a ctor's level params are the parent inductive's; when no value
            # references it directly (e.g. Eq.refl reached via the Eq type),
            # seed its use-site vector from the parent
            pvecs = sites.get(name, set())
            for c in ent["ind"]["ctors"]:
                if c not in sites and pvecs:
                    sites[c] = set(pvecs)
                visit(c)

    for r in roots:
        visit(r)

    # a specialized constant entered the table monomorphically: the (redundant)
    # level args on references to it are dropped so encoding/validation treat
    # it like any other monomorphic const.  TOY consts get the same treatment
    # (the toy table is monomorphic by construction; concrete instantiation
    # levels like Nat.brecOn's motive universe are stripped, param levels are
    # left for _validate to reject).
    def drop(x):
        if isinstance(x, Const) and x.levels and (
                x.name in included or x.name in TOY_NAMES):
            if all(not isinstance(l, (LParam, LMVar)) for l in x.levels):
                return Const(x.name)
        return x
    for ent in included.values():
        ent["ty"] = _rewrite(ent["ty"], drop)
        if ent["val"] is not None:
            ent["val"] = _rewrite(ent["val"], drop)

    # second pass: validate refs against the final allowed set
    allowed = TOY_NAMES | set(included)
    for name, ent in included.items():
        _validate(ent["ty"], f"{name}.type", allowed)
        if ent["val"] is not None:
            _validate(ent["val"], f"{name}.value", allowed)

    consts = list(TOY_CONSTS)
    ctors = set(TOY_CTORS)
    structs = dict(TOY_STRUCTS)
    for name in sorted(included):
        ent = included[name]
        consts.append((name, ent["ty"], ent["val"]))
        if ent["kind"] == "ctor":
            ctors.add(name)
        elif ent["kind"] == "ind" and ent["ind"]["isStruct"]:
            ind = ent["ind"]
            if ind["np"] != 0 or len(ind["ctors"]) != 1:
                raise ExportError(
                    f"{name}: structured eta needs a 0-param single-ctor "
                    f"structure (got np={ind['np']}, ctors={ind['ctors']})")
            structs[name] = (ind["ctors"][0], ind["np"], ind["nf"])
    return consts, ctors, structs


# ── WP1 metadata channel (VM_SPEC §13.7 item 1) ──────────────────────────────
#
# ``import_env`` above is the M4 *executable* slice: it prunes at TOY_NAMES,
# accepts only kind ∈ {def, ctor, ind} (Recursor is rejected), and returns the
# (consts, ctors, structs) triple with NO declaration metadata. WP1/WP3 need
# the real ConstantInfo metadata in the token stream (ENV_FORMAT §2) so the
# graph/ref-VM can read it at run time. The following functions are additive:
# they convert a dump_env closure wholesale — every ConstantInfo kind, Recursor
# included — into a constant list plus a cid-keyed ``expr.tokens.Encoder``
# const_meta. ``import_env``'s signature and return shape are unchanged.

def const_meta_entry(meta: dict, up=None) -> dict:
    """Convert one real ``dump_env`` entry's ``meta`` dict (the DUMPCONST
    metaJson, ENV_FORMAT §1) into an ``expr.tokens.Encoder`` ``const_meta``
    entry using the §2.4 field names. Every constant_info_kind is accepted:

      0 Axiom / 1 Definition / 2 Theorem / 3 Opaque / 4 Quot /
      5 Inductive / 6 Constructor / 7 Recursor

    ``up`` is the constant's ``levelParams`` list; it becomes ``lparams`` so
    the Encoder writes T_ENV_META.V0 = len(up) and a T_ENV_UNIVPARAMS chain
    (WP2, VM_SPEC §12.1). Recursor rules keep declaration order (ctor,
    nfields, rhs) and Inductive keeps ``ctors``/``all`` verbatim — both are
    load-bearing for iota (ENV_FORMAT §2.6)."""
    k = int(meta["kind"])
    o: dict = {"kind": k, "lparams": list(up or [])}
    if k == 1:                                          # Definition
        o.update(hints=meta["hints"], height=meta["height"],
                 safety=meta["safety"], is_unsafe=meta.get("isUnsafe", False),
                 all=list(meta.get("all", [])))
    elif k in (0, 2, 3):                                # Axiom/Theorem/Opaque
        o.update(is_unsafe=meta.get("isUnsafe", False),
                 all=list(meta.get("all", [])))
    elif k == 4:                                        # Quot
        o.update(quot_kind=meta["quotKind"])
    elif k == 5:                                        # Inductive
        o.update(nparams=meta["np"], nindices=meta["ni"], nnested=meta["nn"],
                 is_rec=meta["isRec"], is_unsafe=meta.get("isUnsafe", False),
                 is_reflexive=meta["isRefl"], all=list(meta.get("all", [])),
                 ctors=list(meta.get("ctors", [])))
    elif k == 6:                                        # Constructor
        o.update(induct=meta["induct"], cidx=meta["cidx"], nparams=meta["np"],
                 nfields=meta["nfields"], is_unsafe=meta.get("isUnsafe", False))
    elif k == 7:                                        # Recursor
        rules = []
        for r in meta.get("rules", []):
            rhs = r.get("rhs")
            if isinstance(rhs, dict):       # raw JSON rhs (dump_env converts)
                rhs = json_to_expr(rhs)
            rules.append({"ctor": r["ctor"], "nfields": int(r["nfields"]),
                          "rhs": rhs})
        o.update(nparams=meta["np"], nindices=meta["ni"], nmotives=meta["nm"],
                 nminors=meta["nmin"], is_k=meta["isK"],
                 is_unsafe=meta.get("isUnsafe", False),
                 all=list(meta.get("all", [])), rules=rules)
    else:
        raise ExportError(f"unknown constant_info_kind {meta.get('kind')!r}")
    return o


def const_meta_for(consts: list[tuple[str, Expr, Optional[Expr]]],
                   dump: dict[str, dict]) -> dict[int, dict]:
    """Key real-dump metadata by cid for a ``(name, type, value)`` const list
    (same order as the Encoder, so cids line up). Raises if a constant has no
    dump entry — metadata must come from the real binary, never be invented."""
    out: dict[int, dict] = {}
    for cid, (name, _, _) in enumerate(consts):
        if name not in dump:
            raise ExportError(f"{name}: missing from dump (no metadata)")
        ent = dump[name]
        out[cid] = const_meta_entry(ent["meta"], ent.get("up"))
    return out


def import_env_meta(defs: str, roots: list[str],
                    dump: dict[str, dict] | None = None
                    ) -> tuple[list, set, dict, dict[int, dict]]:
    """WP1 metadata channel: real dump → (consts, ctors, structs, const_meta).

    Unlike ``import_env`` this is metadata-complete rather than executable:
      * every constant in the dump closure is included, all 8 kinds (Recursor
        is accepted — the ``import_env`` M4 kind filter does not apply here);
      * ``consts`` carries the real (un-normalized) type/value trees, ordered
        by name so cids are deterministic and independent of TOY_CONSTS;
      * ``const_meta[cid]`` is a §2.4 ``Encoder`` entry carrying kind, lparams
        (from ``up``), flags, Inductive ``ctors``/``all`` and Recursor
        ``rules`` (ctor/nfields/rhs) straight from the real Environment.

    The dump is validated for closure over type/value/rule-rhs Const refs, so
    the returned ``consts`` can be fed directly to ``Encoder(...,
    const_meta=const_meta)``. ``import_env`` keeps its old (consts, ctors,
    structs) triple."""
    if dump is None:
        dump = dump_env(defs, roots)
    names = sorted(dump)
    consts = [(n, dump[n]["ty"], dump[n]["val"]) for n in names]
    const_meta = const_meta_for(consts, dump)
    ctors = {n for n in names if dump[n]["kind"] == "ctor"}
    structs: dict[str, tuple] = {}
    for n in names:
        ent = dump[n]
        if ent["kind"] == "ind" and ent["ind"] and ent["ind"].get("isStruct"):
            ind = ent["ind"]
            # Informational only: unlike import_env (which must satisfy the
            # graph's eta/proj gate), the metadata channel reports every real
            # structure, including parameterized ones (e.g. OfNat, np=2).
            structs[n] = (ind["ctors"][0], ind["np"], ind["nf"])
    # closure check: Encoder resolves every Const reference through b.cids, so
    # a dump that misses a referenced constant must fail loudly here.
    cid_names = set(names)
    for n in names:
        refs = _const_names(dump[n]["ty"])
        if dump[n]["val"] is not None:
            refs |= _const_names(dump[n]["val"])
        for r in (dump[n]["meta"].get("rules") or []):
            rhs = r.get("rhs")
            if isinstance(rhs, Expr):
                refs |= _const_names(rhs)
        missing = refs - cid_names
        if missing:
            raise ExportError(f"{n}: dump not closed; missing {sorted(missing)}")
    return consts, ctors, structs, const_meta
