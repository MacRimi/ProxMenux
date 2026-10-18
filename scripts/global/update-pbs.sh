#!/bin/bash
# ==========================================================
# Proxmox Backup Server Update Script (post-install flows)
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
APT_ENV="env DEBIAN_FRONTEND=noninteractive LC_ALL=C LANG=C"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS/global/pmx_journal.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/pmx_journal.sh"
fi
source "$LOCAL_SCRIPTS/global/common-functions.sh"
source "$LOCAL_SCRIPTS/global/repository-functions.sh"

load_language
initialize_cache

update_pbs() {
    local FUNC_VERSION="1.0"
    pmx_journal_context "update_pbs" "$FUNC_VERSION"

    if ! pmx_is_pbs || [[ "$(pmx_platform_field supported)" != true ]]; then
        msg_error "$(translate 'This operation supports PBS 3 on Debian 12 and PBS 4 on Debian 13.')"
        return 1
    fi

    local start_time
    start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    local screen_capture="/tmp/proxmenux_screen_capture_$$.txt"
    local OS_CODENAME
    OS_CODENAME=$(pmx_platform_field codename)

    {
        echo "=== ProxMenux — Proxmox Backup Server update ==="
        echo "Started: $(date -Iseconds)"
        echo "Host:    $(hostname)"
        echo "Running: proxmox-backup-server $(dpkg-query -W -f='${Version}' proxmox-backup-server 2>/dev/null)"
    } > "$log_file"

    if ! ensure_pbs_repositories; then
        msg_error "$(translate "Failed to configure Proxmox Backup Server repositories")"
        rm -f "$screen_capture"
        return 1
    fi

    local available_space
    available_space=$(df /var/cache/apt/archives | awk 'NR==2 {print int($4/1024)}')
    if [ "$available_space" -lt 1024 ]; then
        msg_error "$(translate "Insufficient disk space. Available: ${available_space}MB")"
        return 1
    fi

    local update_output update_exit_code
    update_output=$(apt-get -o APT::Update::Error-Mode=any update 2>&1)
    update_exit_code=$?
    {
        echo
        echo "--- apt-get update (exit $update_exit_code) ---"
        printf '%s\n' "$update_output"
    } >> "$log_file"
    if [ $update_exit_code -ne 0 ]; then
        msg_error "$(translate "APT refresh failed. Check the PBS subscription and repositories in Administration > Repositories. Log:") $log_file"
        return 1
    fi
    msg_ok "$(translate "Package lists updated successfully")" | tee -a "$screen_capture"

    local current_version available_version
    current_version=$(dpkg-query -W -f='${Version}' proxmox-backup-server 2>/dev/null)
    available_version=$(apt-cache policy proxmox-backup-server 2>/dev/null | awk '/Candidate:/ {print $2; exit}')

    local upgradable upgradable_raw upgradable_list security_updates
    upgradable_raw=$($APT_ENV apt list --upgradable 2>/dev/null \
        | sed '1d' \
        | sed '/^\s*$/d')
    upgradable=$(printf '%s' "$upgradable_raw" | grep -c . )
    security_updates=$(printf '%s\n' "$upgradable_raw" | grep -ci '\-security')
    upgradable_list=$(printf '%s\n' "$upgradable_raw" | pmx_format_upgradable)

    {
        echo
        echo "--- Packages to upgrade ($upgradable) ---"
        [ "$upgradable" -gt 0 ] && printf '%s\n' "$upgradable_list"
    } >> "$log_file"

    local menu_text
    menu_text="$(translate "System Update Information")\n\n"
    menu_text+="$(translate "Current PBS Version"): $current_version\n"
    if [ -n "$available_version" ] && [ "$available_version" != "$current_version" ]; then
        menu_text+="$(translate "Available PBS Version"): $available_version\n"
    fi
    menu_text+="\n$(translate "Package Updates Available"): $upgradable\n"
    menu_text+="$(translate "Security Updates"): $security_updates\n\n"

    if [ "$upgradable" -eq 0 ]; then
        menu_text+="$(translate "System is already up to date")"
        whiptail --title "$(translate "Update Status")" --msgbox "$menu_text" 15 70
        clear
        show_proxmenux_logo
        msg_title "$(translate "$SCRIPT_TITLE")"
        cat "$screen_capture"
        msg_ok "$(translate "System is already up to date. No update needed.")"
        echo -e "\nSystem is already up to date." >> "$log_file"
        rm -f "$screen_capture"
        return 0
    fi

    menu_text+="$(translate "Packages to be upgraded"):\n$upgradable_list\n\n"
    menu_text+="$(translate "Do you want to proceed with the system update?")"
    local proceed=0
    whiptail --title "$(translate "Proxmox Backup Server Update")" --scrolltext --yesno "$menu_text" 24 78 || proceed=1

    clear
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    cat "$screen_capture"

    if [ $proceed -ne 0 ]; then
        msg_info2 "$(translate "Update cancelled by user")"
        rm -f "$screen_capture"
        return 0
    fi

    pmx_record_execution "Upgrade Proxmox Backup Server packages" "apt -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade"
    local dpkg_mark upgrade_exit_code
    dpkg_mark=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "\n--- apt full-upgrade ---" >> "$log_file"
    DEBIAN_FRONTEND=noninteractive apt -y \
        -o Dpkg::Options::='--force-confdef' \
        -o Dpkg::Options::='--force-confold' \
        full-upgrade 2> >(tee -a "$log_file" >&2)
    upgrade_exit_code=$?
    echo -e
    {
        echo
        echo "--- Packages changed (exit $upgrade_exit_code) ---"
        pmx_dpkg_changes_since "$dpkg_mark"
    } >> "$log_file"

    clear
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    cat "$screen_capture"
    rm -f "$screen_capture"

    if [ $upgrade_exit_code -ne 0 ]; then
        msg_error "$(translate "System upgrade failed. Check log: $log_file")"
        echo "Finished: $(date -Iseconds) — upgrade failed (exit $upgrade_exit_code)" >> "$log_file"
        return 1
    fi

    pmx_record_execution "Remove unused packages" "apt-get -y autoremove"
    apt-get -y autoremove > /dev/null 2>&1 || true
    apt-get -y autoclean > /dev/null 2>&1 || true
    msg_ok "$(translate "Cleanup finished")"

    local end_time duration minutes seconds
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    minutes=$((duration / 60))
    seconds=$((duration % 60))

    echo -e "${TAB}${BGN}$(translate "====== PBS UPDATE COMPLETED ======")${CL}"
    echo -e "${TAB}${GN}⏱️  $(translate "Duration")${CL}: ${BL}${minutes}m ${seconds}s${CL}"
    echo -e "${TAB}${GN}📄 $(translate "Log file")${CL}: ${BL}$log_file${CL}"
    echo -e "${TAB}${GN}📦 $(translate "Packages upgraded")${CL}: ${BL}$upgradable${CL}"
    echo -e "${TAB}${GN}🗄️  $(translate "Proxmox Backup Server")${CL}: ${BL}$(dpkg-query -W -f='${Version}' proxmox-backup-server 2>/dev/null) (Debian $OS_CODENAME)${CL}"

    {
        echo
        echo "Finished: $(date -Iseconds) — ${minutes}m ${seconds}s"
        echo "Running: proxmox-backup-server $(dpkg-query -W -f='${Version}' proxmox-backup-server 2>/dev/null)"
    } >> "$log_file"

    if [ -f /var/run/reboot-required ] || [ "$(uname -r)" != "$(ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|/boot/vmlinuz-||' | sort -V | tail -1)" ]; then
        msg_warn "$(translate "A newer kernel is installed. Reboot before the next backup window to use it.")"
    fi
    msg_ok "$(translate "Proxmox Backup Server update completed.")"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_pbs
fi
