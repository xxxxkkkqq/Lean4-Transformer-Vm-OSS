# 002. 多态常量的类型实例化放在编码期，不引入运行期替换算子

- 状态：accepted（2026-09-13，WP2b）
- 背景：universe 多态常量（如带 `level param` 的类型）在被 `Const` 使用时需要把类型里的 `Level.param` 实例化成调用方给出的 level 实例。真内核在 `infer_constant` 里做 `instantiateType`（`K/type_checker.cpp:101` 附近，见 `docs/KERNEL_COVERAGE.md` A6）。实现前需要回答：在图上做还是在编码时做。
- 决策：由**编码器**在使用点把类型根实例化后写入 `K_CONST.E2`；图侧 `CONST` 推断按 `E2 >= 1 ? E2 : ENV_HDR.V1` 选择（`lean_vm/build_vm.py:3650-3662`），即"有实例化类型根就用它，否则退回 ENV 里的泛型类型"。相关辅助：`expr/tokens.py` 的 `Encoder._const_type_expr` / `_specializing` / `_level_has_param` / `_expr_has_param_univ` / `_inst_level` / `_inst_expr` / `_specialize_type`。语义记录在 `docs/VM_SPEC.md` §12.7。
- 被拒方案：
  - 运行期 level 替换算子：需要新的图原语与"遍历类型树逐参数替换"的子程序，会显著增加每条 `Const` 推断路径的微步数（当前 `Cov_poly_nat` 已 294 步），并把 depth 从常数推向随类型规模增长——违反 `docs/DESIGN.md` §4.2「循环由时间承担、图深度不随输入规模增长」。
  - 在 ENV 里为每个 (常量, level 组合) 预开一条目：环境规模随多态实例数爆炸，与 §4.3「环境是数据」的紧凑编码目标冲突。
- 预期后果：
  - 好：零新增图算子、零新增 token 种类（复用 `K_CONST.E2`），`Cov_poly_nat` / `Cov_poly_type` 从 reject 变 accept（294 / 251 步）。
  - 坏：实例化结果编码在 token 里，ENV 区与 STATE 区的职责边界因此变薄了一层（编码期承担了部分内核语义）；且**只实例化了类型根，值里的 `Level.param` 尚未接入 delta 展开路径**（缺口记在 `docs/handoffs/000-*.md` §3.3）；后续要支持同一常量多种实例并存时，需先扩展 E2 的承载方式并再次走 ADR。
