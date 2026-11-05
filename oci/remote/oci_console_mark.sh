#!/bin/sh
# Run by the lxc.hook.pre-start of an OCI container. Marks each start in its
# console log, so the log can be read from the last start, and queues the
# check of its DHCP address for when it is up.
case "$1" in
  ''|*[!0-9]*) exit 0 ;;
esac
# Direct PVE restore formats managed filesystems again. The installed record
# authorizes this narrow cleanup; missing/busy records leave the guest alone.
# A hook failure must not prevent the console marker or the DHCP timer.
volumes="${0%/*}/oci_managed_volumes.py"
if [ -r "$volumes" ] && command -v timeout >/dev/null 2>&1; then
  timeout --signal=TERM --kill-after=2 10 python3 "$volumes" startup "$1" >/dev/null 2>&1 || :
fi
printf '\n=== ProxMenux: container started %s ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
  >> "/var/log/proxmenux/oci/$1.console.log" 2>/dev/null
lease="${0%/*}/oci_dhcp_lease.py"
if [ -r "$lease" ] && command -v systemd-run >/dev/null 2>&1; then
  systemd-run --quiet --collect --on-active=20 /usr/bin/python3 "$lease" "$1" >/dev/null 2>&1
fi
exit 0
