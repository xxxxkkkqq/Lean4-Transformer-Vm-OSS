# 021. 声明注入第二拍（G02）的四个实测结论与两处编码决定

- 状态：accepted（代理 G 落档，2026-09-19；总控验尸后生效）
- 关联：卡 010、ADR 020（载体与 level 测法的上位决定）、防线 §1.17（实测优先于推理）

## 背景

ADR 020 定了"kind/mode 同走 `TASK_CHECK` 锚帧 E2"和"is_prop 的 level 测法沿用
sort-零测"。G02 落地时撞到四件卡片与裁决都没预见的事，全部由真 lean 4.33.1
现跑取得；另两件是卡片留白处的编码选择。写下来是为了：(a) 下一拍（G03
G2-unsafe）不许重新推一遍，(b) 卡 012 补 universe 归一化时知道缺口的真实边界。

## 实测结论

### A. `Nat → True` 是 Prop：核 `infer_pi` 靠 `mk_imax` 折叠，图侧 INFER 已经一致

卡片要求"theorem 类型非 Prop（如 `Sort 1` / `Nat` 级）"，我按 PTS 直觉把
`Nat → True` 当非 Prop 写成期望触码 8 的用例。真核回的不是 `thmTypeIsNotProp`
而是 `declTypeMismatch`（`#KDECL` 通道；原文日志
`/home/xkq/logs/010G/g02_probe_kernel_classes.log`，源
`g02_probe_kernel_classes.lean` 同目录）：

```
SHOWTY G.D_imax (Sort (imax (succ zero) zero))
SHOWTY G.D_max (Sort (max zero zero))
KDECL2 thm_true OK
KDECL2 thm_nat thmTypeIsNotProp
KDECL2 axm_nat OK
KDECL2 def_nat OK
KDECL2 opa_nat OK
KDECL2 thm_imax OK
KDECL2 thm_max OK
KDECL2 def_imax OK
KDECL2 thm_sortraw thmTypeIsNotProp
```
（`Nat → True` 这条在套件里的 id 是 `thm_arrow`，当时因 `mkForall` 参数序写错
没跑出来，后来在套件里跑通。）
机理：`infer_pi`（`K/type_checker.cpp:144-166`）对每个 binder 做
`r = mk_imax(domain_level, r)`，而 `mk_imax(a, 0) = 0`（`K/level.cpp:112-114`，
即矩阵 D2 的智能构造）——体的 level 是 0（`True : Prop`），所以整体
`Sort (imax 1 0)` → 折叠成 `Sort 0` = Prop。**Prop 对依赖积封闭在这条路径上
就是 D2 折叠的产物。**

图侧实测同结论：`thm_arrow` → 图 code 1（declTypeMismatch 通道），与核一致
（`tests/test_decl_injection_vs_lean.py` B 段）。所以：

- **本拍不补 Pi 臂**：图的 INFER 侧构造 level 时已经做了等价折叠（它自己造
  `imax` 的场景有限，构造点即折叠点）。
- 语料改向：`thm_arrow` 变成"闸门通过、错误类别仍一致"的正面证据，另加
  `thm_pi_type`（`Nat → Nat`，体不是 Prop）覆盖"闸门在 Pi 上抛 8"。

教训入账：**"某个形是不是 Prop"这类判断不许按教科书直觉写期望**，一律先
`#KDECL` 现跑。这条与铁律 1（自写机不是判据）同源。

### B. 非归一 level 形在"经前端的环境"里不可达，只能由 raw `addDecl` 注入

`Sort (imax 1 0)` / `Sort (max 0 0)` 写在 Lean 源里，前端在存进环境**之前**就
归一化了。实测（`reference/olean_export.dump_env` 读存储的 `ConstantInfo.type`；
脚本与输出：`/home/xkq/logs/010G/g02_probe_frontend_normalizes_levels.{py,log}`）：

```
A_imax0 kind= def up= [] ty= Sort(level=LZero()) val= Const(name='True', levels=())
A_max0 kind= def up= [] ty= Sort(level=LZero()) val= Const(name='True', levels=())
A_max1 kind= def up= [] ty= Sort(level=LSucc(l=LZero())) val= Const(name='Nat', levels=())
A_imax_nested kind= def up= [] ty= Sort(level=LZero()) val= Const(name='True', levels=())
A_succ0 kind= def up= [] ty= Sort(level=LSucc(l=LZero())) val= Const(name='Nat', levels=())
```
（源定义依次是 `def A_imax0 : Sort (imax 1 0) := True`、
`def A_max0 : Sort (max 0 0) := True`、`def A_max1 : Sort (max 1 0) := Nat`、
`def A_imax_nested : Sort (imax (max 1 0) 0) := True`、`def A_succ0 : Sort (0+1) := Nat`。）
即 `def d : Sort (imax 1 0) := True` 的存储类型是 `Sort zero`，
核 `normalizes_to_zero` 与图的 syntactic 根比**必然同判**，缺口测不出来。
要拿到真正非归一的存储 level，只能绕开源语法：
`Lean.Expr.sort (Lean.Level.imax (Level.succ Level.zero) Level.zero)` 构
`Declaration` 后 `Lean.addDecl`（实测该常量导出为
`Sort(level=LIMax(a=LSucc(l=LZero()), b=LZero()))`）。

定性（供卡 012 与矩阵 G3a 行使用）：
- 分歧是真的、双向实跑取证的：`thm_imax` / `thm_max00` 核 = `OK`，图 = 假拒码 8；
  同类型同值的 `kind=definition` 对照（`def_imax`）双侧通过 → 分歧只在 is_prop 臂。
- 但**触发面被前端封住**：经 elaborator 的语料不会产生非归一存储 level，
  所以现实危害≈0；剩余风险是"外部/历史环境里存在 raw 注入的常量"（以及
  图侧自己构造 level 的其他路径，见 A）。
- 修法唯一：D1/D2（`mk_max`/`mk_imax` 智能构造）落进图的 level 判据 —— 归卡 012。
  缺口在册期间由 `KNOWN_GAPS` 的 XPASS 协议守着：修好之后若仍留在册，套件 **FAIL**，
  不许静默转绿（卡 009 协议）。

### C. `axiom` 的新增量是"带非零 kind 载荷"，不是"首次走 X=0"

我一度以为 G5（锚帧 X=0 = 无值）没有 run_check 用例——**错了**：
`tests/test_defeq_branches_vs_lean.py:424-426` 就是
`val=None → v=0 → drv.run_check([(t, 0)])`（KERNEL_COVERAGE 的 G5 行也写着
`test_defeq_branches_vs_lean.py g5×2` 是验它的）。
本拍 `axm_nat` 的真实增量是：X=0 的 axiom 形状第一次**同时带非零 kind 载荷**
（E2=1）过整条 CHECK 链，实测 `oracle=OK / graph=accept(4 步)` 与核一致
→ 说明 kind 载体与 G5 的 ax_go/ax_done 臂互不干扰；G5 既有实现不需要动。
（教训同 A：先用 grep 断言"没有用例"也是推理，也要核原文。）

### D. 拒码链上 8 的位置不是平局裁决

`environment.cpp:200`（`check_constant_val`）先于 `:201`（`is_prop`），故 8 排在
5 之后。实测支撑：`thm_typeexpected`（声明类型 `2`，kind=3）核 = `typeExpected`、
图 = 码 5（不是 8）。同时按构造互斥（`g1_fail` 要 `!ck_g1_ok`，`g3` 要 `ck_g1_ok`），
且码 7 只在值 infer 步抛（is_prop 之后才走到），
所以 `7>6>5>8>4` 记录的是内核次序，不是在解同拍竞争。
卡 011 继续加码时可按同一论证排位置，不必担心与既有臂抢同一拍。

## 编码决定（卡片留白处）

### E. 载体空闲性守卫的哨兵值 = `kind_code=1`（不是"任意非零数"）

`kinds=None` 写 E2=0，而 0 本身是合法取值（unspecified），所以"非零且必须全程
无效"的哨兵只能落在**闸门不看的那个 kind** 上。选 1（axiom）：改图前它必然惰性
（图根本没读 E2），改图后它仍然惰性（新臂只测 3）→ 同一个断言同时充当
"载体空闲性实证件"和"改图后的常设守卫"，不必为下一拍另造一件。
另在 `guard` 段加 `gate_off_kind0`：同一条 `Nat : 2` 在 kind=0 下 accept、
kind=3 下码 8 —— 钉死"unspecified 时闸门完全失效"（ENV_FORMAT §2.8 的 0 行）。

### F. 图侧 kind 解码按布局做满，不写成 `E2 == 3`

解码 = `mode := (E2 >= 8)`；`kind := E2 - 8*mode`；再测 `kind == 3`。
理由：`add_theorem` 恒用 **safe** checker（`environment.cpp:196`
`type_checker checker(*this, diag.get())`，没有 unsafe 分支），所以 is_prop 与
mode 位无关；若写成 `E2 == 3`，G03 一旦启用 mode=1（E2=11）就会让闸门
**静默失效**——那是最坏的一种错（不报任何东西）。成本仍是 O(1)。

### G. 读写两侧的布局常量分置 + 套件内漂移对拍

理想位置是 `expr/tokens.py`（读写两侧本来就共用它），但卡 010 的文件所有权表
冻结该文件。故：写侧常量在 `lean_vm/step_driver.py:28-45`，读侧在
`lean_vm/build_vm.py:224-235`，两处注释都指回 ENV_FORMAT §2.8，且
`tests/test_decl_injection_vs_lean.py` 的 `a0` 段逐常量对拍 + `check_e2()` 的
越界/类型校验（kind>4、mode>1、非 int → `ValueError`）。
若总控认为该合并进 tokens.py，是一次 4 行搬移 + 删掉 a0 的常量对拍，不需要重测语义。

## 取证方法（复现要用，别重新发明）

- 图未改动的基线 = `git show HEAD:lean_vm/build_vm.py` 拷进仓库快照
  `/home/xkq/logs/010G/g02_pre_repo/`（`tests/*.py` 用
  `Path(__file__).resolve().parents[1]` 定 sys.path，快照内解析正确）。
- **坑**：快照里 `model/` 若软链回真仓库，`model/compile_vm.py` 的
  `Path(__file__).resolve()` 会**穿过软链**把 sys.path 指回真仓库 → "改前编译"
  实际编的是改后图（两份 .sbin md5 相同才暴露）。快照要跑 compile_vm 必须真拷
  `model/*.py`。
- 新套件支持 `G02_LEGACY_BUILD_VM=<path>`（把改前 build_vm 以 `lean_vm.build_vm`
  模块名装载）与 `G02_ONLY=<section|case>`（开发期只跑子集，单次反馈 <2min）；
  env dump 路径按 PID 唯一（`reference/*` 写固定 /tmp 路径会互相踩）。

## 影响

- `docs/ENV_FORMAT.md` §2.8（E2 布局与取值表）、`docs/VM_SPEC.md` §7.4（码 8）
  与 §16.4（G3 臂、E2 载体路径、臂序依据、缺口表）、`docs/KERNEL_COVERAGE.md`
  G3 行改"已实现"并新增 G3a 具名缺口行（NOT-VERIFIED 标注）。
- 新常驻件：`tests/test_decl_injection_vs_lean.py`（a0 / guard / bcd）。
  进回归表由总控执笔（`scripts/*` 不在本拍可改集内）；实测单条图用例约 16s、
  全套约 15min、峰值 RSS 与 check_e2e 同量级（≤2GB）。
