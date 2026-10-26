#!/usr/bin/env bash

# ==========================================================
# Guest Agent Configurator - ProxMenux
# ==========================================================
# Adds QEMU Guest Agent support and the useful devices, per guest OS.
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache



function configure_guest_agent() {
  if [[ -z "$VMID" ]]; then
    msg_error "$(translate "No VMID defined. Cannot apply guest agent config.")"
    return 1
  fi

  msg_info "$(translate "Adding QEMU Guest Agent support...")"

  # Enable the agent on the VM
  qm set "$VMID" -agent enabled=1 >/dev/null 2>&1

  # Añadir canal de comunicación virtio
  qm set "$VMID" -chardev socket,id=qga0,path=/var/run/qemu-server/$VMID.qga,server=on,wait=off >/dev/null 2>&1
  qm set "$VMID" -device virtio-serial-pci -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0 >/dev/null 2>&1

  msg_ok "$(translate "Guest Agent configuration applied")"

  if [[ "$OS_TYPE" == "windows" ]]; then
    echo -e "${YW}$(translate "Reminder: You must install the QEMU Guest Agent inside the Windows VM")${NC}"
    echo -e "${YW}$(translate "Tip: Also mount the VirtIO ISO for drivers and guest agent installer")${NC}"
    echo -e "${TAB}- https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/"
  elif [[ "$OS_TYPE" == "linux" || "$OS_TYPE" == "lite" ]]; then
    echo -e "${YW}$(translate "Tip: You can install the QEMU Guest Agent inside the VM with:")${NC}"
    echo -e "${TAB}apt install qemu-guest-agent -y && systemctl enable --now qemu-guest-agent"
  fi
}

