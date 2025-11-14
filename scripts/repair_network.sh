#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description:
# This script allows users to assign physical disks for passthrough to existing
# Proxmox virtual machines (VMs) through an interactive menu.
# - Detects and lists physical and network interfaces.
# - Verifies and repairs bridge configurations.
# - Ensures network connectivity by checking IP assignments.
# - Provides options to manually repair or verify network settings.
# - Offers interactive menus for user-friendly operation.
#
# The script aims to simplify network troubleshooting and ensure
# that Proxmox systems maintain stable connectivity.
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
# ==========================================================

# Function to detect physical network interfaces
detect_physical_interfaces() {

    physical_interfaces=$(ip -o link show | awk -F': ' '$2 !~ /^(lo|veth|dummy|bond)/ {print $2}')
    whiptail --title "$(translate 'Network Interfaces')" --msgbox "$physical_interfaces" 10 78
}


# Function to get all relevant network interfaces (physical and bridges)
get_relevant_interfaces() {
    echo $(ip -o link show | awk -F': ' '$2 !~ /^(lo|veth|dummy)/ {print $2}')
}



# Function to check and fix bridge configuration
check_and_fix_bridges() {

    local output=""
    output+="$(translate 'Checking bridges')\\n\\n"
    bridges=$(grep "^auto vmbr" /etc/network/interfaces | awk '{print $2}')
    for bridge in $bridges; do
        old_port=$(grep -A1 "iface $bridge" /etc/network/interfaces | grep "bridge-ports" | awk '{print $2}')
        if ! ip link show "$old_port" &>/dev/null; then
            output+="$(translate 'Bridge port missing'): $bridge - $old_port\\n"
            new_port=$(echo "$physical_interfaces" | tr ' ' '\n' | grep -v "vmbr" | head -n1)
            if [ -n "$new_port" ]; then
                sed -i "/iface $bridge/,/bridge-ports/ s/bridge-ports.*/bridge-ports $new_port/" /etc/network/interfaces
                output+="$(translate 'Bridge port updated'): $bridge - $old_port -> $new_port\\n"
            else
                output+="$(translate 'No physical interface available')\\n"
            fi
        else
            output+="$(translate 'Bridge port OK'): $bridge - $old_port\\n"
        fi
    done
    whiptail --title "$(translate 'Checking Bridges')" --msgbox "$output" 20 78
}


clean_nonexistent_interfaces() {

    local output=""
    output+="$(translate 'Cleaning interfaces')\\n\\n"
    configured_interfaces=$(grep "^iface" /etc/network/interfaces | awk '{print $2}' | grep -v "lo")
    for iface in $configured_interfaces; do
        if [[ ! $iface =~ ^(vmbr|bond) ]] && ! ip link show "$iface" &>/dev/null; then
            sed -i "/iface $iface/,/^$/d" /etc/network/interfaces
            output+="$(translate 'Interface removed'): $iface\\n"
        fi
    done
    whiptail --title "$(translate 'Cleaning Interfaces')" --msgbox "$output" 15 78
}


# Update other functions to use physical_interfaces or get_relevant_interfaces as appropriate
configure_physical_interfaces() {

    local output=""
    output+="$(translate 'Configuring interfaces')\\n\\n"
    for iface in $physical_interfaces; do
        if ! grep -q "iface $iface" /etc/network/interfaces; then
            echo -e "\niface $iface inet manual" >> /etc/network/interfaces
            output+="$(translate 'Interface added'): $iface\\n"
        fi
    done
    whiptail --title "$(translate 'Configuring Interfaces')" --msgbox "$output" 15 78
}

# Function to restart networking service
restart_networking() {
    if (whiptail --title "$(translate 'Restarting Network')" --yesno "$(translate 'Do you want to restart the network service?')" 10 60); then
        clear
        msg_info "$(translate 'The network service is about to restart. You may experience a brief disconnection.')"
        systemctl restart networking
        if [ $? -eq 0 ]; then
            msg_ok "$(translate 'Network service restarted successfully')"
        else
            msg_error "$(translate 'Failed to restart network service')"
        fi
    else
        msg_ok "$(translate 'Network restart canceled')"
    fi
}

# Function to check network connectivity
check_network_connectivity() {
    if ping -c 4 8.8.8.8 &> /dev/null; then
        msg_ok "$(translate 'Network connectivity OK')"
        return 0
    else
        msg_error "$(translate 'Network connectivity failed')"
        return 1
    fi
}


# Update the show_ip_info function to use the new get_relevant_interfaces function
show_ip_info() {
    whiptail --title "$(translate 'IP Information')" --infobox "$(translate 'Gathering IP information...')" 8 78
    local ip_info=""
    ip_info+="$(translate 'IP Information')\\n\\n"

    local interfaces=$(get_relevant_interfaces)

    for interface in $interfaces; do
        local interface_ip=$(ip -4 addr show $interface 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
        if [ -n "$interface_ip" ]; then
            ip_info+="$interface: $interface_ip\\n"
        else
            ip_info+="$interface: $(translate 'No IP assigned')\\n"
        fi
    done

    whiptail --title "$(translate 'Result')" --msgbox "${ip_info}\\n\\n$(translate 'IP information gathering completed')\\n\\n$(translate 'Press Enter to continue')" 20 78
}


# Function to repair network
repair_network() {
    whiptail --title "$(translate 'Network Repair Started')" --infobox "$(translate 'Repairing network...')" 8 78
    echo -ne "${TAB}${YW}-$(translate 'Repairing network...') ${CL}"
    sleep 3
    detect_physical_interfaces
    clean_nonexistent_interfaces
    check_and_fix_bridges
    configure_physical_interfaces
    restart_networking
    if check_network_connectivity; then
        show_ip_info
        msg_ok "$(translate 'Network repair completed successfully')"
    else
        msg_error "$(translate 'Network repair failed')"
    fi
    whiptail --title "$(translate 'Result')" --msgbox "$(translate 'Repair process completed')\\n\\n$(translate 'Press Enter to continue')" 10 78
}

# Function to verify network configuration
verify_network() {
    whiptail --title "$(translate 'Network Verification Started')" --infobox "$(translate 'Verifying network...')" 8 78
    echo -ne "${TAB}${YW}-$(translate 'Verifying network...') ${CL}"
    detect_physical_interfaces
    show_ip_info
    if check_network_connectivity; then
        msg_ok "$(translate 'Network verification completed successfully')"
    else
        msg_error "$(translate 'Network verification failed')"
    fi
    whiptail --title "$(translate 'Result')" --msgbox "$(translate 'Verification process completed')\\n\\n$(translate 'Press Enter to continue')" 10 78
}

# Function to show main menu
show_main_menu() {
    while true; do
        OPTION=$(whiptail --title "$(translate 'Network Repair Menu')" --menu "$(translate 'Choose an option:')" 15 60 4 \
        "1" "$(translate 'Verify Network')" \
        "2" "$(translate 'Show IP Information')" \
        "3" "$(translate "Return to Main Menu")" 3>&1 1>&2 2>&3)

        case $OPTION in
            1)
                verify_network
                ;;
            2)
                show_ip_info
                ;;
            3) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
            *) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
            
        esac
    done
}


    clear
    #show_proxmenux_logo
    show_main_menu
