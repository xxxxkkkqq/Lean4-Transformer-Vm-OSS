# 003. 字符串字面量比较套件的微步预算：600 → 6000

- 状态：accepted（2026-09-13，WP5）
- 背景：`tests/test_string_graph_vs_lean.py` 有 6 例报 `TimeoutError: no halt after 600 steps`（B `deq_oflist_true`/`deq_oflist_false`/`deq_proj_vs_oflist_true`，C `es_str_true`/`es_str_false`/`es_str_nultrue`）。用探针（环检测 + 逐步 frame/token 打印，脚本 `/tmp/wp5b_probe.py`、`/tmp/wp5b_counts.py`，日志 `/tmp/wp5b_counts*.log`）实测：**没有循环**。6 例全部真实停机——B 三例分别在 2449 / 670 / 2451 步停机并给出与 lean 一致的真值/假值；C 三例 710 / 628 / 708 步。调查同时暴露一个真实缺陷（见"预期后果"第 3 条，已另行修复），它使 `es_str_false` 的停机结果被误读为 True，但停机本身早已发生。5 例超时纯属预算不足。
- 真内核步数对照：
  - 内核 `is_def_eq_core` 对这条链**没有任何步数上限**：递归深度护栏 `scope_rec_depth` 的阈值默认 0 = unlimited（`/home/xkq/lean4/src/runtime/interrupt.h:45-48`，"0 means unlimited (the default)"），且它限的是 C++ 递归深度而非归一化步数；`try_string_lit_expansion_core`（`K/type_checker.cpp:1143-1156`）对展开后 spine 的每个 cons 节点再次调用 `is_def_eq_core`，任意深度合法。
  - oracle 实测：本套件 33 例在 lean 4.33.1 下全部即时返回 true/false，无一超时/崩溃——真内核接受了图因 600 预算而拒绝的这些计算。
  - 图的微步成本随展开深度线性增长（探针 `len 1..4`：380 / 710 / 1124 / 1622 步，约 330 微步/cons 层；`deq_oflist_swap` 548 步）。600 不是内核算法性质，是套件作者对单层展开成本的误估。
- 决策：`GRAPH_MAX_STEPS` 由 600 提到 **6000**（`tests/test_string_graph_vs_lean.py:109-117`，与仓内现成最大值一致：`tests/test_stepgraph_infer_defeq.py` 的 6000，其用例 `deq_brec_sum_stuck` 实测 1024 步）。不删用例、不加逐用例豁免、不改判定逻辑来迁就旧预算。
- 被拒方案：
  - 放宽/删除超时用例（指令明令禁止）；把慢用例标 xfail——掩盖 E3b 的真实语义覆盖。
  - 保留 600 并在 es_str 里"省步"（例如把 cons/nil 比较折叠成一帧）——实现优化可以以后做，但只能作为提速手段，不能作为预算正确性的依据；先按语义定预算，再谈优化。
- 预期后果：
  - 好：套件如实报告真实成本（全绿时实际最大停机步数 2451）；预算有内核侧与仓内双重背书。
  - 坏：字符串套件最坏耗时随上限线性放大（上限 6000 只在真停机时付费，实测均值远低于此）；长字符串（>4 codepoint）成本按层数线性、总步数约二次增长——corpus 不含此类输入，真正的尺寸上限问题归 card 006（本 ADR 不越界）。
  - 关联修复：`es_str_false` 停机态 (A=0, E=1, D=0) 的 `result_pos` 被 D_SP1 剥皮循环遗留在 C/F 的 pend 链指针经 `A_done` 的 `result_spine` 分支劫持（输出 2529 而非 0）。修复在 `lean_vm/build_vm.py:4729-4733`：新增 `A_res = _select(reglu(halt, ret_pending), SA, A_done)` 并令 `o_result_pos` 读 `A_res`（`:4745`）——停机时若手中是判决（`ret_pending`），结果即判决本身。whnf 的 spine-root 结果约定不受影响（其停机走 `complete` 且 E=0）。
