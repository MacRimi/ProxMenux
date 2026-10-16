#!/usr/bin/env bash
# Pure helpers shared by the ZRAM installer and its fixture tests.

# The kernel's maximum priority puts ZRAM ahead of standard Proxmox swap.
# A disk swap explicitly configured at this same maximum cannot be outranked.
if ! declare -p ZRAM_SWAP_PRIORITY >/dev/null 2>&1; then
    readonly ZRAM_SWAP_PRIORITY=32767
fi

zram_render_generator_config() {
    local algorithm=zstd
    [[ "${1:-false}" == true ]] && algorithm='zstd(level=9)'
    cat <<EOF
# ProxMenux ZRAM profile
[zram0]
zram-size = ram / 10
compression-algorithm = $algorithm
swap-priority = $ZRAM_SWAP_PRIORITY
EOF
}

zram_list_foreign_active_zram_swap() {
    local swaps_file="$1" owned_device="${2:-}"
    local swap_paths swap_path real_device
    [[ -r "$swaps_file" ]] || return 2
    swap_paths="$(awk 'NR > 1 { print $1 }' "$swaps_file")" || return 2
    while IFS= read -r swap_path; do
        [[ -z "$swap_path" ]] && continue
        real_device="$(readlink -f -- "$swap_path" 2>/dev/null)" || real_device="$swap_path"
        if [[ "$real_device" =~ ^/dev/zram[0-9]+$ && "$real_device" != "$owned_device" ]]; then
            printf 'active zram: %s\n' "$swap_path"
        fi
    done <<< "$swap_paths"
}

zram_list_foreign_fstab_zram_swap() {
    local fstab_file="$1"
    [[ -r "$fstab_file" ]] || return 2
    awk '
        $0 !~ /^[[:space:]]*#/ && NF >= 3 && $3 == "swap" && $1 ~ /^\/dev\/zram[0-9]+$/ {
            print "fstab zram: " $1
        }
    ' "$fstab_file"
}

# Print generator configuration outside this feature's dedicated drop-in.
zram_foreign_generator_config() {
    local owned_file="$1" fixture_root="${2:-}" root file
    local roots=(/etc/systemd /run/systemd /usr/local/lib/systemd /usr/lib/systemd /lib/systemd)
    if [[ -n "$fixture_root" ]]; then
        roots=("$fixture_root/etc/systemd" "$fixture_root/run/systemd" "$fixture_root/usr/local/lib/systemd" "$fixture_root/usr/lib/systemd" "$fixture_root/lib/systemd")
    fi
    for root in "${roots[@]}"; do
        for file in "$root/zram-generator.conf" "$root"/zram-generator.conf.d/*.conf; do
            [[ -e "$file" || -L "$file" ]] || continue
            [[ "$file" == "$owned_file" ]] && continue
            # Ignore package defaults containing only comments, whitespace and
            # section headers. Any directive or malformed active line is foreign.
            local active
            active="$(awk '
                {
                    line=$0
                    sub(/^[[:space:]]+/, "", line)
                    sub(/[[:space:]]+$/, "", line)
                    if (line == "" || line ~ /^[#;]/ || line ~ /^\[[^]]+\]$/) next
                    found=1
                }
                END { if (found) print "active" }
            ' "$file")" || return 2
            if [[ -n "$active" ]]; then
                printf '%s\n' "$file"
            fi
        done
    done
}

zram_list_foreign_systemd_zram_units() {
    local fixture_root="${1:-}" root file unit what unit_files
    local roots=(/etc/systemd/system /run/systemd/system /usr/local/lib/systemd/system /usr/lib/systemd/system /lib/systemd/system)
    if [[ -n "$fixture_root" ]]; then
        roots=("$fixture_root/etc/systemd/system" "$fixture_root/run/systemd/system" "$fixture_root/usr/local/lib/systemd/system" "$fixture_root/usr/lib/systemd/system" "$fixture_root/lib/systemd/system")
    fi
    for root in "${roots[@]}"; do
        [[ -d "$root" ]] || continue
        # Skip activation links; systemd-generator creates links under
        # *.wants and they must not look like foreign unit definitions.
        unit_files="$(find "$root" \( -type d \( -name '*.wants' -o -name '*.requires' \) -prune \) -o \( \( -name '*.swap' -o -path '*.swap.d/*.conf' \) \( -type f -o -type l \) -print \) 2>/dev/null)" || return 2
        while IFS= read -r file; do
            [[ -z "$file" ]] && continue
            unit="$(basename "$file")"
            if [[ -L "$file" && "$(readlink -f -- "$file" 2>/dev/null || true)" == /dev/null ]]; then
                if [[ "$unit" == "dev-zram0.swap" ]]; then
                    printf 'systemd zram unit masked: %s\n' "$file"
                fi
                continue
            fi
            # A persistent unit named for a zram device could shadow the
            # generated unit, even if it currently points at another device.
            what="$(awk '
                /^[[:space:]]*\[Swap\][[:space:]]*$/ { in_swap=1; next }
                /^[[:space:]]*\[/ { in_swap=0 }
                in_swap && /^[[:space:]]*What[[:space:]]*=[[:space:]]*\/dev\/zram[0-9]+([[:space:]]|$)/ {
                    found=1
                }
                END { if (found) print "zram" }
            ' "$file")" || return 2
            if [[ "$unit" =~ ^dev-zram[0-9]+\.swap$ || -n "$what" ]]; then
                printf 'systemd zram unit: %s\n' "$file"
            fi
        done <<< "$unit_files"
    done
}

zram_profile_verify_active() {
    local expected_algorithm="$1" expected_priority="${2:-$ZRAM_SWAP_PRIORITY}"
    local sys_block_root="${3:-/sys/block}" meminfo_path="${4:-/proc/meminfo}" swaps_path="${5:-/proc/swaps}"
    local zram0="$sys_block_root/zram0" expected_bytes actual_bytes active_algorithm

    [[ -r "$zram0/disksize" && -r "$zram0/comp_algorithm" && -r "$meminfo_path" && -r "$swaps_path" ]] || return 1
    expected_bytes="$(awk '/^MemTotal:/ { print int($2 * 1024 / 10) }' "$meminfo_path")"
    actual_bytes="$(cat "$zram0/disksize")"
    [[ "$expected_bytes" =~ ^[0-9]+$ && "$actual_bytes" =~ ^[0-9]+$ ]] || return 1
    (( actual_bytes >= expected_bytes - 1048576 && actual_bytes <= expected_bytes + 1048576 )) || return 1
    active_algorithm="$(grep -oE '\[[^]]+\]' "$zram0/comp_algorithm" | tr -d '[]')"
    [[ "$active_algorithm" == "$expected_algorithm" ]] || return 1
    awk -v priority="$expected_priority" '
        NR > 1 && $1 == "/dev/zram0" {
            found=1
            if ($5 + 0 != priority + 0) bad=1
        }
        NR > 1 && $1 ~ /^\/dev\/zram[0-9]+$/ && $1 != "/dev/zram0" { bad=1 }
        END { exit !(found && !bad) }
    ' "$swaps_path"
}
