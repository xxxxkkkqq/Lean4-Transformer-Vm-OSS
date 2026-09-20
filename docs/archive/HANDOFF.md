# HANDOFF — Phase 5 M3 完成 / 下一会话启动提示词

> **已作废**：交接链已迁到 `docs/handoffs/`（读最新一份）+ `AGENTS.md` + `总控提示词.md`。
> 本文件只作 2026-09-05 时期的历史存档，其中的 artifact 路径与"提交并继续"提示词不要再执行。

> 用法：新开会话，把下面"提示词正文"整段粘贴给 AI 即可继续。
> 本文件对应 2026-09-05 会话结束时的状态：**M3 图帧化已完成并提交**
> （proof-irrel / eta / 结构 eta / proj 进 ALM 图，52/53 图 vs 参照机）。
> 另：`.claude/` 下已配好跨会话接力 hooks（见文末"环境"）。

---

## 提示词正文（复制以下全部内容）

你在 /home/xkq/Lean4-Transformer-Vm-OSS 继续一个进行中的项目：把 Lean 4 内核的
证明验证（INFER→WHNF→DEFEQ）编译成一个 ALM（Append-Only Lookup Machine）计算
图，解析构造（不训练）为 Transformer 权重，让 Transformer 自回归前向执行证明验
证。对标 GitHub 上的 Percepta-Core/transformer-vm（它对 WASM 做的事，我们对
Lean 内核做）。

Phase 1–4 已提交。Phase 5：M1（RefVM infer/defeq 37/37 vs 真 lean）、M2
（INFER/DEFEQ 图帧化 + 三层保真 37/37）、M3-ref（RefVM 侧 proof-irrel/eta/
结构 eta/proj，53/53 vs 真 lean）均已提交。**M3 图帧化已完成**：把 §8.1 的 6
条语义搬进 `lean_vm/build_vm.py` 的 CONT 树（stuck 链续延帧 id 32–54），
`tests/test_stepgraph_infer_defeq.py` **52/53 图 vs 参照机**（16 个 M3 新例
15 通过）。唯一钉住的是 `deq_eta_lam`（**P6.1 已解除**，见下）。全部回归绿：RefVM
vs 真 lean 34/34（whnf）+ 53/53（infer/defeq）、step 图 vs 参照机 34/34、
step 图 vs 真 lean 34/34；重编译权重（635,747,778 参数，71 层 d_model=4374）
后权重 vs 图逐微步 lockstep 34/34。

**M4.1/M4.2/M4.3 ✅（2026-09-06）**：.olean 导出 + 端到端 CHECK + 变异拒绝/
V2 错误定位全部落地（M4 完成）。**P6.1 ✅（2026-09-06）**：whnf spine-root
约定 + marker env 传播修复，`deq_eta_lam` 解除钉住，图 vs 参照机与参照机
vs 真 lean 双双 **54/54（0 钉住）**（VM_SPEC §11.5）。**P6.2 ✅（2026-09-06）**：
infer_proj 帧（机制 F）进图，新语料 `inf_proj_fst/snd/mk`，双双 **57/57**
（VM_SPEC §11.6）。**P6.4 ✅（2026-09-06）**：iota 参照机侧——`Nat.rec`
reduce_recursor（VM_SPEC §11.7），语料 7 例 `deq_rec_*`，参照机 vs 真 lean
**64/64**、图 vs 参照机 57/64（7 钉住）。**P6.5 ✅（2026-09-06）**：iota 图侧
框架（fire_rec + rec_dn 分类 + 15 步 rhs 发射链，VM_SPEC §11.8），5 例
`deq_rec_*` 解除钉住。**P6.5b ✅（2026-09-06）**：解钉最后 2 例
`deq_rec_stuck/stuck_no`——三处独立 bug（VM_SPEC §11.8）：(1) 语料 `_REC_MOT`
把 motive 的**类型**误当 binder domain（ill-typed）；(2) `_pi_natrec` 的 motive
引用 de Bruijn 索引漏算 `z`/`s` binder；(3) 图 `D_XPI2`/`D_TPC2` 跨类 Pi 帧忘
覆写 `fr2_task`（默认 WHNF 而非 DEFEQ）。参照机靠 `_proof_irrel` try/except
吞 infer 异常而侥幸对齐真 lean，图无异常故暴露。修后图 vs 参照机 **64/64
（0 钉住）**、参照机 vs 真 lean **64/64**。**P7.1 ✅（2026-09-06）**：内核
功能补全首里程碑——`is_def_eq_unit_like`（子单元素 defeq，卡住链最后一条规则，
VM_SPEC §11.9）。新增 `UnitT : Type`（0 字段结构，非 Prop 故不被 proof-irrel
遮蔽）+ 语料 `deq_unit_like/no`；参照机 `_unit_like`，图侧镜像 proof-irrel 的
`PI_*` 链（新 cont id 59–63，`es_no` 改踢 `ST_UL`；坑：新 id 须登记
`em_frame_m2/em_frame2_m2`）。验收 **图 vs 参照机 66/66（0 钉住）、参照机 vs
真 lean 66/66**；回归全绿。**下一步（Phase 7 backlog）**：string-lit 展开、
宇宙多态常量（const-const 比 level）、quot、其它 recursor（casesOn/brecOn）；
P6.3（C++ 引擎重建）受"权重重编译禁止"约束挂起，等用户放行资源。

**GPU 速度调研（2026-09-06，docs/GPU_SPEED.md）**：用户放行 GPU，实测 transformer
推理做证明的速度。关键发现：所谓 635M 参数模型 **99.997% 是 0，仅 21,324 个非零**
（解析编译只写 slot→slot 连接）——稠密 forward 每步在读 2.5GB 的零。每 micro-step：
GPU 稠密 fp64 ~858ms / fp32 ~44ms；C++ CSR 引擎（增量 KV、CPU fp64）~11ms（另 +4.4s
载入 5GB）；lean4 内核 ~0.02µs（`Nat.mul 300 300`=9万 iota 仅 1.7ms）。**结论：与
lean4 parity 架构性不可达**（每步依赖上一步、无证明内并行；成本=步数×整模型 forward，
lean4=步数×20ns 且不读权重；差距随证明规模扩大）。手写 CUDA 现实可把稠密路径 ~1000×
（21K 稀疏入 shared mem + CUDA-graph + fp32 + 跨独立证明批量），但仍 10²–10³× 慢于
lean4。**用户决定：先做 Phase 7 到内核完备（能做证明 + 报错一致），速度/CUDA 后置。**

**P7.5a casesOn 参照机侧 ✅（2026-09-06）**：通用 iota（inductive.h L77
`inductive_reduce_rec`）的参照机侧泛化第一步——`casesOn`（major_idx=0、无递归调用、
`match`/`induction` 编译产物）。`Nat.casesOn`(cid 30)/`P2.casesOn`(cid 31) 入
TOY_CONSTS；RefVM 新增 `self.caseson` 元数据表 + `_match_ctor`（nat 字面量先转构造子
形，按构造子 cid 选 minor，字段按应用序喂入）+ whnf K_CONST 分支 casesOn 归约。语料 7
例 `deq_caseson_*`。验收 **参照机 vs 真 lean 73/73**（66→73）；回归全绿：whnf 34/34×2、
图 vs 参照机 66/73（7 casesOn 钉住）。

**P7.5b-2 Nat.casesOn 图侧 ✅（2026-09-06）**：casesOn 派发编进 ALM step 图。
`tokens.py` 给 `Nat.casesOn` 打 `OP_CASESON=12`；`build_vm.py` 复用 `Nat.rec` iota
骨架：`fire_caseson` 弹 4 项 spine（`[t,motive,zero,succ]`，`t` 在 PEND 头）、
`NAT(OP_CASESON,caller,1)` 帧下子 whnf 主前提、`cs_dn` 三分支——zero→zero minor、
succ→**cs_build 循环**（3 raw 步建 `succ_minor (Nat.pred t)`，惰性 pred 无数字循环）、
其它→§10.2 卡住交付。帧登记入 `em_frame`+`frame_V1/V2/X/E2/F2`（P7.1 死循环陷阱），
`dn1` 排除 `OP_CASESON`。验收 **图 vs 参照机 72/73**（6 casesOn 解钉，succ 例 27/33
微步）；回归全绿：whnf 34/34×3、参照机 vs 真 lean 73/73、M4.2 15/15、M4.3 16/16+8/8。

**P7.5b-3 P2.casesOn 图侧 ✅（2026-09-06）**：结构消解 iota 入图。独立派发键
`OP_CASESON_P2=13`（cid 31）。差异：3 项 spine `[t,motive,alt]`、单一 2 参 minor、
主前提是卡住构造子应用 `P2.mk a b`（**值在 spine 根 `SF`**，焦点 `SA` 只是头
`Const(P2.mk)`——踩过的坑：`p2_ctor` 必须查 `SF` 非 `SA`；`fire_p2` 门控查 alt 项
存在非 extras）。`p2 build` 2 raw 步建 `alt a b`。验收 **图 vs 参照机 73/73**
（`deq_caseson_p2` 解钉，M3_PENDING 清空，p2 例 36 微步）；回归全绿同上。**casesOn
图侧（Nat+P2）至此完备。下一步 P7.5c**：brecOn/drecOn（带递归调用的结构递归）。

**P7.5b-4 Bool.casesOn 图侧 ✅（2026-09-06）**：`if-then-else`/`decide` 的 iota
入图。独立派发键 `OP_CASESON_BOOL=14`（cid 32）。4 项 spine `[t,motive,false,true]`、
两 minor 均 0 字段 → **无 build 循环**（选中 minor 直接继续 whnf，同 Nat zero 规则，
15 微步）。`fire_bool` 弹 4 项（门控查 true 项存在 `b_false[2]>=1`）、`bool_dn` 读
焦点 `fK/fV0` 分 `bool_false_r`/`bool_true_r`/`bool_stuck_r`。**两个保真/接线坑**：
(1) Lean 先声明 `false` 后 `true`，minor 序为 **[false,true]**——初版写反，参照机 vs
真 lean 74/77，修正 `_pi_boolcaseson` de Bruijn + `self.caseson` 表 + 语料期望后
77/77（对拍真 lean 抓出构造子声明序，猜不得）；(2) 帧 `E2/F2` 槽须加 `fire_bool`
选择器（`E2=SF`/`F2=SC`），漏则帧落成 `E2=0,F2=0`、minor 链读空死循环。验收
**参照机 vs 真 lean 77/77、图 vs 参照机 77/77**（4 条 `deq_boolcaseson_*`，
M3_PENDING 仍空）；回归全绿：whnf 34/34×3、M4.2 15/15、M4.3 16/16+8/8。**casesOn
图侧（Nat+P2+Bool）至此完备。下一步 P7.5c**：brecOn/drecOn（带递归调用的结构递归）。

**P7.5c-1 brecOn 参照机侧 ✅（2026-09-06）**：结构递归（真实递归 `match`/`def`/
`induction` 的编译目标）。**SOTA 核查关键发现**：内核**无** brecOn 原始 iota——
`Nat.brecOn` 是 `@[reducible]` def-over-`Nat.rec`+`PProd`（`Lean/Meta/Constructions/
BRecOn.lean`），消解 = delta 展开 → `Nat.rec` iota（已有）→ proj（已有）。派生 iota
规则（zero/succ 同形，minor 首参是**完整 t** 非 pred）：`brecOn motive (succ n) F ⟶
F (succ n) (Nat.below motive (succ n))`。P7.5c-1 范围：zero/succ **派发**，语料 minor
**忽略 below** → 卡住 `Nat.below motive t` 被 beta 丢弃，**无需 PProd/go/Nat.below
定义**。toy env 加 `Nat.below`(cid33 占位类型)/`Nat.brecOn`(cid34，spine `[t,motive,F]`
major_idx=0)；RefVM whnf K_CONST 分支加 brec 派发（发射 `F t (below motive t)` 5 token，
封闭项 env=0）。验收 **参照机 vs 真 lean 82/82**（5 条 `deq_brec_*`）；图侧 5 例钉
M3_PENDING（图 iota 待 P7.5c-1b），图 vs 参照机 77/82；回归全绿：whnf 34/34×3、
M4.1 21/21+17/17、M4.2 15/15、M4.3 16/16+8/8。**下一步 P7.5c-1b**：brecOn 图侧 iota
（fire/dn + 5-token build 循环，复用 casesOn 骨架）。**P7.5c-2 设计分叉**：真递归
（minor 用 below 取递归值）需 PProd/NatBelow 表示，单态 toy env 表达不了异构宇宙
多态的 below 链——届时先问用户。

**P7.5c-1b brecOn 图侧 iota ✅（2026-09-07）**：OP_BREC(15) 铺进六层主选择器——
门（br_mot/br_F/brecop/fire_brec）、结果与卡住门（brec_dn/brec_sd/brec_nat/
brec_build_r/brec_stuck_r）、分支态（fire/build/stuck/sd）、`is_brec_build` 进
B2-F2 build 选择器与 em_frame/raw_K/V0/V1 门；每块恰好 31 闭合（曾两次踩
闭合数坑：替换串少吞/多给 `)`，最终用脚本断言 len(run)==58/31 重建）。
**卡住例真根因（本轮最重要发现）**：`_pi_natbrecOn` 的结果 codomain 编成了
`motive F`（de Bruijn `App(BVar(1),BVar(0))`，ctx [F,motive,t] 下 idx0=F），
正确为 `motive t` = `App(BVar(1),BVar(2))`。cod 是惰性闭包：run 1（spine 推理）
从不解引用它 → 4 条 iota 例全绿；卡住例 proof-irrel 链 PI_TY 真正 INFER cod
闭包 → `(fun _ => Nat) minor` → I 链推 minor 类型得 PICLO，与 dom=Nat 配成
卡住对 → PI_T(33) → INFER(PICLO) → bad_i → REJECT 4。RefVM 被 `_proof_irrel`
try/except 掩盖（吞 cod-infer 异常落回 spine 比较，碰巧同判 TRUE）——**toy env
的类型 AST 必须过图侧差分，ref 的软失败会吞类型错误**。诊断法：/tmp/bs7.py
记录每个 token 的出生步号 + 归一化 trace 对比（rec vs brec），确认两运行 F 层
f_type 表示差异（物化 PI vs 惰性 PICLO）只是表象。验收 **图 vs 参照机 82/82
（0 pinned，解钉 5 条 deq_brec_*；步数 zero 27/succ 27/const 24/no 27/
stuck 224）**；三层回归全绿：ref vs lean 82/82、whnf 34/34×3、M4.1 21/21+17/17、
M4.2 15/15、M4.3 16/16+8/8。权重维持 M3 冻结。**下一步 P7.5c-2**：brecOn 真递归
（minor 用 below 取递归值 → PProd/NatBelow 表示，设计分叉先问用户）；之后
P7.3 宇宙多态 / P7.4 quot / P7.2 string-lit。

### 环境与纪律（必须遵守）

- **GPU 已放行（2026-09-06 用户指令）**：RTX 5070 Ti 16GB 空闲、RAM 30G/23G 可用，
  可用于 transformer 推理测速；但用户决定**速度/CUDA 后置**，当前主线是 Phase 7
  内核完备。CPU 测试仍保守用 `OMP_NUM_THREADS=4 taskset -c 0-3`。权重重编译禁令
  已随 GPU 放行解除（但当前 checkpoint 仍是 WHNF-only、落后于现图，重编留待速度线）。
  跑测试前估算耗时并用 timeout 包裹；后台长任务 `setsid nohup ... > log 2>&1 < /dev/null &`，
  输出重定向到文件轮询（python 记得 `python3 -u`），**绝不用管道 tail**（会把
  中间输出吞掉，本会话实测踩过）；进程可能随工具调用中止被杀。
- 对拍对象**只有真 lean 二进制**（`~/.elan/bin/lean` v4.33.1）；永不复活旧
  Python Lean 内核。`/home/xkq/lean4/src/kernel/` 是 4.35 master 源码，只读、
  用于核对真算法（type_checker.cpp：infer_proj L247、is_prop L383、
  is_def_eq_proof_irrel L932、is_def_eq L780–1000、try_eta_expansion_core /
  try_eta_struct_core）。
- **SOTA 核查义务（用户明确要求）**：动手前先读真 lean 内核源码核实算法；
  架构拿不准时去 GitHub 核查 Percepta-Core/transformer-vm 怎么做
  （frame 协议、保真分层、KV cache 引擎、.olean 导出）。4.33.1 二进制与 4.35
  源码分歧时，以对二进制做 #ORACLE 探针实测为准。
- git 纪律：每个里程碑一个 commit 带验收数字，docs 与代码同 commit；
  model/step_vm.pt/.bin 已 gitignore。遇设计分歧先问用户。
- oracle 命令的 mvar 坑修复（reference/lean_ref.py 里
  synthesizeSyntheticMVarsNoPostponing + instantiateMVars）别回退。
- 修图坑（M2/M3 实测）：`_select(cond,a,b)` 的 cond 必须严格 0/1；Expression
  不能相乘，乘 0/1 用 `reglu(a,b)`；发射位次序 raw,pend,link,link2,litdig,
  frame,frame2,lithead,gap,litdig2,const,STATE，**槽位寻址是位置性的**（一步
  发多 token 时后续 frame 槽址随已发数 +1，M3 的 c4 即由此而来）；frame 默认
  task 覆写、rej_* 累加。

### 跨会话接力（本仓库已配置）

`.claude/settings.json` 配了两个 hook：
- **PreCompact(auto)** → `.claude/hooks/handoff.sh`：auto-compact 触发时把
  transcript 路径写进 `.claude/last-session.txt`，结尾 assistant 文本快照到
  `.claude/handoff-snapshot.md`（压缩照常发生做兜底）。
- **SessionStart(startup|clear|compact)** → `.claude/hooks/inject-handoff.sh`：
  新会话注入上述指针 + docs/HANDOFF.md 提示。
需要旧会话精确细节时 **grep 旧 transcript JSONL**（勿整体读入）。

### M3 图帧化的机制（细节见 VM_SPEC §10.2 M3 表 + build_vm 注释）

1. **proj 归约（机制 E）**：whnf 子项到满 `P2.mk` spine → `I_PROJ` 投 `a_idx`，
   否则重贴 proj token；`deq_proj` 快速比（同 sname+idx → 递归子项，否则 False）。
2. **binder 身份（机制 A）**：`T_LINK.F2 = bid`（binder 唯一身份，= 链接位置或
   eta 的 `M2.F2=M` 共享）。DEFEQ bvar/bvar 走链后 `D_BV3` 比 bid 而非比位置。
3. **proof irrelevance（机制 B）**：stuck 对最先做；`PI_T→PI_TY→PI_LVL→PI_S/PI_D`，
   infer(nt) whnf 成 Prop 则 defeq(ty,ty) 投 True。
4. **eta 展开（机制 C）**：恰一侧 LAM；`ST_ET→ETA_T→ETA_S→ETA_DOM→ETA_LINK→
   ETA_LNK2`，infer 非 lam 侧 whnf 成 Pi → defeq(dom) → 造 `M,L,M2` 标记 +
   合成 `App(BVar1,BVar0)` raw → defeq(体, 应用)。lam_is_t 暂存 bvar0.X、
   M 位置暂存 bvar1.X（帧预算紧）。
5. **结构 eta（机制 D）**：一侧满参非递归 ctor（`P2.mk`，0 参 2 字段）；
   `ST_ES→ES_T→ES_DOM→ES_NEXT`，`s_ty` 静态 = `Const(P2)`（**免 infer(Proj)**，
   P6.2 后图 INFER 已含 Proj，但静态捷径对 P2 等价且省步），defeq(t_ty,s_ty) → 逐字段 `Proj(nid,i,t)` vs
   `args[nfields-1-i]`（倒序）。

### 已知缺口（Phase 6）

- ~~**`deq_eta_lam`（M3_PENDING 唯一钉住例）**~~ **P6.1 已修（2026-09-06）**：
  图 `mk_stuck` spine-root 交付 + WALK 帧 F2 携带 env₀ + `mk_dq` 值链交付；
  参照机 `whnf` marker 分支同步 spine-root 并引入 `spine_env`。顺带修掉
  head-only 交付的不健全性（新守卫例 `deq_fvar_args`：`f 1 ≡ f 2` 必须
  False）与图 `I_LIT` 的 `raw_V0=SB` env 泄漏。细节见 VM_SPEC §11.5。
- ~~**infer_proj 帧（机制 F）**~~ **P6.2 已修（2026-09-06）**：图 INFER 补
  Proj 类型推断（`proj_i` + IP_TY/IP_PEEL 续延，id 57/58，P2 build-time
  门控，VM_SPEC §11.6）。结构 eta 的 ES_T 仍用静态 s_ty 捷径（等价且省步）。
- **iota 图侧（P6.5 进行中）**：参照机已实现（P6.4，VM_SPEC §11.7），图侧
  7 例钉住。设计：`NAT_OP_CODES["Nat.rec"]=11`（ENV_HDR.X 派发，不进
  NAT_OPS——参照机不受影响）；main 模式 `fire_rec`（pend≥4：弹 4 项、
  压 NAT(OP_REC,caller,1) 帧，F2=m_entry、E2=spine-root）；maj whnf 完成
  → `rec_dn` 分类（zero：续跑 z 闭包；succ：重写帧 X=2 进 compute 相位
  ph2 的 15 步 rhs 发射链，pred 用 `Nat.pred <maj原位置>` 两 token 技巧
  免数字链；stuck：交付 spine-root + maj env）；ph2 链 = pred(2 raw) +
  e1..e4(2×link+link2) + b0..b3(4 raw) + rc(1 raw) + 6 App raw，位置全部
  = base+常数（base 存帧 E2），done 步 A=rhs、B=e4、D=caller、E=0 续跑。
  已知偏差（语料不触及）：`Nat.succ <stuck>` 两侧都非 stuck（图出垃圾链/
  参照机 ERR_TYPE），内核留 stuck——offset 规则后续里程碑。
- **C++ 引擎**：只读旧 10 槽，不覆盖 M3 帧（raw 槽 / INFER/DEFEQ / 新续延）。
  Phase 6 重建二进制格式 + 读出表同步。

### 立即下一步（按序）

0. **M4.1 ✅（2026-09-06）**：.olean 常量子集导出已落地
   （`reference/olean_export.py` + `tests/test_olean_export.py`，
   RefVM(导出 env) vs 真 lean 21/21、图 vs RefVM 17/17，回归不变）。
1. **M4.2 ✅（2026-09-06）**：端到端 CHECK 已落地（T_CHECK 锚帧 +
   CK_TY/CK_RES 续延 + `StepDriver.run_check` + `RefVM.check`，
   `tests/test_check_e2e.py`：RefVM vs 真 lean 15/15、图 vs RefVM 15/15）。
2. **M4.3 ✅（2026-09-06）**：变异拒绝 + V2 错误定位已落地
   （`tests/test_mutation_reject.py` + `lean_vm/localize.py`：Part A 三层一致
   16/16、Part B 定位 8/8，driver 侧零图改动）。**顺带修复 M2 遗留 bug**：
   `build_vm.py` D_NCC 块 `rej_c` 赋值覆写丢弃 I_CHK 等 CONT-tree 拒绝，致图
   `infer_app` 接受参数类型错误申请；改累加后正确 reject，全套回归不变。
   **M4 三项全部完成 → 下一步 = Phase 6**。
3. **P6.1 ✅（2026-09-06）**：`deq_eta_lam` spine-peel env 传播已修
   （图 `mk_stuck`/WALK-F2/`mk_dq` 三处 + 参照机 `whnf` spine-root/`spine_env`；
   新守卫例 `deq_fvar_args`；图 vs 参照机 54/54、参照机 vs 真 lean 54/54，
   回归全绿，VM_SPEC §11.5）。
4. **P6.2 ✅（2026-09-06）**：infer_proj 帧（机制 F）已进图
   （`proj_i` + IP_TY/IP_PEEL 续延 id 57/58，P2 build-time 门控；语料
   `inf_proj_fst/snd/mk`；图 vs 参照机 57/57、参照机 vs 真 lean 57/57，
   回归全绿，VM_SPEC §11.6）。
5. **P6.4 ✅（2026-09-06）**：iota 参照机侧已落地（`Nat.rec`
   reduce_recursor，VM_SPEC §11.7；语料 7 例 `deq_rec_*` 总 64；参照机
   vs 真 lean 64/64、图 vs 参照机 57/64（7 钉住），回归全绿）。
   **下一步 = P6.5**：iota 图侧框架（设计见"已知缺口"节），逐例解除
   `M3_PENDING` 钉住。

### 关键文件

- `lean_vm/build_vm.py`：微步图（M2 块后是 M3 块：proj/bid/proof-irrel/eta/
  结构 eta 的 CONT 分支 + c4 槽）；`step_driver.py`：驱动器（raw/link2/frame
  E2/F2 槽已有）。
- `lean_vm/ref_vm.py`：RefVM（M3 语义在 defeq/`_proof_irrel`/`_try_eta`/
  `_try_eta_struct`/`_proj_core`/infer K_PROJ 分支，注释带内核行号）。
- `reference/toy_env.py`：TOY_CONSTS 含 True/P2/T_pair、TOY_STRUCTS、
  DEFEQ_CORPUS 37 例 / INFER_CORPUS 16 例。
- `tests/test_stepgraph_infer_defeq.py`（52/53，1 例 M3_PENDING）、
  `tests/test_ref_infer_defeq.py`（53/53 基准）、回归四件套
  `test_stepgraph_vs_refvm.py` / `test_stepgraph_vs_lean.py` /
  `test_ref_vs_lean.py` / `test_weights_fidelity.py`、`test_engine_vs_runner.py`。
- `docs/VM_SPEC.md` §8.1（M3 语义）、§10.2（M3 微步表）、§7.4（M4 错误定位）。

---

## Phase 7 / M5 里程碑（2026-09-12）

四项一次落地（4 个 commit：593a3fa / 663671e / 69eaebf / 22c828e）：

1. **追加项 1（槽位分配修复）✅**：`compiler/weights.py:_assign_slots` 四处修复——
   death 回到「直接消费者 + 1」；删 3c3（输出维传递依赖延寿）；着色改层粒度
   （写入加法、擦除掩码只跨层、同层禁复用，closed 区间
   `[birth//4,(death-1)//4]`）；贪心回收弹出的空闲槽推回堆时保留**原键**
   （重键为当前层 lo 是 d_model 爆到 ≈num_dims 的直接原因）。
   **d_model 6018→1898，参数 1.61B→509,009,436，权重 12.9GB→4.07GB。**
2. **追加项 2（稀疏权重格式）✅**：`save_weights_sparse`（L4SV v1：魔数+6i 头+token
   名+每矩阵 CSR + erase/tiebreak/meta 尾，embedding 不写）+
   `engine/vm.cpp:load_weights_sparse` mmap。**载入 7ms vs 稠密 5.8s**，流与
   稠密逐 token 一致。`model/compile_vm.py` 三件套（.pt/.bin/.sbin）。
3. **追加项 3（测试角色重定位）✅**：`tests/test_weights_fidelity.py` 改**权重
   编译后的开发检查**（默认 RELEASE_SUBSET 13 例，`--full` 全量含 big_mul/pow
   `--quick` no-op，新增 `--ckpt/--gpu`）；新增 `scripts/run_cpu_regression.sh`
   （8 套件，一条命令，各 timeout 1800）。
4. **M5 核心（choose 图侧 reject）✅**：根因不是 nat/casesOn extras，而是
   **proj 函数位待应用参数丢失**——`(P2.fst ih) k` 的 `k` 被 `I_PROJ` 清 C 丢弃，
   焦点停在字段 Lam 后被当 add 实参 → `nat_hard` 拒。修复 =
   `proj_setup` 把 SC 存 ST 帧 E2、`I_PROJ` 恢复 C 且在有链时 E=0 回 main 模式
   （见 `docs/VM_SPEC.md` §11.18）；`ref_vm.py` proj 分支提取字段后 `continue`。
   toy 新增 3 例 proj 语料 → **图 vs 参照机 37/37**；choose 扫描全 OK
   （2 1=2/600 步、3 1=3/921 步、10 3=120）。重编译：**d_model 1904、
   511,178,304 参数**、3 件套。
5. **real_env_bench**：`Nat.factorial 6/10` 图侧收敛且 RefVM=lean ✓；
   `Nat.choose 10 3` 同（图=ran）。`sqrt/gcd` 导出拒绝 = 文档化切片边界
   （thm 不在 M4 切片 / `PSigma.rec`）；`fib` 拒绝 = 需 Prod（2 参结构 eta
   泛化）→ 候选新里程碑（立项前问用户）。

**回归数字**：`scripts/run_cpu_regression.sh` = **8 passed, 0 failed**；
`test_stepgraph_vs_refvm.py` 37/37；`test_ref_vs_lean.py` 34/34；
`test_ref_infer_defeq.py` 82/82；`test_stepgraph_infer_defeq.py` 84/84。
权重编译后的开发检查（GPU fp64，`--ckpt model/step_vm_fixed.pt`）：**发布子集
13/13 PASS**（最大数值偏差 ≤1.4e-08）；据此已晋升
`model/step_vm.pt/.bin/.sbin`（d_model 1904、511,178,304 参数）。
`--full`（34 例）后台续跑中，日志 `/tmp/fidelity_fixed_full.out`。
该检查是编译期开发检查（只覆盖 WHNF 任务），不是验收；验收是判定与
真 Lean 4 内核一致（[DESIGN.md](DESIGN.md) §2）。

**切片边界（明示，不修）**：`Nat.sqrt`（`Nat.le_of_ble_eq_true` 是 thm）、
`Nat.gcd`（`PSigma.rec`）、`Nat.fib`（`Prod` 参数化结构 eta）仍拒绝导出；
均为 M4 导出切片之外，非本里程碑缺陷。

