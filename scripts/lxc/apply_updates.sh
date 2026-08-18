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
#   UPDATE_COMMAND    — optional; user-defined bash string. When set
#                       and TARGET is "app" or "both", the script
#                       runs this VIA sh -c inside the CT instead of
#                       /usr/bin/update. This IS the one place we
#                       intentionally use sh -c with a variable
#                       payload — the threat model matches "user
#                       typed it via pct exec themselves"; ProxMenux
#                       does not compose or interpret the command.
#
# Exit codes:
#   0  everything requested completed OK
#   1  CT not found on this node
#   2  CT could not be started
#   3  pre-update backup failed (abort so the user still has a rollback)
#   4  OS update failed OR OS family not supported for automated updates
#   5  TARGET=app requested but no update method (neither UPDATE_COMMAND
#      nor /usr/bin/update) available in the CT
#   6  post-update restart failed
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

STARTED_AT=$(date -Iseconds)
NODE=$(hostname)
echo "=== ProxMenux LXC update — CT $VMID on $NODE ==="
echo "Started:  $STARTED_AT"
echo "Target:   $TARGET"
echo "Backup:   $BACKUP${BACKUP_STORAGE:+ (storage: $BACKUP_STORAGE)}"
echo "Restart:  $RESTART"
echo

# 1) CT must exist on this node.
if ! pct list | awk 'NR>1 {print $1}' | grep -qE "^${VMID}$"; then
  echo "ERROR: CT $VMID is not on this node." >&2
  exit 1
fi

# 2) CT must be running for pct exec. Auto-start stopped CTs.
STATE=$(pct status "$VMID" | awk '{print $2}')
if [[ "$STATE" != "running" ]]; then
  echo "CT is $STATE. Starting it before applying updates…"
  if ! pct start "$VMID"; then
    echo "ERROR: failed to start CT $VMID." >&2
    exit 2
  fi
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

# 6) Application update. Precedence:
#    a) /usr/bin/update present (community-scripts convention) →
#       runs the community-scripts helper FROM THE HOST with CTID
#       env var. Their build.func framework requires CTID + host-only
#       `pveversion`, so `pct exec ... /usr/bin/update` inside the CT
#       always fails ("You need to set 'CTID' variable"). We parse
#       the ct/<slug>.sh URL from /usr/bin/update and re-fetch it
#       here with CTID set. PHS_SILENT=1 keeps it non-interactive.
#    b) UPDATE_COMMAND env var set → run it verbatim via `sh -c`
#       inside the CT. The one intentional shell-exec-with-variable
#       in ProxMenux — see header comment for threat-model rationale.
#    Both can run in the same invocation: the helper first (if
#    present), then the per-app custom commands.
if [[ "$TARGET" == "app" || "$TARGET" == "both" ]]; then
  APP_METHOD_RAN=0
  UPDATE_URL=""
  RESOLVED_SLUG=""
  if pct exec "$VMID" -- test -f /usr/bin/update 2>/dev/null; then
    UPDATE_URL=$(pct exec "$VMID" -- cat /usr/bin/update 2>/dev/null | grep -oE 'https?://[^"'"'"' ]+ct/[a-zA-Z0-9._-]+\.sh' | head -1)
    RESOLVED_SLUG=$(echo "$UPDATE_URL" | sed -nE 's|.*/ct/([a-zA-Z0-9._-]+)\.sh$|\1|p')
  fi
  # HELPER_SLUG env is a passthrough from the backend when the CT no
  # longer carries /usr/bin/update (older installs where the file was
  # removed) but the community-scripts slug is known via hostname
  # match against the helpers_cache. Lets us run the same host-side
  # updater without requiring the on-CT marker file.
  if [[ -z "$RESOLVED_SLUG" && -n "$HELPER_SLUG" ]]; then
    if [[ "$HELPER_SLUG" =~ ^[a-zA-Z0-9._-]+$ ]]; then
      RESOLVED_SLUG="$HELPER_SLUG"
      UPDATE_URL="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/${RESOLVED_SLUG}.sh"
    else
      echo "WARN: HELPER_SLUG contains invalid characters — ignored." >&2
    fi
  fi
  if [[ -n "$UPDATE_URL" && -n "$RESOLVED_SLUG" ]]; then
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
      if ! pct exec "$VMID" -- bash -c "PHS_SILENT=1 bash -c \"\$($IN_CT_FETCH)\""; then
        echo "ERROR: community-scripts helper returned non-zero." >&2
        APP_FAILED=1
      fi
    fi
    APP_METHOD_RAN=1
    echo
  fi
  if [[ -n "$UPDATE_COMMAND" ]]; then
    echo "--- Running user-defined update command ---"
    echo "\$ $UPDATE_COMMAND"
    if ! pct exec "$VMID" -- sh -c "$UPDATE_COMMAND"; then
      echo "ERROR: user-defined update command returned non-zero." >&2
      APP_FAILED=1
    fi
    APP_METHOD_RAN=1
    echo
  fi
  if [[ "$APP_METHOD_RAN" -eq 0 ]]; then
    if [[ "$TARGET" == "app" ]]; then
      echo "ERROR: TARGET=app but no update method (UPDATE_COMMAND unset AND /usr/bin/update missing) in CT $VMID." >&2
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
  echo "=== Update FAILED — CT left running for inspection. ==="
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
