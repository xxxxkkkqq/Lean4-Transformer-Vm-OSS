"""Expression-algebra primitives for building the ALM step graph.

Moved from the retired `kernels/kernel_islands/common.py` (island era);
only the primitives lean_vm actually uses live here. The arithmetic
helpers (_mul_acc/_div_acc/…) and CommonSetup died with the islands.
"""
from __future__ import annotations

from lean_kernel.alm_graph import (
    Expression, ReGLUDimension, reglu,
    _to_expr, _one_dim, _all_dims,
)


def _stepglu_raw(a, b) -> Expression:
    """a * step(b >= 0) via 2 ReGLU dims. NOT persisted."""
    a_expr = _to_expr(a); b_expr = _to_expr(b)
    r1 = ReGLUDimension(a_expr, b_expr + Expression({_one_dim: 1}))
    r2 = ReGLUDimension(a_expr, b_expr)
    _all_dims.extend([r1, r2])
    return Expression({r1: 1, r2: -1})


def _kind_eq_raw(k_expr, k_value, one_expr) -> Expression:
    """1 if k == k_value else 0. Costs 3 ReGLU dims."""
    diff = k_expr - one_expr * k_value
    abs_diff = reglu(one_expr * 2, diff) - diff
    return _stepglu_raw(one_expr, -abs_diff)


def _value_eq_raw(v_expr, v_value, one_expr) -> Expression:
    """1 if v == v_value else 0. Costs 3 ReGLU dims."""
    diff = v_expr - one_expr * v_value
    abs_diff = reglu(one_expr * 2, diff) - diff
    return _stepglu_raw(one_expr, -abs_diff)


def _abs_diff_expr(x, y):
    """|x - y| via reglu, no persist."""
    d = _to_expr(x) - _to_expr(y)
    return reglu(Expression({_one_dim: 2}), d) - d


def _eq_expr(x, y):
    """1 if x == y else 0, no persist."""
    return _stepglu_raw(Expression({_one_dim: 1}), -_abs_diff_expr(x, y))


def _select(cond, yes_expr, no_expr):
    """cond * yes + (1-cond) * no. cond must be 0 or 1."""
    return reglu(_to_expr(yes_expr), _to_expr(cond)) + \
           reglu(_to_expr(no_expr), Expression({_one_dim:1}) - _to_expr(cond))


def _geq_expr(x, y):
    """1 if x >= y else 0."""
    return _stepglu_raw(Expression({_one_dim: 1}),
                        _to_expr(x) - _to_expr(y))
