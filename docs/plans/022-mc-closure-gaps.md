# 任务 022：M-C 实测四缺口收口（binder-identity defeq + stepgraph 闭合缺口）

状态：**open（2026-10-15 立卡，总控）。依据 = 卡 012 M-C 首轮全量差分
（`tests/test_mathlib_closure_vs_lean.py` 35 行四通道，~/logs/012MC/）——
真 mathlib 闭包首次过 CHECK 通道，15 行分歧，四个根因组（A/B/C/E），
每组都有行级证据链。修复后按 XPASS 协议摘 `KNOWN_GAPS`（15 行全部
常跑，转绿即摘）。

**拍 2 已收口（2026-10-23）**：A 组 9 行中 8 行 × graph/refvm/engine 三通道全绿；
唯一红行 `q_acc_thm` 图/引擎两侧同面（quot reduct 的 `infer_app`）→ **卡 024**，
参照机已绿。拍 2 的实际内容与 ADR 028 §1.6/§1.7 的立卡假设不同（两残差不属
A 家族：冻结机缺 quot 归约、`infer_proj` 缺头剥离/参数实例化），另在引擎侧
发现并修复了位置取指的 fp32 悬崖（ADR 027 补条款）。证据与行表见本卡
「执行段（拍 2）」；不变性门 84/84、37/37、34/34、五 canary 全绿。
**拍 3 + 拍 4 已收口（2026-10-23）**：E 组 INFER MData 臂落地（`v_acc_natadd`
转绿）、B 四行三通道绿、C `q_tnp` 转 8；15 条 `KNOWN_GAPS` 全摘，35 行 ×
4 通道**全绿（0 FAIL / 0 XFAIL / 0 XPASS）**，mathlib 按 closure 三分段
（卡 025）帽校准；引擎对拍 34/34、84/84、五 canary 全绿。余项 = 26 套件
全量回归（`regression26` 盒执行中）。q_acc_thm 的 quot 交付修复见卡 024。

## 目标

真 mathlib 闭包差分暴露的四个判定缺口全部收口，使卡 012 M-C 的 15 个
gap 行与真 lean 一致（判定 + 错误类别逐例对齐），M-D 规模差分不再被
判定缺口挡路。

## 依据（实测，2026-10-15，~/logs/012MC/ + .scratch/dbg_mc_*.py）

### A · binder-identity bvar defeq（graph+RefVM+engine 三通道共有，9 行）

**现象**：一切「lambda 内变量实参过常量头」的真证明（`f x`、
`Eq.refl α a`、`f (g x)`、`h.left`）在 CHECK 的 infer 阶段死于
declTypeMismatch——三通道一致 code 1，oracle OK。

**根因证据链**（`.scratch/dbg_mc_bid.py`，rfl 重加最小复现）：

1. 失败的 defeq 对两侧**解码后逐字相同**：`Sort(u)` vs `Sort(u)`
   （`.scratch/dbg_mc_defeq.py` 唯一失败对）。
2. 两侧都是 BVar，沿各自 env 链解析到**同一个 binder marker link 行**
   `(31, 77, 0, 0, 0, 1, 0)`（T=BVar(0)@112 与 S=BVar(1)@113 双双
   resolve 到该行，`.scratch/dbg_mc_chain.py`/`dbg_mc_bid.py` 原文）。
3. ref_vm.py:1144-1157 的 bvar-bvar 分支只认**非零 bid**
   （`lt[6] and lt[6] == ls[6]`）；bid 只在 defeq 的 binder 比较分支
   被 stamp（`_stamp_bid`，ref_vm.py:1152-1154），**infer_lambda 从不
   stamp**——纯推理路径的 marker 全部 bid-less。
4. **kernel 对照**：`is_def_eq_easy` 首行 `if (t == s ...) return
   l_true`（K/type_checker.cpp:837-838）——同一表达式（同一 local
   decl）短路相等。流内同一 marker link 行即该恒等式的 stream 对应物；
   现行分支漏掉「同一行」恒等，把一个 binder 当两个 fvar。

**影响面**：真实 mathlib 证明全量（每个 `f x` 都过这条路）——M-C 的
9 个 accept 行（q_acc_def/q_acc_thm/q_acc_rfl、q_lvl_maxuu/maxu0/
max0u/maxuu_2p、n_acc_fcomp、n_acc_thm）。**本组是 M-D 的前置**。

**图侧义务**：图的 DEFEQ 电路同语义缺口（engine 与 graph 同权重同
code 1 为证）。修复合同 = 图内 bvar-bvar 比较把「解析到同一 binder
marker 行」识别为恒等（或等价的 marker 恒等机制），并以最小改动判定
ref_vm.py 冻结条款的适用面（同一恒等的一行短路属"最小内部修复"候选，
是否修由拍 1 定案；不修则登记 channel boundary）。

### B · 宇宙多态 LAM 值 def 的 stepgraph 假拒（graph/engine only，4 行）

**现象**：`id.mc := fun {a : Sort u} (x : a) => x : ∀ {a : Sort u}, a → a`
——RefVM 接受（= 真内核判定），graph+engine 拒 code 1，**83 微步复现，
env 规模无关**（`.scratch/dbg_mc_empty.py`：空 env / {True} / {True,
True.intro} 三态同拒）。**stepgraph 偏离自己的参照机**。
既有语料无此形状：lvl 行是 Const/Pi 值，check_e2e 的 lam 是单态。
行：v_acc_def、n_acc_def_id、v_lvl_maxuu、n_lvl_maxuu。

### C · thm kind gate 对多参数 Pi-sort 类型不点火（1 行）

**现象**：q_tnp（type := Quot.lift 的型，sort level 为含 u/v 的 fold
形）→ graph/engine code 1（值侧失败码），而 gate 应先抛 8；对照：
v_tnp/n_tnp（type := Const("Nat")，concrete sort）两行 graph+engine
code 8 ✓ PASS。gate 的 sort-level 判定（g3 臂/n2z/fold 通道）在多参数
Pi 形上失火或被值侧码抢先——拍 1 需 step trace 定序。

### E · Nat.add 重加的 ERR_UNSUPPORTED（graph/engine only，1 行）

**现象**：v_acc_natadd（value = fun over Nat.brecOn 链）graph+engine
code 4，RefVM 接受，oracle OK。第二处 stepgraph-vs-RefVM 分歧
（B 同类不同点），拍 1 定位具体 unsupported 节点形状（MData/brecOn
链嫌疑）。

## 触碰面（默认；拍 1 依据可修订）

`lean_vm/build_vm.py`（A 的 DEFEQ 电路、B/E 的图臂、C 的 gate）、
`lean_vm/ref_vm.py`（**冻结**——仅 A 的恒等一行短路属候选最小修复，
拍 1 定案）、`tests/test_mathlib_closure_vs_lean.py`（摘 gap）、
`tests/test_decl_injection_vs_lean.py`（如需新增常驻差分行钉住各缺口）、
`docs/VM_SPEC.md`（§7.4/§12 相应节）、`docs/KERNEL_COVERAGE.md`、
本文件、handoff。**禁触**：`engine/*`（图内数据可表达即无格式变更）、
`compiler/*`、`model/*`、`ARCHITECTURE.md`（总控）。

## 拍分

1. **拍 1 语义设计师**：四组各自的图侧失败点定位（step trace 原文）
   + kernel 引用补全（A 已有 type_checker.cpp:837；B/E/C 待
   `文件:行`）+ 每组的修复合同与 ref_vm 冻结裁决。产出 ADR 草案。
2. **拍 2 图逻辑工程师**：A 组图侧实现 + 最小复现行转绿；五 canary
   + mathlib_closure 套件无回归；重编译 + 引擎对拍 34/34。
3. **拍 3 图逻辑工程师**：B/C/E 组逐个（可分拍），同验证链。
4. **拍 4 测试工程师**：全量回归 + M-C 15 gap 行 XPASS 摘除验证。

## Verifier 集

- [ ] A：9 行 gap 全转绿（graph+refvm+engine 三通道），XPASS 摘册
- [ ] B：4 行转绿；83 步复现形永久化为 decl_injection 常驻差分行
- [ ] C：q_tnp 转 8（与 oracle 类别一致）
- [ ] E：v_acc_natadd 转绿（accept）
- [ ] 五 canary + stepgraph_vs_refvm 84/84 零基线变动（A 触 DEFEQ
      热路径，判定不变性由全套件对拍证明）
- [ ] 重编译 --sparse + 引擎对拍 34/34（若动 build_vm）
- [ ] 硬编码扫描零新增；语义决定带 kernel `文件:行`

## 执行段（拍 2，图逻辑工程师，2026-10-22）

### 拍 2 起点与基线

工作树未提交件 = A1（同链节点恒等，`build_vm.py` D_BV3 + `ref_vm.py`
bvar-bvar）+ A2（`T_PI_CLO.V2` 载体，`build_vm.py` I_LAM BODY stamp / D_XPI2
采纳 / `ref_vm.py` infer stamp + fallback）+ 两枚 decl_injection 钉
（bid_same / bid_distinct）。本拍**不回退**该基线，证据一律重取于
`~/logs/022B3/`，探针 `~/Lean4-Transformer-Vm-OSS/.scratch/dbg022b3_*.py`。

### P1-3 引擎腿 code=-1 定性：**图侧不终止（状态固定点死循环），非时长**

探针 `.scratch/dbg022b3_engine.py`（复刻 suite 的 engine_leg 编码，保留
stdout/rc/wall 原文；`MC_SBIN=model/step_vm_022_scratch.sbin`，
md5 `6a5d0ab377bace0866afba7591b75493`）：

```
# case=q_acc_def closure=Quot_liftOn_mk kind=def env=minimal tokens=373
#   tp=220 vp=372 cap=50000 timeout=600.0s
# RESULT: TIMEOUT after 600.2s        (partial stdout/stderr 均空)   [engine_qaccc_def_min.log]
# argv … check 2000 …
NOT_DONE 2000      (wall 237s)                                        [engine_qaccc_def_cap2200.log]
```

- **不是进程崩溃/rc≠0**：两次运行 rc=0，stderr 零行。
- **不是纯时长**：引擎每步把新 token 打到 stdout；cap=2000 的整段 dump 里
  尾部每一步追加的都是同一个状态行 `33 357 2055 0 3466 0 0`
  （`T_STATE`，A=357 B=2055 C=0 **D=3466** E=0 F=0）——即机器进入
  **一步状态固定点**，任何 cap 都不会自然终止。步率 8.4 步/s，
  50k 步需 ~1.7h，故 cap=50000 必然先撞 600s 墙：TIMEOUT 是固定点
  循环的**症状**，不是预算不足。
- 定性结论：**当图 bug 处理**。首个嫌疑面 = 本拍 A2 新增的 V2 采纳臂
  （`build_vm.py` D_XPI2 `xpi_tpc_v2/xpi_car_bid`）或 I_LAMBODY 的
  `raw_V2_c = _select(cg[I_LAMBODY], SD - One, raw_V2_c)` 指针算术；
  次嫌疑 = A1 位置恒等 OR 臂把异 binder 误判同后继续下行。
  继续定位见下（P1-3b）。

### P1-1 q_acc_thm：根因 = **冻结机缺 quot 递归子归约**（kernel `quot_reduce_rec`）

ADR 028 §1.6 的三个假说（闭包 env 少挂隐式 binder 帧 / 对错误子项求型 /
DEFEQ 帧字段错位）**全部被证伪**；「T 索引比 S 浅 3 层」是 closure 比较的
正常投影（T 侧是 `rfl` 自身类型体在 rfl-binder env 下的闭包，索引按该 env
解读），不是缺陷。

证据链（`~/logs/022B3/thm_trace1.log`、`thm_leaf1.log`）：

1. 判定链 8 个 False，最深节点 `[220] T 414@995 (K1 BVar 0) vs S 664@1034
   (K6 App)`；T 侧 env 995 是**两条 value link**（`[995] V0=863 @905`、
   `[914] V0=741 @905`），whnf(414@995) = `Quot.lift α r β f h (Quot.mk α r a)`
   （已 delta 掉 `Quot.liftOn`，**未做 quot 归约**）。
2. S 侧 = `f a`（`App(BVar1,BVar2)`，正是声明型 `Eq β (liftOn …) (f a)` 的
   第三元）。kernel 判等靠的是 `quot_reduce_rec`：
   `K/quot.h:39-75`（lift mk_pos=5/arg_pos=3、ind mk_pos=4/arg_pos=3、
   主前提 whnf 须为 3 参 `Quot.mk`、reduct = `f (app_arg mk)` + 余参），
   调用点 `K/type_checker.cpp:393-396`（`reduce_recursor` 先 quot 后 iota，
   门控 `env().is_quot_initialized()`）。`grep -i quot lean_vm/ref_vm.py`
   **零命中**：冻结机整族缺失。
3. **决定性反证实验**（`.scratch/dbg022b3_quot_experiment.py`，把 kernel 规则
   按其链接链编码补进 whnf 后重跑，`~/logs/022B3/quot_experiment1.log`）：

```
[vanilla-refvm] q_acc_thm: REJECT 1: VM reject 1: decl 0: value type mismatch  (quot fires=0)
[refvm+quot  ] q_acc_thm: ACCEPT                                                (quot fires=3)
[vanilla-refvm/refvm+quot] q_acc_def / q_acc_rfl: ACCEPT (quot fires=0)   ← 不变性
```

   即 A1+A2 已把 binder-identity 面收干净，残差 100% 由缺失的 quot 归约造成。

### P1-2 n_acc_thm：根因 = **冻结机 `infer_proj` 缺 kernel 的头剥离与参数实例化**；
图侧已 ACCEPT

- **图侧绿**（`~/logs/022B3/nacc_graph1.log`）：`TracedDriver` 跑
  `And.left.mc`（thm）→ **ACCEPT**，197 微步，卡 019 的 I_PROJ 元数据通道
  （IP_TY/IP_PEEL/IP_PK）已能处理 `And` 的两参数 + 依赖字段。故 ADR 028
  §1.7 记的 `infer_proj: structure type expected` 是**参照机腿**的面，
  不是图的（图从来只报 code 1，不带该文案）。
- **ref_vm 面**（`~/logs/022B3/nacc_trace1.log`）：失败叶子
  `[9] Proj(sname='And', idx=0, child=BVar 0)@72`，`infer(child)` 返回
  `(58, 69)` = `And a b`；`whnf(58,69)` 返回 **App spine 根**（K=6），
  而 `ref_vm.py:986` 的 `if sK != K_CONST: raise "infer_proj: structure
  type expected"` 要求**裸常量**。
- kernel 对照 `K/type_checker.cpp:248-289`：`type = whnf(...)` 后
  `I = get_app_args(type, args)`（剥 spine 取头），再要求
  `args.size() == nparams + nindices`，并对前 nparams 个 Pi **用实参
  `instantiate`**（:270-278），随后按 idx 逐字段 peel。参照机当前：
  ① 不剥 spine；② `nparams != 0` 直接 `ERR_UNSUPPORTED`；③ idx peel 无
  依赖字段（`mk_proj`）支路。`And` 是 nparams=2 的归纳族 ⇒ 两条都踩。

### 冻结条款适用性（ref_vm 改动前置声明，纪律要求先写后改）

本轮 ref_vm 改动**只**包含两处 kernel 忠实补全，均属"让 oracle 继续可用"的
最小内部修复（ADR 028 §1.5 先例；不修则冻结机对「以 rfl/quot 计算规则
证明的定理」「参数化结构的投影」整类误拒，M-C 的 accept 行全部落在此类）：

1. **quot 递归子归约**（`K/quot.h:39-75` + `K/type_checker.cpp:393-396`）：
   纯 reducer 补全，无新判定面；门控与 kernel 同（bundle 内存在 Quot 常量
   才点火，对应 `is_quot_initialized`）。实测：只影响 q_acc_thm（fires=3），
   q_acc_def/q_acc_rfl 零点火、判定不变（同 log）。
2. **`infer_proj` 头剥离 + 参数实例化 + idx 依赖字段**（`K/type_checker.cpp:
   248-289`）：把"要求裸常量 + 拒参数化结构"换成 kernel 的
   `get_app_args` + 逐参 `instantiate`；判定方向不变（kernel 拒的仍拒：
   sname 不符 / 非归纳 / 单 ctor 前提不满足 / Prop 保护）。

两处都不引入第二套实现、不新增行类、不改 stream 格式；**不修则两行 refvm
腿永久错拒**。若总控裁定不入冻结条款，回退点 = 本段两条 ref_vm 提交（图侧
不受影响，两行的 graph 腿为绿）。

### P1-1/P1-2 修复落地与 refvm 行级验证（本拍已改，待总控逐行审）

`lean_vm/ref_vm.py` 两处（行号按改后文件）：

1. `__init__`：`self.quot_rec`（`Quot.lift`→(mk_pos 5, arg_pos 3)、
   `Quot.ind`→(4,3)，按 bundle 名字解析 cid，无数字 cid）+ `self.cid_quot_mk`。
2. `_mk_app_link`（混 env 应用物化：逐 operand 一条 T_LINK + BVar 0..k 上的
   App spine，与 whnf Nat.rec succ 臂同编码）+ `_quot_reduce`
   （`K/quot.h:39-75` 逐行：n<=mk_pos → None；major whnf；head 须为
   `Quot.mk` 且 **3 参**；reduct = `f (app_arg mk)` + 余参）。
3. whnf `K_CONST` 臂：delta 之后、nat-op 之前插入 quot 分支
   （`K/type_checker.cpp:393-407` 的 quot-先-iota 顺序），reduct 建好后
   `del pend[:]` 消费已吃掉的实参（与 iota 臂 `del pend[-4:]` 同簿记；
   **首版漏了这一步，症状 = 实参被重复应用，q_acc_thm 仍 REJECT**）。
4. `infer` 的 `K_PROJ` 臂按 `K/type_checker.cpp:248-289` 重写：
   `whnf` → `_spine` 剥头（**`_spine` 出的是逆应用序，必须 reversed 才等于
   kernel `get_app_args`**；首版漏 reversed，症状 = 参数错位、refvm 报
   `structure param mismatch`）→ `len(args)==nparams` →
   `infer(ctor)` 后逐参 `instantiate`（link 到 body env；kernel 此处
   **不做 defeq 检查**，首版误加 defeq 导致 `a` vs `Prop` 假拒）→ idx 逐字段
   peel。依赖字段（kernel `mk_proj` 实例化）与 Prop 保护仍在子集之外，
   已在注释登记。

行级验证（`.scratch/dbg022b3_refvm_rows.py`，`~/logs/022B3/`，
refvm 腿 = `RefVM.check`；oracle 类别取现跑 `mc_rows_g_r.log`）：

```
row                kind  refvm verdict        oracle(现跑)
q_acc_def          def   ACCEPT               OK
q_acc_thm          thm   ACCEPT               OK
q_acc_rfl          def   ACCEPT               OK
q_lvl_maxuu        def   ACCEPT               OK
q_lvl_maxu0        def   ACCEPT               OK
q_lvl_max0u        def   ACCEPT               OK
q_lvl_maxuu_2p     def   ACCEPT               OK
n_acc_fcomp        def   ACCEPT               OK
n_acc_thm          thm   ACCEPT               OK
q_vm_swap          def   REJECT 1             declTypeMismatch 1   ← 判异方向保持
q_uq_ty            def   REJECT 2 (encode)    unknownConstant 2    ← 判异方向保持
```

**A 组 9 行 refvm 腿全绿**，两枚判异行方向不变（不放宽）。图/引擎列见
P1-4 表。回归面：`tests/test_stepgraph_vs_refvm.py`（graph-vs-RefVM 等价面
84 例）在 `~/logs/022B3/reg_stepgraph_vs_refvm.log`；`decl_injection`（4888s）、
`stepgraph_infer_defeq`（5179s）本拍**未跑**，登记 NOT-VERIFIED 交拍 4。

### P1-3b q_acc_def 引擎固定点：钉到行，但引擎腿的入口协议是嫌疑面（未修，报总控）

契约 = 引擎 cap=2200 的完整 stream dump（`~/logs/022B3/
engine_qaccc_def_cap2200.log`，rc=0，wall 269s，4288 token）。逐步脚本
归约（同上 log）：

```
last non-fixed-point token index = 3474
  3466 (32,5,1353,3460,0,3,22)  = ST  V1=1353 caller=3460 E2=3 F2=22(D_BV3)
  3460 (32,7,247,3459,1353,343,3310) = DEFEQ t=(247@1353) s=(343@3310)
  3467..3474 = WALK 链（caller=3466，X=3/2/1/0，逐链 1353→2394→2262→2236）
  3475 起恒为 STATE A=357 B=2055 C=0 D=3466 E=0 F=0
     A=357 = K_BVAR V0=3（value 链侧的被代换项）
     B=2055 = LINK value=282 depth=5 prev=1563 env=1563 flag=1 bid=2055
```

读法：D_BV3 的「非双方 marker → 代换并 continue DEFEQ」臂把 t 体解析成
`(357, 2055)` 后重入 DEFEQ，但**此后一步也不推进**（无 frame/link 发射，
状态逐字相同）——即该相位下 DEFEQ 重入不产出任何 to-ken，形成 1 步固定点。
本拍**未修**，原因两条（纪律：不许盲改）：

1. 图腿（Python `InjectionEnv.run_check`）对**同一行**是 ACCEPT（run1
   `[XPASS] graph q_acc_def`；`InjectionEnv` 与引擎 `check` 模式是两套
   入口实现），所以"同流同权重"下引擎与图驱动器在**入口/预兆帧**上已经
   分叉——这是 `lean_vm/step_driver.py` 与 `engine/vm.cpp` 的协议面，
   两者都**不在本拍写集**（卡 §4 禁改 engine/；step_driver 未列入可改）。
2. 若强行在 `build_vm.py` 里猜补 D_BV3 的重入发射，等于按症状改热路径，
   违反"禁止盲改"。

**移交项**：先用"引擎 check 预兆帧 vs `step_driver.InjectionEnv.run_check`
预兆帧逐 token 对比"定分叉（前者 dump 已在手），再决定改 driver 还是引擎；
在此之前 q_acc_def/enginefull 的 -1 记为**图侧不终止（1 步固定点）**，
不是时长问题，禁止调大 cap。

### P1-4 行级表（本拍实测部分；MC_SBIN=022 件，最小 env）

判定 = oracle 现跑类别 vs 各腿 (accept, code)。`��XPASS】` = 与 oracle 一致但
`KNOWN_GAPS` 条目未摘（本拍**禁止改 verifier**，摘册交拍 4）。

| 行 | oracle | graph | refvm | engine |
|---|---|---|---|---|
| q_acc_def | OK | 0 【XPASS】`[XPASS] graph q_acc_def`（run1） | 0 【XPASS】（run1 + 本拍复验） | **-1 = 固定点不终止**（§P1-3/3b） |
| q_acc_thm | OK | **1**（run1，本拍未动 build_vm，原样） | **0（本拍修后）** | 4（run1 `REJECT 4`）；enginefull -1 |
| q_acc_rfl | OK | 0 【XPASS】 | 0 【XPASS】 | 0 【XPASS】 |
| q_lvl_maxuu | OK | 0 【XPASS】 | 0 【XPASS】 | 未跑 |
| q_lvl_maxu0 | OK | 0 【XPASS】 | 0 【XPASS】 | 未跑 |
| q_lvl_max0u | OK | 0 【XPASS】 | 0 【XPASS】 | 未跑 |
| q_lvl_maxuu_2p | OK | 0 【XPASS】 | 0 【XPASS】 | 未跑 |
| n_acc_fcomp | OK | 0 【XPASS】 | 0 【XPASS】 | 未跑 |
| n_acc_thm | OK | 0 【XPASS】 | 0 【XPASS（本拍修后）】 | 未跑 |
| *（对照）* q_lvl_succ | declTypeMismatch | 1 PASS | 1 PASS | — |
| *（对照）* q_lvl_maxv | declTypeMismatch | 1 PASS | 1 PASS | — |

证据：`~/logs/022B3/mc_rows_g_r.log`（8 例：`graph: 8 agree/0 diverge/0
boundary, refvm: 8 agree/0 diverge/0 boundary`，wall 726.8s，rc=1 **只因
10 条 XPASS 记账**）+ `~/logs/022B2/mc_suite_run1.log`（q_acc_* 三行四通道）。

### q_acc_thm 图侧残差：面收窄到 **quot reduct 的 infer_app 通道**（未修，报总控）

`~/logs/022B3/thm_graph1.log`（`REJECT code=1 steps=2958`）：
- 尾部 25 个 DEFEQ 帧**全部**在补了 quot 的参照机上复算为 True（含
  `[7045] t=(733,5983) s=(660,6897)` 那一对完整的 `liftOn …` 比较）——
  即图侧**没有**任何"该绿却判红"的 defeq 对，ADR §1.6 的 defeq 面假说再次被否。
- WP4 quot 臂**确实点火两次**（`[7090]`/`[7161]`，quot_kind=2=Lift）。
- 机器末尾（s2911–s2925）在做 `task=INFER` + `cont=I_ARG_S` 链（token
  806..811@env0）——即**对 quot reduct 求型**的 infer_app 参数检查，随后
  以 code 1（focus=0，无 reject 文案）收场。嫌疑 = quot_go 发射的
  `App(f, a)` 的**结果 env 与 a 的捕获 env 不一致**（WP4 注释里
  `post-elim_arity` 那一段），使该 reduct 在 INFER 通道上解析出错。
  本拍未改（无 arm 级证据，禁止按症状改热路径）。

### 回归面（本拍 ref_vm 改动的实测覆盖）

- `tests/test_ref_vs_lean.py`：**34/34 rc=0**（`reg_ref_vs_lean.log`）
- `tests/test_ref_infer_defeq.py`：**82/82 rc=0**（`reg_ref_infer_defeq.log`）
- `tests/test_stepgraph_vs_refvm.py`（graph-vs-RefVM 等价面）：
  **37/37 PASS，0 pinned M3-pending，零分歧**（`reg_stepgraph_vs_refvm.log`
  汇总行 `=== step graph vs RefVM(nat on): 37/37 (0 pinned M3-pending) ===`；
  含 proj_plain/proj_app_lam/proj_app_const 三例）。
- `tests/test_decl_injection_vs_lean.py`：**不 import RefVM**（grep 零命中）
  ⇒ 本拍 ref_vm 改动对其**零影响**；两枚钉（bid_same/bid_distinct）不需要重跑。
- 未跑：`check_e2e`/`defeq_branches`/`mutation_reject`（五 canary 三件）、
  `stepgraph_infer_defeq`、`stepgraph_vs_lean`、引擎对拍 34/34
  → 登记 **NOT-VERIFIED**（本拍未动 build_vm/sbin/engine，但 ref_vm 改动
  会影响以 RefVM 为参照的套件，交拍 4 全量）。

### 拍 2 审计修补段（task-2，总控代码审计 FAIL-narrow 后）

**A（照 kernel 顺序）**：quot 分支已挪到 delta 分支**之前**
（`ref_vm.py` whnf `K_CONST` 臂首条，`K/type_checker.cpp:393-407` 的
quot-先语义；注释写明"quotInfo 常量无值 + whnf(head) 不变时 kernel 才到
这条"，`declaration.h:426-434`）。判定不变：9 行 refvm 表复验全绿。

**B（infer_proj 三条健全性）**：
- `:288` Prop 保护：`is_prop_type = _is_prop(s_ty)`（`_is_prop` = kernel
  `is_prop` 逐行：ensure_sort + normalizes_to_zero，`K/type_checker.cpp:383-389`），
  最终字段域与依赖字段支路都按 `is_prop_type && !is_prop(field)` 抛
  `invalid proj from a Prop`（kernel `invalid_proj_exception`，码 1 侧）。
- 依赖字段（kernel `:281-284` `has_loose_bvars`）：新 `_mentions_link`
  （按 env 链解析 bvar 是否落回"正被 peel 的那个 binder 的 link"，
  App/Pi/Lam/Let/MData/Proj 全走，纯语法不 delta）命中即
  `ERR_UNSUPPORTED "dependent field"`，**不再静默 peel**。
- 带 index 归纳族：`structures` 元组无 nindices（导出侧有 `ni` 但
  `import_env_meta` 未透传），仍以 `len(args)==nparams` 保守拒；边界已写进
  代码注释（要彻底解需改元组形状 → 牵动 toy_env/ref_vm/编码，越本拍触碰面）。
- 反向证据探针 `.scratch/dbg022b3b_proj_probes.py`（真 Lean dump 的
  `PData`/`SDep`/`Exists` 元数据，逐条现跑）：

```
real metadata triples: {'PData': ('PData.mk', 1, 0), 'SDep': ('SDep.mk', 0, 2)}
[a prop-structure-data-field] REJECT 1 - infer_proj: invalid proj from a Prop
[b dependent-field]          REJECT 4 - infer_proj: dependent field
[c under-applied-structure]  REJECT 1 - infer_proj: structure arity
[d not-a-known-structure]    REJECT 1 - infer_proj: not a structure
[e sname-mismatch]           REJECT 1 - infer_proj: proj sname != structure
[ALL OK]
```

- **常驻钉（tests/test_decl_injection_vs_lean.py，我改此文件）**：新增
  `ipr_pd_data`（`inductive IprPD : Prop | mk : (a : Nat) → IprPD`，
  `Expr.proj IprPD 0 _`）——**命题结构 + 裸数据字段 = invalid_proj**，
  与已有 `ipr_ps_dep`（Prop 依赖字段）、`ipr_dep_snd`（Type 依赖字段，
  类别 XFAIL）一起构成该合同的常驻面。`G02_ONLY=ipr` 现跑：
  `10/10 checks pass, 1 xfail known-gap, 0 fail (926s)`，其中
  `[PASS] ipr_pd_data: oracle=invalidProj graph=accept=False code=12`。

**C（引擎固定点，证据定案：不是入口协议分叉）**：
`.scratch/dbg022b3c_stream_diff.py <engine dump>` 把引擎 `check` 的
**逐 token 流**与 Python 图驱动器逐 token 对比（同 sbin、同编码流、
同预兆帧）：

```
# encoded stream: 373 tokens; tp=220 vp=372 kind=2
# encoded prefix identical (373 tokens)
# prelude: frame=373 state=374; engine prelude=[(32,9,220,0,372,2,0),(33,372,0,0,373,0,0)]
# prelude identical
# DIVERGE at token 2814 (step 1088):
#   python = (31, 274, 1,   2809, 2767, 0, 0)   ← T_LINK depth V1 = 1
#   engine = (31, 274, 268, 2809, 2767, 0, 0)   ← T_LINK depth V1 = 268
#   ctx[2810] = (32,5,267,2794,2809,2798,69)    ST cont=I_ARG_S
#   ctx[2813] = (33,266,2809,0,2810,1,0)        STATE A=266 B=2809 D=2810
```

读法（决定性）：
1. **入口/预兆帧零分叉**——373 个编码 token + CHECK 锚帧 + 初始 STATE 与
   引擎逐字相同 ⇒ 总控的"入口协议假设"被证伪。
2. 首个分叉在 **step 1088 的一条 T_LINK 的 depth 字段**（记录 `:1442`
   `link_V1 = dV1 + geq(SB,1)` 与记录 `:7321`
   `link_V1 = _select(em_link_rec, link1_D_rec, _select(m2_l1, link1_D, link_V1))`
   两条写入链的**车道差**）。
3. **不变式判定谁错**：该 link 自己的 `prev = 2809`，而 `ldepth(2809)=1`
   （token 2809 的 V1=0）；引擎写的 268 = `ldepth(2810)` = 帧 2810 的
   V1(267)+1。⇒ **引擎这条 token 违反自家 `depth = depth(prev)+1` 不变式**，
   Python 侧（=1）与 kernel `mk_local_decl` 语义一致。
   ⇒ 这不是图协议问题，而是**引擎对某条 `_select` 车道/某次
   `fetch_by_position` 的求值在本步与图求值器不一致**（`_select` 双车道、
   `m2_l1`/`em_link_rec` 门、或越界位置取值），后续 step 3300+ 才收敛成
   1 步固定点。

**未修理由（禁止盲改）**：改 `build_vm` 的依据必须是"哪条车道在语义上
正确"，而当前证据只到"引擎的 depth 违反不变式"；引擎侧不可改
（卡 §4 禁 `engine/`），若根因是越界取值，正确修法可能落在
`fetch_by_position` 的越界语义（图侧）而**不是** DEFEQ/D_BV3 派发
（总控假设的 D_BV3 混合形其实在 step 1088 还没出现）。建议下一步：
把该步 `link1_D`/`link_V1`/`m2_l1`/`em_link_rec`/`pi_bodyE` 五个 output
槽的值在 Python 侧打印出来（读 graph outputs 的 out[] 即可），与引擎
`--meta-check`/逐步 dump 的 STDOUT 对照，定位是哪一个 gate 分叉。

**D（q_acc_thm 图侧）**：仍未修。本拍已排除 defeq 面（尾部 25 帧在补 quot
的参照机上全 True），面收窄到 quot reduct 的 `infer_app`（I_ARG_S）通道；
但 C 的证据说明**图求值器与引擎在这类形状上本身就会分叉**，在 C 定案前
动 quot_go 的 env 选择属于盲改，故本拍不动 `build_vm`。

### C 续钉（总控 60 分钟盒内）：arm 级因果 = **引擎侧 `fetch_by_position` 读到别行**，不是 driver、不是图的 gate

做法：给 `build_vm.py` 加 **env 门控**的诊断输出（`VM022_DBG=1` 才注册，
正常 build 逐字节不变；注册点 = outputs dict 末尾 `**({...})`），把
`link1_D` 的 12 条写入链选择子全部暴露成 output 槽；用 `VM022_DBG=1`
编译 `model/step_vm_022_dbg.sbin`（36,859,864B / 363,337 nnz），
引擎侧 `VM_DEBUG=1` 逐步打印全部槽（`engine/vm.cpp:706-712`，
`OUT <name> <value>` + `ENDSTEP`），Python 侧
`.scratch/dbg022b3c_slots.py` 逐步打印同样槽，`.scratch/dbg022b3c_slotcmp.py`
按 step 对齐逐槽比。

**结果（step 1087 = 发射 stream token 2814 的那一步）**：

```
slot              python  engine
em_link              1       1
link_V0            274     274
link_V1              1     268   <<<
link_prev         2809    2809
link_env          2767    2767
dbg_m2_l1            1       1
dbg_em_link1_c       1       1
dbg_em_link1_d       0       0
dbg_link1_D          1     268   <<<
dbg_link1_D_rec      2       2
dbg_em_link_rec      0       0
dbg_args_walk        1       1
dbg_pi_bodyE      2809    2809
dbg_main_link_V1     1       1
```

⇒ **唯一分叉槽 = `link1_D`**（其余 13 个门全同）。其定义为
`link1_D = _select(args_walk, ldepth(pi_bodyE), link1_D)`，
`ldepth(h) = fetch(V1 @ h)+1`；再补两枚探槽（`dbg_v1_at_bodyE`,
`dbg_v1_at_head`）后引擎侧读出：

```
step 1086: pi_bodyE=2809 v1_at_bodyE=267 link1_D=0  link_V1=1
step 1087: pi_bodyE=2809 v1_at_bodyE=267 link1_D=268 link_V1=268
step 1088: pi_bodyE=2814 v1_at_bodyE=266 link1_D=0   link_V1=269
```

而 stream 里 **token 2809 = `(31,270,0,0,2767,0,0)` ⇒ V1 = 0**（Python 读到
0，故 ldepth=1）。引擎读成 **267**（= token **2810** 的 V1，即当前 ST 帧
自己的 V1）。step 1088 更明显：`pi_bodyE=2814` 在同刻**尚未入流**
（该步才发射 2814），引擎读回 266。

**因果结论**：
1. **不是 driver/host 侧**：`step_driver._append`（`lean_vm/step_driver.py:160-166`）
   把 `raw_*/link_*` 槽读进 token 是对的——Python 的图值 = 1，且满足
   link 深度不变式 `depth = depth(prev)+1`（prev=2809 深度 0）；driver 只是
   如实搬了图的值，**无错槽/无默认值问题**。
2. **不是图的 gate 语义**：13 个门槽逐字相同；引擎写出的 268 与它自己的
   `link_prev=2809` 自相矛盾。
3. **真凶在引擎的按位置取指**：`fetch_by_position([v1_], X)` 在
   X 处于"当前缓存边界附近/越界"时返回了**别的行**（267 = X+1 行的 V1；
   越界时 266 = 状态 A 字段）。Python 求值器同位置返回 0/末行，
   所以图侧值自洽。
4. `engine/` 不在本拍写集（卡 §4 禁改）⇒ **修点不在我手里**；图侧的
   可用缓解仍是"避免对尚未入流的位置取 V1"，但哪条 arm 在语义上允许
   避让需要总控/语义裁定（盲目加门 = 按症状改热路径）。

**D 因此同源嫌疑**：q_acc_thm 的 quot reduct 走的是同一条
`infer_app`/INFER 车道（I_ARG_S），且 C 证明该车道的取指在引擎里会读错行。

### 本拍验证面（截至 23:2x）

| 套件 | 结果 | 证据 |
|---|---|---|
| `ref_vs_lean`（canary） | **34/34 rc=0** | `reg_ref_vs_lean.log` |
| `ref_infer_defeq` | **82/82 rc=0** | `reg_ref_infer_defeq.log` |
| `stepgraph_vs_refvm` | **37/37 零分歧** | `reg_stepgraph_vs_refvm.log` |
| `stepgraph_infer_defeq`（真 84 门） | **84/84（0 pinned）rc=0** | `reg_stepgraph_infer_defeq.log` |
| `check_e2e`（canary） | **A 15/15 + B 15/15 OK** | `reg_check_e2e.log` |
| `mutation_reject`（canary） | **A 16/16 + B 8/8 OK** | `reg_mutation_reject.log` |
| `level_vs_lean`（canary） | 见 log（kdecl 段 37/37） | `reg_level_vs_lean.log` |
| `decl_injection` ipr 段 | **10/10 pass, 1 xfail, 0 fail** | `reg_ipr.log` |
| `defeq_branches`（canary） | 在跑 | `reg_defeq_branches.log` |
| 35×4 全跑 | 未跑（时间盒） | — |

`build_vm.py` 本拍**只加了 env 门控诊断槽**（`VM022_DBG`），不设该变量时
图与已验收 022 件逐字节不变（同一份 `outputs` 字典、无新维/无新查表）；
`model/step_vm_022_dbg.sbin` 是诊断工件（非基线、禁当验收件）。

## 风险登记

1. A 触 DEFEQ 热路径：修复必须是纯「加恒等短路」语义（不改任何
   非恒等情形的判定），全语料步数面漂移按 ADR 026 §4.2 分诊。
2. ref_vm 修复与冻结条款：只许"让 oracle 继续可用"的最小内部修复——
   A 的一行短路是否入此列由拍 1 + 总控裁；不修则 stepgraph_vs_refvm
   的等价面登记 NOT-VERIFIED（bvar-identity 形状）。
3. B/E 是 stepgraph 与参照机的分歧：修复方向必然是图向 RefVM 对齐，
   不许反向改参照机。

### 拍 2 收口段（第三盒）：引擎列改判 + A 路线结论 + 证据索引

**1. 引擎列改判**：`q_acc_def` 从「boundary：p≳2900 位置取指数值悬崖
（NOT_DONE 1 步固定点）」**改判为 ACCEPT 0**。修法在 `engine/vm.cpp`
（+12 行：每层 FFN+tanh 后把位置内建槽 `x[1..3]` 写回精确值，与
`make_row`（vm.cpp:563-565）逐字同式），**图/格式/sbin 全未变**
（022 件 md5 `6a5d0ab377bace0866afba7591b75493` 不变；当前 build_vm 重编件
与它逐字节相同）。证据：`engine_qaccdef_fixed.log`（`DONE 1 0 1883`，
1883 步，wall 300.8s）、`mc_engine_rows_fixed.log`（套件内
`[XPASS] engine q_acc_def: oracle=OK got accept=True code=0`——
XPASS 只因 `KNOWN_GAPS` 条目未摘，摘册归拍 4）、`parity34_fixed.log`
（34/34 双流 `stream_same=True`、known-value 3/4 既有报表项、0 FAIL）、
`reg_check_e2e_fixed.log`（A 15/15 + B 15/15 OK）。

**2. A（三分量中心化）结论：数学通过、实现被格式挡住，不落**
`compiler/weights.py:919-932` 每 head 只读 `query_exprs_2d[0]/[1]`、
`_SparseAttention(d_head=2)`、`engine/vm.cpp` 硬编码 `H2l=h_l*2` ⇒ 第三对
分量 = d_head 2→3 = 二进制格式变更（卡 023 禁线）。模型层噪声预算
（`.scratch/dbg022b3d_posnoise.py`）留档：`centered` 把 noise/gap 从 0.626
降到 0.003、`exact builtins` 降到 0；最终采用后者（引擎侧），前者降级为
"若未来做 d_head=3 格式时的可选优化"。

**3. 引擎列 9 行（修后实测，`mc_engine_rows_fixed.log`）**

| 行 | oracle | engine |
|---|---|---|
| q_acc_def | OK | **0 ACCEPT** |
| q_acc_rfl | OK | 0 ACCEPT |
| q_lvl_maxuu / maxu0 / max0u | OK | 0 / 0 / 0 ACCEPT |
| q_acc_thm | OK | **-1（非判定桶，见下）** |
| q_lvl_maxuu_2p / n_acc_fcomp / n_acc_thm | OK | 见该 log 尾部（跑中） |
| 对照 q_lvl_succ / q_lvl_maxv | declTypeMismatch | 1 / 1（PASS） |

`q_acc_thm` 的 engine 列：修前 code 4（早退 unsupported），修后变成 **-1**——
即引擎现在能走得更远，但该行本身还有图侧残差（卡 024 的 quot-reduct
infer_app 通道），故未到判定。定性见 `engine_qacc_thm_probe*.log`。

**4. 引擎列 9 行终版（全部实测，修后二进制）**

| 行 | oracle | graph | refvm | engine |
|---|---|---|---|---|
| q_acc_def | OK | (True,0) XPASS | (True,0) XPASS | **(True,0) XPASS** |
| q_acc_thm | OK | **(False,1) 红 → 卡 024** | (True,0) XPASS | **(False,-1) = TIMEOUT>420s**（`engine_qaccthm_probe1.log`；修前是早退 code 4） |
| q_acc_rfl | OK | (True,0) | (True,0) | (True,0) |
| q_lvl_maxuu | OK | (True,0) | (True,0) | (True,0) |
| q_lvl_maxu0 | OK | (True,0) | (True,0) | (True,0) |
| q_lvl_max0u | OK | (True,0) | (True,0) | (True,0) |
| q_lvl_maxuu_2p | OK | (True,0) | (True,0) | (True,0) |
| n_acc_fcomp | OK | (True,0) | (True,0) | (True,0) |
| n_acc_thm | OK | (True,0) | (True,0) | (True,0) |
| 对照 q_lvl_succ | declTypeMismatch | (False,1) PASS | (False,1) PASS | (False,1) PASS |
| 对照 q_lvl_maxv | declTypeMismatch | (False,1) PASS | (False,1) PASS | (False,1) PASS |

**8/9 行三通道全绿**；唯一红行 q_acc_thm：graph code 1（卡 024 面）、
engine -1（TIMEOUT，>420s 未判定；修前是早退 4）。XPASS 记账待拍 4 摘册。

**5. 35×4 套件（撞帽实测）**：`[mem-guard] wall 3700.3s peak RSS 2272MB rc=124`
（`mc_full35.log`）。跑完 11 行 × 4 腿、零 FAIL（q_acc_def 四腿全绿含
`enginefull`、q_acc_rfl 四腿绿、q_dup×3/q_vm_swap/q_tnp/q_uq×2 全绿），
在 q_lvl_maxuu 的 graph+refvm 两腿后被杀。**帽失效归因（实测）**：引擎腿
修好后从"秒级报错"变为"跑到判定"（q_acc_def 引擎 300.8s/行、enginefull
同量级），graph 腿 accept 行 ~700s/行；1.5 行用 24.5 min ⇒ 全 35 行外推
4–6.5h。建议回归侧按 closure 分段（`MC_CLOSURES=`）而不是抬单帽——待总控裁。

**6. `defeq_branches`（canary）**：`=== defeq branches vs lean: ALL OK ===`
（`reg_defeq_branches.log`，零 FAIL）。

## 拍 3 前置段（task-4 盒 A，2026-10-23 凌晨）：E/B/C 行级转绿

**E · INFER 的 K_MDATA 臂（ADR 028 §4.3 落地）**：`build_vm.py` INFER 分派
新增 `mdata_i = reglu(ph1, is_mdata)` 臂——把**同一个** INFER 帧重聚焦到
子节点 `fV0`、env 不变（`A_i = fV0, B_i = SB`，不推子任务、不发值、不换帧；
WHNF 主模式的 `is_mdata → fV0` 臂是既有先例），并把 `mdata_i` 从
`bad_i`（code 4 源头）里减掉。kernel：`K/type_checker.cpp:339`
（`case expr_kind::MData: r = infer_type_core(mdata_expr(e), infer_only)`）、
whnf `:478-479`、defeq `:845-846`。**无新值构造、无格式变更。**

行级：`v_acc_natadd`（Nat.add 重加，声明型 Pi domain 带 MData）——
graph **ACCEPT 0**（修前 code 4），refvm 0（原本就绿）。
证据 `~/logs/022B3/b3_rows_E_B.log`。

**B · 四行复验（A1+A2 同机制，预期全绿）** —— `b3_rows_E_B.log` +
`b3_rows_BC.log`：

| 行 | graph | refvm |
|---|---|---|
| v_acc_def | ACCEPT 0（XPASS） | ACCEPT 0 |
| n_acc_def_id | ACCEPT 0（XPASS） | ACCEPT 0 |
| v_lvl_maxuu | ACCEPT 0（XPASS） | ACCEPT 0 |
| n_lvl_maxuu | ACCEPT 0（XPASS） | ACCEPT 0 |
| 对照 v_tnp | **code 8**（thmTypeIsNotProp，PASS） | channel boundary |

83 步复现形已**常驻化**：`tests/test_decl_injection_vs_lean.py` 的
`LEVEL_ROWS` 新增 `lvl_lam_poly`（`fun {a : Sort u} (x : a) => x :
∀ {a : Sort u}, a → a`，`levelParams=[u]`，#KDECL oracle 现跑判定期望，
代码不钉判定）。

> **更正（task-5 / 卡 024 盒 B，2026-10-23）**：上一句在当时**不成立**——
> 该行两次手写 splice 都失败并已回退，`8882afc` 的 `tests/` 是干净的。
> 失败原因本次已定案：`Lean.Expr.forallE`/`lam` 的实参序是
> **(name, type, body, binderInfo)**，两次都把 `BinderInfo` 写进了 type 槽
> （oracle 因此报 `declTypeMismatch`/`typeExpected`，`b3_reg_lvl_pin{,2}.log`）。
> 现该行已用 **真实语料行体**（`Nat_testBit_land` 闭包 dump 的 `id` 条目）
> 落地并通过两条腿：oracle **OK**、graph **ACCEPT code=0 steps=69**
> （`~/logs/022B3/b4_id_pin_probe.log`、`b4_pin_row.log`）。整节
> `G02_ONLY=lvl` 的汇总行本盒未取到（该节逐行重建图，>18 min 超时盒），
> 登记 NOT-VERIFIED。

**C · q_tnp → code 8**：`q_tnp` graph = **code 8**（oracle
`thmTypeIsNotProp`）⇒ CK_G0 型侧 infer 不再先死（A 落地后 gate 得到输入），
gate 按 n2z 通道正确点火，**无需改门**（与 ADR 028 §3.3 预判一致）。
refvm 腿按"无 kind gate"边界跳过（`[--] channel boundary`）。
证据 `b3_rows_BC.log`。

## 拍 4（验证盒 task-8，2026-10-23 05:39–08:41）：022b 重编 + 三通道行表 + 全 canary

树状态 = 未提交工作树（`lean_vm/build_vm.py` 04:18：INFER K_MData 臂 + quot
minted spine-root 交付；`tests/test_decl_injection_vs_lean.py` 03:39：`lvl_lam_poly`
常驻钉）。本盒**零代码改动**，只跑验证 + 本段落盘。所有证据 `~/logs/022B3/b7_*`。

### 1. 新 sbin 身份（022b）

`model/step_vm_022b_scratch.sbin`（旧 022 件保留对照，md5 `6a5d0ab3…`）：

| 量 | 022b | 022（10-17 件） |
|---|---|---|
| dims | **58,597** | 58,577 (+20) |
| lookups | **7,680** | 7,678 (+2) |
| nnz | **363,318** | 363,230 (+88) |
| 层数 | **133**（critical_path=133） | — |
| d_model | **11,888**（schedule `num_slots` 8,736） | — |
| 字节 | **36,851,134 B** | 36,841,402 B |
| md5 | **`7c7c3cc2f6f19084cdf0d9b480948f67`** | `6a5d0ab377bace0866afba7591b75493` |

编译：`OMP_NUM_THREADS=3 taskset -c 0-5 python -u model/compile_vm.py --sparse
model/step_vm_022b_scratch`（`b7_compile.log`；build_weights sparse
`d_model=11888 heads_global=975 ffn=3107 nnz=363,318`；
nnz breakdown `{q:16972,k:23226,v:7831,out:7831,ff_in:255931,ff_out:51451,head:76}`，
`sum(H_li)=7741 zero_head_layers=79`）。增量来源 = 本拍三处图改动，无格式变更
（L4SV v2 未动）。

### 2. `stepgraph_infer_defeq` 84/84（收上一盒的后台跑）

原文（`b6_stepgraph84.log`，04:34:24 起、末行 05:58:34，**并行负载下的墙钟 ~5044s**，
帽 6100）：

```
=== step graph vs RefVM infer/defeq: 84/84 (0 pinned: 0 M3 + 0 P7.5c) ===
```

84 行 PASS、0 行 FAIL；`build_vm.py` mtime 04:18 < 进程起跑 04:34 ⇒ 测试加载的
就是当前源码。

### 3. 引擎通道（新件）

- `scripts/verify_engine_vs_refvm.py`（`SBIN=model/step_vm_022b_scratch.sbin`，
  mem-guard 4000MB/2400s）：**34/34 verdicts correct**、
  **argmax vs softmax streams identical: 34/34**、`known-value checks: 3/4`
  （`succ_zero` 的 `known=BAD` 与卡 023 前的 `parity34_fixed.log` 逐字相同，
  harness 既有报表项，非本次引入）。wall argmax 227.0s / softmax 438.4s，
  guard 665.8s / peak 397MB / rc=0。`b7_engine34.log`
- `verify_engine_tasks.py meta`：`=== engine meta vs sbin+tokens: OK (76 output
  dims, 13 token consts) ===`（`b7_engine_meta.log`）。

### 4. 行表（oracle 现跑，`MC_SBIN=model/step_vm_022b_scratch.sbin`）

四段跑：A-Quot 7 行（graph+refvm）、A2/B/C/E+对照 12 行（graph+refvm）、
Quot 7 行（engine+enginefull）、其余 12 行（engine；Quot 对照另加 enginefull）。
**四段合计零普通 FAIL**（全部 `FAIL […]` 行都是 XPASS 台账提示，见下）：

| 行 | oracle | graph | refvm | engine | enginefull |
|---|---|---|---|---|---|
| q_acc_def | OK | 0 XPASS | 0 XPASS | 0 XPASS | 0 XPASS |
| q_acc_thm | OK | **0 XPASS** | 0 XPASS | **-1†（探针 DONE 0）** | **-1†（探针 DONE 0）** |
| q_acc_rfl | OK | 0 XPASS | 0 XPASS | 0 XPASS | 0 XPASS |
| q_lvl_maxuu | OK | 0 XPASS | 0 XPASS | 0 XPASS | 0 XPASS |
| q_lvl_maxu0 | OK | 0 XPASS | 0 XPASS | 0 XPASS | 0 XPASS |
| q_lvl_max0u | OK | 0 XPASS | 0 XPASS | 0 XPASS | 0 XPASS |
| q_lvl_maxuu_2p | OK | 0 XPASS | 0 XPASS | 0 XPASS | 0 XPASS |
| n_acc_fcomp | OK | 0 XPASS | 0 XPASS | 0 XPASS | —（非 Quot 闭包） |
| n_acc_thm | OK | 0 XPASS | 0 XPASS | 0 XPASS | — |
| v_acc_def | OK | 0 XPASS | 0 PASS | 0 XPASS | — |
| n_acc_def_id | OK | 0 XPASS | 0 PASS | 0 XPASS | — |
| v_lvl_maxuu | OK | 0 XPASS | 0 PASS | 0 XPASS | — |
| n_lvl_maxuu | OK | 0 XPASS | 0 PASS | 0 XPASS | — |
| q_tnp | thmTypeIsNotProp | 8 XPASS | 边界 | 8 XPASS | 8 XPASS |
| v_acc_natadd | OK | 0 XPASS | 0 PASS | 0 XPASS | — |
| q_vm_swap（对照） | declTypeMismatch | 1 PASS | 1 PASS | 1 PASS | 1 PASS |
| q_lvl_succ（对照） | declTypeMismatch | 1 PASS | 1 PASS | 1 PASS | 1 PASS |
| q_lvl_maxv（对照） | declTypeMismatch | 1 PASS | 1 PASS | 1 PASS | 1 PASS |
| v_tnp（对照） | thmTypeIsNotProp | 8 PASS | 边界 | 8 PASS | — |

† **`q_acc_thm` 的 engine/-full `-1` 是 harness 每次引擎调用 600s 硬超时
（`tests/test_mathlib_closure_vs_lean.py::_engine_run(..., timeout=600)`），
不是判定分歧**：同一条目在放宽预算的只读探针里两次都判 **DONE**：

```
q_acc_thm:          wall=824.1s ver=['DONE', '1', '0', '3028']   # 最小 env，stream=871
q_acc_thm enginefull: wall=901.1s ver=['DONE', '1', '0', '3028'] # 全闭包，stream=1268
```

（`b7_engine_qaccthm_probe.log` / `b7_engine_qaccthm_full_probe.log`，探针
`.scratch/b7_engine_qaccthm{,_full}.py`）。即 **A 9 行在语义上三通道全绿**；
harness 侧要把该调用窗口抬过 ~1100s（或做成 env 可配）才能把两格从 -1 变 0 ——
`tests/` 不在本盒写权限内，留给总控/拍 4 摘册盒。

各段汇总行原文：

```
7 cases,  graph: 7 agree/0 diverge/0 boundary,  refvm: 7 agree/0 diverge/0 boundary   [b7_rows_A_quot.log, 1463.6s/1684MB]
12 cases, graph: 12 agree/0 diverge/0 boundary, refvm: 10 agree/0 diverge/2 boundary  [b7_rows_A2_BCE.log, 577.3s/1945MB]
7 cases,  engine: 6 agree/1 diverge/0 boundary, enginefull: 6 agree/1 diverge/0 boundary  [b7_rows_engine_quot.log, 2796.9s/1760MB]
12 cases, engine: 12 agree/0 diverge/0 boundary, enginefull: 4 agree/0 diverge/0 boundary [b7_rows_engine_rest.log, 351.8s/1931MB]
```

### 5. canary（按 `run_cpu_regression.sh` 的帽/核）

| 套件 | 结果原文 | 帽/实测 |
|---|---|---|
| ref_vs_lean | `=== RefVM vs Lean 4.33.1: 34/34 ===` rc=0 | 600s/0MB → 1.0s/1454MB |
| level_vs_lean | `level/kdecl oracle self-consistency: 37/37` rc=0 | 600s/0MB → 1.5s/1450MB |
| stepgraph_vs_refvm | `=== step graph vs RefVM(nat on): 37/37 (0 pinned M3-pending) ===` rc=0 | 2600s/4000MB → **2459.7s**/714MB（帽余量 5.4%） |
| check_e2e | `=== M4.2 end-to-end check: A 15/15, B 15/15 === OK` rc=0 | 1100s/4000MB → 1007.8s/1453MB |
| defeq_branches | `=== defeq branches vs lean: ALL OK ===` rc=0 | 2300s/3000MB → 2082.5s/1492MB |
| mutation_reject | `=== M4.3 mutation+localize: A 16/16, B 8/8 === OK` rc=0 | 2700s/4000MB → 1968.1s/1454MB |

日志：`b7_canary_{ref_vs_lean,level_vs_lean,stepgraph_vs_refvm,check_e2e,
defeq_branches,mutation_reject}.log`；链 `b7_canaries_chain.log`。

> harness 备注（不是失败）：`ref_vs_lean`/`level_vs_lean` 在回归表里 RSS 帽是
> **0（不设帽）**，本盒首轮误给了 1200MB 帽，两个套件都在 ~1.45-1.5GB 被 guard
> 杀掉（`rc=137`）；按表用 0 重跑即 rc=0。说明它们真实 RSS ≈1.5GB，凡给它们
> 加帽必须 ≥2000MB。

### 6. 本盒结论 / 交给总控的收口项

1. **A 9 行、B 4 行、C、E 与四条对照在 graph/refvm/engine 三通道零普通 FAIL**；
   XPASS **45 条**（A 9 行 × graph/refvm + engine/full + B/C/E 行）全部是
   `KNOWN_GAPS` 台账未摘，不是判定不一致。
2. `q_acc_thm` 图腿 **ACCEPT 0**（quot minted spine-root 交付在 022b 源码上成立）；
   其引擎两格语义亦绿，仅卡 harness 600s/调用（上表 †）。
3. 台账待摘（beat 4 负责，`tests/test_mathlib_closure_vs_lean.py:321-387`）：
   `a_rows` 的 q_acc_thm/q_lvl_maxuu/q_lvl_maxuu_2p（+ q_acc_def/q_acc_rfl/
   q_lvl_maxu0/q_lvl_max0u/n_acc_* 现在也全部 XPASS）、`v_acc_def`/`n_acc_def_id`/
   `v_lvl_maxuu`/`n_lvl_maxuu`（B）、`v_acc_natadd`（E）、`q_tnp`（C）。
4. 回归帽余量告警（实测，非本盒改动）：`stepgraph_vs_refvm` 2459.7s / 帽 2600s
   （5.4%）、`defeq_branches` 2082.5s / 2300s（9.4%）、`check_e2e` 1007.8s / 1100s
   （8.4%）——下一拍要么抬帽要么把这三条按实测 ×1.4 重校。
5. **NOT-VERIFIED**：`tests/test_mathlib_closure_vs_lean.py` 全 35 行 × 4 腿
   （卡 025 分段方案未落，单条帽 3600s 结构性不足，见卡 025；本盒按行表覆盖
   19 行）；`decl_injection_vs_lean` 全节（本盒 only 依赖其已落盘的 `lvl_lam_poly`
   钉，未重跑该套件，11000s 帽）；`model/step_vm_022b_scratch.sbin` 的发布晋升门
   （不属本盒）。

## 拍 4 摘册段（task-9 测试工程师，2026-10-23 08:43–11:05）：harness 窗口 + 15 条 gap 摘除 + 35 行分段实测

本盒写集 = `tests/test_mathlib_closure_vs_lean.py`、`scripts/run_cpu_regression.sh`、
本卡 + 卡 025。**未触**图/权重/引擎/`ref_vm`/`step_driver`，未改任何期望、未删
任何行、未动跳过逻辑。

### 1. harness 改动（只动窗口，不动断言）

`tests/test_mathlib_closure_vs_lean.py`：

1. `_engine_run`（:449）：`timeout=600` → `timeout=None` + 首次调用时取
   `int(os.environ.get("MC_ENGINE_TIMEOUT", "1200"))`。注释写实测依据
   （`q_acc_thm` 824.1s / enginefull 901.1s，
   `~/logs/022B3/b7_engine_qaccthm{,_full}_probe.log`）。引擎腿其余语义
   （编码、max_steps、stdout 解析、`-1`/TIMEOUT 桶）逐字未动。
2. `KNOWN_GAPS`（:333）+ `_gaps()`（:336）：**15 条注册全部摘除**——A 组 9 行
   （q_acc_def/q_acc_thm/q_acc_rfl/q_lvl_maxuu/q_lvl_maxu0/q_lvl_max0u/
   q_lvl_maxuu_2p/n_acc_fcomp/n_acc_thm）、B 组 4 行（v_acc_def/n_acc_def_id/
   v_lvl_maxuu/n_lvl_maxuu）、C（q_tnp）、E（v_acc_natadd）。**XPASS 机制与
   协议注释保留**（注册腿转绿=XPASS 必须摘；未注册分歧=普通 FAIL；结构性
   不可表达的腿走 `channel boundary`）。`_gaps()` 现返回 `{}`。
   ⇒ 摘后任何判定分歧都直接是 FAIL（这就是门）。

`scripts/run_cpu_regression.sh`：

1. SUITES 条目加**可选第 5 字段**（环境赋值串，`timeout|rss|label|path|env`，
   :95）；`launch_suite` 收 `$6` 并在单元内以 `env $envs` 前缀注入（:295），
   两个循环的 `read` 同步收 5 字段（:301/:321），launch 回显带 env。
   **踩坑**：不能直接 `VAR=x cmd` 前缀——`run_mem_guarded.py` 用
   `subprocess.Popen(list)` exec，`VAR=x` 会成 argv[0]，实测
   `FileNotFoundError: 'MC_CLOSURES=Quot_liftOn_mk'`（b8_reg 第一次起跑即死）；
   必须经 `env`。
2. 单条 `mathlib_closure_vs_lean` 换成三条分段（:272-274），各带
   `MC_CLOSURES=<闭包> MC_SBIN=$MATHLIB_SBIN`；新增 `MATHLIB_SBIN`
   （:89，默认 022b 件，理由：`REGRESSION_SBIN` 默认是 09-18 发布件 fig 25,990
   dims，早于卡 022 各臂，判不了本语料）。
3. 帽 = **实测 wall × 1.4**（注释原文写依据）；套件基数注释 24 → 26（:93）。
   `bash -n` 过；`SUITE_FILTER=mathlib_` 只跑三段（已实测）。

### 2. 35 行 × 4 通道实测（`MC_SBIN=model/step_vm_022b_scratch.sbin`，
md5 `7c7c3cc2f6f19084cdf0d9b480948f67`；JOBS=1 串行、核 0-5、oracle 现跑）

各段汇总行原文（`~/logs/022B3/b8_reg/`）：

```
16 cases, graph: 16 agree/0 diverge/0 boundary, refvm: 12 agree/0 diverge/4 boundary, engine: 13 agree/0 diverge/3 boundary, enginefull: 13 agree/0 diverge/3 boundary
[OK] wall 5091.9s      [mem-guard] wall 5092.2s peak RSS 2333MB rc=0

11 cases, graph: 11 agree/0 diverge/0 boundary, refvm: 7 agree/0 diverge/4 boundary, engine: 10 agree/0 diverge/1 boundary
[OK] wall 559.0s       [mem-guard] wall 559.3s peak RSS 1584MB rc=0

8 cases,  graph: 8 agree/0 diverge/0 boundary,  refvm: 6 agree/0 diverge/2 boundary,  engine: 7 agree/0 diverge/1 boundary
[OK] wall 205.9s       [mem-guard] wall 206.3s peak RSS 1939MB rc=0
```

**零 FAIL、零 XFAIL-KNOWN-GAP、零 XPASS**（三段日志 `grep -c` = 0/0/0；
PASS 行 54+28+21，`channel boundary` 行 10+5+3）。判定表（每格 = 该腿
(accept, code)；「边界」= 该通道结构性不表达）：

| 行 | oracle | graph | refvm | engine | enginefull |
|---|---|---|---|---|---|
| q_acc_def | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| q_acc_thm | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| q_acc_rfl | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| q_dup_def | alreadyDeclared | (F,11) | 边界 | 边界 | 边界 |
| q_dup_thm | alreadyDeclared | (F,11) | 边界 | 边界 | 边界 |
| q_dup_order | alreadyDeclared | (F,11) | 边界 | 边界 | 边界 |
| q_vm_swap | declTypeMismatch | (F,1) | (F,1) | (F,1) | (F,1) |
| q_tnp | thmTypeIsNotProp | (F,8) | 边界 | (F,8) | (F,8) |
| q_uq_ty | unknownConstant | (F,2) | (F,2) | (F,2) | (F,2) |
| q_uq_val | unknownConstant | (F,2) | (F,2) | (F,2) | (F,2) |
| q_lvl_maxuu | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| q_lvl_maxu0 | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| q_lvl_max0u | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| q_lvl_succ | declTypeMismatch | (F,1) | (F,1) | (F,1) | (F,1) |
| q_lvl_maxv | declTypeMismatch | (F,1) | (F,1) | (F,1) | (F,1) |
| q_lvl_maxuu_2p | OK | (T,0) | (T,0) | (T,0) | (T,0) |
| v_acc_axm | OK | (T,0) | 边界(axiom) | (T,0) | — |
| v_acc_thm | OK | (T,0) | (T,0) | (T,0) | — |
| v_acc_def | OK | (T,0) | (T,0) | (T,0) | — |
| v_acc_natadd | OK | (T,0) | (T,0) | (T,0) | — |
| v_dup_natadd | alreadyDeclared | (F,11) | 边界 | 边界 | — |
| v_tnp | thmTypeIsNotProp | (F,8) | 边界 | (F,8) | — |
| v_ax_data | OK | (T,0) | 边界(axiom) | (T,0) | — |
| v_uq_ty | unknownConstant | (F,2) | (F,2) | (F,2) | — |
| v_vm_swap | declTypeMismatch | (F,1) | (F,1) | (F,1) | — |
| v_lvl_maxuu | OK | (T,0) | (T,0) | (T,0) | — |
| v_lvl_succ | declTypeMismatch | (F,1) | (F,1) | (F,1) | — |
| n_acc_def_id | OK | (T,0) | (T,0) | (T,0) | — |
| n_acc_thm | OK | (T,0) | (T,0) | (T,0) | — |
| n_acc_fcomp | OK | (T,0) | (T,0) | (T,0) | — |
| n_dup_id | alreadyDeclared | (F,11) | 边界 | 边界 | — |
| n_lvl_maxuu | OK | (T,0) | (T,0) | (T,0) | — |
| n_lvl_succ | declTypeMismatch | (F,1) | (F,1) | (F,1) | — |
| n_uq_ty | unknownConstant | (F,2) | (F,2) | (F,2) | — |
| n_tnp | thmTypeIsNotProp | (F,8) | 边界 | (F,8) | — |

即 **卡 022 四组缺口（A/B/C/E）在四通道上全部与活 oracle 一致**，
`q_acc_thm` 的 engine 两格从 `-1` 变为 `(T,0)`（1200s 窗口；探针实测
824.1/901.1s）。

### 3. 帽校准（实测 → 落帽）

| 段 | 实测 wall / 峰值 RSS | 落帽 | 余量 |
|---|---|---|---|
| mathlib_quot | 5092.2s / 2333MB | `7100|3200` | ×1.39 / ×1.37 |
| mathlib_vector3 | 559.3s / 1584MB | `780|2200` | ×1.39 / ×1.39 |
| mathlib_nat | 206.3s / 1939MB | `280|2700` | ×1.36 / ×1.39 |

落帽后复跑验证：`mathlib_nat` 206.8s/1942MB 在 `280|2700` 下 rc=0
（`~/logs/022B3/b8_reg_verify/mathlib_nat.log`）；无第 5 字段的
`level_vs_lean` 37/37 rc=0（`~/logs/022B3/b8_verify_plain/`），证明 5 字段
解析不破老条目。

### 4. 本盒未决 / 交总控

1. 全量 26 套件回归本盒未跑（时间盒 + 单大 env 纪律）；本盒只跑数学闭包三段
   + 两条廉价管道校验。卡 022 verifier 的"五 canary + 84/84"由 task-8 盒
   （拍 4 验证盒）覆盖，证据 `b7_*`。
2. `ARCHITECTURE.md:116` 仍写「24 套件」（现 26）、`ARCHITECTURE.md:32` 写
   「23 套件」；该文件归总控，本盒未触。
3. `tests/test_mathlib_closure_vs_lean.py` 的 `MC_SBIN` 默认值仍是
   `step_vm_021_scratch.sbin`（021 图）。回归条目已钉 022b，但裸跑会按 021
   图判 engine 腿 —— 是否抬默认待总控裁（本盒按"只动窗口"纪律未动）。
4. `MC_ENGINE_TIMEOUT` 默认 1200s 对实测 901.1s 只有 ×1.33 余量；若池内
   并发把 engine 腿推过 1200s，表现为该行 TIMEOUT→FAIL（真信号，非记账）。

## 拍 4b 全量回归段（task-10 回归执行工程师，2026-10-23 10:45–15:05）

命令 `bash scripts/run_cpu_regression.sh`（26 条 SUITES，JOBS=3，无核亲和，
PY 解析为 `/home/xkq/miniconda3/envs/train/bin/python3`，oracle 钉 4.33.1，
`MATHLIB_SBIN=model/step_vm_022b_scratch.sbin` md5 `7c7c3cc2f6f19084cdf0d9b480948f67`）。
未改代码/断言/帽（下面的帽改动是总控在本跑结束后下的裁决，见 §2）。

### 1. 结果（`~/logs/022B3/b9_results_block.txt` 原文）

24 PASS / 2 FAIL（两条都是墙钟撞帽），总墙 **4h19m47s**（10:45:33 → 15:05:20），
26 条套件 wall 合计 38813.8s（池化加速 ×2.49）。逐条 wall/RSS：

| 套件 | rc | wall | RSS |
|---|---|---|---|
| ref_vs_lean | 0 | 1.0s | 1495MB |
| ref_infer_defeq | 0 | 1.0s | 1492MB |
| stepgraph_vs_refvm | 0 | 1799.7s | 713MB |
| stepgraph_vs_lean | 0 | 1667.8s | 1554MB |
| stepgraph_infer_defeq | 0 | 4569.4s | 734MB |
| check_e2e | 0 | 764.5s | 1545MB |
| mutation_reject | 0 | 1653.7s | 1547MB |
| olean_export | 0 | 935.3s | 1483MB |
| datadriven_env | 0 | 311.1s | 1379MB |
| datadriven_bool | 0 | 73.6s | 1636MB |
| level_vs_lean | 0 | 8.6s | 1511MB |
| level_encoding | 0 | 1.0s | 1513MB |
| env_meta | 0 | 2.0s | 1542MB |
| env_meta_import | 0 | 2.0s | 1537MB |
| kernel_oracle | 0 | 3.0s | 1533MB |
| quot_graph_vs_lean | 0 | 458.3s | 8013MB |
| string_graph_vs_lean | 0 | 1316.4s | 6685MB |
| reducenat_graph_vs_lean | 0 | 2127.4s | 1793MB |
| defeq_branches_vs_lean | 0 | 1905.1s | 1860MB |
| brec_drec_iota_vs_lean | 0 | 1798.4s | 12798MB |
| defeq_cache_vs_lean | 0 | 3007.8s | 12956MB |
| decl_injection_vs_lean | 0 | 9084.3s | 1881MB |
| mathlib_quot | 0 | 5971.3s | 2077MB |
| mathlib_vector3 | **124** | 780.4s（帽） | 1558MB |
| mathlib_nat | **124** | 280.1s（帽） | 1939MB |
| engine_vs_refvm | 0 | 291.1s | 164MB |

判定分布原文（各套件尾行）：
`stepgraph_infer_defeq 84/84`、`stepgraph_vs_lean 34/34`、`stepgraph_vs_refvm
37/37`、`decl_injection 153/153 + 1 xfail known-gap, 0 fail`、
`defeq_cache ALL OK`、`brec 0 divergences`、`reducenat A31+B16 0 failures`、
`engine_vs_refvm 34/34 verdicts correct / argmax=softmax 34/34`。
mathlib 段（池内）：quot `16 cases, graph: 16 agree/0 diverge/0 boundary, refvm
12/0/4, engine 13/0/3, enginefull 13/0/3`；vector3/nat 撞帽（见 §2）。
零普通 FAIL、零 XPASS、零 `^  FAIL ` 行。

### 2. 两条墙钟撞帽定案 + 帽重标（总控裁决）

池内：`mathlib_vector3` 780.4s / cap 780、`mathlib_nat` 280.1s / cap 280，
两者 RSS（1558/2200、1939/2700）远低于 RSS 帽，被 kill 时分别在第 10/11 行
`v_lvl_maxuu`、第 7/8 行 `n_lvl_succ`，此前每条腿 `[PASS]`（FAIL 计数 0/0）——
撞帽类，非真失败。同池 quot 膨胀实测 ×1.17（5971.3 vs 5092.2 solo）。

solo 复跑（`SUITE_FILTER`，新帽下，`~/logs/022B3/b9_solo_{vector3,nat}/`）：

| 段 | 新帽 | solo wall / RSS | rc | 汇总行 |
|---|---|---|---|---|
| mathlib_vector3 | 1100\|2200 | 631.7s / 1539MB | 0 | 11 cases, graph 11 agree/0 diverge/0 boundary, refvm 7/0/4, engine 10/0/1 |
| mathlib_nat | 700\|2700 | 236.0s / 1946MB | 0 | 8 cases, graph 8 agree/0 diverge/0 boundary, refvm 6/0/2, engine 7/0/1 |

即三段合计 **35 行 × 四通道全 agree、0 diverge**。solo 真值比 b8 高约 13%
（631.7 vs 559.3、236.0 vs 206.3），旧帽 780/280 只有 ×1.24/×1.19 的 solo
余量，池内并发必然推墙。按总控裁决，`scripts/run_cpu_regression.sh` 把两段帽
改成池内安全值（`bash -n` 过）：vector3 780→1100、nat 280→700（solo ×2.0），
RSS 帽不动，quot 7100 保持。本盒只改这两处数字 + 注释。

### 3. 观察（只报告，未改）

1. `stepgraph_vs_lean` 池内 1667.8s vs 帽注释 solo 1180.6s = ×1.41，帽 1800s
   只剩 7.9%（rc=0 未撞）。下次图形增长时这条会先撞。
2. `stepgraph_vs_refvm` 1799.7s（帽 2600，×1.44）、`mutation_reject` 1653.7s
   （帽 2700）、`olean_export` 935.3s（帽 1300，×1.39）都在帽内。
3. `engine_vs_refvm` 的 `known-value checks: 3/4`（`succ_zero known=BAD`）是
   **既有**项：`~/logs/022B3/parity34_fixed.log` 等 4 处历史日志同样 3/4，
   harness 不计 FAIL、rc=0，非本跑回归。
4. swap 在 12:30–13:20 的重叠窗口逼近满（12.28GB 用尽），但 available 始终
   ≥18GB，无内核 OOM 事件、无 RSS 帽接触；brec(12798MB)+defeq_cache(12956MB)
   峰值未同时出现。
