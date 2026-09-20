# ADR 014：人工指令扩容范围——五条接缝、iota 一般性、Mathlib 规模全部转为在办工作包

日期：2026-09-15。决策人：人（项目所有者），总控落档。

## 背景

卡 007 结案时把 G3/G6/G8/G9/G2-unsafe 记为"当前架构不可表达"的接缝
（`docs/handoffs/003-D-wp7.md`）；README 另列 `brecOn`/`drecOn` 一般 iota 与
Mathlib 端到端未试为缺项；`docs/DESIGN.md` §7.2 把 Mathlib 规模列为风险并
给出处方（按证明抽闭包、紧凑编码、完整元数据）。

## 指令

人明确裁定：以上全部**都要完成**，不接受"接缝/移交"作为终态。

## 影响

1. 范围合法性：DESIGN §5 本就要求 environment.cpp 全部声明加入检查
   （含 theorem 的 `is_prop`）；Mathlib 按 §7.2 处方执行不算改宪法。
   五条"不可表达"接缝改判为"待架构改造"，立卡排产。
2. 新工作包（`docs/plans/009-*.md` … `012-*.md`），执行序：卡 008（在途）→
   里程碑出口（iota 大 env + pow 全量收拢）→ 009（iota 一般性）→
   010（step_driver 注入协议改造，解锁 G3/G6/G2-unsafe）→ 011（G8/G9 表达层）→
   012（Mathlib 闭包规模）。
3. 新增属主：`lean_vm/step_driver.py` 首次列入文件所有权表（卡 010 属主），
   它不是冻结文件（不在 AGENTS 冻结清单），但改造必须保持既有 verifier 全绿。
4. 验收不变：仍按 AGENTS 五道门 + 真 lean 差分；Mathlib 卡的第一里程碑是
   闭包编码正确性（差分抽验），不是全库吞吐。

## 备选（否决记录）

- 维持接缝为终态：与 §5"复刻 environment.cpp 检查路径"矛盾，且人否决。
- 把 Mathlib 解释为非目标：§6 未列它，§7.2 给了处方，属风险项非排除项。

## 修订（2026-09-16，人裁，lead3 会话落档）

008 handoff 的 J1 审计 B 条证实"引擎 CHECK/INFER/DEFEQ 权重通道是纯工程"
（vm.cpp 缺 reject 通道、em_raw/em_link2/link_env 发射臂、三任务入口；估
100-200 行 C++，不动 sbin 格式），人裁定：**插卡 013 入册，排后段**——
009 结案后排产（engine/* 与 010/011/012 文件零交集，但按"同时只许 1 个
写盘代理"串行纪律，在途链间隙派发）；013 产物晋升基线必须等图侧封版
（F 链在途改 build_vm.py，任何时点重编的 sbin 都会混入未验收图改动，
J1 风险②）。排产序变为 009 → 010 → 011 →（013 机动）→ 012 收口。
原执行序其余部分不动。见 `docs/plans/013-engine-check-channel.md`。
