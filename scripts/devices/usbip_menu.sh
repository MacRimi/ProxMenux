#!/bin/bash
# ProxMenux - selected USB devices over authenticated SSH (GPL-3.0)
set -o pipefail
umask 077

BASE_DIR="/usr/local/share/proxmenux"
LOCAL_SCRIPTS="$BASE_DIR/scripts"
MANAGER="$LOCAL_SCRIPTS/devices/usbip_manager.py"
if [[ -f "$BASE_DIR/utils.sh" ]]; then
    source "$BASE_DIR/utils.sh"
    load_language
    initialize_cache
else
    translate() { printf '%s' "$1"; }
fi
if [[ -f "$LOCAL_SCRIPTS/global/pmx_journal.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/pmx_journal.sh"
fi

if [[ $EUID -ne 0 ]]; then
    printf '%s\n' "$(translate 'Run this menu as root.')" >&2
    exit 1
fi

usbip_dialog() {
    dialog --backtitle "ProxMenux" --title "$(translate 'USB/IP over SSH')" "$@"
}

usbip_action() {
    local output result=0
    output=$(mktemp) || return 1
    if python3 "$MANAGER" "$@" >"$output" 2>&1; then
        if declare -F pmx_journal_context >/dev/null; then
            pmx_journal_context "usbip_${1//-/_}" "1.0" "usbip_menu.sh"
            pmx_record_execution "USB/IP: $1" "python3 $MANAGER $1"
        fi
        usbip_dialog --msgbox "$(translate 'USB/IP configuration updated. Open status to check the connection.')" 9 72
    else
        usbip_dialog --textbox "$output" 20 85
        result=1
    fi
    rm -f "$output"
    return "$result"
}

usbip_dependencies() {
    local role="$1" package output
    local -a packages=(usbip openssh-client kmod)
    [[ "$role" == server ]] && packages+=(socat)
    local missing=false
    command -v usbip >/dev/null || missing=true
    command -v ssh >/dev/null || missing=true
    command -v modprobe >/dev/null || missing=true
    if [[ "$role" == server ]]; then
        command -v usbipd >/dev/null || missing=true
        command -v socat >/dev/null || missing=true
    fi
    [[ "$missing" == false ]] && return 0
    usbip_dialog --yesno "$(translate 'Install the USB/IP dependencies from the configured Debian repositories?')" 9 72 || return 1
    output=$(mktemp) || return 1
    # Keep the operator's repository configuration; do not enable new sources.
    if ! apt-get update -o APT::Update::Error-Mode=any >"$output" 2>&1; then
        usbip_dialog --textbox "$output" 20 85
        rm -f "$output"
        return 1
    fi
    for package in "${packages[@]}"; do
        if declare -F pmx_install_pkg >/dev/null; then
            pmx_install_pkg "$package" >>"$output" 2>&1
        else
            DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" >>"$output" 2>&1
        fi
        if [[ $? -ne 0 ]]; then
            usbip_dialog --textbox "$output" 20 85
            rm -f "$output"
            return 1
        fi
    done
    rm -f "$output"
}

usbip_status() {
    local output raw
    output=$(mktemp) || return 1
    raw=$(mktemp) || { rm -f "$output"; return 1; }
    if python3 "$MANAGER" status >"$raw" 2>"$output"; then
        jq -r '"SERVER configured: \(.server)  running: \(.server_active)\n",
          (.exports[] | "EXPORT \(.id)  \(.name)\n  \(.vendor):\(.product)  serial: \(.serial)\n  bus: \(.busid // "waiting")  state: \(.status)\n"),
          (.server_status.errors // {} | to_entries[] | "ERROR \(.key): \(.value)"),
          "\nCLIENTS:",
          (.imports[] | "\(.id)  root@\(.host):\(.ssh_port)\n  export: \(.export_id)  local tunnel: 127.0.0.1:\(.local_port)\n  running: \(.active)  state: \(.status.state)  \(.status.error // "")\n")' "$raw" >"$output"
    fi
    usbip_dialog --textbox "$output" 26 100
    rm -f "$output" "$raw"
}

usbip_add_export() {
    local busid label chosen
    local -a choices=()
    while IFS=$'\t' read -r busid label; do
        [[ -n "$busid" ]] && choices+=("$busid" "$label")
    done < <(python3 "$MANAGER" inventory | jq -r '.[] | select(.blocked == "" and .driver != "usbip-host") | [.busid, "\(.name) [\(.vendor):\(.product)] serial: \(.serial)"] | @tsv')
    if [[ ${#choices[@]} -eq 0 ]]; then
        usbip_dialog --msgbox "$(translate 'No eligible USB devices found. Hubs and mass storage are excluded.')" 10 75
        return
    fi
    chosen=$(usbip_dialog --stdout --menu "$(translate 'Select the USB device to share:')" 22 100 12 "${choices[@]}") || return
    usbip_dialog --yesno "$(translate 'The selected USB device will become unavailable to local applications and guests. Only one remote client can use it at a time. Share this device?')\n\n$chosen" 12 80 || return
    usbip_action add-export "$chosen"
}

usbip_select_saved() {
    local field="$1" identifier label
    local -a choices=()
    while IFS=$'\t' read -r identifier label; do
        [[ -n "$identifier" ]] && choices+=("$identifier" "$label")
    done < <(python3 "$MANAGER" status | jq -r --arg field "$field" '.[$field][] | [.id, (.name // .host)] | @tsv')
    [[ ${#choices[@]} -gt 0 ]] || return 1
    usbip_dialog --stdout --menu "$(translate 'Select a saved USB/IP device:')" 20 90 10 "${choices[@]}"
}

usbip_add_import() {
    usbip_dependencies client || return
    local host ssh_port key local_port output error selected identifier label
    local -a choices=()
    usbip_dialog --msgbox "$(translate 'The client must already trust the server SSH host key and have a root SSH key authorized there. Test normal SSH first. ProxMenux will not change SSH access or accept unknown host keys.')" 12 85
    host=$(usbip_dialog --stdout --inputbox "$(translate 'USB/IP server IP address or DNS hostname:')" 9 75) || return
    ssh_port=$(usbip_dialog --stdout --inputbox "$(translate 'Server SSH port:')" 9 70 "22") || return
    key=$(usbip_dialog --stdout --inputbox "$(translate 'Absolute path of the client SSH private key:')" 9 80 "/root/.ssh/id_ed25519") || return
    output=$(mktemp) || return
    error=$(mktemp) || { rm -f "$output"; return; }
    if ! python3 "$MANAGER" remote --host "$host" --ssh-port "$ssh_port" --key "$key" >"$output" 2>"$error"; then
        usbip_dialog --textbox "$error" 20 90
        rm -f "$output" "$error"
        return
    fi
    while IFS=$'\t' read -r identifier label; do
        [[ -n "$identifier" ]] && choices+=("$identifier" "$label")
    done < <(jq -r '.[] | select(.status == "exported") | [.id, "\(.name) [\(.busid)]"] | @tsv' "$output")
    rm -f "$output" "$error"
    if [[ ${#choices[@]} -eq 0 ]]; then
        usbip_dialog --msgbox "$(translate 'No shared devices are available on this server.')" 9 72
        return
    fi
    selected=$(usbip_dialog --stdout --menu "$(translate 'Select the remote USB device:')" 20 95 10 "${choices[@]}") || return
    local_port=$(usbip_dialog --stdout --inputbox "$(translate 'Unused local loopback TCP port for this device:')" 9 75 "33240") || return
    usbip_action add-import --host "$host" --ssh-port "$ssh_port" --key "$key" --export-id "$selected" --local-port "$local_port"
}

while true; do
    option=$(usbip_dialog --stdout --menu "$(translate 'Share selected USB devices through SSH, or connect this Linux machine to a USB/IP server.')" 22 95 12 \
        "1" "$(translate 'View USB/IP status')" \
        "2" "$(translate 'Enable USB/IP server')" \
        "3" "$(translate 'Share a local USB device')" \
        "4" "$(translate 'Stop sharing a USB device')" \
        "5" "$(translate 'Disable USB/IP server')" \
        "6" "$(translate 'Connect a remote USB device')" \
        "7" "$(translate 'Remove a remote USB connection')" \
        "8" "$(translate 'Linux guest setup and migration notes')" \
        "0" "$(translate 'Back')") || break
    case "$option" in
        1) usbip_status ;;
        2) usbip_dependencies server && usbip_action server-enable ;;
        3) usbip_add_export ;;
        4)
            selected=$(usbip_select_saved exports) || continue
            usbip_dialog --yesno "$(translate 'Stop sharing this device? An attached remote client will disconnect.')\n\n$selected" 10 80 && usbip_action remove-export "$selected"
            ;;
        5)
            usbip_dialog --yesno "$(translate 'Disable the server and release all USB devices managed by ProxMenux? Saved selections are kept for the next enable.')" 11 80 && usbip_action server-disable
            ;;
        6) usbip_add_import ;;
        7)
            selected=$(usbip_select_saved imports) || continue
            usbip_dialog --yesno "$(translate 'Remove this connection and detach its USB device?')\n\n$selected" 10 75 && usbip_action remove-import "$selected"
            ;;
        8)
            usbip_dialog --msgbox "$(translate 'Run the client inside the Linux VM that needs the USB device. Install usbip, openssh-client and kmod, then copy usbip_manager.py to the same path as on the server. Configure key authentication and verify the server host key before adding a connection. The client uses the guest kernel and can reconnect after migration while the physical USB device stays on the server. Unprivileged LXC and Home Assistant OS need their own kernel/device or add-on setup. A physical device supports one attached client at a time.')" 19 95
            ;;
        0) break ;;
    esac
done
