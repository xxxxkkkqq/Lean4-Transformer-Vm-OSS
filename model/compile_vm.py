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
from compiler.weights import (
    build_weights, save_weights, save_weights_sparse, save_sparse_native,
)

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
    # max_layers must clear the graph critical path: schedule_graph's old
    # default 32 was fine for the M3-era graph, but the P7.5c build
    # (brecOn/casesOn/UL layers) pushed critical_path to 98, and the
    # scheduler's 6*cp auto-scale was dead code behind min(32, cap).
    # 128 layers with the ×1.5 retry ladder (128→192→288) covers cp with
    # packing headroom; the plan's final layer count is trimmed to the
    # highest used phase.
    plan = schedule_graph(graph.all_dims, graph.all_lookups,
                          graph.input_tokens, output_tokens,
                          max_layers=128)
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
    # engine-facing CSR sparse file (mmapped by vm_run; ms-level load)
    sbin_path = str(Path(out_path).with_suffix(".sbin"))
    save_weights_sparse(model, all_tokens, sbin_path)
    log(f"saved {out_path} + {bin_path} + {sbin_path} "
        f"({count_params(model):,} params)")
    return model, meta


def compile_step_vm_sparse(out_path: str = "model/step_vm", log=print):
    """Sparse-native compile (H1/H2): emit the L4SV v2 .sbin directly.

    Identical pipeline to compile_step_vm up to build_weights, but passes
    sparse=True so the analytic construction writes SparseMatrix dicts with
    per-layer head counts (H_li) and no dense tensor is ever allocated.
    Only the .sbin is written — no .pt/.bin (which would be ~20 GB of zeros).
    """
    t0 = time.time()
    graph, outputs = build_step_graph()
    log(f"graph: {len(graph.all_dims)} dims, {len(graph.all_lookups)} lookups "
        f"({time.time()-t0:.1f}s)")

    output_tokens = {name: Expression({d: 1}) for name, d in outputs.items()}

    t0 = time.time()
    plan = schedule_graph(graph.all_dims, graph.all_lookups,
                          graph.input_tokens, output_tokens,
                          max_layers=128)
    log(f"schedule: {plan.num_layers} layers, d_model={plan.num_slots} "
        f"({time.time()-t0:.1f}s)")

    t0 = time.time()
    model, all_tokens, tok_to_idx = build_weights(
        plan, graph.all_dims, graph.all_lookups,
        graph.input_tokens, output_tokens, sparse=True)
    log(f"build_weights(sparse): d_model={model.d_model} "
        f"heads_global={model.n_heads} ffn={model.d_ffn} "
        f"nnz={model.nnz():,} ({time.time()-t0:.1f}s)")
    log(f"  nnz breakdown: {model.nnz_breakdown()}")
    log(f"  sum(H_li)={sum(model.layer_heads)} "
        f"global_H*L={model.n_heads * model.n_layers} "
        f"zero_head_layers={sum(1 for h in model.layer_heads if h == 0)}")

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
    model.runner_meta = meta

    sbin_path = str(Path(out_path).with_suffix(".sbin"))
    nnz = save_sparse_native(model, all_tokens, sbin_path)
    log(f"saved {sbin_path} ({nnz:,} nnz)")
    return model, meta


def count_params(model) -> int:
    return sum(p.numel() for p in model.parameters())


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sparse = "--sparse" in sys.argv
    if sparse:
        out = args[0] if args else "model/step_vm"
        compile_step_vm_sparse(out)
    else:
        out = args[0] if args else "model/step_vm.pt"
        compile_step_vm(out)
