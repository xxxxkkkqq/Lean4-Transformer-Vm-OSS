# Hybrid execution architecture for the compiled Lean-kernel VM

Status: design, 2026-09-13. Supersedes the "dense Transformer layer" model in
`ARCHITECTURE.md` §2 for execution purposes; the weight-compilation contract
(`docs/VM_SPEC.md`, `docs/DESIGN.md`) is unchanged.

## 1. What is actually being executed

`lean_vm/build_vm.build_step_graph()` produces an ALM dataflow graph with four
node classes:

| class | count (current graph) | ALM meaning |
|---|---|---|
| `InputDimension` | 11 | read a stream field / builtin |
| `LookUpDimension` | 1305 (1250 lookups) | fetch a value from an earlier position |
| `ReGLUDimension` | 9710 | multiply two values |
| `PersistDimension` | 84 | carry a value to the next micro-step |

Total 11110 dims. `compiler/milp_scheduler.schedule_graph()` packs these into a
99-layer schedule with 2346 residual slots; `compiler/weights.build_weights()`
lowers each layer to `CompactAttention` + ReGLU FFN and materialises dense
parameters.

### Measured cost of the dense lowering

On the P7.5c/WP8 graph (`d_model=3388, n_heads=400, d_ffn=1321, 99 layers`):

- dense parameters: **2,403,125,340** (~19.2 GB at fp64)
- non-zero parameters: **28,546** (density **5.6e-05**, 1 in ~17,800)
- of those nonzeros: `ff_in` 20488, `ff_out` 6250, `q` 534, `k` 732,
  `v` 271, `out` 271, `head` 76

So >99.99% of the dense weight file is zeros, and a micro-step computes
`O(n_layers × d_model²)` dense multiply-adds to evaluate ~30K meaningful ones.

### Measured cost of the routing lowering

Lookups per layer are extremely skewed:

```
lookups/layer: total=1250 max=395 nonzero_layers=34
histogram (lookups, #layers):
  (0,65) (2,7) (3,2) (4,3) (5,7) (6,3) (7,1) (13,2) (16,1)
  (17,1) (21,1) (27,1) (32,1) (71,1) (204,1) (349,1) (395,1)
```

65 of 99 layers route nothing. But `n_heads` is the **global** maximum (≈400),
and `CompactAttention.forward` / `vm.cpp`'s head loop iterate all `H` heads in
every layer. The head loop therefore costs `99 × 395 × T` per micro-step when
the work actually present is `Σ H_li ≈ 1250` heads — a **~31× waste**, on top
of the 65 entirely empty layers.

### Precision consequence of the routing lowering

A lookup is a discrete fetch, but it is lowered to softmax with a `HARD_K=1e4`
temperature to force one-hot. Measured score range on `succ_zero`:

```
layer  0: score in [-1.83e9, 9.14e9]   softmax peak 1.000000
layer 13: score in [-1.23e9, 1.29e10]  softmax peak 1.000000
```

Correctness of a discrete operation therefore depends on saturating a
continuous function. Measured outcomes: fp64/fp32 correct; **fp16 NaN** (scores
1e9 ≫ 65504 → inf → inf−inf); bf16 0/12. `argmax` is scale-invariant, so the
exact fetch needs no temperature, no `exp`, and no precision margin.

## 2. The architecture

Three execution classes, each with the representation it actually needs. This
is the "hybrid": dense residual routing for state, sparse exact arithmetic, and
exact index routing for fetches — not one uniform dense layer type.

| class | representation | execution |
|---|---|---|
| state (`Persist`, residual stream) | dense vector of `num_slots` | index copy |
| arithmetic (`ReGLU`) | CSR, ~28.5K nonzeros total | sparse gather/multiply/scatter |
| routing (`LookUp`) | per-layer head count `H_li`, 2 dims per head | exact `argmax` + `gather` |

Invariant that must be preserved: **the weights still are the program.** The
sparse tensors are the same analytic construction; only storage and execution
change. No node is replaced by hand-written host code, so `build_vm.py` remains
the single source of truth for kernel semantics.

### Why per-layer capacity is the architectural fix, not a micro-optimisation

The current lowering assumes every layer can hold the graph's worst-case
routing load. That assumption is what produces a 400-head, 3388-slot layer
uniformly across 99 layers. Allocating `H_li = max lookups in layer li` makes
the layer shape a function of the schedule rather than of the global maximum:

- attention parameters: `Σ_li 8·H_li·D ≈ 8 × 1250 × D` instead of
  `99 × 8 × 395 × D` → ~31× fewer.
- head loop: `Σ_li H_li·T ≈ 1250·T` instead of `99 × 395 × T`.
- 65 layers with `H_li = 0` skip the routing sublayer entirely.

## 3. Work items

Ordered; each has its own verification.

- **H1 — direct-to-sparse emission.** `build_weights` currently allocates dense
  `nn.Parameter` tensors (19.2 GB) and then CSR-ises them for `.sbin`. Emit CSR
  directly and never materialise the dense tensor. This is what makes the
  current graph compilable at all; the 19.2 GB materialisation is the OOM cause.
- **H2 — weight format v2.** Add per-layer head count (and per-layer FFN width)
  to the `L4SV` header so `H_li` is data, not a global. Keep v1 readable.
- **H3 — engine.** `vm.cpp`: iterate `H_li` heads, skip zero-lookup layers,
  make exact `argmax` the default (`VM_HARDMAX` currently opt-in).
- **H4 — runner parity.** Mirror H3 in `model/runner.py` so the differential
  test can compare engine vs runner.
- **H5 — residual `const_cid` hardcode.** `build_vm.py:1292` emits the Bool
  literal from the `beq`/`ble` comparison machine with hardcoded
  `CID_TRUE`/`CID_FALSE`, outside the WP8 metadata dispatch. Audit and fix, or
  document why the emitted literal is order-independent.
- **H6 — recompile and verify.** Regenerate `.pt` + `.sbin` from the current
  graph; run the engine-vs-runner differential test and the corpus.

## 4. Verification

- Fidelity: engine stream == runner stream, token for token, on the toy corpus
  and the coverage corpus (`tests/test_engine_vs_runner.py`).
- Sparsity: `.sbin` nonzero count equals the graph's live-op count.
- Precision: `argmax` path must be identical to the softmax path where the
  softmax saturates (verified so far on 10/10 cases), and must not NaN in fp16.
- No hardcoded answers: `tests/test_datadriven_env.py` (32/32 over four
  name-order/subset runs) must stay green.

## 5. Non-goals

- Replacing ALM primitives with hand-written host code (would break the
  "compiled from the kernel source" contract).
- Changing `build_vm.py`'s kernel semantics; H5 is a bug fix, not a redesign.
- Training anything: all weights remain analytically constructed.

## 6. Artifact status at time of writing

`model/` contains three mutually inconsistent builds:

| artifact | d_model | layers | heads | notes |
|---|---|---|---|---|
| `step_vm_new.pt` / `.bin` | 1898 | 98 | 94 | pre-WP8; the only dense checkpoint on disk |
| `step_vm.sbin` | 2084 | 99 | 94 | sparse, stale relative to current graph |
| deleted `*.bloated19g` | 3388 | 99 | 400 | post-WP8 dense, 19.2 GB, removed |

`model/step_vm.pt` (the default path several tests read) does not exist; H6
restores it. Any timing or behaviour claim must name the artifact it was
measured on, because they are not interchangeable.
