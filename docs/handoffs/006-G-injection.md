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
