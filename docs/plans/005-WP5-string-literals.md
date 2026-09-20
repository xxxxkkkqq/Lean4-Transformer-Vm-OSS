# 任务 005：WP5 字符串字面量（E 组）

状态：**完成（2026-09-14，A/A2 链交付，总控五道门 PASS）**。verifier 由总控独立重跑取证：string B 30/30 + C 3/3 对真 lean、quot 7/7、stepgraph_vs_refvm 37/37（proj_plain 恢复）、infer_defeq 84/84、引擎对拍 33/34（唯一失败 pow=卡 006 已知）。裁决与证据见 `docs/handoffs/001-2026-09-14-lead1.md`。
依赖：WP1、WP2、WP3、WP4 均已 landed。

## 已存在的半成品（先读，不要重做）

- `expr/tokens.py`：`STR_ID_CODES`(:168)、`STRING_EXPAND_NAMES`(:173)、`utf8_codepoints`(:182，Lean 宽容 UTF-8 解码，src/runtime/utf8.cpp:148-221)、字面量→`String.ofList` 展开(:217-227)、LitStr 编解码(:837-848、:952)。
- `lean_vm/build_vm.py`：`OP_OFLIST,OP_STRING=18,19`(:94)、扫描登记(:399,:440-441，注释声明故意无 legacy 回退)、投影前转构造子(:1059-1067,:3406)、`try_string_lit_expansion`(:3166-3184)。
- `tests/test_string_graph_vs_lean.py`：最小 env 55 常量、warm 18.9s；最后成绩 A 段 0 失败 / B 段 27/30 / C 段 0/3。
- 剩余缺口 = **6 例同一症状 `no halt after 600 steps`**：`B deq_oflist_true`、`B deq_oflist_false`、`B deq_proj_vs_oflist_true`、`C es_str_true`、`C es_str_false`、`C es_str_nultrue`。反方向 `deq_oflist_swap` 通过（548 步）→ 病灶在 arm 触发条件或展开后回边。
- 前代理调试现场（仍在盘上，可当线索不可当结论）：`/tmp/wp5_dbg_oflist.log`、`/tmp/wp5_equiv.log`、`/tmp/wp5_profile.log`、`/tmp/wp5_string_graph.log`。
- 主回归未倒退：改动前后 `test_stepgraph_infer_defeq` 均 84/84。

## 目标

让含 String 字面量的输入在图侧与真 Lean 4.33.1 判定一致：字面量能推断出类型 `String`、能按内核方式展开成构造子形式、能与 `String.mk`/`String.ofList` 应用互比、投影能穿过字面量；卡住情形也一致。

## 非目标

- 不做 Nat 字面量尺寸上限（`LEAN_NAT_MAX_SIZE`，属任务 006）。
- 不做 parser/elaborator（字符串必须已是 kernel 项）。
- 不动 `compiler/weights.py`、`model/runner.py`、`engine/*`。

## 涉及文件（触碰面）

`expr/tokens.py`、`expr/model.py`、`lean_vm/build_vm.py`、新 `tests/test_string_graph_vs_lean.py`、`docs/VM_SPEC.md`、`docs/ENV_FORMAT.md`、`docs/KERNEL_COVERAGE.md`（E 组状态行）。

## 权威依据

- E1 `LitStr` 数据模型：`/home/xkq/lean4/src/kernel/expr.h`（Literal strVal）；现状 `expr/tokens.py:271-272` 抛 `NotImplementedError`。
- E2 `string_lit_to_constructor`：`K/inductive.cpp:1368-1380`（UTF-8 解码成 `String.ofList` / `List.cons Char` / `Char.ofNat`，构造子选择必须照源码）。
- E3 `try_string_lit_expansion`：`K/type_checker.cpp:1145-1156`。
- E4 `infer_lit` 的 String 分支：`K/type_checker.cpp:315-321`。
- E5 `reduce_proj_core` 对 string lit 先转构造子：`K/type_checker.cpp:421-422`。

## 必须先回答的设计问题（写进 VM_SPEC 再动工）

字符串长 L 会展开成 O(L) 的 `List.cons`/`Char.ofNat` 树：字节放 ENV 区还是 STATE 逐 token 吐出？每字节消耗多少微步？UTF-8 解码用图原语怎么表达？答案与代价测算记进 ADR（格式变更属必写 ADR 的时机）。

## 机制规则

- 新增常量（`String.ofList`、`String.mk`、`Char.ofNat`、`List.cons`、`List.nil`）一律走名字扫描 + 元数据（`build_vm.py` 的 `_SCAN_OPS` 机制，legacy 回退照 `:285-330` 的 `_ctor_site`/`_no_meta` 写法）。禁止新硬编码 cid。
- `lean_vm/ref_vm.py` 冻结：不许长成第二套字符串实现；差分判据是真 lean。
- 差分测试用最小 env（写法照 `tests/test_quot_graph_vs_lean.py`）。

## Verifier 集（完工唯一依据）

- [ ] 新 `tests/test_string_graph_vs_lean.py` 全绿，必须含：E4 类型推断、E2+E3 `"ab"` vs 展开形式、E5 投影、stuck 一例、**至少一个非 ASCII 字面量**（真测 UTF-8 解码）；日志里要有 lean 侧证据。
- [ ] `test_stepgraph_infer_defeq` 84/84
- [ ] `test_datadriven_env` 32/32、`test_datadriven_bool` 12/12
- [ ] `test_level_vs_lean` 37/37
- [ ] `test_check_e2e` A 15/15 / B 15/15
- [ ] `test_quot_graph_vs_lean` 7/7
- [ ] 硬编码扫描零新增命中
- [ ] `python3 -u model/compile_vm.py --sparse model/step_vm_new_sparse` 成功，报告 dims/lookups 与峰值 RSS 增量（基线：16444 dims / 1915 lookups / 624MB）
- [ ] `scripts/verify_engine_vs_refvm.py` 保持 33/34（唯一已知失败 `pow`）

## 心跳预算

单次开发反馈 ≤1 分钟（最小 env）；全量差分 ≤30 分钟；预计 1-2 段会话。

## 决策引用

`docs/decisions/002`（编码期实例化，若字符串类型涉及多态需复用同一手法）；新建 ADR 记录 LitStr 编码方案。

## 完工后

更新 `docs/KERNEL_COVERAGE.md` E 组状态 + 本卡状态 + `docs/handoffs/001-*.md`。
