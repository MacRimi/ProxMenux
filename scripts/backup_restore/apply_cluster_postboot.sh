#!/bin/bash
# ==========================================================
# ProxMenux - Apply Cluster Configs (post-boot)
# ==========================================================
# Fires AFTER pve-cluster.service is up, when /etc/pve is
# the live pmxcfs FUSE mount. We can write individual files
# to /etc/pve at this point and they propagate through the
# cluster filesystem normally — no need to stop pve-cluster
# (which would be unsafe at this stage of boot).
#
# Trigger: apply_pending_restore.sh writes a marker file at
# /var/lib/proxmenux/cluster-apply-pending whose contents is
# the absolute path of the recovery dir containing the
# extracted /etc/pve content. The systemd unit has
# ConditionPathExists=<marker>, so on a normal boot (no
# marker), the unit short-circuits and does nothing.

set +u

MARKER="${PMX_CLUSTER_APPLY_MARKER:-/var/lib/proxmenux/cluster-apply-pending}"
LOG_DIR="${PMX_LOG_DIR:-/var/log/proxmenux}"

mkdir -p "$LOG_DIR" >/dev/null 2>&1 || true
LOG_FILE="${LOG_DIR}/proxmenux-cluster-postboot-$(date +%Y%m%d_%H%M%S).log"
exec >>"$LOG_FILE" 2>&1

echo "=== ProxMenux cluster post-boot apply at $(date -Iseconds) ==="

if [[ ! -f "$MARKER" ]]; then
    echo "No marker found at $MARKER — nothing to apply."
    exit 0
fi

# Marker is env-style key=value, written by apply_pending_restore.sh.
# Defaults so a malformed marker still gives us safe behaviour.
RECOVERY_ROOT=""
PENDING_DIR=""
NEEDS_INITRAMFS=0
NEEDS_GRUB=0
# shellcheck source=/dev/null
source "$MARKER"
echo "Recovery root:   $RECOVERY_ROOT"
echo "Pending dir:     $PENDING_DIR"
echo "Needs initramfs: $NEEDS_INITRAMFS"
echo "Needs grub:      $NEEDS_GRUB"

if [[ -z "$RECOVERY_ROOT" || ! -d "$RECOVERY_ROOT" ]]; then
    echo "Recovery root invalid — aborting cleanly."
    rm -f "$MARKER"
    exit 0
fi

SOURCE_PVE="$RECOVERY_ROOT/etc/pve"
if [[ ! -d "$SOURCE_PVE" ]]; then
    echo "No /etc/pve content in recovery dir — nothing to do."
    rm -f "$MARKER"
    exit 0
fi

# Wait for pmxcfs to be fully writable. The After=pve-cluster.service
# in our unit gets us past the service-start point, but on slow boots
# the FUSE mount can take a few extra seconds to settle.
echo "Waiting for /etc/pve to be writable..."
for i in {1..60}; do
    if [[ -d /etc/pve ]] \
        && touch "/etc/pve/.proxmenux-test-$$" 2>/dev/null; then
        rm -f "/etc/pve/.proxmenux-test-$$" 2>/dev/null
        echo "/etc/pve writable after ${i}s"
        break
    fi
    sleep 1
done

# ── Detect source node name for cross-host node rename ────
# The source backup's node dir is whatever the source host
# was called; we copy its contents into THIS host's node
# dir. Two sources for the source hostname, in order of
# preference:
#   1. metadata/run_info.env from the pending dir (definitive)
#   2. The first (and usually only) dir under nodes/ in the
#      source backup — works when metadata is missing
SRC_NODE=""
if [[ -n "$PENDING_DIR" ]]; then
    META_RUN_INFO=$(find "$PENDING_DIR" -maxdepth 3 -name run_info.env 2>/dev/null | head -1)
    if [[ -n "$META_RUN_INFO" && -f "$META_RUN_INFO" ]]; then
        SRC_NODE=$(grep -m1 '^hostname=' "$META_RUN_INFO" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]')
    fi
fi
if [[ -z "$SRC_NODE" && -d "$SOURCE_PVE/nodes" ]]; then
    SRC_NODE=$(find "$SOURCE_PVE/nodes" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)
    SRC_NODE=$(basename "$SRC_NODE" 2>/dev/null)
fi
CUR_NODE=$(hostname)
echo "Source node: ${SRC_NODE:-(unknown)} / Current node: ${CUR_NODE}"

# ── Apply EVERY top-level file in /etc/pve ────────────────
# Anything that's a regular file at the root of /etc/pve
# (datacenter.cfg, storage.cfg, user.cfg, domains.cfg,
# vzdump.cron, jobs.cfg, replication.cfg, ceph.conf,
# corosync.conf if cluster, etc). pmxcfs symlinks like
# /etc/pve/local, /etc/pve/lxc, /etc/pve/qemu-server,
# /etc/pve/openvz are auto-created by pmxcfs and we skip
# them — copying over them throws "Operation not permitted".
echo ""
echo "── Global config files ──"
copied_global=0
PMX_SYMLINKS_SKIP="local lxc qemu-server openvz"
for src in "$SOURCE_PVE"/*; do
    [[ -f "$src" ]] || continue
    name=$(basename "$src")
    # Skip files that mirror pmxcfs symlinks
    skip=0
    for s in $PMX_SYMLINKS_SKIP; do
        [[ "$name" == "$s" ]] && { skip=1; break; }
    done
    (( skip )) && continue
    if cp -f "$src" "/etc/pve/$name" 2>&1; then
        echo "  ✓ $name"
        ((copied_global++))
    else
        echo "  ✗ $name (cp failed)"
    fi
done

# ── Subdirectories we want to preserve verbatim ───────────
# Each gets contents copied flat (no recursive dir copy of
# symlinks). These are the "shared cluster state" dirs.
echo ""
echo "── Cluster subdirectories ──"
copied_subdirs=0
for subdir in firewall sdn mapping virtual-guest priv ha; do
    src_dir="$SOURCE_PVE/$subdir"
    [[ -d "$src_dir" ]] || continue
    mkdir -p "/etc/pve/$subdir" 2>/dev/null || true
    while IFS= read -r f; do
        rel="${f#"$src_dir"/}"
        dst="/etc/pve/$subdir/$rel"
        if [[ -d "$f" ]]; then
            mkdir -p "$dst" 2>/dev/null || true
        elif [[ -f "$f" ]]; then
            mkdir -p "$(dirname "$dst")" 2>/dev/null || true
            cp -f "$f" "$dst" 2>/dev/null && ((copied_subdirs++))
        fi
    done < <(find "$src_dir" -mindepth 1 2>/dev/null)
    echo "  ✓ $subdir/ (subtree)"
done

# ── Apply guest configs into THIS node's dir ──────────────
# This is the bit that makes `pct list` / `qm list` show
# the restored guests. We deliberately copy from the
# source's node dir into the current host's node dir, so
# cross-host restores Just Work without renaming anything.
echo ""
echo "── Guest configs (LXC + QEMU) ──"
copied_guests=0
skipped_guests=0
if [[ -n "$SRC_NODE" ]] && [[ -d "$SOURCE_PVE/nodes/$SRC_NODE" ]]; then
    for kind in lxc qemu-server; do
        src_dir="$SOURCE_PVE/nodes/$SRC_NODE/$kind"
        dst_dir="/etc/pve/nodes/$CUR_NODE/$kind"
        [[ -d "$src_dir" ]] || continue
        mkdir -p "$dst_dir" 2>/dev/null || true
        for conf in "$src_dir"/*.conf; do
            [[ -f "$conf" ]] || continue
            vmid=$(basename "$conf" .conf)
            if [[ -e "$dst_dir/$vmid.conf" ]]; then
                echo "  ⚠ $kind/$vmid.conf already exists on this host — skipping (avoid clash)"
                ((skipped_guests++))
                continue
            fi
            if cp -f "$conf" "$dst_dir/$vmid.conf" 2>&1; then
                echo "  ✓ $kind/$vmid.conf"
                ((copied_guests++))
            else
                echo "  ✗ $kind/$vmid.conf (cp failed)"
            fi
        done
    done
else
    echo "  (no source node dir to copy from)"
fi

# ── Done with cluster config apply ─────────────────────────
echo ""
echo "Cluster summary: globals=$copied_global, subdirs=$copied_subdirs, guests=$copied_guests, guest-clashes-skipped=$skipped_guests"

# Remove the marker NOW (before the slow maintenance step
# below) so if the operator reboots mid-maintenance, we
# don't redo the (idempotent but wasteful) cluster apply.
# Maintenance below is also idempotent on re-run but takes
# 10+ min, so we'd rather not repeat it either — see the
# marker handling in the maintenance block.
rm -f "$MARKER"

# ── Post-restore maintenance (slow, deferrable) ────────────
# After a host-config restore, we need to:
#   - update-initramfs -u -k all  → so /etc/modules /etc/modprobe.d
#       /etc/initramfs-tools changes get baked into the initramfs
#       of every installed kernel for the NEXT boot.
#   - update-grub  → so /etc/default/grub changes land in
#       /boot/grub/grub.cfg for the NEXT boot.
#
# These are EXPENSIVE (initramfs build per kernel × 3 = 5-10 min;
# grub a few seconds) but the user's system is already fully up
# at this point: they can SSH in, use PVE, do anything — these
# run in the background and finish whenever they finish. The
# unit's TimeoutStartSec=900 (set in apply_pending_restore.sh)
# gives us a 15-min cushion. We log progress to the same log
# file so the operator can `tail -f` if curious.
echo ""
echo "── Post-restore maintenance ──"
# Only do these if the apply_pending_restore.sh's path-trigger
# analysis said they're needed. On a restore that didn't touch
# /etc/modules /etc/default/grub etc., both flags are 0 and we
# skip the slow rebuild entirely.
MAINT_MARKER="/var/lib/proxmenux/post-restore-maintenance-pending"
if [[ "$NEEDS_INITRAMFS" == "1" ]] || [[ "$NEEDS_GRUB" == "1" ]]; then
    mkdir -p /var/lib/proxmenux >/dev/null 2>&1 || true
    printf 'started: %s\n' "$(date -Iseconds)" > "$MAINT_MARKER"
fi

if [[ "$NEEDS_INITRAMFS" == "1" ]] && command -v update-initramfs >/dev/null 2>&1; then
    echo "Running: update-initramfs -u -k all  (5-10 min — restore touched initramfs inputs)"
    if update-initramfs -u -k all 2>&1 | tail -10; then
        echo "  ✓ update-initramfs done"
    else
        echo "  ✗ update-initramfs failed (system still boots; re-run manually)"
    fi
else
    echo "Skipping update-initramfs (restore didn't touch modules/initramfs-tools/crypttab)"
fi

if [[ "$NEEDS_GRUB" == "1" ]] && command -v update-grub >/dev/null 2>&1; then
    echo "Running: update-grub"
    if update-grub 2>&1 | tail -3; then
        echo "  ✓ update-grub done"
    else
        echo "  ✗ update-grub failed (re-run manually)"
    fi
else
    echo "Skipping update-grub (restore didn't touch /etc/default/grub or /etc/kernel)"
fi

# Clean up the maintenance marker now that we're done.
rm -f "$MAINT_MARKER"

# ── Component auto-reinstall (driven by components_status.json) ──
# The host-config restore brings back ProxMenux state (including
# components_status.json) but NOT the binary artifacts those
# components installed outside of apt — driver modules under
# /lib/modules/<kernel>/, binaries in /usr/bin/<tool>, downloaded
# .deb files, DKMS source trees, etc. For each component the
# restore state says was installed, we kick off its native
# installer in `--auto-reinstall` mode so it replays the install
# without dialogs. The installer's own logic handles "already
# present → no-op", so this is idempotent.
#
# Apt-only components are still handled by the
# packages.manual.list pass done earlier in the restore flow
# (they're in `apt-mark showmanual`). Running the installer here
# for them is harmless overhead (the installer just sees the
# package is present and exits 0), so we don't try to filter.
#
# To register a NEW component for auto-reinstall: add it to the
# COMPONENT_INSTALLERS array below as "component_key:relative
# script path". The script must accept `--auto-reinstall` and
# read its own state from components_status.json.
COMPONENTS_STATUS="/usr/local/share/proxmenux/components_status.json"
COMPONENT_INSTALLERS=(
    "nvidia_driver:gpu_tpu/nvidia_installer.sh"
    "amdgpu_top:gpu_tpu/amd_gpu_tools.sh"
    "intel_gpu_tools:gpu_tpu/intel_gpu_tools.sh"
    "coral_driver:gpu_tpu/install_coral.sh"
)

if command -v jq >/dev/null 2>&1 && [[ -f "$COMPONENTS_STATUS" ]]; then
    echo ""
    echo "── Component auto-reinstall ──"
    SCRIPTS_BASE="/usr/local/share/proxmenux/scripts"
    for entry in "${COMPONENT_INSTALLERS[@]}"; do
        comp="${entry%%:*}"
        installer="$SCRIPTS_BASE/${entry#*:}"

        comp_status=$(jq -r ".${comp}.status // \"\"" "$COMPONENTS_STATUS" 2>/dev/null)
        if [[ "$comp_status" != "installed" ]]; then
            continue   # Was never installed on the source, or was uninstalled — skip.
        fi

        if [[ ! -f "$installer" ]]; then
            echo "  ✗ $comp: installer missing at $installer — skipping"
            continue
        fi

        echo ""
        echo "  → $comp (running $installer --auto-reinstall)"
        # Run with limited output capture. The installer logs in full to
        # its own log file; we only echo a tail here for the operator.
        bash "$installer" --auto-reinstall 2>&1 | sed -e 's/^/    /' | tail -15
        rc=${PIPESTATUS[0]}
        if (( rc == 0 )); then
            echo "  ✓ $comp ok"
        else
            echo "  ✗ $comp installer exited $rc — see its own log"
        fi
    done
fi

echo ""
echo "=== Apply finished at $(date -Iseconds) ==="
echo "Log: $LOG_FILE"
