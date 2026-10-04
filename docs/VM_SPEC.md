# VM_SPEC — Lean Kernel VM 操作码与编码规格（v1 草案）

> 本文是 VM 的**唯一事实来源**。`expr/model.py`、`expr/tokens.py`、
> `lean_vm/ref_vm.py`、`lean_vm/build_vm.py` 都必须与本文一致；
> 改语义先改本文。数据模型对应 `lean4/src/kernel/{expr.h,level.h}`。
> 状态：v1 草案，覆盖 Phase 1–2（WHNF 切片）；INFER/DEFEQ 操作码在 §8
> 预留，Phase 5 定稿。最后更新：2026-08-29。

## 1. 机器模型：Krivine 式环境机（本规格的核心决策）

Weak head normalization 是环境机（Krivine machine）的经典问题。本 VM
采用 **链接（link）而非物理替换**：

- 状态 = `(焦点表达式位置, 环境链, 帧栈)`，全部住在 token 流里。
- **beta/zeta 不改写树**：进入 lambda 体时压入一个 `LINK` token
  （绑定 = 值位置 + 指向上一链接的指针）；`bvar(i)` 求值 = 沿链走 i 步
  取值位置。追加只读（append-only），与 ALM 的注意力检索天然对齐
  （链深度计数 = `fetch_sum`/CumSum，检索 = `fetch_by_position`）。
- 这从根上替代旧架构"逐 token 物理拼接"的路线，也使 beta 的代价与
  替换树的大小无关。
- 求值策略是 **call-by-need**：参数在头暴露出 lambda 之前不求值，
  LINK 持有未求值的 (expr 位置, 环境链) 闭包。对弱头归约语义安全。

与 Lean 内核的对应：WHNF 主循环 = Krivine 循环 + delta（常量展开）
+ zeta（let）+ nat 操作码；INFER/DEFEQ 作为同一机器的其他任务
（§8），共享帧栈与链接机制。

## 2. Token 格式与数值域

每个 token 是 `(K, V0, V1, V2, X)` 五个数值字段 + 位置 `POS`。
五个字段各对应 ALM 图中一个 `InputDimension`（旧架构只有 4 个，新增 X）。
**token 种类常量（唯一权威表，`expr/tokens.py` 同步维护）**：

| K | 名称 | 用途 |
|---|---|---|
| 1..12 | K_BVAR..K_PROJ | 表达式节点（§4，与 `expr/model.py` 一致） |
| 13 | T_LIT_DIG | Nat 数字链的位（V0=0..9，V2=链头） |
| 21 | T_NAME | 名字表项（V0=nid，V1=父 nid） |
| 22 | T_ENV | ENV_HDR（§3） |
| 23 | T_ENV_META | ENV_META（§3） |
| 30 | T_PEND | Krivine 待求值参数（V0=arg 位置，V2=前一 PEND，X=压入时环境链头） |
| 31 | T_LINK | 环境链接（V0=值位置，V1=链深，V2=上一链接，X=捕获的环境链头，E2=1 标记 binder marker——见 §8） |
| 32 | T_FRAME | 帧（V0=task，V1=焦点，V2=caller，X=阶段） |
| 33 | T_STATE | ALM 微步状态（A..F = 7 字段重命名，§10.1） |
| 34 | T_PI_CLO | 机器发射的 Pi 类型，两半各为闭包（V0=域根，V1=体根，X=域 env，E2=体 env，§8） |
| 24..29, 35..38 | T_ENV_DEFVAL..T_ENV_RECEXTRA | 声明元数据专用 token（ENV_FORMAT §2.2/§2.4；T_ENV_LIST=35 的 V2=role 0=all/1=ctors/2=lparams） |
| 39 | T_ENV_UNIVPARAMS | 常量 lparams 名字链头（V0=cid，V1=T_ENV_LIST(role=2) 链头，F2=next_meta；§12.1） |
| 201..204 | OUT_VAL / ACCEPT / REJECT / HALT | 输出（§7.3、§7.4） |

| 字段 | 用途 | 数值域（v1 限制） |
|---|---|---|
| K | 种类/操作码，门控查表主键 | 1..255 |
| V0, V1 | 依 kind 而定的载荷（指针、id、计数） | 0..4095 |
| V2 | **父指针**（expr 节点 → 父节点位置；frame/link → 前驱） | 0..4095 |
| X | 第 5 字段，避免续接 token（见 §4） | 0..4095 |

Phase 2 起 token 实为 **7 字段** `(K, V0, V1, V2, X, E2, F2)`：E2/F2 是
第 6/7 字段，供 T_STATE（§10.1 的 A..F 命名）与 T_PI_CLO（X/E2 = 两个
独立 env）等需要双载荷的机器 token 复用；expr 节点不用 E2/F2。

**表示约束**（编码层限制，不是验收标准）：所有字段是非负整数；ALM
残差流用 float64，整数在 2^24 内精确，但 attention key 表达式含 `k²`
项且 `HARD_K = 1e4`，故 v1 硬限制 **序列长度 ≤ 4096、所有指针/计数
≤ 4095**。（放宽到 2^24 需 transformer-vm 的 hull-attention，列入
Phase 4+。）验收标准是判定与真 Lean 4 内核一致，见 DESIGN.md §2。
"0" 是合法空指针（NULL）；指针从 0 起算，token 流的第 0 个位置即 ENV 区头。

## 3. 名称、常量与 ENV 前导区

内核逻辑只做**整数相等**判断，字符串只活在工具链里：

- **nid**（name-id）：每个名字（含字符串字面量内容、fvar/mvar 名）在
  ENV 前导区的名字表中登记一次，nid 从 1 起（0 = NULL）。
- **cid**（constant-id）：每个环境常量一个 cid，从 0 起。

**序列布局**（追加只读；`E_n` 表示 ENV 区内第 n 个常量的块）：

```
[名字表: K=NAME, V0=nid, V1=父nid(层级名,可0), V2=0]…（nid 按出现顺序）
[E_0]: ENV_HDR | type树 | value树(若是定义) | ENV_META
[E_1]: …
[证明树]  [目标树]  [工作区(自回归生成)]
```

- `ENV_HDR`: `K=ENV, V0=cid, V1=type根位置, V2=value根位置(无定义则0),
  X=flags`。flags 位 0 = is_definition，位 1 = is_constructor，
  位 2 = is_inductive，位 3 = is_recursor（v1 只用位 0/1）。
- `ENV_META`: `K=ENV_META, V0=univ_arity(类型参数个数), V1=0, V2=0,
  X=0`。（recursor 的 major/param 计数等 Phase 5 扩展本 token。）
- type/value 树用 §4 的节点编码，树内父指针指向本树根。
- v1 约束：常量的类型/值中出现的常量必须已在前面的块中登记
  （拓扑序，参照机构造时保证）。

## 4. 表达式节点编码（K = `expr/model.py` 的种类常量）

所有节点：`V2 = 父指针`；`X` 字段用于吸收"第三个载荷"，避免续接 token。

| K | 节点 | V0 | V1 | X |
|---|---|---|---|---|
| 1 K_BVAR | bvar | de Bruijn index | 0 | 0 |
| 2 K_FVAR | fvar | nid | 0 | 0 |
| 3 K_MVAR | mvar | nid | 0 | 0 |
| 4 K_SORT | sort | level 子树根位置 | 0 | 0 |
| 5 K_CONST | const | cid | level 参数块根位置（无则 0）| 0 |
| 6 K_APP | app | fn 位置 | arg 位置 | 0 |
| 7 K_LAM | lam | domain 位置 | body 位置 | binder_info (0..4) |
| 8 K_PI | pi | domain 位置 | body 位置 | binder_info (0..4) |
| 9 K_LET | let | domain 位置 | value 位置 | **body 位置** |
| 10 K_LIT | lit | 见 §5 | literal_kind (0=Nat,1=Str) | 0 |
| 11 K_MDATA | mdata | child 位置 | 0 | 0 |
| 12 K_PROJ | proj | nid(结构名) | 字段 idx（0 基）| **child 位置** |

- `K_LET` 的 nondep 布尔不进 token（内核归约不读它；仅在工具链保留）。
- `K_APP` 的 fn 是 spine 头：`app(f,a1)(a2)…` 编码为右折叠嵌套，
  头 = 最内 App 的 V0。
- **level 子树**（K = `level/model` 常量，1-based over level_kind）：
  `KL_ZERO=1`（V0=0），`KL_SUCC=2`（V0=child），`KL_MAX=3 / KL_IMAX=4`
  （V0/V1=两 child），`KL_PARAM=5 / KL_MVAR=6`（V0=nid）。
  level 节点同样 V2=父指针。**v1 即采用完整结构编码**（不是旧架构的
  "高度整数"近似），INFER/DEFEQ 的 level 比较无需返工。
- const 的 level 参数块：V1 指向第一个参数的 level 子树根；参数间
  通过 ENV_META 的 `univ_arity` + level 树的**兄弟链**组织：每棵
  参数 level 树的根把 `X = 下一参数根位置`（最后一个 = 0）。
  （level 根的 X 复用为零冲突：非根 level 节点 X=0。）

## 5. Nat 字面量：数字链（无量程限制的机制）

`lit(Nat v)` 编码为 **十进制小端数字链**：

```
K=LIT, V0=位数 n, V1=LIT_NAT        ← 链头（H）
  K=LIT_DIG, V0=dᵢ∈{0..9}, V2=H     ← 位置 H+2+2i（步幅 2，见下）
```

- v = Σ dᵢ·10ⁱ。零 = 位数 1、d₀=0（规范形：最高位 dₙ₋₁≠0，n=1 除外）。
- **步幅 2（2026-08-30 定稿）**：第 i 位数字住在 `H+2+2i`，不是紧邻链头。
  原因：ALM 机器每个微步只能追加一个数字 + 一个 STATE token（自回归
  状态必须占最后位置），机器发射的数字链天然是"数字-状态-数字"交错；
  encoder/ref_vm 发射链时补显式 NULL gap token 以对齐同一步幅。解码按
  位置公式读取（不扫描）。机器发射的链 V0 允许是出位数上界（尾部前导
  零填充），解码按求和计算值，前导零无害。
- 任意大 Nat 的算术 = 数字链上的逐位查表 + 进位 token（加法）、
  移位-加循环（乘法，时间换深度）。`NAT_MAX` 类常数被禁止。
- 字符串字面量 v1 不编码（LIT_STR 标记，内核的 string→constructor
  展开属 Phase 5）。

## 6. 帧栈与链接

**帧**（工作栈 = 通过 V2 链成 caller 链）：

```
K=FRAME, V0=task, V1=焦点位置, V2=caller 帧位置, X=阶段/等待计数
```

**链接**（环境链；追加只读，同一表达式子树可被多条链复用）：

```
K=LINK, V0=值位置(未求值的 arg), V1=链深(0=最先压入), V2=上一链接位置,
X=创建时捕获的环境链头
```

- **bvar(i) 解析**：从当前链头沿 V2 回走 i 步，取该 LINK 的
  (V0=值位置, X=捕获环境)。参照机直接走链；ALM 侧 = 链深计数
  （`fetch_sum` 对 K=LINK 累计）+ 按位置检索。
- **Krivine 待求值参数栈**（PEND）：遇到 APP 时把 (arg 位置, 当前环境链头)
  压栈；遇到 LAM 时弹栈并转成 LINK。参照机用 Python 栈；ALM 侧将用
  T_PEND token 链 + run-id 区分并发求值（Phase 2 定稿）。
- 下降进 lam body 时压 LINK；任务返回时弹到 caller 帧。

## 7. 操作码表（Phase 1–2：WHNF 切片）

task 常量：`T_WHNF=1, T_NAT=2`（v1）；`T_INFER=3, T_DEFEQ_L=4,
T_DEFEQ_R=5, T_CHECK=6`（§8 占位）。输出 token 也用 K 标记
（`OUT_VAL=201, ACCEPT=202, REJECT=203, HALT=204`）。

> **参照实现**：`lean_vm/ref_vm.py` 按本节语义逐字实现，已于 2026-08-30
> 对真 Lean 4.33.1 二进制在 32 个 WHNF 切片用例上 100% 一致
> （tests/test_ref_vs_lean.py）。机器行为已按内核实测校准：
> `Nat.div a 0 = 0`、`Nat.mod a 0 = a`、`Nat.zero` 停在构造子、
> `Nat.succ/pred/add/sub/mul/pow/div/mod/beq/ble` 在字面量参数上
> 由内核原生归约。

### 7.1 T_WHNF 主循环（对焦点 `e`，环境链 `ρ`）

| 焦点 kind | 动作 |
|---|---|
| APP | 压帧 `(T_WHNF, e.V0, AWAIT_HEAD)`，切到 fn |
| LAM / PI / SORT / FVAR / BVAR(自由) / PROJ(不可约) | WHNF 完成，按 §7.3 返回 |
| CONST(cid) | 查 ENV：有定义 → 压 `(T_WHNF, value根, 新链=ρ)`（**delta**；level 参数实例化 Phase 5，v1 仅处理 univ_arity=0 常量）；无定义（公理/归纳类型/构造器）→ WHNF 完成 |
| LET | **zeta**：压 LINK(value 位置, 链=ρ)，焦点 = body 位置（X 字段），链 +1 |
| LIT | 头是 `Nat.*` 构造器应用 → §7.2；否则完成 |
| MDATA | 焦点 = child（内核忽略 mdata 包装，expr.cpp 对应行为）|

APP 归约：fn 的 WHNF 结果是 LAM → **beta**：LINK(arg 位置, fn 原链)，
焦点 = body，链 +1，继续循环。头是 CONST `Nat.succ/add/…` → 转 §7.2。
头是其他（未折叠常量、fvar…）→ 整个 app 为 WHNF。

### 7.2 Nat 操作码（焦点 = 数字链头或可归约 Nat 项）

进入条件：WHNF 头解析出 `Nat.add` 等内核已知 nat 操作。帧按
`(T_NAT, op, 阶段)` 推进：先对每个参数跑 T_WHNF（阶段计数在帧 X），
参数就绪后执行：

| op | 语义（对数字链） | 实现要点 |
|---|---|---|
| NAT_SUCC | v+1 | 逐位 +carry |
| NAT_ADD / SUB | a±b（SUB = 截断，同内核 Nat.sub）| 逐位查表+carry |
| NAT_MUL | a×b | 逐位部分积 + 移位累加，循环=时间 |
| NAT_DIV / MOD | ⌊a/b⌋ / a−b·⌊a/b⌋（b=0 → 返回 b 本身，同内核 Nat.div/Nat.mod）| 试商循环，时间换深度 |
| NAT_EQ / LE | beq / ble → 输出构造器 `Bool.true/false` 的 cid | 逐位 AND/OR |
| NAT_GCD / LAND / LOR / XOR / SHIFT… | Phase 2+ 追加，同机制 | — |

结果以新数字链 token 追加到工作区，再按 §7.3 返回。

### 7.3 返回协议

任务完成时：生成 `K_OUT_VAL, V0=结果位置, V2=当前帧` token，
弹出当前帧，焦点/caller 状态从 caller 帧恢复。整个证明验证以
`K_ACCEPT` / `K_REJECT(code)` 收尾（INFER+DEFEQ 任务在 §8 后接入；
v1 的 WHNF-only 验证 = 目标类型与推断类型互为 WHNF-CONV，Phase 5）。

### 7.4 停机与错误码

- `K_HALT, V0=0`：正常停机（结果已就绪）。
- `K_REJECT, V0=err_code`：1 = 类型不匹配，2 = 常量缺失，
  3 = 编码越界（指针/长度超 §2 限制），4 = 不支持构造（v1 遇到
  LIT_STR / mvar 等）；WP7 增补：5 = typeExpected（声明类型的类型非
  Sort，K/type_checker.cpp:70），6 = 声明根节点含自由/约束元变量
  （K/environment.cpp:87-95），7 = safe 上下文引用 unsafe/partial 常量
  （kernel_exception .other，K/type_checker.cpp:110-117；门控数据 = 锚点
  F2=use_reject，见 §16.3 与 ENV_FORMAT §2.3）。卡 010 G02 增补：
  8 = theoremTypeIsNotProp（theorem 的声明类型非 Prop，
  K/environment.cpp:200-202；门控数据 = CHECK 锚帧 E2 的 kind_code=3，
  见 §16.4 与 ENV_FORMAT §2.8）。见 §16.2。错误定位 = 焦点位置的父指针链（V2 链），
  供 Phase 5 的 error_path 输出。（M4.3 落地：error_path 由驱动器侧
  `lean_vm/localize.py` 消费 V2 链 + 机器 reject 焦点/`run_infer` 结果实现，
  不改图、不新增发射 token——见 §11.3。）

## 8. INFER / DEFEQ（Phase 5 M1 定稿，参照机语义）

内核算法源：`type_checker.cpp` infer_type（infer_app/lambda/pi/let/
constant，L88–327）与 is_def_eq（L780–1000）。类型在机器里不是值——
是**闭包 `(类型根位置, env)`**，与 expr 同机制（Krivine），infer 产出、
defeq 消费的类型全部走这个表示。

**关键机制（Phase 5 新增）**：

- **binder marker**：T_LINK 的 E2=1 标记"fvar 模拟"链接，V0=该 binder
  的 domain **类型闭包**，X=domain 的 env。`_resolve` 命中 marker 时
  （a）WHNF：焦点卡住（fvar 无 reduction）；（b）INFER：返回 (V0, X)
  即 domain 闭包——Krivine 版的 `infer_bvar = local_decl 类型`。
  beta 一侧的 value 链接（E2=0）则照常 INFER 其值的类型。
- **T_PI_CLO（K=34）**：infer_lambda 需要返回 `Pi(dom, body_type)` 但
  两半各带独立 env（域用 lambda 的 env，体用 binder marker env）。
  K_PI 树只有一份共享 env 无法表达，故机器发射 T_PI_CLO token：
  V0=域根、V1=体根、X=域 env、E2=体 env。语义上
  `(K_PI, e) ≡ T_PI_CLO(dom=e下域, body=link(marker,e)下体)`；
  DEFEQ 的跨形比较（K_PI vs T_PI_CLO）按 `_pi_parts` 拆开后对齐。
- **level**：v1 的 infer_pi 只做数字 level 的 imax/max
  （toy env 无 univ 参数）；level 树结构比较进 Phase 5 后段。

**INFER（ref_vm.infer，checking 模式子集）**：

| 焦点 K | 规则（对齐内核） |
|---|---|
| BVAR | resolve env：marker → domain 闭包；value 链 → infer(值) |
| CONST | const_type_pos[cid]（单态 env：instantiate_type_lparams 直通） |
| LIT | 发射 Const(Nat)（lit_type） |
| SORT | Sort(level+1)（机器发射 level 链） |
| APP | spine 剥离 → 逐参：infer(fn) → whnf → `_pi_parts`（ensure_pi）→ infer(arg) → **defeq(arg 类型, domain)**（非 just is_def_eq，内核 infer_app 同）→ 体 env link 上 arg 闭包（类型代入 = Krivine link） |
| LAM | ensure_sort(infer 域)；域上压 binder marker；infer 体（env 带 marker）；发射 T_PI_CLO |
| PI | ensure_sort 两侧；imax（l1=0 → l2，否则 max）；发射 Sort |
| LET | infer(value) → **defeq(值类型, declared)**；declared 上压 marker；infer 体（内核 infer_let） |

**DEFEQ（ref_vm.defeq，M1 子集）**：主循环双游标下降——快速结构
（同位置同 env 直通、CONST 同 cid、SORT level 相等、LIT 链值相等）、
binding 两侧（域先比，再各自压 marker 比体——两侧 marker 独立压而非
共享一个链接，因两侧外层链不同；域已证相等故语义与内核共享 fvar
等价）、BVAR 双侧 resolve 后续降、MDATA 直通（内核对 mdata 全程透明）、
跨形 Pi（K_PI↔T_PI_CLO）；否则 `_soft_whnf` 双侧（nat-op 对非字面量
的 ERR_TYPE/ERR_OVERFLOW 吞掉→卡住）后继续；双侧卡住做结构比较：
spine（arity/头/逐参）与 **Nat ctor↔字面量**（`Nat.zero≡0`、
`Nat.succ x ≡ x+1`，内核 reduce_nat 类比）。

**M1 验收（2026-09-02）**：`tests/test_ref_infer_defeq.py`
**37/37 vs 真 lean**（21 DEFEQ + 16 INFER；oracle 侧
`#ORACLE_DEFEQ`/`#ORACLE_INFER` 走 elaborate→synthesizeSyntheticMVars
→instantiateMVars→Meta.isDefEq/inferType——数值字面量遗留 instance
mvar，不合成则 isDefEq 全盘假阴性的坑已探针钉死）。
回归：RefVM WHNF 34/34、step 图 34/34、权重保真 34/34
（worst 1.08e-09）、C++ 引擎 34/34。

### 8.1 M3 扩展（proof irrelevance / eta / 结构 eta / proj）

内核算法源：`type_checker.cpp` L932 `is_def_eq_proof_irrel`、L383
`is_prop`、`infer_proj`（L247）、`try_eta_expansion_core` /
`try_eta_struct_core`。M3 在 M1 子集上新增：

- **binder 身份（T_LINK.F2 = bid）**：binding 比较时两侧各压一个
  marker，但共享同一 bid（t 侧 marker 位置，`_stamp_bid`）；同一
  binder 的 BVar 在两侧 resolve 到相等 bid → 直通（kernel fvar 名相等
  / 共享 local decl 的模拟）；**不等 bid 的 marker 对是卡住对**，落到
  stuck 处理（proof-irrel/eta/spine），绝不原地 continue——否则主循环
  死循环（M3 调试实测的坑）。
- **proof irrelevance**（stuck 对上**最先**做，内核顺序）：`is_prop(e)
  = ensure_sort(infer_type(e))` 的 level 归一化为 0——即先 infer 一次
  再取 sort level（直接对类型取 level 是错的，类型是 `True` 不是
  `Sort`）；是 Prop 则 t ≡ s iff defeq(两类型)。infer 越界（
  ERR_TYPE/ERR_UNSUPPORTED）→ l_undef（None），继续后面的规则。
- **eta 展开**（`_try_eta`）：t 是 LAM、s 不是且 infer(s) whnf 为 Pi →
  域先比，再比 `体 vs BVar(1) BVar(0)`（s 侧构造合成 App：BVar(1) 经
  value 链接指向 s 闭包，BVar(0) 经共享 bid 的 marker 为新 binder）。
- **结构 eta**（`_try_eta_struct`）：s 是**满参**非递归结构 ctor
  application（arity = nparams+nfields）→ 两类型先 defeq，再逐字段
  `proj(t, i) ≡ a_i`。注意 `_spine` 从最外层参数收集（**field 倒序**），
  field i 在 `args[nparams+nfields-1-i]`。
- **proj 归约与 infer**：whnf 对 `ctor a_1..a_n .idx` 归约为 `a_idx`
  （`reduce_proj_core` 非递归子集；delta 过 struct 值 const 由子项
  whnf 自然完成）。`_proj_core` 按构造子 cid 查 `struct_of_ctor` 表
  （`ctor_of_struct` 是反向键——按归纳 cid，查错表是 M3 实测坑）。
  `infer_proj`（单态、非依赖域子集）：whnf(子项类型) 必须是结构与
  proj sname 一致的 const；剥 ctor 类型的 nparams+idx 个 Pi 取 domain
  即字段类型（依赖字段/带参结构/prob-guard 在内核里走
  instantiate_type_lparams 与 mk_proj 代入，子集外，ERR_UNSUPPORTED）。
- **结构表**：`TOY_STRUCTS = {名: (ctor 名, nparams, nfields)}`，
  RefVM 构造时传入（`structures=`），proj 归约与 eta-struct 共用；
  toy env 新增 `True`（Prop，irrelevance 供给）与 `P2`（2 字段非递归
  结构，proj/eta-struct 供给）。

**M3-ref 验收（2026-09-03）**：`tests/test_ref_infer_defeq.py`
**53/53 vs 真 lean**（37 DEFEQ 含 16 个 M3 新例 + 16 INFER）。
**M3 图帧化已完成（2026-09-05，见 §10.2 M3 表）**：16 个 M3 新例中 15
个解除 M3_PENDING，`test_stepgraph_infer_defeq.py` 图 vs 参照机 **52/53**
（唯一钉住 `deq_eta_lam`：嵌套 eta 的 spine-peel env 传播缺口，Phase 6
——**已由 P6.1 解除**，见 §11.5）。
回归全绿：RefVM WHNF 34/34、step 图 WHNF 34/34、step 图 vs 真 lean 34/34；
重编译权重（635,747,778 参数）后权重保真 34/34。C++ 引擎不覆盖 M3 帧
（Phase 6 重建二进制格式 + 读出表同步）。

- CHECK：INFER + univ 一致性检查的组合任务（M4 端到端）。

## 9. 已知限制（v1）

1. 序列 ≤ 4096（§2 精度规则）；ENV 拓扑序手工/工具链保证。
2. univ 参数实例化（delta 时按常量 univ_arity 替换值中的 lparam）
   Phase 5 接入；v1 只支持 univ_arity=0 的定义展开。WP2 的完整
   level/universe 规格（D1–D14、编码、oracle）见 **§12**。
3. 字符串字面量、mvar、quot.（Phase 5）、recursor iota（Phase 5，
   需要 ENV_META 的 recursor 字段扩展）不在 v1 切片。
4. LAM 链深（连续 beta）与 ENV 链长受序列上限约束——超过即
   `K_REJECT, V0=3`，如实拒绝而非静默错答。

## 10. 微步执行模型（v2，Phase 2 的 ALM 图按此实现）

§7 的机器语义要落到 ALM 图，每一步的计算量必须**定界**（图深度常数）。
原则：一切数据相关的迭代降级为机器时间——**微步（micro-step）**。
`lean_vm/ref_vm.py` 语义不变，只把控制细化为状态机；ALM 图每步只做
一次转移，由驱动器（eval_graph_sequence，Phase 3 起是真权重前向）
逐 token 自回归推进。

### 10.1 状态 token

字段扩到 7 个：`(K, A, B, C, D, E, F)`（新增 E、F 两个输入维，
d_model 代价可忽略，消除槽位不足的别扭设计）。当前机器状态一个 token：

```
K=T_STATE(33), A=焦点位置, B=环境链头, C=PEND 栈头, D=帧栈头,
E=辅助1, F=辅助2
```

E/F 按当前微步复用（走链剩余步数、nat 进位、倒数计数等）。

### 10.2 微步转移表

每步：按 (焦点 K，帧 X=phase) 分派，读取 1–3 个历史 token
（按位置寻址 fetch），产出下一个 STATE token（可能伴随 0–2 个
PEND/LINK/LIT_DIG 追加）。T_WHNF 主循环无帧（Krivine 循环内联）：

| 焦点 K / 条件 | 微步动作 |
|---|---|
| APP | 追加 PEND(V1, prev=C, X=B)；state ← (焦点=V0, C=新 PEND) |
| LAM，C≠0 | 读 PEND 栈顶 t；追加 LINK(t.A, 链深=depth(B)+1, prev=B, X=t.C)；state ← (焦点=lam 体, B=新 LINK, C=t 的 prev) |
| LAM，C=0 | 值完成 → 返回协议（见下） |
| CONST 有定义 | state ← (焦点=value_pos, B=0)（delta） |
| CONST nat-op 且 \|pend\|≥arity | 压 FRAME(T_NAT, focus, caller, phase=1)；state ← (焦点=栈顶.A=arg1, B=栈顶.C, C 不变) |
| LET | 追加 LINK(V1, prev=B, X=B)；state ← (焦点=X 体, B=新 LINK) |
| BVAR(i) | 进入走链微步：E=i，state ← (焦点=B=链头, 帧压 WALK 辅助) |
| WALK（E>0） | 读 LINK@A：E←E−1，state ← (焦点=A.V2=prev) |
| WALK（E=0） | 读 LINK@A：state ← (焦点=A.V0=值, B=A.X=捕获环境)，弹 WALK 辅助 |
| LIT/SORT/FVAR/PI/PROJ/MVAR | 值完成 → 返回协议 |

**返回协议**：值完成时读帧栈头：caller=0 → 追加 OUT_VAL(A=值位置) +
HALT（全机停机）；否则按帧类型恢复调用者状态（T_NAT 帧见下）。

**T_NAT 帧微步**（args 依次求值，值回填 PEND 栈顶）：
1. phase=1（等 arg1）：完成时 → 弹 arg1 的 PEND，压 PEND(值位置, X=值环境)，
   phase=2，state 焦点 = 新栈顶（=arg2）。
2. phase=2（等 arg2）：同上，phase=3。
3. phase=3（计算）：读两链头 token（V0=位数 n），E←max(n₁,n₂)+1（出位数，
   上线允许前导零，解码侧规范化），F←0（进位），进入逐位循环。
4. 逐位：读两链第 k 位（位置 = 链头+1+k，越界读 0），d = a+b+F 进位查表；
   追加 LIT_DIG(dᵢ)；F←carry；E←E−1；E=0 时：追加链头 LIT(V0=n, V1=NAT)
   于数字块前——**实现上链头在 phase=3 就先追加**（n 已知），逐位补齐，
   值完成 → 返回协议（OUT_VAL 指向链头）。

**卡头 spine 的结果表示（2026-08-30 发现的缺口，M2 前必须修）**：
whnf 对卡头的 App spine（如部分应用 `Nat.add 3`、或 nat 关闭时的
`Nat.add 21 21`）结果 = **整条原 spine**，不是裸头——真 lean 输出
`Nat.add 3` 而非 `Nat.add`。机器须追踪 spine 根：主循环中 APP 在
PEND 栈为空时压栈，则该 APP 位置即 spine 根（存于 STATE.E，主模式
E 空闲；走链模式不用 E）；值完成且 PEND 非空时结果 = spine 根位置，
否则 = 焦点位置。ref_vm 当前同样只返回裸头（M1 双方一致故未暴露），
M2 一并修复。
beq/ble/sub（截断）等按同模式给出各自 phase 3 子表。
**M2 已实现（2026-08-30，帧协议定稿）**：帧链 = ST 存储帧（task=5：
V1=存储位置 V2=下一帧 X=存储环境）+ NAT 控制帧（task=2：V1=操作码
V2=caller（phase<3）或 ST' 位置（phase=3 二元）X=phase）。帧不可改写，
"更新" = 追加新帧并把 D 指向它。二元操作协议：
  fire:   D=[ST(arg2), NAT(op, caller, 1)]，焦点=arg1，PEND 栈弹出两个
  arg1 完成: D=[ST'(arg1 值), NAT(op, caller, 2)]，焦点=arg2（C 丢弃残留）
  arg2 完成: D=[NAT(op, ST' 位置, 3)]，发射输出链头，F=链头位置
  逐位微步: 按 (链头+2+2k) 取两链第 k 位（§5 步幅），逐操作码子表
            （进位/借位/比较状态在 E，k 在 B），发射 LIT_DIG；完成步
            把 D 弹到 caller、结果放入 A —— 下一步的"值完成"逻辑统一
            投递（D 栈顶为 ST/NAT(phase 1) 即等待态），嵌套 nat 操作
            无需专用返回路径。一元操作（succ/pred）不用 ST 帧。
  下溢（sub/pred 且 b>a）: 完成步改发射新链 [0]（链头+gap+数字 0，
            §5 步幅）。
  beq/ble 不发射数字链，完成步发射 CONST(Bool.true/false cid)。
计算模式与主模式按 D 栈顶区分：task=2 且 X=3 即计算模式；WALK 帧
（task=3）为走链模式；其余为主模式。主模式的"值完成"（卡叶/空参
LAM/卡 CONST）按 D 分派：D=0 → 停机；D=ST → 交付（phase 1→2 / 2→3）；
D=NAT(X=1) → 一元交付。**多跳走链修复**：WALK 续帧必须真实发射新
T_FRAME（M1 的 D 自指省略从未工作过，旧语料 nat 关闭未覆盖）。
**encoder 布局修复（同日）**：NAME 表先于 ENV 块时，pass-2 头改写会
覆盖 NAME token、丢失 X 操作码字段——现已改为 NULL/ENV 块在前、名字表
在后（§3 C-scheme 不变，cid+1 寻址恢复正确）。
**M2 验收**：34 例语料，图 vs 参照机 34/34；图 vs 真 lean 24/34
（10 个 xfail 全部落在 mul/pow/div/mod 范围：9 个直接用例 + mixed
的参数含 T_four=mul；原估 25/34 少算了 mixed）。未实现操作码
（mul=5/pow=6/div=7/mod=8）不 fire，按卡头 spine 返回整条 spine。
**M3 已实现（2026-08-30）**：全部 10 个 nat 操作码进同一台机器，帧相
位扩展（NAT 帧 X）：3 = 逐位循环（简单操作 + mul/pow cell）、4 = div
比较（R vs b，状态在 E）、5 = div R:=R-b、6 = div Q:=Q+1、10 = pow 控
制器（b 为零 → 结果 acc）、13 = pow b:=b-1。
  mul/pow cell：acc'[j] = accC[j] + m_i·x_{j-i} + carry（外层 i 扫乘数
  m，内层 j 逐位），acc 链每行重建（追加只读，不可原地改写）。mul:
  m = v1、x = v2；pow: m = 本轮 acc（cell 帧 V2）、x = a。acc 头 V2 存
  行号 i，行头 X 线程化 ST' 位置（跨多帧调用链保持 caller 可达，常数
  跳数弹出）。
  div/mod：while R ≥ b（比较相位）{ R := R-b；Q := Q+1 }；div 结果 Q、
  mod 结果 R；b=0 特例：div → [0] 链、mod → a 本身（内核实测校准）。
  R'/Q' 链头 X 携带 ST' 位置（线程化）。
  逐位算术：cell 的 p ∈ 0..98，商/余数用阈值和（10 个 geq）完整取
  mod-10；进位 = 商。链头 V0（位数上界）必须与实际发射位数一致——
  controller 的行头 V0 = x_n+1 与 cell 的 row_len 公式严格对齐（曾经
  不一致导致越位读垃圾，2026-08-30 修复）。
  发射顺序契约（驱动器）：pend, link, litdig, frame, frame2, lithead,
  gap, litdig2, const, STATE——litdig 在 frame/lithead 之前，使 cell 的
  末位数字与下一行头可同步发射且步幅（数字 k 在链头+2+2k）不破。
**M3 验收**：图 vs 参照机 34/34；图 vs 真 lean 34/34（xfail 集合清空）。
big_mul（9×9 位）131 微步；图深度仍为常数。

**Phase 5 M2 已实现（2026-09-03）：INFER/DEFEQ 进 ALM 图。** 同一台
状态机、同一张图新增帧任务 task=6（INFER）、task=7（DEFEQ）
（`expr/tokens.py` 编号与 build_vm 对齐；原 TASK_CHECK 迁至 9）。
`step_driver` 新入口：`run_infer(term, env)` 压 T_FRAME(V0=6, E2=1)
后 init_state(焦点=term, D=帧位)；`run_defeq(t, t_env, s, s_env)` 压
T_FRAME(V0=7, V1/X/E2/F2=两侧闭包) 后 init_state 双侧装填。帧字段与
ref_vm 语义一一对应；reject 路径经输出维 reject/reject_code 由驱动器
发射 T_REJECT+T_HALT 并抛 VMError。

  CONT 树：主模式"值完成"投递扩展到 infer/defeq 调用点——ST 帧
  （task=5）的 F2 存**续延 id**（I_FN/I_PI/I_ARG/I_CHK/I_LAMDOM/…/
  D_NCD 共 31 个，见 build_vm 常量区），E=1 表示帧链顶。每步按
  ST.F2 分派 CONT 分支：读子结果（A）+ 帧链现场（frV0..frF2，位置
  = ST 的 X 线程化帧位），产出下一个 ST 帧或直接投递回上一调用点
  （resume 树 A_r）。即：显式栈上的手动 CPS——图每步只做一次
  分派 + 一次字段重组。

  INFER 协议（与 ref_vm.infer 一致）：spine 逐参剥离（每剥一参压
  ST(F2=I_ARG, V1=被剥参闭包, V2=上一 ST)）→ 卡头/CONST 时查类型
  （T_PI_CLO 实例化）→ I_FN（函数类型即结果）/ I_PI（Pi 类型剥离
  dom 后沿续延）→ I_ARG（对被剥参 infer，与 dom defeq，续延
  I_CHK）→ I_LAM（binder marker link + 域推断 + 体）→ I_LETV/
  I_LETD（val_type ⊑ declared_type 检查 + marker + 体）→
  I_SORTEM（Sort 归属）。LAM 体/LET 体的续延帧经 I_LAMBODY 发射
  raw T_PI_CLO、I_LETD 发射 link+frame+frame2：**帧地址不变式——
  凡 CONT 分支在 POS+1 追加 raw/link，其 frame/frame2 槽位必须
  相应 +1（c2→c3）**（两处 focus 指错 c2 的 bug 均由此而来）。
  LET token 的位置在 let 分派时存入 INFER 帧 E2、经 I_LETV 续延帧
  的 E2 透传，I_LETD 用它 fetch body（LET.X）——E2 在续延链上的
  每一帧都必须显式保真，默认清零即丢。

  DEFEQ 协议（与 ref_vm.defeq 一致）：同位置快速比较 → 逐 kind
  分派（bvar 走链后比、app spine 逐参、lam/pi 双侧 binder marker
  + dom 递归 + 体递归、let 展开双侧、sort/lit/const）→ 双侧 whnf
  循环 → 卡头 spine 逐参对比 → Nat ctor↔literal 归一。递归对
  (t,s) 压 DEFEQ 帧（V1/X/E2/F2），verdict 沿 CONT 树回传，短路
  用 rej_code（1=类型错 2=defeq 失败…）。

  驱动器发射契约扩到 11 槽：**raw**（任意 token kind：T_PI_CLO、
  级链、spine 第二 PEND）在 pend/link 之前，寻址 POS+1；
  link/link2 与 frame/frame2 均带全 7 字段（E2=marker flag）。
  StepDriver 换 IncrementalGraphEvaluator（alm_p2）：token 只追加
  且每位置只依赖前缀，缓存历史位置的 vals，O(n²)→O(n)。

  **M2 验收**：新差分测试 tests/test_stepgraph_infer_defeq.py
  （21 defeq + 16 infer）图 vs 参照机 **37/37**；回归：RefVM vs
  真 lean 34/34（whnf）+ 37/37（infer/defeq）、step 图 vs 参照机
  34/34、step 图 vs 真 lean 34/34；重编译权重（240,662,136 参数，
  45 层 d_model=3432）后权重 vs 图逐步对比 34/34（最大数值偏差
  ≤1.3e-09）。这是编译期开发检查，只覆盖 WHNF，不是验收。

**Phase 5 M3 已实现（2026-09-05）：proof-irrel / eta / 结构 eta / proj 进图。**
内核 `is_def_eq_core` 卡头后段（§8.1 语义）落到同一张 step 图的 CONT 树。
卡头对 (nt,ns) 的判定顺序即 stuck 链的帧续延顺序，每步读**埋藏的原
DEFEQ 调用帧**（`oo* = fetch(v1_,x_,e2_,f2_ ← ST.V2)`）取回卡头对，verdict
投回 `ST.V2`（pop_task）。新增续延 id 32–54（build_vm 常量区）：

| 机制 | 续延帧（ST.F2） | 微步动作 |
|---|---|---|
| E proj 归约 | `I_PROJ` | whnf 子项到满 `P2.mk` spine → 投 `a_idx`；否则重贴 proj token |
| A binder 身份 | `D_BV2/D_BV3` | bvar 走链交付 **LINK 位置**（非域闭包），D_BV3 比两侧 `T_LINK.F2` bid |
| B proof-irrel | `PI_T→PI_TY→PI_LVL→PI_S/PI_D` | infer(nt) whnf 是否 Prop；是则 defeq(ty,ty) 投 True |
| C eta 展开 | `ST_ET→ETA_T→ETA_S→ETA_DOM→ETA_LINK→ETA_LNK2` | 恰一侧 LAM：infer 非 lam 侧 whnf 成 Pi → defeq(dom) → 造 `M,L,M2` 标记（`M2.F2=M` 共享 bid）+ 合成 `App(BVar1,BVar0)` raw → defeq(体, 应用) |
| D 结构 eta | `ST_ES→ES_T→ES_DOM→ES_NEXT` | 一侧满参非递归 ctor（`P2.mk`，0 参 2 字段）：`s_ty` 静态 = `Const(P2)`（免 infer(Proj)）→ defeq(t_ty,s_ty) → 逐字段 `Proj(nid,i,t)` vs `args[nfields-1-i]`（倒序） |

  **T_LINK.F2 = bid 语义**（机制 A 的核心）：binder 链接（flag=1）的
  第 7 字段 F2 存该 binder 的**唯一身份 id**（= 链接自身位置，或 eta
  的 `M2.F2=M` 共享）。DEFEQ 的 bvar/bvar 走链后比 bid 而非比位置——
  两侧 binder 只要 bid 相等即同一局部变量（α-等价）。`link/link2`
  发射槽带 F2（驱动器 11 槽契约的 link 全 7 字段）。

  **发射槽位扩展 c4**：eta 的 ETA_DOM 一步发 raw(bvar0)+link1(M)+
  link2(L)+frame(ST) 共 4 token，frame 落 `POS+4`（c4）。发射序
  raw,pend,link,link2,litdig,frame,frame2,… 不变，仅后续 frame 槽址
  随已发 token 数 +1（位置性寻址）。

  **M3 验收**：tests/test_stepgraph_infer_defeq.py 图 vs 参照机
  **52/53**（16 个 M3 新例中 15 通过；`deq_eta_lam` 钉住——嵌套 eta 的
  spine fn 对含 ≥1 跳 BVar 头，whnf-under-marker 在 spine-end 把其 env
  清 0，marker-vs-marker 对到不了 D_BV3；属共享 spine-peel/whnf 路径的
  既有缺口，改动危及 46 个通过例，留 Phase 6；**P6.1 已解除，见 §11.5**）。回归：RefVM vs 真 lean
  34/34 + 53/53、step 图 vs 参照机 34/34、step 图 vs 真 lean 34/34；
  重编译权重（635,747,778 参数，71 层 d_model=4374）后权重 vs 图逐步
  对比 34/34（开发检查，只覆盖 WHNF，不是验收）。C++ 引擎仍只读旧 10 槽、
  不覆盖 M3 帧（Phase 6 重建二进制格式）。

### 10.3 驱动器契约

驱动器维护 token 序列；每步把当前 STATE token 作为最后位置喂给 ALM 图，
从输出维读出下一状态字段与追加 token，append 后进入下一步。
Phase 2 的驱动器 = eval_graph_sequence 重放（`lean_vm/step_driver.py`）；
Phase 3 起同一契约换成真 Transformer 前向——**图不变**。

**Phase 3 runner 形态**（`model/runner.py` WeightRunner，与 StepDriver
同 init_state/step/run 接口、同发射顺序）：

- **输入行直通，无词表**。我们的 token 是 7 个任意整数字段
  (K,V0,V1,V2,X,E2,F2)，不是固定词表条目，因此不走 embedding 查表：
  runner 直接构造残差行——7 个字段值写进编译期固定下来的对应
  InputDimension 槽位 + `one` 槽位置 1.0；position / inv_log_pos /
  position² 三个位置内建维由 `LeanTransformer.forward_stream` 按位置写
  （槽位 1/2/3，`one` 固定占槽 0）。这与 transformer-vm 的做法同构
  （其 embedding 行本身就是稀疏系数向量直进残差槽位），只是查表一步
  也省了。
- **输出读出 = identity 头**。编译时把 output_tokens 传成
  `{name: Expression({dim: 1})}`：这同时（a）把 38 个输出 persist 维的
  槽位寿命保护到最后一步（`_assign_slots` 的 output-dim death=P 及其
  传递依赖延长），（b）使 head 第 idx 行恰为该维槽位的指示向量——
  `logits[..., idx]` 就是该 persist 维在最后位置的值，无需 argmax。
- 每步对整条流做 teacher-forcing 全前向（无 KV cache），取最后位置
  读出；全 float64（`compiler/weights.py` 模块级
  `set_default_dtype(float64)`，BIG=1e20 clear-key 与 pos² 需要精度）。
  序列上限 4096 同 Phase 2（HARD_K=1e4 键精度）；KV cache 与 hull
  attention 留给 Phase 4+。

### 10.4 为什么这样是 ALM 可实现的

每微步的读取 = 常数次"按位置寻址 fetch"（§6 的 fetch_by_position）；
每微步的计算 = 常数个 `_kind_eq_raw`/`_select`/逐位查表门控；
一切循环（走链、进位、参数求值）都摊到时间维。图深度是常数，
d_model 随分派表大小线性——这正是旧架构做不到的两点。

## 11. Phase 5 M4 规划（端到端证明验证；M4.1/M4.2/M4.3 已实现）

M1–M3 把内核的 WHNF/INFER/DEFEQ 切片搬进了图，但语料仍是手写的 toy
闭包。M4 的目标是**端到端**：从真 lean 的 `.olean` 导出常量子集 → 编码
成机器 token 流 → 图执行 CHECK → 对**变异证明**给出拒绝并定位错误。
M4.1/M4.2/M4.3 均已落地（实现注记见各小节）。

### 11.1 .olean 常量子集导出

- 真 lean 的编译产物 `.olean` 是序列化环境（常量 + 类型 + 值 + univ
  参数 + 构造子/结构元数据）。导出工具链：用 lean 的 `Lean.Environment`
  API 把目标证明依赖的**常量子集**（传递闭包：被引用常量的类型/值再
  递归引用者）dump 成 §3 的 ENV 块 + NAME 表 + struct 元数据
  （`struct_of_ctor`/`ctor_of_struct`，§8.1）。
- 对标 transformer-vm：它对 WASM 做的是"模块 → 指令表 + 内存段"的
  静态导出；我们对 `.olean` 做"环境 → 常量表 + 类型/值树"。差异在于
  lean 的类型是闭包（含 univ/lparam），导出时须把 univ_arity=0 的先
  落地，univ_arity>0 的留 §9.2 的实例化路径（M4 子集可先限 0）。
- 验收：导出的子集喂 RefVM 与图，二者对真 lean `#check` 的 verdict 一致
  （对真 lean 差分，扩展 `test_ref_infer_defeq.py` 的语料来源从手写 → .olean）。

**已实现（2026-09-06，M4.1）**：`reference/olean_export.py`（`dump_env` +
`import_env`）+ `tests/test_olean_export.py`。机制：`#DUMP_ENV` elab 命令沿
type/value 的 Const 引用做传递闭包，serExpr 逐常量打 JSON 行（4.33.1 API
实测：`ConstantVal.levelParams`、`InductiveVal.numParams/ctors`、
`getStructureInfo?`）；Python 侧在 toy 表处剪枝（真 `Nat.add` 的值是
`Nat.brecOn/Nat.rec` 的 iota 机器，Phase 6 债务，toy 表按内置 opcode 建模），
归一化 `OfNat.ofNat Nat n (instOfNatNat n)` → `LitNat n`（与内核 whnf 的
delta+beta+proj 路径等价，避免导入宇宙多态的 OfNat——§9.2 缺口），校验 M4
切片（univ_arity=0、无 fvar/mvar/LParam/LitStr、Const 引用 ∈ toy ∪ 导出集、
结构须 0 参单构造子），导出常量**追加在 TOY_CONSTS 之后**（cid ≥ 28，图内
硬编码的 nat-op/Bool/P2 cid 不受影响）。验收：Layer A RefVM(导出 env) vs
真 lean **21/21**（8 WHNF + 7 DEFEQ + 6 INFER，含真结构 `E_pair` 的 proj
defeq）；Layer B 图 vs RefVM **17/17**；回归四件套 + M3 套件数字不变。
限制：图的 proj/结构 eta 门是 P2 编译期常量，图层级语料避开新结构 Proj
（RefVM 数据驱动、已覆盖）；带 level 参数的多态常量仍不导入（Phase 6）。

### 11.2 端到端 CHECK 任务（M4.2 已实现）

- 新增 task=T_CHECK=9（§7 占位 6→已迁 9，M4 复用）：组合 INFER + 一致性
  检查——对声明 `(name : type, val)`，infer(val) 得 `t_ty`，
  defeq(t_ty, type) 即 CHECK 通过。复用 M2/M3 的 INFER/DEFEQ 帧与 stuck
  链，无需新语义，只需一个顶层组合帧 + 多常量循环（append-only 帧栈）。
- **实现（2026-09-06）**：CHECK 帧是每声明的循环锚：
  `V0=9, V1=声明类型根, X=值根, V2=下一锚（0=最后）`。锚不入
  `is_task_frame`（pop 不掉它）；`ck_kick = is_check_frame ∧ ¬ret_pending`
  发射 frame1=ST(`V1=frV1, V2=frV2(下一锚), F2=CK_TY`) + frame2=INFER
  (`V2=c1, E2=1`)，STATE `A=frX, D=c2`。关键设计：ST 续延帧的 caller 链
  在 kickoff 时就**跳过锚直指下一锚**，于是 CK_RES 的"推进"就是普通
  pop（`D=frV2`），"接受"就是 `frV2=0` 时 halt——无需新 fetch。
  CK_TY（infer 结果 (A,B) 送达）镜像 I_ARG：改写 ST 为 `F2=CK_RES`、压
  DEFEQ(`V1=A, X=B, E2=frV1(声明类型), F2=0, V2=c1`)。CK_RES：verdict
  `A=0` → reject(ERR_TYPE=1)；`A=1 ∧ frV2≠0` → 推进（`A=nbX` 下一值根）；
  `A=1 ∧ frV2=0` → ACCEPT（`halt += ck_accept`，result=1）。
  新续延 id `CK_TY=55, CK_RES=56`（`g` 扩到 range(1,57)）；`m2_merge` 增
  ck 槽；`main_mode` 减去 `is_check_frame`。
- 驱动器入口 `StepDriver.run_check(decls)`：decls=`[(type_root, val_root)]`，
  逆序压 CHECK 帧使首声明居链头，`init_state(首值根, D=首锚)`；全通过 →
  返回 (1,0)，首个失败 → `step()` 抛 VMError(ERR_TYPE)。RefVM 侧
  `RefVM.check(decls)` 逐声明 infer+defeq 同语义。
- 验收（tests/test_check_e2e.py）：oracle=真 lean 编译
  `example : T := v`（exit 0=接受）。Layer A RefVM vs 真 lean **15/15**
  （12 单声明含 accept/reject/结构体/高阶/let/Sort + 3 多声明序列）；
  Layer B 图 vs RefVM **15/15**（accept 4–16 微步，reject 24–42 微步，
  7 声明序列 65 微步）。回归全绿：M1 53/53、M3-ref 34/34、M2 图 52/53、
  M3 图 34/34+34/34、M4.1 21/21+17/17。
- 限制：图侧 CHECK 的语义覆盖面 = M2/M3 INFER/DEFEQ 子集（proj/eta 门
  P2-only、无 polymorphic 常量、避开 `deq_eta_lam` 形态）；错误定位
  （V2 父指针链）属 M4.3，未实现。

### 11.3 变异证明拒绝 + V2 父指针链错误定位（M4.3 已实现）

- **变异拒绝**：对正确证明做语义保持性破坏的最小变异（换构造子、改
  字面量、交换 binder、删 proj 字段），图必须 REJECT 而 RefVM/真 lean
  同样 REJECT。这是"机器不是背答案"的证据——对标 transformer-vm 的
  mutation testing。语料：每个 M3 例配 1–2 个变异体，期望 verdict=False。
- **错误定位（§7.4）**：REJECT 时焦点位置的 **V2 父指针链**回溯到子项
  根，给出"哪个表达式节点导致不可判定"。实现：reject 步额外发射一条
  error_path 输出（焦点位置 + 沿 V2 链的若干祖先位置），驱动器读出后
  映射回 .olean 常量名。V2 链在 §2/§4 已是节点→父的不变字段，M4 只是
  在 reject 路径上消费它，不改编码。
- 验收：变异体拒绝率 100%（图 vs 真 lean 一致），且 error_path 指向的
  节点与真 lean 报错位置语义对应（人工抽查 + 自动 cid 比对）。
- **实现（2026-09-06，`tests/test_mutation_reject.py` + `lean_vm/localize.py`）**：
  - **变异拒绝**：8 个类型正确声明（M4.1 导出 env）+ 8 个最小破坏变异
    （改声明类型头 Nat→Bool、改 Pi 余域、换结构 E_pair→P2、把项类型声明成
    Bool、构造子字段塞 Bool）。三层（真 lean `example : T := v` exit code /
    RefVM.check / 图 run_check）逐条一致：原语全 accept、变异全 reject。
    验收 **Part A 16/16（accept 8/8 + reject 8/8）**。
  - **错误定位（driver 侧，零图改动）**：机器只做决定，`localize.py` 只解释
    机器已维护的数据——V2 父指针链（§2，`Encoder._fix_parent` 写入）+ 编码
    的类型树。两类 reject：(a) 类型不匹配（CK_RES verdict-false，焦点是布尔
    非节点）→ 用图自身 `run_infer(值)` 得推断类型，与声明类型做**位置级结构
    diff**（`diff_pos` 递归同种子节点，返回最深公共前缀分歧 = 变异子项）；
    (b) 值非良构（图 INFER 直接 reject）→ `step()` 把 reject 步的焦点闭包
    (A,B) 塞进 `VMError.focus/env`，焦点>0 即 offending 节点。两者都沿 V2 链
    回溯到声明树根。验收 **Part B 8/8**：offending_expr 恰为变异子项（如
    `Const Bool`/`Const P2`），Pi 余域变异定位到 path 深度 2（证明 diff 正确
    递归），V2 链根 == 声明类型树根。
  - **顺带修复 M2 遗留正确性 bug**：`build_vm.py` D_NCC 块曾以
    `rej_c = reglu(ncc_fail, One)` **赋值**（而非累加）覆写 rej_c，静默丢弃
    了更早的 CONT-tree 拒绝（I_CHK/i_ls/i_p1/i_p2/i_ld）。后果：图 `infer_app`
    接受参数类型错误的申请（`Nat.add true 1` 竟 infer 成 `Nat`），M2 语料无
    良构性反例故长期潜伏。改为累加后 infer_app 正确 reject(ERR_TYPE) 且焦点
    指向参数类型节点；全套回归不变（M1 53/53、M3-ref 34/34、M2 图 52/53、
    M3 图 34/34+34/34、M4.1 21/21+17/17、M4.2 15/15+15/15）。

### 11.4 与 Phase 6 的边界

M4 不碰：whnf-under-marker 的 spine-peel env 重做（`deq_eta_lam`）、
infer_proj 帧、C++ 引擎二进制重建——这些是 Phase 6 的图/引擎债务。M4
假定图侧语义已冻结在 M3 的 52/53 水平，端到端语料避开 `deq_eta_lam`
形态（嵌套 eta 的 ≥1 跳 BVar 头）。

### 11.5 P6.1：whnf spine-root 约定与 marker env 传播（2026-09-06）

`deq_eta_lam`（M3 唯一钉住例）解除钉住，图/参照机首次同时到 **54/54**。
三处语义修复都在共享的 spine-peel / whnf-under-marker 路径上：

1. **图 `mk_stuck` spine-root 交付**（§10.2 约定）：WHNF 父帧且有 pending
   args 时，stuck 结果交付原闭包 `(nbV1, nbX)`（整条 spine + kickoff 时的
   env），而非裸 head。旧的 head-only 交付会让 `f 1 ≡ f 2` 仅凭 head bid
   被接受（不健全性，新守卫例 `deq_fvar_args`）。
2. **WALK 帧 F2 携带 env₀**：bvar 焦点 env 写入 walk 帧 F2（此前恒 0；
   所有 frF2 读者被 `is_st_frame` 门控，不会误触发），顶层 stuck 兜底交付
   `(SF, frF2)`——spine env 不再被 walk 清 0。
3. **`mk_dq` 放宽**：`D_BV2/D_BV3` 下的 walk 解析到值链（flag=0，如 eta 的
   L 链）时直接交付链位置（`walk_done ∧ par_bv`），不再弹回 resume_mode
   冻结（旧行为 300+ 步无进展）。

参照机 `ref_vm.whnf` 的 K_BVAR marker 分支同步 spine-root 约定，并引入
`spine_env`：spine 的参数活在 App 处的 env 里，head 解析会经值链替换/
delta 改写 `env`，故 stuck 返回必须用 spine 打开时记录的 env（K_CONST
stuck 分支同有该潜在错误，一并修）。

顺带修复图侧 `I_LIT` 规则：infer 字面量发 `Const(Nat)` 时 `raw_V0` 误取
`SB`（当前 env）——顶层 env=0 恰等于 `CID_NAT` 故长期被掩盖；marker env
下发成 `Const(marker_pos)`，I_CHK 再 infer 不存在的常量 → reject 4。
改为固定 `CID_NAT`。

**P6.1 验收**：`test_stepgraph_infer_defeq` 图 vs 参照机 **54/54**
（0 钉住；DEFEQ 38 + INFER 16）；`test_ref_infer_defeq` 参照机 vs 真 lean
**54/54**。回归全绿：RefVM whnf 34/34、图 whnf 34/34、图 vs 真 lean
34/34、M4.1 21/21+17/17、M4.2 15/15+15/15、M4.3 16/16+8/8。

### 11.6 P6.2：infer_proj 帧（机制 F，2026-09-06）

图 INFER 子集补上 Proj 类型推断（内核 `infer_proj`，type_checker.cpp
L247；单态、非递归、非依赖域子集——P2，build-time 门控，与结构 eta 同
约定）。新续延 id `IP_TY=57` / `IP_PEEL=58`：

- **`proj_i`（INFER ph1）**：焦点 `Proj(nid, idx, child)` → 压
  ST(IP_TY, V1=nid, X=idx) + INFER(child)。
- **`IP_TY`**：子项类型闭包 (A,B) → 压 WHNF（硬 whnf，E2=0）+
  ST(IP_PEEL, E2=0)。
- **`IP_PEEL` 相位 0**（frE2=0）：whnf 后类型必须是 `Const(CID_P2)` 且
  proj sname 为 `NID_P2`，否则 reject ERR_TYPE（内核 invalid_proj）；
  通过则焦点 = ctor 类型根（`ENV_HDR(CID_P2MK).V1` = `Nat → Nat → P2`），
  E2 置 1 重入。
- **`IP_PEEL` 相位 1**：剥 X 个 Pi（非依赖域，免实例化），交付字段
  domain（闭树 → env 0）；焦点非 Pi（idx 越界）→ ERR_TYPE。

结构 eta 的 ES_T 保留静态 `s_ty` 捷径（对 P2 等价且省步，注释已同步）。
语料 `inf_proj_fst/snd/mk`（INFER 16→19，总 57）。

**P6.2 验收**：图 vs 参照机 **57/57**（proj 三例 14/15/21 微步）、参照机
vs 真 lean **57/57**；回归全绿：whnf 34/34×3、M4.1 21/21+17/17、M4.2
15/15+15/15、M4.3 16/16+8/8。

### 11.7 P6.4：iota——RefVM `Nat.rec` reduce_recursor（2026-09-06）

内核 `inductive_reduce_rec`（inductive.h L77）的 Nat.rec 子集进入参照机
whnf 的 K_CONST 分支（nat-op 派发之后、stuck 返回之前）。`Nat.rec` 追加
进 TOY_CONSTS（cid 27；export cid 动态 ≥ len，无碰撞；类型树为装饰性
依赖 Pi，iota 不读）。门控 `V0 == cid_rec && len(pend) >= 4`：pend 序
`[.., maj, s, z, m]`（Krivine 下降 append，pop 得应用序），major_idx=3 →
maj = `pend[-4]`。

- **major whnf 分类**（内核 `whnf(major)` + `nat_lit_to_constructor`）：
  `K_LIT v==0` 或 `Const(Nat.zero)` → **zero 规则**：弹 4 项，pos/env = z
  闭包续跑（extras 留栈，= 内核 extras 应用于 rhs）；`K_LIT v>0` →
  pred = `chain(v-1)`（剥一个 succ，惰性）；`K_APP` 且 head 为
  `Const(Nat.succ)` → pred = 实参闭包（防御分支：nat-op 开启时 succ 永不
  以 stuck App 形态离开 whnf）；其余 → recursor spine stuck，走 §10.2
  spine-root 返回。
- **succ 规则** rhs = `s pred (Nat.rec m z s pred)`：四个闭包 (pos,env)
  经 LINK 链 `e4`（BVar 0=pred,1=s,2=z,3=m）携带，重发 spine 在 e4 下
  封闭；循环 `continue` 即惰性递归（whnf 续跑 rhs，beta 归约 s）。

已知缺口（与图侧一致、语料不触及）：`Nat.succ <stuck>` 在参照机走
nat-op 路径抛 ERR_TYPE（内核留 stuck）——offset/构造子 stuck 参数属后续
里程碑；依赖 motive 的 `infer(Nat.rec)` 不在范围。

语料 7 例 `deq_rec_*`（lit/zero/no/add/succ-spine/stuck/stuck-no；DEFEQ
38→45，总 64），图侧暂钉住（`M3_PENDING`，待 P6.5 图框架落地逐例解除）。

**P6.4 验收**：参照机 vs 真 lean **64/64**；图 vs 参照机 **57/64（7 钉
住）**；回归全绿：whnf 34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、
M4.3 16/16+8/8。

### 11.8 P6.5：iota——图侧 `Nat.rec` 框架（2026-09-06）

§11.7 的 reduce_recursor 语义编进单一 ALM 步图。`Nat.rec` 进
`NAT_OP_CODES`（code 11，ENV_HDR.X 派发；**不**进 `NAT_OPS`/
`NAT_OP_ARITY`，故参照机 nat-op 路径不受影响，其 iota 门控直读 cid）。
分支态 `A_fire_rec / A_zero_r / A_build_r / A_stuck_r / A_rec_sd`，发射
链经 `em_raw_rec / em_link_rec / em_link2_rec` 以 `is_build` 选择层并入
raw/link/link2 合并。

- **fire_rec**：焦点 = major-premise 闭包（pend 弹到 extras），压
  `NAT(OP_REC, caller, 1)` 帧，帧 E2=spine root、F2=m entry。
- **rec_dn 分类**：zero → 弹 NAT 帧、以 z 闭包续跑 whnf（extras 留栈）；
  succ → 重写进 15 步 rhs 发射链；其余 → stuck 交付 spine-root（§10.2）。
- **rhs 发射链（succ 规则）**：rhs = `s pred (rec m z s pred)`，四闭包经
  LINK 链 `e4`（BVar 0=pred,1=s,2=z,3=m）携带，重发 spine 在 e4 下封闭；
  链尾 `A=rhs`、`B=e4` 即惰性递归的续跑焦点。

**发射链偏移表**（实测；base `b = frE2 = c1+2`，因 rec_dn 步把 frame 发在
c1、STATE 发在 c1+1，首个 build token 落 c1+2）。驱动器每步在发射序
`raw,pend,link,link2,litdig,frame,frame2,lithead,gap,litdig2,const,STATE`
之后追加一个 T_STATE（K=33），槽位 `c1=POS+1..c4=POS+4` 固定：

| 槽 | 偏移 | 槽 | 偏移 | 槽 | 偏移 |
|----|------|----|------|----|------|
| pred CONST | b+0 | b1 | b+12 | app3 | b+24 |
| pred APP | b+2 | b2 | b+14 | r4 | b+26 |
| e1 | b+4 | b3 | b+16 | a1 | b+28 |
| e2 | b+5 | rc | b+18 | rhs | b+30 |
| e3 | b+7 | app1 | b+20 | done A | b+30 |
| e4 | b+8 | app2 | b+22 | done B | b+8 |

步 2、3 发 link+link2+STATE（3 token），其余发 raw+STATE（2 token）。
`sel(*args)`（右嵌套 `_select`）**要求奇数参**（`c1,e1,…,cn,en,default`）；
偶数参会静默错配、打乱载荷——`raw_K_rec` 曾因多余 `Zero` 凑成 8 参而发
K=0（非法 kind），已修。下降 env 取自 STATE 的 B（`pend_env=SB`），非
raw token 的 X（build token `raw_X=0` 无碍）。

**padding-safe zero 测试**：计算链是**补零**的——`succ(zero)→V0=2 [1,0]`、
`succ(1)→V0=3 [2,0,0]`；`pred` 保持位数（`[2,0,0]→[1,0,0]→[0,0,0]`），
`pred(0)` 下溢返回原参。故 zero 可呈 `V0=0`、`V0=1 [0]`、或补零
`[0,0,0]`。`is_zlit_r` 扫 4 位（`SA+2+2i`，i=0..3，stride-2 间隙被 STATE
占）判全零，**语料界：值 < 10000**（4 位扫描足够；超界需扩位）。既有
`is_bzero_d`、`_value_eq_n` 仍持 clean-chain 假设——iota 是首个消费计算
产出链的分支，故新测试独立。

**P6.5b 解钉 stuck 2 例（三处 bug）**：`deq_rec_stuck / deq_rec_stuck_no`
（Lam 体为卡住的 recursor spine，DEFEQ 走 proof-irrel 的 `infer`）原在图侧
reject/死锁。根因是**三处独立 bug**，参照机靠 `_proof_irrel` 的 try/except
吞掉 infer 异常而侥幸与真 lean 一致，图无异常机制故暴露：

1. **`_REC_MOT` ill-typed**：语料把 motive 的**类型** `Nat -> Sort 1` 误当
   Lam 的 binder domain，编码成 `fun (_ : Nat -> Sort 1) => Nat`；源串实为
   `fun _ => Nat`（binder `Nat`）。修：`Lam("x", BI_DEFAULT, NAT, NAT)`。
2. **`_pi_natrec` de Bruijn 索引错**：`s_ty` 与结果里的 motive 引用漏算了
   中间的 `z`/`s` binder（写成 `BVar(1)/BVar(2)`，实为 `BVar(2)/BVar(3)`），
   故 `infer` 检查 s 参数时 whnf `m n` 解析成死 BVar → `A=0` 死锁。修：
   按上下文 `[motive,z,n(,ih)]` / `[motive,z,s,n]` 重排索引。
3. **`D_XPI2`/`D_TPC2` 缺 `fr2_task` 覆写**：cont 段 `fr2_task` 默认
   `TASK_WHNF`（L1086），`D_BIND2` 显式覆写成 `TASK_DEFEQ` 但这两个跨类
   Pi 帧忘了，body 比较帧被发成 WHNF、caller 字段当续延 id → 死锁。修：
   两帧各加 `fr2_task = _select(g, TASK_DEFEQ, fr2_task)`。

修后 proof-irrel 的 `infer(Nat.rec m z s n)` 成功（type=`m n`=Nat 非 Prop →
l_undef → ST_SP 结构比较），图与参照机、真 lean 三方一致。

**P6.5 验收**：图 vs 参照机 **64/64（0 钉住）**；参照机 vs 真 lean
**64/64**；回归全绿：whnf 34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、
M4.3 16/16+8/8。

### 11.9 P7：`is_def_eq_unit_like`——子单元素 defeq（2026-09-06）

内核 `is_def_eq_core` 卡住链的最后一条规则（type_checker.cpp L1159，在
eta-struct / string-lit 之后、`return false` 之前）：若 `t` 的类型 whnf 后
头是**单构造子、零字段**的非递归结构（subsingleton），则 `t ≡ s` 当且仅当
两者类型 defeq。此前图/参照机的卡住链止于 eta-struct，缺这条。

**为何 `True` 不够**：`True` 虽是零字段结构，但它是 `Prop`，proof-irrel
（链首）已先判真，unit_like 永不被触发。故新增 `UnitT : Type`（cid 28，
`structure UnitT : Type where`，唯一构造子 `UnitT.mk : UnitT`，0 字段）——
非 Prop，proof-irrel 落空，unit_like 成为判定规则。语料
`deq_unit_like`（`fun (x : UnitT) (y : UnitT) => x` ≡ `... => y`，两不同
stuck fvar → True）与 `deq_unit_like_no`（同形但 `P2`，2 字段 → unit_like
拒绝 → False）。真 lean `Meta.isDefEq` 实测同值（probe 2026-09-06）。

**参照机**（`ref_vm._unit_like`）：`infer(t)` → `whnf` → `_spine` 取头
`get_app_fn` → 查 `ctor_of_struct[head_cid]` 且 `nfields==0` → 命中则
`defeq(t_ty, infer(s))`。接在 defeq 卡住分支 eta-struct 之后。

**图侧**（镜像 proof-irrel 的 `PI_*` 链，新增 cont id 59–63）：卡住链
`ST_ES` 不适用（`es_no`）不再直接判 False，而是踢出 `ST_UL` 帧（focus=nt，
caller=buried DEFEQ 帧）。链 `ST_UL`（infer nt→t_ty）→ `UL_W`（hard-whnf
t_ty→t_ty_n，t_ty 经帧 V1/X 携带）→ `UL_CHK`（头是否 `Const(CID_UNITT)`：
是→`UL_D`，否→判 False 给 caller）→ `UL_D`（infer ns→s_ty，`defeq(t_ty,
s_ty)` 给 caller）。UnitT 0 参数，故 `UL_CHK` 直接测头 cid，无需剥参（同
P2 路径的 0-参数简化）。**关键坑**：新 cont id 必须登记进 `em_frame_m2`/
`em_frame2_m2`（否则帧不发、`D` 指向 STATE token → 死循环）；按"是否总发帧"
选登记粒度——`ST_UL`/`UL_W` 恒发 fr1+fr2 故登记 cont id，`UL_CHK` 仅
`ul_yes` 发帧（`ul_no` 是裸 verdict）故登记分支门 `ul_yes`，`UL_D` 仅发
fr1（DEFEQ），`es_no` 仅发 fr1（kickoff）。

**P7 验收**：图 vs 参照机 **66/66（0 钉住）**；参照机 vs 真 lean
**66/66**；回归全绿：whnf 34/34×3、M4.1 21/21+17/17、M4.2 15/15+15/15、
M4.3 16/16+8/8。卡住链现覆盖 proof-irrel→app→nat-ctor→eta→eta-struct→
unit_like；仍缺 string-lit 展开与 quot（后续里程碑）。

### 11.10 P7.5a：通用 iota——`casesOn` 参照机侧（2026-09-06）

内核 `inductive_reduce_rec`（inductive.h L77）是**元数据驱动**的通用 iota：
取 recursor 的 `major_idx`、whnf 主前提、`get_rec_rule_for` 按主前提的构造子
选规则、把 `rhs`（预存的、含递归调用）依次喂 params+motives+minors、构造子
字段、extras。`Nat.rec` 只是它的一个实例（major_idx=3、succ 规则 rhs 含
`Nat.rec m z s n` 递归调用）。P6.4/6.5 把 `Nat.rec` 手搓进图，未泛化。

**casesOn** 是最简单的通用实例：major_idx=0、nmotives=1、nminors=构造子数、
**无递归调用**（纯 case 分析，`match`/`induction` 的编译产物）。归约：whnf
主前提到构造子 `C f₁…f_k` → 结果 = 第 `C` 个 minor 应用于 `f₁…f_k`。

参照机侧（`lean_vm/ref_vm.py`）：
- `__init__` 新增 `self.caseson = {recursor_cid: (major_idx, [(ctor_cid,
  nfields), …])}`（Nat.casesOn→[(zero,0),(succ,1)]，P2.casesOn→[(P2.mk,2)]）。
- `_match_ctor(wpos, wenv, ctors)`：主前提若是 nat 字面量先转构造子形（内核
  `nat_lit_to_constructor`，L94），再按构造子 cid 命中，返回 (minor 序标,
  字段闭包表·应用序)。`_spine` 返回逆应用序，字段需 `reversed`。
- whnf 的 K_CONST 分支、`Nat.rec` 块之前：spine（应用序）= `[major, motive,
  alt₀, alt₁…]`；`args=reversed(pend)`，whnf `args[major_idx]`，命中则
  `pend[:] = reversed(extras) + reversed(fields)`、`pos,env = minor`、continue；
  主前提卡住则落到 §10.2 原样返回整 spine。

语料（`reference/toy_env.py`）：`Nat.casesOn`(cid 30)/`P2.casesOn`(cid 31) 类型
`_pi_natcaseson`/`_pi_p2caseson`（de Bruijn 逐 binder 深度核对）；7 例
`deq_caseson_*`（succ/zero/succ2/p2/no/stuck/stuck_no）。

**P7.5a 验收**：参照机 vs 真 lean **73/73**（66→73）；回归全绿：whnf 34/34×2、
图 vs 参照机 66/73（7 casesOn 钉住，图侧 P7.5b 待做）。

### 11.11 P7.5b-2：`Nat.casesOn` 图侧 iota（2026-09-06）

把 `Nat.casesOn`（major_idx=0、无递归调用）编进 ALM step 图，复用 P6.5
`Nat.rec` 的 iota 骨架（fire → 子 whnf 主前提 → `*_dn` 分类 → 分支）。派发键
仍是 ENV_HDR.X：`tokens.py` 给 `Nat.casesOn` 打 `OP_CASESON=12`（与 `OP_REC=11`
并列），`build_vm.py` 的 `csonop`/`fire_caseson` 据此触发。

**spine 与链**：应用序 `[t, motive, zero, succ]`，`t` 最后压 → PEND 头 `SC`。
经 V2 链 `SC=t → motive → zero → succ → extras`。`fire_caseson` 弹 4 项
（`C = cs_succ[2]` = extras），在 `NAT(OP_CASESON, caller, 1)` 帧下子 whnf `t`
（`E2` = spine 根供 §10.2 卡住交付，`F2` = `t` 项供回读 minors）。

**`cs_dn` 分类**（主前提 whnf 完成 `E=0`）：复用 `Nat.rec` 的字面量判据
`is_zlit_r`/`is_zconst_r`/`is_lit_r`（读焦点 `SA` 的十进制链，padding-safe 扫
前 4 位）。三分支：
- `cs_zero_r`（值 0）→ 焦点 = zero minor（`rzV0_c`/`rzX_c`，回读自 `t→motive→
  zero` 链），extras 留栈，`D=frV2` 弹帧。zero minor 0 参，直接续 whnf。
- `cs_succ_r`（正字面量）→ 进 **cs_build 循环**（见下）。
- `cs_stuck_r`（非 nat 叶 / 卡住交付 `cs_sd`）→ §10.2 原样交付 spine 根
  （`frE2` 在 `rtX_c` 下）。

**cs_build 循环（succ 规则）**：rhs = `succ_minor (Nat.pred t)`，3 个 raw 步
（基址 `b = frE2`，每步 1 raw + 1 STATE → POS +2）：
`SB=0` `CONST(PRED)@b`；`SB=1` `APP(PRED, t)@b+2 = pred`；`SB=2`
`APP(succ_minor, pred)@b+4 = rhs`；`SB=3` done → 焦点 `b+4`、env = succ minor
env（`rsuccX_c`）、`D=frV2`。`pred` 用惰性 `Nat.pred` nat-op（与 `Nat.rec` succ
规则同款技巧，无数字循环）。extras 仍在 pend，机器把 rhs 应用上去。

**帧登记陷阱**（P7.1 教训）：`cs_succ_r` 必须进 `em_frame` 且 `frame_V1/V2/X/
E2/F2` 各加一条 `_select(cs_succ_r, …)`（V1=`OP_CASESON`、V2=`frV2`、X=2、
E2=`c1+2`、F2=`frF2`），否则推帧无登记 → `D` 指 STATE → 死循环。`dn1` 同步排除
`OP_CASESON`（否则任意 X=1 NAT 帧误触发）。

**P7.5b-2 验收**：图 vs 参照机 infer/defeq **72/73**（66→72，6 例 `deq_caseson_*`
解钉：succ/zero/succ2/no/stuck/stuck_no；`deq_caseson_p2` 仍钉，P2.casesOn 图侧
待 P7.5b-3）。回归全绿：whnf 图 vs 参照机 34/34、whnf 图 vs 真 lean 34/34、
whnf 参照机 vs 真 lean 34/34、参照机 vs 真 lean infer/defeq **73/73**、M4.2
check A/B 15/15、M4.3 mutation A 16/16 / B 8/8。succ 例 27/33 微步（旧 stuck
误判 215 步）。

### 11.12 P7.5b-3：`P2.casesOn` 图侧 iota（2026-09-06）

结构消解（`match` 在结构体上的编译产物）。与 `Nat.casesOn` 的形态差异：spine
3 项 `[t, motive, alt]`（非 4）、单一 minor `alt` 取 **2 参**、主前提是卡住的
构造子应用 `P2.mk a b`（非 nat 字面量）。故用独立派发键 `OP_CASESON_P2=13`
（`tokens.py` 给 `P2.casesOn` cid 31 打标），与 `OP_CASESON=12` 并列但各走各的
fire/dn/build 链。

**fire_p2**：弹 3 项（`C = p2_mot[2]` 的 V2 = extras），`NAT(OP_CASESON_P2,
caller, 1)` 帧下子 whnf `t`（`E2` = spine 根、`F2` = `t` 项）。门控查 **alt 项
存在**（`p2_mot[2] >= 1`，即 motive 的 V2）——语料 fully-applied 无 extras，若误
查 extras 则门恒假（踩过的坑）。

**p2_dn 分类**：主前提 whnf 完成为卡住构造子应用，其**值是 spine 根 `SF`**（外层
`App(App(Const(P2.mk),a),b)`），焦点 `SA` 只是头 `Const(P2.mk)`。故 `p2_ctor`
匹配 `SF` 形（`K_APP → K_APP → Const(CID_P2MK)`），字段 `a = SF.V0.V1`、
`b = SF.V1`。命中 → `p2_succ_r` 进 build；否则 `p2_stuck_r`（§10.2 交付 spine
根）；卡住交付 `p2_sd`。

**p2 build 循环（2 raw 步，基址 b=frE2）**：`SB=0` `APP(alt,a)@b`；`SB=1`
`APP(that,b)@b+2 = rhs`；`SB=2` done → 焦点 `b+2`、env = alt minor env
（`p2_altX`）、`D=frV2`。alt（2 参 Lam）经机器 beta 绑定 a、b；语料字段为字面量
（env-free），扁平 rhs 在 alt env 下忠实（与 Nat succ 路径同一封闭项假设，开放
项的字段 env 需后续闭包机制，记于 §11.13 待办）。

**接线**：`is_cs_build_p2` 入 `main_mode` 排除与 A2–F2 模式合并；`fire_p2`/
`p2_succ_r`/`p2_stuck_r`/`p2_sd` 入 A–F 主选择器；帧登记入 `em_frame` +
`frame_V1/V2/X/E2/F2`；`dn1` 排除 `OP_CASESON_P2`；raw 装配加 `em_raw_p2` +
`is_cs_build_p2` 选择器。

**P7.5b-3 验收**：图 vs 参照机 infer/defeq **73/73**（72→73，`deq_caseson_p2`
解钉，M3_PENDING 清空）；回归全绿：whnf 图 vs 参照机 34/34、whnf 图 vs 真 lean
34/34、whnf 参照机 vs 真 lean 34/34、参照机 vs 真 lean infer/defeq 73/73、M4.2
check A/B 15/15、M4.3 mutation A 16/16 / B 8/8。p2 例 36 微步。casesOn 图侧
（Nat + P2）至此完备。

### 11.13 P7.5b-4：`Bool.casesOn` 图侧 iota（2026-09-06）

`if-then-else` / `decide` 的编译产物，也是 `match` 在 `Bool` 上的消解。spine
4 项 `[t, motive, false-minor, true-minor]`（`major_idx=0`），两个 minor 均
**0 字段**——故无需 build 循环，每条规则只是「选中 minor、继续 whnf」（与 Nat
的 zero 规则同形）。独立派发键 `OP_CASESON_BOOL=14`（`tokens.py` 给 cid 32
打标），与 `OP_CASESON=12`/`OP_CASESON_P2=13` 并列。

**保真关键坑（差分对拍抓出）**：Lean 的 `Bool` 先声明 `false` 后声明 `true`，
故 recursor 的 minor 顺序是 **[false, true]**——`casesOn true m 7 9` 取**第二个**
minor（9），不是第一个。初版 `_pi_boolcaseson` 与 `self.caseson` 表按直觉写成
[true, false]，参照机 vs 真 lean 立刻 **74/77**（三条 bool 例全反）。修正类型
de Bruijn（false_ty 在 ctx `[motive,t]`、true_ty 在 ctx `[true,motive,t]`）、
参照机表 `[(cid_false,0),(cid_true,0)]`、语料期望值后 **77/77**。这正是对拍
真 lean 二进制而非自洽的价值：构造子声明顺序是内核事实，猜不得。

**fire_bool**：弹 4 项（`C = b_true[2]` 的 V2 = extras），`NAT(OP_CASESON_BOOL,
caller, 1)` 帧下子 whnf `t`（`E2` = spine 根、`F2` = `t` 项）。门控查 **true 项
存在**（`b_false[2] >= 1`，即 false minor 的 V2）。

**bool_dn 分类**：主前提 whnf 完成为 0 字段构造子 `Const`，直接读焦点 `fK/fV0`：
`fK==K_CONST ∧ fV0==CID_FALSE` → `bool_false_r`（继续 whnf false minor，env
`b_falseX`）；`fV0==CID_TRUE` → `bool_true_r`（true minor，`b_trueX`）；否则
`bool_stuck_r`（§10.2 交付 spine 根）；卡住交付 `bool_sd`。

**接线坑**：帧的 `E2/F2` 槽与 `V1/V2/X` 一样要加 `fire_bool` 选择器（`E2=SF`、
`F2=SC`）。初版只加了 `frame_V1/V2/X`，漏了 `frame_E2/F2` → 帧落成 `E2=0,F2=0`，
minor 链读空、焦点归 0 死循环（trace 一眼见 `NAT(V1=14,X=1,E2=0,F2=0)`）。补
`frame_E2`/`frame_F2` 后通。`dn1` 排除 `OP_CASESON_BOOL`；`em_frame += fire_bool`；
`fire_bool/bool_false_r/bool_true_r/bool_stuck_r/bool_sd` 入 A–F 主选择器。

**P7.5b-4 验收**：参照机 vs 真 lean infer/defeq **77/77**（73→77，4 条
`deq_boolcaseson_*`）；图 vs 参照机 infer/defeq **77/77**（M3_PENDING 仍空）；
bool 例 15 微步（无 build 循环，比 Nat/P2 更短）。回归全绿：whnf 图 vs 参照机
34/34、whnf 图 vs 真 lean 34/34、whnf 参照机 vs 真 lean 34/34、M4.2 check A/B
15/15、M4.3 mutation A 16/16 / B 8/8。casesOn 图侧（Nat + P2 + Bool）至此完备，
`if-then-else`/`decide` 可在 ALM 上消解。

### 11.14 P7.5c-1：`Nat.brecOn` 参照机侧（结构递归，2026-09-06）

**SOTA 核查（关键发现）**：内核**没有** brecOn 原始 iota。`Nat.brecOn` 是
`@[reducible]` 定义，展开为 `Nat.rec` + `PProd`(×') 对（`Lean/Meta/
Constructions/BRecOn.lean`）：
```
Nat.below  motive t := Nat.rec (fun _ => Sort _) PUnit (fun n ih => motive n ×' ih) t
Nat.brecOn.go motive t F := Nat.rec ⟨F 0 PUnit.unit, PUnit.unit⟩
                            (fun n ih => ⟨F n.succ ih, ih⟩) t
Nat.brecOn motive t F := (Nat.brecOn.go t F).1
```
故内核消 brecOn = delta 展开 → `Nat.rec` iota（已有）→ proj（已有）。派生出的
iota 规则（对 zero/succ 同形，minor 首参是**完整 t** 非 pred）：
```
brecOn motive 0        F ⟶ F 0 (Nat.below motive 0)
brecOn motive (succ n) F ⟶ F (succ n) (Nat.below motive (succ n))
```

**P7.5c-1 范围**：先做 zero/succ **派发**，语料 minor **忽略 below 参**——于是
`Nat.below motive t` 作为卡住项被 beta 丢弃，**无需 PProd/go/Nat.below 定义**。
toy env 加 `Nat.below`(cid 33，仅类型 `(Nat→Type)→Nat→Type` 的占位常量)、
`Nat.brecOn`(cid 34，类型见 `_pi_natbrecOn`，major_idx=0、spine `[t,motive,F]`)。
RefVM whnf K_CONST 分支加 brec 派发：whnf 主前提到 nat 构造子形（复用
`_match_ctor`），命中则发射 `F t (Nat.below motive t)`（5 个 token：Const(below)、
App(below,motive)、App(_,t)、App(F,t)、App(_,below)），extras 留栈，封闭项 env=0
（与 casesOn build 循环同一封闭假设）。

**为何不直接走 delta-over-rec**：toy env 的 `Nat.below` 链是异构 + 宇宙多态的
（`motive n ×' below n`，基 `PUnit`），单态 toy env 表达不了；故把 brecOn 当作
带派生规则的原始派发，比硬塞 PProd 更忠实可控。真递归（minor 用 below 取递归值）
留 P7.5c-2，届时需引入 PProd/NatBelow 表示（设计分叉）。

**P7.5c-1 验收**：参照机 vs 真 lean infer/defeq **82/82**（77→82，5 条
`deq_brec_*`：zero/succ/const/no/stuck）。图侧 5 例钉在 M3_PENDING（图 iota 待
P7.5c-1b），图 vs 参照机 77/82（5 钉）。回归全绿：whnf 34/34×3、M4.1 21/21+17/17、
M4.2 15/15、M4.3 16/16+8/8。

### 11.15 P7.5c-1b：`Nat.brecOn` 图侧 iota（2026-09-07）

**接线**（`lean_vm/build_vm.py`，OP_BREC=15 已在 P7.5c-1 进 tokens.py）：
brec 与 rec/casesOn 同构地铺进六层主选择器：

- 门（~L401-404）：`br_mot`/`br_F` 取 spine 第 2/3 实参，`brecop`（cid==34 且
  OP==OP_BREC），`fire_brec`（主前提到 nat 构造子形）。
- 结果/卡住门（~L571-584）：`brec_dn`、`brec_sd`、`br_motE/br_FE/br_motV0/
  br_FV0/br_FX/br_rtX`、`brec_nat = is_lit_r + is_zconst_r`、`brec_build_r`、
  `brec_stuck_r`。
- 分支态（~L841-852）：`A_fire_brec`（pV0,pX,br_F[2],c1）、`A_build_brec`
  （SA,Zero,SC,c1）、`A_stuck_brec`/`A_sd_brec`（frE2,br_rtX,Zero,frV2，E=One、
  F=SF）。
- `is_brec_build` 进 em_frame 门与 raw_K/V0/V1 最外层选择器；B2/C2/D2/E2/F2
  在 `_select(is_cs_build_p2, …)` 后插 `_select(is_brec_build, …)`；六层
  main 选择器各插 4 条 brec 分支（fire/build/stuck/sd），per-block whnf 交付
  目标 A→A_done、B→SB、C→SC、D→frV2、E→One、F→SF，每块恰好 31 个闭合。

**toy env 修复（deq_brec_stuck 的真根因）**：`_pi_natbrecOn` 的结果 codomain
编码成了 `motive F`（de Bruijn `App(BVar(1), BVar(0))`，ctx [F,motive,t] 下
idx0=F），正确为 `motive t` = `App(BVar(1), BVar(2))`。诊断链（/tmp/bs7.py
token dump + 归一化 trace 对比）：cod 是惰性闭包，**run 1（spine 推理）从不
解引用它**——故 4 条 iota 例全绿；卡住例的 proof-irrel 链 PI_TY 会真正 INFER
cod 闭包 → `(fun _ => Nat) minor` → I 链推 minor 类型得 PICLO，与 dom=Nat 配对
成卡住对 → PI_T(33) → INFER(PICLO) → bad_i → REJECT code=4。RefVM 侧被
`_proof_irrel` 的 try/except 掩盖：cod-infer 抛异常 → 落回 spine 结构比较
（碰巧同判 TRUE），这就是 82/82 vs lean 一直全绿的假象。教训：**toy env 的
类型 AST 也要过图侧差分——ref 的软失败会吞类型错误**。

**P7.5c-1b 验收**：图 vs 参照机 infer/defeq **82/82**（0 pinned，解钉
5 条 `deq_brec_*`；步数 zero 27 / succ 27 / const 24 / no 27 / stuck 224）。
三层回归全绿：ref vs lean infer/defeq 82/82、whnf 34/34×3（图 vs lean、
图 vs ref、ref vs lean）、M4.1 21/21+17/17、M4.2 15/15、M4.3 16/16+8/8。
权重维持 M3 冻结（635,747,778 参数），未跑保真/引擎回归。

### 11.16 P7.5c-2 Route A：`Nat.brecOn` 忠实 delta-over-rec（2026-09-07）

**drecOn 结论（核查关闭）**：`drecOn` 在 lean 4.33.1 与 4.35 master 内核源码
（`/home/xkq/lean4/src/kernel/`、`src/library/`、elan 工具链源码）中**不存在**
（grep 零命中）——它是 Lean 3 命名；Lean 4 的 `Nat.rec` 本身就是依赖消除器，
派生族只有 `recOn`/`casesOn`/`brecOn`。Phase 7 的 brecOn/drecOn 目标由此收敛为
brecOn 单项。

**Route A 设计（忠实 delta，原语机退役）**：toy env 的 `Nat.below`/`Nat.brecOn`
携带真实 def-over-rec delta 值（`_below_value` = `Nat.rec UnitT.mk (fun n ih =>
motive n ×' ih) t` 的忠实编码；`_brec_value` = `(Nat.rec ⟨F 0 unit, unit⟩
(fun n ih => ⟨F n.succ ih, ih⟩) t).1` 的忠实编码，ih 兼任 below 实参）。
ref 的 K_CONST 门与图侧 OP_BREC 六层分支、tokens 常量**全部退役**——brecOn
消解 = delta → rec iota → P2-proj，全部走已有机制。语料扩到 7 条
（zero/succ/const/no/stuck/sum/sum_stuck）。

**单态 sidestep（设计分叉，明示）**：真内核 `PProd.mk` 是 universe-polymorphic
且良型；单态 toy 的 `P2.mk` 类型 domain 是 `Const(Nat)`，而 brec delta 的
M-body 把 `motive n : Sort 1` 喂给它 → **rec 应用的 infer 按构造失败**。
参照机靠 `_proof_irrel` 的 catch-decline 存活；图侧需要同语义（下述软 infer）。
below/brec delta 的 ih 域注记用封闭 `Sort 1`（真型是 below-app，会令
lam-compare 的 domain 检查沿 below 自身值无限递归；注记从不 sort-check）。

**图侧修复 1 — proj_same 帧发射缺失（deq_brec_stuck 死循环根因）**：
`proj_same` 只写了状态载荷（D=c1）而漏在 `em_frame_m2` 发射旗求和里 → 状态
D 指向状态 token 本身 → 帧栈丢失 → main 模式 proj_setup 原地打转。修复：
`em_frame_m2` 补 `+ proj_same`（与 deq_mdata 同型：单帧、槽 1，V2 保持 SD 让
旧 DEFEQ 帧在 verdict pop 时直通）。

**图侧修复 2 — 软 infer catch（对齐 `_proof_irrel` try 语义）**：
ref 语义：`_proof_irrel` 把 `infer(t)`/`infer(t_ty)` 包进
`try/except VMError(ERR_TYPE, ERR_UNSUPPORTED) → None → decline`；`infer(s)`
在 try 外（硬）；`_unit_like`/`_try_eta`/`_try_eta_struct` 不 catch。图侧机制：

- **walk ST 指向任务帧**：infer walk 推的 ST 一律 `V2 = SD`（其 TASK_INFER
  帧），infer 完成经 pop_task 穿任务帧交付（WALK 任务既有协议；与旧直通交付
  载荷等价：pop_task 转发 SA/SB/SC，D=task.V2，E 保持 1）。
- **F2 = 软旗**：TASK_INFER 帧的 F2 槽（本就无人读）作软旗。PI_T/PI_TY 启动
  置 1；嵌套 infer 全部继承（task 模式直读 `frF2`；cont 模式经 `fetch f2_
  frV2`，walk ST 的 V2 即任务帧）。pl_prop 的 `infer(s)`、eta/eta-struct/
  unit-like 链的 infer、CHECK/M4 启动均保持 0（硬，与 ref try 范围一致）。
  （P7.5c-3 修正：unit-like 链并不整体硬——图侧 UL 链对 t 侧结果类型的
  descend 对应 ref `_proof_irrel` 的 try 范围，须软；见 §11.17。）
- **失败投递**：`i_chk_fail`（arg-check DEFEQ 判 False）与 `bad_i`
  （ERR_UNSUPPORTED）在软旗下不 reject，改为向 `task.V2` 投递失败标记
  `A=0`（位置从 1 起，0 无歧义）；消费者 cont 级联上行：
  I_FN/I_ARG/I_LAMDOM/I_LAMBODY/I_PIDOM/I_PIS2/I_LETV/IP_TY 逐层转发，
  PI_TY 收到标记 → `pl_fall` → ST_SP（链条 decline 到 spine 比较）。
  **I_PIL1/I_PIL2/I_SORTEM 不加门**：它们消费 LEVEL 任务结果，A=0 是合法的
  level-zero。PI_LVL 收到标记自动 decline（stream[0]=T_NULL，非 K_SORT）。
- **验证**：4 条快速例步数逐位不变（zero 58/succ 89/const 67/no 88）；
  cyc_trace 确认软旗在活（TASK_INFER F2=1）且 DEFEQ 对序列单调走过 ref 的
  spine 比较树。

**良性 frankenstep（存照，不修）**：main_mode 不排除 ret_pending → pop_task
（E=1 + 任务帧）与 main 模式 proj_setup 同步触发，发射孤儿死 token；机器
语义不受影响（D/E 由 pop_task 定），先于本次改动即存在。

**P7.5c-2 验收**：见 PLAN（图 vs 参照机 7 条 brec 语料 + 三层回归数字）。
权重维持 M3 冻结（635,747,778 参数），未跑保真/引擎回归。

### 11.17 P7.5c-3 Route-2：pair-free 后 UL 链软拒收敛（2026-09-10）

**背景**：pair-free delta（dcdd9e5）消除 brecOn stuck 例的按构造 infer 失败后，
ref 判 `deq_brec_sum_stuck` = True，图侧却在 ~325 微步硬拒 code 4。此前
"recursor 结果类型实例化 off-by-one" 的诊断**不成立**：walk-off 本身合法，
错在**该拒绝处图硬拒、ref 却是 catch→decline**。ref 侧探针存照：该例判决路径
= `_proof_irrel` 连拒 7 次（try 捕获 / 不适用）、eta/eta-struct 不适用、
`_unit_like` 返回 None（不抛）、spine/nat-ctor 收 True——UL 链的 t 侧 infer
descend 始终落在 proof-irrel 的 try 语义内。

**图侧修复（build_vm.py，四层）**：
1. **UL 链软旗补 F2**：TASK_INFER 帧上 E2=相位 P1、**F2 才是软旗**（soft_flag）。
   ST_UL 与 ul_yes 两处 infer 启动原只置 E2=1，硬拒由此而生；两处补 `fr2_F2=1`。
2. **UL_W decline guard**：软 infer 失败向 UL_W 投递 A=0 哨兵；原逻辑会去 whnf
   哨兵 token 0（无 WHNF 规则 → 活锁）。guard 后 A=0 → 按 ul_no 同型向 caller
   交付 verdict-False（unit-like 判定失败，链条继续）。
3. **UL_D decline guard**：同型——s_ty=A=0 时不得 DEFEQ 哨兵，verdict-False 上行。
4. **wpos 嵌套 NAT 爬升**：casesOn 观察对象的 whnf 令 NAT 帧嵌套
   （NAT(succ)→NAT(caseson)→WHNF），软旗在**两级之上**的 WHNF 帧；原单跳爬升
   误读中间 NAT 帧的 E2（节点位置）为软旗 → code 1 误拒（@424）。`stuck_nat_nested`
   （parent 帧 task==TASK_NAT 时）再爬一跳取 `nbV2`。

**验收（纯 Python，graph vs ref）**：官方 suite（DEFEQ+INFER）**84/84、0 pinned**，
含 `deq_brec_sum_stuck` = True（1052 微步；此前为 pinned 硬拒）；brec 7 条全绿、
UL 相关（unit_like×2）、casesOn/stuck/rec 各层零回归；P75C_PENDING 清零。
**权重仍失配**：本改动后须
`python model/compile_vm.py`（全核）+ `make -C engine` 重编译并跑三层复钉
（保真/engine/lean oracle），因机器散热暂缓。

### 11.18 P7.5c-M5：proj 函数位待应用参数丢失（2026-09-12）

**症状**：`Nat.choose 10 3` 图侧 reject code 1（@236）；最小例 `Nat.choose 2 1`
（ref=2，图 @232 拒），`Nat.choose 1 0`（base case，无递归）通过。所有 `k>0`
例同在 @232 拒——与 n/k 取值无关，说明卡在递归分支的形状而非数值。

**根因**（不在 nat/casesOn 的 extras）：`Proj` 处于**函数位**时待应用参数
丢失。以 choose 的 `(P2.fst ih) k` 为例：外层 App 把 `k` 压入 pend（C=SC）后
转去 whnf `Proj(P2,0,ih)`；`proj_setup` 推帧、whnf child；child 归约完后
`I_PROJ` 提取字段并**无条件置 C=0**（旧 L2567）→ `k` 丢失 → 焦点停在字段
（choose 中是 `fun k => match_1 …` 的 Lam，本应 beta 应用 `k`）→ 该 Lam 成
`Nat.add` 的实参 → `nat_hard`（`wE2 != 1`）硬拒。

**最小复现**（toy env，无需 Mathlib；须给 RefVM 传 `structures=TOY_STRUCTS`，
否则参照机不归约 proj）：
- `Proj(P2,0, P2.mk (fun y=>y) T_two) 3`：ref=`3`，修前图=`fun y=>y`。
- `Proj(P2,0, T_pair) 3`：ref=`2`，修前图=`T_two`。
两条都是字段交付后参数未消费。

**图侧修复（build_vm.py 三处）**：
1. `proj_setup` 推 ST 帧时，把进入 child 子 whnf 前的待应用链 `SC` 存入该帧
   **自由的 E2 槽**（`frame_E2` 末端注入 `_select(proj_setup, SC, …)`；
   `proj_setup` 是 main 模式 focus=Proj，与 iota 的 focus=Const 状态互斥，
   注入不会碰撞）。
2. `I_PROJ` 令 `C_c = frE2`（原 `Zero`）恢复该链。
3. `I_PROJ` 的 `E_c`：`frE2>=1`（有保存链）时置 0 → 回 main 模式，由常规 app
   机制消费参数（Lam→beta、Const/App→归约后再应用、卡头→`mk_stuck` 重建 App
   spine）；`frE2==0` 时维持原 final-vs-reduce 判定。`proj_setup` 步本身已
   `C=Zero`（main 默认表），child 子 whnf 不受外层 pend 干扰。

**参照机配套**：`ref_vm.py` whnf 的 K_PROJ 分支提取字段后 `continue`（继续
whnf）——真内核 `reduceProj` 回灌 whnf；brecOn below-pair 的字段是未归约应用，
原样返回会停在非范式（这也是 choose 之前必须同时修 ref 的原因）。

**验收**：toy 语料新增 3 例 `proj_plain/proj_app_lam/proj_app_const`
（`test_stepgraph_vs_refvm.py`，RefVM 需 structures）→ **37/37**；choose 扫描
（RefVM vs 图）全 OK（2 1=2/600 步、3 1=3/921 步、10 3=120）；真实 Mathlib
`Nat.factorial 6/10`、`Nat.choose 10 3` 图侧收敛（real_env_bench graph=ran）；
三层 CPU 回归 **8/8**。

### 11.19 软 INFER 脊对齐内核 infer_only（I_ARG_S=69，2026-09-16）

**背景与依据**：软 INFER 通道（proof-irrel 链上的 infer，`soft_flag` 语义见
§11.16 修复 2 / §11.17）原先仍走硬通道的 arg 逐参验证式级联，d6 卡对环
三次修复（005 F13-02/F14 fix2/F15 fix3 前两次）均是在硬 I_ARG 上做变体。
裁决 2 换新简报：对齐内核 infer_app 的 **infer_only 脊**
（`K/type_checker.cpp:189-205`：不 infer 实参、不做 arg-vs-domain DEFEQ，
沿 Pi 体走、末尾 instantiate_rev；对照完整通道 `:174-188`）。

**图侧新增（build_vm.py，老 I_ARG 硬语义一字不动）**：
- 新 cont id `I_ARG_S=69`，仅软 infer 帧（frF2=1）可达；总 cont id 数 69。
- **软 I_PI step**（`pi_walk` 门 = cg[I_PI]·soft_flag·(sk3 是 K_PI/T_PI_CLO)）：
  focus 换 Pi 体（`v1_(SA)`，状态解引用；首个软 I_PI 的 ST.V1=0，故读 focus
  的 kind 而非帧链 tK——与 §11.17 的软旗读取同一陷阱族），B=c1，发
  link(P=focus body env, E=paX, F=0) + TASK_WHNF 帧（V2=c2，硬 ensure_pi）+
  ST(I_ARG_S)；args 链与深度由 fr1 携带（`fr1_X=c1`、`fr1_E2=paV2`、
  `fr1_F2=I_ARG_S`）。
- **resume step**（`args_walk` 门 = cg[I_ARG_S]·链未空(frE2>=1)·focus 仍 Pi）：
  同构续层（link 下一 arg、WHNF 下一体）；**链空**（`args_done`）→ 交付
  (SA,SB) 原样 E=1 D=frV2，无 link 无 frame。resume 的剥皮目标是 **focus 的
  body**（I_PI step 与 resume 各自按当时 focus 求值同一表达式 `v1_(SA)`），
  不是 ST.V1——resume 时 ST.V1 仍是上一层 Pi，tV1 会错位一层 de Bruijn。
- **失败通道**：focus 非 Pi 且 args 链未空（`i_args_notpi`）与 focus kind
  非 Pi 的软 I_PI（`i_pi_bad_pi`，读 sk3=whnf 后的 f_type kind）并入既有
  `i_pi_soft` 投递（**decline 级联语义未动**）；发射计数 link+frame+frame2
  与 I_CHK 成功形同构，**c1=POS+1/c2=POS+2 地址算术未动**。
- 实现陷阱（F15-08）：I_CHK 块对 `em_link1_c` 是**重赋值**，软 I_PI 的
  link 旗必须在该块并入（`em_link1_c = chk_ok + pi_walk`），先前 `+=`
  会被抹掉；args_done 的链空判是 `frE2>=1` 的否定（paV2=0 时链头 arg
  尚未消费，off-by-one 由原始 dump 定位）。

**验收**：d7（d6l=?=d7r 对照例）= False，路径=预测形（软脊走完 →
proj-infer 消费链 → IP_PEEL/PI_LVL 失败 → A=0 → PI_TY ST_SP decline →
卡对链，005 F15-01 预测 / F15-08 实证）；全量差分
`tests/test_brec_drec_iota_vs_lean.py` B/C 组 10 例与 oracle 一致 +
G4_d6 xfail（见下），账面 0 divergence；scratch 稀疏权重（dims 25,930/
lookups 2,898/nnz 192,405，较基线 +1,016/+20/+5,513）引擎对拍 34/34。
**G4_d6 为 KNOWN-GAP**（卡对链 go-pair 实参同 pos 异 env 根 → DEFEQ 内部
WHNF 展开 below 族 → 结构逐轮加深的 PI_T 环；内核同常量脊比对从不展开
below，`#print Nat.brecOn/go` 原文见 005 F15-08）——裁决 3 停手，全面
定谳与后续出路（缓存层）见 `docs/decisions/018-soft-infer-spine-and-d6-known-gap.md`。
**卡 014 P2 落地后追记**：whnf memo（§18）使 d6 于 1012 步收敛
halt=True（P1-only=1070；内核判定 True 一致），但 720 步帽内不绿——
位置键 memo 无法吸收逐轮新位置的 below 展开，G4_d6 维持 KNOWN-GAP。

---

## 12. level / universe 语义（WP2 规格）

本节是 WP2 的规格，覆盖 `docs/KERNEL_COVERAGE.md` §2.D 的 D1–D14。语义来源为
内核源码 `/home/xkq/lean4/src/kernel/`（下称 `K`）；数据模型
`R/expr/model.py:90-118` 已与 `K/level.h:20-30` 一致，现有编码见 §4
（`docs/VM_SPEC.md:114-122`）。WP1（`docs/ENV_FORMAT.md`）把常量 universe
参数的**个数**编码为 `T_ENV_META.V0`（`R/expr/tokens.py:35,175`；
`docs/ENV_FORMAT.md:191-196`），**名字**留待本节决定
（`docs/ENV_FORMAT.md:493-496` 第 3 条）。

本节只定义语义、编码与验收，不写实现。

### 12.1 level 的 token 编码

**节点形状**（KL_* 为 `K/level.h:30` 的 kind 枚举 1-based，
`R/expr/model.py:66-72`；编码 `R/expr/tokens.py:286-307`，解码 `:422-436`）：

| K | 节点 | V0 | V1 | X | V2 | 内核依据 |
|---|---|---|---|---|---|---|
| 1 KL_ZERO | zero | 0 | 0 | 0 | 父指针 | `K/level.h:91` |
| 2 KL_SUCC | succ l | 子节点位置 | 0 | 0 | 父指针 | `K/level.h:70,97` |
| 3 KL_MAX | max a b | a 位置 | b 位置 | 0 | 父指针 | `K/level.h:64-65,95` |
| 4 KL_IMAX | imax a b | a 位置 | b 位置 | 0 | 父指针 | `K/level.h:66-67,96` |
| 5 KL_PARAM | param n | nid(名) | 0 | 0 | 父指针 | `K/level.h:71,98` |
| 6 KL_MVAR | mvar n | nid(名) | 0 | 0 | 父指针 | `K/level.h:72,99` |

参数名的 nid 进 NAME 表（`b.nid`）；nid 整数相等即内核 `Name` 相等
（`K/level.h:71-73` `param_id`，`K/level.cpp:294`）。level 节点均带 V2 父指针；
**根节点若作为 const 的 level 实参，其 X 复用为兄弟链指针**，非根 X=0
（§4 的零冲突约定，`docs/VM_SPEC.md:122`）。

**常量 level 实参块（本次要补的缺口）**。`K_CONST`(K=5)：
V0=cid，V1=第一个 level 实参的子树根位置（无实参则 0）；各实参子树根按实参
顺序用 X 串成兄弟链，最后一个 X=0（`R/expr/tokens.py:229-239`；§4
`docs/VM_SPEC.md:102,119-122`）。实参个数 = 沿 X 链读到的根数。

- 位置寻址：每个实参是一棵独立 level 子树，根位置任意；运行期从 `K_CONST.V1`
  起、按 `X=下一根` 读完整条链，不靠相邻位置。
- 使用侧个数必须与目标常量的声明侧个数相等：内核比较
  `length(get_lparams())` 与 `length(const_levels(e))`
  （`K/type_checker.cpp:105-108`；`K/declaration.h:463-464`），对应 token 层
  `T_ENV_META.V0`（univ_arity）与 X 链长度。§4 括注"通过 ENV_META 的
  univ_arity + 兄弟链组织"应理解为：`univ_arity` 是声明侧期望个数，X 链是
  使用侧实参，二者独立存储、运行期比对，不是用 univ_arity 限长 X 链。
- 现状缺口：`R/expr/tokens.py:172,175` 恒写 `T_ENV_META.V0=0`；
  `_enc_level_args`（`:309-318`）是"数类型 Pi binder"的错误代理、恒返回 0，
  WP2 应删除该函数，改由每个常量的声明 lparams 驱动。

**声明侧 lparams 名字表（本节新增，WP1 留白）**。内核的 instantiate 与
get_undef_param 都按名字进行（`K/level.cpp:294,329-331`），所以运行期必须能
拿到某常量 lparams 的**有序名字表**：

- 新增专用元数据 token `T_ENV_UNIVPARAMS`，K=39（取 `docs/ENV_FORMAT.md:168`
  空闲段 14–20、39–200 中最小未占用值），挂在 per-cid 元数据链上，字段
  `V0=cid, V1=名字链头, F2=next_meta`，与 ENV_FORMAT §2.4 的链约定一致。
- 名字链复用 `T_ENV_LIST`（K=35，`docs/ENV_FORMAT.md:229`），`role(V2)=2`，
  `V0=owner_cid, V1=nid(参数名), X=next_node`；顺序必须等于声明
  `get_lparams()` 顺序（`K/declaration.h:70`），index i 对应 instantiate 的
  `ps[i]`（`K/level.cpp:329-333`）。
- `T_ENV_META.V0` 仍为个数，必须等于名字链长度；不一致判编码错误。
- univ_arity=0 的常量可省略该 token（V1=0，与现状兼容）。

### 12.2 D1–D14 精确语义

**D1 mk_max**（`K/level.cpp:81-104`）。按序：
1. l1、l2 均 explicit → 返回 `get_depth` 较大者，相等取 l1（`:82-83`；
   `get_depth(zero)=0`、`get_depth(succ x)=get_depth(x)+1`，`:40`）。
2. `l1 == l2` → l1（`:84-85`）。
3. `zero(l1)` → l2；`zero(l2)` → l1（`:86-89`）。
4. `is_max(l2)` 且 l1 是 l2 的某一侧 → l2；对称地 `is_max(l1)` 且 l2 是其一侧
   → l1（`:90-93`）。
5. 否则 `p1=to_offset(l1)`、`p2=to_offset(l2)`：base 相同 → offset 大者
   （`:95-99`）；base 不同 → `mk_max_core` 裸构造（`:100-102`；`mk_max_core`
   `:34`）。

**D2 mk_imax**（`K/level.cpp:112-123`）。按序：
1. `is_not_zero(l2)` → `mk_max(l1,l2)`（`:113-114`）。
2. `is_zero(l2)` → zero（`:115-116`）。
3. `is_zero(l1) || is_one(l1)` → l2（`:117-118`；`is_one` 定义 `:106-110`，
   即 `l == succ zero`）。
4. `l1 == l2` → l1（`:119-120`）。
5. 否则 `mk_imax_core` 裸构造（`:122`；`:35`）。
第 3 条的 `is_one(l1)` 分支是内核规则；Lean 侧 `Level.mkLevelIMax'`
（`src/Lean/Level.lean:542-551`）无此分支，oracle 不能拿它当结构期望（12.5）。

**D3 结构相等 operator==**（`K/level.cpp:125-150`）：kind 不同 false；hash 不同
false；指针同 true（`:127-128`）；Zero→true（`:130-131`）；Param/MVar 比
`level_id`（`:132-133`）；Succ/Max/IMax 先比 depth 再递归，Succ 比子、Max/IMax
比两侧（`:134-148`）。hash/depth 只是快速路径（`:39-40,44-52`），VM 直接结构
递归与之一致。

**D4 is_equivalent**（`K/level.cpp:518-521`）：
`lhs == rhs || normalize(lhs) == normalize(rhs)`（`:520`）；`check_system`
（`:519`）只做资源检查，不改语义。type_checker 的 `is_def_eq(level,level)`
就是这个（`K/type_checker.cpp:814-820`；声明 `K/type_checker.h:88`）。

**D5 normalize**（`K/level.cpp:454-516`）：
- `p = to_offset(l)`（`:455`），`r = p.first`（剥掉外层 `succ^k`），
  `k = p.second`。
- r 为 Zero/Param/MVar → 原样返回 l（`:460-462`）。
- r 为 IMax：`l1=normalize(imax_lhs(r))`、`l2=normalize(imax_rhs(r))`，返回
  `mk_succ(mk_imax(l1,l2), k)`（`:463-467`）。
- r 为 Max：用 `push_max_args` 摊平 max 树（`:420-427`），逐元素 normalize
  （`:470-473`），按 `is_norm_lt` 排序（`:474`；定义 `:395-418`），按 explicit
  吸收/去重规则处理（`:477-510`），给每个结果加外层 offset k（`:511-512`），
  `mk_max(buffer)` 重建（`:513`；`:429-444`）。
- `is_norm_lt`（`:395-418`）：先 `to_offset` 剥 succ，再比 base；base 不同按
  kind 枚举序（`K/level.h:30`：Zero < Succ < Max < IMax < Param < MVar）比
  kind（`:402`）；Param/MVar 比 name（`:407`）；Max/IMax 字典序比 lhs 再 rhs
  （`:408-412`）；base 相同比 offset（`:415-416`）。
- **重要**：该排序与 Lean 侧 `Level.normalize` 的 `normLt` 不同（Lean 用
  `ctorToNat` 序 Zero < Param < MVar < Succ < Max < IMax，
  `src/Lean/Level.lean:267-302`）。实测 4.33.1 binary 把
  `max (imax u v) w` 归一为 `max w (imax u v)`，而 C++ `is_norm_lt` 的 kind
  序会把 IMax 排在 Param 前。故 oracle 不能比较 normalize 的序列化结构
  （12.5）。VM 按 C++ 规则实现。

**D6 is_lt（level 与 levels 两版）**（`K/level.cpp:189-215` / `:217-226`）：
任意全序，仅作缓存 key（`level_quick_cmp`，`K/level.h:158-161`），不参与判定
语义。规则：指针同 false（`:190`）；depth 小 true、大 false（`:191-194`）；
kind 不同比 kind（`:195`）；use_hash 时比 hash（`:196-199`）；结构相等 false
（`:200`）；否则 Param/MVar 比 name（`:204-205`）、Max/IMax 比 lhs 再 rhs
（`:206-210`）、Succ 比子（`:211-212`）。levels 版先比头再比尾（`:217-226`）。
是否实现见 12.6 第 2 条。

**D7 is_geq / is_geq_core**（`K/level.cpp:523-544`）：
`is_geq(l1,l2) = is_geq_core(normalize(l1), normalize(l2))`（`:542-544`）；
`is_geq_core` 假定两侧已归一：
1. `l1 == l2 || zero(l2)` → true（`:524-525`）。
2. `is_max(l2)` → 对两侧都 geq（`:526-527`）。
3. `is_max(l1)` 且任一侧 geq l2 → true（`:528-529`）。
4. `is_imax(l2)` → 对两侧都 geq（`:530-531`）。
5. `is_imax(l1)` → 只与 rhs 比（impredicative：`imax u v ≥ x` 当且仅当
   `v ≥ x`，`:532-533`）。
6. `p1=to_offset(l1)`、`p2=to_offset(l2)`：`p1.base == p2.base` 或
   `zero(p2.base)` → `p1.off >= p2.off`（`:534-537`）；offset 相同且 > 0 且
   base 不同 → `is_geq(p1.base, p2.base)`（`:538-539`）；否则 false（`:540`）。

**D8 is_not_zero / normalizes_to_zero**（`K/level.cpp:160-172` / `:174-187`）：
- `is_not_zero`（对**所有**赋值都非零）：Zero/Param/MVar→false，Succ→true，
  Max→`lhs || rhs`，IMax→只看 rhs（`:160-172`）。Param/MVar 为 false 是关键。
- `normalizes_to_zero`（项本身归零）：Zero→true，Param/MVar/Succ→false，
  Max→`lhs && rhs`，IMax→只看 rhs（`:174-187`）。
- `is_prop` 用后者（`K/type_checker.cpp:383-389`）：`imax 1 0` 这种项必须经
  normalizes_to_zero 判为 Prop。

**D9 is_explicit / to_offset / to_explicit**（`K/level.cpp:54-64 / 67-74 /
76-79`）：is_explicit：Zero→true，Param/MVar/Max/IMax→false，Succ→递归子
（`:54-64`）。to_offset：剥 succ 得 `(base, k)`；非 succ 得 `(l, 0)`
（`:67-74`）。to_explicit：要求 is_explicit，返回 `to_offset().second`
（`:76-79`），`to_explicit(zero)=0`。

**D10 instantiate(level, params, levels)**（`K/level.cpp:317-340`）：前置条件
`length(params) == length(levels)`（`:318` assert，不抛异常）。用 `replace`
自顶向下（`:261-277`）应用：
- l 不含 param → 原样（`:320-321`）。
- l 是 Param：按位在 params 里找 `param_id(l)`，命中返回 `levels[i]`；
  **未命中原样返回 l，不报错**（`:322-335`）。
- 其它（Max/IMax/Succ 含 param）→ none，继续递归（`:336-338`）。
重建时 `update_succ`/`update_max` 会重跑 mk_succ/mk_max/mk_imax 智能构造
（`:301-315`）。LMVar 不含 param，直接原样返回（`:320-321`）。
（"undefined param 报错"来自 D11 + check_level，不是 instantiate。）

**D11 get_undef_param**（`K/level.cpp:289-299`）：`for_each` 前序遍历 level
（`:247-259`）；某子树不含 param 或已找到就停止下行（`:292-293`）；遇到 Param
且 `param_id` 不在 ps 中（`std::find`，`:294`）即返回该名字；否则 none。
`check_level` 依赖它（`K/type_checker.cpp:85-91`）。

**D12 lparams_to_levels**（`K/level.cpp:545-550`）：把 names 按序 map 为
`mk_univ_param`，顺序保持。使用点 `K/inductive.cpp:138,255,998`（生成/复制
归纳与 recursor，非证明检查主路径）。

**D13 instantiate_lparams(expr, lps, ls)**（`K/instantiate.cpp:232-246`）：先
`has_param_univ(e)` 短路（`:233`；`K/expr.h:157,358`）；`replace` 自顶向下
（`:235-245`）：Constant 节点把 `const_levels(e)` 的每个 level 用 D10
instantiate 后 `update_constant`（`:238-239`）；Sort 节点
`update_sort(instantiate(sort_level(e)))`（`:240-241`）；其余返回 none 继续
递归（`:242-244`）。只替换常量 level 实参与 Sort level，不改其它结构。

**D14 instantiate_type_lparams / instantiate_value_lparams**
（`K/instantiate.cpp:248-254 / 256-264`）：
- 两者先校验 `get_num_lparams() == length(ls)`，不等则 `lean_internal_panic`
  （`:249-250 / :257-258`）——这是**不可捕获的内部错误**，不是
  kernel_exception；正常路径由 infer_constant 的显式 arity 检查先拦
  （`K/type_checker.cpp:105-108`）。
- type 版：ls 空或 type 无 param univ → 原 type；否则
  `instantiate_lparams(type, lparams, ls)`（`:251-253`）。
- value 版：要求 `has_value()`，否则 panic（`:259-260`）；同样短路后
  `instantiate_lparams(value, ...)`（`:261-263`）。

### 12.3 在检查路径中的使用点

- **check_level**（`K/type_checker.cpp:85-91`）：仅当 `m_lparams != nullptr`
  （`check` 模式）才检查；`infer_type` 模式不检查（`m_lparams=nullptr`，
  `:360-362,1280`）。`check` 设定 lparams（`:364-367`），
  `check_ignore_undefined_universes` 显式置空（`:369-372`）。
- **infer_constant**（`K/type_checker.cpp:101-123`）：
  1. `length(lparams) != length(const_levels(e))` → 抛 kernel_exception
     （`:105-108`）。
  2. 非 infer_only 时先 unsafe/partial 检查（`:110-117`），再对每个显式 level
     调 `check_level`（`:118-120`）——检查的是**当前被检查声明的** lparams，
     不是目标常量的。
  3. 返回 `instantiate_type_lparams(info, ls)`（`:122`）。
- **infer_sort**（`K/type_checker.cpp:345-348`）：非 infer_only 时
  `check_level(sort_level(e))`（`:346`），类型 `mk_sort(mk_succ(...))`（`:347`）。
- **infer_pi**（`K/type_checker.cpp:144-166`）：逐 binder `ensure_sort` 后收每个
  域的 sort level 进 us（`:150-152`）；体 sort level 为 r（`:157-159`）；从内
  到外折叠 `r = mk_imax(us[i], r)`（`:160-164`），返回 `mk_sort(r)`（`:165`）。
  这是 D2 的主要消费点。
- **level 的 is_def_eq**：`is_def_eq(level,level)`（`K/type_checker.h:88`，impl
  `K/type_checker.cpp:814-820`）= D4；在 `quick_is_def_eq` 的 Sort 分支被调用
  （`:843-844`）。`is_def_eq(levels,levels)`（`:822-832`）逐位比，用于
  is_def_eq_core 常量同名同级判定（`:1209-1210`，KERNEL_COVERAGE A18）与
  lazy-delta hints 优化（`:1038`）。
- **is_prop**（`K/type_checker.cpp:383-389`）用 normalizes_to_zero（D8）。
- **is_delta/unfold_definition_core** 的 level 实例化缓存（A28）用
  instantiate_value_lparams（`K/type_checker.cpp:555-565`）。
- **check 需要 sort 的地方**：`ensure_sort_core`（`:62-71`）在不是 sort 时抛
  `type_expected_exception`（`:68-69`）。
- **D6/D7** 不直接出现在判定主路径：D6 只服务缓存；D7 不在 type_checker 的
  level defeq 里（defeq 走 D4），主要由归纳声明的检查使用（KERNEL_COVERAGE
  之外的 `K/inductive.cpp:482,560,600`）。WP2 仍要实现以备后续工作包。

### 12.4 错误行为与粗粒度错误码

| 情形 | 内核异常 | 来源 | Lean 侧观测（`Kernel.Exception`） |
|---|---|---|---|
| level 实参个数与常量 lparams 不符 | `kernel_exception`（普通） | `K/type_checker.cpp:105-108` | `.other "incorrect number of universe levels parameters for '...', #n expected, #m provided"` |
| 引用未声明的 universe param | `kernel_exception`（普通） | `K/type_checker.cpp:85-91`（D11） | `.other "invalid reference to undefined universe level parameter '...'"` |
| 需要 sort 处不是 sort | `type_expected_exception` | `K/type_checker.cpp:62-70` | `.typeExpected` |
| instantiate_type/value_lparams 个数不符 | `lean_internal_panic` | `K/instantiate.cpp:249-250,257-258` | 不可捕获（panic）；正常路径由上面的显式检查先拦 |

普通 `kernel_exception` 经 `catch_kernel_exceptions` 落入 `.other`
（`K/kernel_exception.h:201-203`）；`type_expected_exception` 映射到构造子 6
`.typeExpected`（`K/kernel_exception.h:95-101,183-185`）。

本仓库现有粗粒度码 `R/lean_vm/ref_vm.py:47-50`：`ERR_TYPE=1`、
`ERR_MISSING_CONST=2`、`ERR_OVERFLOW=3`、`ERR_UNSUPPORTED=4`。WP2 映射建议：
前两类与"非 sort"→ `ERR_TYPE`；未实现的 level 形态（LMVar 等）→
`ERR_UNSUPPORTED`。验收要求"拒绝时错误类别一致"，但现有 4 码无法区分
arity / undef / typeExpected（KERNEL_COVERAGE §6 第 1 条全局 TBD）。建议实现
时在 `VMError.detail` 保留内核消息类别、并新增等级错误码或子类，最终粒度随
§6 决定。

### 12.5 验收 / oracle 设计

> **状态：oracle 已实现（2026-09-12）**。`#LEVEL` 与 `#KDECL` 两种真 Lean oracle
> 见 `reference/lean_ref.py`（`LEVEL_TEMPLATE`/`KDECL_TEMPLATE`、
> `run_level_oracle(defs, cases)`/`run_kdecl_oracle(defs, cases)`），自洽性测试见
> `tests/test_level_vs_lean.py`。VM 侧谓词 API 与 VM-vs-oracle 逐项比对仍属后续
> 工作包（(A)/(C) 中的 VM 侧部分尚未实现）。

**现状**：仓库无独立 Level API 真 Lean oracle（`docs/KERNEL_COVERAGE.md:220-221,
348`）。现有 `reference/lean_ref.py` 的 `ORACLE_TEMPLATE`（`:27-87`）只有
WHNF/DEFEQ/INFER。方案：**扩展 `reference/lean_ref.py`**（不新建模块，保持单一
oracle 入口），新增两种命令与两个 `run_*` 函数，并新增测试
`tests/test_level_vs_lean.py`（仿 `tests/test_ref_infer_defeq.py:59-107` 的入口
与比较风格）。期望值一律由真 `lean`（`~/.elan/bin/lean`）产生，不得手写。

**(A) `#LEVEL`：纯 level 代数 oracle。** 用 `Lean.Level` 公开 API + `#eval`。
实测 4.33.1 binary 可用：`Level.zero/.succ/.max/.imax/.param`、`Level.one`、
`Level.normalize`、`Level.isEquiv`、`Level.geq`、`Level.isNeverZero`、
`Level.isAlwaysZero`、`Level.isExplicit`、`Level.getOffset`、
`Level.getLevelOffset`、`Level.instantiateParams`、`Level.occurs`、
`Level.normLt`；而 `Level.mkLevelMax`/`mkLevelMax'`/`mkLevelIMax'` **不可见**
（实测 `#check` 报 unknown，未暴露）。因此：
- 造 level 用**裸构造子** `.max`/`.imax`/`.succ`/`.param`/`.zero`（对应 C++
  `mk_max_core`/`mk_imax_core`）。
- **不要比较 `normalize` 的序列化结构**：binary 的 `Level.normalize` 是 Lean
  侧实现，`normLt` 参数序（`ctorToNat`）与 C++ `is_norm_lt` 的 kind 序不同
  （12.2 D5 已给出实测反例）。序列化比较会假失败。
- 可用观测（两实现应一致的谓词）：`isEquiv(a,b)`（D4，同时覆盖 D5/D10 的
  语义面）、`geq(a,b)`（D7）、`isNeverZero`（D8 的 is_not_zero）、
  `isAlwaysZero`（D8 的 normalizes_to_zero）、`isExplicit`（D9）、`getOffset`
  （D9 的 offset 计数）、`getLevelOffset`（D9 的 base）、`occurs`（D11 基础）。
  `instantiateParams`/`normalize` 的结果再用 `isEquiv` 与另一构造项比较
  （如断言 `isEquiv (instantiateParams l ps ls) expected = true`）。
- 输出：每 case 一行 `LEVEL <id> <json>`，json 放上述布尔/整数；Python 解析
  后与 VM 对应谓词逐项比。VM 侧谓词 API 由 WP2 实现（建议 `expr/level.py`：
  `is_equivalent/normalize/is_geq/is_not_zero/normalizes_to_zero/is_explicit/
  to_offset/to_explicit/instantiate/get_undef_param/lparams_to_levels/occurs`，
  签名对应内核）。
- 语料（每类至少含一个 Param）：D1 各分支（显式取大、等值、零吸收、max 吸收、
  同 base offset、不同 base）；D2 各分支（`imax u 0`、`imax 0 u`、`imax 1 u`、
  `imax u u`、rhs 非零走 max）；succ 传播 `normalize (succ (max ...))`；
  `geq` 的 max/imax/offset 分支；`instantiateParams` 命中/未命中/嵌套；
  `occurs`；`isExplicit/to_offset/to_explicit`。因 smart constructor 不可直接
  调用，D1/D2 分支以 `normalize(.max ...)`/`normalize(.imax ...)` 的谓词结果
  等价覆盖，并在语料注释里标出每个 case 覆盖的 C++ 行号。
  一个反例种子（必须进语料）：`normalize (max (imax u v) w)` 的结构在 binary
  与 C++ 间不同，但 `isEquiv` 相同——用它证明测试只比谓词。

**(B) `#KDECL`：内核声明 oracle（D1/D2/D4/D5/D7/D10/D11/D13/D14 的主证据）。**
用 `Lean.Kernel.Environment.addDecl`（`~/.elan/toolchains/leanprover--lean4---
v4.33.1/src/lean/Lean/AddDecl.lean:23`，实测可用）向环境加原始 `Declaration`，
让**真 C++ 内核**跑 `check`（内部走 infer_constant/check_level/
instantiate_type_lparams/ensure_sort/is_def_eq(level)），把
`Except Kernel.Exception Environment` 的构造子名打一行
`KDECL <id> OK|<class>`。已实测的语料形状：
- `axiom A.{u} : Sort u` → OK。
- `defn` levelParams=[] 且 type/value 用 `Sort (param u)` →
  `.other "invalid reference to undefined universe level parameter 'u'"`
  （D11 + check_level）。
- `defn` 的 value = `Bool.{u}`（Bool 有 0 个 lparams）→ `.other
  "incorrect number of universe levels parameters for 'Bool', #0 expected,
  #1 provided"`（infer_constant + D14 前置）。
- `def B : Sort 1 := A.{1}` → OK（D10/D14 正确实例化）。
- `def C.{u} : Sort (imax 1 u) := A.{u}` → OK；`def D.{u} :
  Sort (imax u 1) := A.{u}` → `.declTypeMismatch`；`def E.{u} :
  Sort (max u 1) := A.{max 1 u}` → OK。这三条把 D2 的 `is_one` 分支与
  D4/D5 通过真内核钉死。
- 另加一条非 sort（如 value 的声明类型是 `A.{u}` 而 value 用 `Bool`）→
  `.typeExpected`（12.4）。

**(C) 测试文件。** 新增 `tests/test_level_vs_lean.py`：
- 调 `reference.lean_ref.run_level_oracle(defs, cases)`（12.5(A) 新增），VM 侧
  用 12.5(A) 的谓词 API 逐项断言相等；失败打印 case id 与两侧值。
- 调 `run_kdecl_oracle(defs, cases)`（12.5(B) 新增），VM 侧对同一声明给出
  OK/错误类别，断言类别相等（先比 "OK vs 非 OK"，类别粒度收紧随 12.6 第 3 条）。
- VM 侧输入沿用 `reference/toy_env.py` 的常量定义方式；univ 多态声明语料需要
  WP1 编码支持，最小语料建议直接建在测试文件里，不改 `reference/toy_env.py`。
- 回归：`tests/test_ref_infer_defeq.py`、`tests/test_stepgraph_infer_defeq.py`、
  `tests/test_check_e2e.py`、`tests/test_mutation_reject.py`、
  `tests/test_olean_export.py` 不破（KERNEL_COVERAGE 的 Reg 栏）。
- oracle 代码与测试在 WP2 实现阶段落地；本节只定接口、语料与断言内容。

### 12.6 WP2 TBD

1. **lparams 名字 token 与列表 role**：本节取 `T_ENV_UNIVPARAMS=K39` +
   `T_ENV_LIST role=2`。备选：独立列表 kind，或塞进 `T_ENV_META` 未用字段
   （现无空位）。建议按本节方案，理由：K39 在 ENV_FORMAT §2.2 空闲段内、复用
   已有列表布局、只增不重排；需同步更新 `docs/ENV_FORMAT.md` §2.4/§2.7
   （本文不改该文件）。
2. **D6 is_lt / level_quick_cmp 是否实现**：只服务 A27 缓存，不影响判定；且
   binary 无公开 `isLt`（只有语义不同的 `normLt`），难做真 Lean 差分。建议
   实现但不列为 WP2 验收硬项，属性能取舍。
3. **错误类别粒度**：现有 4 码无法区分 arity / undef / typeExpected（12.4）。
   建议新增 level 专用码或子类，并在 `detail` 保留内核消息类别；最终粒度随
   KERNEL_COVERAGE §6 全局决定。
4. **normalize 的结构对齐程度**：D4 只比较同实现内两个归一形，任何规范形都给
   出相同等价判定；但若将来有处直接比较归一形（缓存 key、序列化输出），则必须
   与 C++ 逐结构一致。建议逐结构对齐 C++（含 `is_norm_lt` 的 kind 序与
   explicit 吸收），代价只是排序 comparator。
5. **LMVar 处理**：内核 type checker 直接拒绝 mvar（`K/type_checker.cpp:342`），
   instantiate 对 LMVar 原样返回（`K/level.cpp:320-321`）。VM toy 无 mvar；
   建议 instantiate 原样、其余谓词按 D3/D8/D9 结构规则；若出现在被检查项中则
   `ERR_UNSUPPORTED`。
6. **check_level 的 m_lparams 在 VM 中的载体**：内核由 `check(e, lps)` 显式传入
   （`K/type_checker.cpp:364-367`）。VM 的 CHECK 任务需携带被检查声明的 lparams
   （建议：任务参数 + 该 cid 的 `T_ENV_UNIVPARAMS`，二者一致）。具体任务编码属
   WP7/图侧，本文不锁死。
7. **binary 4.33.1 与源码 4.35 的一致性**：D1–D14 在两者间应稳定（实测关键行为
   一致），但 Lean 侧 `Level.normalize` 与内核 C++ `normalize` 的 normal-form
   参数序已证不同（12.2 D5、12.5(A)），所以纯 API oracle 只比谓词；内核声明
   oracle（12.5(B)）走的是 binary 的 C++ 内核，是判定行为的直接证据。若发现某
   D 函数两者语义不一致，以 `/home/xkq/lean4` 内核源码为准并在本节记录。

### 12.7 WP2b：level 实例化的图侧实现（D13/D14）

> **状态：已实现（2026-09-13）**。`tests/corpus/coverage.lean` 的
> `Cov_poly_nat : Cov_id Cov_two = Cov_two` 与 `Cov_poly_type : Cov_id Nat = Nat`
> 两条在图侧从 `ERR_1` 变为接受（StepDriver：294 / 251 微步）。

**内核语义。** `infer_constant` 推断常量类型时返回
`instantiate_type_lparams(info, ls)`（`K/type_checker.cpp:122`；前置 arity 检查
`:105-108`）。`instantiate_type_lparams` = `instantiate(info.get_type(),
info.get_lparams(), ls)`（`K/instantiate.cpp:248-254`），`instantiate` 把每个
`Param p` 替换为 `ps[i]`（`K/level.cpp:317-340`），命中判定按 `p` 在
`ps` 中的下标（`find`，`:329-333`）；替换用 `level` 版递归（`:302-315`）并对
`imax`/`max` 重建走 `mk_imax`/`mk_max`（D1/D2）。`instantiate` 在本仓库的
`ref_vm.py` 已有精确实现（`_inst_level`/`_inst_expr`/`_instantiate_value`），
图侧此前缺这条"按声明 lparams 位置替换"的通道。

**编码（新增 K_CONST.E2）。** 与在图上做替换不同，本实现把实例化**在编码期
完成**：`Encoder` 初始化时保存每个 cid 的声明类型（`_const_type_expr`），
遇到带 level 实参的 `Const` 时调用 `_specialize_type(cid, levels)`：

1. 取该 cid 的声明 `lparams`（WP2 §12.1 的 `T_ENV_META` 名字链）与 use-site
   `levels`，个数不等则不实例化（内核 `:249-250` 的 panic 前置已由
   `infer_constant` arity 检查覆盖，返回 0 即退回共享声明类型）。
2. 若声明类型**不含** universe param 则不实例化（`has_param_univ` 短路，
   `K/instantiate.cpp:233,238-240`）。
3. 否则按位置建 `{lparam_name -> levels[i]}` 映射，对声明类型做 D13 递归
   替换（`_inst_expr`，与内核 `instantiate` 同构；未变化时保留对象身份），
   把实例化后的类型树编码进 stream，根位置写入该 `K_CONST` 的 **E2** 字段。
   E2=0 表示该 use site 单态 / 无 param，沿用 `ENV_HDR.V1` 的共享声明类型。
4. `_specializing` 集合做 D14 发射环保护（自引用声明的实例化终止）。

图中 `CONST` infer 分支据此选类型：
`A_i = select(const, E2>=1 ? E2 : ENV_HDR.V1, A_i)`
（`lean_vm/build_vm.py` CONST 段）。因此 `Cov_id`（`{α : Type u} → α → α`）
在 `Cov_id Cov_two` 处以 `u := 1`、在 `Cov_id Nat` 处以 `u := 0` 实例化，
`I_ARG` 的 `defeq(arg_type, domain)` 拿到 `Sort 1`/`Sort 0` 而非
`Sort (succ (Param u))`，D10/D13/D14 在检查路径上闭合。

**与 §12.1/§12.2 的关系。** 本机制不新增 level 节点，也不依赖运行期的符号
level 链：实例化后的类型是普通的、param-free 的 expr 子树，走既有 expr 编码。
`universe u` 中 `u` 的 `Sort` 在单一 use site 上已解析为具体整数等级，故
`docs/VM_SPEC.md` §12.1 的符号 level 比较（`deq_sort`/`_lvl_chain_eq`）无需
在 DEFEQ 期解 `Param`。这是有意的取舍：把替换前移到编码期，避免在图上引入
逐 param 查表的运行期链（试过运行期 `T_LVLSUB` 环境链方案，`build_step_graph`
因子树指数复制而不可行）。

**跨 kind Pi binder 身份修复（附带）。** D_XPI2 比较两 Pi 时，若一侧是 lambda
推断出的 `T_PI_CLO`、另一侧是显式 `K_PI`，两 binder marker 原本都得 bid=0，
D_BV3 要求 bid>=1 才认同一 binder，于是 α-相等的体对被送进 stuck 链。
修复：`I_LAMSORT` 给 marker link 的 F2 写 bid=1；D_XPI2 在 `xgip` 分支读
`T_PI_CLO` 体环境（`t: oBdE, s: sBdE`）的 E2 标志与 F2 bid，把该 bid 采纳为
新 marker 的 bid。两 marker 同 bid 后 D_BV3 正常收敛。该修复只改 marker 身份，
不改 T_PI_CLO token 本体（其 F2 仍为 0），故 INFER 的解码闭包输出不变。

---

## 13. 通用 recursor iota（WP3 规格）

本节是 WP3 的规格，覆盖 `docs/KERNEL_COVERAGE.md` §2.B（B1–B13）。语义来源为
内核源码 `/home/xkq/lean4/src/kernel/`（下称 `K`）；元数据与 token 编码来自
`docs/ENV_FORMAT.md` §1.5–§1.7/§2.4/§2.6，level 编码来自 §12.1。现状是
`R/lean_vm/ref_vm.py` 只处理 `Nat.rec` 加三个 `casesOn` 特例（`R/lean_vm/ref_vm.py:164-241`、
硬编码表 `:83-93`），`R/lean_vm/build_vm.py` 另有硬编码 cid（`R/lean_vm/build_vm.py:68-136`）
与手写 `Nat.rec` rhs 发射链（`R/lean_vm/build_vm.py:1129-1188`）。WP3 用环境数据
（`recursor_val.rules`）替换全部硬编码分支。

本节只定义语义、数据流与验收，不写实现。

### 13.1 数据来源与不变量

**内核对 iota 唯一入口**是模板函数 `inductive_reduce_rec`（`K/inductive.h:77-121`），
由 `type_checker::reduce_recursor` 在 `whnf_core` 的 App 分支调用
（`K/type_checker.cpp:399-404`；调用点 `:526`；结果立即再 whnf `:533`）。该函数只读
`environment::find` 到的 `constant_info`：要求 `is_recursor()`（`K/inductive.h:82-83`），
再取 `recursor_val`。WP3 的所有判定输入都必须来自该结构，不得来自 cid 常量。

**WP1 token 承载的字段**（`docs/ENV_FORMAT.md:104-131`、`:216-233`；实现
`R/expr/tokens.py:349-469`，解码 `:798-888`）：

| 内核字段 | 访问器 | token | 字段位置 |
|---|---|---|---|
| kind = Recursor | `K/declaration.h:426` | `T_ENV_META`(K=23) | V1=7；X bit3(`ENV_F_IS_RECURSOR`) |
| nparams | `K/declaration.h:378` | `T_ENV_RECVAL`(K=28) | V1 |
| nindices | `K/declaration.h:379` | `T_ENV_RECVAL` | V2 |
| nmotives | `K/declaration.h:380` | `T_ENV_RECVAL` | X |
| nminors | `K/declaration.h:381` | `T_ENV_RECVAL` | E2 |
| is_k | `K/declaration.h:384` | `T_ENV_META` | X bit8(`ENV_F_IS_K`) |
| rule.ctor | `K/declaration.h:347` | `T_ENV_RULE`(K=29) | V1=ctor_cid |
| rule.nfields | `K/declaration.h:348` | `T_ENV_RULE` | V2 |
| rule.rhs | `K/declaration.h:349` | `T_ENV_RULE` | X=rhs 树根位置 |
| rules 链头 | — | `T_ENV_RECEXTRA`(K=38) | V2 |
| all 链头 | `K/declaration.h:377` | `T_ENV_RECEXTRA` | V1 |
| lparams 个数 | `K/declaration.h:70` | `T_ENV_META` | V0（=名字链长度） |
| lparams 名字链 | — | `T_ENV_UNIVPARAMS`(K=39) | V1；列表 role=2 |

**访问路径**：同一 cid 的元数据 token 经 `F2` 串成链表，头在
`anchor(cid)`（`T_ENV_META.V2`）处；`anchor(cid) = n+1+cid`，`n = T_NULL.V0`
（`R/expr/tokens.py:176-183`；`docs/ENV_FORMAT.md:262-286`）。这与图侧现有
`cid+1` 头块寻址（`R/lean_vm/build_vm.py:194-203` 用 `fV0 + One`）同属 O(1)
位置寻址，图只需再读位置 0 的 `T_NULL.V0` 得到 `n`。

**不变量**（不进判定，但编码必须维持，`R/tests/test_env_meta.py:261-279`）：

- `major_idx = nparams+nmotives+nminors+nindices`（`K/declaration.h:382`）。
- rule 链顺序 = 该递归器的 `InductiveVal.ctors` 声明顺序（`docs/ENV_FORMAT.md:253-259`）；
  运行期按构造子名匹配（`K/inductive.cpp:117-119`），顺序不影响选规则，但
  `rhs` 内的 minor 变量索引按扁平化顺序写死，顺序错了 rhs 会引用错 minor。
- `T_ENV_META.V0`（univ_arity）= lparams 名字链长度（`R/expr/tokens.py:884-887`）。

### 13.2 精确 iota 算法（B1–B9、B13）

按 `K/inductive.h:77-121` 的求值顺序逐步定义。`e` 是待归约的递归器应用，
`rec_fn = get_app_fn(e)`，`rec_args = get_app_args(e)`（应用序，major 在下标
`major_idx`）。

1. **入口校验（B1）**：`rec_fn` 必须是 constant（`:80-81`），环境里必须存在且
   `is_recursor()`（`:82-83`），否则返回 none（iota 不适用，whnf 保持原样）。
2. **major 定位（B3）**：`major_idx = nparams+nmotives+nminors+nindices`
   （`K/declaration.h:382`）；`major_idx >= rec_args.size()` → none（major 缺失，
   `K/inductive.h:87-88`）。`major = rec_args[major_idx]`（`:89`）。
3. **K 转换（B4）**：若 `rec_val.is_k()`，先 `major = to_cnstr_when_K(env, rec_val,
   major, whnf, infer_type, is_def_eq)`（`:90-91`）。`is_k` 的生成规则是「非互递归
   声明、结果层归一化为零（Prop）、唯一构造子且该构造子无字段」
   （`K/inductive.cpp:594-616`）；检查期只读该标志（`K/declaration.h:384`）。
4. **major whnf**：`major = whnf(major)`（`K/inductive.h:93`）。注意 whnf 发生在
   K 转换**之后**，故 K 型数据变量已被换成默认构造子应用。
5. **字面量/结构转换（B5/B6）**，三选一（`:94-99`）：
   - Nat 字面量：`major = nat_lit_to_constructor(major)`（`:94-95`）。
   - String 字面量：`major = whnf(string_lit_to_constructor(major))`（`:96-97`）。
   - 否则：`major = to_cnstr_when_structure(env, rec_val.get_major_induct(), major,
     whnf, infer_type, is_prop)`（`:98-99`）。
6. **按构造子名查规则（B2）**：`get_rec_rule_for(rec_val, major)` 取
   `get_app_fn(major)` 的头常量名，遍历 `rec_val.get_rules()`，名字相等即返回
   （`K/inductive.cpp:114-122`）。无匹配 → none（`:100-101`）。
7. **nfields 校验（B7）**：`major_args = get_app_args(major)`；若
   `rule.get_nfields() > major_args.size()` → none（`:102-104`）。
8. **universe 实例化（B13）**：若 `length(const_levels(rec_fn)) !=
   length(rec_info.get_lparams())` → none（`:105`）；否则 `rhs =
   instantiate_lparams(rule.get_rhs(), rec_info.get_lparams(),
   const_levels(rec_fn))`（`:106`）。见 §13.3。
9. **应用顺序（B8）**，严格按 `K/inductive.h:107-119`：
   - 先 apply **params+motives+minors**：`mk_app(rhs, nparams+nmotives+nminors,
     rec_args.data())`（`:107-108`）。取的是递归器应用的前 `nparams+nmotives+nminors`
     个实参（应用序），即第 0..nparams-1 参数、随后 motives、再随后 minors。
   - **indices 不应用于 rhs**：indices 位于 `rec_args[nparams+nmotives+nminors ..
     major_idx-1]`，但 `:108` 的计数不含 nindices。原因是规则 rhs 已预先特化到该
     构造子（含其索引），索引信息由构造子出现与字段承载；这正是
     `Eq.rec` 的 refl 规则 rhs 只引用 minor、不引用索引变量的原因（实测见 §13.3）。
   - 再 apply **字段**：`nparams_major = major_args.size() - rule.get_nfields()`
     （`:109-112`，注释说明嵌套归纳时构造子参数数与递归器参数数可不等）；
     `mk_app(rhs, rule.get_nfields(), major_args.data() + nparams_major)`
     （`:113-114`），即 major 应用的最后 `nfields` 个实参。
   - 最后 apply **extras**：若 `rec_args.size() > major_idx+1`，`nextra =
     rec_args.size()-major_idx-1`，`mk_app(rhs, nextra, rec_args.data()+major_idx+1)`
     （`:115-119`），即 major 之后的全部实参。
10. 返回 `some(rhs)`（`:120`）；`whnf_core` 对该结果继续 whnf（`K/type_checker.cpp:533`），
    故 iota 天然惰性、可递归。

**cheap_rec 开关**：`reduce_recursor` 在 `cheap_rec=true` 时用 `whnf_core` 而非
`whnf` 归约 major（`K/type_checker.cpp:400`）。当前 `is_def_eq_core` 走
`whnf_core(t, false, true)`（`K/type_checker.cpp:1194`），即 `cheap_rec=false`；
`whnf_core_cheap`（`K/type_checker.h:176`）在本内核源码内无调用点。因此证明检查
切片只需求 `cheap_rec=false`（major 全 whnf）；WP3 目标即此，`cheap_rec=true`
路径记为 TBD（13.7 第 8 条）。

**各子行为的内核依据**：

- B4 `to_cnstr_when_K`（`K/inductive.h:30-50`）：`app_type = whnf(infer_type(e))`
  （`:34`）；其头必须是常量且名等于 `rval.get_major_induct()`，否则原样返回
  （`:35-36`）；`app_type` 含 mvar 且 nparams 之后的任一实参含 mvar 时原样返回
  （`:37-44`，执行器/elaborator 保护，已 elaborated 输入不触发）；调用
  `mk_nullary_cnstr`（`:45`，实现 `K/inductive.cpp:88-97`）取**第一个**构造子
  （`get_first_cnstr`，`K/inductive.cpp:80-86`）并以类型的前 nparams 个实参应用
  （`args.shrink(num_params)` 保留前 num_params 个，`K/inductive.cpp:95-96`；
  `buffer::shrink` 语义见 `src/runtime/buffer.h:200-206`）；最后要求
  `is_def_eq(app_type, infer_type(new_cnstr_app))`，否则原样返回（`:47-48`）。
- B5 Nat 字面量（`K/inductive.cpp:1359-1366`）：`v==0` → `Nat.zero`；否则
  `Nat.succ (lit (v-1))`（只剥一层 succ，剩余字面量由外层 whnf 继续归约）。
- B5 String 字面量（`K/inductive.cpp:1368-1380`）：UTF-8 解码为码点序列，右折叠
  成 `List.cons (Char.ofNat c) ... List.nil`，再包 `String.ofList`（`g_string_mk`
  在 `K/inductive.cpp:1394` 初始化为 `String.ofList`）；内核随后对其 whnf。
- B6 `to_cnstr_when_structure`（`K/inductive.h:62-74`）：仅当
  `is_non_rec_structure(induct_name)` 且 e 不是构造子应用（`:65`；
  `is_non_rec_structure` = 单构造子、零 index、非递归，`K/inductive.cpp:28-33`；
  `is_constructor_app` `K/inductive.cpp:53-60`）；whnf `infer_type(e)` 且头常量名必须
  等于 `induct_name`（`:67-68`）；**Prop 保护**：`is_prop(e_type)` 为真则原样返回
  （`:70-72`）；否则 `expand_eta_struct`（`:73`，实现 `K/inductive.cpp:99-112`）：
  `C.mk p1..pn e.1 ... e.nfields`（构造子带类型前 nparams 参数 `:105-107`，逐字段
  `mk_proj` `:108-110`）。
- B2 `get_rec_rule_for`（`K/inductive.cpp:114-122`）：只看 major 头常量名，不做类型检查。
- B9 递归 rhs：规则 rhs 是内核在声明生成期预存的表达式，已包含对同一递归器的
  递归调用（例如 `Nat.rec` succ 规则 rhs 体内含 `Nat.rec`，实测 §13.3）。WP3 **不做
  任何递归重写**，只做 §13.2 步 8/9 的实例化与套用；`R/lean_vm/ref_vm.py:214-238`
  的手写 rhs 形状整体删除。

### 13.3 递归 rhs 与 universe 实例化（B9、B13）

**rhs 预存、无重写**。用真 Lean 4.33.1 dump 的 `Nat.rec` succ 规则 rhs（探针
2026-09-12，`reference/olean_export.dump_env`）为：

```
λ(motive: Nat→Sort u) λ(zero: motive 0) λ(succ: ∀n, motive n → motive (n+1)) λ(n: Nat).
  succ n (Nat.rec.{u} motive zero succ n)
```

即 rhs 恰有 `nparams+nmotives+nminors` 个外层 binder（0+1+2=3）再加 `nfields`
个字段 binder（1），体内显式含 `Nat.rec.{u}` 的递归出现。`Eq.rec` refl 规则 rhs
（探针同）为 `λ(α) λ(a) λ(motive) λ(refl : motive a (Eq.refl a)). refl`，恰有
`nparams+nmotives+nminors = 2+1+1 = 4` 个 binder、nfields=0、体内就是 minor 变量。
`MyIdx.rec`（带 index 的自定义归纳，探针）z/s 规则 rhs 均只引用对应 minor，
**不引用 index 变量**，印证 §13.2 步 9 的「indices 不 applied」。

**universe 实例化**：rhs 的常量 level 实参与 `Sort` level 里出现的 `LParam`（如
`Nat.rec.{u}` 的 `u`）在 `:106` 处被替换为递归器应用 `rec_fn` 携带的实际 level
实参，替换函数是 `instantiate_lparams`（`K/instantiate.cpp:232-246`，WP2 D13）。
`rec_info.get_lparams()` 为声明侧有序名字表（`K/declaration.h:70`），token 层是
`T_ENV_UNIVPARAMS` 的 role=2 列表（`docs/VM_SPEC.md:1280-1292`）；`const_levels(rec_fn)`
为使用侧 level 实参，token 层是 `K_CONST.V1` 起、用 `X` 串成的兄弟链
（`docs/VM_SPEC.md:1263-1278`）。实例化必须发生在参数套用**之前**，否则 rhs 里的
level 仍是 `LParam`。

**arity 不符 → stuck，不是错误**：`:105` 在个数不等时返回 none，`whnf_core` 于是
把整个 recursor spine 视为卡住（`K/type_checker.cpp:534-535` 返回 e）。这与
`instantiate_type/value_lparams` 的 `lean_internal_panic` 不同（`docs/VM_SPEC.md:1462`）：
iota 路径不会抛异常，只会「不归约」。WP3 的 RefVM/图必须返回 stuck（保持原 spine）；
现有粗粒度错误码（`R/lean_vm/ref_vm.py:47-50`）不新增 iota 专用码（见 13.7 第 7 条）。

**依赖**：B13 依赖 WP2a。toy 环境当前把 `Nat.rec` 编码为单态（univ_arity=0，
`docs/ENV_FORMAT.md:322-334`），实例化恒等；真实 `Nat.rec` 的 lparams=[u]（探针
与 `docs/ENV_FORMAT.md:325`）。因此 B13 的差分只能在把真实 lparams 与 `K_CONST`
level 兄弟链接入 token 流之后做（13.7 第 6 条）。

### 13.4 indices / nested / 互递归 / 多 motive-minor（B10–B12）

这些在数据驱动算法里都不是独立分支，而是由 `nindices/nmotives/nminors` 计数与
`rhs` 形状决定的。是否纳入 v1 切片按下表区分（探针值来自 2026-09-12 真
Lean 4.33.1 的 dump）：

| 编号 | 行为 | 内核做什么 | v1 决定 |
|---|---|---|---|
| B10 | indices（带索引归纳的 major） | `major_idx` 含 nindices（`K/declaration.h:382`），但 indices 不应用于 rhs（`K/inductive.h:108`）；规则 rhs 已特化到构造子与索引。`Eq.rec`：nparams=2/nindices=1/nmotives=1/nminors=1，refl 规则 nfields=0 | **在切片内**。算法无额外机制，`Eq.rec`/自定义 `MyIdx` 直接覆盖 |
| B11 | nested（`nnested>0`，`all`、辅助声明、多 motive） | 嵌套归纳的 recursor 有额外 motive/minor 与辅助类型；`MyTree.rec` 实测 nmotives=2/nminors=4（规则仍每条构造子一条，leaf/node）；字段参数计数用 `major_args.size()-nfields` 兜底（`K/inductive.h:109-112` 注释） | **算法按计数通用，但 v1 验收语料明确排除**（`docs/ENV_FORMAT.md:501-502` 第 6 条）。嵌套还需辅助嵌套类型及其 recursor/构造子全部进 token 环境，v1 未接；语料排除、VM 对嵌套 recursor 必须返回 stuck（不得给出错判） |
| B12 | 多 motive / 多 minor（互递归 recursor） | 互递归块生成多个 recursor，每个 `all` 含整块（`K/declaration.h:377`）、nmotives/nminors>1；`MA.rec`/`MB.rec` 实测 all=[MA,MB]、nmotives=2/nminors=2 | **在切片内**（算法按计数通用）。语料可用 `MA.rec`；注意 `all[0]` 不是每个 recursor 的 major 归纳（`MB.rec` 的 major 是 MB），不可用 `all[0]` 代替 `major_induct`（13.7 第 5 条） |

结论：v1 **在**：B10、B12（纯计数，无额外机制）以及 B1–B9、B13。v1 **明确排除**：
B11 嵌套归纳的验收语料（实现可留计数通用，但不得对嵌套给出错误判定——必须
stuck）。String 字面量 major（B5 后半）依赖 WP5，见 13.5/13.7。

### 13.5 图侧与参照机如何读取 WP1 token

目标：删除 `R/lean_vm/build_vm.py:68-136` 的 cid 与 `R/lean_vm/ref_vm.py:83-93`
的 rule 表，改为运行期读 `anchor(cid)` 链。字段对照（名字取
`docs/ENV_FORMAT.md:222-233` 与 `R/expr/tokens.py:349-469`）：

| 需要的信息 | 读取位置 | 说明 |
|---|---|---|
| 是否 recursor | `anchor(cid).V1 == 7` 或 `anchor(cid).X & ENV_F_IS_RECURSOR` | `docs/ENV_FORMAT.md:205-214`；对照内核 `is_recursor()`（`K/inductive.h:83`） |
| nparams/nindices/nmotives/nminors | `T_ENV_RECVAL`(K=28) 的 V1/V2/X/E2 | `R/expr/tokens.py:407-415` 发射，`:860-865` 解码 |
| major_idx | `nparams+nindices+nmotives+nminors`，运行期加法 | 与 `K/declaration.h:382` 一致；不再用 `pend[-4]`（现 `R/lean_vm/ref_vm.py:190`） |
| is_k | `anchor(cid).X & ENV_F_IS_K` | `docs/ENV_FORMAT.md:211` |
| rules 头 | `T_ENV_RECEXTRA`(K=38).V2 | `R/expr/tokens.py:871-873` |
| rule ctor 匹配 | `T_ENV_RULE`(K=29).V1 == major 头 cid | 对应 `K/inductive.cpp:117-119` |
| rule nfields | `T_ENV_RULE.V2` | `docs/ENV_FORMAT.md:229` |
| rhs 树根 | `T_ENV_RULE.X` | rhs 已按表达式编码追加（`R/expr/tokens.py:277-286`）；解码 `decode_expr` |
| 构造子元数据 | `T_ENV_CTORVAL`(K=27)：V1=induct_cid、V2=cidx、X=nparams、E2=nfields | 用于 major 头 nfields、K 默认构造子取「第一个」 |
| 归纳元数据 | `T_ENV_INDVAL`(K=26)：V1=nparams、V2=nindices、X=nnested；构造子数=INDEXTRA(37).V2 链长；isRec=flags bit6 | 用于 `is_non_rec_structure`（`K/inductive.cpp:32`）与 `to_cnstr_when_structure` |
| lparams | `T_ENV_META.V0` + `T_ENV_UNIVPARAMS`(39).V1 role=2 链 | B13；`docs/VM_SPEC.md:1280-1292` |
| recursor 应用 level 实参 | `K_CONST.V1` + X 兄弟链 | `docs/VM_SPEC.md:1263-1278` |
| major_induct | 由 `T_ENV.V1`（递归器类型树）沿 major_idx 个 Pi binder 下行取 domain app 头 | 对应 `K/declaration.cpp:145-154`；或对良型输入用 major 的推断类型头（13.7 第 5 条） |

**major 定位**：spine 的应用序实参数 = pend 逆序；`major = args[major_idx]`
（`K/inductive.h:89`）。图侧现有工作区已有按 NAT 帧读 spine 的机制
（`R/lean_vm/build_vm.py:363-406`），WP3 把它从「固定 spine 长度 + 固定 op」
改为「由 `T_ENV_RECVAL` 计数 + `major_idx` 定位」；major 的 whnf 已完成后的
**转换后** major 才是字段来源（`K/inductive.h:93-99`），因此 RHS 套用必须读取
转换/eta 后的 major args，而非原始 major。

**rhs 发射**：内核语义是 `mk_app(instantiate_lparams(rhs), params,motives,minors,
fields, extras)`（§13.2 步 9）。图侧可复用现有「link 链携带闭包 + 重发 rhs」的
做法（`R/lean_vm/build_vm.py:1129-1188`），但 rhs 树必须来自 `T_ENV_RULE.X` 而非
手写 token 形状；具体发射机制（直接以 rhs 树为焦点让机器 beta 归约，还是展开成
App spine）属实现选择，见 13.7 第 9 条。ref_vm 侧对应改动是把
`R/lean_vm/ref_vm.py:186-241` 的 `Nat.rec` 特例与 `:164-183` 的 casesOn 特例合并为
一个读元数据的通用分支，`_match_ctor`（`:541-571`）泛化为「构造子 cid + nfields
来自 `T_ENV_CTORVAL`」。

**casesOn 的特别说明**：真内核里 `Nat.casesOn`/`Bool.casesOn`/`P2.casesOn` 是
`defnInfo`（abbreviation），**不是** Recursor（`docs/ENV_FORMAT.md:338-350`，探针
确认；`R/tests/test_env_meta.py:281-294`）。所以它们不会命中 recursor iota；要由
delta 展开其 Definition value 后再归约（value 内含对应 recursor 应用）。迁移路线
见 13.7 第 2 条。

### 13.6 验收 / oracle 设计

**原则**：所有期望判定来自真 Lean 二进制（`~/.elan/bin/lean`，v4.33.1），不得手写。
oracle 入口见 `R/reference/lean_ref.py`：`run_oracle`（WHNF，`:90`）、
`run_oracle_mixed`（WHNF/DEFEQ/INFER，`:97`）、`run_check_oracle`（`example : T := v`
接受/拒绝，`:142`）、`run_level_oracle`/`run_kdecl_oracle`（`:337`/`:369`）。
真环境元数据（含 recursor rules）由 `R/reference/olean_export.dump_env`（`:198`）
读真 `Environment.find?`/`ConstantInfo` 得到；`docs/ENV_FORMAT.md:449-478` 已用此
管道实测 `Nat.rec`/`Bool.rec` 等。

**语料来源**（在 oracle 的 `defs` 里声明真实归纳类型，或引用 prelude 的
`Nat`/`Bool`/`Eq`/`List`/`String`；每个用例的 lhs/rhs 用真 Lean 项，含由
`match`/`induction`/`cases` 编译出的 recursor 应用）：

- **C1 递归 rhs（B1/B2/B3/B8/B9）**：自定义递归归纳（如
  `inductive WTree | leaf | node : WTree → WTree → WTree`）+ 结构递归函数
  （`def wsum (t : WTree) : Nat := match t with | .leaf => 0 | .node l r => wsum l + wsum r + 1`）。
  DEFEQ：`wsum (node leaf leaf) =?= 1`；WHNF：`wsum (node leaf leaf)`。
- **C2 非零 nparams（B3）**：`List.rec`/自定义 `inductive Box (α) | mk : α → Box α`。
  DEFEQ 验证 `major_idx = nparams+...`。
- **C3 K 型（B4）**：`Eq.rec`（探针 isK=true）：
  `Eq.rec (motive := fun _ _ => Nat) 7 h =?= 7`（`h : 0 = 0`）；
  负例：两构造子类型的卡住变量 major（如 `Bool`/自定义 `WB` 的 fvar）DEFEQ 到任一
  branch 为 false（major stuck → 整 spine stuck，`K/inductive.h:101`）。注意
  `Subsingleton.rec` 探针 isK=false，它由 proof-irrel（§11.9 之外的另一支）处理，
  不作为 K 语料。
- **C4 Nat 字面量 major（B5）**：`Nat.rec`/`Nat.casesOn` 作用于字面量（已有
  `deq_rec_*`/`deq_caseson_*` 语料，`R/reference/toy_env.py`）。
- **C5 String 字面量 major（B5）**：`String.rec`/`String.casesOn` 作用于 `"abc"`；
  探针 `String.rec` 规则是 `String.ofByteArray` nfields=2，故实际路径是
  `string_lit_to_constructor` → whnf `String.ofList` → delta 到构造子。**WP5 依赖**，
  v1 先只断言接口/门存在，差分语料随 WP5（13.7 第 3 条）。
- **C6 结构 eta（B6）**：0 参非递归结构 `WS`（2 字段），卡住变量 `s : WS` 下
  `WS.rec … s =?= (minor s.a s.b)`（DEFEQ 在 `fun s => …` 体内比较，触发
  `to_cnstr_when_structure`）；Prop 结构负例验证 `is_prop` 保护不 eta（`K/inductive.h:70-72`）。
- **C7 nfields 校验（B7）**：变异测试：篡改 `T_ENV_RULE.V2` 使 `nfields` 与真值不符，
  断言解码值与真 dump 不符、且 VM 走 stuck（仿 `R/tests/test_env_meta.py:322-348`
  与 `R/tests/test_mutation_reject.py`）。
- **C8 indices（B10）**：自定义带索引归纳
  `inductive MyIdx : Nat → Type | z : MyIdx 0 | s : MyIdx 1` 的 `MyIdx.rec`，
  以及 `Eq.rec`；DEFEQ 命中/不命中两例。
- **C9 嵌套（B11）**：`MyTree`（`leaf : Nat → MyTree`、`node : List MyTree → MyTree`，
  探针 nnested=1/nmotives=2/nminors=4）。v1 **不在差分语料**：用显式排除集
  （仿 `R/tests/test_ref_infer_defeq.py:56` 的 `LEAN_NO_MIRROR`）；另加单元断言
  VM 对嵌套 recursor 返回 stuck，不返回错误 verdict。
- **C10 互递归（B12）**：`mutual inductive MA | a : MB → MA` / `MB | b : MA → MB`；
  `MA.rec` 的 2 motive/2 minor DEFEQ。验证不能靠 `all[0]` 取 major_induct。
- **C11 universe 实例化（B13）**：多态递归器（真 `Nat.rec`/`List.rec`）在不同 level
  实参下归约 DEFEQ；arity 不符时断言 VM 与内核同为 stuck（不抛）。
- **C12 端到端声明**：`run_kdecl_oracle` 加 `defnDecl`，其 value 的类型检查必须依赖
  某条 iota 规则（例如 `def t : Nat := Nat.rec (motive := fun _ => Nat) 0
  (fun _ _ => 1) 3`），断言类别 `OK`；把规则 rhs 指向不可归约项则内核报
  `.declTypeMismatch`/`.other`，VM 同判拒绝。此为最强 oracle：期望类别来自真 C++ 内核
  `Environment.addDecl`（`R/reference/lean_ref.py:315-323`）。

**每个测试断言什么**：

1. DEFEQ/WHNF/INFER（`run_oracle_mixed`）：RefVM 与图侧结果与 oracle 逐例相等；
   WHNF/INFER 比较 decode 后的表达式（binder 名与 MData 按现有习惯剥离，见
   `R/tests/test_olean_export.py:100-112`）。
2. CHECK（`run_check_oracle`）：`example : T := v` 的接受/拒绝布尔与 VM `check`
   一致（错误类别粒度见 13.7 第 7 条）。
3. KDECL（`run_kdecl_oracle`）：返回 "OK" 或 `Lean.Kernel.Exception` 构造子名；
   VM 判定的粗粒度类别与之一致。
4. 负例/变异：篡改元数据 token 后 VM 行为与真 dump 期望分离，且不产生假接受。

**要新增的测试文件**（本节只命名，不创建）：

- `R/tests/test_iota_vs_lean.py`：RefVM 与 step graph 对真 lean 的差分。调用
  `run_oracle_mixed`（C1–C6、C8、C10、C11）、`run_check_oracle`/`run_kdecl_oracle`
  （C12）；C9 用排除集跳过。语料与真元数据用 `dump_env` + `test_env_meta._conv`
  风格从真二进制构造（`R/tests/test_env_meta.py:48-81`）。
- `R/tests/test_iota_graph_vs_refvm.py`：图 vs RefVM 同语料，0 pinned（仿
  `R/tests/test_stepgraph_infer_defeq.py`、`R/tests/test_stepgraph_vs_refvm.py`）。

**回归不破**（KERNEL_COVERAGE 的 Reg 栏）：`tests/test_ref_vs_lean.py`、
`tests/test_ref_infer_defeq.py`、`tests/test_stepgraph_vs_lean.py`、
`tests/test_stepgraph_infer_defeq.py`、`tests/test_stepgraph_vs_refvm.py`、
`tests/test_check_e2e.py`、`tests/test_mutation_reject.py`、
`tests/test_olean_export.py`、`tests/test_env_meta.py`、`tests/test_level_vs_lean.py`。

### 13.7 WP3 TBD

1. **olexport 到 token 的通路未接**：`R/reference/olean_export.py:566` 的
   `import_env` 只接受 kind ∈ {def, ctor, ind}，拒绝 Recursor；返回三元组
   `(consts, ctors, structs)`（`:644`）不带 `const_meta`。现有 `Encoder` 已支持
   `const_meta`（`R/expr/tokens.py:226-288`），`test_env_meta` 手工用 `_conv`
   （`R/tests/test_env_meta.py:48-81`）从真 dump 构造。WP3 落地必须先扩展
   `import_env` 接受 rec（及 ind 的 `ctors`/`all`/`nindices`/`isRec`）并回传
   `const_meta`，否则数据驱动路径无真实元数据可读。
2. **casesOn 的路线**：真 kind 是 Definition（`docs/ENV_FORMAT.md:338-350`）。
   选项 (a) 图/ref 对 abbreviation 做 delta 展开（value 里就是 recursor 应用），
   (b) toy 保留显式 dispatch 但改为按名/cid 查表。建议 (a) 以与真环境一致；若
   性能/复杂度不可行则 (b)，但需保证 verdict 与真内核一致。二选一未定。
3. **String 字面量 major（B5）**：依赖 WP5（`LitStr` 编码现抛
   `R/expr/tokens.py:271-272`）、`string_lit_to_constructor` 与
   `String`/`List`/`Char`/`ByteArray` 的 delta。建议 WP3 只留门与调用点，
   v1 差分语料等到 WP5 落地，先记 gap。
4. **嵌套（B11）的接受范围**：`docs/ENV_FORMAT.md:501-502` 已判 nnested>0 不在
   v1。建议维持，并要求 VM 对 nested recursor 返回 stuck（可观测的 gap），不进入
   差分语料；待辅助嵌套类型编码后单开语料。
5. **major_induct 的取法**：内核从递归器类型沿 major_idx 个 binder 取 domain app 头
   （`K/declaration.cpp:145-154`）。token 的 `all` 头（`T_ENV_RECEXTRA.V1`）对互递归
   递归器不是其 major（探针：`MB.rec` 的 all=[MA,MB]）。建议图侧对良型输入直接用
   major 的 whnf 推断类型头作 K/structure 门，或严格沿 `T_ENV.V1` 走类型树；
   二者取一并在互递归语料上验证。
6. **lparams/level 接线（B13）**：需 WP2a 的 `K_CONST` level 兄弟链与
   `T_ENV_UNIVPARAMS` 真正写入（当前 toy `univ_arity=0`，见
   `docs/ENV_FORMAT.md:322-334`；`R/expr/tokens.py:290-305` 已支持）。未接前
   B13 的差分只覆盖单态恒等情形。
7. **错误类别粒度**：iota 本身不抛异常（缺失 major/无规则/nfields 不足/level arity
   不符都返回 none，`K/inductive.h:88,101,104,105`），故 WP3 无 iota 专用错误码；
   拒绝来自后续 defeq/check。KDECL/CHECK oracle 返回的内核类别到
   `R/lean_vm/ref_vm.py:47-50` 四个粗码的映射仍是全局 TBD
   （`docs/KERNEL_COVERAGE.md:338-345`）。建议先只比 "OK vs 非 OK"，类别粒度随全局决定。
8. **cheap_rec=true 路径**：内核 `whnf_core_cheap`（`K/type_checker.h:176-178`）当前在
   内核源码内无调用点；证明检查路径 `is_def_eq_core` 用 cheap_rec=false
   （`K/type_checker.cpp:1194`）。建议 WP3 只实现 cheap_rec=false，另一档记 TBD。
9. **图侧 rhs 发射机制**：把 `T_ENV_RULE.X` 的 rhs 树与 params/motives/minors/fields/
   extras 套用的通用发射，具体是用 link 链承载参数后以 rhs 树为焦点，还是展开为
   App spine，属实现选择；须保证与内核 `mk_app` 的 beta 语义一致。现有
   `R/lean_vm/build_vm.py:1129-1188` 的固定偏移发射表将整体替换。
10. **major stuck / K 转换失败时的一致性**：`to_cnstr_when_K` 在类型头不符或有 mvar
   时原样返回（`K/inductive.h:36,42-43`），`is_def_eq` 不符时也原样返回（`:48`）；
   这些失败分支最终导致 major 头不是构造子 → 无规则 → stuck。图上必须同样落到
   §10.2 的 spine stuck 交付，不得误发 build。

### 13.8 quot 归约（WP4，C 组）

**内核入口与调用顺序（C5）**：`whnf_core` 的 App 分支统一走
`type_checker::reduce_recursor`（`K/type_checker.cpp:393-407`）。它**先**尝试
`quot_reduce_rec`（`:393`），仅当环境 `is_quot_initialized()`（`:394`，见下）且
头是 quotInfo 常量时归约；否则继续走 `inductive_reduce_rec`（`:399-404`）。因此
`Quot.lift` / `Quot.ind` 作为 quotInfo 常量（`K/quot.cpp:90,100`，非递归子）只可能
被 quot 分支归约，iota 分支对它们返回 none。图上两个分支互斥：头的 WP1 元数据
kind 为 `CK_QUOT` 时只有 `fire_quot` 命中，为 `CK_RECURSOR` 时只有 `fire_iota`
命中（`R/lean_vm/build_vm.py:4194-4219`），与内核“先 quot 后 inductive”对这两类
常量的净效果一致。

**`is_quot_initialized` 代理（C3）**：内核在 `add_quot`（`K/quot.cpp:47-104`，
mark 于 `:102`）首次注入四个 Quot 常量时把环境位 `quot_initialized_` 置真
（`K/environment.cpp:66`）。token 环境无此位，故图以“环境中至少存在一个
`CK_QUOT` 元数据常量”为等价判据（`_QUOT_INIT`，
`R/lean_vm/build_vm.py:435-443`），复用 §13.5 的 `anchor(cid).V2` 元数据链读取，
不使用任何写死 cid。

**`quot_reduce_rec`（C1，`K/quot.h:39-70`）**：按头常量的 `quot_kind` 取
`mk_pos`/`arg_pos`（`quot.h:45-50`）：`Quot.lift` → mk_pos=5/arg_pos=3，
`Quot.ind` → mk_pos=4/arg_pos=3；两者 arg_pos 均为 3。步骤：
1. `e` 的实参数须 `> mk_pos`（`quot.h:55-57`，图上 `fire_quot` 的 pend 非空校验）。
2. `mk = whnf(args[mk_pos])`（`:58`）；图上以 `NAT(OP_QUOT, X=1)` 帧对该实参做
   惰性 whnf，完成态即 `quot_dn`（`build_vm.py:1057-1058`）。
3. `mk` 的头必须是 `Quot.mk` 常量且 `get_app_num_args(mk)==3`（`quot.h:59-61`）；
   否则返回 none → 不归约。图上 `q_is_mk`（头 `CK_QUOT` 且 `quot_kind==1`）+
   `q_arity==3`（`build_vm.py:1069-1072`）实现此判据。arity 门（2 参数的
   `@Quot.mk Nat R`）在内核对良型商不可达（良型 `Quot.mk` 恒 3 参），故以图侧
   ill-typed 直驱单独验证：whnf 原样返回 spine（测试 §C）。
4. 归约结果 = `mk_app(args[arg_pos], app_arg(mk))` 再接 `args[mk_pos+1..]`
   （`quot.h:64-68`）。图上 `quot_go`（`build_vm.py:1085,1090-1096`）聚焦
   `f=args[3]`、以 `a=app_arg(mk)` 为 PEND、extras=`args[mk_pos+1..]` 续上，交由
   机器的 beta 归约完成，语义等价。

**`quot_is_stuck`（C2，`K/quot.h:76-95`）**：与 C1 同位置判据；major whnf 后头非
`Quot.mk`、或参数数≠3、或 `e` 实参不足 → 该应用 stuck。图上以 `quot_stuck_r` /
`quot_sd` 交付原始 spine 根（`build_vm.py:1097-1103`），与 iota 的 spine stuck 交付
同型（§10.2），对应内核 whnf 原样返回 `e`。

**`quot_val` / `quot_kind` 元数据（C4，`K/declaration.h:388-412`）**：
`quot_kind ∈ {type=0, mk=1, lift=2, ind=3}` 经 WP1 编码在
`T_ENV_QUOTVAL.V1`（`R/expr/tokens.py:446-449`，解码 `:1028-1029`）；`olean_export`
由内核 `quotInfo` 读出（`R/reference/olean_export.py:118-119,685-686`）。差分测试
的 §A 逐常量核对解码值与 `dump_env` 真值一致（四个常量 kind=4、quot_kind 分别
0/1/2/3）。

**验收**：`R/tests/test_quot_graph_vs_lean.py`（oracle 4.33.1）三段——§A 元数据
（C3/C4）、§B 归约+stuck 语料对真值（C1/C2/C5：`Quot.lift` 恒等与 succ、
`Quot.ind`→`True.intro`、经 `Quotient.mk` 的 delta 展开、axiom major 的 stuck 与
“只归到正确值”的 DEFEQ 正反）、§C arity 门（C1）。图侧以 §13.8 的一次性
warm-prefix 记忆化避免每例重扫整段环境前缀（`IncrementalGraphEvaluator` 因果
求值为 O(N²·L)，与 §13.6 同源于 WP3/WP8 的名字链扫描，非 WP4 新增）。

---

## 14. 字符串字面量（WP5 规格）

本节是 WP5 的规格，覆盖 `docs/KERNEL_COVERAGE.md` §2.E 的 E1–E5（清单
`:114-122`；工作包 `:238-243`）。语义来源为内核源码 `/home/xkq/lean4/src/kernel/`
（下称 `K`），数据模型对应 `R/expr/model.py:172-178`。现状是字符串字面量是唯一
完全无法编码的表达式构造：`R/expr/tokens.py:598-599` 编码抛
`NotImplementedError("LIT_STR not supported in v1")`，解码 `:688` 同样拒绝。
现状注记（2026-09-13）：本节原为规格；E1–E5 已按 14.7 落地，上述编码/解码
拒绝已被字节链 + 影子展开实现取代。
本节定义语义、编码与验收；实现决议（含 14.6 各条的处置）见 14.7。

需要先区分三件事，WP5 其余内容都围绕它们：

1. **字面量数据**：内核 `Literal` 的 String 负载是 UTF-8 字节串（`K/expr.h:44-64`，
   构造 `K/expr.cpp:26-28`）。
2. **字面量的 token 表示**：把该字节串编进 expr 树（14.1）。
3. **展开为构造子**：`string_lit_to_constructor` 在把字面量当 major/被投影项/defeq
   一侧时才把字节串解码成码点并构造成 `String.ofList (...)`（14.2 E2）。裸字面量
   的 WHNF 不展开——`whnf_core` 对 `Lit` 直接原样返回（`K/type_checker.cpp:474-477`）。

### 14.1 数据模型与 token 编码（E1）

**内核模型**：`enum class literal_kind { Nat, String }`（`K/expr.h:43`）；`literal`
类的 String 负载经 `get_string()` 取回 `string_ref`（`K/expr.h:59`），其底层是 UTF-8
字节串（`literal(char const * v)` 用 `mk_string` 构造，`K/expr.cpp:26-28`）。
`is_string_lit(e)`（`K/expr.h:235`）即 `is_lit(e) && kind()==String`。
`R/expr/model.py:86-87` 的 `LIT_NAT=0`/`LIT_STR=1` 与内核枚举序一致，
`LitStr(value: str)` 在 `:176-178`。

**token 形状**：字符串字面量是一个 `K_LIT`（`K_LIT=10`，`R/expr/model.py:57`；
VM_SPEC §4 `docs/VM_SPEC.md:109`）头，后面跟一条**字节链**。链头字段与 Nat 数字链
（§5，`docs/VM_SPEC.md:126-145`）相同：`V0=链长 n`、`V1=literal_kind`、`V2=父指针`。
链体是步幅 2 的显式 gap token + 一个字节 token：

| 位置 | K | V0 | V1 | V2 | 含义 |
|---|---|---|---|---|---|
| H | K_LIT(10) | n | LIT_STR(1) | 父指针 | 链头；n = UTF-8 字节数 |
| H+1+2i | 0 (NULL gap) | 0 | 0 | 0 | 步幅占位（同 §5） |
| H+2+2i | T_LIT_BYTE(40) | b_i (0..255) | 0 | H | 第 i 个 UTF-8 字节 |

`b_0 … b_{n-1}` 是 `s.encode("utf-8")` 的字节，顺序不变；
`n = len(bytes)`。空串合法：`n=0`、无链体 token（与 Nat 不同，Nat 的零是 1 位 `[0]`，
`R/expr/tokens.py:139-148`）。

**为什么新增内层 kind 而不复用 `T_LIT_DIG`**：`T_LIT_DIG`（K=13，`R/expr/tokens.py:28`）
的契约是十进制数码 `V0∈0..9`，Nat 算术微步按该契约读取（VM_SPEC §5/§7.2，
`docs/VM_SPEC.md:126-145,204-213`）。字符串链的负载是 `0..255` 的字节、且解码是
UTF-8 而不是位置十进制，语义不同；用独立 kind 可避免 ALM 解码器按链头 V1 上下文
分派，保持每种 token kind 单一含义。链的布局（K_LIT 头、步幅 2、V2=H）完全复用
Nat 的做法。

**新 kind 编号**：取 **K=40，名 `T_LIT_BYTE`**。依据 `docs/ENV_FORMAT.md` §2.2
（`:168` 空闲段 `14–20、24–29、35–200、205–255`；`:174-186` 分配规则
"新增 kind 一律取 24–29、然后 35–38 中最小的未占用值"）：24–29 已用满，35–38
已用满，39 已被 §12.1 的 `T_ENV_UNIVPARAMS` 占用（`R/expr/tokens.py:64`，
`docs/ENV_FORMAT.md:186`），故 35–200 段内最小可用值是 40。`T_LIT_DIG`/`T_NAME`
等既有编号不重排（`docs/ENV_FORMAT.md:171`）。该编号需同步回写
`docs/ENV_FORMAT.md` §2.2（本文不改该文件）；备选 14–20 见 14.6 第 1 条。

**解码（round-trip）**：`decode_expr` 的 `K_LIT` 分支（`R/expr/tokens.py:680-688`）
在 `V1==LIT_NAT` 时按十进制求和；WP5 增加 `V1==LIT_STR` 分支：读 `n=V0` 个字节
`b.stream[pos+2+2i].V0`（i=0..n-1），拼接后 `bytes(...).decode("utf-8")` 得
`LitStr`。`decode_closure` 对字面量无 env 依赖，直接转 `decode_expr`
（`R/expr/tokens.py:734-735`），无需改动。对良构输入 round-trip 无损：
`encode(LitStr(s)) → decode == LitStr(s)`。

**字段/序列上限**（VM_SPEC §2，`docs/VM_SPEC.md:50-66`）：

- 每个字节 `b_i ≤ 255 ≤ 4095`，单字段安全；`n = V0` 必须 `≤ 4095`。
- 该字面量占 `1 + 2n` 个 token；整个流的长度硬上限 4096，故 `n` 到约 2047 时
  单个字面量已接近上限（其余内容另计）。
- 越界行为：`n > 4095` 时 `V0` 装不下，编码层无法表示；`1+2n` 使流超 4096 时
  与 §9.4 的越界一致，运行期 `K_REJECT, V0=3`（ERR_OVERFLOW，
  `docs/VM_SPEC.md:343-344`，`R/lean_vm/ref_vm.py:47-50`）。内核本身对字符串
  长度无类似 `LEAN_NAT_MAX_SIZE` 的限制（`string_lit_to_constructor` 只受内存约束，
  `K/inductive.cpp:1368-1380`；`check_nat_size` 只作用于 Nat，`K/type_checker.cpp:318-319`），
  故此限制是 v1 编码缺口，记 14.6 第 4 条。

### 14.2 E1–E5 精确语义

#### E1 `LitStr` 编码/解码

内核数据模型如上（`K/expr.h:43-64,234-236`；`K/expr.cpp:26-28`）。仓库现状：
`R/expr/model.py:172-178` 有 `LitStr`、`:213-214` 有 `lit_kind_of`，但
`R/expr/tokens.py:598-599`（编码）与 `:688`（解码）都拒绝。WP5 按 14.1 补齐，
不改 `K_LIT` 的 `V1` 含义（`V1` 仍是 literal_kind，`docs/VM_SPEC.md:109`）。

#### E2 `string_lit_to_constructor`（展开为构造子）

`K/inductive.cpp:1368-1380`，逐句语义：

1. `lean_assert(is_string_lit(e))`（`:1369`；谓词 `K/expr.h:235`）。
2. `s = lit_value(e).get_string()` 取 UTF-8 字节串（`:1370`；`K/expr.h:59`）。
3. `utf8_decode(s.to_std_string(), cs)` 解码为 `std::vector<unsigned> cs` 码点序列
   （`:1372`；算法 `K/runtime/utf8.cpp:216-221`）。
4. 以 `r = *g_list_nil_char` 起（`:1373`），从末位往前右折叠：
   `r = List.cons Char (Char.ofNat (lit c_i)) r`（`:1375-1378`）。
5. 返回 `mk_app(*g_string_mk, r)`（`:1379`）。

展开中四个常量的确切身份由 `initialize_inductive` 初始化（`:1383-1405`）：

| 全局 | 常量 | 说明 |
|---|---|---|
| `g_string_mk` | `String.ofList` | `K/inductive.cpp:1394`；无 level，直接 `mk_constant({"String","ofList"})` |
| `g_list_cons_char` | `List.cons.{0} Char` | `:1397`：`mk_app(mk_constant({"List","cons"},{level()}), Char)`，即 level 实参 `zero` |
| `g_list_nil_char` | `List.nil.{0} Char` | `:1399`，同上带 `Char` |
| `g_char_of_nat` | `Char.ofNat` | `:1401`；参数是 Nat 字面量 `mk_lit(literal(cs[i]))`（`:1377`） |

注意 `Char.ofNat` 与 `String.ofList` 都是 **Definition**，不是构造子；`Char` 的唯一
构造子是 `Char.mk`，`String` 的唯一构造子是 `String.ofByteArray`（源码
`src/Init/Prelude.lean:2876-2892`（`Char.ofNat` 定义）、`:3540-3546`（`String`
结构 `ofByteArray` 构造子）、`:3559-3561`（`String.ofList` 定义）；真 lean 4.33.1
探针：`String.ofList` kind=def hints=Regular height=14 safety=safe，`Char.ofNat`
def Regular height=7，`String.ofByteArray` ctor induct=String cidx=0 nfields=2，
`List` np=1 ctors=[List.nil,List.cons]）。因此 `string_lit_to_constructor` 只产生
`String.ofList (List.cons (Char.ofNat c) …)`；调用方随后对其 `whnf`（`K` 的
`String.ofList` 是 `implicit_reducible`，`src/Init/Prelude.lean:3559`），
delta 展开成 `String.ofByteArray (List.utf8Encode data) proof`，在构造子
`String.ofByteArray` 处停下。真 lean 4.33.1 探针：`#ORACLE String.ofList ['a','b','c']`
的 WHNF 正是 `String.ofByteArray (List.utf8Encode (List.cons (Char.ofNat 97) …)) …`。

**通过 WP1 元数据定位常量（不写死 cid）**：

- `List.cons`/`List.nil` 是构造子。用 `T_ENV_CTORVAL`(K=27，
  `docs/ENV_FORMAT.md:227`；解码 `R/expr/tokens.py:855-859`) 的 `V1=induct_cid`、
  `V2=cidx` 定位：先找到 `List` 的 cid（kind=Inductive 且 `T_ENV_INDEXTRA.V2`
  的 ctors 链含这两个名字），再由 `cidx=0`（nil）/`1`（cons）取（List 声明序
  `src/Init/Prelude.lean:2981-2990`：nil 先、cons 后；探针 ctors=[List.nil,List.cons]）。
  类 recursor 一样，勿再写 `CID_*` 数字。
- `String.ofList`/`Char.ofNat` 是 Definition（kind=1）。用 `T_ENV_META.V1`
  （constant_info_kind，`K/declaration.h:426`；`docs/ENV_FORMAT.md:205-214`）
  筛出 Definition，并在 NAME 表（`T_NAME`，`R/expr/tokens.py:155-158,186-192`）
  按名字取 cid（`bundle.cids[name]`）；`String.ofByteArray` 是
  `String` 的 cidx=0 构造子，同理由 `T_ENV_CTORVAL` 取（归纳元数据 `T_ENV_INDVAL`/
  `T_ENV_INDEXTRA`，`docs/ENV_FORMAT.md:227-233`）。

#### E3 `try_string_lit_expansion`

`K/type_checker.cpp:1145-1156`，精确匹配条件：

```
核心 t,s： is_string_lit(t) && is_app(s) && app_fn(s) == *g_string_mk
          → is_def_eq_core(whnf(string_lit_to_constructor(t)), s)
入口：    先 core(t,s)，返回 l_undef 再 core(s,t)（对称）
```

- 匹配只要求 **t 是字符串字面量**、**s 是应用且其头恰为常量 `String.ofList`**
  （`app_fn` 取 app spine 头；`*g_string_mk` 是 `mk_constant({"String","ofList"})`，
  无 level 实参，`K/type_checker.cpp:1342`）。**不检查 s 的参数结构**，参数是否
  与展开相等交给 `is_def_eq_core`。
- 命中后比较 `whnf(string_lit_to_constructor(t))` 与 `s`（`:1147`）。
- 包装函数对调两参再试一次，故字面量在左或在右都覆盖（`:1152-1156`）。
- 调用点在 `is_def_eq_core` 卡住链：`try_eta_struct`（`:1236-1237`）之后、
  `is_def_eq_unit_like`（`:1242-1243`）之前（`:1239-1240`）。此处的 `t_n`/`s_n`
  来自 `whnf_core(t,false,true)`（`:1194-1195`）——**无 delta**，所以 s 仍可能以
  `String.ofList` 为头（未展开），这正是该规则存在的前提。

真 lean 4.33.1 探针锚定：`"abc" =?= String.ofList ['a','b','c']` 为 true，
`"abc" =?= String.ofList ['a','b','d']` 为 false，`"∀" =?= String.ofList [Char.ofNat 8704]`
为 true，`"😀" =?= String.ofList [Char.ofNat 128512]` 为 true，
`"" =?= String.ofList ([] : List Char)` 为 true。

#### E4 `infer_lit` 的 String 分支

`K/type_checker.cpp:315-321`：`infer_lit` 只对 Nat 字面量做尺寸检查
（`is_nat_lit(e)` 时 `check_nat_size`，`:318-319`），随后对所有字面量返回
`lit_type(lit_value(e))`（`:320`）。`lit_type`（`K/expr.cpp:78-79` 转发
`lean_lit_type`）在 Lean 侧定义（`src/Lean/Expr.lean:621-627`）：

```
| .natVal _ => mkConst `Nat
| .strVal _ => mkConst `String
```

故 String 分支语义 = **返回 `Const(String)`，无 level 实参，无尺寸检查**。
分派点 `case expr_kind::Lit: r = infer_lit(e)`（`K/type_checker.cpp:337-338`）。
真 lean 4.33.1 探针：`#ORACLE_INFER "abc"` 与 `#ORACLE_INFER ""` 均为
`Const(String)`。VM 侧现状 `R/lean_vm/ref_vm.py:457-458` 只返回 Nat
（`docs/KERNEL_COVERAGE.md:40`），WP5 需按字面量的 `LIT_STR` 标记返回 `String` 的 cid。

#### E5 `reduce_proj_core` 对 string lit 的处理

`K/type_checker.cpp:420-441`。首句（`:421-422`）：

```
if (is_string_lit(c)) c = whnf(string_lit_to_constructor(c));
```

即**被投影项若是字符串字面量，先把 E2 展开并 whnf 成构造子应用**，再走通用
投影：`get_app_args(c, args)`（`:423-424`）→ 头必须是常量（`:425-426`）→ 必须是
构造子（`:427-429`）→ `mk_val.get_induct() == sname`（`:431-435`）→
`nparams+idx < args.size()` 时返回 `args[nparams+idx]`（`:436-440`）。调用点
`whnf_core` 的 `Proj` 分支（`:504-509`）。对 `String`（nparams=0，两字段
`toByteArray`=0/`isValidUTF8`=1，`src/Init/Prelude.lean:3540-3546`），
`String.toByteArray "abc"` 先展开成 `String.ofByteArray (List.utf8Encode …) proof`，
取 idx 0 得 `List.utf8Encode …`，外层 whnf 继续归约（真 lean 4.33.1 探针：
`#ORACLE String.toByteArray "abc"` 得 `ByteArray.mk (Array.push … ) …`；
`String.toByteArray "abc" =?= String.toByteArray (String.ofList ['a','b','c'])`
为 true）。

### 14.3 与 iota 的交互（WP3）

内核在 `inductive_reduce_rec` 里对 major 的转换顺序（`K/inductive.h:90-99`）：
先可选的 `to_cnstr_when_K`（`:90-91`）→ `major = whnf(major)`（`:93`）→
**若 major 是字符串字面量，`major = whnf(string_lit_to_constructor(major))`**
（`:96-97`）→ 否则结构 eta（`:98-99`）。之后才用**转换后的 major** 查规则
（`get_rec_rule_for` 只看 `get_app_fn(major)` 的头常量名，`K/inductive.cpp:114-122`）
并取字段（`major_args = get_app_args(major)`，`K/inductive.h:102-103`；
字段从转换后 major 的最后 `nfields` 个实参取，`:112-114`）。

与 §13.2 的数据驱动 iota 组合方式：§13.2 步 5 的"字面量/结构转换"分支即此处。
WP3 在"major 定位（步 4）→ 规则查找（步 6）"之间必须插入一个
`convert_major(major)`，其字符串分支 = WP5 E2 的展开 + whnf；**不得**把
字符串字面量 major 当作 stuck，因为 `get_rec_rule_for` 匹配的是展开后的头
（如 `String.ofByteArray`）。转换后的 major 才是字段来源（`K/inductive.h:102-114`），
不是原始 `LitStr` 节点。真 lean 4.33.1 探针：`String.rec (motive:=fun _=>Nat)
(fun _ _ => 7) "abc"` 的 WHNF 为 `7`，`String.casesOn … "abc" (fun _ _ => 9)` 为 `9`；
`String.rec` 的规则 ctor 是 `String.ofByteArray`、nfields=2（对应 `String`
单构造子 2 字段）。另注意裸字面量的 whnf 不展开（`K/type_checker.cpp:474-477`），
展开只发生在三个显式转换点（`K/inductive.h:97`、`K/type_checker.cpp:422`、`:1147`）。

### 14.4 Unicode / UTF-8 处理

**内核表示是 UTF-8 字节串，不是 UTF-16，无代理对（surrogate pair）**：

- `String` 的运行时表示是 `ByteArray`（`src/Init/Prelude.lean:3540-3549`，
  `String.ofByteArray` 构造子 + `lean_string_to_utf8`/`from_utf8_unchecked` extern）。
- `string_lit_to_constructor` 用 `utf8_decode` 把字节串转成**码点**序列
  （`K/inductive.cpp:1372`；`K/runtime/utf8.cpp:216-221`）。
- `next_utf8`（`K/runtime/utf8.cpp:165-209`）按 UTF-8 首字节分支：
  1 字节 `0x00-0x7F`（`:167-171`）；2 字节（`:173-181`）；3 字节
  `0x800-0xFFFF` **但排除 `0xD800-0xDFFF` 代理码点**（`:183-192`，判据在 `:188`）；
  4 字节直接解出 `0x10000-0x10FFFF`（`:194-203`）。**没有 UTF-16 代理对合并逻辑**，
  4 字节序列一步得到补充平面码点（如 😀 U+1F600 = 码点 128512）。
- 非法序列的容错：都不匹配时返回首字节值并只前进 1（`:206-208`），
  `utf8_decode` 循环直到字节耗尽（`:216-221`）。
- 码点合法性另由 `Char.isValidChar` 约束：`n < 0xD800 ∨ (0xDFFF < n ∧ n < 0x110000)`
  （`src/Init/Prelude.lean:2845-2848`）；`Char.ofNat` 对非法码点回退到 `'\0'`
  （`:2876-2892`，回退分支 `:2892`）。真 lean 4.33.1 探针：`Char.ofNat 0xD800`
  与 `Char.ofNat 0` defeq true；`Char.ofNat 0x10FFFF` 与 `Char.ofNat 1114111` 相同。

**token 编码存字节，不存码点；理由是字节才是字面量的内核数据**（`K/expr.h:59`、
`K/expr.cpp:26-28`），码点是从字节经 `utf8_decode` 派生的中间量
（`K/inductive.cpp:1372`）。两者在良构输入上等价，但存字节还有一个硬约束：
码点最大 `0x10FFFF = 1114111 > 4095`，装不进 VM_SPEC §2 的单个字段
（`docs/VM_SPEC.md:50-55`），而 UTF-8 单字节恒 `≤ 255`。因此 14.1 存字节，
**归约期的码点派生必须实现内核的宽松算法** `next_utf8`/`utf8_decode`
（`K/runtime/utf8.cpp:165-221`），不能用严格的 Python `bytes.decode`，否则对
非法字节序列的行为会与内核不符。良构字面量（已 elaborated 的真实输入）上
`encoded_bytes.decode("utf-8")` 与内核 `utf8_decode` 结果一致。
`R/expr/model.py` 的 `LitStr.value` 是 Python `str`（码点序列），编码时
`s.encode("utf-8")`；含孤立代理码点的 Python `str` 无法编码，与 Lean 拒绝
代理码点（`src/Init/Prelude.lean:2845-2848`）方向一致，具体报错形态记 14.6 第 5 条。

### 14.5 验收 / oracle 设计

**原则**：所有期望判定来自真 Lean 二进制（`~/.elan/bin/lean`，v4.33.1），不得手写。
现有 oracle 入口已可直接复用：`R/reference/lean_ref.py` 的 `run_oracle`（纯 WHNF，
`:90`）、`run_oracle_mixed`（WHNF/DEFEQ/INFER，`:97`）、`run_check_oracle`
（`example : T := v` 接受/拒绝，`:142`）、`run_kdecl_oracle`（`:447`）、
`run_kcheck_oracle`（raw `Kernel.check`/`isDefEq`，`:480`）。oracle 的
`serExpr` 已支持 `.strVal` 序列化（`:53-55`），`json_to_expr` 已支持 k=10 的
`"str"` → `LitStr`（`:178-181`），故 WHNF/INFER 侧 oracle 无需改动。

**语料**（每条期望值一律由真二进制产生）：

- **C1 字面量本身**：`""`、`"a"`、`"abc"`、`"∀"`（2 字节）、`"😀"`（4 字节）、
  混合 `"a∀😀z"`、长 ASCII（如 300 字符）、边界长度。WHNF：字面量原样不变
  （`{"k":10,"str":...}`）；INFER：`Const(String)`。
- **C2 defeq**（触发 E3 与 E5）：`"abc"=?="abc"`（T）、`"abc"=?="abd"`（F）、
  `"abc"=?=String.ofList ['a','b','c']`（T）、`"abc"=?=String.ofList ['a','b','d']`（F）、
  `""=?=String.ofList ([] : List Char)`（T）、`"∀"=?=String.ofList [Char.ofNat 8704]`（T）、
  `"😀"=?=String.ofList [Char.ofNat 128512]`（T）；E5：
  `String.toByteArray "abc" =?= String.toByteArray (String.ofList ['a','b','c'])`（T）。
- **C3 iota**（触发 E2+WP3）：`String.rec (motive:=fun _=>Nat) (fun _ _=>7) "abc"`
  的 WHNF/DEFEQ 期望 `7`；`String.casesOn (motive:=fun _=>Nat) "abc" (fun _ _=>9)` 期望 `9`。
- **C4 端到端声明**（`run_check_oracle`）：`example : String := "abc"`（接受）、
  `example : Nat := "abc"`（拒绝）、`example : String := String.ofList ['a','b','c']`
  （接受）；raw 内核用 `run_kcheck_oracle` 加 `("String", "\"abc\"")` 等，
  走 `Kernel.check`+`Kernel.isDefEq`，期望 `OK`/`declTypeMismatch`。
- **C5 编码 round-trip**（无 oracle）：对 C1 每条断言
  `decode_expr(encode(LitStr(s))) == LitStr(s)`、`V0==len(s.encode("utf-8"))`、
  第 i 字节 token 在 `H+2+2i` 且 kind=40；空串 `V0=0`。

**每个测试断言什么**：

1. **编码层** `tests/test_string_lit_encoding.py`（新增）：C5 的 round-trip/形状/边界；
   `n>4095` 或流超 4096 时报 `ERR_OVERFLOW`；孤立代理 Python `str` 的报错形态
   （14.6 第 5 条）。
2. **参照机 vs 真 lean** `tests/test_string_lit_vs_lean.py`（新增）：对 C1–C4 调
   `run_oracle_mixed`/`run_check_oracle`/`run_kcheck_oracle`，把 RefVM 的
   WHNF/INFER 结果 decode 后按现有习惯剥离 binder 名/MData 再比较
   （`R/tests/test_olean_export.py:100-112`），DEFEQ/接受拒绝按布尔/类别逐条相等。
3. **图 vs 参照机** `tests/test_string_lit_graph_vs_refvm.py`（新增）：同一语料经
   `StepDriver` 与 RefVM 比对，0 pinned（仿 `R/tests/test_stepgraph_infer_defeq.py`）。
   注意图侧 `I_LIT` 现固定发 `Const(Nat)`（§11.5，`docs/VM_SPEC.md:713-717`），
   WP5 需按 `LIT_STR` 补 String 分支，否则 INFER/defeq 会错。
4. **负例/变异**：把字节链改一个字节后 defeq 期望翻转为 false；篡改 `V0`
   链长导致解码失败或越界拒绝（仿 `R/tests/test_mutation_reject.py`）。

**回归不破**（KERNEL_COVERAGE 的 Reg 栏）：`tests/test_ref_vs_lean.py`、
`tests/test_ref_infer_defeq.py`、`tests/test_stepgraph_vs_lean.py`、
`tests/test_stepgraph_infer_defeq.py`、`tests/test_check_e2e.py`、
`tests/test_mutation_reject.py`、`tests/test_olean_export.py`、
`tests/test_env_meta.py`、`tests/test_level_vs_lean.py`。

### 14.6 WP5 TBD

1. **新 kind 编号**：本节取 `T_LIT_BYTE=40`（35–200 段最小可用值，
   `docs/ENV_FORMAT.md:168`），因 §2.2 的分配规则所列 24–29/35–38 已被
   35–39 占满。备选 14–20（也在空闲段，但可能预留给后续表达式 kind）。
   建议 40；需实现时同步 `docs/ENV_FORMAT.md` §2.2（本文不改该文件）。
   **已决议（14.7）：取 40，§2.1/§2.2 已同步。**
2. **字节 vs 码点存储**：本节选字节（14.4 理由：字段上限 + 忠实于
   `string_ref`）。若图侧展开需要直接读码点，需另行设计码点的多字段/分段编码；
   当前不需要，因为 `Char.ofNat` 的实参是 Nat 字面量，可由字节在归约期派生。
   **已决议（14.7）：字节存树；展开所需的码点由编码层按 utf8.cpp 宽松
   算法预先派生进影子树，归约期不派生。**
3. **图侧展开的实例化方式**：`string_lit_to_constructor` 的结果是一棵 eagerly
   构造的 expr（`K/inductive.cpp:1375-1379`），而 VM 是惰性 token 机。图侧可以在
   编译期预生成该展开子树（按字面量位置引用），或在归约期由字节链合成；
   两者的 `mk_app`/beta 语义必须与内核一致（§13.7 第 9 条同类问题）。
   **已决议（14.7）：编译期影子子树，挂在字面量头 `K_LIT.X`；三个转换点
   为 O(1) 改写/重推帧；缺名（`STRING_EXPAND_NAMES`）时 `X=0` 全臂关死。**
4. **长度上限的编码缺口**：内核字符串无 `LEAN_NAT_MAX_SIZE` 类限制
   （`K/type_checker.cpp:318-319` 只查 Nat），而 v1 token 流 `V0≤4095`、序列
   ≤4096（`docs/VM_SPEC.md:50-66`）。超限如实拒绝（`ERR_OVERFLOW`），不静默错答；
   是否需要分段/续链编码留待放宽序列上限（Phase 4+）时决定。
5. **非法 UTF-8 / 孤立代理**：内核 `next_utf8` 对非法序列宽松回退
   （`K/runtime/utf8.cpp:206-208`），Python `str`/JSON oracle 走严格 Unicode。
   已 elaborated 的真实字面量是良构 UTF-8，故差分语料不受影响；若将来接受
   手工构造的非法字节流，需明确报错类别（全局错误类别 TBD，
   `docs/KERNEL_COVERAGE.md:340-347`）。
6. **E5 展开后的深层归约**：`String.toByteArray "abc"` 的 whnf 进一步归约到
   `ByteArray.mk (Array.push …) …`（真 4.33.1 探针）。这依赖 `List.utf8Encode`/
   `ByteArray`/`Array` 的定义进入 VM 环境；E5 的最小断言只到
   "取字段 idx"（`K/type_checker.cpp:421-440`），更深的字节级归约是否纳入
   v1 语料记 TBD。**决议（14.7）：v1 语料不纳入 proj 字段 0 的 WHNF；字段
   0 通过 DEFEQ 对（两侧同 stuck 头，仅比判定）覆盖，字段 1 用
   `Lean.mkProj` 直喂内核 proj 路径。**
7. **`String.mk` 不是匹配目标**：真 4.33.1 探针 `String.mk` 是 Definition
   （别名），`try_string_lit_expansion` 只匹配 `String.ofList`
   （`K/type_checker.cpp:1146`），故不需要为 `String.mk` 加分支；`String`
   的唯一构造子是 `String.ofByteArray`（`src/Init/Prelude.lean:3540`）。
   **决议（14.7）：维持——无 `String.mk` 分支，测试 env 亦不携带。**
8. **错误类别映射**：同全局 TBD（`docs/KERNEL_COVERAGE.md:340-347`）；WP5 的
   越界/非法输入错误码建议先复用 `ERR_OVERFLOW`/`ERR_UNSUPPORTED`
   （`R/lean_vm/ref_vm.py:47-50`），最终粒度随全局决定。

### 14.7 实现决议（WP5 落地，2026-09-13）

本节记录实际实现与 14.6 各项的决议状态；行号引用以真内核参考树
`/home/xkq/lean4/src/kernel/`（下称 `K`）为准。

**E1 数据位置与展开实例化（14.6 第 2、3 条 → 决议）。** 字节存树：
`K_LIT` 头 `V0=n`（UTF-8 字节数）、`V1=LIT_STR(1)`、`X=` 影子展开树根
（0=放弃），字节链 `T_LIT_BYTE=40` 步幅 2（§14.1，`R/expr/tokens.py:33-38`）。
E2 的结果不在归约期合成，而是**编码期预生成影子子树**挂在字面量头的 `X`
上：`App(Const String.ofList, cons.{0} Char (Char.ofNat cp) … (@List.nil.{0}
Char))`，由 `_enc_expr` 常规递归按 `K/inductive.cpp:1368-1380` 语法构建，
A 节逐节点断言与内核语法一致。理由：图是定权有限状态机，没有归约期的
"任意骨架构造"微程序（§13 的 iota_build 循环只是 NAT(OP_IOTA) 单帧实例）；
预生成把三个转换点全部变成 O(1) 改写/重推帧：

- E2（iota major 转换，`K/inductive.h:96-97`）：`iota_str_r` 臂重推
  `NAT(OP_IOTA)` 帧对，focus 指向 `X`；
- E5（`K/type_checker.cpp:421-422`）：`pr_str` 臂重推 `[ST(I_PROJ),
  WHNF(X)]`（与既有 proj_setup 同构）；
- E3b（`K/type_checker.cpp:1145-1156`）：`es_str` 臂把 ST 帧替换为 DEFEQ
  帧对 `X` vs 侧 B，命中 FINAL（`:1147-1150`）。

成本（探针实测，`R/expr/tokens.py` Encoder）：编码侧每字面量
`1+2n`（头+字节链）+ 影子展开 `6 + Σ码点(7 + 数码链)` ≈ 13 token/码点
（ASCII；码点位的十进制数码链与 §5 同布局）。归约期三个臂均为常数次帧
操作，与链长无关。字节数上限 `LIT_STR_MAX_BYTES=4095`（`V0` 字段约束；
超出在编码层抛错，运行期拒绝语义沿用 §9.4）；内核无字符串尺寸限制
（`K/type_checker.cpp:318-319` 只查 Nat），该上限属 v1 编码缺口，
14.6 第 4 条维持 TBD。

**放弃规则（与 §14.2 "通过 WP1 元数据定位常量"一致的 v1 实现）**：
`STRING_EXPAND_NAMES = (String.ofList, List.cons, List.nil, Char.ofNat,
Char)`（`R/expr/tokens.py:173-174`）任一名字不在 env `b.cids`，则
`X=0`、三个臂 gated 关死，字面量退化为普通 stuck token（A 节 decline
分支验证；无遗留硬编码 fallback）。`String.ofList=18`、`String=19` 由
`STR_ID_CODES`（`R/expr/tokens.py:168`）按名写进 `ENV_HDR.X`，图侧
`_SCAN_OPS` 在 cid<96 窗（`R/lean_vm/build_vm.py:267`）发现（14.6 第 1、
7 条 → 决议：`T_LIT_BYTE=40` 已同步 `docs/ENV_FORMAT.md` §2.1/§2.2 与
§4.2 操作码占用表；`String.mk` 别名不加任何分支——`try_string_lit_expansion`
只匹配 `g_string_mk = Const "String.ofList"`，`K/type_checker.cpp:1146`、
`K/inductive.cpp:1394`）。

**E4**：`lit_i` 臂按 `V1` 分派（`K/type_checker.cpp:315-321`）：`V1=1` →
发 `Const(_STRING_CID)`（E4 gated `_STRING_OK`；env 无 `String` 时 `bad_i`
拒绝，与内核在无 String 环境 infer 失败一致）。Nat 尺寸检查半边属 WP6，
未做。

**E3a**：defeq 字面量对 `deq_lit_str`：`V0` 不等 → 直接 `K_FALSE`
（字节数不同的字面量其展开必不相等，与 `:1147` 比较整棵展开等价）；
相等 → `D_LITL` 沿步幅 2 逐字节比较（字节链与 Nat 数码链同布局，循环
复用）。等字节 ⇒ 等字符串，无 padding 假阳性；长度陷阱由 `deq_nul*`
语料覆盖（B 节）。

**oracle 层事实（修正 §14.5 预期，14.6 第 6 条 → 决议）**：4.33.1 的
`Lean.Meta.whnf` 是 `@[extern "lean_whnf"]`
（src/lean/Lean/Meta/Basic.lean:779），即 `#ORACLE` 的 WHNF 判定就是
内核 `whnf` 本身（含其对 Definition 的全量 delta、对 theorem 值的
不展开）。两点由此确立：
(a) `String.ofList._proof_1`、`String.isValidUTF8` 等 kind=2 应用在内核
whnf 下原位 stuck（2026-09-13 run_cmd 探针），而 `String.casesOn` 在
4.33.1 是 kind=1 def、会被展开——差分测试的 env 必须按 kind 选择携带
哪些 value（测试白名单 `KEEP_VAL={String.ofList, String.casesOn}`）；
(b) proj 字段 0 的 whnf 会把 `List.utf8Encode` 一路展开到
`ByteArray.mk (Array.push …)`（需 Array/UInt8 闭包），不进 v1 语料——
字段 0 改由 DEFEQ 对（两侧同 stuck 头、只比判定）覆盖，字段 1 用
`Lean.mkProj`（4.33.1 无 `x#i` 用户语法）经 oracle `run_cmd` 直喂内核
proj 路径。`String.ofList` 有值时 E3 臂被 lazy_delta 前置展开遮蔽、判定
经 eta-struct 得出（与 §14.2 调用点分析一致）；臂本体只在
value-pruned env（§14.5 C 节，真 lean 不存在此 env）可达，故 C 节为
图内语义形状检查，B 节判定仍全量对齐真 lean。

**实现位置**：编码 `R/expr/tokens.py`（`T_LIT_BYTE`、`STR_ID_CODES`、
`utf8_codepoints`、`string_expansion`、Encoder `_enc_expr` LitStr 分支、
`decode_expr` K_LIT 分支）；图 `R/lean_vm/build_vm.py`（`_SCAN_OPS`、
`iota_str_r`、`pr_str`、`es_str`/`es_no`、`deq_lit_str`、`lit_i`）；
验收 `R/tests/test_string_graph_vs_lean.py`（A 编码不变量 / B 差分 /
C pruned-env 臂）。

### 14.8 WP5 收尾决议（2026-09-14，代理 A）

**根投递通道的二值 gate（E4 修复）。** 字面量的 INFER 投递（`lit_i` 臂发
raw `Const(String-cid)` 后以 A=raw 位、E=1、D=0 到根）同时满足两条根 halt
条件：`ret_pending`（E=1 ∧ 无框，K/无对应——机器协议）与 `complete`
（focus 是不动点 Const，`K/type_checker.cpp:474-477` 的裸字面量/常量语义在
图上的对应即 stuck 终结）。`halt` 是加法通道，此处合计 2（done 仅判非零，
无害）。结果位置 `A_res` 的 gate 必须是**恒二值**的根投递通道本身
`reglu(ret_pending, One - has_frame)`，不得用 `halt·ret_pending`：非二值
gate 经 `_select(cond, SA, A_done) = cond·SA + (1−cond)·A_done` 线性外推，
把结果乘成 `2·SA`（越界位置，驱动侧 decode IndexError）。语义不变式：
E=1 到根的投递，结果在 A（DEFEQ 判定 0/1 或 INFER 类型位置），永不是
pend-spine 根 SF；同时保住 02:43 修 D_SP1 stale-pend 劫持 `result_spine`
的原意（es_str_false 曾把 PEND token 当结果报出）。

**C 节判据契约。** C 段是 pruned-env 图内语义形状检查（真 lean 无此 env，
`String.ofList` 必有值，§14.7 oracle 层事实 (a)）。判据 = 二值判定与期望
**双端一致**（`got is want`，bool 恒等既查值也查类型），True/False 两类
期望都合法——内核 `try_string_lit_expansion` 命中臂时对
`is_def_eq_core(whnf(string_lit_to_constructor(t)), s)` 的结果取
`to_lbool`（type_checker.cpp:1145-1150），调用点
`if (r != l_undef) return r == l_true`（:1238-1239）true/false 均为终结
FINAL。False 期望的真值锚 = B 段同形输入 `deq_oflist_false`
（`"ab"` vs `String.ofList ['a']`）lean=False 实测定锚（图判定一致 PASS）。

**微步预算（GRAPH_MAX_STEPS=6000）。** 内核 `is_def_eq_core` 无步数预算
（`scope_rec_depth` 默认 0=unlimited，`src/runtime/interrupt.h:45-47`），
故本套 cap 只许大于任何收敛计算的真停机，不得反客为主改判定。实测：
E3b/eta-struct 链上 `"ab" =?= String.ofList ['a','b']`（真 env，须对
utf8Encode 侧与字面量展开侧做全 spine 配对比较）2449 微步停机、proj 对 2451；
False 例（首分歧即停）670；C 段臂本体（展开→重入 DEFEQ 一次）710/708/548。
成本来源：`String.ofList` delta 展开成 `String.ofByteArray (List.utf8Encode
…) proof` 后，`List.utf8Encode` 逐 cons 重算码点→字节，每层 cons 需帧
pop/push + 数字链逐位比较（实测 ~330 微步/码点层：len 1/2/3/4 =
380/710/1124/1622，True 全链翻倍）。本套件最大真停机 2451 → 6000 ≈ 2.4×
余量，且与仓库既有最大先例（`test_stepgraph_infer_defeq`）同值；改预算
不改判定，判据仍是与 lean 一致。

## 15. reduce_nat 图侧补齐（WP6，2026-09-14/15，代理 C3）

F 组新算子（`Nat.gcd/land/lor/xor/shiftLeft/shiftRight`，ENV_HDR.X 操作码
20-25，`NAT_OP_CODES` 名字扫描 = 铁律 3 合规）与尺寸守卫 F1-F4/F9 的图相位。
设计蓝本与探针证据链见 `docs/handoffs/002-C-wp6.md`；守卫决策的 Why 在 ADR
007（相位编号）/008（MAX 烘焙）/009（strip 扫描）/010（阈值取整方向）。
权威语义（4.33.1 实测与 4.35 master 源码逐条一致，见 handoff「阶段 1」）：

| 算子 | 内核尺寸检查 | 依据 |
|---|---|---|
| add / sub / mul | 算出 r 后 `check_size`：拒 ⟺ 8·limbs(r) > MAX | K:644-658 |
| succ | v+1 后同检查 | K:706-713 |
| pow | `get_count_arg(exp)` 先行（>UINT32_MAX 抛，K:308-313），再：拒 ⟺ base>1 ∧ k≠0 ∧ size(base) > MAX/k | K:660-675 |
| shiftLeft | v=0 直接收；`get_count_arg`；拒 ⟺ size(v)+⌊k/8⌋+1 > MAX | K:677-690 |
| pred / gcd / land / lor / xor / shiftRight / beq / ble | **无**尺寸检查 | K:644-713 |
| 字面量（含操作数位置） | infer_lit：8·limbs > MAX 抛 | K:315-321 |

### 15.1 gcd（Stein 二进制版，相位 X41-X57）

内核 `Nat.gcd` 走 GMP（值唯一，算法不可见），图用二进制 gcd：
X41/X42 对 u/v 零扫描（`gcd 0 b = b` 等，K:721）→ X43 双偶门（g++，先各
÷2 一次，X44/X45 低→高 ÷2 pass）→ 主循环 X46/X48 单侧偶门（u 除到奇、v
除到奇，X47/X49 复用 44/45 的逐位算式）→ X50 高→低量级比较（E 打包：0 平
/ 1 u<v / 2 u>v）→ X52/X53 低→高借位减（v−=u 或 u−=v；head 由 X50 done 臂
预发、borrow pass 往 stride 位填数字，X52/X53 不再发 head；结果 head 槽位
X52 在 F2、X53 在 E2）→ 减零即定胜负（X56 k 门）→ X57 ×2^g 交付 pass。
终止 ⟺ 某一侧归零（既有 nzflag）。

### 15.2 shiftLeft（相位 X61-X68）

X61 k 十进制位数门（≤9 放行、=10 进 X62 高→低逐位比 4294967295 表、≥11
拒——仅 GREATER 拒，tie 收，K:308-313）；X63 v 零扫描（v=0 → 直接交付 0，
K:685 的 `!v.is_zero()` 门）；X64-X65 尺寸守卫：非零 v 预发 m1 = k + 64·L(D)
的 head（V0 = n_k+1），X64 低→高十进制加法（64·L ≤ 27264，按 10 的幂阈值
分解），X65 m1 vs 8·MAX 高→低 lex，**严格小于才放行**——对应内核
size+k/8+1 > MAX 的 > 语义。机器 CERTAIN 拒条件 `k+64·L ≥ 8·MAX` 的推导：
bytes = 8·limbs ≥ 8·L，故守卫量 ≥ 8L + (k−7)/8 + 1 = 8L + k/8 + 1/8，
8L + k/8 ≥ MAX ⟹ > MAX，整数侧即 ≥ MAX+1。带（真 limbs > L 使内核拒而机器
收）= 文档化松弛，语料不可达（结果 ≥ MAX 字节，链式物化同样不可行）。
X66 高→低 Horner 把 k 装进 A 计数（**低→高读会把数字串反转**，实测坑）；
X67 轮门：A=0 → 交付 frE2（v·2^k），否则 A-- 并预发 ×2 head；X68 低→高
×2 pass（镜像 X57）。

### 15.3 尺寸守卫（F1/F2/F3/F9，相位 X71-X76 + rej_o/rej_lit）

阈值烘焙（选项 B，ADR-008）：`_read_nat_size_env()`（build_vm:75-98）编译
期复刻内核 read_nat_size_env（K:1307-1315：strtoull 全串消耗否则回默认
128MB，负数按 size_t 回绕 mod 2^64），MAX/8·MAX/4294967295 的十进制数字只
进数字表（数据）。派生量：T = ⌊MAX/8⌋+1（limbs 拒绝阈）；
L(D) = 1+⌊(D−1)·3321/64000⌋（mpn limb 下界，425 项阈值扫一步出值，
`_limbs6`）；`_T_DIG = 1+⌈64000(T−1)/3321⌉`（精确位数 ⟹ 必拒的界），
图内比较常量 `_T_DIG_CMP` 取 ≥ 真值的最小 fp32（向上，ADR-010：解集只会
缩小，机器拒 ⊆ 内核拒不被破坏）。默认 MAX=128MB 时 _T_DIG ≈ 3.2 亿位，远
超可编码链（≤8191 位）——尺寸类守卫恒不点火，可证零开销；32 位帽守卫
（pow/shiftLeft 第二参 > 4294967295）与字面量守卫（infer_lit、rej_o）在任
意 D ≥ 21（小 MAX 8 烘焙）时点火。**前提 MAX ≥ 8**：X76 全零链按 D_r=1
放行（值 0 的 size=8 ≤ MAX），MAX<8 的烘焙会连 `0` 一起拒——内核同样拒
（8·limbs(0)=8 > MAX），但本仓库不测该配置，文档记死。

pow 守卫 X71-X75（插在 d23 分发 X=10→pow 与 X10 扫描之间，get_count_arg
先行所以帽在 base 门前）：X71 exp 位数门 / X72 exp vs 4294967295 lex（镜
像 X61/X62，exp 链在焦点寄存器 A）；X73 base>1 门（Nat.zero 构造子经
`_wz6`、一位链 "0"/"1" 经 V0==1 头——数字链规范编码无前导零，两门可证互
斥且二值；非字面量 base 误分类无害：机器与内核同样跳过=不猜）+ 把
s73 = 8·L(D_a) 存帧 F2 + 预发乘积链 p = s·k 的 head@c2（V0 = n2+10，10 位
pad 吃掉一切进位；s < 10^6 ⟹ t = d·s + carry < 10^7 < 2^24，fp32 精确）；
X74 低→高逐位填 p（十进制位阈值分解求 /10 与进位）；X75 p vs MAX 数字高→
低 lex（**严格 > 拒，tie 收**——`size(base)·k > MAX` 与内核
`size(base) > MAX/k` 的整数除法等价，K:670）；放行 → X10（F := acc head
c2，C/E/B 清零，caller V2 经 pow_go 续线程）。

X76 结果 strip 扫描（ADR-009，add/sub/mul/succ 的**结果**守卫）：交付步
（done_s 的 addfam 与非下溢 sub 臂、mul_done）保留原寄存器臂，仅 D 改写
X=76 帧于 c2（caller 弹出目标 caller_c/ncV2 暂存帧 V2），数字链尾在 c1。
X76 高→低扫已物化链：首个非零数字 ⟹ 精确位数 D_r = V0−SB；done76 步
`D_r ≥ _T_DIG_CMP` 即 `rej_q` 拒（limbs ≥ L(D_r) ≥ T ⟹ bytes > MAX，内核
必拒，**无 false reject**），否则 D := frV2 原样弹回。B 计数器在 hit 步冻
结（done76 晚一拍，SE 滞后；不冻结则阈值上恰 21 位（MAX=8）false
accept——build_vm :2419-2422）。带（limbs = L+1 且高位数字稀疏，内核拒机
器收）为文档化松弛：语料侧排除（test 文件头有区间推导），不许反向放宽。
pred 与 sub 下溢交付不接入（K 不查/值为 0）。

操作数字面量门 `rej_o`（d23/dn1 分发步）与根 infer 门 `rej_lit`（K:315-321
镜像）：reduce 通道从不把操作数当 infer 焦点，故在 d23 取两参链头 V0（仅
nat-lit 才计数：kind=LIT ∧ V1=0 门控，stuck 操作数掩零）、在 dn1 取 pred
参数位数，max ≥ _T_DIG_CMP 即拒；rej_lit 保留原语义（焦点字面量在 INFER
分支才点火）。全部守卫臂并入 `reject` 和（rej_q + rej_p + rej_o + …），
code 仍 1（ERR_TYPE = 内核异常通道，与 step_driver 的 VMError 一致）。

差分测试：`tests/test_reducenat_graph_vs_lean.py`（最小 env、期望只来自真
oracle 现跑）。A 段默认 MAX（帽/尺寸回归 + pow 帽与 shl 帽的机器-内核一致
性；帽类用例内核消息被 elaborator 抢先（threshold 警告→maxRecDepth、
shiftl runtime PANIC），以 rc≠0 为内核拒绝判据、类名记 "cap-artifact"）；
B 段 `LEAN_NAT_MAX_SIZE=8` 烘焙同值双侧（例：add 带内 20 位边界、
`mul 10^10 10^15` 26 位 X76 拒、pow tie/帽/带、shl 尺寸带、操作数 10^20
字面量拒、sub 长借位回归）。拒绝用例**逐例 lean 子进程**（批内一条异常整
批死），接受用例走 `#ORACLE` WHNF 批（注意 #ORACLE 走 elaborator 无检查
解释器，只能给值不能给守卫判定）。



## 16. is_def_eq 剩余分支与声明错误类别（WP7 规格，2026-09-15，代理 D，卡 007）

### 16.1 DEFEQ 派发新增臂（build_step_graph 的 DEFEQ dispatch，§10 协议）

派发门（互相排斥，deq_fall 元组逐一排除；soft-whnf 兜底 = `deq_sw0 =
deq_fall + proj_diff`）：

- `deq_succ`（A26，K/type_checker.cpp:1076-1085）：双侧 K_APP、头部裸
  K_CONST、`_is_succ`（ENV ctor 标签 + legacy 回退）双双命中 →
  succ/succ 尾调用参数对（核 commit 子判定，尾调用忠实）；zero/zero 由
  whnf 折叠后进 deq_lit。
- `deq_refl`（A14，K:1181-1185）：`s` 侧 = Bool.true（`_is_true`）且非
  deq_const/deq_same → 单侧 soft-whnf `t`，DE_RFL sink 按 whnf 结果与
  Bool.true 比对并**直接 commit**（commit-false 可靠性论证 = ADR-011 §2：
  Bool 非递归结构无 eta-struct、非 Prop 无 proof-irrel/unit-like）。
- `proj_same` 改造（A15，K:1216-1227）：同 sname+idx 的 proj/proj 不再
  commit-false。发射 [ST(F2=DE_PRJ, V2=SD), DEFEQ(child 对)]，peel/child
  的 verdict 走各自 V2 进 sink；sink true → 穿埋没 DEFEQ 帧 commit，
  false → 用 oo*（frV2 处原始对）重推 deq_sw0。`proj_diff` 并入 deq_sw0
  （核 :1224 起 whnf 重 dispatch）。
- `deq_hargs`（A17，K:1032-1045）：双侧同 cid 头、头 K_CONST、
  `ENV_HDR(cid+1).V2 ≥ 1`（is_delta 有值）、anchor 元数据
  `T_ENV_META.V1 == CK_DEFINITION` 且 `anchor.V2` 指向的
  `T_ENV_DEFVAL.V1 == 2`（Regular hints）、头 level 链 `_lvl_chain_eq`
  → 非 commit 尝试：[ST(F2=DE_ATT, V2=SD), ST(F2=D_SP1, V2=c1)]（复用
  stuck-pair peel 链，commit 目的地 = sink）。sink true → commit（核
  :1039）；false → 重推 deq_sw0（核 :1043 Continue→双侧 unfold）。
  legacy 无 meta 流 gate 恒 0（无 DEFVAL token），行为与改图前一致；
  hints 判定零常量名/零 cid 写死（验收铁律 3）。
- 新续延 id：`DE_PRJ=64, DE_RFL=65, DE_ATT=66, CK_G0=67, CK_G1=68`
  （`g = range(1,69)`）；2 帧臂全部登记进 `em_frame_m2`/`em_frame2_m2`。
- A30（try_unfold_proj_app，K:983-990）判定中性、被 deq_fall whnf-both
  吸收，不做专用臂（ADR-011 §4；证据 = j5 + A15 组差分）。

### 16.2 CHECK 通道的 G1/G7（K/environment.cpp:87-95,127-133 → K/type_checker.cpp:62-70）

- kickoff 改为 ensure_sort(声明类型) 链：`[ST(F2=CK_G0; V1=声明类型根,
  X=值根, V2=下一锚), INFER(声明类型根)]`；CK_G0 收到 T1 后压
  `[ST(CK_G1), WHNF(T1, soft)]`；CK_G1 判定 whnf(T1) 的 kind==K_SORT →
  按原 kickoff 形状续跑值 infer（`[ST(CK_TY), INFER(值根)]`），否则
  reject。
- G7：锚帧的 `V1`/`X` 根 token 为 K_FVAR/K_MVAR → 直接 reject（核
  declHasMVars/declHasFVars 在 check_constant_val 之前）。仅根位置近似；
  深层 fvar/mvar 仍走 infer 通道既有 reject（类别记录为接缝）。
- 新拒绝码（§7.4 扩展）：`5 = typeExpected`、`6 = decl root has
  free/meta variables`。既有 1/2/3/4 输出不变；`reject_code` 输出仅
  Python 驱动器消费（engine/vm.cpp 无该通道）。
- 未实现（接缝，卡 007 边界记录）：G3 thmTypeIsNotProp（run_check 通道
  无声明 kind 信息，需 step_driver 属主改动 → 移交总控裁决）；G8
  alreadyDeclared（编码层 name 唯一，token 流不可表达）；G9 dup
  univ params（核 O(n²) 链查重，需新链扫描帧）。
- 验收：`tests/test_defeq_branches_vs_lean.py`（新差分，KDEFEQ 核通道 +
  KDECLMSG 类别映射，legacy/meta 双流 32 例 + G 8 例全对齐）；
  `test_check_e2e` A15/B15 不变。

### 16.3 CHECK 通道的 G5/G10 与臂序/门语义（WP7 续，2026-09-15，代理 D2）

§16.2 的链假设"每个声明都有 value"，且没有 safety 门。本小节补齐两臂并写
死臂序；语义决策见 `docs/decisions/012-wp7-g5-g10-gates.md`。

- **臂序（CK 区，一次 select 内互斥）**：ck_kick（ST→CK_G0 起 ensure_sort
  链）→ CK_G0（收 whnf(T1) 压 CK_G1）→ CK_G1 判定 `whnf==Sort` 后三分叉：
  `ck_g1_val`（帧 X≥1，有 value）→ 旧 value-infer 重launch（hard INFER，
  E2=1，焦点=X=值根）；`ax_go`（X==0 且 V2≠0）→ 直接推进链：A=n 锚的
  value 根（nbX）、D=frV2 重新武装 ck_kick；`ax_done`（X==0 且链尾）→
  A=One 进 halt 验收合并（:5806，`halt += ck_accept + ax_done`）。无值形
  态即 axiom：add_axiom 只跑 check_constant_val
  （K/environment.cpp:152-158，`axiom_val` 无 value 字段，K/declaration.h）。
  G7（锚帧根 token 是 FVar/MVar，`ck_kick` 处 :5071，先于本链）与
  g1_fail（whnf≠Sort）位置不变。
- **G5 约定（数据面）**：声明帧 X 字段（= ENV_HDR.V2 值根拷贝）为 0 表示
  "声明无 value"，ENV_HDR 本体不变；这是结构约定，不是名字/cid 分支
  （验收铁律 3）。编码与差分双向钉住：`g5_axiom_funtype_ok`（真核
  `.axiomDecl (Nat → Nat)` = OK，旧 dummy-value 臂会错判
  declTypeMismatch——本臂把该分歧钉死）、`g5_axiom_type_lit`（type
  非 Sort → typeExpected，仍走 CK_G1 失败臂）。
- **G10 门（INFER const 臂，build_vm :5257-5269）**：内核仅在
  `infer_constant`（safe-mode type_checker，默认安全
  K/type_checker.h:125-128）抛 `.other`（K/type_checker.cpp:111 unsafe、
  :115 partial；全仓库唯一抛点，实测 grep），whnf/delta 展开无 safety 检
  查（`unfoldDefinition` 不调 infer_constant），故 DEFEQ 臂不触门。
  flags 位测试不可在环内 select 展开，编码器把 `IS_UNSAFE|IS_PARTIAL` 的
  析取预算成锚点 `T_ENV_META.F2`（use_reject；ENV_FORMAT §2.3）；图侧
  `safety_i = ph1 ∧ const ∧ F2==1` 并入 bad 通道（:5344：soft infer→失败标
  记、hard infer→reject，与核 inType/value 两个位置一致），同时从
  `const_i` 掩掉正常通道；reject_code 选择链顶加 `7`（装配点现为
  `build_vm.py:6564-6568`，卡 010 G02 加 8 后优先序 7>6>5>8>4。原文误引
  `:6053`，那是 quot_stuck 的 select 行——总控 2026-09-19 验尸勘正），
  门控数据 = 锚点 F2=use_reject（见 §16.3 与 ENV_FORMAT §2.3）。
  legacy 流 F2 恒 0 = 数据缺失门自然关闭（差分用例
  `meta_only` 标记记录，不放宽断言）。
- **4.33.1 实测语义（差分据此写死）**：elaborate 的 `partial def` 本体存为
  OpaqueInfo（toolchain Main.lean:20-37 重写 kind=opaque + inhabitant
  值），引用它 = OK；真正 safety=partial 的是生成影子
  `<name>._unsafe_rec`（Basic.lean:280-296、Old.lean:47-48），引用它抛
  "safe declaration must not contain partial declaration"。原始
  `.defnDecl safety:=.partial` 作被引用者同样抛——门只看被引用常量的
  safety 与检查器 mode，不看添加方自身（实测）。三例：
  `g10_partial_plain_ok`（OK）、`g10_partial_use`（meta 流 code 7）、
  `g10_unsafe_use`（meta 流 code 7）、`g10_safe_control`（门闭合
  0）。
- **G2/G4 现状**：unsafe-add-先注册后检查（env.cpp:160-190 的 else 支与
  add_mutual :236-241 的块内可见性）在单遍 ENV 下不可表达（自引用声明
  需要先存在于环境）——记为接缝；safe 支序列（check_constant_val→fvar
  门→check(value)→defeq）已由 §16.2 链 + G5/G10 完整覆盖。G4
  add_opaque 与 safe add_definition 检查序列逐行相同
  （env.cpp:211-223 vs :177-184），差分 `g4_opaque_mismatch` 与 G2 同类
  别（declTypeMismatch）实测一致。
- 验收（本小节新增）：同文件 G 臂 15 例全对齐（legacy 双流 12 +
  meta_only 3），legacy/meta A 臂 32 例与 D 记录一致；`test_check_e2e`
  A15/B15、`test_datadriven_bool` 12/12 步数与改前逐值相同；重编译
  scratch 24914 dims / 2878 lookups（+31/+2）。

### 16.4 CHECK 通道的 G3：theorem `is_prop` 与拒码 8（卡 010 G02，2026-09-19，代理 G）

内核 `add_theorem`（`K/environment.cpp:192-209`）的检查序列是
`check_constant_val` → **`is_prop(type)`** → `check_no_metavar_no_fvar(val)` →
`check(val)` → `is_def_eq`；`is_prop` 假即抛
`theorem_type_is_not_prop`。图侧的 `check_constant_val` 段早已存在
（§16.2 的 CK_G0/CK_G1：软 whnf 声明类型的类型 → 要求 `K_SORT` → 否则码 5），
所以本拍只补"level 归零"这一测。

- **载体**：`TASK_CHECK` 锚帧 E2 = `kind_code + 8*check_mode_code`
  （格式与取值表在 ENV_FORMAT §2.8；写侧
  `lean_vm/step_driver.py:38-58 check_e2()`，读侧
  `lean_vm/build_vm.py:224-235 CHECK_*` 常量）。kind 走数据、无名字/cid 分支
  （铁律 3）。`kinds=None` → E2=0 = unspecified → 闸门完全失效，旧路径逐字不变。
- **E2 的图内路径**：kickoff `fr1_E2_k = frE2`（`build_vm.py:5509-5511`）把
  锚帧 E2 复制进 ST；CK_G0 `fr1_E2 = _select(ck_g0, frE2, fr1_E2)`（:5430）
  再 forward 一跳；CK_G1 步骤的 D 指向该 ST，闸门在那里读。
  为什么这个槽可用：CHECK 链的 ST 用 F2 ∈ {CK_G0, CK_G1, CK_TY, CK_RES}，
  而其余 `frE2`/`nbE2` 读者都按帧类型或 continuation id 门控
  （`nbE2` 的唯一读者 :1366-1367 要求 `nbV0==TASK_WHNF`；`soft_flag` :359
  要求 `nbV0==TASK_INFER`；`cg[IP_PEEL]` :5042-5043 要求 `F2==IP_PEEL`）。
  空闲性的**实证**件 = `tests/test_decl_injection_vs_lean.py` 的 `guard` 段
  （整份 check_e2e 语料，判定/错误码/微步数逐字相等），并已在图未改动的快照
  上跑过一次（006 心跳 S1）。
- **新臂**（`build_vm.py:5449-5473`）：
  `g3 = ck_g1_ok ∧ kind_code==theorem ∧ 声明类型的类型的 level 根 ≠ KL_ZERO`
  → `rej_c += g3`、reject_code 链插 8（:6564-6568，7>6>5>8>4）。
  level 零测**复用 PI 链 `pl_prop` 的同一段测法**
  （`fetch_by_position([k_], _fv0(SA))` vs `KL_ZERO`，:4469-4474 同源，本拍前是 :4451-4457，
  ADR 020 决策 B：不另造第二套 level 判据）。
- **臂序依据**：`environment.cpp:200` 的 `check_constant_val` 先于 `:201` 的
  `is_prop`，故 8 排在 5 之后。两条臂本身按构造互斥
  （`g1_fail` 要 `!ck_g1_ok`，`g3` 要 `ck_g1_ok`），且 7 只在值 infer 步抛
  （is_prop 通过后才会走到），所以链上位置记录的是内核次序，不是在解平局。
  实测：`thm_typeexpected`（声明类型 `2`，kind=3）→ 核抛 typeExpected、
  图给码 5（不是 8）。
- **闸门只对 theorem 生效**：kind 1/2/4 在同一条非 Prop 类型（`Nat`）上
  实测全部不触 8（差分 `axm_nat`/`def_nat`/`opa_nat`，双侧 OK/accept）。
  axiom 行是 X=0（G5 无值形状）第一次带非零 kind 载荷过链（该路径本身已由
  `test_defeq_branches_vs_lean.py` 的 g5×2 验过）。
- **Prop 闭包是实测的**：核 `infer_type` 对 `forall (x : Nat), True` 给
  `Sort 0`（Prop 依赖积封闭），故它是 **Prop**；实测 oracle=declTypeMismatch、
  图 code=1 一致（差分 `thm_arrow`）。图侧 INFER 的 Pi 归 sorts 已实现该
  封闭规则，本拍无需补臂。
- **已知缺口（ADR 020 决策 B 命中，实测双方原文）**：核
  `normalizes_to_zero`（`K/level.cpp:174-186`）对 `imax(_,0)` 只看 rhs、
  对 `max(0,0)` 两边皆零即真，而图侧测法是根节点 syntactic 比 KL_ZERO，
  所以：
  | 用例 | 声明类型的类型 | lean 4.33.1 (`#KDECL`) | 图 |
  |---|---|---|---|
  | `thm_imax` | `Sort (imax 1 0)` | `OK` | reject code **8** |
  | `thm_max00` | `Sort (max 0 0)` | `OK` | reject code **8** |
  | `def_imax`（对照，kind=2） | 同上 | `OK` | accept（15 微步） |
  | `thm_sortraw_imax` | `Sort (imax 1 0)` 直接当声明类型 | `thmTypeIsNotProp` | code 8（一致） |
  假拒（把该过的声明报成 reject），显性不静默；根因 = 矩阵 D1/D2
  （`mk_max`/`mk_imax` 智能构造缺失，卡 012）。语料侧注意：源写的
  `Sort (imax 1 0)` 会被前端归一（实测存储为 `Sort zero`），所以非归一形
  只能用 `Lean.Expr.sort (Lean.Level.imax …)` 经 `Lean.addDecl` 注入 env，
  该构造是**输入**而非结果。登记在
  `tests/test_decl_injection_vs_lean.py:KNOWN_GAPS`，按卡 009 的 XPASS 协议
  （修好后仍留在册会 **FAIL**，不许静默转绿）。
- **不做**：mode 位（E2 的高位）在本拍只定义、不接入图侧行为（G2-unsafe
  先注册后检查留给 G03）。
- **验收通道边界（申报）**：码 8 只有 **Python 图 + 真 lean 差分**这一条通道。
  `scripts/verify_engine_vs_refvm.py` 的 34 例是 WHNF 通道（回归表头注即写明
  "the C++ engine … IS the weight-side acceptance channel, WHNF only"），
  它只能证明"新臂没把权重侧的 WHNF 判定弄坏"，**不经过 CHECK 链**，
  故"编译后的 C++ 引擎在 kind=3 上抛 8"这一条 NOT-VERIFIED。
  权重侧对码 8 的等价性目前由"同一张图的符号求值"承担（臂是 O(1) 门控，
  +22 dims / +2 lookups / +104 nnz，见 006 心跳 H2 的 pre/post 对照表）。

### 16.5 CHECK 通道的 G6：mutual 块前置可见与码 9（卡 010 G06 拍，2026-09-20，代理 G）

内核 `add_mutual`（`K/environment.cpp:225-269`）把一个 `MutualDefinition`
声明的 n 个成员**先注册后体检**；driver 侧对应物 = 新类 `InjectionEnv`
（`lean_vm/step_driver.py`，add_axiom/add_definition(safe/unsafe)/add_theorem/
add_opaque/add_mutual 家族，逐分支镜像 ：271-284 分发的各检查序列）。
**图（build_vm.py）零改动**：本拍无任何新图臂。

- **码 9 = mutual well-formedness（driver 簿记族，不进图）**：图没有名字
  空间与块概念，下列判定全部在 `InjectionEnv.add_mutual` 内以数据完成
  （零常量名/cid 分支），消息原文逐字镜像核（4.33.1 实测，P1 探针）：
  空块 "invalid empty mutual definition"（:228-229）；块 safety=safe
  "invalid mutual definition, declaration is not tagged as unsafe/partial"
  （:230-232）；同 safety（:239-240）/ 同 lparams（:241-242）/ 块内重名
  found-set "invalid mutual definition, duplicate declaration name '…'"
  （:246-248）。核侧这些是纯文本 `kernel_exception` →
  `Kernel.Exception.other`（`kernel_exception.h:201-203`），oracle 类别
  "other" ↔ 码 9。
- **两阶段相位（对齐核的注册前后切分）**：header 循环（:236-251，含
  `check_constant_val` 的 `checker.check(type)`，:127-132）跑在**旧 env**
  上、先于注册（:253-257）；值体检（:259-267）跑在 new_env 上。driver：
  pass A = 全员 header 图检（锚 X=0 = G5 无值形状，kinds=[2]×n，
  E2 mode=块 safety）在注册前 → 注册全员（Encoder 环境表追加）→
  pass B = 全员全检；任一失败**整块回滚**（_consts/_names 弹回，
  被遮蔽的旧名绑定恢复）。回滚可观察性实测（P2 探针，handoff 006 G06）：
  失败块成员从调用方 env 引用 = unknownConstant；异常载荷 env 里成员已
  注册（"先注册"真实发生、只是不提交）。
- **`run_check` 协议扩展**：第 4 参 `check_mode=0`（G01 备案名）。E2 =
  kind + 8*mode（§2.8 布局）。`kinds=None` 路径 E2 恒 0，逐字节不变；
  `kinds=None ∧ check_mode≠0` 显式 ValueError。图侧 kind 解码本来就
  mode 无关（§16.4），mode 臂 = G03。
- **已知近似（三条，显性登记）**：① partial 块的图检 mode 位走
  CHECK_MODE_UNSAFE（§2.8 布局无 partial 值；两值模式与 G01 备案的
  "partial|unsafe 析取"一致）；② 核按成员交错"簿记 wf + header 检查"，
  driver 先全员簿记再全员 header——仅在多缺陷块上首错次序可观察差
  （差分语料不构造多缺陷块）；③ 成员 unsafe/partial 标志与 G10 门
  （码 7，mode 臂缺失，build_vm.py:5640-5646 自证 "always safe-mode"）
  的整面交互 = **G03 差分面**——本套件语料沿 G02 惯例不带 const_meta
  （门自然闭合），safe checker 引用 unsafe 常量在核侧是
  `.other["invalid declaration, it uses unsafe declaration …"]`
  （K/type_checker.cpp:111，4.33.1 实测）。
- **oracle 通道（P1 定案）**：`Declaration.mutualDefnDecl`（4.33.1
  `Lean/Declaration.lean:191`）经 `#KDECL` 原通道直达 C++ `add_mutual`
  （`Kernel.Environment.addDecl`），**无需**前端 mutual 语法（禁用，
  elaborator 会重写成 recursor）。五条 wf 消息原文与回滚行为全部由
  4.33.1 现跑探针钉住（handoff 006 G06 节）。
- **oracle 工具链钉住**：`~/.elan/bin/lean` 随 elan default(stable) 漂到
  4.34.0（2026-09-20 实测；G02 验收跑仍是 4.33.1）。套件全部 lean 调用
  显式钉 `~/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean`
  （`run_kdecl_oracle`/`dump_env` 的 `lean_cmd` 覆盖参数，reference/ 冻结
  零改动）。elan default 是否改回 = 总控/用户裁决。
- **差分行集**（`tests/test_decl_injection_vs_lean.py` G6 节，G02_ONLY=g6）：
  W 组（wf，零图跑）dup-name / safe-block / empty / mixed-safety /
  lparams-mismatch；V 组（图跑）互引正例（成员值引用块内兄弟，两阶段
  必要性即差分点）/ 块员体检失败 → 整块拒绝 + 回滚（成员缺席 + 后继
  引用 = 码 2）/ 后继声明引用已提交块员（预注入 RAW_MUTUAL，引用方
  须自身 unsafe）/ 分发两行（thm→8、def→accept）。期望全部 oracle
  现跑。

### 16.6 CHECK 通道的 G03：unsafe-mode checker 臂（码 7 抛门的 mode 抑制）（卡 010 G03 拍，2026-09-20，代理 G）

内核依据：unsafe `add_definition` 的**头检与体检都用 unsafe-mode checker**
（`K/environment.cpp:165-169` 头检、`:172-177` 体检——先注册后检查，自引用
合法）；mutual 块同理（:236/:260 的 checker 以块 safety 构造）。抛门本体 =
`infer_constant` 在**safe-mode** checker 下遇到 unsafe/partial 常量的引用
（`K/type_checker.cpp:110-117`，核侧类别 `.other`"…it uses unsafe declaration
…"，4.33.1 实测）。`add_theorem` 恒 safe checker（:196），kind 解码与 mode
无关（§16.4 已定）。

- **mode 数据面（复核 §16.4/§16.5）**：TASK_CHECK 锚帧 E2 =
  kind + 8*mode（ENV_FORMAT §2.8）；`run_check(…, check_mode=)` 写侧。
  注入声明的 ConstantInfo 元数据（kind/safety）由 `InjectionEnv` 的
  per-cid 表经 `Encoder(const_meta=)` 进编码器（`expr/tokens.py:569-580`
  预算锚点 F2 = use_reject = IS_UNSAFE|IS_PARTIAL 析取，ENV_FORMAT §2.3）
  ——G03 前该位无数据源，门恒闭合。基环境常量不带 meta → 锚全零。
- **mode 臂（图侧 9 处 O(1) select/reglu 编辑，`build_vm.py`）**：
  ① kickoff 头检 INFER 发射 E2 = 1+8*mode（ck_mode_k 从锚帧 frE2 解码）；
  ② ck_g1_val 体检 INFER 发射 E2 = 1+8*mode（g3_mode——G02 的
  copy-forward 已把锚 E2 送到该读点）；③ INFER 派发解码
  `inf_mode = reglu(is_infer_frame, frE2 >= 8)`（mode 只搭 phase-1 值
  1→9，phase-2 比较 `ph_emit = (frE2 == 2)` 零改动）；④-⑧ 五个子发射
  继承（peel_end 脊头 / lam 域 / pi 域 / let 值 / proj 子项）；
  ⑨ 门与**降级共闸**：`ck7_gate = reglu(One - inf_mode, anc_f2 >= 1)`，
  `safety_i = const_i ∧ ck7_gate` 且 `const_i` 的降级（原 :5647 把 F2=1
  的 const 排除出推理臂）同用此闸。
- **降级共闸是实测必需（编码时抓到的坑）**：只抑抛门不抑降级时，F2=1 的
  const 既不抛也不推理，落进默认 WHNF delta 臂，自引用值自展开**无限
  循环**（探针 case 卡死实抓，handoff 006 G03 H2）。mode=1 时降级消失 →
  const 臂正常推理 A = ENV_HDR.V1（声明类型）= 核
  `instantiate_type_lparams` 语义。
- **mode=0 旧路径不变性**：legacy `kinds=None` 流每帧 E2 ∈ {0,1,2}，
  inf_mode ≡ 0 → ck7_gate ≡ `anc_f2 >= 1`（逐值还原旧合取）→ 全图所有
  新节点取值与旧图相同。实证 = guard 段（整份 check_e2e 语料
  kinds=None vs 哨兵 kind，判定/码/微步逐字相等，本拍复跑）+ 三 canary
  判定与步数基线不变。
- **已知缺口（卡 016 已清偿两条；2026-09-26 更新）**：mode 位跨 ST 续体
  交付不存活——自引用作为 **APP 参数**（I_FN→I_PI 跳）或 **lam/let
  body**（I_LAMDOM→I_LAMSORT / I_LETD 跳）到达时假拒 7（`g03g_arg_selfref`、
  `g03h_lam_selfref`，4.33.1 实测 oracle OK / 图 7@11/25 步）——**卡 016
  3-甲 已修复并摘除登记**（见 §16.7.1 载体编码）。遗留近似（仍不携带
  mode，保守侧）：pi codomain 链（I_PIS1→I_PIL1→I_PIS2→I_PIL2 与其
  body infer 发射）与 DEFEQ 链 soft 发射（帧六槽全占、F2=s_env 为位置值，
  步进编码不适用，若未来覆盖须为 DEFEQ 帧族另设计通道）。假拒方向 =
  保守侧（多拒），与 thm_imax 缺口（§16.4）同类。
- **差分行集**（`tests/test_decl_injection_vs_lean.py` G03 节，G02_ONLY=g03）：
  `g03a_selfref`（unsafe 自引用正例，两相 mode 抑制）、`g03b_later_ref` /
  `g03b2_unsafe_ref`（mode=0 抛 7 vs mode=1 放行的同语料孪生对——
  mode 位被消费的证明）、`g03c_body_fail`（体检失败 declTypeMismatch +
  整 add 回滚）、`g03e_mutual_xref`（unsafe mutual 互引，G06 两相位 +
  mode 臂叠加）、g03g/g03h（XFAIL）。oracle = `#KDECL` 现跑，unsafe 定义
  走 `_DEF_UNSAFE` 项，预注入 `RAW_G03`（`g03r_f` unsafe 自引用定义）供
  后继引用行差分表达。
- **编译与引擎**：scratch `model/step_vm_010g03_scratch.sbin`
  （--sparse；graph 26023 dims / 2901 lookups，nnz 192,867，md5
  `08bb2af7032d26fc9ace6558349e7d7b`，18,910,254 字节）；引擎对拍
  `SBIN=` 钉新件 34/34（argmax=softmax 34/34）。
- **验收通道边界（申报）**：码 7 的 mode 臂只有 Python 图 + 真 lean 差分
  通道；C++ 引擎不经过 CHECK 链（§16.4 同款边界）。码 7 引擎侧本就
  NOT-VERIFIED，不因本拍变化。

### 16.7 driver 侧 run_whnf：proj 回灌续推循环（卡 010 G04 拍，2026-09-20，代理 G2）

内核 `whnf_core` 在 proj-reduce 成功后把结果回灌继续归约
（`K/type_checker.cpp:504-508`），且对 recursor 应用先 whnf 主前提再 iota
（`K/inductive.h:93` `major = whnf(major)`；iota 结果同样回灌
`type_checker.cpp:527-533`）。图的 TASK_WHNF 顶层交付合同不变（P7.5c-2
raw-field 停止仍是稳定原语，**本拍图零改动、零重编译、零引擎跑**），续推
搬到调用方：`StepDriver.run_whnf(term_pos, max_steps=2000, max_rounds=16)`。

- **循环合同（ADR016-B 方案 B）**：每轮 = 一个完整图 TASK_WHNF
  （`init_state(pos, env)` + `_run_loop(max_steps)`，与 `run()` 同一组
  原语）；停机判定 = 焦点 `(pos, env)` 与本轮输入逐槽相同 → 返回；轮预算
  耗尽与 `max_rounds` 耗尽均抛 `TimeoutError`（同一异常类型，预算纪律复用）。
  driver 不做任何归约/语义判定（判定全在图内，不引入 Python 近似），
  只做续轮与"焦点是否前进"的比较。
- **差分行集**（`tests/test_decl_injection_vs_lean.py` G04 节，
  G02_ONLY=g04 / 交付态按族子进程）：G1/a1 五载体 11 行 + c2 直投影族
  2 行 = 13 行（nat d1/d3/d4、lst eL1/eL2/eL3、mu eG4MU1/eG4MU2、iv
  eG4IV1/eG4IV2、tree eG4W、proj g04proj_fst_redex / g04proj_fst_fst——
  直接编码的 `Proj(P2,…)` 节点载体，PProd→P2 toy 约定与 brec 套件同源），
  期望 = 真 4.33.1 `#ORACLE` WHNF 通道（`Meta.whnf`，
  `reference/lean_ref.run_oracle_mixed`）现跑逐字比对，零预置。行输出带
  `steps=`/`rounds=`（rounds 由测试侧 `_G04Drv._run_loop` 计数观测，
  run_whnf 签名未动）。实测
  12 PASS + 1 XFAIL：闭 def 载体在当前图上 raw 一轮即达 head-normal
  （009 链记录的"停 raw field"不再发生在这些形状上——合同未动，后续图
  演进吞掉了差额），循环对这些行是幂等保险（焦点不动即停）。
- **c2 实证（续推轮覆盖与负面结论，2026-09-20）**：def 载体穷尽后
  rounds≥2 无一触发（11 行全单轮）；直投影载体 g04proj_* 触发到
  round-2 停机判定分支——但注意其 round-1 的 raw 交付**同样是
  head-normal**（单轮 `run()` 到达同一字面量，`g04b_c2_probe4.log`
  RAW 行），即 round-2 是幂等停而非"补差"。结论：**当前图上不存在任何
  闭载体形状使续推轮成为语义必需**——raw 合同对一切可达闭形状都直达
  head-normal；唯一观测到"round>1 且焦点真推进"的是 IV2（env
  3599→3827，`g04b_diag.log`），其终点仍是 stuck（登记 XFAIL）。proj 两行
  的价值 = 在差额潜伏期内保持 round-2/停机判定这条路径有语料覆盖，图侧
  I_PROJ 若演进回 raw-field 交付，这两行立刻变成续推的正例。附带
  发现：universe 多态 accessor def（`PProd.fst …` 骨栈）在当前
  univ_arity=0 编码下 whnf 活锁（2000 步不 halt、4GB，
  `g04b_c2_probe1.log`；B13/WP1 编码债，非本拍范围），故 proj 载体一律
  直编 Proj 节点绕过。
- **环境最小化纪律（stage C，本拍实测定版）**：per-family 忠实 dump 闭包
  之上两条数据驱动裁剪——① theorem 的 value 置 None（kind 取自 dump
  数据，非名字分支；证明树不进这些载体的归约路径）；② toy 基底之外的
  dump extras 做传递可达闭包（种子 = carrier roots；存表
  ty/val + 递归子 rule rhs/ctor/ctors/all/induct），闭包外条目出表。
  **例外：nat/proj 族整表钉住 toy 基底**（闭包种子并入 toy 全名；proj 族
  载体的 `Nat.add` 归约走同一台需要 Nat.pred 的机件）——归约会
  动态查 ENV 里存表不可见的名字：§11.11 cs_build 的 succ 规则 rhs 即现造
  `Nat.pred t`；bisect 实测单加 `Nat.pred` 就把 d1 从卡死 @30 翻正为 @122
  （`/home/xkq/logs/010G/g04b_bisect.log`），静态闭包剪 toy 表不安全。
  其余族不得钉 toy 表：忠实 Nat.below/brecOn 大树上纯 Python 求值约
  20MB/步，iv 族（77 常量）实测烧穿 6GB 纪律线
  （`/home/xkq/logs/010G/g04b_full3.log`、`g04b_ivtrace.log`，guard rc=-9
  主动杀）。依据：probe7 全闭包 iv env 把纯 Python 求值顶到
  8.9-11.9GB RSS（违反 6GB 纪律的裸跑），stage C 后 iv 族峰值 3.8GB
  （`/home/xkq/logs/010G/g04b_diag.log`）。交付模式每族一个子进程
  （G04_FAMILY 协议），任何时刻树上只有一个大 env 求值器。
- **已知缺口（卡 016 已清偿；2026-09-26 更新）**：`g04iv_eG4IV2`（IV 索引
  剥离步交付 `Nat.casesOn (Nat.add 0 1) …` 并 HALT，主前提未 whnf，非
  head-normal；核侧 `inductive.h:93` 对 caseOn 主前提先 whnf，oracle
  4.33.1 现跑 = `LitNat(6)`）——**已修复并摘除登记**，死因两段：缺口 B =
  iv 族 stage C 闭包不含 `Nat.pred`/`Nat.rec` → `rec_ids_ok` 门压 0（环境
  纪律缺口，§16.7.2 条款 C-16.7.x-1 修复）；缺口 A = ctor 应用 major 的
  交付分类面 literal-only（语义缺口，§16.7.2 修复）。005 F7-01
  "spine-root 交付（头未 delta）"家族在本语料上的余量 = stuck major 的
  delta 头形状差（图交付原 `Nat.casesOn` spine，核侧 delta 展开为
  `Nat.rec` spine）——判定同为 stuck、语料行不触及，保持登记不在本卡。
- **验收通道边界（申报）**：`run_whnf` 是 Python 驱动器出口语义，C++
  引擎与编译通道不经过它（§16.4/§16.6 同款边界）；引擎侧 whnf 顶层交付
  合同维持 P7.5c-2 现状。

### 16.7.1 ST 续体 F2 的 checker-mode 载体编码（卡 016 拍 B 3-甲，2026-09-26）

ST 帧六槽唯一值域余量在 F2（续体 id ≤ 70）：**`ST.F2 = cont_id +
128*mode`（`MODE_STRIDE = 128`）**，mode = addDecl 的 checker safety 位
（§16.6 的 E2 通道向 ST 链的延伸）。

- **解码单点**（`build_vm.py:3207-3220` 续体门区）：`mode_st = is_st_frame ∧
  frF2 ≥ 128`、`fid = frF2 − mode_st*128`，续体门改键
  `gid(n) = (fid == n)`；`cg = gid ∧ cont_mode` 结构不变。is_st_frame 门
  是合同审计（卡 016 执行段 B3）的硬约束：DEFEQ 帧 F2 = s_env 为位置值
  （可 >128），非 ST 帧一律不得解码出 mode。
- **写侧合同（B3 审计定谳）**："ST.F2 = 续体 id（+mode 高位）"——全部
  ST 帧压帧点核查为零例外；INFER 帧 F2 = 软旗（0/1）、DEFEQ 帧 F2 =
  s_env、CHECK 锚帧 F2 = g9 链/NAT 帧 F2 = pend 项链，各有专属语义，
  均不进步进编码。
- **mode 流**：锚 E2（kind+8*mode）→ kickoff/ck_g1_val 的 INFER 发射
  （E2 = 1+8*mode，§16.6 ①②）→ INFER 派发 6 处 ST 写点
  `mid(id, inf_mode)`（I_FN/I_LAMDOM/I_PIDOM/I_LETV/I_SORTEM/IP_TY）→
  CONT 树 8 处链内 ST 写点 `mid(id, mode_st)`（I_FN→I_PI、I_PI→
  I_ARG_S/I_ARG、I_ARG→I_CHK、chk_ok→I_PI、args_walk→I_ARG_S、
  I_LAMDOM→I_LAMSORT、I_LAMSORT→I_LAMBODY、I_LETV→I_LETD）→ 三处续体
  TASK_INFER 发射 `E2 = One + reglu(mode_st, 8)`（I_PI = APP 参数
  infer、I_LAMSORT = lam body infer、I_LETD = let body infer）——
  **mode 从当前帧自身 F2 解码**，不依赖落点下方帧的拓扑（G03 H2 的
  SD-1 失效破局点）。gate 消费面（`ck7_gate` 经 `inf_mode`）零改动。
- **遗留近似（保守侧，保留登记）**：pi codomain 链
  （I_PIS1/I_PIL1/I_PIS2/I_PIL2 及其 body infer 发射）与 DEFEQ 链 soft
  发射不携带 mode；pi 域链在 I_PIDOM 入口携带、链内不续。
- **mode=0 不变性**：`fid = frF2`（逐值还原）、全部 `mid(id, 0)` 写点
  = 裸 id；实证 = g03b/g03b2 mode 孪生对与 guard/bcd/canary 全节复跑
  （卡 016 执行段 B4/B7）。

### 16.7.2 I_CASE 主前提 whnf 续推：ctor 应用 major 的规则匹配（卡 016 拍 B 2-乙，2026-09-26）

核侧合同（`K/inductive.h:77-121`）：`major = whnf(major)`（:93）后按
**whnf 后 major 的头构造子**匹配规则（:100），字段原样进 rhs（:114）。
`Nat.succ <field>` 型 major（field 为 stuck 叶）在核侧 head-normal 存活
——whnf 不入 ctor 参数、`reduce_nat` 只吃 `is_nat_lit_ext` 实参
（`is_nat_lit_ext` = `Nat.zero` 常量或字面量，`K/type_checker.cpp:637`；
succ 臂 ：704-713，实参先 whnf 再过门）——然后 succ 规则照配。图侧三件套：

1. **fire 门 decline**（NAT 帧作用域）：调用帧为 TASK_NAT 且实参为直接
   stuck 非字面量叶（Sort/FVar/MVar/Pi/T_PI_CLO/字符串 K_LIT，以及
   **无值 Const**）时 succ/pred/arity-2 op 不点火——ctor 应用经
   `const_stuck` 以**剥离态**完成 whnf（焦点 = `Const(Nat.succ)`、字段项
   = pend 顶，自带 env）。**无值 Const 判别** = cid≠0 且 env 头 `cid+1`
   位置 V2 值指针为 0（即 axiom/opaque/ctor/thm；与主机器 `const_delta`
   的 `eV2 ≥ 1` 同寻址同信号，`build_vm.py` C-scheme 头注释 ：341-343、
   decline 取值 ：782-791）——**有值 Const（def）照旧点火**：核侧 delta
   只展开有值常量（`K/type_checker.cpp:555-563` `is_delta` 门
   `info->has_value()`；`K/declaration.h:230` `has_value() =
   is_definition()`），有值 def 可 delta 归约到字面量（如
   `T_four = Nat.mul T_two T_two`）；修前把非零 Const 一律当 stuck 叶
   曾饿死 pend 臂致死 nat_hard（卡 016 修复段 F1-F4 探针定案：
   succ_delta 修前 REJECT code 1 @beat6、fire1=fire2=0，修复后 79 步
   AGREE 且与 pre-beat-B 逐值同）。BVar（walk 可解）与可归约实参照旧
   点火；非 NAT 调用者的 soft/hard 交付合同不动。
2. **交付分类面扩展**：`ctor_succ_head = 焦点 K_CONST ∧ V0 == _SUCC_CID`
   （名字扫描，铁律 3 合规）；`rec_ctor = rec_dn ∧ ctor_succ_head` 并入
   `build_r` 门（OP_REC 走既有 15 步 build：e4 LINK 链自带 rmajX，
   `<maj>` 输入 rmajV0 本就是 major 原位）；cs 侧不走平铺 build（无法
   携带字段 env，p2_ctor 教训同源）——**直接交付** `cs_ctor_r`：焦点 =
   succ minor（home env）、pend = 字段项++extras（decline 路径 pend
   未被打扰），beta 以字段项自携 env 绑定（`K/inductive.h:114` 语义）。
   `cs_stuck_r` 同步收缩（补集式）。
3. **pred 形状规则** `Nat.pred (Nat.succ X) → X`（pred 臂 dn1 拍，
   `natbad1 ∧ OP_PRED ∧ ctor_succ_head`）：核侧经 delta 展开+iota 匹配
   归约（非 reduce_nat），软硬上下文均归约——优先级在 nat_soft 之前。
   交付 = 字段项（pend 顶自携 env），弹出该项与 NAT(pred) 帧。
   `rej_n`/`em_frame` 相应扣除（该拍弹帧不拒不压）。
- **残余（登记，后续里程碑）**：minor 体含 `Nat.add <stuck> <lit>` 时
  （如 `fun n => n + 1000`），核侧 rec 展开一步给
  `Nat.succ (Nat.add k 999)`，图侧 nat-arg 门硬拒——§11.7 已登记的
  "offset/构造子 stuck 参数" 债，非本拍范围；stuck major 的 delta 头
  形状差（`Nat.casesOn` vs 展开的 `Nat.rec`）= 005 F7-01 家族余量；
  裸 `Nat.succ <无值 Const>`（如 `Nat.succ kq`，kq=axiom）在 NAT 链
  decline 后的 const_stuck 完成路径未接住（图 REJECT code 1，oracle
  钉真值 = stuck 形 `Nat.succ kq`）——卡 016 修复段 F2 探针实测
  **pre-beat-B 即同行为**（非本卡引入，三版本逐值相同），登记后续卡。
- **差分行集**：G04 `csctor` 族 3 行（`g04cs_eG4CSC` ctor-major casesOn
  直接交付 = 42、`g04cs_eG4RECC` Nat.rec build = 999、`g04cs_eG4PRED`
  pred 形状规则 = k），env 10 常量，oracle `#ORACLE` WHNF 现跑。

> **C-16.7.x 运行时现造名的闭包保留纪律**（stage C 条款，卡 016 拍 A
> memo §1.3 转正式；逐条 归约臂 file:line → 动态名 → ENV 保证方式 的
> 盘点表见 docs/decisions/023-reduction-continuation-family-memo.md §1.2 D1-D10）
> 1. 归约/推理/差分臂按名字现造节点的完整清单：`Nat.pred`、`Nat.rec`、
>    `Bool.true`、`Bool.false`、`Nat`、`String`、`String.ofList`。这些名字
>    不经过输入项的静态引用闭包；任何环境最小化（stage C）必须把清单中与
>    语料归约路径相关的名字并入闭包 frontier 种子（等价于按需 keep-toy；
>    实测：iv 族 dump 本含 `Nat.rec` 不含 `Nat.pred`——roots 与种子都要
>    补），缺名时图必须走存在计数门优雅降级（`rec_ids_ok` → stuck），禁止
>    合成伪 cid。
> 2. 差分语料若覆盖 iota succ 规则或合成名面，verifier 须先断言对应名字
>    的名字扫描存在计数 ≥1 再比对判定——否则该行的分歧定性为「环境缺失」，
>    不构成语义分歧证据。
> 3. legacy toy cid 回退维持现状三处（Bool.true/false、Nat、UnitT），
>    新臂禁止新增回退点。
> 4. `rec_ids_ok` 对 casesOn 变体的 `_REC_OK` 合取为过保守（cs_build 三步
>    只造 pred）；2-乙 实施后 cs_ctor_r 直接交付不再经 build 循环，该合取
>    维持现状（保守方向，不收窄不算错）。

### 16.8 CHECK 通道的 G8/G9：重名拒绝与重复 univ 参数（卡 011 拍 1，2026-09-21/23）

`check_constant_val`（`K/environment.cpp:127-135`）对单一声明依次跑
`check_name`（:128）→ `check_duplicated_univ_params`（:129）→
`check_no_metavar_no_fvar`（:130）→ checker。两条新臂按同一顺序接入：

- **码 11 = alreadyDeclared（driver 簿记族，不进图）**：`check_name`
  （`K/environment.cpp:102-105`）抛专用构造器 `already_declared_exception`
  （`K/kernel_exception.h:32-37` → `Kernel.Exception.alreadyDeclared`，catch
  :168-169）；Lean 侧渲染 "constant has already been declared 'n'"。图没有
  名字空间，判定由 `InjectionEnv` 注册簿记（`_names` 名→cid 表）在任何图
  体检之前完成——与码 9=mutualWF 同族（§16.5）。driver 消息镜像核文案，
  oracle 类别 alreadyDeclared ↔ 码 11。
- **码 10 = duplicate universe level parameter（图内臂）**：
  `check_duplicated_univ_params`（`K/environment.cpp:111-121`）O(n²) 成对
  比较，命中抛纯文本 `kernel_exception` → `Kernel.Exception.other`，
  oracle 类别 other ↔ 码 10。图侧载体：声明的 univ 参数名单经
  `Encoder.emit_univparams`（`expr/tokens.py`，复用 `_emit_list`
  role=2 = `ENV_LIST_UNIVPARAMS` 形状，§12.1 同款）编码为
  `T_ENV_LIST(role=2)` 链，链头写进 `TASK_CHECK` 锚帧的 **F2 槽**
  （`step_driver.run_check(lparams=…)` 第 5 参，None/0 → 臂惰性、旧路径
  逐字节不变）；cell 间以 V1 = interred nid 比较——nid 是流数据，图不暴露
  名字表（验收铁律 3）。
- **扫描臂（build_vm.py `CK_G9`=70 续体）**：resume-mode 续推循环，焦点
  A=外层 cell / B=内层 cell，每微步一对 cell 取数；耗尽（无内层）→ 外移
  下一 cell；全耗尽 → `g9_done` **代发**原 kickoff 对（帧载 V1/X/V2/E2 =
  type/value/next/kind），使 g7 的 fvar/mvar 根检（核序 :130 在 dup 扫描
  之后）**顺延**到同一 done 步——核序 name→dup-univ→fvar→checker 逐级
  保持。命中 → reject_code 链顶插 10（链序 10>7>6>5>8>4，各臂续体模式
  互斥无共射）。本轮实测：dims +76(+0.22%)/lookups +6/nnz +394(+0.17%)
  （011 scratch vs 015 基线），常数量级电路与 O(1) 预算一致。
- **verifier 行集**：`tests/test_decl_injection_vs_lean.py` section_g8
  （8 行：新名 accept ×3 kind + 重名 reject code=11 + badbody/nonprop 顺序
  行）与 section_g9（9 行：accept ×3 + `u,u` dup reject code=10 ×3 + 顺序
  行 + `g9name_lp` 证 G8 先于 G9，oracle 类别 other/alreadyDeclared 先探针
  实测再落测试）。全部 17/17 oracle 现跑 PASS（312s），引擎对拍 34/34。

### 16.9 引擎任务通道 INFER/DEFEQ/CHECK（卡 013，2026-09-21/23）

`engine/vm.cpp` 原只有 WHNF 入口；本卡把图侧已构造进权重的三任务判定
（INFER/DEFEQ/CHECK，`model/runner.py:357-398` 的 Python 实现）补齐到
C++ 引擎，判定逐例与 RefVM/runner 一致。CLI 向后兼容：第四参为数字 =
legacy WHNF（旧用法逐字不变）；为词 = 任务模式：

```
vm_run <sbin> <stream> <term_pos> <max_steps>             # WHNF（旧）
vm_run <sbin> <stream> <term_pos> <ms> infer [t_env]
vm_run <sbin> <stream> <t_pos> <ms> defeq <t_env> <s_pos> <s_env>
vm_run <sbin> <stream> <v0> <ms> check <n> <t1> <v1> <e2_1> …
vm_run <sbin> --meta-check                                # 转储 token 常量
```

- **前导帧注入**：任务模式在 STATE 前先 push 前导 `T_FRAME`（TASK_INFER=6/
  TASK_DEFEQ=7/TASK_CHECK=9，`expr/tokens.py:137-140`），字段布局与 STATE
  载荷逐字照 `runner.py`（infer 帧 E2=1、defeq 帧载 t/s 双焦点、check 帧
  逆序链 + STATE A=首声明 value 根）；`check` 的每锚 `e2` = ENV_FORMAT
  §2.8 kind 载体，0 = runner 的 legacy 全惰形状。
- **reject 通道**：主循环新读 `reject`/`reject_code` 两输出维（
  `step_driver.py:89-97` 合同），命中即发 `T_REJECT(203)` + `T_HALT(204)`
  （`expr/tokens.py:75-76`）并停止，终局打印 `REJECT <code> <focus> <env>
  <steps>`；reject 微步不发 STATE、不计步（与 Python driver 同款）。
- **发射臂补齐**：`em_raw`（6 维，raw_K 即任意 token kind，F2=0 与
  driver raw 臂不传 F2 逐字一致）、`em_link2`（6 维，同用 T_LINK）、
  `em_link` 补发 `link_flag`/`link_F2`（原硬编码 0）——发射顺序与
  `step_driver.py:145-204` 逐项对拍。
- **meta-check 防漂移**：`vm_run --meta-check` 转储 HEADER/SLOT/OUT/CONST
  （全部硬编码 token 常量 + 读到的 sbin meta），`scripts/verify_engine_tasks.py
  meta` 与 `expr/tokens.py` + sbin 尾部对拍——token 漂移由 harness 抓，
  不靠肉眼。本次证据：`OK (76 output dims, 13 token consts)`。
- **verifier**：WHNF 基线 34/34 不倒退（钉 `step_vm_015_full_scratch.sbin`）；
  三任务对拍 99/99（INFER 19 + DEFEQ 65 + CHECK 12 + SEQ 3，accept/reject/
  reject_code 三元逐例 == RefVM，540.8s）；`#KDECL` 真内核直连 12/12
  （覆盖全部可达错误类别，≥10 要求）；23 套件 canary 级 3/3 rc=0
  （engine_vs_refvm 34 例 + level×2，图侧零改动故 canary 足够，理由入
  handoff 009-K）。引擎对拍一律钉封版 sbin、禁重编（防在途图改动混入）。

## 17. 编译通道 ReGLU 钳位常数（卡 008，2026-09-15，代理 E）

编译权重通道（transformer 前向）在 FFN ReGLU 输出上钳位
`act = clamp(relu(gate)*val, ±REGLU_CLAMP)`，`REGLU_CLAMP = 1e6`。
三处镜像必须同一语义：定义在 `compiler/weights.py`（forward 与
forward_stream 两点使用），`model/runner.py` import 该定义，
`engine/vm.cpp` 为 C++ 镜像（常量定义点注释互指）。

- **动机**：非停机路径上 gate/val 同读大隐状态值时乘积可爆炸
  （旧注释例：133·133=17689），钳位是数值保护，不是语义。
- **下界（C > 一切合法读数）**：位置寄存器 F 等经乘积臂读出，值 = 流位置；
  步环每步 ≤10 token（vm.cpp 9 条件发射臂 + STATE），verify harness 预算
  3000 步 ⇒ 位置 ≤ n₀+30,001，runner 默认预算 10,000 步 ⇒ ≤ ~100,001，
  实测最大合法读数 1003（pow，1203 token 流，002-C-wp6 C5）。C=1e6 全数
  覆盖。**旧值 ±1000 曾把 pow 的 F=1003 压平到恰 1000.0，机器失步烧满
  3000 步**——这就是卡 008 修的 bug。
- **上界（C ≤ 2^24-1 = 16,777,215）**：fp32 精确整数区，`llround` 读数
  无舍入歧义，钳位值本身精确可表示。
- **一致性约束（与图语义的分歧边界）**：图侧符号求值器无钳位
  （`lean_kernel/alm_p2.py:226`）；编译通道在 |act| ≤ 1e6 区间必须与图
  语义一致，压平只允许出现在非停机垃圾路径（|act| > 1e6）。语料合法值
  不可达该区间（上界论证）。若未来需要流长 >1e6 的语料，本常数必须重访
  （ADR 013）。
- **格式语义**：常数在代码不在 sbin 字节——`compile_vm.py --sparse` 重编
  产物与晋升真值逐字节一致（卡 008 verifier）；L4SV 版本号不变。代价与
  裁决见 `docs/decisions/013-reglu-clamp-1e6.md`。
- 验收：`SBIN=<scratch 重编译> verify_engine_vs_refvm` 34/34（含 pow，
  DONE 348 步）、argmax=softmax 34/34；回归引擎套件（新 vm_run × 真值，
  pow 具名豁免）33/33。

---

## 18. 内核缓存层对齐：is_def_eq 正缓存（P1）+ whnf memo（P2，**dormant，ADR 019**）（卡 014，2026-09-17，代理 M1–M6；交付态=P1-only，§18.6）

内核在两处做 memoization，图侧本节全部对齐。这是**判定一致性的组成**
（ADR 017：有限步帽下 Timeout=判定分歧），不是性能优化。两臂各有构建期
开关（`lean_vm/build_vm.py` 模块级）：`VM014_CACHE`（P1）、
`VM014_WMEMO`（P2）；=0 时臂不构造，三态图逐字节可复现
（baseline=009 件；P1-only=a131287 件；P1+P2=本卡件
`model/step_vm_m4_scratch.sbin`，dims 26,056/lookups 2,900/nnz 193,062，
P2 增量 +71 dims/+1 lookup/+371 nnz。三态逐字节对拍实锤：M5-03 从 HEAD
源码重编三件，`cmp` 全等——scratch 零漂移、P1 态≡`step_vm_m2_scratch.sbin`、
base 态≡`step_vm_009_scratch.sbin`，原文见板 010-M M5-03 条目）。

### 18.1 内核合同与图侧对应

| 内核（`K/type_checker.cpp`） | 图侧 |
|---|---|
| `quick_is_def_eq` 查询正缓存 `succeeded_before(t,s)` :834-836（入口原对，`t==s` 之后 = 图 deq_same 之后） | `defeq_cache` 命中门（DEFEQ dispatch 拍，遮蔽 deq_gate） |
| `is_def_eq` 包装器写 `cache_success(t,s)` :1247-1252，**只在 True**（`if (r)`），写入口原对 | 写臂 `_dc_w`：dispatch-True 直提拍 ∪ pop-True 拍，发 `T_DEFCACHE`(41) |
| `whnf(e)` 入口查 `m_whnf.find(e)` :755-757；写回 :763/:766/:772 **全在归约循环完成后**（"完成才可查"）；:738-752 简单叶子不缓存（图侧允许写叶子条目——重放值相同，语义中性超集） | `whnf_cache` 命中门（WHNF 帧首拍）；写臂 `_wc_w` 发 `T_WHNFCACHE`(43) |
| 失败缓存 :953/:1042 不对称（只在 lazy_delta 同脊 args 比败处写） | **P1b 未做**（卡面登记：d6 数据证明失败臂对其无效，按合同仍欠） |

### 18.2 attention 内容检索机制（两臂共用）

缓存条目写在 raw 槽（每拍至多 1 个 token，位置 POS+1）。查询 = 单拍
LookUp，分数 `2q·v0 − v0² − BIG·clear + α·invlog`，tie_break=latest：
- **v0² 精确键分**：`reglu(v0_,v0_) = v0·ReLU(v0) = v0²`（v0≥0，单 ReGLU
  每位置），与 `fetch_by_position` 的 `2q·pos−pos²` 同款**精确 argmax**——
  这是全图第一个数据键精确检索（M1-01a 机器事实：此前全仓 fetch( 零使用）。
- `clear = persist(1−[k==本 kind])` 先折叠再乘 BIG（alm_p2 多单式陷阱）；
  两臂 kind 不同（41/43），互不串扰。
- **空缓存=确定性 miss（M6 修正，此前论证有误）**：全流 cleared 分数同落
  −BIG（ulp(1e20)≫v0²≤4096²），键项被吞后 argmax 按 tie_break=latest 落到
  **全流最新 token（典型=当拍头 STATE token），不是 position 0 的 T_NULL**。
  STATE 的 (v0,v1,v2,x,e2) 可以在帧验证字段上恒等（入口形拍强制
  SA==frV1、SB==frX，硬帧 frE2=0 对 STATE.e2=0）——M1-01b 的"首字段验证
  必败"哨兵论证只覆盖 P1 四元组且靠位置字段侥幸，P2 三元组验证在入口形
  拍上**全过**，构成 b_inc/chk/inf 族 5-6 拍空缓存假命中（§18.6）。
  **结构性修复（M6 修 (a)，两臂保留）**：`_fetch_by_v0sq` 把匹配 token 的
  kind 作为首字段返回，两臂命中门各加 `kind==T_DEFCACHE`/`kind==
  T_WHNFCACHE` 验证——命中门对非条目 token 零防御的根因闭合。
- 键遮蔽/碰撞 → 取回四元/五元组在**当拍**用 `_eq_expr` 全字段验证，败=miss
  =现行为，判定安全。P1 实测 d6 键（t_pos）遮蔽率 0；P2 键=WHNF 帧
  V1=focus pos，实测遮蔽 0（11 个 dup 全部 1 步重放，010-M M4-02d）。
- **钳位边界（编译通道）**：REGLU_CLAMP=1e6（ADR 013/§17）压平 |act|>1e6
  的 ReGLU 输出——`_v0sq` 是其一 ⇒ 位置 >1000 的键平方在**引擎/runner
  编译通道**被压平，命中可能退化 miss（=安全，见上）；Python 符号求值器
  无钳位，差分/trace 不受影响。引擎 34 例合法位置读数 ≤1003（贴界）；
  M5-03 引擎钉 P1+P2 scratch 复验 34/34 通过，钳位退化未伤判定
  （`/home/xkq/logs/014/m5_engine_scratch.log`）。
- fp32 值域：v0≤4096 序列帽 → v0²≤2²⁴，与 position_sq 同精确边缘；路由
  用精确 argmax（HYBRID_ARCH，与数值精度解耦）。

### 18.3 P1 臂（DEFEQ 正缓存）

查询：`defeq_cache = is_defeq_frame ∧ kind==T_DEFCACHE ∧ 4×_eq_expr(
(v0,v1,v2,x)==(frV1,frX,frE2,frF2))`（kind 验证=M6 修 (a)，§18.2）；
`deq_gate = reglu(is_defeq_frame, 1−defeq_cache)` 遮蔽全部
dispatch 臂（内核 quick_is_def_eq 在 core 之前返回 True，:836/:1173）；
命中提交 = deq_same 形（A=1,B=0,E=1,D=frV2）+ 写臂刷新（latest 良性）。
写臂两拍：①dispatch-True 直提 ∪ ②pop-True；**①带 busy 门**
（M2-03 活锁实锤：raw@POS+1 与同拍**活**发帧臂的 c1=POS+1/c2=POS+2 地址
算术互毁——写 token 平移后续槽位，D=c2 落进 ST(D_BIND2) 帧 → period-1
停摆）。共发拍（快判让位给体链）放弃写入=判定无损。

### 18.4 P2 臂（whnf memo）— **DORMANT（ADR 019，2026-09-17 M6）**

> **本臂自 M6 起默认关闭（`VM014_WMEMO` 默认 "0"），码保留仅供研究
> opt-in，禁止上任何验收路径**。两度根因修（(a) 命中门 kind 验证、
> (b) 写门收紧到净出口）后 string 族仍破线：spine-walk 重派拍在启动
> WHNF 帧的**同拍推进焦点**，帧 V1/X 记旧焦点 → 净出口拍把新焦点的
> 交付值写进旧焦点键（错标条目），后续合法请求重放外来值 →
> deq_oflist_true True@792→reject@336（§18.6）。判别 launch 拍焦点位移
> 的信息是跨拍的，帧 6 字段无空位——健全性需要重新设计，非修门可达；
> 全文证据与 P2 重启出路三条见 `docs/decisions/019-p2-whnf-memo-rollback.md`。
> 以下描述为 dormant 码的存档合同（含 M6 修 (a)(b) 后的形态）。

- 条目五字段：V0=focus pos（键）, V1=env 根, V2=soft flag（帧 E2）,
  X=结果 pos, E2=结果 env（raw 槽恰 5 字段全用；soft flag 入键：图侧
  soft/hard 通道可对同闭包交付不同结果，内核无此旗是通道差异非合同差）。
- 命中门 = `is_whnf_frame ∧ kind==T_WHNFCACHE（M6 修 (a)，§18.2）∧
  ¬ret_pending ∧ 入口形 (SA==frV1 ∧ SB==frX)
  ∧ 干净链 (SC==0 ∧ SF==0) ∧ 3 字段验证 ∧ ¬reject`。
  **入口形+干净链**两条款是 d6 首跑活锁修正（010-M M4-02d：mid-args-walk
  pop 回复写入口形状但 C=增长链，重放污染交付态）。D_SW2/de_prj_f/
  de_att_f 软 whnf 发射方恒置 C=0/F=0（:4216-4217），消费方 D_SW3 续读帧
  字段并重置——d6 射程不受损；spine 增长链发射的 whnf 只可能是 miss=现行为。
- 命中提交 = whnf_deliver 出口形：A=结果 pos, B=结果 env, C=SC, D=frV2,
  E=1, F=SF（六路 `_select` 加在 A2..F2 链顶）。命中拍 co-fire 的发射物
  =死垃圾：出口提交无 c1/c2 活引用、指针全绝对、kind 过滤使缓存扫描不可达。
- 写门 = 价值门：`_wc_w = is_whnf_frame ∧ (D2==frV2) ∧ ¬whnf_cache`——
  "本拍把结果交付给 caller" 由最终提交的 D2 值判定，任何 co-fire 抢走提交
  即 D2≠frV2 自动不写。**价值门自带 busy 语义**，是 18.3 陷阱的结构性
  免疫（与 P1① 的手抄 busy 掩码不同路线）。发射字段取**提交后**的
  A2/B2=交付值。命中不刷新（同键必同值：whnf 是 (pos,env,flag) 的确定
  函数，流 append-only、token 不可变、env 链根相等⟹链相等）。
- 未覆盖出口（v1 射程，与侦察探针 pop 口径一致）：wf_soft/nat_soft 型
  从 WALK/NAT 帧直接跳 caller 的软失败出口不写条目（D 不在 whnf 帧上）。

### 18.5 判定不变性与实测账（P1 验收面）

论证（详版 010-M M4-01）：条目只由真实完成的出口写；重放=同一输入的
确定函数复算；写拍在读拍之前（流序），自引用帧无己键条目；miss=现行为。
跨流只保**内容**决定，不保**位置**决定——重算会把归约链重新物化为新
token，而重放复用首次物化的规范位置（同一表达式树；实测 o1.r：重放
(573,0)=重算 (613,0)=`LitNat(5)`，板 M5-02c）。P2 专测 whnf 活性臂据此
用 `decode_closure` 内容等比较（该臂现仅研究 opt-in，§18.6）。

**验证面随 ADR 019 重划（M7 勘正）**：本节的验收账只算**交付态 =
P1-only**（基线 OFF vs P1，全判定语料）；M4/M5 时代"含 P2"的账目保留为
**历史实测**（dormant 码行为的记录，非验收证据）——尤其 M5 的 55 例
P2 不变性表（`m5_inv_p2.log`：j2/j3/j4 −6、d7 −28、d6 −58，判定点全
ON=OFF）后被 M6 证明**语料面不完整**（string/check/mutation/olean 四族
不在表内），P2 恰在未测族破线（§18.4/ADR 019）。

P1 交付账：
- M2 层：55 例 ×2 遍全 OK、steps 全 +0（该集无重复对，=现行为对照）。
- **M7 全语料层（本案合同补全）**：probe_014_invariance 覆盖
  A/Am/G/brec 55 + STR 30 + CHK 15 + MUTB 8 + MUT 8 + OE/INF 17，
  OFF vs P1 两态逐用例 verdict 字符串相等 + 步数非增
  （实跑全表原文 `/home/xkq/logs/014/m9_inv_full.log`：`=== ALL OK ===`、
  133/133 行 OK、rc=0、4782s；M6 bisect 的 7 破线例全在表内：oflist
  两条 -192 步、其余五条 +0，判定逐字=OFF，板 M9-01 终局）。
- P1 命中活性：专测 small 臂（`m7_cache_all.log`）True 例 run2 命中
  1 步 vs OFF 全量重跑；新语料首见真命中 deq_oflist_true
  True@792→True@600（−192 步、52 条目，ADR 019 背景段）。
- 步数事实与帽裁决：**d6 P1-only=1070 步收敛 halt=True**（=live
  oracle），P1+P2=1012（历史实测，memo 省 58）。d6 由此定性为**合法慢**
  （非无界环），总控终局裁决 `GRAPH_MAX_STEPS 720→1100`（步帽=Python
  求值器墙钟预算，非语义量；d4 600→720 先例，005 F8-02 线性表论证
  标准）；d6 在 1100 下转绿，G4_d6 按 KNOWN_GAPS 的 XPASS 规程摘除：
  先跑出 XPASS 证明（`m5_brec_xpproof.log`），再摘条目重跑 **12/12
  PASS、0 分歧、0 xfail**（`m5_brec_final.log`；交付态=默认图重跑由
  M7-05 全量回归复核）。
- P2 活性历史实测（dormant 码）：d6 全程（1012 步轨迹，
  whnf_result_m4_on_1500.json）writes=54、1 步重放命中 17；专测 whnf
  活性臂 18/18（`m5_cache_whnf.log`，现仅 `VM014_ALLOW_P2=1` 可跑）。
- 零回归：卡 009 套件 P1 图 0 分歧（M2 m2_brec_full.log）；专测 small
  臂 64 例 + false-repeat + d6 P1-only 臂全 OK（`m7_cache_all.log`）。

### 18.6 交付态与 P2 撤销记录（M6 执行、M7 定稿，2026-09-18）

**交付合同 = P1-only**：默认构建开关 `VM014_CACHE=1`、`VM014_WMEMO=0`
（后者默认值即回滚执行体，`lean_vm/build_vm.py:252`，M6 ROLLBACK 注释块
:238 引 ADR 019）。三态确定性（总控亲验 + M7-04 复核）：默认编译 ≡
显式 P1 编译逐字节；OFF 态（两开关全 0）编译 ≡ 卡 009 基线件
（`model/step_vm_009_scratch.sbin`）逐字节。发布图 dims/lookups/nnz
= **25,990 / 2,899 / 192,717**（=m2 件 25,985/2,899/192,691 + 修 (a)
增量 +5/0/+26；M8-03 自 HEAD c841ff1 默认开关编译
`model/step_vm_m8_scratch.sbin` 实测，`m8_compile.log`：
`graph: 25990 dims, 2899 lookups`、`build_weights(sparse): d_model=6252
heads_global=650 ffn=2704 nnz=192,717`、`schedule: 114 layers`；引擎钉件
复验 34/34 `m8_engine.log`；已登记 ARCHITECTURE 真值表）。

**P2 撤销的两机制**（全文与重启出路 = `docs/decisions/019-p2-whnf-memo-`
`rollback.md`，此处只留案底口径）：
1. 空缓存假命中：`_fetch_by_v0sq` 全 cleared 时分数同落 −BIG、
   tie_break=latest 落**当拍头 STATE token**（非本 §18.2 旧哨兵论证声称
   的 position-0 T_NULL——旧论证只覆盖 P1 四元组且靠位置字段侥幸，
   M6 修正已在 §18.2 留案，本案根因之一）。STATE 字段在入口形拍上
   恒满足 P2 三元验证 → b_inc/chk/inf 族 5-6 拍 reject。**修 (a)
   （命中门 kind 验证）保留在共享底座**：P1 由"侥幸安全"变"结构安全"。
2. spine-walk 重派错标键：派发拍同拍推进焦点、帧 V1/X 记旧焦点，净出口
   拍把新焦点的交付值写进旧焦点键 → 后续合法请求重放外来值（string 族
   True@792→reject@336）。修 (b)（写门净出口收紧）挡不住键本身错标；
   判别信息跨拍而帧无空位 ⇒ 健全性=重新设计，不在修门射程。
   **修 (b) 保留在 dormant 码内**（重启的必要非充分条件）。

**验收路径禁令**：任何差分/回归/引擎验收禁走 `VM014_WMEMO=1`；专测
whnf 相位与 d6 P1+P2 臂 = 显式 SKIP + 打印理由 + 研究 opt-in
`VM014_ALLOW_P2=1`（不许默删用例）；默认图反向断言 T_WHNFCACHE 条目
数=0（专测 d6 臂，M7 加）。d6 绿不依赖 P2：P1-only True@1070 ≤ 帽
1100（`m4_d6_p1_1500.log` 收敛实测、M5-02b 帽内复现、M7 默认态全绿）。
