# 006. 根投递 gate 必须恒二值：修正 ADR-003 的 A_res 关联修复

- 状态：accepted（2026-09-14，WP5 收尾，代理 A）
- 关系：修正（不推翻）ADR 003「关联修复」条目；语义规格同步在
  `docs/VM_SPEC.md` §14.8。

## 背景

ADR-003 的关联修复把 `result_pos` 改为
`A_res = _select(reglu(halt, ret_pending), SA, A_done)`，治好了
`es_str_false` 的 stale-pend 劫持（halt=1 通道）。但 `halt` 是加法通道：
字面量 INFER 的投递步同时满足两条根 halt 条件——

1. `ret_pending`（E=1 ∧ 无框：INFER 结果在 A，机器协议）；
2. `complete`（focus 恰是不动点常量——`infer_lit` 的返回类型
   `Const(String)` 本身，内核语义对应 whnf 对常量/字面量原地返回，
   `K/type_checker.cpp:474-477`）。

两者合计 `halt=2`，gate `halt·relu(ret_pending)=2` 非二值；
`_select(cond, yes, no) = cond·yes + (1−cond)·no` 在 cond=2 时线性外推
`A_res = 2·SA`（1198→2396），驱动侧 `decode_closure` 报
`IndexError: list index out of range`。B 段 `infer_lit/infer_empty/infer_uni`
三例因此从 PASS 退化。单步探针证据：
`/tmp/wp5A_probe_infer2.log`（PRE 1: done=2, result_pos=2396）。

## 决策

gate 改用**恒二值**的根投递通道本身：

```python
A_res = _select(reglu(ret_pending, One - has_frame), SA, A_done)
```

（`lean_vm/build_vm.py` A_res 定义处，注释注明不变式。）

依据的机器不变式：**E=1 到根的投递，结果在 A**（DEFEQ 的 0/1 判定、INFER
的类型位置），永不是 pend-spine 根 SF；whnf 的 spine-root 约定走
`ret_pending=0` 分支的 `A_done`，不受影响。ADR-003 的
「whnf 停机走 complete 且 E=0」论证只对 WHNF 投递成立，漏掉了
「INFER 类型是不动点常量 → 同一步两个通道都真」的组合——本 ADR 补上。

行为差：仅 halt=2∧ret_pending 的三例从 `2·SA` 恢复为 `SA`；halt=1∧
ret_pending（es_str_true/nultrue、deq_oflist_* 等全部既有绿路）gate 同为 1，
不变；ret_pending=0（WHNF 根投递、CHECK accept）走 `A_done`，不变。
`done=2` 本身保留（驱动 `if done:` 只判非零；该双计数在 HEAD 早已存在且
无害，改它属引擎二进制协议面，非本卡所有权）。

## 附带：C 段判据契约修正（恒假断言）

`tests/test_string_graph_vs_lean.py` C 段判定行原为
`got is True and got == want`——对 `want=False` 的用例（es_str_false）恒假
（got=False 被 `is True` 拦死，got=True 被 `== want` 拦死），任何图输出都
FAIL；实测图判定 False 正确（lead repro 03:28 原文 `graph=False want=False`）。
内核依据：`try_string_lit_expansion` 命中臂时 true/false 都是终结 FINAL
（`K/type_checker.cpp:1145-1150, 1238-1239`）；真 lean 4.33.1 对同形输入
（B 段 `deq_oflist_false`）判 False，图一致 PASS。改为 `got is want`
（bool 恒等，既查值也查类型，False 用例同样严格）——修恒假式，非放宽。
完整证据链在 `docs/handoffs/001-A-wp5.md`。
