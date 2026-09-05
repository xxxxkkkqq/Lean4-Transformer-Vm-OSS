# Lean 4 Kernel, compiled into transformer weights

A compiler that maps a slice of the [Lean 4](https://github.com/leanprover/lean4)
kernel's deterministic operations — WHNF reduction, type inference, and
definitional equality — into **one** Append-only Lookup Machine (ALM)
computation graph, then constructs standard transformer weights from that
graph analytically (no training). The transformer's autoregressive forward
pass executes the kernel step by step. A dependency-free C++ executor runs
the compiled verifier without Python or torch.

## What it does

- **WHNF reduction** — beta, zeta, delta (incl. nested and higher-order),
  and all ten `Nat` arithmetic opcodes (add/sub/mul/div/mod/pow/beq/ble/
  succ/pred) as per-digit lookup with carry, inside the graph.
- **Type inference** — spine peeling, lambda / pi / let inference, constant
  types, binder markers.
- **Definitional equality** — per-kind dispatch, whnf loop, Nat normalisation,
  plus the stuck-pair tail of the kernel's `is_def_eq`: proof irrelevance,
  eta expansion, structural eta, projection reduction, and binder identity
  (shared `bid` on environment links).
- **Graph → weights** — `model/compile_vm.py` schedules the graph with a MILP
  layer assignment and emits a ~636 M-parameter transformer; the weights are
  built by closed-form construction, not gradient descent.
- **C++ executor** (`engine/`) — reads the weight binary with a KV cache and
  runs the WHNF slice with no Python/torch at runtime.

## Verification status

Every result is differential-tested against the **real Lean 4 binary**
(v4.33.1); the in-repo reference VM (`lean_vm/ref_vm.py`) is only an
intermediate oracle, never the judge. On a hand-built toy corpus:

| Layer | Comparison | Result |
|-------|-----------|--------|
| WHNF | graph vs real Lean (34 cases) | 34/34 |
| WHNF | reference VM vs real Lean (34 cases) | 34/34 |
| INFER/DEFEQ | reference VM vs real Lean (53 cases) | 53/53 |
| INFER/DEFEQ | graph vs reference VM (53 cases) | 52/53 |
| Weights | compiled forward vs graph interpreter, per micro-step | lockstep, integer dims agree to ≤1e-9 (tol 1e-6) |
| C++ engine | engine vs Python runner (WHNF slice) | agrees |

The single uncovered INFER/DEFEQ case is a nested-eta edge where a spine head
resolves through more than one binder marker; it is pinned in the test suite
rather than silently dropped.

## Structure

- `lean_vm/` — reference VM (`ref_vm.py`), the single-graph builder
  (`build_vm.py`), and the step driver (`step_driver.py`)
- `expr/` — expression model and token encode/decode
- `lean_kernel/` — the ALM graph DSL and the position-addressing graph
  interpreter (correctness reference, not the product engine)
- `compiler/` — MILP layer scheduling and analytical weight construction
- `model/` — weight-compile entry point and the Python weight runner
- `engine/` — C++17 executor
- `reference/` — the real-Lean oracle harness and the toy environment/corpus
- `tests/` — differential tests for each layer (vs real Lean, vs reference VM,
  vs weights, vs the C++ engine)

## Quick start

```bash
# Build the graph and run the differential suites (CPU only)
python3 tests/test_stepgraph_vs_lean.py        # WHNF graph vs real Lean
python3 tests/test_ref_infer_defeq.py          # reference VM vs real Lean
python3 tests/test_stepgraph_infer_defeq.py    # graph vs reference VM

# Compile the graph into transformer weights
python3 model/compile_vm.py                    # -> model/step_vm.pt / .bin

# Weights-vs-graph fidelity (slow: full-stream re-forward per micro-step)
python3 tests/test_weights_fidelity.py --quick

# C++ engine
make -C engine && python3 tests/test_engine_vs_runner.py --quick
```

Compiled weights (`model/step_vm.pt`, `model/step_vm.bin`) and the engine
binary are gitignored; both are deterministic rebuilds from the graph.

## Limitations

- **Not a complete kernel.** No metavariable solving, no universe-polymorphic
  instantiation, no inductive-recursor iota reduction, no string literals, no
  `quot`.
- **No end-to-end proof checking yet.** The machine runs hand-built toy
  closures, not constants imported from `.olean`. `.olean` constant-subset
  export, end-to-end `#check`, and mutation-rejection are the next milestone
  (planned in `docs/VM_SPEC.md`, not implemented).
- The corpus is small; the weights-fidelity and engine full regressions are
  slow on CPU (the largest cases re-forward the whole stream every micro-step).
- The C++ engine currently covers only the WHNF slice; the INFER/DEFEQ frames
  are not yet in its binary weight format.

## License

Apache License 2.0. Copyright 2026 Keqin Xie.

## Acknowledgements

This project stands on the shoulders of two communities whose work made it possible.

**Lean 4.** The kernel operation semantics, the C++ reference implementation in [lean4](https://github.com/leanprover/lean4), and the [mathlib4](https://github.com/leanprover-community/mathlib4) standard library have been indispensable references throughout this work. Without the careful engineering of the Lean team and the mathlib community, a faithful port of the kernel into transformer weights would not have been possible.

**The transformer-as-virtual-machine research line.** The idea that a standard transformer can be treated as a virtual machine whose program is encoded in analytically constructed weights — rather than learned through gradient descent — has been pioneered by three projects that this work draws inspiration from, in chronological order:

1. [**Tracr**](https://github.com/deepmind/tracr) (Lindner et al., 2023, DeepMind & ETH Zurich) — the first compiler from human-readable RASP programs to standard decoder-only transformer weights, and the work that opened the "compiled transformer" direction.

2. [**ALTA**](https://github.com/google-deepmind/alta) (Shaw et al., TMLR 2025, Google DeepMind) — extends the RASP/Tracr line with dynamic control flow (loops), compilation to Universal Transformers, and a sparse-transition-rule representation of the MLP sublayer, demonstrating constructive expressivity results for parity, addition, and SCAN.

3. [**transformer-vm**](https://github.com/Percepta-Core/transformer-vm) (Tzamos et al., 2026, Percepta) — compiles a WebAssembly virtual machine into the weights of an autoregressive transformer via the Append-only Lookup Machine (ALM) abstraction, demonstrating exact, differentiable execution of arbitrary C programs inside the transformer forward pass.

The present project is a Lean 4–kernel specialization of this paradigm: rather than a general-purpose VM, it compiles the deterministic kernel operations of a proof assistant into transformer weights, with the goal of providing the kernel with a fast, matrix-multiply-native execution substrate.
