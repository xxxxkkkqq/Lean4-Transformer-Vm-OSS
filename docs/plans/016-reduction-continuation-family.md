# 任务 016：归约续推与状态携带家族（I_CASE whnf / mode 续体 / ENV 动态名盘点）

状态：**CLOSED（2026-10-04，总控五道门 + 审核 PASS）**——拍 A（语义设计
2026-09-25，memo docs/decisions/023，审核 PASS/勘误已落）；拍 B（图侧实现
2-乙+3-甲，2026-09-26，实现代理死于额度两次、断点接手完成；B6 引擎门曾 FAIL
33/34 = succ_delta 回归，修复拍定案 decline 门 K_CONST 子句缺 delta 判别，
收窄"无值常量"后 34/34 恢复，探针钉 decline 唯一死因、修后与 pre-beat-B
逐值同）；拍 C（独立全量回归 2026-10-04：**23/23 rc=0 语义零 FAIL**，
`~/logs/016C/`，decl_injection 106/106+0xfail = 103 基线摘 3 xfail + csctor
3 新行）；拍 D（整卡审核 PASS 2026-10-04，收口项已落：真值表 016 行 /
卡 checkbox / VM_SPEC 指针 / 锚勘正）。dims 34,671/4,527/236,947（+203/+32/
+1,523 对 011 基线）；摘 3 XFAIL（g04iv_eG4IV2 775 步、g03g 23 步、g03h 40
步）；两条残余债登记 VM_SPEC §16.7.2/§11.7；帽校准 mutation 2700 /
decl_injection 7200（a0d18cb 格式）；真值表行 ARCHITECTURE
`step_vm_016_scratch.sbin`。

原始状态：open，待派（2026-09-21 总控自卡 011 移交队列 1/3/4 拆出；排产在卡
011 拍 1 收口后，图侧写盘串行）

## 目标

三条同族的"续推/状态携带"缺口，各以既有 XFAIL 摘除为出口判据：

1. **I_CASE 主前提 whnf 续推**：核侧 `K/inductive.h:93` 对 casesOn 主前提
   先 whnf 再 match 索引，图 I_CASE 无此续推（005 F7-01 "spine-root 交付"
   家族）。摘 `g04iv_eG4IV2` XFAIL。证据：handoff 006 G04 / `g04b_diag.log`。
2. **mode 位跨 ST 续体携带**：G03 登记的保守侧假拒 7（APP 参数 / lam·let
   body 自引用）——mode 位需沿 ST 帧续体传递。摘 `g03g`/`g03h` 两 XFAIL。
   证据：真值表 `step_vm_010g03_scratch` 行、handoff 006 G03 段。
3. **归约层 ENV 动态名字依赖盘点**（先于 1/2 的排查拍）：cs_build succ 规则
   运行时现造 `Nat.pred t`（静态引用闭包不可见，bisect 实证
   `g04b_bisect.log`）——盘点全部"归约期动态查表的名字"，产出 ENV 侧保留
   纪律条款入 `docs/VM_SPEC.md`（§16.7 stage C 续），"环境是数据"铁律合规
   结论。纯排查（只读代码 + oracle 探针），不改图。

## 拍次划分（建议）

- 拍 A（语义设计师）：第 3 条盘点 + 第 1/2 条的核侧语义依据
  （`K/inductive.h` casesOn 臂、mode 位合同与 `step_driver.py` 对照）+
  方案 memo（新帧延续 vs 载体位扩展，图规模增量预估）。
- 拍 B（图逻辑工程师）：按拍 A 裁决实现 1、2；每摘一条 XFAIL 即差分行转绿。
- 拍 C（测试工程师）：全量 decl_injection 分节 + 23 套件回归 canary；拍 D 审核。

## 涉及文件

拍 A：只读 + 文档（本卡执行段 / ADR 如需）。拍 B：`lean_vm/build_vm.py`、
`lean_vm/step_driver.py`（如需）、`expr/tokens.py`（如需）、
`tests/test_decl_injection_vs_lean.py`（XFAIL 摘除）、`docs/VM_SPEC.md`、
`docs/KERNEL_COVERAGE.md` 对应行。

## Verifier 集

- [x] ENV 动态名盘点表落 VM_SPEC（每条：归约臂 `file:line` → 动态名 → ENV 保证方式）（VM_SPEC §16.7.2 C-16.7.x 四条款 + 7 名清单；逐条盘点表 memo 023 §1.2 D1-D10）
- [x] `g04iv_eG4IV2` 转 PASS（oracle 现跑对类别）（775 步，reg4.log + g04_full2.log 18/18）
- [x] `g03g`/`g03h` 转 PASS（23 步 / 40 步，reg4.log）
- [x] 全量回归不倒退 + 引擎对新 scratch 对拍 + 硬编码零新增 + dims 增量记录（23/23 rc=0；引擎 34/34 三次独立；硬编码自查两轮 PASS；+203/+32/+1,523）

## 基线与帽

- 图侧封版基线 = `model/step_vm_015_full_scratch.sbin` 代（34,392/4,489/235,030）。
- dims 增长敏感：n2z 单节点 ~16 dims 教训（ADR 022 组件 2 即因此 NOT-VERIFIED）；
  本卡方案预估必须给 per-node 成本。
- 回归帽按 a0d18cb 校准表（decl_injection 5000|7000）。

## 已知邻接

- 卡 011 拍 1 同时改 `build_vm.py`/`step_driver.py`——本卡必须等其收口。
- 卡 012 M-B（编码规模）撞不到本卡缺口（015 已修 accessor 活锁），但
  casesOn 类续推会在 Mathlib 语料出现——第 1 条优先于第 2 条。

## 拍 A 执行段（语义设计师，2026-09-25 开工）

### 执行计划清单（先落盘再干活，每完成一个可验证子步立即回填 [x]）

- [x] 0.1 读卡 016 全文 + handoff 006 G03/G04 段 + 003-D-wp7 CK_* 先例 + ADR 022
  dims 教训；grep build_vm.py 定位 OP_CASESON/cs_build/mode 臂。
- [x] 0.2 落盘本计划段。
- [x] T1 ENV 动态名盘点：build_vm.py 归约臂逐个分类（OP_SUCC/PRED/REC
  nat-op 臂、cs_build succ 规则、P2/Bool casesOn 臂、Nat.rec 臂、quot 臂、
  string/Bool 字面量机件、defeq redirect），分类「静态闭包可见 vs 运行时动态
  查表」，每条带 build_vm.py:行 + kernel file:line + ENV 保证方式。
  → memo §1.2 十条盘点表（D1-D10）+ §1.1 机制基座 + §1.3 VM_SPEC §16.7
  stage C 续写条款草稿（4 条）。
- [x] T1.1 探针裁定：T1 无需新探针——图侧证据已有 g04b_bisect.log（单加
  Nat.pred 翻正 d1）+ stage C 闭包代码（tests:1203-1262）；核侧规则 rhs 来自
  env 的合同由 K/inductive.h:107-118 原文锚定。
- [x] T2 I_CASE 主前提 whnf 续推：核侧合同（K/inductive.h:93 major whnf、
  :99-100 规则按 whnf 后 ctor 头匹配、:114-118 字段不预归约）→ 图侧缺口
  两段（缺口 A = 交付分类面只认字面量 :998-1051，ctor 应用 major 落
  cs_stuck_r；缺口 B = rec_ids_ok 门 :1020 被 iv 族闭包缺 Nat.pred/Nat.rec
  压 0，即 eG4IV2 直接死因）→ 方案 2-乙（分类面扩展+pred 形状规则，推荐，
  +35-50 dims）/ 2-甲（新帧续推，拒：同机重发幂等）/ 2-丙（driver 续轮，
  拒：G04 定谳）/ 2-丁（iv 全量 keep-toy，拒：6GB 实测）。
- [x] T2.1 oracle 探针 4+1 发（/tmp/probe_016a_icase.py，原文 memo §4）：
  p1 ctor-app major 核侧匹配 succ 规则字段穿透、p2 真 stuck 整项 stuck
  （图 cs_sd 一致）、p5 IV2 形状核侧 descent、p6 + Nat.pred(Nat.succ k)→k
  pred 形状规则依据。
- [x] T3 mode 位跨 ST 续体：合同（K/environment.cpp:167/:172-177 双 unsafe
  checker、K/type_checker.cpp:111/:115 抛点；G03 行对）→ 图侧缺口（三处
  续体发射 :3216/:3423/:3631 的 fr2_E2=One 无 mode；SD-1 死帧 + 六槽全占
  实测）→ 方案 3-甲（F2 载体位扩展 id+128*mode，推荐，gid 单点改键
  :3135-3136，+60-80 dims）/ 3-乙（SD-2 重定标，拒：实现偶然非合同）/
  3-丙（mode 载体帧，拒：同类可寻址性失败+爆炸半径）/ 3-丁（ENV 承载，
  拒：mode 是 run 侧性质）/ 3-戊（并入 3-甲）。
- [x] T4 memo 落盘 `docs/decisions/023-reduction-continuation-family-memo.md`
  （三节 + 探针原文 + 拍 B 移交要点）；本段回填完成。
- [x] T5 最终报告给总控（会话输出，不另落盘）。

### 拍 A 产出登记

- memo：`docs/decisions/023-reduction-continuation-family-memo.md`（已落盘）；
  正式条款落 VM_SPEC §16.7 stage C 留拍 B（草稿在 memo §1.3）。
- 只读代码 + 本卡执行段 + 023 memo，未改其他任何文件；未碰 git。
- 三条结论一句话：① ENV 动态名 = 名字键控 X 标签/cid 锚元数据/存在计数门
  三件套合规，真缺口是 stage C 闭包纪律（D2/D3 的 Nat.pred/Nat.rec 等
  现造名不入静态闭包，条款草稿 C-16.7.x）；② I_CASE 缺口 = 交付分类面
  literal-only（ctor 应用 major 分歧，探针 p1 实证）+ rec_ids_ok 环境门
  （eG4IV2 直接死因），推荐 2-乙 +35-50 dims；③ mode 断点 = 三处 ST 续体
  发射 mode 无处搭，推荐 F2 载体位扩展（id+128*mode，gid 单点改键）
  +60-80 dims。

## 拍 B 执行段（图逻辑工程师，2026-09-25 开工）

### 执行计划清单（先落盘再干活，每完成一个可验证子步立即回填 [x]，含命令原文）

- [x] B0. 读卡 016 + memo 023 全文 + handoff 011 拍 1 收口段；核对图基线
  34,468/4,495/235,424（卡 011 G8/G9 后 HEAD）。（2026-09-25 完成）
- [x] B1. 第 1 步 C-16.7.x-1 闭包种子（图零改动）：`Nat.pred`/`Nat.rec` 两名
  并入 iv 族 stage C 闭包种子（tests/test_decl_injection_vs_lean.py `_g04_env`
  族）；重跑 g04iv 分节记录缺口 B 摘除效果（预期仍 XFAIL，stuck 形状转为
  缺口 A 形态）。（2026-09-25 完成）

  实现：`G04_GROUPS["iv"]` roots 增 `Nat.pred`（探针实测原 dump 106 项含
  `Nat.rec` 不含 `Nat.pred`，dump 无名则 frontier 种子空转）；grp 增第 4 元
  显式种子 `["eG4IV1","eG4IV2","Nat.pred","Nat.rec"]`（_g04_env 的 carriers
  即 frontier 种子，第 4 元语义=显式种子，proj/uprod 先例同）。
  命令：`OMP_NUM_THREADS=3 taskset -c 0-5 env G04_FAMILY=iv timeout 300
  /home/xkq/miniconda3/envs/train/bin/python -u tests/test_decl_injection_vs_lean.py`
  输出原文（env 57→59 consts）：
  ```
  [PASS] G04 iv/eG4IV1: oracle=LitNat(value=5) run_whnf=LitNat(value=5) steps=192 rounds=2
  [XPASS] G04 iv/eG4IV2: oracle=LitNat(value=6) run_whnf=LitNat(value=6) steps=775 rounds=2
  G04X [G04 g04iv_eG4IV2] XPASS: known-gap entry must be removed (run_whnf now agrees with lean)
  G04-DONE rc=1
  ```
  与 memo §5.1 预期"仍 XFAIL 转 gap A 形态"不符：本语料 fix 缺口 B 后直接
  XPASS（语料深处的 succ 规则 major 均为字面量可归约形态，ctor-app major
  未现形）。KNOWN_GAPS 摘除按 memo 约定留到 2-乙 完成后一并执行（XPASS
  期间 dev-loop rc=1 属预期中间态）。
- [x] B2. 第 2 步 2-乙（摘 g04iv_eG4IV2）：cs_ctor 形状门 + cs_succ_r/build_r
  门扩展 + 构造循环 `<maj>` 输入 select + pred 形状规则；py_compile + 最小
  差分；摘 `g04iv_eG4IV2` xfail 标记转 PASS（oracle 现跑对类别）。
  （2026-09-26 实现完成、dev 验证通过，全节复跑挂 B7）

  **探针定案（/tmp/probe_016b_csctor.py，oracle 现跑，修正 memo 现状模型）**：
  修前 ctor 应用 major（p1 = `Nat.casesOn (Nat.succ k) …`，k opaque）不是落
  `cs_stuck_r`，而是 **beat 8 reject code 1**——死于 NAT(succ) 帧嵌套
  nat-arg 硬拒（`dbg_dn1=1 dbg_nathard=1`；NAT(caseson) 的 E2=spine 根≠软旗，
  wpos 单跳爬升读不到软 WHNF 帧）。memo §2.3 的分类面扩展因此不可达，须先补
  两个使能件（均在 NAT 帧作用域内，非 NAT 调用者的 soft/hard 合同不动）：
  ① **fire 门 decline**（build_vm.py :764-793）：调用者为 TASK_NAT 帧且实参
  为直接 stuck 非字面量叶（Sort/FVar/MVar/Pi/T_PI_CLO/非零 Const/字符串
  K_LIT）时不点火 → ctor 应用经 const_stuck 以剥离态（焦点=Const(Nat.succ)、
  字段=pend 顶）完成 whnf——核侧 `Nat.succ k` head-normal（whnf 不入 ctor
  参数；reduce_nat 只吃 is_nat_expr 实参，K/type_checker.cpp:702-733）。
  BVar/可归约实参照旧点火；p6 形状（可归约字段）不受影响（实测 AGREE 不变）。
  ② **pred 形状规则** `Nat.pred (Nat.succ X) → X`（:6041-6049 门 +
  :1571-1573 状态臂 + 六链插入 + em_frame `dn1 − pred_ctor_r` + rej_n 扣除，
  优先级在 nat_soft 之前——核侧走 delta+iota 而非 reduce_nat，软硬上下文都
  归约）。③ **cs_ctor_r 直接交付**（memo 的 `<maj>` select 被取代）：cs 侧
  平铺 build 无法携带字段 env（p2_ctor 教训原文），改按 p2_succ_r 先例直接
  交付：焦点=succ minor（home env）、pend=字段项++extras（decline 路径
  pend 未被打扰）；OP_REC 侧走既有 15 步 build（e4 链已携带 rmajX，且
  `<maj>` 输入 rmajV0 本就是 major 原位，无需 select），只加宽
  build_r 门（rec_ctor）。
  **dev 实测**：p7（cs ctor，闭环 minor）=42 AGREE 9 步；p9（Nat.rec ctor）
  =999 AGREE 39 步；p10（`Nat.pred (Nat.succ k)`）=k AGREE 44 步；
  p5/p6（字面量路径）AGREE 且单载体 A/B（git show HEAD 版 vs 改后版同 env）
  步数逐值相等（83/176）——字面量路径零步数增量。iv 族 eG4IV1 PASS 192 步、
  nat 族 3/3 PASS（122/591/1227）。**残余（登记，不在本卡）**：p1 形状
  （minor 体 `n + 1000`）仍 reject——`Nat.add k 1000` 的 rec 展开（核侧
  `Nat.succ (Nat.add k 999)`）= VM_SPEC §11.7 已登记 "offset/构造子 stuck
  参数属后续里程碑" 债；p2（stuck major）delta 头形状差（Nat.rec vs
  Nat.casesOn）= 005 F7-01 既有家族，本卡不触碰。
  **新增差分行**：G04 新家族 `csctor`（tests:1139-1152 defs、:1200-1207
  注册；env 10 常量，seeds 含 Nat.pred/Nat.rec）3 行 eG4CSC/eG4RECC/eG4PRED
  全 PASS（oracle 现跑）；KNOWN_GAPS 摘除 `g04iv_eG4IV2` 条目（tests:247），
  文件头 §g04 注释同步。全节复跑结果记 B7。
- [ ] B3. 第 3 步 F2 写点合同审计：grep 全部 TASK_ST 压帧点 F2 写点，确认皆
  为续体 id；结果记本段，有例外立即停手上报。（2026-09-26 完成，结论=合同
  在 ST 帧上成立，零例外）

  审计面 = 全部 66 处 `fr1_F2*` 写点（build_vm.py，fr1/fr1_*_d/_r/_i/_k 五族
  ST/任务帧发射）。逐点分类：
  ① 写**续体 id 常量**（I_*/D_*/CK_*/DE_*/ES_*/ETA_*/IP_*/PI_*/ST_*/UL_*，
  全部 ≤70）：47 处 ✓。
  ② 写 `frF2`（当前帧 F2 拷贝，5 处 :3214/:4158/:4167/:5319/:5767/:6091）：
   - :3214（CONT 树默认）/ :5319（resume 树默认）/ :6091（D_NCT 循环步）：
     当前帧为 TASK_ST 且其 F2 = 续体 id（dispatch 本就按 gid 键控）→ 拷贝
     保 id ✓；
   - :4158/:4167（deq_mdata/deq_succ）与 :5767（em_more）：同门下
     fr1_task 已被改写为 TASK_DEFEQ / TASK_INFER（:4154/:4163/:5765）→
     非 ST 帧，is_st_frame 挡在 gid 之外 ✓。
  ③ 写**位置/数据值**（soft_flag :3615/:3642、SB :4460/:4617/:5298、
  frE2 :4816、es_of_env :4926、nb_se :4390）：逐点核对同门 fr1_task 改写——
  全部落在 TASK_INFER（P_EMIT 软旗继承，注释自证 "NOT the default frF2
  cont id"）或 TASK_DEFEQ（s_ty env / M2 pos / DEFEQ s_env）帧上，非 ST 帧 ✓。
  **结论**："ST.F2 = 续体 id" 合同在所有 is_st_frame 为真的帧上成立，无例外。
  **对 3-甲 的两条实现约束**：(a) mode_st 解码必须 is_st_frame 门控（DEFEQ
  帧 F2=s_env 为位置值，可 ≥128，不得误解码为 mode）；(b) 步进编码只写
  ST 续体写点（①类 + ②①小类的 ST 帧），INFER/DEFEQ/CHECK 帧的 F2 通道
  （软旗/s_env/anchor 位）一律不动。
- [x] B4. 第 4 步 3-甲（摘 g03g/g03h）：MODE_STRIDE=128 解码单点改键 + 写侧
  全部 TASK_ST 压帧点带 mode + 三处续体发射 fr2_E2 加宽 + 下一跳 fr1_F2 带
  mode；py_compile + 最小差分；摘 `g03g`/`g03h` xfail 转 PASS。
  （2026-09-26 实现完成，g03 节 7/7 PASS）

  实现（build_vm.py，MODE_STRIDE=128，F2 = cont_id + 128*mode）：
  ① 解码单点 :3195-3207：`mode_st = is_st_frame ∧ frF2 ≥ 128`（比 memo 多一
  道 is_st_frame 门——B3 审计约束 (a)，DEFEQ 帧 s_env 位置值 ≥128 不得误解码
  为 mode）、`fid = frF2 − mode_st*128`、`gid(n) = _kind_eq_raw(fid, n)`、
  `mid(n, m) = id + m*128` 助手；`cg` reglu 结构不动。
  ② INFER 派发 6 处 ST 写点带 `mid(id, inf_mode)`：peel_end→I_FN、lam_i→
  I_LAMDOM、pi_i→I_PIDOM、let_i→I_LETV、sort_i→I_SORTEM、proj_i→IP_TY
  （memo 预算内 15 写点的一部分）。
  ③ CONT 树 8 处链内 ST 写点带 `mid(id, mode_st)`：I_FN→I_PI、I_PI→
  I_ARG_S/I_ARG、I_ARG→I_CHK、chk_ok→I_PI、args_walk→I_ARG_S、
  I_LAMDOM→I_LAMSORT、I_LAMSORT→I_LAMBODY、I_LETV→I_LETD。
  ④ 三处续体 TASK_INFER 发射加宽 `E2 = One + reglu(mode_st, 8)`：
  I_PI（APP 参数 infer）、I_LAMSORT（lam body infer）、I_LETD（let body
  infer）——mode 从**当前帧自身 F2** 解码（SD-1 失效的破局点）。
  pi codomain 链（I_PIS1/I_PIL1/I_PIS2/I_PIL2）与 DEFEQ soft 发射不 widening
  ——遗留近似按 memo §3.3 保留登记。gate 消费面（ck7_gate :5941 经 inf_mode）
  零改动；frF2 全读点盘点（NAT 链/DEFEQ s_env/CHECK g9/INFER 软旗/WALK
  marker）均不受步进编码影响（各帧族 F2 语义专属，ST 帧才进 gid）。
  命令：`G02_ONLY=g03 …` 输出原文（摘除后复跑）：
  ```
  [PASS] A g03a_selfref: oracle=OK graph=code=0(accept) steps=8 registered=True
  [PASS] B g03b_later_ref: oracle=other graph=code=7(unsafeConstUse) steps=5
  [PASS] B g03b2_unsafe_ref: oracle=OK graph=code=0(accept) steps=8 registered=True
  [PASS] C g03c_body_fail: oracle=declTypeMismatch graph=code=1(declTypeMismatch) rollback(member_absent=True, later_ref=code=2(unknownConstant))
  [PASS] E g03e_mutual_xref: oracle=OK graph=code=0(accept) steps=17 members_registered=True
  [PASS] G g03g_arg_selfref: oracle=OK graph=code=0(accept) steps=23
  [PASS] G g03h_lam_selfref: oracle=OK graph=code=0(accept) steps=40
  === card 010 G02 decl-injection differential: 7/7 checks pass, 0 xfail known-gap, 0 fail (574s) ===
  ```
  mode=0 不变性：g03b（safe 引用照拒 7）/g03b2（unsafe 照收）对 PASS；
  KNOWN_GAPS 摘 g03g/g03h 两条（tests:228-242），g03 节头与文件头注释同步。
  全节回归挂 B7。
- [x] B4x. g04 全节复跑确认（/tmp/016_g04_full2.log，detached，含 csctor 新
  家族；首次 detached 跑因混合版本中途杀掉——家族子进程会拾取编辑中的
  3-甲 图，按 pid 清理后重起）。（2026-09-26 完成；日志由总控抢救落
  `~/logs/016B/g04_full2.log`）

  **证据原文（`/home/xkq/logs/016B/g04_full2.log`，1046s，`=== OK ===` 收尾）**：
  ```
  [PASS] G04 nat/d1: oracle=LitNat(value=3) run_whnf=LitNat(value=3) steps=122 rounds=2
  [PASS] G04 nat/d3: oracle=LitNat(value=3) run_whnf=LitNat(value=3) steps=591 rounds=2
  [PASS] G04 nat/d4: oracle=LitNat(value=100) run_whnf=LitNat(value=100) steps=1227 rounds=2
  [PASS] G04 lst/eL1: oracle=LitNat(value=1) run_whnf=LitNat(value=1) steps=108 rounds=2
  [PASS] G04 lst/eL2: oracle=LitNat(value=2) run_whnf=LitNat(value=2) steps=256 rounds=2
  [PASS] G04 lst/eL3: oracle=LitNat(value=2) run_whnf=LitNat(value=2) steps=704 rounds=2
  [PASS] G04 mu/eG4MU1: oracle=LitNat(value=20) run_whnf=LitNat(value=20) steps=134 rounds=2
  [PASS] G04 mu/eG4MU2: oracle=LitNat(value=20) run_whnf=LitNat(value=20) steps=570 rounds=2
  [PASS] G04 iv/eG4IV1: oracle=LitNat(value=5) run_whnf=LitNat(value=5) steps=192 rounds=2
  [PASS] G04 iv/eG4IV2: oracle=LitNat(value=6) run_whnf=LitNat(value=6) steps=775 rounds=2
  [PASS] G04 tree/eG4W: oracle=LitNat(value=6) run_whnf=LitNat(value=6) steps=749 rounds=2
  [PASS] G04 proj/(PProd.mk (Nat.add 1 3) Nat.zero…: oracle=LitNat(value=4) run_whnf=LitNat(value=4) steps=14 rounds=2
  [PASS] G04 proj/(PProd.mk Nat.zero (PProd.mk (Na…: oracle=LitNat(value=9) run_whnf=LitNat(value=9) steps=33 rounds=2
  [PASS] G04 uprod/UProd.fst (UProd.mk 3 4 : UProd …: oracle=LitNat(value=3) run_whnf=LitNat(value=3) steps=16 rounds=2
  [PASS] G04 uprod/UProd.snd (UProd.mk 3 4 : UProd …: oracle=LitNat(value=4) run_whnf=LitNat(value=4) steps=32 rounds=2
  [PASS] G04 csctor/eG4CSC: oracle=LitNat(value=42) run_whnf=LitNat(value=42) steps=9 rounds=2
  [PASS] G04 csctor/eG4RECC: oracle=LitNat(value=999) run_whnf=LitNat(value=999) steps=39 rounds=2
  [PASS] G04 csctor/eG4PRED: oracle=Const(name='k', levels=()) run_whnf=Const(name='k', levels=()) steps=44 rounds=2

  === card 010 G02 decl-injection differential: 18/18 checks pass, 0 xfail known-gap, 0 fail (1046s) ===
  ```
  即 2-乙 摘 `g04iv_eG4IV2`（XPASS→PASS 775 步）+ csctor 新家族 3 行
  （eG4CSC 9 步 / eG4RECC 39 步 / eG4PRED 44 步）全绿；g03 节 7/7 证据
  见 B4 段。g03g/g03h/g04iv_eG4IV2 三条 known-gap 摘除已在 tests 落地
  （B2/B4 段），全量复跑挂 B7。
- [x] B5. 重编译 scratch：`OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u
  model/compile_vm.py --sparse model/step_vm_016_scratch`；dims 实测增量记本段。
  （2026-09-26 完成；实跑命令 `OMP_NUM_THREADS=3 taskset -c 8-13
  /home/xkq/miniconda3/envs/train/bin/python -u model/compile_vm.py --sparse
  model/step_vm_016_scratch`——0-5 被 g04 全节复跑占用、14-19 被 lane 2 画像
  占用，按机器纪律错段到 8-13）

  **实测：34,663 dims / 4,525 lookups / 236,905 nnz**（基线 34,468 / 4,495 /
  235,424 = **+195 dims / +30 lookups / +1,481 nnz**，+0.56%/+0.67%/+0.63%）。
  计数口径与 handoff 011 一致（`len(graph.all_dims)`/`len(graph.all_lookups)`，
  HEAD 版同口径复测 = 34,468/4,495 逐值吻合）。**超 memo 预算（+95-130 /
  +0~+2）的归因**：(a) memo §2.3 的现状模型缺 beat-8 硬拒事实，2-乙 实际
  需要 decline 门（≈23 terms）+ pred_ctor_r 交付臂（≈18）+ cs_ctor_r 直接
  交付臂（≈12）三组 memo 未列的电路；(b) memo 的"写点加宽 3-4 dims"低估——
  实测每 select 臂展开 ≈8-12 terms（×15 写点）。非失控型增长：两项语义特性
  有界增量，编译峰值 700MB 内、25.5s，sparse 正常落盘。
- [ ] B6. 引擎对新 scratch 对拍 34/34（scripts/verify_engine_vs_refvm.py，
  SBIN=新 scratch，meta 校验过）。**→ 判定 FAIL（33/34），见下附录，停手待
  总控裁决（2026-09-26）**

  **B6 附录：引擎对拍 FAIL 记录（2026-09-26，收尾代理；核 0-5、
  OMP_NUM_THREADS=3，解释器 = /home/xkq/miniconda3/envs/train/bin/python）**

  命令：`SBIN=$PWD/model/step_vm_016_scratch.sbin OMP_NUM_THREADS=3 taskset
  -c 0-5 <PY> -u scripts/verify_engine_vs_refvm.py`

  输出原文（关键行；33 行 [PASS] 从略，succ_zero 一行为 [PASS] … known=BAD，
  系脚本静态 known 表与 RefVM 交付形状的既有出入——两次跑 verdict 均 PASS
  ⇒ got 同为 RefVM 期望值 ⇒ known 结果与 015 基线跑相同，非本卡回归）：
  ```
  [FAIL] succ_delta         REJECT   steps=    5 argmax=  3.31s softmax=  5.86s stream_same=True

  === H3 engine vs RefVM: 33/34 verdicts correct ===
      argmax vs softmax streams identical: 34/34
      known-value checks: 3/4
      total engine wall time: argmax 141.0s, softmax 264.6s
    FAIL succ_delta: got='NOT_DONE' exp=LitNat(value=5) (verdict ['REJECT', '1', '215', '0', '5'])
  ```

  **基线对照（同一引擎二进制 engine/vm_run、同一脚本、唯一变量 = sbin）**：
  `SBIN=$PWD/model/step_vm_015_full_scratch.sbin …` 输出原文（尾段）：
  ```
  === H3 engine vs RefVM: 34/34 verdicts correct ===
      argmax vs softmax streams identical: 34/34
      known-value checks: 3/4
      total engine wall time: argmax 143.0s, softmax 267.4s
  ```
  ⇒ **卡 016 图改动引入的回归**（015 = 34/34，016 = 33/34）。

  meta 门（`SBIN=…016_scratch.sbin <PY> -u scripts/verify_engine_tasks.py meta`）
  原文：`=== engine meta vs sbin+tokens: OK (76 output dims, 13 token consts) ===`
  ——meta 校验过， FAIL 仅 verdict 面。

  **陈旧排除**：build_vm.py mtime 03:57:43 < sbin 04:22:15 < checkpoint
  04:44:48，scratch 即 HEAD 源码所编，非混合版本。

  **肇因定界（读 diff 得出，假设级，供修复拍探针定案）**：succ_delta =
  `Nat.succ T_four`（toy_env.py:384），`T_four = Nat.mul T_two T_two`
  （toy_env.py:286）——NAT 链内层 nat-op（mul）的实参是 **delta 可展开
  Const**。checkpoint 新增 decline 门（build_vm.py fire1/fire2，diff 见
  `git show 17a0b82 -- lean_vm/build_vm.py`）把 K_CONST 实参按
  `reglu(_kind_eq_raw(_slK, K_CONST, One), One - _is_zero(_fv0(…)))` 归入
  stuck 叶——**任何非零 Const 实参都算 stuck，无 delta 可展开性判别**，
  叠加 `_nat_caller`（frV0==TASK_NAT）后，NAT 链内经 Const 间接的可归约
  实参从"照旧点火"变为"decline 不点火"，与 B2 执行段"可归约实参照旧点火"
  的声明不符（该声明实测只对字面量/BVar 形状成立）。次疑：pred_ctor_r
  在主 select 链插到 nat_soft 之前 + `rej_n = reglu(nat_hard, One −
  pred_ctor_r)` 的 rej_n 扣除（REJECT code 1 与 B2 探针 p1 修前死法同码，
  `['REJECT','1',…]`）。建议修复拍用 B2 同款 dbg 计数器（dbg_dn1/dbg_nathard）
  对 succ_delta 形状现跑定案，不许按本假设盲改。

  **对 verifier 集的影响**：该回归在 g03/g04（decl_injection，Python 侧）
  不可见（B4x 18/18 全绿），只在 toy 语料经引擎对拍现形——verifier 集
  "引擎对新 scratch 对拍"门设计目的即此，门红 ⇒ 本拍不得收口。B7 全节
  复跑（74min）在 scratch 判 FAIL 前提下不起跑（跑了也不改变拍次判定，
  且修复后须对新 scratch 重跑 B6+B7）；B8 KERNEL_COVERAGE 状态行不记
  "已验证"态；B9 收口报告不出。已按纪律原文上报总控。
- [ ] B7. decl_injection 全节复跑（帽 5000|7000，RSS ~7GB，先查 lane 2 画像
  是否在跑：pgrep -af run_mem_guarded）+ 硬编码零新增自查。
- [ ] B8. 文档同步：docs/VM_SPEC.md §16.7 stage C 正式条款 + F2 载体编码
  新小节、docs/KERNEL_COVERAGE.md 对应行、ENV_FORMAT（如需）。
- [ ] B9. 最终报告给总控（会话输出）。

### 拍 B 收尾段（图逻辑工程师续，2026-09-26 开工；续接第 5 次限流事故，
### B1-B5 已完成不许重做，只做 B4x 记账 + B6/B7/B8/B9）

#### 收尾计划清单（开工第一步落盘；每完成一个可验证子步立即回填 [x]，含命令与输出原文）

- [x] C0. 计划落盘（本条）+ 现场核对：HEAD=17a0b82 工作树干净；
  `model/step_vm_016_scratch.sbin` 在库（23,234,470B，2026-09-26 04:22）；
  `engine/vm_run` 二进制在库（2026-09-21 16:19，卡 013 代次）；
  `pgrep -af run_mem_guarded` 无别的大 env 任务；g04_full2.log 证据已在
  `~/logs/016B/`（总控抢救自 /tmp）。（2026-09-26 完成）
- [x] C1（=B4x 记账）：B2/B4/B4x 三个 checkbox 补 [x]；B4x 下贴
  `~/logs/016B/g04_full2.log` 18/18 原文。（2026-09-26 完成）
- [x] C2（=B6 引擎对拍）：已执行并记录，**判定 FAIL（33/34，succ_delta
  回归），证据与定界见 B6 条目下附录**；meta 门 OK。停手待总控裁决，
  C3-C5 未起跑。（2026-09-26 完成）
- [ ] C3（=B7 全节复跑）：**NOT-VERIFIED，未起跑**——B6 判 FAIL 后按纪律
  停手（修复后须对新 scratch 重跑 B6+B7，本跑不作数）。

  **硬编码零新增自查（已完成，2026-09-26，独立于 B7 可先交）**：
  ① `git diff 17a0b82 -- lean_vm/build_vm.py lean_vm/step_driver.py
  expr/tokens.py` = 空（工作树即 checkpoint，无未提交改动）；
  ② checkpoint `git diff 17a0b82^ 17a0b82` 三文件中仅 build_vm.py 有改动
  （step_driver.py/tokens.py 零触碰），167 行改动逐块过：
  新电路引用 = `_SUCC_CID`（既有 `_SCAN_OPS` 名字扫描产物，例外条款适用）+
  既有 kind/帧类码（K_CONST/K_LIT/TASK_NAT/OP_PRED/OP_SUCC）+ 编码参数
  （MODE_STRIDE=128、CHECK_E2_STRIDE 既有形制）；`Nat.pred`/`Nat.rec` 等具名
  仅出现在注释；select 链插入（cs_ctor_r/pred_ctor_r）与 `em_frame
  dn1 − pred_ctor_r` 为机械改键。**结论：具体常量名/cid 分支零新增，自查
  PASS**（依据：上述 diff 全文，非转述）。
- [ ] C4（=B8 文档同步）：**未执行**——KERNEL_COVERAGE 状态行不得在引擎
  门红时记"已验证"态；VM_SPEC §16.7.1/§16.7.2 复核留修复拍一并做。
- [ ] C5（=B9）：**收口报告不出**（拍次未绿）；B6 FAIL 原文已按纪律上报
  总控（2026-09-26）。

### 拍 B 修复段（总控 2026-09-26 裁决授权：B6 FAIL 坐实，解除"不许碰实现"
### 限制，触碰面 = decline 门判别面及其直接关联电路；落盘纪律照旧）

#### 修复计划清单（开工第一步落盘；每子步完成即回填 [x]，含命令与输出原文）

- [x] F0. 计划落盘（本条）+ 触碰面声明：只许改 `lean_vm/build_vm.py` 的
  decline 门判别面（_sl1/_sl2 的 K_CONST 子句及其新增取值电路；
  pred_ctor_r 插序仅当探针证实共犯才动）；tests/model 其余实现不动；
  model/ 只许重编 `step_vm_016_scratch.sbin`；禁止 git。

  **F0x. 接手计划（图逻辑工程师续，2026-09-26；前代理死于 harness 错误，
  F3 代码已在工作树、F1/F2 证据未回填、F4 起未跑——本会话只补证据 + 走
  完整验证链，按限流死亡教训每子步立即回填）**：
  1. F1 先行（纯只读）：实读 `/home/xkq/lean4/src/kernel/` 钉三锚行号
     （type_checker.cpp / declaration.h / reduce_nat 所在文件），行号以实读
     为准回填本段。
  2. F2 探针定案（不许跳过，证据先于一切）：修前图 = `git show
     17a0b82:lean_vm/build_vm.py` 落 `/tmp/build_vm_016b_prefix.py`，经
     `G02_LEGACY_BUILD_VM` 指给 /tmp/probe_016b2_fix.py 的
     `_load_graph_builder`（修后跑 = 同脚本不带该 env，即工作树）；
     ① TRACE_CARRIER=s1（succ_delta 形状）修前 dbg 逐拍，判 decline 唯一
     死因 + pred_ctor_r 不参与；② oracle 两侧（s1 def→字面量、s2
     axiom→stuck）原文回填。若①推翻假设：停手上报，不碰语义。
  3. F3 只核对不重写：已落 _sl1/_sl2 K_CONST 子句与探针结论一致性 +
     py_compile；矛盾才最小修正。
  4. F4 最小差分（同 A/B 法）：succ_delta 翻正 LitNat(5) AGREE；
     p1/p2/p5/p6/p7/p9/p10 与修前逐值相等；字面量路径零增量。
  5. F5 → F6 → F7 → F8 验证链按卡原文执行；F8 起跑前 pgrep 查冲突，
     setsid 脱管记 pid 轮询。
  6. F9 文档 + F10 报告。全程禁 git、禁碰 tests/step_driver/tokens/engine/。
     （2026-09-26 落盘，随即开工 F1）
- [x] F1. 核侧合同钉线：whnf delta 只展开**有值**常量（defnInfo 带 value；
  axiom/opaque 无 value 才真 stuck）——读 `/home/xkq/lean4/src/kernel/`
  钉 file:line 记本段。（2026-09-26 完成，三锚实读全部吻合前代理注释）

  实读原文钉线（/home/xkq/lean4/src/kernel/，4.35 master）：
  - `type_checker.cpp:555-563` `type_checker::is_delta`：仅当
    `env().find(const_name(f))` 且 **:559 `info->has_value() &&
    length(const_levels(f)) == info->get_num_lparams()`** 才返回 info——
    delta 可展开性 = 有值 + level 参数数匹配。函数注释 :554 "If is_delta
    succeeds, then unfold_definition will also succeed"。
  - `declaration.h:230` `bool has_value() const { return is_definition(); }`，
    :228-229 文档原文："Only definitions have values for the purpose of
    reduction and type checking. Theorems used to be like that; now they are
    treated like opaque declarations."——axiom/opaque/ctor/thm 一律无值。
  - `type_checker.cpp:702` `reduce_nat`（succ 臂 :704-713：实参先 `whnf`
    再 `is_nat_lit_ext` 门；二元 op 臂 :643-668 两实参 whnf 后同门）；
    `is_nat_lit_ext` :637 `= e == *g_nat_zero || is_nat_lit(e)`——
    reduce_nat 只吃 Nat.zero 常量或字面量。
  **合同结论**：K_CONST 实参能否 whnf 到字面量取决于其常量是否**有值**
  （有值 def 可经 delta → iota/reduce_nat 到字面量，如 T_four；无值
  axiom/opaque 永远 head-normal stuck，如 `Nat.succ kq`）。decline 门把
  有值 Const 归入 stuck 叶 = 与核侧合同相反，坐实判别面缺口；修复方向
  （有值照旧点火、无值才 decline）与 :559 合同一致。
- [x] F2. 探针定案（不许跳过）：
  ① dbg 计数器（dbg_frv0/dbg_fire1/dbg_fire2/dbg_dn1/dbg_nathard，B2 探针
  同款 TraceDrv）对 `succ_delta = Nat.succ T_four` 现跑修前图，确认 decline
  是唯一死因（NAT(succ) 链内 mul 因 K_CONST 子句 decline 不点火）且
  pred_ctor_r 未参与该死法；
  ② oracle 现跑（4.33.1）钉两侧：`Nat.succ <axiom>` → stuck（整项 head-
  normal）、`Nat.succ <def 常量>`（T_four 形）→ 归约到字面量。输出原文贴
  本段。若①推翻"decline 门唯一死因"假设：停手写证据上报。
  （2026-09-26 完成：①假设**坐实未推翻**，修复方向验证通过；②两侧钉死）

  探针 = /tmp/probe_016b2_fix.py（前代理遗留，原样使用；DEFS 含
  `opaque kq : Nat` / `def s1 := Nat.succ T_four` / `def s2 := Nat.succ kq`，
  carriers=[s1,s2]，oracle 经 T.LEAN_CMD = 4.33.1 现跑，零预置）。修前图 =
  `git show 17a0b82:lean_vm/build_vm.py > /tmp/build_vm_016b_prefix.py`
  （py_compile OK），经 `G02_LEGACY_BUILD_VM` 注入；另补 **pre-beat-B 第三点
  对照**（`git show 5f783bc:lean_vm/build_vm.py`，无 decline 门）用于判别
  s2 是否既有缺口。命令（taskset 内 env 须用 `env` 包裹）：
  `taskset -c 0-5 env OMP_NUM_THREADS=3 G02_LEGACY_BUILD_VM=/tmp/
  build_vm_016b_prefix.py TRACE_CARRIER=s1 <PY> -u /tmp/probe_016b2_fix.py`

  **① 修前图 dbg 原文（s1 即 succ_delta 形状）**：
  ```
  ORACLE s1: LitNat(value=5)
  ORACLE s2: App(fn=Const(name='Nat.succ', levels=()), arg=Const(name='kq', levels=()))
  GRAPH-SOURCE: legacy copy /tmp/build_vm_016b_prefix.py
  beat 6: {'done': 0, 'reject': 1, 'reject_code': 1, 'A': 275, 'B': 0, 'C': 1389, 'D': 1391, 'E': 0, 'F': 1392, 'dbg_frv0': 2, 'dbg_main': 1, 'dbg_fire1': 0, 'dbg_fire2': 0, 'dbg_dn1': 1, 'dbg_d23': 0, 'dbg_complete': 1, 'dbg_natsoft': 0, 'dbg_nathard': 1}
  s1: graph =VMError code=1 REJECT steps=6 DIVERGE
  ```
  **② 修后（工作树）原文**：
  ```
  GRAPH-SOURCE: in-tree build_vm
  s1: graph =LitNat(value=5) steps=79 AGREE
  ```
  **②' pre-beat-B（5f783bc）原文**：
  ```
  GRAPH-SOURCE: legacy copy /tmp/build_vm_015e.py
  s1: graph =LitNat(value=5) steps=79 AGREE
  ```
  **判读**：(a) 修前 fire1=0/fire2=0（decline 门把 T_four 归 stuck 叶不点火）
  → dn1=1 → nat_hard 击杀 REJECT code=1 @beat 6——与 B6 引擎侧
  `['REJECT','1',…]` 同码，decline 饿死是唯一死因；(b) 形状无 `Nat.pred`
  且 pre-beat-B 图无 pred_ctor_r 电路而 s1 AGREE ⇒ pred_ctor_r 零参与；
  (c) 修后 79 步与 pre-beat-B **逐值相等** ⇒ F3 把 delta 路径精确还原为
  修前基线行为。

  **登记观察（不在本卡触碰面，未修）**：s2 = `Nat.succ <axiom>` 三版本
  （pre-B / 修前 / 修后）同样 REJECT code=1 @beat 3（计数器逐值相同：dn1=1
  nathard=1，decline 点火后 const_stuck 完成路径未接住裸 stuck 叶）——
  **既有缺口，非本卡引入、F3 未改变**（oracle 钉真值为 stuck 形
  `App(Nat.succ, kq)`）；本卡 verifier 面（B6 引擎 34 行 = RefVM 期望 +
  g03/g04 语料）不含该形状，登记供后续卡排产，本拍不上手。
- [x] F3. 实现：_sl1/_sl2 的 K_CONST 子句收窄为"**无值常量**"——读 pend
  条目 cid（`_fv0`，既有）→ env 头 `cid+1` 位置 V2 值指针（与主机器
  `const_delta` 的 `eV2 ≥ 1` 同一信号同一寻址，:342 注释 C-scheme），V2=0
  才 decline；有值 Const 照旧点火。零新增硬编码 cid/常量名。py_compile。
  （2026-09-26 完成：前代理已落代码，本步只核对，未改动；py_compile OK）

  核对结论（三面全部一致，代码原样保留）：
  ① **寻址一致性**：`_slval1 = fetch_by_position([v2_], _slcid1 + One)[0]`
  与主机器 :343 `eV2 = fetch_by_position([v2_], fV0 + One)` 同寻址
  （:341-342 "ENV header for const cid: headers occupy positions cid+1
  (C-scheme)"），`:756 const_delta = reglu(reglu(is_const, _geq_expr(eV2,
  One)), main_mode)` 同信号（V2≥1 = 有值）。
  ② **语义差集 = 探针修复方向**：修前 decline = [K_CONST]·[cid≠0]；修后
  = [K_CONST]·[cid≠0]·[V2=0]。行为差集恰为「cid≠0 ∧ 有值」集（delta 可
  展开），F2 探针实测该集从 REJECT@beat6 翻正 AGREE@79 步；cid-0 零常量面
  （is_zconst_r）与无值常量（axiom/opaque/ctor/thm）两侧均与修前逐值不变
  （s2 三版本同 REJECT beat 3 实证）。
  ③ **注释锚**：代码内注释三锚与 F1 实读行号吻合（is_delta
  type_checker.cpp:555-563 / has_value declaration.h:230 / is_nat_lit_ext
  :637 + reduce_nat succ 臂 :704-713）。
  py_compile：`/home/xkq/miniconda3/envs/train/bin/python -m py_compile
  lean_vm/build_vm.py` → OK（本步复跑）。
- [x] F4. 最小差分（探针 harness A/B，修前图 = 修前源码副本）：succ_delta
  形状翻正（= LitNat(5) AGREE）；p1/p2/p5/p6/p7/p9/p10 步数与修前逐值相等
  （axiom k 无值 → decline 行为不变；字面量路径 K_LIT 子句未动）。
  （2026-09-26 完成，A/B 全等）

  harness = /tmp/probe_016b_csctor.py（B2 dev 探针，carriers
  p1/p2/p5/p6/p7/p9/p10，oracle 4.33.1 现跑）；修前图 =
  `G02_LEGACY_BUILD_VM=/tmp/build_vm_016b_prefix.py`，修后 = 工作树。
  命令：`taskset -c 0-5 env OMP_NUM_THREADS=3 [G02_LEGACY_BUILD_VM=…]
  /home/xkq/miniconda3/envs/train/bin/python -u /tmp/probe_016b_csctor.py`

  **A/B 关键行（七形状结果与步数序列修前/修后逐值全等）**：
  ```
  p1: graph =VMError code=1 REJECT steps=15 DIVERGE      （两版同；登记残余不变）
  p2: graph =…Nat.casesOn… steps=28 DIVERGE              （两版同；005 F7-01 既有家族不变）
  p5: graph =LitNat(value=1000) steps=111 AGREE          （两版同）
  p6: graph =LitNat(value=1001) steps=204 AGREE          （两版同；字面量路径零增量）
  p7: graph =LitNat(value=42)   steps=213 AGREE          （两版同）
  p9: graph =LitNat(value=999)  steps=243 AGREE          （两版同）
  p10: graph =Const(name='k', levels=()) steps=248 AGREE （两版同）
  PROBE-DONE
  ```
  注：harness 单 drv 跨 carriers 累计计步（p1 15 → p2 28 → …），绝对值与
  B2 段单载体口径不同属预期；A/B 同 harness 同 env，逐值相等判定有效。
  succ_delta 翻正证据 = F2 段（s1 修前 REJECT@beat6 → 修后 LitNat(5)
  AGREE@79，且与 pre-beat-B 逐值同）。
- [x] F5. g03 + g04 两节受影响行复跑（G02_ONLY=g03 / G04_FAMILY 全家族），
  受影响行原文贴本段。（2026-09-26 完成，两节全绿零倒退；g03 pid=3984719
  核 0-5、g04 pid=3984720 核 14-19，均 setsid 脱管）

  g03 命令：`setsid nohup env OMP_NUM_THREADS=3 G02_ONLY=g03 taskset -c 0-5
  <PY> -u tests/test_decl_injection_vs_lean.py > /tmp/016fix_g03.log 2>&1`
  尾段原文（mode 载体受影响行 = g03g/g03h，562s）：
  ```
  [PASS] G g03g_arg_selfref: oracle=OK graph=code=0(accept) steps=23
  [PASS] G g03h_lam_selfref: oracle=OK graph=code=0(accept) steps=40
  === card 010 G02 decl-injection differential: 7/7 checks pass, 0 xfail known-gap, 0 fail (562s) ===
  === OK ===
  ```
  g04 命令：`setsid nohup env OMP_NUM_THREADS=3 G02_ONLY=g04 taskset -c 14-19
  <PY> -u tests/test_decl_injection_vs_lean.py > /tmp/016fix_g04.log 2>&1`
  全家族 18/18（1184s），受影响族原文（nat 逐值同 B4x、iv eG4IV2 修复行、
  csctor 新族 3 行，步数与 B4x 逐值相等）：
  ```
  [PASS] G04 nat/d1: oracle=LitNat(value=3) run_whnf=LitNat(value=3) steps=122 rounds=2
  [PASS] G04 nat/d3: oracle=LitNat(value=3) run_whnf=LitNat(value=3) steps=591 rounds=2
  [PASS] G04 nat/d4: oracle=LitNat(value=100) run_whnf=LitNat(value=100) steps=1227 rounds=2
  [PASS] G04 iv/eG4IV1: oracle=LitNat(value=5) run_whnf=LitNat(value=5) steps=192 rounds=2
  [PASS] G04 iv/eG4IV2: oracle=LitNat(value=6) run_whnf=LitNat(value=6) steps=775 rounds=2
  [PASS] G04 csctor/eG4CSC: oracle=LitNat(value=42) run_whnf=LitNat(value=42) steps=9 rounds=2
  [PASS] G04 csctor/eG4RECC: oracle=LitNat(value=999) run_whnf=LitNat(value=999) steps=39 rounds=2
  [PASS] G04 csctor/eG4PRED: oracle=Const(name='k', levels=()) run_whnf=Const(name='k', levels=()) steps=44 rounds=2
  === card 010 G02 decl-injection differential: 18/18 checks pass, 0 xfail known-gap, 0 fail (1184s) ===
  === OK ===
  ```
  （lst/mu/tree/proj/uprod 10 行亦全 PASS，原文在 /tmp/016fix_g04.log，
  步数 108/256/704/134/570/749/14/33/16/32 与 B4x 逐值相等）
- [x] F6. 重编译 `model/step_vm_016_scratch.sbin`（错峰选核），dims 增量
  记本段。（2026-09-26 完成）

  命令：`OMP_NUM_THREADS=3 taskset -c 0-5 /home/xkq/miniconda3/envs/train/bin/
  python -u model/compile_vm.py --sparse model/step_vm_016_scratch`
  尾段原文：`saved model/step_vm_016_scratch.sbin (236,947 nnz)`（编译约 40s）。
  同口径复测（build_step_graph 后 `len(g.all_dims)`/`len(g.all_lookups)`）：
  **34,671 dims / 4,527 lookups / 236,947 nnz**——F3 修复增量 = **+8 dims /
  +2 lookups / +42 nnz**（对照修前 34,663/4,525/236,905）；对 011-后 HEAD
  基线 34,468/4,525→见 B5 段口径，累计 +203/+32/+1,523（+0.59%/+0.71%/
  +0.65%），符合"有界增量"定性。
- [x] F7. B6 重跑：引擎对拍 34/34 + 双流一致 + meta 门（SBIN=新 scratch），
  原文贴 B6 附录后继段。（2026-09-26 完成，**34/34 全绿**，B6 回归摘除）

  命令：`setsid nohup env OMP_NUM_THREADS=3 SBIN=$PWD/model/
  step_vm_016_scratch.sbin taskset -c 0-5 <PY> -u
  scripts/verify_engine_vs_refvm.py > /tmp/016fix_f7_engine.log`
  尾段原文（修复行 succ_delta + 总账）：
  ```
  [PASS] succ_delta         DONE     steps=   78 argmax=  4.99s softmax=  9.48s stream_same=True

  === H3 engine vs RefVM: 34/34 verdicts correct ===
      argmax vs softmax streams identical: 34/34
      known-value checks: 3/4
      total engine wall time: argmax 146.2s, softmax 275.1s
  ```
  succ_zero 行仍 `… known=BAD exp=App(fn=Const(name='Nat.succ',…Nat.zero…))`
  ——B6 附录已定性的静态 known 表与 RefVM 交付形状既状，verdict PASS，
  非本卡回归。meta 门：`SBIN=…016_scratch.sbin <PY> -u
  scripts/verify_engine_tasks.py meta` → `=== engine meta vs sbin+tokens:
  OK (76 output dims, 13 token consts) ===`。基线对照：015=34/34（B6 附录）、
  修前 016=33/34、修后 016=**34/34**。
- [x] F8. B7 全节复跑（REGRESSION_CORES=0-5，全新 LOG_DIR=$HOME/logs/016B/reg，
  先 pgrep 确认无冲突任务），106 行记账或按实际。（2026-09-26 完成：第 1/2
  次被内存帽击杀 NOT-VERIFIED、第 3 次证据定帽 9000 后 **106/106 全绿**，
  事故与帽重校建议见下）

  **第 1 次尝试（reg2，事故记录 2026-09-26）：NOT-VERIFIED——被内存护栏
  击杀，非语义失败**。命令 = 修复段原文（SUITE_FILTER=decl_injection，
  LOG_DIR=$HOME/logs/016B/reg2，bash pid 4095686）；结果：
  `[mem-guard] wall 3367.3s peak RSS 7003MB rc=-9 KILLED: RSS 7003MB >
  cap 7000MB`（.rc=137）。击杀点 = g04 delivery 段 iv 族子进程运行中
  （nat/lst/mu 三族已完成回灌，[PASS] 行因父进程 capture_output 缓冲
  全部丢失）。**定界**：树峰值 = 母套件进程（guard/g02/g03 段后 ~3.7GB）
  + iv 族子进程（最大族，59 consts）≈ 7.0GB，F3 图增量 +203 dims
  （+0.59%）把本就贴帽运行的树顶穿 3MB（0.04%）——系统性越界非偶发
  抖动，原样重试无意义。**脚本 SUITES 表内注释载有卡 015 完全同款先例**
  （"dims +32% pushed the full run past … Cap 2700|4000 -> 5000|7000"）：
  帽重校属总控职权（scripts/ 不在本卡触碰面），本拍按同款处置用仓库钦定
  护栏直跑测试本体补证据（帽 7500MB，见下），总控收口时正式校准表值。

  **第 2 次尝试（reg3，直跑 + 钦定护栏）：NOT-VERIFIED——同点击杀**。
  `[mem-guard] wall 3217.3s peak RSS 7505MB rc=-9 KILLED: RSS 7505MB >
  cap 7500MB`（g04 段 iv 族窗口，与 reg2 同点位）。**两次数据合读**：
  护栏报告的"峰值"= 击杀穿越值（reg2 穿 7000 即死 7003、reg3 穿 7500
  即死 7505）⇒ 树真实需求 **>7505MB 且上界未知**，帽值系统性不足，非
  边缘抖动；继续逐档加帽 = 盲试（纪律禁止第 3 次盲改）。

  **第 3 步诊断（g04 分节，帽 9000）：完成**，`=== card 010 G02
  decl-injection differential: 18/18 checks pass, 0 xfail known-gap, 0 fail
  (1007s) ===` + `[mem-guard] wall 1006.8s peak RSS 6866MB rc=0`——
  **g04 分节树峰值实测 6866MB**（卡 015 同分节 5894MB → 拍 B +972MB，
  与 +203 dims + iv 族 2 常量 + csctor 子进程 + 新载体 per-step 求值器
  状态相符，卡 012 M-B 画像 1.3MB/token 量级）。全量需求估算 = 6866 +
  母进程跨节保留 ≈ 7.6-7.9GB。

  **第 3 次尝试（reg4，全量 + 帽 9000，证据定帽非盲试）：PASS**。
  命令 = 第 2 次同款、帽 9000；原文（尾段）：
  ```
  [PASS] G9 g9thm_dup_nonprop: oracle=other graph=code=10(dupUnivParams) steps=1
  [PASS] G9 g9name_lp: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0

  === card 010 G02 decl-injection differential: 106/106 checks pass, 0 xfail known-gap, 0 fail (3798s) ===
  === OK ===
  [mem-guard] wall 3798.6s peak RSS 7640MB rc=0
  ```
  **106/106 + 0 xfail + 0 fail**（= 卡面预期 106 行；三条 known-gap
  g03g/g03h/g04iv_eG4IV2 已在 B2/B4 摘除，受影响行原文：g03g 23 步 /
  g03h 40 步 / eG4IV2 775 步 / eG4CSC 9 步全 PASS）。真峰值 **7640MB**。
  硬编码零新增自查见 F9 段（PASS）。

  **移交总控（帽重校）**：decl_injection SUITES 表现值 `5000|7000` 已被
  拍 B 图增量顶穿（reg2 7000/reg3 7500 两次击杀、分节实测 6866MB、全量
  真峰值 7640MB）。按 harness 自身余量哲学（卡 015：实测 5894 → 帽
  7000 = ×1.19），建议 `5000|7000` → **`5000|9200`**（7640×1.20≈9170）；
  timeout 5000 实测 3798s 余量充足不动。logs：reg2/reg3/reg4/g04diag =
  `~/logs/016B/{decl_injection_vs_lean.log→reg2/, reg3.log,
  reg3_g04diag.log, reg4.log}`。
- [x] F9. B8 文档同步：KERNEL_COVERAGE.md I_CASE/mode 两行状态+file:line；
  VM_SPEC §16.7.1/§16.7.2 对照实现复核勘正（含 decline 门新判别面表述）。
  （2026-09-26 完成，F7 引擎门绿后落笔，状态行记"已验证"态合规）

  **docs/KERNEL_COVERAGE.md**（2 处）：
  - G2 行：mode 位跨 ST 续体"已知缺口…XFAIL 登记"改为**已修复（卡 016
    3-甲）**+ MODE_STRIDE 载体编码表述 + 解码单点 `build_vm.py:3207-3220`
    + g03g/g03h 转 PASS（23/40 步）；工作包列补卡 016；verifier 列
    XFAIL→PASS、VM_SPEC 引用补 §16.7.1。
  - 新增 **B15 行**（I_CASE 主前提 whnf 续推，原矩阵无此行——beat B 的
    B8 未执行过，按 B 组行格式补）：`K/inductive.h:93,99-100,114` 合同 +
    三件套（decline 门/分类面扩展+直接交付/pred 形状规则）+ 无值 Const
    判别 + 修复段 succ_delta 故事一行 + 图侧 file:line（:773-793/:1072/
    :1111/:1633/:1074/:1584/:6088-6090/:531）+ verifier（G04 18/18、引擎
    34/34+meta）+ 残余两条登记。

  **docs/VM_SPEC.md**（3 处）：
  - §16.7.2 头段勘误：`is_nat_expr` → **`is_nat_lit_ext`**（=:637，
    Nat.zero 常量或字面量），行号 `:702-733` → succ 臂 **:704-713**。
  - §16.7.2 item 1 勘正：判别面"非零 Const"→"**无值 Const**（cid≠0 且
    env 头 cid+1 位置 V2 值指针=0，即 axiom/opaque/ctor/thm）"，补
    同寻址同信号锚（:341-343/:782-791）+ 核侧 has_value 合同
    （type_checker.cpp:555-563 / declaration.h:230）+ 有值 Const 照旧
    点火 + 修复段探针故事（REJECT@beat6 → 79 步 AGREE 同 pre-B）。
  - §16.7.2 残余段补第三条：裸 `Nat.succ <无值 Const>`（s2 形）decline
    后 const_stuck 完成路径未接住——**pre-beat-B 即同行为**（F2 探针
    三版本对照实证，非本卡引入），登记后续卡。
  - §16.7.1 对照实现复核：解码公式/写点清单/mid() 助手与 ：3207-3220
    逐条吻合，无事实漂移，仅补行号锚（"续体门区"→"`build_vm.py:
    3207-3220` 续体门区"）。

  **F3 硬编码零新增自查**：`git diff` 工作树 22 行仅新增 `_slcid1/_slval1/
  _slcid2/_slval2` 四个中间量，电路 = 既有 `_fv0`/`fetch_by_position`/
  `reglu`/`_is_zero`/`_geq_expr`/`K_CONST` 组合 + env 头 C-scheme 寻址，
  零具体常量名/cid 分支（`_SUCC_CID` 等名字扫描产物未新增）。自查 PASS。
- [x] F0y. 续接核验段（图逻辑工程师续接，2026-10-04；总控简报基于死点快照
  HEAD=0a2d0f1，实际 77f4b6e 已入库 F1-F9——按简报首要指令"核对已落代码
  与探针结论一致，探针为准"对已落修复做全链独立复验，**零代码改动**，
  `lean_vm/build_vm.py` py_compile OK）：

  **F1 复验**：三锚实读全部吻合（`K/type_checker.cpp:555-563` is_delta、
  :559 `info->has_value() && length(const_levels(f)) == info->get_num_lparams()`；
  `K/declaration.h:230` `has_value() = is_definition()`；
  `K/type_checker.cpp:637` is_nat_lit_ext、:702 reduce_nat、succ 臂 :704-713
  实参先 whnf 再过门）。已落代码注释三锚一致。

  **F2 复验（探针现跑 = ~/logs/016B/probe_016b2_fix.py 原样；修前图 =
  `git show 17a0b82:lean_vm/build_vm.py` → /tmp/build_vm_016b_prefix.py，
  py_compile OK；护栏 run_mem_guarded 6000MB、核 0-5、真值解释器）**：
  ```
  ORACLE s1: LitNat(value=5)
  ORACLE s2: App(fn=Const(name='Nat.succ', levels=()), arg=Const(name='kq', levels=()))
  修前(17a0b82): beat 6: {... 'dbg_fire1': 0, 'dbg_fire2': 0, 'dbg_dn1': 1, ... 'dbg_nathard': 1}
                 s1: graph =VMError code=1 REJECT steps=6 DIVERGE
                 s2: graph =VMError code=1 REJECT steps=3 DIVERGE（beat 3）
  修后(工作树):  s1: graph =LitNat(value=5) steps=79 AGREE
                 s2: graph =VMError code=1 REJECT steps=3 DIVERGE（beat 3）
  pre-B(5f783bc): s1: graph =LitNat(value=5) steps=79 AGREE
                  s2: graph =VMError code=1 REJECT steps=3 DIVERGE（beat 3）
  ```
  关键计数器（fire1/fire2/dn1/nathard/beat/步数）与 F2 段原文逐值相同
  ⇒ decline 唯一死因、pred_ctor_r 零参与、修后 = pre-B 逐值还原，
  三结论现跑坐实；oracle 两侧现跑钉死（def→字面量 5 / axiom→stuck 形）。

  **F4 复验（probe_016b_csctor.py A/B，修前 vs 工作树）**：七形状
  verdict/形状/累计步数逐值全等：p1 REJECT 15 / p2 DIVERGE 28 / p5 111 /
  p6 204 / p7 213 / p9 243 / p10 248（两版同）——行为差集收敛于
  有值 Const decline 面。

  **F5/F8 证据在位**：/tmp 日志已被清理，证据以 `~/logs/016B/reg4.log`
  存档为准（106/106 + 0 xfail + 0 fail 3798s、peak 7640MB rc=0；受影响
  行 g03g 23 / g03h 40 / eG4IV2 775 / eG4CSC 9 / eG4RECC 39 / eG4PRED 44
  与 F5/F8 引文逐值一致）。

  **F6 复验**：build_step_graph 复测 DIMS 34671 / LOOKUPS 4527（与 F6 段
  逐值同）；新鲜度序 build_vm.py 05:32 < sbin 06:59（sbin = 修复后源码
  所编，未被后续改动覆盖）。

  **F7 复验（本会话现跑，/tmp/016v_engine.log；SBIN=016 scratch，核 0-5）**：
  ```
  [PASS] succ_delta         DONE     steps=   78 argmax=  4.75s softmax=  9.12s stream_same=True

  === H3 engine vs RefVM: 34/34 verdicts correct ===
      argmax vs softmax streams identical: 34/34
      known-value checks: 3/4
      total engine wall time: argmax 156.8s, softmax 303.1s
  ```
  meta 门复验：`=== engine meta vs sbin+tokens: OK (76 output dims,
  13 token consts) ===`。

  **F9 复验**：77f4b6e 内 KERNEL_COVERAGE（G2 行改写 + B15 新行）与
  VM_SPEC（§16.7.1 行锚、§16.7.2 is_nat_lit_ext 勘误 + 无值 Const 判别
  面 + 残余第三条）diff 与段内声明一致；行锚抽查 build_vm.py
  :783-792（decline 取值电路）/:3207-3212（MODE_STRIDE 解码）在位。

  **beat C 现状观察（非本拍触碰面，报总控）**：09-26 10:57 起跑的独立
  全量回归（pid 551211，`$HOME/logs/016C/reg`）止于 8/23 套件：
  mutation_reject 被护栏 wall 帽击杀（`[mem-guard] wall 1200.3s peak RSS
  1930MB rc=-9 KILLED: wall 1200s > timeout`，Part A 16/16 已绿），
  stepgraph_infer_defeq 11:48 收尾后无新套件产出（.rc 最晚
  2026-09-26 11:48:59）、进程已不在——decl_injection 等 15 套件未在
  016C 复跑。需总控对 beat C 处置（续跑/改帽重派）。
- [x] F10. B9 最终报告给总控。（2026-10-04 会话输出交付，证据见 F0y 段）
