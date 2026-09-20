# 任务 010：声明注入协议改造（step_driver 属主卡）——解锁 G3/G6/G2-unsafe

状态：**CLOSED**（2026-09-21，G02/G06/G03/G04 四拍全验收，见增补 5；遗留缺口转卡 011）
依赖：卡 007 的 CK_* 通道（§16.2/16.3）。本卡先动，G6/G8/G9 图侧卡 011 依赖本卡协议。

## 目标

`lean_vm/step_driver.py` 的 `run_check(decls)` 从"单遍 ENV、无声明 kind"升级为
与内核 `add_*` 家族一致的注入协议：

1. **声明 kind 携带**（解锁 G3）：`theorem` 额外 `is_prop(type)`，否则
   `theorem_type_is_not_prop`（`K/environment.cpp:192-209`）。图侧新增错误码
   与既有 4-7 并列（ENV_FORMAT 同步）。
2. **unsafe 先注册后检查**（解锁 G2-unsafe 支）：`add_definition(is_unsafe)`
   路径先把 constant_info 加进环境再 check（`K/environment.cpp:160-190` 的
   `else` 支），使自引用可见；检查失败则整次 add 不生效（异常语义由 driver
   层模拟：注册回滚）。G10 的 use_reject 标志须能感知"注册后"状态。
3. **mutual 块前置可见**（解锁 G6）：`add_mutual` 先把全部 n 个 constant_info
   加入再逐一 check（`K/environment.cpp:225-269`）；块名重复校验
   `check_multi_param_names`（:236-241）。

## 涉及文件

`lean_vm/step_driver.py`（**本卡起列入文件所有权表，属主=注入协议**）、
`lean_vm/build_vm.py`（仅当错误码/新链需要图侧配合）、
新 `tests/test_decl_injection_vs_lean.py`、`docs/VM_SPEC.md` §16、
`docs/ENV_FORMAT.md`、`docs/KERNEL_COVERAGE.md` G 行、`docs/handoffs/006-G-injection.md`。

## 铁律

- step_driver 改造必须**保持既有 verifier 全绿**（check_e2e 15/15、
  defeq_branches 全臂）；协议变更以新增参数/新增通道实现，旧默认路径不改语义。
  若无法不破坏，停手写 ADR 等人裁（本卡是"属主改造"，允许动结构，但每次动
  完立即全量 canary）。
- 错误类别判据 = 真 lean `addDecl` 抛的消息（`Kernel.Environment.addDecl`
  通道，D 链 #KDECLMSG 机制），差分逐例核类别。
- ref_vm.py 冻结不破：注入协议的参照语义写在 step_driver 与测试内，
  不扩 ref_vm。

## Verifier 集

- [ ] 新差分：G3 三类（prop 通过/非 prop 拒/错误类别一致）+ G2-unsafe 自引用
      （真 lean 实测行为为准）+ G6（互块自引用、块内重名）逐条绿
- [ ] check_e2e / defeq_branches / 20 套件回归全绿；引擎不倒退
- [ ] 硬编码扫描零新增；ENV_FORMAT/VM_SPEC/矩阵同步

## 派工增补（总控 2026-09-18，卡 014 结案后排产）

- **折入 ADR 016-B 子任务**（accepted 2026-09-17，实作归属本卡）：
  TASK_WHNF 顶层交付合同**图侧不动**，driver 侧（`step_driver.run_whnf`
  的调用方语义层）对 raw-field 交付**续 whnf 到头范式**，对齐内核
  `whnf_core` proj 回灌（`K/type_checker.cpp:504-508`）。验收=
  G1/a1 四载体（Nat/Lst/MA-MB/IV/MyTree）顶层 `#WHNF` 与 oracle
  `#WHNF` 逐字一致的新差分；既有图侧 whnf 套件（OE 族、引擎通道）
  **不许出现任何基线变动**（合同没动图的证明）。
- **防线 15 硬项**：本卡三机制（kind 携带/unsafe 后注册/mutual 前置）
  均为 driver 侧协议改造、非图语义分支，对象差异评估=写进首拍——
  逐机制列与图侧共享面（错误码空间 4-7、CK_* 通道、G10 标志感知点）。
- **防线 17 硬项**：新差分套件的行集=声明注入全部判定面（三类机制
  ×正/反例 ×错误类别列）；**首跑 rc=0 原文落板才算交付**，静态验证不算。
- **回归表基线更新**：全量回归现为 **22 套件**（卡 014 起含
  defeq_cache 行）；本卡"20 套件回归全绿"条目按 22 执行。

## 派工增补 2（总控 2026-09-19，G01 验尸后追加，依据 ADR 020）

G01 备案的两处缺陷已在 `docs/handoffs/006-G-injection.md` 总控裁决段落定，编码拍按定案执行，
不再复议。对本卡 Verifier 集的硬项增补：

- [ ] **载体空闲性实证件（常设守卫，落进新差分套件）**：图与权重**不动**，仅 driver 在
      TASK_CHECK 锚帧 E2 写入非零哨兵值，`check_e2e` / stepgraph 族 / defeq 族的**判定与步数
      逐字不变**。这是 E2 可用作 kind/mode 载体的唯一凭证形式；grep 结论不入账（防线 §1.17）。
      任一变即停手换槽上报，不许"改基线让它过"。
- [ ] **禁用 T_NULL 任何字段当新载体**（`build_vm.py:289` 位置 0＝null 哨兵；`:614/:849/:948/:1012`
      存在以可能为 0 的指针读 X 的站点）。若实施中新发现必须用哨兵位，停手写 ADR。
- [ ] **码 8 臂序与类别对拍**：挂在 `g1_fail`（码 5）之后，装配点 `build_vm.py:6507-6511`
      （G01 与本页上文所记 `:6053` 为误引，实为 quot_stuck 的 select 行）；与真 lean 的
      `thmTypeIsNotProp` 类别逐例对拍（`#KDECLMSG` 通道，
      `tests/test_defeq_branches_vs_lean.py:279-312` 现成样板）。
- [ ] **非归一 level 形必须有结论**（ADR 020 决策 B）：构造一条"声明类型的类型"为
      `Sort (imax 1 0)` / `Sort (max zero zero)` 级的 theorem，oracle 现跑判定与图判定对照；
      不一致即记矩阵缺口行并标 `NOT-VERIFIED`，encoder 表达不出也照样记账写原因。
      禁止以"toy env 只有零级"跳过。

## 派工增补 3（总控 2026-09-20，G02 验收收口）

**G02 子链验收通过**（五道门收口，本卡整体仍 open——G6 mutual 拍未做）：

- [x] 新差分（G3 三类 + G2-unsafe 自引用 + 码 8 类别逐例对拍）：
      54/54 checks + 2 xfail known-gap（非归一 level 形，ADR 020 B 预言被实跑证实），
      rc=0，1395.6s / 峰值 2101MB（`/home/xkq/logs/010G/lead_full_suite.log`）。
- [x] 载体空闲性实证件：guard 段对 check_e2e 全语料 kinds=None vs E2=1 判定与步数
      逐字一致，全 PASS（同日志）。
- [x] 22 套件回归等效齐全：21 项 09-19 06:43 PASS（`lead_regression.log`，
      mutation_reject 当趟 900s 超时系机器负载环境性）+ mutation_reject 09-20 单项重跑
      **rc=0**（A 16/16、B 8/8，754.8s / 1552MB，`/home/xkq/logs/010G/mutation_rerun/`）。
      代码态一致性证明：`git diff 15a500d..HEAD --stat` 零代码文件（仅文档/钩子）。
- [x] 引擎不倒退：34/34 rc=0（`post_engine_scratch.log`，钉 010 scratch 件）。
- [x] 硬编码扫描零新增（09-20 复扫：仅存量注释与 `CID_P2MK + 1` 已知项）。
- [x] ENV_FORMAT §2.8 / VM_SPEC §7.4+§16.4 / 矩阵 G3 行 + G3a 缺口行同步（随 1075001）。
- [x] 总控裁决（详见 handoff 006 末段与 handoff 011）：① ST 帧 E2 占用**追认**——
      载体空闲性实证 + a0 漂移对拍为凭证，ENV_FORMAT §2.8 即单一口径，ADR 020
      "仅锚帧"措辞由 ADR 021 实测更新；② 引擎侧码 8 保持 `NOT-VERIFIED`，归卡 013
      CHECK 通道。
- [x] 新套件入回归表：`decl_injection_vs_lean` 已由总控执笔加入
      `scripts/run_cpu_regression.sh`（2100s/4000MB，按实测 1395.6s/2101MB 定），日常
      回归基数 22 → **23**；ARCHITECTURE 同步。

剩余（本卡下拍）：G6 mutual 块前置可见 + 块内重名（码 9 driver 簿记族），
设计备案在 handoff 006 §3，测试行集须含互块自引用正/反例与重名拒。

## 派工增补 4（总控 2026-09-20，G03 验收收口）

**G03（unsafe 图臂）子链验收通过**：G10 抛门 checker-mode 感知（锚帧 E2 mode 位
下行 + 抛门/降级共闸），dims +11/nnz +46（O(1)）；差分 7/7+2 XFAIL（mode 跨 ST
续体不存活=保守侧已知缺口，XPASS 登记，续体携带 mode 归卡 011+）；引擎 34/34
（`step_vm_010g03_scratch.sbin`，真值表已登记）；全量回归 **23/23 rc=0**
（g03_reg）；旧路径（a0/guard/bcd/g6 四节）逐字零差异。decl_injection 帽
2100→2700（1755.4s 实测，>1.5x 裕量）。

本卡余最后一拍：**run_whnf（ADR016-B 方案 B）**——driver 侧 proj 回灌续推循环，
图合同零改动；验收=G1/a1 四载体顶层 #WHNF 与 oracle 逐字一致新差分 + 既有
whnf 套件（OE 族/引擎通道）零基线变动。落拍即整卡收口。

## 派工增补 5（总控 2026-09-21，G04 验收收口——整卡 CLOSED）

**G04（run_whnf，ADR016-B 方案 B）验收通过，本卡四拍全部收口，卡 CLOSED。**

- 交付：`StepDriver.run_whnf`（纯迭代器，停机=焦点 (pos,env) 幂等，预算
  2000×16，零图改动）；G04 差分节 13 行（nat/lst/mu/iv/tree 11 + 直编 Proj
  载体 2），期望全现跑 #ORACLE WHNF；**12 PASS + 1 XFAIL**
  （`g04iv_eG4IV2`=图侧 I_CASE 主前提续推缺口，登记不掩盖）。VM_SPEC §16.7
  合同定版 + 环境最小化纪律（含"归约层动态查 ENV 不可见名字"实测课）。
- 验收证据：总控独立复跑 decl_injection 全量 82/82+5xfail rc=0
  （g04b_lead_verify，IV2 stuck 项逐字复现）；c2 后全文件 canary 84/84 rc=0；
  审核补拍 c2 钉死负面结论（当前图无闭形状使续推轮语义必需，rounds 观测列
  已入行）。五道门全过，逐条见 handoff 006《总控验收记录：G04 拍》。
- 遗留（本卡不修，全部转卡 011 增补队列）：① I_CASE 主前提 whnf 续推
  （IV2 XFAIL 摘除的正门）；② universe 多态 accessor def whnf 活锁
  （univ_arity=0 编码债，c2 probe1 实证 4GB@2000 步）；③ 归约层 ENV 动态
  名字依赖排查（cs_build 现造 `Nat.pred t` 类）；④ mode 位跨 ST 续体
  （G03 登记项，随卡 011）。
- 终验证件=`step_vm_010g03_scratch.sbin`（真值表注记）；晋升决策归卡 011
  开工拍。回归帽 decl_injection `2700|4000` 复核维持（最坏实测 2442s，与
  GPU 训练并行条件）。
