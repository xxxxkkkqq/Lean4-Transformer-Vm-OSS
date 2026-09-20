# 板子 010-M — 卡 014「图侧内核缓存层对齐」执行板

继承链：009F（卡 009 终态 F15-16 结案，d6=KNOWN_GAPS xfail G4_d6，帽 720）
→ 本卡 014（ADR 017 缓存层立项、ADR 018 指路）。前板只读：
`docs/handoffs/005-F-iota.md`（F15 段）、`docs/plans/014-kernel-cache-parity.md`。

## 机器姿态（开工快照 2026-09-17）

- 核段：**0-5**（简报写死）。Python 一律
  `/home/xkq/miniconda3/envs/train/bin/python`，长任务经
  `scripts/run_mem_guarded.py`（差分帽 4096-6144）。日志
  `/home/xkq/logs/014/`。同时只挂一个大 env 求值。
- 开工时 `ps --sort=-rss`：唯一大户 = 用户 GPU 训练
  `cpt/train_minimal.py`（pid 2443834，1.3GB，勿动勿杀）。无并行代理。
- 可用内存 22GB；本代理峰值纪律 ≤6GB 主动杀。
- git 零接触（总控执笔）。基线 commit：ce37f48（卡 009 CLOSED）。

## 当前图基线（继承自 009F，ce37f48）

- scratch 编译 `model/step_vm_009_scratch.sbin`：**dims 25,930 /
  lookups 2,898 / nnz 192,405，114L**（本卡编译报增量，别覆盖该文件）。
- 全量差分 0 计 divergence（d6 走 [XFAIL-KNOWN-GAP]）；CPU 回归 **21 套件**
  （brec 套件行已入表，注意不是 20）。
- d6 环机制（ADR 018 定谳）：卡对链 go-pair 实参 (2154,env1) vs
  (2154,env2) 同 pos 异 env 根 → refl 快道不可用 → DEFEQ 内 WHNF 展开
  below 族 → 卡对链反复 PI_T 尝试、结构逐轮加深 → 720 步不收敛。
  内核同常量脊比对从不展开 below。

## 内核缓存点（只读参考 /home/xkq/lean4/src/kernel/type_checker.cpp）

- 正缓存写：`is_def_eq` 包装器 :1247-1252 —— `r = is_def_eq_core(t,s);
  if (r) cache_success(t,s)`。写的是**入口原对**（未 whnf），只在 True。
- 查询：`quick_is_def_eq` :834-836 —— `t == s || succeeded_before(t,s)`
  （cheap structural 先行，正缓存第二），调用点 :1050（is_def_eq_core 内、
  lazy delta 循环之后）。
- 失败缓存写：:1042（lazy_delta_reduction_step 同常量分支，
  `is_eqp(*d_t,*d_s)` 且 regular hints，levels/args 比败才写
  `cache_failure(t_n,s_n)`）——**不是每个失败都写**，对齐这个不对称。
- 失败查询：`failed_before(t_n,s_n)` :1034，先于同常量 args 优化重试。
- whnf memo（P2 范围）：`m_st->m_whnf.find(e)` :753-755。

## 子任务清单（探查先行，五条设计问题的答案进本板后才许动图）

| id | 内容 | 状态 |
|---|---|---|
| M1-01 | 设计探查：(t,s) 对流内定位/比较、_eq_expr/_lvl_eq 可否复用为查询键、attention 查询成本最小 env 实测、P1 发射点选址、软/硬通道两案算账 | pending |
| M1-02 | 判定不变性探针：开关对照 harness，同用例集缓存臂开/关逐条判定相等 | pending |
| M1-03 | P1 实现：TASK_DEFEQ 入口数据驱动正缓存臂（命中已完成同构 (t,s)→直接交付）；失败缓存对齐 :1042 不对称；引行号进注释 | pending |
| M1-04 | d6 归属实验：全量差分 test_brec_drec_iota_vs_lean.py；d6 转绿则摘除 G4_d6（XPASS 会 FAIL 运行）+ 同步卡 014 第 4 问答案 | pending |
| M1-05 | P2 评估：d6 绿且 d4 类步数达标→立缓注记；否则开子任务 | pending |
| M1-06 | 收口：卡 014 Verifier 集全跑（21 套件回归 + scratch dims 增量 + 硬编码扫描）+ VM_SPEC 新节 + KERNEL_COVERAGE + 板子终态 | pending |

## 硬红线（继承卡 014/ADR 017/018 + AGENTS）

- 缓存臂只减步数、不改判定；任何变绿另证无缓存语义下判定不变。
- 零硬编码：缓存对任意 (t,s) 结构成立，禁常量名/数字 cid 进分派分支。
- 不动 c1=POS+1/c2=POS+2 pend 地址算术；不动 decline 级联语义。
- 不为绿灯放宽断言/删用例；ref_vm.py 冻结；step_vm*.{pt,bin,sbin} 发布产物不动。
- 期望结果只许 oracle 现跑（~/.elan/bin/lean v4.33.1）。

## 日志

（节拍条目按时间正序追加，每条 = 一个可验证小步）

### M1-01a 机制勘察（板子建立后第一拍）——流内 (t,s) 定位/比较的机器事实

**DEFEQ 对的流内表示**：DEFEQ 帧 = T_FRAME token（kind 32），
`V0=TASK_DEFEQ(7), V1=t_pos, X=t_env, E2=s_pos, F2=s_env, V2=caller`
（build_vm.py:3648 注释、step_driver.run_defeq:181）。四元组全是 token
位置标量（≤4096 序列帽）。查询键比较可复用 `_eq_expr`
（primitives.py:44，标量等值，3 ReGLU/次）：`deq_same` 臂
（build_vm.py:3652）就是 `_eq_expr(frV1,frE2)·_eq_expr(frX,frF2)` =
 refl 快道 = 内核 `t == s`（:837 前半）。`_lvl_eq` 是 level 树专用
（:3605），与闭包等值无关——**缓存键用不到它**；闭包等值 = pos 相等 +
env 链等值，`_eq_expr` 对位置标量直接可用，env 链等值即 deq_same 的
`_eq_expr(frX,frF2)` 同款（两个 env 根位置相等 = 同一链 = 结构相同，
de Bruijn/Krivine 表示下 env 是共享 DAG，根相等⟹链相等）。

**内核缓存语义核对（4.35 源码 + 4.33.1 行为基准）**：
- 查询在 `quick_is_def_eq`（:834-836）：`t == s || succeeded_before(t,s)`，
  在 is_def_eq_core **入口原对**上（:1173-1174 第一步）；whnf 后对
  归一对再做一次同款（:874）。→ 图侧查询点 = **DEFEQ 帧 dispatch 步**
  （is_defeq_frame ∧ ¬ret_pending），排在 deq_same 之后、其余臂之前，
  命中 = 与 deq_same 同形提交（A=1,B=0,E=1,D=frV2，:3799-3802）。
- 写在包装器 `is_def_eq`（:1247-1252）：core 返回 True 才
  `cache_success(t,s)`（原对）。图侧写点 = **一切 DEFEQ 帧以 True 出栈的
  拍**：①dispatch 步 True 提交臂（E_d=1∧A_d=1∧D_d=frV2）；②pop_task
  拍（is_defeq_frame ∧ ret_pending ∧ SA≥1，:5895-5934——verdict 在 SA，
  帧字段 = 原对）。两处并存，写臂要 OR。
- 失败缓存不对称（卡 014 设计问题 3）：:1034-1042——只在
  lazy_delta_reduction_step 同常量分支（`is_eqp(*d_t,*d_s)` + regular
  hints）levels/args 比败时写 `cache_failure(t_n,s_n)`，查询在
  `failed_before` 先于重试。**图侧这个位置的对应物 = deq_hargs/A17 臂
  （WP7，:3753-3768）+ DE_ATT sink 失败通道（:4214-4240）**：A17 探到
  args 不等 → DE_ATT FALSE → 重发 deq_sw0 继续 unfold。失败缓存 = 在
  DE_ATT FALSE 拍写「该 (t,s) 对 args 已比败」标记，deq_hargs 臂前查
  标记跳过重试。注意内核写的是 (t_n,s_n)（进入该分支的脊对），非原对。

**内容寻址检索的机器约束（关键发现）**：
- `fetch_by_position`（alm_p2.py:50）：精确命中靠 `2q·pos − pos²`，
  仅位置可精确匹配（position_sq 是内建输入维）。`fetch`（alm_graph.py:341）
  的 1D 数据键 score=k(2q−1) 线性、退化为极值——**图内现在没有任何
  数据键精确检索**（全仓 fetch( 零使用，clear_key 零使用）。
- **但有解**：LookUp 的 key 表达式是任意 Expression；
  `reglu(v0, v0) = v0·ReLU(v0) = v0²`（v0≥0）——单个 ReGLU 神经元即可
  在**每个 token 位置**算出该 token V0 的平方（输入维 v0 在 depth-0，
  编译器按 DAG 深度调度，lookup 排在后层即可）。score =
  `2Q·v0_j − v0_j²` 对「V0==Q 的缓存 token」精确 argmax；再用
  `clear_key = 1−[k_j==T_DEFCACHE]`（persist 折叠后 ×BIG 剔除，
  alm_p2:84 多单式陷阱有注释）限定只命中缓存 token；tie_break=latest
  取最新；**取回缓存 token 全四字段后在当前拍用 _eq_expr 逐字段验证**
  ——键碰撞/遮蔽 → 验证失败 → 按 miss 走原路（miss=现行为，判定安全）。
  值域：v0 ≤4096（序列帽）→ v0² ≤16.7M ≈ 2^24，与 position_sq 同一
  fp32 精确边缘（HARD_K=1e4 路由用精确 argmax，HYBRID_ARCH 已解耦）。
- 键只能编码**一个**标量（2D query 的等值通道只有一个）——四元组里
  选哪个当键、遮蔽率多少，**待 d6 trace 实测**（重复对共享字段分布）。
- 备选（不动 attention）：链式缓存 token + 微步回退扫描——**卡在
  head 指针无处存**（STATE 六字段全有主：A/B=focus、C=pend、D=frame、
  E=ret、F=s-pend/litdig 链；append-only 流无固定槽可放寄存器）→ 除非
  新开一个每拍穿线的字段（改动面全机器）否则不可行。**attention-v0 方案
  胜出（单拍查询、零 STATE 侵占、复用既有 raw 发射槽）**。

**写臂发射槽 = raw（已核）**：em_raw 发任意 K + V0,V1,V2,X,E2
（step_driver:100-106，无 F2）→ 缓存 token 用新 kind `T_DEFCACHE`，
V0=t_pos, V1=t_env, V2=s_pos, X=s_env（E2=0）。V0=t_pos 恰是候选键。
pop/dispatch-True 拍现用 raw=0，零冲突（待逐臂核对 em_raw merge 清单）。

**发射位置算术安全性**：raw 在 POS+1、STATE 随后追加——写拍发 1 raw 不
动 D/E/F，指针全是绝对位置，无级联（c1/c2 约定只在发帧臂相关，写臂不发帧）。

### M1-01b 设计裁决（P1 架构定稿草案，trace 数字后补）

**查询臂（单拍、零步成本）**——DEFEQ dispatch 步内做内容检索，不占步数：
- 新 helper `_fetch_by_v0sq(values, q)`（build_vm.py 内联，直接构造
  `LookUp`，imports 补 LookUp + _inv_log_pos_dim）：score =
  `2q·v0_j − v0_j² − BIG·clear_j + α·invlog_j`，其中 `v0² = reglu(v0_,v0_)`
  （单 ReGLU 在每位置算平方，v0≥0 恒成立）；`clear = persist(1 −
  _kind_eq_raw(k_, T_DEFCACHE))`（多单式先折叠再乘 BIG，alm_p2:77-86 的坑）。
  tie_break=latest。
- **无需哨兵 token**：空缓存时全流 clear → argmax 落 position 0 = T_NULL，
  其 V0=n_consts < 任何真 term 位置（term 从 env 区之后起）→ 首字段验证
  必败 → 恒为 miss（确定性，无假命中）。
- 取回值 = 缓存 token 的 (v0,v1,x,e2) = 四元组，当前拍 4× `_eq_expr` 验证
  （碰撞/遮蔽 → miss，判定安全）。`deq_cache = 验证 ∧ ¬deq_same`；
  **一行接入**：`deq_gate = reglu(is_defeq_frame, One − deq_cache)`
  （:3651）——所有 dispatch 臂共用 deq_gate，遮蔽自动互斥，
  deq_fall/sw 落链随之关门。命中提交形 = deq_same 形
  （A=1,B=0,E=1,D=frV2，:3799-3802 同款，加在其后第一位）。
- 内核顺序对照：查询在 is_def_eq_core 入口（:1173-1174 的
  quick_is_def_eq :836，t==s 之后）——图侧 deq_same 之后、其余臂之前 ✓；
  re-dispatch（sw_loop :4150 重发 DEFEQ 帧）天然再过入口查询 = 内核
  :1224-1227 re-dispatch 后再入 core 的缓存读序 ✓。

**写臂（零步成本，raw 槽）**：`T_DEFCACHE`（tokens.py 新 kind 41）。
写门 W = ①dispatch True 直提臂（deq_same、deq_const、deq_sort∧verdict、
deq_cache 命中——命中重发=刷新 latest，对遮蔽良性）∪ ②pop-True 拍
（pop_task ∧ is_defeq_frame ∧ SA≥1，:5895/5934 链——卡对链/软链的终
verdict 一律经此，覆盖 de_att_t/de_prj_t/DE_RFL 的下一拍）。
发射 = raw 槽（em_raw :6155 合式加项；raw 在 is_defeq_frame 与 pop 拍
现为零使用，已核 em_raw_i=INFER dispatch、em_raw_c/r=ST 模式）：
raw_K=T_DEFCACHE, raw_V0=frV1(t_pos), raw_V1=frX, raw_V2=frE2,
raw_X=frF2, raw_E2=0。不动 D/E/F/帧槽，c1/c2 约定零接触（写拍无帧发射）。
- 失败缓存（对齐 :1042 不对称）**缓一步**：P1 先正缓存；失败臂语义 =
  DE_ATT FALSE 拍（:4214-4240，de_att_f）写「同脊 args 比败」标记 +
  deq_hargs 前查跳过（= failed_before :1034）。若 trace 显示 d6 靠
  正缓存即收敛，失败臂按内核合同仍要做（:1042 的写点图侧已存在=
  A17 探败），列为 P1b。

**Q1 答复（流内定位/比较 + 成本）**：(t,s)=帧 (V1,X,E2,F2) 四标量；
比较 = `_eq_expr` 复用成立（env 根位置相等 ⟹ 共享 DAG 链相等，
Krivine 表示，deq_same 已论证此语义）。attention 查询 = **一拍内常数额外
电路（~+6-10 dims、+1 lookup），步数零增**；成本与 env/流长无关（非扫描）。
**Q5 答复（软/硬两案）**：两案算账——共用入口（deq_gate 级）= 内核合同
（is_def_eq 包装器不分调用方，proof-irrel 的 defeq(t_ty,s_ty) 也写缓存）；
分通道 = 需给 DEFEQ 帧加来源旗标（帧字段无空位，E/STATE 侵占）且
d6 的重发对恰在卡对链（软侧），分通道会漏。裁决 = 共用入口。
**Q2 路径**：开关 = build 时环境变量（VM014_CACHE=0 → 不构造臂，
两臂各自成图），对照 harness 逐用例 verdict 相等 + 步数只降不升。

### M1-01c trace p4 判读（d6/d7/d4 @720，guard pid 2539448，rc=0，峰 4074MB，228.5s，原文 `/home/xkq/logs/014/trace_p4.log` + trace_result.json）

d6@720：**49 次 DEFEQ 发射 / 29 次 pop，全部 True（T29/F0）**——卡对链
没有失败对，是一条**真增长的 x 阶梯**：(x,3197,x,3239) x=2139…2176（第一
层），换 env 根 3656/3657→3664/3665→4007/4039→4227/4228→4281/4282，
每层再走 15-20 个**新 x**（新 witness 结构）。**exact-repeat（同四元组
重发且首次已 True 完成）= 仅 4 次**（(2145)@169→@173、(490)@571→@575、
(501)@579→@587、(502)@582→@586），各值 ~1-2 步。**大开销段 = 每层一次
90-130 步的 below 展开比较**（(2154)@204→294=90 步、(513)@506→602=96、
(641)@471→603=132）——是**新结构的 whnf 重推**，不是同对重比。

**结论（卡 014 设计问题 4 的答案 = 实测数据）**：
- **P1 正缓存不足以让 d6 转绿**（预测"重复 (t,s) 对第二次命中→增长环
  断掉"不成立：环里 45/49 是首次出现的新键对）。卡 014 第 4 问按实测
  修正：d6 残环的逐层成本在 **whnf 重展开**（TASK_WHNF 臂，
  K/type_checker.cpp:753-755 的 m_whnf memo 正是内核对此的那一层），
  归 **P2** 射程 → M1-05 按"不达标→给 P2 开子任务"分支执行，
  且子任务带本 trace 证据立项。
- **P1 仍必须落地**（ADR 017：判定一致性组成，非优化）：4 次 exact-repeat
  与 d7/d4 零回归、其余差分套件的重复对（待 M1-04 全量看）；且缓存合同
  不落地，深输入家族的 Timeout=判定分歧面不收窄。
- **键字段裁决**：`shadow_by_field` = **t_pos 键遮蔽 0**，t_env 键遮蔽
  20-21，s_pos/s_env 12-21（d6 同 env 根横比多对共享）。→ **attention
  键 = 缓存 token V0 = t_pos**（单通道等值 + 取回四元组全验证，遮蔽 =
  安全 miss）。
- d4@720：2 发射 2 pop（T2/F0），repeats=0，shadow 全 0——**缓存臂对
  d4 零接触**（步数不变的对照组）。d7@182 绿，2 发射 2 pop（F2）。

M1-01 设计问题五问至此全有答案（Q1 见 M1-01b/单拍 attention；Q2 开关
对照路径见 M1-01b + M1-02 实现；Q3 失败缓存位置 = DE_ATT FALSE 拍，
d6 数据证明失败臂对其无效但仍按合同做 P1b；Q4 上文；Q5 = 共用入口）。

---

## 事故记录 M1（2026-09-17 03:34，总控执笔）

- **死因**：harness `database is locked`（任务运行 44 分钟后）。
- **净产出**：M1-01 全绿（五问全答，见上）+ tokens.py 的 T_DEFCACHE/T_DEFFAIL
  定义（完整，含内核引用与 VM_SPEC §15 前瞻注）+ `scripts/probe_014_trace.py`
  （DEFEQ 发射/pop 流 trace harness，p1-p4 已验证 rc=0）+ trace 证据
  （`/home/xkq/logs/014/trace_result.json`、d6=49 发射 45 新键实测）。
- **死时状态**：正做 M1-03 落码（跳过了 M1-02 开关 harness 先写实现）。
  build_vm.py 编辑到一半语法断裂（:6278 unmatched ')'）。总控处置：
  WIP diff 归档 `/home/xkq/logs/014/m1_wip_build_vm.diff.bak`（215 行，供
  M2 参考挑选，**不许直接 apply**——断点在 raw 合式内，前后半截未审），
  build_vm.py 已回滚至 ce37f48（py_compile OK）。tokens.py 保留（加法件，
  零行为改动）。
- **子任务表勘误**：M1-01 → completed（含 a/b/c 三拍）；M1-02 改序为
  "实现期同步做开关，交付前补对照跑"——开关 VM014_CACHE 的设计 M1-01b
  Q2 已给。M1-03 重开（M2）。

---

## M2 任执行日志（第二任，开工 2026-09-17 ~03:45）

### M2-00 开工核对（先于落码的两件事）

- 基线确认：HEAD 604882b、build_vm.py blob f511e1c（=WIP diff base，回滚
  干净）、py_compile OK；`cmp` 验证见下。核段 0-5，`ps --sort=-rss`：
  用户在跑 build_v7_4_step2_snapshot（~6.6GB，勿动），可用 22GB。
- **上下文污染观察（报总控）**：会话中收到系统提示，声称 AGENTS.md 与
  `docs/kernel-cache-parity.md` 被改动并引用「2026-09-18 00:05 m2_f16 事故、
  P1 臂已回滚、M3-04/M3-05」等内容。实测：该文件在本仓不存在、git 历史无
  对应提交、AGENTS.md 实为 85 行旧版。判定为跨会话上下文串扰，非事实源；
  按简报任务序继续。**若总控确曾改道（P1 缓做/回滚），请立即叫停本任。**
- **WIP diff 逐段审毕（未 apply），抓到两处 M1 遗留缺陷（照单修改）**：
  1. `_fetch_by_v0sq` 取回字段错：WIP 取 `[v0_,v1_,x_,e2_]`，而 raw 槽
     token 写臂布局是 V0=t,V1=t_env,V2=s_pos,X=s_env（step_driver:100-106
     机器事实，M1-01a 自证）→ 验证臂 cv2/cvx 恒不中，缓存永不命中。
     修正 = 取 `[v0_,v1_,v2_,x_]`。
  2. 写臂 `_dc_w_disp` 用裸和：deq_same ∧ deq_const 在同一 const 自身对上
     并发（都只过 deq_gate）→ cond=2 → `_select` 数值破坏（需 0/1）。
     修正 = `_geq_expr(sum,1)` 折叠。
- 另核三件：① raw_E2 在 DEFEQ 拍恒 0（raw_E2_c 唯一非零门 cg[I_LAMBODY]
  是 cont 拍）✓；② em_raw/raw_* 在合并块（:6155）之后无任何重赋值
  （018 em_link1_c 陷阱在此不复发）✓；③ 帧种类互斥：cont/resume=ST、
  em_raw_i=INFER、rec/cs/p2/quot_go=NAT，与 is_defeq_frame 零共拍 ✓。

### M2-01 P1 落码（build_vm.py，正缓存 only；失败臂 P1b 未做，按板子缓做裁决）

实现（全部改动只在此文件）：
- 开关 `VM014_CACHE`（import 期读 env，=0 全臂不构造）；新导入
  `_inv_log_pos_dim/LookUp/LATEST_ALPHA/BIG` + `T_DEFCACHE`。
- helper `_fetch_by_v0sq(kind)`（`_lvl_chain_eq` 后）：score =
  2·frV1·v0 − v0² − BIG·clear(1−[k==kind 持久化折叠]) + 0.3·invlog，
  tie_break=latest，取回 (v0,v1,v2,x) 四元组。
- 查询：`defeq_cache = is_defeq_frame ∧ 4×_eq_expr 全中`；
  `deq_gate = reglu(is_defeq_frame, 1−defeq_cache)`（开关 off 时逐字回基线
  形 `deq_gate = is_defeq_frame`）。
- 命中提交形（deq_same 后第一位）：A=1,B=0,E=1,D=frV2。
- 写臂（raw 槽首位 `_select`）：`_dc_w = dispatch-True 直提 ∪ pop-True`：
  ①(deq_same+deq_const+defeq_cache+deq_sort∧verdict)_geq·¬ret_pending
  ②pop_task·is_defeq_frame·SA≥1；发 T_DEFCACHE(t,t_env,s,s_env)。
  `_deq_sort_verdict` 提升为具名（写臂只认 True）。
- 哨兵论证修正（记入设计事实）：空缓存时全部 cleared 分数在 fp32 里
  同落 −BIG（ulp(1e20)≫2^25）→ argmax 取 position 0（T_NULL，
  V0=n_consts<任何 term 位）→ 首字段验证必败 = 确定性 miss。

**编译增量（scratch 前缀自设，未碰 009 件）**：
- ON `model/step_vm_m2_scratch.sbin`：dims 25,982（+52）/ lookups 2,899
  （+1）/ nnz 192,657（+252）/ 114L / d_model 4,822（+10）。
- OFF `model/step_vm_m2_off.sbin`：dims 25,930 / 2,898 / 192,405 / 114L，
  **`cmp` 与 `model/step_vm_009_scratch.sbin` 逐字节一致**（对照臂=基线本身）。
- 日志 `/home/xkq/logs/014/m2_compile_{on,off}.log`。

**新机器事实（ReGLU 钳位 × v0² 键）**：卡 008 的 `REGLU_CLAMP=1e6` 作用于
编译通道（runner/weights/vm.cpp）的**全部** FFN ReGLU 输出，`_v0sq` 是其
一 → 位置 >1000 的键平方在编译通道被压平：命中可能退化为 miss（verify
兜底，判定安全），Python 符号求值器无钳位、命中正常。引擎 34 例合法位置
读数 ≤1003（ADR 013），贴界；差分/trace 走 Python 求值器不受影响。
入 VM_SPEC §15 已知边界。

下一步：M2-02 对照 harness（scripts/probe_014_invariance.py，两图同程
verdict 相等 + 步数只降不升；quick 子集先行）。

### M2-02 判定不变性 harness（scripts/probe_014_invariance.py 新建，M1 欠账补上）

两图同程（模块开关 build_vm.VM014_CACHE 在两次 build_step_graph 间 patch，
reset_graph 支持多图；off 图先跑，off 步数即基线）；oracle 全部现跑
（run_lean KDEFEQ/KDECLMSG + lean_ref.run_oracle_mixed），逐用例
verdict 字符串相等 + steps(on)≤steps(off)。

**quick 集（defeq A 16 例 legacy + brec C/lst 4 例）实跑原文**：
`/home/xkq/logs/014/m2_inv_quick.log` guard rc=0，peak 3315MB，775s：
20/20 `OK`，全 +0（该集无重复对，缓存恒 miss）；lst 例
`defcache_toks=2` → 写臂确发 T_DEFCACHE（off 恒 0）。off 步数
118/158/460/458 与 F10 记录逐位吻合（off 臂=基线复现 ✓）。

full 集（+Am/G 臂 + nat B 组含 d6/d4/d1_shadow）后台跑：guard pid
2618435/子 2618439，日志 `/home/xkq/logs/014/m2_inv_full.log`。

### M2-02 full 表实跑（guard pid 2618435，rc=0，peak 5507MB，2160s，原文
`/home/xkq/logs/014/m2_inv_full.log`）

55 用例（defeq_branches A 16 legacy + A 16 meta + G 12 check + brec nat 7 +
lst 4），开关两版同程逐条判定相等、**步数 delta 全 +0**、oracle 通道全对。
off 臂步数与 009 记录逐位吻合（134/132/171/483/648/timeout720/182;
118/158/460/458）。写臂观察：True 完成例 `defcache_toks=2`、False 例 0
（`if (r)` 合同活体证据）。**未观测到命中**（全表 +0）——该用例集的重复对
只在 d6 环内（M1-01c 的 4 次 exact-repeat），命中活性待 trace 复跑判读，
另立专测（卡 verifier「专造重复对用例」）。

### M2-03 首个实跑抓出并修复：dispatch-True 写拍 × c1/c2 地址算术 = d6 活锁

trace 复跑（ON 首版）：d6 事件流与 OFF 前缀逐步一致到 s468，随后
**period-1 活锁**（A=1,B=0,E=0,D=ST(F2=19=D_BIND2) 恒不动）。诊断件
`scripts/probe_014_diag.py`（ON/OFF 同窗对拍，原文
`/home/xkq/logs/014/m2_diag_{on,off}.log`）钉死机制：

- 基线机器上 deq_same 与 kind 臂**可同拍共发**（d6 实例：同闭包
  (680,0,680,0) 且 680 是 LAM → deq_same=1 ∧ bind_k=1，bind 的 D=c2 覆盖
  deq_same 的 D=frV2 与 E=1，机器把 lam/lam 快判让位给体比较链，OFF
  s468→471 正常走通：fr1 ST@POS+1、fr2 DEFEQ@POS+2、D=c2 指体对帧）。
- 我的 raw 写 token 插 POS+1 → 该拍后续 token 全体 +1 平移，D=c2 落进
  ST(D_BIND2) 帧（E=0 不可 dispatch、非 cont、非 pop）→ 活锁。
  **c1/c2 约定对「写拍 + 发帧拍共现」零防御——这正是 018 血的教训的
  同款陷阱**（简报预警的 em_raw 合式陷阱实为发射 stride 陷阱）。
- 修复（M2 裁决）：**写臂加 busy 门**——dispatch-True 写只在该拍
  不发任何帧时执行（_dc_busy = 全部发帧臂之和 deq_lit/lit_str_eq/bvar/
  mdata/succ/refl/hargs/tpc/proj_same/bind_k/xpi/sw0）。共发拍（快判让位
  给体链）放弃写入：判定无损（该对终由 pop-True 拍或重发拍写入）；
  pop-True 拍与 hit-refresh 拍恒纯，不受影响。
- 修复后增量：dims 25,985（基线 +55）/ lookups 2,899（+1）/ nnz 192,691
  （+286），114L；ON trace 复跑后台 pid 2704819/2704820，日志
  `m2_trace_on_d6b.log`。（M1 OFF trace 原始件已备份
  `trace_result_m1_off.json`，防被 ON 跑覆盖。）

### M2-03 trace 复跑（busy-gate 修复后，ON 图）+ 命中活性专测上线

`m2_trace_on_d6b.log`（guard rc=0，168s，peak 4020MB，原文要点）：
`G4_d6: timeout720 steps=720 launches=49 pops=29(T29/F0)
exact_repeats=4 distinct_true=29 shadow={'t_pos':0,...}` —— 与 OFF 基线
M1 trace 事件流逐拍同形（shadow t_pos=0 即 M1 结论），活锁消除 ✓，
d6 仍 timeout = 「P1 救不了 d6、d6 绿是 P2 验收」的板书预期一致。
（重复对是「被旁路的死推送帧」，从不二次 dispatch → P1 恒 miss。）

专测 `tests/test_defeq_cache_vs_lean.py`（卡 verifier「专造重复对」臂）：
同流二连 run_defeq，run2 命中 root T_DEFCACHE。后台 guard pid
2710489，日志 `/home/xkq/logs/014/m2_cache_test.log`。首 case 即出活性：
`j1 legacy: on run1=True/21 run2=True/1 defcache=3 off run2=True/21`
—— 命中 1 步 vs 基线 21 步，写 3 条。判据：verdict 逐例=live oracle、
True 例 run2 严格少于 off-run2、False 重跑不翻、d6 双图同 timeout（
XPASS 即报摘除 G4_d6 指引）。

### M2-03a 守卫实录 + 专测重构（guard 生效，非图缺陷）

首跑（pid 2710489，日志 `m2_cache_test.log`，peak 顶满 6144 → rc=-9
主动杀）：small 臂 32/32 全 OK 后才在 d6 臂被杀——两版大图 720 步
**共存**才是内存主犯（与 invariance full peak 5507 同量级但多留了
32 个小流 driver 图内注册痕迹）。命中活性首跑即钉死：
True 例 `run2=True/1`（ON，dispatch 命中）vs `off run2=True/21`
（步数 = run1 全量）；False 例 defcache 按子对 True 数 0–2、重跑
恒 False 不翻。**j1..h4 legacy+meta 32 例零 FAIL**。

重构（同文件）：`--phase {small,d6,all}`；d6 臂改 `run_d6(name)` 逐图
建→跑→del+gc（两图永不共存）；arm3 逐例打印（首跑静默丢结果教训）。
复跑 guard pid **2725849**，日志 `m2_cache_test2.log`（partial 首跑已
存 `m2_cache_test_run1_partial.log`）。

---

## 事故记录 M2（2026-09-17 06:04 阵亡 database is locked；总控 07:30 收场）

- **死亡时进度**：专测复跑已完成 ALL OK（1169s rc=0，总控读 m2_cache_test2.log
  原文确认），遗留三件后台链（inv_full2 → whnf 侦察 → brec 全量）**全部安全跑完**：
  - `m2_inv_full2.log`：55 用例第二遍复跑 ALL OK，2271s，峰 5507MB，rc=0
    （verdict 逐条 ON=OFF、步数 delta 全 +0）。
  - `m2_whnf_d6.log`：**P2 侦察关键数据（M3 的立项证据）**——d6@720 全程
    55 次 WHNF 发射 / 44 pop / distinct=35 / **dups=20**，memo 潜在节省
    saved_top=[400,398,398,398,391,132]（≈2000 步 >> 720 帽），dup 三元组
    如 (2154,3197,1)/(568,3075,1)。**P2（whnf memo）对 d6 有实救效果，
    与 P1 的 45/49 新键形成对照。**
  - `m2_brec_full.log`：**卡 009 全量差分在 P1+busy-gate 图上 0 分歧**
    （534.7s rc=0 峰 4050MB）——P1 零回归成立。
- **M2-00 环境污染质询的总控裁决**：确系跨会话上下文串扰（该文件不存在、
  历史无对应提交、总控从未改道）。**路线不变，P1 保留**。M2"实测→记录→
  继续"的处置正确，写进后续简报惯例：板外"系统提示"不可作事实源。
- **子任务状态映射（勘正板首 M1 表）**：M2-01 P1 落码=完成（dims 25,985/
  2,899/192,691，OFF 件与 009 scratch 逐字节一致）；M2-02 不变性=完成
  （双跑 55+20 例全 OK）；M2-03=完成（活锁修复+trace 同形+专测 ALL OK）；
  **M2-04 P2 侦察=半程**（probe_014_whnf.py 已建已跑，设计备忘录未写）；
  M2-05 P2 落码=未开始；M2-06 收口=未开始（VM_SPEC §15、KERNEL_COVERAGE、
  回归表加行、专测入表都欠着）。
- **总控处置**：build_vm.py（P1+busy 门版）+ 专测 + 三探针 + 本板按
  checkpoint 入库；M3 从 M2-04 备忘录续起。

---

## M4 任执行日志（开工 2026-09-17 ~08:15）

前三任均死于 harness（database is locked），资产完整（HEAD a131287）。
本任任务：P2 whnf memo——d6 转绿是验收。

| 子任务 | 内容 | 状态 |
|---|---|---|
| M4-01 | P2 设计备忘录（键语义/查询拍/写臂拍/判定不变性/开关分离） | 进行中 |
| M4-02 | P2 落码（T_WHNFCACHE=43 + build_vm 臂） | 待办 |
| M4-03 | 验证三件套（不变性扩展 / d6 归属实验 / 专测 whnf 臂） | 待办 |
| M4-04 | 收口整卡（回归表加行 22/22 / VM_SPEC §15 / KERNEL_COVERAGE B14 / 板终态） | 待办 |

### M4-01 P2 设计备忘录（whnf memo 架构定稿，机器事实先行）

**内核合同（只读参考 /home/xkq/lean4/src/kernel/type_checker.cpp）**：
`whnf(e)` :736-775 —— :738-752 简单叶子（BVar/Sort/MVar/Pi/Lit）直接返回
不进缓存（"Do not cache easy cases"）；查询 :755-757
`m_whnf.find(e)` 命中即返；**三处写回全在 while 循环算完之后**：:763
（reduce_native）、:766（reduce_nat）、:772（stuck 结果 r）。另有
whnf_core 二级 memo（:491-493 查询、:548 写，且仅 !cheap_rec&&!cheap_proj）
——我们的 TASK_WHNF 帧建模的是外层 whnf() 循环，图侧对齐对象 = m_whnf。
"完成才可查"由写点在后天然保证。

**键与值的图侧语义（三元组可表达性实测反推）**：请求 = (focus pos,
env 根, soft flag) = WHNF 帧 (frV1, frX, frE2)（fr2_V1/V2/X/E2 发射形，
build_vm.py:3093/4209-4213/5093；与 whnf_result.json dup 三元组同形——
探针 launch triple=(v1,x,e2)）。值 = 出口拍交付的闭包对 (rpos, renv)
（whnf_deliver: A_done/SB；pop-under-whnf: SA/SB）。T_WHNFCACHE=43 布局
（raw 槽恰 5 字段全用）：V0=pos（注意力键）, V1=env, V2=flag,
X=rpos, E2=renv。flag 必入键：soft 失败交付输入原闭包、hard 失败 reject，
同 (pos,env) 两通道结果可不同。内核无 flag——soft 是我们图上 _soft_whnf
通道的既有旗标（:3009-3010 注释），键含旗标 = 对两通道的保守分离，只会
少命中不会错命中。

**查询拍（单拍，零步成本）**：同 P1 机制，`_fetch_by_v0sq` 的 5 字段变体
（score=2·frV1·v0−v0²−BIG·clear(1−[k==43])+α·invlog，latest；键通道与
P1 共用 _v0sq 单 ReGLU）。命中门
`whnf_cache = is_whnf_frame ∧ ¬ret_pending ∧ (SA==frV1) ∧ (SB==frX) ∧
eq(wv0,frV1) ∧ eq(wv1,frX) ∧ eq(wv2,frE2) ∧ (1−reject)`。
两个增量设计（相对 P1）：
1. **入口形限** (SA==frV1 ∧ SB==frX)：只在"帧刚拿到输入"的拍命中 =
   内核 whnf(e) 在调用点查 memo（mid-loop 不查）。防运行中拍（focus 已
   归约/返回 pending）被旁路，也让 C/F 寄存器与发射拍一致（见 R1）。
   环内重发射（探针 20 dup 全是 fresh launch）不受影响。
2. **¬reject**：命中不得吞拒绝（判定面）。
命中提交 = whnf_deliver 出口形：A=wv_X, B=wv_E2, C=SC, D=frV2, E=1,
F=SF（六个 _select 加在 A2..F2 链顶，最高优先）。发射臂不遮蔽（whnf 执行
臂是共享主机器，不像 DEFEQ 有私有 deq_gate）——命中拍的 co-fire 发射物
全部死垃圾：出口提交无 c1/c2 相对指针、指针全绝对、kind 过滤使 attention
扫不到、链根不被引用。

**写臂拍（价值门 = 自带 busy 门）**：
`_wc_w = is_whnf_frame ∧ _eq_expr(D2, frV2) ∧ ¬whnf_cache`。
D2=最终提交值：谓词恰=「本拍把结果交付给 caller」= whnf_deliver ∪
pop-under-whnf ∪（soft 失败出口形若存在同被捕获）。**M2-03 陷阱免疫证明**：
任何 co-fire 使别的臂提交（D2≠frV2）→ 该拍不写——价值门天然就是 busy 门，
无需 12 臂手抄清单；真出口拍的提交只用绝对/寄存器指针（frV2/SA/SB/SC/SE/SF/
A_done），raw@POS+1 平移 co-fire 死帧无害（死帧内部 c 引用错位仅伤死帧，
无活指针可达）。¬whnf_cache=不做命中刷新：同键必同值（whnf 确定性，流
append-only、token 不可变、env 链共享 DAG 根相等⟹链相等，deq_same 同论证），
重放无信息增益，免掉「命中拍+写拍」双身份。发射字段：raw_K=43,
raw_V0=frV1, raw_V1=frX, raw_V2=frE2, raw_X=A2, raw_E2=B2（出口拍的
A2/B2 即交付值）。与 P1 写臂天然互斥（is_whnf_frame ⊥ is_defeq_frame），
与 raw 其余源互斥（cont/resume=ST、em_raw_i=INFER、rec/cs/p2=NAT、
quot_go 提交≠出口形 D2）。

**判定不变性论证**：①条目=真实完成计算的忠实记录（写门=出口拍，值=该拍
提交对）；②replay=重放（入口拍交付同值+同出口形），与重跑的交付终态在
(A,B,D,E) 全等，省掉的中间拍不携带任何只有它们能产生的后续信息（内核
memo 同理：whnf 是 (e) 的纯函数）；③自引用不可能：运行中帧无己键条目
（写在出口之后、流序保证读只见历史），环内先后序=内核 while+insert-after；
④缓存只旁路「本帧」不旁路他人指针（绝对指针+kind 过滤）。合同=ADR 017
红线：步数只降、判定逐条等——由 M4-03 双跑实测背书。
d6 收益：20 dup 中重跑成本大头 (2154/2157,·,1) 首轮 42-120 步、
(39x,0,0) 族×5、(513/641,40xx,1) 各 ~10-130 步，命中=1 拍。

**开关分离**：`VM014_WMEMO`（import 期 env，独立于 VM014_CACHE）。
三态：P1+P2（默认）/ VM014_WMEMO=0 → 图与 a131287 P1 件逐字节等 /
VM014_CACHE=0 VM014_WMEMO=0 → 与 009 scratch 逐字节等。

**已识别风险（验证计划对应）**：
- R1 C/F 奇偶：命中拍 C=SC@entry vs 真跑出口 C=SC@exit（spine 拍会增长）。
  d6 环通道实测无害：D_SW2/de_prj_f/de_att_f 发射方置 C=0/F=0（:4216-4217/
  4278-4279），D_SW3 消费方续读帧字段并重置 C/F（:4246-4247），pop 透传的
  C 无人读。非 soft 通道由 M4-03① 全量 invariance + ② brec 兜底；若翻车，
  备选收紧 = 写门 ∧ SC==0 ∧ 命中门 ∧ SC==0（干净链才缓存——环恰此形）。
- R2 ReGLU 钳位 pos>1000：同 P1，编译通道键分压平→引擎退化 miss（安全），
  Python 求值器无钳位。
- R3 键遮蔽：t_pos 键 P1 实测遮蔽 0；误遮蔽=verify 败=miss，判定安全。

### M4-02 落码进度节拍（~08:55）

- tokens.py：T_WHNFCACHE=43（注引 :753-757/:763/:766/:772，布局 V0=key,V1=env,
  V2=flag,X=rpos,E2=renv）。
- build_vm.py 五处（全在 VM014_WMEMO 门下，OFF 态零表达式）：查询 fetch
  （_fetch_by_v0sq 扩 nfields=5，_v0sq 条件放宽为 CACHE∨WMEMO）；whnf_cache0
  （is_whnf ∧ ¬ret_pending ∧ 入口形 SA==frV1∧SB==frX ∧ 3 字段验证）；命中提交
  （A2..F2 六路 _select 链顶 + reject 折叠 ¬geq(rej_sum,1) 防吞拒绝 + halt 同防）；
  写臂 _wc_w = is_whnf ∧ _eq_expr(D2,frV2) ∧ ¬hit（价值门=自带 busy 门，M2-03
  免疫论证见备忘录）；raw 槽 _select 外层包（X/E2 取提交后 A2/B2=交付值，
  出口拍无 c1/c2 活引用，co-fire 发射物全死垃圾安全）。
- 冒烟：三态 dims 26048/25985/25930、lookups 2900/2899/2898（P1-only 与 base
  与记录逐位吻合）。P2 增量 +63 dims/+1 lookup。
- 三态编译链后台 pid 3451118，日志 /home/xkq/logs/014/m4_compile_{on,p1,base}.log
  + m4_chain.log（rc 行）。对拍计划：m4_p1 vs step_vm_m2_scratch.sbin 逐字节等、
  m4_base vs step_vm_009_scratch.sbin 逐字节等。
- 操作事故记录（自查）：误用 `compile_vm.py --help`——该脚本把未知 flag 当
  非 --sparse 处理，默认输出 model/step_vm.pt（发布路径）。head 管道 SIGPIPE
  令其在写盘前终止；实测无文件落地、git 干净、无残留进程。教训：该脚本
  无 argparse 校验，调用必须显式 `--sparse <prefix>`，禁止探测其 help。

### M4-02d d6 首跑翻车→诊断→机制修正（~14:40）

- **首跑（无 clean-chain 门）**：d6 ON=timeout720 且轨迹早期漂移（env 根
  3135→3137 平移=写 token 副作用，良性；但 dup@66/68 未吸收、环不收敛）。
  诊断（launch/pop 按帧位置配对计时）钉死：**mid-args-walk 拍
  （I_ARG/ensure_pi 型发射 pop 回 whnf 帧时 SA==frV1∧SB==frX 复成立但
  C≠0），命中把「别人增长中的链」当交付态重放 → 交付形被污染**。
- **修正**：命中门加 **SC==0 ∧ SF==0**（launch 态干净链才准命中；D_SW2/
  de_prj_f/de_att_f 发射形恰 C=0/F=0，d6 射程不损）。写门未加此约束：
  条目记录「干净入→(链可增长)出」的终值 (A,B,D,E)，C/F 奇偶风险见备忘录
  R1，由 M4-03① 全量 55 例在环裁决。
- **修后诊断（whnf_result_m4_diag.json，m4_whnf_d6_diag.log 原文）**：
  ON@720 timeout 但 memo 已活：**memo_writes=42、dup_hits_1step=11**
  （(568,3075,1)@(66/68)、(393,0,0)@(105/499)、(304/303,0,0)、
  (631,0,0)@(398)、(392/391,0,0)@(501/503)、(731,0,0)@(627) 全 1 步重放；
  (390,0,0)@505 dur=8）。未吸收 dup（@32/63/258/262/557/558 dur=None）
  = 非干净链发射或 walk-bypass 出口（v1 射程外，与探针 pop 口径一致）。
  环成本主体=每圈**新位置 below 首推**（与 P1 的 45/49 新键同构：位置键
  memo 对「结构重复、位置全新」的环天然无力）。
- **归属实验 cap=1500（链 pid 3455836，m4_d6_{p1,on}_1500.log）**：
  **P1-only d6 @1500 = halt1 steps=1070（verdict=True，与内核一致！）**
  —— d6 不是无界增长环，是 1070 步收敛、720 帽差 350。M2 的
  「saved_top≈2000」是 relaunch-减-first-done 上界幻象（重跑成本实测
  2-42 步/dup）。d6 绿（≤720）需 memo 省 ≥350 步——ON@1500 收敛点见下拍。
- 专测扩展中：main_whnf 活性臂（同流双发 root WHNF，run1≥4 步 run2≤3 步
  结果相等 + P1-only 对照恒重跑）；main_d6 三态臂（P1-only vs P1+P2+
  live oracle+registry 一致 + memo 死臂哨兵）。probe_014_whnf.py 加
  memo_writes/dup_hits_1step/launch_durations 统计与 --out（不覆盖 M2 证据）。

---

## 事故记录 M4（约 15:45 客户端闪退，总控 15:5x 验尸收场）

- **在跑件被杀**：`m4_inv_p2.log`（P2 55 例不变性对照）89 行处中断（Am 组
  已跑条目步数与 M2 基线逐位吻合，无翻车迹象，但**未跑完=不作数**）。
  chain3（pid 3482773）已死。
- **M4 净产出（总控验尸确认）**：P2 whnf memo 全码入库（三态编译
  v2 15:18 rc=0：26,048/2,900/… vs 25,985/2,899 vs 25,930/2,898）；
  d6 性质定谳（**帽 1500 下 P1-only halt1@1070、P1+P2 halt1@1012，
  verdict=True 与内核一致——d6 不是无界环，是合法慢**）；探针升级
  （memo_writes/dup_hits_1step/--out 防覆盖）；M2"saved_top≈2000"被 M4
  自己纠正为 relaunch-first_done 上界幻象（真实重放成本 2-42 步）。
  命中门修正（SC==0∧SF==0 干净链，首跑 mid-args-walk 污染事故→诊断→修）。
  文档推进：VM_SPEC §18 整节成文、专测三态臂扩展、回归表 +5 行。
  板外操作事故（--help 触发发布路径）自查合格：无文件落地、无残留。
- **总控终局裁决（用户授权"项目经理说了算"，d4 抬帽先例同款证据标准）**：
  1. **GRAPH_MAX_STEPS 720→1100**。依据：d6 收敛点 1012（P2 在码后）、
     判定 True 与内核一致；步帽是 Python 求值器的墙钟产物、非语义量
     （d4 648→720 先例、F8-02 线性表论证）；验收判据=verdict 一致，
     不含步数预算。d6 转绿走 XPASS 规程摘除 G4_d6（registry 设计如此）。
  2. **P2 memo 保留**，理由不是 d6（它只省 58 步），是内核 m_whnf 合同的
     语义补齐 + 全量不变性零回归（待 M5 补完跑）+ 活性实证（17 次 1 步重放）。
  3. **ADR 018 更正追记**：G4_d6 定性由"不收敛环+缓存层出路"改为"合法慢+
     帽预算"，memo 合同独立成立；卡 009/014 结案文案随之修。
- **M4 未竟（M5 任务序见简报）**：P2 不变性对照补完跑 → 帽 1100 落码 +
  d6 XPASS 摘条目 + brec/专测重钉 → 全量回归 22 套件 + 引擎对拍 +
  §18/tokens 交叉引用勘对（tokens.py 注引 §15 是否已同步改 §18——M5 核对）
  + KERNEL_COVERAGE B14 更新 + ADR018 追记 + 卡面终态。

---

## M5 任执行日志（收尾，开工 2026-09-17 ~15:58）

第四任 M4 死于客户端闪退（P2 不变性对照跑到一半，与项目无关）。本任=收尾
验收任，无设计工作，按总控终局裁决（板子 M4 事故记录三条）执行终局清单。

### 机器姿态（开工快照）

- `ps --sort=-rss`（15:58）：无大 Python 任务在跑，最大户 = ZCode/brave
  桌面进程（≤360MB）。用户 GPU 训练当前未见。核段 0-5。
- HEAD 应为 a3de0a5（P1+P2 全码已入库）。scratch =
  `model/step_vm_m4_scratch*`，不覆盖发布件与 009/m2 件。

### 终局清单

| id | 内容 | 状态 |
|---|---|---|
| M5-00 | 必读材料核对（板/卡/ADR017-018/VM_SPEC §18/两测试现场） | 进行中 |
| M5-01 | P2 不变性对照补完跑（55 例全表 verdict ON=OFF + 步数只降不升） | 待办 |
| M5-02 | 帽 720→1100 落码 + d6 转绿 + 摘 G4_d6 + brec 全量重跑 + 专测三态臂完整跑 | 待办 |
| M5-03 | 引擎通道 scratch 重编译对拍 + verify_engine_vs_refvm 34/34 + §18.2 钳位核对 | 待办 |
| M5-04 | 全量回归 22 套件（timeout 富余核对） | 待办 |
| M5-05 | 硬编码扫描（缓存两臂尤其干净） | 待办 |
| M5-06 | 文档定稿（§15/§18 交叉引用、KERNEL_COVERAGE B14、ADR018 追记、卡 014/009、ARCHITECTURE、VM_SPEC §18 定稿） | 待办 |
| M5-07 | 板子终态条目（verifier 原文粘贴 + 勘正 + 五道门自查） | 待办 |

### 节拍日志

### M5-00 开工核对（16:0x）

- HEAD=a3de0a5 确认；工作区除本板外无改动（git status 干净）。
- 现场数字勘正：简报「P2 26,048/2,900」为 M4-02 冒烟旧值（clean-chain
  命中门前）。v2 重编译日志 `m4_compile_on_v2.log:1` = **26,056 dims /
  2,900 lookups / nnz 193,062 / 120L**，与 ARCHITECTURE(26,056) 与
  VM_SPEC §18 一致；P1 件 25,985/2,899/192,691（m4_compile_p1_v2 与
  M2 记录逐位吻合）。总控事故记录里 26,048 一处为旧值（不影响裁决）。
- ARCHITECTURE L90 与 VM_SPEC §18 引用的「010-M M4-02e」三态逐字节对拍
  条目**不在板上**（M4 死于跑前）——M5-03 重做该对拍并以 M5 条目落证。
- 证据链核对：d6@1500 P1+P2 `halt1 steps=1012`（m4_d6_on_1500.log，峰
  4686MB）、P1-only `halt1 steps=1070`（m4_d6_p1_1500.log，峰 4737MB）；
  whnf_result_m4_on_1500.json：launches=82 pops=60 memo_writes=54
  dup_hits_1step=17。帽 1100 下双臂均在界内收敛。
- m4_inv_p2.log 死点=89 行（on 臂 Am 组 h3 后），off 臂（P1-only）55 例
  已过、无翻车迹象；M5-01 按规程整轮补完跑（不作废续跑，从头全表）。
- 回归表核对：brec 行 1200s/5000MB——d6 段现多跑 ~292 步（1012 vs
  720-timeout），M2 brec 全量 534.7s → 预估 ~700-750s，1200s 富余；
  5000MB 帽对实测峰 4737（单 d6 图）仅 5% 余量，M5-04 前行内升至 6000。
  defeq_cache 行 1800s：M2 版 1169s@720，d6 双臂 +~350s → 预估 ~1550s，
  偏紧，M5-02c 实测后再定（超则行内加）。

### M5-02a 帽 720→1100 落码（16:1x）

- `tests/test_brec_drec_iota_vs_lean.py:GRAPH_MAX_STEPS=1100`，注释引
  005 F8-02 线性表先例 + M4 帽 1500 收敛实测（whnf_result_m4_on_1500.json
  halt@1012 verdict=True=内核）。`test_defeq_cache_vs_lean.py` 经
  `brec.GRAPH_MAX_STEPS` 导入同源（run_d6 注释同步；docstring 历史句改
  "old 720 cap"）。两文件 py_compile OK。G4_d6 条目**暂留**——先跑
  XPASS 证明（registry 设计：d6 绿而条目在=XPASS FAIL，即转绿实证），
  证明拿到后再摘条目重跑得「0 分歧 0 xfail」终态原文。
- 跑1（XPASS 证明）已起：guard pid 3510018/子 3510019，日志
  `/home/xkq/logs/014/m5_brec_xpproof.log`，帽 6144。

### M5-02a 结果 XPASS 证明（帽 1100，G4_d6 在 registry，原文
`/home/xkq/logs/014/m5_brec_xpproof.log`）

```
  [PASS] D G3_d1_shadow: d1=?=d5r  oracle=True  graph=True
  [PASS] D G2_d3: d3=?=e3  oracle=True  graph=True
  [PASS] D G2_d4: d4=?=e4  oracle=True  graph=True
  [XPASS] D G4_d6: d6l=?=d6r  oracle=True  graph=True
  [PASS] D G4_d7: d6l=?=d7r  oracle=False  graph=False
...
  [NOTE] [B nat G4_d6] XPASS: known-gap entry must be removed (graph now agrees with lean)

=== brecOn/drecOn faithful iota vs lean: FAIL (1 divergences) 471s ===
[mem-guard] wall 470.9s peak RSS 4693MB rc=1
```

d6 转绿 = registry 设计的 XPASS 实证（FAIL 即转绿信号，非放宽）。全程唯一
失败行即摘条目指令，其余 B/C 11 例全 PASS。耗时 471s（帽 1100 下 d6 收敛
1012 步反而**快于**旧 720-timeout 跑 534.7s），回归行 1200s 帽 2.5x 富余；
峰 4693MB→回归行 RSS 帽 5000→6000（M5-04 前落）。

### M5-02b 摘除 G4_d6 + 全量重跑（进行中）

- KNOWN_GAPS 的 G4_d6 条目按 XPASS 规程摘除（文件内注释记录摘除依据：
  帽 1500 实测收敛 1012/1070=True + XPASS 证明日志；registry 与双向防
  漂移机制保留、字典空壳）。docstring 历史账面段同步更正（gap #2b/#3
  定性）；NAT_CASES 行注更新。py_compile OK。
- 跑2（终态证据）已起：guard pid 3511137/子 3511138，日志
  `/home/xkq/logs/014/m5_brec_final.log`，预期 0 分歧 0 xfail rc=0。

### M5-02b 结果 终态原文（G4_d6 已摘，帽 1100，`/home/xkq/logs/014/m5_brec_final.log`）

```
A  export-boundary normalizer (route ii) invariants
   OK (no redex HAdd left; P2.casesOn toy order + 1 level)
B nat  faithful brecOn DEFEQ vs oracle (graph max_steps=1100)
  [PASS] D G3_d1_3: d1=?=e1  oracle=True  graph=True
  [PASS] D G3_d1_4: d2f=?=ef  oracle=False  graph=False
  [PASS] D G3_d1_shadow: d1=?=d5r  oracle=True  graph=True
  [PASS] D G2_d3: d3=?=e3  oracle=True  graph=True
  [PASS] D G2_d4: d4=?=e4  oracle=True  graph=True
  [PASS] D G4_d6: d6l=?=d6r  oracle=True  graph=True
  [PASS] D G4_d7: d6l=?=d7r  oracle=False  graph=False
C lst  faithful brecOn DEFEQ vs oracle (graph max_steps=1100)
  [PASS] D G5_eL1: eL1=?=eL1R  oracle=True  graph=True
  [PASS] D G5_eL2: eL2=?=eLR  oracle=True  graph=True
  [PASS] D G5_eL3: eL3=?=eLR  oracle=True  graph=True
  [PASS] D G5_eL3_neg: eL3=?=eLF  oracle=False  graph=False

=== brecOn/drecOn faithful iota vs lean: OK (0 divergences) 468s ===
[mem-guard] wall 468.8s peak RSS 4694MB rc=0
```

12/12 PASS、0 分歧、0 xfail。brec 行回归参数终态：timeout 1200s 富余
2.5x；RSS 帽 5000→6000（峰 4694+oracle 子进程）。

### M5-01 补完跑启动（16:2x）

`probe_014_invariance.py --layer p2`（P1-only=off vs P1+P2=on，帽
1100 经 brec.GRAPH_MAX_STEPS 生效；本次含 d6 双臂 True@1070/1012 的
全表对照）。guard pid 3511974/子 3511975，日志
`/home/xkq/logs/014/m5_inv_p2.log`，帽 6144。harness 补了 M5 内存纪律
（phase 间 gc.collect()，两图周期不共存；build_vm.py:263 reset_graph
本就断链）。M4 死跑 89 行判读：off 臂全 55 例 + on 臂至 Am/h3 与基线
逐位吻合，无翻车迹象，但整轮作废从头补完跑（不作废续跑无法保证同窗
输入一致）。

### M5-0x 并行推进（探针在跑 13 分钟时点，off 臂 nat 组步数与 M2 基线逐位吻合）

- **M5-05 硬编码扫描（初扫，正式条目待终态）**：`git diff ce37f48..HEAD --
  lean_vm/build_vm.py` 新增 275 行逐查——零 cid 引用（`grep CID_|cid` 非注释
  行 0 命中）、零常量名字符串；非注释字符串字面量仅 env 开关名（VM014_*）、
  docstring、`tie_break="latest"`。缓存两臂全结构式：键=token kind 常数
  （41/43 是流内 kind，非 ENV cid）、查询=_eq_expr 四/五元组、写门=D2 价值
  门/busy 掩码（帧臂名）。tokens.py/文档注引已全在 §18（M4 已把 M1 的
  "§15 前瞻注"落为 §18 实际引用；`ENV_FORMAT.md:449` 的 §15 指 reduce_nat
  表扩，本就正确）。
- **ENV_FORMAT 补账（完工定义第 3 条）**：§2.1/§2.2 编号表登记
  41=T_DEFCACHE / 42=T_DEFFAIL（预留未发射）/ 43=T_WHNFCACHE，字段布局与
  VM_SPEC §18 指针写明（M2/M4 落 kind 时欠的同步，M5 补上）。
- **文档定稿已落**：ADR 018 追记节（d6 定性更正+XPASS 摘除记录+memo 独立
  理由）；KERNEL_COVERAGE B14 终态行（11/11 全绿、KNOWN_GAPS 空）；卡 009
  状态追记+verifier 第 1 项补勾（12/12 原文）；ARCHITECTURE 卡 009/014 段
  终态改写（closed、帽裁决执行、G4_d6 摘除）。
- **引擎通道预核**：vm.cpp kind 无白名单（S_K 透传值，kind 比较在图内
  dims），新 kind 不需引擎改动；vm_run 未重编（09-15）即可读新件的假设由
  M5-03 34/34 实证。§18.2 钳位段两臂共用 `_v0sq` 已写明，无遗漏。

---

## 总控裁决 ADR016（2026-09-17 16:5x，补上欠了 17 任的闸）

三选一裁决：**采 B（合同不动，调用方续 whnf）**。理由与边界：

- **A（图侧改 I_PROJ 交付合同）否**：交付合同变更=全部 whnf 差分基线
  重钉（34/34 引擎、22 套件回归、stepgraph 37 例、verify_engine_vs_refvm）
  + 存量"停 raw field 正是其绿灯原因"用例逐例复核（P7.5c-2 开放项场景），
  且历史证明软/硬拒绝边界一动就出事（§11.17 软旗 bug 族）。收益（顶层
  交付直出 whnf）不值这张回炉票。
- **C（记录不修）否**：B 的循环出口归卡 010（step_driver.py 属主域），
  卡 010 反正要动 step_driver 的声明注入协议——顺手把续 whnf 出口做了，
  边际成本≈0；C 省不下任何东西，只把已知缺陷拖进卡 013 的引擎 CHECK
  通道依赖面（顶层 whnf 交付的消费方在下一张卡就出现）。
- **B 采**：驱动器对 TASK_WHNF 顶层出口按内核 `whnf_core` 回灌语义
  （`K/type_checker.cpp:503-508`）再发 TASK_WHNF 至焦点不再前进。
  停止条件复用 TimeoutError 预算（焦点不变即停，§11.17 decline 语义为
  参照）。**判定仍全走图**（B 的循环由图自身 whnf 任务构成，非 Python
  语义近似，与验收铁律 1 相容）。
- **归属与接口**：实作折入 **卡 010 任务书**（G 链，step_driver.py owner）；
  卡 010 交付时须含"raw field 开放项不空转"用例（焦点不变即停的负例）。
  卡 013（引擎 CHECK）设计时可依赖"顶层 whnf 出口=头范式"的合同（B 落地后）。
- 本裁决使 ADR016 自 draft 转 **accepted**；F15 复核段（引用行号核对）
  全部成立，无需追改。

### M5-01 结果 P2 不变性 55 例全表补完跑（原文 `/home/xkq/logs/014/m5_inv_p2.log`，帽 1100）

```
=== verdict invariance table (steps may only go DOWN) ===
case             oracle   off                    on                     delta
A/j1_same_def_diffidx True     True/21                True/21                +0 OK
A/j2_diff_def_sameidx_fieldeq True     True/69                True/63                -6 OK
A/j3_diff_def_sameidx_fieldne False    False/69               False/63               -6 OK
A/j4_ctor_child_no_delta False    False/69               False/63               -6 OK
A/j5_proj_vs_lit_direct True     True/15                True/15                +0 OK
A/o1_succ_delta_args True     True/37                True/37                +0 OK
A/o2_succ_lit_chain True     True/27                True/27                +0 OK
A/o3_succ_vs_lit_fail False    False/16               False/16               +0 OK
A/r1_refl_beq_true True     True/10                True/10                +0 OK
A/r2_refl_delta_arg True     True/11                True/11                +0 OK
A/r3_refl_false_side False    False/10               False/10               +0 OK
A/r4_refl_swapped True     True/13                True/13                +0 OK
A/h1_args_fastpath True     True/63                True/63                +0 OK
A/h2_args_ne     False    False/41               False/41               +0 OK
A/h3_mixed_hints True     True/42                True/42                +0 OK
A/h4_red_vs_regular True     True/77                True/77                +0 OK
Am/j1_same_def_diffidx True     True/21                True/21                +0 OK
Am/j2_diff_def_sameidx_fieldeq True     True/69                True/63                -6 OK
Am/j3_diff_def_sameidx_fieldne False    False/69               False/63               -6 OK
Am/j4_ctor_child_no_delta False    False/69               False/63               -6 OK
Am/j5_proj_vs_lit_direct True     True/15                True/15                +0 OK
Am/o1_succ_delta_args True     True/37                True/37                +0 OK
Am/o2_succ_lit_chain True     True/27                True/27                +0 OK
Am/o3_succ_vs_lit_fail False    False/16               False/16               +0 OK
Am/r1_refl_beq_true True     True/10                True/10                +0 OK
Am/r2_refl_delta_arg True     True/11                True/11                +0 OK
Am/r3_refl_false_side False    False/10               False/10               +0 OK
Am/r4_refl_swapped True     True/13                True/13                +0 OK
Am/h1_args_fastpath True     True/27                True/27                +0 OK
Am/h2_args_ne    False    False/50               False/50               +0 OK
Am/h3_mixed_hints True     True/42                True/42                +0 OK
Am/h4_red_vs_regular True     True/77                True/77                +0 OK
G/g0_accept_add  ?        0/8                    0/8                    +0 OK
G/g1_type_lit    ?        5/4                    5/4                    +0 OK
G/g1b_type_lam   ?        5/10                   5/10                   +0 OK
G/g7_fvar_type   ?        6/0                    6/0                    +0 OK
G/g7_mvar_type   ?        6/0                    6/0                    +0 OK
G/g7_mvar_value  ?        6/0                    6/0                    +0 OK
G/g7_fvar_value  ?        6/0                    6/0                    +0 OK
G/g2_def_mismatch ?        1/30                   1/30                   +0 OK
G/g4_opaque_mismatch ?        1/30                   1/30                   +0 OK
G/g5_axiom_funtype_ok ?        0/18                   0/18                   +0 OK
G/g5_axiom_type_lit ?        5/4                    5/4                    +0 OK
G/g10_partial_plain_ok ?        0/16                   0/16                   +0 OK
G3_d1_3          True     True/134               True/134               +0 OK
G3_d1_4          False    False/132              False/132              +0 OK
G3_d1_shadow     True     True/171               True/171               +0 OK
G2_d3            True     True/483               True/483               +0 OK
G2_d4            True     True/648               True/648               +0 OK
G4_d6            True     True/1070              True/1012              -58 OK
G4_d7            False    False/182              False/154              -28 OK
G5_eL1           True     True/118               True/118               +0 OK
G5_eL2           True     True/158               True/158               +0 OK
G5_eL3           True     True/460               True/460               +0 OK
G5_eL3_neg       False    False/458              False/458              +0 OK
=== ALL OK ===
total 2369s
[mem-guard] wall 2369.2s peak RSS 5506MB rc=0
```

要点：55 例 verdict 逐条 ON=OFF、步数只降不升（**P2 新命中首次全表可见**：
P1 层（M2 双跑）全 +0 无命中，P2 层 j2/j3/j4 两流各 -6、d7 -28、d6
-58（1070→1012），其余 +0；全表无一上升）。d6 双臂 True=live oracle
（表列 oracle True）——off 臂 P1-only 1070 步收敛在帽 1100 内，替代了
M4 时代只能靠 1500 专项跑的证据位。两遍 off 臂步数与 M2 基线逐位吻合
（134/132/171/483/648/720→1070/182; 118/158/460/458）。guard rc=0，
2369.2s，峰 5506MB（相位间 gc.collect() 生效，两图不共存）。

### M5-02c 专测三态臂完整跑（在跑）

`tests/test_defeq_cache_vs_lean.py --phase all`（small 64 例双臂 +
d6 P1-only/P1+P2 双臂 live oracle + registry 一致性 + whnf 活性臂）：
guard pid 3517083/子 3517084，日志 `/home/xkq/logs/014/m5_cache_all.log`，
帽 6144。此为 M4 扩展后**首次完整跑**（M4 死前未跑），同时给回归行
defeq_cache 的 timeout/RSS 帽定实测依据。

### M5-02c 首跑结果与 whnf 活性臂过度断言的修正（重要，非放宽）

`--phase all` 首跑（`m5_cache_all.log`，2138.6s 峰 4742MB rc=1，9 FAIL）：

- **small 臂 64 例 + false-repeat 全 OK（977s）**；**d6 臂全绿**：
  `d6 live oracle: d6l=?=d6r -> True`
  `d6 P1-only=(True, 1070, 87, 0)  P1+P2=(True, 1012, 87, 54)`
  ——双臂=oracle、步数降、54 条 memo 活性、registry 一致性检查通过。
- 9 个 FAIL 全在 **whnf 活性臂的跨图结果比较**：`r1[1][1] == p2v` 要求
  P1-only 对照组 run2 的交付闭包与 P2 重放臂 run2 **逐位置相等**。实测
  反例形如 run1=(573,0)/19 → p2 重放 run2=(573,0)/1，对照重算
  run2=(613,0)/19。诊断（/tmp 探针复刻臂机制，decode_closure 解树）：
  **内容全等**（o1.r LitNat(5)=LitNat(5)、h1.l 16、h2.l 6、o3.l 4，
  replay==control-recompute content 全 True；p2 图 run1 内 p1v==p2v
  位置等亦全 True）。机制=流 append-only：重算把归约链**重新物化为新
  token**（573→613 差 40 个 nat-redex 位点），重放复用 run1 的规范
  物化位点——位置不是跨流不变量，**内容才是**（whnf 是 (pos,env,flag)
  的函数，其值以表达式树计）。j 系（纯 delta 展开、不新增 token）位置
  恰好相等，掩盖了该假设。
- 裁决：**判定不变性零破线**（verdict 面：d6/brec/55 表全绿；步数面：
  只降），坏的是 M4 写的 harness 断言超出其自身 docstring 合同
  （"re-runs at full cost (the control)"——控制组合同是**成本**不是
  位置）。修正=跨图比较改 decode_closure 内容等（这比位置等**更能**
  抓错重放：值错必翻），同图 replay==run1 位置等保留（该处健全），
  控制组步数 `> s2` 保留。不删用例、不降步数/活性判据。注释按踩坑
  记录规约写明证据。py_compile OK。
- 复跑（whnf 臂）：guard pid 3593311/子 3593312，日志
  `/home/xkq/logs/014/m5_cache_whnf.log`（预计 ~12min）。

---

## 事故记录 M5（约 18:2x database is locked，第 18 任；总控收场）

- **死亡时进度**：M5-01（55 例不变性补完 ALL OK 2369s rc=0）、M5-02（帽
  1100 生效 → **XPASS 实证触发 → G4_d6 按规程摘除 → 全量重跑 0 分歧
  0 xfail 468.8s rc=0** = d6 转绿）、M5-02c（专测 --phase all 首跑 9 FAIL
  全在 whnf 臂跨图位置比较，M5 诊断为 harness 断言超出自身合同——位置非
  跨流不变量、内容才是；修断言为 decode_closure 内容等（严于位置等），
  零删用例零降判据；复跑 whnf 臂 **ALL OK** 712s rc=0）、M5-03（引擎钉
  P2 scratch **34/34** rc=0）、文档定稿（ADR018 追记、B14 终态、卡面、
  ARCHITECTURE）全部完成。**唯一未竟：M5-04 全量回归——死亡后遗留后台链
  仍在跑（stepgraph 系在核 0-5 活跃），按 M2 先例候其自完，总控读 rc 定账。**
- 总控补跑：三态编译 OFF 臂=基线逐字节确定性（lead 亲验）；d6@1100 全量
  差分与引擎 34/34 总控亲验重跑。

---

## 总控警报：M5 回归链抓出判定不变性破线（18:5x，M6 任务书依据）

M5 遗留的 22 套件回归链（后台存活，截至 18:46 出 18 rc，**5 个非零**，
全部为卡 014 图变更所引入——ce37f48 基线上这些套件昨夜 21/21 全绿总控亲跑）：

| 套件 | 失败点 | 症状 |
|---|---|---|
| string B | `deq_oflist_true`、`deq_proj_vs_oflist_true` | graph=VMError reject，oracle=True（B 28/30） |
| check_e2e B | `chk_inc_fn` | graph=False，refvm=True（B 14/15） |
| mutation_reject | `b_inc` BASE 被拒；`m_dbl_bool`/`m_pairapp_p2` **错误类别错位**（ill_typed localize 的 off 读数≠期望） | 违反验收标准 2（拒绝错误类别一致） |
| olean_export B | 1 例 B 16/17（ref=Const Nat 形状差） | 同类 |

- **合同洞**：M5-01 的 55 例不变性表只覆盖 defeq_branches/brec 语料族，
  string/check/mutation/olean 不在表内——缓存臂的判定不变性合同自 M2 起
  的验证面就不完整，M4 备忘录 R1（写臂不约束 C/F、命中重放链态不齐）
  是头号嫌疑，在未测语料域成真。
- **待 M6**：三态 bisect（OFF/P1/P2 × string+check_e2e）定罪到臂 →
  机制诊断（diag 探针逐拍对拍首漂点）→ 根因修（禁语料白名单式 ad-hoc）→
  **不变性表扩到全判定语料**（这是本卡对"合同"欠的账）。
- **后备方案（授权 M6）**：d6 绿不依赖 P2（P1-only 1070≤帽 1100 即收敛）——
  若 P2 修两败仍破线，P2 整体回滚（d6 绿专测臂同滚），P1 单独交付
  收口，whnf memo 合同降级为"引擎通道钳位域外、Python 域破线待修"另立
  ADR。第 3 次盲改禁止（红线 6）。
- 回归链剩余（brec/defeq_cache/engine）rc 由 M6 候完记录；任何新失败并入
  bisect 证据面。

---

## M6 任执行日志（破线根因修，开工 2026-09-17 ~19:0x）

第五任 M5 死于 database is locked（18:2x），遗留 22 套件回归链抓出缓存臂
判定不变性破线（总控警报在上）。本任=根因修复任：定罪→bisect→机制→
根因修→不变性合同扩全语料。git 零接触。

### 机器姿态（开工快照 19:0x）

- 核段 0-5。`ps --sort=-rss`：用户 GPU 训练 `cpt/train_minimal.py`
  （pid 3654261 系 5 进程，~2.8GB+4×450MB，勿动勿杀）。
- M5 遗留回归链**仍在跑**（bash pid 3624762；当前套件
  test_defeq_cache_vs_lean pid 3656308，14min，RSS 944MB 正常）。
  本任**候其收工后才起大 eval**。
- 已出 rc（18:16–18:59 本轮）：非零 5 件 = check_e2e(1)、mutation_reject(1)、
  olean_export(1)、string(1)、**stepgraph_infer_defeq(137)**（新失败，
  mem-guard/timeout kill，cap 4000MB@18:40——案情面未列，并入证据面核查）。
  brec=0、engine=0（18:59）已收；defeq_cache 在跑。
- HEAD ed51502；三态编译件在盘
  （model/step_vm_m4_{base,p1,scratch}.sbin）。

### 子任务表

| id | 内容 | 状态 |
|---|---|---|
| M6-01 | 候 M5 回归链收工；记录 brec/defeq_cache/engine rc；新失败并入案情面 | 完成 |
| M6-02 | 三态 bisect：最小用例 string/deq_oflist_true + check_e2e/chk_inc_fn，定罪到臂 | 完成 |
| M6-03 | 机制诊断：ON/OFF 同窗逐拍对拍钉首漂拍，证据落板 | 完成（两案） |
| M6-04 | 根因修（禁白名单/特判；每次编辑后 py_compile；scratch 前缀 step_vm_m6_scratch） | 完成（(a)+(b) 修 + P2 回滚，见下） |
| M6-05 | 不变性合同扩表：probe_014_invariance 覆盖全判定语料族，三态对照 | 待办 |
| M6-06 | 全链收口：d6 绿/专测三态/引擎 34/34/22 套件回归/§18 合同更新/板终态 | 待办 |

### M6-01 回归链终账（19:2x 收工，原文 `/home/xkq/logs/014/m5_regression.log` 末段）

```
=== CPU regression: 17 passed, 5 failed ===
  FAIL stepgraph_infer_defeq: FAIL (memory guard kill) (rc=137)
  FAIL check_e2e: FAIL (rc=1)
  FAIL mutation_reject: FAIL (rc=1)
  FAIL olean_export: FAIL (rc=1)
  FAIL string_graph_vs_lean: FAIL (rc=1)
```

三件指定 rc：**brec=PASS**（562.4s peak 4693MB rc=0）、**defeq_cache=PASS**
（2013.5s peak 4750MB rc=0，whnf 臂 658s ALL OK——d6 P1-only=(True,1070)
P1+P2=(True,1012) 双臂=oracle）、**engine=PASS**（34/34，252.6s rc=0）。

案情面追加：`stepgraph_infer_defeq rc=137` 非判定破线，是 **mem-guard 顶帽
kill**（1388.7s 时 RSS 顶 4000MB 帽，kill 前所有已出用例全 PASS，末行
deq_brec_sum 469 步 PASS；日志原文 `/home/xkq/logs/lean4vm_cpu_regression/
stepgraph_infer_defeq.log`）。定性=缓存臂新增流 token（写臂 raw 每拍+1）
抬高 37 例长跑累积 RSS 越过旧帽——资源面回归，与 brec 行 5000→6000 先例
同族；修后（写门收紧=写量下降）复测，必要时行内升帽并记录证据。

bisect 最小复现体：`scripts/bisect_014_m6.py`（单例图求值，三态=三进程，
判据=与 OFF 态逐条相等；不预置答案——OFF≡live-lean 由各套件自身在案）。

### M6-02 三态 bisect（19:3x，harness 原文 `/home/xkq/logs/014/m6_bisect_*.log` 要点）

7 例破线面全复现，定罪唯一：**P2（VM014_WMEMO whnf memo）全案犯；
P1（VM014_CACHE）全清白**（verdict 逐例=OFF，步数只降）：

| case | OFF | P1(1,0) | P2(1,1) |
|---|---|---|---|
| deq_oflist_true | True/792 | True/600 (52写) | **reject/336** (21+48写) |
| deq_proj_vs_oflist_true | True/795 | True/603 | **reject/337** |
| chk_inc_fn | True/26 | True/26 | **reject/5** |
| b_inc | True/26 | True/26 | **reject/5** |
| inf_hof_app | Nat/13 | Nat/13 | **reject/6** |
| m_dbl_bool | tm/Bool/47 | 同 | **ill_typed/Nat**/44 |
| m_pairapp_p2 | tm/P2/61 | 同 | **ill_typed/Nat**/52 |

关键反常＝定罪证据：b_inc/chk/inf 在 P2 态 **5-6 拍 reject 且全流零
T_WHNFCACHE 条目**——破线**不是对已写条目的重放**，是命中门在无条目时
也开门。（P1 在新语料首见真命中：deq_oflist −192 步、52 条目，判定
不变=ADR 017 合同在 P1 成立。）

### M6-03 机制诊断（首漂拍钉死：空缓存假命中，命中值=当拍头 STATE token）

`scripts/probe_014_diag_check.py` P1 vs P2 逐拍对拍 b_inc（原文
`/home/xkq/logs/014/m6_diag_binc_{p1,p2}.log`）：s001-s004 两态全同；
s004 态 (A=145,B=0,C=0,D=590,E=0,F=0)，其中 D=590 = WHNF 帧
`FRAME(WHNF,1,145,589,0,0,0)`（V1=145 焦点、X=0 空 env、E2=0 硬通道、
caller=589）；该拍末尾追加的 **STATE token 本体 = (kind33, v0=145, v1=0,
v2=0, x=590, e2=0)**。P2 态 s005 提交 A=590 B=0 C=0 D=589 E=1 F=0、
s006 reject——与命中提交形 (A=wvx,B=wve,C=SC,D=frV2,E=1,F=SF) **逐字段
吻合**：(wv0,wv1,wv2,wvx,wve) 恰等于当拍头 STATE token 的
(v0,v1,v2,x,e2)=(145,0,0,590,0)。

**机制**：`_fetch_by_v0sq` 空缓存（或全部 cleared）时各位置分数同落
−BIG（ulp(1e20)≫2²⁴ 键项被吞），argmax 由 tie_break=latest 落到
**最新 token=当拍头 STATE**（不是 §18.2 声称的 position-0 T_NULL——
M1-01b 哨兵论证只验证了 P1 的四元组：STATE 的 v0=A=frV1 与 v1=B 过前两
关，v2=C 对 DEFEQ 的 s_pos、x=D 对 s_env 必败=侥幸安全，从未被结构保证）。
P2 三元组验证 (v0,v1,v2)==(frV1,frX,frE2) 在**入口形拍上是恒真式**：
入口门已强制 SA==frV1、SB==frX、SC==0，而硬 whnf 帧 frE2=0——三个验证
全过；STATE 的 (x,e2)=(D,E)=(帧位置, ret) 被当作"缓存结果"交付
→ 焦点 := 帧 token 自身 → 下游 ill_typed/reject。命中门对
「非条目 token」零防御是本案根因；M4 备忘录 R1（写臂不约束 C/F）是同族
次级合同洞（55 例表语料恰好全走 soft flag=1 或脏链路径，未触发）。

### M6-03(2) 第二机制：spine-walk 重派拍写错标键（string 族 reject@341）

修 (a)（命中门加 kind 验证：`_fetch_by_v0sq` 返回首字段=匹配 token 的
kind，P1/P2 命中门各自要求 `ckind==T_DEFCACHE` / `wvkind==T_WHNFCACHE`，
原文 `lean_vm/build_vm.py` M6-fix 注释）+ 修 (b)（P2 写门 `_wc_w` 收紧到
`is_whnf_frame ∧ D2==frV2 ∧ ¬whnf_cache ∧ SC==0 ∧ SF==0`=只在净出口拍写）
后，check/mutation/olean 三族 5 例转绿，**string 两例仍漂**。带临时
dbg 旗标（dbg_wchit/dbg_dchit/dbg_wcw/dbg_dcw，已删）逐拍定位
（原文 `/home/xkq/logs/014/m6_diag_str_p2.log`、`m6_diag_str_p1.log`）：

- s330 前后：帧 `FRAME(WHNF,V1=784,X=0,E2=0,caller)` 在 **spine-walk
  重派形**下被再次拍下——派发拍（I_ARG_S/ST phase2 类）在启动子 WHNF
  帧的**同一拍里推进焦点** (784,0)→(783, env@1603)。帧的 V1/X 记的是
  **旧焦点**，真机 whnf 的对象是新焦点。
- 子任务净出口拍把 (783 交付形) 写进键 (784,0)：`WHNFCACHE(784,0,...)`
  携带**外来值**。
- s338-339：一次**合法的入口形请求** (784,0) 命中该错标条目 → 重放
  外来值 → 走 INFER(783, foreign env) → 注错 CONST(0) →
  s342 REJECT focus=2075。P1 态同流无此条目，(784,0) 真机重算
  stuck→最终 d6 形交付 True@600。

即：键 (V1,X) 在「启动拍即推进焦点」的派发帧上是**过时的**，命中门无法
区分「帧 V1 就是 whnf 对象」与「帧 V1 已被同拍推进作废」。判别信息
（launch 拍焦点位移）跨拍，帧 6 字段无空位可存（F2 被 soft_flag/
D_SW3 id 占用；位置 ≤4096 时位打包 V2/X 撞帽）——P2 的健全性需要
**跨拍记忆 = 重新设计**，不是继续修门。

### M6-04 根因修 + 后备条款执行（P2 回滚，P1 单独交付）

两度修（(a) kind 验证、(b) 写门净出口收紧）后 string 族仍破线 ⇒
触发任务书后备条款「**P2 两度修仍破线 → 回滚 P2，P1 单独交付走
M6-05/06 同程，P2 破线案落新 ADR 移交后续卡**」。回滚=**dormant 不删
码**（臂保留在码，默认关闭）：

1. `VM014_WMEMO` 默认 "1"→"0"（`build_vm.py:252`，M6 ROLLBACK 注释块
   :238：stale V1/X 错标键、需跨拍记忆、仅研究用途显式 opt-in、
   禁上任何验收路径、指向 ADR 019）。
2. 保留修 (a)：P1 命中门同样吃 `_fetch_by_v0sq` kind 验证——它修的是
   共享底座的空缓存假命中类，对 P1 是防御性收紧（P1 四元组本已侥幸
   安全，现在结构安全）。
3. 保留修 (b) 于 dormant 码内（若后续卡重启 P2，(b) 是必要非充分）。
4. 临时 dbg 输出四枚已删；`py_compile` 全绿。

d6 不损失：P1-only 收敛 True@1070 ≤ 帽 1100（在案 M5-02b）。

**回滚后默认态复测（原文 `/home/xkq/logs/014/m6_bisect_final_default.log`
+ `m6_bisect_off_all7.log`，OFF 对照在跑，pid 3719694/3719695）：**

```
RESULT case=deq_oflist_true cache=1 wmemo=0 got=True steps=600 defcache=52 whnfcache=0 t=51.8s
RESULT case=deq_proj_vs_oflist_true cache=1 wmemo=0 got=True steps=603 defcache=53 whnfcache=0 t=53.8s
RESULT case=chk_inc_fn cache=1 wmemo=0 got=True steps=26 defcache=3 whnfcache=0 refvm=True t=15.4s
RESULT case=b_inc cache=1 wmemo=0 got=True steps=26 defcache=3 whnfcache=0 t=15.6s
RESULT case=inf_hof_app cache=1 wmemo=0 got="Const(name='Nat', levels=())" steps=13 defcache=3 whnfcache=0 ref=Const(name='Nat', levels=()) t=16.4s
RESULT case=m_dbl_bool cache=1 wmemo=0 got="reject(VM reject 1: step graph reject) loc={'kind': type_mismatch, 'off': Const(name='Bool', levels=())}" steps=47 defcache=1 whnfcache=0 t=33.4s
RESULT case=m_pairapp_p2 cache=1 wmemo=0 got="reject(VM reject 1: step graph reject) loc={'kind': type_mismatch, 'off': Const(name='P2', levels=())}" steps=61 defcache=2 whnfcache=0 t=34.7s
```

7/7 破线例在默认态（P1-only）全部回到 OFF 判定且步数非增。

---

## M7 任执行日志（终局收口，开工 2026-09-18 ~00:44）

第六任 M6 完成定罪（P2 全犯、两机制钉死、ADR 019 accepted）与回滚执行
（P2 dormant、修 (a) 入共享底座、修 (b) 留休眠码），死于断电前未跑
M6-05/06。本任=终局收口任：P1-only 交付态的合同补全 + 全链验收。git 零接触。

### 机器姿态（开工快照）

- 核段 0-5（简报写死）。`ps --sort=-rss`（00:44）：无大 Python 任务；
  最大户 = ZCode/gnome 桌面进程 ≤408MB。用户 GPU 训练当前未见。
  同时段另有清洁子代理在跑（只动 __pycache__/pip 缓存/tmp 残留，无核
  算力；scratch 件若"消失"先查板子再报，不动它的目录）。
- HEAD 04d424c；默认编译=显式 P1 编译逐字节、OFF 态编译=009 基线逐字节
  （总控亲验在案）。Python=/home/xkq/miniconda3/envs/train/bin/python，
  日志 /home/xkq/logs/014/m7_*.log。

### 子任务表

| id | 内容 | 状态 |
|---|---|---|
| M7-00 | 必读核对（板/卡/ADR019/§18/探针/专测现场）+ 上板 | 完成 |
| M7-01 | 专测适配默认态：whnf/P2 臂 WMEMO-off 下干净跳过或反向断言，`--phase all` 全绿（帽 6144） | 待办 |
| M7-02 | 全语料不变性表：probe_014_invariance 扩 string B30/check_e2e A/B30/mutation/olean/defeq55/brec B-C，OFF vs P1 两态逐用例 verdict 相等+步数非增，三列全表落板；7 破线例在表内 verdict=OFF | 待办 |
| M7-03 | stepgraph_infer_defeq 复跑（M5 rc=137=mem-guard 顶帽杀非语义失败）：默认图 guarded 单跑，必要时行内升内存帽（只动帽不动 timeout 语义，理由落板） | 待办 |
| M7-04 | 引擎通道：m7_scratch 编译报 dims/lookups/nnz（nnz 应≈192,691 P1 级/192,717 级核对）+ verify_engine_vs_refvm 34/34 + 硬编码扫描（缓存两臂重点） | 待办 |
| M7-05 | 全量回归 run_cpu_regression.sh → 22/22（默认图=P1 态首次干净全绿=本卡验收门）；任何 FAIL 停手落证据 | 待办 |
| M7-06 | 文档定稿（ADR019 口径）：§18 补 §18.6 交付态节+§18.5 勘正、ENV_FORMAT 42/43 dormant 注记、KERNEL_COVERAGE B14 终态、卡 014 verifier 原文证据备齐（勾选留总控）、板终态+总控自查清单 | 待办 |

### M7-00 必读核对结论（00:5x）

- 板/卡/ADR019/§18/探针/专测全读。HEAD 04d424c、工作区干净（开工时除本板）。
- **文档现状盘点（影响 M7-06 范围）**：M6 断电前已把 §18 标题/§18.2 哨兵
  更正/§18.3/§18.4 DORMANT 块写好，但 §18 内 3 处引用 **§18.6**（交付态节）
  不存在=悬空引用，§18.5 仍按"P2 在验收面"口径 → M7-06a 补 §18.6 + 勘正
  §18.5。ENV_FORMAT L190/L192 两 kind 行已有布局注记，缺 41=发射态/
  42/43=dormant 状态注 → M7-06b。KERNEL_COVERAGE B14 仍是 M5 终态
  （11/11 含 memo）→ M7-06c 按 ADR019 口径重写。
- **专测默认态适配（M7-01）已由 M6 落码**：whnf 相位与 d6 P1+P2 臂均为
  显式 SKIP+打印理由+`VM014_ALLOW_P2` 研究 opt-in（非静默）；本任在
  d6 臂追加**反向断言**：P1-only 默认图 T_WHNFCACHE 条目数必须=0
  （p1[3]≠0 即 FAIL，钉死"发布图 whnf-memo 惰性"）。small/d6 P1 臂不动。
- **探针缺口（M7-02 待补）**：现 collect_fams 覆盖 STR 27/CHK 12/MUTB 8/
  MUT 8/INF 6；实测套件面 = string B **30**（缺 PROJ_CASES 3：raw .proj
  WHNF，w5.run_proj_oracle 活体批）、check_e2e 图侧 **15**（缺 SEQUENCES
  3 多声明案例；A/B 30 = 15 判定×RefVM/图两层）、olean B **17**（缺
  GRAPH_WHNF 7 + GRAPH_DEFEQ 4，现仅 INF 6）。mutation 8+8 已全。
  → 补三面后全表 = 55 核心 + 30+15+16+14 语料面。

### M7-01a 专测默认态起跑 + 探针扩面落码（~01:0x）

- 专测 `--phase all`（默认态，含本任新加的 d6 反向断言 p1[3]==0）：
  guard pid **13029**/子 **13030**，帽 6144，日志
  `/home/xkq/logs/014/m7_cache_all.log`。small 臂 legacy 16/16 全 OK
  （run2 命中全 1 步，如 j5=True/15→True/1、h1=True/63→True/1）。
- 探针扩面落码（scripts/probe_014_invariance.py，未跑图先静态验证）：
  ①STR +3 PROJ_CASES（raw .proj WHNF，活体 w5.run_proj_oracle 批）=30；
  ②CHK +3 SEQUENCES（多声明 run_check）=15；③新 OE 族 11
  （GRAPH_WHNF 7 + GRAPH_DEFEQ 4，GRAPH_* 过滤口径与套件一致）；
  INF 6 保留。**抓出并修 M6 遗留 bug**：expected 循环对已解包 payload
  又取 `oval[1]`（run_oracle_mixed 返回 (kind,payload)，探针解包成
  (_k,oval) 后 oval 即 payload）——M6 只跑过 quick 烟测（CHK/INF-only）
  未触及该循环，full 首跑即 KeyError；修正直用 payload（注释留案）。
- collect_fams('full') 干跑实锤：fam 计数 STR 30/CHK 15/MUTB 8/MUT 8/
  INF 6/OE 11=78 + 核心 55 = **133 行/态、266 判定**；expected 30 条
  （STR 全族活体 lean；CHK/MUT/OE 按套件在案=表内"?"，与 M6 口径一致）。
  破线 7 例位点核对：deq_oflist_true/deq_proj_vs_oflist_true=STR、
  chk_inc_fn=CHK、b_inc=MUTB、m_dbl_bool/m_pairapp_p2=MUT、
  inf_hof_app=INF，全在表。
- 硬编码扫描（M7-04 静态半）：`git diff ce37f48..HEAD`（build_vm+tokens）
  新增非注释行 178 行全查——字符串字面量仅 "VM014_CACHE"/"VM014_WMEMO"
  （env 开关名）与 "latest"（tie_break）；零 CID_ 引用、零常量名分派
  （E_d 系变量名误中、docstring 叙事含 b_inc 案名非分支）。缓存两臂
  键=流内 kind 常数 41/43+四/五元组 _eq_expr 验证，结构式。
- 文档已动：ENV_FORMAT kind 表 41/42/43 发射态注记（M7-06b 毕）；
  KERNEL_COVERAGE B14 终态行按 ADR019 口径重写（M7-06c 毕）；
  VM_SPEC §18.5 验收面勘正 + §18.6 交付态节补写（数字占位待
  M7-02/M7-04/M7-05 终值回填，M7-06a 半程）。

---

## M8 任执行日志（验证跑收口，开工 2026-09-18 ~01:1x）

第七任 M7 死于 33min 跑后 database is locked（第 20 任）；其交付：专测
`--phase all` 默认态 ALL OK@1100s（m7_cache_all.log，d6 P1-only=True@1070、
P2 休眠反向断言=0 成立）、不变性探针扩面落码+静态验证（133 行/态、
破线 7 例全在表、M6 KeyError 已修）、硬编码扫描干净、文档占位半程。
本任=验证跑收口任：四件大跑 + 定稿回填。git 零接触。

### 机器姿态（开工快照 01:19）

- 核段 0-5（简报写死）。`ps --sort=-rss`：用户 GPU 训练
  `cpt/train_minimal.py`（pid 27899 系 5 进程，1.35GB+4×336MB，勿动勿杀）；
  本项目域无大 Python 求值；`pgrep -af 'probe_014|run_mem_guarded'` 空。
  可用内存 23GB。
- HEAD c841ff1；默认图=P1-only（VM014_WMEMO 默认 "0"），nnz 192,717
  （总控双编译确定性亲验）；OFF 态与 009 基线逐字节。
- 大 eval 串行规则：inv_full 跑完前不起另一个大 eval（stepgraph 复跑
  与编译算小件放行；22 套件回归必须排队等 inv_full）。
- Python=/home/xkq/miniconda3/envs/train/bin/python，日志
  /home/xkq/logs/014/m8_*.log。

### 子任务表

| id | 内容 | 状态 |
|---|---|---|
| M8-01 | 全语料不变性表实跑（probe --cases full，OFF vs P1，帽 6144，133 行/态×2）；判据：逐用例 verdict 相等+步数 P1≤OFF；破线 7 例逐条点名；任何破线立停上板不放宽 | 在跑 |
| M8-02 | stepgraph_infer_defeq 单跑复测，帽 5000MB（M5 顶 4000 被杀、kill 前全 PASS；只动帽不动 timeout，依据落板）；rc=0 后 run_cpu_regression.sh 该行 4000→5000 | 候 M8-01 |
| M8-03 | 引擎通道：compile_vm --sparse model/step_vm_m8_scratch 报 dims/lookups/nnz 终数 + SBIN 钉件 verify_engine_vs_refvm 34/34 原文 | 候 M8-01 |
| M8-04 | 22 套件回归 22/22（默认图=P1 首次干净全绿=本卡验收门；必须 M8-01 完成后起）；任何 FAIL 停手报告 | 待办 |
| M8-05 | 定稿回填：VM_SPEC §18.5/§18.6 占位→终值、KERNEL_COVERAGE B14 勘正、板终态（子任务表勘正+verifier 原文粘贴+总控五道门自查清单）；卡 014 状态/勾框不动（结案权属总控） | 待办 |

### M8-01 全语料不变性表实跑起跑（01:2x）

- 起法照简报：guard pid **90671** / 子 **90672**，`run_mem_guarded.py
  --max-rss-mb 6144 -- probe_014_invariance.py --cases full`（layer 默认
  p1=OFF vs 默认图 P1 两态），日志 `/home/xkq/logs/014/m8_inv_full.log`。
- 预计 1.5–2.5h（133 行/态 × 2 态）。判据：逐用例 verdict 相等、步数
  P1≤OFF；破线 7 例（deq_oflist_true/deq_proj_vs_oflist_true/chk_inc_fn/
  b_inc/inf_hof_app/m_dbl_bool/m_pairapp_p2）逐条点名 verdict=OFF、步数
  非增。任何一条破线→立停、证据落板、不放宽。

### M8-02 stepgraph 单跑复测起跑（01:2x，与 M8-01 并行=简报放行小件）

- 起法：`run_mem_guarded.py --max-rss-mb 5000 --timeout 2700 --
  tests/test_stepgraph_infer_defeq.py`，guard pid **91086** / 子 **91087**，
  日志 `/home/xkq/logs/014/m8_stepgraph.log`。
- 依据：M5 该行 rc=137=mem-guard 顶 4000MB 帽 kill（1388.7s 时 RSS 顶帽，
  kill 前所有已出用例全 PASS，末行 deq_brec_sum 469 步 PASS——板 M6-01
  案情面在案）→ 资源面非语义失败。本跑只动内存帽 4000→5000（留 ~21%
  裕度，同 brec 行先例），timeout 2700 照回归行不动。rc=0 后才把
  run_cpu_regression.sh:96 该行帽同步。

### M8-01 起跑状态（01:2x 抽查）

- `corpora + live oracles collected 17s`；OFF 相位已在逐用例出数
  （A/j1 True@21、A/j2 True@69）。

### M8-03 引擎通道（01:2x）

- 编译（pid 91182，日志 `m8_compile.log`）终数：
  `graph: 25990 dims, 2899 lookups`；`schedule: 114 layers,
  d_model=4822`；`build_weights(sparse): d_model=6252 heads_global=650
  ffn=2704 nnz=192,717`；`saved model/step_vm_m8_scratch.sbin`
  （18,888,194 B）。**nnz=192,717 与总控双编译确定性亲验值精确一致**
  （M7-04 预估 192,691/192,717 两档之一），schedule 114 层。
- 对拍：`SBIN=$PWD/model/step_vm_m8_scratch.sbin
  verify_engine_vs_refvm.py` 已起（日志 `m8_engine.log`），34 例结果待收。

### M8-03 引擎对拍收工（01:3x，原文 `/home/xkq/logs/014/m8_engine.log` 末段）

- `SBIN=$PWD/model/step_vm_m8_scratch.sbin` 钉件跑（首起 exit=127 系我把
  SBIN= 放 taskset 之后被当命令名，改经 env 前置即起，非图问题）：

```
=== H3 engine vs RefVM: 34/34 verdicts correct ===
    argmax vs softmax streams identical: 34/34
    known-value checks: 3/4
    total engine wall time: argmax 104.6s, softmax 186.0s
```

- `^  FAIL ` 行=0（脚本 rc 判据 `return 0 if not fails`）；`[PASS]`=34。
- 与回归基线（M6 轮 engine 行）逐字段一致：known=BAD 仅在 succ_zero
  （WHNF 交付形态差），3/4 为在案旧基线，非倒退。

### 文档回填（编译终数，01:4x；M8-05 提前完成编译数部分）

- ARCHITECTURE.md：权重侧规模行改**交付态=25,990/2,899/192,717/114 层**
  （critical_path 历史值 120 系 P1+P2 态，009 代=114，P1+修 (a) 实测
  critical_path=114——文档与 m8_compile 实测冲突即改，AGENTS 冲突裁决）；
  真值表新增 `step_vm_m8_scratch.sbin`=当前图行（18,888,194B、引擎 34/34
  在案），m2/m4 件标签勘正（m4=P1+P2 历史研究件，P2 dormant）。
- VM_SPEC §18.6：发布图占位「25,985+修 (a) 增量」→ 终值 25,990/2,899/
  192,717 + 日志引用（m8_compile.log/m8_engine.log 原文要点）。

### M8-01 中段观察（01:5x，非结论）

- OFF 相 `nat:G4_d6 True steps=1070 defcache_toks=0`（m8_inv_full.log 原文）
  ——基线（零缓存）d6 即在帽 1100 内收敛 @1070，与 P1-only 1070 持平：
  d6 转绿实质由 720→1100 帽裁决完成，P1 对 d6 无步数增益（与 M1-01c
  "P1 不足让 d6 转绿/重复对新键" 勘察并不矛盾——慢在 below 重展开本身，
  帽内可收敛）。预期 ON 相 d6 delta=+0 或微降，均合法（只禁升）。
- 01:55 前后 OFF 相已进 STR 族；stepgraph 37 例区仍全 PASS、RSS 峰值段。

### M8-02 stepgraph 复测收工（02:0x，原文 `/home/xkq/logs/014/m8_stepgraph.log` 末段）

```
=== step graph vs RefVM infer/defeq: 84/84 (0 pinned: 0 M3 + 0 P7.5c) ===
[mem-guard] wall 1493.3s peak RSS 1479MB rc=0
```

- 84/84 全 PASS、rc=0。**实测峰值 1479MB**——远低于 M5 顶帽的 4000：
  M5 rc=137 的死因（P1+P2 态写臂 raw 每拍抬累积 RSS）确已被 P2 回滚
  消解（ADR 019 影响段预言兑现；本跑默认图=P1-only+修 (a)）。
- 回归行帽 4000→5000：**按本任简报指令执行**（run_cpu_regression.sh:96，
  只改此一处数字；`bash -n` 语法过）。落板双事实供总控勘正：实测
  1479MB 下旧帽 4000 已可绿，5000 升帽为简报指令产物而非实测必需，
  若总控按 ADR019「仍顶帽才升」口径更严，可回改 4000——两值均无害。

### 事故+修复 M8-01 首跑（02:0x，rc=1 崩于 OFF 相 98/133 行）

- **崩因（harness bug，非判定破线）**：`ValueError: not enough values to
  unpack (expected 2, got 1)` @ probe L242——M7-02 SEQUENCES 扩面括号错位
  `check_case([(CASE[m][2], CASE[m][3])] for m in members)` 把每个元素包成
  1 元 list；chk 12 单声明例全出、首个 seq 例即崩（quick 烟测从不执行
  seq 体，M7 静态验证只数了行数）。定罪过程：闭包 freevar 内省实锤
  decls 元素 `(1,'list')`。run_check 多声明路径本身有套件在案
  （test_check_e2e:100-106 layer B 同形），修=挪括号一对多（语义对齐
  套件），`py_compile` 过、复内省 7/2/2 全 `(2,'tuple')`。M6 KeyError
  同族案：扩面代码首跑才触底。
- **证据保留**：首跑日志改名 `/home/xkq/logs/014/m8_inv_full_crash1.log`
  （98 行 OFF：含 OFF 态 d6 True@1070、STR 30 行全出、chk 12 单例全出）。
- **帽调整（资源面，brec 升帽先例）**：crash1 实测 OFF 相 98/133 行已顶
  peak RSS 5930MB，帽 6144 余量仅 3.5%，ON 相必顶帽——升 `--max-rss-mb
  8192`（机 23GB 可用、用户 GPU 训练 ~2.8GB 稳定；判定判据一字不动）。
- **重跑**：guard pid **131386** / 子 **131387**，同日志
  `m8_inv_full.log`，02:0x 起。

### OFF 态跨进程确定性旁证（02:2x，非正式判据）

- 重启跑已完成的 OFF 行与 crash1 同名行 `comm -23`=0（verdict+步数逐字段
  等，39 行含 nat:G4_d6 True@1070）——OFF 图求值跨进程确定，供总控
  自查清单「OFF/默认确定性」门的既有账外补充旁证。

---

## M9 任执行日志（大跑收口，开工 2026-09-18 ~02:4x）

第八任 M8 死于会话级闪退（第 21 杀，~02:27；这次连 setsid 后台件也被带走）。
其已交付资产全在案：引擎 34/34（m8_engine.log）、stepgraph 84/84 rc=0 峰
1479MB、探针 seq 括号 bug 落码修复+py_compile 过、crash1 98 行 OFF 证据+39 行
跨进程确定性旁证、编译终数已回填 ARCHITECTURE/§18.6。本任=大跑收口任：
两件大跑（不变性全表 → 22 套件回归，严格串行）+ 定稿回填。git 零接触。

### 机器姿态（开工快照）

- 核段 0-5（简报写死）。Python=/home/xkq/miniconda3/envs/train/bin/python。
  日志 /home/xkq/logs/014/m9_*.log。HEAD f4f8e22。
- 死因勘查先行（M9-00），据结果定排程与双活证节奏。

### 子任务表

| id | 内容 | 状态 |
|---|---|---|
| M9-00 | 死因勘查：journalctl/dmesg OOM 记录 + 现状 free/ps；OOM 连带→大跑严格串行+自帽 ≤8192；纯客户端崩溃→setsid 件理论幸存，每件大跑起后 3 分钟内 pid+log mtime 双活证上板 | 在办 |
| M9-01 | 不变性全表实跑：probe --cases full（OFF vs 默认图 P1，133 行/态×2，帽 8192）；判据逐用例 verdict 相等+步数 ON≤OFF，破线 7 例逐条点名；任何破线立停上板不放宽、M9-02 不起 | 待办 |
| M9-02 | 22 套件回归 22/22（必须 M9-01 收工后串行起）；任何 FAIL 停手报告 | 待办 |
| M9-03 | 定稿回填：§18.5/§18.6 占位→终数、KERNEL_COVERAGE B14 复核、板终态（子任务表勘正+verifier 原文粘贴+总控五道门自查清单）；卡 014 状态/勾框不动 | 待办 |

### M9-00 动作计划

journalctl -k OOM 过滤 + dmesg 尾部；读不了则 free -g + ps --sort=-rss 现状
记录。结果落板后立刻起 M9-01。

### M9-00 死因勘查结论（02:5x，证据=journalctl 原文）

**死因定罪：systemd-oomd 整组击杀 ZCode 客户端 scope，setsid 件因同 cgroup 陪葬**
（不是 kernel OOM killer，不是纯客户端崩溃）：

```
9月 18 02:27:12 systemd[1398]: app-zcode-7806.scope: systemd-oomd killed some process(es) in this unit.
9月 18 02:27:12 systemd-oomd[944]: Killed /user.slice/user-1000.slice/user@1000.service/app.slice/app-zcode-7806.scope
    due to memory pressure for /user.slice/user-1000.slice/user@1000.service being 82.63% > 50.00% for > 20s with reclaim activity
9月 18 02:27:12 systemd-oomd[944]: Considered 61 cgroups for killing, top candidates were:
        Path: .../app.slice/app-zcode-7806.scope
                Pressure: Avg10: 84.56 Avg60: 33.68 Avg300: 8.29 Total: 32s
                Current Memory Usage: 24.8G
```

- kernel journal 同时段无 “Killed process”（OOM killer 未出手）；无 coredump。
- `m8_inv_full.log` mtime=02:27:01、末行 `[off] CHK/chk_two_pair OK steps=30`——
  无 `[mem-guard]` 总结行 ⇒ 非帽杀非自死，是外部 SIGKILL 整组。旁证：重跑已越过
  crash1 死点（seq 括号修复生效，chk_two_pair/chk_let 多声明例正常出数）。
- **机理**：M8 重跑由客户端会话 Bash 起 ⇒ setsid 换 session **不换 cgroup**，
  guard+probe 全在 app-zcode scope 内；该 scope memory.current 涨到 24.8G
  （probe RSS ~7-8G + 客户端 ~2G + 计入 cgroup 的 page cache 大头），user.slice
  PSI>50% 持续 20s+ ⇒ oomd 选它开刀，客户端与后台件同灭（“静默蒸发”真身）。
- **排程对策（简报 OOM 连带分支）**：①两件大跑严格串行（本就如此）；②自帽
  8192 不变；③**新增 cgroup 围栏**：起法外层加 `systemd-run --user --unit
  -p MemoryMax=12G -p MemorySwapMax=0`（AGENTS 首选内核级双限，09-16 实测
  “代价不出组”），把 RSS+cache 记账挪出客户端 scope、封顶 12G——即便 probe
  涨穿，OOM 只发生在我的瞬态 unit 内（rc=137），客户端与本任会话不再陪葬；
  内层 run_mem_guarded --max-rss-mb 8192 判据/帽语义与简报命令一字不动。
- 现状（02:5x）：free 24G/30G、PSI some avg10=0.00、swap used 3G；用户训练
  pid 27899 现 RSS 454MB（GPU 件勿动）；本会话新客户端 scope 各 zcode 进程
  ≤400MB；`pgrep probe_014|run_mem_guarded` 空。

### M9-01 起跑（02:5x）

- 起法：`systemd-run --user --unit=m9-inv-01 -p MemoryMax=12G -p
  MemorySwapMax=0 -p WorkingDirectory=<repo> /bin/bash -c 'exec env
  OMP_NUM_THREADS=3 taskset -c 0-5 python -u scripts/run_mem_guarded.py
  --max-rss-mb 8192 -- python -u scripts/probe_014_invariance.py --cases
  full >> /home/xkq/logs/014/m9_inv_full.log 2>&1 < /dev/null'`
  （除围栏外层，其余逐字照简报：同脚本/同帽/同核段 0-5/OMP=3/同日志名）。
- 起跑实锤（双活证 ①，t+111s）：unit MainPID **195378**（guard）/子
  **195381**（probe）；**PPID=1398（用户 systemd）**=已脱离客户端进程树，
  客户端再死不带件（M8 死法免疫）。`stat` log mtime=02:44:43、已出
  `[off] A/j5 True@15 / A/o1 True@37 / A/o2 True@27`；unit MemoryCurrent
  662MB、增长正常。预计 2–2.5h。

### M9-01 轮询心跳（双活证 ②…）

- **② t+12.5min（02:55）**：pid 195378/195381 活；log mtime 02:54:29；OFF
  45/133 行（A 55 族毕+G 族中），节奏 ~14s/行，零 VERDICT-DIFF/FAIL/
  Traceback；子 RSS 2.5G、unit 内存 2.6G（帽内、围栏远未触）。按此前置
  估 OFF 全相 ~35min、总时长按 ON 相似估 1.2–2h。

### M9-01 终局（总控代笔，M9 本体第 21 杀：database is locked，其大跑幸存）

- 客户端 03:0x 闪带走 M9 会话，**probe 大跑未陪葬**（setsid+脱离客户端树
  起法生效，与 M8 死法对比即 ADR 之外的规程实证）。总控接手亲自监跑至毕。
- 终账（原文 `/home/xkq/logs/014/m9_inv_full.log`）：
  `[mem-guard] wall 4782.4s peak RSS 5921MB rc=0`，尾部 `=== ALL OK ===`。
  **全表 133 行 ×{OFF,P1}=266 判定逐条 verdict 相等、步数非增
  （`grep -c " OK$" = 133`，非 OK 行 0）**。P2 全表 whnfcache_toks=0
  （dormant 反向断言在语料面再度成立）。
- **7 破线例终验**（M6 bisect 名单，交付态逐条）：
  `STR/deq_oflist_true True/792→True/600 -192 OK`；
  `STR/deq_proj_vs_oflist_true True/795→True/603 -192 OK`；
  `CHK/chk_inc_fn OK/26→OK/26 +0 OK`；`MUTB/b_inc OK/26→OK/26 +0 OK`；
  `INF/inf_hof_app 同值/13 +0 OK`；`MUT/m_dbl_bool 同判定/47 +0 OK`；
  `MUT/m_pairapp_p2 同判定/61 +0 OK`。前两条 = §18.5 命中活性账的
  全表内独立复现（52/53 条目与 M6 bisect 数字逐字一致）。
- 本节即 §18.5"M7 全语料层"引用的实跑凭证落点（M7 静态验证 →
  M8 首跑带伤 98 行 → M9 全量毕）。

## M10（总控亲自执行的终局复验，2026-09-18 05:2x–07:0x）

按 09-18 用户指令改法：最后一里不再派代理，总控自跑。

- **22 套件全量回归（交付态默认图）**：起法
  `setsid nohup env OMP_NUM_THREADS=3 REGRESSION_CORES=0-5 PYTHON=<train>
  taskset -c 0-5 <train>/python -u scripts/run_mem_guarded.py
  --max-rss-mb 12288 -- bash scripts/run_cpu_regression.sh`
  （日志 `/home/xkq/logs/014/m10_regression.log`）。外层 bash 的
  results 汇总段被会话中断陪葬（setsid 件幸存至全部套件落 rc 文件），
  按脚本自身判据逐条复核：**22/22 rc=0、零 FAIL**。关键行原文：
  `brec...: OK (0 divergences) 593s`；`defeq cache vs lean [all]:
  ALL OK (1273s)`；`H3 engine vs RefVM: 34/34 verdicts correct /
  argmax vs softmax streams identical: 34/34 / 0 条 FAIL /
  无 artifact 漂移（sbin-before 与终态 stat 逐字节同串）`。
  stepgraph_infer_defeq（帽 2700s/5000MB）等其余 19 套件 rc 全 0。
- 卡 014 五道门至此全过（差分零回归+M9 全表、回归 22/22、范围核对、
  文档同步、确定性/真值表在案）→ **卡 014 CLOSED（总控勾验）**。
