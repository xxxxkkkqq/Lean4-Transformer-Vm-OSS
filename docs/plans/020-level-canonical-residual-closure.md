# 任务 020：level canonical 残余收口（hargs 差分收口 + imax 子形 zero-elim + canonical-by-construction 设计）

状态：**CLOSED（2026-10-14，总控收口）**：拍 A 全绿（lvl 17/17+0
xfail、decl 全语料 132/132+1xfail、level 37/37、stepgraph 84/84、
引擎 34/34+meta、dims +3,672 窗内、消融因果性三证齐、独立复核五门
PASS）；23 套件里程碑回归 23/23 rc=0（3 例池帽杀经 solo 真值闭环 +
帽校准，见 §6 尾项）。上游：卡 018 CLOSED 的三件遗留（deq_hargs 链步臂差分
NOT-VERIFIED、VM_SPEC §16.10 残余清单、23 套件里程碑出口）+ ADR 025
扩展旋钮条款（"扩展须以语料/探针证据驱动"）。

## 1. 目标（三件）

1. **deq_hargs 链步臂差分收口**：`lvl_hd` 正向行（Regular-hints def 头
   `k18W.{l1}` vs `k18W.{l2}`、链 [max (succ u) u] vs [succ u]，oracle
   OK）+ `lvl_hd_sn` 负向行（链 [max 1 u] vs [u]，oracle
   declTypeMismatch——防过收，sn 类）。消融取证（hargs 臂 struct-only
   变体下步数差）记录臂的因果性。
2. **ADR 025 残余 1（imax 子形归一）收口**：`_lvl_max_canon` 的 imax 臂
   子比较加 zero-elim 腿——kernel normalize 递归进 imax 子（
   `level.cpp:461-467`），证据形状 `max(x, 0) ≡ x`（explicit k=0 被
   存活实参吸收，`:487-499`）。`lvl_isb` 翻 PASS，按 XPASS 协议摘
   KNOWN_GAPS。残余更新：zero-elim 类关闭；更深子形（imax 子内
   `max(u,u)≡u`、嵌套 zero）无证据继续登记。
3. **canonical-by-construction 设计落 ADR 026 草案**（残余 2-5 的
   数学解，不在本拍实现）：encoder 侧全量 normalize + fold 规范发射
   → 图内 level 全规范 → deq 比较降为 struct + n2z → 6 实例 canonical
   臂退役（图缩 ~7-9k dims，估算以拍 B 实测为准）。

## 2. 依据（kernel + 文献，全部可复核）

- kernel：`K/level.cpp:454-516`（normalize 全文——IMax 支
  `:461-467` **递归 normalize 两子后过 mk_imax**；Max 支全量摊平 +
  `:477-499` explicit subsumption：explicit k 被任一 offset ≥k 的
  存活实参吸收，`max(u,0)` 的 k=0 被 u(offset 0) 吸收 → 归一为 u）；
  `:518-521`（is_equivalent = 一次 normalize 比较）；`:81-123`（D1/D2）。
- 文献（构造期 canonical form 的内核先例）：
  - **Coq/Rocq kernel** `kernel/univ.ml` Universe 模块：
    `(* Invariants: non empty, sorted and without duplicates *)`（:266
    附近）——algebraic universe 以"排序去重"为**构造不变量**
    （`Expr = Level.t × int`，Hashcons.Make hash-consed），比较在
    canonical 形上做（`Expr.compare` 先 offset 后 Level.compare）。
    即：内核可以不等任意形状、只等规范形——前提是**构造期**维护规范。
  - **Lean kernel**：mk_max/mk_imax 智能构造在构造期归一
    （level.cpp:81-123），is_equivalent 比较期懒 normalize（:454-521）；
    runtime 层 lean_level_mk_* 经 extern（:30-33）走 runtime 对象层。
  - 代数面：level 的 max 是 **AC + 幂等 + 0 单位元**（ACI），显式
    succ^k(0) 有吸收律；canonical form = 任一固定全序下排序去重的
    实参集 + explicit 合并，**等价判定 ⟺ canonical 相等**（与排序键
    选择无关——这正是卡 018 免排序 multiset 论证的镜像：multiset 相等
    ⟺ 任意固定序下 sorted 相等）。imax 角：imax(a,b) = b≡0 ? 0 :
    max(a,b)（D2），可判定子=n2z。
- 探针/行证据：`lvl_isb`（卡 018 §5.1，oracle OK / 图拒 = 残余 1 的
  常驻差分行）；§16.10 残余文本自身。

## 3. 拍次与验收

**拍 A（本拍）**：

- A1 hargs 差分行：prelude 加 `def k18W.{v} : Type v → Type v :=
  fun x => x` 与 `axiom k18E.{v} : k18W.{v} k18P.{v}`；行
  `lvl_hd`（declared `k18W.{max (succ u) u} k18P.{max (succ u) u}`，
  value `k18E.{succ u}`——头部同 cid Regular def、链步 0 canonical
  臂决定）与 `lvl_hd_sn`（declared `k18W.{max 1 u} k18P.{max 1 u}`，
  value `k18E.{u}`——链不等，oracle 拒）。
- A2 imax zero-elim 腿：`_lvl_max_canon` 内加 `_ze(x, y)`（x 是
  KL_MAX ∧ 某子为 KL_ZERO → 另一子 struct-eq y；双向；both-zero 由
  survivor=zero 子自然覆盖）；imax 臂子比较 =
  struct ∨ zero-elim。预算：每臂组 ~+500 dims，6 组合计
  **+2.5k-4.5k dims**（实测落账；超窗停手复核）。
- A3 回归与文档：lvl 节全绿 → decl_injection 全节 → level 37/37 →
  stepgraph 84/84 → 重编译 `step_vm_020_scratch` + 引擎 34/34+meta →
  硬编码扫描 → VM_SPEC §12.8（imax 臂描述）/§16.10（残余 1 处置）/
  KERNEL_COVERAGE D4 注 / ARCHITECTURE 020 行 / ADR 026 草案 / handoff。
  23 套件全量在拍 A 收口后按里程碑口径跑（受影响集先行的证据链
  已含上面五件）。

**拍 B（后续独立卡，ADR 026 实现）**：encoder normalize（expr/tokens.py
level 子树全量归一——非 E2 式特化、无复制爆炸；ADR 022 的被拒案是
"use-site 特化复制"，本方案是逐节点语义保持改写，区别落 ADR 026）+
fold 规范发射（nid 全序发射 + mk_max merge 完备）→ canonical 臂退役
→ 全量 23 套件。风险登记：stepgraph_vs_refvm 的步数一致面（encoder
改写后图内步数可能变，需 pinned 项复核）；B13/D14 落地时实例化必须
走全量 normalize 重发射（保持"图内 level 全规范"不变量）。

## 4. Verifier 集（完工唯一依据）

- [x] `G02_ONLY=lvl` 全绿：`lvl_isb` **PASS**（摘 KNOWN_GAPS），
      `lvl_hd`/`lvl_hd_sn` 与 oracle 一致；全节 17/17 0 fail（`lvl_a.log`
      原文在"拍 A 记录"）
- [x] 消融取证原文：hargs struct-only 变体下 `lvl_hd` 步数差 > 0
      （臂因果性 25↔33）；正常图下 verdict/步数原文落卡。
      **复核意见 #2 处置**：消融脚本为一次性探针未持久化（AGENTS §4
      "成为证据须落库"按字面适用于 harness——如实注记：方法 = 单参数
      变体 `LVL_CHAIN_DEPTH, 2→0`（.scratch sed 副本，分钟级可重建），
      原文 4 行在 §6；裁决级证据（hd/hd_sn 常驻行）已永久在库，复核
      认定此记账诚实）
- [x] decl_injection 全节 0 fail（132/132+1xfail，xfail 只剩 ipr_dep_snd）
- [x] level_vs_lean 37/37；stepgraph_infer_defeq 84/84（3738.6s rc=0）
- [x] 重编译 `step_vm_020_scratch.sbin` dims 记账（+3,672/+504 窗内）
      + 引擎 34/34 + known 3/4 + meta OK（1204.5s/312MB）
- [x] 硬编码扫描零新增（build_vm 增行 30 行零命中；k18W/k18E 为测试
      语料数据非图分支）
- [x] 文档四件同步 + ADR 026 草案在库 + 卡 018 §16.10 残余清单更新
      （residual 1 收口、2-5 立结构性解、ADR 026 草案）
- [x] 23 套件全量（里程碑口径）：**23/23 rc=0**——池内 20 套件 rc=0
      （`~/logs/020/reg/`，2026-10-13 波次）；3 套件池帽杀（非语义）经
      solo 真值跑闭环：`stepgraph_vs_refvm` solo rc=0 1476.7s/588MB
      （37/37，帽 1200→2000）；`brec_drec` 三级爬帽后真值 rc=0
      1277.0s/**10575MB**/0 divergences（帽 8000→12000）；`defeq_cache`
      真值 rc=0 2505.4s/**10565MB** ALL OK（帽 2700→3600、8000→12000）。
      RSS 增长归因 = 图 dims 012 时代 ~33k → 020 49.3k（+50%），
      帽校准三条已落 `scripts/run_cpu_regression.sh`（a0d18cb 格式，
      实测依据在注释）。事故记录：原 solo 看守器死锁（pgrep 模式匹配
      自身祖先命令行，AGENTS §三 pgrep 坑的镜像），总控接管重跑链
      （`~/logs/020/reg_solo/chain.log` 全程留痕）。

## 5. 触碰面

拍 A：`lean_vm/build_vm.py`（仅 `_lvl_max_canon` 的 imax 臂 zero-elim
腿）、`tests/test_decl_injection_vs_lean.py`（prelude/roots/lvl_hd×2/
KNOWN_GAPS 摘 isb）、`docs/VM_SPEC.md` §12.8+§16.10、
`docs/KERNEL_COVERAGE.md` D4 注、`ARCHITECTURE.md` 020 行、本卡、
`docs/decisions/026-*.md`（草案）、handoff、`.scratch/`（消融脚本，
取证后删）。**禁触**：`lean_vm/ref_vm.py`、`expr/tokens.py`（拍 A 零
编码变更）、`engine/*` 源码、`compiler/*`、`model/` 源码。

## 6. 拍 A 记录（2026-10-13，总控亲执）

### 实现记录

- **A2 zero-elim 腿**（`build_vm.py:3411` `_lvl_max_canon`，:3543 `_ze`
  / :3554 `_child`）：`_ze(x,y)` = x 是 KL_MAX ∧ 某子 kind==KL_ZERO
  （`_geq_expr` 合并）→ survivor = `_select(x1_zero, x0, x1)` →
  `_lvl_eq_struct(surv, y, 4)`；双向 OR（prioritized merge 保 0/1）；
  both-zero 由 survivor=zero 子自然覆盖（`max(0,0)≡0`）。imax 臂子
  比较改 `_child` = struct ∨ zero-elim。6 实例共享函数，一次改动
  全部署。**dims 实测 +3,672 / +504 lookups**（49,347/6,119），预算窗
  +2.5k-4.5k 内。
- **A1 hargs 行**（tests：prelude +`k18W`（Regular-hints def 头）+
  `k18E`（其应用类型的 axiom）；行 `lvl_hd`（链 [max (succ u) u] vs
  [succ u] 正向）+ `lvl_hd_sn`（链 [max 1 u] vs [u] 负向防过收））。
  KNOWN_GAPS 摘 `lvl_isb`（A2 使其翻 PASS，XPASS 协议强制摘除）。

### 验证记录（原文，~/logs/020/）

```
$ G02_ONLY=lvl ... test_decl_injection_vs_lean.py        # lvl_a.log
lvl   card 018 symbolic level channel: ... vs live #KDECL oracle
  [PASS] lvl lvl_isb: oracle=OK graph=accept=True code=0(accept) steps=11
      # 残余 1 收口：原 XFAIL-KNOWN-GAP 行翻 PASS
  [PASS] lvl lvl_hd: oracle=OK graph=accept=True code=0(accept) steps=25
  [PASS] lvl lvl_hd_sn: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=55
  ...（十五行卡 018/019 既有行全部保持 PASS，原文 lvl_a.log）
=== card 010 G02 decl-injection differential: 17/17 checks pass, 0 xfail known-gap, 0 fail (457s) ===
[mem-guard] wall 457.2s peak RSS 1519MB rc=0
```

**消融取证**（.scratch/ablate_hargs.py，hargs 链门 canon_steps 2→0
的变体，取证后删）：

```
normal lvl_hd:    accept=True code=0 steps=25
ablate lvl_hd:    accept=True code=0 steps=33   # 臂关掉后走 delta 展开绕路
normal lvl_hd_sn: accept=False code=1 steps=55
ablate lvl_hd_sn: accept=False code=1 steps=55  # 负向两侧同拒同价
```

+8 步差证明 canonical 链臂在正常图**因果点火**（快路 25 步 vs 绕路
33 步），负向行两态同拒——臂无过收。deq_hargs 链步臂 NOT-VERIFIED
据此收口（正向差分 + 负向钉 + 因果性三证齐）。

### 复跑账目（A3）

| 项 | 结果 | 证据 |
|---|---|---|
| #LEVEL 通道 | **37/37**（1.5s / 1435MB / rc=0） | `level_020.log` |
| 重编译 --sparse | `step_vm_020_scratch.sbin`：49,347/6,119/nnz 315,874、28,554,782B、md5 `7363b960...` | `compile_020.log` |
| 引擎 meta | **OK（76 output dims, 13 token consts）** | `engine_meta_020.log` |
| 引擎对拍 | **34/34 + known 3/4**（SBIN 自证行在日志首） | `engine_020.log` |
| decl_injection 全节 | **132/132 checks pass, 1 xfail known-gap, 0 fail**（6942s；xfail
      仅剩 `ipr_dep_snd`——isb 已翻 PASS；`lvl_hd` accept=25 步、
      `lvl_hd_sn` 拒 55 步、`lvl_isb` PASS 全语料内复现）。帽注：总控
      solo 直跑 7800s 头余（pkill 自匹配事故后沿用首启进程；018 时代
      实测 6382s + m8 邻居负载 +2 lvl 行），回归脚本池帽 7200 未动
      （6942s = 96% 池帽，池跑需盯）。mem-guard 尾行未落 log（事故后
      首启包装进程的 stderr 去向异常），wall 以汇总行原文为准、RSS
      峰值未记录——如实登记 | `decl_full.log` |
| stepgraph_infer_defeq | **84/84 (0 pinned)**、rc=0；wall 3738.6s / RSS 609MB（018 基线
      3420.9s → +9.3%，m8 邻居训练负载；帽 4500 内） | `stepgraph.log` |
| 硬编码扫描 | 卡 020 delta（HEAD vs afe652c）：zero-elim 腿与测试行扫描——**零具名常量/cid 分支**（KL_* 仅 kind 标签判据；k18W/k18E 是测试语料数据非图分支） | 会话现场 grep |
| 23 套件全量 | 收口后按里程碑口径跑（待回填） | — |

## 7. 决策引用

- 卡 018（CLOSED）§3.4 残余清单 + §16.10——本卡收口 1 项、设计 4 项
- ADR 025 §2.3（imax 臂 = 有序 struct 配对；子形归一登记残余）+
  扩展旋钮条款（探针证据驱动）
- ADR 022（被拒案"纯编码期特化"= use-site 复制爆炸；ADR 026 将区分
  "逐节点 normalize 改写"与之不同，未动该 ADR 结论）
- Coq kernel universes（canonical-by-construction 先例）+ Lean
  level.cpp normalize（懒归一的对照设计）
