# 020. 声明注入协议的两个载体决策（kind/mode 载体 + is_prop 的 level 测法）

- 状态：accepted（总控 2026-09-19，卡 010 派工前定案）
- 关联：卡 010、ADR 012（G5/G10 门）、ADR 016（whnf raw-field 合同）、防线 §1.15/§1.17

## 背景

G 链首拍（G01，2026-09-18，`docs/handoffs/006-G-injection.md`）给出三机制的载体设计：
kind 走 TASK_CHECK 锚帧 E2、check_mode 走 **T_NULL（pos 0）X 字段**。总控派工前逐条
验码，结论：kind 载体可用（但"空闲"必须是实测结论），**mode 载体必须换**；另有一处
level 语义要预先定性，否则会把已知缺口变成静默假判。

## 决策 A：kind 与 mode 同载体 = TASK_CHECK 锚帧的 E2 槽（拒绝 T_NULL.X）

1. **注入数据是"每条声明一份"，只能挂在承载该声明的帧上。** 现锚帧
   `T_FRAME{V0=TASK_CHECK, V1=declared type, X=value, V2=next}`（`lean_vm/step_driver.py:197`），
   图侧读点为 `frV1`（类型根，`build_vm.py:5390`）、`frX`（值根，`:5433` 判 `X=0` 即 axiom 支）、
   `frV2`（next，`:5435` 判链尾）、`F2`（图自用的下一跳地址，`:5409`/`:5440`）。
   六槽里唯一未被 CHECK 链占用的是 **E2**（kickoff 处显式写 `fr1_E2_k = Zero`，`:5459`）。
   kind 需要 ≥4 值（axiom/def/theorem/opaque）+ unsafe 位，恰是 E2 这种多位数值槽的用途。
2. **T_NULL.X 不是空闲字段，是空指针哨兵。** `build_vm.py:289` 自注 "Position 0 is the
   T_NULL"＝位置 0 就是 null env 哨兵；而图里存在以**可能为 0 的指针**读 X 的站点
   （`:614 xF = fetch([x_], SF)`、`:948/:1012 fetch([x_], frF2)`、`:849 fetch([x_], anc)`）。
   把 mode 写进 `T_NULL.X` 会让每一次空 env 的 X 读取从 0 变 1，即**给全图广播一个
   伪 env 字段**——不是新增能力，是给既有路径注入脏数据。
3. **"空闲"必须是实测结论，不是 grep 结论。** 防线 §1.17 已有前科：M1-01b 的
   "T_NULL 哨兵必然无人读"论证被实测推翻（实际落当拍头 STATE，`docs/handoffs/010-M-cache.md` §18.2 勘正）。
   故本卡第一拍必须交付一个**载体空闲性实证件**：图与权重不动，仅让 driver 在锚帧 E2 写入
   非零哨兵值，既有 check_e2e / stepgraph / defeq 三族的**判定与步数逐字不变**才算载体可用；
   任一变即回退换槽并停手上报。该件落进新差分套件成为常设守卫。

### 被拒方案

- **拒 T_NULL.X（G01 原案）**：见决策 A 第 2 条，跨全图的哨兵污染，且与"环境是数据"无关——
  它不是给某条声明带元数据，是给位置 0 这个哨兵换含义。
- **拒 T_ENV_META 锚点位**：ENV_FORMAT §2.3 的锚点元数据是**已注册常量**的属性，而 CHECK
  发生在注册之前（非 unsafe 路）；unsafe 先注册后检查虽有锚点，但 kind 的 theorem/opaque
  之分不是 safety 位。硬塞会把"声明的簿记属性"与"常量的环境属性"混成一个位空间，卡 011
  的 G8（重名）来了无处放。
- **拒新增专用 ENV token / 新帧类型**：二进制与 ENV 格式变更，本卡的三条接缝用现成空闲槽即可，
  不值得引入版本化成本（AGENTS 完工定义 3 + 必须写 ADR 的时机清单）。
- **拒 driver 侧算 is_prop 再传布尔**：判定必须留在图内（验收铁律 1/2），driver 只搬数据。

## 决策 B：is_prop 的 level 归零测法沿用既有 sort-零测，非归一形记已知缺口

内核 `is_prop(e) = ensure_sort(infer_type(e)) ∧ normalizes_to_zero(sort_level)`
（`K/type_checker.cpp:383-389`）。`normalizes_to_zero`（`K/level.cpp:174-186`）对 `max` 要求
两边皆零、对 `imax` **只看 rhs**，其正确性依赖 `mk_imax` 智能构造把 `imax(_,0)` 归约为 `0`
（`K/level.cpp:112`，即矩阵 D2）。

图侧现测法是根节点 syntactic 比较：`_kind_eq_raw(pl_lvK, KL_ZERO)`（`build_vm.py:4451-4457`，
PI 链 proof-irrelevance 已在用），**没有 level 归一化**（D1 `mk_max` / D2 `mk_imax` 皆"缺失"，
`docs/KERNEL_COVERAGE.md:100-101`）。因此：

- 对已归一的 level（toy env 全部如此），两法等价。
- 对**非归一形**（如 `Sort (imax 1 0)`、`Sort (max zero zero)`，内核判 Prop），图的 syntactic
  测法判非零 → 新码 8 **假拒**。假拒比假放更显性（会把该过的声明报成 reject），但不许静默。

定案：新码 8 复用 sort-零测（与 PI 链同源，不另造第二套 level 判据），并在卡 010 的差分面
**必须实跑一条非归一 level 形的 theorem**：oracle 现跑给 accept 而图给 8，则该形按 `NOT-VERIFIED`
+ 矩阵行登记为 D1/D2 缺口在 G3 面上的具体表现（防线 §1.3：跳过＝未验收，必须记账）；
若 encoder 表达不出该形，同样记 NOT-VERIFIED 并写清原因，不许以"必然等价"入账。

### 被拒方案

- **拒"先在 driver 侧把 level 归一再传码"**：等于把内核语义搬到 Python，违反铁律 1/2。
- **拒本卡顺手补 D1/D2**：universe 归一化是独立语义分支（防线 §1.15 的对象差异评估要求），
  与注入协议无耦合，已排卡 012；在此顺手会把本卡验收面拖进 level 链的深水区。

## 预期后果

- 图侧新增一条 CHECK 臂（kind=thm ∧ sort-非零 → 码 8），臂序落在既有 5 之后
  （`reject_code` 链实装位置 `build_vm.py:6507-6511`，7>6>5>4；G01 记的 `:6053` 是
  quot_stuck 的 select，行号勘误）。E2 从"恒 0"变"可非 0"，故 CHECK 相关基线（check_e2e 15 例）
  必须逐字不变——这既是回归也是载体证明。
- 需 `--sparse` 重编 scratch + 引擎对拍 34/34 不倒退；dims 增量应为 O(1) 级（一条臂）。
- 决策 B 若命中非归一形，矩阵上多一条具名缺口行，卡 012 的 D1/D2 因此多一个真实反例来源（好事）。
