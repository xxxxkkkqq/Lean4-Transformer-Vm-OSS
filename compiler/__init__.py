"""Compiler: MILP schedule + analytical weight construction for Lean 4 kernel ALM graphs.

Public API:
  - milp_schedule:        Full MILP-based schedule (minimizes d_model).
  - schedule_graph:       High-level entry point (delegates to milp_schedule).
  - SchedulePlan:         Schedule data class.
  - write_plan / load_plan: Plan serialization.
  - compute_flops:        FLOPs estimate from a plan.

Deprecated helpers (kept for reference, not used by MILP path):
  - SchedOp:              Old greedy scheduler's operation data class.
  - (internal helpers removed)
"""
from compiler.milp_scheduler import (
    milp_schedule, schedule_graph,
    SchedulePlan,
    write_plan, load_plan,
    compute_flops,
)
from compiler.milp_scheduler import SchedOp  # kept for backward compat
