#!/bin/bash
# ==========================================================
# Remove Subscription Banner - Proxmox VE 9.x ONLY
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

# Tool registration system
ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

register_tool() {
    local tool="$1"
    local state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

remove_subscription_banner_pve9() {
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local MIN_JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    local APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"
    
    # Verify PVE 9.x
    local pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1)
    local pve_major=$(echo "$pve_version" | cut -d. -f1)
    
    if [ "$pve_major" -lt 9 ] 2>/dev/null; then
        msg_error "This script is for PVE 9.x only. Detected PVE $pve_version"
        return 1
    fi
    
    msg_info "Detected Proxmox VE $pve_version - Applying PVE 9.x patches"
    
    # Verify that the file exists
    if [ ! -f "$JS_FILE" ]; then
        msg_error "JavaScript file not found: $JS_FILE"
        return 1
    fi
    
    
    # Create backup of original file
    local backup_file="${JS_FILE}.backup.pve9.$(date +%Y%m%d_%H%M%S)"
    cp "$JS_FILE" "$backup_file"
    
    # Clean any existing problematic APT hooks
    for f in /etc/apt/apt.conf.d/*nag*; do 
        [[ -e "$f" ]] && rm -f "$f"
    done
    
    
    # Main subscription check patches for PVE 9
    sed -i "s/res\.data\.status\.toLowerCase() !== 'active'/false/g" "$JS_FILE"
    sed -i "s/subscriptionActive: ''/subscriptionActive: true/g" "$JS_FILE"
    sed -i "s/title: gettext('No valid subscription')/title: gettext('Community Edition')/g" "$JS_FILE"
    
    # Additional UX improvements for PVE 9
    sed -i "s/You do not have a valid subscription for this server/Community Edition - No subscription required/g" "$JS_FILE"
    sed -i "s/Enterprise repository needs valid subscription/Enterprise repository configured/g" "$JS_FILE"
    sed -i "s/icon: Ext\.Msg\.WARNING/icon: Ext.Msg.INFO/g" "$JS_FILE"
    
    # Additional subscription patterns that may exist in PVE 9
    sed -i "s/subscription = !(/subscription = false \&\& (/g" "$JS_FILE"
    
    # Remove compressed/minified files to force regeneration
    [[ -f "$GZ_FILE" ]] && rm -f "$GZ_FILE"
    [[ -f "$MIN_JS_FILE" ]] && rm -f "$MIN_JS_FILE"
    
    # Clear various caches
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    
    # Create PVE 9.x specific APT hook
    [[ -f "$APT_HOOK" ]] && rm -f "$APT_HOOK"
    cat > "$APT_HOOK" << 'EOF'
DPkg::Post-Invoke {
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/res\\.data\\.status\\.toLowerCase() !== '\''active'\''/false/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/subscriptionActive: '\'\'\''/subscriptionActive: true/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/title: gettext('\''No valid subscription'\'')/title: gettext('\''Community Edition'\'')/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/subscription = !(/subscription = false \\&\\& (/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "rm -f /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz || true";
};
EOF
    
    chmod 644 "$APT_HOOK"
    
    # Verify APT hook syntax
    if ! apt-config dump >/dev/null 2>&1; then
        msg_warn "APT hook has syntax issues, removing..."
        rm -f "$APT_HOOK"
    else
        msg_ok "APT hook created successfully"
    fi
    
    
    msg_ok "Subscription banner removed successfully for Proxmox VE $pve_version"
    msg_ok "Banner removal process completed"

    
    register_tool "subscription_banner" true
}


# Execute function if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    remove_subscription_banner_pve9
fi
