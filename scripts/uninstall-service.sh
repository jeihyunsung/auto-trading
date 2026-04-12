#!/bin/bash
#
# Trading Bot Systemd Service Uninstaller
# Usage: sudo ./scripts/uninstall-service.sh
#

set -e

SERVICE_NAME="trading-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "Uninstalling $SERVICE_NAME service..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run with sudo${NC}"
    exit 1
fi

# Stop service if running
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Stopping service..."
    systemctl stop "$SERVICE_NAME"
fi

# Disable service
if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Disabling service..."
    systemctl disable "$SERVICE_NAME"
fi

# Remove service file
if [ -f "$SERVICE_FILE" ]; then
    echo "Removing service file..."
    rm "$SERVICE_FILE"
fi

# Reload systemd
systemctl daemon-reload

echo ""
echo -e "${GREEN}Service uninstalled successfully.${NC}"
echo "Note: Logs in ./logs/ were preserved."
