# 008. LEAN_NAT_MAX_SIZE 的图侧镜像：编译期烘焙（选项 B）

- 状态：accepted（2026-09-15，WP6，代理 C3）
- 关系：落实验收铁律 3（环境是数据）在 Nat 尺寸守卫上的唯一可行通道；
  语义引用 `K/type_checker.cpp:1307-1321`（read_nat_size_env）与
  `docs/VM_SPEC.md` §15。

## 背景

内核的 `LEAN_NAT_MAX_SIZE` 在**进程初始化期**由 `initialize_type_checker`
读一次（strtoull 全串消耗，malformed 回退默认 128 MB；负数按 size_t 回绕
mod 2^64），之后所有 reduce 守卫（add/sub/mul/succ/pow/shiftLeft/infer_lit）
用同一个冻结值。图侧守卫需要比较 MAX（或 8·MAX、⌊MAX/8⌋+1 的派生量，默认
值 134217728 超过 fp32 精确整数区 2^24），标量化不可行，必须走数字链字典
序比较，而被比较对象的**十进制数字串**必须在图里以数据形式存在。

候选：A) ENV 区新增常量元数据 token 携带 MAX——污染 ENV_FORMAT 且内核环境
里不存在这个"常量"；B) 编译期烘焙——图镜像内核的"进程初始化期读一次"时机。

## 决策

选项 B。`lean_vm/build_vm.py::_read_nat_size_env()`（:75-98）逐条复刻内核
解析语义（空白+符号前缀、纯数字、全串消耗否则回默认、负值 mod 2^64 回绕），
在 `build_step_graph` 调用时读 `os.environ` 一次（:2182），派生量
`_NAT_MAX / 8·_NAT_MAX / _T_LIMB / _T_DIG / MAX·4294967295 数字表
(_MAX_DIG/_MAX8_DIG/_U32_DIG)` 全部作为**数字表数据**进入权重（每个下标处
是常量 mux，无分支、无 cid）。默认 128 MB 与自定义值走完全同一条图路径。

差分测试（tests/test_reducenat_graph_vs_lean.py）在 build 之前设置
`LEAN_NAT_MAX_SIZE`，并让该 env **同时覆盖图烘焙与 lean 子进程**，用小 MAX
证明守卫真会拒（默认 MAX 下机器可编码链 ≤4095 位 ≤1704 B，尺寸类守卫可证
不触发，无法造用例）。

## 后果

- 换 MAX 需要重编图（与内核换 env 需要重启进程严格对应，成本语义一致）。
- ENV_FORMAT 无变更：烘焙发生在权重侧，token 流不动（归 ENV_FORMAT 维护者
  知悉即可，本卡不触该文件）。
- 已知限制：env 只在 build 期读，runner/engine 加载 sbin 时**不再读**——
  权重即事实。跑 sbin 前必须确认烘焙值与被测内核一致（真值表记 mtime/参数）。
- compile_vm 的 dims 随 MAX 位数线性微增（数字表行数），默认值下与旧基线
  同表。
