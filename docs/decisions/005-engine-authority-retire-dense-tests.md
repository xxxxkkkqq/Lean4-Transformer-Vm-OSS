# 005. 权重/引擎侧端到端验收以 C++ 引擎为准，dense Python 权重路径退役

- 编号说明：任务卡 004 指定本决策落 `003-*.md`，但 003/004 已被 WP5（代理 A）
  的字符串决策占用（`003-string-suite-step-budget.md`、
  `004-string-handle-cid-no-legacy-fallback.md`），按"架构决定 →
  `docs/decisions/NNN-<slug>.md` 唯一登记处"规则顺延为 005。
- 状态：accepted（2026-09-14，卡 004）
- 背景（全部为实测/磁盘证据，非推测）：
  - 三个端到端测试 `tests/test_endtoend_corpus.py`、
    `tests/test_engine_vs_runner.py`、`tests/test_weights_fidelity.py`
    的输入是 dense torch checkpoint `model/step_vm.pt`（`WeightRunner` 吃
    `torch.load(...)` 出来的 `LeanTransformer` + meta 字典）。该文件**不存在**
    （2026-09-14 总控与 B 分别 `ls` 核实）→ 三个测试不是失败，是静默不可跑。
  - 重建它不可行：post-WP8 图 dense 参数 **2,403,125,340 ≈ 19.2GB**
    （`docs/HYBRID_ARCH.md` §1 实测），本机可用 ~22GB，materialize 必然 OOM；
    红线 9 禁止让 >1GB checkpoint 重新出现在磁盘。非零密度实测 5.6e-05，
    当前唯一有效产物是 `model/step_vm_new_sparse.sbin`（L4SV v2，
    13,272,290B，2026-09-14 01:54:50），它没有 Python 侧消费者
    （runner 不接受该格式）。
  - 磁盘上的旧 checkpoint `model/step_vm_new.pt`（4.07GB，09-12 pre-WP8）
    对 `test_weights_fidelity` 报 `KeyError: 'dbg_r0'`（checkpoint 的
    output-map 与当前 `build_step_graph` 输出名不匹配）——即使拿它跑，
    验的也不是当前图。真值表已标"过期、禁止使用"。
  - `test_endtoend_corpus` 即便有产物也不可行：其 docstring 自测 dense runner
    在 2552-token env 上 ~216ms/微步，最简单声明 >2000 步不halt（>430s），
    全语料超出任何正常测试预算。
  - 引擎通道已存在且在跑：`engine/vm_run`（09-13 06:36 构建，`engine/vm.cpp`
    未再改动）+ `scripts/verify_engine_vs_refvm.py`——对 toy CORPUS 全量
    34 例做 引擎(argmax) vs RefVM 结果判定 + argmax/softmax 双流逐 token 一致
    + 已知字面值检查。2026-09-14 基线（对 01:54 版 sbin，B 亲跑，
    `/tmp/004B_verify_base.log`）：**33/34 verdicts correct，唯一失败
    `pow`**（引擎 F 通道 off-by-one，卡 006 收口）；argmax/softmax 流
    34/34 一致。
  - 缺口记账前提：引擎只驱动 **WHNF** 切片，不能跑 CHECK / is_def_eq
    （boot handoff §3.4）。故"权重侧端到端与真 lean 一致"目前只对 WHNF
    可验收；corpus 级 CHECK 端到端在引擎长出 CHECK 能力前**没有**可跑载体。
- 决策：
  1. **权重/引擎侧验收以 C++ 引擎为准**：`scripts/verify_engine_vs_refvm.py`
     列为日常回归（`scripts/run_cpu_regression.sh`）的第 4 层套件；
     判据链 = 引擎==RefVM（本套件）+ RefVM==真 lean、图==真 lean
     （既有 1–3 层套件）。`pow` 作为具名豁免（仅此一条允许红）。
  2. **删除三个测试文件**：`tests/test_endtoend_corpus.py`（未跟踪，直接移出
     工作树）、`tests/test_engine_vs_runner.py`、
     `tests/test_weights_fidelity.py`（git 跟踪，删除留 `git status` 的 D）。
     理由：三者共同前提是 dense Python 权重的存在，该前提被 19GB 实测与
     红线 9 永久否定；"存在但没跑"的测试即不存在的验收。
     `test_engine_vs_runner` 的引擎-vs-runner 对拍价值被
     verify_engine_vs_refvm 的引擎-vs-RefVM 通道取代（RefVM 才是有 oracle
     背书的参照；runner-vs-engine 只是双实现自洽）。
  3. **`model/runner.py` 降级为开发探针**：本体保留（不改逻辑），文件头注明
     它吃什么产物、为何不再被回归覆盖、复活需新 ADR。
  4. `tests/corpus/coverage.lean` / `reject.lean` 与 oracle 封装保留在树里；
     权重侧 CHECK 端到端等引擎支持 INFER/DEFEQ/CHECK 后（卡 006+ 之后的
     独立包）按本决策第 1 条的通道重写。该能力缺口显式记入
     `ARCHITECTURE.md`，不以图侧绿灯掩盖（红线 10）。
- 被拒方案：
  - **按任务卡倾向的反面——让 Python 权重 runner 直接吃 `.sbin`**
    （`compiler/weights.py` 的 `SparseLeanModel` 路线，保住三个测试）：
    等于用 Python 再实现一遍稀疏执行语义，与 C++ 引擎构成持续对齐负担的
    双执行器；红线 2 禁止自写第二套实现当判据，而判据链里 RefVM 已经在
    对拍位置。退役文档里明写"dense Python 路径与 19GB 一起退役，别再维护
    两套执行器语义"。拒绝。
  - **重铸当前图的 dense `model/step_vm.pt`**：19GB OOM，红线 9。拒绝。
  - **拿旧 `step_vm_new.pt`（4.07GB pre-WP8）凑跑**：版本不匹配
    （`KeyError: 'dbg_r0'` 实测），验的不是当前图，且把过期快照重新变成
    事实基线，污染真值表。拒绝。
  - **`test_endtoend_corpus` 只删 VM 半边、保留真 lean 编译 corpus 的半边**：
    剩下的只是 oracle 自检，不是验收测试；语义等价物已在
    `test_check_e2e`/`test_kernel_oracle`。不留半具尸体。拒绝。
  - **`test_weights_fidelity` 改造成 sbin 结构对拍（nnz 计数 vs 图 live-op）**：
    `docs/HYBRID_ARCH.md` §4 列为"Sparsity"验证，但计数对不上不代表判定错、
    对上了也不代表逐维忠实；结果级对拍（决策 1）才是判据。若未来需要防
    "改图忘重编"，用真值表 mtime 纪律 + 里程碑出口的图-vs-lean 套件兜住，
    本卡不新增半成品 harness。拒绝（记录为可选后续）。
- 预期后果：
  - 好：回归入口与实际技术栈一致（1–3 层图/参照机/真 lean + 第 4 层引擎吃
    当前 sbin）；日常回归全清单一次跑完（实测 <20 分钟，含 string 套件）；
    磁盘不再需要任何 >1GB 产物；双执行器维护债清零。
  - 坏（损失点名）：
    - 权重 vs 图的逐步逐维 bitwise lockstep 消失——"sbin 是当前图的忠实
      lower"从运行时验收降级为"编译期解析构造 + 结果级对拍"。防护：
      `ARCHITECTURE.md` 真值表要求记录产物 mtime/大小/生成命令；图改动后
      必须重编 sbin 再跑引擎对拍（AGENTS.md 反馈回路既有纪律）。
    - 权重侧端到端只对 WHNF 验收；CHECK/INFER/DEFEQ 的权重侧覆盖 = 无，
      已显式记账（ARCHITECTURE + 本 ADR），引擎长出该能力前不许声称
      "端到端全绿"。
    - `test_weights_fidelity` 未提交的 4 行增量求值加速（`driver._eval.sync`
      替换全量重放）随文件删除消失；若未来复活任何 lockstep 测试，可从
      git 历史取回该思路。
    - `pow` 保持具名豁免（卡 006）；除它以外引擎套件红即回归红。
