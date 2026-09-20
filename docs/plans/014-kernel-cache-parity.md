# 任务 014：图侧内核缓存层对齐（whnf memo + is_def_eq 正/负缓存）

状态：**CLOSED（2026-09-18 总控五道门勾验）**——M1-M10 沿革全录
docs/handoffs/010-M-cache.md。交付态 = **P1-only**（is_def_eq 正缓存默认
开、whnf memo P2 dormant，ADR 019）；d6 定性合法慢并以帽 1100 裁决收编
（GAP 摘除，0 xfail）；P2 重启需求（跨拍记忆）已落 ADR 019 移交后续卡。
依据：ADR 017（`docs/decisions/017-upstream-scope-gap-and-cache-layer.md`）。
依赖：卡 009 终态基线（全量差分 ≤1 分歧）、`docs/HYBRID_ARCH.md`（稀疏/内存纪律）。

## 目标

把内核本来就有的 memoization 层补进图，作为**判定一致性的组成部分**
（不是性能优化）：对任意深输入，图必须在与内核同量级的步数内到达与
内核相同的判定；有限步帽下的 Timeout = 判定分歧（验收铁律 1）。范围分两档：

- **P1 is_def_eq 正缓存**（先做）：内核在最终成功处写 `cache_success`
  （`K/type_checker.cpp:972`，调用点 :1251），入口处做 cheap structural
  check + 正缓存查询（:836），失败侧有 `cache_failure`（:953，调用点 :1042，
  仅缓存可安全回放的失败——注意内核只在一批位置写 failure，不是每个失败
  都缓存，对齐这个不对称）。图侧对应 = TASK_DEFEQ 入口新增数据驱动的
  流内查询臂：在已完成的 def-eq 帧中找**结构相同的 (t,s) 对**，命中则直接
  交付该结果。禁止按常量名/cid 特判（验收铁律 3）。
- **P2 whnf memo**（P1 落地后评估必要性再定）：内核 whnf 查
  `m_st->m_whnf`（:753-755）。图侧若 P1 已消掉 d6 类增长环且步数达标，
  P2 可以立"已知差距"缓做；不许两档同时开工。

## 涉及文件

`lean_vm/build_vm.py`、`expr/tokens.py`（如需新 token 类型，同步
`docs/ENV_FORMAT.md`）、新 `tests/test_defeq_cache_vs_lean.py`（差分：缓存
臂命中/未命中路径判定必须一致，且含 d6 类增长用例）、
`tests/test_brec_drec_iota_vs_lean.py`（仅当 d6 以 KNOWN-GAP 结案时在此
文件收编）、`docs/VM_SPEC.md`（新分派臂 + 缓存合同节）、
`docs/KERNEL_COVERAGE.md`、`docs/handoffs/005-F-iota.md` 或新交接板（派发时定）。

## 执行勘误（M1-01c 实测，2026-09-17，全录 docs/handoffs/010-M-cache.md）

五问已有答案：查询=单拍 attention 内容检索（reglu(v0,v0)=v0² 精确键分，
T_DEFCACHE raw 槽写、4×_eq_expr 验证、miss=现行为）；键=t_pos（实测遮蔽 0）；
软/硬=共用入口。**关键改判：d6 环 49 次 DEFEQ 发射中 45 次是首次新键——
P1 正缓存不足以让 d6 转绿，d6 成本在 below 族的 whnf 重展开 = P2
（m_whnf memo，:753-755）射程**。本卡第 4 条设计问题的 d6 归属实验按此
修正预期：P1 目标=重复对家族的判定一致性合同收窄，d6 绿是 P2 的验收。

## 设计问题（探查先行，答案进 handoff 后才许动图）

1. **流内匹配怎么表达**：已完成 def-eq 对的 (t,s) 序列化形态在 token 流里
   如何定位与比较？现有 `_eq_expr`/`_lvl_eq` 能否复用为查询键？attention
   查询成本随 env/流长怎么标（对照 AGENTS 反馈回路：开发期反馈 ≤1 分钟 →
   最小 env 探针）？
2. **判定不变性红线**（ADR 017）：缓存臂只能减少步数，不能改变 verdict。
   必须构造对照实验：同一用例集，关缓存臂 vs 开缓存臂，判定逐条相等；
   开帽前基线用 f13_diff_full_fix1.log 系。
3. **失败缓存的对齐边界**：内核 failure 只在特定位置写（:1042），并且
   `is_def_eq` 的循环重入语义（:1224-1227 re-dispatch guard）与缓存读有
   先后关系——图侧照抄顺序，引用行号写注释。
4. **d6 归属实验**：若 009 以 d6=KNOWN-GAP 结案，本卡第一件实质工作 =
   验证 P1 缓存臂使 d6 在帽内收敛（预期：重复 (t,s) 对第二次命中，增长环
   断掉）。d6 转绿则 009 的 KNOWN-GAP 注记改为"014 内解决"。
5. **软/硬通道边界**（与 009-F15 联动）：若 F15 的软链专用新臂落地，
   缓存查询放共用入口还是分通道入口，由 F15 终态决定，探查时两案都算。

## Verifier 集

- [x] P1 差分新测试绿：命中/未命中判定一致 ×（d4/d6/lst/nat 组 + 专造的
      重复对用例）；期望结果全部来自 oracle 现跑。
      （`m7_cache_all.log` small 64 例 ALL OK 1100s；回归位
      `defeq_cache_vs_lean` **ALL OK (1273s)** [M10]）
- [x] 全量差分相对 009 终态**零回归**；d6（若曾挂 GAP）转绿。
      （brec `OK (0 divergences) 593s`、G4_d6 已按 XPASS 规程摘除、
      d6 P1-only True@1070 ≤ 帽 1100）
- [x] 步数证据表：每用例缓存臂开/关的步数对比（只许降不许升，
      判定不许变）；d4 类线性成本用例步数下降记录在案。
      （**全语料 133 行×{OFF,P1}=266 判定表 `m9_inv_full.log`
      === ALL OK ===、rc=0、4782s**；命中活性 oflist 两例
      True@792→600 / 795→603；d4 类 = 缓存零接触对照组 +0）
- [x] 20 套件回归全绿；`verify_engine_vs_refvm` 不倒退；重编译 `--sparse`
      scratch 报 dims/lookups/nnz 增量；引擎钉 scratch 全例复验。
      （回归表已增至 **22 套件**：M10 亲跑 22/22 rc=0、零 FAIL；
      引擎 **34/34** 且无 artifact 漂移；交付态件
      `model/step_vm_m8_scratch.sbin` 25,990/2,899/192,717/114L [M8-03]）
- [x] 硬编码扫描零新增（常量名/cid 不入分派分支）。
      （M7-04 静态半：`git diff ce37f48..HEAD` 干净，缓存臂全数据驱动，
      板 M7 段；M5-05 初扫同样结论）
- [x] VM_SPEC 新合同节 + ENV_FORMAT（若动编码）+ ARCHITECTURE 真值表同步。
      （VM_SPEC §18.1-18.6 定稿含 M9 实跑凭证；ENV_FORMAT kind 41/42/43
      发射态全登记；ARCHITECTURE 真值表 m8 件行 + P1-only dims 行）

## 机器纪律

照 AGENTS：`setsid nohup env OMP_NUM_THREADS=3 taskset -c <核段>` +
`scripts/run_mem_guarded.py --max-rss-mb 4096`（差分求值帽 6144 内按需），
PY=/home/xkq/miniconda3/envs/train/bin/python，日志 `$HOME/logs/014/`，
≤10 分钟节拍落盘。核段派发时写进简报（0-5 代理段）。
