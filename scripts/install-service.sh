#!/bin/bash
#
# Trading Bot Systemd Service Installer
# Usage: sudo ./scripts/install-service.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="trading-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Detect user (use SUDO_USER if running with sudo, otherwise current user)
if [ -n "$SUDO_USER" ]; then
    BOT_USER="$SUDO_USER"
else
    BOT_USER="$(whoami)"
fi

BOT_HOME=$(eval echo "~$BOT_USER")
UV_PATH="$BOT_HOME/.local/bin/uv"

# Default trading options
SYMBOLS="${SYMBOLS:-KRW-BTC}"
ISOLATED="${ISOLATED:-true}"
ISOLATED_CAPITAL="${ISOLATED_CAPITAL:-10000}"
COOLDOWN="${COOLDOWN:-60}"

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Trading Bot Service Installer${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Configuration:"
echo "  User: $BOT_USER"
echo "  Project: $PROJECT_DIR"
echo "  UV Path: $UV_PATH"
echo "  Symbols: $SYMBOLS"
echo "  Isolated Mode: $ISOLATED"
echo "  Isolated Capital: ${ISOLATED_CAPITAL} KRW"
echo "  Cooldown: ${COOLDOWN}s"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run with sudo${NC}"
    echo "Usage: sudo ./scripts/install-service.sh"
    exit 1
fi

# Check if uv exists
if [ ! -f "$UV_PATH" ]; then
    echo -e "${YELLOW}Warning: uv not found at $UV_PATH${NC}"
    echo "Trying to find uv..."
    UV_PATH=$(which uv 2>/dev/null || echo "")
    if [ -z "$UV_PATH" ]; then
        echo -e "${RED}Error: uv not found. Install it first:${NC}"
        echo "curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    echo "Found uv at: $UV_PATH"
fi

# Check if .env exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Create it before starting the service:"
    echo "  cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
    echo "  # Edit .env with your API keys"
fi

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Creating service file: $SERVICE_FILE"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Auto Trading Bot (Event-driven BTC Trading with Isolated Mode)
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
Group=$BOT_USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$BOT_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$BOT_HOME

# Main command (streaming mode with isolated trading)
ExecStart=$UV_PATH run python -m trading.main_async --symbols $SYMBOLS --isolated --isolated-capital $ISOLATED_CAPITAL --cooldown $COOLDOWN

# Restart policy
Restart=always
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Create logs directory
echo "Creating logs directory..."
mkdir -p "$PROJECT_DIR/logs"
chown -R "$BOT_USER:$BOT_USER" "$PROJECT_DIR/logs"

# Reload systemd
echo "Reloading systemd..."
systemctl daemon-reload

# Enable service
echo "Enabling service..."
systemctl enable "$SERVICE_NAME"

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Commands:"
echo "  sudo systemctl start $SERVICE_NAME     # Start bot"
echo "  sudo systemctl stop $SERVICE_NAME      # Stop bot"
echo "  sudo systemctl restart $SERVICE_NAME   # Restart bot"
echo "  sudo systemctl status $SERVICE_NAME    # Check status"
echo "  sudo journalctl -u $SERVICE_NAME -f    # View logs"
echo ""
echo "To start the bot now:"
echo -e "  ${GREEN}sudo systemctl start $SERVICE_NAME${NC}"
echo ""
