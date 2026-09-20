# DESIGN — Lean 4 kernel as a transformer

> 本文件是目标、验收标准与范围的权威说明。
> 仓库现状见 [ARCHITECTURE.md](../ARCHITECTURE.md)；指令级规格见
> [VM_SPEC.md](VM_SPEC.md)；现行推进口径见
> [KERNEL_COVERAGE.md](KERNEL_COVERAGE.md) + [plans/](plans/)（Phase 0-7
> 旧阶段台账已移 [archive/PLAN.md](archive/PLAN.md)）。

## 1. 目标

把 Lean 4 内核的判定过程——WHNF（弱头归约）、类型推断（infer）、定义等价
（is_def_eq）、声明检查（check）——编码成一台 ALM（Append-only Lookup
Machine）计算图，再由该图解析构造出 Transformer 权重（不训练），使
Transformer 的自回归前向传播执行内核的检查步骤。

### 动机

为什么不直接用外面的 lean 二进制，而要把内核搬进权重：

- **生成与核查同基底**（主押注）：写证明的权重与查证明的权重是同一组参数，
  自我核查成为模型的内部行为，核查信号与生成同处一个可微基底之上。
- **可微裁判**（远期支线）：外部内核对证明生成器只回传零梯度的 1-bit 奖励，
  内核进权重是"检查证明"进入反向传播路径的前提。该支线的前提未解：实测
  fp32 是可用下限、fp16/bf16 过不了判定（AGENTS 铁律 4、
  `docs/HYBRID_ARCH.md`），需另造可微通道才可兑现，不构成当前交付承诺。

## 2. 验收标准

对同一输入（一个已 elaborated 的声明及其环境），判定必须与真 Lean 4 内核
**完全一致**：

1. 接受 / 拒绝一致；
2. 拒绝时的错误类别一致；
3. 推断出的类型通过真内核的 `is_def_eq` 与声明类型判定一致。

权重与图在数值上接近只是编译期的开发检查，不是验收标准；容差不能替代
判定一致。语料不得硬编码答案：输入取自环境或由环境生成，期望结果由真
lean 二进制给出。

## 3. 范围

**内核与前端的分界。** 内核只接收已 elaborated 的项，它看不到源码、宏和
tactic。本仓库实现的是内核。parser、宏展开、elaborator、tactic 引擎不属于
内核，本仓库不实现。

**待定决策（输入面）。** 是否让产品直接接受 Lean 源码，有两种口径：

- 口径 A（推荐）：前端复用真 Lean（parse + elaborate + tactic 由真 Lean
  完成，产出 kernel 项与环境），本仓库只做内核检查。产品形态是"内核
  检查器"。
- 口径 B：产品本身完成从源码到判定的全过程。这要求重写 Lean 的
  parser / elaborator / tactic 引擎 / 类型类搜索等，规模远大于内核，且
  正确性的可信部分仍在内核，因此不在可行范围内。

当前实现对应口径 A 的内核部分，输入是已编码的 kernel 项。最终口径待定。

## 4. 实现原则

1. **一张图，一份权重。** 全部内核操作编码进单个解释器图
   （`lean_vm/build_vm.py`），编译出一份权重。不存在按操作拆分成的多个
   图，也不存在外部 Python 程序在运行时串联它们。
2. **循环由时间承担。** WHNF 迭代、DEFEQ 递归、Nat 进位等每一步都是一次
   自回归 token 生成，图中每个操作只写一次，图深度是常数，不随输入规模
   增长。
3. **环境是数据。** 常量表（类型、值、构造子、recursor 规则、universe
   参数、reducibility、quot 信息）序列化为 token 流，图读取它来驱动
   归约与判定；图内不得针对具体常量写死分支。
4. **唯一裁判是真 Lean 二进制。** 仓库内的 Python 参照机与图只用于开发
   迭代，正确性一律以真 `lean` 的判定为准。

## 5. 需要复刻的内核范围

以 `/home/xkq/lean4/src/kernel/` 为参考（安装的 oracle 是 v4.33.1 二进制；
两者若不一致以二进制为准）。检查一个已存在的声明所需的部分：

- `type_checker.cpp`：`whnf` / `whnf_core`、`infer_*`、`is_def_eq` 及其全部分支、
  `check` / `ensure_sort` / `ensure_pi` / `is_prop` / `check_level`。
- `inductive.cpp` 中的 `inductive_reduce_rec`（iota 归约），由环境的
  recursor 规则数据驱动。归纳声明本身的合法性检查（严格正性、universe
  约束）不需要复刻：环境中的归纳类型是导入的现成数据。
- `quot.cpp`：`Quot` 的归约规则。
- `level.cpp`：universe 的归一化与实例化。
- `expr` / `instantiate` / `replace` / `abstract` / `local_ctx`：项的实例化与
  局部上下文。
- `environment.cpp`：声明加入时的检查路径（infer 值类型 → 与声明类型
  `is_def_eq`；theorem 还需 `is_prop`；以及 `check_no_metavar_no_fvar`）。
- `declaration.h`：`constant_info` 的全部字段（axiom / definition / theorem /
  opaque / quot / inductive / constructor / recursor），这是环境数据的格式。

内核在收到 mvar 时返回卡住状态；只要输入是无 mvar 的 elaborated 项，内核
侧不需要 mvar 求解。`native_decide` / `Lean.reduceBool` / `reduceNat` 会调用
编译后的代码，真内核通过 axiom `Lean.ofReduceBool` 信任它；要判定一致，需
同样把这条路径视为 axiom，并在文档中声明该信任边界。

## 6. 非目标

- 不训练模型：权重由图的解析构造得到。
- 不重写 Lean 前端（parser / elaborator / tactic）：见 §3 口径 A。
- 不使用自己写的内核实现作为正确性判据。
- 不把具体定理的答案或特定常量的结果预置进权重或语料。

## 7. 风险

1. **内核规则的完备性与细节。** 需要逐条对齐 `is_def_eq` 的分支、iota
   归约（嵌套、indices、k 标志）、universe 多态、quot、字符串字面量等；
   任一分支不一致都会导致判定不同。这是工作量主体，且必须逐分支配真
   lean 差分测试。
2. **环境规模。** Mathlib 的常量及其依赖闭包很大，不能整体放入 token
   前缀；需要按证明抽取闭包、共享与紧凑编码，并完整带上
   inductive / recursor / quot 元数据。
3. **数值表示与判定的确定性。** 图用浮点残差流承载整数与逻辑值。验收
   要求判定一致，因此数值方案必须保证判定确定；若某个分支在浮点下会
   不稳定，需要改编码或表示，而不是放宽验收。
4. **性能。** 一次微步一个 token、严格串行，证明规模下的内核步数很大；
   这是是否可用的关键约束，需要专门处理（批处理、KV cache、更省的数值
   方案等）。
