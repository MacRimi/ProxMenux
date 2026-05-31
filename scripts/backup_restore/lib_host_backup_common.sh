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
    local paths=(
        "/etc/pve"
        "/etc/network"
        "/etc/hosts"
        "/etc/hostname"
        "/etc/ssh"
        "/etc/systemd/system"
        "/etc/modules"
        "/etc/modules-load.d"
        "/etc/modprobe.d"
        "/etc/udev/rules.d"
        "/etc/default/grub"
        "/etc/fstab"
        "/etc/kernel"
        "/etc/apt"
        "/etc/vzdump.conf"
        "/etc/postfix"
        "/etc/resolv.conf"
        "/etc/timezone"
        "/etc/iscsi"
        "/etc/multipath"
        "/usr/local/bin"
        "/usr/local/share/proxmenux"
        "/root"
        "/etc/cron.d"
        "/etc/cron.daily"
        "/etc/cron.hourly"
        "/etc/cron.weekly"
        "/etc/cron.monthly"
        "/etc/cron.allow"
        "/etc/cron.deny"
        "/var/spool/cron/crontabs"
        "/var/lib/pve-cluster"
    )
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

            # Runtime pending-restore data belongs in /var/lib/proxmenux, never in app code tree.
            if [[ "$rel" == "usr/local/share/proxmenux" || "$rel" == "usr/local/share/proxmenux/"* ]]; then
                rsync_opts+=(
                    --exclude "restore-pending/"
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

    if [[ -f /etc/pve/storage.cfg ]]; then
        local current="" server="" datastore="" username="" pw_file pw_val
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
                fi
                current="${BASH_REMATCH[1]}"; server="" datastore="" username=""
            elif [[ -n "$current" ]]; then
                [[ $line =~ ^[[:space:]]+server[[:space:]]+(.+)$    ]] && server="${BASH_REMATCH[1]}"
                [[ $line =~ ^[[:space:]]+datastore[[:space:]]+(.+)$ ]] && datastore="${BASH_REMATCH[1]}"
                [[ $line =~ ^[[:space:]]+username[[:space:]]+(.+)$  ]] && username="${BASH_REMATCH[1]}"
                if [[ $line =~ ^[a-zA-Z]+:[[:space:]] &&
                      -n "$server" && -n "$datastore" && -n "$username" ]]; then
                    pw_file="/etc/pve/priv/storage/${current}.pw"
                    pw_val="$([[ -f "$pw_file" ]] && cat "$pw_file" || echo "")"
                    HB_PBS_NAMES+=("$current")
                    HB_PBS_REPOS+=("${username}@${server}:${datastore}")
                    HB_PBS_SECRETS+=("$pw_val")
                    HB_PBS_SOURCES+=("proxmox")
                    current="" server="" datastore="" username=""
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
        fi
    fi

    # Manual configs
    local manual_cfg="$HB_STATE_DIR/pbs-manual-configs.txt"
    if [[ -f "$manual_cfg" ]]; then
        local line name repo sf
        while IFS= read -r line; do
            line="${line%%#*}"
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            [[ -z "$line" ]] && continue
            name="${line%%|*}"; repo="${line##*|}"
            sf="$HB_STATE_DIR/pbs-pass-${name}.txt"
            HB_PBS_NAMES+=("$name"); HB_PBS_REPOS+=("$repo")
            HB_PBS_SECRETS+=("$([[ -f "$sf" ]] && cat "$sf" || echo "")")
            HB_PBS_SOURCES+=("manual")
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

hb_ask_pbs_encryption() {
    local key_file="$HB_STATE_DIR/pbs-key.conf"
    local enc_pass_file="$HB_STATE_DIR/pbs-encryption-pass.txt"
    export HB_PBS_KEYFILE_OPT=""
    export HB_PBS_ENC_PASS=""

    dialog --backtitle "ProxMenux" --title "$(hb_translate "Encryption")" \
        --yesno "$(hb_translate "Encrypt this backup with a keyfile?")" \
        "$HB_UI_YESNO_H" "$HB_UI_YESNO_W" || return 0

    if [[ -f "$key_file" ]]; then
        export HB_PBS_KEYFILE_OPT="--keyfile $key_file"
        if [[ -f "$enc_pass_file" ]]; then
            HB_PBS_ENC_PASS="$(<"$enc_pass_file")"
            export HB_PBS_ENC_PASS
        fi
        msg_ok "$(hb_translate "Using existing encryption key:") $key_file"
        return 0
    fi

    # No key — offer to create one
    dialog --backtitle "ProxMenux" --title "$(hb_translate "Encryption")" \
        --yesno "$(hb_translate "No encryption key found. Create one now?")" \
        "$HB_UI_YESNO_H" "$HB_UI_YESNO_W" || return 0

    local pass1 pass2
    while true; do
        pass1=$(dialog --backtitle "ProxMenux" --insecure --passwordbox \
            "$(hb_translate "Encryption passphrase (separate from PBS password):")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 0
        pass2=$(dialog --backtitle "ProxMenux" --insecure --passwordbox \
            "$(hb_translate "Confirm encryption passphrase:")" \
            "$HB_UI_PASS_H" "$HB_UI_PASS_W" "" 3>&1 1>&2 2>&3) || return 0
        [[ "$pass1" == "$pass2" ]] && break
        dialog --backtitle "ProxMenux" \
            --msgbox "$(hb_translate "Passphrases do not match. Try again.")" 8 50
    done

    msg_info "$(hb_translate "Creating PBS encryption key...")"
    if PBS_ENCRYPTION_PASSWORD="$pass1" \
        proxmox-backup-client key create "$key_file" >/dev/null 2>&1; then
        printf '%s' "$pass1" > "$enc_pass_file"
        chmod 600 "$enc_pass_file"
        msg_ok "$(hb_translate "Encryption key created:") $key_file"
        HB_PBS_KEYFILE_OPT="--keyfile $key_file"
        HB_PBS_ENC_PASS="$pass1"
        local key_warn_msg
        key_warn_msg="$(hb_translate "IMPORTANT: Back up this key file. Without it the backup cannot be restored.")"$'\n\n'"$(hb_translate "Key:") $key_file"
        dialog --backtitle "ProxMenux" --msgbox \
            "$key_warn_msg" \
            10 74
    else
        msg_error "$(hb_translate "Failed to create encryption key. Backup will proceed without encryption.")"
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

    if [[ ${#rows[@]} -eq 0 ]]; then
        local no_backups_msg
        no_backups_msg="$(hb_translate "No backup archives were found in:") $base_dir"$'\n\n'"$(hb_translate "Select another source path and try again.")"
        dialog --backtitle "ProxMenux" \
            --title "$(hb_translate "No backups found")" \
            --msgbox "$no_backups_msg" \
            10 78 || true
        return 1
    fi

    local i=1 row epoch size path date_str size_str label
    for row in "${rows[@]}"; do
        epoch="${row%%|*}"; row="${row#*|}"
        size="${row%%|*}";  path="${row#*|}"
        epoch="${epoch%%.*}"   # drop sub-second fraction from %T@
        date_str=$(date -d "@$epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "-")
        size_str=$(numfmt --to=iec-i --suffix=B "$size" 2>/dev/null || echo "${size}B")
        label="${path#$base_dir/}    $date_str    $size_str"
        files+=("$path"); menu+=("$i" "$label"); ((i++))
    done

    local choice
    choice=$(dialog --backtitle "ProxMenux" --title "$title" \
        --menu "\n$(hb_translate "Detected backups — newest first:")" \
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
