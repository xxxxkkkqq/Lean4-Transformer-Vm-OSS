# ADR 026：level canonical-by-construction（编码期全量归一 + 规范发射 → 比较降级）

状态：**ACCEPTED（2026-10-14，卡 021 拍 B 实现收口）**：三构造边界
（encoder normalize + Sort 级 succ 影子 + I_PIL2 case-A union-rebuild
含 3 幸存者 2-beat 发射）落地，lvl 节 32/32（含 15 探针常驻行，含
lvl_xc 不对称钉）、kernel_oracle Part A 10/10 + 容量 3/3、引擎 34/34
+known 3/4、dims 实测 58,445/7,676/362,418（**净增长 +9,098 dims**——
§3 的"净缩 −6k±2k"预估被实测推翻，mm 递归腿与 fold 重建电路的增量
超过臂退役的节省；按 §6"以拍 B 实测为准"条款如实记账，实质收益 =
残余 2-5 的结构性清偿与 M-C/M-D 的形状完备）。拍 B 期间的三个
机制修正并入本 ADR：① 草案 §3.2 的"两臂 select"被否证（union-rebuild
必需，见 §3.2 修订）；② **臂与 encoder normalize 不可共存**（臂对
规范形二次 normalize 假收，lvl_xc B1 实证）——退役必须与接线同一提交；
③ Sort 级 succ 影子为第三构造边界（草案漏列，infer_sort 的运行期
succ 分配律）。
上游：卡 018/ADR 025 的 sound-incomplete 残余清单（VM_SPEC §16.10
第 2-5 条：部署深度帽）+ 本 ADR 的中心论点。

## 1. 问题

ADR 025 的有界 canonical 比较把 kernel normalize 电路化，深度帽
（摊平 2 层 / succ 脊 3 / multiset 槽内 pos_eq / 链步 0-1）由语料
证据钉死。帽的成因是架构性的：图无递归/共享，每个调用点复制整份
电路（6 实例 ≈ 9.6k dims），加深 = 每级 ×6 的成本乘法，"完整
normalize"被 ADR 022 以 ~44k dims 否决。残余因此永远跟随语料走，
M-C 每暴露新形状就要一次加深拍。

## 2. 论点（kernel + 文献先例）

**内核不给任意形状维持全序比较——它们把规范形做进构造期。**

- **Coq/Rocq kernel**（`kernel/univ.ml`，Universe 模块）：
  `(* Invariants: non empty, sorted and without duplicates *)` —
  algebraic universe（Level.t × offset 的 max 集）以"排序去重"为
  **构造不变量**，Expr 经 Hashcons 共享；比较（`Expr.compare` 先
  offset 后 Level.compare）只发生在规范形上。内核不比较任意形状，
  因为构造路径保证形状规范。
- **Lean kernel**：mk_max/mk_imax 智能构造在**构造期**归一
  （`level.cpp:81-123`）；is_equivalent 的 normalize（`:454-516`）是
  比较期的兜底，其输出同样是排序去重的 max 集——即两个内核殊途
  同归：**规范形 = 任一固定全序下排序、去重、吸收完毕的实参集 +
  合并 explicit 偏移**。
- 代数骨架：max 是 **AC + 幂等 + 0 单位元**；显式实参 succ^k(0) 被
  同 base 或 offset≥k 的存活实参吸收（`:477-499`）。因此
  **等价 ⟺ 规范形相等**，且规范形对排序键的选择不敏感（multiset
  相等 ⟺ 任意固定全序下 sorted 相等——卡 018 免排序论证的镜像，
  也解释了为何两个内核用不同的键仍判定一致）。imax 角
  imax(a,b) = b≡0 ? 0 : max(a,b)（D2 :112-123），可判定子 = n2z，
  已在图内。

## 3. 方案（canonical-by-construction）

图内 level 的三个产生边界全部产出规范形：

1. **Encoder（静态边界，`expr/tokens.py`）**：编码期对每棵 level
   子树做全量 normalize（摊平任意深度、zero-elim、explicit 吸收、
   同 base 合并、**按 nid 整数全序排序去重**——本仓库自己的固定
   全序，不复现内核的 interned level_id 序，也不需要：等价判定与
   键无关）。Python 侧无深度限制——残余 3/4（摊平帽、succ 帽）对
   静态形状直接消失。
2. **Fold（运行期边界，I_PIL2）**：**拍 B 修订（探针+扫描实测，卡 021
   §2）**——草案的"KL_MAX 发射按 nid 取 V0=min/V1=max（两臂 select，
   ~10 dims）"**不充分，已被否证**：运行期构造的 kernel 对应项是
   `mk_imax → mk_max` 裸构造（max 顶），比较期 normalize 走 **Max 支
   全量摊平**，故图侧 fold 的 case A（is_not_zero(l2)）输出必须等于
   **union-rebuild**：`split(l1) ∪ split(l2)` → 排序（kind 序
   Zero<Succ<Max<IMax<Param<MVar，即 KL_* 编号；Param/MVar 按 nid；
   再 offset）→ explicit 吸收（幸存 offset ≥ k 时丢弃最大 explicit，
   :487-499；吸收可把结果塌缩到**单节点 = 既有 position**，探针 pF1）→
   同 base 去重保大 offset → 右折叠重建（:508-509 buffer 语义）；3
   幸存者时 2-beat 发射（P_EMIT 相位扩展，图内数据无格式变更）。case B
   （is_not_zero(l2) = 0）保留 kernel mk_imax 逐规则精确语义（imax 路径
   的 pairwise 结果就是规范形——设计验证器全语料 1497 链 0 mismatch）。
   忠实移植含 **succ 分配律**（normalize 的 Max 支把 succ 脊柱逐幸存者
   重包，:449-453+:507-509：`normalize(succ (max u v))` =
   `max (succ u) (succ v)`——探针 pF4i 实证）。槽预算实测：侧 A
   （domain sort level）恒 1 原子（477/477）、侧 B（链累积）≤3、
   union ≤4、幸存者 ≤3（12 次全部来自 Vector3 闭包类型 = M-C 必踩
   形状）；Max/Imax 基互排无语料证据 → 超预算（union>4 或基对不可
   序）回退 pairwise 裸发射 = sound-incomplete（与帽语义同向）。
3. **比较降级**：图内 level 全规范后，deq 判定回到
   `eq_struct ∨ n2z`（n2z 保留给 is_prop/pl_prop 的 zero 判定）；
   6 实例 canonical 臂（multiset2 + imax 臂，~9.6k dims）退役，
   **图净缩（估 −6k ± 2k dims，以拍 B 实测为准）**。残余 2
   （链步 ≥2 / deq 深度 ≥2）与残余 5（multiset 槽内嵌套）随之
   失去暴露面。

**与 ADR 022 被拒案的区别**（该案维持否决）：被拒的是
"use-site **特化**"——按每 use-site 复制实例化类型，768/779 常量
规模下复制爆炸。本方案是**逐节点语义保持改写**（normalize 输出
≤ 输入规模，无复制）；比较仍发生在运行期（两个操作数在编码期
各自归一，谁与谁比仍由运行期决定——thm_imax 的运行期共享类型读
不受影响，读到的就是规范形）。ADR 022 反例（"动态比较无法前移"）
针对的是把**比较**前移；本方案只前移**操作数整形**。

## 4. 不变量与未来交互（风险面，拍 B 必须逐一验证）

1. **不变量**：任何进入图的 level 节点都是规范形。违反者即残余
   回归——B13/D14（运行期实例化）落地时，instantiate 的 level
   替换必须重跑**全量** normalize（对齐 kernel `:301-315`
   update_max 之外再加排序去重——kernel 的 instantiate 走 mk_max
   智能构造，智能构造**不排序**，kernel 靠 is_equivalent 兜底；
   我们没有兜底预算，必须构造期规范化）。
2. **stepgraph_vs_refvm 步数一致面**：encoder 改写后图内步数/
   token 流可能变（比较提前接受/拒绝），ref_vm 是冻结参照机、按
   内核语义实现 normalize 等价——判定应逐值一致，步数按 016 时代
   "pinned 项"协议核对；不一致即停手分诊。
3. **引检验收铁律**：差分行期望仍全部 oracle 现跑；lvl 矩阵 +
   PG 行 + 018 全语料不倒退。isb/sn/xc 等负向行必须在规范形语义
   下仍拒。**xc 的精确机制（复核后已定，原 ？? 标记解决）**：
   normalize 是**逐路径一次**的——`normalize(imax (succ u) 1)` 走
   IMax 支（:461-467）重建 `mk_imax(succ u, 1)` → is_not_zero(1)
   → **mk_max 裸构造** `max(succ u, 1)`（mk_max 智能构造**不重跑**
   normalize 的 explicit-subsumption——succ u 的 offset 1 本可吸收
   explicit 1，但 imax 路径不再摊平）；而 `normalize(max (succ u) 1)`
   走 Max 支摊平+排序 → explicit 1 被 succ u(offset 1 ≥ 1) 吸收 →
   `succ u`。两路径产物**结构不等**（`max(succ u,1)` vs `succ u`）→
   is_equivalent FALSE → xc 拒。**推论（拍 B 的硬约束）**：encoder
   normalize 必须是 level.cpp normalize 的**忠实逐行移植**（含
   imax/max 路径不对称——"逐路径一次"语义），**不是**理想化 ACI
   规范形；xc 行就是钉死这一点的回归测试。Coq 先例成立的原因是
   Coq 的比较本来就定义在其构造不变量上；Lean 的 normalize 有一次性
   不对称，必须照抄而不是"数学化"。sn 同理成立：max(1,u) 规范形
   保留 {1,u} ≠ {u}（吸收条件 offset≥k 不满足）→ 拒 ✓。
4. **公平性红线**：encoder normalize 是通用语义保持改写（对任意
   常量名/cid 一致生效），不预设答案；差分期望仍由 oracle 现跑
   产生。满足验收铁律 2/3。

## 5. 被拒替代

- **维持现状（ADR 025 帽 + 证据驱动加深）**：每形状一次加深拍，
  成本线性于语料暴露；M-C 前有效，M-C 后不可持续。
- **图内全量 normalize 电路**：ADR 022 已拒（~44k），维持。
- **比较结果缓存/哈希通道**：图内无运行期哈希基础设施（无比较/
   存储回路），引入即 ADR 022 的 T_LVLSUB 同型爆炸。

## 6. 判据与拍 B 出口

- 完工 = lvl 矩阵 + decl_injection 全节 + stepgraph + 引擎对拍
  全绿（oracle 现跑），图 dims 实测净减，VM_SPEC §12.8/§16.10、
  KERNEL_COVERAGE D 组行同步，本 ADR 状态翻转 ACCEPTED。
- 任何负向行翻 ACCEPT 或正向行翻 REJECT = 规范形语义实现有错，
  停手分诊（对齐 kernel normalize 逐规则比对）。
