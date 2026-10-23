# 任务 018：符号 level 运行期通道（P0-1 设计拍 + 拍 B 实现卡）

状态：**CLOSED（2026-10-13，总控收口）**。拍 A 设计 + ADR 025（10-04/05，
复核 PASS 带四条修正）；拍 B=B1+B2+B3：B1=054407f，B2 图侧实现随
054407f 入树、B2.R1-R6 由 2026-10-12 总控续接收口，B3 收口跑全绿
（"B3 复跑账目"逐项原文）；独立复核两轮：首轮五门 gate1-4 PASS、
gate5 FAIL（§7 链臂错标）→ 修复（`lvl_cc` 真分行 + deq_hargs NOT-VERIFIED
登记 + minor 全清）→ 复核 **gate5 PASS、接受 CLOSED**（85497c4 +
后续清扫提交）。23 套件全量 NOT-RUN 留里程碑出口。设计拍完成于
2026-10-04/05。本卡由
卡 017 P0-1 建议立卡；设计拍只读代码 + oracle/图探针 + 写本卡与 ADR 025
草案，未触碰代码/tests/其他文档，未 git。探针脚本与生成件全在
/tmp/018design/（仓库外 scratch，/tmp 易失；重建要点已抄录 §5）。
**设计产出须过一段干净上下文的独立复核（AGENTS §七）后才可派拍 B。**

## 0. 执行计划（设计拍，开工即落，随做随勾）

| # | 步骤 | 产物/落点 | 状态 |
|---|---|---|---|
| P1 | 读齐设计输入：卡 017 P0-1 节、卡 015（组件 2 NOT-VERIFIED）、ADR 021、ADR 022、K/level.cpp 全文、K/type_checker.cpp 锚段、图侧锚（LEVEL dispatch / _lvl_eq / _n2z / I_PIS1/I_PIS2/I_PIL2/I_SORTEM / deq_sort/deq_const/deq_hargs / pl_prop/G3）、VM_SPEC §12 | 本卡 §2 | done |
| P2 | 问题 1（表示）：符号 level 的图内承载方案，候选 ≥2 含被拒案 | 本卡 §3.1 + ADR 025 | done |
| P3 | 问题 2（操作面）：n2z 复用面 / canonical 比较 / infer_pi 折叠 / instantiate 时机，每个操作给图侧实现形状 | 本卡 §3.2-§3.4 + ADR 025 | done |
| P4 | 图基线 dims/lookups 复测（只读 build_step_graph，不编译不落盘）+ 候选电路原型计量（/tmp 微图，仓库外） | 本卡 §4/§5.2 | done |
| P5 | 问题 5（oracle 探针）：拿不准的核侧行为 4.33.1 现跑定案，原文进 §5.1/ADR 025 | 本卡 §5.1 + ADR 025 | done |
| P6 | 问题 3（dims 预算）：per-node 成本 × 操作数，总数 + 置信区间，对照 n2z cap8 实测 4,084/单电路（自定参照，非 ADR 022 原文） | 本卡 §4 | done |
| P7 | 问题 4（拍次划分）：拍 B 实现拆步 + 依赖序 + 每步验收探针 | 本卡 §6 | done |
| P8 | ADR 025 草案落盘（含被拒方案与 015/021/022 合并关系） | docs/decisions/025-symbolic-level-runtime-channel.md | done |

设计拍完成判据：P2-P8 全勾 + ADR 025 草案在库。拍 B（图逻辑工程师）待总控
排产，本卡 §6 为其拆步与验收依据。

## 1. 目标与范围（承卡 017 P0-1，四件不变）

PG2/PG3/PG6 三条实测分歧（卡 017"P0-1 节"）转 ACCEPT；A18/deq 链消费点换
通道。四件：
1. LEVEL 任务符号化：Param(nid 恒等)/Succ 剥离/Max/IMax 智能构造按
   K/level.cpp:54-124（D1/D2/D9 内联）。
2. I_PIS1/I_PIS2/I_PIL2/I_SORTEM 消费符号 level（消 PG2 的 ERR 4）。
3. _lvl_eq 补 Max/IMax 有界归一等价：n2z 判据（卡 015 D8 已有）+ 有界
   canonical 形比较；不做 ADR 022 已否决的完整 D5 全序/is_norm_lt 全序。
4. deq_sort/deq_const（含 A17 hints 链 deq_hargs）level 链消费点全部换新
   通道（A18，含卡 015 组件 2 NOT-VERIFIED 的清偿）。

**非目标（沿用 017/022 口径）**：D6/D7/D12（P3 关账）；B13/D14 运行期
level 实例化（P1，M-D 差分裁定，见 §3.2 末条）；D11（P2）；引擎侧零改动
（同权重编译自然携带）；不动 ref_vm.py。

## 2. 设计输入核对（P1）

- 核侧合同（复核扩展，与卡 017 钉的一致）：level.cpp:54-79（D9 三件）、
  :81-104（D1 mk_max 六规则）、:106-123（D2 mk_imax 五规则 + is_one 语义）、
  :125-150（D3 结构相等）、:160-172（is_not_zero）、:174-186（n2z）、
  :189-226（D6，P3 不做）、:289-299（D11，P2 不做）、:317-340（D10
  instantiate，重建时 update_max 重跑智能构造 :301-315）、:395-418（is_norm_lt，
  **Param 比的是 interned level_id**（10-13 勘误，非字典序）——图 nid 是整数值不可复现，canonical 方案
  必须绕开排序，见 §3.2）、:454-516（D5 normalize）、:518-521（D4）、
  :523-544（D7，P3 不做）；type_checker.cpp:144-166（infer_pi 折叠）、
  :383-389（is_prop→n2z）、:814-820（level defeq 唯一入口=is_equivalent）、
  :843-844（quick Sort）、:1209-1211（const levels）。
- 图侧现状锚（本拍逐一读过）：LEVEL 帧分发 build_vm.py:6006-6031（整数
  计数器，lvl_bad→rej 4；kind 常量 KL_ZERO=1..KL_MVAR=6 已备）；TASK_LEVEL
  推入点全文件仅三处：I_PIS1(:3577)、I_PIS2(:3618)、D_SORT2(:4310，**休眠
  臂**——全文件无 F2=D_SORT2 写入点，D_SORT3 的整数判据 :4317-4318 同死)；
  I_PIL2 整数折叠(:3633-3656)；I_SORTEM 已符号化(:3658-3683，卡 015 产物)；
  deq_sort 判据(:4150-4156，_lvl_eq 深度 8)；deq_const/deq_hargs 链
  (:3986-3989/:4098-4101，_lvl_chain_eq 深度 8 ×2 实例)；_lvl_eq(:3757-3785，
  结构子集 + Max/IMax 仅 pos_eq)；_n2z(:3814-3833，深度 8 共享子树 2^d-1
  节点)；pl_prop(:4619-4626)/G3(:5646-5657) 已接 n2z；P_EMIT(:5789-)按
  "链当前位 B + 剩余 succ 数 V1"包装 K_SORT，位置制。
- level 节点布局（VM_SPEC §12.1 已定且编码器已实现，expr/tokens.py:920-943）：
  K∈1..6，KL_SUCC.V0=子、KL_MAX/KL_IMAX.V0/V1=两侧、KL_PARAM/KL_MVAR.V0=
  nid(名)，V2=父指针，const 实参根 X=兄弟链。**运行期发射通道已存在**：
  raw 槽（raw_K_c/raw_V0_c/raw_V1_c/raw_X_c/raw_E2_c，build_vm.py:6764-6790）
  每微步可追加一个节点，I_SORTEM 已用它发射 KL_SUCC；c1=POS+1 为"本拍
  刚发射节点"的位置常数（:1179）。
- ST 六字段：task/V1/V2/E2/F2/X；任务结果经 E=1 + A 弹回父帧。
- 语料画像（本拍补扫，脚本 /tmp/018design/scan_chain_pos.py，三闭包
  dump.jsonl 只读，原文 §5.3）：**非平凡 level 实参只出现在链位 0/1**
  （本卡"非平凡"排除 succ(zero)；卡 017:68 的 13,892 计数含之——两卡数字
  口径不同非矛盾，审核 H4）
  （testBit 位置 0:253、位置 1:62；Vector3 0:41、1:13；Quot 0）；形状分布
  succ(param) 168 / max(succ 0,param) 56 / succ(succ param) 32 /
  imax(param,param) 29 / max(succ param,param) 11 /
  succ(imax(param, imax(...))) 6；level 树最深 3；const 链最长 5 实参。
  该分布钉死链位部署帽（§3.2）。
- 基线（本拍 P4 复测 = 卡 017 口径）：**34,671 dims / 4,527 lookups**；
  n2z 实测增量 +8,369 dims / +1,588 lookups（对 26,023 基线，2 个消费点）。

## 3. 设计（P2/P3 结论，细则与被拒案见 ADR 025）

### 3.1 表示（问题 1）——裁决：沿用节点位置制，零新编码

**入选（方案 R1）**：符号 level = ENV 节点子树（§12.1 布局，K/V0/V1/X），
ST/任务通道里流动的是**根位置**（整数位）；显式级保持 succ^k(zero) 节点链
（不再解码成计数器整数）；Param 恒等 = nid 整数相等（b.nid 名字注册表，
expr/tokens.py:311）；Max/IMax 二叉 = V0/V1 两侧位置。运行期构造走既有
raw 发射槽（一拍一节点），fold 产物 ≤1 个新节点/拍。
理由：布局/编码器/nid/发射槽/KL_* 全部已存在（卡 015 I_SORTEM 先例），
增量集中在判据电路；PG2 的 ERR 4 不是表示缺失而是 LEVEL 任务把符号树
解码成计数器。被拒案 R2（新 level token 流）、R3（ST 槽组合编码）、
R4（整数通道扩位）见 ADR 025。

### 3.2 操作面（问题 2）

- **to_offset 视图 `_lv_view(pos, cap=3)`**（D9）：沿 KL_SUCC 脊线性展开
  （非二叉——只追 V0），输出 (base 位置, base kind, k 计数, 越帽旗)。
  线性展开每级 1 个打包 fetch（k_,v0_ 同位一次取回=1 lookup）+ ~9 dims；
  cap 3 实测 **38 dims / 4 lookups**（§5.2 原型）。越帽（3 个 succ 旗全 1）
  → 保守判异（比较）或按原位处理（fold）。实测语料树深 ≤3（§2），帽 3 足盖。
- **is_not_zero 有界电路 `_n2z_or(pos, cap=3)`**（D8 姊妹，D2 规则 1 用）：
  Succ→1、Zero/Param/MVar→0、Max→两侧或、IMax→右支；实测 **137 dims /
  7 lookups**。与 n2z 方向相反（Succ/Max 门翻转）**不可共享**。
- **结构比较腿（D3 子集，现 _lvl_eq 改名 eq_struct 保留）**：pos_eq / Zero /
  Param/MVar nid / Succ 递归 / Max/IMax 仅 pos_eq。语义不动，只拆名——它是
  canonical 比较与 fold 内部的"便宜腿"。
- **canonical 等价 `eq_canon = eq_struct ∨ (n2z 双侧) ∨ max_branch`**（D4/D5
  有界子集）：
  - **n2z 双侧**：两侧都归零即等价（sound：normalize 后同为 zero）。仅部署
    deq_sort 一处（packed cap 4 双根 = 2×244 dims / 30 lookups）。覆盖
    探针 iz 类（Sort(imax 1 0) =?= Sort 0）。链位不部署（imax 归零形进链
    仅 raw 注入可得，残余记 sound-incomplete）。
  - **max_branch（multiset2，实测 779 dims / 44 lookups + imax 臂 ~180/~8）**：
    **不用 is_norm_lt 排序**——核按 interned level_id 排（level.cpp:407，10-13 勘误），图 nid
    整数序不可复现；且比较只需等价判定，等价 ⟺ 归一后多重集相等，免排序。
    步骤：两侧各做深度 2 max 摊平（根 + 单侧一层嵌套，3 实参槽 + 槽活性旗；
    根非 Max = 单槽原位；两侧同嵌 = 越帽）→ 每实参 _lv_view → 显式实参
    （base kind=Zero）先并成最大 k → 同 base 去重（保留最大 k，3 对/侧）→
    显式 k 被任一非显式存活实参 k'≥k 吸收（D5 :477-499 语义，探针 sn 钉
    负向）→ 3×3 配对匹配（base 等 = pos_eq ∨ 双显式 ∨ 双 Param nid 等；
    k 相等）→ 两侧存活实参互配且显式侧归并一致。
  - **imax 臂**：双侧根同为 KL_IMAX 时按 2 元有序对匹配（实参用 eq_struct
    比较）。**双侧根 kind 不同（MAX vs IMAX）一律判异**——探针 xc 钉死：
    核对 imax(succ u, 1) =?= max(succ u, 1) 判 declTypeMismatch（normalize
    是一次性展开，IMax 支经 mk_imax 智能构造不进 max 摊平路径），图必须
    同判，不许"数学等价"超收。
  - **部署面（6 实例，语料+探针证据钉死）**：deq_sort 结构递归深度 0 与 1
    各 1（深度 1 = PG6 的 succ(max 1 1) vs succ 1 形）；deq_const 链步 0/1
    各 1；deq_hargs 链步 0/1 各 1（kernel :1037 hints 链）。链步 ≥2 与
    deq_sort 深度 ≥2 保持纯结构腿——语料非平凡实参只在链位 0/1（§2 扫描），
    更深处判异方向 sound。扩展旋钮：每加 1 个链步/深度 ≈ +960 dims /
    +52 lookups（M-C 暴露再加深）。
- **infer_pi 折叠（D1/D2，I_PIL2 符号化，单拍电路，实测 525 dims /
  45 lookups）**：l1=frV1、l2=SA（位置）。按 K/level.cpp:112-123 序：
  is_not_zero(l2)（_n2z_or）→ mk_max 有界子集（规则序：双显式→k 大者；
  结构等→l1；zero(l1)→l2；zero(l2)→l1；吸收 m4 pos_eq 版（l2=max 侧含
  l1 位置）→对侧；同 base offset 比较→k 大者；否则发射 KL_MAX）→
  is_zero(l2)→l2 → is_zero(l1)∨is_one(l1)（k=SUCC ∧ v0 kind=Zero，2 lookups）
  →l2 → l1==l2（eq_struct）→l1 → 否则发射 KL_IMAX。发射/不发射由规则门控
  （em_raw_c 条件化），发射载荷恒 V0=l1、V1=l2；结果位置 =
  _select(链：mk_max 结果 / l2 / l2 / l1 / c1)，B_c=结果位、V1=0，
  P_EMIT 原样包装 K_SORT（零改动）。探针 pg2 钉死规则 4 路径
  （imax(succ u, succ u)→succ u，跨副本结构等）。**全序语义逐条对应
  ADR 022 组件 2 的欠账 + ADR 021 "修法唯一：D1/D2 落进图的 level 判据"。**
- **I_PIS1/I_PIS2 换道**：删 TASK_LEVEL 推入，l1=fV0 / l2=lvl2_root 直传
  （I_PIS1 的 A_c=fV0 写本来就有，只删 fr2 推入行）；根 kind∉1..6 保留
  rej 4（lvl_* 门已有，移进两臂，~20-40 dims/2 sites）。
- **LEVEL 任务退役**：TASK_LEVEL 分发块（:6006-6031）与三处推入点删除
  （含 D_SORT2/D_SORT3 休眠臂），防"Param 合法后旧 rej 4 复活"。
  P_EMIT/I_SORTEM/pl_prop/G3 零改动。
- **instantiate（D10/:317）时机**：本卡**不做**。检查路径需要它的点只有
  delta value / iota rhs 的运行期实例化（D14/B13，卡 017 P1）与
  infer_constant 声明类型实例化（图侧 §12.7 编码期 E2 特化已覆盖单
  use-site）；M-C 三探针（PG2/PG3/PG6）与 decl_injection 语料均不触发
  （PG2 的 ERR 4 出在 infer_pi 的 LEVEL 扫描，不是实例化）。通道就绪后
  （Param=nid 可寻址 + T_ENV_UNIVPARAMS 名字链已在库，expr/tokens.py:92）
  B13/D14 立卡时做"unfold 单步替换"，届时须复刻 D10 重建路径的
  update_max 智能构造（level.cpp:301-315）；§12.7 环境链方案维持被拒
  （ADR 022）。

### 3.3 声明注入/G3 面

decl_injection 语料的 kind 载荷（E2）与 is_prop 判据（n2z）不动；PG3/PG6
的 declTypeMismatch→ACCEPT 翻转只来自 deq_sort 判据升级。错误类别面：
canonical 比较只会**减少假拒**（多接受），不新增接受面以外的类别变化；
探针 sn/xc 钉死两个"必须仍拒"的负向行，防过收。ADR 021 KNOWN-GAP
（thm_imax/thm_max00 假拒 8）已由卡 015 清偿，XPASS 协议行保持。

### 3.4 残余（sound-incomplete，全部判异方向，进 ADR 025 与 VM_SPEC §16）

1. imax 子形归一（探针 isb：核 OK / 图拒）——n2z 双侧盖 imax 归零类，
   其余子形归一等价拒。
2. 链位 ≥2 与 deq_sort 深度 ≥2 的 canonical 比较（保持纯结构）。
3. max 摊平深度 >2（≥5 实参，或两侧同嵌）。
4. succ 脊 >3 的 (base,k) 视图（越帽判异）。
5. multiset 槽内的嵌套 Max/IMax 实参只 pos_eq（结构）。
6. fold 的 m4 吸收 pos_eq 版（跨副本同形吸收漏 → 发射冗余 max 节点，
   语义不变，下游 canonical 比较可兜）。

## 4. dims/lookups 预算（P4/P6，全部实测，原文 §5.2）

| 项 | 实例数 | dims/实例 | lookups/实例 | 小计 dims | 小计 lookups |
|---|---|---|---|---|---|
| max_branch（multiset2 779 + imax 臂 ~180） | 6（§3.2 部署面） | ~960 | ~52 | ~5.8k | ~312 |
| n2z 双侧 @deq_sort（packed cap 4） | 1 | ~490 | ~30 | ~0.49k | ~30 |
| I_PIL2 符号 fold（含 _n2z_or + 视图 + eq_struct×2） | 1 | ~525-600 | ~45-55 | ~0.56k | ~50 |
| I_PIS1/I_PIS2 换道 + kind 门 | 2 | ~20-40 | ~3-5 | ~0.06k | ~8 |
| LEVEL 任务退役回收（含 D_SORT2/3 死臂） | −1 | −(40-80) | −(3-5) | −0.06k | −4 |
| 杂项（select 门/发射载荷/结果通路布线） | — | — | — | +0.2-0.5k | +20-40 |
| **合计（点估）** | | | | **+7.0k-7.6k** | **+416-436** |

**总预估：+6.5k-9.5k dims / +0.4k-0.6k lookups**（点估上再加集成带宽
上界 ~25%——n2z 实测残差仅 2.4%-3.7%，25% 系自定保守余量；审核 H2）。
原 8.5k 上沿作废。点估下述：
集成开销带宽 2.4%-25%，校准见 §5.2）。

- 对照卡 017 预估窗 +8k-18k dims / +2k-4k lookups：**点估双指标低于下沿**（9.5k 上界贴近下沿）——
  原因：multiset 配对替代预估假设的"配对比较树 ×2"（2^depth 配对展开，
  被拒案 5，~44k dims）；fetch 打包（一 lookup 取同位多字段）把单树电路
  的 lookups 从 3/节点压到 1/节点。低于预估是方案收益，落地以实测为准。
- 对照 ADR 022 失控线（单节点 ~16 dims 级组合爆炸；单电路参照 n2z cap8
  = 4,084 dims）：最贵单电路 max_branch ~960 dims，**不触线**（~23%）。
- per-node 校准链：primitives 实价 reglu=1 dim、_eq_expr=3、_kind_eq_raw=3、
  _select=2、fetch=1 lookup（打包 N 字段同价）；n2z cap8 复刻件 4,084
  dims/765 lookups ×2 消费点 = 8,168/1,530，对卡 015 实测 +8,369/+1,588
  残差 2.4%/3.7% = 集成开销，方法学闭合（§5.2 原文）。
- 置信度：实例数（6/1/2）是图侧锚点+语料扫描实测计数（非估计）；
  dims/实例为原型实测值（同 primitives 构图），不确定性只剩实现期布线
  开销，区间已覆盖。

## 5. 探针记录（P4/P5，原文落盘）

### 5.1 oracle（4.33.1，run_kdecl_oracle，连跑两次输出一致；脚本
/tmp/018design/probe018.py，DEFS 前导含 6 条源 axiom + 1 条
`#eval Lean.addDecl` raw axiom k18IU，构造式要点全部在脚本内）

```
== run_kdecl_oracle (4.33.1, 2026-10-04) ==
  neg1     declTypeMismatch     # 负控：Sort (succ u) vs 值 k18T1:Sort 1
  p3_d0    OK                   # PG3 形：Sort(max 1 (succ u)) := k18P.{u}
  p6_d1    OK                   # PG6 形：Sort(succ (max 1 1)) := k18T1
  m5_sb    OK                   # mk_max 规则5：Sort(max (succ u) u) := k18P.{u}
  oi       OK                   # 序无关：Sort(max (succ u) (succ v)) := ax:max (succ v) (succ u)
  iz       OK                   # imax 归零：Sort(imax 1 0) := True
  sn       declTypeMismatch     # 负向钉：Sort(max 1 u) ≠ Sort u（显式 1 不被 k=0 实参吸收）
  isb      OK                   # imax 子形归一：Sort(imax u (max u 0)) := ax:Sort(imax u u)
  nm       OK                   # 嵌套摊平：Sort(max (max u v) u) := ax:Sort(max u v)
  xc       declTypeMismatch     # 跨类钉：Sort(imax (succ u) 1) ≠ 值型 Sort(max (succ u) 1)
                                 #   （normalize 一次性：IMax 支不进 max 摊平，图须同拒）
  pg2      OK                   # PG2 形 raw decl：Pi(x:Sort(succ u)) Sort(succ u) := λx.x
```

钉死的设计点：p3_d0/p6_d1 = PG3/PG6 的核侧期望（与卡 017 ok1/PG6 一致，
深度 0 与深度 1 两种形态都要盖）；m5_sb = mk_max 同 base offset 吸收；
oi = canonical 比较免排序的合法性（多重集语义）；iz = n2z 双侧快捷的
接受面；sn = 吸收负向（图 multiset 必须仍拒）；isb = 残余 1（核接受、
有界图拒）；xc = 跨 MAX/IMAX 根必须拒（图 imax 臂的门）；pg2 = fold
规则 4 路径（跨副本结构等）。

通道要点（重建用）：#KDECL 案例间 env 不互通（模板 addDecl 结果不回写
meta env），共享常量放 DEFS 前导；`succ` 不是 Level 源语法（用 `(v+1)`）；
`Lean.mkConst` 的 level 实参是 `List Level`（要 `Lean.Level.param \`u`）；
raw axiom 注入用 `#eval Lean.addDecl (.axiomDecl {...})` 单行结构实例
（ADR 021 方法）。

### 5.2 图基线与原型计量（/tmp/018design/，仓库外 scratch）

```
$ python /tmp/018design/baseline.py            # 只读 build_step_graph，不编译
baseline: 34671 dims, 4527 lookups             # 与卡 017 基线一致

$ python /tmp/018design/proto_circuits.py      # 同 primitives 构图的原型件
[n2z cap8 replica (build_vm verbatim)] dims=4084 (reglu=3315 lookupdims=765) lookups=765
[n2z packed cap4]  dims=244 (reglu=195 lookupdims=45)  lookups=15
[n2z packed cap3]  dims=116 (reglu=91  lookupdims=21)  lookups=7
[n2z_or packed cap3] dims=137 (reglu=112 lookupdims=21) lookups=7
[lv_view cap3 packed] dims=38 (reglu=27 lookupdims=7)   lookups=4
[lvl_eq_struct cap3]  dims=103 (reglu=87 lookupdims=12) lookups=12
[max_branch nargs=3 spine=3] dims=779 (reglu=709 lookupdims=66) lookups=44
[max_branch nargs=2 spine=3] dims=779 (arg 帽不敏感：主成本在提取/配对/门)
[max_branch nargs=3 spine=2] dims=713 lookups=38
[fold cap3] dims=525 (reglu=453 lookupdims=68) lookups=45
```

校准闭合：n2z cap8 复刻件 ×2 消费点 = 8,168 dims / 1,530 lookups，对卡 015
实测增量 +8,369 / +1,588，残差 201/58（2.4%/3.7%）= 消费点集成开销。
原型件与 build_vm 用同一 primitives 集（alm_graph.reglu /
lean_vm.primitives._eq_expr/_select/fetch_by_position 打包），per-实例数
即实现成本的直接计量。max_branch 的 imax 臂（~180 dims / ~8 lookups）为
原型外加估算（对配对比较结构外推），是 §4 区间上限的主要来源。

### 5.3 语料扫描（/tmp/018design/scan_chain_pos.py，三闭包 dump.jsonl 只读）

```
Nat_testBit_land: 非平凡实参位置 {0:253, 1:62}；形状 top: succ(param)168,
  max(succ 0,param)56, succ(succ param)32, imax(param,param)29,
  max(succ param,param)11, succ(imax(param,imax(...)))6；树深 ≤3；链长 ≤5
Vector3_cons_fz:  位置 {0:41, 1:13}；树深 ≤3
Quot_liftOn_mk:   位置 {}（无非平凡实参）
```

结论：链位部署帽 0-1 覆盖三闭包 100% 非平凡实参位；树深帽 3 覆盖 100%。

## 6. 拍 B 拆步建议（问题 4，总控排产输入）

依赖序裁决：**③（deq 判据）先行，①②（LEVEL 符号化 + fold）后行**。
理由：③ 只动 defeq 臂（deq_sort/deq_const/deq_hargs），不碰 infer 链，
回归半径最小；PG3/PG6 两线立即可验；fold（①②）发射的 Max/IMax 节点
落地时 canonical 消费端已在位，避免"fold 先行但比较仍旧"的中间态假拒。

- **拍 B1（③，图逻辑工程师）**：eq_struct/eq_canon 拆分（_lvl_eq 改名
  保留语义）+ max_branch（multiset2 + imax 臂，6 实例部署）+ n2z 双侧
  @deq_sort。验收：PG3/PG6 转 ACCEPT（原文落板）；PG1/PG4/PG5 保持 ACCEPT；
  §5.1 探针的图侧差分行 oi/nm/m5_sb/sn/xc/isb 与 oracle 判定逐行一致
  （sn/xc/isb 图=拒为期望）；decl_injection 全语料零破线；
  thm_imax/thm_max00 XPASS 行不回归；#LEVEL 37/37 保持。PG2 仍 REJECT 4
  （预期，B2 清）。
- **拍 B2（①②，图逻辑工程师）**：I_PIS1/I_PIS2 换道 + I_PIL2 符号 fold
  + LEVEL 任务退役（含 D_SORT2/D_SORT3 死臂清理）。验收：PG2 转 ACCEPT；
  B1 全部验收行不回退；新 fold 差分行（pg2 形 + imax(u,v) 发射形状对
  oracle）一致；decl_injection 全语料零破线；#LEVEL 全绿。
- **拍 B3（收尾，测试工程师 + 总控）**：重编译 --sparse + 引擎对拍
  （verify_engine_vs_refvm）+ 23 套件回归 + 图规模增量实测落
  ARCHITECTURE/VM_SPEC §12/§16/矩阵 D1-D5/D9/D10/A8/A18 行 + 卡 015
  组件 2 NOT-VERIFIED 摘记 + 残余清单（§3.4）进 VM_SPEC §16。
- 每拍独立可停：B1 失败不阻塞 B2 语义设计（fold 电路不依赖 multiset2），
  但 B2 不先于 B1 合入（§6 依赖序）。

## 7. Verifier 集（完工唯一依据，承卡 015/017 口径）

**2026-10-12 收口勾选**（证据 `~/logs/018/`，原文见 B2/B3 记录）：

- [x] PG2/PG3/PG6 转 ACCEPT（oracle 期望 = §5.1 现跑原文，禁预置）——
      lvl_pg2/lvl_p3_d0/lvl_p6_d1 全 PASS（oracle 同批现跑）
- [x] PG1/PG4/PG5 保持 ACCEPT（harness 自证）——lvl_PG1（链行自证）/
      lvl_PG4/lvl_PG5 PASS
- [x] §5.1 十一行探针的图侧差分行逐行与 oracle 判定一致
      （含负向 sn/xc 与残余 isb）——14/14+1xfail（isb 按残余登记方向）
- [x] decl_injection 全语料零破线（含 thm_imax/thm_max00 XPASS 协议行）
      ——129/129+2xfail 0 fail（10-12 收口跑）；10-13 复核修复后
      **130/130+2xfail 0 fail**（含新增 lvl_cc；`decl_full2.log` 6382.5s
      rc=0）；thm_imax/thm_max00 现为普通 D 行保持 PASS（XPASS 协议行
      卡 015 已摘除，无 XPASS 可现）
- [x] #LEVEL 通道（tests/test_level_vs_lean.py）37/37 保持并按新能力扩行
      （max/imax canonical 等价差分行，期望 = §5.1 通道现跑）——**37/37
      （10-13 复跑，`~/logs/018/level_018.log` wall 1.5s rc=0）**；
      "扩行"落位=常驻 `section lvl`（十一行矩阵+PG 行+cc 链行，
      本文件 §B2 验证记录）
- [x] A18/deq_const/A17 hints 链差分行（非平凡实参形状对照 oracle）——
      **10-13 复核更正**：§5.1 矩阵各行全部是 Sort-vs-Sort 判定，只踩
      deq_sort 深度 0/1 canonical 臂（lvl_p3_d0/m5_sb/nm/oi 等逐行 PASS
      属实，但映射记错了臂）。链步臂差分现状：**deq_const 链步 0 由
      `lvl_cc` 真差分**（同 cid 双 Const，链 [max (succ u) u] vs
      [succ u]：oracle=OK、纯结构腿必拒——15/15 原文见 B2 验证记录）；
      **deq_hargs 链步 0/1 差分行 NOT-VERIFIED**（11-常量最小 env 内
      未构造出"regular-hints def 头 + 异 level 链同 cid 对"的可判定行；
      臂在 build_vm.py:4462 与 :4352 同电路，语义风险低，按 AGENTS 如实
      记 NOT-VERIFIED，随卡 012 M-C 语料通道补差分）。链位 ≥2 无差分
      行=设计帽（语料无该形状，§16.10 残余 2）。
- [x] 23 套件回归全绿；重编译 --sparse + 引擎 34/34 不倒退；dims/lookups
      增量实测落文档（对照 §4 预估窗）——**部分满足如实记**：收口集
      （decl_injection 全节 130/130+2xfail、g03 7/7、g04 18/18、#LEVEL
      37/37、stepgraph 84/84）全绿 rc=0、引擎 34/34+known 3/4+meta、
      增量 +9,073/+544 在窗内；**23 套件全量 NOT-RUN**（B3 计划口径
      留里程碑出口，与 §7 原文差异如实登记，不算已满足）
- [x] 硬编码扫描零新增（无 cid/常量名分支）；VM_SPEC §12/§16、
      ENV_FORMAT（如需）/KERNEL_COVERAGE D 组行同步——扫描零命中
      （唯一 hit 为注释行）；VM_SPEC §12.8/§16.10、KERNEL_COVERAGE
      A8/A18/D1-D5/D9/D10 行、ARCHITECTURE 018 行（+019 漏行补登）已落；
      ENV_FORMAT 未动（零编码变更，"如需"不触发）

## 8. 触碰面

设计拍（本卡）：只写 `docs/plans/018-level-runtime-channel.md` 与
`docs/decisions/025-symbolic-level-runtime-channel.md`；探针脚本/生成件
一律 /tmp/018design/（仓库外）。
拍 B（图逻辑工程师，预告）：`lean_vm/build_vm.py`（主战场）；
`tests/`、`scripts/`（测试工程师）；`docs/VM_SPEC.md` §12/§16、
`docs/KERNEL_COVERAGE.md`、`ARCHITECTURE.md`（总控收口）。
禁触：`lean_vm/ref_vm.py`、`engine/*`、`compiler/*`、`model/runner.py`、
`expr/tokens.py`（本卡无新 token/布局需求——零编码变更）。

## 8.5 拍 B 执行段（图逻辑工程师，开工即落，随做随勾）

开工核对（2026-10-05，HEAD=2caca84）：基线复测 **36,602 dims / 5,071
lookups**（`/tmp/018design/baseline.py` 只读 build_step_graph，与卡 019
compile_019.log 记账一致；nnz 247,955 以 B3 重编译实测为准）。设计拍锚点
漂移复测（语义全部在位，实测行号回填）：

| 锚 | 设计拍行号 | 实测（2caca84） |
|---|---|---|
| c1/c2/c3 常数 | :1179 | :1199-1201 |
| I_PIS1（TASK_LEVEL 推入 fr2 行） | :3577 | :3597 |
| I_PIS2（同）+ lvl2_root select | :3618 | :3638 / :3629 |
| I_PIL2 整数折叠 + raw KL_ZERO | :3633-3656 | :3653-3676 |
| I_SORTEM（已符号化，零改动） | :3658-3683 | :3678-3703 |
| _lvl_eq / _lvl_chain_eq / _n2z | :3757-3833 | :3777-3853 |
| deq_const / deq_sort 门 | :3986-3989 | :4006-4011 |
| deq_hargs 链消费 | :4098-4101 | :4118-4120 |
| deq_sort 判据落点 | — | :4170-4176 |
| D_SORT2/D_SORT3 死臂 | :4306-4322 | :4326-4342 |
| P_EMIT（ph_emit 段，零改动） | :5789 | :5975-5996 |
| LEVEL 分发块 | :6006-6031 | :6189-6223 |
| m2_merge / frame 载荷合并 | :6764-6790 | :6776-6877 |
| raw 槽合并（cont 臂） | — | :6906-6991 |
| rej_code lvl_bad 臂 | — | :7055-7061 |

TASK_LEVEL 推入点全文件仍恰三处：I_PIS1(:3597)、I_PIS2(:3638)、
D_SORT2(:4330)；D_SORT2 无 F2=D_SORT2 写入点（休眠臂）。

### B0 执行序（串行；每步改 → py_compile → 探针 → 回填本段）

- [x] B0.1 本执行段落盘（锚点回填 + 基线复测）。
- [x] B0.2 oracle 期望现跑（/tmp/018design/probe018.py，4.33.1；§5.1 十一行
      原文核对一致，禁预置）。**2026-10-12**：/tmp 探针脚本已失，oracle
      期望由常驻 `section lvl` 的 `build_lvl_oracle()` 现跑产生（同
      #KDECL 通道、同 4.33.1），判定与 §5.1 原文逐行一致（见 B2 验证记录）。
- [x] B1 eq_canon 六实例 + n2z 双侧 @deq_sort + imax 臂（改 build_vm.py
      level 电路段）→ py_compile → 图探针（PG1-PG6 + §5.1 逐行）→ 回填。
      （054407f 落账+B1 验证记录；10-12 经 section lvl 当前树复跑一致。）
- [x] B2 I_PIS1/I_PIS2 换道 + I_PIL2 符号 fold + kind 门入臂 + LEVEL/D_SORT2/3
      退役 → py_compile → 图探针（PG2 翻线 + 全 11 行）→ 回填。
      （图侧实现随 054407f 入树；10-12 复跑见 B2 验证记录，PG2 转 ACCEPT。）
- [x] B3 测试集（decl_injection 全节 / g03 / g04 / #LEVEL 扩行 /
      stepgraph 84）+ 重编译 scratch + 引擎对拍 + 硬编码自查 + 文档同步
      （VM_SPEC/KERNEL_COVERAGE/本卡状态）。**10-12 总控收口**：全绿，
      账目见"B3 复跑账目"；文档同步 VM_SPEC §12.8/§16.10、
      KERNEL_COVERAGE D1/D2/D3/D4/D5/D9/D10/A8/A18、ARCHITECTURE 真值表
      018 行（019 漏行一并补登）。

### B1 实现记录（电路形状按 ADR 025 §2.3；实施中的偏差在此登记）

- 电路分层：`_lvl_eq` 语义不动改名 `_lvl_eq_struct`；新增
  `_lvl_eq_canon(l, r, depth, canon_left)`（struct 腿逐级复用 + 每个带
  canon_left>0 的层级挂 canonical 臂），deq_sort 顶层 canon_left=2
  （本层 + 第一层 succ 递归各 1 实例），链步 0/1 同构。
- 偏差登记（原型 → 实现）：① 原型 `n2z_or` 的 or 公式
  `reglu(a,reglu(One,b))+reglu(b,reglu(One,a))` = 2ab 在 a=b=1 时出 2，
  非 0/1 安全——实现改 `a + reglu(One-a, b)`（-_select 门要求）。② 原型
  fold 的 `m2 = lvl_eq_struct(...)` 与 r4 重复建两份电路——实现共用一个
  Expression（省 ~103 dims）。③ 原型 max_branch 的 expl 合并
  （`t_expl_ok` 要求双侧 anye 等价）与 D5 :477-499 语义不符（PG3 形：
  t 侧显式被自身非显式吸收而 s 侧无显式，须判等）——实现改为 per-side
  吸收后比较"显式存活者"（surv_t ⟺ surv_s ∧ k 相等）。
- **预算校正（实测归因，变体构建法 /tmp/018design/dims_attrib.py）**：
  单个 canonical 臂组（multiset + imax 臂 + 内嵌 struct 腿）实测
  **1,616 dims / ~90 lookups**（原型 779+~180 低估了 D5 幸存者语义
  ——吸收/支配去重/显式存活者一致——与 imax 臂 2×struct 配对的实价）。
  首版误把链步也建成 canon_left=2（每步 2 臂组，全图 10 个臂组）
  ——按设计"6 实例"语义改为链步=1 个臂组（实例=链步本身，步内 succ
  脊纯结构）→ −6,464；imax 臂子比较 struct 深度 8→4（语料树深 ≤3，
  §5.3；深度不足判异，登记残余）→ −2,640/−320。
- **附带修复（越界面外、根因修复，报总控备案）**：card 011 G9 外层推进门
  `g9_oon = reglu(step, reglu(1-hasin, g9_oX))` 的内项是裸位置值非 0/1 门
  ——≥2 个 lparam 的声明（如 §5.1 oi 行 u,v）整拍按位置值缩放（em_frame=32
  个帧）→ CHECK 活锁。G9 语料全是单元素链（oX=0）掩盖了 oon 迁移。
  修为 `_geq_expr(g9_oX, One)`。oi 行因此在基线上也不收敛（本拍实测基线
  oi TIMEOUT 复现），不修则卡 018 verifier 的 oi 行无法图侧运行。

### B1 验证记录（2026-10-05，探针原文 /tmp/018design/gprobe_b1_v4.log；
oracle 同批现跑 4.33.1，期望未预置）

```
graph env: 11 consts
  [PASS] neg1: oracle=declTypeMismatch graph=accept=False code=1 steps=11
  [PASS] p3_d0: oracle=OK graph=accept=True code=0 steps=11
  [PASS] p6_d1: oracle=OK graph=accept=True code=0 steps=10
  [PASS] m5_sb: oracle=OK graph=accept=True code=0 steps=11
  [PASS] oi: oracle=OK graph=accept=True code=0 steps=13
  [PASS] iz: oracle=OK graph=accept=True code=0 steps=10
  [PASS] sn: oracle=declTypeMismatch graph=accept=False code=1 steps=11
  [RESIDUAL-REJECT (expected)] isb: oracle=OK graph=accept=False code=1
      steps=11          # §3.4 残余 1，按拒登记
  [PASS] nm: oracle=OK graph=accept=True code=0 steps=13
  [PASS] xc: oracle=declTypeMismatch graph=accept=False code=1 steps=11
  [FAIL] pg2: oracle=OK graph=accept=False code=4 steps=11
      # B1 预期态：仍走 LEVEL 任务（Param → rej 4），B2 清
  [info] PG1: graph=accept=True code=0 steps=19
  [info] PG3: graph=accept=True code=0 steps=11
  [info] PG4: graph=accept=True code=0 steps=11
  [info] PG5: graph=accept=True code=0 steps=7
  [info] PG6: graph=accept=True code=0 steps=10
```

- 图基线复测（B1 后）：**45,198 dims / 5,557 lookups**（增量 **+8,596 /
  +486**，预算窗 +6.5k-9.5k / +0.4k-0.6k 内）。

### B2 续接执行计划（2026-10-05 第二任图逻辑代理，开工即落）

现场修正（总控派工简报与实际树状态的差异，先落档再动手）：

- **HEAD=054407f 的 build_vm.py 已含 B2 全部图侧实现**——第一任 B2 代理
  完成后被取消，总控 B1 checkpoint 连同其 WIP 一起提交，本卡 B2 段未及
  回填。证据（054407f 实测行号）：I_PIS1 换道 + kind 门 :3948-3978、
  I_PIS2 换道 + lvl2_root + kind 门 :3979-4010、I_PIL2 符号 fold
  :4012-4099、I_SORTEM 符号消费 :4101-4126、D_SORT2/3 退役注记
  :4670-4671、整数 LEVEL 分发块删除注记 :6526、TASK_LEVEL 全文件仅剩
  import（:63）。
- 第一任探针日志链 /tmp/018design/：gprobe_b2.log（UnboundLocalError
  `_lvl_kind_ok`）→ gprobe_b2b.log（m2_merge 参数数错）→ gprobe_b2c.log
  （11 行全 PASS + PG1-PG6 全 accept）。修复已入树；但日志是当时树状态
  产物，**不可作证据**，须在当前树现跑复核。
- 派工简报"thm_imax XPASS 行摘除"核对：KNOWN_GAPS 现仅 ipr_dep_snd
  （卡 019），thm_imax/thm_max00 的 gap 登记卡 015 已摘除、现为普通 D 行
  （tests/test_decl_injection_vs_lean.py:296-299 无 xfail 挂钩）——无
  XPASS 可摘；实测复跑若确认为 PASS 即记"已满足（卡 015 清偿）"。

步骤（串行；每步 py_compile → 探针/测试 → 回填本段）：

- [x] B2.R1 py_compile + §5.1 十一行探针当前树现跑（/tmp/018design/
      graphprobe.py，oracle 现跑钉期望 4.33.1，核 0-5）。
      **2026-10-12 总控**：py_compile OK；/tmp/018design 已随 /tmp 清空
      丢失，改经常驻 `section lvl`（同矩阵 + oracle 现跑）执行，结果见
      "B2 验证记录"（14/14+1xfail rc=0）。
- [x] B2.R2 换道/fold 实测行号回填（上方"现场修正"表按当前树核对）。
      **2026-10-12 总控复核**：当前树行号与"现场修正"表一致——I_PIS1 换道
      + kind 门 :3948-3978、I_PIS2 :3979-3981、I_PIL2 fold :4012-4099、
      I_SORTEM 符号消费 :4101-4104、D_SORT2/3 退役注记 :4670-4672、
      LEVEL 分发块退役注记 :6525-6528；LVL_DEPTH=8 :3240、
      LVL_CANON_SPINE=3 :3350。工作树相对 054407f 仅 import 行一改动
      （行数不变），表免回填直接成立。
      **10-13 追记（85497c4 后）**：复核 follow-up 的 :3336 注释改动净
      +1 行，≥:3336 锚点整体 +1（I_PIS1 :3949-3979、I_PIS2 :3980-3982、
      I_PIL2 fold :4013-4100、I_SORTEM :4102-4105、D_SORT2/3 :4671-4673、
      LEVEL 退役注记 :6526-6529、_lvl_eq_struct :3244、_lvl_chain_eq
      :3274、_lv_view :3370、_n2z_or :3577、_lvl_eq_canon :3542、
      deq_const :4352、deq_hargs :4462、deq_sort :4517）；
      VM_SPEC/KERNEL_COVERAGE 已同步；dims/lookups 不变（comment-only）。
- [x] B2.R3 TASK_LEVEL 残留 import 清理（build_vm.py 导出表移除；tokens.py
      常量保留——scripts/probe_014_* 诊断脚本仍导入）+ 整数计数器路径
      grep 复核（无其他消费点）。**2026-10-12 总控复核**：import 行已移除
      （工作树，待提交）；`grep TASK_LEVEL lean_vm/build_vm.py` 零命中
      （连 import 痕迹也无）；`tokens.py` 常量按卡口径保留不动。
- [x] B2.R4 tests/test_decl_injection_vs_lean.py 新增 section lvl（卡 018）：
      §5.1 十一行矩阵落成常驻差分行（env 走 import_env_meta + k18 前导，
      沿 section_ipr 先例；isb 以 KNOWN_GAPS 登记"有界比较残余，
      核 OK/图拒"）；G02_ONLY=lvl 可单独跑。**2026-10-12 总控**：节已
      存在（第二任代理落盘未提交），现跑 14/14+1xfail rc=0 验证通过。
- [x] B2.R5 decl_injection 全节复跑（115/115+1 xfail 基线不倒退 + 新 lvl
      节）。**10-12**：129/129+2xfail 0 fail（=115+14 lvl 行；
      xfails=ipr_dep_snd+lvl_isb），rc=0。
- [x] B2.R6 本卡 B2 实现记录 + B2 验证记录回填（原文粘贴）。**10-12**：
      "B2 验证记录"段已落（lvl1.log 原文）。

B3 计划（收口，承派工简报）：decl_injection 全节 + g03 7/7 + g04 18/18 +
test_level_vs_lean.py 37/37 + test_stepgraph_infer_defeq 84/84 复跑（mem-guard
脱管，LOG_DIR=$HOME/logs/018/reg，核 14-19）→ 重编译
model/step_vm_018_scratch（--sparse，核 14-19）+ dims 记账 vs 45,198/5,557 →
verify_engine_vs_refvm 34/34 + meta → 硬编码自查（KL_* 残留消费点）→
VM_SPEC §12/§16 + KERNEL_COVERAGE D1-D5/D10/A8/A18 行 + 本卡状态行同步；
23 套件全量 NOT-RUN（留里程碑出口）。

### B2 验证记录

**2026-10-12 总控收口跑；10-13 复核修复后重跑**（卡间隔 7 天后续接；探针
scratch /tmp/018design/ 已随 /tmp 清空丢失——R1 改经 B2.R4 落成的常驻
`section lvl` 差分节执行，同一十一行矩阵 + oracle 现跑，且从此防 /tmp
易失。**10-13：独立复核发现 §7 第 5 项错标——§5.1 矩阵各行全部是
Sort-vs-Sort 判定、只踩 deq_sort canonical 臂，链步臂无差分行**；按复核
指令补 `lvl_cc`（同 cid 双 Const、链 [max (succ u) u] vs [succ u]，
oracle=OK / 纯结构腿必拒=真分叉 deq_const 链步 0 canonical 臂），原文
如下（`~/logs/018/lvl2.log`；前次 14 行版 `lvl1.log` 保留）：

```
oracle binary: Lean (version 4.33.1, x86_64-unknown-linux-gnu, commit 819816b2e0a3bf405af45ae5c7af2491d8f5bee6, Release)
oracle channel: #KDECL → Lean.Kernel.Environment.addDecl (/home/xkq/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean); generated file /tmp/vm_kdecl_oracle.lean
graph env: 58 consts (8 ctors, 3 structs)
  stored type of injX_imax: Sort(level=LIMax(a=LSucc(l=LZero()), b=LZero()))
  stored type of injX_max: Sort(level=LMax(a=LZero(), b=LZero()))
  stored type of injD_imax: Sort(level=LZero())
  stored type of injD_max: Sort(level=LZero())
  stored type of g06v_f: Const(name='Nat', levels=())
  stored type of g06v_g: Const(name='Nat', levels=())
lvl   card 018 symbolic level channel: bounded canonical max/imax compare + I_PIL2 fold vs live #KDECL oracle
  [PASS] lvl lvl_neg1: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=11
  [PASS] lvl lvl_p3_d0: oracle=OK graph=accept=True code=0(accept) steps=11
  [PASS] lvl lvl_p6_d1: oracle=OK graph=accept=True code=0(accept) steps=10
  [PASS] lvl lvl_m5_sb: oracle=OK graph=accept=True code=0(accept) steps=11
  [PASS] lvl lvl_oi: oracle=OK graph=accept=True code=0(accept) steps=13
  [PASS] lvl lvl_iz: oracle=OK graph=accept=True code=0(accept) steps=10
  [PASS] lvl lvl_sn: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=11
  [XFAIL-KNOWN-GAP] lvl lvl_isb: oracle=OK graph=accept=False code=1(declTypeMismatch) steps=11
      known gap: card 018: imax subterm normalization — kernel OK via one-shot normalize (level.cpp:518-521), graph rejects (bounded canonical compare, ADR 025 residual 1; n2z dual side covers the imax→zero class only).
  [PASS] lvl lvl_nm: oracle=OK graph=accept=True code=0(accept) steps=13
  [PASS] lvl lvl_xc: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=11
  [PASS] lvl lvl_pg2: oracle=OK graph=accept=True code=0(accept) steps=35
  [PASS] lvl lvl_PG1: graph=accept=True code=0(accept) steps=19 (chain, harness self-evident accept)
  [PASS] lvl lvl_PG4: oracle=OK graph=accept=True code=0(accept) steps=11
  [PASS] lvl lvl_PG5: oracle=OK graph=accept=True code=0(accept) steps=7

=== card 010 G02 decl-injection differential: 14/14 checks pass, 1 xfail known-gap, 0 fail (245s) ===
=== OK ===
[mem-guard] wall 245.7s peak RSS 1566MB rc=0
```

10-13 复核修复重跑原文（`~/logs/018/lvl2.log`，新增 `lvl_cc` 行）：

```
lvl   card 018 symbolic level channel: bounded canonical max/imax compare + I_PIL2 fold vs live #KDECL oracle
  [PASS] lvl lvl_neg1: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=11
  [PASS] lvl lvl_p3_d0: oracle=OK graph=accept=True code=0(accept) steps=11
  [PASS] lvl lvl_p6_d1: oracle=OK graph=accept=True code=0(accept) steps=10
  [PASS] lvl lvl_m5_sb: oracle=OK graph=accept=True code=0(accept) steps=11
  [PASS] lvl lvl_oi: oracle=OK graph=accept=True code=0(accept) steps=13
  [PASS] lvl lvl_iz: oracle=OK graph=accept=True code=0(accept) steps=10
  [PASS] lvl lvl_sn: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=11
  [XFAIL-KNOWN-GAP] lvl lvl_isb: oracle=OK graph=accept=False code=1(declTypeMismatch) steps=11
      known gap: card 018: imax subterm normalization — kernel OK via one-shot normalize (level.cpp:518-521), graph rejects (bounded canonical compare, ADR 025 residual 1; n2z dual side covers the imax→zero class only).
  [PASS] lvl lvl_nm: oracle=OK graph=accept=True code=0(accept) steps=13
  [PASS] lvl lvl_xc: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=11
  [PASS] lvl lvl_pg2: oracle=OK graph=accept=True code=0(accept) steps=35
  [PASS] lvl lvl_cc: oracle=OK graph=accept=True code=0(accept) steps=29
  [PASS] lvl lvl_PG1: graph=accept=True code=0(accept) steps=19 (chain, harness self-evident accept)
  [PASS] lvl lvl_PG4: oracle=OK graph=accept=True code=0(accept) steps=11
  [PASS] lvl lvl_PG5: oracle=OK graph=accept=True code=0(accept) steps=7

=== card 010 G02 decl-injection differential: 15/15 checks pass, 1 xfail known-gap, 0 fail (302s) ===
=== OK ===
[mem-guard] wall 302.9s peak RSS 1548MB rc=0
```

- 十一行矩阵逐行与 oracle（4.33.1 现跑）一致；`lvl_isb` 按 ADR 025 残余 1
  以 XFAIL-KNOWN-GAP 登记（判异方向，不过收）。**PG2 转 ACCEPT**（lvl_pg2，
  I_PIL2 fold 路径，35 步）——B2 拍目标达成；PG1/PG4/PG5 保持 ACCEPT。
- 十一行探针的图侧差分行（含负向 sn/xc 与残余 isb）全部与 §5.1 oracle
  判定一致——卡 §7 verifier 行 1/2/3 满足。
- 全节复跑（R5）与 B3 账目见 §"B3 复跑账目"。

### B3 复跑账目

**2026-10-12 总控收口跑**（~/logs/018/；核段：验证 8-13、编译/引擎 14-19；
逐项 mem-guard 脱管）：

| 项 | 结果 | 证据 |
|---|---|---|
| decl_injection 全节（R5/B3） | 收口跑 **129/129 checks pass, 2 xfail known-gap, 0 fail**（6210.2s / RSS 1841MB / rc=0）；对卡 019 基线 115/115+1xfail = +14 lvl 行 +1 xfail（lvl_isb），**零破线**；g03 **7/7**、g04 **18/18** 逐行核出全 PASS（含 thm_imax/thm_max00 普通 D 行保持绿=卡 015 清偿不倒退）。**10-13 复核修复后带 `lvl_cc` 行全语料重跑**：`decl_full2.log`：
**130/130 checks pass, 2 xfail known-gap, 0 fail**（6382.5s / RSS 1808MB /
rc=0；=129+cc，lvl_cc 行 [PASS] oracle=OK graph=accept=True code=0
steps=29 同日志内） | `decl_full.log`、`decl_full2.log` |
| #LEVEL 通道 | **37/37**（10-13 复跑 `level_018.log`：wall 1.5s / RSS 1508MB / rc=0；10-12 收口日跑 6.1s/1541MB 同 rc=0）；新能力扩行经 lvl 常驻差分行承载（§7 口径） | `level_018.log` |
| stepgraph_infer_defeq | **84/84 (0 pinned)**、rc=0；wall 3420.9s / RSS 565MB。帽账（诚实登记）：首跑撞回归旧帽 3300s 被 timeout 杀（78 行全 PASS 0 FAIL=合法耗时长；同时段桌面另一项目 m8_epoch.py 占 CPU/GPU 内存，见 §事故记录）→ 提帽 4500（=3420.9×1.31）复跑 rc=0。中间一次因客户端 OOM 闪退连坐断跑（stepgraph2，42 行处进程树被清，非本任务内存所致——OOM dump 击杀对象 pid 375294 anon-rss 20.2GB 属另一会话任务，本任务当时 513MB） | `stepgraph.log`（首杀）、`stepgraph3.log`（终态） |
| 重编译 --sparse | `model/step_vm_018_scratch.sbin`：dims **45,675** / lookups **5,615** / nnz **296,674**、26,416,446B、md5 `5e93e0cc0d0254e5c6f898f27b30a630`（41.4s / 峰值 ~700MB）；对 B1 **+477/+58**，对卡 019 基线 **+9,073/+544**——预算窗 +6.5k-9.5k / +0.4k-0.6k **双侧内** | `compile_018.log`、`build_step_graph` 实测 |
| 引擎对拍 | **34/34 + known 3/4（基线持平）+ meta 门 OK**（76 output dims, 13 token consts）；1112.5s / 285MB / rc=0；钉 SBIN=step_vm_018_scratch.sbin。**10-13 复核意见 #4（日志未自证 SBIN）处理**：`verify_engine_vs_refvm.py` 首行打印 SBIN（1 行 harness 改），带 echo 重跑 `engine_018b.log`：**34/34 + known 3/4 + rc=0（1109.8s/286MB），首行 `SBIN under test: .../step_vm_018_scratch.sbin`** | `engine_018.log`、`engine_018b.log`、`engine_meta_018.log` |
| 硬编码自查 | 卡 018 delta（054407f vs 2caca84，build_vm.py +539 行）扫描：**零具名常量名/cid 分支**（唯一命中为注释行）；TASK_LEVEL build_vm 内零残留；KL_* 消费点全为既存 kind 标签判据 | 会话现场 grep |
| 23 套件全量 | **NOT-RUN**（按卡 §B3 计划留里程碑出口） | — |

**事故记录（2026-10-12 09:32:55，本机 global OOM，内核 journal 原文）**：
`Out of memory: Killed process 375294 (python3) anon-rss:20210244kB`，
task_memcg=app-zcode-ce scope——20.2GB 的被杀 python3 属另一会话的训练任务
（桌面 Neural computer 项目 m8_epoch 一代，同 dump 内另有 5.7GB 同项目进程）；
本卡 stepgraph2 当时 RSS 513MB（帽 5000MB）非起因，但随客户端闪退被进程树
清理连坐死亡（日志断在 42/84 行，无 mem-guard 终行）。处置：stepgraph 重跑
（stepgraph3 rc=0），帽 3300→4500 校准（依据：首跑 78 行全 PASS 0 FAIL +
3420.9s 实测 + 同时段邻居负载），登记回归脚本帽由总控另行落
`scripts/run_cpu_regression.sh`（本卡未动）。

## 9. 决策引用

- 卡 017 P0-1（四件范围 + PG 探针表 + 语料证据 + 预算窗）——本卡上游
- 卡 015 组件 2 NOT-VERIFIED（deq_sort/A18 Max/IMax，"独立卡候选"）——
  本卡 §3.2 canonical 比较即其清偿，收口时摘记
- ADR 022（混合方案；组件 2 可后置；被拒案：纯编码期特化/完整 D5 全序/
  运行期 T_LVLSUB 环境链）——本卡继承全部被拒结论，canonical 方案显式
  避开"完整全序"；组件 1（n2z，cap 8 双点）原样保留不动
- ADR 021（mode 非归一 level 形 KNOWN-GAP；"修法唯一：D1/D2 落进图的
  level 判据"）——本卡 §3.2 fold 即其落地
- VM_SPEC §12.1-§12.7（token 布局/D1-D14 语义/§12.7 实例化失败史）
- n2z 先例成本：卡 015/017（+8,369 dims / +1,588 lookups 对 26,023 基线；
  本拍 §5.2 复刻件把该数拆到 per-实例 4,084/765）
