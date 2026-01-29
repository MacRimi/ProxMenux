#!/bin/bash
# ProxMenux - AMD GPU Tools Installer
# ============================================
# Author      : MacRimi
# License     : MIT
# Version     : 1.0
# Last Updated: 29/01/2026
# ============================================
# Installs amdgpu_top for monitoring AMD GPUs
# https://github.com/Umio-Yasuno/amdgpu_top

SCRIPT_TITLE="AMD GPU Tools Installer for Proxmox VE"

LOCAL_SCRIPTS="c"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
COMPONENTS_STATUS_FILE="$BASE_DIR/components_status.json"
LOG_FILE="/tmp/amd_gpu_tools_install.log"

export BASE_DIR
export COMPONENTS_STATUS_FILE

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

if [[ ! -f "$COMPONENTS_STATUS_FILE" ]]; then
  echo "{}" > "$COMPONENTS_STATUS_FILE"
fi

load_language 2>/dev/null || true
initialize_cache 2>/dev/null || true

# ==========================================================
# AMD GPU detection
# ==========================================================
detect_amd_gpus() {
  local lspci_output
  lspci_output=$(lspci | grep -iE "(AMD|ATI)" \
    | grep -Ei "VGA compatible controller|3D controller|Display controller" || true)

  if [[ -z "$lspci_output" ]]; then
    AMD_GPU_PRESENT=false
    DETECTED_GPUS_TEXT="No AMD GPU detected on this system."
  else
    AMD_GPU_PRESENT=true
    DETECTED_GPUS_TEXT=""
    local i=1
    while IFS= read -r line; do
      DETECTED_GPUS_TEXT+="  ${i}. ${line}\n"
      ((i++))
    done <<< "$lspci_output"
  fi
}

# ==========================================================
# Check if amdgpu_top is installed
# ==========================================================
check_amdgpu_top_installed() {
  if command -v amdgpu_top >/dev/null 2>&1; then
    AMDGPU_TOP_INSTALLED=true
    AMDGPU_TOP_VERSION=$(amdgpu_top --version 2>/dev/null | head -n1 || echo "unknown")
  else
    AMDGPU_TOP_INSTALLED=false
    AMDGPU_TOP_VERSION=""
  fi
}

# ==========================================================
# Get latest amdgpu_top release from GitHub
# ==========================================================
get_latest_release() {
  local api_url="https://api.github.com/repos/Umio-Yasuno/amdgpu_top/releases/latest"
  
  LATEST_VERSION=$(curl -sL "$api_url" | grep '"tag_name"' | head -n1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
  
  if [[ -z "$LATEST_VERSION" ]]; then
    msg_error "$(translate 'Failed to get latest version from GitHub')"
    return 1
  fi
  
  # Get the .deb download URL for amd64
  DEB_URL=$(curl -sL "$api_url" | grep -oP '"browser_download_url":\s*"\K[^"]+amd64\.deb' | head -n1)
  
  if [[ -z "$DEB_URL" ]]; then
    msg_error "$(translate 'Failed to get .deb download URL')"
    return 1
  fi
  
  return 0
}

# ==========================================================
# Install dependencies
# ==========================================================
install_dependencies() {
  msg_info "$(translate 'Installing required dependencies...')"
  
  apt-get update -qq >>"$LOG_FILE" 2>&1
  
  # Install libdrm packages required for amdgpu_top
  if apt-get install -y libdrm-dev libdrm-amdgpu1 libdrm2 curl wget >>"$LOG_FILE" 2>&1; then
    msg_ok "$(translate 'Dependencies installed successfully')"
    return 0
  else
    msg_error "$(translate 'Failed to install dependencies')"
    return 1
  fi
}

# ==========================================================
# Install amdgpu_top
# ==========================================================
install_amdgpu_top() {
  local tmp_dir="/tmp/amdgpu_top_install"
  mkdir -p "$tmp_dir"
  
  msg_info "$(translate 'Downloading amdgpu_top') ${LATEST_VERSION}..."
  
  local deb_file="$tmp_dir/amdgpu_top.deb"
  
  if ! wget -q -O "$deb_file" "$DEB_URL" >>"$LOG_FILE" 2>&1; then
    msg_error "$(translate 'Failed to download amdgpu_top')"
    rm -rf "$tmp_dir"
    return 1
  fi
  
  msg_ok "$(translate 'Downloaded amdgpu_top') ${LATEST_VERSION}"
  
  msg_info "$(translate 'Installing amdgpu_top...')"
  
  if ! dpkg -i "$deb_file" >>"$LOG_FILE" 2>&1; then
    # Try to fix dependencies if dpkg failed
    apt-get install -f -y >>"$LOG_FILE" 2>&1
    if ! dpkg -i "$deb_file" >>"$LOG_FILE" 2>&1; then
      msg_error "$(translate 'Failed to install amdgpu_top')"
      rm -rf "$tmp_dir"
      return 1
    fi
  fi
  
  msg_ok "$(translate 'amdgpu_top installed successfully')"
  
  # Clean up
  rm -rf "$tmp_dir"
  
  # Update component status
  if type update_component_status &>/dev/null; then
    update_component_status "amdgpu_top" "installed" "$LATEST_VERSION" "gpu" '{"source":"github"}'
  fi
  
  return 0
}

# ==========================================================
# Uninstall amdgpu_top
# ==========================================================
uninstall_amdgpu_top() {
  msg_info "$(translate 'Uninstalling amdgpu_top...')"
  
  if dpkg -r amdgpu-top >>"$LOG_FILE" 2>&1 || apt-get remove -y amdgpu-top >>"$LOG_FILE" 2>&1; then
    msg_ok "$(translate 'amdgpu_top uninstalled successfully')"
    
    if type update_component_status &>/dev/null; then
      update_component_status "amdgpu_top" "uninstalled" "" "gpu" '{}'
    fi
    return 0
  else
    msg_error "$(translate 'Failed to uninstall amdgpu_top')"
    return 1
  fi
}

# ==========================================================
# Main execution
# ==========================================================
main() {
  # Show ProxMenux logo and title
  show_proxmenux_logo
  msg_title "$(translate "$SCRIPT_TITLE")"
  
  # Detect AMD GPUs
  detect_amd_gpus
  
  if ! $AMD_GPU_PRESENT; then
    msg_warn "$(translate 'No AMD GPU detected on this system.')"
    msg_info2 "$(translate 'This tool is designed for systems with AMD GPUs.')"
    msg_info2 "$(translate 'You can still install amdgpu_top if needed.')"
    echo ""
  else
    msg_ok "$(translate 'AMD GPU(s) detected:')"
    echo -e "$DETECTED_GPUS_TEXT"
  fi
  
  # Check if already installed
  check_amdgpu_top_installed
  
  if $AMDGPU_TOP_INSTALLED; then
    msg_ok "$(translate 'amdgpu_top is already installed:') $AMDGPU_TOP_VERSION"
    
    # Check for updates
    if get_latest_release; then
      if [[ "$AMDGPU_TOP_VERSION" != *"$LATEST_VERSION"* ]]; then
        msg_info2 "$(translate 'A newer version is available:') $LATEST_VERSION"
        msg_info "$(translate 'Updating amdgpu_top...')"
        
        if install_dependencies && install_amdgpu_top; then
          msg_ok "$(translate 'amdgpu_top updated to') $LATEST_VERSION"
        else
          msg_error "$(translate 'Failed to update amdgpu_top')"
          exit 1
        fi
      else
        msg_ok "$(translate 'amdgpu_top is up to date')"
      fi
    fi
  else
    msg_info2 "$(translate 'amdgpu_top is not installed')"
    msg_info "$(translate 'Starting installation...')"
    
    # Get latest release info
    if ! get_latest_release; then
      msg_error "$(translate 'Failed to get release information from GitHub')"
      exit 1
    fi
    
    msg_ok "$(translate 'Latest version:') $LATEST_VERSION"
    
    # Install dependencies
    if ! install_dependencies; then
      msg_error "$(translate 'Failed to install dependencies')"
      exit 1
    fi
    
    # Install amdgpu_top
    if ! install_amdgpu_top; then
      msg_error "$(translate 'Installation failed')"
      exit 1
    fi
  fi
  
  echo ""
  msg_ok "$(translate 'AMD GPU Tools installation completed!')"
  echo ""
  msg_info2 "$(translate 'You can now monitor your AMD GPU using:')"
  echo "    amdgpu_top           - $(translate 'TUI mode')"
  echo "    amdgpu_top --json    - $(translate 'JSON output for scripts')"
  echo "    amdgpu_top --gui     - $(translate 'GUI mode (if available)')"
  echo ""
  
  # In web mode, don't wait for user input
  if ! is_web_mode 2>/dev/null; then
    msg_success "$(translate 'Installation completed. Press Enter to continue...')"
    read -r
  else
    msg_success "$(translate 'Installation completed.')"
  fi
}

# Run main function
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi