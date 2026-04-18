#!/bin/bash
# smoke.sh — 最低限の動作確認 (import / endpoint / collect 起動)
# /improve からブランチ push 前に呼ばれる安全ネット。
#
# Exit 0 = pass, exit 非0 = fail (PR 作成を中止すべき)

set -euo pipefail

COMPILER_DIR="${COMPILER_DIR:-$HOME/Projects/locus-project/locus}"
LOCUS_PRIVATE_DIR="${LOCUS_PRIVATE_DIR:-$HOME/Projects/locus-project/locus-private}"
UV="${UV_BIN:-$(command -v uv || echo /opt/homebrew/bin/uv)}"
PORT_TEST="${SMOKE_PORT:-18083}"   # 本番 :8083 と衝突回避

log() { echo "[smoke] $*"; }

# ── 1. Python import 通過チェック ─────────────────────────────────────
log "1. import check (news_app / collect_news / config)"
"$UV" run --no-sync --directory "$COMPILER_DIR" python -c "
import sys
sys.path.insert(0, '$LOCUS_PRIVATE_DIR/scripts')
sys.path.insert(0, '$COMPILER_DIR/scripts')
import news_app, collect_news, config
print('  imports OK')
"

# ── 2. news_app endpoint 起動チェック ─────────────────────────────────
log "2. news_app endpoint (:${PORT_TEST})"
SERVER_LOG=$(mktemp)
"$UV" run --no-sync --directory "$COMPILER_DIR" \
    uvicorn --app-dir "$LOCUS_PRIVATE_DIR/scripts" news_app:app \
    --host 127.0.0.1 --port "$PORT_TEST" > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null || true; rm -f $SERVER_LOG" EXIT
sleep 3

if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT_TEST/" | grep -q "^200$"; then
    log "  / → 200 OK"
else
    log "  ERROR: / did not return 200"
    cat "$SERVER_LOG" | tail -20
    exit 1
fi

if curl -s "http://127.0.0.1:$PORT_TEST/api/news" | python3 -c "import sys, json; json.load(sys.stdin)" 2>/dev/null; then
    log "  /api/news → valid JSON"
else
    log "  ERROR: /api/news did not return valid JSON"
    exit 1
fi

kill $SERVER_PID 2>/dev/null || true
trap - EXIT
rm -f "$SERVER_LOG"

# ── 3. collect_news.py の dry-run（実 API は叩かない）─────────────────
log "3. collect_news.py syntax check"
"$UV" run --no-sync --directory "$COMPILER_DIR" \
    python -c "import ast; ast.parse(open('$COMPILER_DIR/scripts/collect_news.py').read()); print('  syntax OK')"

log "ALL SMOKE TESTS PASSED"
exit 0
