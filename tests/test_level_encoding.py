"""WP2a — level/universe *token encoding* round-trip vs real lean.

This is the ENCODING half of level support only. The semantics package
(normalize / is_equivalent / is_geq / instantiate / check_level and the
graph operations) is a separate later work package and is NOT implemented or
tested here. What must hold: polymorphic declarations are encodable and
round-trippable.

Encoding implemented per docs/VM_SPEC.md §12.1:
  - a dedicated metadata token ``T_ENV_UNIVPARAMS`` (K=39) hangs off each
    constant's per-cid F2 metadata chain and points (V1) at the head of a
    ``T_ENV_LIST`` (K=35, role=2) chain holding the ordered LevelParam names;
  - the ordered names come from the real kernel and their count equals
    ``T_ENV_META.V0`` (univ_arity);
  - Const level arguments use ``K_CONST.V1`` as the first level-subtree root,
    with the remaining roots chained through the root level node's ``X``
    (VM_SPEC §4/§12.1, ENV_FORMAT §2.7 position addressing).

Expected values are NEVER hand-written: every expected name, arity and
level term is produced by dumping the real declaration source with the real
lean binary (``~/.elan/bin/lean``, 4.33.1) through
``reference.olean_export.dump_env``. Per VM_SPEC §12.5(C) the polymorphic
declarations live in this test file, not in reference/toy_env.py.

Run: OMP_NUM_THREADS=4 python3 tests/test_level_encoding.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.model import Const, LMax, LSucc, LZero, LParam
from expr.tokens import (
    Encoder, decode_env_meta, decode_expr,
    T_ENV_LIST, T_ENV_UNIVPARAMS, T_ENV_META,
    ENV_LIST_UNIVPARAMS,
    CK_AXIOM, CK_DEFINITION,
)
from reference.olean_export import dump_env

# ── real polymorphic declaration source (verified shapes, VM_SPEC §12.5(B)) ──
# Multi-param annotation requires the comma: `Poly.{u, v}`.
POLY_DEFS = """\
axiom A.{u} : Sort u
def B : Sort 1 := A.{1}
def C.{u} : Sort (imax 1 u) := A.{u}
def D.{u} : Sort (max u 1) := A.{max 1 u}
axiom Poly.{u, v} : Sort (max (u+1) (v+1))
"""
POLY_NAMES = ["A", "B", "C", "D", "Poly"]
# B is deliberately monomorphic: it is the concrete use-site A.{1}.
POLY_PARAM_NAMES = ["A", "C", "D", "Poly"]
_KIND = {"axiom": CK_AXIOM, "def": CK_DEFINITION}


def _consts(dump: dict) -> list:
    return [(n, dump[n]["ty"], dump[n]["val"]) for n in POLY_NAMES]


def _const_meta(dump: dict) -> dict[int, dict]:
    """{cid: Encoder const_meta} with the ordered real LevelParam names."""
    out = {}
    for cid, n in enumerate(POLY_NAMES):
        e = dump[n]
        m: dict = {"kind": _KIND[e["kind"]], "lparams": list(e["up"])}
        if e["kind"] == "def":
            mm = e["meta"]
            m.update(hints=mm["hints"], height=mm["height"],
                     safety=mm["safety"], is_unsafe=mm["isUnsafe"],
                     all=mm["all"])
        else:
            m.update(is_unsafe=e["meta"]["isUnsafe"],
                     all=e["meta"].get("all", []))
        out[cid] = m
    return out


def _meta_chain(b, cid: int) -> list[int]:
    out, p = [], b.stream[b.env_anchor(cid)][3]
    while p:
        out.append(p)
        p = b.stream[p][6]
    return out


def _level_chain(b, const_pos: int) -> list[int]:
    """Root positions of a K_CONST's level-argument sibling chain."""
    K, V0, V1, _V2, _X, _E2, _F2 = b.stream[const_pos]
    assert K == 5, f"expected K_CONST at {const_pos}, got K={K}"
    roots, r = [], V1
    while r:
        roots.append(r)
        r = b.stream[r][4]          # X = next level root
    return roots


def main() -> int:
    n_fail = 0
    fails: list[str] = []

    # ── real-lean dump: the sole source of expected values ──────────────────
    dump = dump_env(POLY_DEFS, POLY_NAMES)
    print(f"real-lean dump: {len(dump)} constants (roots={POLY_NAMES})")
    for n in POLY_NAMES:
        print(f"  {n:5s} kind={dump[n]['kind']:5s} up={dump[n]['up']}")
    for n in POLY_PARAM_NAMES:
        assert dump[n]["up"], f"{n}: no LevelParams in real dump (test shape)"

    consts = _consts(dump)
    meta = _const_meta(dump)
    enc = Encoder(consts, const_meta=meta)
    b = enc.b

    # ── A: univ_arity + ordered lparams names vs real LevelParams ───────────
    for cid, n in enumerate(POLY_NAMES):
        if n not in POLY_PARAM_NAMES:
            continue
        real_up = list(dump[n]["up"])
        dec = decode_env_meta(b, cid)
        if dec["univ_arity"] != len(real_up):
            fails.append(f"[A {n}] univ_arity {dec['univ_arity']} != "
                         f"real {len(real_up)}")
        if dec["lparams"] != real_up:
            fails.append(f"[A {n}] lparams {dec['lparams']} != real {real_up}")
        if b.const_univ_arity[cid] != len(real_up):
            fails.append(f"[A {n}] bundle const_univ_arity "
                         f"{b.const_univ_arity[cid]} != real {len(real_up)}")
        if b.stream[b.env_anchor(cid)][1] != len(real_up):
            fails.append(f"[A {n}] T_ENV_META.V0 "
                         f"{b.stream[b.env_anchor(cid)][1]} != real "
                         f"{len(real_up)}")
    print("A  univ_arity + ordered lparams names vs real LevelParams")

    # ── B: exact token shape (K=39 + T_ENV_LIST role=2) ─────────────────────
    for cid, n in enumerate(POLY_NAMES):
        if n not in POLY_PARAM_NAMES:
            continue
        chain = _meta_chain(b, cid)
        ups = [p for p in chain if b.stream[p][0] == T_ENV_UNIVPARAMS]
        if len(ups) != 1:
            fails.append(f"[B {n}] expected one K=39 token, got {len(ups)}")
            continue
        upos = ups[0]
        _K, V0, V1 = b.stream[upos][:3]
        if V0 != cid:
            fails.append(f"[B {n}] T_ENV_UNIVPARAMS.V0 {V0} != cid {cid}")
        lhead = V1
        if not lhead or b.stream[lhead][0] != T_ENV_LIST:
            fails.append(f"[B {n}] V1 {lhead} is not a T_ENV_LIST node")
            continue
        if b.stream[lhead][3] != ENV_LIST_UNIVPARAMS:
            fails.append(f"[B {n}] list role {b.stream[lhead][3]} != "
                         f"{ENV_LIST_UNIVPARAMS}")
        # walk the name chain and compare to the ordered real names
        names, p, seen = [], lhead, set()
        while p:
            if p in seen:
                fails.append(f"[B {n}] list cycle")
                break
            seen.add(p)
            names.append(b.id_names[b.stream[p][2]])
            p = b.stream[p][4]
        if names != list(dump[n]["up"]):
            fails.append(f"[B {n}] chain names {names} != real "
                         f"{list(dump[n]['up'])}")
    print("B  T_ENV_UNIVPARAMS(K=39) + T_ENV_LIST(role=2) chain shape")

    # ── C: Const level-argument sibling chain round-trips exactly ───────────
    #  (a) declaration types/values decoded == real dump Exprs
    for cid, n in enumerate(POLY_NAMES):
        got_ty = decode_expr(b, b.const_type_pos[cid])
        if got_ty != dump[n]["ty"]:
            fails.append(f"[C {n}.type] {got_ty} != real {dump[n]['ty']}")
        vpos = b.const_value_pos[cid]
        real_val = dump[n]["val"]
        if real_val is not None:
            got_val = decode_expr(b, vpos)
            if got_val != real_val:
                fails.append(f"[C {n}.value] {got_val} != real {real_val}")
    #  (b) explicit use-site terms: A.{1} (B.value, ground) and
    #      A.{max 1 u} (D.value, param-bearing max), encoded standalone.
    for n, want in (("B", Const("A", (LSucc(LZero()),))),
                    ("D", Const("A", (LMax(LSucc(LZero()), LParam("u")),)))):
        real = dump[n]["val"]
        if real != want:
            fails.append(f"[C {n}.real] real {real} != expected shape {want}")
        pos = enc.encode_term(real)
        got = decode_expr(b, pos)
        if got != real:
            fails.append(f"[C {n}.use-site] {got} != real {real}")
        # sibling-chain length == real level-arg count (the Const is interior
        # in B/D, so re-encode it standalone and read V1/X)
        cpos = enc.encode_term(real)
        roots = _level_chain(b, cpos)
        if len(roots) != len(real.levels):
            fails.append(f"[C {n}.shape] level root chain len {len(roots)} != "
                         f"real {len(real.levels)}")
    #  (c) multi-arg chain: Poly.{u v} — two roots linked through X
    term = Const("Poly", (LParam("u"), LParam("v")))
    pos = enc.encode_term(term)
    if decode_expr(b, pos) != term:
        fails.append(f"[C multi] {decode_expr(b, pos)} != {term}")
    if len(_level_chain(b, pos)) != 2:
        fails.append("[C multi] Poly level-arg chain length != 2")
    print("C  Const level-arg sibling chain (K_CONST.V1 + root X) round-trip")

    # ── D: default Encoder (no const_meta) is unchanged ─────────────────────
    enc0 = Encoder(consts)
    b0 = enc0.b
    if any(t[0] == T_ENV_UNIVPARAMS for t in b0.stream):
        fails.append("[D] default encoder emitted a K=39 token")
    if any(t[0] == T_ENV_LIST for t in b0.stream):
        fails.append("[D] default encoder emitted a K=35 list node")
    for cid, n in enumerate(POLY_NAMES):
        if b0.const_univ_arity[cid] != 0:
            fails.append(f"[D {n}] default arity {b0.const_univ_arity[cid]} != 0")
        d0 = decode_env_meta(b0, cid)
        if d0["univ_arity"] != 0 or d0["lparams"] != []:
            fails.append(f"[D {n}] default meta arity/lparams "
                         f"{d0['univ_arity']}/{d0['lparams']}")
        # level args still encode with no metadata (the Const token is
        # metadata-independent, VM_SPEC §4)
        if d0["kind"] != 0 or b0.stream[b0.env_anchor(cid)][0] != T_ENV_META:
            fails.append(f"[D {n}] default anchor changed")
    if decode_expr(b0, b0.const_type_pos[POLY_NAMES.index("D")]) != \
            dump["D"]["ty"]:
        fails.append("[D] default encoder changed type encoding")
    print("D  default Encoder unchanged (arity 0, no K=39/K=35)")

    # ── E: §12.1 invariant — count must equal chain length ──────────────────
    try:
        Encoder(consts, const_meta={0: {"kind": CK_AXIOM, "lparams": ["u"],
                                        "univ_arity": 2}})
        fails.append("[E] mismatched univ_arity/lparams not rejected")
    except ValueError:
        pass
    # decode-side: corrupt T_ENV_META.V0 and require decode_env_meta to reject
    anchor = b.env_anchor(0)
    saved = b.stream[anchor]
    b.stream[anchor] = (T_ENV_META, saved[1] + 1, saved[2], saved[3],
                        saved[4], saved[5], saved[6])
    try:
        decode_env_meta(b, 0)
        fails.append("[E] decode accepted univ_arity != chain length")
    except ValueError:
        pass
    b.stream[anchor] = saved
    # restored round-trip
    if decode_env_meta(b, 0)["lparams"] != list(dump["A"]["up"]):
        fails.append("[E] restore failed")
    print("E  count==chain-length invariant (encode + decode)")

    for msg in fails:
        print(f"  [FAIL] {msg}")
    print(f"\n=== WP2a level encoding: {len(fails)} failures ===")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
