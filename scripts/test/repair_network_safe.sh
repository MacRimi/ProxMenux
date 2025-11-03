#!/bin/bash

# ==========================================================
# ProxMenu - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT
# Version     : 1.1
# Last Updated: 30/04/2025
# ==========================================================
# Description:
# This script allows users to repair or verify network configuration in Proxmox.
# It avoids making changes if the system is already connected to the internet.
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

detect_physical_interfaces() {
    physical_interfaces=$(ip -o link show | awk -F': ' '$2 !~ /^(lo|veth|dummy|bond|tap|fw|vmbr|br)/ {print $2}')
    whiptail --title "$(translate 'Network Interfaces')" --msgbox "$physical_interfaces" 10 78
}

get_relevant_interfaces() {
    echo $(ip -o link show | awk -F': ' '$2 !~ /^(lo|veth|dummy)/ {print $2}')
}

check_and_fix_bridges() {
    local output=""
    output+="$(translate 'Checking bridges')\n\n"

    bridges=$(grep "^auto vmbr" /etc/network/interfaces | awk '{print $2}')

    for bridge in $bridges; do
        old_port=$(grep -A1 "iface $bridge" /etc/network/interfaces | grep "bridge-ports" | awk '{print $2}')

        if ! ip link show "$old_port" &>/dev/null; then
            output+="$(translate 'Bridge port missing'): $bridge - $old_port\n"

            new_port=$(whiptail --title "$(translate 'Missing Port Detected')"                 --menu "$(translate 'The bridge') $bridge $(translate 'is using a missing port') ($old_port).\n\n$(translate 'Select a replacement interface:')"                 20 60 10                 $(echo "$physical_interfaces" | tr ' ' '\n' | grep -v "vmbr" | awk '{print $1 " " $1}')                 3>&1 1>&2 2>&3)

            if [ -n "$new_port" ]; then
                sed -i "/iface $bridge/,/bridge-ports/ s/bridge-ports.*/bridge-ports $new_port/" /etc/network/interfaces
                output+="$(translate 'Bridge port updated'): $bridge - $old_port -> $new_port\n"
            else
                output+="$(translate 'No replacement selected. Skipping update for') $bridge\n"
            fi
        else
            output+="$(translate 'Bridge port OK'): $bridge - $old_port\n"
        fi
    done

    whiptail --title "$(translate 'Checking Bridges')" --msgbox "$output" 20 78
}

clean_nonexistent_interfaces() {
    local output=""
    output+="$(translate 'Cleaning interfaces')\n\n"
    configured_interfaces=$(grep "^iface" /etc/network/interfaces | awk '{print $2}' | grep -v "lo")
    for iface in $configured_interfaces; do
        if [[ ! $iface =~ ^(vmbr|bond) ]] && ! ip link show "$iface" &>/dev/null; then
            sed -i "/iface $iface/,/^$/d" /etc/network/interfaces
            output+="$(translate 'Interface removed'): $iface\n"
        fi
    done
    whiptail --title "$(translate 'Cleaning Interfaces')" --msgbox "$output" 15 78
}

configure_physical_interfaces() {
    local output=""
    output+="$(translate 'Configuring interfaces')\n\n"
    for iface in $physical_interfaces; do
        if ! grep -q "iface $iface" /etc/network/interfaces; then
            echo -e "\niface $iface inet manual" >> /etc/network/interfaces
            output+="$(translate 'Interface added'): $iface\n"
        fi
    done
    whiptail --title "$(translate 'Configuring Interfaces')" --msgbox "$output" 15 78
}

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

check_network_connectivity() {
    if ping -c 4 8.8.8.8 &> /dev/null; then
        msg_ok "$(translate 'Network connectivity OK')"
        return 0
    else
        msg_error "$(translate 'Network connectivity failed')"
        return 1
    fi
}

show_ip_info() {
    whiptail --title "$(translate 'IP Information')" --infobox "$(translate 'Gathering IP information...')" 8 78
    local ip_info=""
    ip_info+="$(translate 'IP Information')\n\n"

    local interfaces=$(get_relevant_interfaces)

    for interface in $interfaces; do
        local interface_ip=$(ip -4 addr show $interface 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
        if [ -n "$interface_ip" ]; then
            ip_info+="$interface: $interface_ip\n"
        else
            ip_info+="$interface: $(translate 'No IP assigned')\n"
        fi
    done

    whiptail --title "$(translate 'Result')" --msgbox "${ip_info}\n\n$(translate 'IP information gathering completed')\n\n$(translate 'Press Enter to continue')" 20 78
}

repair_network() {
    if check_network_connectivity; then
        msg_ok "$(translate 'Network is already working. No repair needed.')"
        whiptail --title "$(translate 'Network Status')" --msgbox "$(translate 'Network is already connected. No action will be taken.')" 10 78
        return
    fi

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

    whiptail --title "$(translate 'Result')" --msgbox "$(translate 'Repair process completed')\n\n$(translate 'Press Enter to continue')" 10 78
}

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
    whiptail --title "$(translate 'Result')" --msgbox "$(translate 'Verification process completed')\n\n$(translate 'Press Enter to continue')" 10 78
}

show_main_menu() {
    while true; do
        OPTION=$(whiptail --title "$(translate 'Network Repair Menu')" --menu "$(translate 'Choose an option:')" 15 60 4 \
        "1" "$(translate 'Repair Network')" \
        "2" "$(translate 'Verify Network')" \
        "3" "$(translate 'Show IP Information')" \
        "4" "$(translate "Return to Main Menu")" 3>&1 1>&2 2>&3)

        case $OPTION in
            1) repair_network ;;
            2) verify_network ;;
            3) show_ip_info ;;
            4) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
            *) exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh" ;;
        esac
    done
}

clear
show_proxmenux_logo
show_main_menu
