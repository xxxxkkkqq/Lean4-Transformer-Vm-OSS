"""WP8-H5 regression: the beq/ble machine's synthesized Bool literal must carry
the *environment's* Bool.true / Bool.false cid, not the toy cids 2 / 3.

The bug: ``lean_vm/build_vm.py`` emitted the result of ``Nat.beq`` / ``Nat.ble``
as ``K_CONST(V0 = CID_TRUE | CID_FALSE)`` with ``CID_TRUE/CID_FALSE = 2/3``
hardcoded, outside the WP8 metadata/name-keyed dispatch.  Under any environment
whose cids are assigned differently (name-sorted real exports, or a reordered
toy table) the emitted literal is a *different* constant: the Bool.casesOn
classifier (``_is_true``/``_is_false``, metadata-driven) then treats the major
as "other" and the spine sticks, and defeq compares cids that never match.

This test drives the *step graph* (``StepDriver``) and the reference interpreter
(``RefVM``) over the SAME bundles and pins that:

  * the graph agrees with RefVM on the beq/ble whnf cases in two name orders,
  * the two orders really move the Bool.true/Bool.false cids and the pair is not
    the toy (2, 3) pair, so a pass cannot come from an accidental hardcoded
    match, and
  * the no-metadata legacy path still emits the toy cids (fallback intact).

Run: python3 tests/test_datadriven_bool.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure
from expr.model import App, Const, LitNat
from lean_vm.ref_vm import RefVM
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference.toy_env import TOY_CONSTS, TOY_CTORS, toy_const_meta

GRAPH_MAX_STEPS = 3000
TOY_CID = {n: i for i, (n, _, _) in enumerate(TOY_CONSTS)}

# Closed over the constants used: Nat (=0) and Bool (=7) are referenced by
# Nat.beq/Nat.ble's Pi types, so they must be in the bundle for the Encoder.
# Placed so that even this order already moves Bool.true/false off cids 2/3.
BOOL_BASE = ["Nat", "Nat.zero", "Nat.succ", "Nat.pred", "Nat.add",
             "Nat.beq", "Nat.ble", "Bool", "Bool.true", "Bool.false"]
# Toy-relative order for the legacy fallback run: Nat=0, Bool=1, Bool.true=2,
# Bool.false=3, exactly the cids the old hardcode assumed.
LEGACY_ORDER = ["Nat", "Bool", "Bool.true", "Bool.false", "Nat.zero",
                "Nat.succ", "Nat.pred", "Nat.add", "Nat.beq", "Nat.ble"]
TRACKED = ("Bool.true", "Bool.false")

CASES = [
    ("beq_true", "Nat.beq 3 3", App(App(Const("Nat.beq"), LitNat(3)), LitNat(3))),
    ("beq_false", "Nat.beq 3 5", App(App(Const("Nat.beq"), LitNat(3)), LitNat(5))),
    ("ble_true", "Nat.ble 3 5", App(App(Const("Nat.ble"), LitNat(3)), LitNat(5))),
    ("ble_false", "Nat.ble 5 3", App(App(Const("Nat.ble"), LitNat(5)), LitNat(3))),
]


def _bundle(subset_order, meta_by_name):
    """(consts, ctors, const_meta) for a subset in the given name order; cids
    follow the order exactly (no toy value is assumed or reused)."""
    toy_by_name = {n: (n, t, v) for n, t, v in TOY_CONSTS}
    consts = [toy_by_name[n] for n in subset_order]
    meta = {cid: copy.deepcopy(meta_by_name[n])
            for cid, n in enumerate(subset_order)}
    ctors = {n: True for n in subset_order if n in TOY_CTORS}
    return consts, ctors, meta


def _run(tag, subset, with_meta, graph, outputs, fails, strip_bool_tags=False):
    toy_names = [n for n, _, _ in TOY_CONSTS]
    full = toy_const_meta()
    meta_by_name = {n: full[i] for i, n in enumerate(toy_names)}
    consts, ctors, meta = _bundle(subset, meta_by_name)
    cid = {n: i for i, (n, _, _) in enumerate(consts)}
    n_pass = 0
    for cid_, src, term in CASES:
        # reference side gets its own bundle (both sides mutate their streams)
        ref_meta = meta if with_meta else None
        ref_enc = Encoder(consts, is_ctor=ctors, const_meta=ref_meta)
        ref_vm = RefVM(ref_enc.b, nat_enabled=True, structures={})
        rp, renv = ref_vm.whnf(ref_enc.encode_term(term), 0)
        expected = decode_closure(ref_enc.b, rp, renv)

        g_enc = Encoder(consts, is_ctor=ctors, const_meta=ref_meta)
        if strip_bool_tags:
            # simulate a legacy stream built before CTOR_ID_CODES existed: the
            # Bool ctor headers carry no X tag, so the header scan finds nothing
            # and the graph must fall back to CID_TRUE / CID_FALSE.
            for name in TRACKED:
                hdr = cid[name] + 1
                t = g_enc.b.stream[hdr]
                g_enc.b.stream[hdr] = (t[0], t[1], t[2], t[3], 0, t[5], t[6])
        drv = StepDriver(g_enc.b, graph, outputs)
        gp, genv = drv.run(g_enc.encode_term(term))
        got = decode_closure(g_enc.b, gp, genv)
        if got == expected:
            n_pass += 1
        else:
            fails.append("%s/%s: graph=%s ref=%s" % (tag, cid_, got, expected))
    print("  %-12s meta=%d  n=%2d  %d/%d cases   cids: Bool.true=%s "
          "Bool.false=%s" % (tag, with_meta, len(consts), n_pass, len(CASES),
                             cid.get("Bool.true"), cid.get("Bool.false")))
    return n_pass, cid


def main() -> int:
    fails: list[str] = []
    graph, outputs = build_step_graph()

    n_i, cid_ident = _run("ident", BOOL_BASE, True, graph, outputs, fails)
    n_r, cid_rev = _run("reversed", list(reversed(BOOL_BASE)), True,
                        graph, outputs, fails)
    # legacy: no metadata, toy-relative cids, Bool ctor header tags stripped ->
    # the fallback must still emit the toy cids 2 / 3.
    n_l, cid_leg = _run("legacy", LEGACY_ORDER, False, graph, outputs, fails,
                        strip_bool_tags=True)
    if (cid_leg.get("Bool.true"), cid_leg.get("Bool.false")) != (2, 3):
        fails.append("legacy order does not put Bool ctors at toy cids 2/3")

    # the two orders must really move each Bool ctor cid, and the (true, false)
    # pair must not be the toy (2, 3) pair the old code emitted.
    for name in TRACKED:
        a, b = cid_ident.get(name), cid_rev.get(name)
        if a == b:
            fails.append("reversed table left %s at cid %s" % (name, a))
    if (cid_ident.get("Bool.true"), cid_ident.get("Bool.false")) == (2, 3):
        fails.append("identity order happens to match the hardcoded (2,3)")
    if (cid_rev.get("Bool.true"), cid_rev.get("Bool.false")) == (2, 3):
        fails.append("reversed order happens to match the hardcoded (2,3)")

    total = len(CASES) * 3
    got_total = n_i + n_r + n_l
    print("\n=== data-driven Bool literal: %d/%d cases over 3 runs ==="
          % (got_total, total))
    for f in fails:
        print("  [FAIL] " + f)
    return 0 if (got_total == total and not fails) else 1


if __name__ == "__main__":
    sys.exit(main())
