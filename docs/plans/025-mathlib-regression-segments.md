# 任务 025：mathlib_closure 回归按闭包分段（帽失效收口）

状态：**CLOSED（2026-10-23 立卡并当日收口）**。三段落地实测：Quot 5092.2s/
2333MB、Vector3 559.3s/1584MB、Nat 206.3s/1939MB；帽 = 实测 ×1.4
（`7100|3200` / `780|2200` / `280|2700`）；5 字段解析不破老条目，
`SUITE_FILTER=mathlib_` 只跑三段。 —
拍 4 验证段已完成：三段实现落地、实测与帽校准见 §实测，待总控收口。

## 背景（实测）

卡 012 把 `tests/test_mathlib_closure_vs_lean.py`（35 行 × 4 通道）放进
`scripts/run_cpu_regression.sh`，帽 `3600|4000`（依据是 2026-10-15 的
2121.6s/1950MB）。2026-10-23 卡 022 拍 2 修复后复跑：

```
[mem-guard] wall 3700.3s  peak RSS 2272MB  rc=124（撞帽被杀）
跑完 11 行 × 4 腿，零 FAIL
```

## 帽失效的归因（实测，不是负载）

1. **引擎腿从"秒级报错"变成"跑到判定"**：卡 023 修好位置取指悬崖后，
   `q_acc_def` 引擎单行 300.8s、`enginefull` 同量级（修前是快速 -1）。
2. **graph 腿的 accept 行 ~700s/行**（Python 求值器 O(N²·L)，且 accept 行
   要走到 check 完成）。
3. 11 行 3700s ⇒ 外推全 35 行 **4–6.5h**。抬帽到 ~25000s 违背"回归套件
   墙钟纪律"（单套件与整天预算都爆），且掩盖了"某一行变慢"的信号。

## 方案（已定）

**按 closure 分段**，三段各自成一个回归条目：

| 段 | 闭包 | 行数 | 预期墙钟（立卡时的估计） |
|---|---|---|---|
| `mathlib_quot` | `Quot_liftOn_mk` | 16 | ~40–50 min |
| `mathlib_vector3` | `Vector3_cons_fz` | 11 | ~30–40 min |
| `mathlib_nat` | `Nat_testBit_land` | 8 | ~25–35 min |

实现：`scripts/run_cpu_regression.sh` 的 SUITES 条目加**可选第 5 字段**
（环境赋值串，例 `MC_CLOSURES=Quot_liftOn_mk`），`launch_suite` 在
`$PY -u <path>` 之前注入；删掉原单条 `mathlib_closure_vs_lean`，换三条。
帽先按上表给保守值，**首轮实测后按 `实测 × 1.4` 校准并落注释**。

## Verifier

- [x] 三段各自 rc=0、汇总行含 `graph: N agree/... , refvm: ...`，且三段行数合计 **35**
- [x] 三段 wall/RSS 实测原文落 log，帽按实测校准（注释写清依据）
- [x] `SUITE_FILTER=mathlib_` 能只跑三段；`SUITE_FILTER` 语义不变
- [ ] 24 套件基数 → 26（脚本侧已写 `26 suites below`；**`ARCHITECTURE.md:116` 仍写
      「24 套件」，该文件归总控，未触**）；脚本 `bash -n` 过

## 风险

1. 分段后每段各自重建闭包 env（M-A 闭包 jsonl 只读），启动开销 ×3（可接受）；
2. 段间无共享缓存，oracle（lean）每段各跑一次（~5–11s）；
3. 回归总墙钟仍 ~2h，属"收尾级"，不进日常心跳。

## 实测（拍 4 验证段，2026-10-23 09:0x–10:33；`MC_SBIN=model/step_vm_022b_scratch.sbin`
md5 `7c7c3cc2f6f19084cdf0d9b480948f67`，JOBS=1 串行、核 0-5）

| 段 | 行数 | 实测 wall / 峰值 RSS（进程树） | 落帽 | 余量 |
|---|---|---|---|---|
| `mathlib_quot` | 16 | **5092.2s / 2333MB** rc=0 | `7100\|3200` | ×1.39 / ×1.37 |
| `mathlib_vector3` | 11 | **559.3s / 1584MB** rc=0 | `780\|2200` | ×1.39 / ×1.39 |
| `mathlib_nat` | 8 | **206.3s / 1939MB** rc=0 | `280\|2700` | ×1.36 / ×1.39 |

三段合计 **35 行 × 4 通道零 FAIL、零 XPASS、零 XFAIL**（摘册后判定分歧=普通 FAIL）：

```
16 cases, graph: 16 agree/0 diverge/0 boundary, refvm: 12 agree/0 diverge/4 boundary, engine: 13 agree/0 diverge/3 boundary, enginefull: 13 agree/0 diverge/3 boundary
11 cases, graph: 11 agree/0 diverge/0 boundary, refvm: 7 agree/0 diverge/4 boundary, engine: 10 agree/0 diverge/1 boundary
8 cases,  graph: 8 agree/0 diverge/0 boundary,  refvm: 6 agree/0 diverge/2 boundary,  engine: 7 agree/0 diverge/1 boundary
```

证据：脚本 `~/logs/022B3/b8_reg_pass1.log`；分段日志
`~/logs/022B3/b8_reg/mathlib_{quot,vector3,nat}.log`；落帽后复跑
`~/logs/022B3/b8_reg_verify/`（nat，206.8s/1942MB 在 `280|2700` 下 rc=0）与
`~/logs/022B3/b8_verify_plain/`（无第 5 字段的 `level_vs_lean` 37/37 rc=0）。

**实现要点（踩坑）**：第 5 字段的赋值串不能直接前缀到命令上 ——
`scripts/run_mem_guarded.py` 用 `subprocess.Popen(list)` 直接 exec，`VAR=x`
会变成 argv[0]（实测 `FileNotFoundError: 'MC_CLOSURES=Quot_liftOn_mk'`）；
必须经 `env $envs`（`run_cpu_regression.sh:291`）。

**未决**：
1. 帽按 solo（JOBS=1）实测 ×1.4；池内（JOBS=3）首跑才是并发校验。
2. `MATHLIB_SBIN` 默认钉 `model/step_vm_022b_scratch.sbin`（scratch 件）；
   发布晋升后需改默认或由 `MATHLIB_SBIN=` 覆盖。
3. `tests/test_mathlib_closure_vs_lean.py` 自带的 `MC_SBIN` 默认仍是
   `step_vm_021_scratch.sbin`（021 图），裸跑会按 021 图判 engine 腿 ——
   是否抬默认值待总控裁（本卡只经回归条目的第 5 字段钉 022b）。
