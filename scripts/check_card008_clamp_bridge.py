#!/usr/bin/env python3
"""Card 008 runner hot-path fold check.

Current-graph dense checkpoints no longer exist (AGENTS bans dense
materialization), so the runner-vs-engine same-stream byte check runs on a
small synthetic LeanTransformer serialized to both channels (float64 CSR
/sbin for engine/vm_run; the same nn tensors for WeightRunner).

Regime A (small weights): every |act| stays <= 1000 -> old and new channels
must agree 4-way byte-for-byte (the fold changed nothing reachable).
Regime B (large weights): some |act| lands in (1000, 1e6] -> new runner ==
new engine and old runner == old engine (pairwise consistent mirrors), while
new != old exactly because of the clamp constant (the intended change).

Silenced head rows (done/reject/em_raw/em_link2/link_flag/link_F2) keep the
synthetic run inside the emission contract both channels implement (the
engine has no raw/link2 arms and zeroes link E2/F2; done=0 so both run the
fixed step count).
"""
import importlib.util
import os
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, "/home/xkq/Lean4-Transformer-Vm-OSS")
import torch

import compiler.weights as W
import model.runner as Rn
from model.runner import WeightRunner as RunnerNew

OLD_DIR = "/tmp/card008_baseline"
ENG_NEW = "/home/xkq/Lean4-Transformer-Vm-OSS/engine/vm_run"
ENG_OLD = os.path.join(OLD_DIR, "vm_run_old")

spec = importlib.util.spec_from_file_location("runner_old", os.path.join(OLD_DIR, "runner_old.py"))
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
RunnerOld = _mod.WeightRunner

NAMES = [
    "done", "reject", "reject_code", "result_pos", "A", "B", "C", "D", "E", "F",
    "em_raw", "raw_K", "raw_V0", "raw_V1", "raw_V2", "raw_X", "raw_E2",
    "em_pend", "pend_V0", "pend_prev", "pend_env",
    "em_link", "link_V0", "link_V1", "link_prev", "link_env", "link_flag", "link_F2",
    "em_link2", "link2_V0", "link2_V1", "link2_prev", "link2_env", "link2_flag", "link2_F2",
    "em_litdig", "dig_V0",
    "em_frame", "frame_task", "frame_V1", "frame_V2", "frame_X", "frame_E2", "frame_F2",
    "em_frame2", "frame2_task", "frame2_V1", "frame2_V2", "frame2_X", "frame2_E2", "frame2_F2",
    "em_lithead", "head_V0", "head_V2", "head_X",
    "em_gap", "em_litdig2", "dig2_V0", "em_const", "const_cid",
]
SILENT = {
    "done", "reject", "reject_code",
    "em_raw", "raw_K", "raw_V0", "raw_V1", "raw_V2", "raw_X", "raw_E2",
    "em_link2", "link2_V0", "link2_V1", "link2_prev", "link2_env",
    "link2_flag", "link2_F2", "link_flag", "link_F2",
}
FIELD_SLOTS = {"k": 0, "v0": 4, "v1": 5, "v2": 6, "x": 7, "e2": 8, "f2": 9}
ONE_SLOT = 11
D_MODEL, N_HEADS, N_LAYERS, D_FFN = 16, 3, 2, 10
PRE = [(33, 5, 0, 2, 0, 0, 0), (10, 3, 0, 7, 0, 0, 0), (31, 2, 1, 4, 0, 0, 0),
       (30, 9, 0, 1, 0, 0, 0), (13, 4, 0, 6, 0, 0, 0), (5, 3, 0, 0, 0, 0, 0)]
STEPS = 8


def build_model(scale, read_pos_builtins):
    """read_pos_builtins=False: zero residual-read columns 1..3 (pos,
    inv_log, pos^2) in q/k/v/ff_in/head so all |act| stay < 1000 (the old
    clamp's linear regime -> fold must be a no-op 4-way).
    True: keep pos^2 visible to ff_in/head -> |act| crosses 1000 (the pow
    bug's regime -> old and new channels must split exactly there).
    """
    torch.manual_seed(11)
    m = W.LeanTransformer(vocab_size=len(NAMES), d_model=D_MODEL,
                          n_heads=N_HEADS, n_layers=N_LAYERS, d_ffn=D_FFN)
    m.tanh_c = 1e9
    m.layer_heads = [N_HEADS] * N_LAYERS
    m.attn_erase = [[] for _ in range(N_LAYERS)]
    m.ffn_erase = [[] for _ in range(N_LAYERS)]
    m.head_tiebreak = []
    with torch.no_grad():
        for p in m.parameters():
            p.normal_(0.0, scale)
        if not read_pos_builtins:
            for a in m.attn_layers:
                for w in (a.q_weight, a.k_weight, a.v_weight):
                    w.data[:, 1:4] = 0.0
            for f in m.ff_in:
                f.weight.data[:, 1:4] = 0.0
        for i, name in enumerate(NAMES):
            if not read_pos_builtins:
                m.head.weight.data[i, 1:4] = 0.0
            if name in SILENT:
                m.head.weight.data[i] = 0.0
    m.eval()
    return m


def smat_from(t2d):
    sm = W.SparseMatrix(t2d.shape[0], t2d.shape[1])
    for i in range(t2d.shape[0]):
        sm[i] = t2d[i]
    return sm


class _WrapLin:
    def __init__(self, w):
        self.weight = w


def write_sbin(m, path):
    shim = SimpleNamespace(
        n_layers=N_LAYERS, d_model=D_MODEL, n_heads=N_HEADS, d_ffn=D_FFN,
        stop_token_id=0, layer_heads=list(m.layer_heads),
        attn_layers=[SimpleNamespace(
            q_weight=smat_from(a.q_weight.detach()),
            k_weight=smat_from(a.k_weight.detach()),
            v_weight=smat_from(a.v_weight.detach()),
            out_weight=smat_from(a.out_weight.detach()))
            for a in m.attn_layers],
        ff_in=[_WrapLin(smat_from(f.weight.detach())) for f in m.ff_in],
        ff_out=[_WrapLin(smat_from(f.weight.detach())) for f in m.ff_out],
        head=_WrapLin(smat_from(m.head.weight.detach())),
        attn_erase=m.attn_erase, ffn_erase=m.ffn_erase, head_tiebreak=[],
        runner_meta={"output_index": {n: i for i, n in enumerate(NAMES)},
                     "field_slots": FIELD_SLOTS, "one_slot": ONE_SLOT},
        nnz=lambda: 0,
    )
    # model.nnz() is only used for the log line; give it a cheap real count
    tot = sum(x.weight.nnz() if hasattr(x, "weight") else
              sum(v.nnz() for v in vars(x).values() if isinstance(v, W.SparseMatrix))
              for x in (shim.head, *shim.ff_in, *shim.ff_out))
    for al in shim.attn_layers:
        tot += sum(v.nnz() for v in vars(al).values() if isinstance(v, W.SparseMatrix))
    shim.nnz = lambda: tot
    W.save_sparse_native(shim, NAMES, path)


def run_engine(engine, sbin, term_pos, steps):
    with open("/tmp/card008_fold_stream.txt", "w") as f:
        f.write(f"{len(PRE)}\n")
        for t in PRE:
            f.write(" ".join(str(x) for x in t) + "\n")
    p = subprocess.run([engine, sbin, "/tmp/card008_fold_stream.txt",
                        str(term_pos), str(steps)],
                       capture_output=True, text=True, check=True)
    lines = p.stdout.strip().splitlines()
    n = int(lines[0])
    return [tuple(int(x) for x in ln.split()) for ln in lines[1:1 + n]]


def run_runner(RunnerCls, m, steps):
    bundle = SimpleNamespace(stream=list(PRE))
    meta = {"output_index": {n: i for i, n in enumerate(NAMES)},
            "field_slots": FIELD_SLOTS, "one_slot": ONE_SLOT}
    r = RunnerCls(bundle, m, meta)
    r.init_state(0)
    acts = []
    hooks = [f.register_forward_pre_hook(
        lambda mod, args: acts.append(float(args[0].abs().max())))
        for f in m.ff_out]
    try:
        for _ in range(steps):
            r.step()
    finally:
        for h in hooks:
            h.remove()
    return [tuple(int(x) for x in t) for t in bundle.stream], max(acts)


def main():
    old_clamp = Rn.REGLU_CLAMP
    results = {}
    for tag, scale, pos in (("A_small", 0.1, False), ("B_big", 0.1, True)):
        m = build_model(scale, pos)
        sbin = f"/tmp/card008_fold_{tag}.sbin"
        write_sbin(m, sbin)
        # raw-product magnitude (clamp disabled on the new channel; the
        # runner reads REGLU_CLAMP from its own module globals)
        Rn.REGLU_CLAMP = 1e18
        _, raw_max = run_runner(RunnerNew, m, STEPS)
        Rn.REGLU_CLAMP = old_clamp
        sr_new = run_runner(RunnerNew, m, STEPS)[0]
        sr_old = run_runner(RunnerOld, m, STEPS)[0]
        se_new = run_engine(ENG_NEW, sbin, 0, STEPS)
        se_old = run_engine(ENG_OLD, sbin, 0, STEPS)
        results[tag] = dict(raw_max=raw_max,
                            rn_eq_en=sr_new == se_new,
                            ro_eq_eo=sr_old == se_old,
                            rn_eq_ro=sr_new == sr_old,
                            en_eq_eo=se_new == se_old,
                            lens=(len(sr_new), len(se_new), len(sr_old), len(se_old)))
        print(f"[{tag}] raw_max|act|={raw_max:.1f} len(rn,en,ro,eo)={results[tag]['lens']}")
        print(f"[{tag}] new runner==new engine: {results[tag]['rn_eq_en']}")
        print(f"[{tag}] old runner==old engine: {results[tag]['ro_eq_eo']}")
        print(f"[{tag}] new==old runner: {results[tag]['rn_eq_ro']}  "
              f"new==old engine: {results[tag]['en_eq_eo']}")
        if not (results[tag]["rn_eq_en"] and results[tag]["ro_eq_eo"]):
            def first_diff(a, b):
                for i, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        return i, x, y
                return None, "len", "len"
            print("  rn/en first diff:", first_diff(sr_new, se_new))
            print("  ro/eo first diff:", first_diff(sr_old, se_old))
            print("FAIL: channel mirror broken")
            return 1
    a = results["A_small"]; b = results["B_big"]
    ok = (a["raw_max"] <= 1000.0                  # regime A is truly sub-clamp
          and a["rn_eq_ro"] and a["en_eq_eo"]     # fold changed nothing there
          and b["raw_max"] > 1000.0               # regime B crosses 1000
          and not b["rn_eq_ro"] and not b["en_eq_eo"])  # split = clamp only
    print("=== card008 fold check:", "PASS" if ok else "FAIL", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
