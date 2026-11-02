#!/bin/bash
# ==========================================================
# ProxMenux - Log2RAM setup shared by both post-install modes
# ==========================================================
# Log2RAM keeps /var/log in RAM and writes it to disk on a schedule. The
# journal and the task logs of Proxmox VE and Proxmox Backup Server stay on
# disk: see log2ram_keep_on_disk.sh, which moves them before Log2RAM starts.
#
# Requires utils.sh (translate, msg_*) and pmx_journal.sh (pmx_write_file...).
# ==========================================================

PMX_L2R_TAG="1.7.2"
PMX_L2R_COMMIT="f171449530f8984374c8f69fff3c92af813a694b"
PMX_L2R_REPO="https://github.com/azlux/log2ram.git"
PMX_L2R_SCRIPTS="/usr/local/share/proxmenux/scripts/global"
PMX_L2R_REVERT_UNIT="/etc/systemd/system/proxmenux-log2ram-revert.service"

# Size in MB and sync interval in hours proposed for this host's RAM.
pmx_log2ram_default_size() {
    local ram_gb
    ram_gb="$(awk '/^MemTotal:/{print int($2/1024/1024)}' /proc/meminfo)"
    if (( ${ram_gb:-4} <= 8 )); then echo 128
    elif (( ram_gb <= 16 )); then echo 256
    else echo 512; fi
}

pmx_log2ram_default_hours() {
    local ram_gb
    ram_gb="$(awk '/^MemTotal:/{print int($2/1024/1024)}' /proc/meminfo)"
    if (( ${ram_gb:-4} <= 8 )); then echo 1
    elif (( ram_gb <= 16 )); then echo 3
    else echo 6; fi
}

# What an installed Log2RAM is set to, for an update to keep it.
pmx_log2ram_current_size() {
    local size
    size="$(grep -E '^SIZE=' /etc/log2ram.conf 2>/dev/null | tail -1 | cut -d= -f2 | tr -dc '0-9')"
    echo "${size:-$(pmx_log2ram_default_size)}"
}

pmx_log2ram_current_hours() {
    local hours
    hours="$(sed -n 's/^OnCalendar=\*-\*-\* 00\/\([0-9]*\):55:00$/\1/p' \
        /etc/systemd/system/log2ram-daily.timer.d/proxmenux.conf 2>/dev/null)"
    # Earlier versions synced from a cron entry: "0 */N * * * root ... write".
    [[ -n "$hours" ]] || hours="$(sed -n 's/^0 \*\/\([0-9]*\) .*log2ram write.*/\1/p' /etc/cron.d/log2ram 2>/dev/null)"
    echo "${hours:-$(pmx_log2ram_default_hours)}"
}

# Size-based rotation for the API logs of Proxmox Backup Server, whose
# package ships no rule for them.
_pmx_log2ram_pbs_logrotate() {
    dpkg-query -W -f='${Status}' proxmox-backup-server 2>/dev/null | grep -q 'install ok installed' || return 0
    pmx_write_file /etc/logrotate.d/proxmox-backup-api <<'EOF'
/var/log/proxmox-backup/api/access.log /var/log/proxmox-backup/api/auth.log {
    size 20M
    rotate 3
    compress
    missingok
    notifempty
    copytruncate
}
EOF
    chmod 0644 /etc/logrotate.d/proxmox-backup-api
}

# Files of the Log2RAM release, copied from a verified checkout. Its own
# install.sh is not run: it refuses to run while Log2RAM is active and starts
# by deleting /var/hdd.log, which is the disk copy of /var/log while mounted.
_pmx_log2ram_install_release() {
    local checkout="/tmp/log2ram-${PMX_L2R_TAG}"
    rm -rf "$checkout"
    if ! git clone --quiet --depth 1 --branch "$PMX_L2R_TAG" "$PMX_L2R_REPO" "$checkout" >/dev/null 2>&1; then
        msg_error "$(translate "Log2RAM could not be downloaded")"
        return 1
    fi
    if [[ "$(git -C "$checkout" rev-parse HEAD 2>/dev/null)" != "$PMX_L2R_COMMIT" ]]; then
        rm -rf "$checkout"
        msg_error "$(translate "The downloaded Log2RAM does not match the expected release")"
        return 1
    fi
    mkdir -p /usr/local/bin
    install -m 644 "$checkout/log2ram.service" /etc/systemd/system/log2ram.service
    install -m 644 "$checkout/log2ram-daily.service" /etc/systemd/system/log2ram-daily.service
    install -m 644 "$checkout/log2ram-daily.timer" /etc/systemd/system/log2ram-daily.timer
    install -m 755 "$checkout/log2ram" /usr/local/bin/log2ram
    [[ -d /etc/logrotate.d ]] && install -m 644 "$checkout/log2ram.logrotate" /etc/logrotate.d/log2ram
    [[ -f /etc/log2ram.conf ]] || install -m 644 "$checkout/log2ram.conf" /etc/log2ram.conf
    rm -rf "$checkout"
}

# What earlier versions of this function installed and this one replaces.
_pmx_log2ram_remove_legacy() {
    local path
    for path in /etc/cron.d/log2ram /usr/local/bin/log2ram-check.sh \
        /etc/cron.hourly/proxmox-backup-logrotate \
        /usr/local/bin/log2ram.proxmenux.bak /usr/sbin/log2ram.proxmenux.bak; do
        pmx_remove_file "$path" 2>/dev/null || true
    done
}

# pmx_log2ram_setup SIZE_MB SYNC_HOURS WATCH(true|false)
pmx_log2ram_setup() {
    local size_mb="$1" hours="$2" watch="$3"
    local keep_free_mb=$(( size_mb / 2 ))

    command -v rsync >/dev/null 2>&1 || pmx_install_pkg rsync
    command -v git >/dev/null 2>&1 || pmx_install_pkg git

    msg_info "$(translate "Installing Log2RAM") ${PMX_L2R_TAG}..."
    _pmx_log2ram_install_release || return 1
    msg_ok "$(translate "Log2RAM installed:") ${PMX_L2R_TAG}"

    # The journal is not in RAM, so Log2RAM does not rotate it before a sync;
    # and Proxmox has no mail command for its error notice.
    pmx_edit_file /etc/log2ram.conf \
        -e "s/^SIZE=.*/SIZE=${size_mb}M/" \
        -e "s/^JOURNALD_AWARE=.*/JOURNALD_AWARE=false/" \
        -e "s/^#\?NOTIFICATION=.*/NOTIFICATION=false/"
    grep -q '^NOTIFICATION=' /etc/log2ram.conf || printf 'NOTIFICATION=false\n' | pmx_append_file /etc/log2ram.conf

    mkdir -p /etc/systemd/system/log2ram.service.d /etc/systemd/system/log2ram-daily.timer.d
    pmx_write_file /etc/systemd/system/log2ram.service.d/proxmenux.conf <<EOF
# ProxMenux: the journal stays on disk, and a sync is on disk when it ends.
[Service]
ExecStartPre=-${PMX_L2R_SCRIPTS}/log2ram_keep_on_disk.sh
ExecReload=
ExecReload=/usr/local/bin/log2ram write
ExecReload=/bin/sync -f /var/hdd.log
EOF
    pmx_write_file /etc/systemd/system/log2ram-daily.timer.d/proxmenux.conf <<EOF
# ProxMenux: /var/log is written to disk every ${hours} hour(s).
[Timer]
OnCalendar=
OnCalendar=*-*-* 00/${hours}:55:00
EOF

    mkdir -p /etc/systemd/journald.conf.d
    pmx_write_file /etc/systemd/journald.conf.d/proxmenux-log2ram.conf <<EOF
# ProxMenux: the journal is kept on disk, outside the Log2RAM folder.
# SystemKeepFree also bounds it while it is still in RAM, until the next boot.
[Journal]
Storage=persistent
SystemMaxUse=1G
SystemKeepFree=${keep_free_mb}M
# MaxLevelStore=info: required for ProxMenux Monitor log display and Fail2Ban detection.
MaxLevelStore=info
EOF
    # The journal folder is a link; the attribute for btrfs goes to its target.
    pmx_write_file /etc/tmpfiles.d/journal-nocow.conf <<'EOF'
# ProxMenux: /var/log/journal links to /var/hdd.journal while Log2RAM is installed.
h /var/hdd.journal - - - - +C
h /var/hdd.journal/%m - - - - +C
h /var/hdd.journal/remote - - - - +C
EOF

    if [[ "$watch" == true ]]; then
        pmx_write_file /etc/cron.d/log2ram-auto-sync <<EOF
# ProxMenux: past 85% of its size, /var/log in RAM is rotated and written to disk.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
3-59/10 * * * * root nice -n 19 ionice -c 3 ${PMX_L2R_SCRIPTS}/log2ram_watch.sh >/dev/null 2>&1
EOF
        chmod 0644 /etc/cron.d/log2ram-auto-sync
    else
        pmx_remove_file /etc/cron.d/log2ram-auto-sync 2>/dev/null || true
    fi

    _pmx_log2ram_pbs_logrotate
    _pmx_log2ram_remove_legacy
    pmx_remove_file "$PMX_L2R_REVERT_UNIT" 2>/dev/null || true

    systemctl daemon-reload >/dev/null 2>&1 || true
    pmx_apply_setting "service-enabled:log2ram" "systemctl is-enabled log2ram" \
        systemctl enable log2ram.service log2ram-daily.timer || return 1
    msg_ok "$(translate "Log2RAM keeps /var/log in RAM; the journal stays on disk from the next boot")"
}

# Log2RAM stops at the next shutdown, writing /var/log to disk on its way;
# the boot after that puts the journal back in /var/log.
pmx_log2ram_remove() {
    pmx_disable_service log2ram-daily.timer 2>/dev/null || true
    systemctl disable log2ram.service >/dev/null 2>&1 || true

    local path
    for path in /etc/cron.d/log2ram-auto-sync /etc/systemd/journald.conf.d/proxmenux-log2ram.conf \
        /etc/tmpfiles.d/journal-nocow.conf /etc/systemd/system/log2ram.service.d/proxmenux.conf \
        /etc/systemd/system/log2ram-daily.timer.d/proxmenux.conf; do
        pmx_remove_file "$path" 2>/dev/null || true
    done
    _pmx_log2ram_remove_legacy

    pmx_write_file "$PMX_L2R_REVERT_UNIT" <<EOF
[Unit]
Description=ProxMenux: put the journal back in /var/log after removing Log2RAM
DefaultDependencies=no
After=local-fs.target
Before=systemd-journald.service sysinit.target
ConditionPathExists=!/etc/systemd/system/sysinit.target.wants/log2ram.service

[Service]
Type=oneshot
Environment=PMX_L2R_REVERT=1
ExecStart=-${PMX_L2R_SCRIPTS}/log2ram_keep_on_disk.sh
ExecStart=/bin/sh -c 'mountpoint -q /var/hdd.log || rmdir /var/hdd.log 2>/dev/null; rm -f /usr/local/bin/log2ram /usr/local/bin/uninstall-log2ram.sh /etc/log2ram.conf /etc/logrotate.d/log2ram /etc/systemd/system/log2ram.service /etc/systemd/system/log2ram-daily.service /etc/systemd/system/log2ram-daily.timer; rmdir /etc/systemd/system/log2ram.service.d /etc/systemd/system/log2ram-daily.timer.d 2>/dev/null; systemctl disable proxmenux-log2ram-revert.service; rm -f ${PMX_L2R_REVERT_UNIT}; systemctl daemon-reload'

[Install]
WantedBy=sysinit.target
EOF
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable proxmenux-log2ram-revert.service >/dev/null 2>&1 || true
}
