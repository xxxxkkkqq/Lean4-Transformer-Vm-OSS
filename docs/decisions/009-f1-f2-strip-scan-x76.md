# 009. F1/F2 结果守卫：精确位数 strip 扫描（X76），不用链长上界

- 状态：accepted（2026-09-15，WP6，代理 C3）
- 关系：`K/type_checker.cpp:644-658,705-710`；机制表在
  `docs/VM_SPEC.md` §15；`_T_DIG_CMP` 取整见 ADR-010。

## 背景

内核在 add/sub/mul/succ 算出结果 r 之后检查 `8·limbs(r) > MAX`
（`check_size`，K:654-658）。图侧若用**交付链的 V0（头部位数界）**做守卫，
方向性不成立：

- head_V0 对 add/succ 是 `n1+1` 上界、对 mul 是 `n1+n2` 上界——高估。
  用它判拒会把「链界 ≥ T 但真实 limbs ≤ MAX/8」的合法结果误拒（如
  `mul 10^10 10^15`，链界 26 位、真值 10^25 = 2  limbs… 在默认 MAX 下当然
  无事，但小 MAX 差分用例证明它会错）；
- sub 可以完全抵消（`sub 5 (10^19+1) = 0`），头界毫无信息。

误拒违反验收铁律（判定必须与内核一致；机器拒 ⊆ 内核拒是底线方向）。

## 决策

交付步（`done_s` 的 addfam/非下溢 sub 臂 + `mul_done`）把投递**改道**到相位
X76：原臂全部保留（A := SF、B=C=E=F := 0、caller 恢复），唯独 D 不弹 caller
帧，而是在 c1（最后一个数字位之后）发结果链、c2 写一帧
`X=76, V2 = caller 弹出目标（caller_c/ncV2）`。X76 对**已物化**的结果链做
高→低扫描：首个非零数字下标 idx = V0−1−SB ⟹ 精确位数 D_r = V0−SB；全零链
以 SB = V0−1 退出，D_r = 1（值 0，bytes 8 ≤ MAX——见 MAX ≥ 8 前提）。
done76 步判 `D_r ≥ _T_DIG_CMP` 拒（`rej_q`），否则 `D := frV2` 原样弹回
caller——与改道前的 done_s 完全同构，只是多花 V0 步扫描。

下界 `_T_DIG` 由 `limbs ≥ L(D) = 1+⌊(D−1)·3321/64000⌋` 反解（L(D) ≥ T ⟺
D ≥ 1+⌈64000(T−1)/3321⌉，T = ⌊MAX/8⌋+1），所以扫描命中 ⟹ 内核必拒，
**无 false reject**；代价是反方向的带（真 limbs > L(D)，内核拒而机器收），
记为已文档化松弛（VM_SPEC §15.3），语料侧排除、不许用它当绿灯。

不做改道：pred/下溢 sub（内核不查或值为 0）、bitop/shr/gcd（K 无尺寸检查）。

## 后果

- addfam/mul 交付多 O(D) 微步；默认 MAX 下守卫可证不触发（D_r < _T_DIG 恒
  成立，_T_DIG ≈ 3.2 亿 ≫ 链上限 8191），成本只在带/小 MAX 场景出现。
- SE 滞后一拍：hit76 步 B 冻结（B76 的 `reglu(One−SE, hit76)` 项），否则
  done76 的 D_r 少 1，恰在阈值（MAX=8 的 21 位）false accept——实现见
  build_vm :2419-2422 注释。
- 引擎/参照机无须感知 X76：仍是既有发射协议（frame + c1/c2 单元）。
