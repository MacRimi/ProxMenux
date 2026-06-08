#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest collector — kernel_params
# ==========================================================
# /proc/cmdline (filtered to user-meaningful extras), /etc/modules,
# and /etc/modprobe.d/ files with custom directives. Read-only.
# Schema: scripts/backup_restore/schema/manifest.schema.json
# ==========================================================
set -euo pipefail

# ── cmdline_extra ──
# /proc/cmdline contains the kernel command line the bootloader passed.
# We strip the boring boilerplate (BOOT_IMAGE, initrd, root, ro, rw, quiet,
# splash, boot=zfs, rootflags) so the manifest captures only the user-
# meaningful tweaks (intel_iommu, iommu=pt, hugepages, pcie_acs_override,
# acpi=off, etc.). These are the bits a restore wizard cares about.
cmdline_extra='[]'
if [[ -r /proc/cmdline ]]; then
  raw_cmdline="$(cat /proc/cmdline)"
  for token in $raw_cmdline; do
    case "$token" in
      BOOT_IMAGE=*|initrd=*|root=*|ro|rw|quiet|splash|boot=*|rootflags=*)
        ;;  # boilerplate, drop
      *)
        cmdline_extra="$(jq --argjson acc "$cmdline_extra" --arg t "$token" -n '$acc + [$t]')"
        ;;
    esac
  done
fi

# ── modules_loaded_at_boot ──
# /etc/modules lists modules systemd-modules-load.service inserts on boot.
modules_at_boot='[]'
if [[ -r /etc/modules ]]; then
  while IFS= read -r mod; do
    # Strip comments and inline comments
    mod="${mod%%#*}"
    mod="$(printf '%s' "$mod" | xargs)"
    [[ -z "$mod" ]] && continue
    modules_at_boot="$(jq --argjson acc "$modules_at_boot" --arg m "$mod" -n '$acc + [$m]')"
  done < /etc/modules
fi

# ── modprobe_d_files ──
# /etc/modprobe.d/*.conf files. We emit the path of every file that
# contains at least one `options`, `blacklist`, `install`, `alias`, or
# `softdep` directive — i.e. anything that has actual effect. Files that
# are empty or pure comments aren't worth tracking.
modprobe_files='[]'
if [[ -d /etc/modprobe.d ]]; then
  for f in /etc/modprobe.d/*.conf; do
    [[ -r "$f" ]] || continue
    if grep -qE '^[[:space:]]*(options|blacklist|install|alias|softdep)[[:space:]]' "$f" 2>/dev/null; then
      modprobe_files="$(jq --argjson acc "$modprobe_files" --arg p "$f" -n '$acc + [$p]')"
    fi
  done
fi

jq -n \
  --argjson cmdline_extra        "$cmdline_extra" \
  --argjson modules_loaded       "$modules_at_boot" \
  --argjson modprobe_files       "$modprobe_files" \
  '{
    cmdline_extra:           $cmdline_extra,
    modules_loaded_at_boot:  $modules_loaded,
    modprobe_d_files:        $modprobe_files
  }'
