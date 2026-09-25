#!/bin/bash

set -euo pipefail

SCRIPT_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CUSTOM_SCRIPT="$SCRIPT_ROOT/customizable_post_install.sh"
UNINSTALL_SCRIPT="$SCRIPT_ROOT/uninstall-tools.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

assert_eq() {
    [[ "$1" == "$2" ]] || fail "expected '$2', got '$1'"
}

for script in "$CUSTOM_SCRIPT" "$UNINSTALL_SCRIPT"; do
    [[ -r "$script" ]] || fail "missing script: $script"
done

# Load only the function libraries. Redirecting the built-in installation
# paths keeps the test isolated from a real ProxMenux installation.
load_language() { :; }
initialize_cache() { :; }
translate() { printf '%s' "$1"; }
msg_info() { :; }
msg_info2() { :; }
msg_ok() { :; }
msg_warn() { :; }
msg_error() { :; }
msg_success() { :; }
show_proxmenux_logo() { :; }
clear() { :; }

sed \
    -e "s|^LOCAL_SCRIPTS=.*|LOCAL_SCRIPTS=\"$TEST_ROOT/missing-scripts\"|" \
    -e "s|^BASE_DIR=.*|BASE_DIR=\"$TEST_ROOT/state\"|" \
    -e "s|^UTILS_FILE=.*|UTILS_FILE=\"$TEST_ROOT/missing-utils.sh\"|" \
    -e "s|^TOOLS_JSON=.*|TOOLS_JSON=\"$TEST_ROOT/installed_tools.json\"|" \
    "$CUSTOM_SCRIPT" > "$TEST_ROOT/customizable.sh"
# shellcheck disable=SC1090
source "$TEST_ROOT/customizable.sh"

BASE_DIR="$TEST_ROOT/state"
TOOLS_JSON="$TEST_ROOT/installed_tools.json"
mkdir -p "$BASE_DIR"
printf '{}\n' > "$TOOLS_JSON"
REGISTRY_LOG="$TEST_ROOT/registry.log"
register_tool() { printf '%s|%s|%s\n' "$1" "$2" "${3:-}" >> "$REGISTRY_LOG"; }

# RPC: preserve asymmetric service/socket states and expose rollback even if
# a later disable operation were to fail.
declare -A UNIT_ENABLED=(
    [rpcbind.socket]="enabled"
    [rpcbind.service]="disabled"
)
declare -A UNIT_ACTIVE=(
    [rpcbind.socket]="active"
    [rpcbind.service]="inactive"
)

systemctl() {
    local action="$1"
    shift
    case "$action" in
        show)
            local unit="${@: -1}"
            printf 'loaded\n'
            ;;
        is-enabled)
            printf '%s\n' "${UNIT_ENABLED[$1]:-disabled}"
            ;;
        is-active)
            printf '%s\n' "${UNIT_ACTIVE[$1]:-inactive}"
            ;;
        disable)
            [[ "${1:-}" == "--now" ]] && shift
            local unit
            for unit in "$@"; do
                UNIT_ENABLED[$unit]="disabled"
                UNIT_ACTIVE[$unit]="inactive"
            done
            ;;
        enable)
            local runtime=false
            if [[ "${1:-}" == "--runtime" ]]; then
                runtime=true
                shift
            fi
            UNIT_ENABLED[$1]="$([[ "$runtime" == true ]] && printf 'enabled-runtime' || printf 'enabled')"
            ;;
        mask)
            local runtime=false
            if [[ "${1:-}" == "--runtime" ]]; then
                runtime=true
                shift
            fi
            UNIT_ENABLED[$1]="$([[ "$runtime" == true ]] && printf 'masked-runtime' || printf 'masked')"
            ;;
        start) UNIT_ACTIVE[$1]="active" ;;
        stop) UNIT_ACTIVE[$1]="inactive" ;;
        *) return 0 ;;
    esac
}

disable_rpc
grep -Fqx 'rpcbind.socket|enabled|active' "$BASE_DIR/rpcbind.state" || fail "rpcbind.socket state was not recorded"
grep -Fqx 'rpcbind.service|disabled|inactive' "$BASE_DIR/rpcbind.state" || fail "rpcbind.service state was not recorded"
grep -Fqx 'rpc|true|1.1' "$REGISTRY_LOG" || fail "RPC was not registered with version 1.1"
assert_eq "${UNIT_ENABLED[rpcbind.socket]}" "disabled"
assert_eq "${UNIT_ACTIVE[rpcbind.socket]}" "inactive"

# Source uninstall functions without launching their interactive menu.
sed \
    -e "s|^LOCAL_SCRIPTS=.*|LOCAL_SCRIPTS=\"$TEST_ROOT/missing-scripts\"|" \
    -e "s|^BASE_DIR=.*|BASE_DIR=\"$TEST_ROOT/state\"|" \
    -e "s|^UTILS_FILE=.*|UTILS_FILE=\"$TEST_ROOT/missing-utils.sh\"|" \
    -e "s|^TOOLS_JSON=.*|TOOLS_JSON=\"$TEST_ROOT/installed_tools.json\"|" \
    -e '/^show_uninstall_menu$/d' \
    "$UNINSTALL_SCRIPT" > "$TEST_ROOT/uninstall.sh"
# shellcheck disable=SC1090
source "$TEST_ROOT/uninstall.sh"
BASE_DIR="$TEST_ROOT/state"
TOOLS_JSON="$TEST_ROOT/installed_tools.json"
register_tool() { printf '%s|%s|%s\n' "$1" "$2" "${3:-}" >> "$REGISTRY_LOG"; }

uninstall_rpc
assert_eq "${UNIT_ENABLED[rpcbind.socket]}" "enabled"
assert_eq "${UNIT_ACTIVE[rpcbind.socket]}" "active"
assert_eq "${UNIT_ENABLED[rpcbind.service]}" "disabled"
assert_eq "${UNIT_ACTIVE[rpcbind.service]}" "inactive"
[[ ! -e "$BASE_DIR/rpcbind.state" ]] || fail "RPC state was not removed after a successful restore"

# MOTD: verify both an existing file and a previously absent file are
# restored byte-for-byte to their original state.
PROXMENUX_MOTD_FILE="$TEST_ROOT/motd"
export PROXMENUX_MOTD_FILE
printf 'Original line\n\nSecond line\n' > "$PROXMENUX_MOTD_FILE"
cp "$PROXMENUX_MOTD_FILE" "$TEST_ROOT/motd.expected"
rm -f "$BASE_DIR/motd.state" "$BASE_DIR/motd.original"
setup_motd
uninstall_motd
cmp -s "$PROXMENUX_MOTD_FILE" "$TEST_ROOT/motd.expected" || fail "existing MOTD was not restored exactly"

rm -f "$PROXMENUX_MOTD_FILE" "$BASE_DIR/motd.state" "$BASE_DIR/motd.original"
setup_motd
uninstall_motd
[[ ! -e "$PROXMENUX_MOTD_FILE" ]] || fail "previously absent MOTD was not removed on restore"

# System utilities: only packages absent before this invocation may be
# recorded for a later purge.
INSTALLED_PACKAGES="$TEST_ROOT/installed-packages"
printf 'curl\n' > "$INSTALLED_PACKAGES"
PROXMENUX_UTILS=(
    'curl:curl:curl client'
    'htop:htop:process viewer'
)
dialog() { printf '"curl" "htop"' >&2; }
ensure_repositories() { return 0; }
dpkg-query() {
    local package="${@: -1}"
    if grep -Fqx "$package" "$INSTALLED_PACKAGES"; then
        printf 'install ok installed\n'
        return 0
    fi
    return 1
}
install_single_package() {
    local package="$1"
    grep -Fqx "$package" "$INSTALLED_PACKAGES" || printf '%s\n' "$package" >> "$INSTALLED_PACKAGES"
    return 0
}
rm -f "$BASE_DIR/system_utils.packages"
install_system_utils
grep -Fqx 'htop' "$BASE_DIR/system_utils.packages" || fail "new utility was not tracked"
if grep -Fqx 'curl' "$BASE_DIR/system_utils.packages"; then
    fail "pre-existing utility was incorrectly tracked for removal"
fi

# Static contracts from the audit. Capture function bodies first so
# `set -o pipefail` cannot mistake grep -q's early exit for a failure in
# `declare -f` caused by SIGPIPE.
install_ceph_body="$(declare -f install_ceph)"
enable_kexec_body="$(declare -f enable_kexec)"
if grep -q 'apt-key' <<< "$install_ceph_body"; then
    fail "install_ceph still contains apt-key"
fi
grep -q 'Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg' <<< "$install_ceph_body" || fail "Ceph deb822 keyring is missing"
grep -q 'is already installed' <<< "$enable_kexec_body" || fail "kexec package state message is missing"
grep -q 'service file is already configured' <<< "$enable_kexec_body" || fail "kexec service state message is missing"
if grep -Eq '^[[:space:]]*(lvm_repair|repo_cleanup|apt_upgrade)\)' "$UNINSTALL_SCRIPT"; then
    fail "orphaned uninstall menu entries remain"
fi
if declare -F uninstall_apt_upgrade >/dev/null; then
    fail "unsafe apt full-upgrade uninstaller remains"
fi

printf 'PASS: post-install audit fixes\n'
