# 007 — I 链：卡 012 M-A Mathlib 闭包抽取器（handoff / 进度链）

核 14-19，OMP_NUM_THREADS=3，日志 $HOME/logs/012I/。总控占 8-13，F2 占 0-5。
GPU RTX 5070 Ti（16GB）本卡用不上（M-A 是 lean+CPU），闲置中勿动。
用户 ~11GB 训练任务在跑（/home/xkq/train，勿动勿杀）。

## 状态

- 派发：2026-09-16 03:2x，I1（agent_...）。从卡 012 拆出 M-A 先行——
  M-A 与 F2（build_vm.py/tokens.py）、G（step_driver）、H（图侧 G8/G9）**文件零交集**，
  是全链条唯一可立即并行的工作。A 链已证明 M-B/M-C/M-D 依赖图侧收口，不许提前。
- 前置事实（总控实测，2026-09-16 03:19）：本机无 mathlib olean；
  `~/.elan/toolchains/` 仅 v4.33.1（判据版本，不许换）。
  `nvidia-smi` util 100% 但无进程、mem 7MiB——用户训练任务已让位，GPU 闲置。

## 简报（总控 → I1）

### 你是谁、在链条哪一环

你是开发代理 I1，执行 `docs/plans/012-mathlib-scale-closure.md` 的 **M-A 子项**
（闭包抽取器）。卡 012 全系列最后一张，M-A 是唯一能现在动的部分。

### 必读顺序

1. `AGENTS.md` 全文（验收铁律、机器纪律、反馈回路、禁止项、完工定义）。
2. 本简报 + `docs/plans/012-mathlib-scale-closure.md`（只领 M-A，M-B/C/D 不动）。
3. `reference/olean_export.py`（现有 ENV 导出通道，你要扩展的对象）。
4. `docs/ENV_FORMAT.md`（输出格式合同）。
5. `docs/handoffs/000-2026-09-14-boot.md` §3（环境导出链路背景）。
6. `docs/ORACLE.md`（真 lean 调用方式；差分口径）。

### 目标（M-A verifier 原文）

"≥3 个真实 Mathlib 定理的闭包导出成功且元数据完整（inductive 字段逐项对真
lean `const2decl`）"。交付物：

1. **Mathlib checkout（v4.33.1 兼容）**：放 `/home/xkq/mathlib_src`（仓库外，
   磁盘先 `df -h` 确认 ≥15GB 余量再动手；lake build 产物也在那）。
   版本锁：mathlib 以 `lean-toolchain` 声明 v4.33.x 的 tag/commit 为准
   （git log 找），不许拿 master 赌。**这一步失败（网络/磁盘/构建超时）→
   立刻落 handoff 报总控，不许硬撑**。
2. **抽取器 `scripts/export_mathlib_closure.py`**：输入=定理名列表 +
   Mathlib 项目根；用真 lean API（`Lean.collectDependencies` 类，或 import
   环境遍历 `Environment.constants` 过滤 reachable 闭包）取常量依赖闭包
   （inductive/recursor/def/thm/axiom + universe 约束 + 完整元数据），
   输出**现 ENV 格式**（复用 `olean_export.py` 的编码路径，不另起炉灶）。
   闭包规模必须打印：常量数、ENV 字节数、按 kind 分布。
3. **元数据完整性核查**：抽 ≥20 个闭包内常量（含全部 inductive），
   逐项对真 lean `const2decl`/等价查询核字段（构造子数、字段类型、
   recursor 规则数、univ 参数）。差异清单落 handoff。
4. **语料红线**：期望 verdict 一律不预置进脚本/fixture（验收铁律 2）。
   抽取器只产 ENV，判定留给后续 M-C 现跑 oracle。

### 选例（≥3 定理）

从 Mathlib 真实证明里选跨支路的：一条算术位运算族（Nat/Int）、
一条 List/Vector iota 重（brecOn 形态）、一条 Quot/String 相关。
具体名字到了 mathlib 现场按 `grep -r "theorem" Mathlib/Init` 一类找短小可导出的，
写进 handoff 再抽。

### 硬约束（越界=FAIL）

- **只许改**：新 `scripts/export_mathlib_closure.py`、新
  `tests/test_mathlib_closure_env.py`（只做结构校验，不做判定差分）、
  `reference/olean_export.py`（扩展，旧 toy 路径语义逐字节不变）、
  `docs/ENV_FORMAT.md`（新增节）、本文件、`docs/decisions/` 新 ADR（若出现
  编码扩展决策）。
- **禁改**：`lean_vm/build_vm.py`、`expr/tokens.py`（F2 属主）、
  `lean_vm/step_driver.py`（G 属主）、`engine/*`、`compiler/*`、`model/*`、
  `lean_vm/ref_vm.py`（冻结）、`ARCHITECTURE.md`、`README.md`、既有 tests、
  `lean_kernel/*`。不许 git commit/add。
- 旧回归不破：`SUITE_FILTER=olean_export python3 scripts/run_cpu_regression.sh`
  级别的 canary 每次动 olean_export.py 后必跑（套件已在 20 套件表内）。
- 万级常量的 ENV **只许生成+结构校验，不许喂进 Python 图求值**
  （里程碑出口实证：81 常量 env 就吃 8GB，越线即死）。图侧规模验证归 M-B，不是你的事。

### 机器纪律

- lake build / lean 大编译：`setsid nohup env OMP_NUM_THREADS=3 taskset -c 14-19 <cmd> > $HOME/logs/012I/xxx.log 2>&1 < /dev/null &`，
  起后 `ps -o pid,rss,etime -p <pid>` 抽查，RSS>6GB 主动杀。禁止 `| tail`。
- 探针走 PrivateTmp 或单跑，禁并行 oracle（固定 /tmp/vm_dump_env.lean 互踩过）。
- pkill 先 `pgrep -af` 看清防自杀。master 日志放 REGRESSION_LOG_DIR 外。
- 上下文吃紧：把完成度、下一步三件事写进本文件再退。半完工+完整记录 >> 全完工+黑盒。

### 完工定义

1. M-A verifier 达成（原文粘贴尾行）。
2. 改动只触及声明文件集；旧 olean_export canary 绿。
3. 闭包规模数字（常量数/字节/kind 分布）+ 元数据核查差异清单落本文件。
4. 非常识决策落 ADR；本文件更新到最新。

---

## I 段（执行记录）

### 执行骨架（I1，2026-09-16 派发后立刻落盘）

| # | 步骤 | 预期产出 | 状态 |
|---|---|---|---|
| 0 | 清场：`ps --sort=-rss`、`df -h`（≥15GB）、确认 lean v4.33.1 | 数字记录在本节 | 进行中 |
| 1 | git clone mathlib → `/home/xkq/mathlib_src`，锁 `lean-toolchain` 声明 v4.33.x 的 tag（git log 找，不用 master） | commit/tag 记录 | 待 |
| 2 | `lake build`（setsid nohup，核 14-19，OMP=3，日志 `$HOME/logs/012I/build.log`；起后 ps 抽查 RSS>6GB 杀） | `.lake/build/lib/Mathlib.olean` 存在 + 墙钟 | 待 |
| 3 | 选例：3 条跨支路定理（Nat/Int 位运算族、List/Vector brecOn 形态、Quot/String 相关），名字先记录再抽 | 定理名清单 | 待 |
| 4 | 新 `scripts/export_mathlib_closure.py`：调 `olean_export.dump_env(defs, roots, lean_cmd=["lake","env","lean"], cwd=mathlib)` 抽闭包；打印常量数/ENV 字节/kind 分布；复用现 ENV 编码路径（Encoder/import_env_meta），不另起炉灶 | 脚本 + env 产物（仓库外或 scripts 输出目录） | 待 |
| 5 | 元数据核查 ≥20 常量（含全部 inductive）：dump 字段逐项对真 lean `const2decl`（独立 lean 查询，非同一 dump） | 差异清单落本节 | 待 |
| 6 | 新 `tests/test_mathlib_closure_env.py`：结构校验（小闭包快速跑；**不喂 Python 图求值、不做判定差分、不预置 verdict**） | verifier 原文尾行 | 待 |
| 7 | canary：`SUITE_FILTER=olean_export python3 scripts/run_cpu_regression.sh`（每次动 olean_export.py 后必跑） | 尾行原文 | 待 |
| 8 | 收尾：本文件更新（规模数字+差异清单+commit/墙钟）；若有编码扩展决策落 ADR；`docs/ENV_FORMAT.md` 新增节 | 完工四条对照 | 待 |

任何一步失败（网络/磁盘/构建超时）→ 立刻停手写进本节报总控，不换判据版本、不放宽要求。

### 步骤 0 结果（清场，2026-09-16）

- `df -h /`：466G 可用 ≥15GB ✅；内存 30G（可用 16G）。
- `~/.elan/bin/lean --version`：`Lean (version 4.33.1, x86_64-unknown-linux-gnu, commit 819816b2e0a3bf405af45ae5c7af2491d8f5bee6, Release)` ✅ 判据版本在位。
- `lake --version`：`Lake version 5.0.0-src+819816b (Lean version 4.33.1)`（与判据同 commit）。
- 进程大户：`python3 /tmp/probe009F/probe3.py lst` RSS 6.9GB——**F2/G 链的探针，非我派生，不动不杀**；我的 lake build 单进程核 14-19，起后 RSS 抽查见下。

### 步骤 1 结果（clone + tag）

- `git clone --filter=blob:none https://github.com/leanprover-community/mathlib4.git /home/xkq/mathlib_src`（blob 按需拉取，历史完整，HEAD 是 v4.34.0 时代 master，toolchain v4.34.0——不能直接用）。
- `git tag` 里有 **v4.33.1**，`git show v4.33.1:lean-toolchain` = `leanprover/lean4:v4.33.1`，与本机判据**精确匹配**。
- `git checkout v4.33.1`：**tag v4.33.1，commit 0df444a360eaa60ab8c11dca51a86af692955474**。
- `lake-manifest.json` 固定 8 个依赖 rev（batteries 4488d40d…、aesop 3448c0bc… 等），无声明其他 toolchain 的包。

### 步骤 2 过程记录（lake build）

- 起法（遵守纪律）：`setsid nohup env OMP_NUM_THREADS=3 taskset -c 14-19 ~/.elan/bin/lake build > $HOME/logs/012I/build.log 2>&1 < /dev/null &`
- 起后抽查：lake 主进程 pid=576111，RSS 823MB（依赖 clone 阶段），未越 6GB 线。
- 进度抽查（起后 ~5 分钟）：1394/8712 模块，lake RSS 952MB，未越线。
- 结果：（待 build 完成后记墙钟与尾行）

### 步骤 3 候选（选例，build 完成前按源码 grep 预选，现场再验证可解析）

- 算术位运算族：`Nat.testBit_land`（Mathlib/Data/Nat/Bitwise.lean:118，
  `theorem testBit_land : ∀ m n k, testBit (m &&& n) k = (testBit m k && testBit n k)`；
  同文件 `land_bit`/`testBit_lor` 备用）。
- List/Vector iota 重（brecOn 形态）：`Vector3.cons_fz`（Mathlib/Data/Vector3.lean:73，
  对索引类型 Vector3 的求值定理，证明体走 recursor/brecOn；备用 `append_nil`:142）。
- Quot 相关：`Quot.liftOn_mk`（Mathlib/Data/Quot.lean:105；备用 `Setoid.ext`:38）。
- String 相关备选：`String.length_eq_list_length`（Mathlib/Data/String/Lemmas.lean:24）。
- 注意：Mathlib 的 import 链是整库级（Data.Nat.Bitwise → Algebra.Ring.Defs →…），
  闭包规模可能到数千常量——M-A 只生成+结构校验，不喂图求值（红线）。

### 步骤 5 设计决策（记录，防上下文丢失）

简报词"逐项对真 lean `const2decl`"：**`const2decl` 在 v4.33.1 toolchain 源码与
4.35 master 全树 grep 零命中**（该名字不在当前 API 里）。按简报"或等价查询"口径，
独立核查通道设计为：dump 的 Declaration JSON → Python 重建 Lean `ConstantInfo`
→ 经真内核 `Environment.addDeclWithoutChecking`（extern `lean_add_decl_without_checking`，
kernel/environment.cpp:297，绑定 Environment.lean:691）往返 → 逐字段比对
`env.find?` 原始输出。inductive 用 `Declaration.inductDecl`、ctor/rec 用
`ctorDecl`/`recDecl`，绕开 elaborator，纯数据往返。差异清单落本节。

---

## 总控裁决（卡 012 M-A，总控 2026-09-20 补记——handoff 断链 4 天后的验尸裁决）

**I1 链实际结局（据 ~/logs/012I/ 六份日志重建）**：03:28 本文件最后写入后，
无界 `lake build` 04:14 峰值约 19GB 触发内核 OOM 崩掉桌面客户端（I1 大概率死于
此刻），三次重建尝试后 05:08 经 `LD_PRELOAD` sysconf shim（限 3 CPU）重建成功
（build5.log 尾行 `Build completed successfully (8705 jobs).`），05:23 落
`scripts/build_mathlib_capped.sh` + `scripts/lake_nproc_shim.c`（范围偏差两件，
良性构建工具，已被 009-L 轮审追认、commit e2d7cdf 入库）后 I1 退出，
**未回写本文件**。此后至 09-20 零动作。

**M-A 完成度定性：环境预置 100%、抽取器 0%**——
- 已完成（真资产）：Mathlib v4.33.1 checkout（/home/xkq/mathlib_src，commit 0df444a）
  + 全量 olean 构建（Mathlib.olean 768,392B 在位）；构建护栏工具两件。
- 未开工：`scripts/export_mathlib_closure.py`、`tests/test_mathlib_closure_env.py`、
  元数据差异清单、规模数字。Verifier 5 项勾 0。
- 教训入账：handoff 断链 = 死因 §1.16 反面（05:23 的收尾动作没落盘）；
  "M-A in progress" 状态行对 4 天零产出子项有误导。

**处置**：状态行改为 stalled 并重派 I2（资产坐标：olean 就绪无需重建、
选例候选见上文"步骤 3"、核查通道设计见上文"步骤 5"——`const2decl` 零命中
已定谳，走 addDeclWithoutChecking 往返）。I2 只做骨架步骤 3→4→5→6→8，
机器纪律按 009-L 升级口径（run_mem_guarded 进程树口径、双限 cgroup）。
ORACLE.md 的 /tmp/mlbench 路径欠账已由总控 09-20 清偿（commit 6c938cb），
I2 文件清单不含 ORACLE.md。

---

## I2 执行记录（2026-09-20 接续，干净上下文一次性）

核 14-19，OMP_NUM_THREADS=2 + LEAN_NUM_THREADS=2，日志 /home/xkq/logs/012I/。
解释器 /home/xkq/miniconda3/envs/train/bin/python。lean 通道：
`cd /home/xkq/mathlib_src && lake env lean`（实测 `lake env lean --version` →
`Lean (version 4.33.1, x86_64-unknown-linux-gnu, commit 819816b2e0a3bf405af45ae5c7af2491d8f5bee6, Release)`）。
Mathlib.olean 在位（/home/xkq/mathlib_src/.lake/build/lib/lean/Mathlib.olean 768,392B）。

### 步骤 3 结果（选例，2026-09-20）

三条定理在 v4.33.1 checkout 源码 grep 确认在位，且经 `lake env lean`
#check 实测可解析（探针 /home/xkq/logs/012I/probe_resolve.lean，墙钟 13.0s）：

- `Nat.testBit_land`（Mathlib/Data/Nat/Bitwise.lean:118，算术位运算族）
  → `Nat.testBit_land : ∀ (m n k : ℕ), (m &&& n).testBit k = (m.testBit k && n.testBit k)`
- `Vector3.cons_fz`（Mathlib/Data/Vector3.lean:73，List/Vector iota 重，Fin2 索引）
  → `@Vector3.cons_fz : ∀ {α : Type u_1} {n : ℕ} (a : α) (v : Vector3 α n), Vector3.cons a v Fin2.fz = a`
- `Quot.liftOn_mk`（Mathlib/Data/Quot.lean:105，Quot 支路）
  → `@Quot.liftOn_mk : ∀ {α : Sort u_1} {γ : Sort u_2} {r : α → α → Prop} (a : α) (f : α → γ) (h : ∀ (a₁ a₂ : α), r a₁ a₂ → f a₁ = f a₂), (Quot.mk r a).liftOn f h = f a`

备用（若闭包导出失败再启用）：`String.length_eq_list_length`
（Mathlib/Data/String/Lemmas.lean:24）。

### 步骤 4+5 结果（闭包导出 + 全量元数据往返核查，2026-09-20）

交付物 `scripts/export_mathlib_closure.py`（py_compile 绿）：给 fully-qualified
定理名，git grep 定位 leaf 名（多候选时按 `env.getModuleIdxFor?`
（Lean/Environment.lean:1195 → const2ModIdx）逐候选 lean 探针定谳——import
是传递的，#check 无法区分声明模块）；`olean_export.dump_env`（lean_cmd=
["lake","env","lean"], cwd=mathlib_src）取闭包；`_const_names` 补洞循环
（recursor rule rhs 可达 getUsedConstants 之外的常量，实测 0 轮补洞）；
`import_env_meta` + `Encoder(const_meta=…)` 编码成 ENV；内核往返核查
（同上探针机制，含拓扑序与 parseLeanName 精确名字重建）；迭代式
（显式栈）expr 树读回——Mathlib 证明项深度超 Python 递归限。

运行原文（`OMP_NUM_THREADS=2 LEAN_NUM_THREADS=2 taskset -c 14-19
python3 -u scripts/export_mathlib_closure.py --theorem Nat.testBit_land
--theorem Vector3.cons_fz --theorem Quot.liftOn_mk`，日志
/home/xkq/logs/012I/export_all.log）：

```
== Nat.testBit_land  (module Mathlib.Data.Nat.Bitwise) ==
  closure: 779 constants (8.1s)
  round trip: skipped_opaques=0, diffs=0
  ENV: 779 consts, 4107045 tokens, 41070450 bytes (61 ctors, 33 structs, lparams consts 288, height>4095 clamped 0)
  kinds: {'axiom': 2, 'ctor': 61, 'def': 337, 'ind': 50, 'quot': 3, 'rec': 20, 'thm': 306}
  decode readback: 779/779 cids clean
== Vector3.cons_fz  (module Mathlib.Data.Vector3) ==
  closure: 87 constants (1.5s)
  round trip: skipped_opaques=0, diffs=0
  ENV: 87 consts, 47916 tokens, 479160 bytes (13 ctors, 5 structs, lparams consts 50, height>4095 clamped 0)
  kinds: {'axiom': 1, 'ctor': 13, 'def': 37, 'ind': 11, 'rec': 4, 'thm': 21}
  decode readback: 87/87 cids clean
== Quot.liftOn_mk  (module Mathlib.Data.Quot) ==
  closure: 8 constants (10.0s)
  round trip: skipped_opaques=0, diffs=0
  ENV: 8 consts, 869 tokens, 8690 bytes (1 ctors, 0 structs, lparams consts 8, height>4095 clamped 0)
  kinds: {'ctor': 1, 'def': 2, 'ind': 1, 'quot': 3, 'thm': 1}
  decode readback: 8/8 cids clean
=== 3 theorems, 874 constants total, 0 diffs/decode errors ===
```

- 元数据核查规模：874 常量全量往返（>>20），含全部 62 个 inductive
  （50+11+1）及其全部 ctor/rec（内核重算 cidx/nfields/numIndices/isRec/
  isReflexive/recursor rules 逐字段一致）；产物在
  /home/xkq/logs/012I/closures/<thm>/（dump.lean / dump.jsonl / rt.lean /
  rt.jsonl）。
- ENV 字节口径：token=K(8bit)+6 字段×12bit=10 字节（VM_SPEC §2 字段域）；
  本拍只编码 ENV 区（无证明树）。
- 过程中的两次失败（第 1 次失败即停手写证据）：
  1. `_private.Init.Data.Nat.Bitwise.Basic.0.PSigma.casesOn._arg_pusher`
     （779 闭包中唯一带 hygienic universe 参数名的常量）往返 diff 3 字段。
     根因：`String.toName` 不是 `Name.toString` 的逆（hygienic 名
     `<name>._@.(<imported>.<ctx>)*._hyg.<scopes>` 整体塌缩成
     [anonymous]，实测；`Init/Data/ToString/Name.lean:117-120` 自述名字
     可能不 round trip）。修复：rt 程序实现 `parseLeanName`（按
     MacroScopesView 语法精确重建，`Init/Prelude.lean:5659-5700`
     `extractMacroScopes`/`MacroScopesView.review`），diff 清零。
     数字典名（`foo.1`→.num）实测 String.toName 本就精确。
  2. 迭代读回初版把 K_CONST 的 level 兄弟链挂到表达式栈——
     KL_PARAM(5) 与 K_CONST(5) 数值碰撞致 KeyError；改为 level 内联
     解码（小树递归）。均为检查通道实现 bug，非数据问题。
- 验收铁律 3 核对：`grep -n "CID_[A-Z0-9_]* *[+*/-] *[0-9]"
  scripts/export_mathlib_closure.py` 零输出；脚本无常量名/cid 分支。

### 步骤 6 结果（结构测试，2026-09-20）

`tests/test_mathlib_closure_env.py`（py_compile 绿）：三定理全流程——A 闭包
导出（schema 断言只有 kind/up/ty/val/ind/meta 六键，无 verdict 字段）+
B 内核往返 0 diff + C 逐 cid 元数据不变量（kind/lparams/rec 规则序=cidx 序/
major_idx 公式/ind ctor 序/ctor cidx+nfields）+ D 全量迭代读回（类型+值树
与源树相等）+ E expr.tokens 参考解码器（decode_expr/decode_level）在小闭包
上的正向对照。三闭包检查数 2196，全部绿：

```
=== M-A closure ENV verifier: 0 failures / 2196 checks ===
RC=0
```

（运行与日志同上口径：taskset -c 14-19，日志 /home/xkq/logs/012I/
test_closure_env.log、.rc。运行期间进程 RSS 峰值 <1GB，未越 4GB 护栏；
测试不经 run_cpu_regression.sh——套件表为显式清单，加入与否归 M-D/总控。）

### 步骤 8 收尾（I2 完工对照，2026-09-20）

**Verifier 集（M-A，逐条原文）**

1. `python3 -m py_compile` 两个新文件：
   ```
   py_compile both OK
   ```
2. ≥3 定理闭包导出成功 + 规模数字：见上文"步骤 4+5 结果"运行原文——
   779 + 87 + 8 = 874 常量；ENV 41,070,450 / 479,160 / 8,690 字节；
   kind 分布 {'axiom':2,'ctor':61,'def':337,'ind':50,'quot':3,'rec':20,
   'thm':306} / {'axiom':1,'ctor':13,'def':37,'ind':11,'rec':4,'thm':21} /
   {'ctor':1,'def':2,'ind':1,'quot':3,'thm':1}。
3. 元数据往返核查：874/874 常量（含全部 62 inductive 及其 ctor/rec）
   零差异清单——三闭包 `diffs=0`（原文见上文），无 skipped_opaques；
   toy 级探针那次唯一的 opaque 跳过口径记录在"步骤 5 机制探针"节。
4. tests/test_mathlib_closure_env.py rc=0：原文见步骤 6。
5. 硬编码扫描零新增：
   ```
   $ grep -n "CID_[A-Z0-9_]* *[+*/-] *[0-9]" scripts/export_mathlib_closure.py
   （零输出，rc=1）
   ```

**触碰文件**：新建 scripts/export_mathlib_closure.py、
tests/test_mathlib_closure_env.py；追加本文件 I2 执行记录。
reference/、lean_vm/、expr/、engine/、compiler/、docs/{ENV_FORMAT,VM_SPEC,
KERNEL_COVERAGE}.md、其他 tests **零改动**（git status 中 step_driver.py、
VM_SPEC.md、KERNEL_COVERAGE.md、006-G-injection.md、
test_decl_injection_vs_lean.py 的未提交改动属并行 G 链，非本代理）。
olean_export.py 未动 → I1 简报的 olean_export canary 无触发条件，未跑。

**墙钟**：步骤 3 选例+探针 ~0.5h；步骤 5 机制探针（toy 往返）~1h；
步骤 4 抽取器（含两次失败排查）~1.5h；步骤 6 测试 ~0.5h；
单次三定理全流程 ~3.5 min（dump+raw+往返各一轮 lean），测试全量 ~3 min。

**未尽事项 / 移交下一拍**：
- ENV_FORMAT/VM_SPEC 无新编码决策（现格式直接可用），无需 ADR；
  hints_height>4095 钳位在本批语料未触发（clamped=0），TBD#1 维持原状。
- opaque 值不进 dump（DUMP_TEMPLATE 冻结所致）：本批闭包实测 0 只
  opaque；未来闭包若含 opaque，其值缺失口径已写进脚本头注释。
- M-B/M-C/M-D 仍 open，按 ADR 014 等图侧收口；本卡 779 常量闭包 ENV
  已可直接供 M-B 做编码规模实验（同样禁止直接喂 Python 图求值）。

### 步骤 5 机制探针（toy 级先行验证，2026-09-20）

往返通道在 Mathlib 之前先在 WP1 toy 语料上全链验证（探针件：
/home/xkq/logs/012I/{rt.lean,probe_rt.py}，不属于仓库交付物，机制将原样
嵌入 scripts/export_mathlib_closure.py）：

- **空 env**：`Lean.mkEmptyEnvironment 0`（Lean/Environment.lean:1530）
  给出零常量环境——连 Quot 都没有（`importModules #[]` 同样全空，实测）。
  因此闭包内**每个**常量都要经 addDeclWithoutChecking 重建，含 quot 块与
  全部 inductive。
- **内核级 API 落位**：4.33.1 里真正的纯内核路径是
  `Kernel.Environment.addDeclWithoutChecking`（Lean/Environment.lean:307-308，
  extern `lean_add_decl_without_checking`；:692 的同名 private 函数是
  elaborator 层 `lean_elab_add_decl_without_checking`，不走它）。
  handoff 原设计行里的 "Environment.lean:691" 指向的是后者的 wrapper；
  4.33.1 与 4.35 的 Declaration API 有差异（4.33.1 无 ctorDecl/recDecl
  变体，`inductDecl lparams nparams types isUnsafe` 携带
  `InductiveType {name,type,ctors}`，**构造子随 inductDecl 一起进内核，
  recursor 由内核 addInductive 自动推导**——推断规则数/numIndices/isRec
  全部由内核重算，比对因此更强）。
- **拓扑序必需**：即使 without checking，内核 addInductive 从 ctor 类型
  推导 recursor 时要求被引用常量已在 env（实测 MPair 在 Nat 之前加入即
  `Kernel.Exception.unknownConstant` 失败）。往返程序按类型引用做 DFS
  拓扑排序（互递归 inductive 块 = 单元；ctor/rec 由内核派生不单独加）。
- **4.33.1 表达式细节**：`lam/forallE (name) (type) (body) (binderInfo)`
  binderInfo 在最后；fvar/mvar 携带 FVarId/MVarId 无法从名字重建——内核
  常量是封闭项，dump 里若出现 fvar/mvar 视为发现（deserializer 直接
  throw）。serExpr 的 `bi` 字段必须还原，否则隐式 binder 全成假差异。
- **toy 结果**：34 常量 33 个零差异（逐字段含 kind/up/ty/val/meta、
  内核重算的 recursor rules、ind ctors 顺序、quot 四件套）。
  唯一例外 `M_op`（bodyless `opaque`）：
  DUMP_TEMPLATE（reference/olean_export.py:177-180，冻结文件）只对
  defnInfo/thmInfo 序列化 `val`，**opaque 的 value 不在 dump 里**，重建
  需要发明数据 → 按红线跳过并计数上报，不伪造。Mathlib 闭包若含 opaque
  同样处理并如实计入差异清单为零的口径说明。
- **比对范围裁定**：`ind.isStruct/ind.nf` 来自 `getStructureInfo?`
  （elaborator structureExt 环境扩展，Lean/Structure.lean:126），不是内核
  ConstantInfo 字段（ENV_FORMAT §1.5 inductive_val 无此二字段），纯内核
  重建环境无法承载 → 逐字段比对跳过这两键并在报告里单独列明；其余全部
  字段必须逐字节相等。
