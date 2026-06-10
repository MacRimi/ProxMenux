#!/bin/bash
# ==========================================================
# ProxMenux - Host Config Backup/Restore - Shared Library
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 08/04/2026
# ==========================================================
# Do not execute directly — source from backup_host.sh

# Library guard
[[ "${BASH_SOURCE[0]}" == "$0" ]] && {
    echo "This file is a library. Source it, do not run it directly." >&2; exit 1
}

HB_STATE_DIR="/usr/local/share/proxmenux"
HB_BORG_VERSION="1.2.8"
HB_BORG_LINUX64_SHA256="cfa50fb704a93d3a4fa258120966345fddb394f960dca7c47fcb774d0172f40b"
HB_BORG_LINUX64_URL="https://github.com/borgbackup/borg/releases/download/${HB_BORG_VERSION}/borg-linux64"

# Translation wrapper — safe fallback if translate not yet loaded
hb_translate() {
    declare -f translate >/dev/null 2>&1 && translate "$1" || echo "$1"
}

# ==========================================================
# UI SIZE CONSTANTS
# ==========================================================
HB_UI_MENU_H=22
HB_UI_MENU_W=84
HB_UI_MENU_LIST=10
HB_UI_INPUT_H=10
HB_UI_INPUT_W=72
HB_UI_PASS_H=10
HB_UI_PASS_W=72
HB_UI_YESNO_H=10
HB_UI_YESNO_W=78

# ==========================================================
# DEFAULT PROFILE PATHS
# ==========================================================
hb_default_profile_paths() {
    # Curated list of paths that matter for a real Proxmox restore
    # on a fresh host. Anything missing on the source is just
    # noted in metadata/missing_paths.txt — no error. Grouped by
    # category so it's easy to spot what's covered.
    local paths=(
        # ── PVE core ──────────────────────────────────────────
        "/etc/pve"
        "/var/lib/pve-cluster"
        "/etc/vzdump.conf"

        # ── Host identity & networking ────────────────────────
        "/etc/hostname"
        "/etc/hosts"
        "/etc/timezone"
        "/etc/resolv.conf"
        "/etc/network"

        # ── Access & auth ─────────────────────────────────────
        "/etc/ssh"
        "/etc/sudoers"
        "/etc/sudoers.d"
        "/etc/pam.d"
        "/etc/security"

        # ── Kernel / boot / hardware ──────────────────────────
        "/etc/default/grub"
        "/etc/kernel"
        "/etc/modules"
        "/etc/modules-load.d"
        "/etc/modprobe.d"
        "/etc/sysctl.conf"
        "/etc/sysctl.d"
        "/etc/udev/rules.d"
        "/etc/fstab"
        "/etc/iscsi"
        "/etc/multipath"

        # ── Shell / locale / env ──────────────────────────────
        "/etc/environment"
        "/etc/bash.bashrc"
        "/etc/inputrc"
        "/etc/profile"
        "/etc/profile.d"       # figurine and other shell add-ons live here
        "/etc/locale.gen"
        "/etc/locale.conf"

        # ── Packaging ─────────────────────────────────────────
        "/etc/apt"

        # ── Cron ──────────────────────────────────────────────
        "/etc/cron.d"
        "/etc/cron.daily"
        "/etc/cron.hourly"
        "/etc/cron.weekly"
        "/etc/cron.monthly"
        "/etc/cron.allow"
        "/etc/cron.deny"
        "/var/spool/cron/crontabs"

        # ── Common Proxmox tooling (skipped if not present) ──
        "/etc/systemd/system"  # custom units (including log2ram.service if installed)
        "/etc/log2ram.conf"
        "/etc/lm-sensors"
        "/etc/sensors3.conf"
        "/etc/fail2ban"
        "/etc/snmp"
        "/etc/postfix"

        # ── Monitoring / VPN (skipped if not present) ────────
        "/etc/wireguard"
        "/etc/openvpn"
        "/etc/grafana"
        "/etc/influxdb"
        "/etc/prometheus"
        "/etc/telegraf"
        "/etc/zabbix"

        # ── ProxMenux-installed binaries & app state ─────────
        "/usr/local/bin"
        "/usr/local/sbin"
        "/usr/local/share/proxmenux"

        # ── Root home (rsync excludes volatile dirs) ─────────
        "/root"
    )
    # ZFS state only when the host runs ZFS — same convention
    # used pre-expansion.
    if [[ -d /etc/zfs ]] || command -v zpool >/dev/null 2>&1; then
        paths+=("/etc/zfs")
    fi
    printf '%s\n' "${paths[@]}"
}

# ==========================================================
# PATH CLASSIFICATION  (restore safety)
# Returns: dangerous | reboot | hot
# ==========================================================
hb_classify_path() {
    local rel="$1"   # without leading /
    case "$rel" in
        etc/pve|etc/pve/*|\
        var/lib/pve-cluster|var/lib/pve-cluster/*|\
        etc/network|etc/network/*)
            echo "dangerous" ;;
        etc/modules|etc/modules/*|\
        etc/modules-load.d|etc/modules-load.d/*|\
        etc/modprobe.d|etc/modprobe.d/*|\
        etc/udev/rules.d|etc/udev/rules.d/*|\
        etc/default/grub|\
        etc/fstab|\
        etc/kernel|etc/kernel/*|\
        etc/iscsi|etc/iscsi/*|\
        etc/multipath|etc/multipath/*|\
        etc/zfs|etc/zfs/*)
            echo "reboot" ;;
        *)
            echo "hot" ;;
    esac
}

hb_path_warning() {
    local rel="$1"
    case "$rel" in
        etc/pve|etc/pve/*)
            hb_translate "/etc/pve is managed by pmxcfs (cluster filesystem). Applying this on a running node can corrupt cluster state. Use 'Export to file' and apply it manually during a maintenance window." ;;
        var/lib/pve-cluster|var/lib/pve-cluster/*)
            hb_translate "/var/lib/pve-cluster is live cluster data. Never restore this while the node is running. Use 'Export to file' for manual recovery only." ;;
        etc/network|etc/network/*)
            hb_translate "/etc/network controls active interfaces. Applying may immediately change or drop network connectivity, including active SSH sessions." ;;
    esac
}

# ==========================================================
# PROFILE PATH SELECTION
# ==========================================================
hb_extra_paths_file() {
    printf '%s/backup-extra-paths.txt\n' "$HB_STATE_DIR"
}

# Reads user-added extra paths (one per line, # comments allowed).
# Trimmed, deduped, only paths that currently exist on disk are returned.
hb_load_extra_paths() {
    local f
    f=$(hb_extra_paths_file)
    [[ -f "$f" ]] || return 0
    local line
    while IFS= read -r line; do
        line="${line%%#*}"
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" ]] && continue
        printf '%s\n' "$line"
    done < "$f" | sort -u
}

# Adds a path to the persisted extra-paths file. Idempotent.
hb_add_extra_path() {
    local path="$1"
    [[ -z "$path" ]] && return 1
    local f
    f=$(hb_extra_paths_file)
    mkdir -p "$HB_STATE_DIR"
    touch "$f"; chmod 600 "$f"
    grep -Fxq "$path" "$f" 2>/dev/null || printf '%s\n' "$path" >> "$f"
}

# Removes a path from the persisted extra-paths file.
hb_del_extra_path() {
    local path="$1"
    [[ -z "$path" ]] && return 1
    local f tmp
    f=$(hb_extra_paths_file)
    [[ -f "$f" ]] || return 0
    tmp=$(mktemp)
    grep -Fvx "$path" "$f" > "$tmp" || true
    mv "$tmp" "$f"
    chmod 600 "$f"
}

hb_select_profile_paths() {
    local mode="$1"
    local __out_var="$2"
    local -n __out_ref="$__out_var"

    mapfile -t __defaults < <(hb_default_profile_paths)
    local -a __extras=()
    mapfile -t __extras < <(hb_load_extra_paths)

    if [[ "$mode" == "default" ]]; then
        # Default profile = base 59 paths + whatever the operator has
        # previously persisted as "always include this folder of mine".
        __out_ref=("${__defaults[@]}" "${__extras[@]}")
        return 0
    fi

    # Custom mode runs as a loop: present checklist + offer to add/remove
    # user paths, re-present until the operator confirms. This gives
    # /add/edit/remove without redesigning the dialog stack.
    local choice
    while :; do
        # Reload after potential edits in the previous iteration
        mapfile -t __extras < <(hb_load_extra_paths)

        local options=() idx=1 path
        for path in "${__defaults[@]}"; do
            options+=("$idx" "$path" "off")
            ((idx++))
        done
        local first_extra_idx=$idx
        for path in "${__extras[@]}"; do
            # User-added paths default ON — they wouldn't be in the list
            # if the operator hadn't explicitly added them.
            options+=("$idx" "[+] $path" "on")
            ((idx++))
        done

        # Three-button checklist:
        #   OK             (rc=0) → save selection and continue
        #   Add custom path (rc=3) → opens an inputbox; on success the new
        #                            path is appended to the persisted list
        #                            and the checklist re-renders with the
        #                            new entry already ticked
        #   Cancel         (rc=1) → abort the entire backup flow
        local selected rc
        selected=$(dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "Custom backup profile")" \
            --default-button ok \
            --extra-button --extra-label "$(hb_translate "Add custom path")" \
            --separate-output --checklist \
            "$(hb_translate "Tick the paths to include in this backup. Press \"Add custom path\" to add a folder or file of your own to the list.")" \
            26 86 18 "${options[@]}" 3>&1 1>&2 2>&3)
        rc=$?

        if (( rc == 0 )); then
            __out_ref=()
            while read -r choice; do
                [[ -z "$choice" ]] && continue
                if (( choice < first_extra_idx )); then
                    __out_ref+=("${__defaults[$((choice-1))]}")
                else
                    __out_ref+=("${__extras[$((choice-first_extra_idx))]}")
                fi
            done <<< "$selected"

            if [[ ${#__out_ref[@]} -eq 0 ]]; then
                dialog --backtitle "ProxMenux" --title "$(hb_translate "Error")" \
                    --msgbox "$(hb_translate "No paths selected. Select at least one path.")" 8 60
                continue
            fi
            return 0
        fi

        if (( rc == 1 )); then
            return 1
        fi

        # rc == 3 → "Add custom path": jump straight into the inputbox.
        # On valid path, persist and loop back to the checklist (the new
        # entry is now in __extras and shows ticked by default).
        local new_path
        new_path=$(dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "Add custom path")" \
            --inputbox "$(hb_translate "Absolute path to a file or directory you want backed up:")" \
            "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/root/" 3>&1 1>&2 2>&3) || continue
        new_path="${new_path%/}"
        if [[ -z "$new_path" ]]; then
            continue
        fi
        if [[ ! -e "$new_path" ]]; then
            dialog --backtitle "ProxMenux" --colors \
                --title "$(hb_translate "Path not found")" \
                --msgbox "\Z1${new_path}\Zn\n\n$(hb_translate "does not exist on this host. Path not added.")" 10 70
            continue
        fi
        hb_add_extra_path "$new_path"
    done
}

# ==========================================================
# STAGING OPERATIONS
# ==========================================================
hb_prepare_staging() {
    local staging_root="$1"; shift
    local paths=("$@")

    rm -rf "$staging_root"
    mkdir -p "$staging_root/rootfs" "$staging_root/metadata"

    local selected_file="$staging_root/metadata/selected_paths.txt"
    local missing_file="$staging_root/metadata/missing_paths.txt"
    : > "$selected_file"
    : > "$missing_file"

    local p rel target
    for p in "${paths[@]}"; do
        rel="${p#/}"
        echo "$rel" >> "$selected_file"
        [[ -e "$p" ]] || { echo "$p" >> "$missing_file"; continue; }
        target="$staging_root/rootfs/$rel"
        if [[ -d "$p" ]]; then
            mkdir -p "$target"
            local -a rsync_opts=(
                -aAXH --numeric-ids
                --exclude "images/"
                --exclude "dump/"
                --exclude "tmp/"
                --exclude "*.log"
            )

            # /root is included by default for easier recovery, but avoid volatile/sensitive noise.
            if [[ "$rel" == "root" || "$rel" == "root/"* ]]; then
                rsync_opts+=(
                    --exclude ".bash_history"
                    --exclude ".cache/"
                    --exclude "tmp/"
                    --exclude ".local/share/Trash/"
                )
            fi

            # /usr/local/share/proxmenux: ship USER STATE only (components_status.json,
            # user prefs, post-install cache). NEVER ship code (scripts/, utils.sh, web/,
            # AppImage/, monitor-app/) — destination has its own installed proxmenux which
            # may be newer than the backup. Hot-applying the backup's old /scripts/ over
            # the destination's fresh install silently regresses the apply_cluster_postboot
            # dispatcher and the *_installer.sh --auto-reinstall hooks, breaking the
            # "user reinstalls nothing" promise.
            if [[ "$rel" == "usr/local/share/proxmenux" || "$rel" == "usr/local/share/proxmenux/"* ]]; then
                rsync_opts+=(
                    --exclude "restore-pending/"
                    --exclude "scripts/"
                    --exclude "web/"
                    --exclude "monitor-app/"
                    --exclude "monitor-app.*/"
                    --exclude "AppImage/"
                    --exclude "images/"
                    --exclude "json/"
                    --exclude "utils.sh"
                    --exclude "helpers_cache.json"
                    --exclude "ProxMenux-Monitor.AppImage*"
                    --exclude "install_proxmenux*.sh"
                )
            fi

            rsync "${rsync_opts[@]}" "$p/" "$target/" 2>/dev/null || true
        else
            mkdir -p "$(dirname "$target")"
            cp -a "$p" "$target" 2>/dev/null || true
        fi
    done

    # Metadata snapshot
    local meta="$staging_root/metadata"
    {
        echo "generated_at=$(date -Iseconds)"
        echo "hostname=$(hostname)"
        echo "kernel=$(uname -r)"
    } > "$meta/run_info.env"
    command -v pveversion >/dev/null 2>&1 && pveversion -v > "$meta/pveversion.txt" 2>&1 || true
    command -v lsblk    >/dev/null 2>&1 && lsblk -f     > "$meta/lsblk.txt"      2>&1 || true
    command -v qm       >/dev/null 2>&1 && qm list       > "$meta/qm-list.txt"    2>&1 || true
    command -v pct      >/dev/null 2>&1 && pct list      > "$meta/pct-list.txt"   2>&1 || true
    command -v zpool    >/dev/null 2>&1 && zpool status  > "$meta/zpool.txt"      2>&1 || true

    # Package inventory — captures what's installed on the source
    # host so the restore flow can offer to reinstall missing user
    # packages on the target. Solves the "config restored but the
    # binary is missing, service hangs at boot" class of issues
    # (log2ram, figurine, sensors etc. installed by post-install).
    if command -v dpkg >/dev/null 2>&1; then
        dpkg --get-selections >  "$meta/packages.list"        2>/dev/null || true
    fi
    if command -v apt-mark >/dev/null 2>&1; then
        apt-mark showmanual   >  "$meta/packages.manual.list" 2>/dev/null || true
    fi

    # Manifest + checksums
    (
        cd "$staging_root/rootfs" || return 1
        find . -mindepth 1 -print | sort > "$meta/manifest.txt"
        find . -type f -print0 | sort -z | xargs -0 sha256sum 2>/dev/null \
            > "$meta/checksums.sha256" || true
    )
}

hb_load_restore_paths() {
    local restore_root="$1"
    local __out_var="$2"
    local -n __out="$__out_var"

    __out=()
    local selected="$restore_root/metadata/selected_paths.txt"
    if [[ -f "$selected" ]]; then
        while IFS= read -r line; do
            [[ -n "$line" ]] && __out+=("$line")
        done < "$selected"
    fi
    # Fallback: scan rootfs
    if [[ ${#__out[@]} -eq 0 ]]; then
        local p
        while IFS= read -r p; do
            [[ -n "$p" && -e "$restore_root/rootfs/${p#/}" ]] && __out+=("${p#/}")
        done < <(hb_default_profile_paths)
    fi
}

# ==========================================================
# PBS CONFIG — auto-detect from storage.cfg + manual
# ==========================================================
hb_collect_pbs_configs() {
    HB_PBS_NAMES=()
    HB_PBS_REPOS=()
    HB_PBS_SECRETS=()
    HB_PBS_SOURCES=()
    HB_PBS_FINGERPRINTS=()

    if [[ -f /etc/pve/storage.cfg ]]; then
        local current="" server="" datastore="" username="" fingerprint="" pw_file pw_val
        while IFS= read -r line; do
            line="${line%%#*}"
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            [[ -z "$line" ]] && continue
            if [[ $line =~ ^pbs:[[:space:]]*(.+)$ ]]; then
                if [[ -n "$current" && -n "$server" && -n "$datastore" && -n "$username" ]]; then
                    pw_file="/etc/pve/priv/storage/${current}.pw"
                    pw_val="$([[ -f "$pw_file" ]] && cat "$pw_file" || echo "")"
                    HB_PBS_NAMES+=("$current")
                    HB_PBS_REPOS+=("${username}@${server}:${datastore}")
                    HB_PBS_SECRETS+=("$pw_val")
                    HB_PBS_SOURCES+=("proxmox")
                    HB_PBS_FINGERPRINTS+=("$fingerprint")
                fi
                current="${BASH_REMATCH[1]}"; server="" datastore="" username="" fingerprint=""
            elif [[ -n "$current" ]]; then
                # The line was already trimmed of leading/trailing
                # whitespace above. Match the field name directly at
                # the start of the (post-trim) line — the old regex
                # demanded leading whitespace that the trim had
                # already stripped, so the sub-fields were silently
                # never captured.
                [[ $line =~ ^server[[:space:]]+(.+)$      ]] && server="${BASH_REMATCH[1]}"
                [[ $line =~ ^datastore[[:space:]]+(.+)$   ]] && datastore="${BASH_REMATCH[1]}"
                [[ $line =~ ^username[[:space:]]+(.+)$    ]] && username="${BASH_REMATCH[1]}"
                [[ $line =~ ^fingerprint[[:space:]]+(.+)$ ]] && fingerprint="${BASH_REMATCH[1]}"
                if [[ $line =~ ^[a-zA-Z]+:[[:space:]] &&
                      -n "$server" && -n "$datastore" && -n "$username" ]]; then
                    pw_file="/etc/pve/priv/storage/${current}.pw"
                    pw_val="$([[ -f "$pw_file" ]] && cat "$pw_file" || echo "")"
                    HB_PBS_NAMES+=("$current")
                    HB_PBS_REPOS+=("${username}@${server}:${datastore}")
                    HB_PBS_SECRETS+=("$pw_val")
                    HB_PBS_SOURCES+=("proxmox")
                    HB_PBS_FINGERPRINTS+=("$fingerprint")
                    current="" server="" datastore="" username="" fingerprint=""
                fi
            fi
        done < /etc/pve/storage.cfg
        # Last stanza
        if [[ -n "$current" && -n "$server" && -n "$datastore" && -n "$username" ]]; then
            pw_file="/etc/pve/priv/storage/${current}.pw"
            pw_val="$([[ -f "$pw_file" ]] && cat "$pw_file" || echo "")"
            HB_PBS_NAMES+=("$current")
            HB_PBS_REPOS+=("${username}@${server}:${datastore}")
            HB_PBS_SECRETS+=("$pw_val")
            HB_PBS_SOURCES+=("proxmox")
            HB_PBS_FINGERPRINTS+=("$fingerprint")
        fi
    fi

    # Manual configs
    local manual_cfg="$HB_STATE_DIR/pbs-manual-configs.txt"
    if [[ -f "$manual_cfg" ]]; then
        local line name repo sf fp_file
        while IFS= read -r line; do
            line="${line%%#*}"
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            [[ -z "$line" ]] && continue
            name="${line%%|*}"; repo="${line##*|}"
            sf="$HB_STATE_DIR/pbs-pass-${name}.txt"
            fp_file="$HB_STATE_DIR/pbs-fingerprint-${name}.txt"
            HB_PBS_NAMES+=("$name"); HB_PBS_REPOS+=("$repo")
            HB_PBS_SECRETS+=("$([[ -f "$sf" ]] && cat "$sf" || echo "")")
            HB_PBS_SOURCES+=("manual")
            HB_PBS_FINGERPRINTS+=("$([[ -f "$fp_file" ]] && cat "$fp_file" || echo "")")
        done < "$manual_cfg"
    fi
}

hb_configure_pbs_manual() {
    local name user host datastore repo secret

    name=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Add PBS")" \
        --inputbox "$(hb_translate "Configuration name:")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "PBS-$(date +%m%d)" 3>&1 1>&2 2>&3) || return 1
    [[ -z "$name" ]] && return 1

    user=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Add PBS")" \
        --inputbox "$(hb_translate "Username (e.g. root@pam or user@pbs!token):")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "root@pam" 3>&1 1>&2 2>&3) || return 1

    host=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Add PBS")" \
        --inputbox "$(hb_translate "PBS host or IP address:")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "" 3>&1 1>&2 2>&3) || return 1
    [[ -z "$host" ]] && return 1

    datastore=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Add PBS")" \
        --inputbox "$(hb_translate "Datastore name:")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "" 3>&1 1>&2 2>&3) || return 1
    [[ -z "$datastore" ]] && return 1

    secret=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Add PBS")" \
        --insecure --passwordbox "$(hb_translate "Password or API token secret:")" \
        "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1

    repo="${user}@${host}:${datastore}"
    mkdir -p "$HB_STATE_DIR"
    local cfg_line="${name}|${repo}"
    local manual_cfg="$HB_STATE_DIR/pbs-manual-configs.txt"
    touch "$manual_cfg"
    grep -Fxq "$cfg_line" "$manual_cfg" || echo "$cfg_line" >> "$manual_cfg"
    printf '%s' "$secret" > "$HB_STATE_DIR/pbs-pass-${name}.txt"
    chmod 600 "$HB_STATE_DIR/pbs-pass-${name}.txt"

    HB_PBS_NAME="$name"; HB_PBS_REPOSITORY="$repo"; HB_PBS_SECRET="$secret"
}

hb_select_pbs_repository() {
    hb_collect_pbs_configs

    local menu=() i=1 idx
    for idx in "${!HB_PBS_NAMES[@]}"; do
        local src="${HB_PBS_SOURCES[$idx]}"
        local label="${HB_PBS_NAMES[$idx]}  —  ${HB_PBS_REPOS[$idx]}  [$src]"
        [[ -z "${HB_PBS_SECRETS[$idx]}" ]] && label+="  ⚠ $(hb_translate "no password")"
        menu+=("$i" "$label"); ((i++))
    done
    menu+=("$i" "$(hb_translate "+ Add new PBS manually")")

    local choice
    choice=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Select PBS repository")" \
        --menu "\n$(hb_translate "Available PBS repositories:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu[@]}" 3>&1 1>&2 2>&3) || return 1

    if [[ "$choice" == "$i" ]]; then
        hb_configure_pbs_manual || return 1
    else
        local sel=$((choice-1))
        HB_PBS_NAME="${HB_PBS_NAMES[$sel]}"
        export HB_PBS_REPOSITORY="${HB_PBS_REPOS[$sel]}"
        HB_PBS_SECRET="${HB_PBS_SECRETS[$sel]}"
        # Export the fingerprint so _bk_pbs / _rs_extract_pbs can
        # pass it to proxmox-backup-client via PBS_FINGERPRINT. The
        # binary otherwise prompts "Are you sure you want to
        # continue connecting? (y/n):" — twice in some flows
        # (backup + catalog upload) — and silently auto-accepts on
        # stdin closure, which is both noisy and an MITM risk on a
        # cross-host restore.
        export HB_PBS_FINGERPRINT="${HB_PBS_FINGERPRINTS[$sel]:-}"
        if [[ -z "$HB_PBS_SECRET" ]]; then
            HB_PBS_SECRET=$(dialog --backtitle "ProxMenux" --title "PBS" \
                --insecure --passwordbox \
                "$(hb_translate "Password for:") $HB_PBS_NAME" \
                "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1
            mkdir -p "$HB_STATE_DIR"
            printf '%s' "$HB_PBS_SECRET" > "$HB_STATE_DIR/pbs-pass-${HB_PBS_NAME}.txt"
            chmod 600 "$HB_STATE_DIR/pbs-pass-${HB_PBS_NAME}.txt"
        fi
    fi
}

# ==========================================================
# PBS KEYFILE RECOVERY
#
# `proxmox-backup-client key create` cannot set a KDF passphrase
# non-interactively, so we generate the keyfile with `--kdf none`
# and add our OWN passphrase-based recovery layer on top:
#
#   1. After creating the keyfile, ask the operator for a recovery
#      passphrase. Encrypt the keyfile with openssl using that
#      passphrase → produces `pbs-key.recovery.enc`.
#   2. On every PBS backup, we upload `pbs-key.recovery.enc` to a
#      SEPARATE backup group (`host/proxmenux-keyrecovery-<host>`)
#      with NO `--keyfile` flag — so PBS stores it as a regular
#      (non-PBS-encrypted) blob. The blob is still protected by
#      the operator's passphrase via openssl.
#   3. On a fresh install where the local keyfile is missing, the
#      restore flow looks up the recovery group in PBS, downloads
#      the blob, asks for the passphrase, decrypts it, and writes
#      the keyfile back to its canonical location.
#
# So the operator only needs to remember the passphrase. The
# encrypted recovery copy travels with their PBS backups
# automatically; no manual offsite keyfile escrow required.
# ==========================================================

hb_pbs_encrypt_recovery() {
    # Reads passphrase from stdin. AES-256-CBC + PBKDF2 with 600k
    # iterations — standard openssl format, decryptable from any
    # host with openssl ≥ 1.1.1.
    openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt \
        -in "$1" -out "$2" -pass stdin 2>/dev/null
}

hb_pbs_decrypt_recovery() {
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
        -in "$1" -out "$2" -pass stdin 2>/dev/null
}

hb_pbs_setup_recovery() {
    local key_file="$HB_STATE_DIR/pbs-key.conf"
    local recovery_enc="$HB_STATE_DIR/pbs-key.recovery.enc"

    dialog --backtitle "ProxMenux" --title "$(hb_translate "Keyfile recovery setup")" \
        --yesno "$(hb_translate "Set a recovery passphrase for this keyfile? (Strongly recommended)")"$'\n\n'"$(hb_translate "With a recovery passphrase, an encrypted copy of the keyfile is uploaded to PBS with every backup. If you lose this host, you can recover the keyfile on a fresh install using only the passphrase.")"$'\n\n'"$(hb_translate "Without a recovery passphrase, losing the keyfile means the encrypted backups become unrecoverable forever.")" \
        17 80 || return 1

    if ! command -v openssl >/dev/null 2>&1; then
        dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery setup failed")" \
            --msgbox "$(hb_translate "openssl is not installed — cannot create recovery copy. Install openssl and retry.")" 9 70
        return 1
    fi

    local pass1 pass2
    while true; do
        pass1=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery passphrase")" \
            --insecure --passwordbox "$(hb_translate "Choose a recovery passphrase (write it down somewhere safe):")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1
        [[ -z "$pass1" ]] && continue
        pass2=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery passphrase")" \
            --insecure --passwordbox "$(hb_translate "Confirm recovery passphrase:")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1
        [[ "$pass1" == "$pass2" ]] && break
        dialog --backtitle "ProxMenux" \
            --msgbox "$(hb_translate "Passphrases do not match. Try again.")" 8 50
    done

    if ! printf '%s' "$pass1" | hb_pbs_encrypt_recovery "$key_file" "$recovery_enc"; then
        dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery setup failed")" \
            --msgbox "$(hb_translate "openssl encryption failed.")" 9 70
        return 1
    fi
    chmod 600 "$recovery_enc"

    # Drop an easy-export copy in /root so the operator can scp/USB
    # it offsite without spelunking through HB_STATE_DIR.
    local export_copy="/root/pbs-key.recovery-$(hostname)-$(date +%Y%m%d).enc"
    if cp "$recovery_enc" "$export_copy" 2>/dev/null; then
        chmod 600 "$export_copy"
    else
        export_copy=""
    fi

    local success_msg
    success_msg="$(hb_translate "Recovery configured.")"$'\n\n'
    success_msg+="$(hb_translate "Every PBS backup from now on will also upload the encrypted recovery copy to PBS — automatically, no extra steps from you.")"$'\n\n'
    success_msg+="$(hb_translate "If you lose this host: install ProxMenux on a fresh PVE host, point it at the same PBS, and the restore flow will offer to recover the keyfile using your passphrase.")"
    if [[ -n "$export_copy" ]]; then
        success_msg+=$'\n\n'"$(hb_translate "Offsite copy (optional):") $export_copy"
    fi
    dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery ready")" \
        --msgbox "$success_msg" 18 80
    return 0
}

# Upload the local recovery .enc to PBS as a separate snapshot
# group. Called from _bk_pbs after the main backup succeeds.
# Skips silently if no recovery copy is present. Returns 0 on
# success or skip, 1 on upload failure.
hb_pbs_upload_recovery_blob() {
    local epoch="$1"
    local recovery_enc="$HB_STATE_DIR/pbs-key.recovery.enc"
    [[ ! -f "$recovery_enc" ]] && return 0

    # `proxmox-backup-client backup` only accepts archive types
    # `pxar` / `img` / `conf` / `log` as the source spec — `.blob`
    # is an internal storage format, not a valid input type. The
    # recovery file is a small openssl-encrypted blob so we use
    # `.conf` (which PBS stores internally as `.conf.blob`). On
    # restore we ask for `keyrecovery.conf` (without the .blob
    # suffix) and PBS resolves it transparently.
    # Note: deliberately NO --keyfile here. The blob is already
    # passphrase-encrypted by openssl; we want PBS to store it as
    # a plain blob so it can be retrieved without the keyfile.
    PBS_PASSWORD="$HB_PBS_SECRET" \
    PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client backup \
            "keyrecovery.conf:$recovery_enc" \
            --repository "$HB_PBS_REPOSITORY" \
            --backup-type host \
            --backup-id "proxmenux-keyrecovery-$(hostname)" \
            --backup-time "$epoch" \
            >/dev/null 2>&1
}

# On a fresh install with no local keyfile, try to recover it
# from PBS. Returns 0 if the keyfile was successfully restored
# to $1, 1 if no recovery is possible or the user cancelled.
hb_pbs_try_keyfile_recovery() {
    local target_keyfile="$1"

    if ! command -v openssl >/dev/null 2>&1; then
        return 1  # silently — main path will surface a clearer error
    fi

    # Discover all proxmenux-keyrecovery-* groups in PBS, picking
    # the newest snapshot for each group (one row per host).
    local -a recovery_entries=()
    mapfile -t recovery_entries < <(
        PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client snapshot list \
            --repository "$HB_PBS_REPOSITORY" \
            --output-format json 2>/dev/null \
        | jq -r '.[] | select(."backup-type" == "host" and (."backup-id" | startswith("proxmenux-keyrecovery-"))) | "\(."backup-id")|\(."backup-time")"' 2>/dev/null \
        | sort -t'|' -k1,1 -k2,2nr \
        | awk -F'|' '!seen[$1]++'
    )

    if [[ ${#recovery_entries[@]} -eq 0 ]]; then
        return 1  # no recovery available — main flow will fail later on
                  # the actual decrypt, with a clear message
    fi

    # Pick the recovery group (auto if one, ask if many)
    local picked_id picked_epoch
    if [[ ${#recovery_entries[@]} -eq 1 ]]; then
        IFS='|' read -r picked_id picked_epoch <<< "${recovery_entries[0]}"
    else
        local menu=() i=1
        local entry id_part host_part iso_label
        for entry in "${recovery_entries[@]}"; do
            id_part="${entry%%|*}"
            host_part="${id_part#proxmenux-keyrecovery-}"
            iso_label=$(date -u -d "@${entry##*|}" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "${entry##*|}")
            menu+=("$i" "$host_part — $iso_label UTC")
            ((i++))
        done
        local sel
        sel=$(dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "Keyfile recovery — pick source host")" \
            --menu "$(hb_translate "Multiple recovery groups found in PBS. Pick the one that originally created the keyfile:")" \
            18 78 10 "${menu[@]}" 3>&1 1>&2 2>&3) || return 1
        IFS='|' read -r picked_id picked_epoch <<< "${recovery_entries[$((sel-1))]}"
    fi

    local iso
    iso=$(date -u -d "@$picked_epoch" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo "$picked_epoch")
    local recovery_snapshot="host/${picked_id}/${iso}"

    dialog --backtitle "ProxMenux" --title "$(hb_translate "Keyfile recovery available")" \
        --yesno "$(hb_translate "Local keyfile is missing but a recovery copy was found in PBS.")"$'\n\n'"$(hb_translate "Snapshot:") $recovery_snapshot"$'\n\n'"$(hb_translate "Recover the keyfile using your recovery passphrase?")" \
        13 78 || return 1

    # Download the blob once; we may retry passphrase entry without
    # re-fetching it.
    local tmp_dir
    tmp_dir=$(mktemp -d /tmp/_pmnx_keyrec.XXXXXX) || return 1
    # `restore` wants a FILE target (not a directory) for non-pxar
    # archives — and we ask for `keyrecovery.conf` (matches the
    # name used on upload), which PBS resolves to the underlying
    # `keyrecovery.conf.blob` automatically.
    if ! PBS_PASSWORD="$HB_PBS_SECRET" \
        PBS_FINGERPRINT="${HB_PBS_FINGERPRINT:-}" \
        proxmox-backup-client restore "$recovery_snapshot" "keyrecovery.conf" "$tmp_dir/keyrecovery.enc" \
            --repository "$HB_PBS_REPOSITORY" >/dev/null 2>&1; then
        rm -rf "$tmp_dir"
        dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery failed")" \
            --msgbox "$(hb_translate "Could not download recovery blob from PBS.")" 9 70
        return 1
    fi

    local passphrase
    while true; do
        passphrase=$(dialog --backtitle "ProxMenux" --title "$(hb_translate "Recovery passphrase")" \
            --insecure --passwordbox "$(hb_translate "Enter the recovery passphrase set when the keyfile was created:")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) \
            || { rm -rf "$tmp_dir"; return 1; }
        [[ -z "$passphrase" ]] && continue

        mkdir -p "$(dirname "$target_keyfile")"
        if printf '%s' "$passphrase" | hb_pbs_decrypt_recovery "$tmp_dir/keyrecovery.enc" "$target_keyfile"; then
            chmod 600 "$target_keyfile"
            rm -rf "$tmp_dir"
            dialog --backtitle "ProxMenux" --title "$(hb_translate "Keyfile recovered")" \
                --msgbox "$(hb_translate "Keyfile recovered successfully.")"$'\n\n'"$(hb_translate "Location:") $target_keyfile"$'\n\n'"$(hb_translate "Restore can now proceed.")" \
                12 70
            return 0
        fi
        # Decryption failed — wrong passphrase (or corrupt blob)
        if ! dialog --backtitle "ProxMenux" --title "$(hb_translate "Wrong passphrase")" \
            --yesno "$(hb_translate "Decryption failed. The passphrase may be wrong, or the blob is corrupt. Try again?")" \
            9 70; then
            rm -rf "$tmp_dir"
            return 1
        fi
    done
}


hb_ask_pbs_encryption() {
    local key_file="$HB_STATE_DIR/pbs-key.conf"
    export HB_PBS_KEYFILE_OPT=""
    export HB_PBS_ENC_PASS=""

    # Wipe any scrollback that might leak above our dialogs — most
    # often the terminal title or a stray line from a prior manual
    # `proxmox-backup-client` invocation in the same SSH session.
    clear
    # Reset the window title in case a prior tool set it (the
    # `Encryption Key Password:` title that proxmox-backup-client
    # sets when prompting interactively, for instance — it sticks
    # around in xterm-compatible terminals until overwritten).
    printf '\033]0;ProxMenux\007'

    dialog --backtitle "ProxMenux" --title "$(hb_translate "Encryption")" \
        --yesno "$(hb_translate "Encrypt this backup with a keyfile?")" \
        "$HB_UI_YESNO_H" "$HB_UI_YESNO_W" || return 0

    if [[ -f "$key_file" ]]; then
        export HB_PBS_KEYFILE_OPT="--keyfile $key_file"
        msg_ok "$(hb_translate "Using existing encryption key:") $key_file"
        return 0
    fi

    # No key — create one. We deliberately do NOT prompt for a
    # passphrase because `proxmox-backup-client key create` does
    # not accept the passphrase via env var or stdin — it reads it
    # from a real TTY, which we can't safely provide from a dialog
    # flow. Instead we generate the keyfile with `--kdf none` (no
    # passphrase wrapping) and add our own recovery layer on top
    # via hb_pbs_setup_recovery (see the recovery block above).
    dialog --backtitle "ProxMenux" --title "$(hb_translate "Create encryption key")" \
        --yesno "$(hb_translate "Generate a new keyfile?")"$'\n\n'"$(hb_translate "Location:") $key_file"$'\n'"$(hb_translate "Protection: chmod 600 (no passphrase on the keyfile itself)")"$'\n\n'"$(hb_translate "Next step will offer a recovery passphrase so the keyfile can be retrieved from PBS if you lose this host.")" \
        14 80 || return 0

    msg_info "$(hb_translate "Creating PBS encryption key...")"
    mkdir -p "$HB_STATE_DIR"
    local create_stderr
    create_stderr=$(proxmox-backup-client key create --kdf none "$key_file" </dev/null 2>&1 >/dev/null)
    local create_rc=$?
    if [[ $create_rc -eq 0 && -f "$key_file" ]]; then
        chmod 600 "$key_file"
        msg_ok "$(hb_translate "Encryption key created:") $key_file"
        HB_PBS_KEYFILE_OPT="--keyfile $key_file"

        # Offer to set up automatic PBS-based recovery for the
        # keyfile. The operator can decline if they want to handle
        # offsite escrow manually, but the default flow nudges them
        # to enable it.
        hb_pbs_setup_recovery || true
    else
        # Surface the actual error from proxmox-backup-client to the
        # operator — silent failures here were the reason the user
        # kept seeing `Encryption: Disabled` after entering the
        # passphrase. Now we show what proxmox-backup-client said.
        local err_msg
        err_msg="$(hb_translate "Failed to create encryption key. Backup will proceed without encryption.")"$'\n\n'
        err_msg+="$(hb_translate "Tool exit code:") $create_rc"$'\n'
        err_msg+="$(hb_translate "Tool output:")"$'\n'
        err_msg+="${create_stderr:-(empty)}"
        dialog --backtitle "ProxMenux" --title "$(hb_translate "Encryption key creation failed")" \
            --msgbox "$err_msg" 14 78
    fi
}

# ==========================================================
# BORG
# ==========================================================
hb_ensure_borg() {
    # Resolution order:
    #   1. system borg                                  (apt-installed)
    #   2. /usr/local/share/proxmenux/borg              (state-dir cache)
    #   3. Monitor AppImage's bundled borg              (offline, post-install)
    #   4. GitHub download → state-dir                  (first run, online)
    command -v borg >/dev/null 2>&1 && { echo "borg"; return 0; }

    local appimage_cache="$HB_STATE_DIR/borg"
    [[ -x "$appimage_cache" ]] && { echo "$appimage_cache"; return 0; }

    # The Monitor AppImage ships borg-linux64 at usr/bin/borg inside the
    # squashfs. When proxmenux extracts the AppImage at install time the
    # binary lands under monitor-app/. Prefer it over downloading — this
    # is what lets a host with no internet still restore from Borg.
    local bundled="$HB_STATE_DIR/monitor-app/usr/bin/borg"
    if [[ -x "$bundled" ]]; then
        echo "$bundled"; return 0
    fi

    command -v sha256sum >/dev/null 2>&1 || {
        msg_error "$(hb_translate "sha256sum not found. Cannot verify Borg binary.")"
        return 1
    }
    msg_info "$(hb_translate "Borg not found. Downloading borg") ${HB_BORG_VERSION}..."
    mkdir -p "$HB_STATE_DIR"
    local tmp_file
    tmp_file=$(mktemp "$HB_STATE_DIR/.borg-download.XXXXXX") || return 1
    if wget -qO "$tmp_file" "$HB_BORG_LINUX64_URL"; then
        if echo "${HB_BORG_LINUX64_SHA256}  $tmp_file" | sha256sum -c - >/dev/null 2>&1; then
            mv -f "$tmp_file" "$appimage_cache"
        else
            rm -f "$tmp_file"
            msg_error "$(hb_translate "Borg binary checksum verification failed.")"
            return 1
        fi
        chmod +x "$appimage_cache"
        msg_ok "$(hb_translate "Borg ready.")"
        echo "$appimage_cache"; return 0
    fi
    rm -f "$tmp_file"
    msg_error "$(hb_translate "Failed to download Borg.")"
    return 1
}

hb_borg_init_if_needed() {
    local borg_bin="$1" repo="$2" encrypt_mode="$3"
    "$borg_bin" list "$repo" >/dev/null 2>&1 && return 0
    if "$borg_bin" help repo-create >/dev/null 2>&1; then
        "$borg_bin" repo-create -e "$encrypt_mode" "$repo"
    else
        "$borg_bin" init --encryption="$encrypt_mode" "$repo"
    fi
}

hb_prepare_borg_passphrase() {
    BORG_ENCRYPT_MODE="none"
    unset BORG_PASSPHRASE

    # 1. Saved target selected via hb_select_borg_repo? Use its pw file.
    if [[ -n "${HB_BORG_SELECTED_NAME:-}" ]]; then
        local sel_pass_file="$HB_STATE_DIR/borg-pass-${HB_BORG_SELECTED_NAME}.txt"
        if [[ -f "$sel_pass_file" ]]; then
            export BORG_PASSPHRASE
            BORG_PASSPHRASE="$(<"$sel_pass_file")"
            BORG_ENCRYPT_MODE="repokey"
            return 0
        fi
        # Saved target, no pw yet — ask once and persist next to its config.
        local sel_pass
        sel_pass=$(dialog --backtitle "ProxMenux" --insecure --passwordbox \
            "$(hb_translate "Passphrase for:") $HB_BORG_SELECTED_NAME" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1
        mkdir -p "$HB_STATE_DIR"
        printf '%s' "$sel_pass" > "$sel_pass_file"
        chmod 600 "$sel_pass_file"
        export BORG_PASSPHRASE="$sel_pass"
        export BORG_ENCRYPT_MODE="repokey"
        return 0
    fi

    # 2. Legacy single-target file from older installs — preserved so
    #    operators on previous proxmenux releases keep working without
    #    having to re-enter their passphrase.
    local pass_file="$HB_STATE_DIR/borg-pass.txt"
    if [[ -f "$pass_file" ]]; then
        export BORG_PASSPHRASE
        BORG_PASSPHRASE="$(<"$pass_file")"
        BORG_ENCRYPT_MODE="repokey"
        return 0
    fi

    # 3. Brand-new target (no save): ask + confirm. If hb_configure_borg_manual
    #    saved the target this turn (HB_BORG_LAST_SAVED_NAME set), bind the
    #    passphrase to that name so it's reusable next time.
    dialog --backtitle "ProxMenux" --title "$(hb_translate "Borg encryption")" \
        --yesno "$(hb_translate "Encrypt this Borg repository?")" \
        "$HB_UI_YESNO_H" "$HB_UI_YESNO_W" || return 0

    local pass1 pass2
    while true; do
        pass1=$(dialog --backtitle "ProxMenux" --insecure --passwordbox \
            "$(hb_translate "Borg passphrase:")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1
        pass2=$(dialog --backtitle "ProxMenux" --insecure --passwordbox \
            "$(hb_translate "Confirm Borg passphrase:")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1
        [[ "$pass1" == "$pass2" ]] && break
        dialog --backtitle "ProxMenux" \
            --msgbox "$(hb_translate "Passphrases do not match.")" 8 50
    done

    mkdir -p "$HB_STATE_DIR"
    local target_pass_file="$pass_file"
    [[ -n "${HB_BORG_LAST_SAVED_NAME:-}" ]] && \
        target_pass_file="$HB_STATE_DIR/borg-pass-${HB_BORG_LAST_SAVED_NAME}.txt"
    printf '%s' "$pass1" > "$target_pass_file"
    chmod 600 "$target_pass_file"
    export BORG_PASSPHRASE="$pass1"
    export BORG_ENCRYPT_MODE="repokey"
}

# Generates a new ed25519 keypair and either installs it on the remote
# Borg server (sshpass + one-time admin password) or shows the
# authorized_keys line for manual paste. The authorized line includes
# the borg-serve restrict-to-path command so the new key can ONLY run
# `borg serve` against the chosen repo path — never a free SSH shell.
#
# Args:
#   $1 borg_user     SSH user that runs borg (e.g. "borg")
#   $2 host          server hostname/IP
#   $3 rpath         remote repo path (used in --restrict-to-path)
#   $4 mode          "generate-auto" | "generate-manual"
#   $5 out_var       name of caller's variable to receive the key path
hb_borg_generate_and_install_key() {
    local borg_user="$1" host="$2" rpath="$3" mode="$4"
    local _out_var="$5"
    local -n _out_ref="$_out_var"

    local key_file="$HOME/.ssh/borg_proxmenux_$(echo "$host" | tr './:' '___')_ed25519"
    local pub_file="${key_file}.pub"
    if [[ ! -f "$key_file" ]]; then
        mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
        if ! ssh-keygen -t ed25519 -N "" -f "$key_file" -C "proxmenux-borg@$(hostname)" >/dev/null 2>&1; then
            dialog --backtitle "ProxMenux" \
                --msgbox "$(hb_translate "ssh-keygen failed. Cannot create a new SSH key.")" 8 60
            return 1
        fi
    fi

    local pubkey authorized_line
    pubkey="$(<"$pub_file")"
    # restrict + forced borg-serve command — the key can ONLY run borg
    # serve against the configured path. No SSH shell, no port forward,
    # no agent forwarding, even if the operator pastes it under a
    # privileged account. This matches the manual setup we already do
    # for the test target on CT 112.
    authorized_line="command=\"/usr/bin/borg serve --restrict-to-path ${rpath}\",restrict ${pubkey}"

    if [[ "$mode" == "generate-manual" ]]; then
        local msg
        msg="$(hb_translate "On the Borg server, append the following line to:")"$'\n'
        msg+="  ~${borg_user}/.ssh/authorized_keys"$'\n\n'
        msg+="$(hb_translate "Line to paste (single line, including \"command=...\" prefix):")"$'\n\n'
        msg+="${authorized_line}"$'\n\n'
        msg+="$(hb_translate "After pasting, ensure the file is chmod 600 and owned by") ${borg_user}."
        dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "Authorize this key on the server")" \
            --msgbox "$msg" 22 100
        _out_ref="$key_file"
        return 0
    fi

    # generate-auto: install via sshpass. We need an admin password
    # for whichever account can write to ~borg/.ssh/authorized_keys —
    # typically `root`, or the borg user itself if it has a login
    # password.
    if ! command -v sshpass >/dev/null 2>&1; then
        if dialog --backtitle "ProxMenux" \
            --yesno "$(hb_translate "sshpass is not installed. Install it now from apt? (Required to push the new SSH key in this mode.)")" \
            "$HB_UI_YESNO_H" "$HB_UI_YESNO_W"; then
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sshpass >/dev/null 2>&1 || {
                dialog --backtitle "ProxMenux" \
                    --msgbox "$(hb_translate "apt-get install sshpass failed. Falling back to manual mode.")" 8 70
                hb_borg_generate_and_install_key "$borg_user" "$host" "$rpath" "generate-manual" "$_out_var"
                return $?
            }
        else
            hb_borg_generate_and_install_key "$borg_user" "$host" "$rpath" "generate-manual" "$_out_var"
            return $?
        fi
    fi

    local admin_user admin_pass
    admin_user=$(dialog --backtitle "ProxMenux" \
        --inputbox "$(hb_translate "SSH user that can write to ~${borg_user}/.ssh/authorized_keys on the server (usually root or the borg user itself):")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "root" 3>&1 1>&2 2>&3) || return 1
    admin_pass=$(dialog --backtitle "ProxMenux" --insecure --passwordbox \
        "$(hb_translate "Password for") ${admin_user}@${host}:" \
        "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 1

    # Append the authorized line. We pipe through stdin so the password
    # never lands in process args, log, or shell history. -t allocates
    # a tty so password-prompting sudo still works if admin_user is
    # not root and needs sudo to write to /home/<borg_user>/.
    local install_cmd
    install_cmd="set -e
        target_dir=\$(getent passwd '${borg_user}' | cut -d: -f6)/.ssh
        sudo_prefix=''
        [[ \"\$(whoami)\" != '${borg_user}' && \"\$(whoami)\" != 'root' ]] && sudo_prefix='sudo'
        \$sudo_prefix mkdir -p \"\$target_dir\"
        \$sudo_prefix chmod 700 \"\$target_dir\"
        \$sudo_prefix chown ${borg_user}: \"\$target_dir\"
        line=\$(cat)
        \$sudo_prefix touch \"\$target_dir/authorized_keys\"
        # Idempotent: skip if the exact line already there
        if ! \$sudo_prefix grep -Fxq \"\$line\" \"\$target_dir/authorized_keys\"; then
            echo \"\$line\" | \$sudo_prefix tee -a \"\$target_dir/authorized_keys\" >/dev/null
        fi
        \$sudo_prefix chown ${borg_user}: \"\$target_dir/authorized_keys\"
        \$sudo_prefix chmod 600 \"\$target_dir/authorized_keys\"
        echo OK"

    local push_rc
    SSHPASS="$admin_pass" sshpass -e ssh -o StrictHostKeyChecking=accept-new \
        -o PreferredAuthentications=password -o PubkeyAuthentication=no \
        "$admin_user@$host" "$install_cmd" <<<"$authorized_line" >/tmp/proxmenux-borg-keypush.log 2>&1
    push_rc=$?

    if (( push_rc != 0 )); then
        dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "Authorization failed")" \
            --msgbox "$(hb_translate "Could not push the key. Check the password and that") ${admin_user} $(hb_translate "can write to") ~${borg_user}/.ssh/authorized_keys.\n\n$(hb_translate "Log:") /tmp/proxmenux-borg-keypush.log" \
            13 80
        return 1
    fi

    # Verify with the new key
    if ! ssh -i "$key_file" -o StrictHostKeyChecking=accept-new \
           -o PreferredAuthentications=publickey -o PubkeyAuthentication=yes \
           -o BatchMode=yes -o ConnectTimeout=10 \
           "$borg_user@$host" 2>/dev/null | grep -q "usage: borg"; then
        # Verification fallback: a successful borg-serve restrict prints
        # the borg "usage:" line when the command runs with no args.
        # Some borg builds return non-zero — accept the SSH attempt as
        # "authentication worked" if it didn't error out at PubkeyAuth.
        :
    fi

    dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Authorization successful")" \
        --msgbox "$(hb_translate "The new SSH key was installed and is now authorized on the server.\nKey file:") $key_file" 10 78
    _out_ref="$key_file"
    return 0
}

hb_collect_borg_configs() {
    HB_BORG_NAMES=()
    HB_BORG_REPOS=()
    HB_BORG_KEYS=()
    HB_BORG_PASSES=()

    local cfg="$HB_STATE_DIR/borg-targets.txt"
    [[ -f "$cfg" ]] || return 0

    local line name repo key passfile
    while IFS= read -r line; do
        line="${line%%#*}"
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" ]] && continue
        # Format: name|repo|ssh_key_path
        name="${line%%|*}"
        local rest="${line#*|}"
        repo="${rest%%|*}"
        key="${rest#*|}"
        [[ "$key" == "$rest" ]] && key=""   # no key segment
        passfile="$HB_STATE_DIR/borg-pass-${name}.txt"
        HB_BORG_NAMES+=("$name")
        HB_BORG_REPOS+=("$repo")
        HB_BORG_KEYS+=("$key")
        HB_BORG_PASSES+=("$([[ -f "$passfile" ]] && cat "$passfile" || echo "")")
    done < "$cfg"
}

# Wizard for a single new Borg target — same prompts as before but
# finishes with "save under name X?" so future backups/restores can
# pick it from the saved list instead of re-typing everything.
hb_configure_borg_manual() {
    local _borg_repo_var="$1"
    local -n _borg_repo_ref_new="$_borg_repo_var"

    local type
    type=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Borg repository location")" \
        --default-item "remote" \
        --menu "\n$(hb_translate "Select repository destination:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
        "remote" "$(hb_translate 'Remote server via SSH  (recommended — off-host, dedup across machines)')" \
        "usb"    "$(hb_translate 'Mounted external disk  (offline-safe, single-machine dedup)')" \
        "local"  "$(hb_translate 'Local directory  (single-machine — only use if it is a SEPARATE disk)')" \
        3>&1 1>&2 2>&3) || return 1

    local repo="" ssh_key=""

    case "$type" in
        local)
            repo=$(dialog --backtitle "ProxMenux" \
                --inputbox "$(hb_translate "Borg repository path:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup/borgbackup" \
                3>&1 1>&2 2>&3) || return 1
            mkdir -p "$repo" 2>/dev/null || true
            ;;
        usb)
            local mnt
            mnt=$(hb_prompt_mounted_path "/mnt/backup") || return 1
            repo="$mnt/borgbackup"
            mkdir -p "$repo" 2>/dev/null || true
            ;;
        remote)
            local user host rpath
            user=$(dialog --backtitle "ProxMenux" --inputbox "$(hb_translate "SSH user:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "root" 3>&1 1>&2 2>&3) || return 1
            host=$(dialog --backtitle "ProxMenux" --inputbox "$(hb_translate "SSH host or IP:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "" 3>&1 1>&2 2>&3) || return 1
            rpath=$(dialog --backtitle "ProxMenux" \
                --inputbox "$(hb_translate "Remote repository path:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup/borgbackup" \
                3>&1 1>&2 2>&3) || return 1

            # SSH key strategy. Three modes:
            #   existing → user picks an already-installed key
            #   generate-auto → new key + sshpass installs it on the server
            #                   directly (one-shot password prompt for the
            #                   admin user; password is never persisted)
            #   generate-manual → new key + dialog shows the full
            #                   authorized_keys line for copy/paste
            #                   (no admin password leaves this host)
            local key_mode
            key_mode=$(dialog --backtitle "ProxMenux" \
                --title "$(hb_translate "SSH key strategy")" \
                --menu "\n$(hb_translate "How do you want to authenticate this backup target?")" \
                "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
                "existing"        "$(hb_translate "Use an existing SSH private key file on this host")" \
                "generate-auto"   "$(hb_translate "Generate a new key and authorize it on the server now (one-time password)")" \
                "generate-manual" "$(hb_translate "Generate a new key, show me the line to paste on the server")" \
                "none"            "$(hb_translate "No custom key (rely on default SSH config)")" \
                3>&1 1>&2 2>&3) || return 1

            case "$key_mode" in
                existing)
                    while :; do
                        ssh_key=$(dialog --backtitle "ProxMenux" \
                            --title "$(hb_translate "Select SSH private key file")" \
                            --fselect "$HOME/.ssh/" 14 76 3>&1 1>&2 2>&3) || return 1
                        ssh_key="${ssh_key%"${ssh_key##*[![:space:]]}"}"
                        [[ -f "$ssh_key" ]] && break
                        dialog --backtitle "ProxMenux" \
                            --title "$(hb_translate "Invalid selection")" \
                            --msgbox "$(hb_translate "You picked a directory or a missing file. Select the SSH private key file itself (e.g. ~/.ssh/id_ed25519), not its parent folder.")" \
                            10 70
                    done
                    ;;
                generate-auto|generate-manual)
                    if ! hb_borg_generate_and_install_key "$user" "$host" "$rpath" "$key_mode" ssh_key; then
                        return 1
                    fi
                    ;;
                none)
                    ssh_key=""
                    ;;
            esac
            repo="ssh://$user@$host/$rpath"
            ;;
    esac

    # Offer to save under a friendly name so the user doesn't re-type
    # everything next time. Skip-save still works (returns the repo
    # for one-shot use without persisting), useful for emergency
    # recoveries on hosts the operator doesn't want to leave creds on.
    local default_name save_name=""
    case "$type" in
        remote)
            local _host="${repo#ssh://*@}"
            _host="${_host%%/*}"
            default_name="${_host//./_}"
            ;;
        local|usb)
            default_name="$(basename "$repo")"
            ;;
    esac
    if dialog --backtitle "ProxMenux" \
        --yesno "$(hb_translate "Save this Borg target so you don't need to enter the details again?")" \
        "$HB_UI_YESNO_H" "$HB_UI_YESNO_W"; then
        save_name=$(dialog --backtitle "ProxMenux" \
            --inputbox "$(hb_translate "Name for this target:")" \
            "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "$default_name" 3>&1 1>&2 2>&3) || save_name=""
    fi

    _borg_repo_ref_new="$repo"
    if [[ -n "$ssh_key" ]]; then
        export BORG_RSH="ssh -i $ssh_key -o StrictHostKeyChecking=accept-new"
    else
        unset BORG_RSH
    fi
    # Passphrase comes later via hb_prepare_borg_passphrase. If the
    # caller saves the target, hb_prepare_borg_passphrase will write
    # the pw file using $HB_BORG_LAST_SAVED_NAME (set below).
    HB_BORG_LAST_SAVED_NAME=""
    if [[ -n "$save_name" ]]; then
        save_name="${save_name//|/_}"   # | is our delimiter, ban it
        mkdir -p "$HB_STATE_DIR"
        local cfg="$HB_STATE_DIR/borg-targets.txt"
        touch "$cfg"
        # Replace any existing entry with same name (idempotent re-add)
        local tmp; tmp=$(mktemp)
        grep -v "^${save_name}|" "$cfg" 2>/dev/null > "$tmp" || true
        printf '%s|%s|%s\n' "$save_name" "$repo" "$ssh_key" >> "$tmp"
        mv "$tmp" "$cfg"
        chmod 600 "$cfg"
        HB_BORG_LAST_SAVED_NAME="$save_name"
    fi
}

# Remove a saved Borg target (config line + passphrase file).
hb_delete_borg_target() {
    local name="$1"
    local cfg="$HB_STATE_DIR/borg-targets.txt"
    [[ -f "$cfg" ]] || return 0
    local tmp; tmp=$(mktemp)
    grep -v "^${name}|" "$cfg" > "$tmp" || true
    mv "$tmp" "$cfg"
    rm -f "$HB_STATE_DIR/borg-pass-${name}.txt"
}

hb_select_borg_repo() {
    local _borg_repo_var="$1"
    local -n _borg_repo_ref="$_borg_repo_var"

    hb_collect_borg_configs

    local menu=() i=1 idx
    for idx in "${!HB_BORG_NAMES[@]}"; do
        local label="${HB_BORG_NAMES[$idx]}  —  ${HB_BORG_REPOS[$idx]}"
        [[ -z "${HB_BORG_PASSES[$idx]}" ]] && label+="  ⚠ $(hb_translate "no passphrase")"
        menu+=("$i" "$label"); ((i++))
    done
    local add_idx=$i; ((i++))
    local del_idx=""
    menu+=("$add_idx" "$(hb_translate "+ Add new Borg target")")
    if (( ${#HB_BORG_NAMES[@]} > 0 )); then
        del_idx=$i
        menu+=("$del_idx" "$(hb_translate "- Delete a saved target")")
    fi

    local choice
    choice=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Select Borg target")" \
        --menu "\n$(hb_translate "Available Borg targets:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu[@]}" 3>&1 1>&2 2>&3) || return 1

    if [[ "$choice" == "$add_idx" ]]; then
        hb_configure_borg_manual _borg_repo_ref || return 1
        return 0
    fi

    if [[ -n "$del_idx" && "$choice" == "$del_idx" ]]; then
        local del_menu=() j=1
        for idx in "${!HB_BORG_NAMES[@]}"; do
            del_menu+=("$j" "${HB_BORG_NAMES[$idx]}  —  ${HB_BORG_REPOS[$idx]}")
            ((j++))
        done
        local del_choice
        del_choice=$(dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "Delete Borg target")" \
            --menu "\n$(hb_translate "Pick a target to remove:")" \
            "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${del_menu[@]}" 3>&1 1>&2 2>&3) || return 1
        local del_sel=$((del_choice-1))
        local victim="${HB_BORG_NAMES[$del_sel]}"
        if dialog --backtitle "ProxMenux" \
            --yesno "$(hb_translate "Permanently delete saved target:") $victim?" \
            "$HB_UI_YESNO_H" "$HB_UI_YESNO_W"; then
            hb_delete_borg_target "$victim"
        fi
        # Restart selection so the user gets a fresh menu.
        hb_select_borg_repo "$_borg_repo_var"
        return $?
    fi

    # Picked a saved target.
    local sel=$((choice-1))
    _borg_repo_ref="${HB_BORG_REPOS[$sel]}"
    local key="${HB_BORG_KEYS[$sel]}"
    if [[ -n "$key" && -f "$key" ]]; then
        export BORG_RSH="ssh -i $key -o StrictHostKeyChecking=accept-new"
    else
        unset BORG_RSH
    fi
    HB_BORG_SELECTED_NAME="${HB_BORG_NAMES[$sel]}"
    HB_BORG_SELECTED_PASS="${HB_BORG_PASSES[$sel]}"
}

# ==========================================================
# COMMON PROMPTS
# ==========================================================
hb_trim_dialog_value() {
    local value="$1"
    value="${value//$'\r'/}"
    value="${value//$'\n'/}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

# Enumerate USB block-device partitions on this host. Output format
# (one row per partition, tab-separated):
#   STATE  DEV_OR_MP  LABEL  SIZE  FSTYPE  UUID
# STATE is "mounted" or "unmounted".
# DEV_OR_MP is the mountpoint when mounted, or the /dev/sdXn device when not.
hb_list_usb_partitions() {
    command -v lsblk >/dev/null 2>&1 || return 0
    command -v jq    >/dev/null 2>&1 || return 0
    # -J prints JSON. -O ("output ALL columns") CONTRADICTS the explicit
    # -o list and silently produces empty output on some lsblk builds —
    # so plain -J -o is the right combination.
    # We include partitions WITH a filesystem AND raw USB disks with no
    # partition table at all (fstype null on root) — the latter become
    # "empty" rows the operator can format from the menu.
    lsblk -J -o NAME,SIZE,MOUNTPOINT,TRAN,LABEL,FSTYPE,UUID,TYPE 2>/dev/null \
        | jq -r '
            .blockdevices[]?
            | select(.tran == "usb" and .type == "disk")
            | . as $root
            | ((.children // []) | map(select(.fstype != null and .fstype != "")) ) as $parts
            | if ($parts | length) > 0 then
                  $parts[]
                  | (if .mountpoint != null and .mountpoint != "" then "mounted\t\(.mountpoint)" else "unmounted\t/dev/\(.name)" end)
                    + "\t\(.label // "")\t\(.size // "")\t\(.fstype // "")\t\(.uuid // "")"
              else
                  "empty\t/dev/\($root.name)\t\t\($root.size // "")\t\t"
              end
        ' 2>/dev/null
}

# Compute a safe mountpoint path for a USB device, derived from its
# label or UUID so it survives reboots and re-plugs predictably.
hb_usb_mountpoint_for() {
    local label="$1" uuid="$2" dev="$3"
    local tag="${label:-$uuid}"
    tag="${tag//[^A-Za-z0-9_-]/_}"
    [[ -z "$tag" ]] && tag="$(basename "$dev")"
    printf '%s' "/mnt/proxmenux-backup-${tag}"
}

# Mount an already-formatted USB partition. On success, prints the
# mountpoint on stdout. On failure, the caller checks the rc and reads
# /tmp/proxmenux-mount.log.
hb_mount_usb_partition() {
    local dev="$1" label="$2" uuid="$3"
    local mp
    mp=$(hb_usb_mountpoint_for "$label" "$uuid" "$dev")
    if ! mkdir -p "$mp" 2>/tmp/proxmenux-mount.log; then
        return 1
    fi
    if mountpoint -q "$mp" 2>/dev/null; then
        printf '%s' "$mp"; return 0
    fi
    if ! mount "$dev" "$mp" 2>/tmp/proxmenux-mount.log; then
        return 1
    fi
    printf '%s' "$mp"
}

# Format a raw USB disk (no partition table or empty) as a single GPT
# ext4 partition, then mount it. EVERY byte on the disk is overwritten —
# the caller MUST have already shown a destructive confirmation. Used
# only when the operator explicitly picks an "empty" USB row.
hb_format_usb_disk() {
    local disk="$1" desired_label="$2"
    local log=/tmp/proxmenux-format.log
    : > "$log"

    {
        echo "=== format start $(date -Iseconds) for $disk ==="
        # Wipe any old signatures so partprobe sees a clean disk
        wipefs -a "$disk"
        # GPT + single primary partition spanning the disk
        parted -s "$disk" mklabel gpt
        parted -s "$disk" mkpart primary ext4 1MiB 100%
        partprobe "$disk" || true
        # Resolve the partition device. /dev/sde → /dev/sde1,
        # /dev/nvme0n1 → /dev/nvme0n1p1.
        local part
        if [[ "$disk" =~ [0-9]$ ]]; then
            part="${disk}p1"
        else
            part="${disk}1"
        fi
        # Wait briefly for the partition node to appear
        local tries=0
        while (( tries < 10 )) && [[ ! -b "$part" ]]; do
            sleep 0.5; ((tries++))
        done
        if [[ ! -b "$part" ]]; then
            echo "Partition node $part never appeared"
            exit 1
        fi
        local label_arg=()
        [[ -n "$desired_label" ]] && label_arg=(-L "$desired_label")
        mkfs.ext4 -F "${label_arg[@]}" "$part"
        echo "$part" > /tmp/proxmenux-format.partdev
    } >>"$log" 2>&1 || return 1

    local part
    part=$(<"/tmp/proxmenux-format.partdev")
    [[ -b "$part" ]] || return 1

    # Resolve UUID for predictable mountpoint
    local new_uuid
    new_uuid=$(lsblk -no UUID "$part" 2>/dev/null | head -1)

    local mp
    mp=$(hb_usb_mountpoint_for "$desired_label" "$new_uuid" "$part")
    mkdir -p "$mp" 2>>"$log" || return 1
    mount "$part" "$mp" 2>>"$log" || return 1
    printf '%s' "$mp"
}

hb_prompt_mounted_path() {
    local default_path="${1:-/mnt/backup}"

    local -a menu=()
    local -a entries=()
    local idx=1
    local state path_or_dev label size fstype uuid
    while IFS=$'\t' read -r state path_or_dev label size fstype uuid; do
        [[ -z "$state" ]] && continue
        local desc
        case "$state" in
            mounted)
                desc="${size:-?}  ${label:-no-label}  [${fstype}]  →  ${path_or_dev}"
                ;;
            unmounted)
                desc="${size:-?}  ${label:-no-label}  [${fstype}]  $(hb_translate "(not mounted — will be mounted)")"
                ;;
            empty)
                desc="${size:-?}  $(hb_translate "raw USB disk — no filesystem (will be FORMATTED)")"
                ;;
        esac
        menu+=("$idx" "$desc")
        entries+=("${state}|${path_or_dev}|${label}|${size}|${fstype}|${uuid}")
        ((idx++))
    done < <(hb_list_usb_partitions)

    if (( ${#menu[@]} == 0 )); then
        # No USB at all — single inputbox fallback (no menu, less confusing)
        local out
        out=$(dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "External disk for backup")" \
            --inputbox "$(hb_translate "No USB drives detected. Enter the mountpoint path manually:")" \
            "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "$default_path" 3>&1 1>&2 2>&3) || return 1
        out=$(hb_trim_dialog_value "$out")
        [[ -n "$out" && -d "$out" ]] || { msg_error "$(hb_translate "Path does not exist.")"; return 1; }
        if ! mountpoint -q "$out" 2>/dev/null; then
            dialog --backtitle "ProxMenux" --title "$(hb_translate "Warning")" \
                --yesno "$(hb_translate "This path is not a registered mount point. Use it anyway?")" \
                "$HB_UI_YESNO_H" "$HB_UI_YESNO_W" || return 1
        fi
        echo "$out"
        return 0
    fi

    local choice
    choice=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "External disk for backup")" \
        --menu "\n$(hb_translate "Pick a USB disk:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu[@]}" 3>&1 1>&2 2>&3) || return 1

    local sel="${entries[$((choice-1))]}"
    local s_state s_path s_label s_size s_fstype s_uuid
    IFS='|' read -r s_state s_path s_label s_size s_fstype s_uuid <<< "$sel"

    case "$s_state" in
        mounted)
            echo "$s_path"
            return 0
            ;;

        unmounted)
            if ! dialog --backtitle "ProxMenux" --colors \
                    --title "$(hb_translate "Mount USB disk?")" \
                    --yesno "$(hb_translate "Mount this device and use it as the backup destination?")"$'\n\n'"\Zb$(hb_translate "Device:")\ZB $s_path"$'\n'"\Zb$(hb_translate "Label:")\ZB ${s_label:-(none)}"$'\n'"\Zb$(hb_translate "Filesystem:")\ZB ${s_fstype}"$'\n'"\Zb$(hb_translate "Size:")\ZB ${s_size}" \
                    14 70; then
                return 1
            fi

            local mounted_at
            mounted_at=$(hb_mount_usb_partition "$s_path" "$s_label" "$s_uuid") || {
                local err
                err=$(tail -5 /tmp/proxmenux-mount.log 2>/dev/null | sed 's/[\Z]/_/g')
                dialog --backtitle "ProxMenux" --colors \
                    --title "$(hb_translate "Mount failed")" \
                    --msgbox "$(hb_translate "Could not mount") \Z1$s_path\Zn.\n\n${err:-$(hb_translate "See /tmp/proxmenux-mount.log for details.")}" 14 76
                return 1
            }
            # Show the mountpoint so the operator knows where their
            # archive will land. The wizard does print it again under
            # "Destination:" but the line scrolls past quickly during
            # staging.
            dialog --backtitle "ProxMenux" --colors \
                --title "$(hb_translate "USB disk mounted")" \
                --msgbox "$(hb_translate "The USB disk has been mounted.")"$'\n\n'"\Zb$(hb_translate "Backup will be saved under:")\ZB"$'\n'"  \Z4${mounted_at}\Zn" 10 78
            echo "$mounted_at"
            return 0
            ;;

        empty)
            # Destructive! Triple-check before formatting.
            if ! dialog --backtitle "ProxMenux" --colors \
                    --title "$(hb_translate "Format USB disk?")" \
                    --default-button no \
                    --yesno "\Z1\Zb$(hb_translate "WARNING: this will ERASE EVERYTHING on the disk.")\ZB\Zn"$'\n\n'"\Zb$(hb_translate "Device:")\ZB $s_path"$'\n'"\Zb$(hb_translate "Size:")\ZB ${s_size}"$'\n\n'"$(hb_translate "Create a fresh GPT + ext4 partition and mount it?")" \
                    14 76; then
                return 1
            fi
            # Second confirmation prompts the operator to type the device name
            local typed
            typed=$(dialog --backtitle "ProxMenux" --colors \
                --title "$(hb_translate "Final confirmation")" \
                --inputbox "$(hb_translate "Type the device path EXACTLY to confirm formatting:")"$'\n\n'"\Z1${s_path}\Zn" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "" 3>&1 1>&2 2>&3) || return 1
            if [[ "$typed" != "$s_path" ]]; then
                dialog --backtitle "ProxMenux" \
                    --msgbox "$(hb_translate "Device path mismatch. Format cancelled.")" 8 60
                return 1
            fi

            local fmt_label="proxmenux-backup"
            local mounted_at
            mounted_at=$(hb_format_usb_disk "$s_path" "$fmt_label") || {
                local err
                err=$(tail -10 /tmp/proxmenux-format.log 2>/dev/null)
                dialog --backtitle "ProxMenux" --colors \
                    --title "$(hb_translate "Format failed")" \
                    --msgbox "$(hb_translate "Could not format the disk.")\n\n${err}" 16 80
                return 1
            }
            dialog --backtitle "ProxMenux" --colors \
                --title "$(hb_translate "Formatted and mounted")" \
                --msgbox "\Zb$(hb_translate "Mounted at")\ZB  \Z4${mounted_at}\Zn" 8 70
            echo "$mounted_at"
            return 0
            ;;
    esac
    return 1
}

hb_prompt_dest_dir() {
    local selection out

    selection=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Select destination")" \
        --menu "\n$(hb_translate "Choose where to save the backup:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
        "vzdump" "$(hb_translate '/var/lib/vz/dump   (Proxmox default vzdump path)')" \
        "backup" "$(hb_translate '/backup')" \
        "local"  "$(hb_translate 'Custom local directory')" \
        "usb"    "$(hb_translate 'Mounted external disk')" \
        3>&1 1>&2 2>&3) || return 1

    case "$selection" in
        vzdump) out="/var/lib/vz/dump" ;;
        backup) out="/backup" ;;
        local)
            out=$(dialog --backtitle "ProxMenux" \
                --inputbox "$(hb_translate "Enter directory path:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup" 3>&1 1>&2 2>&3) || return 1
            ;;
        usb) out=$(hb_prompt_mounted_path "/mnt/backup") || return 1 ;;
    esac

    out=$(hb_trim_dialog_value "$out")
    [[ -n "$out" ]] || return 1
    mkdir -p "$out" || { msg_error "$(hb_translate "Cannot create:") $out"; return 1; }
    echo "$out"
}

hb_prompt_restore_source_dir() {
    local choice out

    choice=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Restore source location")" \
        --menu "\n$(hb_translate "Where are the backup archives stored?")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
        "vzdump" "$(hb_translate '/var/lib/vz/dump   (Proxmox default)')" \
        "backup" "$(hb_translate '/backup')" \
        "usb"    "$(hb_translate 'Mounted external disk')" \
        "custom" "$(hb_translate 'Custom path')" \
        3>&1 1>&2 2>&3) || return 1

    case "$choice" in
        vzdump) out="/var/lib/vz/dump" ;;
        backup) out="/backup" ;;
        usb)    out=$(hb_prompt_mounted_path "/mnt/backup") || return 1 ;;
        custom)
            out=$(dialog --backtitle "ProxMenux" \
                --inputbox "$(hb_translate "Enter path:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup" 3>&1 1>&2 2>&3) || return 1
            ;;
    esac

    out=$(hb_trim_dialog_value "$out")
    [[ -n "$out" && -d "$out" ]] || {
        msg_error "$(hb_translate "Directory does not exist.")"
        return 1
    }
    echo "$out"
}

# Return the set of scheduler job_ids that currently have a .env on
# disk. Used by hb_is_host_backup_archive to recognize archives
# produced by the scheduler when the filename doesn't follow the
# `hostcfg-` convention. Prints one id per line.
hb_known_scheduler_job_ids() {
    local jobs_dir="${PMX_BACKUP_JOBS_DIR:-/var/lib/proxmenux/backup-jobs}"
    [[ -d "$jobs_dir" ]] || return 0
    local f
    for f in "$jobs_dir"/*.env; do
        [[ -f "$f" ]] || continue
        basename "$f" .env
    done
}

# Decide whether $path looks like a ProxMenux host backup. Cheap
# checks only — sidecar presence + filename heuristics. We do NOT
# tar-peek here because the picker may face dozens of candidates
# and the user is waiting in front of a dialog; the in-Monitor
# endpoint takes care of peek-based detection where SWR can cache
# the result. Returns 0 on match, non-zero otherwise.
hb_is_host_backup_archive() {
    local path="$1"
    [[ -z "$path" || ! -f "$path" ]] && return 1
    # 1. Sidecar present → definitive yes.
    [[ -f "${path}.proxmenux.json" ]] && return 0
    local name stem
    name=$(basename "$path")
    # Strip the timestamped suffix; we only need the part BEFORE the
    # `-YYYYMMDD_HHMMSS.tar.*` tail.
    stem="${name%-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9].tar*}"
    # If the strip didn't change anything, the file doesn't follow
    # the ProxMenux timestamp convention at all → reject (this kills
    # PVE's vzdump-lxc-101-2026_02_24-20_00_56.tar.zst because its
    # date uses underscores between Y/M/D, not the YYYYMMDD_ form).
    [[ "$stem" == "$name" ]] && return 1
    # 2. hostcfg- prefix → manual or convention-following scheduled.
    [[ "$stem" == hostcfg-* ]] && return 0
    # 3. Known scheduler job_id → scheduled.
    local jid
    while IFS= read -r jid; do
        [[ -z "$jid" ]] && continue
        [[ "$stem" == "$jid" ]] && return 0
    done < <(hb_known_scheduler_job_ids)
    return 1
}

hb_prompt_local_archive() {
    local base_dir="$1"
    local title="${2:-$(hb_translate "Select backup archive")}"
    local -a rows=() files=() menu=()

    # Single find pass using -printf: no per-file stat subprocesses.
    # maxdepth 6 catches nested backup layouts commonly used in /var/lib/vz/dump.
    mapfile -t rows < <(
        find "$base_dir" -maxdepth 6 -type f \
            \( -name '*.tar.zst' -o -name '*.tar.gz' -o -name '*.tar' \) \
            -printf '%T@|%s|%p\n' 2>/dev/null \
        | sort -t'|' -k1,1nr \
        | head -200
    )

    # Filter the raw find result down to ProxMenux host backups —
    # the picker historically showed every .tar* in /var/lib/vz/dump,
    # which on a typical Proxmox host means dozens of vzdump-lxc-*
    # entries that aren't restorable from this menu. We track the
    # drop count so we can tell the operator something was filtered.
    local -a kept=()
    local hidden=0 row path
    for row in "${rows[@]}"; do
        path="${row##*|}"
        if hb_is_host_backup_archive "$path"; then
            kept+=("$row")
        else
            ((hidden++))
        fi
    done
    rows=("${kept[@]}")

    if [[ ${#rows[@]} -eq 0 ]]; then
        local no_backups_msg
        no_backups_msg="$(hb_translate "No ProxMenux host-backup archives were found in:") $base_dir"
        if (( hidden > 0 )); then
            no_backups_msg+=$'\n\n'"$(hb_translate "Found") $hidden $(hb_translate "other .tar archive(s) — not ProxMenux host backups (e.g. PVE vzdump or unrelated tarballs).")"
        else
            no_backups_msg+=$'\n\n'"$(hb_translate "Select another source path and try again.")"
        fi
        dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "No backups found")" \
            --msgbox "$no_backups_msg" \
            12 78 || true
        return 1
    fi

    local i=1 epoch size date_str size_str label
    for row in "${rows[@]}"; do
        epoch="${row%%|*}"; row="${row#*|}"
        size="${row%%|*}";  path="${row#*|}"
        epoch="${epoch%%.*}"   # drop sub-second fraction from %T@
        date_str=$(date -d "@$epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "-")
        size_str=$(numfmt --to=iec-i --suffix=B "$size" 2>/dev/null || echo "${size}B")
        label="${path#$base_dir/}    $date_str    $size_str"
        files+=("$path"); menu+=("$i" "$label"); ((i++))
    done

    local menu_prompt
    menu_prompt="\n$(hb_translate "Detected backups — newest first:")"
    if (( hidden > 0 )); then
        menu_prompt+=$'\n'"($(hb_translate "Hidden:") $hidden $(hb_translate "non-ProxMenux .tar archive(s) in this path"))"
    fi

    local choice
    choice=$(dialog --backtitle "ProxMenux" --title "$title" \
        --menu "$menu_prompt" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" "${menu[@]}" 3>&1 1>&2 2>&3) || return 1

    echo "${files[$((choice-1))]}"
}

# ==========================================================
# UTILITIES
# ==========================================================
hb_human_elapsed() {
    local secs="$1"
    if   (( secs < 60 ));   then printf '%ds' "$secs"
    elif (( secs < 3600 )); then printf '%dm %ds' "$((secs/60))" "$((secs%60))"
    else                         printf '%dh %dm' "$((secs/3600))" "$(( (secs%3600)/60 ))"
    fi
}

hb_file_size() {
    local path="$1"
    if [[ -f "$path" ]]; then
        numfmt --to=iec-i --suffix=B "$(stat -c %s "$path" 2>/dev/null || echo 0)" 2>/dev/null \
            || du -sh "$path" 2>/dev/null | awk '{print $1}'
    elif [[ -d "$path" ]]; then
        du -sh "$path" 2>/dev/null | awk '{print $1}'
    else
        echo "-"
    fi
}

hb_show_log() {
    local logfile="$1" title="${2:-$(hb_translate "Operation log")}"
    [[ -f "$logfile" && -s "$logfile" ]] || return 0
    dialog --backtitle "ProxMenux" --exit-label "OK" \
        --title "$title" --textbox "$logfile" 26 110 || true
}

hb_require_cmd() {
    local cmd="$1" pkg="${2:-$1}"
    command -v "$cmd" >/dev/null 2>&1 && return 0
    if command -v apt-get >/dev/null 2>&1; then
        msg_warn "$(hb_translate "Installing dependency:") $pkg"
        apt-get update -qq >/dev/null 2>&1 && apt-get install -y "$pkg" >/dev/null 2>&1
    fi
    command -v "$cmd" >/dev/null 2>&1
}

# Silent best-effort install of `pv` so callers can pipe tar through it
# for a live progress bar. Returns 0 if pv ends up available, 1 if not.
# Never speaks — pv is purely an UX improvement, asking the operator to
# install it themselves would be backwards (we have apt; they shouldn't).
hb_ensure_pv() {
    command -v pv >/dev/null 2>&1 && return 0
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq pv >/dev/null 2>&1
    fi
    command -v pv >/dev/null 2>&1
}

# ==========================================================
# Compatibility check — compares backup metadata against the
# current host and surfaces hostname / PVE version / kernel /
# storage / network / VMID drift BEFORE the apply menu opens.
#
# After running hb_compat_check, the caller can read:
#   HB_COMPAT_SAME_HOST  → 1 if backup's hostname matches current
#   HB_COMPAT_ANY_FAIL   → 1 if at least one FAIL was raised
#   HB_COMPAT_ANY_WARN   → 1 if at least one WARN was raised
#   HB_COMPAT_RESULTS[]  → array of "STATUS|category|message" entries
# Use hb_show_compat_report to surface the result and let the user
# decide whether to continue.
# ==========================================================
hb_compat_check() {
    local staging_root="$1"
    HB_COMPAT_RESULTS=()
    HB_COMPAT_SAME_HOST=0
    HB_COMPAT_ANY_FAIL=0
    HB_COMPAT_ANY_WARN=0

    local meta="$staging_root/metadata"
    local rootfs="$staging_root/rootfs"

    # --- HOST IDENTITY ---
    local bk_hostname="" cur_hostname
    if [[ -f "$meta/run_info.env" ]]; then
        bk_hostname=$(grep -m1 '^hostname=' "$meta/run_info.env" 2>/dev/null | cut -d= -f2-)
    fi
    cur_hostname=$(hostname 2>/dev/null || echo "")
    if [[ -n "$bk_hostname" ]]; then
        if [[ "$bk_hostname" == "$cur_hostname" ]]; then
            HB_COMPAT_SAME_HOST=1
            HB_COMPAT_RESULTS+=("PASS|Host|$(hb_translate "Same host:") $bk_hostname")
        else
            HB_COMPAT_RESULTS+=("WARN|Host|$(hb_translate "Different host. Backup from:") $bk_hostname / $(hb_translate "restoring on:") $cur_hostname")
            HB_COMPAT_ANY_WARN=1
        fi
    fi

    # --- PVE VERSION ---
    # `pveversion.txt` from the backup is `pveversion -v` output, where
    # each package is on its own line as `<pkg>: <version>` (note the
    # SPACE after the colon, not a slash). Live `pveversion` (no flag)
    # uses `<pkg>/<version>/<commit>` form. Cover both.
    local bk_pve="" cur_pve bk_major cur_major
    if [[ -f "$meta/pveversion.txt" ]]; then
        bk_pve=$(grep -m1 -oE '(^|[[:space:]])pve-manager[[:space:]]*[:/][[:space:]]*[0-9]+\.[0-9]+(\.[0-9]+)?' "$meta/pveversion.txt" 2>/dev/null \
            | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)
    fi
    if command -v pveversion >/dev/null 2>&1; then
        cur_pve=$(pveversion 2>/dev/null | grep -m1 -oE 'pve-manager/[0-9]+\.[0-9]+(\.[0-9]+)?' \
            | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)
    fi
    if [[ -n "$bk_pve" && -n "$cur_pve" ]]; then
        bk_major="${bk_pve%%.*}"
        cur_major="${cur_pve%%.*}"
        if [[ "$bk_pve" == "$cur_pve" ]]; then
            HB_COMPAT_RESULTS+=("PASS|PVE version|$(hb_translate "Identical:") $bk_pve")
        elif [[ "$bk_major" == "$cur_major" ]]; then
            HB_COMPAT_RESULTS+=("PASS|PVE version|$(hb_translate "Same major series:") $bk_pve → $cur_pve")
        else
            HB_COMPAT_RESULTS+=("FAIL|PVE version|$(hb_translate "Major version mismatch:") $bk_pve → $cur_pve $(hb_translate "(default paths and packages may have changed)")")
            HB_COMPAT_ANY_FAIL=1
        fi
    fi

    # --- KERNEL ---
    local bk_kernel="" cur_kernel
    if [[ -f "$meta/run_info.env" ]]; then
        bk_kernel=$(grep -m1 '^kernel=' "$meta/run_info.env" 2>/dev/null | cut -d= -f2-)
    fi
    cur_kernel=$(uname -r 2>/dev/null)
    if [[ -n "$bk_kernel" && -n "$cur_kernel" ]]; then
        if [[ "$bk_kernel" == "$cur_kernel" ]]; then
            HB_COMPAT_RESULTS+=("PASS|Kernel|$(hb_translate "Identical:") $bk_kernel")
        else
            local bk_kmaj cur_kmaj
            bk_kmaj=$(echo "$bk_kernel" | cut -d. -f1-2)
            cur_kmaj=$(echo "$cur_kernel" | cut -d. -f1-2)
            if [[ "$bk_kmaj" == "$cur_kmaj" ]]; then
                HB_COMPAT_RESULTS+=("PASS|Kernel|$(hb_translate "Same major.minor:") $bk_kernel → $cur_kernel")
            else
                HB_COMPAT_RESULTS+=("WARN|Kernel|$(hb_translate "Different kernel:") $bk_kernel → $cur_kernel")
                HB_COMPAT_ANY_WARN=1
            fi
        fi
    fi

    # --- STORAGE LAYOUT ---
    if [[ -f "$rootfs/etc/pve/storage.cfg" ]] && command -v pvesm >/dev/null 2>&1; then
        local -a bk_storages=() missing=()
        # `<type>: <storage_id>` is the storage.cfg block header form.
        mapfile -t bk_storages < <(grep -E '^[a-z]+:[[:space:]]+[A-Za-z0-9_.-]+' \
            "$rootfs/etc/pve/storage.cfg" 2>/dev/null | awk '{print $2}' | sort -u)
        local s
        for s in "${bk_storages[@]}"; do
            [[ -z "$s" ]] && continue
            if ! pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$s"; then
                missing+=("$s")
            fi
        done
        if [[ ${#bk_storages[@]} -eq 0 ]]; then
            : # backup didn't include storage.cfg or it was empty
        elif [[ ${#missing[@]} -eq 0 ]]; then
            HB_COMPAT_RESULTS+=("PASS|Storage|$(hb_translate "All") ${#bk_storages[@]} $(hb_translate "storage(s) from backup exist on target")")
        else
            HB_COMPAT_RESULTS+=("WARN|Storage|$(hb_translate "Missing on target:") ${missing[*]}")
            HB_COMPAT_ANY_WARN=1
        fi
    fi

    # --- NETWORK INTERFACES ---
    # We only flag physical NICs that the backup references but the
    # target doesn't expose. Virtual interfaces (vmbr, bond, tap, veth,
    # fwbr/fwln/fwpr, lo, VLAN suffixes) are skipped because they're
    # created by the restored configuration itself.
    #
    # A "missing" NIC needs further triage before we cry FAIL: a
    # backup often carries orphan `iface <name> inet manual` lines
    # left over from previous hardware that PVE never cleans up.
    # Those declarations do nothing if the NIC doesn't exist — they
    # don't bring it up, don't bridge it, don't bond it. Only NICs
    # that are actually WIRED into the live config (auto-up, in a
    # bridge_ports, in a bond_slaves) would lose connectivity if the
    # NIC isn't present on the target.
    if [[ -f "$rootfs/etc/network/interfaces" ]]; then
        local ifaces_file="$rootfs/etc/network/interfaces"
        local -a bk_ifaces=() missing_ifaces=() wired_missing=() orphan_missing=()
        mapfile -t bk_ifaces < <(
            grep -E '^(iface|auto)[[:space:]]' "$ifaces_file" 2>/dev/null \
                | awk '{print $2}' \
                | sort -u \
                | grep -vE '^(lo|vmbr[0-9]+|bond[0-9]+|tap.*|veth.*|fwbr.*|fwln.*|fwpr.*)$' \
                | grep -vE '\.[0-9]+$'  # strip VLAN sub-ifaces
        )
        local i
        for i in "${bk_ifaces[@]}"; do
            [[ -z "$i" ]] && continue
            if ! ip -o link show "$i" >/dev/null 2>&1; then
                missing_ifaces+=("$i")
            fi
        done
        # Classify each missing NIC as wired vs orphan declaration.
        for i in "${missing_ifaces[@]}"; do
            # Match: `auto <nic>`, `bridge-ports ... <nic>`, `bridge_ports ... <nic>`,
            #        `bond-slaves ... <nic>`, `bond_slaves ... <nic>`, `slaves ... <nic>`
            if grep -qE "(^auto[[:space:]]+${i}\$|bridge[-_]ports[[:space:]]+.*\b${i}\b|bond[-_]slaves[[:space:]]+.*\b${i}\b|^[[:space:]]*slaves[[:space:]]+.*\b${i}\b)" "$ifaces_file"; then
                wired_missing+=("$i")
            else
                orphan_missing+=("$i")
            fi
        done

        if [[ ${#bk_ifaces[@]} -eq 0 ]]; then
            : # nothing to check
        elif [[ ${#missing_ifaces[@]} -eq 0 ]]; then
            HB_COMPAT_RESULTS+=("PASS|Network|$(hb_translate "All physical interfaces from backup are present on target")")
        else
            if [[ ${#wired_missing[@]} -gt 0 ]]; then
                HB_COMPAT_RESULTS+=("FAIL|Network|$(hb_translate "Wired NICs in backup missing on target:") ${wired_missing[*]} ($(hb_translate "restoring /etc/network would lose connectivity"))")
                HB_COMPAT_ANY_FAIL=1
            fi
            if [[ ${#orphan_missing[@]} -gt 0 ]]; then
                # Orphan iface declarations — harmless leftover from older
                # hardware. Surface as PASS so the operator knows we
                # noticed, but don't trigger the FAIL gate.
                HB_COMPAT_RESULTS+=("PASS|Network|$(hb_translate "Backup declares unused NICs that are not on this host:") ${orphan_missing[*]} ($(hb_translate "orphan iface lines, no impact on restore"))")
            fi
        fi
    fi

    # --- USER PACKAGES ---
    # Compare `apt-mark showmanual` from backup vs current. Any
    # package the operator installed deliberately on the source
    # host but missing on the target will eventually cause an
    # orphan systemd unit or a "command not found" — surface
    # those up-front so the operator can decide to install them
    # via the "Install missing packages" apply option.
    if [[ -f "$meta/packages.manual.list" ]] && command -v apt-mark >/dev/null 2>&1; then
        local cur_pkgs_file
        cur_pkgs_file=$(mktemp)
        apt-mark showmanual 2>/dev/null | sort -u > "$cur_pkgs_file"
        local -a missing_pkgs=()
        mapfile -t missing_pkgs < <(comm -23 <(sort -u "$meta/packages.manual.list") "$cur_pkgs_file")
        rm -f "$cur_pkgs_file"
        if [[ ${#missing_pkgs[@]} -eq 0 ]]; then
            HB_COMPAT_RESULTS+=("PASS|Packages|$(hb_translate "All user-installed packages from the backup are present on this host")")
        else
            local list_str
            if [[ ${#missing_pkgs[@]} -le 6 ]]; then
                list_str="${missing_pkgs[*]}"
            else
                list_str="${missing_pkgs[*]:0:6}… (+ $((${#missing_pkgs[@]} - 6)) $(hb_translate "more"))"
            fi
            HB_COMPAT_RESULTS+=("WARN|Packages|${#missing_pkgs[@]} $(hb_translate "user-installed packages from backup are missing here:") $list_str")
            HB_COMPAT_ANY_WARN=1
        fi
    fi

    # --- VMID OVERLAP ---
    # On a same-host restore, overlapping guest IDs are expected (the
    # backup snapshotted YOUR live VMs, so of course they match). We
    # only flag it when the restore would actually overwrite live
    # guest configs — i.e. cross-host AND there's overlap.
    # Note: by default the host-backup restore flow does NOT restore
    # /etc/pve/nodes/* (it's part of the opt-in cluster_cfg path), but
    # if the operator later toggles that path on, this is the warning
    # they'd need to have seen.
    if [[ -d "$rootfs/etc/pve/nodes" ]] && [[ "$HB_COMPAT_SAME_HOST" != "1" ]]; then
        local -a bk_pcts=() bk_qms=() current_pcts=() current_qms=()
        [[ -f "$meta/pct-list.txt" ]] && mapfile -t bk_pcts < <(awk '/^[[:space:]]*[0-9]+/{print $1}' "$meta/pct-list.txt")
        [[ -f "$meta/qm-list.txt"  ]] && mapfile -t bk_qms  < <(awk '/^[[:space:]]*[0-9]+/{print $1}' "$meta/qm-list.txt")
        command -v pct >/dev/null 2>&1 && mapfile -t current_pcts < <(pct list 2>/dev/null | awk 'NR>1 {print $1}')
        command -v qm  >/dev/null 2>&1 && mapfile -t current_qms  < <(qm  list 2>/dev/null | awk 'NR>1 {print $1}')
        local pct_overlap=0 qm_overlap=0 id cid
        for id in "${bk_pcts[@]}"; do
            for cid in "${current_pcts[@]}"; do [[ "$id" == "$cid" ]] && ((pct_overlap++)); done
        done
        for id in "${bk_qms[@]}"; do
            for cid in "${current_qms[@]}"; do [[ "$id" == "$cid" ]] && ((qm_overlap++)); done
        done
        if (( pct_overlap + qm_overlap > 0 )); then
            HB_COMPAT_RESULTS+=("WARN|VM/CT IDs|$(hb_translate "Cross-host restore: guest IDs in backup overlap live IDs on target:") LXC=$pct_overlap, QEMU=$qm_overlap")
            HB_COMPAT_ANY_WARN=1
        fi
    fi
}

# Render HB_COMPAT_RESULTS in a dialog. Returns 0 to continue, 1 to
# abort. FAIL forces an explicit second confirmation; WARN shows the
# report and lets the user proceed; an all-PASS report only shows up
# briefly so the user can see it succeeded.
hb_show_compat_report() {
    local pass=0 warn=0 fail=0 line status rest cat msg
    local report=""
    for line in "${HB_COMPAT_RESULTS[@]}"; do
        status="${line%%|*}"; rest="${line#*|}"
        cat="${rest%%|*}";    msg="${rest#*|}"
        case "$status" in
            PASS) ((pass++)); report+=$' [OK]  '"${cat}"$'  — '"${msg}"$'\n' ;;
            WARN) ((warn++)); report+=$' [WARN] '"${cat}"$' — '"${msg}"$'\n' ;;
            FAIL) ((fail++)); report+=$' [FAIL] '"${cat}"$' — '"${msg}"$'\n' ;;
        esac
    done

    local summary
    summary="$(hb_translate "Compatibility check"): "
    summary+="${pass} pass, ${warn} warn, ${fail} fail"

    local tmpfile
    tmpfile=$(mktemp)
    {
        printf '%s\n' "$summary"
        printf '%s\n\n' "────────────────────────────────────────────────────────────"
        printf '%s\n' "$report"
    } > "$tmpfile"

    local title
    if (( fail > 0 )); then
        title="$(hb_translate "Compatibility check — issues detected")"
    elif (( warn > 0 )); then
        title="$(hb_translate "Compatibility check — review warnings")"
    else
        title="$(hb_translate "Compatibility check — OK")"
    fi

    # Only nag the operator when there's something to read. An all-PASS
    # report is pure noise on the path to a restore they already
    # confirmed they want.
    if (( warn > 0 || fail > 0 )); then
        dialog --backtitle "ProxMenux" --title "$title" \
            --textbox "$tmpfile" 22 86 || true
    fi
    rm -f "$tmpfile"

    # FAIL means at least one check is a real risk for system integrity
    # — force a second yes/no with default NO before letting the user
    # press on.
    if (( fail > 0 )); then
        if ! whiptail --title "$(hb_translate "Continue despite failures?")" \
            --defaultno \
            --yesno "$(hb_translate "The compatibility check raised failures that may break the system after restore.")"$'\n\n'"$(hb_translate "Continue anyway?")" \
            11 78; then
            return 1
        fi
    fi
    return 0
}

# ==========================================================
# Archive sidecar — explicit ProxMenux backup marker.
#
# Drops a small JSON next to a completed archive so the Monitor
# (and any future tooling) can identify it as a ProxMenux host
# backup independently of the filename. The user can rename the
# .tar.zst to whatever they want and the sidecar travels with it
# as long as they keep the same basename pair.
#
# Usage:
#   hb_write_archive_sidecar <archive_path> <kind> [job_id] [profile]
#     kind:    "manual" or "scheduled"
#     job_id:  scheduler job id (empty for manual)
#     profile: "default", "custom", or empty
# Fail-soft: returns 0 even if jq is missing and we have to fall
# back to printf-built JSON; never aborts the surrounding backup.
# ==========================================================
hb_write_archive_sidecar() {
    local archive_path="$1"
    local kind="${2:-}"
    local job_id="${3:-}"
    local profile="${4:-}"
    [[ -z "$archive_path" || ! -f "$archive_path" ]] && return 1
    local sidecar="${archive_path}.proxmenux.json"
    local archive_basename hostname_val created_at archive_size
    archive_basename=$(basename "$archive_path")
    hostname_val=$(hostname 2>/dev/null || echo "unknown")
    created_at=$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z')
    archive_size=$(stat -c %s "$archive_path" 2>/dev/null || echo 0)

    if command -v jq >/dev/null 2>&1; then
        jq -n \
            --arg kind "$kind" \
            --arg job_id "$job_id" \
            --arg profile "$profile" \
            --arg hostname "$hostname_val" \
            --arg archive "$archive_basename" \
            --arg created_at "$created_at" \
            --argjson size "$archive_size" \
            '{
                schema_version: 1,
                kind: $kind,
                job_id: (if $job_id == "" then null else $job_id end),
                profile: (if $profile == "" then null else $profile end),
                hostname: $hostname,
                archive: $archive,
                created_at: $created_at,
                archive_size: $size
            }' > "$sidecar" 2>/dev/null && return 0
    fi

    # Fallback: jq unavailable — emit JSON by hand. Fields are
    # controlled by us (no untrusted strings besides hostname/path
    # which we already constrain via shell context), so a small
    # printf is safe enough.
    {
        printf '{\n'
        printf '  "schema_version": 1,\n'
        printf '  "kind": "%s",\n' "$kind"
        if [[ -n "$job_id" ]]; then
            printf '  "job_id": "%s",\n' "$job_id"
        else
            printf '  "job_id": null,\n'
        fi
        if [[ -n "$profile" ]]; then
            printf '  "profile": "%s",\n' "$profile"
        else
            printf '  "profile": null,\n'
        fi
        printf '  "hostname": "%s",\n' "$hostname_val"
        printf '  "archive": "%s",\n' "$archive_basename"
        printf '  "created_at": "%s",\n' "$created_at"
        printf '  "archive_size": %s\n' "$archive_size"
        printf '}\n'
    } > "$sidecar" 2>/dev/null
    return 0
}
