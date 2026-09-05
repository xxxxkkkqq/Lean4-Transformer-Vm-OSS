"""Compile the WHNF step graph (lean_vm/build_vm) into transformer weights.

Pipeline: build_step_graph -> schedule_graph (MILP) -> build_weights ->
torch.save. The checkpoint carries the LeanTransformer plus the plain-data
metadata WeightRunner needs (output-dim -> head row, field -> slot).

Run: python3 model/compile_vm.py [out_path]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lean_kernel.alm_graph import (
    Expression, InputDimension, _one_dim,
)
from lean_vm.build_vm import build_step_graph
from compiler.milp_scheduler import schedule_graph
from compiler.weights import build_weights, save_weights

# The stream's 7 token fields (VM_SPEC §2); their InputDimensions live in
# the graph under these names and get residual-stream slots at compile time.
FIELD_DIMS = ("k", "v0", "v1", "v2", "x", "e2", "f2")


def compile_step_vm(out_path: str = "model/step_vm.pt", log=print):
    t0 = time.time()
    graph, outputs = build_step_graph()
    log(f"graph: {len(graph.all_dims)} dims, {len(graph.all_lookups)} lookups "
        f"({time.time()-t0:.1f}s)")

    # Output head = identity projection per output dim: passing
    # {name: Expression({dim: 1})} both protects the dims' slots until the
    # last layer and makes logits[..., idx] read the dim's slot value.
    output_tokens = {name: Expression({d: 1}) for name, d in outputs.items()}

    t0 = time.time()
    plan = schedule_graph(graph.all_dims, graph.all_lookups,
                          graph.input_tokens, output_tokens)
    log(f"schedule: {plan.num_layers} layers, d_model={plan.num_slots} "
        f"({time.time()-t0:.1f}s)")

    t0 = time.time()
    model, all_tokens, tok_to_idx = build_weights(
        plan, graph.all_dims, graph.all_lookups,
        graph.input_tokens, output_tokens)
    log(f"build_weights: d_model={model.d_model} heads={model.n_heads} "
        f"ffn={model.d_ffn} params={count_params(model):,} "
        f"({time.time()-t0:.1f}s)")

    slot_of = model._slot_of
    field_slots = {}
    for d in graph.all_dims:
        if isinstance(d, InputDimension) and d.name in FIELD_DIMS:
            field_slots[d.name] = int(slot_of[d])
    assert len(field_slots) == len(FIELD_DIMS), "field dims missing slots"
    meta = {
        "output_index": {name: tok_to_idx[name] for name in outputs},
        "field_slots": field_slots,
        "one_slot": int(slot_of[_one_dim]),
    }
    # embedded in the binary format for the Phase 4 C++ engine
    model.runner_meta = meta

    torch.save({"model": model, "meta": meta}, out_path)
    bin_path = str(Path(out_path).with_suffix(".bin"))
    save_weights(model, all_tokens, bin_path)
    log(f"saved {out_path} + {bin_path} ({count_params(model):,} params)")
    return model, meta


def count_params(model) -> int:
    return sum(p.numel() for p in model.parameters())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "model/step_vm.pt"
    compile_step_vm(out)
