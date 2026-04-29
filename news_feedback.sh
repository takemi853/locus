#!/bin/bash
# news_feedback.sh — 日次フィードバック分析 + テックワード自動収集
#
# 毎日 22:00 に LaunchAgent から呼ばれる。
# 1. feedback.py が news-feedback.json を集計し news-feedback-log.md に追記
# 2. term_freq.py --add-new --min-freq 3 が直近 24h の X tweet からテックワードを
#    抽出し、未登録のものを inbox/interests/ に stub 追加
#    (news_app の background enrich が後で interest.py で enrich)
#
# 旧設計は /news feedback skill 呼び出しだったが skill 不在で silent fail して
# いたため Python script に置換 (digest.py と同じ修正パターン)。

set -euo pipefail

# ~/.zshenv から環境変数を読み込む（launchd は zshenv を読まないため）
if [ -f ~/.zshenv ]; then
    source ~/.zshenv 2>/dev/null || true
fi

COMPILER_DIR="${COMPILER_DIR:-$HOME/Projects/locus-project/locus}"
LOCUS_PRIVATE_DIR="${LOCUS_PRIVATE_DIR:-$HOME/Projects/locus-project/locus-private}"
UV="${UV_BIN:-$(command -v uv || echo $HOME/.local/bin/uv)}"
LOG_FILE="/tmp/locus-news-feedback.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

notify_fail() {
  osascript -e "display notification \"$1\" with title \"⚠️ locus news\" sound name \"Basso\"" 2>/dev/null || true
}

log "=== news_feedback.sh 開始 ==="

# 最新コードを fast-forward pull
log "git pull 開始..."
for repo in "$COMPILER_DIR" "$LOCUS_PRIVATE_DIR"; do
  if ! git -C "$repo" pull --ff-only 2>&1 | tee -a "$LOG_FILE"; then
    log "[abort] $repo の git pull に失敗。手動解決が必要です"
    notify_fail "$(basename "$repo") pull failed"
    exit 1
  fi
done
log "git pull 完了"

log "feedback 分析開始..."
"$UV" run --no-sync \
  --directory "$COMPILER_DIR" \
  python "$LOCUS_PRIVATE_DIR/scripts/process/feedback.py" 2>&1 | tee -a "$LOG_FILE"
log "feedback 分析完了"

# テックワード自動収集 (24h X tweet → whitelist 集計 → 未登録分を stub 化)
# --min-freq 3 = 同 batch 内で 3 回以上言及されたテックワードのみ追加
# 既存登録は重複検出で自動 skip。stub は inbox/interests/<slug>.md に書かれ、
# news_app の background polling で interest.py 経由 enrich される。
log "テックワード自動収集開始..."
"$UV" run --no-sync \
  --directory "$COMPILER_DIR" \
  python "$LOCUS_PRIVATE_DIR/scripts/analyze/term_freq.py" \
    --add-new --min-freq 3 --hours 24 2>&1 | tee -a "$LOG_FILE"
log "テックワード自動収集完了"

log "=== 完了 ==="
