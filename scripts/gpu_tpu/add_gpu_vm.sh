#!/bin/bash
# ==========================================================
# ProxMenux - GPU Passthrough to Virtual Machine (VM)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 03/04/2026
# ==========================================================
# Description:
# Automates full GPU passthrough (VFIO) from Proxmox host to a VM.
# Supports Intel iGPU, AMD and NVIDIA GPUs.
#
# Features:
#  - IOMMU detection and activation offer
#  - Multi-GPU selection menu
#  - IOMMU group analysis (all group devices passed together)
#  - Single-GPU warning (host loses physical video output)
#  - Switch mode: detects GPU used in LXC or another VM
#  - AMD ROM dump via sysfs
#  - Idempotent host config (modules, vfio.conf, blacklist)
#  - VM config: hostpci entries, NVIDIA KVM hiding
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
TOOLS_JSON="$BASE_DIR/installed_tools.json"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
    LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
    UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
    UTILS_FILE="$BASE_DIR/utils.sh"
fi
LOG_FILE="/tmp/add_gpu_vm.log"
screen_capture="/tmp/proxmenux_add_gpu_vm_screen_$$.txt"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/pci_passthrough_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/pci_passthrough_helpers.sh"
fi
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/gpu_hook_guard_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/gpu_hook_guard_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/gpu_hook_guard_helpers.sh" ]]; then
    source "$LOCAL_SCRIPTS_DEFAULT/global/gpu_hook_guard_helpers.sh"
fi

load_language
initialize_cache

# ==========================================================
# Global state
# ==========================================================
declare -a ALL_GPU_PCIS=()       # "0000:01:00.0"
declare -a ALL_GPU_TYPES=()      # intel / amd / nvidia
declare -a ALL_GPU_NAMES=()      # human-readable name
declare -a ALL_GPU_DRIVERS=()    # current kernel driver

SELECTED_GPU=""                  # intel / amd / nvidia
SELECTED_GPU_PCI=""              # 0000:01:00.0
SELECTED_GPU_NAME=""

declare -a IOMMU_DEVICES=()      # all PCI addrs in IOMMU group (endpoint devices)
declare -a IOMMU_VFIO_IDS=()    # vendor:device for vfio-pci ids=
declare -a EXTRA_AUDIO_DEVICES=() # sibling audio function(s), typically *.1
declare -a EXTRA_AUDIO_INFO=()    # parallel to EXTRA_AUDIO_DEVICES — "BDF|current_driver" pairs for the summary dialog
IOMMU_GROUP=""
IOMMU_PENDING_REBOOT=false

SELECTED_VMID=""
VM_NAME=""

GPU_COUNT=0
SINGLE_GPU_SYSTEM=false

SWITCH_FROM_LXC=false
SWITCH_LXC_LIST=""
SWITCH_FROM_VM=false
SWITCH_VM_SRC=""
SWITCH_VM_ACTION=""   # keep_gpu_disable_onboot | remove_gpu_keep_onboot
TARGET_VM_ALREADY_HAS_GPU=false
VM_SWITCH_ALREADY_VFIO=false
PREFLIGHT_HOST_REBOOT_REQUIRED=true

AMD_ROM_FILE=""

HOST_CONFIG_CHANGED=false   # set to true whenever host VFIO config is actually written

PRESELECT_VMID=""
WIZARD_CALL=false
GPU_WIZARD_RESULT_FILE=""

declare -a LXC_AFFECTED_CTIDS=()
declare -a LXC_AFFECTED_NAMES=()
declare -a LXC_AFFECTED_RUNNING=()   # 1 or 0
declare -a LXC_AFFECTED_ONBOOT=()    # 1 or 0
LXC_SWITCH_ACTION=""                  # keep_gpu_disable_onboot | remove_gpu_keep_onboot


# ==========================================================
# Helpers
# ==========================================================
_get_pci_driver() {
    local pci_full="$1"
    local driver_link="/sys/bus/pci/devices/${pci_full}/driver"
    if [[ -L "$driver_link" ]]; then
        basename "$(readlink "$driver_link")"
    else
        echo "none"
    fi
}

_add_line_if_missing() {
    local line="$1"
    local file="$2"
    touch "$file"
    if ! grep -qF "$line" "$file"; then
        echo "$line" >> "$file"
        HOST_CONFIG_CHANGED=true
    fi
}

_append_unique() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 1
    done
    return 0
}

_vm_is_running() {
    local vmid="$1"
    qm status "$vmid" 2>/dev/null | grep -q "status: running"
}

_vm_onboot_enabled() {
    local vmid="$1"
    qm config "$vmid" 2>/dev/null | grep -qE "^onboot:\s*1"
}

_ct_is_running() {
    local ctid="$1"
    pct status "$ctid" 2>/dev/null | grep -q "status: running"
}

_ct_onboot_enabled() {
    local ctid="$1"
    pct config "$ctid" 2>/dev/null | grep -qE "^onboot:\s*1"
}

_lxc_conf_uses_selected_gpu() {
    local conf="$1"
    case "$SELECTED_GPU" in
        nvidia)
            grep -qE "dev[0-9]+:.*(/dev/nvidia|/dev/nvidia-caps)" "$conf" 2>/dev/null
            ;;
        amd)
            grep -qE "dev[0-9]+:.*(/dev/dri|/dev/kfd)|lxc\.mount\.entry:.*dev/dri" "$conf" 2>/dev/null
            ;;
        intel)
            grep -qE "dev[0-9]+:.*(/dev/dri)|lxc\.mount\.entry:.*dev/dri" "$conf" 2>/dev/null
            ;;
        *)
            grep -qE "dev[0-9]+:.*(/dev/dri|/dev/nvidia|/dev/kfd)|lxc\.mount\.entry:.*dev/dri" "$conf" 2>/dev/null
            ;;
    esac
}

_lxc_switch_action_label() {
    case "$LXC_SWITCH_ACTION" in
        keep_gpu_disable_onboot) echo "$(translate 'Keep GPU in LXC config + disable Start on boot')" ;;
        remove_gpu_keep_onboot) echo "$(translate 'Remove GPU from LXC config + keep Start on boot unchanged')" ;;
        *) echo "$(translate 'No specific LXC action selected')" ;;
    esac
}

_vm_switch_action_label() {
    case "$SWITCH_VM_ACTION" in
        keep_gpu_disable_onboot) echo "$(translate 'Keep GPU in source VM config + disable Start on boot if enabled')" ;;
        remove_gpu_keep_onboot) echo "$(translate 'Remove GPU from source VM config + keep Start on boot unchanged')" ;;
        *) echo "$(translate 'No specific VM action selected')" ;;
    esac
}

_gpu_register_vfio_iommu_tool() {
    command -v jq >/dev/null 2>&1 || return 0
    [[ -f "$TOOLS_JSON" ]] || echo "{}" > "$TOOLS_JSON"
    jq '.vfio_iommu=true' "$TOOLS_JSON" > "$TOOLS_JSON.tmp" \
        && mv "$TOOLS_JSON.tmp" "$TOOLS_JSON" || true
}

_set_wizard_result() {
    local result="$1"
    [[ -z "${GPU_WIZARD_RESULT_FILE:-}" ]] && return 0
    printf '%s\n' "$result" >"$GPU_WIZARD_RESULT_FILE" 2>/dev/null || true
}

# ==========================================================
# UI wrapper helpers — dialog in standalone, whiptail in wizard
# ==========================================================
# Strips dialog color sequences (\Zb, \Z1, \Zn, etc.) from a string
_strip_colors() {
    printf '%s' "$1" | sed 's/\\Z[0-9a-zA-Z]//g'
}

# Msgbox: dialog in standalone mode, whiptail in wizard mode.
# I/O pinned to /dev/tty so the dialog renders reliably regardless of
# how the caller redirected stdin/stdout, and immune to the SIGTTOU
# trap that fires when this script is resumed as a background job.
_pmx_msgbox() {
    local title="$1" msg="$2" h="${3:-10}" w="${4:-72}"
    if [[ "$WIZARD_CALL" == "true" ]]; then
        whiptail --backtitle "ProxMenux" --title "$title" \
            --msgbox "$(_strip_colors "$msg")" "$h" "$w" < /dev/tty > /dev/tty
    else
        dialog --backtitle "ProxMenux" --colors \
            --title "$title" --msgbox "$msg" "$h" "$w" < /dev/tty > /dev/tty
    fi
}

# Yesno: dialog in standalone mode, whiptail in wizard mode.
# Returns 0 for yes, 1 for no (same as dialog/whiptail).
# I/O pinned to /dev/tty — see the note on _pmx_msgbox.
_pmx_yesno() {
    local title="$1" msg="$2" h="${3:-10}" w="${4:-72}"
    if [[ "$WIZARD_CALL" == "true" ]]; then
        whiptail --backtitle "ProxMenux" --title "$title" \
            --yesno "$(_strip_colors "$msg")" "$h" "$w" < /dev/tty > /dev/tty
    else
        dialog --backtitle "ProxMenux" --colors \
            --title "$title" --yesno "$msg" "$h" "$w" < /dev/tty > /dev/tty
    fi
    return $?
}

# Menu: dialog in standalone mode, whiptail in wizard mode
# Accepts optional --default-item VALUE before title
# Usage: _pmx_menu [--default-item VAL] title msg h w list_h item desc ...
_pmx_menu() {
    local -a extra_opts=()
    while [[ "${1:-}" == --* ]]; do
        case "$1" in
            --default-item) extra_opts+=("--default-item" "$2"); shift 2 ;;
            *) shift ;;
        esac
    done
    local title="$1" msg="$2" h="$3" w="$4" lh="$5"
    shift 5
    if [[ "$WIZARD_CALL" == "true" ]]; then
        whiptail --backtitle "ProxMenux" "${extra_opts[@]}" \
            --title "$title" \
            --menu "$(_strip_colors "$msg")" "$h" "$w" "$lh" \
            "$@" 3>&1 1>&2 2>&3
    else
        dialog --backtitle "ProxMenux" --colors "${extra_opts[@]}" \
            --title "$title" \
            --menu "$msg" "$h" "$w" "$lh" \
            "$@" 2>&1 >/dev/tty
    fi
    return $?
}

# Checklist: dialog in standalone mode, whiptail in wizard mode.
# Usage: _pmx_checklist title msg h w list_h tag1 desc1 state1 tag2 desc2 state2 ...
# state is "on" or "off". Returns the space-separated list of selected
# tags on stdout (one line). Returns non-zero if the user cancels.
_pmx_checklist() {
    local title="$1" msg="$2" h="$3" w="$4" lh="$5"
    shift 5
    if [[ "$WIZARD_CALL" == "true" ]]; then
        whiptail --backtitle "ProxMenux" \
            --title "$title" \
            --checklist "$(_strip_colors "$msg")" "$h" "$w" "$lh" \
            "$@" 3>&1 1>&2 2>&3
    else
        dialog --backtitle "ProxMenux" --colors \
            --title "$title" \
            --checklist "$msg" "$h" "$w" "$lh" \
            "$@" 2>&1 >/dev/tty
    fi
    return $?
}

_file_has_exact_line() {
    local line="$1"
    local file="$2"
    [[ -f "$file" ]] || return 1
    grep -qFx "$line" "$file"
}

evaluate_host_reboot_requirement() {
    if [[ "$IOMMU_PENDING_REBOOT" == "true" ]]; then
        PREFLIGHT_HOST_REBOOT_REQUIRED=true
        return 0
    fi

    # Fast path for VM-to-VM reassignment where GPU is already bound to vfio
    if [[ "$VM_SWITCH_ALREADY_VFIO" == "true" ]]; then
        PREFLIGHT_HOST_REBOOT_REQUIRED=false
        return 0
    fi

    local needs_change=false
    local current_driver
    current_driver=$(_get_pci_driver "$SELECTED_GPU_PCI")
    [[ "$current_driver" != "vfio-pci" ]] && needs_change=true

    # /etc/modules expected lines
    local modules_file="/etc/modules"
    local modules=("vfio" "vfio_iommu_type1" "vfio_pci")
    local kernel_major kernel_minor
    kernel_major=$(uname -r | cut -d. -f1)
    kernel_minor=$(uname -r | cut -d. -f2)
    if (( kernel_major < 6 || ( kernel_major == 6 && kernel_minor < 2 ) )); then
        modules+=("vfio_virqfd")
    fi
    local mod
    for mod in "${modules[@]}"; do
        _file_has_exact_line "$mod" "$modules_file" || needs_change=true
    done

    # vfio-pci ids
    local vfio_conf="/etc/modprobe.d/vfio.conf"
    local ids_line ids_part
    ids_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
    if [[ -z "$ids_line" ]]; then
        needs_change=true
    else
        [[ "$ids_line" == *"disable_vga=1"* ]] || needs_change=true
        ids_part=$(echo "$ids_line" | grep -oE 'ids=[^[:space:]]+' | sed 's/ids=//')
        local existing_ids=()
        IFS=',' read -ra existing_ids <<< "$ids_part"
        local required found existing
        for required in "${IOMMU_VFIO_IDS[@]}"; do
            found=false
            for existing in "${existing_ids[@]}"; do
                [[ "$existing" == "$required" ]] && found=true && break
            done
            $found || needs_change=true
        done
    fi

    # modprobe options files
    _file_has_exact_line "options vfio_iommu_type1 allow_unsafe_interrupts=1" \
        /etc/modprobe.d/iommu_unsafe_interrupts.conf || needs_change=true
    _file_has_exact_line "options kvm ignore_msrs=1" \
        /etc/modprobe.d/kvm.conf || needs_change=true

    # AMD softdep
    if [[ "$SELECTED_GPU" == "amd" ]]; then
        _file_has_exact_line "softdep radeon pre: vfio-pci" "$vfio_conf" || needs_change=true
        _file_has_exact_line "softdep amdgpu pre: vfio-pci" "$vfio_conf" || needs_change=true
        _file_has_exact_line "softdep snd_hda_intel pre: vfio-pci" "$vfio_conf" || needs_change=true
    fi

    # host driver blacklist
    local blacklist_file="/etc/modprobe.d/blacklist.conf"
    case "$SELECTED_GPU" in
        nvidia)
            _file_has_exact_line "blacklist nouveau" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist nvidia" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist nvidia_drm" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist nvidia_modeset" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist nvidia_uvm" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist nvidiafb" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist lbm-nouveau" "$blacklist_file" || needs_change=true
            _file_has_exact_line "options nouveau modeset=0" "$blacklist_file" || needs_change=true
            [[ -f /etc/modules-load.d/nvidia-vfio.conf ]] && needs_change=true
            grep -qE '^(nvidia|nvidia_uvm|nvidia_drm|nvidia_modeset)$' /etc/modules 2>/dev/null && needs_change=true
            local svc
            for svc in nvidia-persistenced.service nvidia-persistenced nvidia-powerd.service nvidia-fabricmanager.service; do
                if systemctl is-active --quiet "$svc" 2>/dev/null || systemctl is-enabled --quiet "$svc" 2>/dev/null; then
                    needs_change=true
                fi
            done
            ;;
        amd)
            _file_has_exact_line "blacklist radeon" "$blacklist_file" || needs_change=true
            _file_has_exact_line "blacklist amdgpu" "$blacklist_file" || needs_change=true
            ;;
        intel)
            _file_has_exact_line "blacklist i915" "$blacklist_file" || needs_change=true
            ;;
    esac

    if [[ "$needs_change" == "true" ]]; then
        PREFLIGHT_HOST_REBOOT_REQUIRED=true
    else
        PREFLIGHT_HOST_REBOOT_REQUIRED=false
    fi
}

parse_cli_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --vmid)
                if [[ -n "${2:-}" ]]; then
                    PRESELECT_VMID="$2"
                    shift 2
                else
                    shift
                fi
                ;;
            --wizard)
                WIZARD_CALL=true
                shift
                ;;
            --result-file)
                if [[ -n "${2:-}" ]]; then
                    GPU_WIZARD_RESULT_FILE="$2"
                    shift 2
                else
                    shift
                fi
                ;;
            *)
                shift
                ;;
        esac
    done
}

_get_vm_run_title() {
    if [[ "$SWITCH_FROM_LXC" == "true" && "$SWITCH_FROM_VM" == "true" ]]; then
        echo "$(translate 'GPU Passthrough to VM (reassign from LXC and another VM)')"
    elif [[ "$SWITCH_FROM_LXC" == "true" ]]; then
        echo "$(translate 'GPU Passthrough to VM (from LXC)')"
    elif [[ "$SWITCH_FROM_VM" == "true" ]]; then
        echo "$(translate 'GPU Passthrough to VM (reassign from another VM)')"
    else
        echo "$(translate 'GPU Passthrough to VM')"
    fi
}

_is_pci_slot_assigned_to_vm() {
    if declare -F _pci_slot_assigned_to_vm >/dev/null 2>&1; then
        _pci_slot_assigned_to_vm "$1" "$2"
        return $?
    fi

    local pci_full="$1"
    local vmid="$2"
    local slot_base
    slot_base="${pci_full#0000:}"
    slot_base="${slot_base%.*}"   # 01:00

    qm config "$vmid" 2>/dev/null \
        | grep -qE "^hostpci[0-9]+:.*(0000:)?${slot_base}(\\.[0-7])?([,[:space:]]|$)"
}

# Match a specific PCI function when possible.
# For function .0, also accept slot-only entries (e.g. 01:00) as equivalent.
_is_pci_function_assigned_to_vm() {
    if declare -F _pci_function_assigned_to_vm >/dev/null 2>&1; then
        _pci_function_assigned_to_vm "$1" "$2"
        return $?
    fi

    local pci_full="$1"
    local vmid="$2"
    local bdf slot func pattern
    bdf="${pci_full#0000:}"      # 01:00.0
    slot="${bdf%.*}"             # 01:00
    func="${bdf##*.}"            # 0

    if [[ "$func" == "0" ]]; then
        pattern="^hostpci[0-9]+:.*(0000:)?(${bdf}|${slot})([,:[:space:]]|$)"
    else
        pattern="^hostpci[0-9]+:.*(0000:)?${bdf}([,[:space:]]|$)"
    fi

    qm config "$vmid" 2>/dev/null | grep -qE "$pattern"
}

ensure_selected_gpu_not_already_in_target_vm() {
    while _is_pci_slot_assigned_to_vm "$SELECTED_GPU_PCI" "$SELECTED_VMID"; do
        local current_driver
        current_driver=$(_get_pci_driver "$SELECTED_GPU_PCI")

        # GPU is already assigned to this VM, but host is not in VFIO mode.
        # Continue so the script can re-activate VM passthrough on the host.
        if [[ "$current_driver" != "vfio-pci" ]]; then
            TARGET_VM_ALREADY_HAS_GPU=true
            local popup_title
            popup_title=$(_get_vm_run_title)
            _pmx_msgbox "${popup_title}" \
                "\n$(translate 'The selected GPU is already assigned to this VM, but the host is not currently using vfio-pci for this device.')\n\n$(translate 'Current driver'): ${current_driver}\n\n$(translate 'The script will continue to restore VM passthrough mode on the host and reuse existing hostpci entries.')" \
                13 78
            return 0
        fi

        # Single GPU system: nothing else to choose
        if [[ $GPU_COUNT -le 1 ]]; then
            _pmx_msgbox "$(translate 'GPU Already Added')" \
                "\n$(translate 'The selected GPU is already assigned to this VM.')\n\n$(translate 'No changes are required.')" \
                9 66
            exit 0
        fi

        # Build menu with GPUs that are NOT already assigned to this VM
        local menu_items=()
        local i available
        available=0
        for i in "${!ALL_GPU_PCIS[@]}"; do
            local pci label
            pci="${ALL_GPU_PCIS[$i]}"
            _is_pci_slot_assigned_to_vm "$pci" "$SELECTED_VMID" && continue
            label="${ALL_GPU_NAMES[$i]} [${ALL_GPU_DRIVERS[$i]}] — ${pci}"
            menu_items+=("$i" "$label")
            available=$((available + 1))
        done

        if [[ $available -eq 0 ]]; then
            _pmx_msgbox "$(translate 'All GPUs Already Assigned')" \
                "\n$(translate 'All detected GPUs are already assigned to this VM.')\n\n$(translate 'No additional GPU can be added.')" \
                10 70
            exit 0
        fi

        local choice
        choice=$(_pmx_menu \
            "$(translate 'GPU Already Assigned to This VM')" \
            "\n$(translate 'The selected GPU is already present in this VM. Select another GPU to continue:')" \
            18 82 10 \
            "${menu_items[@]}") || exit 0

        SELECTED_GPU="${ALL_GPU_TYPES[$choice]}"
        SELECTED_GPU_PCI="${ALL_GPU_PCIS[$choice]}"
        SELECTED_GPU_NAME="${ALL_GPU_NAMES[$choice]}"
    done
}


# ==========================================================
# Phase 1 — Step 1: Detect host GPUs
# ==========================================================
detect_host_gpus() {
    while IFS= read -r line; do
        local pci_short pci_full name type driver pci_info
        pci_short=$(echo "$line" | awk '{print $1}')
        pci_full="0000:${pci_short}"

        # Prefer full vendor/model descriptor for clearer menus.
        pci_info=$(lspci -nn -s "${pci_short}" 2>/dev/null | sed 's/^[^ ]* //')
        name="${pci_info#*: }"
        [[ "$name" == "$pci_info" ]] && name="$pci_info"
        name=$(echo "$name" | sed -E 's/ \(rev [^)]+\)$//' | cut -c1-72)
        [[ -z "$name" ]] && name="$(translate 'Unknown GPU')"

        if echo "$line" | grep -qi "Intel"; then
            type="intel"
        elif echo "$line" | grep -qiE "AMD|Advanced Micro|Radeon"; then
            type="amd"
        elif echo "$line" | grep -qi "NVIDIA"; then
            type="nvidia"
        else
            type="other"
        fi

        driver=$(_get_pci_driver "$pci_full")

        ALL_GPU_PCIS+=("$pci_full")
        ALL_GPU_TYPES+=("$type")
        ALL_GPU_NAMES+=("$name")
        ALL_GPU_DRIVERS+=("$driver")

    done < <(lspci -nn | grep -iE "VGA compatible controller|3D controller|Display controller" \
                        | grep -iv "Ethernet\|Network\|Audio")

    GPU_COUNT=${#ALL_GPU_PCIS[@]}

    if [[ $GPU_COUNT -eq 0 ]]; then
        _set_wizard_result "no_gpu"
        _pmx_msgbox "$(translate 'No GPU Detected')" \
            "\n$(translate 'No compatible GPU was detected on this host.')" 8 60
        exit 0
    fi

    [[ $GPU_COUNT -eq 1 ]] && SINGLE_GPU_SYSTEM=true
}


# ==========================================================
# Phase 1 — Step 2: Check IOMMU, offer to enable it
# ==========================================================
check_iommu_enabled() {
    # Dedup: if IOMMU was already configured by another script in this wizard run, skip prompt
    if [[ "${VM_STORAGE_IOMMU_PENDING_REBOOT:-0}" == "1" ]]; then
        IOMMU_PENDING_REBOOT=true
        HOST_CONFIG_CHANGED=true
        _gpu_register_vfio_iommu_tool
        return 0
    fi

    if declare -F _pci_is_iommu_active >/dev/null 2>&1 && _pci_is_iommu_active; then
        _gpu_register_vfio_iommu_tool
        return 0
    fi

    local configured_next_boot=false
    if grep -qE 'intel_iommu=on|amd_iommu=on' /etc/kernel/cmdline 2>/dev/null || \
       grep -qE 'intel_iommu=on|amd_iommu=on' /etc/default/grub 2>/dev/null; then
        configured_next_boot=true
    fi

    if [[ "$configured_next_boot" == "true" ]]; then
        IOMMU_PENDING_REBOOT=true
        HOST_CONFIG_CHANGED=true
        _gpu_register_vfio_iommu_tool
        VM_STORAGE_IOMMU_PENDING_REBOOT=1
        export VM_STORAGE_IOMMU_PENDING_REBOOT
        _pmx_msgbox "$(translate 'IOMMU Pending Reboot')" \
            "\n$(translate 'IOMMU is already configured for next boot, but it is not active yet.')\n\n$(translate 'GPU passthrough configuration will continue now and will become effective after host reboot.')" \
            11 78
        return 0
    fi

    local msg
    msg="\n$(translate 'IOMMU is not active on this system.')\n\n"
    msg+="$(translate 'GPU passthrough to VMs requires IOMMU to be enabled in the kernel.')\n\n"
    msg+="$(translate 'Do you want to enable IOMMU now?')\n\n"
    msg+="$(translate 'Note: A system reboot will be required after enabling IOMMU.')\n"
    msg+="$(translate 'Configuration will continue now and be effective after reboot.')"

    _pmx_yesno "$(translate 'IOMMU Required')" "$msg" 15 72

    local response=$?
    [[ "$WIZARD_CALL" != "true" ]] && clear

    if [[ $response -eq 0 ]]; then
        [[ "$WIZARD_CALL" != "true" ]] && show_proxmenux_logo
        msg_title "$(translate 'Enabling IOMMU')"
        if ! _enable_iommu_cmdline; then
            echo
            msg_error "$(translate 'Failed to configure IOMMU automatically.')"
            echo
            msg_success "$(translate 'Press Enter to continue...')"
            read -r
            exit 0
        fi
        IOMMU_PENDING_REBOOT=true
        HOST_CONFIG_CHANGED=true
        _gpu_register_vfio_iommu_tool
        VM_STORAGE_IOMMU_PENDING_REBOOT=1
        export VM_STORAGE_IOMMU_PENDING_REBOOT
        echo
        msg_success "$(translate 'IOMMU configured. GPU passthrough setup will continue now and will be effective after reboot.')"
        echo
        if [[ "$WIZARD_CALL" != "true" ]]; then
            msg_success "$(translate 'Press Enter to continue...')"
            read -r
        fi
        return 0
    fi
    exit 0
}

_enable_iommu_cmdline() {
    local cpu_vendor
    cpu_vendor=$(grep -m1 "vendor_id" /proc/cpuinfo 2>/dev/null | awk '{print $3}')

    local iommu_param
    if [[ "$cpu_vendor" == "GenuineIntel" ]]; then
        iommu_param="intel_iommu=on"
        msg_info "$(translate 'Intel CPU detected')"
    elif [[ "$cpu_vendor" == "AuthenticAMD" ]]; then
        iommu_param="amd_iommu=on"
        msg_info "$(translate 'AMD CPU detected')"
    else
        msg_error "$(translate 'Unknown CPU vendor. Cannot determine IOMMU parameter.')"
        return 1
    fi

    local cmdline_file="/etc/kernel/cmdline"
    local grub_file="/etc/default/grub"

    if [[ -f "$cmdline_file" ]] && grep -qE 'root=ZFS=|root=ZFS/' "$cmdline_file" 2>/dev/null; then
        # systemd-boot / ZFS
        if ! grep -q "$iommu_param" "$cmdline_file"; then
            cp "$cmdline_file" "${cmdline_file}.bak.$(date +%Y%m%d_%H%M%S)"
            sed -i "s|\\s*$| ${iommu_param} iommu=pt|" "$cmdline_file"
            proxmox-boot-tool refresh >/dev/null 2>&1 || true
            msg_ok "$(translate 'IOMMU parameters added to /etc/kernel/cmdline')"
        else
            msg_ok "$(translate 'IOMMU already configured in /etc/kernel/cmdline')"
        fi
    elif [[ -f "$grub_file" ]]; then
        # GRUB
        if ! grep -q "$iommu_param" "$grub_file"; then
            cp "$grub_file" "${grub_file}.bak.$(date +%Y%m%d_%H%M%S)"
            sed -i "/GRUB_CMDLINE_LINUX_DEFAULT=/ s|\"$| ${iommu_param} iommu=pt\"|" "$grub_file"
            update-grub >/dev/null 2>&1 || true
            msg_ok "$(translate 'IOMMU parameters added to GRUB')"
        else
            msg_ok "$(translate 'IOMMU already configured in GRUB')"
        fi
    else
        msg_error "$(translate 'Neither /etc/kernel/cmdline nor /etc/default/grub found.')"
        return 1
    fi
}


# ==========================================================
# Phase 1 — Step 3: GPU selection
# ==========================================================
select_gpu() {
    # Single GPU: auto-select, no menu needed
    if [[ $GPU_COUNT -eq 1 ]]; then
        SELECTED_GPU="${ALL_GPU_TYPES[0]}"
        SELECTED_GPU_PCI="${ALL_GPU_PCIS[0]}"
        SELECTED_GPU_NAME="${ALL_GPU_NAMES[0]}"
        return 0
    fi

    # Multiple GPUs: show menu
    local menu_items=()
    local i
    for i in "${!ALL_GPU_PCIS[@]}"; do
        local label="${ALL_GPU_NAMES[$i]} [${ALL_GPU_DRIVERS[$i]}] — ${ALL_GPU_PCIS[$i]}"
        menu_items+=("$i" "$label")
    done

    local choice
    choice=$(_pmx_menu \
        "$(translate 'Select GPU for VM Passthrough')" \
        "\n$(translate 'Select the GPU to pass through to the VM:')" \
        18 82 10 \
        "${menu_items[@]}") || exit 0

    SELECTED_GPU="${ALL_GPU_TYPES[$choice]}"
    SELECTED_GPU_PCI="${ALL_GPU_PCIS[$choice]}"
    SELECTED_GPU_NAME="${ALL_GPU_NAMES[$choice]}"
}


# ==========================================================
# SR-IOV guard — refuse to assign a Virtual Function or a Physical
# Function with active VFs. Matches the policy in switch_gpu_mode.sh:
# writing this GPU's vendor:device to /etc/modprobe.d/vfio.conf would
# let vfio-pci claim the PF at next boot and destroy the whole VF
# tree. ProxMenux does not yet manage SR-IOV lifecycle, so we stop
# before touching vfio.conf / blacklist.conf.
# ==========================================================
check_sriov_and_block_if_needed() {
    declare -F _pci_sriov_role >/dev/null 2>&1 || return 0
    [[ -n "$SELECTED_GPU_PCI" ]] || return 0

    local role first_word detail=""
    role=$(_pci_sriov_role "$SELECTED_GPU_PCI")
    first_word="${role%% *}"

    case "$first_word" in
        vf)
            local parent="${role#vf }"
            detail="$(translate 'The selected device') \Zb${SELECTED_GPU_PCI}\Zn $(translate 'is an SR-IOV Virtual Function (VF). Its parent Physical Function is') \Zb${parent}\Zn."
            ;;
        pf-active)
            local n="${role#pf-active }"
            detail="$(translate 'The selected device') \Zb${SELECTED_GPU_PCI}\Zn $(translate 'is a Physical Function with') \Zb${n}\Zn $(translate 'active Virtual Functions. Changing its driver binding would destroy every VF.')"
            ;;
        *)
            return 0
            ;;
    esac

    local msg
    msg="\n\Zb\Z6$(translate 'SR-IOV Configuration Detected')\Zn\n\n"
    msg+="${detail}\n\n"
    msg+="$(translate 'To assign VFs to VMs or LXCs, edit the configuration manually via the Proxmox web interface. The Physical Function will remain bound to the native driver.')"

    _pmx_msgbox "$(translate 'SR-IOV Configuration Detected')" "$msg" 16 82

    [[ "$WIZARD_CALL" == "true" ]] && _set_wizard_result "cancelled"
    exit 0
}


# ==========================================================
# Phase 1 — Step 4: Single-GPU warning
# ==========================================================
warn_single_gpu() {
    [[ "$SINGLE_GPU_SYSTEM" != "true" ]] && return 0

    local msg
    msg="\n\Zb\Z1⚠  $(translate 'WARNING: This is a single GPU system')\Zn\n\n"
    msg+="$(translate 'When this GPU is passed through to a VM, the Proxmox host will lose all video output on the physical monitor.')\n\n"
    msg+="$(translate 'After the reboot, you will only be able to access the Proxmox host via:')\n"
    msg+="  •  SSH\n"
    msg+="  •  Proxmox Web UI (https)\n"
    msg+="  •  Serial console\n\n"
    msg+="$(translate 'The VM guest will have exclusive access to the GPU.')\n\n"
    msg+="\Z1$(translate 'Important: some GPUs may still fail in passthrough and can affect host stability or overall performance depending on hardware/firmware quality.')\Zn\n\n"
    msg+="$(translate 'Make sure you have SSH or Web UI access before rebooting.')\n\n"
    msg+="$(translate 'Do you want to continue?')"

    _pmx_yesno "$(translate 'Single GPU Warning')" "$msg" 22 76

    [[ $? -ne 0 ]] && exit 0
}


# ==========================================================
# Phase 1 — Step 4b: Hardware passthrough compatibility check
# ==========================================================

# Returns: apu | dedicated | unknown
_detect_amd_gpu_subtype() {
    local name_lower
    name_lower=$(echo "$SELECTED_GPU_NAME" | tr '[:upper:]' '[:lower:]')

    # Known AMD APU / integrated GPU codenames (mobile and desktop)
    local apu_codenames=(
        "lucienne" "renoir" "cezanne" "van gogh" "barcelo"
        "rembrandt" "phoenix" "hawk point" "strix" "mendocino"
        "pollock" "raphael" "dragon range" "raven" "picasso"
    )
    for codename in "${apu_codenames[@]}"; do
        echo "$name_lower" | grep -qi "$codename" && echo "apu" && return
    done

    # Markers of discrete / dedicated cards
    if echo "$name_lower" | grep -qiE "radeon rx|radeon pro|radeon vii|radeon r[0-9]|firepro|instinct|navi|polaris|vega|fiji|ellesmere|baffin"; then
        echo "dedicated"
        return
    fi

    echo "unknown"
}

# Returns: flr | bus | pm | none | unknown
_check_pci_reset_method() {
    local pci_full="$1"
    local reset_file="/sys/bus/pci/devices/${pci_full}/reset_method"

    if [[ ! -f "$reset_file" ]]; then
        [[ -f "/sys/bus/pci/devices/${pci_full}/reset" ]] && echo "unknown" || echo "none"
        return
    fi

    local method
    method=$(cat "$reset_file" 2>/dev/null)
    echo "$method" | grep -q "flr" && echo "flr" && return
    echo "$method" | grep -q "pm"  && echo "pm"  && return
    echo "$method" | grep -q "bus" && echo "bus" && return
    echo "unknown"
}

# Returns: igpu | dedicated | unknown
_detect_intel_gpu_subtype() {
    local name_lower pci_full
    name_lower=$(echo "$SELECTED_GPU_NAME" | tr '[:upper:]' '[:lower:]')
    pci_full="$SELECTED_GPU_PCI"

    # Typical integrated Intel GPU PCI function
    [[ "$pci_full" == "0000:00:02.0" ]] && echo "igpu" && return

    # Common integrated markers
    if echo "$name_lower" | grep -qiE "uhd|hd graphics|iris|xe graphics|integrated"; then
        echo "igpu"
        return
    fi

    # Common dedicated markers (Intel Arc family)
    if echo "$name_lower" | grep -qiE "arc|a3[0-9]{2}|a5[0-9]{2}|a7[0-9]{2}|a7[5-9]0|b5[0-9]{2}|b7[0-9]{2}"; then
        echo "dedicated"
        return
    fi

    echo "unknown"
}

check_intel_vm_compatibility() {
    local pci_full="$SELECTED_GPU_PCI"
    local gpu_subtype reset_method power_state vendor device viddid

    gpu_subtype=$(_detect_intel_gpu_subtype)
    reset_method=$(_check_pci_reset_method "$pci_full")
    power_state=$(cat "/sys/bus/pci/devices/${pci_full}/power_state" 2>/dev/null | tr -d '[:space:]')
    vendor=$(cat "/sys/bus/pci/devices/${pci_full}/vendor" 2>/dev/null | sed 's/0x//' | tr '[:upper:]' '[:lower:]')
    device=$(cat "/sys/bus/pci/devices/${pci_full}/device" 2>/dev/null | sed 's/0x//' | tr '[:upper:]' '[:lower:]')
    viddid="${vendor}:${device}"

    # ── BLOCKER: Known unsupported Intel Apollo Lake iGPU IDs ────────────
    if [[ "$viddid" == "8086:5a84" || "$viddid" == "8086:5a85" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'GPU Not Compatible with VM Passthrough')\Zn\n\n"
        msg+="$(translate 'The selected Intel GPU belongs to Apollo Lake generation and is blocked by policy for VM passthrough due to host instability risk.')\n\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n"
        msg+="  \ZbID: ${viddid}\Zn\n\n"
        msg+="$(translate 'This GPU is considered incompatible with GPU passthrough to a VM in ProxMenux.')\n\n"
        msg+="$(translate 'Recommended: use GPU with LXC workloads instead of VM passthrough on this hardware.')"

        _pmx_msgbox "$(translate 'Blocked GPU ID')" "$msg" 20 84
        exit 0
    fi

    # ── BLOCKER: Intel GPU in D3cold ──────────────────────────────────────
    if [[ "$power_state" == "D3cold" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'GPU Not Available for Reliable VM Passthrough')\Zn\n\n"
        msg+="$(translate 'The selected Intel GPU is currently in power state D3cold'):\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n\n"
        msg+="$(translate 'Detected power state'): \Zb${power_state}\Zn\n\n"
        msg+="$(translate 'This state has a high probability of VM startup/reset failures.')\n\n"
        msg+="\Zb$(translate 'Configuration has been stopped to prevent an unusable VM state.')\Zn"

        _pmx_msgbox "$(translate 'High-Risk GPU Power State')" "$msg" 20 80
        exit 0
    fi

    # ── BLOCKER: no usable reset method ──────────────────────────────────
    if [[ "$reset_method" == "none" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'Incompatible Reset Capability for Intel GPU')\Zn\n\n"
        msg+="$(translate 'The selected Intel GPU does not expose a PCI reset interface'):\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n\n"
        msg+="  $(translate 'Detected reset method'): \Zb${reset_method}\Zn\n\n"
        msg+="$(translate 'Without a usable reset path, passthrough reliability is poor and VM')\n"
        msg+="$(translate 'startup/restart errors are likely.')\n\n"
        msg+="\Zb$(translate 'Configuration has been stopped due to high reset risk.')\Zn"

        _pmx_msgbox "$(translate 'Reset Capability Blocked')" "$msg" 20 80
        exit 0
    fi

    # ── BLOCKER: Intel dGPU without FLR ──────────────────────────────────
    if [[ "$gpu_subtype" == "dedicated" && "$reset_method" != "flr" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'Incompatible Reset Capability for Intel dGPU')\Zn\n\n"
        msg+="$(translate 'An Intel dedicated GPU has been detected without FLR support'):\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n\n"
        msg+="  $(translate 'Detected reset method'): \Zb${reset_method}\Zn\n\n"
        msg+="$(translate 'For dedicated GPUs, FLR is required by this policy to reduce VM')\n"
        msg+="$(translate 'start/restart failures and reset instability.')\n\n"
        msg+="\Zb$(translate 'Configuration has been stopped due to high reset risk.')\Zn"

        _pmx_msgbox "$(translate 'Reset Capability Blocked')" "$msg" 20 80
        exit 0
    fi

    # ── WARNING: Intel subtype unknown and reset is not FLR ──────────────
    if [[ "$gpu_subtype" == "unknown" && "$reset_method" != "flr" ]]; then
        local msg
        msg="\n\Z4\Zb$(translate 'Warning: Limited PCI Reset Support')\Zn\n\n"
        msg+="$(translate 'The selected Intel GPU has non-FLR reset support and unknown subtype'):\n"
        msg+="  $(translate 'Detected subtype'): \Zb${gpu_subtype}\Zn\n"
        msg+="  $(translate 'Detected reset method'): \Zb${reset_method}\Zn\n\n"
        msg+="$(translate 'Passthrough may work, but startup/restart reliability is not guaranteed.')\n\n"
        msg+="$(translate 'Do you want to continue anyway?')"

        _pmx_yesno "$(translate 'Reset Capability Warning')" "$msg" 18 78
        [[ $? -ne 0 ]] && exit 0
    fi
}

check_gpu_vm_compatibility() {
    [[ "$SELECTED_GPU" != "amd" && "$SELECTED_GPU" != "intel" ]] && return 0

    if [[ "$SELECTED_GPU" == "intel" ]]; then
        check_intel_vm_compatibility
        return 0
    fi

    local pci_full="$SELECTED_GPU_PCI"
    local gpu_subtype reset_method power_state

    gpu_subtype=$(_detect_amd_gpu_subtype)
    reset_method=$(_check_pci_reset_method "$pci_full")
    power_state=$(cat "/sys/bus/pci/devices/${pci_full}/power_state" 2>/dev/null | tr -d '[:space:]')

    # ── BLOCKER: AMD device currently in D3cold ──────────────────────────
    # D3cold on AMD passthrough candidates is a high-risk state for VM use.
    # In practice this often leads to failed power-up/reset when QEMU starts.
    if [[ "$power_state" == "D3cold" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'GPU Not Available for Reliable VM Passthrough')\Zn\n\n"
        msg+="$(translate 'The selected AMD GPU is currently in power state D3cold'):\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n\n"
        msg+="$(translate 'Detected power state'): \Zb${power_state}\Zn\n\n"
        msg+="$(translate 'This state indicates a high risk of passthrough failure due to'):\n"
        msg+="  •  $(translate 'Inaccessible device during VM startup')\n"
        msg+="  •  $(translate 'Failed transitions from D3cold to D0')\n"
        msg+="  •  $(translate 'Potential QEMU startup/assertion failures')\n\n"
        msg+="\Zb$(translate 'Configuration has been stopped to prevent an unusable VM state.')\Zn"

        _pmx_msgbox "$(translate 'High-Risk GPU Power State')" "$msg" 22 80
        exit 0
    fi

    # ── BLOCKER: AMD APU without FLR reset ───────────────────────────────
    # Validated in testing: Lucienne/Renoir/Cezanne + bus-only reset →
    #   "write error: Inappropriate ioctl for device" on PCI reset
    #   "Unable to change power state from D3cold to D0"
    #   QEMU pci_irq_handler assertion failure → VM does not start
    if [[ "$gpu_subtype" == "apu" && "$reset_method" != "flr" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'GPU Not Compatible with VM Passthrough')\Zn\n\n"
        msg+="$(translate 'An AMD integrated GPU (APU) has been detected'):\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n\n"
        msg+="$(translate 'Although VFIO can bind to this device, full passthrough to a VM is')\n"
        msg+="$(translate 'not reliable on this hardware due to the following limitations'):\n\n"
        msg+="  •  $(translate 'PCI reset method'): \Zb${reset_method}\Zn"
        msg+=" — $(translate 'Function Level Reset (FLR) not available')\n"
        msg+="  •  $(translate 'SoC-integrated GPU: tight coupling with other SoC components')\n"
        msg+="  •  $(translate 'Power state D3cold/D0 transitions may be inaccessible')\n"
        [[ "$power_state" == "D3cold" ]] && \
        msg+="  •  \Z1$(translate 'Current power state: D3cold (device currently inaccessible)')\Zn\n"
        msg+="\n$(translate 'Attempting passthrough with this GPU typically results in'):\n"
        msg+="  —  write error: Inappropriate ioctl for device\n"
        msg+="  —  Unable to change power state from D3cold to D0\n"
        msg+="  —  QEMU IRQ assertion failure → VM does not start\n\n"
        msg+="\Zb$(translate 'Configuration has been stopped to prevent leaving the VM in an unusable state.')\Zn"

        _pmx_msgbox "$(translate 'Incompatible GPU for VM Passthrough')" "$msg" 26 80
        exit 0
    fi

    # ── BLOCKER: AMD dedicated GPU without FLR reset ─────────────────────
    # User policy: for dGPU + no FLR, do not continue automatically.
    if [[ "$gpu_subtype" == "dedicated" && "$reset_method" != "flr" ]]; then
        local msg
        msg="\n\Zb\Z1$(translate 'Incompatible Reset Capability for AMD dGPU')\Zn\n\n"
        msg+="$(translate 'An AMD dedicated GPU has been detected without FLR support'):\n"
        msg+="  ${SELECTED_GPU_NAME}\n"
        msg+="  ${SELECTED_GPU_PCI}\n\n"
        msg+="  $(translate 'Detected reset method'): \Zb${reset_method}\Zn\n\n"
        msg+="$(translate 'Without Function Level Reset (FLR), passthrough is not considered reliable')\n"
        msg+="$(translate 'for this policy and may fail after first use or on subsequent VM starts.')\n\n"
        msg+="\Zb$(translate 'Configuration has been stopped due to high reset risk.')\Zn"

        _pmx_msgbox "$(translate 'Reset Capability Blocked')" "$msg" 20 80
        exit 0
    fi

    # ── WARNING: Unknown AMD subtype without FLR ─────────────────────────
    # Keep optional path for unknown classifications only.
    if [[ "$gpu_subtype" == "unknown" && "$reset_method" != "flr" ]]; then
        local msg
        msg="\n\Z4\Zb$(translate 'Warning: Limited PCI Reset Support')\Zn\n\n"
        msg+="$(translate 'The selected AMD GPU does not report FLR reset support'):\n"
        msg+="  $(translate 'Detected subtype'): \Zb${gpu_subtype}\Zn\n"
        msg+="  $(translate 'Detected reset method'): \Zb${reset_method}\Zn\n\n"
        msg+="$(translate 'Passthrough may fail depending on hardware/firmware implementation.')\n\n"
        msg+="$(translate 'Do you want to continue anyway?')"

        _pmx_yesno "$(translate 'Reset Capability Warning')" "$msg" 18 78
        [[ $? -ne 0 ]] && exit 0
    fi
}


# ==========================================================
# Phase 1 — Step 5: IOMMU group analysis
# ==========================================================
analyze_iommu_group() {
    local pci_full="$SELECTED_GPU_PCI"
    local group_link="/sys/bus/pci/devices/${pci_full}/iommu_group"

    if [[ ! -L "$group_link" ]]; then
        if [[ "$IOMMU_PENDING_REBOOT" == "true" ]]; then
            IOMMU_GROUP="pending-reboot"
            IOMMU_DEVICES=("$pci_full")
            IOMMU_VFIO_IDS=()

            local vid did
            vid=$(cat "/sys/bus/pci/devices/${pci_full}/vendor" 2>/dev/null | sed 's/0x//')
            did=$(cat "/sys/bus/pci/devices/${pci_full}/device" 2>/dev/null | sed 's/0x//')
            [[ -n "$vid" && -n "$did" ]] && IOMMU_VFIO_IDS+=("${vid}:${did}")

            _pmx_msgbox "$(translate 'IOMMU Group Pending')" \
                "\n$(translate 'IOMMU groups are not available yet because reboot is pending.')\n\n$(translate 'The script will preconfigure the selected GPU now and finalize hardware binding after reboot.')\n\n$(translate 'Selected GPU function'):\n  • ${pci_full}" \
                14 82
            return 0
        fi

        _pmx_msgbox "$(translate 'IOMMU Group Error')" \
            "\n$(translate 'Could not determine the IOMMU group for the selected GPU.')\n\n$(translate 'Make sure IOMMU is properly enabled and the system has been rebooted after activation.')" \
            10 72
        exit 1
    fi

    IOMMU_GROUP=$(basename "$(readlink "$group_link")")
    IOMMU_DEVICES=()
    IOMMU_VFIO_IDS=()

    local group_dir="/sys/kernel/iommu_groups/${IOMMU_GROUP}/devices"
    local display_lines=""
    local extra_devices=0

    for dev_path in "${group_dir}/"*; do
        [[ -e "$dev_path" ]] || continue
        local dev
        dev=$(basename "$dev_path")

        # Skip PCI bridges and host bridges (class 0x0604 / 0x0600)
        local dev_class
        dev_class=$(cat "/sys/bus/pci/devices/${dev}/class" 2>/dev/null)
        if [[ "$dev_class" == 0x0604* || "$dev_class" == 0x0600* ]]; then
            continue
        fi

        IOMMU_DEVICES+=("$dev")

        # Collect vendor:device ID
        local vid did
        vid=$(cat "/sys/bus/pci/devices/${dev}/vendor" 2>/dev/null | sed 's/0x//')
        did=$(cat "/sys/bus/pci/devices/${dev}/device" 2>/dev/null | sed 's/0x//')
        [[ -n "$vid" && -n "$did" ]] && IOMMU_VFIO_IDS+=("${vid}:${did}")

        # Build display line
        local dev_name dev_driver
        dev_name=$(lspci -nn -s "${dev#0000:}" 2>/dev/null | sed 's/^[^ ]* //' | cut -c1-52)
        dev_driver=$(_get_pci_driver "$dev")
        display_lines+="  • ${dev}  ${dev_name}  [${dev_driver}]\n"

        [[ "$dev" != "$pci_full" ]] && extra_devices=$((extra_devices + 1))
    done

}

# Returns 0 if the BDF at $1 is a real PCI audio device (class 04xx).
_pci_is_audio_device() {
    local bdf="$1"
    [[ -n "$bdf" ]] || return 1
    local dev_path="/sys/bus/pci/devices/${bdf}"
    [[ -d "$dev_path" ]] || return 1
    local class_hex
    class_hex=$(cat "${dev_path}/class" 2>/dev/null | sed 's/^0x//')
    [[ "${class_hex:0:2}" == "04" ]]
}

# Registers an audio BDF for passthrough alongside the GPU.
# Idempotent: skips if the BDF was already recorded by analyze_iommu_group
# (IOMMU_DEVICES) or by a previous call here (EXTRA_AUDIO_DEVICES).
# Updates EXTRA_AUDIO_DEVICES, EXTRA_AUDIO_INFO, and IOMMU_VFIO_IDS.
_register_gpu_audio_device() {
    local bdf="$1"
    [[ -n "$bdf" ]] || return 1
    local dev_path="/sys/bus/pci/devices/${bdf}"
    [[ -d "$dev_path" ]] || return 1

    local dev
    for dev in "${IOMMU_DEVICES[@]}"; do
        [[ "$dev" == "$bdf" ]] && return 0
    done
    for dev in "${EXTRA_AUDIO_DEVICES[@]}"; do
        [[ "$dev" == "$bdf" ]] && return 0
    done

    EXTRA_AUDIO_DEVICES+=("$bdf")
    local drv
    drv=$(_get_pci_driver "$bdf")
    EXTRA_AUDIO_INFO+=("${bdf}|${drv}")

    local vid did new_id
    vid=$(cat "${dev_path}/vendor" 2>/dev/null | sed 's/0x//')
    did=$(cat "${dev_path}/device" 2>/dev/null | sed 's/0x//')
    if [[ -n "$vid" && -n "$did" ]]; then
        new_id="${vid}:${did}"
        if _append_unique "$new_id" "${IOMMU_VFIO_IDS[@]}"; then
            IOMMU_VFIO_IDS+=("$new_id")
        fi
    fi
    return 0
}

# Scans the host for all class-04 PCI audio devices and lets the user
# pick which ones to pass to the VM. Only invoked when the selected GPU
# has no .1 sibling audio function — the dGPU fast path continues to
# auto-include that sibling without prompting.
#
# Devices already in the GPU's IOMMU group are excluded from the list
# (analyze_iommu_group has already queued them). The checklist defaults
# to all-OFF so nothing gets passed through silently.
_prompt_user_for_audio_devices() {
    # Collect eligible audio BDFs from sysfs.
    local -a candidates=()
    local dev_path bdf
    for dev_path in /sys/bus/pci/devices/*; do
        [[ -d "$dev_path" ]] || continue
        bdf=$(basename "$dev_path")
        _pci_is_audio_device "$bdf" || continue
        # Skip ones already queued by the IOMMU group sweep.
        local skip=false dev
        for dev in "${IOMMU_DEVICES[@]}"; do
            [[ "$dev" == "$bdf" ]] && { skip=true; break; }
        done
        $skip && continue
        candidates+=("$bdf")
    done

    [[ ${#candidates[@]} -eq 0 ]] && return 0

    # Build checklist items: tag=BDF, description="<name> (driver: X)".
    local -a items=()
    local name drv label
    for bdf in "${candidates[@]}"; do
        name=$(lspci -nn -s "${bdf#0000:}" 2>/dev/null \
            | sed 's/^[^ ]* //' \
            | sed 's/ \[0401\]//; s/ \[0403\]//; s/ \[0400\]//' \
            | cut -c1-52)
        [[ -z "$name" ]] && name="PCI audio"
        drv=$(_get_pci_driver "$bdf")
        label="${name}  (driver: ${drv})"
        items+=("$bdf" "$label" "off")
    done

    local prompt selection dialog_h list_h
    prompt="$(translate 'The selected GPU has no dedicated .1 audio sibling function.')\n"
    prompt+="$(translate 'If you want HDMI/analog audio inside the VM, select the audio controller(s) to pass through along with the GPU.')\n\n"
    prompt+="$(translate 'Default is none (video-only passthrough). Use SPACE to toggle selections.')"

    # Give the list area a floor of 4 rows so a single candidate doesn't
    # render cramped under the description. Overall dialog height scales
    # with that floor + room for the 4-line prompt, blank line, borders
    # and button row.
    list_h=${#candidates[@]}
    (( list_h < 4 )) && list_h=4
    dialog_h=$(( list_h + 14 ))

    selection=$(_pmx_checklist \
        "$(translate 'Add Audio Passthrough')" \
        "$prompt" \
        "$dialog_h" 82 "$list_h" \
        "${items[@]}") || return 0

    # dialog wraps selected tags in quotes, whiptail does not — _strip them.
    selection=$(echo "$selection" | tr -d '"')
    [[ -z "$selection" ]] && return 0

    local picked
    for picked in $selection; do
        _register_gpu_audio_device "$picked"
    done
}

detect_optional_gpu_audio() {
    EXTRA_AUDIO_DEVICES=()
    EXTRA_AUDIO_INFO=()

    # Fast path: dGPUs (NVIDIA / AMD discrete) and some APUs expose audio
    # as function .1 of the same slot. When present, auto-include it —
    # this is the unambiguous, always-safe case because such audio only
    # outputs through the GPU's own ports and was never used by the host.
    local sibling_audio="${SELECTED_GPU_PCI%.*}.1"
    if _pci_is_audio_device "$sibling_audio"; then
        _register_gpu_audio_device "$sibling_audio"
        return 0
    fi

    # Slow path: no sibling audio (typical for Intel iGPUs whose HDMI
    # audio lives on the PCH, or setups with an external sound card).
    # Ask the user explicitly via checklist — the decision of whether to
    # pass chipset audio alongside an iGPU is intentional, not automatic.
    _prompt_user_for_audio_devices
}


# ==========================================================
# Phase 1 — Step 6: VM selection
# ==========================================================
select_vm() {
    if [[ -n "$PRESELECT_VMID" ]]; then
        if qm config "$PRESELECT_VMID" >/dev/null 2>&1; then
            SELECTED_VMID="$PRESELECT_VMID"
            VM_NAME=$(qm config "$SELECTED_VMID" 2>/dev/null | grep "^name:" | awk '{print $2}')
            return 0
        fi
        _pmx_msgbox "$(translate 'Invalid VMID')" \
            "\n$(translate 'The preselected VMID does not exist on this host:') ${PRESELECT_VMID}" 9 72
        exit 1
    fi

    local menu_items=()

    while IFS= read -r line; do
        [[ "$line" =~ ^[[:space:]]*VMID ]] && continue
        local vmid name status
        vmid=$(echo "$line" | awk '{print $1}')
        name=$(echo "$line" | awk '{print $2}')
        status=$(echo "$line" | awk '{print $3}')
        [[ -z "$vmid" || ! "$vmid" =~ ^[0-9]+$ ]] && continue
        menu_items+=("$vmid" "${name:-VM-${vmid}} (${status})")
    done < <(qm list 2>/dev/null)

    if [[ ${#menu_items[@]} -eq 0 ]]; then
        _pmx_msgbox "$(translate 'No VMs Found')" \
            "\n$(translate 'No Virtual Machines found on this system.')\n\n$(translate 'Create a VM first (machine type q35 + UEFI BIOS), then run this option again.')" \
            10 68
        exit 0
    fi

    SELECTED_VMID=$(_pmx_menu \
        "$(translate 'Select Virtual Machine')" \
        "\n$(translate 'Select the VM to add the GPU to:')" \
        20 72 12 \
        "${menu_items[@]}") || exit 0

    VM_NAME=$(qm config "$SELECTED_VMID" 2>/dev/null | grep "^name:" | awk '{print $2}')
}


# ==========================================================
# Phase 1 — Step 7: Machine type check (must be q35)
# ==========================================================
check_vm_machine_type() {
    local machine_line
    machine_line=$(qm config "$SELECTED_VMID" 2>/dev/null | grep "^machine:" | awk '{print $2}')

    if echo "$machine_line" | grep -q "q35"; then
        return 0
    fi

    local msg
    msg="\n$(translate 'The selected VM') \"${VM_NAME}\" (${SELECTED_VMID}) "
    msg+="$(translate 'is not configured as machine type q35.')\n\n"
    msg+="$(translate 'PCIe GPU passthrough requires:')\n"
    msg+="  •  $(translate 'Machine type: q35')\n"
    msg+="  •  $(translate 'BIOS: OVMF (UEFI)')\n\n"
    msg+="$(translate 'Changing the machine type on an existing installed VM is not safe: it changes the chipset and PCI slot layout, which typically prevents the guest OS from booting.')\n\n"
    msg+="$(translate 'To use GPU passthrough, please create a new VM configured with:')\n"
    msg+="  •  $(translate 'Machine: q35')\n"
    msg+="  •  $(translate 'BIOS: OVMF (UEFI)')\n"
    msg+="  •  $(translate 'Storage controller: VirtIO SCSI')"

    _pmx_msgbox "$(translate 'Incompatible Machine Type')" "$msg" 20 78
    exit 0
}


# ==========================================================
# Phase 1 — Step 8: Switch mode detection
# ==========================================================
check_switch_mode() {
    local pci_slot="${SELECTED_GPU_PCI#0000:}"  # 01:00.0
    pci_slot="${pci_slot%.*}"                   # 01:00

    # ── LXC conflict check ────────────────────────────────
    LXC_AFFECTED_CTIDS=()
    LXC_AFFECTED_NAMES=()
    LXC_AFFECTED_RUNNING=()
    LXC_AFFECTED_ONBOOT=()
    LXC_SWITCH_ACTION=""

    local lxc_affected=()
    local running_count=0
    local onboot_count=0

    for conf in /etc/pve/lxc/*.conf; do
        [[ -f "$conf" ]] || continue
        _lxc_conf_uses_selected_gpu "$conf" || continue

        local ctid ct_name running_flag onboot_flag
        ctid=$(basename "$conf" .conf)
        ct_name=$(pct config "$ctid" 2>/dev/null | awk '/^hostname:/ {print $2}')
        [[ -z "$ct_name" ]] && ct_name="CT-${ctid}"

        running_flag=0
        onboot_flag=0
        _ct_is_running "$ctid" && running_flag=1
        _ct_onboot_enabled "$ctid" && onboot_flag=1

        LXC_AFFECTED_CTIDS+=("$ctid")
        LXC_AFFECTED_NAMES+=("$ct_name")
        LXC_AFFECTED_RUNNING+=("$running_flag")
        LXC_AFFECTED_ONBOOT+=("$onboot_flag")

        lxc_affected+=("CT ${ctid} (${ct_name})")
        [[ "$running_flag" == "1" ]] && running_count=$((running_count + 1))
        [[ "$onboot_flag" == "1" ]] && onboot_count=$((onboot_count + 1))
    done

    if [[ ${#lxc_affected[@]} -gt 0 ]]; then
        SWITCH_FROM_LXC=true
        SWITCH_LXC_LIST=$(IFS=', '; echo "${lxc_affected[*]}")

        local msg action_choice
        msg="\n$(translate 'The selected GPU is currently used by the following LXC container(s):')\n\n"
        local i
        for i in "${!LXC_AFFECTED_CTIDS[@]}"; do
            local status_txt onboot_txt
            status_txt="$(translate 'stopped')"
            onboot_txt="onboot=0"
            [[ "${LXC_AFFECTED_RUNNING[$i]}" == "1" ]] && status_txt="$(translate 'running')"
            [[ "${LXC_AFFECTED_ONBOOT[$i]}" == "1" ]] && onboot_txt="onboot=1"
            msg+="  •  CT ${LXC_AFFECTED_CTIDS[$i]} (${LXC_AFFECTED_NAMES[$i]}) [${status_txt}, ${onboot_txt}]\n"
        done
        msg+="\n$(translate 'VM passthrough requires exclusive VFIO binding of the GPU.')\n"
        msg+="$(translate 'Choose how to handle affected LXC containers before switching to VM mode.')\n\n"
        [[ "$running_count" -gt 0 ]] && \
            msg+="\Z1$(translate 'Running containers detected'): ${running_count}\Zn\n"
        [[ "$onboot_count" -gt 0 ]] && \
            msg+="\Z1\Zb$(translate 'Start on boot enabled (onboot=1)'): ${onboot_count}\Zn\n"
        msg+="\n\Z1$(translate 'After this LXC → VM switch, reboot the host so the new binding state is applied cleanly.')\Zn"

        action_choice=$(_pmx_menu --default-item "2" \
            "$(translate 'GPU Used in LXC Containers')" \
            "$msg" 25 96 8 \
            "1" "$(translate 'Keep GPU in LXC config (disable Start on boot)')" \
            "2" "$(translate 'Remove GPU from LXC config (keep Start on boot)')") || exit 0

        case "$action_choice" in
            1) LXC_SWITCH_ACTION="keep_gpu_disable_onboot" ;;
            2) LXC_SWITCH_ACTION="remove_gpu_keep_onboot" ;;
            *) exit 0 ;;
        esac
    else
        SWITCH_FROM_LXC=false
    fi

    # ── VM conflict check (different VM than selected) ────
    local vm_src_id="" vm_src_name=""
    for conf in /etc/pve/qemu-server/*.conf; do
        [[ -f "$conf" ]] || continue
        local vmid
        vmid=$(basename "$conf" .conf)
        [[ "$vmid" == "$SELECTED_VMID" ]] && continue  # same target VM, no conflict
        if grep -qE "hostpci[0-9]+:.*${pci_slot}" "$conf"; then
            vm_src_id="$vmid"
            vm_src_name=$(grep "^name:" "$conf" 2>/dev/null | awk '{print $2}')
            break
        fi
    done

    if [[ -n "$vm_src_id" ]]; then
        local src_running=false
        _vm_is_running "$vm_src_id" && src_running=true

        if [[ "$src_running" == "true" ]]; then
            local msg
            msg="\n$(translate 'The selected GPU is already assigned to another VM that is currently running:')\n\n"
            msg+="  VM ${vm_src_id} (${vm_src_name:-VM-${vm_src_id}})\n\n"
            msg+="$(translate 'The same GPU cannot be used by two VMs at the same time.')\n\n"
            msg+="$(translate 'Next step: stop that VM first, then run')\n"
            msg+="  Hardware Graphics → Add GPU to VM\n"
            msg+="$(translate 'to move the GPU safely.')"

            _pmx_msgbox "$(translate 'GPU Busy in Running VM')" "$msg" 16 78
            exit 0
        fi

        SWITCH_FROM_VM=true
        SWITCH_VM_SRC="$vm_src_id"
        SWITCH_VM_ACTION="remove_gpu_keep_onboot"
        local selected_driver
        selected_driver=$(_get_pci_driver "$SELECTED_GPU_PCI")
        if [[ "$selected_driver" == "vfio-pci" && "$SWITCH_FROM_LXC" != "true" ]]; then
            VM_SWITCH_ALREADY_VFIO=true
        fi

        local src_onboot target_onboot
        src_onboot="0"
        target_onboot="0"
        _vm_onboot_enabled "$vm_src_id" && src_onboot="1"
        _vm_onboot_enabled "$SELECTED_VMID" && target_onboot="1"

        local msg
        msg="\n$(translate 'The selected GPU is already configured for passthrough to:')\n\n"
        msg+="  VM ${vm_src_id} (${vm_src_name:-VM-${vm_src_id}})\n\n"
        msg+="$(translate 'That VM is currently stopped, so the GPU can be reassigned now.')\n"
        msg+="\Z1\Zb$(translate 'Important: both VMs cannot be running at the same time with the same GPU.')\Zn\n\n"
        msg+="$(translate 'Target VM'): VM ${SELECTED_VMID} (${VM_NAME:-VM-${SELECTED_VMID}})\n"
        msg+="$(translate 'Source VM'): VM ${vm_src_id} (${vm_src_name:-VM-${vm_src_id}})\n\n"
        if [[ "$src_onboot" == "1" && "$target_onboot" == "1" ]]; then
            msg+="\Z1\Zb$(translate 'Warning: both VMs have autostart enabled (onboot=1).')\Zn\n"
            msg+="\Z1\Zb$(translate 'Disable autostart on one VM to avoid startup conflicts.')\Zn\n\n"
        fi
        if [[ "$VM_SWITCH_ALREADY_VFIO" == "true" ]]; then
            msg+="$(translate 'Host GPU is already bound to vfio-pci. Host reconfiguration/reboot should not be required for this VM-to-VM reassignment.')\n\n"
        fi
        msg+="$(translate 'Choose conflict policy for the source VM:')"

        local vm_action_choice
        vm_action_choice=$(_pmx_menu --default-item "1" \
            "$(translate 'GPU Already Assigned to Another VM')" \
            "$msg" 24 84 8 \
            "1" "$(translate 'Keep GPU in source VM config (disable Start on boot if enabled)')" \
            "2" "$(translate 'Remove GPU from source VM config (keep Start on boot)')") || exit 0

        case "$vm_action_choice" in
            1) SWITCH_VM_ACTION="keep_gpu_disable_onboot" ;;
            2) SWITCH_VM_ACTION="remove_gpu_keep_onboot" ;;
            *) exit 0 ;;
        esac
    fi
}


# ==========================================================
# Phase 1 — Step 9: Confirmation summary
# ==========================================================
confirm_summary() {
    local msg
    msg="\n$(translate 'The following changes will be applied'):\n"
    msg+="\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg+="  $(translate 'GPU')          :  ${SELECTED_GPU_NAME}\n"
    msg+="  $(translate 'PCI Address')  :  ${SELECTED_GPU_PCI}\n"
    if [[ "$IOMMU_PENDING_REBOOT" == "true" ]]; then
        msg+="  $(translate 'IOMMU Group')  :  $(translate 'pending (reboot required to enumerate full group)')\n"
    else
        msg+="  $(translate 'IOMMU Group')  :  ${IOMMU_GROUP} (${#IOMMU_DEVICES[@]} $(translate 'devices'))\n"
    fi
    msg+="  $(translate 'Target VM')    :  ${VM_NAME:-VM-${SELECTED_VMID}} (${SELECTED_VMID})\n"
    msg+="  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg+="  \Zb$(translate 'Host'):\Zn\n"
    if [[ "$PREFLIGHT_HOST_REBOOT_REQUIRED" != "true" ]]; then
        msg+="  •  $(translate 'Host VFIO configuration already up to date')\n"
        msg+="  •  $(translate 'No host VFIO reconfiguration expected')\n"
        msg+="  •  $(translate 'No host reboot expected')\n\n"
    else
        msg+="  •  $(translate 'VFIO modules in /etc/modules')\n"
        msg+="  •  $(translate 'vfio-pci IDs in /etc/modprobe.d/vfio.conf')\n"
        [[ "$SELECTED_GPU" == "amd" ]] && \
            msg+="  •  $(translate 'AMD softdep configured')\n"
        [[ "$SELECTED_GPU" == "amd" ]] && \
            msg+="  •  $(translate 'GPU ROM dump to /usr/share/kvm/')\n"
        msg+="  •  $(translate 'GPU driver blacklisted')\n"
        msg+="  •  $(translate 'initramfs updated')\n"
        msg+="  •  \Zb$(translate 'System reboot required')\Zn\n\n"
    fi
    msg+="  \Zb$(translate 'VM') ${SELECTED_VMID}:\Zn\n"
    [[ "$TARGET_VM_ALREADY_HAS_GPU" == "true" ]] && \
        msg+="  •  $(translate 'Existing hostpci entries detected — they will be reused')\n"
    msg+="  •  $(translate 'Virtual display normalized to vga: std (compatibility)')\n"
    if [[ "$IOMMU_PENDING_REBOOT" == "true" ]]; then
        msg+="  •  $(translate 'hostpci entries for selected GPU functions (full IOMMU group will be enforced after reboot)')\n"
    else
        msg+="  •  $(translate 'hostpci entries for all IOMMU group devices')\n"
    fi
    if [[ ${#EXTRA_AUDIO_DEVICES[@]} -gt 0 ]]; then
        msg+="  •  $(translate 'Additional audio function(s) to be added'):\n"
        local _audio_info _audio_bdf _audio_drv
        for _audio_info in "${EXTRA_AUDIO_INFO[@]}"; do
            _audio_bdf="${_audio_info%%|*}"
            _audio_drv="${_audio_info#*|}"
            if [[ -n "$_audio_drv" && "$_audio_drv" != "none" && "$_audio_drv" != "vfio-pci" ]]; then
                msg+="       • ${_audio_bdf}  \Zb(${_audio_drv})\Zn\n"
            else
                msg+="       • ${_audio_bdf}\n"
            fi
        done
    fi
    [[ "$SELECTED_GPU" == "nvidia" ]] && \
        msg+="  •  $(translate 'NVIDIA KVM hiding (cpu hidden=1)')\n"
    if [[ "$SWITCH_FROM_LXC" == "true" ]]; then
        msg+="\n  \Z1•  $(translate 'Affected LXC containers'): ${SWITCH_LXC_LIST}\Zn\n"
        msg+="  \Z1•  $(translate 'Selected LXC action'): $(_lxc_switch_action_label)\Zn\n"
        if [[ "$LXC_SWITCH_ACTION" == "remove_gpu_keep_onboot" ]]; then
            msg+="  \Z1•  $(translate 'To use the GPU again in LXC, run Add GPU to LXC from GPUs and Coral-TPU Menu')\Zn\n"
        fi
    fi
    if [[ "$SWITCH_FROM_VM" == "true" ]]; then
        if [[ "$SWITCH_VM_ACTION" == "keep_gpu_disable_onboot" ]]; then
            msg+="\n  \Z1•  $(translate 'GPU will remain configured in source VM'): ${SWITCH_VM_SRC}\Zn\n"
            msg+="  \Z1•  $(translate 'Start on boot will be disabled on source VM only if currently enabled')\Zn\n"
            msg+="  \Z1•  $(translate 'GPU guard hook will block concurrent start when another VM is already using this GPU')\Zn\n"
        else
            msg+="\n  \Z1•  $(translate 'GPU will be removed from source VM config'): ${SWITCH_VM_SRC}\Zn\n"
        fi
        msg+="  \Z1•  $(translate 'Selected VM action'): $(_vm_switch_action_label)\Zn\n"
    fi
    msg+="\n$(translate 'Do you want to proceed?')"

    local run_title
    run_title=$(_get_vm_run_title)

    _pmx_yesno "${run_title}" "$msg" 28 78
    [[ $? -ne 0 ]] && exit 0
}


# ==========================================================
# Phase 2 — Processing
# ==========================================================

# ── VFIO modules in /etc/modules ─────────────────────────
add_vfio_modules() {
    msg_info "$(translate 'Configuring VFIO modules...')"
    local modules=("vfio" "vfio_iommu_type1" "vfio_pci")
    local kernel_major kernel_minor
    kernel_major=$(uname -r | cut -d. -f1)
    kernel_minor=$(uname -r | cut -d. -f2)
    if (( kernel_major < 6 || ( kernel_major == 6 && kernel_minor < 2 ) )); then
        modules+=("vfio_virqfd")
    fi
    for mod in "${modules[@]}"; do
        _add_line_if_missing "$mod" /etc/modules
    done
    msg_ok "$(translate 'VFIO modules configured in /etc/modules')" | tee -a "$screen_capture"
}


# ── vfio-pci IDs — merge with existing ones ─────────────
configure_vfio_pci_ids() {
    msg_info "$(translate 'Configuring vfio-pci device IDs...')"
    local vfio_conf="/etc/modprobe.d/vfio.conf"
    touch "$vfio_conf"

    # Collect existing IDs (if any)
    local existing_ids=()
    local existing_line
    existing_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
    if [[ -n "$existing_line" ]]; then
        local ids_part
        ids_part=$(echo "$existing_line" | grep -oE 'ids=[^[:space:]]+' | sed 's/ids=//')
        IFS=',' read -ra existing_ids <<< "$ids_part"
    fi

    # Merge: add new IDs not already present
    local all_ids=("${existing_ids[@]}")
    for new_id in "${IOMMU_VFIO_IDS[@]}"; do
        local found=false
        for existing in "${existing_ids[@]}"; do
            [[ "$existing" == "$new_id" ]] && found=true && break
        done
        $found || all_ids+=("$new_id")
    done

    local ids_str
    ids_str=$(IFS=','; echo "${all_ids[*]}")

    local existing_full_line
    existing_full_line=$(grep "^options vfio-pci ids=" "$vfio_conf" 2>/dev/null | head -1)
    local new_full_line="options vfio-pci ids=${ids_str} disable_vga=1"
    if [[ "$existing_full_line" != "$new_full_line" ]]; then
        sed -i '/^options vfio-pci ids=/d' "$vfio_conf"
        echo "$new_full_line" >> "$vfio_conf"
        HOST_CONFIG_CHANGED=true
    fi
    msg_ok "$(translate 'vfio-pci IDs configured') (${ids_str})" | tee -a "$screen_capture"
}


# ── IOMMU interrupt remapping ─────────────────────────────
configure_iommu_options() {
    _add_line_if_missing "options vfio_iommu_type1 allow_unsafe_interrupts=1" \
        /etc/modprobe.d/iommu_unsafe_interrupts.conf
    _add_line_if_missing "options kvm ignore_msrs=1" \
        /etc/modprobe.d/kvm.conf
    msg_ok "$(translate 'IOMMU interrupt remapping configured')" | tee -a "$screen_capture"
}


# ── AMD softdep ──────────────────────────────────────────
add_softdep_amd() {
    msg_info "$(translate 'Configuring AMD softdep...')"
    local vfio_conf="/etc/modprobe.d/vfio.conf"
    _add_line_if_missing "softdep radeon pre: vfio-pci"       "$vfio_conf"
    _add_line_if_missing "softdep amdgpu pre: vfio-pci"       "$vfio_conf"
    _add_line_if_missing "softdep snd_hda_intel pre: vfio-pci" "$vfio_conf"
    msg_ok "$(translate 'AMD softdep configured in /etc/modprobe.d/vfio.conf')" | tee -a "$screen_capture"
}


# ── Blacklist GPU drivers (idempotent) ───────────────────
blacklist_gpu_drivers() {
    msg_info "$(translate 'Blacklisting GPU host drivers...')"
    local blacklist_file="/etc/modprobe.d/blacklist.conf"
    touch "$blacklist_file"

    case "$SELECTED_GPU" in
        nvidia)
            _add_line_if_missing "blacklist nouveau"          "$blacklist_file"
            _add_line_if_missing "blacklist nvidia"           "$blacklist_file"
            _add_line_if_missing "blacklist nvidia_drm"       "$blacklist_file"
            _add_line_if_missing "blacklist nvidia_modeset"   "$blacklist_file"
            _add_line_if_missing "blacklist nvidia_uvm"       "$blacklist_file"
            _add_line_if_missing "blacklist nvidiafb"         "$blacklist_file"
            _add_line_if_missing "blacklist lbm-nouveau"      "$blacklist_file"
            _add_line_if_missing "options nouveau modeset=0"  "$blacklist_file"
            ;;
        amd)
            _add_line_if_missing "blacklist radeon"   "$blacklist_file"
            _add_line_if_missing "blacklist amdgpu"   "$blacklist_file"
            ;;
        intel)
            _add_line_if_missing "blacklist i915"     "$blacklist_file"
            ;;
    esac
    msg_ok "$(translate 'GPU host driver blacklisted in /etc/modprobe.d/blacklist.conf')" | tee -a "$screen_capture"
}

sanitize_nvidia_host_stack_for_vfio() {
    msg_info "$(translate 'Sanitizing NVIDIA host services for VFIO mode...')"
    local changed=false
    local state_dir="/var/lib/proxmenux"
    local state_file="${state_dir}/nvidia-host-services.state"
    local svc
    local -a services=(
        "nvidia-persistenced.service"
        "nvidia-powerd.service"
        "nvidia-fabricmanager.service"
    )

    mkdir -p "$state_dir" >/dev/null 2>&1 || true
    : > "$state_file"

    for svc in "${services[@]}"; do
        local was_enabled=0 was_active=0
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            was_enabled=1
        fi
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            was_active=1
        fi
        if (( was_enabled == 1 || was_active == 1 )); then
            echo "${svc} enabled=${was_enabled} active=${was_active}" >>"$state_file"
        fi

        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            systemctl stop "$svc" >>"$LOG_FILE" 2>&1 || true
            changed=true
        fi
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            systemctl disable "$svc" >>"$LOG_FILE" 2>&1 || true
            changed=true
        fi
    done

    [[ -s "$state_file" ]] || rm -f "$state_file"

    if [[ -f /etc/modules-load.d/nvidia-vfio.conf ]]; then
        mv /etc/modules-load.d/nvidia-vfio.conf /etc/modules-load.d/nvidia-vfio.conf.proxmenux-disabled-vfio >>"$LOG_FILE" 2>&1 || true
        changed=true
    fi

    if grep -qE '^(nvidia|nvidia_uvm|nvidia_drm|nvidia_modeset)$' /etc/modules 2>/dev/null; then
        sed -i '/^nvidia$/d;/^nvidia_uvm$/d;/^nvidia_drm$/d;/^nvidia_modeset$/d' /etc/modules
        changed=true
    fi

    # Disable NVIDIA udev rules that trigger nvidia-smi (causes conflict with vfio-pci)
    local udev_rules="/etc/udev/rules.d/70-nvidia.rules"
    if [[ -f "$udev_rules" ]]; then
        mv "$udev_rules" "${udev_rules}.proxmenux-disabled" >>"$LOG_FILE" 2>&1 || true
        udevadm control --reload-rules >>"$LOG_FILE" 2>&1 || true
        changed=true
    fi

    # Create hard blacklist to prevent ANY nvidia module loading (even via modprobe/nvidia-smi)
    local nvidia_blacklist="/etc/modprobe.d/nvidia-blacklist.conf"
    if [[ ! -f "$nvidia_blacklist" ]]; then
        cat > "$nvidia_blacklist" <<'EOF'
# ProxMenux: Hard blacklist to prevent ANY nvidia module loading in VFIO mode
# This prevents nvidia-smi and other tools from triggering module load attempts
install nvidia /bin/false
install nvidia_uvm /bin/false
install nvidia_drm /bin/false
install nvidia_modeset /bin/false
EOF
        changed=true
    fi

    if $changed; then
        HOST_CONFIG_CHANGED=true
        msg_ok "$(translate 'NVIDIA host services/autoload disabled for VFIO mode')" | tee -a "$screen_capture"
    else
        msg_ok "$(translate 'NVIDIA host services/autoload already aligned for VFIO mode')" | tee -a "$screen_capture"
    fi
}


# ── AMD ROM dump: sysfs first, VFCT ACPI table as fallback ───────────────
_dump_rom_via_vfct() {
    local rom_dest="$1"
    local vfct_file="/sys/firmware/acpi/tables/VFCT"
    [[ -f "$vfct_file" ]] || return 1

    # VFCT table layout:
    #   Offset  0-35  : standard ACPI header (36 bytes)
    #   Offset 36-47  : VFCT-specific fields (12 bytes)
    #   Offset 48     : first GPU_BIOS_IMAGE object
    #     +0  VendorID        (2 bytes)
    #     +2  DeviceID        (2 bytes)
    #     +4  SubsystemVendorID (2 bytes)
    #     +6  SubsystemDeviceID (2 bytes)
    #     +8  PCIBus/Device/Function/Reserved (4 bytes)
    #     +12 ImageLength     (4 bytes, little-endian)
    #     +16 VBIOS image data
    local img_length
    img_length=$(od -An -tu4 -j60 -N4 "$vfct_file" 2>/dev/null | tr -d '[:space:]')
    if [[ -z "$img_length" || "$img_length" -le 0 ]]; then
        return 1
    fi

    dd if="$vfct_file" bs=1 skip=64 count="$img_length" of="$rom_dest" 2>/dev/null
    [[ -s "$rom_dest" ]]
}

dump_amd_rom() {
    local pci_full="$SELECTED_GPU_PCI"
    local rom_path="/sys/bus/pci/devices/${pci_full}/rom"
    local kvm_dir="/usr/share/kvm"

    mkdir -p "$kvm_dir"
    local vid did
    vid=$(cat "/sys/bus/pci/devices/${pci_full}/vendor" 2>/dev/null | sed 's/0x//')
    did=$(cat "/sys/bus/pci/devices/${pci_full}/device" 2>/dev/null | sed 's/0x//')
    local rom_filename="vbios_${vid}_${did}.bin"
    local rom_dest="${kvm_dir}/${rom_filename}"

    # ── Method 1: sysfs /rom ──────────────────────────────
    if [[ -f "$rom_path" ]]; then
        msg_info "$(translate 'Dumping AMD GPU ROM BIOS via sysfs...')"
        echo 1 > "$rom_path" 2>/dev/null
        if cat "$rom_path" > "$rom_dest" 2>>"$LOG_FILE" && [[ -s "$rom_dest" ]]; then
            echo 0 > "$rom_path" 2>/dev/null
            AMD_ROM_FILE="$rom_filename"
            msg_ok "$(translate 'GPU ROM dumped to') ${rom_dest}" | tee -a "$screen_capture"
            return 0
        fi
        echo 0 > "$rom_path" 2>/dev/null
        rm -f "$rom_dest"
        msg_warn "$(translate 'sysfs ROM dump failed — trying ACPI VFCT table...')"
    else
        msg_info "$(translate 'No sysfs ROM entry — trying ACPI VFCT table...')"
    fi

    # ── Method 2: ACPI VFCT table ────────────────────────
    if _dump_rom_via_vfct "$rom_dest"; then
        AMD_ROM_FILE="$rom_filename"
        msg_ok "$(translate 'GPU ROM extracted from ACPI VFCT table to') ${rom_dest}" | tee -a "$screen_capture"
        return 0
    fi

    rm -f "$rom_dest"
    msg_warn "$(translate 'ROM dump not available — configuring without romfile.')"
    msg_warn "$(translate 'Passthrough may still work without a ROM file.')"
}


_remove_selected_gpu_from_lxc_conf() {
    local conf="$1"
    case "$SELECTED_GPU" in
        nvidia)
            sed -i '/dev[0-9]\+:.*\/dev\/nvidia/d' "$conf"
            ;;
        amd)
            sed -i '/dev[0-9]\+:.*\/dev\/dri/d' "$conf"
            sed -i '/dev[0-9]\+:.*\/dev\/kfd/d' "$conf"
            sed -i '/lxc\.mount\.entry:.*dev\/dri/d' "$conf"
            sed -i '/lxc\.cgroup2\.devices\.allow:.*226/d' "$conf"
            ;;
        intel)
            sed -i '/dev[0-9]\+:.*\/dev\/dri/d' "$conf"
            sed -i '/lxc\.mount\.entry:.*dev\/dri/d' "$conf"
            sed -i '/lxc\.cgroup2\.devices\.allow:.*226/d' "$conf"
            ;;
        *)
            sed -i '/dev[0-9]\+:.*\/dev\/dri/d' "$conf"
            sed -i '/dev[0-9]\+:.*\/dev\/nvidia/d' "$conf"
            sed -i '/dev[0-9]\+:.*\/dev\/kfd/d' "$conf"
            sed -i '/lxc\.mount\.entry:.*dev\/dri/d' "$conf"
            sed -i '/lxc\.cgroup2\.devices\.allow:.*226/d' "$conf"
            ;;
    esac
}

# ── Apply selected action for affected LXC (switch mode) ─
cleanup_lxc_configs() {
    [[ "$SWITCH_FROM_LXC" != "true" ]] && return 0
    [[ ${#LXC_AFFECTED_CTIDS[@]} -eq 0 ]] && return 0

    msg_info2 "$(translate 'Applying selected LXC switch action')"

    local i
    for i in "${!LXC_AFFECTED_CTIDS[@]}"; do
        local ctid conf
        ctid="${LXC_AFFECTED_CTIDS[$i]}"
        conf="/etc/pve/lxc/${ctid}.conf"

        if [[ "${LXC_AFFECTED_RUNNING[$i]}" == "1" ]]; then
            msg_info "$(translate 'Stopping LXC') ${ctid}..."
            # _pmx_stop_lxc: graceful shutdown with forceStop+timeout, then
            # fallback to pct stop. Avoids the indefinite hang that raw
            # `pct stop` produces when the container is locked or has
            # unresponsive processes (Plex, databases, etc.).
            if _pmx_stop_lxc "$ctid" "$LOG_FILE"; then
                msg_ok "$(translate 'LXC stopped') ${ctid}" | tee -a "$screen_capture"
            else
                msg_warn "$(translate 'Could not stop LXC') ${ctid}" | tee -a "$screen_capture"
            fi
        else
            msg_ok "$(translate 'LXC already stopped') ${ctid}" | tee -a "$screen_capture"
        fi

        if [[ "$LXC_SWITCH_ACTION" == "keep_gpu_disable_onboot" ]]; then
            if [[ "${LXC_AFFECTED_ONBOOT[$i]}" == "1" ]]; then
                if pct set "$ctid" -onboot 0 >>"$LOG_FILE" 2>&1; then
                    msg_warn "$(translate 'Start on boot disabled for LXC') ${ctid}" | tee -a "$screen_capture"
                else
                    msg_error "$(translate 'Failed to disable Start on boot for LXC') ${ctid}" | tee -a "$screen_capture"
                fi
            fi
        fi

        if [[ "$LXC_SWITCH_ACTION" == "remove_gpu_keep_onboot" && -f "$conf" ]]; then
            _remove_selected_gpu_from_lxc_conf "$conf"
            msg_ok "$(translate 'GPU access removed from LXC') ${ctid}" | tee -a "$screen_capture"
        fi
    done

    if [[ "$LXC_SWITCH_ACTION" == "remove_gpu_keep_onboot" ]]; then
        msg_warn "$(translate 'If needed again, re-add GPU to LXC from GPUs and Coral-TPU Menu → Add GPU to LXC.')" | tee -a "$screen_capture"
    fi
}


# ── Remove GPU from another VM config (switch mode) ──────
cleanup_vm_config() {
    [[ "$SWITCH_FROM_VM" != "true" ]] && return 0
    [[ -z "$SWITCH_VM_SRC" ]] && return 0

    local pci_slot="${SELECTED_GPU_PCI#0000:}"
    pci_slot="${pci_slot%.*}"   # 01:00

    if [[ "$SWITCH_VM_ACTION" == "keep_gpu_disable_onboot" ]]; then
        msg_info "$(translate 'Keeping GPU in source VM config') ${SWITCH_VM_SRC}..."
        if _vm_onboot_enabled "$SWITCH_VM_SRC"; then
            if qm set "$SWITCH_VM_SRC" -onboot 0 >>"$LOG_FILE" 2>&1; then
                msg_warn "$(translate 'Start on boot disabled for VM') ${SWITCH_VM_SRC}" | tee -a "$screen_capture"
            else
                msg_error "$(translate 'Failed to disable Start on boot for VM') ${SWITCH_VM_SRC}" | tee -a "$screen_capture"
            fi
        else
            msg_ok "$(translate 'Start on boot already disabled for VM') ${SWITCH_VM_SRC}" | tee -a "$screen_capture"
        fi
        msg_ok "$(translate 'GPU kept in source VM config') ${SWITCH_VM_SRC}" | tee -a "$screen_capture"
        return 0
    fi

    local src_conf="/etc/pve/qemu-server/${SWITCH_VM_SRC}.conf"
    if [[ -f "$src_conf" ]]; then
        msg_info "$(translate 'Removing GPU from VM') ${SWITCH_VM_SRC}..."
        # Precise regex: slot must be followed by ".<function>" and a
        # delimiter. Kept in sync with switch_gpu_mode.sh. A looser
        # ".*${pci_slot}" would match the slot as a substring and wipe
        # unrelated hostpci entries (e.g. slot "00:02" matching inside
        # a dGPU BDF 0000:02:00.0).
        sed -E -i "/^hostpci[0-9]+:[[:space:]]*(0000:)?${pci_slot}\.[0-7]([,[:space:]]|$)/d" "$src_conf"
        msg_ok "$(translate 'GPU removed from VM') ${SWITCH_VM_SRC}" | tee -a "$screen_capture"

        # Cascade cleanup: detect audio companions orphaned in the
        # source VM after the GPU slot is removed. Typical case: the
        # source VM had an Intel iGPU at 00:02.0 paired with chipset
        # audio at 00:1f.3 via the Part 1 checklist — the sed above
        # only strips 00:02.* entries, leaving the chipset audio
        # hostpci pointing at a device the source VM no longer uses.
        #
        # Unlike switch_gpu_mode (detach flow), we deliberately do NOT
        # touch /etc/modprobe.d/vfio.conf here. The GPU is being moved
        # to the current target VM, which may select the same audio
        # companion in its own Part 1 checklist. Any vendor:device
        # orphaned in vfio.conf after this move is inert — the user
        # can clean it up later via switch_gpu_mode if they want.
        if declare -F _vm_list_orphan_audio_hostpci >/dev/null 2>&1; then
            local _orphan_audio
            _orphan_audio=$(_vm_list_orphan_audio_hostpci "$SWITCH_VM_SRC" "$pci_slot")
            if [[ -n "$_orphan_audio" ]]; then
                local -a _orph_items=()
                local _oline _o_idx _o_bdf _o_name
                while IFS= read -r _oline; do
                    [[ -z "$_oline" ]] && continue
                    _o_idx="${_oline%%|*}"
                    _oline="${_oline#*|}"
                    _o_bdf="${_oline%%|*}"
                    _o_name="${_oline#*|}"
                    _orph_items+=("$_o_idx" "${_o_bdf}  ${_o_name}" "on")
                done <<< "$_orphan_audio"

                local _prompt
                _prompt="\n$(translate 'The GPU has been moved out of VM')  \Zb${SWITCH_VM_SRC}\Zn.\n\n"
                _prompt+="$(translate 'The source VM also has these audio devices, likely added together with the GPU. Remove them too?')\n\n"
                _prompt+="$(translate '(Checked entries will be removed. Uncheck to keep in VM.)')"

                local _selected
                _selected=$(_pmx_checklist \
                    "$(translate 'Associated Audio Devices')" \
                    "$_prompt" \
                    20 84 "$(( ${#_orph_items[@]} / 3 ))" \
                    "${_orph_items[@]}") || _selected=""
                _selected=$(echo "$_selected" | tr -d '"')

                local _sel _removed=""
                for _sel in $_selected; do
                    if declare -F _vm_remove_hostpci_index >/dev/null 2>&1; then
                        _vm_remove_hostpci_index "$SWITCH_VM_SRC" "$_sel" "$LOG_FILE" \
                            && _removed+=" hostpci${_sel}"
                    else
                        qm set "$SWITCH_VM_SRC" --delete "hostpci${_sel}" >>"$LOG_FILE" 2>&1 \
                            && _removed+=" hostpci${_sel}"
                    fi
                done
                if [[ -n "$_removed" ]]; then
                    show_proxmenux_logo
                    msg_title "${run_title}"
                    msg_ok "$(translate 'Associated audio removed from VM'): ${SWITCH_VM_SRC} —${_removed}" \
                        | tee -a "$screen_capture"
                fi
            fi
        fi
    fi
}


# ── VM display normalization for passthrough stability ────
ensure_vm_display_std() {
    msg_info "$(translate 'Checking VM virtual display model...')"

    local current_vga current_base
    current_vga=$(qm config "$SELECTED_VMID" 2>/dev/null | awk '/^vga:/ {print $2}')
    current_base="${current_vga%%,*}"

    if [[ -z "$current_base" ]]; then
        if qm set "$SELECTED_VMID" --vga std >>"$LOG_FILE" 2>&1; then
            msg_ok "$(translate 'Virtual display set to'): vga: std" | tee -a "$screen_capture"
        else
            msg_warn "$(translate 'Could not set VM virtual display to vga: std')" | tee -a "$screen_capture"
        fi
        return 0
    fi

    if [[ "$current_base" == "std" ]]; then
        msg_ok "$(translate 'Virtual display already set to'): vga: std" | tee -a "$screen_capture"
        return 0
    fi

    if qm set "$SELECTED_VMID" --vga std >>"$LOG_FILE" 2>&1; then
        msg_ok "$(translate 'Virtual display changed from') ${current_base} $(translate 'to') std" | tee -a "$screen_capture"
    else
        msg_warn "$(translate 'Could not change VM virtual display to vga: std')" | tee -a "$screen_capture"
    fi
}


# ── Configure VM: add hostpci entries ─────────────────────
configure_vm() {
    msg_info "$(translate 'Configuring VM') ${SELECTED_VMID}..."

    # Find next free hostpciN index
    local idx=0
    if declare -F _pci_next_hostpci_index >/dev/null 2>&1; then
        idx=$(_pci_next_hostpci_index "$SELECTED_VMID" 2>/dev/null || echo 0)
    else
        while qm config "$SELECTED_VMID" 2>/dev/null | grep -q "^hostpci${idx}:"; do
            idx=$((idx + 1))
        done
    fi

    # Primary GPU: pcie=1, x-vga=1 only for NVIDIA/AMD (not Intel iGPU), romfile if AMD
    local gpu_opts="pcie=1"
    [[ "$SELECTED_GPU" == "nvidia" || "$SELECTED_GPU" == "amd" ]] && gpu_opts+=",x-vga=1"
    [[ -n "$AMD_ROM_FILE" ]] && gpu_opts+=",romfile=${AMD_ROM_FILE}"

    if _is_pci_function_assigned_to_vm "$SELECTED_GPU_PCI" "$SELECTED_VMID"; then
        msg_ok "$(translate 'GPU already present in target VM — existing hostpci entry reused')" | tee -a "$screen_capture"
    else
        if qm set "$SELECTED_VMID" --hostpci${idx} "${SELECTED_GPU_PCI},${gpu_opts}" >>"$LOG_FILE" 2>&1; then
            msg_ok "$(translate 'GPU added'): hostpci${idx}: ${SELECTED_GPU_PCI},${gpu_opts}" | tee -a "$screen_capture"
        else
            msg_error "$(translate 'Failed to add GPU to target VM'): ${SELECTED_GPU_PCI}" | tee -a "$screen_capture"
            return 1
        fi
        idx=$((idx + 1))
    fi

    # Remaining IOMMU group devices (audio, USB controllers, etc.)
    for dev in "${IOMMU_DEVICES[@]}"; do
        [[ "$dev" == "$SELECTED_GPU_PCI" ]] && continue
        if _is_pci_function_assigned_to_vm "$dev" "$SELECTED_VMID"; then
            msg_ok "$(translate 'Device already present in target VM — existing hostpci entry reused'): ${dev}" | tee -a "$screen_capture"
            continue
        fi
        if qm set "$SELECTED_VMID" --hostpci${idx} "${dev},pcie=1" >>"$LOG_FILE" 2>&1; then
            msg_ok "$(translate 'Device added'): hostpci${idx}: ${dev},pcie=1" | tee -a "$screen_capture"
        else
            msg_error "$(translate 'Failed to add IOMMU group device'): ${dev}" | tee -a "$screen_capture"
            return 1
        fi
        idx=$((idx + 1))
    done

    # Optional sibling GPU audio function (typically *.1) when split from IOMMU group
    for dev in "${EXTRA_AUDIO_DEVICES[@]}"; do
        if _is_pci_function_assigned_to_vm "$dev" "$SELECTED_VMID"; then
            msg_ok "$(translate 'GPU audio already present in target VM — existing hostpci entry reused'): ${dev}" | tee -a "$screen_capture"
            continue
        fi
        if qm set "$SELECTED_VMID" --hostpci${idx} "${dev},pcie=1" >>"$LOG_FILE" 2>&1; then
            msg_ok "$(translate 'GPU audio added'): hostpci${idx}: ${dev},pcie=1" | tee -a "$screen_capture"
        else
            msg_error "$(translate 'Failed to add GPU audio function'): ${dev}" | tee -a "$screen_capture"
            return 1
        fi
        idx=$((idx + 1))
    done

    # NVIDIA: hide KVM hypervisor from guest
    [[ "$SELECTED_GPU" == "nvidia" ]] && _configure_nvidia_kvm_hide
    return 0
}

_configure_nvidia_kvm_hide() {
    msg_info "$(translate 'Configuring NVIDIA KVM hiding...')"

    # CPU: host,hidden=1
    local current_cpu
    current_cpu=$(qm config "$SELECTED_VMID" 2>/dev/null | grep "^cpu:" | awk '{print $2}')
    if ! echo "$current_cpu" | grep -q "hidden=1"; then
        qm set "$SELECTED_VMID" --cpu "host,hidden=1,flags=+pcid" >>"$LOG_FILE" 2>&1
        msg_ok "$(translate 'CPU set to host,hidden=1,flags=+pcid')" | tee -a "$screen_capture"
    else
        msg_ok "$(translate 'NVIDIA CPU hiding already configured')" | tee -a "$screen_capture"
    fi

    # args: kvm=off + vendor_id spoof
    local current_args
    current_args=$(qm config "$SELECTED_VMID" 2>/dev/null | grep "^args:" | sed 's/^args: //')
    if ! echo "$current_args" | grep -q "kvm=off"; then
        local kvm_args="-cpu 'host,+kvm_pv_unhalt,+kvm_pv_eoi,hv_vendor_id=NV43FIX,kvm=off'"
        local new_args
        if [[ -n "$current_args" ]]; then
            new_args="${current_args} ${kvm_args}"
        else
            new_args="$kvm_args"
        fi
        qm set "$SELECTED_VMID" --args "$new_args" >>"$LOG_FILE" 2>&1
        msg_ok "$(translate 'NVIDIA KVM args configured (kvm=off, vendor_id spoof)')" | tee -a "$screen_capture"
    else
        msg_ok "$(translate 'NVIDIA KVM hiding already configured')" | tee -a "$screen_capture"
    fi
}


# ── Update initramfs ─────────────────────────────────────
update_initramfs_host() {
    msg_info "$(translate 'Updating initramfs (this may take a minute)...')"
    update-initramfs -u -k all >>"$LOG_FILE" 2>&1
    msg_ok "$(translate 'initramfs updated')" | tee -a "$screen_capture"
}


# ==========================================================
# Main
# ==========================================================
main() {
    parse_cli_args "$@"

    : >"$LOG_FILE"
    : >"$screen_capture"
    [[ "$WIZARD_CALL" == "true" ]] && _set_wizard_result "cancelled"

    # ── Phase 1: all dialogs (no terminal output) ─────────
    detect_host_gpus
    check_iommu_enabled
    select_gpu
    check_sriov_and_block_if_needed
    warn_single_gpu
    select_vm
    ensure_selected_gpu_not_already_in_target_vm
    check_gpu_vm_compatibility
    analyze_iommu_group
    detect_optional_gpu_audio
    check_vm_machine_type
    check_switch_mode
    evaluate_host_reboot_requirement
    confirm_summary

    # ── Phase 2: processing ───────────────────────────────
    local run_title
    run_title=$(_get_vm_run_title)
    if [[ "$WIZARD_CALL" == "true" ]]; then
        echo
    else
        show_proxmenux_logo
        msg_title "${run_title}"
    fi

    if [[ "$VM_SWITCH_ALREADY_VFIO" == "true" ]]; then
        msg_ok "$(translate 'Host already in VFIO mode — skipping host reconfiguration for VM reassignment')" | tee -a "$screen_capture"
    else
        add_vfio_modules
        configure_vfio_pci_ids
        configure_iommu_options
        [[ "$SELECTED_GPU" == "amd" ]] && add_softdep_amd
        blacklist_gpu_drivers
        [[ "$SELECTED_GPU" == "amd" ]] && dump_amd_rom
    fi
    [[ "$SELECTED_GPU" == "nvidia" ]] && sanitize_nvidia_host_stack_for_vfio
    cleanup_lxc_configs
    cleanup_vm_config
    ensure_vm_display_std
    if ! configure_vm; then
        msg_error "$(translate 'VM passthrough configuration failed. Review the log and VM config.')"
        [[ "$WIZARD_CALL" == "true" ]] && _set_wizard_result "failed"
        rm -f "$screen_capture"
        exit 1
    fi
    if declare -F attach_proxmenux_gpu_guard_to_vm >/dev/null 2>&1; then
        ensure_proxmenux_gpu_guard_hookscript
        attach_proxmenux_gpu_guard_to_vm "$SELECTED_VMID"
        sync_proxmenux_gpu_guard_hooks
    fi
    [[ "$HOST_CONFIG_CHANGED" == "true" ]] && update_initramfs_host

    # ── Phase 3: summary ─────────────────────────────────
    if [[ "$WIZARD_CALL" == "true" ]]; then
        echo
    else
        show_proxmenux_logo
        msg_title "${run_title}"
        cat "$screen_capture"
        echo
    fi

    if [[ "$WIZARD_CALL" == "true" ]]; then
        if [[ "$HOST_CONFIG_CHANGED" == "true" ]]; then
            _set_wizard_result "applied_reboot_required"
        else
            _set_wizard_result "applied"
        fi
        rm -f "$screen_capture"
        return 0
    fi

    echo -e "${TAB}${BL}📄 Log: ${LOG_FILE}${CL}"
    if [[ "$HOST_CONFIG_CHANGED" == "true" ]]; then
        echo -e "${TAB}${DGN}- $(translate 'Host VFIO configuration changed — reboot required before starting the VM.')${CL}"
    else
        echo -e "${TAB}${DGN}- $(translate 'Host VFIO config was already up to date — no reboot needed.')${CL}"
    fi

    case "$SELECTED_GPU" in
        nvidia)
            echo -e "${TAB}${DGN}- $(translate 'Install NVIDIA drivers from nvidia.com inside the guest.')${CL}"
            echo -e "${TAB}${DGN}- $(translate 'If Code 43 error appears, KVM hiding is already configured.')${CL}"
            ;;
        amd)
            echo -e "${TAB}${DGN}- $(translate 'Install AMD GPU drivers inside the guest.')${CL}"
            echo -e "${TAB}${DGN}- $(translate 'If passthrough fails on Windows: install RadeonResetBugFix.')${CL}"
            [[ -n "$AMD_ROM_FILE" ]] && \
            echo -e "${TAB}${DGN}- $(translate 'ROM file used'): /usr/share/kvm/${AMD_ROM_FILE}${CL}"
            ;;
        intel)
            echo -e "${TAB}${DGN}- $(translate 'Install Intel Graphics Driver inside the guest.')${CL}"
            echo -e "${TAB}${DGN}- $(translate 'Enable Remote Desktop (RDP) before disabling the virtual display.')${CL}"
            ;;
    esac

    echo
    msg_info2 "$(translate 'If you want to use a physical monitor on the passthrough GPU:')"
    echo "  • $(translate 'First install the GPU drivers inside the guest and verify remote access (RDP/SSH).')"
    echo "  • $(translate 'Then change the VM display to none (vga: none) when the guest is stable.')"

    echo
    msg_success "$(translate 'GPU passthrough configured for VM') ${SELECTED_VMID} (${VM_NAME})."
    echo

    rm -f "$screen_capture"

    # Final reboot prompt. Whiptail is invoked directly (not through
    # the _pmx_yesno helper) because the ProxMenux menu chain
    # (menu → main_menu → hw_grafics_menu → add_gpu_vm) has been
    # verified to work reliably with a bare whiptail here, while the
    # dialog-based helper path hits process-group / TTY edge cases in
    # that exact chain.
    #
    # The extra `Press Enter to continue ... read -r` between whiptail
    # and `reboot` is deliberate — it gives the user a visible pause
    # after the dialog closes so an accidental Enter on the yes button
    # cannot trigger an immediate reboot.
    if [[ "$HOST_CONFIG_CHANGED" == "true" ]]; then
        whiptail --title "$(translate 'Reboot Required')" \
            --yesno "$(translate 'A reboot is required for VFIO binding to take effect. Do you want to restart now?')" 10 68
        if [[ $? -eq 0 ]]; then
            msg_success "$(translate 'Press Enter to continue...')"
            read -r
            msg_warn "$(translate 'Rebooting the system...')"
            reboot
        else
            msg_info2 "$(translate 'You can reboot later manually.')"
            msg_success "$(translate 'Press Enter to continue...')"
            read -r
        fi
    else
        msg_success "$(translate 'Press Enter to continue...')"
        read -r
    fi
}

main "$@"
