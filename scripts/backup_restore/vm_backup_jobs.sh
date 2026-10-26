#!/bin/bash

# ==========================================================
# ProxMenux - VM/CT Backup Jobs Manager
# ==========================================================
# Author      : MattiaC46 (PR #421), MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# View, create, edit, enable/disable, delete and run on-demand
# the PVE backup jobs normally found under
#   Datacenter > Backup
# This is a thin wrapper around the official `pvesh` API
# (/cluster/backup), so jobs created/edited here show up exactly
# the same in the native PVE web UI and vice versa.
# ==========================================================

# Configuration ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SCRIPTS_DEFAULT="/usr/local/share/proxmenux/scripts"
LOCAL_SCRIPTS="$LOCAL_SCRIPTS_DEFAULT"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"

if [[ -f "$LOCAL_SCRIPTS_LOCAL/utils.sh" ]]; then
    LOCAL_SCRIPTS="$LOCAL_SCRIPTS_LOCAL"
    UTILS_FILE="$LOCAL_SCRIPTS/utils.sh"
elif [[ ! -f "$UTILS_FILE" ]]; then
    UTILS_FILE="$BASE_DIR/utils.sh"
fi

# shellcheck source=/dev/null
if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
else
    echo "Error: $UTILS_FILE not found"
    exit 1
fi

load_language
initialize_cache

BACKTITLE="ProxMenux"
UI_W=84
UI_H=22
UI_LIST_H=12

function header() {
    show_proxmenux_logo
    msg_title "$(translate "VM/CT Backup Jobs (Datacenter > Backup)")"
}

# ── Sanity checks ──────────────────────────────────────────

if ! command -v pvesh >/dev/null 2>&1; then
    dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
        --msgbox "$(translate "pvesh not found. This must run on a Proxmox VE node.")" 8 60
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
        --msgbox "$(translate "jq is required for this menu and is not installed.")" 8 60
    exit 1
fi

THIS_NODE=$(hostname)

# ── Helpers ────────────────────────────────────────────────

# Lists storages that accept "backup" content, one per line: id<TAB>type
list_backup_storages() {
    pvesh get /storage --output-format json 2>/dev/null \
        | jq -r '.[] | select(.content // "" | contains("backup")) | "\(.storage)\t\(.type)"'
}

# Lists VMs and CTs on the whole cluster, one per line: vmid<TAB>name<TAB>kind
list_guests() {
    {
        pvesh get /cluster/resources --type vm --output-format json 2>/dev/null \
            | jq -r '.[] | select(.type=="qemu" or .type=="lxc") | "\(.vmid)\t\(.name // "-")\t\(.type)"'
    } | sort -n
}

# Host backups of ProxMenux that run with a Proxmox job, comma separated.
attached_host_backups() {
    local job_id="$1" file found=()
    for file in /var/lib/proxmenux/backup-jobs/*.env; do
        [[ -f "$file" ]] || continue
        grep -qxF "PVE_PARENT_JOB=${job_id}" "$file" 2>/dev/null && found+=("$(basename "$file" .env)")
    done
    local IFS=,
    echo "${found[*]}"
}

# Pretty one-line summary of a job, used in the main list
job_summary_line() {
    local j="$1"
    local vmid storage schedule mode enabled all
    vmid=$(jq -r '.vmid // empty' <<<"$j")
    all=$(jq -r '.all // 0' <<<"$j")
    storage=$(jq -r '.storage // "-"' <<<"$j")
    schedule=$(jq -r '.schedule // "-"' <<<"$j")
    mode=$(jq -r '.mode // "snapshot"' <<<"$j")
    enabled=$(jq -r '.enabled // 1' <<<"$j")

    local target
    if [[ "$all" == "1" || "$all" == "true" ]]; then
        target="$(translate "all guests")"
    elif [[ -n "$vmid" ]]; then
        target="VM/CT: $vmid"
    else
        target="$(translate "(no guests selected)")"
    fi

    local state
    if [[ "$enabled" == "0" || "$enabled" == "false" ]]; then
        state="[$(translate "disabled")]"
    else
        state=""
    fi

    echo "$schedule | $storage | $mode | $target $state"
}

# ── Guest picker (checklist) ──────────────────────────────
# Sets GUEST_SELECTION to "ALL" or a comma-separated vmid list.
# Returns 1 on cancel.
select_guests() {
    local pick
    pick=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Select Guests")" \
        --menu "\n$(translate "Which guests should this job back up?")" 12 70 2 \
        "ALL" "$(translate "All guests on the cluster")" \
        "PICK" "$(translate "Choose specific VMs/CTs")" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    if [[ "$pick" == "ALL" ]]; then
        GUEST_SELECTION="ALL"
        return 0
    fi

    local guests=()
    while IFS=$'\t' read -r vmid name kind; do
        [[ -z "$vmid" ]] && continue
        guests+=("$vmid" "$name ($kind)" "off")
    done < <(list_guests)

    if [[ ${#guests[@]} -eq 0 ]]; then
        dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
            --msgbox "$(translate "No VMs or CTs found on this cluster.")" 8 60
        return 1
    fi

    local raw
    raw=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Select Guests")" \
        --checklist "\n$(translate "Mark the VMs/CTs to include in this job:")" 20 70 12 \
        "${guests[@]}" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    GUEST_SELECTION=$(echo "$raw" | tr -d '"' | tr -s ' ' ',' | sed 's/^,//;s/,$//')
    if [[ -z "$GUEST_SELECTION" ]]; then
        dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
            --msgbox "$(translate "No guest selected.")" 8 60
        return 1
    fi
    return 0
}

# ── Storage picker ─────────────────────────────────────────
# Sets JOB_STORAGE. Returns 1 on cancel.
select_storage() {
    local items=()
    while IFS=$'\t' read -r sid stype; do
        [[ -z "$sid" ]] && continue
        items+=("$sid" "$stype")
    done < <(list_backup_storages)

    if [[ ${#items[@]} -eq 0 ]]; then
        dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
            --msgbox "$(translate "No storage with 'backup' content enabled was found.\n\nAdd one from Datacenter > Storage first (PBS, or a directory/NFS with the Backup content type).")" 10 70
        return 1
    fi

    JOB_STORAGE=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Target Storage")" \
        --menu "\n$(translate "Select the storage that will receive the backups:")" "$UI_H" "$UI_W" "$UI_LIST_H" \
        "${items[@]}" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$JOB_STORAGE" ]] && return 1
    return 0
}

# ── Schedule picker ─────────────────────────────────────────
# Sets JOB_SCHEDULE (systemd calendar-event syntax). Returns 1 on cancel.
select_schedule() {
    local pick
    pick=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Schedule")" \
        --menu "\n$(translate "Choose a schedule (systemd calendar-event syntax):")" 18 74 7 \
        "daily-02"   "$(translate "Daily at 02:00")" \
        "daily-03"   "$(translate "Daily at 03:00")" \
        "weekly-sun" "$(translate "Weekly, Sunday 02:00")" \
        "every-6h"   "$(translate "Every 6 hours")" \
        "hourly"     "$(translate "Every hour")" \
        "custom"     "$(translate "Custom (type it myself)")" \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    case "$pick" in
        daily-02)   JOB_SCHEDULE="02:00" ;;
        daily-03)   JOB_SCHEDULE="03:00" ;;
        weekly-sun) JOB_SCHEDULE="sun 02:00" ;;
        every-6h)   JOB_SCHEDULE="00/6:00" ;;
        hourly)     JOB_SCHEDULE="hourly" ;;
        custom)
            JOB_SCHEDULE=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Custom Schedule")" \
                --inputbox "\n$(translate "Enter a systemd calendar event, e.g.:")\n  'mon..fri 01:30'\n  '*-*-1 03:00' ($(translate "first of every month")))" \
                12 70 "02:00" 3>&1 1>&2 2>&3)
            [[ $? -ne 0 || -z "$JOB_SCHEDULE" ]] && return 1
            ;;
    esac
    return 0
}

# ── Mode / compression / retention pickers ─────────────────

select_mode() {
    JOB_MODE=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Backup Mode")" \
        --radiolist "\n$(translate "Select the backup mode:")" 14 74 3 \
        "snapshot" "$(translate "Snapshot - no downtime (recommended)")" on \
        "suspend"  "$(translate "Suspend - pauses the guest during backup")" off \
        "stop"     "$(translate "Stop - shuts the guest down during backup")" off \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$JOB_MODE" ]] && return 1
    return 0
}

select_compress() {
    JOB_COMPRESS=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Compression")" \
        --radiolist "\n$(translate "Select compression:")" 14 74 4 \
        "zstd" "$(translate "ZSTD - fast, good ratio (recommended)")" on \
        "gzip" "$(translate "GZIP - slower, widely compatible")" off \
        "lzo"  "$(translate "LZO - fastest, weaker ratio")" off \
        "0"    "$(translate "None")" off \
        3>&1 1>&2 2>&3)
    [[ $? -ne 0 || -z "$JOB_COMPRESS" ]] && return 1
    return 0
}

input_retention() {
    local default="${1:-keep-last=3}"
    JOB_PRUNE=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Retention")" \
        --inputbox "\n$(translate "Retention policy (prune-backups syntax).")\n$(translate "Examples:")\n  keep-last=3\n  keep-daily=7,keep-weekly=4,keep-monthly=6\n\n$(translate "Leave empty to use the retention of the storage.")" \
        14 74 "$default" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1
    return 0
}

input_notes() {
    local default="${1:-{{guestname}}}"
    JOB_NOTES=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Notes Template")" \
        --inputbox "\n$(translate "Notes template shown next to each backup (optional).")\n$(translate "Placeholders: {{guestname}} {{node}} {{vmid}}")" \
        12 74 "$default" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1
    return 0
}

# ── Create ───────────────────────────────────────────────

create_job_wizard() {
    header
    GUEST_SELECTION=""; JOB_STORAGE=""; JOB_SCHEDULE=""; JOB_MODE=""; JOB_COMPRESS=""; JOB_PRUNE=""; JOB_NOTES=""

    select_guests || return 1
    select_storage || return 1
    select_schedule || return 1
    select_mode || return 1
    select_compress || return 1
    input_retention "keep-last=3" || return 1
    input_notes "{{guestname}}" || return 1

    local job_id
    job_id=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Job ID (optional)")" \
        --inputbox "\n$(translate "Short name for this job (letters, numbers, hyphens).")\n$(translate "Leave empty to auto-generate one.")" \
        10 70 "" 3>&1 1>&2 2>&3)
    [[ $? -ne 0 ]] && return 1

    local args=(create /cluster/backup --storage "$JOB_STORAGE" --schedule "$JOB_SCHEDULE" \
        --mode "$JOB_MODE" --compress "$JOB_COMPRESS" --enabled 1)
    [[ -n "$job_id" ]] && args+=(--id "$job_id")
    if [[ "$GUEST_SELECTION" == "ALL" ]]; then
        args+=(--all 1)
    else
        args+=(--vmid "$GUEST_SELECTION")
    fi
    [[ -n "$JOB_PRUNE" ]] && args+=(--prune-backups "$JOB_PRUNE")
    [[ -n "$JOB_NOTES" ]] && args+=(--notes-template "$JOB_NOTES")

    header
    msg_info "$(translate "Creating backup job...")"
    local out
    if out=$(pvesh "${args[@]}" 2>&1); then
        msg_ok "$(translate "Backup job created successfully.")"
    else
        msg_error "$(translate "Failed to create the job.")"
        echo "$out"
    fi
    echo
    read -n 1 -s -r -p "$(translate "Press any key to continue...")"
}

# ── Edit ─────────────────────────────────────────────────

edit_job_wizard() {
    local job_id="$1"
    local current
    current=$(pvesh get "/cluster/backup/$job_id" --output-format json 2>/dev/null)
    if [[ -z "$current" ]]; then
        dialog --backtitle "$BACKTITLE" --title "$(translate "Error")" \
            --msgbox "$(translate "Could not read this job.")" 8 60
        return 1
    fi

    local cur_vmid cur_all cur_storage cur_schedule cur_mode cur_compress cur_prune cur_notes
    cur_vmid=$(jq -r '.vmid // empty' <<<"$current")
    cur_all=$(jq -r '.all // 0' <<<"$current")
    cur_storage=$(jq -r '.storage // empty' <<<"$current")
    cur_schedule=$(jq -r '.schedule // empty' <<<"$current")
    cur_mode=$(jq -r '.mode // "snapshot"' <<<"$current")
    cur_compress=$(jq -r '.compress // "zstd"' <<<"$current")
    cur_prune=$(jq -r '."prune-backups" // empty | if type == "object" then to_entries | map("\(.key)=\(.value)") | join(",") else . end' <<<"$current")
    cur_notes=$(jq -r '."notes-template" // empty' <<<"$current")

    local field
    while true; do
        field=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Edit Job") $job_id" \
            --menu "\n$(translate "What do you want to change?")" 20 74 8 \
            "guests"   "$(translate "Guests") ($( [[ "$cur_all" == "1" ]] && echo "all" || echo "$cur_vmid" ))" \
            "storage"  "$(translate "Storage") ($cur_storage)" \
            "schedule" "$(translate "Schedule") ($cur_schedule)" \
            "mode"     "$(translate "Mode") ($cur_mode)" \
            "compress" "$(translate "Compression") ($cur_compress)" \
            "prune"    "$(translate "Retention") ($cur_prune)" \
            "notes"    "$(translate "Notes template")" \
            "SAVE"     "$(translate ">> Save and return <<")" \
            3>&1 1>&2 2>&3)
        [[ $? -ne 0 ]] && return 1

        case "$field" in
            guests)
                if select_guests; then
                    if [[ "$GUEST_SELECTION" == "ALL" ]]; then
                        cur_all=1; cur_vmid=""
                    else
                        cur_all=0; cur_vmid="$GUEST_SELECTION"
                    fi
                fi
                ;;
            storage)
                if select_storage; then
                    local attached
                    attached=$(attached_host_backups "$job_id")
                    if [[ -n "$attached" && "$JOB_STORAGE" != "$cur_storage" ]]; then
                        dialog --backtitle "$BACKTITLE" --title "$(translate "Storage")" \
                            --msgbox "\n$(translate "These host backups run with this job and expect its storage:") $attached\n\n$(translate "With another storage this job no longer starts them. Another job that writes to the original storage still does.")" 14 70
                    fi
                    cur_storage="$JOB_STORAGE"
                fi
                ;;
            schedule) select_schedule && cur_schedule="$JOB_SCHEDULE" ;;
            mode)     select_mode && cur_mode="$JOB_MODE" ;;
            compress) select_compress && cur_compress="$JOB_COMPRESS" ;;
            prune)    input_retention "$cur_prune" && cur_prune="$JOB_PRUNE" ;;
            notes)    input_notes "$cur_notes" && cur_notes="$JOB_NOTES" ;;
            SAVE)
                local args=(set "/cluster/backup/$job_id" \
                    --storage "$cur_storage" --schedule "$cur_schedule" \
                    --mode "$cur_mode" --compress "$cur_compress")
                if [[ "$cur_all" == "1" ]]; then
                    args+=(--all 1 --delete vmid)
                else
                    args+=(--vmid "$cur_vmid" --delete all)
                fi
                if [[ -n "$cur_prune" ]]; then
                    args+=(--prune-backups "$cur_prune")
                else
                    args+=(--delete prune-backups)
                fi
                if [[ -n "$cur_notes" ]]; then
                    args+=(--notes-template "$cur_notes")
                else
                    args+=(--delete notes-template)
                fi

                header
                msg_info "$(translate "Saving changes...")"
                local out
                if out=$(pvesh "${args[@]}" 2>&1); then
                    msg_ok "$(translate "Job updated successfully.")"
                else
                    msg_error "$(translate "Failed to update the job.")"
                    echo "$out"
                fi
                echo
                read -n 1 -s -r -p "$(translate "Press any key to continue...")"
                return 0
                ;;
        esac
    done
}

# ── Delete / Toggle / Run now ───────────────────────────────

delete_job() {
    local job_id="$1"
    local attached warning=""
    attached=$(attached_host_backups "$job_id")
    [[ -n "$attached" ]] && warning="\n\n$(translate "This job will no longer start these host backups:") $attached\n$(translate "Another job that writes to the same storage still starts them.")"
    dialog --backtitle "$BACKTITLE" --title "$(translate "Confirm Delete")" \
        --yesno "\n$(translate "Delete backup job") '$job_id'?\n\n$(translate "This only removes the schedule. Existing backup archives are NOT deleted.")${warning}" 16 70
    [[ $? -ne 0 ]] && return 1

    header
    msg_info "$(translate "Deleting job...")"
    local out
    if out=$(pvesh delete "/cluster/backup/$job_id" 2>&1); then
        msg_ok "$(translate "Job deleted.")"
    else
        msg_error "$(translate "Failed to delete the job.")"
        echo "$out"
    fi
    echo
    read -n 1 -s -r -p "$(translate "Press any key to continue...")"
}

toggle_job() {
    local job_id="$1" enabled="$2"
    local new=1
    [[ "$enabled" != "0" && "$enabled" != "false" ]] && new=0

    header
    msg_info "$(translate "Updating job status...")"
    local out
    if out=$(pvesh set "/cluster/backup/$job_id" --enabled "$new" 2>&1); then
        if [[ "$new" == "1" ]]; then
            msg_ok "$(translate "Job enabled.")"
        else
            msg_ok "$(translate "Job disabled.")"
        fi
    else
        msg_error "$(translate "Failed to update the job.")"
        echo "$out"
    fi
    echo
    sleep 1
}

# Runs the job now with its own settings. Each node runs its part as a
# Proxmox task, so it is listed and logged like a scheduled run.
run_job_now() {
    local job_id="$1"
    local current
    current=$(pvesh get "/cluster/backup/$job_id" --output-format json 2>/dev/null)
    [[ -z "$current" ]] && return 1

    local mode
    mode=$(jq -r '.mode // "snapshot"' <<<"$current")
    local warning=""
    [[ "$mode" == "stop" ]] && warning="\n\n$(translate "The mode of this job is stop: its guests are shut down during the backup.")"

    dialog --backtitle "$BACKTITLE" --title "$(translate "Run Now")" \
        --yesno "\n$(translate "Run job") '$job_id' $(translate "now, with its current settings?")\n\n$(translate "The backup runs as a Proxmox task; follow it in the task log of Proxmox.")${warning}" 14 74
    [[ $? -ne 0 ]] && return 1

    header
    msg_info "$(translate "Starting the backup...")"

    local nodes=() node
    node=$(jq -r '.node // empty' <<<"$current")
    if [[ -n "$node" ]]; then
        nodes=("$node")
    elif [[ "$(jq -r '.all // 0' <<<"$current")" =~ ^(1|true)$ || -n "$(jq -r '.pool // empty' <<<"$current")" ]]; then
        mapfile -t nodes < <(pvesh get /nodes --output-format json 2>/dev/null \
            | jq -r '.[] | select(.status=="online") | .node')
    else
        local wanted
        wanted=$(jq -c '(.vmid // "") | tostring | split(",") | map(gsub(" "; ""))' <<<"$current")
        mapfile -t nodes < <(pvesh get /cluster/resources --type vm --output-format json 2>/dev/null \
            | jq -r --argjson wanted "$wanted" '[.[] | select((.vmid|tostring) as $id | $wanted | index($id)) | .node] | unique | .[]')
    fi

    if [[ ${#nodes[@]} -eq 0 ]]; then
        msg_error "$(translate "No online node has a guest of this job.")"
        echo
        read -n 1 -s -r -p "$(translate "Press any key to continue...")"
        return 1
    fi

    # Every option of the job that vzdump understands, as it is stored.
    local run_args=()
    mapfile -t run_args < <(jq -r '
        del(.id, .type, .schedule, .enabled, ."next-run", .comment, ."repeat-missed", .digest, .node, .starttime, .dow)
        | to_entries[] | select(.value != null and .value != "")
        | "--\(.key)",
          (if (.value|type) == "object" then (.value | to_entries | map("\(.key)=\(.value)") | join(","))
           elif (.value|type) == "boolean" then (if .value then "1" else "0" end)
           else (.value|tostring) end)' <<<"$current")

    stop_spinner
    local out
    for node in "${nodes[@]}"; do
        if out=$(pvesh create "/nodes/$node/vzdump" "${run_args[@]}" 2>&1); then
            msg_ok "$(translate "Backup started on node") $node"
            echo -e "${TAB}$(grep -o 'UPID:[^"[:space:]]*' <<<"$out" | head -1)"
        else
            msg_error "$(translate "The backup could not be started on node") $node"
            echo "$out"
        fi
    done

    echo
    read -n 1 -s -r -p "$(translate "Press any key to continue...")"
}

# ── Job list / detail menu ──────────────────────────────────

job_detail_menu() {
    local job_id="$1"
    while true; do
        local current enabled
        current=$(pvesh get "/cluster/backup/$job_id" --output-format json 2>/dev/null)
        [[ -z "$current" ]] && return
        enabled=$(jq -r '.enabled // 1' <<<"$current")

        local toggle_label
        if [[ "$enabled" == "0" || "$enabled" == "false" ]]; then
            toggle_label="$(translate "Enable job")"
        else
            toggle_label="$(translate "Disable job")"
        fi

        local choice
        choice=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Job") $job_id" \
            --menu "\n$(job_summary_line "$current")" 16 78 6 \
            "run"    "$(translate "Run now")" \
            "edit"   "$(translate "Edit")" \
            "toggle" "$toggle_label" \
            "delete" "$(translate "Delete")" \
            "back"   "$(translate "Back to job list")" \
            3>&1 1>&2 2>&3)
        [[ $? -ne 0 || "$choice" == "back" ]] && return

        case "$choice" in
            run)    run_job_now "$job_id" ;;
            edit)   edit_job_wizard "$job_id" ;;
            toggle) toggle_job "$job_id" "$enabled" ;;
            delete) delete_job "$job_id"; return ;;
        esac
    done
}

list_jobs_menu() {
    while true; do
        local jobs_json
        jobs_json=$(pvesh get /cluster/backup --output-format json 2>/dev/null)

        local count
        count=$(jq 'length' <<<"${jobs_json:-[]}" 2>/dev/null)
        [[ -z "$count" ]] && count=0

        local items=()
        if [[ "$count" -gt 0 ]]; then
            while IFS=$'\t' read -r jid jsummary; do
                [[ -z "$jid" ]] && continue
                items+=("$jid" "$jsummary")
            done < <(jq -r '.[] | [.id, (.schedule // "-")+" | "+(.storage // "-")+" | "+(.vmid // (if .all==1 then "all" else "-" end))] | @tsv' <<<"$jobs_json")
        fi

        items+=("NEW" "$(translate ">> Create a new backup job <<")")
        items+=("BACK" "$(translate "Return")")

        header
        local choice
        choice=$(dialog --backtitle "$BACKTITLE" --title "$(translate "Backup Jobs") ($THIS_NODE)" \
            --menu "\n$(translate "Select a job to view/edit, or create a new one:")" 22 86 12 \
            "${items[@]}" \
            3>&1 1>&2 2>&3)
        [[ $? -ne 0 || "$choice" == "BACK" ]] && exit 0

        if [[ "$choice" == "NEW" ]]; then
            create_job_wizard
        else
            job_detail_menu "$choice"
        fi
    done
}

# ── Entry point ──────────────────────────────────────────────
list_jobs_menu
