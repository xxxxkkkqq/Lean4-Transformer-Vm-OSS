"""M4.3 error localization (VM_SPEC §7.4): turn a machine reject into a
pointer at the offending subterm.

The machine (build_vm / step_driver) DECIDES accept/reject; this module only
INTERPRETS that decision using data the machine already maintains — the V2
parent-pointer chain (§2, written by Encoder._fix_parent on every expr node)
and the encoded type trees. No graph change: localization is a read-only walk
over the token stream plus the graph's own run_infer result.

Two reject shapes:
  * ill-typed value — the graph's INFER rejects. When the rejecting step had a
    node focus (A > 0, e.g. unsupported-kind), that focus IS the offending
    subterm; localize reports it and its V2 path.
  * type mismatch — INFER succeeds, but the inferred type is not defeq to the
    declared type (the CK_RES verdict-false path, whose focus is the boolean
    verdict, not a node). localize diffs the two type trees position-wise and
    returns the first differing node — exactly where the mutation lives.
"""
from __future__ import annotations

from typing import Optional

from expr.tokens import decode_expr
from expr.model import (
    K_APP, K_LAM, K_PI, K_LET, K_PROJ, K_MDATA,
)


def v2_path(b, pos: int) -> list[int]:
    """Walk the V2 parent chain from `pos` up to the tree root (V2=0)."""
    path = [pos]
    while True:
        parent = b.stream[path[-1]][3]      # field 3 = V2
        if not parent:
            break
        path.append(parent)
    return path


def _child_pairs(b, pa: int, pb: int, K: int):
    """Structural child-position pairs to recurse into for a same-kind node."""
    ta, tb = b.stream[pa], b.stream[pb]
    if K == K_APP or K in (K_LAM, K_PI):
        return [(ta[1], tb[1]), (ta[2], tb[2])]        # V0, V1
    if K == K_LET:
        return [(ta[1], tb[1]), (ta[2], tb[2]), (ta[4], tb[4])]  # V0,V1,X
    if K == K_PROJ:
        return [(ta[4], tb[4])]                         # child in X
    if K == K_MDATA:
        return [(ta[1], tb[1])]                         # child in V0
    return []                                           # const/lit/sort/bvar


def diff_pos(b, pa: int, pb: int) -> Optional[tuple[int, int]]:
    """First position pair where the two encoded subterms differ, or None if
    they are equal. Descends same-kind children so the returned pair is the
    deepest common-prefix divergence (the culprit node), not just the roots."""
    if decode_expr(b, pa) == decode_expr(b, pb):
        return None
    ka, kb = b.stream[pa][0], b.stream[pb][0]
    if ka != kb:
        return (pa, pb)
    for ca, cb in _child_pairs(b, pa, pb, ka):
        d = diff_pos(b, ca, cb)
        if d is not None:
            return d
    # same kind, children all equal, but the nodes differ (cid / literal
    # value / level / bvar index) — the divergence is here
    return (pa, pb)


def localize(b, type_root: int, val_root: int,
             inferred: Optional[tuple[int, int]] = None,
             infer_focus: int = -1) -> dict:
    """Produce a localization record for a rejected declaration.

    inferred: (pos, env) from the graph's run_infer when INFER succeeded, else
    None. infer_focus: the machine's focus A at an INFER-time reject (may be 0
    for a verdict-false reject, or >0 for a node-level reject)."""
    if inferred is None:
        off = infer_focus if infer_focus and infer_focus > 0 else val_root
        path = v2_path(b, off)
        return {"kind": "ill_typed",
                "offending_pos": off,
                "offending_expr": decode_expr(b, off),
                "path": path, "root": path[-1]}
    ipos = inferred[0]
    d = diff_pos(b, ipos, type_root)
    if d is None:
        # machine rejected but the two types decode equal — a defeq subtlety
        # (binder/proj) below structural equality; report the roots.
        d = (ipos, type_root)
    ip, dp = d
    path = v2_path(b, dp)
    return {"kind": "type_mismatch",
            "inferred_pos": ip, "inferred_expr": decode_expr(b, ip),
            "declared_pos": dp, "declared_expr": decode_expr(b, dp),
            "offending_pos": dp, "offending_expr": decode_expr(b, dp),
            "path": path, "root": path[-1]}
