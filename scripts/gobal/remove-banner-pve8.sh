#!/bin/bash
# ==========================================================
# Remove Subscription Banner - Proxmox VE 8.x ONLY
# ==========================================================
# This script is specifically designed for PVE 8.x
# DO NOT use on PVE 9.x - use remove-banner-pve9.sh instead
# ==========================================================

remove_subscription_banner_pve8() {
    local JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
    local GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
    local APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"
    
    # Verify PVE 8.x
    local pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1)
    local pve_major=$(echo "$pve_version" | cut -d. -f1)
    
    if [ "$pve_major" -ge 9 ] 2>/dev/null; then
        msg_error "This script is for PVE 8.x only. Detected PVE $pve_version"
        return 1
    fi
    
    msg_info "Detected Proxmox VE $pve_version - Applying PVE 8.x patches"
    
    # Verify that the file exists
    if [ ! -f "$JS_FILE" ]; then
        msg_error "JavaScript file not found: $JS_FILE"
        return 1
    fi
    
    
    for f in /etc/apt/apt.conf.d/*nag*; do 
        [[ -e "$f" ]] && rm -f "$f"
    done
    
    
    sed -i "s/res\.data\.status\.toLowerCase() !== 'NoMoreNagging'/false/g" "$JS_FILE"
    sed -i "s/res\.data\.status\.toLowerCase() !== \"NoMoreNagging\"/false/g" "$JS_FILE"
    sed -i "s/res\.data\.status\.toLowerCase() !== 'active'/false/g" "$JS_FILE"
    sed -i "s/res\.data\.status !== 'Active'/false/g" "$JS_FILE"
    sed -i "s/subscription = !(/subscription = false \&\& (/g" "$JS_FILE"
    
    sed -i '/checked_command: function/,/},$/c\
    checked_command: function (orig_cmd) {\
        orig_cmd();\
    },' "$JS_FILE"
    
    sed -i "s/title: gettext('No valid subscription')/title: gettext('Subscription Active')/g" "$JS_FILE"
    sed -i "s/icon: Ext\.Msg\.WARNING/icon: Ext.Msg.INFO/g" "$JS_FILE"
    
    sed -i '/check_subscription: function/,/},$/c\
    check_subscription: function () {\
        let me = this;\
        let vm = me.getViewModel();\
        vm.set("subscriptionActive", true);\
        me.getController().updateState();\
    },' "$JS_FILE"
    
    [[ -f "$GZ_FILE" ]] && rm -f "$GZ_FILE"
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    
    [[ -f "$APT_HOOK" ]] && rm -f "$APT_HOOK"
    cat > "$APT_HOOK" << 'EOF'
DPkg::Post-Invoke {
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/res\\.data\\.status\\.toLowerCase() !== \\'NoMoreNagging\\'/false/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/res\\.data\\.status\\.toLowerCase() !== \\'active\\'/false/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "test -e /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js && sed -i 's/subscription = !(/subscription = false \\&\\& (/g' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js || true";
    "rm -f /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz || true";
};
EOF
    chmod 644 "$APT_HOOK"
    
    apt --reinstall install proxmox-widget-toolkit -y > /dev/null 2>&1
    
    local changes_applied=0
    if ! grep -q "res\.data\.status\.toLowerCase() !== 'NoMoreNagging'" "$JS_FILE"; then
        ((changes_applied++))
    fi
    if ! grep -q "title: gettext('No valid subscription')" "$JS_FILE"; then
        ((changes_applied++))
    fi
    
    if [[ $changes_applied -gt 0 ]]; then
        msg_ok "Subscription banner removed successfully."
    else
        msg_warn "Patches may not have been applied correctly. Please verify manually."
    fi
    
    register_tool "subscription_banner" true
}



# Execute function if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    remove_subscription_banner_pve8
fi
