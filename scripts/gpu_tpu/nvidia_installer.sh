#!/bin/bash
# ==========================================================
# ProxMenux - NVIDIA GPU Driver Installer
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.2
# Last Updated: 26/03/2026
# ==========================================================
# Description:
# Installs and manages the NVIDIA proprietary driver on a
# Proxmox VE host. Detects hardware, picks a kernel-compatible
# driver version and handles the full lifecycle
# (install / update / remove).
#
# Features:
#  - GPU detection + VFIO passthrough safety check
#  - Kernel-aware driver version filter (5.15 → 6.17+)
#  - Nouveau blacklist + module unload
#  - DKMS-backed install (survives kernel upgrades)
#  - udev rules + nvidia-persistenced service
#  - Optional keylase/nvidia-patch (NVENC session limit)
#  - LXC container driver propagation (Alpine/Arch/Debian)
#  - Complete uninstall path
# ==========================================================

SCRIPT_TITLE="NVIDIA GPU Driver Installer for Proxmox VE"

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
COMPONENTS_STATUS_FILE="$BASE_DIR/components_status.json"
LOG_FILE="/tmp/nvidia_install.log"
screen_capture="/tmp/proxmenux_nvidia_screen_capture_$$.txt"

NVIDIA_BASE_URL="https://download.nvidia.com/XFree86/Linux-x86_64"
NVIDIA_WORKDIR="/opt/nvidia"

# LXC post-install update constants (used only when NVIDIA LXC passthrough
# containers are detected and the user confirms updating them after the host
# install/reinstall finishes).
NVIDIA_INSTALL_MIN_MB=2048
CT_ORIG_MEM=""

export BASE_DIR
export COMPONENTS_STATUS_FILE

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

if [[ ! -f "$COMPONENTS_STATUS_FILE" ]]; then
  echo "{}" > "$COMPONENTS_STATUS_FILE"
fi

load_language
initialize_cache

# ==========================================================
# GPU detection and current status
# ==========================================================
detect_nvidia_gpus() {
  # Only video controllers (not audio)
  local lspci_output
  lspci_output=$(lspci | grep -i "NVIDIA" \
    | grep -Ei "VGA compatible controller|3D controller|Display controller" || true)

  if [[ -z "$lspci_output" ]]; then
    NVIDIA_GPU_PRESENT=false
    DETECTED_GPUS_TEXT="$(translate 'No NVIDIA GPU detected on this system.')"
  else
    NVIDIA_GPU_PRESENT=true
    DETECTED_GPUS_TEXT=""
    local i=1
    while IFS= read -r line; do
      DETECTED_GPUS_TEXT+="  ${i}. ${line}\n"
      ((i++))
    done <<< "$lspci_output"
  fi
}

check_gpu_not_in_vm_passthrough() {
  local dev vendor driver vfio_list=""
  for dev in /sys/bus/pci/devices/*; do
    vendor=$(cat "$dev/vendor" 2>/dev/null)
    [[ "$vendor" != "0x10de" ]] && continue
    if [[ -L "$dev/driver" ]]; then
      driver=$(basename "$(readlink "$dev/driver")")
      if [[ "$driver" == "vfio-pci" ]]; then
        vfio_list+="  • $(basename "$dev")\n"
      fi
    fi
  done

  [[ -z "$vfio_list" ]] && return 0

  local msg
  msg="\n$(translate "One or more NVIDIA GPUs are currently configured for VM passthrough (vfio-pci):")\n\n"
  msg+="${vfio_list}\n"
  msg+="$(translate "Installing host drivers while the GPU is assigned to a VM could break passthrough and destabilize the system.")\n\n"
  msg+="$(translate "To install host drivers, first remove the GPU from VM passthrough configuration and reboot.")"

  dialog --backtitle "ProxMenux" \
    --title "$(translate "GPU in VM Passthrough Mode")" \
    --msgbox "$msg" 16 78
  exit 0
}

detect_driver_status() {
  CURRENT_DRIVER_INSTALLED=false
  CURRENT_DRIVER_VERSION=""
  
  # First check if nvidia kernel module is actually loaded
  if grep -q "^nvidia " /proc/modules 2>/dev/null; then

    modprobe nvidia-uvm 2>/dev/null || true
    sleep 1
    

    if command -v nvidia-smi >/dev/null 2>&1; then
      CURRENT_DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1)
      
      if [[ -n "$CURRENT_DRIVER_VERSION" ]]; then
        CURRENT_DRIVER_INSTALLED=true
        # Register the installed driver version in components_status.json
        update_component_status "nvidia_driver" "installed" "$CURRENT_DRIVER_VERSION" "gpu" '{"patched":false}'
      fi
    fi
  fi

  if $CURRENT_DRIVER_INSTALLED; then
    CURRENT_STATUS_TEXT="$(printf '%s %s' "$(translate 'NVIDIA driver installed:')" "$CURRENT_DRIVER_VERSION")"
  else
    CURRENT_STATUS_TEXT="$(translate 'No NVIDIA driver installed.')"
  fi

  if $CURRENT_DRIVER_INSTALLED; then
    CURRENT_STATUS_COLORED="${CURRENT_STATUS_TEXT}"
  else
    CURRENT_STATUS_COLORED="${CURRENT_STATUS_TEXT}"
  fi
}

# ==========================================================
# LXC NVIDIA passthrough — discovery & userspace-libs update
# Invoked after the host install/reinstall completes. Aligned with the install
# path used in add_gpu_lxc.sh (distro-aware, memory/disk checks, --no-dkms,
# --no-install-compat32-libs, visible progress via tee).
# ==========================================================
find_nvidia_containers() {
  NVIDIA_CONTAINERS=()
  for conf in /etc/pve/lxc/*.conf; do
    [[ -f "$conf" ]] || continue
    if grep -qiE "dev[0-9]+:.*nvidia" "$conf"; then
      NVIDIA_CONTAINERS+=("$(basename "$conf" .conf)")
    fi
  done
}

get_lxc_nvidia_version() {
  local ctid="$1"
  local version=""

  # Prefer nvidia-smi when the container is running (works with .run-installed drivers)
  if pct status "$ctid" 2>/dev/null | grep -q "running"; then
    version=$(pct exec "$ctid" -- nvidia-smi \
      --query-gpu=driver_version --format=csv,noheader 2>/dev/null \
      | head -1 | tr -d '[:space:]' || true)
  fi

  # Fallback: dpkg status for apt-installed libcuda1 (dir-type storage, no start needed)
  if [[ -z "$version" ]]; then
    local rootfs="/var/lib/lxc/${ctid}/rootfs"
    if [[ -f "${rootfs}/var/lib/dpkg/status" ]]; then
      version=$(grep -A5 "^Package: libcuda1$" "${rootfs}/var/lib/dpkg/status" \
        | grep "^Version:" | head -1 | awk '{print $2}' | cut -d- -f1)
    fi
  fi

  echo "${version:-$(translate 'not installed')}"
}

_detect_container_distro() {
  local distro
  distro=$(pct exec "$1" -- grep "^ID=" /etc/os-release 2>/dev/null \
    | cut -d= -f2 | tr -d '[:space:]"')
  echo "${distro:-unknown}"
}

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
      msg_warn "$(translate 'Insufficient memory. Skipping LXC') ${ctid}."
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

_start_container_and_wait() {
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
    msg_warn "$(translate 'Container') ${ctid} $(translate 'did not become ready. Skipping.')"
    return 1
  fi
  msg_ok "$(translate 'Container') ${ctid} $(translate 'started.')" | tee -a "$screen_capture"
  return 0
}

update_lxc_nvidia() {
  local ctid="$1"
  local version="$2"
  local started_here=false

  local old_version
  old_version=$(get_lxc_nvidia_version "$ctid")

  msg_info2 "$(translate 'Container') ${ctid}: $(translate 'updating NVIDIA userspace libs') (${old_version} → ${version})"

  if ! pct status "$ctid" 2>/dev/null | grep -q "running"; then
    started_here=true
    _start_container_and_wait "$ctid" || return 1
  fi

  msg_info "$(translate 'Detecting container OS...')"
  local distro
  distro=$(_detect_container_distro "$ctid")
  msg_ok "$(translate 'Container OS:') ${distro}" | tee -a "$screen_capture"

  local install_rc=0

  case "$distro" in
    arch|manjaro|endeavouros)
      msg_info2 "$(translate 'Upgrading NVIDIA utils (Arch)...')"
      pct exec "$ctid" -- bash -c \
        "pacman -Syu --noconfirm nvidia-utils" \
        2>&1 | tee -a "$LOG_FILE"
      install_rc=${PIPESTATUS[0]}
      ;;
    *)
      local run_file="${NVIDIA_WORKDIR}/NVIDIA-Linux-x86_64-${version}.run"

      if [[ ! -f "$run_file" ]]; then
        msg_warn "$(translate 'Installer not found:') ${run_file}. $(translate 'Skipping LXC') ${ctid}."
        install_rc=1
      elif ! _ensure_container_memory "$ctid"; then
        install_rc=1
      else
        local free_mb
        free_mb=$(pct exec "$ctid" -- df -P -m / 2>/dev/null | awk 'END{print $4}')
        free_mb=${free_mb:-0}
        if [[ "$free_mb" -lt 1500 ]]; then
          _restore_container_memory "$ctid"
          whiptail --backtitle "ProxMenux" \
            --title "$(translate 'Insufficient Disk Space')" \
            --msgbox "\n$(translate 'Container') ${ctid} $(translate 'has only') ${free_mb}MB $(translate 'of free disk space.')\n\n$(translate 'NVIDIA libs require approximately 1.5GB of free space.')" \
            11 72
          msg_warn "$(translate 'Insufficient disk space. Skipping LXC') ${ctid}."
          install_rc=1
        else
          local extract_dir="${NVIDIA_WORKDIR}/extracted_${version}"
          local archive="/tmp/nvidia_lxc_${version}.tar.gz"

          msg_info2 "$(translate 'Extracting NVIDIA installer on host...')"
          rm -rf "$extract_dir"
          sh "$run_file" --extract-only --target "$extract_dir" 2>&1 | tee -a "$LOG_FILE"
          if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
            msg_warn "$(translate 'Extraction failed. Check log:') ${LOG_FILE}"
            _restore_container_memory "$ctid"
            install_rc=1
          else
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
              rm -rf "$extract_dir"
              _restore_container_memory "$ctid"
              install_rc=1
            else
              rm -f "$archive"
              msg_ok "$(translate 'Installer copied to container.')" | tee -a "$screen_capture"

              msg_info2 "$(translate 'Running NVIDIA installer in container. This may take several minutes...')"
              echo "" >>"$LOG_FILE"
              if [[ "$distro" == "alpine" ]]; then
                # Alpine uses musl libc and does not ship a glibc dynamic
                # loader, so the nvidia-installer binary (glibc) cannot
                # execute. We pull `gcompat` to provide the glibc loader
                # and a libc shim, then copy the userspace libs and the
                # standard NVIDIA binaries by hand. SONAME symlinks are
                # built from `readelf` (binutils) instead of trusting a
                # hard-coded list — the .run ships ~50 .so files and the
                # set varies between branches.
                pct exec "$ctid" -- sh -c '
                  set -e
                  mkdir -p /tmp/nvidia_lxc_install
                  tar -xzf /tmp/nvidia_lxc.tar.gz -C /tmp/nvidia_lxc_install
                  apk add --no-cache gcompat binutils >/dev/null
                  cd /tmp/nvidia_lxc_install
                  mkdir -p /usr/lib /usr/bin
                  cp -P *.so* /usr/lib/ 2>/dev/null || true
                  for lib in /usr/lib/lib*.so.*; do
                    [ -f "$lib" ] || continue
                    soname=$(readelf -d "$lib" 2>/dev/null | grep SONAME | head -n1 | sed -e "s/.*\[//" -e "s/\].*//")
                    [ -n "$soname" ] && [ "$(basename "$lib")" != "$soname" ] && ln -sf "$(basename "$lib")" "/usr/lib/$soname"
                  done
                  for bin in nvidia-smi nvidia-debugdump nvidia-cuda-mps-control nvidia-cuda-mps-server nvidia-persistenced nvidia-modprobe; do
                    [ -f "$bin" ] && cp -P "$bin" /usr/bin/ && chmod 755 "/usr/bin/$bin"
                  done
                  rm -rf /tmp/nvidia_lxc_install /tmp/nvidia_lxc.tar.gz
                ' 2>&1 | tee -a "$LOG_FILE"
                install_rc=${PIPESTATUS[0]}
              else
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
                install_rc=${PIPESTATUS[0]}
              fi

              rm -rf "$extract_dir"
              _restore_container_memory "$ctid"
            fi
          fi
        fi
      fi
      ;;
  esac

  if [[ $install_rc -ne 0 ]]; then
    msg_warn "$(translate 'NVIDIA update failed for LXC') ${ctid} (rc=${install_rc}). $(translate 'Check log:') ${LOG_FILE}"
    if $started_here; then
      pct stop "$ctid" >>"$LOG_FILE" 2>&1 || true
    fi
    return 1
  fi

  if pct exec "$ctid" -- sh -c "which nvidia-smi" >/dev/null 2>&1; then
    local new_ver
    new_ver=$(pct exec "$ctid" -- nvidia-smi \
      --query-gpu=driver_version --format=csv,noheader 2>/dev/null \
      | head -1 | tr -d '[:space:]' || true)
    msg_ok "$(translate 'Container') ${ctid}: ${old_version} → ${new_ver:-$version}" | tee -a "$screen_capture"
  else
    msg_warn "$(translate 'nvidia-smi not found in container') ${ctid} $(translate 'after update.')"
  fi

  if $started_here; then
    msg_info "$(translate 'Stopping container') ${ctid}..."
    pct stop "$ctid" >>"$LOG_FILE" 2>&1 || true
    msg_ok "$(translate 'Container stopped.')" | tee -a "$screen_capture"
  fi
  return 0
}

# Post-host-install LXC update offer — scans for NVIDIA LXCs and, if any are
# found, asks the user if they want to propagate the driver update to them.
offer_lxc_updates_if_any() {
  local target_version="$1"
  find_nvidia_containers
  [[ ${#NVIDIA_CONTAINERS[@]} -eq 0 ]] && return 0

  local info ctid lxc_ver ct_name
  info="\n$(translate 'The following LXC containers have NVIDIA passthrough configured:')\n\n"
  for ctid in "${NVIDIA_CONTAINERS[@]}"; do
    lxc_ver=$(get_lxc_nvidia_version "$ctid")
    ct_name=$(pct config "$ctid" 2>/dev/null | grep "^hostname:" | awk '{print $2}')
    info+="  CT ${ctid}  ${ct_name:+(${ct_name})}  — $(translate 'driver:') ${lxc_ver}\n"
  done
  info+="\n$(translate 'Do you want to update the NVIDIA userspace libraries inside these containers to match the host?')"

  if ! hybrid_whiptail_yesno "$(translate 'Update NVIDIA in LXC Containers')" "$info" 20 80; then
    msg_info2 "$(translate 'LXC update skipped by user.')"
    return 0
  fi

  for ctid in "${NVIDIA_CONTAINERS[@]}"; do
    update_lxc_nvidia "$ctid" "$target_version" || true
  done
}

# ==========================================================
# System preparation (repos, headers, etc.)
# ==========================================================
ensure_repos_and_headers() {
  msg_info "$(translate 'Checking kernel headers and build tools...')"

  local kver
  kver=$(uname -r)

  apt-get update -qq >>"$LOG_FILE" 2>&1

  if ! dpkg -s "pve-headers-$kver" >/dev/null 2>&1 && \
     ! dpkg -s "proxmox-headers-$kver" >/dev/null 2>&1; then
    apt-get install -y "pve-headers-$kver" "proxmox-headers-$kver" build-essential dkms >>"$LOG_FILE" 2>&1 || true
  else
    apt-get install -y build-essential dkms >>"$LOG_FILE" 2>&1 || true
  fi

  msg_ok "$(translate 'Kernel headers and build tools verified.')" | tee -a "$screen_capture"
}

blacklist_nouveau() {
  msg_info "$(translate 'Blacklisting nouveau driver...')"

  # Write blacklist config files
  if ! grep -q '^blacklist nouveau' /etc/modprobe.d/blacklist.conf 2>/dev/null; then
    echo "blacklist nouveau" >> /etc/modprobe.d/blacklist.conf
  fi

  # Also write explicit options file to ensure it's fully disabled
  cat > /etc/modprobe.d/nouveau-blacklist.conf <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF

  # Attempt to unload nouveau if currently loaded
  if grep -q "^nouveau " /proc/modules 2>/dev/null; then

    msg_info "$(translate 'Nouveau module is loaded, attempting to unload...')"
    modprobe -r nouveau 2>/dev/null || true
    sleep 1

    # Check if unload succeeded
    if grep -q "^nouveau " /proc/modules 2>/dev/null; then
      NOUVEAU_STILL_LOADED=true
      msg_warn "$(translate 'Could not unload nouveau module (may be in use). The blacklist will take effect after reboot. Installation will continue but a reboot will be required.')"
      echo "WARNING: nouveau module still loaded after unload attempt" >> "$LOG_FILE"
    else
      NOUVEAU_STILL_LOADED=false
      msg_ok "$(translate 'nouveau module unloaded successfully.')" | tee -a "$screen_capture"
    fi
  else
    NOUVEAU_STILL_LOADED=false
    msg_ok "$(translate 'nouveau driver has been blacklisted.')" | tee -a "$screen_capture"
  fi

}

ensure_modules_config() {
  msg_info "$(translate 'Configuring NVIDIA and VFIO modules...')"
  cat > /etc/modules-load.d/nvidia-vfio.conf <<'EOF'
vfio
vfio_iommu_type1
vfio_pci
vfio_virqfd
nvidia
nvidia_uvm
EOF
  msg_ok "$(translate 'Modules configuration updated.')" | tee -a "$screen_capture"
}

stop_and_disable_nvidia_services() {
  local services=(
    "nvidia-persistenced.service"
    "nvidia-persistenced"
    "nvidia-powerd.service"
  )

  local services_detected=0 

  for service in "${services[@]}"; do
    if systemctl is-active --quiet "$service" 2>/dev/null || \
       systemctl is-enabled --quiet "$service" 2>/dev/null; then
      services_detected=1
      break 
    fi
  done

  if [ "$services_detected" -eq 1 ]; then
    msg_info "$(translate 'Stopping and disabling NVIDIA services...')"
    
    for service in "${services[@]}"; do
      if systemctl is-active --quiet "$service" 2>/dev/null; then
        systemctl stop "$service" >/dev/null 2>&1 || true
      fi
      if systemctl is-enabled --quiet "$service" 2>/dev/null; then
        systemctl disable "$service" >/dev/null 2>&1 || true
      fi
    done

    sleep 2
    
    msg_ok "$(translate 'NVIDIA services stopped and disabled.')" | tee -a "$screen_capture"
  fi
}

unload_nvidia_modules() {
  for mod in nvidia_uvm nvidia_drm nvidia_modeset nvidia; do
    modprobe -r "$mod" >/dev/null 2>&1 || true
  done

  # Give the kernel a moment to finalize sysfs teardown before re-checking.
  # Reading /proc/modules directly (instead of lsmod) avoids the
  # "could not open /sys/module/<mod>/holders" race when a module has just
  # been removed from /proc/modules but its sysfs dir hasn't been reaped yet.
  sleep 1

  if grep -q "^nvidia" /proc/modules 2>/dev/null; then
    for mod in nvidia_uvm nvidia_drm nvidia_modeset nvidia; do
      modprobe -r --force "$mod" >/dev/null 2>&1 || true
    done
    sleep 1
  fi

  if grep -q "^nvidia" /proc/modules 2>/dev/null; then

    if command -v lsof >/dev/null 2>&1; then
      echo "$(translate 'Processes using NVIDIA:'):" >> "$LOG_FILE"
      lsof /dev/nvidia* 2>/dev/null >> "$LOG_FILE" || true
    fi
  else

    msg_ok "$(translate 'NVIDIA kernel modules unloaded successfully.')" | tee -a "$screen_capture"
  fi
}

complete_nvidia_uninstall() {
  stop_and_disable_nvidia_services
  unload_nvidia_modules
  
  if command -v nvidia-uninstall >/dev/null 2>&1; then
    msg_info "$(translate 'Running NVIDIA uninstaller...')"
    nvidia-uninstall --silent >>"$LOG_FILE" 2>&1 || true
    msg_ok "$(translate 'NVIDIA uninstaller completed.')"
  fi
  msg_ok "$(translate 'NVIDIA uninstallation steps completed.')" | tee -a "$screen_capture"
  cleanup_nvidia_dkms
  
  msg_info "$(translate 'Removing NVIDIA packages...')"
  apt-get -y purge 'nvidia-*' 'libnvidia-*' 'cuda-*' 'libcudnn*' >>"$LOG_FILE" 2>&1 || true
  apt-get -y autoremove --purge >>"$LOG_FILE" 2>&1 || true
  apt-get -y autoclean >>"$LOG_FILE" 2>&1 || true
  
  rm -f /etc/modules-load.d/nvidia-vfio.conf
  rm -f /etc/udev/rules.d/70-nvidia.rules
  rm -rf /usr/lib/modprobe.d/nvidia*.conf
  rm -rf /etc/modprobe.d/nvidia*.conf
  
  if [[ -d "$NVIDIA_WORKDIR" ]]; then
    find "$NVIDIA_WORKDIR" -type d -name "nvidia-persistenced" -exec rm -rf {} + 2>/dev/null || true
    find "$NVIDIA_WORKDIR" -type d -name "nvidia-patch" -exec rm -rf {} + 2>/dev/null || true
  fi

  update_component_status "nvidia_driver" "removed" "" "gpu" '{}'
  
  msg_ok "$(translate 'Complete NVIDIA uninstallation finished.')" | tee -a "$screen_capture"
  
}

cleanup_nvidia_dkms() {
  local versions
  versions=$(dkms status 2>/dev/null | awk -F, '/nvidia/ {gsub(/ /,"",$2); print $2}' || true)

  [[ -z "$versions" ]] && return 0

  msg_info "$(translate 'Removing NVIDIA DKMS entries...')"
  while IFS= read -r ver; do
    [[ -z "$ver" ]] && continue
    dkms remove -m nvidia -v "$ver" --all >/dev/null 2>&1 || true
  done <<< "$versions"
  msg_ok "$(translate 'NVIDIA DKMS entries removed.')"
}

ensure_workdir() {
  mkdir -p "$NVIDIA_WORKDIR"
}

# ==========================================================
# Kernel compatibility detection
# ==========================================================
get_kernel_compatibility_info() {
  local kernel_version
  kernel_version=$(uname -r)
  
  # Determine Proxmox and kernel version
  if [[ -f /etc/pve/.version ]]; then
    PVE_VERSION=$(cat /etc/pve/.version)
  else
    PVE_VERSION="unknown"
  fi
  
  # Extract kernel major version (6.x, 5.x, etc)
  KERNEL_MAJOR=$(echo "$kernel_version" | cut -d. -f1)
  KERNEL_MINOR=$(echo "$kernel_version" | cut -d. -f2)
  
  # Define minimum compatible versions based on kernel.
  # Floor bumped from 580.82.07 → 580.105.08 for kernel 6.17+ after a
  # user report (issue tracked as Sprint 11.4) that 580.82-580.95 builds
  # fail on kernel 6.17.13 (DKMS module compile errors with the newer
  # toolchain shipped with PVE 9.1). 580.105.08 is verified working on
  # the test host. Future kernel 7.x falls into the same bucket — the
  # `KERNEL_MAJOR -ge 7` branch was previously missing and routed 7.x
  # kernels to MIN=535 incorrectly.
  if { [[ "$KERNEL_MAJOR" -ge 7 ]]; } || \
     { [[ "$KERNEL_MAJOR" -eq 6 ]] && [[ "$KERNEL_MINOR" -ge 17 ]]; }; then
    # Kernel 6.17+ / 7.x (Proxmox 9.x +) - Requires 580.105.08 or higher
    MIN_DRIVER_VERSION="580.105.08"
    RECOMMENDED_BRANCH="580"
    COMPATIBILITY_NOTE="Kernel $kernel_version requires NVIDIA driver 580.105.08 or newer (older 580.x builds fail to compile)"
  elif [[ "$KERNEL_MAJOR" -ge 6 ]] && [[ "$KERNEL_MINOR" -ge 8 ]]; then
    # Kernel 6.8-6.16 (Proxmox 8.2+) - Works with 550.x or higher
    MIN_DRIVER_VERSION="550"
    RECOMMENDED_BRANCH="580"
    COMPATIBILITY_NOTE="Kernel $kernel_version works best with NVIDIA driver 550.x or newer"
  elif [[ "$KERNEL_MAJOR" -ge 6 ]]; then
    # Kernel 6.2-6.7 (Proxmox 8.x initial) - Works with 535.x or higher
    MIN_DRIVER_VERSION="535"
    RECOMMENDED_BRANCH="550"
    COMPATIBILITY_NOTE="Kernel $kernel_version works with NVIDIA driver 535.x or newer"
  elif [[ "$KERNEL_MAJOR" -eq 5 ]] && [[ "$KERNEL_MINOR" -ge 15 ]]; then
    # Kernel 5.15+ (Proxmox 7.x, 8.x legacy) - Works with 470.x or higher
    MIN_DRIVER_VERSION="470"
    RECOMMENDED_BRANCH="535"
    COMPATIBILITY_NOTE="Kernel $kernel_version works with NVIDIA driver 470.x or newer"
  else
    # Old kernels
    MIN_DRIVER_VERSION="450"
    RECOMMENDED_BRANCH="470"
    COMPATIBILITY_NOTE="For older kernels, compatibility may vary"
  fi
}

is_version_compatible() {
  local version="$1"
  local ver_major ver_minor ver_patch
  
  # Extract version components (major.minor.patch)
  ver_major=$(echo "$version" | cut -d. -f1)
  ver_minor=$(echo "$version" | cut -d. -f2)
  ver_patch=$(echo "$version" | cut -d. -f3)
  
  # Full-version comparison when MIN is dotted (e.g. "580.105.08").
  # Strips the dotted threshold from MIN_DRIVER_VERSION and reuses the
  # existing `version_le` helper. The previous code had a hardcoded
  # branch only for "580.82.07" — bumping the floor required editing two
  # places. Sprint 11.4.
  case "$MIN_DRIVER_VERSION" in
    *.*.*)
      # Dotted threshold: compare full triple.
      local _min_major _min_minor _min_patch
      IFS='.' read -r _min_major _min_minor _min_patch <<<"$MIN_DRIVER_VERSION"
      _min_major=${_min_major:-0}
      _min_minor=${_min_minor:-0}
      _min_patch=${_min_patch:-0}
      ver_minor=${ver_minor:-0}
      ver_patch=${ver_patch:-0}
      if (( 10#$ver_major > 10#$_min_major )); then
        return 0
      elif (( 10#$ver_major == 10#$_min_major )); then
        if (( 10#$ver_minor > 10#$_min_minor )); then
          return 0
        elif (( 10#$ver_minor == 10#$_min_minor )); then
          if (( 10#${ver_patch:-0} >= 10#$_min_patch )); then
            return 0
          fi
        fi
      fi
      return 1
      ;;
    *)
      # Single-major threshold (e.g. "550", "535"): compare major only.
      if [[ ${ver_major} -ge ${MIN_DRIVER_VERSION} ]]; then
        return 0
      else
        return 1
      fi
      ;;
  esac
}


is_current_nvidia_patched() {
  local status_file="/usr/local/share/proxmenux/components_status.json"
  [[ -f "$status_file" ]] || return 1
  command -v jq >/dev/null 2>&1 || return 1
  local patched
  patched=$(jq -r '.nvidia_driver.patched // false' "$status_file" 2>/dev/null)
  [[ "$patched" == "true" ]]
}

KEYLASE_PATCH_CACHE="/var/cache/proxmenux/keylase_patch_versions.txt"
KEYLASE_PATCH_TTL_SECONDS=$((7 * 86400))
KEYLASE_PATCH_URL="https://raw.githubusercontent.com/keylase/nvidia-patch/master/patch.sh"

refresh_keylase_patch_cache() {
  local now ts age
  now=$(date +%s)
  if [[ -f "$KEYLASE_PATCH_CACHE" ]]; then
    ts=$(stat -c '%Y' "$KEYLASE_PATCH_CACHE" 2>/dev/null || echo 0)
    age=$(( now - ts ))
    if (( age < KEYLASE_PATCH_TTL_SECONDS )) && [[ -s "$KEYLASE_PATCH_CACHE" ]]; then
      return 0
    fi
  fi
  mkdir -p "$(dirname "$KEYLASE_PATCH_CACHE")" 2>/dev/null || return 1
  local tmp
  tmp=$(mktemp)
  if curl -fsSL --max-time 15 "$KEYLASE_PATCH_URL" 2>/dev/null \
       | grep -oE '\["[0-9]+\.[0-9]+(\.[0-9]+)?"\]' \
       | sed -E 's/\["([0-9.]+)"\]/\1/' \
       | sort -u > "$tmp" && [[ -s "$tmp" ]]; then
    mv "$tmp" "$KEYLASE_PATCH_CACHE"
    return 0
  fi
  rm -f "$tmp"
  return 1
}

is_keylase_patch_supported() {
  local ver="$1"
  [[ -z "$ver" ]] && return 1
  [[ -f "$KEYLASE_PATCH_CACHE" && -s "$KEYLASE_PATCH_CACHE" ]] || return 1
  grep -qFx "$ver" "$KEYLASE_PATCH_CACHE"
}

filter_keylase_supported() {
  local versions_in="$1"
  while IFS= read -r ver; do
    [[ -z "$ver" ]] && continue
    if is_keylase_patch_supported "$ver"; then
      printf '%s\n' "$ver"
    fi
  done <<< "$versions_in"
}

filter_option_c_branch() {
  local versions_in="$1"
  local current="$2"
  local recommended_branch="$3"
  local target_branch=""

  if [[ -n "$current" && "$current" =~ ^([0-9]+)\. ]]; then
    local current_branch="${BASH_REMATCH[1]}"
    if is_version_compatible "$current"; then
      target_branch="$current_branch"
    fi
  fi

  if [[ -z "$target_branch" ]]; then
    target_branch="$recommended_branch"
  fi

  if [[ -z "$target_branch" ]]; then
    printf '%s\n' "$versions_in"
    return 0
  fi

  while IFS= read -r ver; do
    [[ -z "$ver" ]] && continue
    local ver_major="${ver%%.*}"
    if [[ "$ver_major" == "$target_branch" ]]; then
      printf '%s\n' "$ver"
    fi
  done <<< "$versions_in"
}

version_le() {
  local v1="$1"
  local v2="$2"

  IFS='.' read -r a1 b1 c1 <<<"$v1"
  IFS='.' read -r a2 b2 c2 <<<"$v2"

  a1=${a1:-0}; b1=${b1:-0}; c1=${c1:-0}
  a2=${a2:-0}; b2=${b2:-0}; c2=${c2:-0}

  a1=$((10#$a1)); b1=$((10#$b1)); c1=$((10#$c1))
  a2=$((10#$a2)); b2=$((10#$b2)); c2=$((10#$c2))

  if (( a1 < a2 )); then
    return 0
  elif (( a1 > a2 )); then
    return 1
  fi

  if (( b1 < b2 )); then
    return 0
  elif (( b1 > b2 )); then
    return 1
  fi

  if (( c1 <= c2 )); then
    return 0
  else
    return 1
  fi
}


# ==========================================================
# NVIDIA version management - FIXED VERSION
# ==========================================================
download_latest_version() {
  local latest_line version

  latest_line=$(curl -fsSL "${NVIDIA_BASE_URL}/latest.txt" 2>&1)
  if [[ -z "$latest_line" ]]; then
    echo "" >&2
    return 1
  fi

  version=$(echo "$latest_line" | awk '{print $1}' | tr -d '[:space:]')
  
  if [[ -z "$version" ]]; then
    echo "" >&2
    return 1
  fi
  
  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    echo "" >&2
    return 1
  fi
  
  echo "$version"
  return 0
}

list_available_versions() {
  local html_content versions
  
  html_content=$(curl -s "$NVIDIA_BASE_URL/" 2>&1)
  
  if [[ -z "$html_content" ]]; then
    echo "" >&2
    return 1
  fi
  
  versions=$(echo "$html_content" \
    | grep -o 'href=[^ >]*' \
    | awk -F"'" '{print $2}' \
    | grep -E '^[0-9]' \
    | sed 's/\/$//' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | sort -Vr \
    | uniq)
  
  if [[ -z "$versions" ]]; then
    echo "" >&2
    return 1
  fi
  
  echo "$versions"
  return 0
}

verify_version_exists() {
  local version="$1"
  local url="${NVIDIA_BASE_URL}/${version}/"
  
  if curl -fsSL --head "$url" >/dev/null 2>&1; then
    return 0
  else
    return 1
  fi
}

download_nvidia_installer() {
  ensure_workdir
  local version="$1"
  
  version=$(echo "$version" | tr -d '[:space:]' | tr -d '\n' | tr -d '\r')
  
  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    msg_error "Invalid version format: $version" >&2
    echo "ERROR: Invalid version format: '$version'" >> "$LOG_FILE"
    return 1
  fi
  
  local run_file="$NVIDIA_WORKDIR/NVIDIA-Linux-x86_64-${version}.run"

  if [[ -f "$run_file" ]]; then
    echo "Found existing file: $run_file" >> "$LOG_FILE"
    local existing_size file_type
    existing_size=$(stat -c%s "$run_file" 2>/dev/null || stat -f%z "$run_file" 2>/dev/null || echo "0")
    file_type=$(file "$run_file" 2>/dev/null || echo "unknown")
    
    echo "Existing file size: $existing_size bytes" >> "$LOG_FILE"
    echo "Existing file type: $file_type" >> "$LOG_FILE"
    
 
    if [[ $existing_size -gt 40000000 ]] && echo "$file_type" | grep -q "executable"; then

      if sh "$run_file" --check 2>&1 | tee -a "$LOG_FILE" | grep -q "OK"; then
        echo "Existing file passed integrity check" >> "$LOG_FILE"
        msg_ok "$(translate 'Installer already downloaded and verified.')" >&2
        printf '%s\n' "$run_file"
        return 0
      else
        echo "Existing file FAILED integrity check, removing..." >> "$LOG_FILE"
        msg_warn "$(translate 'Existing file, re-downloading...')" >&2
        rm -f "$run_file"
      fi
    else
      echo "Existing file invalid (size or type), removing..." >> "$LOG_FILE"
      msg_warn "$(translate 'Removing invalid existing file...')" >&2
      rm -f "$run_file"
    fi
  fi

  if ! verify_version_exists "$version"; then
    msg_error "Version $version does not exist on NVIDIA servers" >&2
    echo "ERROR: Version $version not found on server" >> "$LOG_FILE"
    return 1
  fi

  local urls=(
    "${NVIDIA_BASE_URL}/${version}/NVIDIA-Linux-x86_64-${version}.run"
    "${NVIDIA_BASE_URL}/${version}/NVIDIA-Linux-x86_64-${version}-no-compat32.run"
  )

  # Web mode (ProxMenux Monitor) runs scripts without a controlling TTY, so
  # /dev/tty is not writable and progress-bar animations using \r don't render
  # in the web terminal. Fall back to a quiet wget in that case; interactive
  # users (SSH / console) still get the ISO-like progress bar.
  local _nv_has_tty=false
  if ! is_web_mode 2>/dev/null && [[ -t 2 ]]; then
    _nv_has_tty=true
  fi

  if $_nv_has_tty; then
    printf '\n  %s NVIDIA-Linux-x86_64-%s.run\n' \
      "$(translate 'Downloading')" "$version" >/dev/tty
  else
    echo "  $(translate 'Downloading') NVIDIA-Linux-x86_64-${version}.run" >&2
  fi

  local success=false
  local url_index=0

  for url in "${urls[@]}"; do
    ((url_index++))
    echo "Attempting download from: $url" >> "$LOG_FILE"

    rm -f "$run_file"

    local _dl_ok=false
    if $_nv_has_tty; then
      # Interactive: progress bar to /dev/tty (bypasses any caller redirection).
      if wget --no-verbose --show-progress \
              --connect-timeout=30 --timeout=600 --tries=1 \
              -O "$run_file" "$url" 2>/dev/tty; then
        _dl_ok=true
      fi
    else
      # Web / no-TTY: silent wget, log errors only.
      if wget --quiet \
              --connect-timeout=30 --timeout=600 --tries=1 \
              -O "$run_file" "$url" 2>>"$LOG_FILE"; then
        _dl_ok=true
      fi
    fi

    if $_dl_ok; then
      echo "Download completed, verifying file..." >> "$LOG_FILE"

      if [[ ! -f "$run_file" ]]; then
        echo "ERROR: File not created after download" >> "$LOG_FILE"
        continue
      fi

      local file_size
      file_size=$(stat -c%s "$run_file" 2>/dev/null || stat -f%z "$run_file" 2>/dev/null || echo "0")
      echo "Downloaded file size: $file_size bytes" >> "$LOG_FILE"

      if [[ $file_size -lt 40000000 ]]; then
        echo "ERROR: File too small ($file_size bytes, expected >40MB)" >> "$LOG_FILE"
        head -c 200 "$run_file" >> "$LOG_FILE" 2>&1
        rm -f "$run_file"
        continue
      fi

      local file_type
      file_type=$(file "$run_file" 2>/dev/null)
      echo "File type: $file_type" >> "$LOG_FILE"

      if echo "$file_type" | grep -q "executable"; then
        echo "SUCCESS: Valid executable downloaded" >> "$LOG_FILE"
        success=true
        break
      else
        echo "ERROR: Not a valid executable" >> "$LOG_FILE"
        head -c 200 "$run_file" | od -c >> "$LOG_FILE" 2>&1
        rm -f "$run_file"
      fi
    else
      echo "ERROR: wget failed for $url (exit code: $?)" >> "$LOG_FILE"
      rm -f "$run_file"
    fi
  done

  if ! $success; then
    msg_error "$(translate 'Download failed for all attempted URLs')" >&2
    msg_error "Version $version may not be available for your architecture" >&2
    echo "ERROR: All download attempts failed" >> "$LOG_FILE"
    return 1
  fi

  chmod +x "$run_file"
  echo "Installation file ready: $run_file" >> "$LOG_FILE"
  printf '%s\n' "$run_file"
}

# ==========================================================
# Installation / uninstallation
# ==========================================================
run_nvidia_installer() {
  local installer="$1"

  msg_info2 "$(translate 'Starting NVIDIA installer. This may take several minutes...')"
  echo "" >>"$LOG_FILE"
  echo "=== Running NVIDIA installer: $installer ===" >>"$LOG_FILE"

  # If nouveau is still loaded, rebuild initramfs first so the blacklist takes
  # effect for the installer sanity checks. Without this the .run installer
  # detects nouveau as active and aborts even when --disable-nouveau is passed.
  if [[ "${NOUVEAU_STILL_LOADED:-false}" == "true" ]]; then
    msg_info "$(translate 'Rebuilding initramfs to apply nouveau blacklist before installation...')"
    update-initramfs -u -k all >>"$LOG_FILE" 2>&1 || true
    # Try one more time to unload nouveau after initramfs rebuild
    modprobe -r nouveau 2>/dev/null || true
    sleep 1
    if grep -q "^nouveau " /proc/modules 2>/dev/null; then
      echo "WARNING: nouveau still loaded after initramfs rebuild, proceeding with --no-nouveau-check" >> "$LOG_FILE"
      msg_warn "$(translate 'nouveau still active. Proceeding with installation. A reboot will be required for the driver to work.')"
    else
      NOUVEAU_STILL_LOADED=false
      msg_ok "$(translate 'nouveau module unloaded after initramfs rebuild.')" | tee -a "$screen_capture"
    fi
  fi

  local tmp_extract_dir="$NVIDIA_WORKDIR/tmp_extract"
  mkdir -p "$tmp_extract_dir"

  # --no-nouveau-check: prevents the installer from aborting when nouveau is
  # still loaded. The blacklist files are already in place; nouveau will be
  # gone after the reboot that the script offers at the end.
  sh "$installer" \
    --tmpdir="$tmp_extract_dir" \
    --no-questions \
    --ui=none \
    --disable-nouveau \
    --no-nouveau-check \
    --dkms \
    2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}
  echo "" >>"$LOG_FILE"
  
  rm -rf "$tmp_extract_dir"

  if [[ $rc -ne 0 ]]; then
    msg_error "$(translate 'NVIDIA installer reported an error. Check /tmp/nvidia_install.log')"
    update_component_status "nvidia_driver" "failed" "" "gpu" '{"patched":false}'
    return 1
  fi

  msg_ok "$(translate 'NVIDIA driver installed successfully.')" | tee -a "$screen_capture"
  return 0
}

remove_nvidia_driver() {
  complete_nvidia_uninstall
}

install_udev_rules_and_persistenced() {
  msg_info "$(translate 'Installing NVIDIA udev rules and persistence service...')"

  cat >/etc/udev/rules.d/70-nvidia.rules <<'EOF'
# /etc/udev/rules.d/70-nvidia.rules
KERNEL=="nvidia", RUN+="/bin/bash -c '/usr/bin/nvidia-smi -L'"
KERNEL=="nvidia_uvm", RUN+="/bin/bash -c '/usr/bin/nvidia-modprobe -c0 -u'"
EOF

  udevadm control --reload-rules
  udevadm trigger --subsystem-match=drm --subsystem-match=pci || true

  ensure_workdir
  cd "$NVIDIA_WORKDIR" || return 1
  # Pin to the last release tag so a hostile push to upstream `master`
  # can't slip arbitrary code into the install. Bump as needed; the
  # `--depth 1` keeps the clone fast. Audit Tier 6 — `nvidia-persistenced`
  # git clone sin pinning de versión.
  local NVIDIA_PERSISTENCED_TAG="${NVIDIA_PERSISTENCED_TAG:-575.64.05}"
  if [[ ! -d nvidia-persistenced ]]; then
    git clone --depth 1 --branch "$NVIDIA_PERSISTENCED_TAG" \
      https://github.com/NVIDIA/nvidia-persistenced.git >>"$LOG_FILE" 2>&1 \
      || git clone --depth 1 https://github.com/NVIDIA/nvidia-persistenced.git >>"$LOG_FILE" 2>&1 \
      || true
  fi

  if [[ -d nvidia-persistenced/init ]]; then
    cd nvidia-persistenced/init || return 1
    ./install.sh >>"$LOG_FILE" 2>&1 || true
  fi

  msg_ok "$(translate 'NVIDIA udev rules and persistence service installed.')" | tee -a "$screen_capture"
}

apply_nvidia_patch_if_needed() {
  if ! hybrid_whiptail_yesno "$(translate 'NVIDIA Patch')" \
    "\n$(translate 'Do you want to apply the optional NVIDIA patch to remove some GPU limitations?')"; then
    msg_info2 "$(translate 'NVIDIA patch not applied.')"
    update_component_status "nvidia_driver" "installed" "$CURRENT_DRIVER_VERSION" "gpu" '{"patched":false}'
    return 0
  fi

  msg_info "$(translate 'Cloning and applying NVIDIA patch (keylase/nvidia-patch)...')"
  ensure_workdir
  cd "$NVIDIA_WORKDIR" || return 1
  # Pin keylase/nvidia-patch to a known-good commit. Override via env var
  # for forward-compat as new driver versions land. patch.sh ships a list
  # of supported drivers in the repo; if our running driver isn't covered
  # the patch silently no-ops, so we surface a warning before running.
  # Audit Tier 6 — `keylase/nvidia-patch` sin pinning + sin compat check.
  local NVIDIA_PATCH_REF="${NVIDIA_PATCH_REF:-master}"
  if [[ ! -d nvidia-patch ]]; then
    git clone --depth 1 --branch "$NVIDIA_PATCH_REF" \
      https://github.com/keylase/nvidia-patch.git >>"$LOG_FILE" 2>&1 \
      || git clone --depth 1 https://github.com/keylase/nvidia-patch.git >>"$LOG_FILE" 2>&1 \
      || true
  fi

  # Best-effort compatibility check: peek the supported-driver list in
  # patch.sh and warn if our driver isn't on it.
  if [[ -n "$CURRENT_DRIVER_VERSION" && -f nvidia-patch/patch.sh ]]; then
    if ! grep -qF "$CURRENT_DRIVER_VERSION" nvidia-patch/patch.sh 2>/dev/null; then
      msg_warn "$(translate 'NVIDIA driver') $CURRENT_DRIVER_VERSION $(translate 'is not in the patch.sh supported list. The patch may no-op or fail; review keylase/nvidia-patch README before continuing.')"
    fi
  fi

  if [[ -x nvidia-patch/patch.sh ]]; then
    cd nvidia-patch || return 1
    ./patch.sh >>"$LOG_FILE" 2>&1 || true
    msg_ok "$(translate 'NVIDIA patch applied - check README for supported versions.')"
    update_component_status "nvidia_driver" "installed" "$CURRENT_DRIVER_VERSION" "gpu" '{"patched":true}'
  else
    msg_warn "$(translate 'Could not run NVIDIA patch script. Please verify repository and driver version.')"
    update_component_status "nvidia_driver" "installed" "$CURRENT_DRIVER_VERSION" "gpu" '{"patched":false}'
  fi
}

restart_prompt() {
  if hybrid_whiptail_yesno "$(translate 'NVIDIA Drivers')" \
    "\n$(translate 'The installation/changes require a server restart to apply correctly. Do you want to reboot now?')"; then
    msg_success "$(translate 'Installation completed. Press Enter to continue...')"
    read -r
    msg_warn "$(translate 'Restarting the server...')"
    rm -f "$screen_capture"
    reboot
  else
    msg_success "$(translate 'Installation completed. Please reboot the server manually as soon as possible.')"
    msg_success "$(translate 'Completed. Press Enter to return to menu...')"
    read -r
    rm -f "$screen_capture"
  fi
}

# ==========================================================
# Dialog menus
# ==========================================================
show_action_menu_if_installed() {
  if ! $CURRENT_DRIVER_INSTALLED; then
    ACTION="install"
    return 0
  fi

  local menu_choices=(
    "install" "$(translate 'Reinstall/Update NVIDIA drivers')"
    "remove"  "$(translate 'Uninstall NVIDIA drivers and configuration')"
  )

  ACTION=$(hybrid_menu "ProxMenux" "$(translate 'NVIDIA Actions')\n\n$(translate 'Choose an action:')" 14 80 8 "${menu_choices[@]}") || ACTION="cancel"
}

show_install_overview() {
  local overview
  overview="\n$(translate 'This installation will:')\n\n"
  overview+=" • $(translate 'Install NVIDIA proprietary drivers')\n"
  overview+=" • $(translate 'Configure GPU passthrough with VFIO')\n"
  overview+=" • $(translate 'Blacklist nouveau driver')\n"
  overview+=" • $(translate 'Enable IOMMU support if not enabled')\n"
  overview+=" • $(translate 'Optionally update NVIDIA libs in LXC containers with passthrough')\n\n"

  overview+="$(translate 'Detected GPU(s):')\n"
  overview+="\Zb\Z4$DETECTED_GPUS_TEXT\Zn\n"

  overview+="\n\Zn$(translate 'Current status: ') "
  overview+="\Zb${CURRENT_STATUS_TEXT}\Zn\n"

  # Scan for LXC containers with NVIDIA passthrough and surface them in the
  # overview so the user knows upfront they will be offered a driver update.
  find_nvidia_containers
  if [[ ${#NVIDIA_CONTAINERS[@]} -gt 0 ]]; then
    overview+="\n$(translate 'LXC containers with NVIDIA passthrough:')\n"
    local ctid lxc_ver ct_name
    for ctid in "${NVIDIA_CONTAINERS[@]}"; do
      lxc_ver=$(get_lxc_nvidia_version "$ctid")
      ct_name=$(pct config "$ctid" 2>/dev/null | grep "^hostname:" | awk '{print $2}')
      overview+="  \Zb\Z4CT ${ctid}\Zn  ${ct_name:+(${ct_name})}  — $(translate 'driver:') ${lxc_ver}\n"
    done
  fi

  overview+="\n$(translate 'After confirming, you will be asked to choose the NVIDIA driver version to install.')\n\n"
  overview+="$(translate 'Do you want to continue?')"

  hybrid_yesno "$(translate 'NVIDIA GPU Driver Installation')" "$overview" 24 90
}

show_version_menu() {
  local latest versions_list
  local kernel_version
  kernel_version=$(uname -r)
  

  latest=$(download_latest_version 2>/dev/null)
  

  versions_list=$(list_available_versions 2>/dev/null)
  

  if [[ -z "$latest" ]] && [[ -z "$versions_list" ]]; then
    hybrid_msgbox "$(translate 'Error')" \
      "$(translate 'Could not retrieve versions list from NVIDIA. Please check your internet connection.')\n\nURL: ${NVIDIA_BASE_URL}" 10 80
    DRIVER_VERSION="cancel"
    return 1
  fi
  

  if [[ -z "$latest" ]] && [[ -n "$versions_list" ]]; then
    latest=$(echo "$versions_list" | head -n1)
  fi
  

  if [[ -n "$latest" ]] && [[ -z "$versions_list" ]]; then
    versions_list="$latest"
  fi
  
  # Clean latest version
  latest=$(echo "$latest" | tr -d '[:space:]')
  
  local current_list="$versions_list"
  
  # Apply kernel compatibility filter if needed
  if [[ -n "$MIN_DRIVER_VERSION" ]]; then
    local filtered_list=""
    while IFS= read -r ver; do
      [[ -z "$ver" ]] && continue
      if is_version_compatible "$ver"; then
        filtered_list+="$ver"$'\n'
      fi
    done <<< "$current_list"
    current_list="$filtered_list"
  fi

  # Option C: kernel-compat alone is too permissive (e.g. kernel 6.14
  # accepts ≥ 550 so 595.x shows up — but 595.x has historically broken
  # builds on this kernel). Restrict the offered list to the user's
  # current branch when their installed driver still works, otherwise
  # fall back to the recommended branch for the kernel.
  if [[ -n "$current_list" ]]; then
    current_list=$(filter_option_c_branch "$current_list" "$CURRENT_DRIVER_VERSION" "$RECOMMENDED_BRANCH")
  fi

  if [[ -n "$latest" ]]; then
    local filtered_max_list=""
    while IFS= read -r ver; do
      [[ -z "$ver" ]] && continue
      if version_le "$ver" "$latest"; then
        filtered_max_list+="$ver"$'\n'
      fi
    done <<< "$current_list"
    current_list="$filtered_max_list"
  fi

  # If the user has the keylase NVENC patch applied, only offer versions
  # that the patch supports — picking an unsupported version reinstalls
  # the driver fine but the patch silently no-ops afterwards, so the
  # user loses NVENC limit removal without warning.
  local patch_filtered=false
  local patch_filter_note=""
  if is_current_nvidia_patched && [[ -n "$current_list" ]]; then
    if refresh_keylase_patch_cache; then
      local trimmed
      trimmed=$(filter_keylase_supported "$current_list")
      if [[ -n "$trimmed" ]]; then
        current_list="$trimmed"
        patch_filtered=true
      else
        patch_filter_note="$(translate 'No version in this branch is currently supported by keylase/nvidia-patch — the NVENC patch will not reapply after reinstall.')"
      fi
    else
      patch_filter_note="$(translate 'Could not fetch keylase/nvidia-patch supported list — patch reapply compatibility is not verified.')"
    fi
  fi

  # Recompute "latest" as the highest version still in the filtered list
  # so the menu's "Latest available" label matches what we actually offer
  # rather than the global upstream latest (which may have been filtered
  # out by Option C / kernel-compat / patch awareness).
  if [[ -n "$current_list" ]]; then
    latest=$(printf '%s\n' "$current_list" | head -n1 | tr -d '[:space:]')
  fi

  local menu_text="$(translate 'Select the NVIDIA driver version to install:')\n\n"
  menu_text+="$(translate 'Versions shown are compatible with your kernel. Latest available is recommended in most cases.')"
  if $patch_filtered; then
    menu_text+="\n\n$(translate 'NVENC patch detected — list narrowed to versions supported by keylase/nvidia-patch.')"
  elif [[ -n "$patch_filter_note" ]]; then
    menu_text+="\n\n${patch_filter_note}"
  fi

  local choices=()
  choices+=("latest" "$(translate 'Latest available') (${latest:-unknown})")
  choices+=("" "")

  if [[ -n "$current_list" ]]; then
    while IFS= read -r ver; do
      [[ -z "$ver" ]] && continue
      ver=$(echo "$ver" | tr -d '[:space:]')
      [[ -z "$ver" ]] && continue
      
      choices+=("$ver" "$ver")
    done <<< "$current_list"
  else
    choices+=("" "$(translate 'No compatible versions found for your kernel')")
  fi

  local selection=$(hybrid_menu "$(translate 'NVIDIA Driver Version')" "$menu_text" 26 90 16 "${choices[@]}") || { DRIVER_VERSION="cancel"; return 1; }

  case "$selection" in
    "")
      DRIVER_VERSION="cancel"
      return 1
      ;;
    latest)
      DRIVER_VERSION="$latest"
      DRIVER_VERSION=$(echo "$DRIVER_VERSION" | tr -d '[:space:]')
      return 0
      ;;
    *)
      DRIVER_VERSION="$selection"
      DRIVER_VERSION=$(echo "$DRIVER_VERSION" | tr -d '[:space:]')
      return 0
      ;;
  esac
}

# ==========================================================
# Main flow
# ==========================================================
main() {
  # Rotate the previous run's log instead of truncating — when the
  # current install fails, the user can compare against the previous
  # attempt to see what changed. Audit Tier 7 — log truncation.
  if [[ -f "$LOG_FILE" && -s "$LOG_FILE" ]]; then
    cp -p "$LOG_FILE" "${LOG_FILE}.prev" 2>/dev/null || true
  fi
  : >"$LOG_FILE"
  : >"$screen_capture"

  NOUVEAU_STILL_LOADED=false

  detect_nvidia_gpus
  detect_driver_status
  check_gpu_not_in_vm_passthrough

  if ! $NVIDIA_GPU_PRESENT; then
    dialog --backtitle "ProxMenux" --title "$(translate 'NVIDIA GPU Driver Installation')" --msgbox \
      "\n$(translate 'No NVIDIA GPU has been detected on this system. The installer will now exit.')" 20 70
    exit 1
  fi

  show_action_menu_if_installed

  case "$ACTION" in
    install)
      if ! show_install_overview; then
        exit 0
      fi

      get_kernel_compatibility_info

      show_version_menu
      if [[ "$DRIVER_VERSION" == "cancel" || -z "$DRIVER_VERSION" ]]; then
        exit 0
      fi

      if $CURRENT_DRIVER_INSTALLED; then
        if [[ "$CURRENT_DRIVER_VERSION" == "$DRIVER_VERSION" ]]; then
          local confirm_text
          confirm_text="\n\n\n$(translate 'Version') \Zb\Z4$DRIVER_VERSION\Zn\n\n$(translate 'is already installed. Do you want to reinstall it? This will perform a clean uninstall first.')"
          if ! hybrid_yesno "$(translate 'Same Version Detected')" "$confirm_text" 14 70; then
              exit 0
          fi
        else
          local confirm_text
          confirm_text="\n\n$(translate 'Current version:') \Zb$CURRENT_DRIVER_VERSION\Zn\n"
          confirm_text+="$(translate 'New version:') \Zb\Z4$DRIVER_VERSION\Zn\n\n"
          confirm_text+="$(translate 'The current driver will be completely uninstalled before installing the new version. Continue?')"
          if ! hybrid_yesno "$(translate 'Version Change Detected')" "$confirm_text" 20 70; then
              exit 0
          fi
        fi
        
        show_proxmenux_logo
        msg_title "$(translate "$SCRIPT_TITLE")"
        msg_info2 "$(translate 'Uninstalling current NVIDIA driver before installing new version')"
        complete_nvidia_uninstall
        
        sleep 2
        
        CURRENT_DRIVER_INSTALLED=false
        CURRENT_DRIVER_VERSION=""
      fi

      show_proxmenux_logo
      msg_title "$(translate "$SCRIPT_TITLE")"

      ensure_repos_and_headers
      blacklist_nouveau
      ensure_modules_config
      
      stop_and_disable_nvidia_services
      unload_nvidia_modules

      # No msg_info spinner here — it would clash with wget --show-progress,
      # which writes its progress bar directly to /dev/tty from inside the
      # download function. Stderr from the function is allowed through so
      # warnings/errors reach the user.
      local installer
      installer=$(download_nvidia_installer "$DRIVER_VERSION")
      local download_result=$?

      if [[ $download_result -ne 0 ]]; then
        msg_error "$(translate 'Failed to download NVIDIA installer')"
        exit 1
      fi

      msg_ok "$(translate 'NVIDIA installer downloaded successfully')" | tee -a "$screen_capture"

      if [[ -z "$installer" || ! -f "$installer" ]]; then
        msg_error "$(translate 'Internal error: NVIDIA installer path is empty or file not found.')"
        rm -f "$screen_capture"
        exit 1
      fi

      if ! run_nvidia_installer "$installer"; then
        rm -f "$screen_capture"
        exit 1
      fi
      
      sleep 2
      show_proxmenux_logo
      msg_title "$(translate "$SCRIPT_TITLE")"
      cat "$screen_capture"
      echo -e "${TAB}${GN}📄 $(translate "Log file")${CL}: ${BL}$LOG_FILE${CL}"

      install_udev_rules_and_persistenced

      msg_info "$(translate 'Updating initramfs for all kernels...')"
      update-initramfs -u -k all >>"$LOG_FILE" 2>&1 || true
      msg_ok "$(translate 'initramfs updated.')"

      msg_info2 "$(translate 'Checking NVIDIA driver status with nvidia-smi')"
      if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi || true
        CURRENT_DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1)
        CURRENT_DRIVER_INSTALLED=true
      else
        msg_warn "$(translate 'nvidia-smi not found in PATH. Please verify the driver installation.')"
      fi

      if [[ -n "$CURRENT_DRIVER_VERSION" ]]; then
        msg_ok "$(translate 'NVIDIA driver') $CURRENT_DRIVER_VERSION $(translate 'installed successfully.')"
        update_component_status "nvidia_driver" "installed" "$CURRENT_DRIVER_VERSION" "gpu" '{"patched":false}'
        msg_success "$(translate 'Driver installed successfully. Press Enter to continue...')"
        read -r
      else
        msg_error "$(translate 'Failed to detect installed NVIDIA driver version.')"
        update_component_status "nvidia_driver" "failed" "" "gpu" '{"patched":false}'
      fi

      # Propagate the new driver to LXC containers with NVIDIA passthrough, if any.
      # Uses the same .run installer cached in $NVIDIA_WORKDIR — runs only if the
      # host install succeeded and the user confirms.
      if [[ -n "$CURRENT_DRIVER_VERSION" ]]; then
        offer_lxc_updates_if_any "$CURRENT_DRIVER_VERSION"
      fi

      apply_nvidia_patch_if_needed
      restart_prompt
      ;;
    remove)
      if hybrid_yesno "$(translate 'NVIDIA Driver Uninstall')" \
        "\n\n\n$(translate 'This will remove NVIDIA drivers and related configuration. Do you want to continue?')" 14 70; then

        show_proxmenux_logo
        msg_title "$(translate "$SCRIPT_TITLE")"

        remove_nvidia_driver

        msg_info "$(translate 'Updating initramfs for all kernels...')"
        update-initramfs -u -k all >>"$LOG_FILE" 2>&1 || true
        msg_ok "$(translate 'initramfs updated.')"

        restart_prompt
      fi
      ;;
    cancel|*)
      exit 0
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi