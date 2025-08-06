#!/bin/bash
# ==========================================================
# Remove Subscription Banner - Proxmox VE 8.4.9 
# ==========================================================
REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache


ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

register_tool() {
    local tool="$1"
    local state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

remove_subscription_banner_pve8() {
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    local APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"

    local pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1)
    local pve_major=$(echo "$pve_version" | cut -d. -f1)

    if [[ "$pve_major" -ge 9 ]]; then
        msg_error "This script is for PVE 8.x only. Detected PVE $pve_version"
        return 1
    fi

    msg_info "Detected Proxmox VE $pve_version - Applying safe JS patch..."

    if [[ ! -f "$JS_FILE" ]]; then
        msg_error "JavaScript file not found: $JS_FILE"
        return 1
    fi

    cp "$JS_FILE" "${JS_FILE}.bak.$(date +%s)"

    sed -i "s/No valid subscription/Subscription active/g" "$JS_FILE"
    sed -i "s/Ext.Msg.WARNING/Ext.Msg.INFO/g" "$JS_FILE"

    [[ -f "$GZ_FILE" ]] && rm -f "$GZ_FILE"
    [[ -f "$APT_HOOK" ]] && rm -f "$APT_HOOK"

    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true

    msg_ok "Subscription banner removed successfully."

    register_tool "subscription_banner" true
}




# Execute function if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    remove_subscription_banner_pve8
fi
