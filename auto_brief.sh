#!/bin/bash
# auto_brief.sh — 12h テックニュースブリーフ自動生成パイプライン
#
# 1. ニュース収集 (collect_news.py)
# 2. Claude Code で英語記事を翻訳 (/news-translate)
# 3. Claude Code でダイジェスト生成 (/news silent)
# 4. macOS 通知
#
# LaunchAgent から 07:00 / 19:00 に呼ばれる。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCUS_PRIVATE_DIR="${LOCUS_PRIVATE_DIR:-$HOME/Projects/locus-project/locus-private}"

# ~/.zshenv から環境変数を読み込む（launchd は zshenv を読まないため）
if [ -f ~/.zshenv ]; then
    source ~/.zshenv 2>/dev/null || true
fi
UV="${UV_BIN:-$(command -v uv || echo $HOME/.local/bin/uv)}"
CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo $HOME/.local/bin/claude)}"
DATA_DIR="$SCRIPT_DIR/scripts"
LOG_FILE="/tmp/locus-auto-brief.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

notify_fail() {
  osascript -e "display notification \"$1\" with title \"⚠️ locus news\" sound name \"Basso\"" 2>/dev/null || true
}

log "=== auto_brief.sh 開始 ==="

# ── Step 0: 最新コードを pull（laptop ↔ mini 双方向で dirty work tree 想定）─
# --rebase --autostash で:
#   • 通常の追従 → linear rebase
#   • 自動生成ファイルの未コミット差分 → autostash で逃す
#   • 競合 → rebase 自体がクリーンに abort
log "git pull 開始..."
for repo in "$SCRIPT_DIR" "$LOCUS_PRIVATE_DIR"; do
  if ! git -C "$repo" pull --rebase --autostash 2>&1 | tee -a "$LOG_FILE"; then
    git -C "$repo" rebase --abort 2>/dev/null || true
    log "[abort] $repo の git pull に失敗。手動解決が必要です"
    notify_fail "$(basename "$repo") pull failed"
    exit 1
  fi
done
log "git pull 完了"

# ── Step 1: ニュース収集 ───────────────────────────────────────────────
log "ニュース収集開始..."
"$UV" run --no-sync \
  --directory "$SCRIPT_DIR" \
  python "$DATA_DIR/collect_news.py" 2>&1 | tee -a "$LOG_FILE"
log "収集完了"

# ── Step 2: 英語記事を翻訳（collect_news.py が既に Google Translate で実施済み）──
# /news-translate スキルは行方不明のため撤去。translate は collect_news.py 内で完結。

# ── Step 3: ダイジェスト生成 (locus-private/scripts/process/digest.py) ─────────
log "ダイジェスト生成開始..."
"$UV" run --no-sync \
  --directory "$SCRIPT_DIR" \
  python "$LOCUS_PRIVATE_DIR/scripts/process/digest.py" 2>&1 | tee -a "$LOG_FILE"
log "ダイジェスト生成完了"

# ── Step 4: 件数取得 + macOS 通知 ─────────────────────────────────────
TOTAL=$(python3 -c "
import json, sys
try:
    d = json.load(open('$DATA_DIR/news-latest.json'))
    print(len(d.get('items', [])))
except Exception as e:
    print('?')
" 2>/dev/null || echo "?")

DATE=$(python3 -c "
import json
try:
    d = json.load(open('$DATA_DIR/news-latest.json'))
    print(d.get('date',''))
except:
    print('')
" 2>/dev/null || echo "")

log "通知送信: ${DATE} ${TOTAL}件"
osascript -e "display notification \"${TOTAL}件のテックニュース · ${DATE}\" with title \"📰 Daily Brief 準備完了\" sound name \"Ping\"" 2>/dev/null || true

log "=== 完了 ==="
