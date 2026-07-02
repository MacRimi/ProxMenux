#!/usr/bin/env bash
# ==========================================================
# kernel_pin_plan.sh — JSON reporter for cross-kernel restore
# ==========================================================
# Usage:  bash kernel_pin_plan.sh <staging_root>
# Output: JSON on stdout — one of:
#
#   {"detected":false}
#     Backup + target run the same kernel major.minor.
#     No action needed.
#
#   {"detected":true,
#    "backup_kernel":"6.17.2-1-pve",
#    "target_kernel":"7.0.12-1-pve",
#    "action":"installed",
#    "pkg":"proxmox-kernel-6.17.2-1-pve-signed"}
#     Cross-kernel. The backup's kernel is already installed on the
#     target; the restore flow will pin it.
#
#   {"detected":true, ...,
#    "action":"installable",
#    "pkg":"proxmox-kernel-6.17.2-1-pve-signed"}
#     Cross-kernel. The kernel is available in Proxmox repos and
#     will be installed before the pin.
#
#   {"detected":true, ...,
#    "action":"unavailable",
#    "reason":"not installed on this host and not available in the
#             configured Proxmox repositories"}
#     Cross-kernel. The kernel is neither installed nor obtainable.
#     The restore flow must refuse.
#
# The heavy lifting is delegated to hb_kernel_pin_plan in
# lib_host_backup_common.sh, so the CLI menu and the Web Monitor
# agree byte-for-byte on which restores are safe to start.
# ==========================================================
set -euo pipefail

staging_root="${1:-}"
[[ -z "$staging_root" || ! -d "$staging_root" ]] && {
    printf '{"detected":false,"error":"staging_root missing"}\n'
    exit 0
}

LIB="/usr/local/share/proxmenux/scripts/backup_restore/lib_host_backup_common.sh"
if [[ ! -f "$LIB" ]]; then
    printf '{"detected":false,"error":"lib_host_backup_common.sh not found"}\n'
    exit 0
fi
# shellcheck source=/dev/null
source "$LIB"

# Read the backup's kernel release.
bk_kernel=""
if [[ -f "$staging_root/metadata/run_info.env" ]]; then
    bk_kernel=$(grep -m1 '^kernel=' "$staging_root/metadata/run_info.env" 2>/dev/null \
        | cut -d= -f2-)
fi
cur_kernel=$(uname -r 2>/dev/null || echo "")

if [[ -z "$bk_kernel" || -z "$cur_kernel" ]]; then
    printf '{"detected":false}\n'
    exit 0
fi

# Compare major.minor — the same rule hb_compat_check uses.
bk_mm=$(echo "$bk_kernel" | cut -d. -f1-2)
cur_mm=$(echo "$cur_kernel" | cut -d. -f1-2)
if [[ "$bk_mm" == "$cur_mm" ]]; then
    printf '{"detected":false}\n'
    exit 0
fi

# Cross-kernel: compute the pin plan.
hb_kernel_pin_plan "$bk_kernel"

# Emit JSON. jq if we have it (safer with special chars), else printf.
if command -v jq >/dev/null 2>&1; then
    jq -cn \
        --arg bkk "$bk_kernel" \
        --arg trk "$cur_kernel" \
        --arg act "${HB_KERNEL_PIN_ACTION:-unavailable}" \
        --arg pkg "${HB_KERNEL_PIN_PKG:-}" \
        --arg rsn "${HB_KERNEL_PIN_REASON:-}" \
        '{detected:true, backup_kernel:$bkk, target_kernel:$trk,
          action:$act, pkg:$pkg, reason:$rsn}'
else
    printf '{"detected":true,"backup_kernel":"%s","target_kernel":"%s","action":"%s","pkg":"%s","reason":"%s"}\n' \
        "$bk_kernel" "$cur_kernel" \
        "${HB_KERNEL_PIN_ACTION:-unavailable}" \
        "${HB_KERNEL_PIN_PKG:-}" \
        "${HB_KERNEL_PIN_REASON:-}"
fi
