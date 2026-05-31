#!/bin/bash
# ==========================================================
# ProxMenux - Add Controller or NVMe PCIe to VM
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 06/04/2026
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
TOOLS_JSON="$BASE_DIR/installed_tools.json"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
  LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
  UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
  UTILS_FILE="$BASE_DIR/utils.sh"
fi

LOG_FILE="/tmp/proxmenux_add_controller_nvme_vm.log"
screen_capture="/tmp/proxmenux_add_controller_nvme_vm_screen_$$.txt"

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh"
fi
load_language
initialize_cache

SELECTED_VMID=""
SELECTED_VM_NAME=""
declare -a SELECTED_CONTROLLER_PCIS=()
IOMMU_PENDING_REBOOT=0
IOMMU_ALREADY_ACTIVE=0
WIZARD_CONFLICT_POLICY=""
WIZARD_CONFLICT_SCOPE=""

set_title() {
  show_proxmenux_logo
  msg_title "$(translate "Add Controller or NVMe PCIe to VM")"
}

ensure_tools_json() {
  [[ -f "$TOOLS_JSON" ]] || echo "{}" > "$TOOLS_JSON"
}

register_tool() {
  local tool="$1"
  local state="$2"
  command -v jq >/dev/null 2>&1 || return 0
  ensure_tools_json
  jq --arg t "$tool" --argjson v "$state" \
    '.[$t]=$v' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" \
    && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

register_vfio_iommu_tool() {
  register_tool "vfio_iommu" true || true
}

enable_iommu_cmdline() {
  local silent="${1:-}"
  local cpu_vendor iommu_param
  cpu_vendor=$(grep -m1 "vendor_id" /proc/cpuinfo 2>/dev/null | awk '{print $3}')

  if [[ "$cpu_vendor" == "GenuineIntel" ]]; then
    iommu_param="intel_iommu=on"
    [[ "$silent" != "silent" ]] && msg_info "$(translate "Intel CPU detected")"
  elif [[ "$cpu_vendor" == "AuthenticAMD" ]]; then
    iommu_param="amd_iommu=on"
    [[ "$silent" != "silent" ]] && msg_info "$(translate "AMD CPU detected")"
  else
    msg_error "$(translate "Unknown CPU vendor. Cannot determine IOMMU parameter.")"
    return 1
  fi

  local cmdline_file="/etc/kernel/cmdline"
  local grub_file="/etc/default/grub"

  if [[ -f "$cmdline_file" ]] && grep -qE 'root=ZFS=|root=ZFS/' "$cmdline_file" 2>/dev/null; then
    if ! grep -q "$iommu_param" "$cmdline_file" || ! grep -q "iommu=pt" "$cmdline_file"; then
      cp "$cmdline_file" "${cmdline_file}.bak.$(date +%Y%m%d_%H%M%S)"
      sed -i "s|\\s*$| ${iommu_param} iommu=pt|" "$cmdline_file"
      proxmox-boot-tool refresh >/dev/null 2>&1 || true
      [[ "$silent" != "silent" ]] && msg_ok "$(translate "IOMMU parameters added to /etc/kernel/cmdline")"
    else
      [[ "$silent" != "silent" ]] && msg_ok "$(translate "IOMMU already configured in /etc/kernel/cmdline")"
    fi
  elif [[ -f "$grub_file" ]]; then
    if ! grep -q "$iommu_param" "$grub_file" || ! grep -q "iommu=pt" "$grub_file"; then
      cp "$grub_file" "${grub_file}.bak.$(date +%Y%m%d_%H%M%S)"
      sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$| ${iommu_param} iommu=pt\"|" "$grub_file"
      update-grub >/dev/null 2>&1 || true
      [[ "$silent" != "silent" ]] && msg_ok "$(translate "IOMMU parameters added to GRUB")"
    else
      [[ "$silent" != "silent" ]] && msg_ok "$(translate "IOMMU already configured in GRUB")"
    fi
  else
    msg_error "$(translate "Neither /etc/kernel/cmdline nor /etc/default/grub found.")"
    return 1
  fi
}

check_iommu_or_offer_enable() {
  if [[ "${IOMMU_PENDING_REBOOT:-0}" == "1" ]]; then
    register_vfio_iommu_tool
    return 0
  fi

  if grep -qE 'intel_iommu=on|amd_iommu=on' /etc/kernel/cmdline 2>/dev/null || \
     grep -qE 'intel_iommu=on|amd_iommu=on' /etc/default/grub 2>/dev/null; then
    IOMMU_PENDING_REBOOT=1
    register_vfio_iommu_tool

    return 0
  fi

  if declare -F _pci_is_iommu_active >/dev/null 2>&1 && _pci_is_iommu_active; then
    IOMMU_ALREADY_ACTIVE=1
    register_vfio_iommu_tool
    return 0
  fi

  if grep -qE 'intel_iommu=on|amd_iommu=on' /proc/cmdline 2>/dev/null && \
     [[ -d /sys/kernel/iommu_groups ]] && \
     [[ -n "$(ls /sys/kernel/iommu_groups/ 2>/dev/null)" ]]; then
    IOMMU_ALREADY_ACTIVE=1
    register_vfio_iommu_tool
    return 0
  fi

  local msg
  msg="\n$(translate "IOMMU is not active on this system.")\n\n"
  msg+="$(translate "Controller/NVMe passthrough to VMs requires IOMMU to be enabled in the kernel.")\n\n"
  msg+="$(translate "Do you want to enable IOMMU now?")\n\n"
  msg+="$(translate "Note: A system reboot will be required after enabling IOMMU.")\n"
  msg+="$(translate "Configuration can continue now and will be effective after reboot.")"

  dialog --backtitle "ProxMenux" \
    --title "$(translate "IOMMU Required")" \
    --yesno "$msg" 15 74
  local response=$?

  [[ $response -ne 0 ]] && return 1

  set_title
  msg_title "$(translate "Enabling IOMMU")"
  if ! enable_iommu_cmdline; then
    echo
    msg_error "$(translate "Failed to configure IOMMU automatically.")"
    msg_success "$(translate "Press Enter to continue...")"
    read -r
    return 1
  fi

  register_vfio_iommu_tool
  IOMMU_PENDING_REBOOT=1
  return 0
}

select_target_vm() {
  local -a vm_menu=()
  local line vmid vmname vmstatus vm_machine status_label
  local max_name_len=0 padded_name

  while IFS= read -r line; do
    vmid=$(awk '{print $1}' <<< "$line")
    vmname=$(awk '{print $2}' <<< "$line")
    [[ -z "$vmid" || "$vmid" == "VMID" ]] && continue
    [[ -f "/etc/pve/qemu-server/${vmid}.conf" ]] || continue
    [[ ${#vmname} -gt $max_name_len ]] && max_name_len=${#vmname}
  done < <(qm list 2>/dev/null)

  while IFS= read -r line; do
    vmid=$(awk '{print $1}' <<< "$line")
    vmname=$(awk '{print $2}' <<< "$line")
    vmstatus=$(awk '{print $3}' <<< "$line")
    [[ -z "$vmid" || "$vmid" == "VMID" ]] && continue
    [[ -f "/etc/pve/qemu-server/${vmid}.conf" ]] || continue

    vm_machine=$(qm config "$vmid" 2>/dev/null | awk -F': ' '/^machine:/ {print $2}')
    [[ -z "$vm_machine" ]] && vm_machine="unknown"
    status_label="${vmstatus}, ${vm_machine}"
    printf -v padded_name "%-${max_name_len}s" "$vmname"
    vm_menu+=("$vmid" "${padded_name}  [${status_label}]")
  done < <(qm list 2>/dev/null)
  if [[ ${#vm_menu[@]} -eq 0 ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate "Add Controller or NVMe PCIe to VM")" \
      --msgbox "\n$(translate "No VMs available on this host.")" 8 64
    return 1
  fi

  SELECTED_VMID=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "Select VM")" \
    --menu "\n$(translate "Select the target VM for PCI passthrough:")" 20 82 12 \
    "${vm_menu[@]}" \
    2>&1 >/dev/tty) || return 1

  SELECTED_VM_NAME=$(qm config "$SELECTED_VMID" 2>/dev/null | awk '/^name:/ {print $2}')
  [[ -z "$SELECTED_VM_NAME" ]] && SELECTED_VM_NAME="VM-${SELECTED_VMID}"
  return 0
}

validate_vm_requirements() {
  local status
  status=$(qm status "$SELECTED_VMID" 2>/dev/null | awk '{print $2}')
  if [[ "$status" == "running" ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate "VM Must Be Stopped")" \
      --msgbox "\n$(translate "The selected VM is running.")\n\n$(translate "Stop it first and run this option again.")" 10 72
    return 1
  fi

  if ! _vm_is_q35 "$SELECTED_VMID"; then
    dialog --backtitle "ProxMenux" --colors \
      --title "$(translate "Incompatible Machine Type")" \
      --msgbox "\n\Zb\Z1$(translate "Controller/NVMe passthrough requires machine type q35.")\Zn\n\n$(translate "Selected VM"): ${SELECTED_VM_NAME} (${SELECTED_VMID})\n\n$(translate "Edit the VM machine type to q35 and try again.")" 12 80
    return 1
  fi

  check_iommu_or_offer_enable || return 1

  return 0
}

select_controller_nvme() {
  # Show progress during potentially slow PCIe + disk detection
  set_title
  msg_info "$(translate "Analyzing system for available PCIe storage devices...")"

  _refresh_host_storage_cache

  local -a menu_items=()
  local blocked_report=""
  local pci_path pci_full class_hex name controller_desc disk state slot_base
  local -a controller_disks=()
  local safe_count=0 blocked_count=0 hidden_target_count=0

  while IFS= read -r pci_path; do
    pci_full=$(basename "$pci_path")
    class_hex=$(cat "$pci_path/class" 2>/dev/null | sed 's/^0x//')
    [[ -z "$class_hex" ]] && continue
    [[ "${class_hex:0:2}" != "01" ]] && continue
    slot_base=$(_pci_slot_base "$pci_full")

    # Already attached to target VM: hide from selection.
    if _vm_has_pci_slot "$SELECTED_VMID" "$slot_base"; then
      hidden_target_count=$((hidden_target_count + 1))
      continue
    fi

    name=$(lspci -nn -s "${pci_full#0000:}" 2>/dev/null | sed 's/^[^ ]* //')
    [[ -z "$name" ]] && name="$(translate "Unknown storage controller")"

    controller_disks=()
    while IFS= read -r disk; do
      [[ -z "$disk" ]] && continue
      _array_contains "$disk" "${controller_disks[@]}" || controller_disks+=("$disk")
    done < <(_controller_block_devices "$pci_full")

    # blocked_reasons: system disk OR disk in RUNNING guest → hide controller
    # warn_reasons:   disk in STOPPED guest only → show with ⚠ but allow selection
    local -a blocked_reasons=()
    local -a warn_reasons=()
    for disk in "${controller_disks[@]}"; do
      if _disk_is_host_system_used "$disk"; then
        blocked_reasons+=("${disk} (${DISK_USAGE_REASON})")
      elif _disk_used_in_guest_configs "$disk"; then
        if _disk_used_in_running_guest "$disk"; then
          blocked_reasons+=("${disk} ($(translate "In use by running VM/LXC — stop it first"))")
        else
          warn_reasons+=("$disk")
        fi
      fi
    done

    if [[ ${#blocked_reasons[@]} -gt 0 ]]; then
      blocked_count=$((blocked_count + 1))
      blocked_report+="  •  ${pci_full} — $(_shorten_text "$name" 56)\n"
      continue
    fi

    local short_name display_name
    display_name=$(_pci_storage_display_name "$pci_full")
    short_name=$(_shorten_text "$display_name" 56)

    local assigned_suffix=""
    if [[ -n "$(_pci_assigned_vm_ids "$pci_full" "$SELECTED_VMID" 2>/dev/null | head -1)" ]]; then
      assigned_suffix=" | $(translate "Assigned to VM")"
    fi

    # Warn if some disks are referenced in stopped VM/CT configs
    local warn_suffix=""
    if [[ ${#warn_reasons[@]} -gt 0 ]]; then
      warn_suffix=" ⚠"
    fi

    controller_desc="${short_name}${assigned_suffix}${warn_suffix}"

    state="off"
    menu_items+=("$pci_full" "$controller_desc" "$state")
    safe_count=$((safe_count + 1))
  done < <(ls -d /sys/bus/pci/devices/* 2>/dev/null | sort)

  stop_spinner

  if [[ "$safe_count" -eq 0 ]]; then
    local msg
    if [[ "$hidden_target_count" -gt 0 && "$blocked_count" -eq 0 ]]; then
      msg="$(translate "All detected controllers/NVMe are already present in the selected VM.")\n\n$(translate "No additional device needs to be added.")"
    else
      msg="$(translate "No available Controllers/NVMe devices were found.")\n\n"
    fi
    if [[ "$blocked_count" -gt 0 ]]; then
      msg+="$(translate "Hidden for safety"):\n${blocked_report}"
    fi
    dialog --backtitle "ProxMenux" \
      --title "$(translate "Controller + NVMe")" \
      --msgbox "$msg" 18 84
    return 1
  fi

  local raw selected
  raw=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "Controller + NVMe")" \
    --checklist "\n$(translate "Select available Controllers/NVMe to add:")" 20 96 12 \
    "${menu_items[@]}" \
    2>&1 >/dev/tty) || return 1

  selected=$(echo "$raw" | tr -d '"')
  SELECTED_CONTROLLER_PCIS=()
  local pci
  for pci in $selected; do
    _array_contains "$pci" "${SELECTED_CONTROLLER_PCIS[@]}" || SELECTED_CONTROLLER_PCIS+=("$pci")
  done

  if [[ ${#SELECTED_CONTROLLER_PCIS[@]} -eq 0 ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate "Controller + NVMe")" \
      --msgbox "\n$(translate "No controller/NVMe selected.")" 8 62
    return 1
  fi

  # SR-IOV guard: drop VFs / active PFs and inform the user. Same policy
  # as add_gpu_vm.sh and the VM creators — refuse to rewrite host VFIO
  # config for an SR-IOV device since it would collapse the VF tree.
  if declare -F _pci_sriov_filter_array >/dev/null 2>&1; then
    local sriov_removed=""
    sriov_removed=$(_pci_sriov_filter_array SELECTED_CONTROLLER_PCIS)
    if [[ -n "$sriov_removed" ]]; then
      local sriov_msg=""
      sriov_msg="\n$(translate "The following devices were excluded because they are part of an SR-IOV configuration:")\n"
      local entry bdf role first
      while IFS= read -r entry; do
        [[ -z "$entry" ]] && continue
        bdf="${entry%%|*}"
        role="${entry#*|}"
        first="${role%% *}"
        if [[ "$first" == "vf" ]]; then
          sriov_msg+="\n  •  ${bdf}  — $(translate "Virtual Function")"
        else
          sriov_msg+="\n  •  ${bdf}  — $(translate "Physical Function with") ${role#pf-active } $(translate "active VFs")"
        fi
      done <<< "$sriov_removed"
      sriov_msg+="\n\n$(translate "To pass SR-IOV Virtual Functions to a VM, edit the VM configuration manually via the Proxmox web interface.")"
      dialog --backtitle "ProxMenux" --colors \
        --title "$(translate "SR-IOV Configuration Detected")" \
        --msgbox "$sriov_msg" 18 82
    fi

    if [[ ${#SELECTED_CONTROLLER_PCIS[@]} -eq 0 ]]; then
      dialog --backtitle "ProxMenux" \
        --title "$(translate "Controller + NVMe")" \
        --msgbox "\n$(translate "No eligible controllers remain after SR-IOV filtering.")" 8 70
      return 1
    fi
  fi

  return 0
}

_prompt_raw_disk_conflict_policy() {
  local disk="$1"
  shift
  local -a guest_ids=("$@")
  local msg gid gtype gid_num gname gstatus

  msg="$(translate "Disk") ${disk} $(translate "is referenced in the following stopped VM(s)/CT(s):")\\n\\n"
  for gid in "${guest_ids[@]}"; do
    gtype="${gid%%:*}"; gid_num="${gid##*:}"
    if [[ "$gtype" == "VM" ]]; then
      gname=$(_vm_name_by_id "$gid_num")
      gstatus=$(qm status "$gid_num" 2>/dev/null | awk '{print $2}')
      msg+="  - VM $gid_num ($gname) [${gstatus}]\\n"
    else
      gname=$(pct config "$gid_num" 2>/dev/null | awk '/^hostname:/ {print $2}')
      [[ -z "$gname" ]] && gname="CT-$gid_num"
      gstatus=$(pct status "$gid_num" 2>/dev/null | awk '{print $2}')
      msg+="  - CT $gid_num ($gname) [${gstatus}]\\n"
    fi
  done
  msg+="\\n$(translate "Choose action:")"

  local choice
  choice=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "Disk Reference Conflict")" \
    --menu "$msg" 22 84 3 \
    "1" "$(translate "Disable onboot on affected VM(s)/CT(s)")" \
    "2" "$(translate "Remove disk references from affected VM(s)/CT(s) config")" \
    "3" "$(translate "Skip — leave as-is")" \
    2>&1 >/dev/tty) || { echo "skip"; return; }

  case "$choice" in
    1) echo "disable_onboot" ;;
    2) echo "remove_refs" ;;
    *) echo "skip" ;;
  esac
}

confirm_summary() {
  # ── Risk detection ─────────────────────────────────────────────────────────
  local reinforce_limited_firmware="no"
  local bios_date bios_year current_year bios_age cpu_model risk_detail=""
  bios_date=$(cat /sys/class/dmi/id/bios_date 2>/dev/null)
  bios_year=$(echo "$bios_date" | grep -oE '[0-9]{4}' | tail -n1)
  current_year=$(date +%Y 2>/dev/null)
  if [[ -n "$bios_year" && -n "$current_year" ]]; then
    bios_age=$(( current_year - bios_year ))
    if (( bios_age >= 7 )); then
      reinforce_limited_firmware="yes"
      risk_detail="$(translate "BIOS from") ${bios_year} (${bios_age} $(translate "years old")) — $(translate "older firmware may increase passthrough instability")"
    fi
  fi
  cpu_model=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | xargs)
  if echo "$cpu_model" | grep -qiE 'J4[0-9]{3}|J3[0-9]{3}|N4[0-9]{3}|N3[0-9]{3}|Apollo Lake'; then
    reinforce_limited_firmware="yes"
    [[ -z "$risk_detail" ]] && risk_detail="$(translate "Low-power CPU platform"): ${cpu_model}"
  fi

  # ── Build unified message ──────────────────────────────────────────────────
  local msg pci display_name
  msg="\n"

  # Devices to add
  msg+="\Zb$(translate "Devices to add to VM") ${SELECTED_VMID} (${SELECTED_VM_NAME}):\Zn\n"
  for pci in "${SELECTED_CONTROLLER_PCIS[@]}"; do
    display_name=$(_pci_storage_display_name "$pci")
    msg+="  \Zb•\Zn  ${pci}   ${display_name}\n"
  done
  msg+="\n"

  # Compatibility notice (always shown)
  msg+="\Zb\Z4⚠  $(translate "Controller/NVMe passthrough — compatibility notice")\Zn\n\n"
  msg+="$(translate "Not all platforms support Controller/NVMe passthrough reliably.")\n"
  msg+="$(translate "On some systems, when starting the VM the host may slow down for several minutes until it stabilizes, or freeze completely.")\n"

  # Detected risk (only when applicable)
  if [[ "$reinforce_limited_firmware" == "yes" && -n "$risk_detail" ]]; then
    msg+="\n\Z1$(translate "Detected risk factor"): ${risk_detail}\Zn\n"
  fi

  msg+="\n$(translate "If the host freezes, remove hostpci entries from") /etc/pve/qemu-server/${SELECTED_VMID}.conf\n"
  msg+="\n\Zb$(translate "Do you want to continue?")\Zn"

  local height=22
  [[ "$reinforce_limited_firmware" == "yes" ]] && height=25

  if ! dialog --backtitle "ProxMenux" --colors \
    --title "$(translate "Confirm Controller + NVMe Assignment")" \
    --yesno "$msg" $height 90; then
    return 1
  fi
  return 0
}

prompt_controller_conflict_policy() {
  local pci="$1"
  shift
  local -a source_vms=("$@")
  local msg vmid vm_name st ob
  msg="\n$(translate "Selected device is already assigned to other VM(s):")\n\n"
  for vmid in "${source_vms[@]}"; do
    vm_name=$(_vm_name_by_id "$vmid")
    st="stopped"; _vm_status_is_running "$vmid" && st="running"
    ob="0"; _vm_onboot_is_enabled "$vmid" && ob="1"
    msg+="  - VM ${vmid} (${vm_name}) [${st}, onboot=${ob}]\n"
  done
  msg+="\n$(translate "Choose action for this controller/NVMe:")"

  local choice
  choice=$(dialog --backtitle "ProxMenux" \
    --title "$(translate "Controller/NVMe Conflict Policy")" \
    --menu "$msg" 20 80 10 \
    "1" "$(translate "Keep in source VM(s) + disable onboot + add to target VM")" \
    "2" "$(translate "Move to target VM (remove from source VM config)")" \
    "3" "$(translate "Skip this device")" \
    2>&1 >/dev/tty) || { echo "skip"; return; }

  case "$choice" in
    1) echo "keep_disable_onboot" ;;
    2) echo "move_remove_source" ;;
    *) echo "skip" ;;
  esac
}

# ── DIALOG PHASE: resolve all conflicts before terminal ───────────────────────
resolve_disk_conflicts() {
  local -a new_pci_list=()
  local pci vmid action slot_base scope_key has_running

  # ── hostpci conflicts: controller already assigned to another VM ──────────
  for pci in "${SELECTED_CONTROLLER_PCIS[@]}"; do
    local -a source_vms=()
    mapfile -t source_vms < <(_pci_assigned_vm_ids "$pci" "$SELECTED_VMID" 2>/dev/null)

    if [[ ${#source_vms[@]} -eq 0 ]]; then
      new_pci_list+=("$pci")
      continue
    fi

    has_running=false
    for vmid in "${source_vms[@]}"; do
      if _vm_status_is_running "$vmid"; then
        has_running=true
        dialog --backtitle "ProxMenux" \
          --title "$(translate "Device In Use")" \
          --msgbox "\n$(translate "Controller") $pci $(translate "is in use by running VM") $vmid.\n\n$(translate "Stop it first and run this option again.")" \
          10 72
        break
      fi
    done
    $has_running && continue

    scope_key=$(printf '%s,' "${source_vms[@]}")
    if [[ -n "$WIZARD_CONFLICT_POLICY" && "$WIZARD_CONFLICT_SCOPE" == "$scope_key" ]]; then
      action="$WIZARD_CONFLICT_POLICY"
    else
      action=$(prompt_controller_conflict_policy "$pci" "${source_vms[@]}")
      WIZARD_CONFLICT_POLICY="$action"
      WIZARD_CONFLICT_SCOPE="$scope_key"
    fi

    case "$action" in
      keep_disable_onboot)
        for vmid in "${source_vms[@]}"; do
          _vm_onboot_is_enabled "$vmid" && qm set "$vmid" -onboot 0 >/dev/null 2>&1
        done
        new_pci_list+=("$pci")
        ;;
      move_remove_source)
        slot_base=$(_pci_slot_base "$pci")
        for vmid in "${source_vms[@]}"; do
          _remove_pci_slot_from_vm_config "$vmid" "$slot_base"
        done
        new_pci_list+=("$pci")
        ;;
      *) ;; # skip — do not add to new_pci_list
    esac
  done

  SELECTED_CONTROLLER_PCIS=("${new_pci_list[@]}")

  if [[ ${#SELECTED_CONTROLLER_PCIS[@]} -eq 0 ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate "Controller + NVMe")" \
      --msgbox "\n$(translate "No controllers remaining after conflict resolution.")" 8 64
    return 1
  fi

  # ── Raw disk passthrough conflicts ───────────────────────────────────────
  local raw_disk_policy="" raw_disk_scope=""
  for pci in "${SELECTED_CONTROLLER_PCIS[@]}"; do
    local -a cdisks=()
    while IFS= read -r disk; do
      [[ -z "$disk" ]] && continue
      _array_contains "$disk" "${cdisks[@]}" || cdisks+=("$disk")
    done < <(_controller_block_devices "$pci")

    for disk in "${cdisks[@]}"; do
      _disk_used_in_guest_configs "$disk" || continue
      _disk_used_in_running_guest "$disk" && continue

      local -a guest_ids=()
      mapfile -t guest_ids < <(_disk_guest_ids "$disk")
      [[ ${#guest_ids[@]} -eq 0 ]] && continue

      local gscope gaction
      gscope=$(printf '%s,' "${guest_ids[@]}")
      if [[ -n "$raw_disk_policy" && "$raw_disk_scope" == "$gscope" ]]; then
        gaction="$raw_disk_policy"
      else
        gaction=$(_prompt_raw_disk_conflict_policy "$disk" "${guest_ids[@]}")
        raw_disk_policy="$gaction"
        raw_disk_scope="$gscope"
      fi

      local gid gtype gid_num slot
      case "$gaction" in
        disable_onboot)
          for gid in "${guest_ids[@]}"; do
            gtype="${gid%%:*}"; gid_num="${gid##*:}"
            if [[ "$gtype" == "VM" ]]; then
              _vm_onboot_is_enabled "$gid_num" && qm set "$gid_num" -onboot 0 >/dev/null 2>&1
            else
              grep -qE '^onboot:\s*1' "/etc/pve/lxc/$gid_num.conf" 2>/dev/null && \
                pct set "$gid_num" -onboot 0 >/dev/null 2>&1
            fi
          done
          ;;
        remove_refs)
          for gid in "${guest_ids[@]}"; do
            gtype="${gid%%:*}"; gid_num="${gid##*:}"
            if [[ "$gtype" == "VM" ]]; then
              while IFS= read -r slot; do
                [[ -z "$slot" ]] && continue
                qm set "$gid_num" -delete "$slot" >/dev/null 2>&1
              done < <(_find_disk_slots_in_vm "$gid_num" "$disk")
            else
              while IFS= read -r slot; do
                [[ -z "$slot" ]] && continue
                pct set "$gid_num" -delete "$slot" >/dev/null 2>&1
              done < <(_find_disk_slots_in_ct "$gid_num" "$disk")
            fi
          done
          ;;
      esac
    done
  done

  return 0
}

apply_assignment() {
  : >"$LOG_FILE"
  set_title

  msg_info "$(translate "Applying Controller/NVMe passthrough to VM") ${SELECTED_VMID}..."
  msg_ok "$(translate "Target VM validated") (${SELECTED_VM_NAME} / ${SELECTED_VMID})"
  msg_ok "$(translate "Selected devices"): ${#SELECTED_CONTROLLER_PCIS[@]}"

  local hostpci_idx=0
  if declare -F _pci_next_hostpci_index >/dev/null 2>&1; then
    hostpci_idx=$(_pci_next_hostpci_index "$SELECTED_VMID" 2>/dev/null || echo 0)
  else
    local hostpci_existing
    hostpci_existing=$(qm config "$SELECTED_VMID" 2>/dev/null)
    while grep -q "^hostpci${hostpci_idx}:" <<< "$hostpci_existing"; do
      hostpci_idx=$((hostpci_idx + 1))
    done
  fi

  local pci bdf assigned_count=0
  for pci in "${SELECTED_CONTROLLER_PCIS[@]}"; do
    bdf="${pci#0000:}"
    if declare -F _pci_function_assigned_to_vm >/dev/null 2>&1; then
      if _pci_function_assigned_to_vm "$pci" "$SELECTED_VMID"; then
        msg_warn "$(translate "Controller/NVMe already present in VM config") ($pci)"
        continue
      fi
    elif qm config "$SELECTED_VMID" 2>/dev/null | grep -qE "^hostpci[0-9]+:.*(0000:)?${bdf}([,[:space:]]|$)"; then
      msg_warn "$(translate "Controller/NVMe already present in VM config") ($pci)"
      continue
    fi

    local display_name
    display_name=$(_pci_storage_display_name "$pci")
    msg_info "$(translate "Adding") ${display_name} (${pci}) → hostpci${hostpci_idx}..."
    if qm set "$SELECTED_VMID" "--hostpci${hostpci_idx}" "${pci},pcie=1" >>"$LOG_FILE" 2>&1; then
      msg_ok "$(translate "Controller/NVMe assigned") (hostpci${hostpci_idx} → ${pci})"
      assigned_count=$((assigned_count + 1))
      hostpci_idx=$((hostpci_idx + 1))
    else
      msg_error "$(translate "Failed to assign Controller/NVMe") (${pci})"
    fi
  done

  echo ""
  echo -e "${TAB}${BL}Log: ${LOG_FILE}${CL}"

  if [[ "$assigned_count" -gt 0 ]]; then
    msg_ok "$(translate "Completed.") $assigned_count $(translate "device(s) added to VM") ${SELECTED_VMID}."
  else
    msg_warn "$(translate "No new Controller/NVMe entries were added.")"
  fi

  if [[ "${IOMMU_ALREADY_ACTIVE:-0}" == "1" ]]; then
    msg_ok "$(translate "IOMMU is enabled on the system")"
  elif [[ "${IOMMU_PENDING_REBOOT:-0}" == "1" ]]; then
    msg_ok "$(translate "IOMMU has been enabled — a system reboot is required")"
    echo ""
    if whiptail --title "$(translate "Reboot Required")" \
      --yesno "\n$(translate "IOMMU has been enabled on this system. A reboot is required to apply the changes. Reboot now?")" 11 64; then
      msg_success "$(translate "Press Enter to continue...")"
      read -r
      msg_warn "$(translate "Rebooting the system...")"
      reboot
    else
      msg_info2 "$(translate "To use the VM without issues, the host must be restarted before starting it.")"
      msg_info2 "$(translate "Do not start the VM until the system has been rebooted.")"
    fi
  fi
  echo ""
  msg_success "$(translate "Press Enter to continue...")"
  read -r
}

main() {
  export WIZARD_CONFLICT_POLICY
  export WIZARD_CONFLICT_SCOPE
  select_target_vm         || exit 0
  validate_vm_requirements || exit 0
  select_controller_nvme   || exit 0
  resolve_disk_conflicts   || exit 0
  confirm_summary          || exit 0
  apply_assignment
}

main "$@"
