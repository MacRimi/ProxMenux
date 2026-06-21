#!/bin/bash
# ==========================================================
# ProxMenux - Shared utility installation functions
# ==========================================================
# Source this file in scripts that need to install system utilities.
# Provides: PROXMENUX_UTILS array, ensure_repositories(), install_single_package()
#
# Usage:
#   source "$LOCAL_SCRIPTS/global/utils-install-functions.sh"
# ==========================================================

# All available utilities — format: "package:verify_command:description"
PROXMENUX_UTILS=(
    "axel:axel:Download accelerator"
    "dos2unix:dos2unix:Convert DOS/Unix text files"
    "grc:grc:Generic log colorizer"
    "htop:htop:Interactive process viewer"
    "btop:btop:Modern resource monitor"
    "iftop:iftop:Real-time network usage"
    "iotop:iotop:Monitor disk I/O usage"
    "iperf3:iperf3:Network bandwidth testing"
    "intel-gpu-tools:intel_gpu_top:Intel GPU tools"
    "s-tui:s-tui:Stress-Terminal UI"
    "ipset:ipset:Manage IP sets"
    "iptraf-ng:iptraf-ng:Network monitoring tool"
    "plocate:locate:Locate files quickly"
    "msr-tools:rdmsr:Access CPU MSRs"
    "net-tools:netstat:Legacy networking tools"
    "sshpass:sshpass:Non-interactive SSH login"
    "tmux:tmux:Terminal multiplexer"
    "unzip:unzip:Extract ZIP files"
    "zip:zip:Create ZIP files"
    "libguestfs-tools:virt-filesystems:VM disk utilities"
    "aria2:aria2c:Multi-source downloader"
    "cabextract:cabextract:Extract CAB files"
    "wimtools:wimlib-imagex:Manage WIM images"
    "genisoimage:genisoimage:Create ISO images"
    "chntpw:chntpw:Edit Windows registry/passwords"
)


# Ensure APT repositories are configured for the current PVE version.
# Creates missing no-subscription repo entries for PVE8 (bookworm) or PVE9 (trixie).
ensure_repositories() {
    local pve_version need_update=false
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if (( pve_version >= 9 )); then
        # ===== PVE 9 (Debian 13 - trixie) =====
        if [[ ! -f /etc/apt/sources.list.d/proxmox.sources ]]; then
            cat > /etc/apt/sources.list.d/proxmox.sources <<'EOF'
Enabled: true
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
            need_update=true
        fi

        if [[ ! -f /etc/apt/sources.list.d/debian.sources ]]; then
            cat > /etc/apt/sources.list.d/debian.sources <<'EOF'
Types: deb
URIs: http://deb.debian.org/debian/
Suites: trixie trixie-updates
Components: main contrib non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security/
Suites: trixie-security
Components: main contrib non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
            need_update=true
        fi

    else
        # ===== PVE 8 (Debian 12 - bookworm) =====
        local sources_file="/etc/apt/sources.list"

        if ! grep -qE 'deb .* bookworm .* main' "$sources_file" 2>/dev/null; then
            {
                echo "deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware"
                echo "deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware"
                echo "deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware"
            } >> "$sources_file"
            need_update=true
        fi

        if [[ ! -f /etc/apt/sources.list.d/pve-no-subscription.list ]]; then
            echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" \
                > /etc/apt/sources.list.d/pve-no-subscription.list
            need_update=true
        fi
    fi

    if [[ "$need_update" == true ]] || [[ ! -d /var/lib/apt/lists || -z "$(ls -A /var/lib/apt/lists 2>/dev/null)" ]]; then
        msg_info "$(translate "Updating APT package lists...")"
        apt-get update >/dev/null 2>&1 || apt-get update
        # Spinner pair: msg_info must be closed before returning.
        # Without this the next `msg_info` caller spawns a second
        # spinner on top of ours and the original line never gets
        # ✓'d — leaving a dangling progress char on screen.
        msg_ok "$(translate "APT package lists updated")"
    fi

    return 0
}


# Install a single package and verify the resulting command is available.
# Args: package_name  verify_command  description
# Returns: 0=ok  1=install_failed  2=installed_but_command_not_found
install_single_package() {
    local package="$1"
    local command_name="${2:-$package}"
    local description="${3:-$package}"

    msg_info "$(translate "Installing") $package${description:+ ($description)}..."
    local install_success=false

    if DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" >/dev/null 2>&1; then
        install_success=true
    fi
    cleanup 2>/dev/null || true

    if [[ "$install_success" == true ]]; then
        hash -r 2>/dev/null
        sleep 1
        if command -v "$command_name" >/dev/null 2>&1; then
            msg_ok "$package $(translate "installed correctly and available")"
            return 0
        else
            msg_warn "$package $(translate "installed but command not immediately available")"
            msg_info2 "$(translate "May need to restart terminal")"
            return 2
        fi
    else
        msg_error "$(translate "Error installing") $package"
        return 1
    fi
}
