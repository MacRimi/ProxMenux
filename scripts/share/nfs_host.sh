#!/bin/bash
# ==========================================================
# ProxMenux - NFS Host Manager for Proxmox Host
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Mounts an external NFS export on the Proxmox host.
# User picks one or both methods:
#   1. As Proxmox storage (pvesm add nfs)  → /mnt/pve/<id>
#   2. As host fstab mount                 → user-chosen path
#
# Method 2 is for users who want the host to mount the share
# for LXC bind-mounts WITHOUT exposing it as a Proxmox storage
# in the Datacenter UI. The mount path is opened up so
# unprivileged LXCs can read/write through a bind-mount —
# all permission tweaks happen on the host side, NEVER inside
# the container.
#
# Features:
# - Auto-discover NFS servers on the local subnet (nmap).
# - Reachability validation chain (ping + nc + showmount).
# - Content-type checklist (import/backup/iso/vztmpl/images/
#   rootdir/snippets).
# - View, remove and connectivity-test for existing storages.
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

if ! command -v pveversion >/dev/null 2>&1; then
    dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
        --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
    exit 1
fi

# ==========================================================
# STORAGE CONFIG READER
# ==========================================================
get_storage_config() {
    local storage_id="$1"
    awk -v id="$storage_id" '
        /^[a-z]+: / { found = ($0 ~ ": "id"$"); next }
        found && /^[^ \t]/ { exit }
        found { print }
    ' /etc/pve/storage.cfg
}

# ==========================================================
# SERVER DISCOVERY
# ==========================================================

discover_nfs_servers() {
    show_proxmenux_logo
    msg_title "$(translate "Add NFS Share as Proxmox Storage")"
    msg_info "$(translate "Scanning network for NFS servers...")"

    HOST_IP=$(hostname -I | awk '{print $1}')
    NETWORK=$(echo "$HOST_IP" | cut -d. -f1-3).0/24

    if ! which nmap >/dev/null 2>&1; then
        apt-get install -y nmap &>/dev/null
    fi

    SERVERS=$(nmap -p 2049 --open "$NETWORK" 2>/dev/null | grep -B 4 "2049/tcp open" | grep "Nmap scan report" | awk '{print $5}' | sort -u || true)

    if [[ -z "$SERVERS" ]]; then
        cleanup
        dialog --clear --title "$(translate "No Servers Found")" \
            --msgbox "$(translate "No NFS servers found on the network.")\n\n$(translate "You can add servers manually.")" 10 60
        return 1
    fi

    OPTIONS=()
    while IFS= read -r server; do
        if [[ -n "$server" ]]; then
            EXPORTS_COUNT=$(showmount -e "$server" 2>/dev/null | tail -n +2 | wc -l || echo "0")
            OPTIONS+=("$server" "NFS Server ($EXPORTS_COUNT exports)")
        fi
    done <<< "$SERVERS"

    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        cleanup
        dialog --clear --title "$(translate "No Valid Servers")" --msgbox "$(translate "No accessible NFS servers found.")" 8 50
        return 1
    fi

    cleanup
    NFS_SERVER=$(whiptail --backtitle "ProxMenux" --title "$(translate "Select NFS Server")" \
        --menu "$(translate "Choose an NFS server:")" 20 80 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$NFS_SERVER" ]] && return 0 || return 1
}

select_nfs_server() {
    METHOD=$(dialog --backtitle "ProxMenux" --title "$(translate "NFS Server Selection")" \
        --menu "$(translate "How do you want to select the NFS server?")" 15 70 3 \
        "auto"   "$(translate "Auto-discover servers on network")" \
        "manual" "$(translate "Enter server IP/hostname manually")" \
        3>&1 1>&2 2>&3)

    case "$METHOD" in
        auto)
            discover_nfs_servers || return 1
            ;;
        manual)
            clear
            NFS_SERVER=$(whiptail --inputbox "$(translate "Enter NFS server IP or hostname:")" \
                10 60 --title "$(translate "NFS Server")" 3>&1 1>&2 2>&3)
            [[ -z "$NFS_SERVER" ]] && return 1
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

select_nfs_export() {
    if ! which showmount >/dev/null 2>&1; then
        whiptail --title "$(translate "NFS Client Error")" \
            --msgbox "$(translate "showmount command is not working properly.")\n\n$(translate "Please check the installation.")" \
            10 60
        return 1
    fi

    if ! ping -c 1 -W 3 "$NFS_SERVER" >/dev/null 2>&1; then
        whiptail --title "$(translate "Connection Error")" \
            --msgbox "$(translate "Cannot reach server") $NFS_SERVER\n\n$(translate "Please check:")\n• $(translate "Server IP/hostname is correct")\n• $(translate "Network connectivity")\n• $(translate "Server is online")" \
            12 70
        return 1
    fi

    if ! nc -z -w 3 "$NFS_SERVER" 2049 2>/dev/null; then
        whiptail --title "$(translate "NFS Port Error")" \
            --msgbox "$(translate "NFS port (2049) is not accessible on") $NFS_SERVER\n\n$(translate "Please check:")\n• $(translate "NFS server is running")\n• $(translate "Firewall settings")\n• $(translate "NFS service is enabled")" \
            12 70
        return 1
    fi

    EXPORTS_OUTPUT=$(showmount -e "$NFS_SERVER" 2>&1)
    EXPORTS_RESULT=$?

    if [[ $EXPORTS_RESULT -ne 0 ]]; then
        ERROR_MSG=$(echo "$EXPORTS_OUTPUT" | grep -i "error\|failed\|denied" | head -1)
        whiptail --title "$(translate "NFS Error")" \
            --msgbox "$(translate "Failed to connect to") $NFS_SERVER\n\n$(translate "Error:"): $ERROR_MSG" \
            12 80
        return 1
    fi

    EXPORTS=$(echo "$EXPORTS_OUTPUT" | tail -n +2 | awk '{print $1}' | grep -v "^$")

    if [[ -z "$EXPORTS" ]]; then
        whiptail --title "$(translate "No Exports Found")" \
            --msgbox "$(translate "No exports found on server") $NFS_SERVER\n\n$(translate "You can enter the export path manually.")" \
            12 70
        NFS_EXPORT=$(whiptail --inputbox "$(translate "Enter NFS export path (e.g., /mnt/shared):")" \
            10 60 --title "$(translate "Export Path")" 3>&1 1>&2 2>&3)
        [[ -z "$NFS_EXPORT" ]] && return 1
        return 0
    fi

    OPTIONS=()
    while IFS= read -r export_line; do
        if [[ -n "$export_line" ]]; then
            EXPORT_PATH=$(echo "$export_line" | awk '{print $1}')
            CLIENTS=$(echo "$EXPORTS_OUTPUT" | grep "^$EXPORT_PATH" | awk '{for(i=2;i<=NF;i++) printf "%s ",$i; print ""}' | sed 's/[[:space:]]*$//')
            if [[ -n "$CLIENTS" ]]; then
                OPTIONS+=("$EXPORT_PATH" "$CLIENTS")
            else
                OPTIONS+=("$EXPORT_PATH" "$(translate "NFS export")")
            fi
        fi
    done <<< "$EXPORTS"

    if [[ ${#OPTIONS[@]} -eq 0 ]]; then
        NFS_EXPORT=$(whiptail --inputbox "$(translate "Enter NFS export path (e.g., /mnt/shared):")" \
            10 60 --title "$(translate "Export Path")" 3>&1 1>&2 2>&3)
        [[ -n "$NFS_EXPORT" ]] && return 0 || return 1
    fi

    NFS_EXPORT=$(whiptail --title "$(translate "Select NFS Export")" \
        --menu "$(translate "Choose an export to mount:")" 20 70 10 "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$NFS_EXPORT" ]] && return 0 || return 1
}

validate_host_export_exists() {
    local server="$1"
    local export="$2"
    VALIDATION_OUTPUT=$(showmount -e "$server" 2>/dev/null | grep "^${export}[[:space:]]")
    if [[ -n "$VALIDATION_OUTPUT" ]]; then
        return 0
    else
        show_proxmenux_logo
        echo -e
        msg_error "$(translate "Export not found on server:") $export"
        return 1
    fi
}

# ==========================================================
# STORAGE CONFIGURATION
# ==========================================================

configure_nfs_storage() {
    STORAGE_ID=$(whiptail --inputbox "$(translate "Enter storage ID for Proxmox:")" \
        10 60 "nfs-$(echo "$NFS_SERVER" | tr '.' '-')" \
        --title "$(translate "Storage ID")" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1
    [[ -z "$STORAGE_ID" ]] && STORAGE_ID="nfs-$(echo "$NFS_SERVER" | tr '.' '-')"

    if [[ ! "$STORAGE_ID" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
        whiptail --msgbox "$(translate "Invalid storage ID. Use only letters, numbers, hyphens and underscores.")" 8 70
        return 1
    fi

    local raw_content
    raw_content=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Content Types")" \
        --checklist "\n$(translate "Select content types for this storage:")\n$(translate "(Import is selected by default — required for disk image imports)")" 18 65 7 \
        "import"   "$(translate "Import            — disk image imports")"   on  \
        "backup"   "$(translate "Backup            — VM and CT backups")"    off \
        "iso"      "$(translate "ISO image         — installation images")"  off \
        "vztmpl"   "$(translate "Container template— LXC templates")"        off \
        "images"   "$(translate "Disk image        — VM disk images")"       off \
        "rootdir"  "$(translate "Container         — LXC root directories")" off \
        "snippets" "$(translate "Snippets          — hook scripts / config")" off \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    # Convert dialog checklist output (quoted space-separated) to comma-separated
    MOUNT_CONTENT=$(echo "$raw_content" | tr -d '"' | tr -s ' ' ',' | sed 's/^,//;s/,$//')
    [[ -z "$MOUNT_CONTENT" ]] && MOUNT_CONTENT="import"

    return 0
}

add_proxmox_nfs_storage() {
    local storage_id="$1"
    local server="$2"
    local export="$3"
    local content="${4:-import}"

    msg_info "$(translate "Starting Proxmox storage integration...")"

    if ! command -v pvesm >/dev/null 2>&1; then
        msg_error "$(translate "pvesm command not found. This should not happen on Proxmox.")"
        return 1
    fi

    if pvesm status "$storage_id" >/dev/null 2>&1; then
        msg_warn "$(translate "Storage ID already exists:") $storage_id"
        if ! whiptail --yesno "$(translate "Storage ID already exists. Do you want to remove and recreate it?")" \
            8 60 --title "$(translate "Storage Exists")"; then
            return 0
        fi
        pvesm remove "$storage_id" 2>/dev/null || true
    fi

    msg_ok "$(translate "Storage ID is available")"
    msg_info "$(translate "NFS storage adding in progress...")"
    if pvesm_output=$(pvesm add nfs "$storage_id" \
        --server "$server" \
        --export "$export" \
        --content "$content" 2>&1); then

        msg_ok "$(translate "NFS storage added successfully!")"

        local nfs_version="Auto-negotiated"
        if get_storage_config "$storage_id" | grep -q "options.*vers="; then
            nfs_version="v$(get_storage_config "$storage_id" | grep "options" | grep -o "vers=[0-9.]*" | cut -d= -f2)"
        fi

        echo -e ""
        echo -e "${TAB}${BOLD}$(translate "Storage Added:")${CL}"
        echo -e "${TAB}${BGN}$(translate "Storage ID:")${CL} ${BL}$storage_id${CL}"
        echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
        echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$export${CL}"
        echo -e "${TAB}${BGN}$(translate "Content Types:")${CL} ${BL}$content${CL}"
        echo -e "${TAB}${BGN}$(translate "NFS Version:")${CL} ${BL}$nfs_version${CL}"
        echo -e "${TAB}${BGN}$(translate "Mount Path:")${CL} ${BL}/mnt/pve/$storage_id${CL}"
        echo -e ""
        msg_ok "$(translate "Storage is now available in Proxmox web interface under Datacenter > Storage")"
        return 0
    else
        msg_error "$(translate "Failed to add NFS storage to Proxmox.")"
        echo -e "${TAB}$(translate "Error details:"): $pvesm_output"
        echo -e ""
        msg_info2 "$(translate "You can add it manually through:")"
        echo -e "${TAB}• $(translate "Proxmox web interface: Datacenter > Storage > Add > NFS")"
        echo -e "${TAB}• pvesm add nfs $storage_id --server $server --export $export --content $content"
        return 1
    fi
}

# ==========================================================
# FSTAB MOUNT (host-only, NOT as Proxmox storage)
# ==========================================================

# Pick a mount path on the host. Default is /mnt/<export-basename>.
# Validates the path is absolute and not already in use.
select_host_mount_path() {
    local default_name
    default_name=$(basename "$NFS_EXPORT")
    [[ -z "$default_name" || "$default_name" == "/" ]] && default_name="nfs_share"

    while true; do
        HOST_MOUNT_PATH=$(whiptail --inputbox \
            "$(translate "Enter the host mount path:")\n\n$(translate "Default location is /mnt/<name>. The share will be mounted here on the host. Use this path in /etc/fstab. For LXC access, bind-mount this path with the LXC Mount Manager.")" \
            14 70 "/mnt/$default_name" \
            --title "$(translate "Host Mount Path")" 3>&1 1>&2 2>&3)
        [[ $? -ne 0 ]] && return 1
        [[ -z "$HOST_MOUNT_PATH" ]] && HOST_MOUNT_PATH="/mnt/$default_name"

        if [[ ! "$HOST_MOUNT_PATH" =~ ^/.+ ]]; then
            whiptail --msgbox "$(translate "Mount path must be an absolute path starting with /")" 8 60
            continue
        fi

        if mount | grep -q " on $HOST_MOUNT_PATH "; then
            whiptail --msgbox "$(translate "Something is already mounted at:") $HOST_MOUNT_PATH\n\n$(translate "Choose a different path or unmount it first.")" 10 70
            continue
        fi

        if grep -qE "[[:space:]]${HOST_MOUNT_PATH}[[:space:]]" /etc/fstab 2>/dev/null; then
            if ! whiptail --yesno "$(translate "An fstab entry already exists for:") $HOST_MOUNT_PATH\n\n$(translate "Replace it?")" 10 70 \
                --title "$(translate "fstab entry exists")"; then
                continue
            fi
            FSTAB_REPLACE=1
        else
            FSTAB_REPLACE=0
        fi
        break
    done
    return 0
}

# Pick NFS mount options for the fstab entry.
select_nfs_mount_options() {
    local choice
    choice=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "Mount Options")" \
        --menu "$(translate "Select mount options:")" 15 70 4 \
        "1" "$(translate "Read/Write (default)")" \
        "2" "$(translate "Read-only")" \
        "3" "$(translate "Custom")" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    case "$choice" in
        1) NFS_MOUNT_OPTS="rw,hard,nofail,_netdev,rsize=131072,wsize=131072,timeo=600,retrans=2" ;;
        2) NFS_MOUNT_OPTS="ro,hard,nofail,_netdev,rsize=131072,wsize=131072,timeo=600,retrans=2" ;;
        3)
            NFS_MOUNT_OPTS=$(whiptail --inputbox \
                "$(translate "Enter custom NFS mount options:")" \
                10 70 "rw,hard,nofail,_netdev,rsize=131072,wsize=131072,timeo=600,retrans=2" \
                --title "$(translate "Custom Options")" 3>&1 1>&2 2>&3)
            [[ $? -ne 0 ]] && return 1
            [[ -z "$NFS_MOUNT_OPTS" ]] && NFS_MOUNT_OPTS="rw,hard,nofail,_netdev"
            ;;
    esac
    return 0
}

# Mount the NFS export on the host and persist to /etc/fstab.
# Permission tweaks happen on the host side ONLY — never inside any LXC.
mount_nfs_via_fstab() {
    local server="$1"
    local export_path="$2"
    local mount_path="$3"
    local mount_opts="$4"
    local replace="$5"

    msg_info "$(translate "Preparing host mount...")"

    if [[ ! -d "$mount_path" ]]; then
        if ! mkdir -p "$mount_path" 2>/dev/null; then
            msg_error "$(translate "Failed to create mount point:") $mount_path"
            return 1
        fi
    fi
    msg_ok "$(translate "Mount point ready:") $mount_path"

    msg_info "$(translate "Mounting NFS share...")"
    if ! mount -t nfs -o "$mount_opts" "${server}:${export_path}" "$mount_path" >/dev/null 2>&1; then
        msg_error "$(translate "Failed to mount NFS share on host.")"
        return 1
    fi
    msg_ok "$(translate "NFS share mounted at:") $mount_path"

    # Verify host can write (informational — NFS server controls write access).
    if touch "$mount_path/.proxmenux_write_test" 2>/dev/null; then
        rm -f "$mount_path/.proxmenux_write_test" 2>/dev/null
        msg_ok "$(translate "Host write access confirmed.")"
    else
        msg_warn "$(translate "No host write access — server-side ACL or root_squash. Continuing anyway.")"
    fi

    # Best-effort: open perms so an unprivileged LXC bind-mounting this path
    # can read/write. NFS controls perms server-side; these calls succeed only
    # if the server export allows them. Failures are silent.
    chmod 1777 "$mount_path" 2>/dev/null || true
    setfacl -m o::rwx "$mount_path" 2>/dev/null || true

    # Persist in /etc/fstab.
    if [[ "$replace" == "1" ]]; then
        sed -i "\|[[:space:]]${mount_path}[[:space:]]|d" /etc/fstab
    fi
    echo "${server}:${export_path} $mount_path nfs $mount_opts 0 0" >> /etc/fstab
    msg_ok "$(translate "Added to /etc/fstab.")"

    systemctl daemon-reload 2>/dev/null || true

    echo -e ""
    echo -e "${TAB}${BOLD}$(translate "Host fstab Mount:")${CL}"
    echo -e "${TAB}${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
    echo -e "${TAB}${BGN}$(translate "Export:")${CL} ${BL}$export_path${CL}"
    echo -e "${TAB}${BGN}$(translate "Mount path:")${CL} ${BL}$mount_path${CL}"
    echo -e "${TAB}${BGN}$(translate "Options:")${CL} ${BL}$mount_opts${CL}"
    echo -e "${TAB}${BGN}$(translate "Persistent:")${CL} ${BL}$(translate "yes (survives reboot)")${CL}"
    echo -e ""
    msg_info2 "$(translate "To use this share from an LXC, bind-mount it via:")"
    echo -e "${TAB}  pct set <ctid> -mpN $mount_path,mp=<container-path>,shared=1,backup=0"
    echo -e "${TAB}  $(translate "or use the ProxMenux LXC Mount Manager.")"

    return 0
}

# ==========================================================
# MOUNT METHOD SELECTION
# ==========================================================

# Show a checklist with the two mount methods (pvesm / fstab).
# User must mark at least one and press OK; if none is marked,
# loop and show the dialog again. Cancel exits the flow.
# Sets MODE_PVESM and MODE_FSTAB to 0 or 1 on success.
select_mount_methods() {
    MODE_PVESM=0
    MODE_FSTAB=0

    while true; do
        local result
        result=$(dialog --backtitle "ProxMenux" \
            --title "$(translate "Mount Method")" \
            --checklist "\n$(translate "Choose how to mount the NFS share on this host. Mark one or both options:")\n\n$(translate "• Proxmox storage (pvesm): visible in Datacenter > Storage, mount at /mnt/pve/<id>")\n$(translate "• Host fstab: mounted at a path you choose, NOT visible as Proxmox storage")\n$(translate "• Both: mounts twice (pvesm + an independent fstab entry)")" 20 78 2 \
            "pvesm" "$(translate "As Proxmox storage")"      off \
            "fstab" "$(translate "As host fstab mount only")" off \
            3>&1 1>&2 2>&3)
        local rc=$?
        [[ $rc -ne 0 ]] && return 1   # Cancel → abort the whole flow

        # Parse selection
        if echo "$result" | grep -qw "pvesm"; then MODE_PVESM=1; fi
        if echo "$result" | grep -qw "fstab"; then MODE_FSTAB=1; fi

        if [[ "$MODE_PVESM" == "1" || "$MODE_FSTAB" == "1" ]]; then
            return 0
        fi

        whiptail --msgbox "$(translate "Please mark at least one option, or press Cancel to exit.")" 8 70
    done
}

# ==========================================================
# MAIN OPERATIONS
# ==========================================================

mount_nfs_share() {
    if ! which showmount >/dev/null 2>&1; then
        msg_info "$(translate "Installing NFS client tools...")"
        apt-get update &>/dev/null
        apt-get install -y nfs-common &>/dev/null
        msg_ok "$(translate "NFS client tools installed")"
    fi

    # Step 1: Select server
    select_nfs_server || return

    # Step 2: Select export
    select_nfs_export || return

    # Step 3: Validate export
    if ! validate_host_export_exists "$NFS_SERVER" "$NFS_EXPORT"; then
        echo -e ""
        msg_error "$(translate "Cannot proceed with invalid export path.")"
        msg_success "$(translate "Press Enter to continue...")"
        read -r
        return
    fi

    # Step 4: Pick mount method(s) — pvesm, fstab, or both
    select_mount_methods || return

    # Step 5a: If pvesm selected, gather storage params
    if [[ "$MODE_PVESM" == "1" ]]; then
        configure_nfs_storage || return
    fi

    # Step 5b: If fstab selected, gather host mount params
    if [[ "$MODE_FSTAB" == "1" ]]; then
        select_host_mount_path || return
        select_nfs_mount_options || return
    fi

    # Step 6: Apply
    show_proxmenux_logo
    msg_title "$(translate "Mount NFS Share on Host")"
    msg_ok "$(translate "NFS server:") $NFS_SERVER"
    msg_ok "$(translate "NFS export:") $NFS_EXPORT"
    if [[ "$MODE_PVESM" == "1" ]]; then
        msg_ok "$(translate "Method:") pvesm  ($(translate "Storage ID:") $STORAGE_ID, $(translate "content:") $MOUNT_CONTENT)"
    fi
    if [[ "$MODE_FSTAB" == "1" ]]; then
        msg_ok "$(translate "Method:") fstab  ($(translate "Mount path:") $HOST_MOUNT_PATH)"
    fi
    echo -e ""

    local overall_rc=0
    if [[ "$MODE_PVESM" == "1" ]]; then
        if ! add_proxmox_nfs_storage "$STORAGE_ID" "$NFS_SERVER" "$NFS_EXPORT" "$MOUNT_CONTENT"; then
            overall_rc=1
        fi
        echo -e ""
    fi
    if [[ "$MODE_FSTAB" == "1" ]]; then
        if ! mount_nfs_via_fstab "$NFS_SERVER" "$NFS_EXPORT" "$HOST_MOUNT_PATH" "$NFS_MOUNT_OPTS" "$FSTAB_REPLACE"; then
            overall_rc=1
        fi
    fi

    echo -e ""
    if [[ "$overall_rc" == "0" ]]; then
        msg_success "$(translate "Press Enter to continue...")"
    else
        msg_warn "$(translate "Some operations failed — review messages above. Press Enter to continue...")"
    fi
    read -r
}

# ==========================================================
# FSTAB ENTRY DISCOVERY (host mounts NOT registered with pvesm)
# ==========================================================

# Print every NFS entry in /etc/fstab as: server|export|mount_path|opts
# Skips comments and blank lines. Includes both currently-mounted and
# inactive entries (the live state is reported by the caller).
list_nfs_fstab_entries() {
    awk '
        /^[[:space:]]*#/  { next }
        /^[[:space:]]*$/  { next }
        $3 == "nfs" || $3 == "nfs4" {
            # $1 = server:/export, $2 = mount path, $4 = opts
            split($1, srv_exp, ":")
            print srv_exp[1] "|" srv_exp[2] "|" $2 "|" $4
        }
    ' /etc/fstab 2>/dev/null
}

# Echo "active" if the given path is currently mounted, "inactive" otherwise.
check_mount_state() {
    local path="$1"
    if mount | grep -q " on ${path} type "; then
        echo "active"
    else
        echo "inactive"
    fi
}

view_nfs_storages() {
    show_proxmenux_logo
    msg_title "$(translate "NFS Mounts on Host")"

    echo "=================================================="
    echo ""

    # ---- Proxmox storages (pvesm) ----
    local NFS_STORAGES=""
    if command -v pvesm >/dev/null 2>&1; then
        NFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "nfs" {print $1, $3}')
    fi

    if [[ -z "$NFS_STORAGES" ]]; then
        msg_warn "$(translate "No NFS Proxmox storages configured.")"
    else
        echo -e "${BOLD}$(translate "NFS Proxmox storages (pvesm):")${CL}"
        echo ""
        while IFS=" " read -r storage_id storage_status; do
            [[ -z "$storage_id" ]] && continue
            local storage_info server export_path content
            storage_info=$(get_storage_config "$storage_id")
            server=$(echo "$storage_info" | awk '$1 == "server" {print $2}')
            export_path=$(echo "$storage_info" | awk '$1 == "export" {print $2}')
            content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')

            echo -e "${TAB}${BOLD}$storage_id${CL}  ${TAB}[pvesm]"
            echo -e "${TAB}  ${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Export:")${CL} ${BL}$export_path${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Content:")${CL} ${BL}$content${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Mount Path:")${CL} ${BL}/mnt/pve/$storage_id${CL}"
            if [[ "$storage_status" == "active" ]]; then
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${GN}$(translate "Active")${CL}"
            else
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${RD}$storage_status${CL}"
            fi
            echo ""
        done <<< "$NFS_STORAGES"
    fi

    # ---- Host fstab mounts (NOT pvesm) ----
    local FSTAB_ENTRIES
    FSTAB_ENTRIES=$(list_nfs_fstab_entries)

    if [[ -z "$FSTAB_ENTRIES" ]]; then
        echo -e "${BOLD}$(translate "Host fstab NFS mounts:")${CL} $(translate "(none)")"
    else
        echo -e "${BOLD}$(translate "Host fstab NFS mounts (not registered with pvesm):")${CL}"
        echo ""
        while IFS="|" read -r server export_path mount_path opts; do
            [[ -z "$mount_path" ]] && continue
            local mstate
            mstate=$(check_mount_state "$mount_path")

            echo -e "${TAB}${BOLD}$(basename "$mount_path")${CL}  ${TAB}[fstab]"
            echo -e "${TAB}  ${BGN}$(translate "Server:")${CL} ${BL}$server${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Export:")${CL} ${BL}$export_path${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Mount Path:")${CL} ${BL}$mount_path${CL}"
            echo -e "${TAB}  ${BGN}$(translate "Options:")${CL} ${BL}$opts${CL}"
            if [[ "$mstate" == "active" ]]; then
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${GN}$(translate "Active")${CL}"
            else
                echo -e "${TAB}  ${BGN}$(translate "Status:")${CL} ${RD}$(translate "Inactive (entry in fstab, not currently mounted)")${CL}"
            fi
            echo ""
        done <<< "$FSTAB_ENTRIES"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

remove_nfs_storage() {
    # Collect every removable NFS entry: pvesm storages and fstab-only mounts.
    local OPTIONS=()
    local has_pvesm=0
    local has_fstab=0

    # pvesm-registered NFS storages
    if command -v pvesm >/dev/null 2>&1; then
        local NFS_STORAGES
        NFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "nfs" {print $1}')
        if [[ -n "$NFS_STORAGES" ]]; then
            has_pvesm=1
            while IFS= read -r storage_id; do
                [[ -z "$storage_id" ]] && continue
                local storage_info server export_path
                storage_info=$(get_storage_config "$storage_id")
                server=$(echo "$storage_info" | awk '$1 == "server" {print $2}')
                export_path=$(echo "$storage_info" | awk '$1 == "export" {print $2}')
                # Encode key with a prefix so we know how to handle the selection.
                OPTIONS+=("pvesm:$storage_id" "[pvesm] $storage_id  ($server:$export_path)")
            done <<< "$NFS_STORAGES"
        fi
    fi

    # fstab-only NFS mounts
    local FSTAB_ENTRIES
    FSTAB_ENTRIES=$(list_nfs_fstab_entries)
    if [[ -n "$FSTAB_ENTRIES" ]]; then
        has_fstab=1
        while IFS="|" read -r server export_path mount_path opts; do
            [[ -z "$mount_path" ]] && continue
            OPTIONS+=("fstab:$mount_path" "[fstab] $mount_path  ($server:$export_path)")
        done <<< "$FSTAB_ENTRIES"
    fi

    if [[ "$has_pvesm" == "0" && "$has_fstab" == "0" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Nothing to remove")" \
            --msgbox "\n$(translate "No NFS Proxmox storage and no NFS fstab mount found on this host.")" 9 70
        return
    fi

    local SELECTED
    SELECTED=$(dialog --backtitle "ProxMenux" --title "$(translate "Remove NFS Mount")" \
        --menu "$(translate "Select the entry to remove. [pvesm] entries are removed from Proxmox storage; [fstab] entries are unmounted and removed from /etc/fstab.")" \
        20 90 12 \
        "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
    [[ -z "$SELECTED" ]] && return

    local kind="${SELECTED%%:*}"
    local target="${SELECTED#*:}"

    case "$kind" in
        pvesm)
            local storage_info server export_path content
            storage_info=$(get_storage_config "$target")
            server=$(echo "$storage_info" | awk '$1 == "server" {print $2}')
            export_path=$(echo "$storage_info" | awk '$1 == "export" {print $2}')
            content=$(echo "$storage_info" | awk '$1 == "content" {print $2}')

            if whiptail --yesno "$(translate "Remove Proxmox NFS storage:")\n\n$target\n\n$(translate "Server:"): $server\n$(translate "Export:"): $export_path\n$(translate "Content:"): $content\n\n$(translate "WARNING: This removes the storage from Proxmox. The NFS server is not affected.")" \
                16 80 --title "$(translate "Confirm Remove")"; then

                show_proxmenux_logo
                msg_title "$(translate "Remove NFS Storage")"

                if pvesm remove "$target" 2>/dev/null; then
                    msg_ok "$(translate "Storage") $target $(translate "removed successfully from Proxmox.")"
                else
                    msg_error "$(translate "Failed to remove storage.")"
                fi

                echo -e ""
                msg_success "$(translate "Press Enter to continue...")"
                read -r
            fi
            ;;
        fstab)
            local mount_path="$target"
            local fstab_line
            fstab_line=$(awk -v mp="$mount_path" '$2 == mp && ($3 == "nfs" || $3 == "nfs4") {print; exit}' /etc/fstab)

            if whiptail --yesno "$(translate "Remove NFS fstab mount:")\n\n$mount_path\n\n$(translate "fstab line:")\n$fstab_line\n\n$(translate "Steps that will run:")\n  1. $(translate "umount the path if currently mounted")\n  2. $(translate "delete the matching line from /etc/fstab")\n  3. $(translate "remove the (now-empty) directory if possible")\n\n$(translate "WARNING: The NFS server is not affected. The mount directory contents are NOT deleted (data stays on the server).")" \
                20 90 --title "$(translate "Confirm Remove")"; then

                show_proxmenux_logo
                msg_title "$(translate "Remove NFS fstab Mount")"

                # Try umount only if currently mounted; never force.
                if mount | grep -q " on ${mount_path} type "; then
                    if umount "$mount_path" 2>/dev/null; then
                        msg_ok "$(translate "Unmounted:") $mount_path"
                    else
                        msg_warn "$(translate "Could not unmount") $mount_path. $(translate "The fstab entry will still be removed; reboot or manual umount needed.")"
                    fi
                else
                    msg_info2 "$(translate "Not currently mounted — skipping umount.")"
                fi

                # Delete the matching line(s) from /etc/fstab using awk (exact $2 + $3 match).
                cp /etc/fstab /etc/fstab.proxmenux.bak 2>/dev/null
                if awk -v mp="$mount_path" '
                    $2 == mp && ($3 == "nfs" || $3 == "nfs4") { next }
                    { print }
                ' /etc/fstab > /etc/fstab.tmp && mv /etc/fstab.tmp /etc/fstab; then
                    msg_ok "$(translate "Removed entry from /etc/fstab")  ($(translate "backup at /etc/fstab.proxmenux.bak"))"
                else
                    msg_error "$(translate "Failed to edit /etc/fstab — remove the line manually.")"
                fi

                systemctl daemon-reload 2>/dev/null || true

                # Try to remove the directory if empty; keep it otherwise.
                if [[ -d "$mount_path" ]] && rmdir "$mount_path" 2>/dev/null; then
                    msg_ok "$(translate "Removed empty mount directory:") $mount_path"
                fi

                echo -e ""
                msg_success "$(translate "Press Enter to continue...")"
                read -r
            fi
            ;;
    esac
}

test_nfs_connectivity() {
    show_proxmenux_logo
    msg_title "$(translate "Test NFS Connectivity")"

    echo "=================================================="
    echo ""

    if which showmount >/dev/null 2>&1; then
        msg_ok "$(translate "NFS Client Tools: AVAILABLE")"

        if systemctl is-active --quiet rpcbind 2>/dev/null; then
            msg_ok "$(translate "RPC Bind Service: RUNNING")"
        else
            msg_warn "$(translate "RPC Bind Service: STOPPED - starting...")"
            systemctl start rpcbind 2>/dev/null || true
        fi
    else
        msg_warn "$(translate "NFS Client Tools: NOT AVAILABLE")"
    fi

    echo ""

    if command -v pvesm >/dev/null 2>&1; then
        echo -e "${BOLD}$(translate "Proxmox NFS Storage Status:")${CL}"
        NFS_STORAGES=$(pvesm status 2>/dev/null | awk '$2 == "nfs" {print $1, $3}')

        if [[ -n "$NFS_STORAGES" ]]; then
            while IFS=" " read -r storage_id storage_status; do
                [[ -z "$storage_id" ]] && continue
                local server
                server=$(get_storage_config "$storage_id" | awk '$1 == "server" {print $2}')

                echo -n "  [pvesm] $storage_id ($server): "

                if ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                    echo -ne "${GN}$(translate "Reachable")${CL}"

                    if nc -z -w 2 "$server" 2049 2>/dev/null; then
                        echo -e " | NFS port 2049: ${GN}$(translate "Open")${CL}"
                    else
                        echo -e " | NFS port 2049: ${RD}$(translate "Closed")${CL}"
                    fi

                    if showmount -e "$server" >/dev/null 2>&1; then
                        echo -e "    $(translate "Export list:") ${GN}$(translate "Available")${CL}"
                    else
                        echo -e "    $(translate "Export list:") ${RD}$(translate "Failed")${CL}"
                    fi
                else
                    echo -e "${RD}$(translate "Unreachable")${CL}"
                fi

                if [[ "$storage_status" == "active" ]]; then
                    echo -e "    $(translate "Proxmox status:") ${GN}$storage_status${CL}"
                else
                    echo -e "    $(translate "Proxmox status:") ${RD}$storage_status${CL}"
                fi
                echo ""
            done <<< "$NFS_STORAGES"
        else
            echo "  $(translate "No NFS Proxmox storage configured.")"
        fi
    else
        msg_warn "$(translate "pvesm not available.")"
    fi

    # ---- fstab-only NFS mounts ----
    local FSTAB_ENTRIES
    FSTAB_ENTRIES=$(list_nfs_fstab_entries)
    echo ""
    echo -e "${BOLD}$(translate "Host fstab NFS Mounts:")${CL}"
    if [[ -z "$FSTAB_ENTRIES" ]]; then
        echo "  $(translate "(none)")"
    else
        while IFS="|" read -r server export_path mount_path opts; do
            [[ -z "$mount_path" ]] && continue
            echo -n "  [fstab] $mount_path ($server:$export_path): "

            if ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
                echo -ne "${GN}$(translate "Reachable")${CL}"
                if nc -z -w 2 "$server" 2049 2>/dev/null; then
                    echo -e " | NFS port 2049: ${GN}$(translate "Open")${CL}"
                else
                    echo -e " | NFS port 2049: ${RD}$(translate "Closed")${CL}"
                fi
            else
                echo -e "${RD}$(translate "Unreachable")${CL}"
            fi

            local mstate
            mstate=$(check_mount_state "$mount_path")
            if [[ "$mstate" == "active" ]]; then
                echo -e "    $(translate "Mount status:") ${GN}$(translate "Active")${CL}"
            else
                echo -e "    $(translate "Mount status:") ${RD}$(translate "Not currently mounted")${CL}"
            fi
            echo ""
        done <<< "$FSTAB_ENTRIES"
    fi

    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}

# ==========================================================
# MAIN MENU
# ==========================================================

while true; do
    CHOICE=$(dialog --backtitle "ProxMenux" \
        --title "$(translate "NFS Host Manager - Proxmox Host")" \
        --menu "$(translate "Choose an option:")" 18 70 6 \
        "1" "$(translate "Mount NFS Share on Host")" \
        "2" "$(translate "View NFS Mounts (pvesm + fstab)")" \
        "3" "$(translate "Remove NFS Mount (pvesm or fstab)")" \
        "4" "$(translate "Test NFS Connectivity")" \
        "5" "$(translate "Exit")" \
        3>&1 1>&2 2>&3)

    RETVAL=$?
    if [[ $RETVAL -ne 0 ]]; then
        exit 0
    fi

    case $CHOICE in
        1) mount_nfs_share ;;
        2) view_nfs_storages ;;
        3) remove_nfs_storage ;;
        4) test_nfs_connectivity ;;
        5) exit 0 ;;
        *) exit 0 ;;
    esac
done
