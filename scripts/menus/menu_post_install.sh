#!/bin/bash
# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.2
# Last Updated: 06/07/2025
# ==========================================================

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
confirm_and_run() {
    local name="$1"
    local command="$2"
    
    dialog --clear --title "$(translate "Confirmation")" \
           --yesno "\n\n$(translate "Do you want to run the post-installation script from") $name?" 10 70
    
    response=$?
    clear
    
    if [ $response -eq 0 ]; then
        eval "$command"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r _
    else
        msg_warn "$(translate "Cancelled by user.")"
        sleep 1
    fi
}

# ==========================================================
confirm_automated_script() {
    local script_info=""


    script_info+="$(translate "This script will apply the following optimizations and advanced adjustments to your Proxmox VE server"):\n\n"
    script_info+="• $(translate "Configure") \Z4free repositories\Z0 $(translate "and upgrade the system (disables the enterprise repo)")\n"
    script_info+="• $(translate "Optionally remove") \Z4subscription banner\Z0 $(translate "from Proxmox web interface (you will be asked)")\n"
    script_info+="• $(translate "Optimize") \Z4memory\Z0, \Z4kernel\Z0, $(translate "and") \Z4network\Z0 $(translate "for better performance and stability")\n"
    script_info+="• $(translate "Install and configure") \Z4Log2RAM\Z0 $(translate "(only on SSD/NVMe) to protect your disk")\n"
    script_info+="• $(translate "Improve log rotation and limit log size to save space and extend disk life")\n"
    script_info+="• $(translate "Increase file and process limits for advanced workloads")\n"
    script_info+="• $(translate "Set up time synchronization and entropy generation")\n"
    script_info+="• $(translate "Add color prompts and useful aliases to the terminal environment")\n\n"

    script_info+="\Zb$(translate "All changes are reversible using the ProxMenux uninstaller.")\Z0\n\n"
    script_info+="$(translate "Do you want to apply these optimizations now?")"

    dialog --clear --colors \
           --backtitle "ProxMenux" \
           --title "$(translate "Automated Post-Install Script")" \
           --yesno "$script_info" 22 80

    local response=$?
    clear

    if [ $response -eq 0 ]; then
        bash <(curl -s $REPO_URL/scripts/post_install/auto_post_install.sh)
    else
        msg_warn "$(translate "Cancelled by user.")"
        sleep 1
    fi
}

# ==========================================================

declare -a PROXMENUX_SCRIPTS=(
    "Customizable post-installation script|ProxMenux|bash <(curl -s $REPO_URL/scripts/post_install/customizable_post_install.sh)"
    "Automated post-installation script|ProxMenux|confirm_automated_script"
    "Uninstall optimizations|ProxMenux|bash <(curl -s $REPO_URL/scripts/post_install/uninstall-tools.sh)"
)


declare -a COMMUNITY_SCRIPTS=(
    "Proxmox VE Post Install|Helper-Scripts|bash -c \"\$(wget -qLO - https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/post-pve-install.sh); msg_success \\\"\$(translate 'Press ENTER to continue...')\\\"; read -r _\""
    "Xshok-proxmox Post install|fork xshok-proxmox|confirm_and_run \"Xshok\" \"wget https://raw.githubusercontent.com/MacRimi/xshok-proxmox/master/install-post.sh -c -O install-post.sh && bash install-post.sh && rm install-post.sh\""
)

# ==========================================================

format_menu_item() {
    local description="$1"
    local source="$2"
    local total_width=62  
    

    local desc_length=${#description}
    local source_length=${#source}
    local spaces_needed=$((total_width - desc_length - source_length))
    

    [ $spaces_needed -lt 3 ] && spaces_needed=3
    

    local spacing=""
    for ((i=0; i<spaces_needed; i++)); do
        spacing+=" "
    done
    
    echo "${description}${spacing}${source}"
}

# ==========================================================
show_menu() {
    while true; do
        local menu_items=()
        

        declare -A script_commands
        local counter=1
        

        for script in "${PROXMENUX_SCRIPTS[@]}"; do
            IFS='|' read -r name source command <<< "$script"
            local translated_name="$(translate "$name")"
            local formatted_item
            formatted_item=$(format_menu_item "$translated_name" "$source")
            menu_items+=("$counter" "$formatted_item")
            script_commands["$counter"]="$command"
            ((counter++))
        done
        

        menu_items+=("" "")
        menu_items+=("-" "───────────────────── $(translate "Community Scripts") ──────────────────────")
        menu_items+=("" "")
        

        for script in "${COMMUNITY_SCRIPTS[@]}"; do
            IFS='|' read -r name source command <<< "$script"
            local translated_name="$(translate "$name")"
            local formatted_item
            formatted_item=$(format_menu_item "$translated_name" "$source")
            menu_items+=("$counter" "$formatted_item")
            script_commands["$counter"]="$command"
            ((counter++))
        done
        

        menu_items+=("" "")
        menu_items+=("0" "$(translate "Return to Main Menu")")
        

        exec 3>&1
        script_selection=$(dialog --clear \
                                 --backtitle "ProxMenux" \
                                 --title "$(translate "Post-Installation Scripts")" \
                                 --menu "\n$(translate "Select a post-installation script:"):\n" \
                                 22 78 15 \
                                 "${menu_items[@]}" 2>&1 1>&3)
        exit_status=$?
        exec 3>&-
        

        if [ $exit_status -ne 0 ] || [ "$script_selection" = "0" ]; then
            exec bash <(curl -s "$REPO_URL/scripts/menus/main_menu.sh")
        fi
        

        if [[ "$script_selection" == "-" || "$script_selection" == "" ]]; then
            continue
        fi
        

        if [[ -n "${script_commands[$script_selection]}" ]]; then
            eval "${script_commands[$script_selection]}"
        else
            msg_error "$(translate "Invalid selection")"
            sleep 1
        fi
    done
}

# ==========================================================

show_menu
