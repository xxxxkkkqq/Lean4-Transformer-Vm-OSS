# 任务 021：level canonical-by-construction（ADR 026 拍 B：encoder 全量 normalize + fold 规范发射 + canonical 臂退役）

状态：**CLOSED（2026-10-15 总控收口）**。拍 B ladder 全绿：lvl **34/34+0
xfail**、decl 全语料 **149/149+1 xfail**（7823.3s/1869MB，xfail 仅既有
ipr_dep_snd）、stepgraph **84/84（0 pinned）**（3755.4s/733MB）、引擎
**34/34+known 3/4**（重跑链 648.7s）、level 37/37、kernel_oracle
10/10+容量 3/3、轻七件全绿、dims 实测 58,565/7,676/362,418（复核修复
后重编译）、硬编码扫描零命中、文档六件同步。独立复核首轮 FAIL
（finding 1 影子双重归一 CRITICAL——修复 9533455：影子从源项计算 +
encoder 根归一一次/裸递归；finding 2 both_pm kind 相等；3/4 文档/归档）
→ 复核者复验 AGREE → §7 复核节在案。**23 套件里程碑回归 23/23 rc=0**
（池 18 + solo/重跑 5，2026-10-15）+ 帽校准 12 行落
scripts/run_cpu_regression.sh（§4 末项有完整证据表）。遗留登记
（全部转后续卡）：bf3 3 幸存者 2-beat 发射（Vector3 形，KNOWNGAPS）
、fold 动态根/影子 k≥2 嵌套（VM_SPEC §16.10 R 残余）、mode 位跨 ST
续体（G03 登记项不变）。总控亲执（用户指令"剩余内容必须全部完成"，
角色偏离同卡 020 先例，收口经独立复核五道门）。
角色偏离同卡 020 先例：图侧由总控承担，收口走独立复核五道门）**。
上游：卡 020 拍 A（ADR 026 草案定稿 xc 机制 + 硬约束"encoder normalize 必须是
level.cpp 的忠实移植"）、VM_SPEC §16.10 残余 2-5、ADR 025 §2.3 六实例部署。

## 1. 目标（三件 + 回归钉）

1. **Encoder 全量 normalize（静态边界，`expr/model.py` + `expr/tokens.py`）**：
   level.cpp:454-516 的逐行忠实移植（含逐路径一次不对称），`_enc_level`
   入口先归一再编码；排序键 = Param/MVar 的 **nid 全序**（图内固定全序，
   等价判定与键选择无关——等价 ⟺ 规范形相等，multiset 论证）。
2. **Fold 规范发射（运行期边界，`build_vm.py` I_PIL2）**：case B（l2 非零
   判定失败）保留 kernel mk_imax 逐规则精确语义；case A 改为
   **union-rebuild**——split(l1) ∪ split(l2) → 排序（kind+nid+offset，
   Max/IMax 基互排无语料证据→保守 fallback）→ explicit 吸收 → 同 base
   去重 → 右折叠重建，3 幸存者时 2-beat 发射（P_EMIT 相位扩展）。
   **修订 ADR 026 §3.2 草案的"两臂 select ~10 dims"**：探针 pF1/pF3/pF4
   证明只排 V0/V1 不够——explicit 吸收可把结果塌缩到单节点（既有
   position），摊平可产生 3-4 原子 union，发射序由 kind 序（Max < Param）
   决定；忠实移植含 succ 分配律（`normalize(succ (max u v))` =
   `max (succ u) (succ v)`，:449-453+:507-509 逐幸存者重包——pF4i 实证）。
3. **Canonical 臂退役（比较降级）**：6 实例 `_lvl_max_canon` 臂退役
   （deq 回到 eq_struct ∨ n2z，n2z 留给 is_prop/pl_prop）；预算实测净缩
   ~-8k dims（臂 -9.6k + fold 重建电路 +1.3-1.6k，以实测为准）。
4. **回归钉**：15 行 oracle 探针全部进 `tests/test_decl_injection_vs_lean.py`
   lvl 节为常驻差分行（pX1-pX7 静态不对称 + pF1-pF4j fold 行，含 2 个
   发射序负向钉 pF4i/pF4j）。

## 2. 依据（全部实测，非推理定案）

### 2.1 Oracle 探针（#KDECL 原始通道，4.33.1，.scratch/probe_norm_asym.py 原文）

| 行 | 断言 | oracle |
|---|---|---|
| pX1 | `imax (succ u) 1` vs `max (succ u) 1`（xc 孪生） | REJECT declTypeMismatch |
| pX2 | `imax (succ u) 1` vs `succ u` | REJECT（imax 路径不吸收 explicit） |
| pX3 | `max (succ u) 1` vs `succ u` | ACCEPT（max 路径吸收） |
| pX4 | `max 1 u` vs `max u 1` | ACCEPT（排序不敏感） |
| pX5 | `imax u 1` vs `max u 1` | REJECT（pairwise 源序 vs 排序形） |
| pX6 | `imax u 1` vs `max 1 u` | REJECT |
| pX7 | `imax 1 u` vs `u` | ACCEPT（D2: imax 1 u = u） |
| pF1 | fold 运行期 `imax(u+2,2)` 链 vs `u+2` | ACCEPT（explicit 2 被吸收→单节点） |
| pF1n | 同链 vs `u+1` | REJECT |
| pF2 | 3-arg union 链 vs `max (u+2) (v+2)` | ACCEPT |
| pF2n | 同链 vs `max u v` | REJECT |
| pF3 | 4-arg union 链（3 域 curried Type）vs 右折叠 3 幸存者形 | ACCEPT |
| pF4 | succ 包裹 max 原子链 vs 静态 max 形 | ACCEPT |
| pF4i | 同链 vs `imax (succ (max u v)) (u+2)`（错误嵌套序） | REJECT（succ 分配律实证） |
| pF4j | 同链 vs `imax (u+2) (succ (max u v))` | REJECT（发射序钉） |

pF4i 修正了立卡前的一个分析错误：我最初把 `normalize(succ (max u v))`
当成恒等，oracle 拒绝该行暴露 **succ 脊柱在 Max 支逐幸存者重包**（分配律）。
Python 移植 15/15 复现（.scratch/check_port_vs_probes.py 原文）。

### 2.2 语料扫描 + fold 设计验证器（.scratch/scan_fold_budget.py）

- **设计验证器 0 mismatch**：1497 条 Pi-spine fold 链逐位重放（kernel
  原始 mk_imax 链 vs beat-B 图侧设计 case-B精确+case-A union-rebuild），
  全语料 `W_graph == normalize(raw_chain)`——fold 设计经实测背书。
- **槽预算（测量值）**：侧 A（domain sort level）恒 1 原子（477/477）；
  侧 B（链累积）≤3 原子；union ≤4（414×2 / 51×3 / 12×4）；幸存者 ≤3
  （272×1 / 193×2 / 12×3 → 2-beat 发射 12 次必要，全部来自 Vector3
  闭包类型 = M-C 必踩形状）；explicit 吸收 12 次 / 存活 459 次两类都要。
- **排序键**：宽 union 成分全部为 Z-base explicit + param 原子
  （`P1,P1,P1,Z2`/`P2,P2,P2`/`P1,Z2,Z2`/`P1,P1,Z2`）——**语料内无
  Max/IMax 基互排**→比较电路无递归腿，Max/Imax 基对 → 保守 fallback。
- **静态普查**：160,570 棵 level 树（874 常量闭包 + decl/lvl/ipr 语料），
  raw 摊平宽 ≤4、规范形摊平宽 ≤3、spine ≤2、树深 ≤6、norm 改形 90 棵
  （encoder normalize 将真实改变 90 棵树的编码形状）。

### 2.3 kernel 引用

- `K/level.cpp:454-516`（normalize 全文）+ `:81-123`（mk_max/mk_imax
  智能构造）+ `:393-415`（is_norm_lt，kind 序 Zero<Succ<Max<IMax<Param<MVar
  = level.h:30 枚举，KL_* 1-6 编号同序）+ `:449-453`（mk_succ 逐幸存者
  重包）+ `:518-521`（is_equivalent = 一次 normalize 比较）。
- `K/type_checker.cpp:144-166`（infer_pi 左折叠 mk_imax 链——fold 火点）
  + `:345-348`（infer_sort succ 包裹）。
- 运行期通道的 kernel 对应物：**fold 输出必须等于
  `normalize(kernel 运行期构造项)`**——case A 的 kernel 构造项是
  mk_max 裸构造（max 顶），比较期 normalize 走 **Max 支全量摊平**，
  故图侧 fold 必须发规范重建形而非 pairwise 源序形（pF1/pF3/pF4 实证）。

## 3. 实现拍次（单卡两检查点，B1/B2）

- **B1（本拍）**：encoder normalize + fold union-rebuild + 15 探针行入
  测试 + **canonical 臂保留**（双保险：臂在规范形对上恒空转，只在
  fallback 形上兜底）。Ladder 全绿后进 B2。
- **B2（同卡续拍）**：canonical 臂退役（6 实例 `_lvl_max_canon` 调用点
  降级 eq_struct∨n2z），dims 记账，ladder 复跑。超预算 fold 形
  （union >4 或 Max/Imax 基互排）回退 pairwise 发射 = sound-incomplete
  （与 ADR 025 帽语义同向：只假拒不假收），登记 §16.10 新残余。

## 4. Verifier 集（完工唯一依据）

- [x] B1→B2 合并落地：`G02_ONLY=lvl` **32/32+0 xfail** rc=0
      （`lvl_b5.log` 1441s / 缓存影子复跑 `lvl_b6.log` 908s；B1 检查点
      曾证臂与 encoder normalize 不可共存——27/32，lvl_xc 被臂二次
      normalize 假收打破，据此 B1/B2 合并）
- [x] decl_injection 全节 **147/147+1 xfail 0 fail** rc=0（7735.1s，
      `decl_full_c.log`；xfail 仅 ipr_dep_snd 卡 019 既有登记）
- [x] level_vs_lean 37/37；stepgraph_infer_defeq **84/84（0 pinned）**
      rc=0（5179.1s/733MB，`stepgraph_021.log`）；引擎 **34/34 + known
      3/4 + argmax/softmax 流一致 34/34**（`engine_021.log`，
      1532.7s/399MB，SBIN=021 自证）
- [x] 重编译 `step_vm_021_scratch.sbin`：**58,445/7,676/362,418 nnz**
      （对 020 基线 +9,098/+1,557/+46,544——净增长，ADR §3 预估翻向
      按《实测为准》条款如实记账）+ kernel_oracle Part B 容量 3/3
      （影子致 List.map 7881>4096 破窗 → Sort-only 门控 + 共享缓存
      修复至 4044≤4096）
- [x] B2：臂退役后 ladder 全绿（B1/B2 合并落地，臂与 encoder
      normalize 不可共存为合并依据）；dims 实测净增长见上（ADR 条款）
- [x] 硬编码扫描零新增（拍 B delta 全量 grep：残留仅移植循环
      计数器；union-rebuild 仅 kind/nid/offset 判据）
- [x] 文档六件：VM_SPEC **§12.8.2**（三构造边界契约 + 比较降级 +
      图账）/§16.10 重写（1-5 结构性关闭 + 现行 R1-R6）、ENV_FORMAT
      level 槽位约定（E2 影子/X 链）、KERNEL_COVERAGE D4/D5 翻
      canonical-by-construction/全量实现、ARCHITECTURE 021 行
      （md5 a817d395…）、ADR 026 状态翻 ACCEPTED（含三个拍 B 修正
      并入）、本卡
- [x] 23 套件里程碑回归（2026-10-15，复核修复后新 sbin 174c31c 代，
      md5 3564c786…）：**23/23 rc=0** = 池内 18（`~/logs/lean4vm_
      cpu_regression/`，followon 自动化 16:44 起）+ 池杀 5 件 solo/重跑
      链真值（stepgraph_vs_lean 1180.6s/1540MB、quot 474.5s/7927MB、
      brec_drec 1622.7s/12485MB、defeq_cache 2338.4s/12983MB 四件
      `~/logs/021/reg_solo/`；decl_injection 7823.3s/1869MB
      149/149+1xfail `~/logs/021/decl_full_e.log`）。其余证据：
      stepgraph_infer_defeq 池 4323.0s rc=0 + 重跑链 3755.4s rc=0
      （84/84）、engine 池 264.0s + 重跑链 648.7s rc=0（34/34+known
      3/4）、mutation 池 1595.1s rc=0、olean 池 873.4s + solo 729.0s
      rc=0、defeq_branches 池 1781.6s + solo 1586.0s rc=0。修复前
      池证据整体保名 `~/logs/lean4vm_cpu_regression_prefix_b7/`。
      **帽校准 12 行**（scripts/run_cpu_regression.sh，a0d18cb 格式
      注释记实测依据）：池杀 5 行（decl 7200→11000、stepgraph_vs_lean
      1500→1800、quot RSS 6500→11000、brec 1800\|12000→2300\|17000、
      defeq_cache RSS 12000→18000）+ 池内余量 <1.25 的 7 行
      （stepgraph_vs_refvm 2000→2600、stepgraph_infer 4500→6100、
      check_e2e 900→1100、olean 900→1300、string 1500\|7500→1800\|
      10000、reducenat 2400→2900、defeq_branches 1800→2300）。

## 5. 触碰面

`expr/model.py`（normalize 移植——已落）、`expr/tokens.py`（_enc_level
接线）、`lean_vm/build_vm.py`（I_PIL2 fold union-rebuild + P_EMIT 相位
扩展 + B2 臂退役）、`tests/test_decl_injection_vs_lean.py`（15 行）、
`docs/VM_SPEC.md`、`docs/KERNEL_COVERAGE.md`、`ARCHITECTURE.md`、
`docs/decisions/026-*.md`、本卡、handoff。**禁触**：`lean_vm/ref_vm.py`、
`engine/*`（E2 相位码与 scratch 槽协议是图内数据，无格式变更）、
`compiler/*`、`model/` 源码、`scripts/run_cpu_regression.sh`（020 收口
件单独提交）。

## 6. 风险登记（ADR 026 §4 逐条 + 本卡新增）

1. **stepgraph 步数面**：encoder 改写后 90 棵树编码形状变化，步数/微步
   计会变；stepgraph_vs_refvm 0 pinned 项复核，decl lvl 行步数只记录不
   断言；判定逐值一致是唯一硬门槛，步数漂移按 ADR 026 §4.2 分诊协议。
2. **fold 2-beat 发射**：3 幸存者右折叠需 P_EMIT 相位扩展；首次实现
   若复杂度超预算，回退方案 = 4 槽 union 限 2 幸存者 + 第 3 幸存者
   fallback（M-C 前必须解除，pF3 行钉住）。
3. **臂退役的时序**：B1 臂保留期若发现臂在规范形对上非空转（= 有图内
   形不是规范形），先停手分诊（encoder/fold 漏了某个入口）再进 B2。
4. **B13/D14 未来交互**（ADR 026 §4.1 原文保留）：运行期实例化落地时
   level 替换必须重跑全量 normalize。

## 7. 独立复核（2026-10-15，干净上下文代理，五道门）

**首轮裁决：FAIL**——门 1-4 PASS，门 5 FAIL，findings 四条：

1. **CRITICAL（受理）**：影子从规范化形计算（`normalize(succ(normalize(L)))`）
   而非源项——双重归一类在 succ 边界的第二个面。非幂等 imax 形上
   `normalize(succ(normalize(imax u 1))) = max 2 (succ u)`（分配）而
   kernel 的 `normalize(succ (imax u 1)) = succ (max u 1)`（imax 路径
   不分配）。复核者实测 HEAD：`Sort (max 2 (succ u))` vs
   `(x : Sort (imax u 1)) → Sort 0` = oracle 拒、图收（**非受控假收**，
   违验收铁律 1）；反向形 oracle 收、图拒。
2. LOW（受理）：`_lvl_base_eq` 的 both_pm 把 PARAM×MVAR 同 nid 判同 base
   ——kernel operator==（level.cpp:126-136）先比 kind 再比 id；语料
   无 level mvar 不可达。
3. DOCS（受理）：KERNEL_COVERAGE 残留旧 D5 行碎片。
4. PROCESS（受理）：轻套件证据未归档（已补 `~/logs/021/light/` 7 件）；
   f17c386 提交信息描述了实际落在 31d6575 的修复（提交卫生备注在案，
   非代码缺陷）。

**修复（9533455）**：finding 1 两件套——①影子改从**源项**计算
（`sh = normalize(LSucc(source_l))`，缓存按源键——同规范形的不同源
不得共享影子，其 succ 包裹归一不同）；②encoder normalize **只在根
跑一次**、整树裸递归（探针 spy 实测抓到第二面：对 imax 路径孩子
`max(u,1)` 的再归一把它重排成 `max(1,u)`，编码树与 kernel 比较形
脱钩）；finding 2（both_pm 加 kind 相等）；finding 3（删过期行）。
**复验**：复核者两探针双向 AGREE（pS1d 假收闭合、pS2d 假拒闭合，
`~/logs/021/` 探针原文）；两行永久化为 `lvl_bs1/lvl_bs2`（shadow
边界钉）；lvl 全节 **34/34+0 xfail rc=0**（916s，`lvl_b7.log`）；
port 15/15、轻七件全绿（`~/logs/021/light/`）。decl 全语料 +
stepgraph 复跑进行中（`decl_full_d.log`/`stepgraph_021b.log`）。

**复核方法论注**：发现 1 的完整形态是"双重归一"这一单一机制缺陷的
**三个面**——旧比较臂（B1 实证）、影子计算（复核首轮）、编码器递归
（修复探针时 spy 抓到）——同一数学根因（normalize 非幂等：imax 路径
产物再归一会摊平分配）。beat B 文档已按此统一表述（VM_SPEC §12.8.2）。
