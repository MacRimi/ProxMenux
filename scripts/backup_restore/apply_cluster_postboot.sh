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
# State file the Monitor Web polls to show a live progress card on
# the Backups tab. A dismiss action (POST /api/host-backups/restore/dismiss)
# just flips `acknowledged` to true — the file itself lives until the
# next restore overwrites it, and a copy is archived under history/
# when the run finishes so the operator can browse past restores.
STATE_DIR="/var/lib/proxmenux"
STATE_FILE="$STATE_DIR/restore-state.json"
HISTORY_DIR="$STATE_DIR/restore-history"
mkdir -p "$STATE_DIR" "$HISTORY_DIR" >/dev/null 2>&1 || true

mkdir -p "$LOG_DIR" >/dev/null 2>&1 || true
LOG_FILE="${LOG_DIR}/proxmenux-cluster-postboot-$(date +%Y%m%d_%H%M%S).log"
exec >>"$LOG_FILE" 2>&1

# Capture start epoch BEFORE any long-running step. The final duration
# is derived from this; the previous approach used stat -c %Y on the
# log file, which reads the last-write mtime — and since we `exec >>`
# to the log for the whole run, that mtime is always ~end-of-run and
# the duration came out as 0m00s.
POSTBOOT_START_EPOCH=$(date +%s)

# ── State-file helpers ─────────────────────────────────────────
# Every milestone advances `steps_done` and optionally updates a
# handful of other fields. Writes go through a temp file + rename
# so the Monitor never reads a half-written JSON. All calls are
# `|| true` at the callsite — if jq or write fails, the restore
# still proceeds; only the UI progress reporting suffers.
_state_started_at="$(date -Iseconds)"
_state_steps_total=0
_state_steps_done=0
_state_write() {
    # Merges a JSON snippet ($1) into the existing state file.
    # Missing state file → seeded from an empty JSON object first.
    command -v jq >/dev/null 2>&1 || return 0
    [[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"
    local tmp
    tmp=$(mktemp "${STATE_FILE}.XXXXXX") || return 0
    if jq -c ". * $1" "$STATE_FILE" > "$tmp" 2>/dev/null; then
        mv -f "$tmp" "$STATE_FILE"
    else
        rm -f "$tmp"
    fi
}
_state_step() {
    # Called as a *step transition*: the previous step just finished,
    # start the next one. Increments steps_done and sets the label to
    # $1. Init seeds current_step with the first step's label; every
    # _state_step call after that advances to the NEXT step.
    #
    # Example flow with 3 total steps:
    #   init         → steps_done=0, current_step="Applying cluster config"
    #   step "Foo"   → steps_done=1, current_step="Foo"
    #   step "Bar"   → steps_done=2, current_step="Bar"
    #   _state_finish→ steps_done=3, status="complete"
    local label="$1"
    _state_steps_done=$((_state_steps_done + 1))
    # jq variable names sdone/stotal — plain `done` collides with the
    # bash reserved word when the arg is on its own continuation line.
    _state_write "$(jq -n \
        --arg step "$label" \
        --argjson sdone "$_state_steps_done" \
        --argjson stotal "$_state_steps_total" \
        '{current_step:$step, steps_done:$sdone, steps_total:$stotal}')"
}
_state_component() {
    # Add or update an entry in state.components. Arrays are replaced
    # by jq's `*` merge, so plain _state_write can't be used for the
    # per-component list — this helper explicitly appends new entries
    # and updates existing ones by name.
    #   $1 = component name (nvidia_driver, coral_driver, …)
    #   $2 = status: installing | ok | failed
    #   $3 = per-component log path (empty allowed)
    #   $4 = installer exit code (only meaningful for failed; empty otherwise)
    command -v jq >/dev/null 2>&1 || return 0
    [[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"
    local tmp
    tmp=$(mktemp "${STATE_FILE}.XXXXXX") || return 0
    if jq -c \
        --arg name "$1" \
        --arg status "$2" \
        --arg log "$3" \
        --arg rc "${4:-}" \
        '($.components // []) as $comps
         | ($comps | map(.name) | index($name)) as $idx
         | ({name:$name, status:$status, log:$log}
            + (if $rc == "" then {} else {exit_code:$rc} end)) as $entry
         | .components =
             (if $idx == null then $comps + [$entry]
              else ($comps | map(if .name == $name then $entry else . end)) end)' \
        "$STATE_FILE" > "$tmp" 2>/dev/null; then
        mv -f "$tmp" "$STATE_FILE"
    else
        rm -f "$tmp"
    fi
}
_state_finish() {
    # $1 = "complete" | "failed"
    # Promotes steps_done to steps_total so the progress bar reads 100%
    # instead of freezing at whatever the last _state_step call left it
    # at (typically N-1 because "finalize" itself never gets its own
    # _state_step). Also relabels current_step so the card stops
    # showing the last in-flight step ("Boot sanity check") as if it
    # were still running.
    local final_status="$1"
    local final_label="Restore finished"
    [[ "$final_status" == "failed" ]] && final_label="Restore failed"
    _state_write "$(jq -n \
        --arg s "$final_status" \
        --arg t "$(date -Iseconds)" \
        --arg dur "${POSTBOOT_DURATION_FMT:-}" \
        --arg step "$final_label" \
        --argjson stotal "$_state_steps_total" \
        '{status:$s, finished_at:$t, duration:$dur, current_step:$step, steps_done:$stotal, steps_total:$stotal}')"
    # Archive a copy to history/ so past restores stay browsable
    # from the Monitor even after the operator dismisses the card.
    if [[ -f "$STATE_FILE" ]]; then
        cp -f "$STATE_FILE" "$HISTORY_DIR/$(date +%Y%m%d_%H%M%S)-${final_status}.json" 2>/dev/null || true
        # Keep the last 20 entries in the history dir. Everything
        # older is expected to have been reviewed already. Using
        # find+sort-by-mtime keeps this safe against odd filenames.
        find "$HISTORY_DIR" -maxdepth 1 -type f -name '*.json' -printf '%T@ %p\n' 2>/dev/null \
            | sort -rn | tail -n +21 | cut -d' ' -f2- | xargs -r rm -f 2>/dev/null || true
    fi
}

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

# Compute how many milestones the Monitor will see for this run.
# Base 3 = apply /etc/pve + boot sanity check + finalize. Add one
# for each optional phase that will actually run.
_state_steps_total=3
[[ "$NEEDS_INITRAMFS" == "1" ]] && _state_steps_total=$((_state_steps_total + 1))
[[ "$NEEDS_GRUB" == "1" ]] && _state_steps_total=$((_state_steps_total + 1))
# Count components that will be re-installed via --auto-reinstall.
# Read the same components_status.json the reinstall loop uses so
# our step count matches exactly what the loop will process.
_COMP_STATUS_PATH="/usr/local/share/proxmenux/components_status.json"
_COMPONENT_KEYS=(nvidia_driver amdgpu_top intel_gpu_tools coral_driver)
_comps_to_reinstall=0
if command -v jq >/dev/null 2>&1 && [[ -f "$_COMP_STATUS_PATH" ]]; then
    for _k in "${_COMPONENT_KEYS[@]}"; do
        [[ "$(jq -r ".$_k.status // \"\"" "$_COMP_STATUS_PATH" 2>/dev/null)" == "installed" ]] \
            && _comps_to_reinstall=$((_comps_to_reinstall + 1))
    done
fi
(( _comps_to_reinstall > 0 )) && _state_steps_total=$((_state_steps_total + _comps_to_reinstall))

# Seed the initial state file so the Monitor's poll sees the run
# almost immediately after the postboot unit starts. `acknowledged`
# false means the Backups tab card will show; the operator flips
# it to true (via POST /dismiss) after they've read the summary.
_state_write "$(jq -n \
    --arg started "$_state_started_at" \
    --arg log "$LOG_FILE" \
    --argjson steps "$_state_steps_total" \
    '{status:"running",
      started_at:$started,
      finished_at:null,
      current_step:"Applying cluster config",
      steps_done:0,
      steps_total:$steps,
      log_path:$log,
      components:[],
      rollback_delta:{},
      sanity_warnings:[],
      summary:null,
      acknowledged:false}')"

if [[ -z "$RECOVERY_ROOT" || ! -d "$RECOVERY_ROOT" ]]; then
    echo "Recovery root invalid — aborting cleanly."
    rm -f "$MARKER"
    _state_finish "failed" || true
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

# ── LXC bind-mount stub directories ───────────────────────
# LXC containers with `mp<n>: /path,mp=...` bind-mount entries fail the
# pre-start hook (status 2) if `/path` doesn't exist on the host. After a
# cross-host restore the source's bind-mount paths (custom NAS mounts, second
# disk paths, etc.) generally don't exist on the target's fresh install yet.
# We create empty stubs so `onboot: 1` containers start; the operator wires
# the real data source afterwards. PVE-managed storages (`/mnt/pve/*`) and
# /dev/* are skipped — PVE handles the first, kernel handles the second.
echo ""
echo "── LXC bind-mount stubs ──"
stub_created=0
stub_skipped=0
if compgen -G "/etc/pve/nodes/$CUR_NODE/lxc/*.conf" >/dev/null 2>&1; then
    for conf in /etc/pve/nodes/"$CUR_NODE"/lxc/*.conf; do
        [[ -f "$conf" ]] || continue
        while IFS= read -r line; do
            if [[ "$line" =~ ^mp[0-9]+:[[:space:]]*(/[^,]+), ]]; then
                src="${BASH_REMATCH[1]}"
                [[ "$src" == /mnt/pve/* ]] && continue
                [[ "$src" == /dev/* ]]    && continue
                if [[ -e "$src" ]]; then
                    ((stub_skipped++))
                    continue
                fi
                if mkdir -p "$src" 2>/dev/null; then
                    echo "  + stub $src  (from $(basename "$conf"))"
                    ((stub_created++))
                fi
            fi
        done < "$conf"
    done
fi
echo "Stubs: created=$stub_created, already-present=$stub_skipped"

# ── Stale node-dir cleanup ────────────────────────────────
# Fresh PVE install creates /etc/pve/nodes/<install-hostname>/. After our
# restore changes the hostname back to the source's, pve-cluster boots into
# the source's node dir but leaves the install-hostname dir orphaned. The
# web UI then shows a phantom offline node. Only remove dirs whose lxc/
# qemu-server/ are empty — never trample a real second cluster member.
echo ""
echo "── Stale node-dir cleanup ──"
removed_nodes=0
for nodedir in /etc/pve/nodes/*/; do
    n=$(basename "$nodedir")
    [[ "$n" == "$CUR_NODE" ]] && continue
    lxc_empty=1; qemu_empty=1
    [[ -d "$nodedir/lxc" ]] && [[ -n "$(ls -A "$nodedir/lxc"        2>/dev/null)" ]] && lxc_empty=0
    [[ -d "$nodedir/qemu-server" ]] && [[ -n "$(ls -A "$nodedir/qemu-server" 2>/dev/null)" ]] && qemu_empty=0
    if (( lxc_empty && qemu_empty )); then
        if rm -rf "$nodedir" 2>/dev/null; then
            echo "  ✓ removed stale node dir: $n"
            ((removed_nodes++))
        else
            echo "  ✗ rm failed for $n (pmxcfs may have it busy)"
        fi
    else
        echo "  ⚠ kept $n (has guest configs — looks like a real cluster member)"
    fi
done
echo "Stale node dirs removed: $removed_nodes"

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
    _state_step "Rebuilding initramfs" || true
    echo "Running: update-initramfs -u -k all  (5-10 min — restore touched initramfs inputs)"
    if update-initramfs -u -k all 2>&1 | tail -10; then
        echo "  ✓ update-initramfs done"
    else
        echo "  ✗ update-initramfs failed (system still boots; re-run manually)"
    fi
    if command -v proxmox-boot-tool >/dev/null 2>&1; then
        proxmox-boot-tool refresh 2>&1 | tail -3 || true
    fi
else
    echo "Skipping update-initramfs (restore didn't touch modules/initramfs-tools/crypttab)"
fi

if [[ "$NEEDS_GRUB" == "1" ]] && command -v update-grub >/dev/null 2>&1; then
    _state_step "Updating bootloader" || true
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
        _state_step "Reinstalling $comp" || true
        _state_component "$comp" "installing" "" ""
        # Redirect to a per-component log instead of piping. NVIDIA's
        # runfile installer forks helpers that inherit stdout, so a
        # `bash $installer | sed | tail` pipeline never sees EOF after
        # the parent exits and hangs until systemd kills the unit.
        comp_log="/var/log/proxmenux/component-${comp}-$(date +%Y%m%d_%H%M%S).log"
        bash "$installer" --auto-reinstall >"$comp_log" 2>&1
        rc=$?
        sed -e 's/^/    /' "$comp_log" | tail -15
        if (( rc == 0 )); then
            echo "  ✓ $comp ok  (full log: $comp_log)"
            _state_component "$comp" "ok" "$comp_log" ""
        else
            echo "  ✗ $comp installer exited $rc — see $comp_log"
            _state_component "$comp" "failed" "$comp_log" "$rc"
        fi
    done
fi

POSTBOOT_END_EPOCH=$(date +%s)
POSTBOOT_DURATION=$((POSTBOOT_END_EPOCH - POSTBOOT_START_EPOCH))
POSTBOOT_DURATION_FMT=$(printf '%dm%02ds' $((POSTBOOT_DURATION / 60)) $((POSTBOOT_DURATION % 60)))

# ── Rollback delta report (read-only) ──────────────────────────
# If _rs_prepare_pending_restore left a rollback.json in the
# pending dir, surface the deltas that a full rollback would
# touch: VMs/LXCs created after the backup that are still here,
# extra components not present in the backup. The operator
# decides what to do with them — we don't destroy guests or
# uninstall packages automatically (left to a future R2.D fase 2
# once every installer ships an --auto-uninstall mode).
ROLLBACK_PLAN_FILE=""
[[ -n "$PENDING_DIR" && -f "$PENDING_DIR/rollback.json" ]] && \
    ROLLBACK_PLAN_FILE="$PENDING_DIR/rollback.json"
if [[ -n "$ROLLBACK_PLAN_FILE" ]] && command -v jq >/dev/null 2>&1; then
    rb_vm_extras=$(jq -r '.vms_to_remove | join(", ") // ""' "$ROLLBACK_PLAN_FILE" 2>/dev/null)
    rb_lxc_extras=$(jq -r '.lxcs_to_remove | join(", ") // ""' "$ROLLBACK_PLAN_FILE" 2>/dev/null)
    rb_comp_extras=$(jq -r '.components_to_uninstall | join(", ") // ""' "$ROLLBACK_PLAN_FILE" 2>/dev/null)
    # Copy the structured plan into the state file so the Monitor's
    # detail modal can render each list as its own table without
    # re-parsing the CSV strings above.
    _state_write "$(jq -c '{rollback_delta:{
        vms_to_remove: (.vms_to_remove // []),
        lxcs_to_remove: (.lxcs_to_remove // []),
        components_to_uninstall: (.components_to_uninstall // [])
    }}' "$ROLLBACK_PLAN_FILE" 2>/dev/null)" || true
    if [[ -n "$rb_vm_extras" || -n "$rb_lxc_extras" || -n "$rb_comp_extras" ]]; then
        echo ""
        echo "── Rollback delta report ──"
        echo "These entries exist on the host but were NOT in the restored backup."
        echo "Review them and remove manually if a clean rollback is desired:"
        [[ -n "$rb_vm_extras"   ]] && echo "  • VMs   created after the backup: $rb_vm_extras"
        [[ -n "$rb_lxc_extras"  ]] && echo "  • LXCs  created after the backup: $rb_lxc_extras"
        [[ -n "$rb_comp_extras" ]] && echo "  • Components installed after the backup: $rb_comp_extras"
        echo ""
        echo "Manual cleanup commands (run only if you want to truly roll back):"
        for _id in $(echo "$rb_vm_extras" | tr ',' ' '); do
            [[ -n "$_id" ]] && echo "  qm stop $_id 2>/dev/null; qm destroy $_id --purge"
        done
        for _id in $(echo "$rb_lxc_extras" | tr ',' ' '); do
            [[ -n "$_id" ]] && echo "  pct stop $_id 2>/dev/null; pct destroy $_id --purge"
        done
    fi
fi

# ── Boot sanity check ──────────────────────────────────────────
# Cross-version restores are the most likely path to a broken
# boot: even with the safe-restore filter, catch situations where
# the default kernel has no matching /lib/modules, no ESP is
# configured, or a stale reference survived. Runs on every restore
# (cheap); warnings feed the completion notification so it tells
# the truth instead of a blanket "all fine".
_state_step "Boot sanity check" || true
SANITY_WARNINGS=""
_sanity_warn() {
    if [[ -z "$SANITY_WARNINGS" ]]; then
        SANITY_WARNINGS="$1"
    else
        SANITY_WARNINGS="${SANITY_WARNINGS}; $1"
    fi
}

if command -v proxmox-boot-tool >/dev/null 2>&1; then
    if ! proxmox-boot-tool status 2>/dev/null | grep -q 'configured with'; then
        _sanity_warn "proxmox-boot-tool reports no ESP configured"
    fi
fi

if [[ -d /boot ]]; then
    for _vmlinuz in /boot/vmlinuz-*; do
        [[ -e "$_vmlinuz" ]] || continue
        _kver="${_vmlinuz##*vmlinuz-}"
        if [[ ! -d "/lib/modules/$_kver" ]]; then
            _sanity_warn "kernel $_kver has no /lib/modules"
        fi
    done
fi

if [[ -L /vmlinuz && ! -e /vmlinuz ]]; then
    _sanity_warn "/vmlinuz symlink is dangling"
fi

if [[ -n "$SANITY_WARNINGS" ]]; then
    echo ""
    echo "── Boot sanity check ──"
    echo "$SANITY_WARNINGS"
    echo "Cross-version: ${HB_COMPAT_CROSS_VERSION:-0}"
fi

# Persist sanity warnings as a JSON array so the Monitor's detail
# modal can render each warning as its own line. Empty warnings →
# empty array, which the UI treats as "sanity OK".
if command -v jq >/dev/null 2>&1; then
    _state_write "$(jq -cn --arg s "$SANITY_WARNINGS" \
        '{sanity_warnings: (if $s == "" then [] else ($s | split("; ")) end)}')" || true
fi

# ── Notify ProxMenux Monitor that we're done ───────────────────
# Routes through the user's configured channels (Telegram, Discord,
# ntfy, etc.). Localhost-only endpoint, no auth needed. We try
# briefly — if the Monitor isn't running, just log and move on.
COMPONENTS_REINSTALLED_CSV=""
if command -v jq >/dev/null 2>&1 && [[ -f "$COMPONENTS_STATUS" ]]; then
    COMPONENTS_REINSTALLED_CSV=$(
        for entry in "${COMPONENT_INSTALLERS[@]}"; do
            comp="${entry%%:*}"
            s=$(jq -r ".${comp}.status // \"\"" "$COMPONENTS_STATUS" 2>/dev/null)
            [[ "$s" == "installed" ]] && printf '%s,' "$comp"
        done | sed 's/,$//'
    )
    [[ -z "$COMPONENTS_REINSTALLED_CSV" ]] && COMPONENTS_REINSTALLED_CSV="none"
fi

if command -v curl >/dev/null 2>&1; then
    # jq builds a proper JSON when available so SANITY_WARNINGS with
    # special chars can't break the payload. Falls back to printf on
    # hosts without jq — we already restrict SANITY_WARNINGS content
    # to plain ASCII in the sanity check above, so the fallback is
    # safe too.
    if command -v jq >/dev/null 2>&1; then
        PAYLOAD=$(jq -cn \
            --arg hostname    "$(hostname)" \
            --arg guests      "${copied_guests:-0}" \
            --arg stubs       "${stub_created:-0}" \
            --arg stale_nodes "${removed_nodes:-0}" \
            --arg components  "${COMPONENTS_REINSTALLED_CSV:-none}" \
            --arg duration    "$POSTBOOT_DURATION_FMT" \
            --arg warnings    "$SANITY_WARNINGS" \
            '{hostname:$hostname, guests:$guests, stubs:$stubs, stale_nodes:$stale_nodes, components:$components, duration:$duration, warnings:$warnings}')
    else
        PAYLOAD=$(printf '{"hostname":"%s","guests":"%s","stubs":"%s","stale_nodes":"%s","components":"%s","duration":"%s","warnings":"%s"}' \
            "$(hostname)" \
            "${copied_guests:-0}" \
            "${stub_created:-0}" \
            "${removed_nodes:-0}" \
            "${COMPONENTS_REINSTALLED_CSV:-none}" \
            "$POSTBOOT_DURATION_FMT" \
            "$SANITY_WARNINGS")
    fi
    NOTIFY_HTTP=$(curl -s -o /dev/null -w '%{http_code}' \
        -X POST "http://127.0.0.1:8008/api/internal/restore-event" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        --max-time 5 2>/dev/null || echo "000")
    if [[ "$NOTIFY_HTTP" == "200" ]]; then
        echo "Notification sent (HTTP 200)"
    else
        echo "Notification skipped (Monitor not reachable or disabled — HTTP $NOTIFY_HTTP)"
    fi
fi

# Persist a compact summary the Monitor's card can render inline.
# Mirrors what the notification block sends; keeps a single source
# of truth for both the alert channels and the Web UI.
if command -v jq >/dev/null 2>&1; then
    _state_write "$(jq -cn \
        --arg hostname    "$(hostname)" \
        --arg guests      "${copied_guests:-0}" \
        --arg stubs       "${stub_created:-0}" \
        --arg stale_nodes "${removed_nodes:-0}" \
        --arg components  "${COMPONENTS_REINSTALLED_CSV:-none}" \
        --arg duration    "$POSTBOOT_DURATION_FMT" \
        '{summary:{hostname:$hostname, guests:$guests, stubs:$stubs, stale_nodes:$stale_nodes, components:$components, duration:$duration}}')" || true
fi
_state_finish "complete" || true

echo ""
echo "=== Apply finished at $(date -Iseconds) — total ${POSTBOOT_DURATION_FMT} ==="
echo "Log: $LOG_FILE"
