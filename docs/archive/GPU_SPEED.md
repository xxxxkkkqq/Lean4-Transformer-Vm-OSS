# GPU 推理速度评估（Phase 8 前置调研）

目标（用户指令）：用 GPU 跑 transformer 推理做证明，测其速度能否逼近真 lean4
内核，"哪怕手写 CUDA"。本文是**实测**结论，不是估算。

## 测量环境
- GPU：NVIDIA RTX 5070 Ti（16 GB，空闲）。CPU：`taskset -c 0-3`。
- 权重：`model/step_vm.pt` / `step_vm.bin`，Phase 3 编译产物（**仅 WHNF 图**，
  不含 INFER/DEFEQ/iota/unit_like）。dtype float64，d_model=4374，n_layers=71，
  n_heads=64，params=635,747,778。
- lean4：`~/.elan/bin/lean` v4.33.1。

## 关键发现：权重是 21K 稀疏程序，不是稠密网络
```
total params 635,747,778   nonzero 21,324   density 0.003%
fp32 稠密 2543 MB   vs   非零仅 0.1 MB
```
解析编译只写入 slot→slot 的具体连接，其余全 0。**稠密 forward 每步在读
2.5 GB 的零**——这正是它慢的全部原因，而非计算量。

## 每微步耗时（同一批 WHNF 用例，结果均正确）
| 路径 | 每 micro-step | 说明 |
|---|---|---|
| lean4 内核 | ~0.02 µs（50M iota/sec） | `Nat.mul 300 300`=9万 iota 仅 1.7 ms |
| lean4 整证明（含 elaborate） | ~0.7 ms/proof | 200 条 `rfl` 摊薄启动后 |
| GPU 稠密 fp64（全流重算） | ~858 ms | O(T²)，无 KV cache |
| GPU 稠密 fp32（全流重算） | ~44 ms | 比 fp64 快 20×，仍 O(T²) |
| C++ CSR 引擎（CPU fp64，增量 KV） | ~11 ms | 已利用权重稀疏；另 +4.4 s 载入 5 GB |
| StepDriver（Python 图重放） | ~200 ms | 参考实现，非下限 |

## 结论：与 lean4 内核"一个水平"架构性不可达
1. **顺序依赖**：每个 micro-step 依赖上一步，单条证明内无并行；lean4 的 iota
   是 C++ 紧循环，每步 ~20 ns 且**不读任何权重**。
2. **差距随证明规模扩大**：我们的成本 = 步数 × 每步 forward；lean4 = 步数 ×
   20 ns。每步常数差 ~10⁵–10⁶×，证明越长差越大。
3. **权重读带宽不是主墙**（因为仅 21K 非零），但**残差流宽度 4374 + 71 层串行
   + 逐步同步**是。手写 CUDA 稀疏引擎（只存 21K 权、残差入 shared mem、
   CUDA-graph 整条 71 层、fp32、跨**独立证明**批量）现实可把 44 ms → 低 µs 级，
   约 10³× 提升；但即便如此，单步仍 ~10²–10³× 慢于 lean4，且批处理只在多条
   独立证明间摊薄。

**判定**：transformer-VM 的价值不在执行速度（这条永远输给 C++ 内核），而在
"内核=可微权重"这一研究产物本身。把"追平 lean4 速度"作为工程目标不成立；
可达成的最大收益是**把 21K 稀疏结构做成一等公民的引擎**（相对当前稠密 GPU
路径 ~1000×），作为 throughput/演示优化，而非 parity。

## 复现脚本
`/tmp/gpu_bench.py`（forward_stream 计时）、`/tmp/gpu_e2e.py`（端到端 WHNF
fp64/fp32）、lean4 计时见本文命令。
