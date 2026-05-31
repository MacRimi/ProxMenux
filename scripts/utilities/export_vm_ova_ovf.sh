#!/bin/bash
# ==========================================================
# ProxMenux - Export VM to OVA or OVF
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Exports a Proxmox VM to OVA (single TAR archive) or OVF
# (descriptor + VMDK files) using the standard DMTF OVF schema.
# The exported package is portable and importable on VMware
# (ESXi / Workstation / Fusion), VirtualBox and Proxmox itself
# (via the matching import_vm_ova_ovf.sh).
#
# Features:
#   - Dependency check (dialog, qm, pvesm, qemu-img, tar, sha1sum).
#   - VM picker from 'qm list'; offers graceful shutdown (qm
#     shutdown --timeout 120) or force-stop (qm stop) for running
#     VMs.
#   - Format selector: OVA (single portable file) or OVF
#     (descriptor + external VMDK files).
#   - Destination directory selector (presets + manual path), with
#     write-access and free-space pre-flight (~120% of virtual disk
#     for OVF, ~220% for OVA).
#   - Disk inventory excludes CD-ROMs and cloud-init drives.
#   - Conversion via 'qemu-img convert -O vmdk -o subformat=
#     streamOptimized' (single-pass VMware-friendly format).
#   - OVF descriptor with vCPU / memory / SCSI controller / disks /
#     NIC count, plus SHA1 manifest (.mf) of all files.
#   - Temporary working directory cleaned on EXIT via trap.
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Missing dependency")" \
            --msgbox "$(translate "Required command not found:") $cmd" 8 60
        return 1
    fi
    return 0
}

human_bytes() {
    local bytes="$1"
    local units=("B" "KB" "MB" "GB" "TB" "PB")
    local idx=0
    local value="$bytes"

    [[ -z "$value" || ! "$value" =~ ^[0-9]+$ ]] && { echo "N/A"; return; }

    while [[ "$value" -ge 1024 && "$idx" -lt 5 ]]; do
        value=$((value / 1024))
        idx=$((idx + 1))
    done

    echo "${value}${units[$idx]}"
}

sanitize_name() {
    local raw="$1"
    local out
    out=$(echo "$raw" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-zA-Z0-9._-]/_/g' | sed 's/__*/_/g' | sed 's/^_\+//;s/_\+$//')
    [[ -z "$out" ]] && out="vm"
    echo "$out"
}

xml_escape() {
    local s="$1"
    s=${s//&/&amp;}
    s=${s//</&lt;}
    s=${s//>/&gt;}
    s=${s//\"/&quot;}
    s=${s//\'/&apos;}
    echo "$s"
}

validate_destination_dir() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Directory error")" \
            --msgbox "$(translate "Destination directory does not exist:")\n$dir" 8 74
        return 1
    fi

    if [[ ! -w "$dir" ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "Permission error")" \
            --msgbox "$(translate "Destination directory is not writable:")\n$dir" 8 70
        return 1
    fi

    return 0
}

select_vm() {
    local options=()
    local line vmid name status

    while read -r line; do
        [[ -z "$line" ]] && continue
        vmid=$(echo "$line" | awk '{print $1}')
        name=$(echo "$line" | awk '{print $2}')
        status=$(echo "$line" | awk '{print $3}')
        [[ -z "$vmid" || "$vmid" == "VMID" ]] && continue
        [[ -z "$name" ]] && name="vm-${vmid}"
        options+=("$vmid" "$name [$status]")
    done < <(qm list 2>/dev/null)

    if [[ ${#options[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(translate "No VMs found")" \
            --msgbox "$(translate "No virtual machines were found on this host.")" 8 60
        return 1
    fi

    VMID=$(dialog --backtitle "ProxMenux" --title "$(translate "Export VM to OVA or OVF")" \
        --menu "$(translate "Select VM to export:")" 20 80 12 \
        "${options[@]}" 3>&1 1>&2 2>&3)

    [[ -n "$VMID" ]] || return 1
    return 0
}

ensure_vm_stopped() {
    local status
    status=$(qm status "$VMID" 2>/dev/null | awk '{print $2}')

    if [[ "$status" == "stopped" ]]; then
        return 0
    fi

    if ! dialog --backtitle "ProxMenux" --title "$(translate "VM is running")" --yesno \
        "$(translate "For a consistent export, the VM should be stopped.")\n\n$(translate "Do you want ProxMenux to stop it now?")" 10 70; then
        return 1
    fi

    qm shutdown "$VMID" --timeout 120 >/dev/null 2>&1 || true

    local i
    for i in $(seq 1 60); do
        status=$(qm status "$VMID" 2>/dev/null | awk '{print $2}')
        [[ "$status" == "stopped" ]] && return 0
        sleep 2
    done

    if dialog --backtitle "ProxMenux" --title "$(translate "Shutdown timeout")" --yesno \
        "$(translate "Graceful shutdown timed out.")\n\n$(translate "Force stop VM now?")" 10 60; then
        qm stop "$VMID" >/dev/null 2>&1 || true
        sleep 2
        status=$(qm status "$VMID" 2>/dev/null | awk '{print $2}')
        [[ "$status" == "stopped" ]] && return 0
    fi

    dialog --backtitle "ProxMenux" --title "$(translate "Cannot continue")" \
        --msgbox "$(translate "VM is still running. Export cancelled.")" 8 60
    return 1
}

select_export_mode() {
    EXPORT_MODE=$(dialog --backtitle "ProxMenux" --title "$(translate "Export Format")" \
        --menu "$(translate "Select export format:")" 14 70 4 \
        "ova" "$(translate "OVA (single portable file)")" \
        "ovf" "$(translate "OVF (descriptor + VMDK files)")" \
        3>&1 1>&2 2>&3)
    [[ -n "$EXPORT_MODE" ]] || return 1
    return 0
}

select_destination_dir() {
    local dump_dir="/var/lib/vz/dump"
    local iso_dir="/var/lib/vz/template/iso"
    local options=(
        "1" "$dump_dir          [$(translate "recommended")]"
        "2" "$iso_dir  [$(translate "recommended")]"
        "M" "$(translate "Manual path entry")"
    )

    while true; do
        local choice
        choice=$(dialog --backtitle "ProxMenux" --title "$(translate "Destination Directory")" \
            --menu "$(translate "Select where to export VM files (OVA/OVF + temporary workspace):")" \
            16 84 8 "${options[@]}" 3>&1 1>&2 2>&3)

        [[ -n "$choice" ]] || return 1

        case "$choice" in
            M)
                DEST_DIR=$(dialog --backtitle "ProxMenux" --title "$(translate "Manual destination path")" \
                    --inputbox "$(translate "Enter destination directory for exported file(s):")" \
                    10 90 "/var/lib/vz/dump" 3>&1 1>&2 2>&3)
                [[ -n "$DEST_DIR" ]] || continue
                if [[ ! -d "$DEST_DIR" ]]; then
                    if dialog --backtitle "ProxMenux" --title "$(translate "Create directory")" \
                        --yesno "$(translate "The selected directory does not exist:")\n$DEST_DIR\n\n$(translate "Do you want to create it now?")" \
                        11 80; then
                        if ! mkdir -p "$DEST_DIR" 2>/dev/null; then
                            dialog --backtitle "ProxMenux" --title "$(translate "Directory error")" \
                                --msgbox "$(translate "Could not create destination directory:")\n$DEST_DIR" 8 74
                            continue
                        fi
                    else
                        continue
                    fi
                fi
                validate_destination_dir "$DEST_DIR" || continue
                return 0
                ;;
            1)
                DEST_DIR="$dump_dir"
                validate_destination_dir "$DEST_DIR" || continue
                return 0
                ;;
            2)
                DEST_DIR="$iso_dir"
                validate_destination_dir "$DEST_DIR" || continue
                return 0
                ;;
            *)
                continue
                ;;
        esac
    done
}

get_vm_metadata() {
    VM_CONF=$(qm config "$VMID" 2>/dev/null) || return 1

    VM_NAME=$(echo "$VM_CONF" | awk -F': ' '/^name:/{print $2; exit}')
    [[ -z "$VM_NAME" ]] && VM_NAME="vm-${VMID}"

    VM_MEMORY=$(echo "$VM_CONF" | awk -F': ' '/^memory:/{print $2; exit}')
    [[ -z "$VM_MEMORY" ]] && VM_MEMORY=1024

    VM_CORES=$(echo "$VM_CONF" | awk -F': ' '/^cores:/{print $2; exit}')
    VM_SOCKETS=$(echo "$VM_CONF" | awk -F': ' '/^sockets:/{print $2; exit}')
    [[ -z "$VM_CORES" ]] && VM_CORES=1
    [[ -z "$VM_SOCKETS" ]] && VM_SOCKETS=1
    VM_VCPUS=$((VM_CORES * VM_SOCKETS))

    VM_OSTYPE=$(echo "$VM_CONF" | awk -F': ' '/^ostype:/{print $2; exit}')
    case "$VM_OSTYPE" in
        l26|l24) VM_OS_DESC="Linux" ;;
        win11|win10|win8|win7|w2k8|w2k12|w2k16|w2k19|w2k22|wxp|w2k|w2k3)
            VM_OS_DESC="Windows"
            ;;
        *) VM_OS_DESC="Other" ;;
    esac

    NET_COUNT=$(echo "$VM_CONF" | grep -E '^net[0-9]+:' | wc -l)
}

get_virtual_size_bytes() {
    local src="$1"
    local bytes=""

    bytes=$(qemu-img info "$src" 2>/dev/null | sed -n 's/.*virtual size:.*(\([0-9]\+\) bytes).*/\1/p' | head -1)
    if [[ -n "$bytes" && "$bytes" =~ ^[0-9]+$ ]]; then
        echo "$bytes"
        return 0
    fi

    if [[ -b "$src" ]]; then
        bytes=$(blockdev --getsize64 "$src" 2>/dev/null || true)
        if [[ -n "$bytes" && "$bytes" =~ ^[0-9]+$ ]]; then
            echo "$bytes"
            return 0
        fi
    fi

    bytes=$(stat -c%s "$src" 2>/dev/null || true)
    if [[ -n "$bytes" && "$bytes" =~ ^[0-9]+$ ]]; then
        echo "$bytes"
        return 0
    fi

    echo "0"
    return 0
}

collect_vm_disks() {
    DISK_COUNT=0
    unset DISK_SLOTS DISK_SRCS DISK_VSIZES
    declare -ga DISK_SLOTS DISK_SRCS DISK_VSIZES

    local line slot value source src

    while IFS= read -r line; do
        if [[ "$line" =~ ^(scsi|sata|virtio|ide)[0-9]+: ]]; then
            slot="${line%%:*}"
            value="${line#*: }"

            [[ "$value" == *"media=cdrom"* ]] && continue
            [[ "$value" == *"cloudinit"* ]] && continue

            source="${value%%,*}"
            [[ -z "$source" || "$source" == "none" ]] && continue

            src=""
            if [[ "$source" == /dev/* || "$source" == /* ]]; then
                src="$source"
            elif [[ "$source" == *:* ]]; then
                src=$(pvesm path "$source" 2>/dev/null || true)
            fi

            if [[ -z "$src" || ! -e "$src" ]]; then
                continue
            fi

            DISK_SLOTS+=("$slot")
            DISK_SRCS+=("$src")
            DISK_VSIZES+=("$(get_virtual_size_bytes "$src")")
            DISK_COUNT=$((DISK_COUNT + 1))
        fi
    done <<< "$VM_CONF"

    [[ "$DISK_COUNT" -gt 0 ]] || return 1
    return 0
}

check_destination_space() {
    local total=0
    local i
    for i in "${DISK_VSIZES[@]}"; do
        [[ "$i" =~ ^[0-9]+$ ]] && total=$((total + i))
    done

    local factor=120
    [[ "$EXPORT_MODE" == "ova" ]] && factor=220
    REQUIRED_BYTES=$((total * factor / 100))

    AVAILABLE_BYTES=$(df -PB1 "$DEST_DIR" | awk 'NR==2{print $4}')
    [[ "$AVAILABLE_BYTES" =~ ^[0-9]+$ ]] || AVAILABLE_BYTES=0

    if [[ "$AVAILABLE_BYTES" -lt "$REQUIRED_BYTES" ]]; then
        if ! dialog --backtitle "ProxMenux" --title "$(translate "Low free space warning")" --yesno \
            "$(translate "Estimated required free space:") $(human_bytes "$REQUIRED_BYTES") ($REQUIRED_BYTES bytes)\n$(translate "Current free space:") $(human_bytes "$AVAILABLE_BYTES") ($AVAILABLE_BYTES bytes)\n\n$(translate "Do you want to continue anyway?")" 13 90; then
            return 1
        fi
    fi

    return 0
}

generate_ovf_descriptor() {
    local ovf_path="$1"
    local vm_name_xml os_desc_xml
    vm_name_xml=$(xml_escape "$VM_NAME")
    os_desc_xml=$(xml_escape "$VM_OS_DESC")

    {
        echo '<?xml version="1.0" encoding="UTF-8"?>'
        echo '<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1" xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1" xmlns:rasd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData" xmlns:vssd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData">'
        echo '  <References>'
    } > "$ovf_path"

    local idx file_id disk_id file_name file_size capacity
    for idx in "${!EXPORT_DISK_FILES[@]}"; do
        file_id="file$((idx + 1))"
        file_name="${EXPORT_DISK_FILES[$idx]}"
        file_size=$(stat -c%s "$WORK_DIR/$file_name")
        echo "    <File ovf:id=\"$file_id\" ovf:href=\"$file_name\" ovf:size=\"$file_size\"/>" >> "$ovf_path"
    done

    {
        echo '  </References>'
        echo '  <DiskSection>'
        echo '    <Info>Virtual disk information</Info>'
    } >> "$ovf_path"

    for idx in "${!EXPORT_DISK_FILES[@]}"; do
        file_id="file$((idx + 1))"
        disk_id="vmdisk$((idx + 1))"
        capacity="${DISK_VSIZES[$idx]}"
        [[ -z "$capacity" || "$capacity" -le 0 ]] && capacity=$(stat -c%s "$WORK_DIR/${EXPORT_DISK_FILES[$idx]}")
        echo "    <Disk ovf:diskId=\"$disk_id\" ovf:fileRef=\"$file_id\" ovf:capacity=\"$capacity\" ovf:capacityAllocationUnits=\"byte\" ovf:format=\"http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized\"/>" >> "$ovf_path"
    done

    {
        echo '  </DiskSection>'
        echo "  <VirtualSystem ovf:id=\"$(sanitize_name "$VM_NAME")\">"
        echo '    <Info>A virtual machine</Info>'
        echo "    <Name>$vm_name_xml</Name>"
        echo '    <OperatingSystemSection ovf:id="94">'
        echo '      <Info>Guest operating system</Info>'
        echo "      <Description>$os_desc_xml</Description>"
        echo '    </OperatingSystemSection>'
        echo '    <VirtualHardwareSection>'
        echo '      <Info>Virtual hardware requirements</Info>'
        echo '      <System>'
        echo '        <vssd:ElementName>Virtual Hardware Family</vssd:ElementName>'
        echo '        <vssd:InstanceID>0</vssd:InstanceID>'
        echo '        <vssd:VirtualSystemIdentifier>vm</vssd:VirtualSystemIdentifier>'
        echo '        <vssd:VirtualSystemType>vmx-14</vssd:VirtualSystemType>'
        echo '      </System>'
        echo '      <Item>'
        echo '        <rasd:AllocationUnits>hertz * 10^6</rasd:AllocationUnits>'
        echo '        <rasd:Description>Number of Virtual CPUs</rasd:Description>'
        echo '        <rasd:ElementName>Virtual CPU(s)</rasd:ElementName>'
        echo '        <rasd:InstanceID>1</rasd:InstanceID>'
        echo "        <rasd:VirtualQuantity>$VM_VCPUS</rasd:VirtualQuantity>"
        echo '        <rasd:ResourceType>3</rasd:ResourceType>'
        echo '      </Item>'
        echo '      <Item>'
        echo '        <rasd:AllocationUnits>byte * 2^20</rasd:AllocationUnits>'
        echo '        <rasd:Description>Memory Size</rasd:Description>'
        echo '        <rasd:ElementName>Memory</rasd:ElementName>'
        echo '        <rasd:InstanceID>2</rasd:InstanceID>'
        echo "        <rasd:VirtualQuantity>$VM_MEMORY</rasd:VirtualQuantity>"
        echo '        <rasd:ResourceType>4</rasd:ResourceType>'
        echo '      </Item>'
        echo '      <Item>'
        echo '        <rasd:Address>0</rasd:Address>'
        echo '        <rasd:Description>SCSI Controller</rasd:Description>'
        echo '        <rasd:ElementName>SCSI Controller 0</rasd:ElementName>'
        echo '        <rasd:InstanceID>10</rasd:InstanceID>'
        echo '        <rasd:ResourceSubType>lsilogic</rasd:ResourceSubType>'
        echo '        <rasd:ResourceType>6</rasd:ResourceType>'
        echo '      </Item>'
    } >> "$ovf_path"

    for idx in "${!EXPORT_DISK_FILES[@]}"; do
        disk_id="vmdisk$((idx + 1))"
        echo '      <Item>' >> "$ovf_path"
        echo "        <rasd:AddressOnParent>$idx</rasd:AddressOnParent>" >> "$ovf_path"
        echo '        <rasd:Description>Hard disk</rasd:Description>' >> "$ovf_path"
        echo "        <rasd:ElementName>Hard disk $((idx + 1))</rasd:ElementName>" >> "$ovf_path"
        echo "        <rasd:HostResource>ovf:/disk/$disk_id</rasd:HostResource>" >> "$ovf_path"
        echo "        <rasd:InstanceID>$((200 + idx + 1))</rasd:InstanceID>" >> "$ovf_path"
        echo '        <rasd:Parent>10</rasd:Parent>' >> "$ovf_path"
        echo '        <rasd:ResourceType>17</rasd:ResourceType>' >> "$ovf_path"
        echo '      </Item>' >> "$ovf_path"
    done

    if [[ "$NET_COUNT" -gt 0 ]]; then
        local n
        for n in $(seq 1 "$NET_COUNT"); do
            {
                echo '      <Item>'
                echo '        <rasd:AutomaticAllocation>true</rasd:AutomaticAllocation>'
                echo '        <rasd:Connection>VM Network</rasd:Connection>'
                echo "        <rasd:ElementName>Ethernet adapter $n</rasd:ElementName>"
                echo "        <rasd:InstanceID>$((300 + n))</rasd:InstanceID>"
                echo '        <rasd:ResourceType>10</rasd:ResourceType>'
                echo '      </Item>'
            } >> "$ovf_path"
        done
    fi

    {
        echo '    </VirtualHardwareSection>'
        echo '  </VirtualSystem>'
        echo '</Envelope>'
    } >> "$ovf_path"
}

generate_manifest() {
    local mf_path="$1"
    shift
    local files=("$@")
    : > "$mf_path"

    local f hash
    for f in "${files[@]}"; do
        hash=$(sha1sum "$WORK_DIR/$f" | awk '{print $1}')
        echo "SHA1($f)= $hash" >> "$mf_path"
    done
}

print_export_result() {
    local mode="$1"
    local path="$2"

    echo ""
    msg_title "$(translate "Export Summary")"

    msg_ok "$(translate "VM:") ${VMID} — ${VM_NAME}"
    msg_ok "$(translate "vCPUs:") ${VM_VCPUS}    $(translate "Memory:") ${VM_MEMORY} MB    $(translate "Disks exported:") ${DISK_COUNT}"
    echo ""

    if [[ "$mode" == "ova" ]]; then
        local ova_size ova_sha1
        ova_size=$(stat -c%s "$path" 2>/dev/null || echo 0)
        ova_sha1=$(sha1sum "$path" 2>/dev/null | awk '{print $1}')
        msg_ok "$(translate "Format:") OVA — $(translate "single portable archive")"
        msg_ok "$(translate "File:") $path"
        msg_ok "$(translate "Size:") $(human_bytes "$ova_size")  (${ova_size} $(translate "bytes"))"
        msg_ok "SHA1: ${ova_sha1}"
    else
        local fsz total_size=0 f
        msg_ok "$(translate "Format:") OVF — $(translate "descriptor + VMDK files")"
        msg_ok "$(translate "Directory:") $path"
        for f in "${EXPORT_DISK_FILES[@]}"; do
            fsz=$(stat -c%s "$path/$f" 2>/dev/null || echo 0)
            total_size=$((total_size + fsz))
            msg_info2 "  ${f}  [$(human_bytes "$fsz")]"
        done
        msg_ok "$(translate "Total size:") $(human_bytes "$total_size")"
    fi

    echo ""
    msg_ok "$(translate "Compatible with:") VMware ESXi 6.7+ (vmx-14)  ·  VMware Workstation / Fusion  ·  VirtualBox  ·  Proxmox VE"
    msg_info2 "$(translate "Not portable:") $(translate "PCI passthrough, TPM state, cloud-init configuration, Proxmox hooks")"
    echo ""
}

run_export() {
    show_proxmenux_logo
    msg_title "$(translate "Export VM to OVA or OVF")"

    msg_ok "$(translate "VM selected:") $VMID ($VM_NAME)"
    msg_ok "$(translate "Export mode:") ${EXPORT_MODE^^}"
    msg_ok "$(translate "Destination:") $DEST_DIR"

    local ts vm_safe base_name
    ts=$(date +%Y%m%d_%H%M%S)
    vm_safe=$(sanitize_name "$VM_NAME")
    base_name="${vm_safe}-${VMID}-${ts}"

    WORK_DIR=$(mktemp -d "$DEST_DIR/.ovaovf-${base_name}-XXXXXX")
    if [[ ! -d "$WORK_DIR" ]]; then
        msg_error "$(translate "Could not create temporary working directory.")"
        return 1
    fi

    msg_ok "$(translate "Working directory:") $WORK_DIR"

    # Clean up temp dir on unexpected exit (Ctrl+C, unhandled error, etc.)
    trap 'rm -rf "$WORK_DIR" 2>/dev/null' EXIT

    declare -ga EXPORT_DISK_FILES
    EXPORT_DISK_FILES=()

    local i src dst disk_name
    for i in "${!DISK_SRCS[@]}"; do
        src="${DISK_SRCS[$i]}"
        disk_name="${base_name}-disk$((i + 1)).vmdk"
        dst="$WORK_DIR/$disk_name"

        echo ""
        msg_info "$(translate "Converting disk") $((i + 1))/$DISK_COUNT: ${DISK_SLOTS[$i]}"
        msg_info2 "$(translate "Source:") $src"

        if ! qemu-img convert -p -O vmdk -o subformat=streamOptimized "$src" "$dst"; then
            msg_error "$(translate "Disk conversion failed for") ${DISK_SLOTS[$i]}"
            return 1
        fi

        # Validate the produced VMDK. `qemu-img check` reports leaks /
        # corrupted clusters that the convert exit code might not have
        # surfaced (silent partial-write under disk pressure, qemu-img
        # bug, etc.). Audit Tier 7 — `export_vm_ova_ovf.sh` no valida
        # integridad del VMDK convertido.
        if command -v qemu-img >/dev/null 2>&1; then
            if ! qemu-img check -q "$dst" 2>/dev/null; then
                msg_error "$(translate "Integrity check failed on") $disk_name"
                return 1
            fi
        fi

        EXPORT_DISK_FILES+=("$disk_name")
        msg_ok "$(translate "Converted + verified:") $disk_name"
    done

    local ovf_file mf_file
    ovf_file="${base_name}.ovf"
    mf_file="${base_name}.mf"

    msg_info "$(translate "Generating OVF descriptor...")"
    generate_ovf_descriptor "$WORK_DIR/$ovf_file"

    msg_info "$(translate "Generating manifest...")"
    generate_manifest "$WORK_DIR/$mf_file" "$ovf_file" "${EXPORT_DISK_FILES[@]}"

    if [[ "$EXPORT_MODE" == "ovf" ]]; then
        local final_dir="$DEST_DIR/${base_name}-ovf"
        rm -rf "$final_dir"
        trap - EXIT
        mv "$WORK_DIR" "$final_dir"

        print_export_result "ovf" "$final_dir"
        return 0
    fi

    local ova_path="$DEST_DIR/${base_name}.ova"
    msg_info "$(translate "Packaging OVA file...")"

    if ! tar -C "$WORK_DIR" -cf "$ova_path" "$ovf_file" "$mf_file" "${EXPORT_DISK_FILES[@]}"; then
        msg_error "$(translate "Failed to create OVA archive.")"
        return 1
    fi

    trap - EXIT
    rm -rf "$WORK_DIR"

    print_export_result "ova" "$ova_path"
    return 0
}

main() {
    require_cmd dialog || exit 1
    require_cmd qm || exit 1
    require_cmd pvesm || exit 1
    require_cmd qemu-img || exit 1
    require_cmd tar || exit 1
    require_cmd sha1sum || exit 1

    if ! command -v pveversion >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
            --msgbox "$(translate "This script must be run on a Proxmox host.")" 8 60
        exit 1
    fi

    select_vm || exit 0
    ensure_vm_stopped || exit 0
    select_export_mode || exit 0
    select_destination_dir || exit 0

    get_vm_metadata || {
        dialog --backtitle "ProxMenux" --title "$(translate "Error")" \
            --msgbox "$(translate "Could not read VM configuration.")" 8 60
        exit 1
    }

    collect_vm_disks || {
        dialog --backtitle "ProxMenux" --title "$(translate "No exportable disks")" \
            --msgbox "$(translate "No exportable VM disks were found (CD-ROM/cloud-init are excluded).")" 9 80
        exit 1
    }

    check_destination_space || exit 0

    if ! dialog --backtitle "ProxMenux" --title "$(translate "Confirm export")" --yesno \
        "$(translate "VM:") $VMID ($VM_NAME)\n$(translate "Disks to export:") $DISK_COUNT\n$(translate "Format:") ${EXPORT_MODE^^}\n$(translate "Destination:") $DEST_DIR\n\n$(translate "Continue?")" 13 80; then
        exit 0
    fi

    if run_export; then
        echo ""
        msg_success "$(translate "Press Enter to return...")"
        read -r
        exit 0
    else
        echo ""
        msg_error "$(translate "Export failed.")"
        msg_info2 "$(translate "Temporary working directory (if present):") $WORK_DIR"
        msg_success "$(translate "Press Enter to return...")"
        read -r
        exit 1
    fi
}

main "$@"
