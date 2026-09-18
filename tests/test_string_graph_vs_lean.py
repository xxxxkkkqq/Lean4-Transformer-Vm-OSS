"""WP5 (E-group): string literals in the ALM step graph vs the real Lean
4.33.1 binary (the acceptance oracle).

Authority (read-only, 4.35 master kernel):
  * ``string_lit_to_constructor`` — K/inductive.cpp:1368-1380: the expansion is
    ``App(Const("String.ofList"), cons(Char.ofNat cp, ... nil))`` with the
    globals fixed at :1382-1400 (``g_string_mk = Const "String.ofList"``, no
    level args; ``g_list_cons_char``/``g_list_nil_char`` = ``List.cons.{0} Char``
    / ``List.nil.{0} Char`` partial apps; ``g_char_of_nat = Const "Char.ofNat"``).
  * ``try_string_lit_expansion`` — K/type_checker.cpp:1145-1156 (arm fires only
    against a literal ``App(Const("String.ofList"), _)`` head; matched arm is
    FINAL).
  * ``infer`` String branch — K/type_checker.cpp:315-321 (``lit_kind == 1`` →
    ``Const("String")``; the Nat size-limit half is WP6, not here).
  * ``reduce_proj_core`` — K/type_checker.cpp:420-442 (string-lit major is
    converted + whnf'd before field extraction).
  * ``whnf_core`` Lit case — a bare literal returns itself (:468-540).
  * lenient UTF-8 decode — K/util/utf8.cpp:148-221.

What is verified
----------------
A  E1 encoding invariants (expr/tokens.py): byte-chain roundtrip incl. empty /
   non-ASCII / raw-NUL bytes; the X expansion tree matches the kernel grammar
   (inductive.cpp:1368-1380) node for node; the lenient decoder agrees with the
   utf8.cpp:148-221 branch table on malformed input; name-keyed ENV_HDR.X tags
   (String.ofList=18, String=19) land inside the graph's 96-const scan window;
   an env without the five expansion names declines the shadow tree (X=0).
B  differential corpus vs real lean: INFER "ab" : String (E4); WHNF "ab" stuck;
   String.rec / String.casesOn on a literal (E2 — kernel converts the major to
   the ``String.ofList`` expansion, unfolds it to the ``String.ofByteArray``
   ctor and fires the iota rule); Proj on a literal (E5) — 4.33.1 has no user
   syntax for a raw ``.proj`` node (``x#i`` rejects), so these cases drive
   ``Lean.mkProj`` from an oracle ``run_cmd``; ``Meta.whnf`` is
   ``@[extern "lean_whnf"]`` (Lean/Meta/Basic.lean:779), i.e. the real kernel
   whnf, so proj-on-lit exercises reduce_proj_core directly: field 1 of
   ``"ab"`` whnfs to the stuck ``String.ofList._proof_1`` application (theorem
   values stay stuck under lean_whnf — probe 2026-09-13 — which is why the env
   value-prunes kind=2 constants), field 1 of ``""`` to the stuck
   ``_proof_1 ∘ @List.nil Char``, and the accessor app ``"ab".isValidUTF8``
   returns itself unchanged.  Field 0 is NOT WHNF-tested: lean_whnf unfolds
   ``List.utf8Encode`` all the way to ``ByteArray.mk (Array.push …)`` (needs
   the whole Array/UInt8 closure); proj-0 pairs are tested through DEFEQ where
   both sides keep the same stuck head and only the verdict is comparable.
   DEFEQ lit-vs-lit through the
   byte-chain dispatch (E3a: identical → True, differing byte → False,
   differing length → False, raw-NUL padding traps); DEFEQ lit vs
   ``String.ofList ['a','b']`` (E3b/eta-struct → E4 infer → E5 fieldwise — with
   the real ``String.ofList`` def present the kernel ``lazy_delta`` unfolds it
   first, so the literal ``try_string_lit_expansion`` arm is effectively dead
   and the verdict flows through eta-struct, which is what the graph follows).
C  graph-only: with ``String.ofList`` value-pruned (the only setting in which
   the kernel's ``try_string_lit_expansion`` arm can fire — matched arm FINAL,
   type_checker.cpp:1147-1150), ``"ab" =?= String.ofList ['a','b']`` is True
   via the es_str conversion and ``"ab" =?= String.ofList ['a']`` False.

Run: setsid nohup env OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u \
       tests/test_string_graph_vs_lean.py > /tmp/string_graph.log 2>&1 < /dev/null &
"""
from __future__ import annotations

import sys
import os
import json
import time
import pickle
import traceback
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import (
    App, Const, Lam, LitNat, LitStr, BVar, Sort, Proj, LZero, LSucc,
    BI_DEFAULT,
)
from expr.tokens import (
    Encoder, decode_expr, decode_closure, utf8_codepoints, string_expansion,
    STR_ID_CODES, STRING_EXPAND_NAMES, LIT_STR,
)
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference import lean_ref
from reference.olean_export import dump_env, const_meta_for
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_LEAN_DEFS

# ── real-lean closure roots for the string environment ──────────────────────
ROOTS = [
    "String", "String.ofList", "String.ofByteArray", "String.ofList._proof_1",
    "ByteArray", "ByteArray.IsValidUTF8", "ByteArray.IsValidUTF8.intro",
    "String.rec", "String.casesOn", "String.isValidUTF8", "String.toByteArray",
    "List", "List.cons", "List.nil", "List.utf8Encode",
    "Char", "Char.ofNat", "Nat", "Bool", "Eq", "Eq.refl", "rfl",
]
# kind=1 constants whose real values the graph must carry: lean_whnf unfolds
# defs but leaves theorem (kind=2) applications stuck — probed on 4.33.1 via
# run_cmd/Meta.whnf — so every other closure name is type-only (value pruned;
# the kernel never head-reduces them on these cases, see module docstring).
KEEP_VAL = {"String.ofList", "String.casesOn"}

# Names that must land inside the graph's 96-constant cid-scan window.
# (Nat/Bool come from TOY_CONSTS — do not duplicate them.)
FRONT = [
    "String", "String.ofList", "String.ofByteArray", "String.ofList._proof_1",
    "ByteArray.IsValidUTF8", "ByteArray.IsValidUTF8.intro", "List.utf8Encode",
    "String.rec", "String.casesOn", "String.isValidUTF8", "String.toByteArray",
    "List", "List.cons", "List.nil",
    "Char", "Char.ofNat", "ByteArray", "Eq", "Eq.refl", "rfl",
]

# Micro-step budget for this suite (ADR docs/decisions/003, backedfill 2026-09-13).
# The kernel's is_def_eq_core recursion has NO step budget (scope_rec_depth
# default 0 = unlimited, src/runtime/interrupt.h:45-48), so this cap must not
# reject any converging graph computation: a string literal of n codepoints
# expands to an n-deep ofList/cons spine, and the E3b arm re-enters the
# stuck chain per cons level (~330 micro-steps/level measured: len 1/2/3/4
# = 380/710/1124/1622 steps).  This suite's real halts: B 670-2451, C 628-710,
# well under the cap; 6000 matches the repo's largest precedent
# (test_stepgraph_infer_defeq) and keeps the corpus honest about its cost.
GRAPH_MAX_STEPS = 6000

# Dev-loop hooks (no effect when unset — the acceptance run is unfiltered):
#   WP5_ONLY=id1,id2   run only these B/C case ids (oracle batch still runs
#                      every entry, so lean expectations stay live)
#   WP5_TB=1           print the full traceback when a graph run raises
_ONLY = {s for s in os.environ.get("WP5_ONLY", "").split(",") if s}
_TB = bool(os.environ.get("WP5_TB"))


def _run_one(fn):
    """Execute one graph case; on exception, optionally dump the traceback
    and return "<ExcType>: <msg>" as the value (same contract as before)."""
    try:
        return fn()
    except Exception as ex:                       # noqa: BLE001
        if _TB:
            traceback.print_exc()
        return f"{type(ex).__name__}: {ex}", -1


def _A(f, *xs):
    for x in xs:
        f = App(f, x)
    return f


def _canon(e):
    """Semantic comparison form (same normalization as the quot test):
    strip Const universe levels and binder names — both sides lose them
    identically through decode/oracle serialization."""
    from expr.model import Let, Pi, MData
    if isinstance(e, MData):
        return _canon(e.child)
    if isinstance(e, App):
        return App(_canon(e.fn), _canon(e.arg))
    if isinstance(e, (Lam, Pi)):
        return type(e)("", e.binfo, _canon(e.domain), _canon(e.body))
    if isinstance(e, Let):
        return Let("", _canon(e.domain), _canon(e.value), _canon(e.body),
                   e.nondep)
    if isinstance(e, Proj):
        return Proj(e.sname, e.idx, _canon(e.child))
    if isinstance(e, Const):
        return Const(e.name, ())
    return e


def _cached_dump(path, defs, roots):
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    d = dump_env(defs, roots)
    pickle.dump(d, open(path, "wb"))
    return d


def build_env(keep_val=KEEP_VAL):
    toy_names = [n for n, _, _ in TOY_CONSTS]
    toy_dump = _cached_dump("/tmp/wp5_toy_dump.pkl",
                            TOY_LEAN_DEFS, sorted(toy_names))
    str_dump = _cached_dump("/tmp/wp5_string_dump.pkl", "", ROOTS)
    merged = dict(toy_dump)
    merged.update(str_dump)
    missing = [n for n in ROOTS if n not in merged]
    if missing:
        raise SystemExit(f"closure missing roots: {missing}")
    ordered = [n for n in FRONT if n in merged]
    consts = list(TOY_CONSTS) + [
        (n, merged[n]["ty"],
         merged[n]["val"] if n in keep_val else None)
        for n in ordered]
    meta = const_meta_for(consts, merged)
    ctors = {n: True for n in ordered if merged[n]["meta"]["kind"] == 6}
    ctors.update({n: True for n, _, _ in TOY_CONSTS if n in TOY_CTORS})
    return consts, ctors, meta, ordered


# ── graph-side terms ---------------------------------------------------------
STR = Const("String")
BOOL_SORT = Sort(LSucc(LZero()))                  # Type == Sort 1
TRUE_TY = Const("Bool")


def char_list(s: str):
    """The kernel expansion list: Char.ofNat-per-codepoint, utf8.cpp order."""
    tail = App(Const("List.nil", (LZero(),)), Const("Char"))
    for cp in reversed(utf8_codepoints(s.encode("utf-8"))):
        tail = _A(Const("List.cons", (LZero(),)), Const("Char"),
                  App(Const("Char.ofNat"), LitNat(cp)), tail)
    return tail


def of_list(s: str):
    return App(Const("String.ofList"), char_list(s))


# @String.rec.{1} — {motive : String → Sort u} → minor → (t : String)
# (real signature #check'd on 4.33.1: motive := fun _ => Type, minor
# fun b h => Bool, result Bool).
BOOL_TY = Const("Bool")
MOTIVE = Lam("m", BI_DEFAULT, STR, BOOL_SORT)             # fun _ => Sort 1
CASE_BYTES = App(Const("ByteArray.IsValidUTF8"), BVar(0))  # IsValidUTF8 b
REC_CASE = Lam("b", BI_DEFAULT, Const("ByteArray"),
               Lam("h", BI_DEFAULT, CASE_BYTES, BOOL_TY))   # ... => Bool
REC_TRUE = _A(Const("String.rec", (LSucc(LZero()),)), MOTIVE, REC_CASE)
# String.casesOn explicit order: motive, t, minor (see #check above)
CASES_TRUE = _A(Const("String.casesOn", (LSucc(LZero()),)), MOTIVE,
                LitStr("ab"), REC_CASE)

lit_ab = LitStr("ab")
lit_ba = LitStr("ba")
lit_empty = LitStr("")
lit_a = LitStr("a")
lit_forall = LitStr("∀")
lit_exists = LitStr("∃")
lit_emoji = LitStr("😀")
lit_nul = LitStr("\x00")
lit_nulnul = LitStr("\x00\x00")

# (id, kind, src_a, src_b, expr_a, expr_b)
CASES = [
    # E4 (infer): string literal infers to String (type_checker.cpp:315-321)
    ("infer_lit", "INFER", '"ab"', None, lit_ab, None),
    ("infer_empty", "INFER", '""', None, lit_empty, None),
    ("infer_uni", "INFER", '"∀"', None, lit_forall, None),
    # whnf_core: a bare literal is its own whnf (type_checker.cpp:468-540)
    ("whnf_bare", "WHNF", '"ab"', None, lit_ab, None),
    ("whnf_uni", "WHNF", '"∀x😀"', None, LitStr("∀x😀"), None),
    # E2 (inductive_reduce_rec string major): recursor on the literal converts
    # to the ofList expansion, unfolds to the ofByteArray ctor, iota fires and
    # discards the (stuck) field args (inductive.cpp + type_checker.cpp:468-540)
    ("rec_on_lit", "WHNF",
     'String.rec (motive := fun _ => Type) (fun _ _ => Bool) "ab"', None,
     App(REC_TRUE, lit_ab), None),
    ("casesOn_on_lit", "WHNF",
     'String.casesOn (motive := fun _ => Type) "ab" (fun _ _ => Bool)', None,
     CASES_TRUE, None),
    # E2 stuck (no literal involved: under-applied recursor must stay stuck)
    ("rec_partial_stuck", "WHNF",
     'String.rec (motive := fun _ => Type) (fun _ _ => Bool)', None,
     REC_TRUE, None),
    # E5 via the accessor function (kind=2 theorem — lean_whnf never unfolds
    # theorem values): the app is its own whnf on BOTH layers (kernel and
    # graph: value-pruned head, no delta arm).  Raw .proj nodes on a literal
    # are in PROJ_CASES below (no user syntax for them in 4.33.1).
    ("proj_isValidUTF8_whnf", "WHNF", '"ab".isValidUTF8', None,
     App(Const("String.isValidUTF8"), lit_ab), None),
    # E3a: byte-chain dispatch of lit-vs-lit pairs
    ("deq_same", "DEFEQ", '"ab"', '"ab"', lit_ab, LitStr("ab")),
    ("deq_diff", "DEFEQ", '"ab"', '"ba"', lit_ab, lit_ba),
    ("deq_len", "DEFEQ", '"ab"', '"abc"', lit_ab, LitStr("abc")),
    ("deq_empty", "DEFEQ", '""', '""', lit_empty, LitStr("")),
    ("deq_empty_vs_a", "DEFEQ", '""', '"a"', lit_empty, lit_a),
    ("deq_uni", "DEFEQ", '"∀"', '"∀"', lit_forall, LitStr("∀")),
    ("deq_uni_diff", "DEFEQ", '"∀"', '"∃"', lit_forall, lit_exists),
    ("deq_emoji", "DEFEQ", '"😀"', '"😀"', lit_emoji, LitStr("😀")),
    ("deq_emoji_vs_uni", "DEFEQ", '"😀"', '"∀"', lit_emoji, lit_forall),
    ("deq_nul_pad", "DEFEQ", r'"\x00"', '"a"', lit_nul, lit_a),
    ("deq_nul2_pad", "DEFEQ", r'"\x00\x00"', '"aa"', lit_nulnul,
     LitStr("aa")),
    ("deq_mixed", "DEFEQ", '"a∀"', '"∀a"', LitStr("a∀"), LitStr("∀a")),
    # E3b in a real env: ofList has a value → lazy_delta unfolds it → eta-struct
    # (infer "ab" : String, fieldwise Proj through E5) decides the pair.
    ("deq_oflist_true", "DEFEQ", '"ab"', "String.ofList ['a', 'b']",
     lit_ab, of_list("ab")),
    ("deq_oflist_false", "DEFEQ", '"ab"', "String.ofList ['a']",
     lit_ab, of_list("a")),
    ("deq_oflist_swap", "DEFEQ", '"ab"', "String.ofList ['b', 'a']",
     lit_ab, of_list("ba")),
    # E5 via DEFEQ: field0 extraction on both sides (utf8Encode stays a stuck
    # head in the graph — pruned value — where the kernel keeps unfolding; the
    # pair-compare then walks identical spines, so the VERDICT agrees).
    ("deq_proj_refl", "DEFEQ", '"ab".toByteArray', '"ab".toByteArray',
     Proj("String", 0, lit_ab), Proj("String", 0, lit_ab)),
    ("deq_proj_vs_oflist_true", "DEFEQ",
     '"ab".toByteArray', "(String.ofList ['a', 'b']).toByteArray",
     Proj("String", 0, lit_ab), Proj("String", 0, of_list("ab"))),
    ("deq_proj_vs_diff_false", "DEFEQ", '"ab".toByteArray',
     '"ba".toByteArray', Proj("String", 0, lit_ab), Proj("String", 0, lit_ba)),
]

# Raw ``.proj`` nodes on string literals (E5 — reduce_proj_core,
# type_checker.cpp:420-442: convert the major to the ofList expansion, unfold
# to the ofByteArray ctor, extract the field).  4.33.1 has no ``x#i`` user
# syntax, so the oracle drives ``Lean.mkProj`` from a run_cmd; ``Meta.whnf``
# is ``@[extern "lean_whnf"]`` (Lean/Meta/Basic.lean:779) — the kernel whnf
# itself — so the oracle here IS the kernel proj path.  Field 0 is excluded:
# lean_whnf fully unfolds List.utf8Encode to ``ByteArray.mk (Array.push …)``,
# which needs the whole Array/UInt8 closure (proj-0 pairs are DEFEQ-tested
# above, where both sides keep the stuck head).
PROJ_CASES = [
    ("proj1_ab_whnf", 1, "ab", Proj("String", 1, lit_ab)),
    ("proj1_empty_whnf", 1, "", Proj("String", 1, lit_empty)),
    ("proj1_uni_whnf", 1, "∀x😀", Proj("String", 1, LitStr("∀x😀"))),
]


def run_proj_oracle():
    """One lean batch; returns one serialized-WHNF dict per PROJ_CASES entry."""
    body = lean_ref.ORACLE_TEMPLATE.format(defs="", imports="")
    for _cid, idx, s, _e in PROJ_CASES:
        body += ("\nrun_cmd do liftTermElabM <| do\n"
                 f'  let e : Expr := mkProj `String {idx} '
                 f'(Lean.mkStrLit "{s}")\n'
                 "  let w ← Meta.whnf e\n"
                 '  IO.println ("ORACLE " ++ serExpr w)')
    path = Path("/tmp/wp5_proj_batch.lean")
    path.write_text(body)
    r = subprocess.run([str(lean_ref.LEAN), str(path)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"lean failed:\n{(r.stdout + r.stderr)[:2000]}")
    out = [json.loads(ln[len("ORACLE "):])
           for ln in r.stdout.splitlines() if ln.startswith("ORACLE ")]
    if len(out) != len(PROJ_CASES):
        raise RuntimeError(f"proj oracle: {len(out)} lines for "
                           f"{len(PROJ_CASES)} cases")
    return out


def _warm_prefix(consts, ctors, meta, graph, outputs):
    """Same memoization as the quot test: sync the env-only token prefix once,
    snapshot the evaluator's causal state, and let each case resume from it."""
    enc0 = Encoder(consts, is_ctor=ctors, const_meta=meta)
    drv0 = StepDriver(enc0.b, graph, outputs)
    env_len = len(drv0.names)
    drv0._eval.sync(drv0.names)
    return env_len, drv0._eval.vals, drv0._eval.lookup_history


def _run_graph(consts, ctors, meta, graph, outputs, ca, cb, kind, warm):
    env_len, warm_vals, warm_hist = warm
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    drv = StepDriver(enc.b, graph, outputs)
    drv._eval.vals = list(warm_vals)
    drv._eval.lookup_history = {i: list(h) for i, h in warm_hist.items()}
    assert len(drv.names) == env_len, "env prefix diverged from warm-up"
    t0 = time.perf_counter()
    if kind == "WHNF":
        p, e = drv.run(enc.encode_term(ca), max_steps=GRAPH_MAX_STEPS)
        res = _canon(decode_closure(enc.b, p, e))
    elif kind == "INFER":
        p, e = drv.run_infer(enc.encode_term(ca), max_steps=GRAPH_MAX_STEPS)
        res = _canon(decode_closure(enc.b, p, e))
    else:
        v = drv.run_defeq(enc.encode_term(ca), 0, enc.encode_term(cb), 0,
                          max_steps=GRAPH_MAX_STEPS)[0]
        res = bool(v)
    if os.environ.get("STR_TIME"):
        print(f"    [time] case run={time.perf_counter()-t0:.1f}s "
              f"steps={drv.steps}", flush=True)
    return res, drv.steps


def check_A(consts, ctors, meta, ordered):
    """E1 encoding invariants + name-keyed tags (no graph, no oracle)."""
    fails = []
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    b = enc.b
    # roundtrip every corpus literal, incl. NUL / empty / multi-byte
    for s in ("", "a", "ab", "∀", "😀", "\x00", "\x00\x00", "a∀x😀\x01"):
        p = enc.encode_term(LitStr(s))
        head = b.stream[p]
        if head[0] != 10 or head[2] != LIT_STR:   # K_LIT, V1 = string
            fails.append(f"[A roundtrip {s!r}] head={head}")
            continue
        if head[1] != len(s.encode("utf-8")):
            fails.append(f"[A roundtrip {s!r}] byte count {head[1]}")
        back = decode_expr(b, p)
        if not isinstance(back, LitStr) or back.value != s:
            fails.append(f"[A roundtrip {s!r}] decoded {back!r}")
    # kernel grammar: App(Const String.ofList, cons(Char.ofNat cp, ... nil))
    for s in ("ab", "∀"):
        p = enc.encode_term(LitStr(s))
        x = b.stream[p][4]
        if not x:
            fails.append(f"[A expansion {s!r}] X=0 with all five names present")
            continue
        got = decode_expr(b, x)
        want = string_expansion(s)
        if _canon(got) != _canon(want):
            fails.append(f"[A expansion {s!r}] got {got!r}")
        # structural spine checks against inductive.cpp:1368-1380
        if not isinstance(got, App) or not isinstance(got.fn, Const) \
                or got.fn.name != "String.ofList" or got.fn.levels:
            fails.append(f"[A expansion {s!r}] head not bare String.ofList")
            continue
        lst = got.arg
        cps = utf8_codepoints(s.encode("utf-8"))
        for cp in cps:
            cons = lst
            if not isinstance(cons, App) or not isinstance(cons.fn, App) \
                    or not isinstance(cons.fn.fn, App):
                fails.append(f"[A expansion {s!r}] cons spine at {lst!r}")
                break
            head_c = cons.fn.fn.fn
            if not (isinstance(head_c, Const) and head_c.name == "List.cons"
                    and head_c.levels == (LZero(),)):
                fails.append(f"[A expansion {s!r}] cons head {head_c!r}")
            if cons.fn.fn.arg != Const("Char"):
                fails.append(f"[A expansion {s!r}] cons type arg")
            cof = cons.fn.arg.fn if isinstance(cons.fn.arg, App) else None
            if not (isinstance(cof, Const) and cof.name == "Char.ofNat") \
                    or cons.fn.arg.arg != LitNat(cp):
                fails.append(f"[A expansion {s!r}] Char.ofNat {cp} at cons")
            lst = cons.arg
        want_nil = App(Const("List.nil", (LZero(),)), Const("Char"))
        if lst != want_nil:
            fails.append(f"[A expansion {s!r}] tail {lst!r} != {want_nil!r}")
    # lenient UTF-8 decoder: utf8.cpp:148-221 branch table (hand-checked
    # expectations — the decoder IS the thing under test here, cited inline)
    cases = [
        (b"\x41", [0x41]), (b"\xc3\xa9", [0xE9]),
        (b"\xe2\x88\x80", [0x2200]), (b"\xf0\x9f\x98\x80", [0x1F600]),
        (b"\xc3", [0xC3]),                      # truncated 2-byte → raw byte
        (b"\xe0\x80\x41", [0xE0, 0x80, 0x41]),  # bad continuation → raw bytes
        (b"\xed\xa0\x80", [0xED, 0xA0, 0x80]),  # surrogate → raw bytes
        (b"\xf4\x90\x80\x80", [0xF4, 0x90, 0x80, 0x80]),  # > 0x10FFFF → raw
        (b"\xf0\x9f\x98", [0xF0, 0x9F, 0x98]),  # truncated 4-byte → raw bytes
    ]
    for data, want in cases:
        got = utf8_codepoints(data)
        if got != want:
            fails.append(f"[A utf8 {data!r}] {got} != {want}")
    # name-keyed tags within the 96-const scan window
    for nm, tag in STR_ID_CODES.items():
        if nm not in b.cids:
            fails.append(f"[A tag] {nm} absent")
            continue
        cid = b.cids[nm]
        if cid >= 96:
            fails.append(f"[A tag] {nm} cid {cid} outside the 96 scan window")
        if b.stream[cid + 1][4] != tag:
            fails.append(f"[A tag] {nm} X={b.stream[cid+1][4]} != {tag}")
    print(f"A  E1 invariants + tags: {len(fails)} failures "
          f"(env {len(b.cids)} names)")
    for msg in fails:
        print(f"  [A] {msg}")
    return fails


def check_A_decline():
    """Encoder-level: without the five expansion names the shadow tree is
    declined (X=0) and the literal still roundtrips."""
    fails = []
    consts = [(n, t, v) for n, t, v in TOY_CONSTS if n in
              ("Nat", "Nat.zero", "Nat.succ", "Bool", "Bool.true")]
    enc = Encoder(consts, is_ctor={})
    p = enc.encode_term(LitStr("ab"))
    if enc.b.stream[p][4] != 0:
        fails.append("[A decline] X != 0 without expansion names")
    if decode_expr(enc.b, p) != LitStr("ab"):
        fails.append("[A decline] roundtrip broken when declined")
    return fails


def main() -> int:
    n_fail = 0
    fails = []

    consts, ctors, meta, ordered = build_env()
    print(f"env: {len(TOY_CONSTS) + len(ordered)} consts "
          f"(string prefix {len(ordered)}, window 96)")
    fails += check_A(consts, ctors, meta, ordered)
    fails += check_A_decline()

    _g0 = time.perf_counter()
    if os.environ.get("STR_SKIP_B") and os.environ.get("STR_SKIP_C"):
        graph = outputs = warm = None
    else:
        graph, outputs = build_step_graph()
        warm = _warm_prefix(consts, ctors, meta, graph, outputs)
    if os.environ.get("STR_TIME") and warm:
        print(f"    [time] build + warm (env_len={warm[0]}) "
              f"{time.perf_counter()-_g0:.1f}s", flush=True)

    # ── B. differential corpus vs real lean ─────────────────────────────────
    if os.environ.get("STR_SKIP_B"):
        print("B  corpus: skipped (STR_SKIP_B set)")
        b_pass, b_total = 0, len(CASES) + len(PROJ_CASES)
    else:
        entries = [(k, a, bb) for (_, k, a, bb, _, _) in CASES]
        _o0 = time.perf_counter()
        oracle = lean_ref.run_oracle_mixed(TOY_LEAN_DEFS, entries)
        if os.environ.get("STR_TIME"):
            print(f"    [time] oracle {time.perf_counter()-_o0:.1f}s",
                  flush=True)
        b_pass = 0
        for (cid, kind, sa, sb, ea, eb), oval in zip(CASES, oracle):
            if _ONLY and cid not in _ONLY:
                continue
            got, steps = _run_one(
                lambda: _run_graph(consts, ctors, meta, graph, outputs,
                                   ea, eb, kind, warm))
            if kind == "DEFEQ":
                exp = oval[1]
            else:                       # WHNF / INFER: serialized expr dict
                exp = _canon(lean_ref.json_to_expr(oval[1]))
            if got == exp:
                b_pass += 1
                print(f"  [PASS] {cid} ({kind}, {steps} micro-steps)")
            else:
                fails.append(f"[B {cid}] graph={got!r} lean={exp!r}")
        # E5 raw-proj nodes via the run_cmd batch oracle
        poracle = run_proj_oracle()
        for (cid, idx, s, ea), pval in zip(PROJ_CASES, poracle):
            if _ONLY and cid not in _ONLY:
                continue
            got, steps = _run_one(
                lambda: _run_graph(consts, ctors, meta, graph, outputs,
                                   ea, None, "WHNF", warm))
            exp = _canon(lean_ref.json_to_expr(pval))
            if got == exp:
                b_pass += 1
                print(f"  [PASS] {cid} (WHNF, {steps} micro-steps)")
            else:
                fails.append(f"[B {cid}] graph={got!r} lean={exp!r}")
        print(f"B  corpus vs real lean: {b_pass}/"
              f"{len(CASES) + len(PROJ_CASES)}")

    # ── C. graph-only: value-pruned env → the kernel's try_string_lit
    #     _expansion arm (type_checker.cpp:1145-1156) reachable for the first
    #      time (String.ofList has no value → lazy_delta declines → eta_struct
    #      falls through to the arm; matched arm is FINAL).  No oracle exists
    #      for this env (real lean's ofList always has a value), so these are
    #      semantic-shape checks against the cited kernel lines.
    if os.environ.get("STR_SKIP_C"):
        print("C  arm-coverage: skipped (STR_SKIP_C set)")
        c_pass, c_total = 0, 2
    else:
        consts_c, ctors_c, meta_c, _ = build_env(keep_val=set())
        warm_c = _warm_prefix(consts_c, ctors_c, meta_c, graph, outputs)
        c_cases = [
            # (id, a, b, expected: expansion==ofList-app)
            ("es_str_true", lit_ab, of_list("ab"), True),
            ("es_str_false", lit_ab, of_list("a"), False),
            ("es_str_nultrue", lit_nulnul, of_list("\x00\x00"), True),
        ]
        c_pass = 0
        for cid, ea, eb, want in c_cases:
            if _ONLY and cid not in _ONLY:
                continue
            got, steps = _run_one(
                lambda: _run_graph(consts_c, ctors_c, meta_c, graph,
                                   outputs, ea, eb, "DEFEQ", warm_c))
            # bool identity: checks value AND type (an exception string can
            # never be True/False).  The old `got is True and got == want`
            # was unsatisfiable for the want=False case — see handoff
            # docs/handoffs/001-A-wp5.md for the full evidence chain.
            if got is want:
                c_pass += 1
                print(f"  [PASS] {cid} ({steps} micro-steps)")
            else:
                fails.append(f"[C {cid}] graph={got!r} want={want}")
        print(f"C  try_string_lit_expansion arm (pruned env): "
              f"{c_pass}/{len(c_cases)}")

    for msg in fails:
        print(f"  [FAIL] {msg}")
    ok = not fails
    corpus = "skipped" if os.environ.get("STR_SKIP_B") \
        else f"{b_pass}/{len(CASES) + len(PROJ_CASES)}"
    cs = "skipped" if os.environ.get("STR_SKIP_C") else f"{c_pass}/3"
    print(f"\n=== WP5 string literals: B corpus {corpus}, C arm {cs}, "
          f"{len(fails)} failures === {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
