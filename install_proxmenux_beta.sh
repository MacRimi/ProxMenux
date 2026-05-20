#!/bin/bash

# ==========================================================
# ProxMenux Monitor - Beta Program Installer
# ==========================================================
# Author       : MacRimi
# Subproject   : ProxMenux Monitor Beta
# Copyright    : (c) 2024-2025 MacRimi
# License      : GPL-3.0 (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version      : Beta 1.1
# Branch       : develop
# Last Updated : 2026-03-26
# ==========================================================
# Description:
# This script installs the BETA version of ProxMenux Monitor
# from the develop branch on GitHub.
#
# Beta testers are expected to:
#   - Report bugs and unexpected behavior via GitHub Issues
#   - Provide feedback to help improve the final release
#
# Installs:
#   • dialog, curl, jq, git     (system dependencies)
#   • ProxMenux core files      (/usr/local/share/proxmenux)
#   • ProxMenux Monitor AppImage (Web dashboard on port 8008)
#   • Systemd service           (auto-start on boot)
#
# Notes:
#   - Clones from the 'develop' branch
#   - Beta version file: beta_version.txt in the repository
#   - Transition to stable: re-run the official installer
# ==========================================================

# ── Configuration ──────────────────────────────────────────
INSTALL_DIR="/usr/local/bin"
BASE_DIR="/usr/local/share/proxmenux"
CONFIG_FILE="$BASE_DIR/config.json"
CACHE_FILE="$BASE_DIR/cache.json"
UTILS_FILE="$BASE_DIR/utils.sh"
LOCAL_VERSION_FILE="$BASE_DIR/version.txt"
BETA_VERSION_FILE="$BASE_DIR/beta_version.txt"
MENU_SCRIPT="menu"

MONITOR_INSTALL_DIR="$BASE_DIR"
MONITOR_RUNTIME_DIR="$BASE_DIR/monitor-app"
MONITOR_SERVICE_FILE="/etc/systemd/system/proxmenux-monitor.service"
MONITOR_PORT=8008

REPO_URL="https://github.com/MacRimi/ProxMenux.git"
REPO_BRANCH="develop"
TEMP_DIR="/tmp/proxmenux-beta-install-$$"

# ── Colors ─────────────────────────────────────────────────
RESET="\033[0m"
BOLD="\033[1m"
WHITE="\033[38;5;15m"
NEON_PURPLE_BLUE="\033[38;5;99m"
DARK_GRAY="\033[38;5;244m"
ORANGE="\033[38;5;208m"
GN="\033[1;92m"
YW="\033[33m"
YWB="\033[1;33m"
RD="\033[01;31m"
BL="\033[36m"
CL="\033[m"
BGN="\e[1;32m"
TAB="    "
BFR="\\r\\033[K"
HOLD="-"
BOR=" | "
CM="${GN}✓ ${CL}"

SPINNER_PID=""

# ── Spinner ────────────────────────────────────────────────
spinner() {
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local spin_i=0
    printf "\e[?25l"
    while true; do
        printf "\r ${YW}%s${CL}" "${frames[spin_i]}"
        spin_i=$(( (spin_i + 1) % ${#frames[@]} ))
        sleep 0.1
    done
}

type_text() {
    local text="$1"
    local delay=0.04
    for ((i=0; i<${#text}; i++)); do
        echo -n "${text:$i:1}"
        sleep $delay
    done
    echo
}

msg_info() {
    local msg="$1"
    echo -ne "${TAB}${YW}${HOLD}${msg}"
    spinner &
    SPINNER_PID=$!
}

msg_ok() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null 2>&1; then
        kill $SPINNER_PID > /dev/null 2>&1
        SPINNER_PID=""
    fi
    printf "\e[?25h"
    echo -e "${BFR}${TAB}${CM}${GN}${1}${CL}"
}

msg_error() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null 2>&1; then
        kill $SPINNER_PID > /dev/null 2>&1
        SPINNER_PID=""
    fi
    printf "\e[?25h"
    echo -e "${BFR}${TAB}${RD}[ERROR] ${1}${CL}"
}

msg_warn() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null 2>&1; then
        kill $SPINNER_PID > /dev/null 2>&1
        SPINNER_PID=""
    fi
    printf "\e[?25h"
    echo -e "${BFR}${TAB}${YWB}${1}${CL}"
}

msg_title() {
    echo -e "\n"
    echo -e "${TAB}${BOLD}${HOLD}${BOR}${1}${BOR}${HOLD}${CL}"
    echo -e "\n"
}

show_progress() {
    echo -e "\n${BOLD}${BL}${TAB}Installing ProxMenux Beta: Step ${1} of ${2}${CL}"
    echo
    echo -e "${TAB}${BOLD}${YW}${HOLD}${3}${CL}"
}

# ── Cleanup ────────────────────────────────────────────────
cleanup() {
    if [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

# ── Logo ───────────────────────────────────────────────────
show_proxmenux_logo() {
    clear

    if [[ -z "$SSH_TTY" && -z "$(who am i | awk '{print $NF}' | grep -E '([0-9]{1,3}\.){3}[0-9]{1,3}')" ]]; then

LOGO=$(cat << "EOF"
\e[0m\e[38;2;61;61;61m▆\e[38;2;60;60;60m▄\e[38;2;54;54;54m▂\e[0m \e[38;2;0;0;0m             \e[0m \e[38;2;54;54;54m▂\e[38;2;60;60;60m▄\e[38;2;61;61;61m▆\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[38;2;61;61;61;48;2;37;37;37m▇\e[0m\e[38;2;60;60;60m▅\e[38;2;56;56;56m▃\e[38;2;37;37;37m▁       \e[38;2;36;36;36m▁\e[38;2;56;56;56m▃\e[38;2;60;60;60m▅\e[38;2;61;61;61;48;2;37;37;37m▇\e[48;2;62;62;62m  \e[0m\e[7m\e[38;2;60;60;60m▁\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[7m\e[38;2;61;61;61m▂\e[0m\e[38;2;62;62;62;48;2;61;61;61m┈\e[48;2;62;62;62m \e[48;2;61;61;61m┈\e[0m\e[38;2;60;60;60m▆\e[38;2;57;57;57m▄\e[38;2;48;48;48m▂\e[0m \e[38;2;47;47;47m▂\e[38;2;57;57;57m▄\e[38;2;60;60;60m▆\e[38;2;62;62;62;48;2;61;61;61m┈\e[48;2;62;62;62m \e[48;2;61;61;61m┈\e[0m\e[7m\e[38;2;60;60;60m▂\e[38;2;57;57;57m▄\e[38;2;47;47;47m▆\e[0m \e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[38;2;32;32;32m▏\e[7m\e[38;2;39;39;39m▇\e[38;2;57;57;57m▅\e[38;2;60;60;60m▃\e[0m\e[38;2;40;40;40;48;2;61;61;61m▁\e[48;2;62;62;62m  \e[38;2;54;54;54;48;2;61;61;61m┊\e[48;2;62;62;62m  \e[38;2;39;39;39;48;2;61;61;61m▁\e[0m\e[7m\e[38;2;60;60;60m▃\e[38;2;57;57;57m▅\e[38;2;38;38;38m▇\e[0m \e[38;2;193;60;2m▃\e[38;2;217;67;2m▅\e[38;2;225;70;2m▇\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[38;2;32;32;32m▏\e[0m \e[38;2;203;63;2m▄\e[38;2;147;45;1m▂\e[0m \e[7m\e[38;2;55;55;55m▆\e[38;2;60;60;60m▄\e[38;2;61;61;61m▂\e[38;2;60;60;60m▄\e[38;2;55;55;55m▆\e[0m \e[38;2;144;44;1m▂\e[38;2;202;62;2m▄\e[38;2;219;68;2m▆\e[38;2;231;72;3;48;2;226;70;2m┈\e[48;2;231;72;3m  \e[48;2;225;70;2m▉\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[38;2;32;32;32m▏\e[7m\e[38;2;121;37;1m▉\e[0m\e[38;2;0;0;0;48;2;231;72;3m  \e[0m\e[38;2;221;68;2m▇\e[38;2;208;64;2m▅\e[38;2;212;66;2m▂\e[38;2;123;37;0m▁\e[38;2;211;65;2m▂\e[38;2;207;64;2m▅\e[38;2;220;68;2m▇\e[48;2;231;72;3m  \e[38;2;231;72;3;48;2;225;70;2m┈\e[0m\e[7m\e[38;2;221;68;2m▂\e[0m\e[38;2;44;13;0;48;2;231;72;3m  \e[38;2;231;72;3;48;2;225;70;2m▉\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[38;2;32;32;32m▏\e[0m \e[7m\e[38;2;190;59;2m▅\e[38;2;216;67;2m▃\e[38;2;225;70;2m▁\e[0m\e[38;2;95;29;0;48;2;231;72;3m  \e[38;2;231;72;3;48;2;230;71;2m┈\e[48;2;231;72;3m  \e[0m\e[7m\e[38;2;225;70;2m▁\e[38;2;216;67;2m▃\e[38;2;191;59;2m▅\e[0m  \e[38;2;0;0;0;48;2;231;72;3m  \e[38;2;231;72;3;48;2;225;70;2m▉\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[38;2;32;32;32m▏   \e[0m \e[7m\e[38;2;172;53;1m▆\e[38;2;213;66;2m▄\e[38;2;219;68;2m▂\e[38;2;213;66;2m▄\e[38;2;174;54;2m▆\e[0m \e[38;2;0;0;0m   \e[0m \e[38;2;0;0;0;48;2;231;72;3m  \e[38;2;231;72;3;48;2;225;70;2m▉\e[0m
\e[38;2;59;59;59;48;2;62;62;62m▏  \e[0m\e[38;2;32;32;32m▏             \e[0m \e[38;2;0;0;0;48;2;231;72;3m  \e[38;2;231;72;3;48;2;225;70;2m▉\e[0m
\e[7m\e[38;2;52;52;52m▆\e[38;2;59;59;59m▄\e[38;2;61;61;61m▂\e[0m\e[38;2;31;31;31m▏             \e[0m \e[7m\e[38;2;228;71;2m▂\e[38;2;221;69;2m▄\e[38;2;196;60;2m▆\e[0m
EOF
)
        TEXT=(
            ""
            ""
            "${BOLD}ProxMenux${RESET}"
            ""
            "${BOLD}${NEON_PURPLE_BLUE}An Interactive Menu for${RESET}"
            "${BOLD}${NEON_PURPLE_BLUE}Proxmox VE management${RESET}"
            ""
            "${BOLD}${YW}  ★  BETA PROGRAM  ★${RESET}"
            ""
            ""
        )
        mapfile -t logo_lines <<< "$LOGO"
        for i in {0..9}; do
            echo -e "${TAB}${logo_lines[i]}  ${WHITE}│${RESET}  ${TEXT[i]}"
        done
        echo -e

    else

        TEXT=(
            ""  ""  ""  ""
            "${BOLD}ProxMenux${RESET}"
            ""
            "${BOLD}${NEON_PURPLE_BLUE}An Interactive Menu for${RESET}"
            "${BOLD}${NEON_PURPLE_BLUE}Proxmox VE management${RESET}"
            ""
            "${BOLD}${YW}  ★  BETA PROGRAM  ★${RESET}"
            ""  ""  ""
        )
        LOGO=(
            "${DARK_GRAY}░░░░                     ░░░░${RESET}"
            "${DARK_GRAY}░░░░░░░               ░░░░░░ ${RESET}"
            "${DARK_GRAY}░░░░░░░░░░░       ░░░░░░░    ${RESET}"
            "${DARK_GRAY}░░░░    ░░░░░░ ░░░░░░      ${ORANGE}░░${RESET}"
            "${DARK_GRAY}░░░░       ░░░░░░░      ${ORANGE}░░▒▒▒${RESET}"
            "${DARK_GRAY}░░░░         ░░░     ${ORANGE}░▒▒▒▒▒▒▒${RESET}"
            "${DARK_GRAY}░░░░   ${ORANGE}▒▒▒░       ░▒▒▒▒▒▒▒▒▒▒${RESET}"
            "${DARK_GRAY}░░░░   ${ORANGE}░▒▒▒▒▒   ▒▒▒▒▒░░  ▒▒▒▒${RESET}"
            "${DARK_GRAY}░░░░     ${ORANGE}░░▒▒▒▒▒▒▒░░     ▒▒▒▒${RESET}"
            "${DARK_GRAY}░░░░         ${ORANGE}░░░         ▒▒▒▒${RESET}"
            "${DARK_GRAY}░░░░                     ${ORANGE}▒▒▒▒${RESET}"
            "${DARK_GRAY}░░░░                     ${ORANGE}▒▒▒░${RESET}"
            "${DARK_GRAY}  ░░                     ${ORANGE}░░  ${RESET}"
        )
        for i in {0..12}; do
            echo -e "${TAB}${LOGO[i]}  │${RESET}  ${TEXT[i]}"
        done
        echo -e
    fi
}

# ── Beta welcome message ───────────────────────────────────
show_beta_welcome() {
    local width=62
    local line
    line=$(printf '─%.0s' $(seq 1 $width))

    echo -e "${TAB}${BOLD}${YW}┌${line}┐${CL}"
    echo -e "${TAB}${BOLD}${YW}│${CL}${BOLD}          Welcome to the ProxMenux Monitor Beta Program         ${YW}│${CL}"
    echo -e "${TAB}${BOLD}${YW}└${line}┘${CL}"
    echo
    echo -e "${TAB}${WHITE}You are about to install a ${BOLD}pre-release (beta)${RESET}${WHITE} version of${CL}"
    echo -e "${TAB}${WHITE}ProxMenux Monitor, built from the ${BOLD}develop${RESET}${WHITE} branch.${CL}"
    echo
    echo -e "${TAB}${BOLD}${GN}What this means for you:${CL}"
    echo -e "${TAB}  ${GN}•${CL} You'll get the latest features before the official release."
    echo -e "${TAB}  ${GN}•${CL} Some things may not work perfectly — that's expected."
    echo -e "${TAB}  ${GN}•${CL} Your feedback is what makes the final version better."
    echo
    echo -e "${TAB}${BOLD}${YW}How to report issues:${CL}"
    echo -e "${TAB}  ${YW}→${CL} Open a GitHub Issue at:"
    echo -e "${TAB}    ${BL}https://github.com/MacRimi/ProxMenux/issues${CL}"
    echo -e "${TAB}  ${YW}→${CL} Describe what happened, what you expected, and any"
    echo -e "${TAB}    error messages you saw. Logs help a lot:"
    echo -e "${TAB}    ${DARK_GRAY}journalctl -u proxmenux-monitor -n 50${CL}"
    echo
    echo -e "${TAB}${BOLD}${NEON_PURPLE_BLUE}Thank you for being part of the beta program!${CL}"
    echo -e "${TAB}${DARK_GRAY}Your help is essential to deliver a stable and polished release.${CL}"
    echo
    echo -e "${TAB}${BOLD}${YW}┌${line}┐${CL}"
    echo -e "${TAB}${BOLD}${YW}│${CL}                                                              ${YW}│${CL}"
    echo -e "${TAB}${BOLD}${YW}│${CL}  Press ${BOLD}${GN}[Enter]${CL} to continue with the beta installation,     ${YW}│${CL}"
    echo -e "${TAB}${BOLD}${YW}│${CL}  or ${BOLD}${RD}[Ctrl+C]${CL} to cancel and exit.                           ${YW}│${CL}"
    echo -e "${TAB}${BOLD}${YW}│${CL}                                                              ${YW}│${CL}"
    echo -e "${TAB}${BOLD}${YW}└${line}┘${CL}"
    echo

    read -r -p ""
    echo
}

# ── Helpers ────────────────────────────────────────────────
get_server_ip() {
    local ip
    ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+')
    [ -z "$ip" ] && ip=$(hostname -I | awk '{print $1}')
    [ -z "$ip" ] && ip="localhost"
    echo "$ip"
}

update_config() {
    local component="$1"
    local status="$2"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    mkdir -p "$(dirname "$CONFIG_FILE")"
    [ ! -f "$CONFIG_FILE" ] || ! jq empty "$CONFIG_FILE" >/dev/null 2>&1 && echo '{}' > "$CONFIG_FILE"

    local tmp_file
    tmp_file=$(mktemp)
    if jq --arg comp "$component" --arg stat "$status" --arg time "$timestamp" \
        '.[$comp] = {status: $stat, timestamp: $time}' "$CONFIG_FILE" > "$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$CONFIG_FILE"
    else
        echo '{}' > "$CONFIG_FILE"
    fi
    [ -f "$tmp_file" ] && rm -f "$tmp_file"
}

reset_update_flag() {
    # Reset the update_available flag in config.json after successful update
    [ ! -f "$CONFIG_FILE" ] && return 0
    
    local tmp_file
    tmp_file=$(mktemp)
    if jq '.update_available.beta = false | .update_available.beta_version = ""' "$CONFIG_FILE" > "$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$CONFIG_FILE"
    fi
    [ -f "$tmp_file" ] && rm -f "$tmp_file"
}

cleanup_corrupted_files() {
    if [ -f "$CONFIG_FILE" ] && ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        rm -f "$CONFIG_FILE"
    fi
    if [ -f "$CACHE_FILE" ] && ! jq empty "$CACHE_FILE" >/dev/null 2>&1; then
        rm -f "$CACHE_FILE"
    fi
}

detect_latest_appimage() {
    local appimage_dir="$TEMP_DIR/AppImage"
    [ ! -d "$appimage_dir" ] && return 1
    local latest
    latest=$(find "$appimage_dir" -name "ProxMenux-*.AppImage" -type f | sort -V | tail -1)
    [ -z "$latest" ] && return 1
    echo "$latest"
}

get_appimage_version() {
    local filename
    filename=$(basename "$1")
    echo "$filename" | grep -oP 'ProxMenux-\K[0-9]+\.[0-9]+\.[0-9]+'
}

# ── AppImage runtime extraction ────────────────────────────
# Extract the AppImage's squashfs to a stable directory and run AppRun
# directly. Avoids the FUSE mount under /tmp/.mount_ProxMe<random>, which
# trips Wazuh rule 521 / rkhunter "Possible kernel level rootkit" alerts
# (issue #101) — those scanners flag any directory that appears in
# readdir() but is hidden from lstat(), which is exactly what AppImage's
# FUSE mount layer looks like to them. Running from a plain extracted
# directory has the same files but no FUSE indirection, so the false
# positive disappears.
extract_appimage_to_runtime_dir() {
    local appimage_path="$1"
    local target_runtime_dir="$2"
    local tmp_extract_dir
    tmp_extract_dir=$(mktemp -d /tmp/proxmenux-extract.XXXXXX) || return 1

    #msg_info "Extracting AppImage runtime to ${target_runtime_dir}..."

    if ! ( cd "$tmp_extract_dir" && "$appimage_path" --appimage-extract >/dev/null 2>&1 ); then
        msg_error "Failed to extract AppImage."
        rm -rf "$tmp_extract_dir"
        return 1
    fi

    if [ ! -x "$tmp_extract_dir/squashfs-root/AppRun" ]; then
        msg_error "Extracted AppImage missing AppRun."
        rm -rf "$tmp_extract_dir"
        return 1
    fi

    rm -rf "${target_runtime_dir}.new"
    mv "$tmp_extract_dir/squashfs-root" "${target_runtime_dir}.new"
    rm -rf "$tmp_extract_dir"

    if [ -d "$target_runtime_dir" ]; then
        rm -rf "${target_runtime_dir}.old"
        mv "$target_runtime_dir" "${target_runtime_dir}.old"
    fi
    mv "${target_runtime_dir}.new" "$target_runtime_dir"
    rm -rf "${target_runtime_dir}.old"

    rm -f "$appimage_path"

    msg_ok "AppImage runtime extracted (no FUSE mount; bypasses Wazuh rule 521)."
    return 0
}

# ── Monitor install ────────────────────────────────────────
install_proxmenux_monitor() {
    local appimage_source
    appimage_source=$(detect_latest_appimage)

    if [ -z "$appimage_source" ] || [ ! -f "$appimage_source" ]; then
        msg_error "ProxMenux Monitor AppImage not found in $TEMP_DIR/AppImage/"
        msg_warn "Make sure the AppImage directory exists in the develop branch."
        update_config "proxmenux_monitor" "appimage_not_found"
        return 1
    fi

    local appimage_version
    appimage_version=$(get_appimage_version "$appimage_source")

    systemctl is-active --quiet proxmenux-monitor.service 2>/dev/null && \
        systemctl stop proxmenux-monitor.service

    local service_exists=false
    [ -f "$MONITOR_SERVICE_FILE" ] && service_exists=true

    local sha256_file="$TEMP_DIR/AppImage/ProxMenux-Monitor.AppImage.sha256"
    if [ -f "$sha256_file" ]; then
        msg_info "Verifying AppImage integrity..."
        local expected_hash actual_hash
        expected_hash=$(grep -Eo '^[a-f0-9]+' "$sha256_file" | tr -d '\n')
        actual_hash=$(sha256sum "$appimage_source" | awk '{print $1}')
        if [ "$expected_hash" != "$actual_hash" ]; then
            msg_error "SHA256 verification failed! The AppImage may be corrupted."
            return 1
        fi
        msg_ok "SHA256 verification passed."
    else
        msg_warn "SHA256 checksum file not found. Skipping verification."
    fi

    msg_info "Installing ProxMenux Monitor (beta)..."
    mkdir -p "$MONITOR_INSTALL_DIR"
    local target_path="$MONITOR_INSTALL_DIR/ProxMenux-Monitor.AppImage"
    cp "$appimage_source" "$target_path"
    chmod +x "$target_path"

    if ! extract_appimage_to_runtime_dir "$target_path" "$MONITOR_RUNTIME_DIR"; then
        update_config "proxmenux_monitor" "extract_failed"
        return 1
    fi

    # Copy shutdown-notify.sh script for systemd ExecStop
    local shutdown_script_src="$TEMP_DIR/scripts/shutdown-notify.sh"
    local shutdown_script_dst="$MONITOR_INSTALL_DIR/scripts/shutdown-notify.sh"
    if [ -f "$shutdown_script_src" ]; then
        cp "$shutdown_script_src" "$shutdown_script_dst"
        chmod +x "$shutdown_script_dst"
        msg_ok "Shutdown notification script installed."
    else
        msg_warn "Shutdown script not found at $shutdown_script_src"
    fi
    msg_ok "ProxMenux Monitor beta v${appimage_version} installed."

    if [ "$service_exists" = false ]; then
        return 0
    else
        msg_info "Updating service configuration..."
        update_monitor_service
        
        systemctl start proxmenux-monitor.service
        sleep 2
        if systemctl is-active --quiet proxmenux-monitor.service; then
            update_config "proxmenux_monitor" "beta_updated"
            return 2
        else
            msg_warn "Service failed to restart. Check: journalctl -u proxmenux-monitor"
            update_config "proxmenux_monitor" "failed"
            return 1
        fi
    fi
}

# Update existing service file with new configuration
update_monitor_service() {
    local exec_path="$MONITOR_RUNTIME_DIR/AppRun"

    cat > "$MONITOR_SERVICE_FILE" << EOF
[Unit]
Description=ProxMenux Monitor - Web Dashboard (Beta)
After=network.target
Before=shutdown.target reboot.target halt.target
Conflicts=shutdown.target reboot.target halt.target

[Service]
Type=simple
User=root
WorkingDirectory=$MONITOR_RUNTIME_DIR
ExecStart=$exec_path
ExecStop=/bin/bash $MONITOR_INSTALL_DIR/scripts/shutdown-notify.sh
Restart=on-failure
RestartSec=10
Environment="PORT=$MONITOR_PORT"
TimeoutStopSec=45
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    msg_ok "Service configuration updated."
}

create_monitor_service() {
    msg_info "Creating ProxMenux Monitor service..."
    local exec_path="$MONITOR_RUNTIME_DIR/AppRun"

    if [ -f "$TEMP_DIR/systemd/proxmenux-monitor.service" ]; then
        sed -e "s|^ExecStart=.*|ExecStart=$exec_path|g" \
            -e "s|^WorkingDirectory=.*|WorkingDirectory=$MONITOR_RUNTIME_DIR|g" \
            -e "s|^Environment=.*PORT=.*|Environment=\"PORT=$MONITOR_PORT\"|g" \
            "$TEMP_DIR/systemd/proxmenux-monitor.service" > "$MONITOR_SERVICE_FILE"
        msg_ok "Service file loaded from repository."
    else
        cat > "$MONITOR_SERVICE_FILE" << EOF
[Unit]
Description=ProxMenux Monitor - Web Dashboard (Beta)
After=network.target
Before=shutdown.target reboot.target halt.target
Conflicts=shutdown.target reboot.target halt.target

[Service]
Type=simple
User=root
WorkingDirectory=$MONITOR_RUNTIME_DIR
ExecStart=$exec_path
ExecStop=/bin/bash $MONITOR_INSTALL_DIR/scripts/shutdown-notify.sh
Restart=on-failure
RestartSec=10
Environment="PORT=$MONITOR_PORT"
TimeoutStopSec=45
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
        msg_ok "Default service file created."
    fi

    systemctl daemon-reload
    systemctl enable proxmenux-monitor.service > /dev/null 2>&1
    systemctl start proxmenux-monitor.service > /dev/null 2>&1
    sleep 3

    if systemctl is-active --quiet proxmenux-monitor.service; then
        msg_ok "ProxMenux Monitor service started successfully."
        update_config "proxmenux_monitor" "beta_installed"
        return 0
    else
        msg_warn "ProxMenux Monitor service failed to start."
        echo -e "${TAB}${DARK_GRAY}Check logs : journalctl -u proxmenux-monitor -n 20${CL}"
        echo -e "${TAB}${DARK_GRAY}Check status: systemctl status proxmenux-monitor${CL}"
        update_config "proxmenux_monitor" "failed"
        return 1
    fi
}

# ── Main install ───────────────────────────────────────────
install_beta() {
    local total_steps=4
    local current_step=1

    # ── Step 1: Dependencies ──────────────────────────────
    show_progress $current_step $total_steps "Installing system dependencies"

    if ! command -v jq > /dev/null 2>&1; then
        apt-get update > /dev/null 2>&1
        if apt-get install -y jq > /dev/null 2>&1 && command -v jq > /dev/null 2>&1; then
            update_config "jq" "installed"
        else
            local jq_url="https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64"
            if wget -q -O /usr/local/bin/jq "$jq_url" 2>/dev/null && chmod +x /usr/local/bin/jq \
               && command -v jq > /dev/null 2>&1; then
                update_config "jq" "installed_from_github"
            else
                msg_error "Failed to install jq. Please install it manually and re-run."
                update_config "jq" "failed"
                return 1
            fi
        fi
    else
        update_config "jq" "already_installed"
    fi

    local BASIC_DEPS=("dialog" "curl" "git")
    if [ -z "${APT_UPDATED:-}" ]; then
        apt-get update -y > /dev/null 2>&1 || true
        APT_UPDATED=1
    fi

    for pkg in "${BASIC_DEPS[@]}"; do
        # Strict per-package check — `dpkg -l | grep -qw python3` falsely
        # matches `python3-pip` (the `-` is a word boundary), so dpkg-query
        # for the EXACT package name is the only reliable test.
        # Issue #205.
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
            if apt-get install -y "$pkg" > /dev/null 2>&1; then
                update_config "$pkg" "installed"
            else
                msg_error "Failed to install $pkg. Please install it manually."
                update_config "$pkg" "failed"
                return 1
            fi
        else
            update_config "$pkg" "already_installed"
        fi
    done

    msg_ok "Dependencies installed: jq, dialog, curl, git."

    # ── Step 2: Clone develop branch ─────────────────────
    ((current_step++))
    show_progress $current_step $total_steps "Cloning ProxMenux develop branch"

    msg_info "Cloning branch '${REPO_BRANCH}' from repository..."
    if ! git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$TEMP_DIR" 2>/dev/null; then
        msg_error "Failed to clone branch '$REPO_BRANCH' from $REPO_URL"
        exit 1
    fi
    msg_ok "Repository cloned successfully (branch: ${REPO_BRANCH})."

    # Read beta version if available
    local beta_version="unknown"
    if [ -f "$TEMP_DIR/beta_version.txt" ]; then
        beta_version=$(cat "$TEMP_DIR/beta_version.txt" | tr -d '[:space:]')
    fi

    cd "$TEMP_DIR"

    # ── Step 3: Files ─────────────────────────────────────
    ((current_step++))
    show_progress $current_step $total_steps "Creating directories and copying files"

    mkdir -p "$BASE_DIR" "$INSTALL_DIR"
    [ ! -f "$CONFIG_FILE" ] && echo '{}' > "$CONFIG_FILE"

    # Preserve user/runtime directories that must never be overwritten
    mkdir -p "$BASE_DIR/oci"

    cp "./scripts/utils.sh" "$UTILS_FILE"
    cp "./menu" "$INSTALL_DIR/$MENU_SCRIPT"
    cp "./version.txt" "$LOCAL_VERSION_FILE" 2>/dev/null || true

    # Store beta version marker
    if [ -f "$TEMP_DIR/beta_version.txt" ]; then
        cp "$TEMP_DIR/beta_version.txt" "$BETA_VERSION_FILE"
    else
        echo "$beta_version" > "$BETA_VERSION_FILE"
    fi

    cp "./install_proxmenux.sh" "$BASE_DIR/install_proxmenux.sh" 2>/dev/null || true
    cp "./install_proxmenux_beta.sh" "$BASE_DIR/install_proxmenux_beta.sh" 2>/dev/null || true

    # Wipe the scripts tree before copying so any file removed upstream
    # (renamed, consolidated, deprecated) disappears from the user install.
    # Only $BASE_DIR/scripts/ is cleared; config.json, cache.json,
    # components_status.json, version.txt, beta_version.txt, monitor.db,
    # smart/, oci/ and the AppImage live outside this path and are preserved.
    rm -rf "$BASE_DIR/scripts"
    mkdir -p "$BASE_DIR/scripts"
    cp -r "./scripts/"* "$BASE_DIR/scripts/"
    # Only .sh files need the executable bit. Applying +x recursively would
    # also flag README.md, .json, .py etc. as executable for no reason.
    find "$BASE_DIR/scripts" -type f -name '*.sh' -exec chmod +x {} +

    if [ -d "./oci" ]; then
        mkdir -p "$BASE_DIR/oci"
        cp -r "./oci/"* "$BASE_DIR/oci/" 2>/dev/null || true
    fi
    chmod +x "$INSTALL_DIR/$MENU_SCRIPT"
    [ -f "$BASE_DIR/install_proxmenux.sh" ]      && chmod +x "$BASE_DIR/install_proxmenux.sh"
    [ -f "$BASE_DIR/install_proxmenux_beta.sh" ] && chmod +x "$BASE_DIR/install_proxmenux_beta.sh"

    # Store beta flag in config
    update_config "beta_program" "active"
    update_config "beta_version" "$beta_version"
    update_config "install_branch" "$REPO_BRANCH"

    msg_ok "Files installed. Beta version: ${beta_version}."

    # ── Step 4: Monitor ───────────────────────────────────
    ((current_step++))
    show_progress $current_step $total_steps "Installing ProxMenux Monitor (beta)"

    install_proxmenux_monitor
    local monitor_status=$?

    if [ $monitor_status -eq 0 ]; then
        create_monitor_service
    elif [ $monitor_status -eq 2 ]; then
        msg_ok "ProxMenux Monitor beta updated successfully."
    fi

    # Reset the update indicator flag after successful installation
    reset_update_flag
    
    msg_ok "Beta installation completed."
}

# ── Stable transition notice ───────────────────────────────
check_stable_available() {
    # Called if a stable version is detected (future use by update logic)
    # When main's version.txt > beta_version.txt, the menu/updater can call this
    echo -e "\n${TAB}${BOLD}${GN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${CL}"
    echo -e "${TAB}${BOLD}${GN}  A stable release is now available!${CL}"
    echo -e "${TAB}${WHITE}  To leave the beta program and switch to the stable version,${CL}"
    echo -e "${TAB}${WHITE}  run the official installer:${CL}"
    echo -e ""
    echo -e "${TAB}  ${YWB}bash -c \"\$(wget -qLO - https://raw.githubusercontent.com/MacRimi/ProxMenux/main/install_proxmenux.sh)\"${CL}"
    echo -e ""
    echo -e "${TAB}${DARK_GRAY}  This will cleanly replace your beta install with the stable release.${CL}"
    echo -e "${TAB}${BOLD}${GN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${CL}\n"
}

# ── Entry point ────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RD}[ERROR] This script must be run as root.${CL}"
    exit 1
fi

cleanup_corrupted_files
show_proxmenux_logo
show_beta_welcome

msg_title "Installing ProxMenux Beta — branch: develop"
install_beta

# Load utils if available
[ -f "$UTILS_FILE" ] && source "$UTILS_FILE"

msg_title "ProxMenux Beta installed successfully"

if systemctl is-active --quiet proxmenux-monitor.service; then
    local_ip=$(get_server_ip)
    echo -e "${GN}🌐  ProxMenux Monitor (beta) is running${CL}: ${BL}http://${local_ip}:${MONITOR_PORT}${CL}"
    echo
fi

echo -ne "${GN}"
type_text "To run ProxMenux, execute this command in your terminal:"
echo -e "${YWB}    menu${CL}"
echo
echo -e "${TAB}${DARK_GRAY}Report issues at: https://github.com/MacRimi/ProxMenux/issues${CL}"
echo
exit 0
