#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.3
# Last Updated: 04/07/2025
# ==========================================================
# Description:
# This script installs and configures ProxMenux, a menu-driven
# tool for managing Proxmox VE.
#
# - Ensures the script is run with root privileges.
# - Displays an installation confirmation prompt.
# - Installs required dependencies:
# - whiptail (for interactive terminal menus)
# - curl (for downloading remote files)
# - jq (for handling JSON data)
# - Python 3 and virtual environment (for translations)
# - Configures the Python virtual environment and installs googletrans.
# - Creates necessary directories for storing ProxMenux data.
# - Downloads required files from GitHub, including:
# - Cache file (`cache.json`) for translation caching.
# - Utility script (`utils.sh`) for core functions.
# - Main script (`menu.sh`) to launch ProxMenux.
# - Sets correct permissions for execution.
# - Displays final instructions on how to start ProxMenux.
#
# This installer ensures a smooth setup process and prepares
# the system for running ProxMenux efficiently.
# ==========================================================

# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
UTILS_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/scripts/utils.sh"
INSTALL_DIR="/usr/local/bin"
BASE_DIR="/usr/local/share/proxmenux"
CONFIG_FILE="$BASE_DIR/config.json"
CACHE_FILE="$BASE_DIR/cache.json"
UTILS_FILE="$BASE_DIR/utils.sh"
LOCAL_VERSION_FILE="$BASE_DIR/version.txt"
MENU_SCRIPT="menu"
VENV_PATH="/opt/googletrans-env"

MONITOR_APPIMAGE_URL="https://github.com/MacRimi/ProxMenux/raw/refs/heads/main/AppImage/ProxMenux-1.0.0.AppImage"
MONITOR_SHA256_URL="https://github.com/MacRimi/ProxMenux/raw/refs/heads/main/AppImage/ProxMenux-Monitor.AppImage.sha256"
MONITOR_INSTALL_PATH="$BASE_DIR/ProxMenux-Monitor.AppImage"
MONITOR_SERVICE_FILE="/etc/systemd/system/proxmenux-monitor.service"
MONITOR_PORT=8008

if ! source <(curl -sSf "$UTILS_URL"); then
    echo "Error: Could not load utils.sh from $UTILS_URL"
    exit 1
fi

cleanup_corrupted_files() {
    if [ -f "$CONFIG_FILE" ] && ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "Cleaning up corrupted configuration file..."
        rm -f "$CONFIG_FILE"
    fi
    if [ -f "$CACHE_FILE" ] && ! jq empty "$CACHE_FILE" >/dev/null 2>&1; then
        echo "Cleaning up corrupted cache file..."
        rm -f "$CACHE_FILE"
    fi
}

# ==========================================================
check_existing_installation() {
    local has_venv=false
    local has_config=false
    local has_language=false
    local has_menu=false
    
    if [ -f "$INSTALL_DIR/$MENU_SCRIPT" ]; then
        has_menu=true
    fi
    
    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/activate" ]; then
        has_venv=true
    fi
    
    if [ -f "$CONFIG_FILE" ]; then
        if jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
            has_config=true
            local current_language=$(jq -r '.language // empty' "$CONFIG_FILE" 2>/dev/null)
            if [[ -n "$current_language" && "$current_language" != "null" && "$current_language" != "empty" ]]; then
                has_language=true
            fi
        else
            echo "Warning: Corrupted config file detected, removing..."
            rm -f "$CONFIG_FILE"
        fi
    fi
    
    if [ "$has_venv" = true ] && [ "$has_language" = true ]; then
        echo "translation"
    elif [ "$has_menu" = true ] && [ "$has_venv" = false ]; then
        echo "normal"
    elif [ "$has_menu" = true ]; then
        echo "unknown"
    else
        echo "none"
    fi
}

uninstall_proxmenux() {
    local install_type="$1"
    local force_clean="$2"
    
    if [ "$force_clean" != "force" ]; then
        if ! whiptail --title "Uninstall ProxMenux" --yesno "Are you sure you want to uninstall ProxMenux?" 10 60; then
            return 1
        fi
    fi
    
    echo "Uninstalling ProxMenux..."
    
    if [ -f "$VENV_PATH/bin/activate" ]; then
        echo "Removing googletrans and virtual environment..."
        source "$VENV_PATH/bin/activate"
        pip uninstall -y googletrans >/dev/null 2>&1
        deactivate
        rm -rf "$VENV_PATH"
    fi
    
    if [ "$install_type" = "translation" ] && [ "$force_clean" != "force" ]; then
        DEPS_TO_REMOVE=$(whiptail --title "Remove Translation Dependencies" --checklist \
            "Select translation-specific dependencies to remove:" 15 60 3 \
            "python3-venv" "Python virtual environment" OFF \
            "python3-pip" "Python package installer" OFF \
            "python3" "Python interpreter" OFF \
            3>&1 1>&2 2>&3)
        
        if [ -n "$DEPS_TO_REMOVE" ]; then
            echo "Removing selected dependencies..."
            read -r -a DEPS_ARRAY <<< "$(echo "$DEPS_TO_REMOVE" | tr -d '"')"
            for dep in "${DEPS_ARRAY[@]}"; do
                echo "Removing $dep..."
                apt-mark auto "$dep" >/dev/null 2>&1
                apt-get -y --purge autoremove "$dep" >/dev/null 2>&1
            done
            apt-get autoremove -y --purge >/dev/null 2>&1
        fi
    fi
    
    rm -f "$INSTALL_DIR/$MENU_SCRIPT"
    rm -rf "$BASE_DIR"
    
    [ -f /root/.bashrc.bak ] && mv /root/.bashrc.bak /root/.bashrc
    if [ -f /etc/motd.bak ]; then
        mv /etc/motd.bak /etc/motd
    else
        sed -i '/This system is optimised by: ProxMenux/d' /etc/motd
    fi
    
    echo "ProxMenux has been uninstalled."
    return 0
}

handle_installation_change() {
    local current_type="$1"
    local new_type="$2"
    
    if [ "$current_type" = "$new_type" ]; then
        return 0
    fi
    
    case "$current_type-$new_type" in
        "translation-1"|"translation-normal")
            if whiptail --title "Installation Type Change" \
                --yesno "Switch from Translation to Normal Version?\n\nThis will remove translation components." 10 60; then
                echo "Preparing for installation type change..."
                uninstall_proxmenux "translation" "force" >/dev/null 2>&1
                return 0
            else
                return 1
            fi
            ;;
        "normal-2"|"normal-translation")
            if whiptail --title "Installation Type Change" \
                --yesno "Switch from Normal to Translation Version?\n\nThis will add translation components." 10 60; then
                return 0
            else
                return 1
            fi
            ;;
        *)
            return 0
            ;;
    esac
}

update_config() {
    local component="$1"
    local status="$2"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    local tracked_components=("dialog" "curl" "jq" "python3" "python3-venv" "python3-pip" "virtual_environment" "pip" "googletrans" "proxmenux_monitor")
    
    if [[ " ${tracked_components[@]} " =~ " ${component} " ]]; then
        mkdir -p "$(dirname "$CONFIG_FILE")"
        
        if [ ! -f "$CONFIG_FILE" ] || ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
            echo '{}' > "$CONFIG_FILE"
        fi
        
        local tmp_file=$(mktemp)
        if jq --arg comp "$component" --arg stat "$status" --arg time "$timestamp" \
           '.[$comp] = {status: $stat, timestamp: $time}' "$CONFIG_FILE" > "$tmp_file" 2>/dev/null; then
            mv "$tmp_file" "$CONFIG_FILE"
        else
            echo '{}' > "$CONFIG_FILE"
            jq --arg comp "$component" --arg stat "$status" --arg time "$timestamp" \
               '.[$comp] = {status: $stat, timestamp: $time}' "$CONFIG_FILE" > "$tmp_file" && mv "$tmp_file" "$CONFIG_FILE"
        fi
        
        [ -f "$tmp_file" ] && rm -f "$tmp_file"
    fi
}

show_progress() {
    local step="$1"
    local total="$2"
    local message="$3"
    
    echo -e "\n${BOLD}${BL}${TAB}Installing ProxMenux: Step $step of $total${CL}"
    echo
    msg_info2 "$message"
}

select_language() {
    if [ -f "$CONFIG_FILE" ] && jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        local existing_language=$(jq -r '.language // empty' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$existing_language" && "$existing_language" != "null" && "$existing_language" != "empty" ]]; then
            LANGUAGE="$existing_language"
            msg_ok "Using existing language configuration: $LANGUAGE"
            return 0
        fi
    fi
    
    LANGUAGE=$(whiptail --title "Select Language" --menu "Choose a language for the menu:" 20 60 12 \
        "en" "English (Recommended)" \
        "es" "Spanish" \
        "fr" "French" \
        "de" "German" \
        "it" "Italian" \
        "pt" "Portuguese" 3>&1 1>&2 2>&3)
    
    if [ -z "$LANGUAGE" ]; then
        msg_error "No language selected. Exiting."
        exit 1
    fi
    
    mkdir -p "$(dirname "$CONFIG_FILE")"
    
    if [ ! -f "$CONFIG_FILE" ] || ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        echo '{}' > "$CONFIG_FILE"
    fi
    
    local tmp_file=$(mktemp)
    if jq --arg lang "$LANGUAGE" '. + {language: $lang}' "$CONFIG_FILE" > "$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$CONFIG_FILE"
    else
        echo "{\"language\": \"$LANGUAGE\"}" > "$CONFIG_FILE"
    fi
    
    [ -f "$tmp_file" ] && rm -f "$tmp_file"
    
    msg_ok "Language set to: $LANGUAGE"
}

# Show installation confirmation for new installations
show_installation_confirmation() {
    local install_type="$1"
    
    case "$install_type" in
        "1")
            if whiptail --title "ProxMenux - Normal Version Installation" \
                --yesno "ProxMenux Normal Version will install:\n\n• dialog  (interactive menus) - Official Debian package\n• curl       (file downloads) - Official Debian package\n• jq        (JSON processing) - Official Debian package\n• ProxMenux core files     (/usr/local/share/proxmenux)\n• ProxMenux Monitor        (Web dashboard on port 8008)\n\nThis is a lightweight installation with minimal dependencies.\n\nProceed with installation?" 20 70; then
                return 0
            else
                return 1
            fi
            ;;
        "2")
            if whiptail --title "ProxMenux - Translation Version Installation" \
                --yesno "ProxMenux Translation Version will install:\n\n• dialog (interactive menus)\n• curl (file downloads)\n• jq (JSON processing)\n• python3 + python3-venv + python3-pip\n• Google Translate library (googletrans)\n• Virtual environment (/opt/googletrans-env)\n• Translation cache system\n• ProxMenux core files\n• ProxMenux Monitor        (Web dashboard on port 8008)\n\nThis version requires more dependencies for translation support.\n\nProceed with installation?" 20 70; then
                return 0
            else
                return 1
            fi
            ;;
    esac
}

get_server_ip() {
    local ip
    # Try to get the primary IP address
    ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+')
    
    if [ -z "$ip" ]; then
        # Fallback: get first non-loopback IP
        ip=$(hostname -I | awk '{print $1}')
    fi
    
    if [ -z "$ip" ]; then
        # Last resort: use localhost
        ip="localhost"
    fi
    
    echo "$ip"
}

install_proxmenux_monitor() {
    systemctl stop proxmenux-monitor 2>/dev/null || true
    
    # Check if URL is accessible
    if ! wget --spider -q "$MONITOR_APPIMAGE_URL" 2>/dev/null; then
        msg_warn "ProxMenux Monitor AppImage not available at: $MONITOR_APPIMAGE_URL"
        msg_info "The monitor will be available in future releases."
        return 1
    fi
    
    # Download AppImage silently
    if ! wget -q -O "$MONITOR_INSTALL_PATH" "$MONITOR_APPIMAGE_URL" 2>&1; then
        msg_warn "Failed to download ProxMenux Monitor from GitHub."
        msg_info "You can install it manually later when available."
        return 1
    fi
    
    # Download SHA256 checksum silently
    local sha256_file="/tmp/proxmenux-monitor.sha256"
    if ! wget -q -O "$sha256_file" "$MONITOR_SHA256_URL" 2>/dev/null; then
        msg_warn "SHA256 checksum file not available. Skipping verification."
        msg_info "AppImage downloaded but integrity cannot be verified."
        rm -f "$sha256_file"
    else
        # Verify SHA256 silently
        local expected_hash=$(cat "$sha256_file" | awk '{print $1}')
        local actual_hash=$(sha256sum "$MONITOR_INSTALL_PATH" | awk '{print $1}')
        
        if [ "$expected_hash" != "$actual_hash" ]; then
            msg_error "SHA256 verification failed! AppImage may be corrupted."
            msg_info "Expected: $expected_hash"
            msg_info "Got:      $actual_hash"
            rm -f "$MONITOR_INSTALL_PATH" "$sha256_file"
            return 1
        fi
        rm -f "$sha256_file"
    fi
    
    # Make executable
    chmod +x "$MONITOR_INSTALL_PATH"
    
    # Show single success message at the end
    msg_ok "ProxMenux Monitor installed and activated successfully."
    
    return 0
}

create_monitor_service() {
    msg_info "Creating ProxMenux Monitor service..."
    
    cat > "$MONITOR_SERVICE_FILE" << EOF
[Unit]
Description=ProxMenux Monitor - Web Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BASE_DIR
ExecStart=$MONITOR_INSTALL_PATH
Restart=on-failure
RestartSec=10
Environment="PORT=$MONITOR_PORT"

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd, enable and start service
    systemctl daemon-reload
    systemctl enable proxmenux-monitor.service > /dev/null 2>&1
    systemctl start proxmenux-monitor.service > /dev/null 2>&1
    
    # Wait a moment for service to start
    sleep 2
    
    # Check if service is running
    if systemctl is-active --quiet proxmenux-monitor.service; then
        msg_ok "ProxMenux Monitor service started successfully."
        update_config "proxmenux_monitor" "installed"
        return 0
    else
        msg_warn "ProxMenux Monitor service failed to start. Check logs with: journalctl -u proxmenux-monitor"
        return 1
    fi
}

####################################################
install_normal_version() {
    local total_steps=4
    local current_step=1
    
    show_progress $current_step $total_steps "Installing basic dependencies"
    
    if ! command -v jq > /dev/null 2>&1; then
        # Try installing from APT (silently)
        apt-get update > /dev/null 2>&1
        
        if apt-get install -y jq > /dev/null 2>&1 && command -v jq > /dev/null 2>&1; then
            update_config "jq" "installed"
        else
            # Fallback: Download jq binary from GitHub
            local jq_url="https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64"
            if wget -q -O /usr/local/bin/jq "$jq_url" 2>/dev/null && chmod +x /usr/local/bin/jq; then
                if command -v jq > /dev/null 2>&1; then
                    update_config "jq" "installed_from_github"
                else
                    msg_error "Failed to install jq. Please install it manually."
                    update_config "jq" "failed"
                    return 1
                fi
            else
                msg_error "Failed to install jq from both APT and GitHub. Please install it manually."
                update_config "jq" "failed"
                return 1
            fi
        fi
    else
        update_config "jq" "already_installed"
    fi
    
    BASIC_DEPS=("dialog" "curl")
    for pkg in "${BASIC_DEPS[@]}"; do
        if ! dpkg -l | grep -qw "$pkg"; then
            if apt-get install -y "$pkg" > /dev/null 2>&1; then
                update_config "$pkg" "installed"
            else
                msg_error "Failed to install $pkg. Please install it manually."
                update_config "$pkg" "failed"
                return 1
            fi
        else
            update_config "$pkg" "already_installed"
        fi
    done
    
    msg_ok "jq, dialog and curl installed successfully."
    
    ((current_step++))
    
    show_progress $current_step $total_steps "Creating directories and configuration"
    
    mkdir -p "$BASE_DIR"
    mkdir -p "$INSTALL_DIR"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo '{}' > "$CONFIG_FILE"
    fi
    
    msg_ok "Directories and configuration created."
    ((current_step++))
    
    show_progress $current_step $total_steps "Downloading necessary files"
    
    FILES=(
        "$UTILS_FILE $REPO_URL/scripts/utils.sh"
        "$INSTALL_DIR/$MENU_SCRIPT $REPO_URL/$MENU_SCRIPT"
        "$LOCAL_VERSION_FILE $REPO_URL/version.txt"
    )
    
    for file in "${FILES[@]}"; do
        IFS=" " read -r dest url <<< "$file"
        sleep 2
        if wget -qO "$dest" "$url"; then
            msg_ok "${dest##*/} downloaded successfully."
        else
            msg_error "Failed to download ${dest##*/}. Check your Internet connection."
            return 1
        fi
    done
    
    chmod +x "$INSTALL_DIR/$MENU_SCRIPT"
    
    ((current_step++))
    show_progress $current_step $total_steps "Installing ProxMenux Monitor"
    
    if install_proxmenux_monitor; then
        create_monitor_service
    fi
}

####################################################
install_translation_version() {
    local total_steps=5
    local current_step=1
    
    show_progress $current_step $total_steps "Language selection"
    select_language
    ((current_step++))
    
    show_progress $current_step $total_steps "Installing system dependencies"
    
    if ! command -v jq > /dev/null 2>&1; then
        # Try installing from APT (silently)
        apt-get update > /dev/null 2>&1
        
        if apt-get install -y jq > /dev/null 2>&1 && command -v jq > /dev/null 2>&1; then
            update_config "jq" "installed"
        else
            # Fallback: Download jq binary from GitHub
            local jq_url="https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64"
            if wget -q -O /usr/local/bin/jq "$jq_url" 2>/dev/null && chmod +x /usr/local/bin/jq; then
                if command -v jq > /dev/null 2>&1; then
                    update_config "jq" "installed_from_github"
                else
                    msg_error "Failed to install jq. Please install it manually."
                    update_config "jq" "failed"
                    return 1
                fi
            else
                msg_error "Failed to install jq from both APT and GitHub. Please install it manually."
                update_config "jq" "failed"
                return 1
            fi
        fi
    else
        update_config "jq" "already_installed"
    fi
    
    DEPS=("dialog" "curl" "python3" "python3-venv" "python3-pip")
    for pkg in "${DEPS[@]}"; do
        if ! dpkg -l | grep -qw "$pkg"; then
            if apt-get install -y "$pkg" > /dev/null 2>&1; then
                update_config "$pkg" "installed"
            else
                msg_error "Failed to install $pkg. Please install it manually."
                update_config "$pkg" "failed"
                return 1
            fi
        else
            update_config "$pkg" "already_installed"
        fi
    done
    
    msg_ok "jq, dialog, curl, python3, python3-venv and python3-pip installed successfully."
    
    ((current_step++))
    
    show_progress $current_step $total_steps "Setting up translation environment"
    
    if [ ! -d "$VENV_PATH" ] || [ ! -f "$VENV_PATH/bin/activate" ]; then
        python3 -m venv --system-site-packages "$VENV_PATH" > /dev/null 2>&1
        if [ ! -f "$VENV_PATH/bin/activate" ]; then
            msg_error "Failed to create virtual environment. Please check your Python installation."
            update_config "virtual_environment" "failed"
            return 1
        else
            update_config "virtual_environment" "created"
        fi
    else
        update_config "virtual_environment" "already_exists"
    fi
    
    source "$VENV_PATH/bin/activate"
    
    if pip install --upgrade pip > /dev/null 2>&1; then
        update_config "pip" "upgraded"
    else
        msg_error "Failed to upgrade pip."
        update_config "pip" "upgrade_failed"
        return 1
    fi
    
    if pip install --break-system-packages --no-cache-dir googletrans==4.0.0-rc1 > /dev/null 2>&1; then
        update_config "googletrans" "installed"
    else
        msg_error "Failed to install googletrans. Please check your internet connection."
        update_config "googletrans" "failed"
        deactivate
        return 1
    fi
    
    deactivate
    ((current_step++))
    
    show_progress $current_step $total_steps "Downloading necessary files"
    
    mkdir -p "$BASE_DIR"
    mkdir -p "$INSTALL_DIR"
    
    FILES=(
        "$CACHE_FILE $REPO_URL/json/cache.json"
        "$UTILS_FILE $REPO_URL/scripts/utils.sh"
        "$INSTALL_DIR/$MENU_SCRIPT $REPO_URL/$MENU_SCRIPT"
        "$LOCAL_VERSION_FILE $REPO_URL/version.txt"
    )
    
    for file in "${FILES[@]}"; do
        IFS=" " read -r dest url <<< "$file"
        sleep 2
        if wget -qO "$dest" "$url"; then
            if [[ "$dest" == "$CACHE_FILE" ]]; then
                msg_ok "Cache file updated with latest translations."
            fi
        else
            msg_error "Failed to download ${dest##*/}. Check your Internet connection."
            return 1
        fi
    done
    
    chmod +x "$INSTALL_DIR/$MENU_SCRIPT"
    
    ((current_step++))
    show_progress $current_step $total_steps "Installing ProxMenux Monitor"
    
    if install_proxmenux_monitor; then
        create_monitor_service
    fi
}

####################################################
show_installation_options() {
    local current_install_type
    current_install_type=$(check_existing_installation)
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)
    
    local menu_title="ProxMenux Installation"
    local menu_text="Choose installation type:"
    
    if [ "$current_install_type" != "none" ]; then
        case "$current_install_type" in
            "translation")
                menu_title="ProxMenux Update - Translation Version Detected"
                ;;
            "normal")
                menu_title="ProxMenux Update - Normal Version Detected"
                ;;
            "unknown")
                menu_title="ProxMenux Update - Existing Installation Detected"
                ;;
        esac
    fi
    
    if [[ "$pve_version" -ge 9 ]]; then
        INSTALL_TYPE=$(whiptail --backtitle "ProxMenux" --title "$menu_title" --menu "\n$menu_text" 14 70 2 \
            "1" "Normal Version      (English only)" 3>&1 1>&2 2>&3)
        
        if [ -z "$INSTALL_TYPE" ]; then
            show_proxmenux_logo
            msg_warn "Installation cancelled."
            exit 1
        fi
    else
        INSTALL_TYPE=$(whiptail --backtitle "ProxMenux" --title "$menu_title" --menu "\n$menu_text" 14 70 2 \
            "1" "Normal Version      (English only)" \
            "2" "Translation Version (Multi-language support)" 3>&1 1>&2 2>&3)
        
        if [ -z "$INSTALL_TYPE" ]; then
            show_proxmenux_logo
            msg_warn "Installation cancelled."
            exit 1
        fi
    fi
    
    if [ -z "$INSTALL_TYPE" ]; then
        show_proxmenux_logo
        msg_warn "Installation cancelled."
        exit 1
    fi
    
    # For new installations, show confirmation with details
    if [ "$current_install_type" = "none" ]; then
        if ! show_installation_confirmation "$INSTALL_TYPE"; then
            show_proxmenux_logo
            msg_warn "Installation cancelled."
            exit 1
        fi
    fi
    
    if ! handle_installation_change "$current_install_type" "$INSTALL_TYPE"; then
        show_proxmenux_logo
        msg_warn "Installation cancelled."
        exit 1
    fi
}

install_proxmenux() {
    show_installation_options
    
    case "$INSTALL_TYPE" in
        "1")
            show_proxmenux_logo
            msg_title "Installing ProxMenux - Normal Version"
            install_normal_version
            ;;
        "2")
            show_proxmenux_logo
            msg_title "Installing ProxMenux - Translation Version"
            install_translation_version
            ;;
        *)
            msg_error "Invalid option selected."
            exit 1
            ;;
    esac
    
    msg_title "$(translate "ProxMenux has been installed successfully")"
    
    if systemctl is-active --quiet proxmenux-monitor.service; then
        local server_ip=$(get_server_ip)
        echo -e "${GN}🌐 $(translate "ProxMenux Monitor activated")${CL}: ${BL}http://${server_ip}:${MONITOR_PORT}${CL}"
        echo
    fi
    
    echo -ne "${GN}"
    type_text "$(translate "To run ProxMenux, simply execute this command in the console or terminal:")"
    echo -e "${YWB}    menu${CL}"
    echo
}

if [ "$(id -u)" -ne 0 ]; then
    msg_error "This script must be run as root."
    exit 1
fi

cleanup_corrupted_files
install_proxmenux
