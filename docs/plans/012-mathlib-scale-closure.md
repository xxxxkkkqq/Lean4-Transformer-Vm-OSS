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
走 ADR。**M-B 拍 2（P1 history numpy 化）ACCEPTED（2026-10-04，总控收口）**：
footprint warmup 峰值 6091→**840MB**（history 44.5B/条，`_mir` 0MB，时间律
不劣化），规模上限 ~25-26k token 落 `docs/VM_SPEC.md` §19；消费测试
quot/string/defeq_cache 默认 numpy 后端 rc=0 + canary 3/3 rc=0；brec_drec
两次同值墙钟杀点 → 总控提帽 1800 亲跑真值 **rc=0，1387.2s/7813MB，
0 divergences**（+29.3% vs list 时代 1072.9s）——裁定接受（内存 7.1x 收益，
判定逐值不变由双后端 diff + 消费测试背书），机制候选（fork 物化逐条造新
元组 vs list 指针拷贝）登记 §19.4 后续优化项。M-C/M-D 待排；报告
docs/decisions/024-evaluator-memory-profile.md（E5 已标注执行）。**M-C
差分套件落地（2026-10-15，总控亲执）**：`tests/test_mathlib_closure_
vs_lean.py` 35 行四通道（oracle=mc_oracle checked-add / graph=
InjectionEnv+run_check / refvm=RefVM.check / engine=vm_run check 模式；
逐例最小 env 按 ADR 027），oracle 35/35 现跑零义务破戒（无 other 类）
；**20 行全通道对齐**（accept/alreadyDeclared/declTypeMismatch/
thmTypeIsNotProp/unknownConstant/level 等价与不等价类各有对齐行），
**15 行分歧分诊为四个根因组（A/B/C/E）→ 全部登记卡 022**（A =
binder-identity bvar defeq，三通道共有，真证明全量受影响，M-D 前置）
。引擎规模实测（45.6k token 全环境 CHECK >3600s、WHNF warmup >1800s）
落 **ADR 027**——M-B 的"引擎通道承载 3000+ cid"裁定被实测修正，
M-D 按 ADR 027 §2 重定义。

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
- [x] M-C：≥20 例三通道差分全对齐（错误类别一致）——2026-10-15 首批 35 行四通道；2026-10-23 35 行全绿（0 FAIL / 0 XFAIL / 0 XPASS，`~/logs/022B3/b8_reg/`）
- [x] M-D：规模差分终态 = 35 行 × 4 通道全绿 + Quot 全环境引擎腿（enginefull 1268 token）绿 + 分段曲线归档（VM_SPEC §19.6；Quot 5092.2s/2333MB、Vector3 559.3s、Nat 206.3s）。**26 套件全量回归**：`regression26` 盒执行中（`~/logs/lean4vm_cpu_regression/`），完成后补 rc 表
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

### 拍 2：P1 求值器 history numpy 化（后端 lane，2026-10-04）

设计依据 = ADR 024 §6 P1（审核 PASS，含 E5 前置指令）。触碰面：
`lean_kernel/alm_p2.py`、`scripts/profile_evaluator_memory.py`（新建）、
本文档、ADR 024（E5 标注）、`docs/VM_SPEC.md`（§19 规模上限）。
**tests/ 零改动**；engine/、lean_vm/、model/ 不碰。

计划清单（先落盘再干活，逐项回填命令+输出原文）：

1. [ ] 前置 E5：重建 `scripts/profile_evaluator_memory.py` 复测 harness
   （/tmp/012_memprof/ 已被清理，按 ADR §4 输出契约重建；static 结构节 +
   warmup 检查点节 + GC-TOP 可选 + 内部看门狗 + teardown 报告；用法注释、
   绝对解释器自检、mem-guard 提示）。
2. [ ] P1 本体（alm_p2.py）：`VM012_HISTORY=numpy|list` 环境旗标双后端，
   **默认 numpy**（论证：默认 list 则回归与生产永远跑旧路径，新后端成死代码，
   footprint 目标落空；两后端语义同构性由构建方式 + 双后端 diff 探针 +
   4 消费测试 + canary 验证链兜住，风险不对称性成立。ADR 019 的 VM014_WMEMO
   默认 off 是**语义风险**决策（dormant 路径），本旗标两后端判定路径逐值
   同构，风险性质不同，不构成先例冲突；list 保留为回滚开关=同款旗标格式）。
   实现：per-lookup `_HistStore`（kx/ky/va 预分配 float64 数组，倍增扩容，
   pos 由结构不变式派生 + append 时卫语句 fail-fast；数组即权威，kx/ky 不再
   有第二份——`_mir` 仅对 fork 后的普通 list 条目沿用既有镜像机制，异构条目
   兼容由此免费获得）；values 评估：每 entry 的值清单写入 va 数组行
   （~24B/entry 含 kx/ky），淘汰 240B 元组记录；`_HistStore` 提供与 list
   兼容的物化协议（`__iter__` 惰性产出 (pos,kx,ky,values) 元组、`__len__`、
   `__getitem__`），fork 方 `{i: list(h)...}` 零改动。非增量路径
   `_eval_position` 不改：其元组协议即本拍保留的公共契约，且无调用方
   （grep 证实仅 docstring 引用），语义参照地位不变。
3. [ ] 语义零变化验证（快迭代，最小图先行）：build_p2_var_lookup_graph 上
   eval_graph_sequence（参照）vs 增量求值器 numpy vs list 三方 vals 逐值
   diff 为空 + history 物化元组 diff 为空；再上 iota 81 常量 env 双后端
   真实 case token 流/判定 diff 为空 + fork 路径（物化→续跑）双后端 diff
   为空（/tmp 一次性探针）。
4. [ ] footprint 复测：probe 先跑 **list 后端**校准（应复现 ADR §4
   ~6091MB/4720MB 量级 = 探针自证），再跑 **numpy 后端**（mem-guard 6500、
   核 14-19、setsid 脱管）：峰值 RSS + history 结构占比 + 时间律
   （劣化 >+20% 即回退/优化）。
5. [ ] 4 个消费测试零改动直接跑（核 14-19、OMP_NUM_THREADS=3、帽照
   scripts/run_cpu_regression.sh 表，串行=一会话一个大 env 求值任务）：
   quot(1500|6500) → string(1500|7500) → brec_drec(1200|8000) →
   defeq_cache(2700|8000)。
6. [ ] canary 回归：check_e2e(900|4000) + ref_vs_lean(600|0) +
   level_vs_lean(600|0)。全量 23 套件留里程碑出口，声明 NOT-RUN+理由。
7. [ ] 文档：docs/VM_SPEC.md §19（Python 求值器规模上限 + 引擎通道裁定
   引用 + 旗标说明）；本卡状态行更新；ADR 024 标注 E5 已执行。

执行日志（随做随写）：

**P1 实现落盘**（2026-10-04）：`lean_kernel/alm_p2.py` 新增 `_HistStore`
（预分配 float64 kx/ky/va 数组 + 倍增扩容 + `__slots__`；append 卫语句强制
"每位置恰一 entry"不变式，pos 由 entry 下标派生不占存储；`__iter__`/`len`/
`__getitem__` 提供 (pos,kx,ky,values) 兼容物化；`storage_bytes()` 供画像）；
`IncrementalGraphEvaluator.__init__` 按 `VM012_HISTORY`（默认 numpy）选
容器，非法值 fail-fast ValueError；`_eval_pos` lookup 臂按容器类型分派
（store=数组权威路径 / 普通list=原镜像路径原样保留——fork 物化出的异构
条目因此零改动兼容）；py_compile 过。非增量 `_eval_position` 不改
（公共元组协议即其产出格式，无调用方）。

**语义探针 Part A**（/tmp/012p2/probe_sem.py，P2 小图 max_level=6）：

```
PART A OK: 3-way vals equal, histories equal, fork x4 equal, store protocol edges pass
```

三方逐值相等（eval_graph_sequence 参照 / list 后端 / numpy 后端），
history 物化（fork 消费面）相等，fork 4 组合（warm后端×fork后端）vals+
history 相等，store 协议边界（iter/getitem/负index/切片/越界）过。
中途修过一个探针自身 bug：把 warm 的全量 history 物化却只回退 vals[:P]
制造了消费方从不产生的失配状态（真协议里 warm 前缀两者等长）。

**harness 校准跑**（scripts/profile_evaluator_memory.py --backend list
--checkpoints 100，与语义探针并发同核，墙钟受扰仅供参考）：

```
graph dims total: 34671 by type: {'InputDimension': 11, 'LookUpDimension': 4586, 'ReGLUDimension': 29997, 'PersistDimension': 77}
graph lookups: 4527
[354.2s rss=6134MB] case1@4440: hist entries=20,099,880 nonempty_lookups=4527 per_entry=388B ...
[354.2s] case1 warmup complete peak_rss=6134MB
[373.0s] after teardown gc.collect: rss=725MB peak=6133MB
```

两个发现：(1) 当前图已是卡 016 态（dims 34,671/lookups 4,527，比拍 1 的
34,468/4,495 多出 016 增量）——ADR §4 的 4,495 基线按现图平移（entries
20,099,880 = 4527×4440），list 校准峰值 6134MB 与拍 1 的 6091MB 量级吻合
（+32 lookups 解释增量），探针复现成立；(2) 初版 per_entry 采样 388B 虚高
（hist_total 7437MB > 实测 RSS 6134MB，物理不可能）——根因：dict 序把多值
metadata lookup 排在最前，头部 20 个采样偏置，已改为跨全部 lookup 步进采样
（代表性 ~260B/entry：tuple 72+pos 28+kx 24+ky 24+超配 list 88+float 24）。

**语义探针 Part B**（同一探针 --iota，81 常量 iota env，真实 case，
双后端各全 warmup，2026-10-04）：

```
  [numpy] wb_a_whnf (WHNF) -> LitNat(value=10) steps=15
  [numpy] wb_b_deq (DEFEQ) -> True steps=24
  [numpy] tree_node_whnf (WHNF) -> LitNat(value=1) steps=98
  [list] wb_a_whnf (WHNF) -> LitNat(value=10) steps=15
  [list] wb_b_deq (DEFEQ) -> True steps=24
  [list] tree_node_whnf (WHNF) -> LitNat(value=1) steps=98
PART B OK: numpy vs list verdicts, steps, token streams identical on 3 iota cases
```

判定/微步数/输出 token 流双后端逐值 diff 为空；前两例步数与拍 1 复跑的
oracle 判定记录一致（wb_a_whnf 15 微步、wb_b_deq 24 微步）。
教训记录：本探针未挂 guard，list 阶段 RSS 10.2GB（numpy 残留 arena + list
warmup 叠加）——后续长跑一律 guard，不再裸跑。

**续跑计划（第 9 次代理：验证链续跑，2026-10-04；实现已 checkpoint
HEAD=3b8bf5c，语义不动，只做剩余验证与文档）**：

- R0. [x] 开工落盘本计划；field check（`ps --sort=-rss`：无本项目大 env
  进程；3.6GB pytest 为无关进程不动）。
- R1. [x] numpy footprint 复测（核心验收）：
  `scripts/profile_evaluator_memory.py --backend numpy --checkpoints 100`
  4440-token iota warmup 完整跑；systemd-run MemoryMax=4000M +
  run_mem_guarded 4000 双限，核 14-19，OMP_NUM_THREADS=3，setsid 脱管记
  pid 轮询；记录峰值 RSS / history 结构占比（对比拍 1 list 4720MB）/
  ms/pos（对比拍 1 37.7→69.8，劣化 >20% 说明原因或回退）。
  **结果（2026-10-04，/tmp/012p2_verify/footprint_numpy.log 原文）**：
  rc=0，wall 282.8s，guard 树峰 1535MB（含 build_env 真 lean oracle
  子进程瞬态 ~0.7-1.6GB），**进程内 warmup 峰值 840MB**（teardown 后
  rss=576MB）；backend 确认 `numpy (VM012_HISTORY=(unset))`。

  ```
  [4.0s rss=150MB] case1@100: hist entries=452,700 nonempty_lookups=4527
    per_entry=30.9B(arr) hist_total~13MB ... _mir~0MB input_tokens=4440 ms/pos=40.5
  [274.2s rss=840MB] case1@4440: hist entries=20,099,880 nonempty_lookups=4527
    per_entry=44.5B(arr) hist_total~852MB vals n=4440 per_dict~2264B vals~10MB
    (+floats~8MB) _mir~0MB input_tokens=4440 ms/pos=61.8
  [274.2s] case1 warmup complete peak_rss=840MB
  [274.3s] after teardown gc.collect: rss=576MB peak=840MB
  [mem-guard] wall 282.8s peak RSS 1535MB rc=0
  ```

  对比：list 校准 6134MB（entries 同 20,099,880，~260B/entry，
  hist_total~7437MB 采样偏高 / 代表性 ~4720MB）；numpy **840MB = 基线
  的 13.7%**，history 部分 44.5B/entry≈852MB（含倍增松弛，部分页未触
  达）vs list 4720MB，`_mir` 0MB（kx/ky 双份存储消除）。ADR §6-P1 预期
  "~0.9GB 驻留 / 1.5-2GB 峰值"：驻留 840MB 优于预期，树峰 1535MB 落在
  预期带下沿（差额 = oracle 子进程）。边际驻留 ~0.21MB/token（0.19
  history + 0.02 vals），6GB 线外推 ~25-26k token（≈460 常量），与 ADR
  预估 ~26k 吻合。时间律：ms/pos 40.5@100 → 61.8@4440（list 37.7 →
  69.8），头部 +7% / 尾部 −11%，全程 warmup 274.2s vs list 独占跑
  ~262-270s（+4.6%），远低于 20% 回退线，无回退必要。
- R2. [ ] 消费测试零改动验证（默认 numpy 后端 = 回归意义所在）：
  quot(1500|6500)、string(1500|7500)、brec_drec(1200|8000)、
  defeq_cache(2700|8000)，帽照 scripts/run_cpu_regression.sh；先两两并行
  盯 RSS，不稳转串行；全部 rc=0 才算 fork 协议零改动兼容成立；任何 FAIL
  停手原文上报（不许改测试）。
  **执行方式修订（证据驱动）**：开工时 MemAvailable 仅 9.4GB（无关
  pytest 3.6GB + brave 群 ~10GB 占用），两两并行（6.5+7.5GB 帽）必然
  压线——按本条"不稳就串行"预案直接落串行链
  （/tmp/012p2_verify/chain_r2r3.sh，launch 形状照抄 run_cpu_regression.sh
  launch_suite：systemd-run PrivateTmp + guard + timeout，核 14-19，
  OMP/MKL=3，前一套件非 0 rc 即停链；日志/rc 在
  ~/logs/012p2_verify/）。教训一处：首版链把日志写 /tmp，被 PrivateTmp
  命名空间吞掉（rc=99 秒停），改 $HOME/logs 后正常——与回归脚本注释
  "PrivateTmp isolates them for free" 的既有经验一致。
  - [x] quot_graph_vs_lean（默认 numpy 后端）：**rc=0**，wall 286.5s，
    树峰 4727MB（帽 6500）。原文收尾两行：
    `=== WP4 Quot reduction: 7/7 corpus, A=4 meta, C-stuck=y, 0 failures === OK`
    `[mem-guard] wall 286.5s peak RSS 4727MB rc=0`
  - [x] string_graph_vs_lean（默认 numpy 后端）：**rc=0**，wall 872.3s，
    树峰 4311MB（帽 7500）。原文收尾两行：
    `=== WP5 string literals: B corpus 30/30, C arm 3/3, 0 failures === OK`
    `[mem-guard] wall 872.3s peak RSS 4311MB rc=0`
  - [ ] brec_drec_iota_vs_lean：**首跑 wall 超时 rc=124（非判定 FAIL）**。
    原文（~/logs/012p2_verify/brec_drec_iota_vs_lean.log 尾）：
    `C lst  faithful brecOn DEFEQ vs oracle (graph max_steps=1100)`
    `[mem-guard] wall 1200.8s peak RSS 7814MB rc=-9 KILLED: wall 1200s > timeout`
    （C 节运行中被杀；已完成的 A 组不变量 + B 组 nat brecOn 全语料
    逐例 PASS，含 d6 True@≤1100 步 = 历史难点例）。历史锚（016C
    beat-C，list 后端）：`brec_drec_iota_vs_lean: PASS [mem-guard]
    wall 1072.9s peak RSS 7352MB rc=0`——1200s 帽对该套件只有 ~12%
    余量；今跑期间机器上有无关 5.2GB pytest 并发（quot 窗口期 3.6GB，
    brec 窗口期 5.2GB 持续爬升）。同场 quot 反而比 016C 快
    （286.5s vs 339.9s），排除"机器整体变慢"解释。处置：按 016C
    mutation_reject 先例（并发 1200s 超时 → 单独跑 1814s PASS，
    016C/w3a），链续跑其余套件后**同帽（1200|8000）单独重跑 brec**
    以分辨"负载超时"vs"numpy 后端真实时间回归"；两次尝试原文都留档。
    若静场重跑仍超时 = numpy 后端对 fork 重型套件有 ≥+12% 墙钟回归
    （机制候选：_HistStore 物化 `list(h)` 逐条造新元组 vs list 后端
    指针拷贝），超卡 20% 线与否由实测定，停手上报总控裁决。
  - [x] defeq_cache_vs_lean（默认 numpy 后端）：**rc=0**，wall 2402.9s，
    树峰 7806MB（帽 8000，贴帽）。原文收尾两行：
    `=== defeq cache vs lean [all]: ALL OK (2402s) ===`
    `[mem-guard] wall 2402.9s peak RSS 7806MB rc=0`
    （whnf phase 按 ADR 019 SKIP——P2 dormant 既有口径。cache 命中例
    正常：run2=True/1 一步重放。对比 016B 历史 wall 2138.6s/4742MB：
    +12.3% 墙钟、树峰 +3.0GB——跑在无关 pytest battery 满载窗口；
    判定面 240+ 例 ALL OK。）
  - [ ] brec_drec_retry（同帽 1200|8000 静场复测）：**rc=124 再超时，
    两次尝试确定性一致 → 停手上报，不再跑第三次**。原文：
    `C lst  faithful brecOn DEFEQ vs oracle (graph max_steps=1100)`
    `[mem-guard] wall 1200.7s peak RSS 7813MB rc=-9 KILLED: wall 1200s > timeout`
    与首跑（1200.8s / 7814MB / 同死于 C 节）kill 点与峰值逐字级一致；
    起跑时 MemAvailable 13075MB（首跑 10127MB），跑中 battery 复活
    （降至 7428MB）——负载混淆未完全消除，但两次独立一致排除偶发。
    **事实**：numpy 后端下该套件墙钟 ≥1200s（真值被帽删失，未知），
    list 后端 016C 实测 1072.9s → 劣化 ≥+11.9%；RSS 峰 7813MB < 8000
    帽（+6.3% vs 历史 7352MB，不破线）；**语义面**：A/B/D 三节全部
    完成且逐例 PASS（含 d6 True@≤1100 步），仅 C 节（list brecOn
    DEFEQ）在 numpy 下从未跑完（两跑均死于 C 节内）——C 节判定面
    存在真实验证缺口。**留总控裁决**：(a) 照 016C mutation_reject
    先例提帽重跑（如 1800|8000）补 C 节验证并量真值；(b) 或裁定
    C 节 NOT-VERIFIED 挂账（语义风险受 R1 双后端 diff + A/B/D 完成
    节 + R4 正交论证覆盖）。机制候选（未实测）：fork 物化
    `list(_HistStore)` 逐条造新元组 vs list 后端 `list(list)` 指针
    拷贝 + 物化后 mirror 重建两案同价。
- R3. [x] 快套件 canary（核 14-19，同链串行）：3/3 **rc=0**。
  `check_e2e [mem-guard] wall 656.9s peak RSS 1508MB rc=0`、
  `ref_vs_lean [mem-guard] wall 1.6s peak RSS 1512MB rc=0`、
  `level_vs_lean [mem-guard] wall 2.6s peak RSS 1436MB rc=0`。
- R4. [x] 判定不变性补充：**采"论证已有证据足够"路线**（不补 defeq_cache
  双后端探针）。理由（grep 全仓证据，file:line）：
  1. 旗标只换一个结构：`VM012_HISTORY` 只在
     `lean_kernel/alm_p2.py:390-403`（`__init__` 选容器）出现；
     `self.lookup_history` 的全部读点 = `_eval_pos` lookup 臂
     （alm_p2.py:431-489，两分支同式 hardmax、同 float64 键值）；
     非增量 `_eval_position` 的 history 是**函数自建普通 dict**
     （alm_p2.py:273），旗标不可达。lean_vm/、model/、compiler/ 全无
     lookup_history 引用。
  2. §18.3 defeq 正缓存是**图结构**不是 Python 容器
     （`lean_vm/build_vm.py:3906` `defeq_cache = reglu(...)`，
     :3982/:4140-4143 选择臂）——它经同一 lookup 臂求值，与 history
     容器正交；"defeq_cache 语料 × list 后端"的额外交互面**构造上为空**。
  3. 消费面（fork 协议）已穷尽：Part A 小图 fork ×4 后端组合
     （warm numpy/list × fork numpy/list）vals+物化 history 全等 +
     store 协议边界；Part B 3 个 iota 真实 case（含 DEFEQ 判定
     wb_b_deq=True@24 微步）判定/微步数/token 流双后端逐值 diff 为空。
  4. 语料规模上的判定正确性由 4 个消费套件（期望全部 oracle 现跑）
     在默认 numpy 下 rc=0 直接给出——这是验收铁律 1 的判据本身，
     强于任何双后端 /tmp 探针。
  补充成本对照：defeq_cache 单 case 双后端探针需两次大 env warmup
  （~30-70min guard 墙钟），新增覆盖 = 上第 2 条已证构造为空的交互。
- R5. [x] 文档：docs/VM_SPEC.md **§19**（19.1 旗标双后端 / 19.2 实测
  footprint 表 + 边际驻留 + 6GB 线 token 上限 ~25-26k / 19.3 时间律 +
  引擎通道裁定引用 ADR 024 §5/§7.3）；卡 012 状态行更新（拍 2 态 +
  brec 悬决项显式）；ADR 024 E5 已执行标注（harness 路径 + 校准/复测
  数字）。改动文件全集 = 本卡 + VM_SPEC §19 + ADR 024 尾注，未触碰
  alm_p2.py / scripts/ / tests/ / model/。
- R6. [x] 最终报告给总控（结论 / numpy 峰值 vs 基线 vs 预期 / 时间律 /
  消费测试 3/4 rc=0 + brec 两次超时原文 / canary / 文档摘要 / 未尽事项）。
