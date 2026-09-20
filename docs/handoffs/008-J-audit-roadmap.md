# 008 — J 链：外部战略评审的独立审计（只读）

## 简报（总控 → J1，2026-09-16 03:3x）

你是审计代理 J1。用户对项目做了一次外部 AI 战略评审（粘贴稿在
`/home/xkq/.zcode/tmp/paste-attachments/2026-09-16/pasted-text-20260916-032351-e44665e3.txt`，
先完整读它）。你的任务：**逐条核实评审论断在本仓库的真值**，产出采纳/驳回清单。
你不开卡、不写代码——裁决权在总控。

### 硬规则：全程只读

Read/Grep/Glob + 只读 Bash（cat/grep/git log/git tag/ls/stat；
sqlite3 只许 `file:...?mode=ro` 只读 URI）。不许 Write/Edit，不许起任何计算任务
（F2 占核 0-5、I1 占核 14-19，你在它们的夹缝里只能动嘴）。
唯一例外：本文件末尾"J 段"追加你的报告。

### 必读顺序

1. `AGENTS.md`（验收铁律——尤其铁律 1"真 lean 是唯一判据"与口径 A 的含义）。
2. `docs/DESIGN.md` §1/§2/§3/§7（目标、验收、范围、风险）。
3. `ARCHITECTURE.md`（当前状态段+真值表）、`README.md`。
4. 评审粘贴稿（上面路径）。
5. 抽查证据用：`engine/vm.cpp`（WHNF 通道规模）、`tests/test_check_e2e.py`、
   `scripts/run_cpu_regression.sh`（SUITES 表）、`lean_vm/step_driver.py`、
   `docs/decisions/`（ADR 序列，尤其 005/014）、`docs/plans/009~012`。

### 要核实的论断清单（逐条给 VERDICT：属实/部分属实/失实 + 证据 file:line）

A. **动机缺口**："DESIGN.md 讲了是什么/怎么验收/什么范围，但'为什么把内核搬进
   权重'没有正面回答（可微裁判、生成核查同基底）"。→ 通读 DESIGN.md 找动机段；
   没有就确认缺失。
B. **引擎 CHECK 是纯工程**："图侧已实现 INFER/DEFEQ/CHECK 且差分对真 lean 全过
   （84 例 INFER/DEFEQ + 15 例 CHECK），缺的只是 engine/vm.cpp 没实现这三任务的
   通道；可与 009-011 并行开卡 013"。→ 核实三点：(1) 图侧三任务是否真全绿
   （看回归 SUITES 与 handoff 记录）；(2) vm.cpp 到底缺什么（协议？token 编码？
   输出通道？估计改造面行数）；(3) "不依赖 009-011"是否成立——CHECK 语料 15 例
   走的 recursor 形态会不会被 brecOn/iota 缺口或 G3 注入协议卡住。
C. **首飞 demo 近零成本**："挑一条 rfl 型真实定理走 源码→elaborate→编码→权重引擎
   →accept，rfl 只走 is_def_eq 链，避开 009 未覆盖形态即可"。→ 查现有端到端链路
   还差哪几环（parser/elaborator 不在口径内，那"源码"这步实际是什么？现成
   harness 能拼出来吗？）。
D. **发布/背书债**："repo 零 star 因为没人知道；WHNF 34/34+差分文化已是该家族最强
   公开工作；transformer-vm 有 wasm-eval+MILP 调度器"。→ 核对本仓库事实部分
   （测试规模、对外文档），外部博客部分标"无法本地验证"。
E. **native_decide 信任边界**：评审说 Lean Zulip 会认真讨论这点。→ 读 README
   相关段，判断我们口径是否自洽（不是核对，是给总控的风险备注）。
F. **排序建议本身**：评审主张"CHECK 通道+首飞 > 语义完备性补完"。结合 AGENTS.md
   铁律与 ADR 014 排产，给出你看到的两派各自的依据链（不改你立场，摆证据）。

### 交付格式（写进本文件"J 段"）

每条：论断复述一句 → VERDICT → 证据（file:line 或命令输出原文摘录）→
若属实给"最小动作建议"（一句话，不展开方案）。最后一段"评审稿里我认为是噪音的
论点"列 1-3 条并说明理由。诚实优先：不确定就写不确定，不许脑补。

完工定义：六条全覆盖 + 本文件落盘。上下文吃紧就把已裁条目+剩余清单写完再退。

---

## J 段（执行记录）

J1，2026-09-16，全程只读（本段为唯一写入）。证据形式：file:line 或命令输出原文。

### A. 动机缺口

论断：DESIGN.md 讲了是什么/怎么验收/什么范围，但"为什么把内核搬进权重"没有正面回答。

**VERDICT：属实。**

证据：`docs/DESIGN.md` 全部 7 节（§1 目标 :7-12、§2 验收 :14-25、§3 范围 :27-42、
§4 实现原则 :44-56、§5 复刻范围 :58-80、§6 非目标 :82-87、§7 风险 :89-103）均为
what/how/scope；grep "motivat|why|动机|为什么" 在 DESIGN.md 与 README.md 零命中。
§1 只说"使 Transformer 的自回归前向传播执行内核的检查步骤"，未答"为何不用外面的
lean 二进制"。

最小动作建议：DESIGN.md §1 后补一小节"动机"，押注口径由总控/人裁（评审给的两条：
可微裁判、生成核查同基底——注意这两条是评审稿自己的发明，不是仓库既有立场）。

### B. 引擎 CHECK 是纯工程

论断三点：(1) 图侧三任务差分全绿（84 INFER/DEFEQ + 15 CHECK）；(2) 缺的只是
vm.cpp 协议；(3) 可与 009-011 并行开卡 013。

**VERDICT：(1) 部分属实；(2) 大体属实但有低估；(3) 部分属实。**

(1) 计数对、措辞过。回归实测原文（`/home/xkq/logs/008E_lead/reg_master.log`，
2026-09-16 00:57）：`=== CPU regression: 20 passed, 0 failed ===`，逐套件 rc=0。
但分层看：
- CHECK 15 例：Layer A（RefVM vs 真 lean）**且** Layer B（图 vs RefVM）各 15/15
  （`check_e2e.log` 尾行 `=== M4.2 end-to-end check: A 15/15, B 15/15 === OK`），
  即图→真 lean 有两段链拼接，成立。
- INFER/DEFEQ 84 例：**只有图 vs RefVM 一层**（`stepgraph_infer_defeq.log` 尾行
  `=== step graph vs RefVM infer/defeq: 84/84`）；对真 lean 的镜像只有 82 例且是
  **RefVM** 级（`ref_infer_defeq.log`：`M1 infer/defeq vs real lean: 82/82 (2 brec-sum
  cases skipped: no faithful lean mirror)`）。README:85-86 自己就写明"84 cases
  (82 have a real-Lean mirror)"。"差分对真 lean 全过（84…）"是把两层拼成一句话，
  审计口径下不算全绿表述。

(2) vm.cpp 缺项清单（核过源码，609 行文件）：
- 无 reject 通道：`engine/vm.cpp` 主循环 :579 只读 `done`；全文 grep 无 "reject"。
  而图侧输出维 `reject`/`reject_code` 已构造进权重（`lean_vm/build_vm.py:6152,6170`
  `out(reject,"o_reject")` / `out(reject_code,"o_reject_code")`；Python 侧
  `model/runner.py:273-280` 已消费）。引擎需加读两维＋按 `step_driver.py:89-97`
  合同发 T_REJECT(203)/T_HALT(204)（`expr/tokens.py:53-54`）＋终局输出判定。~20 行。
- 缺发射臂：`em_raw`、`em_link2`（含 link_flag/link_F2 字段）、`link_env`——
  `step_driver.py:100-124` 有、`vm.cpp:585-593` 无（grep em_raw/em_link2 于 vm.cpp
  = 0 命中）。INFER/DEFEQ/CHECK 路径会发这些臂（PI_CLO/level 链/binder-identity）。~40 行。
- 硬编码 token 值需与 sbin meta 校验一致（vm.cpp:440-441）。
- 驱动器形态：现 main 只有 WHNF 入口（init_state(term_pos)，:558）；run_infer/
  run_defeq/run_check 的前导帧注入不同（`step_driver.py:171-200`）。注意
  **`model/runner.py:357-398` 已有这三个任务的 Python 实现**（含 prefill），
  是现成的移植参照。合计估 100-200 行 C++，不动 sbin 格式。
- "协议没实现"这个定性基本准确，但评审没说 runner.py 已是半程。

(3) 不依赖 009-011：**通道本身成立，验收范围要收窄**。
- 15 例 CHECK 语料（`tests/test_check_e2e.py:43-70`）全在 toy env 上，形态为
  delta/beta/Proj/let/结构体 + Nat.add/mul（`test_olean_export.py:33-45`
  TARGET_DEFS），无 brecOn/drecOn/一般 iota → 009 缺口碰不到。✓
- G3/G6/G2-unsafe：CHECK 锚帧不带声明 kind，theorem 的 is_prop 门根本不在现通路上
  （`docs/plans/010-decl-injection-protocol.md` 目标 1-3；`003-D-wp7.md` 结案段
  "G3 需 step_driver 携带声明 kind"）。与 010 正交，评审自己也标了 xfail 挂账。✓
- 但两个真实风险评审没列：① mutation 16 例走的是 `lean_ref.run_check_oracle`
  （`test_mutation_reject.py:95`），其 oracle 是**带 elaborator 的 `example : T := v`
  编译退出码**，不是 raw kernel（`reference/lean_ref.py:142-150`、ORACLE.md :38
  明言 Meta-path）——引擎通道若沿用该判据，与铁律 1"内核判定对齐"有口径缝；
  应改用 `#KDECL` addDecl 通道（`lean_ref.py:447`，`test_defeq_branches_vs_lean.py`
  已是样板）。② 工作区实况：F2 正在改 build_vm.py（`005-F-iota.md` F 段在写、
  probe3.py 6.9GB 在跑），任何时点重编的 sbin 都混入 009 在途图改动——卡 013
  排期可以并行，但晋升基线必须等 F 链封版，否则违反真值表纪律。

### C. 首飞 demo 近零成本

论断：挑一条 rfl 型真实定理走 源码→elaborate→编码→权重引擎→accept，rfl 只走
is_def_eq 链即可。

**VERDICT：部分属实——方向对，"近零成本"失实。**

还差的环（逐个核过）：
1. 引擎 CHECK 通道不存在（见 B(2)）——这是前置，不是零。
2. "源码→elaborate→编码"没有自动管道。现有最接近件：`#KCHECK` oracle 内部做
   elaborate+raw check（`lean_ref.py:480-520`）；`olean_export.dump_env` 从真
   lean 导出闭包 ENV（:203）。缺一个把"具体 example 的 elaborated (type,value)
   对"自动喂进 Encoder/anchor 的胶水 harness——不在仓库里。
3. 真实定理的 recursor 形态赌注未验证。toy 语料刻意避开 brecOn
   （`reference/toy_env.py:134-141` P7.5c-3 pair-free 近似）；`tests/corpus/coverage.lean`
   （27 条 def/theorem，头注释自称端到端验收语料）**没有任何 Python 消费者**
   （grep coverage.lean 于 tests/scripts/*.py = 0 命中，ADR 005 记"保留备用"）。
   一条"真实小定理"（哪怕 `Nat.add_comm` 级别或带 List 的）是否踩到 F 链刚发现的
   三个 iotа/proj 缺口（`005-F-iota.md` 差距清单 G1-G4），现在没人知道。
4. universe-polymorphic 常量的 level 实例化靠编码期特化（VM_SPEC §12.7），
   对真实定理环境（Nat.add 全族带 u）是否全覆盖未验。

好消息（评审没提）：变异 reject 半边几乎免费——`reject_code` 已在权重输出里，
引擎加了 reject 读取后，mutation 走的就是真机器拒绝，比 Meta-path oracle 更干净。

最小动作建议：先按 B 打通引擎，再立一张独立的"首飞可行性探针"小卡（选例→人工
elaborate→RefVM 跑通→再谈引擎），不许把探针当交付。

### D. 发布/背书债

**VERDICT：本仓库事实部分属实；外部对照部分本地无法核实或存疑。**

- "WHNF 34/34"：属实。`engine_vs_refvm.log` PASS，回归脚本 :170 `[all 34 cases
  incl. pow since card 008]`，ARCHITECTURE 真值表同记。
- "差分文化已是该家族最强公开工作"：**无法本地验证**（比较性主张，需要家族全景）。
- "repo 零 star 因为没人知道"：star=0 属实（GitHub API：
  `{'stargazers_count': 0, 'forks_count': 0, ...}`，repo 公开）；归因是猜测。
  另有一个评审没说的硬事实：`pushed_at: 2026-09-05`——GitHub 上已 11 天无推送，
  本地 80 个 commit、56 个未提交改动。**对外快照远落后于 HEAD，发布前必须先推
  一次干净的 release 代。**
- 打 tag：本地与 GitHub 均零 tag/releases（`git tag` 空；API tags `[]`），评审这
  一步有靶子。但"当前组合是可复现的"要打折：README:61 仍写"98-layer, d_model=1904,
  511,178,304-parameter float64"，与当前真值（109 层 / d_model 6222 / sparse sbin，
  ARCHITECTURE 真值表）不符——对外文档自身就是过期状态，v0.1 之前得先修 README。
- "transformer-vm 有 wasm-eval+MILP 调度器"：属实（Percepta-Core/transformer-vm
  README :102 wasm-eval、`transformer_vm/scheduler/milp.py` 存在）。
- "transformer-vm (Tzamos et al., 2026)"（README:160 引用）：**存疑**——该 repo
  README 无作者/引用信息，归属 Percepta-Core，"Tzamos et al."本地找不到出处。

### E. native_decide 信任边界

**VERDICT：口径自洽，但只是文档层的自洽，代码层无机制。**

- 三处一致：DESIGN.md:78-80（视为 axiom + 文档声明）、README:115-118、
  KERNEL_COVERAGE.md:190（`K/type_checker.cpp:608-635 reduce_native`，超出覆盖、
  语料筛选 TBD）。与真内核行为一致（lean4 源码 :614,:762,:1101-1104 核实调用点）。
- 风险备注给总控：① 仓库里没有任何检测/标注机制——reduceBool/reduceNat/ofReduceBool
  在 ref_vm.py/build_vm.py 零命中；证明项里出现 `Lean.ofReduceBool` 轴心常量只会作为
  普通 axiom 类型检查通过，不会被打标。Zulip 上会被追问"你们怎么排除的"，答案目前
  只能是"人工选例外"。② 更普遍的同类问题：项目整体接受"经检验的 lean 二进制做的
  是 elaboration"这一前提（口径 A），native_decide 只是最尖锐的实例——对外叙事时
  两条最好合并成一个 trust-boundary 论述，比单讲 native_decide 更站得住。

### F. 排序建议（CHECK 通道+首飞 > 语义完备性）

不改立场，摆两派依据链。

支持评审方：
- ARCHITECTURE.md:65-67 自己把这行字挂在显式缺口："权重侧端到端目前只对 WHNF
  验收，CHECK/INFER/DEFEQ 的权重侧覆盖 = 无"——DESIGN §1 的产品定义是"前向传播
  执行内核检查步骤"，现状连成品判定都没从权重出过一次。
- 工程独立性证据强（见 B(3)）：15 例语料形态与 009/010/011 的缺口集合不相交。
- 里程碑价值：首飞句"第一条被神经网络权重核验通过的定理"是当前任何公开工作
  （含 transformer-vm，其演示对象是 WASM 程序而非定理检查器）没有的。

支持现行排产方：
- AGENTS.md 冲突裁决："验收与范围以 docs/DESIGN.md 为准"；DESIGN §5 把
  environment.cpp 全部声明加入检查（含 theorem is_prop）列为范围本体，
  §2 要求错误类别一致——五条接缝不收口，"与真内核一致"这句宪法承诺就不完整。
- ADR 014 是**人**的裁定（"以上全部都要完成，不接受'接缝/移交'作为终态"）并锁了
  执行序 008→出口→009→010→011→012；插卡在程序上等于推翻 9 月 15 日的人工决策，
  应由人重新裁，不由 agent 裁。
- 资源现实：F2/I1/G 三条链在途占核占内存（007 handoff：用户 ~11GB 训练 + F 探针
  6.9GB），再开第四条热路径违反"一个会话只许同时挂一个大 env 任务"的边缘精神。
- 评审方案的隐藏假设已被证伪一半：它假定 CHECK-from-weights 一旦打通判定即完整，
  但 theorem 类声明（G3）不通则"真实定理"这句话对外说不圆——首飞只能飞 def/example
  形，叙事强度打折。

### 评审稿里我认为是噪音的论点

1. **"你的验收纪律比绝大多数研究代码库严格""是目前这个方向上已知最认真的实现"**
   ——比较性赞美无判据，且与盘上事实有张力：84/84 那层是图 vs 自写 RefVM
   （B(1)），"分层差分表结构上无懈可击"忽略了 INFER/DEFEQ 图↔lean 直连缺失。
   这种话不该进采纳清单。
2. **"可微裁判"作为第一理由**——与本仓库宪法直接冲突：AGENTS.md 铁律 4 与
   HYBRID_ARCH 实测 fp16 全 NaN、bf16 直接错、fp32 是可用下限；softmax 分数
   1e9-1e10 量级下梯度数值上是垃圾。把它写成"产品定义"级别的押注（评审原话
   "押了 1，softmax 就不是 dev 玩具而是产品"）没有对应工程路径，最多算远期研究
   支线定位。
3. **数字/归属细节不可靠**：README:160 "transformer-vm (Tzamos et al., 2026)"
   本地无出处；评审称 dense 为"511M 参数 float64"（那是 pre-WP8 旧 artifact，
   当前真值是 24 亿参数 dense / 18MB sparse sbin）；"GPU_SPEED.md 该提优先级"
   ——该文档实测对象是已退役的 dense `.pt`（d_model 4374/71 层，GPU_SPEED.md:9-11），
   结论不能直接搬到稀疏引擎。引用评审稿时这类句子要过滤。

### 剩余清单

六条全覆盖，无剩余。不确定项已就地标明（"最强公开工作"、"Tzamos et al."归属、
真实 rfl 定理的 recursor 形态可达性）。

---

## 总控跟进裁决（lead3，2026-09-16 03:5x）

对 J1 六条逐条处置。两项宪法级提请了人裁，其余总控裁。

- **A（动机缺口）→ 人裁：采纳**。ADR 015 置 Accepted，DESIGN.md §1 末已补
  "动机"小节（押注"生成与核查同基底"为主、"可微裁判"明写为远期支线并附
  fp32 下限对冲）；README Verification layers 末加摘要段。§2 验收、§3 范围未动。
- **B（引擎 CHECK 通道）→ 人裁：插卡 013，排后段**。已立
  `docs/plans/013-engine-check-channel.md`，ADR 014 加修订段。J1 两条风险已入卡
  硬约束：①真 lean 直连判据禁走 mutation 16 例的 elaborator Meta-path oracle，
  一律 `#KDECL` addDecl 内核通道；②产物晋升基线必须等图侧封版。
- **C（首飞）→ 总控裁：接受 J1 的"部分属实"定性与动作建议**。不立卡、
  不在 013 结案前谈首飞；013 交付后再评估"首飞可行性探针"小卡
  （选例→人工 elaborate→RefVM 跑通→再谈引擎）。
- **D（发布/背书债）→ 总控核账**：README 旧 dense 数字（98 层/1904/511M f64）
  **已不在盘上**——J1 审计时点引用的该行属旧态，现 README:62-66 与真值表一致
  （109 层/d_model 6222/186,892 nnz/L4SV v2 稀疏），此条债已清。
  "Tzamos et al., 2026" 归属已按 J1 证据改
  为可核口径（Percepta-Core，上游无作者名单）。push/tag/对外 release 代=人工
  按键，收尾时提请；"该家族最强公开工作"类比较性主张不进任何对外文案。
  drecOn 的 README 口径修正（E0a：判据版本无此构造）等 F4 落建议后总控改。
- **E（native_decide 信任边界）→ 总控裁：记文档层债务，不建机制**。对外叙事
  时与"口径 A 接受真 lean 做 elaboration"合并为单一 trust-boundary 论述
  （DESIGN §5 末段已有事实基础）；语料筛选机制维持人工选例外现状，如对外被
  追问再立卡。
- **F（排序）→ 已由 A/B 两项人裁落定**：语义完备性主线（009→010→011→012）
  不变，013 插后段机动。总控不再自行偏离 ADR 014 修订后的排产序。

派单记录：F4（agent_b2fed284，background）03:5x 派发，任务书=005"F3 简报增补"
段逐字（F3→F4），落盘节拍 ≤10min 已入简报硬条款；派发后数分钟内 005 已见其
"F4 段"表头落盘，存活。lake build（pid 576111，核 14-19，进度 4542/8712 @03:52，
实占 ~12GB/可用 18GB）按裁决不杀，总控盯至完工后收编。本会话同时写盘代理数=1。

---

## 事故记录：04:14 客户端 OOM crash 与恢复段（lead 窗三，2026-09-16 04:2x）

### 亲验事实
- ~04:14±1 客户端 crash 级重启（zcode 全族新建；loadavg 15 分钟 33 → 1 分钟 3，
  swap 用过 3-5G）。F4 随 crash 阵亡，产出在 005 有盘上记录：a1/a2/a3 完成
  （含 G1 四载体推广钉板、eL2"快速错判非死循环"机制更正）、b 定位完成
  （F2 假设被否，真根因=方程编译 hAdd beta-redex 残留漏过 _norm_hbinop，
  修复取测试侧编码前 beta 归一）；b 实施、c1/c2、d、v 未完。图文件零污染
  （build_vm.py/tokens.py 仍 09-15 代，真值表未动）。
- lake build 已死（0 lean 进程，Mathlib.olean 未产，build.log 停 04:13、
  6985/8712≈80%，模块 olean 缓存在盘可增量续）。
- **双窗并发控制实锤**：04:0x-04:3x 间本文件与卡 013 盘上曾出现另一总控
  （lead2 窗）的记载（"G 04:04 已派发""I2 04:15:57 阵亡""lake 已回收"），
  现又不在盘上（006 G 段未动、step_driver.py mtime 2026-09-06、卡 013 为
  窗三 03:55 版）。两窗各自以为"唯一写者"、同改一套控制文档——本轮派单
  超量的放大器。处置需人：**关掉另一个 lead 窗，或明示留哪个**。

### 记账与参数（对以后所有派发生效）
1. 病因主犯=lake build 默认 20 worker 无封顶（曾见总 worker RSS 19GB 级），
   叠加多窗代理与总控灌入。窗三继承"勿杀"裁决后只抽查 RSS 不设进程组封顶，
   **失稳在主控，已记**。007/事故记录 2 早有同款记录（13GB+swap5G 击杀 I1），
   这次连客户端一起打死，教训升级：凡 lake/编译类，必须 `-j 4` + OMP=2 +
   进程组聚合 RSS>6GB 即 kill 全组，且与差分代理不同窗共跑。
2. 即刻冻结：不派任何代理、不起 lake，等人裁恢复。
3. 恢复顺序（人确认后）：F5 续 005（清单在该文件事故记录 5 末，探针 4GB 水位）
   → F5 结案后串行 G(010)/lake 重启二选一 → 011/I2/013 照 ADR 014 修订序。
4. 单一 lead 窗纪律入册：派单前 `pgrep -af zcode-cli` 数一下 lead 级会话进程，
   多于一个在干活就停手报人。

### 恢复执行记录（04:3x，人授权"随意关、其余你定"后，本窗单控）
- 双窗处置：实测 04:12 后对本仓库的写盘只有窗三；lead2（sess_ff013798）的
  agent 目录冻结在 03:40，crash 级重启后其 G/I2 代理全部死亡且无复活写痕
  ——**对窗已失能，不盲杀任何 zcode 进程**（现存 4 个 zcode-cli 里
  sess_2dcd56cc 是用户在桌面/experiment/wt050 的 Rust 测试窗，与本项目无关）。
  触发器替代杀进程：仓库任何非本窗写的文件变更 → 立即冻结并报人。
- lake 封顶（两段勘误，最终形态）：先试"枚举 -P3 单模块"（build2/3.log），
  **被实测证伪**：lake 把 `X.lean:o` 静默展开成整闭包作业集（单探针=2746 jobs），
  三槽并发实测 24 worker/24.3GB——每次 kill 还会留截断产物（本轮扫描 260 个
  kill-window 文件，全解析无损，无需清理）。根因：lake 4.33 无 -j、job 数
  取 `sysconf(_SC_NPROCESSORS_ONLN)`、无视 affinity。**正解=LD_PRELOAD sysconf
  谎报核数**（`scripts/lake_nproc_shim.c`，返回 3）：单条全量 `lake build`，
  实测 3-4 进程/3.3GB，依赖调度与竞争语义完全不变。现跑 **pgid=843828**，
  核 14-19，日志 $HOME/logs/012I/build5.log（04:53 时点 6332/8424，missing≈1200
  按 -3 并发 ETA ~1h）。杀法 `kill -9 -843828`；启动/看门狗规范见
  `scripts/build_mathlib_capped.sh`。wave/xargs 脚本已删（方法错误，教训入
  shim 头注释）。
- F5 派发（agent_956959b0，04:3x）：任务书=005 事故记录 5 的 F5 续跑清单
  （b 实施 (ii) → c1/c2 备忘录 → d 测试收编 → #1 ADR016 草案 → v 收尾），
  探针 4GB 水位、≤10min 节拍入简报。唯一写盘代理。
- 排产不变：F5 结案 → 串行 G(010) → H(011) → 013/I2 照 ADR 014 修订序。
