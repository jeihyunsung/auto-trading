#!/bin/bash
#
# Trading Bot Status & Logs Viewer
# Usage: ./scripts/bot-status.sh [logs|report|portfolio]
#

SERVICE_NAME="trading-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ISOLATED_STATE="$PROJECT_DIR/logs/isolated_balance.json"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Function to display isolated mode portfolio
show_isolated_portfolio() {
    if [ -f "$ISOLATED_STATE" ]; then
        echo -e "${CYAN}=== Isolated Mode Portfolio ===${NC}"

        # Parse JSON using python (more reliable than jq for decimals)
        python3 << 'PYEOF'
import json

try:
    with open("'"$ISOLATED_STATE"'") as f:
        state = json.load(f)

    krw = float(state.get("krw", 0))
    btc = float(state.get("btc", 0))
    initial_capital = float(state.get("initial_capital", 10000))
    total_invested = float(state.get("total_invested", 0))
    total_fees = float(state.get("total_fees", 0))
    last_updated = state.get("last_updated", "N/A")[:19]

    print(f"  Initial Capital: {initial_capital:,.0f} KRW")
    print(f"  KRW Balance:     {krw:,.0f} KRW")
    print(f"  BTC Balance:     {btc:.8f} BTC")
    print(f"  Total Invested:  {total_invested:,.0f} KRW")
    print(f"  Total Fees:      {total_fees:,.0f} KRW")
    print(f"  Last Updated:    {last_updated}")

    # Note: Current value requires BTC price which we don't have here
    if btc > 0:
        print(f"  (Run with BTC price to see current value)")

except Exception as e:
    print(f"  Error reading state: {e}")
PYEOF
        echo ""
    else
        echo -e "${YELLOW}Isolated mode not active (no state file)${NC}"
        echo ""
    fi
}

case "${1:-status}" in
    status)
        echo -e "${GREEN}=== Service Status ===${NC}"
        systemctl status "$SERVICE_NAME" --no-pager 2>/dev/null || echo "Service not installed"
        echo ""

        # Show isolated portfolio
        show_isolated_portfolio

        echo -e "${GREEN}=== Latest Performance ===${NC}"
        LATEST_REPORT=$(ls -t "$PROJECT_DIR"/logs/daily_report_*.md 2>/dev/null | head -1)
        if [ -n "$LATEST_REPORT" ]; then
            # Extract key metrics
            grep -E "(Total Return|Max Drawdown|Alpha|Total Trades)" "$LATEST_REPORT" | head -5
        else
            echo "No performance report found"
        fi
        echo ""

        echo -e "${GREEN}=== Recent Logs (last 10 lines) ===${NC}"
        journalctl -u "$SERVICE_NAME" -n 10 --no-pager 2>/dev/null || echo "No logs available"
        ;;

    logs)
        echo "Showing live logs (Ctrl+C to exit)..."
        journalctl -u "$SERVICE_NAME" -f
        ;;

    report)
        LATEST_REPORT=$(ls -t "$PROJECT_DIR"/logs/daily_report_*.md 2>/dev/null | head -1)
        if [ -n "$LATEST_REPORT" ]; then
            echo -e "${GREEN}=== $LATEST_REPORT ===${NC}"
            cat "$LATEST_REPORT"
        else
            echo "No performance report found"
        fi
        ;;

    portfolio)
        show_isolated_portfolio
        # Show recent trade logs from daily trade file
        TODAY=$(date +%Y%m%d)
        TRADE_LOG="$PROJECT_DIR/logs/trades_${TODAY}.jsonl"
        if [ -f "$TRADE_LOG" ]; then
            echo -e "${CYAN}=== Recent Trades (Today) ===${NC}"
            tail -5 "$TRADE_LOG" | python3 -c "
import sys
import json

for line in sys.stdin:
    try:
        trade = json.loads(line.strip())
        action = trade.get('decision', {}).get('action', '?')
        ts = trade.get('timestamp', '')[:16]
        result = trade.get('result', {})
        qty = result.get('filled_quantity', 0)
        price = result.get('average_price', 0)
        status = result.get('status', 'unknown')
        emoji = '📈' if action == 'BUY' else '📉'
        print(f'  {emoji} {action}: {qty:.8f} BTC @ {price:,.0f} ({status}) [{ts}]')
    except:
        pass
"
        else
            echo -e "  No trades today"
        fi
        ;;

    *)
        echo "Usage: $0 [status|logs|report|portfolio]"
        echo "  status    - Show service status and summary (default)"
        echo "  logs      - Show live logs (follow mode)"
        echo "  report    - Show latest performance report"
        echo "  portfolio - Show isolated mode portfolio details"
        ;;
esac
