# 任务 006：WP6 `reduce_nat` 补齐（F 组）+ 尺寸上限

状态：**完成（附一项移交）**。总控五道门裁决 PASS，见
`docs/handoffs/002-C-wp6.md` 总控裁决段（2026-09-15）。F1-F9 图侧实现 +
差分测试 A31/B16 全绿 + 真值 sbin 晋升（16,468,986B @ 08:13:03）+
lead_reg4 亲跑 19/19。唯一未达成项"引擎 33/34→34/34"经 C5 根因判定为
**编译通道 ReGLU ±1000 钳位压平位置读数**（`engine/vm.cpp:523-524`、
`compiler/weights.py:451/516`、`model/runner.py:223-224`；符号求值器
`alm_p2.py:226` 无钳位），修复需动本卡禁改文件 ⇒ 移交
`docs/plans/008-compiled-channel-reglu-clamp.md`。
依赖：WP1、WP2、WP3。与 005 都触碰 `lean_vm/build_vm.py`，**必须串行**。

## 目标

`Nat` 位运算算子的图侧判定与真内核一致，并实现全部尺寸/上限行为：超限输入像内核一样报错而不是卡住或返回错值。

## 非目标

- 不改 `ref_vm.py` 成为第二实现（冻结）。
- 不做 Mathlib 规模性能优化（另卡）。
- 不动 `engine/*`、`compiler/*`。

## 涉及文件

`lean_vm/build_vm.py`、`expr/tokens.py:66-89`（`NAT_OPS`/`NAT_OP_ARITY`/`NAT_OP_CODES`）、新 `tests/test_reducenat_graph_vs_lean.py`、`docs/VM_SPEC.md`、`docs/KERNEL_COVERAGE.md` F 组状态。

## 权威依据（`docs/KERNEL_COVERAGE.md` F 组，逐条实现）

| 编号 | 功能 | kernel | 现状 |
|---|---|---|---|
| F1 | `Nat.succ` 含尺寸检查 | `K/type_checker.cpp:702-713` | 部分（无尺寸检查） |
| F2 | `add`/`sub`/`mul` 含尺寸检查 | `:717-719` | 部分 |
| F3 | `pow` 指数上限 + 结果尺寸估算 | `:720,660-675` | 部分 |
| F4 | `gcd`（`div`/`mod` 已有，含 `a % 0` 约定） | `:721-723` | 部分 |
| F6 | `land`/`lor`/`xor` | `:726-728` | 缺失 |
| F7 | `shiftLeft` 上限 + 尺寸估算 | `:729,677-690` | 缺失 |
| F8 | `shiftRight` | `:730` | 缺失 |
| F9 | `LEAN_NAT_MAX_SIZE`（默认 128MB）与 32 位指数/shift 上限行为 | `:36,298-313,656,670-673,685-688` | 缺失 |

## 附带收口的存量 bug（本卡的硬验收之一）

- **`pow` 引擎保真 off-by-one**：`scripts/verify_engine_vs_refvm.py` 唯一失败项。第 999 个 token 处 StepDriver 发 `litdig V2=1001`，引擎读回 `V2=1000`（F 通道读出偏一），fp64 与所有 dtype 同样不收敛，全局 H 下亦复现 → 与折叠/H 系列无关，是 `pow` 的逐位输出问题。定位与修复属于本卡。

## Verifier 集

- [ ] 新差分测试逐算子绿（含 gcd/land/lor/xor/shiftLeft/shiftRight 与超限拒绝，错误类别一致）
- [ ] `scripts/verify_engine_vs_refvm.py` 从 33/34 变 **34/34**
- [ ] 既有回归全绿：`test_stepgraph_infer_defeq` 84/84、`test_datadriven_env` 32/32、`test_datadriven_bool` 12/12、`test_level_vs_lean` 37/37、`test_check_e2e` A15/B15、`test_quot_graph_vs_lean` 7/7、（005 若已落地）`test_string_graph_vs_lean`
- [ ] 重编译 `--sparse` 报告 dims/lookups/RSS 增量（基线 16444 / 1915 / 624MB）
- [ ] 硬编码扫描零新增命中
- [ ] 超限用例不得靠"图里抛 Python 异常"通过——必须是与内核一致的 reject 判定

## 心跳预算

差分测试最小 env；单次反馈 ≤1 分钟；全量 ≤30 分钟。
