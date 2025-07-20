#!/bin/bash
# ==========================================================
# ProxMenu - Network Management and Repair Tool
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.1
# Last Updated: 08/07/2025
# ==========================================================

# Description:
# Advanced network management and troubleshooting tool for Proxmox VE.
# Features include interface detection, bridge management, connectivity testing,
# network diagnostics, configuration backup/restore, and automated repairs.
# Special thanks to @Andres_Eduardo_Rojas_Moya for contributing the persistent
# network naming function and for the original idea.
# Configuration ============================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
BACKUP_DIR="/var/backups/proxmenux"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================
# Utility Functions
create_backup_dir() {
    [ ! -d "$BACKUP_DIR" ] && mkdir -p "$BACKUP_DIR"
}

backup_network_config() {
    create_backup_dir
    local timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
    local backup_file="$BACKUP_DIR/interfaces_backup_$timestamp"
    cp /etc/network/interfaces "$backup_file"
    echo "$backup_file"
}
# Tool registration system
ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

register_tool() {
    local tool="$1"
    local state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}
# ==========================================================
# Network Detection Functions
detect_network_method() {
    # Detect Netplan
    if compgen -G "/etc/netplan/*.yaml" > /dev/null; then
        echo "netplan"
        return 0
    fi

    # Detect systemd-networkd
    if systemctl is-active --quiet systemd-networkd 2>/dev/null; then
        echo "systemd-networkd"
        return 0
    fi

    # Detect NetworkManager
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        echo "networkmanager"
        return 0
    fi

    # Default: Debian/Proxmox classic
    echo "classic"
}

detect_physical_interfaces() {
    ip -o link show | awk -F': ' '$2 !~ /^(lo|veth|dummy|bond|tap|tun|docker|br-)/ && $2 !~ /vmbr/ {print $2}' | sort
}

detect_bridge_interfaces() {
    ip -o link show | awk -F': ' '$2 ~ /^vmbr/ {print $2}' | sort
}

detect_all_interfaces() {
    ip -o link show | awk -F': ' '$2 !~ /^(lo|veth|dummy|tap|tun)/ {print $2}' | sort
}

get_interface_info() {
    local interface="$1"
    local info=""
    
    # Get IP address
    local ip=$(ip -4 addr show "$interface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | head -1)
    [ -z "$ip" ] && ip="$(translate "No IP")"
    
    # Get status
    local status=$(ip link show "$interface" 2>/dev/null | grep -o "state [A-Z]*" | cut -d' ' -f2)
    [ -z "$status" ] && status="UNKNOWN"
    
    # Get MAC address
    local mac=$(ip link show "$interface" 2>/dev/null | grep -o "link/ether [a-f0-9:]*" | cut -d' ' -f2)
    [ -z "$mac" ] && mac="$(translate "No MAC")"
    
    echo "$interface|$ip|$status|$mac"
}

# ==========================================================

show_routing_table_() {
    local route_info=""
    route_info+="$(translate "Routing Table")\n"
    route_info+="$(printf '=%.0s' {1..30})\n\n"
    route_info+="$(ip route show)\n\n"
    route_info+="$(translate "Default Gateway"): $(ip route | grep default | awk '{print $3}' | head -1)\n"
    
    dialog --backtitle "ProxMenux" --title "$(translate "Routing Information")" \
           --msgbox "$route_info" 20 80
}


show_routing_table() {
    local route_info=""
    local default_gw=$(ip route | grep default | awk '{print $3}' | head -1)
    local routes=$(ip route show)
    local route_count=$(echo "$routes" | wc -l)
    
    route_info+="🗺️  $(translate "Routing Table")\n"
    route_info+="$(printf '═%.0s' {1..60})\n\n"
    
    if [ -z "$routes" ]; then
        route_info+="⚠️  $(translate "No routing information found.")\n\n"
    else
        route_info+="$(translate "Total routes"): $route_count\n\n"

        while read -r line; do
            if [[ "$line" == *"default"* ]]; then
                route_info+="➡️  $line\n"
            else
                route_info+="   • $line\n"
            fi
        done <<< "$routes"
        route_info+="\n"
        route_info+="🌍 $(translate "Default Gateway"): ${default_gw:-$(translate "Not found")}\n"
    fi

    dialog --backtitle "ProxMenux" --title "$(translate "Routing Information")" \
           --msgbox "$route_info" 20 80
}


# ==========================================================
# Network Testing Functions
test_connectivity() {
    local test_results=""
    local tests=(
        "8.8.8.8|Google DNS"
        "1.1.1.1|Cloudflare DNS"
        "$(ip route | grep default | awk '{print $3}' | head -1)|Gateway"
    )
    show_proxmenux_logo
    msg_info "$(translate "Test Connectivity")"
    test_results+="$(translate "Connectivity Test Results")\n"
    test_results+="$(printf '=%.0s' {1..35})\n\n"
    
    for test in "${tests[@]}"; do
        IFS='|' read -r target name <<< "$test"
        if [ -n "$target" ] && [ "$target" != "" ]; then
            if ping -c 2 -W 3 "$target" >/dev/null 2>&1; then
                test_results+="✓ $name ($target): $(translate "OK")\n"
            else
                test_results+="✗ $name ($target): $(translate "FAILED")\n"
            fi
        fi
    done
    
    # DNS Resolution test
    if nslookup google.com >/dev/null 2>&1; then
        test_results+="✓ $(translate "DNS Resolution"): $(translate "OK")\n"
    else
        test_results+="✗ $(translate "DNS Resolution"): $(translate "FAILED")\n"
    fi
    cleanup
    dialog --backtitle "ProxMenux" --title "$(translate "Connectivity Test")" \
           --msgbox "$test_results" 20 70
}

advanced_network_diagnostics() {

    NETWORK_METHOD=$(detect_network_method)

    if [[ "$NETWORK_METHOD" != "classic" ]]; then
        dialog --title "Unsupported Network Stack" \
            --msgbox "WARNING: This script only supports the classic Debian/Proxmox network configuration (/etc/network/interfaces).\n\nDetected: $NETWORK_METHOD.\n\nAborting for safety.\n\nPlease configure your network using your distribution's supported tools." 14 70
        exit 1
    fi

    show_proxmenux_logo
    msg_info "$(translate "Advanced Diagnostics")"
    sleep 1
    
    local diag_info=""
    
    diag_info+="$(translate "Advanced Network Diagnostics")\n"
    diag_info+="$(printf '=%.0s' {1..40})\n\n"
    
    # Network statistics
    diag_info+="$(translate "Active Connections"): $(ss -tuln | wc -l)\n"
    diag_info+="$(translate "Listening Ports"): $(ss -tln | grep LISTEN | wc -l)\n"
    diag_info+="$(translate "Network Interfaces"): $(ip link show | grep -c "^[0-9]")\n\n"
    
    # Check for common issues
    diag_info+="$(translate "Common Issues Check"):\n"

    # Check if NetworkManager is running (shouldn't be on Proxmox)
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        diag_info+="⚠ $(translate "NetworkManager is running (may cause conflicts)")\n"

        if dialog --title "$(translate "NetworkManager Detected")" \
                --yesno "$(translate "NetworkManager is running, which may conflict with Proxmox.")\n\n$(translate "Do you want to disable and remove it now?")" 10 70; then

            dialog --infobox "$(translate "Disabling and removing NetworkManager...")" 6 60
            systemctl stop NetworkManager >/dev/null 2>&1
            systemctl disable NetworkManager >/dev/null 2>&1
            apt-get purge -y network-manager >/dev/null 2>&1

            diag_info+="✓ $(translate "NetworkManager has been removed successfully")\n"
        else
            diag_info+="ℹ️  $(translate "User chose not to remove NetworkManager")\n"
        fi
    else
        diag_info+="✓ $(translate "NetworkManager not running")\n"
    fi

    # Check for duplicate IPs
    local ips=($(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | sort | uniq -d))
    if [ ${#ips[@]} -gt 0 ]; then
        diag_info+="⚠ $(translate "Duplicate IP addresses found"): ${ips[*]}\n"
    else
        diag_info+="✓ $(translate "No duplicate IP addresses")\n"
    fi

    cleanup 

    dialog --backtitle "ProxMenux" --title "$(translate "Network Diagnostics")" \
           --msgbox "$diag_info" 20 70
}


# ==========================================================
# SAFE Network Analysis Functions (NO AUTO-REPAIR)
# ==========================================================

analyze_bridge_configuration() {

    NETWORK_METHOD=$(detect_network_method)

    if [[ "$NETWORK_METHOD" != "classic" ]]; then
        dialog --title "Unsupported Network Stack" \
            --msgbox "WARNING: This script only supports the classic Debian/Proxmox network configuration (/etc/network/interfaces).\n\nDetected: $NETWORK_METHOD.\n\nAborting for safety.\n\nPlease configure your network using your distribution's supported tools." 14 70
        exit 1
    fi

    show_proxmenux_logo
    msg_info "$(translate "Analyzing Bridge Configuration - READ ONLY MODE")"
    sleep 1
    
    local physical_interfaces=($(detect_physical_interfaces))
    local bridges=($(detect_bridge_interfaces))
    local analysis_report=""
    local issues_found=0
    local suggestions=""
    
    analysis_report+="🔍 $(translate "BRIDGE CONFIGURATION ANALYSIS")\n"
    analysis_report+="$(printf '=%.0s' {1..50})\n\n"
    cleanup
    if [ ${#bridges[@]} -eq 0 ]; then
        analysis_report+="ℹ️  $(translate "No bridges found in system")\n"
        dialog --backtitle "ProxMenux" --title "$(translate "Bridge Analysis")" --msgbox "$analysis_report" 10 60
        return
    fi
    
    # Analyze each bridge
    for bridge in "${bridges[@]}"; do
        analysis_report+="🌉 $(translate "Bridge"): $bridge\n"
        
        # Get current configuration
        local current_ports=$(grep -A5 "iface $bridge" /etc/network/interfaces 2>/dev/null | grep "bridge-ports" | cut -d' ' -f2-)
        local bridge_ip=$(ip -4 addr show "$bridge" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | head -1)
        local bridge_status=$(ip link show "$bridge" 2>/dev/null | grep -o "state [A-Z]*" | cut -d' ' -f2)
        
        analysis_report+="   📍 $(translate "Status"): ${bridge_status:-UNKNOWN}\n"
        analysis_report+="   🌐 $(translate "IP"): ${bridge_ip:-$(translate "No IP assigned")}\n"
        analysis_report+="   🔌 $(translate "Configured Ports"): ${current_ports:-$(translate "None")}\n"
        
        if [ -n "$current_ports" ]; then
            local invalid_ports=""
            local valid_ports=""
            
            # Check each configured port
            for port in $current_ports; do
                if ip link show "$port" >/dev/null 2>&1; then
                    valid_ports+="$port "
                    analysis_report+="   ✅ $(translate "Port") $port: $(translate "EXISTS")\n"
                else
                    invalid_ports+="$port "
                    analysis_report+="   ❌ $(translate "Port") $port: $(translate "NOT FOUND")\n"
                    ((issues_found++))
                fi
            done
            
            # Generate suggestions for invalid ports
            if [ -n "$invalid_ports" ]; then
                suggestions+="🔧 $(translate "SUGGESTION FOR") $bridge:\n"
                if [ ${#physical_interfaces[@]} -gt 0 ]; then
                    suggestions+="   $(translate "Replace invalid port(s)") '$invalid_ports' $(translate "with"): ${physical_interfaces[0]}\n"
                    suggestions+="   $(translate "Command"): sed -i 's/bridge-ports.*/bridge-ports ${physical_interfaces[0]}/' /etc/network/interfaces\n"
                else
                    suggestions+="   $(translate "Remove invalid port(s)") '$invalid_ports'\n"
                    suggestions+="   $(translate "Command"): sed -i 's/bridge-ports.*/bridge-ports none/' /etc/network/interfaces\n"
                fi
                suggestions+="\n"
            fi
        else
            analysis_report+="   ⚠️  $(translate "No ports configured")\n"
            if [ ${#physical_interfaces[@]} -gt 0 ]; then
                suggestions+="🔧 $(translate "SUGGESTION FOR") $bridge:\n"
                suggestions+="   $(translate "Consider adding physical interface"): ${physical_interfaces[0]}\n"
                suggestions+="   $(translate "Command"): sed -i '/iface $bridge/a\\    bridge-ports ${physical_interfaces[0]}' /etc/network/interfaces\n\n"
            fi
        fi
        analysis_report+="\n"
    done
    
    # Summary
    analysis_report+="📊 $(translate "ANALYSIS SUMMARY")\n"
    analysis_report+="$(printf '=%.0s' {1..25})\n"
    analysis_report+="$(translate "Bridges analyzed"): ${#bridges[@]}\n"
    analysis_report+="$(translate "Issues found"): $issues_found\n"


    local auto_only=$(grep "^auto" /etc/network/interfaces | awk '{print $2}' | while read i; do
        grep -q "^iface $i" /etc/network/interfaces || echo "$i"
    done)

    if [ -n "$auto_only" ]; then
        analysis_report+="⚠️  $(translate "Interfaces defined with 'auto' but no 'iface' block"): $auto_only\n"
        ((issues_found++))
    fi

    analysis_report+="$(translate "Physical interfaces available"): ${#physical_interfaces[@]}\n\n"
    
    if [ $issues_found -gt 0 ]; then
        analysis_report+="$suggestions"
        analysis_report+="⚠️  $(translate "IMPORTANT"): $(translate "No changes have been made to your system")\n"
        analysis_report+="$(translate "Use the Guided Repair option to fix issues safely")\n"
    else
        analysis_report+="✅ $(translate "No bridge configuration issues found")\n"
    fi
    
    # Show analysis in scrollable dialog
    local temp_file=$(mktemp)
    echo -e "$analysis_report" > "$temp_file"
    dialog --backtitle "ProxMenux" --title "$(translate "Bridge Configuration Analysis")" \
           --textbox "$temp_file" 25 80
    rm -f "$temp_file"
   

    # Offer guided repair if issues found
    if [ $issues_found -gt 0 ]; then
        if dialog --backtitle "ProxMenux" --title "$(translate "Guided Repair Available")" \
                  --yesno "$(translate "Issues were found. Would you like to use the Guided Repair Assistant?")" 8 60; then
            guided_bridge_repair
        fi
    fi
}


guided_bridge_repair() {
    local step=1
    local total_steps=5


    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local preview_backup_file="$BACKUP_DIR/interfaces_backup_$timestamp"


    if ! dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Safety Backup")" \
                --yesno "$(translate "Before making any changes, we'll create a safety backup.")\n\n$(translate "Backup location"): $preview_backup_file\n\n$(translate "Continue?")" 12 70; then
        return
    fi
    ((step++))

    
    show_proxmenux_logo
    local backup_file=$(backup_network_config)
    msg_ok "$(translate "Network configuration backed up")"
    sleep 2

    dialog --backtitle "ProxMenux" --title "$(translate "Backup Created")" \
           --msgbox "$(translate "Safety backup created"): $backup_file\n\n$(translate "You can restore it anytime with"):\ncp $backup_file /etc/network/interfaces" 10 70
    
    # Step 2: Show current configuration
    if ! dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Current Configuration")" \
                --yesno "$(translate "Let's review your current network configuration.")\n\n$(translate "Would you like to see the current") /etc/network/interfaces $(translate "file?")" 10 70; then
        return
    fi
    ((step++))
    
    # Show current config
    local temp_config=$(mktemp)
    cat /etc/network/interfaces > "$temp_config"
    dialog --backtitle "ProxMenux" --title "$(translate "Current Network Configuration")" \
           --textbox "$temp_config" 20 80
    rm -f "$temp_config"
    
    # Step 3: Identify specific changes needed
    local physical_interfaces=($(detect_physical_interfaces))
    local bridges=($(detect_bridge_interfaces))
    local changes_needed=""
    
    for bridge in "${bridges[@]}"; do
        local current_ports=$(grep -A5 "iface $bridge" /etc/network/interfaces 2>/dev/null | grep "bridge-ports" | cut -d' ' -f2-)
        
        if [ -n "$current_ports" ]; then
            for port in $current_ports; do
                if ! ip link show "$port" >/dev/null 2>&1; then
                    if [ ${#physical_interfaces[@]} -gt 0 ]; then
                        changes_needed+="$(translate "Bridge") $bridge: $(translate "Replace") '$port' $(translate "with") '${physical_interfaces[0]}'\n"
                    else
                        changes_needed+="$(translate "Bridge") $bridge: $(translate "Remove invalid port") '$port'\n"
                    fi
                fi
            done
        fi
    done
    
    if [ -z "$changes_needed" ]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Changes Needed")" \
               --msgbox "$(translate "After detailed analysis, no changes are needed.")" 8 50
        return
    fi
    
    if ! dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Proposed Changes")" \
                --yesno "$(translate "These are the changes that will be made"):\n\n$changes_needed\n$(translate "Do you want to proceed?")" 15 70; then
        return
    fi
    ((step++))
    
    # Step 4: Apply changes with verification
    dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Applying Changes")" \
           --infobox "$(translate "Applying changes safely...")\n\n$(translate "This may take a few seconds...")" 8 50
    
    # Apply the changes
    for bridge in "${bridges[@]}"; do
        local current_ports=$(grep -A5 "iface $bridge" /etc/network/interfaces 2>/dev/null | grep "bridge-ports" | cut -d' ' -f2-)
        
        if [ -n "$current_ports" ]; then
            local new_ports=""
            for port in $current_ports; do
                if ip link show "$port" >/dev/null 2>&1; then
                    new_ports+="$port "
                fi
            done
            
            # If no valid ports and we have physical interfaces, use the first one
            if [ -z "$new_ports" ] && [ ${#physical_interfaces[@]} -gt 0 ]; then
                new_ports="${physical_interfaces[0]}"
            fi
            
            # Apply the change
            if [ "$new_ports" != "$current_ports" ]; then
                sed -i "/iface $bridge/,/bridge-ports/ s/bridge-ports.*/bridge-ports $new_ports/" /etc/network/interfaces
            fi
        fi
    done
    ((step++))
    
    # Step 5: Verification
    local verification_report=""
    verification_report+="✅ $(translate "CHANGES APPLIED SUCCESSFULLY")\n\n"
    verification_report+="$(translate "Verification"):\n"
    
    for bridge in "${bridges[@]}"; do
        local new_ports=$(grep -A5 "iface $bridge" /etc/network/interfaces 2>/dev/null | grep "bridge-ports" | cut -d' ' -f2-)
        verification_report+="$(translate "Bridge") $bridge: $new_ports\n"
        
        # Verify each port exists
        for port in $new_ports; do
            if ip link show "$port" >/dev/null 2>&1; then
                verification_report+="  ✅ $port: $(translate "EXISTS")\n"
            else
                verification_report+="  ❌ $port: $(translate "NOT FOUND")\n"
            fi
        done
    done
    
    verification_report+="\n$(translate "Backup available at"): $backup_file\n"
    verification_report+="$(translate "To restore"): cp $backup_file /etc/network/interfaces"
    
    dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Repair Complete")" \
           --msgbox "$verification_report" 18 70
    
    # Ask about network restart
    if dialog --backtitle "ProxMenux" --title "$(translate "Network Restart")" \
              --yesno "$(translate "Changes have been applied to the configuration file.")\n\n$(translate "Do you want to restart the network service to apply changes?")\n\n$(translate "WARNING: This may cause a brief disconnection.")" 12 70; then
        
        clear
        msg_info "$(translate "Restarting network service...")"
        
        if systemctl restart networking; then
            msg_ok "$(translate "Network service restarted successfully")"
        else
            msg_error "$(translate "Failed to restart network service")"
            msg_warn "$(translate "You can restore the backup with"): cp $backup_file /etc/network/interfaces"
        fi
        
        msg_success "$(translate "Press ENTER to continue...")"
        read -r
    fi
}


# ==========================================================




analyze_network_configuration() {

    NETWORK_METHOD=$(detect_network_method)

    if [[ "$NETWORK_METHOD" != "classic" ]]; then
        dialog --title "Unsupported Network Stack" \
            --msgbox "WARNING: This script only supports the classic Debian/Proxmox network configuration (/etc/network/interfaces).\n\nDetected: $NETWORK_METHOD.\n\nAborting for safety.\n\nPlease configure your network using your distribution's supported tools." 14 70
        exit 1
    fi

    show_proxmenux_logo
    msg_info "$(translate "Analyzing Network Configuration - READ ONLY MODE")"
    sleep 1
    
    local configured_interfaces=($(grep "^iface" /etc/network/interfaces | awk '{print $2}' | grep -v "lo"))
    local analysis_report=""
    local issues_found=0
    local suggestions=""
    
    analysis_report+="🔍 $(translate "NETWORK CONFIGURATION ANALYSIS")\n"
    analysis_report+="$(printf '=%.0s' {1..50})\n\n"
    
    cleanup
    if [ ${#configured_interfaces[@]} -eq 0 ]; then
        analysis_report+="ℹ️  $(translate "No network interfaces configured (besides loopback)")\n"
        dialog --title "$(translate "Configuration Analysis")" --msgbox "$analysis_report" 10 60
        return
    fi
    
    analysis_report+="📋 $(translate "CONFIGURED INTERFACES")\n"
    analysis_report+="$(printf '=%.0s' {1..30})\n"
    
    # Analyze each configured interface
    for iface in "${configured_interfaces[@]}"; do
        analysis_report+="🔌 $(translate "Interface"): $iface\n"
        
        # Check if interface exists physically
        if ip link show "$iface" >/dev/null 2>&1; then
            local status=$(ip link show "$iface" 2>/dev/null | grep -o "state [A-Z]*" | cut -d' ' -f2)
            local ip=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | head -1)
            
            analysis_report+="   ✅ $(translate "Status"): $(translate "EXISTS") ($status)\n"
            analysis_report+="   🌐 $(translate "IP"): ${ip:-$(translate "No IP assigned")}\n"
            
            # Check if it's a bridge or bond (these are virtual, so it's normal they exist)
            if [[ $iface =~ ^(vmbr|bond) ]]; then
                analysis_report+="   ℹ️  $(translate "Type"): $(translate "Virtual interface (normal)")\n"
            else
                analysis_report+="   ℹ️  $(translate "Type"): $(translate "Physical interface")\n"
            fi
        else
            analysis_report+="   ❌ $(translate "Status"): $(translate "NOT FOUND")\n"
            analysis_report+="   ⚠️  $(translate "Issue"): $(translate "Configured but doesn't exist")\n"
            ((issues_found++))
            
            # Only suggest removal for non-virtual interfaces
            if [[ ! $iface =~ ^(vmbr|bond) ]]; then
                suggestions+="🔧 $(translate "SUGGESTION FOR") $iface:\n"
                suggestions+="   $(translate "This interface is configured but doesn't exist physically")\n"
                suggestions+="   $(translate "Consider removing its configuration")\n"
                suggestions+="   $(translate "Command"): sed -i '/iface $iface/,/^$/d' /etc/network/interfaces\n\n"
            fi
        fi
        analysis_report+="\n"
    done
    
    # Summary
    analysis_report+="📊 $(translate "ANALYSIS SUMMARY")\n"
    analysis_report+="$(printf '=%.0s' {1..25})\n"
    analysis_report+="$(translate "Interfaces configured"): ${#configured_interfaces[@]}\n"
    analysis_report+="$(translate "Issues found"): $issues_found\n\n"
    
    if [ $issues_found -gt 0 ]; then
        analysis_report+="$suggestions"
        analysis_report+="⚠️  $(translate "IMPORTANT"): $(translate "No changes have been made to your system")\n"
        analysis_report+="$(translate "Use the Guided Cleanup option to fix issues safely")\n"
    else
        analysis_report+="✅ $(translate "No configuration issues found")\n"
    fi
    
    # Show analysis in scrollable dialog
    local temp_file=$(mktemp)
    echo -e "$analysis_report" > "$temp_file"
    dialog --backtitle "ProxMenux" --title "$(translate "Network Configuration Analysis")" \
           --textbox "$temp_file" 25 80
    rm -f "$temp_file"
    
    # Offer guided cleanup if issues found
    if [ $issues_found -gt 0 ]; then
        if dialog --backtitle "ProxMenux" --title "$(translate "Guided Cleanup Available")" \
                  --yesno "$(translate "Issues were found. Would you like to use the Guided Cleanup Assistant?")" 8 60; then
            guided_configuration_cleanup
        fi
    fi
}

guided_configuration_cleanup() {
    local step=1
    local total_steps=5

    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local preview_backup_file="$BACKUP_DIR/interfaces_backup_$timestamp"


    if ! dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Safety Backup")" \
                --yesno "$(translate "Before making any changes, we'll create a safety backup.")\n\n$(translate "Backup location"): $preview_backup_file\n\n$(translate "Continue?")" 12 70; then
        return
    fi
    ((step++))

    
    show_proxmenux_logo
    local backup_file=$(backup_network_config)
    msg_ok "$(translate "Network configuration backed up")"
    sleep 2
    
    dialog --backtitle "ProxMenux" --title "$(translate "Backup Created")" \
           --msgbox "$(translate "Safety backup created"): $backup_file\n\n$(translate "You can restore it anytime with"):\ncp $backup_file /etc/network/interfaces" 10 70
    
    # Step 2: Identify interfaces to remove
    local configured_interfaces=($(grep "^iface" /etc/network/interfaces | awk '{print $2}' | grep -v "lo"))
    local interfaces_to_remove=""
    local removal_list=""
    
    for iface in "${configured_interfaces[@]}"; do
        if [[ ! $iface =~ ^(vmbr|bond) ]] && ! ip link show "$iface" >/dev/null 2>&1; then
            interfaces_to_remove+="$iface "
            removal_list+="❌ $iface: $(translate "Configured but doesn't exist")\n"
        fi
    done
    
    if [ -z "$interfaces_to_remove" ]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Cleanup Needed")" \
               --msgbox "$(translate "After detailed analysis, no cleanup is needed.")" 8 50
        return
    fi
    
    if ! dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Interfaces to Remove")" \
                --yesno "$(translate "These interface configurations will be removed"):\n\n$removal_list\n$(translate "Do you want to proceed?")" 15 70; then
        return
    fi
    ((step++))
    
    # Step 3: Show what will be removed
    local temp_preview=$(mktemp)
    echo "$(translate "Configuration sections that will be REMOVED"):" > "$temp_preview"
    echo "=================================================" >> "$temp_preview"
    echo "" >> "$temp_preview"
    
    for iface in $interfaces_to_remove; do
        echo "# Interface: $iface" >> "$temp_preview"
        sed -n "/^iface $iface/,/^$/p" /etc/network/interfaces >> "$temp_preview"
        echo "" >> "$temp_preview"
    done
    
    if ! dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Preview Changes")" \
                --yesno "$(translate "Review what will be removed"):\n\n$(translate "Press OK to see the preview, then confirm")" 10 60; then
        rm -f "$temp_preview"
        return
    fi
    
    dialog --backtitle "ProxMenux" --title "$(translate "Configuration to be Removed")" \
           --textbox "$temp_preview" 20 80
    rm -f "$temp_preview"
    
    if ! dialog --backtitle "ProxMenux" --title "$(translate "Final Confirmation")" \
                --yesno "$(translate "Are you sure you want to remove these configurations?")" 8 60; then
        return
    fi
    ((step++))
    
    # Step 4: Apply changes
    dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Applying Changes")" \
           --infobox "$(translate "Removing invalid configurations...")\n\n$(translate "This may take a few seconds...")" 8 50
    
    for iface in $interfaces_to_remove; do
        sed -i "/^iface $iface/,/^$/d" /etc/network/interfaces
    done
    ((step++))
    
    # Step 5: Verification
    local verification_report=""
    verification_report+="✅ $(translate "CLEANUP COMPLETED SUCCESSFULLY")\n\n"
    verification_report+="$(translate "Removed configurations for"):\n"
    
    for iface in $interfaces_to_remove; do
        verification_report+="❌ $iface\n"
    done
    
    verification_report+="\n$(translate "Verification"): $(translate "Checking remaining interfaces")\n"
    local remaining_interfaces=($(grep "^iface" /etc/network/interfaces | awk '{print $2}' | grep -v "lo"))
    
    for iface in "${remaining_interfaces[@]}"; do
        if ip link show "$iface" >/dev/null 2>&1; then
            verification_report+="✅ $iface: $(translate "OK")\n"
        else
            verification_report+="⚠️  $iface: $(translate "Still has issues")\n"
        fi
    done
    
    verification_report+="\n$(translate "Backup available at"): $backup_file\n"
    verification_report+="$(translate "To restore"): cp $backup_file /etc/network/interfaces"
    
    dialog --backtitle "ProxMenux" --title "$(translate "Step") $step/$total_steps: $(translate "Cleanup Complete")" \
           --msgbox "$verification_report" 18 70
}


# ==========================================================



setup_persistent_network() {
    local LINK_DIR="/etc/systemd/network"
    local BACKUP_DIR="/etc/systemd/network/backup-$(date +%Y%m%d-%H%M%S)"
    
    if ! dialog --title "$(translate "Network Interface Setup")" \
         --yesno "\n$(translate "Create persistent network interface names?")" 8 60; then
        return 1
    fi
    ensure_tools_json
    show_proxmenux_logo    
    msg_info "$(translate "Setting up persistent network interfaces")"
    sleep 2
    # Create directory
    mkdir -p "$LINK_DIR"
    
    # Backup existing files
    if ls "$LINK_DIR"/*.link >/dev/null 2>&1; then
        mkdir -p "$BACKUP_DIR"
        cp "$LINK_DIR"/*.link "$BACKUP_DIR"/ 2>/dev/null || true
    fi
    
    # Process physical interfaces
    local count=0
    for iface in $(ls /sys/class/net/ | grep -vE "lo|docker|veth|br-|vmbr|tap|fwpr|fwln|virbr|bond|cilium|zt|wg"); do
        if [[ -e "/sys/class/net/$iface/device" ]] || [[ -e "/sys/class/net/$iface/phy80211" ]]; then
            local MAC=$(cat /sys/class/net/$iface/address 2>/dev/null)
            
            if [[ "$MAC" =~ ^([a-fA-F0-9]{2}:){5}[a-fA-F0-9]{2}$ ]]; then
                local LINK_FILE="$LINK_DIR/10-$iface.link"
                
                cat > "$LINK_FILE" <<EOF
[Match]
MACAddress=$MAC

[Link]
Name=$iface
EOF
                chmod 644 "$LINK_FILE"
                ((count++))
            fi
        fi
    done
    
    if [[ $count -gt 0 ]]; then
        msg_ok "$(translate "Created persistent names for") $count $(translate "interfaces")"
        msg_ok "$(translate "Changes will apply after reboot.")"
    else
        msg_warn "$(translate "No physical interfaces found")"
    fi
        register_tool "persistent_network" true
        echo -e
        msg_success "$(translate "Press ENTER to continue...")"
        read -r
}



# ==========================================================


restart_network_service() {
    if dialog --title "$(translate "Restart Network")" \
              --yesno "\n$(translate "This will restart the network service and may cause a brief disconnection. Continue?")" 10 60; then

        show_proxmenux_logo
        msg_info "$(translate "Restarting network service...")"

        if systemctl restart networking; then
            msg_ok "$(translate "Network service restarted successfully")"
        else
            msg_error "$(translate "Failed to restart network service")"
            msg_warn "$(translate "If you lose connectivity, you can restore from backup using the console.")"
        fi

        msg_success "$(translate "Press ENTER to continue...")"
        read -r
    fi
}



# ==========================================================
# Configuration Management
show_network_config() {

    NETWORK_METHOD=$(detect_network_method)

    if [[ "$NETWORK_METHOD" != "classic" ]]; then
        dialog --title "Unsupported Network Stack" \
            --msgbox "WARNING: This script only supports the classic Debian/Proxmox network configuration (/etc/network/interfaces).\n\nDetected: $NETWORK_METHOD.\n\nAborting for safety.\n\nPlease configure your network using your distribution's supported tools." 14 70
        exit 1
    fi

    local config_content
    config_content=$(cat /etc/network/interfaces)
    show_proxmenux_logo
    echo -e
    echo -e
    echo "========== $(translate "Network Configuration File") =========="
    echo
    cat /etc/network/interfaces
    echo
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}


create_network_backup_manual() {

    NETWORK_METHOD=$(detect_network_method)

    if [[ "$NETWORK_METHOD" != "classic" ]]; then
        dialog --title "Unsupported Network Stack" \
            --msgbox "WARNING: This script only supports the classic Debian/Proxmox network configuration (/etc/network/interfaces).\n\nDetected: $NETWORK_METHOD.\n\nAborting for safety.\n\nPlease configure your network using your distribution's supported tools." 14 70
        exit 1
    fi

    show_proxmenux_logo
    echo -e
    msg_info "$(translate "Creating backup of network interfaces configuration...")"
    sleep 3
    cleanup
    backup_network_config
    msg_ok "$(translate "Network configuration backed up")"
    echo -e
    msg_success "$(translate "Press Enter to continue...")"
    read -r

}



restore_network_backup() {

    NETWORK_METHOD=$(detect_network_method)

    if [[ "$NETWORK_METHOD" != "classic" ]]; then
        dialog --title "Unsupported Network Stack" \
            --msgbox "WARNING: This script only supports the classic Debian/Proxmox network configuration (/etc/network/interfaces).\n\nDetected: $NETWORK_METHOD.\n\nAborting for safety.\n\nPlease configure your network using your distribution's supported tools." 14 70
        exit 1
    fi

    local backups=($(ls -1 "$BACKUP_DIR"/interfaces_backup_* 2>/dev/null | sort -r))
    
    if [ ${#backups[@]} -eq 0 ]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No Backups")" \
               --msgbox "\n$(translate "No network configuration backups found.")" 14 60
        return
    fi

    local menu_items=()
    local counter=1

    for backup in "${backups[@]}"; do
        local filename=$(basename "$backup")
        local timestamp=$(basename "$backup" | sed 's/interfaces_backup_//')
        menu_items+=("$counter" "$timestamp")
        ((counter++))
    done

    local selection=$(dialog --backtitle "ProxMenux" --title "$(translate "Restore Backup")" \
                            --menu "$(translate "Select backup to restore:"):" 20 70 12 \
                            "${menu_items[@]}" 3>&1 1>&2 2>&3)

    if [ -n "$selection" ] && [ "$selection" -ge 1 ] && [ "$selection" -le ${#backups[@]} ]; then
        local selected_backup="${backups[$((selection-1))]}"


        if dialog --backtitle "ProxMenux" --title "$(translate "Preview Backup")" \
                  --yesno "\n$(translate "Do you want to view the selected backup before restoring?")" 8 60; then
            dialog --backtitle "ProxMenux" --title "$(translate "Backup Preview")" \
                   --textbox "$selected_backup" 22 80
        fi

        if dialog --backtitle "ProxMenux" --title "$(translate "Confirm Restore")" \
            --yesno "\n$(translate "Are you sure you want to restore this backup?\nCurrent configuration will be overwritten.")\n\n$(translate "For your safety, a backup of the current configuration will be created automatically before restoring.")" 14 70; then

            local pre_restore_backup=$(backup_network_config)
            cp "$selected_backup" /etc/network/interfaces


            dialog --backtitle "ProxMenux" --title "$(translate "Backup Restored")" \
                   --msgbox "\n$(translate "Network configuration has been restored from backup.")" 8 60


            if dialog --backtitle "ProxMenux" --title "$(translate "Restart Network")" \
                      --yesno "\n$(translate "Do you want to restart the network service now to apply changes?")" 8 60; then
                if systemctl restart networking; then
                    dialog --backtitle "ProxMenux" --title "$(translate "Network Restarted")" \
                           --msgbox "\n$(translate "Network service restarted successfully.")" 8 50
                fi
            fi
        fi
    fi
}


launch_iftop() {
    if ! command -v iftop &>/dev/null; then
        apt-get update -qq && apt-get install -y iftop &>/dev/null
    fi

    dialog --backtitle "ProxMenux" --title "$(translate "iftop usage")" --msgbox "\n$(translate "To exit iftop, press q")" 8 50
    clear
    iftop
}

launch_iptraf() {
    if ! command -v iptraf-ng &>/dev/null; then
        apt-get update -qq && apt-get install -y iptraf-ng &>/dev/null
    fi

    dialog --backtitle "ProxMenux" --title "$(translate "iptraf-ng usage")" --msgbox "\n$(translate "To exit iptraf-ng, press x")" 8 50
    clear
    iptraf-ng
}


# ==========================================================


confirm_and_run() {
    local name="$1"
    local command="$2"
    
    dialog --clear --title "$(translate "Confirmation")" \
           --yesno "\n\n$(translate "Do you want to run the network script from") $name?" 10 70
    
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

declare -a PROXMENUX_SCRIPTS=(
    "Real-time network usage (iftop)||launch_iftop"
    "Network monitoring tool (iptraf-ng)||launch_iptraf"
    "Show Routing Table||show_routing_table"
    "Test Connectivity||test_connectivity"
    "Advanced Diagnostics||advanced_network_diagnostics"
    "Analyze Bridge Configuration||analyze_bridge_configuration"
    "Analyze Network Configuration||analyze_network_configuration"
    "Setup Persistent Network Names||setup_persistent_network"
    "Restart Network Service||restart_network_service"
    "Show Network Config File||show_network_config"
    "Create Network Backup||create_network_backup_manual"
    "Restore Network Backup||restore_network_backup"
)



declare -a COMMUNITY_SCRIPTS=(
    "Disable NIC Offloading (Intel e1000e)|Helper-Scripts|confirm_and_run \"Helper-Scripts\" \"bash <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/nic-offloading-fix.sh)\""
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
                                 --title "$(translate "Network Management")" \
                                 --menu "\n$(translate "Select a network management option:"):\n" \
                                 26 78 19 \
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
