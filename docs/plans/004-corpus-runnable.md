# 任务 004：把端到端权重/引擎验收跑起来（含回归入口补全）

状态：**完成（2026-09-14，B/B2 链交付，总控五道门 PASS）**。reg3 全量 18 套件（B2 跑 17/18；string 一项由总控以 cap 复核裁决 5000→6000MB 后独立重验 rc=0，实测树峰 5259MB）= 有效 18/18 绿。裁决与证据见 `docs/handoffs/001-B-004.md` 总控段。

## 目标

"权重侧端到端与真 lean 判定一致"这件事重新变成可跑的：三个现在因缺 artifact 而**根本没在跑**的测试要么能跑要么消失；`scripts/run_cpu_regression.sh` 覆盖当前全部套件。

## 非目标

- 不改图语义（禁止碰 `lean_vm/build_vm.py`、`expr/tokens.py`、`expr/model.py`）。
- 不为跑通而 materialize dense 权重（>1GB checkpoint 需先 ADR，见红线 9）。
- 不实现引擎侧 INFER/DEFEQ/CHECK（那是独立包，本卡只把现状钉死并写清缺口）。

## 涉及文件

`tests/test_endtoend_corpus.py`、`tests/test_engine_vs_runner.py`、`tests/test_weights_fidelity.py`、`model/runner.py`、`scripts/run_cpu_regression.sh`、`scripts/verify_engine_vs_refvm.py`、`ARCHITECTURE.md` 真值表、新 `docs/decisions/003-*.md`（若需要 sparse-as-default 契约）。

## 现状（2026-09-14 实测）

- 三个测试默认路径 `model/step_vm.pt` **不存在** → 不是失败，是没跑。
- 磁盘上 `model/step_vm_new.pt/.bin`（4.07GB）是 pre-WP8 过期快照，对它跑 `test_weights_fidelity` 报 `KeyError: 'dbg_r0'`（checkpoint 与 output-map 版本不匹配）。
- 当前有效产物只有 `model/step_vm_new_sparse.sbin`（L4SV v2，11.3MB）。
- `scripts/run_cpu_regression.sh` 清单落后：缺 `test_datadriven_env/bool`、`test_level_vs_lean`、`test_env_meta*`、`test_quot_graph_vs_lean`、`test_iota_graph_vs_lean`。

## 要做的决定（写进 ADR 003）

Python 权重 runner 是走 `compiler/weights.py` 的 `SparseLeanModel` 直接吃 `.sbin`，还是让三个测试统一改为**以 C++ 引擎为准**（`engine/vm_run` + `scripts/verify_engine_vs_refvm.py` 的通道），Python runner 只保留作开发探针。倾向后者：dense Python 路径与 19GB 一起退役，别再维护两套执行器语义。

## Verifier 集

- [ ] `run_cpu_regression.sh` 全清单跑通（列出实际跑的套件名与各自结果原文）
- [ ] 三个测试各自的结局明确：跑通（贴原文）或按 ADR 删除/合并（贴 diff 说明），不许留"存在但没跑"
- [ ] `test_weights_fidelity` 若保留：换成与当前图版本匹配的产物生成路径，并贴 `dbg_r0` 问题消失的证据
- [ ] 不动 `build_vm.py` 前提下，`scripts/verify_engine_vs_refvm.py` 结果不倒退（当前 33/34）
- [ ] `ARCHITECTURE.md` 真值表更新为实际磁盘状态（含新产物与生成命令）

## 心跳预算

本卡以工程接线为主，单次反馈 ≤1 分钟；全量回归一次 ≤20 分钟。
