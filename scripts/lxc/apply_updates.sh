#!/bin/bash
# ==========================================================
# ProxMenux — Apply Updates to an LXC container
# ==========================================================
# Runs inside the Monitor's terminal streamer (PTY over WS).
# Input via env vars (all set by the frontend before launch):
#
#   VMID              — target container id (required)
#   TARGET            — "os" | "app" | "both" (required)
#   BACKUP            — "1" to snapshot with vzdump first, "0" to skip
#   BACKUP_STORAGE    — PVE storage name for vzdump (required when BACKUP=1)
#   RESTART           — "1" to `pct reboot` after update, "0" to skip
#   RUN_HELPER        — "1" to run the verified community-scripts
#                       updater declared by /usr/bin/update, "0"
#                       to leave it alone. Never inferred from names.
#   UPDATE_COMMAND    — optional user-defined bash string. When set
#                       and TARGET is "app" or "both", the script
#                       runs it VIA sh -c inside the CT. A custom
#                       command always replaces RUN_HELPER for safety.
#                       This IS the one place we
#                       intentionally use sh -c with a variable
#                       payload — the threat model matches "user
#                       typed it via pct exec themselves"; ProxMenux
#                       preserves arbitrary commands. Historical downloaded
#                       shell launchers get an explicit download failure guard.
#   ALLOW_HELPER_WITH_CUSTOM — "1" only for an explicit multi-app plan
#                       where RUN_HELPER belongs to one registered app and
#                       UPDATE_COMMAND contains other registered apps. The
#                       default "0" preserves the custom-replaces-helper rule
#                       for single-app and legacy callers.
#   DOCKER_STANDALONE_TARGETS — optional comma-separated Docker container
#                       names. Each is recreated transactionally by the
#                       protected host-side Docker recreation helper.
#   UPDATE_DOCKER_ENGINE — "1" to update only the installed Docker Engine
#                       package stack, without upgrading unrelated OS packages.
#
# Exit codes:
#   0  everything requested completed OK
#   1  CT not found on this node
#   2  CT could not be started
#   3  pre-update backup failed (abort so the user still has a rollback)
#   4  OS/app update failed OR OS family not supported for automated updates
#   5  TARGET=app requested but no update method (neither UPDATE_COMMAND
#      nor explicitly-enabled verified helper) available in the CT
#   6  post-update restart failed
#   7  another ProxMenux update is already running for this CT
#
# The frontend surfaces exit code + duration in a follow-up POST to
# /api/lxc-updates/<vmid>/applied so the notification event fires with
# the correct result field.
# ==========================================================

set -o pipefail

: "${VMID:?VMID is required}"
: "${TARGET:?TARGET is required}"
BACKUP="${BACKUP:-0}"
RESTART="${RESTART:-0}"
RUN_HELPER="${RUN_HELPER:-0}"
UPDATE_COMMAND="${UPDATE_COMMAND:-}"
ALLOW_HELPER_WITH_CUSTOM="${ALLOW_HELPER_WITH_CUSTOM:-0}"
DOCKER_STANDALONE_TARGETS="${DOCKER_STANDALONE_TARGETS:-}"
UPDATE_DOCKER_ENGINE="${UPDATE_DOCKER_ENGINE:-0}"

if [[ ! "$VMID" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: VMID must be a positive integer." >&2
  exit 1
fi
if [[ "$TARGET" != "os" && "$TARGET" != "app" && "$TARGET" != "both" ]]; then
  echo "ERROR: TARGET must be os, app, or both." >&2
  exit 4
fi
if [[ "$RUN_HELPER" != "0" && "$RUN_HELPER" != "1" ]]; then
  echo "ERROR: RUN_HELPER must be 0 or 1." >&2
  exit 5
fi
if [[ "$ALLOW_HELPER_WITH_CUSTOM" != "0" && "$ALLOW_HELPER_WITH_CUSTOM" != "1" ]]; then
  echo "ERROR: ALLOW_HELPER_WITH_CUSTOM must be 0 or 1." >&2
  exit 5
fi
if [[ "$UPDATE_DOCKER_ENGINE" != "0" && "$UPDATE_DOCKER_ENGINE" != "1" ]]; then
  echo "ERROR: UPDATE_DOCKER_ENGINE must be 0 or 1." >&2
  exit 5
fi

# Resolve only static, constrained metadata from a Proxmox VE
# Helper-Scripts update entrypoint. Historical wrappers contain a literal
# ct/<slug>.sh URL; current wrappers are regenerated after updates and
# declare SCRIPT_SLUG / UPDATE_SCRIPT_NAME before composing the URL.
# Never source or evaluate the wrapper: its contents belong to the CT.
extract_helper_slug_from_wrapper() {
  local wrapper="$1"
  local key slug

  for key in SCRIPT_SLUG UPDATE_SCRIPT_NAME; do
    slug=$(printf '%s\n' "$wrapper" | sed -nE \
      "s/^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=[[:space:]]*[\"']?([a-z0-9][a-z0-9._-]*)[\"']?[[:space:]]*(#.*)?$/\\2/p" \
      | head -n 1)
    if [[ "$slug" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
      printf '%s\n' "$slug"
      return 0
    fi
  done

  slug=$(printf '%s\n' "$wrapper" \
    | grep -oE 'https?://[^"'"'"' ]+ct/[a-z0-9][a-z0-9._-]*\.sh' \
    | head -n 1 \
    | sed -nE 's|.*/ct/([a-z0-9][a-z0-9._-]*)\.sh$|\1|p')
  if [[ "$slug" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
    printf '%s\n' "$slug"
    return 0
  fi
  return 1
}

# One update per CT at a time, regardless of whether it came from the
# UI or the scheduler. The descriptor remains open for this process.
LOCK_DIR="${PROXMENUX_LOCK_DIR:-/run/lock}"
exec 9>"${LOCK_DIR}/proxmenux-lxc-update-${VMID}.lock"
if ! flock -n 9; then
  echo "ERROR: another ProxMenux update is already running for CT $VMID." >&2
  exit 7
fi

STARTED_AT=$(date -Iseconds)
NODE=$(hostname)
echo "=== ProxMenux LXC update — CT $VMID on $NODE ==="
echo "Started:  $STARTED_AT"
echo "Target:   $TARGET"
echo "Backup:   $BACKUP${BACKUP_STORAGE:+ (storage: $BACKUP_STORAGE)}"
echo "Restart:  $RESTART"
echo "Helper:   $RUN_HELPER"
echo

# 1) CT must exist on this node.
if ! pct list | awk 'NR>1 {print $1}' | grep -qE "^${VMID}$"; then
  echo "ERROR: CT $VMID is not on this node." >&2
  exit 1
fi

# 2) CT must be running for pct exec. Auto-start stopped CTs, then
#    restore their original stopped state on every exit path.
STATE=$(pct status "$VMID" | awk '{print $2}')
STARTED_BY_PROXMENUX=0
restore_original_state() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ "$STARTED_BY_PROXMENUX" == "1" ]]; then
    echo
    echo "Restoring original state: stopping CT $VMID…"
    if ! pct shutdown "$VMID" --timeout 60; then
      echo "ERROR: update finished but CT $VMID could not be returned to its original stopped state." >&2
      if [[ "$rc" -eq 0 ]]; then
        rc=6
      fi
    fi
  fi
  exit "$rc"
}
trap restore_original_state EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ "$STATE" != "running" ]]; then
  echo "CT is $STATE. Starting it before applying updates…"
  if ! pct start "$VMID"; then
    echo "ERROR: failed to start CT $VMID." >&2
    exit 2
  fi
  STARTED_BY_PROXMENUX=1
  # give the CT a moment for services to come up
  sleep 3
fi

# 3) Optional pre-update snapshot. Uses vzdump (not `pct snapshot`)
#    because most homelab storages support vzdump snapshots (including
#    directory + PBS) whereas `pct snapshot` requires the underlying
#    storage type to expose it. Abort on backup failure so the user
#    always has a rollback point when they asked for one.
if [[ "$BACKUP" == "1" ]]; then
  : "${BACKUP_STORAGE:?BACKUP_STORAGE is required when BACKUP=1}"
  echo "--- Creating vzdump snapshot on '$BACKUP_STORAGE' ---"
  if ! vzdump "$VMID" --mode snapshot --storage "$BACKUP_STORAGE" --compress zstd --notes-template "pre-update {{guestname}} {{node}}"; then
    echo "ERROR: pre-update backup failed. Aborting so you keep a rollback point." >&2
    exit 3
  fi
  echo
fi

# 4) Detect OS family for the OS-update branch.
OS_FAMILY="unknown"
if OS_LINE=$(pct exec "$VMID" -- sh -c 'grep -E "^ID=" /etc/os-release 2>/dev/null | head -1' 2>/dev/null); then
  OS_FAMILY=$(echo "$OS_LINE" | sed -e 's/^ID=//' -e 's/^"//' -e 's/"$//')
fi
echo "OS family: $OS_FAMILY"
echo

OS_FAILED=0
APP_FAILED=0

# 5) OS package updates.
if [[ "$TARGET" == "os" || "$TARGET" == "both" ]]; then
  echo "--- Applying OS package updates ---"
  case "$OS_FAMILY" in
    debian|ubuntu)
      # `apt-get` (not `apt`) for machine-friendly output; the
      # DEBIAN_FRONTEND avoids interactive dpkg prompts on config
      # conflicts (dpkg keeps the local version by default with
      # --force-confold).
      if ! pct exec "$VMID" -- env DEBIAN_FRONTEND=noninteractive \
            apt-get -y -o Dpkg::Options::="--force-confold" dist-upgrade; then
        echo "ERROR: apt-get dist-upgrade failed inside CT $VMID." >&2
        OS_FAILED=1
      fi
      ;;
    alpine)
      if ! pct exec "$VMID" -- apk upgrade --no-cache; then
        echo "ERROR: apk upgrade failed inside CT $VMID." >&2
        OS_FAILED=1
      fi
      ;;
    *)
      echo "OS family '$OS_FAMILY' isn't supported for automated OS updates." >&2
      OS_FAILED=1
      ;;
  esac
  echo
fi

# 6) Application update. Explicit methods only:
#    a) RUN_HELPER=1 + a valid /usr/bin/update wrapper →
#       parses its static slug (legacy URL or current generated
#       SCRIPT_SLUG format), canonicalises it to the official repository,
#       then runs the current helper
#       inside the CT with PHS_SILENT=1.
#    b) UPDATE_COMMAND set → run it verbatim via `sh -c`
#       inside the CT. The one intentional shell-exec-with-variable
#       in ProxMenux — see header comment for threat-model rationale.
#    UPDATE_COMMAND always wins if a legacy caller also sets RUN_HELPER.
#    A hostname/tag/cache guess is never executable evidence.
if [[ "$TARGET" == "app" || "$TARGET" == "both" ]]; then
  APP_METHOD_RAN=0
  if [[ -n "$UPDATE_COMMAND" && "$RUN_HELPER" == "1" && "$ALLOW_HELPER_WITH_CUSTOM" != "1" ]]; then
    echo "Custom update command configured; skipping Proxmox VE Helper-Scripts updater."
    RUN_HELPER=0
  fi
  if [[ "$UPDATE_DOCKER_ENGINE" == "1" ]]; then
    echo "--- Updating Docker Engine only ---"
    if ! python3 /usr/local/share/proxmenux/monitor-app/usr/bin/update_docker_engine.py \
          --vmid "$VMID"; then
      echo "ERROR: Docker Engine update failed." >&2
      APP_FAILED=1
    fi
    APP_METHOD_RAN=1
    echo
  fi
  if [[ "$RUN_HELPER" == "1" ]]; then
    UPDATE_WRAPPER=""
    UPDATE_URL=""
    RESOLVED_SLUG=""
    if pct exec "$VMID" -- test -f /usr/bin/update 2>/dev/null; then
      UPDATE_WRAPPER=$(pct exec "$VMID" -- cat /usr/bin/update 2>/dev/null)
      RESOLVED_SLUG=$(extract_helper_slug_from_wrapper "$UPDATE_WRAPPER")
    fi
    case "$RESOLVED_SLUG" in
      alpine|archlinux|archlinux-vm|debian|fedora|gentoo|opensuse|ubuntu)
        echo "ERROR: /usr/bin/update references the base-OS helper '$RESOLVED_SLUG', not an application updater." >&2
        APP_FAILED=1
        RESOLVED_SLUG=""
        ;;
    esac
    if [[ -z "$RESOLVED_SLUG" ]]; then
      if [[ "$APP_FAILED" -eq 0 ]]; then
        echo "ERROR: RUN_HELPER=1 but /usr/bin/update contains no valid Proxmox VE Helper-Scripts app slug." >&2
        APP_FAILED=1
      fi
    else
      # Detection is not consent. Recheck the saved per-app choice here too,
      # so a stale browser/plan cannot run a helper after it was deselected.
      if ! python3 - "$VMID" "$RESOLVED_SLUG" <<'PY'
import json
import os
import sys
sys.path.insert(0, '/usr/local/share/proxmenux/monitor-app/usr/bin')
import lxc_apps
targets = json.loads(os.environ.get('REQUESTED_TARGETS_JSON') or '[]')
if not isinstance(targets, list):
    raise SystemExit(1)
raise SystemExit(0 if lxc_apps.helper_update_selected(
    sys.argv[1], sys.argv[2], targets or None,
) else 1)
PY
      then
        echo "ERROR: Helper-Scripts has not been selected for this application. Configure its update method first." >&2
        exit 5
      fi
      # Never execute the arbitrary URL embedded in the CT. The slug is
      # constrained by the parser; fetch the canonical upstream path.
      UPDATE_URL="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/${RESOLVED_SLUG}.sh"
    echo "--- Running community-scripts helper (slug: $RESOLVED_SLUG) ---"
    # Community-scripts' build.func in start() dispatches on
    # `command -v pveversion`: present → install_script (whiptail
    # "Default Install / Advanced / Settings" menu); absent → the
    # PHS_SILENT=1 branch runs update_script silently. Since
    # pveversion only exists on the Proxmox host, we run the script
    # INSIDE the CT so the framework picks the silent update path.
    # The CT must have wget or curl — every modern helper install
    # ships one of them.
    IN_CT_FETCH=""
    if pct exec "$VMID" -- sh -c 'command -v wget >/dev/null 2>&1'; then
      IN_CT_FETCH="wget -qLO - '$UPDATE_URL'"
    elif pct exec "$VMID" -- sh -c 'command -v curl >/dev/null 2>&1'; then
      IN_CT_FETCH="curl -fsSL '$UPDATE_URL'"
    fi
    if [[ -z "$IN_CT_FETCH" ]]; then
      echo "ERROR: CT $VMID has neither wget nor curl — cannot fetch the helper." >&2
      APP_FAILED=1
    else
      # Check the download before invoking bash: bash -c "$(failed wget)"
      # otherwise executes an empty string and falsely returns success.
      if ! pct exec "$VMID" -- bash -c "
_proxmenux_updater=\$($IN_CT_FETCH) || {
  echo 'ERROR: updater download failed; nothing was executed.' >&2
  exit 1
}
[ -n \"\$_proxmenux_updater\" ] || {
  echo 'ERROR: downloaded updater is empty; nothing was executed.' >&2
  exit 1
}
PHS_SILENT=1 bash -c \"\$_proxmenux_updater\""; then
        echo "ERROR: community-scripts helper returned non-zero." >&2
        APP_FAILED=1
      fi
    fi
    APP_METHOD_RAN=1
    echo
    fi
  fi
  if [[ -n "$UPDATE_COMMAND" ]]; then
    echo "--- Running user-defined update command ---"
    echo "\$ $UPDATE_COMMAND"
    # Also covers a legacy command submitted by a browser opened before the
    # upgrade. Bulk/scheduled plans protect each constituent command upstream.
    if ! PREPARED_COMMAND=$(UPDATE_COMMAND="$UPDATE_COMMAND" python3 - protect-update-command <<'PY'
import os
import sys
sys.path.insert(0, '/usr/local/share/proxmenux/monitor-app/usr/bin')
from lxc_apps import protect_download_update_command
sys.stdout.write(protect_download_update_command(os.environ['UPDATE_COMMAND']))
PY
    ); then
      echo "ERROR: could not prepare the update command; nothing was executed." >&2
      APP_FAILED=1
    elif ! pct exec "$VMID" -- sh -c "$PREPARED_COMMAND"; then
      echo "ERROR: user-defined update command returned non-zero." >&2
      APP_FAILED=1
    fi
    APP_METHOD_RAN=1
    echo
  fi
  if [[ -n "$DOCKER_STANDALONE_TARGETS" ]]; then
    IFS=',' read -r -a DOCKER_TARGETS <<< "$DOCKER_STANDALONE_TARGETS"
    for DOCKER_CONTAINER in "${DOCKER_TARGETS[@]}"; do
      if [[ ! "$DOCKER_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
        echo "ERROR: invalid Docker container target '$DOCKER_CONTAINER'." >&2
        APP_FAILED=1
        continue
      fi
      echo "--- Recreating standalone Docker container: $DOCKER_CONTAINER ---"
      if ! python3 /usr/local/share/proxmenux/monitor-app/usr/bin/recreate_docker_container.py \
            --vmid "$VMID" --container "$DOCKER_CONTAINER"; then
        echo "ERROR: protected Docker recreation failed for '$DOCKER_CONTAINER'." >&2
        APP_FAILED=1
      fi
      APP_METHOD_RAN=1
      echo
    done
  fi
  if [[ "$APP_METHOD_RAN" -eq 0 ]]; then
    if [[ "$TARGET" == "app" ]]; then
      echo "ERROR: TARGET=app but no update method was explicitly selected for CT $VMID." >&2
      exit 5
    else
      echo "No app update method available in this CT — skipping app update step."
      echo
    fi
  fi
fi

# 7) If either branch failed, abort here BEFORE the optional reboot so
#    the CT stays in the pre-update state and the user can inspect it.
if (( OS_FAILED || APP_FAILED )); then
  echo "=== Update FAILED. ==="
  exit 4
fi

# 8) Optional post-update reboot. Handy for kernel/library upgrades and
#    OCI-style CTs whose PID 1 is a user entrypoint (a plain `apt
#    upgrade` doesn't restart the app; a CT reboot does).
if [[ "$RESTART" == "1" ]]; then
  echo "--- Rebooting CT $VMID ---"
  if ! pct reboot "$VMID"; then
    echo "ERROR: pct reboot failed." >&2
    exit 6
  fi
fi

FINISHED_AT=$(date -Iseconds)
echo
echo "=== Update complete — CT $VMID ==="
echo "Started:  $STARTED_AT"
echo "Finished: $FINISHED_AT"
exit 0
