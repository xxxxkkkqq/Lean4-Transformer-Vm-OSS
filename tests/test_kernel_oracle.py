"""Acceptance-oracle harness upgrade: raw-kernel #KCHECK + capacity measurement.

Two independent parts.

Part A (kernel-vs-Meta sanity). The toy environment's value-bearing
declarations are checked through BOTH:
  * the existing accept/reject oracle `lean_ref.run_check_oracle`
    (`example : T := v`, elaborator + kernel via `addDecl`); and
  * the new raw-kernel path `lean_ref.run_kcheck_oracle` (`#KCHECK`, which
    calls `Lean.Kernel.check` / `Lean.Kernel.isDefEq` directly, bypassing
    Meta), including a few deliberately ill-typed pairs so accept and reject
    are both exercised.
The two must agree on accept/reject.  Any disagreement is printed and
asserted against `ALLOWED_DIFFS` (empty: no known legitimate difference on
this corpus); an undocumented difference fails the test rather than passing
silently.

Part B (capacity, measured not asserted from theory). Representative real
declarations from Lean core and, when reachable, /tmp/mlbench Mathlib are
dumped through the real binary and measured for
  * constants in the transitive dependency closure (cid / nid fields are
    capped at 4095, VM_SPEC §2); and
  * expr nodes in the declaration's own type+value and in its whole closure
    (each node is one token; the v1 token stream is capped at 4096, §2).
For closures small enough to encode in Python, the actual token-stream
length is measured with the real `expr/tokens.py` encoder.  Closures larger
than `MAX_ENCODE_CONSTS` are not encoded (that would be slow); their
constant/node counts already exceed a documented limit.  The first
construct the v1 encoder cannot represent at all is also pinned.

Expected values are produced by the real `lean` (4.33.1, ~/.elan/bin/lean)
at run time; nothing is hand-written.

Part B's Mathlib measurements are skipped by default to bound memory (the
Matrix.mul_assoc closure is ~4.2M nodes). Set `VM_CAPACITY_MATHLIB=1` to run
the Mathlib defs/theorems, and additionally `VM_CAPACITY_BIG=1` for the
4115-constant Matrix.mul_assoc case. Recorded results: docs/ORACLE.md §5.

Run: OMP_NUM_THREADS=4 python3 tests/test_kernel_oracle.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference import lean_ref
from reference.olean_export import dump_env
from reference.toy_env import TOY_LEAN_DEFS
from expr.tokens import (
    Encoder, CK_AXIOM, CK_DEFINITION, CK_THEOREM, CK_OPAQUE, CK_QUOT,
    CK_INDUCTIVE, CK_CONSTRUCTOR, CK_RECURSOR,
)
from expr.model import App, Lam, Pi, Let, MData, Proj, Const

# ---- v1 hard limits (docs/VM_SPEC.md §2) -----------------------------------
SEQ_LIMIT = 4096      # token-stream positions / sequence length
FIELD_LIMIT = 4095    # every pointer/count field (V0/V1/V2/X), incl. cid, nid

MAX_ENCODE_CONSTS = 600   # skip Python encoding above this closure size

# Part B's Mathlib measurements are OFF by default. The Matrix.mul_assoc
# closure is ~4.2M expr nodes; materializing it in Python (a deps set per
# constant, then a second full node walk) peaks at multiple GB, and the
# Mathlib-importing lean process adds several more. That combination can OOM
# a developer machine even though it is a correct measurement. The measured
# numbers are recorded in docs/ORACLE.md; set these to 1 only when
# re-measuring on a machine with headroom.
ENABLE_MATHLIB = os.environ.get("VM_CAPACITY_MATHLIB") == "1"
ENABLE_BIG = os.environ.get("VM_CAPACITY_BIG") == "1"
# Defensive cap: never walk a dump this large unless explicitly forced.
MAX_CLOSURE_CONSTS = 1200

CK_BY_KIND = {"axiom": CK_AXIOM, "def": CK_DEFINITION, "thm": CK_THEOREM,
              "opaque": CK_OPAQUE, "quot": CK_QUOT, "ind": CK_INDUCTIVE,
              "ctor": CK_CONSTRUCTOR, "rec": CK_RECURSOR}


# ===========================================================================
# Part A — kernel vs Meta agreement on the toy environment
# ===========================================================================

# (id, type_src, val_src, note). The first six are the toy env's accepted
# value-bearing declarations (T_dbl/T_inc/T_two/T_four/T_ten/T_pair); the rest
# are ill-typed pairs included so the comparison covers reject too.
TOY_CASES: list[tuple[str, str, str, str]] = [
    ("toy_dbl",     "Nat → Nat", "T_dbl",        "accepted toy def"),
    ("toy_inc",     "Nat → Nat", "T_inc",        "accepted toy def"),
    ("toy_two",     "Nat",       "T_two",        "accepted toy def"),
    ("toy_four",    "Nat",       "T_four",       "accepted toy def"),
    ("toy_ten",     "Nat",       "T_ten",        "accepted toy def"),
    ("toy_pair",    "P2",        "T_pair",       "accepted toy def"),
    ("rej_dbl_bool", "Bool",     "T_dbl 2",      "ill-typed: Nat value vs Bool"),
    ("rej_two_bool", "Bool",     "T_two",        "ill-typed: Nat value vs Bool"),
    ("rej_pair_nat", "Nat",      "T_pair",       "ill-typed: P2 value vs Nat"),
    ("rej_inc_bad",  "Nat → Bool", "T_inc",      "ill-typed: Nat→Nat vs Nat→Bool"),
]

# No known legitimate Meta-vs-raw-kernel disagreement on this corpus. A
# disagreement not listed here fails (it is never silently accepted).
ALLOWED_DIFFS: dict[str, tuple[bool, bool, str]] = {}


def _part_a(fails: list[str]) -> int:
    cases = [(cid, t, v) for cid, t, v, _ in TOY_CASES]
    raw = lean_ref.run_kcheck_oracle(TOY_LEAN_DEFS, cases)
    meta = lean_ref.run_check_oracle(TOY_LEAN_DEFS, [(t, v) for _, t, v in cases])
    assert len(raw) == len(meta) == len(TOY_CASES)

    n_ok = 0
    print("Part A — toy env: Meta-path oracle vs raw-kernel #KCHECK")
    for (cid, _, _, note), r, m in zip(TOY_CASES, raw, meta):
        raw_accept, meta_accept = (r == "OK"), bool(m)
        if raw_accept == meta_accept:
            n_ok += 1
            print(f"  [AGREE] {cid:14s} {'accept' if meta_accept else 'reject':6s} "
                  f"(meta={'accept' if meta_accept else 'reject'}, "
                  f"raw={r}) — {note}")
        else:
            allowed = ALLOWED_DIFFS.get(cid)
            print(f"  [DIFF]  {cid:14s} meta={'accept' if meta_accept else 'reject'} "
                  f"raw={r} — {note}")
            if allowed is None:
                fails.append(
                    f"Part A {cid}: undocumented Meta/raw disagreement "
                    f"(meta={'accept' if meta_accept else 'reject'}, raw={r})")
            else:
                assert (meta_accept, raw_accept) == (allowed[0], allowed[1]), \
                    f"{cid}: diff {meta_accept}/{raw_accept} != allowed {allowed}"
    # the cases labeled "accepted" must be accepted by the real binary's
    # Meta-path oracle (the expectation comes from lean, not from a literal).
    for (cid, _, _, note), m in zip(TOY_CASES, meta):
        if note.startswith("accepted") and not m:
            fails.append(f"Part A {cid}: real-binary oracle rejected a toy "
                         f"declaration labeled accepted")
    print(f"  agreement: {n_ok}/{len(TOY_CASES)}")
    return n_ok


# ===========================================================================
# Part B — capacity measurement
# ===========================================================================

def _collect(e, out: set):
    if e is None:
        return
    if isinstance(e, App):
        _collect(e.fn, out); _collect(e.arg, out)
    elif isinstance(e, (Lam, Pi)):
        _collect(e.domain, out); _collect(e.body, out)
    elif isinstance(e, Let):
        _collect(e.domain, out); _collect(e.value, out); _collect(e.body, out)
    elif isinstance(e, MData):
        _collect(e.child, out)
    elif isinstance(e, Proj):
        _collect(e.child, out)
    elif isinstance(e, Const):
        out.add(e.name)


def _nodes(e) -> int:
    if e is None:
        return 0
    if isinstance(e, App):
        return 1 + _nodes(e.fn) + _nodes(e.arg)
    if isinstance(e, (Lam, Pi)):
        return 1 + _nodes(e.domain) + _nodes(e.body)
    if isinstance(e, Let):
        return 1 + _nodes(e.domain) + _nodes(e.value) + _nodes(e.body)
    if isinstance(e, MData):
        return 1 + _nodes(e.child)
    if isinstance(e, Proj):
        return 1 + _nodes(e.child)
    return 1


def _deps(dump: dict, name: str) -> set:
    out: set = set()
    _collect(dump[name]["ty"], out)
    _collect(dump[name]["val"], out)
    return {x for x in out if x in dump}


def _closure(dump: dict, root: str) -> list:
    """Transitive used-constant closure of root, in dependency (topological)
    order (closure over type+value Const occurrences; inductive ctor metadata
    is name-only, so it imposes no const order). Iterative (Kahn) so closures
    of thousands of constants cannot hit the Python recursion limit."""
    deps = {n: _deps(dump, n) for n in dump}
    seen: set = set()
    stack = [root]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(deps[n])
    indeg = {n: len(deps[n] & seen) for n in seen}
    rev: dict = {n: [] for n in seen}
    for n in seen:
        for m in deps[n] & seen:
            rev[m].append(n)
    from collections import deque
    queue = deque(sorted(n for n in seen if indeg[n] == 0))
    order: list = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for d in rev[n]:
            indeg[d] -= 1
            if indeg[d] == 0:
                queue.append(d)
    if len(order) != len(seen):                   # a cycle: fall back to sorted
        order = sorted(seen)
    return order


def _meta_for(d: dict) -> dict:
    m = {"kind": CK_BY_KIND[d["kind"]], "lparams": list(d["up"])}
    mm = d.get("meta") or {}
    if d["kind"] == "def":
        m.update(hints=mm.get("hints", 2), height=mm.get("height", 0),
                 safety=mm.get("safety", 1), is_unsafe=mm.get("isUnsafe", False),
                 all=mm.get("all", []))
    elif d["kind"] == "thm":
        m.update(all=mm.get("all", []))
    elif d["kind"] == "opaque":
        m.update(is_unsafe=mm.get("isUnsafe", False), all=mm.get("all", []))
    elif d["kind"] == "axiom":
        m.update(is_unsafe=mm.get("isUnsafe", False), all=[])
    elif d["kind"] == "ind":
        m.update(is_unsafe=mm.get("isUnsafe", False), is_rec=mm.get("isRec", False),
                 is_reflexive=mm.get("isRefl", False), all=mm.get("all", []),
                 ctors=mm.get("ctors", []))
    elif d["kind"] == "ctor":
        m.update(is_unsafe=mm.get("isUnsafe", False), induct=mm.get("induct", ""))
    elif d["kind"] == "rec":
        m.update(is_unsafe=mm.get("isUnsafe", False), is_k=mm.get("isK", False),
                 all=mm.get("all", []), rules=mm.get("rules", []))
    return m


def _encode_closure(dump: dict, order: list):
    """Encode the closure (topological order) as a token stream. Returns
    (stream_len, None) or (None, 'ExcType: msg')."""
    consts = [(n, dump[n]["ty"], dump[n]["val"]) for n in order]
    meta = {i: _meta_for(dump[n]) for i, n in enumerate(order)}
    try:
        enc = Encoder(consts, const_meta=meta)
        return len(enc.b.stream), None
    except Exception as ex:                       # noqa: BLE001 (report it)
        return None, f"{type(ex).__name__}: {ex}"


def measure(defs: str, roots: list, label: str, lean_cmd=None, cwd=None,
            dump_path: str = "/tmp/vm_koracle_dump.lean") -> list:
    """Dump `defs`+`roots` with the real binary and measure each root's
    closure. Returns records; prints a readable table."""
    t0 = time.time()
    try:
        dump = dump_env(defs, roots, path=dump_path, lean_cmd=lean_cmd, cwd=cwd)
    except Exception as ex:                       # noqa: BLE001
        print(f"  [{label}] dump unavailable: {type(ex).__name__}: "
              f"{str(ex)[:140]}")
        return []
    print(f"  [{label}] real-lean dump: {len(dump)} constants in "
          f"{time.time() - t0:.1f}s")
    if len(dump) > MAX_CLOSURE_CONSTS and not ENABLE_BIG:
        print(f"  [{label}] dump has {len(dump)} constants > "
              f"MAX_CLOSURE_CONSTS={MAX_CLOSURE_CONSTS}; skipping the "
              f"closure/node walk to bound memory "
              f"(set VM_CAPACITY_BIG=1 to force)")
        return []
    recs = []
    for root in roots:
        if root not in dump:
            print(f"  [{label}] {root}: NOT FOUND")
            continue
        order = _closure(dump, root)
        nodes_root = _nodes(dump[root]["ty"]) + _nodes(dump[root]["val"])
        nodes_closure = sum(_nodes(dump[n]["ty"]) + _nodes(dump[n]["val"])
                            for n in order)
        stream, err = (None, "skipped (closure too large to encode)")
        if len(order) <= MAX_ENCODE_CONSTS:
            stream, err = _encode_closure(dump, order)
        recs.append({"root": root, "kind": dump[root]["kind"],
                     "consts": len(order), "nodes_root": nodes_root,
                     "nodes_closure": nodes_closure, "stream": stream,
                     "err": err})
        s = f"stream={stream}" if stream is not None else f"stream=({err})"
        print(f"  [{label}] {root:24s} kind={dump[root]['kind']:5s} "
              f"consts={len(order):5d} nodes_root={nodes_root:6d} "
              f"nodes_closure={nodes_closure:8d} {s}")
    return recs


CORE_ROOTS = ["id", "Nat.add", "List.map", "List.append", "List.length",
              "Nat.ble"]
ML_MED_DEFS = ("import Mathlib.Data.Nat.Factorial.Basic\n"
               "import Mathlib.Data.Nat.Choose.Basic\n"
               "import Mathlib.Data.Nat.Fib.Basic\n")
ML_MED_ROOTS = ["Nat.factorial", "Nat.choose", "Nat.fib",
                "Nat.factorial_pos", "Nat.fib_add_two", "Nat.choose_succ_succ"]
ML_BIG_DEFS = "import Mathlib.Data.Matrix.Mul\n"
ML_BIG_ROOTS = ["Matrix.mul_assoc"]


def _part_b(fails: list[str]) -> int:
    n_checks = 0
    print("Part B — capacity of real declarations vs v1 limits "
          f"(sequence<={SEQ_LIMIT}, fields<={FIELD_LIMIT})")

    # (1) Lean core: small declarations that DO fit, with measured stream len.
    core = measure("", CORE_ROOTS, "core")
    by_root = {r["root"]: r for r in core}
    for root in ("id", "Nat.add", "List.map"):
        r = by_root.get(root)
        if r is None:
            continue
        n_checks += 1
        if r["consts"] > FIELD_LIMIT:
            fails.append(f"core {root}: closure {r['consts']} consts > {FIELD_LIMIT}")
        if r["stream"] is None:
            fails.append(f"core {root}: expected an encodable closure, got {r['err']}")
        elif r["stream"] > SEQ_LIMIT:
            fails.append(f"core {root}: stream {r['stream']} > {SEQ_LIMIT} "
                         f"(expected to fit)")
        else:
            print(f"    -> {root} fits: {r['consts']} consts, "
                  f"{r['nodes_closure']} closure nodes, stream={r['stream']} "
                  f"<= {SEQ_LIMIT}")

    # (2) Mathlib, if the lake project is reachable. OFF by default because
    # the closure materialization is memory-heavy (see ENABLE_MATHLIB above).
    if not ENABLE_MATHLIB:
        print("  [mathlib capacity] skipped by default (memory-heavy: the "
              "Matrix.mul_assoc closure is ~4.2M nodes). Set "
              "VM_CAPACITY_MATHLIB=1 to measure; see docs/ORACLE.md §5 for "
              "the recorded numbers.")
        return n_checks
    if not Path("/tmp/mlbench").is_dir():
        print("  [/tmp/mlbench] not present: Mathlib capacity skipped")
        return n_checks
    ml_cmd, ml_cwd = ["lake", "env", "lean"], "/tmp/mlbench"

    med = measure(ML_MED_DEFS, ML_MED_ROOTS, "mathlib-medium",
                  lean_cmd=ml_cmd, cwd=ml_cwd,
                  dump_path="/tmp/vm_koracle_mlmed.lean")
    by_root = {r["root"]: r for r in med}
    # defs still fit; a real theorem's own value already blows the sequence cap
    for root in ("Nat.factorial", "Nat.choose", "Nat.fib"):
        r = by_root.get(root)
        if r is None:
            continue
        n_checks += 1
        if r["stream"] is None or r["stream"] > SEQ_LIMIT:
            fails.append(f"mathlib {root}: expected fit, got "
                         f"stream={r['stream']} err={r['err']}")
        else:
            print(f"    -> {root} fits: {r['consts']} consts, "
                  f"stream={r['stream']} <= {SEQ_LIMIT}")
    for root in ("Nat.factorial_pos", "Nat.fib_add_two"):
        r = by_root.get(root)
        if r is None:
            continue
        n_checks += 1
        limit = "own type+value nodes" if r["nodes_root"] > SEQ_LIMIT else "closure nodes"
        if r["stream"] is not None and r["stream"] > SEQ_LIMIT:
            print(f"    -> {root} EXCEEDS sequence {SEQ_LIMIT}: "
                  f"consts={r['consts']}, nodes_root={r['nodes_root']}, "
                  f"nodes_closure={r['nodes_closure']}, stream={r['stream']}")
        elif r["nodes_closure"] > SEQ_LIMIT:
            print(f"    -> {root} EXCEEDS sequence {SEQ_LIMIT} on {limit}: "
                  f"consts={r['consts']}, nodes_root={r['nodes_root']}, "
                  f"nodes_closure={r['nodes_closure']}")
        else:
            fails.append(f"mathlib {root}: expected to exceed {SEQ_LIMIT}, got "
                         f"nodes_root={r['nodes_root']} "
                         f"nodes_closure={r['nodes_closure']} stream={r['stream']}")

    if not ENABLE_BIG:
        print("    [mathlib-big] skipped (set VM_CAPACITY_BIG=1 to measure; "
              "the constant-cap conclusion is recorded in docs/ORACLE.md §5)")
    else:
        big = measure(ML_BIG_DEFS, ML_BIG_ROOTS, "mathlib-big",
                      lean_cmd=ml_cmd, cwd=ml_cwd,
                      dump_path="/tmp/vm_koracle_mlbig.lean")
        over = [r for r in big if r["consts"] > FIELD_LIMIT]
        for r in big:
            print(f"    -> {r['root']}: consts={r['consts']} "
                  f"(field limit {FIELD_LIMIT}), "
                  f"nodes_closure={r['nodes_closure']}")
        n_checks += 1
        if not over:
            fails.append("mathlib-big: no measured declaration exceeds the "
                         f"{FIELD_LIMIT} constant cap; measurement inconclusive")
        else:
            for r in over:
                print(f"    -> {r['root']} EXCEEDS constant/name cap: "
                      f"consts={r['consts']} > {FIELD_LIMIT} (cid/nid fields)")

    # (3) first construct the v1 encoder cannot represent at all.
    n_checks += 1
    try:
        sdump = dump_env('def myStr : String := "hello"\n', ["myStr"],
                         path="/tmp/vm_koracle_str.lean")
        stream, err = _encode_closure(sdump, _closure(sdump, "myStr"))
        if err is None:
            fails.append("string literal unexpectedly encodable; expected a "
                         "LIT_STR refusal")
        elif "LIT_STR" not in err:
            fails.append(f"string literal encode failed for the wrong reason: {err}")
        else:
            print(f"    -> first unrepresentable construct: LitStr -> {err}")
    except Exception as ex:                       # noqa: BLE001
        fails.append(f"string-literal probe crashed: {type(ex).__name__}: {ex}")

    return n_checks


def main() -> int:
    fails: list[str] = []
    n_a = _part_a(fails)
    n_b = _part_b(fails)
    print(f"\n=== kernel oracle harness: Part A {n_a}/{len(TOY_CASES)} agree, "
          f"Part B {n_b} capacity checks, {len(fails)} failures ===")
    for msg in fails:
        print(f"  [FAIL] {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
