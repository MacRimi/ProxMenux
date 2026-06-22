#!/usr/bin/env bash
# ==========================================================
# ProxMenux RESTORE Debug Snapshot
# ==========================================================
# Author      : MacRimi
# License     : GPL-3.0
# ==========================================================
# Description:
# Single GitHub-pasteable block focused on RESTORE bug
# triage only. Each section corresponds to a class of
# restore failure we need to diagnose. Nothing else is
# included — no notifications data, no global guest counts,
# no system telemetry that doesn't directly explain a
# failed restore.
#
# Sections (and why each one is here):
#   1. Versions               — reproducibility anchor.
#   2. GPU bind state         — passthrough / VFIO bugs.
#   3. Components status      — what ProxMenux thinks is installed.
#   4. Latest restore plan    — rollback.json + plan.env + apply-list.
#   5. Pre-restore snapshot   — what the restore overwrote.
#   6. VFIO config files      — current state of every file the
#                                switch_gpu / restore flows touch
#                                (presence + content).
#   7. Boot args              — /etc/kernel/cmdline vs /proc/cmdline,
#                                proxmox-boot-tool sync state.
#   8. dmesg boot binding     — order vfio-pci ↔ nvidia loaded.
#   9. Restore service        — systemd unit state + on-boot log.
#  10. Cluster post-boot log  — initramfs regen + component reinstall.
#  11. Guests holding the GPU — VMs whose hostpci could keep the GPU
#                                reserved for vfio-pci.
#  12. Recent monitor errors  — fail-fast clues from the service log.
#
# Usage:
#   bash /usr/local/share/proxmenux/scripts/utilities/proxmenux_debug.sh > /tmp/debug.txt
#   cat /tmp/debug.txt   # copy-paste the whole block in the GitHub thread
#
# Output is redacted: hostnames, IPv4 addresses, MAC addresses
# and the obvious password=, passphrase=, token= patterns are
# replaced before printing.
# ==========================================================
set -u

# ── Redaction helpers ──────────────────────────────────────
_HOSTNAME_REAL="$(hostname 2>/dev/null || echo host)"
_redact() {
  sed -E \
    -e "s/${_HOSTNAME_REAL}/<host>/g" \
    -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<ip>/g' \
    -e 's/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/<mac>/g' \
    -e 's/(password|passphrase|secret|token|api[_-]?key)[[:space:]]*[:=][[:space:]]*"?[^"[:space:]]+"?/\1=<redacted>/gi'
}
_header() { echo; echo "── $1 ──"; }
_kv()     { printf '%-22s %s\n' "$1:" "$2"; }
# Dump a config file inline only when it's small (≤2KB) and non-empty.
# Larger or absent files get a single status line so the section
# doesn't balloon with content we won't read anyway.
_dump_if_small() {
  local f="$1"
  if [ ! -e "$f" ]; then
    echo "  absent           : $f"
    return
  fi
  local sz
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  echo "  present (${sz} bytes): $f"
  if [ -s "$f" ] && [ "$sz" -lt 2048 ] 2>/dev/null; then
    sed 's/^/      | /' "$f" | _redact
  fi
}

echo "============================================================"
echo " ProxMenux RESTORE Debug Snapshot"
echo " Generated: $(date -Iseconds 2>/dev/null || date)"
echo "============================================================"

# ── 1. Versions ────────────────────────────────────────────
_header "1. Versions"
PMX_VERSION="(unknown)"
if [ -f /usr/local/share/proxmenux/monitor-app/web/package.json ]; then
  PMX_VERSION=$(grep -oE '"version":[[:space:]]*"[^"]*"' \
                  /usr/local/share/proxmenux/monitor-app/web/package.json \
                | head -1 | sed -E 's/.*"version":[[:space:]]*"([^"]+)".*/\1/')
fi
_kv "ProxMenux"  "$PMX_VERSION"
_kv "Proxmox VE" "$(command -v pveversion >/dev/null 2>&1 && pveversion 2>/dev/null | head -1)"
_kv "Kernel"     "$(uname -r 2>/dev/null)"
_kv "Boot mode"  "$([ -d /sys/firmware/efi ] && echo UEFI || echo BIOS)"

# ── 2. GPU bind state ─────────────────────────────────────
# Most restore bugs we've hit so far revolved around the GPU
# staying bound to vfio-pci when it should have returned to the
# nvidia driver (or vice-versa). Showing the driver, override and
# IOMMU group for every PCI display device tells us at a glance
# which side of that fence the host landed on.
_header "2. GPU PCI bind state"
if command -v lspci >/dev/null 2>&1; then
  for bdf in $(lspci -D 2>/dev/null | grep -iE 'VGA compatible controller|3D controller|Display controller' | awk '{print $1}'); do
    name=$(lspci -nn -s "$bdf" 2>/dev/null \
           | sed -E 's/^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]+ //' \
           | sed -E 's/(VGA compatible controller|3D controller|Display controller) \[[0-9a-f]+\]:[[:space:]]*//I' \
           | cut -c1-80)
    drv=$(basename "$(readlink "/sys/bus/pci/devices/$bdf/driver" 2>/dev/null)" 2>/dev/null || echo "(none)")
    override=$(cat "/sys/bus/pci/devices/$bdf/driver_override" 2>/dev/null || true)
    iommu=$(basename "$(readlink "/sys/bus/pci/devices/$bdf/iommu_group" 2>/dev/null)" 2>/dev/null || echo "-")
    echo "  $bdf  driver=$drv  override=${override:-(unset)}  iommu_group=$iommu"
    echo "         $name"
  done
fi
# nvidia-smi gets its own short summary — confirms the driver
# can actually talk to the device, not just that it's bound.
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "  nvidia-smi:"
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1 | sed 's/^/    /' | head -4
fi

# ── 3. ProxMenux components ───────────────────────────────
_header "3. ProxMenux components_status.json"
CSF=/usr/local/share/proxmenux/components_status.json
if [ -f "$CSF" ] && command -v jq >/dev/null 2>&1; then
  jq -r 'to_entries[] | "  \(.key): status=\(.value.status) version=\(.value.version // "-") patched=\(.value.patched // "-")"' "$CSF"
elif [ -f "$CSF" ]; then
  sed 's/^/  /' "$CSF" | head -40
else
  echo "  (no components registered)"
fi

# ── 4. Latest restore plan ────────────────────────────────
# The rollback.json + plan.env + apply-on-boot.list of the
# most-recent restore tell us exactly what the operator asked
# for and what the system tried to do. Without these we can't
# tell "rollback flag never propagated" from "rollback flag
# propagated but executor skipped guests".
_header "4. Latest restore plan"
PEND=/var/lib/proxmenux/restore-pending
if [ -d "$PEND" ]; then
  latest=$(ls -t "$PEND/completed" 2>/dev/null | head -1)
  if [ -n "$latest" ]; then
    base="$PEND/completed/$latest"
    echo "  pending dir: $base"
    if [ -f "$base/plan.env" ]; then
      echo "  plan.env:"
      sed 's/^/    /' "$base/plan.env"
    fi
    if [ -f "$base/rollback.json" ]; then
      echo "  rollback.json:"
      sed 's/^/    /' "$base/rollback.json"
    fi
    if [ -f "$base/apply-on-boot.list" ]; then
      count=$(wc -l < "$base/apply-on-boot.list" 2>/dev/null || echo 0)
      # Drop the misleading "first 30" tag when the file already fits.
      if [ "$count" -le 30 ]; then
        echo "  apply-on-boot.list (${count} paths):"
      else
        echo "  apply-on-boot.list (${count} paths; first 30):"
      fi
      head -30 "$base/apply-on-boot.list" | sed 's/^/    /'
    fi
  else
    echo "  (no completed restores yet)"
  fi
else
  echo "  (no pending-restore dir)"
fi

# ── 5. Pre-restore preservation ───────────────────────────
# `apply_pending_restore.sh` snapshots every file it's about to
# overwrite into /var/lib/proxmenux/pre-restore/<id>-onboot/. The
# list (paths only — we don't dump contents) tells us what the
# restore touched and lets us spot files that were ON the host
# before but NOT in the backup (additive-restore orphans).
_header "5. Pre-restore preservation (paths overwritten by the restore)"
PRE=/var/lib/proxmenux/pre-restore
if [ -d "$PRE" ]; then
  latest_pre=$(ls -t "$PRE" 2>/dev/null | grep -E -- '-onboot$' | head -1)
  if [ -n "$latest_pre" ]; then
    echo "  pre-restore dir: $PRE/$latest_pre"
    find "$PRE/$latest_pre" -type f 2>/dev/null \
      | sed "s|^$PRE/$latest_pre||" \
      | sort | sed 's/^/    /'
  else
    echo "  (no -onboot snapshot present — apply_pending_restore never ran)"
  fi
else
  echo "  (no pre-restore dir)"
fi

# ── 6. VFIO / passthrough config files ────────────────────
# Every file the host-mode ↔ vfio-mode switch flow touches. We
# need both PRESENCE and CONTENT here, because "the file exists
# but is empty" and "the file has the wrong vendor IDs" are two
# different bug classes (we've hit both).
_header "6. VFIO / passthrough config files (current state)"
for f in \
  /etc/proxmenux/vfio-bind.bdfs \
  /etc/modules-load.d/nvidia-vfio.conf \
  /etc/modules-load.d/nvidia-vfio.conf.proxmenux-disabled-vfio \
  /etc/udev/rules.d/10-proxmenux-vfio-bind.rules \
  /etc/udev/rules.d/70-nvidia.rules \
  /etc/udev/rules.d/70-nvidia.rules.proxmenux-disabled \
  /etc/modprobe.d/proxmenux-nvidia-vfio-blacklist.conf \
  /etc/modprobe.d/nvidia-blacklist.conf \
  /etc/modprobe.d/vfio.conf
do
  _dump_if_small "$f"
done

# ── 7. Kernel boot args ───────────────────────────────────
# /etc/kernel/cmdline is what the operator (or our scripts)
# *configured*. /proc/cmdline is what the running kernel actually
# booted with. They diverge whenever someone edits cmdline and
# forgets proxmox-boot-tool refresh — and that drift breaks every
# downstream passthrough/intel_iommu assumption.
_header "7. Kernel boot args"
echo "  /etc/kernel/cmdline (configured):"
[ -f /etc/kernel/cmdline ] && sed 's/^/    /' /etc/kernel/cmdline | _redact || echo "    (not present — non-systemd-boot host)"
echo "  /proc/cmdline (running):"
sed 's/^/    /' /proc/cmdline 2>/dev/null | _redact
# /etc/default/grub is the OTHER place kernel args can live. On
# systemd-boot hosts `proxmox-boot-tool refresh` reads cmdline +
# GRUB_CMDLINE_LINUX_DEFAULT and concatenates them — so a drift
# here is what causes "intel_iommu=on disappears at the next
# proxmox-boot-tool refresh after restore" bugs.
if [ -f /etc/default/grub ]; then
  echo "  /etc/default/grub  GRUB_CMDLINE_LINUX*:"
  grep -E '^GRUB_CMDLINE_LINUX(_DEFAULT)?=' /etc/default/grub 2>/dev/null \
    | sed 's/^/    /' | _redact || echo "    (no GRUB_CMDLINE_LINUX entries)"
fi
if command -v proxmox-boot-tool >/dev/null 2>&1; then
  echo "  proxmox-boot-tool status:"
  proxmox-boot-tool status 2>&1 | grep -vE '^(System|Re-executing)' | sed 's/^/    /' | head -10
fi

# ── 8. dmesg — vfio + nvidia + GPU PCI bus ────────────────
# The early-boot trace. Tells us whether vfio-pci or nvidia
# claimed the PCI BDF FIRST. If we see `vfio-pci 0000:01:00.0`
# before `nvidia 0000:01:00.0`, that's the smoking gun for a
# restore that didn't clear the vfio bindings before reboot.
_header "8. dmesg — vfio / nvidia / GPU bus binding sequence"
dmesg 2>/dev/null | grep -iE 'vfio|nvidia|VFIO' | head -25 | _redact \
  || echo "  (no matches in dmesg)"

# ── 9. Restore service status + on-boot log ───────────────
# systemd's own view of the on-boot apply (success/timeout/exit)
# plus the script's log file. The two together cover both
# "the script failed silently" and "the script ran but its log
# was truncated by a hung apply".
_header "9. proxmenux-restore-onboot.service — current boot"
journalctl -u proxmenux-restore-onboot.service -b 0 -n 20 --no-pager 2>/dev/null \
  | _redact || echo "  (no journal entries)"
echo
last_ob=$(ls -t /var/log/proxmenux/proxmenux-restore-onboot-*.log 2>/dev/null | head -1)
if [ -n "$last_ob" ]; then
  echo "  log file: $last_ob"
  tail -30 "$last_ob" | sed 's/^/    /' | _redact
else
  echo "  (no restore-onboot log files)"
fi

# ── 10. Cluster post-boot log ─────────────────────────────
# Where update-initramfs / update-grub / component auto-reinstall
# actually run. Surface the whole tail so we see whether the
# postboot finished or stopped partway through.
_header "10. apply_cluster_postboot — last run (full log, redacted)"
last_pb=$(ls -t /var/log/proxmenux/proxmenux-cluster-postboot-*.log 2>/dev/null | head -1)
if [ -n "$last_pb" ]; then
  echo "  log file: $last_pb"
  # Dump the WHOLE post-boot log when small enough — the operator
  # almost always wants to see the header (`=== ProxMenux cluster
  # post-boot apply at … ===`) AND the tail together. 50-line tail
  # was eating the start of the log on every restore we've inspected.
  sz=$(stat -c%s "$last_pb" 2>/dev/null || echo 0)
  if [ "$sz" -lt 8192 ]; then
    sed 's/^/    /' "$last_pb" | _redact
  else
    echo "    (log > 8 KB — showing last 80 lines)"
    tail -80 "$last_pb" | sed 's/^/    /' | _redact
  fi
else
  echo "  (no cluster-postboot log files)"
fi

# ── 11. Guests holding the GPU ────────────────────────────
# If a VM with `hostpci` still exists after the restore, Proxmox
# will auto-rebind the matching PCI device to vfio-pci at the
# next boot — which makes the GPU look "stuck" in passthrough
# even though every config file looks clean. We only list IDs +
# BDFs, NOT full configs, to keep secrets out of the report.
_header "11. Guests with hostpci entries (would re-reserve the GPU)"
hits=0
if command -v qm >/dev/null 2>&1; then
  for vmid in $(qm list 2>/dev/null | awk 'NR>1 {print $1}'); do
    out=$(qm config "$vmid" 2>/dev/null | grep -iE '^hostpci[0-9]+:' || true)
    if [ -n "$out" ]; then
      echo "  VM $vmid:"
      echo "$out" | sed 's/^/    /'
      hits=$((hits + 1))
    fi
  done
fi
if command -v pct >/dev/null 2>&1; then
  for ctid in $(pct list 2>/dev/null | awk 'NR>1 {print $1}'); do
    out=$(pct config "$ctid" 2>/dev/null | grep -iE 'mp[0-9]+:.*nvidia|dev[0-9]+:|lxc.cgroup2.devices' || true)
    if [ -n "$out" ]; then
      echo "  CT $ctid:"
      echo "$out" | sed 's/^/    /'
      hits=$((hits + 1))
    fi
  done
fi
[ "$hits" = "0" ] && echo "  (no guests hold passthrough entries)"

# ── 12. proxmenux-monitor errors (current boot) ───────────
# Any Python traceback or "Error/Exception" line that ended up
# in the service log this boot. Filtered so we don't drown the
# report in the normal startup noise.
_header "12. proxmenux-monitor.service — errors this boot"
err=$(journalctl -u proxmenux-monitor.service -b 0 --no-pager 2>/dev/null \
  | grep -iE 'error|exception|traceback|failed' | tail -15)
if [ -n "$err" ]; then
  echo "$err" | sed 's/^/  /' | _redact
else
  echo "  (no errors logged this boot)"
fi

echo
echo "============================================================"
echo " End of restore debug snapshot."
echo " Paste the whole block in the GitHub discussion thread."
echo "============================================================"
