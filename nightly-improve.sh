#!/bin/bash
# nightly-improve.sh — 毎晩 03:00 (JST) に Locus 自身を自律改善する
#
# フロー:
#   1. 両リポを git pull --ff-only
#   2. /improve スキルを Claude Code 非対話実行
#   3. 完了通知
#
# 不変条件:
#   - PR の merge は人間が GitHub UI で行う（このスクリプト/スキルは絶対 merge しない）
#   - smoke test 失敗時は branch を消して PR を作らない（/improve 側で実装）
#
# launchd 経由で呼ばれる（com.locus.nightly-improve.plist）

set -euo pipefail

# ~/.zshenv から環境変数を読み込む（launchd は zshenv を読まない）
if [ -f "$HOME/.zshenv" ]; then
    source "$HOME/.zshenv" 2>/dev/null || true
fi

CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo $HOME/.local/bin/claude)}"
COMPILER_DIR="${COMPILER_DIR:-$HOME/Projects/locus-project/locus}"
LOCUS_PRIVATE_DIR="${LOCUS_PRIVATE_DIR:-$HOME/Projects/locus-project/locus-private}"
LOG_FILE="/tmp/locus-nightly-improve.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

notify() {
  osascript -e "display notification \"$1\" with title \"$2\" sound name \"$3\"" 2>/dev/null || true
}

log "=== nightly-improve.sh 開始 ==="

# ── Step 0: 両リポ pull ──────────────────────────────────────────────
log "git pull..."
for repo in "$COMPILER_DIR" "$LOCUS_PRIVATE_DIR"; do
  if ! git -C "$repo" pull --ff-only 2>&1 | tee -a "$LOG_FILE"; then
    log "[abort] $repo の pull 失敗"
    notify "$(basename "$repo") pull failed" "⚠️ nightly-improve" "Basso"
    exit 1
  fi
done

# ── Step 1: /improve 実行 ─────────────────────────────────────────────
log "/improve 実行..."
PR_OUTPUT=$(
  cd "$LOCUS_PRIVATE_DIR" && \
  "$CLAUDE" --print "/improve" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"
)

# ── Step 2: PR が立ったかチェック ────────────────────────────────────
PR_COUNT=$(echo "$PR_OUTPUT" | grep -c "^PRs:" || echo "0")
if echo "$PR_OUTPUT" | grep -q "github.com.*pull/"; then
  PR_URLS=$(echo "$PR_OUTPUT" | grep -oE "https://github\.com/[^ ]+/pull/[0-9]+" | head -3 | tr '\n' ' ')
  log "PR 作成: $PR_URLS"
  notify "新規 PR があります: $PR_URLS" "🤖 nightly-improve" "Glass"
else
  log "今晩は提案無し（または smoke test fail）"
  # 通知無し（毎日通知だとうるさい）
fi

log "=== 完了 ==="
