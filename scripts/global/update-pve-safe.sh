#!/bin/bash
# ==========================================================
# Proxmox VE Update Script — Safe / Non-Invasive Variant
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# ==========================================================
# Description:
# Update path intended for a Proxmox host ALREADY in
# production. Unlike scripts/global/update-pve8.sh and
# update-pve9_2.sh (invoked by post_install), this variant
# NEVER modifies the operator's own configuration:
#
#   - Does NOT disable Enterprise / Ceph repositories
#   - Does NOT delete legacy repo files
#   - Does NOT overwrite proxmox.sources / debian.sources
#     when they already exist
#   - Does NOT purge alternative NTP services
#   - Does NOT force-install zfsutils / chrony /
#     proxmox-backup-restore-image
#   - Does NOT write no-firmware-warnings.conf
#
# What it DOES:
#   1. Sanity checks (disk space, network)
#   2. ensure_repositories() — only when repos are MISSING
#   3. apt-get update, with automatic GPG key import when apt
#      reports NO_PUBKEY (any repo, user's or ours)
#   4. cleanup_duplicate_repos() — exact URL+Suite+Component
#      match against proxmox.sources / debian.sources; leaves
#      unrelated custom `download.proxmox.com/*` and
#      user-authored pve-*.list files alone; backs each file
#      up before modifying
#   5. Detect pending upgrades + security count
#   6. Confirmation dialog
#   7. apt-get full-upgrade with --force-confdef / --force-confold
#      (never overwrites the operator's edited config files)
#   8. lvm_repair_check() — refreshes VG metadata when disks
#      passed through to guest VMs (DSM, TrueNAS, …) come back
#      with old PV headers
#   9. apt-get autoremove + autoclean
#
# Reboot detection is handled by the caller (utilities/proxmox_update.sh).
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
APT_ENV="env DEBIAN_FRONTEND=noninteractive LC_ALL=C LANG=C"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

download_common_functions() {
    if ! source "$LOCAL_SCRIPTS/global/common-functions.sh"; then
        return 1
    fi
}

# ensure_repositories() lives with the install helpers.
source_install_functions() {
    local f="$LOCAL_SCRIPTS/global/utils-install-functions.sh"
    if [[ -f "$f" ]]; then
        source "$f"
    fi
}

update_pve_safe() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)
    if [[ -z "$pve_version" ]]; then
        msg_error "$(translate "Unable to detect Proxmox version")"
        return 1
    fi

    local start_time
    start_time=$(date +%s)
    local log_file="/var/log/proxmox-update-$(date +%Y%m%d-%H%M%S).log"
    # Screen capture: replay the pre-upgrade context lines after `clear`
    # so the operator keeps the visual history around the noisy apt run.
    local screen_capture="/tmp/proxmenux_screen_capture_$$.txt"
    : > "$screen_capture"

    download_common_functions
    source_install_functions

    {
        msg_info2 "$(translate "Detected: Proxmox VE $pve_version — running safe update path")"
    } | tee -a "$screen_capture"

    # ── 1. Sanity checks ──
    local available_space
    available_space=$(df /var/cache/apt/archives | awk 'NR==2 {print int($4/1024)}')
    if [ "$available_space" -lt 1024 ]; then
        msg_error "$(translate "Insufficient disk space. Available: ${available_space}MB")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        rm -f "$screen_capture"
        return 1
    fi

    if ! ping -c 1 download.proxmox.com >/dev/null 2>&1; then
        msg_error "$(translate "Cannot reach Proxmox repositories")"
        echo -e
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        rm -f "$screen_capture"
        return 1
    fi

    # ── 2. ensure_repositories: adds base Proxmox+Debian repos only if
    # they don't already exist. On a configured host this is a no-op. ──
    if declare -f ensure_repositories >/dev/null 2>&1; then
        ensure_repositories
    fi

    # ── 3. apt-get update with automatic key recovery ──
    local update_output update_exit_code
    update_output=$(apt-get update 2>&1)
    update_exit_code=$?

    if [ $update_exit_code -eq 0 ]; then
        msg_ok "$(translate "Package lists updated successfully")" | tee -a "$screen_capture"
    else
        if echo "$update_output" | grep -Eq "NO_PUBKEY|GPG error"; then
            local key
            key=$(echo "$update_output" | sed -n 's/.*NO_PUBKEY \([0-9A-F]\{8,40\}\).*/\1/p' | head -1)
            if [ -n "$key" ]; then
                mkdir -p /etc/apt/keyrings
                if command -v gpg >/dev/null 2>&1; then
                    if gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "$key" \
                    && gpg --batch --export "$key" | gpg --dearmor -o "/etc/apt/keyrings/${key}.gpg"; then
                        msg_ok "$(translate "Imported missing GPG key: $key")" | tee -a "$screen_capture"
                    else
                        msg_warn "$(translate "Keyrings method failed; trying apt-key fallback")"
                        apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "$key" >/dev/null 2>&1 || true
                    fi
                else
                    msg_warn "$(translate "gpg not found; trying apt-key fallback")"
                    apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "$key" >/dev/null 2>&1 || true
                fi
            fi
            if apt-get update > "$log_file" 2>&1; then
                msg_ok "$(translate "Package lists updated after GPG fix")" | tee -a "$screen_capture"
            else
                msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
                rm -f "$screen_capture"
                return 1
            fi
        elif echo "$update_output" | grep -Eq "404|Failed to fetch"; then
            msg_warn "$(translate "Some repositories are not available, continuing with available ones...")"
        else
            msg_error "$(translate "Failed to update package lists. Check log: $log_file")"
            echo "Error details: $update_output"
            rm -f "$screen_capture"
            return 1
        fi
    fi

    # ── 4. Precise duplicate cleanup (exact URL+Suite+Component match,
    # backs up files before modifying). Skipped if unavailable. ──
    if declare -f cleanup_duplicate_repos >/dev/null 2>&1; then
        cleanup_duplicate_repos
    fi

    # ── 5-6. Detect + confirm ──
    local current_pve_version available_pve_version upgradable security_updates
    current_pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    available_pve_version=$(apt-cache policy pve-manager 2>/dev/null | grep -oP 'Candidate: \K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    upgradable=$($APT_ENV apt list --upgradable 2>/dev/null | sed '1d' | sed '/^\s*$/d' | wc -l)
    security_updates=$($APT_ENV apt list --upgradable 2>/dev/null | sed '1d' | grep -ci '\-security')

    local menu_text
    menu_text="$(translate "System Update Information")\n\n"
    menu_text+="$(translate "Current PVE Version"): $current_pve_version\n"
    if [ -n "$available_pve_version" ] && [ "$available_pve_version" != "$current_pve_version" ]; then
        menu_text+="$(translate "Available PVE Version"): $available_pve_version\n"
    fi
    menu_text+="\n$(translate "Package Updates Available"): $upgradable\n"
    menu_text+="$(translate "Security Updates"): $security_updates\n\n"

    if [ "$upgradable" -eq 0 ]; then
        menu_text+="$(translate "System is already up to date")"
        whiptail --title "$(translate "Update Status")" --msgbox "$menu_text" 15 70
        apt-get -y autoremove >/dev/null 2>&1 || true
        apt-get -y autoclean >/dev/null 2>&1 || true
        rm -f "$screen_capture"
        return 0
    fi

    menu_text+="$(translate "Do you want to proceed with the system update?")"
    if ! whiptail --title "$(translate "Proxmox Update")" --yesno "$menu_text" 18 70; then
        msg_info2 "$(translate "Update cancelled by user")"
        apt-get -y autoremove >/dev/null 2>&1 || true
        apt-get -y autoclean >/dev/null 2>&1 || true
        rm -f "$screen_capture"
        return 0
    fi

    # ── 7. Full upgrade — --force-confdef/confold preserves user-edited configs ──
    # Redraw the ProxMenux frame before apt starts printing so the operator
    # keeps the visual context around the noisy upgrade output.
    clear
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    cat "$screen_capture"

    # apt's own progress bar (Progress: [ %]) prints on stderr and only
    # when stdout is a TTY. We pipe stderr through tee to keep a log copy
    # while letting apt keep its interactive stdout, so the native bar
    # keeps rendering at the bottom of the terminal as the user expects.
    DEBIAN_FRONTEND=noninteractive apt -y \
        -o Dpkg::Options::='--force-confdef' \
        -o Dpkg::Options::='--force-confold' \
        full-upgrade 2> >(tee -a "$log_file" >&2)
    local upgrade_exit_code=$?
    echo -e

    # Redraw once more so the wrap-up (LVM check, cleanup, summary) reads
    # cleanly instead of scrolling under half-a-screen of apt noise.
    clear
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    cat "$screen_capture"

    if [ $upgrade_exit_code -ne 0 ]; then
        msg_error "$(translate "System upgrade failed. Check log: $log_file")"
        rm -f "$screen_capture"
        return 1
    fi

    msg_ok "$(translate "System upgrade completed")"

    # ── 8. LVM header repair (only touches VGs actually flagged as stale) ──
    if declare -f lvm_repair_check >/dev/null 2>&1; then
        lvm_repair_check
    fi

    # ── 9. DKMS driver rebuild if a new kernel was staged ──
    if declare -f pmx_rebuild_dkms_after_kernel >/dev/null 2>&1; then
        pmx_rebuild_dkms_after_kernel
    fi

    # ── 10. Final cleanup ──
    apt-get -y autoremove >/dev/null 2>&1 || true
    apt-get -y autoclean >/dev/null 2>&1 || true
    msg_ok "$(translate "Cleanup finished")"

    local end_time duration minutes seconds
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    minutes=$((duration / 60))
    seconds=$((duration % 60))

    echo -e "${TAB}${BGN}$(translate "====== PVE UPDATE COMPLETED ======")${CL}"
    echo -e "${TAB}${GN}⏱️  $(translate "Duration")${CL}: ${BL}${minutes}m ${seconds}s${CL}"
    echo -e "${TAB}${GN}📄 $(translate "Log file")${CL}: ${BL}$log_file${CL}"
    echo -e "${TAB}${GN}📦 $(translate "Packages upgraded")${CL}: ${BL}$upgradable${CL}"
    echo -e "${TAB}${GN}🖥️  $(translate "Proxmox VE")${CL}: ${BL}${available_pve_version:-$current_pve_version}${CL}"

    msg_ok "$(translate "Proxmox VE safe update completed")"
    rm -f "$screen_capture"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    update_pve_safe
fi
