#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
RUNNER="$REPO_ROOT/scripts/lxc/apply_updates.sh"
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/proxmenux-update-test.XXXXXX")
trap 'rm -rf "$TEST_ROOT"' EXIT
MOCK_BIN="$TEST_ROOT/bin"
mkdir -p "$MOCK_BIN" "$TEST_ROOT/locks"

cat >"$MOCK_BIN/pct" <<'EOF'
#!/bin/bash
echo "pct $*" >>"$MOCK_LOG"
case "$1" in
  list)
    printf 'VMID Status Name\n101 %s test\n' "${MOCK_INITIAL_STATE:-running}"
    ;;
  status)
    printf 'status: %s\n' "${MOCK_INITIAL_STATE:-running}"
    ;;
  start|shutdown|reboot)
    ;;
  exec)
    shift 3
    joined="$*"
    case "$joined" in
      *'grep -E "^ID="'*) echo 'ID=debian' ;;
      'test -f /usr/bin/update') [[ "${MOCK_HAS_WRAPPER:-1}" == "1" ]] ;;
      'cat /usr/bin/update')
        case "${MOCK_WRAPPER_FORMAT:-legacy}" in
          modern)
            printf '%s\n' \
              '#!/usr/bin/env bash' \
              '# Regenerated on install and on every successful update.' \
              "export SCRIPT_SLUG=\"${MOCK_HELPER_SLUG:-jellyfin}\"" \
              "export UPDATE_SCRIPT_NAME=\"${MOCK_HELPER_SLUG:-jellyfin}\"" \
              'bash -c "$(curl -fsSL "${COMMUNITY_SCRIPTS_URL}/ct/${UPDATE_SCRIPT_NAME}.sh")"'
            ;;
          update-name)
            printf "export UPDATE_SCRIPT_NAME='%s'\n" "${MOCK_HELPER_SLUG:-jellyfin}"
            ;;
          unsafe)
            printf '%s\n' 'export SCRIPT_SLUG="$(touch /tmp/proxmenux-unsafe)"'
            ;;
          *)
            echo "bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/${MOCK_HELPER_SLUG:-jellyfin}.sh)\""
            ;;
        esac
        ;;
      *'command -v wget'*) ;;
      bash\ -c*) echo HELPER_EXEC >>"$MOCK_LOG" ;;
      sh\ -c*)
        echo CUSTOM_EXEC >>"$MOCK_LOG"
        [[ "${MOCK_CUSTOM_FAIL:-0}" != "1" ]]
        ;;
      env\ DEBIAN_FRONTEND=noninteractive*) echo OS_EXEC >>"$MOCK_LOG" ;;
    esac
    ;;
esac
EOF

cat >"$MOCK_BIN/flock" <<'EOF'
#!/bin/bash
[[ "${MOCK_FLOCK_FAIL:-0}" != "1" ]]
EOF

cat >"$MOCK_BIN/python3" <<'EOF'
#!/bin/bash
cat >/dev/null
if [[ "${2:-}" == 'protect-update-command' ]]; then
  printf '%s' "$UPDATE_COMMAND"
  exit 0
fi
[[ "${MOCK_HELPER_SELECTED:-1}" == "1" ]]
EOF

cat >"$MOCK_BIN/sleep" <<'EOF'
#!/bin/bash
exit 0
EOF

cat >"$MOCK_BIN/vzdump" <<'EOF'
#!/bin/bash
echo "vzdump $*" >>"$MOCK_LOG"
EOF
chmod +x "$MOCK_BIN"/*

fail() { echo "FAIL: $*" >&2; exit 1; }
count() { grep -c "$1" "$MOCK_LOG" 2>/dev/null || true; }

run_case() {
  local name=$1
  shift
  export MOCK_LOG="$TEST_ROOT/$name.log"
  : >"$MOCK_LOG"
  set +e
  env PATH="$MOCK_BIN:$PATH" PROXMENUX_LOCK_DIR="$TEST_ROOT/locks" \
    VMID=101 TARGET=app BACKUP=0 RESTART=0 "$@" bash "$RUNNER" \
    >"$TEST_ROOT/$name.out" 2>&1
  CASE_RC=$?
  set -e
}

run_case helper_only RUN_HELPER=1 UPDATE_COMMAND=
[[ $CASE_RC -eq 0 ]] || fail "helper_only returned $CASE_RC"
[[ $(count HELPER_EXEC) -eq 1 ]] || fail "helper_only did not run helper exactly once"
[[ $(count CUSTOM_EXEC) -eq 0 ]] || fail "helper_only unexpectedly ran custom"

run_case helper_not_selected RUN_HELPER=1 UPDATE_COMMAND= MOCK_HELPER_SELECTED=0
[[ $CASE_RC -eq 5 ]] || fail "helper_not_selected expected 5, got $CASE_RC"
[[ $(count HELPER_EXEC) -eq 0 ]] || fail "unselected helper was executed"

run_case modern_helper RUN_HELPER=1 UPDATE_COMMAND= MOCK_WRAPPER_FORMAT=modern MOCK_HELPER_SLUG=nginxproxymanager
[[ $CASE_RC -eq 0 ]] || fail "modern_helper returned $CASE_RC"
[[ $(count HELPER_EXEC) -eq 1 ]] || fail "modern_helper did not run helper exactly once"
grep -qF 'slug: nginxproxymanager' "$TEST_ROOT/modern_helper.out" \
  || fail "modern_helper did not resolve SCRIPT_SLUG"

run_case update_name_helper RUN_HELPER=1 UPDATE_COMMAND= MOCK_WRAPPER_FORMAT=update-name MOCK_HELPER_SLUG=qbittorrent
[[ $CASE_RC -eq 0 ]] || fail "update_name_helper returned $CASE_RC"
[[ $(count HELPER_EXEC) -eq 1 ]] || fail "update_name_helper did not run helper exactly once"
grep -qF 'slug: qbittorrent' "$TEST_ROOT/update_name_helper.out" \
  || fail "update_name_helper did not resolve UPDATE_SCRIPT_NAME"

run_case unsafe_wrapper RUN_HELPER=1 UPDATE_COMMAND= MOCK_WRAPPER_FORMAT=unsafe
[[ $CASE_RC -eq 5 ]] || fail "unsafe_wrapper expected 5, got $CASE_RC"
[[ $(count HELPER_EXEC) -eq 0 ]] || fail "unsafe_wrapper ran helper"
[[ ! -e /tmp/proxmenux-unsafe ]] || fail "unsafe_wrapper evaluated CT content"

run_case custom_override RUN_HELPER=0 UPDATE_COMMAND='update-custom'
[[ $CASE_RC -eq 0 ]] || fail "custom_override returned $CASE_RC"
[[ $(count HELPER_EXEC) -eq 0 ]] || fail "custom_override unexpectedly ran helper"
[[ $(count CUSTOM_EXEC) -eq 1 ]] || fail "custom_override did not run custom exactly once"

run_case custom_replaces_helper RUN_HELPER=1 UPDATE_COMMAND='replace-helper'
[[ $CASE_RC -eq 0 ]] || fail "custom_replaces_helper returned $CASE_RC"
[[ $(count HELPER_EXEC) -eq 0 ]] || fail "custom_replaces_helper unexpectedly ran helper"
[[ $(count CUSTOM_EXEC) -eq 1 ]] || fail "custom_replaces_helper did not run custom exactly once"
grep -qF 'skipping Proxmox VE Helper-Scripts updater' "$TEST_ROOT/custom_replaces_helper.out" \
  || fail "custom_replaces_helper did not report the replacement rule"

run_case explicit_multi_app RUN_HELPER=1 ALLOW_HELPER_WITH_CUSTOM=1 UPDATE_COMMAND='update-another-app'
[[ $CASE_RC -eq 0 ]] || fail "explicit_multi_app returned $CASE_RC"
[[ $(count HELPER_EXEC) -eq 1 ]] || fail "explicit_multi_app did not run helper exactly once"
[[ $(count CUSTOM_EXEC) -eq 1 ]] || fail "explicit_multi_app did not run custom exactly once"

run_case missing_wrapper RUN_HELPER=1 UPDATE_COMMAND= MOCK_HAS_WRAPPER=0
[[ $CASE_RC -eq 5 ]] || fail "missing_wrapper expected 5, got $CASE_RC"
[[ $(count HELPER_EXEC) -eq 0 ]] || fail "missing_wrapper ran helper"

run_case base_os_wrapper RUN_HELPER=1 UPDATE_COMMAND= MOCK_HELPER_SLUG=debian
[[ $CASE_RC -eq 5 ]] || fail "base_os_wrapper expected 5, got $CASE_RC"
[[ $(count HELPER_EXEC) -eq 0 ]] || fail "base_os_wrapper ran helper"

run_case stopped_restore RUN_HELPER=0 UPDATE_COMMAND='update-custom' MOCK_INITIAL_STATE=stopped
[[ $CASE_RC -eq 0 ]] || fail "stopped_restore returned $CASE_RC"
[[ $(count 'pct start 101') -eq 1 ]] || fail "stopped CT was not started exactly once"
[[ $(count 'pct shutdown 101 --timeout 60') -eq 1 ]] || fail "stopped CT state was not restored"

run_case locked RUN_HELPER=0 UPDATE_COMMAND='update-custom' MOCK_FLOCK_FAIL=1
[[ $CASE_RC -eq 7 ]] || fail "locked expected 7, got $CASE_RC"
[[ $(count CUSTOM_EXEC) -eq 0 ]] || fail "locked run executed an updater"

echo "apply_updates.sh: all deterministic tests passed"
