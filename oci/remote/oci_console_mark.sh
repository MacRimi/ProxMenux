#!/bin/sh
# Run by the lxc.hook.pre-start of an OCI container. Marks each start in its
# console log, so the log can be read from the last start, and queues the
# check of its DHCP address for when it is up.
case "$1" in
  ''|*[!0-9]*) exit 0 ;;
esac
printf '\n=== ProxMenux: container started %s ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
  >> "/var/log/proxmenux/oci/$1.console.log" 2>/dev/null
lease="${0%/*}/oci_dhcp_lease.py"
if [ -r "$lease" ] && command -v systemd-run >/dev/null 2>&1; then
  systemd-run --quiet --collect --on-active=20 /usr/bin/python3 "$lease" "$1" >/dev/null 2>&1
fi
exit 0
