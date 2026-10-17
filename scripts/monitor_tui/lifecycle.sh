#!/bin/bash
# Install and remove only ProxMenux-owned console integration files.
set -euo pipefail

BASE_DIR=${PROXMENUX_TUI_BASE_DIR:-/usr/local/share/proxmenux}
BIN_DIR=${PROXMENUX_TUI_BIN_DIR:-/usr/local/bin}
DROPIN_DIR=${PROXMENUX_TUI_DROPIN_DIR:-/etc/systemd/system/getty@tty1.service.d}
DROPIN=$DROPIN_DIR/90-proxmenux-monitor-tui.conf
TMPFILES=${PROXMENUX_TUI_TMPFILES:-/etc/tmpfiles.d/proxmenux-monitor-console.conf}
RUN_DIR=${PROXMENUX_TUI_RUN_DIR:-/run/proxmenux-monitor}
GROUP=proxmenux-monitor
SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

owned_file() {
  [[ -f "$1" && ! -L "$1" ]] || return 1
  local first second
  IFS= read -r first < "$1" || true
  second=$(sed -n '2p' "$1")
  [[ "$first" == '# ProxMenux-owned' ||
     ( "$first" == '#!/bin/sh' && "$second" == '# ProxMenux-owned' ) ]]
}

install_tui() {
  local backup_dir path index=0 status had_group=false wrappers_ready=true temporary
  local -a paths existed
  backup_dir=$(mktemp -d "${PROXMENUX_TUI_TMPDIR:-/run}/proxmenux-monitor-tui.XXXXXX")
  paths=("$BIN_DIR/proxmenux-monitor" "$BIN_DIR/proxmenux-monitor-tui"
         "$BIN_DIR/proxmenux-monitor-getty-pre" "$DROPIN" "$TMPFILES"
         "$BASE_DIR/monitor-tui.disabled" "$BASE_DIR/monitor-tui.group-owned")
  for path in "${paths[@]}"; do
    if [[ -e "$path" || -L "$path" ]]; then
      existed+=(true)
      cp -a -- "$path" "$backup_dir/$index"
    else
      existed+=(false)
    fi
    index=$((index + 1))
  done
  if getent group "$GROUP" >/dev/null; then had_group=true; fi
  rollback_install() {
    status=$?
    trap - ERR
    for index in "${!paths[@]}"; do
      path=${paths[$index]}
      if [[ "${existed[$index]}" == true ]]; then
        rm -f -- "$path"
        mkdir -p "$(dirname "$path")"
        cp -a -- "$backup_dir/$index" "$path"
      else
        rm -f -- "$path"
      fi
    done
    rmdir "$RUN_DIR" 2>/dev/null || true
    if [[ "$had_group" == false ]] && getent group "$GROUP" >/dev/null; then
      groupdel "$GROUP" >/dev/null 2>&1 || true
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    rm -rf -- "$backup_dir"
    exit "$status"
  }
  trap rollback_install ERR
  if ! getent group "$GROUP" >/dev/null; then
    if [[ -e "$BASE_DIR/monitor-tui.group-owned" || -L "$BASE_DIR/monitor-tui.group-owned" ]] &&
       ! owned_file "$BASE_DIR/monitor-tui.group-owned"; then
      echo "Refusing to overwrite unowned group marker state." >&2
      false
    fi
    install -d -m 0755 "$BASE_DIR"
    groupadd --system "$GROUP"
    printf '%s\n' '# ProxMenux-owned' > "$BASE_DIR/monitor-tui.group-owned"
    chmod 0600 "$BASE_DIR/monitor-tui.group-owned"
  fi

  for name in proxmenux-monitor proxmenux-monitor-tui proxmenux-monitor-getty-pre; do
    target="$BIN_DIR/$name"
    if [[ -e "$target" || -L "$target" ]] && ! owned_file "$target"; then
      echo "Skipping unowned $target" >&2
      wrappers_ready=false
      continue
    fi
    temporary=$(mktemp "$BIN_DIR/.${name}.XXXXXX")
    install -m 0755 "$SOURCE_DIR/$name" "$temporary"
    mv -f "$temporary" "$target"
  done

  if [[ -e "$TMPFILES" || -L "$TMPFILES" ]] && ! owned_file "$TMPFILES"; then
    echo "Skipping unowned tmpfiles config $TMPFILES" >&2
  else
    install -d -m 0755 "$(dirname "$TMPFILES")"
    temporary=$(mktemp "$(dirname "$TMPFILES")/.proxmenux-monitor-console.XXXXXX")
    cat > "$temporary" <<EOF
# ProxMenux-owned
# Runtime directory for read-only console samples.
d $RUN_DIR 0750 root $GROUP -
EOF
    chmod 0644 "$temporary"
    mv -f "$temporary" "$TMPFILES"
  fi

  if [[ "$wrappers_ready" != true ]]; then
    echo "TTY1 autostart skipped because a launcher path is owned by another component." >&2
    false
  fi

  if [[ -e "$DROPIN" || -L "$DROPIN" ]] && ! owned_file "$DROPIN"; then
    echo "Skipping unowned getty drop-in $DROPIN" >&2
    false
  fi
  install -d -m 0755 "$DROPIN_DIR"
  temporary=$(mktemp "$DROPIN_DIR/.90-proxmenux-monitor-tui.XXXXXX")
  cat > "$temporary" <<EOF
# ProxMenux-owned
# Removed by Monitor uninstall.
[Service]
ExecStartPre=$BIN_DIR/proxmenux-monitor-getty-pre
TimeoutStartSec=0
EOF
  chmod 0644 "$temporary"
  mv -f "$temporary" "$DROPIN"
  if owned_file "$TMPFILES"; then
    systemd-tmpfiles --create "$TMPFILES" >/dev/null 2>&1 || true
  fi
  systemctl daemon-reload
  # Do not start/restart getty here: an occupied TTY must remain untouched.
  trap - ERR
  rm -rf -- "$backup_dir"
}

uninstall_tui() {
  if [[ -e "$DROPIN" || -L "$DROPIN" ]] && ! owned_file "$DROPIN"; then
    local owned_wrapper=false
    for name in proxmenux-monitor proxmenux-monitor-tui proxmenux-monitor-getty-pre; do
      if owned_file "$BIN_DIR/$name"; then owned_wrapper=true; break; fi
    done
    if [[ "$owned_wrapper" == true ]]; then
      echo "Refusing to remove TTY1 wrappers while an unowned getty drop-in remains: $DROPIN" >&2
      return 1
    fi
  fi
  if owned_file "$DROPIN"; then rm -f "$DROPIN"; fi
  # Apply the restored getty unit before any later cleanup step can fail.
  systemctl daemon-reload
  if owned_file "$TMPFILES"; then rm -f "$TMPFILES"; fi
  for name in proxmenux-monitor proxmenux-monitor-tui proxmenux-monitor-getty-pre; do
    target="$BIN_DIR/$name"
    if owned_file "$target"; then rm -f "$target"; fi
  done
  if [[ -f "$BASE_DIR/monitor-tui.disabled" && ! -L "$BASE_DIR/monitor-tui.disabled" ]] &&
     [[ "$(head -n 1 "$BASE_DIR/monitor-tui.disabled")" == '# ProxMenux-owned TTY1 opt-out state.' ]]; then
    rm -f "$BASE_DIR/monitor-tui.disabled"
  fi
  if [[ -f "$RUN_DIR/console.json" && ! -L "$RUN_DIR/console.json" ]] &&
     python3 - "$RUN_DIR/console.json" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        value = json.load(stream)
    raise SystemExit(0 if value.get("publisher") == "proxmenux-monitor" and value.get("schema_version") == 1 else 1)
except (OSError, ValueError, AttributeError):
    raise SystemExit(1)
PY
  then
    rm -f "$RUN_DIR/console.json"
  fi
  if [[ -f "$RUN_DIR/tty1-seen" && ! -L "$RUN_DIR/tty1-seen" ]] &&
     [[ "$(head -n 1 "$RUN_DIR/tty1-seen")" == 'ProxMenux TTY1 attempted this boot.' ]]; then
    rm -f "$RUN_DIR/tty1-seen"
  fi
  rmdir "$RUN_DIR" 2>/dev/null || true
  if owned_file "$BASE_DIR/monitor-tui.group-owned"; then
    if getent group "$GROUP" >/dev/null; then
      if ! getent group "$GROUP" | awk -F: 'NF && $4 == "" {found=1} END {exit !found}'; then
        echo "Cannot remove $GROUP because it still has members; preserving its ownership marker." >&2
        return 1
      fi
      if ! groupdel "$GROUP" >/dev/null 2>&1; then
        echo "Failed to remove owned group $GROUP; preserving its ownership marker." >&2
        return 1
      fi
    fi
    rm -f "$BASE_DIR/monitor-tui.group-owned"
  fi
}

case "${1:-}" in
  install) install_tui ;;
  uninstall) uninstall_tui ;;
  *) echo "Usage: $0 {install|uninstall}" >&2; exit 2 ;;
esac
