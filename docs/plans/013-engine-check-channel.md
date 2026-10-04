# 任务 013：引擎 CHECK/INFER/DEFEQ 权重通道（engine/vm.cpp）

状态：**CLOSED（2026-09-23 总控五道门验收 PASS）**。拍 1 实现+自验
（2026-09-21 后端工程师，四验证全绿 + canary 3/3 rc=0，证据落 009-K）；
总控独立复跑链（09-23 04:2x-04:5x，核 8-13，钉 `step_vm_015_full_scratch.sbin`，
`~/logs/013K/lead/`）三项全绿：WHNF **34/34**（whnf.log）、三任务
**99/99**（tasks.log，548.2s）、`#KDECL` **12/12**（kdecl.log）。
验收记录：机械门=改动仅 vm.cpp+新 harness+两文档；语义门=diff 逐段审
（reject 通道/em_raw+em_link2/三任务前导帧 vs step_driver.py:89-204 合同，
WHNF legacy 路径字节不变由 34/34 证）；架构门=不动 sbin 格式、零硬编码
新增（meta-check 机制防 token 漂移）；诚实门=无 NOT-VERIFIED 掩盖。
引擎通道节已入 VM_SPEC §16.9，真值表 vm_run 行已同步。

## 目标

C++ 引擎 `engine/vm.cpp` 目前只有 WHNF 入口（`init_state(term_pos)`，:558），
权重侧端到端只对 WHNF 验收（ARCHITECTURE 真值表既有缺口行）。本卡把
INFER/DEFEQ/CHECK 三任务通道补齐，使这三类判定能**从编译权重经引擎出**，
与 Python runner/RefVM 判定逐例一致。J1 审计（`docs/handoffs/008-J-audit-roadmap.md`
J 段 B 条）核实缺项与估计 100-200 行 C++，不动 sbin 格式：

1. reject 通道：主循环 :579 只读 `done`；图侧输出维 `reject`/`reject_code`
   已构造进权重（`lean_vm/build_vm.py:6152,6170`，Python 侧
   `model/runner.py:273-280` 已消费）。引擎加读两维，按
   `lean_vm/step_driver.py:89-97` 合同发 `T_REJECT(203)/T_HALT(204)`
   （`expr/tokens.py:53-54`），终局输出判定。
2. 发射臂：`em_raw`、`em_link2`（含 link_flag/link_F2 字段）、`link_env`——
   合同在 `step_driver.py:100-124`，`vm.cpp:585-593` 缺（grep 零命中）。
   INFER/DEFEQ/CHECK 路径会发这些臂（PI_CLO/level 链/binder-identity）。
3. 三任务入口：前导帧注入区别于 WHNF（`step_driver.py:171-200`）；
   **`model/runner.py:357-398` 已有三任务的 Python 实现（含 prefill），
   是现成移植参照**。硬编码 token 值需与 sbin meta 校验一致（vm.cpp:440-441）。

## 非目标

- 不动图与权重：禁改 `lean_vm/build_vm.py`、`compiler/*`、`model/*`、
  sbin 二进制格式（无格式变更则无版本化义务，卡内写明）。
- 不修 009/010/011 的缺口（brecOn/iota、注入协议、G8/G9）——15 例 CHECK
  语料形态与这些缺口不相交（J1 B(3) 已核）。
- 不做首飞 demo（J1 C 条：引擎打通后另立探针卡）。
- `ref_vm.py` 冻结，只作对照不作扩展。

## 涉及文件（触碰面）

`engine/vm.cpp`（主）、`engine/` 构建脚本（如需）、新
`scripts/verify_engine_tasks.py`（三任务引擎对拍 harness，须落盘进仓库才算
证据）、`docs/VM_SPEC.md`（引擎通道节）、`docs/HYBRID_ARCH.md`（成本数字）、
本文件、`docs/handoffs/009-K-engine-check.md`（新建执行链）。
禁止：图侧/权重侧/`tests/` 既有用例、`ARCHITECTURE.md`、`README.md`（总控改）。

## 权威依据

- 判定合同：`lean_vm/step_driver.py:89-124`（reject 码/发射臂语义）、
  `expr/tokens.py:53-54`。
- 真 lean 判据（验收铁律 1）：引擎通道**不得**沿用 mutation 16 例的
  `run_check_oracle`（那是带 elaborator 的编译退出码 Meta-path，
  `reference/lean_ref.py:142-150`、`docs/ORACLE.md` :38 明言，J1 风险①）；
  对真 lean 的直连一律走 `#KDECL` addDecl 内核通道
  （`lean_ref.py:447`，样板 `tests/test_defeq_branches_vs_lean.py`）。
- 内核语义出处沿用图侧既有记录（VM_SPEC 各节），本卡不改语义只补通道。

## Verifier 集（完工唯一依据）

- [x] WHNF 基线不倒退：`SBIN=$PWD/model/<现真值>.sbin
  python3 -u scripts/verify_engine_vs_refvm.py` 34/34（原文）。
- [x] 三任务引擎对拍绿：CHECK 15 + INFER/DEFEQ 84 逐例，引擎判定 ==
  RefVM/`runner.py` 判定（accept/reject/reject_code 三元一致，原文尾行）。
- [x] 真 lean 直连抽验：CHECK 子集经 `#KDECL` 通道与引擎判定一致（≥10 例，
  含全部错误类别代表；原文）。
- [x] token 常量值 vs sbin meta 校验通过（硬编码防漂移）。
- [x] 20 套件回归（图侧零改动，canary 级即可，注明理由）— 选件与结果见
  `docs/handoffs/009-K-engine-check.md`「卡 013 续接」节 canary 回归段；
  原文 `$HOME/logs/013K/canary.log`（RUN1 engine_vs_refvm 1/1 rc=0，
  RUN2 level_vs_lean+level_encoding 2/2 rc=0，总 3/3 rc=0）。
- [x] 硬编码扫描零新增；`git diff` 只触及声明文件（扫描结论全文见
  `docs/handoffs/009-K-engine-check.md`「卡 013 续接」节硬编码扫描段）。

### 拍 1 验证证据（2026-09-21 续接落账，原文均见 009-K 续接节完工证据）

- ① WHNF 34/34：`$HOME/logs/013K/whnf_baseline_s1.log`
  `=== H3 engine vs RefVM: 34/34 verdicts correct ===`
- ② 三任务 99/99：`$HOME/logs/013K/tasks_s2.log`
  `=== engine tasks vs RefVM: 99/99 accept/reject+code triples correct
  (INFER 19 + DEFEQ 65 + CHECK 12 + SEQ 3), 540.8s ===`
- ③ KDECL 12/12：`$HOME/logs/013K/kdecl_s6.log`
  `=== engine vs #KDECL raw kernel: 12/12 consistent (>=10 required, all
  reachable error classes) ===`
- ④ meta：`$HOME/logs/013K/meta_s7.log`
  `=== engine meta vs sbin+tokens: OK (76 output dims, 13 token consts) ===`
- 真值钉定：卡 013 全部对拍用 `model/step_vm_015_full_scratch.sbin`（ARCHITECTURE
  真值表当前图侧封版验证基线，015 CLOSED 09-21），run 命令原文见 009-K S2/S2b 段。

## 排产与晋升约束

- 基线晋升：引擎对拍所用的 sbin 必须是**图侧封版代**的产物。F 链在途
  改 `build_vm.py` 时，任何重编的 scratch 混有未验收图改动（J1 风险②），
  只可作开发对照，不可当真值。真值表更新归总控。
- 机器：核 0-5（F/G/H 结案后空闲段），日志 `$HOME/logs/013K/`。

## 心跳预算

vm.cpp 重编译约分钟级；单例引擎对拍秒级；84+15 例全量对拍目标 <5 分钟。
超 1 分钟回路（全量回归）只在收尾跑。

## 决策引用

ADR 014（修订段：插卡与排产后段的人裁）、ADR 005（引擎权威/退役 dense）、
ADR 006（root delivery gate）、008 handoff J 段 B/C 条。
