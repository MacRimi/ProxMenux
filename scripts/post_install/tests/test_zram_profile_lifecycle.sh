#!/bin/bash

set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_ROOT/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

CONFIG="$TEST_ROOT/etc/systemd/zram-generator.conf.d/90-proxmenux.conf"
MARKER="$TEST_ROOT/state/zram-swap.state"
SWAPS="$TEST_ROOT/proc/swaps"
FSTAB="$TEST_ROOT/etc/fstab"
EXPECTED_FSTAB="$TEST_ROOT/fstab.expected"
VERIFY_MODE=0
START_COUNT=0
PURGE_COUNT=0

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

load_language() { :; }
initialize_cache() { :; }
translate() { printf '%s' "$1"; }
msg_info() { :; }
msg_info2() { :; }
msg_ok() { :; }
msg_warn() { :; }
msg_error() { printf '%s\n' "$*" >&2; }
msg_success() { :; }
show_proxmenux_logo() { :; }
clear() { :; }
pmx_install_pkg() { return 1; }
pmx_record_uninstall() { :; }
apt-get() {
    if [[ "$*" == "purge -y systemd-zram-generator" ]]; then
        PURGE_COUNT=$((PURGE_COUNT + 1))
    fi
    return 0
}
pmx_journal_context() { :; }

dpkg-query() {
    case "$*" in
        *'${Status}'*) printf 'install ok installed\n' ;;
        *'${Version}'*) printf '1.2.0-1\n' ;;
        *) return 1 ;;
    esac
}

dpkg() {
    [[ "$1" == "--compare-versions" && "$3" == "ge" && "$2" == "1.2.0-1" && "$4" == "1.2.0" ]]
}

systemctl() {
    case "$1" in
        daemon-reload|stop) return 0 ;;
        start)
            START_COUNT=$((START_COUNT + 1))
            if [[ "${2:-}" == "dev-zram0.swap" ]] &&
               ! awk 'NR > 1 && $1 == "/dev/zram0" { found=1 } END { exit !found }' "$SWAPS"; then
                printf '/dev/zram0\tpartition\t3355443\t0\t32767\n' >> "$SWAPS"
            fi
            return 0
            ;;
        is-active) return 1 ;;
        *) return 0 ;;
    esac
}

swapoff() {
    local target="${1:-}" next="$TEST_ROOT/swaps.next"
    [[ -n "$target" ]] || fail "swapoff was called without a target"
    awk -v target="$target" 'NR == 1 || $1 != target' "$SWAPS" > "$next"
    mv "$next" "$SWAPS"
}

PMX_JOURNAL_ROOT="$TEST_ROOT/journal"
export PMX_JOURNAL_ROOT
source "$REPO_ROOT/scripts/global/pmx_journal.sh"

mkdir -p "$TEST_ROOT/host/scripts/post_install"
cp "$SCRIPT_ROOT/zram_profile_helpers.sh" "$TEST_ROOT/host/scripts/post_install/"

# Isolate only host paths; source the real installer function and helper library.
python3 - "$SCRIPT_ROOT/customizable_post_install.sh" "$TEST_ROOT/customizable.sh" "$TEST_ROOT" <<'PY'
from pathlib import Path
import sys

source_path, output_path, root = map(Path, sys.argv[1:])
text = source_path.read_text(encoding="utf-8")

def replace_exact(old, new, expected=1):
    global text
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"expected {expected} path substitutions, found {count}: {old}")
    text = text.replace(old, new)

replace_exact(
    'LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"',
    f'LOCAL_SCRIPTS="{root}/host/scripts"',
)
replace_exact(
    'BASE_DIR="/usr/local/share/proxmenux"',
    f'BASE_DIR="{root}/state"',
)
replace_exact(
    'UTILS_FILE="$BASE_DIR/utils.sh"',
    f'UTILS_FILE="{root}/missing-utils.sh"',
)
replace_exact(
    'TOOLS_JSON="/usr/local/share/proxmenux/installed_tools.json"',
    f'TOOLS_JSON="{root}/state/installed_tools.json"',
)
replace_exact(
    'local config=/etc/systemd/zram-generator.conf.d/90-proxmenux.conf',
    f'local config={root}/etc/systemd/zram-generator.conf.d/90-proxmenux.conf',
)
replace_exact(
    'if [[ ! -r /proc/swaps || ! -r /etc/fstab ]]; then',
    f'if [[ ! -r "{root}/proc/swaps" || ! -r "{root}/etc/fstab" ]]; then',
)
replace_exact(
    'zram_list_foreign_active_zram_swap /proc/swaps "$allowed_zram"',
    f'zram_list_foreign_active_zram_swap "{root}/proc/swaps" "$allowed_zram"',
)
replace_exact(
    'zram_list_foreign_fstab_zram_swap /etc/fstab',
    f'zram_list_foreign_fstab_zram_swap "{root}/etc/fstab"',
)
replace_exact(
    'zram_list_foreign_systemd_zram_units)',
    'zram_list_foreign_systemd_zram_units "$TEST_ROOT")',
)
replace_exact(
    'zram_foreign_generator_config "$config"',
    'zram_foreign_generator_config "$config" "$TEST_ROOT"',
    expected=3,
)
replace_exact(
    "awk 'NR > 1 && $1 == \"/dev/zram0\" { found=1 } END { exit !found }' /proc/swaps",
    f"awk 'NR > 1 && $1 == \"/dev/zram0\" {{ found=1 }} END {{ exit !found }}' \"{root}/proc/swaps\"",
    expected=2,
)
output_path.write_text(text, encoding="utf-8")
PY

# Isolate the real uninstall function and redirect only the paths it inspects.
python3 - "$SCRIPT_ROOT/uninstall-tools.sh" "$TEST_ROOT/uninstall-zram.sh" "$TEST_ROOT" <<'PY'
from pathlib import Path
import sys

source_path, output_path, root = map(Path, sys.argv[1:])
text = source_path.read_text(encoding="utf-8")
start = text.index("uninstall_zram_swap() {")
end = text.index("\n}\n", start) + 3
function = text[start:end]
replacements = {
    "local config=/etc/systemd/zram-generator.conf.d/90-proxmenux.conf":
        f"local config={root}/etc/systemd/zram-generator.conf.d/90-proxmenux.conf",
    'awk \'NR > 1 && $1 == "/dev/zram0" { found=1 } END { exit !found }\' /proc/swaps':
        f'awk \'NR > 1 && $1 == "/dev/zram0" {{ found=1 }} END {{ exit !found }}\' "{root}/proc/swaps"',
    'zram_foreign_generator_config "$config"':
        'zram_foreign_generator_config "$config" "$TEST_ROOT"',
    'zram_list_foreign_active_zram_swap /proc/swaps /dev/zram0':
        f'zram_list_foreign_active_zram_swap "{root}/proc/swaps" /dev/zram0',
    'zram_list_foreign_fstab_zram_swap /etc/fstab':
        f'zram_list_foreign_fstab_zram_swap "{root}/etc/fstab"',
    'zram_list_foreign_systemd_zram_units)':
        'zram_list_foreign_systemd_zram_units "$TEST_ROOT")',
}
for old, new in replacements.items():
    if function.count(old) != 1:
        raise SystemExit(f"expected one uninstall path to rewrite: {old}")
    function = function.replace(old, new)
output_path.write_text(function, encoding="utf-8")
PY

source "$TEST_ROOT/customizable.sh"
source "$TEST_ROOT/uninstall-zram.sh"
BASE_DIR="$TEST_ROOT/state"
TOOLS_JSON="$TEST_ROOT/state/installed_tools.json"
mkdir -p "$BASE_DIR"
register_tool() { printf '%s|%s|%s\n' "$1" "$2" "${3:-}" >> "$TEST_ROOT/registry.log"; }
zram_profile_verify_active() { return "$VERIFY_MODE"; }

reset_fixture() {
    rm -rf "$TEST_ROOT/etc" "$TEST_ROOT/run" "$TEST_ROOT/proc" "$BASE_DIR" "$TEST_ROOT/journal"
    mkdir -p "$TEST_ROOT/etc/systemd/system" "$TEST_ROOT/proc" "$BASE_DIR" "$TEST_ROOT/run/systemd/system"
    printf 'Filename\tType\tSize\tUsed\tPriority\n/dev/nvme0n1p3\tpartition\t1048576\t8\t-2\n' > "$SWAPS"
    printf '/dev/nvme0n1p3 none swap defaults 0 0\n/swapfile none swap sw 0 0\n' > "$FSTAB"
    cp "$FSTAB" "$EXPECTED_FSTAB"
    printf '[Swap]\nWhat=/dev/mapper/pve-swap\n' > "$TEST_ROOT/etc/systemd/system/pve-swap.swap"
    PMX_JOURNAL_ROOT="$TEST_ROOT/journal"
    START_COUNT=0
    PURGE_COUNT=0
    VERIFY_MODE=0
    : > "$TEST_ROOT/registry.log"
}

assert_disk_swap_unchanged() {
    cmp -s "$FSTAB" "$EXPECTED_FSTAB" || fail "installer changed fstab"
    grep -Fq '/dev/nvme0n1p3' "$SWAPS" || fail "active disk swap was removed"
}

reset_fixture
configure_zram_swap || fail "disk swap prevented ZRAM installation"
grep -Fq 'swap-priority = 32767' "$CONFIG" || fail "ZRAM priority is not maximal"
grep -Fq 'installed_by_proxmenux=false' "$MARKER" || fail "package ownership was not preserved"
grep -Fq '/dev/zram0' "$SWAPS" || fail "ZRAM did not become active"
assert_disk_swap_unchanged

configure_zram_swap || fail "owned ZRAM profile could not be re-applied with disk swap"
[[ "$START_COUNT" -eq 1 ]] || fail "matching owned profile was not idempotent"
assert_disk_swap_unchanged
printf 'PASS: disk swap coexists and owned profile is idempotent\n'

reset_fixture
printf '/dev/zram1 none swap defaults 0 0\n' >> "$FSTAB"
cp "$FSTAB" "$EXPECTED_FSTAB"
if configure_zram_swap; then
    fail "foreign fstab ZRAM entry was accepted"
fi
[[ ! -e "$CONFIG" && ! -e "$MARKER" ]] || fail "foreign fstab ZRAM entry left partial profile state"
assert_disk_swap_unchanged
printf 'PASS: foreign fstab ZRAM setup is refused without changing disk swap\n'

reset_fixture
printf '%s\n' '[Swap]' 'What=/dev/zram1' > "$TEST_ROOT/etc/systemd/system/external-zram.swap"
if configure_zram_swap; then
    fail "foreign systemd ZRAM unit was accepted"
fi
[[ ! -e "$CONFIG" && ! -e "$MARKER" ]] || fail "foreign systemd ZRAM unit left partial profile state"
assert_disk_swap_unchanged
printf 'PASS: foreign systemd ZRAM unit is refused without changing disk swap\n'

reset_fixture
VERIFY_MODE=1
if configure_zram_swap; then
    fail "activation verification failure was reported as success"
fi
[[ ! -e "$CONFIG" && ! -e "$MARKER" ]] || fail "failed activation left partial profile state"
if awk 'NR > 1 && $1 == "/dev/zram0" { found=1 } END { exit !found }' "$SWAPS"; then
    fail "rollback left the failed ZRAM device active"
fi
assert_disk_swap_unchanged
printf 'PASS: verification failure rolls back only the ProxMenux ZRAM state\n'

reset_fixture
mkdir -p "$(dirname "$CONFIG")"
printf '# ProxMenux ZRAM profile\n[zram0]\nzram-size = ram / 10\n' > "$CONFIG"
printf 'installed_by_proxmenux=true\n' > "$MARKER"
printf '/dev/zram1 none swap defaults 0 0\n' >> "$FSTAB"
printf '[Swap]\nWhat=/dev/zram2\n' > "$TEST_ROOT/etc/systemd/system/external-zram.swap"
cp "$FSTAB" "$EXPECTED_FSTAB"
uninstall_zram_swap || fail "profile uninstall failed with foreign ZRAM configuration"
[[ "$PURGE_COUNT" -eq 0 ]] || fail "uninstaller purged generator while foreign ZRAM config exists"
[[ ! -e "$CONFIG" && ! -e "$MARKER" ]] || fail "uninstaller left ProxMenux profile files behind"
assert_disk_swap_unchanged
printf 'PASS: uninstall retains generator when foreign ZRAM config exists\n'

reset_fixture
mkdir -p "$(dirname "$CONFIG")"
printf '# ProxMenux ZRAM profile\n[zram0]\nzram-size = ram / 10\n' > "$CONFIG"
printf 'installed_by_proxmenux=true\n' > "$MARKER"
printf '%s\n' '[Swap]' 'What=/dev/zram2' > "$TEST_ROOT/etc/systemd/system/external-zram.swap"
uninstall_zram_swap || fail "profile uninstall failed with foreign systemd ZRAM unit"
[[ "$PURGE_COUNT" -eq 0 ]] || fail "uninstaller purged generator while foreign systemd ZRAM unit exists"
assert_disk_swap_unchanged
printf 'PASS: uninstall retains generator for foreign systemd ZRAM unit\n'

reset_fixture
mkdir -p "$(dirname "$CONFIG")"
printf '# ProxMenux ZRAM profile\n[zram0]\nzram-size = ram / 10\n' > "$CONFIG"
printf 'installed_by_proxmenux=true\n' > "$MARKER"
printf '/dev/zram0\tpartition\t3355443\t8\t32767\n' >> "$SWAPS"
uninstall_zram_swap || fail "owned profile could not be uninstalled"
[[ "$PURGE_COUNT" -eq 1 ]] || fail "owned generator package was not purged"
if awk 'NR > 1 && $1 == "/dev/zram0" { found=1 } END { exit !found }' "$SWAPS"; then
    fail "uninstaller left ProxMenux ZRAM active"
fi
assert_disk_swap_unchanged
printf 'PASS: uninstall removes owned ZRAM and preserves disk swap\n'
