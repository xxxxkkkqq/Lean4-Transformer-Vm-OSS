"""Beat B corpus scan + fold-design validator (card 021 / ADR 026).

Measures, over every corpus ENV and checked-decl row reachable in the test
suite + the three M-A Mathlib closures (874 consts):

  (a) static level census: raw/normalized flatten widths, spine depths,
      node counts;
  (b) Pi-spine fold chains: replay the kernel's runtime construction
      (type_checker.cpp:144-166, RAW mk_imax chain) AND, in parallel, the
      beat-B graph fold design (case B exact imax rules on canonical
      operands; case A union-rebuild over split canonical operands).
      Assert W_graph == normalize(raw_chain) at every step — a mismatch
      anywhere means the fold design has a hole.  Record per-step union
      widths / survivor counts / subsume-dedup-flip events for the slot
      budget.

Domain sort levels: Sort-headed domains exact (s = succ L); Const-headed
via the const's declared type with positional level substitution; stuck
domains are counted and reported.
"""
import sys, os, json, collections, importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from expr.model import (LZero, LSucc, LMax, LIMax, LParam, LMVar, Sort,
                        Const, App, Lam, Pi, BVar, FVar, MVar, LitNat,
                        LitStr, Let, MData, Proj,
                        level_normalize, _lvl_push_max_args, _lvl_to_offset,
                        _lvl_is_explicit, _lvl_is_not_zero, _lvl_is_one,
                        _lvl_mk_imax, _lvl_mk_max, _lvl_lt_key,
                        _lvl_mk_succ_n)

NAME_KEY = lambda n: n
SLOTS = 8               # provisional; measured max reported below

STAT = collections.Counter()
WIDE = collections.Counter()
WIDE_SRC = {}
SIDE_WIDE = collections.Counter()
SRC_TAG = [""]
MAXW = collections.defaultdict(int)      # metric -> max
EVENTS = collections.Counter()
MISMATCH = []

# ── level helpers ────────────────────────────────────────────────────────────
def split_atoms(l):
    out = []
    _lvl_push_max_args(l, out)
    return out

def raw_split_width(l):
    return len(split_atoms(l))

def norm(l):
    return level_normalize(l, NAME_KEY)

def tree_depth(l):
    if isinstance(l, (LZero, LParam, LMVar)): return 0
    if isinstance(l, LSucc): return 1 + tree_depth(l.l)
    return 1 + max(tree_depth(l.a), tree_depth(l.b))

def spine_depth(l):
    d = 0
    while isinstance(l, LSucc):
        l, d = l.l, d + 1
    return d

# beat-B graph fold design (canonical operands in, canonical result out)
def fold_canonical(a, b):
    """the I_PIL2 fold after beat B: case B exact (kernel mk_imax on
    normalized operands), case A union-rebuild (kernel mk_max on raw sides
    then comparison-time normalize == rebuild of the split union)."""
    if not _lvl_is_not_zero(b):
        if isinstance(b, LZero):
            return b, "b-zero"
        if isinstance(a, LZero) or _lvl_is_one(a):
            return b, "a-zero/one"
        if a == b:
            return a, "eq"
        return LIMax(a, b), "imax-emit"
    if a == b:
        return a, "eq"
    ua, ub = split_atoms(a), split_atoms(b)
    EVENTS[f"sideA-{min(len(ua), 4)}"] += 1
    EVENTS[f"sideB-{min(len(ub), 4)}"] += 1
    if len(ua) + len(ub) >= 3:
        SIDE_WIDE[f"{len(ua)}+{len(ub)}:{','.join(sorted(atom_kind(x) for x in ua))}|{','.join(sorted(atom_kind(x) for x in ub))}"] += 1
    w = len(ua) + len(ub)
    EVENTS[f"union-width-{min(w, 9)}"] += 1
    if w > SLOTS:
        EVENTS["fallback-raw-pairwise"] += 1
        return _lvl_mk_max(a, b), "fallback"
    r = rebuild(ua + ub)
    return r, "rebuild"

def atom_kind(l):
    b, k = _lvl_to_offset(l)
    if isinstance(b, LZero): return f"Z{k}"
    if isinstance(b, (LParam, LMVar)): return f"P{k}"
    if isinstance(b, LMax): return f"M{k}"
    if isinstance(b, LIMax): return f"I{k}"
    return "?"

def rebuild(atoms):
    """normalize's Max path over pre-normalized atoms (kernel :477-509 —
    atoms are used as-is, never re-normalized)."""
    if len(atoms) >= 3:
        WIDE[",".join(sorted(atom_kind(a) for a in atoms))] += 1
        WIDE_SRC.update({tuple(sorted(atom_kind(a) for a in atoms)): SRC_TAG[0]})
    args = sorted(atoms, key=lambda x: _lvl_lt_key(x, NAME_KEY))
    rargs = []
    i = 0
    if args and _lvl_is_explicit(args[i]):
        while i + 1 < len(args) and _lvl_is_explicit(args[i + 1]):
            i += 1
        kk = _lvl_to_offset(args[i])[1]
        j = i + 1
        while j < len(args):
            if _lvl_to_offset(args[j])[1] >= kk:
                break
            j += 1
        if j < len(args):
            EVENTS["explicit-subsumed"] += 1
            i += 1
        else:
            EVENTS["explicit-survives"] += 1
    rargs.append(args[i])
    p_prev = _lvl_to_offset(args[i])
    i += 1
    while i < len(args):
        p_curr = _lvl_to_offset(args[i])
        if p_prev[0] == p_curr[0]:
            if p_prev[1] < p_curr[1]:
                EVENTS["same-base-dedup"] += 1
                p_prev = p_curr
                rargs.pop()
                rargs.append(args[i])
        else:
            p_prev = p_curr
            rargs.append(args[i])
        i += 1
    r = rargs[-1]
    for x in reversed(rargs[:-1]):
        r = _lvl_mk_max(x, r)
    EVENTS[f"survivors-{len(rargs)}"] += 1
    if len(rargs) < len(args):
        EVENTS["survivors-collapse"] += 1
    if args != [x for x in rargs]:
        pass
    return r

# ── expr walking ─────────────────────────────────────────────────────────────
def walk_levels(e, src):
    stack = [e]
    while stack:
        x = stack.pop()
        if x is None:
            continue
        if isinstance(x, Sort):
            record_level(x.level, src)
        elif isinstance(x, Const):
            for l in x.levels:
                record_level(l, src)
        elif isinstance(x, App):
            stack += [x.fn, x.arg]
        elif isinstance(x, (Lam, Pi)):
            stack += [x.domain, x.body]
        elif isinstance(x, Let):
            stack += [x.domain, x.value, x.body]
        elif isinstance(x, MData):
            stack.append(x.child)
        elif isinstance(x, Proj):
            stack.append(x.child)

def record_level(l, src):
    STAT["levels"] += 1
    n = norm(l)
    MAXW["raw-flatten-width"] = max(MAXW["raw-flatten-width"], raw_split_width(l))
    MAXW["norm-flatten-width"] = max(MAXW["norm-flatten-width"], len(split_atoms(n)))
    MAXW["spine-depth"] = max(MAXW["spine-depth"], spine_depth(l))
    MAXW["tree-depth"] = max(MAXW["tree-depth"], tree_depth(l))
    for k in ("max", "imax"):
        def cnt(t):
            if isinstance(t, LMax): return 1 + cnt(t.a) + cnt(t.b)
            if isinstance(t, LIMax): return 1 + cnt(t.a) + cnt(t.b)
            if isinstance(t, LSucc): return cnt(t.l)
            return 0
        pass
    if isinstance(l, (LMax, LIMax)):
        STAT["has-max-or-imax"] += 1
    if isinstance(l, LIMax):
        STAT["has-imax"] += 1
    if n != l:
        STAT["norm-changes-shape"] += 1

def subst_level(l, m):
    if isinstance(l, (LParam, LMVar)):
        return m.get(l.name, l)
    if isinstance(l, LSucc): return LSucc(subst_level(l.l, m))
    if isinstance(l, LMax): return LMax(subst_level(l.a, m), subst_level(l.b, m))
    if isinstance(l, LIMax): return LIMax(subst_level(l.a, m), subst_level(l.b, m))
    return l

def subst_all(e, m):
    if isinstance(e, Sort): return Sort(subst_level(e.level, m))
    if isinstance(e, Const): return Const(e.name, tuple(subst_level(l, m) for l in e.levels))
    if isinstance(e, App): return App(subst_all(e.fn, m), subst_all(e.arg, m))
    if isinstance(e, (Lam, Pi)):
        return type(e)(e.name, e.binfo, subst_all(e.domain, m), subst_all(e.body, m))
    if isinstance(e, Let):
        return Let(e.name, subst_all(e.domain, m), subst_all(e.value, m), subst_all(e.body, m))
    return e

def level_of_type(t, env, depth=0):
    if depth > 60:
        return None, "depth"
    if isinstance(t, Sort):
        return LSucc(t.level), None
    if isinstance(t, Pi):
        a, wa = level_of_type(t.domain, env, depth + 1)
        if a is None: return None, wa
        b, wb = level_of_type(t.body, env, depth + 1)
        if b is None: return None, wb
        return _lvl_mk_imax(a, b), None
    if isinstance(t, Const):
        ent = env.get(t.name)
        if ent is None or ent.get("ty") is None:
            return None, "unknown-const"
        up = ent.get("up") or []
        if len(up) != len(t.levels):
            return None, "up-arity"
        ty = subst_all(ent["ty"], dict(zip(up, t.levels)))
        return level_of_type(ty, env, depth + 1)
    return None, f"stuck:{type(t).__name__}"

def scan_pi_spines(e, env, src):
    """replay + validate fold chains for every maximal Pi-spine"""
    stack = [e]
    while stack:
        x = stack.pop()
        if x is None:
            continue
        if isinstance(x, Pi):
            doms = []
            body = x
            while isinstance(body, Pi):
                doms.append(body.domain)
                scan_pi_spines(body.domain, env, src)
                stack.append(body.body)
                body = body.body
            slevels, stuck = [], 0
            for d in doms:
                lv, why = level_of_type(d, env)
                if lv is None:
                    stuck += 1
                    EVENTS[f"dom-stuck:{why}"] += 1
                else:
                    slevels.append(lv)
                    record_level(lv, src + ":dom-sort")
            blv, bwhy = level_of_type(body, env)
            if blv is not None and not stuck:
                STAT["spines-replayed"] += 1
                MAXW["pi-spine-len"] = max(MAXW["pi-spine-len"], len(doms))
                # kernel raw chain
                r_raw = blv
                W = norm(blv)
                for s in reversed(slevels):
                    # validate: graph fold on canonical operands == normalize(raw)
                    W2, kind = fold_canonical(norm(s), W)
                    r_raw = _lvl_mk_imax(s, r_raw)
                    W_expect = norm(r_raw)
                    if W2 != W_expect:
                        MISMATCH.append((src, kind, str(W2), str(W_expect)))
                        STAT["fold-mismatch"] += 1
                    EVENTS[f"fold-{kind}"] += 1
                    record_level(r_raw, src + ":fold")
                    W = W2
        elif isinstance(x, App):
            stack += [x.fn, x.arg]
        elif isinstance(x, Lam):
            stack += [x.domain, x.body]
        elif isinstance(x, Let):
            stack += [x.domain, x.value, x.body]
        elif isinstance(x, (MData, Proj)):
            stack.append(x.child)

def scan_dump(dump, src):
    SRC_TAG[0] = src
    env = {n: ent for n, ent in dump.items()}
    for n, ent in dump.items():
        walk_levels(ent["ty"], f"{src}:{n}.ty")
        scan_pi_spines(ent["ty"], env, f"{src}:{n}.ty")
        if ent["val"] is not None:
            walk_levels(ent["val"], f"{src}:{n}.val")
            scan_pi_spines(ent["val"], env, f"{src}:{n}.val")
        meta = ent.get("meta") or {}
        for rule in meta.get("rules") or []:
            if rule.get("rhs") is not None:
                walk_levels(rule["rhs"], f"{src}:{n}.rule")
                scan_pi_spines(rule["rhs"], env, f"{src}:{n}.rule")

def scan_rows_items(items, src, env=None):
    for it in items:
        if isinstance(it, tuple):
            t = it[0]
            if isinstance(t, tuple):     # LEVEL_ROWS multi-decl chains
                scan_rows_items(t, src)
                continue
            if isinstance(t, (Sort, Pi, Const, App, Lam, Let, Proj, MData)):
                walk_levels(t, f"{src}:row")
                scan_pi_spines(t, env or {}, f"{src}:row")
            if len(it) > 1 and isinstance(it[1], (Sort, Pi, Const, App, Lam,
                                                  Let, Proj, MData)):
                walk_levels(it[1], f"{src}:row")
                scan_pi_spines(it[1], env or {}, f"{src}:row")

# ── run over corpora ─────────────────────────────────────────────────────────
from reference.olean_export import dump_env
from reference import lean_ref

print("== decl_main dump (ALL_DEFS, spawns lean) ==", flush=True)
import tests.test_decl_injection_vs_lean as tdi
scan_dump(dump_env(tdi.ALL_DEFS, tdi.MY_ROOTS), "decl_main")
scan_dump(dump_env(tdi.LEVEL_PRELUDE, tdi.LEVEL_ROOTS), "decl_lvl")
scan_dump(dump_env(tdi.IPR_PRELUDE, tdi.IPR_ROOTS), "decl_ipr")
env_lvl = dump_env(tdi.LEVEL_PRELUDE, tdi.LEVEL_ROOTS)
for row in tdi.LEVEL_ROWS:
    scan_rows_items(row[2], f"lvlrow:{row[0]}", env_lvl)
for row in tdi.ROWS:
    scan_rows_items((row[2], row[3]), f"row:{row[0]}")
for row in tdi.IPR_ROWS:
    scan_rows_items((row[1], row[2]), f"iprrow:{row[0]}")

print("== mathlib closures ==", flush=True)
for name in ("Nat_testBit_land", "Vector3_cons_fz", "Quot_liftOn_mk"):
    path = os.path.expanduser(f"~/logs/012I/closures/{name}/dump.jsonl")
    dump = {}
    with open(path) as f:
        for line in f:
            if not line.startswith("DUMPCONST "):
                continue
            d = json.loads(line[len("DUMPCONST "):])
            dump[d["n"]] = {
                "up": d.get("up") or [],
                "ty": lean_ref.json_to_expr(d["ty"]) if d.get("ty") else None,
                "val": lean_ref.json_to_expr(d["val"]) if d.get("val") else None,
                "meta": d.get("meta"),
            }
    STAT[f"closure:{name}-consts"] = len(dump)
    scan_dump(dump, f"ml:{name}")

print("\n== STAT ==")
for k, v in sorted(STAT.items()):
    print(f"  {k}: {v}")
print("\n== MAX ==")
for k, v in sorted(MAXW.items()):
    print(f"  {k}: {v}")
print("\n== EVENTS ==")
for k, v in sorted(EVENTS.items()):
    print(f"  {k}: {v}")
print("\n== WIDE UNIONS (>=3 atoms: composition -> count, first-source) ==")
for k, v in sorted(WIDE.items()):
    print(f"  {k}: {v}   first-source: {WIDE_SRC.get(tuple(k.split(',')), '?')}")
print(f"\nfold mismatches: {len(MISMATCH)}")
for m in MISMATCH[:10]:
    print("  MISMATCH:", m)
