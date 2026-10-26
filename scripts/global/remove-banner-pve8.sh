#!/bin/bash
# ==========================================================
# Remove Subscription Banner - Proxmox VE 8.4.9 
# ==========================================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS/global/pmx_journal.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/pmx_journal.sh"
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
    local FUNC_VERSION="1.0"
    pmx_journal_context "remove_subscription_banner_pve8" "$FUNC_VERSION"
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    local APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"
    local BACKUP_FILE="${JS_FILE}.bak.$(date +%F_%T)"

    local pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1)
    local pve_major=$(echo "$pve_version" | cut -d. -f1)

    if [[ "$pve_major" -ne 8 ]]; then
        msg_error "This script is only for Proxmox VE 8.x. Detected: $pve_version"
        return 1
    fi

    msg_info "Detected Proxmox VE $pve_version - Applying safe JS patch..."

    if [[ ! -f "$JS_FILE" ]]; then
        msg_error "JavaScript file not found: $JS_FILE"
        return 1
    fi

    cp "$JS_FILE" "$BACKUP_FILE"


    pmx_edit_file "$JS_FILE" \
        -e "s/No valid subscription/Subscription active/g" \
        -e "s/Ext.Msg.WARNING/Ext.Msg.INFO/g" \
        -e "s/res.data.status.toLowerCase() !== 'active'/false/g" \
        -e "s/subscriptionActive: ''/subscriptionActive: true/g"

    [[ -f "$GZ_FILE" ]] && pmx_remove_file "$GZ_FILE"

    pmx_record_execution "Clear cached Proxmox JavaScript files" "find /var/cache/pve-manager/ -name *.js* -delete"
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    pmx_record_execution "Clear generated Proxmox JavaScript files" "find /var/lib/pve-manager/ -name *.js* -delete"
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true

    [[ -f "$APT_HOOK" ]] && pmx_remove_file "$APT_HOOK"


    msg_ok "Subscription banner removed successfully."

    register_tool "subscription_banner" true
}



if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    remove_subscription_banner_pve8
fi
