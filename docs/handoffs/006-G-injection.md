# 006 — G 链：卡 010 声明注入协议改造（step_driver 属主卡）

> 派工前状态：本文件先放简报；G 的执行记录追加在"G 段"之下，总控裁决最后追加。

---

## 简报（总控 → G，2026-09-16）

### 你是谁、在链条哪一环

你是开发代理 G，任务卡 `docs/plans/010-decl-injection-protocol.md`（先读）。
ADR 014 排产第三卡：F 链（卡 009，brecOn/drecOn）结案后派发。你解锁 D 链五条
"架构不可表达"接缝中的三条：**G3 theorem is_prop、G2-unsafe 先注册后检查、
G6 mutual 块前置可见**。G8/G9 留给卡 011，**不许顺手做**。

### 必读顺序

1. `AGENTS.md` 全文（验收铁律 1-5、机器纪律、文件所有权、完工定义）。
2. 本简报 + `docs/plans/010-decl-injection-protocol.md`。
3. `docs/decisions/014-scope-expansion-all-remaining.md`（排产依据）。
4. `lean_vm/step_driver.py`（200 行，`run_check(decls, max_steps)` 是改造对象）。
5. `docs/handoffs/003-D-wp7.md` 的 D2 段（CK_* 通道、G10 门、reject 链
   build_vm.py:6053 优先级 7>6>5>4、#KDECLMSG 机制的出处）。
6. `tests/test_check_e2e.py` 与 `tests/test_defeq_branches_vs_lean.py`
   （前者是你的 must-stay-green 主消费者；后者的 `Kernel.Environment.addDecl`
   消息通道 #KDECLMSG 是你错误类别判据的复用样板）。
7. `docs/ENV_FORMAT.md` §2.3、`docs/VM_SPEC.md` §16（你要同步的两处）。
8. 内核权威（只读）：`/home/xkq/lean4/src/kernel/environment.cpp`
   :192-209（theorem is_prop）、:160-190（unsafe else 支）、:225-269
   （add_mutual）、:236-241（check_multi_param_names）。行号以该文件为准，
   与 4.33.1 二进制不一致时以二进制实测为准并记录。

### 为什么归你而不是图侧卡

三条接缝的共因是**注入侧信息缺失**：driver 单遍 ENV、不带 decl kind、
后注册者对先注册者不可见——图里没有"注册前缀"这个数据，图侧写不出分支。
解法在 driver：按内核 `add_*` 家族语义逐条/逐块注入、失败回滚、
把 kind/unsafe 标志作为数据带进 ENV 前缀。图侧至多配新错误码链。

### 硬约束（越界=FAIL）

- **只许改**：`lean_vm/step_driver.py`（属主）、`lean_vm/build_vm.py`
  （仅错误码/新链最小配合）、新 `tests/test_decl_injection_vs_lean.py`、
  `docs/VM_SPEC.md` §16、`docs/ENV_FORMAT.md`、`docs/KERNEL_COVERAGE.md` G 行、
  本文件、`docs/decisions/` 新 ADR（错误码优先级是你必须落的决策）。
- **禁改**：`expr/tokens.py`（除非编码必须，须先在本文件写明理由）、
  `engine/*`、`compiler/*`、`model/*`、`lean_vm/ref_vm.py`（冻结）、
  `scripts/*`、`ARCHITECTURE.md`、`README.md`、`lean_kernel/*`、
  既有 tests（只读参照）。不许 git commit/add。
- **API 兼容红线**：`StepDriver.__init__` / `step` / `run_check` 的既有签名与
  默认语义**不得破坏**——回归里 stepgraph_vs_refvm、stepgraph_vs_lean、
  check_e2e、datadriven_env、reducenat_graph_vs_lean 五个套件直接构造
  StepDriver。协议扩展走新增参数（带默认值）/新增方法，旧调用路径逐字节不变。
  做不到就停手写 ADR 等人裁，不许硬改消费者。
- 新错误码与 reject 链优先级：现链 7>6>5>4（build_vm.py:6053 附近）。
  你的新码加在链上时优先级排序**必须**给出内核引用（哪条检查先于哪条），
  并同步 ENV_FORMAT + VM_SPEC；卡 011 会接着往上加码，把最终链形写进 ADR。
- 判据 = 真 lean（`~/.elan/bin/lean` v4.33.1）`addDecl` 抛的消息类别，
  逐例差分；ref_vm/自写 driver 只是开发迭代。**语料不得含答案**。
- 环境是数据：kind/unsafe/mutual 块长都走 ENV 元数据，不得按常量名写死分支。

### 反馈回路与机器纪律

- 差分测试用最小 env（几十常量，写法照 test_defeq_branches / test_quot 的
  `*_DEFS` 模式）。每次动 step_driver 立即跑 check_e2e + defeq_branches
  两个 canary（约 900s/1800s timeout 级，别拿全量回归当迭代器）。
- 长任务：`setsid nohup env OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u <cmd> > $HOME/logs/010G/xxx.log 2>&1 < /dev/null &`，
  起后立刻 `ps -o pid,rss,etime -p <pid>` 抽查，RSS>6GB 主动杀。禁止 `| tail`。
  master 日志放套件目录外。pkill 先 `pgrep -af` 看清防自杀。
- 用户 ~11GB 训练任务在跑（/home/xkq/train，勿动勿杀），本机可用约 19GB。
- 与 F 链串行：F 未结案你不动 build_vm.py；开工前先读 005-F-iota.md 的
  结案段确认图已封版。
- 重编译验证用 scratch 前缀：`python3 -u model/compile_vm.py --sparse model/step_vm_010_scratch`，
  报 dims/lookups/RSS 增量；真值 `model/step_vm_new_sparse.sbin` 不许覆盖。
  若你没动 build_vm.py 则免重编，写明理由即可。
- 引擎对拍（若重编）：`SBIN=$PWD/model/step_vm_010_scratch.sbin python3 -u scripts/verify_engine_vs_refvm.py`，
  基线 34/34 含 pow 不许倒退；vm_run 必须用仓库当前构建（09-15 22:31 代）。

### 完工定义（AGENTS.md 四条 + 卡 010 verifier 集）

1. 新差分绿：G3 三类（prop 通过 / 非 prop 拒 / 错误类别一致）+
   G2-unsafe 自引用（以真 lean 实测为准）+ G6（互块自引用、块内重名）逐条，
   原文粘贴尾行。
2. 五 canary 不破（check_e2e 15/15 等）+ 若动图则 scratch 引擎 34/34。
3. 每条语义决策带 environment.cpp 行引；ENV_FORMAT/VM_SPEC/矩阵同步；
   错误码链 ADR 落档。
4. 本文件写完工段：改动清单、verifier 原文、偏差申报。半完工+完整记录 >> 全完工+黑盒。

---

## G 任执行日志

### G01（首拍，2026-09-18）核段 0-5，OMP_NUM_THREADS=3，PY=/home/xkq/miniconda3/envs/train/bin/python，日志 /home/xkq/logs/010/g_*.log

#### 机器姿态快照（ps --sort=-rss，开工时原文摘录）

| PID | RSS | 身份 |
|---|---|---|
| 360689 | 7.36GB | 用户 GPU 训练 cpt/train_minimal.py（勿动勿杀） |
| 360838 | 0.67GB | torch inductor compile_worker（训练附属） |
| 354960 | 0.56GB | ZCode 客户端 |
| 360808-360811 | 各 0.40GB | 训练 dataloader worker |

内存：30GB 总 / 13GB 可用；无其他大 env Python 求值在跑（本会话独占）。lean 4.33.1 在位（`~/.elan/bin/lean --version` 实测输出 `Lean (version 4.33.1, x86_64-unknown-linux-gnu, commit 819816b2e0a3…, Release`）。

#### 现成渠道盘点三问（防线 14 条，附命令原文）

1. **工具自身既有通道**：`grep -n "reject_code\|CK_G0\|CK_G1\|safety_i" lean_vm/build_vm.py` →
   CK 链（ck_kick/CK_G0/CK_G1/G5 臂序）与 G10 门（:5577-5591、:6507）现成；锚帧/TASK_CHECK 的
   E2 字段确认无人读（D 注"free field on these STs"，build_vm.py:5457 自注）→ kind 载体零新帧。
   `grep -n "run_whnf\|kinds" lean_vm/step_driver.py` → 均不存在，协议扩展走新参数确认必要。
   错误类别判据通道现成：`tests/test_defeq_branches_vs_lean.py` 的 `KDECL_MSG_TEMPLATE`
   （#KDECLMSG → classHead，含 thmTypeIsNotProp 分支）与 `reference/lean_ref.py`
   （`run_oracle`/`run_check_oracle`），照抄不改 lean_ref.py。
2. **官方预编译缓存**：无新依赖；判据二进制 v4.33.1 本机已装（上面命令原文）。
3. **仓库 scripts/与 stdlib 等价物**：`ls scripts/` → `run_mem_guarded.py`（内存护栏，AGENTS
   指定入口）与 `run_cpu_regression.sh`（22 套件回归）复用；忠实 ENV 构造复用
   `reference/olean_export.dump_env/const_meta_for`（`tests/test_brec_drec_iota_vs_lean.py:346-363`
   build_group 为样板）。无 stdlib 重造。

#### 防线 15：对象差异评估（三机制逐一：driver 侧 vs 图侧共享面）

共享面 = ①错误码空间 4-7（扩展 8/9）、②CK_* 通道（锚帧字段）、③G10 use_reject 标志感知点。

1. **kind 携带（G3）**：kind 是**注入数据**，经新参数 `run_check(..., kinds=...)` 写入
   TASK_CHECK 锚帧 **E2**（现空闲，0=默认=旧路径逐字节不变）；图侧共享面 = CK_G1 处新臂
   `kind=thm ∧ whnf(T1)是 K_SORT ∧ level≠KL_ZERO → reject code 8`（复用 PI 链 pl_prop 的
   sort-零测法 build_vm.py:4451-4457，核 is_prop=ensure_sort(infer_type)+level 归零，
   K/type_checker.cpp:383-389；检查点次序 = K/environment.cpp:192-209：check_constant_val
   →is_prop→值侧）。臂序：8 落在 5 之后（ensure_sort 先于 is_prop）、与 4 无同步竞争。
   纯图侧判定（prop 与否走图），driver 不自己算 is_prop。
2. **unsafe 先注册后检查（G2）**：driver 侧协议 = 头检（旧 env、mode 位带上）→
   **注册**（常量表追加 + 合成 T_ENV_META 元数据：kind/safety/is_unsafe→use_reject 位由
   编码器现成预算）→ 体检（新 env、检查器 mode=unsafe）；失败=不提交（回滚，异常语义
   由 Python 层 raise 承担，环境不进 self.consts）。图侧共享面 = **G10 标志感知点两处**：
   (a) 注册后锚点 `anchor(cid).F2=1` 自然让**后续安全声明**引用它触 code 7（=任务书"标志
   须能感知注册后状态"，现成机制零改动）；(b) 声明**自身**体检时核用 unsafe-mode checker
   （K/environment.cpp:165-169）——图须知道 mode，否则自引用被 F2=1 误杀成 7。mode 载体 =
   **T_NULL（pos 0）X 字段**（现仅 V0=n_consts 被读，build_vm.py:483），run_check 新参数
   `check_mode=1` 时 driver 写 t0 输入 token；图侧门 = `safety_i ∧ mode=0`（mode≠0 抑制
   抛门）。已知近似：partial-mode 与 unsafe-mode 不区分（锚点 F2 本来就是 unsafe|partial
   析取位，ENV_FORMAT §2.3），"partial 块引用真 unsafe 常量"核抛而图放行——差分不构造
   该组合，接缝记 VM_SPEC（卡 011 若拆位再说）。
3. **mutual 块前置可见（G6）**：driver 侧 = 块内先查重名（核 add_mutual :236-241 的
   found-set，消息 `.other "invalid mutual definition, duplicate declaration name"`）+
   空块/全 safe 标签/同 safety/同 lparams 四条 well-formedness（:227-231、:241-246），
   全部是**环境簿记判定**（核里也在 type_checker 之外的 C++ 里做）→ driver 直接
   raise **新码 9**（`.other` 簿记族，不进图：图无 name 空间、无块概念，G8 同理）；
   块内 n 个常量先全部注册再逐一体检（mode=块 safety），任一失败整块回滚。
   图侧共享面 = 仅复用 2(b) 的 mode 位与注册元数据，**无新增图臂**。
4. **ADR016-B（run_whnf 续推）**：图合同不动（I_PROJ 交付 raw field 语义零变化，
   全部既有 whnf 差分基线不变的证明=套件本身）；driver 新法 `run_whnf` 把核
   whnf_core 的"proj 回灌再归约"循环（K/type_checker.cpp:504-508 外层 while）搬到
   调用方：每轮=一个图 TASK_WHNF，焦点不前进（pos 与 env 双同）即停，预算 TimeoutError
   复用。**不引入任何 Python 语义近似**（判定仍全在图内）。共享面=无（不触 CK 通道/错误码）。

#### 设计备案（编码前钉死，行引以上）

- 新参数全部带默认值：`run_check(decls, max_steps, kinds=None, check_mode=0)`、
  新方法 `run_whnf(...)`、新类 `InjectionEnv`（add_axiom/add_definition/add_theorem/
  add_opaque/add_mutual 家族，镜像 K/environment.cpp add 分发 :271-284）。旧调用
  路径（check_e2e/defeq_branches/stepgraph 五套件直接构造 StepDriver）逐字节不变。
- 新码登记：8=thmTypeIsNotProp（图臂）、9=mutual well-formedness（driver 簿记族，
  `.other`）；unknownConstant=既有粗码 2（driver 侧：注入协议对未注册名编码时
  Encoder 抛 KeyError → 翻译 VMError(2)，对应核 env.get 抛 unknown_constant，
  K/environment.cpp:74-85）。§7.4/ENV_FORMAT/KERNEL_COVERAGE 同步。
- 差分判据通道：#KDECLMSG（类别原文，含 thmTypeIsNotProp/other 消息前缀）逐例对拍；
  期望值全部现跑 `~/.elan/bin/lean`，语料零答案。

（本节之后按心跳 ≤10min 续写。）

### G02（2026-09-19）核段 0-5，OMP_NUM_THREADS=3，PY=python3（`import lean_kernel, torch` 已验，torch 2.13.0+cu130），日志 /home/xkq/logs/010G/g02_*.log

#### 机器姿态快照（开工时 `ps --sort=-rss -eo pid,rss,etime,comm,args | head -15` 原文摘录）

```
1709193 3765280     00:56 lean   lean --run ExtractData.lean .../Mathlib/Computability/AkraBazzi/GrowsPolynomially.lean
1710814 3328520     00:17 lean   lean --run ExtractData.lean .../Mathlib/Computability/PartrecCode.lean
1711843 2028752     00:01 lean   lean --run ExtractData.lean .../Mathlib/Util/Superscript.lean
1693911 1624816     05:17 lean   lean --threads 6 --run ExtractData.lean noDeps
1711907 1445372     00:00 lean   lean --run ExtractData.lean .../Mathlib/Util/CodeActions.lean
1711935 1381740     00:00 lean   lean --run ExtractData.lean .../Mathlib/Util/DischargerAsTactic.lean
1711953 1074704     00:00 lean   lean --run ExtractData.lean .../Mathlib/Util/Notation3.lean
1709164  856356     00:57 lake   lake env lean --run ExtractData.lean ...
```
`free -g`：总 30 / 已用 12 / 可用 **18**。lean 4.33.1 在位（`~/.elan/bin/lean --version` →
`Lean (version 4.33.1, x86_60-unknown-linux-gnu, commit 819816b2e0a3bf405af45ae5c7af2491d8f5bee6, Release`）。
`git status --short` 空、HEAD = `183ceda card 010: bank G01 recon log + lead audit verdict + ADR 020`。

**并发告警（与简报不同，如实记录）**：简报说的另一会话
`/home/xkq/lean4_ws/mathlib_trace_driver.py`（PID 1690712/1693877，
`/home/xkq/venvs/leandojo/bin/python`）开工时已不是 88MB，而是**正在并行派生 7+ 个
`lean --run ExtractData.lean` 子进程，单个 RSS 1.0–3.7GB，合计约 15GB**，且带
`--threads 6`。按指令**勿动勿杀**。对本拍的约束：可用内存 18GB（我的 scratch 重编峰值
约 635MB，安全）；CPU 与我预留的 0-5 号核有争用 → **所有计时数字只作参考，不作基线**；
差分套件的正确性判定不依赖时间。若某步 RSS 或耗时异常，先怀疑该会话而不是我的改动。

#### 计划子步清单（逐项心跳）

- [ ] S1 载体空闲性实证件：只改 `step_driver.run_check` 加 `kinds` 参数（图/权重不动），
      新套件 `tests/test_decl_injection_vs_lean.py` 落常设守卫（E2=非零哨兵 → check_e2e
      全集判定与步数逐字不变），并**先**存 stepgraph / defeq 族改图前基线日志。
- [ ] S2 图侧新臂：`build_vm.py` CHECK 链 kickoff `fr1_E2_k = frE2` + CK_G0 的 E2 copy-forward
      + CK_G1 ok 支的 `kind=theorem ∧ level 根非 KL_ZERO → 码 8`（复用 :4451-4457 的 sort-零测），
      `reject_code` 链 :6507-6511 挂 8（在 5 之后）。
- [ ] S3 新差分套件补全：Prop 通过 / 非 Prop 拒 8 / 类别对拍（`#KDECL`）/ kind 1,2,4 不触闸 /
      `kinds=None` 逐字节不变 / 非归一 level 形（`imax 1 0`、`max 0 0`）实跑双方原文。
- [ ] S4 scratch 重编 + 引擎对拍 34/34 + 22 套件回归 + 硬编码扫描。
- [ ] S5 文档同步：ENV_FORMAT（E2 布局取值表）、VM_SPEC（码 8 臂序 + `kinds` 协议）、
      KERNEL_COVERAGE G3 行；完工段 + 偏差申报。

#### 心跳 H1（S1 载体空闲性实证件：设计与取证方式）

必读文件读完后的两个实施决定（都在简报/ADR 的授权范围内，记录理由）：

1. **哨兵值取 kind_code=1（axiom），不是任意非零数**。`kinds=None` 时 E2=0，
   而 E2=0 本身就是合法值（unspecified），所以"非零且必须全程无效"的载体只能
   落在闸门不看的 kind 上：新臂只测 `kind_code==3`，故 E2=1 在改图前后都必须
   逐字无效 —— 这一件因此既能作为"图未动时的空闲性证明"，又能作为改图后的
   **常设守卫**（同一个断言，两种时刻都成立）。
2. **图侧 kind 解码按布局做满**：`mode = (E2 >= 8)`、`kind = E2 - 8*mode`，
   再测 `kind==3`。理由：`add_theorem` 永远用 safe checker
   （`K/environment.cpp:196`），is_prop 与 mode 位无关；若只测 `E2==3`，
   下一拍（G2-unsafe，mode=1 → E2=11）会让闸门**静默失效**。成本仍是 O(1)。
3. E2 的读点：kickoff 把锚帧 E2 复制进 ST（`fr1_E2_k = frE2`），CK_G0 再
   copy-forward 一跳，CK_G1 读它。既有 `frE2`/`nbE2` 消费点全部按帧类型或
   continuation id 门控（`nbE2` 唯一读者 build_vm.py:1349-1350 要求
   `nbV0==TASK_WHNF`；`cg[IP_PEEL]`/`soft_flag` 等要求各自的 F2），
   CHECK 链的 ST 用的是 CK_G0/CK_G1/CK_TY/CK_RES，与它们互斥。

取证方式（为什么不需要动工作树里的 build_vm.py）：
`git show HEAD:lean_vm/build_vm.py` 复制到
`/home/xkq/logs/010G/g02_pre_repo/`（3.9MB 仓库快照，model/ 用符号链接），
快照里 graph = HEAD 原文、step_driver = 新版（带 kinds）、测试 = 新版；
新套件支持 `G02_ONLY=guard`（只跑载体件）与 `G02_LEGACY_BUILD_VM=<path>`。
命令原文与日志：

```
cd /home/xkq/logs/010G/g02_pre_repo
OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u scripts/run_mem_guarded.py --max-rss-mb 4000 --timeout 1200 -- \
  python3 -u tests/test_check_e2e.py        > /home/xkq/logs/010G/pre_check_e2e.log 2>&1
```
输出尾行原文（**图与权重完全未动、driver 已带 kinds 参数**时的基线）：
```
Layer B  step graph vs RefVM: 15/15

=== M4.2 end-to-end check: A 15/15, B 15/15 === OK
[mem-guard] wall 340.6s peak RSS 1584MB rc=0
```
stepgraph / defeq 族同批基线在跑（pre_stepgraph_refvm.log / pre_defeq_branches.log），
载体哨兵件 pre_guard.log 排在它们之后（同会话一次只挂一个大 env 求值）。
本批脚本的 `echo rc=$?` 被 `$(date)` 命令替换吃掉了返回值（pre_guard 第一次跑因
a0 段读不到 HEAD build_vm 的新常量而 rc=1，状态行却写 rc=0）——已改：先
`st=$?` 再打印，且快照里那次只跑 `G02_ONLY=guard`。教训记下：**后台批的状态行
不许在命令替换里取 `$?`**。

#### 心跳 H2（S2 图侧新臂 + S4 前半：scratch 重编与硬编码扫描）

图改动三处（全部在 CHECK 链，非 CHECK 模式按构造取 0）：
`build_vm.py:224-235`（CHECK_* 布局常量）、`:5430`（CK_G0 的 E2 copy-forward）、
`:5449-5473`（g3 臂 + rej_code_c 8）、`:5509-5511`（kickoff `fr1_E2_k = frE2`）、
`:6564-6568`（reject_code 链插 8，7>6>5>8>4）。driver 侧 `kinds=None` 写 E2=0，
故既有五套直接构造 StepDriver 的套件走的仍是原路径。

**差分实测（新套件 `tests/test_decl_injection_vs_lean.py`，oracle = 现跑
`~/.elan/bin/lean` 4.33.1 的 `#KDECL`；下面每条都是日志原文，不是转述）**：

```
  [PASS] B thm_true: oracle=OK graph=accept=True code=0(accept) steps=8
  [PASS] B thm_nat: oracle=thmTypeIsNotProp graph=accept=False code=8(thmTypeIsNotProp) steps=4
  [PASS] B thm_arrow: oracle=declTypeMismatch graph=accept=False code=1(declTypeMismatch) steps=42
  [PASS] B def_nat: oracle=OK graph=accept=True code=0(accept) steps=8
  [PASS] B opa_nat: oracle=OK graph=accept=True code=0(accept) steps=8
  [PASS] B def_true: oracle=OK graph=accept=True code=0(accept) steps=8
  [PASS] B thm_typeexpected: oracle=typeExpected graph=accept=False code=5(typeExpected) steps=4
  [PASS] B thm_dbl_nat: oracle=thmTypeIsNotProp graph=accept=False code=8(thmTypeIsNotProp) steps=4
  [PASS] B axm_nat: oracle=OK graph=accept=True code=0(accept) steps=4
  [XFAIL-KNOWN-GAP] D thm_imax: oracle=OK graph=accept=False code=8(thmTypeIsNotProp) steps=4
  [XFAIL-KNOWN-GAP] D thm_max00: oracle=OK graph=accept=False code=8(thmTypeIsNotProp) steps=4
  [PASS] D def_imax: oracle=OK graph=accept=True code=0(accept) steps=15
  [PASS] D thm_sortraw_imax: oracle=thmTypeIsNotProp graph=accept=False code=8(thmTypeIsNotProp) steps=6
  [PASS] D thm_sortraw_max00: oracle=thmTypeIsNotProp graph=accept=False code=8(thmTypeIsNotProp) steps=6
  [PASS] C chain_ok_mixed: members=['def_nat', 'thm_true'] kinds=[2, 3] expected-code=0 graph=accept=True code=0(accept) steps=17
  [PASS] C chain_ok_axm_first: members=['axm_nat', 'thm_true'] kinds=[1, 3] expected-code=0 graph=accept=True code=0(accept) steps=13
  [PASS] C chain_reject_second: members=['thm_true', 'thm_nat'] kinds=[3, 3] expected-code=8 graph=accept=False code=8(thmTypeIsNotProp) steps=13
```

三条**实测翻案**（不许用推理入账的那类）：

1. `Nat → True` **是 Prop**。我按"Pi 的类型在 Type"写了这条期望它触 8，核
   `#KDECL` 实测回 `declTypeMismatch`——`infer_type` 对依赖积用 Prop 封闭规则
   （体是 Prop 则整体 Prop），所以 is_prop 通过、倒在值侧。图的 INFER 侧本来
   就实现了这条封闭规则，实测 code=1 与核一致，**本拍无需补臂**。该用例改成
   "闸门通过、错误类别仍一致"的正面证据；另补 `thm_pi_type`（`Nat → Nat`，
   体不是 Prop）覆盖"闸门在 Pi 上抛 8"。
2. 非归一 level 形**必须注入**才可达：源写的 `Sort (imax 1 0)` / `Sort (max 0 0)`
   被前端归一，`reference/olean_export.dump_env` 实测存的是
   `Sort(level=LZero())`；只有用 `Lean.Expr.sort (Lean.Level.imax …)` 走
   `Lean.addDecl` 建常量，导出侧才拿到
   `injX_imax: Sort(level=LIMax(a=LSucc(l=LZero()), b=LZero()))`。
   → ADR 020 B 预测的分歧被实跑证实（核 OK / 图 8），登记 G3a + KNOWN_GAPS。
3. `axiom`（kind=1 + 锚帧 X=0）：我原写"此前没有任何 run_check 用例"，**该断言
   已作废**——`tests/test_defeq_branches_vs_lean.py:424-426` 正是
   `val=None → v=0 → run_check([(t,0)])`（G5 的常驻用例）。本拍的真实增量是
   X=0 形状第一次带**非零 kind 载荷**过链，实测 `oracle=OK / graph=accept(4 步)`
   ✓（详见 ADR 021 §C，那里也记了"grep 断言也要核原文"这条自我纠正）。

**scratch 重编（对照 = 同一命令在图未改动的快照里跑）**：

| | pre（HEAD 图） | post（本拍图） | Δ |
|---|---|---|---|
| graph dims | 25990 | 26012 | **+22** |
| lookups | 2899 | 2901 | **+2** |
| d_model（schedule/weights） | 4822 / 6252 | 4826 / 6258 | +4 / +6 |
| heads_global / ffn | 650 / 2704 | 651 / 2707 | +1 / +3 |
| nnz | 192,717 | 192,821 | **+104** |
| .sbin 字节 | 18,888,194 | 18,906,018 | +17,824 |
| 编译峰值 RSS | — | 718,376 KB（702MB） | 与预算 635MB 同量级 |

解释：一条臂 = 1 个 level-根 fetch + 1 个 `_fv0` NULL 守卫 fetch（+2 lookups）
+ 解码与门控的 6 个 ReGLU 判据按层摊开（+22 dims，均为 O(1) 常数，与 env 规模
无关）✓ 与"一条臂应为 O(1) 级"的预期一致。
新 artifact：`model/step_vm_010_scratch.sbin`，md5 `fc71fa5d44cb73630af41113d61d6aed`，
18,906,018 字节，生成于 2026-09-19 04:20，命令
`OMP_NUM_THREADS=3 taskset -c 0-5 python3 -u model/compile_vm.py --sparse model/step_vm_010_scratch`。
**登记由总控做**（本拍未碰 `ARCHITECTURE.md`）；真值 `model/step_vm_new_sparse.sbin`
未覆盖（mtime 未变）。
踩坑记录：快照的 `model/` 一开始用符号链接指向真仓库，
`compile_vm.py` 里 `Path(__file__).resolve()` 会**穿过符号链接**把 sys.path 指回真仓库，
于是"pre 编译"其实编的是 post 图（两个 .sbin md5 相同才暴露）。已把 `model/*.py`
真拷进快照复测。**快照要跑 compile_vm 就不能软链 model/**。
（tests/*.py 无此问题：`tests/` 不是符号链接，实测 `Path('tests/test_check_e2e.py').resolve()`
落在快照内，且快照 build_vm 无 `CHECK_E2_STRIDE` → 三个 canary 基线确实是改前图。）

**硬编码扫描**（铁律 3，命令原文）：

```
$ grep -c "CID_" lean_vm/build_vm.py            → 37
$ git show HEAD:lean_vm/build_vm.py | grep -c "CID_" → 37   （零新增）
$ git diff -U0 -- lean_vm/build_vm.py lean_vm/step_driver.py | grep '^+' | grep -vE '^\+\+\+' \
    | grep -nE 'CID_|"(E_[A-Za-z]|Nat\.|Bool\.|P2\.|injX_|injD_|True|False|T_)'  → 0 命中
$ git diff -U0 -- lean_vm/build_vm.py | grep '^[+]' | grep -E "One \* [0-9]+|_one_dim: [0-9]+"
  +    rej_code_c = rej_code_c + reglu(g3, One * 8)
  +                  _select(g3, One * 8,
  +                  _select(bad_i + lvl_bad, One * 4, One)))))
```
新增数字字面量只有拒码 8（错误码空间，与既有 5/6/7 同列）与 ENV_FORMAT §2.8
的 kind/mode 取值常量；无按常量名/cid 写死的分支。

#### 心跳 H3（验证编排：两批串行，避免自相踩 /tmp 与内存）

机器事实修正（简报说另一会话约 88MB）：`mathlib_trace_driver` 在 20:26 时点已
派生 5-7 个 `lean --run ExtractData.lean` 子进程，单个 RSS 1.6-4.2GB，
`free -g` 可用从 18GB 掉到 15GB。仍然"勿动勿杀"，但本拍据此**不并行挂第二个
大 env Python 求值**，全部串行：

```
批 1（图未动，快照 /home/xkq/logs/010G/g02_pre_repo）      g02_pre_batch.sh
  pre_check_e2e.log        ✅ rc=0  A15/15 B15/15  wall 340.6s peak 1584MB
  pre_stepgraph_refvm.log  ✅ rc=0  wall 611s
  pre_defeq_branches.log   运行中（timeout 2400）
批 1b（同快照，等批 1 done 再起）                          g02_pre_batch2.sh
  pre_guard.log            G02_ONLY=guard：锚帧 E2 写非零哨兵、图与权重不动
批 2（真仓库，等批 1b done 再起）                          g02_post_batch.sh
  post_engine_scratch.log  SBIN=$PWD/model/step_vm_010_scratch.sbin \
                           python3 -u scripts/verify_engine_vs_refvm.py
  post_full_suite.log      新套件全集（a0 + guard + bcd）
  reg_post/ + post_regression.log   22 套件回归
     （OMP_NUM_THREADS=3 REGRESSION_CORES=0-5 REGRESSION_JOBS=3 \
       REGRESSION_LOG_DIR=/home/xkq/logs/010G/reg_post bash scripts/run_cpu_regression.sh）
```
`reg_post/{check_e2e,stepgraph_vs_refvm,defeq_branches_vs_lean}.log` 将与批 1 的
同名 pre_ 基线逐行 diff —— 这就是"stepgraph/defeq 族判定与步数逐字不变"的取证形式
（回归里三个套件跑的是同一份语料与同一套打印格式，PrivateTmp 只改 /tmp 不改输出）。

新文档落档：`docs/decisions/021-injection-g02-measured-findings.md`（上面三条
实测翻案 + 载体哨兵/解码/常量分置的决定 + 快照取证方法与 model/ 软链坑）。

#### 心跳 H4（回归表缺口：本拍无权写 scripts/）

`tests/test_decl_injection_vs_lean.py` **不在** 22 套件回归表里，因为
`scripts/run_cpu_regression.sh` 在卡 010 的禁改集内。总控加行时的实测参数：
单条图用例约 16s、全套 a0+guard+bcd ≈ 34 条图用例 + 1 次 `#KDECL` lean 批量，
预计 wall ≈ 900-1100s（本机有 mathlib 并发时更长）、峰值 RSS 与 check_e2e 同量级
（批 2 跑完会回填实测值）。建议条目：
`"2400|4000|decl_injection_vs_lean|tests/test_decl_injection_vs_lean.py"`。

#### 心跳 H5（中途状态快照 — 防客户端猝死，防线 §1.16 第①条）

**已经落盘可用**：S1 三条 pre 基线（check_e2e A15/15+B15/15 rc=0 wall 340.6s
peak 1584MB；stepgraph_vs_refvm rc=0 wall 611s；defeq_branches
`=== defeq branches vs lean: ALL OK ===` rc=0 wall 898.3s peak 2045MB，
全部在**图 = git HEAD** 的快照上跑）＋ S2 图臂与 S3 差分主表（H2 的 17 条原文）
＋ S5 三份文档 ＋ ADR 021 ＋ 硬编码扫描（H2）。

**本拍踩到的自己的坑（如实记）**：`section_guard` 第一版把
`CHECK_CASES` 行当成 `(cid, member)` 解，跑起来 `NameError: name 'm' is not
defined` —— 而它直到 20:35 才第一次被真正执行（前几次开发跑都用了 `G02_ONLY`
子集，绕过了这段），所以"pre 载体件"第一次跑就红了。
已修（按 `(cid, type_src, val_src, type_Expr, val_Expr)` 解）并加
`G02_GUARD_LIMIT` 开发档（只在 dev 用，交付跑全集）。**教训**：新套件里任何
"看起来显然"的段，第一次必须真跑到它，别用子集自证。
连带影响：为修它我杀了 post 批的驱动脚本，`pkill -f "g02_post_batch.sh"` 的
模式**匹配到了自己这条命令行**（AGENTS 明写的自杀陷阱），把自己的 shell 打掉了
（rc=143），子进程 verify_engine_vs_refvm 反而活下来了 —— 模式必须先用
`pgrep -af` 看清并加中括号断词。

**正在跑（串行链，`/home/xkq/logs/010G/g02_chain.sh`，状态文件 `g02_chain.status`）**：

1. `post_engine_scratch.log`：`SBIN=$PWD/model/step_vm_010_scratch.sbin
   python3 -u scripts/verify_engine_vs_refvm.py`（基线 34/34 含 pow）
2. `pre_guard.log`：快照（图=HEAD）上跑 `G02_ONLY=guard` = **S1 载体空闲性实证件**
3. `post_full_suite.log`：新图上的新套件全集（a0 + guard 全 15 例 + bcd 全 19 例）
4. `reg_post/` + `post_regression.log`：22 套件回归；随后把
   `reg_post/{check_e2e,stepgraph_vs_refvm,defeq_branches_vs_lean}.log`
   与 1-3 步之前的 pre_ 基线逐行 diff（判定与步数字节不变的那件）

链跑完前**不许**再在 0-5 号核上挂第二个大 env 求值（本会话纪律）。

**申报的偏差与已知近似（终稿要照抄进交付）**：

1. 载体不只落在锚帧：kickoff 会把锚帧 E2 复制进 CHECK 链的 ST 帧（`fr1_E2_k = frE2`），
   CK_G0 再 forward 一跳，CK_G1 才读得到。ADR 020 只钉了"锚帧 E2 空闲"，
   ST 帧 E2 的占用是实现的必然结果。风险与反驳：`kinds=None` 时该值恒 0
   → 既有全部语料逐字不变；非零时 CHECK 链 ST 的 F2 ∈ {CK_G0,CK_G1,CK_TY,CK_RES}
   与其余 `frE2`/`nbE2` 读者的门互斥（VM_SPEC §16.4 列了逐个读者）；
   实测面：新套件里带非零 kind 的 accept 例（thm_true 8 步、def_imax 15 步、
   三条链 13-17 步）+ 全集 guard 双向对拍。若总控判定 ST 槽也不算空闲，
   换槽需重开一次载体件。
2. 图侧 kind 解码按 §2.8 布局做满（`mode=E2>=8`），本拍 mode 恒 0 → 与
   `E2==3` 在本拍等价，但下一拍启用 mode=1 时只有做满才对（ADR 021 §F）。
3. 布局常量读写两侧各一份 + 套件 a0 逐常量对拍：`expr/tokens.py` 在卡 010
   禁改集内（ADR 021 §G）。要合并是 4 行搬移。
4. 码 8 只走"Python 图 + 真 lean 差分"这一条通道；C++ 引擎通道（34 例）是
   WHNF-only，不经过 CHECK 链 → "引擎侧抛 8"这一条 NOT-VERIFIED（VM_SPEC §16.4
   "验收通道边界"）。
5. 新套件不进回归表（`scripts/run_cpu_regression.sh` 禁改）→ 总控加行（H4）。
6. `thm_imax`/`thm_max00` 两条按 ADR 020 B 记为具名缺口（XFAIL-KNOWN-GAP +
   KERNEL_COVERAGE G3a 行），不是本拍可修项（D1/D2 归卡 012）。

---

## 总控裁决（卡 010）

### 对 G01 备案的验尸结论（2026-09-19，总控逐条对码，非转述）

站得住的（可直接实施）：

- **G3 臂落点对**。核 `add_theorem` 次序 = `check_constant_val` → `is_prop` → 值侧
  （`K/environment.cpp:192-209` 实测原文：`check_constant_val(...)`; `if (!checker.is_prop(type))
  throw theorem_type_is_not_prop(...)`），而图侧 `check_constant_val` 的 `ensure_sort` 段
  **已经存在**＝CK_G0/CK_G1（`build_vm.py:5398-5425`，软 whnf T1 → 检 `K_SORT` → 否则码 5）。
  所以 G3 缺的确实只有"level 归零"一测，备案"复用 pl_prop 的 sort-零测法"方向正确。
  勘正措辞：备案写"whnf(T1) 是 K_SORT"里的 T1 是**声明类型的类型**（图既有命名），不是声明类型本身。
- 复用 `pl_prop` 的零测（`build_vm.py:4451-4457`）、`InjectionEnv` 家族镜像核 `add` 分发、
  旧签名带默认值扩展、码 9 走 driver 簿记族不进图——均无架构冲突。

必须改的（两条，都不许带进编码拍）：

1. **mode 载体 T_NULL.X 作废**。位置 0 是**空指针哨兵**（`build_vm.py:289` 自注 "Position 0 is the
   T_NULL"），图里有以可能为 0 的指针读 X 的站点（`:614`、`:849`、`:948`、`:1012`）。往里写 1
   ＝给全图每次 null-env 读取注入伪字段，不是加能力是埋脏数据。这与防线 §1.17 点名的
   "M1-01b T_NULL 哨兵论证错误"同族。**改判：kind 与 mode 同走 TASK_CHECK 锚帧 E2**，
   并要求 E2 空闲性由**实跑**证明（图与权重不动，driver 写非零哨兵 → check_e2e/stepgraph/defeq
   判定与步数逐字不变）。全文见 `docs/decisions/020-injection-carrier-and-level-test.md`。
2. **行号勘误**：reject 链 7>6>5>4 的真实装配点是 `build_vm.py:6507-6511`
   （`reject_code = _select(safety_i, 7, _select(g7, 6, _select(g1_fail, 5, _select(bad_i+lvl_bad, 4, One))))`），
   备案与卡片写的 `:6053` 是 quot_stuck 的 select 行。新码 8 挂在 `g1_fail`（码 5）之后。

预先定性、不许临场发挥的第三件：**非归一 level 形**。核 `normalizes_to_zero` 对 `imax` 只看 rhs
（`K/level.cpp:174-186`），依赖 `mk_imax` 智能构造（矩阵 D2＝缺失）；图的测法是根节点 syntactic
`KL_ZERO` 比较。故 `Sort (imax 1 0)` 这类形核判 Prop、图会**假拒码 8**。处置见 ADR 020 决策 B：
差分面必须实跑一条该形，结果要么是能力要么是记了账的 `NOT-VERIFIED`，不许静默等价。

### 排产

- 卡 010 状态维持 open；verifier 集按 ADR 020 追加三条硬项（载体空闲性实证件、码 8 臂序与
  类别对拍、非归一 level 形要么绿要么 NOT-VERIFIED）。
- G02 派工（本文件之下的执行记录继续追加，**表头先落盘再动手**——防线 §1.16 第①条，
  本项目已 21 次客户端猝死，半件不落盘等于没做）。
- 上一任 G 死于 G01 之后（`/home/xkq/logs/010/` 只留 `g_probe_whnf.log` 44 字节，无代码改动），
  资产未丢：设计备案完整，本裁决即补齐它的两处缺陷。

## 总控收口：G02 验收通过（2026-09-20，本链终态）

三条在跑 verifier 全部落定，五道门收口，**G02 子链 CLOSED**（卡 010 整卡仍
open，余 G6 mutual 拍）：

1. 差分全集 54/54 + 2 xfail（非归一 level 形 KNOWN-GAP，ADR 021），rc=0：
   `/home/xkq/logs/010G/lead_full_suite.log`（05:24）。
2. 载体空闲性 guard：check_e2e 全语料 kinds=None vs E2=1 判定+步数逐字一致，
   全 PASS（同日志 guard 段）。
3. 22 套件回归等效齐全：21 项 09-19 06:43 PASS；mutation_reject 当趟 900s
   超时定性为环境性（机器负载），09-20 单项重跑 rc=0（A 16/16、B 8/8、
   754.8s/1552MB）：`/home/xkq/logs/010G/mutation_rerun/`。代码态一致性：
   `git diff 15a500d..HEAD --stat` 零代码文件。

总控裁决两条（checkpoint 留下的待裁项）：
- **ST 帧 E2 占用：追认**。图侧需把 kind 载体从锚帧 copy-forward 到 ST
  （`build_vm.py` CK_G0 选择行），凭证=载体空闲性全语料 PASS + 套件 a0 段
  写读两侧常量漂移对拍；ENV_FORMAT §2.8 为单一口径。ADR 020「仅锚帧」的
  措辞由 ADR 021 的实测发现更新，不另开 ADR。
- **引擎侧码 8：保持 NOT-VERIFIED**，归卡 013（引擎 CHECK 通道）。

总控执笔的合同变更：新套件 `decl_injection_vs_lean` 入
`scripts/run_cpu_regression.sh`（2100s/4000MB，实测 1395.6s/2101MB 定帽），
日常回归基数 22 → 23。验收清单原文见卡 010 派工增补 3。

### G06 拍表头（总控 2026-09-20 落盘，先于派工——防线 §1.16①）

- 派工对象：图逻辑/驱动器工程师（干净上下文子代理），核段 0-5，OMP_NUM_THREADS=3，
  PY=`/home/xkq/miniconda3/envs/train/bin/python`，日志 `/home/xkq/logs/010G/g06_*.log`。
- 任务：卡 010 G6 mutual 拍——driver 侧 `InjectionEnv` + `add_mutual` 前置可见 +
  块 well-formedness（码 9 簿记族）+ 套件 G6 差分节。**图（build_vm.py）零改动**：
  本拍禁止触碰；若实施中发现必须动图，停手上报（G03 才是图拍）。
- 顺序：探查先行（P1 kernel add_mutual 的 Lean 侧 API 探针 / P2 回滚语义探针，
  答案落本板后才许编码）。
- 交付：套件 G6 节全跑 rc=0 原文 + canary（decl_injection 全节 / check_e2e /
  defeq_branches）+ VM_SPEC §16 / KERNEL_COVERAGE G6 行同步 + 硬编码扫描。
- 状态：IN PROGRESS（表头即存在证明，代理死则从这里续）。

### G06 执行日志（2026-09-20，核段 0-5，OMP_NUM_THREADS=3，PY=/home/xkq/miniconda3/envs/train/bin/python，探针 /tmp/g06_probe1.lean）

#### 环境事实（开工时实测，与简报的差异如实申报）

1. **oracle 工具链漂移（须总控知悉）**：`~/.elan/bin/lean --version` 现回
   `Lean (version 4.34.0, …, commit 293d5d0c0c3f3dded4688b3ccd6a33939ac5102b, Release)`
   —— `~/.elan/settings.toml` 的 `default_toolchain = "stable"` 漂到了 4.34.0
   （elan 自更新于 09-19 15:08 重写了代理；G02 验收跑 09-20 05:24 时仍是 4.33.1，
   `lead_full_suite.log` 首行为证）。本拍处置：**探针与套件全部显式钉
   `~/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean`**（`run_kdecl_oracle`
   /`dump_env` 均有 `lean_cmd` 覆盖参数，冻结文件零改动）；套件对
   `lean_ref.LEAN` 的解析改为"钉住路径存在则用之，否则回退 `~/.elan/bin/lean`"。
   `elan default` 该不该改回，属总控/用户裁决，本拍不动 settings.toml。
2. 机器：30GB 总 / 可用 ~18GB；无其他大 env Python 求值在跑。

#### P1 结论（mutual 的 oracle 通道：**存在，走 #KDECL 原通道**）

命令：`grep -rn "add_mutual\|MutualDecl\|addDecls" /home/xkq/lean4/src/kernel/ /home/xkq/lean4/src/Lean/`
→ kernel 侧仅 `environment.h:72` / `environment.cpp:225` / `environment.cpp:277`
（add 分发的 MutualDefinition 支）；Lean 侧无 addDecls（IR 编译器的不相干同名）。
关键在 `Lean.Declaration.mutualDefnDecl (defns : List DefinitionVal)`
（4.33.1 源 `Lean/Declaration.lean:191`，4.35 master 同）——它是 `add` 分发的
MutualDefinition 载体，**可从 Lean 代码构造**。

探针（`/tmp/g06_probe1.lean`，`~/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean` 实跑，
rc=0，输出原文）：

```
A crossref-unsafe: OK
A2 ref-from-result-env g06x_f: other[invalid declaration, it uses unsafe declaration 'g06x_f']
B dup-name: other[invalid mutual definition, duplicate declaration name 'g06_dup']
C safe-block: other[invalid mutual definition, declaration is not tagged as unsafe/partial]
D empty-block: other[invalid empty mutual definition]
E mixed-safety: other[invalid mutual definition, declarations must have the same safety annotation]
F lparams-mismatch: other[invalid mutual definition, declarations must have the same universe level parameters]
G partial-single: OK
H fail-mutual: declTypeMismatch
H1 ref-from-caller-env g06_rb_ok: unknownConstant(g06_rb_ok)
H2 ref-from-EXCEPTION-env g06_rb_ok: other[invalid declaration, it uses unsafe declaration 'g06_rb_ok']
I1 ref-from-env0 g06x_f (control, env0 unchanged): unknownConstant(g06x_f)
```

五条 well-formedness 消息原文全部到手（上 B/C/D/E/F 行），类别一律 `other`——
与 G01 备案一致：映射链 = kernel `kernel_exception`（纯文本）→
`kernel_exception.h:201-203` 的 `catch (exception &)` → `Kernel.Exception.other(msg)`
→ classOf = "other"。**P1 未触发停手条件**：mutual API 从 Lean 侧可直达，
且走的就是 G02 已验收的 `#KDECL` 通道（case 项 = `.mutualDefnDecl […]` 项），
不需要前端 mutual 语法（elaborator 会重写，禁用——简报原话）。

#### P2 结论（回滚**可观察**，断言形式 = "失败后成员名引用 → unknownConstant"）

C++ 证据链：`add_mutual` 把 n 个成员 add 进**局部副本** `new_env`
（`K/environment.cpp:253-257`），值体检循环抛
`definition_type_mismatch_exception(new_env, d, val_type)`（`:259-267`）——
异常对象**携带** new_env（`kernel_exception.h:171-173` 的 `ex.env()`），但
`lean_add_decl`（environment.cpp:287-295）返回 `Except.error`，**调用方 env 不变**。
探针实测三件套：

- H：块 [ok:=2, bad:True:=2] → `declTypeMismatch`（第二员值侧失败）；
- H1：失败后从**调用方 env**引用 `g06_rb_ok` → `unknownConstant(g06_rb_ok)`
  —— 回滚可观察，差分断言形式由此定：driver 侧失败块成员
  `InjectionEnv` 查名 → VMError(2)（粗码 2 = ERR_MISSING_CONST）↔ oracle
  unknownConstant；
- H2：从**异常载荷 env**引用同一名字 → 过了 unknownConstant、倒在 unsafe-use
  门（`other[invalid declaration, it uses unsafe declaration 'g06_rb_ok']`）
  —— "先全部注册"在核里真实发生（:253-257），只是不提交。
- I1（对照）：成功块 A 的成员从从未 setEnv 的 env0 引用 → unknownConstant，
  排除"env 泄漏"假阳性。

#### P1/P2 的派生实施决定（编码前钉死）

1. **add_mutual 两阶段镜像**（不止"先注册再体检"）：kernel 的 header 循环
   （`:236-251`，含 `check_constant_val` 的 `checker.check(type)`，
   `environment.cpp:127-132`）跑在**旧 env** 上、先于注册（`:253-257`）；值体检
   （`:259-267`）跑在 new_env 上。→ driver：pass A = 全员 header 图检
   （X=0 锚形状 = G5 无值约定，kinds=[2]×n，mode=块 safety）在注册前；
   pass B = 注册全员后逐员全检；任一失败整块回滚（Python 侧弹回
   _consts/_names，异常上抛）。单缺陷语料下首错次序与核一致；
   多缺陷块的"簿记错 vs header 错"交错次序（核按成员交错）记已知近似。
2. **互引正例的图侧通道**：图 G10 门 mode 盲（`build_vm.py:5640-5646` 注释
   自证 "The graph's checker is always safe-mode"；门 = `:5646` safety_i、
   `:5718-5723` 入 bad 通道、`:6569` 拒码 7）——unsafe/partial 成员带真实
   meta（F2=1，`expr/tokens.py:459-465/572-577`）的互引会被图误杀成 7。
   本套件沿用 G02 全部语料的**无 meta 通道**（`Encoder(consts, is_ctor=ctors)`
   不传 const_meta → F2=0 门自然闭合），互引正例因此可差分绿；
   "成员 unsafe/partial 标志 × G10 门（mode 臂）"整面 = **G03 差分面**，
   VM_SPEC G6 节记已知近似。这不是放水：码 7 的 meta 差分面本就归
   defeq_branches 的 meta_only 用例。
3. **A2/I1 的意外语义收获**：kernel 对 unsafe 常量的引用本身（safe checker）
   抛 `other[invalid declaration, it uses unsafe declaration '…']`——
   证实 §16.3 的"全仓库唯一抛点 = infer_constant .other"（K/type_checker.cpp:111）。
4. 套件 G6 节行集：W 组（wf 簿记，零图跑）dup-name / safe-block / empty /
   mixed-safety / lparams-mismatch 五行 + V 组（图跑）互引正例 / 块员失败回滚 /
   后继引用已提交块员（预注入 RAW_MUTUAL）/ 分发两行（thm→8、def→accept）。
   oracle = 同一 `#KDECL` 批（11 case），全现跑。
5. `run_check` 新增第 4 个带默认参数 `check_mode=0`（G01 备案名）：
   `kinds=None` 时仍写 E2=0（逐字节不变）；`kinds` 给出时 E2=kind+8*mode
   （§2.8 布局）。图侧 mode 臂未接（G03），E2 数据先行忠实。

#### G06 心跳 H2（InjectionEnv 骨架 + add_mutual 落地，2026-09-20）

step_driver.py 三处改动，每步 py_compile 过：

1. `ERR_MUTUAL_WF = 9`（码 9 登记，注 kernel 引 :228-248）。
2. `run_check` 增第 4 参 `check_mode=CHECK_MODE_SAFE`：`kinds=None` 路径
   E2 恒 0（逐字节不变，且 kinds=None + check_mode≠0 显式 ValueError 拒绝）；
   kinds 给出时 E2=kind+8*mode。旧调用点零变化（五套件直接构造 StepDriver）。
3. 新类 `InjectionEnv`：add_axiom/add_definition(safe/unsafe)/add_theorem/
   add_opaque/add_mutual 五分支，相位逐条对齐 env.cpp（类 docstring 带行引）；
   `contains()` = env.find 探针；`_check` 的 Encoder KeyError → VMError(2)
   翻译（env.get unknown_constant 镜像）；回滚恢复被遮蔽的旧名绑定。

wf 簿记冒烟（无图跑，graph_builder 注入断言桩，输出原文）：

```
PASS wf: invalid empty mutual definition -> VM reject 9: invalid empty mutual definition
PASS wf: invalid mutual definition, declaration is not tagged as unsafe/partial -> VM reject 9: ...
PASS wf: invalid mutual definition, declarations must have the same safety annotation -> VM reject 9: ...
PASS wf: invalid mutual definition, declarations must have the same universe level parameters -> VM reject 9: ...
PASS wf: invalid mutual definition, duplicate declaration name 'd' -> VM reject 9: ...
graph never fired; smoke OK
```

（进行中：套件 G6 节。）

#### G06 心跳 H3（套件 G6 节子集首跑全绿，2026-09-20）

`G02_ONLY=g6` 子集（mem guard 4000MB，核 0-5，日志
`/home/xkq/logs/010G/g06_subset.log`），输出原文：

```
oracle[g6v1_crossref] = OK
oracle[g6v2_member_fail] = declTypeMismatch
oracle[g6v3_dispatch_thm] = thmTypeIsNotProp
oracle[g6v4_dispatch_def] = OK
oracle[g6v5_later_ref] = OK
oracle[g6w1_dup_name] = other
oracle[g6w2_safe_block] = other
oracle[g6w3_empty_block] = other
oracle[g6w4_mixed_safety] = other
oracle[g6w5_lparams] = other
  [PASS] W g6w1_dup_name: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w2_safe_block: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w3_empty_block: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w4_mixed_safety: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w5_lparams: oracle=other graph=code=9(mutualWF)
  [PASS] V g6v1_crossref: oracle=OK graph=accept=True code=0(accept) steps=17 members_registered=True
  [PASS] V g6v2_member_fail: oracle=declTypeMismatch graph=code=1(declTypeMismatch) rollback(member_absent=True, later_ref=code=2(unknownConstant)) [oracle rollback leg = probe H1, handoff 006 G06]
  [PASS] V g6v3_dispatch_thm: oracle=thmTypeIsNotProp graph=code=8(thmTypeIsNotProp)
  [PASS] V g6v4_dispatch_def: oracle=OK graph=accept=True code=0(accept) steps=8
  [PASS] V g6v5_later_ref: oracle=OK graph=accept=True code=0(accept) steps=8

=== card 010 G02 decl-injection differential: 10/10 checks pass, 0 xfail known-gap, 0 fail (137s) ===
=== OK ===
[mem-guard] wall 137.1s peak RSS 1549MB rc=0
```

首行亦证工具链钉住生效：`oracle binary: Lean (version 4.33.1, …)`、
env 54 consts（含 RAW_MUTUAL 预注入的 g06v_f/g06v_g）。
图侧零改动成立：V1 两阶段 17 步 = header 锚链（2 锚）+ body 锚链（2 锚），
无任何 build_vm 变更。

#### G06 心跳 H4（verifier 串行链在跑）

链 = decl_injection 全集（a0+guard+bcd+g6）→ check_e2e →
defeq_branches（严格串行：lean_ref 的 /tmp oracle 文件是定长路径，
并行互踩）。日志 `/home/xkq/logs/010G/g06_full.log` / `g06_canary_e2e.log` /
`g06_canary_defeq.log`，状态文件 `g06_chain.status`。

（进行中，逐子步回填。）

### G06 完工段（2026-09-20，四 verifier 全绿）

#### Verifier 集原文（全链串行：`/home/xkq/logs/010G/g06_chain.status`）

1. **decl_injection 全集**（a0+guard+bcd+g6，`g06_full.log`）：

```
  (guard: graph from in-tree build_vm; 15 corpus cases × 2 runs)
  [XFAIL-KNOWN-GAP] D thm_imax: oracle=OK graph=accept=False code=8(thmTypeIsNotProp) steps=4
  [XFAIL-KNOWN-GAP] D thm_max00: oracle=OK graph=accept=False code=8(thmTypeIsNotProp) steps=4
  [PASS] W g6w1_dup_name: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w2_safe_block: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w3_empty_block: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w4_mixed_safety: oracle=other graph=code=9(mutualWF)
  [PASS] W g6w5_lparams: oracle=other graph=code=9(mutualWF)
  [PASS] V g6v1_crossref: oracle=OK graph=accept=True code=0(accept) steps=17 members_registered=True
  [PASS] V g6v2_member_fail: oracle=declTypeMismatch graph=code=1(declTypeMismatch) rollback(member_absent=True, later_ref=code=2(unknownConstant)) [oracle rollback leg = probe H1, handoff 006 G06]
  [PASS] V g6v3_dispatch_thm: oracle=thmTypeIsNotProp graph=code=8(thmTypeIsNotProp)
  [PASS] V g6v4_dispatch_def: oracle=OK graph=accept=True code=0(accept) steps=8
  [PASS] V g6v5_later_ref: oracle=OK graph=accept=True code=0(accept) steps=8

=== card 010 G02 decl-injection differential: 64/64 checks pass, 2 xfail known-gap, 0 fail (1079s) ===
=== OK ===
[mem-guard] wall 1079.8s peak RSS 1857MB rc=0
```

   （全集含 G02 既有 54 判定面，全 PASS——bcd oracle 批逐类与
   `lead_full_suite.log` 基线一致，含 `oracle[thm_max00] = OK` 等。）

2. **G6 节单独跑**（`G02_ONLY=g6`，`g06_subset.log`）：10/10 checks，
   rc=0，`[mem-guard] wall 137.1s peak RSS 1549MB rc=0`（H3 全文）。

3. **check_e2e canary**（`g06_canary_e2e.log`）：

```
Layer B  step graph vs RefVM: 15/15

=== M4.2 end-to-end check: A 15/15, B 15/15 === OK
[mem-guard] wall 440.8s peak RSS 1556MB rc=0
```

4. **defeq_branches canary**（`g06_canary_defeq.log`，48 行全 OK 含 meta 流
   与 G 臂）：

```
=== defeq branches vs lean: ALL OK ===
[mem-guard] wall 719.0s peak RSS 1819MB rc=0
```

5. **硬编码扫描**（铁律 3，命令原文）：

```
$ grep -n "CID_[A-Z0-9_]* *[+*/-] *[0-9]\|== *[0-9]\{2,\}" lean_vm/step_driver.py
（零命中，rc=1）
```

6. **git diff 自证 run_check 旧路径零变化**（`git diff lean_vm/step_driver.py`）：
   行为差异仅两处且默认参数下逐字节等价——
   `e2s = [check_e2(k) for k in kinds]` → `e2s = [check_e2(k, check_mode) …]`
   （check_mode 默认 CHECK_MODE_SAFE=0，`check_e2(k, 0) == check_e2(k)`）；
   `kinds=None` 支在 check_mode=0 时走原路径 E2 恒 0（check_mode≠0 时显式
   ValueError，防止静默改变 legacy 语义）。五套件直接构造 StepDriver 的调用点
   逐一核对：全部 `(decls)` 或 `(decls, max_steps=…)` 关键字形，零影响。

#### 改动清单（全部在本卡所有权内）

- `lean_vm/step_driver.py`：`ERR_MUTUAL_WF=9` 登记；`run_check` 第 4 参
  `check_mode`；新类 `InjectionEnv`（add_* 家族 + 两阶段 add_mutual + 回滚）。
  **lean_vm/build_vm.py 零改动**（本拍禁触，已成立）。
- `tests/test_decl_injection_vs_lean.py`：G6 节（W×5 + V×5）+ `G02_ONLY`
  旋钮扩展（g6 行级子集）+ RAW_MUTUAL 预注入（g06v_f/g06v_g 入
  ALL_DEFS/MY_ROOTS）+ **oracle 二进制钉住 4.33.1**（LEAN_CMD，走
  run_kdecl_oracle/dump_env 的 lean_cmd 覆盖参数）。
- `docs/VM_SPEC.md` §16.5、`docs/KERNEL_COVERAGE.md` G6 行、本文件。

#### 偏差与申报（终稿照抄）

1. **oracle 工具链漂移（须总控裁决）**：`~/.elan/bin/lean`（elan default
   `stable`）2026-09-20 实测已漂到 4.34.0，而 G02 验收跑（09-20 05:24
   `lead_full_suite.log`）与 AGENTS.md 均钉 4.33.1。本拍在套件内显式钉
   `~/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean`（冻结文件零
   改动、有覆盖参数）；**未动** `~/.elan/settings.toml`（不在所有权内）。
   回归表若依赖 `~/.elan/bin/lean`，请总控决定：改回 default 或在
   scripts/ 侧钉路径。
2. **码 9 只走 Python driver + #KDECL 差分通道**：码 9 在 driver 内抛、
   不进图（图无名字空间/块概念），故 C++ 引擎侧"抛 9"NOT-VERIFIED
   （与码 8 同款边界，归引擎 CHECK 通道拍）。
3. **G6 已知近似三条**（VM_SPEC §16.5）：partial 块 mode 位走 unsafe 值；
   多缺陷块的簿记/header 交错次序；成员 unsafe/partial 标志 × G10 门
   （码 7）= G03 差分面（本套件语料无 const_meta，门闭合）。safe checker
   引用 unsafe 常量在核侧的类别实测为 `.other`（"invalid declaration, it
   uses unsafe declaration …"），码 7 的类别名 unsafeConstUse 是图侧簿记名。
4. **RAW_MUTUAL 预注入使套件 env 52→54 consts**：仅 G6 的 V5 行需要
   oracle-expressible 的"后继引用已提交块员"；G02 各段语料与判定不受影响
   （全集 64/64 为证）。
5. **全量 23 套件回归未跑**（简报非目标：总控验收时跑）。新全集实测
   1079.8s/1857MB，回归表 decl_injection 行现帽 2100s/4000MB 仍适用。

### G06 拍验收（总控 2026-09-20，五道门收口：G06 CLOSED）

- 机械门：全量 23 套件回归 **23/23 rc=0**（`/home/xkq/logs/010G/g06_reg/`，
  oracle 钉 4.33.1 由回归脚本自检行证明）；decl_injection 全集 64/64+2 xfail
  wall 1492.8s / 峰值 2086MB——**注意回归表现帽 2100s 只剩 1.4x 裕量**，下次
  验收若再涨节需重测重定帽。
- 语义/架构门（总控亲读 diff）：add_mutual 分相=核相位（wf 簿记 → header 跑旧
  env :236-251 → 全注册 :253-257 → body 跑新 env :259-267 → 失败整块回滚）；
  码 9 不进图（图无名空间）；run_check 旧路径守卫（kinds=None ∧ mode≠0 →
  ValueError）；build_vm.py 零改动属实；铁律 3 零硬编码（码 9 属错误码空间）。
- 测试门：W×5 五条 well-formedness 全部 live oracle 对拍；V×5 含回滚可观察
  （member_absent + later_ref=code 2）与 dispatch 臂；RAW_MUTUAL 真内核块预注入
  oracle 基环境使 later_ref 行可差分表达。
- 诚实门：oracle 工具链漂移上报并已由总控仓库侧钉死（commit 6c938cb）；码 9
  引擎侧 NOT-VERIFIED（同码 8，归卡 013）。
- **G06 CLOSED。卡 010 余：G03（unsafe mode 图臂 + 重编译 + 引擎对拍）与
  run_whnf（ADR016-B driver 侧续推）两拍。**

### G03 拍表头（总控 2026-09-20 落盘，先于派工）

- 派工对象：图逻辑工程师（干净上下文），核段 0-5，日志 /home/xkq/logs/010G/g03_*.log。
- 任务：卡 010 G2-unsafe 拍——图侧 mode 臂（anchor E2 的 mode 位抑制 G10 safety 抛门）
  + 套件 G03 节差分（unsafe 自引用正例 / 后继 safe 声明引用已注册 unsafe → 码 7 /
  失败回滚）+ 重编译 scratch + 引擎对拍 34/34。
- 设计依据：本文件"设计备案"§2（unsafe 先注册后检查）+ G06 节已知近似三条（partial
  近似、多缺陷块次序、成员标志×G10=G03 差分面）；mode 载体已由 G06 落定=锚帧 E2
  kind+STRIDE*mode（ENV_FORMAT §2.8），**不再走设计备案原文的 T_NULL X 字段方案**。
- 探查先行（P1）：ENV 编码如何携带 safety/use_reject 位（ENV_FORMAT §2.3 +
  expr/tokens.py Encoder）与图侧 safety_i 读点（build_vm.py :5577-5591 一带）——答案
  落本板后才许动图；**若答案要求改 expr/tokens.py 或 reference/，停手上报**。
- 状态：IN PROGRESS。

### G03 执行日志（2026-09-20，核段 0-5，OMP_NUM_THREADS=3，PY=/home/xkq/miniconda3/envs/train/bin/python，日志 /home/xkq/logs/010G/g03_*.log）

#### 机器姿态（开工时实测）

`free -g`：总 30 / 可用 **25**；`ps --sort=-rss` 无大 env Python 求值、无 GPU 训练
（G02 拍时的用户训练会话已不在）。git 树干净，HEAD = `fd9d1f4`（G03 表头落盘提交）。
lean 4.33.1 钉住路径在位（套件 LEAN_CMD 机制沿用 G06）。

#### P1 结论（答案落板，此后才动图）

**① 什么形状的元数据会把 use_reject 位置 1**：`Encoder(consts, is_ctor=ctors,
const_meta={cid: m})`（`expr/tokens.py:353`，禁改文件零改动——const_meta 参数 G02/WP8
已存在）。per-cid 字典 m 需要 `kind`（constant_info_kind，`expr/tokens.py:101-108` =
ENV_FORMAT §2.5：0=Axiom/1=Definition/2=Theorem/3=Opaque）+ definition 的
`safety`（§2.4 编码 0=unsafe/1=safe/2=partial）。置位链：`_meta_flags`
（`tokens.py:445-473`）——`unsafe = m.is_unsafe or (kind==CK_DEFINITION ∧ safety==0)`
→ 旗标位 5；`kind==CK_DEFINITION ∧ safety==2` → 位 9；锚点写入
`use_reject = 1 if flags & (ENV_F_IS_UNSAFE|ENV_F_IS_PARTIAL)`（`tokens.py:569-580`，
ENV_FORMAT §2.3）。axiom/opaque 走 `is_unsafe: True`（T_ENV_SIMPLEVAL.V1，
`tokens.py:525-528`）。**无 meta 条目的 cid 锚点保持全零、F2=0**（`tokens.py:501-506`
"no metadata" 支）——门闭合。

**② 现有套件语料为何码 7 门闭合**：两处 Encoder 构造都不传 const_meta——
`InjectionEnv._check`（`step_driver.py:356` `Encoder(self._consts, is_ctor=self._ctors)`）
与套件 bcd 的 `_graph_check`（`test_decl_injection_vs_lean.py:274` 同形）。全部锚点
走 `tokens.py:501-506` 空锚支 → F2 恒 0 → 图侧门
`safety_i = reglu(const_i, _geq_expr(anc_f2, One))`（`build_vm.py:5645-5646`，读点
即 G10 抛门，rej 经 bad_i :5722-5723 → 拒码 select :6569）恒 0。所以今天的
"unsafe 自引用误杀 7"**尚未发生**——G03 必须先把 meta 送进编码器（driver 侧），
mode 臂才有对象。

**③ 要动哪些形状（step_driver/tests；expr/tokens.py 与 reference/ 禁改未破）**：
`InjectionEnv` 增一个 per-name 元数据表（{kind, safety}，add_* 家族各分支写入：
unsafe 定义 safety=0、mutual 成员按 §2.4 的 0/2、其余注入常量记 kind/safety=1），
`_check` 把它翻成 `{cid: meta}` 传给 Encoder。测试侧无形状变化（照常调
add_definition(is_unsafe=True)/add_mutual）；oracle 侧新增一段 RAW 预注入字符串
（套件内，照 RAW_MUTUAL 样板）。**结论：不需要改 expr/tokens.py 或 reference/**
→ 不触发停手条件。

#### P2 结论（mode 臂设计定案，编码前钉死）

**读点核实（brief 要求）**：safety_i 的抛点在 **INFER 派发**（ph1 相位，当前帧
= TASK_INFER，`build_vm.py:5547-5548` ph1、`:5633-5646` const_i/safety_i），不在
CHECK 链上。G02 的 E2 copy-forward（kickoff `fr1_E2_k=frE2` :5515、CK_G0 跳
`:5430`）覆盖到 **CK_G1 ST**（g3_mode 读点）为止；body 推理从 ck_g1_val
（`:5486-5505`）发起后，mode 必须随 TASK_INFER 帧下行。

**载体 = TASK_INFER 帧的 E2 高位**（phase ∈ {0,1,2}，+CHECK_E2_STRIDE*mode →
mode 只搭 phase-1 值（1→9），故 `ph_emit = _eq_expr(frE2, 2)`（:5547）**零改动**；
mode=9 的帧只可能是 phase-1）。X 不可用（I_LETD marker env :3613、I_ARG env
:3242、pl_prop env :4482 等已占），F2=soft 旗标。.nbE2 唯一消费者
（:1366）门在父帧=WHNF 上，不读 INFER 帧 → 无误读面。

**注入点（全部 O(1) select/reglu 级）**：
1. kickoff 头检 infer 发射（:5517-5518 `fr2_E2_k`，mode=锚帧 frE2 解码，ck_kick 门内消费）；
2. ck_g1_val 体检 infer 发射（:5496，mode=g3_mode——G02 copy-forward 已覆盖该读点）；
3. INFER 派发 5 个子发射（peel_end :5586 / lam :5597 / pi :5609 / let :5621 /
   proj :5712，`fr2_E2_i = One + 8*inf_mode`，inf_mode 从当前帧解码）；
4. ST 链 2 跳续体发射 I_PI（APP 参数，:3193）/ I_LAMSORT（lam body，:3411）/
   I_LETD（let body，:3615）：mode 读 **SD-1 位置**的帧（交付协议把 D 落在续体
   ST 上，紧邻下方是父任务帧；kind 门在 TASK_INFER 上，非 INFER 邻帧 → mode=0
   = 不抑制）。自洽性论证：单次 run_check 是单一 mode 的链，SD-1 死帧即便读歪
   也只可能给出本链 mode 或 0——**mode=0 链不可能被误抑制**；读丢方向只产生
   "mode 丢失 → 假拒 7"，由差分行实证。
5. 门：`safety_i = reglu(const_i, reglu(One - inf_mode, _geq_expr(anc_f2, One)))`
   （:5646；inf_mode=0 时 reglu 链逐值还原旧合取，kinds=None 旧路径 E2 全 0 →
   所有新节点取值与旧图逐值相同 → 判定/步数不变性由 guard/bcd/canary 对拍证明）。

**已知近似（记 VM_SPEC §16.6）**：pi **codomain** 推理（I_PIL1 :3483-3485，3 跳链
SD-1 是中间 WHNF 帧）不携带 mode；P_EMIT 排序走（I_PIL2/I_SORTEM/em_more）无
const 臂、无需 mode；DEFEQ 链 soft 发射（PI_T/PI_TY/pl_prop/et_app/es_app/ST_UL/
ul_yes——mode=1 pass 的 CK_TY defeq 可达；DEFEQ 帧 V1/X/E2/F2 = t_pos/t_env/
s_pos/s_env 全占，mode 无处搭）不携带——核侧 unsafe checker 下这些推理会成功，
图侧可能 decline/假 7。本拍行集（顶层/APP 参数/lam body 自引用）均不经过这些点。

**mode=1 下的语义对照（核引）**：header+body 两相都用 unsafe-mode checker
（`K/environment.cpp:165-169` 头检、`:172-177` 体检）→ 抑制覆盖头检与体检两发射；
`add_theorem` 恒 safe checker（`:196`）→ kind 解码与 mode 无关（G02 已定）；抛门
本体 = `infer_constant` 的 unsafe/partial use（`K/type_checker.cpp:110-117`）。

#### G03 心跳 H2（图臂落地 + 实测翻案三件）

图臂最终形态 = **9 处编辑**（build_vm.py，逐处 py_compile）：kickoff 头检发射
`fr2_E2_k = One + reglu(ck_mode_k, One*8)`、ck_g1_val 体检发射（g3_mode）、
INFER 派发 `inf_mode` 解码（ph_emit 零改动——mode 只搭 phase-1 值 1→9）、
5 个子发射（peel_end/lam/pi/let/proj）继承、门与**降级行共 seat7_gate**。

实测翻案（/tmp 探针， toy env 48 consts，直连 run_check）：

1. **降级行死循环坑（编码时抓到，P2 备案里没有）**：首版只抑制 `safety_i`，
   `const_i = reglu(const_i, One - _geq_expr(anc_f2, One))`（原 :5647）仍把
   F2=1 的 const 从推理臂**降级**掉——gate 抑制后该 const 既不抛也不推理，
   落入默认 WHNF delta 臂，自引用值自展开**无限循环**（探针 case 卡死实抓）。
   修复 = 降级与抛门共用 `ck7_gate = reglu(One - inf_mode, _geq_expr(anc_f2, One))`：
   mode=1 时降级消失 → const 臂正常推理 → A=ENV_HDR.V1（声明类型）= 核
   instantiate_type_lparams 语义。
2. **SD-1 读点失效（P2 备案的 ST 链 2 跳传播被实测否决）**：I_PI/I_LAMSORT/
   I_LETD 发射点读 SD-1 帧的 E2 高位拿不到父帧 mode（交付协议落点 D 的下方是
   死子树顶帧，不是父任务帧；实测 app-arg/lam-body 两形状 m1 仍 7）——且这些
   ST 六槽全占（V1/V2/X/E2/F2/V0），mode 无处搭。**已回退**这 3 处编辑与
   mb_mode 定义（死机器不留），两个形状按防线进 KNOWN_GAPS（xfail，实测证据
   上板）。传播覆盖面 = 顶层发射 + INFER 派发 5 子发射（链内所有不跨 ST 续体
   交付的推理）。
3. **探针实测终态**（图形如上；判据=直连 run_check 的 (accept, code, steps)）：

```
legacy kinds=None   : (True, 0, 8)     # E2=0 逐字不变
thm Nat:2 (mode 0)  : (False, 8, 4)    # kind 闸门不受影响
def Nat:2 (mode 0)  : (True, 0, 8)     # legacy 显式 kinds
def Nat:2 (mode 1)  : (True, 0, 8)     # mode 臂 armed 但无 meta → 惰性
unsafe selfref m=0  : (False, 7, 5)    # meta-armed + mode=0 → 门照抛（=G02 基线行为）
unsafe selfref m=1  : (True, 0, 8)     # mode 抑制生效，自引用放行
app-arg  m1         : (False, 7, 11)   # KNOWN GAP（I_PI 跨续体不携带 mode）
lam-body m1         : (False, 7, 11)   # KNOWN GAP（I_LAMSORT 同）
```

已知近似（照 G06 惯例记 VM_SPEC §16.6）：APP 参数与 lam/let body 的自引用在
mode=1 下假拒 7（mode 位跨 ST 续体交付不存活）；pi codomain（I_PIL1）与
DEFEQ 链 soft 发射同理。行集构造不依赖这些形状；假拒方向与 thm_imax 缺口
同类（不健全方向是"多拒"，与图既有保守侧一致）。

#### G03 心跳 H3（接手续拍：验证已完成件 + 双链事故与清场，2026-09-20）

接手时代理在 H2 后死亡，工作树已含全部代码件（build_vm 9 处编辑、
InjectionEnv meta 表、测试 G03 节），py_compile 三件过。接手顺序：

1. `G02_ONLY=g3` 子集首跑（本代理独占机器时段）：7/7 + 2 XFAIL，rc=0，
   `[mem-guard] wall 323.0s peak RSS 1547MB rc=0`，oracle 七类与 H2 探针
   终态逐条一致（`/home/xkq/logs/010G/g03_subset.log`）。
2. **双链事故（如实记，教训落档）**：前任的 verifier 链（g03_chain.sh）
   实际未死——它跑完了 full/compile/engine（08:59-09:25），其 defeq 一直
   跑到 09:42:46、stepgraph 到 09:52+；本代理误判"链死于引擎步"（status
   文件当时缺 engine rc 行），另起 chain2 并行补跑，两条链 09:30-10:00
   并行且写**同名 canary 日志**（g03_canary_defeq.log / 
   g03_canary_stepgraph.log 互相截断）。处置：`pgrep -af` 看清后按 PID
   杀两链与四个子进程；**作废全部并行窗口的 canary 日志**，以 g03_can2
   串行重跑为准。教训：接手"死亡"代理先 `pgrep -af <脚本名>` 确认真死
   ——status 文件缺 rc 行 ≠ 进程死了；并行窗口的证据一律作废重取。
   干净窗口（08:59-09:25，本代理 09:30 才起链）的证据有效。
3. 垃圾件清理：chain2 的 pre 编译因 step() 未切 cwd 实际在真仓库编了
   post 图（产物与 scratch md5 相同 `08bb2af7032d26fc9ace6558349e7d7b`），
   已删除 `model/step_vm_010g03_pre.sbin`；HEAD 基线编译改在 can2 链后
   以 `git worktree` + `cd` 子壳正确重做。

#### G03 心跳 H4（verifier 原文汇拢，can2 串行链全绿）

1. **G03 节单独跑**（`G02_ONLY=g03`，本代理独占时段，`g03_subset.log`）：

```
  [PASS] A g03a_selfref: oracle=OK graph=code=0(accept) steps=8 registered=True
  [PASS] B g03b_later_ref: oracle=other graph=code=7(unsafeConstUse) steps=5
  [PASS] B g03b2_unsafe_ref: oracle=OK graph=code=0(accept) steps=8 registered=True
  [PASS] C g03c_body_fail: oracle=declTypeMismatch graph=code=1(declTypeMismatch) rollback(member_absent=True, later_ref=code=2(unknownConstant))
  [PASS] E g03e_mutual_xref: oracle=OK graph=code=0(accept) steps=17 members_registered=True
  [XFAIL-KNOWN-GAP] G g03g_arg_selfref: oracle=OK graph=code=7(unsafeConstUse) steps=11
  [XFAIL-KNOWN-GAP] G g03h_lam_selfref: oracle=OK graph=code=7(unsafeConstUse) steps=25
=== card 010 G02 decl-injection differential: 7/7 checks pass, 2 xfail known-gap, 0 fail (323s) ===
=== OK ===
[mem-guard] wall 323.0s peak RSS 1547MB rc=0
```

   B 行对 = mode 位被消费的证明（同语料，mode=0 抛 7 / mode=1 放行）。

2. **decl_injection 全集**（a0+guard+bcd+g6+g03，干净窗口
   08:59-09:21，`g03_full.log`）：

```
=== card 010 G02 decl-injection differential: 71/71 checks pass, 4 xfail known-gap, 0 fail (1285s) ===
=== OK ===
[mem-guard] wall 1285.5s peak RSS 1888MB rc=0
```

   （4 xfail = thm_imax/thm_max00 存量 + g03g/g03h 本拍新增。）

3. **scratch 重编译**（--sparse，`g03_compile.log`；HEAD 基线 =
   worktree 隔离编译 `g03_pre_compile2.log`）：

| | HEAD 基线 | G03 post | Δ |
|---|---|---|---|
| graph dims | 26012 | 26023 | **+11** |
| lookups | 2901 | 2901 | **+0** |
| d_model（schedule/weights） | 4826 / 6258 | 4826 / 6260 | +0 / +2 |
| heads_global / ffn | 651 / 2707 | 651 / 2707 | +0 |
| nnz | 192,821 | 192,867 | **+46** |
| .sbin 字节 | 18,906,018 | 18,910,254 | +4,236 |
| md5 | `fc71fa5d44cb73630af41113d61d6aed` | `08bb2af7032d26fc9ace6558349e7d7b` | |

   基线交叉确认：HEAD 编译 md5 `fc71fa5d…` 与 G02 验收 scratch 件完全一致
   （图自 G02 后未动过）。+0 lookups 与臂形一致：mode 臂是既有 fetch 之上的
   select/reglu 算术（无新 fetch_by_position）。

4. **引擎对拍**（SBIN 钉新 scratch 件，两次独立取证 rc=0）：

```
=== H3 engine vs RefVM: 34/34 verdicts correct ===
    argmax vs softmax streams identical: 34/34
    known-value checks: 3/4        ← 与 G02 基线逐字一致（big_mul 存量标注，非倒退）
[rc=0]（09:21 g03_engine.log 与 09:30 g03_engine2.log 两跑）
```

5. **canary 三件**（双链事故后 can2 串行重跑，全部干净窗口）：

```
e2e:        === M4.2 end-to-end check: A 15/15, B 15/15 === OK
            [mem-guard] wall 248.4s peak RSS 1550MB rc=0
defeq:      === defeq branches vs lean: ALL OK ===        (48 行全 OK)
            [mem-guard] wall 668.2s peak RSS 1559MB rc=0
stepgraph:  === step graph vs RefVM infer/defeq: 84/84 (0 pinned: 0 M3 + 0 P7.5c) ===
            [mem-guard] wall 1230.0s peak RSS 1480MB rc=0
```

6. **旧路径不变性证明**（新图 vs G06 验收图，判定+步数逐字 diff）：
   a0 段 17 行、guard 段 15 行（整份 check_e2e 语料 kinds=None vs 哨兵）、
   bcd 段 19 行（gate_off + B/C/D 全部行含步数）、g6 段 10 行——
   **零差异**。引擎 34/34 + 三 canary 判定与步数不变为旁证。

7. **硬编码扫描**（铁律 3）：`grep -n "CID_[A-Z0-9_]* *[+*/-] *[0-9]\|== *[0-9]\{2,\}"`
   在 build_vm.py / step_driver.py 零新增（仅存量：2242 注释常数、5061
   `CID_P2MK + 1` 已知项）；diff 新增行字面量扫描零命中（mode=8/9 属
   §2.8 编码空间常量）。

### G03 完工段（2026-09-20）

改动清单（全在所有权内）：`lean_vm/build_vm.py`（mode 臂 9 处：kickoff/
ck_g1_val 发射、inf_mode 解码、5 子发射继承、ck7_gate 抛门+降级共闸）；
`lean_vm/step_driver.py`（InjectionEnv per-cid meta 表 → Encoder
const_meta，add_* 各分支写 kind/safety，回滚清 meta）；`tests/
test_decl_injection_vs_lean.py`（G03 节 A/B/C/E/G 组 + KNOWN_GAPS 两条 +
RAW_G03 预注入）；`docs/VM_SPEC.md` §16.6；`docs/ENV_FORMAT.md` §2.8
mode=1 行改"已接"；`docs/KERNEL_COVERAGE.md` G2 行收口 unsafe 支；本文件。
artifact：`model/step_vm_010g03_scratch.sbin`（登记由总控做；真值
`model/step_vm_new_sparse.sbin` 未动）。

偏差与申报：
1. 双链事故（H3）：并行窗口的 canary 日志全部作废重取；两链的 defeq 均
   以正常时长（779s/771s）跑完、结局全 OK，且 oracle 通道有 id 顺序校验，
   但**按防线从严**只认 can2 重跑件。
2. 码 7 mode 臂的已知缺口（VM_SPEC §16.6，XFAIL 登记）：APP 参数 / lam·let
   body 自引用在 mode=1 下假拒 7（mode 位跨 ST 续体交付不存活）；pi
   codomain 与 DEFEQ 链 soft 发射同理不携带。保守侧（多拒）方向。
3. C++ 引擎侧"mode=1 抑制码 7"NOT-VERIFIED（引擎不经过 CHECK 链，
   §16.4 同款边界）。
4. 卡 010 余项：run_whnf（ADR016-B driver 侧续推）另拍。



### G03 拍验收（总控 2026-09-20，五道门收口：G03 CLOSED）

- 机械门：全量 23 套件回归 **23/23 rc=0**（`/home/xkq/logs/010G/g03_reg/`，
  oracle 钉 4.33.1 自检行在案）；decl_injection 全集 71/71+4 xfail wall 1755.4s
  / 峰值 1981MB——帽 2100→**2700**（>1.5x 裕量，随节增长的重测规矩写进脚本注释）。
- 语义/架构门（总控亲读 diff）：mode 只搭 phase-1 值（1→1+8），phase-2 比较零
  改动；`ck7_gate = reglu(One - inf_mode, anc_f2≥1)` 在 inf_mode=0 时还原旧合取
  （legacy 逐字节不变的代数证明）；**抛门/降级共闸**是本拍最有含量的发现——
  只抑抛门会让 F2=1 常量既不抛也不推断、落 WHNF delta 臂无限自展（代理探针
  卡死实抓），与内核 infer_constant 的 checker 判定（type_checker.cpp:110-117）
  对齐。铁律 3：diff 新增字面量扫描零命中。
- 测试门：G03 节 7/7+2 XFAIL；B 行对（同语料 mode=0 抛 7 / mode=1 放行）是
  mode 位被消费的直接证明；XFAIL/XPASS 协议核实（agreeing 即 FAIL 入册）。
- 诚实门：并行互踩事故自曝 + pgrep 确认真死教训落板；两处 XFAIL（mode 跨 ST
  续体不存活 → APP 参数/lam·let body 自引用假拒 7，保守侧）= 卡 011+ 议题；
  引擎侧 mode=1 NOT-VERIFIED（§16.4 同款边界）。
- **G03 CLOSED。卡 010 余最后一拍：run_whnf（ADR016-B 方案 B，driver 侧续推）。**

### G04 拍表头（总控 2026-09-20 落盘，先于派工）——run_whnf（ADR016-B 方案 B）

- 派工对象：同链驱动器工程师（续用已验收代理，上下文续热），核段 0-5，日志
  /home/xkq/logs/010G/g04_*.log。
- 任务：`lean_vm/step_driver.py` 新方法 `run_whnf`——把核 whnf_core 的 proj 回灌
  再归约循环（K/type_checker.cpp:504-508 外层 while）搬到调用方：每轮=一个图
  TASK_WHNF，焦点不前进（pos 与 env 双同）即停，预算 TimeoutError 复用。
  **图（build_vm.py）零改动、零重编译、零引擎跑**——图合同 ADR016 定案不动。
- 不引入任何 Python 语义近似（判定全在图内，driver 只做循环与停机判定）。
- 验收：新差分=G1/a1 载体（Nat/Lst/MA-MB/IV/MyTree 顶层 raw-field 件）run_whnf
  结果与 oracle `#ORACLE`（WHNF 通道，lean_ref.run_oracle）逐字一致；既有
  stepgraph/refvm whnf 套件零基线变动（由本拍 canary + 总控回归证明）。
- 文档：VM_SPEC §16 收尾小节（driver 侧 whnf 循环合同）+ 卡 010 状态收口。
- 状态：IN PROGRESS。

### G04 拍执行记录（接手代理 G2b，2026-09-20，核段 0-5，日志 /home/xkq/logs/010G/g04b_*.log）

- **IV2 裁决（诊断任务）**：iv/eG4IV2 = **真不收敛，图侧语义缺口，不是预算问题**。
  最小 env（stage C 正式口径）证据链（`g04b_diag.log` + 正式节 `g04b_full4.log`）：
  raw TASK_WHNF 120 步 HALT，焦点 = `Nat.casesOn (Nat.add 0 1) …`（主前提未 whnf，
  非 head-normal）；对同焦点重发幂等（r0 120 步→同焦点，r1 34 步→焦点不动返回）。
  oracle 4.33.1 现跑 = `LitNat(6)`。核侧对照：`K/inductive.h:93`
  `major = whnf(major)`（casesOn 主前提先 whnf）+ `K/type_checker.cpp:511-533`
  （App 分支 iota 回灌）——图的 I_CASE 无此续推，driver 循环结构上补不了。
  probe7 全闭包 env 另一态：≤2000 步不 halt。两态皆与 oracle 不一致。
  **处置**：不动图（越 G04 边界，修复归卡 011+ I_CASE 主前提续推），
  登记 `KNOWN_GAPS["g04iv_eG4IV2"]`（XFAIL 带理由串 + kernel 引用），
  行保持常跑，图修复日按 XPASS 规程摘除。预算不改：run_whnf 默认
  2000×16 保留——没有任何行是"合法慢"（10 个 PASS 行 raw 一轮即达头范式，
  最长 d4=1227 步），不适用 d6 的 720→1100 先例。
- **正式差分节落地**：`tests/test_decl_injection_vs_lean.py` G04 节，
  11 行 = nat d1/d3/d4 + lst eL1/eL2/eL3 + mu eG4MU1/eG4MU2 + iv
  eG4IV1/eG4IV2 + tree eG4W；期望全现跑 `#ORACLE` WHNF（run_oracle_mixed，
  4.33.1），零预置；交付模式每族一个子进程（G04_FAMILY 协议），树上任何
  时刻只有一个大 env 求值器。
- **环境最小化实测课（两次翻车）**：
  ① **toy 表不能按静态引用闭包剪**：首版 stage C 从 carrier roots 闭包，
  nat 三行全卡 `Proj(P2,0,Nat.brecOn.go …)`@30/60/90（`g04b_full.log`）；
  bisect 定位（`g04b_bisect.log`）：单加 `Nat.pred` 即把 d1 翻正为 @122 =
  全闭包基线——§11.11 cs_build 的 succ 规则 rhs 是**运行时现造的**
  `Nat.pred t`，存表里根本没有这条静态引用。② **反过来，非 nat 族也不能钉
  toy 表**：全族钉住后 iv env 77 常量，忠实 Nat.below/brecOn 大树把纯 Python
  求值推到约 20MB/步，iv 子进程烧穿 6GB 线被 guard 主动杀
  （`g04b_full3.log`、`g04b_ivtrace.log` rc=-9；IV1@192 步即 3.85GB）。
  定版 = `G04_KEEP_TOY = {"nat"}`：nat 族闭包种子并入 toy 全名整表保留，
  其余族 carrier-roots 闭包照旧（lst 51/mu 54/iv 55/tree 48 常量级）。
  另修一处种子 bug：保留的替换版 `Nat.brecOn` 静态引用 `Nat.brecOn.go`，
  闭包不并 toy 全名时编码期 KeyError（`g04b_full2.log`）。
- **最终 verifier（G04 节单独，guarded 6000MB）**：`g04b_full4.log`——
  10 行 PASS + `g04iv_eG4IV2` XFAIL-KNOWN-GAP（oracle=LitNat(6)，
  run_whnf=stuck `Nat.casesOn (Nat.add 0 1)…`，steps=346；行原文在 log），
  汇总行 `=== card 010 G02 decl-injection differential: 11/11 checks pass,
  1 xfail known-gap, 0 fail (500s) ===` + `=== OK ===` +
  `[mem-guard] wall 500.0s peak RSS 3855MB rc=0`（6GB 纪律内）。
- canary 自验（均 guarded 6000MB，cores 0-5，train env）：
  ① decl_injection **全文件**一遍（含 G04），`g04b_canary_full.log`：
    `=== card 010 G02 decl-injection differential: 82/82 checks pass,
    5 xfail known-gap, 0 fail (1894s) ===` + `=== OK ===` +
    `[mem-guard] wall 1894.5s peak RSS 4284MB rc=0`。5 个 XFAIL = 既有 4 个
    （D thm_imax / D thm_max00 / G g03g_arg_selfref / G g03h_lam_selfref，
    行与登记前逐字一致，零基线变动）+ 本拍新增 G04 iv/eG4IV2。
  ② 子集快跑 `G02_ONLY=a0,guard,g03`，`g04b_canary_subset.log`：
    `=== card 010 G02 decl-injection differential: 40/40 checks pass,
    2 xfail known-gap, 0 fail (872s) ===` + `=== OK ===` +
    `[mem-guard] wall 871.9s peak RSS 1545MB rc=0`。
  ③ `py_compile` lean_vm/step_driver.py + tests/test_decl_injection_vs_lean.py
    通过；G04 节单独跑见上 `g04b_full4.log`（11/11 + 1 xfail，0 fail）。
- 状态：**G04 执行完毕，待总控审核**（step_driver.py 沿用继承 diff 的
  run_whnf 实现，未再动；文档 §16.7 与本记录已同步）。

### G04 c2 补强：rounds≥2 覆盖（总控审核意见，2026-09-20，代理 G2b）

- 触发：总控指出 11 行语料未实证续推轮。核实中先纠正一处口径——
  run_whnf 的停机判定本身需要一轮幂等确认，**11 行实测全部 rounds=2**
  （`g04b_c2_full5.log` 各行 rounds 列；此前记录只贴 steps，无 rounds
  观测）。总控要的真覆盖 = "round 交付非 head-normal 焦点、下一轮继续
  推进"，探针系列把这条钉死：
  ① `g04b_c2_probe1.log`：经 `PProd.fst/snd` accessor def 的嵌套投影载体
  **活锁**（2000 步不 halt、RSS 4001MB 被 guard 杀）——universe 多态
  accessor 在当前 univ_arity=0 编码下不可 whnf（B13/WP1 债，非 G04 边界）。
  ② `g04b_c2_probe3/4.log`：直接编码 `Proj(P2,…)` 节点载体（PProd→P2
  toy 约定）→ 与 oracle 逐字一致（`add 1 3 →4`、`.2.1 →9`）、rounds=2；
  但 probe4 的 RAW 对照行显示**单轮 run() 到达完全相同的值**——
  当前图 raw whnf 对 proj 链也直达 head-normal，round-2 是幂等停。
  ③ 观测到的唯一"焦点跨轮真推进"= IV2（`g04b_diag.log` r0 env
  3599→3827），终点 stuck，已登记 XFAIL。
- **负面结论（任务要求的穷尽分支）**：当前图上不存在任何闭载体形状使
  续推轮成为语义必需；raw-field 差额对一切可达闭形状潜伏。已写入
  §16.7 c2 段；XFAIL iv/eG4IV2 的"round-1 后幂等"证据链引用之。
- 形式化落盘：语料加 proj 族 2 行（共 13 行）——raw-field 交付一旦回归
  （I_PROJ 演进），这两行自动变续推正例；行输出加 `rounds=` 列
  （`_G04Drv._run_loop` 子类计数，纯观测，run_whnf 签名与语义未动）；
  `G04_KEEP_TOY={nat,proj}`（proj 载体归约 Nat.add 需要 pred 机件，
  同 nat 教训）。
- verifier 原文（G04 节单独，guarded 6000MB，cores 0-5）：
  `g04b_c2_full5.log`——
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
  [XFAIL-KNOWN-GAP] G04 iv/eG4IV2: oracle=LitNat(value=6) run_whnf=App(fn=…Nat.casesOn (Nat.add 0 1)… steps=346 rounds=2
  [PASS] G04 tree/eG4W: oracle=LitNat(value=6) run_whnf=LitNat(value=6) steps=749 rounds=2
  [PASS] G04 proj/(PProd.mk (Nat.add 1 3) Nat.zero…: oracle=LitNat(value=4) run_whnf=LitNat(value=4) steps=14 rounds=2
  [PASS] G04 proj/(PProd.mk Nat.zero (PProd.mk (Na…: oracle=LitNat(value=9) run_whnf=LitNat(value=9) steps=33 rounds=2
=== card 010 G02 decl-injection differential: 13/13 checks pass, 1 xfail known-gap, 0 fail (558s) ===
=== OK ===
[mem-guard] wall 558.8s peak RSS 3827MB rc=0
```
  （IV2 行 stuck 项全文在 log，此处截断。）
- canary 复验（全文件含 c2）：`g04b_c2_canary.log`——
  `=== card 010 G02 decl-injection differential: 84/84 checks pass, 5 xfail
  known-gap, 0 fail (1995s) ===` + `=== OK ===` +
  `[mem-guard] wall 1995.7s peak RSS 4295MB rc=0`。84 = c2 前 82 + proj 族
  新增 2 行；5 个 XFAIL 与基线逐字一致（既有 4 + iv/eG4IV2）。
  py_compile（tests + step_driver）由总控复跑 `COMPILE-OK`。
  注：本 canary 是代理会话额度中断后 setsid 脱管进程独立跑完的，rc=0 有效。

---

## 总控验收记录：G04 拍（2026-09-21，核段 8-13）

**五道门全过，G04 验收通过，卡 010 整卡收口（CLOSED）。**

- **机械门**：`git status` 恰 4 文件（step_driver / tests / VM_SPEC / handoff），
  diffstat +603/-2；`git diff --name-only lean_vm/build_vm.py lean_vm/ref_vm.py
  expr/ compiler/ model/ engine/` = 0（图侧与冻结机零触碰，符合"方案 B 图合同
  不动"架构裁决）；py_compile 复跑 OK。
- **语义门**：IV2 定性 = 图侧 I_CASE 主前提续推缺口，不是预算问题——总控独立
  核对核侧引用：`/home/xkq/lean4/src/kernel/inductive.h:93` 实测即
  `major = whnf(major);`，与登记逐字一致；两态证据（最小 env 幂等 stuck /
  probe7 全闭包不 halt）均在 log。XFAIL 走 XPASS 协议、行保持常跑，登记不
  掩盖。预算 2000×16 维持的裁决接受（无"合法慢"行，d6 先例不适用）。
- **架构门**：run_whnf 纯迭代器零 Python 语义（diff 亲验）；§16.7 申报驱动
  器通道边界（C++ 引擎/编译通道不经过），与 §16.4/16.6 同构，接受。
- **测试门**：总控独立复跑 decl_injection 全量（c2 前代码态）——
  **82/82 + 5 xfail rc=0**（`g04b_lead_verify.log`，wall 2442s peak 4278MB，
  guarded），IV2 stuck 项与代理输出逐字一致 = 判定可复现；c2 后全文件
  canary 84/84 rc=0（上条）。既有 XFAIL 四行零基线变动。增补 4 验收条款
  "whnf 套件（OE 族/引擎通道）零基线变动"由总控补跑钉死：
  `verify_engine_vs_refvm` **34/34 rc=0**（560.4s/163MB）+
  `test_reducenat_graph_vs_lean` **rc=0**（1012.0s/3951MB），
  同 log `g04b_oe.log`，guarded/cores 8-13。
- **诚实门**：代理自报三处口径差异（13 vs 11 计数、probe8 未复查 IV2、
  12→10 笔误已由总控勘正）；c2 负面结论按证据写死（当前图无闭形状使续推轮
  语义必需），未把幂等确认轮粉饰成续推实证。审核意见触发补拍后交付质量
  反而更高（探针挖出 univ_arity accessor 活锁新债）。
- **遗留登记（全部转卡 011+，见卡 011 增补）**：① I_CASE 主前提 whnf 续推
  （IV2，摘 XFAIL 的正门）；② universe 多态 accessor def 在 univ_arity=0
  编码下 whnf 活锁（c2 probe1，4GB@2000 步实证）；③ 归约层 ENV 动态名字
  依赖排查（cs_build 现造 `Nat.pred t` 类，"环境是数据"边角）；
  ④ mode 位跨 ST 续体（G03 登记项，不变）。
- 回归帽：decl_injection `2700|4000` 复核——c2 全量最坏实测 2442s（总控复跑，
  与 GPU 训练并行、核段 8-13）< 2700，**帽不动**；卡 011 若再增语料按注释
  规程复测。
- 本拍无 artifact 变更：`step_vm_010g03_scratch.sbin` 即卡 010 终验证件；
  晋升与否归卡 011 开工拍决策（真值表已同步注记）。

---

## 执行记录：卡 015 拍 2（图逻辑工程师，2026-09-21）——n2z 电路 + I_PROJ 通用抽取

本文档末尾追加本拍执行记录（落盘板，per AGENTS.md §八.4）。全拍在
`tests/test_decl_injection_vs_lean.py` 两个子集 + G04 uprod 差分行上验收，
全量回归与 23 套件归拍 3。改动文件：`lean_vm/build_vm.py` +
`tests/test_decl_injection_vs_lean.py`（图侧唯一触点）。

### 组件 1：is_prop 的 n2z 电路（D8，K/level.cpp:174-186）

- 复现（`G02_ONLY=thm_imax,thm_max00`，comp1_repro_imax_max00.log）：
  `oracle[thm_imax]=OK or oracle[thm_max00]=OK`、graph `code=8`，
  stored type 实测 `injX_imax=Sort(LIMax(LSucc(LZero),LZero))`、
  `injX_max=Sort(LMax(LZero,LZero))`——与 P1 探针逐字一致。
- **两处判据**（不是一处）都改接 n2z 电路，替换 syntactic 根比
  `_kind_eq_raw(★, KL_ZERO, One)`：
  ① `pl_prop`（PI_LVL 证明不可约链，build_vm.py ~4498-4507）；
  ② CHECK 链 `g3`（code-8 拒绝臂，~5495-5500）——拍 2 探针发现 code 8 正是
  `g3` 抛的，仅改 pl_prop 不改 g3 是无效修（首轮实测仍 XFAIL）。
- 电路形态：单树递归 `_n2z(pos, depth)`，深度帽 8，逐 kind 按内核规则
  Zero→1；Param/MVar/Succ→0；Max→两子树∧；IMax→只看 rhs。共享 v1 子树
  （`nz_v1` 同时喂 Max 的 AND 门和 IMax 的 rhs 支，build_vm.py ~3688-3707）。
  **共享是关键**：初版 `max_v` 与 imax 支各现建一次 `_n2z(v1,·)`，递归树按
  3^d 展开（d=8 → 3,280 节点/电路），dims 爆到 130,975(+403%)/lookups
  22,579(+678%)；共享后按 2^d-1=255 节点展开，回落 34,175/4,429
  （实测，D 行子集 2194s→197s）。
- 验收（`G02_ONLY=thm_imax,thm_max00,def_imax,thm_sortraw_imax,thm_sortraw_max00`，
  197s，comp1_drows_all_v2.log）：
```
  [PASS] D thm_imax: oracle=OK graph=accept=True code=0(accept) steps=15
  [PASS] D thm_max00: oracle=OK graph=accept=True code=0(accept) steps=15
  [PASS] D def_imax: oracle=OK graph=accept=True code=0(accept) steps=15
  [PASS] D thm_sortraw_imax: oracle=thmTypeIsNotProp graph=accept=False code=8(thmTypeIsNotProp) steps=6
  [PASS] D thm_sortraw_max00: oracle=thmTypeIsNotProp graph=accept=False code=8(thmTypeIsNotProp) steps=6
```
- KNOWN_GAPS 摘除 thm_imax/thm_max00（XPASS 协议：转绿后仍留册即判 FAIL，
  实测首绿即 XPASS-FAIL，摘除后 PASS）。
- bcd 全节（comp1_bcd_full.log，647s）：`21/21 checks pass, 0 fail`——含
  gate_off_kind0、thm_arrow（Pi-body-Prop 证明不可约链走 pl_prop n2z）无回归。
- 全量增量（`--sparse`，step_vm_015_full_scratch.sbin，compile 42s）：
  基线 26,023/2,901/192,867 → **34392/4489/235030**，即 dims +8,369(+32%)、
  lookups +1,588(+55%)、nnz +42,163(+22%)。ADR 022 预估 +500-1500 dims 偏
  乐观（per-node 成本在该图代数下 ~16 dims + 3 lookups）；O(1)、图深度不增
  成立。**风险注记：dims/lookups 增大会使 decl_injection 全量回归延长，
  bcd 全节已 647s（基线全文件 ~2000s），拍 3 全量须盯 2700s 回归帽。**

### 组件 3：univ 多态 accessor whnf（B13 活锁）

- 复现（G04 uprod 差分行，comp3_upd_probe*.log）：主链 env（_instantiate_dump
  后无 LParam），`UProd.fst` delta → Lam3 → body `Proj(UProd,0,BVar0)`，child
  whnf 到 `@UProd.mk u Nat Nat 3 4`（2 参 + 2 域），随后 **pr_stuck**。
  活锁/卡死的根因 = I_PROJ 的 `pr_full`（build_vm.py ~3095）只认
  `App(App(Const(18),a),b)` 两参骨架；真实 ctor 载 4 参骨 + nparams=2，
  永不匹配 → proj 反复 re-stick → 2000 步/4GB（g04b_c2_probe2.log 的历史
  活锁记录）。**LParam 不是阻塞点**（ADR 候选① unfold-级实例化不适用）；
  阻塞点是 field 抽取本身。ADS 候选②（try_unfold_proj_app 式快捷）也不绕开
  抽取。按内核规格修：`reduce_proj_core`（K/type_checker.cpp:420-441：
  get_app_args 全骨架 + head 必须是目标结构 ctor + `args[nparams+idx]`）。
- 修法（build_vm.py ~3086-3117）：`_app_arity`/`_head_of` 剥全骨 +
  `_is_ctor_any`（metadata ctor 判据，legacy P2.mk 回退）+ `_struct_ind` 取
  induct cid（**不是 `_struct_nid`**——首实现用 nid 当 cid 读 nparams=0，
  field 错取 args[0]）+ nparams=INDVAL.V1 + 守卫 `nparams+idx<arity` +
  `_pick(V0-链, arity-1-j)` 读 V1。P2 玩具案（nparams=0, 2 参）同规则不变。
- 验收（G04_FAMILY=uprod，comp3_g04_uprod.log）：
```
  [PASS] G04 uprod/UProd.fst (UProd.mk 3 4 : UProd …: oracle=LitNat(value=3) run_whnf=LitNat(value=3) steps=16 rounds=2
  [PASS] G04 uprod/UProd.snd (UProd.mk 3 4 : UProd …: oracle=LitNat(value=4) run_whnf=LitNat(value=4) steps=32 rounds=2
```
  oracle=4.33.1 #ORACLE WHNF（probe_015 P2 原文 `{'k':10,'nat':3}`）。
  G04 全 family（comp3_g04_all.log，873s）：**15/15 pass + 1 xfail
  （iv/eG4IV2, steps=346 与基线逐字一致）, 0 fail**——nat/lst/mu/iv/tree/
  proj 全部无回归（proj 两行 steps 仍 14/33）。
- 探针选案记录：两候选（unfold 单步 level 实例化 / accessor 快捷）均经
  探针定性为不适用（见上），落定方案 = 通用 reduce_proj_core 抽取，是
  两候选之外第三条、由内核规格直接钉死（拍 2 探针证据在 /tmp/upd_probe*）。
- 回归面：直接 Proj 节点编码的地址族（proj family、brec 套件）仍走
  nparams=0 分支，逐字不变。

### 组件 2：deq_sort/A18 Max/IMax 比较扩展 —— **NOT-VERIFIED（预算）**

- 未做。依据 ADR 022：sound-incomplete 的 `_lvl_eq`（Max/IMax 非同一闭包
  即不等）不算判定错误、宁可拒不误收；「仅当组件 1 验收后预算有余再扩展」。
- 本拍预算已在组件 1 耗尽且方向已被n2z 实证：Max/IMax 递归配对需要同样的
  2^depth 二进制展开（n2z 的实测 +8k dims 就是单位成本），deq_sort + A18 +
  chain 四处接点会让图再涨 ~2x 组件 1 的开销，且 `_lvl_eq` 在每个 DEFEQ
  微步热路径上。**留给拍 3+（或单独卡）**，不掩盖。
- VERIFIED 清单（本拍子集）：组件 1（两 G02 子集绿 + sortraw 回 8 + bcd
  21/21）+ 组件 3（uprod 差分行绿 + G04 全 15/15）。level 通道套件
  test_level_vs_lean.py 37/37 无涉。全量 23 套件回归归拍 3。
- 未提交 git（子代理禁 git；总控执笔）。py_compile 每编辑即过。

---

## 卡 011 拍 1 续接（2026-09-21）

接手代理死于模型限流，**实现已完成在 git 工作树（未提交）**，本代理只做
验证 + 落盘，不改实现逻辑。计划清单（万一再死，本板是交接态）：
1. 读 diff 现状（build_vm.py G9 dupUnivParams 臂 / step_driver.py G8
   alreadyDeclared 簿记 / tokens.py 新 token / 测试 g8,g9,g9axm_dup 行）。
2. 三个改动文件 py_compile 复跑。
3. `--sparse model/step_vm_011_scratch` 重编译，记 dims/lookups/nnz 与
   015 基线（34,392/4,489/235,030）增量。
4. 差分行集 `G02_ONLY=g8,g9,g9axm_dup` 跑 oracle 4.33.1 通道，期望全 PASS。
5. 引擎对拍 `SBIN=...011_scratch.sbin verify_engine_vs_refvm.py` 预期 34/34。
6. 硬编码扫描（CID/cid 写死）零新增或列例外。
7. 完工报告：四步输出原文 + dims 增量 + 机械缺陷（如有）+ NOT-VERIFIED。
禁止：git commit、动 engine/ 与 model/ 既有件、改 ARCHITECTURE.md。

### 执行记录（续接代理，2026-09-21/23，核段 0-5，PY=/home/xkq/miniconda3/envs/train/bin/python，日志 /home/xkq/logs/011G89/）

接手时发现：**section_g9（差分测试段）缺件**——前代理在 build_vm.py（G9
图内查重臂）与 step_driver.py（G8 簿记）已实现，测试文件头注释也写了 g9
行名与 G02_ONLY 用法，但 tests/ 里只有 section_g8，无 G9_ROW_IDS /
G9_ORACLE_CASES / section_g9，`G02_ONLY=g9,g9axm_dup` 会空跑（0/0 假绿）。
本代理补写 section_g9（9 行，格式对齐 section_g8；属测试补全，非实现逻辑
改动）。其余验证全部复跑：

#### 1. py_compile（三改动文件 + 测试，每编辑后即过）
```
$PY -m py_compile lean_vm/build_vm.py lean_vm/step_driver.py \
   expr/tokens.py tests/test_decl_injection_vs_lean.py
PY_COMPILE OK
```

#### 2. 重编译 step_vm_011_scratch（--sparse，compile_011.log）
```
$ OMP_NUM_THREADS=3 taskset -c 0-5 $PY -u model/compile_vm.py \
    --sparse model/step_vm_011_scratch
rc=0
graph: 34468 dims, 4495 lookups (3.3s)
schedule: 114 layers, d_model=6150 (18.2s)
build_weights(sparse): d_model=8366 heads_global=830 ffn=2721 nnz=235,424 (18.9s)
saved model/step_vm_011_scratch.sbin (235,424 nnz)
```
增量 vs 015 基线（34,392/4,489/235,030，23,306,042B）：
**dims +76(+0.22%) / lookups +6(+0.13%) / nnz +394(+0.17%)**，
sbin 23,389,686B(+83,644B)。G9 扫描臂 = 常数量级电路（无按名字/链长展开），
与 ADR 022 的 O(1) 预算一致。新旧 sbin 均保留。

#### 3. 差分行集（G02_ONLY=g8,g9,g9axm_dup，declinj_g8g9.log，312s）
```
$ G02_ONLY=g8,g9,g9axm_dup OMP_NUM_THREADS=3 taskset -c 0-5 \
    $PY -u scripts/run_mem_guarded.py --max-rss-mb 6000 -- \
    $PY -u tests/test_decl_injection_vs_lean.py
  [PASS] G8 g8axm_new: oracle=OK graph=code=0(accept) steps=4
  [PASS] G8 g8axm_dup: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0
  [PASS] G8 g8def_new: oracle=OK graph=code=0(accept) steps=8
  [PASS] G8 g8def_dup: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0
  [PASS] G8 g8def_dup_badbody: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0
  [PASS] G8 g8thm_new: oracle=OK graph=code=0(accept) steps=8
  [PASS] G8 g8thm_dup: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0
  [PASS] G8 g8thm_dup_nonprop: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0
  [PASS] G9 g9axm_new: oracle=OK graph=code=0(accept) steps=5
  [PASS] G9 g9axm_dup: oracle=other graph=code=10(dupUnivParams) steps=1
  [PASS] G9 g9def_new: oracle=OK graph=code=0(accept) steps=9
  [PASS] G9 g9def_dup: oracle=other graph=code=10(dupUnivParams) steps=1
  [PASS] G9 g9def_dup_badbody: oracle=other graph=code=10(dupUnivParams) steps=1
  [PASS] G9 g9thm_new: oracle=OK graph=code=0(accept) steps=9
  [PASS] G9 g9thm_dup: oracle=other graph=code=10(dupUnivParams) steps=1
  [PASS] G9 g9thm_dup_nonprop: oracle=other graph=code=10(dupUnivParams) steps=1
  [PASS] G9 g9name_lp: oracle=alreadyDeclared graph=code=11(alreadyDeclared) steps=0
=== card 010 G02 decl-injection differential: 17/17 checks pass, 0 xfail known-gap, 0 fail (312s) ===
=== OK ===
[mem-guard] wall 312.8s peak RSS 1655MB rc=0
```
oracle 通道 = `~/.elan/toolchains/leanprover--lean4---v4.33.1` #KDECL 现跑
（禁预置答案）。观测要点：G9 拒绝行 steps=1（扫描首对即中）、accept 行
steps>0（扫描跑满后回 kickoff）；G8/G9 顺序行 g9name_lp code=11 steps=0
（name 检查先于 dup-univ，K/environment.cpp:128<129）。行名 g9axm_dup 在
G02_ONLY 里的用法见文件头注释（已含 g8/g9 两例）。

#### 4. 引擎对拍（engine_011.log）
```
$ SBIN=$PWD/model/step_vm_011_scratch.sbin OMP_NUM_THREADS=3 \
    taskset -c 0-5 $PY -u scripts/verify_engine_vs_refvm.py
rc=0
=== H3 engine vs RefVM: 34/34 verdicts correct ===
    argmax vs softmax streams identical: 34/34
    known-value checks: 3/4
    total engine wall time: argmax 136.8s, softmax 259.7s
```
known 3/4 与 015 基线逐字一致（succ_zero 的 known 字面量在 015 即为 BAD，
非本拍回归；verdict 门 = 34/34 rc=0 与基线持平）。

#### 5. 硬编码扫描（验收铁律 3）
```
$ git diff -U0 lean_vm/build_vm.py lean_vm/step_driver.py expr/tokens.py \
    | grep -E "^\+" | grep -nE "CID_[A-Z0-9_]+\s*[+=]|== *[0-9]+ *(#.*)?$"
rc=1（零匹配）——同样扫了测试文件新增行，零匹配。
```
G9 臂只比较 frF2/F2/链 nid（fetch_by_position v1_/x_），reject 码 10/11、
续体 id CK_G9/CK_G0 均为协议常量，无新 cid/常量名写死分支。

#### 机械缺陷 / 补全
- **缺件（已补）**：section_g9 未实现（见上）——补写 9 行测试，全部过。
- 其余改动未发现语法/机械错误；py_compile 每次编辑后即过。
- 未提交 git；未动 engine/、model/ 既有件、ARCHITECTURE.md。
- NOT-VERIFIED：G9 的 fvar/mvar 顺序行（dup-univ :129 先于 fvar :130）未
  加测试行——oracle 端需构造 FVar 表达式，非本拍验证必需（扫描先于 g7
  的顺序已由 defer 设计与 kernel :129<:130 覆盖，拍 3 可按需补）；全量
  23 套件回归归拍 3。

---

## 卡 011 拍 2 全量回归（2026-09-23，测试工程师，独立 verifier）

计划清单（万一限流死，本板是交接态；回归已脱管，证据不随代理死）：
1. 启动全量 23 套件回归：`setsid nohup env OMP_NUM_THREADS=3
   REGRESSION_CORES=14-19 REGRESSION_LOG_DIR=$HOME/logs/011G89/reg
   bash scripts/run_cpu_regression.sh > $HOME/logs/011G89/reg/run.log
   2>&1 < /dev/null &`（SUITE_FILTER 不设=全量），起完记 pid。
2. 每 ~20 分钟轮询 `$HOME/logs/011G89/reg/*.rc` 进度。
3. 逐套件定性：rc=0 → PASS；rc≠0 → 先定性再上报——帽顶穿（wall/RSS）
   对照 a0d18cb 校准帽（decl_injection 5000|7000、brec_drec_iota 1200|8000、
   defeq_cache 2700|8000、quot 1500|6500、reducenat 1500|7000、
   stepgraph_vs_lean 1500、stepgraph_infer_defeq 3300、mutation 1200、
   olean_export 900、string_graph 1500|7500、defeq_branches 1800|3000、
   stepgraph_vs_refvm 900、check_e2e 900、datadriven_* 900、kernel_oracle
   900、engine_vs_refvm 1200…脚本头注释为全表）→ 按 015 先例单项重跑
   （`SUITE_FILTER=<label> bash scripts/run_cpu_regression.sh`）转绿才算过；
   真语义 FAIL（verdict/判定不一致）立刻在报告高亮，不与帽顶穿混。
4. 每套件结果（rc、wall、RSS 峰值、FAIL/重跑史）逐行写进本节。
5. 完工报告：23 套件 rc 表 + 语义零 FAIL 声明 + 重跑清单 + 帽异常 + 总时长。

开工时机器姿态：`free -g` 总 30 / 可用 ~20；无本项目大 env 求值在跑
（顶 RSS 为无关进程 /tmp/ms/dl.py 1.7GB）。HEAD=`7a50d99`（拍 1 验收提交），
工作树改动=拍 1 实现（build_vm.py G8/G9 + step_driver + tokens + tests，
未提交属总控 git 执笔）。pinned oracle `~/.elan/toolchains/
leanprover--lean4---v4.33.1/bin/lean` 在位。真值 sbin =
`model/step_vm_new_sparse.sbin`（回归引擎套件用它；拍 1 只编 scratch
`step_vm_011_scratch.sbin`，未覆盖真值）。

### 回归启动（2026-09-23）

**pid=2927181**（`bash scripts/run_cpu_regression.sh`；setsid 脱离会话，
工作树 cwd=/home/xkq/Lean4-Transformer-Vm-OSS，05:10 起）。启动命令原文：
```
cd /home/xkq/Lean4-Transformer-Vm-OSS && setsid nohup env OMP_NUM_THREADS=3 \
  REGRESSION_CORES=14-19 REGRESSION_LOG_DIR=$HOME/logs/011G89/reg \
  bash scripts/run_cpu_regression.sh > $HOME/logs/011G89/reg/run.log 2>&1 < /dev/null &
```
注意：脚本开头自清 `rm -f "$LOG_DIR"/*.log "$LOG_DIR"/*.rc`，把自留的
run.log inode 一并删了（fd 仍在、文件已 unlink）——脚本自己的进度/汇总
echo 进死 fd，**证据以每套件 .log/.rc 为准**，汇总表由我按 .rc 逐条重建。
oracle 钉 4.33.1 由脚本自检行证明（写在各 .log 首行）。

### 回归结果（逐套件，2026-09-26 lane 1 回填完毕；wall/RSS 全部取 [mem-guard] 行实测原文，非推算）

| # | 套件 | rc | wall | RSS 峰值 | 定性 | 证据源与备注 |
|---|---|---|---|---|---|---|
| 1 | ref_vs_lean | 0 | 1.0s | 1323MB | PASS | reg1；34/34 |
| 2 | ref_infer_defeq | 0 | 1.0s | 1327MB | PASS | reg1；82/82（2 brec-sum 跳过=登记基线） |
| 3 | stepgraph_vs_refvm | 0 | 1002.5s | 1812MB | PASS | reg2（09-23 前代理采信，S1-f 验真）；37/37 (0 pinned)。reg1 在旧帽 900s 顶穿（900.2s/1815MB）→ 帽 900→1200 被本跑证实充分 |
| 4 | stepgraph_vs_lean | 0 | 1139.3s | 1811MB | PASS | reg1；34/34 |
| 5 | stepgraph_infer_defeq | 0 | 3174.1s | 2242MB | PASS | reg1；84/84 |
| 6 | check_e2e | 0 | 670.9s | 1390MB | PASS | reg1；A 15/15, B 15/15 |
| 7 | mutation_reject | 0 | 1079.9s | 2001MB | PASS | reg2（S1 采信）；A 16/16, B 8/8。reg1 在 3-pool 内 1200s 顶穿（1200.4s/1958MB），单跑 1079.9s < 1200 帽 → 争用性顶穿，帽不动 |
| 8 | olean_export | 0 | 621.7s | 1563MB | PASS | reg1；A 21/21, B 17/17 |
| 9 | datadriven_env | 0 | 259.4s | 1561MB | PASS | reg1；32/32 |
| 10 | datadriven_bool | 0 | 64.4s | 1595MB | PASS | reg1；12/12 |
| 11 | level_vs_lean | 0 | 7.1s | 1457MB | PASS | reg1；37/37 |
| 12 | level_encoding | 0 | 1.5s | 1503MB | PASS | reg1；0 failures |
| 13 | env_meta | 0 | 1.5s | 1324MB | PASS | reg1；0 failures |
| 14 | env_meta_import | 0 | 2.0s | 1525MB | PASS | reg1；0 failures / 259 checks |
| 15 | kernel_oracle | 0 | 3.5s | 1401MB | PASS | reg1；A 10/10 agree, B 3 capacity |
| 16 | quot_graph_vs_lean | 0 | 278.8s | 5377MB | PASS | reg1；7/7 corpus |
| 17 | string_graph_vs_lean | 0 | 903.5s | 4493MB | PASS | reg1；B 30/30, C 3/3 |
| 18 | reducenat_graph_vs_lean | 0 | 1567.9s | 6067MB | PASS | reg2_r2（本拍验证跑）；A=31, B=16, 0 failures。史：reg1 在 3-pool 内 1500s 顶穿 → 单项复跑（reg2/reducenat_graph_vs_lean，09-26）仍 1500.1s/6068MB 顶穿（两次杀点 RSS 几乎全同=合法耗时长非负载）→ 帽 1500→2400（a0d18cb 格式注释）→ 验证跑 rc=0，真实 wall 1567.9s 回填脚本注释 |
| 19 | defeq_branches_vs_lean | 0 | 1466.4s | 2436MB | PASS | reg1；ALL OK |
| 20 | brec_drec_iota_vs_lean | 0 | 1060.4s | 7266MB | PASS | reg1；0 divergences |
| 21 | defeq_cache_vs_lean | 0 | 2029.0s | 7310MB | PASS | reg2（S1 采信）；`[all]: ALL OK (2028s)`，P2/whnf 两相 SKIP=ADR 019 休眠既有登记，非新增跳过 |
| 22 | decl_injection_vs_lean | 0 | 4411.3s | 6637MB | PASS | reg2（S1 采信）；103/103 checks + 3 xfail known-gap, 0 fail（=015 后基线 86+拍 1 新增 17，账目吻合；3 xfail=g03g/g03h/eG4IV2 存量） |
| 23 | engine_vs_refvm | 0 | 569.1s | 164MB | PASS | reg2（S1 采信）；34/34 verdicts + 双流一致 34/34 + known 3/4（基线持平），artifact sbin-before==sbin-after（2026-09-18 18,888,194B）无漂移 |

**23/23 rc=0，语义零 FAIL**（全部 23 行的套件输出汇总行逐个验真为真 PASS，
非仅 rc=0；无一处 verdict 判定不一致，无一处为绿灯放宽断言或删用例）。

- reg1 链条：09-23 05:10–06:27（3-pool，20/23 后代理死亡），证据
  `~/logs/011G89/reg/`。
- reg2 链条（前代理段）：09-23 07:48–10:19（串行单项，5/6 完成后死亡），证据
  `~/logs/011G89/reg2/<label>/` + `run2.log`。
- reg2 链条（本拍）：09-26 00:09–01:07，reducenat 两跑（1500.1s 顶穿证实 + 帽校准后
  1567.9s 验证 PASS），证据 `~/logs/011G89/reg2/reducenat_graph_vs_lean{,_r2}/`。

### 拍 2 完工段（2026-09-26，lane 1 测试工程师）

1. **verifier 集（卡 011 拍 2）**：全量 23 套件回归 23/23 rc=0（上表）；其中
   拍 1 新增 g8/g9 行随 decl_injection 全集跑过（103/103 含 17 行 G8/G9）。
   语义零 FAIL 声明如上。
2. **改动面**：本拍只触及 `docs/handoffs/006-G-injection.md`（本板）与
   `scripts/run_cpu_regression.sh`（reducenat 帽行 + 注释；stepgraph 900→1200
   系前代理在途产物，本拍保留未再动）。tests/、lean_vm/、engine/、model/
   零触碰；真值 `model/step_vm_new_sparse.sbin` mtime 09-18 未动（engine 行
   artifact 前后一致旁证）。工作树中的 `docs/plans/016-*`、
   `docs/decisions/023-*` 为 lane 2 语义设计师触碰面，与本拍无关。
3. **帽变更清单**（本拍新增变更仅 1 项）：
   - `reducenat_graph_vs_lean` timeout 1500→2400（RSS 7000 不动）。依据：
     两次独立杀点 wall/RSS 全同（1500.1s/6069MB 与 1500.1s/6068MB，均未触
     RSS 帽）+ 杀点位置（B 相 14/16）+ 完整跑实测 1567.9s/6067MB → 2400
     保持 ~1.5x。注释已按 a0d18cb 格式落进脚本。
   - （在途保留）`stepgraph_vs_refvm` 900→1200：reg2 单跑 1002.5s 证实充分。
   - `mutation_reject` 1200 帽不动：单跑 1079.9s，reg1 顶穿定性为 3-pool
     争用性。
4. **偏差申报 / 待总控追认**：S1 采信前代理 reg2 残留 5 套件证据（依据 a–f
   六条，见上文）；简报三波方案作废的原因是总控 09-25 审计未覆盖 reg2/
   残留，非对简报的静默偏离。若总控对采信有异议，重跑清单=decl_injection
   （~74min）+ defeq_cache（~34min）+ engine（~10min）+ mutation（~18min）+
   stepgraph（~17min）。
5. **NOT-VERIFIED**：无（23/23 全部有实测证据；跳过为零——defeq_cache 的
   P2/whnf 两相 SKIP 是 ADR 019 登记的休眠相，非本拍跳过）。
6. **总时长**：reg1 ≈77min（并行 3-pool，20/23）+ reg2 前代理段 ≈151min
   （串行 5 套件）+ 本拍 ≈60min（reducenat 顶穿跑 25min + 校准落盘 5min +
   验证跑 26min）。三段日历跨度 09-23 05:10 → 09-26 01:07（中间 48h 停滞为
   代理死亡，非机器时间）。

---

## 总控续接段（2026-09-25，总控）

**卡点诊断**：拍 2 回归链条（pid 2927181）09-23 06:27:48 后死亡，测试工程师
代理同死（限流事故序列第 4 起），此后 48h 无进程在跑——项目停滞 2 天的
直接原因，非技术阻塞。工作树未提交改动 = 本板子 + `run_cpu_regression.sh`
stepgraph_vs_refvm 帽 900→1200（合法在途产物，保留随拍 2 收口提交）。
拍 1 实现已随 7a50d99 入库；回归所跑代码 = HEAD 代码，无语义漂移。

**证据现状（总控 09-25 核对 .rc 原文）**：`~/logs/011G89/reg1/`（即 reg/ 目录）
20 套件在位。rc=0 十七个；rc=124 三个：stepgraph_vs_refvm（900s 旧帽，脚本
已改 1200）、mutation_reject（1200s）、reducenat_graph_vs_lean（1500s）。
未跑三个：defeq_cache_vs_lean、decl_injection_vs_lean、engine_vs_refvm。

**续派（并行 2，面不重叠）**：
- lane 1｜测试工程师｜拍 2 续接：reg2 目录 6 套件补跑/复跑（三批），核 14-19，
  执行记录续写本节之下。
- lane 2｜语义设计师｜卡 016 拍 A（只读 + 文档，与 lane 1 零文件交集），
  核 0-5，执行记录写 `docs/plans/016-*.md` 执行段。

收口：lane 1 全绿 → 总控五道门 → git（本板 + 脚本帽 + 卡 011 状态行 +
真值表 011 scratch 行如缺）。

---

## 卡 011 拍 2 续接执行（lane 1 测试工程师，2026-09-25 深夜–09-26，核段 14-19）

### 执行计划清单（先落盘后起跑——防线 §1.16①）

开工姿态实测：HEAD=`7a50d99`；工作树改动=本板 + `run_cpu_regression.sh` 帽
900→1200 + lane 2 文件（`docs/plans/016-*`、`docs/decisions/023-*`，非本拍
触碰面，零交集）；`free -g` 总 30/可用 20；`ps --sort=-rss` 无项目内大 env
求值（顶 RSS 为 zcode 客户端 1.5GB 等无关进程）；`pgrep -af
"run_cpu_regression|run_mem_guarded"` 零命中（前代理进程确认死透，非 G03 式
"假死"）；`command -v python3` = `/home/xkq/miniconda3/envs/train/bin/python3`
（numpy+torch 自检过，与 reg1 同解析）；钉定 oracle
`~/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean` 在位（--version 实测
4.33.1/819816b2e0a3）。真值 sbin=`model/step_vm_new_sparse.sbin`（mtime
09-18 05:39:52、18,888,194B）未动。回归所跑代码=HEAD 代码。

**S1【已完成】reg2 残留盘点与采信裁决**：

简报未知的事实——前代理 09-23 07:48–10:19 已按本卡模板（SUITE_FILTER 单套件、
`REGRESSION_LOG_DIR=reg2/<label>` 全新子目录、串行逐个）跑完 6 个补跑套件中的
5 个，全部 rc=0：`run2.log` 逐段有 launch 行（含帽参）+ oracle 4.33.1 自检行 +
results 段；stepgraph_vs_refvm 的 unit 于 10:19 写完 .rc/.log 后父进程死，
results 段缺但证据件齐全。采信依据（逐条核过原文）：

- a. 代码态=HEAD `7a50d99`（拍 1 提交在 09-23 前；其后工作树仅文档+脚本帽，
  无语义漂移）。
- b. 脚本 mtime 09-23 07:47:48 早于全部 5 次运行 → 跑的即当前工作树脚本
  （stepgraph 已是 1200 帽；其余 4 项帽参 a0d18cb 未动）。
- c. `run2.log` 每段首行 oracle 自检 `Lean (version 4.33.1, …, commit
  819816b2e0a3…, Release)`。
- d. 帽参与现脚本逐项一致（run2.log launch 行原文：decl 5000s|7000MB、
  defeq_cache 2700s|8000MB、engine 1200s|0MB、mutation 1200s|4000MB、
  stepgraph 1200s|4000MB）。
- e. 串行无双链互踩（相邻运行起止时刻首尾相接），每套件独立子目录。
- f. 语义判定行逐个验真（非仅 rc=0）：
  - decl_injection：`103/103 checks pass, 3 xfail known-gap, 0 fail (4411s)`——
    =015 摘 2 xfail+增 2 proj 行后基线 86 + 拍 1 新增 17，账目吻合；
  - defeq_cache：`defeq cache vs lean [all]: ALL OK (2028s)`（P2/whnf 两相
    SKIP = ADR 019 休眠既有登记行为，非新增跳过）；
  - engine：`34/34 verdicts correct` + 双流一致 34/34 + known 3/4（基线持平），
    artifact `sbin-before==sbin-after`（2026-09-18 18,888,194B）无漂移；
  - mutation：`A 16/16, B 8/8 === OK`；
  - stepgraph_vs_refvm：`37/37 (0 pinned M3-pending)`，wall 1002.5s < 1200
    新帽——帽修正被证实必要且充分。

裁决：5 套件采信 reg2 残留证据，不再重跑（重跑 ~2.5h 机器时零信息增量；
G03 双链事故教训：已完成且证据完整的运行不作废）。偏差申报：总控三波方案
基于 09-25 只核 reg1 .rc 的事实，reg2 残留未在其视野内；本裁决照实落板待
总控追认。

**S2【已完成】reducenat_graph_vs_lean 单项补跑**（reg2 唯一缺件；reg1 在
3-pool 并行下 1500s 帽顶穿，本跑即简报定义的"单项复跑"）：

- 启动命令（与 reg1 逐字同参只换 LOG_DIR/SUITE_FILTER，全新子目录
  `reg2/reducenat_graph_vs_lean`，不传 PYTHON=裸 python3）：

```
cd /home/xkq/Lean4-Transformer-Vm-OSS && setsid nohup env OMP_NUM_THREADS=3 \
  REGRESSION_CORES=14-19 \
  REGRESSION_LOG_DIR=$HOME/logs/011G89/reg2/reducenat_graph_vs_lean \
  SUITE_FILTER=reducenat bash scripts/run_cpu_regression.sh \
  > $HOME/logs/011G89/reg2/reducenat_graph_vs_lean.launch.log 2>&1 < /dev/null &
```

- pid=2205412（2026-09-26 00:09 起，launch.log 首行 oracle 自检 4.33.1/819816b2e0a3
  在位，launch 行原文 `timeout 1500s, cap 7000MB`）。参考基线：G04 验收期单项
  rc=0 wall 1012.0s/3951MB（09-21 图）；reg1 在 3-pool 内被杀时 1500.1s/6069MB
  且仍在增长；015+011 后图 dims +32%，RSS 会高于 G04 期，帽 7000 是否够由本跑
  实测定。
- 判定：rc=0 → PASS；rc=124/137 → 复跑一次确认后按 015 先例（a0d18cb 格式：
  帽值+实测依据注释）校准帽；语义 FAIL → 停手原文上报。
- 简报波 1/波 2 其余 5 套件不重跑（S1 采信），三波并行方案作废（单套件
  串行即足，机器纪律负担最小）。

**S2 结果（2026-09-26）：rc=124 复现 → 帽校准 1500→2400**：

- 第一跑（reg2/reducenat_graph_vs_lean/）：rc=124，`[mem-guard] wall 1500.1s
  peak RSS 6068MB rc=-9 KILLED: wall 1500s > timeout`。被杀点=14/16 B 相例已过
  （10 ACC 全过 + 4 REJ：r_add_op/r_succ_op/r_mul_res/r_pow_res 全 OK），
  只剩 2 个廉价 reject 例（r_pow_cap_tie/r_shl_res）+ 汇总；A 相 31/31 全 OK。
- 与 reg1 对照：reg1 在 3-pool 内被杀 1500.1s/6069MB，本跑单跑 1500.1s/6068MB
  ——两次独立杀点 wall/RSS 几乎全同且未触 RSS 帽 7000 → 合法耗时长，非负载
  漂移（reg1 的 124 不是并行争用假象）。外推真实 wall ≈ 1650–1750s。
- 处置：按简报判定规则（单项复跑仍顶穿→校准帽）改
  `scripts/run_cpu_regression.sh` reducenat 行 `1500|7000` → `2400|7000`，
  注释记两次杀点实测与外推依据（a0d18cb 格式）；RSS 帽不动（实测 6068 < 7000，
  余量由验证跑确认）。**验证复跑**（全新子目录 reg2/reducenat_graph_vs_lean_r2，
  同参同模板）pid=2327716，期望 rc=0 并回填真实 wall 进脚本注释。

**S3【已完成】23 行表回填**：reg1 17 个 rc=0 行保留原证据、wall/RSS 从 reg1
.log 的 `[mem-guard]` 行提取；3 个 reg1 rc=124 行与 5 个 reg2 采信行 +
reducenat 用 reg2 证据。wall/RSS 全部取 guard 行实测原文，非推算。

**S4【已完成】完工交付**：23 行完整表 + 语义零 FAIL 声明（或 FAIL 报告）+
帽变更清单（本拍零新变更；stepgraph 900→1200 系前代理在途产物，S1-f 证实
充分）+ 总时长（reg1 05:10–06:27 + reg2 07:48–10:19 + reducenat 本拍）。

---

## 总控五道门验收（2026-09-26，总控）——卡 011 拍 2 收口 CLOSED

1. **机械门**：lead canary 亲跑（核 8-13，`~/logs/011G89/lead2/`）：
   `ref_vs_lean` **34/34 rc=0**（wall 1.5s/1315MB）；`engine_vs_refvm`
   **34/34 verdicts correct + argmax/softmax 双流一致 34/34 rc=0**（585.1s/164MB，
   known-value 3/4 = 卡 006 起 harness 既有报表项）。23 行表另经审核工程师
   与 .rc/.log 逐行对照（含全部语义汇总行），无虚报。
2. **语义门**：23 套件全为真 lean 4.33.1 差分（各 .log 首行 oracle 自检行；
   reg2 残留段 5 处自检行验真）。
3. **架构门**：本拍零代码改动（仅 handoff + 帽行）；真值
   `step_vm_new_sparse.sbin` mtime 09-18 未动，engine artifact 前后一致。
4. **测试门**：断言零放宽、用例零删除、NOT-VERIFIED=0（defeq_cache SKIP =
   ADR 019 既有休眠登记）。
5. **诚实门**：审核工程师独立复核 **PASS**（报告在案：逐 .rc 对照、采信链
   a–f 验真、帽变更格式合规、触碰面恰 2 文件）；2 处记账缺陷（日期 4 处 +
   "14:46"、S3/S4 状态行滞留待办）由总控当场勘正；**reg2 残留采信被追认**
   （重跑清单留档 handoff 上文第 4 条，如后续存疑可执行）。

**裁决**：卡 011 **CLOSED**（拍 1+拍 2 全绿）。落账：卡状态行 + verifier 集
勾选（docs/plans/011）、真值表新增 `step_vm_011_scratch.sbin` 行
（ARCHITECTURE）、reducenat 帽 2400（脚本）。

**同会话邻接收口（lane 2，卡 016 拍 A）**：语义设计师交付 memo
`docs/decisions/023-reduction-continuation-family-memo.md` + 卡 016 执行段；
审核工程师独立复核 **PASS**（file:line 抽查 ~60 处 + 探针独立复跑逐字复现 +
被拒案实证核查 + 铁律 3 合规）；7 处行引/2 处措辞勘误已由总控按审核指令
当场落盘（结论不变）。拍 B 待派（次序：先 C-16.7.x-1 两名入 iv 族闭包种子
→ 2-乙 摘 eG4IV2 → 3-甲 摘 g03g/g03h；动手前 F2 写点合同审计）。

**下一队列**：卡 016 拍 B（图逻辑工程师）→ 拍 C 回归；卡 012 M-B（011 已
收口，011 scratch 可用）；里程碑快照 public-main 更新与 push 仍待人工按键。

---

## 总控进度追记（2026-09-26 晨，总控）

- **卡 011 CLOSED 已提交**（142cea3）；**卡 016 拍 A ACCEPTED 已提交**（5f783bc，
  memo docs/decisions/023 + 审核勘误已落）。
- **卡 012 M-B 拍 1（内存画像）ACCEPTED 已提交**（f26cb07 checkpoint →
  cc91977 验收）：审核 PASS + 勘误 E1-E5 落盘；关键裁定——3000+ cid 规模差分
  改走引擎通道，P1（alm_p2.py history numpy 化）为拍 2 设计输入。
- **卡 016 拍 B 断点接手**：实现代理死于额度（第 5 起限流事故），死前完成
  B1-B5（闭包种子/2-乙/F2 审计/3-甲/scratch 重编 34,663 dims +195），WIP 已
  checkpoint（17a0b82）。续接代理补 B4x 记账（g04 全节 18/18）后 **B6 引擎
  对拍 FAIL（33/34，succ_delta REJECT）**：B2 新增 decline 门把非零 Const
  实参一律当 stuck 叶，缺 delta 可展开性判别；基线对照（015 sbin 34/34）坐实
  回归，Python 侧 18/18 不可见。收尾代理按纪律停手上报（正确）。
- **总控修复裁决（已授权续接代理执行）**：decline 门 Const 子句收窄为
  "无值常量"（复用主机器 delta 展开的既有有值信号）；先 dbg+oracle 双探针
  定案再改；修复后 B6→B7→B8→B9 全链重验。卡 016 执行段为实时账本。
- 待办：拍 B 修复验收 → 拍 C 独立全量回归（测试工程师）→ 拍 D 审核 →
  卡 016 收口提交；卡 012 拍 2（P1）开卡排产。

---

## 卡 016 拍 C 全量回归（测试工程师，2026-09-26）

独立 verifier（干净上下文，与拍 B 实现者非同一会话）。触碰面：仅本板
（handoff 006）；scripts/、tests/、lean_vm/、model/ 零触碰；禁 git。

**S1【已完成】现场核对**（起跑前）：
- HEAD=77f4b6e（拍 B 修复入库 commit），`git status --porcelain` 干净。
- 真值 `model/step_vm_new_sparse.sbin` mtime 2026-09-18 05:39（18,888,194B，
  未被拍 B 覆盖）；拍 B scratch `model/step_vm_016_scratch.sbin` mtime
  09-26 06:59（23,235,098B，只读不覆盖）。
- 回归脚本 23 套件清点无误；decl_injection 帽行 5000|9200 在位（脚本
  SUITES 段 card 016 注释）；引擎套件走真值 sbin 且带 artifact drift 检查。
- 核占用：14-19 无专属占用者；非本项目进程 `test_v2_equivalence.py`
  （~1.2GB，亲和 0-19 未钉核）与总控 8-13 canary（verify_engine_vs_refvm
  + vm_run on 016 scratch）在跑——只记录不干预；引擎套件走 unit PrivateTmp
  互不污染。
- oracle 钉 4.33.1 由脚本自检（`L4TVM_LEAN` 指向 v4.33.1 toolchain）。

**S2【已完成】计划落盘 + 起跑**：全新 LOG_DIR，起跑后每 ~15-20min 轮询
`.rc`；decl_injection 是长尾（预计 ~3800s），最后回填。判定规则：
rc=0→PASS；rc≠0 先定性（帽顶穿 vs 语义 FAIL），语义 FAIL 立刻停手原文
上报；帽顶穿按先例记录（帽改动决定权在总控，本拍只记实测）。跳过记
NOT-VERIFIED，不放宽断言。已知：脚本开头自清 LOG_DIR 的 .log/.rc（run.log
fd 会死）——证据以每套件 .log/.rc 为准，run.log 仅作启动确认。

启动命令（与 011 拍 2 同构，REGRESSION_CORES=14-19，OMP_NUM_THREADS=3，
JOBS 默认 3）：
```
cd /home/xkq/Lean4-Transformer-Vm-OSS && setsid nohup env OMP_NUM_THREADS=3 \
  REGRESSION_CORES=14-19 REGRESSION_LOG_DIR=$HOME/logs/016C/reg \
  bash scripts/run_cpu_regression.sh > $HOME/logs/016C/reg.run.log 2>&1 < /dev/null &
```
**pid=551211**（真驱动进程；起跑 2026-09-26 10:57（run.log mtime 10:57:12），
oracle 自检行见 run.log 首行 Lean 4.33.1；简报命令基础上显式补
PYTHON=/home/xkq/miniconda3/envs/train/bin/python 钉绝对解释器（AGENTS 机器
纪律，裸 python3 当前也解析到同一 conda train env，语义零差异）；run.log 放
016C/ 父目录、LOG_DIR 自清不波及，证据以每套件 .log/.rc 为准）。

**S3【进行中】轮询与定性**（进行中，逐次追记）。

**S4【待办】交付回填**：23 行表（rc/wall/RSS 取 [mem-guard] 行实测）+
decl_injection 账目（106 checks + 0 xfail = 摘 g03g/g03h/eG4IV2 3 xfail +
csctor 3 行新增）+ 与 011 基线（handoff 上文 1499-1523 行表）逐行差异 +
语义零 FAIL 声明 + 总时长。

### 拍 C 续跑（2026-10-04，新 verifier 会话；前链 pid=551211 止于 8/23，机器闲置 8 天）

**S1'【已完成】现场复核**（10-04 06:26–06:40）：
- HEAD=df17d8b，工作树干净；真值 sbin mtime 2026-09-18 05:39 18,888,194B
  未动；016 scratch 09-26 06:59 只读如旧。
- `python3`→`/home/xkq/miniconda3/envs/train/bin/python3`（numpy 2.5.2 /
  torch 2.13.0 导入通过）；oracle 钉 4.33.1 自检通过；systemd user manager
  存活（degraded=历史残留，systemd-run 可用）。
- 无关进程记录不干预：`/tmp/audit_m33` 链 pytest test_ctransform.py
  （pid 2462374，RSS 3.5GB 且增长中，外层 timeout 7200，亲和未钉核）。
  重波前重查 `free -g`。
- 016C reg 8 行 [mem-guard] 原文已提取（见 S4' 表），证据目录保留未清。

**S3'【进行中】任务一：mutation_reject 定性与帽校准**（reducenat 先例，
a0d18cb 格式；总控预授权分支 b）。分支：
- a) 复跑 rc=0（<1200s）→ 016C 的 124 定性为 3-pool 争用性顶穿（同 011
  reg1 1200.4s 先例），帽不动；
- b) 复跑仍 ~1200s 顶穿且 RSS 远低于帽（两次独立杀点 wall 全同）→ 按预授权
  改脚本 mutation_reject 行 `1200|4000`→`2000|4000`，注释记两次杀点实测
  （016C reg 1200.3s/1930MB + mut2 实测）与 011 solo 基线 1079.9s（增长
  归因=016 图 dims +203），`bash -n` 过后验证跑（LOG_DIR=016C/mut3）应
  rc=0，真实 wall 回填注释与本板；
- c) rc=137（RSS 帽杀）或语义 FAIL → 停手原文上报。

**mut2 结果（10-04 06:30:48 起跑，06:50:48 出局）**：rc=124，
`[mem-guard] wall 1200.3s peak RSS 1930MB rc=-9 KILLED: wall 1200s > timeout`
——与 016C reg 杀点 **wall/RSS 逐字全同**（1200.3s/1930MB），RSS 远低于帽
4000，两次 Part A 16/16 均绿后于 Part B 被杀 → 确定性杀点=合法耗时长非
负载/非语义（011 solo 基线 1079.9s/2001MB，增长归因 016 图 dims +203）。
命中分支 b：已按预授权改 `scripts/run_cpu_regression.sh` mutation_reject 行
`1200|4000`→`2000|4000`（a0d18cb 格式注释记两次杀点 + 011 基线 + mut3
待回填），`bash -n` rc=0。

**mut3 验证跑（帽 2000）**：起跑 10-04 06:53:44，**driver pid=2470881**
（transient unit guard 2000s/4000MB，钉核 14-19；launch.log 确认
`timeout 2000s, cap 4000MB` + Lean 4.33.1 自检）。**结果 rc=0**（07:24:07
出局，实际墙 1814.3s）：`[mem-guard] wall 1814.3s peak RSS 2014MB rc=0`，
Part A 16/16 + Part B 8/8。真实 wall 1814.3s 已回填脚本注释。**余量注记
（上报总控）**：2000/1814.3 仅 ~10% solo 余量，低于脚本惯例 1.5x；预授权
只覆盖 1200→2000，未再自行上调，后续图增长须先复测。任务一闭环：
mutation_reject 终态 = rc=0 PASS（mut3），016C reg 的 124 定性为合法
耗时长（两次独立杀点 wall/RSS 逐字全同），帽 1200→2000 落地。

启动命令（同 S2 模板换 LOG_DIR/SUITE_FILTER；不传 PYTHON——裸 python3 已
验解析到同一 conda train env，与 011/016C 同参可比）：
```
cd /home/xkq/Lean4-Transformer-Vm-OSS && setsid nohup env OMP_NUM_THREADS=3 \
  REGRESSION_CORES=14-19 REGRESSION_LOG_DIR=$HOME/logs/016C/mut2 \
  SUITE_FILTER=mutation_reject bash scripts/run_cpu_regression.sh \
  > $HOME/logs/016C/mut2.launch.log 2>&1 < /dev/null &
```
**pid=2468149**（driver；起跑 10-04 06:30:48（launch.log mtime），transient
unit 2468163，guard 1200s/4000MB，钉核 14-19；launch.log 首行 Lean 4.33.1
自检过）。

**S3'' 任务二：余 15 套件补跑（5 波，波内并行/波间串行，REGRESSION_CORES=14-19）**。
简报波清单合计 14 套，缺 kernel_oracle（脚本第 120 行，余 15 之一，011
基线第 15 行）——按「余 15 套件补跑 + 23 行全表」要求并入波 1 第 4 实例
（w1d，900s/4000MB 轻套件），帽与波框架不动，此为对简报的唯一增补。

**波 1【已完成 10-04 07:36】7/7 rc=0，语义输出与 011 基线一致**：
（07:30:27 四实例并发起跑；setsid 启动器 pid 2474240-2474243，fork 后即退，
真实 driver 未逐个钉死——三实例秒级完赛即退，证据以每套件 .rc/.log 为准，
后续波单独跑时钉 driver pid。）
- w1a level_vs_lean 2.1s/1539MB 37/37；level_encoding 1.0s/1326MB 0 failures。
- w1b env_meta 1.5s/1333MB 0 failures（round-trip 35/35）；env_meta_import
  2.6s/1560MB 0 failures/259 checks。
- w1c datadriven_env 235.3s/1361MB 32/32；datadriven_bool 56.3s/1438MB 12/12。
- w1d kernel_oracle 4.1s/1364MB Part A 10/10 agree + B 3 capacity 0 failures。

**波 2【已完成 10-04 08:05】3/3 rc=0，判定行全验真**：
- w2a quot_graph_vs_lean 339.9s/5472MB（011：278.8s/5377MB）— 7/7 corpus,
  A=4 meta, C-stuck=y, 0 failures。
- w2b string_graph_vs_lean 948.6s/4482MB（011：903.5s/4493MB）— B 30/30,
  C 3/3, 0 failures。
- w2c defeq_branches_vs_lean 1637.7s/2388MB（011：1466.4s/2436MB）— ALL OK。

**波 3【已完成 10-04 08:35】2/2 rc=0**：
- w3a brec_drec_iota_vs_lean 1072.9s/7352MB（011：1060.4s/7266MB）—
  0 divergences。
- w3b reducenat_graph_vs_lean 1659.4s/6110MB（011 solo：1567.9s/6067MB）—
  A=31, B=16, 0 failures（与 011 逐字同）。

**波 4【已完成 10-04 09:11】2/2 rc=0**：
- w4a defeq_cache_vs_lean 2139.1s/7361MB（011：2029.0s/7310MB）— ALL OK；
  d6 P1+P2 arm 与 whnf phase 两相 SKIP=ADR 019 休眠既有登记（VM014_ALLOW_P2/
  VM014_WMEMO 未开），与 011 同账非新增跳过。
- w4b engine_vs_refvm 624.0s/164MB（011：569.1s/164MB）— 34/34 verdicts
  correct + known 3/4（基线持平）+ 0 条意外 FAIL；artifact sbin-before==
  sbin-after（2026-09-18 05:39:52, 18,888,194B）无漂移。

**波 5【进行中 09:12 起跑】**：decl_injection_vs_lean（w5，driver
pid=2506764，帽 5000s/9200MB，长尾单跑）。预期 106/106 + 0 xfail
（=011 基线 103/103+3 xfail 摘 g03g/g03h/eG4IV2 + csctor 3 新行）。
- 波 1（轻，4 实例并行）：level_（w1a：level_vs_lean+level_encoding）、
  env_meta（w1b：两件）、datadriven（w1c：两件）、kernel_oracle（w1d）。
- 波 2（中，3 并行）：quot_graph_vs_lean（w2a，帽 6500）+
  string_graph_vs_lean（w2b，帽 7500）+ defeq_branches_vs_lean（w2c，帽 3000）。
- 波 3（重，2 并行）：brec_drec_iota_vs_lean（w3a，帽 8000）+
  reducenat_graph_vs_lean（w3b，帽 7000）。波前 `free -g`，可用 <14GB 改串行。
- 波 4：defeq_cache_vs_lean（w4a，帽 8000）+ engine_vs_refvm（w4b）。
- 波 5（长尾单跑）：decl_injection_vs_lean（w5，帽 5000|9200）；预期
  106/106 + 0 xfail（=011 基线 103+3xfail 摘 3 + csctor 3 新行）。
判定规则照 S2（rc=0→PASS；rc≠0 先定性，帽顶穿只记实测不自行改帽——
mutation 分支 b 除外；语义 FAIL 停手原文上报；跳过记 NOT-VERIFIED）。
各波启动后 pid 即回填本板。

**S4'【已完成 10-04 10:40】交付回填：23 行完整表**（rc/wall/RSS 全部取
[mem-guard] 行实测原文；011 基线=上文 1499-1523 行表；差异注记逐行给出）。

| # | 套件 | rc | wall | RSS 峰值 | 定性 | 证据源与 011 差异注记 |
|---|---|---|---|---|---|---|
| 1 | ref_vs_lean | 0 | 1.0s | 1317MB | PASS | 016C reg；34/34（011：1.0s/1323MB 同账） |
| 2 | ref_infer_defeq | 0 | 1.0s | 1320MB | PASS | 016C reg；82/82（2 brec-sum 跳过=登记基线；011：1.0s/1327MB 同账） |
| 3 | stepgraph_vs_refvm | 0 | 1154.9s | 1826MB | PASS | 016C reg；37/37 (0 pinned)（011：1002.5s/1812MB；wall +15.2%） |
| 4 | stepgraph_vs_lean | 0 | 1188.8s | 1826MB | PASS | 016C reg；34/34（011：1139.3s/1811MB；wall +4.3%） |
| 5 | stepgraph_infer_defeq | 0 | 3106.9s | 2243MB | PASS | 016C reg；84/84（011：3174.1s/2242MB；wall -2.1%） |
| 6 | check_e2e | 0 | 770.9s | 1344MB | PASS | 016C reg；A 15/15, B 15/15（011：670.9s/1390MB；wall +14.9%） |
| 7 | mutation_reject | 0 | 1814.3s | 2014MB | PASS | 终态=mut3 验证跑（10-04，帽 2000）；A 16/16 + B 8/8。史：016C reg 3-pool rc=124（1200.3s/1930MB）→ mut2 solo 复跑 rc=124（1200.3s/1930MB，与 reg 杀点 wall/RSS 逐字全同=合法耗时长非负载）→ 帽 1200→2000（总控预授权，a0d18cb 格式）→ mut3 rc=0（011 solo：1079.9s/2001MB；wall +68%，归因 016 dims +203；2000 帽 solo 余量 ~10%） |
| 8 | olean_export | 0 | 637.5s | 1447MB | PASS | 016C reg；A 21/21, B 17/17（011：621.7s/1563MB；wall +2.5%） |
| 9 | datadriven_env | 0 | 235.3s | 1361MB | PASS | w1c；32/32（011：259.4s/1561MB） |
| 10 | datadriven_bool | 0 | 56.3s | 1438MB | PASS | w1c；12/12（011：64.4s/1595MB） |
| 11 | level_vs_lean | 0 | 2.1s | 1539MB | PASS | w1a；37/37（011：7.1s/1457MB） |
| 12 | level_encoding | 0 | 1.0s | 1326MB | PASS | w1a；0 failures（011：1.5s/1503MB） |
| 13 | env_meta | 0 | 1.5s | 1333MB | PASS | w1b；0 failures + round-trip 35/35（011：1.5s/1324MB 同账） |
| 14 | env_meta_import | 0 | 2.6s | 1560MB | PASS | w1b；0 failures/259 checks（011：2.0s/1525MB 同账） |
| 15 | kernel_oracle | 0 | 4.1s | 1364MB | PASS | w1d；A 10/10 agree, B 3 capacity（011：3.5s/1401MB 同账；简报波清单漏项，按「余 15 套件」补入波 1） |
| 16 | quot_graph_vs_lean | 0 | 339.9s | 5472MB | PASS | w2a；7/7 corpus, A=4 meta, 0 failures（011：278.8s/5377MB；wall +21.9%） |
| 17 | string_graph_vs_lean | 0 | 948.6s | 4482MB | PASS | w2b；B 30/30, C 3/3（011：903.5s/4493MB；wall +5.0%） |
| 18 | reducenat_graph_vs_lean | 0 | 1659.4s | 6110MB | PASS | w3b；A=31, B=16, 0 failures（011 solo：1567.9s/6067MB；wall +5.8%） |
| 19 | defeq_branches_vs_lean | 0 | 1637.7s | 2388MB | PASS | w2c；ALL OK（011：1466.4s/2436MB；wall +11.7%） |
| 20 | brec_drec_iota_vs_lean | 0 | 1072.9s | 7352MB | PASS | w3a；0 divergences（011：1060.4s/7266MB；wall +1.2%, RSS +1.2%） |
| 21 | defeq_cache_vs_lean | 0 | 2139.1s | 7361MB | PASS | w4a；ALL OK；d6-P2 与 whnf 两相 SKIP=ADR 019 休眠既有登记非新增（011：2029.0s/7310MB；wall +5.4%） |
| 22 | decl_injection_vs_lean | 0 | 4888.0s | 7629MB | PASS | w5；106/106 checks + 0 xfail + 0 fail（=011 基线 103+3xfail 摘 g03g/g03h/eG4IV2 + csctor 3 新行，账目吻合）。**帽余量警报（上报总控）**：5000s 帽 solo 余量仅 2.2%（RSS 9200 余量 17%）；wall 较 016B reg4 solo 3798.0s（同 106 checks 同机）+28.7%，较 011 in-pool 4411.3s +10.8%——漂移超出 dims +203 的可解释面，是否上调帽由总控决定 |
| 23 | engine_vs_refvm | 0 | 624.0s | 164MB | PASS | w4b；34/34 verdicts + known 3/4（基线持平）+ 0 条意外 FAIL；artifact sbin-before==sbin-after（2026-09-18 05:39, 18,888,194B）无漂移（011：569.1s/164MB） |

**23/23 rc=0，语义零 FAIL**：每行套件输出汇总行逐一验真（34/34、82/82、
37/37、34/34、84/84、A15/B15、A16/16+B8/8、A21/B17、32/32、12/12、37/37、
0 failures、0 failures/259、10/10、7/7、30/30+3/3、A=31+B=16、ALL OK、
0 divergences、ALL OK、106/106+0 xfail、34/34+known 3/4）；无一处判定
不一致，无一处为绿灯放宽断言或删用例；唯一 rc≠0 记录（mutation 016C reg
与 mut2 的 124）已定性为合法耗时长并经帽校准+mut3 rc=0 闭环。

**帽变更清单**：
- `mutation_reject`：1200\|4000 → 2000\|4000（总控预授权；两次独立杀点
  wall/RSS 逐字全同；mut3 验证 rc=0，真实 wall 1814.3s 已回填脚本注释；
  solo 余量 ~10% 注记在案，后续图增长先复测）。
- `decl_injection_vs_lean`：5000\|9200 未动（本拍实测 4888.0s 顶到 2.2%
  余量；无预授权不自行上调，是否上调由总控决定）。

**总时长与峰值并发**：证据执行窗口 06:30:48（mut2 起）→ 10:33:46（w5 收）
≈ 4h03m；23 行套件墙钟合计 23,488s（≈6h31m）经波内并行压缩（mutation
另含弃跑 mut2 1200.3s）。峰值并发 = 波 1 四实例 7 套件进程（瞬时 RSS 需求
~10GB）；峰值 RSS 需求 = 波 3（brec 7352 + reducenat 6110，峰不重叠，
<13.4GB），全程无 OOM、无 RSS 帽杀（唯一杀点=mutation 旧 1200 帽）。机器
可用内存最低 ~11GB（波 5 尾段，9200 帽内）。无关进程 /tmp/audit_m33
test_ctransform.py（RSS 3.5GB，timeout 7200 包裹）于波 3 前自然退场，未
干预未误杀。

**证据目录**：016C/reg（8 行 09-26 链）、016C/mut2+mut3（任务一）、
016C/w1a-w1d、w2a-w2c、w3a-w3b、w4a-w4b、w5（10-04 波 1-5）；各 .rc/.log
均落盘。改动文件仅：本板 + scripts/run_cpu_regression.sh（mutation 帽行
一处，预授权内）；tests/、lean_vm/、engine/、model/ 零触碰；未动 git。

---

## 总控五道门收口（2026-10-04，总控）——卡 016 CLOSED

1. **机械门**：lead canary `ref_vs_lean` 34/34 rc=0（`~/logs/016D/lead/canary1/`，
   核 8-13，HEAD df17d8b）；引擎 34/34 已三次独立（F7/F0y/016C w4b）；拍 C
   23/23 rc=0 经拍 D 审核逐行对照（抽 6 行 .log 语义汇总逐字验真）。
2. **语义门**：摘 3 XFAIL + csctor 3 行全部 oracle 现跑；拍 D 轻量探针复核
   （修前计数器逐值全同 / 修后 succ_delta 79 步 AGREE / pre-B 逐值还原）。
3. **架构门**：diff 逐块零新增具名 cid/常量分支（两轮自查 + 拍 D 复核）；
   decline 取值电路与主机器 const_delta 同寻址；MODE_STRIDE=128 落地 B3
   约束 (a)/(b)。
4. **测试门**：断言零放宽、用例零删除（摘 xfail 标签 ≠ 删行，行仍判定）；
   XPASS 协议在位（tests 三处 XPASS 计入 fails）。
5. **诚实门**：拍 D 审核 PASS（五道门全过；4 minor 已由总控当场落：真值表
   016 行、卡 checkbox、VM_SPEC memo 指针、B15 锚 + 脚本路径勘正）；两条
   残余债如实登记；帽校准（mutation 2700 = 1814.3×1.49、decl_injection
   7200 = 4888×1.47）a0d18cb 格式，实测依据注释在脚本。

**裁决**：卡 016 **CLOSED**。落账：卡状态行 + verifier 勾选、ARCHITECTURE
真值表 `step_vm_016_scratch.sbin` 行（md5 4d2564a27534065e9299d40c6383c1c1）、
KERNEL_COVERAGE G2/B15、VM_SPEC §16.7.1/16.7.2、帽 2700/7200。

**下一队列**：卡 012 拍 2（P1 history numpy 化，开卡时按 024 E5 把画像探针
提升进 scripts/）→ 卡 012 M-C/M-D（规模差分走引擎通道，拍 1 裁定）；
里程碑快照 public-main 更新与 push 仍待人工按键。
