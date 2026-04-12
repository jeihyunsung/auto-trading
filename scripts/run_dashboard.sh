#!/bin/bash
# Run the trading dashboard

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default settings
PORT=${DASHBOARD_PORT:-8501}
LOG_DIR=${TRADING_LOG_DIR:-"$PROJECT_DIR/logs"}

# Export log directory for dashboard
export TRADING_LOG_DIR="$LOG_DIR"

echo "Starting Trading Dashboard..."
echo "  Port: $PORT"
echo "  Log dir: $LOG_DIR"
echo ""

# Run streamlit
cd "$PROJECT_DIR"
streamlit run src/trading/dashboard/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
