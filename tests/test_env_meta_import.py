"""WP1 metadata channel — import a REAL olean environment and round-trip it.

Prerequisite TBD#1 (docs/VM_SPEC.md §13.7 item 1): `reference/olean_export.
import_env` is the M4 executable slice — it prunes at TOY_NAMES, accepts only
kind ∈ {def, ctor, ind} (Recursor rejected), and returns no declaration
metadata. This test exercises the additive channel `import_env_meta` /
`const_meta_for` / `const_meta_entry`, which convert a real Environment dump
(every ConstantInfo kind, Recursor included) into a constant list plus a
cid-keyed Encoder `const_meta` (docs/ENV_FORMAT.md §2.3-§2.7).

The dump declares one constant of every kind so the whole H group is covered:

  axiom M_ax, def M_def, theorem M_thm, opaque M_op,
  inductive MTree (leaf/node) + MTree.rec, structure MPair + MPair.rec,
  plus Lean-core Bool/Nat/List/Quot with their constructors and recursors.

Every expected value comes from the real lean binary (Environment.find? via
reference.olean_export.dump_env) — nothing is hand-written. The decoded
fields are compared per kind, including Recursor rules (ctor/nfields/rhs) and
Inductive ctors ordering.

Coverage:
  A. channel shape: all 8 kinds, cid-keyed meta, ctors/structs agree with dump
  B. per-cid decode_env_meta vs real-lean expected (all constants, all kinds)
  C. Recursor: rule order == cidx order, nfields, rhs, major_idx, is_k
  D. Inductive: ctors order/all/flags; Constructor: cidx/induct/nfields;
     Quot: quot_kind
  E. idempotence (encode -> decode -> re-encode byte-identical)
  F. Recursor rejection lifted: import_env still rejects rec; channel accepts
  G. import_env backward compatibility (test_olean_export corpus shape)

Run: OMP_NUM_THREADS=4 python3 tests/test_env_meta_import.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_TESTS))

from expr.tokens import (
    Encoder, decode_env_meta,
    CK_AXIOM, CK_DEFINITION, CK_THEOREM, CK_OPAQUE, CK_QUOT,
    CK_INDUCTIVE, CK_CONSTRUCTOR, CK_RECURSOR,
)
from reference.olean_export import (
    dump_env, import_env, import_env_meta, const_meta_for, const_meta_entry,
    ExportError,
)
from reference.toy_env import TOY_CONSTS

# `_expected` / `_cmp` independently compute the §2.3 decoded view from the
# real dump; reusing the WP1 oracle keeps both tests on one definition.
import test_env_meta as tem
# test_olean_export owns the M4 executable-slice corpus; reuse its inputs to
# assert the legacy import path still behaves identically.
from test_olean_export import TARGET_DEFS, ROOTS as OE_ROOTS

# ── real environment under test (one constant per ConstantInfo kind) ─────────
DEFS = """\
axiom M_ax : Nat
def M_def : Nat := 0
theorem M_thm : M_def = 0 := rfl
opaque M_op : Nat
inductive MTree where
  | leaf : MTree
  | node : MTree -> MTree -> MTree
structure MPair where mk :: (a : Nat) (b : Bool)
"""
ROOTS = ["M_ax", "M_def", "M_thm", "M_op", "MTree", "MTree.rec",
         "MPair", "MPair.rec", "List", "List.rec", "Nat.rec", "Bool.rec",
         "Quot", "Quot.mk", "Quot.lift", "Quot.ind"]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.n = 0

    def ok(self, cond: bool, msg: str) -> bool:
        self.n += 1
        if not cond:
            self.fails.append(msg)
        return bool(cond)

    def eq(self, got, exp, msg: str) -> bool:
        return self.ok(got == exp, f"{msg}: got={got!r} real={exp!r}")


def main() -> int:
    c = Checker()

    # ── 0. one real-lean dump for the whole run ─────────────────────────────
    dump = dump_env(DEFS, ROOTS, path="/tmp/vm_env_meta_import.lean")
    kinds = sorted({e["meta"]["kind"] for e in dump.values()})
    print(f"real-lean dump: {len(dump)} constants, kinds={kinds}")
    c.eq(kinds, list(range(8)),
         "all 8 constant_info_kinds must be present in the dump")

    # ── A. channel shape ────────────────────────────────────────────────────
    n0 = c.n
    consts, ctors, structs, meta = import_env_meta("", [], dump=dump)
    names = [n for n, _, _ in consts]
    c.eq(names, sorted(dump), "[A] consts order")
    c.eq(sorted(meta), list(range(len(consts))), "[A] const_meta cids")
    c.eq(consts, [(n, dump[n]["ty"], dump[n]["val"]) for n in sorted(dump)],
         "[A] consts types/values verbatim from the dump")
    c.eq(ctors, {n for n, e in dump.items() if e["kind"] == "ctor"},
         "[A] ctors set")
    exp_structs = {}
    for n, e in dump.items():
        if e["kind"] == "ind" and e["ind"] and e["ind"].get("isStruct"):
            exp_structs[n] = (e["ind"]["ctors"][0], e["ind"]["np"], e["ind"]["nf"])
    c.eq(structs, exp_structs, "[A] structs map")
    # const_meta constructed independently via const_meta_for lines up
    c.eq(const_meta_for(consts, dump), meta, "[A] const_meta_for == channel")
    for n in ("M_ax", "M_def", "M_thm", "M_op"):
        c.ok(n in names, f"[A] {n} missing (declared constant)")
    for n in ("MTree", "MTree.leaf", "MTree.node", "MTree.rec",
              "MPair", "MPair.mk", "MPair.rec", "List", "List.cons",
              "List.nil", "List.rec", "Nat", "Nat.rec", "Bool", "Bool.rec",
              "Quot", "Quot.mk", "Quot.lift", "Quot.ind"):
        c.ok(n in names, f"[A] {n} missing from channel")
    print(f"A  channel shape: all 8 kinds, {len(consts)} cids, "
          f"{len(ctors)} ctors, structs={sorted(structs)} "
          f"({c.n - n0} checks)")

    # ── B. per-cid decode_env_meta vs independent real-lean expected ────────
    n0 = c.n
    enc = Encoder(consts, is_ctor=ctors, const_meta=meta)
    bad_cids = set()
    for cid, name in enumerate(names):
        dec = decode_env_meta(enc.b, cid)
        m, up = dump[name]["meta"], list(dump[name]["up"])
        exp = tem._expected(name, m, cid=cid, univ_arity=len(up))
        before = len(c.fails)
        tem._cmp(dec, exp, f"[B cid={cid} {name}]", c.fails)
        if dec["lparams"] != up:
            c.fails.append(f"[B cid={cid} {name}] lparams decoded="
                           f"{dec['lparams']} real={up}")
        c.n += 1
        if len(c.fails) > before:
            bad_cids.add(cid)
    print(f"B  per-cid round-trip vs real dump: "
          f"{len(consts) - len(bad_cids)}/{len(consts)} cids clean "
          f"({c.n - n0} checks)")

    # ── C. Recursor specifics ───────────────────────────────────────────────
    n0 = c.n
    for cid, name in enumerate(names):
        m = dump[name]["meta"]
        if m["kind"] != CK_RECURSOR:
            continue
        dec = decode_env_meta(enc.b, cid)
        real_rules = m["rules"]
        rule_order = [r["ctor"] for r in dec["rules"]]
        # real rule order must equal ctors sorted by cidx (iota minor order)
        ind_name = m["all"][0]
        ind_ctors = dump[ind_name]["meta"]["ctors"]
        by_cidx = sorted(ind_ctors, key=lambda c: dump[c]["meta"]["cidx"])
        c.eq(rule_order, [r["ctor"] for r in real_rules],
             f"[C {name}] decoded rule order")
        c.eq(rule_order, by_cidx, f"[C {name}] rule order vs cidx order")
        c.eq([r["nfields"] for r in dec["rules"]],
             [r["nfields"] for r in real_rules], f"[C {name}] rule nfields")
        c.eq([r["rhs"] for r in dec["rules"]],
             [r["rhs"] for r in real_rules], f"[C {name}] rule rhs")
        c.eq(dec["major_idx"], m["np"] + m["ni"] + m["nm"] + m["nmin"],
             f"[C {name}] major_idx")
        c.eq(dec["is_k"], m["isK"], f"[C {name}] is_k")
        c.eq(dec["is_recursor"], True, f"[C {name}] is_recursor flag")
        c.eq(len(dec["rules"]), len(ind_ctors),
             f"[C {name}] one rule per inductive ctor")
    rec_names = [n for n in names if dump[n]["meta"]["kind"] == CK_RECURSOR]
    print(f"C  Recursor rules: {rec_names} ({c.n - n0} checks)")

    # ── D. Inductive / Constructor / Quot specifics ─────────────────────────
    n0 = c.n
    seq = ["MTree", "List", "Nat", "Bool", "MPair"]
    for name in seq:
        cid = names.index(name)
        dec = decode_env_meta(enc.b, cid)
        real_ctors = dump[name]["meta"]["ctors"]
        c.eq(dec["ctors"], real_ctors, f"[D {name}] ctors from dump")
        # declaration order == increasing cidx (ENV_FORMAT §2.6 invariant)
        cidx = [dump[c]["meta"]["cidx"] for c in real_ctors]
        c.eq(cidx, sorted(cidx), f"[D {name}] real ctors are cidx-ordered")
        c.eq([dump[c]["meta"]["cidx"] for c in dec["ctors"]], cidx,
             f"[D {name}] decoded ctors cidx order")
        c.eq(dec["all"], dump[name]["meta"]["all"], f"[D {name}] all")
        c.eq(dec["is_inductive"], True, f"[D {name}] is_inductive flag")
        c.eq(dec["is_rec"], dump[name]["meta"]["isRec"], f"[D {name}] is_rec")
        c.eq(dec["is_reflexive"], dump[name]["meta"]["isRefl"],
             f"[D {name}] is_reflexive")
    for name in ("MTree.leaf", "MTree.node", "MPair.mk", "List.cons"):
        cid = names.index(name)
        dec = decode_env_meta(enc.b, cid)
        m = dump[name]["meta"]
        c.eq(dec["induct"], m["induct"], f"[D {name}] induct")
        c.eq(dec["cidx"], m["cidx"], f"[D {name}] cidx")
        c.eq(dec["nparams"], m["np"], f"[D {name}] nparams")
        c.eq(dec["nfields"], m["nfields"], f"[D {name}] nfields")
        c.eq(dec["is_ctor"], True, f"[D {name}] is_ctor flag")
    for name in ("Quot", "Quot.mk", "Quot.lift", "Quot.ind"):
        dec = decode_env_meta(enc.b, names.index(name))
        c.eq(dec["quot_kind"], dump[name]["meta"]["quotKind"],
             f"[D {name}] quot_kind")
        c.eq(dec["is_quot"], True, f"[D {name}] is_quot flag")
    # scalar kinds recorded in T_ENV anchor V1
    for cid, name in enumerate(names):
        c.eq(enc.b.const_kind[cid], dump[name]["meta"]["kind"],
             f"[D {name}] T_ENV_META.V1 kind")
    print(f"D  Inductive/Constructor/Quot fields ({c.n - n0} checks)")

    # ── E. idempotence ──────────────────────────────────────────────────────
    n0 = c.n
    enc2 = Encoder(consts, is_ctor=ctors, const_meta=const_meta_for(consts, dump))
    c.ok(enc2.b.stream == enc.b.stream, "[E] re-encode stream differs")
    for cid in range(len(consts)):
        c.eq(decode_env_meta(enc2.b, cid), decode_env_meta(enc.b, cid),
             f"[E cid={cid}] decode after re-encode")
    print(f"E  idempotence ({c.n - n0} checks)")

    # ── F. Recursor rejection lifted in the metadata channel ────────────────
    n0 = c.n
    try:
        import_env("", ["List.rec"], dump=dump)
        c.ok(False, "[F] import_env accepted a Recursor root (regression)")
    except ExportError:
        c.ok(True, "[F] import_env still rejects Recursor")
    rec_cid = names.index("Nat.rec")
    dec_rec = decode_env_meta(enc.b, rec_cid)
    c.eq(dec_rec["kind"], CK_RECURSOR, "[F] channel decoded Nat.rec kind")
    c.ok(bool(dec_rec["rules"]), "[F] channel carries Nat.rec rules")
    # channel accepts a non-toy Recursor that import_env rejects
    listrec_cid = names.index("List.rec")
    c.eq(decode_env_meta(enc.b, listrec_cid)["kind"], CK_RECURSOR,
         "[F] channel decoded List.rec kind")
    # const_meta_entry accepts all 8 kinds (no kind filter)
    c.eq({e["kind"] for e in meta.values()}, set(range(8)),
         "[F] channel metadata covers all kinds")
    print(f"F  Recursor rejection lifted ({c.n - n0} checks)")

    # ── G. import_env backward compatibility (M4 executable slice) ──────────
    n0 = c.n
    bc = import_env(TARGET_DEFS, OE_ROOTS)
    c.ok(isinstance(bc, tuple) and len(bc) == 3,
         "[G] import_env must still return a 3-tuple")
    bc_consts, bc_ctors, bc_structs = bc
    c.eq(tuple(bc_consts[:len(TOY_CONSTS)]), tuple(TOY_CONSTS),
         "[G] TOY_CONSTS prefix/cids unchanged")
    toy_names = {n for n, _, _ in TOY_CONSTS}
    for cid, (n, _, _) in enumerate(bc_consts):
        if n not in toy_names:
            c.ok(cid >= len(TOY_CONSTS),
                 f"[G] exported {n} got cid {cid} < {len(TOY_CONSTS)}")
    bc_names = {n for n, _, _ in bc_consts}
    c.ok(set(OE_ROOTS) <= bc_names, "[G] all E_* roots exported")
    c.ok("E_pair" in bc_structs and "E_pair.mk" in bc_ctors,
         "[G] E_pair structure/ctor exported")
    bc_enc = Encoder(bc_consts, is_ctor=bc_ctors)
    c.ok(len(bc_enc.b.stream) > len(bc_consts),
         "[G] legacy export still encodes an empty-meta stream")
    print(f"G  import_env backward compatibility ({c.n - n0} checks)")

    # ── report ──────────────────────────────────────────────────────────────
    for msg in c.fails:
        print(f"  [FAIL] {msg}")
    print(f"\n=== WP1 metadata channel (import_env_meta): "
          f"{len(c.fails)} failures / {c.n} checks ===")
    return 0 if not c.fails else 1


if __name__ == "__main__":
    sys.exit(main())
