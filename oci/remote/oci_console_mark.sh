#!/bin/sh
# Marks each start of an OCI container in its console log, so the log can be
# read from the last start. Run by the container's lxc.hook.pre-start.
case "$1" in
  ''|*[!0-9]*) exit 0 ;;
esac
printf '\n=== ProxMenux: container started %s ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
  >> "/var/log/proxmenux/oci/$1.console.log" 2>/dev/null
exit 0
