"""Unit check: the expr/model.py normalize port must reproduce all 15
oracle-probed verdicts.  Static rows compare normalize(LA) == normalize(LB)
(kernel is_equivalent on static terms).  Fold rows build the runtime
construction chain per type_checker.cpp:144-166 (r = body level; r =
mk_imax(us[i], r) for i = n-1..0 with the RAW smart constructors), then
compare normalize(chain-result) == normalize(L)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from expr.model import (LZero, LSucc, LMax, LIMax, LParam, level_normalize,
                        _lvl_mk_imax, _lvl_mk_max)

K = lambda n: {"u": 0, "v": 1, "w": 2}[n]
Z = LZero(); U = LParam("u"); V = LParam("v"); W = LParam("w")
def TWO(): return SU(SU(LZero()))
SU = lambda l: LSucc(l); MX = lambda a, b: LMax(a, b); IM = lambda a, b: LIMax(a, b)
TWO_L = SU(SU(LZero()))
ONE = SU(Z); S2U = SU(SU(U)); S2V = SU(SU(V)); S2W = SU(SU(W))

def fold_chain(dom_levels, body_level):
    r = body_level
    for s in reversed(dom_levels):
        r = _lvl_mk_imax(s, r)
    return r

def norm(l):
    return level_normalize(l, K)

# body level: infer(Sort 1) = Sort 2 -> level 2
ALL = [
    ("pX1", IM(SU(U), ONE), MX(SU(U), ONE), False),
    ("pX2", IM(SU(U), ONE), SU(U), False),
    ("pX3", MX(SU(U), ONE), SU(U), True),
    ("pX4", MX(ONE, U), MX(U, ONE), True),
    ("pX5", IM(U, ONE), MX(U, ONE), False),
    ("pX6", IM(U, ONE), MX(ONE, U), False),
    ("pX7", IM(ONE, U), U, True),
    ("pF1", fold_chain([S2U], TWO_L), S2U, True),
    ("pF1n", fold_chain([S2U], TWO_L), SU(U), False),
    ("pF2", fold_chain([S2U, S2V], TWO_L), MX(S2U, S2V), True),
    ("pF2n", fold_chain([S2U, S2V], TWO_L), MX(U, V), False),
    ("pF3", fold_chain([S2U, S2V, S2W], TWO_L), MX(S2U, MX(S2V, S2W)), True),
    ("pF4", fold_chain([SU(MX(U, V)), S2U], TWO_L), MX(SU(MX(U, V)), S2U), True),
    ("pF4i", fold_chain([SU(MX(U, V)), S2U], TWO_L), IM(SU(MX(U, V)), S2U), False),
    ("pF4j", fold_chain([SU(MX(U, V)), S2U], TWO_L), IM(S2U, SU(MX(U, V))), False),
]

bad = 0
for rid, a, b, want in ALL:
    na, nb = norm(a), norm(b)
    got = (na == nb)
    mark = "MATCH" if got == want else "*** MISMATCH ***"
    if got != want:
        bad += 1
        print(f"{rid:6s} want={want} got={got}  na={na}  nb={nb}  {mark}")
    else:
        print(f"{rid:6s} want_equiv={want} got={got}  {mark}")
print(f"\n{len(ALL)} rows, {bad} mismatches")
