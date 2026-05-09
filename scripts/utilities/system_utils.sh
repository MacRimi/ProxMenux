#!/bin/bash
# ==========================================================
# ProxMenux - System Utilities Installer
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.2
# ==========================================================
# Description:
# Interactive installer for 26 curated CLI utilities packaged in
# the canonical PROXMENUX_UTILS list (defined in
# global/utils-install-functions.sh). Uses the shared
# ensure_repositories() + install_single_package() pair to keep the
# repo configuration and feedback consistent with the rest of the
# project.
#
# Features:
#   - Custom selection: dialog checklist of all 26 packages.
#   - Install ALL utilities: one-click for all of PROXMENUX_UTILS.
#   - Predefined groups (basic / dev / compression / multiplexers /
#     analysis / network) for quick targeted installs.
#   - Verify installations: checks every PROXMENUX_UTILS command for
#     availability and shows an Available / Missing summary.
#   - Per-package feedback (install_single_package returns 0 ok / 1
#     failed / 2 installed-but-command-not-found-yet).
#   - Hash refresh after each install to surface new commands.
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# Load shared utility installation functions
if [[ -f "$LOCAL_SCRIPTS/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/utils-install-functions.sh"
fi

# ==========================================================
install_system_utils() {

    show_main_utilities_menu() {
        local choice
        choice=$(dialog --clear --backtitle "ProxMenux" \
            --title "$(translate "Utilities Installation Menu")" \
            --menu "$(translate "Select an option"):" 20 70 12 \
            "1" "$(translate "Custom selection")" \
            "2" "$(translate "Install ALL utilities")" \
            "3" "$(translate "Install basic utilities") (grc, htop, tree, curl, wget)" \
            "4" "$(translate "Install development tools") (git, vim, nano)" \
            "5" "$(translate "Install compression tools") (zip, unzip, rsync)" \
            "6" "$(translate "Install terminal multiplexers") (screen, tmux)" \
            "7" "$(translate "Install analysis tools") (jq, ncdu, iotop)" \
            "8" "$(translate "Install network tools") (iperf3, nethogs, nmap, tcpdump)" \
            "9" "$(translate "Verify installations")" \
            "0" "$(translate "Return to main menu")" 2>&1 >/dev/tty)
        echo "$choice"
    }

    show_custom_selection() {
        local utilities=()
        for util_entry in "${PROXMENUX_UTILS[@]}"; do
            IFS=':' read -r pkg cmd desc <<< "$util_entry"
            utilities+=("$pkg" "$(translate "$desc")" "OFF")
        done

        local selected
        selected=$(dialog --clear --backtitle "ProxMenux" \
            --title "$(translate "Select utilities to install")" \
            --checklist "$(translate "Use SPACE to select/deselect, ENTER to confirm")" \
            25 80 20 "${utilities[@]}" 2>&1 >/dev/tty)
        echo "$selected"
    }

    install_utility_group() {
        local group_name="$1"
        shift
        local utilities=("$@")

        clear
        show_proxmenux_logo
        msg_title "$(translate "Installing group"): $group_name"

        if ! ensure_repositories; then
            msg_error "$(translate "Failed to configure repositories. Installation aborted.")"
            return 1
        fi

        local failed=0 success=0 warning=0

        for util_info in "${utilities[@]}"; do
            IFS=':' read -r package command description <<< "$util_info"
            install_single_package "$package" "$command" "$description"
            case $? in
                0) success=$((success + 1)) ;;
                1) failed=$((failed + 1)) ;;
                2) warning=$((warning + 1)) ;;
            esac
            sleep 2
        done

        echo
        msg_info2 "$(translate "Installation summary") - $group_name:"
        msg_ok "$(translate "Successful"): $success"
        [ $warning -gt 0 ] && msg_warn "$(translate "With warnings"): $warning"
        [ $failed -gt 0 ] && msg_error "$(translate "Failed"): $failed"

        dialog --clear --backtitle "ProxMenux" \
            --title "$(translate "Installation Complete")" \
            --msgbox "$(translate "Group"): $group_name\n$(translate "Successful"): $success\n$(translate "With warnings"): $warning\n$(translate "Failed"): $failed" 10 50
    }

    install_selected_utilities() {
        local selected="$1"

        if [ -z "$selected" ]; then
            dialog --clear --backtitle "ProxMenux" \
                --title "$(translate "No Selection")" \
                --msgbox "$(translate "No utilities were selected")" 8 40
            return
        fi

        clear
        show_proxmenux_logo
        msg_title "$(translate "Installing selected utilities")"

        if ! ensure_repositories; then
            msg_error "$(translate "Failed to configure repositories. Installation aborted.")"
            return 1
        fi

        # Build lookup table from global PROXMENUX_UTILS
        declare -A pkg_cmd_map pkg_desc_map
        for util_entry in "${PROXMENUX_UTILS[@]}"; do
            IFS=':' read -r epkg ecmd edesc <<< "$util_entry"
            pkg_cmd_map[$epkg]="$ecmd"
            pkg_desc_map[$epkg]="$edesc"
        done

        local failed=0 success=0 warning=0
        local selected_array
        IFS=' ' read -ra selected_array <<< "$selected"

        for util in "${selected_array[@]}"; do
            util=$(echo "$util" | tr -d '"')
            local verify_command="${pkg_cmd_map[$util]:-$util}"
            local description="${pkg_desc_map[$util]:-$util}"
            install_single_package "$util" "$verify_command" "$description"
            case $? in
                0) success=$((success + 1)) ;;
                1) failed=$((failed + 1)) ;;
                2) warning=$((warning + 1)) ;;
            esac
            sleep 2
        done

        hash -r 2>/dev/null
        echo
        msg_info2 "$(translate "Installation summary"):"
        msg_ok "$(translate "Successful"): $success"
        [ $warning -gt 0 ] && msg_warn "$(translate "With warnings"): $warning"
        [ $failed -gt 0 ] && msg_error "$(translate "Failed"): $failed"

        dialog --clear --backtitle "ProxMenux" \
            --title "$(translate "Installation Complete")" \
            --msgbox "$(translate "Selected utilities installation completed")\n$(translate "Successful"): $success\n$(translate "With warnings"): $warning\n$(translate "Failed"): $failed" 12 60
    }

    verify_installations() {
        clear
        show_proxmenux_logo
        msg_info "$(translate "Verifying all utilities status")..."

        local available=0 missing=0 status_text=""

        for util_entry in "${PROXMENUX_UTILS[@]}"; do
            IFS=':' read -r pkg cmd desc <<< "$util_entry"
            if command -v "$cmd" >/dev/null 2>&1; then
                status_text+="\n✓ $cmd - $desc"
                available=$((available + 1))
            else
                status_text+="\n✗ $cmd - $desc"
                missing=$((missing + 1))
            fi
        done

        cleanup

        local summary="$(translate "Total"): $((available + missing))\n$(translate "Available"): $available\n$(translate "Missing"): $missing"

        dialog --clear --backtitle "ProxMenux" \
            --title "$(translate "Utilities Verification")" \
            --msgbox "$summary$status_text" 25 80
    }

    # Main menu loop
    while true; do
        choice=$(show_main_utilities_menu)
        case $choice in
            1)
                selected=$(show_custom_selection)
                install_selected_utilities "$selected"
                ;;
            2)
                install_utility_group "$(translate "ALL Utilities")" "${PROXMENUX_UTILS[@]}"
                ;;
            3)
                basic_utils=(
                    "grc:grc:Generic Colouriser"
                    "htop:htop:Process monitor"
                    "tree:tree:Directory structure"
                    "curl:curl:Data transfer"
                    "wget:wget:Web downloader"
                )
                install_utility_group "$(translate "Basic Utilities")" "${basic_utils[@]}"
                ;;
            4)
                dev_utils=(
                    "git:git:Version control"
                    "vim:vim:Advanced editor"
                    "nano:nano:Simple editor"
                )
                install_utility_group "$(translate "Development Tools")" "${dev_utils[@]}"
                ;;
            5)
                compress_utils=(
                    "zip:zip:ZIP compressor"
                    "unzip:unzip:ZIP extractor"
                    "rsync:rsync:File synchronizer"
                )
                install_utility_group "$(translate "Compression Tools")" "${compress_utils[@]}"
                ;;
            6)
                multiplex_utils=(
                    "screen:screen:Terminal multiplexer"
                    "tmux:tmux:Advanced multiplexer"
                )
                install_utility_group "$(translate "Terminal Multiplexers")" "${multiplex_utils[@]}"
                ;;
            7)
                analysis_utils=(
                    "jq:jq:JSON processor"
                    "ncdu:ncdu:Disk analyzer"
                    "iotop:iotop:I/O monitor"
                )
                install_utility_group "$(translate "Analysis Tools")" "${analysis_utils[@]}"
                ;;
            8)
                network_utils=(
                    "iperf3:iperf3:Network bandwidth testing"
                    "nethogs:nethogs:Network monitor per process"
                    "nmap:nmap:Network scanner"
                    "tcpdump:tcpdump:Packet analyzer"
                    "lsof:lsof:Open files and ports"
                )
                install_utility_group "$(translate "Network Tools")" "${network_utils[@]}"
                ;;
            9)
                verify_installations
                ;;
            0|"")
                break
                ;;
            *)
                dialog --clear --backtitle "ProxMenux" \
                    --title "$(translate "Invalid Option")" \
                    --msgbox "$(translate "Please select a valid option")" 8 40
                ;;
        esac
    done

    clear
}

install_system_utils
