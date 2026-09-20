# PLAN — 阶段计划与验收标准（历史台账，已归档）

> **已归档（2026-09-20）**：本文件是 Phase 0-7 时代的阶段台账（最后更新
> 2026-09-12），保留其带验收数字的历史价值。现行推进口径是
> [KERNEL_COVERAGE.md](../KERNEL_COVERAGE.md) 的 WP 依赖链 +
> [plans/](../plans/) 的任务卡，不再更新本文件。
>
> 配套设计见 [DESIGN.md](../DESIGN.md)。
> 验收标准：判定与真 Lean 4 内核一致（见 [DESIGN.md](DESIGN.md) §2）。
> 仓库内的图与参照机只用于开发迭代，正确性一律以真 `lean` 的判定为准；
> 权重与图在数值上接近是编译期的开发检查，不是验收。所有工作 CPU 即可。
> 最后更新：2026-09-12

## Phase 0 — 清理与项目管理 ✅（2026-08-29 完成）

- [x] 删除 Python 内核移植残留与全部死引用
      （lean_kernel 端口 11 文件、alm_native、opcode_executor、solvers、
      旧 orchestrator/serializer、diff_test、旧 tests/、audit/）
- [x] 清理 alm_graph.py 死代码（core 依赖的 encode 函数、KernelOp）
- [x] docs/DESIGN.md、docs/PLAN.md 成文；根文档改为如实描述
- [x] 旧架构的 COVERAGE_MATRIX 移入 docs/archive/
- [x] 仓库可 import（唯一存活的独立测试 test_graph_eval 保持通过状态——
      待下次运行窗口验证）

**验收标准：** 无任何模块引用已删文件；文档与代码一致。✅

## Phase 1 — VM 规格 + 数据模型 + 参照机 ✅（2026-08-30 完成）

- [x] `expr/model.py`：Expr/Level 数据类，以 lean4 `expr.h`/`level.h` 为准
      （12 种 expr kind、6 种 level kind、binder_info，含 canonical K 常量）
- [x] `docs/VM_SPEC.md`：VM 规格 v1——Krivine 式环境机（链接替代物理
      替换）、token 五字段格式与种类常量权威表、ENV 前导区、数字链 Nat、
      WHNF 切片操作码表（含内核实测校准规则）、INFER/DEFEQ 占位
- [x] oracle：真 lean 二进制（elan, **v4.33.1 stable**；本地
      `/home/xkq/lean4` 源码是 4.35 master 未发布，故 oracle 用最近
      stable；内核语义两者一致）→ `reference/lean_ref.py`
      （生成 Lean 批处理文件 + JSON 序列化，对 4.33.1 API 实测校准）
- [x] `expr/tokens.py`：token 流编码/解码（§2–§5 全量实现）
- [x] `lean_vm/ref_vm.py`：朴素 Python ISA 参照机（Krivine 循环 + 流内
      LINK 链 + 数字链，逐字实现 §7）

**验收：`tests/test_ref_vs_lean.py` 32/32 与真 Lean 一致** ✅
（覆盖：beta/zeta/delta/嵌套 delta/高阶 beta/深度嵌套 beta、全部 10 个
nat 操作含除零与截断边界、大数 121932631112635269、卡头项）。
调试中修复：LINK 链指针的元组索引错位、nat op 参数弹出顺序、bvar 链回
走语义——均为参照机实现 bug，规格与编码层未动。

## Phase 2 — 单图 ALM 解释器（切片一：WHNF）← 当前阶段

设计已定稿（VM_SPEC §10 微步执行模型）：图只算**一步转移**，驱动器
自回归推进——图深度常数，循环全部摊到时间维。

- [ ] VM_SPEC §10.2 微步转移表补全（beq/ble/sub/乘法的 phase-3 子表）
- [ ] `lean_vm/build_vm.py`：单图实现微步转移（先主循环：APP/LAM/
      delta/zeta/BVAR 走链；再 T_NAT 帧 + 逐位加法）
- [ ] `lean_vm/step_driver.py`：eval_graph_sequence 驱动器（§10.3 契约）
- [ ] 差异测试：驱动器 + 图 vs `lean_vm/ref_vm.py`（同 token 流逐步
      状态一致），再 vs `tests/test_ref_vs_lean.py` 的 32 用例

- [x] **M1 ✅（2026-08-30）**：主循环 + 走链微步，`tests/
      test_stepgraph_vs_refvm.py` 32/32 与参照机一致（含闭包环境），
      每例 2–9 微步，图 146 维 / 4 个 lookup，深度常数
- [x] **M2 ✅（2026-08-30）**：T_NAT 帧链（ST 存储 + NAT 控制，phase
      1/2/3）+ succ/pred/add/sub/beq/ble 逐位子表 + 统一"值完成→投递"
      返回协议。**验收：tests/test_stepgraph_vs_refvm.py 34/34（vs 参照
      机 nat on）；tests/test_stepgraph_vs_lean.py vs 真 lean 24/34**
      （10 个 xfail 全部是 mul/pow/div/mod 范围，原估 25/34 少算了
      mixed 的参数含 T_four=mul）。附带修复两个 M1 潜伏 bug：
      多跳走链续帧（D 自指从未工作，旧语料未覆盖）与 encoder 的
      NAME/ENV 布局覆盖（X 操作码字段丢失，ref_vm 不读 X 故 Phase 1
      未暴露）；数字链定稿步幅 2 布局（VM_SPEC §5，机器发射的链数字
      与 STATE 交错，encoder/ref 补 gap 对齐）。
- [x] **M3 ✅（2026-08-30）**：mul/pow/div/mod 逐位循环子表（移位-加
      cell、比较-减法-递增试商循环、pow 控制器/dec 相位；帧相位 4/5/6/
      10/13）。**验收：tests/test_stepgraph_vs_refvm.py 34/34（vs 参照
      机）；tests/test_stepgraph_vs_lean.py 34/34 vs 真 lean**（M2 的
      xfail 集合清空）。Phase 2 单图 WHNF 切片完成：全部 10 个 nat 操
      作 + 主循环 + 走链，图深度常数，big_mul（9×9 位）131 微步、
      pow 2^10 322 微步。调试中修复：cell 末位数字/累加链指针 C 在
      not-done 步丢失、ph4/5/6 同类 C 丢失、dec 下溢（b=0 多位数链
      [0,0] 减 1 得 99 死循环）、bzero 判零改为数字和扫描（长度无
      关）、比较规则（小端扫描须最后差异覆盖）、d23/一元 done 步的
      caller 弹出按 arity 分派（曾统一用二元两跳链导致嵌套 succ 外层
      丢失）。

**验收标准：** M2 后对真 lean 24/34（10 个 mul/pow/div/mod 用例
xfail）；M3 后 34/34 ✅；图深度为常数（不随输入规模增长）✅。
*搬迁旧架构的算术积木（`_mul_acc`/`_gcd_acc`/`_select` 等）在实现逐位
运算时按需进行，来源 `kernels/kernel_islands/common.py`。*

## Phase 3 — 编译权重 + Python 自回归 runner ✅（2026-09-02 完成）

- [x] 单图 → MILP → 权重（复用 compiler/）：`model/compile_vm.py`。
      图 1237 维 / 29 lookup → MILP 27 层（0.1s）→ 权重
      d_model=1218（槽位分配后）、17 头、FFN 145、18.9M 参数，
      build_weights 2.1s。修复 build_weights 头数 bug（按每层 lookup
      的 value 对数计头，原按 lookup 数计——本图最大 lookup 有 5 个
      value，会静默丢头）；加 float64 纪律（transformer-vm 同款）；
      新增 `LeanTransformer.forward_stream`（残差行直通，无词表）与
      CompactAttention 格式的 load。
- [x] `model/runner.py`：WeightRunner 复刻 StepDriver 契约（同
      init_state/step/run、同发射顺序）；输入行 = 7 字段直通槽位 +
      one=1.0，输出 = identity 头读 persist 维（38 输出维保护到最后一
      层），teacher-forcing 全前向，float64。
- [x] 开发检查（非验收）：`tests/test_weights_fidelity.py` 在同一 token
      流上逐步对比权重前向与图重放的输出，34/34 通过，最大数值偏差
      7.3e-9。该检查只覆盖 WHNF 任务，用于发现编译错误，不构成验收。
      附带修复测试 harness 的 stuck 用例处理（done 在初始 STATE 即置位
      的用例须先 step 再判）。
- [x] 死代码清理（commit bbe1215）：kernels/ 整体退役 →
      lean_vm/primitives.py 单源。

**验收标准：** 权重路径的 WHNF 输出与图一致（开发检查 34/34）✅。
判定与真 Lean 4 内核一致是最终验收，见 [DESIGN.md](DESIGN.md) §2。

**性能基线**（CPU 8 线程，float64；eval=图重放，fwd=权重前向，
wall=双驱动 lockstep 总耗时；fwd 已含每步整流重算）：

| 用例 | 微步 | eval | fwd | 加速 |
|---|---|---|---|---|
| div（28 步） | 29 | 4.6s | 1.4s | 3.3× |
| let_delta | 158 | 51.2s | 25.5s | 2.0× |
| big_mul | 132 | 43.2s | 21.6s | 2.0× |
| pow 2^10 | 323 | 231.2s | 195.3s | 1.2× |

长序列下 O(n²) 前向吃掉线性加速——KV cache（Phase 4）对每步只有
增量 token 的流是 O(n) 化的关键，hull attention 可照搬 transformer-vm
（赢家必在 2D 凸包上）。

## Phase 4 — C++17 引擎 ✅（2026-09-02 完成）

- [x] 权重二进制导出格式：compiler/weights.py `save/load_weights` 在
      transformer-vm 兼容格式尾部追加 runner 元数据段（field→slot、
      one_slot、output name→head row；顺带修复 load 从不消费 tiebreak
      段的格式不对称），`model/compile_vm.py` 双导出 .pt + .bin
- [x] `engine/vm.cpp`：单文件 C++17 引擎 + Makefile。增量 KV cache
      （每层每头 2D key/value，d_head=2）；发射契约循环与
      WeightRunner 逐行同构（token 常量 K_LIT=10/LIT_NAT=0 等镜像自
      expr/model.py）；输出读出走 head 矩阵（identity 投影须实际相乘，
      行号≠槽位号）。权重加载后转 CSR 稀疏 matvec（解析权重每行仅
      ~2-6 个非零，稠密 matvec 是内存带宽瓶颈；跳过精确 0 位等价）；
      `VM_HARDMAX=1` 用精确 argmax 替代 exp-softmax（键内 inv_log
      破平局保证无真平局，输出流与 softmax 模式逐字节一致——与
      transformer-vm C++ 引擎同款）
- [x] 测试 `tests/test_engine_vs_runner.py`：全语料 34/34——同初始流，
      C++ 引擎与 Python WeightRunner 的**完整发射流逐 token 一致**
      （流即全执行轨迹），闭包与 DONE 判定一致
- [x] CLI `engine/vm_run <weights.bin> <stream.txt> <term_pos>`（流级
      接口；vm-eval/vm-ref 等需要 .olean 环境导出，Phase 5 落地）

**验收标准：** C++ 输出与 Python runner 全语料一致 ✅（34/34）；
吞吐基线 ✅。

**吞吐基线**（单线程，含 0.09s 权重加载）：

| 用例 | 微步 | Python runner | C++ 引擎 | 加速 |
|---|---|---|---|---|
| succ_zero | 5 | 0.2s | 0.03s | ~7× |
| div | 28 | 1.4s | 0.13s | ~11× |
| big_mul | 131 | 22.5s | 0.3s | 75× |
| pow 2^10 | 322 | 211.1s | 0.45s (hardmax) / 0.94s (softmax) | **235–469×** |

稳态 ≈ **715 微步/秒**（hardmax；CSR 前每步 ~41ms 内存带宽受限 → CSR 后
~1.2ms，argmax 再省一半 exp）。后续优化空间：初始批 O(n₀) 位置并行、
OpenMP（本机可 ~10 核）、hull 凸包 O(log n) 注意力（transformer-vm
同款；注意其 LATEST 平局退化为 AVERAGE——我们键内 inv_log 破平局，
不受影响）。

## Phase 5 — INFER + DEFEQ 操作码、端到端证明验证

- [x] **M1 ✅（2026-09-02）**：infer/defeq 参考子集。oracle 扩展
      #ORACLE_DEFEQ / #ORACLE_INFER（`reference/lean_ref.py`，探针确认
      必须 synthesizeSyntheticMVarsNoPostponing + instantiateMVars，否则
      numeral 实例 mvar 使 isDefEq 全报 false）；RefVM 增 infer/defeq
      （`lean_vm/ref_vm.py`）：infer = 内核 infer_app/lambda/pi/let 子集
      （spine 剥离 + ensure_pi + arg 类型 defeq + Krivine 类型实例化，
      binder 用 flag=1 marker link 即 fvar 类比，Pi 闭包用 T_PI_CLO 表示
      两端 env 不同的类型）；defeq = 快速结构相等 + 双侧 whnf 循环 +
      卡住 spine 对比 + Nat ctor↔literal 归一（内核 reduce_nat 等价）；
      MData 双侧透明剥离（内核处处透明）。附带修正 toy env 潜伏错误：
      二元 Nat op 类型原为一元 Pi，INFER 一查即爆。验收
      **tests/test_ref_infer_defeq.py 37/37 vs 真 lean 100%**
      （21 defeq + 16 infer）；回归 RefVM 34/34、step 图 34/34、
      权重保真 34/34（worst 1.08e-09）、C++ 引擎 34/34。
- [x] **M2 ✅（2026-09-03）**：ALM 图帧（DEFEQ/INFER）。同一张 step 图
      新增 task=6 INFER / task=7 DEFEQ 帧与 CONT 续延树（ST.F2 存续延
      id，31 个：I_FN…D_NCD）；主模式"值完成"投递扩展到 infer/defeq
      调用点；INFER spine 剥离/lambda/pi/let 全链、DEFEQ 逐 kind 分派
      + whnf 循环 + Nat 归一全部图内化；驱动器发射契约扩到 11 槽
      （raw 槽新增）、StepDriver 换 IncrementalGraphEvaluator（O(n²)
      →O(n)）。修 4 个设计 bug：I_LAMBODY/I_LETD 发射 raw/link 后帧
      槽位未 +1（focus 指到 ST）、I_LETV 丢 LET token 位置（E2 默认
      清零）。验收 **tests/test_stepgraph_infer_defeq.py 37/37 图 vs
      参照机**（21 defeq + 16 infer）；回归 RefVM vs 真 lean 34/34 +
      37/37、step 图 vs 参照机 34/34、step 图 vs 真 lean 34/34；重编译
      权重（240,662,136 参数）后 lockstep 权重保真 34/34
      （worst ≤1.3e-09）。C++ 引擎不覆盖新帧（Phase 4 二进制格式未含
      raw 槽/INFER/DEFEQ 任务），留 Phase 6 重建。
- [x] **M3 ✅（2026-09-05）**：proof irrelevance + eta + 结构 eta + proj
      进 ALM 图（内核 is_def_eq 卡头后段，§8.1/§10.2）。stuck 链续延帧
      id 32–54：proj 归约（I_PROJ）、binder bid 身份（D_BV3 比
      T_LINK.F2）、proof-irrel（PI_*）、eta 展开（ST_ET→ETA_*，合成
      App raw + M/L/M2 共享 bid 标记）、结构 eta（ST_ES→ES_*，满参
      ctor 门 + 逐字段 Proj，s_ty 静态免 infer(Proj)）。发射槽扩 c4
      （raw+link1+link2+frame）。验收 **tests/test_stepgraph_infer_defeq.py
      52/53 图 vs 参照机**（16 个 M3 新例 15 通过；deq_eta_lam 钉住：
      嵌套 eta 的 ≥1 跳 BVar 头在 spine-end 被 whnf-under-marker 清 env，
      属共享 spine-peel 路径既有缺口，危及 46 通过例，留 Phase 6）；
      回归 RefVM vs 真 lean 34/34+53/53、图 vs 参照机 34/34、图 vs 真
      lean 34/34；重编译权重（635,747,778 参数，71 层 d_model=4374）
      lockstep 保真 34/34。C++ 引擎不覆盖 M3 帧（Phase 6 重建二进制）。
- [x] M4：.olean 常量子集导出 + 端到端 CHECK + 变异拒绝（方案见 VM_SPEC §11；M4.1/M4.2/M4.3 全部 ✅ 2026-09-06）
- [x] **M4.1 ✅（2026-09-06）**：.olean 常量子集导出（`reference/olean_export.py`）。
      真 lean Environment API 沿 Const 引用传递闭包 dump → Python 侧 toy 表剪枝 +
      字面量归一化（`OfNat.ofNat Nat n (instOfNatNat n)`→lit）+ M4 切片校验 →
      导出常量追加进 env（cid≥28，图硬编码 cid 不动），delta 从此覆盖任意闭合
      单态环境常量。验收 **tests/test_olean_export.py：RefVM(导出 env) vs 真 lean
      21/21（8 WHNF+7 DEFEQ+6 INFER，含真结构 proj defeq）；图 vs RefVM 17/17**；
      回归 34/34、53/53、34/34、34/34、52/53 不变。限制：图 proj/结构 eta 门
      P2 硬编码（图层级避开新结构 Proj）；宇宙多态常量仍缺（Phase 6）。
      纪律更新：权重编译/重型保真一律禁止（见 NEXT_PROMPT 硬约束），验收止步
      图/参照机/真 lean 三层。
- [x] **M4.2 ✅（2026-09-06）**：端到端 CHECK（`lean_vm/build_vm.py` T_CHECK 帧 +
      `step_driver.run_check` + `ref_vm.check`）。CHECK 帧=每声明循环锚
      （V1=声明类型根, X=值根, V2=下一锚）；`ck_kick` 压 ST(CK_TY)+INFER，
      CK_TY 镜像 I_ARG 压 DEFEQ(推断类型 vs 声明类型)，CK_RES 按 verdict
      reject/推进/ACCEPT——续延 caller 链在 kickoff 即跳过锚，推进=普通 pop、
      接受=锚尽 halt，零新 fetch。新续延 id CK_TY=55/CK_RES=56。验收
      **tests/test_check_e2e.py：RefVM.check vs 真 lean（`example : T := v`
      exit code）15/15（12 单声明 accept/reject + 3 多声明序列）；图 vs RefVM
      15/15**（accept 4–16 微步、reject 24–42、7 声明 65）。回归全绿：M1 53/53、
      M3-ref 34/34、M2 图 52/53、M3 图 34/34+34/34、M4.1 21/21+17/17。
      限制：覆盖面=M2/M3 INFER/DEFEQ 子集；错误定位（V2 父指针链）属 M4.3。
- [x] **M4.3 ✅（2026-09-06）**：变异拒绝 + V2 错误定位（`tests/test_mutation_reject.py`
      + `lean_vm/localize.py`）。**变异拒绝**：8 正确声明 + 8 最小破坏变异（改类型头/
      Pi 余域/换结构/构造子字段塞错类型），真 lean/RefVM/图三层逐条一致——原语全
      accept、变异全 reject，**Part A 16/16**。**错误定位**（driver 侧、零图改动）：
      类型不匹配用图 `run_infer` 结果与声明类型做位置级结构 diff（`diff_pos` 递归到
      最深分歧=变异子项），值非良构用 reject 步焦点（`VMError.focus`），均沿 V2 链回溯
      到声明树根，**Part B 8/8**（Pi 余域变异定位到深度 2，证明 diff 正确递归）。
      **顺带修复 M2 遗留正确性 bug**：`build_vm.py` D_NCC 块 `rej_c` 误用赋值覆写、
      静默丢弃 I_CHK 等更早 CONT-tree 拒绝，致图 `infer_app` 接受参数类型错误申请
      （`Nat.add true 1`→`Nat`）；改累加后正确 reject，全套回归不变。M4 三项全部完成。

**验收标准：** vs 真 lean 差分测试一致（M1 已达标）。

## Phase 6 — 图/引擎语义债务清偿

- [x] **P6.1 ✅（2026-09-06）**：whnf spine-root 约定 + marker env 传播
      （`deq_eta_lam` 解除钉住，详见 VM_SPEC §11.5）。图侧三改：`mk_stuck`
      在 WHNF 父帧+pending args 下交付整条 spine 的原闭包 `(nbV1,nbX)`；
      WALK 帧 F2 携带 bvar 焦点 env₀；`mk_dq` 对 `D_BV2/D_BV3` 下的值链
      直接交付链位置。参照机 `whnf` K_BVAR marker 分支同步 spine-root 并
      引入 `spine_env`（head 解析经值链替换会改写 env，stuck 返回须用
      spine 打开处的 env；K_CONST stuck 分支同修）。新守卫例
      `deq_fvar_args`（`f 1 ≡ f 2` 必须 False——旧 head-only 交付两侧都
      误 True，不健全）；顺带修图 `I_LIT` 的 `raw_V0` 误取 `SB`（顶层
      env=0==CID_NAT 掩盖，marker env 下发成 `Const(marker_pos)` →
      reject 4）。验收 **图 vs 参照机 54/54（0 钉住）、参照机 vs 真 lean
      54/54**；回归全绿：whnf 34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、
      M4.3 16/16+8/8。
- [x] **P6.2 ✅（2026-09-06）**：infer_proj 帧（机制 F，VM_SPEC §11.6）。
      图 INFER 补 Proj 类型推断（内核 `infer_proj` L247 单态非递归非依赖
      子集，P2 build-time 门控）：`proj_i` 压 ST(IP_TY)+INFER(child)，
      IP_TY 压 WHNF，IP_PEEL 两相位（校验 `Const(CID_P2)`+sname → 剥 ctor
      类型 Pi 交付字段 domain），新续延 id 57/58，不匹配 reject
      ERR_TYPE（= 内核 invalid_proj）。ES_T 保留静态 s_ty 捷径。语料
      `inf_proj_fst/snd/mk`（总 57）。验收 **图 vs 参照机 57/57、参照机
      vs 真 lean 57/57**；回归全绿：whnf 34/34×3、M4.1 21/21+17/17、
      M4.2 15/15+15/15、M4.3 16/16+8/8。
- [x] **P6.4 ✅（2026-09-06）**：iota 参照机侧——`Nat.rec` reduce_recursor
      （VM_SPEC §11.7）。内核 inductive.h L77 子集：major_idx=3（pend[-4]），
      major whnf 分类（lit/zero → zero 规则弹 4 项续跑 z；lit v>0 → 剥一
      个 succ；succ-App → 实参闭包；其余 spine stuck 走 §10.2），succ 规则
      rhs = `s pred (rec m z s pred)` 经 LINK 链 e4 携带四闭包、循环续跑
      即惰性递归。`Nat.rec` 进 TOY_CONSTS（cid 27，export cid 动态无碰撞）。
      语料 7 例 `deq_rec_*`（总 64），图侧钉住待 P6.5。验收 **参照机 vs
      真 lean 64/64、图 vs 参照机 57/64（7 钉住）**；回归全绿：whnf
      34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、M4.3 16/16+8/8。
- [x] **P6.5 ✅（2026-09-06）**：iota 图侧——`Nat.rec` reduce_recursor 编进
      单一 ALM 步图（VM_SPEC §11.8）。`Nat.rec` 进 `NAT_OP_CODES`（code 11，
      ENV_HDR.X 派发，不进 `NAT_OPS`/`NAT_OP_ARITY` 故参照机不受影响）；分支
      态 fire_rec/zero_r/build_r/stuck_r/rec_sd，发射链 `em_*_rec` 经 `is_build`
      选择层并入。rhs 15 步发射链偏移表实测（base `b=frE2=c1+2`，步 2/3 发
      3 token 余发 2）；修 `raw_K_rec` 偶数参 `sel` 错配（曾发 K=0）、
      `raw_V0_rec` SB1 误取 `Zero`、`link2_P_rec` SB3 off-by-one、`A/B_build`
      done 槽。padding-safe zero 测试扫 4 位（计算链补零，zero 可呈 V0=0/1/
      补零；语料界值<10000）。**P6.5b 解钉最后 2 例 `deq_rec_stuck/stuck_no`**
      （三处 bug：语料 `_REC_MOT` 把 motive 类型误当 binder domain；
      `_pi_natrec` motive 引用 de Bruijn 索引漏算 z/s binder；图 `D_XPI2`/
      `D_TPC2` 跨类 Pi 帧忘覆写 `fr2_task`→默认 WHNF。参照机 `_proof_irrel`
      try/except 吞 infer 异常而侥幸对齐真 lean，图无异常故暴露）。
      验收 **图 vs 参照机 64/64（0 钉住）、参照机 vs 真 lean 64/64**；回归
      全绿：whnf 34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、M4.3 16/16+8/8。
- [ ] P6.3：C++ 引擎二进制格式重建 + 读出表同步（覆盖 M3/P6 帧）。

**验收标准：** 每子项带全套回归数字，图/参照机/真 lean 三层一致。

## Phase 7 — 内核功能补全（defeq/whnf 缺规则，"完善到极致"）

- [x] **P7.1 ✅（2026-09-06）**：`is_def_eq_unit_like`（子单元素 defeq，
      VM_SPEC §11.9）。卡住链最后一条规则：类型 whnf 后头是单构造子零字段
      非递归结构 → 两元素 defeq。新增 `UnitT : Type`（cid 28，非 Prop 故
      proof-irrel 不遮蔽）+ 语料 `deq_unit_like/no`。参照机 `_unit_like`；
      图侧镜像 proof-irrel 的 `PI_*` 链（新 cont id 59–63：`ST_UL`/`UL_W`/
      `UL_CHK`/`UL_D`，`es_no` 由判 False 改踢 `ST_UL`）。坑：新 cont id 须
      登记 `em_frame_m2`/`em_frame2_m2`（否则不发帧死循环）。验收 **图 vs
      参照机 66/66（0 钉住）、参照机 vs 真 lean 66/66**；回归全绿：whnf
      34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、M4.3 16/16+8/8。
- [ ] P7.2：`try_string_lit_expansion`（字符串字面量 defeq，需 String/List
      编码 + `String.mk` 展开）。
- [ ] P7.3：宇宙多态常量（const-const 比 level + `is_def_eq(level)` 的
      max/imax/succ；现 const-const 忽略 level，玩具环境全 0-arity 故未暴露）。
- [ ] P7.4：quot（`Quot`/`Quot.lift`/`Quot.ind`/`Quot.sound`，内核 quot.cpp）。
- [ ] **P7.5：通用 iota recursor（`casesOn`/`brecOn`/`drecOn`）**——把
      `Nat.rec`-专属的 reduce_recursor 泛化为元数据驱动（major_idx/nparams/
      构造子表），覆盖 `match`/`induction` 编译产物。
  - [x] **P7.5a casesOn 参照机侧 ✅（2026-09-06）**：`Nat.casesOn`(cid 30)/
        `P2.casesOn`(cid 31) 类型入 TOY_CONSTS（major_idx=0、motive@1、minors@2+、
        无递归调用）；RefVM 新增元数据表 `self.caseson` + `_match_ctor`（nat 字面量
        先转构造子形，再按构造子 cid 选 minor、把字段按应用序喂给 minor）+ whnf
        K_CONST 分支的 casesOn 归约（extras 留栈）。语料 7 例 `deq_caseson_*`
        （succ/zero/succ2/p2/no/stuck/stuck_no）。验收 **参照机 vs 真 lean 73/73**；
        回归全绿：whnf 34/34×2、图 vs 参照机 66/73（7 casesOn 钉住待图侧）。
  - [x] **P7.5b-2 Nat.casesOn 图侧 ✅（2026-09-06）**：`OP_CASESON=12` 派发键
        入 `tokens.py`；step 图复用 `Nat.rec` iota 骨架——`fire_caseson` 弹 4 项
        spine、`NAT(OP_CASESON,caller,1)` 帧下子 whnf 主前提、`cs_dn` 三分支
        （zero→zero minor / succ→**cs_build 循环** 3 raw 步建 `succ_minor (Nat.pred
        t)` / 其它→§10.2 卡住交付）。帧登记入 `em_frame`+`frame_V1/V2/X/E2/F2`，
        `dn1` 排除 `OP_CASESON`。验收 **图 vs 参照机 72/73**（6 casesOn 解钉）；
        回归全绿：whnf 34/34×3、参照机 vs 真 lean 73/73、M4.2 15/15、M4.3 16/16+8/8。
  - [x] **P7.5b-3 P2.casesOn 图侧 ✅（2026-09-06）**：独立派发键
        `OP_CASESON_P2=13`（cid 31）。3 项 spine `[t,motive,alt]`、单一 2 参
        minor、主前提卡住构造子应用 `P2.mk a b`（值在 spine 根 `SF`，非焦点头）。
        `fire_p2` 弹 3 项（门控查 alt 项存在）、`p2_dn` 匹配 `SF` 的
        `K_APP→K_APP→Const(P2.mk)` 形取字段 a/b、`p2 build` 2 raw 步建 `alt a b`。
        验收 **图 vs 参照机 73/73**（`deq_caseson_p2` 解钉，M3_PENDING 清空）；
        回归全绿：whnf 34/34×3、参照机 vs 真 lean 73/73、M4.2 15/15、M4.3 16/16+8/8。
        casesOn 图侧（Nat+P2）至此完备。
  - [x] **P7.5b-4 Bool.casesOn 图侧 ✅（2026-09-06）**：独立派发键
        `OP_CASESON_BOOL=14`（cid 32）。4 项 spine `[t,motive,false,true]`、两
        minor 均 0 字段 → **无 build 循环**（选中 minor 直接继续 whnf，同 Nat
        zero 规则）。`fire_bool` 弹 4 项（门控查 true 项存在）、`bool_dn` 读焦点
        `fK/fV0` 分 `bool_false_r`/`bool_true_r`/`bool_stuck_r`。**保真坑**：Lean
        先声明 `false` 后 `true`，minor 序为 [false,true]——初版写反，参照机 vs
        真 lean 74/77，修正类型/表/期望后 77/77（对拍真 lean 抓出构造子声明序）。
        接线坑：帧 `E2/F2` 槽须加 `fire_bool`（漏则 `E2=0,F2=0` 死循环）。验收
        **参照机 vs 真 lean 77/77、图 vs 参照机 77/77**（4 条 `deq_boolcaseson_*`）；
        回归全绿：whnf 34/34×3、M4.2 15/15、M4.3 16/16+8/8。casesOn 图侧
        （Nat+P2+Bool）至此完备，`if-then-else`/`decide` 可在 ALM 上消解。
  - [ ] P7.5c brecOn/drecOn（带递归调用的结构递归）。
        **SOTA 核查**：内核无 brecOn 原始 iota——`Nat.brecOn` 是 `@[reducible]`
        def-over-`Nat.rec`+`PProd`（BRecOn.lean），消解 = delta→rec iota→proj。
        派生 iota：`brecOn motive (succ n) F ⟶ F (succ n) (Nat.below motive (succ n))`
        （zero 同形，首参是完整 t）。
    - [x] **P7.5c-1 brecOn 参照机侧 ✅（2026-09-06）**：zero/succ 派发，minor
          忽略 below → 卡住 `Nat.below motive t` 被 beta 丢弃，无需 PProd/go。
          toy env 加 `Nat.below`(cid33 占位类型)/`Nat.brecOn`(cid34)；RefVM whnf
          加 brec 派发（发射 `F t (below motive t)` 5 token）。验收 **参照机 vs
          真 lean 82/82**（5 条 `deq_brec_*`）；图侧 5 例钉 M3_PENDING，图 vs 参照机
          77/82；回归全绿 whnf 34/34×3、M4.1 21/21+17/17、M4.2 15/15、M4.3 16/16+8/8。
    - [x] **P7.5c-1b brecOn 图侧 iota ✅（2026-09-07）**：OP_BREC 铺进六层主
          选择器（fire/build/stuck/sd 四分支×6，is_brec_build 进 B2-F2 与
          em_frame/raw 门），每块恰好 31 闭合。卡住例根因：`_pi_natbrecOn`
          结果 codomain 编成 `motive F`（`App(BVar(1),BVar(0))`），正确为
          `motive t`（`App(BVar(1),BVar(2))`）——run 1（spine 推理）不解引用
          惰性 cod 故 4 条 iota 例全绿；卡住例 proof-irrel 链 PI_TY 真正 INFER
          cod 闭包 → `(fun _ => Nat) minor` → PICLO vs Nat 卡住对 → reject 4。
          RefVM 被 `_proof_irrel` try/except 掩盖（吞掉 cod-infer 异常落回
          spine 比较，碰巧同判）。验收 **图 vs 参照机 82/82（0 pinned）**；
          三层回归全绿：ref vs lean 82/82、whnf 34/34×3、M4.1 21/21+17/17、
          M4.2 15/15、M4.3 16/16+8/8。步数 stuck 224。
    - [ ] P7.5c-2 brecOn 真递归（minor 用 below 取递归值 → 需 PProd/NatBelow
          表示，单态 toy env 的设计分叉）。

**验收标准：** 每子项带全套回归数字，图/参照机/真 lean 三层一致。

## 里程碑外规则

- 每个 Phase 的代码合入前必须带差异测试；对拍对象只有真 lean。
- archive 中旧架构的任何逻辑搬运进 lean_vm 后，原文件标记退役，禁止双源维护。
- 文档（DESIGN/PLAN/VM_SPEC）与代码同 PR 更新。
