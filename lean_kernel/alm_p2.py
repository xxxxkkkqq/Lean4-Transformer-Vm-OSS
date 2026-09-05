"""P2: Var(n) resolves to its context binder's type via attention.

Sequence layout (concrete test case):
    [BINDER_SORT_<u0>, BINDER_SORT_<u1>, ..., BINDER_SORT_<u_{N-1}>, VAR_<k>]

Semantics: VAR_k is a de Bruijn reference; Var(0) names the innermost binder
(the last BINDER token in the sequence). So VAR_k at position N should
retrieve the binder at position N-1-k and output that binder's type.

This is the first phase where attention actually does work. The previous
end-to-end pipeline never exercised attention — values were already in the
input embedding. Here the VAR token holds only the de Bruijn index; the
binder type must be retrieved by attending to an earlier token.

Why a new `fetch_by_position`
-----------------------------
The existing `fetch` in alm_graph.py builds a 2D key as (2k, -k). With a 1D
query (q, 1), the resulting score is q*2k + (-k) = k*(2q-1) — linear in k,
so argmax always lands at the extreme k (largest or smallest), NOT at k==q.
That breaks exact-match lookup.

The correct construction (used by transformer-vm) is (kx, ky) = (k, -k^2).
With query (2q, 1), score = 2qk - k^2 = -(k-q)^2 + q^2 — argmax at k=q.
For position-keyed lookups we already have `position_sq` available as a
built-in dimension, so no extra multiplication is needed.
"""

from __future__ import annotations
from typing import Dict, Any, List, Sequence, Union

from .alm_graph import (
    InputDimension, Expression, ProgramGraph, LookUp,
    reset_graph, reglu, stepglu, persist, _to_expr,
    _one_dim, _position_dim, _inv_log_pos_dim, _position_sq_dim,
    _all_dims, _all_lookups, LATEST_ALPHA, BIG,
    ReGLUDimension, PersistDimension, LookUpDimension, CumSumDimension,
)


EXPR_KIND_VAR = 1
EXPR_KIND_SORT = 2


# ─── Corrected position-keyed fetch ─────────────────────────────────────────


def fetch_by_position(
    value_exprs: Union[Expression, Sequence[Expression]],
    query,
    clear_key=None,
):
    """Attention lookup keyed by token position with exact-match scoring.

    score = qx*kx + qy*ky = 2*query*position - position^2
          = -(position - query)^2 + query^2
    Maximized at position == query.

    Returns:
        Either a single ALM dim (if value_exprs was a single expr) or a list
        of dims (one per value_expr).
    """
    one = Expression({_one_dim: 1})
    pos = Expression({_position_dim: 1})
    pos_sq = Expression({_position_sq_dim: 1})

    q = _to_expr(query)
    ck = _to_expr(clear_key) if clear_key is not None else None

    qx = q * 2
    qy = one
    kx = pos
    ky = -pos_sq

    if ck is not None:
        # CRITICAL: multiplying a multi-term `ck` by BIG (~1e20) and adding
        # back to ky causes catastrophic cancellation when the terms partially
        # cancel — small-scale signal in ky (like -pos_sq) gets eaten by the
        # +1e20 / -1e20 components in float64. Fix: if ck is multi-term, first
        # collapse it into a single persisted dimension; then `ck * BIG` is a
        # single-term expression and cancels cleanly.
        if len(ck.terms) > 1:
            ck = _to_expr(persist(ck))
        ky = ky - ck * BIG

    # Tie-break: prefer later positions (inv_log_pos grows with position)
    ky = ky + Expression({_inv_log_pos_dim: LATEST_ALPHA})

    is_list = isinstance(value_exprs, (list, tuple))
    values = list(value_exprs) if is_list else [value_exprs]
    values = [_to_expr(v) for v in values]

    lookup = LookUp(values, [qx, qy], [kx, ky], tie_break="latest")
    _all_lookups.append(lookup)
    # NB: alm_graph.LookUp.__init__ creates LookUpDimensions but does NOT add
    # them to _all_dims (unlike ReGLU/Persist created via the helper funcs).
    # We add them here so the scheduler, slot assignment, and the Python
    # evaluator all see them.
    for d in lookup.dims:
        if d not in _all_dims:
            _all_dims.append(d)
    return tuple(lookup.dims) if is_list else lookup.dims[0]


# ─── P2 ALM graph ───────────────────────────────────────────────────────────


def build_p2_var_lookup_graph(max_level: int = 4) -> ProgramGraph:
    """Build the P2 graph.

    Vocabulary:
      Inputs:
        BINDER_SORT_u  for u in [0, max_level)   — a context binder of type Sort(u)
        VAR_k          for k in [0, max_level)   — a de Bruijn reference

      Outputs:
        RESULT_SORT_v  for v in [0, max_level)   — predicted binder type level
    """
    reset_graph()

    expr_kind = InputDimension("p2_expr_kind")
    expr_v0 = InputDimension("p2_expr_val_0")
    binder_type_kind = InputDimension("p2_binder_type_kind")
    binder_type_v0 = InputDimension("p2_binder_type_v0")
    is_binder = InputDimension("p2_is_binder")
    _all_dims.extend([expr_kind, expr_v0, binder_type_kind, binder_type_v0, is_binder])

    one = Expression({_one_dim: 1})
    pos = Expression({_position_dim: 1})
    k_expr = Expression({expr_kind: 1})
    v_expr = Expression({expr_v0: 1})
    btk_expr = Expression({binder_type_kind: 1})
    btv_expr = Expression({binder_type_v0: 1})
    is_bind_expr = Expression({is_binder: 1})

    # is_var: 1 iff expr_kind == 1
    diff_var = k_expr - one * EXPR_KIND_VAR
    abs_diff_var = reglu(one * 2, diff_var) - diff_var
    is_var = persist(stepglu(one, -abs_diff_var), "p2_is_var")

    # Query position: where to attend. For VAR at position p with v0=k, we want
    # to attend to position p - k - 1 (innermost binder = Var(0) = position p-1).
    # For non-VAR tokens this expression is meaningless and we don't use the
    # result because is_var gates everything downstream.
    query_pos = pos - v_expr - one

    # clear_key: zero out non-binder tokens so VAR can't accidentally pick one
    not_binder = one - is_bind_expr

    # Attention retrieval. Note: a binder token's own `binder_type_*` slots
    # provide the value; the VAR token's slots are 0 there.
    retrieved_kind, retrieved_v0 = fetch_by_position(
        [btk_expr, btv_expr],
        query=query_pos,
        clear_key=not_binder,
    )

    # Gate retrieval result by is_var: only the VAR token should produce a
    # meaningful result. Other tokens leave residual zero in result slots.
    result_kind = persist(reglu(retrieved_kind, is_var), "p2_result_kind")
    result_v0 = persist(reglu(retrieved_v0, is_var), "p2_result_v0")

    # Build per-output match indicators
    output_tokens: Dict[str, Expression] = {}
    for v in range(max_level):
        # match the kind: result_kind == 2 (Sort)?
        diff_k = result_kind - one * EXPR_KIND_SORT
        abs_diff_k = reglu(one * 2, diff_k) - diff_k
        kind_ok = stepglu(one, -abs_diff_k)

        # match the value: result_v0 == v?
        diff_v = result_v0 - one * v
        abs_diff_v = reglu(one * 2, diff_v) - diff_v
        val_ok = stepglu(one, -abs_diff_v)

        match_v = persist(reglu(kind_ok, val_ok), f"p2_match_sort_{v}")
        output_tokens[f"RESULT_SORT_{v}"] = match_v

    # Input embeddings
    input_tokens: Dict[str, Expression] = {}
    for u in range(max_level):
        input_tokens[f"BINDER_SORT_{u}"] = Expression({
            binder_type_kind: EXPR_KIND_SORT,
            binder_type_v0: u,
            is_binder: 1,
        })
    for k in range(max_level):
        input_tokens[f"VAR_{k}"] = Expression({
            expr_kind: EXPR_KIND_VAR,
            expr_v0: k,
        })

    return ProgramGraph(input_tokens=input_tokens, output_tokens=output_tokens)


# ─── Python evaluator (handles LookUps for P2) ──────────────────────────────


def _eval_position(graph: ProgramGraph, tok_name: str, pos: int,
                   lookup_history: Dict[int, list]) -> Dict[Any, float]:
    """Evaluate every dimension at one position (causal). lookup_history is
    the per-lookup list of (pos, kx, ky, values) entries for all earlier
    positions; this position's entry is appended here (insert-then-query).
    """
    import math

    if tok_name not in graph.input_tokens:
        raise KeyError(f"Unknown input token: {tok_name}")
    vals: Dict[Any, float] = {}
    vals[_one_dim] = 1.0
    vals[_position_dim] = float(pos)
    vals[_inv_log_pos_dim] = 1.0 / math.log(2) - 1.0 / math.log(pos + 2)
    vals[_position_sq_dim] = float(pos * pos)

    for d, c in graph.input_tokens[tok_name].terms.items():
        vals[d] = vals.get(d, 0.0) + c

    # Walk dims in declaration order.
    processed_lookups: Dict[int, list] = {}
    for d in graph.all_dims:
        if d in vals:
            continue
        if isinstance(d, ReGLUDimension):
            a = d.a_expr.evaluate(vals)
            b = d.b_expr.evaluate(vals)
            vals[d] = a * max(0.0, b)
        elif isinstance(d, PersistDimension):
            vals[d] = d.expr.evaluate(vals)
        elif isinstance(d, CumSumDimension):
            vals[d] = d.value_expr.evaluate(vals)
        elif isinstance(d, LookUpDimension):
            lu = d.lookup
            if lu.id not in processed_lookups:
                # Append current entry to lookup history (insert-then-query)
                kx = lu.key_exprs_2d[0].evaluate(vals)
                ky = lu.key_exprs_2d[1].evaluate(vals)
                value_now = [v.evaluate(vals) for v in lu.value_exprs]
                lookup_history[lu.id].append((pos, kx, ky, value_now))

                qx = lu.query_exprs_2d[0].evaluate(vals)
                qy = lu.query_exprs_2d[1].evaluate(vals)
                # Hardmax over history
                best_score = -float("inf")
                best_seq = -1
                best_vals = [0.0] * len(lu.value_exprs)
                for seq, ekx, eky, evals_ in lookup_history[lu.id]:
                    score = qx * ekx + qy * eky
                    if score > best_score + 1e-9 or (
                        abs(score - best_score) <= 1e-9 and seq > best_seq
                    ):
                        best_score = score
                        best_seq = seq
                        best_vals = evals_
                processed_lookups[lu.id] = best_vals
            vals[d] = processed_lookups[lu.id][d.value_index]
        else:
            vals[d] = 0.0

    return vals


def eval_graph_sequence(
    graph: ProgramGraph,
    token_names: List[str],
) -> List[Dict[Any, float]]:
    """Evaluate the ALM graph token-by-token (causal). Returns per-position
    dict of dim values. Used to verify graph semantics independent of the
    compiled transformer.
    """
    lookup_history: Dict[int, list] = {lu.id: [] for lu in graph.all_lookups}
    return [
        _eval_position(graph, tok_name, pos, lookup_history)
        for pos, tok_name in enumerate(token_names)
    ]


class IncrementalGraphEvaluator:
    """Causal per-position evaluator that caches earlier positions. The
    driver appends tokens one micro-step at a time; re-evaluating the whole
    prefix each step is O(n^2). Tokens are append-only and each position's
    values depend only on the prefix, so earlier vals are final and only the
    new positions need computing."""

    def __init__(self, graph: ProgramGraph):
        self.graph = graph
        self.lookup_history: Dict[int, list] = {
            lu.id: [] for lu in graph.all_lookups}
        self.vals: List[Dict[Any, float]] = []

    def sync(self, token_names: List[str]) -> Dict[Any, float]:
        """Compute/return the vals dict of the LAST position."""
        for pos in range(len(self.vals), len(token_names)):
            self.vals.append(_eval_position(
                self.graph, token_names[pos], pos, self.lookup_history))
        return self.vals[-1]
