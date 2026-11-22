#!/bin/bash
# ==========================================================
# ProxMenux - OCI manager Apps (Technology Preview)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Installs official container images as native Proxmox OCI
# LXC containers from the ProxMenux catalog, and manages the
# instances it created. The catalog and the installer live in
# the OCI engine ($BASE_DIR/oci/engine).
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
OCI_ENGINE_DIR="$BASE_DIR/oci/engine"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS/global/pmx_journal.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/pmx_journal.sh"
fi

load_language
initialize_cache

ensure_oci_dependencies() {
    local -a missing=()
    # Check installed modules without importing jsonschema's whole dependency
    # tree in a throwaway process before starting the actual engine.
    if ! python3 -c 'from importlib.util import find_spec; raise SystemExit(not all(find_spec(name) for name in ("yaml", "jsonschema")))' >/dev/null 2>&1; then
        python3 -c 'import yaml' >/dev/null 2>&1 || missing+=("python3-yaml")
        python3 -c 'import jsonschema' >/dev/null 2>&1 || missing+=("python3-jsonschema")
    fi
    command -v skopeo >/dev/null 2>&1 || missing+=("skopeo")
    [[ ${#missing[@]} -eq 0 ]] && return 0

    show_proxmenux_logo
    msg_title "$(translate "OCI manager Apps (Technology Preview)")"
    msg_info "$(translate "Installing required packages...")"
    apt-get update >/dev/null 2>&1
    local status
    if declare -F pmx_install_pkg >/dev/null; then
        pmx_journal_context "ensure_oci_dependencies" "1.0" "oci_manager_apps.sh"
        pmx_install_pkg "${missing[@]}"
        status=$?
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}" >/dev/null 2>&1
        status=$?
    fi
    if [[ $status -ne 0 ]]; then
        msg_error "$(translate "Could not install the required packages:") ${missing[*]}"
        return 1
    fi
    stop_spinner
}

# Proxmox VE runs OCI images as LXC containers from 9.1 on. The package
# database answers at once; pveversion takes about half a second.
pve_manager_version() {
    dpkg-query -W -f='${Version}' pve-manager 2>/dev/null | grep -oE '^[0-9]+(\.[0-9]+)+' | head -1
}

pve_supports_oci() {
    local major minor
    IFS=. read -r major minor _ <<< "$(pve_manager_version)"
    [[ $major =~ ^[0-9]+$ && $minor =~ ^[0-9]+$ ]] || return 1
    (( major > 9 || (major == 9 && minor >= 1) ))
}

if ! pve_supports_oci; then
    show_proxmenux_logo
    msg_title "$(translate "OCI manager Apps (Technology Preview)")"
    msg_error "$(translate "OCI containers require Proxmox VE 9.1 or later.")"
    PVE_VERSION=$(pve_manager_version)
    [[ -n $PVE_VERSION ]] && msg_info2 "$(translate "Current version:") $PVE_VERSION"
    if [[ -t 0 ]]; then
        echo
        msg_success "$(translate "Press Enter to return to the menu...")"
        read -r
        [[ $# -eq 0 ]] && exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
    fi
    exit 1
fi

if [[ ! -f "$OCI_ENGINE_DIR/src/proxmenux_oci/__main__.py" ]]; then
    msg_error "$(translate "The OCI engine is not installed. Update ProxMenux and try again.")"
    exit 1
fi

ensure_oci_dependencies || exit 1

if [[ $# -gt 0 ]]; then
    PYTHONPATH="$OCI_ENGINE_DIR/src" exec python3 -m proxmenux_oci "$@"
fi
PYTHONPATH="$OCI_ENGINE_DIR/src" python3 -m proxmenux_oci
OCI_STATUS=$?

# Do not replace an OCI engine traceback with the main menu.  Returning to the
# menu is correct after a normal cancellation, but an unexpected non-zero exit
# must remain visible so the user can report and diagnose it.
if [[ $OCI_STATUS -ne 0 ]]; then
    exit "$OCI_STATUS"
fi

exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
