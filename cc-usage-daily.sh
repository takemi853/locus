#!/bin/bash
# cc-usage-daily.sh — 当日 (JST) の Claude Code トークン使用量を knowledge/inbox/cc-usage/ に保存
#
# launchd (com.locus.cc-usage.plist) から毎晩 23:55 JST に呼ばれる想定。
# ccusage は ~/.claude/projects/*/ 配下の JSONL を読むので、各マシン独自のデータを
# それぞれ書き出す（hostname を付けて衝突回避）。
#
# Usage:
#   ./cc-usage-daily.sh                # 今日 (JST) のみ
#   ./cc-usage-daily.sh 20260430       # 指定日のみ

set -euo pipefail

# nvm の最新 node を PATH に（npx 用）
NVM_NODE_DIR="$HOME/.nvm/versions/node"
if [ -d "$NVM_NODE_DIR" ]; then
  LATEST_NODE=$(ls "$NVM_NODE_DIR" 2>/dev/null | sort -V | tail -1)
  if [ -n "$LATEST_NODE" ]; then
    export PATH="$NVM_NODE_DIR/$LATEST_NODE/bin:$PATH"
  fi
fi

DATE_ARG="${1:-$(TZ=Asia/Tokyo date +%Y%m%d)}"
DATE_HUMAN=$(TZ=Asia/Tokyo date -j -f %Y%m%d "$DATE_ARG" +%F 2>/dev/null || echo "$DATE_ARG")

LOCUS_PRIVATE_DIR="${LOCUS_PRIVATE_DIR:-$HOME/Projects/locus-project/locus-private}"
OUT_DIR="$LOCUS_PRIVATE_DIR/knowledge/inbox/cc-usage"
mkdir -p "$OUT_DIR"

HOST=$(hostname -s)
OUT="$OUT_DIR/${DATE_HUMAN}-${HOST}.json"

ts() { TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S'; }
echo "[$(ts)] [cc-usage] $DATE_HUMAN ($HOST) → $OUT"

npx -y ccusage@latest daily \
  -z Asia/Tokyo \
  --since "$DATE_ARG" \
  --until "$DATE_ARG" \
  --json \
  > "$OUT"

# 簡易サマリーをログに残す（cost と output_tokens だけ）
python3 -c "
import json
with open('$OUT') as f: d = json.load(f)
days = d.get('daily', [])
if days:
    x = days[0]
    print(f'  cost=\${x.get(\"totalCost\",0):.2f}  output={x.get(\"outputTokens\",0):,}  cache_r={x.get(\"cacheReadTokens\",0):,}  models={x.get(\"modelsUsed\",[])}')
else:
    print('  (no data for this day)')
" 2>/dev/null || true
