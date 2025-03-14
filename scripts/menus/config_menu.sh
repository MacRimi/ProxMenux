#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================


# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache
# ==========================================================


show_config_menu() {
    
    while true; do
        OPTION=$(whiptail --title "$(translate "Configuration Menu")" --menu "$(translate "Select an option:")" 20 70 8 \
            "1" "$(translate "Change Language")" \
            "2" "$(translate "Show Version Information")" \
            "3" "$(translate "Uninstall ProxMenux")" \
            "4" "$(translate "Return to Main Menu")" 3>&1 1>&2 2>&3)

        case $OPTION in
            1)
                change_language
                ;;
            2)
                show_version_info
                ;;
            3)
                uninstall_proxmenu
                ;;
            4) exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh") ;;
            *) exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh") ;;
        esac
    done
}



# ==========================================================

change_language() {
    LANGUAGE=$(whiptail --title "$(translate "Change Language")" --menu "$(translate "Select a new language for the menu:")" 20 70 12 \
            "en" "$(translate "English (Recommended)")" \
            "es" "$(translate "Spanish")" \
            "fr" "$(translate "French")" \
            "de" "$(translate "German")" \
            "it" "$(translate "Italian")" \
            "pt" "$(translate "Portuguese")" 3>&1 1>&2 2>&3)

    if [ -z "$LANGUAGE" ]; then
        msg_error "$(translate "No language selected.")"
        return
    fi

    # Update only the language field in the config file
    if [ -f "$CONFIG_FILE" ]; then
        tmp=$(mktemp)
        jq --arg lang "$LANGUAGE" '.language = $lang' "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
    else
        echo "{\"language\": \"$LANGUAGE\"}" > "$CONFIG_FILE"
    fi

    msg_ok "$(translate "Language changed to") $LANGUAGE"

    # Reload the menu
    TMP_FILE=$(mktemp)
    curl -s "$REPO_URL/scripts/menus/config_menu.sh" > "$TMP_FILE"
    chmod +x "$TMP_FILE"

    trap 'rm -f "$TMP_FILE"' EXIT

    exec bash "$TMP_FILE"
}



# ==========================================================

show_version_info() {

    local version
    version=$(<"$LOCAL_VERSION_FILE")

    # Prepare the information message
    local info_message="$(translate "Current ProxMenux version:") $version\n\n"
    info_message+="$(translate "Installed components:")\n"
    
    # Check and add information about installed components
    if [ -f "$CONFIG_FILE" ]; then
        while IFS=': ' read -r component value; do
            if [ "$component" = "language" ]; then
                continue
            fi
            
            local status
            if echo "$value" | jq -e '.status' >/dev/null 2>&1; then
                status=$(echo "$value" | jq -r '.status')
            else
                status="$value"
            fi
            
            local translated_status=$(translate "$status")
            case "$status" in
                "installed"|"already_installed"|"created"|"already_exists"|"upgraded")
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
    
    # Add information about ProxMenu files with paths
    info_message+="\n$(translate "ProxMenu files:")\n"
    [ -f "$INSTALL_DIR/$MENU_SCRIPT" ] && info_message+="✓ $MENU_SCRIPT → $INSTALL_DIR/$MENU_SCRIPT\n" || info_message+="✗ $MENU_SCRIPT\n"
    [ -f "$CACHE_FILE" ] && info_message+="✓ cache.json → $CACHE_FILE\n" || info_message+="✗ cache.json\n"
    [ -f "$UTILS_FILE" ] && info_message+="✓ utils.sh → $UTILS_FILE\n" || info_message+="✗ utils.sh\n"
    [ -f "$CONFIG_FILE" ] && info_message+="✓ config.json → $CONFIG_FILE\n" || info_message+="✗ config.json\n"
    [ -f "$LOCAL_VERSION_FILE" ] && info_message+="✓ version.txt → $LOCAL_VERSION_FILE\n" || info_message+="✗ version.txt\n"
    
    # Add information about the virtual environment with path
    info_message+="\n$(translate "Virtual Environment:")\n"
    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/activate" ]; then
        info_message+="✓ $(translate "Installed") → $VENV_PATH\n"
        if [ -f "$VENV_PATH/bin/pip" ]; then
            info_message+="✓ pip: $(translate "Installed") → $VENV_PATH/bin/pip\n"
        else
            info_message+="✗ pip: $(translate "Not installed")\n"
        fi
    else
        info_message+="✗ $(translate "Virtual Environment"): $(translate "Not installed")\n"
        info_message+="✗ pip: $(translate "Not installed")\n"
    fi
    
    # Display the current language (without path)
    local current_language=$(jq -r '.language // "en"' "$CONFIG_FILE")
    info_message+="\n$(translate "Current language:")\n"
    info_message+="$current_language\n"
    
    # Display the information using whiptail
    whiptail --title "$(translate "ProxMenux Information")" \
             --scrolltext \
             --msgbox "$info_message" 20 70
}


# ==========================================================

uninstall_proxmenu() {
    if ! whiptail --title "Uninstall ProxMenu" --yesno "$(translate "Are you sure you want to uninstall ProxMenu?")" 10 60; then
        return
    fi

    # Show checklist for dependencies
    DEPS_TO_REMOVE=$(whiptail --title "Remove Dependencies" --checklist \
        "Select dependencies to remove:" 15 60 3 \
        "python3-venv" "Python virtual environment" OFF \
        "python3-pip"  "Python package installer" OFF \
        "jq"          "JSON processor" OFF \
        3>&1 1>&2 2>&3)
    
    echo "Uninstalling ProxMenu..."

    # Remove googletrans if virtual environment exists
    if [ -f "$VENV_PATH/bin/activate" ]; then
        echo "Removing googletrans..."
        source "$VENV_PATH/bin/activate"
        pip uninstall -y googletrans >/dev/null 2>&1
        deactivate
    fi

    # Remove virtual environment
    if [ -d "$VENV_PATH" ]; then
        echo "Removing virtual environment..."
        rm -rf "$VENV_PATH"
    fi

    # Remove selected dependencies
    if [ -n "$DEPS_TO_REMOVE" ]; then
        echo "Removing selected dependencies..."
        # Remove quotes and process each package
        for dep in $(echo "$DEPS_TO_REMOVE" | tr -d '"'); do
            echo "Removing $dep..."
            
            # Mark package as auto-installed
            apt-mark auto "$dep" >/dev/null 2>&1
            
            # Try to remove with apt-get
            if ! apt-get -y --purge autoremove "$dep" >/dev/null 2>&1; then
                echo "Failed to remove $dep with apt-get. Trying with dpkg..."
                if ! dpkg --purge "$dep" >/dev/null 2>&1; then
                    echo "Failed to remove $dep with dpkg. Trying to force removal..."
                    dpkg --force-all --purge "$dep" >/dev/null 2>&1
                fi
            fi
            
            # Verify if the package was actually removed
            if dpkg -l "$dep" 2>/dev/null | grep -q '^ii'; then
                echo "Warning: Failed to completely remove $dep. You may need to remove it manually."
            else
                echo "$dep successfully removed."
            fi
        done
        
        # Run autoremove to clean up any leftover dependencies
        echo "Cleaning up unnecessary packages..."
        apt-get autoremove -y --purge >/dev/null 2>&1
    fi

    # Remove ProxMenu files
    rm -f "/usr/local/bin/menu.sh"
    rm -rf "$BASE_DIR"

    echo "ProxMenu has been uninstalled."
    
    if [ -n "$DEPS_TO_REMOVE" ]; then
        echo "The following dependencies have been removed successfully: $DEPS_TO_REMOVE"
    fi
    
    echo
    echo "ProxMenux uninstallation complete. Thank you for using it!"
    echo
    exit 0
}


show_config_menu
