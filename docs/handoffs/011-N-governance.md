# Handoff 011-N — 治理重整 + 卡 010 G02 验收收口（2026-09-20）

总控会话（项目经理职责首次显式化：AGENTS.md §二 角色分工）。上一状态见
handoff 006（G02 checkpoint，3 verifier 在跑）与防线 §3.7（发布规程定案）。

## 当前状态

**一、G02 验收通过（卡 010 整卡仍 open，余 G6 mutual 拍）**

- 差分全集 54/54 + 2 xfail（非归一 level 形 KNOWN-GAP，ADR 021）rc=0：
  `/home/xkq/logs/010G/lead_full_suite.log`。
- 载体空闲性 guard 全语料 PASS（同日志）。
- 22 套件回归等效齐全：21 项 09-19 06:43 PASS；mutation_reject 当趟超时定性
  环境性（当时 GPU 训练占机），09-20 单项重跑 **rc=0**（A 16/16、B 8/8，
  754.8s/1552MB）：`/home/xkq/logs/010G/mutation_rerun/`。代码态一致性证明：
  `git diff 15a500d..HEAD --stat` 零代码文件。
- 硬编码扫描零新增（仅存量：注释 1 处 + `CID_P2MK + 1` 已知项 build_vm.py:5061）。
- 两条 checkpoint 待裁项已裁（ST 帧 E2 追认 / 引擎码 8 维持 NOT-VERIFIED 归卡 013），
  原文见 handoff 006 末段；卡 010 派工增补 3 有逐条清单。
- 合同变更（总控执笔）：`decl_injection_vs_lean` 入回归表，基数 22 → **23**
  （2100s/4000MB，按实测 1395.6s/2101MB 定帽）。

**二、仓库治理重整（用户指令：清理无用件、分类、AGENTS.md 角色化）**

- 根目录删除（git rm，历史可找回）：HANDOFF_M5.md、PROGRESS.md、
  下一窗口提示词.md、fidelity.log、smoke.log、logs_milp.txt、plan.pkl（零引用）；
  未跟踪件 engine.log、smoke_m2_regress.log 直接删，NEXT_PROMPT.md（机密、内容
  已全面过时且与现行纪律矛盾）移出仓库至 `~/l4tvm-attic/`。
- 归档：docs/PLAN.md（Phase 0-7 台账，加归档横幅）、docs/HANDOFF.md（已作废的
  集中式交接）、docs/GPU_SPEED.md（基于已退役 dense 件）→ `docs/archive/`。
- 断链修正：DESIGN.md/ARCHITECTURE.md 指针、lean_kernel 两处 docstring、
  .gitignore 失效条目；空壳 `kernels/` 目录删除（未跟踪，代码早已迁
  lean_vm/primitives.py）。
- **AGENTS.md 角色化重写**（5925a5d/fb30fbb 起）：§0 会话开场固定顺序；§二
  六角色分工（总控/Lean4 语义设计师/图逻辑工程师/后端工程师/测试工程师/
  审核工程师）+ 任务生命周期 + "完成即写文档不延误"硬规则；§六 代码组织
  （分层 import 纪律、大文件拆分须开卡）。
- **会话启动钩子已修**：`.claude/hooks/inject-handoff.sh` 原来向每个新会话注入
  "先读 docs/HANDOFF.md"（已作废文档）——改为注入 AGENTS.md §0 开场顺序。
  这是本次盘点发现的最危险残留。
- 交接链全 13 份、ADR 全 21 份、任务卡全 11 份**一份未删**（005-F-iota 与
  010-M-cache 虽 163KB/94KB，是卡 009/014 的证据链正文，被 ADR/闭卡活引用）。
- 盘点代理判定的其他事项：卡 012 M-A 状态疑似脱节（plans/012 "M-A in progress"
  vs handoff 007 自 09-16 03:28 无追加、裁决段空），列入下一步核对。

## artifact 状态

与 ARCHITECTURE.md 真值表一致（本会话已同步）：发布件仍
`model/step_vm_new_sparse.sbin`（P1-only 交付态）；`step_vm_010_scratch.sbin`
为 G02 已验收验证件，仍非发布、禁当基线；本会话未编译、未动任何权重/二进制。
`engine/vm_run` 未动。

## 已定决策

- G02 收口与两条裁决：handoff 006 末段 + 卡 010 派工增补 3（依据 ADR 020/021，
  未新开 ADR——治理重整是流程变更非架构变更，落在 AGENTS.md 本身）。
- 回归表 22 → 23：`scripts/run_cpu_regression.sh` 内注释即变更记录。
- 文档处置原则：**交接链/ADR/任务卡不删**（证据链）；删的只是无人引用、内容
  过时或自认易耗的提示词件与快照；归档用 git mv 保路径历史。

## 下一步（按序，≤3 条，每条可直接开工）

1. **卡 010 G06 拍**：mutual 块前置可见 + 块内重名。设计备案 handoff 006 §3
   （add_mutual :225-269、check_multi_param_names :236-241、新码 9=driver 簿记族）；
   派工走新 G0x 链，表头先落盘，测试行集含互块自引用正/反例与重名拒。
2. **卡 012 M-A 状态核对**：读 `/home/xkq/logs/012I/` 与 handoff 007，核对
   Mathlib 闭包抽取器真实进度，更新 plans/012 状态行并补 handoff 007 裁决段。
3. **里程碑出口快照**：下次卡结案/晋升门按防线 §3.7 执行
   （commit-tree 建快照提交 → `git branch -f public-main` → `git push origin
   public-main:main`——push 是对外发布，人工按键）。

## 已知陷阱

- mutation_reject 的 900s 帽贴着实测 755s，机器一忙就超时：**超时先单项重跑再
  定性**，别当语义回归（本次已两次验证是环境性）。
- 回归现在 23 套件，全程 ~2h；`SUITE_FILTER` 支持单项，别为省时整趟跳过。
- 文档按路径/哈希落账：**不要移动** docs/handoffs/、docs/decisions/、scripts/
  下的既有文件（209 处引用）。
- 会话启动钩子现在注入 AGENTS.md 开场顺序；若见"先读 docs/HANDOFF.md"字样，
  说明跑在旧 hook 上，别照做。
- NEXT_PROMPT.md（`~/l4tvm-attic/`）内容过时且与现行纪律矛盾，仅考古用。

## 进度追记（2026-09-20 下午，同会话续）

- **oracle 漂移事故与修正**：elan default 09-20 实测漂到 4.34.0 → 今晨 mutation 重跑
  实际用了 4.34.0 oracle（证据作废重立）。修正=仓库侧钉 4.33.1（lean_ref.py 解析 +
  L4TVM_LEAN + 回归脚本自检，commit 6c938cb），顺手清偿 009-L 欠账（Mathlib 路径
  /tmp/mlbench→/home/xkq/mathlib_src，kernel_oracle 的 Mathlib 容量段不再静默跳过）。
- **G06 拍 CLOSED**（ InjectionEnv + add_mutual 两阶段 + 码 9；64/64 全集；全量回归
  **23/23 rc=0**，/home/xkq/logs/010G/g06_reg/——mutation 在 4.33.1 上 rc=0 重立）。
  注意：decl_injection 全集涨到 1492.8s，回归表 2100s 帽只剩 1.4x 裕量。
- **卡 012 M-A 完成**（I2 链）：闭包抽取器 + 3 定理 874 常量 + 元数据往返零差异 +
  结构测试 2196 checks rc=0（总控亲跑复验）。M-B/M-C/D 仍 open。
- 下一步：G03 拍（unsafe 图臂）已派工，表头见 handoff 006。
