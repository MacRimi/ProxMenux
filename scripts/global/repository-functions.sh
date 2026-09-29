#!/bin/bash
# Shared repository policy for package-install and safe-update flows.
# Proxmox's own repository API parses .list/.sources and edits individual
# entries. No shell rewriting of operator-maintained APT files.
repository_policy() {
    python3 "$(dirname "${BASH_SOURCE[0]}")/repository_policy.py" "$@"
}

ensure_repositories() {
    local version suite decision
    version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)
    case "$version" in
        8) suite=bookworm ;;
        9) suite=trixie ;;
        *) msg_error "$(translate 'Unsupported or unknown Proxmox version; no repository changed.')"; return 1 ;;
    esac
    # Do not hide diagnostics or open a spinner during user interaction.
    decision=$(repository_policy plan "$suite") || return 1
    case "$decision" in
        preserve) return 0 ;;
        offer) ;;
        *) msg_error "$(translate 'Repository policy returned an unexpected result.')"; return 1 ;;
    esac
    if ! declare -F hybrid_yesno >/dev/null || { [[ ! -t 0 ]] && ! { declare -F is_web_mode >/dev/null && is_web_mode; }; }; then
        msg_error "$(translate 'No subscription and no usable PVE repository. Noninteractive mode cannot change APT sources; configure them in Node > Updates > Repositories.')"
        return 1
    fi
    if ! hybrid_yesno "$(translate 'Proxmox repository')" \
        "$(translate 'This host has no subscription, switch to the no-subscription repository? The inaccessible Enterprise PVE source will be disabled. Enterprise Ceph sources, if present, will be disabled without choosing a replacement Ceph channel; configure Ceph separately if needed.')" 16 90; then
        msg_error "$(translate 'Repository switch declined; no APT source changed.')"
        return 1
    fi
    decision=$(repository_policy apply "$suite") || return 1
    [[ "$decision" == changed || "$decision" == preserve ]] || return 1
    return 0
}
