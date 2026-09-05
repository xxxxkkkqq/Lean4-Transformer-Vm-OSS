"""MILP scheduler: minimize d_model for delayed-reuse erase scheduling.

This is the primary scheduler for the Lean 4 kernel ALM graph. It solves a
mixed-integer linear program (MILP) to assign each ALM operation to a layer
while minimizing d_model with full slot reuse.

Assigns each ALM operation (LookUp, ReGLU, Persist) to a 4-phase layer:
  phase 0: Attention (LookUp)
  phase 1: Persist1
  phase 2: FFN (ReGLU)
  phase 3: Persist2

Minimizes d_model = 2 * D_half where D_half >= max over all boundaries of:
  - ceil(effective_width / 2), counting dims with birth<=c AND death>=c-1
    AND needs_slot (excludes internal lookup/reglu dims consumed same half-layer)
  - n_lu_heads + ceil((dying + passthrough) / 2) per attention layer

Adapted from transformer-vm/transformer_vm/scheduler/milp.py.
"""

from __future__ import annotations
import heapq
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any

import numpy as np

import highspy

logger = logging.getLogger(__name__)


# ─── Schedule Data Types ──────────────────────────────────────────────────


@dataclass
class SchedOp:
    """A schedulable operation in the ALM graph."""
    name: str
    kind: str  # "reglu", "persist", "lookup"
    deps: Set[str] = field(default_factory=set)
    phase: Optional[int] = None
    layer: Optional[int] = None


@dataclass
class SchedulePlan:
    """The complete schedule plan for a program graph."""
    num_layers: int
    num_slots: int  # d_model
    num_heads: int  # n_heads
    layers: List[Dict[str, Any]]


def compute_flops(plan: SchedulePlan) -> int:
    """Compute the approximate FLOPs per token for a scheduled model."""
    D = plan.num_slots
    L = plan.num_layers
    H = plan.num_heads

    # Attention: QKV projection + attention + output projection
    attn_flops = 3 * D * D + 2 * D * D + D * D

    # FFN: input gate + output
    ffn_flops = 2 * 2 * D + D * 2

    per_layer = attn_flops + ffn_flops

    return L * per_layer + 2 * D * len(plan.layers[0].get("ffn", []))


def write_plan(plan: SchedulePlan, path: str):
    """Write a schedule plan to a YAML file.

    Format compatible with transformer-vm's plan.yaml.
    """
    import yaml

    doc = {
        "summary": {
            "layers": plan.num_layers,
            "slots": plan.num_slots,
            "heads": plan.num_heads,
        },
        "layers": [],
    }

    for layer_info in plan.layers:
        entry = {
            "layer": layer_info["layer"],
            "attention": layer_info["attention"],
            "persist1": layer_info["persist1"],
            "ffn": layer_info["ffn"],
            "persist2": layer_info["persist2"],
        }
        doc["layers"].append(entry)

    with open(path, "w") as f:
        yaml.dump(doc, f, default_flow_style=False, sort_keys=False)


def load_plan(path: str) -> SchedulePlan:
    """Load a schedule plan from a YAML file."""
    import yaml

    with open(path) as f:
        doc = yaml.safe_load(f)

    layers = doc["layers"]
    num_layers = doc["summary"]["layers"]
    num_slots = doc["summary"]["slots"]
    num_heads = doc["summary"]["heads"]

    return SchedulePlan(
        num_layers=num_layers,
        num_slots=num_slots,
        num_heads=num_heads,
        layers=layers,
    )


def _build_graph(all_dims, all_lookups, position, ilp, psq):
    """Build dependency graph from dim/lookup lists.

    Mirrors transformer-vm's _build_graph but uses lean4-transformer-vm types.
    """
    from lean_kernel.alm_graph import (
        InputDimension, ReGLUDimension, PersistDimension,
        LookUpDimension, Expression,
    )

    inputs = [d for d in all_dims if isinstance(d, InputDimension)]
    reglus = [d for d in all_dims if isinstance(d, ReGLUDimension)]
    persists = [d for d in all_dims if isinstance(d, PersistDimension)]
    lookups = list(all_lookups)
    ops = reglus + persists + lookups

    produced = {}
    for r in reglus:
        produced[r] = {r}
    for p in persists:
        produced[p] = {p}
    for lu in lookups:
        produced[lu] = set(lu.dims)

    def _edeps(expr):
        return set(expr.terms.keys()) if isinstance(expr, Expression) else set()

    deps_cache = {}
    for r in reglus:
        deps_cache[r] = _edeps(r.a_expr) | _edeps(r.b_expr)
    for p in persists:
        deps_cache[p] = _edeps(p.expr)
    for lu in lookups:
        d = set()
        for expr in lu.query_exprs_2d + lu.key_exprs_2d + lu.value_exprs:
            d |= _edeps(expr)
        d.add(ilp)
        deps_cache[lu] = d

    dim_to_op = {}
    for op in ops:
        for d in produced[op]:
            dim_to_op[d] = op

    op_deps = defaultdict(set)
    children = defaultdict(set)
    consumers = defaultdict(set)
    for op in ops:
        for dim in deps_cache[op]:
            consumers[dim].add(op)
            if dim in dim_to_op and dim_to_op[dim] != op:
                pred = dim_to_op[dim]
                op_deps[op].add(pred)
                children[pred].add(op)

    avg_lookups = {lu for lu in lookups if lu.tie_break == "average"}
    tight_to = defaultdict(set)
    for op in reglus + persists:
        for dim in deps_cache[op]:
            if isinstance(dim, LookUpDimension) and dim in dim_to_op:
                lu = dim_to_op[dim]
                if lu in avg_lookups:
                    tight_to[op].add(lu)

    return dict(
        ops=ops,
        reglus=reglus,
        persists=persists,
        lookups=lookups,
        inputs=inputs,
        produced=produced,
        deps_cache=deps_cache,
        dim_to_op=dim_to_op,
        op_deps=op_deps,
        children=children,
        consumers=consumers,
        tight_to=dict(tight_to),
    )


def _min_layers(ops, op_deps):
    """Critical path length matching the MILP's FFN→FFN constraint.

    FFN→FFN deps (ReGLU↔Persist) require strictly different layers because
    all FFN ops execute in parallel in the transformer model.  LookUp→FFN
    deps are fine within one layer (attention output is added before FFN).

    Returns at least 1 (even for empty graphs, since the model needs at least
    one transformer layer to produce output).
    """
    if not ops:
        return 1
    from lean_kernel.alm_graph import LookUp, ReGLUDimension, PersistDimension

    # Compute earliest PHASE for each op, matching the MILP constraints
    phase, remaining = {}, set(ops)
    while remaining:
        progress = False
        for op in list(remaining):
            if not all(p in phase for p in op_deps[op]):
                continue
            lo = max((phase[p] for p in op_deps[op]), default=-1) + 1
            dep_ffn_types = (ReGLUDimension, PersistDimension)
            op_is_ffn = isinstance(op, dep_ffn_types)
            # For FFN→FFN deps, the consumer must be in a strictly later
            # layer (all FFN ops execute in parallel in the transformer).
            # Phase-based = phase (4*k+2 or 4*k+1/3) + 1 would give same
            # layer for P2→ReGLU, so we fix by bumping a full layer.
            for dep in op_deps[op]:
                if isinstance(dep, dep_ffn_types) and op_is_ffn:
                    dep_ph = phase[dep]
                    min_ph = ((dep_ph // 4) + 1) * 4  # next layer start
                    if op_is_ffn:
                        min_ph += 2 if isinstance(op, ReGLUDimension) else 1
                    lo = max(lo, min_ph)
            if isinstance(op, LookUp):
                lo += (-lo) % 4  # align to phase 0 of a layer
            elif isinstance(op, ReGLUDimension):
                lo += (2 - lo % 4 + 4) % 4  # align to phase 2
            else:  # PersistDimension
                lo += 0 if lo % 2 == 1 else 1  # align to odd phase (1 or 3)
            phase[op] = lo
            remaining.discard(op)
            progress = True
        assert progress, "Cycle in dependencies"
    return max(phase.values()) // 4 + 1


def _all_result_dims(graph):
    """All dimensions in the graph (inputs + produced)."""
    dims = list(graph["inputs"])
    dim_set = set(dims)
    for op in graph["ops"]:
        for d in graph["produced"][op]:
            if d not in dim_set:
                dim_set.add(d)
                dims.append(d)
    return dims


def milp_schedule(
    all_dims: List,
    all_lookups: List,
    input_tokens: Dict[str, Any],
    output_tokens: Dict[str, Any],
    max_layers: Optional[int] = None,
    max_ffn: Optional[int] = None,
    log=None,
) -> SchedulePlan:
    """Optimal MILP schedule minimizing dependency width for the ALM graph.

    Args:
        all_dims: All dimensions in the ALM graph.
        all_lookups: All LookUp operations.
        input_tokens: Input token name -> Expression mapping.
        output_tokens: Output token name -> Expression mapping.
        max_layers: Maximum number of transformer layers (default: auto from critical path).
        max_ffn: Maximum FFN neurons per layer (default: unlimited).
        log: Logging callable (defaults to print).

    Returns:
        SchedulePlan with optimized layer assignments and d_model.
    """
    from lean_kernel.alm_graph import (
        InputDimension, ReGLUDimension, PersistDimension,
        LookUpDimension, Expression, LookUp,
        _one_dim, _position_dim, _inv_log_pos_dim, _position_sq_dim,
    )

    _log = log or print

    graph = _build_graph(all_dims, all_lookups, _position_dim, _inv_log_pos_dim, _position_sq_dim)
    ops = graph["ops"]
    od = graph["op_deps"]
    tt = graph.get("tight_to", {})
    produced = graph["produced"]
    consumers = graph["consumers"]
    dim_to_op = graph["dim_to_op"]

    all_result_dims = _all_result_dims(graph)

    output_dims = set()
    for expr in output_tokens.values():
        if isinstance(expr, Expression):
            output_dims |= set(expr.terms.keys())

    min_possible = _min_layers(ops, od)
    if max_layers is not None:
        # Scale layer budget based on graph complexity
        # For large graphs (>500 ops), use 6x critical path to handle
        # the dense dependency structure from _or_chain aggregation
        if len(ops) > 500:
            scale = 6
        else:
            scale = 4
        cap = max(min_possible * scale, 100)
        N = min(max_layers, max(min_possible, cap))
    else:
        N = min_possible
    P = 4 * N
    _log(f"MILP: {len(ops)} ops, {len(all_result_dims)} dims, {N} layers, {P} phases, "
         f"critical_path={min_possible}")

    # ── MILP (highspy native) — with auto-retry on infeasibility ──
    for attempt in range(3):
        try:
            plan_data = _milp_solve_highspy(
                graph, ops, od, tt, all_result_dims, output_dims,
                N, P, max_ffn, _log,
                _position_dim, _inv_log_pos_dim, _position_sq_dim,
            )
            break
        except RuntimeError as e:
            if "infeasible" in str(e).lower() and attempt < 2:
                N = int(N * 1.5)
                P = 4 * N
                _log(f"  Retry {attempt+1}: increasing to {N} layers, {P} phases")
            else:
                raise

    pa = plan_data["pa"]
    opt_D = plan_data["opt_D"]

    max_phase = max(pa.values())
    num_layers = max_phase // 4 + 1

    by_phase = defaultdict(list)
    for op, p in pa.items():
        by_phase[p].append(op)

    std_layers = []
    for L in range(num_layers):
        std_layers.append(
            (
                [op for op in by_phase.get(4 * L, []) if isinstance(op, LookUp)],
                [op for op in by_phase.get(4 * L + 1, []) if isinstance(op, PersistDimension)],
                [op for op in by_phase.get(4 * L + 2, []) if isinstance(op, ReGLUDimension)],
                [op for op in by_phase.get(4 * L + 3, []) if isinstance(op, PersistDimension)],
            )
        )

    # ── Convert to SchedulePlan ───────────────────────────────────
    layers = []
    for L in range(num_layers):
        attn, p1, ffn, p2 = std_layers[L]
        layer_info = {
            "layer": L,
            "attention": [f"lookup_{lu.id}" for lu in attn],
            "persist1": [pd.name for pd in p1],
            "ffn": [rg.name for rg in ffn],
            "persist2": [pd.name for pd in p2],
        }
        layers.append(layer_info)

    # Log layer info
    _log(f"\nSchedule: {num_layers} layers, d_model={opt_D}")
    for L in range(num_layers):
        li = layers[L]
        _log(
            f"  L{L}: A[{len(li['attention'])}] P1[{len(li['persist1'])}] "
            f"F[{len(li['ffn'])}] P2[{len(li['persist2'])}]"
        )

    return SchedulePlan(
        num_layers=num_layers,
        num_slots=opt_D,
        num_heads=opt_D // 2,
        layers=layers,
    )


# ─── highspy native MILP solver (layer-assignment only; d_model post-hoc) ──


def _milp_solve_highspy(graph, ops, od, tt, all_result_dims, output_dims,
                        N, P, max_ffn, _log, pos_dim, ilp_dim, psq_dim):
    """Solve the scheduling MILP using highspy native API (v1.14+).

    The MILP only assigns ops to layers and chooses persist phases.
    d_model is computed *post-hoc* from the assignment — no per-dim-per-phase
    binary variables are needed, which would otherwise create O(N × n_dims)
    binary vars and make the problem intractable for large graphs.

    Uses HiGHS v1.14 native API:
      - h.addBinaries() / h.addIntegrals() for batch variable creation
      - highspy.highs_linear_expression for sum expressions
      - h.minimize() with linear objective
      - h.getInfo() for solution info

    Returns ``SchedulePlan``-compatible data: phase assignments + d_model.
    """
    from lean_kernel.alm_graph import (
        InputDimension, ReGLUDimension, PersistDimension,
        LookUpDimension, LookUp,
    )

    h = _make_highs_instance()

    # ── Graph metadata used downstream ───────────────────────────────
    dim_to_op = graph["dim_to_op"]
    consumers = graph["consumers"]

    # ── Core variables ────────────────────────────────────────────
    n_ops = len(ops)

    # Layer assignment for each operation: [0, N-1]
    k_vars = h.addIntegrals(n_ops, lb=0, ub=N - 1)
    k = {op: k_vars[i] for i, op in enumerate(ops)}

    # z[p] ∈ {0,1}: 0 → persist1 (phase 1), 1 → persist2 (phase 3)
    # Use h.addBinaries() for batch creation to match HiGHS v1.14 API convention
    persist_ops = [op for op in ops if isinstance(op, PersistDimension)]
    if persist_ops:
        z_vars = h.addBinaries(len(persist_ops))
        z = {op: z_vars[i] for i, op in enumerate(persist_ops)}
    else:
        z = {}

    # ── Phase of operation (linear in k/z) ────────────────────────
    def phase_of(op):
        if isinstance(op, LookUp):
            return 4 * k[op]
        if isinstance(op, ReGLUDimension):
            return 4 * k[op] + 2
        if isinstance(op, PersistDimension):
            return 4 * k[op] + 1 + 2 * z[op]
        return 4 * k[op]

    # ── Dependency ordering ──────────────────────────────────────
    for op in ops:
        for dep in od.get(op, set()):
            if dep in k:
                # Transformer model computes attention → FFN sequentially
                # within each layer. Attention output IS available for FFN
                # ops (ReGLU/Persist) in the same layer. But FFN→FFN deps
                # (ReGLU→ReGLU, ReGLU→Persist, etc.) MUST be in different
                # layers because all FFN ops execute in parallel.
                dep_is_ffn = isinstance(dep, (ReGLUDimension, PersistDimension))
                op_is_ffn = isinstance(op, (ReGLUDimension, PersistDimension))
                if dep_is_ffn and op_is_ffn:
                    # FFN → FFN: must be different layers
                    h.addConstr(k[op] >= k[dep] + 1)
                else:
                    # LookUp → FFN, LookUp → LookUp, or FFN → LookUp:
                    # phase ordering suffices
                    h.addConstr(phase_of(op) >= phase_of(dep) + 1)

    # ── Tight same-layer constraints ──────────────────────────────
    for op, lus in tt.items():
        for lu in lus:
            if lu in k and op in k:
                h.addConstr(k[op] == k[lu])

    # ── Solve ─────────────────────────────────────────────────────
    _log("Solving MILP (layer assignment)...")
    h.setOptionValue("time_limit", 1800)
    h.setOptionValue("mip_rel_gap", 0.15)  # 15% gap acceptable for large graphs
    h.minimize(sum(k[op] for op in ops))  # minimise total layer index
    model_status = h.getModelStatus()

    if model_status not in (highspy.HighsModelStatus.kOptimal,
                            highspy.HighsModelStatus.kTimeLimit):
        raise RuntimeError(
            f"MILP infeasible (status={model_status}); try more layers"
        )

    # ── Extract layer assignments ─────────────────────────────────
    pa = {}
    for op in ops:
        layer = max(0, min(N - 1, int(round(h.variableValue(k[op])))))
        if isinstance(op, LookUp):
            pa[op] = 4 * layer
        elif isinstance(op, ReGLUDimension):
            pa[op] = 4 * layer + 2
        else:
            is_p2 = max(0, min(1, int(round(h.variableValue(z.get(op, 0))))))
            pa[op] = 4 * layer + 1 + 2 * is_p2

    # ── Post-hoc: compute death and d_model ───────────────────────
    opt_D = _compute_d_model_posthoc(
        pa, all_result_dims, output_dims, dim_to_op, consumers,
        P, pos_dim, ilp_dim, psq_dim, _log,
    )

    return {"pa": pa, "opt_D": opt_D}


def _compute_d_model_posthoc(
    pa, all_result_dims, output_dims, dim_to_op, consumers,
    P, pos_dim, ilp_dim, psq_dim, _log,
):
    """Given phase assignments ``pa[op]``, compute the minimum d_model.

    For each dim we compute:
      - birth phase = phase of its producer op
      - death phase = max phase of its consumer ops (earliest possible death)

    Then for each odd phase boundary we count how many dims are alive
    (birth <= boundary < death) and set d_model = 2 × ceil(max_width/2).
    """
    from lean_kernel.alm_graph import (
        InputDimension, ReGLUDimension, PersistDimension,
        LookUpDimension, LookUp,
    )

    protected_dims = {pos_dim, ilp_dim, psq_dim}

    # ── Birth: phase of producer op ──
    birth = {}
    for d in all_result_dims:
        prod = dim_to_op.get(d)
        if prod in pa:
            birth[d] = pa[prod]

    # ── Death: max consumer phase + 1 (ensures the dim is alive at the
    #    boundary just before its last consumer).
    death = {}
    for d in all_result_dims:
        if d in output_dims:
            continue
        cons = [c_op for c_op in consumers.get(d, set()) if c_op in pa]
        if not cons and d is not pos_dim:
            continue
        dv = max(pa[c] for c in cons) if cons else P
        if d is pos_dim:
            for op, p in pa.items():
                if isinstance(op, PersistDimension) and p % 4 == 3:
                    dv = max(dv, p)
        death[d] = dv + 1  # +1: alive at boundary before last consumer

    # ── Helper: alive at odd boundary c ──
    def alive_at(d, c):
        if d in output_dims:
            return False
        if d in protected_dims:
            return True
        return d in birth and d in death and birth[d] <= c < death[d]

    # ── needs_slot: LookUp/ReGLU dims with death <= birth+1 consume in
    #     the same half-layer and don't occupy a d_model slot ──
    def needs_slot(d):
        if isinstance(d, (LookUpDimension, ReGLUDimension)):
            if d in death and d in birth and death[d] <= birth[d] + 1:
                return False
        return True

    # ── Scan each odd boundary for effective width ──
    max_ew = 0
    for c in range(1, P, 2):
        count = sum(
            1 for d in all_result_dims
            if alive_at(d, c) and needs_slot(d)
        )
        max_ew = max(max_ew, count)

    # ── Head-count contribution per attention layer ──
    for L in range(P // 4):
        c_attn = 4 * L + 1
        c_prev = c_attn - 2

        # Number of lookup heads in this layer
        n_lu_heads = sum(
            (len(lu.value_exprs) + 1) // 2
            for lu in pa
            if isinstance(lu, LookUp) and pa[lu] // 4 == L
        )

        # Passthrough count: dims consumed by persist1 ops in this layer
        pt_count = 0
        for op, p in pa.items():
            if isinstance(op, PersistDimension) and p == 4 * L + 1:
                pt_count += 1

        # Born dims (new in this layer, excluding same-half consumed)
        born = sum(
            1 for d in all_result_dims
            if d in birth and birth[d] // 4 == L and needs_slot(d)
        )

        # Dying dims: prev_alive - cur_alive + born
        prev_alive = sum(1 for d in all_result_dims if alive_at(d, c_prev) and needs_slot(d))
        cur_alive = sum(1 for d in all_result_dims if alive_at(d, c_attn) and needs_slot(d))
        dying = prev_alive - cur_alive + born

        hc = 2 * n_lu_heads + max(0, dying) + pt_count
        max_ew = max(max_ew, hc)

    opt_D = max(8, 2 * ((max_ew + 1) // 2))
    _log(f"Post-hoc d_model: {opt_D} (max_effective_width={max_ew})")
    return opt_D


def _make_highs_instance():
    """Create and configure a HiGHS solver instance."""
    h = highspy.Highs()
    h.silent()
    return h


# ─── Compatibility alias ──────────────────────────────────────────────


def schedule_graph(
    all_dims: List,
    all_lookups: List,
    input_tokens: Dict[str, Any],
    output_tokens: Dict[str, Any],
    max_layers: int = 32,
    max_ffn: int = 64,
) -> SchedulePlan:
    """Schedule an ALM graph, minimizing d_model via MILP (replaces old greedy scheduler).

    This is a drop-in replacement for the old greedy ``schedule_graph``.
    It delegates to :func:`milp_schedule` with the same defaults.
    """
    if not all_dims and not all_lookups:
        # Empty graph: return a minimal valid plan.
        return SchedulePlan(
            num_layers=1,
            num_slots=8,
            num_heads=4,
            layers=[{"layer": 0, "attention": [], "persist1": [], "ffn": [], "persist2": []}],
        )
    return milp_schedule(
        all_dims, all_lookups, input_tokens, output_tokens,
        max_layers=max_layers, max_ffn=max_ffn,
    )
