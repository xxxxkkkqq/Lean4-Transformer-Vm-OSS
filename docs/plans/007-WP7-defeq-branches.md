# 任务 007：WP7 `is_def_eq` 剩余分支（A 组缺项 + G 组）

状态：**完成（附接缝移交）**。总控五道门裁决 PASS，见 docs/handoffs/003-D-wp7.md 总控裁决段（2026-09-15 夜）。A14/A15/A17/A24(前卡)/A26/A30 + G1/G2safe/G4/G5/G7/G10/G11 落码差分全绿；G3/G6/G8/G9/G2-unsafe 五条记为架构不可表达接缝（立卡前不做）。真值 sbin 已晋升 24914 dims。
依赖：A18 已完成（WP2）；E3 接入依赖 005。

## 目标

`is_def_eq_core` 的剩余判定分支与真内核一致，使图侧 DEFEQ 覆盖当前缺的分支；G 组声明/环境检查的错误类别与真内核一致。

## 非目标

- A27 成功/失败缓存属性能优化，不影响判定，**不在本卡**（需要时另卡 ADR）。
- 不做 lazy delta 的缓存表实现细节优化（判定语义先行）。
- 不动 `engine/*`、`compiler/*`。

## 涉及文件

`lean_vm/build_vm.py`、`expr/tokens.py`（如需 hints/mdata 编码）、新 `tests/test_defeq_branches_vs_lean.py`、`docs/VM_SPEC.md`、`docs/KERNEL_COVERAGE.md` A/G 组状态。

## 权威依据（逐条）

| 编号 | 功能 | kernel |
|---|---|---|
| A14 | reflection 分支（`t` 无 fvar 且 `s = Bool.true` → 全归约 `t`） | `K/type_checker.cpp:1181-1185` |
| A15 | `is_def_eq_core` 先 `whnf_core(..., cheap_proj=true)` | `:1194-1195` |
| A17 | `lazy_delta_reduction` + `_step`（hints 比较、`try_unfold_proj_app`、`is_def_eq_args`、失败缓存） | `:999,1088` |
| A24 | `try_string_lit_expansion`（依赖 005 的 E 组） | `:1145-1156` |
| A26 | `is_def_eq_offset`（Nat 字面量 / `succ` 的 offset 比较） | `:1076` |
| A30 | `try_unfold_proj_app` | `:983` |
| G1 | `check_constant_val`（check_name、dup univ、no metavar/fvar、`check(type)`、`ensure_sort`） | `K/environment.cpp:127-133` |
| G 组其余 | 见 `docs/KERNEL_COVERAGE.md` G 组表逐行 | — |

## Verifier 集

- [ ] 新差分测试：proof-by-reflection / `decide` 用例、投影与 delta 交错、offset 字面量、G 组各类错误（错误类别必须一致）
- [ ] 既有回归全绿（同 006 清单 + 005/006 新测试）
- [ ] 重编译 `--sparse` 报告增量；`scripts/verify_engine_vs_refvm.py` 不得倒退
- [ ] 硬编码扫描零新增命中
- [ ] hints/reducibility 判定必须由 ENV 元数据驱动（`docs/ENV_FORMAT.md`），不许按常量名写死

## 心跳预算

最小 env 为主；DEFEQ 用例步数大，单例上限 400 步并记录实际步数。
