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

# ── Step 0: 両リポ pull (laptop ↔ mini 双方向対応で rebase + autostash) ────
log "git pull..."
for repo in "$COMPILER_DIR" "$LOCUS_PRIVATE_DIR"; do
  if ! git -C "$repo" pull --rebase --autostash 2>&1 | tee -a "$LOG_FILE"; then
    git -C "$repo" rebase --abort 2>/dev/null || true
    log "[abort] $repo の pull 失敗"
    notify "$(basename "$repo") pull failed" "⚠️ nightly-improve" "Basso"
    exit 1
  fi
done

# ── Step 0.5: 最新 lint レポートを生成（/improve への入力にする）──────
log "lint --structural-only..."
LINT_REPORT=""
if cd "$COMPILER_DIR" && uv run --no-sync python scripts/lint.py --structural-only 2>&1 | tee -a "$LOG_FILE"; then
  TODAY=$(date +%Y-%m-%d)
  LINT_FILE="$LOCUS_PRIVATE_DIR/reports/lint-$TODAY.md"
  if [ -f "$LINT_FILE" ]; then
    LINT_REPORT=$(cat "$LINT_FILE")
    log "lint レポート読み込み済み ($(wc -l < "$LINT_FILE") 行)"
  fi
fi

# ── Step 1: /improve 実行（最大 1 時間で wall-clock 強制終了）────────
log "/improve 実行 (max 60min)..."
TIMEOUT_BIN="${TIMEOUT_BIN:-$(command -v gtimeout || command -v timeout)}"

# /improve に lint レポートを文脈として注入。Claude には:
#   - 重大度 error から優先的に対処
#   - 1晩あたり最大 3 件まで PR 化（小さく刻む）
#   - 機械的に修正できるものは scripts/lint_fix.py を活用
# を指示する。
IMPROVE_PROMPT="/improve

## 今夜の lint レポート（ヘルスチェック結果）

これを参考に、修正可能な小さい issue を 1〜3 件選んで PR を立ててください。
重要度 error から優先。機械的に直せるリンク・バックリンク系は scripts/lint_fix.py が
処理できるのでそれを実行・コミットするだけで OK な場合もあります。

\`\`\`
${LINT_REPORT:-(lint 実行に失敗 — レポート無しで /improve のデフォルト動作で進めてください)}
\`\`\`"

PR_OUTPUT=$(
  cd "$LOCUS_PRIVATE_DIR" && \
  ${TIMEOUT_BIN:+$TIMEOUT_BIN 3600} \
    "$CLAUDE" --print "$IMPROVE_PROMPT" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"
) || log "[warn] claude が exit 非0 (timeout? error?)"

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
