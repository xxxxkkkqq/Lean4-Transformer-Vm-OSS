# ADR 017：与上游构造的范围落差 + 图侧缓存层立项（复盘裁决）

日期：2026-09-16　状态：**accepted**（用户经总控问答拍板；总控执笔）
相关：卡 009 全链（docs/handoffs/005-F-iota.md 事故记录 1–15 + 总控裁决）、
docs/plans/014-kernel-cache-parity.md（本裁决的执行卡）、docs/DESIGN.md §4/§5/§7、
上游参考克隆 `/home/xkq/transformer_vm_upstream/`（Percepta-Core/transformer-vm，只读）。

## 背景

卡 009 连卡 15 任代理（多数死于客户端/账户层事故，技术链 F6→F13 六代把差分
分歧 7→2）。用户要求架构复盘：对照上游 transformer-vm 源码与设计，回答
"为什么卡这么久、哪里做错了"。复盘证据：

1. **上游对象与我们的对象不同阶。** 上游模拟 WASM：机器状态 = 3 个标量
   计数器 + opcode + flag（`wasm/interpreter.py` 的
   `fetch_sum([delta_stack, delta_cursor_expr, delta_call_depth])`），
   ~40 个有界 opcode 用圆周点一次点积分派（`op_dot`，`pointsR2=32045`），
   程序以字节躺在 token 流里按绝对位置寻址，局部变量固定步长
   （`LOCAL_STRIDE=256`）。全仓 Python ~8000 行。
   我们复刻的是 Lean 内核：递归树归约 + binder/de Bruijn + 环境捕获 +
   universe 归一化 + is_def_eq 约 20 分支。`lean_vm/build_vm.py` 6235 行
   编码 9 TASK + 63 continuation id + 19 OP 码，状态是 STATE 六元组
   （A–F）共享寄存器 + pend 链相对地址算术（c1=POS+1/c2=POS+2）。
   **单位语义分支的手工电路成本比上游高一个数量级**；DESIGN §7.1
   的预警当时没有量化到这个倍数。
2. **真正的结构缺失：图没有缓存层，内核有。** 内核 `whnf` 查
   `m_st->m_whnf`（`K/type_checker.cpp:753-755`）；`is_def_eq` 有正缓存 +
   失败缓存（cheap structural + positive cache :836；`cache_failure` :953
   用于 :1042；`cache_success` :972 用于 :1251）；proj 是 lazy delta
   （:1123-1138）。图侧任何东西都不去重、每圈全量重展开。d6 的语义增长环
   （软 I_ARG 对 @Nat.below whnf 重进 INFER 阶梯，每圈产生新 level 结构，
   深度 5→28）在结构上就是"对等价新结构的无限重复展开"；有限步帽下的
   Timeout 即判定分歧。**在内核里缓存只省时间，在我们有限步长的图里
   缓存臂是判定一致性的必要条件（对深输入）。**
3. **错误的语义合流：软/硬 INFER 共用 I_ARG。** 内核 `infer_only` 脊
   （:189-205）从不做 arg-vs-domain 检查，完整 infer（:174-188）才做——
   本就是两条代码路径。图让 proof-irrel 软通道（帧 F2=1）与真 INFER 共用
   I_ARG 臂。修②两次失败（跳 I_ARG 破 c1/c2 pend 地址算术 = period-1 活锁；
   强制成功改写 decline 级联致 d7 坏）证明该共享臂已与全机耦合，
   "最小贴补丁"模式在这台机器上失效——不是执行者手艺问题。
4. **没做错的**（复盘同时记录，防止矫枉过正）：真 lean 唯一判据 + 差分
   方法学、环境是数据、零硬编码答案，全部守住；技术收敛 6 代到 2 分歧
   是健康的；15 任之死是基础设施事故链，不是项目错误。

## 决定

1. **路线：继续当前线 + 插缓存卡。** 验收标准与 DESIGN 宪法不动，
   "一张图一份权重"不动摇——缓存做在图内（数据驱动的结构性去重臂），
   不做在 driver 层（混合架构会放弃可微裁判押注，且 driver 决策进不了
   权重）。执行载体 = 任务卡 `docs/plans/014-kernel-cache-parity.md`，
   排期在卡 009 结案之后、卡 010（G 链）之前。
2. **d6 兜底确认**（与 20:5x 总控裁决一致，经用户批准）：F15 的第三次
   尝试（软链专用新臂，路线 a）若再失败，d6 登记为 KNOWN-GAP + ADR 注记，
   卡 009 按 1 分歧结案不挡主线；d6 根因归入卡 014 的缓存层范围，
   预期在结构性方案下顺带解决。
3. **工作方式修正**：后续工作包按"语义相近分支成组"开卡（proj 族、
   level 族、iota 族），减少逐分支"修一露一"的返工轮次；本条约束
   KERNEL_COVERAGE 后续 WP 的划分，不改已发卡。

## 影响

- 卡 009 交付边界不变：F15 完成 d6 尝试 → d4 抬帽 720 → 全量差分 →
  收口。卡 014 为卡 009 与卡 010 之间的插入项，G(010) 顺延。
- 卡 014 的判定红线：缓存臂**只能减少步数、绝不改变判定**；任何"缓存
  使某例变绿"必须另证该例在无缓存语义下判定不变（内核缓存不影响
  verdict，这是对齐合同而非新语义）。
- 本 ADR 的教训入 `开发防线.md` 待办：开卡前对"对象与上游原型的结构
  差异"做一次书面评估（平坦指令流 vs 递归归约机），避免再按上游节奏
  估算工期。
