#!/bin/bash
# ==========================================================
# ProxMenux - Settings (Configuration Menu)
# ==========================================================
# Author       : MacRimi
# Contributors : cod378
# Copyright    : (c) 2024 MacRimi
# License      : GPL-3.0
#                https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version      : 1.2
# ==========================================================
# Description:
# ProxMenux configuration / settings menu. Options are shown
# conditionally based on the install type and current state:
#
#   - ProxMenux Monitor (Activate / Deactivate + Show Status)
#       Only if proxmenux-monitor.service is registered with
#       systemd. Toggles between active / inactive states.
#
#   - Change Release Channel
#       Switches between Stable (main branch) and Beta (develop
#       branch) by running the official installer for each channel.
#
#   - Change Language
#       Only on the Translation install type (venv +
#       config.json.language present). Languages: en / es / fr /
#       de / it / pt.
#
#   - Show Version Information
#       Always shown. Reports installed components, files,
#       virtual environment state and current language.
#
#   - Uninstall ProxMenux
#       Always shown. Interactive uninstall with optional
#       dependency removal (jq, dialog, python3-*, ...) and
#       restoration of /root/.bashrc + /etc/motd backups.
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
CONFIG_FILE="$BASE_DIR/config.json"
CACHE_FILE="$BASE_DIR/cache.json"
UTILS_FILE="$BASE_DIR/utils.sh"
LOCAL_VERSION_FILE="$BASE_DIR/version.txt"
BETA_VERSION_FILE="$BASE_DIR/beta_version.txt"
INSTALL_DIR="/usr/local/bin"
MENU_SCRIPT="menu"
VENV_PATH="/opt/googletrans-env"
BACKTITLE="ProxMenux Configuration"

REPO_MAIN="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
REPO_DEVELOP="https://raw.githubusercontent.com/MacRimi/ProxMenux/develop"
STABLE_INSTALLER_URL="$REPO_MAIN/install_proxmenux.sh"
BETA_INSTALLER_URL="$REPO_DEVELOP/install_proxmenux_beta.sh"

MONITOR_SERVICE="proxmenux-monitor.service"
MONITOR_UNIT_FILE="/etc/systemd/system/${MONITOR_SERVICE}"
MONITOR_CONFIG_DIR="/root/.config/proxmenux-monitor"
MONITOR_RUNTIME_DIR="$BASE_DIR/monitor-app"
MONITOR_PORT=8008

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================

uninstall_proxmenux_monitor() {

    # 1. Stop service if it is running
    if systemctl is-active --quiet "${MONITOR_SERVICE}"; then
    echo " - Stoping service..."
    systemctl stop "${MONITOR_SERVICE}" > /dev/null 2>&1
    else
    echo " - Service is not running (ok)"
    fi

    # 2. Disable service if enabled
    if systemctl is-enabled --quiet "${MONITOR_SERVICE}"; then
    echo " - Disabling service..."
    systemctl disable "${MONITOR_SERVICE}" > /dev/null 2>&1
    else
    echo " - Service is not enabled (ok)"
    fi

    # 3. Remove unit file
    if [ -f "${MONITOR_UNIT_FILE}" ]; then
    echo " - Removing unit file ${MONITOR_UNIT_FILE}..."
    rm -f "${MONITOR_UNIT_FILE}"
    else
    echo " - Unit file ${MONITOR_UNIT_FILE} does not exist (ok)"
    fi

    # 4. Remove config directory (~/.config/proxmenux-monitor)
    if [ -d "${MONITOR_CONFIG_DIR}" ]; then
    echo " - Removing config dir ${MONITOR_CONFIG_DIR}..."
    rm -rf "${MONITOR_CONFIG_DIR}"
    else
    echo " - Config dir ${MONITOR_CONFIG_DIR} does not exist (ok)"
    fi

    # 5. Reload systemd
    echo " - Recargando systemd..."
    systemctl daemon-reload > /dev/null 2>&1
    systemctl reset-failed > /dev/null 2>&1 || true

    echo "==> Service ${MONITOR_SERVICE} uninstalled."

    
}

detect_installation_type() {
    local has_venv=false
    local has_language=false
    
    # Check if virtual environment exists
    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/activate" ]; then
        has_venv=true
    fi
    
    # Check if language is configured
    if [ -f "$CONFIG_FILE" ]; then
        local current_language=$(jq -r '.language // empty' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$current_language" && "$current_language" != "null" && "$current_language" != "empty" ]]; then
            has_language=true
        fi
    fi
    
    if [ "$has_venv" = true ] && [ "$has_language" = true ]; then
        echo "translation"
    else
        echo "normal"
    fi
}

check_monitor_status() {
    if systemctl list-unit-files | grep -q "$MONITOR_SERVICE"; then
        if systemctl is-active --quiet "$MONITOR_SERVICE"; then
            echo "active"
        else
            echo "inactive"
        fi
    else
        echo "not_installed"
    fi
}

is_beta_program_active() {
    [[ -f "$CONFIG_FILE" ]] || return 1
    local flag
    flag=$(jq -r '.beta_program.status // empty' "$CONFIG_FILE" 2>/dev/null)
    [[ "$flag" == "active" ]]
}

get_release_channel() {
    if is_beta_program_active; then
        echo "beta"
    else
        echo "stable"
    fi
}

release_channel_label() {
    case "$1" in
        "beta")
            echo "$(translate "Beta (develop branch)")"
            ;;
        *)
            echo "$(translate "Stable (main branch)")"
            ;;
    esac
}

download_release_installer() {
    local channel="$1"
    local output_file="$2"
    local installer_url

    case "$channel" in
        "beta")
            installer_url="$BETA_INSTALLER_URL"
            ;;
        "stable")
            installer_url="$STABLE_INSTALLER_URL"
            ;;
        *)
            return 1
            ;;
    esac

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$installer_url" -o "$output_file"
    else
        wget -qO "$output_file" "$installer_url"
    fi
}

set_stable_release_config() {
    local tmp

    mkdir -p "$BASE_DIR"
    if [ ! -f "$CONFIG_FILE" ] || ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        echo '{}' > "$CONFIG_FILE"
    fi

    tmp=$(mktemp)
    if jq 'del(.beta_program, .beta_version, .install_branch)
         | del(.update_available.beta, .update_available.beta_version)
         | if .proxmenux_monitor.status == "beta_updated" then .proxmenux_monitor.status = "updated" else . end
         | if (.update_available // {}) == {} then del(.update_available) else . end' \
        "$CONFIG_FILE" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$CONFIG_FILE"
        rm -f "$BETA_VERSION_FILE" "$BASE_DIR/install_proxmenux_beta.sh"
        return 0
    fi

    rm -f "$tmp"
    return 1
}

normalize_stable_monitor_service() {
    local exec_path="$MONITOR_RUNTIME_DIR/AppRun"
    local was_active=false

    [ -x "$exec_path" ] || return 0
    [ -f "$MONITOR_UNIT_FILE" ] || return 0

    systemctl is-active --quiet "$MONITOR_SERVICE" && was_active=true

    msg_info "$(translate "Normalizing stable monitor service...")"
    cat > "$MONITOR_UNIT_FILE" << EOF
[Unit]
Description=ProxMenux Monitor - Web Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$MONITOR_RUNTIME_DIR
ExecStart=$exec_path
Restart=on-failure
RestartSec=10
Environment="PORT=$MONITOR_PORT"

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$MONITOR_SERVICE" >/dev/null 2>&1

    if [ "$was_active" = true ]; then
        if systemctl restart "$MONITOR_SERVICE" >/dev/null 2>&1; then
            msg_ok "$(translate "Stable monitor service normalized.")"
            return 0
        fi

        msg_error "$(translate "Could not restart ProxMenux Monitor service.")"
        return 1
    fi

    msg_ok "$(translate "Stable monitor service normalized.")"
    return 0
}

apply_release_channel() {
    local target_channel="$1"
    local current_channel installer_file installer_status

    current_channel=$(get_release_channel)
    installer_file=$(mktemp /tmp/proxmenux-${target_channel}-installer.XXXXXX) || return 1

    show_proxmenux_logo
    msg_title "$(translate "Changing Release Channel")"
    msg_ok "$(translate "Current channel:") $(release_channel_label "$current_channel")"
    msg_ok "$(translate "Target channel:") $(release_channel_label "$target_channel")"

    msg_info "$(translate "Downloading official installer...")"
    if download_release_installer "$target_channel" "$installer_file" >/dev/null 2>&1; then
        chmod +x "$installer_file"
        msg_ok "$(translate "Installer downloaded.")"
    else
        msg_error "$(translate "Could not download the installer.")"
        rm -f "$installer_file"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    msg_info "$(translate "Starting installer...")"
    stop_spinner
    bash "$installer_file"
    installer_status=$?
    rm -f "$installer_file"

    if [ "$installer_status" -ne 0 ]; then
        msg_error "$(translate "Installer finished with errors.")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        return 1
    fi

    if [ "$target_channel" = "stable" ]; then
        msg_info "$(translate "Updating release channel configuration...")"
        if set_stable_release_config; then
            msg_ok "$(translate "Release channel set to Stable.")"
            if ! normalize_stable_monitor_service; then
                msg_success "$(translate "Press Enter to return to menu...")"
                read -r
                return 1
            fi
        else
            msg_error "$(translate "Could not update config file.")"
            msg_success "$(translate "Press Enter to return to menu...")"
            read -r
            return 1
        fi
    else
        msg_ok "$(translate "Release channel set to Beta.")"
    fi

    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
    exec bash "$LOCAL_SCRIPTS/menus/config_menu.sh"
}

change_release_channel() {
    local current_channel current_label selected_channel selected_label confirm_message

    current_channel=$(get_release_channel)
    current_label=$(release_channel_label "$current_channel")

    selected_channel=$(dialog --clear --backtitle "$BACKTITLE" \
                              --title "$(translate "Release Channel")" \
                              --default-item "$current_channel" \
                              --menu "$(translate "Current channel:") $current_label\n\n$(translate "Choose the release channel to use:")" 16 74 2 \
                              "stable" "$(translate "Stable (main branch)")" \
                              "beta" "$(translate "Beta (develop branch)")" 3>&1 1>&2 2>&3)

    [ -z "$selected_channel" ] && return

    if [ "$selected_channel" = "$current_channel" ]; then
        dialog --clear --backtitle "$BACKTITLE" \
               --title "$(translate "Release Channel")" \
               --msgbox "\n\n$(translate "This release channel is already active.")" 9 56
        return
    fi

    selected_label=$(release_channel_label "$selected_channel")

    case "$selected_channel" in
        "beta")
            confirm_message="$(translate "This will install the Beta version from the develop branch and enable beta update checks.\n\nBeta builds may contain bugs or incomplete features.\n\nContinue?")"
            ;;
        "stable")
            confirm_message="$(translate "This will reinstall the Stable version from the main branch and disable beta update checks.\n\nContinue?")"
            ;;
        *)
            return
            ;;
    esac

    if dialog --clear --backtitle "$BACKTITLE" \
              --title "$selected_label" \
              --yesno "\n$confirm_message" 14 72; then
        apply_release_channel "$selected_channel"
    fi
}

toggle_monitor_service() {
    local status=$(check_monitor_status)
    
    if [ "$status" = "not_installed" ]; then
        dialog --clear --backtitle "ProxMenux Configuration" \
               --title "$(translate "ProxMenux Monitor")" \
               --msgbox "\n\n$(translate "ProxMenux Monitor is not installed.")" 10 50
        return
    fi
    
    if [ "$status" = "active" ]; then
        if dialog --clear --backtitle "ProxMenux Configuration" \
                  --title "$(translate "Deactivate Monitor")" \
                  --yesno "\n$(translate "Do you want to deactivate ProxMenux Monitor?")" 8 60; then
            systemctl stop "$MONITOR_SERVICE" 2>/dev/null
            systemctl disable "$MONITOR_SERVICE" 2>/dev/null
            dialog --clear --backtitle "ProxMenux Configuration" \
                   --title "$(translate "Monitor Deactivated")" \
                   --msgbox "\n\n$(translate "ProxMenux Monitor has been deactivated.")" 10 50
        fi
    else
        if dialog --clear --backtitle "ProxMenux Configuration" \
                  --title "$(translate "Activate Monitor")" \
                  --yesno "\n$(translate "Do you want to activate ProxMenux Monitor?")" 8 60; then
            systemctl enable "$MONITOR_SERVICE" 2>/dev/null
            systemctl start "$MONITOR_SERVICE" 2>/dev/null
            dialog --clear --backtitle "ProxMenux Configuration" \
                   --title "$(translate "Monitor Activated")" \
                   --msgbox "\n\n$(translate "ProxMenux Monitor has been activated.")" 10 50
        fi
    fi
}

show_monitor_status() {
    clear
    show_proxmenux_logo
    msg_title "$(translate "ProxMenux Monitor Service Verification")"
    echo ""
    
    local status=$(check_monitor_status)
    
    if [ "$status" = "not_installed" ]; then
        msg_warn "$(translate "ProxMenux Monitor is not installed")"
        echo ""
        msg_info2 "$(translate "To install the monitor, reinstall ProxMenux with the latest version")"
    else
        msg_info2 "$(translate "Service Status"): $MONITOR_SERVICE"
        echo ""
        
        if [ "$status" = "active" ]; then
            msg_ok "$(translate "Service is active and running")"
            
            local server_ip=$(hostname -I | awk '{print $1}')
            if [ -n "$server_ip" ]; then
                echo -e "${TAB}${GN}🌐 $(translate "Monitor URL")${CL}: ${BL}http://${server_ip}:8008${CL}"
            fi
        else
            msg_warn "$(translate "Service is inactive")"
        fi
        
        echo ""
        msg_info2 "$(translate "Detailed service information"):"
        echo ""
        systemctl status "$MONITOR_SERVICE" --no-pager -l
    fi
    
    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

# ==========================================================
show_config_menu() {
    local install_type
    install_type=$(detect_installation_type)
    
    while true; do
        local menu_options=()
        local option_actions=()
        
        local monitor_status=$(check_monitor_status)
        local option_num=1
        
        if [ "$monitor_status" != "not_installed" ]; then
            if [ "$monitor_status" = "active" ]; then
                menu_options+=("$option_num" "$(translate "Deactivate ProxMenux Monitor")")
                option_actions[$option_num]="toggle_monitor"
            else
                menu_options+=("$option_num" "$(translate "Activate ProxMenux Monitor")")
                option_actions[$option_num]="toggle_monitor"
            fi
            ((option_num++))
            
            menu_options+=("$option_num" "$(translate "Show Monitor Service Status")")
            option_actions[$option_num]="show_monitor_status"
            ((option_num++))
        fi

        menu_options+=("$option_num" "$(translate "Change Release Channel")")
        option_actions[$option_num]="change_release_channel"
        ((option_num++))

        # Build menu based on installation type
        if [ "$install_type" = "translation" ]; then
            menu_options+=("$option_num" "$(translate "Change Language")")
            option_actions[$option_num]="change_language"
            ((option_num++))
            
            menu_options+=("$option_num" "$(translate "Show Version Information")")
            option_actions[$option_num]="show_version_info"
            ((option_num++))
            
            menu_options+=("$option_num" "$(translate "Uninstall ProxMenux")")
            option_actions[$option_num]="uninstall_proxmenu"
            ((option_num++))
            
            menu_options+=("$option_num" "$(translate "Return to Main Menu")")
            option_actions[$option_num]="return_main"
        else
            # Normal version (English only)
            menu_options+=("$option_num" "Show Version Information")
            option_actions[$option_num]="show_version_info"
            ((option_num++))
            
            menu_options+=("$option_num" "Uninstall ProxMenux")
            option_actions[$option_num]="uninstall_proxmenu"
            ((option_num++))
            
            menu_options+=("$option_num" "Return to Main Menu")
            option_actions[$option_num]="return_main"
        fi
        
        # Show menu
        OPTION=$(dialog --clear --backtitle "ProxMenux Configuration" \
                        --title "$(translate "Configuration Menu")" \
                        --menu "$(translate "Select an option:")" 20 70 10 \
                        "${menu_options[@]}" 3>&1 1>&2 2>&3)
        
        # Execute selected action
        case "${option_actions[$OPTION]}" in
            "toggle_monitor")
                toggle_monitor_service
                ;;
            "show_monitor_status")
                show_monitor_status
                ;;
            "change_release_channel")
                change_release_channel
                ;;
            "change_language")
                change_language
                ;;
            "show_version_info")
                show_version_info
                ;;
            "uninstall_proxmenu")
                uninstall_proxmenu
                ;;
            "return_main"|"")
                exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
                ;;
        esac
    done
}

# ==========================================================
change_language() {
    local new_language
    new_language=$(dialog --clear --backtitle "ProxMenux Configuration" \
                          --title "$(translate "Change Language")" \
                          --menu "$(translate "Select a new language for the menu:")" 20 60 6 \
                          "en" "$(translate "English")" \
                          "es" "$(translate "Spanish")" \
                          "fr" "$(translate "French")" \
                          "de" "$(translate "German")" \
                          "it" "$(translate "Italian")" \
                          "pt" "$(translate "Portuguese")" 3>&1 1>&2 2>&3)
    
    if [ -z "$new_language" ]; then
        dialog --clear --backtitle "ProxMenux Configuration" \
               --title "$(translate "Language Change")" \
               --msgbox "\n\n$(translate "No language selected.")" 10 50
        return
    fi
    
    # Update language in config file
    if [ -f "$CONFIG_FILE" ]; then
        tmp=$(mktemp)
        jq --arg lang "$new_language" '.language = $lang' "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
    else
        echo "{\"language\": \"$new_language\"}" > "$CONFIG_FILE"
    fi
    
    dialog --clear --backtitle "ProxMenux Configuration" \
           --title "$(translate "Language Change")" \
           --msgbox "\n\n$(translate "Language changed to") $new_language" 10 50
    
    # Reload menu with new language
    exec bash "$LOCAL_SCRIPTS/menus/config_menu.sh"
}

# ==========================================================
show_version_info() {
    local version info_message install_type release_channel beta_version
    install_type=$(detect_installation_type)
    release_channel=$(get_release_channel)
    
    if [ -f "$LOCAL_VERSION_FILE" ]; then
        version=$(<"$LOCAL_VERSION_FILE")
    else
        version="Unknown"
    fi
    
    info_message+="$(translate "Current ProxMenux version:") $version\n"
    info_message+="$(translate "Release channel:") $(release_channel_label "$release_channel")\n"
    if [ "$release_channel" = "beta" ] && [ -f "$BETA_VERSION_FILE" ]; then
        beta_version=$(head -n 1 "$BETA_VERSION_FILE" 2>/dev/null)
        [ -n "$beta_version" ] && info_message+="$(translate "Beta version:") $beta_version\n"
    fi
    info_message+="\n"
    
    # Show installation type
    info_message+="$(translate "Installation type:")\n"
    if [ "$install_type" = "translation" ]; then
        info_message+="✓ $(translate "Translation Version (Multi-language support)")\n"
    else
        info_message+="✓ $(translate "Normal Version (English only - Lightweight)")\n"
    fi
    info_message+="\n"
    
    info_message+="$(translate "Installed components:")\n"
    if [ -f "$CONFIG_FILE" ]; then
        while IFS=': ' read -r component value; do
            case "$component" in
                "language"|"beta_program"|"beta_version"|"install_branch"|"update_available")
                    continue
                    ;;
            esac
            local status
            if echo "$value" | jq -e '.status' >/dev/null 2>&1; then
                status=$(echo "$value" | jq -r '.status')
            else
                status="$value"
            fi
            local translated_status=$(translate "$status")
            case "$status" in
                "installed"|"already_installed"|"created"|"already_exists"|"upgraded"|"updated")
                    info_message+="✓ $component: $translated_status\n"
                    ;;
                *)
                    info_message+="✗ $component: $translated_status\n"
                    ;;
            esac
        done < <(jq -r 'to_entries[] | "\(.key): \(.value)"' "$CONFIG_FILE")
    else
        info_message+="$(translate "No installation information available.")\n"
    fi
    
    info_message+="\n$(translate "ProxMenux files:")\n"
    [ -f "$INSTALL_DIR/$MENU_SCRIPT" ] && info_message+="✓ $MENU_SCRIPT → $INSTALL_DIR/$MENU_SCRIPT\n" || info_message+="✗ $MENU_SCRIPT\n"
    [ -f "$UTILS_FILE" ] && info_message+="✓ utils.sh → $UTILS_FILE\n" || info_message+="✗ utils.sh\n"
    [ -f "$CONFIG_FILE" ] && info_message+="✓ config.json → $CONFIG_FILE\n" || info_message+="✗ config.json\n"
    [ -f "$LOCAL_VERSION_FILE" ] && info_message+="✓ version.txt → $LOCAL_VERSION_FILE\n" || info_message+="✗ version.txt\n"
    
    # Show translation-specific files
    if [ "$install_type" = "translation" ]; then
        [ -f "$CACHE_FILE" ] && info_message+="✓ cache.json → $CACHE_FILE\n" || info_message+="✗ cache.json\n"
        
        info_message+="\n$(translate "Virtual Environment:")\n"
        if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/activate" ]; then
            info_message+="✓ $(translate "Installed") → $VENV_PATH\n"
            [ -f "$VENV_PATH/bin/pip" ] && info_message+="✓ pip: $(translate "Installed") → $VENV_PATH/bin/pip\n" || info_message+="✗ pip: $(translate "Not installed")\n"
        else
            info_message+="✗ $(translate "Virtual Environment"): $(translate "Not installed")\n"
            info_message+="✗ pip: $(translate "Not installed")\n"
        fi
        
        current_language=$(jq -r '.language // "en"' "$CONFIG_FILE")
        info_message+="\n$(translate "Current language:")\n$current_language\n"
    else
        info_message+="\n$(translate "Language:")\nEnglish (Fixed)\n"
    fi
    
    # Display information in a scrollable text box
    tmpfile=$(mktemp)
    echo -e "$info_message" > "$tmpfile"
    dialog --clear --backtitle "ProxMenux Configuration" \
           --title "$(translate "ProxMenux Information")" \
           --textbox "$tmpfile" 25 80
    rm -f "$tmpfile"
}

# ==========================================================
uninstall_proxmenu() {
    local install_type
    install_type=$(detect_installation_type)
    
    if ! dialog --clear --backtitle "ProxMenux Configuration" \
                --title "Uninstall ProxMenux" \
                --yesno "\n$(translate "Are you sure you want to uninstall ProxMenux?")" 8 60; then
        return
    fi
    
    local deps_to_remove=""
    
    # Show different dependency options based on installation type
    if [ "$install_type" = "translation" ]; then
        deps_to_remove=$(dialog --clear --backtitle "ProxMenux Configuration" \
                               --title "Remove Dependencies" \
                               --checklist "Select dependencies to remove:" 15 60 4 \
                               "python3-venv" "Python virtual environment" OFF \
                               "python3-pip" "Python package installer" OFF \
                               "python3" "Python interpreter" OFF \
                               "jq" "JSON processor" OFF \
                               3>&1 1>&2 2>&3)
    else
        deps_to_remove=$(dialog --clear --backtitle "ProxMenux Configuration" \
                               --title "Remove Dependencies" \
                               --checklist "Select dependencies to remove:" 12 60 2 \
                               "dialog" "Interactive dialog boxes" OFF \
                               "jq" "JSON processor" OFF \
                               3>&1 1>&2 2>&3)
    fi
    
    # Perform uninstallation with progress bar
    (
        echo "10" ; echo "Removing ProxMenu files..."
        sleep 1
        
        # Remove googletrans and virtual environment if exists
        if [ -f "$VENV_PATH/bin/activate" ]; then
            echo "30" ; echo "Removing googletrans and virtual environment..."
            source "$VENV_PATH/bin/activate"
            pip uninstall -y googletrans >/dev/null 2>&1
            deactivate
            rm -rf "$VENV_PATH"
        fi
        
        echo "50" ; echo "Removing ProxMenu files..."
        rm -f "$INSTALL_DIR/$MENU_SCRIPT"
        rm -rf "$BASE_DIR"
        
        # Remove selected dependencies
        if [ -n "$deps_to_remove" ]; then
            echo "70" ; echo "Removing selected dependencies..."
            read -r -a DEPS_ARRAY <<< "$(echo "$deps_to_remove" | tr -d '"')"
            for dep in "${DEPS_ARRAY[@]}"; do
                apt-mark auto "$dep" >/dev/null 2>&1
                apt-get -y --purge autoremove "$dep" >/dev/null 2>&1
            done
            apt-get autoremove -y --purge >/dev/null 2>&1
        fi

        echo "80" ; echo "Removing ProxMenux Monitor..."
        uninstall_proxmenux_monitor
        
        echo "90" ; echo "Restoring system files..."
        # Restore .bashrc and motd
        [ -f /root/.bashrc.bak ] && mv /root/.bashrc.bak /root/.bashrc
        if [ -f /etc/motd.bak ]; then
            mv /etc/motd.bak /etc/motd
        else
            sed -i '/This system is optimised by: ProxMenux/d' /etc/motd
        fi
        
        echo "100" ; echo "Uninstallation complete!"
        sleep 1
        
    ) | dialog --clear --backtitle "ProxMenux Configuration" \
               --title "Uninstalling ProxMenux" \
               --gauge "Starting uninstallation..." 10 60 0
    
    # Show completion message
    local final_message="ProxMenux has been uninstalled successfully.\n\n"
    if [ -n "$deps_to_remove" ]; then
        final_message+="The following dependencies were removed:\n$deps_to_remove\n\n"
    fi
    final_message+="Thank you for using ProxMenux!"
    
    dialog --clear --backtitle "ProxMenux Configuration" \
           --title "Uninstallation Complete" \
           --msgbox "$final_message" 12 60
    clear    
    exit 0
}

# ==========================================================
# Main execution
show_config_menu
