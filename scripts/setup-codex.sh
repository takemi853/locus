#!/bin/bash
# setup-codex.sh — Mac mini で codex × claude code を並行使用する環境構築
#
# 安全のため install / 認証 / shell 設定の編集は確認プロンプト付き。
# 既存の claude code 環境には触らない（codex を横に追加するだけ）。
#
# Usage:
#   bash scripts/setup-codex.sh            # 対話的に進める
#   bash scripts/setup-codex.sh --yes      # すべて yes で進める（CI 用）
#   bash scripts/setup-codex.sh --check    # 現状の診断のみ（変更しない）

set -euo pipefail

YES=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --yes)   YES=1 ;;
    --check) CHECK_ONLY=1 ;;
  esac
done

confirm() {
  if [ "$YES" = "1" ] || [ "$CHECK_ONLY" = "1" ]; then return 0; fi
  read -r -p "$1 [y/N] " ans
  case "$ans" in y|Y|yes) return 0 ;; *) return 1 ;; esac
}

ok()    { echo "  ✓ $*"; }
warn()  { echo "  ⚠ $*"; }
todo()  { echo "  → $*"; }

echo "=== codex × claude code 環境セットアップ ==="
echo

# ── 0. 前提診断 ─────────────────────────────────────────────────────
echo "[0/4] 前提チェック"
HAS_BREW=0; command -v brew >/dev/null && HAS_BREW=1 && ok "brew: $(brew --version | head -1)"
HAS_NPM=0;  command -v npm >/dev/null  && HAS_NPM=1  && ok "npm:  $(npm --version)"
HAS_CLAUDE=0; command -v claude >/dev/null && HAS_CLAUDE=1 && ok "claude: $(claude --version 2>&1 | head -1)"
HAS_CODEX=0;  command -v codex >/dev/null  && HAS_CODEX=1  && ok "codex: $(codex --version 2>&1 | head -1)" || todo "codex 未インストール"
HAS_TMUX=0;   command -v tmux >/dev/null   && HAS_TMUX=1   && ok "tmux: $(tmux -V)" || todo "tmux 未インストール（並行ペイン用、任意）"

if [ -n "${OPENAI_API_KEY:-}" ]; then ok "OPENAI_API_KEY 設定済み (***${OPENAI_API_KEY: -4})"
else todo "OPENAI_API_KEY 未設定"; fi

echo
[ "$CHECK_ONLY" = "1" ] && exit 0

if [ "$HAS_CLAUDE" = "0" ]; then
  warn "claude code が見つかりません。先に Claude Code をセットアップしてください"
  exit 1
fi

# ── 1. codex CLI インストール ───────────────────────────────────────
echo "[1/4] codex CLI"
if [ "$HAS_CODEX" = "0" ]; then
  if [ "$HAS_BREW" = "1" ]; then
    if confirm "brew install --cask codex で codex を入れますか？"; then
      brew install --cask codex
      ok "codex installed via brew"
    fi
  elif [ "$HAS_NPM" = "1" ]; then
    if confirm "npm i -g @openai/codex で codex を入れますか？"; then
      npm i -g @openai/codex
      ok "codex installed via npm"
    fi
  else
    warn "brew も npm もありません。先にいずれかを入れてください"
    exit 1
  fi
else
  ok "codex 既存"
fi

# ── 2. tmux（任意。並行ペインで使う場合） ────────────────────────────
echo
echo "[2/4] tmux (並行作業用 / 任意)"
if [ "$HAS_TMUX" = "0" ] && [ "$HAS_BREW" = "1" ]; then
  if confirm "brew install tmux しますか？（claude と codex を左右ペインで同時に走らせるため）"; then
    brew install tmux
    ok "tmux installed"
  fi
fi

# ── 3. 認証設定の案内 ────────────────────────────────────────────────
echo
echo "[3/4] OPENAI_API_KEY"
if [ -z "${OPENAI_API_KEY:-}" ]; then
  cat <<'EOF'
  → ~/.zshenv に追記してください（このスクリプトは編集しません）:

      export OPENAI_API_KEY="sk-..."

  反映:
      source ~/.zshenv
      codex login   # OAuth ログインなら不要
EOF
fi

# ── 4. 並行使用ヘルパー（pair-coding.sh） ────────────────────────────
echo
echo "[4/4] pair-coding.sh ヘルパーを scripts/ に設置"
PAIR_PATH="$(dirname "$0")/pair-coding.sh"
if [ -f "$PAIR_PATH" ]; then
  ok "pair-coding.sh 既存（上書きしません）"
else
  cat > "$PAIR_PATH" <<'PAIR'
#!/bin/bash
# pair-coding.sh — claude と codex を tmux で左右ペイン同時起動
# Usage:  bash scripts/pair-coding.sh [作業ディレクトリ]
set -euo pipefail

WORKDIR="${1:-$PWD}"
SESSION="pair-$(basename "$WORKDIR")"

if ! command -v tmux >/dev/null; then
  echo "tmux が必要です: brew install tmux"; exit 1
fi

tmux has-session -t "$SESSION" 2>/dev/null && { tmux attach -t "$SESSION"; exit 0; }

tmux new-session -d -s "$SESSION" -n "pair" -c "$WORKDIR"
tmux split-window -h -t "$SESSION:pair" -c "$WORKDIR"
tmux send-keys    -t "$SESSION:pair.0" "claude" C-m
tmux send-keys    -t "$SESSION:pair.1" "codex"  C-m
tmux attach -t "$SESSION"
PAIR
  chmod +x "$PAIR_PATH"
  ok "pair-coding.sh 作成"
fi

echo
echo "=== 完了 ==="
echo "次の一歩:"
echo "  1. (上記 [3/4] に従って) OPENAI_API_KEY を ~/.zshenv に追加"
echo "  2. source ~/.zshenv"
echo "  3. bash scripts/pair-coding.sh ~/Projects/somewhere"
echo
echo "trouble shooting:  bash scripts/setup-codex.sh --check"
