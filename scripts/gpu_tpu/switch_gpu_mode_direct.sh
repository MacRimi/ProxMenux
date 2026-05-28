#!/bin/bash
# ==========================================================
# ProxMenux - GPU Switch Mode Direct (VM <-> LXC)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 09/04/2026
# ==========================================================
# This script is a hybrid version for ProxMenux Monitor.
# It accepts parameters to skip GPU selection and uses
# hybrid dialogs for web rendering.
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
  LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
  UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
  UTILS_FILE="$BASE_DIR/utils.sh"
fi

LOG_FILE="/tmp/proxmenux_gpu_switch_mode.log"
screen_capture="/tmp/proxmenux_gpu_switch_mode_screen_$$.txt"

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh"
fi
load_language
initialize_cache

# ==========================================================
# Global Variables
# ==========================================================
declare -a ALL_GPU_PCIS=()
declare -a ALL_GPU_TYPES=()
declare -a ALL_GPU_NAMES=()
declare -a ALL_GPU_DRIVERS=()
declare -a ALL_GPU_VIDDID=()
declare -a SELECTED_GPU_IDX=()

declare -a SELECTED_IOMMU_IDS=()
declare -a SELECTED_PCI_SLOTS=()

declare -a LXC_AFFECTED_CTIDS=()
declare -a LXC_AFFECTED_NAMES=()
declare -a LXC_AFFECTED_RUNNING=()
declare -a LXC_AFFECTED_ONBOOT=()

declare -a VM_AFFECTED_IDS=()
declare -a VM_AFFECTED_NAMES=()
declare -a VM_AFFECTED_RUNNING=()
declare -a VM_AFFECTED_ONBOOT=()

TARGET_MODE=""                    # vm | lxc
CURRENT_MODE=""                   # vm | lxc | mixed
LXC_ACTION=""                     # keep_gpu_disable_onboot | remove_gpu_keep_onboot
VM_ACTION=""                      # keep_gpu_disable_onboot | remove_gpu_keep_onboot
GPU_COUNT=0
HOST_CONFIG_CHANGED=false

# Parameters from command line
PARAM_GPU_SLOT=""
PARAM_TARGET_MODE=""

# ==========================================================
# Helper Functions (same as original)
# ==========================================================
_set_title() {
  show_proxmenux_logo
  case "$TARGET_MODE" in
    vm)  msg_title "GPU Switch Mode (GPU -> VM)" ;;
    lxc) msg_title "GPU Switch Mode (GPU -> LXC)" ;;
    *)   msg_title "GPU Switch Mode (VM <-> LXC)" ;;
  esac
}

_add_line_if_missing() {
  local line="$1"
  local file="$2"
  touch "$file"
  if ! grep -qFx "$line" "$file" 2>/dev/null; then
    echo "$line" >>"$file"
    HOST_CONFIG_CHANGED=true
  fi
}

_get_pci_driver() {
  local pci_full="$1"
  local driver_link="/sys/bus/pci/devices/${pci_full}/driver"
  if [[ -L "$driver_link" ]]; then
    basename "$(readlink "$driver_link")"
  else
    echo "none"
  fi
}

_ct_is_running() {
  local ctid="$1"
  pct status "$ctid" 2>/dev/null | grep -q "status: running"
}

_ct_onboot_enabled() {
  local ctid="$1"
  pct config "$ctid" 2>/dev/null | grep -qE "^onboot:\s*1"
}

_vm_is_running() {
  local vmid="$1"
  qm status "$vmid" 2>/dev/null | grep -q "status: running"
}

_vm_onboot_enabled() {
  local vmid="$1"
  qm config "$vmid" 2>/dev/null | grep -qE "^onboot:\s*1"
}

_get_iommu_group_ids() {
  local pci_full="$1"
  local group_link="/sys/bus/pci/devices/${pci_full}/iommu_group"
  [[ ! -L "$group_link" ]] && return

  local group_dir
  group_dir="/sys/kernel/iommu_groups/$(basename "$(readlink "$group_link")")/devices"
  for dev_path in "${group_dir}/"*; do
    [[ -e "$dev_path" ]] || continue
    local dev dev_class vid did
    dev=$(basename "$dev_path")
    dev_class=$(cat "/sys/bus/pci/devices/${dev}/class" 2>/dev/null)
    [[ "$dev_class" == 0x0604* || "$dev_class" == 0x0600* ]] && continue
    vid=$(cat "/sys/bus/pci/devices/${dev}/vendor" 2>/dev/null | sed 's/0x//')
    did=$(cat "/sys/bus/pci/devices/${dev}/device" 2>/dev/null | sed 's/0x//')
    [[ -n "$vid" && -n "$did" ]] && echo "${vid}:${did}"
  done
}

_read_vfio_ids() {
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  local ids_line ids_part
  ids_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
  [[ -z "$ids_line" ]] && return
  ids_part=$(echo "$ids_line" | grep -oE 'ids=[^[:space:]]+' | sed 's/ids=//')
  [[ -z "$ids_part" ]] && return
  tr ',' '\n' <<< "$ids_part" | sed '/^$/d'
}

_write_vfio_ids() {
  local -a ids=("$@")
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  touch "$vfio_conf"

  local current_line new_line ids_str
  current_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
  sed -i '/^options vfio-pci ids=/d' "$vfio_conf"

  if [[ ${#ids[@]} -gt 0 ]]; then
    ids_str=$(IFS=','; echo "${ids[*]}")
    new_line="options vfio-pci ids=${ids_str} disable_vga=1"
    echo "$new_line" >>"$vfio_conf"
    [[ "$current_line" != "$new_line" ]] && HOST_CONFIG_CHANGED=true
  else
    [[ -n "$current_line" ]] && HOST_CONFIG_CHANGED=true
  fi
}

_contains_in_array() {
  local needle="$1"
  shift
  local x
  for x in "$@"; do
    [[ "$x" == "$needle" ]] && return 0
  done
  return 1
}

_remove_gpu_blacklist() {
  local gpu_type="$1"
  local blacklist_file="/etc/modprobe.d/blacklist.conf"
  [[ ! -f "$blacklist_file" ]] && return
  local changed=false
  case "$gpu_type" in
    nvidia)
      grep -qE '^blacklist (nouveau|nvidia|nvidiafb|nvidia_drm|nvidia_modeset|nvidia_uvm|lbm-nouveau)$|^options nouveau modeset=0$' "$blacklist_file" 2>/dev/null && changed=true
      sed -i '/^blacklist nouveau$/d' "$blacklist_file"
      sed -i '/^blacklist nvidia$/d' "$blacklist_file"
      sed -i '/^blacklist nvidiafb$/d' "$blacklist_file"
      sed -i '/^blacklist nvidia_drm$/d' "$blacklist_file"
      sed -i '/^blacklist nvidia_modeset$/d' "$blacklist_file"
      sed -i '/^blacklist nvidia_uvm$/d' "$blacklist_file"
      sed -i '/^blacklist lbm-nouveau$/d' "$blacklist_file"
      sed -i '/^options nouveau modeset=0$/d' "$blacklist_file"
      ;;
    amd)
      grep -qE '^blacklist (radeon|amdgpu)$' "$blacklist_file" 2>/dev/null && changed=true
      sed -i '/^blacklist radeon$/d' "$blacklist_file"
      sed -i '/^blacklist amdgpu$/d' "$blacklist_file"
      ;;
    intel)
      grep -qE '^blacklist i915$' "$blacklist_file" 2>/dev/null && changed=true
      sed -i '/^blacklist i915$/d' "$blacklist_file"
      ;;
  esac
  $changed && HOST_CONFIG_CHANGED=true
  $changed
}

_add_gpu_blacklist() {
  local gpu_type="$1"
  local blacklist_file="/etc/modprobe.d/blacklist.conf"
  touch "$blacklist_file"
  case "$gpu_type" in
    nvidia)
      _add_line_if_missing "blacklist nouveau" "$blacklist_file"
      _add_line_if_missing "blacklist nvidia" "$blacklist_file"
      _add_line_if_missing "blacklist nvidiafb" "$blacklist_file"
      _add_line_if_missing "blacklist nvidia_drm" "$blacklist_file"
      _add_line_if_missing "blacklist nvidia_modeset" "$blacklist_file"
      _add_line_if_missing "blacklist nvidia_uvm" "$blacklist_file"
      _add_line_if_missing "blacklist lbm-nouveau" "$blacklist_file"
      _add_line_if_missing "options nouveau modeset=0" "$blacklist_file"
      ;;
    amd)
      _add_line_if_missing "blacklist radeon" "$blacklist_file"
      _add_line_if_missing "blacklist amdgpu" "$blacklist_file"
      ;;
    intel)
      _add_line_if_missing "blacklist i915" "$blacklist_file"
      ;;
  esac
}

_sanitize_nvidia_host_stack_for_vfio() {
  local changed=false
  local state_dir="/var/lib/proxmenux"
  local state_file="${state_dir}/nvidia-host-services.state"
  local svc
  local -a services=(
    "nvidia-persistenced.service"
    "nvidia-powerd.service"
    "nvidia-fabricmanager.service"
  )

  mkdir -p "$state_dir" >/dev/null 2>&1 || true
  : > "$state_file"

  for svc in "${services[@]}"; do
    local was_enabled=0 was_active=0
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
      was_enabled=1
    fi
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
      was_active=1
    fi
    if (( was_enabled == 1 || was_active == 1 )); then
      echo "${svc} enabled=${was_enabled} active=${was_active}" >>"$state_file"
    fi

    if systemctl is-active --quiet "$svc" 2>/dev/null; then
      systemctl stop "$svc" >>"$LOG_FILE" 2>&1 || true
      changed=true
    fi
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
      systemctl disable "$svc" >>"$LOG_FILE" 2>&1 || true
      changed=true
    fi
  done

  [[ -s "$state_file" ]] || rm -f "$state_file"

  if [[ -f /etc/modules-load.d/nvidia-vfio.conf ]]; then
    mv /etc/modules-load.d/nvidia-vfio.conf /etc/modules-load.d/nvidia-vfio.conf.proxmenux-disabled-vfio >>"$LOG_FILE" 2>&1 || true
    changed=true
  fi

  if grep -qE '^(nvidia|nvidia_uvm|nvidia_drm|nvidia_modeset)$' /etc/modules 2>/dev/null; then
    sed -i '/^nvidia$/d;/^nvidia_uvm$/d;/^nvidia_drm$/d;/^nvidia_modeset$/d' /etc/modules
    changed=true
  fi

  # Disable NVIDIA udev rules that trigger nvidia-smi (causes conflict with vfio-pci)
  local udev_rules="/etc/udev/rules.d/70-nvidia.rules"
  if [[ -f "$udev_rules" ]]; then
    mv "$udev_rules" "${udev_rules}.proxmenux-disabled" >>"$LOG_FILE" 2>&1 || true
    udevadm control --reload-rules >>"$LOG_FILE" 2>&1 || true
    changed=true
  fi

  # Create hard blacklist to prevent ANY nvidia module loading (even via modprobe/nvidia-smi)
  local nvidia_blacklist="/etc/modprobe.d/nvidia-blacklist.conf"
  if [[ ! -f "$nvidia_blacklist" ]]; then
    cat > "$nvidia_blacklist" <<'EOF'
# ProxMenux: Hard blacklist to prevent ANY nvidia module loading in VFIO mode
# This prevents nvidia-smi and other tools from triggering module load attempts
install nvidia /bin/false
install nvidia_uvm /bin/false
install nvidia_drm /bin/false
install nvidia_modeset /bin/false
EOF
    changed=true
  fi

  if $changed; then
    HOST_CONFIG_CHANGED=true
    msg_ok "$(translate 'NVIDIA host services/autoload disabled for VFIO mode')" | tee -a "$screen_capture"
  else
    msg_ok "$(translate 'NVIDIA host services/autoload already aligned for VFIO mode')" | tee -a "$screen_capture"
  fi
}

_restore_nvidia_host_stack_for_lxc() {
  local changed=false
  local state_file="/var/lib/proxmenux/nvidia-host-services.state"
  local disabled_file="/etc/modules-load.d/nvidia-vfio.conf.proxmenux-disabled-vfio"
  local active_file="/etc/modules-load.d/nvidia-vfio.conf"

  # Remove hard blacklist that was preventing nvidia module loading
  local nvidia_blacklist="/etc/modprobe.d/nvidia-blacklist.conf"
  if [[ -f "$nvidia_blacklist" ]]; then
    rm -f "$nvidia_blacklist" >>"$LOG_FILE" 2>&1 || true
    changed=true
  fi

  # Restore NVIDIA udev rules if they were disabled
  local udev_disabled="/etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled"
  local udev_rules="/etc/udev/rules.d/70-nvidia.rules"
  if [[ -f "$udev_disabled" ]]; then
    mv "$udev_disabled" "$udev_rules" >>"$LOG_FILE" 2>&1 || true
    udevadm control --reload-rules >>"$LOG_FILE" 2>&1 || true
    changed=true
  fi

  if [[ -f "$disabled_file" ]]; then
    mv "$disabled_file" "$active_file" >>"$LOG_FILE" 2>&1 || true
    changed=true
  fi

  modprobe nvidia >/dev/null 2>&1 || true
  modprobe nvidia_uvm >/dev/null 2>&1 || true
  modprobe nvidia_modeset >/dev/null 2>&1 || true
  modprobe nvidia_drm >/dev/null 2>&1 || true

  if [[ -f "$state_file" ]]; then
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      local svc enabled active
      svc=$(echo "$line" | awk '{print $1}')
      enabled=$(echo "$line" | awk -F'enabled=' '{print $2}' | awk '{print $1}')
      active=$(echo "$line" | awk -F'active=' '{print $2}' | awk '{print $1}')
      [[ "$enabled" == "1" ]] && systemctl enable "$svc" >>"$LOG_FILE" 2>&1 || true
      [[ "$active" == "1" ]] && systemctl start "$svc" >>"$LOG_FILE" 2>&1 || true
    done <"$state_file"
    rm -f "$state_file"
    changed=true
  fi

  if $changed; then
    HOST_CONFIG_CHANGED=true
    msg_ok "$(translate 'NVIDIA host services/autoload restored for native mode')" | tee -a "$screen_capture"
  else
    msg_ok "$(translate 'NVIDIA host services/autoload already aligned for native mode')" | tee -a "$screen_capture"
  fi
}

_add_amd_softdep() {
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  _add_line_if_missing "softdep radeon pre: vfio-pci" "$vfio_conf"
  _add_line_if_missing "softdep amdgpu pre: vfio-pci" "$vfio_conf"
  _add_line_if_missing "softdep snd_hda_intel pre: vfio-pci" "$vfio_conf"
}

_remove_amd_softdep() {
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  [[ ! -f "$vfio_conf" ]] && return
  local changed=false
  grep -qE '^softdep (radeon|amdgpu|snd_hda_intel) pre: vfio-pci$' "$vfio_conf" 2>/dev/null && changed=true
  sed -i '/^softdep radeon pre: vfio-pci$/d' "$vfio_conf"
  sed -i '/^softdep amdgpu pre: vfio-pci$/d' "$vfio_conf"
  sed -i '/^softdep snd_hda_intel pre: vfio-pci$/d' "$vfio_conf"
  $changed && HOST_CONFIG_CHANGED=true
  $changed
}

_add_vfio_modules() {
  local modules=("vfio" "vfio_iommu_type1" "vfio_pci")
  local kernel_major kernel_minor
  kernel_major=$(uname -r | cut -d. -f1)
  kernel_minor=$(uname -r | cut -d. -f2)
  if (( kernel_major < 6 || ( kernel_major == 6 && kernel_minor < 2 ) )); then
    modules+=("vfio_virqfd")
  fi
  local mod
  for mod in "${modules[@]}"; do
    _add_line_if_missing "$mod" /etc/modules
  done
}

_remove_vfio_modules_if_unused() {
  local vfio_count
  vfio_count=$(_read_vfio_ids | wc -l | tr -d '[:space:]')
  [[ "$vfio_count" != "0" ]] && return 1
  local modules_file="/etc/modules"
  [[ ! -f "$modules_file" ]] && return 1
  local had_any=false
  grep -qE '^vfio$|^vfio_iommu_type1$|^vfio_pci$|^vfio_virqfd$' "$modules_file" 2>/dev/null && had_any=true
  sed -i '/^vfio$/d' "$modules_file"
  sed -i '/^vfio_iommu_type1$/d' "$modules_file"
  sed -i '/^vfio_pci$/d' "$modules_file"
  sed -i '/^vfio_virqfd$/d' "$modules_file"
  if $had_any; then
    HOST_CONFIG_CHANGED=true
    return 0
  fi
  return 1
}

_configure_iommu_options() {
  _add_line_if_missing "options vfio_iommu_type1 allow_unsafe_interrupts=1" /etc/modprobe.d/iommu_unsafe_interrupts.conf
  _add_line_if_missing "options kvm ignore_msrs=1" /etc/modprobe.d/kvm.conf
}

_selected_types_unique() {
  local idx t
  local -a seen=()
  for idx in "${SELECTED_GPU_IDX[@]}"; do
    t="${ALL_GPU_TYPES[$idx]}"
    _contains_in_array "$t" "${seen[@]}" || { seen+=("$t"); echo "$t"; }
  done
}

# ==========================================================
# GPU Detection
# ==========================================================
detect_host_gpus() {
  ALL_GPU_PCIS=()
  ALL_GPU_TYPES=()
  ALL_GPU_NAMES=()
  ALL_GPU_DRIVERS=()
  ALL_GPU_VIDDID=()

  local line pci name vendor vid did drv
  while IFS= read -r line; do
    pci=$(echo "$line" | awk '{print $1}')
    [[ ! "$pci" =~ ^[0-9a-f]{4}: ]] && pci="0000:$pci"
    name=$(echo "$line" | sed 's/^[^ ]* //')

    vendor=""
    if echo "$name" | grep -qi "nvidia"; then
      vendor="nvidia"
    elif echo "$name" | grep -qiE "amd|radeon"; then
      vendor="amd"
    elif echo "$name" | grep -qi "intel"; then
      vendor="intel"
    else
      vendor="other"
    fi

    vid=$(cat "/sys/bus/pci/devices/${pci}/vendor" 2>/dev/null | sed 's/0x//')
    did=$(cat "/sys/bus/pci/devices/${pci}/device" 2>/dev/null | sed 's/0x//')
    drv=$(_get_pci_driver "$pci")

    ALL_GPU_PCIS+=("$pci")
    ALL_GPU_TYPES+=("$vendor")
    ALL_GPU_NAMES+=("$name")
    ALL_GPU_DRIVERS+=("$drv")
    ALL_GPU_VIDDID+=("${vid}:${did}")
  done < <(lspci -D | grep -iE "VGA|3D|Display" | grep -v "Audio")

  GPU_COUNT=${#ALL_GPU_PCIS[@]}
}

# ==========================================================
# Find GPU by PCI Slot (new function for direct mode)
# ==========================================================
find_gpu_by_slot() {
  local target_slot="$1"
  SELECTED_GPU_IDX=()
  
  # Normalize slot format (ensure 0000: prefix)
  [[ ! "$target_slot" =~ ^[0-9a-f]{4}: ]] && target_slot="0000:$target_slot"
  
  local i
  for i in "${!ALL_GPU_PCIS[@]}"; do
    if [[ "${ALL_GPU_PCIS[$i]}" == "$target_slot"* ]]; then
      SELECTED_GPU_IDX+=("$i")
      return 0
    fi
  done
  
  msg_error "$(translate 'GPU not found with slot'): $target_slot"
  return 1
}

# ==========================================================
# SR-IOV guard — abort mode switch when SR-IOV is active
# ==========================================================
# Same policy as the interactive switch_gpu_mode.sh: refuse to operate on
# a Virtual Function or on a Physical Function that already has active
# VFs, since flipping drivers in that state collapses the VF tree and
# breaks every guest that was consuming a VF.
check_sriov_and_block_if_needed() {
  declare -F _pci_sriov_role >/dev/null 2>&1 || return 0

  local idx pci role first_word pf_bdf active_count
  local -a vf_list=()
  local -a pf_list=()

  for idx in "${SELECTED_GPU_IDX[@]}"; do
    pci="${ALL_GPU_PCIS[$idx]}"
    role=$(_pci_sriov_role "$pci")
    first_word="${role%% *}"
    case "$first_word" in
      vf)
        pf_bdf="${role#vf }"
        vf_list+=("${pci}|${pf_bdf}")
        ;;
      pf-active)
        active_count="${role#pf-active }"
        pf_list+=("${pci}|${active_count}")
        ;;
    esac
  done

  [[ ${#vf_list[@]} -eq 0 && ${#pf_list[@]} -eq 0 ]] && return 0

  local msg entry bdf parent cnt
  msg="<div style='color:#f0ad4e;font-weight:bold;margin-bottom:10px;'>$(translate 'SR-IOV Configuration Detected')</div>"

  if [[ ${#vf_list[@]} -gt 0 ]]; then
    msg+="<p>$(translate 'The following selected device(s) are SR-IOV Virtual Functions (VFs):')</p><ul>"
    for entry in "${vf_list[@]}"; do
      bdf="${entry%%|*}"
      parent="${entry#*|}"
      msg+="<li><code>${bdf}</code> &mdash; $(translate 'parent PF:') <code>${parent}</code></li>"
    done
    msg+="</ul>"
  fi

  if [[ ${#pf_list[@]} -gt 0 ]]; then
    msg+="<p>$(translate 'The following selected device(s) are Physical Functions with active Virtual Functions:')</p><ul>"
    for entry in "${pf_list[@]}"; do
      bdf="${entry%%|*}"
      cnt="${entry#*|}"
      msg+="<li><code>${bdf}</code> &mdash; ${cnt} $(translate 'active VF(s)')</li>"
    done
    msg+="</ul>"
  fi

  msg+="<p>$(translate 'To assign VFs to VMs or LXCs, edit the configuration manually via the Proxmox web interface. The Physical Function will remain bound to the native driver.')</p>"

  hybrid_msgbox "$(translate 'SR-IOV Configuration Detected')" "$msg"
  return 1
}

validate_vm_mode_blocked_ids() {
  [[ "$TARGET_MODE" != "vm" ]] && return 0

  local -a blocked_lines=()
  local idx viddid name pci
  for idx in "${SELECTED_GPU_IDX[@]}"; do
    viddid="${ALL_GPU_VIDDID[$idx]}"
    name="${ALL_GPU_NAMES[$idx]}"
    pci="${ALL_GPU_PCIS[$idx]}"

    case "$viddid" in
      8086:5a84|8086:5a85)
        blocked_lines+=("  - ${name} (${pci}) [ID: ${viddid}]")
        ;;
    esac
  done

  [[ ${#blocked_lines[@]} -eq 0 ]] && return 0

  local msg
  msg="<div style='color:#ff6b6b;font-weight:bold;margin-bottom:10px;'>$(translate 'Blocked GPU ID for VM Mode')</div>"
  msg+="<p>$(translate 'At least one selected GPU is blocked by policy for GPU -> VM mode due to passthrough instability risk.')</p>"
  msg+="<p><strong>$(translate 'Blocked device(s)'):</strong></p><ul>"
  local line
  for line in "${blocked_lines[@]}"; do
    msg+="<li>${line}</li>"
  done
  msg+="</ul>"
  msg+="<p>$(translate 'Recommended: use GPU -> LXC mode for these devices.')</p>"

  hybrid_msgbox "$(translate 'GPU Switch Mode Blocked')" "$msg"
  return 1
}

collect_selected_iommu_ids() {
  SELECTED_IOMMU_IDS=()
  SELECTED_PCI_SLOTS=()

  local idx pci viddid slot
  for idx in "${SELECTED_GPU_IDX[@]}"; do
    pci="${ALL_GPU_PCIS[$idx]}"
    viddid="${ALL_GPU_VIDDID[$idx]}"
    slot="${pci#0000:}"
    slot="${slot%.*}"
    SELECTED_PCI_SLOTS+=("$slot")

    local -a group_ids=()
    mapfile -t group_ids < <(_get_iommu_group_ids "$pci")
    if [[ ${#group_ids[@]} -gt 0 ]]; then
      local gid
      for gid in "${group_ids[@]}"; do
        _contains_in_array "$gid" "${SELECTED_IOMMU_IDS[@]}" || SELECTED_IOMMU_IDS+=("$gid")
      done
    elif [[ -n "$viddid" ]]; then
      _contains_in_array "$viddid" "${SELECTED_IOMMU_IDS[@]}" || SELECTED_IOMMU_IDS+=("$viddid")
    fi
  done
}

# ==========================================================
# LXC Detection and Handling (hybrid dialogs)
# ==========================================================
_lxc_conf_uses_type() {
  local conf="$1"
  local gpu_type="$2"
  case "$gpu_type" in
    nvidia) grep -qE "dev[0-9]+:.*(/dev/nvidia|/dev/nvidia-caps)" "$conf" 2>/dev/null ;;
    amd)    grep -qE "dev[0-9]+:.*(/dev/dri|/dev/kfd)|lxc\.mount\.entry:.*dev/dri" "$conf" 2>/dev/null ;;
    intel)  grep -qE "dev[0-9]+:.*(/dev/dri)|lxc\.mount\.entry:.*dev/dri" "$conf" 2>/dev/null ;;
    *)      return 1 ;;
  esac
}

detect_affected_lxc_for_selected() {
  LXC_AFFECTED_CTIDS=()
  LXC_AFFECTED_NAMES=()
  LXC_AFFECTED_RUNNING=()
  LXC_AFFECTED_ONBOOT=()

  local -a types=()
  mapfile -t types < <(_selected_types_unique)

  local conf
  for conf in /etc/pve/lxc/*.conf; do
    [[ -f "$conf" ]] || continue
    local matched=false
    local t
    for t in "${types[@]}"; do
      _lxc_conf_uses_type "$conf" "$t" && matched=true && break
    done
    $matched || continue

    local ctid ct_name run onb
    ctid=$(basename "$conf" .conf)
    ct_name=$(pct config "$ctid" 2>/dev/null | awk '/^hostname:/ {print $2}')
    [[ -z "$ct_name" ]] && ct_name="CT-${ctid}"
    run=0; onb=0
    _ct_is_running "$ctid" && run=1
    _ct_onboot_enabled "$ctid" && onb=1

    LXC_AFFECTED_CTIDS+=("$ctid")
    LXC_AFFECTED_NAMES+=("$ct_name")
    LXC_AFFECTED_RUNNING+=("$run")
    LXC_AFFECTED_ONBOOT+=("$onb")
  done
}

# HYBRID: LXC conflict policy prompt
prompt_lxc_action_for_vm_mode() {
  [[ ${#LXC_AFFECTED_CTIDS[@]} -eq 0 ]] && return 0

  local running_count=0 onboot_count=0 i
  for i in "${!LXC_AFFECTED_CTIDS[@]}"; do
    [[ "${LXC_AFFECTED_RUNNING[$i]}" == "1" ]] && running_count=$((running_count + 1))
    [[ "${LXC_AFFECTED_ONBOOT[$i]}" == "1" ]] && onboot_count=$((onboot_count + 1))
  done

  local msg
  msg="$(translate 'The selected GPU(s) are used in these LXC container(s)'):\n\n"
  for i in "${!LXC_AFFECTED_CTIDS[@]}"; do
    local st ob
    st="$(translate 'stopped')"; ob="onboot=0"
    [[ "${LXC_AFFECTED_RUNNING[$i]}" == "1" ]] && st="$(translate 'running')"
    [[ "${LXC_AFFECTED_ONBOOT[$i]}" == "1" ]] && ob="onboot=1"
    msg+="  - CT ${LXC_AFFECTED_CTIDS[$i]} (${LXC_AFFECTED_NAMES[$i]}) [${st}, ${ob}]\n"
  done
  msg+="\n$(translate 'Switching to GPU -> VM mode requires exclusive VFIO binding.')\n"
  [[ "$running_count" -gt 0 ]] && msg+="$(translate 'Running containers detected'): ${running_count}\n"
  [[ "$onboot_count" -gt 0 ]] && msg+="$(translate 'Start on boot enabled'): ${onboot_count}\n"
  msg+="\n$(translate 'Choose conflict policy'):"

  local choice
  choice=$(hybrid_menu "$(translate 'LXC Conflict Policy')" "$msg" 24 80 8 \
    "1" "$(translate 'Keep GPU in LXC config (disable Start on boot)')" \
    "2" "$(translate 'Remove GPU from LXC config (keep Start on boot)')")

  case "$choice" in
    1) LXC_ACTION="keep_gpu_disable_onboot" ;;
    2) LXC_ACTION="remove_gpu_keep_onboot" ;;
    *) 
      msg_warn "$(translate 'Operation cancelled by user')"
      exit 0 
      ;;
  esac
}

_remove_type_from_lxc_conf() {
  local conf="$1"
  local gpu_type="$2"
  case "$gpu_type" in
    nvidia)
      sed -i '/dev[0-9]\+:.*\/dev\/nvidia/d' "$conf"
      ;;
    amd)
      sed -i '/dev[0-9]\+:.*\/dev\/dri/d' "$conf"
      sed -i '/dev[0-9]\+:.*\/dev\/kfd/d' "$conf"
      sed -i '/lxc\.mount\.entry:.*dev\/dri/d' "$conf"
      sed -i '/lxc\.cgroup2\.devices\.allow:.*226/d' "$conf"
      ;;
    intel)
      sed -i '/dev[0-9]\+:.*\/dev\/dri/d' "$conf"
      sed -i '/lxc\.mount\.entry:.*dev\/dri/d' "$conf"
      sed -i '/lxc\.cgroup2\.devices\.allow:.*226/d' "$conf"
      ;;
  esac
}

apply_lxc_action_for_vm_mode() {
  [[ ${#LXC_AFFECTED_CTIDS[@]} -eq 0 ]] && return 0
  local -a types=()
  mapfile -t types < <(_selected_types_unique)

  local i
  for i in "${!LXC_AFFECTED_CTIDS[@]}"; do
    local ctid conf
    ctid="${LXC_AFFECTED_CTIDS[$i]}"
    conf="/etc/pve/lxc/${ctid}.conf"

    if [[ "${LXC_AFFECTED_RUNNING[$i]}" == "1" ]]; then
      msg_info "$(translate 'Stopping LXC') ${ctid}..."
      # _pmx_stop_lxc: unlock + graceful shutdown with forceStop+timeout,
      # fallback to pct stop. Prevents the indefinite hang that raw
      # `pct stop` triggers on locked / stuck containers.
      if _pmx_stop_lxc "$ctid" "$LOG_FILE"; then
        msg_ok "$(translate 'LXC stopped') ${ctid}" | tee -a "$screen_capture"
      else
        msg_warn "$(translate 'Could not stop LXC') ${ctid}" | tee -a "$screen_capture"
      fi
    fi

    if [[ "$LXC_ACTION" == "keep_gpu_disable_onboot" && "${LXC_AFFECTED_ONBOOT[$i]}" == "1" ]]; then
      if pct set "$ctid" -onboot 0 >>"$LOG_FILE" 2>&1; then
        msg_warn "$(translate 'Start on boot disabled for LXC') ${ctid}" | tee -a "$screen_capture"
      fi
    fi

    if [[ "$LXC_ACTION" == "remove_gpu_keep_onboot" && -f "$conf" ]]; then
      local t
      for t in "${types[@]}"; do
        _remove_type_from_lxc_conf "$conf" "$t"
      done
      msg_ok "$(translate 'GPU access removed from LXC') ${ctid}" | tee -a "$screen_capture"
    fi
  done
}

# ==========================================================
# VM Detection and Handling (hybrid dialogs)
# ==========================================================
detect_affected_vms_for_selected() {
  VM_AFFECTED_IDS=()
  VM_AFFECTED_NAMES=()
  VM_AFFECTED_RUNNING=()
  VM_AFFECTED_ONBOOT=()

  local conf
  for conf in /etc/pve/qemu-server/*.conf; do
    [[ -f "$conf" ]] || continue
    local matched=false slot
    for slot in "${SELECTED_PCI_SLOTS[@]}"; do
      if grep -qE "hostpci[0-9]+:.*(0000:)?${slot}(\\.[0-7])?([,[:space:]]|$)" "$conf"; then
        matched=true
        break
      fi
    done
    $matched || continue

    local vmid vm_name run onb
    vmid=$(basename "$conf" .conf)
    vm_name=$(grep "^name:" "$conf" 2>/dev/null | awk '{print $2}')
    [[ -z "$vm_name" ]] && vm_name="VM-${vmid}"
    run=0; onb=0
    _vm_is_running "$vmid" && run=1
    _vm_onboot_enabled "$vmid" && onb=1

    VM_AFFECTED_IDS+=("$vmid")
    VM_AFFECTED_NAMES+=("$vm_name")
    VM_AFFECTED_RUNNING+=("$run")
    VM_AFFECTED_ONBOOT+=("$onb")
  done
}

# HYBRID: VM conflict policy prompt
prompt_vm_action_for_lxc_mode() {
  [[ ${#VM_AFFECTED_IDS[@]} -eq 0 ]] && return 0

  local running_count=0 onboot_count=0 i
  for i in "${!VM_AFFECTED_IDS[@]}"; do
    [[ "${VM_AFFECTED_RUNNING[$i]}" == "1" ]] && running_count=$((running_count + 1))
    [[ "${VM_AFFECTED_ONBOOT[$i]}" == "1" ]] && onboot_count=$((onboot_count + 1))
  done

  local msg
  msg="$(translate 'The selected GPU(s) are configured in these VM(s)'):\n\n"
  for i in "${!VM_AFFECTED_IDS[@]}"; do
    local st ob
    st="$(translate 'stopped')"; ob="onboot=0"
    [[ "${VM_AFFECTED_RUNNING[$i]}" == "1" ]] && st="$(translate 'running')"
    [[ "${VM_AFFECTED_ONBOOT[$i]}" == "1" ]] && ob="onboot=1"
    msg+="  - VM ${VM_AFFECTED_IDS[$i]} (${VM_AFFECTED_NAMES[$i]}) [${st}, ${ob}]\n"
  done
  msg+="\n$(translate 'Switching to GPU -> LXC mode removes VFIO exclusivity.')\n"
  [[ "$running_count" -gt 0 ]] && msg+="$(translate 'Running VM detected'): ${running_count}\n"
  [[ "$onboot_count" -gt 0 ]] && msg+="$(translate 'Start on boot enabled'): ${onboot_count}\n"
  msg+="\n$(translate 'Choose conflict policy'):"

  local choice
  choice=$(hybrid_menu "$(translate 'VM Conflict Policy')" "$msg" 24 80 8 \
    "1" "$(translate 'Keep GPU in VM config (disable Start on boot)')" \
    "2" "$(translate 'Remove GPU from VM config (keep Start on boot)')")

  case "$choice" in
    1) VM_ACTION="keep_gpu_disable_onboot" ;;
    2) VM_ACTION="remove_gpu_keep_onboot" ;;
    *) 
      msg_warn "$(translate 'Operation cancelled by user')"
      exit 0 
      ;;
  esac
}

apply_vm_action_for_lxc_mode() {
  [[ ${#VM_AFFECTED_IDS[@]} -eq 0 ]] && return 0

  local i
  for i in "${!VM_AFFECTED_IDS[@]}"; do
    local vmid conf
    vmid="${VM_AFFECTED_IDS[$i]}"
    conf="/etc/pve/qemu-server/${vmid}.conf"

    if [[ "${VM_AFFECTED_RUNNING[$i]}" == "1" ]]; then
      msg_info "$(translate 'Stopping VM') ${vmid}..."
      qm stop "$vmid" >>"$LOG_FILE" 2>&1 || true
      msg_ok "$(translate 'VM stopped') ${vmid}" | tee -a "$screen_capture"
    fi

    if [[ "$VM_ACTION" == "keep_gpu_disable_onboot" && "${VM_AFFECTED_ONBOOT[$i]}" == "1" ]]; then
      if qm set "$vmid" -onboot 0 >>"$LOG_FILE" 2>&1; then
        msg_warn "$(translate 'Start on boot disabled for VM') ${vmid}" | tee -a "$screen_capture"
      fi
    fi

    if [[ "$VM_ACTION" == "remove_gpu_keep_onboot" && -f "$conf" ]]; then
      # Primary cleanup: strip hostpci lines whose BDF matches any of
      # the GPU's selected slots. Matches both the PF function (.0) and
      # sibling audio/HDMI codecs (.1, typical for discrete cards).
      #
      # Precise regex: the slot must be followed by ".<function>" and a
      # delimiter. Kept in sync with switch_gpu_mode.sh — a looser
      # substring match would wipe unrelated hostpci entries (e.g. slot
      # "00:02" matching as a substring inside a dGPU BDF 0000:02:00.0).
      local slot
      for slot in "${SELECTED_PCI_SLOTS[@]}"; do
        sed -E -i "/^hostpci[0-9]+:[[:space:]]*(0000:)?${slot}\.[0-7]([,[:space:]]|$)/d" "$conf"
      done
      msg_ok "$(translate 'GPU removed from VM config') ${vmid}" | tee -a "$screen_capture"

      # Cascade cleanup for the web flow: auto-remove any PCI audio
      # hostpci entries at a slot DIFFERENT from the GPU (typical Intel
      # iGPU case where 00:1f.3 chipset audio was paired with the iGPU
      # at 00:02.0). The helper skips audio devices whose slot already
      # has a display sibling in the same VM (HDMI codec of another
      # still-present dGPU), so those are not touched. The web runner
      # has no good way to render a multi-select checklist, so the
      # eligible ones are auto-removed and reported verbatim in the log.
      if declare -F _vm_list_orphan_audio_hostpci >/dev/null 2>&1; then
        local _orphan_audio _line _o_idx _o_bdf _o_name _removed=""
        local _vd_hex _dd_hex _vd_id
        _orphan_audio=$(_vm_list_orphan_audio_hostpci "$vmid" "${SELECTED_PCI_SLOTS[0]}")
        if [[ -n "$_orphan_audio" ]]; then
          while IFS= read -r _line; do
            [[ -z "$_line" ]] && continue
            _o_idx="${_line%%|*}"
            _line="${_line#*|}"
            _o_bdf="${_line%%|*}"
            _o_name="${_line#*|}"
            if _vm_remove_hostpci_index "$vmid" "$_o_idx" "$LOG_FILE"; then
              _removed+="  • hostpci${_o_idx}: ${_o_bdf}  ${_o_name}\n"

              # Fix B: also surface the audio's vendor:device to the
              # upcoming vfio.conf cleanup if no other VM still uses
              # this BDF. Ensures e.g. 8086:51c8 (Intel chipset audio)
              # is stripped from /etc/modprobe.d/vfio.conf when the
              # iGPU it was paired with leaves VM mode.
              if declare -F _pci_bdf_in_any_vm >/dev/null 2>&1 \
                 && ! _pci_bdf_in_any_vm "$_o_bdf" "${VM_AFFECTED_IDS[@]}"; then
                _vd_hex=$(cat "/sys/bus/pci/devices/${_o_bdf}/vendor" 2>/dev/null | sed 's/^0x//')
                _dd_hex=$(cat "/sys/bus/pci/devices/${_o_bdf}/device" 2>/dev/null | sed 's/^0x//')
                if [[ -n "$_vd_hex" && -n "$_dd_hex" ]]; then
                  _vd_id="${_vd_hex}:${_dd_hex}"
                  if ! _contains_in_array "$_vd_id" "${SELECTED_IOMMU_IDS[@]}"; then
                    SELECTED_IOMMU_IDS+=("$_vd_id")
                  fi
                fi
              fi
            fi
          done <<< "$_orphan_audio"
          if [[ -n "$_removed" ]]; then
            msg_ok "$(translate 'Associated audio removed from VM'): ${vmid}" \
              | tee -a "$screen_capture"
            echo -e "$_removed" | tee -a "$screen_capture"
          fi
        fi
      fi
    fi
  done
}

# ==========================================================
# Switch Mode Functions
# ==========================================================
_register_iommu_tool() {
  local tools_json="${BASE_DIR:-/usr/local/share/proxmenux}/installed_tools.json"
  command -v jq >/dev/null 2>&1 || return 0
  [[ -f "$tools_json" ]] || echo "{}" > "$tools_json"
  jq '.vfio_iommu=true' "$tools_json" > "$tools_json.tmp" \
    && mv "$tools_json.tmp" "$tools_json" || true
}

_enable_iommu_cmdline() {
  local cpu_vendor
  cpu_vendor=$(grep -m1 "vendor_id" /proc/cpuinfo 2>/dev/null | awk '{print $3}')

  local iommu_param
  if [[ "$cpu_vendor" == "GenuineIntel" ]]; then
    iommu_param="intel_iommu=on"
  elif [[ "$cpu_vendor" == "AuthenticAMD" ]]; then
    iommu_param="amd_iommu=on"
  else
    return 1
  fi

  local cmdline_file="/etc/kernel/cmdline"
  local grub_file="/etc/default/grub"

  if [[ -f "$cmdline_file" ]] && grep -qE 'root=ZFS=|root=ZFS/' "$cmdline_file" 2>/dev/null; then
    if ! grep -q "$iommu_param" "$cmdline_file"; then
      cp "$cmdline_file" "${cmdline_file}.bak.$(date +%Y%m%d_%H%M%S)"
      sed -i "s|\\s*$| ${iommu_param} iommu=pt|" "$cmdline_file"
      proxmox-boot-tool refresh >>"$LOG_FILE" 2>&1 || true
    fi
  elif [[ -f "$grub_file" ]]; then
    if ! grep -q "$iommu_param" "$grub_file"; then
      cp "$grub_file" "${grub_file}.bak.$(date +%Y%m%d_%H%M%S)"
      sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$| ${iommu_param} iommu=pt\"|" "$grub_file"
      update-grub >>"$LOG_FILE" 2>&1 || true
    fi
  else
    return 1
  fi
  return 0
}

switch_to_vm_mode() {
  detect_affected_lxc_for_selected
  prompt_lxc_action_for_vm_mode

  _set_title
  collect_selected_iommu_ids
  apply_lxc_action_for_vm_mode

  msg_info "$(translate 'Configuring host for GPU -> VM mode...')"

  if declare -F _pci_is_iommu_active >/dev/null 2>&1 && _pci_is_iommu_active; then
    _register_iommu_tool
    msg_ok "$(translate 'IOMMU is already active on this system')" | tee -a "$screen_capture"
  elif grep -qE 'intel_iommu=on|amd_iommu=on' /etc/kernel/cmdline 2>/dev/null || \
       grep -qE 'intel_iommu=on|amd_iommu=on' /etc/default/grub 2>/dev/null; then
    _register_iommu_tool
    HOST_CONFIG_CHANGED=true
    msg_ok "$(translate 'IOMMU already configured in kernel parameters')" | tee -a "$screen_capture"
  else
    if _enable_iommu_cmdline; then
      _register_iommu_tool
      HOST_CONFIG_CHANGED=true
      msg_ok "$(translate 'IOMMU kernel parameters configured')" | tee -a "$screen_capture"
    else
      msg_warn "$(translate 'Could not configure IOMMU kernel parameters automatically. Configure manually and reboot.')" | tee -a "$screen_capture"
    fi
  fi

  _add_vfio_modules
  msg_ok "$(translate 'VFIO modules configured in /etc/modules')" | tee -a "$screen_capture"
  _configure_iommu_options
  msg_ok "$(translate 'IOMMU interrupt remapping configured')" | tee -a "$screen_capture"

  local -a current_ids=()
  mapfile -t current_ids < <(_read_vfio_ids)
  local id
  for id in "${SELECTED_IOMMU_IDS[@]}"; do
    _contains_in_array "$id" "${current_ids[@]}" || current_ids+=("$id")
  done
  _write_vfio_ids "${current_ids[@]}"
  if [[ ${#SELECTED_IOMMU_IDS[@]} -gt 0 ]]; then
    local ids_label
    ids_label=$(IFS=','; echo "${SELECTED_IOMMU_IDS[*]}")
    msg_ok "$(translate 'vfio-pci IDs configured') (${ids_label})" | tee -a "$screen_capture"
  fi

  local -a selected_types=()
  mapfile -t selected_types < <(_selected_types_unique)
  local t
  for t in "${selected_types[@]}"; do
    _add_gpu_blacklist "$t"
  done
  msg_ok "$(translate 'GPU host driver blacklisted in /etc/modprobe.d/blacklist.conf')" | tee -a "$screen_capture"
  _contains_in_array "nvidia" "${selected_types[@]}" && _sanitize_nvidia_host_stack_for_vfio
  _contains_in_array "amd" "${selected_types[@]}" && _add_amd_softdep

  if [[ "$HOST_CONFIG_CHANGED" == "true" ]]; then
    msg_info "$(translate 'Updating initramfs (this may take a minute)...')"
    update-initramfs -u -k all >>"$LOG_FILE" 2>&1
    msg_ok "$(translate 'initramfs updated')" | tee -a "$screen_capture"
  fi
}

_type_has_remaining_vfio_ids() {
  local gpu_type="$1"
  local -a remaining_ids=("$@")
  remaining_ids=("${remaining_ids[@]:1}")
  local idx viddid
  for idx in "${!ALL_GPU_TYPES[@]}"; do
    [[ "${ALL_GPU_TYPES[$idx]}" != "$gpu_type" ]] && continue
    viddid="${ALL_GPU_VIDDID[$idx]}"
    _contains_in_array "$viddid" "${remaining_ids[@]}" && return 0
  done
  return 1
}

switch_to_lxc_mode() {
  collect_selected_iommu_ids
  detect_affected_vms_for_selected
  prompt_vm_action_for_lxc_mode

  _set_title
  apply_vm_action_for_lxc_mode

  msg_info "$(translate 'Removing VFIO ownership for selected GPU(s)...')"

  local -a current_ids=() remaining_ids=() removed_ids=()
  mapfile -t current_ids < <(_read_vfio_ids)
  local id remove
  for id in "${current_ids[@]}"; do
    remove=false
    _contains_in_array "$id" "${SELECTED_IOMMU_IDS[@]}" && remove=true
    if $remove; then
      removed_ids+=("$id")
    else
      remaining_ids+=("$id")
    fi
  done
  _write_vfio_ids "${remaining_ids[@]}"
  if [[ ${#removed_ids[@]} -gt 0 ]]; then
    local ids_label
    ids_label=$(IFS=','; echo "${removed_ids[*]}")
    msg_ok "$(translate 'VFIO device IDs removed from /etc/modprobe.d/vfio.conf') (${ids_label})" | tee -a "$screen_capture"
  fi

  local -a selected_types=()
  mapfile -t selected_types < <(_selected_types_unique)
  local t
  for t in "${selected_types[@]}"; do
    if ! _type_has_remaining_vfio_ids "$t" "${remaining_ids[@]}"; then
      if _remove_gpu_blacklist "$t"; then
        msg_ok "$(translate 'Driver blacklist removed for') ${t}" | tee -a "$screen_capture"
      fi
      if [[ "$t" == "nvidia" ]]; then
        _restore_nvidia_host_stack_for_lxc
      fi
    fi
  done

  if ! _type_has_remaining_vfio_ids "amd" "${remaining_ids[@]}"; then
    _remove_amd_softdep || true
  fi

  if _remove_vfio_modules_if_unused; then
    msg_ok "$(translate 'VFIO modules removed from /etc/modules')" | tee -a "$screen_capture"
  fi

  if [[ "$HOST_CONFIG_CHANGED" == "true" ]]; then
    msg_info "$(translate 'Updating initramfs (this may take a minute)...')"
    update-initramfs -u -k all >>"$LOG_FILE" 2>&1
    msg_ok "$(translate 'initramfs updated')" | tee -a "$screen_capture"
  fi
}

# HYBRID: Confirmation prompt
confirm_plan() {
  local msg mode_line
  if [[ "$TARGET_MODE" == "vm" ]]; then
    mode_line="$(translate 'Target mode'): GPU -> VM (VFIO)"
  else
    mode_line="$(translate 'Target mode'): GPU -> LXC (native driver)"
  fi

  msg="${mode_line}\n\n$(translate 'Selected GPU(s)'):\n"
  local idx
  for idx in "${SELECTED_GPU_IDX[@]}"; do
    msg+="  - ${ALL_GPU_NAMES[$idx]} (${ALL_GPU_PCIS[$idx]}) [${ALL_GPU_DRIVERS[$idx]}]\n"
  done
  msg+="\n$(translate 'Do you want to proceed?')"

  if ! hybrid_yesno "$(translate 'Confirm GPU Switch Mode')" "$msg" 18 88; then
    msg_warn "$(translate 'Operation cancelled by user')"
    exit 0
  fi
}

# HYBRID: Final summary with reboot prompt
final_summary() {
  _set_title
  cat "$screen_capture"
  echo
  echo -e "${TAB}${BL}Log: ${LOG_FILE}${CL}"

  if [[ "$HOST_CONFIG_CHANGED" == "true" ]]; then
    echo -e "${TAB}${DGN}- $(translate 'Host GPU binding changed — reboot required.')${CL}"
    
    if hybrid_yesno "$(translate 'Reboot Required')" "$(translate 'A reboot is required to apply the new GPU mode. Do you want to restart now?')" 10 74; then
      msg_warn "$(translate 'Rebooting the system...')"
      reboot
    else
      msg_info2 "$(translate 'Please reboot manually to complete the switch.')"
      hybrid_msgbox "$(translate 'Reboot Required')" "$(translate 'Please reboot the system manually to complete the GPU switch.')" 8 60
    fi
  else
    echo -e "${TAB}${DGN}- $(translate 'No host VFIO/native binding changes were required.')${CL}"
    hybrid_msgbox "$(translate 'Complete')" "$(translate 'GPU switch mode completed. No reboot required.')" 8 60
  fi
}

# ==========================================================
# Parse Arguments (supports both CLI args and env vars)
# ==========================================================
# Send notification when GPU mode switch completes
# ==========================================================
_send_gpu_mode_notification() {
  local new_mode="$1"
  local gpu_name="$2"
  local gpu_pci="$3"
  local old_mode="$4"
  local notify_script="/usr/bin/notification_manager.py"
  
  [[ ! -f "$notify_script" ]] && return 0
  
  local hostname_short
  hostname_short=$(hostname -s)
  
  local mode_label details
  if [[ "$new_mode" == "vm" ]]; then
    mode_label="GPU -> VM (VFIO passthrough)"
    details="GPU is now ready for VM passthrough. A host reboot may be required."
  else
    mode_label="GPU -> LXC (native driver)"
    details="GPU is now available for LXC containers with native drivers."
  fi
  
  python3 "$notify_script" --action send-raw --severity INFO \
    --title "${hostname_short}: GPU mode changed to ${mode_label}" \
    --message "GPU passthrough mode switched.
GPU: ${gpu_name} (${gpu_pci})
Previous: ${old_mode}
New: ${mode_label}
${details}" 2>/dev/null || true
}

# ==========================================================
parse_arguments() {
  # First, check combined parameter (format: "SLOT|MODE")
  # This is the primary method used by ProxMenux Monitor
  if [[ -n "$GPU_SWITCH_PARAMS" ]]; then
    PARAM_GPU_SLOT="${GPU_SWITCH_PARAMS%%|*}"
    PARAM_TARGET_MODE="${GPU_SWITCH_PARAMS##*|}"
  fi
  
  # Also check individual environment variables as fallback
  [[ -n "$GPU_SLOT" ]] && PARAM_GPU_SLOT="$GPU_SLOT"
  [[ -n "$TARGET_MODE" ]] && PARAM_TARGET_MODE="$TARGET_MODE"
  
  # Then, parse command line arguments (override env vars if provided)
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --gpu-slot=*)
        PARAM_GPU_SLOT="${1#*=}"
        ;;
      --target-mode=*)
        PARAM_TARGET_MODE="${1#*=}"
        ;;
      *)
        # Ignore unknown arguments
        ;;
    esac
    shift
  done
}

# ==========================================================
# Main Entry Point
# ==========================================================
main() {
  : >"$LOG_FILE"
  : >"$screen_capture"

  parse_arguments "$@"

  # Validate required parameters
  if [[ -z "$PARAM_GPU_SLOT" ]]; then
    msg_error "$(translate 'Missing required parameter'): --gpu-slot"
    echo "Usage: $0 --gpu-slot=0000:01:00.0 --target-mode=vm|lxc"
    exit 1
  fi

  if [[ -z "$PARAM_TARGET_MODE" ]] || [[ ! "$PARAM_TARGET_MODE" =~ ^(vm|lxc)$ ]]; then
    msg_error "$(translate 'Missing or invalid parameter'): --target-mode (must be 'vm' or 'lxc')"
    echo "Usage: $0 --gpu-slot=0000:01:00.0 --target-mode=vm|lxc"
    exit 1
  fi

  TARGET_MODE="$PARAM_TARGET_MODE"

  # Detect all GPUs
  detect_host_gpus
  
  if [[ "$GPU_COUNT" -eq 0 ]]; then
    msg_error "$(translate 'No GPUs detected on this host.')"
    exit 1
  fi

  # Find the specific GPU by slot
  if ! find_gpu_by_slot "$PARAM_GPU_SLOT"; then
    exit 1
  fi

  # SR-IOV guard: refuse to toggle the driver on a VF or on a PF with
  # active VFs. Manual handling via Proxmox web UI is required.
  if ! check_sriov_and_block_if_needed; then
    exit 1
  fi

  # Validate if GPU is blocked for VM mode (certain Intel GPUs)
  if ! validate_vm_mode_blocked_ids; then
    exit 1
  fi

 
  # Confirm the operation
  confirm_plan

  clear
  _set_title
  echo

  # Determine old mode before switch for notification
  local old_mode_label
  if [[ "$CURRENT_MODE" == "vm" ]]; then
    old_mode_label="GPU -> VM (VFIO)"
  else
    old_mode_label="GPU -> LXC (native)"
  fi
  
  # Get GPU info for notification
  local gpu_idx="${SELECTED_GPU_IDX[0]}"
  local gpu_name="${ALL_GPU_NAMES[$gpu_idx]}"
  local gpu_pci="${ALL_GPU_PCIS[$gpu_idx]}"

  # Execute the switch
  if [[ "$TARGET_MODE" == "vm" ]]; then
    switch_to_vm_mode
    msg_success "$(translate 'GPU switch complete: VM mode prepared.')"
    _send_gpu_mode_notification "vm" "$gpu_name" "$gpu_pci" "$old_mode_label"
  else
    switch_to_lxc_mode
    msg_success "$(translate 'GPU switch complete: LXC mode prepared.')"
    _send_gpu_mode_notification "lxc" "$gpu_name" "$gpu_pci" "$old_mode_label"
  fi

  final_summary
  rm -f "$screen_capture"
}

main "$@"
