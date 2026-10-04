# ADR 024：纯 Python 图求值器内存画像（卡 012 M-B 拍 1）

状态：已采纳（画像结论 + 改造方向清单，2026-09-25，后端 lane，总控收口待办）
任务卡：`docs/plans/012-mathlib-scale-closure.md` M-B 第一个可验收子项
（"iota 大 env 差分在 ≤6GB 内可跑"）的设计输入。

## 1. 结论（一段话）

驻留大头是 `lean_kernel/alm_p2.py:IncrementalGraphEvaluator.lookup_history`：
每 lookup 每流位置一条 `(pos, kx, ky, values)` Python 元组，O(N·L) 条
（81 常量 env：N=4440 token × L=4495 lookup ≈ **1996 万条 × 240B ≈ 4.7GB**；
240B 为实测深尺寸采样均值（probe_struct.py 逐字段 getsizeof 含 values-list
超配），理想排布逐字段加总 236B，
占单 case warmup 峰值 6091MB 的 77%）。6GB 线最可能从两处破：(P1) 把
history 收进 per-lookup 预分配 float64 数组（kx/ky 目前在元组和 `_mir`
numpy 镜像里**存了两份**），驻留降到 ~0.9GB、峰值 ~1.5-2GB；(P2) 复用
求值器已有的 warm-prefix fork 协议让同 env 多 case 共享 env 前缀（机制
现成，4 个测试已在用，其中 brec/drec 就是 iota 家族）。

## 2. 量测设置与命令

- 被测：`tests/test_iota_graph_vs_lean.py`（81 常量 env，46 自定义；
  `Encoder` 编出 **N=4440 流 token**）经 `lean_vm/step_driver.py:StepDriver`
  驱动 `lean_kernel/alm_p2.py:IncrementalGraphEvaluator`。
  `model/runner.py` 是 torch DEV PROBE（ADR 005），不在本通道。
- 原始 228s/6010MB / 464s/8006MB 出处：`$HOME/logs/milestone_exit/
  iota_large_env{,_try2}.log`（guard stderr 行，格式与
  `scripts/run_mem_guarded.py` 逐字匹配；try1 死于 case2 warmup，
  try2 死于 case3 warmup）。
- 本次复跑命令（2026-09-25，核 14-19，OMP_NUM_THREADS=3）：

```bash
setsid nohup systemd-run --user --scope -p MemoryMax=6500M -p MemorySwapMax=0 \
  $PY -u scripts/run_mem_guarded.py --max-rss-mb 6500 --timeout 900 -- \
  env OMP_NUM_THREADS=3 taskset -c 14-19 $PY -u tests/test_iota_graph_vs_lean.py \
  > /tmp/012_memprof/rerun.log 2>&1 < /dev/null &
```

- 结构画像：/tmp 探针（非仓库交付物，`/tmp/012_memprof/probe_{static,struct}.py`）
  分块 sync + 定向深尺寸采样 + `gc.get_objects()` 类型聚合交叉核对。

## 3. 复跑 RSS 曲线（2s 外采样，`/tmp/012_memprof/rerun_rss_clean.csv`）

| t(s) | 0 | 20 | 40 | 60 | 80 | 100 | 120 | 140 | 160 | 180 | 200 | 220 | 240 | 258 | 278 | 284.7 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSS(MB) | 7 | 540 | 1088 | 1679 | 2132 | 2571 | 3148 | 3506 | 3897 | 4240 | 4622 | 4948 | 5301 | 5940 | 6249 | **6474→kill** |

- 分段增速 27.6 / 24.6 / 20.4 / 16.9 / 25.8 MB/s；全程单调、无平台。
- kill 点：case2（wb_b_deq）warmup 中，t≈285s，6474MB（cgroup
  MemoryMax 连 run_mem_guarded 一起 SIGKILL，guard 汇总行未及输出）。
  stdout 复现原始 try1：`[PASS] wb_a_whnf` 后无新输出。
- t≈244s 处 5371→5687MB 跳变 = case1→case2 转场（case1 已释放但 RSS
  不回落，case2 从残留 base 重新爬升）。
- 与原 try1（228s/6010MB，cap 6000）同一死亡曲线，kill 点一致。

## 4. 结构占比（单 case warmup 完成点，实测原文）

探针输出（case1@4440，N=4440）：

```
[270.8s rss=6091MB] case1@4440: hist entries=19,957,800 nonempty_lookups=4495
  per_entry=240B hist_total~4720MB vals n=4440 per_dict~2264B vals~10MB
  (+floats~8MB) _mir~563MB input_tokens=4440
[270.8s] case1 warmup complete peak_rss=6091MB
```

结构占比 top5（6091MB 峰值分解）：

| # | 结构 | 大小 | 占比 | 说明 |
|---|---|---|---|---|
| 1 | `lookup_history` 元组记录 | ~4720MB | 77% | 4495 lookup × 4440 pos = 19,957,800 条 × 240B（tuple4 72B + kx 24B + ky 24B + values-list 64B + value float 24B + pos int 28B） |
| 2 | 分配器/解释器余量 | ~790MB | 13% | 峰值 − (1+3+4) 项；2000 万小对象的 pymalloc/malloc 开销与碎片 + 图/计划基线 |
| 3 | `_mir` numpy 键镜像 | ~563MB | 9% | 4495×2 数组 × ~1.76h×8B（倍增松弛）；**与元组里的 kx/ky 完全重复** |
| 4 | `vals`（每位置 77 键 persist dict） | ~18MB | 0.3% | 4440 × 2264B + 77×24B floats |
| 5 | `graph.input_tokens`（Expression） | ~3MB | <0.1% | 4440 个 7 域 Expression |

`gc.get_objects()` 交叉核对（case1@2000，RSS 2701MB，浅聚合）：

```
GC-TOP case1@2000: list=9,017,879/827MB  tuple=9,031,275/620MB
  dict=76,123/24MB  function=87,327/13MB  Expression=72,295/3MB
  ReGLUDimension=29,826/1MB  LookUpDimension=4,554/0MB  LookUp=4,495/0MB
```

（899 万 value-list + 899 万 history 元组 + 容器列表，与定向计数吻合；
Expression/Dimension 可忽略——图本体不是问题。）

关键旁证：
- **单 case warmup 本身就到 6091MB**：6GB 线不是"多 case 叠加"才破的，
  一个 case 的 env warmup 就贴线（原 try1 在 case2 破线是叠加分配器残留）。
- **释放是干净的**：`del drv + gc.collect()` 后 RSS 6149→721MB（滞留
  ~590MB = 共享图 + eval plan + 类结构 + 碎片）。case2 从 721MB 重新爬到
  6095MB——每 case 重付全部 warmup 的**时间**与重复爬峰是真实成本。
- **边际驻留律**：~1.2-1.35MB/token（= 4495×240B ≈ 1.04MB history +
  ~140KB mir + ~4KB vals）。任何 env 的 footprint 可由此直接外推：
  `RSS ≈ 700MB + 1.3MB × N_tokens`。注意口径：700MB 底座 = case 释放后
  残留（721MB 实测），该式是**跨 case 棘轮包络**（700+1.3×4440=6472 ≈ 复跑
  kill 点 6474）；首 case 峰值 ≈ 126MB + 1.35MB×N ≈ 6.1GB。
- **时间律**（顺带实测）：warmup 37.7→69.8ms/pos 随位置线性涨
  （O(N²·L) 扫描），4440 token 一次 warmup 262s；外推 N=20k ≈ 89min。
- **逐步垃圾 vs 驻留**：warmup 完成后 15 个微步仅 +58MB（≈ 每 token
  同一边际率，步进也追加 token 入 history），无失控垃圾产生——问题是
  驻留结构本身，不是 GC 不及时。

## 5. 术语勘误（影响后续卡的规模叙事）

里程碑/handoff 里的"4440 常量 env"实为 **81 常量 → 4440 流 token**
（出处 = handoff 000 §3 未验收缺口第 6 条，docs/handoffs/000-2026-09-14-boot.md:71，
"4440 常量"系 token 数误记；§4 陷阱 6 是 succ_zero，另事）。81 常量 env 的
token/常量比 ≈ 54.8。M-B 的"3000+ cid 闭包 ENV"按此比外推 N≈16.5 万
token：现结构 history ≈ **172GB**，即便 P1 优化后 ≈ 29GB。时间外推假设：
按 O(N²) 自 262s@4440 二次外推至 N=164,400 得 **~100h**（早稿 87h 按
N≈15.3 万取整）；L 钉死 4495 是**下界**（lookup 数随 env 增长）且不含
oracle/编码时间——真实更差。**纯 Python 求值器在该规模结构性不可行**，
与优化无关。
M-B/M-C 的闭包规模差分应以引擎通道（C++ `vm_run`）为规模载体，Python
求值器保留语义参照职能（中小 env）。

## 6. 改造方向清单（按收益/风险排序）

### P1（主推）：`lookup_history` numpy 化 + 去重 `_mir`
- 做法：每 lookup 用预分配 float64 数组存 (kx, ky, values) + 计数与
  倍增扩容，淘汰 240B Python 元组记录；`_mir` 并入（kx/ky 现存两份）。
  exact float64 语义不动（tie-break 的 1e-9 契约保持）。
- 收益（按 §4 实测数字）：history+mirdup 5283MB → ~0.9GB（~40B/条含
  松弛）；单 case warmup 峰值 6091 → **~1.5-2GB**；6GB 线 token 上限
  4550 → ~26k token（≈470 常量）。时间不变（扫描仍 O(N²·L)，省元组
  分配后预计略快 10-20%）。
- 风险：`lookup_history` 的 dict[id]->list[tuple] 协议被 warm-prefix
  fork 机制消费（`{i: list(h) for ...}`：tests/test_quot_graph_vs_lean.py:247、
  test_string_graph_vs_lean.py:354、test_brec_drec_iota_vs_lean.py:379、
  test_defeq_cache_vs_lean.py:113 + scripts/probe_014_*.py、
  bisect_014_m6.py）。缓解：兼容视图对象（`__iter__` 惰性产出元组、
  `append`/`len`/对象身份保持，fork 方零改动），或版本化 backend flag
  双后端并存。非增量路径 `_eval_position` 同步改（该路径无测试调用方，
  仅语义参照）。
- 触碰面：`lean_kernel/alm_p2.py`（仅此一个文件 + 依赖快照机制的
  测试如选兼容视图则零改动）。不碰图结构与权重，不违「一张图一份
  权重」；分层方向 `expr → lean_kernel → lean_vm` 合法。

### P2（配套）：同 env 多 case 复用 warm 前缀（fork 机制受控推广）
- 做法：同一 env 的各 case 共享只读 env 前缀的 history/vals，只增算
  term 段——机制就是求值器文档化契约（alm_p2.py docstring "tests
  snapshot/replace it to fork cases off a warm env prefix"），quot/
  string/defeq-cache/brec-drec 四测试已在用，**brec/drec 即 iota 家族
  先例**。
- 收益：case2+ 的 warmup 时间 228s→~2-5s/例（整套 19 例差分从 ~80min
  → 一次 warmup）；峰值不再每 case 重复爬升（配合 P1 后整场 ≤2GB；
  无 P1 时单 case 峰值仍 ~6.1GB，只能解时间不能解内存）。
- 风险：`tests/test_iota_graph_vs_lean.py` 禁 seed 的出处是 handoff 000
  陷阱 5（该测试含 env 污染子检查）。fork 不等于 seed（不预置判定、
  不改流内容，只复用同一 env 前缀的求值缓存），但**对这一个测试启用
  须经总控/任务卡明示批准**，不得顺手改。
- 触碰面：`tests/test_iota_graph_vs_lean.py`（fork 接线，~5 行）；
  库零改动。

### P3（顺手）：case 间显式 teardown
- 做法：每 case 结束 `del drv, enc; gc.collect()`（+可选
  `ctypes malloc_trim`），消除跨 case 的 arena 棘轮（复跑 6474 > 单
  case 6091 的差值即此）。
- 收益：小（几 hundred MB 量级）；无协议风险。
- 触碰面：测试 harness 生命周期管理。

### 否决项（如实记录）
- **降精度（float32/16 keys/values）**：违验收铁律 4——分数是
  float64 精确整数算术，tie-break 依赖其确定性。否决。
- **解析化 winner（fetch_by_position 的 argmax 有闭式解）**：可把
  O(h) 扫描降 O(1)，但等价性证明（非整 query/多term clear_key/tie）
  是独立语义工程，且救不了 §5 的规模外推。留作 P1 后时间瓶颈的
  未来方向，不在本拍承诺。
- **另写批量/向量化第二求值器**：ADR 精神下等于第二套实现，禁。

## 7. 对卡 012 的落地建议（给总控）

1. M-B 验收子项"iota 大 env 差分 ≤6GB 可跑"：**P1 即可达成且有富余**
   （预计 1.5-2GB）；P1+P2 后整场差分 ~2GB / 时间 ~一次 warmup。
2. 开新任务卡实现 P1（触碰面 `lean_kernel/alm_p2.py`，验证面 = 全部
   差分套件 + 本 ADR §4 的 footprint 复测），实现前按 AGENTS 规则
   独立复核本 ADR 的画像数字。
3. M-B"3000+ cid"与 M-C/M-D 的规模差分：改走引擎通道（§5），Python
   求值器的规模上限（P1 后 ~26k token）写进 `docs/VM_SPEC.md` 新节。
4. 术语统一：后续文档把"4440 常量"改为"81 常量/4440 token"。

## 证据文件（/tmp，会话期有效，数字已全文抄录上文）

- `/tmp/012_memprof/probe_static.py` + 输出（结构计数）
- `/tmp/012_memprof/probe_struct.py` + `.log`（结构画像全记录）
- `/tmp/012_memprof/rerun.log`、`rerun_rss_clean.csv`（复跑曲线）
- `/tmp/012_memprof/rss_sampler.py`（外采样器）

> **P1 开卡前置指令（审核 E5）**：按 AGENTS §四"不在仓库里的 harness 等于
> 不存在"，开 P1 优化卡时须把 footprint 复测探针（probe_struct.py 清理版）
> 提升进 `scripts/`——本 ADR §7.2 验证面引用了它，不能长期留在 /tmp。
