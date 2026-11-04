#!/bin/sh
# Borg 1.2.8 has no official ARM64 standalone release. Never ship or run
# its AMD64 executable on ARM; use the host's native distro package instead.
if [ -x /usr/bin/borg ]; then
    exec /usr/bin/borg "$@"
fi
echo 'Native Borg is unavailable. Install the native borgbackup package on this host to use Borg backups.' >&2
exit 127
