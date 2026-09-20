# ORACLE — acceptance oracle harness

Authority: acceptance criterion in [DESIGN.md](DESIGN.md) §2 — for the same
elaborated input, the VM verdict must be identical to the real Lean 4 kernel
(accept/reject, error class, and inferred type up to the kernel's `is_def_eq`).
This file documents the oracle commands that produce the real binary's verdict,
which layer each one exercises, the corpus sources, how to run the differential
suites, the error-class comparison granularity rule, and the measured capacity
limits. All oracle commands live in `reference/lean_ref.py`; expected values are
always produced by the real `lean` binary, never hand-written. The oracle is
pinned to **v4.33.1** (`~/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean`;
`reference/lean_ref.py` resolves it, override with `L4TVM_LEAN` for a future
re-baseline — which then needs its own differential re-run): every expectation
in the repo was probed on 4.33.1, and `elan default` drifted to 4.34.0 on
2026-09-20, so the bare `~/.elan/bin/lean` path is no longer trustworthy.

## 1. Oracle commands and layers

| Command | Layer exercised | Template / runner | Output line |
|---|---|---|---|
| `#ORACLE e` | Meta `Meta.whnf` after `elabTerm` + `instantiateMVars` | `ORACLE_TEMPLATE` / `run_oracle`, `run_oracle_mixed(WHNF)` | `ORACLE <expr-json>` |
| `#ORACLE_DEFEQ a =?= b` | Meta `Meta.isDefEq` | `ORACLE_TEMPLATE` / `run_oracle_mixed(DEFEQ)` | `DEFEQ true|false` |
| `#ORACLE_INFER e` | Meta `inferType` (Meta layer) | `ORACLE_TEMPLATE` / `run_oracle_mixed(INFER)` | `INFER <expr-json>` |
| `#LEVEL id (a, b)` | public `Lean.Level` predicate API (`isEquiv`/`geq`/`occurs`, `normalize`, `getOffset`, …) | `LEVEL_TEMPLATE` / `run_level_oracle` | `LEVEL <id> <json>` |
| `#KDECL id d` | RAW kernel declaration insertion: `Lean.Kernel.Environment.addDecl` (the C++ `environment::add_definition/add_theorem/...` check path, `type_checker` inside) | `KDECL_TEMPLATE` / `run_kdecl_oracle` | `KDECL <id> OK|<class>` |
| `#KCHECK id (t, v)` | RAW kernel type checker on an elaborated declaration pair: `Lean.Kernel.check` + `Lean.Kernel.isDefEq` (the `lean_kernel_check`/`lean_kernel_is_def_eq` externs in `Lean/Environment.lean`, which call `type_checker(...).check` / `.is_def_eq`) | `KCHECK_TEMPLATE` / `run_kcheck_oracle` | `KCHECK <id> OK|<class>` |

`<expr-json>` is the serialization in `ORACLE_TEMPLATE` (`k=1..12` for expr
nodes, `k=1..6` for levels); `json_to_expr` parses it back into `expr/model.py`
objects. `<class>` is a `Lean.Kernel.Exception` constructor name
(`classOf`), for example `declTypeMismatch`, `typeExpected`,
`unknownConstant`, `declHasMVars`, `declHasFVars`, `alreadyDeclared`,
`other`.

There is also a non-`#`-command accept/reject oracle:

| Function | What it runs | Verdict |
|---|---|---|
| `run_check_oracle(defs, [(T, v)])` | one `lean` file per case containing `example : T := v` | exit 0 = accept, nonzero = reject |

This exercises the elaborator (`elabTerm` + type-class synthesis) and then the
kernel insertion check for the generated declaration; it is the "Meta-path"
accept/reject oracle used by `tests/test_check_e2e.py`.

### 1.1 What `#KCHECK` does, step by step

1. `elabTerm` both source terms, `synthesizeSyntheticMVarsNoPostponing`,
   `instantiateMVars` — the input is an elaborated, mvar-free declaration pair.
2. Reject any residual mvar/fvar with `declHasMVars` / `declHasFVars`
   (mirrors `check_no_metavar_no_fvar`, `K/environment.cpp:87-99`).
3. `Kernel.check env lctx type`; require the returned type to be a `Sort`
   (`typeExpected` otherwise) — mirrors `check_constant_val` → `ensure_sort`
   (`K/environment.cpp:124-132`).
4. `Kernel.check env lctx value` — raw kernel inference of the value's type.
5. raw `Kernel.isDefEq env lctx valueType type`; `false` yields
   `declTypeMismatch` — mirrors `add_definition` (`K/environment.cpp:160-179`).

`#KCHECK` is deliberately distinct from `#KDECL`: `#KDECL` builds a raw
`Declaration` value and lets `addDecl` run the whole insertion path, while
`#KCHECK` calls the raw `type_checker` entry points directly. Both reach the
same C++ checker; `#KCHECK` is the one used to check an already-elaborated
type/value pair.

## 2. Corpus sources

- Toy environment: `reference/toy_env.py`. `TOY_CONSTS` is the 35-constant
  table (cid 0..34: `Nat`, `Bool`, constructors, arithmetic, `P2`/`UnitT`
  structures, `Nat.rec`/casesOn, `Nat.below`/`brecOn`); `TOY_LEAN_DEFS` is the
  matching Lean source; `CORPUS` (WHNF), `DEFEQ_CORPUS`, `INFER_CORPUS` are the
  closed-term differential cases.
- Exported environment subset: `tests/test_olean_export.py` `TARGET_DEFS` /
  `ROOTS` (`E_dbl`, `E_two`, `E_four`, `E_ten`, `E_inc`, `E_hof`,
  `E_pair`/`E_pair.mk`, `E_mk`, `E_sum`, `E_let`) layered on the toy table.
- Declaration check: `tests/test_check_e2e.py` `CHECK_CASES` (12 type/value
  pairs over `TARGET_DEFS`, accept and reject) plus `SEQUENCES`.
- Level / raw-declaration oracle self-consistency:
  `tests/test_level_vs_lean.py` `LEVEL_DEFS` + 26 `LEVEL_CASES`,
  `KDECL_DEFS` + 9 `KDECL_CASES`.
- Kernel-vs-Meta and capacity: `tests/test_kernel_oracle.py` (this package).
- Capacity measurement roots (real binary): Lean core
  (`id`, `Nat.add`, `List.map`, `List.append`, `List.length`, `Nat.ble`) and
  Mathlib `/home/xkq/mathlib_src` (`Nat.factorial`, `Nat.choose`, `Nat.fib`,
  `Nat.factorial_pos`, `Nat.fib_add_two`, `Nat.choose_succ_succ`, and
  `Matrix.mul_assoc` — see §5).

## 3. Running the differential suites

```
# WHNF: RefVM (token stream) vs real lean
python3 tests/test_ref_vs_lean.py            # 34/34 expected

# step graph vs real lean
python3 tests/test_stepgraph_vs_lean.py      # 34/34 expected

# INFER + DEFEQ (RefVM vs real lean)
python3 tests/test_ref_infer_defeq.py        # 82/82 expected

# #LEVEL / #KDECL oracle self-consistency
python3 tests/test_level_vs_lean.py          # 37/37 expected

# level token encoding round-trip (real lean dump)
python3 tests/test_level_encoding.py         # 0 failures expected

# end-to-end CHECK: RefVM vs lean (A) and graph vs RefVM (B)
python3 tests/test_check_e2e.py              # A 15/15, B 15/15 expected

# new: #KCHECK kernel-vs-Meta agreement + capacity measurement
OMP_NUM_THREADS=4 python3 tests/test_kernel_oracle.py
```

`tests/test_kernel_oracle.py` is the only suite that invokes the raw-kernel
`#KCHECK` path. Its Part B imports `/home/xkq/mathlib_src` Mathlib (single
`Mathlib.Data.Matrix.Mul` import, ~1 minute); if `/home/xkq/mathlib_src` is absent the
Mathlib capacity section is skipped and the core measurements still run.

## 4. Error-class comparison granularity rule

The real kernel raises many distinct `Kernel.Exception` classes
(`K/kernel_exception.h`); the VM has four coarse codes (`VM_SPEC` §7.4,
`lean_vm/ref_vm.py:47-50`): `ERR_TYPE=1`, `ERR_MISSING_CONST=2`,
`ERR_OVERFLOW=3`, `ERR_UNSUPPORTED=4`. This is the mapping rule used by the
tests; it resolves the global TBD in `docs/KERNEL_COVERAGE.md` §6 item 1 for
the differential suites, at the coarse granularity the VM exposes today.

1. **Accept vs reject is compared strictly, for every case.** This is the
   primary, always-required comparison. A case where one side accepts and the
   other rejects is a hard failure, regardless of error class.
2. **Error class is compared only through the mapping below.** When both sides
   reject, the test maps the kernel class to the VM code and asserts equality;
   the exact kernel class is still recorded and printed, because the VM code
   is strictly coarser.
3. **VM infrastructure codes carry no kernel class counterpart.** A VM
   rejection with `ERR_OVERFLOW` (pointer/length outside the §2 encoding
   range) or `ERR_UNSUPPORTED` (a construct outside the v1 slice, e.g. a
   `LitStr`) is an encoding-layer limitation, not a logical verdict. Such
   cases must be reported and excluded from accept/reject comparisons, never
   counted as agreement with the kernel.

Kernel class → VM code (comparison map):

| Kernel `Exception` class | VM code | Notes |
|---|---|---|
| `declTypeMismatch`, `typeExpected`, `funExpected`, `letTypeMismatch`, `exprTypeMismatch`, `appTypeMismatch`, `invalidProj`, `thmTypeIsNotProp`, `declHasMVars`, `declHasFVars`, `alreadyDeclared`, `other` | `ERR_TYPE` (1) | logical/type error; the coarse VM code cannot separate them |
| `unknownConstant` | `ERR_MISSING_CONST` (2) | |
| `deterministicTimeout`, `excessiveMemory`, `deepRecursion`, `interrupted` | (none) | resource/interrupt conditions, not logical verdicts; excluded from classification |
| — (VM-only) | `ERR_OVERFLOW` (3) | encoding-layer limit, §2 |
| — (VM-only) | `ERR_UNSUPPORTED` (4) | outside the v1 slice (`LitStr`, mvar, unimplemented level form) |

`#KCHECK` / `#KDECL` report the exact kernel class (not a mapped code), so a
future VM that adds finer error codes can re-map without changing the oracle
output. `tests/test_kernel_oracle.py` Part A uses the strict accept/reject
comparison (rule 1) over the toy corpus and prints the raw kernel class for
each reject; it currently finds no Meta-vs-raw disagreement.

## 5. Measured capacity limits

> **重测开关（默认关闭，防止爆内存）**：`tests/test_kernel_oracle.py` Part B
> 默认只测 Lean core 的小声明。Mathlib 部分需要 `VM_CAPACITY_MATHLIB=1`；
> 其中 `Matrix.mul_assoc`（闭包约 418 万节点）还需额外 `VM_CAPACITY_BIG=1`，
> 否则遇到超大 dump 会直接跳过闭包遍历。原因：把百万级节点物化成 Python
> 对象（每个常量一个 deps 集合 + 二次全量遍历）峰值可达数 GB，再叠加一个
> 载入 Mathlib 的 lean 进程，容易 OOM。下表数字是开启开关时测得的，不属于
> 默认测试路径；默认路径实测约 11 秒 / 峰值约 1.6 GB。

Measured 2026-09-12 with `lean` v4.33.1 and Mathlib `v4.33.1` in `/home/xkq/mathlib_src`
(`tests/test_kernel_oracle.py` Part B; tokens measured with the real
`expr/tokens.py` encoder). `consts` = constants in the declaration's transitive
used-constant closure (each needs a cid and at least one nid, both capped at
4095). `nodes_root` = expr nodes in the declaration's own type+value;
`nodes_closure` = expr nodes over its whole closure. `stream` = actual encoded
token-stream length (one token per node plus the header/name/metadata region).

Lean core (fit):

| declaration | consts | nodes_root | nodes_closure | stream |
|---|---|---|---|---|
| `id` | 1 | 10 | 10 | 21 |
| `Nat.add` | 15 | 24 | 512 | 802 |
| `List.map` | 17 | 48 | 770 | 1299 |
| `List.append` | 15 | 46 | 832 | 1351 |
| `List.length` | 41 | 28 | 1449 | 2403 |
| `Nat.ble` | 18 | 24 | 573 | 884 |

Mathlib defs (fit) and theorems (some exceed):

| declaration | kind | consts | nodes_root | nodes_closure | stream | limit exceeded |
|---|---|---|---|---|---|---|
| `Nat.factorial` | def | 36 | 14 | 1153 | 1767 | none |
| `Nat.choose` | def | 31 | 22 | 1077 | 1648 | none |
| `Nat.fib` | def | 36 | 96 | 1140 | 1796 | none |
| `Nat.choose_succ_succ` | thm | 35 | 62 | 1177 | 1791 | none |
| `Nat.factorial_pos` | thm | 96 | 50 | 7980 | 10461 | sequence 4096 |
| `Nat.fib_add_two` | thm | 113 | 8206 | 17955 | 24177 | sequence 4096 (own value alone 8206 nodes) |
| `Matrix.mul_assoc` | thm | 4115 | 664 | 4183324 | not encoded | constant/name cap 4095 (closure 4115) |

Additional large declarations measured from a full `import Mathlib` dump (not
encoded): `Polynomial.eval₂_mul` 4554 constants / 3230539 closure nodes
(exceeds the 4095 constant cap), `Finset.prod_comm` 4065 / 4161501,
`Finset.sum_comm` 4016 / 4160802, `Finset.sum_range_succ` 3316 / 3808516,
`Set.Finite.subset` 2526 / 1727494, `List.map_map` 39 / 2964, `Nat.add_comm`
47 / 3349.

Conclusions, stated against the `VM_SPEC` §2 limits (sequence ≤ 4096, every
pointer/count field ≤ 4095):

- Small Lean core declarations fit with room to spare (`Nat.add`: 15 constants,
  512 closure nodes, 802 stream tokens).
- Mathlib arithmetic *definitions* fit (`Nat.factorial` 1767 tokens,
  `Nat.fib` 1796), but a real Mathlib *theorem* overflows the sequence cap:
  `Nat.factorial_pos` needs 10461 tokens and `Nat.fib_add_two` 24177 tokens
  (> 2.5× and ~5.9× the cap); `Nat.fib_add_two`'s own value alone is 8206
  nodes > 4096.
- The constant/name cap (4095) is exceeded by `Matrix.mul_assoc` (4115
  constants) and `Polynomial.eval₂_mul` (4554 constants). Any declaration whose
  dependency closure has more than 4095 constants cannot be assigned distinct
  cids/nids in v1.
- The v1 encoder can represent the constructs in these closures (they encode,
  just past the limits). The first construct it cannot represent at all is a
  string literal: `def myStr : String := "hello"` raises
  `NotImplementedError: LIT_STR not supported in v1 (VM_SPEC §5)`, because
  `expr/tokens.py:encode_term` has no `LitStr` case (and `decode_expr` refuses
  it too).

These are encoding-capacity facts, not verdict differences: the real kernel
accepts every declaration above. Closing the gap requires either the Phase 4+
hull-attention field widening (2^24) with a larger sequence budget, or
per-proof closure extraction plus sharing so a proof's closure fits the v1
window.
