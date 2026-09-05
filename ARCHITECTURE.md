# Architecture

A single ALM (Append-only Lookup Machine) computation graph implements the
deterministic slice of the Lean 4 kernel — WHNF reduction, type inference, and
definitional equality — as a Krivine-style environment machine whose state
lives entirely in an append-only token stream. The graph is compiled into
standard transformer weights by analytical construction (a MILP layer schedule
plus closed-form weight synthesis, no training); the transformer's autoregressive
forward pass then executes the kernel one micro-step at a time. A dependency-free
C++ executor runs the compiled weights without Python or torch.

Every kernel operation is a micro-step of this one machine, sharing a single
frame stack and a single environment-link mechanism, so beta, zeta, delta, nat
arithmetic, inference, and defeq all compose inside one graph.

## Directory Layout

```
Lean4-Transformer-Vm-OSS/
├── lean_kernel/            # ALM graph DSL + position-addressing interpreter
│   ├── alm_graph.py        #   five-primitive Expression / ProgramGraph
│   └── alm_p2.py           #   fetch_by_position + eval_graph_sequence
├── expr/                   # expression model and token encode/decode
│   ├── model.py            #   Expr kinds, Level, token-kind constants
│   └── tokens.py           #   Encoder: Expr <-> token stream, ENV block
├── lean_vm/                # the single machine
│   ├── ref_vm.py           #   reference VM (differential oracle, not the judge)
│   ├── build_vm.py         #   the micro-step transition graph (WHNF/INFER/DEFEQ)
│   └── step_driver.py      #   append-only driver over the graph
├── compiler/               # graph -> weights
│   ├── milp_scheduler.py   #   MILP layer assignment
│   └── weights.py          #   analytical weight construction + binary export
├── model/                  # weight-compile entry + Python weight runner
│   ├── compile_vm.py
│   └── runner.py
├── engine/                 # C++17 executor (KV cache, WHNF slice)
│   └── vm.cpp
├── reference/              # real-Lean oracle harness + toy environment/corpus
│   ├── lean_ref.py
│   └── toy_env.py
└── tests/                  # differential tests per layer (vs real Lean,
                            #   vs reference VM, vs weights, vs C++ engine)
```

## Execution model

Each micro-step reads a constant number of earlier tokens by position
(`fetch_by_position`), computes the next state with constant-depth gating
(`_kind_eq_raw` / `_select` / per-digit lookup), and appends the next STATE
token plus any emitted PEND/LINK/FRAME tokens. All data-dependent iteration —
environment walking, digit carry, argument evaluation — is unrolled onto the
time axis, so the graph depth is constant while `d_model` grows linearly with
the dispatch-table size.

## Correctness

The authoritative semantics are the real Lean 4 kernel binary; the in-repo
reference VM (`lean_vm/ref_vm.py`) is an intermediate oracle used only for
differential testing. The token encoding, opcode table, and micro-step
transition rules are documented inline in `lean_vm/build_vm.py` and
`expr/tokens.py`. See the README for current pass counts.
