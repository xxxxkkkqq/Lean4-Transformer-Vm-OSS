# ADR 018：软 INFER 通道对齐内核 infer_only 脊（I_ARG_S）+ d6 残环停手为 KNOWN-GAP

日期：2026-09-16　状态：**accepted**（总控裁决 2/3/4 授权，卡 009 F15 执行；
裁决 3 明令第 3 次尝试失败即停、无第 4 次）
相关：docs/handoffs/005-F-iota.md（F13-02、F14 fix2、F15-01…F15-09）、
docs/decisions/017-upstream-scope-gap-and-cache-layer.md（残环的后续出路）、
docs/VM_SPEC.md §8（DEFEQ 软 whnf / 卡对链）、docs/KERNEL_COVERAGE.md B 组、
tests/test_brec_drec_iota_vs_lean.py（KNOWN_GAPS 注册表）

## 背景

卡 009 差分账面 2 分歧（d4 步数帽、d6 卡对环）。d6 的第 3 次尝试（裁决 2）
换新简报重做：**不再做 I_ARG 跳参变体**，而是把软 INFER 通道（proof-irrel
链上的 infer 任务）对齐内核 infer_app 的 infer_only 脊。

内核依据（4.33.1 二进制行为，4.35 master 源码只读参考）：

- `K/type_checker.cpp:189-205`（infer_app infer_only 路径）：**从不 infer
  实参、从不做 arg-vs-domain 的 is_def_eq**；沿 Pi 体走，末尾 instantiate_rev。
- 对照 `:174-188`（完整 infer_app）：只有硬通道才 infer 实参并比 domain。
- 后果：非证明类型在软脊上 is-prop 失败 → 整条链 stuck（卡对链的形成机制）。

前两代修复（F13-02、F14 fix2）都是在硬 I_ARG 上做跳参变体，全部把 d7
（d6l=?=d7r，期望 False 的对照例）打绿或打红，无法同时保 d6/d7。

## 决定

**1. 软脊新增专用臂 I_ARG_S=69（route a）**，老 I_ARG 硬语义一字不动：

- 仅当 ST 挂在软 infer 帧（frF2=1，proof-irrel 链发射）时可达；
- 步进语义 = 内核 infer_only 脊：把 focus 换成其 Pi 体（`v1_(SA)`，状态
  解引用，I_PI step 与 resume 两处同一表达式），args 链逐个经 ensure_pi
  型 WHNF 消费（`args_more = _geq_expr(frE2, One)` 链空判，off-by-one 由
  p8 原始 dump 定位修正），focus 非 Pi 且链未空 → 走既有 i_pi_soft 投递
  通道（**decline 级联语义未动**，裁决 2 禁区之二）；
- 发射计数 link+frame+frame2 与 I_CHK 成功形同构，**c1=POS+1/c2=POS+2
  pend 地址算术未动**（裁决 2 禁区之一）；
- 实现：`lean_vm/build_vm.py`（F15-07 四处编辑 + F15-08 两处修正
  `em_link1_c = chk_ok + pi_walk`、`args_more` 链空判）。

**2. d7 验证通过，软脊保留**：d6l=?=d7r 图判 False，路径 = F15-01 预测形
（软脊走完 → proj-infer 消费链 → IP_PEEL/PI_LVL 失败 → A=0 → PI_TY ST_SP
decline → 卡对链）。与内核 False 一致，且每次软走层 2-4 步干净终止。

**3. d6 停手为 KNOWN-GAP（裁决 3）**。三次尝试（F13-02 / F14 fix2 /
F15 fix3）未闭合，第 3 次失败后 p9b 全程 trace 把环根因钉死——**环不在这条
软脊里**（软 I_ARG_S 每次尝试干净终止），而在卡对链对 go-pair 实参的比较：

- go-pair 脊头对（2149/2149 同 pos 同 env）refl 快道 True；
- 剥到实参对 (2154, B=3197) vs (2154, B=3239)：**同一 pos、不同 env 根**
  （d6r 的原建 go vs d6l 的 delta 展开重建 go）→ refl 快道不可用 →
  落入 DEFEQ 比较内部的 WHNF，而该 WHNF 展开 `Nat.below` 族（每圈新的
  PProd/bvar 位置）→ 反复 PI_T 尝试（s134/s185/s316/s426/s533，结构逐轮
  加深）→ 720 步内不收敛。
- 内核对同一对得到 True 的路径**从不展开 below**：brecOn 是 @[reducible]
  先展开（真 lean `#print Nat.brecOn`：`:= (Nat.brecOn.go t F_1).1`），
  两侧都成 `Proj(go tq F1s, 1)` → 子脊比较 → 同常量 go、实参相等 →
  True（`Nat.brecOn.go t F_1 := Nat.rec ⟨F_1 0 unit,unit⟩ …`，同样
  #print 实测）。两侧 go 同常量同 major，内核按 spine compare 直接收，
  不会走到"同 pos 异 env 根"的比较对上——图侧的 delta 展开重建使两侧
  go 的实参 env 根分叉，这才是与内核的分歧点。
- 三次尝试都试图在比较/软脊层面消解这个 env 根分歧，均未果；裁决 3
  禁止第 4 次。落法：`tests/test_brec_drec_iota_vs_lean.py` KNOWN_GAPS
  注册表，`[XFAIL-KNOWN-GAP]` 不计 divergence、`[XPASS]` 反而 FAIL
  （双向不许静默漂移），用例不删。

## 影响面

- 图：仅 build_vm.py 软通道新增 I_ARG_S 臂 + 软 I_PI ensure_pi 的 focus
  侧门；硬通道、decline 级联、pend 地址算术均未动。引擎/权重/驱动器
  零改动（34/34 与 20 套件为证，见 005 F15-10）。
- 测试：G4_d6 进 KNOWN_GAPS（差分账面 2→1，再因 xfail 规则 →0 计 divergence）；
  d4 由 GRAPH_MAX_STEPS 600→720 解决（裁决 4 无条件，F8-02 线性步数表）。
- 文档：VM_SPEC 增 I_ARG_S 小节；KERNEL_COVERAGE B 组行同步。

## 后续出路（不在本卡）

残环的机制（同位置对反复在增长结构上重比）正是内核 failure/positive
cache 存在的理由（`K/type_checker.cpp:953/972/1042/1251`）。ADR 017 已
立项图侧缓存层（docs/plans/014-kernel-cache-parity.md）；若缓存层落地，
d6 的比较对会在首轮失败后进失败缓存，环自然截断。本 ADR 不修，只指路。

## 证据索引

- d7 预测与实测：005 F15-01（预测）、F15-08（p4d/p4c 判读）；
  trace 原文 `$HOME/logs/009F/f15_p5_d7trace2.log`（修后复跑）、
  `f15_p9b_d6trace.log`（d6 600 步全程）。
- d6 环机制原始 dump：`$HOME/logs/009F/` f15_p8_dump2 系（args 链
  off-by-one 定位）。
- 内核引用：`K/type_checker.cpp:189-205`（infer_only）、`:174-188`
  （完整 infer_app 对照）、`:953/972/1042/1251`（defeq 缓存）；
  真 lean `#print Nat.brecOn` / `#print Nat.brecOn.go` 原文在 005 F15-08。

## 追记 2026-09-17（卡 014 收尾，G4_d6 定性更正——原文一字未删，全录 010-M 板）

帽 1500 归属实测（卡 014 P2 whnf memo 在码后）推翻了本 ADR 登记时的
前提：d6 **不是不收敛环，是合法慢**。

- 判定：P1-only 图 halt=True @1070 步；P1+P2 图 halt=True @1012 步——两
  臂 verdict 均与 live oracle（内核 True）一致
  （`/home/xkq/logs/014/whnf_result_m4_on_1500.json`、
  `m4_d6_{on,p1}_1500.log`）。720 帽截断的是收敛中段，不是环。
- 处置：`GRAPH_MAX_STEPS 720→1100`（总控终局裁决；步帽 = Python 求值器
  墙钟预算，非语义量，d4 600→720 先例的论证标准 = 005 F8-02 线性步数表；
  验收判据是与内核 verdict 一致，不含步数预算）。d6 帽 1100 下转绿，按
  KNOWN_GAPS 的 XPASS 规程摘除 G4_d6 条目（摘除前 XPASS 证明跑
  `m5_brec_xpproof.log`，摘除后 12/12 PASS 0 分歧 0 xfail
  `m5_brec_final.log`）——registry 双向防漂移机制保留。
- 本 ADR「后续出路」段的预期部分修正：环的逐层成本在**新结构的 whnf
  重推**（010-M M1-01c：49 次 DEFEQ 发射 45 次新键），不在同对比败重
  试——失败缓存（P1b）对 d6 无效，卡 014 trace 实测；真正吸收残差的是
  P2 m_whnf memo（省 58 步）与帽预算。正/负缓存合同按 ADR 017 仍是
  判定一致性组成：**P2 memo 保留的独立理由不是 d6**，是内核 `m_whnf`
  合同补齐（查询 :755-757、完成写回 :763/:766/:772，VM_SPEC §18.4）+
  全量不变性零回归 + 活性实证（d6 全程 17 次 1 步重放；专测
  `main_whnf` 活性臂）。
- 卡 009 账面随之更新：B/C 组 11/11（原「10/11+G4_d6=KNOWN-GAP」）。
