"""Micro-step tracer: dump STATE + frame stack + emissions each step.
Usage: python3 scripts/trace_step.py <corpus_id> [--infer]
Reads DEFEQ_CORPUS / INFER_CORPUS by id, runs the graph, prints a trace.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expr.tokens import Encoder, decode_closure
from expr.model import (K_BVAR, K_FVAR, K_MVAR, K_SORT, K_CONST, K_APP,
                        K_LAM, K_PI, K_LET, K_LIT, K_MDATA, K_PROJ,
                        KL_ZERO, KL_SUCC, KL_MAX, KL_IMAX)
from lean_vm.build_vm import build_step_graph
from lean_vm.step_driver import StepDriver
from reference.toy_env import (TOY_CONSTS, TOY_CTORS, TOY_STRUCTS,
                               DEFEQ_CORPUS, INFER_CORPUS)

KNAME = {K_BVAR:"BVar",K_FVAR:"FVar",K_MVAR:"MVar",K_SORT:"Sort",
         K_CONST:"Const",K_APP:"App",K_LAM:"Lam",K_PI:"Pi",K_LET:"Let",
         K_LIT:"Lit",K_MDATA:"MData",K_PROJ:"Proj",KL_ZERO:"LZ",
         KL_SUCC:"LS",KL_MAX:"LMax",KL_IMAX:"LIMax",
         30:"PEND",31:"LINK",32:"FRAME",33:"STATE",34:"PI_CLO",
         13:"DIGIT",21:"NAME",22:"ENV",23:"EMETA",0:"NULL",
         202:"ACCEPT",203:"REJECT",204:"HALT"}
TASKN = {1:"WHNF",2:"NAT",3:"WALK",5:"ST",6:"INFER",7:"DEFEQ",8:"LEVEL"}


def tok_name(b, pos):
    if pos == 0:
        return "NULL"
    if pos >= len(b.stream):
        return f"?{pos}"
    t = b.stream[pos]
    K = t[0]
    return f"{pos}:{KNAME.get(K,K)}(V0={t[1]},V1={t[2]},V2={t[3]},X={t[4]},E2={t[5]},F2={t[6]})"


def dump_frames(b, D, label="D"):
    out = []
    cur = D
    hops = 0
    while cur and hops < 20:
        if cur >= len(b.stream):
            out.append(f"[{cur}>len]")
            break
        t = b.stream[cur]
        if t[0] == 32:  # FRAME
            task = TASKN.get(t[1], t[1])
            out.append(f"[{cur}]{task}(V1={t[2]},V2={t[3]},X={t[4]},E2={t[5]},F2={t[6]})")
            cur = t[3]
        else:
            out.append(f"[{cur}]?{KNAME.get(t[0],t[0])}")
            break
        hops += 1
    return f"{label}=" + " <- ".join(out)


def main():
    cid = sys.argv[1]
    is_infer = "--infer" in sys.argv
    graph, outputs = build_step_graph()
    enc = Encoder(TOY_CONSTS, is_ctor=TOY_CTORS)
    driver = StepDriver(enc.b, graph, outputs)
    if is_infer:
        term = next(t for t in INFER_CORPUS if t[0] == cid)[2]
        tp = enc.encode_term(term)
        fpos = driver._append(32, V0=6, V2=0, X=0, E2=1)
        driver.init_state(tp, 0, D=fpos)
    else:
        _, _, _, l, r = next(t for t in DEFEQ_CORPUS if t[0] == cid)
        lp = enc.encode_term(l)
        rp = enc.encode_term(r)
        fpos = driver._append(32, V0=7, V1=lp, X=0, E2=rp, F2=0)
        driver.init_state(lp, 0, D=fpos, E=rp, F=0)
    for i in range(400):
        vals = driver._eval.sync(driver.names)
        A = driver._val(vals, "A"); B = driver._val(vals, "B")
        C = driver._val(vals, "C"); D = driver._val(vals, "D")
        E = driver._val(vals, "E"); F = driver._val(vals, "F")
        done = driver._val(vals, "done"); rej = driver._val(vals, "reject")
        em = "".join(n[3:] + " " for n in
                     ("em_raw","em_pend","em_link","em_link2","em_litdig",
                      "em_frame","em_frame2","em_lithead","em_gap",
                      "em_litdig2","em_const") if driver._val(vals, n))
        pay = ""
        if driver._val(vals, "em_link"):
            pay += f" link(V0={driver._val(vals,'link_V0')},D={driver._val(vals,'link_V1')},P={driver._val(vals,'link_prev')},E={driver._val(vals,'link_env')},flag={driver._val(vals,'link_flag')})"
        if driver._val(vals, "em_link2"):
            pay += f" link2(V0={driver._val(vals,'link2_V0')},D={driver._val(vals,'link2_V1')},P={driver._val(vals,'link2_prev')},E={driver._val(vals,'link2_env')},flag={driver._val(vals,'link2_flag')})"
        if driver._val(vals, "em_frame"):
            pay += f" frk(t={TASKN.get(driver._val(vals,'frame_task'),driver._val(vals,'frame_task'))},V1={driver._val(vals,'frame_V1')},V2={driver._val(vals,'frame_V2')},X={driver._val(vals,'frame_X')},E2={driver._val(vals,'frame_E2')},F2={driver._val(vals,'frame_F2')})"
        if driver._val(vals, "em_frame2"):
            pay += f" frk2(t={TASKN.get(driver._val(vals,'frame2_task'),driver._val(vals,'frame2_task'))},V1={driver._val(vals,'frame2_V1')},V2={driver._val(vals,'frame2_V2')},X={driver._val(vals,'frame2_X')},E2={driver._val(vals,'frame2_E2')},F2={driver._val(vals,'frame2_F2')})"
        if driver._val(vals, "em_raw"):
            pay += f" raw(K={KNAME.get(driver._val(vals,'raw_K'),driver._val(vals,'raw_K'))},V0={driver._val(vals,'raw_V0')},V1={driver._val(vals,'raw_V1')},V2={driver._val(vals,'raw_V2')},X={driver._val(vals,'raw_X')},E2={driver._val(vals,'raw_E2')})"
        print(f"step {i:3d} A={A} B={B} C={C} D={D} E={E} F={F} "
              f"done={done} rej={rej} emit[{em}]")
        print(f"        focus={tok_name(enc.b, A)}")
        print(f"        {dump_frames(enc.b, D)}")
        if pay:
            print(f"        PAY{pay}")
        if done or rej:
            print(f"  -> done={done} rej={rej} result={driver._val(vals,'result_pos')}")
            break
        driver.step()


if __name__ == "__main__":
    main()
