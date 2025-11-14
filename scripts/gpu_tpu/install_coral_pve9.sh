#!/bin/bash
# ProxMenux - Coral TPU Installer (PVE 9.x)
# =========================================
# Author      : MacRimi
# License     : MIT
# Version     : 1.3 (PVE9, silent build)
# Last Updated: 25/09/2025
# =========================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
LOG_FILE="/tmp/coral_install.log"

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi


load_language
initialize_cache




ensure_apex_group_and_udev() {
  msg_info "Ensuring apex group and udev rules..."


  if ! getent group apex >/dev/null; then
    groupadd --system apex || true
    msg_ok "System group 'apex' created"
  else
    msg_ok "System group 'apex' already exists"
  fi


  cat >/etc/udev/rules.d/99-coral-apex.rules <<'EOF'
# Coral / Google APEX TPU (M.2 / PCIe)
# Assign group "apex" and safe permissions to device nodes
KERNEL=="apex_*", GROUP="apex", MODE="0660"
SUBSYSTEM=="apex", GROUP="apex", MODE="0660"
EOF


  if [[ -f /usr/lib/udev/rules.d/60-gasket-dkms.rules ]]; then
    sed -i 's/GROUP="[^"]*"/GROUP="apex"/g' /usr/lib/udev/rules.d/60-gasket-dkms.rules || true
  fi


  udevadm control --reload-rules
  udevadm trigger --subsystem-match=apex || true

  msg_ok "apex group and udev rules are in place"


  if ls -l /dev/apex_* 2>/dev/null | grep -q ' apex '; then
    msg_ok "Coral TPU device nodes detected with correct group (apex)"
  else
    msg_warn "apex device node not found yet; a reboot may be required"
  fi
}




pre_install_prompt() {
  if ! dialog --title "$(translate 'Coral TPU Installation')" --yesno \
    "\n$(translate 'Installing Coral TPU drivers requires rebooting the server after installation. Do you want to proceed?')" 10 70; then

    exit 0
  fi
}

install_coral_host() {
  show_proxmenux_logo
  : >"$LOG_FILE"  



  msg_info "$(translate 'Installing build dependencies...')"
  apt-get update -qq >>"$LOG_FILE" 2>&1
  apt-get install -y git devscripts dh-dkms dkms proxmox-headers-$(uname -r) >>"$LOG_FILE" 2>&1
  if [[ $? -ne 0 ]]; then msg_error "$(translate 'Error installing build dependencies. Check /tmp/coral_install.log')"; exit 1; fi
  msg_ok   "$(translate 'Build dependencies installed.')"



  cd /tmp || exit 1
  rm -rf gasket-driver >>"$LOG_FILE" 2>&1
  msg_info "$(translate 'Cloning Google Coral driver repository...')"
  git clone https://github.com/google/gasket-driver.git >>"$LOG_FILE" 2>&1
  if [[ $? -ne 0 ]]; then msg_error "$(translate 'Could not clone the repository. Check /tmp/coral_install.log')"; exit 1; fi
  msg_ok   "$(translate 'Repository cloned successfully.')"



  cd /tmp/gasket-driver || exit 1
  msg_info "$(translate 'Patching source for kernel compatibility...')"


  sed -i 's/\.llseek = no_llseek/\.llseek = noop_llseek/' src/gasket_core.c

  sed -i 's/^MODULE_IMPORT_NS(DMA_BUF);/MODULE_IMPORT_NS("DMA_BUF");/' src/gasket_page_table.c

  sed -i "s/\(linux-headers-686-pae | linux-headers-amd64 | linux-headers-generic | linux-headers\)/\1 | proxmox-headers-$(uname -r) | pve-headers-$(uname -r)/" debian/control
  if [[ $? -ne 0 ]]; then msg_error "$(translate 'Patching failed. Check /tmp/coral_install.log')"; exit 1; fi
  msg_ok   "$(translate 'Source patched successfully.')"



  msg_info "$(translate 'Building DKMS package...')"
  debuild -us -uc -tc -b >>"$LOG_FILE" 2>&1
  if [[ $? -ne 0 ]]; then msg_error "$(translate 'Failed to build DKMS package. Check /tmp/coral_install.log')"; exit 1; fi
  msg_ok   "$(translate 'DKMS package built successfully.')"



  msg_info "$(translate 'Installing DKMS package...')"
  dpkg -i ../gasket-dkms_*.deb >>"$LOG_FILE" 2>&1 || true
  if ! dpkg -s gasket-dkms >/dev/null 2>&1; then
    msg_error "$(translate 'Failed to install DKMS package. Check /tmp/coral_install.log')"; exit 1
  fi
  msg_ok   "$(translate 'DKMS package installed.')"



  msg_info "$(translate 'Compiling Coral TPU drivers for current kernel...')"
  dkms remove -m gasket -v 1.0 -k "$(uname -r)" >>"$LOG_FILE" 2>&1 || true
  dkms add    -m gasket -v 1.0            >>"$LOG_FILE" 2>&1 || true
  dkms build  -m gasket -v 1.0 -k "$(uname -r)" >>"$LOG_FILE" 2>&1
  if [[ $? -ne 0 ]]; then
    sed -n '1,200p' /var/lib/dkms/gasket/1.0/build/make.log >>"$LOG_FILE" 2>&1 || true
    msg_error "$(translate 'DKMS build failed. Check /tmp/coral_install.log')"; exit 1
  fi
  dkms install -m gasket -v 1.0 -k "$(uname -r)" >>"$LOG_FILE" 2>&1
  if [[ $? -ne 0 ]]; then msg_error "$(translate 'DKMS install failed. Check /tmp/coral_install.log')"; exit 1; fi
  msg_ok   "$(translate 'Drivers compiled and installed via DKMS.')"


  ensure_apex_group_and_udev

  msg_info "$(translate 'Loading modules...')"
  modprobe gasket >>"$LOG_FILE" 2>&1 || true
  modprobe apex   >>"$LOG_FILE" 2>&1 || true
  if lsmod | grep -q '\bapex\b'; then
    msg_ok "$(translate 'Modules loaded.')"
    msg_success "$(translate 'Coral TPU drivers installed and loaded successfully.')"
  else
    msg_warn "$(translate 'Installation finished but drivers are not loaded. Please check dmesg and /tmp/coral_install.log')"
  fi



  echo "---- dmesg | grep -i apex (last lines) ----" >>"$LOG_FILE"
  dmesg | grep -i apex | tail -n 20 >>"$LOG_FILE" 2>&1
}

restart_prompt() {
  if whiptail --title "$(translate 'Coral TPU Installation')" --yesno \
    "$(translate 'The installation requires a server restart to apply changes. Do you want to restart now?')" 10 70; then
    msg_warn "$(translate 'Restarting the server...')"
    reboot
  else
    msg_success "$(translate 'Completed. Press Enter to return to menu...')"
    read -r
  fi
}


pre_install_prompt
install_coral_host
restart_prompt
