# 任务 011：G8（重名拒绝）与 G9（univ 参数查重）表达层

状态：**CLOSED（2026-09-26，总控五道门）**——拍 1（G8+G9 实现）2026-09-23
验收 PASS；拍 2（全量 23 套件回归，测试工程师独立 verifier）2026-09-26 收口：
**23/23 rc=0、语义零 FAIL**（reg1 17 套件直接 PASS + reg2 6 套件复跑/补跑
PASS：decl_injection 103/103+3 xfail、defeq_cache ALL OK、engine 34/34、
stepgraph_vs_refvm 37/37、mutation A16/B8、reducenat 31+16——末者帽
1500→2400 按 015 先例校准，两次独立杀点 1500.1s 实证）。reg2 中 5 套件
系 09-23 前代理死亡前按同模板完成，续接代理逐条验真（代码态/oracle 自检/
帽参/串行时序/语义行）后采信，审核工程师独立复核确认，总控追认。审核
工程师复核 **PASS**（记账缺陷 2 处已当场勘正）；lead canary ref_vs_lean
34/34 + engine_vs_refvm（`~/logs/011G89/lead2/`）。拍 1 证据：差分行集
17/17（G8 8 + G9 9，含顺序行）总控独立复跑 rc=0（417s，`~/logs/011G89/lead/`，
oracle 4.33.1 现跑）；011 scratch（34,468/4,495/235,424，dims +76/+6/+394
O(1)）引擎对拍 34/34 rc=0（argmax/softmax 双流一致）；py_compile 过、硬编码
零新增。执行链与命令原文见 handoff 006-G「卡 011 拍 1 续接」节；文档同步
VM_SPEC §16.8 / ENV_FORMAT §2.8 / KERNEL_COVERAGE G8/G9 行已落。

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
  univ 参数"错误类（新错误码 **10**，编号勘正见移交队列第 5 条；错误类别
  经真 lean 差分钉，核侧文案 `duplicate universe level parameter`）。

## 涉及文件

`lean_vm/build_vm.py`、`lean_vm/step_driver.py`（G8 侧，属主协调：与 010
代理串行）、`expr/tokens.py`（如需错误码编码）、新差分并入
`tests/test_decl_injection_vs_lean.py`（010 建的，扩展）、
`docs/VM_SPEC.md`、`docs/ENV_FORMAT.md`、`docs/KERNEL_COVERAGE.md` G8/G9 行、
`docs/handoffs/006-G-injection.md`（续）。

## Verifier 集

- [x] G8 差分：新名 accept、重名 reject 且类别一致（含 axiom/def/theorem 三 kind）（拍 1：8 行 rc=0）
- [x] G9 差分：`u u` 重复参数声明被拒、`u v` 通过、类别一致（拍 1：9 行 rc=0）
- [x] 全回归 + 引擎不倒退 + 硬编码零新增（拍 2：23/23 rc=0 语义零 FAIL，09-26 收口）

## 卡 010 移交队列（2026-09-21，增补 5 落地；拆分/合并裁决已定，见下节）

1. **I_CASE 主前提 whnf 续推**（摘 `g04iv_eG4IV2` XFAIL 的正门）：核侧
   `K/inductive.h:93` 对 casesOn 主前提先 whnf，图 I_CASE 无此续推（005
   F7-01 "spine-root 交付"家族）。证据：handoff 006 G04 / `g04b_diag.log`。
   → **转卡 016**。
2. **universe 多态 accessor def 的 whnf 活锁**（B13/WP1 编码债实证新增）：
   `PProd.fst` 类 accessor spine 在当前 univ_arity=0 编码下 2000 步不 halt
   （RSS 4GB 被 guard 杀，`g04b_c2_probe1.log`）。数学库规模（卡 012 M-B）
   会大量撞它，优先级建议排前。
   → **已清偿（卡 015：I_PROJ 通用抽取，UProd.fst/snd 差分行转绿，a0d18cb）**。
3. **归约层 ENV 动态名字依赖排查**：cs_build succ 规则运行时现造
   `Nat.pred t`（静态引用闭包不可见，bisect 实证 `g04b_bisect.log`）——
   盘点还有哪些名字被归约动态查表，决定 ENV 侧保留纪律
   （"环境是数据"铁律边角，VM_SPEC §16.7 stage C 记录）。
   → **转卡 016**。
4. **mode 位跨 ST 续体携带**（G03 登记，摘 `g03g/g03h` 两 XFAIL）：APP
   参数 / lam·let body 自引用现走保守侧假拒 7。
   → **转卡 016**。
5. **编号勘正（排产先办）**：本卡正文写"G9 新错误码 8"已过时——8=
   thmTypeIsNotProp（G02）、9=mutualWF（G06）已被 010 链占用，G9 从
   **码 10** 起编（ENV_FORMAT §2.8 为准）。
   → **已办（2026-09-21 总控，正文已改码 10）**。

## 排产裁决（2026-09-21 总控）

- 本卡范围收敛为 **G8+G9 注入错误面**（同一合同面：注入时刻的可观测拒绝
  行为），拍 1 = 图逻辑工程师实现（G8 driver 簿记臂 + G9 图内查重臂 +
  差分行集入 `tests/test_decl_injection_vs_lean.py`）。
- 队列 1/3/4 三条同属"归约续推与状态携带"家族，另立**卡 016**
  （`docs/plans/016-reduction-continuation-family.md`，待派）；本卡拍 1
  收口后按机器纪律串行排产。
- 错误码占用以 `docs/ENV_FORMAT.md` §2.8 为唯一权威；新码申请先在卡内
  登记再起编。
