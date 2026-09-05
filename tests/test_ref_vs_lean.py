"""Phase 1 differential test: RefVM (token stream) vs real Lean 4 binary.

Oracle = `lean` (v4.33.1, elan) via reference/lean_ref.py, executing the
exact same toy defs. Machine side = expr/tokens.py encoding + lean_vm/
ref_vm.py. Comparison = canonical Expr equality (binder names dropped on
both sides; kernel ignores them).

Run: python3 tests/test_ref_vs_lean.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_expr
from expr.model import MVar
from lean_vm.ref_vm import RefVM, VMError
from reference import lean_ref
from reference.toy_env import TOY_CONSTS, TOY_CTORS, TOY_LEAN_DEFS, CORPUS


def main() -> int:
    enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    vm = RefVM(enc.b)

    sources = [src for (_, src, _) in CORPUS]
    oracle = [payload for (_, payload) in
        lean_ref.run_oracle(TOY_LEAN_DEFS, sources)]

    n_pass = 0
    fails = []
    for (cid, src, our_term), oracle_json in zip(CORPUS, oracle):
        expected = lean_ref.json_to_expr(oracle_json)
        if isinstance(expected, MVar):
            fails.append((cid, "oracle left an mvar (elaboration bug)"))
            continue
        try:
            term_pos = enc.encode_term(our_term)
            result_pos = vm.run_whnf(term_pos)
            got = decode_expr(enc.b, result_pos)
        except VMError as e:
            fails.append((cid, f"VMError: {e}"))
            continue
        if got == expected:
            n_pass += 1
            print(f"  [PASS] {cid}")
        else:
            fails.append((cid, f"got={got!r}\n         expected={expected!r}"))

    n_total = len(CORPUS)
    print(f"\n=== RefVM vs Lean 4.33.1: {n_pass}/{n_total} ===")
    for cid, msg in fails:
        print(f"  [FAIL] {cid}: {msg}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
