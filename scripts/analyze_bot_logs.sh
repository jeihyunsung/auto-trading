#!/usr/bin/env bash
# analyze_bot_logs.sh — auto-trading 봇 운영 데이터 한 번에 수집.
#
# Usage:
#   scripts/analyze_bot_logs.sh                # 전체 섹션 출력
#   scripts/analyze_bot_logs.sh snapshot       # 봇 상태 + 잔고 + BTC 가격
#   scripts/analyze_bot_logs.sh trades         # 최근 N일 거래 detail
#   scripts/analyze_bot_logs.sh decisions      # 결정 분포 (action breakdown)
#   scripts/analyze_bot_logs.sh llm            # LLM 호출/캐시/비용 추정
#   scripts/analyze_bot_logs.sh safety         # stop-loss/take-profit/hysteresis 발동 통계
#   scripts/analyze_bot_logs.sh recent         # 최근 30분 봇 동작 흐름
#
# 환경 변수:
#   VM_NAME      (default: trading-bot)
#   VM_ZONE      (default: asia-northeast3-a)
#   DAYS_BACK    (default: 4)
set -euo pipefail

VM_NAME="${VM_NAME:-trading-bot}"
VM_ZONE="${VM_ZONE:-asia-northeast3-a}"
DAYS_BACK="${DAYS_BACK:-4}"

SECTION="${1:-all}"

# ---------- helpers ----------
ssh_cmd() {
    gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" --command="$1" --quiet 2>&1
}

# ---------- snapshot ----------
section_snapshot() {
    echo "=== 봇 상태 + 격리 잔고 + BTC 가격 ==="
    curl -s "https://api.upbit.com/v1/ticker?markets=KRW-BTC" \
        | python3 -c "import json,sys; d=json.load(sys.stdin)[0]; print(f'BTC: {d[\"trade_price\"]:,.0f} KRW (24h: {d[\"signed_change_rate\"]*100:+.2f}%, high24h: {d[\"high_price\"]:,.0f}, low24h: {d[\"low_price\"]:,.0f})')"
    echo ""
    ssh_cmd "
sudo systemctl status trading-bot --no-pager 2>&1 | grep -E 'Active:|Main PID' | head -2
echo ''
echo '--- isolated_balance ---'
cat ~/auto-trading/logs/isolated_balance.json
echo ''
echo '--- watchdog 최근 3 ---'
sudo tail -3 /var/log/trading-bot-watchdog.log 2>/dev/null || echo 'no watchdog log'
"
}

# ---------- trades ----------
section_trades() {
    echo "=== 최근 ${DAYS_BACK}일 거래 + LLM rationale ==="
    ssh_cmd "
TODAY_KST=\$(date +%Y%m%d)
FILES=()
for i in 0 1 2 3 4 5 6; do
    F=~/auto-trading/logs/trades_\$(date -d \"\$i days ago\" +%Y%m%d).jsonl
    if [ -f \$F ]; then
        FILES+=(\$F)
    fi
done
# Pick last DAYS_BACK
FILES_TAKE=\"\${FILES[@]:0:${DAYS_BACK}}\"
cat \${FILES_TAKE} 2>/dev/null | python3 -c \"
import sys, json, re
trades = [json.loads(l) for l in sys.stdin]
trades.sort(key=lambda t: t['timestamp'])
print(f'Total: {len(trades)} trades in last ${DAYS_BACK} days')
print()
for t in trades:
    d, r, o = t['decision'], t['result'], t['order']
    rsi_m = re.search(r'RSI[=:]?\s*([\d.]+)', d.get('rationale',''))
    src = 'stop_loss' if 'stop_loss' in d.get('rationale','') else ('take_profit' if 'take_profit' in d.get('rationale','') else 'llm')
    print(f\\\"{t['timestamp'][:19]} {o['side'].upper():<5} @ {r.get('average_price',0):>12,.0f} qty={r.get('filled_quantity',0):.6f} conf={d['confidence']:>3.0%} RSI={rsi_m.group(1) if rsi_m else '?':<5} [{src}]\\\")

# Aggregates
buys = [t for t in trades if t['order']['side']=='buy']
sells = [t for t in trades if t['order']['side']=='sell']
if buys:
    avg_b = sum(t['result']['filled_quantity']*t['result']['average_price'] for t in buys) / sum(t['result']['filled_quantity'] for t in buys)
    print(f'\\\\nAvg BUY price: {avg_b:,.0f}')
if sells:
    avg_s = sum(t['result']['filled_quantity']*t['result']['average_price'] for t in sells) / sum(t['result']['filled_quantity'] for t in sells)
    print(f'Avg SELL price: {avg_s:,.0f}')
if buys and sells:
    print(f'Spread: {avg_s - avg_b:+,.0f} ({(avg_s-avg_b)/avg_b*100:+.2f}%)')
\"
"
}

# ---------- decisions distribution ----------
section_decisions() {
    echo "=== 최근 ${DAYS_BACK}일 결정 분포 + confidence range ==="
    ssh_cmd "
for i in \$(seq 0 \$((${DAYS_BACK}-1))); do
    D=\$(date -d \"\$i days ago\" +%Y%m%d)
    F=~/auto-trading/logs/decisions_\${D}.jsonl
    if [ -f \$F ]; then
        python3 -c \"
import json
from collections import Counter
with open('\$F') as f:
    decs = [json.loads(l) for l in f]
actions = Counter(d.get('action','?') for d in decs)
total = len(decs)
parts = ' '.join(f'{a}:{c}' for a,c in actions.most_common())
confs = [d.get('confidence',0) for d in decs]
conf_str = f'{min(confs):.2f}-{max(confs):.2f}' if confs else ''
print(f'$D ({total} decisions): {parts}  conf={conf_str}')
\"
    fi
done
"
}

# ---------- LLM stats ----------
section_llm() {
    echo "=== LLM 호출/캐시 + 비용 추정 (최근 ${DAYS_BACK} UTC days) ==="
    ssh_cmd "
echo \"Day(UTC) | trig | dec | openai_calls | cache_hits | hit_rate%\"
echo \"---------+------+-----+--------------+------------+----------\"
TOT_LLM=0
TOT_CACHE=0
for i in \$(seq 0 \$((${DAYS_BACK}-1))); do
    D=\$(date -u -d \"\$i days ago\" +%Y-%m-%d)
    LLM=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'HTTP Request: POST https://api.openai.com')
    CACHE=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'LLM cache hit')
    TRIG=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'Dispatching batch')
    DEC=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'Decision: ')
    SUM=\$((LLM + CACHE))
    HIT=\$(awk \"BEGIN {printf \\\"%.1f\\\", \$SUM ? \$CACHE/\$SUM*100 : 0}\")
    printf \"%s | %4d | %3d | %12d | %10d | %5s%%\n\" \"\$D\" \"\$TRIG\" \"\$DEC\" \"\$LLM\" \"\$CACHE\" \"\$HIT\"
    TOT_LLM=\$((TOT_LLM + LLM))
    TOT_CACHE=\$((TOT_CACHE + CACHE))
done
echo ''
AVG=\$(( TOT_LLM / ${DAYS_BACK} ))
echo \"Daily avg OpenAI calls: \${AVG}\"
# Token + cost estimate using fixed assumptions
python3 -c \"
calls = $TOT_LLM
days = ${DAYS_BACK}
avg = calls / days if days else 0
# Token estimates from observed rationale length 1050 chars ≈ 700 tokens output
# Input prompt ≈ 2100 tokens
in_tok = avg * 2100
out_tok = avg * 700
# gpt-5-nano estimated pricing (\$/1M)
p_in_nano, p_out_nano = 0.025, 0.20
# gpt-4o-mini fallback pricing
p_in_mini, p_out_mini = 0.15, 0.60
cost_nano = (in_tok/1e6 * p_in_nano) + (out_tok/1e6 * p_out_nano)
cost_mini = (in_tok/1e6 * p_in_mini) + (out_tok/1e6 * p_out_mini)
print(f'Daily token use: in={in_tok:,.0f}, out={out_tok:,.0f}')
print(f'Cost @ gpt-5-nano (\\\\\$0.025/\\\\\$0.20): ~\\\\\${cost_nano:.3f}/day = ~\\\\\${cost_nano*30:.2f}/month')
print(f'Cost @ gpt-4o-mini (\\\\\$0.15/\\\\\$0.60): ~\\\\\${cost_mini:.3f}/day = ~\\\\\${cost_mini*30:.2f}/month')
\"
"
}

# ---------- safety triggers ----------
section_safety() {
    echo "=== Safety triggers (최근 ${DAYS_BACK}일) ==="
    ssh_cmd "
SL=0; TP=0; HYS=0; CAP=0; SDC=0; CUM=0
for i in \$(seq 0 \$((${DAYS_BACK}-1))); do
    D=\$(date -u -d \"\$i days ago\" +%Y-%m-%d)
    DSL=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'STOP-LOSS triggered')
    DTP=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'TAKE-PROFIT triggered')
    DHYS=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'Hysteresis blocked')
    DCAP=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'BUY confidence capped')
    DSDC=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'Same-direction cooldown')
    DCUM=\$(sudo journalctl -u trading-bot --since \"\${D} 00:00:00\" --until \"\${D} 23:59:59\" --no-pager 2>&1 | grep -c 'cumulative blocks')
    echo \"\${D}: stop_loss=\${DSL} take_profit=\${DTP} hyst_blocked=\${DHYS} buy_cap=\${DCAP} same_dir_cooldown=\${DSDC} cumulative=\${DCUM}\"
    SL=\$((SL+DSL)); TP=\$((TP+DTP)); HYS=\$((HYS+DHYS)); CAP=\$((CAP+DCAP)); SDC=\$((SDC+DSDC)); CUM=\$((CUM+DCUM))
done
echo ''
echo \"Totals: stop_loss=\${SL}, take_profit=\${TP}, hyst_blocked=\${HYS}, buy_cap=\${CAP}, same_dir=\${SDC}, cumulative=\${CUM}\"
"
}

# ---------- recent ----------
section_recent() {
    echo "=== 최근 30분 동작 흐름 ==="
    ssh_cmd "
sudo journalctl -u trading-bot --since '30 minutes ago' --no-pager 2>&1 \
    | grep -E 'Decision:|MTF Analysis|Portfolio.*Exposure|Hysteresis|Position sizing|TAKE-PROFIT|STOP-LOSS|BUY confidence capped|Same-direction|stop_loss|take_profit' \
    | tail -20
"
}

# ---------- dispatch ----------
case "$SECTION" in
    snapshot) section_snapshot ;;
    trades) section_trades ;;
    decisions) section_decisions ;;
    llm) section_llm ;;
    safety) section_safety ;;
    recent) section_recent ;;
    all|*)
        section_snapshot
        echo ""
        section_decisions
        echo ""
        section_trades
        echo ""
        section_safety
        echo ""
        section_llm
        echo ""
        section_recent
        ;;
esac
