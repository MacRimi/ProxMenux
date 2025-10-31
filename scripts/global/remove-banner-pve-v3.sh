#!/bin/bash
# ==========================================================
# Remove Subscription Banner - Proxmox VE (v3 - Minimal Intrusive)
# ==========================================================
# This version makes a surgical change to the checked_command function
# by changing the condition to 'if (false)' and commenting out the banner logic.
# Also patches the mobile UI to remove the subscription dialog.
# ==========================================================

set -euo pipefail

# Source utilities if available
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# File paths
JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
MIN_JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js"
MOBILE_UI_FILE="/usr/share/pve-yew-mobile-gui/index.html.tpl"
BACKUP_DIR="$BASE_DIR/backups"
APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"
PATCH_BIN="/usr/local/bin/pve-remove-nag-v3.sh"
MARK="/* PROXMENUX_NAG_PATCH_V3 */"
MOBILE_MARK="<!-- PROXMENUX_MOBILE_NAG_PATCH -->"

# Ensure tools JSON exists
ensure_tools_json() {
    [ -f "$TOOLS_JSON" ] || echo "{}" > "$TOOLS_JSON"
}

# Register tool in JSON
register_tool() {
    command -v jq >/dev/null 2>&1 || return 0
    local tool="$1" state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" \
      > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

# Verify JS file integrity
verify_js_integrity() {
    local file="$1"
    [ -f "$file" ] || return 1
    [ -s "$file" ] || return 1
    grep -Eq 'Ext|function|var|const|let' "$file" || return 1
    if LC_ALL=C grep -qP '\x00' "$file" 2>/dev/null; then
        return 1
    fi
    return 0
}

# Create timestamped backup
create_backup() {
    local file="$1"
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/$(basename "$file").backup.$timestamp"
    
    mkdir -p "$BACKUP_DIR"
    
    if [ -f "$file" ]; then
        rm -f "$BACKUP_DIR"/"$(basename "$file")".backup.* 2>/dev/null || true
        
        cp -a "$file" "$backup_file"
        echo "$backup_file"
    fi
}

# Create the patch script that will be called by APT hook
create_patch_script() {
    cat > "$PATCH_BIN" <<'EOFPATCH'
#!/usr/bin/env bash
# ==========================================================
# Proxmox Subscription Banner Patch (v3 - Minimal)
# ==========================================================
set -euo pipefail

JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
MIN_JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js"
MOBILE_UI_FILE="/usr/share/pve-yew-mobile-gui/index.html.tpl"
BACKUP_DIR="/usr/local/share/proxmenux/backups"
MARK="/* PROXMENUX_NAG_PATCH_V3 */"
MOBILE_MARK="<!-- PROXMENUX_MOBILE_NAG_PATCH -->"

verify_js_integrity() {
    local file="$1"
    [ -f "$file" ] && [ -s "$file" ] && grep -Eq 'Ext|function' "$file" && ! LC_ALL=C grep -qP '\x00' "$file" 2>/dev/null
}

patch_checked_command() {
    [ -f "$JS_FILE" ] || return 0
    
    # Check if already patched
    grep -q "$MARK" "$JS_FILE" && return 0
    
    # Create backup
    mkdir -p "$BACKUP_DIR"
    local backup="$BACKUP_DIR/$(basename "$JS_FILE").backup.$(date +%Y%m%d_%H%M%S)"
    cp -a "$JS_FILE" "$backup"
    
    # Set trap to restore on error
    trap "cp -a '$backup' '$JS_FILE' 2>/dev/null || true" ERR
    
    # Add patch marker at the beginning
    sed -i "1s|^|$MARK\n|" "$JS_FILE"
    
    # Surgical patch: Change the condition in checked_command function
    # This changes the if condition to 'if (false)' making the banner never show
    if grep -q "res\.data\.status\.toLowerCase() !== 'active'" "$JS_FILE"; then
        # Pattern for newer versions (8.4.5+)
        sed -i "/checked_command: function/,/},$/s/res === null || res === undefined || !res || res\.data\.status\.toLowerCase() !== 'active'/false/g" "$JS_FILE"
    elif grep -q "res\.data\.status !== 'Active'" "$JS_FILE"; then
        # Pattern for older versions
        sed -i "/checked_command: function/,/},$/s/res === null || res === undefined || !res || res\.data\.status !== 'Active'/false/g" "$JS_FILE"
    fi
    
    # Also handle the NoMoreNagging pattern if present
    if grep -q "res\.data\.status\.toLowerCase() !== 'NoMoreNagging'" "$JS_FILE"; then
        sed -i "/checked_command: function/,/},$/s/res === null || res === undefined || !res || res\.data\.status\.toLowerCase() !== 'NoMoreNagging'/false/g" "$JS_FILE"
    fi
    
    # Verify integrity after patch
    if ! verify_js_integrity "$JS_FILE"; then
        cp -a "$backup" "$JS_FILE"
        return 1
    fi
    
    # Clean up generated files
    rm -f "$MIN_JS_FILE" "$GZ_FILE" 2>/dev/null || true
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/cache/nginx/ -type f -delete 2>/dev/null || true
    
    trap - ERR
    return 0
}

patch_mobile_ui() {
    [ -f "$MOBILE_UI_FILE" ] || return 0
    
    # Check if already patched
    grep -q "$MOBILE_MARK" "$MOBILE_UI_FILE" && return 0
    
    # Create backup
    mkdir -p "$BACKUP_DIR"
    local backup="$BACKUP_DIR/$(basename "$MOBILE_UI_FILE").backup.$(date +%Y%m%d_%H%M%S)"
    cp -a "$MOBILE_UI_FILE" "$backup"
    
    # Set trap to restore on error
    trap "cp -a '$backup' '$MOBILE_UI_FILE' 2>/dev/null || true" ERR
    
    # Insert the script before </head> tag
    sed -i "/<\/head>/i\\
$MOBILE_MARK\\
        <!-- Script to remove subscription banner from mobile UI -->\\
        <script>\\
    function removeNoSubDialog() {\\
      const observer = new MutationObserver(() => {\\
        const diag = document.querySelector('dialog[aria-label=\"No valid subscription\"]');\\
        if (diag) {\\
          diag.remove();\\
        }\\
      });\\
      observer.observe(document.body, { childList: true, subtree: true });\\
    }\\
    window.addEventListener('load', () => {\\
      setTimeout(removeNoSubDialog, 200);\\
    });\\
  </script>" "$MOBILE_UI_FILE"
    
    trap - ERR
    return 0
}

reload_services() {
    systemctl is-active --quiet pveproxy 2>/dev/null && {
        systemctl reload pveproxy 2>/dev/null || systemctl restart pveproxy 2>/dev/null || true
    }
    systemctl is-active --quiet nginx 2>/dev/null && {
        systemctl reload nginx 2>/dev/null || true
    }
    systemctl is-active --quiet pvedaemon 2>/dev/null && {
        systemctl reload pvedaemon 2>/dev/null || true
    }
}

main() {
    patch_checked_command || return 1
    patch_mobile_ui || true
    reload_services
}

main
EOFPATCH

    chmod 755 "$PATCH_BIN"
}

# Create APT hook to reapply patch after updates
create_apt_hook() {
    cat > "$APT_HOOK" <<'EOFAPT'
/* ProxMenux: reapply minimal nag patch after upgrades */
DPkg::Post-Invoke { "/usr/local/bin/pve-remove-nag-v3.sh || true"; };
EOFAPT
    
    chmod 644 "$APT_HOOK"
    
    # Verify APT hook syntax
    apt-config dump >/dev/null 2>&1 || { 
        rm -f "$APT_HOOK"
    }
}

# Main function to remove subscription banner
remove_subscription_banner_v3() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1 || echo "unknown")
    
    msg_info "$(translate "Detected Proxmox VE") ${pve_version} - $(translate "applying banner patch")"
    

    
    # Remove old APT hooks
    for f in /etc/apt/apt.conf.d/*nag*; do 
        [[ -e "$f" ]] && rm -f "$f"
    done
    
    # Create backup for desktop UI
    local backup_file
    backup_file=$(create_backup "$JS_FILE")
    if [ -n "$backup_file" ]; then
        # msg_ok "$(translate "Desktop UI backup created"): $backup_file"
        :
    fi
    
    if [ -f "$MOBILE_UI_FILE" ]; then
        local mobile_backup
        mobile_backup=$(create_backup "$MOBILE_UI_FILE")
        if [ -n "$mobile_backup" ]; then
        # msg_ok "$(translate "Mobile UI backup created"): $mobile_backup"
        :
        fi
    fi
    
    # Create patch script and APT hook
    create_patch_script
    create_apt_hook
    
    # Apply the patch
    if ! "$PATCH_BIN"; then
        msg_error "$(translate "Error applying patch. Backups preserved at"): $BACKUP_DIR"
        return 1
    fi
    
    # Register tool as applied
    register_tool "subscription_banner" true
    
    msg_ok "$(translate "Subscription banner removed successfully")"
    msg_ok "$(translate "Desktop and Mobile UI patched")"
    msg_ok "$(translate "Refresh your browser (Ctrl+Shift+R) to see changes")"

}

# Run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    remove_subscription_banner_v3
fi
