#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven toolkit for Proxmox VE management
# ==========================================================
# Author       : MacRimi
# Contributors : cod378
# Subproject   : ProxMenux Monitor (System Health & Web Dashboard)
# Copyright    : (c) 2024-2025 MacRimi
# License      : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version      : 1.4
# Last Updated : 12/11/2025
# ==========================================================
# Description:
# This script installs and configures ProxMenux, a menu-driven
# toolkit for managing and optimizing Proxmox VE servers.
#
# - Ensures the script is run with root privileges.
# - Displays an installation confirmation prompt.
# - Installs required dependencies:
#     • whiptail (interactive terminal menus)
#     • curl (downloads and connectivity checks)
#     • jq (JSON parsing)
#     • Python 3 + venv (for translation support)
# - Creates the ProxMenux base directories and configuration files:
#     • $BASE_DIR/config.json
#     • $BASE_DIR/cache.json
# - Copies local project files into the target paths (offline mode by default):
#     • scripts/*     → $BASE_DIR/scripts/
#     • utils.sh      → $BASE_DIR/scripts/utils.sh
#     • menu          → $INSTALL_DIR/menu (main launcher)
#     • install_proxmenux.sh → $BASE_DIR/install_proxmenux.sh
# - Sets correct permissions for all executables.
# - Displays the final instruction on how to start ProxMenux ("menu").
#
# Notes:
# - This installer supports both offline and online setups.
# - ProxMenux Monitor can be installed later as an optional module
#   to provide real-time system monitoring and a web dashboard.
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
INSTALL_DIR="/usr/local/bin"
BASE_DIR="/usr/local/share/proxmenux"
CONFIG_FILE="$BASE_DIR/config.json"
CACHE_FILE="$BASE_DIR/cache.json"
UTILS_FILE="$BASE_DIR/utils.sh"
LOCAL_VERSION_FILE="$BASE_DIR/version.txt"
MENU_SCRIPT="menu"
VENV_PATH="/opt/googletrans-env"

MONITOR_INSTALL_DIR="$BASE_DIR"
MONITOR_SERVICE_FILE="/etc/systemd/system/proxmenux-monitor.service"
MONITOR_PORT=8008

# Offline installer envs
REPO_URL="https://github.com/MacRimi/ProxMenux.git"
TEMP_DIR="/tmp/proxmenux-install-$$"

# Load utility functions
NEON_PURPLE_BLUE="\033[38;5;99m"
WHITE="\033[38;5;15m" 
RESET="\033[0m"  
DARK_GRAY="\033[38;5;244m"
ORANGE="\033[38;5;208m"
YW="\033[33m"
YWB="\033[1;33m"
GN="\033[1;92m"
RD="\033[01;31m"
CL="\033[m"
BL="\033[36m"
DGN="\e[32m"
BGN="\e[1;32m"
DEF="\e[1;36m"
CUS="\e[38;5;214m"
BOLD="\033[1m"
BFR="\\r\\033[K"
HOLD="-"
BOR=" | "
CM="${GN}✓ ${CL}"
TAB="    "   


# Create and display spinner
spinner() {
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local spin_i=0
    local interval=0.1
    printf "\e[?25l"
    
    local color="${YW}"
    
    while true; do
        printf "\r ${color}%s${CL}" "${frames[spin_i]}"
        spin_i=$(( (spin_i + 1) % ${#frames[@]} ))
        sleep "$interval"
    done
}


# Function to simulate typing effect
type_text() {
    local text="$1"
    local delay=0.05
    for ((i=0; i<${#text}; i++)); do
        echo -n "${text:$i:1}"
        sleep $delay
    done
    echo
}


# Display info message with spinner
msg_info() {
    local msg="$1"
    echo -ne "${TAB}${YW}${HOLD}${msg}"
    spinner &
    SPINNER_PID=$!
}


# Display info2 message
msg_info2() {
    local msg="$1"
    echo -e "${TAB}${BOLD}${YW}${HOLD}${msg}${CL}"
}



# Display title script
msg_title() {
    local msg="$1"
    echo -e "\n"
    echo -e "${TAB}${BOLD}${HOLD}${BOR}${msg}${BOR}${HOLD}${CL}"
    echo -e "\n"
}


# Display warning or highlighted information message
msg_warn() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null; then 
        kill $SPINNER_PID > /dev/null
    fi
    printf "\e[?25h"
    local msg="$1"
    echo -e "${BFR}${TAB}${CL} ${YWB}${msg}${CL}"
}


# Display success message
msg_ok() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null; then 
        kill $SPINNER_PID > /dev/null
    fi
    printf "\e[?25h"
    local msg="$1"
    echo -e "${BFR}${TAB}${CM}${GN}${msg}${CL}"
}


# Display error message
msg_error() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null; then 
        kill $SPINNER_PID > /dev/null
    fi
    printf "\e[?25h"
    local msg="$1"
    echo -e "${BFR}${TAB}${RD}[ERROR] ${msg}${CL}"
}
    



show_proxmenux_logo() {
clear

if [[ -z "$SSH_TTY" && -z "$(who am i | awk '{print $NF}' | grep -E '([0-9]{1,3}\.){3}[0-9]{1,3}')" ]]; then

# Logo for terminal noVNC

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
    ""
    ""
    ""
)


mapfile -t logo_lines <<< "$LOGO"

for i in {0..9}; do
    echo -e "${TAB}${logo_lines[i]}  ${WHITE}│${RESET}  ${TEXT[i]}"
done
echo -e

else


# Logo for terminal SSH     
TEXT=(
    ""
    ""
    ""
    ""
    "${BOLD}ProxMenux${RESET}"
    ""
    "${BOLD}${NEON_PURPLE_BLUE}An Interactive Menu for${RESET}"
    "${BOLD}${NEON_PURPLE_BLUE}Proxmox VE management${RESET}"
    ""
    ""
    ""
    ""
    ""
    ""
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

# ==========================================================





cleanup_corrupted_files() {
    if [ -f "$CONFIG_FILE" ] && ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "Cleaning up corrupted configuration file..."
        rm -f "$CONFIG_FILE"
    fi
    if [ -f "$CACHE_FILE" ] && ! jq empty "$CACHE_FILE" >/dev/null 2>&1; then
        echo "Cleaning up corrupted cache file..."
        rm -f "$CACHE_FILE"
    fi
}

# Cleanup function
cleanup() {
    if [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}

# Set trap to ensure cleanup on exit
trap cleanup EXIT


# ==========================================================
check_existing_installation() {
    local has_venv=false
    local has_config=false
    local has_language=false
    local has_menu=false
    
    if [ -f "$INSTALL_DIR/$MENU_SCRIPT" ]; then
        has_menu=true
    fi
    
    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/activate" ]; then
        has_venv=true
    fi
    
    if [ -f "$CONFIG_FILE" ]; then
        if jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
            has_config=true
            local current_language=$(jq -r '.language // empty' "$CONFIG_FILE" 2>/dev/null)
            if [[ -n "$current_language" && "$current_language" != "null" && "$current_language" != "empty" ]]; then
                has_language=true
            fi
        else
            echo "Warning: Corrupted config file detected, removing..."
            rm -f "$CONFIG_FILE"
        fi
    fi
    
    if [ "$has_venv" = true ] && [ "$has_language" = true ]; then
        echo "translation"
    elif [ "$has_menu" = true ] && [ "$has_venv" = false ]; then
        echo "normal"
    elif [ "$has_menu" = true ]; then
        echo "unknown"
    else
        echo "none"
    fi
}

uninstall_proxmenux() {
    local install_type="$1"
    local force_clean="$2"
    
    if [ "$force_clean" != "force" ]; then
        if ! whiptail --title "Uninstall ProxMenux" --yesno "Are you sure you want to uninstall ProxMenux?" 10 60; then
            return 1
        fi
    fi
    
    echo "Uninstalling ProxMenux..."
    
    if systemctl is-active --quiet proxmenux-monitor.service; then
        echo "Stopping ProxMenux Monitor service..."
        systemctl stop proxmenux-monitor.service
    fi
    
    if systemctl is-enabled --quiet proxmenux-monitor.service 2>/dev/null; then
        echo "Disabling ProxMenux Monitor service..."
        systemctl disable proxmenux-monitor.service
    fi
    
    if [ -f "$MONITOR_SERVICE_FILE" ]; then
        echo "Removing ProxMenux Monitor service file..."
        rm -f "$MONITOR_SERVICE_FILE"
        systemctl daemon-reload
    fi
    
    if [ -d "$MONITOR_INSTALL_DIR" ]; then
        echo "Removing ProxMenux Monitor directory..."
        rm -rf "$MONITOR_INSTALL_DIR"
    fi
    
    if [ -f "$VENV_PATH/bin/activate" ]; then
        echo "Removing googletrans and virtual environment..."
        source "$VENV_PATH/bin/activate"
        pip uninstall -y googletrans >/dev/null 2>&1
        deactivate
        rm -rf "$VENV_PATH"
    fi
    
    if [ "$install_type" = "translation" ] && [ "$force_clean" != "force" ]; then
        DEPS_TO_REMOVE=$(whiptail --title "Remove Translation Dependencies" --checklist \
            "Select translation-specific dependencies to remove:" 15 60 3 \
            "python3-venv" "Python virtual environment" OFF \
            "python3-pip" "Python package installer" OFF \
            "python3" "Python interpreter" OFF \
            3>&1 1>&2 2>&3)
        
        if [ -n "$DEPS_TO_REMOVE" ]; then
            echo "Removing selected dependencies..."
            read -r -a DEPS_ARRAY <<< "$(echo "$DEPS_TO_REMOVE" | tr -d '"')"
            for dep in "${DEPS_ARRAY[@]}"; do
                echo "Removing $dep..."
                apt-mark auto "$dep" >/dev/null 2>&1
                apt-get -y --purge autoremove "$dep" >/dev/null 2>&1
            done
            apt-get autoremove -y --purge >/dev/null 2>&1
        fi
    fi
    
    rm -f "$INSTALL_DIR/$MENU_SCRIPT"
    rm -rf "$BASE_DIR"
    
    [ -f /root/.bashrc.bak ] && mv /root/.bashrc.bak /root/.bashrc
    if [ -f /etc/motd.bak ]; then
        mv /etc/motd.bak /etc/motd
    else
        sed -i '/This system is optimised by: ProxMenux/d' /etc/motd
    fi
    
    echo "ProxMenux has been uninstalled."
    return 0
}

handle_installation_change() {
    local current_type="$1"
    local new_type="$2"
    
    if [ "$current_type" = "$new_type" ]; then
        return 0
    fi
    
    case "$current_type-$new_type" in
        "translation-1"|"translation-normal")
            if whiptail --title "Installation Type Change" \
                --yesno "Switch from Translation to Normal Version?\n\nThis will remove translation components." 10 60; then
                echo "Preparing for installation type change..."
                uninstall_proxmenux "translation" "force" >/dev/null 2>&1
                return 0
            else
                return 1
            fi
            ;;
        "normal-2"|"normal-translation")
            if whiptail --title "Installation Type Change" \
                --yesno "Switch from Normal to Translation Version?\n\nThis will add translation components." 10 60; then
                return 0
            else
                return 1
            fi
            ;;
        *)
            return 0
            ;;
    esac
}

update_config() {
    local component="$1"
    local status="$2"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    local tracked_components=("dialog" "curl" "jq" "python3" "python3-venv" "python3-pip" "virtual_environment" "pip" "googletrans" "proxmenux_monitor")
    
    if [[ " ${tracked_components[@]} " =~ " ${component} " ]]; then
        mkdir -p "$(dirname "$CONFIG_FILE")"
        
        if [ ! -f "$CONFIG_FILE" ] || ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
            echo '{}' > "$CONFIG_FILE"
        fi
        
        local tmp_file=$(mktemp)
        if jq --arg comp "$component" --arg stat "$status" --arg time "$timestamp" \
           '.[$comp] = {status: $stat, timestamp: $time}' "$CONFIG_FILE" > "$tmp_file" 2>/dev/null; then
            mv "$tmp_file" "$CONFIG_FILE"
        else
            echo '{}' > "$CONFIG_FILE"
            jq --arg comp "$component" --arg stat "$status" --arg time "$timestamp" \
               '.[$comp] = {status: $stat, timestamp: $time}' "$CONFIG_FILE" > "$tmp_file" && mv "$tmp_file" "$CONFIG_FILE"
        fi
        
        [ -f "$tmp_file" ] && rm -f "$tmp_file"
    fi
}

show_progress() {
    local step="$1"
    local total="$2"
    local message="$3"
    
    echo -e "\n${BOLD}${BL}${TAB}Installing ProxMenux: Step $step of $total${CL}"
    echo
    msg_info2 "$message"
}

select_language() {
    if [ -f "$CONFIG_FILE" ] && jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        local existing_language=$(jq -r '.language // empty' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$existing_language" && "$existing_language" != "null" && "$existing_language" != "empty" ]]; then
            LANGUAGE="$existing_language"
            msg_ok "Using existing language configuration: $LANGUAGE"
            return 0
        fi
    fi
    
    LANGUAGE=$(whiptail --title "Select Language" --menu "Choose a language for the menu:" 20 60 12 \
        "en" "English (Recommended)" \
        "es" "Spanish" \
        "fr" "French" \
        "de" "German" \
        "it" "Italian" \
        "pt" "Portuguese" 3>&1 1>&2 2>&3)
    
    if [ -z "$LANGUAGE" ]; then
        msg_error "No language selected. Exiting."
        exit 1
    fi
    
    mkdir -p "$(dirname "$CONFIG_FILE")"
    
    if [ ! -f "$CONFIG_FILE" ] || ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        echo '{}' > "$CONFIG_FILE"
    fi
    
    local tmp_file=$(mktemp)
    if jq --arg lang "$LANGUAGE" '. + {language: $lang}' "$CONFIG_FILE" > "$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$CONFIG_FILE"
    else
        echo "{\"language\": \"$LANGUAGE\"}" > "$CONFIG_FILE"
    fi
    
    [ -f "$tmp_file" ] && rm -f "$tmp_file"
    
    msg_ok "Language set to: $LANGUAGE"
}

# Show installation confirmation for new installations
show_installation_confirmation() {
    local install_type="$1"
    
    case "$install_type" in
        "1")
            if whiptail --title "ProxMenux - Normal Version Installation" \
                --yesno "ProxMenux Normal Version will install:\n\n• dialog  (interactive menus) - Official Debian package\n• curl       (file downloads) - Official Debian package\n• jq        (JSON processing) - Official Debian package\n• ProxMenux core files     (/usr/local/share/proxmenux)\n• ProxMenux Monitor        (Web dashboard on port 8008)\n\nThis is a lightweight installation with minimal dependencies.\n\nProceed with installation?" 20 70; then
                return 0
            else
                return 1
            fi
            ;;
        "2")
            if whiptail --title "ProxMenux - Translation Version Installation" \
                --yesno "ProxMenux Translation Version will install:\n\n• dialog (interactive menus)\n• curl (file downloads)\n• jq (JSON processing)\n• python3 + python3-venv + python3-pip\n• Google Translate library (googletrans)\n• Virtual environment (/opt/googletrans-env)\n• Translation cache system\n• ProxMenux core files\n• ProxMenux Monitor        (Web dashboard on port 8008)\n\nThis version requires more dependencies for translation support.\n\nProceed with installation?" 20 70; then
                return 0
            else
                return 1
            fi
            ;;
    esac
}

get_server_ip() {
    local ip
    # Try to get the primary IP address
    ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+')
    
    if [ -z "$ip" ]; then
        # Fallback: get first non-loopback IP
        ip=$(hostname -I | awk '{print $1}')
    fi
    
    if [ -z "$ip" ]; then
        # Last resort: use localhost
        ip="localhost"
    fi
    
    echo "$ip"
}

detect_latest_appimage() {
    local appimage_dir="$TEMP_DIR/AppImage"
    
    if [ ! -d "$appimage_dir" ]; then
        return 1
    fi
    
    local latest_appimage=$(find "$appimage_dir" -name "ProxMenux-*.AppImage" -type f | sort -V | tail -1)
    
    if [ -z "$latest_appimage" ]; then
        return 1
    fi
    
    echo "$latest_appimage"
    return 0
}

get_appimage_version() {
    local appimage_path="$1"
    local filename=$(basename "$appimage_path")
    
    local version=$(echo "$filename" | grep -oP 'ProxMenux-\K[0-9]+\.[0-9]+\.[0-9]+')
    
    echo "$version"
}

install_proxmenux_monitor() {
    local appimage_source=$(detect_latest_appimage)
    
    if [ -z "$appimage_source" ] || [ ! -f "$appimage_source" ]; then
        msg_error "ProxMenux Monitor AppImage not found in $TEMP_DIR/AppImage/"
        msg_warn "Please ensure the AppImage directory exists with ProxMenux-*.AppImage files."
        update_config "proxmenux_monitor" "appimage_not_found"
        return 1
    fi
    
    local appimage_version=$(get_appimage_version "$appimage_source")
    
    if systemctl is-active --quiet proxmenux-monitor.service; then
        systemctl stop proxmenux-monitor.service
    fi
    
    local service_exists=false
    if [ -f "$MONITOR_SERVICE_FILE" ]; then
        service_exists=true
    fi
    
    local sha256_file="$TEMP_DIR/AppImage/ProxMenux-Monitor.AppImage.sha256"
    
    if [ -f "$sha256_file" ]; then
        msg_info "Verifying AppImage integrity..."
        local expected_hash=$(cat "$sha256_file" | grep -Eo '^[a-f0-9]+' | tr -d '\n')
        local actual_hash=$(sha256sum "$appimage_source" | awk '{print $1}')
        
        if [ "$expected_hash" != "$actual_hash" ]; then
            msg_error "SHA256 verification failed! AppImage may be corrupted."
            return 1
        fi
        msg_ok "SHA256 verification passed."
    else
        msg_warn "SHA256 checksum not available. Skipping verification."
    fi
    
    msg_info "Installing ProxMenux Monitor..."
    mkdir -p "$MONITOR_INSTALL_DIR"
    
    local target_path="$MONITOR_INSTALL_DIR/ProxMenux-Monitor.AppImage"
    cp "$appimage_source" "$target_path"
    chmod +x "$target_path"
    
    msg_ok "ProxMenux Monitor v$appimage_version installed."
    
    if [ "$service_exists" = false ]; then
        return 0  # New installation - service needs to be created
    else

        systemctl start proxmenux-monitor.service
        sleep 2
        
        if systemctl is-active --quiet proxmenux-monitor.service; then

            update_config "proxmenux_monitor" "updated"
            return 2  # Update successful
        else
            msg_warn "Service failed to restart. Check: journalctl -u proxmenux-monitor"
            update_config "proxmenux_monitor" "failed"
            return 1
        fi
    fi
}

create_monitor_service() {
    msg_info "Creating ProxMenux Monitor service..."
    
    local exec_path="$MONITOR_INSTALL_DIR/ProxMenux-Monitor.AppImage"
    
    if [ -f "$TEMP_DIR/systemd/proxmenux-monitor.service" ]; then
        sed "s|ExecStart=.*|ExecStart=$exec_path|g" \
            "$TEMP_DIR/systemd/proxmenux-monitor.service" > "$MONITOR_SERVICE_FILE"
        msg_ok "Using service file from repository."
    else
        cat > "$MONITOR_SERVICE_FILE" << EOF
[Unit]
Description=ProxMenux Monitor - Web Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$MONITOR_INSTALL_DIR
ExecStart=$exec_path
Restart=on-failure
RestartSec=10
Environment="PORT=$MONITOR_PORT"

[Install]
WantedBy=multi-user.target
EOF
        msg_ok "Created default service file."
    fi

    systemctl daemon-reload
    systemctl enable proxmenux-monitor.service > /dev/null 2>&1
    systemctl start proxmenux-monitor.service > /dev/null 2>&1
    
    sleep 3
    
    if systemctl is-active --quiet proxmenux-monitor.service; then
        msg_ok "ProxMenux Monitor service started successfully."
        update_config "proxmenux_monitor" "installed"
        return 0
    else
        msg_warn "ProxMenux Monitor service failed to start."
        msg_info "Check logs with: journalctl -u proxmenux-monitor -n 20"
        msg_info "Check status with: systemctl status proxmenux-monitor"
        update_config "proxmenux_monitor" "failed"
        return 1
    fi
}

install_normal_version() {
    local total_steps=5
    local current_step=1
    
    show_progress $current_step $total_steps "Installing basic dependencies."
    
    if ! command -v jq > /dev/null 2>&1; then
        apt-get update > /dev/null 2>&1
        
        if apt-get install -y jq > /dev/null 2>&1 && command -v jq > /dev/null 2>&1; then
            update_config "jq" "installed"
        else
            local jq_url="https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64"
            if wget -q -O /usr/local/bin/jq "$jq_url" 2>/dev/null && chmod +x /usr/local/bin/jq; then
                if command -v jq > /dev/null 2>&1; then
                    update_config "jq" "installed_from_github"
                else
                    msg_error "Failed to install jq. Please install it manually."
                    update_config "jq" "failed"
                    return 1
                fi
            else
                msg_error "Failed to install jq from both APT and GitHub. Please install it manually."
                update_config "jq" "failed"
                return 1
            fi
        fi
    else
        update_config "jq" "already_installed"
    fi
    
    BASIC_DEPS=("dialog" "curl" "git")
    for pkg in "${BASIC_DEPS[@]}"; do
        if ! dpkg -l | grep -qw "$pkg"; then
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
    
    msg_ok "jq, dialog, curl and git installed successfully."

    ((current_step++))

    show_progress $current_step $total_steps "Install ProxMenux repository"
    msg_info "Cloning ProxMenux repositoryy."
    if ! git clone --depth 1 "$REPO_URL" "$TEMP_DIR" 2>/dev/null; then
        msg_error "Failed to clone repository from $REPO_URL"
        exit 1
    fi

    msg_ok "Repository cloned successfully."

    cd "$TEMP_DIR"

    ((current_step++))
    
    show_progress $current_step $total_steps "Creating directories and configuration"
    
    mkdir -p "$BASE_DIR"
    mkdir -p "$INSTALL_DIR"
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo '{}' > "$CONFIG_FILE"
    fi
    
    msg_ok "Directories and configuration created."
    ((current_step++))
    
    show_progress $current_step $total_steps "Copying necessary files"
    
    cp "./scripts/utils.sh" "$UTILS_FILE"
    cp "./menu" "$INSTALL_DIR/$MENU_SCRIPT"
    cp "./version.txt" "$LOCAL_VERSION_FILE"
    cp "./install_proxmenux.sh" "$BASE_DIR/install_proxmenux.sh"

    mkdir -p "$BASE_DIR/scripts"
    cp -r "./scripts/"* "$BASE_DIR/scripts/"
    chmod -R +x "$BASE_DIR/scripts/"
    chmod +x "$BASE_DIR/install_proxmenux.sh"
    msg_ok "Necessary files created."

    chmod +x "$INSTALL_DIR/$MENU_SCRIPT"
    
    ((current_step++))
    show_progress $current_step $total_steps "Installing ProxMenux Monitor"
    
    install_proxmenux_monitor
    local monitor_status=$?
    
    if [ $monitor_status -eq 0 ]; then
        create_monitor_service
    fi
    
    msg_ok "ProxMenux Normal Version installation completed successfully."
}

install_translation_version() {
    local total_steps=5
    local current_step=1
    
    show_progress $current_step $total_steps "Language selection"
    select_language
    ((current_step++))
    
    show_progress $current_step $total_steps "Installing system dependencies"
    
    if ! command -v jq > /dev/null 2>&1; then
        apt-get update > /dev/null 2>&1
        
        if apt-get install -y jq > /dev/null 2>&1 && command -v jq > /dev/null 2>&1; then
            update_config "jq" "installed"
        else
            local jq_url="https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64"
            if wget -q -O /usr/local/bin/jq "$jq_url" 2>/dev/null && chmod +x /usr/local/bin/jq; then
                if command -v jq > /dev/null 2>&1; then
                    update_config "jq" "installed_from_github"
                else
                    msg_error "Failed to install jq. Please install it manually."
                    update_config "jq" "failed"
                    return 1
                fi
            else
                msg_error "Failed to install jq from both APT and GitHub. Please install it manually."
                update_config "jq" "failed"
                return 1
            fi
        fi
    else
        update_config "jq" "already_installed"
    fi
    
    DEPS=("dialog" "curl" "git" "python3" "python3-venv" "python3-pip")
    for pkg in "${DEPS[@]}"; do
        if ! dpkg -l | grep -qw "$pkg"; then
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
    
    msg_ok "jq, dialog, curl, git, python3, python3-venv and python3-pip installed successfully."
    
    ((current_step++))
    
    show_progress $current_step $total_steps "Setting up translation environment"
    
    if [ ! -d "$VENV_PATH" ] || [ ! -f "$VENV_PATH/bin/activate" ]; then
        python3 -m venv --system-site-packages "$VENV_PATH" > /dev/null 2>&1
        if [ ! -f "$VENV_PATH/bin/activate" ]; then
            msg_error "Failed to create virtual environment. Please check your Python installation."
            update_config "virtual_environment" "failed"
            return 1
        else
            update_config "virtual_environment" "created"
        fi
    else
        update_config "virtual_environment" "already_exists"
    fi
    
    source "$VENV_PATH/bin/activate"
    
    if pip install --upgrade pip > /dev/null 2>&1; then
        update_config "pip" "upgraded"
    else
        msg_error "Failed to upgrade pip."
        update_config "pip" "upgrade_failed"
        return 1
    fi
    
    if pip install --break-system-packages --no-cache-dir googletrans==4.0.0-rc1 > /dev/null 2>&1; then
        update_config "googletrans" "installed"
    else
        msg_error "Failed to install googletrans. Please check your internet connection."
        update_config "googletrans" "failed"
        deactivate
        return 1
    fi
    
    deactivate
    
    show_progress $current_step $total_steps "Cloning ProxMenux repository"
    if ! git clone --depth 1 "$REPO_URL" "$TEMP_DIR" 2>/dev/null; then
        msg_error "Failed to clone repository from $REPO_URL"
        exit 1
    fi
    msg_ok "Repository cloned successfully."
    
    cd "$TEMP_DIR"
    
    ((current_step++))
    
    show_progress $current_step $total_steps "Copying necessary files"
    
    mkdir -p "$BASE_DIR"
    mkdir -p "$INSTALL_DIR"
    
    cp "./json/cache.json" "$CACHE_FILE"
    msg_ok "Cache file copied with translations."
    
    cp "./scripts/utils.sh" "$UTILS_FILE"
    cp "./menu" "$INSTALL_DIR/$MENU_SCRIPT"
    cp "./version.txt" "$LOCAL_VERSION_FILE"
    cp "./install_proxmenux.sh" "$BASE_DIR/install_proxmenux.sh"
    
    mkdir -p "$BASE_DIR/scripts"
    cp -r "./scripts/"* "$BASE_DIR/scripts/"
    chmod -R +x "$BASE_DIR/scripts/"
    chmod +x "$BASE_DIR/install_proxmenux.sh"
    msg_ok "Necessary files created."
    
    chmod +x "$INSTALL_DIR/$MENU_SCRIPT"
    
    ((current_step++))
    show_progress $current_step $total_steps "Installing ProxMenux Monitor"
    
    install_proxmenux_monitor
    local monitor_status=$?
    
    if [ $monitor_status -eq 0 ]; then
        create_monitor_service
    elif [ $monitor_status -eq 2 ]; then
        msg_ok "ProxMenux Monitor updated successfully."
    fi
    
    msg_ok "ProxMenux Translation Version installation completed successfully."
}

show_installation_options() {
    local current_install_type
    current_install_type=$(check_existing_installation)
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)
    
    local menu_title="ProxMenux Installation"
    local menu_text="Choose installation type:"
    
    if [ "$current_install_type" != "none" ]; then
        case "$current_install_type" in
            "translation")
                menu_title="ProxMenux Update - Translation Version Detected"
                ;;
            "normal")
                menu_title="ProxMenux Update - Normal Version Detected"
                ;;
            "unknown")
                menu_title="ProxMenux Update - Existing Installation Detected"
                ;;
        esac
    fi
    
    if [[ "$pve_version" -ge 9 ]]; then
        INSTALL_TYPE=$(whiptail --backtitle "ProxMenux" --title "$menu_title" --menu "\n$menu_text" 14 70 2 \
            "1" "Normal Version      (English only)" 3>&1 1>&2 2>&3)
        
        if [ -z "$INSTALL_TYPE" ]; then
            show_proxmenux_logo
            msg_warn "Installation cancelled."
            exit 1
        fi
    else
        INSTALL_TYPE=$(whiptail --backtitle "ProxMenux" --title "$menu_title" --menu "\n$menu_text" 14 70 2 \
            "1" "Normal Version      (English only)" \
            "2" "Translation Version (Multi-language support)" 3>&1 1>&2 2>&3)
        
        if [ -z "$INSTALL_TYPE" ]; then
            show_proxmenux_logo
            msg_warn "Installation cancelled."
            exit 1
        fi
    fi
    
    if [ -z "$INSTALL_TYPE" ]; then
        show_proxmenux_logo
        msg_warn "Installation cancelled."
        exit 1
    fi
    
    if [ "$current_install_type" = "none" ]; then
        if ! show_installation_confirmation "$INSTALL_TYPE"; then
            show_proxmenux_logo
            msg_warn "Installation cancelled."
            exit 1
        fi
    fi
    
    if ! handle_installation_change "$current_install_type" "$INSTALL_TYPE"; then
        show_proxmenux_logo
        msg_warn "Installation cancelled."
        exit 1
    fi
}

install_proxmenux() {
    show_installation_options
    
    case "$INSTALL_TYPE" in
        "1")
            show_proxmenux_logo
            msg_title "Installing ProxMenux - Normal Version"
            install_normal_version
            ;;
        "2")
            show_proxmenux_logo
            msg_title "Installing ProxMenux - Translation Version"
            install_translation_version
            ;;
        *)
            msg_error "Invalid option selected."
            exit 1
            ;;
    esac

    if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
    fi
    
    msg_title "ProxMenux has been installed successfully"
    
    if systemctl is-active --quiet proxmenux-monitor.service; then
        local server_ip=$(get_server_ip)
        echo -e "${GN}🌐  ProxMenux Monitor activated${CL}: ${BL}http://${server_ip}:${MONITOR_PORT}${CL}"
        echo
    fi
    
    echo -ne "${GN}"
    type_text "To run ProxMenux, simply execute this command in the console or terminal:"
    echo -e "${YWB}    menu${CL}"
    echo
    # -------
    exit 0
}

if [ "$(id -u)" -ne 0 ]; then
    msg_error "This script must be run as root."
    exit 1
fi

cleanup_corrupted_files
install_proxmenux
