# 022. 运行期 universe/level 通道：normalizes_to_zero 电路先行（卡 015 拍 1 定案）

- 状态：accepted（2026-09-21 总控落档；拍 1 语义探针证据见下）
- 背景：图 LEVEL 通道是整数显式级计数器（`build_vm.py:5786-5798` 自述边界），
  Param/MVar/Max/IMax 不可表达。三处实跑咬人：① `thm_imax`/`thm_max00`
  XFAIL（is_prop 假拒 8，KNOWN_GAPS 登记）；② univ 多态 accessor def whnf
  活锁（`g04b_c2_probe1.log`：2000 步不 halt / 4GB）；③ Mathlib 闭包
  779 常量中 768 个（98.6%）存储树含 `Level.param`（P4 实测），卡 012 M-B
  撞通道缺失。
- 决策：**混合方案**——保留 §12.7 编码期 type 特化（零改动），运行期补三件：

  **组件 1（本卡主体）：`normalizes_to_zero` 电路（D8，K/level.cpp:174-186）**
  - 逐 kind 规则（内核原文）：Zero→true；Param/MVar/Succ→false；
    Max→`n2z(lhs) && n2z(rhs)`；**IMax→只看 rhs**（`mk_imax` 右参为 zero 即返回它）。
  - 接入点一：is_prop（`K/type_checker.cpp:383-389`）——图侧 `pl_prop` 现为
    syntactic 根比 KL_ZERO（`:4451-4457` 注释自述），对 `Sort (imax 1 0)`
    存储类型假拒。改判据 = infer 结果 sort 的 level 树过 n2z 电路。
  - 接入点二：I_PIL2 符号级 imax 折叠（`:3522-3531` 现为整数通道）——
    D2 的 is_zero(l2) 判定复用同一电路（`K/level.cpp:112-123`）。
  - 电路形态：单树展开（每节点一个 AND/OR 门 + 叶子），深度帽 8（实测 level
    树深 ≤3；内核无 level 深度概念，帽只影响极深垃圾路径，sound）。
    与 `_lvl_eq`（`:3674`）"两个 level 树配对比较"不同——n2z 是**单树**递归，
    无 2^depth 配对爆炸。图规模增量预估：满树 ≤511 节点、每节点数个 ReGLU，
    预估 +500~1500 dims（O(1)，图深度不增，宪法 §4 第 2 条不破）。

  **组件 2（可后置）：level defeq 的 Max/IMax 递归比较（D4 子集）**
  - `deq_sort`/`deq_const`（`:3841,:3997-4008`）用 `_lvl_eq`（sound 子集，
    Max/IMax 非同一闭包即不等，`build_vm.py:3632-3648` 注释自述）。
  - 保持 sound-incomplete 不算判定错误（宁可拒不误收）；仅当组件 1 验收
    后预算有余再扩展（Max 结合吸收/递归配对），否则记 NOT-VERIFIED 不掩盖。

  **组件 3（B13 活锁）：图侧 delta 展开的 level 实例化或 accessor proj 快捷**
  - 探针 P4b 实证：accessor def 存储 value = `Lam Lam (Proj UProd 0 x)` 且
    universe params=['u']（`K/type_checker.cpp:555-565` is_delta 要求
    `length(const_levels)==get_num_lparams`，unfold 用 use-site levels 实例化）。
  - 两条候选：① unfold 一步内按 use-site level 链替换 value 的 LParam
    （§12.7 T_LVLSUB 失败史是"环境链"方案，本路径是单步替换，需拍 2 探针
    验证图规模）；② accessor spine 走 A30 `try_unfold_proj_app` 式快捷
    （识别 def 值形状=Lam*Proj → 直接 proj 归约，绕开 LParam 实例化）。
  - 拍 2 先复现活锁（G04 env + `UProd.fst` 载体）再定，两案都保留。

- 被拒方案：
  - **继续纯编码期特化**（现状）：P1 反例——`thm_imax` 的 is_prop 判定在
    运行期读共享声明类型 `Sort (imax 1 0)`，defeq/is_prop 的动态比较无法
    前移到编码期（use-site 才知被比对象）；且 768/779 常量含 LParam 的
    规模下全量特化必然复制爆炸（§12.7 先例）。
  - **完整 D5 normalize 全序**（K/level.cpp:454-516）：只服务"两个任意 level
    归一化后比较"（D4 的 normalize 支）；图侧 sound-incomplete 的 `_lvl_eq`
    已覆盖判定语料（同一闭包/单链/显式级），完整归一化排序电路成本高且
    非判定必需。D6/D7（序关系）同理由，仅服务缓存（VM_SPEC §12.6 TBD2）。
  - **运行期 T_LVLSUB 环境链**：§12.7 已实测 `build_step_graph` 因子树指数
    复制不可行，不复测。
- 预期后果：好——thm_imax/thm_max00 转绿（XPASS 摘除）、univ accessor
  活锁转绿、M-B 闭包可进图；坏——图规模 +500~1500 dims（~2-6%，O(1)），
  decl_injection 回归帽 2700|4000 需按注释规程复测（语料若加行）。

## 拍 1 探针证据（2026-09-21，总控直跑，4.33.1 钉死）

- P1（#KDECL，`tests/test_decl_injection_vs_lean.py` B 节子集，原文）：
  `oracle[thm_imax] = OK`、`oracle[thm_max00] = OK`、`oracle[def_imax] = OK`、
  `oracle[thm_sortraw_imax] = thmTypeIsNotProp`、`oracle[thm_sortraw_max00] = thmTypeIsNotProp`。
  图侧 stored type：`injX_imax` = `Sort(imax (succ 0) 0)`、`injD_imax`（源写）= `Sort(0)`
  （前端归一化证据）。机制定谳：is_prop 检查的是 **A 的 infer 类型** 的 level
  归零——`thm_imax` 的 A=Const injX_imax → infer 得 Sort (imax 1 0) →
  n2z(imax…) 只看 rhs=0 → true → OK；`thm_sortraw_imax` 的 A=Sort (imax 1 0)
  表达式 → infer 得 Sort (succ …) → n2z(succ)=false → NotProp（图侧判 8 与
  kernel 一致，不在 KNOWN_GAPS 的因由）。
- P2（`tests/probe_015_semantics.py`）：`WHNF UProd.fst (UProd.mk 3 4 : UProd Nat Nat)`
  → `{'k':10,'nat':3}`（kernel 一步归约到 3；图侧同形状活锁）；
  `INFER UProd.fst` → `{u} → {α : Sort (succ u)} → {β : Sort (succ u)} → UProd u α β → α`
  （forallE 带 LParam）。
- P4：`/home/xkq/logs/012I/closures/Nat_testBit_land/dump.jsonl` 779 常量，
  288 顶层 univ-params，**768 个存储树含 Level.param**（98.6%）。
- P4b：`UProd.fst` stored type = `{u} → {α : Sort (succ u)} → … → UProd u α β → α`；
  stored value = `Lam Lam (Proj UProd 0 x)`，universe params=['u']（B13 缺口形状）。

## 拍 2 verifier 行集建议（按 XPASS 协议，行常跑不删）

- [ ] thm_imax / thm_max00 转绿摘除（图侧 is_prop 接 n2z 电路后）
- [ ] 新差分：`UProd.fst (UProd.mk 3 4)` whnf → 3（oracle=P2 原文）+ 活锁转绿
- [ ] thm_sortraw_imax / thm_sortraw_max00 保持 NotProp 一致（回归行，防回归）
- [ ] 符号级 Pi infer / imax 折叠差分（P4 形状，多态常量 use-site）
- [ ] decl_injection 全量 + 23 套件回归全绿；重编译 --sparse + 引擎 34/34；
      图规模增量落文档
- [ ] 硬编码扫描零新增；VM_SPEC §12 / ENV_FORMAT（如需）/ 矩阵 D1/D2/D8/B13
      行同步
