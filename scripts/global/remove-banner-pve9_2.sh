#!/bin/bash
# ==========================================================
# Remove Subscription Banner - Proxmox VE 9.x (Clean Version)
# ==========================================================

set -euo pipefail


BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
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
    command -v jq >/dev/null 2>&1 || return 0
    local tool="$1" state="$2"
    ensure_tools_json
    jq --arg t "$tool" --argjson v "$state" '.[$t]=$v' "$TOOLS_JSON" \
      > "$TOOLS_JSON.tmp" && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON"
}

JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
MIN_JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js"
GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
MOBILE_TPL="/usr/share/pve-yew-mobile-gui/index.html.tpl"
APT_HOOK="/etc/apt/apt.conf.d/no-nag-script"
PATCH_BIN="/usr/local/bin/pve-remove-nag.sh"

MARK_JS="PROXMENUX_NAG_REMOVED_v2"
MARK_MOBILE="<!-- PROXMENUX: MOBILE NAG PATCH v2 -->"


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

create_backup() {
    local file="$1"
    local backup_dir="$BASE_DIR/backups"
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/$(basename "$file").backup.$timestamp"
    mkdir -p "$backup_dir"
    if [ -f "$file" ]; then
        cp -a "$file" "$backup_file"
        ls -t "$backup_dir"/"$(basename "$file")".backup.* 2>/dev/null | tail -n +6 | xargs -r rm -f 2>/dev/null || true
        echo "$backup_file"
    fi
}

# ----------------------------------------------------

create_patch_script() {
    cat > "$PATCH_BIN" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
MIN_JS_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.min.js"
GZ_FILE="/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js.gz"
MOBILE_TPL="/usr/share/pve-yew-mobile-gui/index.html.tpl"
MARK_JS="PROXMENUX_NAG_REMOVED_v2"
MARK_MOBILE="<!-- PROXMENUX: MOBILE NAG PATCH v2 -->"
BASE_DIR="/usr/local/share/proxmenux"

verify_js_integrity() {
    local file="$1"
    [ -f "$file" ] && [ -s "$file" ] && grep -Eq 'Ext|function' "$file" && ! LC_ALL=C grep -qP '\x00' "$file" 2>/dev/null
}

patch_web() {
    [ -f "$JS_FILE" ] || return 0
    grep -q "$MARK_JS" "$JS_FILE" && return 0

    local backup_dir="$BASE_DIR/backups"
    mkdir -p "$backup_dir"
    local backup="$backup_dir/$(basename "$JS_FILE").backup.$(date +%Y%m%d_%H%M%S)"
    cp -a "$JS_FILE" "$backup"
    trap "cp -a '$backup' '$JS_FILE' 2>/dev/null || true" ERR

    sed -i '1s|^|/* '"$MARK_JS"' */\n|' "$JS_FILE"

    local patterns_found=0

    if grep -q "res\.data\.status\.toLowerCase() !== 'active'" "$JS_FILE"; then
        sed -i "s/res\.data\.status\.toLowerCase() !== 'active'/false/g" "$JS_FILE"
        patterns_found=$((patterns_found + 1))
    fi

    if grep -q "subscriptionActive: ''" "$JS_FILE"; then
        sed -i "s/subscriptionActive: ''/subscriptionActive: true/g" "$JS_FILE"
        patterns_found=$((patterns_found + 1))
    fi

    if grep -q "title: gettext('No valid subscription')" "$JS_FILE"; then
        sed -i "s/title: gettext('No valid subscription')/title: gettext('Community Edition')/g" "$JS_FILE"
        patterns_found=$((patterns_found + 1))
    fi

    if grep -q "icon: Ext\.Msg\.WARNING" "$JS_FILE"; then
        sed -i "s/icon: Ext\.Msg\.WARNING/icon: Ext.Msg.INFO/g" "$JS_FILE"
        patterns_found=$((patterns_found + 1))
    fi

    if grep -q "subscription = !(" "$JS_FILE"; then
        sed -i "s/subscription = !(/subscription = false \&\& (/g" "$JS_FILE"
        patterns_found=$((patterns_found + 1))
    fi

    # Si nada coincidió (cambio upstream), restaura y sal limpio
    if [ "${patterns_found:-0}" -eq 0 ]; then
        cp -a "$backup" "$JS_FILE"
        return 0
    fi

    # Verificación final
    if ! verify_js_integrity "$JS_FILE"; then
        cp -a "$backup" "$JS_FILE"
        return 1
    fi

    # Limpiar artefactos/cachés
    rm -f "$MIN_JS_FILE" "$GZ_FILE" 2>/dev/null || true
    find /var/cache/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/lib/pve-manager/ -name "*.js*" -delete 2>/dev/null || true
    find /var/cache/nginx/ -type f -delete 2>/dev/null || true

    trap - ERR
}

patch_mobile() {
    [ -f "$MOBILE_TPL" ] || return 0
    grep -q "$MARK_MOBILE" "$MOBILE_TPL" && return 0

    local backup_dir="$BASE_DIR/backups"
    mkdir -p "$backup_dir"
    cp -a "$MOBILE_TPL" "$backup_dir/$(basename "$MOBILE_TPL").backup.$(date +%Y%m%d_%H%M%S)"

    cat >> "$MOBILE_TPL" <<EOM
$MARK_MOBILE
<script>
(function() {
  'use strict';
  function removeSubscriptionElements() {
    try {
      const dialogs = document.querySelectorAll('dialog.pwt-outer-dialog');
      dialogs.forEach(d => {
        const text = (d.textContent || '').toLowerCase();
        if (text.includes('subscription') || text.includes('no valid')) { d.remove(); }
      });
      const cards = document.querySelectorAll('.pwt-card.pwt-p-2.pwt-d-flex.pwt-interactive.pwt-justify-content-center');
      cards.forEach(c => {
        const text = (c.textContent || '').toLowerCase();
        const hasButton = c.querySelector('button');
        if (!hasButton && (text.includes('subscription') || text.includes('no valid'))) { c.remove(); }
      });
      const alerts = document.querySelectorAll('[class*="alert"], [class*="warning"], [class*="notice"]');
      alerts.forEach(a => {
        const text = (a.textContent || '').toLowerCase();
        if (text.includes('subscription') || text.includes('no valid')) { a.remove(); }
      });
    } catch (e) { console.warn('Error removing subscription elements:', e); }
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', removeSubscriptionElements); }
  else { removeSubscriptionElements(); }
  const observer = new MutationObserver(removeSubscriptionElements);
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
    const interval = setInterval(removeSubscriptionElements, 500);
    setTimeout(() => { try { observer.disconnect(); clearInterval(interval); } catch(e){} }, 30000);
  }
})();
</script>
EOM
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
  find /var/cache/pve-manager/ -type f -delete 2>/dev/null || true
  find /var/lib/pve-manager/ -type f -delete 2>/dev/null || true
}

main() {
    patch_web || return 1
    patch_mobile
    reload_services
}

main
EOF
    chmod 755 "$PATCH_BIN"
}
# ----------------------------------------------------


create_apt_hook() {
    cat > "$APT_HOOK" <<'EOF'
/* ProxMenux: reapply nag patch after upgrades */
DPkg::Post-Invoke { "/usr/local/bin/pve-remove-nag.sh || true"; };
EOF
    chmod 644 "$APT_HOOK"
    apt-config dump >/dev/null 2>&1 || { msg_warn "APT hook syntax issue"; rm -f "$APT_HOOK"; }
}



remove_subscription_banner_pve9() {
  local pve_version
  pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' | head -1 || true)
  local pve_major="${pve_version%%.*}"

  msg_info "$(translate "Detected Proxmox VE ${pve_version:-9.x} – removing subscription banner")"

  create_patch_script
  create_apt_hook

  if ! "$PATCH_BIN"; then
    msg_error "$(translate "Error applying patches")"
    return 1
  fi

  register_tool "subscription_banner" true
  msg_ok "$(translate "Subscription banner removed successfully.")"
  msg_ok "$(translate "Refresh your browser to see changes.")"
}



if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  remove_subscription_banner_pve9
fi
