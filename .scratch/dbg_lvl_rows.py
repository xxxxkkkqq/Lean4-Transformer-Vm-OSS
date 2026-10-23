"""Beat B debug harness: build the lvl graph once, run a few rows through
run_check with a small step cap, recording the (A,B) focus cycle on loop."""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("G02_ONLY", "lvl")
import tests.test_decl_injection_vs_lean as tdi
from tests.test_decl_injection_vs_lean import (
    LEVEL_ROWS, _lvl_env, _load_graph_builder,
)
from expr.tokens import Encoder
from lean_vm.step_driver import StepDriver, VMError

CAP = int(os.environ.get("DBG_CAP", "400"))
ONLY = {r.strip() for r in os.environ.get(
    "DBG_ROWS", "lvl_neg1,lvl_pg2,lvl_bf1").split(",")}

consts, ctors, const_meta = _lvl_env()
build_step_graph, _ = _load_graph_builder()
print("building graph...", flush=True)
graph, outputs = build_step_graph()
print("graph built", flush=True)

def tok(b, pos):
    if pos is None or pos <= 0 or pos >= len(b.stream):
        return f"<{pos}>"
    t = b.stream[pos]
    return f"K{t[0]}({t[1]},{t[2]},{t[3]},x{t[4]})"

for row in LEVEL_ROWS:
    cid, kind, items, lps, _t, _ty, _v = row
    if cid not in ONLY:
        continue
    if items and isinstance(items[0], tuple) and len(items[0]) == 3:
        pairs = [(t, vv) for t, vv, _k in items]
        kinds = [k for _t, _vv, k in items]
    else:
        pairs = list(items)
        kinds = [kind]
    enc = Encoder(consts, is_ctor=ctors, const_meta=const_meta)
    decls = [(enc.encode_term(t), enc.encode_term(v) if v is not None else 0)
             for t, v in pairs]
    heads = [enc.emit_univparams(l) if l else 0
             for l in (lps or [None] * len(items))]
    drv = StepDriver(enc.b, graph, outputs)
    rec = []
    orig_step = drv.step
    def rec_step():
        d, ab = orig_step()
        rec.append(ab)
        return d, ab
    drv.step = rec_step
    try:
        r1, r2 = drv.run_check(decls, max_steps=CAP, kinds=kinds,
                               lparams=heads)
        print(f"{cid}: DONE accept rc={r1},{r2} steps={drv.steps} "
              f"n={len(rec)}", flush=True)
    except VMError as ex:
        print(f"{cid}: REJECT code={ex.code} steps={drv.steps} n={len(rec)}",
              flush=True)
        print(f"    focus={getattr(ex, 'focus', None)} "
              f"{tok(drv.b, getattr(ex, 'focus', None))}  "
              f"env={getattr(ex, 'env', None)} "
              f"{tok(drv.b, getattr(ex, 'env', None))}", flush=True)
        for a, b in list(rec)[-8:]:
            print(f"    tail A={a} {tok(drv.b, a)}  B={b} {tok(drv.b, b)}",
                  flush=True)
        print("    stream tail (last 16):", flush=True)
        n = len(drv.b.stream)
        for i in range(max(0, n - 16), n):
            t = drv.b.stream[i]
            print(f"      [{i}] K{t[0]}({t[1]},{t[2]},{t[3]}) x{t[4]} "
                  f"e2={t[5]}", flush=True)
    except TimeoutError as ex:
        tail = collections.Counter(rec[-240:])
        print(f"{cid}: *** LOOP (cap {CAP}) *** last-240 (A,B) "
              f"({len(tail)} distinct):", flush=True)
        for (a, b), c in tail.most_common(6):
            print(f"    A={a} {tok(drv.b, a)}  B={b} {tok(drv.b, b)} x{c}",
                  flush=True)
    drv.step = orig_step
