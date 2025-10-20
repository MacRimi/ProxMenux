#!/usr/bin/env bash

# ==========================================================
# ProxMenux - UUP Dump ISO Creator
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 07/05/2025
# ==========================================================
# Description:
# This script is part of the ProxMenux tools for Proxmox VE.
# It allows downloading and converting official Windows ISO images 
# from UUP Dump using a shared link (with ID, pack, and edition).
#
# Key features:
# - Automatically installs and verifies required dependencies (aria2c, cabextract, wimlib-imagex…)
# - Downloads the selected Windows edition from UUP Dump using aria2
# - Converts the downloaded files into a bootable ISO
# - Stores the resulting ISO in the default template path (/var/lib/vz/template/iso)
# - Provides a graphical prompt via whiptail for user-friendly usage
#
# This tool simplifies the creation of official Windows ISOs
# for use in virtual machines within Proxmox VE.
# ==========================================================

BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================


detect_iso_dir() {
  for store in $(pvesm status -content iso | awk 'NR>1 {print $1}'); do
    for ext in iso img; do
      volid=$(pvesm list "$store" --content iso | awk -v ext="$ext" 'NR>1 && $2 ~ ext {print $1; exit}')
      if [[ -n "$volid" ]]; then
        path=$(pvesm path "$volid" 2>/dev/null)
        dir=$(dirname "$path")
        [[ -d "$dir" ]] && echo "$dir" && return 0
      fi
    done
  done

  if [[ -d /var/lib/vz/template/iso ]]; then
    echo "/var/lib/vz/template/iso"
    return 0
  fi

  return 1
}


function run_uupdump_creator() {


    local DEPS=(curl aria2 cabextract wimtools genisoimage chntpw)
    local CMDS=(curl aria2c cabextract wimlib-imagex genisoimage chntpw)
    local MISSING=()
    local FAILED=()

    for i in "${!CMDS[@]}"; do
        if ! command -v "${CMDS[$i]}" &>/dev/null; then
            MISSING+=("${DEPS[$i]}")
        fi
    done

    if [[ ${#MISSING[@]} -gt 0 ]]; then
        show_proxmenux_logo
        msg_info "$(translate "Installing dependencies: ${MISSING[*]}")"
        apt-get update -qq >/dev/null 2>&1
        if ! apt-get install -y "${MISSING[@]}" >/dev/null 2>&1; then
            msg_error "$(translate "Failed to install: ${MISSING[*]}")"
            sleep 2
            exit 1
        fi
        msg_ok "$(translate "All dependencies installed and verified.")"
    fi

    for i in "${!CMDS[@]}"; do
        if ! command -v "${CMDS[$i]}" &>/dev/null; then
            FAILED+=("${CMDS[$i]}")
        fi
    done

    if [[ ${#FAILED[@]} -gt 0 ]]; then
        show_proxmenux_logo
        msg_error "$(translate "Missing commands after installation:") ${FAILED[*]}"
        sleep 2
        exit 1
    fi



ISO_DIR=$(detect_iso_dir)
if [[ -z "$ISO_DIR" ]]; then
  show_proxmenux_logo
  msg_error "$(translate "Could not determine a valid ISO storage directory.")"
  sleep 2
  exit 1
fi


mkdir -p "$ISO_DIR"



DEFAULT_BASE="/root/uup-temp"
BASE_INPUT=$(dialog --clear --inputbox "$(translate "Enter base folder for temporary files and converter (default:") $DEFAULT_BASE):" 10 60 "$DEFAULT_BASE" 3>&1 1>&2 2>&3)

if [[ $? -ne 0 || -z "$BASE_INPUT" ]]; then
  BASE_INPUT="$DEFAULT_BASE"
fi


BASE_CLEAN="$(echo "$BASE_INPUT" | sed 's:[[:space:]]*$::' | sed 's:/*$::')"


if [[ ! -d "$BASE_CLEAN" ]]; then
  if ! mkdir -p "$BASE_CLEAN"; then
    show_proxmenux_logo
    msg_error "$(translate "The selected base folder does not exist and could not be created:") $BASE_CLEAN"
    sleep 2
    exit 1
  fi
fi
if [[ ! -w "$BASE_CLEAN" ]]; then
  show_proxmenux_logo
  msg_error "$(translate "No write permissions on:") $BASE_CLEAN"
  sleep 2
  exit 1
fi


TMP_DIR="$BASE_CLEAN/uup-temp"
OUT_DIR="$ISO_DIR"
CONVERTER="$BASE_CLEAN/uup-converter"

if ! mkdir -p "$TMP_DIR"; then
  show_proxmenux_logo
  msg_error "$(translate "Could not create temporary directory:") $TMP_DIR"
  sleep 2
  exit 1
fi

if ! mkdir -p "$CONVERTER"; then
  show_proxmenux_logo
  msg_error "$(translate "Could not create converter directory:") $CONVERTER"
  sleep 2
  exit 1
fi

cd "$TMP_DIR" || { msg_error "$(translate "Failed to access:") $TMP_DIR"; exit 1; }



UUP_URL=$(whiptail --inputbox "$(translate "Paste the UUP Dump URL here")" 10 90 3>&1 1>&2 2>&3)
if [[ $? -ne 0 || -z "$UUP_URL" ]]; then
  return 1  
fi

if [[ ! "$UUP_URL" =~ id=.+\&pack=.+\&edition=.+ ]]; then
  show_proxmenux_logo
  msg_error "$(translate "The URL does not contain the required parameters (id, pack, edition).")"
  sleep 2
  return 1 
fi


BUILD_ID=$(echo "$UUP_URL" | grep -oP 'id=\K[^&]+')
LANG=$(echo "$UUP_URL" | grep -oP 'pack=\K[^&]+')
EDITION=$(echo "$UUP_URL" | grep -oP 'edition=\K[^&]+')
ARCH="amd64"

show_proxmenux_logo
echo -e
echo -e "\n${BGN}=============== UUP Dump Creator ===============${CL}"
echo -e "    ${BGN}🆔 ID:${CL} ${DGN}$BUILD_ID${CL}"
echo -e "    ${BGN}🌐 Language:${CL} ${DGN}$LANG${CL}"
echo -e "    ${BGN}💿 Edition:${CL} ${DGN}$EDITION${CL}"
echo -e "    ${BGN}🖥️ Architecture:${CL} ${DGN}$ARCH${CL}"
echo -e "${BGN}===============================================${CL}\n"


if [[ ! -f "$CONVERTER/convert.sh" ]]; then
  echo "📦 $(translate "Downloading UUP converter...")"
  mkdir -p "$CONVERTER"
  cd "$CONVERTER" || exit 1
  wget -q https://git.uupdump.net/uup-dump/converter/archive/refs/heads/master.tar.gz -O converter.tar.gz
  tar -xzf converter.tar.gz --strip-components=1
  chmod +x convert.sh
  cd "$TMP_DIR" || exit 1
fi


cat > uup_download_linux.sh <<EOF
#!/bin/bash
mkdir -p files
echo "https://git.uupdump.net/uup-dump/converter/archive/refs/heads/master.tar.gz" > files/converter_multi

for prog in aria2c cabextract wimlib-imagex chntpw; do
  which \$prog &>/dev/null || { echo "\$prog not found."; exit 1; }
done
which genisoimage &>/dev/null || which mkisofs &>/dev/null || { echo "genisoimage/mkisofs not found."; exit 1; }

destDir="UUPs"
tempScript="aria2_script.\$RANDOM.txt"

aria2c --no-conf --console-log-level=warn --log-level=info --log="aria2_download.log" \
  -x16 -s16 -j2 --allow-overwrite=true --auto-file-renaming=false -d"files" -i"files/converter_multi" || exit 1

aria2c --no-conf --console-log-level=warn --log-level=info --log="aria2_download.log" \
  -o"\$tempScript" --allow-overwrite=true --auto-file-renaming=false \
  "https://uupdump.net/get.php?id=$BUILD_ID&pack=$LANG&edition=$EDITION&aria2=2" || exit 1

grep '#UUPDUMP_ERROR:' "\$tempScript" && { echo "❌ Error generating UUP download list."; exit 1; }

aria2c --no-conf --console-log-level=warn --log-level=info --log="aria2_download.log" \
  -x16 -s16 -j5 -c -R -d"\$destDir" -i"\$tempScript" || exit 1
EOF

chmod +x uup_download_linux.sh



# ==========================
./uup_download_linux.sh
# ==========================



UUP_FOLDER=$(find "$TMP_DIR" -type d -name "UUPs" | head -n1)
[[ -z "$UUP_FOLDER" ]] && msg_error "$(translate "No UUP folder found.")" && exit 1


echo -e "\n${GN}=======================================${CL}"
echo -e "    💿 ${GN}Starting ISO conversion...${CL}"
echo -e "${GN}=======================================${CL}\n"

"$CONVERTER/convert.sh" wim "$UUP_FOLDER" 1


ISO_FILE=$(find "$TMP_DIR" "$CONVERTER" "$UUP_FOLDER" -maxdepth 1 -iname "*.iso" | head -n1)
if [[ -f "$ISO_FILE" ]]; then
  mv "$ISO_FILE" "$OUT_DIR/"
  msg_ok "$(translate "ISO created successfully:") $OUT_DIR/$(basename "$ISO_FILE")"


  msg_ok "$(translate "Cleaning temporary files...")"
if [[ "$CLEAN_ALL" == true ]]; then
  rm -rf "$TMP_DIR" "$CONVERTER"
else
  [[ -d "$TMP_DIR" ]] && rm -rf "$TMP_DIR"
  [[ -d "$CONVERTER" ]] && rm -rf "$CONVERTER"
fi
    
  export OS_TYPE="windows"
  export LANG=en_US.UTF-8
  export LC_ALL=en_US.UTF-8
  export LANGUAGE=en_US:en

  load_language
  initialize_cache

  msg_success "$(translate "Press Enter to return to menu...")"
  read -r

else
  msg_warn "$(translate "No ISO was generated.")"
  rm -rf "$TMP_DIR" "$CONVERTER"
  export LANG=en_US.UTF-8
  export LC_ALL=en_US.UTF-8
  export LANGUAGE=en_US:en

  load_language
  initialize_cache
  msg_success "$(translate "Press Enter to return to menu...")"
  read -r
  return 1
fi

}
