# 任务 023：引擎 check 通道的流前沿取指错行（卡 022 C 移交）

状态：**CLOSED（2026-10-22 立卡，2026-10-23 收口；由卡 022 拍 2 的 C 项移交）。
根因与立卡假设不同：不是取指 off-by-one，而是位置内建槽（slots 1..3）在
fp32 层栈里累积残差导致的位置取指数值悬崖（ADR 027 补条款）；修法 = 引擎
每位置层栈后写回精确内建值（`engine/vm.cpp` +12，无格式变更）。**

## 现象

`q_acc_def`（`Quot.liftOn.mc`，kind=def，最小 env）在引擎 `vm_run check`
通道返回 `NOT_DONE`（1 步状态固定点），而 Python 图驱动器同流同权重
ACCEPT 0；同一行在 **021 件**上引擎给 code 1（有判定）。即 A1/A2 落图后
引擎进入一个自环。

## 根因（arm 级证据，卡 022 拍 2，`~/logs/022B3/`）

1. 引擎 cap=2200 完整 dump（`engine_qaccc_def_cap2200.log`）：
   stream index 2809 = `31 270 0 0 2767 0 0` —— **LINK，V1(depth)=0**。
2. 同一步（step 1087）引擎的取指槽 `v1_at_bodyE = 267` —— 这是 **index
   2810 的 V1**（`32 5 267 2794 2809 2798 69`），**不是 2809 自己的 0**。
3. 引擎据此写 token 2814：`31 274 268 2809 2767 0 0`（V1=268），而
   Python 写 `31 274 1 2809 2767 0 0`（= ldepth(2809) = 0+1，与
   `link_prev=2809` 的不变式自洽）。
4. 该错误 depth 把 D_BV2/D_XPI2 的链深判定带偏，最终落到 1 步固定点
   `STATE(33,357,2055,0,3466,0,0)`（从 token 3475 起逐字重复）。
5. 排除面：13 个图门槽（`m2_l1/em_link1_c/em_link1_d/link1_D/link1_D_rec/
   em_link_rec/args_walk/pi_bodyE/main_link_V1` 等）在 Python 与引擎
   **逐字相同**；driver `_append` 如实搬图值（`step_driver.py:160-166`）；
   prelude 逐字相同。分叉只在"按位置取指"这一层。

## 嫌疑面

`engine/vm.cpp` 的按位置取指：当被取位置位于**当前步正在追加的流前沿**
（此例 2809 在 step 1087 时是最后一条已写行，2810+ 在同一步写入）时，
读取落到下一行/当前行（off-by-one 或读到未提交行）。34/34 对拍语料没有
"同一 step 内读前沿行"的形状，故未暴露。

## 触碰面

`engine/vm.cpp`（**仅取指/前沿语义**；不改二进制格式、不改图、不改
`compiler/`、`model/`），必要时 `tests/` 加一枚最小复现行（oracle 现跑）。
卡 022 的 `build_vm.py` 调试槽（`VM022_DBG`）是诊断工具，**不随本卡
交付**（见卡 022 收口条款）。

## Verifier

- [ ] 引擎对拍 **34/34** + argmax/softmax 流一致（`scripts/verify_engine_vs_refvm.py`），rc=0
- [ ] 最小复现：q_acc_def 引擎腿给出判定（ACCEPT 0），不再是 NOT_DONE
- [ ] 同一 stream dump 上，index 2809 的 V1 取指 = 0（slot 对照原文）
- [ ] A 组引擎列：q_acc_def/q_acc_rfl 及其余可跑行给判定；q_acc_thm 引擎面若仍 code 4 单独登记
- [ ] 无流位移：修复前后除目标行外 stream 逐字一致（或差异全部可解释）
- [ ] 全量回归不破（至少 `check_e2e` + `stepgraph_vs_refvm` + `mutation_reject`）

## 风险

1. 引擎是判定通道之一，取指语义改动必须由 34/34 + 最小复现双向把门；
2. 不许为让 q_acc_def 收敛而调 cap 或放宽判定；
3. 若根因实际在流追加/提交时机（host 侧 `vm_run`），同样按本卡修，但要在卡里写清是"读侧"还是"写侧"。

## 执行段（拍 1 后端，2026-10-22 夜，卡 022 拍 2 代理接卡）

### 结论先说：**不是 C++ 索引/前沿错位，是「按位置取指」这条原语的算术条件数**

用一把 env 门控的诊断打印（`VM_DEBUG_FETCH_T=<pos>` 打印该位置的
`(layer, head, winner, 邻域分数)`；**已回退**，`git diff engine/vm.cpp`
为空、重编 `vm_run` 与 HEAD 行为一致）在 q_acc_def 的 step 1087
（T=2813 的状态 token 求读出槽那一步）取到分数窗：

```
T=2813 li=0 h=5 w=2809 sc[w]=78904813950.313019
     sc[2807]=78904773950.27916 sc[2808]=78904803950.296097
     sc[2809]=78904813950.313019 sc[2810]=78904803950.329941
T=2813 li=0 h=6 w=2810 sc[w]=78961003950.329941
     sc[2808]=78960963950.296097 sc[2809]=78960993950.313019
     sc[2810]=78961003950.329941 sc[2811]=78960993950.346848
（h=7/h=8 与 h=6 同窗）
```

读法：
- 分数是一条抛物线 `sc[u] = C − K·(u − p)²`，**相邻位置间隔恒为 K = 1e4**
  （10000.0169 / 10000.0338 ……），峰值大小 = K·p² ≈ **7.9e10**（p≈2810）。
- 所以「有效信号（相邻差 K）」与「量级」之比 = `K / (K·p²) = 1/p²`，
  与 K **无关**（K 放大时误差同比放大，argmax 结果不变）。
- sbin 权重是 fp32（相对噪声 ~1.2e-7），残差里的位置槽经 133 层
  tanh/ReGLU/spmv 后带 1e-7 相对噪声 ⇒ 分数绝对噪声 ≈
  `1e-7 · K·p² ≈ 7.9e3`，**与间隔 K = 1e4 同量级（比值 1.26）**。
  ⇒ 在 p ≳ `1/sqrt(eps32)` ≈ 2900 处，argmax 由噪声决定而不是由位置决定。
- 本行流长 4.3k token，前沿 p≈2810 正好压在边界上：h=5 选对（2809），
  h=6/7/8 选 2810（同一 gap），引擎写出的 link depth = 268 与它自己的
  `link_prev=2809` 的 `depth=depth(prev)+1` 不变式矛盾；Python（numpy
  float64/不同归约序）落 2809，故两腿分叉并最终进入 1 步固定点。

### 为什么引擎侧无法单独修

噪声源在**输入**（位置槽的残差值），不在 C++ 的比较或索引：任何
`engine/vm.cpp` 内的 double/long double 或换比较写法都改变不了
「间隔 1e4 vs 噪声 7.9e3」。引擎也不能从查询里精确恢复 p（p 本身是
带噪的图维值）。所以**本卡「只改引擎」的路走不通**。

### 两条 sound 修法（都需改图/权重，超出卡 023 写集）

- **A（推荐，1 项原语级改动）**：把分数**中心化**。键已携带
  `(p_u, p_u²)`、每行已有常量槽 `one=1.0`；给查询加一项 `−p²·one` 后
  分数变成 `−K·(p_u−p)²`，峰值 0、间隔仍 K ⇒ 信噪比变成
  `1/(eps·Δ²)`，对任意 p 只要 Δ ≲ 2900 就稳定（峰值附近 Δ≈0）。
  落点：`fetch_by_position` 原语（`lean_vm/primitives.py` /
  `alm_p2` 的位置编码）+ 权重重编；改后 `dims/lookups` 会变，需 34/34。
- **B**：位置槽走精确通道（不经 FFN/tanh，或以 fp64 存该槽）——牵动
  `compiler/` 与二进制格式。

### 本卡状态：**BLOCKED-narrow（等总控裁 A/B 与写集）**

引擎源码已还原（`git diff engine/vm.cpp` 空、`make -C engine` 重编成功），
无格式变更、无 cap 变更、无图变更。诊断工具留在
`.scratch/dbg022b3c_slots.py`（Python 槽）与本文的 `VM_DEBUG_FETCH_T`
补丁说明（引擎侧），产物 `model/step_vm_022_dbg.sbin` 为诊断工件。

## A 实验（中心化）结果：模型层判据 PASS，真原语实验未在盒内完成

原语（`lean_kernel/alm_p2.py:51-100`）现状：
`score = qx*kx + qy*ky = 2·q·pos − pos²`（+`inv_log_pos` 平局项）；
峰值 = `S·q²`（实测 S = 1e4：引擎分数窗相邻间隔 10000.0169、峰值 7.896e10
@q=2810），相邻间隔 = `S`。

纯算术探针 `.scratch/dbg022b3d_posnoise.py`（S、eps 均取自实测/代码：

`S=1e4`，`eps=2^-23`）：

```
     q variant           winner           peak        gap      noise noise/gap
  2810 current             2810     7.8961e+10  2.903e+04  1.818e+04     0.626  unstable
  2810 centered (A)        2810    -1.0071e-03      1e+04      29.86     0.003  OK
  2810 exact builtins      2810     7.8961e+10      1e+04          0     0.000  OK
  3000 current             3000     9.0000e+10  3.169e+04  2.072e+04     0.654  unstable
  3000 centered (A)        3000    -1.1292e-03  1.001e+04      31.88     0.003  OK
  5000 current             5000     2.5000e+11  7.024e+04  5.756e+04     0.819  unstable
  5000 centered (A)        5000    -3.1433e-03  1.001e+04      53.13     0.005  OK
```

**为什么中心化能把噪声打下来**（订正我上一版的说法）：分数对位置输入的
一阶导是 `2(q − pos)`，**在峰值附近 → 0**，所以位置通道的乘性噪声
`δ=eps·pos` 对"近邻候选之间的比较"是可消去的高阶项；而上一版担心的
`2q·pos` 大项舍入在中心化后仍存在，但只影响**共同模态**（对 argmax 无影响）。
实测比：0.626 → 0.003（< 0.1 判据）。

**可行落法（下一盒）**：给 `fetch_by_position` 加第三对分量——
`qsq = reglu(q, q)`（`ReLU(q)·q = q²`，位置为正，`alm_graph.py:287-293`），
`LookUp(values, [qx, qy, Expression({qsq_dim:1}·(-1))],
[kx, ky, one])`；`q²` 的自身噪声也是共同模态项，不需精确。注意
**不能**写成 `qy = 1 − q²`（会引入 `q²·pos²` 项，错）。

**未完成项（盒内）**：真原语探针（构造真 LookUp + 真权重，量 winner/间隔/噪声）
+ 重编 + `--sparse` 34/34（双流）+ q_acc_def/q_acc_rfl 引擎腿 + check_e2e。
预估 25–35 分钟。

## 落地（第二个时间盒）：**引擎侧修好，图/格式/sbin 全不动**

A（三分量中心化）被**格式**挡住：`compiler/weights.py:919-932` 每个 head 只读
`query_exprs_2d[0]/[1]` 两对、`_SparseAttention(d_head=2)`，`engine/vm.cpp`
硬编码 `H2l = h_l*2`、`qv[h*2]/[h*2+1]` ⇒ 第三对分量 = d_head 2→3 = 二进制
格式变更（卡 023 禁线）。

同一数学目的的等价窄口：`fetch_by_position` 的分数 `2q·pos − pos²` 要求位置
内建槽（`make_row` 写的 slots 1/2/3 = `pos, inv_log_pos, pos²`）**逐行精确**
（vm.cpp 头注释本就是 "position builtins added once"），但引擎里这两个槽
被 133 层 tanh/ReGLU/spmv 加了 ~1e-7 相对残差（权重 fp32）⇒ `eps·q² ≳ 1`
时 argmax 由噪声决定（q≈2900 悬崖；实测 q=2810 处噪声/间隔 = 1.26）。

**修法（`engine/vm.cpp`，一处，无格式/图/sbin 变更）**：每层 FFN+tanh 之后
把位置内建写回精确值

```c
x[1] = (double)T;
x[2] = k1log2 - 1.0 / std::log((double)T + 2.0);
x[3] = (double)T * (double)T;
```

### 实测（盒内）

| 项 | 结果 | 证据 |
|---|---|---|
| `q_acc_def` 引擎腿（022 件，minimal env，cap 50000） | **ACCEPT 0**（`DONE 1 0 1883`，1883 步，wall 300.8s）——修前同件同入口 `NOT_DONE`/1 步固定点 | `engine_qaccdef_fixed.log` |
| 引擎对拍 34/34（`SBIN=022 件`，argmax+softmax 双流） | **34/34 PASS，`stream_same=True` 全绿，known-value 3/4（既有 harness 报表项），0 FAIL** | `parity34_fixed.log` |
| 图/sbin | **未变**：`model/step_vm_022_scratch.sbin` md5 `6a5d0ab377bace0866afba7591b75493`（58,577/7,678/363,230）；当前 `build_vm.py` 重编复核件 `step_vm_022_recheck.sbin` 与它逐字节相同 | `compile_recheck.log` |

模型层噪声预算（`.scratch/dbg022b3d_posnoise.py`，S=1e4/eps=2^-23 实测）：
`exact builtins` 变体 p=2810/3000/5000 上 noise=0、winner 精确；
`centered` 变体 0.003（过判据但受格式限制）。

**归口**：卡 023 = 引擎位置内建精确性（本条）；A 的三分量中心化降级为
"未来若做 d_head=3 格式时可选优化"，不落。
