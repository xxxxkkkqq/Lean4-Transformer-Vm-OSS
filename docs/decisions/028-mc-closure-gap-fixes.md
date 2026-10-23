# ADR 028 — M-C 四缺口修复合同（卡 022 拍 1：语义设计 + 修复合同）

状态：**ACCEPTED（022 拍 1，2026-10-17。拍 1 诊断由语义设计师执行、
其探针全量落 .scratch/dbg022_*，设计师代理在 ADR 落盘一步停摆，本文由
总控按落盘证据 + 探针重跑原文代笔；独立复核（干净上下文，只读）判
FAIL-narrow：机制/内核引用/健全性/冻结裁决/证据引文全过，仅 4 处文本
精度缺陷（复核 Findings 1-4，含一处对冻结文件现状的误述），已全部
修订并入（见 §7 复核记录）。）**

## 0. 结论总览（先读这节）

15 个 gap 行四组（A/B/C/E）经拍 1 逐步追踪后**收拢为两个图侧机制 +
两个组内残差**，比立卡时的四根因假设更集中：

1. **binder-identity 恒等机制缺失**（A 9 行 + B 4 行 + C 1 行，共 14 行的
   直接或前置根因）：defeq 的 bvar-bvar 分支只认非零 bid 相等，而 bid 只在
   defeq 的 binder 比较分支被 stamp、infer 路径从不 stamp——一切
   「bvar 实参类型 vs 实例化 Pi domain」的真证明比较把同一个 binder 当
   两个 fvar。修复 = A1（同链节点恒等）+ A2（T_PI_CLO.V2 marker 载体），
   已在 RefVM 上以内存补丁全量验证（A 组 7/9 行转绿、DEFEQ_CORPUS
   零漂移、抗混同探针通过）。C 组不是独立的门缺陷：kind gate 从未点火
   （CK_G1 帧数为零）是因为**型侧 infer 先死于 A 面**——A 落地后 gate
   的输入才存在。
2. **INFER 任务无 K_MDATA 臂**（E 1 行）：Nat.add 的声明类型
   `∀ (n m : Nat), Nat` 的 Pi domain 带 MData(Nat) 包裹，CHECK 通道的
   CK_G0 型侧 infer 第 2 微步即触 kind 11 → ERR_UNSUPPORTED（code 4）。
   立卡时的 brecOn 链嫌疑**被证据否定**（value 树从未被走到）。
3. **组内两残差**（q_acc_thm、n_acc_thm）：A1+A2 下仍 code 1，失败面
   已钉到原文（见 §1.6/§1.7），根因未完全定案——登记为拍 2 诊断义务
   （NOT-VERIFIED，不许拍 2 无证据硬改）。

kernel 引用均为 `/home/xkq/lean4/src/kernel/`（4.35 master，只读参照）；
判据是 4.33.1 二进制，本卡全部行的 oracle 判定与设计预期一致，未出现
源码-二进制分歧。

## 1. A 组 — binder-identity bvar defeq（9 行，三通道共有）

### 1.1 现象与行清单

`q_acc_def / q_acc_thm / q_acc_rfl / q_lvl_maxuu / q_lvl_maxu0 /
q_lvl_max0u / q_lvl_maxuu_2p / n_acc_fcomp / n_acc_thm`——graph+refvm+
engine 三通道一致 code 1，oracle OK（~/logs/012MC/guarded_final.log）。

### 1.2 根因（我方代码，@HEAD）

- `lean_vm/ref_vm.py:1129-1144` bvar-bvar 分支：`lt[6] and lt[6] == ls[6]`
  只认非零 bid；`_stamp_bid` 调用点全集 = defeq binder 臂（:1121、
  :1177-1184）+ `_try_eta` 对其自建新 marker（:1299，与恒等缺口无关）；
  `infer_lambda` 从不 stamp（infer() 全函数无 _stamp_bid 调用）——
  infer 产的 marker 在任何 defeq binder 比较触及它们之前一律 bid-less，
  恒等条件永假（实测失败 marker 正是 stamp 前状态）。
- 图侧同构缺口：`lean_vm/build_vm.py:4822-4845`（D_BV2/D_BV3 的
  「same bid → True / distinct bid → stuck pair」臂，注释自述只认
  bid）；`build_vm.py:3842-3848`（bid 机制说明）；XPI 臂的 tpc bid
  读取在 `build_vm.py:4884-4892`。
- 证据链（拍 0 已钉）：失败 defeq 对两侧解码逐字相同（Sort(u) vs
  Sort(u)）；两侧 BVar 沿各自 env 链解析到**同一 binder marker link 行**
  `(31,77,0,0,0,1,0)`（`.scratch/dbg_mc_{defeq,chain,bid}.py`）。

kernel 对照：`t == s` 恒等短路是 `quick_is_def_eq` 的第一行
（K/type_checker.cpp:834-837，`if (t == s || succeeded_before(t, s))
return l_true`）。流内同一 marker link 行 = 该恒等式的 stream 对应物。

### 1.3 修复合同（拍 2 实现，已在 RefVM 验证其形）

**A1 · 同链节点恒等**（dbg022_patch.py `a1_defeq` 的 A1' 块）：
bvar-bvar 分支中，把两侧沿父链走 `V0`/`W0` 步得到的**链节点位置**
相等作为恒等条件，与既有 bid 相等条件并联：

```
pt, ps = t_env, s_env
for _ in range(V0): pt = b.stream[pt][3]
for _ in range(W0): ps = b.stream[ps][3]
if pt == ps: return True        # A1'（在 bid 检查之前）
```

外加说明：defeq 循环顶的 `(t_pos,t_env)==(s_pos,s_env)` 短路（t==s 的
直接 stream 对应物）**HEAD 已有**（ref_vm.py:1087-1088，复核 Finding 1
核实）——所以本合同对 ref_vm 的全部改动 = 上面这一个 bvar-bvar 块，
仅此一处。图侧落点：D_BV2/D_BV3 臂
（build_vm.py:4822-4845 一带，帧已携带两侧 link 位置，加「同位置」
门即可），不改任何 bid 既有语义。

**健全性**（关键，拍 1 已验）：marker link 行按发射分配、链节点位置
唯一标识 binder 实例；「同链节点 ⇒ 同 binder」在两种危险形状下被探针
证伪风险为零——同形异 binder 仍判异：

```
same marker row via two chains: vanilla=False A1+A2=True (fix target: False -> True)
two distinct markers, identical shape: vanilla=False A1+A2=False (must stay False)
M1 row=(31, 431, 0, 0, 0, 1, 0) M2 row=(31, 431, 0, 0, 0, 1, 0)   ← 内容全同仍判异
```

（dbg022_a_final.py 原文；M1/M2 行内容逐字段相同，位置不同 → 不混同。）

**A2 · T_PI_CLO.V2 marker 载体**（dbg022_patch.py `stamped_infer` +
XPI 臂 `a2` 块）：`infer_lambda` 产出 T_PI_CLO 行时，把该 lam 自己的
binder marker 链位置 stamp 进**空闲的 V2 字段**（row[3]）；XPI（跨形
Pi：T_PI_CLO vs K_PI）臂在 `_binder_marker` 找不到 marker 时改从该
载体取。为何必须：被拒的「只查 X」形只翻转 3/8 行——**最后一层 Pi 的
body env 是 env 0 上的 value-link 链，永远走不到 binder marker**，且
其 body token 是 K_APP、无 X 可查（dbg022_a_final.py 首轮实测，被拒
方案记录在案）。图侧落点：I_LAMBODY 的 T_PI_CLO 发射
（build_vm.py:3870-3874）stamp V2；XPI 臂（build_vm.py:4884-4892 一带）
在 tpc body env 非 marker 时取 V2。kernel 语义对应：infer_lambda
（K/type_checker.cpp:125）创建的 local decl 就是 Pi 型所引用的那个
local decl——恒等是构造事实，流内需要载体把它带出来。

**拍 2 实现前置义务**：grep 确认今天没有任何消费者读 T_PI_CLO 行的
row[3]（V2 空闲声明必须核实，不许沿用拍 1 假设）。

### 1.4 验证结果（拍 1 在 RefVM 上的内存补丁全量原文）

A 组 9 行 × {vanilla, A1, A1+A2}（~/logs/022B1/a_final.log）：

```
  [A1+A2  ] q_acc_def        ACCEPT        [A1+A2  ] q_lvl_max0u     ACCEPT
  [A1+A2  ] q_acc_thm        REJECT 1  ←残差    [A1+A2  ] q_lvl_maxuu_2p ACCEPT
  [A1+A2  ] q_acc_rfl        ACCEPT        [A1+A2  ] n_acc_fcomp     ACCEPT
  [A1+A2  ] q_lvl_maxuu      ACCEPT        [A1+A2  ] n_acc_thm       REJECT 1  ←残差
  [A1+A2  ] q_lvl_maxu0      ACCEPT
```

（A1 单独：失败点从 `infer_app: argument type mismatch` 移到
`decl 0: value type mismatch`，不修复——A2 必需。）

判定不变性（DEFEQ_CORPUS 全语料）与钉行：

```
vanilla->A1: 0 verdict changes / A1->A1+A2: 0 verdict changes / vanilla->A1+A2: 0 verdict changes
pin deq_fvar_args: A1+A2 verdict = False / pin deq_fvar_swap_no: A1+A2 verdict = False
pin deq_lam_no: A1+A2 verdict = False / pin deq_lam_alpha: A1+A2 verdict = True
```

### 1.5 ref_vm 冻结条款裁决（卡的显式问题）：**准修（YES，A1+A2 皆入「最小内部修复」）**

理由四条：
1. A1 是 kernel `t == s` 短路（type_checker.cpp:837）中**唯一还缺的那半
   （闭包 env 下的链节点恒等）**：ref_vm 侧改动只是一个分支条件块
   （循环顶 (pos,env) 恒等 HEAD 已在，见 §1.3），纯「加恒等」、不含
   任何新语义面。
2. A2 是**同一恒等语义**在 infer 产出行上的最小载体（约 10 行：
   stamp 一处、读一处、bid 统一一处），不引入第二套实现；不修它则
   冻结机对「一切带变量实参的真证明」整类误拒（M-C 全部 accept 行
   所在类），oracle 通道本身失效——恰是冻结条款要保护的可用性。
3. 判定不变性有实测：DEFEQ_CORPUS 三级对比零变化 + 四钉行保持 +
   抗混同探针（§1.3）。
4. 反方案（不修 + 登记 channel boundary）会让 refvm 腿对 A 组 9 行
   永久错拒、且与修好的图语义脱钩（stepgraph_vs_refvm 等价面反向
   撕裂），比修更伤冻结条款的目的。

边界记录：若拍 2 的 V2 空闲性核查失败（发现既有消费者），A2 改走
新字段/新行类并回本 ADR 修订，不许覆盖语义。

### 1.6 残差 q_acc_thm（拍 2 诊断义务，根因 NOT-VERIFIED）

A1+A2 下仍 `REJECT 1: decl 0: value type mismatch`。钉死的证据
（~/logs/022B1/a_thm_diff.log）：

```
check-level call: idx=439 verdict=False
structural divergences (first 6): 3
  root.body.body.body.body.body.body.fn.fn.arg: BVAR 1 vs 4
  root.body.body.body.body.body.body.fn.arg: KIND BVar vs App
  root.body.body.body.body.body.body.arg: KIND BVar vs App
False calls inside the check-level subtree: 1
  [439] T 1001@0 S 671@0
```

读法：全部 Pi domain 层比较通过后，失败收敛到**最内层 Eq spine**；
T（infer 产 T_PI_CLO @1001，K=34）一侧的 de Bruijn 索引比 S（声明型
K_PI @671）**整体浅 3 层**（1 vs 4；Quot.liftOn_mk 前三个隐式 binder
恰是 {α γ r}），且两个等式项位置 T 是裸 BVar、S 是 liftOn 应用——
不是重索引能对齐的同一项，是 infer 侧**闭包 env 链在深处少挂了
隐式 binder 帧**或对错误子项求型。拍 2 从 dbg022_a_thm{,_diff,
_residual}.py 的证据起手，把闭包 env 构造钉到行，修完该行转绿；
不许未定位就改。

### 1.7 残差 n_acc_thm（拍 2 诊断义务，根因 NOT-VERIFIED）

面 = `REJECT 1: infer_proj: structure type expected`（vanilla 与
A1+A2 同面）。And.left 的值 `fun {a b} (h : And a b) => h.left` 的
`.left` 走卡 019 的 INFER-PROJ 元数据通道（值树 census：K_PROJ 节点
为零，`.scratch/dbg022_e_node.py` 同法）。proj 臂要 h 的型，h 是
bvar——怀疑 infer_lambda 的 env 链解析出的型不是实例化结构头
（与 §1.6 同属多 binder lam 链 env 构造家族）。图侧另证：步 197 处
D_XPI2 链尾 reject code 1 focus=0（~/logs/022B1/a_final.log 尾段）。
拍 2 同 §1.6 处置。

### 1.8 被拒方案（A 组）

- **给 infer 路径也 stamp bid**（对齐 defeq 路径）：需在每个 infer
  闭包构造点改动，触碰面大且 stamp 时机无 kernel 对应物；A1 的链节点
  恒等已覆盖其语义，弃。
- **X 咨询形**（XPI 只查 X 字段）：首轮实测仅翻转 3/8 行（§1.3），
  最后一层 Pi 无 X 可查，弃（证据留 dbg022_a_final.py docstring）。
- **按 marker 行内容判恒等**（行 tuple 相等 ⇒ 同 binder）：被抗混同
  探针直接证伪——M1/M2 内容全同而是不同 binder（§1.3 原文），必须
  用链节点位置。

### 1.9 验证义务（拍 2）

1. A 组 9 行三通道全绿（graph/refvm/engine，最小 env，MC_ONLY 逐行）。
2. 两残差行诊断证据链补进本 ADR 修订版（不许无证据转绿）。
3. DEFEQ_CORPUS 零漂移 + deq_fvar_args/swap_no/lam_no/lam_alpha 四钉 +
   抗混同微探针**常驻化**进 tests/test_decl_injection_vs_lean.py
   （同-row-双链 True / 异-marker 同形 False 两行）。
4. T_PI_CLO.V2 空闲性核查（grep 全消费者）。
5. 五 canary + mathlib_closure 套件 + stepgraph_vs_refvm 84/84 零漂移
   （A 触 DEFEQ 热路径，判定不变性由全套件对拍证明）。
6. 重编译 `--sparse` + 引擎对拍 34/34。

## 2. B 组 — 宇宙多态 LAM 值 def 的图侧假拒（4 行，graph+engine）

### 2.1 现象

`v_acc_def / n_acc_def_id / v_lvl_maxuu / n_lvl_maxuu`——`id.mc :=
fun {a : Sort u} (x : a) => x : ∀ {a : Sort u}, a → a` 图+引擎 code 1，
RefVM 接受（= kernel 判定），83 微步复现、env 规模无关
（dbg_mc_empty.py）。

### 2.2 根因（拍 1 定案）

**与 A 同一机制的图侧面**，不需要独立修复臂。83 步追踪
（~/logs/022B1/bce.log）：CK_RES 顶比较 → XPI（T_PI_CLO 推断型 vs
K_PI 声明型）逐层下行，s52 建 marker [136]，s54/s80 D_BV2 走链，
**最后一层 Pi 的 T_PI_CLO body env 是 env 0 上的 value-link 链、走不到
binder marker**（A2 docstring 同一事实），bvar-bvar 比较把一个 binder
当两个 fvar → s83 reject code 1。RefVM 对照（同 log）：

```
[B-refvm] infer(val) OK -> (21,0) Pi(Sort u, Pi(BVar(idx=0), BVar(idx=0)))
[B-refvm] declared = Pi(Sort u, Pi(BVar(idx=0), BVar(idx=1)))  (binfo=1 首层)
[B-refvm] defeq = True
```

kernel grounding：def 检查路径 = `environment::add_definition` 的
checked 分支——安全 def（id.mc 即是）走 else 分支 K/environment.cpp:
179-188（infer 值型 @:184 → `is_def_eq(val_type, type)` @:185 →
`definition_type_mismatch` throw @:186；:163-176 是 unsafe 分支，语义
相同）；lam 头值走 `infer_lambda`（K/type_checker.cpp:125）。RefVM 顶比较路径能过（其
`_binder_marker` 在 XPI 内自行恢复 marker），infer 路径不能——正是 A
的缺口面在 XPI 臂上的呈现。

### 2.3 修复合同

**无独立机制**：拍 2 落 A1+A2 的图侧实现后，B 组 4 行随 A 转绿。
RefVM 侧本就绿（A1+A2 内存补丁下保持绿，~/logs/022B1/be_refvm.log
vanilla/A1+A2 双列全 ACCEPT）——不许反向动参照机（卡风险 3）。
验证义务：4 行 graph+engine 转绿；83 步复现形按卡要求常驻化进
decl_injection 差分行（id.mc 形）。

### 2.4 被拒方案

- 改编码让 infer 产不同闭包形状：格式级变更、越卡触碰面，弃。
- 只修 bid stamping：同 §1.8 第一条。

## 3. C 组 — thm kind gate 不点火（1 行，q_tnp）

### 3.1 现象

q_tnp（type := Quot.lift 的型，含 u/v 的 fold 形）graph+engine code 1
（值侧失败码），oracle thmTypeIsNotProp（8）。concrete sort 型
（v_tnp/n_tnp）两行 graph+engine 正确 8。

### 3.2 根因（拍 1 定案：gate-REACH，非排序、非门电路缺陷）

q_tnp 图侧追踪（~/logs/022B1/c_reach.log + bce.log）：

```
[C-graph] REJECT code=1 focus=485 env=1072 steps=142
  focus decode: decode_closure: bvar 1 beyond env
CK_G1 (cont=68) frames in stream: []        ← gate 从未点火
  INFER frame[...] owner conts: ['CK_G0(type-side)'] ×8
```

CK_G0（型侧 ensure-sort）先要 infer 声明型；该 infer 在步 142 死于
**A 族面**（bvar 越链）——门还没有输入就先死了。v_tnp 对照（同 log）：
`REJECT code=8 focus=44 steps=4`，CK_G0→INFER→CK_G1→WHNF 顺序正确，
`LVL_N2Z_DEPTH = 8`。

A1+A2 内存补丁下的型侧 infer 对照（c_reach.log）：

```
[A1+A2] infer OK: Sort(level=LIMax(LSucc(u), LIMax(LMax(u, LSucc(0)), LIMax(LSucc(v), LMax(u, v)))))
  sort-level-root=601 n2z=False
```

kernel 排序与判定：`environment::add_theorem`（K/environment.cpp:
189-204）——`if (!checker.is_prop(type)) throw theorem_type_is_not_prop`
@ :202 **先于**值检查（:204-205）；图侧 CK_G0→CK_G1→值的顺序与内核
一致，无需重排。`is_prop` = `ensure_sort(infer_type(e))` +
`normalizes_to_zero(sort_level)`（K/type_checker.cpp:383-388，注释明言
「imax 1 0 denotes Prop without being syntactically zero」——必须按
规范化判零，不许语法判）。q_tnp 的型规范后是含参 IMax fold，
n2z=False ⇒ 非 Prop ⇒ 8。

### 3.3 修复合同

**拍 3 不预设门改动**：A 落地后 q_tnp 的型侧 infer 应通，gate 得到
输入后按既有 n2z 通道（D8，K/level.cpp:174-186 规则族；探测显示
LVL_N2Z_DEPTH=8 对本 fold 深度 ~5 足量）判 False → 8。拍 3 的义务 =
复跑 q_tnp：若仍非 8，才允许动门（按 level.cpp 规范化规则扩 fold
通道），并回本 ADR 修订记录。

### 3.4 被拒方案

- 把门挪到值检查之后：违反内核顺序（environment.cpp:202 先于 :204）。
- 语法判 Prop（sort level 字面为 0 才算）：违反 is_prop 注释的显式
  禁令（imax 1 0 反例）。

## 4. E 组 — Nat.add 重加 ERR_UNSUPPORTED（1 行，v_acc_natadd）

### 4.1 现象

graph+engine code 4，RefVM 接受，oracle OK。立卡嫌疑（MData/brecOn
链）**被证据否定**——value 树从未被走到。

### 4.2 根因（拍 1 定案）

**图侧 INFER 任务无 K_MDATA 臂**。证据（~/logs/022B1/e_node.log）：

```
static stream length 1461; ty root=1405 val root=1460
[E-graph] REJECT code=4 focus=1400 env=0 steps=2
focus [1400] static-encoded=True K=11 ... focus decoded = MData(child=Const(name='Nat'))
referenced by nodes: [1399, 1405]      ← [1405] 即声明型根（K=8 Pi）
type tree kinds: {Const 3, Pi 2, MData 2}    value tree kinds: {...} MData nodes: []
frames: [1463]ST/CK_G0 → [1464]INFER → [1466]ST/I_PIDOM(dom=1400!) → [1467]INFER
```

Nat.add 的声明型 `∀ (n m : Nat), Nat` 的两个 Pi domain 各带
MData(Nat) 包裹；CHECK 通道 CK_G0 型侧 infer 在第 2 微步触达
MData 节点（kind 11），INFER 任务无臂 → ERR_UNSUPPORTED。
代码面：`grep K_MDATA lean_vm/build_vm.py` 只命中 ST walk 门
（:752）与 DEFEQ 臂（:4463-4464）——INFER 任务零命中，与行为一致。

通道架构对照（同 log）：

```
RefVM.infer(declared type): VMError code=4: infer: token kind 11 at 1400
(RefVM.check never infers the declared type; it only infers the value and
 defeqs against the type — whnf unwraps MData there)
RefVM.check: ACCEPT (1, 0)
```

即 RefVM 的 infer **同样**无 MData 臂；RefVM.check 之所以接受，是它
从不 infer 声明型（只 infer 值 + 对型 defeq，whnf 会剥 MData）。
图侧 CK_G0 为取 sort level 必须 infer 型——所以图的 INFER 必须补臂。

kernel grounding：MData 处处透明——infer 递归子项
（K/type_checker.cpp:339 `case expr_kind::MData: r = infer_type_core(
mdata_expr(e), infer_only)`）、whnf 剥裹（:478-479 whnf_core、
:742-743 whnf）、defeq 比子（:845-846）。

### 4.3 修复合同

图侧 INFER 任务加 is_mdata 门臂：对 K_MDATA 节点**重派 INFER 到子
节点 V0**（MData 推断透明：子的型即 MData 节点的型），发射落点 =
build_vm.py:6626-6633 的 INFER kind 分派（`bad_i` 枚举无 is_mdata 项、
`rej_code_i = reglu(rej_i, One*4)` 即 code 4 源头——复核定位）；臂内
写法参照 ST 门的 is_mdata（:752、walk 消费 :1420）与 DEFEQ 的
deq_mdata（:4463-4464）。无新值构造、无格式变更。
engine/refvm 腿不动：engine 随 sbin 重编译继承；refvm 腿走 check()
通道本就接受。

边界登记：RefVM.infer 的 MData decline 保留（冻结机，其 check 路径
不需要）。若 stepgraph_vs_refvm 语料含「INFER 面 MData」形状导致
84/84 漂移，登记 channel boundary 而不是改冻结机；拍 3 跑 84/84
定夺。

### 4.4 被拒方案

- 编码期剥 MData：全消费者格式级变更、需 ENV_FORMAT 版本化与全语料
  复验，相较单臂添加严重过度，弃。
- 只在 CK_G0 型走查里跳 MData：值型 infer 的嵌套位置同样会触达
  （Pi domain 深处），修不到面，弃。

## 5. 拍 2/3 实现顺序提案

1. **拍 2 = A**（A1+A2 图侧 + ref_vm 最小修复 + 两残差诊断收口）。
   理由：B 由同机制覆盖、C 以 A 为前置——A 不落地则 B/C 无从验证。
   残差（q_acc_thm/n_acc_thm）在拍 2 内完成诊断，A 组 9 行不全绿
   不进拍 3。
2. **拍 3 = E（INFER MData 臂）+ C 复验（预期零门改动）+ B 复验**。
   E 与 A 无耦合，但同触 build_vm，串行避免图文件冲突。
3. **拍 4 = 测试工程师**全量回归 + 15 行 XPASS 摘册验证。

每拍验证链（卡 022 Verifier）：最小复现行 → 五 canary →
mathlib_closure 套件 → stepgraph_vs_refvm 84/84 → `--sparse` 重编译
→ 引擎对拍 34/34。

## 6. 证据与工具索引

- 探针（.scratch/，拍 1 全量）：`dbg022_patch.py`（A1+A2 验证形，
  importable）、`dbg022_a_final.py`（9 行表+不变性+抗混同+n_acc_thm
  图迹）、`dbg022_a_thm{,_diff,_residual}.py`（q_acc_thm 残差）、
  `dbg022_bce.py`（B 83 步/C 对照）、`dbg022_be_refvm.py`（B/E 参照
  机对照）、`dbg022_c_reach.py`（C gate-REACH 定案）、
  `dbg022_e_node.py`（E 定案）、`dbg022_common.py`（TracedDriver）。
- 重跑日志（总控代笔时取证，2026-10-17）：`~/logs/022B1/`（a_final /
  a_thm / a_thm_residual / a_thm_diff / bce / be_refvm / c_reach /
  ce2 / e_node .log）。dbg022_bce.py 尾部有一处 NameError 探针 bug
  （E 段 `ex` 未定义，rc=1）——E 段结论以 e_node.py 重跑为准。
- 判定基线：~/logs/012MC/guarded_final.log（35 行四通道，0206705 代
  码态 = 当前 HEAD）。
- 引文口径：本文各引块以日志为准，个别长行作了省略/节写（如 §2.2 的
  B-refvm 三行、§4.2 的 stream 长度行）；逐字判据一律以 ~/logs/022B1/
  与 .scratch/ 探针 stdout 为准。

## 7. 复核记录（独立复核，2026-10-17，干净上下文只读）

判定：**FAIL-narrow → 修订后收货**。复核面 A-I 全过：kernel 引用
逐条核到行、我方代码引用全部命中、§1.4/§3.2/§4.2/§1.6 引文与日志
逐字相符（复核者重跑 dbg022_e_node.py 复现 byte-for-byte）、A1 健全
性在代码面复核（ref_vm._link 与 StreamBundle.push 均纯 append 无
dedup/interning；图侧 I_LAMSORT marker bid=自身位置，build_vm.py:1197、
:3850）、A2「V2 空闲」前提复核者已预验（全部 T_PI_CLO 消费者只读
字段 1/2/4/5；发射管线三腿齐备：图槽 raw_V2_c build_vm.py:3594、
driver step_driver.py:163、引擎 I_RAW2 vm.cpp:741）、冻结裁决与
不变性证据判 sound（复核者 diff 了探针 flags-off 拷贝 vs HEAD defeq
行为等价，vanilla 列 ≡ HEAD）。

五条 findings 处置：
1. **FAIL 级（已修）**：§1.3 误述「HEAD defeq 循环无顶恒等」——实际
   ref_vm.py:1087-1088 已有；本合同 ref_vm 改动收窄为仅 bvar-bvar 块。
2. 已修：§1.2 `_stamp_bid` 枚举补 :1299（_try_eta 自建 marker）+ 
   bid-less 断言限定「stamp 前」。
3. 已修：§2.2 kernel 引用改指安全分支 :179-188（throw @:186）。
4. 已修：§4.3 落点改写 build_vm.py:6626-6633（bad_i 枚举 + code 4
   源头）。
5. 已修：×7→×8 + §6 引文口径注。

复核者登记的残余风险（全部并入拍 2/3 验证义务，无新增开放面）：
B/C 行转绿是机制推定（无图侧内存补丁预演），由拍 2/3 行级验证 +
84/84 套件把门；DEFEQ_CORPUS 不变性扩面靠 canary/stepgraph 套件；
A2 marker 匹配无对抗语料，靠套件门；两残差可能暴露 A1+A2 覆盖不到
的更深层 infer 闭包 env 缺陷——已登记 NOT-VERIFIED 拍 2 诊断义务。

## 8. 拍 2 审计修订（2026-10-22，总控代码审计后追加）

**背景**：拍 2 图侧实现（A1+A2 落图 + ref_vm 最小修复）完成后，总控逐行
审代码（对照 `K/quot.h`、`K/type_checker.cpp:248-289/:393-407` 原文）
并对残差行独立抽验（`MC_ONLY=oracle,graph,refvm,q_acc_thm`，wall
786.8s：graph code 1 / refvm ACCEPT 0）。审计改变了本 ADR 的两处判断：

### 8.1 两残差的根因不是 A 家族（§1.6/§1.7 的"NOT-VERIFIED"结案）

- **q_acc_thm**：冻结机**缺 quot 递归子归约**（`K/quot.h:39-75`；
  `grep -i quot ref_vm.py` 原先零命中）。判定性证据：只加该规则
  → `refvm+quot q_acc_thm ACCEPT (fires=3)`，q_acc_def/q_acc_rfl 零
  点火（`~/logs/022B3/quot_experiment1.log`）。"T 比 S 浅 3 层"是
  closure 比较的正常投影，§1.6 三假说全部证伪。
- **n_acc_thm**：`infer_proj` 缺 kernel 的头剥离 + 参数实例化。证据
  `~/logs/022B3/nacc_trace1.log`：`whnf(child type)` 返回 App spine 根
  （K=6），旧代码要求裸 K_CONST 直接死；`And` 是 nparams=2，旧代码
  另有 `nparams!=0 → ERR_UNSUPPORTED`。**图侧对同一行本来就 ACCEPT**
  （卡 019 I_PROJ 通道），§1.7 引的"structure type expected"是参照机
  文案，不是图的故障面。

### 8.2 冻结裁决（准修，条件生效）

两处 ref_vm 补全（quot reducer；infer_proj 头剥离/参数实例化）**准修**：
kernel 逐条移植、无新判定面、带 `文件:行`、有回退点（撤
`ref_vm.py:93-99/147-188/224-236/1063-1101` 五段即回退，图侧不受影响），
属 §1.5 "最小内部修复"先例。**条件**（缺一即回退为 channel boundary）：
1. `infer_proj` 必须实现 `K/type_checker.cpp:288` 的 Prop 保护
   （`is_prop(结构型) && !is_prop(字段)` → 拒）——否则删掉
   `nparams!=0` 保守拒会把接受面放宽到"参数化 Prop 结构 + 数据字段"，
   构成 refvm 通道假接受；
2. 依赖字段（kernel :281-284 `has_loose_bvars` 分支）必须**保守拒**
   （ERR_UNSUPPORTED），不许静默 peel；
3. 带 index 的归纳族边界（bundle 的 `structures` 元组无 nindices）
   必须登记；负向证据（上述两条各一枚探针 + 常驻钉）必须落
   `tests/test_decl_injection_vs_lean.py`；
4. quot 分支位置与 `:393-407` 的 quot-先-delta 顺序不一致处，代码或
   注释必须自洽（quotInfo 常量无值（dump 实测 val=NONE），行为等价，
   但引用与实现不许两张皮）。

### 8.3 验证口径纠正

卡 022 Verifier 写的 "stepgraph_vs_refvm 84/84" 是两套套件的串读：
`test_stepgraph_vs_refvm.py` = **37/37**（已绿），
`test_stepgraph_infer_defeq.py` = **84/84**（DEFEQ 热路径不变性门，
拍 2 必须跑，solo 真值 3755.4s / cap 6100|5000）。拍 2/3/4 一律按
此口径记账。

### 8.4 拍 2 内必须收口的两项（不许移交）

1. **引擎 q_acc_def 1 步固定点**：022 件同入口 NOT_DONE（逐 token
   dump 从 stream 3475 起每步追加同一 `T_STATE(33,357,2055,0,3466,0,0)`），
   而 021 件同入口给 code 1 —— 是 A1/A2 新路径下的**图可达自环**
   （liveness 缺陷），不是"入口协议不同"可结案的。要求：引擎 check
   预兆帧 vs `step_driver.InjectionEnv.run_check` 预兆帧的 token 级
   对比定分叉；若状态图上可达，修 DEFEQ/D_BV3 混合形（双 bvar 之外
   的 bvar 侧）的下一跳。禁止调大 cap。
2. **q_acc_thm 图侧**：WP4 quot 臂已点火（2 次），失败面收窄到
   quot reduct 的 `infer_app` 参数检查（token 806..811@env0）——
   `App(f,a)` 的结果 env 与 a 的捕获 env 一致性需 arm 级证据并修。

### 8.5 拍 2 收口实测（2026-10-23 01:1x）

**两残差的闭环**（都不属于 A 家族，§8.1 已定）：
- `q_acc_thm`：冻结机补 quot 递归子归约 → refvm ACCEPT 0（fires=3）。
- `n_acc_thm`：`infer_proj` 补头剥离/参数实例化 + Prop 保护/依赖字段保守拒
  → refvm ACCEPT 0；图侧本来就绿（卡 019 通道）。

**A 组 9 行三通道（本拍实测终版）**：

| 行 | oracle | graph | refvm | engine |
|---|---|---|---|---|
| q_acc_def | OK | 0 | 0 | **0（引擎位置内建精确化后）** |
| q_acc_thm | OK | **1（卡 024）** | **0** | **-1（同卡 024 面）** |
| q_acc_rfl | OK | 0 | 0 | 0 |
| q_lvl_maxuu/maxu0/max0u/maxuu_2p | OK | 0×4 | 0×4 | 0×4 |
| n_acc_fcomp | OK | 0 | 0 | 0 |
| n_acc_thm | OK | 0 | 0 | 0 |
| 对照 q_lvl_succ / maxv | declTypeMismatch | 1/1 | 1/1 | 1/1 |

即 **8 行 × 3 通道全绿**；唯一红行 `q_acc_thm` 在 graph/engine 两侧同面
（quot reduct 的 `infer_app` env），已立**卡 024**、refvm 腿已绿。

**引擎侧意外收获（ADR 027 补条款）**：`q_acc_def` 的 1 步固定点是
**位置取指的 fp32 悬崖**（q≳2900 时 argmax 由噪声决定），引擎在每位置
层栈后把 slots 1..3 写回精确内建值即修复（`engine/vm.cpp` +12，无格式/
图/sbin 变更），34/34 双流一致、q_acc_def 引擎腿 `DONE 1 0 1883`。

**不变性门**（全 rc=0，`~/logs/022B3/`）：`stepgraph_infer_defeq`
**84/84（0 pinned）**、`stepgraph_vs_refvm` **37/37**、`ref_vs_lean`
**34/34**、`ref_infer_defeq` **82/82**、`check_e2e` A15/15+B15/15、
`mutation_reject` A16/16+B8/8、`defeq_branches` 零 FAIL、
`level_vs_lean` 37/37（kdecl 段）、引擎对拍 **34/34**（`stream_same`
34/34）。XPASS 计数 = 已与 oracle 对齐但 `KNOWN_GAPS` 未摘的行
（摘册归拍 4），无普通 FAIL。

**冻结条款条件**（§8.2）全部满足：Prop 保护已实现、依赖字段保守拒、
index 族边界登记、负向探针 + `ipr_pd_data` 常驻钉（`oracle=invalidProj`,
graph code 12）。

### 8.6 拍 3 / 拍 4 / 卡 024 收口（2026-10-23）

**卡 024（q_acc_thm graph）根因与 §8.4 的假设不同**：不是 `infer_app` 的
env 槽，而是 **quot reduct 的 whnf 交付**。`quot_go` 已按 `K/quot.h:64-68`
现造 reduct App（`mk_app(f, app_arg mk)`，图侧 7106/7177），但 WHNF 完成仍按
P6.1 约定交回**任务原闭包** `(733,5983)`/`(660,6897)`；D_SW3 的 "unmoved"
恒等判据把"内核确实归约了"读成"两边未动"，逐项比未归约脊后 frame 7045
判 False。修法（`build_vm.py` +40）：① `quot_go` 把 reduct App 的操作数 env
记入该 token 的 **X 槽**（树 App 恒 X=0，槽空闲）；② `ms_sp_whnf` 交付按
**token 形状**（`result_spine ∧ K=K_APP ∧ X≥1`）改取 spine root + 自带 env。
形状门保证其它脊根臂（rec/cs/iota 的 PEND 链、X=0 树 App）逐位不变。
行级：`q_acc_thm` graph ACCEPT 0（857.3s），engine/enginefull 亦 (T,0)
（824/901s；引擎调用窗口 600→1200s，见下）。对照 3 行仍 code 1。

**拍 3**：E 组 INFER `K_MDATA` 透明臂（`K/type_checker.cpp:339`）→
`v_acc_natadd` graph ACCEPT 0；B 四行（`v_acc_def`/`n_acc_def_id`/
`v_lvl_maxuu`/`n_lvl_maxuu`）三通道绿；C `q_tnp` = code 8（gate 按 n2z
通道点火，无需改门）。B 形常驻钉 = `lvl_lam_poly`（Nat 闭包真实 `id`
条目，oracle 现跑 OK + graph ACCEPT 0）。

**拍 4**：15 条 `KNOWN_GAPS` 全摘（A 9 / B 4 / C / E），35 行 × 4 通道
**全绿（0 FAIL / 0 XFAIL / 0 XPASS）**；引擎调用窗口 600→1200s
（`MC_ENGINE_TIMEOUT`，实测 q_acc_thm 824.1s / enginefull 901.1s，只动
窗口不动断言）；mathlib 套件按 closure 三分段（卡 025）帽按实测 ×1.4
校准。**终验证件 = `model/step_vm_022b_scratch.sbin`**（dims 58,597 /
lookups 7,680 / nnz 363,318 / md5 `7c7c3cc2f6f19084cdf0d9b480948f67`）；
引擎对拍 34/34 双流、`stepgraph_infer_defeq` 84/84。

**不变性门**（全 rc=0）：84/84、37/37、34/34、ref_vs_lean 34/34、
ref_infer_defeq 82/82、check_e2e、mutation_reject、defeq_branches、
level_vs_lean。
