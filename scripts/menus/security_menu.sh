#!/bin/bash
# ==========================================================
# ProxMenux - Security Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Dispatcher for security tools shipped with ProxMenux. Loads the
# selected installer/manager script and returns to the main menu
# on cancel.
#
# Features:
#   - Fail2Ban — intrusion prevention for SSH and the Proxmox /
#     ProxMenux Monitor web interfaces, with auto-detected firewall
#     backend (nftables / iptables).
#   - Lynis    — security auditing tool installed from upstream
#     GitHub (always latest), with run-audit and update actions.
# ==========================================================

SCRIPT_TITLE="Security Tools"

BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
LOCAL_SCRIPTS="$BASE_DIR/scripts"

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================
# Security Menu
# ==========================================================
security_menu() {
  while true; do
    local menu_text
    menu_text+="\n$(translate 'Select an option:')"

    local OPTION
    OPTION=$(dialog --backtitle "ProxMenux" \
      --title "$(translate "$SCRIPT_TITLE")" \
      --menu "$menu_text" 20 70 10 \
      "1" "$(translate 'Fail2Ban - Intrusion Prevention')" \
      "2" "$(translate 'Lynis - Security Audit')" \
      3>&1 1>&2 2>&3) || OPTION="0"

    case "$OPTION" in
      1)
        if [[ -f "$LOCAL_SCRIPTS/security/fail2ban_installer.sh" ]]; then
          bash "$LOCAL_SCRIPTS/security/fail2ban_installer.sh"
        else
          msg_error "$(translate 'Script not found:') fail2ban_installer.sh"
          sleep 2
        fi
        ;;
      2)
        if [[ -f "$LOCAL_SCRIPTS/security/lynis_installer.sh" ]]; then
          bash "$LOCAL_SCRIPTS/security/lynis_installer.sh"
        else
          msg_error "$(translate 'Script not found:') lynis_installer.sh"
          sleep 2
        fi
        ;;
      *) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
    esac
  done
}

# ==========================================================
# Main
# ==========================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  security_menu
fi
