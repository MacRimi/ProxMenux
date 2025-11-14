#!/bin/bash


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


CONFIG_FILE="/etc/proxmox-telegram.conf"
PID_DIR="/var/run/proxmox-telegram"
WRAPPER_PATH="/usr/local/bin/telegram-notifier-wrapper.sh"
t() { translate "$1"; }
declare -A IFACE_DOWN
declare -A IFACE_DOWN_TIME
disk_full_detected=false
disk_nearly_full_detected=false
inode_full_detected=false
cpu_usage_history=""
last_cpu_sustained_notification=0
last_swap_notification=0




# ==================================================
#  TELEGRAM
# ==================================================

# Create configuration file if it doesn't exist
if [[ ! -f "$CONFIG_FILE" ]]; then
    cat <<EOF > "$CONFIG_FILE"
BOT_TOKEN=""
CHAT_ID=""
vm_start=0
vm_shutdown=0
vm_restart=0
vm_fail=0
update_available=0
update_complete=0
system_shutdown=0
system_problem=0
system_load_high=0
kernel_panic=0
disk_fail=0
disk_full=0
disk_io_error=0
node_disconnect=0
split_brain=0
network_down=0
network_saturation=0
firewall_issue=0
backup_complete=0
backup_fail=0
snapshot_complete=0
snapshot_fail=0
auth_fail=0
ip_block=0
user_permission_change=0
cpu_high=0
ram_high=0
temp_high=0
low_disk_space=0
EOF
    chmod 600 "$CONFIG_FILE" 
fi

source "$CONFIG_FILE"


########################################################################


send_notification() {
    local message="$1"
    

    if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
        return 1
    fi
    

    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$message" > /dev/null 2>&1
}



#########################################################################



# Function to configure Telegram
configure_telegram() {

    [[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE"


    BOT_TOKEN=$(whiptail --title "$(translate "Telegram Configuration")" \
                         --inputbox "$(translate "Enter your Telegram Bot Token:")" 10 70 "$BOT_TOKEN" 3>&1 1>&2 2>&3)

    if [[ $? -ne 0 ]]; then
        return
    fi


    CHAT_ID=$(whiptail --title "$(translate "Telegram Configuration")" \
                       --inputbox "$(translate "Enter your Telegram Chat ID:")" 10 70 "$CHAT_ID" 3>&1 1>&2 2>&3)

    if [[ $? -ne 0 ]]; then
        return
    fi

    # Save configuration to file
    if [[ -n "$BOT_TOKEN" && -n "$CHAT_ID" ]]; then

        cp "$CONFIG_FILE" "${CONFIG_FILE}.bak" 2>/dev/null
        

        if grep -q "^BOT_TOKEN=" "$CONFIG_FILE"; then
            sed -i "s/^BOT_TOKEN=.*/BOT_TOKEN=\"$BOT_TOKEN\"/" "$CONFIG_FILE"
        else
            echo "BOT_TOKEN=\"$BOT_TOKEN\"" >> "$CONFIG_FILE"
        fi
        
        if grep -q "^CHAT_ID=" "$CONFIG_FILE"; then
            sed -i "s/^CHAT_ID=.*/CHAT_ID=\"$CHAT_ID\"/" "$CONFIG_FILE"
        else
            echo "CHAT_ID=\"$CHAT_ID\"" >> "$CONFIG_FILE"
        fi
        

        source "$CONFIG_FILE"
        
        # Test the configuration immediately
        response=$(curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=$(translate "Telegram is working correctly!")")

        if [[ "$response" =~ "ok\":true" ]]; then
            whiptail --title "$(translate "Success")" \
                     --msgbox "$(translate "Valid Telegram configuration. Notifications will be sent.")" 10 70
        else
            whiptail --title "$(translate "Error")" \
                     --msgbox "$(translate "Invalid Telegram configuration. Please verify the token and chat ID.")" 10 70
        fi
    else
        whiptail --title "$(translate "Error")" \
                 --msgbox "$(translate "Incomplete Telegram configuration. Please provide both token and chat ID.")" 10 70
    fi
}



# ==================================================





# ==================================================
# NOTIFICATION CONFIGURATION
# ==================================================



# Options for the menu
options=(
    "VM and Container|$(t 'VM/Container Start')|vm_start"
    "VM and Container|$(t 'VM/Container Shutdown')|vm_shutdown"
    "VM and Container|$(t 'VM/Container Restart')|vm_restart"
    "VM and Container|$(t 'VM/Container Start Failure')|vm_fail"
    "System|$(t 'New update available')|update_available"
    "System|$(t 'Update completed')|update_complete"
    "System|$(t 'System shutdown')|system_shutdown"
    "System|$(t 'System problem')|system_problem"
    "System|$(t 'High system load')|system_load_high"
    "Storage|$(t 'Disk failure')|disk_fail"
    "Storage|$(t 'Storage full')|disk_full"
    "Storage|$(t 'Read/Write issues')|disk_io_error"
    "Cluster|$(t 'Node disconnected')|node_disconnect"
    "Cluster|$(t 'Split-brain (quorum conflict)')|split_brain"
    "Network|$(t 'Network interface down')|network_down"
    "Network|$(t 'Network saturation')|network_saturation"
    "Network|$(t 'Firewall issue')|firewall_issue"
    "Backup and Snapshot|$(t 'Backup completed')|backup_complete"
    "Backup and Snapshot|$(t 'Backup failed')|backup_fail"
    "Backup and Snapshot|$(t 'Snapshot completed')|snapshot_complete"
    "Backup and Snapshot|$(t 'Snapshot failed')|snapshot_fail"
    "Security|$(t 'Failed authentication attempt')|auth_fail"
    "Security|$(t 'Automatic IP blocks')|ip_block"
    "Security|$(t 'User permission change')|user_permission_change"
    "Resources|$(t 'High CPU usage')|cpu_high"
    "Resources|$(t 'High RAM usage')|ram_high"
    "Resources|$(t 'High system temperature')|temp_high"
    "Resources|$(t 'Low disk space')|low_disk_space"
)






# Function to configure notifications
configure_notifications() {


    IFS=$'\n' sorted_options=($(for option in "${options[@]}"; do
        IFS='|' read -r category description var_name <<< "$option"
        printf "%s|%s|%s\n" "$category" "$description" "$var_name"
    done | sort -t'|' -k1,1 -k2,2))
    unset IFS


    declare -A index_to_var
    index=1


    menu_items=()
    for option in "${sorted_options[@]}"; do
        IFS='|' read -r category description var_name <<< "$option"


        index_to_var["$index"]="$var_name"
        

        formatted_item="$description"
        current_length=${#formatted_item}
        spaces_needed=$((50 - current_length))

        for ((j = 0; j < spaces_needed; j++)); do
            formatted_item+=" "
        done

        formatted_item+="$category"


        state="OFF"
        [[ "$(eval echo \$$var_name)" -eq 1 ]] && state="ON"

        menu_items+=("$index" "$formatted_item" "$state")
        ((index++))
    done

    # whiptail menu
    selected_indices=$(whiptail --backtitle "ProxMenuX" --title "$(translate "Telegram Notification Configuration")" \
                            --checklist --separate-output \
                            "\n$(translate "Select the events you want to receive:")\n" \
                            30 100 20 \
                            "${menu_items[@]}" \
                            3>&1 1>&2 2>&3)
    
    local result=$?


    if [[ $result -eq 0 ]]; then

        cp "$CONFIG_FILE" "${CONFIG_FILE}.bak" 2>/dev/null
        
        for var_name in "${index_to_var[@]}"; do
            sed -i "s/^$var_name=.*/$var_name=0/" "$CONFIG_FILE"
        done

        for selected_index in $selected_indices; do
            var_name="${index_to_var[$selected_index]}"
            sed -i "s/^$var_name=.*/$var_name=1/" "$CONFIG_FILE"
        done


        source "$CONFIG_FILE"

        whiptail --backtitle "ProxMenuX" --title "$(translate "Success")" \
                 --msgbox "$(translate "Configuration updated successfully.")" 10 70
    fi
}





# ==================================================




# Function to get VM/CT name from its ID
get_vm_name() {
    local vmid="$1"
    local name=""
    
    if [[ -f "/etc/pve/qemu-server/$vmid.conf" ]]; then
        name=$(grep -i "^name:" "/etc/pve/qemu-server/$vmid.conf" | cut -d ' ' -f2-)
    elif [[ -f "/etc/pve/lxc/$vmid.conf" ]]; then
        name=$(grep -i "^hostname:" "/etc/pve/lxc/$vmid.conf" | cut -d ' ' -f2-)
    fi
    

    if [[ -n "$name" ]]; then
        echo "$name ($vmid)"
    else
        echo "$vmid"
    fi
}


# ==================================================





# ==================================================
# NOTIFICATION EVENTS
# ==================================================




# Function: capture events from journalctl
capture_journal_events() {


    local processed_events_file="$PID_DIR/processed_events"
    

    mkdir -p "$PID_DIR" 2>/dev/null
    

    if [[ ! -f "$processed_events_file" ]]; then
        touch "$processed_events_file"
    fi
    

    while true; do

        # Use tail for Proxmox tasks file
        tail -F /var/log/pve/tasks/index 2>/dev/null | while read -r line; do

            event_id=$(echo "$line" | md5sum | cut -d' ' -f1)
            
            if grep -q "$event_id" "$processed_events_file" 2>/dev/null; then
                continue
            fi
            

            echo "$event_id" >> "$processed_events_file"
            
            tail -n 1000 "$processed_events_file" > "${processed_events_file}.tmp" 2>/dev/null && mv "${processed_events_file}.tmp" "$processed_events_file" 2>/dev/null
            
            local event_processed=false
            



            # ===== IMMEDIATE NOTIFICATION EVENTS =====
            
            # VM or CT start failure (CRITICAL)
            if [[ "$vm_fail" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # Detect VM errors
                if [[ "$line" =~ "Failed to start VM" || "$line" =~ "qmstart" && "$line" =~ "err" || "$line" =~ "qmstart" && "$line" =~ "fail" ]]; then
                    VM_ID=$(echo "$line" | grep -oP '(VM |qmstart:)\K[0-9]+')
                    NAME=$(get_vm_name "$VM_ID")
                    send_notification "🚨 $(translate "CRITICAL: Failed to start VM:") $NAME"
                    event_processed=true
                # Detect CT (LXC) errors
                elif [[ "$line" =~ "Failed to start CT" || "$line" =~ "lxc-start" && "$line" =~ "err" || "$line" =~ "lxc-start" && "$line" =~ "fail" ]]; then
                    CT_ID=$(echo "$line" | grep -oP '(CT |lxc-start:)\K[0-9]+')
                    NAME=$(get_vm_name "$CT_ID")
                    send_notification "🚨 $(translate "CRITICAL: Failed to start Container:") $NAME"
                    event_processed=true
                fi
            fi
            


            # Disk I/O errors (CRITICAL)
            if [[ "$disk_io_error" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                if [[ "$line" =~ "I/O error" || "$line" =~ "read error" || "$line" =~ "write error" || 
                    "$line" =~ "blk_update_request" || "$line" =~ "buffer I/O error" || 
                    "$line" =~ "medium error" || "$line" =~ "sense key: Medium Error" || 
                    "$line" =~ "ata.*failed command" || "$line" =~ "SCSI error" ]]; then
                    
                    # Extract device name with improved pattern matching
                    DISK=$(echo "$line" | grep -oE "/dev/[a-zA-Z0-9]+" || 
                        echo "$line" | grep -oE "sd[a-z][0-9]*" || 
                        echo "$line" | grep -oE "nvme[0-9]+n[0-9]+" || 
                        echo "unknown")
                    
                    # Try to extract error type
                    ERROR_TYPE="unknown"
                    if [[ "$line" =~ "read error" ]]; then
                        ERROR_TYPE="read"
                    elif [[ "$line" =~ "write error" ]]; then
                        ERROR_TYPE="write"
                    elif [[ "$line" =~ "medium error" || "$line" =~ "sense key: Medium Error" ]]; then
                        ERROR_TYPE="medium"
                    elif [[ "$line" =~ "timeout" ]]; then
                        ERROR_TYPE="timeout"
                    fi
                    
                    # Try to extract sector information if available
                    SECTOR=$(echo "$line" | grep -oP "sector [0-9]+" || echo "")
                    if [[ -n "$SECTOR" ]]; then
                        SECTOR=" ($SECTOR)"
                    fi
                    
                    # Send notification with enhanced information
                    send_notification "🚨 $(translate "CRITICAL: Disk ${ERROR_TYPE} error on:") $DISK$SECTOR"
                    
                    event_processed=true
                fi
            fi
            


            # Disk failure (CRITICAL)
            if [[ "$disk_fail" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                if [[ "$line" =~ "disk failure" || "$line" =~ "hard drive failure" || 
                    "$line" =~ "SMART error" || "$line" =~ "SMART failure" || 
                    "$line" =~ "SMART Status BAD" || "$line" =~ "failed SMART" || 
                    "$line" =~ "drive failure" || "$line" =~ "bad sectors" || 
                    "$line" =~ "sector reallocation" || "$line" =~ "uncorrectable error" || 
                    "$line" =~ "media error" || "$line" =~ "not responding" && "$line" =~ "disk" || 
                    "$line" =~ "SSD life critical" || "$line" =~ "SSD wear" && "$line" =~ "critical" ]]; then
                    
                    # Extract device name with improved pattern matching
                    DISK=$(echo "$line" | grep -oE "/dev/[a-zA-Z0-9]+" || 
                        echo "$line" | grep -oE "sd[a-z][0-9]*" || 
                        echo "$line" | grep -oE "nvme[0-9]+n[0-9]+" || 
                        echo "$line" | grep -oE "ata[0-9]+" || 
                        echo "unknown")
                    
                    # Try to determine failure type
                    FAILURE_TYPE="hardware"
                    if [[ "$line" =~ "SMART" ]]; then
                        FAILURE_TYPE="SMART"
                        
                        # Try to extract SMART attribute if available
                        SMART_ATTR=$(echo "$line" | grep -oP "Attribute \K[^:]*" || 
                                    echo "$line" | grep -oP "SMART attribute \K[^:]*" || 
                                    echo "")
                        if [[ -n "$SMART_ATTR" ]]; then
                            SMART_ATTR=" (Attribute: $SMART_ATTR)"
                        fi
                    elif [[ "$line" =~ "bad sectors" || "$line" =~ "sector reallocation" ]]; then
                        FAILURE_TYPE="bad sectors"
                    elif [[ "$line" =~ "SSD" ]]; then
                        FAILURE_TYPE="SSD wear"
                    elif [[ "$line" =~ "not responding" ]]; then
                        FAILURE_TYPE="unresponsive"
                    fi
                    
                    # Send notification with enhanced information
                    send_notification "🚨 $(translate "CRITICAL: Disk failure detected") ($FAILURE_TYPE): $DISK$SMART_ATTR"
                    
                    event_processed=true
                fi
            fi
            


            # Snapshot failed (CRITICAL)
            if [[ "$line" =~ "snapshot" ]] && [[ "$snapshot_fail" -eq 1 ]] && [[ "$line" =~ "error" || "$line" =~ "fail" || "$line" =~ "unable to" || "$line" =~ "cannot" ]] && [[ "$event_processed" = false ]]; then
               
                # Extract VM/CT ID
                VM_ID=$(echo "$line" | grep -oP 'TASK \K[0-9]+')
                if [[ -z "$VM_ID" ]]; then
                    VM_ID=$(echo "$line" | grep -oP 'VM \K[0-9]+')
                fi
                if [[ -z "$VM_ID" ]]; then
                    VM_ID=$(echo "$line" | grep -oP 'CT \K[0-9]+')
                fi

                # Extract snapshot ID
                SNAPSHOT_ID=$(echo "$line" | grep -oP 'snapshot \K[a-zA-Z0-9_-]+')
                if [[ -z "$SNAPSHOT_ID" ]]; then
                    SNAPSHOT_ID=$(echo "$line" | grep -oP 'snap\K[a-zA-Z0-9_-]+')
                fi

                
                # Try to determine error reason
                ERROR_REASON=""
                if [[ "$line" =~ "no space" || "$line" =~ "space exhausted" || "$line" =~ "out of space" ]]; then
                    ERROR_REASON=" (No space left)"
                elif [[ "$line" =~ "timeout" ]]; then
                    ERROR_REASON=" (Operation timed out)"
                elif [[ "$line" =~ "already exists" ]]; then
                    ERROR_REASON=" (Snapshot already exists)"
                elif [[ "$line" =~ "locked" || "$line" =~ "lock" ]]; then
                    ERROR_REASON=" (Resource locked)"
                elif [[ "$line" =~ "permission" ]]; then
                    ERROR_REASON=" (Permission denied)"
                elif [[ "$line" =~ "quorum" ]]; then
                    ERROR_REASON=" (Quorum error)"
                fi
                
                # Format the notification message
                if [[ -n "$VM_ID" ]]; then
                    NAME=$(get_vm_name "$VM_ID")
                    if [[ -n "$SNAPSHOT_ID" ]]; then
                        send_notification "🚨 $(translate "CRITICAL: Snapshot failed for:") $NAME (ID: $SNAPSHOT_ID)$ERROR_REASON"
                    else
                        send_notification "🚨 $(translate "CRITICAL: Snapshot failed for:") $NAME$ERROR_REASON"
                    fi
                else
                    if [[ -n "$SNAPSHOT_ID" ]]; then
                        send_notification "🚨 $(translate "CRITICAL: Snapshot failed") (ID: $SNAPSHOT_ID)$ERROR_REASON"
                    else
                        send_notification "🚨 $(translate "CRITICAL: Snapshot failed")$ERROR_REASON"
                    fi
                fi
                
                event_processed=true
            fi
            


            # Backup failed (CRITICAL)
            if [[ "$backup_fail" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # Expanded pattern matching for backup failures
                if [[ "$line" =~ "backup" && ("$line" =~ "error" || "$line" =~ "fail" || "$line" =~ "unable to" || "$line" =~ "cannot" || "$line" =~ "abort") ]]; then

                    # Extract VM/CT ID
                    VM_ID=$(echo "$line" | grep -oP 'TASK \K[0-9]+')
                    if [[ -z "$VM_ID" ]]; then
                        VM_ID=$(echo "$line" | grep -oP 'VM \K[0-9]+')
                    fi
                    if [[ -z "$VM_ID" ]]; then
                        VM_ID=$(echo "$line" | grep -oP 'CT \K[0-9]+')
                    fi

                    # Extract backup target
                    BACKUP_TARGET=$(echo "$line" | grep -oP 'to ["\047]?\K[a-zA-Z0-9_-]+')
                    if [[ -z "$BACKUP_TARGET" ]]; then
                        BACKUP_TARGET=$(echo "$line" | grep -oP 'storage ["\047]?\K[a-zA-Z0-9_-]+')
                    fi

                    
                    # Try to determine error reason
                    ERROR_REASON=""
                    if [[ "$line" =~ "no space" || "$line" =~ "space exhausted" || "$line" =~ "out of space" ]]; then
                        ERROR_REASON=" (No space left)"
                    elif [[ "$line" =~ "timeout" ]]; then
                        ERROR_REASON=" (Operation timed out)"
                    elif [[ "$line" =~ "connection" && "$line" =~ "refused" ]]; then
                        ERROR_REASON=" (Connection refused)"
                    elif [[ "$line" =~ "network" ]]; then
                        ERROR_REASON=" (Network error)"
                    elif [[ "$line" =~ "permission" ]]; then
                        ERROR_REASON=" (Permission denied)"
                    elif [[ "$line" =~ "locked" || "$line" =~ "lock" ]]; then
                        ERROR_REASON=" (Resource locked)"
                    elif [[ "$line" =~ "quorum" ]]; then
                        ERROR_REASON=" (Quorum error)"
                    elif [[ "$line" =~ "already running" ]]; then
                        ERROR_REASON=" (Another backup is already running)"
                    fi
                    
                    # Format the notification message
                    if [[ -n "$VM_ID" ]]; then
                        NAME=$(get_vm_name "$VM_ID")
                        if [[ -n "$BACKUP_TARGET" ]]; then
                            send_notification "🚨 $(translate "CRITICAL: Backup failed for:") $NAME (Target: $BACKUP_TARGET)$ERROR_REASON"
                        else
                            send_notification "🚨 $(translate "CRITICAL: Backup failed for:") $NAME$ERROR_REASON"
                        fi
                    else
                        if [[ -n "$BACKUP_TARGET" ]]; then
                            send_notification "🚨 $(translate "CRITICAL: Backup failed") (Target: $BACKUP_TARGET)$ERROR_REASON"
                        else
                            send_notification "🚨 $(translate "CRITICAL: Backup failed")$ERROR_REASON"
                        fi
                    fi
                    
                    event_processed=true
                fi
            fi


            
            # Failed authentication attempt (CRITICAL)
            if [[ "$auth_fail" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                if [[ "$line" =~ "authentication failure" || "$line" =~ "auth fail" || "$line" =~ "login failed" || 
                    "$line" =~ "Failed password" || "$line" =~ "Invalid user" || "$line" =~ "failed login" || 
                    "$line" =~ "authentication error" || ( "$line" =~ "unauthorized" && "$line" =~ "access" ) ]]; then
                    
                    # Extract username
                    USER=$(echo "$line" | grep -oP 'user=\K[^ ]+')
                    if [[ -z "$USER" ]]; then
                        USER=$(echo "$line" | grep -oP 'user \K[^ ]+')
                    fi
                    if [[ -z "$USER" ]]; then
                        USER=$(echo "$line" | grep -oP 'for user \K[^ ]+')
                    fi
                    if [[ -z "$USER" ]]; then
                        USER=$(echo "$line" | grep -oP 'for invalid user \K[^ ]+')
                    fi
                    if [[ -z "$USER" ]]; then
                        USER=$(echo "$line" | grep -oP 'for \K[^ ]+' | grep -v "invalid")
                    fi
                    if [[ -z "$USER" ]]; then
                        USER="unknown"
                    fi

                    # Extract IP address
                    IP=$(echo "$line" | grep -oP 'rhost=\K[^ ]+')
                    if [[ -z "$IP" ]]; then
                        IP=$(echo "$line" | grep -oP 'from \K[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')
                    fi
                    if [[ -z "$IP" ]]; then
                        IP=$(echo "$line" | grep -oP 'from \K[0-9a-f:]+')
                    fi
                    if [[ -z "$IP" ]]; then
                        IP=$(echo "$line" | grep -oP 'IP: \K[^ ]+')
                    fi
                    if [[ -z "$IP" ]]; then
                        IP="unknown"
                    fi

                    
                    # Try to determine authentication service
                    SERVICE="system"
                    if [[ "$line" =~ "sshd" ]]; then
                        SERVICE="SSH"
                    elif [[ "$line" =~ "pvedaemon" || "$line" =~ "pveproxy" ]]; then
                        SERVICE="Proxmox Web UI"
                    elif [[ "$line" =~ "nginx" || "$line" =~ "apache" ]]; then
                        SERVICE="Web Server"
                    elif [[ "$line" =~ "smtp" || "$line" =~ "mail" ]]; then
                        SERVICE="Mail"
                    elif [[ "$line" =~ "ftp" ]]; then
                        SERVICE="FTP"
                    fi
                    
                    # Try to extract authentication method if available
                    AUTH_METHOD=""
                    if [[ "$line" =~ "password" ]]; then
                        AUTH_METHOD=" (Password auth)"
                    elif [[ "$line" =~ "publickey" ]]; then
                        AUTH_METHOD=" (Public key auth)"
                    elif [[ "$line" =~ "keyboard-interactive" ]]; then
                        AUTH_METHOD=" (Interactive auth)"
                    elif [[ "$line" =~ "PAM" ]]; then
                        AUTH_METHOD=" (PAM auth)"
                    fi
                    
                    # Count failed attempts from this IP if possible
                    ATTEMPT_COUNT=""
                    if [[ -n "$IP" && "$IP" != "unknown" ]]; then
                        # Use journalctl to count recent failed attempts from this IP
                        if command -v journalctl &>/dev/null; then
                            COUNT=$(journalctl -q --since "1 hour ago" | grep -c "$IP")
                            if [[ $COUNT -gt 1 ]]; then
                                ATTEMPT_COUNT=" ($COUNT attempts in the last hour)"
                            fi
                        fi
                    fi
                    
                    # Send notification with enhanced information
                    send_notification "🚨 $(translate "CRITICAL: Failed authentication attempt:") $USER from $IP - $SERVICE$AUTH_METHOD$ATTEMPT_COUNT"
                    
                    event_processed=true
                fi
            fi
            


            # Firewall issue (CRITICAL)
            if [[ "$line" =~ "firewall" && "$firewall_issue" -eq 1 && 
                ( "$line" =~ "error" || "$line" =~ "block" || "$line" =~ "reject" || 
                    "$line" =~ "drop" || "$line" =~ "denied" || "$line" =~ "fail" || "$line" =~ "invalid" ) && 
                "$event_processed" = false ]]; then

                
                # Try to determine the type of firewall issue
                ISSUE_TYPE="issue"
                if [[ "$line" =~ "error" ]]; then
                    ISSUE_TYPE="configuration error"
                elif [[ "$line" =~ "block" || "$line" =~ "denied" ]]; then
                    ISSUE_TYPE="blocked connection"
                elif [[ "$line" =~ "reject" ]]; then
                    ISSUE_TYPE="rejected connection"
                elif [[ "$line" =~ "drop" ]]; then
                    ISSUE_TYPE="dropped packet"
                elif [[ "$line" =~ "invalid" ]]; then
                    ISSUE_TYPE="invalid rule"
                fi
                
                # Extract source IP
                SRC_IP=$(echo "$line" | grep -oP 'SRC=\K[0-9.]+')
                if [[ -z "$SRC_IP" ]]; then
                    SRC_IP=$(echo "$line" | grep -oP 'from \K[0-9.]+')
                fi
                if [[ -z "$SRC_IP" ]]; then
                    SRC_IP=$(echo "$line" | grep -oP 'source \K[0-9.]+')
                fi

                # Extract destination IP
                DST_IP=$(echo "$line" | grep -oP 'DST=\K[0-9.]+')
                if [[ -z "$DST_IP" ]]; then
                    DST_IP=$(echo "$line" | grep -oP 'to \K[0-9.]+')
                fi
                if [[ -z "$DST_IP" ]]; then
                    DST_IP=$(echo "$line" | grep -oP 'destination \K[0-9.]+')
                fi

                
                # Try to extract port information if available
                PORT_INFO=""
                SRC_PORT=$(echo "$line" | grep -oP 'SPT=\K[0-9]+' || echo "")
                DST_PORT=$(echo "$line" | grep -oP 'DPT=\K[0-9]+' || echo "")
                if [[ -n "$SRC_PORT" && -n "$DST_PORT" ]]; then
                    PORT_INFO=" (Port $SRC_PORT → $DST_PORT)"
                elif [[ -n "$DST_PORT" ]]; then
                    PORT_INFO=" (Port $DST_PORT)"
                fi
                
                # Try to extract protocol if available
                PROTO=$(echo "$line" | grep -oP 'PROTO=\K[A-Za-z]+' || 
                        echo "$line" | grep -oP 'protocol \K[A-Za-z]+' || echo "")
                if [[ -n "$PROTO" ]]; then
                    PROTO=" $PROTO"
                fi
                
                # Try to extract interface if available
                IFACE=$(echo "$line" | grep -oP 'IN=\K[^ ]+' || 
                        echo "$line" | grep -oP 'OUT=\K[^ ]+' || 
                        echo "$line" | grep -oP 'on \K[^ ]+' || echo "")
                if [[ -n "$IFACE" ]]; then
                    IFACE=" on $IFACE"
                fi
                
                # Format the notification message
                if [[ -n "$SRC_IP" && -n "$DST_IP" ]]; then
                    send_notification "🚨 $(translate "CRITICAL: Firewall ${ISSUE_TYPE}:") $SRC_IP → $DST_IP$PORT_INFO$PROTO$IFACE"
                elif [[ -n "$SRC_IP" ]]; then
                    send_notification "🚨 $(translate "CRITICAL: Firewall ${ISSUE_TYPE}:") from $SRC_IP$PORT_INFO$PROTO$IFACE"
                elif [[ -n "$DST_IP" ]]; then
                    send_notification "🚨 $(translate "CRITICAL: Firewall ${ISSUE_TYPE}:") to $DST_IP$PORT_INFO$PROTO$IFACE"
                else
                    # Extract a more concise message from the line
                    CONCISE_MSG=$(echo "$line" | sed -E 's/.*firewall[^:]*: ?//i' | cut -c 1-100)
                    send_notification "🚨 $(translate "CRITICAL: Firewall ${ISSUE_TYPE}:") $CONCISE_MSG"
                fi
                
                event_processed=true
            fi
            



            # Network interface recovery handler
            if [[ "$network_down" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                if [[ "$line" =~ (eth[0-9]+|eno[0-9]+|enp[0-9]+s[0-9]+|wlan[0-9]+) ]]; then
                    IFACE="${BASH_REMATCH[1]}"
                    
                    # Detect interface going down
                    if [[ "$line" =~ "link down" || "$line" =~ "disconnected" || "$line" =~ "no carrier" || "$line" =~ "failure" ]]; then
                        # Mark interface as down and store the timestamp
                        IFACE_DOWN["$IFACE"]=true
                        IFACE_DOWN_TIME["$IFACE"]="$(date +%s)"
                    fi

                    # Detect interface recovery
                    if [[ "$line" =~ "link up" || "$line" =~ "activated" ]]; then
                        if [[ "${IFACE_DOWN[$IFACE]}" == true ]]; then
                            RESTORE_TIME=$(date +%s)
                            START_TIME=${IFACE_DOWN_TIME[$IFACE]}
                            DURATION=$((RESTORE_TIME - START_TIME))

                            # Check if this is the default route interface
                            PRIMARY=""
                            if ip route | grep -q "default.*$IFACE"; then
                                PRIMARY=" (PRIMARY INTERFACE)"
                            fi

                            # Send notification after connection is restored
                            send_notification "$(translate '✅ Network connection was lost and has been restored on') $IFACE$PRIMARY. $(translate 'Downtime duration'): ${DURATION}s"

                            # Clean up the interface state
                            unset IFACE_DOWN["$IFACE"]
                            unset IFACE_DOWN_TIME["$IFACE"]
                            event_processed=true
                        fi
                    fi
                fi
            fi



            
            # Split-brain detected (CRITICAL)
            if [[ "$split_brain" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # Expanded pattern matching for split-brain detection
                if [[ "$line" =~ "Split-Brain" || "$line" =~ "split brain" || "$line" =~ "split-brain" || 
                    ( "$line" =~ "fencing" && "$line" =~ "required" ) || 
                    ( "$line" =~ "cluster" && "$line" =~ "partition" ) ]]; then

                    
                    NODES=$(echo "$line" | grep -oP 'nodes: \K[^.]+')
                    if [[ -z "$NODES" ]]; then
                        NODES=$(echo "$line" | grep -oP 'between \K[^.]+')
                    fi
                    if [[ -n "$NODES" ]]; then
                        NODES=" (Affected nodes: $NODES)"
                    fi

                    # Try to extract fence status if available
                    FENCE_INFO=""
                    if [[ "$line" =~ "fencing" ]]; then
                        if [[ "$line" =~ "successful" ]]; then
                            FENCE_INFO=" (Fencing successful)"
                        elif [[ "$line" =~ "failed" ]]; then
                            FENCE_INFO=" (Fencing failed)"
                        else
                            FENCE_INFO=" (Fencing required)"
                        fi
                    fi
                    
                    # Send notification with enhanced information
                    send_notification "🚨 $(translate "CRITICAL: Split-brain detected in cluster")$NODES$FENCE_INFO - $(translate "Manual intervention required!")"
                    
                    event_processed=true
                fi
            fi



            # Node disconnected from cluster (CRITICAL)
            if [[ "$node_disconnect" -eq 1 ]] && [[ "$event_processed" = false ]]; then

                # Expanded pattern matching for node disconnection
                if [[ ( "$line" =~ "quorum" && "$line" =~ "lost" ) || 
                    ( "$line" =~ "node" && "$line" =~ "left" ) || 
                    ( "$line" =~ "node" && "$line" =~ "offline" ) || 
                    ( "$line" =~ "connection" && "$line" =~ "lost" && "$line" =~ "node" ) ]]; then

                    
                    # Extract node name with improved pattern matching
                    NODE=$(echo "$line" | grep -oP 'node \K[^ ,.]+')
                    if [[ -z "$NODE" ]]; then
                        NODE=$(echo "$line" | grep -oP 'Node \K[^ ,.]+')
                    fi
                    if [[ -z "$NODE" ]]; then
                        NODE=$(echo "$line" | grep -oP 'from \K[^ ,.]+')
                    fi
                    if [[ -z "$NODE" ]]; then
                        NODE="unknown"
                    fi

                    
                    # Try to determine if quorum is still valid
                    QUORUM_STATUS=""
                    if [[ "$line" =~ "quorum" ]]; then
                        if [[ "$line" =~ "lost" ]]; then
                            QUORUM_STATUS=" (Quorum lost)"
                        elif [[ "$line" =~ "still" && "$line" =~ "valid" ]]; then
                            QUORUM_STATUS=" (Quorum still valid)"
                        fi
                    fi
                    
                    # Try to extract remaining nodes count if available
                    REMAINING_COUNT=$(echo "$line" | grep -oP 'remaining nodes: \K[0-9]+')
                    if [[ -z "$REMAINING_COUNT" ]]; then
                        REMAINING_COUNT=$(echo "$line" | grep -oP 'nodes left: \K[0-9]+')
                    fi
                    if [[ -n "$REMAINING_COUNT" ]]; then
                        REMAINING=" ($REMAINING_COUNT nodes remaining)"
                    fi

                    
                    # Try to determine if this is expected or unexpected
                    EXPECTED=""
                    if [[ "$line" =~ "shutdown" || "$line" =~ "maintenance" ]]; then
                        EXPECTED=" (Planned)"
                    else
                        EXPECTED=" (Unexpected)"
                    fi
                    
                    # Send notification with enhanced information
                    send_notification "🚨 $(translate "CRITICAL: Node disconnected from cluster:") $NODE$QUORUM_STATUS$REMAINING$EXPECTED"
                    
                    event_processed=true
                fi
            fi




            # System shutdown (NON-CRITICAL - with interval)
            if [[ "$system_shutdown" -eq 1 ]] && (( current_time - last_shutdown_notification > resource_interval )); then
                if [[ "$line" =~ "systemd-journald" && "$line" =~ "Journal stopped" ]]; then
                    
                    # No hay razón específica, pero podemos indicar que se detuvo el journal (lo último antes del apagado)
                    send_notification "⚠️ $(translate "System is shutting down")"
                    last_shutdown_notification=$current_time

                    # Log the event
                    logger -t proxmox-notify "System is shutting down (journal stopped)"
                    
                    event_processed=true
                fi
            fi



            # System problem (CRITICAL)
            if [[ "$system_problem" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                if [[ "$line" =~ "kernel panic" || "$line" =~ "segfault" || "$line" =~ "Out of memory" || 
                    "$line" =~ "BUG:" || "$line" =~ "Call Trace:" || 
                    "$line" =~ "Failed to start" || "$line" =~ "Unit .* failed" || 
                    "$line" =~ "Service .* exited with" ]]; then
                    
                    # Extract possible service name or component if available
                    COMPONENT=$(echo "$line" | grep -oP 'Failed to start \K[^:]+' || 
                                echo "$line" | grep -oP 'Unit \K[^ ]+' || 
                                echo "$line" | grep -oP 'Service \K[^ ]+' || echo "unknown")

                    # Format and send the notification
                    send_notification "🚨 $(translate "CRITICAL: System problem detected") ($COMPONENT)"
                    logger -t proxmox-notify "CRITICAL: System problem detected ($COMPONENT)"

                    event_processed=true
                fi
            fi



            # User permission change (NON-CRITICAL - with interval)
            if [[ "$user_permission_change" -eq 1 ]] && (( current_time - last_user_permission_notification > resource_interval )); then
                if [[ "$line" =~ "set permissions" || "$line" =~ "user added to group" || "$line" =~ "user removed from group" || 
                    "$line" =~ "ACL updated" || "$line" =~ "Role assigned" || "$line" =~ "Changed user permissions" ]]; then
                    
                    # Try to extract username
                    USER=$(echo "$line" | grep -oP 'user \K[^ ]+' || 
                        echo "$line" | grep -oP 'for user \K[^ ]+' || 
                        echo "$line" | grep -oP 'User \K[^ ]+' || echo "unknown")

                    # Try to detect change type
                    ACTION="Permission change"
                    if [[ "$line" =~ "added to group" ]]; then
                        ACTION="Added to group"
                    elif [[ "$line" =~ "removed from group" ]]; then
                        ACTION="Removed from group"
                    elif [[ "$line" =~ "Role assigned" ]]; then
                        ACTION="Role assigned"
                    elif [[ "$line" =~ "ACL updated" ]]; then
                        ACTION="ACL updated"
                    fi

                    send_notification "🔐 $(translate "User permission changed:") $USER ($ACTION)"
                    logger -t proxmox-notify "User permission changed: $USER ($ACTION)"
                    last_user_permission_notification=$current_time
                    event_processed=true
                fi
            fi



            # Network saturation (NON-CRITICAL - with interval)
            if [[ "$network_saturation" -eq 1 ]] && (( current_time - last_network_saturation_notification > resource_interval )); then
                if command -v ip &>/dev/null; then
                    saturated_ifaces=""
                    
                    # Loop over interfaces and look for rx/tx errors/drops
                    while read -r line; do
                        iface=$(echo "$line" | awk -F: '{print $2}' | xargs)
                        stats=$(ip -s link show "$iface" | awk '/RX:|TX:/ {getline; print}')
                        
                        rx_errors=$(echo "$stats" | awk 'NR==1 {print $3}')
                        tx_errors=$(echo "$stats" | awk 'NR==2 {print $3}')
                        rx_dropped=$(echo "$stats" | awk 'NR==1 {print $4}')
                        tx_dropped=$(echo "$stats" | awk 'NR==2 {print $4}')
                        
                        if (( rx_errors > 100 || tx_errors > 100 || rx_dropped > 100 || tx_dropped > 100 )); then
                            saturated_ifaces+="$iface (RX errors: $rx_errors, TX errors: $tx_errors, RX dropped: $rx_dropped, TX dropped: $tx_dropped), "
                        fi
                    done < <(ip -o link show | awk -F': ' '{print $2}')

                    # Clean and notify
                    if [[ -n "$saturated_ifaces" ]]; then
                        saturated_ifaces="${saturated_ifaces%, }"
                        send_notification "⚠️ $(translate "WARNING: Network saturation or errors detected on:") $saturated_ifaces"
                        logger -t proxmox-notify "WARNING: Network saturation on: $saturated_ifaces"
                        last_network_saturation_notification=$current_time
                    fi
                fi
            fi



            # Automatic IP blocks (NON-CRITICAL - with interval)
            if [[ "$ip_block" -eq 1 ]] && (( current_time - last_ip_block_notification > resource_interval )); then
                if [[ "$line" =~ "fail2ban" || "$line" =~ "Banned IP" || "$line" =~ "Blocking IP" || 
                    "$line" =~ "DROP" && "$line" =~ "SRC=" || 
                    "$line" =~ "REJECT" && "$line" =~ "SRC=" ]]; then
                    
                    # Try to extract IP address
                    IP=$(echo "$line" | grep -oP 'SRC=\K[0-9.]+' || 
                        echo "$line" | grep -oP 'from \K[0-9.]+' || 
                        echo "$line" | grep -oP 'Banned IP \K[0-9.]+' || 
                        echo "$line" | grep -oP 'Blocking IP \K[0-9.]+' || echo "unknown")

                    # Detect source (Fail2ban, Firewall, etc.)
                    SOURCE="Firewall"
                    if [[ "$line" =~ "fail2ban" ]]; then
                        SOURCE="Fail2ban"
                    elif [[ "$line" =~ "pve-firewall" ]]; then
                        SOURCE="PVE Firewall"
                    fi

                    send_notification "🔒 $(translate "Automatic IP block detected") ($IP - $SOURCE)"
                    logger -t proxmox-notify "IP block detected: $IP ($SOURCE)"
                    last_ip_block_notification=$current_time
                    event_processed=true
                fi
            fi

            
            
            # ===== NON-CRITICAL EVENTS (IMMEDIATE) =====
            
            # VM/CT start (NON-CRITICAL but immediate)
            if [[ "$vm_start" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # VM start detection
                if [[ "$line" =~ "qmstart" && ! "$line" =~ "err" && ! "$line" =~ "fail" ]]; then
                    VM_ID=$(echo "$line" | grep -oP 'qmstart:\K[0-9]+' || 
                            echo "$line" | grep -oP 'VM \K[0-9]+' || echo "")
                    
                    if [[ -n "$VM_ID" ]]; then
                        NAME=$(get_vm_name "$VM_ID")
                        
                        # Try to extract additional information
                        EXTRA_INFO=""
                        
                        # Check if this is a template
                        if [[ "$line" =~ "template" ]]; then
                            EXTRA_INFO=" (Template)"
                        fi
                        
                        # Check if this is a restore or clone operation
                        if [[ "$line" =~ "restore" ]]; then
                            EXTRA_INFO=" (Restored)"
                        elif [[ "$line" =~ "clone" ]]; then
                            EXTRA_INFO=" (Cloned)"
                        fi
                        
                        send_notification "✅ $(translate "VM started successfully:") $NAME$EXTRA_INFO"
                        event_processed=true
                    fi
                # LXC container start detection
                elif [[ "$line" =~ "lxc-start" && ! "$line" =~ "err" && ! "$line" =~ "fail" ]] || 
                    [[ "$line" =~ "Starting CT" && ! "$line" =~ "err" && ! "$line" =~ "fail" ]]; then
                    
                    CT_ID=$(echo "$line" | grep -oP 'lxc-start:\K[0-9]+' || 
                            echo "$line" | grep -oP 'CT \K[0-9]+' || echo "")
                    
                    if [[ -n "$CT_ID" ]]; then
                        NAME=$(get_vm_name "$CT_ID")
                        
                        # Try to extract additional information
                        EXTRA_INFO=""
                        
                        # Check if this is a template
                        if [[ "$line" =~ "template" ]]; then
                            EXTRA_INFO=" (Template)"
                        fi
                        
                        # Check if this is a restore or clone operation
                        if [[ "$line" =~ "restore" ]]; then
                            EXTRA_INFO=" (Restored)"
                        elif [[ "$line" =~ "clone" ]]; then
                            EXTRA_INFO=" (Cloned)"
                        fi
                        
                        send_notification "✅ $(translate "Container started successfully:") $NAME$EXTRA_INFO"
                        event_processed=true
                    fi
                fi
            fi


            
            # VM/CT shutdown (NON-CRITICAL but immediate)
            if [[ "$vm_shutdown" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # VM shutdown detection
                if [[ "$line" =~ "qmstop" && ! "$line" =~ "err" && ! "$line" =~ "fail" ]]; then
                    VM_ID=$(echo "$line" | grep -oP 'qmstop:\K[0-9]+' || 
                            echo "$line" | grep -oP 'VM \K[0-9]+' || echo "")
                    
                    if [[ -n "$VM_ID" ]]; then
                        NAME=$(get_vm_name "$VM_ID")
                        
                        # Try to determine shutdown type
                        SHUTDOWN_TYPE=""
                        if [[ "$line" =~ "force" || "$line" =~ "kill" ]]; then
                            SHUTDOWN_TYPE=" (Forced)"
                        elif [[ "$line" =~ "suspend" ]]; then
                            SHUTDOWN_TYPE=" (Suspended)"
                        elif [[ "$line" =~ "hibernate" ]]; then
                            SHUTDOWN_TYPE=" (Hibernated)"
                        elif [[ "$line" =~ "timeout" ]]; then
                            SHUTDOWN_TYPE=" (Timeout)"
                        elif [[ "$line" =~ "acpi" ]]; then
                            SHUTDOWN_TYPE=" (ACPI shutdown)"
                        fi
                        
                        send_notification "✅ $(translate "VM stopped successfully:") $NAME$SHUTDOWN_TYPE"
                        event_processed=true
                    fi
                # LXC container shutdown detection
                elif [[ "$line" =~ "lxc-stop" && ! "$line" =~ "err" && ! "$line" =~ "fail" ]] || 
                    [[ "$line" =~ "Stopping CT" && ! "$line" =~ "err" && ! "$line" =~ "fail" ]]; then
                    
                    CT_ID=$(echo "$line" | grep -oP 'lxc-stop:\K[0-9]+' || 
                            echo "$line" | grep -oP 'CT \K[0-9]+' || echo "")
                    
                    if [[ -n "$CT_ID" ]]; then
                        NAME=$(get_vm_name "$CT_ID")
                        
                        # Try to determine shutdown type
                        SHUTDOWN_TYPE=""
                        if [[ "$line" =~ "force" || "$line" =~ "kill" ]]; then
                            SHUTDOWN_TYPE=" (Forced)"
                        elif [[ "$line" =~ "timeout" ]]; then
                            SHUTDOWN_TYPE=" (Timeout)"
                        fi
                        
                        send_notification "✅ $(translate "Container stopped successfully:") $NAME$SHUTDOWN_TYPE"
                        event_processed=true
                    fi
                fi
            fi


            
            # VM/CT restart (NON-CRITICAL but immediate)
            if [[ "$vm_restart" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # VM restart detection
                if [[ ("$line" =~ "qmreset" || "$line" =~ "qmreboot") && ! "$line" =~ "err" && ! "$line" =~ "fail" ]]; then
                    VM_ID=$(echo "$line" | grep -oP '(qmreset|qmreboot):\K[0-9]+' || 
                            echo "$line" | grep -oP 'VM \K[0-9]+' || echo "")
                    
                    if [[ -n "$VM_ID" ]]; then
                        NAME=$(get_vm_name "$VM_ID")
                        
                        # Try to determine restart type
                        RESTART_TYPE=""
                        if [[ "$line" =~ "qmreset" ]]; then
                            RESTART_TYPE=" (Hard reset)"
                        elif [[ "$line" =~ "force" || "$line" =~ "kill" ]]; then
                            RESTART_TYPE=" (Forced)"
                        elif [[ "$line" =~ "timeout" ]]; then
                            RESTART_TYPE=" (After timeout)"
                        elif [[ "$line" =~ "acpi" ]]; then
                            RESTART_TYPE=" (ACPI restart)"
                        fi
                        
                        send_notification "✅ $(translate "VM restarted successfully:") $NAME$RESTART_TYPE"
                        event_processed=true
                    fi
                # LXC container restart detection
                elif [[ "$line" =~ "lxc-restart" || "$line" =~ "Restarting CT" || 
                        ("$line" =~ "lxc-stop" && "$line" =~ "lxc-start" && "$line" =~ "restart") ]] && 
                    [[ ! "$line" =~ "err" && ! "$line" =~ "fail" ]]; then
                    
                    CT_ID=$(echo "$line" | grep -oP 'lxc-restart:\K[0-9]+' || 
                            echo "$line" | grep -oP 'CT \K[0-9]+' || 
                            echo "$line" | grep -oP 'lxc-(stop|start):\K[0-9]+' || echo "")
                    
                    if [[ -n "$CT_ID" ]]; then
                        NAME=$(get_vm_name "$CT_ID")
                        
                        # Try to determine restart type
                        RESTART_TYPE=""
                        if [[ "$line" =~ "force" || "$line" =~ "kill" ]]; then
                            RESTART_TYPE=" (Forced)"
                        elif [[ "$line" =~ "timeout" ]]; then
                            RESTART_TYPE=" (After timeout)"
                        fi
                        
                        send_notification "✅ $(translate "Container restarted successfully:") $NAME$RESTART_TYPE"
                        event_processed=true
                    fi
                fi
            fi


            
            # Snapshot completed (NON-CRITICAL but immediate)
            if [[ "$line" =~ "snapshot" ]] && [[ "$snapshot_complete" -eq 1 ]] && [[ ! "$line" =~ "error" ]] && [[ "$event_processed" = false ]]; then

                # Additional pattern matching for completed snapshots
                if [[ "$line" =~ "complete" || "$line" =~ "finished" || "$line" =~ "success" || ! "$line" =~ "fail" && ! "$line" =~ "unable" ]]; then
                    
                    # Extract VM/CT ID with improved pattern matching
                    VM_ID=$(echo "$line" | grep -oP 'TASK \K[0-9]+')
                    if [[ -z "$VM_ID" ]]; then
                        VM_ID=$(echo "$line" | grep -oP 'VM \K[0-9]+')
                    fi
                    if [[ -z "$VM_ID" ]]; then
                        VM_ID=$(echo "$line" | grep -oP 'CT \K[0-9]+')
                    fi

                    
                    # Try to extract snapshot name/ID if available
                    SNAPSHOT_NAME=$(echo "$line" | grep -oP 'snapshot \K[a-zA-Z0-9_-]+' || 
                                    echo "$line" | grep -oP 'snap\K[a-zA-Z0-9_-]+' || 
                                    echo "$line" | grep -oP 'name: \K[a-zA-Z0-9_-]+' || echo "")
                    
                    # Try to extract snapshot size if available
                    SNAPSHOT_SIZE=$(echo "$line" | grep -oP 'size: \K[0-9.]+[KMGT]B' || 
                                    echo "$line" | grep -oP '[0-9.]+[KMGT]B' || echo "")
                    
                    # Try to extract duration if available
                    DURATION=$(echo "$line" | grep -oP 'duration: \K[0-9.]+s' || 
                            echo "$line" | grep -oP 'in \K[0-9.]+s' || 
                            echo "$line" | grep -oP 'took \K[0-9.]+s' || echo "")
                    
                    # Format additional information
                    ADDITIONAL_INFO=""
                    if [[ -n "$SNAPSHOT_NAME" ]]; then
                        ADDITIONAL_INFO+=" (Name: $SNAPSHOT_NAME"
                        
                        if [[ -n "$SNAPSHOT_SIZE" ]]; then
                            ADDITIONAL_INFO+=", Size: $SNAPSHOT_SIZE"
                        fi
                        
                        if [[ -n "$DURATION" ]]; then
                            ADDITIONAL_INFO+=", Duration: $DURATION"
                        fi
                        
                        ADDITIONAL_INFO+=")"
                    elif [[ -n "$SNAPSHOT_SIZE" || -n "$DURATION" ]]; then
                        ADDITIONAL_INFO+=" ("
                        
                        if [[ -n "$SNAPSHOT_SIZE" ]]; then
                            ADDITIONAL_INFO+="Size: $SNAPSHOT_SIZE"
                            
                            if [[ -n "$DURATION" ]]; then
                                ADDITIONAL_INFO+=", "
                            fi
                        fi
                        
                        if [[ -n "$DURATION" ]]; then
                            ADDITIONAL_INFO+="Duration: $DURATION"
                        fi
                        
                        ADDITIONAL_INFO+=")"
                    fi
                    
                    # Try to determine snapshot type
                    SNAPSHOT_TYPE=""
                    if [[ "$line" =~ "memory" || "$line" =~ "ram" ]]; then
                        SNAPSHOT_TYPE=" (With RAM)"
                    elif [[ "$line" =~ "disk-only" ]]; then
                        SNAPSHOT_TYPE=" (Disk only)"
                    fi
                    
                    # Format the notification message
                    if [[ -n "$VM_ID" ]]; then
                        NAME=$(get_vm_name "$VM_ID")
                        send_notification "✅ $(translate "Snapshot completed for:") $NAME$ADDITIONAL_INFO$SNAPSHOT_TYPE"
                    else
                        send_notification "✅ $(translate "Snapshot completed")$ADDITIONAL_INFO$SNAPSHOT_TYPE"
                    fi
                    
                    event_processed=true
                fi
            fi
            


            # Backup completed (NON-CRITICAL but immediate)
            if [[ "$line" =~ "backup" && "$backup_complete" -eq 1 &&
                ( "$line" =~ "successful" || "$line" =~ "complete" || "$line" =~ "finished" || "$line" =~ "success" ) &&
                ! "$line" =~ "error" && ! "$line" =~ "fail" &&
                "$event_processed" = false ]]; then

                # Extract VM/CT ID
                VM_ID=$(echo "$line" | grep -oP 'TASK \K[0-9]+')
                if [[ -z "$VM_ID" ]]; then
                    VM_ID=$(echo "$line" | grep -oP 'VM \K[0-9]+')
                fi
                if [[ -z "$VM_ID" ]]; then
                    VM_ID=$(echo "$line" | grep -oP 'CT \K[0-9]+')
                fi

                # Extract backup target
                BACKUP_TARGET=$(echo "$line" | grep -oP 'to ["\047]?\K[a-zA-Z0-9_-]+')
                if [[ -z "$BACKUP_TARGET" ]]; then
                    BACKUP_TARGET=$(echo "$line" | grep -oP 'storage ["\047]?\K[a-zA-Z0-9_-]+')
                fi
                if [[ -z "$BACKUP_TARGET" ]]; then
                    BACKUP_TARGET=$(echo "$line" | grep -oP 'target ["\047]?\K[a-zA-Z0-9_-]+')
                fi

                
                # Try to extract backup size if available
                BACKUP_SIZE=$(echo "$line" | grep -oP 'size: \K[0-9.]+[KMGT]B' || 
                            echo "$line" | grep -oP '[0-9.]+[KMGT]B' || echo "")
                
                # Try to extract duration if available
                DURATION=$(echo "$line" | grep -oP 'duration: \K[0-9.]+s' || 
                        echo "$line" | grep -oP 'in \K[0-9.]+s' || 
                        echo "$line" | grep -oP 'took \K[0-9.]+s' || echo "")
                
                # Try to extract compression rate if available
                COMPRESSION=$(echo "$line" | grep -oP 'compression: \K[0-9.]+%' || 
                            echo "$line" | grep -oP 'compressed: \K[0-9.]+%' || echo "")
                
                # Format additional information
                ADDITIONAL_INFO=""
                if [[ -n "$BACKUP_TARGET" || -n "$BACKUP_SIZE" || -n "$DURATION" || -n "$COMPRESSION" ]]; then
                    ADDITIONAL_INFO+=" ("
                    
                    if [[ -n "$BACKUP_TARGET" ]]; then
                        ADDITIONAL_INFO+="Target: $BACKUP_TARGET"
                        
                        if [[ -n "$BACKUP_SIZE" || -n "$DURATION" || -n "$COMPRESSION" ]]; then
                            ADDITIONAL_INFO+=", "
                        fi
                    fi
                    
                    if [[ -n "$BACKUP_SIZE" ]]; then
                        ADDITIONAL_INFO+="Size: $BACKUP_SIZE"
                        
                        if [[ -n "$DURATION" || -n "$COMPRESSION" ]]; then
                            ADDITIONAL_INFO+=", "
                        fi
                    fi
                    
                    if [[ -n "$DURATION" ]]; then
                        ADDITIONAL_INFO+="Duration: $DURATION"
                        
                        if [[ -n "$COMPRESSION" ]]; then
                            ADDITIONAL_INFO+=", "
                        fi
                    fi
                    
                    if [[ -n "$COMPRESSION" ]]; then
                        ADDITIONAL_INFO+="Compression: $COMPRESSION"
                    fi
                    
                    ADDITIONAL_INFO+=")"
                fi
                
                # Try to determine backup type
                BACKUP_TYPE=""
                if [[ "$line" =~ "incremental" ]]; then
                    BACKUP_TYPE=" (Incremental)"
                elif [[ "$line" =~ "differential" ]]; then
                    BACKUP_TYPE=" (Differential)"
                elif [[ "$line" =~ "full" ]]; then
                    BACKUP_TYPE=" (Full)"
                fi
                
                # Format the notification message
                if [[ -n "$VM_ID" ]]; then
                    NAME=$(get_vm_name "$VM_ID")
                    send_notification "✅ $(translate "Backup completed for:") $NAME$ADDITIONAL_INFO$BACKUP_TYPE"
                else
                    send_notification "✅ $(translate "Backup completed")$ADDITIONAL_INFO$BACKUP_TYPE"
                fi
                
                event_processed=true
            fi



            # System update completed (NON-CRITICAL but immediate)
            if [[ "$update_complete" -eq 1 ]] && [[ "$event_processed" = false ]]; then
                # Match various patterns that indicate a completed update
                if [[ "$line" =~ "update" && ("$line" =~ "complete" || "$line" =~ "finished" || "$line" =~ "done" || "$line" =~ "success") && 
                    ! "$line" =~ "error" && ! "$line" =~ "fail" && ! "$line" =~ "unable" ]]; then
                    
                    # Try to determine what was updated
                    update_type="system"
                    if [[ "$line" =~ "proxmox" || "$line" =~ "pve" ]]; then
                        update_type="Proxmox VE"
                    elif [[ "$line" =~ "kernel" ]]; then
                        update_type="kernel"
                    elif [[ "$line" =~ "package" ]]; then
                        update_type="package"
                    fi
                    
                    # Try to extract version information if available
                    version_info=""
                    if [[ "$line" =~ "version" ]]; then
                        version=$(echo "$line" | grep -oP 'version \K[0-9.]+' || 
                                echo "$line" | grep -oP 'to \K[0-9.]+' || echo "")
                        if [[ -n "$version" ]]; then
                            version_info=" ($(translate "version") $version)"
                        fi
                    fi
                    
                    # Try to extract package count if available
                    package_count=""
                    if [[ "$line" =~ "package" ]]; then
                        count=$(echo "$line" | grep -oP '([0-9]+) package' || echo "")
                        if [[ -n "$count" ]]; then
                            package_count=" ($count $(translate "packages"))"
                        fi
                    fi
                    
                    # Try to get a list of updated packages if available
                    package_list=""
                    if [[ -f /var/log/apt/history.log ]]; then
                        # Get the most recent upgrade entry
                        recent_upgrade=$(tac /var/log/apt/history.log | grep -m 1 -A 20 "Upgrade:" | grep -v "End-Date:" | grep "Upgrade:")
                        if [[ -n "$recent_upgrade" ]]; then
                            # Extract package names and versions
                            packages=$(echo "$recent_upgrade" | grep -oP '[a-zA-Z0-9.-]+:[a-zA-Z0-9]+ $$[^)]+$$' | head -n 5)
                            if [[ -n "$packages" ]]; then
                                package_list="
                                $(translate "Updated packages:") $(echo "$packages" | tr '\n' ', ' | sed 's/,$//')"
                                
                                # If there are more packages, indicate this
                                total_packages=$(echo "$recent_upgrade" | grep -oP '[a-zA-Z0-9.-]+:[a-zA-Z0-9]+ $$[^)]+$$' | wc -l)
                                if [[ $total_packages -gt 5 ]]; then
                                    package_list="$package_list, ... ($(translate "and") $((total_packages-5)) $(translate "more"))"
                                fi
                            fi
                        fi
                    fi
                    
                    # Check if a reboot is required
                    reboot_required=""
                    if [[ -f /var/run/reboot-required ]]; then
                        reboot_required="
                      ⚠️ $(translate "System restart required to complete the update")"
                    fi
                    
                    # Format the notification message
                    send_notification "✅ $(translate "${update_type} update completed")${version_info}${package_count}${package_list}${reboot_required}"
                    
                    event_processed=true
                    
                    # Log the event
                    logger -t proxmox-notify "${update_type} update completed"
                fi
            fi

        done

        # Si llegamos aquí, es porque tail -F terminó inesperadamente
        sleep 5
    done
}


# Function: capture direct system events
capture_direct_events() {

    # Variables to control notification frequency
    local last_load_notification=0
    local last_temp_notification=0
    local last_disk_space_notification=0
    local last_cpu_notification=0
    local last_ram_notification=0
    local last_update_notification=0
    

    local resource_interval=900  # 15 minutes for resources
    local update_interval=86400  # 24 hours for updates
    

    local disk_full_detected=false
    
    while true; do
        current_time=$(date +%s)
        
        # ===== CRITICAL IMMEDIATE NOTIFICATION EVENTS =====
        
        # Disk full (CRITICAL - immediate)
        if [[ "$disk_full" -eq 1 ]]; then
            # Check for disks that are completely full (100%)
            full_disks=$(df -h | awk '$5 == "100%" {print $1 " (100% full)"}')
            
            # Check for disks that are nearly full (>=95%)
            nearly_full_disks=$(df -h | awk '$5 >= "95%" && $5 < "100%" {print $1 " (" $5 " full)"}')
            
            # Handle completely full disks
            if [[ -n "$full_disks" && "$disk_full_detected" = false ]]; then
                # Format the output for better readability
                formatted_full_disks=$(echo "$full_disks" | tr '\n' ', ' | sed 's/,$//' | sed 's/,/, /g')
                
                send_notification "🚨 $(translate "CRITICAL: Storage completely full:") $formatted_full_disks"
                disk_full_detected=true
                
                # Log the event
                logger -t proxmox-notify "CRITICAL: Storage completely full: $formatted_full_disks"
            elif [[ -z "$full_disks" ]]; then
                disk_full_detected=false
            fi
            
            # Handle nearly full disks (separate notification)
            if [[ -n "$nearly_full_disks" && "$disk_nearly_full_detected" = false ]]; then
                # Format the output for better readability
                formatted_nearly_full_disks=$(echo "$nearly_full_disks" | tr '\n' ', ' | sed 's/,$//' | sed 's/,/, /g')
                
                send_notification "⚠️ $(translate "WARNING: Storage nearly full:") $formatted_nearly_full_disks"
                disk_nearly_full_detected=true
                
                # Log the event
                logger -t proxmox-notify "WARNING: Storage nearly full: $formatted_nearly_full_disks"
            elif [[ -z "$nearly_full_disks" ]]; then
                disk_nearly_full_detected=false
            fi
            
            # Check for inode usage (sometimes disks can be full of inodes but not space)
            full_inodes=""
            while read -r filesystem inodes_used inodes_total iuse_percent mounted_on; do
                # Skip if the line doesn't have a valid percentage
                if ! [[ "$iuse_percent" =~ ^[0-9]+%$ ]]; then
                    continue
                fi
                
                # Extract percentage number without the % sign
                percent_num=${iuse_percent/\%/}
                
                # Skip if percentage is less than 95
                if [[ $percent_num -lt 95 ]]; then
                    continue
                fi
                
                # Skip certain Proxmox-specific filesystems that normally show high inode usage
                # but don't represent a real problem
                if [[ "$filesystem" =~ ^/dev/mapper/pve- || 
                    "$filesystem" =~ ^/dev/pve/ || 
                    "$mounted_on" =~ ^/var/lib/vz/root/ || 
                    "$mounted_on" =~ ^/etc/pve/ || 
                    "$mounted_on" == "/var/lib/vz" && "$percent_num" -lt 98 ]]; then
                    continue
                fi
                
                # Skip tmpfs and devtmpfs filesystems
                if [[ "$filesystem" == "tmpfs" || "$filesystem" == "devtmpfs" ]]; then
                    continue
                fi
                
                # Skip if the filesystem has very few total inodes (less than 1000)
                # This helps avoid alerts on small or special filesystems
                if [[ $inodes_total -lt 1000 ]]; then
                    continue
                fi
                
                # Get a more user-friendly name for the filesystem
                fs_name="$filesystem"
                if [[ "$mounted_on" != "/" ]]; then
                    fs_name="$mounted_on ($filesystem)"
                fi
                
                # Add to our list of filesystems with high inode usage
                full_inodes+="$fs_name ($iuse_percent inodos usados, $inodes_used/$inodes_total), "
            done < <(df -i | grep -v "Filesystem" | awk '{print $1, $3, $2, $5, $6}')

            # Remove trailing comma and space if any
            full_inodes=${full_inodes%, }

            if [[ -n "$full_inodes" && "$inode_full_detected" = false ]]; then
                send_notification "⚠️ $(translate "WARNING: Inode usage critical:") $full_inodes"
                inode_full_detected=true
                
                # Log the event
                logger -t proxmox-notify "WARNING: Inode usage critical: $full_inodes"
            elif [[ -z "$full_inodes" ]]; then
                inode_full_detected=false
            fi
        fi
        


        # ===== NON-CRITICAL EVENTS WITH INTERVAL =====
        
        # High system load (NON-CRITICAL - with interval)
        if [[ "$system_load_high" -eq 1 ]]; then
            # Get current load averages (1, 5, 15 minutes)
            load_1=$(awk '{print $1}' /proc/loadavg)
            load_5=$(awk '{print $2}' /proc/loadavg)
            load_15=$(awk '{print $3}' /proc/loadavg)
            
            # Get number of CPU cores
            if [[ -f /proc/cpuinfo ]]; then
                cpu_cores=$(grep -c "^processor" /proc/cpuinfo)
            else
                # Default to 1 if we can't determine
                cpu_cores=1
            fi
            
            # Calculate thresholds based on number of cores
            warning_threshold=$(echo "$cpu_cores * 0.8" | bc -l)
            critical_threshold=$(echo "$cpu_cores * 1.5" | bc -l)
            
            # Format load averages for display
            load_info="1m: $load_1, 5m: $load_5, 15m: $load_15"
            
            # Check if load exceeds critical threshold
            if (( $(echo "$load_1 > $critical_threshold" | bc -l) )) && 
            (( current_time - last_load_notification > resource_interval )); then
                
                # Get top processes consuming CPU
                if command -v top &>/dev/null; then
                    top_processes=$(top -b -n 1 | head -n 12 | tail -n 5 | awk '{print $NF " (" $9 "% CPU)"}' | tr '\n' ', ' | sed 's/,$//')
                    process_info=" $(translate "Top processes:") $top_processes"
                else
                    process_info=""
                fi
                
                # Get memory usage
                if [[ -f /proc/meminfo ]]; then
                    mem_total=$(grep "MemTotal" /proc/meminfo | awk '{print $2}')
                    mem_available=$(grep "MemAvailable" /proc/meminfo | awk '{print $2}')
                    mem_used_percent=$(echo "scale=1; 100 - ($mem_available * 100 / $mem_total)" | bc -l)
                    memory_info=" $(translate "Memory usage:") ${mem_used_percent}%"
                else
                    memory_info=""
                fi
                
                send_notification "🚨 $(translate "CRITICAL: Extremely high system load:") $load_info ($(translate "on") $cpu_cores $(translate "cores"))$memory_info$process_info"
                last_load_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "CRITICAL: Extremely high system load: $load_info"
            
            # Check if load exceeds warning threshold
            elif (( $(echo "$load_1 > $warning_threshold" | bc -l) )) && 
                (( current_time - last_load_notification > resource_interval )); then
                
                # Get memory usage
                if [[ -f /proc/meminfo ]]; then
                    mem_total=$(grep "MemTotal" /proc/meminfo | awk '{print $2}')
                    mem_available=$(grep "MemAvailable" /proc/meminfo | awk '{print $2}')
                    mem_used_percent=$(echo "scale=1; 100 - ($mem_available * 100 / $mem_total)" | bc -l)
                    memory_info=" $(translate "Memory usage:") ${mem_used_percent}%"
                else
                    memory_info=""
                fi
                
                send_notification "⚠️ $(translate "WARNING: High system load:") $load_info ($(translate "on") $cpu_cores $(translate "cores"))$memory_info"
                last_load_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "WARNING: High system load: $load_info"
            fi
        fi



        # Available updates (NON-CRITICAL - with daily interval)
        if [[ "$update_available" -eq 1 ]] && (( current_time - last_update_notification > update_interval )); then
            # Update package lists quietly
            apt-get update -qq &>/dev/null
            
            # Count total upgradable packages
            updates=$(apt list --upgradable 2>/dev/null | grep -v "Listing..." | wc -l)
            
            # Check for security updates specifically
            security_updates=$(apt list --upgradable 2>/dev/null | grep -i security | wc -l)
            
            # Check for Proxmox VE updates specifically
            proxmox_updates=$(apt list --upgradable 2>/dev/null | grep -E "^(proxmox-ve|pve-manager|pve-kernel|pve-container|pve-firewall|pve-ha-manager|pve-docs|pve-qemu-kvm|pve-storage|pve-cluster|pve-gui|pve-headers|pve-firmware|pve-zsync|pve-guest-common)" | wc -l)
            
            # Get Proxmox version information
            current_pve_version=$(pveversion -v 2>/dev/null | grep -oP "pve-manager/\K[0-9]+\.[0-9]+" || echo "unknown")
            
            # Check if there's a new major Proxmox version available
            new_pve_version=""
            if [[ $proxmox_updates -gt 0 ]]; then
                new_version_check=$(apt list --upgradable 2>/dev/null | grep "^pve-manager/" | grep -oP "pve-manager/\K[0-9]+\.[0-9]+" || echo "")
                if [[ -n "$new_version_check" && "$new_version_check" != "$current_pve_version" ]]; then
                    new_pve_version="$new_version_check"
                fi
            fi
            
            # Get list of specific packages that have updates
            if [[ $updates -gt 0 ]]; then
                # Get a list of all upgradable packages (limited to 10 to avoid too long messages)
                package_list=$(apt list --upgradable 2>/dev/null | grep -v "Listing..." | head -n 10 | awk -F/ '{print $1}' | tr '\n' ', ' | sed 's/,$//')
                
                # If there are more than 10 packages, indicate this
                if [[ $updates -gt 10 ]]; then
                    package_list="$package_list, ... ($(translate "and") $((updates-10)) $(translate "more"))"
                fi
                
                # Format the notification message
                update_msg="ℹ️ $(translate "Updates available:") $updates"
                
                if [[ $security_updates -gt 0 ]]; then
                    update_msg="$update_msg ($(translate "including") $security_updates $(translate "security updates"))"
                fi
                
                
                # If there's a new Proxmox version, highlight it
                if [[ -n "$new_pve_version" ]]; then
                    update_msg="🔄 $(translate "NEW PROXMOX VERSION AVAILABLE:") $new_pve_version ($(translate "current:") $current_pve_version)

                $update_msg"
                elif [[ $proxmox_updates -gt 0 ]]; then
                    update_msg="🔄 $(translate "Proxmox updates available") ($proxmox_updates $(translate "packages"))

                $update_msg"
                fi
                
                send_notification "$update_msg"
                last_update_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "Updates available: $updates packages"
            fi
        fi



        # Low disk space (NON-CRITICAL - with interval)
        if [[ "$low_disk_space" -eq 1 ]] && (( current_time - last_disk_space_notification > resource_interval )); then
            # Check partitions with critical space (95-99% usage)
            critical_space=$(df -h | awk '$5 ~ /9[5-9]%/ && $5 != "100%" {print $1 " (" $5 " full, " $4 " free)"}')
            
            # Check partitions with warning space (90-94% usage)
            warning_space=$(df -h | awk '$5 ~ /9[0-4]%/ {print $1 " (" $5 " full, " $4 " free)"}')
            
            # Check partitions with attention space (85-89% usage)
            attention_space=$(df -h | awk '$5 ~ /8[5-9]%/ {print $1 " (" $5 " full, " $4 " free)"}')
            
            # Format messages for better readability
            if [[ -n "$critical_space" ]]; then
                critical_space=$(echo "$critical_space" | tr '\n' ', ' | sed 's/,$//' | sed 's/,/, /g')
            fi
            
            if [[ -n "$warning_space" ]]; then
                warning_space=$(echo "$warning_space" | tr '\n' ', ' | sed 's/,$//' | sed 's/,/, /g')
            fi
            
            if [[ -n "$attention_space" ]]; then
                attention_space=$(echo "$attention_space" | tr '\n' ', ' | sed 's/,$//' | sed 's/,/, /g')
            fi
            
            # Build notification message
            disk_space_msg=""
            
            if [[ -n "$critical_space" ]]; then
                disk_space_msg+="🚨 $(translate "CRITICAL: Very low disk space:") $critical_space"
            fi
            
            if [[ -n "$warning_space" ]]; then
                if [[ -n "$disk_space_msg" ]]; then
                    disk_space_msg+="

        "
                fi
                disk_space_msg+="⚠️ $(translate "WARNING: Low disk space:") $warning_space"
            fi
            
            if [[ -n "$attention_space" && -z "$critical_space" && -z "$warning_space" ]]; then
                # Only show attention level if no higher alerts are present
                disk_space_msg+="ℹ️ $(translate "ATTENTION: Disk space getting low:") $attention_space"
            fi
            
            # Send notification if any space issues were detected
            if [[ -n "$disk_space_msg" ]]; then
                send_notification "$disk_space_msg"
                last_disk_space_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "Low disk space detected"
                
                # Suggest cleanup options for Proxmox
                if [[ -d /var/lib/vz/dump || -d /var/lib/vz/template ]]; then
                    cleanup_msg="$(translate "TIP: Consider cleaning up old backups with:") 'rm -f /var/lib/vz/dump/vzdump-*.tar' $(translate "or old templates with:") 'rm -f /var/lib/vz/template/cache/*.tar.gz'"
                    send_notification "$cleanup_msg"
                fi
            fi
        fi



        # High CPU usage (NON-CRITICAL - with interval)
        if [[ "$cpu_high" -eq 1 ]] && (( current_time - last_cpu_notification > resource_interval )); then
            # Get number of CPU cores
            if [[ -f /proc/cpuinfo ]]; then
                cpu_cores=$(grep -c "^processor" /proc/cpuinfo)
            else
                # Default to 1 if we can't determine
                cpu_cores=1
            fi
            
            # Use mpstat if available, otherwise use top
            if command -v mpstat &>/dev/null; then
                cpu_usage=$(mpstat 1 1 | awk '/Average:/ {print 100 - $NF}')
            else
                cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2 + $4}')
            fi
            
            # Round to one decimal place
            cpu_usage=$(printf "%.1f" $cpu_usage)
            
            # Get CPU temperature if available
            cpu_temp=""
            if command -v sensors &>/dev/null; then
                # Try to get CPU temperature from sensors
                cpu_temp=$(sensors | grep -i "core\|temp" | grep -oP '\+\K[0-9.]+°C' | sort -nr | head -n1)
            elif [[ -f /sys/class/thermal/thermal_zone0/temp ]]; then
                # Alternative method using sysfs
                cpu_temp=$(echo "scale=1; $(cat /sys/class/thermal/thermal_zone0/temp) / 1000" | bc -l)
                cpu_temp="${cpu_temp}°C"
            fi
            
            # Add temperature info if available
            temp_info=""
            if [[ -n "$cpu_temp" ]]; then
                temp_info=" ($(translate "Temperature:") $cpu_temp)"
            fi
            
            # Get top CPU consuming processes
            process_info=""
            if command -v top &>/dev/null; then
                top_processes=$(top -bn1 -o %CPU | head -n 12 | tail -n 5 | awk '{print $NF " (" $9 "%)"}' | tr '\n' ', ' | sed 's/,$//')
                process_info="
        $(translate "Top processes:") $top_processes"
            fi
            
            # Check for critical CPU usage (>95%)
            if (( $(echo "$cpu_usage > 95" | bc -l) )); then
                send_notification "🚨 $(translate "CRITICAL: Very high CPU usage:") ${cpu_usage}% ($(translate "on") $cpu_cores $(translate "cores"))${temp_info}${process_info}"
                last_cpu_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "CRITICAL: Very high CPU usage: ${cpu_usage}%"
            
            # Check for high CPU usage (>85%)
            elif (( $(echo "$cpu_usage > 85" | bc -l) )); then
                send_notification "⚠️ $(translate "WARNING: High CPU usage:") ${cpu_usage}% ($(translate "on") $cpu_cores $(translate "cores"))${temp_info}${process_info}"
                last_cpu_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "WARNING: High CPU usage: ${cpu_usage}%"
            fi
            
            # Check for sustained moderate CPU usage (>70% for extended period)
            # This requires tracking previous readings
            if [[ -z "$cpu_usage_history" ]]; then
                cpu_usage_history="$cpu_usage"
            else
                cpu_usage_history="$cpu_usage_history,$cpu_usage"
                
                # Keep only the last 5 readings
                cpu_usage_history=$(echo "$cpu_usage_history" | awk -F, '{for(i=NF-4>1?NF-4:1; i<=NF; i++) printf("%s%s", $i, i==NF?"":",") }')
                
                # Calculate average of last readings
                cpu_usage_avg=$(echo "$cpu_usage_history" | awk -F, '{sum=0; for(i=1; i<=NF; i++) sum+=$i; print sum/NF}')
                
                # If average is >70% and we haven't sent a notification recently
                if (( $(echo "$cpu_usage_avg > 70" | bc -l) )) && 
                (( current_time - last_cpu_sustained_notification > resource_interval * 3 )); then
                    send_notification "ℹ️ $(translate "ATTENTION: Sustained CPU usage:") ${cpu_usage_avg}% $(translate "average over time") ($(translate "on") $cpu_cores $(translate "cores"))${temp_info}"
                    last_cpu_sustained_notification=$current_time
                    
                    # Log the event
                    logger -t proxmox-notify "ATTENTION: Sustained CPU usage: ${cpu_usage_avg}%"
                fi
            fi
        fi



        # High RAM usage (NON-CRITICAL - with interval)
        if [[ "$ram_high" -eq 1 ]] && (( current_time - last_ram_notification > resource_interval )); then
            # Get detailed memory information
            total_ram=$(free -m | awk '/Mem:/ {print $2}')
            used_ram=$(free -m | awk '/Mem:/ {print $3}')
            free_ram=$(free -m | awk '/Mem:/ {print $4}')
            shared_ram=$(free -m | awk '/Mem:/ {print $5}')
            cache_ram=$(free -m | awk '/Mem:/ {print $6}')
            available_ram=$(free -m | awk '/Mem:/ {print $7}')
            
            # Calculate percentages
            ram_usage=$(echo "scale=1; ($total_ram - $available_ram) * 100 / $total_ram" | bc -l)
            ram_usage_no_cache=$(echo "scale=1; ($used_ram - $cache_ram) * 100 / $total_ram" | bc -l)
            
            # Get swap information
            total_swap=$(free -m | awk '/Swap:/ {print $2}')
            used_swap=$(free -m | awk '/Swap:/ {print $3}')
            
            # Calculate swap percentage if swap exists
            swap_info=""
            if [[ $total_swap -gt 0 ]]; then
                swap_percent=$(echo "scale=1; $used_swap * 100 / $total_swap" | bc -l)
                swap_info=", $(translate "Swap:") ${swap_percent}% (${used_swap}MB/${total_swap}MB)"
            fi
            
            # Format memory values for display
            ram_info="${ram_usage}% (${used_ram}MB/${total_ram}MB)"
            ram_info_detailed="Used: ${used_ram}MB, Free: ${free_ram}MB, Cache: ${cache_ram}MB, Available: ${available_ram}MB"

            # Get top memory consuming processes
            process_info=""
            if command -v ps &>/dev/null; then
                top_processes=$(ps aux --sort=-%mem | head -n 6 | tail -n 5 | awk '{print $11 " (" int($4) "%)"}' | tr '\n' ', ' | sed 's/,$//')
                process_info="
        $(translate "Top processes:") $top_processes"
            fi
            
            # Check for critical RAM usage (>95%)
            if (( $(echo "$ram_usage > 95" | bc -l) )); then
                send_notification "🚨 $(translate "CRITICAL: Very high RAM usage:") ${ram_info}${swap_info}
        ${ram_info_detailed}${process_info}"
                last_ram_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "CRITICAL: Very high RAM usage: ${ram_usage}%"
            
            # Check for high RAM usage (>85%)
            elif (( $(echo "$ram_usage > 85" | bc -l) )); then
                send_notification "⚠️ $(translate "WARNING: High RAM usage:") ${ram_info}${swap_info}
        ${ram_info_detailed}${process_info}"
                last_ram_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "WARNING: High RAM usage: ${ram_usage}%"
            
            # Check for high RAM usage excluding cache (>80%)
            # This is important because Linux uses free RAM for cache, but can free it when needed
            elif (( $(echo "$ram_usage_no_cache > 80" | bc -l) )); then
                send_notification "ℹ️ $(translate "ATTENTION: High RAM usage (excluding cache):") ${ram_usage_no_cache}%${swap_info}
        ${ram_info_detailed}${process_info}"
                last_ram_notification=$current_time
                
                # Log the event
                logger -t proxmox-notify "ATTENTION: High RAM usage (excluding cache): ${ram_usage_no_cache}%"
            fi
            
            # Check for high swap usage if swap exists and is being used
            if [[ $total_swap -gt 0 && $used_swap -gt 0 ]]; then
                # Only alert on high swap if we haven't already alerted on RAM
                if (( $(echo "$swap_percent > 50" | bc -l) )) && 
                (( $(echo "$ram_usage <= 85" | bc -l) )) && 
                (( current_time - last_swap_notification > resource_interval )); then
                    send_notification "⚠️ $(translate "WARNING: High swap usage:") ${swap_percent}% (${used_swap}MB/${total_swap}MB)
        ${ram_info_detailed}${process_info}"
                    last_swap_notification=$current_time
                    
                    # Log the event
                    logger -t proxmox-notify "WARNING: High swap usage: ${swap_percent}%"
                fi
            fi
        fi



        # High temperature (NON-CRITICAL - with interval)
        if [[ "$temp_high" -eq 1 ]] && (( current_time - last_temp_notification > resource_interval )); then
            # Initialize variables
            temp_detected=false
            max_temp=0
            temp_sources=""
            
            # Method 1: Use 'sensors' command if available
            if command -v sensors &>/dev/null; then
                # Update sensors database if needed
                if [[ ! -f /var/run/proxmox-notify-sensors-updated ]]; then
                    sensors-detect --auto &>/dev/null || true
                    touch /var/run/proxmox-notify-sensors-updated
                fi
                
                # Try to get CPU temperature from various patterns
                cpu_temp=$(sensors | grep -E 'Package id 0:|Core [0-9]+:|CPU:|Tdie:|Tctl:' | grep -oP '\+\K[0-9.]+°C|[0-9.]+°C' | sed 's/°C//' | sort -nr | head -n1)
                
                if [[ -n "$cpu_temp" && "$cpu_temp" != "0" ]]; then
                    temp_detected=true
                    if (( $(echo "$cpu_temp > $max_temp" | bc -l) )); then
                        max_temp=$cpu_temp
                        temp_sources="CPU"
                    fi
                fi
                
                # Try to get motherboard/system temperature
                mb_temp=$(sensors | grep -E 'MB Temperature|System Temp|Board Temp|Motherboard' | grep -oP '\+\K[0-9.]+°C|[0-9.]+°C' | sed 's/°C//' | sort -nr | head -n1)
                
                if [[ -n "$mb_temp" && "$mb_temp" != "0" ]]; then
                    temp_detected=true
                    if (( $(echo "$mb_temp > $max_temp" | bc -l) )); then
                        max_temp=$mb_temp
                        temp_sources="Motherboard"
                    elif (( $(echo "$mb_temp == $max_temp" | bc -l) )); then
                        temp_sources="$temp_sources, Motherboard"
                    fi
                fi
                
                # Try to get GPU temperature if available
                gpu_temp=$(sensors | grep -E 'GPU|VGA' | grep -oP '\+\K[0-9.]+°C|[0-9.]+°C' | sed 's/°C//' | sort -nr | head -n1)
                
                if [[ -n "$gpu_temp" && "$gpu_temp" != "0" ]]; then
                    temp_detected=true
                    if (( $(echo "$gpu_temp > $max_temp" | bc -l) )); then
                        max_temp=$gpu_temp
                        temp_sources="GPU"
                    elif (( $(echo "$gpu_temp == $max_temp" | bc -l) )); then
                        temp_sources="$temp_sources, GPU"
                    fi
                fi
                
                # Try to get disk temperature if available
                disk_temp=$(sensors | grep -E 'Drive Temp|Disk Temp|Storage Temp' | grep -oP '\+\K[0-9.]+°C|[0-9.]+°C' | sed 's/°C//' | sort -nr | head -n1)
                
                if [[ -n "$disk_temp" && "$disk_temp" != "0" ]]; then
                    temp_detected=true
                    if (( $(echo "$disk_temp > $max_temp" | bc -l) )); then
                        max_temp=$disk_temp
                        temp_sources="Disk"
                    elif (( $(echo "$disk_temp == $max_temp" | bc -l) )); then
                        temp_sources="$temp_sources, Disk"
                    fi
                fi
            fi
            
            # Method 2: Use sysfs thermal zones if sensors not available or no temp detected
            if ! $temp_detected && [[ -d /sys/class/thermal ]]; then
                for zone in /sys/class/thermal/thermal_zone*/temp; do
                    if [[ -f "$zone" ]]; then
                        zone_temp=$(echo "scale=1; $(cat "$zone") / 1000" | bc -l)
                        
                        if [[ -n "$zone_temp" && "$zone_temp" != "0" ]]; then
                            temp_detected=true
                            if (( $(echo "$zone_temp > $max_temp" | bc -l) )); then
                                max_temp=$zone_temp
                                # Try to get zone type
                                zone_dir=$(dirname "$zone")
                                if [[ -f "$zone_dir/type" ]]; then
                                    zone_type=$(cat "$zone_dir/type")
                                    temp_sources="$zone_type"
                                else
                                    temp_sources="Thermal Zone"
                                fi
                            fi
                        fi
                    fi
                done
            fi
            
            # Method 3: Use ipmitool if available and no temp detected yet
            if ! $temp_detected && command -v ipmitool &>/dev/null; then
                ipmi_temp=$(ipmitool sdr type temperature 2>/dev/null | grep -i -E 'CPU|System|Ambient|Inlet|Exhaust' | head -1 | awk '{print $4}')
                
                if [[ -n "$ipmi_temp" && "$ipmi_temp" != "0" ]]; then
                    temp_detected=true
                    max_temp=$ipmi_temp
                    temp_sources="IPMI"
                fi
            fi
            
            # Method 4: Use hddtemp for disk temperatures if available
            if command -v hddtemp &>/dev/null; then
                for disk in /dev/sd[a-z]; do
                    if [[ -b "$disk" ]]; then
                        disk_temp=$(hddtemp "$disk" 2>/dev/null | grep -oP '[0-9.]+°C' | sed 's/°C//')
                        
                        if [[ -n "$disk_temp" && "$disk_temp" != "0" ]]; then
                            temp_detected=true
                            if (( $(echo "$disk_temp > $max_temp" | bc -l) )); then
                                max_temp=$disk_temp
                                disk_name=$(basename "$disk")
                                temp_sources="Disk $disk_name"
                            elif (( $(echo "$disk_temp == $max_temp" | bc -l) )); then
                                disk_name=$(basename "$disk")
                                temp_sources="$temp_sources, Disk $disk_name"
                            fi
                        fi
                    fi
                done
            fi
            
            # If we detected a temperature, check against thresholds
            if $temp_detected && [[ -n "$max_temp" && "$max_temp" != "0" ]]; then
                # Critical temperature (>90°C)
                if (( $(echo "$max_temp > 90" | bc -l) )); then
                    send_notification "🚨 $(translate "CRITICAL: Dangerously high temperature:") ${max_temp}°C (${temp_sources})"
                    last_temp_notification=$current_time
                    
                    # Log the event
                    logger -t proxmox-notify "CRITICAL: Dangerously high temperature: ${max_temp}°C (${temp_sources})"
                
                # High temperature (>80°C)
                elif (( $(echo "$max_temp > 80" | bc -l) )); then
                    send_notification "⚠️ $(translate "WARNING: High temperature:") ${max_temp}°C (${temp_sources})"
                    last_temp_notification=$current_time
                    
                    # Log the event
                    logger -t proxmox-notify "WARNING: High temperature: ${max_temp}°C (${temp_sources})"
                
                # Elevated temperature (>70°C)
                elif (( $(echo "$max_temp > 70" | bc -l) )); then
                    send_notification "ℹ️ $(translate "ATTENTION: Elevated temperature:") ${max_temp}°C (${temp_sources})"
                    last_temp_notification=$current_time
                    
                    # Log the event
                    logger -t proxmox-notify "ATTENTION: Elevated temperature: ${max_temp}°C (${temp_sources})"
                fi
            fi
        fi

        # Pause between checks
        sleep 30
    done
}










# Function to start the notification service
start_notification_service() {
    if [[ ! -f /etc/systemd/system/proxmox-telegram.service ]]; then
        install_systemd_service
    fi

    if systemctl is-active --quiet proxmox-telegram.service; then
        whiptail --title "$(translate "Information")" \
                 --msgbox "$(translate "The notification service is already running.")" 10 70
    else
        systemctl start proxmox-telegram.service
        if systemctl is-active --quiet proxmox-telegram.service; then
            whiptail --title "$(translate "Started")" \
                     --msgbox "$(translate "The service has been started successfully.")" 10 70
        else
            whiptail --title "$(translate "Error")" \
                     --msgbox "$(translate "Could not start the notification service.")" 10 70
        fi
    fi
}

# Function to stop the service
stop_notification_service() {
    if [[ -f /etc/systemd/system/proxmox-telegram.service ]]; then
        if systemctl is-active --quiet proxmox-telegram.service; then
            systemctl stop proxmox-telegram.service
            sleep 2
        fi

        if ! systemctl is-active --quiet proxmox-telegram.service; then
            whiptail --title "$(translate "Stopped")" \
                     --msgbox "$(translate "The service has been stopped successfully.")" 10 70
        else
            whiptail --title "$(translate "Error")" \
                     --msgbox "$(translate "Could not stop the notification service.")" 10 70
        fi
    else
        whiptail --title "$(translate "Information")" \
                 --msgbox "$(translate "The notification service is not installed yet.")" 10 70
    fi
}

# Function to check service status
check_service_status() {
    clear
    if [[ -f /etc/systemd/system/proxmox-telegram.service ]]; then
        systemctl status proxmox-telegram.service
    else
        echo "$(translate "The service is not installed.")"
    fi
    echo
    msg_success "$(translate "Press Enter to return to the menu...")"
    read -r
}

# Function to remove the systemd service
remove_systemd_service() {
    if [[ -f /etc/systemd/system/proxmox-telegram.service ]]; then
        if systemctl is-active --quiet proxmox-telegram.service; then
            systemctl stop proxmox-telegram.service
        fi
        systemctl disable proxmox-telegram.service
        rm -f /etc/systemd/system/proxmox-telegram.service
        systemctl daemon-reexec
        whiptail --title "$(translate "Removed")" \
                 --msgbox "$(translate "The service has been removed successfully. You can reinstall it from the menu if desired.")" 10 70
    else
        whiptail --title "$(translate "Information")" \
                 --msgbox "$(translate "The service does not exist, nothing to remove.")" 10 70
    fi
}



# Functions required by systemd
start_silent() {
    mkdir -p "$PID_DIR"

    capture_journal_events > /dev/null 2>&1 &
    echo $! > "$PID_DIR/journal.pid"
    journal_pid=$!

    capture_direct_events > /dev/null 2>&1 &
    echo $! > "$PID_DIR/direct.pid"
    direct_pid=$!

    echo $$ > "$PID_DIR/service.pid"

    # Wait for both processes to finish (keeps systemd service alive)
    wait $journal_pid
    wait $direct_pid

}

stop_silent() {
    
    send_notification "⚠️ $(translate "System is shutting down on") $(hostname) at $(date)"

    kill $(cat "$PID_DIR/journal.pid" 2>/dev/null) 2>/dev/null
    kill $(cat "$PID_DIR/direct.pid" 2>/dev/null) 2>/dev/null
    kill $(cat "$PID_DIR/service.pid" 2>/dev/null) 2>/dev/null
    rm -f "$PID_DIR"/*.pid
}




# Function to install the service as a systemd service
install_systemd_service() {
    mkdir -p "$PID_DIR"


    cat > "$WRAPPER_PATH" <<EOW
#!/bin/bash
exec bash <(curl -fsSL https://raw.githubusercontent.com/MacRimi/ProxMenux/main/scripts/telegram-notifier.sh) "\$@"
EOW
    chmod +x "$WRAPPER_PATH"


    cat > /etc/systemd/system/proxmox-telegram.service <<EOF
[Unit]
Description=Proxmox Telegram Notification Service
After=network.target pve-cluster.service

[Service]
Type=simple
ExecStart=$WRAPPER_PATH start_silent
ExecStop=$WRAPPER_PATH stop_silent
Restart=on-failure
PIDFile=$PID_DIR/service.pid

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reexec
    systemctl enable proxmox-telegram.service
    systemctl start proxmox-telegram.service
}



# Main menu
main_menu() {
    while true; do

        local menu_options=(
            "1" "$(translate "Configure Telegram")"
            "2" "$(translate "Configure Notifications")"
            "3" "$(translate "Start Notification Service")"
            "4" "$(translate "Stop Notification Service")"
            "5" "$(translate "Check Service Status")"
        )
        

        if [[ -f /etc/systemd/system/proxmox-telegram.service ]]; then
            menu_options+=(
                "6" "$(translate "Remove Notification Service")"
            )
        fi
        

        menu_options+=(
            "7" "$(translate "Exit")"
        )
        

        OPTION=$(whiptail --backtitle "ProxMenuX" --title "$(translate "Proxmox Notification Configuration")" \
                         --menu "$(translate "Choose an option:")" 20 70 10 \
                         "${menu_options[@]}" \
                         3>&1 1>&2 2>&3)
        
        if [[ $? -ne 0 ]]; then 
            exit 0
        fi
        
        case "$OPTION" in
            1) configure_telegram ;;
            2) configure_notifications ;;
            3) start_notification_service ;;
            4) stop_notification_service ;;
            5) check_service_status ;;
            6) remove_systemd_service ;;
            7) exit 0 ;;
        esac
    done
}

case "$1" in
  start_silent) start_silent ;;
  stop_silent) stop_silent ;;
  *) main_menu ;;
esac