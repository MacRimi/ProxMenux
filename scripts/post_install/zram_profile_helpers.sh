#!/usr/bin/env bash
# Pure helpers shared by the ZRAM installer and its fixture tests.

zram_render_generator_config() {
    local algorithm=zstd
    [[ "${1:-false}" == true ]] && algorithm='zstd(level=9)'
    cat <<EOF
# ProxMenux ZRAM profile
[zram0]
zram-size = ram / 10
compression-algorithm = $algorithm
swap-priority = 100
EOF
}

zram_list_non_zram_swap() {
    local swaps_file="$1" fstab_file="$2"
    awk 'NR > 1 && $1 !~ /^\/dev\/zram[0-9]+$/ { print "active: " $1 }' "$swaps_file"
    awk '$0 !~ /^[[:space:]]*#/ && NF >= 3 && $3 == "swap" && $1 !~ /^\/dev\/zram[0-9]+$/ { print "fstab: " $1 }' "$fstab_file"
}

zram_has_non_zram_swap() {
    [[ -r "$1" && -r "$2" ]] || return 2
    [[ -n "$(zram_list_non_zram_swap "$1" "$2")" ]]
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
            if awk '
                {
                    line=$0
                    sub(/^[[:space:]]+/, "", line)
                    sub(/[[:space:]]+$/, "", line)
                    if (line == "" || line ~ /^[#;]/ || line ~ /^\[[^]]+\]$/) next
                    found=1
                }
                END { exit !found }
            ' "$file"; then
                printf '%s\n' "$file"
            fi
        done
    done
}

zram_list_defined_systemd_swap_units() {
    local fixture_root="${1:-}" root file
    local roots=(/etc/systemd/system /run/systemd/system)
    if [[ -n "$fixture_root" ]]; then
        roots=("$fixture_root/etc/systemd/system" "$fixture_root/run/systemd/system")
    fi
    for root in "${roots[@]}"; do
        [[ -d "$root" ]] || continue
        while IFS= read -r file; do
            # Files in these roots are administrator-defined units. The
            # generator's own output lives under /run/systemd/generator and
            # is intentionally outside this scan.
            printf 'systemd: %s\n' "$file"
        done < <(find "$root" -name '*.swap' \( -type f -o -type l \) -print 2>/dev/null)
    done
}
