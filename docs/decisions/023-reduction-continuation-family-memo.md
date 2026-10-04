# 023. 归约续推与状态携带家族：ENV 动态名盘点 / I_CASE 主前提 whnf 续推 / mode 位跨 ST 续体（卡 016 拍 A 语义设计 memo）

- 状态：proposed（拍 A 产出；正式条款落 VM_SPEC §16.7 stage C 续、实现裁决与
  摘 XFAIL 留拍 B 图逻辑工程师）
- 作者：Lean4 语义设计师（2026-09-25）
- 权威：kernel 只读参考 `/home/xkq/lean4/src/kernel/`（4.35 master；行号为实测，
  与 4.33.1 二进制行为不一致处以二进制为准——本 memo 三处关键行为均经
  4.33.1 oracle 现跑复证，见 §4）。期望结果全部来自 oracle 现跑，零预置。
- 范围：只读代码 + 本 memo + 卡 016 执行段。未改任何代码/测试/VM_SPEC。

---

## §1 归约层 ENV 动态名盘点（卡 016 第 3 条）

### §1.1 机制基座（判定「静态可见 vs 运行时查表」的两条通道）

- **名字 → cid 的唯一合法通道 = ENV_HDR.X 名字键控标签 + 无展开扫描**
  （`build_vm.py:510-560` `_SCAN_OPS` 机制）：编码器按**常量名**写 X 标签
  （`expr/tokens.py:382-384`，`NAT_OP_CODES`/`CTOR_ID_CODES`/`STR_ID_CODES`
  三表，对 toy 与注入常量一视同仁），图侧在 0.._NSCAN 头部位置上做无展开
  线性扫描得 cid 与存在计数。这是铁律 3「ENV 元数据 + 名字扫描 + legacy 回退」
  的载体。
- **静态引用闭包**：stage C 最小化（`tests/test_decl_injection_vs_lean.py:1203-1262`
  `_g04_env`）从 carrier roots 出发沿 stored ty/val 树（`_g04_walk`）+
  recursor 规则 rhs / ctor / induct 元数据遍历闭包。凡「归约臂自己按名字
  合成节点」的名字都不在这棵闭包里——这就是 010G bisect 实证的失效模式
  （`/home/xkq/logs/010G/g04b_bisect.log`：单加 `Nat.pred` 把 nat d1 从
  stuck@30 翻正为 halt@122）。

### §1.2 盘点表（每条：归约臂 → 动态名 → 静态可见？ → ENV 保证）

| # | 归约臂（build_vm.py:行） | kernel 对应（file:line） | 运行时动态查表/合成的名字 | 静态闭包可见？ | ENV 侧保证方式 |
|---|---|---|---|---|---|
| D1 | nat-op 计算臂派发（fire1/fire2 `:761-762`，opg1-10 `:607-616`） | reduce_nat，K/type_checker.cpp:702-733 | 无名字合成（字面量数字链算术）；**派发键** = 头部 X 名字标签 | 参与常量在输入项中静态可见；X 标签按名写入任何编码流（tokens.py:382-384） | X 标签表即保证；无标签 → natop=0 不点火（优雅） |
| D2 | Nat.rec iota 构造循环（is_build `:678-679`；15 步 rhs 现造 CONST(pred)@step0 `:2892`、CONST(rec)@step8 `:2895`） | inductive.h:100-118（rhs=`rule->get_rhs()` 来自 env 规则，:107 lparams 实例化） | **Nat.pred、Nat.rec** | **否**——rhs 由图硬形状现造，存表树无此静态引用（bisect 实证） | `_PRED_CID/_REC_CID` 名字扫描 `:532-533` + `rec_ids_ok` 门 `:1020`：缺席 → `stuck_r` 交付 spine 根（优雅，禁伪 cid）；stage C 闭包须保留两名 |
| D3 | casesOn succ 规则构造循环（is_cs_build `:682-683`；3 步 rhs 现造 CONST(pred)@step0 `:2942`） | inductive.h:99-118（get_rec_rule_for :100 按 major 头匹配） | **Nat.pred**（cs 变体不造 Nat.rec，但门仍双查 `_REC_OK∧_PRED_OK` `:1049-1050`） | **否**（同 D2；iv 族 stage C 闭包不含 → g04iv_eG4IV2 直接死因） | 同 D2。注：cs 变体门收窄到只查 `_PRED_OK` 属可选优化（保守方向，不收窄不算错） |
| D4 | beq/ble 机器 Bool 字面量合成（`const_cid :1657`） | reduce_nat beq/ble K/type_checker.cpp:702-733 的 Bool 结果 ctor | **Bool.true、Bool.false** | 否（结果节点由图合成） | `_TRUE_CID/_FALSE_CID` 名字扫描 `:546-551` + **legacy toy 回退（显式登记的唯一回退点之一）** |
| D5 | INFER 字面量类型发射（`raw_V0_i :5849-5850`） | infer_lit，K/type_checker.cpp:315-321 | **Nat（类型常量）、String** | 否（合成 Const(Nat)/Const(String)） | `_NAT_CID` = 拥有 Nat.succ 名标的 inductive（`_struct_ind(_SUCC_CID)` `:566-570`，legacy toy 回退，显式登记）；`_STRING_CID` `:560` **无回退**——缺席即拒（= 核侧无法构型，语义一致） |
| D6 | 字符串字面量展开重定向（`:4816`） | try_string_lit_expansion K/type_checker.cpp:1143-1156；string_lit_to_constructor K/inductive.cpp:1368-1380 | **String.ofList**（shadow 展开另需 List.cons/List.nil/Char.ofNat/Char，编码期整表检查 tokens.py:200-202） | 否（展开目标名不在字面量项里） | `_OFLIST_CID` 名字扫描 `:557-558`，缺席 → 臂不点火（优雅，K_LIT.X=0） |
| D7 | Quot 归约门与 kind 通道（门 `:934`，`_quot_kind :500-508`） | reduce_recursor 门 K/type_checker.cpp:394（is_quot_initialized）；quot.h:39-70 的名字比较被 kind 元数据替代 | 无名字合成——kind 按 cid 锚读 T_ENV_QUOTVAL（数据驱动） | 参与 cid 来自输入项（静态可见） | `_QUOT_INIT` = CK_QUOT 元数据存在性扫描 `:575-579`；无元数据 → 门关（legacy 不变） |
| D8 | 通用 recursor iota OP_IOTA（`:690-697`，规则表全部读自元数据，§13） | inductive.h:77-121 | 规则 rhs 树由 env 读（T_ENV_RULE/T_ENV_RECVAL）；**rhs 树里引用的常量须同名在册** | rhs 是 env 数据（非 value 树）；stage C 闭包必须遍历规则 rhs（`_g04_env` 已做，tests:1250-1262） | 闭包纪律：recursor 声明的 rules[].rhs / ctor / induct 元数据一并入 frontier；越界深度帽（PMM_MAX 等 `:822`）超限 → stuck（永不错误归约） |
| D9 | casesOn/rec 派发键（csonop `:786`、csonop_p2 `:795`、csonop_bool `:806`、recop `:773`） | inductive.h:77-99 | **Nat.casesOn / P2.casesOn / Bool.casesOn / Nat.rec 的名字标签（派发用）** | 参与常量在输入项中静态可见 | X 标签名字驱动（同 D1）；toy 侧 CID_CASESON_* `:172-180` 仅注释性登记（派发不读 cid） |
| D10 | eta-struct / unit-like / 通用 proj（`_is_unit_induct :581-604`、proj 臂 `:3095-3123`） | is_non_rec_structure K/type_checker.cpp:1159；reduce_proj :420-441；expand_eta_struct K/inductive.h:58/:73 | 无名字合成——ctor 计数 / nfields / induct 链接 / nparams 全按 cid 锚读 T_ENV_CTORVAL/T_ENV_META | 参与 cid 来自输入项 | 元数据存在性；legacy toy cid 回退仅 `CID_UNITT :600-601` 一处（显式登记） |

**结论（铁律 3 合规判定）**：全部 10 条动态面均为「名字键控标签扫描 / cid 锚
元数据 / 存在计数门 + 缺席优雅降级」三件套，无一处按具体 cid 写分支；toy cid
回退 = 名字扫描族三处（Bool.true/false `:546-551`、Nat `:566-570`、UnitT
`:600-601`）+ 既有 `_ctor_site`/`_struct_ind` 玩具分类回退（`_is_zero/_is_succ/
_is_false/_is_true` `:423-432`、`_struct_ind/_struct_nid` `:456/:493`，存量
另册登记，被 zconst/Bool casesOn/p2_ctor 分类消费但不合成名、不产生闭包缺口）。
真正的缺口是**闭包纪律**：D2/D3 的
`Nat.pred`/`Nat.rec`（以及 D4-D6 的合成名）不经过静态引用闭包，stage C
最小化若不把它们并入 frontier 就会把可归约语料判成假 stuck——这就是
`G04_KEEP_TOY={"nat","proj"}` 的本质（tests:1176-1178 注释自述"reduction
dynamically needs Nat.pred"）。

### §1.3 VM_SPEC §16.7 stage C 续写条款草稿（拍 B 正式落盘用，本拍只交草稿）

> **C-16.7.x 运行时现造名的闭包保留纪律**
> 1. 归约/推理/差分臂按名字现造节点的完整清单（盘点表 D2-D6）：`Nat.pred`、
>    `Nat.rec`、`Bool.true`、`Bool.false`、`Nat`、`String`、`String.ofList`。
>    这些名字不经过输入项的静态引用闭包；任何环境最小化（stage C）必须把
>    清单中与语料归约路径相关的名字并入闭包 frontier 种子（等价于按需
>    keep-toy），缺名时图必须走存在计数门优雅降级（stuck/臂不点火），
>    禁止合成伪 cid。
> 2. 差分语料若覆盖 D2/D3（iota succ 规则）或 D4/D5/D6（合成名面），verifier
>    须先断言对应名字的名字扫描存在计数 ≥1 再比对判定——否则该行的分歧
>    定性为「环境缺失」，不构成语义分歧证据。
> 3. legacy toy cid 回退维持现状三处（Bool.true/false `:546-551`、Nat
>    `:566-570`、UnitT `:600-601`），新臂禁止新增回退点。
> 4. `rec_ids_ok`（`:1020`）对 casesOn 变体的 `_REC_OK` 合取为过保守
>    （cs_build 三步只造 pred，`:2930-2955`）；收窄与否留拍 B，不收窄不算错。

---

## §2 I_CASE 主前提 whnf 续推（卡 016 第 1 条；摘 g04iv_eG4IV2）

### §2.1 核侧行为合同（file:line + 探针复证）

`inductive_reduce_rec`（K/inductive.h:77-121）对 recursor/casesOn 应用项的
主前提执行**有序归一化管线**后才做规则匹配：

1. `:91` K 型 recursor 先 `to_cnstr_when_K`（本盘点语料不涉及，注记不展开）；
2. **`:93` `major = whnf(major)`——主前提先 FULL whnf（含 delta）**，这是本条
   的合同核心；
3. `:94-95` nat 字面量 → `nat_lit_to_constructor`（K/inductive.cpp:1359）；
   `:96-97` 字符串字面量 → ofList 展开；`:99` `to_cnstr_when_structure`
   （非递归结构 eta 展开，K/inductive.h:58/:63-73）；
4. `:100` `get_rec_rule_for(rec_val, major)` 按 **whnf 后 major 的头构造子**
   匹配规则——**字段不预归约**，`:114` 把 major_args 原样应用到 rhs；
5. `:115-119` extras 续挂；rhs 回灌外层 whnf 循环（K/type_checker.cpp:760
   外层 while(true)，循环体 :736-774；App 分支 iota 回灌 :511-541）。

匹配失败（major 非 ctor）→ `none` → 整个 rec/casesOn 原样 stuck。

### §2.2 图侧缺口精确定位

图 I_CASE 家族（OP_CASESON/OP_REC/P2/Bool 四臂同构）已实现的续推：
fire（`:1550/:1528`）压 NAT(op,caller,1) 帧、焦点=主前提、主循环续推
（= 合同第 2 步**已存在**，不是"无子 whnf"）；交付分类（`:1031-1051` rec、
`:1045-1051` cs、`:1085-1086` p2、`:1112-1116` bool）只认
**零字面量 / 正字面量**（`is_zlit_r/is_lit_r/is_zconst_r`，`:998-1015`）。
缺口两段：

- **缺口 A（语义主缺口）**：完成的 major 是 **ctor 应用**（如 `Nat.succ k`，
  k 为 stuck 字段）→ 落 `cs_stuck_r`（`:1051`）交付 spine 根；核侧按
  `:100` 规则匹配 succ 规则、字段原样进 rhs（`:114`）→ **分歧**。
  探针 p1/p6（§4）实证核侧行为。P2 臂已有同类形状匹配先例（`p2_ctor`
  `:1079-1082`），Nat 臂缺这一份。
- **缺口 B（ENV 纪律缺口，g04iv_eG4IV2 的直接死因）**：正字面量 major 落
  `cs_succ_r`（`:1049-1050`）但被 `rec_ids_ok`（`:1020` = `_REC_OK∧_PRED_OK`）
  门住——iv 族 stage C 闭包不含 `Nat.pred`/`Nat.rec`（D2/D3 静态不可见）→
  门 0 → `cs_stuck_r`。核侧无此依赖面（规则 rhs 从 env 的 recursor 声明
  读， Nat.pred 在核 env 里恒在）。g04b_diag.log 实测：raw 120 步 HALT 于
  原 spine 根焦点，重发幂等（r1 34 步焦点不动）。

driver 侧 run_whnf 续轮救不了两者（G04 已定谳"driver 循环结构上补不了"）：
交付焦点=spine 根，重发幂等。

### §2.3 候选方案

**方案 2-乙（推荐）：分类面扩展 + pred 形状规则（"载体位扩展"家族）**
1. cs/rec 交付分类加 ctor 应用形状门：`cs_ctor = cs_dn ∧ fK==K_CONST ∧
   fV0==_SUCC_CID`（fK/fV0 焦点读已存在；`_SUCC_CID` 名字扫描已有 `:531`；
   形状匹配先例 = `p2_ctor :1079-1082`）。字段=主前提自身 spine 的 pend 尾
   （pV0/pX 同源读，拍 B 需按 M5 教训审计交付点 pend 布局）。
2. `cs_succ_r`/`build_r` 门扩为 `rec_ids_ok ∧ (is_lit_r ∨ cs_ctor)`；构造
   循环的 `<maj>` 输入选择字面量焦点 SA 或 ctor 字段位（`raw_V1_cs :2946-2949`
   一处 select；OP_REC 同构一处）。
3. **pred 形状规则**：`Nat.pred (Nat.succ X) → X` 进 nat-op pred 臂
   （形状匹配+字段选择，先例 p2_ctor 级）。无此规则时 ctor-app major 的
   rhs 内 `Nat.pred k`（k stuck）图侧保持 stuck，核侧已归约到 k（探针 p1
   `Nat.succ (Nat.add k 999)` vs 图侧 `succ_minor (Nat.pred k)…`）——stuck
   形状分歧会在后续 defeq 比较上二次咬人，必须同拍补上。
4. `is_zconst_r`/零规则面不变；P2/Bool 臂不变（P2 已有 p2_ctor；Bool 只有
   0 字段 ctor，字面量分类已覆盖其等价面）。

per-node dims 预估（图基线 34,468 dims / 4,495 lookups / 235,424 nnz = 拍 1
G8/G9 后 HEAD 图；015 封版 34,392/4,489/235,030 + 76/6/394；
教训单位出处：handoff 006 卡 015 拍 2 实测记录「n2z 单节点 ~16 dims」，
ADR 022 原文只给「每节点数个 ReGLU、≤511 节点」上限，不载 ~16 数字）：形状门 2 处 × ~8-12（p2_ctor
同构）+ 门/选择字加宽 2 处 × ~3-5 + pred 形状规则 ~10-16 ≈ **+35-50 dims、
lookups +0~+2、步数 +0（字面量路径逐值不变：全部新门为加取析，字面量
major 上 cs_ctor≡0）**。≈ 2-3 个 n2z 级节点，远低于 ADR 022 组件 2 的
失控先例。

**方案 2-甲（被拒）：新帧续推（非分类完成 major 时帧改写 X←1 重发子 whnf 轮）**
拒绝理由：完成交付（E=0）是机器自身的不动点，同机重发同焦点幂等
（g04b_diag r1 = 34 步焦点不动；G04 c2 探针系列已证"当前图上不存在任何
闭载体形状使续推轮成为语义必需"）；要推进就必须新增归约能力，而那正是
分类面扩展本身——帧往返是死机器 + 每个非字面量交付加步数。新帧 state 类
（X=2 已被 build 循环占用）还需扩帧状态空间。

**方案 2-丙（被拒）：driver 侧 run_whnf 续轮**。G04 定谳（handoff 006 G04
段）：图在非头范式焦点上 HALT，重发幂等，调用方循环补不了语义缺口。

**方案 2-丁（被拒）：iv 族全量 keep-toy（ENV 侧硬保）**。实测否决：忠实
Nat.below/brecOn 树使纯 Python 求值 ~20MB/步，iv 子进程 6GB 被杀
（g04b_full3.log / g04b_ivtrace.log rc=-9，IV1@192 步即 3.85GB）。ENV 纪律
只能按 §1.3 C-16.7.x-1 的**两名种子**（Nat.pred/Nat.rec）做，不能整表钉。

**拍 B 前置**：先落 §1.3 C-16.7.x-1（两名入 iv 族闭包）把缺口 B 摘掉
（g04iv_eG4IV2 的直接死因），再实施 2-乙 摘语义缺口 A；两步分别跑差分行，
XFAIL 摘除以两步全完后 XPASS 协议执行。

---

## §3 mode 位跨 ST 续体携带（卡 016 第 2 条；摘 g03g/g03h）

### §3.1 核侧行为合同

- mode 是 **checker 的性质**，同一 addDecl 的头检与体检用同一 safety 的
  checker：unsafe add_definition 头检 `type_checker(..., definition_safety::unsafe)`
  （K/environment.cpp:167）、体检再起一个同 safety checker（`:172-177`）；
  add_theorem 恒默认（safe）checker（`:192-196`）。
- 抛点 = `infer_constant`（K/type_checker.cpp:101-123）：unsafe 引用抛
  `:111`、safe 体内 partial 引用抛 `:115`，`m_definition_safety !=
  definition_safety::unsafe` 时才抛——**mode=1 全链抑制，包括 lam body /
  app 参数等任意深度的推理**（单 checker 单链，无逐帧衰减概念）。
- oracle 侧证据：G03 verifier 行对——同语料 mode=0 抛 7 / mode=1
  oracle=OK（g03g_arg_selfref / g03h_lam_selfref 行，handoff 006 G03 H4 原文）。

### §3.2 图侧缺口精确定位

- 现有通道：mode 搭 TASK_INFER 帧 E2 高位（`CHECK_E2_STRIDE=8` `:230`，
  只搭 phase-1 值 1→9；`inf_mode` 解码 `:5693-5694`；`ck7_gate :5817`
  = `reglu(1−inf_mode, anc_f2≥1)`，抛门/降级共闸）。
- 覆盖面：kickoff 头检发射、ck_g1_val 体检发射、INFER 派发 5 子发射
  （peel_end `:5738` / lam `:5752` / pi `:5766` / let `:5780` / proj `:5885`，
  形如 `fr2_E2_i = One + reglu(inf_mode, 8)`）。
- **断点 = 三处 ST 链续体发射**：I_PI（APP 参数，`:3216`）、I_LAMSORT
  （lam body，`:3434`）、I_LETD（let body，`:3638`）——三处均
  `fr2_E2 = One`（不带 mode）。原因（G03 H2 实测登记，handoff 006）：
  ① 交付落点 D 下方是**死子树顶帧**，不是父 INFER 帧（SD-1 读点实测失效，
  app-arg/lam-body 两形状 m1 仍 7）；② 被压 ST 帧六槽全占——I_PI 为证：
  V1=f_type pos `:3206`、X=f_type env `:3207`、E2=args 链 `:3208`、
  F2=续体 id `:3211`、V2=task 指针、V0=TASK_ST（`fr1` 默认 `:3161-3162`）。

### §3.3 候选方案

**方案 3-甲（推荐）：F2 载体位扩展（续体 id × mode 双段编码）**

ST 帧唯一有值域余量的槽是 F2：续体 id ≤ 70（`g = {n: … for n in range(1,71)}`
`:3138`），取 `MODE_STRIDE=128`，编码 `F2' = cont_id + 128*mode`。

1. 解码单点：`mode_st = _geq_expr(frF2, One*128)`、`fid = frF2 − mode_st*128`，
   续体门改键 `gid(n) = _kind_eq_raw(fid, n, One)`（`:3135-3136` **单点改动**，
   `cg = {n: reglu(g[n], cont_mode)}` `:3141` 不动）。
   安全性：非 ST 帧的 F2（DEFEQ 的 s_env、NAT 帧的 m-entry 位置、CHECK 锚的
   lparams 链头）本就被 `cont_mode = is_st_frame ∧ frF2≥1`（`:716`）挡在
   cg 之外——步进编码不引入新碰撞面。
2. 写侧：check 链上所有 TASK_ST 压帧点把 F2 写成 `id + 128*<可解码 mode>`——
   kickoff（ck_mode_k 已解码）、5 子发射（inf_mode 已解码）、三处续体发射
   （从**当前帧自身 F2** 经 mode_st 解码——当前帧永远可寻址，这正是本方案
   对 SD-1 失效的破局点）。
3. 三处续体发射的 `fr2_E2` 加宽为 `One + reglu(mode_st, 8)`（与 5 子发射
   同形）；下一跳 ST 的 `fr1_F2` 同步带 mode（I_LAMSORT→I_LAMBODY `:3430`、
   I_LETV→I_LETD `:3601` 等链内跳）。gate 侧 `:5817` 消费面零改动。
4. 审计项（拍 B）：grep 全部 TASK_ST 的 F2 写点，确认皆为续体 id（今日任何
   位置值写入都会与 gid 等值匹配误撞，设计合同即"ST.F2=续体 id"）；新续体
   id 上限 127（现 70，余 57）。

per-node dims 预估（同基线）：解码 ~4-6 + 写点加宽 ~15 处 × 3-4 + 三发射
fr2_E2/fr1_F2 ~12-20 ≈ **+60-80 dims（0.17-0.23%）、lookups +0（frF2 为
寄存器读）、步数 +0（mode=0 时 fid=frF2 逐值还原旧图）**。≈ 4-5 个 n2z 级
节点。

**方案 3-乙（被拒为主案，可留作一次性探针）：SD-2/落点重定标**。SD-1 已被
G03 H2 实测否决；SD-2 的"落点下方第二帧=父帧"只是 I_PI 形状下的实现偶然
（I_LAMSORT 的落点下方是死 domain 推理帧、I_LETD 又不同），不是协议合同，
未来任何协议演化都会静默破坏；且需逐发射点探针定拓扑，证明负担 > 改动量。

**方案 3-丙（被拒）：mode 载体帧（新帧延续）**。在 5 子发射处额外压一个
TASK_ST(mode) 载体帧——载体帧同样被变深的子树埋住（与 SD-1 同类可寻址性
失败）；且额外帧移动所有 SD-k 固定偏移读点，爆炸半径=整个续体协议，与
G03"协议扩展走新通道、旧默认路径语义不动"（§五 step_driver 行）冲突。

**方案 3-丁（被拒）：ENV/锚元数据承载**。mode 是 run 侧性质：同一 ENV 下
mode=0/1 两跑判定不同（G03 B 行对即证），ENV 是 per-stream 静态数据承载
不了；CHECK 锚帧 E2 只覆盖 kickoff 一跳（G02 copy-forward 到 CK_G1 为止，
G03 P2 备案实测），下游变深不可回读。

**方案 3-戊（并入主案）：六槽空位复用**。V0=帧类、V1/V2/X/E2 数据、F2=id
——唯一值域余量就是 F2 的 id 上界以下空间，已并入 3-甲。

**遗留近似（本修不覆盖，须保留登记）**：pi codomain（I_PIL1 `:3483-3485`）
与 DEFEQ 链 soft 发射仍不携带 mode（G03 已登记）；DEFEQ 帧六槽同样全占且
F2=s_env 是位置值（非续体 id），3-甲 的 stride 编码不能直接套用，若未来
要覆盖须为 DEFEQ 帧族另设计通道。g03g/g03h 的形状（APP 参数 / lam·let
body 自引用）恰在三跳续体上，属本修覆盖面。

---

## §4 oracle 探针记录（4.33.1 现跑，核 0-5，OMP_NUM_THREADS=3）

探针脚本 `/tmp/probe_016a_icase.py`（defs = `opaque k : Nat` + 4 个 def
载体；通道 = `reference/lean_ref.run_oracle` = Meta.whnf，ORACLE_TEMPLATE）。
输出原文（`/tmp/probe_016a_icase.out`，rc=0）：

```
TERM p1   # Nat.casesOn (Nat.succ k) 100 (fun n => n + 1000)
  -> ["WHNF", {"k": 6, "f": {"k": 5, "n": "Nat.succ", "u": []}, "a": {"k": 6, "f": {"k": 6, "f": {"k": 5, "n": "Nat.add", "u": []}, "a": {"k": 5, "n": "k", "u": []}}, "a": {"k": 10, "nat": 999}}}]
TERM p2   # Nat.casesOn k 100 (fun n => n + 1000)
  -> ["WHNF", {"k": 6, "f": … "Nat.rec" … 100 … "k" …}]   # 整项原样 stuck
TERM p5   # Nat.casesOn (Nat.add 0 1) 100 (fun n => n + 1000)
  -> ["WHNF", {"k": 10, "nat": 1000}]
TERM p6   # Nat.casesOn (Nat.succ (Nat.add 0 1)) 100 (fun n => n + 1000)
  -> ["WHNF", {"k": 10, "nat": 1001}]
```

首轮批（同文件前身，`#ORACLE` 直跑项）另取一发定案证据：

```
#ORACLE Nat.pred (Nat.succ k)  ->  ORACLE {"k":5,"n":"k","u":[]}
```

**定案读数**：
- p1 = 核侧对 **ctor 应用 major（字段 stuck）** 匹配 succ 规则并把字段经
  `Nat.pred (Nat.succ k)→k` 传入 minor——缺口 A 的核侧行为直接实证
  （图侧现行 cs_stuck_r 交付 spine 根 = 分歧）。
- p2 = 真 stuck major（opaque）→ 整项 stuck，规则匹配失败——图侧 cs_sd
  交付 spine 根与核一致（无分歧，方案 2-乙不触碰此分支）。
- p5 = IV2 形状（nat-op major）核侧全 descent 到 1000——图侧当前在
  rec_ids_ok 门上假 stuck（缺口 B）。
- p6 + `Nat.pred (Nat.succ k)→k` = ctor 字段可再归约时核侧继续穿透
  （1001）——方案 2-乙第 3 条（pred 形状规则）的核侧依据。
- 探针口径注记：casesOn 直跑 `#ORACLE` 会撞 elaborator eliminator 需期望
  类型（"failed to elaborate eliminator, expected type is not available"），
  改经 def 体间接（同时更贴 IV2 语料形状）；p6 一度撞 Meta 层
  maxRecDepth，defs 顶部 `set_option maxRecDepth 100000` 解（Meta 层工件，
  非核判定面）。
- 本拍未跑新 T3 探针：mode 的核侧合同由 G03 verifier 行对（oracle=OK vs
  图=7）+ K/environment.cpp:167/:172-177 + K/type_checker.cpp:111/:115
  原文锚定，无"拿不准"项。

## §5 给拍 B 的移交要点

1. 顺序：先 §1.3 C-16.7.x-1（Nat.pred/Nat.rec 入 iv 族闭包种子，图零改动、
   只动测试的 stage C 组装）摘缺口 B → 重跑 g04iv_eG4IV2 行（预期仍 XFAIL，
   stuck 形状变为缺口 A 形态）→ 实施 2-乙 → XPASS 摘除。
2. 3-甲 的 gid 改键点在 `:3135-3136`，动前 grep 全部 TASK_ST F2 写点做
   合同审计；判定+步数不变性由 guard/bcd/canary 对拍证明（mode=0 逐值
   还原）。
3. dims 预算：2-乙 ≈ +35-50，3-甲 ≈ +60-80，合计 ≈ +95-130（0.3-0.4%），
   远低于回归帽敏感区；实现后按卡 016 verifier 集记录实际增量。
4. 保留登记：pi codomain / DEFEQ 链 soft 发射不携带 mode（§3.3 遗留近似）；
   to_cnstr_when_K / to_cnstr_when_structure（inductive.h:91/:99）不在此拍
   语义面（Nat 非 K 型、非非递归结构），Mathlib 语料若现形另行开卡。
