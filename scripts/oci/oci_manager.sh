#!/bin/bash
# ProxMenux - OCI Application Manager
# ============================================
# Author      : MacRimi
# License     : GPL-3.0
# Version     : 1.0
# ============================================
# Manages OCI container applications through dialog menus or direct CLI.
# This script wraps the Python oci_manager.py for terminal usage.

SCRIPT_TITLE="OCI Application Manager"

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
OCI_MANAGER="$LOCAL_SCRIPTS/oci_manager.py"

# OCI paths - persistent data in proxmenux directory
OCI_DIR="$BASE_DIR/oci"
OCI_CATALOG="$OCI_DIR/catalog.json"
OCI_INSTALLED="$OCI_DIR/installed.json"
OCI_INSTANCES="$OCI_DIR/instances"

# Source catalog bundled with Scripts
SCRIPTS_CATALOG="$LOCAL_SCRIPTS/oci/catalog.json"

export BASE_DIR

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

load_language 2>/dev/null || true
initialize_cache 2>/dev/null || true


# ==========================================================
# OCI Directory Initialization
# ==========================================================
ensure_oci_directories() {
  # Create OCI directories if they don't exist
  mkdir -p "$OCI_DIR"
  mkdir -p "$OCI_INSTANCES"
  
  # Copy catalog from Scripts if not present
  if [[ ! -f "$OCI_CATALOG" && -f "$SCRIPTS_CATALOG" ]]; then
    cp "$SCRIPTS_CATALOG" "$OCI_CATALOG"
    msg_ok "Initialized OCI catalog"
  fi
  
  # Create empty installed.json if not present
  if [[ ! -f "$OCI_INSTALLED" ]]; then
    echo '{"version": "1.0.0", "instances": {}}' > "$OCI_INSTALLED"
  fi
}


# ==========================================================
# Proxmox OCI Support Detection
# ==========================================================
check_proxmox_oci_support() {
  PVE_VERSION=""
  OCI_SUPPORTED=false
  
  # Get Proxmox VE version
  if command -v pveversion >/dev/null 2>&1; then
    PVE_VERSION=$(pveversion | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1)
    
    # Check if version >= 9.1
    local major minor
    major=$(echo "$PVE_VERSION" | cut -d. -f1)
    minor=$(echo "$PVE_VERSION" | cut -d. -f2)
    
    if [[ $major -gt 9 ]] || [[ $major -eq 9 && $minor -ge 1 ]]; then
      OCI_SUPPORTED=true
    fi
  fi
}

check_oci_support() {
  check_proxmox_oci_support
  
  if [[ "$OCI_SUPPORTED" != "true" ]]; then
    msg_error "$(translate "OCI containers require Proxmox VE 9.1 or later.")"
    msg_info2 "$(translate "Current version: $PVE_VERSION")"
    return 1
  fi
  return 0
}


# ==========================================================
# Helper Functions
# ==========================================================
run_oci_manager() {
  python3 "$OCI_MANAGER" "$@"
}

get_app_status() {
  local app_id="$1"
  run_oci_manager status --app-id "$app_id" 2>/dev/null | jq -r '.state // "not_installed"'
}

is_installed() {
  local app_id="$1"
  local status=$(get_app_status "$app_id")
  [[ "$status" != "not_installed" ]]
}


# ==========================================================
# Secure Gateway Functions
# ==========================================================
deploy_secure_gateway() {
  show_proxmenux_logo
  msg_title "$(translate "Secure Gateway (Tailscale VPN)")"
  
  if ! check_oci_support; then
    return 1
  fi
  
  # Check if already installed
  if is_installed "secure-gateway"; then
    local status=$(get_app_status "secure-gateway")
    msg_warn "$(translate "Secure Gateway is already installed.")"
    msg_info2 "Status: $status"
    echo ""
    read -p "$(translate "Press Enter to continue...")" _
    return 0
  fi
  
  msg_info2 "$(translate "This will deploy a Tailscale VPN gateway for secure remote access.")"
  msg_info2 "$(translate "You will need a Tailscale auth key from: https://login.tailscale.com/admin/settings/keys")"
  echo ""
  
  # Get auth key
  local auth_key
  while true; do
    read -p "$(translate "Enter Tailscale Auth Key"): " auth_key
    if [[ -z "$auth_key" ]]; then
      msg_error "$(translate "Auth key is required.")"
      continue
    fi
    if [[ ! "$auth_key" =~ ^tskey- ]]; then
      msg_warn "$(translate "Warning: Auth key should start with 'tskey-'")"
    fi
    break
  done
  
  # Get hostname
  local default_hostname="${HOSTNAME:-proxmox}-gateway"
  read -p "$(translate "Device hostname") [$default_hostname]: " hostname
  hostname="${hostname:-$default_hostname}"
  
  # Access mode
  echo ""
  msg_info2 "$(translate "Access Scope:")"
  echo "  1) Host Only - ProxMenux Monitor & Proxmox UI only"
  echo "  2) Proxmox Network - Include VMs, LXCs, and host services"
  echo "  3) Custom - Select specific networks"
  echo ""
  
  local access_mode="host_only"
  local routes=""
  
  read -p "$(translate "Select access mode") [1]: " mode_choice
  case "$mode_choice" in
    2)
      access_mode="proxmox_network"
      # Auto-detect networks
      routes=$(detect_networks_for_routing)
      ;;
    3)
      access_mode="custom"
      msg_info2 "$(translate "Enter networks to advertise (comma-separated CIDR):")"
      msg_info2 "  Example: 10.0.1.0/24,192.168.1.0/24"
      read -p "Networks: " routes
      ;;
    *)
      access_mode="host_only"
      ;;
  esac
  
  # Exit node option
  local exit_node="false"
  read -p "$(translate "Offer as exit node?") [y/N]: " exit_choice
  [[ "$exit_choice" =~ ^[Yy] ]] && exit_node="true"
  
  # Accept routes option
  local accept_routes="false"
  read -p "$(translate "Accept routes from other nodes?") [y/N]: " accept_choice
  [[ "$accept_choice" =~ ^[Yy] ]] && accept_routes="true"
  
  echo ""
  msg_info2 "$(translate "Configuration Summary:")"
  echo "  Hostname: $hostname"
  echo "  Access Mode: $access_mode"
  [[ -n "$routes" ]] && echo "  Networks: $routes"
  echo "  Exit Node: $exit_node"
  echo "  Accept Routes: $accept_routes"
  echo ""
  
  read -p "$(translate "Deploy with this configuration?") [Y/n]: " confirm
  if [[ "$confirm" =~ ^[Nn] ]]; then
    msg_warn "$(translate "Deployment cancelled.")"
    return 0
  fi
  
  # Build config JSON
  local routes_array="[]"
  if [[ -n "$routes" ]]; then
    # Convert comma-separated to JSON array
    routes_array=$(echo "$routes" | tr ',' '\n' | jq -R . | jq -s .)
  fi
  
  local config_json=$(cat <<EOF
{
  "auth_key": "$auth_key",
  "hostname": "$hostname",
  "access_mode": "$access_mode",
  "advertise_routes": $routes_array,
  "exit_node": $exit_node,
  "accept_routes": $accept_routes
}
EOF
)
  
  msg_info "$(translate "Deploying Secure Gateway...")"
  
  local result
  result=$(run_oci_manager deploy --app-id "secure-gateway" --config "$config_json" --source "cli" 2>&1)
  
  if echo "$result" | jq -e '.success == true' >/dev/null 2>&1; then
    msg_ok "$(translate "Secure Gateway deployed successfully!")"
    msg_info2 "$(translate "The gateway should appear in your Tailscale admin console shortly.")"
  else
    local error_msg=$(echo "$result" | jq -r '.message // "Unknown error"')
    msg_error "$(translate "Deployment failed"): $error_msg"
    return 1
  fi
  
  echo ""
  read -p "$(translate "Press Enter to continue...")" _
}

detect_networks_for_routing() {
  # Detect bridge interfaces and their subnets
  local networks=""
  
  for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -E '^vmbr|^bond' | head -5); do
    local subnet=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP 'inet \K[\d.]+/\d+' | head -1)
    if [[ -n "$subnet" ]]; then
      # Convert IP/prefix to network/prefix
      local network=$(python3 -c "import ipaddress; print(ipaddress.IPv4Network('$subnet', strict=False))" 2>/dev/null)
      if [[ -n "$network" ]]; then
        [[ -n "$networks" ]] && networks="$networks,"
        networks="$networks$network"
      fi
    fi
  done
  
  echo "$networks"
}

manage_secure_gateway() {
  show_proxmenux_logo
  msg_title "$(translate "Manage Secure Gateway")"
  
  local status=$(get_app_status "secure-gateway")
  
  msg_info2 "Current status: $status"
  echo ""
  
  case "$status" in
    "running")
      echo "1) Stop gateway"
      echo "2) Restart gateway"
      echo "3) View logs"
      echo "4) Remove gateway"
      echo "5) Back"
      ;;
    "stopped"|"exited")
      echo "1) Start gateway"
      echo "2) View logs"
      echo "3) Remove gateway"
      echo "4) Back"
      ;;
    *)
      msg_error "$(translate "Gateway is not installed.")"
      read -p "$(translate "Press Enter to continue...")" _
      return
      ;;
  esac
  
  echo ""
  read -p "$(translate "Select option"): " choice
  
  case "$status" in
    "running")
      case "$choice" in
        1) action_stop_gateway ;;
        2) action_restart_gateway ;;
        3) action_view_logs ;;
        4) action_remove_gateway ;;
      esac
      ;;
    "stopped"|"exited")
      case "$choice" in
        1) action_start_gateway ;;
        2) action_view_logs ;;
        3) action_remove_gateway ;;
      esac
      ;;
  esac
}

action_start_gateway() {
  msg_info "$(translate "Starting gateway...")"
  local result=$(run_oci_manager start --app-id "secure-gateway" 2>&1)
  if echo "$result" | jq -e '.success == true' >/dev/null 2>&1; then
    msg_ok "$(translate "Gateway started.")"
  else
    msg_error "$(translate "Failed to start gateway.")"
  fi
  read -p "$(translate "Press Enter to continue...")" _
}

action_stop_gateway() {
  msg_info "$(translate "Stopping gateway...")"
  local result=$(run_oci_manager stop --app-id "secure-gateway" 2>&1)
  if echo "$result" | jq -e '.success == true' >/dev/null 2>&1; then
    msg_ok "$(translate "Gateway stopped.")"
  else
    msg_error "$(translate "Failed to stop gateway.")"
  fi
  read -p "$(translate "Press Enter to continue...")" _
}

action_restart_gateway() {
  msg_info "$(translate "Restarting gateway...")"
  local result=$(run_oci_manager restart --app-id "secure-gateway" 2>&1)
  if echo "$result" | jq -e '.success == true' >/dev/null 2>&1; then
    msg_ok "$(translate "Gateway restarted.")"
  else
    msg_error "$(translate "Failed to restart gateway.")"
  fi
  read -p "$(translate "Press Enter to continue...")" _
}

action_view_logs() {
  echo ""
  msg_info2 "$(translate "Recent logs:")"
  echo "----------------------------------------"
  $RUNTIME logs --tail 50 proxmenux-secure-gateway 2>/dev/null || echo "No logs available"
  echo "----------------------------------------"
  echo ""
  read -p "$(translate "Press Enter to continue...")" _
}

action_remove_gateway() {
  echo ""
  read -p "$(translate "Remove Secure Gateway? State will be preserved.") [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy] ]]; then
    return
  fi
  
  msg_info "$(translate "Removing gateway...")"
  local result=$(run_oci_manager remove --app-id "secure-gateway" 2>&1)
  if echo "$result" | jq -e '.success == true' >/dev/null 2>&1; then
    msg_ok "$(translate "Gateway removed.")"
  else
    msg_error "$(translate "Failed to remove gateway.")"
  fi
  read -p "$(translate "Press Enter to continue...")" _
}


# ==========================================================
# Main Menu
# ==========================================================
show_oci_menu() {
  while true; do
    show_proxmenux_logo
    msg_title "$(translate "$SCRIPT_TITLE")"
    
    detect_runtime
    
    if [[ -z "$RUNTIME" ]]; then
      msg_warn "$(translate "No container runtime available.")"
      msg_info2 "$(translate "Install podman or docker to continue.")"
      echo ""
      read -p "$(translate "Press Enter to exit...")" _
      return
    fi
    
    msg_info2 "Runtime: $RUNTIME $RUNTIME_VERSION"
    echo ""
    
    # Check gateway status
    local gw_status=$(get_app_status "secure-gateway")
    local gw_label="Secure Gateway (Tailscale VPN)"
    if [[ "$gw_status" != "not_installed" ]]; then
      gw_label="$gw_label [$gw_status]"
    fi
    
    echo "1) $gw_label"
    echo ""
    echo "0) $(translate "Exit")"
    echo ""
    
    read -p "$(translate "Select option"): " choice
    
    case "$choice" in
      1)
        if [[ "$gw_status" == "not_installed" ]]; then
          deploy_secure_gateway
        else
          manage_secure_gateway
        fi
        ;;
      0|q|Q)
        break
        ;;
      *)
        msg_error "$(translate "Invalid option")"
        sleep 1
        ;;
    esac
  done
}


# ==========================================================
# CLI Mode
# ==========================================================
cli_mode() {
  local command="$1"
  shift
  
  case "$command" in
    deploy)
      local app_id=""
      local config=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --app-id) app_id="$2"; shift 2 ;;
          --config) config="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
      
      if [[ -z "$app_id" ]]; then
        echo "Error: --app-id required"
        exit 1
      fi
      
      run_oci_manager deploy --app-id "$app_id" --config "${config:-{}}" --source "cli"
      ;;
    start|stop|restart|remove|status)
      local app_id=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --app-id) app_id="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
      
      if [[ -z "$app_id" ]]; then
        echo "Error: --app-id required"
        exit 1
      fi
      
      run_oci_manager "$command" --app-id "$app_id"
      ;;
    list)
      run_oci_manager list
      ;;
    catalog)
      run_oci_manager catalog
      ;;
    networks)
      run_oci_manager networks
      ;;
    runtime)
      run_oci_manager runtime
      ;;
    *)
      echo "Usage: $0 [command] [options]"
      echo ""
      echo "Commands:"
      echo "  (no args)     Interactive menu"
      echo "  deploy        Deploy an app (--app-id, --config)"
      echo "  start         Start an app (--app-id)"
      echo "  stop          Stop an app (--app-id)"
      echo "  restart       Restart an app (--app-id)"
      echo "  remove        Remove an app (--app-id)"
      echo "  status        Get app status (--app-id)"
      echo "  list          List installed apps"
      echo "  catalog       List available apps"
      echo "  networks      Detect available networks"
      echo "  runtime       Show container runtime info"
      exit 1
      ;;
  esac
}


# ==========================================================
# Entry Point
# ==========================================================
main() {
  # Initialize OCI directories and catalog
  ensure_oci_directories
  
  if [[ $# -gt 0 ]]; then
    cli_mode "$@"
  else
    show_oci_menu
  fi
}

main "$@"
