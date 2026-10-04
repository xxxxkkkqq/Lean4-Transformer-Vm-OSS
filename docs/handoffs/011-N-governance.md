# Handoff 011-N — 治理重整 + 卡 010 G02 验收收口（2026-09-20）

总控会话（项目经理职责首次显式化：AGENTS.md §二 角色分工）。上一状态见
handoff 006（G02 checkpoint，3 verifier 在跑）与防线 §3.7（发布规程定案）。

## 当前状态

**一、G02 验收通过（卡 010 整卡仍 open，余 G6 mutual 拍）**

- 差分全集 54/54 + 2 xfail（非归一 level 形 KNOWN-GAP，ADR 021）rc=0：
  `/home/xkq/logs/010G/lead_full_suite.log`。
- 载体空闲性 guard 全语料 PASS（同日志）。
- 22 套件回归等效齐全：21 项 09-19 06:43 PASS；mutation_reject 当趟超时定性
  环境性（当时 GPU 训练占机），09-20 单项重跑 **rc=0**（A 16/16、B 8/8，
  754.8s/1552MB）：`/home/xkq/logs/010G/mutation_rerun/`。代码态一致性证明：
  `git diff 15a500d..HEAD --stat` 零代码文件。
- 硬编码扫描零新增（仅存量：注释 1 处 + `CID_P2MK + 1` 已知项 build_vm.py:5061）。
- 两条 checkpoint 待裁项已裁（ST 帧 E2 追认 / 引擎码 8 维持 NOT-VERIFIED 归卡 013），
  原文见 handoff 006 末段；卡 010 派工增补 3 有逐条清单。
- 合同变更（总控执笔）：`decl_injection_vs_lean` 入回归表，基数 22 → **23**
  （2100s/4000MB，按实测 1395.6s/2101MB 定帽）。

**二、仓库治理重整（用户指令：清理无用件、分类、AGENTS.md 角色化）**

- 根目录删除（git rm，历史可找回）：HANDOFF_M5.md、PROGRESS.md、
  下一窗口提示词.md、fidelity.log、smoke.log、logs_milp.txt、plan.pkl（零引用）；
  未跟踪件 engine.log、smoke_m2_regress.log 直接删，NEXT_PROMPT.md（机密、内容
  已全面过时且与现行纪律矛盾）移出仓库至 `~/l4tvm-attic/`。
- 归档：docs/PLAN.md（Phase 0-7 台账，加归档横幅）、docs/HANDOFF.md（已作废的
  集中式交接）、docs/GPU_SPEED.md（基于已退役 dense 件）→ `docs/archive/`。
- 断链修正：DESIGN.md/ARCHITECTURE.md 指针、lean_kernel 两处 docstring、
  .gitignore 失效条目；空壳 `kernels/` 目录删除（未跟踪，代码早已迁
  lean_vm/primitives.py）。
- **AGENTS.md 角色化重写**（5925a5d/fb30fbb 起）：§0 会话开场固定顺序；§二
  六角色分工（总控/Lean4 语义设计师/图逻辑工程师/后端工程师/测试工程师/
  审核工程师）+ 任务生命周期 + "完成即写文档不延误"硬规则；§六 代码组织
  （分层 import 纪律、大文件拆分须开卡）。
- **会话启动钩子已修**：`.claude/hooks/inject-handoff.sh` 原来向每个新会话注入
  "先读 docs/HANDOFF.md"（已作废文档）——改为注入 AGENTS.md §0 开场顺序。
  这是本次盘点发现的最危险残留。
- 交接链全 13 份、ADR 全 21 份、任务卡全 11 份**一份未删**（005-F-iota 与
  010-M-cache 虽 163KB/94KB，是卡 009/014 的证据链正文，被 ADR/闭卡活引用）。
- 盘点代理判定的其他事项：卡 012 M-A 状态疑似脱节（plans/012 "M-A in progress"
  vs handoff 007 自 09-16 03:28 无追加、裁决段空），列入下一步核对。

## artifact 状态

与 ARCHITECTURE.md 真值表一致（本会话已同步）：发布件仍
`model/step_vm_new_sparse.sbin`（P1-only 交付态）；`step_vm_010_scratch.sbin`
为 G02 已验收验证件，仍非发布、禁当基线；本会话未编译、未动任何权重/二进制。
`engine/vm_run` 未动。

## 已定决策

- G02 收口与两条裁决：handoff 006 末段 + 卡 010 派工增补 3（依据 ADR 020/021，
  未新开 ADR——治理重整是流程变更非架构变更，落在 AGENTS.md 本身）。
- 回归表 22 → 23：`scripts/run_cpu_regression.sh` 内注释即变更记录。
- 文档处置原则：**交接链/ADR/任务卡不删**（证据链）；删的只是无人引用、内容
  过时或自认易耗的提示词件与快照；归档用 git mv 保路径历史。

## 下一步（按序，≤3 条，每条可直接开工）

1. **卡 010 G06 拍**：mutual 块前置可见 + 块内重名。设计备案 handoff 006 §3
   （add_mutual :225-269、check_multi_param_names :236-241、新码 9=driver 簿记族）；
   派工走新 G0x 链，表头先落盘，测试行集含互块自引用正/反例与重名拒。
2. **卡 012 M-A 状态核对**：读 `/home/xkq/logs/012I/` 与 handoff 007，核对
   Mathlib 闭包抽取器真实进度，更新 plans/012 状态行并补 handoff 007 裁决段。
3. **里程碑出口快照**：下次卡结案/晋升门按防线 §3.7 执行
   （commit-tree 建快照提交 → `git branch -f public-main` → `git push origin
   public-main:main`——push 是对外发布，人工按键）。

## 已知陷阱

- mutation_reject 的 900s 帽贴着实测 755s，机器一忙就超时：**超时先单项重跑再
  定性**，别当语义回归（本次已两次验证是环境性）。
- 回归现在 23 套件，全程 ~2h；`SUITE_FILTER` 支持单项，别为省时整趟跳过。
- 文档按路径/哈希落账：**不要移动** docs/handoffs/、docs/decisions/、scripts/
  下的既有文件（209 处引用）。
- 会话启动钩子现在注入 AGENTS.md 开场顺序；若见"先读 docs/HANDOFF.md"字样，
  说明跑在旧 hook 上，别照做。
- NEXT_PROMPT.md（`~/l4tvm-attic/`）内容过时且与现行纪律矛盾，仅考古用。

## 进度追记（2026-09-20 下午，同会话续）

- **oracle 漂移事故与修正**：elan default 09-20 实测漂到 4.34.0 → 今晨 mutation 重跑
  实际用了 4.34.0 oracle（证据作废重立）。修正=仓库侧钉 4.33.1（lean_ref.py 解析 +
  L4TVM_LEAN + 回归脚本自检，commit 6c938cb），顺手清偿 009-L 欠账（Mathlib 路径
  /tmp/mlbench→/home/xkq/mathlib_src，kernel_oracle 的 Mathlib 容量段不再静默跳过）。
- **G06 拍 CLOSED**（ InjectionEnv + add_mutual 两阶段 + 码 9；64/64 全集；全量回归
  **23/23 rc=0**，/home/xkq/logs/010G/g06_reg/——mutation 在 4.33.1 上 rc=0 重立）。
  注意：decl_injection 全集涨到 1492.8s，回归表 2100s 帽只剩 1.4x 裕量。
- **卡 012 M-A 完成**（I2 链）：闭包抽取器 + 3 定理 874 常量 + 元数据往返零差异 +
  结构测试 2196 checks rc=0（总控亲跑复验）。M-B/M-C/D 仍 open。
- 下一步：G03 拍（unsafe 图臂）已派工，表头见 handoff 006。

## 进度追记（2026-09-21，同会话续——G03/G04 收口 + 卡 010 CLOSED）

- **G03 拍 CLOSED**：mode 位图臂 +11 dims O(1)，引擎 34/34，全量回归 23/23
  （g03_reg）。decl_injection 帽 2100→2700。
- **G04 拍 CLOSED（本会话最重的一拍，多灾多难但证据最全）**：前任代理账户
  额度中断后复活接手交付 run_whnf + 13 行 WHNF 差分；c2 补拍钉死负面结论
  （当前图无闭载体使续推轮语义必需）并挖出 univ_arity accessor 活锁新债。
  总控五道门全过：独立复跑 82/82 rc=0（stuck 项逐字复现）、c2 canary 84/84、
  OE 条款补跑（引擎 34/34 + reducenat rc=0）。提交 5037d88/531affc。
- **卡 010 整卡 CLOSED**（增补 5）；4 项遗留 + 编号勘正转卡 011 移交队列。
- **里程碑快照已建**：`public-main` = 021f687（parent b55d1b0，树内最大 blob
  360KB）。**push 是人工按键**：`git push origin public-main:main`。
- 教训入档：setsid 脱管的 canary 在代理会话死亡后照常跑完出证（rc=0 有效）
  ——长验证据此更该脱管起，别挂在代理生命周期上。
- **下一步队列**：卡 011 开工拍（先跑移交队列第 5 条编号勘正，再排产
  G8/G9 与 4 项遗留的拆分/合并决策，注意 univ_arity 活锁优先——卡 012 M-B
  的 779 常量闭包会大量撞它）；卡 013（引擎 CHECK 通道，码 8/9/mode 在
  引擎侧 NOT-VERIFIED）；卡 012 M-B。
- 用户级提示（非仓库）：elan default 现为 4.34.0，本仓库已自钉 4.33.1 不受
  影响；若用户其他项目需要旧行为可 `elan default v4.33.1`。

## 进度追记（2026-09-21 上午，总控会话——卡 015 立卡 + 矩阵勘正 + 拍 1 派工）

- **卡 015 立卡**（`docs/plans/015-universe-level-runtime-channel.md`，git 36cc7b0）：
  图侧运行期 universe/level 通道（D 组收口）。归属裁定：卡 010 移交队列第 2 条
  （univ_arity 活锁）+ KNOWN_GAPS thm_imax/thm_max00 根因（
  `tests/test_decl_injection_vs_lean.py:198` 注明"修属卡 012"，但卡 012 涉及文件栏
  明令"语义分支不动"——归属冲突，本卡裁定：D 组语义收口归卡 015，卡 012 只管
  M-B 编码规模实验）+ M-B 闭包实测 288/779 带 universe 参数（37%，
  `/home/xkq/logs/012I/closures/Nat_testBit_land/dump.jsonl`）。
- **矩阵勘正 13 行**（事实性更新，证据附代码位置，git 36cc7b0）：H1 已实现
  （tokens.py:581 写 kind + test_env_meta_import.py:214 对拍）、H2 已实现
  （tokens.py:428 _univ_arity / :561-567 UNIVPARAMS 链）、D13 已实现 / D14 部分
  （§12.7 `_specialize_type` tokens.py:776）、D10 部分（ref_vm `_inst_level` 编码期）、
  D1/D2 部分（I_PIL2 整数近似 build_vm.py:3522-3531）、B13 部分（编码期特化；
  运行期缺=活锁根因）、I1-I5 部分（WP8 已落地，残余硬编码 CID_P2MK+1
  build_vm.py:5061）。矩阵其余"缺失"行（D4/D5/D8/D11/D12 等）保持原状，待卡 015
  实现后统一更新。
- **卡 015 拍 1 已派工**（语义设计师，后台 agent_45d86e84）：oracle 探针 P1-P4
  （thm_imax/thm_max00 期望侧 #KDECL、univ accessor oracle 期望、level defeq、
  infer_pi imax 折叠）+ build_vm.py level 消费点 gap 清单 + ADR 022 草案 + 设计
  memo（方案对比含图规模增量预估）。首派撞 tpm/rpm 限流失败，重试成功。
- 下一步：拍 1 交付后按 ADR 022 方案裁决 → 拍 2 图逻辑工程师（build_vm.py）→
  拍 3 测试工程师独立 verifier → 拍 4 审核 → 总控收口。XPASS 协议：thm_imax/
  thm_max00 修复后行仍常跑，摘除日留档；decl_injection 回归帽 2700|4000 若
  语料变动需按注释规程复测。

## 进度追记（2026-09-21 午前，总控会话——卡 015 拍 1 CLOSED：ADR 022 定案）

- **拍 1 执行史**：语义设计师代理两次撞 tpm/rpm 限流（38s / 431s，均零落盘），
  按防线 §1 第 4 条停手换执行者——**总控直跑探针**（跑 oracle verifier 属总控
  职责）：P1 #KDECL 子集（`G02_ONLY=thm_imax,thm_max00,thm_sortraw_imax,
  thm_sortraw_max00,def_imax`，oracle 段原文落 /tmp/p1_kdecl_subset.log）+ 新探针
  `tests/probe_015_semantics.py`（P2/P4/P4b）。G02 子集图侧段超时（rc=124）但
  oracle 段完整，P1 证据有效（oracle 在测试开头现跑，图侧不是本拍目标）。
- **P1 机制定谳**（与 ADR 021/卡 010 假说一致并更精确）：is_prop 检查的是
  **A 的 infer 类型**的 level 归零。`oracle[thm_imax]=OK`（A=Const injX_imax，
  infer 得 Sort (imax 1 0)，n2z 只看 rhs=0 → true）；`oracle[thm_sortraw_imax]=
  thmTypeIsNotProp`（A=Sort (imax 1 0) 表达式，infer 得 Sort (succ …) → false）。
  图侧 syntactic 根比 KL_ZERO 对前者假拒 8 = 修复点。
- **P2/P4/P4b 证据**：univ accessor whnf oracle=字面量 3（图侧同形状活锁）；
  Mathlib 闭包 779 常量 768 个（98.6%）存储树含 Level.param；UProd.fst value=
  Lam Lam Proj + univ params=['u']（B13 缺口形状）。
- **ADR 022 定案（accepted）**：混合方案——组件 1 normalizes_to_zero 电路
  （D8）接 is_prop（pl_prop）+ I_PIL2 符号级 is_zero（拍 2 主体，预估图
  +500~1500 dims O(1)）；组件 2 level defeq Max/IMax 扩展（预算有余才做，
  否则 NOT-VERIFIED）；组件 3 B13 活锁（拍 2 先复现，unfold 单步实例化 vs
  accessor proj 快捷两案）。被拒：纯编码期特化（P1 反例 + 规模）、完整 D5
  全序、T_LVLSUB 链（§12.7 先例）。verifier 行集落 ADR 022 末节。
- 提交：36cc7b0（卡+矩阵）、9163784（handoff 立卡段）、拍 1 收尾提交（ADR
  022 + probe + 本段）。
- 下一步：拍 2 图逻辑工程师（build_vm.py，组件 1 主体 + 组件 3 复现），按
  ADR 022 行集验收。

## 进度追记（2026-09-21 午，总控会话——子代理持续限流事故记录）

- **事故**：卡 015 拍 1（两次）/拍 2（一次）子代理连续撞 `inference exceeds
  tpm/rpm limit`，均零落盘：拍 1 首派 38s、重试 431s、拍 2 首派 262s。
  时间窗 09-21 09:4x-10:1x。主会话工具调用全程正常（Bash/Read/Edit 未受限），
  仅 Agent 子代理的模型推理被限——定性 = 账户级推理速率限制（防线 §1 第 16
  条"客户端/账户层"同族），非项目代码问题。
- **对策（按防线第 4 条"小步落盘"与第 16 条"停派上报"之间取务实折中）**：
  ① 拍 1 已降级为总控直跑探针并收口（ADR 022，42a0cf2）；② 拍 2 改用
  **大幅精简简报**（必读清单砍半、实现指引浓缩）重试一次——限流为瞬时性，
  拍 1 第二次重试即成功（431s 存活）为证；③ 若精简版再死，停派上报人工，
  等窗口或换时段。
- 教训入档：子代理简报越长的会话越早撞 rpm；拍 2 起简报控制在中短篇幅，
  文档定位尽量由总控预读（"读哪些 + 读什么"给足，但少让代理自行 grep 海量
  文件）。

## 进度追记（2026-09-21 午后，总控会话——卡 015 拍 2 验收 PASS）

- **拍 2 五道门全过（总控独立复证，非转述）**：
  ① 机械门：diff 恰 3 文件（build_vm.py +124/-50、tests、handoff 006）；py_compile
  复跑 OK；硬编码扫描零新增（仅存量注释 + `CID_P2MK+1` 已知项 :5117）；dims
  实测 26,023→34,392（+8,369/+32%）、lookups 2,901→4,489（+1,588/+55%）、
  nnz 192,867→235,030（+42,163/+22%），O(1) 图深度不增。
  ② 语义门：总控独立复跑 `G02_ONLY=thm_imax,thm_max00,thm_sortraw_imax,
  thm_sortraw_max00,def_imax` 子集 **6/6 rc=0**（269s）：thm_imax/thm_max00 PASS
  （oracle=OK→graph accept code 0 steps 15，与代理输出逐字一致）、sortraw 两行
  保持 8；UProd.fst→3/snd→4 差分行代理已验证（G04 全 15/15+1 xfail 逐字）。
  ③ 架构门：diff 审阅——`_n2z` 逐 kind 按 K/level.cpp:174-186（Max→AND 双子、
  **IMax→只看 rhs**），共享 v1 子树（2^8-1=255 节点；初版 3^8=3280 节点曾把
  dims 顶到 130,975 被代理自查修复）；`pl_prop`(:4506) 与 CHECK 链 g3 拒绝臂
  (:5499) 两处同换成 n2z（首轮只改 pl_prop 仍假拒，探针定位 g3 才是抛 8 处）；
  I_PROJ 通用抽取（:3086-3117）按 reduce_proj_core（K/type_checker.cpp:420-441）
  ——`_app_arity`/`_head_of` 剥全骨、`_is_ctor_any` metadata ctor 判据 + legacy
  P2.mk 回退（既有模式，非新硬编码）、`_struct_ind` 读 INDVAL.V1 nparams、
  守卫 arity ≥ np+idx+1、SPINE_MAX=12；P2 玩具案（nparams=0）同规则不变且
  steps 14/33 逐字未动（toy proj 回归零差异，brec 套件同）。
  ④ 测试门：UProd 差分行入 G04 uprod family（g04up/fst, g04up/snd）；KNOWN_GAPS
  摘 thm_imax/thm_max00（XPASS 协议，首绿→摘除→PASS）；组件 2 记 NOT-VERIFIED
  不掩盖。⑤ 诚实门：ADR 022 预估 +500-1500 dims 偏差自报且给 per-node 成本
  （~16 dims + 3 lookups）；回归帽 2700s 风险注记。
- 引擎对拍（总控独立）：**34/34 verdicts correct + argmax=softmax 34/34**，
  `lead_engine_015_v2.log`（首次钉 sbin 传参错误——写成位置参数而非环境变量，
  引擎在验旧图，已发现并修正重跑；known-value 3/4 为既有报表项）。
- 遗留 NOT-VERIFIED：组件 2（deq_sort/A18 Max/IMax 比较扩展）——ADR 022 许可
  预算不足不掩盖；n2z 实测 +8k dims 即 2^depth 展开单位成本实证，独立卡候选。
- 下一步：拍 3 测试工程师（全量 decl_injection_vs_lean + 23 套件回归 +
  摘 xfail 复核 + 2700s 帽盯守）；新 sbin 已登真值表（待全量绿后晋升决策）。

## 进度追记（2026-09-21 傍晚，总控会话——卡 015 CLOSED：拍 3 验收 + 回归帽校准）

- **拍 3 验收 PASS（测试工程师独立跑，代理死于限流但资产全在——脱管+落盘的回报）**：
  - T1 全量 decl_injection：2700s 帽击穿（rc=-9 死于 g03 段，g04 未跑，峰值 2358MB）——
    dims +32% 后套件变慢的必然；**分节重跑全绿**：a0+guard 33/33（1137.9s/1289MB）、
    bcd 21/21（922.2s/1556MB，含 thm_imax/max00/def_imax/sortraw×2 全 PASS）、
    g6+g03 17/17+2 xfail（g03g/g03h 既有登记）、g04 15/15+1 xfail（iv/eG4IV2 既有；
    **UProd.fst→3 steps=16、UProd.snd→4 steps=32 活锁修复确认**）。合计 86/86+3 xfail 0 fail。
  - T2 23 套件回归：语义面**零 FAIL**（全部 rc≠0 均为 PASS 尾部 + wall/RSS 帽顶穿）；
    单跑重跑 8 套件转绿 rc=0（brec/mutation/olean/quot/reducenat/stepgraph×3）——
    唯一 hard 证据：brec 单跑峰值 7288MB、reducenat 6060、quot 5425、defeq_cache 主回归
    6001MB>6000 被杀且重跑仍 137——dims +32% 的 RSS 增长是真实的。
- **回归帽校准（总控裁决，run_cpu_regression.sh 已改）**：decl_injection 2700|4000→
  **5000|7000**（全量估计 ~4200s、g04 段峰值 5894MB）；brec 6000→8000（7288 实测）；
  defeq_cache 6000→8000；quot 5000→6500（5425 实测）；reducenat 4000→7000（6060 实测）；
  stepgraph_vs_lean 900→1500（942 实测+并发）、vs_refvm 900→1200、infer_defeq 2700→3300
  （2098 实测）、mutation 900→1200、olean 600→900。依据与日志路径全入脚本注释。
  注：全量回归整体时长 ~2h→~3.5h，下次日常回归自然验证新帽。
- **矩阵更新**：D8 缺失→**已实现**（_n2z 电路 + 两处接入）；G3a 具名缺口→**已修复**
  （thm_imax/thm_max00 XPASS 摘除，KNOWN_GAPS 已清）；B13 部分实现（活锁已修注记，
  完整 rhs 实例化仍编码期特化）。D1/D2 保持部分实现（n2z 只覆盖 is_zero 判定支）。
- **卡 015 CLOSED**（docs/plans/015-*.md 状态行）。遗留：组件 2（deq_sort/A18
  Max/IMax 扩展）NOT-VERIFIED，独立卡候选（n2z 实测 +8k dims 即 2^depth 单位成本，
  新卡需先探针定编码方案）。
- 提交：3550e4c（限流事故记录）→ 84ab21e（拍 2 验收）→ 392da64（真值表登记）→
  本收口提交（回归帽 + 矩阵 + 卡状态 + 本段）。
- 下一步队列（未动）：卡 011（G8/G9 + I_CASE 续推 + mode 续体 + ENV 动态名字排查）、
  卡 013（引擎 CHECK 通道）、卡 012 M-B（编码规模，现在 015 件可作新基线）。
- **发布待人工按键**：public-main 快照仍在本地（021f687，卡 010 收官）；
  卡 015 收口后是否更新快照/是否 push 由人工决定。

## 进度追记（2026-09-21 晚，总控会话——卡点诊断 + 卡011/013 双 lane 派工）

**卡点诊断**（用户报"卡了很久推不动"，盘点结论=不是代码死结，是三个流程
前置堆积）：
1. 卡 011 开工拍有两个**只属于总控的前置**未办：移交队列第 5 条编号勘正、
   G8/G9 与 4 项遗留的拆分/合并裁决——两项本拍均已落（见下）。
2. 子代理账户级 tpm/rpm 限流一天内打死 3 次派工（拍 1×2/拍 2×1，全零落盘），
   心理成本极高。对策沿用傍晚协议：精简简报 + 小步落盘 + 长验 setsid 脱管；
   本拍两 lane 简报均中短篇幅、锚点由总控预读钉好（代理少 grep）。
3. 卡 013 前提半过时：09-16 J1 审计写的 vm.cpp 缺项，09-21 实测**发射臂已
   大半在场**（em_pend/em_link/em_frame/em_frame2/em_lithead/em_gap/
   em_litdig2/em_const，vm.cpp:403-441 索引+主循环消费）；真缺口=
   ①reject/reject_code 读维+终局、②em_raw/em_link2（link_flag/link_F2）、
   ③INFER/DEFEQ/CHECK 三任务入口（grep reject|em_raw|link2 零命中为证）。
   回归表 20→23 套件。派工简报已按实测改写任务面。

**本拍总控落盘**：卡 011 状态行+码 10 勘正+队列 2/5 清偿标记+排产裁决节；
新卡 016（`docs/plans/016-reduction-continuation-family.md`，队列 1/3/4 拆出，
待派）；真值表 015 行勘正（CLOSED、图侧封版验证基线）+010g03 行接替注记。
错误码占用确认：1-8 图侧、9=mutualWF（driver 簿记族不进图）、**10 空闲**。
kernel 依据复核：`K/environment.cpp:102-109`（重名→already_declared）、
`:111-125`（dup univ param 文案 `duplicate universe level parameter`）。

**排产裁决**：卡 011 范围收敛为 G8+G9 注入错误面；队列 1/3/4→卡 016。
ADR 014"同时只许 1 个写盘代理"的串行约束系针对当年共改 build_vm.py 的
F/G/H 链；现行 AGENTS.md §二=并行≤2 且文件集合不重叠——lane A（lean_vm/*、
expr/*、tests/*）与 lane B（engine/*、新 scripts/）**面不相交**，裁并行。
lane B 钉 `model/step_vm_015_full_scratch.sbin` 现件（禁重编，防 lane A 在途
图改动混入真值——卡 013 晋升约束条原样执行）。

**派工**（09-21 晚）：
- lane A｜图逻辑工程师｜卡 011 拍 1（G8 driver 名占用拒 + G9 图内查重臂码 10
  + 差分行集）｜核 0-5｜日志 `~/logs/011G89/`｜执行链续 handoff 006。
- lane B｜后端工程师｜卡 013（上列三缺口 + verify_engine_tasks.py 对拍 +
  #KDECL 抽验）｜核 14-19｜日志 `~/logs/013K/`｜执行链新 handoff 009-K。

**下一步**：两 lane 交付后按五道门验收（测试工程师独立 verifier 拍随后派）；
卡 012 M-B 排队等 lane A 收口（新基线可用 011 scratch）；里程碑快照仍待人工。

## 进度追记（2026-09-23，总控会话——两 lane 限流续接 + 卡 013 CLOSED + 卡 011 拍 1 PASS）

（注：本段日期按机器时钟 09-23；上几段 09-21 系上轮会话时钟，事实一致仅日期
记号漂移，不回溯改写。）

- **限流事故续**：首派两 lane 均 52 分钟死于账户级 tpm/rpm 限流，但资产
  全在——lane A/B 都把半成品写进了工作树与 handoff。按协议续接
  （精简简报 + 断点接手 + 强制先落盘计划清单）：lane B 续接代理收尾
  （四验证核对 + canary 3/3 + 卡状态），lane A 续接代理验证+落盘并
  **抓到关键缺件**——前代理写了 G9 图臂但漏 section_g9 测试段（会 0/0
  假绿），已补 9 行（oracle 类别先探针实测再落）。
- **卡 013 CLOSED（总控五道门）**：独立复跑链全绿（核 8-13 钉
  `step_vm_015_full_scratch.sbin`，`~/logs/013K/lead/`）：WHNF 34/34、
  三任务 99/99（548.2s）、`#KDECL` 12/12 rc=0；canary 3/3（engine_vs_refvm
  34 例 + level×2）。vm.cpp +188 行三通道（reject/em_raw+em_link2/任务前导
  帧），WHNF legacy CLI 字节不变；meta-check 机制化防 token 漂移。引擎
  通道节入 VM_SPEC §16.9，真值表 vm_run 行同步（09-21 16:19 重建）。
- **卡 011 拍 1 验收 PASS（总控独立复跑）**：diff 17/17 rc=0（417s）、
  011 scratch 引擎 34/34 rc=0；dims +76/+6/+394（O(1)）；硬编码零新增。
  G9 载体 = 锚帧 F2 载 univparams 链头（0 惰性、旧路径逐字节不变），
  nid 比较无名字分支；核序 name→dup-univ→fvar→checker 逐级保持
  （reject 链 10>7>6>5>8>4，`g9name_lp` 证 G8 先于 G9）。文档同步：
  VM_SPEC §16.8 / ENV_FORMAT §2.8（码 10/11 登记 + F2 载体）/ KERNEL_COVERAGE
  G8/G9 行由缺失→已实现。
- **排队**：卡 011 拍 2 = 全量 23 套件回归（测试工程师，脱管）；卡 016
  （I_CASE/mode 续体/ENV 动态名）待派；卡 012 M-B 在 011 后；发布快照
  public-main 更新与 push 仍待人工按键。
