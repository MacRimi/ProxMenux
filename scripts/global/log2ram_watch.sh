#!/bin/bash
# ==========================================================
# ProxMenux - Keeps the Log2RAM folder from filling up
# ==========================================================
# Past 85% of its size, the logs in RAM are rotated and the ones just rotated
# are compressed at once, then everything is written to disk. Rules with
# delaycompress, such as the one of pveproxy, would otherwise leave the largest
# log uncompressed until the next day. No log is emptied.
# ==========================================================

PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

mountpoint -q /var/log || exit 0
used="$(df --output=pcent /var/log 2>/dev/null | tail -1 | tr -dc '0-9')"
[ "${used:-0}" -ge 85 ] || exit 0

exec 9>/run/proxmenux-log2ram-watch.lock || exit 0
flock -n 9 || exit 0

logrotate -f /etc/logrotate.conf >/dev/null 2>&1 || true
find /var/log -xdev -type f -name '*.1' -exec gzip -9 -- {} + 2>/dev/null || true
systemctl reload log2ram >/dev/null 2>&1 || true
