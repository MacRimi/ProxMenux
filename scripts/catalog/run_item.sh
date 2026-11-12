#!/bin/bash
# ==========================================================
# ProxMenux - Run an item of the Monitor's Catalog tab
# ==========================================================
# Called by the Monitor's terminal with:
#   KIND      oci (an OCI manager application), cs (a Community Scripts script)
#             or pmx (an option of the ProxMenux menu)
#   ITEM      the application id or the script slug
#   ADVANCED  1 for the advanced installation of an OCI application
# Each one runs the same flow as the menu.
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache

if [[ ! ${ITEM:-} =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
    msg_error "$(translate "Invalid application")"
    exit 1
fi

# The item ends where its own flow does instead of going on to other menus
# (see catalog_env.sh), and the screen is cleared after it, so no menu is left
# drawn under the result.
export PROXMENUX_CATALOG=1
export BASH_ENV="$LOCAL_SCRIPTS/catalog/catalog_env.sh"

run() {
    "$@"
    local status=$?
    clear
    exit "$status"
}

case "${KIND:-}" in
    oci)
        args=(install "$ITEM" --menu)
        [[ ${ADVANCED:-} == "1" ]] && args+=(--advanced)
        export PROXMENUX_CATALOG_TARGET="$LOCAL_SCRIPTS/oci/oci_manager_apps.sh"
        run bash "$PROXMENUX_CATALOG_TARGET" "${args[@]}"
        ;;
    cs)
        export PROXMENUX_CATALOG_TARGET="$LOCAL_SCRIPTS/menus/menu_Helper_Scripts.sh"
        run bash "$PROXMENUX_CATALOG_TARGET" "$ITEM"
        ;;
    pmx)
        # A ProxMenux option is opened by the menu search, which only opens
        # options of its own list and names the script it starts.
        run python3 "$LOCAL_SCRIPTS/menus/search_menu.py" --run "$ITEM"
        ;;
    *)
        msg_error "$(translate "Invalid application")"
        exit 1
        ;;
esac
