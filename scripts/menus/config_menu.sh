#!/bin/bash
# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.1
# Last Updated: 04/07/2025
# ==========================================================

# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
CONFIG_FILE="$BASE_DIR/config.json"
CACHE_FILE="$BASE_DIR/cache.json"
UTILS_FILE="$BASE_DIR/utils.sh"
LOCAL_VERSION_FILE="$BASE_DIR/version.txt"
INSTALL_DIR="/usr/local/bin"
MENU_SCRIPT="menu"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================

detect_installation_type() {
    local has_venv=false
    local has_language=false
    

    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/activate" ]; then
        has_venv=true
    fi
    

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

# ==========================================================
show_config_menu() {
    local install_type
    install_type=$(detect_installation_type)
    
    while true; do
        local menu_options=()
        local option_actions=()
        

        if [ "$install_type" = "translation" ]; then
            menu_options+=("1" "$(translate "Change Language")")
            option_actions[1]="change_language"
            
            menu_options+=("2" "$(translate "Show Version Information")")
            option_actions[2]="show_version_info"
            
            menu_options+=("3" "$(translate "Uninstall ProxMenux")")
            option_actions[3]="uninstall_proxmenu"
            
            menu_options+=("4" "$(translate "Return to Main Menu")")
            option_actions[4]="return_main"
        else

            menu_options+=("1" "Show Version Information")
            option_actions[1]="show_version_info"
            
            menu_options+=("2" "Uninstall ProxMenux")
            option_actions[2]="uninstall_proxmenu"
            
            menu_options+=("3" "Return to Main Menu")
            option_actions[3]="return_main"
        fi
        

        OPTION=$(dialog --clear --backtitle "ProxMenux Configuration" \
                        --title "$(translate "Configuration Menu")" \
                        --menu "$(translate "Select an option:")" 20 70 10 \
                        "${menu_options[@]}" 3>&1 1>&2 2>&3)
        

        case "${option_actions[$OPTION]}" in
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
                exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
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
    

    if [ -f "$CONFIG_FILE" ]; then
        tmp=$(mktemp)
        jq --arg lang "$new_language" '.language = $lang' "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
    else
        echo "{\"language\": \"$new_language\"}" > "$CONFIG_FILE"
    fi
    
    dialog --clear --backtitle "ProxMenux Configuration" \
           --title "$(translate "Language Change")" \
           --msgbox "\n\n$(translate "Language changed to") $new_language" 10 50
    

    TMP_FILE=$(mktemp)
    curl -s "$REPO_URL/scripts/menus/config_menu.sh" > "$TMP_FILE"
    chmod +x "$TMP_FILE"
    trap 'rm -f "$TMP_FILE"' EXIT
    exec bash "$TMP_FILE"
}

# ==========================================================
show_version_info() {
    local version info_message install_type
    install_type=$(detect_installation_type)
    
    if [ -f "$LOCAL_VERSION_FILE" ]; then
        version=$(<"$LOCAL_VERSION_FILE")
    else
        version="Unknown"
    fi
    
    info_message+="$(translate "Current ProxMenux version:") $version\n\n"
    

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
            [ "$component" = "language" ] && continue
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
    
    info_message+="\n$(translate "ProxMenux files:")\n"
    [ -f "$INSTALL_DIR/$MENU_SCRIPT" ] && info_message+="✓ $MENU_SCRIPT → $INSTALL_DIR/$MENU_SCRIPT\n" || info_message+="✗ $MENU_SCRIPT\n"
    [ -f "$UTILS_FILE" ] && info_message+="✓ utils.sh → $UTILS_FILE\n" || info_message+="✗ utils.sh\n"
    [ -f "$CONFIG_FILE" ] && info_message+="✓ config.json → $CONFIG_FILE\n" || info_message+="✗ config.json\n"
    [ -f "$LOCAL_VERSION_FILE" ] && info_message+="✓ version.txt → $LOCAL_VERSION_FILE\n" || info_message+="✗ version.txt\n"
    

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
                --title "Uninstall ProxMenu" \
                --yesno "\n$(translate "Are you sure you want to uninstall ProxMenu?")" 8 60; then
        return
    fi
    
    local deps_to_remove=""
    

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
    

    (
        echo "10" ; echo "Removing ProxMenu files..."
        sleep 1
        

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
        

        if [ -n "$deps_to_remove" ]; then
            echo "70" ; echo "Removing selected dependencies..."
            read -r -a DEPS_ARRAY <<< "$(echo "$deps_to_remove" | tr -d '"')"
            for dep in "${DEPS_ARRAY[@]}"; do
                apt-mark auto "$dep" >/dev/null 2>&1
                apt-get -y --purge autoremove "$dep" >/dev/null 2>&1
            done
            apt-get autoremove -y --purge >/dev/null 2>&1
        fi
        
        echo "90" ; echo "Restoring system files..."

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