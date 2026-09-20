#!/usr/bin/env bash
# PreCompact hook (matcher: auto) — "换窗口接力" 的落盘侧。
# auto-compact 触发时（约上下文将满），把当前会话的 transcript 路径与
# 关键指针写入 .claude/last-session.txt，供新会话按需检索旧聊天记录。
# 不 block 压缩（压缩作为兜底继续发生，避免撞 API 硬上限）。
set -u
DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
INPUT="$(cat)"
TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty')"
SESSION_ID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty')"
TRIGGER="$(printf '%s' "$INPUT" | jq -r '.trigger // "auto"')"
[ -n "$TRANSCRIPT" ] || exit 0

# transcript 可能不存在（异常情况）——没得抢救就直接放行
[ -f "$TRANSCRIPT" ] || exit 0

{
  echo "transcript=$TRANSCRIPT"
  echo "session_id=$SESSION_ID"
  echo "trigger=$TRIGGER"
  echo "recorded_at=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$DIR/.claude/last-session.txt"

# 最近一段 assistant 文本（尾部 60 条消息里的正文）快照到
# handoff-snapshot.md —— 新会话不用解析整个 JSONL 也能看到收尾状态。
jq -r 'select(.type == "assistant") | .message.content[]?
       | select(.type == "text") | .text' "$TRANSCRIPT" 2>/dev/null \
  | tail -n 200 > "$DIR/.claude/handoff-snapshot.md"

exit 0
