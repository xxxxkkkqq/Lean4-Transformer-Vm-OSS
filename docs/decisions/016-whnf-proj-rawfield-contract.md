# ADR 016（草案，未裁决）：TASK_WHNF 交付合同——proj 停 raw field vs 续 whnf 到头范式

日期：2026-09-16　状态：**accepted — 采方案 B**（2026-09-17 总控裁决，见文末
"总控裁决"节；B 的实作折入卡 010/ADR016-B 子任务，卡 009 按零图改动结案不受影响）
相关：docs/handoffs/005-F-iota.md（G1 行、a1"载体推广"段）、docs/plans/009-brec-drec-general-iota.md、
docs/VM_SPEC.md §11.15（P7.5c-1b）、§11.18（P7.5c-M5）、§8（DEFEQ 软 whnf）

## 背景

真内核的 `whnf_core` 在 `reduce_proj` 成功后**继续归约交付结果**
（`/home/xkq/lean4/src/kernel/type_checker.cpp:504-508`：proj-reduce 回灌
`whnf_core(*m)`），即 `t.fst` 的 whnf 是"字段值继续 whnf 到头范式"。
图的 I_PROJ 分支按 P7.5c-2 合同实现为：对 TASK_WHNF 调用者（帧 E=1 侧），
字段交付即终止 whnf，停在 **raw field**（未归约的字段应用）；理由当时记录在
VM_SPEC §11.16 注（brecOn 的真值形 `(go t F).1` 停在 F 应用上，图若续 whnf
会把"应当 stuck 的开放项"多推一步；权重把该合同烤进编译产物）。

卡 009 探查（F2→F4→F5 链）钉死了这个合同的完整影响面：

- **G1（Nat 载体）**：忠实 ENV（真 dump 的 `Nat.brecOn/go/below` 值）下，
  `#WHNF (brecOn 2 F2s)` 图停在 raw field
  `F2s (succ(pred n)) (Nat.rec …)`；oracle WHNF 给出字面量。
- **a1 载体推广**（F4 收编 mu/iv/nt 组 + F5 复核）：同一机制在 **Lst、互递归
  MA/MB、索引化 IV、嵌套 MyTree** 四种载体全部复现——与载体无关，凡
  "proj 交付头是未归约应用"的 whnf 请求都停 raw field。
- **通道不对称**：DEFEQ 通道不受影响（软 whnf 会继续 delta/beta/iota：G3 三例、
  D5 恒等式在图上都与 oracle 一致）；缺口只伤 **TASK_WHNF 顶层交付**——
  即 CHECK/whnf 直出路径与一切以 whnf 结果为输入的下游。

## 决定（草案，三选一，倾向 B）

**A. 图侧改合同**：I_PROJ 交付点对 TASK_WHNF 调用者继续一轮 whnf
（对齐 `type_checker.cpp:504-508` 的回灌）。
- 代价：交付合同变更 → 全部 whnf 差分基线重钉（引擎 34/34、20 套件、
  `test_stepgraph_vs_refvm` 37 例、`verify_engine_vs_refvm`），权重重编，
  且需处理"停 raw field 正是某些绿用例的原因"的存量用例（P7.5c-2 注中
  的开放项场景必须逐例复核）。
- 风险：软/硬拒绝边界移动，历史上 UL 链的软旗 bug（§11.17）即此族。

**B. 合同不动，调用方续 whnf（推荐）**：TASK_WHNF 交付 raw field 保持为
图的稳定原语；在驱动器层（whnf 任务的顶层出口）对交付闭包再发一轮
TASK_WHNF 直到焦点不再前进（内核 `whnf_core` 的循环语义等价搬出图外）。
- 与验收铁律的关系：判定仍全走图（B 的循环由图自己的 whnf 任务构成，
  不引入 Python 语义近似）。
- 边界：属主与 `step_driver.py`（卡 010 协议域）交叉，需要与声明注入协议
  的 owner 协调；改动面 = 驱动器出口一处，不触权重/引擎。
- 注意停止条件必须复用 TimeoutError 预算，防止 open 项上的空转
  （焦点不变即停，参照 §11.17 的 decline 语义）。

**C. 记录为已知限制不修**：whnf 顶层交付仅服务开发通道，真实验收走 DEFEQ/
CHECK（不受影响）。若总控判定下游无人消费 raw field，则维持现状并在
VM_SPEC §9 记合同边界。

## 影响面与证据索引

- 复现材料：`/tmp/probe009F/` probe2（G1 原表）、probe_groups.log
  （a1 四载体）、f5_* 系列（F5 复核）；oracle 判定原文在
  `$HOME/logs/009F/`。
- 与缺口 #2b 的关系：F5 证明 D3/D4 的 DEFEQ False 另有图侧下降 bug
  （`UnitT vs Nat` 的组件比较，见 005 F5-b03 段），**与本合同正交**；
  本 ADR 不解决、也不掩盖那条。
- 不许顺手做的事：在测试侧用 `Nat.brecOn.real`（pair-free 重建近似）绕开
  本缺口——那是 P7.5c-3 的旧路线，卡 009 的目标恰恰是废掉近似。

## 结论

等总控在 A/B/C 中裁决；裁决前卡 009 的 b 项按"零图改动"执行，
本 ADR 只立项不实现。

## F15 复核（2026-09-16，未裁决、只核对）

卡 009 收口复核，本 ADR 状态不变（draft，A/B/C 仍待总控裁决）：

- **合同未被卡 009 第 14 任执行触碰**：F15 的软 INFER 改造（ADR 018 的
  I_ARG_S 臂）只动 build_vm.py 的 INFER 通道，I_PROJ 交付点与
  TASK_WHNF 合同一字未动；引擎/权重/驱动器零改动。
- **DEFEQ 通道不受影响的结论复核成立**：卡 009 全量差分（B/C 组 11 例
  DEFEQ）中除 G4_d6（KNOWN-GAP，见 ADR 018，与本合同正交——残环在
  卡对链比较的 below 展开，不在 proj 交付点）外全部与 oracle 一致。
- 引用核对：VM_SPEC §11.15（:1069）/§11.16（:1104）/§11.17（:1165）/
  §11.18（:1194）/§8（:236）、005-F-iota.md G1 行均在；证据材料
  `/tmp/probe009F/` 与 `$HOME/logs/009F/f5_*`（21 个文件）在位。
- B 选项的 step_driver 属主交叉提醒仍成立：驱动器出口续 whnf 需与
  声明注入协议 owner 协调（ADR 014/卡 010 域）。
