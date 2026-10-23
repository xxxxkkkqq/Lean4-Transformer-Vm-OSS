"""Chained-I_PIL2 SA-handoff debugging: run bf1 (green) and bf2 (broken)
through run_check, dumping the per-step STATE (A..F) + the last frame token,
and print both traces side by side around the fold beats."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("G02_ONLY", "lvl")
from tests.test_decl_injection_vs_lean import (
    LEVEL_ROWS, _lvl_env, _load_graph_builder,
)
from expr.tokens import Encoder
from lean_vm.step_driver import StepDriver, VMError

CAP = int(os.environ.get("DBG_CAP", "120"))
ONLY = {r.strip() for r in os.environ.get(
    "DBG_ROWS", "lvl_bf1,lvl_bf2").split(",")}

consts, ctors, const_meta = _lvl_env()
build_step_graph, _ = _load_graph_builder()
print("building graph...", flush=True)
graph, outputs = build_step_graph()
print("graph built", flush=True)

def tok(b, pos):
    if pos is None or pos <= 0 or pos >= len(b.stream):
        return f"<{pos}>"
    t = b.stream[pos]
    return f"K{t[0]}({t[1]},{t[2]},{t[3]})"

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
    trace = []
    orig_step = drv.step
    dbg = []
    def rec_step():
        d, ab = orig_step()
        vals = drv._eval.sync(drv.names)
        g = lambda n: int(round(vals[drv.out[n]])) if n in drv.out else -1
        dbg.append((g("dbg_r1"), g("dbg_r4"), g("dbg_fb"), g("dbg_ns"),
                    g("dbg_e2")))
        trace.append((len(drv.b.stream), d, ab))
        return d, ab
    drv.step = rec_step
    try:
        drv.run_check(decls, max_steps=CAP, kinds=kinds, lparams=heads)
        print(f"{cid}: DONE accept", flush=True)
    except VMError as ex:
        print(f"{cid}: REJECT code={ex.code}", flush=True)
    except TimeoutError:
        print(f"{cid}: cap hit", flush=True)
    drv.step = orig_step
    if os.environ.get("DBG_DUMP"):
        lo, hi = (int(x) for x in os.environ["DBG_DUMP"].split(":"))
        print(f"--- {cid} stream [{lo}:{hi}] ---", flush=True)
        for i in range(lo, min(hi, len(drv.b.stream))):
            t = drv.b.stream[i]
            print(f"  [{i}] K{t[0]}({t[1]},{t[2]},{t[3]}) x{t[4]} "
                  f"e2={t[5]} f2={t[6]}", flush=True)
    print(f"--- {cid} trace (n={len(trace)}) ---", flush=True)
    for i, (a, b, c, dd, e) in enumerate(dbg):
        if a or b or c or dd >= 0 and (dd > 0 or e or a or b or c):
            print(f"  dbg[{i}] r1={a} r4={b} fb={c} ns={dd} e2={e}",
                  flush=True)
    for i, (slen, d, (A, B)) in enumerate(trace):
        # the STATE token the driver appended this beat = the last K33
        st = None
        for p in range(slen - 1, max(0, slen - 8), -1):
            t = drv.b.stream[p]
            if t[0] == 33:
                st = t
                break
        fr = None
        for p in range(slen - 1, max(0, slen - 8), -1):
            t = drv.b.stream[p]
            if t[0] == 32:
                fr = t
                break
        s = (f"A={st[1]} B={st[2]} C={st[3]} D={st[4]} E2={st[5]} "
             f"F2={st[6]}") if st else "no-state"
        f = (f"frame(task={fr[1]},foc={fr[2]},call={fr[3]},ph={fr[4]},"
             f"F2={fr[6]})") if fr else "no-frame"
        mark = ""
        if fr and fr[6] in (9, 10, 11, 12, 13):
            mark = "  <<< " + {9: "I_PIS1", 10: "I_PIL1", 11: "I_PIS2",
                               12: "I_PIL2", 13: "I_SORTEM"}[fr[6]]
        print(f"  {i:3d} slen={slen} {s}  {f}{mark}", flush=True)
