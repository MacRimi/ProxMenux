#!/bin/bash
# ProxMenux - NVIDIA Driver Installer (PVE 9.x)
# ============================================
# Author      : MacRimi
# License     : MIT
# Version     : 0.9 (PVE9, fixed download issues)
# Last Updated: 29/11/2025
# ============================================

SCRIPT_TITLE="NVIDIA GPU Driver Installer for Proxmox VE"

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
COMPONENTS_STATUS_FILE="$BASE_DIR/components_status.json"
LOG_FILE="/tmp/nvidia_install.log"
screen_capture="/tmp/proxmenux_nvidia_screen_capture_$$.txt"

NVIDIA_BASE_URL="https://download.nvidia.com/XFree86/Linux-x86_64"
NVIDIA_WORKDIR="/opt/nvidia"

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

detect_driver_status() {
  CURRENT_DRIVER_INSTALLED=false
  CURRENT_DRIVER_VERSION=""
  
  # First check if nvidia kernel module is actually loaded
  if lsmod | grep -q "^nvidia "; then

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
  if ! grep -q '^blacklist nouveau' /etc/modprobe.d/blacklist.conf 2>/dev/null; then
    echo "blacklist nouveau" >> /etc/modprobe.d/blacklist.conf
  fi
  msg_ok "$(translate 'nouveau driver has been blacklisted.')" | tee -a "$screen_capture"
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
  msg_info "$(translate 'Unloading NVIDIA kernel modules...')"

  for mod in nvidia_uvm nvidia_drm nvidia_modeset nvidia; do
    modprobe -r "$mod" >/dev/null 2>&1 || true
  done


  if lsmod | grep -qi '\bnvidia'; then
    for mod in nvidia_uvm nvidia_drm nvidia_modeset nvidia; do
      modprobe -r --force "$mod" >/dev/null 2>&1 || true
    done
  fi

  if lsmod | grep -qi '\bnvidia'; then
    msg_warn "$(translate 'Some NVIDIA modules could not be unloaded. Installation may fail. Ensure no processes are using the GPU.')"
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
  
  # Define minimum compatible versions based on kernel
  # Based on https://docs.nvidia.com/datacenter/tesla/drivers/index.html
  if [[ "$KERNEL_MAJOR" -ge 6 ]] && [[ "$KERNEL_MINOR" -ge 17 ]]; then
    # Kernel 6.17+ (Proxmox 9.x) - Requires 580.82.07 or higher
    MIN_DRIVER_VERSION="580.82.07"
    RECOMMENDED_BRANCH="580"
    COMPATIBILITY_NOTE="Kernel $kernel_version requires NVIDIA driver 580.82.07 or newer"
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
  
  if [[ "$MIN_DRIVER_VERSION" == "580.82.07" ]]; then
    # Compare full version: must be >= 580.82.07
    if [[ ${ver_major} -gt 580 ]]; then
      return 0
    elif [[ ${ver_major} -eq 580 ]]; then
      if [[ $((10#${ver_minor})) -gt 82 ]]; then
        return 0
      elif [[ $((10#${ver_minor})) -eq 82 ]]; then
        if [[ $((10#${ver_patch:-0})) -ge 7 ]]; then
          return 0
        fi
      fi
    fi
    return 1
  fi
  

  if [[ ${ver_major} -ge ${MIN_DRIVER_VERSION} ]]; then
    return 0
  else
    return 1
  fi
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
        msg_warn "$(translate 'Existing file failed verification, re-downloading...')" >&2
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
  
  local success=false
  local url_index=0
  
  for url in "${urls[@]}"; do
    ((url_index++))
    echo "Attempting download from: $url" >> "$LOG_FILE"
    

    rm -f "$run_file"
    

    if curl -fL --connect-timeout 30 --max-time 600 "$url" -o "$run_file" >> "$LOG_FILE" 2>&1; then
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
      echo "ERROR: curl failed for $url (exit code: $?)" >> "$LOG_FILE"
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

  local tmp_extract_dir="$NVIDIA_WORKDIR/tmp_extract"
  mkdir -p "$tmp_extract_dir"
  
  sh "$installer" --tmpdir="$tmp_extract_dir" --no-questions --ui=none --disable-nouveau --dkms 2>&1 | tee -a "$LOG_FILE"
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
  if [[ ! -d nvidia-persistenced ]]; then
    git clone https://github.com/NVIDIA/nvidia-persistenced.git >>"$LOG_FILE" 2>&1 || true
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
  if [[ ! -d nvidia-patch ]]; then
    git clone https://github.com/keylase/nvidia-patch.git >>"$LOG_FILE" 2>&1 || true
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
  overview+=" • $(translate 'Enable IOMMU support if not enabled')\n\n"

  overview+="$(translate 'Detected GPU(s):')\n"
  overview+="\Zb\Z4$DETECTED_GPUS_TEXT\Zn\n"   

  overview+="\n\Zn$(translate 'Current status: ') "
  overview+="\Zb${CURRENT_STATUS_TEXT}\Zn\n\n"  

  overview+="$(translate 'After confirming, you will be asked to choose the NVIDIA driver version to install.')\n\n"
  overview+="$(translate 'Do you want to continue?')"

  hybrid_yesno "$(translate 'NVIDIA GPU Driver Installation')" "$overview" 22 90
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

  local menu_text="$(translate 'Select the NVIDIA driver version to install:')\n\n"
  menu_text+="$(translate 'Versions shown are compatible with your kernel. Latest available is recommended in most cases.')"

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
  : >"$LOG_FILE"
  : >"$screen_capture"

  detect_nvidia_gpus
  detect_driver_status

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
        msg_info2 "$(translate 'Uninstalling current NVIDIA driver before installing new version...')"
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

      msg_info "$(translate 'Downloading NVIDIA driver version:') $DRIVER_VERSION"
      
      local installer
      installer=$(download_nvidia_installer "$DRIVER_VERSION" 2>>"$LOG_FILE")
      local download_result=$?
      
      if [[ $download_result -ne 0 ]]; then
        msg_error "$(translate 'Failed to download NVIDIA installer')"
        exit 1
      fi
      
      msg_ok "$(translate 'NVIDIA installer downloaded successfully')"

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
