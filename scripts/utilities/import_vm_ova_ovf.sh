#!/bin/bash
# ==========================================================
# ProxMenux - Import VM from OVA or OVF
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Imports a virtual machine from an OVA or OVF package into
# Proxmox VE. Compatible with exports from VMware (ESXi /
# Workstation / Fusion), VirtualBox and Proxmox itself (via the
# matching export_vm_ova_ovf.sh).
#
# Features:
#   - File picker: scans /var/lib/vz/dump and /var/lib/vz/template/iso
#     by default, manual path also supported. Lists every .ova / .ovf.
#   - OVA auto-extracted to /tmp/.proxmenux-import-* with cleanup
#     trap; OVF used in place.
#   - OVF parsed via AWK to extract VM name, vCPU count, memory
#     (RASD ResourceType 4), NIC count (type 10) and disk file
#     references (.vmdk / .qcow2 / .img / .raw).
#   - OS-type heuristic: maps Linux -> l26, Windows -> win10,
#     anything else -> other.
#   - Dialog flow for VMID (suggests pvesh nextid), name, target
#     storage (pvesm status -content images), bridge (auto-picks
#     when only one exists).
#   - VM created with --scsihw lsi --net0 e1000,bridge=...; extra
#     NICs added per OVF NIC count.
#   - Disks imported with 'qm importdisk' (storage-native format),
#     then attached as scsiN and unusedN markers cleared.
#   - Boot config set to scsi0.
#
# What requires manual review after import:
#   - Network bridge assignment (vmbr0 assigned by default).
#   - NIC model (e1000 by default -- change to VirtIO if guest
#     supports it).
#   - Firmware (BIOS / UEFI -- must match the original VM).
#   - VirtIO/qemu-guest-agent installation inside the guest (especially from ESXi)
#   - PCI passthrough, TPM, cloud-init, snapshots — not portable in OVF/OVA
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
LOCAL_SCRIPTS="$BASE_DIR/scripts"
UTILS_FILE="$BASE_DIR/utils.sh"
INSTALL_HELPERS="$LOCAL_SCRIPTS/global/utils-install-functions.sh"

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
[[ -f "$INSTALL_HELPERS" ]] && source "$INSTALL_HELPERS"
load_language
initialize_cache

BACKTITLE="ProxMenux"
UI_MENU_H=20
UI_MENU_W=84
UI_MENU_LIST_H=10

# Globals populated during the flow
SOURCE_FILE=""
OVF_FILE=""
OVF_DIR=""
WORK_DIR=""

OVF_VM_NAME=""
OVF_VCPUS=1
OVF_MEMORY_MB=1024
OVF_DISK_FILES=()
OVF_DISK_CAPACITIES=()
OVF_NET_COUNT=0
OVF_OS_TYPE="other"

NEW_VMID=""
NEW_VM_NAME=""
STORAGE=""
BRIDGE="vmbr0"


# -------------------------------------------------------
# HELPERS
# -------------------------------------------------------

# Ensure GNU awk (gawk) is installed before parsing OVF.
# The OVF parser uses match($0, /regex/, array) — the 3-argument form
# is a gawk extension; mawk (the Debian/Proxmox default 'awk') errors
# with "syntax error at or near ,". Returns 0 on success, 1 if install
# fails (caller is expected to abort with a clear error).
ensure_gawk() {
    if command -v gawk >/dev/null 2>&1; then
        return 0
    fi

    echo

    if type ensure_repositories &>/dev/null && type install_single_package &>/dev/null; then
        # Canonical path: install_single_package handles its own
        # msg_info / msg_ok / msg_error pair, so we don't open one here
        # (would leave an orphan spinner overlapping with theirs).
        if ! ensure_repositories; then
            msg_error "$(translate "Failed to configure repositories.")"
            return 1
        fi
        install_single_package "gawk" "gawk" "GNU awk (required for OVF parsing)"
        case $? in
            0|2) return 0 ;;
            *) return 1 ;;
        esac
    fi

    # Fallback when utils-install-functions.sh was not sourced.
    # Here we own the spinner: msg_info opens it, msg_ok / msg_error closes it.
    msg_info "$(translate "Installing gawk (required for OVF parsing)...")"
    if apt-get update -qq >/dev/null 2>&1 && apt-get install -y gawk >/dev/null 2>&1; then
        msg_ok "$(translate "gawk installed")"
        return 0
    fi

    msg_error "$(translate "Failed to install gawk")"
    msg_warn "$(translate "Install manually with:") apt-get install gawk"
    return 1
}

human_bytes() {
    local bytes="$1"
    local units=("B" "KB" "MB" "GB" "TB")
    local idx=0 value="$bytes"
    [[ -z "$value" || ! "$value" =~ ^[0-9]+$ ]] && { echo "N/A"; return; }
    while [[ "$value" -ge 1024 && "$idx" -lt 4 ]]; do
        value=$((value / 1024))
        idx=$((idx + 1))
    done
    echo "${value}${units[$idx]}"
}


# -------------------------------------------------------
# SELECT SOURCE FILE
# -------------------------------------------------------

select_source_file() {
    local dump_dir="/var/lib/vz/dump"
    local iso_dir="/var/lib/vz/template/iso"
    local options=(
        "1" "$dump_dir"
        "2" "$iso_dir"
        "M" "$(translate "Manual path entry")"
    )

    while true; do
        local choice
        choice=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Import VM from OVA or OVF")" \
            --menu "$(translate "Where is the OVA/OVF file located?")" \
            14 82 4 "${options[@]}" 3>&1 1>&2 2>&3)
        [[ -n "$choice" ]] || return 1

        local search_dir=""
        case "$choice" in
            1) search_dir="$dump_dir" ;;
            2) search_dir="$iso_dir" ;;
            M)
                search_dir=$(dialog --backtitle "$BACKTITLE" \
                    --title "$(translate "Custom Path")" \
                    --inputbox "\n$(translate "Enter directory containing OVA/OVF files:")" \
                    10 82 "/var/lib/vz/dump" 3>&1 1>&2 2>&3)
                [[ -n "$search_dir" ]] || continue
                ;;
        esac

        if [[ ! -d "$search_dir" ]]; then
            dialog --backtitle "$BACKTITLE" --title "$(translate "Not found")" \
                --msgbox "$(translate "Directory does not exist:")\n$search_dir" 8 74
            continue
        fi

        local file_opts=()
        while IFS= read -r f; do
            local fname size_h
            fname=$(basename "$f")
            size_h=$(du -sh "$f" 2>/dev/null | awk '{print $1}')
            file_opts+=("$f" "$fname  [$size_h]")
        done < <(find "$search_dir" -maxdepth 2 \( -name "*.ova" -o -name "*.ovf" \) 2>/dev/null | sort)

        if [[ ${#file_opts[@]} -eq 0 ]]; then
            dialog --backtitle "$BACKTITLE" \
                --title "$(translate "No files found")" \
                --msgbox "$(translate "No .ova or .ovf files found in:")\n\n$search_dir" 10 74
            continue
        fi

        local selected
        selected=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Select OVA/OVF file")" \
            --menu "$(translate "Select the file to import:")" \
            $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
            "${file_opts[@]}" 3>&1 1>&2 2>&3)

        [[ -n "$selected" ]] || continue

        SOURCE_FILE="$selected"
        return 0
    done
}


# -------------------------------------------------------
# EXTRACT OVA / LOCATE OVF
# -------------------------------------------------------

prepare_ovf() {
    local src="$SOURCE_FILE"
    local ext="${src##*.}"
    ext="${ext,,}"

    if [[ "$ext" == "ova" ]]; then
        WORK_DIR=$(mktemp -d "/tmp/.proxmenux-import-XXXXXX")
        trap 'rm -rf "$WORK_DIR" 2>/dev/null' EXIT

        msg_info "$(translate "Extracting OVA archive...")"
        if ! tar xf "$src" -C "$WORK_DIR" 2>/dev/null; then
            msg_error "$(translate "Failed to extract OVA file:") $src"
            return 1
        fi
        msg_ok "$(translate "Archive extracted.")"

        OVF_FILE=$(find "$WORK_DIR" -maxdepth 2 -name "*.ovf" | head -1)
        if [[ -z "$OVF_FILE" ]]; then
            msg_error "$(translate "No .ovf descriptor found inside OVA.")"
            return 1
        fi
        OVF_DIR=$(dirname "$OVF_FILE")

    elif [[ "$ext" == "ovf" ]]; then
        OVF_FILE="$src"
        OVF_DIR=$(dirname "$src")
        WORK_DIR=""

    else
        msg_error "$(translate "Unsupported format. Only .ova and .ovf files are supported.")"
        return 1
    fi

    return 0
}


# -------------------------------------------------------
# PARSE OVF XML
# -------------------------------------------------------

parse_ovf() {
    local ovf_file="$1"

    # The parser below uses gawk's 3-argument match() form, which is
    # NOT supported by mawk (the default 'awk' on Debian/Proxmox).
    # ensure_gawk installs gawk on first use if missing.
    ensure_gawk || return 1

    local result
    result=$(gawk '
        BEGIN {
            in_item=0; rt=""; qty=""
            file_count=0; cap_count=0; net_count=0
            name=""; vcpu="1"; mem="1024"; os=""
        }

        /<[Nn]ame>/ {
            match($0, /<[Nn]ame>([^<]+)</, a)
            if (a[1] != "" && name == "") name = a[1]
        }

        /[Ll]inux/ && /[Dd]escription|[Oo]perating/ { if (os == "") os="linux" }
        /[Ww]indows/ && /[Dd]escription|[Oo]perating/ { if (os == "") os="windows" }

        /ovf:href=|href=/ {
            n = split($0, parts, /"/)
            for (i=1; i<=n; i++) {
                if (parts[i] ~ /\.(vmdk|qcow2|img|raw)$/) {
                    files[file_count++] = parts[i]
                }
            }
        }

        /[Cc]apacity=/ {
            match($0, /[Cc]apacity="([0-9]+)"/, a)
            if (a[1]+0 > 0) caps[cap_count++] = a[1]
        }

        /<Item>|<Item / { in_item=1; rt=""; qty=""; au="" }
        /<\/Item>/ {
            if (in_item) {
                if (rt=="3" && qty ~ /^[0-9]+$/) vcpu=qty
                # ResourceType=4 is Memory. Normalise `qty` to MiB based
                # on AllocationUnits: VMware sometimes emits `byte`,
                # `byte * 2^10` (KiB), `byte * 2^30` (GiB) or textual
                # `MegaBytes`/`GigaBytes`. Defaulting to MiB blindly
                # (the previous behaviour) imported 8 GB VMs as 8 MiB
                # or vice-versa. Audit Tier 6 — OVF memory units.
                if (rt=="4" && qty ~ /^[0-9]+$/) {
                    if (au ~ /byte \* 2\^30/ || au ~ /[Gg]iga[Bb]yte/) {
                        mem = qty * 1024
                    } else if (au ~ /byte \* 2\^10/ || au ~ /[Kk]ilo[Bb]yte/) {
                        mem = int((qty + 1023) / 1024)
                    } else if (au ~ /byte \* 2\^20/ || au ~ /[Mm]ega[Bb]yte/ || au == "") {
                        mem = qty
                    } else if (au == "byte" || au ~ /^bytes?$/) {
                        mem = int((qty + 1048575) / 1048576)
                    } else {
                        mem = qty
                    }
                }
                if (rt=="10") net_count++
            }
            in_item=0
        }
        /ResourceType>/ {
            match($0, /ResourceType>([0-9]+)</, a); rt=a[1]
        }
        /VirtualQuantity>/ {
            match($0, /VirtualQuantity>([0-9]+)</, a); qty=a[1]
        }
        /AllocationUnits>/ {
            match($0, /AllocationUnits>([^<]+)</, a); au=a[1]
        }

        END {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
            if (name == "") name = "imported-vm"
            print "NAME=" name
            print "VCPU=" vcpu
            print "MEM=" mem
            print "NET=" net_count
            print "OS=" os
            for (i=0; i<file_count; i++) print "FILE=" files[i]
            for (i=0; i<cap_count; i++) print "CAP=" caps[i]
        }
    ' "$ovf_file")

    OVF_VM_NAME=$(echo "$result" | grep '^NAME=' | cut -d= -f2-)
    OVF_VCPUS=$(echo "$result"  | grep '^VCPU=' | cut -d= -f2-)
    OVF_MEMORY_MB=$(echo "$result" | grep '^MEM=' | cut -d= -f2-)
    OVF_NET_COUNT=$(echo "$result" | grep '^NET=' | cut -d= -f2-)
    OVF_OS_TYPE=$(echo "$result"   | grep '^OS='  | cut -d= -f2-)

    OVF_DISK_FILES=()
    while IFS= read -r line; do
        OVF_DISK_FILES+=("${line#FILE=}")
    done < <(echo "$result" | grep '^FILE=')

    OVF_DISK_CAPACITIES=()
    while IFS= read -r line; do
        OVF_DISK_CAPACITIES+=("${line#CAP=}")
    done < <(echo "$result" | grep '^CAP=')

    [[ -z "$OVF_VM_NAME" ]]    && OVF_VM_NAME="imported-vm"
    [[ ! "$OVF_VCPUS"      =~ ^[0-9]+$ ]] && OVF_VCPUS=1
    [[ ! "$OVF_MEMORY_MB"  =~ ^[0-9]+$ ]] && OVF_MEMORY_MB=1024
    [[ ! "$OVF_NET_COUNT"  =~ ^[0-9]+$ ]] && OVF_NET_COUNT=0

    case "$OVF_OS_TYPE" in
        linux)   OVF_OS_TYPE="l26"   ;;
        windows) OVF_OS_TYPE="win10" ;;
        *)       OVF_OS_TYPE="other" ;;
    esac

    [[ ${#OVF_DISK_FILES[@]} -gt 0 ]] || return 1
    return 0
}


# -------------------------------------------------------
# SELECT IMPORT OPTIONS  (dialogs — no terminal output)
# -------------------------------------------------------

select_import_options() {
    # VMID
    local suggested_vmid
    suggested_vmid=$(pvesh get /cluster/nextid 2>/dev/null || echo "100")

    while true; do
        NEW_VMID=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "VM ID")" \
            --inputbox "\n$(translate "Enter the VMID for the new VM:")  ($(translate "suggested:") $suggested_vmid)" \
            10 72 "$suggested_vmid" 3>&1 1>&2 2>&3)
        [[ -n "$NEW_VMID" ]] || return 1

        if ! [[ "$NEW_VMID" =~ ^[0-9]+$ ]]; then
            dialog --backtitle "$BACKTITLE" --title "$(translate "Invalid VMID")" \
                --msgbox "$(translate "VMID must be a number.")" 8 50
            continue
        fi

        if qm status "$NEW_VMID" &>/dev/null; then
            dialog --backtitle "$BACKTITLE" --title "$(translate "VMID in use")" \
                --msgbox "$(translate "VMID $NEW_VMID is already in use. Please choose another.")" 8 60
            continue
        fi
        break
    done

    # VM Name
    NEW_VM_NAME=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "VM Name")" \
        --inputbox "\n$(translate "Enter name for the imported VM:")" \
        10 72 "$OVF_VM_NAME" 3>&1 1>&2 2>&3)
    [[ -n "$NEW_VM_NAME" ]] || return 1

    # Storage
    local storage_list storage_opts=()
    storage_list=$(pvesm status -content images 2>/dev/null | awk 'NR>1 {print $1}')
    if [[ -z "$storage_list" ]]; then
        dialog --backtitle "$BACKTITLE" --title "$(translate "No storage")" \
            --msgbox "$(translate "No storage volumes available for VM images.")" 8 60
        return 1
    fi
    while IFS= read -r s; do
        storage_opts+=("$s" "")
    done <<< "$storage_list"

    STORAGE=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Select Storage")" \
        --menu "$(translate "Select storage for imported disk(s):")" \
        $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
        "${storage_opts[@]}" 3>&1 1>&2 2>&3)
    [[ -n "$STORAGE" ]] || return 1

    # Network bridge
    local bridge_opts=()
    while IFS= read -r br; do
        [[ -n "$br" ]] && bridge_opts+=("$br" "")
    done < <(ip link show type bridge 2>/dev/null | awk -F': ' '/^[0-9]+:/{print $2}' | sed 's/@.*//')

    if [[ ${#bridge_opts[@]} -gt 1 ]]; then
        BRIDGE=$(dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Network Bridge")" \
            --menu "$(translate "Select bridge for network interface(s):")" \
            $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
            "${bridge_opts[@]}" 3>&1 1>&2 2>&3)
        [[ -n "$BRIDGE" ]] || return 1
    elif [[ ${#bridge_opts[@]} -eq 1 ]]; then
        BRIDGE="${bridge_opts[0]}"
    fi

    return 0
}


# -------------------------------------------------------
# CONFIRM BEFORE IMPORT  (dialog)
# -------------------------------------------------------

confirm_import() {
    local disk_count="${#OVF_DISK_FILES[@]}"
    local disk_info="" i

    for i in "${!OVF_DISK_FILES[@]}"; do
        local cap="${OVF_DISK_CAPACITIES[$i]:-0}"
        disk_info+="\n  disk$((i+1)): ${OVF_DISK_FILES[$i]}  ($(human_bytes "$cap"))"
    done

    local msg
    msg="$(translate "New VM:") $NEW_VMID  ($NEW_VM_NAME)\n"
    msg+="$(translate "vCPUs:") $OVF_VCPUS   $(translate "Memory:") ${OVF_MEMORY_MB} MB   $(translate "OS type:") $OVF_OS_TYPE\n"
    msg+="$(translate "NICs:") $OVF_NET_COUNT   $(translate "Bridge:") $BRIDGE\n"
    msg+="$(translate "Storage:") $STORAGE\n"
    msg+="$(translate "Disks to import:") $disk_count${disk_info}\n\n"
    msg+="$(translate "Continue?")"

    dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Confirm Import")" \
        --yesno "$msg" 18 84 3>&1 1>&2 2>&3
}


# -------------------------------------------------------
# RUN IMPORT  (terminal output only — no dialogs)
# -------------------------------------------------------

run_import() {
    show_proxmenux_logo
    msg_title "$(translate "Import VM from OVA or OVF")"

    msg_ok "$(translate "VM:") $NEW_VMID ($NEW_VM_NAME)"
    msg_ok "$(translate "vCPUs:") $OVF_VCPUS    $(translate "Memory:") ${OVF_MEMORY_MB} MB    $(translate "OS:") $OVF_OS_TYPE"
    msg_ok "$(translate "Storage:") $STORAGE    $(translate "Bridge:") $BRIDGE    $(translate "NICs:") $OVF_NET_COUNT"
    echo ""

    # 1. Create VM shell
    msg_info "$(translate "Creating VM...")"
    if ! qm create "$NEW_VMID" \
            --name "$NEW_VM_NAME" \
            --memory "$OVF_MEMORY_MB" \
            --cores "$OVF_VCPUS" \
            --ostype "$OVF_OS_TYPE" \
            --scsihw lsi \
            --net0 "e1000,bridge=$BRIDGE" \
            &>/dev/null; then
        msg_error "$(translate "Failed to create VM") $NEW_VMID"
        return 1
    fi
    msg_ok "$(translate "VM shell created:") $NEW_VMID"

    # Add extra NICs (net0 already created above)
    local n
    for n in $(seq 1 $((OVF_NET_COUNT - 1))); do
        qm set "$NEW_VMID" "--net${n}" "e1000,bridge=$BRIDGE" &>/dev/null || true
    done
    [[ "$OVF_NET_COUNT" -gt 1 ]] && msg_ok "$(translate "Network interfaces added:") $OVF_NET_COUNT"

    # 2. Import disks
    local disk_count="${#OVF_DISK_FILES[@]}"
    local i disk_file src_path
    local TEMP_STATUS_FILE TEMP_DISK_FILE

    for i in "${!OVF_DISK_FILES[@]}"; do
        disk_file="${OVF_DISK_FILES[$i]}"
        src_path="$OVF_DIR/$disk_file"

        if [[ ! -f "$src_path" ]]; then
            msg_error "$(translate "Disk file not found:") $src_path"
            return 1
        fi

        echo ""
        msg_info "$(translate "Importing disk") $((i + 1))/$disk_count: $disk_file"
        msg_info2 "$(translate "Source:") $src_path"

        TEMP_STATUS_FILE=$(mktemp)
        TEMP_DISK_FILE=$(mktemp)

        (
            qm importdisk "$NEW_VMID" "$src_path" "$STORAGE" 2>&1
            echo $? > "$TEMP_STATUS_FILE"
        ) | while IFS= read -r line; do
            if [[ "$line" =~ transferred ]]; then
                local pct
                pct=$(echo "$line" | grep -oP "\d+\.\d+(?=%)")
                [[ -n "$pct" ]] && echo -ne "\r${TAB}${BL}- $(translate "Importing:") $disk_file -${CL} ${pct}%"
            elif [[ "$line" =~ successfully\ imported\ disk ]]; then
                echo "$line" | grep -oP "(?<=successfully imported disk ').*(?=')" > "$TEMP_DISK_FILE"
            fi
        done
        echo -ne "\n"

        local import_status
        import_status=$(cat "$TEMP_STATUS_FILE" 2>/dev/null)
        rm -f "$TEMP_STATUS_FILE"
        [[ -z "$import_status" ]] && import_status=1

        if [[ "$import_status" -ne 0 ]]; then
            msg_error "$(translate "Import failed for:") $disk_file"
            rm -f "$TEMP_DISK_FILE"
            return 1
        fi

        # Locate the unused disk entry in VM config
        local unused_id unused_disk
        unused_id=$(qm config "$NEW_VMID" | grep -E '^unused[0-9]+:' | tail -1 | cut -d: -f1)
        unused_disk=$(qm config "$NEW_VMID" | grep -E '^unused[0-9]+:' | tail -1 | cut -d: -f2- | xargs)
        rm -f "$TEMP_DISK_FILE"

        if [[ -z "$unused_disk" ]]; then
            msg_error "$(translate "Could not locate imported disk in VM config.")"
            return 1
        fi

        # Attach to scsi slot i
        if ! qm set "$NEW_VMID" "--scsi${i}" "$unused_disk" &>/dev/null; then
            msg_error "$(translate "Failed to attach disk as scsi$i.")"
            return 1
        fi

        # Remove the unused marker
        [[ -n "$unused_id" ]] && qm set "$NEW_VMID" --delete "$unused_id" &>/dev/null || true

        msg_ok "$(translate "Disk attached as:") scsi${i}  (${disk_file})"
    done

    # 3. Set boot disk
    echo ""
    msg_info "$(translate "Configuring boot order...")"
    if qm set "$NEW_VMID" --boot c --bootdisk "scsi0" &>/dev/null; then
        msg_ok "$(translate "Boot disk:") scsi0"
    fi

    return 0
}


# -------------------------------------------------------
# PRINT FINAL RESULT
# -------------------------------------------------------

print_import_result() {
    local disk_count="${#OVF_DISK_FILES[@]}"

    echo ""
    msg_title "$(translate "Import Summary")"

    msg_ok "$(translate "VM imported successfully")"
    msg_ok "$(translate "VM ID:") $NEW_VMID    $(translate "Name:") $NEW_VM_NAME"
    msg_ok "$(translate "vCPUs:") $OVF_VCPUS    $(translate "Memory:") ${OVF_MEMORY_MB} MB    $(translate "Disks:") $disk_count"
    msg_ok "$(translate "Storage:") $STORAGE    $(translate "Bridge:") $BRIDGE    $(translate "NICs:") $OVF_NET_COUNT"
    echo ""

    msg_ok "$(translate "To start the VM:") qm start $NEW_VMID"
    echo ""

    msg_title "$(translate "Manual steps recommended after import")"
    msg_info2 "$(translate "Network  :") $(translate "Verify bridge assignment and NIC model — change to VirtIO if guest drivers are available")"
    msg_info2 "$(translate "Firmware :") $(translate "Check BIOS/UEFI in Hardware > BIOS — must match what the original VM used")"
    msg_info2 "$(translate "Drivers  :") $(translate "If imported from ESXi: install qemu-guest-agent inside the guest OS")"
    msg_info2 "$(translate "Display  :") $(translate "Set Display > Graphic card (VGA, SPICE or VirtIO) to match the guest")"
    msg_info2 "$(translate "OS type  :") $(translate "Verify Options > OS Type — currently set to:") $OVF_OS_TYPE"
    echo ""
    msg_info2 "$(translate "Not imported:") $(translate "PCI passthrough, TPM state, cloud-init, snapshots, Proxmox-specific hooks")"
    echo ""
}


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------

main() {
    if ! command -v pveversion >/dev/null 2>&1; then
        dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
            --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
        exit 1
    fi

    for cmd in dialog qm pvesm qemu-img tar; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            dialog --backtitle "$BACKTITLE" --title "$(translate "Missing dependency")" \
                --msgbox "$(translate "Required command not found:") $cmd" 8 60
            exit 1
        fi
    done

    # Step 1: pick the OVA/OVF file (dialog)
    select_source_file || exit 0

    # Step 2: extract + parse (terminal output)
    show_proxmenux_logo
    msg_title "$(translate "Import VM from OVA or OVF")"

    msg_ok "$(translate "Source:") $SOURCE_FILE"
    echo ""

    prepare_ovf || {
        echo ""
        msg_success "$(translate "Press Enter to return...")"
        read -r
        exit 1
    }

    msg_info "$(translate "Parsing OVF descriptor...")"
    if ! parse_ovf "$OVF_FILE"; then
        msg_error "$(translate "Could not parse OVF file, or no disk image references found.")"
        echo ""
        msg_success "$(translate "Press Enter to return...")"
        read -r
        exit 1
    fi
    msg_ok "$(translate "OVF parsed:")"
    msg_info2 "  $(translate "Name:") $OVF_VM_NAME    $(translate "vCPUs:") $OVF_VCPUS    $(translate "Memory:") ${OVF_MEMORY_MB} MB"
    msg_info2 "  $(translate "Disks:") ${#OVF_DISK_FILES[@]}    $(translate "NICs:") $OVF_NET_COUNT    $(translate "OS hint:") $OVF_OS_TYPE"

    # Clean screen before returning to dialogs
    show_proxmenux_logo

    # Step 3: configure the new VM (dialogs)
    select_import_options || exit 0

    # Step 4: confirm (dialog)
    confirm_import || exit 0

    # Step 5: do the import (terminal output only)
    if run_import; then
        print_import_result
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        exit 0
    else
        echo ""
        msg_error "$(translate "Import failed. VM $NEW_VMID may be in partial state.")"
        # Offer to clean up the orphan VM. Most users want this — it
        # otherwise sits in the PVE UI as a half-broken entry that the
        # user has to clean up manually with the command we hint at. Audit
        # Tier 6 — `import_vm_ova_ovf.sh` VM huérfana tras fallo.
        if dialog --backtitle "$BACKTITLE" \
            --title "$(translate "Cleanup partial VM?")" \
            --yesno "$(translate "Remove the partial VM ($NEW_VMID) and its imported disks?")" 8 60; then
            clear
            msg_info "$(translate "Removing partial VM") $NEW_VMID..."
            if qm destroy "$NEW_VMID" --destroy-unreferenced-disks 1 &>/dev/null; then
                msg_ok "$(translate "Partial VM removed")"
            else
                msg_warn "$(translate "Could not remove VM automatically. Run manually:") qm destroy $NEW_VMID --destroy-unreferenced-disks 1"
            fi
        else
            msg_info2 "$(translate "To remove partial VM:") qm destroy $NEW_VMID --destroy-unreferenced-disks 1"
        fi
        echo ""
        msg_success "$(translate "Press Enter to return...")"
        read -r
        exit 1
    fi
}

main "$@"
