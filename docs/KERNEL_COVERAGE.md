# 内核覆盖清单

本文件是后续实现"内核缺失部分"的工作令。条目来自真内核源码
`/home/xkq/lean4/src/kernel/` 和本仓库实际代码。

---

## 1. 用途与验收标准

本清单用来指导把本仓库的 VM（`expr/tokens.py` 的编码层、`lean_vm/ref_vm.py` 的
解释器、`lean_vm/build_vm.py` 的 ALM 图）补齐到能够复现真 Lean 4 内核的判定
行为。**验收标准**：对同一输入（已 elaborated 的声明及其环境），本 VM 的判定与真
Lean 4 内核完全一致——包括接受/拒绝、拒绝时的错误类别、以及推断出的类型经真内核
`is_def_eq` 判定为相等。权重与图数值的接近程度只是编译期开发检查，不是验收。

约定：

- 真内核路径前缀 `K = /home/xkq/lean4/src/kernel/`；本仓库前缀
  `R = /home/xkq/Lean4-Transformer-Vm-OSS/`。
- 验收测试栏中 `D` 表示对真 `lean` 二进制的差分（现有机制见
  `R/reference/lean_ref.py`、`R/tests/test_ref_vs_lean.py`、
  `R/tests/test_stepgraph_vs_lean.py`），`Reg` 表示现有回归不破
  （`R/tests/test_ref_infer_defeq.py`、`R/tests/test_stepgraph_infer_defeq.py`、
  `R/tests/test_check_e2e.py`、`R/tests/test_mutation_reject.py`、
  `R/tests/test_olean_export.py`）。
- 现状只有三种：已实现 / 部分实现 / 缺失。`file:line` 均为真实位置；不确定处写 TBD。

---

## 2. 覆盖清单

### A. WHNF / infer / is_def_eq 主流程

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| A1 | `whnf` 主循环（`whnf_core` → `reduce_native`/`reduce_nat` → delta 循环） | `K/type_checker.cpp:736` | 部分实现（m_whnf 缓存层图侧臂已写入但 **DORMANT，ADR 019**：卡 014 P2 `T_WHNFCACHE=43` 默认关（`VM014_WMEMO=0`），交付图零条目、禁上验收路径；两机制定罪与重启出路见 ADR 019/VM_SPEC §18.4/§18.6；查询 :755-757/完成写回 :763/:766/:772 的合同映射保留于 dormant 码） | `R/lean_vm/ref_vm.py:127-284`（冻结参照）；`R/lean_vm/build_vm.py`（`whnf_cache`/`_wc_w` 臂） | WP7 | D+Reg（whnf 活性臂 `tests/test_defeq_cache_vs_lean.py` main_whnf 相位=研究 opt-in `VM014_ALLOW_P2=1` 专属，默认显式 SKIP） |
| A2 | `whnf_core`（无 delta、无 normalizer；`cheap_rec`/`cheap_proj` 两开关、缓存） | `K/type_checker.cpp:468` | 部分实现（无独立 core，无 cheap 两档，无缓存） | `R/lean_vm/ref_vm.py:127-284` | WP7 | D+Reg |
| A3 | `whnf_fvar`（zeta：local decl 有值则归约） | `K/type_checker.cpp:409` | 部分实现 | `R/lean_vm/ref_vm.py:250-263` | WP7 | D+Reg |
| A4 | `infer_fvar` | `K/type_checker.cpp:93` | 部分实现 | `R/lean_vm/ref_vm.py:448-452` | WP7 | D+Reg |
| A5 | `infer_lit`（Nat 尺寸检查；String 返回 String） | `K/type_checker.cpp:315` | 已实现（图侧 WP5+WP6：Nat→Nat、String→String；Nat 尺寸检查 = `rej_lit` 字面量位数 + `rej_o` 操作数位置位数；RefVM 冻结机仍无尺寸检查） | `R/lean_vm/ref_vm.py:457-458`（冻结参照）；`R/lean_vm/build_vm.py:4992,2439`（rej_lit/rej_o） | WP5/WP6 | D+Reg |
| A6 | `infer_constant`（lparams 数与 level 数校验、`instantiate_type_lparams`、`check_level`、unsafe/partial 检查） | `K/type_checker.cpp:101` | 部分实现（直接取编码时类型，无实例化/校验） | `R/lean_vm/ref_vm.py:453-456` | WP1/WP2/WP7 | D+Reg |
| A7 | `infer_lambda`（逐个 binder `ensure_sort`、`cheap_beta_reduce`、`mk_pi`） | `K/type_checker.cpp:125` | 部分实现 | `R/lean_vm/ref_vm.py:481-486` | WP7 | D+Reg |
| A8 | `infer_pi`（`mk_imax` 折叠、多 binder） | `K/type_checker.cpp:144` | 部分实现（imax 用整数近似） | `R/lean_vm/ref_vm.py:487-493` | WP2/WP7 | D+Reg |
| A9 | `infer_app`（`ensure_pi`、参数类型 `is_def_eq`、实例化 body；`eagerReduce` 特例） | `K/type_checker.cpp:173` | 部分实现（无 eagerReduce） | `R/lean_vm/ref_vm.py:461-480` | WP7 | D+Reg |
| A10 | `infer_proj`（单构造子结构、参数实例化、依赖字段用 `mk_proj` 回代、Prop 保护） | `K/type_checker.cpp:247` | 部分实现（monomorphic、非依赖、无参数结构） | `R/lean_vm/ref_vm.py:502-530` | WP1/WP8 | D+Reg |
| A11 | `infer_let`（`ensure_sort`、val 类型 defeq、`mk_pi ... true`） | `K/type_checker.cpp:208` | 部分实现 | `R/lean_vm/ref_vm.py:494-501` | WP7 | D+Reg |
| A12 | `check` / `ensure_sort` / `ensure_pi` / `is_prop` / `check_level` | `K/type_checker.cpp:62,74,85,364,383` | 部分实现（`ensure_sort`/`check`/`is_prop` 有；`check_level` 无） | `R/lean_vm/ref_vm.py:434-442,711-721,733-735` | WP7/WP2 | D+Reg |
| A13 | `quick_is_def_eq`（结构快判 + 成功缓存） | `K/type_checker.cpp:835` | 图侧已实现（结构快判+成功缓存查询 :834-836 对齐——卡 014 P1 `defeq_cache` 门遮蔽 deq_gate，VM_SPEC §18.3；RefVM 冻结机仍无缓存） | `R/lean_vm/ref_vm.py:601-621`（冻结参照）；`R/lean_vm/build_vm.py` | WP7 | D+Reg |
| A14 | reflection 分支（`t` 无 fvar 且 `s = Bool.true` → 全归约 `t`） | `K/type_checker.cpp:1181-1185` | 已实现（卡 007：`deq_refl` 门 + DE_RFL sink 单侧 soft-whnf 后按核判定 commit；commit-false 可靠性论证见 ADR-011 §2；`Bool.true` 走 ENV `_is_true`） | 差分 probe r1-r4（Meta 通道 + 核通道全对齐） | WP7 | D |
| A15 | `is_def_eq_core` 先 `whnf_core(..., cheap_proj=true)`（含 proj/proj 尝试 :1216-1227） | `K/type_checker.cpp:1194-1195` | 已实现（卡 007：proj/proj 非 commit 尝试 DE_PRJ sink + proj_diff 并入 deq_sw0 软 whnf 重 dispatch；cheap_proj 本体被 deq_fall whnf-both 吸收，判定中性） | 差分 probe j1-j5（True@21/75, False@75/75, True@15） | WP7 | D |
| A16 | `is_def_eq_proof_irrel` | `K/type_checker.cpp:932` | 部分实现 | `R/lean_vm/ref_vm.py:727-742` | WP7 | D+Reg |
| A17 | `lazy_delta_reduction` + `lazy_delta_reduction_step`（hints 比较、`try_unfold_proj_app`、`is_def_eq_args` 优化、失败缓存） | `K/type_checker.cpp:999,1088` | 已实现 hints+args 快路径（卡 007：`deq_hargs` 门读 ENV `T_ENV_DEFVAL.V1`==Regular + `ENV_HDR.V2` 有值 + 同 cid + level 链相等；peel 链非 commit 尝试 + DE_ATT sink，false 重推 deq_sw0）；`try_unfold_proj_app` 见 A30；失败缓存未实现（A27，纯性能） | 差分 probe h1-h4（meta 流 h1 63→27 步，判定全对齐） | WP7 | D |
| A18 | `is_def_eq_core` const 同名同级 | `K/type_checker.cpp:1209-1211` | 部分实现（只比 cid，不比 levels） | `R/lean_vm/ref_vm.py:608-609` | WP2/WP7 | D+Reg |
| A19 | `is_def_eq_core` fvar 同名 | `K/type_checker.cpp:1213-1214` | 部分实现（binder marker bid） | `R/lean_vm/ref_vm.py:640-642` | WP7 | D+Reg |
| A20 | `is_def_eq_core` proj 同 sname/idx → `lazy_delta_proj_reduction` | `K/type_checker.cpp:1216-1221,1123` | 部分实现（同 sname/idx 比 child；无 lazy proj delta） | `R/lean_vm/ref_vm.py:615-621` | WP7 | D+Reg |
| A21 | `is_def_eq_app` | `K/type_checker.cpp:911` | 部分实现 | `R/lean_vm/ref_vm.py:682-690` | WP7 | D+Reg |
| A22 | `try_eta_expansion_core/try_eta_expansion` | `K/type_checker.cpp:874` | 部分实现 | `R/lean_vm/ref_vm.py:744-769` | WP7 | D+Reg |
| A23 | `try_eta_struct_core/try_eta_struct`（非递归结构、参数+字段数、逐字段 proj） | `K/type_checker.cpp:889` | 部分实现（结构来自硬编码表） | `R/lean_vm/ref_vm.py:771-797` | WP1/WP8 | D+Reg |
| A24 | `try_string_lit_expansion` | `K/type_checker.cpp:1145-1156` | 已实现（WP5，卡 005：`build_vm.py:4194` 双向展开；差分 `test_string_graph_vs_lean` C 臂 3/3） | 无 | WP5 | D |
| A25 | `is_def_eq_unit_like` | `K/type_checker.cpp:1159` | 部分实现（硬编码单结构） | `R/lean_vm/ref_vm.py:799-816` | WP1/WP8 | D+Reg |
| A26 | `is_def_eq_offset`（Nat 字面量 / `succ` 的 offset 比较） | `K/type_checker.cpp:1076` | 已实现（卡 007：`deq_succ` 门 ENV `_is_succ` 驱动，succ/succ 尾调用参数对——核 :1080-1082  commit 子判定，尾调用忠实；zero/zero 由 deq_lit 承接 whnf 折叠） | 差分 probe o1-o3（True@37/27, False@16） | WP7 | D |
| A27 | 成功缓存 `succeeded_before`/`cache_success`、失败缓存 `failed_before`/`cache_failure` | `K/type_checker.cpp:941-977` | 缺失（仅结构位置相等） | 无 | WP7 | Reg（不影响判定，仅性能） |
| A28 | `is_delta` / `unfold_definition` / `unfold_definition_core`（含 level 实例化缓存） | `K/type_checker.cpp:555,565,589` | 部分实现（`is_delta` 未看 hints，无 level 缓存） | `R/lean_vm/ref_vm.py:152-156` | WP2/WP7 | D+Reg |
| A29 | `reduce_proj` / `reduce_proj_core`（构造子 + sname 校验 + 参数偏移） | `K/type_checker.cpp:420,444` | 部分实现 | `R/lean_vm/ref_vm.py:267-307` | WP1/WP8 | D+Reg |
| A30 | `try_unfold_proj_app` | `K/type_checker.cpp:983` | 已吸收（判定中性单边 whnf 快捷，declaration.h:33 + K:1005-1011；deq_fall whnf-both 同不动点，ADR-011 §4） | 差分 j5 True 双侧一致；A15 proj 组全对齐 | WP7 | D |

### B. recursor iota

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| B1 | `inductive_reduce_rec` 总入口 | `K/inductive.h:77` | 部分实现（仅 `Nat.rec` + 3 个 casesOn 特例） | `R/lean_vm/ref_vm.py:164-241` | WP3 | D+Reg |
| B2 | `get_rec_rule_for`（按 major 构造子名查 rule） | `K/inductive.cpp:114` | 部分实现（硬编码 rule 表） | `R/lean_vm/ref_vm.py:83-93` | WP1/WP3 | D+Reg |
| B3 | `major_idx` 计算（`nparams+nmotives+nminors+nindices`） | `K/declaration.h:382` | 部分实现（casesOn 硬编码 0；`Nat.rec` 硬编码 `pend[-4]`） | `R/lean_vm/ref_vm.py:169,190` | WP1/WP3 | D+Reg |
| B4 | `is_k` 标志 + `to_cnstr_when_K`（K 型数据转默认构造子） | `K/inductive.h:31-50` | 缺失 | 无 | WP1/WP3 | D |
| B5 | major 为 Nat 字面量（`nat_lit_to_constructor`） / String 字面量 | `K/inductive.h:94-97`；`K/inductive.cpp:1359,1368` | 部分实现（Nat 有，String 无） | `R/lean_vm/ref_vm.py:194-201` | WP3/WP5 | D+Reg |
| B6 | `to_cnstr_when_structure` / `expand_eta_struct` | `K/inductive.h:63`；`K/inductive.cpp:99` | 缺失 | 无 | WP1/WP3 | D |
| B7 | `nfields` 校验（`rule->get_nfields() > major_args.size()`） | `K/inductive.h:104` | 部分实现（nfields 来自硬编码表） | `R/lean_vm/ref_vm.py:83-93` | WP3 | D |
| B8 | params/motives/minors/fields/extras 套用顺序 | `K/inductive.h:107-119` | 部分实现（仅 Nat.rec/casesOn 的固定形状） | `R/lean_vm/ref_vm.py:178-183,214-238` | WP3 | D+Reg |
| B9 | 递归 rhs 重写（succ 规则里重发 recursor） | `K/inductive.h:106,120` | 部分实现（`Nat.rec` 手写 rhs） | `R/lean_vm/ref_vm.py:214-238` | WP3 | D+Reg |
| B10 | indices（有索引归纳的 major 构造子） | `K/declaration.h:379` | 缺失 | 无 | WP3 | D |
| B11 | nested / mutual（`all`、嵌套参数计数、辅助声明） | `K/declaration.h:302,305`；`K/inductive.h:109-112` | 缺失 | 无 | WP3 | D |
| B12 | 多 motive / 多 minor（mutual recursor） | `K/declaration.h:380-381` | 缺失 | 无 | WP3 | D |
| B13 | rhs 的 universe 实例化 `instantiate_lparams` + lparams 数校验 | `K/inductive.h:105-106` | 缺失 | 无 | WP2/WP3 | D |
| B14 | brecOn 族（below 展开 + `(go t F).1` 投影）经通用 iota + delta | 编译器生成辅助递归子（`src/Lean/Elab/PreDefinition/Structural/BRecOn.lean`，@[reducible] 库定义非内核 C++）；内核侧=普通 delta+iota+proj（`K/type_checker.cpp:503-508`）；内核 memo 层=`is_def_eq` 正缓存（:834-836/:1247-1252）+ whnf `m_whnf` memo（:753-757） | 已实现·全绿（图侧通用 iota + 忠实 delta-over-rec：B/C 组 11/11 例与 oracle 一致；软 INFER 脊=I_ARG_S 对齐 `K/type_checker.cpp:189-205`；原 G4_d6=KNOWN-GAP 已收口：卡 014 帽 1500 实测 d6 为**合法慢**（P1-only halt True@1070、=内核）非不收敛环，帽 720→1100 裁决后 d6 转绿，XPASS 规程摘除 G4_d6 条目（ADR 018 追记）。缓存层终态：**P1（is_def_eq 正缓存，T_DEFCACHE=41）交付有效**（VM_SPEC §18.3，全判定语料 OFF vs P1 不变性表零破线）；**P2（whnf memo，T_WHNFCACHE=43）DORMANT**——M6 三态 bisect 定罪两机制（空缓存假命中已修入共享底座；spine-walk 重派错标键需跨拍记忆=重新设计），回滚条款执行、移后续卡，证据与出路见 ADR 019） | `R/lean_vm/build_vm.py`（I_ARG_S=69 软脊；缓存臂 P1 交付 / P2 dormant `VM014_WMEMO=0`）；`tests/test_brec_drec_iota_vs_lean.py`、`tests/test_defeq_cache_vs_lean.py`、`scripts/probe_014_invariance.py` | 卡 009/014 | D `test_brec_drec_iota_vs_lean.py`（12/12 PASS，KNOWN_GAPS 空）；`test_defeq_cache_vs_lean.py --phase all`（P2 臂显式 skip=ADR 019） |

### C. quot

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| C1 | `quot_reduce_rec`（`Quot.lift` mk_pos=5/arg_pos=3，`Quot.ind` mk_pos=4/arg_pos=3；要求 `Quot.mk` 3 参数） | `K/quot.h:39-70` | 已实现（WP4） | `lean_vm/build_vm.py:1056-1103` + `:373,439,783`；语义记录 `docs/VM_SPEC.md` §13.8；`tests/test_quot_graph_vs_lean.py` 7/7 | WP4 | D |
| C2 | `quot_is_stuck`（同一位置常量） | `K/quot.h:76-95` | 已实现（WP4） | `lean_vm/build_vm.py:1056-1103` + `:373,439,783`；语义记录 `docs/VM_SPEC.md` §13.8；`tests/test_quot_graph_vs_lean.py` 7/7 | WP4 | D |
| C3 | `is_quot_initialized` / `add_quot`（Quot/Quot.mk/Quot.lift/Quot.ind 类型与 kind） | `K/environment.cpp:66`；`K/quot.cpp:47-104` | 已实现（WP4） | `lean_vm/build_vm.py:1056-1103` + `:373,439,783`；语义记录 `docs/VM_SPEC.md` §13.8；`tests/test_quot_graph_vs_lean.py` 7/7 | WP4 | D |
| C4 | `quot_val` / `quot_kind` 元数据 | `K/declaration.h:388-412` | 缺失 | 无 | WP1/WP4 | D |
| C5 | `reduce_recursor` 先调 `quot_reduce_rec` 再调 inductive | `K/type_checker.cpp:393-407` | 缺失（无 quot 分支） | 无 | WP4 | D |

### D. universe / level

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| D1 | `mk_max` 智能构造与归一化 | `K/level.cpp:81` | 缺失 | 无 | WP2 | D+Reg |
| D2 | `mk_imax` 智能构造 | `K/level.cpp:112` | 缺失 | 无 | WP2 | D+Reg |
| D3 | `operator==`（按 kind/hash/depth 结构相等） | `K/level.cpp:125` | 部分实现（数据类冻结结构相等，非内核语义） | `R/expr/model.py:92-118` | WP2 | D+Reg |
| D4 | `is_equivalent`（`lhs==rhs || normalize lhs==normalize rhs`） | `K/level.cpp:518` | 缺失 | 无 | WP2 | D |
| D5 | `normalize` | `K/level.cpp:454` | 缺失 | 无 | WP2 | D |
| D6 | `is_lt`（level 与 levels 两版） | `K/level.cpp:189,217` | 缺失 | 无 | WP2 | D |
| D7 | `is_geq` / `is_geq_core` | `K/level.cpp:523,542` | 缺失 | 无 | WP2 | D |
| D8 | `is_not_zero` / `normalizes_to_zero` | `K/level.cpp:160,174` | 缺失 | 无 | WP2 | D |
| D9 | `is_explicit` / `to_offset` / `to_explicit` | `K/level.cpp:54,67,76` | 缺失 | 无 | WP2 | D |
| D10 | `instantiate(level, params, levels)` | `K/level.cpp:317` | 缺失 | 无 | WP2 | D |
| D11 | `get_undef_param`（`check_level` 依赖） | `K/level.cpp:289` | 缺失 | 无 | WP2 | D |
| D12 | `lparams_to_levels` | `K/level.cpp:545` | 缺失 | 无 | WP2 | D |
| D13 | `instantiate_lparams`（expr 内替换常量 levels / sort） | `K/instantiate.cpp:232` | 缺失 | 无 | WP2 | D |
| D14 | `instantiate_type_lparams` / `instantiate_value_lparams` | `K/instantiate.cpp:248,256` | 缺失 | 无 | WP2 | D |

### E. 字符串字面量

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| E1 | `LitStr` 数据模型 | `K/expr.h`（Literal strVal，见 `R/expr/model.py:176-178`） | 已实现（WP5 收尾，2026-09-14） | `R/expr/tokens.py:160-227`（STR_ID_CODES/STRING_EXPAND_NAMES/utf8_codepoints/LitStr 编解码） | WP5 | string 30/30 |
| E2 | `string_lit_to_constructor`（UTF-8 解码为 `String.ofList`/`List.cons Char`/`Char.ofNat`） | `K/inductive.cpp:1368-1380` | 已实现（编码期影子展开树挂 K_LIT.X） | `R/lean_vm/build_vm.py:1059-1070`（iota 前转换+重入）；展开构造 `R/expr/tokens.py:217-227` | WP5 | string 30/30 |
| E3 | `try_string_lit_expansion`（与 `String.mk`/`String.ofList` 应用互比） | `K/type_checker.cpp:1145-1156` | 已实现（es_str 臂，true/false 均 FINAL，§14.8） | `R/lean_vm/build_vm.py:3166-3199` | WP5 | string C 段 3/3 |
| E4 | `infer_lit` 的 String 分支（`lit_type` 返回 `String`） | `K/type_checker.cpp:315-321` | 已实现（lit_i 臂 raw Const 投递；根 gate 恒二值修复 §14.8） | `R/lean_vm/build_vm.py:4739` | WP5 | string B 段 |
| E5 | `reduce_proj_core` 对 string lit 先转构造子 | `K/type_checker.cpp:421-422` | 已实现 | `R/lean_vm/build_vm.py:3404-3412`（WP5-E5 块） | WP5 | string proj 对 |

### F. reduce_nat 算子

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| F1 | `Nat.succ`（含尺寸检查） | `K/type_checker.cpp:702-713` | 已实现（WP6：结果尺寸检查 = 交付步转 X76 位数 strip 扫描，`D_r ≥ _T_DIG_CMP` 即拒 + 操作数字面量 `rej_o`） | `R/lean_vm/build_vm.py:2414-2426,2439`（X76/rej_q、rej_o）；语义 `docs/VM_SPEC.md` §15.3 | WP6 | reducenat A31/B16 |
| F2 | `Nat.add` / `Nat.sub` / `Nat.mul` | `K/type_checker.cpp:717-719` | 已实现（WP6：三算子交付步同走 X76 结果守卫；借位链修复 `done_bor=mx+1`；操作数 `rej_o`） | `R/lean_vm/build_vm.py:2414-2426,2439`；`R/tests/test_reducenat_graph_vs_lean.py` | WP6 | reducenat A31/B16 |
| F3 | `Nat.pow`（指数上限、结果尺寸估算） | `K/type_checker.cpp:720,660-675` | 已实现（WP6：X71-X75 帽检查先行 + 8·L(D)·k 乘积链 vs MAX 十进制 lex；`exp=0` 恒发数字修复） | `R/lean_vm/build_vm.py:2471-2551`（ph71-ph75）；`docs/VM_SPEC.md` §15.3 | WP6 | reducenat A31/B16 |
| F4 | `Nat.gcd` / `Nat.mod` / `Nat.div` | `K/type_checker.cpp:721-723` | 已实现（div/mod 含 a%0 约定；gcd = Stein 二进制版 X41-X57，零门 `gcd 0 n = n`） | `R/lean_vm/build_vm.py:2104`（wp6g_all）；`docs/VM_SPEC.md` §15.1 | WP6 | reducenat A31/B16 |
| F5 | `Nat.beq` / `Nat.ble` | `K/type_checker.cpp:724-725` | 已实现 | `R/lean_vm/ref_vm.py:361-366` | WP6 | D |
| F6 | `Nat.land` / `Nat.lor` / `Nat.xor` | `K/type_checker.cpp:726-728` | 已实现（WP6：相位 X21-X25，÷2 低→高 pass + ×2 pow2 累加，r 链长 max(n1,n2)+1；操作码 21-23 名字扫描） | `R/lean_vm/build_vm.py:2339-2363`（g21/ph22-ph25）；`R/expr/tokens.py:129`（NAT_OP_CODES）；`docs/VM_SPEC.md` §15 | WP6 | reducenat A31/B16 |
| F7 | `Nat.shiftLeft`（shift 上限、尺寸估算） | `K/type_checker.cpp:729,677-690` | 已实现（WP6：X61-X68——k>4294967295 帽拒、`v=0` 直收、`size(v)+⌊k/8⌋+1>MAX` 守卫（拒量 `k+64·L(D) ≥ 8·MAX`，带松弛已文档化）、×2 pass） | `R/lean_vm/build_vm.py:2312,2336`（rej_s、wp6s_all）；`docs/VM_SPEC.md` §15.2 | WP6 | reducenat A31/B16 |
| F8 | `Nat.shiftRight` | `K/type_checker.cpp:730` | 已实现（WP6：X31-X33 ÷2+dec(s) 轮，`a=0` 或 s 下溢停；巨大 s 不迭代；内核无尺寸检查） | `R/lean_vm/build_vm.py:2364-2366`（ph31-ph33 gates）；`docs/VM_SPEC.md` §15 | WP6 | reducenat A31/B16 |
| F9 | `LEAN_NAT_MAX_SIZE`（默认 128 MB）与指数/shift 的 32 位上限行为 | `K/type_checker.cpp:36,298-313,656,670-673,685-688` | 已实现（编译期烘焙 `_read_nat_size_env()` 复刻内核 read_nat_size_env，MAX/8·MAX/4294967295 只进数字表=数据；拒并入 reject code 1=ERR_TYPE；差分侧 `LEAN_NAT_MAX_SIZE=8` 同覆盖 build 与 oracle） | `R/lean_vm/build_vm.py:75-98,2179-2193,5742`；`docs/decisions/008-natmax-compile-bake.md` | WP6 | reducenat B 段 |

### G. 声明与环境检查

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| G1 | `check_constant_val`（check_name、dup univ、no metavar/fvar、`check(type)`、`ensure_sort`） | `K/environment.cpp:127-133` | 已实现（WP7：CHECK 通道 CK_G0/CK_G1 ensure_sort 链 + 根 fvar/mvar 门；深层 fvar/mvar 走 infer 通道既有 reject，类别记接缝） | `R/lean_vm/build_vm.py:5085-5103`；`docs/VM_SPEC.md` §16.2 | WP1/WP7 | D `test_defeq_branches_vs_lean.py` g0/g1/g1b |
| G2 | `add_definition`（unsafe 先加后查；else 查后加；value 类型 defeq 声明类型） | `K/environment.cpp:160-190` | **已实现（卡 010 G03 收口 unsafe 支）**：safe 支=WP7 value-infer+defeq 链 + G5/G10 门（`g2_def_mismatch`=declTypeMismatch 实测对齐）；unsafe 支=driver `InjectionEnv.add_definition(is_unsafe)` 两相（头检旧 env → 注册 → 体检新 env，mode 位随 E2 下行）+ 图侧 mode 臂（`inf_mode` 解码，`ck7_gate` 抑制 G10 抛门与 const 降级——降级共闸为实测必需，否则自引用落 delta 臂死循环）；已知缺口：mode 位跨 ST 续体交付不存活（APP 参数 / lam·let body 自引用假拒 7，XFAIL 登记） | `R/lean_vm/build_vm.py`（inf_mode/ck7_gate/9 处发射）、`R/lean_vm/step_driver.py`（InjectionEnv meta 表）、`R/expr/tokens.py:569-580`（use_reject 预算，未改）；`docs/VM_SPEC.md` §16.6 | WP7/卡010 | G `test_decl_injection_vs_lean.py` G03 节（selfref/later_ref/unsafe_ref 孪生/body_fail 回滚/mutual_xref + g03g/g03h XFAIL）；引擎 34/34（scratch 件） |
| G3 | `add_theorem`（额外 `is_prop(type)`，否则 `theorem_type_is_not_prop`） | `K/environment.cpp:192-209` | **已实现（卡 010 G02）**：声明 kind 经 `TASK_CHECK` 锚帧 E2 作为数据进入图（ENV_FORMAT §2.8，写侧 step_driver、读侧图常量），CK_G1 的 ok 支新臂 `kind=theorem ∧ 声明类型的类型的 level 根≠KL_ZERO → reject 8`；level 零测复用 PI 链 `pl_prop` 同一段测法（ADR 020 B：不另造第二套 level 判据）；臂序 = 核 `check_constant_val`(:200) 先于 `is_prop`(:201)，实测 `thm_typeexpected` 给 5 不给 8。非归一 level 形的分歧另记 G3a | `R/lean_vm/build_vm.py:5449-5473`（g3 臂）、`:5430`+`:5509-5511`（E2 载体路径）、`:6564-6568`（reject 链插 8）；`R/lean_vm/step_driver.py:28-58`（check_e2）、`:221-249`（run_check kinds 参数）；`docs/VM_SPEC.md` §16.4；`docs/decisions/020-injection-carrier-and-level-test.md` | WP7/卡010 | G `test_decl_injection_vs_lean.py` B/C/D 段（thm_true、thm_nat、thm_pi_type、thm_arrow、thm_sort、axm_nat、def_nat、opa_nat、def_true、thm_typeexpected、thm_dbl_nat、4 条 kind 链、gate_off_kind0、guard 载体件） |
| G3a | `is_prop` 的 level 判据在非归一形上的分歧：核 `normalizes_to_zero`（max 两边皆零、imax 只看 rhs）vs 图 syntactic 根比 KL_ZERO | `K/level.cpp:174-186`；`K/type_checker.cpp:383-389` | **具名缺口（卡 010 G02 实跑钉死，非推理入账）**：声明类型的类型为 `Sort (imax 1 0)` / `Sort (max 0 0)` 的 theorem，核 `#KDECL`=OK、图=假拒码 8；同类型同值的 kind=definition 对照双侧一致通过（证明分歧只在 is_prop 臂）。根因 = D1/D2（`mk_max`/`mk_imax` 智能构造缺失），修属卡 012。取证附注：源写的 `Sort (imax 1 0)` 会被前端归一（实测存储为 `Sort zero`），非归一形必须由 `Lean.addDecl` 注入 raw `Expr.sort` 才可达 | `R/tests/test_decl_injection_vs_lean.py:KNOWN_GAPS`（thm_imax/thm_max00，卡 009 XPASS 协议：修好仍留在册即 FAIL）；`docs/VM_SPEC.md` §16.4 表 | WP2(D1/D2)/卡012 | NOT-VERIFIED（"G3 与核在非归一 level 形上一致"这一条未实现；分歧本身已双向实跑取证） |
| G4 | `add_opaque` | `K/environment.cpp:211-223` | 已实现（检查序列与 safe add_definition 逐行相同 :211-223 vs :177-184，同通道覆盖；`g4_opaque_mismatch` 实测同类别 declTypeMismatch） | `R/lean_vm/build_vm.py:5105-5131`；`docs/VM_SPEC.md` §16.3 | WP7 | D `test_defeq_branches_vs_lean.py` g4 |
| G5 | `add_axiom` | `K/environment.cpp:152-158` | 已实现（WP7：锚 X==0=无 value 约定，CK_G1 后 ax_go/ax_done 推进/验收臂；`axiom : Nat → Nat` 实测 OK，旧 dummy-value 臂错判已钉死） | `R/lean_vm/build_vm.py:5105-5131,:5806`；`docs/decisions/012-wp7-g5-g10-gates.md` | WP7 | D `test_defeq_branches_vs_lean.py` g5×2 |
| G6 | `add_mutual`（相同 safety/lparams、块内重名校验） | `K/environment.cpp:225-269` | **已实现（卡 010 G06，driver 侧；图零改动）**：新 `InjectionEnv.add_mutual` 两阶段镜像核相位——wf 簿记（空块/全 safe 标签/同 safety/同 lparams/块内重名 found-set，:228-248）→ raise 码 9（`.other` 簿记族，消息原文逐字镜像，不进图）→ header 图检跑旧 env（X=0 锚形状，:236-251 先于 :253-257）→ 注册全员 → body 图检跑新 env（:259-267）→ 任一失败整块回滚（P2 实测：调用方 env 不变，oracle 侧成员引用=unknownConstant）。已知近似：partial 块 mode 位走 unsafe 值；核按成员交错簿记/header 而驱动先全员簿记（多缺陷块首错次序）；成员 unsafe/partial 标志 × G10 门 = G03 差分面 | `R/lean_vm/step_driver.py`（InjectionEnv + run_check check_mode 参数）；`docs/VM_SPEC.md` §16.5 | WP7/卡010 | G `test_decl_injection_vs_lean.py` G6 节（W：dup_name/safe_block/empty/mixed_safety/lparams 五行；V：crossref 正例/member_fail 回滚/later_ref/dispatch×2；oracle=`#KDECL` 的 `Declaration.mutualDefnDecl` 项，P1 探针定通道） |
| G7 | `check_no_metavar_no_fvar` | `K/environment.cpp:97-100` | 已实现（根位置近似，ck_kick 处 g7 门，先于 ensure_sort 链） | `R/lean_vm/build_vm.py:5071`（g7）；`docs/VM_SPEC.md` §16.2 | WP7 | D g7×4 |
| G8 | `check_name`（重名拒绝） | `K/environment.cpp:102-109` | 缺失（接缝：编码层 name→cid 唯一，token 流不可表达重名） | 无 | WP7 | D |
| G9 | `check_duplicated_univ_params` | `K/environment.cpp:111-125` | 缺失（接缝：核 O(n²) 链查重需新链扫描帧，属 WP2 后续） | 无 | WP2/WP7 | D |
| G10 | definition safety（unsafe / partial：`infer_constant` 拒绝 safe 上下文使用 unsafe/partial） | `K/declaration.h:96`；`K/type_checker.cpp:110-117`（全仓库唯一抛点） | 已实现（锚点 F2=use_reject 编码期预算，INFER const 臂 safety_i→bad 通道，reject_code=7；delta/whnf 不触门=内核一致；仅 meta 流有数据，legacy F2=0 自然关闭；4.33.1 实测 `partial def` 存 OpaqueInfo、partial 数据在 `_unsafe_rec` 影子） | `R/lean_vm/build_vm.py:5257-5269,:5341-5344,:6053`；`R/expr/tokens.py:548-558`；`docs/decisions/012-wp7-g5-g10-gates.md` | WP7 | D `test_defeq_branches_vs_lean.py` g10×4（meta_only） |
| G11 | reducibility hints 对 delta 的影响（hints 比较决定先展开哪一侧；相同 Regular 时走 `is_def_eq_args` 优化） | `K/declaration.h:35-54`；`K/type_checker.cpp:1026-1048` | 已实现（WP7 A17：DE_ATT=66 args 快路径 + T_ENV_DEFVAL.V1==2(Regular) ENV 提示门，h1 步数 meta<legacy 为证；一侧优先展开的序被 ADR-011 吸收论证） | `R/lean_vm/build_vm.py`（DE_ATT 区）；`docs/decisions/011-wp7-faithfulness-strategy.md`；`docs/VM_SPEC.md` §16.1 | WP7 | D h1-h4 双流 |

### H. 环境元数据编码

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| H1 | `constant_info_kind`（Axiom/Definition/Theorem/Opaque/Quot/Inductive/Constructor/Recursor） | `K/declaration.h:426` | 部分实现（`T_ENV` 的 flags 位定义存在，Encoder 未写入 kind；仅 Python 侧 `const_is_ctor`） | `R/expr/tokens.py:34,50-53,177` | WP1 | D+Reg |
| H2 | `lparams`（常量 universe 参数表） | `K/declaration.h:463` | 缺失（`univ_arity` 恒 0） | `R/expr/tokens.py:35,175,313-318` | WP1/WP2 | D+Reg |
| H3 | `inductive_val`（nparams/nindices/nnested/isRec/isReflexive/ctors/all） | `K/declaration.h:291-309` | 缺失 | 无 | WP1 | D |
| H4 | `constructor_val`（induct/cidx/nparams/nfields） | `K/declaration.h:319-332` | 缺失 | 无 | WP1 | D |
| H5 | `recursor_val`（nparams/nindices/nmotives/nminors/k/rules/all） | `K/declaration.h:365-386` | 缺失 | 无 | WP1 | D |
| H6 | `quot_val`（quot_kind） | `K/declaration.h:400-412` | 缺失 | 无 | WP1/WP4 | D |

### I. 图侧数据化

| 编号 | 功能 | 真内核位置 | 本仓库现状 | 本仓库位置 | 工作包 | 验收测试 |
|---|---|---|---|---|---|---|
| I1 | 用环境数据替换硬编码 cid | `K/declaration.h:426`（kind 决定字段） | 缺失 | `R/lean_vm/build_vm.py:83-115` | WP8 | D+Reg |
| I2 | 用环境数据替换结构字段布局 | `K/declaration.h:319-332` | 缺失 | `R/lean_vm/build_vm.py:2408-2553` | WP8 | D+Reg |
| I3 | 用环境数据替换 casesOn/recursor arity 与 major_idx | `K/declaration.h:365-386`；`K/inductive.h:77-121` | 缺失 | `R/lean_vm/ref_vm.py:83-93`；`R/lean_vm/build_vm.py:73-75,286-293,367-397,472-560,768-819,1182-1250` | WP8 | D+Reg |
| I4 | 用环境数据替换构造子顺序/索引 | `K/declaration.h:328` | 缺失 | `R/lean_vm/ref_vm.py:86,89,93` | WP8 | D+Reg |
| I5 | 用规则 rhs 替换 `Nat.rec` 手写 rhs 与固定 token 偏移 | `K/inductive.h:106,120` | 缺失 | `R/lean_vm/build_vm.py:1132-1180` | WP3/WP8 | D+Reg |

---

## 3. "检查证明时不需要"的部分

以下功能在**声明已经被前端 elaborated 并加入环境之后**、只做"检查已有声明的证明"
这一目标下不需要实现。验收输入是已 elaborated 的声明及其环境，声明本身（归纳类型、
构造子、recursor、Quot 常量）由真内核生成；本 VM 只从环境读取并消费这些元数据。

| 功能 | 真内核位置 | 理由 |
|---|---|---|
| 归纳声明的严格正性检查 | `K/inductive.cpp:436 check_positivity`（调用点 486-487） | 只在生成归纳声明时运行。已加入环境的归纳类型已通过该检查；检查证明时不会重新声明归纳类型。 |
| uniform occurrence 检查 | `K/inductive.cpp:134 check_uniform_ind_occs`（调用点 1248） | 同属声明生成期检查，与证明项判定无关。 |
| 构造子类型检查与注册 | `K/inductive.cpp:456 check_constructors`、`K/inductive.cpp:499 declare_constructors` | 生成期。证明检查只通过 `constructor_val`（nparams/nfields）读取已注册构造子。 |
| recursor 生成与生成结果自检 | `K/inductive.cpp:748 mk_rec_rules`、`K/inductive.cpp:795 declare_recursors`、`K/inductive.cpp:829 check_recursors` | 生成期。证明检查只需读取 `recursor_val` 的 rules 做 iota（WP3），不需要重新生成。 |
| Quot 常量初始化 | `K/quot.cpp:47 add_quot` | 初始化只在环境缺 Quot 时发生。证明检查只需 `is_quot_initialized` 为真后按 `quot_reduce_rec` 归约（WP4）。 |
| native_decide / `Lean.reduceNat`、`Lean.reduceBool` 的原生归约信任边界 | `K/type_checker.cpp:608-635 reduce_native`（`is_def_eq` 经 `lazy_delta_reduction` 在 1101-1104 调用） | 该路径把归约结果委托给原生编译代码，不是 token 流可复现的规则。若验收语料包含使用 `native_decide` 的证明项，其归约结果超出本 VM 覆盖范围。是否把这类证明纳入验收语料是 TBD，需在语料筛选阶段明确排除或标注为信任边界。 |

注意：上表"不需要"仅指**生成期/信任边界**功能。归纳类型的**消费**（iota、
`constructor_val`/`recursor_val` 元数据、`is_non_rec_structure` 判定）在范围之内，
见 B、H、I 组。

---

## 4. 工作包划分与依赖顺序

依赖主链：`WP1 → WP2 → WP3 → WP4/WP5/WP6/WP7 → WP8`。WP2 不依赖 WP1，可与 WP1
并行；WP4/WP5/WP6/WP7 都依赖 WP1、WP2、WP3。每个工作包的验收都包含两部分：
对真 `lean` 的差分（D）+ 现有回归不破（Reg）。

### WP1 环境元数据编码
- 目标：把 H 组全部元数据编码进 token 流，使 WP3-WP8 能只读环境数据工作。
  扩展 `T_ENV`/`T_ENV_META` 或新增 token kind，承载 `constant_info_kind`、
  `lparams`、`inductive_val`、`constructor_val`、`recursor_val`、`quot_val`。
- 涉及文件：`R/expr/tokens.py`、`R/expr/model.py`、`R/reference/olean_export.py`
  （`DUMP_TEMPLATE`/`usedOf`/kind 映射在 `R/reference/olean_export.py:50-146`）。
- 验收：导出含 inductive+constructor+recursor 的真 olean 环境，逐条与真 Lean API
  读出的元数据比对相等；`R/tests/test_olean_export.py` 不破。

### WP2 level 语义
- 目标：实现 D 组全部函数（智能构造、相等、归一化、等价、序关系、实例化、
  undefined param 检查），并在 `infer_constant`/`infer_pi`/defeq 中使用。
- 涉及文件：新增 `R/expr/` 下的 level 模块或扩展 `R/expr/model.py`；
  `R/lean_vm/ref_vm.py`、`R/lean_vm/build_vm.py`。
- 验收：对含 universe 形参、`max`/`imax`/`succ` 的声明，D 判定与真内核一致
  （含 `check_level` 的 `get_undef_param` 拒绝）；Reg 不破。
  TBD：仓库当前没有针对 `Level` API 的独立真 Lean oracle，差分载体需在实现时确定
  （建议扩展 `R/reference/lean_ref.py` 的 oracle 或直接对声明判定取结果）。

### WP3 通用 iota
- 目标：用环境里的 `recursor_val.rules` 实现 B 组全部行为（`major_idx`、k、
  Nat/String 字面量 major、结构 eta、nfields 校验、套用顺序、递归 rhs、indices、
  nested/mutual、多 motive/minor、universe 实例化），删除 `Nat.rec`/casesOn 手写分支。
- 涉及文件：`R/lean_vm/ref_vm.py`、`R/lean_vm/build_vm.py`、`R/expr/tokens.py`。
- 验收：对真 `lean` 编出的 `match`/`induction`/自定义 recursor/嵌套归纳用例，
  D 判定一致；现有 `Nat.rec`/casesOn 回归（`R/tests/test_ref_vs_lean.py`、
  `R/tests/test_stepgraph_vs_lean.py`）不破。

### WP4 quot
- 目标：实现 C 组（`quot_reduce_rec`、`is_quot_initialized`、`quot_val`），
  并接入 `reduce_recursor` 的调用顺序。
- 涉及文件：`R/lean_vm/ref_vm.py`、`R/lean_vm/build_vm.py`、WP1 的元数据编码。
- 验收：`Quot.lift`/`Quot.ind` 对 `Quot.mk` 的归约与真内核一致；D。

### WP5 字符串
- 目标：实现 E 组（`LitStr` 编码、`string_lit_to_constructor`、展开分支、
  `infer_lit` String、proj 对 string lit 的处理）。
- 涉及文件：`R/expr/tokens.py:271-272`、`R/expr/model.py`、`R/lean_vm/ref_vm.py`、
  `R/lean_vm/build_vm.py`。
- 验收：含字符串字面量的声明 D 一致；Reg 不破。

### WP6 reduce_nat 补齐
- 目标：补齐 F 组缺失算子与全部尺寸/指数/shift 上限行为（`LEAN_NAT_MAX_SIZE`）。
- 涉及文件：`R/expr/tokens.py:66-89`（`NAT_OPS`/`NAT_OP_ARITY`/`NAT_OP_CODES`）、
  `R/lean_vm/ref_vm.py:341-367`、`R/lean_vm/build_vm.py`。
- 验收：逐算子对真内核差分（含 gcd/land/lor/xor/shiftLeft/shiftRight 与超限拒绝）；
  Reg 不破。

### WP7 is_def_eq 剩余分支
- 目标：实现 A 组缺失/降级的判定分支：reflection、`cheap_proj` 两档 whnf、
  `lazy_delta_reduction`（含 hints）、`is_def_eq_offset`、`try_string_lit_expansion`
  接入（E3/WP5）、缓存（可选，仅性能），以及 G 组的声明/环境检查（G1-G11）。
  note：A18（const 同级）依赖 WP2。
- 涉及文件：`R/lean_vm/ref_vm.py`、`R/lean_vm/build_vm.py`、`R/expr/tokens.py`。
- 验收：对真 `lean` 的 proof-by-reflection/decide（reflection 分支）、投影与 delta
  交错、offset 字面量等用例 D 判定一致；G 组对真内核的错误类别一致（见下方 TBD）；
  Reg 不破。

### WP8 图侧数据化
- 目标：把第 5 节列出的全部硬编码常量替换为 WP1 环境数据驱动的运行期查表。
- 涉及文件：`R/lean_vm/build_vm.py:83-115`、`R/lean_vm/build_vm.py:2408-2553`、
  `R/lean_vm/ref_vm.py:60-93`。
- 验收：把环境常量顺序打乱（例如新增/重排常量）后，D 判定与 Reg 都不依赖旧 cid；
  对真 `lean` 差分一致。

---

## 5. 硬编码清单（WP8 输入）

以下常量元数据被写死在代码中，均须改为读环境数据。

### 5.1 `R/lean_vm/build_vm.py:68-136`

| 常量 | 值 | 含义 / 来源 |
|---|---|---|
| `OP_SUCC..OP_BLE` | 1..10 | nat op 码，对应 `R/expr/tokens.py:66-76` |
| `OP_REC` | 11 | `Nat.rec` dispatch（对应 `R/expr/tokens.py:80`） |
| `OP_CASESON` | 12 | `Nat.casesOn` dispatch |
| `OP_CASESON_P2` | 13 | `P2.casesOn` dispatch（3-entry spine，1 minor） |
| `OP_CASESON_BOOL` | 14 | `Bool.casesOn` dispatch（4-entry spine，2 个 0 字段 minor） |
| `CID_TRUE` | 2 | `Bool.true` |
| `CID_FALSE` | 3 | `Bool.false` |
| `CID_ZERO` | 4 | `Nat.zero` |
| `CID_NAT` | 0 | `Nat` |
| `CID_SUCC` | 5 | `Nat.succ` |
| `CID_PRED` | 6 | `Nat.pred`（iota succ 规则的 pred 技巧） |
| `CID_REC` | 27 | `Nat.rec` |
| `CID_P2MK` | 18 | `P2.mk`（2 字段、0 参数构造子） |
| `NID_P2` | 18 | 结构名 `P2` 的 name id |
| `CID_P2` | 17 | `P2`（结构类型） |
| `CID_UNITT` | 28 | `UnitT`（0 字段结构，unit_like） |
| `CID_CASESON_NAT` | 30 | `Nat.casesOn` |
| `CID_CASESON_P2` | 31 | `P2.casesOn` |
| `CID_CASESON_BOOL` | 32 | `Bool.casesOn` |
| continuation ids `I_FN..D_NCD` | `range(1,32)` | 图内部 continuation id，非内核元数据；WP8 不要求数据化，列出以免与 CID 混淆 |
| continuation ids `I_PROJ..UL_D` | `range(32,64)` | 同上 |

### 5.2 `R/lean_vm/build_vm.py:2408-2747`

| 位置 | 硬编码内容 |
|---|---|
| `:2410-2414` | 结构唯一为 `P2.mk`，0 参数、2 字段 |
| `:2425` | 结构 eta 的 ctor 判据 `Const(CID_P2MK)` |
| `:2434-2435` | 字段布局固定为 inner=field0、outer=field1 |
| `:2467` | 结构类型 `Const(CID_P2)`（不重新 infer） |
| `:2493-2495` | 投影 `Proj(NID_P2, 0, t)` |
| `:2526-2528` | 投影 `Proj(NID_P2, 1, t)` |
| `:2533` | 第二字段 idx 固定为 1 |
| `:2639-2643` | `infer_proj` 判据：child 类型必须是 `Const(CID_P2)`、sname 必须是 `NID_P2` |
| `:2658-2659` | 构造子类型根 = `ENV_HDR(CID_P2MK + 1).V1`（依赖 header 位置 = cid+1） |
| `:2694-2747` | unit_like 判据固定为 `Const(CID_UNITT)` |
| `:1132-1180` | `Nat.rec` 递归 rhs 的手写 token 形状与固定偏移 `frE2 + One*N` |

### 5.3 `R/lean_vm/ref_vm.py:60-93`

| 位置 | 硬编码内容 |
|---|---|
| `:65-69` | `Nat.zero`/`Nat.succ`/`Nat.rec`/`Bool.true`/`Bool.false` 的 cid 由名字取，运行期表 |
| `:83-86` | `Nat.casesOn`：`major_idx=0`，`[(Nat.zero,0),(Nat.succ,1)]` |
| `:87-89` | `P2.casesOn`：`major_idx=0`，`[(P2.mk,2)]` |
| `:90-93` | `Bool.casesOn`：`major_idx=0`，`[(Bool.false,0),(Bool.true,0)]`，构造子顺序 false 先于 true |
| `:190` | `Nat.rec` major 固定为 `pend[-4]`（应用序第 4 个） |
| `:83-93,164-241` | 全部 casesOn/rec 的 arity 与构造子顺序来自上述硬编码表，而非 `recursor_val.rules` |

### 5.4 `R/reference/toy_env.py`

| 位置 | 硬编码内容 |
|---|---|
| `:256-318` | `TOY_CONSTS` 顺序决定全部 cid：`Nat=0, Bool=1, Bool.true=2, Bool.false=3, Nat.zero=4, Nat.succ=5, Nat.pred=6, Nat.add=7, Nat.sub=8, Nat.mul=9, Nat.pow=10, Nat.div=11, Nat.mod=12, Nat.beq=13, Nat.ble=14, True=15, True.intro=16, P2=17, P2.mk=18, P2.fst=19, P2.snd=20, T_dbl=21, T_inc=22, T_two=23, T_four=24, T_ten=25, T_pair=26, Nat.rec=27, UnitT=28, UnitT.mk=29, Nat.casesOn=30, P2.casesOn=31, Bool.casesOn=32, Nat.below=33, Nat.brecOn=34`；`olean_export` 追加的常量从 35 开始 |
| `:320-321` | `TOY_CTORS` 集合 |
| `:721` | `TOY_STRUCTS = {"P2": ("P2.mk", 0, 2), "UnitT": ("UnitT.mk", 0, 0)}` |

---

## 6. TBD 列表

- **错误类别映射**：验收要求"拒绝时错误类别"一致，但真内核有多个异常类
   （`K/kernel_exception.h:25-155`，如 `type_expected_exception`、
  `function_expected_exception`、`invalid_proj_exception`、`def_type_mismatch_exception`、
  `already_declared_exception` 等），本仓库目前只有 4 个粗粒度码
  （`R/lean_vm/ref_vm.py:47-50`：`ERR_TYPE/ERR_MISSING_CONST/ERR_OVERFLOW/ERR_UNSUPPORTED`）。
  两者的对应表目前是 TBD，需先定义验收时比较的"错误类别"粒度。
- **native_decide 语料**：是否将使用 `native_decide`（`Lean.reduceNat`/`Lean.reduceBool`，
  `K/type_checker.cpp:608-635`）的证明纳入验收语料是 TBD；见第 3 节。
- **WP2 差分载体**：仓库当前无独立的 `Level` API 真 Lean oracle（见 WP2 验收）。
- **WP1 token 布局**：承载 `inductive_val`/`constructor_val`/`recursor_val`/`quot_val`
  的 token 具体布局是 TBD，由实现时按 `R/expr/tokens.py` 与 `VM_SPEC` 约定确定。
- **A27 缓存**：成功/失败缓存不影响判定结果，是否实现属性能取舍；若为对齐"完全一致"
  的判定语义可不实现，标为 TBD。
