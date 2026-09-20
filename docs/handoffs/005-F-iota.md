# 005 — F 链：卡 009 brecOn/drecOn 一般 iota（handoff / 进度链）

核 0-5，OMP_NUM_THREADS=3，日志 $HOME/logs/009F/。总控占 8-13。
用户自有训练任务在吃约 11GB（/home/xkq/train，勿动），按 19GB 可用预算规划。

## 简报（F，第一个代理）

进会话先读：`AGENTS.md`（硬规则）、`docs/plans/009-brec-drec-general-iota.md`
（任务卡）、本文件、`docs/VM_SPEC.md` §12.7/§13（现有 iota/brec 记录）、
`docs/handoffs/003-D-wp7.md` 的"硬编码扫描"与 A17 peel 链写法（同类链的范本）。

**任务性质**：这是**探查先行**的卡。README 称 `brecOn`/`drecOn` 一般 iota
未实现，但 B 组最小 env 差分（P7.5c）已有 brec 7 例全绿。你第一步是搞清
"哪些一般形态当前真不支持"，产出差距清单后才许动图。**不许**为凑数把已支持
的当缺口，也不许把不支持的含糊过去。

**你只许改**：`lean_vm/build_vm.py`、`expr/tokens.py`（如需编码）、
新 `tests/test_brec_drec_iota_vs_lean.py`、`docs/VM_SPEC.md`、
`docs/KERNEL_COVERAGE.md` B/I 组、`docs/handoffs/005-F-iota.md`（追加）、
`docs/decisions/`（新 ADR）。
**禁改**：`engine/*`、`compiler/*`、`model/*`、`lean_vm/ref_vm.py`、
`lean_vm/step_driver.py`（属主卡 010，本卡不许动注入协议）、`scripts/*`、
`ARCHITECTURE.md`、`README.md`、`lean_kernel/*`。越界=FAIL。

**方法纪律**：
1. 探查阶段：真 lean 4.33.1 造 ≥10 组 brecOn/drecOn 最小用例
   （嵌套 inductive、带 indices、k=1/k=0、brec vs drec、major 需先 whnf、
   below 影子、跨 recursor），逐例记录当前图判定 vs 真内核判定。
   差距清单 + kernel 行引（`K/structural.cpp` iota 规则、
   `K/inductive.cpp:748/829 mk_rec_rules/check_recursors` 生成侧）写进本文件。
   探针走 PrivateTmp 或单跑，禁并行 oracle（固定 /tmp 互踩）。
2. 每补一个缺口：全链路（gate→frame select→发射→判定）→
   `python3 -c "import lean_vm.build_vm"` 语法检查 → 最小 env 差分 →
   更新本文件。**不留 `x=x` 占位、不留"注释说 below 替换但下方没替换"**
   （这是 C 链死过的坑，AGENTS §1.13）。gate 连写 ≥4 层 reglu 写完立刻
   import 检查。
3. 判定必须走图：不许 materialize 真 brecOn 展开闭包来近似结果。
4. 长任务 setsid 脱离管道，起后 `ps -o pid,rss,etime -p <pid>` 抽查，
   RSS>6GB（本卡用最小 env，正常远低于此）主动杀。pkill 先 pgrep -af 看清。
   master 日志放 REGRESSION_LOG_DIR 外。
5. 完工前：`python3 -u model/compile_vm.py --sparse model/step_vm_009_scratch`
   报 dims/lookups/RSS 增量（基线 24914/2878/186892 nnz，699MB 级）；
   `SBIN=$PWD/model/step_vm_009_scratch.sbin python3 -u
   scripts/verify_engine_vs_refvm.py` **不 --skip-cases**（卡 008 起 pow 已修，
   基线 34/34）不得倒退；全量回归 20 套件（REGRESSION_CORES=0-5，
   新差分测试尚未接入脚本，你单跑过即可并注明）。
6. 上下文吃紧就把差距清单完成度、已修/未修分支、下一步三件事写进本文件再退。

**真值**：`model/step_vm_new_sparse.sbin` 18,027,726B @ 21:59（24914 dims）
不许覆盖/删；vm_run 现基线 22:31（卡 008 钳位 1e6）。不许 git commit/add。

---

## 事故记录：F1 零产出阵亡（总控，2026-09-16 02:2x）

F1（agent_6f2fccc8）运行 ~43 分钟后以 harness 内部错误终止
（`database is locked`，非任务失败）。盘上证据：`$HOME/logs/009F/` 空目录
（01:38 建）；build_vm.py/tokens.py/VM_SPEC/KERNEL_COVERAGE mtime 均早于派发
时刻（18:17/18:09/22:52/19:28，全属 D/E 时代）；无测试文件、无 scratch 产物、
本文件无追加。**零损失重派 F2**，简报沿用上一段。纪律教训再记一条：
小步落盘的"第一步"应尽早——落一份最小探查骨架（用例清单表头）再深挖，
纯读 43 分钟不落盘，阵亡即全丢。F2 执行时把"探查清单先落表头"当第一个动作。

---

## 差距清单（F2，2026-09-16 凌晨，探查先行，逐例追加）

| # | 用例 | 形态（recursor/载体/indices/k/嵌套） | kernel 行引 | 真 lean 判定 | 当前图判定 | 结论 |
|---|---|---|---|---|---|---|
| E0a | `#check @Nat.drecOn` `@Nat.drec` | drecOn/drec 存在性 | 4.35 无 DRecOn 构造（src/Lean/Meta/Constructions/ 仅 BRecOn.lean）；4.35 kernel/inductive.h:77-121 已无任何 brec/drec 特判（全 recursor 统一 generic iota：major=whnf、lit→ctor、nextra） | 4.33.1 二进制：**Unknown constant `Nat.drecOn` / `Nat.drec`**（rc=1） | n/a | **drecOn 在判据版本不存在**。卡 009 的 drec 半边收敛为"实测无此构造"记录，非缺口 |
| E0b | `#print Nat.brecOn/.go/Nat.below` | Nat.brecOn 定义形态 | 同上（4.33.1 二进制实测为准） | `@[reducible] def Nat.brecOn {motive} t F := (Nat.brecOn.go t F).1`；`go := Nat.rec ⟨F 0 PUnit.unit, PUnit.unit⟩ (fun n ih => ⟨F n.succ ih, ih⟩) t`；`below := Nat.rec PUnit (fun n ih => motive n ×' ih) t` | toy env 现状：pair-free 重写值（`Nat.rec motive (F 0 0) (fun n ih => F n.succ ih)`），P7.5c-3 用 `Nat.brecOn.real` 重建闭包近似 | **brecOn 无原始 iota，纯 delta→rec→proj**。收口 = ENV 注真值（brecOn/go/below 三件套），判定走图的 delta+generic iota+proj，替换重建近似；F 真用 `.2` 影子/非 Nat 载体时 pair-free 与重建都失真 |
| E0c | `#check @List.brecOn @List.below @PProd` | 非 Nat 载体存在性 | 同上 | 均存在；`PProd : Sort u → Sort v → Sort (max (max 1 u) v)`（Type/Sort 值域，非 Type 专有） | — | 一般形态可达，探针可用 |
| G1 | 忠实 Nat.brecOn WHNF，t=0/1/2/3/4，F∈{F1s 忽略 bh, F2s 拆 ⟨ih,_⟩, F3s 拆 ⟨_,⟨ih,_⟩⟩}（方程编译 def 入 ENV） | 真 dump 值 brecOn/go/below 进 ENV（PProd→P2、PUnit→UnitT、u→0） | type_checker.cpp:504-508（`reduce_proj` 后 `whnf_core(*m)` 继续）；inductive.h:100-120 | oracle: 1/3/3,6/100,101（全 literal） | 图: 全停在 **raw field** `F1s (succ(pred n)) (Nat.rec … (pred n))` —— proj 交付的 field 不再归约（TASK_WHNF 调用者 E=1 合同） | **缺口 #1：proj 不续 whnf**。内核 proj-reduce 后继续归约到 head-normal；图对 TASK_WHNF 停在 raw field。D5（闭 major 交叉恒等式）经 DEFEQ 通道却是 True——合同只伤 whnf 顶层交付 |
| G2 | DEFEQ `brecOn 2 F2s =?= 3`、`brecOn 4 F3s =?= 100`（F 用 PProd.casesOn 拆对） | pair-destructure 方程编译 | inductive.h:77-121（generic iota 读 rec meta） | oracle: True / True | 图: False / False | **缺口 #2：pair-destructure 的 F 走 `PProd.casesOn`/`PProd.rec`——probe ENV 无 const_meta（recursor 无规则可用）且 PProd.casesOn 未映射到 P2.casesOn 约定**。属数据接线缺口（_norm_pprod 只映射 mk/Proj/类型形，不映射 casesOn）；待确认后修 |
| G3 | DEFEQ `brecOn 2 F1s =?= 3` / `=?= 4` / `brecOn 2 F1s =?= F1s 2 (go 2 F1s).2`（brecOn.eq 恒等式，闭 major） | 忽略 bh + .2 影子交叉验证 | BRecOn.lean:288-308（brecOn.eq 定理生成） | oracle: True/False/True | 图: True/False/True | **已支持**（DEFEQ 通道软 whnf 会继续 delta/beta/iota；pair-free 与忠实编码在这三条一致）——不记缺口 |
| G4 | DEFEQ stuck：`brecOn mot tq F1s =?= (go mot tq F1s).1`（tq=axiom，两侧同 delta 形）/ `=?= F1s tq (go tq).2`（错配应 False） | major 为开项，proj 重粘 | inductive.h:100（get_rec_rule_for 失败→stuck）；type_checker.cpp:504-508 | oracle: D6 True / D7 False | 图: D6 **False** / D7 False | **缺口 #3：stuck rec 上的 Proj 重粘 D6 判 False（内核 True）**；D7（错配 False）一致。待定位 |
| G5 | 非 Nat 载体 Lst：WHNF eL1(nil,FLs)/eL2(cons 1 nil,FLs)/eL3(cons 2 cons 1 nil,FLr 拆 ⟨ih,_⟩)；DEFEQ eL3=?=2 | Lst.below=Lst.rec P2 (fun n ih => P2.mk(FLs..))，brecOn=go.proj 同 Nat 形 | type_checker.cpp:504-508；inductive.h:93（major whnf） | oracle: 1/2/2；eL3≡2 **True** | 图: WHNF 全停在 raw field `FLs nil UnitT.mk` / `FLr cons(…) (Lst.rec…)`（G1 机制在通用载体复现）；DEFEQ eL3 **no halt after 1200/6000 steps** | **缺口 #1 的载体推广 + 缺口 #4：DEFEQ 通道在 pair-destructure 链上死循环（不收敛）**。loop 不是 False，是超时——与 Nat D3/D4 的 False 不同机制（这里 meta 已接好，P2.casesOn 规则可用）。待定位 |

**内存事件（F2，03:0x–03:2x）**：probe2（全族单 env，141 consts）无输出期 RSS 爬到 6.48GB 触线自杀（AGENTS 护栏）；拆成分组最小 env（probe3，73–130 consts/组）后 lst 组的 DEFEQ 死循环单条仍冲到 **11.1GB** 才被第二次抽查发现（监控抓错 PID：pgrep 先匹配到 bash 壳，python 子进程没盯住——教训：**watchdog 必须锁 `$!` 真 PID**）。已加 run_guarded.sh（RSS>4GB 自动 kill -9）+ max_steps 降 1200。lst 的 D(eL2,eLR) 在该 11GB 期被杀，无判定输出（按死循环同机制处理，未钉结论）。

---

## 事故记录 2：同错误第 3 次（F2、I1 阵亡，总控 2026-09-16 03:4x）

`database is locked` 于 ~2 小时内击杀 3 个代理：F1（01:32→~02:15，43min）、
F2（02:16→03:33，77min）、I1（03:20→03:35，15min）。**已排除的成因**（实测）：
磁盘（45% 使用、454G 空闲 @03:38）；客户端重启（zcode zygote ELAPSED 10h55m
横跨全部死亡时刻）；内核 OOM（无记录，18G 可用）；用户训练任务（已不在进程表）。
**相关性**：F2/I1 死亡相隔 2 分钟，与 I1 的 lake build 拉起 15 个 lean worker
（~13GB、swap 5G）同时；但 F1 死亡时机器空闲——负载假设不完整。
未证实假说（不猜，记录在案）：同 workspace 多会话并发写 `~/.zcode` 会话库。

规避参数（对后续所有派发生效）：
1. **同时只许 1 个写盘代理**（只读可并行）——回到串行纪律，本轮并行实验以
   连死两代理收场；M-A 改串行重派（时机：lake build 完成后收编产物）。
2. **缩短单派发寿命**：卡 009 拆段，F3 只做探查收尾+缺口定位，#1 单立后续卡。
3. **落盘节拍 ≤10 分钟**：静默工作窗超时即先写结论再深挖。
4. **孤儿产物收编**：F2 的 setsid 探针（probe_groups.log，mu 组）与 lake build
   均由总控盯 RSS 继续存活，结果交下一任读取。

F2 遗产盘点：差距清单 7 行全落盘（上表）；build_vm.py/tokens.py **零改动**
（mtime 09-15 18:17/18:09，F2 未及动图）；无 scratch 产物。缺口 #1–#4 的
证据、kernel 行引、交叉验证（G3"已支持"行）齐备，F3 从差距清单直接续。

## F3 简报增补（总控 → F3，2026-09-16 03:4x）

- 你是卡 009 第三任，前段所有权/禁改清单/机器纪律照 F1 简报原样生效。
  **范围压缩**（防阵亡丢面）：
  (a) 收编 `$HOME/logs/009F/probe_groups.log` 的 mu 组结果，补 G1 行"载体推广"
      结论；D(eL2,eLR) 用例单跑重钉（run_guarded.sh 已就位）；
  (b) **缺口 #2** 定位+修复（probe ENV 的 PProd.casesOn/rec const_meta 数据接线，
      `_norm_pprod` 映射扩展——build_vm.py 内改，属你所有）；
  (c) 缺口 #3（stuck rec Proj 重粘 D6）与 #4（DEFEQ pair 链死循环）各写一份
      **定位备忘录**：证据、假设、候选修法、影响面。不要求修，修了更好；
  (d) 建 `tests/test_brec_drec_iota_vs_lean.py` 收已修用例 + G3"已支持"回归位。
- **缺口 #1 不许动**：它是 TASK_WHNF 交付合同变更（proj 后继续 whnf vs 停
  raw field），牵动全套既有差分，须先 ADR+总控裁决；F2 的证据已够写 ADR 草案，
  你可以把草案放进 docs/decisions/（新号）但不实现。
- E0a"drecOn 不存在"的 README/KERNEL_COVERAGE 口径修正建议写进本文件，
  README 归总控改。
- 每完成 (a)-(d) 任一项当场追加本文件；完工或退场前把 scratch 编译/引擎对拍
  状态写明（若只修了 #2 数据接线也须重编 scratch 验证 34/34 不倒退）。

---

## 事故记录 3：F3 秒死，病因定位=总控会话自身（2026-09-16 03:45）

F3（agent_4989d4d1）派发后 **84 秒**阵亡，同错 `database is locked`，零产出
（本文件最后一次变更 03:39 是总控所写）。四连死时间线：F1 43min / F2 77min /
I1 15min / F3 84sec——**与代理寿命、机器负载（已排除磁盘/OOM/客户端重启，见
事故记录 2）、写盘并发数全部解耦**。唯一共因：都由本总控会话（sess_ff013798）
派生。结论：病在本会话（超长+多轮压缩+大粘贴稿灌入的会话库状态），换新窗口
即愈。lead2 交接段见 001 handoff 末尾；F3 范围原样更名 F4，新 lead 直接派。

---

## F4 段（执行记录，2026-09-16 派发）

F4 = 卡 009 第三任执行者（F1/F2/F3 死史见上）。范围 = "F3 简报增补"四项，不扩。
落盘节拍 ≤10 分钟一条，本段即第一动作（深挖前落盘）。

| 子任务 | 内容 | 状态 |
|---|---|---|
| a1 | 收编 $HOME/logs/009F/probe_groups.log mu 组结果，补 G1"载体推广"结论 | pending |
| a2 | D(eL2,eLR) 单跑重钉（run_guarded.sh，/tmp/probe009F/） | pending |
| b | 缺口 #2 定位+修复：probe ENV PProd.casesOn/rec const_meta 数据接线，_norm_pprod 映射扩展（build_vm.py） | pending |
| c1 | 缺口 #3 定位备忘录（stuck rec Proj 重粘 D6）：证据/假设/候选修法/影响面 | pending |
| c2 | 缺口 #4 定位备忘录（DEFEQ pair 链死循环）：证据/假设/候选修法/影响面 | pending |
| d | 建 tests/test_brec_drec_iota_vs_lean.py（已修用例 + G3 回归位） | pending |
| #1 | 缺口 #1 ADR 草案（docs/decisions/ 新号，只写不实现） | pending |
| v | 收尾：import 检查、scratch --sparse 编译、引擎对拍 34/34、20 套件回归 | pending |

### (a1) mu 组收编 + G1"载体推广"结论（F4，03:5x）

来源：`$HOME/logs/009F/probe_groups.log` GROUP mu（66 consts，总控盯活的孤儿 run）+
GROUP iv/nt 同文件。原文结论：

- `W eMU1`（`@MA.brecOn … MA.base FMA FMB`，互递归 MA/MB 载体）：oracle `LitNat 20`；
  图停在 raw field `FMA MA.base UnitT.mk`（proj 交付的 field 不再归约）。
- `W eMU2`（major=`MA.a (MB.b MA.base)`）：oracle `LitNat 21`；图停在 raw field
  `FMA (MA.a (MB.b MA.base)) (MB.rec …)`——与 Nat 载体 G1 完全同机制，且下面挂着
  未归约的 `MB.rec`（互递归对侧递归器）。
- `D eMU1=?=eMU1R`：oracle `True`；图 `TimeoutError: no halt after 1200 steps`
  ——缺口 #4 的 DEFEQ 不收敛在互递归载体复现（与 lst 同机制，非 False 判定）。
  `D eMU2` 无输出：watchdog 在 4GB 线杀死（RSS 累积）。
- iv 组（索引载体 `IV : Nat → Type`）：`W eIV1/eIV2` oracle 5/6，图同样停 raw
  field `FIV 0 IV.v0 UnitT.mk` / `FIV (0+1) (IV.v1 …) (IV.rec …)`——raw field
  停在**带 index** 载体上同样成立。nt 组（嵌套 MyTree）`W eNT1/eNT2` 同机制。

**G1 行"载体推广"钉板结论**：缺口 #1（proj 不续 whnf、TASK_WHNF 停 raw field）
不是 Nat 载体特例——在 Lst（G5）、互递归 MA/MB、索引 IV、嵌套 MyTree 四种载体上
全部复现，机制与载体无关（proj 交付 → 停）。修复属 TASK_WHNF 交付合同变更，
见 ADR 草案（本卡 016），本卡不动。
缺口 #4（DEFEQ pair 链不收敛）载体推广：lst（6000 步不收敛，收编 log 钉板）+
mu（1200 步不收敛）两组独立复现。

### (a2) D(eL2,eLR) 单跑重钉（F4，04:0x，/tmp/probe009F/probe4.py，日志 $HOME/logs/009F/f4_lst_eL2.log）

Fresh 进程、lst 组 73 consts、max_steps=1200、watchdog 锁真 PID（4GB 线，峰值
1.79GB 未触线）。原文输出：

```
step 99: stream=2939 fp=4e49249c focus=<decode fail ValueError>
step 199: stream=3128 fp=68803510 focus=Const(name='Nat', levels=())
CYCLE focus step 199 == 299 len=28 stream=3228
#### RC_probe4=0
```

**钉板结论**：D(eL2,eLR) 图侧不收敛确认（oracle True）。且机制钉死为 **livelock
而非发散**：焦点闭包在 step199/299 完全同形（`Const Nat`），流仅按 STATE token
1/步增长（3128→3228）——机器在"重推同一 whnf 任务"里转圈，不产生新结构。
这修正 F2 的"按死循环同机制处理，未钉结论"：现在 D(eL2,eLR) 与 D(eL3,eLR)
同判（no halt），缺口 #4 在 lst 组两条 DEFEQ 上全钉。

### (b) 缺口 #2 定位进展（F4，04:0x）——"数据接线"不成立，根因是 HAdd 类脚手架

实验 `probe5.py`（nat 族，probe3 同款接线：`const_meta_for` 全量元数据 +
`_pprod` 的 PProd.casesOn→P2.casesOn 映射 + Nat.below/brecOn 真 dump 值替换），
日志 `$HOME/logs/009F/f4_nat5.log`，原文：

```
== D d1=?=e1   oracle: True   graph : ('ok', True)
== D d2f=?=ef  oracle: False  graph : ('ok', False)
== D d3=?=e3   oracle: True   graph : ('ok', False)
== D d4=?=e4   oracle: True   graph : ('ok', False)
```

**F2 假设被否定**：const_meta 接线 + casesOn 映射后 D3/D4 仍 False（不是不收敛，
是快速错判）。真根因（`dump8.lean` 项级证据，`F2s.match_1`/`FLr` 的 cons 分支）：
方程编译把 `ih + (k+1)` 编成
`HAdd.hAdd.{0,0,0} ((fun _ => Nat) b) Nat ((fun _ => Nat) b) (instHAdd (fun..) instAddNat) a 1`
——首/三参是 **beta 红子**（动机替换残留），`olean_export._norm_hbinop` 只认
`args[0]==args[1]==args[2]==Const Nat` 的闭合形，红子形**漏网**；图内类脚手架
（HAdd/HAdd.add 投影/instHAdd）是 §9.2 Phase-6 明确排除切片 → 链尾卡在不可
归约的 `HAdd.hAdd …` 上，与字面量比对 → False。PProd.casesOn 本身（def→delta→
PProd.rec 通用 iota，fire_iota 门 `K/inductive.h:77-121` 元数据驱动）经映射
P2.casesOn 后**不是**堵点。

候选修法（属图/编码器，风险自低到高）：
  (i) `expr/tokens.py` 编码期把红子形 hAdd 数据化归一（与 _norm_hbinop 同构但
      在 Encoder 内做 beta-then-match，属"ENV 是数据"边界，最小侵入）；
  (ii) build_vm 增补 ENV 侧 beta 归一（编码前对 ENV 值做一次性 beta-头归一，
      使 _norm_hbinop 闭合形命中——但 olean_export 不属我，改在测试侧 norm
      管线预 beta 化，等价且零图改动）；
  (iii) 真接类脚手架投影（HAdd.add 字段 proj + 实例 delta）——大工程，不属本卡。
本卡取 (ii)：在 `tests/test_brec_drec_iota_vs_lean.py` 的 env 构建里对 dump 值
做"编码前头部 beta 归一 + _norm_hbinop 复跑"，G2 的 D3/D4 即可钉绿；(i) 若总控
要推广到真 env 再立卡。

---

## 事故记录 5：F4 阵亡于 04:14 客户端 crash，本文件回到总控手里（2026-09-16 04:2x，lead 窗三）

F4（agent_b2fed284，新总控窗三 03:52 派发）随客户端 OOM 级联倒下，与 G（006，
零盘上产出：step_driver.py mtime 仍 2026-09-06）、I2（04:15:57 database locked）
同事件。非单会话 pathology，是全机负载事件：lake build 20 worker 峰值
（loadavg 5/15 分钟 36/35）叠多线代理与总控灌入，swap 5G 压死客户端。
总控自记账：继承"lake 勿杀"后只盯不封顶，失稳在主控，补救参数见 008 恢复段。

F4 落盘进度（以其 04:10 版记录为准，可信）：
- (a1)(a2)(a3) 完成：mu 组收编；G1"载体推广"钉板（raw field 停在 Lst/互递归
  MA-MB/索引 IV/嵌套 MyTree 四载体全复现，#1 机制与载体无关）；eL2 重钉——
  **机制更正**：D(eL2,eLR) 是 True/False 快速错判不是死循环，与 #2 同根。
- (b) 定位完成：F2 的"PProd.casesOn 无规则"假设被探针否定；真根因=方程编译把
  hAdd 编成带 beta-redex 残留、`_norm_hbinop` 只认闭合形漏网；修复取 (ii) 测试侧
  编码前 beta 归一（零图改动），(i) 编码器侧推广真 env 另立卡。
- (b) 实施、(c1)(c2) 备忘录、(d) 测试收编、(v) 收尾、#1 ADR016 草案未完成。

零污染确认（总控 04:2x 亲验）：build_vm.py/tokens.py 仍 09-15 代（18:17/18:09），
无半成品 tests/scratch 产物，真值表未动。

F5 续跑清单（按序）：b 实施 (ii) 钉绿 D3/D4/eL3 → c1/c2 定位备忘录 →
d 收 `tests/test_brec_drec_iota_vs_lean.py`（含 G3 回归位）→ v 收尾
（import 检查 + scratch --sparse + 引擎对拍 34/34 + 20 套件）→ #1 ADR016 草案。
**派发冻结中**：等 008 恢复清单的人裁后复命。

---

## F5 段（执行记录，2026-09-16 04:2x 派发，从盘上记录续跑）

F5 = 卡 009 第四任执行者。F4 的 (a1)(a2)(b 定位) 结论直接继承，零重做。
核 0-5，OMP_NUM_THREADS=3，日志 $HOME/logs/009F/，watchdog 锁 `$!` 真 PID、
树聚合 RSS>4GB 主动杀。Mathlib 封顶重建（核 14-19，pgid 807184）勿碰。

| 子任务 | 内容 | 状态 |
|---|---|---|
| b | 缺口 #2 实施：新测试 env 构建里"编码前头部 beta 归一 + _norm_hbinop 复跑"（路线 (ii)，零图改动），钉绿 D3/D4（Nat 对）+ eL3/eL2（lst 对） | in_progress |
| c1 | 缺口 #3 定位备忘录（stuck rec Proj 重粘 D6 判 False、内核 True）：证据/假设/候选修法/影响面 | pending |
| c2 | 缺口 #4 定位备忘录（pair-destructure 链：快速错判机制已由 F4 更正归 #2；lst 6000 步不收敛仍是死循环个案）：证据/假设/候选修法/影响面 | pending |
| d | `tests/test_brec_drec_iota_vs_lean.py` 收 G3"已支持"三例回归位 + b 钉绿全部用例；期望值现跑 oracle | pending |
| #1 | 缺口 #1 ADR 草案 → docs/decisions/016-*.md（只写不实现） | pending |
| v | 收尾：import 检查 → scratch 编译或"图零改动免重编"证据 → 引擎对拍 34/34（或免） → 20 套件回归（REGRESSION_CORES=0-5） | pending |

节拍：≤10 分钟一条追加本段。若 b 实施被迫要动 tokens.py/build_vm 编码侧（路线 (i)），停手记证据等总控裁。

### F5-b01（04:5x）norm_ext 预检完成，D3 在清洗后 ENV 仍 False——F4 的"真根因=hAdd 红子"对 D3/D4 不成立

预检探针 `/tmp/probe009F/f5_a1_normcheck.py`/`f5_a2_rawform.py`/f5_a4（日志
`$HOME/logs/009F/f5_a{1,2}*.log`、`f5_a4_whereisadd.log`，无图求值，纯 dump+归一）：

- 红子位置修正：beta 红子形 `HAdd.hAdd.{0,0,0} ((fun _=>Nat) x) Nat ((fun _=>Nat) x) (instHAdd ..) ih e`
  在 **`F2s` 本体值**里（不在 `F2s.match_1`，那里 add=0；F4 备忘录的位置写错了）。
  `F3s` 值无 add；`F3s.match_1` 是**闭合形**（args[0..2]=Const Nat），plain norm 的
  `_norm_hbinop` 当场命中、归一成 `Nat.add`（探针计数 norm 后=0）。
- `norm_ext`（f4norm.py，非依赖 beta + hbinop 复跑）实测把 `F2s` 的红子全部洗掉：
  `norm_ext(F2s)` 的 hAdd 残留计数 = 0（`f5_b_diagnose.log`）。**清洗函数本身有效。**
- 但把 probe5 全接线（const_meta + _pprod 映射 + Nat.below/brecOn 真值）下的 norm
  换成 norm_ext 后单跑（`f5_b_natext.py`，日志 `f5_b_nat.log`，ENV=78 consts，
  RSS 3.55GB@2min 被手动杀——watchdog 盯错 PID，`setsid nohup env` 时 `$!` 是外壳、
  真 python 子 PID 要 pgrep 二次解析，教训已在案）：**D3 (`brecOn 2 F2s =?= 3`) 仍
  ('ok', False)**。D1/D2f 与 oracle 一致。
- D3 trace（`f5_b_trace3.py`/`f5_b_tail.py`，日志 `f5_b_trace_d3.log`/`f5_b_tail_d3.log`）：
  **不是活锁，是快速错判**——step 207-210 焦点还有效（Pi(Nat, Sort 1)），
  step 211-212 A=1（判决位），**step 222 停机 verdict=False**（A=B=D=0 尾影）。
  与 F4 (a2) 的 livelock 结论不同机制（那条是 eL2，本条是 d3）。
- 正在跑：`f5_b_tail.py d3 90`（pid 844892，RSS 1.09GB，90 步宽窗解码判决路径，
  日志 `f5_b_tail_d3b.log`）。

**零受阻**：未动 `expr/tokens.py`/`lean_vm/build_vm.py`（mtime 仍 09-15 18:09/18:17），
路线 (ii) 测试侧进行中没有被迫越界。Mathlib 重建（pgid 843828，核 14-19）已确认勿碰。

### F5-b02（05:0x）norm_ext 不足；真堵点=probe `_pprod` 的 casesOn 约定错（顺序+level），F2 假设方向对但接线错了

- `f5_b_refcmp.py`（norm env，日志 `f5_b_refcmp.log`）：RefVM 判 d3 直接
  **REJECT code 1: "incorrect number of universe levels for 'P2.casesOn',
  #1 expected, #0 provided"** —— 冻结参照机暴露了图侧吞掉的软失败。
- 修 level 再跑（`f5_b_refcmp2.py`，日志 `f5_b_refcmp2.log`）：ref 仍同样拒绝
  → 0-level `P2.casesOn` 另有来源。`f5_c_levels.py nat`（level 修复+beta 清洗
  的 ENV 上图）D3/D4 仍 ('ok',False)（4/7，D6 维持缺口 #3 False）。
- 来源钉死（扫描探针 + `p5d.lean` 内核对尾器实证）：
  1. **`_norm_elim_spine` 重建头部丢 level**（`Const(head.name)`，olean_export.py:300-320）
     ——凡走 swap 的 casesOn 全变 0-level，与 toy meta 的 1 lparams 冲突。
  2. **probe3._pprod 的 PProd.casesOn 解包顺序错**：真 dump 的 @-spine 实测
     （4.33.1 内核对尾器报错为证，`p5d.lean`）是 `(α, β, motive, MAJOR, minor)`
     （casesOn 系 = motive 后紧跟 major 再 minors；`@Nat.casesOn` 同理由报错钉死），
     而 `_pprod` 按 `(α,β,motive,minor,major)` 解包并发射 `(major, mot, minor)`，
     之后 `_norm_elim_spine` 又对同一节点二次 swap → 终态 `(mot, minor→占major位, …)`
     = 双错。Nat.casesOn 的真实 dump app 走 swap 后 `(major, motive, alts)` 是对的
     （所以 C/B 组历史测试全绿）；**只有 PProd→P2 映射与 swap 叠加处出错**。
- 修法（全部测试侧 norm 管线内，零图改动，符合 (ii) 授权）`/tmp/probe009F/f5norm.py`：
  `_pprod` 发射 `(mot, major, minor)`（让 elim swap 完成最后一步到 toy 序）+
  管线尾部 `_relevel` 给 `P2/Nat/Bool.casesOn` 头补 `(LZero(),)` + `nondep_beta`
  洗 F2s 红子 + hbinop 复跑。`f5_c_levels.py nat`（pid 885828）验证中，
  日志 `$HOME/logs/009F/f5_c_nat2.log`；随后 lst 组同管线。
- 顺带钉板（c1 素材）：D6 (`brecOn mot tq F1s =?= (go mot tq F1s).1`) 在
  level 修复后的 norm2 env 里 **ref=True（与 oracle 一致），图=False** ——
  缺口 #3 是**图的 DEFEQ 下降问题**，不是 ENV 数据问题（ref 参照机同 token 流判对）。
- 运行状态：单探针进程，RSS <1.2GB；无 build_vm/tokens 改动。

### F5-b03（05:2x）norm2 管线在 RefVM 上 7/7 与 oracle 一致；图侧 D3/D4 仍 False=图 DEFEQ 下降 bug（非数据）

- `f5norm.norm2`（顺序修正+relevel+beta+hbinop）env 喂 RefVM
  （`f5_b_refcmp3.py`，日志 `f5_b_refcmp3.log`）：**d1/d2f/d3/d4/d5r/d6l-d6r
  全部与 oracle 一致**（唯 d6l=?=d7r ref 硬拒 code1 infer_app 参数类型不匹配，
  oracle=False——拒绝类一致）。→ **ENV 数据管线判为正确**，(ii) 路线的数据侧完成。
- 同一 env 上图（`f5_c_levels.py nat`→`f5_d_trace4.py`，日志
  `f5_c_nat2.log`/`f5_d_trace_d3.log`）：D3 仍 ('ok',False)。trace 显示
  链条各段形状全对（`P2.casesOn.{0}` (major,mot,minor) toy 序 ✓、
  `Nat.casesOn.{0}` (major,mot,alts) ✓、pred/succ 数值链 ✓、进到
  `Nat.add` 深度），**不是卡壳是判错**——图在 ~330-400 步给终判 False。
  端局 trace（460 步、i>=300 起每步含 D 帧链）在跑：
  `f5_d_trace5.py`，日志 `$HOME/logs/009F/f5_d_endgame.log`。
- 判读框架：若端局显示"两侧都 whnf 到 lit 后仍拒"，则是 DEFEQ 判决交付 bug
  （build_vm 下降分支）；这超出 (ii) 测试侧范围，届时按简报**停手记证据等总控裁**
  （build_vm 的 DEFEQ 分支是热路径，动它=改图，须总控批+全量回归）。
- 状态：探针 pid 见日志首行；RSS 峰值 <1.3GB；图文件零改动（mtime 不变）。

---

## 事故记录 6：F5 阵亡（孤立 harness 库锁，非机器事件）+ F6 任务书（总控 lead窗三，05:3x）

F5（agent_956959b0）05:2x 会话终止。**死因未定案**：客户端未重启（zcode-cli
寿命 1h19m）、无 OOM（用 5.8G/可用 24G）、无机器事件重合——候选解释是
单发 `database is locked`（既往主死法）或代理自截会话：尾句"现在跑全套 20
套件回归"**并未执行**（无回归进程、无新日志目录），且 detach 探针仍在其后
自行启动（f5_c_levels.py lst，pid 911938，05:34，sequencer 遗腹子）。
记录本身零丢失：F5-b01..b03 落盘 + $HOME/logs/009F/f5_* 全在。
F6 第 0 步：收编 lst 探针的产出（f5_c_lst.log/f5_c_lst2.log，等 pid 911938
自然结束，>4GB 水位照旧），其结果直接决定 (c2) 备忘录里 lst 是否同根。

F5 净产出（把 #2 的真正堵点换了层，比 F4 定位又进一步）：
- 数据侧完成：`f5norm.norm2`（`_pprod` spine 序修正 `(α,β,mot,MAJOR,minor)`
  实证 + `_relevel` 补 level（源头 `_norm_elim_spine` 丢 level，
  olean_export.py:300-320）+ nondep_beta 洗红子 + hbinop 复跑）env 喂 RefVM
  **7/7 与 oracle 一致**（f5_b_refcmp3.log）→ ENV 数据管线判正。
- 端局 trace（**f5_d_endgame2.log 尾段 05:29**，比最后落盘新）：i=593 弹出畸形
  `TDEFEQ(V1=3006,V2=0,X=0,E2=3007,F2=0)`（V2=0 空操作数），i=594-595 D 栈
  排空，i=596 done 停机判 False。符合 F5 预设判读框架：**build_vm DEFEQ 下降
  分支的判决交付 bug**，不是数据问题。
- c1 素材钉死（b03）：D6 同 env 下 ref=True（=oracle）/图=False——D3/D4/D6
  同根概率高，图侧一处修复可能收口多个缺口；lst eL3 的 6000 步不收敛待归因。

### F5-b04（05:5x，F5 收尾段）交付物就位 + lst 复钉定案 + 与 F6 的接缝声明

- **交付物（F5 落盘，F6 直接续用、勿重建）**：
  1. `tests/test_brec_drec_iota_vs_lean.py` **已存在**：norm2 管线收编为
     测试内函数（A 节=数据不变量，实测绿：F2s 无红子 HAdd、
     F2s.match_1 的 P2.casesOn=3 参 (major,Lam,Lam) toy 序 + levels=(LZero,)）；
     B nat（G3 三例 + D3/D4 + D6/D7 七例）/ C lst（eL1/eL2/eL3 + 负控 eLF
     四例）逐例 DEFEQ，**期望值全部现跑 oracle，不预置答案、不放宽断言**。
     首跑在途：`$HOME/logs/009F/f5_test2.log`（pid 923520，watchdog 4GB）。
     F6 修好图后直接复跑该文件即得"全钉绿"证据，无需新写 harness。
  2. `docs/decisions/016-whnf-proj-rawfield-contract.md`：#1 ADR **草案**
     （三案 A=改 I_PROJ 续 whnf / B=驱动器出口循环补推[倾向] / C=记限制；
     未实现，影响面与证据已全列）。
- **lst 复钉定案（收编我自己杀掉的 911938 遗腹探针）**：
  `f5_c_lst.log`：eL1 在 **norm2 修正 env** 下 TimeoutError no halt@600；
  `f5_c_lst2.log`：eL2 同 env 同 timeout（RSS 3.3GB 水位杀）。eL3/eLF 未
  再排（内存纪律）。→ **缺口 #4 的 lst 不收敛不是坏数据伪影**，独立成立；
  见下 c2。
- **探针/内存纪律补充落账**：本轮再次确认 `setsid nohup env` 下 `$!` 是
  外壳，真 python 需 `pgrep -f` + RSS>50MB 过滤二次解析（b04 起已用此法）。

### F5-c1 备忘录（缺口 #3：stuck rec 上的 Proj 重粘）——F13-04 按 F11-03/F13-01/F13-02 重定性改写

> 本节为 F5 原文的重写。原文"图 restick 交付形态错 + 纯图 DEFEQ 下降 bug"
> 两个主张均被后续证据推翻；历史原文见 git/早期快照，判据翻案见 F11-03。

- **重定性结论（三层）**：
  1. **交付层无罪**（F11-03 判读 f11_p2，i=31/63）：双侧 whnf 的
     stuck-proj 交付 `Proj(P2,0,·)` 与内核 reduce_proj 失败原样返回
     （K/type_checker.cpp:503-508）一致——c1 旧假设"不对称中间态"不成立。
  2. **当时 False 的真病灶=测试侧注入常量的层级保真**（F11-03）：dump 的
     `Nat.brecOn` 值内 `go@{LParam u}` 被 `_spec` 折级洗成 `go@{LZero}`，
     与 d6r 使用点具体层级 `{1}` 头对头不一致 → 图触发 x-pi/infer 深降，
     造出 `UnitT =?= Nat` 假 False。**F5-b03 分离判据的失效条件**：数据
     本身含非法层级对时，"ref=True/图=False ⇒ 纯图 bug"无效——ref_vm
     快速路径不比常量层级，分叉是数据伪影。
  3. **数据修后暴露的图侧真缺陷（现存）**：F11-04 use-site 实例化后层级
     头对头一致、False 臂消失，d6/d7 转 Timeout。F13-01 钉死机器步：头对
     `Nat.rec@{max(1,1)} =?= 自身`因 `_lvl_eq` 无 Max/IMax 递归、无同闭包
     捷径而落入软 whnf/proof-irrel 阶梯，False 解缠进 DE_PRJ 假臂重派环
     （f11_p7 cycle1 i=64-439）。修①（位置恒等捷径，内核引据
     K/level.cpp:517-520 is_equivalent 深层结构即真）→ d7 快速 False。
     d6 残留=语义增长环，入口=软 INFER 的 arg-domain 检查（内核
     infer_type 走 infer_only=true 不做该检查，K/type_checker.cpp:360-362/
     :174-205）在真 dump below 域上的展开；修②（软模式跳过）失败
     （d7 的 False 下降依赖同一验证式级联），已回滚——d6 为开放缺陷，
     停手等裁（005 F13-02 末条）。
- **kernel 引用（现行有效集）**：`K/type_checker.cpp:503-508`（proj 卡死
  原样返回）、`:1216-1221`（stuck-proj 对端臂）、`:1123-1138`
  （lazy_delta_proj_reduction）、`:360-362` + `:174-205`（infer_type
  infer_only 不查 arg-domain）、`K/level.cpp:517-520`（层级深层结构相等）。
- **影响面（现行）**：C 组 lst 4/4 绿；B 组 d1/d2f/d3 绿、d4 帽内合法慢
  （648 步，待 F13-03 抬帽）、d7 快速 False、**d6 Timeout=卡 009 最后
  真缺陷（裁决项）**。
- **F15 终局层（四层定谳，2026-09-16，裁决 2/3/4）**：
  4. **d6 定案=KNOWN-GAP，不再是开放缺陷**。F14 fix2（I_ARG 跳参第 2
     变体）失败后，裁决 2 以新简报授权第 3 次：软 INFER 通道对齐内核
     infer_only 脊（`K/type_checker.cpp:189-205`：不 infer 实参、不比
     arg-vs-domain；对照完整通道 `:174-188`）→ 图侧新增专用臂 I_ARG_S=69
     （老 I_ARG 硬语义未动，decline 级联与 c1/c2 地址算术未动，F15-07/08）。
     **d7=False 实证**（F15-01 预测形：软脊走完 → proj-infer 消费链 →
     IP_PEEL/PI_LVL 失败 → A=0 → PI_TY ST_SP decline → 卡对链），软脊正确
     并保留。**d6 残环根因钉死且不在软脊**（F15-08，p9b 600 步全程
     trace）：软走层每次尝试 2-4 步干净终止；环=卡对链对 go-pair 实参的
     比较——两侧 go 同常量同 major，但实参**同一 pos 不同 env 根**
     （d6r 原建 go vs d6l delta 展开重建的 go，B=3197 vs 3239），refl
     快道不可用 → DEFEQ 内部 WHNF 展开 below 族（每圈新 PProd/bvar
     位置）→ 反复 PI_T 尝试结构逐轮加深。内核对同一对 True 的路径从不
     展开 below：brecOn @[reducible] 先展开、两侧同成 `Proj(go tq F1s,1)`
     后子脊比对即收（真 lean `#print Nat.brecOn/go` 原文，F15-08）。
     三次尝试（F13-02/F14 fix2/F15 fix3）均未闭合，裁决 3 禁第 4 次 →
     d6 进 `KNOWN_GAPS` 注册表（`[XFAIL-KNOWN-GAP]` 不计 divergence、
     `[XPASS]` 反而 FAIL），全面定谳见 **ADR 018**
     （docs/decisions/018-soft-infer-spine-and-d6-known-gap.md），后续
     出路=ADR 017 缓存层（内核 defeq failure cache 同机制，
     `K/type_checker.cpp:953/972/1042/1251`）。
- **kernel 引用（F15 增补）**：`K/type_checker.cpp:189-205`（infer_only
  脊，修③依据）。

### F5-c2 备忘录（缺口 #4：pair/通用载体链不收敛——与 #2b 定案分家）——F13-04 补 F9→F10 材料链收口

- **定案**：坏数据时代混着的"no halt"有两种机制——
  (甲) 伪不收敛：probe3 `_pprod` 的 casesOn **顺序+level 双错**导致
  ENV 含内核永不接受的无效形，机器反复重推同一 stuck 形（F4 (a2) 的
  CYCLE `focus=Const Nat`、流 1 token/步 = 签名）——数据修（norm2）后
  **Nat 载体消失**（d3/d4 转为有终局的快速错判=#2b）；
  (乙) 真不收敛：norm2 env 下 **lst eL1/eL2 仍 no halt@600**（b04 复钉，
  与坏数据无关）。
- **(乙) 收口材料链（F9→F10，两任执行完毕）**：
  - F9-03/04（f9_p7 全 trace + eL1 判读）：et_sfall 修后 eL1 真机 174 步
    自然 halt（非 no-halt，lst 形态改判）；停滞点钉死在 whnf 交付部分应用
    lam（焦点 1259@2853）；次级毁伤=tests `_spec` 折级造 x-pi 域比较
    Sort1 vs Sort0 假 False。
  - F10-01/02：lst 第二层根因=通用 OP_IOTA build 环不喂 extras
    （丢应用点），修复落码。
  - F10-04：spec1+splice 下 lst 4/4 对 oracle 全绿；spec0 臂裁决改独立
    进程，裁决规则（F10-04 已批）由 F11 执行=回退 `_spec`，零扰动实证=
    四绿例步数逐一相同（135/133/172/484，f11_p5）。
  - 现行状态：**C 组 lst 4/4 绿**（f11_p1_full）；(乙) 缺口关闭。
- **反模式警告（保留，本卡 009 现行约束）**：不许用"提高 max_steps 直到
  halt"或软旗放宽来治不收敛——把不收敛藏进预算。F13-02 对 d6 修②的
  失败（软 INFER 跳过既破 d7 下降又未收 d6）与 F13-03 抬帽的红线约束
  （新 Timeout 例须合法慢证据）均沿用此条。
- **F15 收口注（2026-09-16）**：本警告在收口时的正反两用——
  (正) d4 抬帽 600→720 按 F13-03 路线执行：合法慢证据=F8-02 线性步数表
  （引擎侧无此帽可完成，Python 侧只是墙钟预算），裁决 4 无条件批准落码
  （tests 第 64-67 行）。
  (反) d6 **没有**靠抬帽解决：720 步仍 Timeout，且环是结构逐轮加深的
  增长环（非合法慢），抬帽只会把预算烧穿——最终按裁决 3 停手为
  KNOWN-GAP（ADR 018），帽只服务 d4。

### F6 任务书（范围=卡 009 原题"与真内核一致"，不扩）
1. 读 f5_d_endgame2.log 尾段 + /tmp/probe009F/f5norm.py，复现最小 trace；在
   `lean_vm/build_vm.py` 的 DEFEQ 下降分支定位"V2=0 空操作数帧"的生成点
   （发射丢字段还是 link 回收丢字段），语义决策带 kernel 引用。
2. 最小修复 → D3/D4（Nat）、D6、eL3/eL2（lst）全钉绿；若牵出交付合同级变更，
   停手写 ADR 草案等总控裁。
3. d：建 `tests/test_brec_drec_iota_vs_lean.py`——把 f5norm 管线收编成测试内
   函数、全钉绿用例 + G3 三例回归位；期望值现跑 oracle，不预置答案。
4. c1/c2 备忘录补完落 005（c1 素材已在 b03；c2 判 lst 是否同根）；
   #1 ADR016 草案（只写不实现）。
5. v：图有改动 → `python3 -c "import lean_vm.build_vm"` →
   `python3 -u model/compile_vm.py --sparse model/step_vm_009_scratch`（基线
   24914/2878/186892 nnz）→ `SBIN=... python3 -u scripts/verify_engine_vs_refvm.py`
   34/34 不退 → 20 套件（REGRESSION_CORES=0-5）+ 新差分单跑注明。

机器纪律：核 0-5、OMP=3；长任务首选 `scripts/run_mem_guarded.py --max-rss-mb
4096 -- <cmd>`（AGENTS 新条款，勿再在 /tmp 造看门狗）或
`systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=4G`；watchdog 锁
真 PID（F5 b01 又盯错一次：`setsid nohup env` 形态下 `$!` 是外壳）。
≤10min 一条落 005，第一动作=F6 段表头。lake/Mathlib 已完工（olean 在
/home/xkq/mathlib_src，只读），核 14-19 已空但 F6 仍锁 0-5。所有权/禁改清单
照 F1 简报原样（build_vm.py 属你；engine/compiler/model/ref_vm/step_driver/
scripts/README/ARCHITECTURE 禁改）。

---

## F6 段（执行记录，2026-09-16 05:5x 派发，从盘上记录续跑）

F6 = 卡 009 第五任执行者。继承 F5 结论：norm2 数据管线判正（RefVM 7/7 与
oracle 一致），残余 = build_vm.py DEFEQ 下降分支判决交付 bug（端局 trace
`f5_d_endgame2.log` i=593 弹出畸形 `TDEFEQ(V1=3006,V2=0,X=0,E2=3007,F2=0)`）。
核 0-5，OMP=3，日志 $HOME/logs/009F/（f6_ 前缀），长任务走
scripts/run_mem_guarded.py 或 systemd-run cgroup，watchdog 锁真 PID。

| 子任务 | 内容 | 状态 |
|---|---|---|
| 1 | 复现最小 trace；build_vm.py DEFEQ 下降分支定位 V2=0 空操作数帧生成点（发射丢字段 vs link 回收丢字段）；语义决策带 kernel 文件:行 | in_progress |
| 2 | 最小修复 → D3/D4（Nat）、D6、eL3/eL2（lst）全钉绿（oracle 现跑判期望）；若牵出交付合同级变更停手写 ADR 等裁 | pending |
| 3 | d：建 tests/test_brec_drec_iota_vs_lean.py（f5norm 管线收编为测试内函数 + 全钉绿用例 + G3 三例回归位；期望 oracle 现跑） | pending |
| 4a | c1 备忘录补完落本文件（缺口 #3 D6 素材已在 F5-b03） | pending |
| 4b | c2 备忘录补完落本文件（判 lst 是否同根；收编遗腹探针 f5_c_lst2.log pid 911938） | pending |
| 4c | #1 ADR016 草案 docs/decisions/016-*.md（只写不实现，素材=F2 G1 行 + F4 载体推广） | pending |
| 5 | v：import 检查 → scratch --sparse 编译（基线 24914/2878/186892）→ 引擎对拍 34/34 → 20 套件回归 + 新差分单跑注明 | pending |

### 事故记录 7：F6 阵亡（2026-09-16 ~05:49 后，总控 06:1x 定案）与资产收编

**定案依据**：末次盘上活动 05:49（f5_test2.log 收尾），005 末次落盘 05:44 段表头，
静默 25min 破 10min 节拍；核 0-5 无任何工作进程；用户侧界面显示其最后一条只读
grep/sed 命令"执行失败"后会话不再动。死因按 F5 同口径：**未定案**（无客户端重启、
无 OOM 痕迹，`database is locked` 复发为头号嫌疑但无日志实锤）。若 F6 复苏再写盘，
立即停手让位 F7，其增量以 git diff 收编。

**F6 实际完成度（表头未及更新，总控按盘上证据重记）**：
- 步骤 1 **完成**：端局复现已固化，7 分歧基线 =
  `f5_test2.log`（445s）：A 段 normalizer 不变量 **OK**；B nat 组
  G2_d3/G2_d4/G4_d6 graph=False vs oracle=True，G3 三例+G4_d7 绿；
  C lst 组 eL1/eL2/eL3/eL3_neg 全部 600 步不收敛。
- 步骤 3 **基本完成**：`tests/test_brec_drec_iota_vs_lean.py`（05:41，15997B）
  已入仓库，头注含 gap 归属与 kernel 引用，A/B/C 分区 + 期望现跑 oracle。
  修绿后只需把 B/C 断言并入回归表（当前它不进 20 套件表）。
- 步骤 2 定位线索（其遗孤 trace）：`/tmp/probe009F/f6_e1_trace7.py`（05:44）
  起跑即死于解释器问题，见下条陷阱。
- 步骤 4a/4b/4c/5 未动。build_vm.py **无改动**（09-15 mtime 已核）。

**新增机器陷阱（F7 起全体遵守）**：系统 `python3`（/usr/bin、/bin）**没有
numpy**，F6 e1 经 `scripts/run_mem_guarded.py` 起探针时子进程继承 shell PATH，
解析到 /usr/bin/python3 → `ModuleNotFoundError: numpy`（alm_p2.py:32 即死）。
历次成功探针用的是 `/home/xkq/miniconda3/envs/train/bin/python`
（numpy 2.5.2 + torch 在位；只读该 env 文件，与运行中的训练进程无关）。
**一切 python 调用写死全路径或用该 env 的 python**，不许裸 `python3`。

---

## F7 任务书（总控 → 第七任，2026-09-16 06:2x）

F7 = 卡 009 第六任执行者。F6 资产已全部在盘（上条定案），**不许重造**：
测试文件、复现基线、/tmp/probe009F 全套探针直接续用。

1. 第一动作：本文件追加"F7 段"表头（≤10min 节拍起点）。开工自检：
   `python=/home/xkq/miniconda3/envs/train/bin/python` 跑
   `$PY -c "import numpy;import lean_vm.build_vm"`（cwd=仓库根）。
2. 主线（F6 步骤 2）：build_vm.py DEFEQ 下降分支定位畸形帧
   `TDEFEQ(V1=3006,V2=0,X=0,E2=3007,F2=0)` 的生成点（发射丢字段 vs link
   回收丢字段，对照 K/inductive.cpp / infer_eq 侧内核引用）。最小修复后
   `$PY -u tests/test_brec_drec_iota_vs_lean.py` 必须从 7 分歧走向 B 组
   3 例 + C 组 4 例全绿（期望由 oracle 现跑，不许改判据迁就图）。
   注意测试头注归因：D3/D4=缺口 #2b（下降多比了一对
   `UnitT =?= Nat`）、D6=缺口 #3（stuck Proj restick）、lst=不收敛，
   三种机制**先证是否同根再一起修**，不同根就分开钉。
3. 备忘录 c1/c2 + ADR016 草案（照 F6 表 4a/4b/4c 原文执行，c2 素材：
   f5_c_lst2.log 超时机制 vs Nat 快速 False）。
4. v 收口（照 F6 表步骤 5）；新差分测试若在修绿后耗时 <600s，评估是否列入
   20 套件表（列表属 scripts/run_cpu_regression.sh 禁改名单之外——它归你，
   列入需在 v 段写明理由）。
5. 停手条件：合同级变更（TASK_WHNF 交付形态、ENV 格式）→ 写 ADR 草案到
   docs/decisions/ 并停在 005 报总控；同一错误第 2 次修不好 → 落证据等裁。
6. 机器纪律照 F6 简报段原样（核 0-5、OMP=3、run_mem_guarded 或 cgroup、
   watchdog 锁真 PID、pkill 先 pgrep -af），外加解释器全路径条款（事故记录 7）。

---

## F7 段（执行记录，2026-09-16 06:1x 派发，从盘上记录续跑）

F7 = 卡 009 第六任执行者。继承 F6 定案（资产全在盘：测试文件、norm2 管线、
f5_d_endgame2.log 端局 trace、7 分歧基线 f5_test2.log）。解释器铁律：
PY=/home/xkq/miniconda3/envs/train/bin/python（系统 python3 无 numpy）。
核 0-5，OMP=3，日志 $HOME/logs/009F/（f7_ 前缀），长任务走
scripts/run_mem_guarded.py --max-rss-mb 4096 -- $PY …。本段表头即第一动作。

| 子任务 | 内容 | 状态 |
|---|---|---|
| 0 | 自检：$PY -c "import lean_vm.build_vm"（cwd=仓库根） | in_progress |
| 1 | 定位畸形帧 TDEFEQ(V1=…,V2=0,…空第二操作数) 生成点：发射丢字段 vs link 回收丢字段（f5_d_endgame2.log i=593-596；kernel 引用） | pending |
| 2 | 三机制同根性探针（#2b UnitT=?=Nat / #3 stuck Proj restick / lst 不收敛）→ 最小修复 → 测试 B/C 全绿（7→0） | pending |
| 3 | 修绿复跑 $PY -u tests/test_brec_drec_iota_vs_lean.py 原文尾行落本段 | pending |
| 4a | c1 备忘录（缺口 #3）补完落本文件 | pending |
| 4b | c2 备忘录（lst 是否同根；素材 f5_c_lst2.log）补完落本文件 | pending |
| 4c | ADR016 草案 docs/decisions/016-*.md（TASK_WHNF proj 交付合同，只写不实现；F5 已落草案则核对补完） | pending |
| 5 | v 收口：scratch --sparse 编译报增量 → 引擎对拍 34/34 → 20 套件回归（REGRESSION_CORES=0-5）→ 新差分列入评估 | pending |

### F7-01（06:3x）"畸形帧"定性更正：3008 是驱动器种子根帧，非丢字段帧；真端局=软 whnf 恒等返回 raw field

- 复核 f5_d_endgame2.log + /tmp/probe009F/f5_d_trace6.py 种子代码：
  `fpos = drv._append(T_FRAME, V0=7, V1=tp, X=0, E2=sp, F=0)`（V2 默认 0）。
  nat 组 ENV 前导约 3000 token，tp/sp/根帧恰好落在 3006/3007/3008。
  **TDEFEQ(V1=3006,V2=0,X=0,E2=3007,F2=0) = 根帧本身（V2=0 合法，X/F2=0
  顶层空 env）**。"发射丢字段 vs link 回收丢字段"两问均不成立——不是生成点
  bug，F5/F6 的"判决交付畸形帧"框架被证伪（记录于此，防后人再查）。
- 真端局（i=591-596）：3852 ST(UL_W) 失败 → verdict False 沿 TASK 弹出协议
  （E=1 时 DEFEQ/WHNF 帧逐步 pop 转发）经 3123 → 3008 → 停机判 False。
  UL 链比较 (397=?=301)（=F5 记的 UnitT-vs-Nat 臂）只是**下游症状**。
- 上游真机制（D3，端局 i=415-428 证据）：帧 3123 = D_SW3 sw_loop 再分发对
  (nt=2144, ns=2553)，nt = raw field 形 `F2s (succ (pred 2)) (shadow)`。
  软 whnf(2144) **恒等返回**（SA==ooV1、SB==ooX → sw_stuck → PI 链 → UL
  → False）。主模式 const_delta 若命中 F2s 应一路 delta→match_1→P2.casesOn
  iota→Nat.add→lit。恒等返回说明 whnf 停在 §10.2 spine-root 交付（头未 delta）。
  候选根因：(a) ENV_HDR(F2s).V2=0（值未进 ENV，def 被当 opaque）→ 数据侧；
  (b) I_PROJ→TASK_WHNF 的 E=1 合同（build_vm.py:4609-4617 自注"load-bearing
  for D_SW2/D_SW3"）把 raw field 当 FINAL 交付、主模式续推没发生。
  探针 f7_p1（trace6 复刻 + 端局解码 2144/2553/3006/3007 + ENV_HDR dump）在跑。
- 内核基准钉好：whnf_core Proj 分支续归约 field（type_checker.cpp:501-506
  `r = whnf_core(*m,...)`）；whnf 循环对 field 继续 unfold_definition
  （:759-767）；is_def_eq_core 的 lazy_delta 对单侧 delta 头 unfold
  （:1013-1020），raw field 头（值 const）在 is_def_eq 通道**必然**被续展开。
  ref_vm.py:281-296（K_PROJ continue，注释明说 returning raw would end whnf
  in a non-normal form）与内核一致；图在 DEFEQ 软 whnf 通道违背两者。

### F7-02（06:5x）同根性定位完成：I_PROJ 对 TASK_WHNF 调用者停发 E=1（build_vm.py:4630-4639 pr_arg_target 不含 TASK_WHNF）

- f7_p1_whnf.py（日志 f7_p1.log，60s）：
  - 端局对确认：子 DEFEQ 帧 3123 动态重找到 t=(2144,3108)=
    `F2s (succ (pred 2)) (Nat.below 影子 Nat.rec…)`、s=(2553,0)=LitNat 3。
  - 在该 t 操作数上直接种子 TASK_WHNF(E2=0 硬)：**不恒等**、且 400 步未停机
    （流暴涨）——主模式对 raw field 是能下推的（F2s cid=40 T_ENV.V2=866 有值，
    f7_p0_static.log 证数据侧无罪）。
  - 但 DEFEQ 通道里软 whnf(2144) **恒等**（sw_stuck 触发进 PI 链，端局
    TINFER(2144)@3853 为证）。两者差异 = 软 whnf 从 d3 根出发：
    whnf(d3)→delta brecOn→Proj(0, go…)→proj_setup whnf 子→Nat.rec iota→
    P2.mk→I_PROJ 取 field→**field 可约(App)、调用者是 deq_sw0 推的
    TASK_WHNF(E2=1)→ pr_arg_target(NAT+ST) 不含 WHNF → E=1 FINAL 交付**
    → d3 的 whnf 在 raw field 处终止（§10.2 spine-root 惯例让后续软 whnf(2144)
    内部对 below 投影同点停住、整体回退成恒等假象）→ sw_stuck → PI 链 →
    UL 型比较(397 vs 301) → 快速 False。**这就是 #2b 的生成点**，不是帧生成 bug。
- 内核/参照机基准：K/type_checker.cpp:501-506（whnf_core 的 Proj 分支
  `r = whnf_core(*m,...)` 对 field 续归约）+ :759-767（whnf 循环对
  投影后的 field 头继续 unfold_definition）；ref_vm.py:281-296 K_PROJ
  `continue`（注释明言 returning raw would end whnf in a non-normal form）。
  图 build_vm.py:4609-4617 的 P7.5c-2 注释"ref contract proj ends whnf
  对 D_SW2/D_SW3 load-bearing"与 ref_vm 源码矛盾（F7 更正：ref 契约是
  续 whnf；stuck field(pr_full=0) 的 E=1 restick 才是 load-bearing）。
- 修法（最小）：pr_arg_target 加 TASK_WHNF（即 pr_full∧pr_f_red 时
  对任何调用者都 E=0 续推，主模式会自然停在真 stuck 头经 whnf_deliver 交付
  E=1）。D6 走 pr_full=0 restick 臂，不受影响——若修后 D6 仍 False，
  即证 #3 与 #2b/lst **不同根**，分开钉。

### F7-03（06:59）fix 第 1 次尝试结果落档：修 I_PROJ 的 pr_full=1∧pr_f_red=1 后 B 组 d3/d4 仍 False、C 组 lst 仍 no-halt（同根性=未证实）

- 改动（第 1 次）：build_vm.py I_PROJ 交付 E_c 选择（:4645-4650）——
  删 pr_arg_target（只认 NAT/ST 调用者），改为：pr_pend≥1→E=0 续；
  pr_pend=0∧pr_full∧pr_f_red→E=0 续（即对任何调用者、可约 field 一律续推）；
  pr_pend=0∧pr_full∧¬pr_f_red→E=1 stuck 交付；pr_pend=0∧¬pr_full→E=1 restick。
  依据 K/type_checker.cpp:501-506/:759-767 + ref_vm.py:281-296（已钉 F7-02）。
- 全量差分 f7_test1（run_mem_guarded 4096，wall 412.5s peak 3749MB rc=1）：
  A 组 OK；B：G3 三例全 PASS（d1_3 True/d1_4 False/d1_shadow True）、
  **G2_d3 FAIL False、G2_d4 FAIL False、G4_d6 FAIL False、G4_d7 PASS False**；
  C：G5_eL1/eL2/eL3/eL3_neg 全 FAIL no-halt@600。**与基线 7 分歧逐条同形**——
  即修后 d3/d4 的 False 判决**生成点没变**：要么软 whnf 的恒等停在别的投递门
  （§10.2 spine-root/soft-fallback wf 在 build_vm.py:1298-1303 一带），
  要么 I_PROJ pr_full 根本没在该路径触发。p1 的"恒等=根 proj E=1 停发"推断
  被本实验证伪（至少不完整）——教训：静态推断投递门≠实证。
- 同根判定（对任务书"三机制是否同根"）：lst 4 例与 d3/d4 同形（no-halt/False
  均在软 whnf raw field 通道）、d6 走 pr_full=0 restick 臂——**三机制共享
  raw field 通道但止于不同门**的假设仍开放，需修后 d3 的新端局定位。
- 下一步（第 2 次修复的依据）：f7_p2_trace（trace6 复刻、i>=120 全打、620 步）
  看修后 d3 端局落在哪个位置/哪条交付臂；证据落档后才动第 2 次修复；
  第 2 次修不好→按停手条件把已试方案+错误原文落本段等裁。

### F7-04（07:15）修后 d3 端局重锤（f7_p2/f7_p3，各 ~120s）：算术全部完成，但软 WHNF 帧仍把"原始闭包"当 FINAL 弹出——身份发生在最后一步的 soft 回退，不在 I_PROJ

- f7_p2/p3 = trace6 复刻（修后 build_vm、种子根 DEFEQ 3008=(d3 3006, e3 3007)）。
  p2 日志 f7_p2.log、p3 全步逐行日志 f7_p3.log（窗口判读 i=440-517）。
- 新事实（p3，i=440-495）：修后软 whnf **确实下推到 F2s 内层**：match beta、
  pred 2→1（i=483-488）、ih+2 加法 NAT 数字循环（i=489-495 X=76）全部执行，
  i=495 焦点=最终字面量 token(3946)。**i=496：焦点突变为 (3006,0)=Const d3 原物、
  E=1、栈顶=ST(D_SW2)** ——即根软 WHNF 帧（3490 TWHNF(V1=3006,E2=1)）在
  算术已成功的最后一步仍把"帧原始操作数"作 FINAL 交付 → sw_stuck → PI 链
  (PI_TY 3967→PI_LVL 3971) → UL 链 (UL_T 3985→UL_W 3989) → False 沿
  3487(子 DEFEQ，其 t 侧 V1=3006 **第一轮就已交付原物**) → 3008 弹出停机。
- 机制收窄：不是 I_PROJ 停发（尝试 1 修的就是那里，改后下推明显变深、
  时间 450→412s 但端局同形）。候选 = 图内**唯一两处"交付 nbV1(帧原物)+E=1"**：
  WALK 溢出 wf_soft（:1296-1303、:1329-1350）与 §10.2 spine-root
  ms_sp_whnf（:1327-1328）。i=495→496 一步内焦点从 lit 变 nbV1、且栈从
  ST'(3903) 弹到 3489——中间必经一次 WALK 解析（beta 体内 bvar 走 env 链）。
  **下一步（f7_p4）**：修探针 frames() 的调用者链（此前误沿 X 字段、应为 V2=t[3]），
  窗口 i=380-500 全栈打印，钉死 overflow 的那一步：哪个 WALK 帧、frX(目标深度)、
  停在哪个 LINK/NULL——据此判 env 链是谁构造错的（不是放宽验收，是数据构造 bug）。
- 同根性更新：D3/D4（本轮证据）= 最后一步 soft 回退交付原物；lst 4 例 no-halt
  与 d6 仍待各跑一遍同形判定。尝试 1（I_PROJ）保留在树上：它让软通道下推到
  内核语义深度（对齐 K:501-506/ref_vm K_PROJ continue），其回归面 v 收口时判定。

### F7-05（07:33）端局门钉死 = natbad2→nat_soft（build_vm.py:5410-5451）；ST'.V1 的 arg1"结果"是 F2s 自身 value-lam（865），微探针证明纯 Nat.add 通道无恙

- p4（f7_p4.log，调用者链修正后）i=495→496 精确匹配 nat_soft 臂：
  D=ST'(3903: V1=**865**,X=3901,V2=3904) ∧ focus=lit(3946) ∧ nb=NAT(3904:
  V1=3=OP_ADD,X=2) → **d23 触发** → valid1 = fields(865) 非 LIT/零 ctor → 0 →
  **natbad2**（:5418）→ wpos=nbV2=3490（根软 WHNF,E2=1）→ **nat_soft**（:5450）
  → 交付 (wV1,wX,E)=(3006,0,1) = 帧原物 → sw_stuck → PI/UL → False。
  内核基准：真内核在 is_def_eq 的 whnf 里 **不会**出现"add 参数是 lam"——
  该项在源头就不是 Nat 表达式；图在 arg1 的 whnf 把 `ih` 解析成 **F2s 自己的
  value 闭包**（f7_p0：F2s cid=40 V2=866；865-868=其 value 的 Lam 链，
  i=466-468 焦点 867→866→865 正是沿 env-LINK 走到 value-lam 后
  "lam_done 即 complete"），把裸 Lam 当 arg1 的归约结果存进 d12 的 ST'.V1
  （:2902 frame_V1←v_done）。**根因 = brecOn/match 层构造的 env 里
  `ih` 的链接值指错（自指 F2s value-lam），非 nat_soft 交付臂本身。**
- 微探针 f7_p5（同 norm2 环境，直接 seed DEFEQ）：
  m0 `3=3`→1；m2 `add 1 2=?=3`→1；m3 `add 2 2=?=4`→1；
  m1 `add (pred 2) 2=?=3`→1；m4 `add (add 1 2) 2=?=5`→1（m5/m6 在跑）。
  → 纯 Nat.add/nat-compute 通道完好；错链只在 F2s(iota+match+投影) 复合层出现。
- 下一步：f7_p6（读 em_link*/frame* 每步输出，窗口 430-500）钉"哪一步发射了
  link_V0=865"——即 ih 自指链的生成点；据此做尝试 2（生成点最小修）。

### F7-06 07:46 f7_p6 发射窗判读（d3 修后，步 430-500 全量）
- 端局逐帧钉死（f7_p6.log，wall 121.5s peak 3407MB rc=0）：
  - i=443-447：WALK 帧沿 env 链 3846→3844→3717→3715→3633（X=4→0），
    **i=448 解析 `ih`：link@3633 的 V0=867 = F2s value-lam 自身**（闭包 env=3612），
    随后 i=449-452 焦点 867→866→865→856 一路 lam 下钻到 body
    `App(App(Nat.add, ih…), k+1)`。i=455-495 内层 k+1/pred 侧**算对了**
    （i=497 dec=LitNat 3 @2553）。
  - i=469：d12 把 ST'.V1=v_done=865（裸 LAM）塞进 NAT 控制帧；
    i=496：d23 读 frV1=865 → valid1 失败（tK=LAM≠LIT/CONST-nullary）→
    natbad2 → wpos=nbV2=soft WHNF 帧 3490 → **nat_soft 交付原始操作数
    (3006,0,E=1)**（= DEFEQ t 侧闭包本身，恒等复位）→ i=497-500
    PI_T/PI_TY/INFER(3006)… → i=517 done verdict=False。
  - 同一坏链在 i=466-468 第二次出现（外层 add 的两次 arg1 walk 同源）。
- 结论修正：i=466 处 tok(867) 不是"自指 LINK"，而是 **link@3633 的值域
  直接写了 867（F2s 的 value 闭包根）**。坏数据 = 3633（及 3612/3715/3717
  链段）由 **步 430 之前** 的某次发射产生（b.stream 位置单调递增可二分定位）。
- 下一步 f7_p7：全程 620 步跟踪 `len(b.stream)` 增删，命中监控位
  {3612,3633,3708,3715,3717} 的那一步打印发射时完整 dbg+帧 payload+前态焦点
  decode，钉"哪条分支（fire2/d12/cs/p2/beta）写出 link_V0=867"→ 生成点最小修。

### F7-07 07:54 f7_p7 写入器定位（07:47 起，wall 112.9s peak 3407MB rc=0）
- 监控位写入步全部钉住：3612←步316、**3633←步326**、3708←步367、
  3715←步371、3717←步372、3844/3846←步439/440、3865/3867/3869←步450-452。
- 坏链现场：appended[3633] = (31, 867, 4, 3631, 3612)（LINK V0=867 depth4）。
  发射步 324-326 连续三次主模式 em_link（dbg_main=1）：V0=812/828/867，
  focus 1154→1153→1152（递减）——**在剥 F2s.match_1 展开后的
  casesOn 四参 spine（静态 token 1147-1155）**，每次 beta 把 LAM 的
  arg 位置记进 link。arg@1152 的 V0=867 = F2s value 的第三层 LAM 根。
- 静态区判读（f7_p8 在跑）：865/866/867 都是 LAM（dom=853/831/830），
  864=APP(856,863)、868=APP(829,867)。**疑似真根因 = pV0/link_V0 语义：
  beta 绑参时把"参数的 V0 字段"当参数本体写入 link，而应写参数的位置**。
  （对照：步 315 link@3612 V0=2143=pend 头位置——那是正确形状；步 324-326
  的 V0=812/828/867 若是"arg 的 V0"则为指针丢失一级。）
- 待 p8 静态 dump 判 1152 的确切 kind/V0 后定夺尝试 2 的落点（:1282
  link_V0 = pV0 与 pV0 的定义链）。未改任何代码。

### F7-08 08:05 p8/p9 静态判读：坏链 3633 语义 = match_1 binder-e（合法！）
- p8（静态 env dump，rc=0 wall 1.5s）：F2s vpos=870 = `fun n x =>
  App(App(App(App(App(match_1,808),BVar1),BVar0),828),867)`；
  match_1 vpos=1157 = 5-LAM 链，体 1152 = casesOn spine，1144 =
  `App(App(App(BVar4,BVar3),BVar1),BVar0)`；867 = cons handler
  `fun u v w => add(BVar1, …BVar2…)`；828 = nil handler。
  2138=(1,2,0,…)=BVar2、2144=App(App(BVar2@2138, App(cid5,BVar1)),BVar0)
  是 **brecOn(.go) 骨架的静态 token**（骨架 f n ih 应用体）。
- p9（全 append 流，wall 125.5s rc=0）：步 316 pend=867→步 326 beta 链
  d2=812(BVar0)/d3=828/d4=867 **全部合法**（brecOn 骨架把 F2s 拆成
  match_1 五参 spine，e-binder=cons handler 867）。
- 真正的错位端局（p6+p9 对齐）：步 437-439 lam@1146/lam@1145（match_1
  体内 cast/motive 臂）分别以 **2144/2146（brecOn 骨架 token）** 为参数做
  beta，link_env 记 **3717（match_1 链）**；步 449-452 e=867 三参 beta 后
  add arg1 `ih`→BVar1@3846→d7@3844=**2144 env 3717**；步 461-466 whnf
  2144 时其 BVar2（骨架 f 槽）在 env 3717 里 2-hop 解析到 d4=867，
  沿 867→866→865 lam 链止步（**骨架 token 配了 caller 环境**）。
- 疑点收敛到步 433-436 的 RAW 发射区（动态 spine 3835/3837 构造处，
  2144 首次带 env 3717 进 pend）：f7_p10 窗口 425-442 全 token dump。

### F7-09 (08:26) p10 读出 = 根因钉死 + 尝试2 设计（直发方案）
- p10（窗口 425-442 全 token dump）钉死生成点：步 432 p2_succ_r 改推
  X=2 build 帧 @3833（E2=3835 base，F2=3723 旧 t-entry 链）；步 433-435
  RAW 两步在 frE2 造平铺 `App(App(1146,2144),2146)` 并以 **B=p2_altX=3717**
  交付（@3835 APP(1146,2144)、@3837 APP(3835,2146)，post st=(3837,3717)）。
- 字段 2144/2146 是 brecOn go 骨架静态 token，binder 空间 = major whnf 的
  环境；步 430/431 peel 已在 C 链上留下**新鲜字段 pend 条目 @3831=(30,2144,
  prev=3829,X=3827)、@3829=(30,2146,prev=0,X=3827)**（3827 = 交付时 SB =
  major 自身环境，天然忠实）。旧 C:=p2_extras(=0) 把这些条目丢弃，平铺 APP
  在 alt 环境 3717 下重 peel → beta link env=3717（:1285 link_env=pX）→
  ih=BVar1@1144 解析成 2144@3717 → 骨架 BVar2 在 3717 链 2-hop 撞 d4=867
  （match_1 cons-handler），算术失败→nat_soft 恒等→PI_T/PI_TY 比对 False。
  即 :2871-2875 注释的"fields are literals(env-free)"假设在 go 结果作
  major 时破裂。**d3/d4 同根确认；c2 预判：d6/lst 的 major 若同样是
  brecOn 见证对 P2.mk(带 loose bvars) 即同根。**
- 正确语义 = 内核 iota：字段原样应用到 minor.rhs，extras 尾随
  （/home/xkq/lean4/src/kernel/inductive.h:112-118）。机器里等价物 =
  Bool.casesOn 的 0-field 直发形状（A_false_bool = minor@X+extras+pop）。
- 尝试2（本根因第 1 次修复；attempt-1 I_PROJ 属另一根因）：p2_succ_r
  改直发 `A:=p2_altV0, B:=p2_altX, C:=SC(新鲜字段链,extras 已在其尾),
  D:=frV2, E:=0, F:=SF`；em_frame(:6053) 移除 p2_succ_r（不推 X=2 帧 →
  is_cs_build_p2 恒 0，旧 build loop 变死代码，注释改写点明 unreachable）；
  frame_V1/V2/X 的 p2_succ_r 臂留为 dead（em_frame=0 时不被读）。
- beta 走主模式 :1257-1285：link_env=pX=3827 ✓✓（字段捕获环境由条目自带），
  prev=SB=3717 ✓（alt 自家链）→ 1144 处 BVar4→3633=867 consC ✓、
  BVar1→link_a=2144@3827 ✓ → 递归 f(succ n) 正常 whnf 出字面量。
- 下一步：改码 → 全量差分（守卫，~450s）→ 若 B 组 7→0/部分，按 c2 查 lst。

### F7-10 (08:30) 尝试2 已改码并起全量差分 f7_test2
- build_vm.py 改动（仅声明内文件）：
  1) :1488-1497 p2_succ_r 交付线改直发 `A,B,C,D,E,F = p2_altV0, p2_altX, SC,
     frV2, 0, SF`（原 A=SA/B=0/C=p2_extras/D=c1+推 X=2 帧）。
  2) :6050 em_frame 去掉 `+ p2_succ_r`（不再推 build 帧）。
  3) :620-624 / :2870-2876 注释改写：is_cs_build_p2 标注 unreachable，
     平铺 APP 丢字段捕获环境的坑记录在案（线保留，图稳定）。
- 引据：K/inductive.h:112-118（iota 把 ctor 字段原样 mk_app 到 minor.rhs，
  extras 尾随）+ 机器主模式 beta :1285 link_env=pX（pend 条目自带环境）。
- f7_test2 起法：guarded（run_mem_guarded 4096，taskset 0-5，OMP=3），
  pid 1124934/子 1124935，日志 ~/logs/009F/f7_test2.log。08:31 进 B 组，
  子 RSS 2.66GB（< 基线峰值口径，护栏盯）。预计 ~450s。

### F7-11 (08:48) f7_test2 判读：7→6 分歧，d3 转 PASS
- 原文：`=== brecOn/drecOn faithful iota vs lean: FAIL (6 divergences) 445s ===`
  `[mem-guard] wall 445.2s peak RSS 3749MB rc=1`
- 变化：B G2_d3 **PASS**（直发生效，True=oracle）；B G2_d4 由 False→
  `no halt after 600 steps`（解析已能推进，疑为更深递归步数超预算，待证
  不是环）；B G4_d6 仍 False（异根，c1 单独钉）；C lst 4 例仍 no-halt
  （**c2 判：非同根**——Lst.below 见证非 P2，走 WP5 通用 iota 通道，
  gi_pend_env 本就按条目带环境；no-halt 形态未变 = 另案，探针见 F7-12）。
- 下一步：f7_p11 探 d4（预算抬到 4000：判单调推进 vs 状态环，尾窗 dump）
  + eL1（同法，nil 案例都不收敛 → 疑似 ping-pong）；d6 单独尾窗探针。
  若 d4/eL* 为合法慢：tests 内 600 预算属 harness 资源帽（非期望值），
  抬预算须带"步数≈线性于递归深度"的证据并落 005/ADR，不许裸放宽。

### 事故记录 8：F7 阵亡（database is locked **实锤**）与资产收编

**死因首次定案**：harness 后台任务终止通知的错误原文即 `database is locked`
（非推测）。F7 寿命 06:18→~08:40（2h22m），节拍 F7-01…F7-11 共 11 条，
全链最长寿也最富有的一任。至此该病因由"头号嫌疑"升格为**已证**：客户端层
慢性病，SQLite 会话库写锁把长寿代理逐个处死（F1/F4/F5/F6 推定同因）。
缓解手段被证明有效：**≤10min 小步落盘，F7 净损失仅末条之后几分钟**。
总控已向人申报此环境事实；策略不变（死→收资产→换任）。若 F7 复苏写盘，
立即让位 F8，增量以 git diff 收编。

**F7 资产账（全在盘，F8 不许重造）**：
- 根因钉死（F7-09）：p2_succ_r 平铺 APP 在 alt 环境（3717）重 peel，丢 go
  骨架字段捕获环境（BVar1@1144→2144@3717 错解 → 骨架 BVar2 在 3717 链
  2-hop 撞 d4=867）。:2871-2875 "fields are literals(env-free)" 假设在
  go 结果作 major 时破裂。
- 尝试2 已入码 build_vm.py（:1488-1497 直发 A,B,C,D,E,F=p2_altV0,p2_altX,SC,
  frV2,0,SF；:6050 em_frame 去 p2_succ_r；:620/:2870 注释 + unreachable 标注），
  引据 K/inductive.h:112-118 + 主模式 beta :1285 link_env=pX。
- 判据（f7_test2.log 原文在册）：**7→6 分歧，445s，peak RSS 3749MB**：
  G2_d3 PASS；d4 False→no-halt；d6 仍 False（异根）；lst 4 例 no-halt 不变
  （F7-11 c2 判**不同根**：Lst.below 见证非 P2，走 WP5 通用通道 gi_pend_env）。
- 遗腹探针 f7_p11_budget.py（d4 预算 3000，guard 4096，pid 1131315/1131316）
  08:4x 仍在跑，日志 ~/logs/009F/f7_p11.log——F8 第一件收编对象。

---

## F8 任务书（总控 → 第八任，2026-09-16 08:5x）

F8 = 卡 009 第七任执行者。剩余问题被 F7 切成四个互相独立的块，逐块钉：

1. 第一动作 = 005 追加 "## F8 段" 表头（≤10min 节拍起点；你死了别人只认这段）。
   然后收编 f7_p11.log：若探针被 RSS 帽杀而无结论，**别硬抬预算重跑**，改用
   "状态环检测"（步窗内 dump st 元组，重复即环，单调推进即合法慢）——
   3000 步暴力跑在 O(N²) 驱动器上必爆内存，这是已知教训。
2. d4 判定：合法慢 → GRAPH_MAX_STEPS（测试内 600）属 harness 资源帽，抬帽
   必须带"步数≈递归深度线性"证据并落 005（期望值仍 oracle 现跑，不动判据）；
   是环 → 新缺陷，回定位流程（带 kernel 引用）。
3. d6 异根修复：stuck Proj restick（素材 F5-b03 + 缺口 #3），最小修 + kernel 行引。
4. lst 4 例异根：eL1（nil 载体）都不收敛 → 优先查 ping-pong/环，走 WP5
   通用 iota 通道（gi_pend_env 侧），不是 p2 通道。
5. 每块修绿后跑全量差分（guarded，~450s），分歧数递减原文落 F8 段；
   全绿（0 divergences）后进 4a/4b/4c 备忘录 + ADR016 草案 + v 收口
   （scratch --sparse → 34/34 → 20 套件 → 新差分列入评估）。
6. 停手条件与所有权照 F7 任务书原文（含解释器全路径铁律
   PY=/home/xkq/miniconda3/envs/train/bin/python）；d4 抬帽拿不出线性证据
   = 视同放宽验收，禁止。同一块第 2 次修不好 → 落证据等裁。

---

## F8 段（执行记录，2026-09-16 08:4x 派发，从盘上记录续跑）

F8 = 卡 009 第七任执行者。继承 F7 资产（尝试2 直发已入 build_vm.py、
f7_test2=6 分歧基线、遗腹探针 f7_p11.log）。解释器铁律 PY=/home/xkq/miniconda3/
envs/train/bin/python（numpy 2.5.2，开工自检 `$PY -c "import lean_vm.build_vm"` 通过 @08:47）。
核 0-5，OMP=3，日志 $HOME/logs/009F/（f8_ 前缀），长任务走
scripts/run_mem_guarded.py --max-rss-mb 4096 -- $PY …。本段表头即第一动作。

| 子任务 | 内容 | 状态 |
|---|---|---|
| 1 | 收编 f7_p11.log：d4 定性 + eL1 状态环检测（禁暴力抬预算） | in_progress |
| 2 | d4：补"步数≈递归深度线性"证据（d1/d3/d4 参考点），决定抬 GRAPH_MAX_STEPS 或回定位 | pending |
| 3 | d6：stuck Proj restick（缺口 #3，素材 F5-b03）最小修 + kernel 行引 | pending |
| 4 | lst 4 例：环/ping-pong 检测 → WP5 通用 iota（gi_pend_env）侧修复 | pending |
| 5 | 每块见进展跑全量差分（guarded ~450s），分歧递减原文落本段（6→…→0） | pending |
| 6 | 0 分歧后：c1/c2 备忘录 + ADR016 草案 + v 收口（scratch→34/34→20 套件→差分入表评估） | pending |

### F8-01（08:4x）f7_p11 收编：d4 判"合法慢 + 判决正确"，eL1 复现 OOM（禁暴力，转环检测）

- 判读（run_defeq/step 语义已核 step_driver.py:80-88/178-184：done 时
  `res=(result_pos,B)`，DEFEQ 通道 result_pos=1 ⇒ verdict True）：
  d4 段原文 `done at step 648 res=(1, 0) st=(1, 0, 0, 0, 1, 0) stream=4230`。
  **648<3000 自然停机，且全程无 `CYCLE:` 行**（探针 step65-66 有环检测：命中即打印，
  本次未命中）→ **d4 合法慢 + 判对（True=oracle）**。i=636→637 焦点跳到
  (3007/2557,0,0,..) 后 645→648 收敛到 done，尾窗单调推进，非环。
- eL1 段原文 `[mem-guard] wall 132.3s peak RSS 5257MB rc=-9 KILLED`：
  lst 暴力抬预算 **实测爆内存**（印证 F2 G5/b04：lst env O(N²) 于步数），
  无 st 尾窗输出 = 未跑到能判读的点。**禁再试 3000**，改状态环检测小窗（预算 ≤600）。
- 与总控 08:4x 快讯一致。下一步 F8-02：d4 线性证据（depth 参考点 done-step），
  并行起 lst eL1 环检测小窗（≤600）。

### F8-02（08:5x）d4 线性预算证据钉板：done-step ≈ 深度仿射，非环

- 探针 f8_p2_depth.py（guarded 4096，peak 3.57GB 主动收；日志 ~/logs/009F/f8_p2.log）。
  F2s 是**强制使用 ih** 的 handler（`|k+1,⟨ih,_⟩ => ih+(k+1)`，brecOn m F2s=Σ1..m），
  递归深度=-major，每层必须落到真值 → 是 d4 通道的正确对照（F1s 忽略 ih，
  done-step 恒 134，探针 f8_p1 已证其"非环但不测深度"，弃用）。
- 原文 done-step / stream（全部 res=(1,0)=True，全程无 `CYCLE:` 行）：
  `g1(m=1):275/2595  g2(m=2):483/2989  g3(m=3):710/3419  g4(m=4):956/3885`
  一阶差分 208/227/246（≈+19/层的稳定小量，来自 Σ 值变大后 Nat.add 多耗数字位步，
  **非指数、非发散**）；单调、确定、判决恒对。→ 机器对"深度 m 的 brecOn DEFEQ"
  给出可预测的线性级步数预算。
- 判读：d4=`brecOn 4 F3s`（F3s `|k+2,⟨_,⟨ih,_⟩⟩ => ih` 直返 ih、**不做加法**），
  done@648 **低于**同深度 F2s 的 m=4 外推（956）→ d4=648 严格落在该线性包络内，
  **合法慢**成立（不是环、不是隐藏不收敛）。
- 处置决定：**抬 GRAPH_MAX_STEPS=600 属 harness 资源帽**，判据（期望 True）不动
  （oracle 现跑，F8_p2 六例全 True 亦为旁证）。但**抬帽动作推迟到 d6/lst 真修之后**
  再统一执行——现在抬帽会让 lst 的 TimeoutError 阈值变高、全量差分 peak RSS 上探
  （基线 3749MB@cap600），且 lst 属另案须真修不许靠预算。目标终态：d6/lst 修好后
  各非环用例均快速停机，cap 抬到 ~720（覆盖 d4=648 + 余量）后全量 RSS 仍 <4GB。

### F8-03（09:0x）lst 定性=真环（livelock），非合法慢；eL2/eL3 汇到同一冻结态

- 探针 f8_p3_lst.py（guarded 4096，wall 127s peak 2864MB rc=0，预算钉 ≤600）。
  **修正 F2/F4 的环检测缺陷**：f7_p11 的 key=(st,streamlen)，stream 每步必涨→永不
  命中，环检测形同虚设；本轮改 key=state 6-元组(A,B,C,D,E,F) 单独。原文：
  - eL1 `CYCLE state repeat: step 144->145 period=1 st=(3018,0,0,3024,1,0)
    stream-delta/period=1`；尾窗 i=138-145：A=1259→2174→3018 后**冻结**、
    D=3011→3024 后冻结、E 在 0/1 抖、stream 每步 +1（纯 STATE token 追加）。
  - eL2 `CYCLE step 179->180 period=1 st=(3088,0,0,3094,1,0)`；
    eL3 **同一 st=(3088,0,0,3094,1,0)**——eL2/eL3 自 i≈160 起轨迹完全同形。
- 判读（对 F8 任务书第 4 条）：lst = **状态环**（period-1 冻结 + 1 token/步
  空转），与 d4 的"大跳单调推进到 done"截然不同（d4 全程 st 每步大变）。
  eL2/eL3 汇到同一冻结态 ⇒ 堵点是二者共享的 **Lst.below 见证对
  （P2/PProd 投影）**，与 FLs/FLr 是否用 ih 无关——正是**缺口 #1 载体推广里
  那个 below-pair**，但卡在这里不是"停 raw field"而是**通用 iota 重推进环**。
- 方向钉：走 **WP5 通用 iota（gi_pend_env，build_vm.py:1230-1247）**，非 p2
  通道（p2_succ_r 只覆盖 Nat 对；Lst.rec 走 fire_iota 元数据驱动）。冻结帧
  D=3024/3094 的性质由 f8_p4 解码钉（在跑）。

### F8-04（09:1x）f8_p4 解码：lst 冻结态 = ST(ETA_S) 自环（图 bug，非数据）

- f8_p4_lsttrace.py（guarded，wall 99s peak 2741MB rc=0）。eL1 冻结现场
  （原文尾段）：pos 3018=K_CONST(Nat)（裸 Const Nat！）、
  pos 3020=T_FRAME(5,1,2936,0,0,**43**)（TASK_ST，F2=43=**ETA_S**）、
  pos 3021=T_FRAME(1,3018,3020,0,1,0)（TASK_WHNF soft 包着裸 Const Nat、
  caller=ETA_S-ST）、pos 3023 起 STATE 自指：i=144 D=3024，此后每步
  st=(3018,0,0,3024,1,0) 不动、stream +1（dbg_complete+dbg_main 每步真、
  无发射）。即：ETA_S 续臂对"裸 Const Nat"再推 WHNF → complete 恒真 →
  弹回同一 ETA_S-ST → **period-1 状态环**。
- 对照 d4：d4 尾窗 st 每步大变（焦点沿操作数链推进）；lst 焦点恒 3018、
  栈恒 3024——定性钉死：**lst=环（新缺陷）**，不是合法慢，不抬帽。
- 内核语义基准：is_def_eq 的 eta-struct（K/type_checker.cpp eta 段）只对
  **Lam/非 lam 一侧** 做 eta-expansion，对 `Const Nat`（Sort 级类型常量）
  根本不该进 ETA_* 链。eL1 的 DEFEQ 下降把裸 `Nat` 喂进 eta-struct 的
  生成点 = 本块定位对象（候选：stuck-chain/UL 链上游某臂把 type-operand
  当 term 交给 D_SW→PI→ETA，与 d3 端局的 PI/UL 臂同族）。
- 下一步：f8_p5=同 norm2 env 喂 **冻结参照机 RefVM**（F5-b03 同款
  ref-vs-graph 判据分离法）：ref 若 halt=True → 纯图 bug（本卡修）；
  ref 若同样不收敛/拒绝 → 数据/协议问题（停手等裁）。同时用 f8_p6 沿
  caller 链回溯"裸 Nat 进 ETA_S 的那一步"生成臂。

### F8-05（09:2x）尝试 lst-1：em_frame_m2 漏 `et_sfall` 一处修复 + 新暴露第二层问题

- f8_p5（RefVM 判据分离，guarded 10s）：同 norm2 env 下 RefVM 对全部 4 条 lst
  DEFEQ **REJECT code=1 infer_app: argument type mismatch**——参照机对非 toy
  的 Lst 载体（TOY_STRUCTS 无 Lst 注记）根本推不出类型，**无判据力**（不像
  nat 族 d6 那次 ref=True 的干净分离）。故 lst 定性不靠 ref，靠下面的
  帧解码直证。
- 根因（f8_p4 帧解码直证，不依赖 ref）：`et_sfall`（ETA_S 的 s_ty 非 Pi
  回退臂，build_vm.py:4274-4286）与 `et_fall`(:4232/4250) 逐字段同构（都发
  单帧 ST(ST_ES, caller=oo 帧)、D_c=c1、E=1），但 `em_frame_m2`(:5849-5875)
  的发射 OR 列了 `et_fall` **漏列 `et_sfall`**。f8_p4 原文佐证：冻结步
  `frame_task=5(TASK_ST) frame_V2=2936 frame_F2=41(ST_ES)` 全部算好、
  `em_frame` 恒 0、D_c=c1 → D 落在本步 STATE token(3024) 上 → period-1 环。
  即"gate 连写发射漏"陷阱（AGENTS/防线 C 链同族）。
  内核依据：K/type_checker.cpp:874-886 `try_eta_expansion_core` 在
  :877 `!is_pi(s_type) → return false`；is_def_eq_core :1233-1236 收到 false
  **继续** try_eta_struct——内核任何一步都不停驻。
- 修复（第 1 次尝试，一行）：:5856 发射表加 `+ et_sfall`（带注释与内核引用）。
  import 检查 OK。
- 复测 f8_p3b（guarded 132s peak 2916MB）：**ETA_S 环消失、机器大推进**，
  但暴露第二层（三例同形）：i≈164 焦点曾 A=1（True 判决），i=166 起
  A=0 并沿 caller 链外.pop：D 3065→3064→3031→3028→**2936→2738→0**——
  2738 落在 ENV 静态区（env_len≈2743，根 DEFEQ 帧在 2741）= **pop 链
  走到垃圾"caller"**；终态 (0,0,0,0,1,0) 不停机、每步 +3 token（新环，
  比旧环深得多=真推进）。两问待钉：(α) 为何 True 翻 False（eta-struct 链
  对 Lst.below PProd 见证的判决臂？）；(β) 根判决 A=0/E=1/D=0 为何不
  halt 而空转（正常 False 用例如 d7/eLF 能快停机，说明根交付协议只在
  "pop 到 D=0 时 A 恰好是终判"路径成立，本路径的 verdict 转发把根帧
  的 caller 字段本身写坏了）。
- 下一步 f8_p7：修后 eL1 尾窗全帧解码（窗口 140-180 + 链走 2936/2738 的
  每帧 (task,V1,V2,X,E2,F2) + cont-id 命名 + A/B/E/F 两侧焦点 decode），
  钉 (α)(β) 同一处还是两处。

### 事故记录 9：F8 终止（~09:36，F8-06 判读未落）与资产收编

**形状**：后台通知标 "completed" 但 result 为空（53min/90 调用）；005 末条
F8-05（09:26），f8_p7.log 09:35 **完整跑完 rc=0**，其后无任何盘上动作。
死因未定案（探针善终说明至少活到 09:35，疑似 F8-06 判读撰写中阵亡，同
`database is locked` 族；人已于 ~12:45 重启 ZCode 客户端，环境事实记录在案）。
若 F8 复苏写盘立即让位 F9。

**F8 资产账**（全在盘，F9 不许重做）：
- d4 定性完成（F8-01/02）：648 步自然 halt、判决 True=oracle、done-step 随
  深度仿射（m=1..4 → 275/483/710/956，一阶差分 208/227/246），**合法慢实锤**。
  处置：GRAPH_MAX_STEPS 600→~720 已批**但推迟执行**（等 lst/d6 真修，
  防 lst 靠预算假绿）。
- lst 第一层已修（F8-05）：`et_sfall` 发射漏列，build_vm.py:5856-5861 一行
  修复在位（总控 09:37 复验 import OK），ETA_S period-1 环消失；引据
  K/type_checker.cpp:874-886/:1233-1236。
- lst 第二层探针数据**齐**（f8_p7.log，rc=0）：新环 RING@i=173（焦点
  frame_X=3/frame2_X=2 空转、dbg_frv0=75）、root frame area 2735-2746 全量
  dump、caller-chain walk（2936→2738→0 断链、2741→2740→2738→0）。
  (α) True 翻 False、(β) 根判决不 halt 空转两问的判读**未写**——F9 第一块
  骨头自己判读 f8_p7.log（方法照 F8-04/05 帧解码；不依赖 RefVM：F8-05 已证
  RefVM 对 Lst 载体无判据力）。
- d6 未动（缺口 #3 stuck Proj restick，素材 F5-b03 + F7-11）。
- 全量差分自 et_sfall 修复后**未跑过**：6 分歧基线形态未知，F9 修第二层时
  一并跑（guarded ~450s；B 组应 4 PASS+2 FAIL，C 组看环消失后新形态）。

---

## F9 任务书（总控 → 第九任，2026-09-16 12:5x）

F9 = 卡 009 第八任执行者。剩余四块，顺序：

1. 第一动作 = 005 追加 "## F9 段" 表头（≤10min 节拍）。自检
   `$PY -c "import lean_vm.build_vm"`（PY=/home/xkq/miniconda3/envs/train/bin/python）。
2. lst 第二层：判读 f8_p7.log 钉 (α)(β)——新环 RING@173 的帧语义
   （frame_X=3 是哪条续臂、dbg_frv0=75 空转发射源）、A=1→0 翻转点、根帧
   caller 字段写坏点；定性后最小修（kernel 引用齐）。若牵出 (β)=根交付
   协议缺陷（verdict 转发合同），**停手写 ADR 草案等裁**——那是合同级。
3. d6 修复（独立块，缺口 #3，素材 F5-b03/F7-11）。
4. 两块修绿后抬 GRAPH_MAX_STEPS 600→~720（证据=F8-02 线性表，引用落段），
   跑全量差分至 **0 divergences** 原文。**红线：lst 不许靠抬帽转绿**——
   第二层若有"合法慢"成分须先有 F8-02 同款线性证据。
5. 收尾：c1/c2 备忘录（c2 结论已有：lst 与 d3 不同根、与 d4 不同类）、
   ADR016 草案（docs/decisions/016-*.md，只写不实现）、v 收口
   （scratch --sparse 基线 24914/2878/186892 → 引擎 34/34 → 20 套件 guarded →
   新差分入 run_cpu_regression.sh 表评估）。
6. 机器与所有权条款照 F7/F8 任务书原文（核 0-5、guard 4096、解释器全路径、
   build_vm/tests/两 docs+decisions 所有权、禁改清单、pkill 防自杀、
   同一块第 2 次修不好停手等裁）。

---

## F9 段（执行记录，2026-09-16 12:4x 派发，客户端重启后首任）

F9 = 卡 009 第八任执行者。继承 F8 资产：d4 合法慢实锤（F8-02 线性表）、
lst 第一层 et_sfall 修复在位（build_vm.py:5856-5861）、f8_p7.log 第二层
探针数据齐（rc=0，判读未写）、d6 未动。解释器铁律
PY=/home/xkq/miniconda3/envs/train/bin/python（自检 import 见 F9-01）。
核 0-5，OMP=3，日志 $HOME/logs/009F/（f9_ 前缀），长任务走
scripts/run_mem_guarded.py --max-rss-mb 4096 -- $PY …。本段表头即第一动作。

| 子任务 | 内容 | 状态 |
|---|---|---|
| 0 | 自检 import + 环境确认（本段表头即落盘起点） | completed |
| 1 | lst 第二层：判读 f8_p7.log 钉 (α)(β)——RING@173 帧语义、True→False 翻转点、根帧 caller 写坏点 | completed（(β)=探针伪影关闭；(α) 判读见 F9-03/04） |
| 1b | (α)(β) 定性后最小修 + kernel 行引；若 (β)=根交付协议缺陷 → ADR 草案停手等裁 | in_progress |
| 2 | d6 修复（缺口 #3 stuck Proj restick，素材 F5-b03/F7-11）最小修 + kernel 行引 | pending |
| 3 | 每块见进展跑全量差分（guarded ~450s），分歧递减原文落本段 | pending |
| 4 | 真修全绿后抬 GRAPH_MAX_STEPS 600→~720（证据=F8-02 线性表）→ 0 divergences | pending |
| 5 | 收尾：c1/c2 备忘录 + ADR016 草案 + v 收口（scratch→34/34→20 套件→差分入表评估） | pending |

### F9-04（13:49）eL1 全链判读：停滞点钉死在 whnf 交付部分应用 lam

真实回路（f9_p2，run_defeq 原生 emit，逐步原始 token 转储 f9_p3/p4/p5，
窗口 i=40..174 全部读完）判读结论：

1. **(β) 关闭（重申）**：根交付协议无缺陷，f8_p7 的"不 halt"是探针外部
   sync() 与驱动 emit 一拍错位伪影。ground truth 只认 `drv.b.stream[-1]`。
2. **whnf(eL1) 停滞**：root WHNF@2741（i=40..101）走完 delta/beta 骨链、
   一个 TASK_NAT 帧（@2906，产 PEND 值 1649/1651/1665，LINK 2914/2916/2918
   挂 env 2872）和 WALK 链后，焦点=2870@2853→**1259@2853，C=0（pend 空），
   E=1651（残留 scratch）**。1259 = `fun (h : @Lst.below (fun x=>Nat) Lst.nil) => …`
   （域即 1255；env 2853 是 5 条 LINK 链，捕获值 1039/1041/1043/1057/1079，
   对应 match_1 展开的 binder 层）。即 FLs/nil-arm 的**第二 binder（h 见证）
   的应用在机器里丢了**。真 kernel：whnf(eL1)=1（oracle 判 eL1=1 True）。
3. i=102 whnf 以该 lam 作结果回注 ST@2740；D_SW2@2931 软归约 s 侧
   2737→2174=LitNat 1；i=106 deq_sw0 → **DEFEQ@2936 (lam 1259@2853, lit 2174@0)**
   ——这对项在真 kernel 里根本不出现。
4. 判决翻转链（i=106..174）：dispatch 14 臂（build_vm.py:3525-3657）无一命中
   (Lam, K_LIT) → deq_fall → stuck-pair/PI/ETA/UL 阶梯：PI_T@2946、PI_S@2948、
   INFER(1259)@2949 → I_LAMDOM 推域 1255=`@below (fun x=>Nat) nil` →
   I_ARG 的 DEFEQ@2985/3065：推得 `Pi(Lst→Sort 1)` vs `Lst.below` 声明 motive
   域 1422=`Pi(Lst→Sort 0)` → deq_xpi dom True@3068 → body Sort1 vs Sort0 →
   **False@3072** → 逐级上传成根判决 False，i=174 halt (0,0)。
5. **1422 的 Sort0 是测试侧数据毁伤**：`tests/test_brec_drec_iota_vs_lean.py`
   的 `norm()._spec`（:136-145）把 dump 的 `Lst.below` ty 里 motive binder 域
   `Lst → Sort (LParam u)` 折成 `Sort LZero`；而 use-site 常量 1247/1255 携带
   `Lst.below (LSucc LZero)`（u:=1 实证）。层级信息两边不一致。
6. 定性：主根因=图侧 whnf iota 链丢应用（h 见证没喂进 1259）；_spec 毁伤是
   次级放大器，决定"错判决 False"的形态。**最小修候选两层，f9_p6（13:47 起，
   pid=1189390，log /home/xkq/logs/009F/f9_p6.log）在解码 1259@2853 全体、
   5-link 捕获值与 1649/1651/1665/2398-2401 身份，钉丢应用的确切机器步。**

红线自查：未抬帽、未放宽断言；本步只读+探针（/tmp/probe009F/，非证据位）。

### 事故记录 10：F9 终止（~14:2x，F9-05 判读未落）与资产收编

**形状**：95min/95 调用，通知标 completed 但 result 空（同 F8 死状，
`database is locked` 族——**客户端 12:4x 重启后 F9 仍死于此，重启未根治，
环境事实更新**。005 末条 F9-04（13:50），f9_p7.log **14:12 完整跑完 rc=0**，
其后无盘上动作 ⇒ F9-05 判读未写。若 F9 复苏写盘立即让位 F10。

**F9 资产账（全在盘，F10 不许重做）**：
- (β) **撤销**（F9-02/03）：根交付协议无缺陷；f8_p7 "不 halt" 是探针外部
  sync() 与驱动实际 append 差一拍的**伪影**。ground truth 只认
  `drv.b.stream[-1]`（方法学教训，F10 简报已钉）。
- lst 形态**改判**（F9-03）：et_sfall 修后 eL1 真机 **174 步自然 halt、
  verdict False**（oracle=True）——"no halt after 600" 是修复前形态，
  F8 把探针伪环当成了机器环。第二层 = 纯 (α)：错判 False，源头 i=166
  DEFEQ@3072（D_XPI2 臂另起的子比较），False 沿 caller 链上传成根判决。
- (α) 停滞点**钉死**（F9-04）：whnf(eL1) 走完骨链后焦点 = 1259@2853
  （`fun (h : @Lst.below…nil) => …`，FLs/nil-arm **第二 binder h 见证的
  应用在机器里丢了**），C=0、E=1651 残留 scratch。
- **次级毁伤**（F9-04 §5）：tests 文件 `norm()._spec`（:136-145）把
  `Lst.below` ty 里 motive binder 域 `Lst → Sort (LParam u)` 折成
  `Sort LZero`，与 use-site 常量 1247/1255 的 `Lst.below (LSucc LZero)`
  层级不一致 → 决定"错成 False"的形态。属测试内数据 bug，F10 所有权内。
- 未写判读的探针数据：f9_p6.log（13:50：1259@2853 全体解码、5-link 捕获值、
  PEND 1649/1651/1665 身份）+ **f9_p7.log**（14:12 rc=0：1285@2872/@2853
  双环境对照、**"dec(1288,2872) spine in WRONG env = bvar 6 beyond env"
  报错**、raw 帧区 2752-2757、常量表）。p7 的 WRONG-env 行直指：应用对
  （1259+见证 h）在错环境展开后被弃——F10 定位从这条起。
- d6 仍**未动**（缺口 #3）；全量差分自 et_sfall 后**仍未跑过**（6 分歧
  基线陈旧，F10 首见进展即跑）。

---

## F10 任务书（总控 → 第十任，2026-09-16 14:3x）

F10 = 卡 009 第九任执行者。剩余三块：

1. 第一动作 = 005 追加 "## F10 段" 表头（≤10min 节拍）。自检
   `$PY -c "import lean_vm.build_vm"`（PY=/home/xkq/miniconda3/envs/train/bin/python）。
   **方法学红线**：机器真实态只认驱动 append 的 STATE token
   （`drv.b.stream[-1]`）；外部再 sync() 差一拍，是 f8_p7 伪环成因，禁止复发。
2. lst 第二层修复：判读 f9_p6/f9_p7.log，从 "spine in WRONG env (bvar6
   beyond env)" 与 whnf 停滞焦点 1259@2853 起，定位 **h 见证应用丢失**的
   确切机器步（iota 应用侧，build_vm.py），最小修 + kernel 引用
   （/home/xkq/lean4/src/kernel/inductive.h iota 应用段）。同时修 tests
   `norm()._spec` 层级毁伤（恢复 `Sort (LParam u)`，与 1247/1255 一致）。
   修后跑全量差分（guarded ~450s）记录递减原文。
3. d6 修复（缺口 #3 stuck Proj restick，素材 F5-b03/F7-11，独立块）。
4. 两块真修绿后抬 GRAPH_MAX_STEPS 600→~720（证据=F8-02 线性表引用落段）→
   0 divergences。红线：lst 不许靠抬帽转绿；期望值始终真 lean 现跑。
5. 收尾：c1/c2 备忘录（c2 结论链已齐：lst 与 d3 不同根、d4=合法慢、
   lst 二层=丢应用）、ADR016 草案、v 收口（scratch --sparse 基线
   24914/2878/186892 → 引擎 34/34 → 20 套件 → 差分入 run_cpu_regression.sh
   表评估）。
6. 机器/所有权/停手条款照 F7 任务书原文（可改：build_vm.py、
   tests/test_brec_drec_iota_vs_lean.py、run_cpu_regression.sh 仅加行、
   VM_SPEC、KERNEL_COVERAGE B 行、005、decisions/；同一块第 2 次修不好
   停手等裁；牵出合同级写 ADR 停手）。

### F9-01（12:49）开工：表头落盘、import 自检 OK、机器检查

- `$PY -c "import lean_vm.build_vm"` → import OK（0.68s）。`ps --sort=-rss`：
  唯一大户 = 卡 006 的 GPU 训练进程（1.3GB，非本卡、不抢 0-5 内存帽），
  无并行大 env Python。f8_p7.log 全文已在手（8476B，rc=0）。

### F9-02（13:0x）寄存器语义钉板 + (β) 实验：根 halt 通道在合成态下**是好的**

- 帧/task 语义对照（build_vm.py:63-74、expr/tokens.py:111-116、:186-204）：
  task：1=WHNF、2=NAT、3=WALK、5=ST、6=INFER、7=DEFEQ；ST.F2 cont-id：
  I_FN=1、I_PI=2、I_ARG=3…I_LAMSORT=6…D_XPI2=23、D_SW2=24…；
  32=I_PROJ、ST_ES=41、ETA_S=43、ETA_LNK2=47、CK_TY=55、UL_W=61。
  `ret_pending=reglu(SE,1-walk-compute-iota)`(:650)、`has_frame=SD>=1`(:607)、
  根交付 halt = `ret_pending·(1-has_frame)`(:5844 第二项，注释 :6113-6123)。
- 探针 f9_p1（guarded 108s peak 2866MB rc=0，~/logs/009F/f9_p1.log）关键原文：
  `i=173 st=(0,0,0,0,1,0) done=0 raw_done=1.0000`（外部 sync 读 done=1！）
  `SYN in=(A0,B0,C0,D0,E1,F0) -> done=1 r=(0,0) raw_done=1.0000`
  `SYN in=(A1,B0,C0,D0,E1,F0) -> done=1 r=(1,0)`。
  ⇒ **(β) 的"合同级缺陷"方向被否**：根交付协议本身完好——合成喂
  (0,0,0,0,E=1) 一步即 done=1、result=(0,0)=False 判决。矛盾在重放环里
  step() 内部读到 done=0：f8_p7 打印的 st 是探针**外部再 sync** 的输出，
  ≠ 驱动实际 append 的 STATE token（增量求值外部/内部 sync 差一拍）。
  f9_p2（在跑）读原始 append token + 真 run_defeq(800) 判"到底停不停"。
- 预钉 (α) 翻转点（f8_p7 + f9_p1 对齐）：i=163-164 DEFEQ@3068 判 True
  （st=(1,0,0,3067,1,0)），ST@3067(cont=D_XPI2=23) 消费 True 后以 E=0
  重新起子比较 DEFEQ@3072（i=165-166），3072 一步判 False 弹回：
  A=1→0 翻转 = **3072 这个新 DEFEQ 子任务的判定**，不是转发写坏。
  3072 比的是什么（frame2_V1=230=pend_V0 侧?）等 f9_p3 帧区 dump 钉死。

### F9-03（13:1x）(β) 销案 + lst 形态改判：真循环 **halt=174 步、verdict False**（非 no-halt）

- f9_p2_truth.py（guarded 161s peak 2869MB rc=0，~/logs/009F/f9_p2.log）原文：
  `REALLOOP halt: (0, 0) steps: 174` + 尾窗逐步打印**驱动实际 append 的
  STATE token**：`i=173 appended=(K=33,A=0,B=0,C=0,D=0,E=1,F=0) ret_done=0`
  `i=174 appended=(…D=0,E=1…) ret_done=1 ret=(0, 0)` `DONE (0, 0)`。
- 判读（推翻 F8-05 的 (β) 两问）：
  1. **环不存在**——f8_p7/f8_p3b 打印的 st 来自探针**外部再 sync**，与驱动
     append 的真实 STATE 差一拍；真实机器在 174 步自然 halt。
     `no halt after 600` 是 et_sfall **修复前** 的形态（ETA_S period-1 环），
     修后全量差分未跑过（F8 资产账已注记），F8-05 把探针伪环当成了机器环。
  2. **根交付协议无缺陷 → 不写 ADR、不涉合同级**（(β) 撤销）。
  3. lst 第二层 = 纯 (α)：**graph 判 False，oracle=真 lean 判 True**（d1 类
     正例转成了错判，分歧数没少、形态变了）。verdict False 的源头：
     i=165 ST@3067（cont=D_XPI2=23）消费子判 True 后另起 DEFEQ@3072，
     3072 在 i=166 直接判 0 弹回 caller 链 3065→3064→3031→3028→2936→2738→0。
- 下一步 f9_p3（在跑，逐步 append dump + 帧区 2930..3094 全解码 + DEFEQ 帧
  双侧闭包解码）：钉 3072 的 t/s 是什么、3067 D_XPI2 臂起子比较用的 env，
  与 deq_xpi 发射字段对照内核 type_checker.cpp 的 x-pi 臂语义。

## F10 段（执行记录，2026-09-16 14:4x 派发，第九任 F9 阵亡后首任）

F10 = 卡 009 第九任执行者。继承 F9 资产：(β) 撤销、lst 改判 174 步 halt
verdict False、停滞点 1259@2853（h 见证应用丢失）、f9_p6/f9_p7.log 判读
未写、_spec 层级毁伤已定位、d6 未动、全量差分 et_sfall 后未跑。
解释器铁律 PY=/home/xkq/miniconda3/envs/train/bin/python。核 0-5，OMP=3，
日志 $HOME/logs/009F/（f10_ 前缀），长任务走
scripts/run_mem_guarded.py --max-rss-mb 4096 -- $PY …。
**方法学红线**：机器真实态只认驱动 append 的 STATE token
（`drv.b.stream[-1]`），禁止探针外部 sync() 再读（f8_p7 伪环成因）。
本段表头即第一动作。

| 子任务 | 内容 | 状态 |
|---|---|---|
| 0 | 自检 import + 环境确认（本段表头即落盘起点） | completed |
| 1 | 判读 f9_p6/f9_p7.log：从 WRONG-env 行与 1259@2853 定位 h 见证应用丢失的确切机器步 | in_progress |
| 1b | lst 第二层最小修 build_vm.py（kernel 引用 inductive.h iota 应用段）+ tests norm()._spec 层级修复 | pending |
| 2 | 修后全量差分（guarded ~450s，核 0-5 OMP=3），分歧递减原文 | pending |
| 3 | d6 修复（缺口 #3 stuck Proj restick，素材 F5-b03/F7-11，独立块） | pending |
| 4 | 两块真修绿后抬 GRAPH_MAX_STEPS 600→~720（F8-02 线性表）→ 0 divergences | pending |
| 5 | 收尾：c1/c2 备忘录 + ADR016 草案 + v 收口（scratch→34/34→20 套件→差分入表评估） | pending |

### F10-01（14:5x）f9_p6/f9_p7 判读：丢应用点=通用 OP_IOTA build 环不喂 extras

- 判读结论（真机帧 2752-2759、2880-2890 + 闭包解码，全在 F9 盘上数据内）：
  1. **触发 iota 的是 Lst.rec**（scratch 帧 2883: V1=52=Lst.rec cid、V2=2741
     caller、X=2 build 环；控制帧 2882: V1=15=OP_IOTA、X=1、E2=1288 脊根）。
     1288@2853 解码 = `App^5(Lst.casesOn, motive, nil, nArm, cArm, UnitT.mk)`
     ——witness（UnitT.mk）在 spine 上活着（2881 F=1288、2882 E2=1288、
     2884 F=1288 一路带进帧），但 build 完成后交付焦点=1259@2853（nil-arm
     lam `fun h => (fun h=>1) h`），C=0——witness 应用没接回去。
  2. **build 环只发 pmm+nf 个 PEND**（build_vm.py:1214-1247：
     gb_total=pmm+SB、索引 E 从 0 到 total-1，无 extras 通道）。真内核
     4.35 master `/home/xkq/lean4/src/kernel/inductive.h:113-117` 在 fields
     之后有显式一段：`if (rec_args.size() > major_idx + 1) { nextra = ...;
     rhs = mk_app(rhs, nextra, rec_args.data()+major_idx+1); }` ——recursor
     脊 major 之后的额外实参必须重新贴到 rhs。硬编码
     OP_REC/OP_CASESON/OP_CASESON_P2/OP_CASESON_BOOL 臂都带 extras
     （rec_extras/cs_extras/p2_extras/b_extras = maj entry 的 V2，
     :929/:979/:1005/:1041），**唯独通用 OP_IOTA 没有**。
  3. WRONG-env 报错（dec(1288,2872)=bvar6 beyond env）是**次生伪影**：1288
     是 5-link env(2853) 下的项，探针在 2872 链的同 pos token 上用错 env
     解码，不是机器用错 env。
  4. d1-d4 不炸的原因：Nat 语料的 casesOn/rec 全走硬编码臂（extras 齐），
     P2.below 链 extras 恒空；Lst 语料 first-fire 走通用臂、extras=
     UnitT.mk 非空 → 丢应用。
- 修复方向（待定探针钉死 build 完成态的链序再动手）：build 环把 maj entry
  之后的 extras 链头接进最终 PEND 尾（同 quot 的 `V2=extras` 手法，
  build_vm.py:1193/:1204-1205 有先例）。
- 下一步 f10_p1：动态复现 whnf(eL1) 至 halt，标出 fire 步与 build 完成步，
  dump 交付态 (A..F)+PEND 链序（确认 arg0 在头），钉 extras 接入点。

### F10-02（15:0x）f10_p1 动态钉死 + extras 修复落码（build_vm.py 三处）+ _spec 修

- f10_p1（guarded 91s peak 2630MB rc=0，~/logs/009F/f10_p1.log）逐步 append
  STATE trace（驱动真值，无外部 sync）关键原文：
  - `i=56 ... F2781(t=2,V1=15,V2=2782,X=1,E2=1598,F2=2779) scr(2,52,2758,2,0,0) IOTA1`
    ——第一次 fire：cid52=Lst.rec，major=chain[3]。
  - `i=63/64/65 F2794(t=2,V1=15,...,X=2,...) IOTA2`（E=0→1→2，pmm=3 发满）
    → `i=66 C=2796 pend=[1565/2771,1575/2771,1595/2771]`——**交付链只有
    3 个重建 PEND，major 之后无链接续**（尾节点 V2=0）。
  - `i=111 A=1667 B=2872 C=0 D=2882 F2882(t=2,V1=15,V2=2883,X=1,E2=1288,
    F2=2880) scr(2,52,2741,2,0,0) IOTA1` + i=110 pend=
    `[1649/2872,1651/2872,1665/2872,1667/2872,1287/2853]`——第二次 fire 的
    保存链**第 5 项 1287@2853 = witness UnitT.mk**，build 完成后同样被丢。
  - major walk（i=112-115）X=2→1→0 落 link 2868 val=1245=Lst.nil——bvar
    idx 按 d 反序解析正确（F9 曾疑 off-by-one，销）。
- 修复（build_vm.py，通用 OP_IOTA 三处，语义引
  `/home/xkq/lean4/src/kernel/inductive.h:115-118`：`if (rec_args.size() >
  major_idx + 1) { nextra=...; rhs = mk_app(rhs, nextra, rec_args.data()+
  major_idx+1); }`；prefix/fields 对照同文件 :107-108/:113-114）：
  1. 交付处新增 `gi_extras = v2(_pick(_chain_v2(frF2, CHAIN_MAX),
     gm["majidx"]))`（从 frame 保存链重读，同 rec/cs/p2/b_extras 的
     M5 重导手法）。
  2. build 环最终发射步 `gi_pend_prev` 尾部 `Zero → gi_extras`：重建 PEND
     链尾直接**拼接原始 extras 节点**（自带 expr pos+env，不重发、零新增
     token 数）。
  3. `iota_zero_r` 退化分支 `C_iota_build: Zero → gi_extras`（rhs 不吃参数
     时 extras 直接上摆）。
  extras=0 的既有语料（Nat 硬编码臂 + 无 extras 通用臂）逐位不变。
- tests norm()._spec：`LParam → LSucc(LZero)`（原 LZero）。依据：语料全部
  motive `fun x => Nat : Sort 1`，use-site 常量实证携带 (LSucc LZero)；
  折 0 造成 x-pi 域比较 Sort1 vs Sort0 假 False（F9-04 §5 次级毁伤）。
- f10_p2（在跑，guarded，~/logs/009F/f10_p2.log）：修后图判 11 例（无
  oracle）。预期 eL1 转 True；d4 仍帽内 False（合法慢 648>600，待抬帽）。

### F10-03（15:2x）f10_p2 判读：Nat 前三例+d3 无回归，d6/d7 False→Timeout 回归，二分在跑

- f10_p2.log 原文（B 组）：
  ```
  GRAPH B nat G3_d1_3: d1=?=e1 -> True
  GRAPH B nat G3_d1_4: d2f=?=ef -> False
  GRAPH B nat G3_d1_shadow: d1=?=d5r -> True
  GRAPH B nat G2_d3: d3=?=e3 -> True
  GRAPH B nat G2_d4: d4=?=e4 -> TimeoutError: no halt after 600 steps
  GRAPH B nat G4_d6: d6l=?=d6r -> TimeoutError: no halt after 600 steps
  GRAPH B nat G4_d7: d6l=?=d7r -> TimeoutError: no halt after 600 steps
  [mem-guard] wall 417.2s peak RSS 4195MB rc=-9 KILLED: RSS 4195MB > cap 4096MB
  ```
  lst 组未跑到（p2 设计=两组共用一进程，d6/d7 各 600 步超时把 RSS 顶过
  4096 帽被看门狗杀——是 d6/d7 回归的症状，非 lst 本身内存问题；基线
  f7_test1 peak 3749MB 时 d6/d7 是快速 False）。
- 判读：d1/d1_4/shadow/d3 与基线逐条一致（**build 侧 extras 拼接对 Nat
  硬编码臂零影响，符合设计**）。**新回归=d6/d7 快速 False→Timeout@600**，
  头号嫌疑=tests `_spec` 折级 LZero→LSucc(LZero)（改的是数据侧层级，
  level 比较路径多一条 UL/imax 回路）；次嫌疑=拼接误入 Nat 语料的某条
  通用臂（PProd 残留 spine）。f10_p3（guarded 4096，~/logs/009F/f10_p3.log）
  =保持 build 拼接、_spec 回退 LZero，只跑 d6/d7 二分。
- 预案：若归因 _spec → 换修法：**不全局折级**，改为在 norm() 里只对
  `below` 常量 ty 的 motive 域做定点归一（或干脆只修 use-site 一致性），
  层级毁伤的另一半可能由 lst 修复后自动消失（不再进 x-pi 比较）。
  同一块第 2 次修不好 → 停手落证据等裁（纪律）。
- 待办不变：eL1 判决验证（单独 lst 小探针）、d6 尾窗 trace（f8_p6 从未跑过，
  需按 append 真值口径改写）、全量差分。

### F10-04（15:2x）f10_p4：spec1+splice 下 lst 4/4 对 oracle 全绿；spec0 臂裁决改独立进程

- f10_p4.log 原文：
  ```
  == _spec=spec1(LSucc LZero) ==
    G5_eL1: eL1=?=eL1R -> True steps=118
    G5_eL2: eL2=?=eLR -> True steps=158
    G5_eL3: eL3=?=eLR -> True steps=460
    G5_eL3_neg: eL3=?=eLF -> False steps=458
  == _spec=spec0(LZero) ==
  [mem-guard] wall 180.1s peak RSS 4240MB rc=-9 KILLED: RSS 4240MB > cap 4096MB
  ```
- 判读：**第二层（extras 丢应用）修实锤**——eL1 由 174 步 False → 118 步
  True，与 oracle（True/True/True/False，基线 6 分歧= d4,d6+lst×4 反推）
  4/4 一致；步数 118–460 全部帽内。d6/d7 回归确归因 _spec（F10-03 二分）。
- spec0 臂没出裁决（同进程双臂内存累积 4240MB 越帽被杀，非 lst 本身内存
  问题）。f10_p5=独立进程只跑 spec0 lst（帽 5120，机器侧仍 <6GB 红线）。
  裁决规则不变：**spec0 若也 4/4 绿 → 整体回退 _spec 编辑（数据管线不动，
  F9 那次折级是对 bvar off-by-one 误诊的残留）**；spec0 若红 → spec1 是
  lst 真需，d6/d7 在 spec1 层级下的 Timeout 归 d6 块（缺口 #3 臂对
  level≠0 常量的处理）继续查。同一块第 2 次修不好即停手等裁。

### 事故记录 11：F10 阵亡（database is locked 再实锤，~15:2x）与资产收编

**形状**：通知 error 原文 `database is locked`（59min/95→100+ 调用），005
末条 F10-04（15:26），遗腹探针 f10_p5_spec0_lst.py **仍在跑**
（pid 1216050/1216051，帽 5120，log ~/logs/009F/f10_p5.log 空待出）。
环境事实：重启客户端无效已记录，该病按"每任必死、靠节拍兜损"运营。

**F10 资产账（全在盘，F11 不许重做）**：
- **lst 第二层根因判读完成 + 已修复**（F10-01/02）：通用 OP_IOTA build 环
  不喂 extras——交付链只发 pmm+nf 个重建 PEND，major 之后的 extras 原始
  节点（witness UnitT.mk）被丢；硬编码 rec/cs/p2/b 臂都带 extras 唯独
  通用臂没有。修三处（gi_extras 重读 + build 尾拼接 + iota_zero_r 退化
  分支），引据 inductive.h:115-118。**f10_p4 实证 lst 4/4 对 oracle 全绿**
  （eL1 118 步 True、eL2 158、eL3 460、neg 458 步 False，全帽内）。
- WRONG-env 报错定性=探针次生伪影（在错 env 的同 pos token 上解码），销案。
- **遗留回归 = _spec 编辑副作用**：tests norm()._spec 折级
  LZero→LSucc(LZero) 致 d6/d7 快速 False→Timeout@600（F10-03 二分锁定，
  f10_p4 spec1 臂复现）。**裁决规则（F10-04 已批，F11 执行）**：
  f10_p5 spec0 臂若也 4/4 绿 → 整体回退 _spec 编辑；若红 → spec1 保留，
  d6/d7 Timeout 归 d6 块（缺口 #3 臂对 level≠0 常量的处理）继续查。
- d6 仍未修；全量差分仍未跑过（修后形态=预期 B 组除 d6/d7?+d4 帽内，
  C 组全绿）。

---

## F11 任务书（总控 → 第十一任，2026-09-16 15:4x）

F11 = 卡 009 第十任执行者。剩余三块，顺序：

1. 第一动作 = 005 追加 "## F11 段" 表头（≤10min 节拍）；**不得杀**
   f10_p5 遗腹探针（pid 1216050/1216051），轮询其 f10_p5.log 出结果
   （预计 ~450s 内）。自检 `$PY -c "import lean_vm.build_vm"`
   （PY=/home/xkq/miniconda3/envs/train/bin/python）。
2. 执行 F10-04 裁决规则（规则原文在上条，不许改判）：spec0 绿 → 回退
   _spec 编辑（git checkout 该 tests 文件的 :136-145 段，回退前先
   备份 diff 进 F11 段）；spec0 红 → 保留 spec1，d6/d7 Timeout 并案
   入 d6 块。无论哪支，回退/保留动作后立即跑一次全量差分
   （guarded 5120、独立进程可分 B/C 两跑防内存累积），分歧数原文落段。
3. d6 修复（缺口 #3 stuck Proj restick，素材 F5-b03/F7-11 + 若 spec1 支
   则含 d6/d7 Timeout 归因）：尾窗 trace 必须按 append 真值口径
   （drv.b.stream[-1]，f8_p7 伪环教训），最小修 + kernel 文件:行。
4. d4 抬帽 GRAPH_MAX_STEPS 600→~720（F8-02 线性表证据引用落段），复跑
   至 **0 divergences**。红线不变：lst/d6 不许靠帽转绿；期望值真 lean 现跑。
5. 收尾：c1/c2 备忘录成文、ADR016 草案、v 收口（scratch --sparse →
   引擎 34/34 → 20 套件 → 差分入 run_cpu_regression.sh 表评估）。
6. 机器/所有权/停手条款照 F7/F10 任务书原文。特别警示：机器上另有非本卡
   进程（research gemma4 探针、用户 GPU 训练），**勿动勿杀**；本卡只锁
   核 0-5。同一块第 2 次修不好 → 落证据停手等裁。

---

## F11 段（执行记录，2026-09-16 15:3x 派发，第九任 F10 阵亡后首任）

F11 = 卡 009 第十任执行者。继承 F10 资产：OP_IOTA extras 三处修复在码
（gi_extras 重读 :1147 / iota_zero_r 退化 :1173 / 链尾拼接 :1261，引据
inductive.h:115-118，import 自检 OK）、f10_p4 实证 spec1 下 lst 4/4 绿、
裁决输入=遗腹探针 f10_p5。解释器铁律
PY=/home/xkq/miniconda3/envs/train/bin/python（自检 import + numpy 2.5.2 @15:35 通过）。
核 0-5，OMP=3，日志 $HOME/logs/009F/（f11_ 前缀），长任务走
scripts/run_mem_guarded.py。方法学红线：机器真实态只认 `drv.b.stream[-1]`。
本段表头即第一动作。

| 子任务 | 内容 | 状态 |
|---|---|---|
| 0 | 自检 import + 环境确认（本段表头即落盘起点） | completed |
| 1 | 收编 f10_p5 spec0 臂 → 执行 F10-04 裁决规则（不许改判） | completed（裁决=回退 _spec） |
| 2 | 裁决后全量差分（guarded 5120，B/C 分跑防内存累积），分歧数原文 | pending |
| 3 | d6 修复（缺口 #3 stuck Proj restick；append 真值口径尾窗 trace；素材 F5-b03/F7-11） | pending |
| 4 | d4 抬帽 GRAPH_MAX_STEPS 600→~720（F8-02 线性表）→ 复跑至 0 divergences | pending |
| 5 | c1/c2 备忘录成文 + ADR016 草案（只写不实现） | pending |
| 6 | v 收口：scratch --sparse 报增量 → 引擎 34/34 → 20 套件 → 差分入表评估 + 文档同步 | pending |

### F11-01（15:36）f10_p5 自然跑完收编 + 裁决执行：回退 _spec 编辑

- 探针终态（15:34 检查：pid 1216050/1216051 已不存在=自然退出，未被杀）。
  `~/logs/009F/f10_p5.log` 原文：
  ```
  spec0 G5_eL1: eL1=?=eL1R -> True steps=118
  spec0 G5_eL2: eL2=?=eLR -> True steps=158
  spec0 G5_eL3: eL3=?=eLR -> True steps=460
  spec0 G5_eL3_neg: eL3=?=eLF -> False steps=458
  total 177s
  [mem-guard] wall 184.7s peak RSS 3265MB rc=0
  ```
- **裁决**：spec0 4/4 绿（步数与 spec1 逐条全同 118/158/460/458）→ 按
  F10-04 已批规则：**整体回退 _spec 编辑**（数据管线=LST_ROOTS 增注
  Lst.below/brecOn/brecOn.go + _PPROD_EXEMPT 映射豁免，全部不动）。
  F9 的折级改动系对 bvar off-by-one 误诊的残留（F10-01 §3 WRONG-env 已销案）。
  旁证：f10_p3.log（splice+spec0 只跑 d6/d7）原文
  `SPEC0 G4_d6 -> False / SPEC0 G4_d7 -> False`，175s rc=0 peak 3750MB——
  回退后 d6/d7 恢复"快速 False"基线形态（缺口 #3 本体，另案真修），
  d6/d7 Timeout 不再并案入 d6 块。
- **回退前 diff 备份**（tests/test_brec_drec_iota_vs_lean.py :136-153，
  该文件为 untracked 新文件，F6 建档后未提交，无法 git checkout，故直接
  Edit 回退；备份=被替换文本原文）：
  ```python
  def _spec(l):
      if isinstance(l, LParam):
          # Instantiate dumped level params at the universe the ACTUAL motives
          # use: every motive in these corpora is `fun x => Nat` : Sort 1, and
          # the use-site constants carry concrete (LSucc LZero) (e.g. the
          # `Lst.below` witness domain, 005 F9-04 §5).  Folding to LZero made
          # the declared motive domain `Sort 0` disagree with the inferred
          # `Sort 1` and turned the kernel's x-pi arg check False (secondary
          # damage of the eL1 divergence; main root cause was the graph-side
          # OP_IOTA extras drop, K/inductive.h:115-118).
          return LSucc(LZero())
      if isinstance(l, LSucc):
          return LSucc(_spec(l.l))
      if isinstance(l, LMax):
          return LMax(_spec(l.a), _spec(l.b))
      if isinstance(l, LIMax):
          return LIMax(_spec(l.a), _spec(l.b))
      return l
  ```
  回退动作：LParam 分支 `return LSucc(LZero())` → `return LZero()`，注释改为
  记录本裁决（防后人再折）。其余逐字不动。
- 机器检查：无本卡遗留进程；f10_p5 终态 rc=0 后 $HOME/logs/009F 无新增写入者。
  下一步 F11-02：回退落码 → import 检查 → B/C 分跑全量差分。

### F11-02（15:49）回退落码 + 裁决后全量差分：**2 分歧**（7→6→2 轨迹成立）

- _spec 回退已落 tests（LParam→LZero，注释记录裁决防再折）；数据管线
  （LST_ROOTS 增注 below/brecOn/go + _PPROD_EXEMPT）未动。单进程全量
  （A+B+C 同进程未触发内存问题，无需 B/C 分跑）：
  `run_mem_guarded --max-rss-mb 5120`，pid 1234212/1234213，日志
  `$HOME/logs/009F/f11_p1_full.log` 原文：
  ```
  A  export-boundary normalizer (route ii) invariants
     OK (no redex HAdd left; P2.casesOn toy order + 1 level)
  B nat  faithful brecOn DEFEQ vs oracle (graph max_steps=600)
    [PASS] D G3_d1_3: d1=?=e1  oracle=True  graph=True
    [PASS] D G3_d1_4: d2f=?=ef  oracle=False  graph=False
    [PASS] D G3_d1_shadow: d1=?=d5r  oracle=True  graph=True
    [PASS] D G2_d3: d3=?=e3  oracle=True  graph=True
    [FAIL] D G2_d4: d4=?=e4  oracle=True  graph=TimeoutError: no halt after 600 steps
    [FAIL] D G4_d6: d6l=?=d6r  oracle=True  graph=False
    [PASS] D G4_d7: d6l=?=d7r  oracle=False  graph=False
  C lst  faithful brecOn DEFEQ vs oracle (graph max_steps=600)
    [PASS] D G5_eL1: eL1=?=eL1R  oracle=True  graph=True
    [PASS] D G5_eL2: eL2=?=eLR  oracle=True  graph=True
    [PASS] D G5_eL3: eL3=?=eLR  oracle=True  graph=True
    [PASS] D G5_eL3_neg: eL3=?=eLF  oracle=False  graph=False
    [NOTE] [B nat G2_d4] graph='TimeoutError: no halt after 600 steps' lean=True
    [NOTE] [B nat G4_d6] graph=False lean=True

  === brecOn/drecOn faithful iota vs lean: FAIL (2 divergences) 379s ===
  [mem-guard] wall 379.6s peak RSS 3771MB rc=1
  ```
- 判读：回退兑现预期——d6/d7 恢复"快速 False"形态（Timeout 随 _spec 回退
  消失，**不并案**）；C 组 4/4 绿且与 B 组同进程不炸内存（peak 3771MB
  <4GB）。剩余 2 分歧=① d4 帽内合法慢（648>600，F8-02 线性表，待任务 4
  抬帽）② d6 缺口 #3（本卡唯一真缺陷）。
- 递减轨迹：7（f5_test2 基线）→6（f7_test2）→2（f11_p1_full）。

### F11-03（16:0x）d6 全链 trace 判读：假说更正——非图 restick bug，是注入常量的层级保真

- 内核基准已钉：whnf 侧 Proj 分支
  K/type_checker.cpp:503-508（reduce_proj 失败 r=e 原样返回）；stuck-proj
  对端判定臂 :1216-1221（`is_proj&&is_proj&&sname==&&idx==` →
  `lazy_delta_proj_reduction` :1123-1138），图内已有 WP7-A15 非承诺版
  （build_vm.py:206-209/3580-3585/4061+ DE_PRJ）。
  探针 f11_p2（guarded 5120，pid 1240088/1240089，rc=0，wall 120.9s peak
  3770MB；日志 $HOME/logs/009F/f11_p2.log）：nat 组 d6l=?=d6r 全步
  append 真值 trace（STATE token + D 帧 + DEFEQ 双侧闭包解码）。**真机
  557 步自然 halt，verdict False**（非不收敛）。判读：
  1. 双侧 whnf 的 stuck-proj 交付本身是对的（i=31/63）：T=`558@3025`、
     S=`2311@3085`，均 `Proj(P2,0,·)`，restick 臂行为与内核
     :503-508 一致。**"stuck Proj restick 交付形态错"的 c1 旧假设不成立。**
  2. 根 DEFEQ@3128 → proj_same 子比较 DEFEQ@3131（i=65 双侧闭包解码）：
     T=`App^3(Nat.brecOn.go@{LZero},·,·,·)`，S=`App^3(Nat.brecOn.go@{LSucc
     LZero},·,·,·)`——**头常量层级 0 vs 1 不一致**。这不是图判决 bug，是
     测试侧 ENV 数据不一致：机器的 delta 重放取 ENV_HDR.V2 共享单值
     （build_vm.py:1275，无层级实例化；D13/D14 只对**声明类型**按使用点
     实例化并存 K_CONST.E2，:5284-5290 注释+VM_SPEC §12.7；raw param
     进 LEVEL 直接拒 :5405）。tests 注入的 dump `Nat.brecOn` 值里
     `go@{LParam u}` 被 norm()._spec **回退后的折级**洗成 `go@{LZero}`；
     而 d6r 源文本 `@Nat.brecOn.go (fun x=>Nat) tq F1s` 的 elaborator
     实参层级是 concrete `{1}`（`use`-site 无 LParam，_spec 不触）。
  3. False 生成臂（i=159-236 帧解码）：层级不一致触发图的 x-pi/infer 深降
     （I_PI/I_ARG/I_CHK 阶梯），比较里出现 `UnitT =?= Nat`（DEFEQ@3427，
     i=236 判 False）——即 _spec=LSucc 时代 d3 端局同款臂（F5 c1 关联判断
     对上了：D6 与 #2b 历史上确实同臂，但**臂的输入数据**才是病灶）。
     后续 i=510-554 的 `Pi(Nat,Sort1)=?=Pi(Nat,Sort0)`（折级后 below 声明
     motive 域 Sort0 vs 使用点 Sort1）是第二处层级自伤。
  4. 结论：**缺口 #3 重定性=测试侧注入常量的层级保真问题**（F9-04 §5
     "次级毁伤"实为 d6 的主伤）；F5-b03 "ref=True/图=False ⇒ 纯图 bug"
     的分离判据在"数据本身含非法层级对"时无效——ref_vm 快速路径不比
     常量层级，才会与图分叉。真内核环境里 brecOn@{1} 的 delta 值内
     go@{1}，与 d6r 同形，quick 结构即 True（oracle 现跑 True 与此一致）。
- 修复路线（F11-04 验证）：不动全局 _spec（裁决保持 LZero）、不动图
  delta 重放语义——在 build_group 对**注入的**多态常量
  （Nat.below/Nat.brecOn）做**使用点实例化**：从同 dump 的使用点
  （d1..d7r 的 spine 里 `Const Nat.brecOn@{1}`）读该常量各 univ param
  的具体层级，把其 ty/val 内的 LParam(name) 按参数名映射替换（等价于
  内核 instantiate_value_lparams，K/instantiate.cpp:248-254 的测试侧
  预演）。F10-03 预案"只修 use-site 一致性"的落地。若替换后 d6 仍非
  快速 True（Timeout/环），才回到图侧（并案分支）。

### F11-04（16:2x-16:4x）use-site 实例化落码 + 静态验证 + 图探针：d6 转入 Timeout 形态 → 走并案分支

- 层级几何探针 f11_p4（lean-only，直跑 rc=0，日志
  $HOME/logs/009F/f11_p4.log）：nat 组 `Nat.below/Nat.brecOn/Nat.brecOn.go`
  均 `up=['u']`（单参），三者的**具体使用点唯一且一致**=`{S(LZero)}`（d1..d4、
  d6l 用 brecOn@{1}；F1s/F2s/F3s/d5r/d6r/d7r 用 below@{1}/go@{1}）；
  `Nat.rec` 具体 tuple 4 个（语法变体混存）、`Nat.casesOn/PProd.casesOn` 等
  "仅参数化使用"——这些按设计跳过（留给 _spec 折级，零回归）。lst 组
  `Lst.below/Lst.brecOn` 具体 tuple `{S(LZero)}`，`Lst.brecOn.go` 无直接
  具体使用点（其 {1} 只能从实例化后的 Lst.brecOn.val 传播得到）。
- 落码（tests/test_brec_drec_iota_vs_lean.py，新增 4 个纯数据 helper
  `_has_lparam/_subst_lvl/_subst_use/_concrete_use_sites` +
  `_instantiate_dump`，build_group 在 dump_env 之后调用）：**不写死任何常量
  名**——凡 `up` 非空的 dump 条目都进候选集，迭代传播至不动点（外层先实例
  化、把内层使用点变具体），唯一具体 tuple 才替换 ty/val 里的 LParam；
  多 tuple/无 tuple 保持现状。注释指 K/instantiate.cpp:248-254 与
  build_vm.py:1273-1284（图侧 monomorphic replay 无层级实例化）。
- 静态验证 f11_p5（rc=0，$HOME/logs/009F/f11_p5.log）：实例化后
  brecOn.val 内 `go@{1}`、go.val 内 `below@{1}/PUnit.unit@{Max(1,1)}`、
  三者 ty 内 motive 域 `Sort(1)` 全部具体；ty 残留 LParam 仅 PProd 自身
  声明位（预期，跳过项）。`_instantiate_dump` 达到不动点（否则 assert 抛）。
- 图探针 f11_p6（guarded 5120，pid 1243083/1243084，wall 259.5s peak
  3879MB rc=0，$HOME/logs/009F/f11_p6_nat.log），期望列=f11_p1 真 oracle
  原文：
  ```
  [OK ] G3_d1_3: d1=?=e1 expected=True got=True steps=135 9.9s stream=3310
  [OK ] G3_d1_4: d2f=?=ef expected=False got=False steps=133 8.4s stream=3306
  [OK ] G3_d1_shadow: d1=?=d5r expected=True got=True steps=172 10.4s stream=3378
  [OK ] G2_d3: d3=?=e3 expected=True got=True steps=484 29.5s stream=3968
  [BAD] G2_d4: d4=?=e4 expected=True got=TimeoutError: no halt after 600 steps steps=-1 38.3s stream=4191
  [BAD] G4_d6: d6l=?=d6r expected=True got=TimeoutError: no halt after 600 steps steps=-1 40.0s stream=4309
  [BAD] G4_d7: d6l=?=d7r expected=False got=TimeoutError: no halt after 600 steps steps=-1 40.8s stream=4321
  ```
  判读：d1/d2f/shadow/d3 步数与 f11_p1 **逐一相同**（135/133/172/484）——
  实例化对既有绿灯零扰动；d4 维持帽内合法慢（待任务 4 抬帽）。
  **d6/d7 由"快速 False / 快速 False"双双转为 Timeout@600**——与 F10-03
  spec1 时代 Timeout@600 形态吻合（spec1=全局折成 {1}，本修=精确实例化，
  二者对 below/brecOn/go 家族数据等价），证实 F11-03 预判：层级头对头一旦
  一致，False 生成臂不再触发，暴露出的是**更深处的图侧不收敛**。
  按 F11-03 登记的分支规则，进入图侧并案调查；d7 同步 Timeout 说明该环
  发生在"两侧同为 stuck Proj(go@{1}·) 的递归下降"处，尚未到判 False 的
  末端。全步 trace=f11_p7（guarded 5120，pid 1243706/1243707，跑动中）。

### 事故记录 12：F11 阵亡（新死因 Model request failed，~16:4x）与资产收编

**形状**：73min 后 harness error 原文 `Model request failed.`（模型 API 请求
失败，与 database is locked 不同族——环境事实登记：代理死因已见两族，均
客户端/网络层，非项目层）。005 末条 F11-04（16:34），f11_p7.log **16:35
自然跑完 rc=0**（124s，peak 3896MB），F11-05 判读未写。若 F11 复苏写盘让位 F12。

**F11 资产账（全在盘，F12 不许重做）**：
- 裁决执行完毕：_spec 回退落码（备份原文在 F11-01），d6/d7 恢复快速 False，
  不并案。
- **全量差分 2 分歧**（f11_p1_full.log 原文在 F11-02；轨迹 7→6→2）：
  剩 d4=帽内合法慢（648>600，待抬帽）+ d6=卡 009 最后真缺陷。C 组 lst 4/4 绿。
- d6 重定性（F11-03，翻案 c1 旧假说）：**非 stuck Proj restick 交付 bug**。
  病灶=测试侧注入常量的层级保真（brecOn@{1} 的 delta 值内 go@{LParam u}
  被折级洗成 go@{LZero}，与 d6r 具体层级 {1} 头对头不一致 → 图触发深降
  x-pi/infer 阶梯造出 `UnitT =?= Nat` 假 False）。F5-b03 的 ref-vs-graph
  分离判据在"数据含非法层级对"时无效——c1 备忘录要按此重写。
- 数据侧修复已落码（F11-04）：tests 内 use-site 实例化（`_instantiate_dump`
  等 5 个纯数据 helper，无写死常量名、不动点传播、唯一具体 tuple 才替换，
  等价 K/instantiate.cpp:248-254 的测试侧预演）；静态验证 f11_p5 过；
  零扰动实证=四绿例步数与 f11_p1 逐一相同（135/133/172/484）。
- **新暴露的真图侧缺陷**：实例化后层级头对头一致，False 臂消失，
  d6/d7 双双转 **Timeout@600**——卡死点在"两侧同为 stuck Proj(go@{1}·)
  的递归下降"（图侧第 0 次修复机会，F11 分支规则预告的并案对象）。
  探针数据=f11_p7.log 全文 75KB（rc=0）：尾窗 i=606-615 显示焦点在
  INFER/ST 阶梯上绕圈（I_LAMDOM/I_LAMSORT/I_SORTEM/I_LAMBODY/I_ARG 轮转、
  多处 *A-FLIP*、pend 恒空）——**F12 第一块骨头=判读 p7 全 trace 钉死
  这个 INFER 环的机器步**。图侧嫌疑区：WP7-A15 非承诺版 DE_PRJ
  （build_vm.py:206-209/3580-3585/4061+）与内核
  K/type_checker.cpp:1123-1138（lazy_delta_proj_reduction）/:503-508 的语义差。

---

## F12 任务书（总控 → 第十二任，2026-09-16 16:5x）

F12 = 卡 009 第十一任执行者。卡已到最后一里：**d6 图侧一处真修 + 抬帽 + 收口**。

1. 第一动作 = 005 追加 "## F12 段" 表头（≤10min 节拍）。自检
   `$PY -c "import lean_vm.build_vm"`（PY=/home/xkq/miniconda3/envs/train/bin/python）。
   方法学红线照旧（append 真值口径 drv.b.stream[-1]）。
2. d6 图侧修复（第一次图侧尝试；F11 数据侧修复保留不动）：判读
   f11_p7.log 全 trace，钉死 stuck Proj 递归下降的 INFER 环生成步；对照
   内核 type_checker.cpp:1123-1138/:503-508/:1216-1221 与图内 DE_PRJ 臂
   （build_vm.py:206-209/3580-3585/4061+）找语义差，最小修 + kernel 引用。
   修后 d6/d7 快速 True/False → 全量差分复核（guarded 5120，原文落段）。
   **图侧第 2 次仍修不好 → 停手把已试方案+trace 证据落段等裁**（红线）。
3. d4 抬帽：GRAPH_MAX_STEPS 600→~720（证据=F8-02 线性表，引用落段）；
   同一步核 d6/d7 修后步数帽内。**任何例不许靠帽转绿**：帽抬后若有新
   Timeout 例，须各自拿出合法慢证据（halt 步数<帽 + 判决对 oracle）。
4. 0 divergences 后收尾：c1 备忘录**按 F11-03 重定性改写**（缺口 #3=层级
   保真+图侧环，非 restick 交付形态）、c2 成文、ADR016 草案
   （docs/decisions/016-*.md 只写不实现）、v 收口（scratch --sparse 基线
   24914/2878/186892 → 引擎 34/34 → 20 套件 REGRESSION_CORES=0-5 →
   差分入 run_cpu_regression.sh 表评估）、VM_SPEC/KERNEL_COVERAGE B 行同步。
5. 机器/所有权条款照 F7/F10/F11 原文（可改名单同 F11；勿动用户 GPU 训练
   与 research 探针；pkill 前 pgrep -af）。

---

## F12 段（执行记录，2026-09-16 16:5x 派发，第十一任 F11 阵亡后首任）

**F12 = 卡 009 第十二任执行者**。死因预告：F11 死于模型 API 层，本段以 ≤10min 节拍落盘。

| 子任务 | 内容 | 状态 |
|---|---|---|
| F12-00 | 表头落盘 + 必读链（本文件 F11 段全文/tests 头注/卡 009） | 进行中 |
| F12-01 | 判读 f11_p7.log 全 trace，钉死 INFER 环机器步 | 未开始 |
| F12-02 | d6 图侧最小修（第 1 次尝试，kernel 引用齐）→ d6/d7 快速 True/False | 未开始 |
| F12-03 | d4 抬帽 GRAPH_MAX_STEPS 600→~720（F8-02 线性表证据）→ 全量差分 0 分歧 | 未开始 |
| F12-04 | c1 按 F11-03 重定性改写 + c2 成文 | 未开始 |
| F12-05 | ADR016 草案（TASK_WHNF proj 交付合同，只写不实现） | 未开始 |
| F12-06 | v 收口：scratch --sparse 重编译 → 34/34 → 20 套件 → 差分入回归表评估 → VM_SPEC/KERNEL_COVERAGE 同步 | 未开始 |

机器姿态：核 0-5、OMP=3、guarded 帽 4096-5120；`ps --sort=-rss` 已看过（下一条目补实测）。

### 事故记录 13：F12 阵亡（credit 耗尽，~17:03）——派发通道停摆，等充值

- 死因：harness error 原文 `credit insufficient balance: balance=0 required=4404`
  （模型账户余额打空，**硬阻塞**：所有子代理派发不可用，直至充值）。
- 寿命 11min，仅落本段表头（16:55）；零代码改动、零日志、无进程遗留。
  净损失 ≈ 0——F12 任务书（上表）与全部资产原样有效。
- **总控处置**：暂停派发；接任者（F13 或总控自办）从上表 F12-01 起，
  第一动作 = 追加 "## F13 段" 表头，其余按 F12 任务书原文（005「F12 任务书」节）。
- 环境事实累计：代理死因三族——database is locked（多任）、
  Model request failed（F11）、credit 耗尽（F12）；均客户端/账户层，
  项目侧资产零丢失（节拍落盘全程兜底有效）。

---

## F13 段（执行记录，2026-09-16 18:0x 派发，第十二任 F12 阵亡后首任）

**F13 = 卡 009 第十三任执行者**。继承：F11 数据侧 use-site 实例化在码保留
不动；全量差分基线=2 分歧（f11_p1_full.log）；d6/d7 实例化后双 Timeout@600
（f11_p6 原文在 F11-04），f11_p7.log 全 trace 已自然跑完 rc=0 待判读。
死因预告：项目已死 12 任（三族均客户端/账户层），本段以 ≤10min 节拍落盘。

| 子任务 | 内容 | 状态 |
|---|---|---|
| F13-00 | 表头落盘 + 必读链（本文件 F11 段全文/tests 头注/卡 009） | completed |
| F13-01 | 判读 f11_p7.log 全 trace，钉死 INFER 环机器步 | completed（根因=_lvl_eq 无 Max 分支，见 F13-01） |
| F13-02 | d6 图侧最小修（第 1 次尝试，kernel 引用齐）→ d6/d7 快速 True/False | 进行中（修①已落码：d7 已快速 False，d6 仍 Timeout，探针 ②在跑） |
| F13-03 | d4 抬帽 GRAPH_MAX_STEPS 600→~720（F8-02 线性表证据）→ 全量差分 0 分歧 | 未开始 |
| F13-04 | c1 按 F11-03 重定性改写 + c2 成文 | 未开始 |
| F13-05 | ADR016 草案（TASK_WHNF proj 交付合同，只写不实现） | 未开始 |
| F13-06 | v 收口：scratch --sparse 重编译 → 34/34 → 20 套件 → 差分入回归表评估 → VM_SPEC/KERNEL_COVERAGE 同步 | 未开始 |

机器姿态（18:08 实测）：`ps --sort=-rss` 前排全为 brave/zcode-cli（本会话
客户端进程），无本卡遗留求值进程、无用户 GPU 训练大进程在跑；核 0-5、
OMP=3、guarded 帽 4096-5120；日志 $HOME/logs/009F/（f13_ 前缀）。

### F13-01（18:2x-18:5x）f11_p7.log 全 trace 判读：INFER"环"的机器步钉死——真根因是 `_lvl_eq` 无 Max/IMax 分支

- 先纠偏：f11_p7 尾窗的 INFER/ST 阶梯本身**不是环**——同款阶梯在 cycle 1
  （i=134-235）与 d3 绿例里都有；"绕圈"的机器事实是 **DE_PRJ 假臂把整场
  比较重演了一遍**（cycle 2 与 cycle 1 同形、帧号全新），f8_p7 式状态环
  检测从未在 post-fix d6 上跑过。全 trace 结构判读（append 真值口径，
  log 619 行 i=1-615，rc=0 wall 124s peak 3896MB，600 步预算耗尽于
  cycle 2 半途）：
  1. **cycle 1（i=64-439）**：root DEFEQ@3178=Proj(P2,0,·)=?=Proj(P2,0,·)
     → proj_same → 子比较 @3181（go-spine，两侧同 term 位）→ 软 whnf delta
     展 go → @3259=App^4(Nat.rec@{Max(1,1)},·,·,·,tq)=?=同（V1=E2=2176，
     仅闭包 env 3197/3239 不同）→ 双 App 卡死 → sw_pi → PI_T@3308（i=133）
     → INFER 阶梯 i=134-235（infer_type(rec-app)；I_ARG 的 arg-vs-domain
     检查在 i=183 开出 DEFEQ@3418 `UnitT=?=App(Nat.below@{1}…)`，i=214
     收窄为 @3477 `UnitT=?=Nat`，**i=236 判 False**——这是玩具 PProd 约定
     下 below 见证 `F1s 0 UnitT.mk` 对声明域 @Nat.below 的必败检查，内核
     infer_type 不做 arg 检查、永不触此臂）→ 软失败标记 0/K0 级联
     （i=237-239：I_CHK→I_ARG→PI_TY 消费者）→ **PI_TY 无标记检测**
     （cg[PI_TY] build_vm.py:4152-4163 无条件推 INFER，与 :4215-4217 注释
     承诺的"at PI_TY the proof-irrel ST_SP decline"不符）→ i=240 对标记
     跑垃圾 INFER(0/K0) → i=241 PI_LVL → i=242 pl_fall → ST_SP——降落
     最终发生但绕了一圈垃圾步。i=243-247 ST_SP→sp_both_app→D_SP1 剥 4 参
     → i=248 头对 @3557=Const Nat.rec@{Max(1,1)}=?=Const Nat.rec@{同}
     （**V1=E2=2139 同 term 位，仅 env 异**）。i=249-250 @3557 首派发**
     未走 deq_const 真值快捷臂**，落入 deq_sw0 → 软 whnf 卡死 → sw_pi →
     PI_T（i=253）→ INFER 阶梯 i=254-435（infer Nat.rec 的巨型 Pi 类型，
     I_PIDOM/I_PIS1/I_PIL1/I_PIS2/I_PIL2 排序检查）→ **i=436 @3557 判
     A=0** → i=437 D_SPA → i=438 @3259 → i=439 @3181 逐级 A=0 解卷 →
     i=440 **DE_PRJ sink 收到假**。
  2. **DE_PRJ 假臂（build_vm.py:4061-4091 de_prj_f）**：按内核 ：1224 合同
     重发 deq_sw0 于原始对——但内核 ：1225-1227 有 `!is_eqp(t_n_n,t_n)||
     !is_eqp(s_n_n,s_n)` 守卫：**未变的 stuck 对不重派**，直接落终局链
     （app/eta/eta-struct/unit→False）。图侧无此守卫 → i=441-486 重软
     whnf 两侧（原样卡死）→ i=488 PI_T（V2=3178 root）→ i=489-615 root
     Proj 的 INFER 阶梯重演（cycle 2；i=570 @4246 同款 Nat.rec 全同对再现，
     i=595-615 PI_T→INFER 阶梯再现）→ 预算耗尽。cycle 1 ≈376 步，
     cycle 2 至截断已 175+ 步未完 → 任何 ≤600 帽内必 Timeout。
  3. **头对 @3557 为何不走 deq_const**：@3557 首派发时唯一可能的真值臂
     deq_const（build_vm.py:3544-3547：同 kind K_CONST + `tV0==sV0` +
     `_lvl_chain_eq(tV1,sV1)`）前两件 trivially 满足（同 term 位），排除法
     只剩 `_lvl_chain_eq`。其节点比较 `_lvl_eq`（:3510-3524）只处理
     KL_ZERO/KL_SUCC/KL_PARAM/KL_MVAR——**KL_MAX/KL_IMAX 无任何分支，
     连"同闭包即等"的位置捷径都没有**（:3495-3506 注释自称"compare
     unequal unless they are the same closure"，代码无此事）。Nat.rec 的
     层级链含 LMax(S(0),S(0)) → `_lvl_eq` 返 0 → deq_const=0 → 全同常量
     头被推进软 whnf/证明无关阶梯并判 False。内核对照：`is_equivalent`
     （K/level.cpp:517-520）`lhs == rhs || normalize == normalize`——深层
     结构相等，同构 Max 必真；:1196-1200 const/const 捷径随之返 True。
  - **结论（F13-02 修什么）**：病灶单点=_lvl_eq 对 KL_MAX/KL_IMAX 连恒等
    快捷都没有。最小修=在 _lvl_eq 顶部加位置恒等捷径 `_eq_expr(l,r)`
    （层级无 bvar、env 无关，同 env 槽=同层级项=内核深层结构相等，sound；
    对 Max 递归展开会 2^depth 爆电路，既有 sound-incomplete 决策保持不动）。
    修后 d6 路径：头对 deq_const 真快捷 → D_SPA 逐参 → @3259 True →
    @3181 True → DE_PRJ 真臂 commit → root True，DE_PRJ 假臂在语料内不再
    触发（d7=T=Proj vs S=App 走 proj_diff/deq_sw0 一趟终局链 False）。
    风险：参数对逐层 App 各付一趟必败 INFER 阶梯（~100 步/层），d6 总步数
    待实测，若 >600 再议。

### F13-02（18:5x-19:1x）图侧最小修①落码 + d6/d7 探针：d7 转快速 False，d6 仍 Timeout

- **修①落码**（lean_vm/build_vm.py `_lvl_eq`，:3510-3538 区域）：顶部加位置
  恒等捷径 `pos_eq = _eq_expr(l, r)`，三个 kind 分支（KL_ZERO/PARAM/MVAR/
  SUCC）全部改挂 `One - pos_eq` 门，和恒 ∈{0,1}（_select 契约）。Max/IMax
  子树递归保持不做（sound-incomplete 决策不动）。内核引据：
  K/level.cpp:517-520（is_equivalent：lhs==rhs 深层结构即真，无需 normalize）。
  import 自检 OK（numpy 2.5.2）。
- 探针 f13_p1_d67（guarded 4096，wall 201.3s peak 3839MB rc=0，
  $HOME/logs/009F/f13_p1_d67.log 原文）：
  ```
  G4_d6: d6l=?=d6r  oracle=True  graph=TimeoutError: no halt after 600 steps  52.9s
  G4_d7: d6l=?=d7r  oracle=False  graph=False  49.1s
  [mem-guard] wall 201.3s peak RSS 3839MB rc=0
  ```
  判读：**d7 由 Timeout@600 转快速 False（判决对 oracle）**——修①方向正确
  （d7 的比较链里同槽层级对已快捷放行，终局链一趟走完）。**d6 仍
  Timeout@600**——True 路径上还有堵点。旁证：d1/d2f/d3/d4 未跑（本探针只
  跑 d6/d7），零扰动性留全量差分复核。
- 下一步：f13_p2_d6cycle（guarded 4096，d6 长预算 3000 步 + f8_p3 式
  state-6 元组环检测，真值口径 drv.b.stream[-1]）分辩"合法慢 vs 仍有环"，
  环窗带 D 帧解码。

### F13-02 续（19:1x-19:2x）环检测探针三连假阳性后改抽样语义签名

- p2（state-6 元组，guarded 4096）wall 169s RSS 4102>cap 被 kill，无重复
  报告；p3（首个 DEFEQ 帧解码键）键恒为埋底的 root 对（d6l=?=d6r）→ 常量
  键假阳性；p4（全 D 链签名，位置剔除）报 gap=1 假阳性（步 0→1 同链属正常
  连拍节拍）。三者教训：环键既要位置无关，又要滤掉"同一帧多步处理"的合法
  同链期（f11_p7 单帧可占 ~376 步）。
- p5（裸跑 3000 步+尾部 40 环窗）：guarded 5120，wall 222.8s RSS 5123MB
  被 kill，未 halt（$HOME/logs/009F/f13_p5_d6plain.log）。RSS 增长系 driver
  每步复制 lookup_history 的固有开销，不能据此判环。
- 进行中：p6 = 每 10 步抽样解码 D 链语义签名，只报 gap≥100 的重现（假循环
  周期 ~376 步会命中），预算 1200 步，guarded 6144。

### F13-02 续（19:2x-19:4x）d6 判定为语义增长环，环体入 below/go 展开

- p6（每 10 步抽样语义签名，gap≥100 报重现，1200 步，guarded 6144，
  wall 212.4s peak 4848MB rc=0，$HOME/logs/009F/f13_p6_d6sample.log）：
  ```
  NO HALT, NO REPEAT within 1200 steps (120 samples)
  total stream len 5526
  ```
- p7（每 25 步 D 链剖面，1500 步，guarded 7168，wall 246.7s peak 5571MB
  rc=0，$HOME/logs/009F/f13_p7_d6profile.log）：
  ```
  step  125 depth 7  Q=Nat.rec spine (levels LMax(S0,S0))
  step  143 depth 11 top=INFER motive-Lam, 2nd ST Nat vs P2
  step  184-197: WHNF Nat.below-app 进入；NAT/WALK 上一卡死 rec-app
  step  1225 depth 27 Q=Nat.rec spine (levels LSucc(LMax(S0,S0)))
  step  1500 depth 12 Q=P2 =?= P2
  NO HALT within 1500 steps
  ```
  判读：链深 5→16→20-28 上行、Q 帧数 3-5→16-19、Nat.below/Nat.rec 对在
  越来越深的层级结构上持续新生。p6 无重现的原因=**语义增长环**（每周期
  产生更深新结构，键必然漂移；f7_p11 教训的语义版）。d6 修①后非合法慢。
- p8（只在链深创新高时打点，500 步，guarded 4096，wall 152.8s peak
  3686MB rc=0，$HOME/logs/009F/f13_p8_d6growth.log）环体钉到
  steps 143-197：INFER 阶梯（软 proof-irrel）→ WHNF `Nat.below`-app →
  NAT/WALK 卡死 rec-app（levels LSucc(LMax(S0,S0))），下一增长事件 step 489
  （gap ~292 步/周期，深度 +2）。step 489 INFER 的对=Pi(Nat,Nat)（F1s 型）。
- 内核对照：is_def_eq_core 对同头 App 脊逐参比较（K/type_checker.cpp:1229+），
  同 const 头在 :1196-1200 快捷 True——**内核全程不 infer 类型、不碰
  Nat.below**（brecOn/go 卡死 major 的 rec-iota 拒绝后 proj 不剥，
  :503-508）。图侧却在软 INFER/类型域比较里展开 below。
- 进行中：p9 = steps 180-292 逐步 STATE trace（真值 drv.b.stream[-1]），
  钉死推 below 帧的具体 dispatch 臂，作为修②（第 2 次图侧尝试，最后一次）
  的靶点。

### F13-02 续（19:5x-20:3x）修②（软 I_ARG 跳过）两轮失败，回滚，停手等裁

- 修②依据（内核钉死）：infer_type = infer_type_core(e, infer_only=true)
  （K/type_checker.cpp:360-362）；infer_app 的 arg-vs-domain is_def_eq 只在
  !infer_only 分支（:174-188），infer_only 脊走（:189-205）不查。软 INFER
  （F2=1，proof-irrel 链）是 infer_type 对应物 → 其 I_ARG 检查超内核；真
  dump 的 F_ty bh 域 = @Nat.below motive t'，其 whnf 每周期在新结构上重入
  INFER 阶梯 = d6 增长环入口。
- 修②落码 v1：I_ARG 臂按 soft_flag 跳过 fr2 发射 + 强制判决 1。
  p8b（增长探针复跑）：增长事件止于 depth 11（修前到 18），below 入口消失
  → 门生效。p7b（剖面复跑）：step ~175 起 D 链变空（depth=0）仍每步 +1
  token——D=c2 落到本步 STATE token，周期-1 活锁（:5886-5888 注释同款，
  fr2 抑制破坏 c1=POS+1/c2=POS+2 固定地址算术）。
- 修②落码 v2（补 D=i_arg_skip→c1）：p10b d6 仍 Timeout@1200 且
  **d7 回退 False→Timeout**（软 INFER 验证式失败级联正是 d7 下降依托；
  内核 proof-irrel 的 is_prop 门 pl_prop 前的失败decline 语义被跳过改写）。
- 判定：**修②失败（第 2 次图侧尝试用尽）→ 按任务书红线停手等裁**。
  回滚修②两处（I_ARG 块 + em_frame2_m2 门），恢复 fix① 唯一改动。
- 回滚验证 p10d（600 步套件口径，guarded 6144，wall 276.4s peak 4769MB
  rc=0，$HOME/logs/009F/f13_p10d_d67_600.log）：
  ```
  G4_d6: d6l=?=d6r  graph=TimeoutError: no halt after 600 steps  55.8s
  G4_d7: d6l=?=d7r  graph=False  108.7s
  ```
  = fix① 状态精确恢复（d7 快速 False，d6 Timeout 残留）。
- 裁决请求材料（已备）：已试方案清单 + p6/p7/p8/p9 日志（$HOME/logs/009F/）
  + 内核引用。核心矛盾：软 INFER 的验证式 arg 检查（ref_vm _proof_irrel
  try/except 语义的图侧对应物）既被 d7 的 False 下降依赖，又是 d6 增长环
  入口——二者绑在同一臂上，最小修不能同时保住。

### 事故记录 14：F13 阵亡（Provider rejected，2h33m 全链最长寿命）+ 死前全量差分已出

- 死因第四族：harness error 原文 `Provider rejected the model request.`
  （20:4x，9212s）。005 末条 F13-02 续（20:35）+ **f13_diff_full_fix1.log
  20:39 已完整跑完 rc=1**（修①后全量差分，下条裁决引为其原文）。
- **修①后全量差分原文（f13_diff_full_fix1.log，499s peak 4047MB）**：
  11 例中 9 绿（A 段 OK、B 组 d1/d1_4/shadow/d3/d7 绿、C 组 lst 4/4 绿），
  剩 2 分歧 = d4（帽内合法慢，648>600，F8-02 线性表）+ d6（Timeout，
  卡 009 唯一残留真缺陷）。d7 转绿坐实，修①零回归。
- build_vm.py 现状已总控核验：修①（_lvl_eq 恒等捷径 :3523-3536）在位、
  修②已回滚干净、import OK。
- ADR016 草案已见于 docs/decisions/016-whnf-proj-rawfield-contract.md
  （F4 时代 05:34 落，非 F13 产物；F13-05 任务=核对补完而非新建）。

---

## 总控裁决（2026-09-16 20:5x，应 F13 停手等裁请求）

1. **修①批准保留**：全量差分复核通过（上条原文），d7 转绿、零回归、
   内核引据 K/level.cpp:517-520 成立。`_lvl_eq` 恒等捷径为卡 009 正式改动。
2. **d6 第三次图侧尝试批准，但换简报**（同一简报两败后按审核标准换法，
   不是盲改第三次）：靶点从"I_ARG 臂怎么跳"改为**"软 INFER 通道对齐内核
   infer_only 脊语义"**——K/type_checker.cpp:360-362（infer_type=
   infer_type_core(e, infer_only=true)）、:189-205（infer_only 脊**不查
   arg-vs-domain**）、:174-188（该检查只在 !infer_only 分支）。
   - 路线 (a)（优先）：软链专用新臂（新 cont-id/新发射通道），旧 I_ARG
     硬语义不动——协议扩展原则（AGENTS 对 step_driver 同款）。
   - 路线 (b)：I_ARG 发射结构不动、仅按 soft 标志改发射条件。
   - 两条**禁令**（F13 两败的教训，违者即停）：不得破坏 c1=POS+1/c2=POS+2
     pend 地址算术（v1 教训：D 落 STATE token=period-1 活锁）；不得改写
     decline 级联语义（v2 教训：d7 的 False 下降依托失败级联）。
   - 开工前置：先写 d7-only 小探针，预测新语义下 d7 的下降路径（内核手推：
     proof-irrel 检查用 infer_type 结果类型是否 prop，不做 arg 检查 →
     App 类型=codomain，两侧类型非 proof → 落终局 False），探针证实后动码。
3. **第 3 次失败即停**：写 ADR（软 INFER 通道与内核 infer_only 的语义差
   =架构级已知缺口），d6 列卡 009 显式 open 项（verifier 第 1 条不勾、
   Handoff 记 NOT-VERIFIED d6 一行），**链条照常推进不阻塞**——d6 是
   brecOn 通用 iota 一角，G(010)/H(011) 不依赖它；其余成果（修①+extras
   +et_sfall+直发+实例化，11/12 例绿）按流程收口落库。
4. **d4 抬帽 720 无条件执行**（合法慢证据齐：F8-02 线性表 + p11 自然
   halt@648 判决对 oracle；帽=harness 资源帽非判据）。

## F14 任务书（总控 → 第十四任，2026-09-16 20:5x）

1. 第一动作 = 005 追加 "## F14 段" 表头。自检 import
   （PY=/home/xkq/miniconda3/envs/train/bin/python）。
2. d6 第三次尝试（按裁决 2 的靶点/路线/禁令/前置探针执行）。
   修绿 → 全量差分（guarded 5120）应 1 分歧（d6 转绿后仅剩 d4 帽内）。
   失败 → 按裁决 3 停手路线执行（ADR+open 项），不许再开第四次。
3. d4 抬帽 GRAPH_MAX_STEPS 600→720（F8-02 证据引用落段）→ 全量差分
   终态：**0 divergences**（d6 修绿情形）或 1 分歧+d6 KNOWN-GAP 注记
   （停手情形）。期望值真 lean 现跑，红线照旧。
4. c1 备忘录按 F11-03+F13-01 重定性改写（缺口 #3 终审=层级保真+F11 数据侧
   修复+_lvl_eq 恒等+软 INFER 语义差三层）、c2 成文（素材链 F9-03/F10-01）。
5. ADR016 核对补完（文件已在 docs/decisions/016-*.md，F4 时代草案）；
   若走停手路线另落软-INFER-ADR。
6. v 收口：scratch --sparse（基线 24914/2878/186892 报增量）→ 引擎 34/34 →
   20 套件（REGRESSION_CORES=0-5）→ 差分入 run_cpu_regression.sh 表评估
   （若 d6 open，测试文件内 d6 用例标 xfail+KNOWN-GAP 注记，不许删例）
   → VM_SPEC/KERNEL_COVERAGE B 行同步。
7. 机器/所有权/方法学条款照 F12/F13 任务书原文。

---

## F14 段（执行记录，2026-09-16 21:0x 派发，F13 阵亡（Provider rejected）后首任）

**F14 = 卡 009 第十四任执行者**。继承：修①（_lvl_eq 恒等捷径）批准保留在码；
全量差分基线=2 分歧（f13_diff_full_fix1.log：d4 合法慢 648>600 + d6 Timeout）；
d7 已绿、lst 4/4、零回归。修②两败教训在案（跳 I_ARG 破 pend 算术 / 强制成功
破 decline 级联）。本段以 ≤10min 节拍落盘。

| 子任务 | 内容 | 状态 |
|---|---|---|
| F14-00 | 表头落盘 + 必读链（005 F13 段+裁决+任务书 / tests 头注 / 卡 009） | completed |
| F14-01 | d6 前置探针：d7-only 小探针预测软 INFER 对齐 infer_only 脊后 d7 下降路径 | pending |
| F14-02 | d6 第三次图侧修（路线 a 优先：软链专用新臂；禁令两条）→ d6 True / d7 绿 | pending |
| F14-03 | d4 抬帽 GRAPH_MAX_STEPS 600→720（F8-02 证据落段）→ 全量差分 0 或 1 分歧 | pending |
| F14-04 | c1 备忘录按 F11-03+F13-01 重定性改写 + c2 成文（F9-03/F10-01） | pending |
| F14-05 | ADR016 核对补完；若停手路线另落软-INFER-ADR | pending |
| F14-06 | v 收口：scratch --sparse → 34/34 → 20 套件 → 回归表评估（仅加行）→ VM_SPEC/KERNEL_COVERAGE B 行同步 | pending |

机器姿态（21:0x 待实测后补记）：核 0-5、OMP=3、guarded 帽 4096-6144；
日志 $HOME/logs/009F/（f14_ 前缀）。

### 事故记录 15：F14 阵亡（计费账户冻结，3.5min，仅表头）——派发通道二次停摆

- 死因第五族：harness error 原文 `计费账户已被冻结`（20:52，213s）。
  F14 仅落表头（20:49），零代码零日志零进程；净损失≈0，F14 任务书
  （本文件上方总控裁决节之后）原样有效。
- **处置**：暂停派发，等用户解冻账户/换 API 后说"继续"，总控原样重派
  （接任者第一动作 = 追加 "## F15 段" 表头，任务=裁决 2/3/4 + F14 任务书）。
- 死因五族累计：database is locked、Model request failed、credit 耗尽、
  Provider rejected、账户冻结——全部客户端/账户层，项目侧资产零丢失。

---

## F15 段（执行记录，2026-09-16 21:2x 派发，F14 阵亡（账户冻结）后首任，账户已恢复）

**F15 = 卡 009 第十四任有效执行者**（F14 仅落表头零改动，编号顺延）。
继承：修①（_lvl_eq 恒等捷径 :3523-3536，总控已批准保留）在码；全量差分
基线=2 分歧（f13_diff_full_fix1.log：d4 合法慢 648>600 + d6 Timeout）；
d7 绿、lst 4/4、零回归。修②两败教训在案（跳 I_ARG 破 c1/c2 pend 地址
算术=period-1 活锁 / 强制成功改写 decline 级联致 d7 坏）。本段以 ≤10min
节拍落盘，长任务探针起进程后立即落盘再等结果（并发可能触发账户冻结）。

| 子任务 | 内容 | 状态 |
|---|---|---|
| F15-00 | 表头落盘 + 必读链（005 F13 段+裁决+F14 任务书 / tests 头注 / 卡 009） | completed |
| F15-01 | d6 前置探针：d7-only 小探针预测软 INFER 对齐 infer_only 脊后 d7 下降路径（内核手推：App 类型=codomain，两侧类型非 proof → 终局 False） | pending |
| F15-02 | d6 第三次图侧修（路线 a 优先：软链专用新臂；禁令：不破 c1=POS+1/c2=POS+2、不改 decline 级联）→ d6 True / d7 绿 | pending |
| F15-03 | d4 抬帽 GRAPH_MAX_STEPS 600→720（F8-02 线性表证据）→ 全量差分 0 或 1 分歧 | pending |
| F15-04 | c1 备忘录按 F11-03+F13-01 重定性改写 + c2 成文（F9-03/F10-01 素材） | pending |
| F15-05 | ADR016 核对补完；若停手路线另落软-INFER-ADR | pending |
| F15-06 | v 收口：scratch --sparse（基线 24914 dims/2878 lookups/186892 nnz 报增量）→ 34/34 → 20 套件（REGRESSION_CORES=0-5）→ 回归表评估（仅加行）→ VM_SPEC/KERNEL_COVERAGE B 行同步 | pending |

机器姿态（21:25 实测）：`ps --sort=-rss` 前排=python3(1352067, 用户侧)/
zcode 客户端链 + pt_data_worker×4（用户 GPU 训练伴生，勿动勿杀），无本卡
遗留求值进程。核 0-5、OMP=3、guarded 帽 4096-6144；日志 $HOME/logs/009F/
（f15_ 前缀）。PY=/home/xkq/miniconda3/envs/train/bin/python。

### F15-00（21:3x）必读链完成 + F15-01 探针已起（起进程先落盘）

- 必读链完成：005 F13 段全文/事故 14/15/总控裁决/F14 任务书、tests 头注、
  卡 009。build_vm.py 关键区已读：soft_flag 定义 :303-310、I_FN/I_PI/I_ARG/
  I_CHK 块 :3103-3229、PI_T/PI_TY/PI_LVL/PI_D/ST_SP 链 :4147-4243、INFER
  dispatch :5192-5364、cont-id 表 :186-220（已用到 68=CK_G1，g dict
  range(1,69)）。
- **内核 infer_app 原文核到**（/home/xkq/lean4/src/kernel/
  type_checker.cpp:172-205）：`infer_only=true` 脊（:189-205）只
  `infer_type_core(f, true)` 推 fn 型、随后逐层 `binding_body` 剥 Pi 并
  instantiate_rev——**不推 arg 型、不做 is_def_eq(a_type, d_type)**；
  arg-vs-domain 检查仅在 `!infer_only`（:174-188）。裁决 2 的靶点与手推
  与源一致。
- 修①后 d6/d7 的机器路径重判读（f13_p9/f13_p8 证据）：d6 增长环入口 =
  软 INFER（PI_T/PI_TY/pl_prop 发射，fr2_F2=One）阶梯内的 I_ARG arg-vs-
  domain DEFEQ（硬 DEFEQ 帧，F2=dom_env），其域侧 whnf（Nat.below 展开）
  每周期在更深层级结构上重入软 INFER；d7 现行 False 下降依托同臂的失败
  级联（I_CHK soft-fail → A=0 标记 → 消费者级联 → 终局链）。
- **路线 (a) 设计已定**（落码前待 F15-01 证实）：新 cont-id `I_ARG_S=69`
  （g dict 扩 range(1,70)）；I_PI 块 `fr1_F2` 按 soft_flag 选 I_ARG_S/
  I_ARG（旧 I_ARG 硬语义一字不动）；I_ARG_S 块 = I_ARG 的失败通道
  （i_arg_fail A=0 标记投递 + i_pi_soft ensure_pi 软投递）原样保留 +
  成功通道 = I_CHK 判 True 的成功路径（i_more link1/ST@I_PI/WHNF fr2/
  D=c3；完成 E=1 D=frV2 交付 codomain+link）——即内核 infer_only 脊
  "剥完 Pi 直达 codomain"。发射结构与 I_CHK 成功路径逐字段同构，不碰
  c1/c2/c3 约定；d7 的 A=0 级联通道不动。
- F15-01 探针 f15_p1_d7trace.py 已起（guarded 4096，核 0-5，
  $HOME/logs/009F/f15_p1_d7trace.log）：d7-only 逐步 trace，过滤打印
  ST[I_ARG/I_CHK/PI_T/PI_TY/PI_LVL/PI_D/ST_SP/ST_ET/IP_*] 与
  INFER/DEFEQ 帧头，钉现行 d7 下降的事件序列。

### F15-01（21:4x）d7 前置探针判读：预测证实——现行下降走 arg-vs-domain 失败级联，修后走 pl_fall，两者同落 ST_SP

- 探针原文（f15_p1_d7trace.log，wall 164.4s peak 3799MB rc=0）：
  `HALT at step 553 verdict A=0  (52.9s)`——d7 快速 False（对 oracle），
  与 f13_p10d 一致。
- 现行 d7 下降事件序列（trace 钉死）：
  1. 软 INFER 阶梯（PI_T i=128 发射，infer d6l 侧 Proj→go-app）逐层
     I_ARG：i=150/163/171 发射 arg-vs-domain DEFEQ；i=171 的检查两侧
     恰为同形 Pi(Nat, below-app) 对 → 域侧 whnf 展 below（i=175-210，
     ~60 步）→ 卡死 rec-app 对 → 二级 PI_T（i=235）→ 二级软 INFER →
     **i=255 I_ARG → i=259 DEFEQ Sort(LMax(S1,S1)) vs Sort(LSucc(LZero))
     失败** → i=260 判 0 → i=261 I_CHK(A=0) 软失败 → i=262 PI_TY(A=0) →
     i=263 垃圾 INFER(0/K0) → i=264 PI_LVL(A=0) → i=265 ST_SP——A=0
     级联 + F13-01 记录的 PI_TY 无标记检测垃圾步，全部再现。
  2. **修后通道已在 trace 中现形**：i=334 PI_TY(A=300=Const Nat，一次
     完整走完的软 infer) → i=336 PI_LVL(A=239=Sort) → pl_prop=0 →
     i=337 ST_SP——软 infer 完整完成 → 类型非 toy-Prop → pl_fall →
     ST_SP，正是修①后所有软 infer 的统一下降形态。i=339/340 ST_ET/
     ST_ES 终局链随后。
  3. 结论：现行 d7 False 依托的 arg-vs-domain 失败级联（i=259-265）与
     修后 pl_fall 通道（i=334-337）**落在同一 ST_SP 继续链**；内核手推
     （infer_only App 类型=codomain、非 proof → 终局 False）与 trace
     实证一致。修后 i=174-265 整段（below 域 whnf + 二级 proof-irrel +
     失败级联，~90 步）整体消失，d7 应更快且判决不变。
- **动码批准条件成立**（裁决 2 前置探针已证实）。路线 (a) 落码 =
  新 cont-id I_ARG_S=69：I_PI 按 soft_flag 选臂；I_ARG_S 失败通道
  （A=0 标记 + ensure_pi 软投递）复用 I_ARG 既有机制（门扩
  cg[I_ARG]+cg[I_ARG_S]），成功通道复用 I_CHK 判 True 成功路径
  （门 cg[I_CHK]+i_args_ok，i_args_ok 排除两失败通道）；发射计数
  i_more: link1+fr1(ST@I_PI)+fr2(WHNF) D=c3 / done: link1 无帧
  D=frV2——与 I_CHK 成功路径逐字段同构，c1/c2/c3 约定不动。

### F15-02（21:5x）修③落码（6 处编辑）+ p2 首测：d7 保持 False，**d6 仍 Timeout@600**——环未断，需增长探针定位剩余入口

- 落码 6 处（全在 lean_vm/build_vm.py）：I_ARG_S=69 常量+注释、g dict
  range(1,70)、I_PI fr1_F2 soft 选臂、i_arg_fail/i_pi_bad 门扩
  cg[I_ARG_S]、i_args_ok 判别式、I_CHK 成功路径门 chk_ok=cg[I_CHK]+
  i_args_ok（link1/em_link1/A/B/C/F/fr1_*/fr2_V2/E/D 全套）+ m2_chk 加
  reglu(i_args_ok, i_more)。import+build OK（I_ARG_S=69）。
- p2（f15_p2_d67fix3，600 步套件口径，d7 直跑无护栏、d6 同批）：
  ```
  G4_d6: d6l=?=d6r  graph=TimeoutError: no halt after 600 steps  55.8s
  G4_d7: d6l=?=d7r  graph=False  73.6s
  ```
  判读：**d7 判决不变（False 对 oracle）**——修③未破坏下降；**d6 仍
  Timeout**——软 I_ARG_S 未剪断环。假说：环的 INFER 阶梯在 I_ARG 点
  读到的 soft_flag=0（阶梯非软）或环体另有入口（硬 I_ARG / DEFEQ 自身
  机械）。下一步：p3 = d6 增长探针（f13_p8 式链深新高打点）+ 步级
  trace 定位修③后仍在推 below 的 dispatch 臂。

### F15-02 续（22:0x）p3 判读：软路由零漏网（MISS=0），残余环向量=软 I_PI 的 **arg 推断本身**——内核 infer_only 脊根本不推 arg

- p3 原文（f15_p3_d6growth.log，guarded 4096，wall 152.3s peak 3830MB
  rc=0）：`NO HALT within 600 steps, final depth 20`，**MISS total 0**
  （ST[I_ARG] 挂软 INFER 的漏网=0，I_ARG_S 发射 23 次——修③机械正确）；
  D 头直方图 WHNF 217 / WALK 99 / INFER 96 / NAT 45 / DEFEQ 23 /
  ST:I_ARG_S 23 / PI_T·PI_TY·PI_LVL·ST_SP 各 3。
- 增长事件 steps 143-219（depth 11→20）：D 链上叠的是
  INFER(raw(2150..2169))（**token 位次逐周期递增=新结构**）+
  ST[I_LAMDOM/I_LAMBODY/I_ARG_S]——软 infer 阶梯在逐层下钻 motive Lam
  体/ witness arg 的新建结构。arg-vs-domain DEFEQ 已被修③剪掉
  （DEFEQ 仅 23 次），但 **I_PI 的 fr2 TASK_INFER(arg) 还在**：软阶梯
  仍对每个 arg 跑完整 infer（motive 体 → P2.mk app → below witness →
  下一层 below），这就是残余增长环。
- 内核对照（type_checker.cpp:189-205 原文已核）：infer_only 脊
  `infer_type_core(f, true)` 只推 fn 型，随后纯 `binding_body` 走 Pi 链
  + instantiate_rev——**从头到尾不对任何 arg 调 infer_type**。图侧软
  I_PI 推 arg = 超内核第二处。
- **修③ stage-2 设计**（I_ARG_S 臂保留为层循环 workhorse，不报废）：
  软 I_PI 不再发射 arg-infer，改为直连内核脊形状——同一发射步内
  link(arg1)（V0=paV0，P=focus 体的 body_env，D=ldepth）+
  ST[I_ARG_S]（V1=SA=f_type 位，X=c1=link，E2=paV2=余链）+
  fr2=TASK_WHNF(f_type 体 under link) 交付到 c2，D=c3；I_ARG_S 的
  i_args_ok 成功路径原样续层（link 下一 arg、WHNF 下一体）；链空 done
  路径 B=frX（累积 link 链）不补 link（I_CHK done 的 B=c1 语义保留）；
  ensure_pi 检查加 focus 侧门 i_pi_bad_pi（读 sk3——首个 I_PI 的
  ST.V1=0，frV1 侧 tK 不可用），失败走既有 i_pi_soft 投递通道
  （decline 级联不动）。发射计数 link+frame+frame2=c1/c2/c3 与 I_CHK
  成功路径同构，c1/c2/c3 约定不动。
| F15-07 | 22:4x | 修③ stage-2 落码（4 处编辑，build OK 76 outputs）：①pi_soft 块改为 pi_walk 门（sk3 的 Pi 门内含，非 Pi 不发射 link/payload，失败走 i_pi_soft）；②i_args_ok 删除，换 i_args_notpi（resume 上 focus 非 Pi 且还有 args → 软失败通道）+ i_pi_soft = reglu(i_pi_bad+i_pi_bad_pi, soft_flag)+i_args_notpi；③chk_ok 回归 cg[I_CHK] 纯硬链；④新 I_ARG_S resume 块（args_walk = cg[I_ARG_S]·i_more·pi_pi_k：link(paV0, P=pi_bodyE)+A_c=pi_bodyP=v1_(SA)+ST[I_ARG_S]+WHNF fr2, D=c3，与 pi_soft 同构；args_done = cg[I_ARG_S]·¬i_more：交付 (SA,SB) 原样 E=1 D=frV2，无 link 无 frame）；m2_chk = reglu(cg[I_CHK],i_more)+args_walk。**关键修正（相对 F15-02续 设计）**：resume 的剥皮目标是 focus 的 body（v1_(SA)），不是 tV1——resume 时 ST.V1 还是上一层 pi，tV1 落后一层会错位 de Bruijn；pi_bodyP/pi_bodyE 是状态解引用表达式，在 I_PI step 和 resume step 各自按当时 focus 求值，同一表达式两处复用。发射计数 link+frame+frame2=c1/c2/c3 与 I_CHK 成功形同构，c1=POS+1/c2=POS+2 不动；decline 级联未动。下一步：p4 探针（d6/d7 600 步）验证 d6=True/d7=False。 |
| F15-08 | 00:5x | **修③ 判读：d6 未转绿 → 依裁决 3 停手（无第 4 次）**。p4b（link 旗标被 I_CHK 块 `em_link1_c = chk_ok` 重赋值抹掉 → 软 I_PI 只发 2 帧，D=c3 指到状态 token → s138 起 period-1 活锁）已修：`em_link1_c = chk_ok + pi_walk`。p4c 暴露 args 链 off-by-one（args_done 错用 paV2=0，链头最后一个 arg 未消费）已修：`args_more = _geq_expr(frE2, One)`。修后 p4d：**d7=False ✓**（路径 = p1 预测形：软脊走完 → proj-infer 消费链 → IP_PEEL/PI_LVL 失败 → A=0 → PI_TY ST_SP decline → 卡对链 → False），**d6=Timeout ✗**。p9b d6 全程 trace（600 步）证实环不在这条软脊里：软 I_ARG_S 走层每次尝试 2-4 步干净终止（s139-143 形），环 = 卡对链反复 PI_T 尝试（s134/s185/s316/s426/s533，结构逐轮加深）。机制已定位：go-pair 脊剥（s201-204 头对 2149/2149 refl True ✓）到 arg 对 (2154,3197) vs (2154,3239)——**同一 pos 不同 env 根**（d6r 原 go vs d6l delta 展开建的 go），refl 快道不可用，DEFEQ 比较内的 WHNF 展开 below 族（s207-240：20+ 步结构走查、新 PProd/bvar 跳转）不粘住；内核 `Nat.brecOn.go t F := Nat.rec ⟨F 0 unit,unit⟩ (fun n ih => ⟨F n.succ ih,ih⟩) t`（真 lean #print 实测）比较 go tq F1s vs go tq F1s = 同常量脊比对即 True，从不展开 below。**结论：修③（软 INFER 内核脊对齐）正确且保留（d7 实证），d6 残环在卡对链 env 根分歧比较的 below 展开，超出本卡第 3 次尝试授权 → 停手路线：软-INFER-ADR + d6 xfail+KNOWN-GAP + verifier 第 1 项不勾 + Handoff NOT-VERIFIED。** |
| F15-09 | 01:0x | 停手路线落地 ①②：①`tests/test_brec_drec_iota_vs_lean.py` 增 KNOWN_GAPS 注册表（G4_d6 条目：env 根分歧 go-pair arg 的 below 展开环，F13-02/F14 fix2/F15 fix3 三次未闭合，裁决 3 无第 4 次）+ run_group() 接线：gap 命中且 graph≠oracle → `[XFAIL-KNOWN-GAP]` 行、**不计 divergence**；gap 命中且 graph=oracle → `[XPASS]` 且**计入 fails**（registry 必须摘除，双向都不许静默漂移）。②裁决 4 无条件执行：GRAPH_MAX_STEPS 600→720（第 64-67 行，注释引 005 F8-02 线性步数表：d4 引擎侧可完成、600 是 Python 侧墙钟不足）。py_compile SYNTAX_OK。下一步：F15-03 全量差分（run_mem_guarded 5120，cores 0-5），预期 0 divergence 或 1 divergence+d6 KNOWN-GAP。 |
| F15-10 | 01:1x | 停手路线落地 ③④：③F5-c1 备忘录增"F15 终局层"（四层定谳：F14 fix2 失败→裁决 2 新简报第 3 次=I_ARG_S 内核 infer_only 脊→d7 实证 False 保留→d6 残环根因=go-pair 实参同 pos 异 env 根的 below 展开环、内核同常量脊比对从不展开 below（#print 原文）→三次未闭合、裁决 3 停手=KNOWN-GAP+ADR 018，出路=ADR 017 缓存层）；F5-c2 备忘录增"F15 收口注"（反模式正反两用：d4 抬帽走 F8-02 合法慢证据路线；d6 是增长环不靠抬帽）。④ADR 018 建档 docs/decisions/018-soft-infer-spine-and-d6-known-gap.md（软脊 I_ARG_S=69 依据 K/type_checker.cpp:189-205 vs :174-188、d7 验证、d6 停手、KNOWN_GAPS 双向不漂移、后续=缓存层）；ADR 016 复核注（合同未被动、DEFEQ 通道结论成立、引用行号核对 §11.15:1069/§11.16:1104/§11.17:1165/§11.18:1194/§8:236、证据 /tmp/probe009F 与 f5_* 21 文件在位，A/B/C 仍待总控）。全量差分跑中（guard pid 2357790 / child 2357791，cap 5120，cores 0-5）。 |
| F15-11 | 01:2x | **F15-03 完成：全量差分 OK（0 计 divergence），542s，guard 峰值 4120MB rc=0**。d4 抬帽生效（G2_d4 PASS@720）；d6 XFAIL-KNOWN-GAP（graph=TimeoutError: no halt after 720 steps，不计 divergence）；d7/d1/d2f/d5r/d3/eL1/eL2/eL3/eL3_neg 10 例全 PASS。账面 2 分歧（d4+d6）→ **0**（d4 闭合+d6 xfail）。原文：`$HOME/logs/009F/f15_diff_full.log`。差分期间并行完成 F15-04/05（c1 终局层、c2 收口注、ADR 018 建档、ADR 016 复核注）。下一步 F15-06 v 收口：scratch 编译→34/34→20 套件→回归表→VM_SPEC/KERNEL_COVERAGE 同步。 |
| F15-12 | 00:5x(09-17) | v 收口 ①：scratch 稀疏编译 rc=0（wall 29.8s，峰 632MB）`model/step_vm_009_scratch.sbin`（18,869,498B）：**dims 25,930（基线 24,914，+1,016）/ lookups 2,898（基线 2,878，+20）/ nnz 192,405（基线 186,892，+5,513）**；114 层、d_model=6246、sum(H_li)=2920。增量来源=I_ARG_S 软脊（新 cont id 69 的微步电路 + 软 I_PI focus 门）。 |
| F15-13 | 01:0x(09-17) | v 收口 ②：**`SBIN=$PWD/model/step_vm_009_scratch.sbin scripts/verify_engine_vs_refvm.py` → `=== H3 engine vs RefVM: 34/34 verdicts correct ===`，argmax vs softmax streams identical: 34/34，known-value checks: 3/4（既有 succ_zero 已知 BAD 例，非回归）**。guard rc=0，wall 275.5s，峰 163MB。原文 `$HOME/logs/009F/f15_engine34.log`。 |
| F15-14 | 01:1x(09-17) | v 收口 ③：20 套件回归启动（`PYTHON=miniconda OMP=3 REGRESSION_CORES=0-5 bash scripts/run_cpu_regression.sh`，guard pid 2375341，runner 内 engine_vs_refvm 套件用生产 sbin=对照臂，与 F15-13 的 scratch sbin 34/34 双通道）。等待期间做 VM_SPEC/KERNEL_COVERAGE 同步。 |
| F15-15 | 02:0x(09-17) | v 收口 ④：**20 套件 `=== CPU regression: 20 passed, 0 failed ===`**（runner 自报尾行原文；engine_vs_refvm 套件行 `--- engine_vs_refvm: PASS [all 34 cases incl. pow since card 008]` 含 sbin 漂移检查=PASS，跑的是生产 sbin=对照臂，与 F15-13 scratch sbin 34/34 双通道互证）。峰值 RSS：quot 4025MB/string 4111MB/reducenat 3945MB，其余 ≤1777MB。日志 `$HOME/logs/lean4vm_cpu_regression/<label>.log`，本次总日志 `$HOME/logs/009F/f15_reg20.log`。⑤差分进回归表（add rows only）：`1200\|5000\|brec_drec_iota_vs_lean\|tests/test_brec_drec_iota_vs_lean.py`（timeout 2.2×实测 542s，cap=峰值 4120MB+21%）；bash -n OK。⑥VM_SPEC §11.19（软 INFER 脊 I_ARG_S=69）+ KERNEL_COVERAGE B14 行落档。⑦硬编码扫描：build_vm.py 逻辑区零 env 常量名/cid 新增（命中仅注释与 _SCAN_OPS 名字扫描既有机制），I_ARG_S 15 处均为 cont id 枚举+门。 |
| F15-16 | 02:1x(09-17) | **卡 009 verifier 集终态（docs/plans/009，勾选由总控执行）**：第 1 项【不勾】——新差分测试 B/C 组 11 例中 10 例绿、**G4_d6=KNOWN-GAP**（[XFAIL-KNOWN-GAP]，graph=TimeoutError@720；判定=停手路线，ADR 018）；第 2 项【绿】20 套件 20/20 + verify_engine_vs_refvm 34/34（生产+scratch 双 sbin）；第 3 项【绿】scratch 增量 dims+1016/lookups+20/nnz+5513、引擎钉 scratch 34/34（F15-12/13）；第 4 项【绿】硬编码扫描零新增（F15-15⑦）。**NOT-VERIFIED：d6**（brecOn 卡对链 go-pair 实参同 pos 异 env 根 → DEFEQ 内 below 展开环；内核同常量脊比对不展开 below；三次修复未闭合、裁决 3 无第 4 次；全面定谳 ADR 018，出路 ADR 017 缓存层）。**F15 完工**：改动集=build_vm.py+tests+runner 行+VM_SPEC+KERNEL_COVERAGE B14+005+ADR016 复核注+ADR018（全部在任务书授权文件集内，git 由人提交，20aadf5 已含图/测试/ADR018）。 |
