# ADR 013：编译通道 ReGLU 钳位常数 1e6（不版本化）

日期：2026-09-15　状态：accepted（卡 008，代理 E）
相关：docs/plans/008-compiled-channel-reglu-clamp.md、docs/handoffs/002-C-wp6.md
（C5 第 1.5/1.6 步根因证据）、docs/handoffs/004-E-card008.md、docs/VM_SPEC.md §17

## 背景

三条编译权重通道（engine/vm.cpp、compiler/weights.py、model/runner.py）在
FFN ReGLU 输出上共享硬钳位 `clamp(act, ±1000)`；图侧符号求值器
（lean_kernel/alm_p2.py:226 `vals[d] = a * max(0.0, b)`）无钳位。位置寄存器
F 经乘积臂 `reglu(gate, POS+k)` 读出，凡流位置 >998 的读数被压平到恰
1000.0：pow 例（流长 1203，合法读数 1003）在引擎第 255 步起失步，烧满
3000 步预算不 halt（引擎 33/34，known 基线见 002-C-wp6 C5）。

## 决定

1. 新常数 **C = 1e6**，单一命名常量 `REGLU_CLAMP` 的三处镜像：
   `compiler/weights.py:47`（定义，forward/forward_stream 两点使用）、
   `model/runner.py`（import 该定义——Python 侧真单源）、
   `engine/vm.cpp`（C++ 镜像，头部数学契约注释与定义点注释互指）。
2. 钳位保留在 ReGLU 输出上（卡约束 3：不顺手移除——非停机输入的数值行为
   有保护动机，且移除无判据覆盖）。
3. 不触 L4SV 版本号、不进权重：运行时行为常数，不在 sbin 字节里。
   证明：卡 008 现场 `compile_vm.py --sparse` 重编产物与晋升真值
   `cmp` 逐字节一致（18,027,726B）。
4. 文档一致性关闭：VM_SPEC 新增 §17 记录常数、上下界依据、两通道一致性
   约束（|act| ≤ C 区间内编译通道必须等于图语义；超出 C 的压平只允许出现
   在非停机垃圾路径上）。

## 边界依据

- **下界（C > 最大合法读数）**：编译通道每步至多发 10 个 token
  （vm.cpp 步环：9 条条件发射臂 + STATE），verify harness 预算 3000 步
  （scripts/verify_engine_vs_refvm.py `max_steps=3000`）⇒ 合法流位置
  ≤ n₀+30,001；runner 文档默认预算 10,000 步 ⇒ ≤ ~100,001。实测最大合法
  位置读数 1003（pow，1203 token 流，002-C-wp6 C5 第 1.6 步）。
  C=1e6 对观测值 ≥800 倍余量，对 10,000 步预算仍有 ~10 倍。
- **上界（C ≤ 2^24-1=16,777,215）**：fp32 精确整数区内所有 ≤C 的整数读数
  无舍入歧义，`llround` 归真确定；C 本身与 ±C 钳位值在 fp32 精确可表示。
- 候选比较：100k 在 runner 10k 步预算下无余量（10·10000=100k 贴界）——弃；
  2^24-1 余量更大但把 FFN 写臂的数值上限推到 1.6e7（非停机路径的爆炸保护
  变弱）且失去人类可读性——弃。1e6 为卡上指定候选，两端余量都舒服。

## 后果与风险

- 引擎 34 例首次全绿（含 pow：DONE 348 步，与符号求值器逐步一致；
  尾行见 004 handoff）。CORPUS 其余 33 例峰值 <1000，钳位改动对它们是
  恒等变换（合成四通道对拍证明 ≤1000 区间 new==old 逐字节；见 handoff）。
- 不版本化的代价：**二进制字节相同的 sbin 上，旧 vm_run 与新 vm_run 对
  act∈(1000,1e6] 的流行为不同**（旧压平、新透传）。接受理由：真值 sbin
  不变（cmp 证明），引擎二进制随仓库源码演进、artifact 真值表按
  ARCHITECTURE.md 管"当前 vm_run = 当前 vm.cpp"；差分判据通道
  （RefVM/符号求值器）无钳位，新常数只把编译通道往图语义推近
  （分歧区间从 (1000,∞) 缩到 (1e6,∞)，合法值不可达）。
- 将来若需要流长 >1e6 的语料（100k+ 步预算或 payload >1e6），必须重访本
  常数；重访时上界受 2^24-1 硬限，届时"合法读数进 (2^24,∞) 区"将迫使
  重新设计位置读出（而不是继续抬钳位）。
