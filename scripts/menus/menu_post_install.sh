#!/bin/bash
# ==========================================================
# ProxMenux - Post-Install Menu Dispatcher
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.2
# ==========================================================
# Description:
# Dispatcher for the post-installation options: Automated
# (zero-prompt baseline), Customizable (checklist per category)
# and Uninstall Optimizations (reverse any previously applied
# change). Also exposes two community post-install scripts
# (Proxmox VE Post Install and Microcode) via wget | bash.
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================
confirm_and_run() {
    local name="$1"
    local command="$2"
    
    dialog --clear --title "$(translate "Confirmation")" \
           --yesno "\n\n$(translate "Do you want to run the post-installation script from") $name?" 10 70
    
    response=$?
    clear
    
    if [ $response -eq 0 ]; then
        eval "$command"
        echo
        msg_success "$(translate 'Press ENTER to continue...')"
        read -r _
    else
        msg_warn "$(translate "Cancelled by user.")"
        sleep 1
    fi
}

# ==========================================================
confirm_automated_script() {
    local script_info=""


    script_info+="$(translate "This script will apply the following optimizations and advanced adjustments to your Proxmox VE server"):\n\n"
    script_info+="• $(translate "Configure") \Z4free repositories\Z0 $(translate "and upgrade the system (disables the enterprise repo)")\n"
    script_info+="• $(translate "Optionally remove") \Z4subscription banner\Z0 $(translate "from Proxmox web interface (you will be asked)")\n"
    script_info+="• $(translate "Optimize") \Z4memory\Z0, \Z4kernel\Z0, $(translate "and") \Z4network\Z0 $(translate "for better performance and stability")\n"
    script_info+="• $(translate "Install and configure") \Z4Log2RAM\Z0 $(translate "(only on SSD/NVMe) to protect your disk")\n"
    script_info+="• $(translate "Improve log rotation and limit log size to save space and extend disk life")\n"
    script_info+="• $(translate "Increase file and process limits for advanced workloads")\n"
    script_info+="• $(translate "Set up time synchronization and entropy generation")\n"
    script_info+="• $(translate "Add color prompts and useful aliases to the terminal environment")\n\n"

    script_info+="\Zb$(translate "All changes are reversible using the ProxMenux uninstaller.")\Z0\n\n"
    script_info+="$(translate "Do you want to apply these optimizations now?")"

    dialog --clear --colors \
           --backtitle "ProxMenux" \
           --title "$(translate "Automated Post-Install Script")" \
           --yesno "$script_info" 22 80

    local response=$?
    clear

    if [ $response -eq 0 ]; then
        bash "$LOCAL_SCRIPTS/post_install/auto_post_install.sh"
    else
        msg_warn "$(translate "Cancelled by user.")"
        sleep 1
    fi
}

# ==========================================================

declare -a PROXMENUX_SCRIPTS=(
    "Automated post-installation script|ProxMenux|confirm_automated_script"
    "Customizable post-installation script|ProxMenux|bash \"$LOCAL_SCRIPTS/post_install/customizable_post_install.sh\""
    "Uninstall optimizations|ProxMenux|bash \"$LOCAL_SCRIPTS/post_install/uninstall-tools.sh\""
)

# ==========================================================
# Sprint 12C: post-install function update detection.
#
# The Monitor's startup hook writes updates_available.json. We read it
# here so the bash menu can show a conditional "Apply available updates"
# entry above Uninstall when bumped versions are detected on disk vs the
# user's installed_tools.json.
# ==========================================================
UPDATES_FILE="/usr/local/share/proxmenux/updates_available.json"
UPDATE_WRAPPER="$LOCAL_SCRIPTS/post_install/update_post_install_function.sh"

count_post_install_updates() {
    [[ ! -f "$UPDATES_FILE" ]] && { echo 0; return; }
    command -v jq >/dev/null 2>&1 || { echo 0; return; }
    jq '.updates | length' "$UPDATES_FILE" 2>/dev/null || echo 0
}

# Build a dialog checklist with the available updates and run the
# wrapper script for whichever the user picks. Entries flagged
# `source_certain=false` (legacy bool entries) are listed but not
# pre-checked; they need a source pick first via the Monitor or a
# fresh re-run of the customizable post-install.
run_updates_dialog() {
    if ! command -v jq >/dev/null 2>&1; then
        msg_error "$(translate "jq is required to apply updates from this menu.")"
        sleep 2
        return
    fi

    if [[ ! -f "$UPDATES_FILE" ]]; then
        msg_warn "$(translate "No updates available — run a scan first or wait for the Monitor to refresh.")"
        sleep 2
        return
    fi

    local count
    count=$(count_post_install_updates)
    if [[ "$count" -eq 0 ]]; then
        msg_ok "$(translate "All ProxMenux optimizations are up to date.")"
        sleep 2
        return
    fi

    # Build the dialog --checklist arguments. Format per row:
    #   <tag> <description> <on|off>
    # We use the tool key as the tag so the selection callback can map
    # back to source/function via jq.
    local checklist=()
    while IFS=$'\t' read -r key current available; do
        # Sprint 12C v2: every row is checked by default. Legacy bool
        # entries default to the auto flow on the wrapper side so the
        # user no longer needs to do a "source pick" first.
        local label="${key} (v${current} → v${available})"
        checklist+=("$key" "$label" "on")
    done < <(jq -r '.updates[] | [.key, .current_version, .available_version] | @tsv' "$UPDATES_FILE" 2>/dev/null)

    if [[ ${#checklist[@]} -eq 0 ]]; then
        msg_warn "$(translate "Updates file is empty or unreadable.")"
        sleep 2
        return
    fi

    local selected
    selected=$(dialog --clear --colors --separate-output \
        --backtitle "ProxMenux" \
        --title "$(translate "Apply Available Updates")" \
        --checklist "\n$(translate "Select the optimizations to update. Each one re-runs its post-install function and registers the new version."):\n" \
        22 78 12 \
        "${checklist[@]}" 3>&1 1>&2 2>&3)

    local rc=$?
    clear
    [[ $rc -ne 0 ]] && return     # cancelled
    [[ -z "$selected" ]] && return

    # Build FUNCTIONS_BATCH (newline-separated source:function:key) by
    # looking up each picked key in the JSON. The detector already
    # populates `.source` (defaulting to "auto" for legacy bool entries
    # that didn't record one) and `.function`, so this is a straight
    # passthrough. Sprint 12C v2 dropped the source-pick gate.
    local batch=""
    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        local entry
        entry=$(jq -r --arg k "$key" '
            .updates[] | select(.key == $k) |
            select(.function != "") |
            "\((.source // "auto")):\(.function):\(.key)"
        ' "$UPDATES_FILE")
        [[ -n "$entry" ]] && batch+="${entry}"$'\n'
    done <<< "$selected"

    if [[ -z "$batch" ]]; then
        msg_warn "$(translate "Nothing to apply — none of the selected updates have a runnable function on disk.")"
        sleep 3
        return
    fi

    # Hand off to the same wrapper the Monitor uses. Running it directly
    # (not through a dialog menu) so the user sees the post-install
    # function output verbatim.
    EXECUTION_MODE="cli" FUNCTIONS_BATCH="$batch" bash "$UPDATE_WRAPPER"

    # Sprint 12C v2: force the Monitor to rewrite updates_available.json
    # so the next loop iteration of show_menu sees the post-update state
    # and the "Apply available updates (N)" entry hides/decrements
    # correctly. The endpoint is exposed on localhost without auth (POST
    # is idempotent — just re-runs the parser), so a plain curl works
    # whether HTTPS is on or off. Falls back to direct file write via
    # the Python module if the service isn't reachable (host where the
    # Monitor isn't running yet).
    local scheme="http"
    [[ -f /etc/proxmenux/ssl_config.json ]] && \
        jq -e '.enabled' /etc/proxmenux/ssl_config.json >/dev/null 2>&1 && \
        scheme="https"
    if ! curl -k -s --max-time 5 -X POST "${scheme}://127.0.0.1:8008/api/updates/post-install/scan" >/dev/null 2>&1; then
        # Fallback: regenerate the JSON via the module directly. We
        # can't import it from system Python because dependencies live
        # inside the AppImage, so just rewrite the file by re-running
        # the detector logic in-process via jq + the on-disk scripts.
        # Simpler: leave the file stale — the next AppImage restart will
        # rewrite it. The Monitor's _ensure_fresh_cache also auto-
        # refreshes when installed_tools.json changes, so the API view
        # is correct even if the bash menu sees a one-cycle-stale list.
        :
    fi

    msg_success "$(translate 'Press ENTER to continue...')"
    read -r _
}


declare -a COMMUNITY_SCRIPTS=(
    "Proxmox VE Post Install|Helper-Scripts|bash -c \"\$(wget -qLO - https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/post-pve-install.sh); msg_success \\\"\$(translate 'Press ENTER to continue...')\\\"; read -r _\""
    "Proxmox VE Microcode|Helper-Scripts|bash -c \"\$(wget -qLO - https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/pve/microcode.sh); msg_success \\\"\$(translate 'Press ENTER to continue...')\\\"; read -r _\""
)

# ==========================================================

format_menu_item() {
    local description="$1"
    local source="$2"
    local total_width=62  
    

    local desc_length=${#description}
    local source_length=${#source}
    local spaces_needed=$((total_width - desc_length - source_length))
    

    [ $spaces_needed -lt 3 ] && spaces_needed=3
    

    local spacing=""
    for ((i=0; i<spaces_needed; i++)); do
        spacing+=" "
    done
    
    echo "${description}${spacing}${source}"
}

# ==========================================================
show_menu() {
    while true; do
        local menu_items=()


        declare -A script_commands
        local counter=1

        # Sprint 12C: re-evaluate available updates on every loop so the
        # entry vanishes after the user has applied everything (and the
        # Monitor has rewritten updates_available.json on its next scan).
        local update_count
        update_count=$(count_post_install_updates)

        for script in "${PROXMENUX_SCRIPTS[@]}"; do
            IFS='|' read -r name source command <<< "$script"

            # Insert the conditional "Apply available updates" item right
            # above "Uninstall optimizations" so it sits next to the
            # related rollback action and not buried in the middle.
            if [[ "$name" == "Uninstall optimizations" && "$update_count" -gt 0 ]]; then
                local update_label
                update_label="Apply available updates ($update_count)"
                local translated_update
                translated_update="$(translate "$update_label")"
                local formatted_update
                formatted_update=$(format_menu_item "$translated_update" "ProxMenux")
                menu_items+=("$counter" "$formatted_update")
                script_commands["$counter"]="run_updates_dialog"
                ((counter++))
            fi

            local translated_name="$(translate "$name")"
            local formatted_item
            formatted_item=$(format_menu_item "$translated_name" "$source")
            menu_items+=("$counter" "$formatted_item")
            script_commands["$counter"]="$command"
            ((counter++))
        done
        

        menu_items+=("" "")
        menu_items+=("-" "───────────────────── Community Scripts ──────────────────────")
        menu_items+=("" "")
        

        for script in "${COMMUNITY_SCRIPTS[@]}"; do
            IFS='|' read -r name source command <<< "$script"
            local translated_name="$(translate "$name")"
            local formatted_item
            formatted_item=$(format_menu_item "$translated_name" "$source")
            menu_items+=("$counter" "$formatted_item")
            script_commands["$counter"]="$command"
            ((counter++))
        done
        

        menu_items+=("" "")
        menu_items+=("0" "$(translate "Return to Main Menu")")
        

        exec 3>&1
        script_selection=$(dialog --clear \
                                 --backtitle "ProxMenux" \
                                 --title "$(translate "Post-Installation Scripts")" \
                                 --menu "\n$(translate "Select a post-installation script:"):\n" \
                                 22 78 15 \
                                 "${menu_items[@]}" 2>&1 1>&3)
        exit_status=$?
        exec 3>&-
        

        if [ $exit_status -ne 0 ] || [ "$script_selection" = "0" ]; then
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
        fi
        

        if [[ "$script_selection" == "-" || "$script_selection" == "" ]]; then
            continue
        fi
        

        if [[ -n "${script_commands[$script_selection]}" ]]; then
            eval "${script_commands[$script_selection]}"
        else
            msg_error "$(translate "Invalid selection")"
            sleep 1
        fi
    done
}

# ==========================================================

show_menu
