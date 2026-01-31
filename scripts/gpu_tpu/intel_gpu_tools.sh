#!/bin/bash
# ProxMenux - Intel GPU Tools Installer
# ============================================
# Author      : MacRimi
# License     : MIT
# Version     : 1.0
# Last Updated: 29/01/2026
# ============================================
# Installs intel-gpu-tools for monitoring Intel GPUs

SCRIPT_TITLE="Intel GPU Tools Installer for Proxmox VE"

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
COMMON_FUNC="$LOCAL_SCRIPTS/global/share_common.func"
COMPONENTS_STATUS_FILE="$BASE_DIR/components_status.json"
LOG_FILE="/tmp/intel_gpu_tools_install.log"

export BASE_DIR
export COMPONENTS_STATUS_FILE

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

if [[ -f "$COMMON_FUNC" ]]; then
  source "$COMMON_FUNC"
fi

if [[ ! -f "$COMPONENTS_STATUS_FILE" ]]; then
  echo "{}" > "$COMPONENTS_STATUS_FILE"
fi

load_language 2>/dev/null || true
initialize_cache 2>/dev/null || true

# ==========================================================
# Intel GPU detection
# ==========================================================
detect_intel_gpus() {
  local lspci_output
  lspci_output=$(lspci | grep -iE "Intel.*VGA|Intel.*Display|Intel.*Graphics" || true)

  if [[ -z "$lspci_output" ]]; then
    INTEL_GPU_PRESENT=false
    DETECTED_GPUS_TEXT="No Intel GPU detected on this system."
  else
    INTEL_GPU_PRESENT=true
    DETECTED_GPUS_TEXT=""
    local i=1
    while IFS= read -r line; do
      DETECTED_GPUS_TEXT+="  ${i}. ${line}\n"
      ((i++))
    done <<< "$lspci_output"
  fi
}

# ==========================================================
# Check if intel-gpu-tools is installed
# ==========================================================
check_intel_gpu_tools_installed() {
  if command -v intel_gpu_top >/dev/null 2>&1; then
    INTEL_GPU_TOOLS_INSTALLED=true
    INTEL_GPU_TOOLS_VERSION=$(dpkg -s intel-gpu-tools 2>/dev/null | grep '^Version:' | awk '{print $2}' || echo "unknown")
  else
    INTEL_GPU_TOOLS_INSTALLED=false
    INTEL_GPU_TOOLS_VERSION=""
  fi
}

# ==========================================================
# Install intel-gpu-tools
# ==========================================================
install_intel_gpu_tools() {
  msg_info "$(translate 'Installing intel-gpu-tools...')"
  
  if apt-get install -y intel-gpu-tools >>"$LOG_FILE" 2>&1; then
    msg_ok "$(translate 'intel-gpu-tools installed successfully')"
    
    # Get installed version
    INTEL_GPU_TOOLS_VERSION=$(dpkg -s intel-gpu-tools 2>/dev/null | grep '^Version:' | awk '{print $2}' || echo "unknown")
    
    # Update component status
    if type update_component_status &>/dev/null; then
      update_component_status "intel_gpu_tools" "installed" "$INTEL_GPU_TOOLS_VERSION" "gpu" '{"source":"apt"}'
    fi
    
    return 0
  else
    msg_error "$(translate 'Failed to install intel-gpu-tools')"
    return 1
  fi
}

# ==========================================================
# Uninstall intel-gpu-tools
# ==========================================================
uninstall_intel_gpu_tools() {
  msg_info "$(translate 'Uninstalling intel-gpu-tools...')"
  
  if apt-get remove -y intel-gpu-tools >>"$LOG_FILE" 2>&1; then
    msg_ok "$(translate 'intel-gpu-tools uninstalled successfully')"
    
    if type update_component_status &>/dev/null; then
      update_component_status "intel_gpu_tools" "uninstalled" "" "gpu" '{}'
    fi
    return 0
  else
    msg_error "$(translate 'Failed to uninstall intel-gpu-tools')"
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
  
  # Detect Intel GPUs
  detect_intel_gpus
  
  if ! $INTEL_GPU_PRESENT; then
    msg_warn "$(translate 'No Intel GPU detected on this system.')"
    msg_info2 "$(translate 'This tool is designed for systems with Intel GPUs.')"
    msg_info2 "$(translate 'You can still install intel-gpu-tools if needed.')"
    echo ""
  else
    msg_ok "$(translate 'Intel GPU(s) detected:')"
    echo -e "$DETECTED_GPUS_TEXT"
  fi
  
  # Check if already installed
  check_intel_gpu_tools_installed
  
  if $INTEL_GPU_TOOLS_INSTALLED; then
    msg_ok "$(translate 'intel-gpu-tools is already installed:') $INTEL_GPU_TOOLS_VERSION"
    
    # Check for updates
    msg_info "$(translate 'Checking for updates...')"
    apt-get update -qq >>"$LOG_FILE" 2>&1
    
    local available_version
    available_version=$(apt-cache policy intel-gpu-tools 2>/dev/null | grep 'Candidate:' | awk '{print $2}')
    
    if [[ -n "$available_version" && "$available_version" != "$INTEL_GPU_TOOLS_VERSION" ]]; then
      msg_ok "$(translate 'A newer version is available:') $available_version"
      
      if apt-get install -y intel-gpu-tools >>"$LOG_FILE" 2>&1; then
        INTEL_GPU_TOOLS_VERSION="$available_version"
        msg_ok "$(translate 'intel-gpu-tools updated to') $INTEL_GPU_TOOLS_VERSION"
        
        if type update_component_status &>/dev/null; then
          update_component_status "intel_gpu_tools" "installed" "$INTEL_GPU_TOOLS_VERSION" "gpu" '{"source":"apt"}'
        fi
      else
        msg_error "$(translate 'Failed to update intel-gpu-tools')"
      fi
    else
      msg_ok "$(translate 'intel-gpu-tools is up to date')"
    fi
  else
    
    # Ensure repositories are configured
    if type ensure_repositories &>/dev/null; then
      ensure_repositories
    fi
    
    # Install intel-gpu-tools
    if ! install_intel_gpu_tools; then
      msg_error "$(translate 'Installation failed')"
      exit 1
    fi
  fi
  
  echo ""
  msg_ok "$(translate 'Intel GPU Tools installation completed!')"
  echo ""
  msg_info2 "$(translate 'You can now monitor your Intel GPU using:')"
  echo "    intel_gpu_top        - $(translate 'TUI mode (requires root)')"
  echo "    intel_gpu_frequency  - $(translate 'Show GPU frequency')"
  echo "    intel_gpu_time       - $(translate 'Show GPU time')"
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