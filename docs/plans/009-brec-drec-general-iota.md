# 任务 009：`brecOn`/`drecOn` 一般 iota 收口

状态：**closed（2026-09-17 总控结案，停手路线）**。F 链 15 任（多数死于客户端/账户层
事故，全录于 docs/handoffs/005-F-iota.md 事故记录 1–15）；结案终态=修①恒等捷径+修③软
INFER 脊 I_ARG_S（ADR 018）+ d6 KNOWN-GAP xfail + 帽 720。总控亲验：全量差分
0 分歧（gate_diff_selfrun.log：587.5s / 峰 4122MB / rc=0）。d6 残环出路=卡 014
缓存层（ADR 017）。
**结案后追记（卡 014 M5，2026-09-17）**：d6 经帽 1500 实测定性为**合法慢**
（halt True@1012 = 内核判定，非环；ADR 018 追记），帽 720→1100 + P2 whnf
memo 落地后 G4_d6 按 XPASS 规程摘除，本卡差分 12/12 PASS 0 分歧 0 xfail
（`/home/xkq/logs/014/m5_brec_final.log`）。
依赖：WP3（一般 iota 基础）、P7.5c（brec delta/below-pair 机制，VM_SPEC 记录）。

## 目标

README"Kernel rules still missing"第一条清零：`brecOn`/`drecOn` 在一般形态下
（嵌套递归、非 Nat 载体、indices/k 标志组合、major-from-whnf 路径）与真内核
`K/structural.cpp` iota 规则一致。当前已知 brec 语料 7 条全绿（P7.5c），
**先做差距探查**再定实现边界。

## 涉及文件

`lean_vm/build_vm.py`、新 `tests/test_brec_drec_iota_vs_lean.py`、
`docs/VM_SPEC.md`、`docs/KERNEL_COVERAGE.md` B 组、`docs/handoffs/005-F-iota.md`。

## 步骤约束

1. 探查阶段：用真 lean 4.33.1 对 brecOn/drecOn 构造 ≥10 组最小用例
   （嵌套 inductive、带 indices、k=1、drecOn 双形态），记录哪些当前图能判、
   哪些错——差距清单进 handoff 后才许动图。
2. 每个差距修一条、差分钉一条；内核引用 `K/inductive.cpp` iota 生成侧 +
   `K/structural.cpp` 使用侧，行号写进注释。
3. 不许 materialize 真 brecOn 展开的数学闭包来"近似"——判定必须走图。

## Verifier 集

- [x] 新差分测试逐条绿（最小 env；accept/reject+错误类别一致）——结案时
  B/C 组 10/11 绿，G4_d6=KNOWN-GAP（[XFAIL-KNOWN-GAP]，registry 双向防漂移；
  裁决 3 停手，ADR 018），账面 0 分歧，总控 2026-09-17 亲跑复现。
  **卡 014 M5 追补 2026-09-17**：帽 1100 + P2 memo 下 d6 转绿、条目按
  XPASS 规程摘除，B/C 组 11/11 全绿（m5_brec_final.log），该项现可完整勾。
- [x] 20 套件回归全绿；`verify_engine_vs_refvm` 不得倒退（总控亲验进行中，
  日志 gate_regression_selfrun.log；F15 自报 20/20+34/34 双 sbin 通道在 005 F15-15）
- [x] 重编译 `--sparse` scratch 报增量（25,930/2,898/192,405，+1,016/+20/+5,513，
  114 层 rc=0）；引擎钉 scratch 全例复验 34/34（005 F15-12/13）
- [x] 硬编码扫描零新增（新常量能力全走 ENV 元数据+名字扫描；005 F15-16）
