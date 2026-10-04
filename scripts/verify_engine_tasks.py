#!/usr/bin/env python3
"""Card 013 verification harness: the engine INFER/DEFEQ/CHECK channels.

Stages (expected verdicts are ALWAYS live-computed — acceptance rule 2,
nothing here is a fixture):
  tasks  — CHECK 15 (12 single + 3 sequences; tests/test_check_e2e.py corpus
           shape, self-contained generation) + DEFEQ 65 + INFER 19
           (reference/toy_env corpora; tests/test_stepgraph_infer_defeq.py
           shape): engine/vm_run accept/reject + reject_code triples vs RefVM
           on the same corpus, plus the DONE payload (defeq verdict / infer
           type closure / check result) as a second, reported-separately gate.
  kdecl  — 12 cases vs the real C++ kernel through reference.lean_ref
           .run_kdecl_oracle (Kernel.Environment.addDecl, VM_SPEC 12.5(B);
           NOT run_check_oracle — that is the elaborator-carrying Meta path,
           not a kernel judgement, card 013 权威依据).  Classes covered:
           OK, declTypeMismatch(1), typeExpected(5), declHasFVars(6),
           thmTypeIsNotProp(8).
  meta   — `vm_run <sbin> --meta-check` dump vs expr/tokens.py constants and
           vs the L4SV tail this file re-parses straight from the sbin
           (hard-coded-value drift gate, card 013 verifier 4).

Run (pinned artifact, AGENTS 会话开场 3):
  SBIN=$PWD/model/step_vm_015_full_scratch.sbin \
  python3 -u scripts/verify_engine_tasks.py [meta] [tasks] [kdecl] [all]
"""
import os
import struct
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = "/home/xkq/Lean4-Transformer-Vm-OSS"
sys.path.insert(0, ROOT)

from expr.tokens import (Encoder, decode_closure,
                         T_PEND, T_LINK, T_FRAME, T_STATE, T_LIT_DIG,
                         K_LIT, K_CONST, LIT_NAT, T_REJECT, T_HALT,
                         TASK_INFER, TASK_DEFEQ, TASK_CHECK)
from expr.model import (App, Const, FVar, Lam, Let, LitNat, MData, Pi, Proj,
                        Sort, BVar, BI_DEFAULT,
                        LZero, LSucc, LMax, LIMax, LParam, LMVar)
from lean_vm.ref_vm import RefVM, VMError
from reference.toy_env import (TOY_CONSTS, TOY_CTORS, TOY_STRUCTS,
                               DEFEQ_CORPUS, INFER_CORPUS)
from reference import lean_ref
from reference.olean_export import import_env
from tests.test_olean_export import TARGET_DEFS, ROOTS

ENGINE = os.environ.get("VM_ENGINE", os.path.join(ROOT, "engine", "vm_run"))
SBIN = os.environ.get("SBIN",
                      os.path.join(ROOT, "model", "step_vm_015_full_scratch.sbin"))

# CHECK anchor E2 kind codes (lean_vm/step_driver.py check_e2 / ENV_FORMAT
# §2.8); 0 = the runner's legacy all-inert shape used by the tasks stage.
KIND_UNSPEC, KIND_AXIOM, KIND_DEFN, KIND_THM = 0, 1, 2, 3

# kernel exception class -> graph reject code (tests/test_defeq_branches_vs_
# lean.py G_CODE, docs/VM_SPEC.md §7.4; thmTypeIsNotProp -> 8 per card 010 G02)
G_CODE = {"typeExpected": 5, "declHasFVars": 6, "declHasMVars": 6,
          "declTypeMismatch": 1, "unknownConstant": 2, "thmTypeIsNotProp": 8}
G_OTHER = [("uses unsafe declaration", 7), ("must not contain partial", 7)]

NAT = Const("Nat")
BOOL = Const("Bool")
TYPE1 = Sort(LSucc(LZero()))


def _arrow(a, b):
    return Pi("", BI_DEFAULT, a, b)


# ── CHECK corpus (tests/test_check_e2e.py shape; generation self-contained)
CHECK_CASES = [
    ("chk_dbl_nat", "Nat", "E_dbl 21", NAT, App(Const("E_dbl"), LitNat(21))),
    ("chk_ten", "Nat", "E_ten", NAT, Const("E_ten")),
    ("chk_dbl_bool", "Bool", "E_dbl 2", BOOL, App(Const("E_dbl"), LitNat(2))),
    ("chk_inc_fn", "Nat → Nat", "E_inc", _arrow(NAT, NAT), Const("E_inc")),
    ("chk_inc_fn_bad", "Nat → Bool", "E_inc", _arrow(NAT, BOOL),
     Const("E_inc")),
    ("chk_mk_pair", "E_pair", "E_mk", Const("E_pair"), Const("E_mk")),
    ("chk_two_pair", "E_pair", "E_two", Const("E_pair"), Const("E_two")),
    ("chk_let", "Nat", "E_let", NAT, Const("E_let")),
    ("chk_hof_inc", "Nat", "E_hof E_inc", NAT,
     App(Const("E_hof"), Const("E_inc"))),
    ("chk_nat_type", "Type", "Nat", TYPE1, NAT),
    ("chk_type_nat", "Nat", "Type", NAT, TYPE1),
    ("chk_mk_nat", "Nat", "E_pair.mk 1 2", NAT,
     App(App(Const("E_pair.mk"), LitNat(1)), LitNat(2))),
]
CASE = {c: (t, v, te, ve) for c, t, v, te, ve in CHECK_CASES}
SEQUENCES = [
    ("seq_all_ok", ["chk_dbl_nat", "chk_ten", "chk_inc_fn", "chk_mk_pair",
                    "chk_let", "chk_hof_inc", "chk_nat_type"]),
    ("seq_reject_second", ["chk_dbl_nat", "chk_dbl_bool"]),
    ("seq_reject_first", ["chk_dbl_bool", "chk_dbl_nat"]),
]


def strip_mdata(e):
    if isinstance(e, MData):
        return strip_mdata(e.child)
    if isinstance(e, App):
        return App(strip_mdata(e.fn), strip_mdata(e.arg))
    if isinstance(e, (Lam, Pi)):
        return type(e)(e.name, e.binfo, strip_mdata(e.domain),
                       strip_mdata(e.body))
    if isinstance(e, Let):
        return Let(e.name, strip_mdata(e.domain), strip_mdata(e.value),
                   strip_mdata(e.body), nondep=e.nondep)
    return e


# ── engine runner ─────────────────────────────────────────────────────────

def run_engine(mode, pre_stream, term_pos, max_steps, extra=(), timeout=600):
    """Invoke vm_run in one of the card-013 task modes; returns
    (final_stream, verdict_tokens, err)."""
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write("%d\n" % len(pre_stream))
    for t in pre_stream:
        f.write(" ".join(str(int(x)) for x in tuple(t) + (0,) * (7 - len(t)))
                + "\n")
    f.close()
    args = [ENGINE, SBIN, f.name, str(term_pos)]
    if mode == "whnf":
        args.append(str(max_steps))
    else:
        args += [mode, str(max_steps)] + [str(x) for x in extra]
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        os.unlink(f.name)
        return None, None, "TIMEOUT %ds" % timeout
    os.unlink(f.name)
    if p.returncode != 0:
        return None, None, p.stderr[-300:]
    lines = p.stdout.strip().splitlines()
    n = int(lines[0])
    st = [tuple(int(x) for x in ln.split()) for ln in lines[1:1 + n]]
    return st, lines[1 + n].split(), None


def engine_tuple(ver):
    """verdict line -> (kind, reject_code, payload) — the first two are the
    card-013 required triple member set; payload is the DONE/reject detail."""
    if ver[0] == "DONE":
        return ("DONE", None, (int(ver[1]), int(ver[2]), int(ver[3])))
    if ver[0] == "REJECT":
        return ("REJECT", int(ver[1]), (int(ver[2]), int(ver[3]), int(ver[4])))
    return ("NOT_DONE", None, (int(ver[1]),))


# ── stage: tasks (card 013 verifier 2) ────────────────────────────────────

def stage_tasks():
    t0 = time.perf_counter()
    fails = []
    n_ok = 0
    total = len(INFER_CORPUS) + len(DEFEQ_CORPUS) + len(CHECK_CASES) \
        + len(SEQUENCES)

    print(f"== INFER ({len(INFER_CORPUS)}): engine vs RefVM ==")
    for cid, _src, term in INFER_CORPUS:
        re_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        re_vm = RefVM(re_enc.b, structures=TOY_STRUCTS)
        rp = re_enc.encode_term(term)
        try:
            rtp, rtev = re_vm.infer(rp, 0)
            exp_expr = strip_mdata(decode_closure(re_enc.b, rtp, rtev))
            exp = ("DONE", None)
        except VMError as e:
            exp = ("REJECT", e.code)
            exp_expr = None
        except Exception as e:  # noqa
            fails.append((cid, f"ref: {e}"))
            print(f"  [REFERR] {cid}: {e}", flush=True)
            continue
        enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        gp = enc.encode_term(term)
        st, ver, err = run_engine("infer", list(enc.b.stream), gp, 10000)
        if err:
            fails.append((cid, f"engine: {err}"))
            print(f"  [FAIL] {cid}: engine {err}", flush=True)
            continue
        got = engine_tuple(ver)
        ok = got[:2] == exp
        if ok and got[0] == "DONE":
            enc.b.stream = st
            try:
                got_expr = strip_mdata(decode_closure(enc.b, got[2][0],
                                                      got[2][1]))
            except Exception as e:  # noqa
                got_expr = f"decode error {e}"
            if got_expr != exp_expr:
                ok = False
                got = ("CLOSEQ", None)
        n_ok += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid:24s} "
              f"eng={got[0]}{'/code=' + str(got[1]) if got[1] is not None else ''} "
              f"ref={exp[0]}{'/code=' + str(exp[1]) if exp[1] is not None else ''} "
              f"{ver[-1]} steps", flush=True)
        if not ok:
            fails.append((cid, f"engine {got[:2]} vs ref {exp[:2]} "
                               f"(ref type={exp_expr!r})"))

    print(f"== DEFEQ ({len(DEFEQ_CORPUS)}) ==")
    for cid, _lsrc, _rsrc, l, r in DEFEQ_CORPUS:
        re_enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        re_vm = RefVM(re_enc.b, structures=TOY_STRUCTS)
        lp = re_enc.encode_term(l)
        rp = re_enc.encode_term(r)
        try:
            exp = ("DONE", None)
            exp_verdict = int(bool(re_vm.defeq((lp, 0), (rp, 0))))
        except VMError as e:
            exp = ("REJECT", e.code)
            exp_verdict = None
        except Exception as e:  # noqa
            fails.append((cid, f"ref: {e}"))
            print(f"  [REFERR] {cid}: {e}", flush=True)
            continue
        enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
        gp_l = enc.encode_term(l)
        gp_r = enc.encode_term(r)
        st, ver, err = run_engine("defeq", list(enc.b.stream), gp_l, 10000,
                                  extra=(0, gp_r, 0))
        if err:
            fails.append((cid, f"engine: {err}"))
            print(f"  [FAIL] {cid}: engine {err}", flush=True)
            continue
        got = engine_tuple(ver)
        verdict = None if got[0] != "DONE" else int(got[2][0] == 1)
        ok = got[:2] == exp and (verdict is None or verdict == exp_verdict)
        n_ok += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid:24s} "
              f"eng={got[0]}{'/code=' + str(got[1]) if got[1] is not None else ''}"
              f"{'' if verdict is None else ' v=' + str(verdict)} "
              f"ref={exp[0]}{'/code=' + str(exp[1]) if exp[1] is not None else ''}"
              f" v={exp_verdict}  {ver[-1]} steps", flush=True)
        if not ok:
            fails.append((cid, f"engine {got[:2]} v={verdict} vs ref "
                               f"{exp[:2]} v={exp_verdict}"))

    consts, ctors, structs = import_env(TARGET_DEFS, ROOTS)

    print(f"== CHECK ({len(CHECK_CASES)} single + {len(SEQUENCES)} "
          f"sequences = 15) ==")

    def check_case(name, decl_exprs):
        re_enc = Encoder(consts, is_ctor=ctors)
        re_vm = RefVM(re_enc.b, structures=structs)
        rdecls = [(re_enc.encode_term(te), re_enc.encode_term(ve))
                  for te, ve in decl_exprs]
        try:
            rr = re_vm.check(rdecls)
            exp = ("DONE", None)
            exp_res = int(rr[0])
        except VMError as e:
            exp = ("REJECT", e.code)
            exp_res = None
        except Exception as e:  # noqa
            fails.append((name, f"ref: {e}"))
            print(f"  [REFERR] {name}: {e}", flush=True)
            return 0
        enc = Encoder(consts, is_ctor=ctors)
        enc = Encoder(consts, is_ctor=ctors)
        trip = []
        for te, ve in decl_exprs:
            trip.append((enc.encode_term(te), enc.encode_term(ve),
                         KIND_UNSPEC))  # runner.run_check legacy E2
        st, ver, err = run_engine(
            "check", list(enc.b.stream), trip[0][1], 50000,
            extra=[len(trip)] + [x for tp in trip for x in tp])
        if err:
            fails.append((name, f"engine: {err}"))
            print(f"  [FAIL] {name}: engine {err}", flush=True)
            return 0
        got = engine_tuple(ver)
        res = None if got[0] != "DONE" else int(got[2][0])
        ok = got[:2] == exp and (res is None or res == exp_res)
        n_ok_local = ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:24s} "
              f"eng={got[0]}{'/code=' + str(got[1]) if got[1] is not None else ''}"
              f"{'' if res is None else ' r=' + str(res)} "
              f"ref={exp[0]}{'/code=' + str(exp[1]) if exp[1] is not None else ''}"
              f" r={exp_res}  {ver[-1]} steps", flush=True)
        if not ok:
            fails.append((name, f"engine {got[:2]} r={res} vs ref "
                                f"{exp[:2]} r={exp_res}"))
        return n_ok_local

    for cid, _t, _v, te, ve in CHECK_CASES:
        n_ok += check_case(cid, [(te, ve)])
    for cid, members in SEQUENCES:
        decls = [(CASE[m][2], CASE[m][3]) for m in members]
        n_ok += check_case(cid, decls)

    print(f"\n=== engine tasks vs RefVM: {n_ok}/{total} "
          f"accept/reject+code triples correct "
          f"(INFER {len(INFER_CORPUS)} + DEFEQ {len(DEFEQ_CORPUS)} + "
          f"CHECK {len(CHECK_CASES)} + SEQ {len(SEQUENCES)}), "
          f"{time.perf_counter() - t0:.1f}s ===")
    for cid, msg in fails:
        print(f"  FAIL {cid}: {msg}")
    return 0 if not fails else 1


# ── stage: kdecl (card 013 verifier 3) ────────────────────────────────────

def _ser_level(L):
    if isinstance(L, LZero):
        return "Level.zero"
    if isinstance(L, LSucc):
        return f"Level.succ ({_ser_level(L.l)})"
    if isinstance(L, LParam):
        return f"Level.param `{L.name}"
    if isinstance(L, LMax):
        return f"Level.max ({_ser_level(L.a)}) ({_ser_level(L.b)})"
    if isinstance(L, LIMax):
        return f"Level.imax ({_ser_level(L.a)}) ({_ser_level(L.b)})"
    raise NotImplementedError(f"level {L}")


def _ser(e):
    """expr.model tree -> Lean source term of type Lean.Expr (raw kernel
    vocabulary), mirroring tests/test_defeq_branches_vs_lean.py's G_CASES.
    Every node returns a fully parenthesized application so it can be
    dropped into any argument or struct-field position unchanged."""
    if isinstance(e, Const):
        base = f"Lean.mkConst ``{e.name}"
        if e.levels:
            base += " [" + ", ".join(_ser_level(l) for l in e.levels) + "]"
        return f"({base})"
    if isinstance(e, App):
        return f"(Lean.mkApp {_ser(e.fn)} {_ser(e.arg)})"
    if isinstance(e, Lam):
        return (f"(Lean.mkLambda `{e.name or 'b'} BinderInfo.default "
                f"{_ser(e.domain)} {_ser(e.body)})")
    if isinstance(e, Pi):
        return (f"(Lean.mkForall `{e.name or 'b'} BinderInfo.default "
                f"{_ser(e.domain)} {_ser(e.body)})")
    if isinstance(e, Sort):
        return f"(Lean.mkSort ({_ser_level(e.level)}))"
    if isinstance(e, LitNat):
        return f"(Lean.mkNatLit {e.value})"
    if isinstance(e, BVar):
        return f"(Lean.mkBVar {e.idx})"
    if isinstance(e, FVar):
        return f'(Lean.mkFVar ⟨.str .anonymous "{e.name}"⟩)'
    if isinstance(e, MData):
        return _ser(e.child)
    raise NotImplementedError(f"term {e}")


def _defn(name, ty, val):
    return (f".defnDecl {{ name := `{name}, levelParams := [], "
            f"type := {_ser(ty)}, value := {_ser(val)}, "
            f"hints := .regular 0, safety := .safe, all := [`{name}] }}")


def _axiom(name, ty):
    return (f".axiomDecl {{ name := `{name}, levelParams := [], "
            f"type := {_ser(ty)}, isUnsafe := false }}")


def _thm(name, ty, val):
    # TheoremVal has no isUnsafe field (tests/test_decl_injection_vs_lean.py
    # _THM shape)
    return (f".thmDecl {{ name := `{name}, levelParams := [], "
            f"type := {_ser(ty)}, value := {_ser(val)} }}")


# (cid, decl_src fn, engine (type_expr, val_expr|None, kind), expected class
#  set).  Engine side runs CHECK on the SAME declaration data: (type_root,
#  val_root, kind-code E2) — kind 1/2/3 = axiom/defn/thm (ENV_FORMAT §2.8).
KDECL_CASES = None  # built at stage time (needs CASE / serializer exprs)


def stage_kdecl():
    global KDECL_CASES
    ok_defns = ["chk_dbl_nat", "chk_ten", "chk_inc_fn", "chk_mk_pair",
                "chk_let", "chk_hof_inc"]
    KDECL_CASES = []
    for i, cid in enumerate(ok_defns):
        t, v, te, ve = CASE[cid]
        KDECL_CASES.append(
            (f"k_ok_{cid}",
             _defn(f"k13d_{i}", te, ve), (te, ve, KIND_DEFN), {"OK"}))
    for i, cid in enumerate(["chk_inc_fn_bad", "chk_type_nat",
                             "chk_dbl_bool"]):
        t, v, te, ve = CASE[cid]
        KDECL_CASES.append(
            (f"k_bad_{cid}",
             _defn(f"k13b_{i}", te, ve), (te, ve, KIND_DEFN),
             {"declTypeMismatch"}))
    KDECL_CASES.append(
        ("k_typeExpected",
         _axiom("k13te", Const("E_two")),
         (Const("E_two"), None, KIND_AXIOM), {"typeExpected"}))
    KDECL_CASES.append(
        ("k_hasFVars",
         _axiom("k13fv", FVar("p")),
         (FVar("p"), None, KIND_AXIOM), {"declHasFVars"}))
    KDECL_CASES.append(
        ("k_thmNotProp",
         _thm("k13np", Const("Nat"), Const("E_ten")),
         (Const("Nat"), Const("E_ten"), KIND_THM), {"thmTypeIsNotProp"}))

    consts, ctors, _structs = import_env(TARGET_DEFS, ROOTS)

    cases = [(cid, dsrc) for cid, dsrc, _eng, _exp in KDECL_CASES]
    kdecl = lean_ref.run_kdecl_oracle(TARGET_DEFS, cases)

    n_ok = 0
    fails = []
    for (cid, _dsrc, (te, ve, kind), exp_cls), cls in zip(KDECL_CASES, kdecl):
        base = cls.split(":", 1)[0]
        matched = any(base == e or (e.startswith("other:")
                                    and base.startswith(e))
                      for e in exp_cls)
        if not matched:
            fails.append((cid, f"kernel live class '{base}' not in "
                               f"declared set {sorted(exp_cls)}"))
            print(f"  [KFAIL] {cid}: live kernel class {base!r} != declared "
                  f"{sorted(exp_cls)} (corpus drifted?)", flush=True)
            continue
        if base == "OK":
            exp_code = 0
        elif base in G_CODE:
            exp_code = G_CODE[base]
        else:
            exp_code = next((c for pref, c in G_OTHER
                             if base.startswith("other") and pref in base), -1)
        # engine side: CHECK on (type_root, val_root|0, kind)
        enc = Encoder(consts, is_ctor=ctors)
        tp = enc.encode_term(te)
        vp = enc.encode_term(ve) if ve is not None else 0
        st, ver, err = run_engine("check", list(enc.b.stream), vp, 50000,
                                  extra=[1, tp, vp, kind])
        if err:
            fails.append((cid, f"engine: {err}"))
            print(f"  [FAIL] {cid}: engine {err}", flush=True)
            continue
        got = engine_tuple(ver)
        if base == "OK":
            ok = got[0] == "DONE"
        else:
            ok = got[0] == "REJECT" and got[1] == exp_code
        n_ok += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid:24s} "
              f"kernel={base:18s} exp_code={exp_code} "
              f"engine={got[0]}{'/code=' + str(got[1]) if got[1] is not None else ''} "
              f"{ver[-1]} steps", flush=True)
        if not ok:
            fails.append((cid, f"engine {got[0]}/"
                               f"{got[1]} vs kernel {base}->{exp_code}"))
    print(f"\n=== engine vs #KDECL raw kernel: {n_ok}/{len(KDECL_CASES)} "
          f"consistent (>=10 required, all reachable error classes) ===")
    for cid, msg in fails:
        print(f"  FAIL {cid}: {msg}")
    return 0 if not fails else 1


# ── stage: meta (card 013 verifier 4) ─────────────────────────────────────

def parse_sbin_meta(path):
    """Python re-parse of the L4SV tail — mirrors compiler/weights.py
    save_sparse_native + engine Cursor/load_tail byte layout."""
    data = open(path, "rb").read()
    p = [0]

    def i32():
        v, = struct.unpack_from("<i", data, p[0])
        p[0] += 4
        return v

    def i64():
        v, = struct.unpack_from("<q", data, p[0])
        p[0] += 8
        return v

    def name():
        ln = i32()
        s = data[p[0]:p[0] + ln].decode()
        p[0] += ln
        return s

    assert data[0:4] == b"L4SV", "bad magic"
    p[0] = 4
    ver = i32()
    assert ver == 2, f"expected L4SV v2, got {ver}"
    vocab, d_model, n_layers, n_heads, d_ffn, stop = struct.unpack_from(
        "<6i", data, p[0])
    p[0] += 24
    layer_heads = [i32() for _ in range(n_layers)]
    for _ in range(vocab):
        name()

    def skip_csr():
        rows = i32()
        i32()  # cols
        nnz = i64()
        p[0] += (rows + 1) * 8 + nnz * 4 + nnz * 8

    for _ in range(n_layers):
        for _ in range(6):
            skip_csr()
    skip_csr()  # head
    has_erase = i32()
    if has_erase:
        for _ in range(n_layers):
            n = i32()
            p[0] += 4 * n
            n = i32()
            p[0] += 4 * n
    if i32():
        p[0] += 4 * n_layers * n_heads
    meta = i32()
    assert meta == 1, "weights file carries no runner meta"
    fs = {}
    for _ in range(i32()):
        nm = name()
        fs[nm] = i32()
    one = i32()
    oi = {}
    for _ in range(i32()):
        nm = name()
        oi[nm] = i32()
    return dict(vocab=vocab, d_model=d_model, n_layers=n_layers,
                n_heads=n_heads, d_ffn=d_ffn, stop=stop,
                field_slots=fs, one_slot=one, output_index=oi)


REQUIRED_OUT = [
    "done", "result_pos", "A", "B", "C", "D", "E", "F",
    "reject", "reject_code",
    "em_raw", "raw_K", "raw_V0", "raw_V1", "raw_V2", "raw_X", "raw_E2",
    "em_pend", "pend_V0", "pend_prev", "pend_env",
    "em_link", "link_V0", "link_V1", "link_prev", "link_env",
    "link_flag", "link_F2",
    "em_link2", "link2_V0", "link2_V1", "link2_prev", "link2_env",
    "link2_flag", "link2_F2",
    "em_litdig", "dig_V0",
    "em_frame", "frame_task", "frame_V1", "frame_V2", "frame_X",
    "frame_E2", "frame_F2",
    "em_frame2", "frame2_task", "frame2_V1", "frame2_V2", "frame2_X",
    "frame2_E2", "frame2_F2",
    "em_lithead", "head_V0", "head_V2", "head_X",
    "em_gap", "em_litdig2", "dig2_V0", "em_const", "const_cid",
]


def stage_meta():
    p = subprocess.run([ENGINE, SBIN, "--meta-check"], capture_output=True,
                       text=True, timeout=120)
    if p.returncode != 0:
        print("  [FAIL] engine --meta-check rc:", p.returncode, p.stderr[-200:])
        return 1
    eng = {"SLOT": {}, "OUT": {}, "CONST": {}}
    hdr = None
    for ln in p.stdout.splitlines():
        w = ln.split()
        if w[0] == "HEADER":
            hdr = w
        elif w[0] in eng:
            eng[w[0]][w[1]] = int(w[2])
    fails = []

    # 1) token constants vs expr/tokens.py (the single source)
    want = dict(T_PEND=T_PEND, T_LINK=T_LINK, T_FRAME=T_FRAME,
                T_STATE=T_STATE, T_LIT_DIG=T_LIT_DIG, K_LIT=K_LIT,
                K_CONST=K_CONST, LIT_NAT=LIT_NAT, T_REJECT=T_REJECT,
                T_HALT=T_HALT, TASK_INFER=TASK_INFER, TASK_DEFEQ=TASK_DEFEQ,
                TASK_CHECK=TASK_CHECK)
    for k, v in want.items():
        if eng["CONST"].get(k) != v:
            fails.append(f"CONST {k}: engine {eng['CONST'].get(k)} vs "
                         f"expr/tokens.py {v}")

    # 2) engine-parsed meta vs Python re-parse of the same file tail
    py = parse_sbin_meta(SBIN)
    if f"vocab {py['vocab']} d_model {py['d_model']} n_layers " \
            f"{py['n_layers']} n_heads {py['n_heads']} d_ffn {py['d_ffn']} " \
            f"stop {py['stop']}" != " ".join(hdr[1:]):
        fails.append(f"HEADER mismatch: engine {hdr} vs python {py}")
    slots = dict(py["field_slots"])
    slots["one"] = py["one_slot"]
    for k, v in slots.items():
        if eng["SLOT"].get(k) != v:
            fails.append(f"SLOT {k}: engine {eng['SLOT'].get(k)} vs file {v}")
    for k, v in py["output_index"].items():
        if eng["OUT"].get(k) != v:
            fails.append(f"OUT {k}: engine {eng['OUT'].get(k)} vs file {v}")

    # 3) the card-013 contract names all resolve (hardcoded-meta drift gate)
    for nm in REQUIRED_OUT:
        if nm not in py["output_index"]:
            fails.append(f"output dim {nm!r} missing from sbin meta")
    print(f"=== engine meta vs sbin+tokens: {'OK' if not fails else 'FAIL'} "
          f"({len(eng['OUT'])} output dims, {len(want)} token consts) ===")
    for f_ in fails:
        print("  FAIL", f_)
    return 0 if not fails else 1


STAGES = {"meta": stage_meta, "tasks": stage_tasks, "kdecl": stage_kdecl}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    order = ["meta", "tasks", "kdecl"] if arg == "all" else [arg]
    rc = 0
    for s in order:
        print(f"\n########## stage {s} ##########")
        try:
            rc |= STAGES[s]()
        except Exception:  # noqa
            traceback.print_exc()
            rc = 1
    sys.exit(rc)
