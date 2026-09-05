"""ALM (Append-Only Lookup Machine) Computation Graph DSL.

Five primitives compose into a DAG that encodes a deterministic computation:
  - InputDimension:    token embeddings and position values
  - ReGLUDimension:    conditional gating ReLU(b) * a
  - LookUpDimension:   attention-based retrieval from token history
  - PersistDimension:  store intermediate results in residual slots
  - CumSumDimension:   cumulative sums via attention averaging

The DSL follows the same approach as transformer-vm (Percepta-Core), which
encodes a WASM VM into transformer weights. Here it is used to encode the
Lean 4 kernel VM (see docs/DESIGN.md and docs/PLAN.md).

Evaluation paths:
  - eval_graph_sequence (lean_kernel/alm_p2.py): exact-arithmetic graph
    interpreter. Correctness reference only — not the product engine.
  - compiler/weights.py + milp_scheduler.py: analytical compilation of a
    ProgramGraph into transformer weights (the product engine path).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set, Callable, Any


# ─── ALM Primitives ────────────────────────────────────────────────────────


# HARD_K controls how "sharp" the attention approximation is.
# Lower values = softer attention, higher = closer to hardmax but risk overflow.
# 1e4 is sufficient for accurate position-based retrieval without overflow.
HARD_K = 1e4
BIG = 1e20  # Clear key magnitude (must be > HARD_K but not cause overflow with HARD_K)


class Dimension:
    """Base class for all ALM dimensions.

    Each dimension represents a single scalar value that flows through
    the transformer's residual stream.
    """
    _counter = 0

    def __init__(self, name: str = None, kind: str = "generic"):
        self.id = Dimension._counter
        Dimension._counter += 1
        self.name = name or f"dim_{self.id}"
        self.kind = kind

    def __repr__(self):
        return f"{self.kind}:{self.name}[{self.id}]"

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, Dimension) and self.id == other.id


class InputDimension(Dimension):
    """A dimension whose value is set per-token (from the input embedding)."""
    def __init__(self, name: str):
        super().__init__(name, kind="input")

    def __repr__(self):
        return f"input:{self.name}[{self.id}]"


class ReGLUDimension(Dimension):
    """A dimension computed as ReLU(b) * a (one FFN neuron)."""
    def __init__(self, a_expr: "Expression", b_expr: "Expression", name: str = None):
        super().__init__(name, kind="reglu")
        self.a_expr = a_expr
        self.b_expr = b_expr


class PersistDimension(Dimension):
    """A dimension that stores a linear combination (via linear projection)."""
    def __init__(self, expr: "Expression", name: str = None):
        super().__init__(name, kind="persist")
        self.expr = expr


class LookUpDimension(Dimension):
    """A dimension computed by attention-based retrieval from previous tokens."""
    def __init__(self, lookup: "LookUp", value_index: int):
        super().__init__(f"lookup_{lookup.id}_v{value_index}", kind="lookup")
        self.lookup = lookup
        self.value_index = value_index


class CumSumDimension(Dimension):
    """A dimension that accumulates a value via cumulative sum."""
    def __init__(self, value_expr: "Expression", name: str = None):
        super().__init__(name, kind="cumsum")
        self.value_expr = value_expr


class Expression:
    """A linear combination of dimensions.

    expr = d1*c1 + d2*c2 + ... + const
    """
    __slots__ = ("terms",)

    def __init__(self, terms: Dict[Dimension, float] = None):
        if terms is None:
            self.terms = {}
        elif isinstance(terms, dict):
            self.terms = {k: v for k, v in terms.items() if v != 0}
        else:
            raise TypeError

    def copy(self) -> "Expression":
        return Expression(dict(self.terms))

    def __add__(self, other):
        if isinstance(other, (int, float)):
            if other == 0:
                return self.copy()
            return self + Expression({_one_dim: other})
        if isinstance(other, Dimension):
            other = Expression({other: 1})
        if isinstance(other, Expression):
            r = dict(self.terms)
            for d, c in other.terms.items():
                r[d] = r.get(d, 0) + c
                if r[d] == 0:
                    del r[d]
            return Expression(r)
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, (int, float)):
            if other == 0:
                return self.copy()
            return Expression({_one_dim: other}) + self
        if isinstance(other, Dimension):
            return Expression({other: 1}) + self
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, (int, float)):
            return self + (-other)
        if isinstance(other, Dimension):
            return self + Expression({other: -1})
        if isinstance(other, Expression):
            r = dict(self.terms)
            for d, c in other.terms.items():
                r[d] = r.get(d, 0) - c
                if r[d] == 0:
                    del r[d]
            return Expression(r)
        return NotImplemented

    def __rsub__(self, other):
        neg = Expression({d: -c for d, c in self.terms.items()})
        if isinstance(other, (int, float)):
            return neg + other
        if isinstance(other, Dimension):
            return Expression({other: 1}) + neg
        if isinstance(other, Expression):
            return other + neg
        return NotImplemented

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            if other == 0:
                return Expression()
            return Expression({d: c * other for d, c in self.terms.items()})
        return NotImplemented

    def __rmul__(self, other):
        if isinstance(other, (int, float)):
            return self.__mul__(other)
        return NotImplemented

    def __neg__(self):
        return Expression({d: -c for d, c in self.terms.items()})

    def __getitem__(self, dim: Dimension) -> float:
        return self.terms.get(dim, 0)

    def __setitem__(self, dim: Dimension, value: float):
        if value == 0 and dim in self.terms:
            del self.terms[dim]
        elif value != 0:
            self.terms[dim] = value

    def evaluate(self, values: Dict[Dimension, float]) -> float:
        result = 0.0
        for d, c in self.terms.items():
            if isinstance(d, InputDimension) and d.name == "one":
                result += c
            else:
                result += c * values.get(d, 0.0)
        return result

    def __repr__(self):
        if not self.terms:
            return "0"
        parts = []
        for d, c in self.terms.items():
            if c == 1:
                parts.append(str(d))
            elif c == -1:
                parts.append(f"-{d}")
            else:
                parts.append(f"{c}*{d}")
        return " + ".join(parts)


# ─── Built-in Dimensions ────────────────────────────────────────────────────


_one_dim: Optional[Dimension] = None
_position_dim: Optional[Dimension] = None
_inv_log_pos_dim: Optional[Dimension] = None
_position_sq_dim: Optional[Dimension] = None

_all_dims: List[Dimension] = []
_all_lookups: List["LookUp"] = []

LATEST_ALPHA = 0.3


def _init_builtins():
    global _one_dim, _position_dim, _inv_log_pos_dim, _position_sq_dim
    _one_dim = InputDimension("one")
    _position_dim = InputDimension("position")
    _inv_log_pos_dim = InputDimension("inv_log_pos")
    _position_sq_dim = InputDimension("position_sq")
    for d in [_one_dim, _position_dim, _inv_log_pos_dim, _position_sq_dim]:
        if d not in _all_dims:
            _all_dims.append(d)


class LookUp:
    """An attention-based retrieval operation.

    value_exprs: list of expressions to retrieve
    query_exprs_2d: [qx, qy] query expressions
    key_exprs_2d: [kx, ky] key expressions
    tie_break: "latest" or "average"
    """
    _counter = 0

    def __init__(self, value_exprs: List[Expression],
                 query_exprs_2d: List[Expression],
                 key_exprs_2d: List[Expression],
                 tie_break: str = "latest"):
        self.id = LookUp._counter
        LookUp._counter += 1
        self.name = None
        self.value_exprs = value_exprs
        self.query_exprs_2d = query_exprs_2d
        self.key_exprs_2d = key_exprs_2d
        self.tie_break = tie_break
        self.dims = [LookUpDimension(self, i) for i in range(len(value_exprs))]


def reset_graph():
    """Reset the graph state for building a new ALM computation graph."""
    global _one_dim, _position_dim, _inv_log_pos_dim, _position_sq_dim
    _all_dims.clear()
    _all_lookups.clear()
    Dimension._counter = 0
    LookUp._counter = 0
    _init_builtins()


# ─── Helper Functions ──────────────────────────────────────────────────────


def _to_expr(x) -> Expression:
    if isinstance(x, Expression):
        return x
    if isinstance(x, Dimension):
        return Expression({x: 1})
    if isinstance(x, (int, float)):
        if x == 0:
            return Expression()
        return Expression({_one_dim: x})
    raise TypeError(f"Cannot convert {type(x)} to Expression")


def reglu(a, b) -> Expression:
    """ReLU(b) * a — single ReGLU neuron (conditional gating)."""
    a_expr = _to_expr(a)
    b_expr = _to_expr(b)
    r = ReGLUDimension(a_expr, b_expr)
    _all_dims.append(r)
    return Expression({r: 1})


def stepglu(a, b) -> Expression:
    """a * step(b >= 0) — step function using two ReGLU neurons."""
    a_expr = _to_expr(a)
    b_expr = _to_expr(b)
    r1 = ReGLUDimension(a_expr, b_expr + Expression({_one_dim: 1}))
    r2 = ReGLUDimension(a_expr, b_expr)
    _all_dims.extend([r1, r2])
    return persist(Expression({r1: 1, r2: -1}))


def persist(expr, name: str = None) -> Expression:
    """Store a linear expression in a dedicated residual slot."""
    expr = _to_expr(expr)
    dim = PersistDimension(expr, name=name)
    _all_dims.append(dim)
    return Expression({dim: 1})


def and_head(indicators, bias_floor: float = 0.5) -> Expression:
    """Compose an output head row that fires when ALL `indicators` are 1.

    Each indicator is a 0/1 Expression (typically a persisted equality
    check). The result is an Expression `sum(indicators) - (n - bias_floor)`
    where n = len(indicators), so the head logit equals:
      bias_floor     when all match,
      bias_floor - 1 when one fails (and ≤ 0 in general),
      negative       otherwise.

    Use bias_floor = 0.5 (default) so the "all match" logit is > 0 but
    "one-off" is < 0, while still letting the halt indicator (logit = 1
    when idle) win when no output should fire.

    This is the D6 d_model-saving trick: instead of persisting one slot per
    output token (the chained AND), the head's linear projection computes
    the AND directly from the n indicator slots. For a vocab of V tokens
    each gated by k indicators, this saves V-k persists.
    """
    if not indicators:
        raise ValueError("and_head needs at least one indicator")
    total = indicators[0]
    for ind in indicators[1:]:
        total = total + ind
    return total + Expression({_one_dim: bias_floor - len(indicators)})


def fetch(value, query=None, key=None, clear_key=None, tie_break="latest") -> Expression:
    """Attention-based retrieval from token history."""
    is_list = isinstance(value, (list, tuple))
    values = list(value) if is_list else [value]
    value_exprs = [_to_expr(v) for v in values]
    q = _to_expr(query) if query is not None else Expression()
    k = _to_expr(key) if key is not None else Expression()
    ck = _to_expr(clear_key) if clear_key is not None else None

    one_expr = Expression({_one_dim: 1})
    kx = k * 2
    ky = -k

    if ck is not None:
        ky = ky - ck * BIG

    if tie_break == "latest":
        ky = ky + Expression({_inv_log_pos_dim: LATEST_ALPHA})
    elif tie_break == "average":
        ky = Expression({_one_dim: 1})

    query_2d = [q, one_expr]
    key_2d = [kx, ky]

    lookup = LookUp(value_exprs, query_2d, key_2d, tie_break=tie_break)
    _all_lookups.append(lookup)

    if is_list:
        return tuple(lookup.dims)
    return lookup.dims[0]


def fetch_sum(value_list):
    """Cumulative sum via attention averaging: avg * position."""
    if not isinstance(value_list, (list, tuple)):
        value_list = [value_list]
    key = Expression({_one_dim: 0})
    query = Expression({_one_dim: 0})
    avg_dims = fetch(value_list, query=query, key=key, tie_break="average")
    if not isinstance(avg_dims, tuple):
        avg_dims = (avg_dims,)
    results = [reglu(_to_expr(d), _to_expr(_position_dim)) for d in avg_dims]
    return tuple(results) if len(results) > 1 else results[0]


# ─── Program Graph ──────────────────────────────────────────────────────────


@dataclass
class ProgramGraph:
    """The captured computation graph for a program.

    Contains all dimensions, lookups, and input/output token mappings
    needed for scheduling and weight construction.
    """
    input_tokens: Dict[str, Expression]
    output_tokens: Dict[str, Expression]
    all_dims: List[Dimension] = field(default_factory=list)
    all_lookups: List[LookUp] = field(default_factory=list)

    def __post_init__(self):
        self.all_dims = list(_all_dims)
        self.all_lookups = list(_all_lookups)


# ─── Graph Analysis ─────────────────────────────────────────────────────────


def analyze_graph(graph: ProgramGraph) -> Dict[str, Any]:
    """Analyze a ProgramGraph and return statistics."""
    num_reglu = sum(1 for d in graph.all_dims if isinstance(d, ReGLUDimension))
    num_persist = sum(1 for d in graph.all_dims if isinstance(d, PersistDimension))
    num_lookup_dim = sum(1 for d in graph.all_dims if isinstance(d, LookUpDimension))
    num_input = sum(1 for d in graph.all_dims if isinstance(d, InputDimension))

    total_ops = num_reglu + num_persist + num_lookup_dim // 2
    estimated_layers = max(1, (total_ops + 3) // 4)

    d_model_estimate = max(8, num_input + num_lookup_dim // 4 + num_persist // 2)
    d_model_estimate += d_model_estimate % 2

    return {
        "num_dims": len(graph.all_dims),
        "num_input_dims": num_input,
        "num_reglu": num_reglu,
        "num_lookups": len(graph.all_lookups),
        "num_lookup_dim": num_lookup_dim,
        "num_persist": num_persist,
        "estimated_layers": estimated_layers,
        "estimated_d_model": max(8, d_model_estimate),
    }


# Initialize built-ins at module load
_init_builtins()