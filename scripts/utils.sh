#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 28/01/2025
# ==========================================================
# Description:
# This script provides a set of utility functions used across
# ProxMenux to facilitate Proxmox VE management.
#
# - Defines color codes for consistent output formatting.
# - Implements a spinner-based loading animation.
# - Provides standardized message functions (info, success, error, warning).
# - Handles translation with caching to reduce API requests.
# - Initializes and manages a local cache for improved performance.
# - Loads language settings from a configuration file.
#
# These utilities ensure a streamlined and uniform user experience
# across different ProxMenux scripts.
#
# This script incorporates elements from the 
# Proxmox VE Post Install script from Proxmox VE Helper-Scripts.
#
# Copyright (c) Proxmox VE Helper-Scripts Community
# Script updates can be found at: https://github.com/community-scripts/ProxmoxVE
#
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
#
# ==========================================================

# Repository and directory structure
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
INSTALL_DIR="/usr/local/bin"
BASE_DIR="/usr/local/share/proxmenux"
CONFIG_FILE="$BASE_DIR/config.json"
CACHE_FILE="$BASE_DIR/cache.json"
LOCAL_VERSION_FILE="$BASE_DIR/version.txt"
MENU_SCRIPT="menu"
VENV_PATH="/opt/googletrans-env"
COMPONENTS_STATUS_FILE="$BASE_DIR/components_status.json"


# Translation context
TRANSLATION_CONTEXT="Context: Technical message for Proxmox and IT. Translate:"

# Color and style definitions
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


# Stop the spinner if it is active
cleanup() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null; then 
        kill $SPINNER_PID > /dev/null
    fi
    sleep 1
    if [[ "$LANGUAGE" != "en" ]]; then
        printf "\r\033[K"    
        printf "\e[?25h"
    fi
}

# Display trnaslate message with spinner
msg_lang() {
    local msg="$1"
    echo -ne "${TAB}${YW}${HOLD}${msg}"
    spinner &
    SPINNER_PID=$!
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
    echo -e "${TAB}${BOLD}${YW}${HOLD} ${msg}${CL}"
}

# Display info message with spinner
msg_info3() {
    local msg="$1"
    echo -ne "${TAB}${YW}${HOLD}${msg}${CL}"
}

# Display success message
msg_success() {
    if [ -n "$SPINNER_PID" ] && ps -p $SPINNER_PID > /dev/null; then 
        kill $SPINNER_PID > /dev/null
    fi
    printf "\e[?25h"
    local msg="$1"
    echo -e "${TAB}${BOLD}${BL}${HOLD}${msg}${CL}"
    echo -e ""
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

msg_ok2() {
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
    

# Initialize cache
initialize_cache() {
    if [[ "$LANGUAGE" != "en" ]]; then
        if [ ! -f "$CACHE_FILE" ]; then
            mkdir -p "$(dirname "$CACHE_FILE")"
            echo "{}" > "$CACHE_FILE"
        fi
    fi
}

# Load language
load_language() {
    LANGUAGE="en"
    if [ -f "$CONFIG_FILE" ]; then
        lang_candidate=$(jq -r '.language // empty' "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$lang_candidate" && "$lang_candidate" != "null" ]]; then
            LANGUAGE="$lang_candidate"
        fi
    fi
}



########################################################



translate() {
    local text="$1"
    local dest_lang="$LANGUAGE"


    if [ "$dest_lang" = "en" ]; then
        echo "$text"
        return
    fi

    if [ ! -s "$CACHE_FILE" ] || ! jq -e . "$CACHE_FILE" > /dev/null 2>&1; then
        echo "{}" > "$CACHE_FILE"
    fi

    local cached_translation=$(jq -r --arg text "$text" --arg lang "$dest_lang" '.[$text][$lang] // .[$text]["notranslate"] // empty' "$CACHE_FILE")
    if [ -n "$cached_translation" ]; then
        echo "$cached_translation"
        return
    fi

    if [ ! -d "$VENV_PATH" ]; then
        echo "$text"
        return
    fi

    source "$VENV_PATH/bin/activate"
    local translated
    translated=$(python3 -c "
from googletrans import Translator
import sys, json, re

def translate_text(text, dest_lang, context):
    translator = Translator()
    try:
        full_text = context + ' ' + text
        result = translator.translate(full_text, dest=dest_lang).text
        translated = re.sub(r'^.*?(Translate:|Traducir:|Traduire:|Übersetzen:|Tradurre:|Traduzir:|翻译:|翻訳:)', '', result, flags=re.IGNORECASE | re.DOTALL).strip()
        translated = re.sub(r'^.*?(Context:|Contexto:|Contexte:|Kontext:|Contesto:|上下文：|コンテキスト：).*?:', '', translated, flags=re.IGNORECASE | re.DOTALL).strip()
        print(json.dumps({'success': True, 'text': translated}))
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))

translate_text(
    json.loads(sys.argv[1]),
    sys.argv[2],
    json.loads(sys.argv[3])
)
" "$(jq -Rn --arg t "$text" '$t')" "$dest_lang" "$(jq -Rn --arg ctx "$TRANSLATION_CONTEXT" '$ctx')")
    deactivate

    local translation_result=$(echo "$translated" | jq -r '.')
    local success=$(echo "$translation_result" | jq -r '.success')
    
    if [ "$success" = "true" ]; then
        translated=$(echo "$translation_result" | jq -r '.text')
        
        # Additional cleaning step
        translated=$(echo "$translated" | sed -E 's/^(Context:|Contexto:|Contexte:|Kontext:|Contesto:|上下文：|コンテキスト：).*?(Translate:|Traducir:|Traduire:|Übersetzen:|Tradurre:|Traduzir:|翻译:|翻訳:)//gI' | sed 's/^ *//; s/ *$//')
        
        # Only cache if the language is not English
        if [ "$dest_lang" != "en" ]; then
            local temp_cache=$(mktemp)
            jq --arg text "$text" --arg lang "$dest_lang" --arg translated "$translated" '
                if .[$text] == null then .[$text] = {} else . end |
                .[$text][$lang] = $translated
            ' "$CACHE_FILE" > "$temp_cache" && mv "$temp_cache" "$CACHE_FILE"
        fi
        
        echo "$translated"
    else
        local error=$(echo "$translation_result" | jq -r '.error')
        echo "$text"
    fi
}



########################################################




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


########################################################


ensure_components_status_file() {
  mkdir -p "$BASE_DIR"
  if [[ ! -f "$COMPONENTS_STATUS_FILE" ]] || ! jq empty "$COMPONENTS_STATUS_FILE" >/dev/null 2>&1; then
    echo '{}' > "$COMPONENTS_STATUS_FILE"
  fi
}

update_component_status() {
  local comp="$1"
  local stat="$2"
  local ver="$3"
  local category="$4"
  local extra_json="$5"
  if [ -z "$extra_json" ]; then
    extra_json="{}"
  fi

  ensure_components_status_file

  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local tmp_file
  tmp_file=$(mktemp)

  if jq --arg comp "$comp" \
        --arg stat "$stat" \
        --arg ver "$ver" \
        --arg category "$category" \
        --arg time "$ts" \
        --argjson extra "$extra_json" \
        '.[$comp] = ({status:$stat, version:$ver, category:$category, timestamp:$time} + $extra)' \
        "$COMPONENTS_STATUS_FILE" > "$tmp_file" 2>/dev/null; then
    mv "$tmp_file" "$COMPONENTS_STATUS_FILE"
  else
    rm -f "$tmp_file"
    echo '{}' > "$COMPONENTS_STATUS_FILE"
  fi
}
