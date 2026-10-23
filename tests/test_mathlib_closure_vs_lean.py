"""Card 012 M-C: declaration checking over REAL mathlib closures vs the live
Lean 4.33.1 kernel — accept/reject and error-class agreement per channel.

Corpus = the three M-A closure exports (scripts/export_mathlib_closure.py,
evidence dirs ~/logs/012I/closures/<name>/dump.jsonl, 16KB-16MB DUMPCONST
jsonl; regenerating them needs the mathlib checkout + lake, so the test
consumes the registered artifacts and fails loudly when they are absent —
they carry NO verdicts, only declarations; every expected verdict below is
produced by the live oracle at run time, acceptance rule 2).

Channels (card 012 M-C verifier: graph + RefVM + engine vs live lean):
  oracle   tests/mc_oracle.py — the whole closure bulk-loaded unchecked
           (addDeclWithoutChecking, the proven M-A channel), each case then
           re-added through the CHECKED Kernel.Environment.addDecl; verdict
           class = Lean.Kernel.Exception constructor name.  The oracle always
           judges against the FULL closure environment.
  graph    lean_vm InjectionEnv + StepDriver.run_check (the card-010
           declaration-injection channel with real metadata wired in via the
           encoder const_meta table).  Verdict = (accept, reject code).
  refvm    lean_vm.ref_vm RefVM.check — the frozen reference machine's
           infer-value-vs-declared-type loop with WP2 decl-lparams.
  engine   engine/vm_run `check` mode (card 013 channel) over the compiled
           sparse weights (MC_SBIN, default the current truth-table sbin).

Scale ruling (measured 2026-10-15, ~/logs/012MC/probe_engine_cost.log):
the encoded closure streams are 879 / 45,592 / 3,876,777 tokens
(Quot/Vector3/Nat).  The Python graph evaluator is O(N^2*L) per case and
structurally capped around ~25-26k tokens (VM_SPEC §19); the C++ engine
measured >1800s for a bare WHNF warmup at 45.6k tokens (super-linear, same
algorithmic class, smaller constant).  So the graph/refvm/engine legs run
against PER-CASE MINIMAL ENVIRONMENTS — the transitive closure over the
constants the case's own (type, value) trees reference — and the full-closure
environment is exercised by the engine on the Quot closure only
(`enginefull` section).  Verdicts are env-monotone for closed declarations:
a checked addDecl consults only constants the declaration names, and the
differential itself verifies the reduction empirically per row.

Case classes (generator obligations from the mc_oracle smoke, 2026-10-15:
(a) every type swap syncs `up` to the replacement type's level params, else
the kernel dies with class other/undefined-universe-level before any
interesting check; (b) replacement types reference closure-local constants
only — the oracle kernel env carries no Nat/Prelude beyond the closure):
  *_acc_*   renamed re-adds, accept class, sampled over axiom/def/thm and
            0-3 level params (kernel re-checks the real value/proof).
  *_dup_*   original-name re-adds → alreadyDeclared (code 11; graph
            bookkeeping only — engine/RefVM are name-blind, those legs skip).
  *_vm_swap value swapped for another closure constant's value →
            declTypeMismatch (code 1).
  *_tnp     theorem whose declared type is a closure-local non-Prop →
            thmTypeIsNotProp (code 8; kind gate — RefVM has none, skips).
  *_ax_data axiom with a non-Prop data type → OK (axioms carry no is_prop
            gate: the kind-gate discriminator on the accept side).
  *_uq_*    fresh unknown constant in the declared type / in the value →
            unknownConstant (code 2; every graph-side channel resolves names
            at the shared Encoder, the same translation InjectionEnv uses).
  *_lvl_*   level mutations of real closure shapes — the card-018/020/021
            canonical channel at mathlib scale.  Equivalence accepts
            (max u u / max u 0 / max 0 u ≡ u, kernel level.cpp mk_max
            rules) go through encoder normalize (card 021) on every channel;
            succ u / max u v are legitimate declTypeMismatch rejects.

Run:  OMP_NUM_THREADS=3 MC_SBIN=model/step_vm_022b_scratch.sbin \
      python3 -u tests/test_mathlib_closure_vs_lean.py
Dev:  MC_ONLY=oracle          (oracle verdicts only)
      MC_ONLY=graph,refvm     (skip engine legs)
      MC_ONLY=q_lvl_succ       (rows whose id starts with the filter)
      MC_CLOSURES=Quot_liftOn_mk   (one closure segment; the full 35 rows take
                              hours on this graph, hence the segment split)
      MC_ENGINE_TIMEOUT=1200  (per engine invocation, seconds)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder
from lean_vm.ref_vm import RefVM, VMError
from lean_vm import step_driver as sd
from lean_vm.step_driver import (
    CHECK_KIND_AXIOM, CHECK_KIND_DEFINITION, CHECK_KIND_THEOREM,
)
from lean_vm.build_vm import build_step_graph
from reference.lean_ref import json_to_expr
from reference.olean_export import import_env_meta
from tests.mc_oracle import run_mc_oracle

CLOSURES_DIR = Path(os.environ.get(
    "MC_CLOSURES_DIR", str(Path.home() / "logs" / "012I" / "closures")))
ENGINE = os.environ.get("VM_ENGINE",
                        str(Path(__file__).resolve().parents[1] / "engine"
                            / "vm_run"))
SBIN = os.environ.get(
    "MC_SBIN",
    str(Path(__file__).resolve().parents[1] / "model"
        / "step_vm_021_scratch.sbin"))
# closures whose rows also run through the engine on the FULL closure env
ENGINE_FULL = {s for s in os.environ.get("MC_ENGINE_FULL",
                                        "Quot_liftOn_mk").split(",") if s}
KIND_CODE = {"axiom": CHECK_KIND_AXIOM, "def": CHECK_KIND_DEFINITION,
             "thm": CHECK_KIND_THEOREM}
# kernel exception class -> graph reject code (decl_injection CODE_OF_CLASS
# + verify_engine_tasks G_CODE + alreadyDeclared 11, card 011 G8)
CODE_OF_CLASS = {"OK": 0, "declTypeMismatch": 1, "unknownConstant": 2,
                "thmTypeIsNotProp": 8, "alreadyDeclared": 11}


# ── closure loading ─────────────────────────────────────────────────────────
def load_raw(name: str) -> dict[str, dict]:
    p = CLOSURES_DIR / name / "dump.jsonl"
    if not p.exists():
        raise SystemExit(
            f"M-A closure artifact missing: {p}\n"
            f"(regenerate with scripts/export_mathlib_closure.py — see "
            f"docs/plans/012-mathlib-scale-closure.md M-A)")
    dump: dict[str, dict] = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("DUMPCONST "):
            d = json.loads(line[10:])
            dump[d["n"]] = d
    return dump


def to_trees(raw: dict[str, dict]) -> dict[str, dict]:
    """Raw jsonl entries -> the dump_env shape import_env_meta consumes
    (ty/val/rules-rhs parsed to expr trees)."""
    out = {}
    for n, d in raw.items():
        e = dict(d)
        e["ty"] = json_to_expr(d["ty"])
        e["val"] = (json_to_expr(d["val"]) if d["val"] is not None
                    else None)
        meta = dict(e.get("meta") or {})
        rules = meta.get("rules")
        if rules:
            meta["rules"] = [dict(r, rhs=json_to_expr(r["rhs"])
                                  if r.get("rhs") is not None else None)
                             for r in rules]
        e["meta"] = meta
        out[n] = e
    return out


# ── json level/expr mutation helpers ────────────────────────────────────────
def _jparam(n: str) -> dict:
    return {"k": 5, "n": n}


def _jzero() -> dict:
    return {"k": 1}


def _jsucc(l: dict) -> dict:
    return {"k": 2, "a": l}


def _jmax(a: dict, b: dict) -> dict:
    return {"k": 3, "a": a, "b": b}


def _mut_level(l: dict, param: str, fn) -> dict:
    k = l["k"]
    if k == 5:
        return fn(l) if l["n"] == param else l
    if k in (1, 6):
        return l
    if k == 2:
        return {"k": 2, "a": _mut_level(l["a"], param, fn)}
    if k in (3, 4):
        return {"k": k, "a": _mut_level(l["a"], param, fn),
                "b": _mut_level(l["b"], param, fn)}
    raise ValueError(f"level kind {k}")


def mut_levels(e: dict, param: str, fn) -> dict:
    """Rebuild a json expr tree replacing every LParam(param) with fn(param).
    Level positions only (Sort.l / Const.u): expr kinds 1-12 and level kinds
    1-6 share the numeric space, discriminated by the parent key."""
    k = e["k"]
    if k == 4:
        return {**e, "l": _mut_level(e["l"], param, fn)}
    if k == 5:
        return {**e, "u": [_mut_level(l, param, fn) for l in e["u"]]}
    if k == 6:
        return {**e, "f": mut_levels(e["f"], param, fn),
                "a": mut_levels(e["a"], param, fn)}
    if k in (7, 8):
        return {**e, "t": mut_levels(e["t"], param, fn),
                "b": mut_levels(e["b"], param, fn)}
    if k == 9:
        return {**e, "t": mut_levels(e["t"], param, fn),
                "v": mut_levels(e["v"], param, fn),
                "b": mut_levels(e["b"], param, fn)}
    if k in (11, 12):
        return {**e, "c": mut_levels(e["c"], param, fn)}
    return e


def _readd(src: dict, new_name: str) -> dict:
    return {**src, "n": new_name}


def _swap_val(src: dict, val_src: dict) -> dict:
    return {**src, "val": val_src["val"]}


def _swap_ty(src: dict, ty_src: dict) -> dict:
    """Type swap with `up` synced to the replacement type's level params
    (generator obligation (a))."""
    return {**src, "ty": ty_src["ty"], "up": list(ty_src["up"])}


def _set_ty_const(src: dict, const_name: str) -> dict:
    """Declared type := a bare closure-local constant (obligation (b))."""
    return {**src, "ty": {"k": 5, "n": const_name, "u": []}, "up": []}


def _jconst(n: str) -> dict:
    return {"k": 5, "n": n, "u": []}


# ── case rows ────────────────────────────────────────────────────────────────
# Row = (cid, closure, case-json, env_extra, is_dup).  env_extra seeds the
# minimal env with names the row must SEE (dup rows: their own name, so the
# InjectionEnv bookkeeping and the kernel's check_name both fire); is_dup
# gates the name-blind channels (RefVM, engine) to their documented boundary.
# The expected class is INTENTIONALLY absent: the live oracle decides.
def build_cases() -> list[tuple[str, str, dict, tuple, bool]]:
    cases: list[tuple[str, str, dict, tuple, bool]] = []
    add = cases.append

    # ── Quot_liftOn_mk (8 consts): full-env feasible on every channel ──
    Q = "Quot_liftOn_mk"
    q = load_raw(Q)
    add(("q_acc_def", Q, _readd(q["Quot.liftOn"], "Quot.liftOn.mc"), (), False))
    add(("q_acc_thm", Q, _readd(q["Quot.liftOn_mk"], "Quot.liftOn_mk.mc"), (), False))
    add(("q_acc_rfl", Q, _readd(q["rfl"], "rfl.mc"), (), False))
    add(("q_dup_def", Q, dict(q["Quot.liftOn"]), ("Quot.liftOn",), True))
    add(("q_dup_thm", Q, dict(q["Quot.liftOn_mk"]), ("Quot.liftOn_mk",), True))
    # name check fires before type checking (K/environment.cpp:128):
    # a duplicate name with a mismatched value is still alreadyDeclared.
    add(("q_dup_order", Q, _swap_val(dict(q["Quot.liftOn"]), q["rfl"]),
         ("Quot.liftOn",), True))
    add(("q_vm_swap", Q, _swap_val(_readd(q["Quot.liftOn"],
                                          "Quot.liftOn.vm"), q["rfl"]), (), False))
    # Quot.lift's type ends in {β : Sort v} -> not a Prop for free v.
    add(("q_tnp", Q, _swap_ty(_readd(q["Quot.liftOn_mk"],
                                     "Quot.liftOn_mk.tnp"), q["Quot.lift"]),
         (), False))
    uq = _readd(q["rfl"], "rfl.uqty")
    add(("q_uq_ty", Q, {**uq, "ty": _jconst("MC.Missing.qTy")}, (), False))
    add(("q_uq_val", Q, {**_readd(q["rfl"], "rfl.uqval"),
                         "val": _jconst("MC.Missing.qVal")}, (), False))
    rfl_mc = _readd(q["rfl"], "rfl.lvl")
    add(("q_lvl_maxuu", Q,
         {**rfl_mc, "ty": mut_levels(rfl_mc["ty"], "u",
                                     lambda l: _jmax(l, l))}, (), False))
    add(("q_lvl_maxu0", Q,
         {**rfl_mc, "ty": mut_levels(rfl_mc["ty"], "u",
                                     lambda l: _jmax(l, _jzero()))}, (), False))
    add(("q_lvl_max0u", Q,
         {**rfl_mc, "ty": mut_levels(rfl_mc["ty"], "u",
                                     lambda l: _jmax(_jzero(), l))}, (), False))
    add(("q_lvl_succ", Q,
         {**rfl_mc, "ty": mut_levels(rfl_mc["ty"], "u", _jsucc)}, (), False))
    add(("q_lvl_maxv", Q,
         {**rfl_mc, "ty": mut_levels(rfl_mc["ty"], "u",
                                     lambda l: _jmax(l, _jparam("v"))),
          "up": ["u", "v"]}, (), False))
    lift_mc = _readd(q["Quot.liftOn"], "Quot.liftOn.lvl")
    add(("q_lvl_maxuu_2p", Q,
         {**lift_mc, "ty": mut_levels(lift_mc["ty"], "u",
                                      lambda l: _jmax(l, l))}, (), False))

    # ── Vector3_cons_fz (87 consts): graph/refvm/engine on minimal envs ──
    V = "Vector3_cons_fz"
    v = load_raw(V)
    add(("v_acc_axm", V, _readd(v["propext"], "propext.mc"), (), False))
    add(("v_acc_thm", V, _readd(v["trivial"], "trivial.mc"), (), False))
    add(("v_acc_def", V, _readd(v["id"], "id.mc"), (), False))
    add(("v_acc_natadd", V, _readd(v["Nat.add"], "Nat.add.mc"), (), False))
    add(("v_dup_natadd", V, dict(v["Nat.add"]), ("Nat.add",), True))
    add(("v_tnp", V, _set_ty_const(_readd(v["trivial"], "trivial.tnp"),
                                    "Nat"), (), False))
    # axioms accept data (no is_prop gate) — the kind-gate discriminator.
    add(("v_ax_data", V, _set_ty_const(_readd(v["propext"], "propext.data"),
                                       "Nat"), (), False))
    add(("v_uq_ty", V, {**_readd(v["id"], "id.uqty"),
                        "ty": _jconst("MC.Missing.vTy")}, (), False))
    add(("v_vm_swap", V, _swap_val(_readd(v["id"], "id.vm"), v["Nat.add"]), (), False))
    id_mc = _readd(v["id"], "id.lvl")
    add(("v_lvl_maxuu", V,
         {**id_mc, "ty": mut_levels(id_mc["ty"], "u",
                                    lambda l: _jmax(l, l))}, (), False))
    add(("v_lvl_succ", V,
         {**id_mc, "ty": mut_levels(id_mc["ty"], "u", _jsucc)}, (), False))

    # ── Nat_testBit_land (779 consts): leaf rows, minimal envs ──
    N = "Nat_testBit_land"
    n = load_raw(N)
    add(("n_acc_def_id", N, _readd(n["id"], "id.mc"), (), False))
    add(("n_acc_thm", N, _readd(n["And.left"], "And.left.mc"), (), False))
    add(("n_acc_fcomp", N, _readd(n["Function.comp"], "Function.comp.mc"), (), False))
    add(("n_dup_id", N, dict(n["id"]), ("id",), True))
    nid = _readd(n["id"], "id.lvl")
    add(("n_lvl_maxuu", N,
         {**nid, "ty": mut_levels(nid["ty"], "u",
                                  lambda l: _jmax(l, l))}, (), False))
    add(("n_lvl_succ", N, {**nid, "ty": mut_levels(nid["ty"], "u", _jsucc)}, (), False))
    add(("n_uq_ty", N, {**_readd(n["id"], "id.uqty"),
                        "ty": _jconst("MC.Missing.nTy")}, (), False))
    add(("n_tnp", N, _set_ty_const(_readd(n["And.left"], "And.left.tnp"),
                                   "Nat"), (), False))
    return cases


# ── XPASS protocol ──────────────────────────────────────────────────────────
# A registered row/leg pair is expected to DISAGREE with the live oracle: if it
# agrees instead the suite reports XPASS and fails, because a stale entry would
# absorb a future regression on that leg without a sound.  An unregistered
# divergence is a plain FAIL.  The register is EMPTY — every group that once
# lived here (binder-identity bvar defeq, universe-polymorphic lam-valued defs,
# the thm kind gate on parameterised Pi sorts, MData / Nat.add) now agrees on
# all three channels, and each fix is pinned by permanent rows in the
# decl-injection and level suites instead of by a gap entry.
KNOWN_GAPS: dict[str, tuple[str, frozenset]] = {}


def _gaps() -> dict[str, tuple[str, frozenset]]:
    """Registered divergences: cid -> (reason, legs).

    The legs matter: a group can diverge on graph+engine while the RefVM leg
    agrees, and that agreement is the expected state, not an XPASS.  Register
    a row only with its root cause, and only for the legs that actually
    diverge; a channel that structurally cannot express the row is a printed
    `channel boundary`, never a register entry (a boundary that starts judging
    is a real signal, not bookkeeping).
    """
    return {}


KNOWN_GAPS.update(_gaps())


# ── per-case minimal environment ────────────────────────────────────────────
def _json_refs(node, acc: set) -> None:
    if isinstance(node, dict):
        if node.get("k") == 5 and "u" in node and "n" in node:
            acc.add(node["n"])
        for x in node.values():
            _json_refs(x, acc)
    elif isinstance(node, (list, tuple)):
        for x in node:
            _json_refs(x, acc)


def case_env(raw: dict[str, dict], case: dict, extra: tuple) -> dict[str, dict]:
    """Transitive closure over ty/val/rules-rhs Const references of the case,
    plus the explicit `extra` names (dup rows must SEE their own name), plus
    every included inductive's ctors: the kernel's full-closure env carries
    them (an ind and its ctors are one declaration unit), and the RefVM
    structures channel resolves structure ctors through the bundle (its
    __init__ would KeyError on an ind whose ctor is absent)."""
    seeds: set[str] = set()
    _json_refs(case["ty"], seeds)
    if case["val"] is not None:
        _json_refs(case["val"], seeds)
    names: set[str] = set()
    frontier = list(seeds) + list(extra)
    while frontier:
        nm = frontier.pop()
        if nm in names or nm not in raw:
            continue
        names.add(nm)
        ent = raw[nm]
        acc: set[str] = set()
        _json_refs(ent["ty"], acc)
        if ent["val"] is not None:
            _json_refs(ent["val"], acc)
        for r in (ent["meta"] or {}).get("rules") or []:
            _json_refs(r.get("rhs"), acc)
        for cn in (ent["meta"] or {}).get("ctors") or []:
            if cn in raw and cn not in names:
                frontier.append(cn)
        frontier.extend(acc - names)
    return {nm: raw[nm] for nm in names}


# ── legs ─────────────────────────────────────────────────────────────────────
def graph_leg(case: dict, raw: dict[str, dict], extra: tuple
              ) -> tuple[bool, int, str]:
    """InjectionEnv + run_check against the per-case minimal env."""
    env = case_env(raw, case, extra)
    consts, ctors, _structs, meta = import_env_meta("", [], dump=to_trees(env))
    inj = sd.InjectionEnv(consts, ctors, build_step_graph)
    inj._meta.update(meta)   # real ConstantInfo metadata for the base env
    ty = json_to_expr(case["ty"])
    val = (json_to_expr(case["val"]) if case["val"] is not None else None)
    lps = list(case["up"]) or None
    try:
        if case["kind"] == "axiom":
            inj.add_axiom(case["n"], ty, lparams=lps)
        elif case["kind"] == "def":
            inj.add_definition(case["n"], ty, val, lparams=lps)
        else:
            inj.add_theorem(case["n"], ty, val, lparams=lps)
        return True, 0, f"{inj.steps_last} steps"
    except VMError as ex:
        return False, ex.code, f"{inj.steps_last} steps"
    except TimeoutError:
        return False, -1, "steps-budget exhausted"


def refvm_leg(case: dict, raw: dict[str, dict], is_dup: bool):
    """RefVM.check (frozen machine): infer(value) defeq declared type, with
    WP2 decl-lparams.  None on channel boundaries (printed, never silent):
    name-blind (alreadyDeclared rows — no name space), axiom rows (check()
    models infer(value); there is no no-value shape), ERR_UNSUPPORTED
    (outside the frozen infer subset), thm rows whose oracle class is the
    kind gate (RefVM predates card 010 and has none — judged by the caller
    from the live oracle class, not hardcoded per row)."""
    if case["kind"] == "axiom":
        return None
    env = case_env(raw, case, ())
    consts, ctors, structs, meta = import_env_meta("", [], dump=to_trees(env))
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    try:
        tp = enc.encode_term(json_to_expr(case["ty"]))
        vp = enc.encode_term(json_to_expr(case["val"]))
    except KeyError as ex:
        return False, 2, f"encode-time unknown constant {ex.args[0]!r}"
    rv = RefVM(enc.b, structures=structs)
    try:
        rv.check([(tp, vp, [str(x) for x in case["up"]])])
        return True, 0, ""
    except VMError as ex:
        if ex.code == 4:      # ERR_UNSUPPORTED: outside the frozen infer subset
            return None
        return False, ex.code, ""


def _engine_run(stream, tp, vp, kind, max_steps=50000, timeout=None):
    # The window is a budget, never a judgement: the engine's accept rows run
    # the whole check and are legitimately slow on this graph — q_acc_thm
    # measured 824.1s (minimal env) / 901.1s (full closure) to reach DONE on
    # the 022b sbin (~/logs/022B3/b7_engine_qaccthm{,_full}_probe.log), so the
    # old 600s window reported TIMEOUT where the engine does have a verdict.
    # MC_ENGINE_TIMEOUT overrides; a genuinely non-terminating row still lands
    # on the -1 bucket through this same window.
    if timeout is None:
        timeout = int(os.environ.get("MC_ENGINE_TIMEOUT", "1200"))
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write("%d\n" % len(stream))
    for t in stream:
        f.write(" ".join(str(int(x))
                        for x in tuple(t) + (0,) * (7 - len(t))) + "\n")
    f.close()
    args = [ENGINE, SBIN, f.name, str(vp), "check", str(max_steps),
            "1", str(tp), str(vp), str(kind)]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, OMP_NUM_THREADS="3"))
    except subprocess.TimeoutExpired:
        os.unlink(f.name)
        return None, "TIMEOUT"
    os.unlink(f.name)
    if p.returncode != 0:
        return None, p.stderr[-200:]
    lines = p.stdout.strip().splitlines()
    return lines[-1].split(), ""


def engine_leg(case: dict, env_trees: dict, is_dup: bool):
    """vm_run check channel.  None on the name-blind boundary: the channel
    carries (type, value, kind) triples, no names."""
    if is_dup:
        return None
    consts, ctors, _structs, meta = import_env_meta("", [], dump=env_trees)
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    try:
        tp = enc.encode_term(json_to_expr(case["ty"]))
        vp = (enc.encode_term(json_to_expr(case["val"]))
              if case["val"] is not None else 0)
    except KeyError as ex:
        return False, 2, f"encode-time unknown constant {ex.args[0]!r}"
    ver, err = _engine_run(list(enc.b.stream), tp, vp, KIND_CODE[case["kind"]])
    if err:
        return False, -1, err
    if ver[0] == "DONE":
        return True, 0, f"{ver[-1]} steps"
    if ver[0] == "REJECT":
        return False, int(ver[1]), f"{ver[-1]} steps"
    return False, -1, f"NOT_DONE {ver[-1]} steps"


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    t0 = time.perf_counter()
    only = {s.strip() for s in os.environ.get("MC_ONLY", "").split(",")
            if s.strip()}
    want_closures = {s.strip() for s in
                     os.environ.get("MC_CLOSURES", "").split(",") if s.strip()}
    sections = {s for s in only if s in
                ("oracle", "graph", "refvm", "engine", "enginefull")}
    row_filter = {s for s in only if s not in sections}
    run_all = not only
    all_cases = build_cases()
    if want_closures:
        all_cases = [c for c in all_cases if c[1] in want_closures]
    if row_filter:
        all_cases = [c for c in all_cases
                     if any(c[0].startswith(f) for f in row_filter)]
    closures = sorted({c[1] for c in all_cases})
    print(f"MC sbin: {SBIN}")
    print(f"MC closures: {closures}  ({len(all_cases)} cases)")

    # oracle leg: one live lean run per closure (expectations NEVER pinned)
    oracle: dict[str, str] = {}
    if run_all or "oracle" in sections or not sections:
        for cl in closures:
            cl_cases = [c for c in all_cases if c[1] == cl]
            path = Path(f"/tmp/mc_cases_{cl}_{os.getpid()}.txt")
            path.write_text("\n".join(
                f"MCCASE {cid} " + json.dumps(
                    {k: c2[k] for k in ("n", "up", "ty", "val", "meta",
                                        "kind")},
                    separators=(",", ":"))
                for cid, _cl, c2, _x, _d in cl_cases) + "\n")
            t1 = time.perf_counter()
            verd = run_mc_oracle(CLOSURES_DIR / cl / "dump.jsonl", path,
                                 Path(f"/tmp/mc_out_{cl}_{os.getpid()}.jsonl"))
            print(f"  oracle[{cl}]: {len(verd)} verdicts, "
                  f"{time.perf_counter() - t1:.0f}s")
            for cid, cls in verd.items():
                print(f"    oracle[{cid}] = {cls}")
            oracle.update(verd)

    fails: list[str] = []
    raws: dict[str, dict[str, dict]] = {cl: load_raw(cl) for cl in closures}
    stats: dict[str, list[int]] = {k: [0, 0, 0] for k in
                                   ("graph", "refvm", "engine", "enginefull")}
    want_sections = (sections if sections else
                     {"graph", "refvm", "engine", "enginefull"} | sections)
    if run_all:
        want_sections = {"graph", "refvm", "engine", "enginefull"}

    def judge(leg, cid, want_cls, got, note=""):
        agree_n, diverge_n, boundary_n = stats[leg]
        want = CODE_OF_CLASS.get(want_cls, -1)
        if got is None:
            stats[leg][2] += 1
            print(f"  [--] {leg:11s} {cid}: channel boundary ({note})")
            return
        acc, code = got[0], got[1]
        agree = (acc, code) == (want == 0, want)
        entry = KNOWN_GAPS.get(cid)
        gap = entry[0] if entry and leg in entry[1] else None
        if agree and gap:
            tag = "XPASS"
            fails.append(f"[{leg} {cid}] XPASS: remove the KNOWN_GAPS entry")
        elif agree:
            tag = "PASS"
        elif gap:
            tag = "XFAIL-KNOWN-GAP"
        else:
            tag = "FAIL"
            fails.append(f"[{leg} {cid}] oracle={want_cls} (code {want}) "
                         f"got accept={acc} code={code} {note}")
        stats[leg][0] += int(agree)
        if not agree:
            stats[leg][1] += 1
        print(f"  [{tag}] {leg:11s} {cid}: oracle={want_cls} "
              f"got accept={acc} code={code} {note}".rstrip())

    for cid, cl, case, extra, is_dup in all_cases:
        cls = oracle.get(cid)
        if cls is None:
            fails.append(f"[{cid}] no oracle verdict (lean emitted nothing)")
            continue
        base_cls = cls.split(" ", 1)[0].split(":", 1)[0]
        if base_cls not in CODE_OF_CLASS:
            fails.append(f"[{cid}] oracle class {cls!r} outside the mapped "
                         f"set — generator obligation breached (a)/(b)?")
            continue
        print(f"  {cid} [{cl}] {case['n']} kind={case['kind']} up={case['up']}")
        if "graph" in want_sections:
            judge("graph", cid, base_cls, graph_leg(case, raws[cl], extra))
        if "refvm" in want_sections:
            if is_dup:
                judge("refvm", cid, base_cls, None,
                      "name-blind — no name space in the channel")
            elif base_cls == "thmTypeIsNotProp":
                judge("refvm", cid, base_cls, None,
                      "no kind gate — frozen machine predates card 010")
            else:
                judge("refvm", cid, base_cls, refvm_leg(case, raws[cl], is_dup))
        if "engine" in want_sections:
            env = case_env(raws[cl], case, extra)
            judge("engine", cid, base_cls,
                  engine_leg(case, to_trees(env), is_dup),
                  "name-blind — no names in the (type, value, kind) triple"
                  if is_dup else "")
        if "enginefull" in want_sections and cl in ENGINE_FULL:
            judge("enginefull", cid, base_cls,
                  engine_leg(case, to_trees(raws[cl]), is_dup),
                  "name-blind" if is_dup else "full closure env")

    print("\n=== card 012 M-C mathlib-closure differential: "
          f"{len(all_cases)} cases, "
          + ", ".join(f"{k}: {v[0]} agree/{v[1]} diverge/{v[2]} boundary"
                      for k, v in stats.items()
                      if v[0] + v[1] + v[2]) + " ===")
    for f in fails:
        print(f"  FAIL {f}")
    ok = not fails
    print(f"[{'OK' if ok else 'FAILED'}] wall {time.perf_counter() - t0:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
