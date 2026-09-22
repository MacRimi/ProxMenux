#!/bin/bash
# ==========================================================
# ProxMenux - OCI manager Apps (beta)
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
    python3 -c 'import yaml' >/dev/null 2>&1 || missing+=("python3-yaml")
    command -v skopeo >/dev/null 2>&1 || missing+=("skopeo")
    [[ ${#missing[@]} -eq 0 ]] && return 0

    show_proxmenux_logo
    msg_title "$(translate "OCI manager Apps (beta)")"
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

if [[ ! -f "$OCI_ENGINE_DIR/src/proxmenux_oci/__main__.py" ]]; then
    msg_error "$(translate "The OCI engine is not installed. Update ProxMenux and try again.")"
    exit 1
fi

ensure_oci_dependencies || exit 1

if [[ $# -gt 0 ]]; then
    PYTHONPATH="$OCI_ENGINE_DIR/src" exec python3 -m proxmenux_oci "$@"
fi
PYTHONPATH="$OCI_ENGINE_DIR/src" python3 -m proxmenux_oci
exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
