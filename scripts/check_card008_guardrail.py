import math, os, subprocess, sys
sys.path.insert(0, "/home/xkq/Lean4-Transformer-Vm-OSS")
SBIN="/home/xkq/Lean4-Transformer-Vm-OSS/model/step_vm_new_sparse.sbin"
ENGINE="/home/xkq/Lean4-Transformer-Vm-OSS/engine/vm_run"
def run(stream, tp, tag, steps=3000):
    f=f"/tmp/g2_{tag}.txt"
    with open(f,"w") as fh:
        fh.write(f"{len(stream)}\n")
        for t in stream: fh.write(" ".join(map(str,t))+"\n")
    env=dict(os.environ); env["VM_DEBUG"]="1"; dbg=f"/tmp/g2_{tag}.dbg"
    with open(dbg,"w") as err:
        p=subprocess.run([ENGINE,SBIN,f,str(tp),str(steps)],stdout=subprocess.PIPE,text=True,env=env,stderr=err,timeout=1500)
    out=p.stdout.strip().splitlines(); n=int(out[0]); st=out[1:1+n]; v=out[1+n]
    vals=[float(l.split()[-1]) for l in open(dbg) if l.startswith("OUT ")]
    bad=sum(1 for x in vals if math.isnan(x) or math.isinf(x))
    print(f"[{tag}] verdict={v!r} rows={n} nan_inf={bad} max|OUT|={max(map(abs,vals),default=0):.3e} nonint_stream={sum(1 for l in st if 'nan' in l.lower() or 'inf' in l.lower())}")
run([(0,0,0,0,0,0,0)]*5, 0, "zeros")
run([(1,7,-1,10**15,0,0,0),(2,0,10**18,-10**15,0,0,0),(33,99999,0,0,0,0,0)], 99999, "garbage")
