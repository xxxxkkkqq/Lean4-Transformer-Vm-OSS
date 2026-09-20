# 环境/声明元数据格式（ENV_FORMAT）

本文件定义如何把真内核 `ConstantInfo` 的声明元数据编码进 token 流，使内核判定
（iota、proj、unit-like、eta 等）读取 token 字段而非硬编码常量 id。

本文是规格，不是实现。所有 `file:line` 以本地 lean4 master（版本 4.35，
`/home/xkq/lean4`）和本仓库当前状态为准；不确定处标 TBD。

当前 token 流的环境区由 `expr/tokens.py` 的 `Encoder`（`expr/tokens.py:134-177`）
建立：`T_ENV`（K=22，`expr/tokens.py:34`）的 V0=cid、V1=type root、V2=value root、
X=flags；`T_ENV_META`（K=23，`expr/tokens.py:35`）只有 V0=univ_arity。
常量表在 `reference/toy_env.py:256-318`，列表下标即 cid。
`StreamBundle` 的字段见 `expr/tokens.py:107-131`。
当前常量种类（kind）、归纳/构造子/recursor/quot 元数据都未编码，所以
`lean_vm/build_vm.py` 用硬编码 cid 判定（`build_vm.py:151-183`）。

---

## 1. 需要携带的字段（真内核来源）

### 1.1 constant_info_kind
`enum class constant_info_kind`：`declaration.h:426`。取值即枚举顺序：

| 值 | 种类 | C++ |
|---|---|---|
| 0 | Axiom | `constant_info_kind::Axiom` |
| 1 | Definition | `Definition` |
| 2 | Theorem | `Theorem` |
| 3 | Opaque | `Opaque` |
| 4 | Quot | `Quot` |
| 5 | Inductive | `Inductive` |
| 6 | Constructor | `Constructor` |
| 7 | Recursor | `Recursor` |

`constant_info::kind()` 从对象 tag 读出：`declaration.h:444`。
注意它和 `declaration_kind`（`declaration.h:201`，多一个 `MutualDefinition`）
不是同一枚举，不要混用。

### 1.2 constant_val
`declaration.h:62-72`：所有种类共有的三个字段。

| 字段 | 访问器 | 含义 |
|---|---|---|
| name | `get_name()` `declaration.h:69` | 常量名 |
| lparams | `get_lparams()` `declaration.h:70` | universe 参数名列表 |
| type | `get_type()` `declaration.h:71` | 常量类型表达式 |

token 层：name 由 cid 与 NAME 表承担；type 已在 `T_ENV.V1`；lparams 的数量即
`T_ENV_META.V0`（univ_arity，`expr/tokens.py:35`）。单个 lparams 名字本身 v1
不编码（§6 TBD，见 VM_SPEC §9.2）。

### 1.3 definition_val / reducibility_hints / definition_safety
`definition_val`：`declaration.h:104-119`。除 constant_val 外有
`value`（`get_value()` `declaration.h:115`）、`hints`（`get_hints()` `:116`）、
`safety`（`get_safety()` `:117`）、`all`（构造参数，见 `declaration.h:106`）。

`reducibility_hints`：`declaration.h:35`（枚举）/`36-47`（类）/`54`（compare）。
`reducibility_hints_kind` 取值：Opaque=0、Abbreviation=1、Regular=2
（`declaration.h:35`）。Regular 另带 definitional height（`get_height()`
`declaration.h:46`、`declaration.cpp:20-22`）。

`definition_safety`：`declaration.h:96`，取值 unsafe=0、safe=1、partial=2。
`definition_val::is_unsafe()` 即 `safety == unsafe`（`declaration.h:118`）。

token 层：value 已在 `T_ENV.V2`；hints 与 safety 新增字段（§2）。

### 1.4 axiom_val / theorem_val / opaque_val
- `axiom_val`：`declaration.h:78-90`，额外 `is_unsafe`（`is_unsafe()` `:89`）。
- `theorem_val`：`declaration.h:127-139`，额外 `value`（`get_value()` `:138`）
  和 `all`（`declaration.h:129` 构造参数）。theorem 恒 `isUnsafe=false`。
- `opaque_val`：`declaration.h:147-160`，额外 `value`（`:158`）、
  `is_unsafe`（`:159`）、`all`（构造参数 `:149`）。

token 层：value 在 `T_ENV.V2`；is_unsafe 与 all 新增字段（§2）。
`all` 的真内核注释明确说 DefinitionVal.all 不被内核使用
（`Lean/Declaration.lean:124-131`），InductiveVal.all 同理；可编码但内核判定不读。

### 1.5 inductive_val
`declaration.h:291-309`（Lean 侧对应 `Lean/Declaration.lean:261-302`）。

| 字段 | 访问器 | 含义 |
|---|---|---|
| nparams | `get_nparams()` `declaration.h:300` | 参数个数（固定于各构造子） |
| nindices | `get_nindices()` `:301` | index 个数（随构造子变化） |
| all | `get_all()` `:302` | 互递归块内全部归纳类型名 |
| cnstrs | `get_cnstrs()` `:303` | 该归纳类型的构造子名列表 |
| ncnstrs | `get_ncnstrs()` `:304` | `length(cnstrs)`，派生 |
| nnested | `get_nnested()` `:305` | 嵌套辅助类型数 |
| isRec | `is_rec()` `:306` | 是否递归 |
| isUnsafe | `is_unsafe()` `:307` | 是否 unsafe |
| isReflexive | `is_reflexive()` `:308` | 是否 reflexive |

### 1.6 constructor_val
`declaration.h:319-332`（Lean 侧 `Lean/Declaration.lean:328-338`）。

| 字段 | 访问器 | 含义 |
|---|---|---|
| induct | `get_induct()` `declaration.h:327` | 所属归纳类型名 |
| cidx | `get_cidx()` `:328` | 构造子下标（声明顺序，0 起） |
| nparams | `get_nparams()` `:329` | 所属归纳类型的参数个数 |
| nfields | `get_nfields()` `:330` | 字段数（arity − nparams） |
| isUnsafe | `is_unsafe()` `:331` | 是否 unsafe |

### 1.7 recursor_val / recursor_rule / major_idx
`recursor_val`：`declaration.h:365-386`（Lean 侧 `Lean/Declaration.lean:357-389`）。

| 字段 | 访问器 | 含义 |
|---|---|---|
| all | `get_all()` `declaration.h:377` | 生成此 recursor 的归纳类型名 |
| nparams | `get_nparams()` `:378` | 参数个数 |
| nindices | `get_nindices()` `:379` | index 个数 |
| nmotives | `get_nmotives()` `:380` | motive 个数 |
| nminors | `get_nminors()` `:381` | minor premise 个数 |
| rules | `get_rules()` `:383` | 每个构造子一条归约规则 |
| k | `is_k()` `:384` | 是否支持 K-like 归约 |
| isUnsafe | `is_unsafe()` `:385` | 是否 unsafe |

`major_idx` 公式在 `declaration.h:382`：
`get_major_idx() = nparams + nmotives + nminors + nindices`。
`declaration.cpp:145-154`（`get_major_induct`）按此数目沿 `binding_body` 下行，
再取 `binding_domain` 的 app head 作为 major 归纳类型名。注意该函数是公式的使用点，
公式本体在头文件。Lean 侧等价实现：`Lean/Declaration.lean:394-409`。

`recursor_rule`：`declaration.h:340-350`（Lean 侧 `Lean/Declaration.lean:348-355`）。

| 字段 | 访问器 | 含义 |
|---|---|---|
| ctor | `get_cnstr()` `declaration.h:347` | 该规则匹配的构造子名 |
| nfields | `get_nfields()` `:348` | 字段数（不含归纳参数） |
| rhs | `get_rhs()` `:349` | 归约右端表达式 |

### 1.8 quot_val
`quot_val`：`declaration.h:388-412`（Lean 侧 `Lean/Declaration.lean:411-425`）。
`quot_kind` 枚举在 `declaration.h:388`：Type=0、Mk=1、Lift=2、Ind=3；
访问器 `get_quot_kind()` `declaration.h:411`。

### 1.9 环境查询 API（验收与导出用）
- `environment::find`：`environment.h:91` / `environment.cpp:74`，
  `environment::get`：`environment.h:94` / `environment.cpp:78`。
- `environment::add_core`：`environment.cpp:144`；`add_inductive`：`environment.h:74`。
- `environment::for_each_constant`：`environment.h:100` / `environment.cpp:303`。
- Lean 侧：`Environment.find?` `src/Lean/Environment.lean:283`，
  `ConstantInfo` `src/Lean/Declaration.lean:430-439`。

---

## 2. 编码方案

### 2.1 token 格式与现有编号
token 为 7 字段 `(K, V0, V1, V2, X, E2, F2)`（VM_SPEC §2，`docs/VM_SPEC.md:55-57`）。
K 取值域 1..255，其余字段 0..4095（VM_SPEC `docs/VM_SPEC.md:48-53`）。
`expr/tokens.py` 现有编号：

| K | 名称 | 位置 |
|---|---|---|
| 1..12 | K_BVAR..K_PROJ | `expr/model.py:48-59` |
| 13 | T_LIT_DIG | `expr/tokens.py:28` |
| 21 | T_NAME | `expr/tokens.py:33` |
| 22 | T_ENV | `expr/tokens.py:34` |
| 23 | T_ENV_META | `expr/tokens.py:35` |
| 30 | T_PEND | `expr/tokens.py:36` |
| 31 | T_LINK | `expr/tokens.py:37` |
| 32 | T_FRAME | `expr/tokens.py:38` |
| 33 | T_STATE | `expr/tokens.py:39` |
| 34 | T_PI_CLO | `expr/tokens.py:40` |
| 40 | T_LIT_BYTE | `expr/tokens.py:33`（WP5 字符串字节链，见 §2.2） |
| 41..43 | T_DEFCACHE/T_DEFFAIL/T_WHNFCACHE | `expr/tokens.py:51,59,65`（卡 014 缓存层流内条目，见 §2.2；发射态：**41=发射**（P1 默认交付）、**42=预留未发射**（P1b 欠账）、**43=dormant**（P2 默认关，ADR 019）） |
| 201..204 | T_OUT_VAL/T_ACCEPT/T_REJECT/T_HALT | `expr/tokens.py:44-47` |

空闲段：14–20、24–29、35–200、205–255。

### 2.2 新编号分配规则
新增 kind 一律取 24–29、然后 35–38 中最小的未占用值；保留 30–34（机器/表达式
专用）与 201–204（输出）不动。已分配编号不得重排。本文分配：

| K | 名称 | 用途 |
|---|---|---|
| 24 | T_ENV_DEFVAL | definition 的 hints/safety/all |
| 25 | T_ENV_SIMPLEVAL | axiom/theorem/opaque 的 is_unsafe/all |
| 26 | T_ENV_INDVAL | inductive 标量 |
| 27 | T_ENV_CTORVAL | constructor 标量 |
| 28 | T_ENV_RECVAL | recursor 标量 |
| 29 | T_ENV_RULE | 单条 recursor rule |
| 35 | T_ENV_LIST | 名字列表节点（all/ctors） |
| 36 | T_ENV_QUOTVAL | quot_kind |
| 37 | T_ENV_INDEXTRA | inductive 的列表头 |
| 38 | T_ENV_RECEXTRA | recursor 的列表/规则头 |
| 39 | T_ENV_UNIVPARAMS | 常量 lparams 名字链头（WP2，见 `docs/VM_SPEC.md` §12.1；预留，不改变已分配编号） |
| 40 | T_LIT_BYTE | 字符串字面量字节链元素（`expr/tokens.py:33`，`docs/VM_SPEC.md` §14.1）。表达式侧 kind，非 ENV 元数据；24–29/35–38 已满，取空闲段 35–200 的最小可用值 40（§14.6 第 1 条的决议，见 `docs/VM_SPEC.md` §14.7）。V0=字节 0..255，V2=K_LIT 链头，步幅 2 同 `T_LIT_DIG` |
| 41 | T_DEFCACHE | 卡 014 P1：is_def_eq 正缓存条目（流内机器 kind，非 ENV 元数据，`expr/tokens.py:51`，合同见 `docs/VM_SPEC.md` §18.3）。**发射态 = 交付图在用**（默认 `VM014_CACHE=1`）。raw 槽单拍写入，V0=t_pos（attention 键）, V1=t_env, V2=s_pos, X=s_env, E2=0 |
| 42 | T_DEFFAIL | 卡 014 P1b 预留：is_def_eq 失败缓存条目（内核 :1042 不对称；**未发射**=预留态，`expr/tokens.py:59`，VM_SPEC §18.1 登记欠账） |
| 43 | T_WHNFCACHE | 卡 014 P2：whnf memo 条目（流内机器 kind，`expr/tokens.py:65`，合同见 `docs/VM_SPEC.md` §18.4）。**发射态 = DORMANT**：P2 于 M6 回滚为默认关闭（`VM014_WMEMO` 默认 "0"，ADR 019），交付图零 kind-43 条目（专测反向断言在案）；仅研究显式 opt-in 下臂才构造、才发射。raw 槽五字段全用：V0=focus pos（键）, V1=env 根, V2=soft flag, X=结果 pos, E2=结果 env |

### 2.3 T_ENV_META 扩展为元数据锚点
`T_ENV`（K=22）字段不变。`T_ENV_META`（K=23，`expr/tokens.py:35`）扩展：

| 字段 | 含义 | 取值 |
|---|---|---|
| V0 | univ_arity（lparams 个数） | 0..4095，语义不变 |
| V1 | constant_info_kind | 0..7（§1.1） |
| V2 | meta_head：该 cid 第一个专用元数据 token 位置 | 0=无 |
| X | flags 位域 | 见下 |
| E2 | 保留 | 0 |
| F2 | use_reject（WP7-G10）：definition safety ∈ {unsafe, partial}（flags 位 5 或 9）时编码期预算 1，否则 0 | 0/1 |

WP7-G10：内核在 `infer_constant` 拒绝 safe 上下文引用 unsafe/partial 常量
（`K/type_checker.cpp:110-117`），但 flags 位测试无法在图内一步 select 展开，
改由编码器（`expr/tokens.py` 锚点写入处）预算成 F2；图侧 INFER 的 const 臂读
锚点 F2 即得门控值，legacy 流（无元数据）F2 恒 0=门不启用（数据缺失，不是
名字/cid 分支，验收铁律 3）。4.33.1 实测：`partial def`  elaborate 后本体存为
`opaqueInfo`（无 safety 字段），真正带 safety=partial 的是编译器生成的
`<name>._unsafe_rec` 影子常量（toolchain `Lean/Elab/PreDefinition/Main.lean:20-37`
`Basic.lean:280-296`、`Lean/Compiler/Old.lean:47-48`），dump 元数据会如实带上
（差分 `tests/test_defeq_branches_vs_lean.py` g10 三例钉住）。

WP7-G5：声明通道约定「CHECK 帧 X 字段（= 声明 value 根，由 ENV_HDR.V2 拷贝）
为 0 表示该声明无 value（axiom 形态，`K/declaration.h` axiom_val 无 value
字段）」；图在 ensure_sort 成功后据此跳过 value-infer/defeq 直接推进或验收
（`K/environment.cpp:152-158` add_axiom 只做 check_constant_val）。ENV_HDR
本体不变。

X 位域（低 10 位，0..1023）：

| 位 | 含义 |
|---|---|
| 0 | has_value（definition/theorem/opaque 有 value） |
| 1 | is_constructor |
| 2 | is_inductive |
| 3 | is_recursor |
| 4 | is_quot |
| 5 | is_unsafe（全种类共用） |
| 6 | is_rec（inductive） |
| 7 | is_reflexive（inductive） |
| 8 | is_k（recursor） |
| 9 | is_partial（definition safety==partial） |

位 0–3 与现有 `ENV_F_*`（`expr/tokens.py:50-53`）一致，避免两套语义。

### 2.4 专用元数据 token 逐字段
同一个 cid 的元数据 token 通过 `F2 = next_meta` 串成单链表（0 结束），
链表头为 `T_ENV_META.V2`。`cid` 字段为 token 层常量 id；核对的
`induct`/`ctor` 名在 token 层用 cid 表示（每个常量都有 cid），
列表成员用 nid（NAME 表，`T_NAME` `expr/tokens.py:33`）。

| K | 名称 | V0 | V1 | V2 | X | E2 | F2 |
|---|---|---|---|---|---|---|---|
| 24 | T_ENV_DEFVAL | cid | hints_kind 0..2 | hints_height 0..4095 | safety 0..2 | all_list_head | next_meta |
| 25 | T_ENV_SIMPLEVAL | cid | is_unsafe 0/1 | all_list_head | 0 | 0 | next_meta |
| 26 | T_ENV_INDVAL | cid | nparams | nindices | nnested | 0 | next_meta |
| 27 | T_ENV_CTORVAL | cid | induct_cid | cidx | nparams | nfields | next_meta |
| 28 | T_ENV_RECVAL | cid | nparams | nindices | nmotives | nminors | next_meta |
| 29 | T_ENV_RULE | rec_cid | ctor_cid | nfields | rhs_root_pos | 0 | next_rule |
| 35 | T_ENV_LIST | owner_cid | nid | role 0=all,1=ctors | next_node | 0 | 0 |
| 36 | T_ENV_QUOTVAL | cid | quot_kind 0..3 | 0 | 0 | 0 | next_meta |
| 37 | T_ENV_INDEXTRA | cid | all_list_head | ctors_list_head | 0 | 0 | next_meta |
| 38 | T_ENV_RECEXTRA | cid | all_list_head | rules_head | 0 | 0 | next_meta |

说明：
- is_unsafe、is_rec、is_reflexive、is_k 放在 `T_ENV_META.X`，不重复进专用 token。
- `T_ENV_CTORVAL.V2 = cidx` 必须取自真内核的构造子声明顺序，不能取常量表顺序
  （见 §3 Bool 例）。
- `all` 列表是 `T_ENV_LIST` 链（role=0），头在 DEFVAL/SIMPLEVAL/INDEXTRA/RECEXTRA；
  ctors 列表为 role=1，头在 INDEXTRA.V2；lparams 名字列表为 role=2（WP2，见
  `docs/VM_SPEC.md` §12.1），头在 T_ENV_UNIVPARAMS(V2)。
- hints_height 超过 4095 时的编码未定（TBD，§6）。

### 2.5 枚举取值

| 枚举 | 值 | 来源 |
|---|---|---|
| constant_info_kind | 0 Axiom,1 Definition,2 Theorem,3 Opaque,4 Quot,5 Inductive,6 Constructor,7 Recursor | `declaration.h:426` |
| reducibility_hints_kind | 0 Opaque,1 Abbreviation,2 Regular | `declaration.h:35` |
| definition_safety | 0 unsafe,1 safe,2 partial | `declaration.h:96` |
| quot_kind | 0 Type,1 Mk,2 Lift,3 Ind | `declaration.h:388` |

### 2.6 规则表（recursor rules）编码
每个 rule 一个 `T_ENV_RULE`（K=29）token：
`V0=rec_cid`、`V1=ctor_cid`、`V2=nfields`、`X=rhs 树根位置`、`F2=下一条 rule
位置`（0 结束）。规则链头在 `T_ENV_RECEXTRA.V2`。rule 顺序必须与
`InductiveVal.ctors` 的声明顺序一致（即与构造子 `cidx` 递增一致），因为
iota 的 minor premise 按此顺序选取。rhs 按 §4 的表达式编码追加，其父指针
指向该 rhs 根。

### 2.7 流布局
为保持现有按位置寻址（`ENV_HDR` 在 `cid+1`，`build_vm.py:194-195`），
`T_ENV` 头块位置 1..n 不变；`T_ENV_META` 锚点改为连续块：

```
pos 0                 T_NULL，V0 = n_consts（原为全 0，新增字段）
pos 1 .. n            T_ENV 头块，每 cid 一个（布局不变）
pos n+1 .. 2n         T_ENV_META 锚点块，anchor(cid) = n+1+cid
pos 2n+1 ..           NAME 表（T_NAME）
之后                  type/value 树（根记在头块 V1/V2）
之后                  专用元数据 token（24..28、36..38）
之后                  T_ENV_RULE（29）链
之后                  T_ENV_LIST（35）节点
之后                  证明树 / 目标树 / 工作区
```

`anchor(cid)` 与 `cid+1` 都是 O(1) 位置寻址：
VM 从 `T_NULL.V0` 得 n，再读 `anchor(cid)` 得 V1（kind）、V2（meta_head）、
X（flags），沿 V2/F2 链取专用字段。这与现有 `fetch_by_position`
（`lean_vm/build_vm.py:48` 导入，`:194` 使用）机制一致。

实现上需要把 `Encoder` 现在在每常量树后立即 push 的 `T_ENV_META`
（`expr/tokens.py:172`）改为在头块之后集中 emit。这是位置变化，不是语义变化：
`reference/ref_vm.py` 读的是 `StreamBundle` 的 Python dict（`const_type_pos` 等，
`expr/tokens.py:115-119`），不依赖 `T_ENV_META` 位置；`build_vm.py` 目前不读
`T_ENV_META`。header 块位置不变，故对现有图无影响。

### 2.8 CHECK 锚帧 E2：声明 kind / checker mode 载体（卡 010 G02）

内核按声明种类分派 `add_axiom` / `add_definition` / `add_theorem` /
`add_opaque`（`K/environment.cpp:271-284`），且**只有** `add_theorem` 跑
`is_prop(type)`（`:200-202`）。图侧从锚帧本身分不出这四种，所以种类必须
作为**数据**随声明进入（验收铁律 3：不许按常量名/cid 写分支）。载体 =
`TASK_CHECK` 锚帧的 E2 槽（六槽里唯一未被 CHECK 链占用的；裁决与被拒方案见
`docs/decisions/020-injection-carrier-and-level-test.md`）。

```
E2 = kind_code + CHECK_E2_STRIDE * check_mode_code      CHECK_E2_STRIDE = 8
```

| kind_code | 含义 | 图侧效果 |
|---|---|---|
| 0 | unspecified（`kinds=None` 旧路径写的值） | 所有 kind 闸门**完全失效**，行为与卡 010 之前逐字相同 |
| 1 | axiom | 不触 is_prop 闸门（`environment.cpp:152-158` 只跑 check_constant_val） |
| 2 | definition | 同上（`:160-190`） |
| 3 | theorem | 触 CK_G1 的 is_prop 闸门 → 非 Prop 即拒码 8 |
| 4 | opaque | 不触闸门（`:211-223`） |

| check_mode_code | 含义 | 图侧效果 |
|---|---|---|
| 0 | safe checker（旧默认） | 现行行为 |
| 1 | unsafe checker（先注册后检查） | **卡 010 G03 已接**：mode 位随 CHECK 锚帧 E2 进图，经 INFER 帧下行（E2=1+8*mode，`inf_mode` 解码），抑制 G10 抛门与 const 降级共闸 `ck7_gate`（核侧 unsafe checker 不抛 unsafe-use，K/type_checker.cpp:110-117）；mode 位跨 ST 续体交付不存活（APP 参数 / lam·let body 自引用假拒 7 = VM_SPEC §16.6 已知缺口） |

解码规则（读侧 `lean_vm/build_vm.py` 的 `CHECK_*` 常量，写侧
`lean_vm/step_driver.check_e2()`）：`mode = (E2 >= 8)`，`kind = E2 - 8*mode`。
kind 判定**与 mode 无关**——`add_theorem` 恒用 safe checker
（`environment.cpp:196` 的 `type_checker checker(*this, diag.get())`），
所以 is_prop 闸门在 mode=1 时同样必须生效。
两份常量分别住在读写两侧（`expr/tokens.py` 被卡 010 的文件所有权表冻结，
不放共享常量模块），漂移由 `tests/test_decl_injection_vs_lean.py` 的 a0 段
逐常量对拍。

取值越界（kind>4、mode>1、非 int）由 `check_e2()` 抛 `ValueError`，不静默写入。

空闲性不是声明出来的，是实证的：`tests/test_decl_injection_vs_lean.py` 的
`guard` 段在**整份 `test_check_e2e` 语料**上比较 `kinds=None` 与
`kinds=[1]`（非零、且闸门不看的哨兵 kind）的判定/错误码/微步数，要求逐字相等；
该件同时在图未改动的快照上跑过一次（证据见 `docs/handoffs/006-G-injection.md`
G02 S1 心跳）。禁止用 `T_NULL`（位置 0）的任何字段当新载体——那是 null 哨兵
（`build_vm.py:289` 自注，另有 `:614/:849/:948/:1012` 以可能为 0 的指针读 X）。

---

## 3. 贯穿示例

cid 取 `reference/toy_env.py:256-318` 的 `TOY_CONSTS` 列表下标。
期望的 kind/标量取真 lean 4.33.1 的 `Environment.find?` 输出（本文实际运行
`#CI` dump 得到，见 §5.2）。

相关 cid：Nat=0、Bool=1、Bool.true=2、Bool.false=3、Nat.zero=4、Nat.succ=5、
P2=17、P2.mk=18、Nat.rec=27、Nat.casesOn=30、P2.casesOn=31、Bool.casesOn=32。
设 n=35（TOY_CONSTS 长度）。

### 3.1 Nat（cid 0）
真值：kind=Inductive，nparams=0、nindices=0、nnested=0、isRec=true、
isUnsafe=false、isReflexive=false、ctors=[Nat.zero, Nat.succ]、all=[Nat]。

- `pos 1`：`T_ENV`(22, V0=0, V1=type_root, V2=0, X=0)。
- `anchor(0)=36`：`T_ENV_META`(23, V0=0(univ_arity), V1=5, V2=meta_head,
  X = bit2|bit6 = 4|64 = 68)。
- `T_ENV_INDVAL`(26, V0=0, V1=0, V2=0, X=0(nnested), F2=next)。
- `T_ENV_INDEXTRA`(37, V0=0, V1=all_head, V2=ctors_head, F2=0)。
- `T_ENV_LIST`(35, V0=0, V1=nid("Nat"), V2=0(all), X=0)。
- ctors 链：`T_ENV_LIST`(35, V0=0, V1=nid("Nat.zero"), V2=1) →
  `T_ENV_LIST`(35, V0=0, V1=nid("Nat.succ"), V2=1, X=0)。

### 3.2 Nat.zero（cid 4）、Nat.succ（cid 5）
真值：Nat.zero cidx=0 nfields=0；Nat.succ cidx=1 nfields=1。

- Nat.zero：`T_ENV_META`(23, V1=6, X=bit1=2)；
  `T_ENV_CTORVAL`(27, V0=4, V1=0(induct_cid=NAT), V2=0(cidx), X=0(nparams),
  E2=0(nfields), F2=0)。
- Nat.succ：`T_ENV_META`(23, V1=6, X=bit1=2)；
  `T_ENV_CTORVAL`(27, V0=5, V1=0, V2=1, X=0, E2=1, F2=0)。

### 3.3 Nat.rec（cid 27）
真值：kind=Recursor，nparams=0、nindices=0、nmotives=1、nminors=2、k=false、
isUnsafe=false，rules=[(Nat.zero,0),(Nat.succ,1)]，major_idx=3，
major_induct=Nat，levelParams=1（univ 多态，toy 用 univ_arity=0 代替）。

- `T_ENV_META`(23, V0=0, V1=7, V2=meta_head, X=bit3=8)。
- `T_ENV_RECVAL`(28, V0=27, V1=0, V2=0, X=1(nmotives), E2=2(nminors),
  F2=next)。
- `T_ENV_RECEXTRA`(38, V0=27, V1=all_head([Nat]), V2=rule1_pos, F2=0)。
- `T_ENV_RULE`(29, V0=27, V1=4(Nat.zero), V2=0(nfields), X=rhs1_root,
  F2=rule2_pos)。
- `T_ENV_RULE`(29, V0=27, V1=5(Nat.succ), V2=1(nfields), X=rhs2_root, F2=0)。
- major_idx = nparams+nmotives+nminors+nindices = 0+1+2+0 = 3。

### 3.4 Nat.succ（见 3.2，构造子）。

### 3.5 Nat.casesOn（cid 30）
真 lean 4.33.1 中 `Nat.casesOn` 是 **Definition**（`defnInfo`，hints=abbreviation，
safety=safe，all=[Nat.casesOn]），不是 Recursor——`Nat.rec` 才是 `recInfo`。
所以真值编码为：

- `T_ENV_META`(23, V0=0, V1=1(Definition), V2=meta_head,
  X=bit0 has_value），
- `T_ENV_DEFVAL`(24, V0=30, V1=1(abbrev), V2=hints_height, X=1(safe),
  E2=all_head, F2=0)。

注意：toy 环境把 `Nat.casesOn` 当作类 recursor 常量并让
`build_vm.py` 用 `CID_CASESON_NAT=30` 硬编码 dispatch（`build_vm.py:104`）。
迁移期两者要分开处理（§4，§6 TBD）。

### 3.6 Bool（cid 1）、Bool.false（cid 3）、Bool.true（cid 2）
真值：Bool kind=Inductive，nparams=0、nindices=0、nnested=0、isRec=false、
isReflexive=false，ctors=[**Bool.false, Bool.true**]；Bool.false cidx=0
nfields=0；Bool.true cidx=1 nfields=0。

- `T_ENV_META`(23, V0=0, V1=5, X=bit2=4)。
- `T_ENV_INDVAL`(26, V0=1, V1=0, V2=0, X=0, F2=next)。
- `T_ENV_INDEXTRA`(37, V0=1, V1=all_head([Bool]), V2=ctors_head)。
- ctors 链顺序 **false 在前**：`T_ENV_LIST`(V1=nid("Bool.false"),V2=1) →
  `T_ENV_LIST`(V1=nid("Bool.true"),V2=1)。
- Bool.false：`T_ENV_CTORVAL`(27, V0=3, V1=1(induct_cid=Bool), V2=0(cidx),
  X=0, E2=0)。
- Bool.true：`T_ENV_CTORVAL`(27, V0=2, V1=1, V2=1(cidx), X=0, E2=0)。

要点：`TOY_CONSTS` 里 Bool.true(cid 2) 排在 Bool.false(cid 3) 之前
（`reference/toy_env.py:259-260`），但真内核 cidx 是 false=0、true=1。
因此 `V2=cidx` 与 ctors 列表顺序都必须按真值写，不能按常量表顺序。
`build_vm.py:83` 的 `CID_TRUE, CID_FALSE = 2, 3` 是常量表顺序，与 cidx 无关。

### 3.7 P2（cid 17）、P2.mk（cid 18）
真值：P2 kind=Inductive，nparams=0、nindices=0、nnested=0、isRec=false、
isReflexive=false，ctors=[P2.mk]；P2.mk cidx=0、nparams=0、nfields=2。

- `T_ENV_META`(23, V0=0, V1=5, X=bit2=4)。
- `T_ENV_INDVAL`(26, V0=17, V1=0, V2=0, X=0)。
- `T_ENV_INDEXTRA`(37, V0=17, V1=all_head, V2=ctors_head)。
- `T_ENV_CTORVAL`(27, V0=18, V1=17(induct_cid=P2), V2=0(cidx), X=0(nparams),
  E2=2(nfields))。

---

## 4. 兼容与迁移

### 4.1 不破坏现有语义的加入方式
1. `T_ENV`(K=22) 字段不变；header 块位置 1..n 不变，`cid+1` 寻址不变。
2. 只扩展 `T_ENV_META`(K=23) 已存在但未用的 V1/V2/X（现在 V1=V2=X=0）；
   旧读者仍可只读 V0。
3. 新 token kind 取空闲编号，不重排 1..13/21..34/201..204。
4. `T_NULL`(pos 0) 的 V0 由 0 改为 n_consts，只有新增读取方使用。
5. `StreamBundle` 可新增 `const_kind`、`const_meta_pos`、`const_meta` 等 dict，
   现有字段（`expr/tokens.py:115-119`）保留，`reference/ref_vm.py` 无需改。
6. `Encoder.__init__` 增加可选参数（如 `const_meta`），默认行为不变。

### 4.2 硬编码 cid 的替换路径
`lean_vm/build_vm.py:83-115` 现有硬编码：

| 行 | 常量 | 值 | 替换来源 |
|---|---|---|---|
| 83 | CID_TRUE, CID_FALSE, CID_ZERO | 2,3,4 | T_ENV_CTORVAL（按 induct_cid 与 cidx）或构造期按名查 cids |
| 84 | CID_NAT, CID_SUCC | 0,5 | T_ENV_INDVAL / T_ENV_CTORVAL |
| 85 | CID_PRED, CID_REC | 6,27 | T_ENV_META.V1（Definition/Recursor）+ T_ENV_RECVAL |
| 90 | CID_P2MK | 18 | T_ENV_CTORVAL（nfields，且 induct_cid∈P2） |
| 93 | NID_P2 | 18 | NAME 表由 nid 反查，或 T_ENV_INDVAL |
| 96 | CID_P2 | 17 | T_ENV_INDVAL |
| 100 | CID_UNITT | 28 | T_ENV_INDVAL（isRec=false）+ T_ENV_CTORVAL（nfields=0） |
| 104 | CID_CASESON_NAT | 30 | 见 §4.3 |
| 107 | CID_CASESON_P2 | 31 | 见 §4.3 |
| 112 | CID_CASESON_BOOL | 32 | 见 §4.3 |

替换分三步，每步可独立验证：
1. 图构造期把常量移到模块级 dict，值由 `bundle.cids[name]` 得到；图的
   数据依赖语义不变（仍编译进权重）。
2. 图运行期改为读 `anchor(cid)` 的 `T_ENV_META` 与专用 token，iota/proj/
   unit-like 的判定条件从 "cid == 常量" 改为 "kind/flags/标量" 匹配。
   位置读取复用 `fetch_by_position`（`build_vm.py:194-195` 的 `cid+1` 先例）。
3. 删除按名/按序的 cid 假设，使图能处理 `import_env` 追加的任意常量
   （`reference/olean_export.py:579-594`）。

`ENV_HDR.X` 的 nat-op/casesOn 操作码（`expr/tokens.py:129-147`，
`build_vm.py:100-106`）在迁移期保留；最终可由 `T_ENV_META.V1` +
`T_ENV_DEFVAL`/`T_ENV_RECVAL` 取代。编码值占用情况：1–10 = Nat 算术 op
（`NAT_OP_CODES`），11 = Nat.rec 分发，12/13/14 = casesOn 分发（15 已废弃，
16/17 = `CTOR_ID_CODES` Bool 构造子句柄）。WP5 新增字符串字面量句柄
`String.ofList=18`、`String=19`（`STR_ID_CODES`，`expr/tokens.py:168`；
`expr/tokens.py` 头部按名写入 `ENV_HDR.X`，`build_vm.py` 的 cid 扫描窗
`_NSCAN=96`（`build_vm.py:267`）内发现；任一缺名则对应转换臂恒不点火、
字面量 `X=0`，见 `docs/VM_SPEC.md` §14.7）。WP6-F 新增位运算/算术 op
`Nat.gcd=20, Nat.land=21, Nat.lor=22, Nat.xor=23, Nat.shiftLeft=24,
Nat.shiftRight=25`（`NAT_OP_CODES` 扩表，`docs/VM_SPEC.md` §15；走同一
`_SCAN_OPS` 名字扫描，无硬编码 cid；15-19 被占用/废弃故从 20 起）。

### 4.3 casesOn 的特殊处理
真内核里 `Nat.casesOn` / `Bool.casesOn` / `P2.casesOn` 都是
`defnInfo`（abbreviation，见 §3.5），没有 `RecursorVal`。toy 环境把它们建成
类 recursor 常量并由图硬编码 dispatch。迁移有两种选择，需实现时确认（TBD）：
(a) 编码真 kind（Definition），图改为对 abbrev 做 delta 展开；
(b) toy 保留显式 dispatch，仅把 cid 来源改为按名。
不建议给它们伪造 RecursorVal，否则 token 流与真内核环境不一致。

---

## 5. 验收测试方案

### 5.1 编码→解码 round-trip（逐字段）
新增解码函数（建议放 `expr/tokens.py`）：`decode_env_meta(bundle, cid) -> dict`，
读取 `anchor(cid)`、沿链取全部专用 token，返回与 §2.4 字段一一对应的 dict。

测试项：
1. 对 `TOY_CONSTS` 每个 cid：`encode -> decode_env_meta`，逐字段与手写期望表比较。
2. 幂等：`encode -> decode -> encode` 两个 stream 的元数据区相同。
3. 交叉核对 `StreamBundle`：`const_type_pos`/`const_value_pos`
   （`expr/tokens.py:115-116`）与 `T_ENV.V1/V2` 一致。
4. 不变量：`major_idx == nparams+nmotives+nminors+nindices`；rule 顺序的
   `ctor_cid` 序列与 inductival 的 ctors 列表（cidx 递增）一致；
   Bool 的 rules/ctors 顺序是 false 先、true 后。

### 5.2 期望值来源：真 Lean Environment / ConstantInfo
期望值不得手写猜测，必须从真 lean 二进制的 `Environment.find?` +
`ConstantInfo` 产生。现有导出管道可复用并扩展：
`reference/olean_export.py` 的 `DUMP_TEMPLATE`（`:50-146`）已用
`env.find?` 和 `.inductInfo`/`.ctorInfo`/`.recInfo` 的分类（`:116-138`）；
把 `InductiveVal`、`ConstructorVal`、`RecursorVal`、`DefinitionVal` 的全部字段
（`src/Lean/Declaration.lean:261-389`）加进 DUMPCONST JSON，
`dump_env`（`reference/olean_export.py:153-188`）解析后作为 oracle。

本次为写规格实际运行的 dump（lean 4.33.1）得到：

```
Nat:       induct numParams=0 numIndices=0 numNested=0 isRec=true  ctors=[Nat.zero, Nat.succ]
Bool:      induct numParams=0 numIndices=0 numNested=0 isRec=false ctors=[Bool.false, Bool.true]
Bool.false:ctor induct=Bool cidx=0 numFields=0
Bool.true: ctor induct=Bool cidx=1 numFields=0
Nat.zero:  ctor induct=Nat  cidx=0 numFields=0
Nat.succ:  ctor induct=Nat  cidx=1 numFields=1
Nat.rec:   rec numParams=0 numIndices=0 numMotives=1 numMinors=2 k=false majorIdx=3
           rules=[(Nat.zero,0),(Nat.succ,1)]
Nat.casesOn: def hints=abbrev safety=safe        <-- 不是 recInfo
Bool.casesOn:def hints=abbrev safety=safe
P2:        induct numParams=0 numNested=0 isRec=false ctors=[P2.mk]
P2.mk:     ctor induct=P2 cidx=0 numFields=2
P2.casesOn:def hints=abbrev safety=safe
```

测试应断言：上面每个字段等于 `decode_env_meta` 的输出；并断言
`Nat.casesOn`/`Bool.casesOn`/`P2.casesOn` 的 `T_ENV_META.V1 == 1`（Definition），
不是 7（Recursor）。

### 5.3 负例 / 变异
仿 `tests/test_mutation_reject.py` 的做法（该文件用 `Encoder(consts, is_ctor=ctors)`，
`tests/test_mutation_reject.py:100-123`）：篡改元数据 token 字段（如把
`T_ENV_CTORVAL.nfields` 改错、把 rule 的 ctor 换成不存在的 cid、把 kind 改成
冲突值），要求解码/校验拒绝或与真值不符。测试入口可复用
`tests/test_ref_infer_defeq.py:22` 的 `Encoder, decode_closure, decode_expr` 导入方式，
并对照 graph 与 ref_vm 两个消费端。

建议新增测试文件 `tests/test_env_meta.py`（本规格不创建）。

---

## 6. 未决项（TBD）

1. hints_height 大于 4095 时的编码（截断/链式/存 Regular 标志位）。
2. `all` 列表是否真的编码：真内核注释称内核不使用（`Lean/Declaration.lean:124-131`）。
3. univ_arity > 0：真 Nat.rec 的 levelParams=1；v1 toy 全为 0，LParam 名未编码
   （VM_SPEC §9.2 已记为缺口）。现有 `_enc_level_args`（`expr/tokens.py:309-318`）
   恒返回 0。
4. casesOn 的真实 kind 处理方案（§4.3，a/b）。
5. quot_val 当前语料未出现，字段已定义但未验证。
6. nnested > 0（嵌套归纳）与 indices > 0 不在 v1 切片内。
7. 元数据 token 的具体落位（§2.7 推荐锚点块 + 追加区）需随
   `Encoder`/`build_vm` 改动最终确定；本文给出的是位置无关的字段语义。
8. 列表成员用 nid 还是 cid：本文选 nid（贴近内核 Name 语义），可改。
9. `T_NULL.V0` 改存 n_consts 是否合适，或另设锚点 token。
10. 真内核 `MutualDefinition`（`declaration_kind`，`declaration.h:201`）不在
    `constant_info_kind` 八类中，互递归在环境中已展开为定义，本文按展开后编码。
