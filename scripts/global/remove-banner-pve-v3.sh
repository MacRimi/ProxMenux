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
    
    # Check if already patched - look for our marker
    if grep -q "$MARK" "$JS_FILE"; then
        # Verify the patch is actually applied by checking if function is simplified
        if grep -A 2 "checked_command: function" "$JS_FILE" | grep -q "orig_cmd();"; then
            return 0
        else
            # Marker exists but patch not applied - remove marker and try again
            sed -i "/$MARK/d" "$JS_FILE"
        fi
    fi
    
    # Create backup
    mkdir -p "$BACKUP_DIR"
    local backup="$BACKUP_DIR/$(basename "$JS_FILE").backup.$(date +%Y%m%d_%H%M%S)"
    cp -a "$JS_FILE" "$backup"
    
    # Set trap to restore on error
    trap "cp -a '$backup' '$JS_FILE' 2>/dev/null || true" ERR
    
    # Use Python to replace the entire checked_command function using brace counting
    python3 <<'PYTHON_END'
import sys

js_file = "/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"

try:
    with open(js_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the line with checked_command
    start_line = -1
    for i, line in enumerate(lines):
        if 'checked_command: function' in line or 'checked_command:function' in line:
            start_line = i
            break
    
    if start_line == -1:
        print("checked_command function not found", file=sys.stderr)
        sys.exit(1)
    
    # Count braces to find the end of the function
    brace_count = 0
    end_line = -1
    started_counting = False
    
    for i in range(start_line, len(lines)):
        line = lines[i]
        
        # Count opening and closing braces
        for char in line:
            if char == '{':
                brace_count += 1
                started_counting = True
            elif char == '}':
                brace_count -= 1
        
        # When we reach 0 and we've started counting, we found the end
        if started_counting and brace_count == 0:
            # Check if this line ends with "}," which is the function closure
            if '},' in line or '},\n' in line:
                end_line = i
                break
    
    if end_line == -1:
        print("Could not find end of checked_command function", file=sys.stderr)
        sys.exit(1)
    
    # Get the indentation of the original function
    indent = len(lines[start_line]) - len(lines[start_line].lstrip())
    indent_str = ' ' * indent
    
    # Create the replacement function (simple version that just calls orig_cmd)
    replacement = [
        f"{indent_str}checked_command: function (orig_cmd) {{\n",
        f"{indent_str}    orig_cmd();\n",
        f"{indent_str}}},\n"
    ]
    
    # Replace the function
    new_lines = lines[:start_line] + replacement + lines[end_line+1:]
    
    # Write the modified content
    with open(js_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    #print(f"Successfully replaced lines {start_line+1} to {end_line+1}")
    sys.exit(0)

except Exception as e:
    print(f"Python patch error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
PYTHON_END
    
    local python_result=$?
    
    if [ $python_result -ne 0 ]; then
        # Python failed, restore backup
        cp -a "$backup" "$JS_FILE"
        trap - ERR
        return 1
    fi
    
    # Verify the patch was applied
    if ! grep -A 2 "checked_command: function" "$JS_FILE" | grep -q "orig_cmd();"; then
        cp -a "$backup" "$JS_FILE"
        trap - ERR
        return 1
    fi
    
    # Add patch marker at the beginning
    sed -i "1s|^|$MARK\n|" "$JS_FILE"
    
    # Verify integrity after patch
    if ! verify_js_integrity "$JS_FILE"; then
        cp -a "$backup" "$JS_FILE"
        trap - ERR
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
        msg_warn "APT hook syntax issue, removing..."
        rm -f "$APT_HOOK"
    }
}

# Main function to remove subscription banner
remove_subscription_banner_v3() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1 || echo "unknown")
    
    msg_info "$(translate "Detected Proxmox VE") ${pve_version} - $(translate "applying minimal banner patch")"
    

    
    # Remove old APT hooks
    for f in /etc/apt/apt.conf.d/*nag*; do 
        [[ -e "$f" ]] && rm -f "$f"
    done
    
    # Create backup for desktop UI
    local backup_file
    backup_file=$(create_backup "$JS_FILE")
    if [ -n "$backup_file" ]; then
        msg_ok "$(translate "Desktop UI backup created")"
    fi
    
    if [ -f "$MOBILE_UI_FILE" ]; then
        local mobile_backup
        mobile_backup=$(create_backup "$MOBILE_UI_FILE")
        if [ -n "$mobile_backup" ]; then
            msg_ok "$(translate "Mobile UI backup created")"
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
