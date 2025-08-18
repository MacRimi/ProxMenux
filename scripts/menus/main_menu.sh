#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 2.0
# Last Updated: 04/04/2025
# ==========================================================

# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"


if ! command -v dialog &>/dev/null; then
    apt update -qq >/dev/null 2>&1
    apt install -y dialog >/dev/null 2>&1
fi


check_pve9_translation_compatibility() {
    local pve_version
    
    if command -v pveversion &>/dev/null; then
        pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)
    else
        return 0
    fi
    
    if [[ -n "$pve_version" ]] && [[ "$pve_version" -ge 9 ]] && [[ -d "$VENV_PATH" ]]; then
        
        local has_googletrans=false
        local has_cache=false
        
        if [[ -f "$VENV_PATH/bin/pip" ]]; then
            if "$VENV_PATH/bin/pip" list 2>/dev/null | grep -q "googletrans"; then
                has_googletrans=true
            fi
        fi
        
        if [[ -f "$BASE_DIR/cache.json" ]]; then
            has_cache=true
        fi
        
        if [[ "$has_googletrans" = true ]] || [[ "$has_cache" = true ]]; then
            
            dialog --clear \
                --backtitle "ProxMenux - Compatibility Required" \
                --title "Translation Environment Incompatible with PVE $pve_version" \
                --msgbox "NOTICE: You are running Proxmox VE $pve_version with translation components installed.\n\nTranslations are NOT supported in PVE 9+. This causes:\n• Menu loading errors\n• Translation failures\n• System instability\n\nREQUIRED ACTION:\nProxMenux will now automatically reinstall the Normal Version.\n\nThis process will:\n• Remove incompatible translation components\n• Install PVE 9+ compatible version\n• Preserve all your settings and preferences\n\nPress OK to continue with automatic reinstallation..." 20 75
            
            bash <(curl -sSL "$REPO_URL/install_proxmenux.sh")

        fi
        exit 
    fi
}

check_pve9_translation_compatibility

# ==========================================================

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi


if [[ "$PROXMENUX_PVE9_WARNING_SHOWN" = "1" ]]; then

    if ! load_language 2>/dev/null; then
        LANGUAGE="en"
    fi

else
    load_language
    initialize_cache
fi

# ==========================================================

show_menu() {
    local TEMP_FILE
    TEMP_FILE=$(mktemp)

    while true; do

        local menu_title="Main ProxMenux"
        if [[ -n "$PROXMENUX_PVE9_WARNING_SHOWN" ]]; then
            menu_title="Main ProxMenux"
        fi

        dialog --clear \
            --backtitle "ProxMenux" \
            --title "$(translate "$menu_title")" \
            --menu "$(translate "Select an option:")" 20 70 10 \
            1 "$(translate "Settings post-install Proxmox")" \
            2 "$(translate "Help and Info Commands")" \
            3 "$(translate "Hardware: GPUs and Coral-TPU")" \
            4 "$(translate "Create VM from template or script")" \
            5 "$(translate "Disk and Storage Manager")" \
            6 "$(translate "Proxmox VE Helper Scripts")" \
            7 "$(translate "Network Management")" \
            8 "$(translate "Utilities and Tools")" \
            9 "$(translate "Settings")" \
            0 "$(translate "Exit")" 2>"$TEMP_FILE"

        local EXIT_STATUS=$?

        if [[ $EXIT_STATUS -ne 0 ]]; then
            clear
            msg_ok "$(translate "Thank you for using ProxMenux. Goodbye!")"
            rm -f "$TEMP_FILE"
            exit 0
        fi

        OPTION=$(<"$TEMP_FILE")

        case $OPTION in
            1) exec bash <(curl -s "$REPO_URL/scripts/menus/menu_post_install.sh") ;;
            2) exec bash <(curl -s "$REPO_URL/scripts/help_info_menu.sh") ;;
            3) exec bash <(curl -s "$REPO_URL/scripts/menus/hw_grafics_menu.sh") ;;
            4) exec bash <(curl -s "$REPO_URL/scripts/menus/create_vm_menu.sh") ;;
            5) exec bash <(curl -s "$REPO_URL/scripts/menus/storage_menu.sh") ;;
            6) exec bash <(curl -s "$REPO_URL/scripts/menus/menu_Helper_Scripts.sh") ;;
            7) exec bash <(curl -s "$REPO_URL/scripts/menus/network_menu.sh") ;;
            8) exec bash <(curl -s "$REPO_URL/scripts/menus/utilities_menu.sh") ;;
            9) exec bash <(curl -s "$REPO_URL/scripts/menus/config_menu.sh") ;;
            0) clear; msg_ok "$(translate "Thank you for using ProxMenu. Goodbye!")"; rm -f "$TEMP_FILE"; exit 0 ;;
            *) msg_warn "$(translate "Invalid option")"; sleep 2 ;;
        esac
    done
}

show_menu
