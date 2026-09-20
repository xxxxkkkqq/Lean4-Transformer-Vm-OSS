# ARCHITECTURE（仓库现状）

> 目标、验收标准与范围见 [docs/DESIGN.md](docs/DESIGN.md)；
> 指令级规格见
> [docs/VM_SPEC.md](docs/VM_SPEC.md)；工作包与内核分支覆盖见
> [docs/KERNEL_COVERAGE.md](docs/KERNEL_COVERAGE.md)；权重与引擎侧架构见
> [docs/HYBRID_ARCH.md](docs/HYBRID_ARCH.md)。本文件只记录仓库里现在有什么。
>
> 开发流程与硬规则不在这里：入口是根目录 `AGENTS.md`（所有 agent 的硬规则）、
> `总控提示词.md`（总控工作方式）、`开发防线.md`（流程法律与模板）；
> 当前进度与缺口看 `docs/handoffs/` 最新一份 + `docs/plans/` 打开的任务卡。

## 目录

| 路径 | 说明 |
|---|---|
| `lean_kernel/alm_graph.py` | ALM 五原语（Input / ReGLU / LookUp / Persist / CumSum）+ ProgramGraph |
| `lean_kernel/alm_p2.py` | 按位置取指 + `eval_graph_sequence` 图解释器（参照用，不是产品引擎） |
| `lean_vm/build_vm.py` | 单图微步：把 WHNF / INFER / DEFEQ / CHECK 编码成一张 ALM 图 |
| `lean_vm/ref_vm.py` | 朴素 Python 参照机（普通 while 循环），用于快速迭代语义 |
| `lean_vm/step_driver.py` | 自回归驱动器：逐步推进 token 流直到 halt |
| `expr/model.py` | Expr / Level 数据类，以 lean4 `expr.h` / `level.h` 为准 |
| `expr/tokens.py` | Expr 与 token 流的互转、ENV 常量区编码 |
| `compiler/weights.py`、`compiler/milp_scheduler.py` | MILP 层调度 + 解析权重构造 |
| `model/compile_vm.py` | 权重编译入口：build_step_graph → schedule → build_weights → 保存 |
| `model/runner.py` | Python 权重 runner——**开发探针**：吃历史 dense `.pt` checkpoint（当前图不可重铸，19GB），不再被回归覆盖（ADR 005） |
| `engine/vm.cpp` | C++ 执行器：加载权重二进制（含 KV cache）跑 WHNF 切片 |
| `reference/lean_ref.py` | 真 lean 二进制 oracle 封装 |
| `reference/olean_export.py` | 从真 lean `Environment` API 导出常量子集 |
| `reference/toy_env.py` | 手写环境（35 常量）与差分测试语料 |
| `tests/` | 各层差分测试，见 README 的 Verification layers 表 |
| `scripts/run_cpu_regression.sh` | 日常 CPU 回归（23 套件分级 timeout，卡 014 起含 `defeq_cache_vs_lean`、卡 010 G02 验收起含 `decl_injection_vs_lean`；第 4 层=引擎通道 34/34 含 pow（卡 008 后豁免退役）；大 env 套件按 MILESTONE NOTES 记账） |
| `scripts/verify_engine_vs_refvm.py` | 引擎 vs RefVM 对拍（`--sparse` 产物，含 hardmax/softmax 两路）＝权重侧 WHNF 验收通道 |
| `scripts/run_mem_guarded.py` | RSS 轮询 + killpg 内存护栏（AGENTS.md 机器纪律的机制化；回归脚本对大内存套件强制） |
| `AGENTS.md`、`总控提示词.md`、`开发防线.md` | 开发控制文件：硬规则 / 总控工作方式 / 流程法律与模板 |
| `docs/plans/`、`docs/handoffs/`、`docs/decisions/` | 任务卡 / 交接链 / ADR（架构与任务状态的唯一登记处） |
| `docs/archive/` | 历史存档（旧架构 41 图覆盖矩阵、Phase 0-7 阶段台账 PLAN、已作废集中式 HANDOFF、GPU 调研）：只读考古，口径不再可信 |

## 当前状态（2026-09-15）

- **图侧**：单图实现 WHNF / INFER / DEFEQ / CHECK，并覆盖 universe 语义（WP2/WP2b）、
  通用 iota（WP3）、quot 归约（WP4）、字符串 `try_string_lit_expansion`（WP5）、
  `reduce_nat` 位运算与 size-bound 族（WP6，卡 006）、`is_def_eq` 分支
  （reflection/cheap_proj whnf/lazy-delta hints/offset literals/try_unfold_proj_app，WP7，卡 007）。
  常量 cid、构造子布局、recursor 规则、quot 元数据**已由环境数据驱动**（WP8），残留一处按邻居猜测的硬编码读
  （`lean_vm/build_vm.py:4723` 的 `ENV_HDR(CID_P2MK + 1)`，行号随 D 链插码平移，性质不变）。逐分支状态以
  `docs/KERNEL_COVERAGE.md` 的覆盖矩阵为准，本文件不重复维护。
  **已收口**：`brecOn`/`drecOn` 一般 iota（卡 009，2026-09-17 结案：账面 0 分歧；
  结案时 B/C 组 10/11+G4_d6=KNOWN-GAP，卡 014 追补后 11/11 全绿——原 KNOWN-GAP
  定性经实测更正为合法慢，ADR 018 追记）。软 INFER 脊=I_ARG_S，VM_SPEC §11.19）。
  **卡 014（closed，代理 M1–M5，2026-09-17）**：内核缓存层对齐——P1 is_def_eq
  正缓存（T_DEFCACHE=41，构建期开关 `VM014_CACHE`）+ P2 whnf memo
  （T_WHNFCACHE=43，开关 `VM014_WMEMO`）已落图，合同与实测=VM_SPEC §18。
  d6 帽 1500 实测收敛 halt=True@1012（P1+P2；P1-only=1070，判定=内核），
  总控终局裁决 GRAPH_MAX_STEPS 720→1100（步帽=墙钟预算非语义量）后 d6
  转绿，G4_d6 按 XPASS 规程摘除，brec 套件 12/12 PASS 0 分歧 0 xfail。
  **尚未收口**：D1/D2 universe 完整归一化（`mk_max`/`mk_imax`）、
  D 链五条架构不可表达接缝 G3/G6/G8/G9/G2-unsafe（ADR 014 排产：注入协议 G3/G2/G6→卡 010，G8/G9→卡 011）。
- **权重侧**：混合架构（`docs/HYBRID_ARCH.md`，ADR `docs/decisions/001-*.md`）。
  ADR 001 基线规模 `16444 dims / 1915 lookups`（当前图=卡 014 交付态
  **P1-only+M6 修 (a)**：**25,990 dims / 2,899 lookups / nnz 192,717 /
  114 层**，M8-03 m8_scratch 实测 rc=0；
  P1 增量 +55/+1/+286（M2 落账），修 (a) 增量 +5/0/+26（M6，m2→m8），
  P2 增量 +71/+1/+371（M4，**dormant 不入交付图**，ADR 019）；
  发布 sbin 已于 09-18 卡 014 结案晋升门重促为
  该 P1-only 件（旧 24,914 时代件改名保留，见真值表）），
  MILP 128 层、`critical_path=114`（卡 014 交付态 m8_scratch 实测；
  P1+P2 历史态=120；009 代=114）；
  死注意力层折叠、逐层 head 容量、精确 argmax 路由、CSR 稀疏原生编译全部为默认路径，
  编译峰值 RSS 数百 MB 级（ADR 001 时 624MB，当前 ~700MB 级）。
  **dense 权重已退役**（约 24 亿参数 / 19GB，本机必然 OOM）。
  精度实测：fp32 是可用下限，fp16 因 softmax 分数 1e9–1e10 溢出为 NaN，bf16 尾数不足全错。
- **引擎侧**：`engine/vm_run` 读 L4SV **v2**（仍兼容 v1），CSR + 增量 KV cache +
  hardmax（`VM_SOFTMAX=1` 回退 softmax）。**只驱动 WHNF 切片**，不能跑 CHECK。
- **权重/引擎侧验收通道（ADR `docs/decisions/005-*.md`，2026-09-14）**：以
  C++ 引擎为准——`scripts/verify_engine_vs_refvm.py`（当前 sbin vs RefVM 全
  CORPUS 对拍，34/34（pow 由卡 008 修复，历史 33/34 见卡 006/008 记录）
  已列入日常回归。原三个依赖 dense `model/step_vm.pt` 的端到端测试
  （`test_endtoend_corpus` / `test_engine_vs_runner` /
  `test_weights_fidelity`）删除：dense 路径 19GB 不可重铸（红线 9）。
  **显式缺口**：权重侧端到端目前只对 WHNF 验收，CHECK/INFER/DEFEQ 的
  权重侧覆盖 = 无（引擎不支持），待引擎实现后以引擎通道重建 corpus 级
  CHECK 验收；`tests/corpus/{coverage,reject}.lean` 与 oracle 封装保留备用。
  `model/runner.py` 降级为开发探针（不被回归覆盖）。
- **输入侧**：已 elaborated 的 kernel 项 + 环境导出（`reference/olean_export.py`），
  无 parser / elaborator / tactic（口径 A，见 `docs/DESIGN.md` §3）。

## artifact 真值表（核对时间 2026-09-18 05:4x，卡 014 结案晋升门：P1-only 态重促 release；旧行保留为 pre014 件记录）

| 路径 | 状态 | 生成方式 |
|---|---|---|
| `model/step_vm_new_sparse.sbin` | **当前唯一有效产物**（卡 014 结案晋升，09-18 05:39：dims **25,990**/lookups **2,899**/nnz **192,717**/114 层/d_model 6,252，18,888,194B；默认开关编译=交付态 **P1-only+修 (a)**。晋升证据链=总控亲跑：HEAD 源码自 c841ff1 起零改动（git diff 空）、`model/step_vm_014_relcan.sbin` 新编译与 `step_vm_m8_scratch.sbin` **逐字节一致**（`cmp`）、M9 全语料不变性表 133 行 `=== ALL OK ===`、M10 全量回归 **22/22 rc=0**、换新件后引擎复验 **PASS 34/34 无漂移**（`m10_promote_engine.log`）、卡 008 guardrail 零 NaN）。 | `python3 -u model/compile_vm.py --sparse model/step_vm_new_sparse` |
| `model/step_vm_pre014_release.sbin` | 上一代发布件（卡 007 晋升、008 通道复验；24,914/2,878/186,892/109 层、18,027,726B）——卡 014 晋升时整件改名保留，仅历史对照，**禁止当基线** | — |
| `model/step_vm_m8_scratch.sbin` / `model/step_vm_014_relcan.sbin` | 交付图两件**逐字节相同**（05:39 cmp 为证）：m8=M8-03 编译（`m8_compile.log`/`m8_engine.log` 34/34），relcan=晋升门重编译确定性件 | `python3 -u model/compile_vm.py --sparse model/step_vm_m8_scratch` |
| `model/step_vm_009_scratch.sbin` / `model/step_vm_m2_scratch.sbin` / `model/step_vm_m4_scratch.sbin` | 三代开发 scratch（非发布件）：009=基线图（25,930/2,898/192,405）、m2=卡 014 P1 图修 (a) 前（25,985/2,899/192,691，a131287 落账件）、m4=P1+P2 whnf memo 历史研究件（26,056/2,900/193,062；P2 自 M6 起 dormant，ADR 019，禁上验收路径）。卡 014 M5-03 三态逐字节对拍（自 HEAD 源码重编 `cmp`，mtime 09-17 18:07-18:09）：`step_vm_m4_scratch.sbin` 与 M4 v2 件零漂移、`step_vm_m4_base.sbin` ≡009_scratch、`step_vm_m4_p1.sbin` ≡m2_scratch——缓存开关=0 时图与历史件零漂移；引擎通道钉 scratch 复验 **34/34**（`/home/xkq/logs/014/m5_engine_scratch.log`，known-value 3/4 为卡 006 起 harness 既有报表项、非本次引入） | `VM014_CACHE=… VM014_WMEMO=… python3 -u model/compile_vm.py --sparse model/step_vm_m4_<state>` |
| `model/step_vm_010_scratch.sbin` | 卡 010 G02 验证件（**非发布件**，禁止当基线）：发布图 + kind 载体 E2 解码 + CHECK 链码 8 臂。dims **26,012**/lookups **2,901**/nnz **192,821**、18,906,018B、md5 `fc71fa5d44cb73630af41113d61d6aed`、编译 09-19 04:20（峰值 702MB）。相对发布件增量 dims +22/lookups +2/nnz +104 = 一条 O(1) 臂。引擎对拍 **34/34 rc=0**（`/home/xkq/logs/010G/post_engine_scratch.log`）。**G02 已验收（09-20）**：差分全集 54/54+2 xfail rc=0、载体空闲性 guard 全语料 PASS、回归等效 22/22（4.33.1 证据在 g06_reg 重立）；被 G03 件接替为卡 010 现行验证基线 | `OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u model/compile_vm.py --sparse model/step_vm_010_scratch` |
| `model/step_vm_010g03_scratch.sbin` | 卡 010 **现行验证件**（G03 图臂，非发布件，禁当基线）：在 010_scratch（基线 md5 同上，双 md5 交叉确认）之上加 G10 抛门的 checker-mode 感知（锚帧 E2 mode 位下行 + `ck7_gate` 抛门/降级共闸）。dims **26,023**(+11)/lookups **2,901**(+0)/nnz **192,867**(+46)、18,910,254B(+4,236)、md5 `08bb2af7032d26fc9ace6558349e7d7b`。引擎对拍 **34/34 rc=0** 两次独立取证（`/home/xkq/logs/010G/g03_*.log`）；旧路径不变性=新图 vs G06 验收图 a0/guard/bcd/g6 四节逐字零差异；差分全集 **71/71+4 xfail** rc=0（1285.5s/1888MB，`g03_full.log`）；卡 010 全量回归在 `g03_reg`。已知缺口（XFAIL 登记）：mode 位跨 ST 续体不存活 → APP 参数/lam·let body 自引用假拒 7（保守侧），续体携带 mode=卡 011+ 议题。**卡 010 已 CLOSED（09-21，G04 driver 拍零图改动收口，见卡 010 增补 5）：本件即卡终验证件，晋升/接替决策归卡 011 开工拍** | `OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u model/compile_vm.py --sparse model/step_vm_010g03_scratch` |
| `model/step_vm_new.pt` / `.bin` | **已删除（2026-09-15 磁盘清理）**：pre-WP8 dense 快照（各 4.07GB），真值表早已标"过期、禁止当基线"、消费者按 ADR 005 全删，无任何依赖 | 如需要可用 `model/compile_vm.py`（非 --sparse）重铸，但按红线 9 禁止 |
| `model/step_vm.sbin` | **已删除（同上）**：v1 旧二进制（5.4MB），禁止当基线 | — |
| `model/step_vm.pt` | **不存在，且不得重建**（19GB dense，红线 9）；其消费者（三个端到端测试）已按 `docs/decisions/005-*.md` 删除 | — |
| `engine/vm_run` | 有效（09-15 22:31:37 构建，卡 008：ReGLU 钳位 ±1000→`REGLU_CLAMP=1e6`（`vm.cpp:370`，L4SV 未动，权重不变已证 cmp）；conda 环境 `ld` 劫持链接，须 `PATH=/usr/bin:/bin make -C engine`。**注意**：图改动只需重编 sbin；但 008 起 vm_run 与 vm.cpp 同代，旧 vm_run 对 act∈(1000,1e6] 行为不同，跑引擎对拍必须用仓库当前构建） | `PATH=/usr/bin:/bin make -C engine` |

验证 harness：`scripts/run_cpu_regression.sh`（日常 CPU 回归 23 套件（卡 010 G02 起），1–3 层图/参照机/
真 lean + 第 4 层引擎通道 `verify_engine_vs_refvm.py`，**34/34 基线（含 pow，
卡 008 后豁免退役）**；大内存套件由 `scripts/run_mem_guarded.py` 强制 RSS 上限）、
`scripts/verify_engine_vs_refvm.py`（引擎 vs RefVM，`SBIN=`/`VM_ENGINE=` 可钉
快照）、`scripts/check_card008_clamp_bridge.py` / `scripts/check_card008_guardrail.py`
（卡 008 收编的钳位合同/护栏证据）。大 env 差分套件 `tests/test_iota_graph_vs_lean.py`（40 分钟级 warmup）
与 `tests/test_quot_graph_vs_lean.py` 的历史 RSS 问题见脚本头 MILESTONE NOTES。
iota 在 2026-09-15 里程碑出口实测仍不可行：env 81 常量、图求值段 2 例后
RSS 越 8GB 护栏（两趟 6010/8006MB，rc=-9），判据挂起待卡 012 M-B 求值器
内存改造；见 001 lead handoff「里程碑出口记录」。

## 旧架构（已退役）

早期把 41 个内核操作各自编码成独立 ALM 图，由 Python orchestrator 串联，
并对自写的 Python 内核做对拍。该路线已被放弃：循环硬展开导致量程受限，
单体 DEFEQ 图在当时的编译预算下无法编译出可用权重，对拍对象不是真 lean。
相关源码与覆盖矩阵存于 `docs/archive/`。
