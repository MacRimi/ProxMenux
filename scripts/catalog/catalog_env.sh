#!/bin/bash
# ==========================================================
# ProxMenux - Bash environment of the Monitor's Catalog tab
# ==========================================================
# run_item.sh sets this file as BASH_ENV, so bash reads it before any script
# an item of the Catalog tab starts. An item ends where its own flow does: a
# script that opens a menu other than the one the item opened, such as the
# menu it returns to or the main menu, ends instead of drawing it.
# ==========================================================

case "$0" in
    */scripts/menus/*.sh|*/scripts/help_info_menu.sh)
        if [[ "$(readlink -f "$0" 2>/dev/null)" != "$(readlink -f "${PROXMENUX_CATALOG_TARGET:-/nonexistent}" 2>/dev/null)" ]]; then
            exit 0
        fi
        ;;
esac
