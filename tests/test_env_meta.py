"""WP1 — ENV declaration-metadata encoding round-trip + real-Lean oracle.

Implements docs/ENV_FORMAT.md §5.1/§5.2/§5.3: encode the real kernel
ConstantInfo metadata of the toy environment into the token stream, decode it
back with expr.tokens.decode_env_meta, and compare every field against a dump
produced by the real lean binary (reference/olean_export.dump_env). No
expected metadata value is hand-written: everything comes from
Environment.find? / ConstantInfo on lean 4.33.1.

Coverage:
  A. per-cid round-trip against the real dump (all 35 toy constants)
  B. idempotence (encode -> decode -> re-encode is byte-identical)
  C. StreamBundle cross-check (T_ENV.V1/V2 vs const_type_pos/value_pos)
  D. §5.1 item 4 invariants (major_idx, rule order vs ctor cidx, Bool order)
  E. §5.2 casesOn kinds are Definition, not Recursor (TBD#4)
  F. supplementary real-dump bundles: Bool.rec rule order, Quot kinds
  G. §5.3 mutations: a corrupted token disagrees with the real values

Run: OMP_NUM_THREADS=4 python3 tests/test_env_meta.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import Const, Sort, LZero
from expr.tokens import (
    Encoder, decode_env_meta,
    T_ENV, T_ENV_META, T_ENV_DEFVAL, T_ENV_SIMPLEVAL, T_ENV_INDVAL,
    T_ENV_CTORVAL, T_ENV_RECVAL, T_ENV_RULE, T_ENV_LIST, T_ENV_QUOTVAL,
    T_ENV_INDEXTRA, T_ENV_RECEXTRA,
    CK_AXIOM, CK_DEFINITION, CK_THEOREM, CK_OPAQUE, CK_QUOT, CK_INDUCTIVE,
    CK_CONSTRUCTOR, CK_RECURSOR,
    ENV_F_HAS_VALUE, ENV_F_IS_CTOR, ENV_F_IS_INDUCTIVE, ENV_F_IS_RECURSOR,
    ENV_F_IS_QUOT, ENV_F_IS_UNSAFE, ENV_F_IS_REC, ENV_F_IS_REFLEXIVE,
    ENV_F_IS_K, ENV_F_IS_PARTIAL,
)
from reference.olean_export import dump_env
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_LEAN_DEFS

_DUMMY_TY = Sort(LZero())


# ── dump → Encoder const_meta ───────────────────────────────────────────────

def _conv(m: dict) -> dict:
    """Real-dump meta dict → expr.tokens.Encoder const_meta entry."""
    k = m["kind"]
    o: dict = {"kind": k}
    if k == CK_DEFINITION:
        o.update(hints=m["hints"], height=m["height"], safety=m["safety"],
                 is_unsafe=m["isUnsafe"], all=m["all"])
    elif k in (CK_AXIOM, CK_THEOREM, CK_OPAQUE):
        o.update(is_unsafe=m.get("isUnsafe", False), all=m.get("all", []))
    elif k == CK_QUOT:
        o.update(quot_kind=m["quotKind"])
    elif k == CK_INDUCTIVE:
        o.update(nparams=m["np"], nindices=m["ni"], nnested=m["nn"],
                 is_rec=m["isRec"], is_unsafe=m["isUnsafe"],
                 is_reflexive=m["isRefl"], all=m["all"], ctors=m["ctors"])
    elif k == CK_CONSTRUCTOR:
        o.update(induct=m["induct"], cidx=m["cidx"], nparams=m["np"],
                 nfields=m["nfields"], is_unsafe=m["isUnsafe"])
    elif k == CK_RECURSOR:
        o.update(nparams=m["np"], nindices=m["ni"], nmotives=m["nm"],
                 nminors=m["nmin"], is_k=m["isK"], is_unsafe=m["isUnsafe"],
                 all=m["all"], rules=m["rules"])
    else:
        raise AssertionError(f"unexpected kind {k}")
    return o


def _meta_for(consts, dump: dict) -> dict[int, dict]:
    out = {}
    for cid, (name, _, _) in enumerate(consts):
        if name not in dump:
            raise AssertionError(f"{name} missing from real-lean dump")
        out[cid] = _conv(dump[name]["meta"])
    return out


# ── real dump → expected decoded dict (independently computed from §2.3) ────

def _expected(name: str, m: dict, cid: int = 0, univ_arity: int = 0) -> dict:
    k = m["kind"]
    safety = int(m.get("safety", 1))
    unsafe = bool(m.get("isUnsafe", False)) or (
        k == CK_DEFINITION and safety == 0)
    flags = 0
    if k in (CK_DEFINITION, CK_THEOREM, CK_OPAQUE):
        flags |= ENV_F_HAS_VALUE
    if k == CK_CONSTRUCTOR:
        flags |= ENV_F_IS_CTOR
    if k == CK_INDUCTIVE:
        flags |= ENV_F_IS_INDUCTIVE
    if k == CK_RECURSOR:
        flags |= ENV_F_IS_RECURSOR
    if k == CK_QUOT:
        flags |= ENV_F_IS_QUOT
    if unsafe:
        flags |= ENV_F_IS_UNSAFE
    if k == CK_DEFINITION and safety == 2:
        flags |= ENV_F_IS_PARTIAL
    if k == CK_INDUCTIVE:
        if m.get("isRec"):
            flags |= ENV_F_IS_REC
        if m.get("isRefl"):
            flags |= ENV_F_IS_REFLEXIVE
    if k == CK_RECURSOR and m.get("isK"):
        flags |= ENV_F_IS_K

    all_names = list(m.get("all", [])) if k in (
        CK_DEFINITION, CK_THEOREM, CK_OPAQUE, CK_INDUCTIVE, CK_RECURSOR) else []
    e = {
        "cid": cid, "name": name, "univ_arity": univ_arity, "kind": k,
        "flags": flags,
        "has_value": bool(flags & ENV_F_HAS_VALUE),
        "is_ctor": bool(flags & ENV_F_IS_CTOR),
        "is_inductive": bool(flags & ENV_F_IS_INDUCTIVE),
        "is_recursor": bool(flags & ENV_F_IS_RECURSOR),
        "is_quot": bool(flags & ENV_F_IS_QUOT),
        "is_unsafe": bool(flags & ENV_F_IS_UNSAFE),
        "is_rec": bool(flags & ENV_F_IS_REC),
        "is_reflexive": bool(flags & ENV_F_IS_REFLEXIVE),
        "is_k": bool(flags & ENV_F_IS_K),
        "is_partial": bool(flags & ENV_F_IS_PARTIAL),
        "all": all_names,
        "hints_kind": m.get("hints") if k == CK_DEFINITION else None,
        "hints_height": m.get("height") if k == CK_DEFINITION else None,
        "safety": safety if k == CK_DEFINITION else None,
        "nparams": m.get("np") if k in (
            CK_INDUCTIVE, CK_CONSTRUCTOR, CK_RECURSOR) else None,
        "nindices": m.get("ni") if k in (
            CK_INDUCTIVE, CK_RECURSOR) else None,
        "nnested": m.get("nn") if k == CK_INDUCTIVE else None,
        "ctors": list(m.get("ctors", [])) if k == CK_INDUCTIVE else [],
        "induct": m.get("induct") if k == CK_CONSTRUCTOR else None,
        "cidx": m.get("cidx") if k == CK_CONSTRUCTOR else None,
        "nfields": m.get("nfields") if k == CK_CONSTRUCTOR else None,
        "nmotives": m.get("nm") if k == CK_RECURSOR else None,
        "nminors": m.get("nmin") if k == CK_RECURSOR else None,
        "major_idx": (m["np"] + m["nm"] + m["nmin"] + m["ni"]
                      if k == CK_RECURSOR else None),
        "quot_kind": m.get("quotKind") if k == CK_QUOT else None,
    }
    if k == CK_RECURSOR:
        e["rules"] = m["rules"]
    else:
        e["rules"] = []
    return e


_CHECK_KEYS = [
    "cid", "name", "univ_arity", "kind", "flags", "has_value", "is_ctor",
    "is_inductive", "is_recursor", "is_quot", "is_unsafe", "is_rec",
    "is_reflexive", "is_k", "is_partial", "all", "hints_kind", "hints_height",
    "safety", "nparams", "nindices", "nnested", "ctors", "induct", "cidx",
    "nfields", "nmotives", "nminors", "major_idx", "quot_kind",
]


def _cmp(dec: dict, exp: dict, path: str, fails: list):
    for key in _CHECK_KEYS:
        if dec.get(key) != exp[key]:
            fails.append(f"{path}: {key}: decoded={dec.get(key)!r} "
                         f"real={exp[key]!r}")
    # rules: ctor/nfields + rhs Expr round-trip
    dr, er = dec.get("rules", []), exp.get("rules", [])
    if len(dr) != len(er):
        fails.append(f"{path}: rule count decoded={len(dr)} real={len(er)}")
    else:
        for i, (a, b) in enumerate(zip(dr, er)):
            if a["ctor"] != b["ctor"]:
                fails.append(f"{path}: rule[{i}].ctor {a['ctor']} != {b['ctor']}")
            if a["nfields"] != b["nfields"]:
                fails.append(f"{path}: rule[{i}].nfields {a['nfields']} "
                             f"!= {b['nfields']}")
            if a.get("rhs") != b["rhs"]:
                fails.append(f"{path}: rule[{i}].rhs decoded={a.get('rhs')!r}\n"
                             f"    real={b['rhs']!r}")


# ── helpers to walk the metadata region (for mutations) ─────────────────────

def _meta_tokens(b, cid, kind=None):
    """All positions in cid's F2 meta chain, optionally filtered by K."""
    out = []
    p = b.stream[b.env_anchor(cid)][3]
    while p:
        if kind is None or b.stream[p][0] == kind:
            out.append(p)
        p = b.stream[p][6]
    return out


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    n_fail = 0

    # single real-lean dump: toy roots + supplementary recurso/Quot roots
    roots = [n for n, _, _ in TOY_CONSTS] + [
        "Bool.rec", "Quot", "Quot.mk", "Quot.lift", "Quot.ind"]
    dump = dump_env(TOY_LEAN_DEFS, roots)
    print(f"real-lean dump: {len(dump)} constants (roots={len(roots)})")

    # ── A: per-cid round-trip, expected from the real dump ──────────────────
    meta = _meta_for(TOY_CONSTS, dump)
    enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS, const_meta=meta)
    b = enc.b
    fails: list[str] = []
    bad_cids = set()
    for cid, (name, _, _) in enumerate(TOY_CONSTS):
        dec = decode_env_meta(b, cid)
        exp = _expected(name, dump[name]["meta"], cid=cid)
        before = len(fails)
        _cmp(dec, exp, f"[A cid={cid} {name}]", fails)
        if len(fails) > before:
            bad_cids.add(cid)
    print(f"A  per-cid round-trip vs real dump: "
          f"{len(TOY_CONSTS) - len(bad_cids)}/{len(TOY_CONSTS)} cids clean")

    # ── B: idempotence ──────────────────────────────────────────────────────
    enc2 = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS,
                   const_meta=_meta_for(TOY_CONSTS, dump))
    if enc2.b.stream != b.stream:
        n = min(len(enc2.b.stream), len(b.stream))
        bad = [i for i in range(n) if enc2.b.stream[i] != b.stream[i]]
        fails.append(f"[B] re-encode stream differs at {bad[:8]} "
                     f"(len {len(enc2.b.stream)} vs {len(b.stream)})")

    # decode again and compare all metadata (encode->decode->encode)
    for cid, (name, _, _) in enumerate(TOY_CONSTS):
        d1 = decode_env_meta(b, cid)
        d2 = decode_env_meta(enc2.b, cid)
        if d1 != d2:
            fails.append(f"[B cid={cid}] metadata differs after re-encode")

    # ── C: StreamBundle cross-check ─────────────────────────────────────────
    for cid, (name, _, _) in enumerate(TOY_CONSTS):
        hdr = b.stream[cid + 1]
        if hdr[0] != T_ENV:
            fails.append(f"[C cid={cid}] pos cid+1 is K={hdr[0]}, not T_ENV")
        if hdr[2] != b.const_type_pos[cid]:
            fails.append(f"[C cid={cid}] T_ENV.V1 {hdr[2]} != "
                         f"const_type_pos {b.const_type_pos[cid]}")
        if hdr[3] != b.const_value_pos[cid]:
            fails.append(f"[C cid={cid}] T_ENV.V2 {hdr[3]} != "
                         f"const_value_pos {b.const_value_pos[cid]}")
    # anchor block positions: n+1..2n
    n = len(TOY_CONSTS)
    for cid in range(n):
        a = b.env_anchor(cid)
        if a != n + 1 + cid or b.stream[a][0] != T_ENV_META:
            fails.append(f"[C cid={cid}] bad anchor {a}")
    if b.stream[0][0] != 0 or b.stream[0][1] != n:
        fails.append(f"[C] T_NULL.V0 {b.stream[0][1]} != n_consts {n}")

    # ── D: §5.1 item 4 invariants ───────────────────────────────────────────
    ind_cid, rec_cid = 0, 27                 # Nat, Nat.rec
    dec_rec = decode_env_meta(b, rec_cid)
    exp_rec = _expected("Nat.rec", dump["Nat.rec"]["meta"], cid=rec_cid)
    if dec_rec["major_idx"] != exp_rec["major_idx"]:
        fails.append(f"[D] major_idx {dec_rec['major_idx']} != "
                     f"{exp_rec['major_idx']}")
    # rule ctor sequence == inductive ctors sorted by cidx
    ctors = dump["Nat"]["meta"]["ctors"]
    by_cidx = sorted(ctors, key=lambda c: dump[c]["meta"]["cidx"])
    rule_order = [r["ctor"] for r in dec_rec["rules"]]
    if rule_order != by_cidx:
        fails.append(f"[D] Nat.rec rule order {rule_order} != by-cidx {by_cidx}")
    # Bool ctors false-then-true, cidx 0/1, decoded same
    dec_bool = decode_env_meta(b, 1)
    if dec_bool["ctors"] != ["Bool.false", "Bool.true"]:
        fails.append(f"[D] Bool ctors {dec_bool['ctors']}")
    if decode_env_meta(b, 3)["cidx"] != 0 or decode_env_meta(b, 2)["cidx"] != 1:
        fails.append("[D] Bool cidx false!=0/true!=1")

    # ── E: §5.2 casesOn kinds are Definition (TBD#4) ────────────────────────
    for name, cid in (("Nat.casesOn", 30), ("P2.casesOn", 31),
                      ("Bool.casesOn", 32)):
        d = decode_env_meta(b, cid)
        if d["kind"] != CK_DEFINITION:
            fails.append(f"[E {name}] kind {d['kind']} != Definition({CK_DEFINITION})")
        if d["kind"] == CK_RECURSOR:
            fails.append(f"[E {name}] fabricated Recursor kind")
        if d["hints_kind"] != 1 or d["safety"] != 1:
            fails.append(f"[E {name}] hints {d['hints_kind']} safety {d['safety']}")
        if dump[name]["meta"]["kind"] != CK_DEFINITION:
            fails.append(f"[E {name}] real dump kind != Definition")
    print(f"E  casesOn kinds: {[decode_env_meta(b, c)['kind'] for c in (30,31,32)]} "
          f"(Definition={CK_DEFINITION})")

    # ── F: supplementary Bool.rec / Quot bundles from the same real dump ────
    bool_consts = [("Bool", _DUMMY_TY, None), ("Bool.false", _DUMMY_TY, None),
                   ("Bool.true", _DUMMY_TY, None), ("Bool.rec", _DUMMY_TY, None)]
    bool_meta = _meta_for(bool_consts, dump)
    benc = Encoder(bool_consts, const_meta=bool_meta)
    brec = decode_env_meta(benc.b, 3)
    exp_bool_rules = dump["Bool.rec"]["meta"]["rules"]
    if [r["ctor"] for r in brec["rules"]] != ["Bool.false", "Bool.true"]:
        fails.append(f"[F] Bool.rec rules {[r['ctor'] for r in brec['rules']]}")
    if [r["ctor"] for r in exp_bool_rules] != ["Bool.false", "Bool.true"]:
        fails.append(f"[F] real Bool.rec rules {[r['ctor'] for r in exp_bool_rules]}")
    for r in brec["rules"]:
        if r["rhs"] is None:
            fails.append(f"[F] Bool.rec rule {r['ctor']} rhs not encoded")

    quot_consts = [("Quot", _DUMMY_TY, None), ("Quot.mk", _DUMMY_TY, None),
                   ("Quot.lift", _DUMMY_TY, None), ("Quot.ind", _DUMMY_TY, None)]
    qenc = Encoder(quot_consts, const_meta=_meta_for(quot_consts, dump))
    got_q = [decode_env_meta(qenc.b, c)["quot_kind"] for c in range(4)]
    exp_q = [dump[n]["meta"]["quotKind"] for n in
             ("Quot", "Quot.mk", "Quot.lift", "Quot.ind")]
    if got_q != exp_q:
        fails.append(f"[F] Quot kinds {got_q} != real {exp_q}")
    print(f"F  Bool.rec rules={[r['ctor'] for r in brec['rules']]}, "
          f"Quot kinds={got_q}")

    # ── G: §5.3 mutations disagree with the real values ─────────────────────
    # G1: corrupt P2.mk nfields (E2) from 2 to 1
    mk_cid = 18
    p = _meta_tokens(b, mk_cid, T_ENV_CTORVAL)[0]
    t = b.stream[p]
    b.stream[p] = (t[0], t[1], t[2], t[3], t[4], 1, t[6])
    d = decode_env_meta(b, mk_cid)
    if d["nfields"] == dump["P2.mk"]["meta"]["nfields"]:
        fails.append("[G1] corrupted nfields not observed")
    b.stream[p] = t                                   # restore

    # G2: change Nat.casesOn kind to Recursor (conflicts with real Definition)
    cs_anchor = b.env_anchor(30)
    a0 = b.stream[cs_anchor]
    b.stream[cs_anchor] = (a0[0], a0[1], CK_RECURSOR, a0[3], a0[4], 0, 0)
    if decode_env_meta(b, 30)["kind"] == dump["Nat.casesOn"]["meta"]["kind"]:
        fails.append("[G2] corrupted kind not observed")
    b.stream[cs_anchor] = a0

    # G3: rule ctor replaced by a nonexistent cid → decoded ctor unknown
    extra = _meta_tokens(b, rec_cid, T_ENV_RECEXTRA)[0]
    rp = b.stream[extra][3]                           # V2 = rules head
    rt = b.stream[rp]
    b.stream[rp] = (rt[0], rt[1], 4095, rt[3], rt[4], rt[5], rt[6])
    if decode_env_meta(b, rec_cid)["rules"][0]["ctor"] is not None:
        fails.append("[G3] corrupted rule ctor not observed")
    b.stream[rp] = rt

    # ── report ──────────────────────────────────────────────────────────────
    for msg in fails:
        print(f"  [FAIL] {msg}")
    print(f"\n=== WP1 ENV metadata: {len(fails)} failures ===")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
