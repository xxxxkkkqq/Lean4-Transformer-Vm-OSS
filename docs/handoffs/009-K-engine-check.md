# Handoff 009-K — 卡 013 引擎 INFER/DEFEQ/CHECK 权重通道（后端工程师执行链）

状态：**进行中**（lane B，派工 2026-09-21 晚，总控勘正版简报）。
基线钉 `model/step_vm_015_full_scratch.sbin`（图侧封版代，禁重编译——lane A
在途改 build_vm.py）。引擎构建 `PATH=/usr/bin:/bin make -C engine`。核 14-19，
日志 `$HOME/logs/013K/`。只许改 `engine/vm.cpp`、engine 构建脚本、新
`scripts/verify_engine_tasks.py`、本文件。

## 缺口核对（勘正实测，vm.cpp @ 派工时 609 行）

- 主循环 :579 只读 done，无 reject/reject_code 读取、无 T_REJECT(203)/T_HALT(204)
  终局（合同 lean_vm/step_driver.py:136-144；model/runner.py:273-280 参照）。
- 发射臂缺 em_raw、em_link2；em_link 现硬编码 E2=0/F2=0（contract 要
  link_flag/link_F2，step_driver.py:158-171）。
- 三任务入口缺：WHNF 之外无前导帧注入（参照 runner.py run_infer:357 /
  run_defeq:369 / run_check:379）。
- sbin meta 已含全部所需输出维（build_vm.py outputs dict :6710-6800，
  compile_vm 写 output_index=全 outputs；卡 008 桥接件 NAMES 表同源可证）。

## 实现设计（CLI 向后兼容，WHNF 用法逐字不变）

```
vm_run <weights> <stream> <term_pos> [max_steps]                          # WHNF
vm_run <weights> <stream> <term_pos> <max_steps> infer [env]
vm_run <weights> <stream> <t_pos> <max_steps> defeq <t_env> <s_pos> <s_env>
vm_run <weights> <stream> <v0> <max_steps> check <n> <t_i> <v_i> <e2_i>... # e2=0 即 runner 语义
vm_run <weights> --meta-check                                              # meta/常量转储
```
终局行：`DONE pos env steps`（不变）/ `REJECT code focus env steps`（新）/
`NOT_DONE steps`。reject 时先 emit T_REJECT(code)+T_HALT 再退出，不转发该两
行（与 Python step() raise 前流态一致）。发射顺序 raw,pend,link,link2,litdig,
frame,frame2,lithead,gap,litdig2,const,STATE（step_driver 合同）。

## 执行日志（每子步命令原文+输出尾行）

### S0 侦察（关键锚点，全部读码实证）
- reject 合同：step_driver.py:136-144；发射臂 145-204；三任务入口 248-304。
- runner.py 移植参照：step():264-343、run_infer:357、run_defeq:369、run_check:379。
- 语料：DEFEQ_CORPUS 65 + INFER_CORPUS 19（reference/toy_env.py，
  tests/test_stepgraph_infer_defeq.py 形态）；CHECK 12+3（tests/test_check_e2e.py
  CHECK_CASES+SEQUENCES，env=import_env(TARGET_DEFS,ROOTS)）。
- KDECL 样板：tests/test_defeq_branches_vs_lean.py（KDECL_MSG 模板、G_CODE 映射
  typeExpected→5 / declHasFVars→6 / declTypeMismatch→1、thmDecl 形状见
  test_decl_injection_vs_lean.py:158）。
- token 常量：T_REJECT=203 T_HALT=204（expr/tokens.py:75-76）；
  TASK_INFER=6 TASK_DEFEQ=7 TASK_CHECK=9（tokens.py:137-140）。
- sbin meta 实证：build_vm.py outputs dict :6710-6800 含 reject/reject_code/
  em_raw/raw_*/em_link2/link2_*/link_flag/link_F2 全部维；引擎
  `--meta-check` 转储 76 个输出维全对齐。

### S1 vm.cpp 改动 + 构建（2026-09-21 16:1x）
命令：`PATH=/usr/bin:/bin make -C engine` → 首轮报 emit  arity 错（T_HALT 少
参），修复（emit 补 7 参）后重编过（g++ -O3 -march=native）。
改动面（全部 engine/vm.cpp）：
1. reject 通道：新读 `reject`/`reject_code` 输出维，主循环 done 检查后按
   step_driver.py:136-144 语义发 T_REJECT(code)+T_HALT 并 break（不转发该两
   token、该步不计 steps），终局行 `REJECT code focus env steps`。
2. 发射臂：em_raw（raw_K..raw_E2，F2=0）插最前；em_link2（link2_*+flag/F2）
   插 em_link 后；em_link 补发 link_flag/link_F2（原硬编码 0）。
3. 三任务入口：CLI 向后兼容（argv[4] 数字=旧 WHNF；词=infer|defeq|check），
   前导帧注入逐字照抄 runner.py:357-398（infer 帧 E2=1；defeq 帧
   V1=t_pos/X=t_env/E2=s_pos/F2=s_env + STATE E/F；check 反序链 + STATE A=
   第一 val，逐锚点 E2 为 kind 数据参数，0=runner legacy 形）。
4. `--meta-check` 模式：转储 HEADER/SLOT/OUT/CONST（全部硬编码 token 常量 +
   读到的 meta），给 meta 校验门用。
冒烟（3 例）：infer DONE 114/0 → decode=Nat 与 RefVM 一致；deq_same DONE v=1；
check chk_dbl_nat DONE r=1（16 步）、chk_inc_fn_bad **REJECT code=1**（48 步）
——reject 通道端到端可用。

### S2 WHNF 基线（在跑，pid 见 ~/logs/013K/whnf_baseline.pid，脱管）
`taskset -c 14-19 env SBIN=$PWD/model/step_vm_015_full_scratch.sbin python -u
scripts/verify_engine_vs_refvm.py` > whnf_baseline_s1.log。尾前逐例 PASS
（含 pow 348 步、em_link E2/F2 补全后不破）。

### S2b 三任务对拍全量（在跑，pid=644005 ~/logs/013K/tasks_s2.log）
`verify_engine_tasks.py tasks`：INFER 19/19 PASS；DEFEQ 在途 58+ 全 PASS
（含 deq_boolcaseson_stuck v=1、deq_rec_no 375 步）；CHECK 15 随后。

### S3 KDECL 阶段调试记录（同类错误第 2 次，按防线§1第4条已停手写证据）
- 第 1 败：run_check_oracle 未用（KDECL 正确通道），败因=序列化器括号错位
  （`Lean.mkConst ``X` 多闭括号）。修 `_ser` 全节点带括号。
- 第 2 败：`.defnDecl` 尾 `all := [\`name}` 缺 `]`；`\`\_` 非法名称；
  thmDecl 无 isUnsafe 字段（test_decl_injection _THM 形）。修复后 12 例中
  10 例 lean 侧已出 OK/typeExpected/declHasFVars。
- 第 3 败（已修）：`\`\`b` 做标识符解析报 unknown identifier——binder 名改
  单反引号字面量。kdecl_s5 在跑（pid 见 ~/logs/013K/kdecl_s5.pid）。
- 旁证（手动 lean 跑生成件）：k_ok×5 全 OK、k_te=typeExpected、k_fv=
  declHasFVars、k_np=thmTypeIsNotProp——kernel 侧类别与预期一致。

### meta 阶段（已过一次）
`verify_engine_tasks.py meta` → `=== engine meta vs sbin+tokens: OK (76
output dims, 13 token consts) ===`（终版在 tasks/kdecl 后复跑钉原文）。

## 卡 013 续接（2026-09-21）

计划清单：①核对四份验证日志尾行并钉原文进本节 → ②canary 回归（图侧零改动，
2-3 小套件，SUITE_FILTER 用法看 run_cpu_regression.sh 头）→ ③硬编码扫描
（git diff engine/vm.cpp 对照 expr/tokens.py）→ ④013 卡 verifier 复选 + 状态行
更新 → ⑤完工报告。不 commit、不改实现逻辑、禁动 lean_vm/expr/model/tests/
ARCHITECTURE.md/docs/VM_SPEC.md。

### 完工证据（四日志原文，2026-09-21 16:42 复核）

- ① WHNF 基线 34/34：`$HOME/logs/013K/whnf_baseline_s1.log` 尾行
  `=== H3 engine vs RefVM: 34/34 verdicts correct ===`（前一行
  `argmax vs softmax streams identical: 34/34`）。
- ② 三任务对拍 99/99：`$HOME/logs/013K/tasks_s2.log` 尾行
  `=== engine tasks vs RefVM: 99/99 accept/reject+code triples correct (INFER 19 + DEFEQ 65 + CHECK 12 + SEQ 3), 540.8s ===`。
- ③ KDECL 真 lean 直连 12/12：`$HOME/logs/013K/kdecl_s6.log` 尾行
  `=== engine vs #KDECL raw kernel: 12/12 consistent (>=10 required, all reachable error classes) ===`
  （覆盖面：OK×6 + declTypeMismatch×3 + typeExpected=5 + declHasFVars=6 +
  thmTypeIsNotProp=8，全部错误类别代表）。
- ④ meta 校验：`$HOME/logs/013K/meta_s7.log` 尾行
  `=== engine meta vs sbin+tokens: OK (76 output dims, 13 token consts) ===`。

### 硬编码扫描（git diff engine/vm.cpp vs expr/tokens.py，2026-09-21 续接）

结论：**零新增魔法数/cid 写死**。全部输出维索引经
`need(W.output_index, "<名字>")` 按 sbin meta 动态解析；所有数值常量为流
token kind（stream contract，不入权重文件），源码单点 `expr/tokens.py`，
`--meta-check` 把 13 个 token 常量全部转储、由 `verify_engine_tasks.py`
meta 阶段对拍防漂移（证据④，meta_s7 76 dims/13 consts 全对齐）。无具体
常量名/cid 进逻辑分支（验收铁律 3 不破）。逐改动面对照：

1. **reject 通道**（diff 段：`I_REJECT/I_REJECT_CODE` 两行
   `need(...,"reject"/"reject_code")` + 主循环 `if (rd(I_REJECT)) { … }` +
   终局 `REJECT %lld %lld %lld %lld`）：只用 T_REJECT=203/T_HALT=204 两个
   流常量（注释指 expr/tokens.py:75-76，meta 转储），reject_code 直接取自
   图输出维 `reject_code`，不映射任何具体错误码常数到 cid。
2. **em_raw + em_link2**（diff 段：`I_ERAW/I_RAW_*` 6 维、`I_ELINK2/I_LINK2_*`
   6 维、`I_LINK_FLAG/I_LINK_F2` 两维 `need` + 主循环三条 emit）：em_raw 形
   `emit(rd(I_RAW_K), raw_V0..raw_E2, 0)`——F2=0 与 step_driver.py raw 臂不传
   F2（_append 默认 0）逐字一致；em_link 补发 link_flag/link_F2（原硬编码 0）、
   em_link2 同用 T_LINK——与 step_driver.py:170-183 对拍；发射顺序
   raw,pend,link,link2,litdig,... 与 step_driver.py:145-204 逐项一致。
3. **三任务入口**（diff 段：argv[4] 解析 + 前导帧注入 + 终局输出）：argv[4]
   数字=legacy WHNF（strtoll 全字解释，非魔法数），词=infer|defeq|check；
   前导帧逐字对照 runner.py:357-398——infer 帧 E2=1 是 runner.py:359
   `_append(T_FRAME, V0=TASK_INFER, V2=0, X=0, E2=1)` 的契约复制；defeq/check
   帧 E2/F2 全从命令行参数来；check 的 per-anchor E2 为 ENV_FORMAT §2.8 kind
   载体（0=runner legacy all-inert 形）。TASK_INFER=6/TASK_DEFEQ=7/
   TASK_CHECK=9（tokens.py:137-140，meta 转储防漂移）。
4. 触碰面：本卡新增 = `engine/vm.cpp`（diff 188 行）+ 新
   `scripts/verify_engine_tasks.py` + 本文件。工作树另存的
   `expr/tokens.py`/`lean_vm/build_vm.py`/`lean_vm/step_driver.py`/
   `tests/test_decl_injection_vs_lean.py` 改动属 lane A 并行在途（派工时就
   已存在，009-K 头注明 lane A 改 build_vm.py），非本卡产物，本代理未触碰。

### canary 回归（2026-09-21 续接，脱管 pid 见 $HOME/logs/013K/canary.pid）

选件理由：引擎代码变了、图/权重零改动，canary 只验「引擎改动没把既有通道
弄坏」——必需直接验引擎的那一件：`engine_vs_refvm`（WHNF 通道、发布件
`model/step_vm_new_sparse.sbin`，34 例全跑含 pow）；另加两件小而快的
不可变 ENV 层套件（`level_vs_lean` + `level_encoding`，均不 import 在途改 的
`build_vm.py`）作环境冒烟。三次调用 `run_cpu_regression.sh`
`SUITE_FILTER=` 过滤，`REGRESSION_CORES=14-19`、`OMP_NUM_THREADS=3`、
`PYTHON=/home/xkq/miniconda3/envs/train/bin/python`、`L4TVM_LEAN` 钉
4.33.1、`REGRESSION_LOG_DIR` 独立防与其他会话互踩。总时长 10 分钟（
04:05:13→04:15:07），<30min 预算。

结果（原文）：
- RUN1 `engine_vs_refvm`：`--- engine_vs_refvm: PASS  [all 34 cases incl.
  pow since card 008]`；`=== CPU regression: 1 passed, 0 failed ===`；
  `rc1=0`；（H3 行 `=== H3 engine vs RefVM: 34/34 verdicts correct ===`
  收尾，wall 592.2s peak RSS 164MB）。
- RUN2 `level` 两件：`=== CPU regression: 2 passed, 0 failed ===`；`rc2=0`。
- 汇总日志 `$HOME/logs/013K/canary.log`，套件日志
  `$HOME/logs/013K/canary_{engine,level}/<label>.log`。

