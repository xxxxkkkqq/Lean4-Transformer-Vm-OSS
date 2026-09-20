# 任务 008：编译通道 ReGLU ±1000 钳位——位置读数压平（pow → 34/34）

状态：**完成**。总控五道门裁决 PASS（2026-09-15 深夜），见 docs/handoffs/004-E-card008.md 总控裁决段。引擎基线 34/34（含 pow），日常回归 pow 豁免已退役。
依赖：无（006 已晋升的真值 sbin 即是复现现场）。与卡 007 互不触碰文件，但按串行纪律排队。

## 问题（已根因，不要重新定位）

编译权重通道的 FFN ReGLU 激活有硬钳位 `clamp(act, ±1000)`，而位置寄存器 F
（流内写指针）经由 `reglu(gate, POS + k)` 乘积臂读出。凡流位置 > 998 的读数
被压平到恰 1000.0，机器从此失步不 halt。

- 三处联动实现（语义必须互相一致）：
  - `engine/vm.cpp:522-525`（C++ 引擎，注释 :14-15 记录了 "clamp +-1000" 为格式语义的一部分）
  - `compiler/weights.py:451, 516`（Python 权重侧 forward，注释 :448-450 说明动机 = 防 ReGLU 溢出，例 133·133=17689）
  - `model/runner.py:223-224`（Python 权重 runner，同一语义）
- **`lean_kernel/alm_p2.py:226` 符号求值器无钳位** ⇒ 图语义与编译通道语义存在一道未被任何测试覆盖的分歧。判据通道（差分测试/RefVM）走符号求值器，所以图侧全绿而引擎 pow 烧满 3000 步。
- 复现与证据链：`docs/handoffs/002-C-wp6.md` "C5 第 1.5/1.6 步"。签名：pow 例（流长 1203）第 255 步 F 真值 1003 → 引擎读 1000；`VM_DEBUG=1` 原始读数在 handoff 内。CORPUS 其余 33 例峰值 < 1000 不受影响。

## 目标

在保留钳位的数值保护动机（防非停机路径上乘积爆炸）的前提下，把三条编译通道
实现的钳位常数提到**不截断任何合法位置读数**的值，使引擎全 34 例（含 pow）达到
34/34，并让分歧在文档层面显式关闭。

## 设计约束（先定，再动手）

1. 新常数 C 必须是单一命名常量的三处镜像（engine/weights/runner），不许三处各自字面量漂移；值 ≤ 2^24-1（fp32 精确整数区，读数以 `llround` 归真，不得引入舍入歧义）。
2. C 必须 > 最大合法流位置。上界依据要写进注释并指到代码：引擎步数预算/流缓冲上限（`engine/vm.cpp` 的 tokens 容器增长路径；verify harness 的 3000 步预算、pow 流 1203 token）。10·10^5 量级候选：1e6（留 ≥800 倍余量且 ≤2^24）。
3. 钳位保留在 ReGLU 输出上（语义与现格式一致），不许"顺手移除"——移除会改变非停机输入下的数值行为且无判据覆盖。若设计阶段认定移除更合理，停手写 ADR 待人裁。
4. `engine/vm.cpp` 头部 :9-17 的格式描述注释（"clamp +-1000"）同步改；这属于运行时行为常数而非二进制布局，**不触 L4SV 版本号**——若发现 sbin 有任何字节变化，立即停手（说明理解错了，钳位不该进权重）。

## 涉及文件

`engine/vm.cpp`、`compiler/weights.py`、`model/runner.py`、`docs/VM_SPEC.md`（新增小节：编译通道钳位常数与其和图语义的一致性约束）、`docs/decisions/`（ADR：常数选择与不版本化的理由）、`ARCHITECTURE.md` 由总控改。

## 非目标

- 不改 `lean_vm/build_vm.py`、`lean_kernel/alm_p2.py`（图侧与符号求值器不动；本卡是编译通道向图语义对齐）。
- 不动 `ref_vm.py`（冻结）。
- 不做 fp16/bf16 复活、不做 Mathlib。

## Verifier 集

- [ ] `SBIN=<现真值> python3 -u scripts/verify_engine_vs_refvm.py` 全 34 例（**不 --skip-cases pow**）→ 34/34，known-value 4/4，argmax=softmax 34/34；原文粘贴尾行。
- [ ] 重编 sbin 后 `cmp` 与旧真值逐字节一致（证明常数未入权重）；若不同，解释并停手。
- [ ] `model/runner.py` 热路径改动按 AGENTS 给折叠前后对拍：runner vs 引擎同流一致（现有 harness 或 ≤50 行的可复用比对，若成为证据须落 `scripts/`）。
- [ ] 全量回归 19 套件绿（string cap 7500 基线；含 `reducenat_graph_vs_lean`）。
- [ ] 数值护栏：非停机路径抽 1 例（截断流/超预算步）确认不 NaN/inf、RSS 正常。

## 心跳预算

引擎单例 pow 复现约 18min/34 例全量约 25min；差分不需要（图未动）。全量收尾一次。

## 机器纪律

核 0-5 或 14-19（与总控 8-13 错开）；`setsid nohup env OMP_NUM_THREADS=3 taskset -c <seg> python3 -u … > $HOME/logs/008/…log 2>&1 < /dev/null &`；RSS>6GB 杀；小步落盘。
