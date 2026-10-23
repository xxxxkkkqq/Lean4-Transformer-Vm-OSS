# 025. 符号 level 运行期通道：节点位置制表示 + 有界 canonical 比较（卡 018 设计拍定案）

- 状态：**draft（语义设计师，2026-10-05；待独立复核 + 总控落档）**
- 背景：图 LEVEL 通道是整数显式级计数器（build_vm.py:6006-6031 自述边界；
  卡 015 后 I_SORTEM/pl_prop 已局部符号化）。卡 017 分诊实测三条判定分歧：
  PG2（带 `Type u` 域的 Pi 型声明 CHECK 即拒 ERR 4，I_PIS1→LEVEL(Param)）、
  PG3/PG6（max 归一化 defeq 假拒 ERR 1）。M-A 语料 288/779 常量带 univ
  参数、非平凡 level 实参 13,892 个；卡 015 组件 2（deq_sort/A18 的
  Max/IMax 比较）按 ADR 022 授权后置，登记 NOT-VERIFIED。
- 决策：**沿用 ENV 节点位置制承载符号 level（零新编码），增量全部落在
  三块有界判据电路上**：
  1. **表示 = 节点位置**（§决策 1）；
  2. **I_PIL2 单拍符号 fold**（D1/D2 智能构造，"图侧 mk_imax/mk_max"）；
  3. **eq_canon = eq_struct ∨ n2z 双侧 ∨ max_branch(multiset2 + imax 臂)**
     （D3/D4/D5 有界子集，6 实例部署）。
  预算 **+6.5k-8.5k dims / +0.4k-0.6k lookups**（对 34,671/4,527 基线，
  实测校准，见 §预算）；最贵单电路 ~960 dims，距 ADR 022 失控线
  （单电路 ~4k dims 量级）约 4 倍余量。
- 与既有裁决的合并/继承关系（显式交代，不推翻）：
  - **卡 015 组件 2 NOT-VERIFIED（deq_sort/A18 Max/IMax，"独立卡候选"）**：
    本 ADR 的 eq_canon 即其清偿方案；拍 B1 落地 + B3 收口后摘记。
  - **ADR 021（"修法唯一：D1/D2 落进图的 level 判据"）**：本 ADR 的
    I_PIL2 符号 fold 即其落地；is_prop 侧已由卡 015（n2z）清偿，
    thm_imax/thm_max00 XPASS 协议行保持为回归卫兵。
  - **ADR 022 全部被拒案继续有效**：纯编码期特化、完整 D5 normalize
    全序、运行期 T_LVLSUB 环境链。本 ADR 的 canonical 比较是 ADR 022
    "组件 2 可后置"占位的兑现，显式避开被拒的完整全序；组件 1（n2z
    电路，cap 8、双消费点）原样保留不动。

## 决策 1：表示——ENV 节点位置制（R1）

符号 level 在图内 = 既有 level 节点子树（VM_SPEC §12.1 布局：
KL_SUCC.V0=子、KL_MAX/KL_IMAX.V0/V1=两侧、KL_PARAM/KL_MVAR.V0=nid(名)，
const 实参根 X=兄弟链；编码器 expr/tokens.py:920-943 已实现）。ST/任务
通道流动**根位置**；显式级保持 succ^k(zero) 节点链，不再解码成计数器
整数；Param 恒等 = nid 整数相等（nid 来自 b.nid 名字注册表，
expr/tokens.py:311，nid 相等 ⟺ 内核 Name 相等）。运行期构造 = 既有 raw
发射槽（build_vm.py:6764-6790，一拍一节点，I_SORTEM 已用同机制发射
KL_SUCC；c1=POS+1 为"本拍刚发射节点"位置常数）。
关键约束的落位：Max/IMax 二叉 = V0/V1 两侧位置（§12.1 布局天然支持）；
显式 0/1 常量的内联吸收不在表示层做——由 fold 的智能构造规则
（D1 规则 1/3、D2 规则 2/3，K/level.cpp:81-123）在构造点吸收，与核一致。

PG2 的 ERR 4 根因不是表示缺失：level 树早就是节点，是 LEVEL 任务把树
解码成 to_explicit 整数、遇到 Param/Max/IMax 即拒。换道后 LEVEL 任务
退役（TASK_LEVEL 分发块与全部三处推入点删除，含 D_SORT2/D_SORT3 死臂
:4306-4322——休眠臂留着会在 Param 合法化后成为误接错臂的隐患）。

### 被拒表示案

- **R2 新 level token 流 / 平行 level 通道**：level 已是一等 ENV 节点、
  走统一 attention fetch；平行流要自己的取数通路（新 lookup heads）+
  第二套编码/解码，成本严格更高、语义零增益。且"一图一权重"宪法下
  双通道表示必然在消费点分叉。
- **R3 ST 槽组合编码**（把 (base,k) 或 kind+payload 打进 ST 字段的
  位布局）：ST 六字段是纯数值槽、被 _select/_eq 直读；复合编码让每个
  消费者背解码电路，且破坏"结果=位置"的 P_EMIT/弹回协议不变量。
- **R4 整数通道扩位**（保留计数器、旁路挂 Param nid）：整数无法承载
  Max/IMax 树（PG3/PG6 恰是树比较），扩位即退化成 R3。

## 决策 2：操作面（图侧实现形状）

### 2.1 to_offset 视图 `_lv_view(pos, cap=3)`（D9）

沿 KL_SUCC 脊**线性**展开（只追 V0，非二叉——这是它便宜的原因），
输出 (base 位置, base kind, k 计数, 越帽旗)。每级 1 个打包 fetch
（k_/v0_ 同位一次取回）+ ~9 dims；cap 3 实测 38 dims / 4 lookups。
越帽保守：比较里判异；fold 里按原位。实测语料 level 树深 ≤3（三闭包
全量扫描），帽 3 全覆盖。

### 2.2 is_not_zero 有界电路 `_n2z_or(pos, cap=3)`（D2 规则 1 用）

D8 n2z 的方向翻转姊妹件：Succ→1、Zero/Param/MVar→0、Max→两侧或、
IMax→右支（K/level.cpp:160-172 原文规则）。实测 137 dims / 7 lookups。
**不可与 n2z 共享**（Succ 与 Max 的门翻转），也不与 n2z 共用 cap（新件
cap 3，n2z 既有 cap 8 双点不动）。

### 2.3 canonical 比较 `eq_canon = eq_struct ∨ (n2z 双侧) ∨ max_branch`
（D3/D4/D5 有界子集；现 _lvl_eq 改名 eq_struct，语义不动）

- **eq_struct**（既有 D3 子集）：pos_eq / Zero / Param/MVar nid / Succ
  递归 / Max/IMax 仅 pos_eq。是 eq_canon 的"便宜腿"，也是 fold 内部
  的比较件。
- **n2z 双侧**（D4 的 normalize-to-zero 快捷，sound：两侧 normalize 后
  同为 zero）：仅部署 deq_sort 一处（packed cap 4 双根 = 2×244 dims /
  30 lookups）。覆盖 imax 归零类（探针 iz：`Sort(imax 1 0) =?= Sort 0`
  核 OK）。**不设独立的 normalizes-to-one 电路**（被拒，见 §被拒案 8）。
- **max_branch = multiset2 + imax 臂**（D5 有界子集，实测 779+~180 dims /
  44+8 lookups）：
  - **免排序**：核的 normalize 按 is_norm_lt 排序（level.cpp:474），其中
    Param/MVar 比 **interned level_id**（level.cpp:407；由 name 的 intern
    注册序派生，非字典序——2026-10-13 复核勘误；结论不变：图 nid 是
    encounter order 的整数值，不可复现该序；且等价**判定**不需要 canonical 序，只需要
    归一后实参多重集相等。故 multiset2 做免序配对（探针 oi 钉死合法性：
    `max (succ u) (succ v) =?= max (succ v) (succ u)` 核 OK）。
  - **max 路（multiset2）**：两侧各做深度 2 max 摊平（根 + 单侧一层嵌套，
    3 实参槽 + 活性旗；根非 Max = 单槽原位；两侧同嵌 = 越帽判异）→
    每实参 _lv_view → 显式实参（base kind=Zero）并成最大 k（核
    level.cpp:477-486 的"找最大显式"语义；小显式被大显式吸收，与核
    rargs 从 args[i] 起重建一致）→ 同 base 去重（保留最大 k）→ 显式 k
    被任一非显式存活实参 k'≥k 吸收（核 :487-499；探针 sn 钉负向：
    `Sort(max 1 u) ≠ Sort u`，k=0 实参不吸收 1）→ 3×3 配对匹配
    （base 等 = pos_eq ∨ 双显式 ∨ 双 Param nid 等；k 相等）→ 两侧存活
    实参互配。探针 nm 钉正向：`max (max u v) u =?= max u v` 核 OK
    （深度 2 摊平 + 去重覆盖）。
  - **imax 臂**：双侧根同为 KL_IMAX → 2 元有序对匹配（实参 eq_struct）。
    **双侧根 kind 不同（MAX vs IMAX）一律判异**——探针 xc 钉死：
    `Sort(imax (succ u) 1) =?= 值型 Sort(max (succ u) 1)` 核判
    declTypeMismatch。机理：normalize 是**一次性展开**（is_equivalent =
    `lhs == rhs || normalize(lhs) == normalize(rhs)`，level.cpp:518-521），
    IMax 支 normalize 走 mk_imax 智能构造（:463-467）不进 max 摊平路径，
    归一后仍是非摊平的 max 形；图若按"数学等价"超收即判错。图必须
    镜像核的一次性 normalize，不是闭包语义。
  - **部署面（6 实例）**：deq_sort 结构递归深度 0/1 各 1（深度 1 盖
    PG6 的 succ(max 1 1) vs succ 1 形）；deq_const 链步 0/1 各 1；
    deq_hargs 链步 0/1 各 1（kernel :1037 hints 链同规则）。链位帽的
    证据：三闭包全量扫描非平凡实参**只出现在链位 0/1**（testBit
    0:253/1:62、Vector3 0:41/1:13、Quot 0，脚本 /tmp/018design/
    scan_chain_pos.py）。扩展旋钮：每加 1 链步/深度 ≈ +960 dims /
    +52 lookups，M-C 暴露再加深。

### 2.4 infer_pi 折叠 = I_PIL2 单拍符号 fold（D1/D2 落地）

输入 l1=ST.V1（域 Sort 的 level 根，I_PIS1 直传 fV0）、l2=ST.A（体 Sort
的 level 根，I_PIS2 直传 lvl2_root）。按 K/level.cpp:112-123 规则序单拍
求值（全部谓词为同拍电路）：
1. is_not_zero(l2)（_n2z_or）→ mk_max 有界子集：
   a. 双显式 → (base,k) 视图 k 大者（D1 规则 1，get_depth 语义）；
   b. l1==l2（eq_struct）→ l1（规则 2；探针 pg2 钉跨副本结构等路径）；
   c. zero(l1) → l2；zero(l2) → l1（规则 3/4，语法零）；
   d. m4 吸收（规则 5/6 的 pos_eq 版：l2 是 max 且 l1 是其一侧 → l2，
      对称）；
   e. 同 base offset 比较（视图 base 等 ∧ 非双显式 → k 大者，规则 7/8
      的 to_offset 语义；探针 m5_sb 钉正向：`max (succ u) u =?= succ u`
      核 OK）；
   f. 否则发射 KL_MAX（V0=l1, V1=l2）。
2. is_zero(l2) → l2（D2 规则 2，语法零）。
3. is_zero(l1) ∨ is_one(l1)（k=SUCC ∧ v0 kind=Zero）→ l2（D2 规则 3；
   is_one 是核的语法判据 level.cpp:106-110，不是 n2o）。
4. l1==l2（eq_struct）→ l1（D2 规则 4）。
5. 否则发射 KL_IMAX。
发射门控：仅 1f/5 发射（em_raw_c 条件化，一拍至多一节点）；结果位置 =
_select(mk_max 结果 / l2 / l2 / l1 / c1)；B_c=结果位、V1=0；P_EMIT 原样
包装 K_SORT（零改动）。整 fold 实测 525 dims / 45 lookups（原型含
_n2z_or + 2 视图 + eq_struct×2）。
与核的形状保真：fold 产物与核 mk_imax/mk_max 的产物逐规则同形——这是
判据一致性的前提（xc 探针证明核不接受"语义等但形状异"的某些对，图
构造点若与核形状分叉，下游 deq 即分叉）。

### 2.5 I_PIS1/I_PIS2 换道 + LEVEL 退役

I_PIS1：删 TASK_LEVEL 推入（fr2 三行），A_c=fV0 直传 I_PIL1；根
kind∉1..6 保留 rej 4（lvl_zero..lvl_mvar 六门已备，移进两臂）。
I_PIS2：同法直传 lvl2_root（既有 select 保留）。LEVEL 分发块
（:6006-6031）与 D_SORT2/D_SORT3 死臂一并删除。P_EMIT/I_SORTEM/
pl_prop/G3 零改动。

### 2.6 instantiate（D10，level.cpp:317）——本卡不做，时机已钉

检查路径需要运行期 level 实例化的点：delta value unfold
（type_checker.cpp:577 instantiate_value_lparams，D14）、iota rhs
（inductive.h:106，B13）、infer_constant 声明类型实例化（图侧 §12.7
编码期 E2 特化已覆盖单 use-site）。三者在 M-C 三探针与 decl_injection
语料均不触发（PG2 的 ERR 4 出在 infer_pi 的 LEVEL 扫描，不是实例化）；
level-blind 归约下数值行为不变（卡 017 D14/B13 分诊）。**通道就绪性**：
本 ADR 落地后 Param=nid 可寻址 + T_ENV_UNIVPARAMS 名字链已在库
（expr/tokens.py:92），B13/D14 立卡时做"unfold 单步替换"，届时须复刻
D10 重建路径的 update_max 智能构造（level.cpp:301-315）。运行期
T_LVLSUB 环境链维持被拒（ADR 022，§12.7 因子树指数复制实测）。

## 预算（实测校准）

| 项 | 实例数 | dims/实例 | lookups/实例 | 小计 dims | 小计 lookups |
|---|---|---|---|---|---|
| max_branch（multiset2 779 + imax 臂 ~180） | 6 | ~960 | ~52 | ~5.8k | ~312 |
| n2z 双侧 @deq_sort（packed cap 4） | 1 | ~490 | ~30 | ~0.49k | ~30 |
| I_PIL2 fold | 1 | ~525-600 | ~45-55 | ~0.56k | ~50 |
| I_PIS1/I_PIS2 换道 + kind 门 | 2 | ~20-40 | ~3-5 | ~0.06k | ~8 |
| LEVEL/D_SORT2 退役回收 | −1 | −(40-80) | −(3-5) | −0.06k | −4 |
| 杂项布线 | — | — | — | +0.2-0.5k | +20-40 |
| **合计（点估）** | | | | **+7.0k-7.6k** | **+416-436** |

**总预估 +6.5k-9.5k dims / +0.4k-0.6k lookups**（点估 7.0-7.6k + 集成
带宽：n2z 实测残差 2.4%-3.7%，25% 上界系设计拍自定的保守集成余量，
审核 H2 指出原 8.5k 上沿与 25% 合成不一致——现按 9.5k 闭合）。校准链：primitives 实价 reglu=1 dim /
_eq_expr=3 / _kind_eq_raw=3 / _select=2 / fetch=1 lookup（同位 N 字段
打包同价）；n2z cap8 复刻件 4,084 dims/765 lookups ×2 消费点 = 8,168/1,530，
对卡 015 实测 +8,369/+1,588 残差 2.4%/3.7%。原型件与 build_vm 同
primitives 集，per-实例数即实现成本直接计量（原文存卡 018 §5.2，
脚本 /tmp/018design/proto_circuits.py）。
对照：卡 017 预估窗 +8k-18k / +2k-4k——点估双指标低于下沿，9.5k 上界
贴近下沿（multiset 替代 2^depth 配对树、fetch 打包，是方案收益不是
欠账）；最贵单电路 ~960 dims，对照 n2z cap8 实测 4,084/单电路
（卡 018 §4 自定参照，非 ADR 022 原文）量级正常。

## 被拒方案（全部带为什么不）

1. **继续纯编码期特化**（ADR 022 已拒，维持）：PG2/PG3/PG6 都是运行期
   判定分歧（CHECK 时的 infer_pi/deq），use-site 才知的比较无法前移。
2. **完整 D5 normalize 全序**（ADR 022 已拒，维持 + 新证据）：is_norm_lt
   的排序键是 interned level_id（level.cpp:407；2026-10-13 复核勘误，
   非字典序），图 nid 整数比较不可复现
   （复现需 interned-id 对照电路，且等价判定本不需全序——只需多重集相等），
   "照抄排序"不可实现且是纯开销。
3. **2^depth 配对比较树**（_lvl_eq 原注释惧怕的形状，本拍显式否决）：
   cap 8 下每实例 ~255 配对节点 ×~10 dims/节点 ×17 实例 ≈ 43.4k dims
   （审核 H1 补 per-node 因子），超卡 017 预算窗上限 2.4 倍；multiset 以
   ~960/实例替代，语义覆盖经探针 oi/nm/sn 钉死等价。
4. **"照抄 n2z 全套"**（把 eq_canon 做成 n2z 的镜像、cap 8、全消费点）：
   n2z 是单树判零（无配对），eq_canon 是双树配对——cap 8 配对即被拒案 3；
   packed cap4 双侧 488/点 ×17 ≈ 8.3k（真 cap8 双侧 = 17×8,168 ≈ 139k，
   审核复核算术）——只服务 imax 归零类，
   而该类在链位语料为 0（§5.3），仅 deq_sort 一处 cap 4 即覆盖探针 iz。
   "为什么不照抄"：n2z 的 cap/部署点是它的判定面（is_prop 全 sort）定的，
   eq_canon 的判定面（deq）与它不同构。
5. **frame 化（TASK 式）level 比较/归一**：dims 更省但引入新任务种类、
   resume 机制与 defeq 热路径上的额外步数；所选 cap 下电路 ~1k dims/实例，
   frame 机制同量级且新增失败面。若未来帽须长到深度 ≥5 再复评（旋钮
   已记，卡 018 §3.2）。
6. **"更聪明"的等价**（接受核所拒的语义等形，如 xc 对）：探针 xc 实证
   核一次性 normalize 的形状保真边界，超收即与真核判定不一致（铁律 1）。
   图的等价判定集合 ⊆ 核集合，方向只能向"少接受"残缺（§残余）。
7. **独立 n2o（normalizes-to-one）电路**：核无此函数（is_one 是语法
   判据 level.cpp:106-110）；"归一到 1"类等价由 eq_struct 的 Succ 腿 +
   multiset 的显式归并覆盖（PG6 的 max(1,1)=1 走归并），专设电路是
   死重。
8. **运行期 T_LVLSUB 环境链**（ADR 022 已拒，维持）：§12.7 实测因子树
   指数复制；B13/D14 未来卡走"unfold 单步替换"。

## 残余（sound-incomplete，全部判异方向；进 VM_SPEC §16 残余段）

1. imax 子形归一（探针 isb：核 OK / 图拒）——n2z 双侧盖 imax 归零类，
   其余子形归一等价拒。暴露面：raw 注入的非常形 imax（M-C 口径可避）。
2. 链位 ≥2 与 deq_sort 深度 ≥2 的 canonical 比较（保持纯结构）。
3. max 摊平深度 >2（≥5 实参或两侧同嵌）。
4. succ 脊 >3 的 (base,k) 视图（越帽判异）。
5. multiset 槽内嵌套 Max/IMax 实参只 pos_eq。
6. fold 的 m4 吸收 pos_eq 版（跨副本同形吸收漏 → 发射冗余 max 节点，
   语义不变，下游 canonical 可兜）。

## 验收与回归（卡 018 §6/§7 全文为准）

拍 B1（deq 判据）→ 拍 B2（LEVEL 换道 + fold）→ 拍 B3（回归 + 收口）；
验收线 = PG2/PG3/PG6 转 ACCEPT + 卡 018 §5.1 十一行探针图侧逐行一致
（负向 sn/xc 必须仍拒、残余 isb 按拒登记）+ decl_injection 零破线 +
#LEVEL 37/37 + 23 套件 + 引擎 34/34 + 硬编码扫描零新增 + dims/lookups
实测落 ARCHITECTURE。oracle 期望一律 §5.1 现跑原文，禁预置。

## 探针证据（4.33.1 现跑，2026-10-04，连跑两次一致；脚本
/tmp/018design/probe018.py，run_kdecl_oracle 通道）

```
== run_kdecl_oracle (4.33.1, 2026-10-04) ==
  neg1     declTypeMismatch     # 负控
  p3_d0    OK                   # PG3 形：Sort(max 1 (succ u)) := ax:Type u
  p6_d1    OK                   # PG6 形：Sort(succ (max 1 1)) := ax:Type 1
  m5_sb    OK                   # mk_max 规则5：Sort(max (succ u) u) := ax:Type u
  oi       OK                   # 序无关：max (succ u) (succ v) =?= max (succ v) (succ u)
  iz       OK                   # imax 归零：Sort(imax 1 0) := True
  sn       declTypeMismatch     # 负向钉：Sort(max 1 u) ≠ Sort u
  isb      OK                   # imax 子形归一：Sort(imax u (max u 0)) := ax:Sort(imax u u)
  nm       OK                   # 嵌套摊平：Sort(max (max u v) u) := ax:Sort(max u v)
  xc       declTypeMismatch     # 跨类钉：Sort(imax (succ u) 1) ≠ 值型 Sort(max (succ u) 1)
  pg2      OK                   # PG2 形 raw decl：Pi(x:Sort(succ u)) Sort(succ u) := λx.x
```

通道要点（复现用）：#KDECL 案例间 env 不互通（模板 addDecl 结果不回写
meta env），共享常量放 DEFS 前导；`succ` 不是 Level 源语法（用 `(v+1)`）；
`Lean.mkConst` 的 level 实参是 `List Level`；raw axiom 注入用
`#eval Lean.addDecl (.axiomDecl {...})` 单行结构实例（ADR 021 方法）。

图基线与原型计量原文：卡 018 §5.2（baseline 34671/4527；n2z cap8 复刻
4084/765；max_branch 779/44；fold 525/45；_lv_view 38/4；_n2z_or 137/7）。
