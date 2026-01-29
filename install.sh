#!/usr/bin/env bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}📨 tg-send-cli Installer${NC}"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv not found. Installing uv...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source the env to get uv in PATH
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}Failed to install uv. Please install it manually:${NC}"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    echo -e "${GREEN}✓ uv installed${NC}"
fi

echo -e "${CYAN}Installing tg-send-cli...${NC}"

# Install the tool using uv
uv tool install tg-send-cli

echo ""
echo -e "${GREEN}✓ Installation complete!${NC}"
echo ""
echo -e "Usage: ${BOLD}tgsend <file>${NC}"
echo ""
echo -e "Example:"
echo -e "  ${CYAN}tgsend photo.jpg${NC}"
echo ""
echo -e "${YELLOW}Note:${NC} On first run, you'll need to set up Telegram API credentials."
