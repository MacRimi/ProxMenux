#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest collector — vms_lxcs_at_backup
# ==========================================================
# Enumerates VMs (qm list) and LXCs (pct list) on this PVE node.
# Read-only; emits the metadata only — actual VM/LXC data is
# the responsibility of vzdump / PBS, not this manifest.
# Schema: scripts/backup_restore/schema/manifest.schema.json
# ==========================================================
set -euo pipefail

vms='[]'
lxcs='[]'

# ── VMs (qm list) ──
# Output:
#       VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
#        100 Alpine-Linux-3-21    stopped    4096               0.00 0
# Header line starts with VMID; we skip it.
if command -v qm >/dev/null 2>&1; then
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    # Skip the header
    [[ "$line" =~ ^[[:space:]]*VMID[[:space:]] ]] && continue
    # Parse positionally. NAME can contain spaces, but `qm list` pads/columns
    # them, so we use fixed positions: VMID at col 1, STATUS as the 3rd
    # whitespace-delimited token from the END (mem, bootdisk, pid are after).
    vmid="$(printf '%s' "$line" | awk '{print $1}')"
    [[ "$vmid" =~ ^[0-9]+$ ]] || continue
    # Strip trailing PID + BOOTDISK + MEM(MB) + STATUS to extract the NAME.
    # rev → cut → rev technique:
    trailing="$(printf '%s' "$line" | awk '{printf "%s %s %s %s", $(NF-3), $(NF-2), $(NF-1), $NF}')"
    status="$(printf '%s' "$trailing" | awk '{print $1}')"
    memory_mb="$(printf '%s' "$trailing" | awk '{print $2}')"
    bootdisk_gb="$(printf '%s' "$trailing" | awk '{print $3}')"
    # Name: drop first column (vmid) and last 4 columns
    name="$(printf '%s' "$line" | awk '{$1=""; for(i=NF-3;i<=NF;i++) $i=""; sub(/^[[:space:]]+/,""); sub(/[[:space:]]+$/,""); print}')"
    case "$status" in
      running|stopped|paused) ;;
      *) status="stopped" ;;
    esac

    vms="$(jq --argjson acc "$vms" \
      --argjson vmid "$vmid" \
      --arg name "$name" \
      --argjson memory_mb "${memory_mb:-0}" \
      --argjson bootdisk_gb "${bootdisk_gb:-0}" \
      --arg status "$status" \
      -n '
      $acc + [{
        vmid:        $vmid,
        name:        $name,
        memory_mb:   $memory_mb,
        bootdisk_gb: $bootdisk_gb,
        status:      $status,
        config_file: ("configs/qemu-server/" + ($vmid|tostring) + ".conf")
      }]
      ')"
  done < <(qm list 2>/dev/null || true)
fi

# ── LXCs (pct list) ──
# Output:
#   VMID       Status     Lock         Name
#   101        running                 alpine
# Header line starts with VMID; we skip it.
if command -v pct >/dev/null 2>&1; then
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^[[:space:]]*VMID[[:space:]] ]] && continue
    vmid="$(printf '%s' "$line" | awk '{print $1}')"
    [[ "$vmid" =~ ^[0-9]+$ ]] || continue
    status="$(printf '%s' "$line" | awk '{print $2}')"
    # Lock column is sparse; name is always last positional non-empty token
    name="$(printf '%s' "$line" | awk '{print $NF}')"
    case "$status" in
      running|stopped) ;;
      *) status="stopped" ;;
    esac

    lxcs="$(jq --argjson acc "$lxcs" \
      --argjson vmid "$vmid" \
      --arg name "$name" \
      --arg status "$status" \
      -n '
      $acc + [{
        vmid:        $vmid,
        name:        $name,
        status:      $status,
        config_file: ("configs/lxc/" + ($vmid|tostring) + ".conf")
      }]
      ')"
  done < <(pct list 2>/dev/null || true)
fi

jq -n --argjson vms "$vms" --argjson lxcs "$lxcs" \
  '{ vms: $vms, lxcs: $lxcs }'
