#!/bin/bash
# ==========================================================
# ProxMenux - Apply Pending Restore On Boot
# ==========================================================

PENDING_BASE="${PMX_RESTORE_PENDING_BASE:-/var/lib/proxmenux/restore-pending}"
CURRENT_LINK="${PENDING_BASE}/current"
LOG_DIR="${PMX_RESTORE_LOG_DIR:-/var/log/proxmenux}"
DEST_PREFIX="${PMX_RESTORE_DEST_PREFIX:-/}"
PRE_BACKUP_BASE="${PMX_RESTORE_PRE_BACKUP_BASE:-/var/lib/proxmenux/pre-restore}"
RECOVERY_BASE="${PMX_RESTORE_RECOVERY_BASE:-/var/lib/proxmenux/recovery}"

mkdir -p "$LOG_DIR" "$PENDING_BASE/completed" >/dev/null 2>&1 || true
LOG_FILE="${LOG_DIR}/proxmenux-restore-onboot-$(date +%Y%m%d_%H%M%S).log"

exec >>"$LOG_FILE" 2>&1

echo "=== ProxMenux pending restore started at $(date -Iseconds) ==="

if [[ ! -e "$CURRENT_LINK" ]]; then
    echo "No pending restore link found. Nothing to do."
    exit 0
fi

PENDING_DIR="$(readlink -f "$CURRENT_LINK" 2>/dev/null || echo "$CURRENT_LINK")"
if [[ ! -d "$PENDING_DIR" ]]; then
    echo "Pending restore directory not found: $PENDING_DIR"
    rm -f "$CURRENT_LINK" >/dev/null 2>&1 || true
    exit 0
fi

APPLY_LIST="${PENDING_DIR}/apply-on-boot.list"
PLAN_ENV="${PENDING_DIR}/plan.env"
STATE_FILE="${PENDING_DIR}/state"

if [[ -f "$PLAN_ENV" ]]; then
    # shellcheck source=/dev/null
    source "$PLAN_ENV"
fi

: "${HB_RESTORE_INCLUDE_ZFS:=0}"

if [[ ! -f "$APPLY_LIST" ]]; then
    echo "Apply list missing: $APPLY_LIST"
    echo "failed" >"$STATE_FILE"
    exit 1
fi

echo "Pending dir: $PENDING_DIR"
echo "Apply list:  $APPLY_LIST"
echo "Include ZFS: $HB_RESTORE_INCLUDE_ZFS"
echo "running" >"$STATE_FILE"

backup_root="${PRE_BACKUP_BASE}/$(date +%Y%m%d_%H%M%S)-onboot"
mkdir -p "$backup_root" >/dev/null 2>&1 || true

cluster_recovery_root=""
applied=0
skipped=0
failed=0

while IFS= read -r rel; do
    [[ -z "$rel" ]] && continue

    src="${PENDING_DIR}/rootfs/${rel}"
    dst="${DEST_PREFIX%/}/${rel}"

    if [[ ! -e "$src" ]]; then
        ((skipped++))
        continue
    fi

    # Cluster data (/etc/pve, /var/lib/pve-cluster) goes into a
    # recovery dir for forensics/rollback, but unlike the live-
    # menu apply path we ALSO apply it for real here: at this
    # point in boot we're before networking.service, nothing is
    # talking to the cluster yet, so a `systemctl stop pve-cluster`
    # → copy → `systemctl start pve-cluster` is safe. This is the
    # whole reason the operator picked "schedule remaining for
    # next boot" instead of doing it live from SSH.
    if [[ "$rel" == etc/pve* ]] || [[ "$rel" == var/lib/pve-cluster* ]]; then
        if [[ -z "$cluster_recovery_root" ]]; then
            cluster_recovery_root="${RECOVERY_BASE}/$(date +%Y%m%d_%H%M%S)-onboot"
            mkdir -p "$cluster_recovery_root" >/dev/null 2>&1 || true
        fi
        mkdir -p "$cluster_recovery_root/$(dirname "$rel")" >/dev/null 2>&1 || true
        cp -a "$src" "$cluster_recovery_root/$rel" >/dev/null 2>&1 || true
        # Mark that we need to do the live apply at the end of
        # the loop (we don't want to stop/start pve-cluster
        # per-file — once is enough).
        cluster_live_apply=1
        ((skipped++))
        continue
    fi

    # /etc/zfs is opt-in.
    if [[ "$rel" == etc/zfs || "$rel" == etc/zfs/* ]]; then
        if [[ "$HB_RESTORE_INCLUDE_ZFS" != "1" ]]; then
            ((skipped++))
            continue
        fi
    fi

    if [[ -e "$dst" ]]; then
        mkdir -p "$backup_root/$(dirname "$rel")" >/dev/null 2>&1 || true
        cp -a "$dst" "$backup_root/$rel" >/dev/null 2>&1 || true
    fi

    if [[ -d "$src" ]]; then
        mkdir -p "$dst" >/dev/null 2>&1 || true
        if rsync -aAXH --delete "$src/" "$dst/" >/dev/null 2>&1; then
            ((applied++))
        else
            ((failed++))
        fi
    else
        mkdir -p "$(dirname "$dst")" >/dev/null 2>&1 || true
        if cp -a "$src" "$dst" >/dev/null 2>&1; then
            ((applied++))
        else
            ((failed++))
        fi
    fi
done <"$APPLY_LIST"

systemctl daemon-reload >/dev/null 2>&1 || true

# `update-initramfs -u -k all` and `update-grub` used to live here
# but: (a) they take 5-10 minutes for 3 kernels, hanging early-boot
# for that long, and (b) ifupdown2 was waiting on us. They now run
# AFTER pve-cluster is up via the apply_cluster_postboot.sh script
# we hook below, in the background where the user is already on the
# login prompt and using the system. Zero manual steps needed.

echo "Applied: $applied"
echo "Skipped: $skipped"
echo "Failed:  $failed"
echo "Backup before restore: $backup_root"

if [[ -n "$cluster_recovery_root" ]]; then
    # Always write the manual-helper script first — that's the
    # rollback path if the live apply below blows up.
    helper="${cluster_recovery_root}/apply-cluster-restore.sh"
    cat > "$helper" <<EOF
#!/bin/bash
set -euo pipefail

RECOVERY_ROOT="${cluster_recovery_root}"
echo "Cluster recovery helper"
echo "Source: \$RECOVERY_ROOT"
echo
echo "WARNING: run this only in a maintenance window."
echo
read -r -p "Type YES to continue: " ans
[[ "\$ans" == "YES" ]] || { echo "Aborted."; exit 1; }

systemctl stop pve-cluster || true
[[ -d "\$RECOVERY_ROOT/etc/pve" ]] && mkdir -p /etc/pve && cp -a "\$RECOVERY_ROOT/etc/pve/." /etc/pve/ || true
[[ -d "\$RECOVERY_ROOT/var/lib/pve-cluster" ]] && mkdir -p /var/lib/pve-cluster && cp -a "\$RECOVERY_ROOT/var/lib/pve-cluster/." /var/lib/pve-cluster/ || true
systemctl start pve-cluster || true
echo "Cluster recovery finished."
EOF
    chmod +x "$helper" >/dev/null 2>&1 || true

    echo "Cluster paths extracted to: $cluster_recovery_root"
    echo "Cluster recovery helper: $helper"

    # We DON'T auto-apply /etc/pve here at boot because early-boot
    # pve-cluster start blocks the unit (corosync etc. not ready).
    # Instead we hand off to a SECOND oneshot unit that fires
    # AFTER pve-cluster.service is up, when /etc/pve is the live
    # pmxcfs FUSE mount and we can write individual files to it
    # without restarting anything. That second unit is gated by
    # ConditionPathExists on the marker file we drop here, so on
    # a normal boot (no marker) it's a no-op.
    if [[ "${cluster_live_apply:-0}" == "1" ]]; then
        echo "Installing post-boot cluster apply unit..."

        # Decide whether the post-boot script needs to run
        # update-initramfs and/or update-grub by inspecting the
        # apply list. Skipping them when nothing relevant was
        # restored saves the operator 5-10 minutes of background
        # initramfs rebuilds on EVERY restore — only do it when
        # the backup actually touched paths that affect those
        # tools' inputs.
        NEEDS_INITRAMFS=0
        NEEDS_GRUB=0
        while IFS= read -r _rel; do
            case "$_rel" in
                etc/modules|etc/modules/*|\
                etc/modules-load.d|etc/modules-load.d/*|\
                etc/modprobe.d|etc/modprobe.d/*|\
                etc/initramfs-tools|etc/initramfs-tools/*|\
                etc/crypttab|\
                etc/cryptsetup-initramfs|etc/cryptsetup-initramfs/*)
                    NEEDS_INITRAMFS=1 ;;
                etc/default/grub|\
                etc/kernel|etc/kernel/*|\
                etc/grub.d|etc/grub.d/*)
                    NEEDS_GRUB=1 ;;
            esac
        done < "$APPLY_LIST"
        echo "Post-boot maintenance flags: initramfs=$NEEDS_INITRAMFS grub=$NEEDS_GRUB"

        # Marker as env-style key=value so the post-boot script
        # can `source` it and read structured fields.
        mkdir -p /var/lib/proxmenux >/dev/null 2>&1 || true
        {
            printf 'RECOVERY_ROOT=%s\n' "$cluster_recovery_root"
            printf 'PENDING_DIR=%s\n'   "$PENDING_DIR"
            printf 'NEEDS_INITRAMFS=%s\n' "$NEEDS_INITRAMFS"
            printf 'NEEDS_GRUB=%s\n'      "$NEEDS_GRUB"
        } > /var/lib/proxmenux/cluster-apply-pending
        chmod 600 /var/lib/proxmenux/cluster-apply-pending

        # Install the systemd unit. Idempotent: overwrite if it
        # already exists (so script changes get picked up).
        cat > /etc/systemd/system/proxmenux-apply-cluster-postboot.service <<UNITEOF
[Unit]
Description=ProxMenux Apply Cluster Configs (post-boot)
After=pve-cluster.service pveproxy.service network-online.target
Wants=pve-cluster.service
# Only fire on boots where pending_restore left us a marker.
# On every other boot, the condition fails and systemd skips
# us — zero overhead.
ConditionPathExists=/var/lib/proxmenux/cluster-apply-pending

[Service]
Type=oneshot
ExecStart=/usr/local/share/proxmenux/scripts/backup_restore/apply_cluster_postboot.sh
# 15-min cap to fit update-initramfs -u -k all (5-10 min for
# 3 kernels) + update-grub (~30s) on top of the (fast) cluster
# config apply. The unit runs AFTER pve-cluster is up so the
# user is already at the login prompt and using the system —
# this just chugs in the background.
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
UNITEOF

        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl enable proxmenux-apply-cluster-postboot.service >/dev/null 2>&1 || true

        # `systemctl enable` only adds the unit to multi-user.target.wants/.
        # It does NOT pull the unit into the currently-running boot
        # transaction — by the time we run, multi-user.target may have
        # already collected its wants. `start --no-block` schedules the
        # unit for activation respecting its After= ordering (pve-cluster
        # comes up first), without blocking apply_pending_restore.sh
        # itself. Without this, the postboot unit only fires on the
        # NEXT reboot, defeating the "single reboot, zero manual steps"
        # promise.
        systemctl start --no-block proxmenux-apply-cluster-postboot.service >/dev/null 2>&1 || true

        echo "Cluster apply will run automatically after pve-cluster comes up."
        echo "Fallback manual: bash $helper"
    fi
fi

if [[ "$failed" -eq 0 ]]; then
    echo "completed" >"$STATE_FILE"
else
    echo "completed_with_errors" >"$STATE_FILE"
fi

restore_id="$(basename "$PENDING_DIR")"
mv "$PENDING_DIR" "${PENDING_BASE}/completed/${restore_id}" >/dev/null 2>&1 || true
rm -f "$CURRENT_LINK" >/dev/null 2>&1 || true

systemctl disable proxmenux-restore-onboot.service >/dev/null 2>&1 || true

echo "=== ProxMenux pending restore finished at $(date -Iseconds) ==="
echo "Log file: $LOG_FILE"

exit 0
