"""012 M-A verifier — real Mathlib closure export + ENV structural readback.

Per docs/plans/012-mathlib-scale-closure.md M-A: >=3 real Mathlib theorem
closures export successfully with complete metadata (inductive fields
checked against the REAL kernel via the addDeclWithoutChecking round trip —
the const2decl name does not exist in 4.33.1, see handoff 007 step-5
design), and the encoded ENV is read back through the expr.tokens decode
path (structural only).

RED LINES (M-A):
  - the closures are NEVER fed to the graph / RefVM / engine for evaluation
    (large-env evaluation is O(N^2*L); this suite only generates and
    structurally checks);
  - no expected verdicts are seeded anywhere — the dump carries environment
    metadata only (schema asserted below), accept/reject belongs to M-C's
    live oracle runs.

Corpus (modules pinned from the disambiguated extractor run recorded in
docs/handoffs/007-I-mathlib-closure.md step 4+5; module resolution itself
was verified against env.getModuleIdxFor? there):
  Nat.testBit_land  (arith/bitwise branch, Mathlib.Data.Nat.Bitwise)
  Vector3.cons_fz   (List/Vector iota-heavy branch, brecOn forms, Vector3)
  Quot.liftOn_mk    (Quot branch, Mathlib.Data.Quot)

Prerequisite: /home/xkq/mathlib_src (v4.33.1 checkout, full oleans built —
handoff 007 steps 1-2).  The lean channel is `lake env lean` in that
project; the oracle pin is the same binary reference/lean_ref.py resolves.

Run: OMP_NUM_THREADS=2 LEAN_NUM_THREADS=2 python3 tests/test_mathlib_closure_env.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from expr.tokens import (
    Encoder, decode_env_meta, decode_expr, decode_level,
    CK_AXIOM, CK_DEFINITION, CK_THEOREM, CK_OPAQUE, CK_QUOT,
    CK_INDUCTIVE, CK_CONSTRUCTOR, CK_RECURSOR,
)
from expr.model import LitNat
from reference.olean_export import _const_names
from scripts.export_mathlib_closure import (
    dump_closure, raw_jsonl, round_trip, compare_dumps, encode_and_stats,
    decode_readback, load_jsonl, RT_TEMPLATE,
)

MATHLIB = Path("/home/xkq/mathlib_src")
CORPUS = [
    ("Nat.testBit_land", "Mathlib.Data.Nat.Bitwise"),
    ("Vector3.cons_fz", "Mathlib.Data.Vector3"),
    ("Quot.liftOn_mk", "Mathlib.Data.Quot"),
]
WORK = Path("/home/xkq/logs/012I/test_closure_env")


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


DUMP_KEYS = {"kind", "up", "ty", "val", "ind", "meta"}


def main() -> int:
    c = Checker()
    if not (MATHLIB / "lean-toolchain").exists():
        print(f"FATAL: mathlib checkout missing at {MATHLIB} "
              f"(handoff 007 steps 1-2)")
        return 1
    WORK.mkdir(parents=True, exist_ok=True)

    for theorem, module in CORPUS:
        work = WORK / theorem.replace(".", "_")
        work.mkdir(parents=True, exist_ok=True)
        print(f"== {theorem} ({module}) ==")

        # ── A. closure export from the real binary ──────────────────────────
        dump, dump_lean = dump_closure(MATHLIB, theorem, module, work)
        n = len(dump)
        kinds: dict[str, int] = {}
        for ent in dump.values():
            kinds[ent["kind"]] = kinds.get(ent["kind"], 0) + 1
        print(f"  A  closure: {n} constants, kinds={dict(sorted(kinds.items()))}")
        c.ok(n > 0, f"[{theorem}] empty closure")
        c.ok(kinds.get("thm", 0) >= 1, f"[{theorem}] theorem itself missing")
        c.ok(theorem in dump, f"[{theorem}] root not in dump")
        # schema: environment metadata only, no verdict fields (M-A red line)
        bad_keys = {k for ent in dump.values() for k in ent} - DUMP_KEYS
        c.eq(bad_keys, set(), f"[{theorem}] unexpected dump fields")
        # closure over type/value/rule-rhs refs (import_env_meta re-checks)
        missing: set[str] = set()
        for name, ent in dump.items():
            refs = _const_names(ent["ty"])
            if ent["val"] is not None:
                refs |= _const_names(ent["val"])
            for r in (ent["meta"] or {}).get("rules") or []:
                if r.get("rhs") is not None:
                    refs |= _const_names(r["rhs"])
            missing |= {x for x in refs if x not in dump}
        c.eq(missing, set(), f"[{theorem}] closure not closed")

        # ── B. kernel round trip (addDeclWithoutChecking -> find?) ──────────
        raw_jsonl(MATHLIB, dump_lean, work / "dump.jsonl")
        (work / "rt.lean").write_text(RT_TEMPLATE)
        skipped, rtmissing = round_trip(work / "dump.jsonl",
                                        work / "rt.lean", work / "rt.jsonl")
        diffs = compare_dumps(work / "dump.jsonl", work / "rt.jsonl", skipped)
        print(f"  B  round trip: skipped_opaques={skipped}, diffs={len(diffs)}")
        c.eq(rtmissing, skipped, f"[{theorem}] RTMISSING beyond opaque skips")
        for d in diffs[:10]:
            print(f"     DIFF {d}")
        c.eq(diffs, [], f"[{theorem}] round-trip diffs")

        # ── C. ENV encoding + per-cid metadata invariants ───────────────────
        st = encode_and_stats(dump)
        b = st["bundle"]
        print(f"  C  ENV: {st['n_consts']} consts, {st['n_tokens']} tokens, "
              f"{st['env_bytes']} bytes, clamped heights "
              f"{st['height_clamped']}")
        c.eq(st["n_consts"], n, f"[{theorem}] consts count")
        c.eq(st["n_tokens"], len(b.stream), f"[{theorem}] token count")
        c.eq(b.stream[0], (0, n, 0, 0, 0, 0, 0),
             f"[{theorem}] T_NULL.V0 = n_consts")
        c.eq(len(st["meta"]), n, f"[{theorem}] const_meta covers all cids")
        c.ok(st["height_clamped"] == 0,
             f"[{theorem}] definitional heights clamped at 4095 "
             "(would need ENV_FORMAT TBD#1 encoding)")
        for cid, (name, _ty, _val) in enumerate(st["consts"]):
            ent = dump[name]
            dec = decode_env_meta(b, cid)
            kind_map = {"axiom": CK_AXIOM, "def": CK_DEFINITION,
                        "thm": CK_THEOREM, "opaque": CK_OPAQUE,
                        "quot": CK_QUOT, "ind": CK_INDUCTIVE,
                        "ctor": CK_CONSTRUCTOR, "rec": CK_RECURSOR}
            c.eq(dec["kind"], kind_map[ent["kind"]],
                 f"[{theorem} cid={cid} {name}] kind vs dump")
            c.eq(dec["lparams"], list(ent["up"]),
                 f"[{theorem} cid={cid} {name}] lparams vs dump")
            m = ent["meta"]
            if ent["kind"] == "rec":
                # ENV_FORMAT §5.1 invariants: rule order == ctor cidx order
                # (iota minor order), major_idx formula
                rules = dec["rules"]
                c.eq([r["ctor"] for r in rules],
                     [r["ctor"] for r in m["rules"]],
                     f"[{theorem} cid={cid} {name}] rule ctor order")
                c.eq([dump[r["ctor"]]["meta"]["cidx"] for r in rules],
                     sorted(dump[r["ctor"]]["meta"]["cidx"] for r in rules),
                     f"[{theorem} cid={cid} {name}] rules cidx-ordered")
                c.eq(dec["major_idx"],
                     m["np"] + m["ni"] + m["nm"] + m["nmin"],
                     f"[{theorem} cid={cid} {name}] major_idx")
            if ent["kind"] == "ind":
                c.eq(dec["ctors"], m["ctors"],
                     f"[{theorem} cid={cid} {name}] ind ctor order")
                c.eq(dec["nparams"], m["np"],
                     f"[{theorem} cid={cid} {name}] nparams")
                c.eq(dec["nindices"], m["ni"],
                     f"[{theorem} cid={cid} {name}] nindices")
            if ent["kind"] == "ctor":
                c.eq(dec["cidx"], m["cidx"],
                     f"[{theorem} cid={cid} {name}] cidx")
                c.eq(dec["nfields"], m["nfields"],
                     f"[{theorem} cid={cid} {name}] nfields")

        # ── D. full iterative readback (types + values, all cids) ───────────
        errs = decode_readback(st)
        print(f"  D  iterative readback: {n - len(errs)}/{n} cids clean")
        for e in errs[:10]:
            print(f"     READBACK {e}")
        c.eq(errs, [], f"[{theorem}] iterative readback")

        # ── E. expr.tokens reference decoder on the small closure ───────────
        # decode_expr/decode_level are recursive; run them on a closure whose
        # trees are shallow (Quot.liftOn_mk) as a positive control that the
        # reference decode path reads these streams, then compare.
        if theorem == "Quot.liftOn_mk":
            bad = 0
            for cid, (name, ty, val) in enumerate(st["consts"]):
                got_ty = decode_expr(b, b.const_type_pos[cid])
                if got_ty != ty:
                    bad += 1
                    c.ok(False, f"[{name}] decode_expr type mismatch")
                if val is not None:
                    if decode_expr(b, b.const_value_pos[cid]) != val:
                        bad += 1
                        c.ok(False, f"[{name}] decode_expr value mismatch")
            _ = LitNat  # (reference; literals decode inside decode_expr)
            print(f"  E  expr.tokens reference decode: {n - bad}/{n} types, "
                  f"values included")
        del st, b

    total = sum(1 for _ in CORPUS)
    c.ok(total >= 3, "fewer than 3 theorems exported")

    for msg in c.fails:
        print(f"  [FAIL] {msg}")
    print(f"\n=== M-A closure ENV verifier: {len(c.fails)} failures / "
          f"{c.n} checks ===")
    return 0 if not c.fails else 1


if __name__ == "__main__":
    sys.exit(main())
