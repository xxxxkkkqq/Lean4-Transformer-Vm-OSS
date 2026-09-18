"""Phase 5 M1 differential test: RefVM infer/defeq subset vs real Lean 4.

Oracle = `lean` (v4.33.1, elan) via reference/lean_ref.run_oracle_mixed,
executing the exact same toy defs with #ORACLE_DEFEQ / #ORACLE_INFER.
Machine side = expr/tokens.py encoding + lean_vm/ref_vm.py infer/defeq
(kernel type_checker subset: quick structural + whnf-both + binder markers;
no eta / proof irrelevance / lazy-delta hints — M3).

DEFEQ comparison: boolean verdict.
INFER comparison: canonical Expr equality after decoding the VM closure
(binder names dropped both sides; kernel ignores them).

Run: python3 tests/test_ref_infer_defeq.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure, decode_expr
from expr.model import MData, MVar, App, Lam, Pi, Let
from lean_vm.ref_vm import RefVM, VMError
from reference import lean_ref
from reference.toy_env import (
    TOY_CONSTS, TOY_CTORS, TOY_STRUCTS, TOY_LEAN_DEFS,
    DEFEQ_CORPUS, INFER_CORPUS,
)


def strip_mdata(e):
    """kernel treats MData wrappers as transparent everywhere; the real
    lean env decorates Nat.add/Nat.beq types with MDATA(const Nat), our toy
    env stores plain Nat. Strip both sides before comparing."""
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


# Corpus cases with NO faithful real-Lean mirror: the P7.5c-2 brec SUM cases
# model the below-arg as bh : Nat and read the recursive value via the P2-proj
# bh.1 (the ↓/go-chain sidestep, VM_SPEC §11.16). Real Nat.brecOn binds
# bh : Nat.below motive t, which is stuck (not defeq to Nat inside the casesOn
# branch), so neither bh.1 nor bh elaborates against the real kernel. These are
# graph-vs-RefVM only (and deq_brec_sum_stuck is additionally pinned there);
# skip them in the lean oracle.
LEAN_NO_MIRROR = {"deq_brec_sum", "deq_brec_sum_stuck"}


def main() -> int:
    enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    vm = RefVM(enc.b, structures=TOY_STRUCTS)

    deq_cases = [c for c in DEFEQ_CORPUS if c[0] not in LEAN_NO_MIRROR]
    entries = [("DEFEQ", lhs, rhs) for (_, lhs, rhs, _, _) in deq_cases]
    entries += [("INFER", src, None) for (_, src, _) in INFER_CORPUS]
    oracle = lean_ref.run_oracle_mixed(TOY_LEAN_DEFS, entries)
    assert len(oracle) == len(entries)

    n_pass = 0
    fails = []

    for (cid, _, _, our_l, our_r), (_, verdict) in zip(deq_cases, oracle):
        try:
            lp = enc.encode_term(our_l)
            rp = enc.encode_term(our_r)
            got = vm.defeq((lp, 0), (rp, 0))
        except VMError as e:
            fails.append((cid, f"vm error: {e}"))
            continue
        if got == verdict:
            n_pass += 1
        else:
            fails.append((cid, f"defeq got {got}, lean says {verdict}"))

    for (cid, _, our_term), (_, oracle_json) in zip(INFER_CORPUS, oracle[
            len(deq_cases):]):
        expected = strip_mdata(lean_ref.json_to_expr(oracle_json))
        try:
            term_pos = enc.encode_term(our_term)
            t_pos, t_env = vm.infer(term_pos, 0)
            got = strip_mdata(decode_closure(enc.b, t_pos, t_env))
        except VMError as e:
            fails.append((cid, f"vm error: {e}"))
            continue
        if got == expected:
            n_pass += 1
        else:
            fails.append((cid, f"infer\n  vm:    {got}\n  lean:  {expected}"))

    total = len(deq_cases) + len(INFER_CORPUS)
    skipped = len(DEFEQ_CORPUS) - len(deq_cases)
    print(f"M1 infer/defeq vs real lean: {n_pass}/{total}"
          f"{f'  ({skipped} brec-sum cases skipped: no faithful lean mirror)' if skipped else ''}")
    for cid, msg in fails:
        print(f"  FAIL {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
