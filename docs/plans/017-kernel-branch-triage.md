# 任务 017：内核分支分诊——卡 012 M-C/M-D 之前的挡路裁定

状态：**分诊完成（语义设计师，2026-10-04）；审核修复完成（同日，改动点见
卡尾"审核修复记录"）**。只读代码 + oracle/图探针 +
本文件；未触碰 KERNEL_COVERAGE/VM_SPEC/代码/tests；未 git。
探针脚本与生成件全在 /tmp/017triage/（仓库外 scratch）。

## 结论（一段话）

**P0 = 2 个簇（合计 9 行）真实挡住 M-C/M-D，均已在交付图上实测复现判定分歧**：
① D1/D2/D3/D4/D5/D10 + A8/A18 组成的**符号 level 运行期通道缺口**（PG2：
带 `Type u` 域的 Pi 型声明在 CHECK 即拒 ERR 4，直接落在 D10 的运行期
instantiate/LEVEL 通道缺口；PG3/PG6：max 归一化 defeq 假拒
ERR 1——M-A 语料 288/779 常量带 univ 参数，`Type (max 1 u)` 形状遍地在）；
② A10 的**图侧 INFER-PROJ 仍是 P2 玩具硬编码**（VM_SPEC §11.6：类型必须
`Const(CID_P2)`，而语料 111 个 Proj 节点分布在 31 个带参结构上）。**P3 可
关账 8 行**（D6/D7/D9/D12/B11 + A7/A11 的 cheap_beta + C4），其余 32 行为
P1/P2（P1 8 行：A4/A9/A16/A20/B4/B6/B13/D14；P2 24 行，登记或随 M-C 差分
实测）。核心误判修正：B 组 B1-B3/B7-B10/B12 等
"部分实现"行反映的是冻结参照机，图侧经卡 009/015 已数据驱动，行状态过时。

## 背景与问题

内核覆盖矩阵（docs/KERNEL_COVERAGE.md §2，A-G 共 90 行：39 已实现 / 34 部分
实现 / 17 未实现或其他；行数口径=已实现 41 减去 A30"已吸收"与 G3a"已修复"
计入"其他"）。卡 012 的 M-C（≥20 例三通道差分）与 M-D（Mathlib 闭包 ENV
全套差分）是 Mathlib 端到端验收门。本卡把非全绿行逐行分诊，回答：

> 哪几行挡住 M-C/M-D（不做就可能判定不一致），哪几行只是深度/性能债？

范围注（审核修复补充）：本卡只分诊 A-G；H3-H6/I1-I5 不单列——A-G 之外的
消费侧等价物由 I2-I5 与 P0-2 覆盖，勘正归后续矩阵勘正。

载体口径：M-B 拍 1 裁定规模差分走**引擎通道**（同一张图编译的 sbin），
因此"交付物"= 图+引擎；`lean_vm/ref_vm.py` 是冻结参照机，矩阵若干行的
"硬编码"注记属参照机，不构成交付缺口（逐行注明）。

## 分级口径

- **P0** = 挡 Mathlib 端到端验收：不做 M-C/M-D 就可能（或已实测会）判定
  不一致 → 给后续卡建议（与既有登记项合并）。
- **P1** = 语料可能撞、风险不确定 → 给探针/实测计划（多数随 M-C 差分顺带
  裁定，不必先实现）。
- **P2** = 纯性能/完备性 → 登记限制（措辞见 P2 节）。
- **P3** = 检查证明不需要 → 引 docs/KERNEL_COVERAGE.md §3 关账。

## 分诊依据（三问）

1. **可达性**：判定入口 = 已 elaborated 声明的 check（DESIGN §3 口径 A；
   内核路径 addDecl → typeChecker.check/infer/is_def_eq/whnf）。行锚点在
   check 路径上有真实调用点才计可达；否则 P3（给出 grep 级调用面证据）。
2. **语料命中率**：M-A 三定理闭包实测画像（/home/xkq/logs/012I/closures/
   的 dump.jsonl，874 常量）+ 内核源码调用面 + oracle 探针（4.33.1 现跑）
   + 交付图探针（InjectionEnv + build_step_graph 现跑）。
3. **代价**：图侧触碰臂族与 per-node dims 量级（n2z 先例：D8 一条电路
   +8,369 dims / +1,588 lookups，系对 26,023 基线实测；现基线 34,671 dims /
   4,527 lookups，量级参考用）。

## 语料画像（分诊的实证底座，2026-10-04 实测）

三闭包 kind 分布：testBit {ind 50, ctor 61, def 337, rec 20, thm 306,
quot 3, axiom 2}=779；Vector3 {ind 11, def 37, ctor 13, rec 4, thm 21,
axiom 1}=87；Quot {ind 1, ctor 1, def 2, quot 3, thm 1}=8。

| 维度 | testBit | Vector3 | Quot | 分诊消费方 |
|---|---|---|---|---|
| univ 参数常量 | 288/779 (37%) | 50/87 (57.5%) | 8/8 | D 簇 P0-1 |
| 常量 level 实参 | 298,085 个：identity 171,633 / 裸 param 1,117 / zero 111,443 / **非平凡 13,892**（succ(0) 13,572、max(succ 0,u) 55、imax(u,v) 32…） | 2,874 个：非平凡 229 | 21 个：非平凡 0 | D 簇 P0-1、A18 |
| recursor | 20 个；**带索引 5**（Eq.rec/HEq.rec/Acc.rec/Nat.le.rec/Nat.le.below.rec）；multi-motive 0；isK=Eq.rec+HEq.rec | 4 个；带索引 3 | 0 | B4/B10/B12 |
| inductive | 50；nested 0；带索引 5；struct 33（np 1-3） | 11；nested 0；带索引 3 | 1 | B6/B11/A10 |
| 单构造子 inductive | 40/50 | 9/11 | 1/1 | B4/B6 候选池 |
| def hints | abbrev 234 / regular 103，safety 全 safe | 23/14 | 1/1 | A17/A28/G10（已实现，无新增缺口） |
| 表达式节点 | 697,190（mdata 6,596、proj 111/31 结构、nat_lit 20,728 最大 1e8、let 859、**str_lit 0**） | 8,306（proj 8、str_lit 0） | 329 | A10/E 组/C4 |
| 证明项内 recursor 应用 | Eq.rec 50、Nat.rec 17、Bool.rec 15、List.rec 13、PSigma.rec 9、Acc.rec 2… | Eq.rec 12、Nat.rec 4 | 0 | B 组 |
| rec major 形状 | bvar 中性 76（其中 **syntactic `a = a` 型 0**）、app 头 48（Eq.symm/funext/congrArg/Nat.add_succ/ctor…） | bvar 16（refl 型 0） | — | B4/B6 |

## 分诊总表（A-G 非全绿 49 行；A30/G3a 已收口不计）

Reach = check 路径可达性（Y=可达并有调用点；N=不可达）。"图"指交付图
（build_vm 编译图，引擎同权重）。

### A 组（WHNF / infer / is_def_eq 主流程，22 行非全绿）

| 行 | 内核锚 | Reach | 级 | 依据（一句话） |
|---|---|---|---|---|
| A1 whnf 主循环 | type_checker.cpp:736 | Y | P2 | 语义核（delta 循环）图侧已有；残余=m_whnf memo，P2 dormant（ADR 019），纯性能 |
| A2 whnf_core | :468 | Y | P2 | cheap 两档已吸收（:1194 cheap_rec=false；whnf_core_cheap 全树无调用点）；残余=缓存，纯性能 |
| A3 whnf_fvar(zeta) | :409 | Y | P2 | 图侧 let/marker 机制覆盖 toy 全绿；Mathlib let 859 节点待 M-C 实证，无已知缺支 |
| A4 infer_fvar | :93 | Y | P1 | RefVM 有；图= binder marker 近似；`test_iota_graph_vs_lean` 已登记 stuck_major_neg（对 recursor 应用做 INFER 抛 ERR 4）——proof_irrel 判 Prop 需要它，见 A16 |
| A5 infer_lit | :315 | — | （已实现，不分诊） | — |
| A6 infer_constant | :101 | Y | P2 | 残余=level arity 校验(:105-108)+check_level(:118-120→D11)：合法闭包不触发，仅 M-C 拒绝语料口径问题 |
| A7 infer_lambda | :125 | Y | P3 | 残余=cheap_beta_reduce(:140)——性能优化，跳过不改变判定（类型少归约一层，defeq 兜住） |
| A8 infer_pi | :144 | Y | **P0-1** | mk_imax 折叠(:163)吃 domain level；图 I_PIS1→LEVEL 任务对 Param 直接 ERR 4（PG2 实测 reject 4），Mathlib 多态 Pi 类型遍地此形 |
| A9 infer_app(eagerReduce) | :173 | Y | P1 | eagerReduce 特例(:178-183)缺；语料命中 1 处（Nat.mul_add_div._f 的 value，app 实参位）；m_eager_reduce 只放宽单个 defeq 的 fvar 门，well-typed 项常规路径应同样通过——M-C 会查该 def，若分歧再升级 |
| A10 infer_proj | :247 | Y | **P0-2** | 图 IP_PEEL 相位 0 硬编码 `Const(CID_P2)`/`NID_P2`（VM_SPEC §11.6），带参结构一律 ERR_TYPE；语料 111 个 Proj 节点分布在 31 个带参结构（Prod/PProd/HAdd…），INFER 走 value 必撞 |
| A11 infer_let | :208 | Y | P3 | 残余=cheap_beta_reduce(:228)，判定保持，同 A7 |
| A12 check/ensure_sort/is_prop/check_level | :62,74,85,364,383 | Y | P2 | 前四者图侧有（n2z 卡 015）；check_level 缺=D11（合法闭包不触发） |
| A13 quick_is_def_eq | :835 | — | （图侧已实现） | — |
| A16 is_def_eq_proof_irrel | :932 | Y | P1 | 图有 proof-irrel 链（:4585）+soft infer；但对"卡在 recursor 应用上的证明项"需 infer 其类型判 Prop——正是 stuck_major_neg 登记的 INFER 缺口，Mathlib 语料 76 个中性 major rec 应用是暴露面，M-C 差分实测裁定 |
| A17 lazy_delta+hints | :999,1088 | — | （已实现） | — |
| A18 const 同名同级 | :1209-1211 | Y | **P0-1** | 核对比 level（is_def_eq(levels)→is_equivalent）；图 _lvl_eq 只对 Zero/Param(名字)/Succ 递归，**Max/IMax 仅位置同一**（:3757 注释自认 sound-incomplete）；语料非平凡 level 实参 13,892 个 |
| A19 fvar 同名 | :1213 | Y | P2 | 核按 fvar user-name 相等（:1213）；图 binder marker 更严——同名不同 binder 假拒风险存在但需两次独立 infer 的同名 fvar 相遇，闭包为封闭项，风险低，登记 |
| A20 proj/proj lazy delta | :1216-1221,1123 | Y | P1 | A15 已做非 commit 尝试+deq_sw0；:1123 的 lazy unfold-under-proj 循环图侧无专臂；语料 111 个 Proj，`p.1 =?= q.1` 形待 M-C 实证 |
| A21 is_def_eq_app | :911 | Y | P2 | 图 spine 走已实现；"部分"细节未知具体缺口，M-C 回归覆盖 |
| A22 try_eta_expansion | :874 | Y | P2 | 核探针 ok4=OK（eta 接受）；图 M3 臂在（:4687）且回归绿；矩阵"部分"主要指参照机，M-C 兜底 |
| A23 try_eta_struct | :889 | Y | P2 | 图 Mechanism D（:4861）经 `_is_struct_ctor2`+元数据派生 inductive cid/nid，**非硬编码 P2**（"与结构 eta 同约定"的静态捷径是 ES_T 的 s_ty 省步路径）；矩阵"硬编码表"=参照机口径；M-C 兜底 |
| A25 is_def_eq_unit_like | :1159 | Y | P2 | 核探针 ok5=OK（PUnit.unit =?= 中性 x）；图硬编码 UnitT；**三闭包 0 个 0-field 结构、0 次调用**——当前语料不撞，登记（M-C 若加 PUnit 定理需先升级） |
| A27 成功/失败缓存 | :941-977 | Y | P2 | 纯性能（矩阵原文"不影响判定"）；A17 正缓存 P1 已交付，本行=ADR 019 同族 |
| A28 is_delta/unfold | :555,565,589 | Y | P2 | 残余=level 实例化缓存(:574-578)纯性能+level arity 门(:559)（编码期 arity 恒匹配，合法闭包不触发）；hints 比较在 A17 已做（矩阵注记"未看 hints"系过时——核 is_delta 本身不看 hints，hints 在 lazy_delta_reduction_step:1026） |
| A29 reduce_proj(_core) | :420,444 | Y | P2 | 图 I_PROJ 通用抽取卡 015 已按 reduce_proj_core 重做（K:420-441），矩阵"部分"=参照机口径；M-C 兜底 |

### B 组（recursor iota，13 行非全绿）

| 行 | 内核锚 | Reach | 级 | 依据 |
|---|---|---|---|---|
| B1 inductive_reduce_rec 总入口 | inductive.h:77 | Y | P2 | 图=通用 iota 数据驱动（卡 009，B/C 组 11/11）；行状态过时（"仅 Nat.rec+3 casesOn"=参照机）；残余集中在 B4/B6 两个转换门 |
| B2 get_rec_rule_for | inductive.cpp:114 | Y | P2 | 图按 T_ENV_RULE 链 ctor cid 匹配（I3），行过时 |
| B3 major_idx | declaration.h:382 | Y | P2 | 图按 RECVAL 计数算 np+nm+nmin+ni（I3），行过时 |
| B4 is_k + to_cnstr_when_K | inductive.h:31-50,:90-92 | Y | P1 | 核机制探针双确认（Eq.rec 中性 major ok2=OK；普通 K 型 Foo2.rec ok b4_foorec_K=OK；负控 b4_noK=MISMATCH）；图**封闭** major 已覆盖（Wproof axiom 用例绿，test_iota_graph_vs_lean），**开放（binder 内）major 未实现未测**（该测试文件自注"K conversion on a major that is an open term is not tested"）；语料 92 个中性 major 中 syntactic a=a 型 0 个，动态（whnf 后 a=a）无法静态排除→M-C 差分兜底 |
| B5 Nat/String 字面量 major | inductive.h:94-97; inductive.cpp:1359,1368 | Y | P2 | Nat 图侧有；String 图侧=编码期影子展开（WP5-E2）覆盖；三闭包 str_lit=0，登记 |
| B6 to_cnstr_when_structure / expand_eta_struct | inductive.h:63-74; inductive.cpp:99-112 | Y | P1 | 核探针 b6_pos=OK（Prod.rec 打中性 p 经 eta 展开归约）+b6_wrong=MISMATCH（负控）；图 fire 门对中性 major 一律 decline（无此转换）；语料暴露面=非 Prop 结构宿主的中性 major **12 处**（PSigma.rec 9、Prod.rec 1、ExprCnstr.rec 1、PolyCnstr.rec 1；And.rec 2 处 Prop 保护核同样 decline=无分歧），分歧是否显形取决于上下文是否需要该归约→M-C 实测裁定 |
| B7 nfields 校验 | inductive.h:104 | Y | P2 | 图按 T_ENV_RULE.V2（I3），行过时 |
| B8 套用顺序 | inductive.h:107-119 | Y | P2 | 图=§13.2 步 9 忠实实现（Pair2 用例），行过时 |
| B9 递归 rhs 重写 | inductive.h:106,120 | Y | P2 | 图=规则 rhs 预存直发（WTree 用例），行过时 |
| B10 indices | declaration.h:379 | Y | P2 | 图=计数通用（MyIdx 用例+§13.4"在切片内"）；语料 Eq.rec 62 处，refl-major 核探针 b10=OK；行过时 |
| B11 nested/mutual | declaration.h:302,305; inductive.h:109-112 | Y | P3 | v1 语料明确排除（VM_SPEC §13.4，须 stuck 不得错判）；**三闭包 nested=0/62**，互递归 recursor 0 个——M-C/M-D 按现口径不触 |
| B12 多 motive/minor | declaration.h:380-381 | Y | P2 | 图=计数通用（MA/MB 用例）；语料 multi-motive=0，行过时 |
| B13 rhs 的 universe 实例化 | inductive.h:106 | Y | P1 | 核在 iota 热路径 :106 对每条 rhs instantiate_lparams；图=编码期特化（§12.7）+rhs 原样重发，递归调用内的 level 实参保持 Param 形——level-blind 归约不受影响，风险=实例化差落进 zero-test（n2z(Param)=false vs n2z(0)=true）；卡 015 已修 accessor 活锁，余下此动态风险随 M-D 全量差分实测 |

### C 组（quot，2 行非全绿）

| 行 | 内核锚 | Reach | 级 | 依据 |
|---|---|---|---|---|
| C4 quot_val/quot_kind 元数据 | declaration.h:388-412 | N(检查期) | P3 | check 路径对 Quot 常量只按固定名查（quot_reduce_rec），quotKind 仅 add_quot 生成期消费（quot.cpp:47，§3 同类先例）；C1-C3 在真实 Quot 四件套上 7/7 绿 |
| C5 reduce_recursor 先 quot 后 inductive | type_checker.cpp:393-407 | Y | P2 | 图 OP_QUOT 臂在（:6022 fire 门）；核按名字分流、图按操作码分流，结果等价（Quot.lift/ind 不是 recursor，互斥命中）；行状态过时 |

### D 组（universe / level，12 行非全绿）——P0-1 主簇

| 行 | 内核锚 | Reach | 级 | 依据 |
|---|---|---|---|---|
| D1 mk_max | level.cpp:81 | Y | **P0-1** | 每 infer_pi/instantiate 都走；图 I_PIL2 只有 is_zero/is_not_zero 分支，explicit-absorption/同基 offset 比较全缺；**PG6 实测：连具体 `Type (max 1 1)` =?= `Type 1` 都假拒 ERR 1**（核 ok1 类形状=OK） |
| D2 mk_imax | level.cpp:112 | Y | **P0-1** | 同上，is_one(l1)→l2 与 l1==l2 吸收缺 |
| D3 operator== | level.cpp:125 | Y | **P0-1** | 图 _lvl_eq: Param 按名字 nid 相等✓、Zero✓、Succ✓、**Max/IMax 无分支**（仅位置同一）→跨位置同形即假拒 |
| D4 is_equivalent | level.cpp:518 | Y | **P0-1** | 调用点 type_checker.cpp:815（level defeq 唯一入口，quick Sort :844 与 const levels :1210 都到它）；核探针 ok1=OK（`Type (max 1 (succ u))` =?= `Type (succ u)` 经 normalize 接受）；图缺 normalize → PG3 假拒 ERR 1 |
| D5 normalize | level.cpp:454 | Y | **P0-1** | 经 D4 可达；ADR 022 曾否决"完整 D5 全序"——本卡建议**有界子集**（见 P0 卡建议），不做则 M-D 必假拒 |
| D6 is_lt | level.cpp:189,217 | N | P3 | grep 全 kernel/：除 level.cpp 内部（is_lt 自递归+levels 版 :217）外零调用点 |
| D7 is_geq/is_geq_core | level.cpp:523,542 | N(检查期) | P3 | 唯一 kernel 调用点 inductive.cpp:482 = check_positivity 族（声明生成期，§3 同类） |
| D9 is_explicit/to_offset/to_explicit | level.cpp:54,67,76 | N(独立) | P3 | 全部为 mk_max/instantiate/normalize/is_lt 的内部件（:82,:95-96,:345,:455,:483-499,:534）；不独立构成行为，随 D1/D4/D5 实现自然携带 |
| D10 instantiate(level) | level.cpp:317 | Y | **P0-1** | 类型侧编码期 E2 特化已覆盖单 use-site；**运行期通道缺**——PG2 实测：Pi 域 `Type u` 的 level 走到 LEVEL 任务即 ERR 4（图 level 通道=整数显式计数器，Param/Max/IMax 越界，build_vm.py LEVEL 段注释自认） |
| D11 get_undef_param | level.cpp:289 | Y | P2 | 调用点 type_checker.cpp:87（check_level，每次 infer_constant）；只在未绑定 level 参数时触发——合法闭包恒不触发，M-C 拒绝语料口径决策 |
| D12 lparams_to_levels | level.cpp:545 | N(检查期) | P3 | 调用点 inductive.cpp:138,255,998 全在声明生成（mk_rec/check_constructors 族，§3 同类） |
| D14 instantiate_value_lparams | instantiate.cpp:256 | Y | P1 | 核 delta 热路径 unfold_definition_core:577 每次多态 delta 都做；图 value 侧运行期实例化缺——level-blind 归约免疫，判据级风险同 B13（实例化差落进 zero-test/defeq），M-D 实测 |

### E / F / G 组

E1-E5、F1-F9、G1-G11+G3a 全绿，不在分诊范围。两条注记：
- E 组：三闭包 **str_lit=0**——M-C 若要覆盖 String 支路需另选定理
  （handoff 007 备选 `String.length_eq_list_length` 在案）。
- B15 残余债（VM_SPEC §16.7.2：`Nat.add <stuck> <lit>` rec 展开、
  `Nat.succ <无值 Const>` const_stuck 路径）维持卡 016 登记，P2。

## P0 清单与建议卡

### P0-1：符号 level 运行期通道（图侧）——行 D1/D2/D3/D4/D5 主干，A8/A18 消费点

**实测分歧（交付图 vs 4.33.1，均在核 0-5 现跑）**：

| 探针 | 内核 | 交付图 | 形状 |
|---|---|---|---|
| PG2 `def.{u} (x : Type u) : Type u := x` | OK（infer_pi 折叠 imax(param 系)） | **REJECT 4**（11 步，I_PIS1→LEVEL(Param) 越界） | 多态 Pi 类型 CHECK 即死 |
| PG3 `def.{u} : Type (max 1 (succ u)) := P.{u}`（P.{v} : Type v） | OK（normalize(max 1 (succ u))=succ u） | **REJECT 1**（11 步，deq_sort 无 Max 分支） | 假拒 declTypeMismatch |
| PG6 `def : Type (max 1 1) := (ax : Type 1)` | OK（mk_max explicit 吸收） | **REJECT 1**（10 步） | 连无参 max 都假拒 |
| PG1/PG4/PG5（identity param / 同形 sort / 裸 max 类型 axiom） | OK | ACCEPT | harness 自证有效 |

**为什么挡 M-C/M-D**：语料 288/779（37%）常量带 univ 参数（Vector3 57.5%、
Quot 100%），Mathlib 多态声明的类型=带 `Type u` 域的 Pi 链（PG2 形状），
CHECK 走 I_PIS1 即触；非平凡 level 实参 13,892 个（testBit）。M-D 全量差分
不可跑，M-C 的"声明检查支路"对任何多态声明不可用。引擎通道同权重，不豁免。

**建议卡（建议与卡 015 组件 2 NOT-VERIFIED、ADR 021、ADR 022 合并重开一卡，
暂名"level 运行期通道收口"）**，范围四件：
1. LEVEL 任务符号化：Param(名字 nid 恒等)/Succ 剥离/Max/IMax 智能构造按
   K/level.cpp:54-124（is_explicit 吸收、zero、同基 offset）——D1/D2/D9 内联；
2. I_PIS1/I_PIS2/I_PIL2/I_SORTEM 消费符号 level（消 PG2 的 ERR 4）；
3. _lvl_eq 补 Max/IMax **有界归一**等价（先 normalize-to-zero/one 判据
   （n2z 已有）+ canonical 形比较，不做 ADR 022 已否决的完整全序）——D3/D4/D5；
4. deq_sort/deq_const 的 level 链消费点全部换新通道——A18。
**代价量级**：n2z 先例 +8,369 dims/+1,588 lookups（系对 26,023 基线实测；
现基线 34,671/4,527，量级参考用）；
本通道为同级或略高（配对比较树 ×2），预估 +8k-18k dims / +2k-4k lookups，
需设计拍按 ADR 022 混合方案先出编码方案再定数。**验收探针即 PG2/PG3/PG6
转 ACCEPT + decl_injection 全语料零破线。**

### P0-2：图侧 INFER-PROJ 元数据化——行 A10

**证据**：VM_SPEC §11.6 原文——IP_PEEL 相位 0 "whnf 后类型必须是
`Const(CID_P2)` 且 proj sname 为 `NID_P2`，否则 reject ERR_TYPE"，相位 1
"剥 X 个 Pi（非依赖域，免实例化）"；build_vm.py:5966 自注"monomorphic
non-rec non-dependent subset — P2 only, build-time gated"。
**语料暴露面**：111 个 Proj 节点 / 31 个结构，全部带参（Prod np=2、PProd 2、
HAdd 3…），位于 thm/def 的 value 内（INFER 必遍历）；M-D 全量必撞，M-C 选例
避开 Proj 会废掉大半证明语料。
**建议卡**：IP_PEEL 换卡 015 I_PROJ 的同一套元数据读数（T_ENV_CTORVAL
np/nfields + INDVAL + ENV 元数据链），ctor 类型根走编码期实例化类型，
np 个 Pi 逐参 apply；依赖域回代（K:278-281 mk_proj）可先缓——语料被 Proj 的
结构需逐一核验无真字段依赖（本卡初扫的 Iff/LawfulBEq/EquivBEq/WellFoundedRelation
命中系把"引用参数"误计为依赖，WellFoundedRelation 单字段不可能依赖，需设计拍
用精确 min-bvar 判据复核）；Prop 保护(:274-290)接 n2z。**代价量级**：卡 016
三件套先例 +203 dims，本臂同量级（O(100) dims，复用既有 metadata 读数）；
验收=带参结构 proj 的 INFER 差分行集（对 oracle 现跑）。

### P0 落选说明（防误伤）

- B4/B6 不进 P0：机制核级确认存在、图侧缺口真实，但语料 syntactic 暴露面
  实测为 0/92（B4）与 12 处中性结构宿主 major 且显形依赖上下文（B6），
  定 P1 由 M-C 差分实测后决定是否立卡，避免为未知显形面预付图规模。
- A25/A9/B5/C4 同理：语料 0 命中或单点窄命中，登记不立卡。

## P1 清单与探针/实测计划（随 M-C/M-D 差分裁定，不先实现）

| 行 | 风险 | 实测计划 |
|---|---|---|
| A16/A4 | 卡在 recursor 应用上的证明项做 proof-irrel 判 Prop 需要 INFER 该应用（stuck_major_neg 已登记 ERR 4） | M-C 必含一例"同 Prop 的两个中性证明项比较"；若图 ERR 4/假拒 → 立卡补 soft-infer 的 recursor 应用分支 |
| A9 | eagerReduce 特例(:178-183)缺；语料命中 1 处（Nat.mul_add_div._f 的 value，app 实参位） | M-C 实测该声明（Nat.mul_add_div._f），分歧则升级 |
| B4 | 开放 major 的 K 转换（图未实现未测） | M-C 差分天然覆盖 76 处 bvar-major 位；另可做定向探针：major 类型经 whnf 变 a=a 的用例（静态扫描无 syntactic 命中，动态面未知） |
| B6 | 结构 eta 经 recursor（图 fire 门 decline 中性 major） | M-C 差分覆盖 12 处非 Prop 结构宿主中性 major（PSigma.rec×9 等）；任一显形 → 立卡（fire 门读 INDVAL is_non_rec + CTORVAL nfields + n2z Prop 保护，量级同 I_PROJ） |
| B13/D14 | iota rhs / delta value 的运行期 level 实例化缺 | M-D 全量差分为主判据；定向探针=同一多态 recursor 在两个不同 level 实例上归约后与核对拍 |
| A20 | proj/proj 的 lazy unfold-under-proj 循环 | M-C 加 `p.1 =?= q.1`（p/q 为需 delta 才见构造子的中性项）行 |

（总控裁决 2026-10-04：A23 维持总表 P2——图侧已元数据化、闭包 31 结构全带参不可触达、M-C 兜底行在总表行注；P1 清单表误收行删除，摘要 P1 计数 8 行 = A4/A9/A16/A20/B4/B6/B13/D14。）

## P2 登记限制清单（措辞照 README 限制清单 / VM_SPEC 残余段格式）

1. whnf/is_def_eq 缓存层（A1 P2 memo、A2 core 缓存、A27 成功/失败缓存、
   A28 level 实例化缓存）：不影响判定，仅步数/墙钟；P2 memo dormant 维持
   ADR 019，M-D 性能回归按实测帽执行。
2. check_level/get_undef_param（A6/A12/D11）与 const level arity 门（A6）：
   合法已 elaborated 闭包不触发；M-C 拒绝语料不含"未绑定 universe 参数"类。
3. eagerReduce 特例（A9）：m_eager_reduce 只影响单点 defeq 的 fvar 门；
   语料 1 处（Nat.mul_add_div._f），M-C 将实测该声明，分歧则升级。
   （2026-10-04 审核修复：A9 按卡自身 P1 定义改标 P1，本条留作其兜底措辞，
   同第 8 条 B13/D14 的先例。）
4. const level 实参比较的超接受面（A18 残余）：同名常量在非恒等、非 Param
   恒等的 level 实参差异上接受（核拒）——elaborated 闭包内部不产生该比较，
   仅影响 M-C 自造拒绝例的口径（语料设计避开）。
5. fvar 同名判定（A19）：核按 user-name 相等、图按 binder marker（更严）；
   封闭证明项不触发，登记为已知近似。
6. unit-like defeq（A25）：图侧仅玩具结构；Mathlib PUnit/Unit 形状未入
   M-C 语料前维持限制。
7. String 字面量 major（B5）：三定理闭包 0 字符串字面量；需 String 支路
   覆盖时换选定理并先过 WP5 影子展开对拍。
8. iota rhs / delta value 运行期 level 实例化（B13/D14，P1 观察项未显形时
   的兜底措辞）：level-blind 归约下数值行为不变，仅判据级 level 比较可能
   受影响，全量差分通过即视为已覆盖。
9. quot 分流序（C5）：图按操作码、核按名字分流，Quot 常量名固定，等价。
10. B15 残余债两条：维持 VM_SPEC §16.7.2 原登记（卡 016）。
11. mdata 不对称对（K_MDATA vs 裸节点）：图双 mdata 有专臂（:4013）、whnf
    剥壳（:1402）；不对称对经 soft-whnf 收敛——M-C 语料放一个 mdata 案例兜底
    （语料 6,596 个 mdata 节点，天然覆盖）。

## P3 关账清单（引 §3 口径，检查证明不需要）

| 行 | 关账依据 |
|---|---|
| D6 is_lt | kernel/ 全树 grep：仅 level.cpp 内部调用（is_lt 自递归 + levels 版 :217），check 路径零调用点 |
| D7 is_geq/is_geq_core | 唯一调用点 inductive.cpp:482，属 check_positivity 声明生成期检查（§3 "归纳声明的严格正性检查"同类） |
| D9 is_explicit/to_offset/to_explicit | mk_max/instantiate/normalize/is_lt 的内部件（:82,:95-96,:345,:455,:483-499,:534），不独立构成检查行为；P0-1 实现时自然内联 |
| D12 lparams_to_levels | 调用点 inductive.cpp:138,:255,:998，全部声明生成期（§3 "recursor 生成与自检"同类） |
| B11 nested/mutual | VM_SPEC §13.4 v1 语料排除（须 stuck 不得错判）；三闭包 nested=0/62、互递归 recursor=0，M-C/M-D 按现口径不触——**§13.4 排除条款保持有效** |
| A7/A11 cheap_beta_reduce | 性能优化（核注释自述"to reduce number of dependencies"），跳过仅使推断类型少归约一层，defeq 兜住，判定不变 |
| C4 quot_val/quot_kind | check 路径按固定名消费 Quot 常量（C1-C3 已在真实 Quot 上 7/7）；quotKind 元数据仅 add_quot 生成期（§3 "Quot 常量初始化"同类） |

已收口不计：A30（已吸收）、G3a（已修复）。

## 探针记录（oracle 现跑原文 + 图探针原文）

环境：判据 lean = `/home/xkq/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean`
（commit 819816b2e0a3bf405af45ae5c7af2491d8f5bee6）；oracle 通道
`reference/lean_ref.run_kcheck_oracle`（#KCHECK = 原核 type_checker 的
check+is_def_eq，VM_SPEC 12.5(D)）与 `run_kdecl_oracle`（#KDECL = 原核
addDecl）；生成件 /tmp/017triage/kc*.lean。图探针 = InjectionEnv + 树内
build_step_graph（in-tree），`OMP_NUM_THREADS=3 taskset -c 0-5`。

**2026-10-04 审核修复（出处重钉）**：下块中 B4/B6 相关 6 行（ok2_eqrec_K /
b4_noK / b6_pos / b6_wrong / b4_foorec_K / b10_eqrec_refl）的原出处
（/tmp/017triage/probe017.py 与 kc4-7.lean 的自研 #KC4/#KC5 通道）经审核
实测不可复现（ImportEnv 缺失；复跑另发现：probe017.py 报 NameError
InjectionEnv，kc4.lean 的 b6 motive 不合法无法 elabor，Eq.rec 行经
term-elab 被 elab_eq_rec 干扰、负控判别失效），该 6 行判定由下方
"oracle 复跑（审核修复）"节重钉，本块对应行仅存档。

### oracle（4.33.1 现跑，期望全由现跑产生）

```
== run_kcheck_oracle / run_kdecl_oracle（2026-10-04）==
  ok1_lvl_norm   OK                  # defnDecl type=Sort(max 1 (succ u)) value=ppgP.{u}
                                     # （axiom ppgP.{v} : Type v）——核 normalize 接受
  ok2_eqrec_K    OK                  # Eq.rec（motive:=fun b _=>Nat）Nat.zero h，
                                     # h : n = n 中性——核 K 转换后归约 = Nat.zero
  ok5_unitlike   OK                  # ∀ x : PUnit.{1}, PUnit.unit.{1} = x（非 Prop 路径）
  b6_pos         OK                  # @Prod.rec Nat Nat (fun _=>Nat) (fun a b=>a) p = Prod.fst p，
                                     # p 中性——核 to_cnstr_when_structure eta 展开后归约
  b6_wrong       declTypeMismatch    # 负控（minor 改取 b）：核拒
  b4_noK         declTypeMismatch    # 负控（h : n = m）：核不转换、目标不可证
  b4_foorec_K    OK                  # inductive Foo2 | mk；@Foo2.rec (fun _=>Nat) Nat.zero h
                                     # （h : Foo2 中性）——普通 K 型 recursor 同机制
  c_sanity OK / c_bad declTypeMismatch  # 通道自检（坏例必须拒，实拒）
  b10_eqrec_refl OK                  # Eq.rec major=Eq.refl a（带索引）归约 = Nat.zero
  a22_eta        OK                  # (fun x => f x) = f（kc6/kc7 干净行）
```

（附注：ok2/b4_noK 的 tyE 若用 `@Eq.rec α a motive minor b h` 全显式 @-应用
会被核的 elab_eq_rec 消除器重排实参（kcshow.lean 实测 `m ▸ Nat.zero` 形），
探针一律改命名实参语法绕开；rfl 因留 mvar 不可用（declHasMVars），值一律
全显式 `@Eq.refl`。）（2026-10-04 复跑修正：经 term-elab 的 Eq.rec 探针即
使命名实参也不可靠——审核实测旧文件负控亦被接受；Eq.rec 行一律改 raw
#KDECL，见下节。）

### oracle 复跑（审核修复 2026-10-04，期望全由现跑产生）

通道与脚本：per-case `reference.lean_ref.run_kcheck_oracle`（kcheck 行）与
`run_kdecl_oracle`（raw-Expr #KDECL 行），判据 lean 同上（4.33.1）；
脚本 /tmp/017triage/rep017_rows.py（仓库外 scratch，构造式要点抄录于本节末，
/tmp 易失可据此重建），`OMP_NUM_THREADS=3 taskset -c 8-13` 现跑，连跑两次
输出一致。

```
== 复跑输出原文（2026-10-04）==
== raw-Expr #KDECL (run_kdecl_oracle, per case) ==
  r_sanity         OK
  r_neg            declTypeMismatch
  ok2_eqrec_K      OK
  b4_noK           declTypeMismatch
  b10_eqrec_refl   OK
== per-case run_kcheck_oracle ==
  b4_foorec_K      OK
  b6_pos           OK
  b6_wrong         declTypeMismatch
```

六行与原判定逐一对应：ok2_eqrec_K OK、b4_noK declTypeMismatch、b6_pos OK、
b6_wrong declTypeMismatch、b4_foorec_K OK、b10_eqrec_refl OK——全部复现。

通道要点（复跑中实测；脚本构造照此重建）：
- **Eq.rec 三行（ok2_eqrec_K / b4_noK / b10_eqrec_refl）必须走 raw-Expr
  #KDECL**，绕开 term elaborator：rfl/裸 `Eq.refl` 留 implicit/binder-type
  mvar → declHasMVars；@-全显式会被 elab_eq_rec 重排。raw 声明用
  `.defnDecl { name := …, levelParams := [], type := …, value := …,
  hints := Lean.ReducibilityHints.regular 0, safety := Lean.DefinitionSafety.safe }`
  （无 `all` 字段，实测可 elabor）。Const levels（α=Nat : Sort 1）：
  `Eq`/`Eq.refl` 取 `[succ 0]`，`Eq.rec.{u, u_1}` 取 `[succ 0, succ 0]`
  （motive 与 α 均 Sort 1）；`@Eq.rec` 实参序 α, a, motive, minor, b, h；
  motive = `fun (b : Nat) (_ : <a> = b) => Nat`（de Bruijn：motive 内
  `_h` 的绑定类型里 a 随两层 lam 位移 +1）。值侧三行分别是
  `fun n h => @Eq.refl Nat Nat.zero` / `fun n m h => @Eq.refl Nat Nat.zero` /
  `fun a => @Eq.refl Nat Nat.zero`（type 侧 h 的绑定类型分别为
  `@Eq Nat n n`、`@Eq Nat n m`，b10 的 major 为 `@Eq.refl Nat a`）。
  通道自检：r_sanity（`@Eq.refl Nat 0`：`@Eq Nat 0 0`）OK /
  r_neg（`@Eq Nat 0 (Nat.succ 0)`）declTypeMismatch。
- **kcheck 三行（b4_foorec_K / b6_pos / b6_wrong）**：值侧 lambda 绑定必须
  带类型标注（无标注的 `fun h => …` 独立 elabor 留 binder-type mvar →
  declHasMVars）。b4_foorec_K 的 Foo2 在 DEFS 内以 Lean 源声明
  （`inductive Foo2 where | mk : Foo2`），探针形
  `∀ (h : Foo2), @Eq Nat (@Foo2.rec (fun _ => Nat) Nat.zero h) Nat.zero` ⊢
  `fun (h : Foo2) => @Eq.refl Nat Nat.zero`。b6 形
  `∀ (p : Nat × Nat), @Eq Nat (@Prod.rec Nat Nat (fun _ => Nat) (fun (a :
  Nat) (b : Nat) => a) p) (Prod.fst p)` ⊢
  `fun (p : Nat × Nat) => @Eq.refl Nat (Prod.fst p)`（b6_wrong 的 minor 改
  取 `b`）；motive 为 `fun _ => Nat`——kc4.lean 存档件的 motive
  `fun (a : Nat) => (b : Nat) → Nat` 不合法 elabor（Prod.rec 的 motive 域
  是 Nat × Nat），系其不可复现的直接原因之一。

### 图探针（InjectionEnv + build_step_graph，toy 基座 + 注入声明）

```
== graph probes（2026-10-04，核 0-5）==
  PG1  ACCEPT  steps=36   # axiom pgA.{u} : Type u; def pgB.{u} : Type u := pgA.{u}
  PG2  REJECT  code=4     # def pgC.{u} (x : Type u) : Type u := x
                          #   detail=VM reject 4: step graph reject steps=11
  PG3  REJECT  code=1     # def pgD.{u} : Type (max 1 (succ u)) := pgP.{u}
                          #   （axiom pgP.{v} : Type v）detail=VM reject 1 steps=11
  PG4  ACCEPT  steps=36   # sanity：双侧 Sort (succ u)
  PG5  ACCEPT  steps=35   # axiom : Sort (max 1 (succ u))（裸类型，不折叠）
  PG6  REJECT  code=1     # def pgH : Type (max 1 1) := (ax : Type 1)  steps=10
```

### 语料画像脚本

/tmp/017triage/{analyze_closures,scan_rec_majors,scan_app_majors,scan_structs,
scan_b4_candidates}.py（只读 dump.jsonl，本卡"语料画像"表数字的出处）。

## 遗留与移交

1. P0-1/P0-2 建议卡需总控裁决立卡与排产（P0-1 设计拍须先出编码方案 +
   ADR，预估 dims 才能定稿）。
2. 矩阵若干行状态过时（B1-B3/B7-B10/B12、A22/A23/A29、C5 的"部分/硬编码"
   系参照机口径，图侧已数据驱动/元数据化）——本卡不代改
   KERNEL_COVERAGE.md，建议总控在下一次矩阵勘正（卡 015 后勘正 13 行的同款
   事实性更新）采纳本卡"分诊总表"的行注。
3. M-C 语料设计输入：错误类别面按 P2 第 2/4 条口径裁剪；String 支路需换选
   定理；mdata/proj/record-eta/中性证明项比较四类行必放。

## 审核修复记录（2026-10-04）

按审核工程师可执行指令修复本卡（审核结论 FAIL，FAIL 点全部在文字层；
实体结论经独立复核证实为真）。改动点：

1. **摘要段计数对齐分诊表（必改①）**：P0 改为 2 簇合计 9 行（① D1/D2/
   D3/D4/D5/D10 + A8/A18；② A10），D10（PG2 ERR 4 的关键解释行）补进摘要
   列举并点明其与 PG2 的因果；P3 改为可关账 8 行（原列表即 8 行而计数写
   7）；其余 32 行 P1/P2（P1 8 行、P2 24 行；9+8+32=49 与总表行数闭合）。
   指令原文的 P1 列表含 A23（A4/A16/A20/A23/B4/B6/B13/D14）；因 A23 在
   分诊总表的现行标注为 P2（不在本次授权修复面内），且指令③将 A9 改标
   P1，摘要 P1 列表按修复后全表实况取 A4/A9/A16/A20/B4/B6/B13/D14。
   A23 的总表标注（P2）与 P1 清单表收录的既有不一致未动，留待总控/
   矩阵勘正裁决。
2. **B4/B6 六行 oracle 出处重钉（必改②）**：原出处 /tmp/017triage/
   probe017.py 与 kc4-7.lean（自研 #KC4/#KC5 通道）经审核实测不可复现，
   本卡不复引。六行经可用通道复跑全部复现原判定（Eq.rec 三行 ok2_eqrec_K/
   b4_noK/b10_eqrec_refl 走 raw-Expr #KDECL，b4_foorec_K/b6_pos/b6_wrong
   走 per-case run_kcheck_oracle），输出原文与构造式要点见
   "oracle 复跑（审核修复 2026-10-04）"节；未伪造、未降级。复跑中发现的
   通道陷阱（rfl/裸 Eq.refl 与无标注 binder 留 mvar、kc4.lean 的 b6 motive
   不合法 elabor、raw 声明缺 `.defnDecl` 前缀即败）一并记录在该节。
3. **顺带项（非阻塞）**：① A9 按卡自身 P1 定义改标 P1（分诊总表行改级 +
   P1 清单新增 A9 行 + P2 清单第 3 条标注留作兜底措辞）；② 卡头
   （背景与问题）补 H3-H6/I1-I5 排除说明一行；③ 两处 dims 预估（分诊依据
   第 3 条、P0-1 建议卡代价段）补注 n2z +8,369 系对 26,023 基线实测
   （现基线 34,671，量级参考用）。

其余结论未动。复跑脚本 /tmp/017triage/rep017_rows.py（仓库外 scratch，
/tmp 易失；构造式要点已抄录进复跑节，可按其重建）。探针限核 8-13，
未触碰 git、KERNEL_COVERAGE/VM_SPEC/代码/tests。
