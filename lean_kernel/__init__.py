"""lean_kernel — ALM graph IR and evaluation for the Lean 4 kernel VM.

This package provides:
  - alm_graph: the ALM (Append-Only Lookup Machine) graph DSL — ProgramGraph
    with five primitives (InputDimension, ReGLUDimension, PersistDimension,
    LookUpDimension, CumSumDimension)
  - alm_p2: position-keyed attention fetch plus eval_graph_sequence, the
    exact-arithmetic graph interpreter (correctness reference only)

There is NO Python port of the Lean 4 kernel here. The correctness oracle is
the real Lean 4 binary; see docs/DESIGN.md and docs/PLAN.md.
"""
