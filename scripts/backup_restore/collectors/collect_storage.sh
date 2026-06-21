#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest collector — storage_inventory
# ==========================================================
# ZFS pools (with stable by-id devices), LVM VGs + thin pools,
# physical disks, PVE storage.cfg, and external mounts.
# Read-only. Schema:
# scripts/backup_restore/schema/manifest.schema.json
# ==========================================================
set -euo pipefail

# ── ZFS pools ──
zfs_pools='[]'
if command -v zpool >/dev/null 2>&1; then
  while IFS= read -r pool; do
    [[ -z "$pool" ]] && continue
    # type: parse zpool status — first vdev line after 'config:' header.
    # Single-device pool shows the device directly; mirror/raidz prefix the
    # vdev type. We look at the indented children list.
    pool_type="single"
    devices='[]'
    # `zpool status -P` outputs full /dev/disk/by-id/... paths for the
    # member disks. We isolate the first whitespace-delimited token on
    # each child line and decide:
    #   - vdev type lines (mirror-0, raidz1-0, stripe, ...) → pool type
    #   - leaf device lines (/dev/disk/by-id/* or /dev/sd*) → membership
    while IFS= read -r vdev_line; do
      token="$(printf '%s' "$vdev_line" | awk '{print $1}')"
      [[ -z "$token" || "$token" == "NAME" || "$token" == "$pool" ]] && continue
      case "$token" in
        mirror-*)  pool_type="mirror" ;;
        raidz1-*)  pool_type="raidz1" ;;
        raidz2-*)  pool_type="raidz2" ;;
        raidz3-*)  pool_type="raidz3" ;;
        stripe-*)  pool_type="stripe" ;;
        /dev/disk/by-id/*)
          # Strip the /dev/disk/by-id/ prefix for the schema field;
          # leave any -partN suffix in place — the restore wizard uses
          # the exact same string to look the disk back up.
          dev_name="${token#/dev/disk/by-id/}"
          devices="$(jq --argjson acc "$devices" --arg d "$dev_name" -n '$acc + [$d]')"
          ;;
        /dev/*)
          # Fallback: ZFS pool created with raw /dev/sdX paths. Record
          # them as-is; restore will need to remap manually.
          devices="$(jq --argjson acc "$devices" --arg d "$token" -n '$acc + [$d]')"
          ;;
      esac
    done < <(zpool status -P "$pool" 2>/dev/null | awk '/^config:/{flag=1; next} /^errors:/{flag=0} flag')

    size_bytes="$(zpool list -H -p -o size "$pool" 2>/dev/null || echo 0)"
    health="$(zpool list -H -o health "$pool" 2>/dev/null || echo UNKNOWN)"
    compression="$(zfs get -H -o value compression "$pool" 2>/dev/null || echo "")"
    mountpoint="$(zfs get -H -o value mountpoint "$pool" 2>/dev/null || echo "")"

    zfs_pools="$(jq --argjson acc "$zfs_pools" \
      --arg name "$pool" \
      --arg type "$pool_type" \
      --argjson devices "$devices" \
      --arg mountpoint "$mountpoint" \
      --arg compression "$compression" \
      --argjson size_bytes "${size_bytes:-0}" \
      --arg health "$health" \
      -n '
      $acc + [{
        name:          $name,
        type:          $type,
        devices_by_id: $devices,
        mountpoint:    $mountpoint,
        compression:   $compression,
        size_bytes:    $size_bytes,
        health:        $health
      }]
      ')"
  done < <(zpool list -H -o name 2>/dev/null || true)
fi

# ── LVM VGs + thin pools ──
lvm_vgs='[]'
if command -v vgs >/dev/null 2>&1; then
  # vgs --reportformat json --units b is reliable in lvm2 ≥ 2.02
  vg_json="$(vgs --reportformat json --units b --noheadings -o vg_name,vg_size 2>/dev/null || echo '{}')"
  while IFS= read -r vg_name; do
    [[ -z "$vg_name" || "$vg_name" == "null" ]] && continue
    vg_size="$(printf '%s' "$vg_json" | jq -r --arg n "$vg_name" '.report[0].vg[]? | select(.vg_name == $n) | .vg_size' | sed 's/[Bb]$//' | head -1)"
    # Thin pools in this VG
    thin_pools='[]'
    while IFS= read -r lv_line; do
      [[ -z "$lv_line" ]] && continue
      lv_name="$(printf '%s' "$lv_line" | awk '{print $1}')"
      lv_size="$(printf '%s' "$lv_line" | awk '{print $2}' | sed 's/[Bb]$//')"
      thin_pools="$(jq --argjson acc "$thin_pools" \
        --arg n "$lv_name" --argjson s "${lv_size:-0}" \
        -n '$acc + [{lv_name: $n, size_bytes: $s}]')"
    done < <(lvs --noheadings --units b -o lv_name,lv_size --select "vg_name=$vg_name && lv_attr=~^t" 2>/dev/null || true)

    lvm_vgs="$(jq --argjson acc "$lvm_vgs" \
      --arg n "$vg_name" --argjson s "${vg_size:-0}" --argjson tp "$thin_pools" \
      -n '$acc + [{name: $n, size_bytes: $s, thin_pools: $tp}]')"
  done < <(printf '%s' "$vg_json" | jq -r '.report[0].vg[]?.vg_name' 2>/dev/null || true)
fi

# ── Physical disks (by-id resolution) ──
physical_disks='[]'
# Build name → by-id map by walking /dev/disk/by-id/. A single block
# device usually has multiple by-id symlinks (ata-*, wwn-*, scsi-*, …).
# We prefer the most human-readable identifier in this order:
#   ata-* → nvme-* → scsi-* → usb-* → wwn-*
# This also makes the manifest consistent with what `zpool status -P`
# reports (zpool defaults to ata-* / wwn-* depending on bus).
declare -A by_id_for
declare -A by_id_priority_for
priority_for_id() {
  case "$1" in
    ata-*)  echo 1 ;;
    nvme-*) echo 2 ;;
    scsi-*) echo 3 ;;
    usb-*)  echo 4 ;;
    wwn-*)  echo 5 ;;
    *)      echo 9 ;;
  esac
}
if [[ -d /dev/disk/by-id ]]; then
  for link in /dev/disk/by-id/*; do
    [[ -L "$link" ]] || continue
    by_id="$(basename "$link")"
    # Skip partition symlinks — we want whole-disk only.
    [[ "$by_id" == *-part* ]] && continue
    target="$(basename "$(readlink -f "$link")")"
    [[ -z "$target" ]] && continue
    new_prio="$(priority_for_id "$by_id")"
    cur_prio="${by_id_priority_for[$target]:-99}"
    if (( new_prio < cur_prio )); then
      by_id_for["$target"]="$by_id"
      by_id_priority_for["$target"]="$new_prio"
    fi
  done
fi

# lsblk -d -b -J for whole disks
lsblk_json="$(lsblk -d -b -o NAME,MODEL,SIZE,TYPE -J 2>/dev/null || echo '{}')"
while IFS= read -r disk_line; do
  [[ -z "$disk_line" ]] && continue
  name="$(printf '%s' "$disk_line" | jq -r '.name')"
  model="$(printf '%s' "$disk_line" | jq -r '.model // ""')"
  size="$(printf '%s' "$disk_line" | jq -r '.size // 0')"
  type="$(printf '%s' "$disk_line" | jq -r '.type')"
  # Only PHYSICAL disks.
  # - skip non-disk types (rom, loop)
  # - skip zd* (ZFS zvols backing VMs)
  # - skip dm-* (LVM-mapped devices)
  # - skip loop* (defensive — type filter usually catches it)
  [[ "$type" != "disk" ]] && continue
  case "$name" in
    zd*|dm-*|loop*) continue ;;
  esac
  by_id="${by_id_for[$name]:-}"
  physical_disks="$(jq --argjson acc "$physical_disks" \
    --arg n "$name" --arg m "$model" --argjson s "${size:-0}" --arg bid "$by_id" \
    -n '
    $acc + [{
      name:       $n,
      model:      (if $m == "" then null else $m end),
      size_bytes: $s,
      by_id:      (if $bid == "" then null else $bid end)
    }]
    ')"
done < <(printf '%s' "$lsblk_json" | jq -c '.blockdevices[]?' 2>/dev/null || true)

# ── PVE storage.cfg ──
# Format is whitespace-key-value with blank-line separators:
#   <type>: <id>
#       key value
#       key value
pve_storage='[]'
if [[ -r /etc/pve/storage.cfg ]]; then
  current_type=""; current_id=""; current_extra='{}'
  flush() {
    if [[ -n "$current_id" ]]; then
      pve_storage="$(jq --argjson acc "$pve_storage" \
        --arg id "$current_id" --arg t "$current_type" --argjson e "$current_extra" \
        -n '$acc + [(($e) + {id: $id, type: $t})]')"
    fi
    current_type=""; current_id=""; current_extra='{}'
  }
  while IFS= read -r line; do
    if [[ -z "${line// }" ]]; then
      flush; continue
    fi
    if [[ "$line" =~ ^([a-z]+):[[:space:]]+([A-Za-z0-9_.-]+) ]]; then
      flush
      current_type="${BASH_REMATCH[1]}"
      current_id="${BASH_REMATCH[2]}"
    elif [[ "$line" =~ ^[[:space:]]+([a-z_]+)[[:space:]]+(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="${BASH_REMATCH[2]}"
      case "$key" in
        # `content` is a comma-separated list — split into JSON array
        content)
          content_array="$(printf '%s\n' "$val" | tr ',' '\n' | jq -R . | jq -s .)"
          current_extra="$(jq --argjson e "$current_extra" --argjson c "$content_array" -n '$e + {content: $c}')"
          ;;
        *)
          current_extra="$(jq --argjson e "$current_extra" --arg k "$key" --arg v "$val" -n '$e + {($k): $v}')"
          ;;
      esac
    fi
  done < /etc/pve/storage.cfg
  flush
fi

# ── External mounts (NFS/CIFS/etc.) ──
# Filter on filesystem types we care about for the manifest. Drop FUSE
# pmxcfs (/etc/pve), tmpfs, devtmpfs, autofs, ZFS internals already
# accounted for. NFS, CIFS, ISO mount points are the interesting ones.
mounts='[]'
if command -v findmnt >/dev/null 2>&1; then
  while IFS= read -r mline; do
    [[ -z "$mline" ]] && continue
    target="$(printf '%s' "$mline" | jq -r '.target')"
    source="$(printf '%s' "$mline" | jq -r '.source')"
    fstype="$(printf '%s' "$mline" | jq -r '.fstype')"
    options="$(printf '%s' "$mline" | jq -r '.options // ""')"
    mounts="$(jq --argjson acc "$mounts" \
      --arg t "$target" --arg s "$source" --arg f "$fstype" --arg o "$options" \
      -n '
      $acc + [{
        target: $t,
        source: $s,
        fstype: $f,
        options: (if $o == "" then null else $o end)
      }]
      ')"
  done < <(findmnt -t nfs,nfs4,cifs,smbfs,fuseblk,fuse.glusterfs -J 2>/dev/null \
            | jq -c '.. | objects | select(.target?)' 2>/dev/null \
            | grep -vE '"target":"/etc/pve"' || true)
fi

# Compose
jq -n \
  --argjson zfs_pools       "$zfs_pools" \
  --argjson lvm_vgs         "$lvm_vgs" \
  --argjson physical_disks  "$physical_disks" \
  --argjson pve_storage     "$pve_storage" \
  --argjson mounts          "$mounts" \
  '{
    zfs_pools:        $zfs_pools,
    lvm:              { vgs: $lvm_vgs },
    physical_disks:   $physical_disks,
    pve_storage_cfg:  $pve_storage,
    mounts:           $mounts
  }'
