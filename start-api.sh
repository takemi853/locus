#!/bin/bash
# launchd から api_server を uv 経由で起動するラッパー
# uv の場所と repo パスは env で上書き可能

if [ -f "$HOME/.zshenv" ]; then
    source "$HOME/.zshenv" 2>/dev/null || true
fi

UV="${UV_BIN:-$(command -v uv || echo /opt/homebrew/bin/uv)}"
COMPILER_DIR="${COMPILER_DIR:-$HOME/Projects/locus-project/locus}"

if [ ! -x "$UV" ]; then
  echo "[error] uv が見つかりません。brew install uv 等で入れてください" >&2
  exit 1
fi

exec "$UV" run --no-sync \
  --directory "$COMPILER_DIR" \
  python "$COMPILER_DIR/scripts/api_server.py"
