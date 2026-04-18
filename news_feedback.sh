#!/bin/bash
# news_feedback.sh — 日次フィードバック分析・news_config.py 自動改善
#
# 毎日 22:00 に LaunchAgent から呼ばれる。
# /news feedback スキルで分析 → X_ACCOUNTS_JA 追加 + ログ保存

set -euo pipefail

# ~/.zshenv から環境変数を読み込む（launchd は zshenv を読まないため）
if [ -f ~/.zshenv ]; then
    source ~/.zshenv 2>/dev/null || true
fi

CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo $HOME/.local/bin/claude)}"
COMPILER_DIR="${COMPILER_DIR:-$HOME/Projects/app/claude-memory-compiler}"
LOCUS_PRIVATE_DIR="${LOCUS_PRIVATE_DIR:-$HOME/Projects/locus-private}"
LOG_FILE="/tmp/locus-news-feedback.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

notify_fail() {
  osascript -e "display notification \"$1\" with title \"⚠️ locus news\" sound name \"Basso\"" 2>/dev/null || true
}

log "=== news_feedback.sh 開始 ==="

# 最新コードを fast-forward pull（mini 運用の整合性確保）
log "git pull 開始..."
for repo in "$COMPILER_DIR" "$LOCUS_PRIVATE_DIR"; do
  if ! git -C "$repo" pull --ff-only 2>&1 | tee -a "$LOG_FILE"; then
    log "[abort] $repo の git pull に失敗。手動解決が必要です"
    notify_fail "$(basename "$repo") pull failed"
    exit 1
  fi
done
log "git pull 完了"

(cd "$LOCUS_PRIVATE_DIR" && \
  "$CLAUDE" --print "/news feedback" --dangerously-skip-permissions) 2>&1 | tee -a "$LOG_FILE"

log "=== 完了 ==="
