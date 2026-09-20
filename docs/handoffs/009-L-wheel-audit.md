# 009 — L 链：重复造轮盘点（只读审计 + 总控验收裁决）

触发：用户 2026-09-16 质问"为什么不直接用 Mathlib 官方预编译缓存"——实锤一例
（`lake build` 源码编 2.5h + 诱发 04:14 OOM crash，而官方 `lake exe cache get`
就写在 mathlib lakefile.lean:114-115 注释里没人盘）。据此对全仓做系统盘点。
审计代理 L1（agent_ca4156f8，只读，04:5x-05:1x），总控逐条抽查证据后落档。

## L1 报告（判定表）

| # | 能力 | 我们的实现 | 现成渠道 | 判定 | 最小动作 |
|---|---|---|---|---|---|
| 1a | 长跑内存封顶 | scripts/run_mem_guarded.py（轮询+组杀）+ AGENTS"ps 抽查"纪律 | `systemd-run --user --scope -p MemoryMax=`（本机 systemd 255、cgroup v2 unified、memory 控制器在委派列表） | 半拉子：run_cpu_regression.sh:24-27 裸口说"tested, MemoryMax not enforced"无输出原文 | **总控已复测定案**：单 MemoryMax 被 swap 穿透（200M 限下放 2GB 存活 rc=0），配 `MemorySwapMax=200M` 则组内 OOM rc=137。内核级封顶可用，双限是硬要求。已改写 AGENTS 机器纪律 |
| 1b | 构建看门狗口径 | scripts/build_mathlib_capped.sh 头注释曾写"`ps -C lean,lake` 全机器聚合>6GB 就杀" | 仓库 run_mem_guarded.py 的进程树口径 | 实锤（错误回潮）：按 comm 名聚合会把别的会话（如 F5 探针的 oracle lean）算进本组误杀 | **已改**：注释换成 run_mem_guarded.py 包一层、按进程树 |
| 2 | 测试调度 | tests/test_*.py 20 个全部自写 main()、0 个 pytest 用例；run_cpu_regression.sh 自写调度池 | pytest（base/miniconda 未装，train env 有） | 合理差异化（RSS 帽/PrivateTmp/分级 timeout 是 pytest 不管的，脚本:13-32 有实测理由）——但 test_*.py 命名误导 pytest 收集（实测 nodeids=[]） | README 测试章加一行"pytest 收集 0 项，唯一入口 run_cpu_regression.sh"【待办】 |
| 3 | 权重二进制 | L4SV v1/v2 CSR+meta+mmap（compiler/weights.py:1502-1524、engine/vm.cpp:217-271） | safetensors（无 CSR/无引擎消费路径）、torch .pt（=已退役 dense，HYBRID_ARCH H1 实测 19.2GB 即死因） | **合理差异化**：ADR 001 记 v1→v2 演进，版本化兼容已兑现（vm.cpp:271） | 无 |
| 4a | 环境常量导出 | reference/olean_export.py 生成 lean 代码 + 手写 serExpr/serLevel | 实测 lean v4.33.1 `--help` 无环境 dump 项；olean 二进制无官方 reader | **合理差异化**（kernel 级 ConstantInfo 全字段确无现成消费者） | 无 |
| 4b | 同上（外部对照） | 同上 | leanprover-community 的 Export 类第三方工具（外部源 404/限流未核实字段覆盖） | 半拉子（低置信） | ORACLE.md 或 ADR 记一行"比对结论+排除理由"【待办，M-B 前】 |
| 4c | Expr→JSON 序列化 | **仓库内两份手写副本且方言已分叉**：lean_ref.py:33-56（不 emit binder-info）vs olean_export.py:71-84（emit `bi`）；两处 `.strVal` 均不转义引号/控制符（lean_ref.py:55、olean_export.py:84，**总控抽查确认**） | Lean core Lean/Data/Json.lean 的 ToJson 设施；至少共用一份模板 | **实锤：轮子×2 + 潜在正确性 bug**（含引号的字符串字面量→坏 JSON） | 立小卡：抽共享序列化器 + 走 core API 转义；改动需全差分套件复验【欠账登记】 |
| 5 | 依赖获取与并发封顶 | (a) clone 用 `--filter=blob:none`、manifest 锁官方 8 依赖——做对了。(b) 8 个依赖 olean 也全部源码编（.lake/packages 编译产物 ~396MB）——`lake exe cache get` 连依赖带 Mathlib 一起拉。(c) 并发封顶用 LD_PRELOAD sysconf shim | 官方渠道=cache get；Lean runtime object.cpp:1083-1088 的 `LEAN_NUM_THREADS`（同处先读 env 再回退 hardware_concurrency） | (b) **实锤**（案例的定量补强）；(c) **半拉子**：盘到"lake 无 -j"（核实属实）就停手，没盘 env 旋钮 | 下次 rebuild 先跑 cache get；LEAN_NUM_THREADS 对照实测（峰值进程数+RSS）回写 shim 头【已注记待实测】 |
| 6 | guarded-runner | /tmp/probe009F/ 的 run_guarded{,4,5,7}.sh **同一轮重造 4 次**（单 PID、sleep 5 轮询、kill -9 $P），严格劣于仓库 09-14 就建好的 scripts/run_mem_guarded.py（全树、0.5s、killpg、timeout、peak 报告） | 仓库自己的 scripts/run_mem_guarded.py | **实锤**：根因=AGENTS"机器与进程纪律"通篇没提这个脚本存在（grep 确认），子代理按手册只能重造 | **已改**：AGENTS 机器纪律点名两个首选护栏（cgroup 双限/run_mem_guarded），并禁止 /tmp 重造 |
| 7a | MILP 调度 | compiler/milp_scheduler.py:30 `import highspy` | HiGHS 官方 Python 接口 | **无造轮** ✓ | 无 |
| 7b | oracle 工作路径 | lean_ref.py 五处写死 /tmp/vm_*.lean，并发互踩后用 systemd PrivateTmp 补救（补救本身买到 cgroup 清孤儿，有价值） | stdlib tempfile 一处改净 | 半拉子：为何不用 tempfile 的取舍无在案理由 | lean_ref.py 头补一行取舍【并入 4c 小卡】 |
| 7c | 压缩/归档/hash/CI | 全仓扫描：无手写 gzip/tar/zip/base64/md5；无自写 CI | stdlib | **无造轮** ✓ | 无 |

**附带发现（文档漂移）**：开发防线 §3.5 与 docs/ORACLE.md:78,108-109,161 仍写
Mathlib 在 `/tmp/mlbench`，实际已迁 `/home/xkq/mathlib_src`（007 链）。

## 总控验收（lead3 亲验记录）

- 抽查证据属实：/tmp 看门狗×4（ls 实拍）；strVal 双副本不转义（grep 原文）；
  lakefile.lean:114-115 注释（自读）；cgroup controllers 含 memory（自读）。
- MemoryMax 争议当场定案（L1 只读禁测，总控补跑）：
  `systemd-run --user --scope -p MemoryMax=200M` 下 `bytearray(1<<31)` 存活
  rc=0；加 `-p MemorySwapMax=200M` 后 rc=137。**结论：可用，但必须双限**。
  run_cpu_regression.sh 的"tested"说法结果碰巧对、过程无据——正是防线 §1.14
  要禁的裸口说。
- 本审计的轮子根因判定：卡 012/007 简报与 §4.1 任务卡模板都没有"现成渠道
  盘点"栏，派活链路没人被要求答"官方有没有现成的"→ 制度缺口，不是某个代理的
  偶发失误。
- 已落地动作：防线 §1 第 14 条（含 MemorySwapMax 定案）；§3.5 路径修正；
  AGENTS 机器纪律改写（cgroup 双限首选、run_mem_guarded 点名、禁 /tmp 重造）；
  AGENTS 禁止项+1；build_mathlib_capped.sh 看门狗口径修正；shim 头注记
  LEAN_NUM_THREADS/cache get 两个未盘渠道待实测。

## 欠账清单（进计划前不得遗忘）

1. [小卡] 共享 Expr→JSON 序列化器 + strVal 转义修复（lean_ref/olean_export 合一，
   全差分复验）；顺带 lean_ref 固定 /tmp 路径的取舍注记。
2. [本卡顺手] README 测试章注明 pytest 收集 0 项、唯一入口是回归脚本。
3. [M-B/I3 前] ORACLE.md 与 test_kernel_oracle.py Part B 的 Mathlib 根路径从
   /tmp/mlbench 迁到 /home/xkq/mathlib_src；外部 Export 类工具比对结论落 ORACLE.md。
4. [下次 rebuild] 先 `lake exe cache get`（失败再源码）；跑 LEAN_NUM_THREADS=3
   对照实测，决定 LD_PRELOAD shim 去留。
5. [待核] run_cpu_regression.sh:24-27 注释按本次定案改写（MemorySwapMax 已证）。
