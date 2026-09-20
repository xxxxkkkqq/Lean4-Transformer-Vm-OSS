# 任务 011：G8（重名拒绝）与 G9（univ 参数查重）表达层

状态：open（ADR 014 排产；依赖卡 010 的注入协议先立）

## 目标

007 记的两条"编码/帧层不可表达"接缝改造为可表达：

- **G8 `check_name`**（`K/environment.cpp:102-109`）：当前 name→cid 双射使
  重名不可见。改造点：注入协议（010）在**注入时刻**校验名字是否已被占用
  （ENV 侧维护名字集），重复 add → 错误类别 `declaration already named`
  与真 lean 一致。不要求 token 流"发现"两个同名 cid（结构上不存在），
  要求的是"重名注入被拒"这个可观测行为。
- **G9 `check_duplicated_univ_params`**（`K/environment.cpp:111-125`）：
  图侧新增查重臂——对声明的 univ 参数链做 O(n²) 成对比较（新帧延续扫描，
  写法照 A17 peel 链；n≤个位数，成本可忽略），命中 → 既有"decl 有重复
  univ 参数"错误类（新错误码 8，与 4-7 并列），错误类别经真 lean 差分钉。

## 涉及文件

`lean_vm/build_vm.py`、`lean_vm/step_driver.py`（G8 侧，属主协调：与 010
代理串行）、`expr/tokens.py`（如需错误码编码）、新差分并入
`tests/test_decl_injection_vs_lean.py`（010 建的，扩展）、
`docs/VM_SPEC.md`、`docs/ENV_FORMAT.md`、`docs/KERNEL_COVERAGE.md` G8/G9 行、
`docs/handoffs/006-G-injection.md`（续）。

## Verifier 集

- [ ] G8 差分：新名 accept、重名 reject 且类别一致（含 axiom/def/theorem 三 kind）
- [ ] G9 差分：`u u` 重复参数声明被拒、`u v` 通过、类别一致
- [ ] 全回归 + 引擎不倒退 + 硬编码零新增

## 卡 010 移交队列（2026-09-21，增补 5 落地；排产时决定并入本卡还是另立新卡）

1. **I_CASE 主前提 whnf 续推**（摘 `g04iv_eG4IV2` XFAIL 的正门）：核侧
   `K/inductive.h:93` 对 casesOn 主前提先 whnf，图 I_CASE 无此续推（005
   F7-01 "spine-root 交付"家族）。证据：handoff 006 G04 / `g04b_diag.log`。
2. **universe 多态 accessor def 的 whnf 活锁**（B13/WP1 编码债实证新增）：
   `PProd.fst` 类 accessor spine 在当前 univ_arity=0 编码下 2000 步不 halt
   （RSS 4GB 被 guard 杀，`g04b_c2_probe1.log`）。数学库规模（卡 012 M-B）
   会大量撞它，优先级建议排前。
3. **归约层 ENV 动态名字依赖排查**：cs_build succ 规则运行时现造
   `Nat.pred t`（静态引用闭包不可见，bisect 实证 `g04b_bisect.log`）——
   盘点还有哪些名字被归约动态查表，决定 ENV 侧保留纪律
   （"环境是数据"铁律边角，VM_SPEC §16.7 stage C 记录）。
4. **mode 位跨 ST 续体携带**（G03 登记，摘 `g03g/g03h` 两 XFAIL）：APP
   参数 / lam·let body 自引用现走保守侧假拒 7。
5. **编号勘正（排产先办）**：本卡正文写"G9 新错误码 8"已过时——8=
   thmTypeIsNotProp（G02）、9=mutualWF（G06）已被 010 链占用，G9 从
   **码 10** 起编（ENV_FORMAT §2.8 为准）。
