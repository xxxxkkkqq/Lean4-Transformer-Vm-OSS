# ADR 027 — 引擎通道的实测规模边界（M-B「引擎通道」裁定的修正案）

状态：**ACCEPTED（2026-10-15，总控亲测，卡 012 M-C 立据）**

## 背景

ADR 024 §5/§7.3（卡 012 拍 1）裁定：3000+ cid 规模差分在 Python 求值器
结构性不可行，规模载体改走引擎通道（C++ vm_run，卡 013）。该裁定当时
只有 toy 规模（4.4k token）的引擎实测，从未在真实闭包规模上量过。
卡 012 M-C 开工前的两轮成本探针（~/logs/012MC/probe_engine_cost.log，
2026-10-15，sbin = 021 scratch 58,565 dims，核 8-13，OMP=3）补上了测量。

## 实测（原文数据点）

| 载荷 | 规模 | 实测 |
|---|---|---|
| toy WHNF/CHECK（engine 套件基线） | 4.4k token | ~4-9 s/run |
| Vector3 全环境 CHECK（trivial 重加） | 45,595 token | **>3000s 超时**（探针 R1），复跑 **>3600s 超时**（探针 step3） |
| Vector3 全环境裸 WHNF（True.intro） | 45,593 token | **>1800s 超时**（探针 step1）——纯 warmup 即不可承受 |
| Vector3 最小环境 CHECK（{True,True.intro}） | 19 token | **0.3s DONE**（19 步，判定正确） |
| 引擎 RSS @45.6k | — | 3.5GB 且随位置爬升（41min 时点读数） |

闭包编码规模（encode-only 实测）：Quot **879** / Vector3 **45,592** /
Nat.testBit_land **3,876,777** token。

## 结论（修正 ADR 024 的"引擎通道承载 3000+ cid"预期）

1. **引擎与 Python 求值器同属超线性成本类**（数据点：4.4k→45.6k 是
   10.3× token、>340× 墙钟），只是常数小得多。45.6k token 的全环境
   单例行已在小时级，Nat 闭包（3.9M token）全环境差分按此曲线
   **结构性不可行**（外推远超任何可接受窗口）——M-D 不得按"全环境
   全差分"原样排产。
2. **M-C/M-D 的通道分工修正为**：
   - 判定正确性差分：**逐例最小 env**（案例引用闭包的传递闭包 +
     inductive 的 ctors），graph/RefVM/engine 三通道全部可行（每例
     秒级）；oracle 永远在全闭包 env 上判（env-monotone：closed 声明
     的 addDecl 只查它点名的常量）——差分本身逐例实证该归约。
   - 规模证据：**Quot 全环境（879 token）引擎腿**（秒级/例）+
     本 ADR 的成本曲线（45.6k 双探针删失值 + 4.4k 基线三点）落
     VM_SPEC §19；Vector3/Nat 全环境引擎腿登记 **不可行（实测）**，
     不再作为 M-D 的验收载荷。
3. **M-D 重定义**（卡 012 M-D 条款随之修订）：全量差分 = 卡 022
   判定缺口收口后，35 行四通道在最小 env 上全绿 + Quot 全环境引擎
   腿全绿 + 增长曲线归档；不是"一个 3.9M token 闭包的全环境跑"。
4. **后续优化方向登记（非本卡义务）**：引擎 warmup 的逐位置成本
   曲线（疑似 O(N²·L) 同构）是独立优化课题——立项前先量
   位置分桶耗时（scripts/verify_engine_tasks.py 加计时探针即可），
   不许未测量就开优化卡。

## 证据文件

- ~/logs/012MC/probe_engine_cost.log（三轮探针原文）
- ~/logs/012MC/full_run.log / final_run.log（35 行四通道差分）
- .scratch/probe_mc_engine.py（探针脚本，一次性工具按 AGENTS §4 处置）
- 闭包 jsonl：~/logs/012I/closures/（M-A 证据件）

## 补条款（2026-10-23，卡 022 拍 2 实测）：位置取指的**正确性**悬崖

本 ADR 原先只量了引擎的**成本**（超线性、45.6k token 不可行）。卡 022
拍 2 在 `q_acc_def`（`Quot.liftOn.mc`，minimal env，流长 4,288 token）上
撞到一个与成本无关的**正确性**边界，必须补进本裁定：

### 现象

引擎 `check` 在该行返回 `NOT_DONE`（从 token 3475 起每步追加同一
`T_STATE(33,357,2055,0,3466,0,0)`，1 步固定点）；同流同权重下 Python
驱动器 ACCEPT 0。逐槽对照（`~/logs/022B3/engine_dbg_slots3.log`）：
13 个图门逐字相同，唯一分叉在 `link1_D`（Python 1 / 引擎 268），
根因是引擎写出的 LINK depth 比正确值大 267 —— 取自"下一行"的位置槽。

### 机制（实测分数）

`fetch_by_position` 的分数 = `2·q·pos − pos²`（`lean_kernel/alm_p2.py:51-100`），
峰值 `S·q²`、相邻候选间隔恰 `S`（实测 `S=1e4`，峰值 7.896e10 @q=2810）。
位置内建槽（slots 1..3 = pos / inv_log_pos / pos²）按设计是"每行常量、
只加一次"（`engine/vm.cpp` 头注释），但 133 层 tanh/ReGLU/spmv 在 fp32
权重下给它们叠了 ~1.2e-7 的相对残差 ⇒ 分数噪声 ≈ `eps·S·q²`。

```
eps·q² ≳ 1  ⇔  q ≳ 1/sqrt(eps32) ≈ 2900
```

实测（`.scratch/dbg022b3d_posnoise.py`，S/eps 均取自实测）：

| q | 变体 | winner | noise/gap |
|---|---|---|---|
| 2810 | 现状 | 2810 | **0.626（不稳定）** |
| 3000 | 现状 | 3000 | **0.654** |
| 5000 | 现状 | 5000 | **0.819** |
| 2810/3000/5000 | 精确内建 | 精确 | **0** |

即 **~2,900 token 是引擎通道的取指悬崖**：越过它的位置查询 argmax
由噪声决定。45.6k token 的全环境 CHECK（M-B/M-D 原拟载荷）即便成本可
接受，其**判定也不可信**——本条款把 ADR 027 §2 的"不可行"从成本
扩为成本 + 正确性两条。

### 修法（已落，无格式/图/sbin 变更）

`engine/vm.cpp` 在每位置层栈之后把 slots 1..3 写回精确内建值
（`x[1]=T; x[2]=k1log2−1/log(T+2); x[3]=T²`，与 `make_row` :563-565
逐字同式），把权重构造所依赖的"位置内建=每行常量"不变式在引擎里
真的成立。验证：34/34 对拍 `stream_same=True`、q_acc_def 引擎腿
`DONE 1 0 1883`（ACCEPT 0，1,883 步）、`check_e2e` A15/15+B15/15。

### 余量与被拒方案

- 修复后取指对任意流长精确（槽噪声=0）；图侧 fp32 权重下若未来提高
  位置动态范围（>2^24 级、fp16），需重估。
- **被拒：三分量中心化**（query 加 `−q²`，使分数 `−(p−q)²`）。数学上
  更稳（噪声/间隔 0.003），但 `compiler/weights.py:919-932` 每个 head
  只吃两对 `query_exprs_2d`、`_SparseAttention(d_head=2)`、引擎硬编码
  `H2l=h_l*2` ⇒ d_head 2→3 = 二进制格式变更，超本卡范围。若将来把引擎
  推到 fp16/bf16（本条款的 eps 会恶化 3–4 个数量级），应优先做该中心化
  并同步格式版本化。
- Python 求值器是 float64（eps≈2.2e-16），悬崖在 ~6.7e7 位置，
  本阶段不构成风险；这也是"driver 绿、引擎红"的直接原因。
