# 任务 012：Mathlib 规模——证明闭包抽取 + 紧凑 ENV 编码 + 端到端抽验

状态：M-A **完成（I2，2026-09-20，五道门收口）**：3 定理闭包导出（874 常量，
Nat.testBit_land 779 / Vector3.cons_fz 87 / Quot.liftOn_mk 8），874/874 元数据
addDeclWithoutChecking 往返零差异（含全部 62 inductive 与内核重算 recursor 规则），
结构测试 2196 checks rc=0（总控亲跑复验）。I1 断链验尸与资产坐标见
docs/handoffs/007-I-mathlib-closure.md。M-B/M-C/M-D 仍 open，按 ADR 014 顺序
等图侧收口；M-B 可直接用 779 常量闭包 ENV 做编码规模实验（仍禁喂 Python 图求值）。

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
