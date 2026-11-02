#!/bin/bash
# ==========================================================
# ProxMenux - Folders of /var/log that Log2RAM leaves on disk
# ==========================================================
# Runs before Log2RAM puts /var/log in RAM. The journal, the task logs of
# Proxmox VE and those of Proxmox Backup Server are records a host needs after
# a power cut, and a task cannot run if its log cannot be written, so they
# stay on disk: each folder moves to
# /var/hdd.<name> and its usual place becomes a link to it. Log2RAM copies a
# link as a link, so their contents never enter the RAM.
#
# With PMX_L2R_REVERT=1 it puts the folders back in /var/log and removes the
# links; the uninstaller runs it that way at the next boot.
#
# PMX_L2R_ROOT prefixes every path, for tests.
# ==========================================================

ROOT="${PMX_L2R_ROOT:-}"
LOG_DIR="$ROOT/var/log"

# Only while /var/log is the folder on disk, never the copy in RAM.
if [ -z "$ROOT" ] && mountpoint -q /var/log; then
    exit 0
fi

KEPT_ON_DISK="journal pve proxmox-backup"

keep_on_disk() {
    local name="$1"
    local place="$LOG_DIR/$name" disk="$ROOT/var/hdd.$name"

    if [ -L "$place" ]; then
        [ -d "$disk" ] || mkdir -p "$disk"
        return 0
    fi
    # The journal is always kept on disk; any other folder only where it exists.
    if [ ! -d "$place" ]; then
        [ "$name" = journal ] || return 0
        mkdir -p "$disk"
        chown root:systemd-journal "$disk" 2>/dev/null || true
        chmod 2755 "$disk"
    elif [ ! -e "$disk" ]; then
        mv "$place" "$disk" || return 1
    else
        cp -a "$place/." "$disk/" || return 1
        rm -rf "${place:?}"
    fi
    ln -s "/var/hdd.$name" "$place"
}

put_back() {
    local name="$1"
    local place="$LOG_DIR/$name" disk="$ROOT/var/hdd.$name"

    [ -d "$disk" ] || { [ -L "$place" ] && rm -f "$place"; return 0; }
    [ -L "$place" ] && rm -f "$place"
    if [ ! -e "$place" ]; then
        mv "$disk" "$place" || return 1
    else
        cp -a "$disk/." "$place/" || return 1
        rm -rf "${disk:?}"
    fi
}

status=0
for name in $KEPT_ON_DISK; do
    if [ "${PMX_L2R_REVERT:-0}" = 1 ]; then
        put_back "$name" || status=1
    else
        keep_on_disk "$name" || status=1
    fi
done
exit "$status"
