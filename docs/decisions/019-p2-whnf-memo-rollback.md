# ADR 019：P2 whnf-memo 回滚为 dormant（两度修仍破线，触发 014 卡后备条款）+ 双机制证据 + P2 重启出路

日期：2026-09-17　状态：**accepted**（M6 任务书后备条款明文授权：
"P2 两度修仍破线 → 回滚 P2（d6 绿不损失——P1-only 1070 在帽内），
P1 单独交付走 M6-05/06 同程，P2 破线案落新 ADR 移交后续卡"；
条件已满足，执行记录在 docs/handoffs/010-M-cache.md M6-03(2)/M6-04）
相关：docs/plans/014-kernel-cache-parity.md、docs/decisions/017（缓存层
授权与"只减步数"红线）、docs/decisions/018（d6 与 P1-only 收敛）、
docs/VM_SPEC.md §18、lean_vm/build_vm.py（VM014_CACHE / VM014_WMEMO 臂）、
scripts/bisect_014_m6.py、scripts/probe_014_diag_check.py、
scripts/probe_014_diag_string.py

## 背景

卡 014 的 P1（is_def_eq 正缓存，T_DEFCACHE=41）+ P2（whnf memo，
T_WHNFCACHE=43）全部在码后，M5 死后的 22 套件回归链抓出缓存臂在 5 个
套件改了判定（7 例：string B 族 deq_oflist_true / deq_proj_vs_oflist_true、
check_e2e chk_inc_fn、mutation_reject b_inc + m_dbl_bool + m_pairapp_p2、
olean_export inf_hof_app）——验收铁律 1 与卡 014 红线（判定不变性优先于
一切）双破线。M6 三态 bisect（OFF(0,0) / P1(1,0) / P1+P2(1,1)，纯 Python
图求值，最小复现体）定罪：**P2 全案犯，P1 全清白**（P1 逐例 verdict=OFF、
步数只降；deq_oflist 792→600、52 条目，正是 ADR 017 预期的健康命中）。

## 机制一（钉死，b_inc/chk/inf 族，5-6 拍 reject 且全流零条目）

P2 命中门用 `_fetch_by_v0sq(T_WHNFCACHE)` 查条目，但该注意力原语在
**空缓存（或全部 cleared）**时各位置分数同落 −BIG（BIG=1e20 的 ulp ≫ 2²⁴，
键项被吞），argmax tie_break=latest 落到**全流最新 token = 当拍头
STATE token**（不是 §18.2 旧声称的 position-0 T_NULL）。STATE 的
(v0,v1,v2,x,e2) 与硬 WHNF 帧的 (frV1,frX,frE2=0,…) 在**入口形拍上恒等**
（入口门已强制 SA==frV1、SB==frX、SC==0），P2 原三元验证全部通过 →
把 STATE 本体当缓存结果交付（焦点 := 帧 token 自身）→ 下游
ill_typed/reject。证据：`/home/xkq/logs/014/m6_diag_binc_{p1,p2}.log`
逐拍对拍，s005 命中提交与 STATE(33,145,0,0,590,0) 逐字段吻合。
**修复 (a)（已保留，P1/P2 共享）**：`_fetch_by_v0sq` 返回匹配 token 的
kind 为首字段，两臂命中门各加 `kind==T_*CACHE` 结构验证——命中门对
"非条目 token"零防御的根因闭合，P1 从"侥幸安全"变"结构安全"。

## 机制二（钉死，string 族 reject@341，修 (a) 后仍漂）

WHNF 帧在 **spine-walk 重派形**（I_ARG_S / ST phase2 类派发拍）下被再次
拍下时，**派发拍在同一拍里推进焦点** (784,0)→(783,1603)，而帧的 V1/X
仍记旧焦点 (784,0)。子任务净出口拍把**新焦点的交付值**写进**旧焦点
键** (784,0)：`WHNFCACHE(784,0,…)←(783,1603 的值)`。此后一次合法的
入口形请求 (784,0) 命中这条**错标键**，重放外来值 → INFER(783, foreign
env) → 注错 CONST(0) → REJECT。修 (b)（写门收紧到
`is_whnf_frame ∧ D2==frV2 ∧ SC==0 ∧ SF==0` 净出口拍）挡不住它——该拍
确实是净出口，坏的是**键本身**。修后复测：check/mutation/olean 三族 5
例转绿，string 两例仍漂。证据：
`/home/xkq/logs/014/m6_diag_str_{p1,p2}.log` + dbg 旗标定位（旗标已删）。

## 为什么是回滚不是三修

判别"帧 V1 是否已被同拍推进作废"的信息是**跨拍**的（launch 拍焦点位移），
而帧 6 字段（task,V1,V2,X,E2,F2）无空位可存：F2 承载 soft_flag /
D_SW3 续延 id，E2 承载软标志，V2=caller、X=env 均在用；位置 ≤4096 的
语料上把焦点位移位打包进 V2/X 会撞帽且污染 passthrough。
⇒ **P2 的健全性需要跨拍记忆 = 重新设计，不在"根因修门"的射程内**；
且修 (b) 已证明会牺牲 d6 walk-writer 覆盖（其交付拍天然 C=1317/F=525
非净，M4 备忘录 R1 同族），继续贴门违反 ADR 017 复盘第 3 条
（"最小贴补丁模式在这台机器上失效"）。后备条款条件正式成立。

## 决定

1. **P2 回滚为 dormant，不删码**：`VM014_WMEMO` 默认 "1"→"0"
   （build_vm.py:252，M6 ROLLBACK 注释块 :238）。任何验收路径禁止
   opt-in P2；研究/后续卡显式 `VM014_WMEMO=1` 可用旧臂（含修 (a)(b)）。
2. **修 (a) 保留**（共享底座，P1 防御性收紧）；**修 (b) 保留在
   dormant 码内**（对任何 P2 重启是必要非充分条件）。
3. **P1 单独交付**走完 M6-05/06 同程：不变性合同表覆盖全判定语料族、
   d6 绿（P1-only True@1070 ≤ 帽 1100，无损失）、引擎 34/34、22 套件
   回归 22/22。
4. **P2 重启出路**（移交后续卡，任选其一先出设计）：
   - 键扩为含 caller 帧 id 的三元组，交付拍验证 `帧.V1 == 当拍焦点`
     才开门（用帧自身回指验证替代不存在的空位）；
   - launch 拍把"焦点推进量"写进条目链侧信道（新增 token 类型，
     ENV_FORMAT 版本化）；
   - 彻底放弃图内 whnf memo（内核 m_whnf 的收益/风险比在本机平坦
     指令流上本就被 d6 案质疑，见 ADR 018 讨论线）。

## 影响

- 交付图 = P1-only：默认态 = VM014_CACHE=1、VM014_WMEMO=0；
  ARCHITECTURE 真值表按此登记，P2 态二进制仅作研究件。
- VM_SPEC §18：P2 合同段改"withdrawn（ADR 019），dormant 码保留"；
  ENV_FORMAT kind-43 行注 dormant。
- 专测与探针的 P2 臂改**显式 skip + ADR 019 指针**（不许默删用例），
  判定不变性合同表（M6-05）以 OFF vs 默认(P1) 两态全语料族对照。
- stepgraph_infer_defeq rc=137（M6-01 案情面追加，资源面）：写臂随 P2
  回滚后写量下降（每拍少一枚 raw token），复测旧帽 4000MB；仍顶帽则
  按 brec 先例行内升帽并留证据。
- 教训入板：§18.2 的"M1-01b 哨兵论证"只覆盖了 P1 四元组，把未验证的
  结论外推到 P2 三元组=合同表没覆盖判决语料族的根子在案面上——
  M6-05 的扩表要求即本 ADR 的直接产物。
