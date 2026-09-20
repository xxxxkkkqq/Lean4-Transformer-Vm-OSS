#!/usr/bin/env bash
# SessionStart hook (matcher: startup|clear|compact) — "换窗口接力" 的注入侧。
# 新会话启动时注入：会话开场顺序 + 上一个会话的 transcript 路径，
# 让新会话能按需检索旧聊天的精确内容（而不是靠压缩摘要）。
# 开场顺序的唯一权威是仓库根 AGENTS.md §0；本注入与它保持一致。
set -u
DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LAST="$DIR/.claude/last-session.txt"

cat <<'EOF'
[会话开场，顺序固定]
1. 读仓库根 AGENTS.md 全文（硬规则 + 角色分工 + 完工定义）。
2. 读 docs/handoffs/ 最新一份（编号最大 ≠ 最新，以文件内状态行为准）
   与 docs/plans/ 里状态 open 的任务卡。
3. 动手前核对 ARCHITECTURE.md 的 artifact 真值表（用哪份权重/二进制）。
4. 没有任务卡不许开工；每个 agent 完成任务立即写文档落盘，不延误。
EOF

if [ -f "$LAST" ]; then
  TRANSCRIPT="$(sed -n 's/^transcript=//p' "$LAST" | head -n1)"
  RECORDED="$(sed -n 's/^recorded_at=//p' "$LAST" | head -n1)"
  if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    cat <<EOF
[上一会话接力]（$RECORDED 记录）
- 完整旧聊天记录（JSONL，可 Read/Grep 按需检索，勿整体读入）：$TRANSCRIPT
- 里程碑提交历史：git log --oneline（每个 commit 带验收数字）
需要旧会话里的精确细节（某个 bug 的调试过程、某条命令输出）时再去
grep 旧 transcript；接力状态以 docs/handoffs/ 为准，不以聊天记录为准。
EOF
  fi
fi
exit 0
