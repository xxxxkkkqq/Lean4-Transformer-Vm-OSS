# 任务 015：图侧运行期 universe/level 通道（D 组收口，解锁 Mathlib 规模与两条 XFAIL）

状态：**CLOSED（2026-09-21，四拍全验收）**：拍 1 语义探针 + ADR 022 定案
      （42a0cf2）→ 拍 2 实现 ACCEPTED（84ab21e，总控五道门独立复证）→ 拍 3
      测试独立跑全量（86/86 checks + 3 xfail 登记 0 fail；23 套件回归语义面
      全绿、环境性超时/内存帽已校准）→ 收口（帽校准 + 矩阵 D8/G3a/B13 更新 +
      handoff 011 追记）。遗留：组件 2（deq_sort/A18 Max/IMax 扩展）NOT-VERIFIED
      （ADR 022 许可，预算；独立卡候选）。
依赖：与卡 011 的 G8/G9、卡 013 引擎通道互不依赖；按排产先于卡 012 M-B 的图侧
      部分——M-B 的 779 常量闭包实测 288/779 带 universe 参数（37%，
      /home/xkq/logs/012I/closures/Nat_testBit_land/dump.jsonl），撞本卡编码债

## 目标

`lean_vm/build_vm.py:5786-5798` 自述的边界：图 LEVEL 通道是整数显式级计数器
（X=peel 的 Succ 数），Param/MVar/Max/IMax 不可表达，带参使用点 ERR_UNSUPPORTED(4)。
本卡把该通道升级为能承载符号 level 的运行期语义，覆盖判定路径上的消费点，使：

1. `thm_imax` / `thm_max00` 两条 XFAIL 转绿并按 XPASS 协议摘除
   （is_prop 的非归一 level 形，K/level.cpp:174-186 normalizes_to_zero）。
2. univ 多态 accessor def 的 whnf 活锁转绿（g04b_c2_probe1.log：
   PProd.fst 骨栈 2000 步不 halt / 4GB 被 guard 杀——B13/WP1 编码债）。
3. Mathlib 闭包 ENV（288/779 带 universe 参数）可进图（卡 012 M-B 前置）。

判定路径消费点（对齐内核）：
- D1 mk_max / D2 mk_imax 智能构造（K/level.cpp:81-104,112-123）：infer_pi 折叠
  （K/type_checker.cpp:144-166）、is_prop（:383-389）、level defeq（:814-820）。
- D8 normalizes_to_zero / D4 is_equivalent（K/level.cpp:174-186,518）。
- A18 const 同名同级（K/type_checker.cpp:1209-1210；lazy-delta hints :1038）。
- B13 recursor rhs 的 universe 实例化（K/inductive.h:105-106）。

## 非目标

- 不做 D6 is_lt / D7 is_geq / A27 成功失败缓存（仅性能，VM_SPEC §12.6 TBD2）。
- 不做引擎侧（卡 013 的事）；不动 C++/compiler。
- 不重写 ref_vm.py（冻结参照机；参照语义已存在于 VM_SPEC §12.2 与 ref_vm
  `_inst_level`）。
- 不做 native_decide / reduceBool 信任边界（DESIGN §5）。
- 不修 G8/G9 / I_CASE 续推 / mode 续体（卡 011 队列其余条目）。

## 涉及文件（触碰面）

- `lean_vm/build_vm.py`（图侧新链/新臂；本卡主战场）
- `expr/tokens.py`（如需新 level token/通道编码；优先复用既有 token 与 ENV 元数据）
- `expr/model.py`（level 数据类已存在，通常只读）
- `tests/test_decl_injection_vs_lean.py`（摘 thm_imax/thm_max00，XPASS 协议）
- 新差分套件/探针（tests/ 或 scripts/ 下新文件）
- `docs/VM_SPEC.md` §12、`docs/ENV_FORMAT.md`（如需）、`docs/KERNEL_COVERAGE.md`
  D/B13/H2/G3a 行
- `docs/handoffs/` 续链（006-G-injection.md 或新链）
- `engine/*`、`compiler/*`、`model/runner.py`、`lean_vm/ref_vm.py`、
  `lean_vm/step_driver.py` 禁止触碰

## 权威依据

- K/level.cpp:81-104（D1）、:112-123（D2）、:125-150（D3）、:454（D5 normalize）、
  :518（D4 is_equivalent）、:174-186（D8 normalizes_to_zero）、:317-340（D10 instantiate）
- K/type_checker.cpp:144-166（infer_pi mk_imax 折叠）、:383-389（is_prop）、
  :814-820（level is_def_eq）、:101-123（infer_constant 实例化）
- K/inductive.h:105-106（B13 rhs universe 实例化）
- VM_SPEC §12.1-§12.7（WP2 规格；§12.7 编码期实例化现状 + "运行期 T_LVLSUB
  因子树指数复制不可行"失败史）、ENV_FORMAT §2.3（T_ENV_UNIVPARAMS 链）
- 差分 oracle：#LEVEL（tests/test_level_vs_lean.py，37/37 现状）+ #KDECL
  （tests/test_decl_injection_vs_lean.py）双通道已存在，禁止新造 oracle

## Verifier 集（完工唯一依据）

- [ ] thm_imax/thm_max00 转绿摘除（XPASS 协议：修复后仍留册即 FAIL）
- [ ] 新差分：非归一 level 形 theorem accept 且错误类别一致（#KDECL）
- [ ] univ 多态 accessor def whnf 与 oracle 逐字一致（活锁转绿，steps 原文落板）
- [ ] level defeq / infer_pi imax 折叠 / A18 同级 level 差分（#LEVEL 通道）
- [ ] 既有 23 套件回归全绿；图改动重编译 --sparse + 引擎 34/34 不倒退；
      图规模增量（dims/lookups/nnz）落文档
- [ ] 硬编码扫描零新增；ENV_FORMAT/VM_SPEC/矩阵 D/B13/H2/G3a 行同步

## 心跳预算

图侧大改，超过 1 分钟反馈即非法：开发迭代一律最小 env（tests/ 现有 toy 写法）；
拍 1 先用 oracle 探针钉死语义与编码方案可行性（§12.7 已翻过一次车：运行期
T_LVLSUB 因子树指数复制），探针落盘 tests/ 或 scripts/ 才算证据；每次编辑
build_vm.py 后 py_compile；增量差分随拍随跑，全量回归只在收尾。

## 对象差异评估（防线 §1 第 15 条）

- 内核该分支语义：递归树（level 是递归数据结构；D1/D2 智能构造含吸收规则、
  D5 normalize 递归、D10 instantiate 递归替换），非平坦查表。
- 与现有臂共享面：LEVEL 帧 dispatch（build_vm.py:5786-5798 的 lvl_* 命名边界）、
  I_PIL2/D_SORT/deq_sort/pl_prop 消费点、ST 六字段。
- 级联风险：§12.7 记录过一次"运行期逐 param 查表链 → 因子树指数复制不可行"
  （实例化因此被搬到编码期）；本卡若把符号通道搬回运行期，必须先探针验证
  编码方案的图规模增量可控；方案被否须有实测依据。

## 拍划分（按任务生命周期，每拍独立验收）

- 拍 1 语义设计师：oracle 探针钉死 D1/D2/D8/D4 在 4.33.1 上的期望行为 + 盘点
  build_vm.py level 消费点 gap 清单 + 设计 memo + ADR 022 草案（只写文档+探针）。
- 拍 2 图逻辑工程师：按设计 memo 落图侧实现，小步落盘，增量差分。
- 拍 3 测试工程师：独立跑 verifier 集（含摘 XFAIL 后的 XPASS 复核）+ 回归。
- 拍 4 审核工程师：独立复核五道门。
- 总控收口：落账 Handoff + 矩阵 + ARCHITECTURE + git。

## 决策引用

- ADR 014（范围扩容：全部接缝与规模转为在办工作包）
- ADR 020/021（非归一 level 形的分歧取证与实测更新）
- 卡 010 增补 5 遗留②（univ_arity 活锁转本卡）、卡 011 移交队列
- 本卡拍 1 产出 ADR 022（方案裁决，被拒方案必填）
