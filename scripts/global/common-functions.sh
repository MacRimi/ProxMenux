#!/bin/bash
# ==========================================================
# Common Functions for Proxmox VE Scripts
# ==========================================================

# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache


get_pve_info() {
    local pve_full_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    local pve_major=$(echo "$pve_full_version" | cut -d. -f1)
    local os_codename="$(grep "VERSION_CODENAME=" /etc/os-release | cut -d"=" -f 2 | xargs)"
    
    if [ -z "$os_codename" ]; then
        os_codename=$(lsb_release -cs 2>/dev/null)
    fi
    

    local target_codename
    if [ "$pve_major" -ge 9 ] 2>/dev/null; then
        target_codename="trixie"
    else
        target_codename="$os_codename"
        if [ -z "$target_codename" ]; then
            target_codename="bookworm"
        fi
    fi
    
    echo "$pve_full_version|$pve_major|$os_codename|$target_codename"
}


lvm_repair_check() {
    msg_info "$(translate "Checking and repairing old LVM PV headers (if needed)...")"
    
    if ! command -v pvs >/dev/null 2>&1; then
        msg_info "$(translate "LVM tools not available, skipping LVM check")"
        return
    fi
    
    pvs_output=$(LC_ALL=C pvs -v 2>&1 | grep "old PV header" || true)
    if [ -z "$pvs_output" ]; then
        msg_ok "$(translate "No PVs with old headers found.")"
        return
    fi
    
    declare -A vg_map
    while read -r line; do
        pv=$(echo "$line" | grep -o '/dev/[^ ]*' || true)
        if [ -n "$pv" ]; then
            vg=$(pvs -o vg_name --noheadings "$pv" 2>/dev/null | awk '{print $1}' || true)
            if [ -n "$vg" ]; then
                vg_map["$vg"]=1
            fi
        fi
    done <<< "$pvs_output"
    
    for vg in "${!vg_map[@]}"; do
        msg_warn "$(translate "Old PV header(s) found in VG $vg. Updating metadata...")"
        vgck --updatemetadata "$vg" 2>/dev/null
        vgchange -ay "$vg" 2>/dev/null
        if [ $? -ne 0 ]; then
            msg_warn "$(translate "Metadata update failed for VG $vg. Review manually.")"
        else
            msg_ok "$(translate "Metadata updated successfully for VG $vg")"
        fi
    done
    
    msg_ok "$(translate "LVM PV headers check completed")"
}




cleanup_duplicate_repos_pve9() {
    msg_info "$(translate "Cleaning up duplicate repositories...")"

    local sources_file="/etc/apt/sources.list"
    local cleaned_count=0

    # Helper: extract a DEB822 field's value from a .sources file. Handles
    # both `Field: value` and folded continuations. Returns the FIRST value
    # only (URIs / Suites / Components with multiple entries are read as a
    # single whitespace-separated string that callers split themselves).
    _deb822_get() {
        local file="$1" field="$2"
        [[ -f "$file" ]] || return 1
        awk -v F="$field" '
            BEGIN{ IGNORECASE=1 }
            /^[[:space:]]*$/{ next }
            /^[^[:space:]]/{
                if (match($0, "^"F"[[:space:]]*:[[:space:]]*")) {
                    print substr($0, RSTART+RLENGTH)
                    exit
                }
            }
        ' "$file"
    }

    # Helper: back up a file once before modifying, so an accidental
    # comment-out is always recoverable next to the original.
    _backup_once() {
        local file="$1"
        [[ -f "$file" ]] || return 0
        local ts backup
        ts=$(date +%Y%m%d_%H%M%S)
        backup="${file}.proxmenux-backup.${ts}"
        [[ -f "$backup" ]] || cp -a "$file" "$backup"
    }

    # ── Phase 1 — comment intra-file duplicates in sources.list by URL+Suite ──
    if [ -s "$sources_file" ]; then
        local temp_file
        temp_file=$(mktemp)
        declare -A seen_repos
        local file_changed=0

        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
                echo "$line" >> "$temp_file"
                continue
            fi
            if [[ "$line" =~ ^deb ]]; then
                read -r _ url dist components <<< "$line"
                local key="${url}_${dist}"
                # Portable "is this associative-array key set?" — `[[ -v arr[key] ]]`
                # is only reliable in bash 4.4+; `${var+set}` works everywhere.
                if [[ -n "${seen_repos[$key]+set}" ]]; then
                    echo "# $line" >> "$temp_file"
                    cleaned_count=$((cleaned_count + 1))
                    file_changed=1
                    msg_info "$(translate "Commented duplicate: $url $dist")"
                else
                    echo "$line" >> "$temp_file"
                    seen_repos[$key]="$components"
                fi
            else
                echo "$line" >> "$temp_file"
            fi
        done < "$sources_file"

        if [[ "$file_changed" -eq 1 ]]; then
            _backup_once "$sources_file"
            mv "$temp_file" "$sources_file"
            chmod 644 "$sources_file"
        else
            rm -f "$temp_file"
        fi
    fi

    # ── Phase 2 — comment lines duplicating what proxmox.sources already declares ──
    # Comparison is EXACT on URL + Suite + at least one Component match, so a
    # legitimate custom repo the user added under `download.proxmox.com` (e.g.
    # /debian/pbs, /debian/ceph-squid, or the same URL pinned to a different
    # suite) is preserved untouched.
    if [ -f "/etc/apt/sources.list.d/proxmox.sources" ]; then
        local pmx_uri pmx_suite pmx_comps
        pmx_uri=$(_deb822_get /etc/apt/sources.list.d/proxmox.sources URIs)
        pmx_suite=$(_deb822_get /etc/apt/sources.list.d/proxmox.sources Suites)
        pmx_comps=$(_deb822_get /etc/apt/sources.list.d/proxmox.sources Components)

        _match_and_comment() {
            local target_file="$1" uri="$2" suite="$3" comps="$4"
            [[ -f "$target_file" ]] || return 0
            [[ -n "$uri" && -n "$suite" && -n "$comps" ]] || return 0
            local base_uri="${uri#http://}"
            base_uri="${base_uri#https://}"
            base_uri="${base_uri%/}"
            local first_comp
            first_comp=$(awk '{print $1}' <<< "$comps")
            local matched=0
            while IFS= read -r ln; do
                [[ "$ln" =~ ^[[:space:]]*# ]] && continue
                [[ "$ln" =~ ^deb ]] || continue
                read -r _ line_url line_suite line_comps <<< "$ln"
                local ln_base="${line_url#http://}"
                ln_base="${ln_base#https://}"
                ln_base="${ln_base%/}"
                [[ "$ln_base" == "$base_uri" ]] || continue
                [[ "$line_suite" == "$suite" ]] || continue
                [[ " $line_comps " == *" $first_comp "* ]] || continue
                matched=1
                break
            done < "$target_file"
            if [[ "$matched" -eq 1 ]]; then
                _backup_once "$target_file"
                # Anchored sed: reconstruct the exact deb prefix to avoid
                # eating unrelated lines. Escape URL for regex safety.
                local esc_uri esc_suite esc_comp
                esc_uri=$(printf '%s' "$uri" | sed 's/[][\.^$*/]/\\&/g')
                esc_suite=$(printf '%s' "$suite" | sed 's/[][\.^$*/]/\\&/g')
                esc_comp=$(printf '%s' "$first_comp" | sed 's/[][\.^$*/]/\\&/g')
                sed -i -E "/^deb[[:space:]]+${esc_uri}[[:space:]]+${esc_suite}[[:space:]]+.*(^| )${esc_comp}( |$)/s/^/# /" "$target_file"
                cleaned_count=$((cleaned_count + 1))
            fi
        }

        _match_and_comment "$sources_file" "$pmx_uri" "$pmx_suite" "$pmx_comps"

        # Only walk a fixed allowlist of known-legacy PVE list files. Any
        # other pve-*.list on disk is assumed to be user-authored (custom
        # mirror, backports, staging) and left alone.
        local legacy_pve_lists=(
            /etc/apt/sources.list.d/pve-public-repo.list
            /etc/apt/sources.list.d/pve-install-repo.list
            /etc/apt/sources.list.d/pve-no-subscription.list
        )
        for legacy in "${legacy_pve_lists[@]}"; do
            _match_and_comment "$legacy" "$pmx_uri" "$pmx_suite" "$pmx_comps"
        done

        # Same exact-match approach for debian.sources vs sources.list.
        if [ -f "/etc/apt/sources.list.d/debian.sources" ]; then
            local dbn_uri dbn_suite dbn_comps
            dbn_uri=$(_deb822_get /etc/apt/sources.list.d/debian.sources URIs)
            dbn_suite=$(_deb822_get /etc/apt/sources.list.d/debian.sources Suites)
            dbn_comps=$(_deb822_get /etc/apt/sources.list.d/debian.sources Components)
            # `Suites` in debian.sources holds multiple ("trixie trixie-updates"),
            # walk each so both duplicates get commented if present.
            for suite_iter in $dbn_suite; do
                _match_and_comment "$sources_file" "$dbn_uri" "$suite_iter" "$dbn_comps"
            done
        fi
    fi

    # ── Phase 3 — remove ONLY the well-known legacy files, and only when the
    # modern replacement already exists ──
    if [ -f "/etc/apt/sources.list.d/proxmox.sources" ]; then
        for old_file in /etc/apt/sources.list.d/pve-public-repo.list /etc/apt/sources.list.d/pve-install-repo.list; do
            if [ -f "$old_file" ]; then
                _backup_once "$old_file"
                rm -f "$old_file"
                cleaned_count=$((cleaned_count + 1))
            fi
        done
    fi

    if [ $cleaned_count -gt 0 ]; then
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate/old repositories")"
        apt-get update > /dev/null 2>&1 || true
    else
        msg_ok "$(translate "No duplicate repositories found")"
    fi
}
        


cleanup_duplicate_repos_pve9_() {
    msg_info "$(translate "Cleaning up duplicate repositories...")"
    
    local sources_file="/etc/apt/sources.list"
    local temp_file=$(mktemp)
    local cleaned_count=0
    declare -A seen_repos

    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
            echo "$line" >> "$temp_file"
            continue
        fi

        if [[ "$line" =~ ^deb ]]; then
            read -r _ url dist components <<< "$line"
            local key="${url}_${dist}"
            if [[ -n "${seen_repos[$key]+set}" ]]; then
                echo "# $line" >> "$temp_file"
                cleaned_count=$((cleaned_count + 1))
            else
                echo "$line" >> "$temp_file"
                seen_repos[$key]="$components"
            fi
        else
            echo "$line" >> "$temp_file"
        fi
    done < "$sources_file"

    mv "$temp_file" "$sources_file"
    chmod 644 "$sources_file"

    for src in proxmox debian ceph; do
        local sources_path="/etc/apt/sources.list.d/${src}.sources"
        if [ -f "$sources_path" ]; then
            case "$src" in
                proxmox)
                    url_match="download.proxmox.com"
                    ;;
                debian)
                    url_match="deb.debian.org"
                    ;;
                ceph)
                    url_match="download.proxmox.com/ceph"
                    ;;
                *)
                    url_match=""
                    ;;
            esac

            if [[ -n "$url_match" ]]; then
                if grep -q "^deb.*$url_match" "$sources_file"; then
                    sed -i "/^deb.*$url_match/s/^/# /" "$sources_file"
                    cleaned_count=$((cleaned_count + 1))
                fi
            fi

            for list_file in /etc/apt/sources.list.d/*.list; do
                [[ -f "$list_file" ]] || continue
                if grep -q "^deb.*$url_match" "$list_file"; then
                    sed -i "/^deb.*$url_match/s/^/# /" "$list_file"
                    cleaned_count=$((cleaned_count + 1))
                fi
            done
        fi
    done

    if [ $cleaned_count -gt 0 ]; then
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate/old repositories")"
        apt-get update > /dev/null 2>&1 || true
    else
        msg_ok "$(translate "No duplicate repositories found")"
    fi
}





cleanup_duplicate_repos_pve8() {
    msg_info "$(translate "Cleaning up duplicate repositories...")"

    local cleaned_count=0
    local sources_file="/etc/apt/sources.list"


    if [[ -f "$sources_file" ]]; then
        local temp_file
        temp_file=$(mktemp)
        declare -A seen_repos

        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
                echo "$line" >> "$temp_file"
                continue
            fi

            if [[ "$line" =~ ^[[:space:]]*deb ]]; then
                read -r _ url dist components <<< "$line"
                local key="${url}_${dist}"
                if [[ -n "${seen_repos[$key]+set}" ]]; then
                    echo "# $line" >> "$temp_file"
                    cleaned_count=$((cleaned_count + 1))
                else
                    echo "$line" >> "$temp_file"
                    seen_repos[$key]="$components"
                fi
            else
                echo "$line" >> "$temp_file"
            fi
        done < "$sources_file"

        mv "$temp_file" "$sources_file"
        chmod 644 "$sources_file"
    fi


    local old_pve_files=(/etc/apt/sources.list.d/pve-*.list /etc/apt/sources.list.d/proxmox.list)

    for file in "${old_pve_files[@]}"; do
        if [[ -f "$file" ]]; then
            local base_name
            base_name=$(basename "$file" .list)
            local sources_equiv="/etc/apt/sources.list.d/${base_name}.sources"

            if [[ -f "$sources_equiv" ]] && grep -q "^Enabled: *true" "$sources_equiv"; then
                msg_info "$(translate "Removing old repository file: $(basename "$file")")"
                rm -f "$file"
                cleaned_count=$((cleaned_count + 1))
            fi
        fi
    done


    if [ "$cleaned_count" -gt 0 ]; then
        msg_ok "$(translate "Cleaned up $cleaned_count duplicate/old repositories")"
        apt-get update > /dev/null 2>&1 || true
    else
        msg_ok "$(translate "No duplicate repositories found")"
    fi
}



cleanup_duplicate_repos() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if [[ "$pve_version" -ge 9 ]]; then
        cleanup_duplicate_repos_pve9
    else
        cleanup_duplicate_repos_pve8
    fi
}
