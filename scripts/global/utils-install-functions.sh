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
        # Force 0644 (world-readable) on every .sources file we drop.
        # Under the default root umask 0027 the redirect would land at
        # 0640, which the PVE 9 webgui's repository manager treats as
        # unparseable and silently hides the source — issue #230.
        if [[ ! -f /etc/apt/sources.list.d/proxmox.sources ]]; then
            cat > /etc/apt/sources.list.d/proxmox.sources <<'EOF'
Enabled: true
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
            chmod 0644 /etc/apt/sources.list.d/proxmox.sources
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
            chmod 0644 /etc/apt/sources.list.d/debian.sources
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


# ==========================================================
# Persistent NIC naming — shared helpers
# ==========================================================
# ProxMenux-owned .link files carry two identifying marks:
#   - filename prefix: 10-proxmenux-<iface>.link
#   - first-line marker: `# Managed by ProxMenux — do not edit`
# Both are required for pmx_uninstall_persistent_network to remove a
# file, so user-authored .link files in /etc/systemd/network/ are
# never touched.

readonly PMX_NIC_LINK_DIR="/etc/systemd/network"
readonly PMX_NIC_LINK_MARKER="# Managed by ProxMenux — do not edit"

# Print the MAC address recorded in a .link file, uppercased, or empty
# if the file has no MACAddress= line.
_pmx_link_mac() {
    awk -F= '
        /^[[:space:]]*MACAddress=/ {
            gsub(/[[:space:]]/, "", $2)
            print toupper($2)
            exit
        }
    ' "$1" 2>/dev/null
}

# Returns 0 if the file exists AND its first line matches the marker.
_pmx_link_is_managed() {
    local first
    IFS= read -r first < "$1" 2>/dev/null || return 1
    [[ "$first" == "$PMX_NIC_LINK_MARKER" ]]
}

# Returns 0 if the file matches the exact template ProxMenux 1.0 used
# to write (no marker, no extra fields). Used once at 1.1 upgrade time
# to reclaim files created by an earlier version and replace them with
# the marked format.
_pmx_link_matches_legacy_10() {
    local file="$1" iface mac
    iface=$(basename "$file" .link)
    iface="${iface#10-}"
    mac=$(_pmx_link_mac "$file")
    [[ -z "$iface" || -z "$mac" ]] && return 1
    local expected
    expected="[Match]
MACAddress=$mac

[Link]
Name=$iface"
    [[ "$(cat "$file" 2>/dev/null)" == "$expected" ]]
}

# Detect physical NICs and generate 10-proxmenux-<iface>.link for
# each. Idempotent — reruns replace stale ProxMenux entries whose MAC
# is no longer present, migrate 1.0-format files, and leave every
# other .link in the directory alone.
#
# Outputs (via `printf`):
#   line "COUNT=<n>" — number of managed files after the run
#   line "REMOVED_STALE=<n>" — reconciled entries for missing MACs
#   line "REMOVED_LEGACY=<n>" — 1.0-format files replaced
pmx_setup_persistent_network() {
    mkdir -p "$PMX_NIC_LINK_DIR"

    declare -A current_macs=()
    local dev_path iface mac
    for dev_path in /sys/class/net/*; do
        iface=$(basename "$dev_path")
        case "$iface" in
            lo|docker*|veth*|br-*|vmbr*|tap*|fwpr*|fwln*|virbr*|bond*|cilium*|zt*|wg*)
                continue ;;
        esac
        if [[ -e "$dev_path/device" || -e "$dev_path/phy80211" ]]; then
            mac=$(cat "$dev_path/address" 2>/dev/null | tr '[:lower:]' '[:upper:]')
            [[ "$mac" =~ ^([A-F0-9]{2}:){5}[A-F0-9]{2}$ ]] && current_macs["$mac"]=1
        fi
    done

    if compgen -G "$PMX_NIC_LINK_DIR"/*.link >/dev/null; then
        local backup_dir
        backup_dir="$PMX_NIC_LINK_DIR/backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$backup_dir"
        cp "$PMX_NIC_LINK_DIR"/*.link "$backup_dir"/ 2>/dev/null || true
    fi

    local removed_stale=0 removed_legacy=0
    local link_file
    for link_file in "$PMX_NIC_LINK_DIR"/10-proxmenux-*.link; do
        [[ -f "$link_file" ]] || continue
        _pmx_link_is_managed "$link_file" || continue
        mac=$(_pmx_link_mac "$link_file")
        [[ -z "$mac" ]] && continue
        if [[ -z "${current_macs[$mac]+x}" ]]; then
            rm -f -- "$link_file"
            removed_stale=$((removed_stale + 1))
        fi
    done

    for link_file in "$PMX_NIC_LINK_DIR"/10-*.link; do
        [[ -f "$link_file" ]] || continue
        [[ "$(basename "$link_file")" == 10-proxmenux-*.link ]] && continue
        if _pmx_link_matches_legacy_10 "$link_file"; then
            rm -f -- "$link_file"
            removed_legacy=$((removed_legacy + 1))
        fi
    done

    local count=0
    for dev_path in /sys/class/net/*; do
        iface=$(basename "$dev_path")
        case "$iface" in
            lo|docker*|veth*|br-*|vmbr*|tap*|fwpr*|fwln*|virbr*|bond*|cilium*|zt*|wg*)
                continue ;;
        esac
        [[ -e "$dev_path/device" || -e "$dev_path/phy80211" ]] || continue
        mac=$(cat "$dev_path/address" 2>/dev/null | tr '[:lower:]' '[:upper:]')
        [[ "$mac" =~ ^([A-F0-9]{2}:){5}[A-F0-9]{2}$ ]] || continue

        local link_file="$PMX_NIC_LINK_DIR/10-proxmenux-$iface.link"
        cat > "$link_file" <<EOF
$PMX_NIC_LINK_MARKER

[Match]
MACAddress=$mac

[Link]
Name=$iface
EOF
        chmod 644 "$link_file"
        count=$((count + 1))
    done

    printf 'COUNT=%d\n' "$count"
    printf 'REMOVED_STALE=%d\n' "$removed_stale"
    printf 'REMOVED_LEGACY=%d\n' "$removed_legacy"
}

# Remove only files that carry BOTH the ProxMenux filename prefix AND
# the marker on the first line. User-authored .link files are left
# intact regardless of their name.
pmx_uninstall_persistent_network() {
    local removed=0 link_file
    for link_file in "$PMX_NIC_LINK_DIR"/10-proxmenux-*.link; do
        [[ -f "$link_file" ]] || continue
        _pmx_link_is_managed "$link_file" || continue
        rm -f -- "$link_file"
        removed=$((removed + 1))
    done
    printf 'REMOVED=%d\n' "$removed"
}


# ==========================================================
# DKMS driver rebuild after a kernel upgrade
# ==========================================================
# Called from update-pve-safe.sh and proxmox_update.sh after
# apt full-upgrade succeeds. Detects whether a new kernel is
# staged for the next boot and, if so, ensures matching headers
# are installed and rebuilds every DKMS module registered by
# ProxMenux components against that kernel — so drivers keep
# working after the reboot without operator intervention.

readonly PMX_COMPONENTS_STATUS="/usr/local/share/proxmenux/components_status.json"

# component_key : dkms_module_name  (empty module = not DKMS)
readonly -a PMX_DKMS_COMPONENTS=(
    "nvidia_driver:nvidia"
    "coral_driver:gasket"
)

# Print the newest installed pve/proxmox kernel version, or empty.
_pmx_newest_installed_kernel() {
    dpkg-query -W -f='${Status}\t${Package}\n' \
        'proxmox-kernel-*-pve-signed' 'pve-kernel-*-pve' 2>/dev/null \
        | awk -F'\t' '/^install ok installed\t/ { print $2 }' \
        | sed -E 's/^(proxmox|pve)-kernel-//; s/-signed$//' \
        | sort -V | tail -1
}

# Return the header package name matching a kernel version.
_pmx_header_pkg_for_kernel() {
    local kver="$1"
    if apt-cache show "proxmox-headers-$kver" >/dev/null 2>&1; then
        printf 'proxmox-headers-%s\n' "$kver"
    else
        printf 'pve-headers-%s\n' "$kver"
    fi
}

# Return 0 if the DKMS module is 'installed' for the given kernel.
_pmx_dkms_module_installed_for_kernel() {
    local module="$1" kver="$2"
    command -v dkms >/dev/null 2>&1 || return 1
    dkms status 2>/dev/null | awk -v m="$module" -v k="$kver" '
        BEGIN { FS = "[,:]" }
        {
            gsub(/[[:space:]]/, "")
            if (index($0, m "/") == 1 && index($0, k) > 0 && $0 ~ /installed/) {
                found = 1; exit
            }
        }
        END { exit found ? 0 : 1 }
    '
}

# Best-effort rebuild. Never returns non-zero — the update flow that
# calls this must always complete regardless of driver state.
pmx_rebuild_dkms_after_kernel() {
    command -v dkms >/dev/null 2>&1 || return 0
    [[ -f "$PMX_COMPONENTS_STATUS" ]] || return 0
    command -v jq >/dev/null 2>&1 || return 0

    local running_kernel newest_kernel
    running_kernel=$(uname -r)
    newest_kernel=$(_pmx_newest_installed_kernel)
    [[ -z "$newest_kernel" || "$newest_kernel" == "$running_kernel" ]] && return 0

    local -a pending_components=() pending_modules=()
    local entry key module status
    for entry in "${PMX_DKMS_COMPONENTS[@]}"; do
        key="${entry%%:*}"
        module="${entry##*:}"
        status=$(jq -r --arg k "$key" '.[$k].status // ""' "$PMX_COMPONENTS_STATUS" 2>/dev/null)
        [[ "$status" == "installed" ]] || continue
        pending_components+=("$key")
        pending_modules+=("$module")
    done
    (( ${#pending_components[@]} == 0 )) && return 0

    local msg
    msg="$(translate 'A new kernel is staged for the next boot:')"$'\n'
    msg+="  ${newest_kernel}"$'\n\n'
    msg+="$(translate 'The following DKMS-managed drivers will now be rebuilt against it so they keep working after reboot:')"$'\n'
    local c
    for c in "${pending_components[@]}"; do
        msg+="  • $c"$'\n'
    done
    msg+=$'\n'"$(translate 'This may take a few minutes. Press OK to proceed.')"

    if [[ -t 0 ]] && command -v whiptail >/dev/null 2>&1; then
        whiptail --title "$(translate 'DKMS driver rebuild')" --msgbox "$msg" 18 78
    else
        msg_info "$(translate 'New kernel staged; rebuilding DKMS drivers:') ${pending_components[*]}"
    fi

    local header_pkg
    header_pkg=$(_pmx_header_pkg_for_kernel "$newest_kernel")
    if ! dpkg-query -W -f='${Status}' "$header_pkg" 2>/dev/null | grep -q 'install ok installed'; then
        msg_info "$(translate 'Installing kernel headers:') $header_pkg"
        if DEBIAN_FRONTEND=noninteractive apt-get install -y "$header_pkg" >/dev/null 2>&1; then
            msg_ok "$(translate 'Kernel headers installed')"
        else
            msg_warn "$(translate 'Kernel headers install failed — DKMS rebuild will likely fail:') $header_pkg"
        fi
    fi

    msg_info "$(translate 'Running dkms autoinstall for kernel') ${newest_kernel}..."
    dkms autoinstall -k "$newest_kernel" >/dev/null 2>&1 || true

    local -a failed_components=() failed_modules=()
    local i
    for i in "${!pending_components[@]}"; do
        if ! _pmx_dkms_module_installed_for_kernel "${pending_modules[$i]}" "$newest_kernel"; then
            failed_components+=("${pending_components[$i]}")
            failed_modules+=("${pending_modules[$i]}")
        fi
    done

    if (( ${#failed_components[@]} == 0 )); then
        msg_ok "$(translate 'DKMS drivers rebuilt for kernel') ${newest_kernel}: ${pending_components[*]}"
        return 0
    fi

    msg_warn "$(translate 'dkms autoinstall did not activate:') ${failed_components[*]}"
    msg_info "$(translate 'Falling back to each installer with --auto-reinstall...')"

    declare -A installer_for=(
        [nvidia_driver]="/usr/local/share/proxmenux/scripts/gpu_tpu/nvidia_installer.sh"
        [coral_driver]="/usr/local/share/proxmenux/scripts/gpu_tpu/install_coral.sh"
    )
    local comp installer still_failing=()
    for comp in "${failed_components[@]}"; do
        installer="${installer_for[$comp]:-}"
        [[ -n "$installer" && -x "$installer" ]] || {
            still_failing+=("$comp")
            continue
        }
        msg_info "$(translate 'Reinstalling') $comp..."
        if bash "$installer" --auto-reinstall >/dev/null 2>&1; then
            msg_ok "$(translate 'Reinstalled') $comp"
        else
            still_failing+=("$comp")
        fi
    done

    if (( ${#still_failing[@]} > 0 )); then
        msg_warn "$(translate 'The following drivers could not be rebuilt for the new kernel — run their installer manually after reboot:') ${still_failing[*]}"
    else
        msg_ok "$(translate 'DKMS drivers reinstalled for kernel') ${newest_kernel}"
    fi
    return 0
}
