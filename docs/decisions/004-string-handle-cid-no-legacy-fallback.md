# 004. 字符串句柄 cid 扫描缺失时不回退 toy 常量

- 状态：accepted（2026-09-13，WP5；补记 `lean_vm/build_vm.py:433-441` 注释中已声明的决策，应 WP5 指令要求正式建档）
- 背景：name-scan + metadata 机制（`lean_vm/build_vm.py:398-441`）从 `ENV_HDR.X` 的名字标签扫描各算子/常量的 cid。Bool 的 `true/false`（WP8-H5）在扫描 miss 时回退到 toy cid（`:427-432`）；而 WP5 引入的两个字符串句柄——`"String.ofList"` 与 `"String"`（`_OFLIST_OK/_OFLIST_CID/_STRING_OK/_STRING_CID`，`:438-441`）——显式**没有** legacy fallback，注释只有一句话。本 ADR 回答"为什么不同样回退"。
- 决策：维持不回退。理由：
  1. 语义正确性优先于兼容性。字符串句柄只被用作**存在性门控**：`_OFLIST_OK` 把守 E3b 展开臂（`ST_ES`/`es_str`，`lean_vm/build_vm.py:3197-3254`）与 ofList 重定向识别，`_STRING_OK` 把守 E4 字面量类型推断臂（`lit_ok_i`，`:3960`）。env 里没有 `"String.ofList"` 时图**不可能**在这些句柄上做出任何正确判断——此时任何 cid 都"可能"是别的常量；toy fallback 等于让图在不懂字符串的环境里假装懂：把某个无关常量当 `String.ofList` 做 fold-tree 展开，产生错误 verdict——比干净拒绝危险得多。
  2. 与内核行为一致（指令"期望值只能来自 lean 现跑"的镜像）。没有 `String` 类型的环境里，内核 infer 一个字符串字面量会直接 unknown-constant 失败；图的 `lit_ok_i` 在 `_STRING_OK=0` 时走 reject，行为同构。没有 `String.ofList` 的环境里内核永远无法构造/比较字符串对；图的臂不触发，对落到 stuck chain 其余臂。
  3. 与 Bool 的回退并存不矛盾。Bool 的 `_TRUE_CID/_FALSE_CID` 参与 beq/ble **算术机器**的数值判定（`:420-426` 注释），旧流（WP1 metadata 前）算术测试仍要能跑，回退有真实受益面；字符串句柄没有这种"在 legacy 流上还有正确用法"的场景，回退只有风险。
  4. 存在性判定必须用命中计数（`:415-419` 的结论：`cid >= 1` 不行，cid 0 合法），`_OFLIST_OK/_STRING_OK = (cnt >= 1)` 与此一致；"miss 时给个默认 cid"会伪造计数语义。
- 被拒方案：
  - 照抄 Bool 的回退模式——见理由 1/2/3。
  - 在 `expr/tokens.py` 侧把编码期展开子树在缺标签时退化保留（当前 `LitStr` 编码仅在五个展开名字齐全时才设 `X` 根指针，`expr/tokens.py:837-859`）——那会让"影子树存在与否"依赖编码分支而非环境标签，违背"标签即权威"。
- 预期后果：
  - 好：WP5 之前的旧流（无 `STR_ID_CODES` 标签，`expr/tokens.py:168`）遇到字符串对时行为可预期（臂不触发/reject），不会产生错误 verdict；`tests/test_quot_graph_vs_lean.py`、`tests/test_stepgraph_infer_defeq.py` 等非字符串套件的流不受影响。
  - 坏：若未来真要在 legacy 流上跑字符串比较，需编码器先补发 `ENV_HDR.X` 标签并重新评估——那是新决策，需要新 ADR。
