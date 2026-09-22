#!/usr/bin/env bash
set -Eeuo pipefail

TEMPLATE_FILE=${1:?template JSON required}
DEPLOYMENT_FILE=${2:?deployment JSON required}
DRY_RUN=${3:-0}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/oci_ui.sh"
PUBLISHER_SOURCE="${SCRIPT_DIR}/rclone_mount_publish.py"

die() {
  stop_spinner
  msg_error "$*"
  if [[ -n ${OCI_LOG:-} && -s ${OCI_LOG:-} ]]; then
    oci_log_tail 12 >&2
    printf '    %s %s\n' "$(translate "Full log:")" "$OCI_LOG" >&2
  fi
  exit 1
}

UNEXPECTED_FAILURE=0
report_unexpected_failure() {
  local status=${1:-$?}
  stop_spinner
  if (( status != 0 && UNEXPECTED_FAILURE == 1 )); then
    msg_error "$(translate "The configuration stopped because of an unexpected error")"
    if [[ -n ${OCI_LOG:-} && -s ${OCI_LOG:-} ]]; then
      oci_log_tail 12 >&2
      printf '    %s %s\n' "$(translate "Full log:")" "$OCI_LOG" >&2
    fi
  fi
  return 0
}
trap 'report_unexpected_failure' EXIT
trap 'UNEXPECTED_FAILURE=1; oci_log "Command failed at line $LINENO (${FUNCNAME[0]:-main})"' ERR

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$(translate "Missing required command:") $1"
}

jqr() {
  jq -er "$1" "$DEPLOYMENT_FILE"
}

safe_absolute_path() {
  local path=$1
  [[ $path == /* && $path != / && $path != *[[:space:],]* && $path != *..* ]]
}

[[ $EUID -eq 0 ]] || die "$(translate "The configuration must run as root on Proxmox VE")"
oci_log_init "rclone-mount"
for command in pct jq python3 mountpoint findmnt systemctl systemd-run lxc-info base64; do
  require_command "$command"
done
[[ -r $PUBLISHER_SOURCE ]] || die "$(translate "The FUSE publication helper was not found")"

VMID=$(jqr '.vmid')
REMOTE_NAME=$(jqr '.remote_name')
REMOTE_PATH=$(jq -r '.remote_path // ""' "$DEPLOYMENT_FILE")
MOUNT_NAME=$(jqr '.mount_name')
VFS_CACHE_MODE=$(jqr '.vfs_cache_mode')
SHARED_PARENT=$(jqr '.shared_mount_root_parent')
SHARED_RW=$(jqr '.shared_mount_root')
SHARED_RO=$(jqr '.shared_mount_read_only_root')
[[ $VMID =~ ^[0-9]+$ ]] || die "$(translate "Invalid VMID")"
[[ $REMOTE_NAME =~ ^[A-Za-z0-9._-]{1,64}$ ]] || die "$(translate "Invalid remote name")"
[[ $MOUNT_NAME =~ ^[A-Za-z0-9._-]{1,64}$ ]] || die "$(translate "Invalid mount name")"
[[ $REMOTE_PATH != /* && $REMOTE_PATH != *$'\n'* && $REMOTE_PATH != *$'\r'* ]] \
  || die "$(translate "Invalid remote path")"
case "$VFS_CACHE_MODE" in off|minimal|writes|full) ;; *) die "$(translate "Invalid VFS cache mode")" ;; esac
for path in "$SHARED_PARENT" "$SHARED_RW" "$SHARED_RO"; do
  safe_absolute_path "$path" || die "$(translate "Invalid host path:") $path"
done
[[ $SHARED_RW == "$SHARED_PARENT"/* && $SHARED_RO == "$SHARED_PARENT"/* ]] \
  || die "$(translate "The published views must be inside the common root")"

pct config "$VMID" >/dev/null 2>&1 || die "$(translate "The container does not exist:") CT $VMID"
CONFIG=$(cat "/etc/pve/lxc/${VMID}.conf")
grep -q '^unprivileged: 0$' <<<"$CONFIG" || die "$(translate "Rclone mount requires a privileged container")"
grep -Eq '^features: .*(^|,)fuse=1(,|$)' <<<"$CONFIG" \
  || grep -q 'fuse=1' <<<"$CONFIG" \
  || die "$(translate "The container does not have the fuse=1 feature enabled")"

msg_info "$(translate "Checking the remote...")"
STATUS=$(pct status "$VMID" | awk '{print $2}')
if [[ $STATUS != running ]]; then
  oci_log "Starting CT $VMID temporarily to check the remote"
  oci_quiet pct start "$VMID"
  for _ in $(seq 1 30); do
    pct exec "$VMID" -- /usr/local/bin/rclone version >/dev/null 2>&1 && break
    sleep 1
  done
fi
REMOTES=$(pct exec "$VMID" -- /usr/local/bin/rclone listremotes \
  --config /config/rclone/rclone.conf 2>/dev/null || true)
grep -Fxq "${REMOTE_NAME}:" <<<"$REMOTES" \
  || die "$(translate "The remote does not exist; create and authorize it first in the WebUI:") ${REMOTE_NAME}:"
msg_ok "$(translate "Remote verified:") ${REMOTE_NAME}:"

if [[ $DRY_RUN == 1 ]]; then
  msg_ok "$(translate "Dry run completed; the container and the mounts were not changed.")"
  exit 0
fi

RC_USER=$(sed -n 's/^lxc\.environment\.runtime: RCLONE_RC_USER=//p' "/etc/pve/lxc/${VMID}.conf" | tail -n1)
RC_PASS=$(sed -n 's/^lxc\.environment\.runtime: RCLONE_RC_PASS=//p' "/etc/pve/lxc/${VMID}.conf" | tail -n1)
if [[ -z $RC_USER || -z $RC_PASS ]]; then
  RC_USER=$(pct exec "$VMID" -- sh -c "sed -n 's/^username=//p' /config/rclone/webui.credentials" 2>/dev/null || true)
  RC_PASS=$(pct exec "$VMID" -- sh -c "sed -n 's/^password=//p' /config/rclone/webui.credentials" 2>/dev/null || true)
fi
[[ -n $RC_USER && -n $RC_PASS ]] || die "$(translate "The persistent WebUI credentials were not found")"

msg_info "$(translate "Applying the mount mode...")"
oci_quiet pct exec "$VMID" -- mkdir -p "/data/mounts/${MOUNT_NAME}"
oci_quiet pct stop "$VMID"

BACKUP_CONF=$(mktemp "/tmp/proxmenux-rclone-${VMID}.conf.XXXXXX")
cp "/etc/pve/lxc/${VMID}.conf" "$BACKUP_CONF"
ROLLBACK=1
rollback() {
  local status=$?
  report_unexpected_failure "$status"
  if (( status != 0 && ROLLBACK == 1 )); then
    msg_info "$(translate "Restoring the previous Rclone configuration...")"
    systemctl stop "proxmenux-rclone-publish-${VMID}.service" >/dev/null 2>&1 || true
    mountpoint -q "$SHARED_RO/$MOUNT_NAME" && umount -l "$SHARED_RO/$MOUNT_NAME" >>"$OCI_LOG" 2>&1 || true
    mountpoint -q "$SHARED_RW/$MOUNT_NAME" && umount -l "$SHARED_RW/$MOUNT_NAME" >>"$OCI_LOG" 2>&1 || true
    cp "$BACKUP_CONF" "/etc/pve/lxc/${VMID}.conf" || true
    pct start "$VMID" >/dev/null 2>&1 || true
    msg_ok "$(translate "Previous Rclone configuration restored")"
  fi
  rm -f "$BACKUP_CONF"
  exit "$status"
}
trap rollback EXIT

install -d -m 0755 /usr/local/libexec /var/lib/vz/snippets \
  "$SHARED_PARENT" "$SHARED_RW/$MOUNT_NAME" "$SHARED_RO/$MOUNT_NAME"
install -m 0755 "$PUBLISHER_SOURCE" /usr/local/libexec/proxmenux-oci-mount-publish

WAITER=$(jq -er '.proxmox.laboratory_contract.generated_assets["mount-publication-waiter"].content' "$TEMPLATE_FILE")
printf '%s\n' "$WAITER" >/usr/local/libexec/proxmenux-oci-mount-wait
chmod 0755 /usr/local/libexec/proxmenux-oci-mount-wait

HOOK=$(jq -er '.proxmox.laboratory_contract.generated_assets["proxmox-hookscript"].content_template' "$TEMPLATE_FILE")
HOOK=${HOOK//\{\{mount_name\}\}/$MOUNT_NAME}
HOOK=${HOOK//\{\{shared_mount_root\}\}/$SHARED_RW}
HOOK=${HOOK//\{\{shared_mount_read_only_root\}\}/$SHARED_RO}
HOOK=${HOOK//\{\{shared_mount_root_parent\}\}/$SHARED_PARENT}
HOOK_PATH="/var/lib/vz/snippets/proxmenux-rclone-${VMID}-fuse-hook.sh"
printf '%s\n' "$HOOK" >"$HOOK_PATH"
chmod 0755 "$HOOK_PATH"

oci_quiet pct mount "$VMID"
ROOTFS="/var/lib/lxc/${VMID}/rootfs"
install -d -m 0755 "$ROOTFS/usr/local/bin" "$ROOTFS/config/rclone"
printf 'username=%s\npassword=%s\n' "$RC_USER" "$RC_PASS" \
  >"$ROOTFS/config/rclone/webui.credentials"
chmod 0600 "$ROOTFS/config/rclone/webui.credentials"
WRAPPER=$(jq -er '.proxmox.laboratory_contract.generated_assets["mount-mode-wrapper"].content_template' "$TEMPLATE_FILE")
REMOTE_NAME_B64=$(printf '%s' "$REMOTE_NAME" | base64 -w0)
REMOTE_PATH_B64=$(printf '%s' "$REMOTE_PATH" | base64 -w0)
WRAPPER=${WRAPPER//\{\{remote_name_base64\}\}/$REMOTE_NAME_B64}
WRAPPER=${WRAPPER//\{\{remote_path_base64\}\}/$REMOTE_PATH_B64}
WRAPPER=${WRAPPER//\{\{mount_name\}\}/$MOUNT_NAME}
WRAPPER=${WRAPPER//\{\{vfs_cache_mode\}\}/$VFS_CACHE_MODE}
WRAPPER=${WRAPPER//\{\{webui_port\}\}/5572}
printf '%s\n' "$WRAPPER" >"$ROOTFS/usr/local/bin/rclone-mount-lxc-start"
chmod 0755 "$ROOTFS/usr/local/bin/rclone-mount-lxc-start"
oci_quiet pct unmount "$VMID"

sed -i -E '/^lxc\.environment\.runtime: RCLONE_RC_(USER|PASS)=/d' "/etc/pve/lxc/${VMID}.conf"
oci_quiet pct set "$VMID" --entrypoint /usr/local/bin/rclone-mount-lxc-start
sed -i -E '/^hookscript:/d' "/etc/pve/lxc/${VMID}.conf"
oci_quiet pct set "$VMID" --hookscript "local:snippets/$(basename "$HOOK_PATH")"
msg_ok "$(translate "Mount mode applied")"

msg_info "$(translate "Starting Rclone and waiting for the FUSE mount...")"
oci_quiet pct start "$VMID"
PUBLISHED_RW="$SHARED_RW/$MOUNT_NAME"
PUBLISHED_RO="$SHARED_RO/$MOUNT_NAME"
for attempt in $(seq 1 120); do
  if mountpoint -q "$PUBLISHED_RW" && mountpoint -q "$PUBLISHED_RO"; then
    break
  fi
  [[ $(pct status "$VMID" 2>/dev/null) == 'status: running' ]] \
    || die "$(translate "The container stopped before publishing the mount")"
  msg_progress "$(translate "Waiting for the FUSE mount:") ${attempt}/120 s"
  sleep 1
done
mountpoint -q "$PUBLISHED_RW" || die "$(translate "The read/write view was not published")"
mountpoint -q "$PUBLISHED_RO" || die "$(translate "The read-only view was not published")"
findmnt -T "$PUBLISHED_RO" -n -o VFS-OPTIONS | tr ',' '\n' | grep -qx ro \
  || die "$(translate "The read-only view does not apply the expected protection")"

IP=$(lxc-info -n "$VMID" -iH 2>/dev/null | grep -m1 -E '^[0-9]+\.' || true)
RESULT=$(jq -nc --argjson vmid "$VMID" --arg ip "$IP" --arg remote "$REMOTE_NAME" \
  --arg mount "$MOUNT_NAME" --arg rw "$PUBLISHED_RW" --arg ro "$PUBLISHED_RO" \
  --arg log "$OCI_LOG" \
  '{vmid:$vmid,ip:(if $ip == "" then null else $ip end),remote:$remote,mount_name:$mount,read_write_path:$rw,read_only_path:$ro,log:$log}')
ROLLBACK=0
msg_ok "$(translate "Rclone mount active")"
printf 'PROXMENUX_RESULT=%s\n' "$(printf '%s' "$RESULT" | base64 -w0)"
