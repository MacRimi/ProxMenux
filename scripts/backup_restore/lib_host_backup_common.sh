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
hb_select_profile_paths() {
    local mode="$1"
    local __out_var="$2"
    local -n __out_ref="$__out_var"

    mapfile -t __defaults < <(hb_default_profile_paths)

    if [[ "$mode" == "default" ]]; then
        __out_ref=("${__defaults[@]}")
        return 0
    fi

    local options=() idx=1 path
    for path in "${__defaults[@]}"; do
        options+=("$idx" "$path" "off")
        ((idx++))
    done

    local selected
    selected=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Custom backup profile")" \
        --separate-output --checklist \
        "$(hb_translate "Select paths to include:")" \
        26 86 18 "${options[@]}" 3>&1 1>&2 2>&3) || return 1

    __out_ref=()
    local choice
    while read -r choice; do
        [[ -z "$choice" ]] && continue
        __out_ref+=("${__defaults[$((choice-1))]}")
    done <<< "$selected"

    if [[ ${#__out_ref[@]} -eq 0 ]]; then
        dialog --backtitle "ProxMenux" --title "$(hb_translate "Error")" \
            --msgbox "$(hb_translate "No paths selected. Select at least one path.")" 8 60
        return 1
    fi
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
    command -v borg >/dev/null 2>&1 && { echo "borg"; return 0; }
    local appimage="$HB_STATE_DIR/borg"
    local tmp_file
    [[ -x "$appimage" ]] && { echo "$appimage"; return 0; }
    command -v sha256sum >/dev/null 2>&1 || {
        msg_error "$(hb_translate "sha256sum not found. Cannot verify Borg binary.")"
        return 1
    }
    msg_info "$(hb_translate "Borg not found. Downloading borg") ${HB_BORG_VERSION}..."
    mkdir -p "$HB_STATE_DIR"
    tmp_file=$(mktemp "$HB_STATE_DIR/.borg-download.XXXXXX") || return 1
    if wget -qO "$tmp_file" "$HB_BORG_LINUX64_URL"; then
        if echo "${HB_BORG_LINUX64_SHA256}  $tmp_file" | sha256sum -c - >/dev/null 2>&1; then
            mv -f "$tmp_file" "$appimage"
        else
            rm -f "$tmp_file"
            msg_error "$(hb_translate "Borg binary checksum verification failed.")"
            return 1
        fi
        chmod +x "$appimage"
        msg_ok "$(hb_translate "Borg ready.")"
        echo "$appimage"; return 0
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
    local pass_file="$HB_STATE_DIR/borg-pass.txt"
    BORG_ENCRYPT_MODE="none"
    unset BORG_PASSPHRASE

    if [[ -f "$pass_file" ]]; then
        export BORG_PASSPHRASE
        BORG_PASSPHRASE="$(<"$pass_file")"
        BORG_ENCRYPT_MODE="repokey"
        return 0
    fi

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
    printf '%s' "$pass1" > "$pass_file"
    chmod 600 "$pass_file"
    export BORG_PASSPHRASE="$pass1"
    export BORG_ENCRYPT_MODE="repokey"
}

hb_select_borg_repo() {
    local _borg_repo_var="$1"
    local -n _borg_repo_ref="$_borg_repo_var"
    local type

    type=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Borg repository location")" \
        --menu "\n$(hb_translate "Select repository destination:")" \
        "$HB_UI_MENU_H" "$HB_UI_MENU_W" "$HB_UI_MENU_LIST" \
        "local"  "$(hb_translate 'Local directory')" \
        "usb"    "$(hb_translate 'Mounted external disk')" \
        "remote" "$(hb_translate 'Remote server via SSH')" \
        3>&1 1>&2 2>&3) || return 1

    unset BORG_RSH
    case "$type" in
        local)
            _borg_repo_ref=$(dialog --backtitle "ProxMenux" \
                --inputbox "$(hb_translate "Borg repository path:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup/borgbackup" \
                3>&1 1>&2 2>&3) || return 1
            mkdir -p "$_borg_repo_ref" 2>/dev/null || true
            ;;
        usb)
            local mnt
            mnt=$(hb_prompt_mounted_path "/mnt/backup") || return 1
            _borg_repo_ref="$mnt/borgbackup"
            mkdir -p "$_borg_repo_ref" 2>/dev/null || true
            ;;
        remote)
            local user host rpath ssh_key
            user=$(dialog --backtitle "ProxMenux" --inputbox "$(hb_translate "SSH user:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "root" 3>&1 1>&2 2>&3) || return 1
            host=$(dialog --backtitle "ProxMenux" --inputbox "$(hb_translate "SSH host or IP:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "" 3>&1 1>&2 2>&3) || return 1
            rpath=$(dialog --backtitle "ProxMenux" \
                --inputbox "$(hb_translate "Remote repository path:")" \
                "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "/backup/borgbackup" \
                3>&1 1>&2 2>&3) || return 1
            if dialog --backtitle "ProxMenux" \
                --yesno "$(hb_translate "Use a custom SSH key?")" \
                "$HB_UI_YESNO_H" "$HB_UI_YESNO_W"; then
                ssh_key=$(dialog --backtitle "ProxMenux" \
                    --fselect "$HOME/.ssh/" 12 70 3>&1 1>&2 2>&3) || return 1
                export BORG_RSH="ssh -i $ssh_key -o StrictHostKeyChecking=accept-new"
            fi
            _borg_repo_ref="ssh://$user@$host/$rpath"
            ;;
    esac
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

hb_prompt_mounted_path() {
    local default_path="${1:-/mnt/backup}"
    local out

    out=$(dialog --backtitle "ProxMenux" \
        --title "$(hb_translate "Mounted disk path")" \
        --inputbox "$(hb_translate "Path where the external disk is mounted:")" \
        "$HB_UI_INPUT_H" "$HB_UI_INPUT_W" "$default_path" 3>&1 1>&2 2>&3) || return 1

    out=$(hb_trim_dialog_value "$out")
    [[ -n "$out" && -d "$out" ]] || { msg_error "$(hb_translate "Path does not exist.")"; return 1; }
    if ! mountpoint -q "$out" 2>/dev/null; then
        dialog --backtitle "ProxMenux" --title "$(hb_translate "Warning")" \
            --yesno "$(hb_translate "This path is not a registered mount point. Use it anyway?")" \
            "$HB_UI_YESNO_H" "$HB_UI_YESNO_W" || return 1
    fi
    echo "$out"
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

    dialog --backtitle "ProxMenux" --title "$title" \
        --textbox "$tmpfile" 22 86 || true
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
