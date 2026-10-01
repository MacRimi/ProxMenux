#!/bin/bash
# Shared repository policy for package-install and safe-update flows.
# Proxmox's own repository API parses .list/.sources and edits individual
# entries. No shell rewriting of operator-maintained APT files.
repository_policy() {
    python3 "$(dirname "${BASH_SOURCE[0]}")/repository_policy.py" "$@"
}

ensure_repositories() {
    local version suite decision refresh_status
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
        msg_error "$(translate 'No active subscription and no usable PVE repository. Noninteractive mode cannot change APT sources; configure them in Node > Updates > Repositories.')"
        return 1
    fi
    if ! hybrid_yesno "$(translate 'Proxmox repository')" \
        "$(translate 'This host has no active subscription, switch to the no-subscription repository? The inaccessible Enterprise PVE source will be disabled. Enterprise Ceph sources, if present, will be disabled without choosing a replacement Ceph channel; configure Ceph separately if needed.')" 16 90; then
        msg_error "$(translate 'Repository switch declined; no APT source changed.')"
        return 1
    fi
    decision=$(repository_policy apply "$suite") || return 1
    [[ "$decision" == changed || "$decision" == preserve ]] || return 1
    if [[ "$decision" == changed ]]; then
        # The switch goes through the Proxmox API; leave it in the changes journal.
        if declare -F pmx_record_execution >/dev/null; then
            local journal_function="${PMX_JOURNAL_FUNCTION:-}" journal_version="${PMX_JOURNAL_VERSION:-}"
            pmx_journal_context "ensure_repositories" "" "${PMX_JOURNAL_SOURCE:-}"
            pmx_record_execution "Switch to the PVE no-subscription repository" \
                "pvesh set /nodes/localhost/apt/repositories --handle no-subscription"
            PMX_JOURNAL_FUNCTION="$journal_function" PMX_JOURNAL_VERSION="$journal_version"
        fi
        # Direct callers may install immediately; refresh their package indexes
        # before returning. Preserve paths must not trigger an extra refresh.
        if apt-get update; then
            return 0
        else
            refresh_status=$?
            msg_error "$(translate 'Repository sources changed, but APT package-list refresh failed. Operation stopped; sources were not rolled back. Inspect Node > Updates > Repositories and retry apt-get update before continuing.')"
            return "$refresh_status"
        fi
    fi
    return 0
}
