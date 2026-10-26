#!/bin/bash
# Experimental native LXC mount hook: PVE devN owns device creation/cgroups.
set -euo pipefail
[[ ${LXC_HOOK_TYPE:-${3:-}} == mount ]] || exit 1
[[ ${LXC_HOOK_SECTION:-${2:-}} == lxc ]] || exit 1
[[ ${NVIDIA_VISIBLE_DEVICES:-void} != void && -n ${NVIDIA_VISIBLE_DEVICES:-} ]] || exit 0
[[ -n ${LXC_ROOTFS_MOUNT:-} && -d $LXC_ROOTFS_MOUNT ]] || exit 1
# Do not use this hook outside an unprivileged user namespace.
awk '$1 == 0 && $2 == 0 && $3 == 4294967295 {exit 1}' /proc/self/uid_map || exit 1
# Same process-only transition used by the upstream LXC NVIDIA mount hook.
# Fail closed if it is denied; do not disable host or container AppArmor.
if [[ -d /sys/kernel/security/apparmor ]]; then
  printf 'changeprofile unconfined\n' > /proc/self/attr/current
fi
args=(--no-cgroups --no-devbind --ldconfig=@/usr/sbin/ldconfig)
args+=("--device=${NVIDIA_VISIBLE_DEVICES}")
capabilities=${NVIDIA_DRIVER_CAPABILITIES:-utility}
[[ $capabilities != all ]] || capabilities=compute,utility,video,graphics,display,compat32
while [[ -n $capabilities ]]; do
  capability=${capabilities%%,*}
  if [[ $capabilities == *,* ]]; then capabilities=${capabilities#*,}; else capabilities=; fi
  case "$capability" in
    compute|utility|video|graphics|display|compat32) args+=("--${capability}") ;;
    *) printf 'Unsupported NVIDIA capability: %s\n' "$capability" >&2; exit 1 ;;
  esac
done
for requirement in $(compgen -e NVIDIA_REQUIRE_ || true); do
  args+=("--require=${!requirement}")
done
exec nvidia-container-cli --user configure "${args[@]}" "$LXC_ROOTFS_MOUNT"
