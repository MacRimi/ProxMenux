#!/bin/bash
# Use PBS's existing repositories; never run PVE repo, Ceph or major-upgrade scripts.
BASE_DIR="/usr/local/share/proxmenux"
LOCAL_SCRIPTS="$BASE_DIR/scripts"
source "$BASE_DIR/utils.sh"
source "$LOCAL_SCRIPTS/global/platform-functions.sh"
load_language
initialize_cache

if ! pmx_is_pbs || [[ "$(pmx_platform_field supported)" != true ]]; then
    msg_error "$(translate 'This operation supports PBS 3 on Debian 12 and PBS 4 on Debian 13.')"
    exit 1
fi
[[ $EUID -eq 0 ]] || { msg_error "$(translate 'Run this operation as root.')"; exit 1; }
dialog --backtitle "ProxMenux · PBS" --title "$(translate 'PBS package update')" \
    --yesno "$(translate 'Refresh the configured APT repositories and review the PBS package upgrade? Repository files will be preserved.')" 10 80 || exit 0
if ! apt-get -o APT::Update::Error-Mode=any update; then
    msg_error "$(translate 'APT refresh failed. Check the PBS subscription and repositories in the native PBS interface; no source was changed.')"
    read -r _
    exit 1
fi
plan=$(mktemp)
trap 'rm -f "$plan"' EXIT
if ! apt-get -s full-upgrade > "$plan" 2>&1; then
    dialog --textbox "$plan" 24 100
    exit 1
fi
dialog --backtitle "ProxMenux · PBS" --title "$(translate 'Review package upgrade')" --textbox "$plan" 24 100
dialog --defaultno --title "$(translate 'Apply PBS package upgrade')" \
    --yesno "$(translate 'Apply the reviewed package upgrade now? Services may restart and packages listed for removal will be removed.')" 11 80 || exit 0
if apt-get -y full-upgrade; then
    msg_ok "$(translate 'PBS package upgrade completed. Check whether a reboot is required before your next backup window.')"
else
    msg_error "$(translate 'PBS package upgrade failed. Review the APT output before retrying.')"
    read -r _
    exit 1
fi
read -r _
