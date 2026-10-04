# 任务 012：Mathlib 规模——证明闭包抽取 + 紧凑 ENV 编码 + 端到端抽验

状态：M-A **完成（I2，2026-09-20，五道门收口）**：3 定理闭包导出（874 常量，
Nat.testBit_land 779 / Vector3.cons_fz 87 / Quot.liftOn_mk 8），874/874 元数据
addDeclWithoutChecking 往返零差异（含全部 62 inductive 与内核重算 recursor 规则），
结构测试 2196 checks rc=0（总控亲跑复验）。I1 断链验尸与资产坐标见
docs/handoffs/007-I-mathlib-closure.md。**M-B 拍 1（求值器内存画像，只读排查）
完成（2026-09-26，审核 PASS + 勘误 E1-E5 已落）**：驻留大头 =
`lean_kernel/alm_p2.py` lookup_history 元组（O(N·L)=4,495×4,440 实测三点
吻合，77%/4.7GB）；边际驻留 1.2-1.35MB/token；主推 P1 history numpy 化
（预期 6091MB→~1.5-2GB，触碰面仅 alm_p2.py）；**规模裁定：3000+ cid 差分
在 Python 求值器结构性不可行（外推 ~29GB/~100h），M-B/M-C 规模差分载体
改走引擎通道（C++ vm_run，卡 013 通道），Python 求值器保留中小 env 语义
参照**——本裁定为拍 2 排产输入，涉及 M-B verifier 口径的修订随拍 2 卡
走 ADR。M-B 拍 2（P1 优化）/M-C/M-D 待排；报告
docs/decisions/024-evaluator-memory-profile.md。

## 目标

`docs/DESIGN.md` §7.2 处方的落地：**不是**吞吐整个 Mathlib，而是
"从真实 Mathlib 证明抽依赖闭包 → 编码为 ENV → 图/引擎判定的正确性与规模
行为"端到端打通。README 已知缺陷"Mathlib has not been tried end-to-end"清零。

## 分解（M 序，每个 M 独立可验收、独立落盘）

- **M-A 闭包抽取器**：给定 Mathlib 定理名，用真 lean（`Lean.collectDependencies`
  类 API 或 import 环境遍历）取其常量依赖闭包（inductive/recursor/def/axiom +
  univ + 完整元数据），输出为现 ENV 格式。约束：闭包规模可测（常量数、
  ENV 字节数）；抽取器落 `scripts/` 成为可复用证据。
- **M-B 编码规模**：紧凑性核查——cid 稠密分配、`T_ENV_HDR`/锚点字段复用、
  影子扫描表（`_SCAN_OPS`）在万级常量下的构建成本曲线；ENV 区进入图输入
  前缀的尺寸上界估算与实测（当前 toy=35 cid → 目标 ≥3000 cid 可用）。
  **起点已知阻塞**：纯 Python 图求值器驻留在 iota 81-常量 env 上两趟实测
  228s/6010MB、464s/8006MB 越护栏（里程碑出口记录，001 lead handoff）；
  M-B 必须先做求值器内存画像与改造（驻留结构、逐步垃圾回收），目标让
  iota 大 env 差分在 ≤6GB 内可跑，作为本卡的第一个可验收子项。
  红线：禁止 materialize dense 权重；规模测试一律 `--sparse` + 最小判定集。
- **M-C 差分抽验**：从闭包定理集抽 ≥20 例（接受/拒绝/各错误类别、跨
  Quot/String/Nat 位运算/声明检查各支路），图+RefVM+引擎三通道与真 lean
  一致。语料无答案预置（验收铁律 2：期望全部 oracle 现跑）。
- **M-D 规模回归**：一个 Mathlib 闭包 ENV 的全套差分（最小 env 规则对
  本卡破例为"闭包 env"，但步数/内存护栏不放松：RSS 树峰 6GB 线、
  单例步数上限、PrivateTmp）；记录墙钟与增长曲线进 `docs/VM_SPEC.md` 新节。

## 涉及文件

`reference/olean_export.py`（闭包导出扩展）、`lean_vm/build_vm.py` 与
`expr/tokens.py`（规模侧只许改编码与扫描表，语义分支不动）、
`scripts/`（抽取器与规模 harness）、`tests/test_mathlib_closure_vs_lean.py`、
`docs/VM_SPEC.md`、`docs/ENV_FORMAT.md`、`ARCHITECTURE.md`（总控）。
`engine/*`、`compiler/*` 不动（若暴露新钳位类上限→停手立卡，卡 008 经验）。

## 心跳与内存

本卡天然超"1 分钟反馈"红线：M-B/M-D 按 AGENTS 属"最终回归"级，允许小时
预算，但开发迭代必须仍用中等闭包（几百常量）；万级只在收尾跑。
派生前 `ps --sort=-rss` 清场，闭包 ENV 构建全程盯 RSS。

## Verifier 集

- [ ] M-A：≥3 个真实 Mathlib 定理的闭包导出成功且元数据完整（inductive 字段
      逐项对真 lean `const2decl`）
- [ ] M-B：3000+ cid 闭包 ENV 编码/加载成功，成本曲线落文档
- [ ] M-C：≥20 例三通道差分全对齐（错误类别一致）
- [ ] M-D：全量回归 20 套件绿（toy 通道不破）+ 规模差分一次完整跑（原文日志）
- [ ] 硬编码扫描零新增；无答案预置（闭包内不得含期望 verdict）

## 执行段

### 拍 1：纯 Python 图求值器内存画像（后端 lane，2026-09-25）

计划清单（先落盘再干活，逐项回填）：
1. [x] 定位与考古。求值器 = `lean_kernel/alm_p2.py` 的
   `IncrementalGraphEvaluator`（`tests/test_iota_graph_vs_lean.py` 经
   `lean_vm/step_driver.py:StepDriver` 驱动；`model/runner.py` 是 torch DEV
   PROBE（ADR 005），与本通道无关，已确认）。嫌疑驻留结构（读码）：
   `vals`（每 token 位置的 persist-dim dict）、`lookup_history`（每 lookup
   每位置一条 (pos,kx,ky,values) 元组，O(N·L)）、`_mir`（每 lookup 的 numpy
   键历史镜像）、共享 graph 的 `input_tokens`。
2. [x] 外采样复跑（见下，kill 点 6474MB@285s，曲线表已落）。
3. [x] 结构画像（见下，top5 占比已落；探针 /tmp/012_memprof/，非仓库交付物）。
4. [x] 改造方案清单 → `docs/decisions/024-evaluator-memory-profile.md`
   （P1 history numpy 化主推 / P2 warm-prefix fork 推广 / P3 teardown，
   否决项与规模外推一并落 ADR）。
5. [x] （可选项）以勘误消解：所谓"4440 常量 WP3 大 env"即本 env
   （81 常量→4440 token），其 warmup 画像已由结构探针完整覆盖
   （262s/6091MB，逐块 ms/pos 曲线在案），无需另跑。

228s/6010MB 的出处（考古原文，`$HOME/logs/milestone_exit/`）：

```
# iota_large_env.log（2026-09-16 01:07）
env: 81 constants (46 custom)
A  real metadata invariants: 13 recursors checked
  [PASS] wb_a_whnf (WHNF, 15 micro-steps)
[mem-guard] wall 228.4s peak RSS 6010MB rc=-9 KILLED: RSS 6010MB > cap 6000MB

# iota_large_env_try2.log（01:22，cap 提到 8000）
env: 81 constants (46 custom)
A  real metadata invariants: 13 recursors checked
  [PASS] wb_a_whnf (WHNF, 15 micro-steps)
  [PASS] wb_b_deq (DEFEQ, 24 micro-steps)
[mem-guard] wall 463.6s peak RSS 8006MB rc=-9 KILLED: RSS 8006MB > cap 8000MB
```

log 只留存了 guard stderr 行，guard 行格式与 `scripts/run_mem_guarded.py`
输出逐字匹配，命令形状重建为
`scripts/run_mem_guarded.py --max-rss-mb 6000|8000 -- python -u tests/test_iota_graph_vs_lean.py`
（被杀点：try1 死于 case2（wb_b_deq）warmup，try2 死于 case3
（tree_node_whnf）warmup——每 case 都用新 Encoder+新 StepDriver 对同一
`build_step_graph()` 图对象重放整个 env 前缀，即 warmup 每 case 重付一遍）。

执行日志（随做随写）：

**外采样复跑**（2026-09-25，核 14-19，OMP_NUM_THREADS=3，命令）：

```
setsid nohup systemd-run --user --scope -p MemoryMax=6500M -p MemorySwapMax=0 \
  $PY -u scripts/run_mem_guarded.py --max-rss-mb 6500 --timeout 900 -- \
  env OMP_NUM_THREADS=3 taskset -c 14-19 $PY -u tests/test_iota_graph_vs_lean.py \
  > /tmp/012_memprof/rerun.log 2>&1 < /dev/null &
```

结果：stdout 与原始 try1 一致（`env: 81 constants (46 custom)` → A 组 13
recursors → `[PASS] wb_a_whnf (WHNF, 15 micro-steps)` 后无新输出）。
**kill 点：case2（wb_b_deq）warmup 中，t≈285s，外部采样器末值 RSS 6474MB**。
cgroup MemoryMax=6500M 把整个 scope（含 run_mem_guarded）一并 SIGKILL，
guard 汇总行没有打出来——峰值以外部采样器 /proc 读数为准（双限护栏的
预期行为，如实记录）。曲线（/tmp/012_memprof/rerun_rss_clean.csv，2s 采样）：

| t(s) | 0 | 20 | 40 | 60 | 80 | 100 | 120 | 140 | 160 | 180 | 200 | 220 | 240 | 258 | 278 | 284.7 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSS(MB) | 7 | 540 | 1088 | 1679 | 2132 | 2571 | 3148 | 3506 | 3897 | 4240 | 4622 | 4948 | 5301 | 5940 | 6249 | **6474→kill** |

分段增速：0-50s 27.6MB/s，50-100s 24.6，100-200s 20.4，200-240s 16.9，
240-285s 25.8（case2 起点叠加：case1 释放后 RSS 不回落，pymalloc arena
滞留 + 新分配叠加，t≈244s 处 5371→5687MB 跳变即 case1→case2 转场）。
全程单调上升、无平台期——与"驻留随位置线性增长"一致。

**静态探针**（/tmp/012_memprof/probe_static.py，81 常量 env + build_step_graph，
不跑求值，2026-09-25）输出原文：

```
[t] import 0.1s
[t] build_env (lean oracle dump) 6.7s, consts=81
graph dims total: 34468 by type: {'InputDimension': 11, 'LookUpDimension': 4554,
  'ReGLUDimension': 29826, 'PersistDimension': 77}
graph lookups: 4495
lookup value_exprs: total 4554 max 5 mean 1.013
value-count histogram: {1: 4470, 2: 3, 3: 12, 4: 8, 5: 2}
persist dims (vals dict keys per position): 77
outputs dict entries: 76
dim expr terms: n=59729 mean=2.86 p99=5 max=909
[t] Encoder 0.0s  stream N=4440 tokens
StepDriver names: 4440 input_tokens entries: 4440
eval plan nslots: 34468 ops: 34457
input_tokens expr terms: mean=3.28 max=7
```

术语勘误：里程碑记录里的"4440 常量 env"实为 **81 常量 → 4440 流 token**
（N=4440 是 token 数不是常量数）。驻留乘法结构由此确定：
`lookup_history` 条目数 = lookups × N = 4495 × 4440 ≈ **1996 万条**
（每 lookup 每位置一条 (pos,kx,ky,values) 元组，alm_p2.py `_eval_pos`
insert-then-query 协议）；`vals` 每位置仅 77 键 persist dict（预期小）；
`_mir` numpy 键镜像 ≈ 2×8B×2h×4495（预期几百 MB）。

**结构画像**（/tmp/012_memprof/probe_struct.py，2026-09-25，核 14-19；
输出原文节选，完整记录在 ADR 024 §4）：

```
[28.1s rss=773MB] case1@500: hist entries=2,247,500 nonempty_lookups=4495
  per_entry=240B hist_total~532MB vals n=500 per_dict~2264B vals~1MB
  (+floats~1MB) _mir~36MB input_tokens=4440
[105.2s rss=2701MB] case1@2000: hist entries=8,990,000 nonempty_lookups=4495
  per_entry=240B hist_total~2124MB vals n=2000 per_dict~2264B vals~4MB
  (+floats~4MB) _mir~141MB input_tokens=4440
[108.4s] GC-TOP case1@2000: list=9,017,879/827MB  tuple=9,031,275/620MB
  dict=76,123/24MB  function=87,327/13MB  Expression=72,295/3MB
  ReGLUDimension=29,826/1MB  LookUpDimension=4,554/0MB  LookUp=4,495/0MB
[270.8s rss=6091MB] case1@4440: hist entries=19,957,800 nonempty_lookups=4495
  per_entry=240B hist_total~4720MB vals n=4440 per_dict~2264B vals~10MB
  (+floats~8MB) _mir~563MB input_tokens=4440
[270.8s] case1 warmup complete peak_rss=6091MB
[274.3s rss=6149MB] case1@steps15: hist entries=20,178,055 ... _mir~563MB
[286.9s rss=721MB] after case1 free+gc.collect: rss=721MB
[558.4s rss=6095MB] case2 warmup complete rss=6095MB
[558.9s rss=6403MB] ABORT: RSS 6403MB > 6300MB (internal watchdog)
```

要点：单 case warmup 峰值即 6091MB（6GB 线被一个 case 就贴上）；
warmup ms/pos 37.7→69.8 随位置线性涨（O(N²·L)），一次 warmup 262s；
释放干净（→721MB），case2 重爬 6095MB——每 case 重付 warmup 时间与爬峰；
边际驻留 ~1.2-1.35MB/token。**驻留大头 = lookup_history 元组 77%**，
`_mir` 9%（kx/ky 双份存储），vals/input_tokens/图本体可忽略。

**拍 1 收口**：完整画像报告 + 改造方向（P1 history numpy 化 / P2
warm-prefix fork 推广 / P3 teardown + 否决项）+ M-B 规模载体建议
（3000+ cid 走引擎通道）落 `docs/decisions/024-evaluator-memory-profile.md`。
