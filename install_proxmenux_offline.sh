#!/bin/bash

# ==========================================================
# ProxMenux Offline Installer
# ==========================================================
# This script clones the ProxMenux repository to a temporary
# location, runs the installer, and then cleans up.
# ==========================================================

set -e  # Exit on error

# Configuration
REPO_URL="https://github.com/c78-contrib/ProxMenuxOffline.git"
TEMP_DIR="/tmp/proxmenux-install-$$"
INSTALLER_SCRIPT="install_proxmenux.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Cleanup function
cleanup() {
    if [ -d "$TEMP_DIR" ]; then
        echo -e "${YELLOW}Cleaning up temporary files...${NC}"
        rm -rf "$TEMP_DIR"
        echo -e "${GREEN}Cleanup completed.${NC}"
    fi
}

# Set trap to ensure cleanup on exit
trap cleanup EXIT

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root.${NC}"
    exit 1
fi

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Git is not installed. Installing git...${NC}"
    apt-get update -qq
    apt-get install -y git
fi

# Clone repository
echo -e "${GREEN}Cloning ProxMenux repository...${NC}"
if ! git clone --depth 1 "$REPO_URL" "$TEMP_DIR" 2>&1; then
    echo -e "${RED}Error: Failed to clone repository from $REPO_URL${NC}"
    exit 1
fi

# Change to temporary directory
cd "$TEMP_DIR"

# Check if installer exists
if [ ! -f "$INSTALLER_SCRIPT" ]; then
    echo -e "${RED}Error: Installer script '$INSTALLER_SCRIPT' not found in repository.${NC}"
    exit 1
fi

# Make installer executable
chmod +x "$INSTALLER_SCRIPT"

# Run the installer
echo -e "${GREEN}Running ProxMenux installer...${NC}"
echo "----------------------------------------"
bash "$INSTALLER_SCRIPT"

echo "----------------------------------------"
echo -e "${GREEN}Installation completed successfully!${NC}"
