# Lean 4 kernel, compiled into transformer weights

This repository implements the Lean 4 kernel's checking procedure — weak-head
normalization (WHNF), type inference, definitional equality — as one ALM
(Append-only Lookup Machine) computation graph, and constructs transformer
weights from that graph in closed form (no training). The transformer's
autoregressive forward pass executes the kernel's checking steps.

## Acceptance criterion

For the same input — an elaborated declaration together with its environment —
the verdict must be **identical to the real Lean 4 kernel**:

- accept/reject agrees;
- on reject, the error class agrees;
- the inferred type is accepted by the real kernel's `is_def_eq` against the
  declared type.

Numeric closeness between the compiled weights and the graph is a development
check used while building the compiler. It is not an acceptance criterion, and
a tolerance is not a substitute for agreement on the verdict.

The corpus must not contain hardcoded answers: inputs are taken from or
generated against the environment, and the expected result comes from running
the real Lean binary.

## Scope

The kernel is the part of Lean that decides whether a declaration is correct.
It only ever sees fully elaborated terms; it does not see source text, macros,
or tactic scripts. This repository implements the kernel. Parsing, macro
expansion, elaboration and tactic execution are not part of the kernel and are
not implemented here.

Whether the product should also accept Lean source text directly (which would
mean reusing the real Lean front end, or reimplementing it) is an open
decision, recorded in [docs/DESIGN.md](docs/DESIGN.md).

Currently the input is an already-elaborated kernel term plus a constant table,
serialized into a token stream (`expr/tokens.py`).

## What is implemented

- **The checking machine as one ALM graph** (`lean_vm/build_vm.py`). The graph
  computes a single micro-step of a Krivine-style machine with a frame stack;
  WHNF, INFER, DEFEQ and CHECK are all tasks of that one graph. Iteration is
  performed over autoregressive time: one micro-step produces one token, so
  the graph depth is constant and does not grow with the input.
- **A reference machine** (`lean_vm/ref_vm.py`), a plain Python interpreter of
  the same instruction-level specification (`docs/VM_SPEC.md`). It is used for
  fast semantic iteration. It is not the judge.
- **The real Lean binary as the only judge** (`reference/lean_ref.py`). Every
  semantic result is differential-tested against the installed `lean`
  (v4.33.1). The local `/home/xkq/lean4` tree is a 4.35 checkout and is used
  as a reference for reading the kernel's semantics; if the two disagree, the
  installed binary is authoritative.
- **A hand-built environment and corpus** (`reference/toy_env.py`, 35
  constants) used to drive the differential tests.
- **Weight compilation** (`model/compile_vm.py`, `compiler/`): MILP layer
  scheduling followed by closed-form weight construction. The current artifact
  is a 109-layer, d_model=6222 sparse (CSR) transformer in fp32 — 186,892
  nonzeros in an 18,027,726-byte `L4SV v2` binary (the old dense float64
  form, 511M parameters, was retired per `docs/decisions/005-*.md`: 19GB,
  OOM on this box; see `ARCHITECTURE.md` truth table).
- **A C++17 executor** (`engine/vm.cpp`) that loads the compiled weight binary
  and runs the WHNF slice without Python or torch.
- **An `.olean` export path** (`reference/olean_export.py`) that dumps a
  constant subset from the real Lean `Environment` API for a restricted set of
  monomorphic declarations (definition / constructor / inductive; theorem,
  axiom and opaque are rejected).

## Verification layers

Each layer is compared against the layer below it or against the real Lean
binary. `scripts/run_cpu_regression.sh` runs the CPU suites (the weights test
is a release gate run only after a weight recompile):

| Layer | Compared against | Where |
|---|---|---|
| reference machine | real Lean binary | `tests/test_ref_vs_lean.py`, `tests/test_ref_infer_defeq.py` |
| ALM step graph | reference machine | `tests/test_stepgraph_vs_refvm.py`, `tests/test_stepgraph_infer_defeq.py` |
| ALM step graph | real Lean binary | `tests/test_stepgraph_vs_lean.py` |
| end-to-end CHECK | real Lean binary (exit code) | `tests/test_check_e2e.py` |
| mutation rejection + localization | real Lean binary | `tests/test_mutation_reject.py` |
| exported `.olean` environment | real Lean binary | `tests/test_olean_export.py` |
| compiled weights / C++ engine | reference machine | `scripts/verify_engine_vs_refvm.py` (WHNF slice only — the engine cannot drive INFER/DEFEQ/CHECK yet, see `docs/decisions/005-*.md`) |

Corpus sizes: WHNF 34 cases, INFER/DEFEQ 84 cases (82 have a real-Lean
mirror), CHECK 15 cases, mutation 16 + localization 8.

Why the kernel inside the weights instead of calling out to a Lean binary:
the weights that write proofs and the weights that check proofs are one and
the same substrate, so self-checking is an internal behavior of the model.
The further research line — a differentiable judge — is gated on an unsolved
precision floor (fp32 is the usable minimum) and is not a current commitment
(`docs/DESIGN.md` §1, motivation).

## What is not implemented

- **Constant metadata is environment data, not code** — but only for the
  scanned names: ids, structure layouts and `casesOn` arities come from the
  `.olean` export + name scan (`build_vm.py` `_SCAN_OPS`, WP1/WP8). One
  hardcoded cid remains as a known defect (`CID_P2MK + 1` in
  `build_vm.py:4723`), and Mathlib has not been tried end-to-end.
- **The compiled weights are verified for WHNF only.** INFER/DEFEQ/CHECK have
  been validated through the graph and the reference machine against the real
  Lean binary, but have not been exercised through the compiled weights, and
  `model/runner.py` has no infer/defeq/check or reject handling.
- **Kernel rules still missing**: general recursor iota for
  `brecOn`/`drecOn` (card 009), full universe-level normalization (D1/D2
  `mk_max`/`mk_imax`), and the declaration-injection checks that need the
  step_driver protocol upgrade — theorem `is_prop` (G3), unsafe register-then-
  check (G2), mutual-block visibility (G6), name reuse and duplicate-univ
  rejection (G8/G9) — scheduled as cards 010/011 per `docs/decisions/014-*.md`.
  Quot (WP4), string literals incl. `try_string_lit_expansion` (WP5), the
  `reduce_nat` bit-op and size-bound family (WP6, card 006), the remaining
  `is_def_eq` branches — reflection, cheap_proj whnf, lazy-delta hints,
  offset literals, `try_unfold_proj_app` — plus the
  `check_constant_val`/`add_axiom`/safety-gate error classes
  (A14/A15/A17/A26/A30, G1/G2/G4/G5/G7/G10/G11; WP7, card 007) are
  implemented, and the compiled engine channel passes the full 34-case WHNF
  corpus incl. `Nat.pow` (the ±1000 ReGLU clamp that flattened stream
  positions above 998 was raised to `REGLU_CLAMP = 1e6` in card 008).
- **No source-level input**: no parser, no elaborator, no tactics.
- **`native_decide` / `Lean.reduceBool`**: the real kernel calls compiled code
  here and trusts it through the axiom `Lean.ofReduceBool`. This cannot be
  reproduced inside the graph; matching the verdict requires treating it the
  same way the kernel does, as an axiom.
- **Performance at proof scale**: one token per micro-step, strictly serial.
  The current numbers are for toy inputs.

## Structure

- `lean_vm/` — reference machine, the single-graph builder, the step driver
- `expr/` — expression model and token encode/decode
- `lean_kernel/` — ALM graph DSL and the position-addressing graph interpreter
- `compiler/` — MILP layer scheduling and weight construction
- `model/` — weight-compile entry point and the Python weight runner
- `engine/` — C++17 executor
- `reference/` — real-Lean oracle harness, `.olean` export, toy environment
- `tests/` — differential tests for each layer

## Quick start

```bash
# Differential suites (CPU only). Note: the test_*.py files are NOT pytest
# suites (pytest collects 0 items — each file has its own main());
# run_cpu_regression.sh is the single entry point.
bash scripts/run_cpu_regression.sh

# Compile the graph into transformer weights (sparse-native, never dense)
python3 -u model/compile_vm.py --sparse model/step_vm_new_sparse   # -> .sbin

# C++ engine
make -C engine && python3 scripts/verify_engine_vs_refvm.py
```

Compiled weights and the engine binary are gitignored; both are deterministic
rebuilds from the graph.

## License

Apache License 2.0. Copyright 2026 Keqin Xie.

## Acknowledgements

The kernel operation semantics follow the Lean 4 kernel
(`src/kernel/`), and the environment format follows Lean's `.olean`
declarations. The idea of representing a machine as analytically constructed
transformer weights follows three earlier projects: Tracr (Lindner et al.,
2023), ALTA (Shaw et al., TMLR 2025), and transformer-vm (Percepta-Core;
the upstream repo carries no author list as of 2026-09). This project is a
Lean 4 kernel specialization of that idea.
