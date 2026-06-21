#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — pre-flight compatibility checks
# ==========================================================
# Runs every pre-flight check against the destination host's current
# state and emits a JSON report. The orchestrator (run_restore.sh)
# decides go/no-go based on whether any check has severity=fail.
#
# Severity levels:
#   pass — green, restore can proceed for this dimension
#   warn — proceed but operator should know (e.g. RAM lower than source,
#          NIC MAC absent, PBS role missing but PVE present)
#   fail — must address before proceeding (e.g. CPU arch mismatch,
#          PVE version older than backup)
#
# Usage:
#   preflight_checks.sh <manifest-json-path-or-archive>
#
# Stdout: JSON {checks: [...], summary: {pass: N, warn: N, fail: N}}.
# Exit code: 0 if all checks pass or warn; 1 if any fail.
# ==========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:-}"

if [[ -z "$SOURCE" ]]; then
  printf 'preflight_checks: missing manifest source\n' >&2
  exit 64
fi

manifest="$(bash "$SCRIPT_DIR/parse_manifest.sh" "$SOURCE")"

# Collect "current host" facts up-front so the checks themselves
# stay declarative.
cur_hostname="$(hostname)"
cur_pve_full="$(pveversion 2>/dev/null | head -1 || true)"
cur_pve_ver="$(printf '%s\n' "$cur_pve_full" | sed -nE 's@^pve-manager/([0-9.]+)/.*@\1@p')"
cur_pbs_present=0
command -v proxmox-backup-manager >/dev/null 2>&1 && cur_pbs_present=1
cur_kernel="$(uname -r)"
cur_boot_mode="$([ -d /sys/firmware/efi ] && echo efi || echo bios)"
cur_root_fs="$(findmnt -no FSTYPE / 2>/dev/null || echo unknown)"
cur_cpu_arch="$(uname -m)"
case "$cur_cpu_arch" in x86_64|amd64) cur_cpu_arch=x86_64 ;; aarch64|arm64) cur_cpu_arch=aarch64 ;; esac
cur_memory_kb="$(awk '/^MemTotal:/{print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"

# Manifest-side facts
m_source="$(printf '%s' "$manifest" | jq -c '.source_host')"
m_pve="$(printf '%s' "$m_source" | jq -r '.pve_version // ""')"
m_pbs="$(printf '%s' "$m_source" | jq -r '.pbs_version // ""')"
m_roles="$(printf '%s' "$m_source" | jq -c '.roles')"
m_boot_mode="$(printf '%s' "$m_source" | jq -r '.boot_mode')"
m_root_fs="$(printf '%s' "$m_source" | jq -r '.root_fs // ""')"
m_cpu_arch="$(printf '%s' "$m_source" | jq -r '.cpu_arch')"
m_memory_kb="$(printf '%s' "$m_source" | jq -r '.memory_kb')"
m_hostname="$(printf '%s' "$m_source" | jq -r '.hostname')"

checks='[]'

# Helper to compare semver-style strings as tuples. Returns 0 if $1 ≥ $2.
ver_ge() {
  # Pad both to (major,minor,patch) and compare numerically.
  local a b
  IFS='.' read -ra a <<< "$1"
  IFS='.' read -ra b <<< "$2"
  for i in 0 1 2; do
    local av="${a[$i]:-0}" bv="${b[$i]:-0}"
    av="${av%%-*}"; bv="${bv%%-*}"   # strip pre-release suffixes
    av="$(printf '%d' "$av" 2>/dev/null || echo 0)"
    bv="$(printf '%d' "$bv" 2>/dev/null || echo 0)"
    if   (( av > bv )); then return 0
    elif (( av < bv )); then return 1
    fi
  done
  return 0
}

add_check() {
  local id="$1" severity="$2" message="$3" details="${4:-null}"
  checks="$(jq --argjson acc "$checks" \
    --arg id "$id" --arg sev "$severity" --arg msg "$message" --argjson det "$details" \
    -n '$acc + [{id: $id, severity: $sev, message: $msg, details: $det}]')"
}

# ── Check 1: CPU arch must match ──
if [[ "$cur_cpu_arch" == "$m_cpu_arch" ]]; then
  add_check cpu_arch_match pass "CPU arch matches ($cur_cpu_arch)"
else
  add_check cpu_arch_match fail \
    "Source $m_cpu_arch ≠ destination $cur_cpu_arch — backup is not portable across architectures" \
    "$(jq -n --arg s "$m_cpu_arch" --arg d "$cur_cpu_arch" '{source: $s, destination: $d}')"
fi

# ── Check 2: Boot mode (efi vs bios) ──
if [[ "$cur_boot_mode" == "$m_boot_mode" ]]; then
  add_check boot_mode_match pass "Boot mode matches ($cur_boot_mode)"
else
  add_check boot_mode_match warn \
    "Source $m_boot_mode ≠ destination $cur_boot_mode. Bootloader config from the backup will not apply." \
    "$(jq -n --arg s "$m_boot_mode" --arg d "$cur_boot_mode" '{source: $s, destination: $d}')"
fi

# ── Check 3: Root filesystem family ──
if [[ -n "$m_root_fs" ]]; then
  if [[ "$cur_root_fs" == "$m_root_fs" ]]; then
    add_check root_fs_match pass "Root filesystem matches ($cur_root_fs)"
  else
    add_check root_fs_match warn \
      "Source root_fs=$m_root_fs vs destination $cur_root_fs. Fine for config-only restore, but ZFS-specific paths from the backup may need manual adjustment." \
      "$(jq -n --arg s "$m_root_fs" --arg d "$cur_root_fs" '{source: $s, destination: $d}')"
  fi
fi

# ── Check 4: PVE version ──
if [[ -n "$m_pve" ]]; then
  if [[ -z "$cur_pve_ver" ]]; then
    add_check pve_version fail \
      "Source had PVE $m_pve but destination has no PVE installed" \
      "$(jq -n --arg s "$m_pve" '{source_version: $s, destination_version: null}')"
  elif ver_ge "$cur_pve_ver" "$m_pve"; then
    add_check pve_version pass \
      "Destination PVE $cur_pve_ver ≥ source $m_pve"
  else
    add_check pve_version warn \
      "Destination PVE $cur_pve_ver is OLDER than source $m_pve. New config files may reference fields the older PVE doesn't recognise." \
      "$(jq -n --arg s "$m_pve" --arg d "$cur_pve_ver" '{source: $s, destination: $d}')"
  fi
fi

# ── Check 5: PBS role ──
roles_have_pbs="$(printf '%s' "$m_roles" | jq 'index("pbs") != null')"
if [[ "$roles_have_pbs" == "true" ]]; then
  if [[ "$cur_pbs_present" == 1 ]]; then
    add_check pbs_role pass "Destination has PBS — manifest's pbs role can be restored"
  else
    add_check pbs_role warn \
      "Source had PBS role but destination has no PBS installed. PBS-related configs will be ignored unless you install proxmox-backup-server first."
  fi
fi

# ── Check 6: Memory ──
if [[ "$m_memory_kb" -gt 0 && "$cur_memory_kb" -gt 0 ]]; then
  # 80% rule — destination must have at least 80% of source RAM.
  threshold_kb=$(( m_memory_kb * 80 / 100 ))
  if [[ "$cur_memory_kb" -ge "$m_memory_kb" ]]; then
    add_check memory pass "Destination $(( cur_memory_kb / 1024 ))MB ≥ source $(( m_memory_kb / 1024 ))MB"
  elif [[ "$cur_memory_kb" -ge "$threshold_kb" ]]; then
    add_check memory warn \
      "Destination $(( cur_memory_kb / 1024 ))MB is below source $(( m_memory_kb / 1024 ))MB but within 80% threshold. VMs may need memory limits reduced."
  else
    add_check memory fail \
      "Destination $(( cur_memory_kb / 1024 ))MB is below 80% of source $(( m_memory_kb / 1024 ))MB. VMs from the backup will likely refuse to start." \
      "$(jq -n --argjson s "$m_memory_kb" --argjson d "$cur_memory_kb" '{source_kb: $s, destination_kb: $d}')"
  fi
fi

# ── Check 7: Required by-id disks present ──
required_disks="$(printf '%s' "$manifest" | jq -r '
  [.storage_inventory.zfs_pools[]?.devices_by_id[]?]
  + [.storage_inventory.physical_disks[]?.by_id // empty]
  | unique[]
' | grep -v '^$' || true)"

missing_disks='[]'
present_disks='[]'
while IFS= read -r dev; do
  [[ -z "$dev" ]] && continue
  if [[ -e "/dev/disk/by-id/$dev" ]]; then
    present_disks="$(jq --argjson acc "$present_disks" --arg d "$dev" -n '$acc + [$d]')"
  else
    missing_disks="$(jq --argjson acc "$missing_disks" --arg d "$dev" -n '$acc + [$d]')"
  fi
done <<< "$required_disks"

missing_count="$(printf '%s' "$missing_disks" | jq 'length')"
present_count="$(printf '%s' "$present_disks" | jq 'length')"
total_count=$(( missing_count + present_count ))

if [[ "$total_count" == 0 ]]; then
  add_check disk_inventory pass "Manifest declares no by-id disks (no ZFS pools to import)"
elif [[ "$missing_count" == 0 ]]; then
  add_check disk_inventory pass "All $present_count required by-id disks present" \
    "$(jq -n --argjson p "$present_disks" '{present: $p}')"
else
  add_check disk_inventory warn \
    "$missing_count of $total_count required by-id disks are missing. Affected ZFS pools / storages cannot auto-import." \
    "$(jq -n --argjson m "$missing_disks" --argjson p "$present_disks" '{missing: $m, present: $p}')"
fi

# ── Check 8: NIC MACs present ──
required_macs="$(printf '%s' "$manifest" | jq -r '.hardware_inventory.nic[]?.mac // empty')"
current_macs="$(ip -j link 2>/dev/null | jq -r '.[].address' 2>/dev/null | sort -u)"

missing_macs='[]'
matched_macs='[]'
while IFS= read -r mac; do
  [[ -z "$mac" ]] && continue
  if printf '%s\n' "$current_macs" | grep -qFx "$mac"; then
    matched_macs="$(jq --argjson acc "$matched_macs" --arg m "$mac" -n '$acc + [$m]')"
  else
    missing_macs="$(jq --argjson acc "$missing_macs" --arg m "$mac" -n '$acc + [$m]')"
  fi
done <<< "$required_macs"

mac_missing="$(printf '%s' "$missing_macs" | jq 'length')"
mac_total=$(( mac_missing + $(printf '%s' "$matched_macs" | jq 'length') ))
if [[ "$mac_total" == 0 ]]; then
  add_check nic_macs pass "Manifest declares no NICs"
elif [[ "$mac_missing" == 0 ]]; then
  add_check nic_macs pass "All $mac_total NIC MACs from source present on destination"
else
  add_check nic_macs warn \
    "$mac_missing of $mac_total source NIC MACs are absent. Bridge memberships referencing those interfaces will need manual remap." \
    "$(jq -n --argjson m "$missing_macs" --argjson p "$matched_macs" '{missing: $m, matched: $p}')"
fi

# ── Check 9: Hostname collision ──
if [[ "$cur_hostname" == "$m_hostname" ]]; then
  add_check hostname pass "Hostname unchanged ($cur_hostname)"
else
  add_check hostname warn \
    "Source hostname '$m_hostname' ≠ destination '$cur_hostname'. Restoring /etc/hostname will change it; this affects PVE cluster identity and some certs." \
    "$(jq -n --arg s "$m_hostname" --arg d "$cur_hostname" '{source: $s, destination: $d}')"
fi

# Compose final report
summary="$(printf '%s' "$checks" | jq '
  reduce .[] as $c ({pass: 0, warn: 0, fail: 0};
    .[$c.severity] += 1)
')"
fail_count="$(printf '%s' "$summary" | jq '.fail')"

jq -n \
  --argjson checks "$checks" \
  --argjson summary "$summary" \
  '{ checks: $checks, summary: $summary }'

exit "$([ "$fail_count" -eq 0 ] && echo 0 || echo 1)"
