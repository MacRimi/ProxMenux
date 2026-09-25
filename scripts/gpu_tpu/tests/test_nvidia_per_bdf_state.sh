#!/usr/bin/env bash
set -euo pipefail

TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT

export PROXMENUX_SYSFS_ROOT="$TEST_ROOT/sys"
export PROXMENUX_ETC_ROOT="$TEST_ROOT/etc"
export PROXMENUX_STATE_ROOT="$TEST_ROOT/usr/local/share/proxmenux"
export PROXMENUX_VFIO_BIND_STATE="$PROXMENUX_ETC_ROOT/proxmenux/vfio-bind.bdfs"
export PROXMENUX_VFIO_BIND_UDEV_RULE="$PROXMENUX_ETC_ROOT/udev/rules.d/10-proxmenux-vfio-bind.rules"
export PROXMENUX_VFIO_CONF="$PROXMENUX_ETC_ROOT/modprobe.d/vfio.conf"
export PROXMENUX_NVIDIA_VFIO_BLACKLIST="$PROXMENUX_ETC_ROOT/modprobe.d/proxmenux-nvidia-vfio-blacklist.conf"
export PROXMENUX_NVIDIA_SERVICE_STATE="$PROXMENUX_STATE_ROOT/nvidia-host-services.state"
export PROXMENUX_NVIDIA_SERVICE_LEGACY_STATE="$TEST_ROOT/var/lib/proxmenux/nvidia-host-services.state"
export PROXMENUX_VFIO_BIND_LEGACY_HOOK="$PROXMENUX_ETC_ROOT/initramfs-tools/scripts/init-top/proxmenux-vfio-bind"
export SYSTEMCTL_LOG="$TEST_ROOT/systemctl.log"

mkdir -p "$PROXMENUX_SYSFS_ROOT/bus/pci/devices" "$PROXMENUX_ETC_ROOT/modprobe.d" "$TEST_ROOT/bin"

# The policy helper manages systemd services on a real host. Unit tests must
# never touch them, so provide an inert command before sourcing the helper.
cat > "$TEST_ROOT/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  is-enabled|is-active) exit 1 ;;
  *) printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"; exit 0 ;;
esac
EOF
chmod +x "$TEST_ROOT/bin/systemctl"
export PATH="$TEST_ROOT/bin:$PATH"

make_pci_device() {
  local bdf="$1" vendor="$2" device="$3" class="$4"
  local path="$PROXMENUX_SYSFS_ROOT/bus/pci/devices/$bdf"
  mkdir -p "$path"
  printf '0x%s\n' "$vendor" > "$path/vendor"
  printf '0x%s\n' "$device" > "$path/device"
  printf '0x%s\n' "$class" > "$path/class"
}

# Two identical NVIDIA GPUs reproduce the collision that vendor:device
# binding caused: both share 10de:2484 but must be independently reversible.
make_pci_device 0000:01:00.0 10de 2484 030000
make_pci_device 0000:01:00.1 10de 228b 040300
make_pci_device 0000:02:00.0 10de 2484 030000
make_pci_device 0000:02:00.1 10de 228b 040300
make_pci_device 0000:00:1f.3 8086 7ad0 040300

cat > "$PROXMENUX_VFIO_CONF" <<'EOF'
options vfio-pci ids=10DE:2484,10DE:228B,8086:7ad0 disable_vga=1
EOF

HOST_CONFIG_CHANGED=false
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../../global/pci_passthrough_helpers.sh
source "$SCRIPT_DIR/../../global/pci_passthrough_helpers.sh"

_proxmenux_vfio_bind_migrate_legacy_nvidia_ids

grep -qxF '0000:01:00.0' "$PROXMENUX_VFIO_BIND_STATE"
grep -qxF '0000:01:00.1' "$PROXMENUX_VFIO_BIND_STATE"
grep -qxF '0000:02:00.0' "$PROXMENUX_VFIO_BIND_STATE"
grep -qxF '0000:02:00.1' "$PROXMENUX_VFIO_BIND_STATE"
grep -q 'ids=8086:7ad0' "$PROXMENUX_VFIO_CONF"
! grep -qi '10de:2484' "$PROXMENUX_VFIO_CONF"
! grep -qi '10de:228b' "$PROXMENUX_VFIO_CONF"
_proxmenux_all_nvidia_in_vfio
[[ -f "$PROXMENUX_NVIDIA_VFIO_BLACKLIST" ]]

# Returning only one GPU to the host must keep the other exact BDF in VFIO,
# remove the global NVIDIA blacklist, retain NVIDIA softdeps, and restore any
# service state captured by the short-lived /var/lib implementation.
mkdir -p "$(dirname "$PROXMENUX_NVIDIA_SERVICE_LEGACY_STATE")"
printf '%s\n' 'nvidia-persistenced.service enabled=1 active=1' \
  > "$PROXMENUX_NVIDIA_SERVICE_LEGACY_STATE"
_proxmenux_vfio_bind_remove_bdfs 0000:01:00.0 0000:01:00.1
! _proxmenux_vfio_bind_has_bdf 0000:01:00.0
! _proxmenux_vfio_bind_has_bdf 0000:01:00.1
_proxmenux_vfio_bind_has_bdf 0000:02:00.0
_proxmenux_vfio_bind_has_bdf 0000:02:00.1
! _proxmenux_all_nvidia_in_vfio
[[ ! -e "$PROXMENUX_NVIDIA_VFIO_BLACKLIST" ]]
grep -qFx 'softdep nvidia pre: vfio-pci' "$PROXMENUX_VFIO_CONF"
[[ ! -e "$PROXMENUX_NVIDIA_SERVICE_LEGACY_STATE" ]]
[[ ! -e "$PROXMENUX_NVIDIA_SERVICE_STATE" ]]
grep -qFx 'enable nvidia-persistenced.service' "$SYSTEMCTL_LOG"
grep -qFx 'start nvidia-persistenced.service' "$SYSTEMCTL_LOG"

# Returning the final NVIDIA GPU removes the remaining per-BDF policy while
# leaving unrelated Intel VFIO configuration untouched.
_proxmenux_vfio_bind_remove_bdfs 0000:02:00.0 0000:02:00.1
! _proxmenux_vfio_bind_has_entries
! grep -qFx 'softdep nvidia pre: vfio-pci' "$PROXMENUX_VFIO_CONF"
grep -q 'ids=8086:7ad0' "$PROXMENUX_VFIO_CONF"

echo "PASS: NVIDIA per-BDF migration and selective restore"
