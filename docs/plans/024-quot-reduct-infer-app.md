# 任务 024：quot reduct 的 `infer_app` 通道错型（q_acc_thm 图侧红行）

状态：**CLOSED（2026-10-22 立卡；2026-10-23 收口，总控）**。根因与立卡假设不同：
不是 `infer_app`/`I_ARG_S` 的 env 槽，而是 **quot reduct 的 whnf 交付**——
`quot_go` 按 `K/quot.h:64-68` 现造了新 App（reduct），但 WHNF 完成仍按
P6.1 约定交回**任务原闭包**；D_SW3 的 "unmoved" 恒等判据因此把"内核确实
归约了"读成"两边都没动"。修法（卡 024 盒 D，`build_vm.py` +40）：`quot_go`
把 reduct App 的操作数 env 记入该 token 的 X 槽（树上 App 恒 X=0，槽空闲），
`ms_sp_whnf` 交付按**token 形状**（`result_spine ∧ K=K_APP ∧ X≥1`）改取
spine root + 自带 env。行级：`q_acc_thm` graph ACCEPT 0（857.3s）、engine/
enginefull 也转 (T,0)（824/901s，窗口 1200）；对照 3 行仍 code 1。

## 现象

`q_acc_thm`（`Quot.liftOn_mk.mc`，kind=thm，最小 env）：
- oracle（现跑）= OK（accept）
- graph（Python 驱动器 `InjectionEnv.run_check`）= **REJECT code 1**，2958 微步，focus=0（无 reject 文案）
- refvm（补 quot 归约后）= ACCEPT 0（卡 022 拍 2 已修）
- engine = code 4（XFAIL，已知缺口同款；A 组引擎列按卡 023/ADR 027 记账）

## 已排除面（卡 022 拍 2，`~/logs/022B3/thm_graph1.log`）

1. **DEFEQ 面**：机器尾部 25 个 DEFEQ 帧在"补了 quot 归约的参照机"上**逐一复算为 True**
   （含完整 `liftOn …` 比较帧 `[7045] t=(733,5983) s=(660,6897)`）——没有"该绿判红"的 defeq 对。
2. **WP4 quot 臂确实点火**（`[7090]`/`[7161]`，quot_kind=2=Lift），非"没归约"。
3. prelude/driver 面与引擎无关（graph 腿在 Python 驱动器；卡 023 的数值悬崖只影响引擎）。

## 收窄到的面

机器末尾（s2911–s2925）在跑 `task=INFER` + `cont=I_ARG_S` 链（token 806..811@env0）——
即**对 quot reduct 求型**的 infer_app 参数检查，随后 code 1 收场。嫌疑：
WP4 `quot_go` 发射的 `App(f, a)`（`lean_vm/build_vm.py:1355-1367` 一带）的**结果 env 与
`a` 的捕获 env（mk 闭包 env SB）不一致**，使该 reduct 在 INFER 通道上解析出错。

## 触碰面

`lean_vm/build_vm.py`（WP4 quot_go 发射的 env 选择；必要时 `I_ARG_S` 车道），
`tests/test_decl_injection_vs_lean.py`（若需常驻钉），`docs/VM_SPEC.md`（§13/§16 相应节）。

## Verifier

- [ ] `q_acc_thm` graph 腿 = ACCEPT 0（oracle 现跑 OK）
- [ ] 对照行方向不变：`q_vm_swap`/`q_lvl_succ`/`q_lvl_maxv` 仍 code 1
- [ ] `tests/test_stepgraph_infer_defeq.py` 84/84（DEFEQ 热路径不变性）
- [ ] 五 canary（check_e2e / defeq_branches / mutation_reject / ref_vs_lean / level_vs_lean）
- [ ] 改 build_vm 后：`--sparse` 重编 + 引擎 34/34（双流）+ `stepgraph_vs_refvm` 37/37
- [ ] 35×4 mathlib 套件汇总行（XPASS 摘册归卡 022 拍 4）

## 风险

1. quot_go 是 WP4 的交付臂，动 env 会同时影响 whnf 通道——必须以 84/84 + 35×4 把门；
2. 不许按症状给 `App(f,a)` 加"补 env"门；要么 env 选择与 kernel `mk_app` 语义对齐，要么登记边界；
3. 与卡 023 的引擎取指悬崖解耦：本卡只对**图腿**负责。

## 盒 A（task-4，2026-10-23 凌晨 02:10–03:40）：arm 级证据 + 未修

### 已取得的证据（`~/logs/022B3/b3_qaccthm_frames{,2}.log`）

1. **203 个 DEFEQ 帧全部在"补 quot 的参照机"上复算为 True**（`0 / 203`
   非 True）⇒ DEFEQ 的**判定**面继续排除（不是"该绿判红"）。
2. 机器末拍落在 **`D_SW2`（soft-whnf 双边的 stuck-pair）通道**：
   `[7399] ST V1=660 X=6897 cont=D_SW2`（一侧 = `Quot.liftOn …` 应用，
   静态 token 660）、`[7400] WHNF V1=733 X=5983 caller=7399 E2=1`
   （另一侧 = `BVar(0)@5983`，其 value link 指向推断型的 liftOn 应用）、
   `[7403] ST V1=665 X=6897 cont=D_SW2` + `[7404] WHNF V1=736 X=5983`。
   即最后一拍比的是 **`(660,6897)` vs `(733,5983)`** 这一对（不是
   `D_XPI2` 域链——域链此前 6 层已逐层 True）。
3. **未取得**：该对的参照机取值。探针
   `.scratch/b3_qaccthm_swpair.py`（按"ST(D_SW2) + caller 指向它的 WHNF
   子任务"精确配对，并 replay）两次运行都异常退出于
   `load_raw` 的 "M-A closure artifact missing"——而同一 shell 里手动
   `load_raw` 正常（artifact 存在、路径一致），**怀疑探针进程环境的
   `HOME`/路径竞争，未定位**（`b3_qaccthm_swpair{,2}.log`）。
   已确认不是 artifact 缺失（`find ~/logs -name dump.jsonl` 三个都在）。

### 结论 / 下一步（本盒未改 `build_vm.py` 的 quot_go）

- 证据不足以定位"结果 env 槽错"，**不动 quot_go**（不按症状改热路径）。
- 下一盒建议（按此顺序，成本递增）：
  1. 修探针：在探针里 `print(os.environ.get("HOME"), Path.home())` 并把
     graph **stream 落盘 pickle**，后续 replay 不再重跑 786s 图；
  2. 用落盘 stream 复算 `defeq((660,6897), (733,5983))`；
     若参照机 True → 病在 `D_SW2/D_SW3` 的 stuck-pair 双车道（含 soft-whnf
     的 quot 归约是否在两边都发生）；若 False → 推断型本身错，
     回到 `infer_app`/I_ARG_S 的粘贴点；
  3. 只有 (2) 指到具体槽后才改 `build_vm.py`。

## 盒 B（task-5，2026-10-23 03:2x–04:5x）：参照机腿 = True（病在图侧），arm 级钉到 quot 臂漏火

### 0. 上一盒"探针异常"的定案（10 分钟内查清）

`load_raw(name)` 的路径是 `CLOSURES_DIR / name / "dump.jsonl"`（
`tests/test_mathlib_closure_vs_lean.py:112-121`），而闭包目录名是
**`Quot_liftOn_mk`（下划线）**；`.scratch/b3_qaccthm_swpair.py` 传的是
`'Quot.liftOn_mk'`（点）⇒ 必然 `artifact missing`。同一 shell 手动
`load_raw('Quot_liftOn_mk')` 正常。**不是 HOME/路径竞争**，是探针传名错误。
本盒探针开头打印 `HOME=… CLOSURES_DIR=… Path.home()=…` 固定该事实
（`b4_step1.log` 首行）。

### 1. 第一步（必做）：末拍对的参照机取值 = **True**

产物：`.scratch/b4_qaccthm_step1.py`（图跑一次 + stream 落盘
`.scratch/b4_qaccthm_stream.pkl`，7426 token）→
`.scratch/b4_qaccthm_replay.py` / `b4_step1_compact.py`（replay，无需重跑图）。
证据 `~/logs/022B3/b4_step1_verdict.log` 原文：

```
# DEFEQ frame census on ref+quot: non-True = 0 / 203

[pair] [7399] ST(D_SW2) t=(733, 5983) s=(660, 6897)  kinds(t,s)=BVAR/APP
  t decode = App(... Const(name='Quot.liftOn', ...) ... )      # bvar 的 value link
  s decode = App(... Const(name='Quot.liftOn', ...) ... )      # 声明型侧的同一应用
  t whnf = (9437, 9434)  App(fn=Pi(name='', ..., domain=Sort(u_1), body=Sort(u_4)), arg=Sort(u_1))
  s whnf = (9448, 9445)  App(fn=Pi(name='', ..., domain=Sort(u_1), body=Sort(u_4)), arg=Sort(u_1))
  ref+quot defeq(t,s) = True
```

即 **补了 quot 归约的参照机把两边都归约到同一个 reduct `f a` 并判 True**
（`f` = lift 的 arg_pos=3 实参 = 一个 Pi 类型，`a` = `app_arg(mk)`；
与 kernel `quot.h:64-68` 的 `mk_app(f, app_arg(mk))` 一致）。
⇒ 按立卡判据：**病在图侧 `D_SW2/D_SW3` 双车道**，不回到 `infer_app`/`I_ARG_S`。

### 2. arm 级根因：**图侧 quot 臂对该 whnf 一次都没点火**（`fire_quot` 漏火）

1. **火数对比**：同一 CHECK，参照机 `fires=3`（ADR 028 §8.5）；图侧扫全部
   `TASK_NAT` 帧只有 **2** 次 `OP_QUOT`（`.scratch/b4_quotfire_scan.py`）：
   ```
   OP_QUOT = 18  OP_REC = 11  OP_IOTA = 15
     NAT frame @7090 op=QUOT V1=18 X=1 E2=359 caller=7091
     NAT frame @7161 op=QUOT V1=18 X=1 E2=359 caller=7162
   ```
   而失败拍落在 ST(D_SW2) `[7399]` + WHNF 子任务 `[7400] WHNF 733@5983`
   —— 该次 soft-whnf **之后没有任何新的 `OP_QUOT` NAT 帧**（7162 之后为零）。
2. **失败对的帧链**（`b4_verdicts.log` + `b4_framechain.log`）：机器在
   **frame 7045**（`t=(733,5983)[BVAR]` vs `s=(660,6897)[APP]`，即上面那一对）
   上提交 **False**，随后逐层上抛
   `7045 → 7044(ST/D_SPA) → 6898 → 6176 → 6109 → 6082 → 6014 → 6006 →
   5998 → 5997(ST/CK_TY)`，在 CK_TY 落 `reject code=1`。
   首枚 False 判定的状态原文：
   ```
   # t=  747.6s REJECT at beat 2958 state={'A': 0, 'B': 0, 'C': 0, 'D': 5997, 'E': 1, 'F': 0} code=1
   # t=  747.6s   false beat 2948 state={'A': 0, ..., 'D': 7045, 'E': 1, 'F': 0}
   ```
3. **因果**：`733@5983` 是**经 bvar value link 到的闭包**（值 = `Quot.liftOn …`
   应用），不是原始递推的直接焦点。该次 whnf 走 delta 展开到 `Quot.lift` 应用后，
   `fire_quot`（`lean_vm/build_vm.py:997-1002`）没有成立 ⇒ 不推
   `NAT(OP_QUOT, caller, 1)` 子任务 ⇒ 没有 `quot_go` 交付（也不发 reduct 节点）
   ⇒ 该对保持两张**未归约**的 lift 脊 ⇒ `D_SW3` 判"两边都没动"⇒
   走 proof-irrel/脊剥离链（`[7406..7422]` 的 Pi 域链，域/体各自 True）⇒
   最终仍以 False 收场。
   **与参照机的差别只在"归约发生/不发生"这一点上**：参照机两边都归约到
   同一 reduct（上节），图侧都没归约，于是拿两张不同来源（一张来自 value
   link、一张来自声明型编码）的脊逐项比，必然有一段不同。
4. **未钉到的最后一格（诚实登记）**：`fire_quot` 的这个合取里是哪一项不成立
   尚未取证——候选（按可能性排序）：
   a. `q_pend0 = _chain_v2(SC, CHAIN_MAX)` 读到的参数链不足 6 项（该 lift
      应用是**经 env 解析**进入的，不是从 App 脊直接降下来的；`SC` 的
      填充路径与直接脊不同）；
   b. `_kind_eq_raw(eX, 0, One)` 这个"const 特化节点"闸（`eX` 取
      `fV0+1` 的 X，`build_vm.py:348`）；
   c. `q_is_rec`（`_quot_kind(fV0)` 读取的 T_ENV_QUOTVAL 在 delta 展开后的
      头上是否仍可读）。
   下一盒的第一步 = 在这三个字段上各加一条**只读**探针（不改热路径），
   用已落盘的 stream（`b4_qaccthm_stream.pkl`）复算即可，不需重跑 748s 图。

### 3. 本盒**未改** `build_vm.py` 的理由（失败纪律）

- 90 分钟盒内未把 `fire_quot` 的失败项钉到字段级；按"不许按症状改热路径"，
  不动 `quot_go`/`fire_quot`/`D_SW2`。**无 build_vm 变更 ⇒ 无需重编 sbin、
  无需重跑引擎 34/34**（本盒也没跑引擎）。
- 已确认**不是** env 槽/`I_ARG_S` 粘点：参照机对同一对判 True，且
  `203/203` DEFEQ 帧全 True。

### 4. 附带：83 步 B 复现形的常驻钉（已落地，`lvl_lam_poly`）

- 行体 = **真实语料**：`Nat_testBit_land` 闭包 dump 的 `id` 条目
  （`ty = {"k":8,"bi":1,…}`，`val = {"k":7,"bi":1,…}`），即
  `fun {a : Sort u} (x : a) => x : ∀ {a : Sort u}, a → a`；期望判定由
  `#KDECL` oracle 现跑给出（代码不钉判定）。
- 上一盒两次失败的**真实原因**（本次用 `.scratch/b4_id_pin_probe.py` 的
  4 变体 oracle 探针定位）：`Lean.Expr.forallE`/`lam` 的实参序是
  **(name, type, body, binderInfo)**，两次手写 splice 都把 `BinderInfo`
  放进了 **type 槽** ⇒ oracle `declTypeMismatch`/`typeExpected`。
  探针原文（`~/logs/022B3/b4_id_pin_probe.log`）：
  ```
  A_bi_implicit    oracle=OK      # forallE `a (sort u) (...) implicit
  B_mk             oracle=OK
  C_all_default    oracle=OK
  D_ty_arrow       oracle=<lean error: mkArrow returns CoreM Expr>
  ```
  即**同一行体、正确实参序**即可被 oracle 接受——不是"行体不能表达"。
- 常驻钉落在 `tests/test_decl_injection_vs_lean.py` 的 `LEVEL_ROWS`
  （行 id `lvl_lam_poly`），本节证据见 §5。

### 5. 行表与常驻钉结果

**常驻钉行（`lvl_lam_poly`）逐腿实测**（`~/logs/022B3/b4_pin_row.log`、
`b4_id_pin_probe.log`）：

| 腿 | 结果 | 证据 |
|---|---|---|
| oracle（`#KDECL` 现跑，行体 = 闭包 `id` 的 ty/val） | **OK** | `b4_id_pin_probe.log` 的 `A_bi_implicit oracle=OK`（同一 splice 文本） |
| graph（`_lvl_env` + `run_check`，lps=[u]，`CHECK_KIND_DEFINITION`） | **ACCEPT code=0 steps=69** | `b4_pin_row.log` |

整节 `G02_ONLY=lvl` 的汇总行**本盒未取到**（该节每行都会
`build_step_graph()` 重建一次图，实测 >17 分钟仍未结束，超本盒时间盒）——
登记 **NOT-VERIFIED**；行本身两条腿已各自单跑通过，且 `section_lvl` 的
`oracle.get(cid)`/`KNOWN_GAPS` 键都是 `lvl_lam_poly`（单 decl 行形状），
无插桩缺口。

**q_acc_thm 行表（本盒实测部分）**：

| 行 | oracle | graph | refvm |
|---|---|---|---|
| q_acc_thm | OK（历次不变） | **code 1（2958 步；本盒两次独立重跑同值）** | **ACCEPT 0**（`b4_rows_refvm.log`） |
| q_vm_swap（对照） | declTypeMismatch | 未跑（本盒未改图；上一盒 b3 实测 code 1） | **code 1**（本盒实测） |
| q_lvl_succ（对照） | declTypeMismatch | 同上 | **code 1**（本盒实测） |
| q_lvl_maxv（对照） | declTypeMismatch | 同上 | **code 1**（本盒实测） |

对照行 graph 腿 = **NOT-VERIFIED（本盒）**：`build_vm.py` 本盒零改动，
单行 graph 跑 ~700s，时间盒内跑不完三行；方向不变的判据取
refvm 腿（本盒实测）+ 上一盒 b3 的 graph 记录。

### 6. 本盒交付与未决

- **代码改动 = 0 行**（`lean_vm/build_vm.py` 未动）⇒ **不需要重编 sbin、
  不需要重跑引擎 34/34，`stepgraph_infer_defeq` 84/84 也不受影响**。
- 唯一改动：`tests/test_decl_injection_vs_lean.py`（+1 行 `lvl_lam_poly`
  + `BI_IMPLICIT` import）。decl_injection 套件的行数 37 → **38**
  （回归脚本的总数注释如写死 37，收口时同步）。
- 未决：`fire_quot` 合取中失败的那一项（三候选见 §2.4）；钉住后用落盘
  stream 复算即可，不必重跑 748s 图；真正修复预计在
  `fire_quot` 的取链/取字段或 `quot_go` 的交付形状上，**不是** `infer_app`
  的 env 槽（该面本盒已用参照机腿排除）。

## 盒 C（task-6，2026-10-23 04:0x–05:2x）：`fire_quot` 三候选**全部证伪**；真locate 在 reduct 的 whnf 交付

### 0. 方法（只读，零 build_vm 改动）

不重跑 748s 图：把 `build_vm.fire_quot` 的每一项在**已落盘 stream**
（`.scratch/b4_qaccthm_stream.pkl`，7426 token）上用 Python 逐字段复算
（`.scratch/b5_fire_quot_probe.py`）：`SA..SF` = STATE 字段；`fV0` = `V0@SA`；
`eX = X@(fV0+1)`；`_mhead/cid = V2@(n_consts+1+cid)`、`_quot_kind` = 其
`K==T_ENV_QUOTVAL` 时的 V1；`_chain_v2(SC,16)` 走 V2；`_fv0(pos)=pos>=1?V0@pos:0`；
`_QUOT_INIT` = 96 个 cid 里是否有 `CK_QUOT`。

### 1. 第一步结果：合取**没有失败项**（(a)(b)(c) 全部证伪）

`~/logs/022B3/b5_conjuncts.log` 原文（整条 stream 只有两个焦点是 Quot 常量的 state）：

```
[ 7089] A=  345 C= 7088 D= 7048 E=733 F=  359 K=  5 name=Quot.lift qk=2 eX=0 mkpos=5
        chain=[348, 350, 352, 354, 356, 358, 0] mk_v0=358 arg_v0=354 fire_at=7090
        FIRE_GATE=PASS is_const=T QUOT_INIT>=1=T q_is_rec=T eX==0=T CHAIN_MAX>=mkpos=T mk_v0>=1=T arg_v0>=1=T
[ 7160] A=  345 C= 7159 D= 7122 E= 0 F=  359 K=  5 name=Quot.lift qk=2 eX=0 mkpos=5
        chain=[348, 350, 352, 354, 356, 358, 0] mk_v0=358 arg_v0=354 fire_at=7161
        FIRE_GATE=PASS … （同上全 T）
# OP_QUOT NAT frames (whole stream) = 2: [7090, 7161]
```

- **(a) `q_pend0` 链长**：不是 <6 项，而是 **恰好 6 项 + NULL**
  （`SC`=7088→7086→…→7078→0，`V0` 依次 348/350/352/354/356/358 = lift 体的
  6 个实参 `#5 #3 #4 #1 #0 #2`）。lift 应用确实经 env 解析进入，但**pend 链完整**。
- **(b) const 特化闸 `eX==0`**：`eX = X@(cid+1) = 0`，**成立**（Quot.lift/
  Quot.liftOn 的 ENV_HDR.X 都不是 nat-op 码）。
- **(c) `q_is_rec`**：`qk=2`（Lift），**成立**。
- 其余：`is_const`、`_QUOT_INIT=1`、`CHAIN_MAX>=mkpos(5)`、`_fv0(mk_entry)=358>=1`、
  `_fv0(arg_entry)=354>=1` 全 T。
⇒ 盒 B §2.4 的三个候选**全部证伪**；`fire_quot` 在两次 whnf 上**都点了火**。

### 2. 顺带证伪："reduct 未物化"

`quot_go` 也点了火，reduct 是**发出来的 raw App 节点**（`~/logs/022B3/b5_trace.log`）：

```
p7106 K=6(APP) V0=354 V1=857     # t 侧 reduct = App(f=#1@7076, a=#2@4183)
p7177 K=6(APP) V0=354 V1=654     # s 侧 reduct
```

两个操作数解码出来与参照机的 reduct **逐字相同**（`~/logs/022B3/b5_reduct_decode.log`）：

```
--- f = #1 body: (354, 7076)
    Pi(binfo=0, domain=Sort(u_1), body=Sort(u_4))          # = 参照机 whnf 的 fn
--- a = mk arg: (857, 4183)
    Sort(u_1)                                              # = 参照机 whnf 的 arg
--- lift q (mk app): (858, 4183)  = Quot.mk (Sort u_1) (Pi…) (Sort u_1)   # q_ok 的来源
--- lift spine root: (359, 7076)  = Quot.lift (Sort u1) (Pi…) (Sort u4) (Pi…→…) (Pi…Eq…) (Quot.mk …)
```

即 **fire + delivery + reduct 形状三者都对**，盒 B「reduct 未物化 ⇒ 未归约的脊逐项比」
的因果链不成立（它把"两次点火"当成了"漏了第三次点火"，而第三次点火在参照机里
是 reduct 内部的再归约）。

### 3. 真正失败的位置：reduct 的 **whnf 交付**把结果退回原脊

t 侧（`b5_trace.log`，state 序列）：`quot_go` 在 7106 发出 reduct 后，
`A=354(f) B=7076 C=7107(pend a) F=7106(spine root)`；随后 whnf(f) 走
`354@7076 → 860(BVar#1)@4183 →` 链路，在

```
p7118 STATE A=733 B=5983 C=7107 X=7048(WHNF frame) E2=1 F2=7106
p7120 STATE A=733 B=5983 C=7107 X=7047         E2=1 F2=7106   # WHNF 帧弹出
p7121 FRAME ST V1=733 V2=7045 X=5983 F2=25                     # 把 (733,5983) 当结果存下
```

**交付的是原始闭包 (733,5983) 而不是 spine root 7106**。s 侧同形
（`p7189 A=660 B=6897 …`、`p7191 A=660 B=6897 X=7121 F2=7177`，ST 帧存 (660,6897)）。
于是 D_SW2 拿到的是"两边都没动"，与参照机"两边都归约到同一 reduct"分岔。

关键矛盾（下一盒的入口）：
- `decode_closure(b, 860, 4183)` 能一路解到 `f = Pi(Sort u1 → Sort u4)`（上面 §2），
  说明 **link 链上的正确值是 Pi**；
- 但机器在同一 env 4183 上给 `BVar#1` 走 `4183→3691`（1 hop）后落到 **733@5983**
  （= 正在 whnf 的那个闭包），而不是 env 4183 链上 `V1=4 → 3691 → V0=685`。
  即 **bvar 解析落点与 `decode_closure` 不一致**，或是"re-entry 检测"把它变成
  stuck 并让完成逻辑取了 `A/B` 而非 `F(spine root)`。
- 已知相关物：`T_DEFCACHE` 在 7036/7040 记过 `(741,4183)≡(538,6897)`、
  `(731,5983)≡(538,6897)`（同脊前缀的兄弟对，全 True），env 4183 的链头
  `LINK(V0=716, V1=5, V2=3691)`——`V1` 是链深度标签、`V0` 是值位置，
  而 7066–7076 那段**新造链**的 `V1` 是 0..5（升序）且 `X` 全是 4183。

### 4. 本盒**未改** build_vm（按纪律）

钉到的不是三候选，而是一个**新的、跨 bvar 解析与 whnf 完成/交付两处**的槽；
按"不许按症状改热路径、第 2 次失败就停手写证据"，本盒只交付定位与设计约束，
**`lean_vm/build_vm.py` 零改动**（⇒ 无需 py_compile/重编 sbin/跑引擎）。

### 5. 下一盒的设计草案（≤10 行，待总控批）

1. 先用 `decode_closure` 为 oracle：对 env 4183 逐 hop 打印 `(pos, V0, V1, X)` 与
   `decode(pos, env)`，确定 `BVar#1@4183` 的**正确值**（预期 = 链上 `V1=4` 那条
   `LINK(V0=685, X=3639)`，而非 733@5983）——一行探针，无需跑图。
2. 若确认解析落点错：病在 7066–7076 那段 link 链的**深度标签/方向**与
   `_walk` 的 hop 语义不一致（`fire_quot` 的 `_chain_v2` 用 hop，link 用 V1），
   修点应在"造链"臂（`LINK` 的 V1 分配），而非 `fire_quot`/`quot_go`。
3. 若解析落点对（733@5983 就是 f 的白盒值 = re-entry）：病在**完成/交付**取
   `A/B` 而非 `F`（spine-root 约定 §10.2 的 quot 分支漏用），修点应在
   `quot_go` 之后那次 whnf 的 delivery 选择项；需 `stepgraph_infer_defeq` 84/84 +
   35×4 把门。
4. 两者都需要重编 sbin + 引擎 34/34 + 五 canary —— 下一盒统一做，本盒不碰。

## 盒 D（task-7，2026-10-23 04:1x–）：选 (ii) 修 whnf 的 minted 脊根交付

### 0. 两个候选的判决（按证据，不按症状）

**候选 (i)「造链臂」证伪**（`~/logs/022B3/b6_env_probe.log` / 探针
`.scratch/b6_env_probe.py`）：

- 7066–7076 那段链是 `Quot.lift` **lambda 应用**的 beta 链（`LINK` 的
  `V1(depth)=0..5`、`V2=prev`、`X=4183` 全链同底），`_link` 语义与 `_walk`
  一致：`BVar#1@7076` 1 hop 落到 `LINK@7074` 的 `V0=860 / X=4183`，
  `BVar#1@4183` 再 1 hop 落到 `LINK@3691` 的 `V0=685 / X=3639`——
  `decode_closure(354,7076)`、`decode_closure(354,4183)` **都**
  解出同一个 `Pi(Sort u_1 → Sort u_4)`（= 参照机 reduct 的 fn）。链的
  深度标签/方向正确，**不需要改**。
- 盒 C 留下的"伴生矛盾"（"BVar#1@4183 落到 733@5983"）由此作废：
  `733 = K_BVAR#0`（不是 Sort），`5983 = LINK(V0=863,V1=1,V2=4219,X=4183)`；
  `(733,5983)` 是 D_SW2 **t 侧原闭包**，与 bvar 解析无关。

**候选 (ii)「whnf 完成交付」成立**（`~/logs/022B3/b6_delivery_probe.log`，
在盒 C 落盘 stream 上逐字段复算 build_vm 的交付判据）：

```
p7117: A=3691 B=3691 C=7107 D=7116 E=860 F=7106  frame task=WALK V1=3691 V2=7048 X=0 F2=4183
       walk_done=1 fE2=1 par_infdq=0 par_bv=0  mk_stuck=1 result_spine=1
       spine_root kind=6(K_APP) env(X)=0  sr_minted=0  ms_sp_whnf=1
       OLD delivers (nbV1,nbX) = (733,5983)      # t 侧
p7188: 同形，OLD delivers (660,6897)             # s 侧
```

即：`f` 的 whnf 经 bvar 走链落到 **binder marker**（`LINK.E2=1`）⇒ `mk_stuck`
（kernel：whnf 对卡住的 bvar 应用返回**整条应用**）⇒ 父帧是 WHNF ⇒ 走
`ms_sp_whnf`（`build_vm.py:1498-1512` 一带），交**任务原闭包** `(nbV1,nbX)`。
这条约定（VM_SPEC §11.5 P6.1）在"脊根 = 原闭包"时正确，但 `quot_go` 已经
**现造了一个新 App**（`K/quot.h:66` 的 `mk_app`）并把 STATE.F 指向它，
原闭包不是脊根了 ⇒ 交付错。

### 1. 修点（只改这一处语义）

1. **发射**：`quot_go` 发射 reduct App 时把它的**环境**写进该 App 令牌空闲的
   `X` 槽（树上的 App 恒 `X=0`，故 `K_APP ∧ X≥1` 唯一标识"机器现造脊根"）。
   该环境 = 发射拍的 `STATE.B` = mk 闭包环境（`q_root` 的 whnf 结果环境），
   reduct 的两个操作数（`f` 的 thunk、`a`）都在它下面解码——
   `b6_env_probe.log`：`(7106,4183)` / `(7177,6897)` 解出
   `App(Pi(Sort u_1)(Sort u_4), Sort u_1)`，与参照机 `whnf(t)/whnf(s)`
   **逐字相同**，且 `defeq = True`；反例：`(7106,7076)` 解成
   `App(Pi, Quot.mk …)`（错），`(7106,0)` 直接 `bvar 1 beyond env`。
2. **交付**：`sr_minted` 时 marker-stuck 交付交 `(SF, X@SF)`，否则维持
   `(nbV1, nbX)`（原谱系）。其它脊根臂（rec/cs/iota 的 PEND 链、`X=0` 的树
   App）由形状门挡住，**逐位不变**。

### 2. 为什么不是"松门"或按案例特判

门是**令牌形状**（App 脊根带自己的环境），不是常量名/cid、不是行 id、不是
"看起来像 lift"。语义依据：`whnf_core` 的 App 分支把 `quot_reduce_rec` 的
返回值当**新 Expr** 继续用（`K/type_checker.cpp:393-407`，
`K/quot.h:64-68`），reduct 的操作数是已求值的值；json token 环境里"值"是
`(pos, env)`，所以现造 App 的脊根必须带上它自己那份 env。

### 3. 本盒改动（`lean_vm/build_vm.py` 三处、一条规则）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `build_vm.py:1029-1041`（`v_done` 之后） | 新增 `sr_env` = `X@SF`、`sr_minted` = `result_spine ∧ K@SF==K_APP ∧ sr_env≥1`（"机器现造脊根且带自己的 env"） |
| 2 | `build_vm.py:1495-1516`（`ms_sp_whnf` 交付） | `A = sr_minted ? SF : nbV1`，`B = sr_minted ? sr_env : nbX`；其余走链/软失败/`mk_dq` 臂不变 |
| 3 | `build_vm.py:7431-7437`、`7452-7461`（raw 发射两支：WMEMO 关/开） | `quot_go` 发射 reduct App 时 `raw_X = SB`（mk 闭包环境） |

只此一条规则；没有按常量名/cid/行 id/closure 的特判，也没有"看起来像 lift 就
松门"。`docs/VM_SPEC.md` §13.8 新增第 5 条记录该约定（含边界）。

### 4. 行表（本盒实测，原文见 §5）

| 行 | oracle | graph | refvm | 证据 |
|---|---|---|---|---|
| **q_acc_thm** | OK | **accept=True code=0（XPASS；原 code 1，857.3s）** | **accept=True code=0** | `b6_row1.log` |
| q_vm_swap（对照，期望 code 1） | declTypeMismatch | **code 1（PASS）** | code 1（PASS） | `b6_controls.log` |
| q_lvl_succ（对照，期望 code 1） | declTypeMismatch | **code 1（PASS）** | code 1（PASS） | 同上（3 行合计 211.0s，`[OK]`） |
| q_lvl_maxv（对照，期望 code 1） | declTypeMismatch | **code 1（PASS）** | code 1（PASS） | 同上 |
| q_lvl_maxuu（同族接受行，不回归） | OK | **accept=True code=0（原 XFAIL）** | accept=True code=0 | `b6_maxuu.log`（535.6s） |
| q_lvl_maxuu_2p（同上，随前缀带入） | OK | **accept=True code=0（原 XFAIL）** | accept=True code=0 | 同上 |
| WP4 quot 最小 env 语料（附加门） | oracle 4.33.1 | **7/7 corpus + A=4 meta + C-stuck=y，0 failures** | — | `b6_quot_unit.log` |
| `tests/test_stepgraph_infer_defeq.py`（84/84，附加门） | — | 见 §6（本盒跑完/未跑完按原文） | — | `b6_stepgraph84.log` |

**注意（给总控的收口项）**：两条腿都是 XPASS 而不是 PASS —— `KNOWN_GAPS` 里
`q_acc_thm` 挂着 A 族项（`tests/test_mathlib_closure_vs_lean.py:372` 的
`a_rows`），而 A 族在 q_acc_thm 上已经不再触发（refvm 腿在盒 B 也已接受）。
harness 因此打 `[FAILED] wall 857.3s` + 两条 `FAIL … XPASS: remove the
KNOWN_GAPS entry`。**这不是判定不一致**（judge 的 `agree` 两条都真），而是台账
需要摘条；`tests/` 不在本盒写权限内，留给总控（同 `q_lvl_maxuu` 若也 XPASS，
一并摘）。

### 5. 证据路径

- `~/logs/022B3/b6_row1.log`（q_acc_thm 三腿，含 graph/refvm 的 XPASS 行）
- `~/logs/022B3/b6_controls.log`（三条对照行）
- `~/logs/022B3/b6_quot_unit.log`（`tests/test_quot_graph_vs_lean.py` 全绿）
- `~/logs/022B3/b6_delivery_probe.log`（交付判据在落盘 stream 上的复算）
- `~/logs/022B3/b6_env_probe.log`（reduct 闭包的环境选择：4183/6897 解出参照机
  whnf 结果，7076/0 解码错；含 `defeq=True`）
- 探针：`.scratch/b6_delivery_probe.py`、`.scratch/b6_env_probe.py`、
  `.scratch/b6_dump2.py`、`.scratch/b6_tokens.py`

### 6. 未决 / 下一盒（含"要不要重编"）

- **需要重编 sbin**：本盒改了图（`v_done` 侧新增 `sr_env/sr_minted` 两次
  fetch + 两次 `_select`，raw 发射两支各多一层 `_select`），
  `model/step_vm_022_scratch.sbin` 是 2026-10-17 的旧图 ⇒ 引擎/enginefull 两腿
  与 sbin 相关的结论**必须**在下一盒 `python3 -u model/compile_vm.py --sparse`
  之后重跑（双流 34/34 + `stepgraph_vs_refvm` 37/37）；本盒按任务书**未重编、
  未跑引擎**。
- **`stepgraph_infer_defeq` 84/84**：本盒并行跑（`b6_stepgraph84.log`，
  进程 `setsid` 留在后台继续写日志）。截至收盒（05:38）：
  **63 例 PASS / 0 例 FAIL（05:38 收盒时的行数，进程仍在后台跑）**（含 `deq_big`/`deq_eta*`/`deq_stuck_args`/
  `deq_irrel*`/`deq_rec*`/`deq_caseson*` 等共享 whnf/delivery 热路径的用例），
  尚未到 `84/84` 汇总行 ⇒ 最终汇总行记 **NOT-VERIFIED（本盒）/ 下一盒必跑**，
  但"已跑部分无回归"是实测。
- **35×4 mathlib 套件**：NOT-VERIFIED（时间盒；下一盒随重编一起）。
- **KNOWN_GAPS 摘条**（`tests/test_mathlib_closure_vs_lean.py:372-376` 的
  `a_rows`）：`q_acc_thm`、`q_lvl_maxuu`、`q_lvl_maxuu_2p` 三条在本改动后
  graph/refvm 两腿都已 accept（XPASS），需总控/测试工程师摘条 → 否则套件
  以 `[FAILED]`（XPASS）收场而判定本身一致。
- **A 族（binder-identity）面**：本次交付修的是 quot reduct 的 whnf 交付，
  `q_acc_thm`/`q_lvl_maxuu*` 变绿说明它们的 A 族失败在本行上是由"未归约的脊"
  引发的，不是 binder-identity 机制缺失；`q_acc_def`/`q_acc_rfl`/`n_acc_fcomp`
  等其它 A 族行是否同因未测（下一盒一并跑，若也变绿则 A 族的账要重记）。
