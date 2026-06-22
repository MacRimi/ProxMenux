#!/usr/bin/env bash
# ==========================================================
# ProxMenux Debug Snapshot
# ==========================================================
# Author      : MacRimi
# License     : GPL-3.0
# ==========================================================
# Description:
# Emits a single GitHub-pasteable text block describing the
# current host + ProxMenux state, intended for collaborator
# bug reports. The operator runs this after reproducing an
# issue (especially in the host-backup / restore flow) and
# pastes the output verbatim in the discussion thread.
#
# Design rules:
#   • read-only — never modifies anything on the host.
#   • no network round-trip — everything is local.
#   • redacts hostnames, public IPs, MAC addresses and
#     credentials from the captured output before printing.
#   • single self-contained script, no external deps beyond
#     standard Proxmox tooling (jq optional).
#
# Usage:
#   bash /usr/local/share/proxmenux/scripts/utilities/proxmenux_debug.sh
#   # or capture to a file then upload:
#   bash .../proxmenux_debug.sh > /tmp/proxmenux-debug.txt
# ==========================================================
set -u

# ── Redaction helpers ──────────────────────────────────────
_HOSTNAME_REAL="$(hostname 2>/dev/null || echo host)"
_HOSTNAME_TOKEN="<host>"

# Replace the real hostname plus common public/PII patterns
# in any captured output. Keeps the report shareable.
_redact() {
  sed -E \
    -e "s/${_HOSTNAME_REAL}/${_HOSTNAME_TOKEN}/g" \
    -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<ip>/g' \
    -e 's/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/<mac>/g' \
    -e 's/(password|passphrase|secret|token|api[_-]?key)[[:space:]]*[:=][[:space:]]*"?[^"[:space:]]+"?/\1=<redacted>/gi'
}

_header() { echo; echo "── $1 ──"; }
_kv()     { printf '%-22s %s\n' "$1:" "$2"; }
_hash()   {
  [ -f "$1" ] && sha256sum "$1" 2>/dev/null | awk -v p="$1" '{print substr($1,1,16)"…  "p}' \
              || echo "(missing)         $1"
}

# ── Banner ─────────────────────────────────────────────────
echo "============================================================"
echo " ProxMenux Debug Snapshot"
echo " Generated: $(date -Iseconds 2>/dev/null || date)"
echo "============================================================"

# ── ProxMenux + Proxmox + Hardware ─────────────────────────
_header "Versions"
PMX_VERSION="(unknown)"
if [ -f /usr/local/share/proxmenux/monitor-app/web/package.json ]; then
  PMX_VERSION=$(grep -oE '"version":[[:space:]]*"[^"]*"' \
                  /usr/local/share/proxmenux/monitor-app/web/package.json \
                | head -1 | sed -E 's/.*"version":[[:space:]]*"([^"]+)".*/\1/')
fi
PVE_VERSION="(not a Proxmox host)"
command -v pveversion >/dev/null 2>&1 && PVE_VERSION=$(pveversion 2>/dev/null | head -1)
_kv "ProxMenux"  "$PMX_VERSION"
_kv "Proxmox VE" "$PVE_VERSION"
_kv "Kernel"     "$(uname -r 2>/dev/null)"
_kv "Distro"     "$(grep -E '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"')"
_kv "Uptime"     "$(uptime -p 2>/dev/null || uptime)"

_header "Hardware"
_kv "CPU model"    "$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ //')"
_kv "CPU cores"    "$(nproc 2>/dev/null)"
_kv "RAM total"    "$(grep -m1 MemTotal /proc/meminfo 2>/dev/null | awk '{printf "%.1f GB\n", $2/1024/1024}')"
_kv "Boot mode"    "$([ -d /sys/firmware/efi ] && echo UEFI || echo BIOS)"

if command -v lspci >/dev/null 2>&1; then
  _kv "NVIDIA GPU"  "$(lspci -nn 2>/dev/null | grep -iE 'nvidia.*(vga|3d)' | sed -E 's/^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]+ //' | head -1 | cut -c1-90)"
  _kv "AMD GPU"     "$(lspci -nn 2>/dev/null | grep -iE 'amd.*(vga|3d)|advanced micro.*(vga|3d)' | sed -E 's/^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]+ //' | head -1 | cut -c1-90)"
  _kv "Intel iGPU"  "$(lspci -nn 2>/dev/null | grep -iE 'intel.*(vga|3d|display)' | sed -E 's/^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]+ //' | head -1 | cut -c1-90)"
fi

# Show whichever NVIDIA devices live on this host along with the
# driver they're currently bound to — the single most useful piece
# of info for any GPU passthrough / restore bug.
if lspci -d 10de: 2>/dev/null | grep -q .; then
  _header "NVIDIA bind state"
  while IFS= read -r bdf; do
    [ -z "$bdf" ] && continue
    drv=$(basename "$(readlink "/sys/bus/pci/devices/$bdf/driver" 2>/dev/null)" 2>/dev/null || echo "(none)")
    override=$(cat "/sys/bus/pci/devices/$bdf/driver_override" 2>/dev/null || true)
    echo "  $bdf  driver=$drv  override=${override:-(unset)}"
  done < <(lspci -D -d 10de: 2>/dev/null | awk '{print $1}')
  echo
  echo "  nvidia-smi:"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1 | sed 's/^/    /' | head -4
  else
    echo "    nvidia-smi not installed"
  fi
fi

# ── Components ─────────────────────────────────────────────
_header "ProxMenux components_status.json"
CSF=/usr/local/share/proxmenux/components_status.json
if [ -f "$CSF" ] && command -v jq >/dev/null 2>&1; then
  jq -r 'to_entries[] | "  \(.key): status=\(.value.status) version=\(.value.version // "-") patched=\(.value.patched // "-")"' "$CSF"
elif [ -f "$CSF" ]; then
  sed -E 's/[[:space:]]+/ /g' "$CSF" | head -40
else
  echo "  (no components registered)"
fi

# ── Script integrity ───────────────────────────────────────
_header "Script SHA-256 (first 16 chars · for drift detection)"
for f in \
  /usr/local/share/proxmenux/scripts/backup_restore/backup_host.sh \
  /usr/local/share/proxmenux/scripts/backup_restore/lib_host_backup_common.sh \
  /usr/local/share/proxmenux/scripts/backup_restore/run_scheduled_backup.sh \
  /usr/local/share/proxmenux/scripts/backup_restore/apply_pending_restore.sh \
  /usr/local/share/proxmenux/scripts/backup_restore/apply_cluster_postboot.sh \
  /usr/local/share/proxmenux/scripts/backup_restore/restore/monitor_apply.sh \
  /usr/local/share/proxmenux/scripts/backup_restore/restore/compute_rollback_plan.sh \
  /usr/local/share/proxmenux/scripts/gpu_tpu/nvidia_installer.sh \
  /usr/local/share/proxmenux/scripts/gpu_tpu/switch_gpu_mode.sh \
  /usr/local/share/proxmenux/scripts/gpu_tpu/switch_gpu_mode_direct.sh \
  /usr/local/share/proxmenux/scripts/global/utils-install-functions.sh
do
  echo "  $(_hash "$f")"
done

# ── Backup / restore state ────────────────────────────────
_header "Backup jobs"
JOBS_DIR=/var/lib/proxmenux/backup-jobs
if [ -d "$JOBS_DIR" ]; then
  for env_f in "$JOBS_DIR"/*.env; do
    [ -f "$env_f" ] || continue
    name=$(basename "$env_f" .env)
    backend=$(grep -E '^BACKEND=' "$env_f" 2>/dev/null | cut -d= -f2)
    mode=$(grep -E '^PROFILE_MODE=' "$env_f" 2>/dev/null | cut -d= -f2)
    enabled=$(grep -E '^ENABLED=' "$env_f" 2>/dev/null | cut -d= -f2)
    manual=$(grep -E '^MANUAL_RUN=' "$env_f" 2>/dev/null | cut -d= -f2)
    status_f="/var/log/proxmenux/backup-jobs/${name}-last.status"
    result=$(grep -E '^RESULT=' "$status_f" 2>/dev/null | cut -d= -f2)
    echo "  $name  backend=$backend  profile=$mode  enabled=${enabled:-?}  manual=${manual:-0}  last=${result:-(no runs)}"
  done | sort -u
else
  echo "  (no jobs dir)"
fi

_header "Pending restore"
PEND=/var/lib/proxmenux/restore-pending
if [ -d "$PEND" ]; then
  current=$(readlink -f "$PEND/current" 2>/dev/null)
  [ -n "$current" ] && echo "  current → $current"
  echo "  pending dirs:"
  ls -1t "$PEND" 2>/dev/null | grep -vE '^current$|^completed$' | sed 's/^/    /'
  echo "  completed (last 3):"
  ls -1t "$PEND/completed" 2>/dev/null | head -3 | sed 's/^/    /'
  # Surface the latest rollback.json if present — this is the
  # single most useful piece of info for restore bugs (it shows
  # what the rollback plan computed before the operator clicked).
  latest_completed=$(ls -t "$PEND/completed" 2>/dev/null | head -1)
  if [ -n "$latest_completed" ] && [ -f "$PEND/completed/$latest_completed/rollback.json" ]; then
    echo "  latest rollback.json:"
    sed 's/^/    /' "$PEND/completed/$latest_completed/rollback.json"
    echo
    if [ -f "$PEND/completed/$latest_completed/plan.env" ]; then
      echo "  latest plan.env:"
      sed 's/^/    /' "$PEND/completed/$latest_completed/plan.env"
    fi
  fi
else
  echo "  (no pending restore dir)"
fi

# ── VFIO / passthrough artefacts ──────────────────────────
_header "VFIO / passthrough artefacts on host"
for f in \
  /etc/modprobe.d/proxmenux-nvidia-vfio-blacklist.conf \
  /etc/modprobe.d/nvidia-blacklist.conf \
  /etc/modprobe.d/vfio.conf \
  /etc/udev/rules.d/10-proxmenux-vfio-bind.rules \
  /etc/modules-load.d/nvidia-vfio.conf \
  /etc/proxmenux/vfio-bind.bdfs
do
  if [ -e "$f" ]; then
    sz=$(stat -c%s "$f" 2>/dev/null || echo "?")
    echo "  present (${sz} bytes): $f"
  else
    echo "  absent           : $f"
  fi
done

# ── Recent logs (last 30 lines each) ──────────────────────
_header "Latest cluster-postboot log (last 30 lines)"
last_pb=$(ls -t /var/log/proxmenux/proxmenux-cluster-postboot-*.log 2>/dev/null | head -1)
[ -n "$last_pb" ] && tail -30 "$last_pb" | _redact || echo "  (no cluster-postboot logs)"

_header "Latest restore-onboot log (last 30 lines)"
last_ob=$(ls -t /var/log/proxmenux/proxmenux-restore-onboot-*.log 2>/dev/null | head -1)
[ -n "$last_ob" ] && tail -30 "$last_ob" | _redact || echo "  (no restore-onboot logs)"

_header "Latest backup runner log (last 30 lines)"
last_bj=$(ls -t /var/log/proxmenux/backup-jobs/*.log 2>/dev/null | head -1)
[ -n "$last_bj" ] && tail -30 "$last_bj" | _redact || echo "  (no backup-job logs)"

_header "proxmenux-monitor.service (last 20 lines, errors only)"
journalctl -u proxmenux-monitor.service -n 200 --no-pager 2>/dev/null \
  | grep -iE 'error|exception|traceback|failed' \
  | tail -20 | _redact \
  || echo "  (no errors)"

# ── Notifications config + last events ─────────────────────
_header "Notifications status"
NOTIF_DB=/usr/local/share/proxmenux/monitor.db
if [ -f "$NOTIF_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  echo "  channels configured:"
  sqlite3 "$NOTIF_DB" \
    "SELECT '    '||setting_key||' = '||substr(setting_value,1,20)||'…' \
     FROM user_settings \
     WHERE setting_key LIKE 'notifications.%enabled' \
        OR setting_key LIKE 'notifications.%digest%' \
        OR setting_key LIKE 'notifications.quiet_hours%' \
        OR setting_key LIKE '%.digest_last_at';" 2>/dev/null | _redact || echo "    (sqlite query failed)"
  echo "  history (last 5):"
  sqlite3 -separator ' | ' "$NOTIF_DB" \
    "SELECT sent_at, channel, event_type, substr(title,1,40) FROM notification_history ORDER BY sent_at DESC LIMIT 5;" \
    2>/dev/null | sed 's/^/    /' | _redact || echo "    (no history)"
else
  echo "  (no monitor.db or sqlite3 missing)"
fi

# ── Guests (count only — config-level data stays private) ──
_header "Guests on this host (count only)"
qm_count=$(qm list 2>/dev/null | awk 'NR>1' | wc -l)
pct_count=$(pct list 2>/dev/null | awk 'NR>1' | wc -l)
_kv "VMs"  "$qm_count"
_kv "LXCs" "$pct_count"

echo
echo "============================================================"
echo " End of debug snapshot. Paste the above in the GitHub thread."
echo "============================================================"
