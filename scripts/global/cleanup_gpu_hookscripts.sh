#!/bin/bash
# ==========================================================
# ProxMenux — Legacy gpu-guard hookscript auto-cleanup
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 28/05/2026
# ==========================================================
# Description:
# Earlier versions of ProxMenux attached the hookscript
# `<storage>:snippets/proxmenux-gpu-guard.sh` to VMs and LXC
# with GPU / PCIe passthrough to validate state at pre-start.
#
# That hookscript reference, baked into the guest .conf, made
# guests fail to start after backup/restore to any host that
# lacked the snippet file — a critical UX failure reported by
# users. The hookscript system has been removed.
#
# This script silently purges any leftover references from
# running and stopped guests, and removes the snippet file
# from every storage that may have it. Idempotent: safe to
# re-run; if nothing matches, exits silently.
#
# Trigger:
#   - Auto-executed by install_proxmenux.sh and
#     install_proxmenux_beta.sh on every install/update.
#   - Can also be run manually:
#       bash /usr/local/share/proxmenux/scripts/global/cleanup_gpu_hookscripts.sh
# ==========================================================

set -u

HOOK_FILENAME="proxmenux-gpu-guard.sh"

cleaned_vms=0
cleaned_cts=0
removed_files=0

# ----------------------------------------------------------
# 1. Strip the hookscript reference from every VM config
#    that points to proxmenux-gpu-guard.sh
#
#    `qm set --delete hookscript` works whether the VM is
#    running or stopped — Proxmox only edits the .conf
#    and the change takes effect on the next start.
# ----------------------------------------------------------
if command -v qm >/dev/null 2>&1; then
    for conf in /etc/pve/qemu-server/*.conf; do
        [[ -f "$conf" ]] || continue
        if grep -qE "^hookscript:.*${HOOK_FILENAME}" "$conf" 2>/dev/null; then
            vmid=$(basename "$conf" .conf)
            if qm set "$vmid" --delete hookscript >/dev/null 2>&1; then
                cleaned_vms=$((cleaned_vms + 1))
            fi
        fi
    done
fi

# ----------------------------------------------------------
# 2. Strip the hookscript reference from every LXC config
#    that points to proxmenux-gpu-guard.sh
# ----------------------------------------------------------
if command -v pct >/dev/null 2>&1; then
    for conf in /etc/pve/lxc/*.conf; do
        [[ -f "$conf" ]] || continue
        if grep -qE "^hookscript:.*${HOOK_FILENAME}" "$conf" 2>/dev/null; then
            ctid=$(basename "$conf" .conf)
            if pct set "$ctid" -delete hookscript >/dev/null 2>&1; then
                cleaned_cts=$((cleaned_cts + 1))
            fi
        fi
    done
fi

# ----------------------------------------------------------
# 3. Remove the snippet file from every storage that has it
#    Walks every active storage with content=snippets and
#    asks `pvesm path` for the absolute path. Handles local,
#    NFS, CIFS, directory storages, etc.
# ----------------------------------------------------------
if command -v pvesm >/dev/null 2>&1; then
    while IFS= read -r storage; do
        [[ -z "$storage" ]] && continue
        snippet_path=$(pvesm path "${storage}:snippets/${HOOK_FILENAME}" 2>/dev/null)
        if [[ -n "$snippet_path" && -f "$snippet_path" ]]; then
            rm -f "$snippet_path" 2>/dev/null && removed_files=$((removed_files + 1))
        fi
    done < <(pvesm status -content snippets 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')
fi

# ----------------------------------------------------------
# 4. Fallback removal for known conventional paths (covers
#    cases where pvesm doesn't list the storage or the file
#    was placed by an older script via a hard-coded path).
# ----------------------------------------------------------
shopt -s nullglob
for legacy in /var/lib/vz/snippets/${HOOK_FILENAME} /mnt/pve/*/snippets/${HOOK_FILENAME}; do
    [[ -f "$legacy" ]] && rm -f "$legacy" 2>/dev/null && removed_files=$((removed_files + 1))
done
shopt -u nullglob

# ----------------------------------------------------------
# 5. Quiet summary on stderr — visible in the install log
#    and in interactive runs, but doesn't pollute STDOUT
#    when invoked from another script's pipeline.
# ----------------------------------------------------------
if [[ "$cleaned_vms" -gt 0 || "$cleaned_cts" -gt 0 || "$removed_files" -gt 0 ]]; then
    echo "[proxmenux-cleanup] Removed legacy gpu-guard hookscript from ${cleaned_vms} VM(s), ${cleaned_cts} LXC(s); deleted ${removed_files} snippet file(s)." >&2
fi

exit 0
