#!/bin/bash
# ==========================================================
# ProxMenux - GPU / iGPU Passthrough to LXC
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 01/04/2026
# ==========================================================
# Description:
# Shares a physical GPU (Intel iGPU, AMD or NVIDIA) with an
# LXC container on Proxmox VE. Unlike VM passthrough, the
# host keeps using the GPU — containers access it through
# device nodes, not via VFIO binding.
#
# Features:
#  - Multi-vendor detection (Intel / AMD / NVIDIA)
#  - Multi-GPU selection via checklist
#  - Switch Mode: detects GPU bound to vfio-pci (VM) and
#    offers to free it before LXC passthrough
#  - SR-IOV check (blocks unsupported configurations)
#  - Automatic dev-node enumeration (DRI, KFD, NVIDIA)
#  - GID alignment (video / render) between host and CT
#  - Distro-aware driver install inside the container
#    (Alpine / Arch / Debian-Ubuntu / NVIDIA .run fallback)
#  - NVIDIA userspace version matched to host driver
#  - Container memory bump during NVIDIA install (restored)
#  - Optional GPU guard hookscript integration
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
LOG_FILE="/tmp/add_gpu_lxc.log"
NVIDIA_WORKDIR="/opt/nvidia"
INSTALL_ABORTED=false
NVIDIA_INSTALL_SUCCESS=false
NVIDIA_SMI_OUTPUT=""
screen_capture="/tmp/proxmenux_add_gpu_screen_capture_$$.txt"
LXC_SWITCH_MODE=false

INTEL_PCI=""
INTEL_VID_DID=""
AMD_PCI=""
AMD_VID_DID=""
NVIDIA_PCI=""
NVIDIA_VID_DID=""

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS/global/pci_passthrough_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS/global/pci_passthrough_helpers.sh"
elif [[ -f "$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)/global/pci_passthrough_helpers.sh" ]]; then
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)/global/pci_passthrough_helpers.sh"
fi
if [[ -f "$LOCAL_SCRIPTS/global/gpu_hook_guard_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS/global/gpu_hook_guard_helpers.sh"
elif [[ -f "$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)/global/gpu_hook_guard_helpers.sh" ]]; then
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)/global/gpu_hook_guard_helpers.sh"
fi

load_language
initialize_cache


# ============================================================
# Helper: next available devN index in LXC config
# ============================================================
get_next_dev_index() {
  local config="$1"
  local idx=0
  while grep -q "^dev${idx}:" "$config" 2>/dev/null; do
    idx=$((idx + 1))
  done
  echo "$idx"
}

_get_lxc_run_title() {
  if [[ "$LXC_SWITCH_MODE" == "true" ]]; then
    echo "GPU Switch Mode (VM → LXC)"
  else
    echo "$(translate 'Add GPU to LXC')"
  fi
}

_gpu_type_label() {
  case "$1" in
    intel)  echo "${INTEL_NAME:-Intel iGPU}" ;;
    amd)    echo "${AMD_NAME:-AMD GPU}" ;;
    nvidia) echo "${NVIDIA_NAME:-NVIDIA GPU}" ;;
    *)      echo "$1" ;;
  esac
}

_config_has_dev_entry() {
  local cfg="$1"
  local dev="$2"
  local dev_escaped
  dev_escaped=$(printf '%s' "$dev" | sed 's/[][(){}.^$*+?|\\]/\\&/g')
  grep -qE "^dev[0-9]+:.*${dev_escaped}([,[:space:]]|$)" "$cfg" 2>/dev/null
}

_is_lxc_gpu_already_configured() {
  local cfg="$1"
  local gpu_type="$2"
  local dev

  case "$gpu_type" in
    intel)
      local have_dri=0
      for dev in /dev/dri/card0 /dev/dri/card1 /dev/dri/renderD128 /dev/dri/renderD129; do
        [[ -c "$dev" ]] || continue
        have_dri=1
        _config_has_dev_entry "$cfg" "$dev" || return 1
      done
      [[ $have_dri -eq 1 ]] || return 1
      return 0
      ;;
    amd)
      local have_dri=0
      for dev in /dev/dri/card0 /dev/dri/card1 /dev/dri/renderD128 /dev/dri/renderD129; do
        [[ -c "$dev" ]] || continue
        have_dri=1
        _config_has_dev_entry "$cfg" "$dev" || return 1
      done
      [[ $have_dri -eq 1 ]] || return 1
      if [[ -c "/dev/kfd" ]]; then
        _config_has_dev_entry "$cfg" "/dev/kfd" || return 1
      fi
      return 0
      ;;
    nvidia)
      local -a nv_devs=()
      for dev in /dev/nvidia[0-9]* /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools /dev/nvidia-modeset; do
        [[ -c "$dev" ]] && nv_devs+=("$dev")
      done
      if [[ -d /dev/nvidia-caps ]]; then
        for dev in /dev/nvidia-caps/nvidia-cap[0-9]*; do
          [[ -c "$dev" ]] && nv_devs+=("$dev")
        done
      fi
      [[ ${#nv_devs[@]} -gt 0 ]] || return 1
      for dev in "${nv_devs[@]}"; do
        _config_has_dev_entry "$cfg" "$dev" || return 1
      done
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

precheck_existing_lxc_gpu_config() {
  local cfg="/etc/pve/lxc/${CONTAINER_ID}.conf"
  [[ -f "$cfg" ]] || return 0

  local -a already_present=() missing=()
  local gpu_type
  for gpu_type in "${SELECTED_GPUS[@]}"; do
    if _is_lxc_gpu_already_configured "$cfg" "$gpu_type"; then
      already_present+=("$gpu_type")
    else
      missing+=("$gpu_type")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    local msg labels=""
    for gpu_type in "${already_present[@]}"; do
      labels+="  •  $(_gpu_type_label "$gpu_type")\n"
    done
    msg="\n$(translate 'The selected GPU configuration already exists in this container.')\n\n"
    msg+="$(translate 'No changes are required for') ${CONTAINER_ID}:\n\n${labels}"
    dialog --backtitle "ProxMenux" \
      --title "$(_get_lxc_run_title)" \
      --msgbox "$msg" 14 74
    exit 0
  fi

  if [[ ${#already_present[@]} -gt 0 ]]; then
    local msg already_labels="" missing_labels=""
    for gpu_type in "${already_present[@]}"; do
      already_labels+="  •  $(_gpu_type_label "$gpu_type")\n"
    done
    for gpu_type in "${missing[@]}"; do
      missing_labels+="  •  $(_gpu_type_label "$gpu_type")\n"
    done
    msg="\n$(translate 'Some selected GPUs are already configured in this container.')\n\n"
    msg+="$(translate 'Already configured'):\n${already_labels}\n"
    msg+="$(translate 'Will be configured now'):\n${missing_labels}"
    dialog --backtitle "ProxMenux" \
      --title "$(_get_lxc_run_title)" \
      --msgbox "$msg" 18 78
  fi

  SELECTED_GPUS=("${missing[@]}")
}


# ============================================================
# GPU detection on host
# ============================================================
detect_host_gpus() {
  HAS_INTEL=false
  HAS_AMD=false
  HAS_NVIDIA=false
  NVIDIA_READY=false
  NVIDIA_HOST_VERSION=""
  INTEL_NAME=""
  AMD_NAME=""
  NVIDIA_NAME=""
  INTEL_PCI=""
  INTEL_VID_DID=""
  AMD_PCI=""
  AMD_VID_DID=""
  NVIDIA_PCI=""
  NVIDIA_VID_DID=""

  local intel_line amd_line nvidia_line
  intel_line=$(lspci -nn | grep -iE "VGA compatible|3D controller|Display controller" \
    | grep -i "Intel" | grep -iv "Ethernet\|Audio\|Network" | head -1)
  amd_line=$(lspci -nn | grep -iE "VGA compatible|3D controller|Display controller" \
    | grep -iE "AMD|Advanced Micro|Radeon" | head -1)
  nvidia_line=$(lspci -nn | grep -iE "VGA compatible|3D controller|Display controller" \
    | grep -i "NVIDIA" | head -1)

  if [[ -n "$intel_line" ]]; then
    HAS_INTEL=true
    INTEL_NAME=$(echo "$intel_line" | sed 's/^[^:]*[^:]: //' | sed 's/ \[.*//' | cut -c1-58)
    INTEL_PCI="0000:$(echo "$intel_line" | awk '{print $1}')"
    INTEL_VID_DID=$(echo "$intel_line" | grep -oE '\[[0-9a-f]{4}:[0-9a-f]{4}\]' | tr -d '[]')
  fi
  if [[ -n "$amd_line" ]]; then
    HAS_AMD=true
    AMD_NAME=$(echo "$amd_line" | sed 's/^[^:]*[^:]: //' | sed 's/ \[.*//' | cut -c1-58)
    AMD_PCI="0000:$(echo "$amd_line" | awk '{print $1}')"
    AMD_VID_DID=$(echo "$amd_line" | grep -oE '\[[0-9a-f]{4}:[0-9a-f]{4}\]' | tr -d '[]')
  fi
  if [[ -n "$nvidia_line" ]]; then
    HAS_NVIDIA=true
    NVIDIA_NAME=$(echo "$nvidia_line" | sed 's/^[^:]*[^:]: //' | sed 's/ \[.*//' | cut -c1-58)
    NVIDIA_PCI="0000:$(echo "$nvidia_line" | awk '{print $1}')"
    NVIDIA_VID_DID=$(echo "$nvidia_line" | grep -oE '\[[0-9a-f]{4}:[0-9a-f]{4}\]' | tr -d '[]')
    if lsmod | grep -q "^nvidia " && command -v nvidia-smi >/dev/null 2>&1; then
      NVIDIA_HOST_VERSION=$(nvidia-smi --query-gpu=driver_version \
        --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]')
      [[ -n "$NVIDIA_HOST_VERSION" ]] && NVIDIA_READY=true
    fi
  fi
}


# ============================================================
# Container selection
# ============================================================
select_container() {
  local menu_items=()
  while IFS= read -r line; do
    [[ "$line" =~ ^VMID ]] && continue
    local ctid status name
    ctid=$(echo "$line" | awk '{print $1}')
    status=$(echo "$line" | awk '{print $2}')
    name=$(echo "$line" | awk '{print $3}')
    [[ -z "$ctid" ]] && continue
    menu_items+=("$ctid" "${name:-CT-${ctid}} (${status})")
  done < <(pct list 2>/dev/null)

  if [[ ${#menu_items[@]} -eq 0 ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate 'Add GPU to LXC')" \
      --msgbox "\n$(translate 'No LXC containers found on this system.')" 8 60
    exit 0
  fi

  CONTAINER_ID=$(dialog --backtitle "ProxMenux" \
    --title "$(translate 'Add GPU to LXC')" \
    --menu "\n$(translate 'Select the LXC container:')" 20 72 12 \
    "${menu_items[@]}" \
    2>&1 >/dev/tty) || exit 0
}


# ============================================================
# GPU checklist selection
# ============================================================
# ============================================================
# SR-IOV guard — refuse to pass an SR-IOV GPU to an LXC via ProxMenux.
# Although the LXC flow does not rewrite vfio.conf/blacklist (so it is
# not destructive like add_gpu_vm.sh), it blindly globs /dev/dri/card*
# and /dev/dri/renderD* without mapping each node to its BDF. With 7
# VFs the container may end up holding any/all of them, which is not
# the behavior a user asking for "one VF to this LXC" expects. Until a
# VF-aware LXC flow exists, stop and point to manual configuration —
# matching the policy used in switch_gpu_mode.sh and add_gpu_vm.sh.
# ============================================================
check_sriov_and_block_if_needed() {
  declare -F _pci_sriov_role >/dev/null 2>&1 || return 0

  local gpu_type pci role first_word
  local -a offenders=()

  for gpu_type in "${SELECTED_GPUS[@]}"; do
    case "$gpu_type" in
      intel)  pci="$INTEL_PCI" ;;
      amd)    pci="$AMD_PCI" ;;
      nvidia) pci="$NVIDIA_PCI" ;;
      *)      continue ;;
    esac
    [[ -n "$pci" ]] || continue

    role=$(_pci_sriov_role "$pci")
    first_word="${role%% *}"
    case "$first_word" in
      vf)
        offenders+=("${pci}|vf|${role#vf }")
        ;;
      pf-active)
        offenders+=("${pci}|pf-active|${role#pf-active }")
        ;;
    esac
  done

  [[ ${#offenders[@]} -eq 0 ]] && return 0

  local msg entry bdf kind info
  msg="\n\Zb\Z6$(translate 'SR-IOV Configuration Detected')\Zn\n\n"
  for entry in "${offenders[@]}"; do
    bdf="${entry%%|*}"
    kind="${entry#*|}"; kind="${kind%%|*}"
    info="${entry##*|}"
    if [[ "$kind" == "vf" ]]; then
      msg+="  •  \Zb${bdf}\Zn — $(translate 'Virtual Function (parent PF:') ${info})\n"
    else
      msg+="  •  \Zb${bdf}\Zn — $(translate 'Physical Function with') ${info} $(translate 'active VFs')\n"
    fi
  done
  msg+="\n$(translate 'To pass SR-IOV Virtual Functions to a container, edit the LXC configuration manually via the Proxmox web interface. The Physical Function will remain bound to the native driver.')"

  dialog --backtitle "ProxMenux" --colors \
    --title "$(translate 'SR-IOV Configuration Detected')" \
    --msgbox "$msg" 16 82

  exit 0
}


select_gpus() {
  local gpu_items=()
  $HAS_INTEL  && gpu_items+=("intel"  "${INTEL_NAME:-Intel iGPU}"  "off")
  $HAS_AMD    && gpu_items+=("amd"    "${AMD_NAME:-AMD GPU}"        "off")
  $HAS_NVIDIA && gpu_items+=("nvidia" "${NVIDIA_NAME:-NVIDIA GPU}"  "off")

  local count=$(( ${#gpu_items[@]} / 3 ))

  if [[ $count -eq 0 ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate 'Add GPU to LXC')" \
      --msgbox "\n$(translate 'No compatible GPUs detected on this host.')" 8 60
    exit 0
  fi

  # Only one GPU — auto-select without menu
  if [[ $count -eq 1 ]]; then
    SELECTED_GPUS=("${gpu_items[0]}")
    return
  fi

  # Multiple GPUs — checklist with loop on empty selection
  while true; do
    local raw_selection
    raw_selection=$(dialog --backtitle "ProxMenux" \
      --title "$(translate 'Add GPU to LXC')" \
      --checklist "\n$(translate 'Select the GPU(s) to add to LXC') ${CONTAINER_ID}:" \
      18 80 10 \
      "${gpu_items[@]}" \
      2>&1 >/dev/tty) || exit 0

    local selection
    selection=$(echo "$raw_selection" | tr -d '"')

    if [[ -z "$selection" ]]; then
      dialog --backtitle "ProxMenux" \
        --title "$(translate 'Add GPU to LXC')" \
        --msgbox "\n$(translate 'No GPU selected. Please select at least one GPU to continue.')" 8 68
      continue
    fi

    read -ra SELECTED_GPUS <<< "$selection"
    break
  done
}


# ============================================================
# NVIDIA host driver readiness check
# ============================================================
check_nvidia_ready() {
  if ! $NVIDIA_READY; then
    dialog --colors --backtitle "ProxMenux" \
      --title "$(translate 'NVIDIA Drivers Not Found')" \
      --msgbox "\n\Z1\Zb$(translate 'NVIDIA drivers are not installed or not loaded on this host.')\Zn\n\n$(translate 'Please install the NVIDIA drivers first using the option:')\n\n  \Z1\Zb$(translate 'Install NVIDIA Drivers on Host')\Zn\n\n$(translate 'available in this same GPU and TPU menu.')" \
      14 72
    exit 0
  fi
}


# ============================================================
# LXC config: DRI device passthrough (Intel / AMD shared)
# ============================================================
_configure_dri_devices() {
  local cfg="$1"
  local video_gid render_gid idx gid

  video_gid=$(getent group video  2>/dev/null | cut -d: -f3); [[ -z "$video_gid"  ]] && video_gid="44"
  render_gid=$(getent group render 2>/dev/null | cut -d: -f3); [[ -z "$render_gid" ]] && render_gid="104"

  # Remove any pre-existing lxc.mount.entry for /dev/dri — it conflicts with devN: entries
  sed -i '/lxc\.mount\.entry:.*dev\/dri.*bind/d' "$cfg" 2>/dev/null || true

  for dri_dev in /dev/dri/card0 /dev/dri/card1 /dev/dri/renderD128 /dev/dri/renderD129; do
    [[ ! -c "$dri_dev" ]] && continue
    if ! grep -qE "dev[0-9]+:.*${dri_dev}[^0-9/]" "$cfg" 2>/dev/null; then
      idx=$(get_next_dev_index "$cfg")
      case "$dri_dev" in
        /dev/dri/renderD*) gid="$render_gid" ;;
        *)                  gid="$video_gid"  ;;
      esac
      echo "dev${idx}: ${dri_dev},gid=${gid}" >> "$cfg"
    fi
  done
}

_configure_intel() {
  local cfg="$1"
  _configure_dri_devices "$cfg"
}

_configure_amd() {
  local cfg="$1"
  local render_gid idx

  _configure_dri_devices "$cfg"

  # /dev/kfd for ROCm / compute workloads
  if [[ -c "/dev/kfd" ]]; then
    render_gid=$(getent group render 2>/dev/null | cut -d: -f3)
    [[ -z "$render_gid" ]] && render_gid="104"
    if ! grep -q "dev.*/dev/kfd" "$cfg" 2>/dev/null; then
      idx=$(get_next_dev_index "$cfg")
      echo "dev${idx}: /dev/kfd,gid=${render_gid}" >> "$cfg"
    fi
  fi
}

_configure_nvidia() {
  local cfg="$1"
  local idx dev video_gid

  video_gid=$(getent group video 2>/dev/null | cut -d: -f3)
  [[ -z "$video_gid" ]] && video_gid="44"

  local -a nv_devs=()
  for dev in /dev/nvidia[0-9]* /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools /dev/nvidia-modeset; do
    [[ -c "$dev" ]] && nv_devs+=("$dev")
  done
  if [[ -d /dev/nvidia-caps ]]; then
    for dev in /dev/nvidia-caps/nvidia-cap[0-9]*; do
      [[ -c "$dev" ]] && nv_devs+=("$dev")
    done
  fi

  for dev in "${nv_devs[@]}"; do
    if ! grep -q "dev.*${dev}" "$cfg" 2>/dev/null; then
      idx=$(get_next_dev_index "$cfg")
      echo "dev${idx}: ${dev},gid=${video_gid}" >> "$cfg"
    fi
  done
}

configure_passthrough() {
  local ctid="$1"
  local cfg="/etc/pve/lxc/${ctid}.conf"
  CT_WAS_RUNNING=false

  if pct status "$ctid" 2>/dev/null | grep -q "running"; then
    CT_WAS_RUNNING=true
    msg_info "$(translate 'Stopping container') ${ctid}..."
    pct stop "$ctid" >>"$LOG_FILE" 2>&1
    msg_ok "$(translate 'Container stopped.')" | tee -a "$screen_capture"
  fi

  for gpu_type in "${SELECTED_GPUS[@]}"; do
    case "$gpu_type" in
      intel)
        msg_info "$(translate 'Configuring Intel iGPU passthrough...')"
        _configure_intel "$cfg"
        msg_ok "$(translate 'Intel iGPU passthrough configured.')" | tee -a "$screen_capture"
        ;;
      amd)
        msg_info "$(translate 'Configuring AMD GPU passthrough...')"
        _configure_amd "$cfg"
        msg_ok "$(translate 'AMD GPU passthrough configured.')" | tee -a "$screen_capture"
        ;;
      nvidia)
        msg_info "$(translate 'Configuring NVIDIA GPU passthrough...')"
        _configure_nvidia "$cfg"
        msg_ok "$(translate 'NVIDIA GPU passthrough configured.')" | tee -a "$screen_capture"
        ;;
    esac
  done
}


# ============================================================
# Driver / userspace library installation inside container
# ============================================================
# ============================================================
# Detect distro inside container (POSIX sh — works on Alpine too)
# ============================================================
_detect_container_distro() {
  local distro
  distro=$(pct exec "$1" -- grep "^ID=" /etc/os-release 2>/dev/null \
    | cut -d= -f2 | tr -d '[:space:]"')
  echo "${distro:-unknown}"
}

# ============================================================
# GID sync helper — POSIX sh, works on all distros
# ============================================================
_sync_gids_in_container() {
  local ctid="$1"
  local hvid hrid
  hvid=$(getent group video  2>/dev/null | cut -d: -f3); [[ -z "$hvid" ]] && hvid="44"
  hrid=$(getent group render 2>/dev/null | cut -d: -f3); [[ -z "$hrid" ]] && hrid="104"

  pct exec "$ctid" -- sh -c "
    sed -i 's/^video:x:[0-9]*:/video:x:${hvid}:/'  /etc/group 2>/dev/null || true
    sed -i 's/^render:x:[0-9]*:/render:x:${hrid}:/' /etc/group 2>/dev/null || true
    grep -q '^video:'  /etc/group 2>/dev/null || echo 'video:x:${hvid}:'  >> /etc/group
    grep -q '^render:' /etc/group 2>/dev/null || echo 'render:x:${hrid}:' >> /etc/group
  " >>"$LOG_FILE" 2>&1 || true
}

# ============================================================
_install_intel_drivers() {
  local ctid="$1"
  local distro="$2"

  _sync_gids_in_container "$ctid"

  case "$distro" in
    alpine)
      pct exec "$ctid" -- sh -c \
        "echo '@community https://dl-cdn.alpinelinux.org/alpine/edge/community' >> /etc/apk/repositories 2>/dev/null || true
         apk update && apk add --no-cache mesa-va-gallium intel-media-driver@community libva libva-utils" \
        2>&1 | tee -a "$LOG_FILE"
      ;;
    arch|manjaro|endeavouros)
      pct exec "$ctid" -- bash -c \
        "pacman -Sy --noconfirm intel-media-driver libva-utils mesa" \
        2>&1 | tee -a "$LOG_FILE"
      ;;
    *)
      pct exec "$ctid" -- bash -s >>"$LOG_FILE" 2>&1 << EOF
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y va-driver-all vainfo libva2 ocl-icd-libopencl1 intel-opencl-icd intel-gpu-tools 2>/dev/null || \
apt-get install -y va-driver-all vainfo libva2 2>/dev/null || true
EOF
      ;;
  esac
}

_install_amd_drivers() {
  local ctid="$1"
  local distro="$2"

  _sync_gids_in_container "$ctid"

  case "$distro" in
    alpine)
      pct exec "$ctid" -- sh -c \
        "apk update && apk add --no-cache mesa-va-gallium mesa-dri-gallium libva-utils" \
        2>&1 | tee -a "$LOG_FILE"
      ;;
    arch|manjaro|endeavouros)
      pct exec "$ctid" -- bash -c \
        "pacman -Sy --noconfirm mesa libva-mesa-driver libva-utils" \
        2>&1 | tee -a "$LOG_FILE"
      ;;
    *)
      pct exec "$ctid" -- bash -s >>"$LOG_FILE" 2>&1 << EOF
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y mesa-va-drivers libdrm-amdgpu1 vainfo libva2 2>/dev/null || \
apt-get install -y mesa-va-drivers vainfo libva2 2>/dev/null || true
EOF
      ;;
  esac
}

# ============================================================
# Memory management helpers (for NVIDIA .run installer)
# ============================================================
CT_ORIG_MEM=""
NVIDIA_INSTALL_MIN_MB=2048

_ensure_container_memory() {
  local ctid="$1"
  local cur_mem
  cur_mem=$(pct config "$ctid" 2>/dev/null | awk '/^memory:/{print $2}')
  [[ -z "$cur_mem" ]] && cur_mem=512

  if [[ "$cur_mem" -lt "$NVIDIA_INSTALL_MIN_MB" ]]; then
    if whiptail --title "$(translate 'Low Container Memory')" --yesno \
      "$(translate 'Container') ${ctid} $(translate 'has') ${cur_mem}MB RAM.\n\n$(translate 'The NVIDIA installer needs at least') ${NVIDIA_INSTALL_MIN_MB}MB $(translate 'to run without being killed by the OOM killer.')\n\n$(translate 'Increase container RAM temporarily to') ${NVIDIA_INSTALL_MIN_MB}MB?" \
      13 72; then
      CT_ORIG_MEM="$cur_mem"
      pct set "$ctid" -memory "$NVIDIA_INSTALL_MIN_MB" >>"$LOG_FILE" 2>&1 || true
    else
      INSTALL_ABORTED=true
      msg_warn "$(translate 'Insufficient memory. NVIDIA install aborted.')"
      return 1
    fi
  fi
  return 0
}

_restore_container_memory() {
  local ctid="$1"
  if [[ -n "$CT_ORIG_MEM" ]]; then
    msg_info "$(translate 'Restoring container memory to') ${CT_ORIG_MEM}MB..."
    pct set "$ctid" -memory "$CT_ORIG_MEM" >>"$LOG_FILE" 2>&1 || true
    msg_ok "$(translate 'Memory restored.')"
    CT_ORIG_MEM=""
  fi
}

# ============================================================
_install_nvidia_drivers() {
  local ctid="$1"
  local version="$NVIDIA_HOST_VERSION"
  local distro="$2"

  case "$distro" in
    alpine)
      # Alpine uses apk — musl-compatible nvidia-utils from Alpine repos
      msg_info2 "$(translate 'Installing NVIDIA utils (Alpine)...')"
      pct exec "$ctid" -- sh -c \
        "apk update && apk add --no-cache nvidia-utils" \
        2>&1 | tee -a "$LOG_FILE"
      ;;

    arch|manjaro|endeavouros)
      # Arch uses pacman — nvidia-utils provides nvidia-smi
      msg_info2 "$(translate 'Installing NVIDIA utils (Arch)...')"
      pct exec "$ctid" -- bash -c \
        "pacman -Sy --noconfirm nvidia-utils" \
        2>&1 | tee -a "$LOG_FILE"
      ;;

    *)
      # Debian / Ubuntu / generic glibc: use the .run binary
      local run_file="${NVIDIA_WORKDIR}/NVIDIA-Linux-x86_64-${version}.run"

      if [[ ! -f "$run_file" ]]; then
        msg_warn "$(translate 'NVIDIA installer not found at') ${run_file}."
        msg_warn "$(translate 'Run \"Install NVIDIA Drivers on Host\" first so the installer is cached.')"
        return 1
      fi

      # Memory check — nvidia-installer needs ~2GB during install
      _ensure_container_memory "$ctid" || return 1

      # Disk space check — NVIDIA libs need ~1.5 GB free in the container
      local free_mb
      free_mb=$(pct exec "$ctid" -- df -m / 2>/dev/null | awk 'NR==2{print $4}' || echo 0)
      if [[ "$free_mb" -lt 1500 ]]; then
        _restore_container_memory "$ctid"
        dialog --backtitle "ProxMenux" \
          --title "$(translate 'Insufficient Disk Space')" \
          --msgbox "\n$(translate 'Container') ${ctid} $(translate 'has only') ${free_mb}MB $(translate 'of free disk space.')\n\n$(translate 'NVIDIA libs require approximately 1.5GB of free space.')\n\n$(translate 'Please expand the container disk and run this option again.')" \
          12 72
        INSTALL_ABORTED=true
        return 1
      fi

      # Extract .run on the host — avoids decompression OOM inside container
      # Use msg_info2 (no spinner) so tee output is not mixed with spinner animation
      local extract_dir="${NVIDIA_WORKDIR}/extracted_${version}"
      local archive="/tmp/nvidia_lxc_${version}.tar.gz"

      msg_info2 "$(translate 'Extracting NVIDIA installer on host...')"
      rm -rf "$extract_dir"
      sh "$run_file" --extract-only --target "$extract_dir" 2>&1 | tee -a "$LOG_FILE"
      if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        msg_warn "$(translate 'Extraction failed. Check log:') ${LOG_FILE}"
        _restore_container_memory "$ctid"
        return 1
      fi
      msg_ok "$(translate 'NVIDIA installer extracted.')" | tee -a "$screen_capture"

      msg_info2 "$(translate 'Packing installer archive...')"
      tar --checkpoint=5000 --checkpoint-action=dot \
          -czf "$archive" -C "$extract_dir" . 2>&1 | tee -a "$LOG_FILE"
      echo ""
      local archive_size
      archive_size=$(du -sh "$archive" 2>/dev/null | cut -f1)
      msg_ok "$(translate 'Archive ready') (${archive_size})." | tee -a "$screen_capture"

      msg_info "$(translate 'Copying installer to container') ${ctid}..."
      if ! pct push "$ctid" "$archive" /tmp/nvidia_lxc.tar.gz >>"$LOG_FILE" 2>&1; then
        msg_warn "$(translate 'pct push failed. Check log:') ${LOG_FILE}"
        rm -f "$archive"
        _restore_container_memory "$ctid"
        return 1
      fi
      rm -f "$archive"
      msg_ok "$(translate 'Installer copied to container.')" | tee -a "$screen_capture"

      msg_info2 "$(translate 'Installing NVIDIA drivers in container. This may take several minutes...')"
      echo "" >>"$LOG_FILE"
      pct exec "$ctid" -- bash -c "
        mkdir -p /tmp/nvidia_lxc_install
        tar -xzf /tmp/nvidia_lxc.tar.gz -C /tmp/nvidia_lxc_install 2>&1
        /tmp/nvidia_lxc_install/nvidia-installer \
          --no-kernel-modules \
          --no-questions \
          --ui=none \
          --no-nouveau-check \
          --no-dkms \
          --no-install-compat32-libs
        EXIT=\$?
        rm -rf /tmp/nvidia_lxc_install /tmp/nvidia_lxc.tar.gz
        exit \$EXIT
      " 2>&1 | tee -a "$LOG_FILE"
      local rc=${PIPESTATUS[0]}

      rm -rf "$extract_dir"
      _restore_container_memory "$ctid"

      if [[ $rc -ne 0 ]]; then
        msg_warn "$(translate 'NVIDIA installer returned error') ${rc}. $(translate 'Check log:') ${LOG_FILE}"
        return 1
      fi
      ;;
  esac

  if pct exec "$ctid" -- sh -c "which nvidia-smi" >/dev/null 2>&1; then
    return 0
  else
    msg_warn "$(translate 'nvidia-smi not found after install. Check log:') ${LOG_FILE}"
    return 1
  fi
}


start_container_and_wait() {
  local ctid="$1"
  msg_info "$(translate 'Starting container') ${ctid}..."
  pct start "$ctid" >>"$LOG_FILE" 2>&1 || true

  local ready=false
  for _ in {1..15}; do
    sleep 2
    if pct exec "$ctid" -- true >/dev/null 2>&1; then
      ready=true
      break
    fi
  done

  if ! $ready; then
    msg_warn "$(translate 'Container did not become ready in time. Skipping driver installation.')"
    return 1
  fi
  msg_ok "$(translate 'Container started.')" | tee -a "$screen_capture"
  return 0
}

install_drivers() {
  local ctid="$1"

  # Detect distro once — passed to each install function
  msg_info "$(translate 'Detecting container OS...')"
  local ct_distro
  ct_distro=$(_detect_container_distro "$ctid")
  msg_ok "$(translate 'Container OS:') ${ct_distro}" | tee -a "$screen_capture"

  for gpu_type in "${SELECTED_GPUS[@]}"; do
    case "$gpu_type" in
      intel)
        #msg_info "$(translate 'Installing Intel VA-API drivers in container...')"
        _install_intel_drivers "$ctid" "$ct_distro"
        msg_ok "$(translate 'Intel VA-API drivers installed.')" | tee -a "$screen_capture"
        ;;
      amd)
        #msg_info "$(translate 'Installing AMD mesa drivers in container...')"
        _install_amd_drivers "$ctid" "$ct_distro"
        msg_ok "$(translate 'AMD mesa drivers installed.')" | tee -a "$screen_capture"
        ;;
      nvidia)
        # No outer msg_info here — _install_nvidia_drivers manages its own messages
        # to avoid a dangling spinner before the whiptail memory dialog
        if _install_nvidia_drivers "$ctid" "$ct_distro"; then
          msg_ok "$(translate 'NVIDIA userspace libraries installed.')" | tee -a "$screen_capture"
          NVIDIA_INSTALL_SUCCESS=true
        elif [[ "$INSTALL_ABORTED" == "false" ]]; then
          msg_warn "$(translate 'NVIDIA install incomplete. Check log:') ${LOG_FILE}"
        fi
        ;;
    esac
  done
}


# ============================================================
# Switch mode: GPU → VM  →  GPU → LXC
# ============================================================

# Returns all vendor:device IDs in the same IOMMU group as a PCI device.
# Skips PCI bridges (class 0x0604 / 0x0600).
_get_iommu_group_ids() {
  local pci_full="$1"
  local group_link="/sys/bus/pci/devices/${pci_full}/iommu_group"
  [[ ! -L "$group_link" ]] && return

  local group_dir
  group_dir="/sys/kernel/iommu_groups/$(basename "$(readlink "$group_link")")/devices"

  for dev_path in "${group_dir}/"*; do
    [[ -e "$dev_path" ]] || continue
    local dev dev_class
    dev=$(basename "$dev_path")
    dev_class=$(cat "/sys/bus/pci/devices/${dev}/class" 2>/dev/null)
    [[ "$dev_class" == 0x0604* || "$dev_class" == 0x0600* ]] && continue
    local vid did
    vid=$(cat "/sys/bus/pci/devices/${dev}/vendor" 2>/dev/null | sed 's/0x//')
    did=$(cat "/sys/bus/pci/devices/${dev}/device" 2>/dev/null | sed 's/0x//')
    [[ -n "$vid" && -n "$did" ]] && echo "${vid}:${did}"
  done
}

# Removes the given vendor:device IDs from the vfio-pci ids= line in vfio.conf.
# If no IDs remain after removal, the line is deleted entirely.
# Prints the number of remaining IDs to stdout (captured by caller).
_remove_vfio_ids() {
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  local -a ids_to_remove=("$@")
  [[ ! -f "$vfio_conf" ]] && echo "0" && return

  local ids_line ids_part
  ids_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
  if [[ -z "$ids_line" ]]; then echo "0"; return; fi
  ids_part=$(echo "$ids_line" | grep -oE 'ids=[^[:space:]]+' | sed 's/ids=//')

  local -a remaining=()
  IFS=',' read -ra current_ids <<< "$ids_part"
  for id in "${current_ids[@]}"; do
    local remove=false
    for r in "${ids_to_remove[@]}"; do
      [[ "$id" == "$r" ]] && remove=true && break
    done
    $remove || remaining+=("$id")
  done

  sed -i '/^options vfio-pci ids=/d' "$vfio_conf"
  if [[ ${#remaining[@]} -gt 0 ]]; then
    local new_ids
    new_ids=$(IFS=','; echo "${remaining[*]}")
    echo "options vfio-pci ids=${new_ids} disable_vga=1" >> "$vfio_conf"
  fi

  echo "${#remaining[@]}"
}

# Removes blacklist entries for the given GPU driver type.
_remove_gpu_blacklist() {
  local gpu_type="$1"
  local blacklist_file="/etc/modprobe.d/blacklist.conf"
  [[ ! -f "$blacklist_file" ]] && return
  case "$gpu_type" in
    nvidia)
      sed -i '/^blacklist nouveau$/d'          "$blacklist_file"
      sed -i '/^blacklist nvidia$/d'            "$blacklist_file"
      sed -i '/^blacklist nvidiafb$/d'          "$blacklist_file"
      sed -i '/^blacklist nvidia_drm$/d'        "$blacklist_file"
      sed -i '/^blacklist nvidia_modeset$/d'    "$blacklist_file"
      sed -i '/^blacklist nvidia_uvm$/d'        "$blacklist_file"
      sed -i '/^blacklist lbm-nouveau$/d'       "$blacklist_file"
      sed -i '/^options nouveau modeset=0$/d'   "$blacklist_file"
      
      # Remove hard blacklist file created for VFIO mode
      local nvidia_blacklist="/etc/modprobe.d/nvidia-blacklist.conf"
      if [[ -f "$nvidia_blacklist" ]]; then
        rm -f "$nvidia_blacklist"
      fi
      
      # Restore NVIDIA udev rules if they were disabled for VFIO mode
      local udev_disabled="/etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled"
      local udev_rules="/etc/udev/rules.d/70-nvidia.rules"
      if [[ -f "$udev_disabled" ]]; then
        mv "$udev_disabled" "$udev_rules"
        udevadm control --reload-rules >/dev/null 2>&1 || true
      fi
      ;;
    amd)
      sed -i '/^blacklist radeon$/d'    "$blacklist_file"
      sed -i '/^blacklist amdgpu$/d'    "$blacklist_file"
      ;;
    intel)
      sed -i '/^blacklist i915$/d'      "$blacklist_file"
      ;;
  esac
}

# Removes AMD softdep entries from vfio.conf.
_remove_amd_softdep() {
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  [[ ! -f "$vfio_conf" ]] && return
  sed -i '/^softdep radeon pre: vfio-pci$/d'         "$vfio_conf"
  sed -i '/^softdep amdgpu pre: vfio-pci$/d'         "$vfio_conf"
  sed -i '/^softdep snd_hda_intel pre: vfio-pci$/d'  "$vfio_conf"
}

# Removes VFIO modules from /etc/modules (called when no IDs remain in vfio.conf).
_remove_vfio_modules() {
  local modules_file="/etc/modules"
  [[ ! -f "$modules_file" ]] && return
  sed -i '/^vfio$/d'             "$modules_file"
  sed -i '/^vfio_iommu_type1$/d' "$modules_file"
  sed -i '/^vfio_pci$/d'         "$modules_file"
  sed -i '/^vfio_virqfd$/d'      "$modules_file"
}

# Detects if any selected GPU is currently in GPU → VM mode (VFIO binding).
# If so, delegates switch handling to switch_gpu_mode.sh and exits.
check_vfio_switch_mode() {
  local vfio_conf="/etc/modprobe.d/vfio.conf"
  [[ ! -f "$vfio_conf" ]] && return 0

  local ids_line ids_part
  ids_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
  [[ -z "$ids_line" ]] && return 0
  ids_part=$(echo "$ids_line" | grep -oE 'ids=[^[:space:]]+' | sed 's/ids=//')
  [[ -z "$ids_part" ]] && return 0

  # Detect which selected GPUs are in VFIO mode
  local -a vfio_types=() vfio_pcis=() vfio_names=()
  for gpu_type in "${SELECTED_GPUS[@]}"; do
    local pci="" vid_did="" gpu_name=""
    case "$gpu_type" in
      intel)  pci="$INTEL_PCI";  vid_did="$INTEL_VID_DID";  gpu_name="$INTEL_NAME"  ;;
      amd)    pci="$AMD_PCI";    vid_did="$AMD_VID_DID";    gpu_name="$AMD_NAME"    ;;
      nvidia) pci="$NVIDIA_PCI"; vid_did="$NVIDIA_VID_DID"; gpu_name="$NVIDIA_NAME" ;;
    esac
    [[ -z "$vid_did" ]] && continue
    if echo "$ids_part" | grep -q "$vid_did"; then
      vfio_types+=("$gpu_type")
      vfio_pcis+=("$pci")
      vfio_names+=("$gpu_name")
    fi
  done

  [[ ${#vfio_types[@]} -eq 0 ]] && return 0

  local msg
  msg="\n$(translate 'The following selected GPU(s) are currently in GPU -> VM mode (vfio-pci):')\n\n"
  for i in "${!vfio_types[@]}"; do
    msg+="  •  ${vfio_names[$i]}  (${vfio_pcis[$i]})\n"
  done
  msg+="\n\Z1\Zb$(translate 'To continue with Add GPU to LXC, first switch the host to GPU -> LXC mode and reboot.')\Zn\n"
  msg+="\Z1\Zb$(translate 'Do you want to open Switch GPU Mode now?')\Zn"

  dialog --backtitle "ProxMenux" --colors \
    --title "$(translate 'GPU -> VM Mode Detected')" \
    --yesno "$msg" 18 84
  [[ $? -ne 0 ]] && exit 0

  local switch_script="$LOCAL_SCRIPTS/gpu_tpu/switch_gpu_mode.sh"
  local local_switch_script
  local_switch_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/switch_gpu_mode.sh"
  if [[ ! -f "$switch_script" && -f "$local_switch_script" ]]; then
    switch_script="$local_switch_script"
  fi

  if [[ ! -f "$switch_script" ]]; then
    dialog --backtitle "ProxMenux" \
      --title "$(translate 'Switch Script Not Found')" \
      --msgbox "\n$(translate 'switch_gpu_mode.sh was not found.')\n\n$(translate 'Expected path:')\n${LOCAL_SCRIPTS}/gpu_tpu/switch_gpu_mode.sh" 10 84
    exit 0
  fi

  bash "$switch_script"

  dialog --backtitle "ProxMenux" --colors \
    --title "$(translate 'Next Step Required')" \
    --msgbox "\n\Z1\Zb$(translate 'After switching mode, reboot the host if requested.')\Zn\n\n$(translate 'Then run this option again:')\n\n  \Z1\ZbAdd GPU to LXC\Zn\n\n$(translate 'This guarantees that device nodes are available before applying LXC GPU config.')" \
    12 84
  exit 0
}


# ============================================================
# Main
# ============================================================
main() {
  : >"$LOG_FILE"
  : >"$screen_capture"

  # ---- Phase 1: all dialogs (no terminal output yet) ----
  detect_host_gpus
  select_container
  select_gpus
  check_sriov_and_block_if_needed
  check_vfio_switch_mode
  precheck_existing_lxc_gpu_config

  # NVIDIA check runs only if NVIDIA was selected
  for gpu_type in "${SELECTED_GPUS[@]}"; do
    [[ "$gpu_type" == "nvidia" ]] && check_nvidia_ready
  done

  # ---- Phase 2: processing ----
  show_proxmenux_logo
  msg_title "$(_get_lxc_run_title)"

  configure_passthrough "$CONTAINER_ID"
  if declare -F attach_proxmenux_gpu_guard_to_lxc >/dev/null 2>&1; then
    ensure_proxmenux_gpu_guard_hookscript
    attach_proxmenux_gpu_guard_to_lxc "$CONTAINER_ID"
    sync_proxmenux_gpu_guard_hooks
  fi

  if start_container_and_wait "$CONTAINER_ID"; then
    install_drivers "$CONTAINER_ID"

    # Capture nvidia-smi output while container is still running
    if $NVIDIA_INSTALL_SUCCESS; then
      NVIDIA_SMI_OUTPUT=$(pct exec "$CONTAINER_ID" -- nvidia-smi 2>/dev/null || true)
    fi

    if [[ "$CT_WAS_RUNNING" == "false" ]]; then
      pct stop "$CONTAINER_ID" >>"$LOG_FILE" 2>&1 || true
    fi
  fi

  if [[ "$INSTALL_ABORTED" == "true" ]]; then
    rm -f "$screen_capture"
    exit 0
  fi

  show_proxmenux_logo
  msg_title "$(_get_lxc_run_title)"
  cat "$screen_capture"
  echo -e "${TAB}${GN}📄 $(translate 'Log')${CL}: ${BL}${LOG_FILE}${CL}"
  if [[ -n "$NVIDIA_SMI_OUTPUT" ]]; then
    msg_info2 "$(translate 'NVIDIA driver verification in container:')"
    echo "$NVIDIA_SMI_OUTPUT"
  fi
  msg_success "$(translate 'GPU passthrough configured for LXC') ${CONTAINER_ID}."
  msg_success "$(translate 'Completed. Press Enter to return to menu...')"
  read -r
  rm -f "$screen_capture"
}

main
