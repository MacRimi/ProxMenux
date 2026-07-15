#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest collector — source_host
# ==========================================================
# Emits the `source_host` section of the manifest as JSON to
# stdout. Read-only; no side effects. Schema:
# scripts/backup_restore/schema/manifest.schema.json
# ==========================================================
set -euo pipefail

# ── pve_version_full / pve_version ──
# pveversion's first line is like:
#   pve-manager/9.2.2/b9984c6d90a4bd80 (running kernel: 7.0.2-6-pve)
pve_version_full=""
pve_version=""
if command -v pveversion >/dev/null 2>&1; then
  pve_version_full="$(pveversion 2>/dev/null | head -1 || true)"
  # Extract the X.Y.Z between "pve-manager/" and "/"
  pve_version="$(printf '%s\n' "$pve_version_full" | sed -nE 's@^pve-manager/([0-9.]+)/.*@\1@p')"
fi

# ── pbs_version ──
# PBS is a separate package. If proxmox-backup-manager exists, host has PBS role.
pbs_version=""
if command -v proxmox-backup-manager >/dev/null 2>&1; then
  pbs_version="$(proxmox-backup-manager versions 2>/dev/null | awk '/^proxmox-backup-server/{print $2; exit}' || true)"
fi

# ── roles ──
roles_json='[]'
if [[ -n "$pve_version" && -n "$pbs_version" ]]; then
  roles_json='["pve","pbs"]'
elif [[ -n "$pve_version" ]]; then
  roles_json='["pve"]'
elif [[ -n "$pbs_version" ]]; then
  roles_json='["pbs"]'
else
  # No PVE, no PBS — exit with the unknown sentinel. Caller decides
  # whether to abort or generate a system-only manifest.
  roles_json='[]'
fi

# ── kernel, boot_mode, root_fs ──
kernel="$(uname -r)"
if [[ -d /sys/firmware/efi ]]; then
  boot_mode="efi"
else
  boot_mode="bios"
fi
root_fs="$(findmnt -no FSTYPE / 2>/dev/null || echo ext4)"

# ── CPU model / arch ──
cpu_model="$(lscpu 2>/dev/null | awk -F: '/^Model name/{sub(/^[ \t]+/, "", $2); print $2; exit}')"
cpu_arch="$(uname -m)"
# Normalize to schema enum
case "$cpu_arch" in
  x86_64|amd64) cpu_arch="x86_64" ;;
  aarch64|arm64) cpu_arch="aarch64" ;;
esac

# ── memory_kb ──
memory_kb="$(awk '/^MemTotal:/{print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"

# Build JSON. Use --arg for strings (always quoted), --argjson for
# numbers/arrays/null. Empty strings → null per schema convention.
jq -n \
  --arg hostname              "$(hostname)" \
  --arg pve_version           "$pve_version" \
  --arg pve_version_full      "$pve_version_full" \
  --arg pbs_version           "$pbs_version" \
  --argjson roles             "$roles_json" \
  --arg kernel                "$kernel" \
  --arg boot_mode             "$boot_mode" \
  --arg root_fs               "$root_fs" \
  --arg cpu_model             "$cpu_model" \
  --arg cpu_arch              "$cpu_arch" \
  --argjson memory_kb         "$memory_kb" \
  '{
    hostname:            $hostname,
    pve_version:         (if $pve_version == "" then null else $pve_version end),
    pve_version_full:    (if $pve_version_full == "" then null else $pve_version_full end),
    pbs_version:         (if $pbs_version == "" then null else $pbs_version end),
    roles:               $roles,
    kernel:              $kernel,
    boot_mode:           $boot_mode,
    root_fs:             $root_fs,
    cpu_model:           $cpu_model,
    cpu_arch:            $cpu_arch,
    memory_kb:           $memory_kb
  }'
