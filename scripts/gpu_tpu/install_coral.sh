#!/bin/bash
# ==========================================================
# ProxMenux - Coral TPU Installer (unified: PCIe/M.2 + USB)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 2.0
# Last Updated: 17/04/2026
# ==========================================================
# Description:
# Single entry point for every Coral variant. At startup the
# script detects what Coral hardware is present on the host
# and installs only what is actually needed.
#
# Features:
#  - Auto-detection of M.2 / Mini-PCIe (vendor 1ac1) and
#    USB (1a6e:089a / 18d1:9302) Accelerators in one pass
#  - PCIe path: builds gasket + apex kernel modules via DKMS
#    using feranick/gasket-driver fork (actively maintained),
#    google/gasket-driver as fallback with kernel patches
#  - Kernel-aware patches applied only when needed
#    (no_llseek → noop_llseek on 6.5+, MODULE_IMPORT_NS
#    string form on 6.13+)
#  - apex system group + udev rules for /dev/apex_* nodes
#  - USB path: Google Coral APT repo (signed-by keyring) +
#    libedgetpu1-std runtime (udev rules ship with package)
#  - Both variants present → both paths run in sequence
#  - Idempotent: reruns skip work already done, recovers
#    from broken gasket-dkms state after PVE 9 kernel upgrades
#  - Reboot prompted only when the PCIe path ran
# ==========================================================

# Guarantee a valid working directory before anything else. When the user
# re-runs the installer from a previous /tmp/gasket-driver/... path that our
# own `rm -rf gasket-driver` removed, the inherited cwd is orphaned and bash
# emits `chdir: error retrieving current directory` warnings from every
# subprocess. Moving to / at launch makes the rest of the script immune to
# that state.
cd / 2>/dev/null || true

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
LOG_FILE="/tmp/coral_install.log"

# Hardware detection results, set by detect_coral_hardware().
CORAL_PCIE_COUNT=0
CORAL_USB_COUNT=0

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

load_language
initialize_cache


# ============================================================
# Hardware detection
# ============================================================
detect_coral_hardware() {
  CORAL_PCIE_COUNT=0
  CORAL_USB_COUNT=0

  # PCIe / M.2 / Mini-PCIe — vendor 0x1ac1 (Global Unichip Corp.)
  if [[ -d /sys/bus/pci/devices ]]; then
    for dev in /sys/bus/pci/devices/*; do
      [[ -e "$dev/vendor" ]] || continue
      local vendor
      vendor=$(cat "$dev/vendor" 2>/dev/null)
      if [[ "$vendor" == "0x1ac1" ]]; then
        CORAL_PCIE_COUNT=$((CORAL_PCIE_COUNT + 1))
      fi
    done
  fi

  # USB Accelerator
  #   1a6e:089a  Global Unichip Corp. (unprogrammed state — before runtime loads fw)
  #   18d1:9302  Google Inc.          (programmed state   — after runtime talks to it)
  if command -v lsusb >/dev/null 2>&1; then
    CORAL_USB_COUNT=$(lsusb 2>/dev/null \
      | grep -cE 'ID (1a6e:089a|18d1:9302)' || true)
  fi
}


# ============================================================
# Dialogs
# ============================================================
no_hardware_dialog() {
  dialog --backtitle "ProxMenux" \
    --title "$(translate 'No Coral Detected')" \
    --msgbox "\n$(translate 'No Coral TPU device was found on this host (neither PCIe/M.2 nor USB).')\n\n$(translate 'Connect a Coral Accelerator and try again.')" \
    12 72
}

pre_install_prompt() {
  local msg="\n"
  msg+="$(translate 'Detected Coral hardware:')\n\n"
  msg+="  • $(translate 'M.2 / PCIe devices:') ${CORAL_PCIE_COUNT}\n"
  msg+="  • $(translate 'USB Accelerators:')   ${CORAL_USB_COUNT}\n\n"

  msg+="$(translate 'This installer will:')\n"
  if [[ "$CORAL_PCIE_COUNT" -gt 0 ]]; then
    msg+="  • $(translate 'Build and install the gasket and apex kernel modules (DKMS)')\n"
    msg+="  • $(translate 'Set up the apex group and udev rules')\n"
  fi
  if [[ "$CORAL_USB_COUNT" -gt 0 ]]; then
    msg+="  • $(translate 'Configure the Google Coral APT repository')\n"
    msg+="  • $(translate 'Install the Edge TPU runtime (libedgetpu1-std)')\n"
  fi

  if [[ "$CORAL_PCIE_COUNT" -gt 0 ]]; then
    msg+="\n$(translate 'A reboot is required after installation to load the new kernel modules.')"
  fi

  msg+="\n\n$(translate 'Do you want to proceed?')"

  if ! dialog --backtitle "ProxMenux" \
      --title "$(translate 'Coral TPU Installation')" \
      --yesno "$msg" 20 78; then
    exit 0
  fi
}


# ============================================================
# PCIe / M.2 branch — gasket + apex kernel modules via DKMS
# ============================================================

ensure_apex_group_and_udev() {
  msg_info "$(translate 'Ensuring apex group and udev rules...')"

  if ! getent group apex >/dev/null; then
    groupadd --system apex || true
    msg_ok "$(translate 'System group apex created.')"
  else
    msg_ok "$(translate 'System group apex already exists.')"
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

  msg_ok "$(translate 'apex group and udev rules are in place.')"

  if ls -l /dev/apex_* 2>/dev/null | grep -q ' apex '; then
    msg_ok "$(translate 'Coral TPU device nodes detected with correct group (apex).')"
  else
    msg_warn "$(translate 'apex device node not found yet; a reboot may be required.')"
  fi
}

cleanup_broken_gasket_dkms() {
  # Recover from a broken gasket-dkms .deb state (half-configured, unpacked,
  # half-installed). This is a common failure mode on PVE 9 kernel upgrades:
  # dkms autoinstall tries to rebuild against the new kernel, fails, and
  # leaves dpkg stuck — which in turn blocks every subsequent apt-get call.
  local pkg_state
  pkg_state=$(dpkg -l gasket-dkms 2>/dev/null | awk '/^[a-zA-Z][a-zA-Z]/ {print $1}' | tail -1)

  [[ -z "$pkg_state" ]] && return 0  # package not present — nothing to clean

  case "$pkg_state" in
    ii|rc)
      msg_info "$(translate 'Removing any pre-existing gasket-dkms package...')"
      dpkg -r gasket-dkms >>"$LOG_FILE" 2>&1 || true
      dkms remove gasket/1.0 --all >>"$LOG_FILE" 2>&1 || true
      msg_ok "$(translate 'Pre-existing gasket-dkms package removed.')"
      ;;
    *)
      msg_warn "$(translate 'Detected broken gasket-dkms package state:') ${pkg_state}. $(translate 'Forcing removal...')"
      dpkg --remove --force-remove-reinstreq gasket-dkms >>"$LOG_FILE" 2>&1 || true
      dpkg --purge --force-all gasket-dkms >>"$LOG_FILE" 2>&1 || true
      dkms remove gasket/1.0 --all >>"$LOG_FILE" 2>&1 || true
      apt-get install -f -y >>"$LOG_FILE" 2>&1 || true
      msg_ok "$(translate 'Broken gasket-dkms package state recovered.')"
      ;;
  esac
}

clone_gasket_sources() {
  # Primary:  feranick/gasket-driver  — community fork, actively maintained,
  #                                     carries patches for kernel 6.10/6.12/6.13.
  # Fallback: google/gasket-driver    — upstream, stale. Requires manual patches.
  # Sets GASKET_SOURCE_USED so the patch step knows whether to apply them.
  local FERANICK_URL="https://github.com/feranick/gasket-driver.git"
  local GOOGLE_URL="https://github.com/google/gasket-driver.git"

  cd /tmp || exit 1
  rm -rf gasket-driver >>"$LOG_FILE" 2>&1

  msg_info "$(translate 'Cloning Coral driver repository (feranick fork)...')"
  if git clone --depth=1 "$FERANICK_URL" gasket-driver >>"$LOG_FILE" 2>&1; then
    GASKET_SOURCE_USED="feranick"
    msg_ok "$(translate 'feranick/gasket-driver cloned (actively maintained, kernel 6.12+ ready).')"
    return 0
  fi

  msg_warn "$(translate 'feranick fork unreachable. Falling back to google/gasket-driver...')"
  rm -rf gasket-driver >>"$LOG_FILE" 2>&1
  if git clone --depth=1 "$GOOGLE_URL" gasket-driver >>"$LOG_FILE" 2>&1; then
    GASKET_SOURCE_USED="google"
    msg_ok "$(translate 'google/gasket-driver cloned (fallback — will apply local patches).')"
    return 0
  fi

  msg_error "$(translate 'Could not clone any gasket-driver repository. Check your internet connection and') ${LOG_FILE}"
  exit 1
}

show_dkms_build_failure() {
  # Print the last 50 lines of make.log on-screen so the user sees the real
  # compilation error without having to dig the log file.
  local make_log="/var/lib/dkms/gasket/1.0/build/make.log"
  echo "" >&2
  msg_warn "$(translate 'DKMS build failed. Last lines of make.log:')"
  if [[ -f "$make_log" ]]; then
    {
      echo "---- /var/lib/dkms/gasket/1.0/build/make.log ----"
      cat "$make_log"
    } >>"$LOG_FILE" 2>&1
    tail -n 50 "$make_log" >&2
  else
    echo "$(translate '(make.log not found — DKMS may have failed before invoking make)')" >&2
  fi
  echo "" >&2
  echo -e "${TAB}${BL}$(translate 'Full log:')${CL} ${LOG_FILE}" >&2
  echo "" >&2
}

install_gasket_apex_dkms() {
  # Detect running kernel — used both to pull matching headers and to apply
  # kernel-version-specific patches if we fall back to google/gasket-driver.
  local KVER KMAJ KMIN
  KVER=$(uname -r)
  KMAJ=$(echo "$KVER" | cut -d. -f1)
  KMIN=$(echo "$KVER" | cut -d. -f2 | cut -d+ -f1 | cut -d- -f1)

  cleanup_broken_gasket_dkms

  msg_info "$(translate 'Installing build dependencies...')"
  apt-get update -qq >>"$LOG_FILE" 2>&1
  if ! apt-get install -y git dkms build-essential "proxmox-headers-${KVER}" >>"$LOG_FILE" 2>&1; then
    msg_error "$(translate 'Error installing build dependencies. Check') ${LOG_FILE}"
    exit 1
  fi
  msg_ok "$(translate 'Build dependencies installed.')"

  clone_gasket_sources

  cd /tmp/gasket-driver || exit 1

  # Patches are only needed for the stale google fork. feranick already carries
  # the equivalent fixes upstream; re-applying them would double-edit sources.
  if [[ "$GASKET_SOURCE_USED" == "google" ]]; then
    msg_info "$(translate 'Patching source for kernel compatibility...')"

    # no_llseek was removed in kernel 6.5 — replace with noop_llseek
    if [[ "$KMAJ" -gt 6 ]] || [[ "$KMAJ" -eq 6 && "$KMIN" -ge 5 ]]; then
      sed -i 's/\.llseek = no_llseek/\.llseek = noop_llseek/' src/gasket_core.c
    fi

    # MODULE_IMPORT_NS syntax changed to string-literal in 6.13.
    # Applying this patch on kernel <6.13 causes a compile error.
    if [[ "$KMAJ" -gt 6 ]] || [[ "$KMAJ" -eq 6 && "$KMIN" -ge 13 ]]; then
      sed -i 's/^MODULE_IMPORT_NS(DMA_BUF);/MODULE_IMPORT_NS("DMA_BUF");/' src/gasket_page_table.c
    fi

    msg_ok "$(translate 'Source patched successfully.') (kernel ${KVER})"
  else
    msg_info2 "$(translate 'Skipping manual patches — feranick fork already supports this kernel.')"
  fi

  local GASKET_SRC="/usr/src/gasket-1.0"

  if [[ ! -d /tmp/gasket-driver/src ]]; then
    msg_error "$(translate 'Expected /tmp/gasket-driver/src not found. The clone seems incomplete or uses an unknown layout.')"
    { echo "---- /tmp/gasket-driver/ contents ----"; ls -la /tmp/gasket-driver 2>/dev/null || true; } >>"$LOG_FILE"
    exit 1
  fi
  if [[ ! -f /tmp/gasket-driver/src/Makefile ]]; then
    msg_error "$(translate 'Expected Makefile not found in /tmp/gasket-driver/src. Source tree is incomplete.')"
    exit 1
  fi

  msg_info "$(translate 'Removing previous DKMS source tree...')"
  dkms remove gasket/1.0 --all >>"$LOG_FILE" 2>&1 || true
  if [[ -d "$GASKET_SRC" ]]; then
    if ! rm -rf "$GASKET_SRC" 2>>"$LOG_FILE"; then
      msg_error "$(translate 'Could not remove previous DKMS tree at') ${GASKET_SRC}. $(translate 'Check') ${LOG_FILE}"
      exit 1
    fi
  fi
  msg_ok "$(translate 'Previous DKMS tree cleared.')"

  # Copy only the `src/` contents (where the kernel sources live) so
  # Makefile + *.c + *.h sit at the DKMS tree root, matching the Debian
  # packaging layout (`dh_install src/* usr/src/gasket-$(VERSION)/`).
  msg_info "$(translate 'Copying sources to') ${GASKET_SRC}..."
  mkdir -p "$GASKET_SRC"
  if ! cp -a /tmp/gasket-driver/src/. "${GASKET_SRC}/" 2>>"$LOG_FILE"; then
    msg_error "$(translate 'Failed to copy sources into') ${GASKET_SRC}. $(translate 'Check') ${LOG_FILE}"
    exit 1
  fi
  if [[ ! -f "$GASKET_SRC/Makefile" ]]; then
    msg_error "$(translate 'Makefile missing in') ${GASKET_SRC} $(translate 'after copy; source tree is incomplete.')"
    exit 1
  fi
  msg_ok "$(translate 'Sources copied to') ${GASKET_SRC}"

  # The repo ships debian/gasket-dkms.dkms as a template with a
  # #MODULE_VERSION# placeholder that the .deb pipeline substitutes. Since we
  # install directly from sources (no .deb), we write our own dkms.conf.
  # MAKE[0] passes ${kernelver} to the Makefile so multi-kernel rebuilds
  # (PVE's autoinstall on new kernel installs) target the right headers.
  msg_info "$(translate 'Generating dkms.conf...')"
  cat > "$GASKET_SRC/dkms.conf" <<'EOF'
PACKAGE_NAME="gasket"
PACKAGE_VERSION="1.0"
BUILT_MODULE_NAME[0]="gasket"
BUILT_MODULE_NAME[1]="apex"
DEST_MODULE_LOCATION[0]="/updates/dkms"
DEST_MODULE_LOCATION[1]="/updates/dkms"
MAKE[0]="make KVERSION=${kernelver}"
CLEAN="make clean"
AUTOINSTALL="yes"
EOF
  if [[ ! -s "$GASKET_SRC/dkms.conf" ]]; then
    msg_error "$(translate 'Failed to write') ${GASKET_SRC}/dkms.conf"
    exit 1
  fi
  msg_ok "$(translate 'dkms.conf generated.')"

  msg_info "$(translate 'Registering module with DKMS...')"
  if ! dkms add "$GASKET_SRC" >>"$LOG_FILE" 2>&1; then
    msg_error "$(translate 'DKMS add failed. Check') ${LOG_FILE}"
    exit 1
  fi
  msg_ok "$(translate 'DKMS module registered.')"

  msg_info "$(translate 'Compiling Coral TPU drivers for current kernel...')"
  if ! dkms build gasket/1.0 -k "$KVER" >>"$LOG_FILE" 2>&1; then
    show_dkms_build_failure
    msg_error "$(translate 'DKMS build failed.')"
    exit 1
  fi
  if ! dkms install gasket/1.0 -k "$KVER" >>"$LOG_FILE" 2>&1; then
    show_dkms_build_failure
    msg_error "$(translate 'DKMS install failed.')"
    exit 1
  fi
  msg_ok "$(translate 'Drivers compiled and installed via DKMS.') (source: ${GASKET_SOURCE_USED})"

  ensure_apex_group_and_udev

  msg_info "$(translate 'Loading modules...')"
  modprobe gasket >>"$LOG_FILE" 2>&1 || true
  modprobe apex   >>"$LOG_FILE" 2>&1 || true
  if lsmod | grep -q '\bapex\b'; then
    msg_ok "$(translate 'Modules loaded.')"
  else
    msg_warn "$(translate 'Installation finished but drivers are not loaded. A reboot may be required.')"
  fi

  echo "---- dmesg | grep -i apex (last lines) ----" >>"$LOG_FILE"
  dmesg | grep -i apex | tail -n 20 >>"$LOG_FILE" 2>&1
}


# ============================================================
# USB branch — libedgetpu runtime from Google's APT repository
# ============================================================

install_libedgetpu_runtime() {
  local KEYRING=/etc/apt/keyrings/coral-edgetpu.gpg
  local LIST_FILE=/etc/apt/sources.list.d/coral-edgetpu.list

  # Modern repo configuration: one keyring file under /etc/apt/keyrings plus
  # a sources.list.d entry with `signed-by=`. Avoids the deprecated apt-key.
  msg_info "$(translate 'Setting up the Google Coral APT repository...')"
  mkdir -p /etc/apt/keyrings

  if [[ ! -s "$KEYRING" ]]; then
    if ! curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
        | gpg --dearmor -o "$KEYRING" 2>>"$LOG_FILE"; then
      msg_error "$(translate 'Failed to fetch the Google Coral GPG key. Check') ${LOG_FILE}"
      exit 1
    fi
    chmod 0644 "$KEYRING"
  fi

  cat > "$LIST_FILE" <<EOF
deb [signed-by=${KEYRING}] https://packages.cloud.google.com/apt coral-edgetpu-stable main
EOF

  if ! apt-get update -qq >>"$LOG_FILE" 2>&1; then
    msg_warn "$(translate 'apt-get update returned warnings. Continuing anyway; check') ${LOG_FILE}"
  fi
  msg_ok "$(translate 'Coral APT repository ready.')"

  # libedgetpu1-std = standard performance; libedgetpu1-max = overclocked mode
  # (more heat). We default to -std; users who explicitly want -max can install
  # it manually. Either way the udev rules come with the package.
  msg_info "$(translate 'Installing Edge TPU runtime (libedgetpu1-std)...')"
  if ! apt-get install -y libedgetpu1-std >>"$LOG_FILE" 2>&1; then
    msg_error "$(translate 'Failed to install libedgetpu1-std. Check') ${LOG_FILE}"
    exit 1
  fi
  msg_ok "$(translate 'Edge TPU runtime installed.')"

  # Reload udev so the rules shipped with libedgetpu1-std apply to any USB
  # Coral already plugged in (otherwise they would only apply after replug).
  udevadm control --reload-rules >/dev/null 2>&1 || true
  udevadm trigger --subsystem-match=usb >/dev/null 2>&1 || true
}


# ============================================================
# Final prompt
# ============================================================
# ============================================================
# Install-state detection (Coral PCIe gasket DKMS / USB libedgetpu)
# ============================================================
# Sets the following globals so main() can branch into install vs
# uninstall like nvidia_installer.sh does. We treat "installed" as
# loosely as possible — even a half-installed DKMS or a stale
# libedgetpu1-std package counts, because the uninstall path needs
# to clean those up too.

CORAL_PCIE_INSTALLED=false
CORAL_USB_INSTALLED=false
CORAL_PCIE_DKMS_VERSION=""
CORAL_USB_RUNTIME_VERSION=""

detect_coral_install_state() {
  CORAL_PCIE_INSTALLED=false
  CORAL_USB_INSTALLED=false
  CORAL_PCIE_DKMS_VERSION=""
  CORAL_USB_RUNTIME_VERSION=""

  # PCIe / M.2 path: any of these means gasket is installed.
  #   * `dkms status` lists a gasket entry
  #   * `dpkg -s gasket-dkms` reports installed
  #   * /dev/apex_* nodes exist (modules loaded right now)
  if command -v dkms >/dev/null 2>&1; then
    local dkms_line
    dkms_line=$(dkms status 2>/dev/null | grep -E '^gasket' | head -n1)
    if [[ -n "$dkms_line" ]]; then
      CORAL_PCIE_INSTALLED=true
      # `dkms status` formats vary across releases:
      #   "gasket, 1.0, 6.8.12-1-pve, x86_64: installed"
      #   "gasket/1.0, ..."
      CORAL_PCIE_DKMS_VERSION=$(echo "$dkms_line" \
        | sed -E 's|^gasket[, /]([^,]+).*|\1|' | tr -d ' ')
    fi
  fi
  if ! $CORAL_PCIE_INSTALLED \
     && dpkg-query -W -f='${Status}' gasket-dkms 2>/dev/null \
        | grep -q 'ok installed'; then
    CORAL_PCIE_INSTALLED=true
  fi
  if ! $CORAL_PCIE_INSTALLED && ls /dev/apex_* >/dev/null 2>&1; then
    CORAL_PCIE_INSTALLED=true
  fi

  # USB path: `libedgetpu1-std` (or the -max variant) installed.
  if dpkg-query -W -f='${Status}' libedgetpu1-std 2>/dev/null \
       | grep -q 'ok installed'; then
    CORAL_USB_INSTALLED=true
    CORAL_USB_RUNTIME_VERSION=$(dpkg-query -W -f='${Version}' \
        libedgetpu1-std 2>/dev/null)
  elif dpkg-query -W -f='${Status}' libedgetpu1-max 2>/dev/null \
         | grep -q 'ok installed'; then
    CORAL_USB_INSTALLED=true
    CORAL_USB_RUNTIME_VERSION=$(dpkg-query -W -f='${Version}' \
        libedgetpu1-max 2>/dev/null)
  fi
}


# ============================================================
# Action menu (install vs uninstall) — only shown when something
# is already installed. Mirrors nvidia_installer.sh::
# show_action_menu_if_installed so the UX is consistent across
# host driver scripts.
# ============================================================
show_coral_action_menu_if_installed() {
  if ! $CORAL_PCIE_INSTALLED && ! $CORAL_USB_INSTALLED; then
    ACTION="install"
    return 0
  fi

  local hint=""
  if $CORAL_PCIE_INSTALLED; then
    hint+="  • $(translate 'PCIe/M.2 gasket-dkms')${CORAL_PCIE_DKMS_VERSION:+ ($CORAL_PCIE_DKMS_VERSION)}\n"
  fi
  if $CORAL_USB_INSTALLED; then
    hint+="  • $(translate 'USB libedgetpu1')${CORAL_USB_RUNTIME_VERSION:+ ($CORAL_USB_RUNTIME_VERSION)}\n"
  fi

  local menu_choices=(
    "install" "$(translate 'Reinstall / update Coral drivers')"
    "remove"  "$(translate 'Uninstall Coral drivers and configuration')"
  )

  if command -v hybrid_menu >/dev/null 2>&1; then
    ACTION=$(hybrid_menu "ProxMenux" \
      "$(translate 'Coral TPU is already installed on this host:')\n\n${hint}\n$(translate 'Choose an action:')" \
      18 80 8 "${menu_choices[@]}") || ACTION="cancel"
  else
    ACTION=$(dialog --backtitle "ProxMenux" \
      --title "$(translate 'Coral Actions')" \
      --menu "\n$(translate 'Coral TPU is already installed:')\n${hint}\n$(translate 'Choose an action:')" \
      18 80 8 \
      "install" "$(translate 'Reinstall / update Coral drivers')" \
      "remove"  "$(translate 'Uninstall Coral drivers and configuration')" \
      3>&1 1>&2 2>&3) || ACTION="cancel"
  fi
}


# ============================================================
# complete_coral_uninstall — full removal of everything the
# installer puts on the host. Mirrors complete_nvidia_uninstall.
# Idempotent: missing pieces are no-ops, never errors.
# ============================================================
complete_coral_uninstall() {
  msg_info "$(translate 'Stopping Coral kernel modules...')"
  modprobe -r apex 2>>"$LOG_FILE" || true
  modprobe -r gasket 2>>"$LOG_FILE" || true
  msg_ok "$(translate 'Coral kernel modules unloaded.')"

  # DKMS removal for every registered gasket version.
  if command -v dkms >/dev/null 2>&1; then
    local versions
    versions=$(dkms status 2>/dev/null \
      | awk -F'[,/ ]+' '/^gasket/ {print $2}' | sort -u)
    if [[ -n "$versions" ]]; then
      msg_info "$(translate 'Removing gasket DKMS modules...')"
      local v
      while IFS= read -r v; do
        [[ -z "$v" ]] && continue
        dkms remove -m gasket -v "$v" --all >>"$LOG_FILE" 2>&1 || true
      done <<<"$versions"
      msg_ok "$(translate 'gasket DKMS entries removed.')"
    fi
  fi

  msg_info "$(translate 'Removing Coral packages...')"
  apt-get -y purge gasket-dkms libedgetpu1-std libedgetpu1-max \
      >>"$LOG_FILE" 2>&1 || true
  apt-get -y autoremove --purge >>"$LOG_FILE" 2>&1 || true
  msg_ok "$(translate 'Coral packages purged.')"

  # udev rules created by our installer.
  rm -f /etc/udev/rules.d/99-coral-apex.rules
  # Restore the upstream udev rule group (set it back to its default
  # GROUP="plugdev") in case dkms-postinstall reinstalls gasket-dkms
  # later — apex group may not exist next time.
  if [[ -f /usr/lib/udev/rules.d/60-gasket-dkms.rules ]]; then
    sed -i 's/GROUP="apex"/GROUP="plugdev"/g' \
      /usr/lib/udev/rules.d/60-gasket-dkms.rules || true
  fi
  udevadm control --reload-rules
  udevadm trigger --subsystem-match=apex >/dev/null 2>&1 || true

  # Apex system group: only remove if no one else is using it.
  if getent group apex >/dev/null 2>&1; then
    local apex_members
    apex_members=$(getent group apex | cut -d: -f4)
    if [[ -z "$apex_members" ]]; then
      groupdel apex >>"$LOG_FILE" 2>&1 || true
      msg_ok "$(translate 'apex group removed.')"
    else
      msg_warn "$(translate 'apex group still has members; left in place:') $apex_members"
    fi
  fi

  # Google Coral APT repo + keyring (only added during USB install).
  rm -f /etc/apt/sources.list.d/coral-edgetpu.list \
        /etc/apt/sources.list.d/coral-cloud.list \
        /usr/share/keyrings/coral-edgetpu-archive-keyring.gpg \
        /etc/apt/trusted.gpg.d/coral-edgetpu-archive-keyring.gpg \
        2>/dev/null || true

  # Update component status if utils.sh exposes the helper (older
  # ProxMenux releases didn't have it; uninstall must still work).
  if declare -f update_component_status >/dev/null 2>&1; then
    update_component_status "coral_driver" "removed" "" "gpu" '{}'
  fi

  msg_ok "$(translate 'Coral uninstallation completed.')"
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


# ============================================================
# Main orchestrator
# ============================================================
main() {
  : >"$LOG_FILE"

  detect_coral_hardware
  detect_coral_install_state

  # No hardware AND no leftover install → nothing to do.
  if [[ "$CORAL_PCIE_COUNT" -eq 0 && "$CORAL_USB_COUNT" -eq 0 ]] \
      && ! $CORAL_PCIE_INSTALLED && ! $CORAL_USB_INSTALLED; then
    no_hardware_dialog
    exit 0
  fi

  # If something is already installed, offer reinstall/uninstall choice.
  # Same UX as nvidia_installer.sh. When nothing is installed yet,
  # ACTION="install" automatically.
  show_coral_action_menu_if_installed

  case "$ACTION" in
    install)
      # No hardware but user picked install → bail out, can't install
      # for nothing. (The earlier "no hardware AND no install" exit
      # already handles the fully-empty case.)
      if [[ "$CORAL_PCIE_COUNT" -eq 0 && "$CORAL_USB_COUNT" -eq 0 ]]; then
        no_hardware_dialog
        exit 0
      fi

      pre_install_prompt

      show_proxmenux_logo
      msg_title "$(translate 'Coral TPU Installation')"

      # Force non-interactive apt/dpkg for the whole run so cleanup_broken_gasket_dkms
      # and the two install paths never get blocked by package-maintainer prompts.
      export DEBIAN_FRONTEND=noninteractive

      # Branch 1 — PCIe / M.2 (kernel modules). Runs first so the reboot reminder
      # at the end only appears when we actually touched kernel modules.
      if [[ "$CORAL_PCIE_COUNT" -gt 0 ]]; then
        msg_info2 "$(translate 'Coral M.2 / PCIe detected — installing gasket and apex kernel modules...')"
        install_gasket_apex_dkms
      fi

      # Branch 2 — USB (user-space runtime).
      if [[ "$CORAL_USB_COUNT" -gt 0 ]]; then
        msg_info2 "$(translate 'Coral USB Accelerator detected — installing Edge TPU runtime...')"
        install_libedgetpu_runtime
      fi

      echo
      if [[ "$CORAL_PCIE_COUNT" -gt 0 ]]; then
        msg_success "$(translate 'Coral TPU drivers installed and loaded successfully.')"
        restart_prompt
      else
        # USB-only install. No reboot required; the udev rules and runtime are
        # already active. Ready to passthrough the device to an LXC/VM.
        msg_success "$(translate 'Coral USB runtime installed. No reboot required.')"
        msg_success "$(translate 'Completed. Press Enter to return to menu...')"
        read -r
      fi
      ;;

    remove)
      # Confirm before purging — gasket-dkms uninstall is destructive
      # to LXC containers that have apex passthrough; warn the user.
      if ! dialog --backtitle "ProxMenux" \
          --title "$(translate 'Coral TPU Uninstall')" \
          --yesno "\n$(translate 'This will remove the Coral TPU drivers (gasket DKMS + libedgetpu) and related configuration. Any LXC container with apex passthrough will lose access to /dev/apex_* after reboot. Continue?')" \
          14 78; then
        exit 0
      fi

      show_proxmenux_logo
      msg_title "$(translate 'Coral TPU Uninstall')"

      export DEBIAN_FRONTEND=noninteractive
      complete_coral_uninstall

      # PCIe path created kernel modules → a reboot is the cleanest
      # way to flush them. USB-only uninstall doesn't need one.
      if $CORAL_PCIE_INSTALLED; then
        restart_prompt
      else
        msg_success "$(translate 'Completed. Press Enter to return to menu...')"
        read -r
      fi
      ;;

    cancel|*)
      exit 0
      ;;
  esac
}

main
