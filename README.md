# Lean 4 kernel, compiled into transformer weights

This repository implements the Lean 4 kernel's checking procedure — weak-head
normalization (WHNF), type inference, definitional equality — as one ALM
(Append-only Lookup Machine) computation graph, and constructs transformer
weights from that graph in closed form (no training). The transformer's
autoregressive forward pass executes the kernel's checking steps.

## Status (2026-10-23)

The current artifact is a 133-layer, d_model=11,888 sparse fp32 transformer
(363,318 nonzeros in a 36,851,134-byte `L4SV v2` binary,
`model/step_vm_022b_scratch.sbin`; the truth table in `ARCHITECTURE.md` lists
which artifact is valid). The kernel-rule closure now covers the whole checked
corpus: the mathlib closure differential — 35 declarations from three real
Mathlib closures, judged on four channels (step graph, reference machine,
compiled C++ engine, and the engine on the full closure environment) against a
live `lean` 4.33.1 — passes with **zero registered gaps**. The 26-suite CPU
regression is green (the two small mathlib segments are re-run solo under
their recalibrated caps; see the comments in `scripts/run_cpu_regression.sh`).
No semantic gap remains open on the checked corpus; remaining work is the
scope noted under "What is not implemented".

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
  the same instruction-level specification (`docs/VM_SPEC.md`), including the
  kernel's quot reduction (`K/quot.h`) and a monomorphic `infer_proj` (spine
  peel + parameter instantiation with the kernel's Prop guard). It is used for
  fast semantic iteration and as one of the differential channels; it is not
  the judge, and its subset boundaries are printed rather than silently
  accepted.
- **The real Lean binary as the only judge** (`reference/lean_ref.py`). Every
  semantic result is differential-tested against the installed `lean`
  (v4.33.1). The local `/home/xkq/lean4` tree is a 4.35 checkout and is used
  as a reference for reading the kernel's semantics; if the two disagree, the
  installed binary is authoritative.
- **A hand-built environment and corpus** (`reference/toy_env.py`, 35
  constants) used to drive the differential tests.
- **Weight compilation** (`model/compile_vm.py`, `compiler/`): MILP layer
  scheduling followed by closed-form weight construction. The current artifact
  is a 133-layer, d_model=11,888 sparse (CSR) transformer in fp32 —
  363,318 nonzeros in a 36,851,134-byte `L4SV v2` binary (the old dense float64
  form, 511M parameters, was retired per `docs/decisions/005-*.md`: 19GB,
  OOM on this box; see `ARCHITECTURE.md` truth table).
- **A C++17 executor** (`engine/vm.cpp`) that loads the compiled weight binary
  and runs the graph's WHNF, INFER, DEFEQ and CHECK tasks without Python or
  torch; its `check` channel is used as a judging leg by the mathlib closure
  differential.
- **A mathlib closure differential** (`tests/test_mathlib_closure_vs_lean.py`):
  35 declarations from three real Mathlib closures (`Quot.liftOn_mk`,
  `Vector3.cons_fz`, `Nat.testBit_land`), each judged on four channels against
  a live Lean kernel run over the same per-case minimal environment.
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
| compiled weights / C++ engine | reference machine (34-case WHNF corpus) | `scripts/verify_engine_vs_refvm.py` |
| compiled weights / C++ engine, `check` mode | real Lean binary | `tests/test_mathlib_closure_vs_lean.py` (engine and full-closure engine legs) |

Corpus sizes: WHNF 34 cases, INFER/DEFEQ 84 cases (82 have a real-Lean
mirror), CHECK 15 cases, declaration injection 153 checks (+1 registered
xfail), mutation 16 + localization 8, mathlib closure 35 declarations x 4
channels.

Why the kernel inside the weights instead of calling out to a Lean binary:
the weights that write proofs and the weights that check proofs are one and
the same substrate, so self-checking is an internal behavior of the model.
The further research line — a differentiable judge — is gated on an unsolved
precision floor (fp32 is the usable minimum) and is not a current commitment
(`docs/DESIGN.md` §1, motivation).

## What is not implemented / current boundaries

- **Mathlib coverage is an excerpt, not the library**: three closures (874
  constants) are exercised per case on per-case minimal environments. The
  whole library is out of reach today — the compiled engine's cost is
  superlinear in stream length (45.6k-token full-environment checks exceed an
  hour; `docs/VM_SPEC.md` §19), so scale evidence is per-case minimal
  environments plus the Quot full-closure engine leg. The name-blind channels
  (reference machine, engine) also cannot judge `alreadyDeclared` rows: they
  carry no name space.
- **Constant metadata is environment data, not code** — for the scanned names:
  ids, structure layouts and `casesOn` arities come from the `.olean` export +
  name scan (`build_vm.py` `_SCAN_OPS`, WP1/WP8). One hardcoded cid remains as
  a known defect (`CID_P2MK` in `build_vm.py`), not as an implementation
  technique.
- **The Python weight runner** (`model/runner.py`) has no infer/defeq/check or
  reject handling; the compiled channel's judging path is the C++ engine
  (`vm_run <sbin> <stream> <pos> check ...`).
- **Reference-machine subset boundaries** (printed, never silent): `infer_proj`
  refuses dependent-field projections and indexed inductives (conservative),
  has no theorem kind gate, and the machine is name-blind.
- **No source-level input**: no parser, no elaborator, no tactics.
- **`native_decide` / `Lean.reduceBool`**: the real kernel calls compiled code
  here and trusts it through the axiom `Lean.ofReduceBool`. This cannot be
  reproduced inside the graph; matching the verdict requires treating it the
  same way the kernel does, as an axiom.
- **Performance at proof scale**: one token per micro-step, strictly serial.
  The measured cost curves (Python evaluator and compiled engine) are in
  `docs/VM_SPEC.md` §19.

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
# Differential suites (CPU only, 26 entries). Note: the test_*.py files are
# NOT pytest suites (pytest collects 0 items — each file has its own main());
# run_cpu_regression.sh is the single entry point. The mathlib closure
# differential runs as three per-closure segments (mathlib_quot / _vector3 /
# _nat) because the full 35-row run takes hours.
bash scripts/run_cpu_regression.sh

# Compile the graph into transformer weights (sparse-native, never dense)
python3 -u model/compile_vm.py --sparse model/step_vm_022b_scratch   # -> .sbin

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
