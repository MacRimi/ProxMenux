#!/bin/bash
# ==========================================================
# ProxMenux - Backup/Restore Test Matrix (non-destructive)
# ==========================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="${SCRIPT_DIR}/run_scheduled_backup.sh"
APPLY_ONBOOT="${SCRIPT_DIR}/apply_pending_restore.sh"
CLUSTER_APPLY="${SCRIPT_DIR}/apply_cluster_postboot.sh"
HOST_SCRIPT="${SCRIPT_DIR}/backup_host.sh"
LIB_SCRIPT="${SCRIPT_DIR}/lib_host_backup_common.sh"
SCHED_SCRIPT="${SCRIPT_DIR}/backup_scheduler.sh"

KEEP_TMP=0
if [[ "${1:-}" == "--keep-tmp" ]]; then
  KEEP_TMP=1
fi

TMP_ROOT="$(mktemp -d /tmp/proxmenux-brtest.XXXXXX)"
REPORT_FILE="/tmp/proxmenux-backup-restore-test-$(date +%Y%m%d_%H%M%S).log"

PASS=0
FAIL=0
SKIP=0

log() {
  echo "$*" | tee -a "$REPORT_FILE"
}

pass() {
  PASS=$((PASS + 1))
  log "[PASS] $*"
}

fail() {
  FAIL=$((FAIL + 1))
  log "[FAIL] $*"
}

skip() {
  SKIP=$((SKIP + 1))
  log "[SKIP] $*"
}

cleanup() {
  if [[ "$KEEP_TMP" -eq 0 ]]; then
    rm -rf "$TMP_ROOT"
  else
    log "[INFO] Temp root preserved: $TMP_ROOT"
  fi
}
trap cleanup EXIT

assert_file_contains() {
  local file="$1"
  local needle="$2"
  if [[ -f "$file" ]] && grep -q "$needle" "$file"; then
    return 0
  fi
  return 1
}

run_cmd_expect_ok() {
  local desc="$1"
  shift
  if "$@" >>"$REPORT_FILE" 2>&1; then
    pass "$desc"
    return 0
  fi
  fail "$desc"
  return 1
}

run_cmd_expect_fail() {
  local desc="$1"
  shift
  if "$@" >>"$REPORT_FILE" 2>&1; then
    fail "$desc"
    return 1
  fi
  pass "$desc"
  return 0
}

syntax_tests() {
  log "\n=== Syntax checks ==="
  run_cmd_expect_ok "bash -n backup_host.sh" bash -n "$HOST_SCRIPT"
  run_cmd_expect_ok "bash -n lib_host_backup_common.sh" bash -n "$LIB_SCRIPT"
  run_cmd_expect_ok "bash -n backup_scheduler.sh" bash -n "$SCHED_SCRIPT"
  run_cmd_expect_ok "bash -n run_scheduled_backup.sh" bash -n "$RUNNER"
  run_cmd_expect_ok "bash -n apply_pending_restore.sh" bash -n "$APPLY_ONBOOT"
  run_cmd_expect_ok "bash -n apply_cluster_postboot.sh" bash -n "$CLUSTER_APPLY"
}

certificate_restore_tests() {
  log "\n=== Custom pveproxy certificate restore (sandbox) ==="
  if ! command -v openssl >/dev/null 2>&1; then
    skip "Certificate restore tests require openssl."
    return
  fi

  local fixture="$TMP_ROOT/certificate-restore"
  local source_node="$fixture/source-node"
  local empty_node="$fixture/empty-node"
  local active_dir="$fixture/active"
  local bin_dir="$fixture/bin"
  local call_log="$fixture/pvenode.calls"
  mkdir -p "$source_node" "$empty_node" "$active_dir" "$bin_dir"

  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=proxmenux-restore-test' \
    -keyout "$source_node/pveproxy-ssl.key" \
    -out "$source_node/pveproxy-ssl.pem" >>"$REPORT_FILE" 2>&1
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
    -out "$fixture/mismatched.key" >>"$REPORT_FILE" 2>&1

  cat > "$bin_dir/pvenode" <<'EOS'
#!/bin/bash
printf '%s\n' "$*" >> "$PMX_TEST_CALL_LOG"
[[ "${PMX_TEST_PVENODE_FAIL:-0}" == "1" ]] && exit 1
if [[ "$1 $2" == "cert set" ]]; then
  cp "$3" "$PMX_PVEPROXY_CERT_PATH"
  cp "$4" "$PMX_PVEPROXY_KEY_PATH"
elif [[ "$1 $2" == "cert delete" ]]; then
  rm -f "$PMX_PVEPROXY_CERT_PATH" "$PMX_PVEPROXY_KEY_PATH"
fi
EOS
  cat > "$bin_dir/systemctl" <<'EOS'
#!/bin/bash
[[ "${PMX_TEST_SERVICE_INACTIVE:-0}" == "1" ]] && exit 1
[[ "$1 $2 $3" == "is-active --quiet pveproxy.service" ]]
EOS
  chmod +x "$bin_dir/pvenode" "$bin_dir/systemctl"

  export PMX_PVENODE_BIN="$bin_dir/pvenode"
  export PMX_SYSTEMCTL_BIN="$bin_dir/systemctl"
  export PMX_PVEPROXY_CERT_PATH="$active_dir/pveproxy-ssl.pem"
  export PMX_PVEPROXY_KEY_PATH="$active_dir/pveproxy-ssl.key"
  export PMX_TEST_CALL_LOG="$call_log"
  export PMX_PVEPROXY_VERIFY_ATTEMPTS=1

  if (
    PMX_CERT_HELPER_ONLY=1
    source "$CLUSTER_APPLY"
    _restore_pveproxy_certificate "$source_node"
  ) >>"$REPORT_FILE" 2>&1; then
    local source_fp active_fp
    source_fp=$(openssl x509 -in "$source_node/pveproxy-ssl.pem" -noout -sha256 -fingerprint)
    active_fp=$(openssl x509 -in "$PMX_PVEPROXY_CERT_PATH" -noout -sha256 -fingerprint)
    if [[ "$source_fp" == "$active_fp" ]] \
      && assert_file_contains "$call_log" "cert set .* --force 1 --restart 1"; then
      pass "Valid custom certificate is installed through pvenode and verified"
    else
      fail "Valid custom certificate was not installed as expected"
    fi
  else
    fail "Valid custom certificate restore failed"
  fi

  rm -f "$call_log"
  if (
    PMX_CERT_HELPER_ONLY=1
    source "$CLUSTER_APPLY"
    _restore_pveproxy_certificate "$empty_node"
  ) >>"$REPORT_FILE" 2>&1 && [[ ! -e "$call_log" ]]; then
    pass "Backup without a custom certificate leaves the current certificate unchanged"
  else
    fail "Empty certificate backup unexpectedly changed the current certificate"
  fi

  local active_before
  active_before=$(openssl x509 -in "$PMX_PVEPROXY_CERT_PATH" -noout -sha256 -fingerprint)
  mv "$source_node/pveproxy-ssl.key" "$fixture/source.key"
  rm -f "$call_log"
  if ! (
    PMX_CERT_HELPER_ONLY=1
    source "$CLUSTER_APPLY"
    _restore_pveproxy_certificate "$source_node"
  ) >>"$REPORT_FILE" 2>&1 \
    && [[ ! -e "$call_log" ]] \
    && [[ "$active_before" == "$(openssl x509 -in "$PMX_PVEPROXY_CERT_PATH" -noout -sha256 -fingerprint)" ]]; then
    pass "Incomplete certificate pair is rejected without changing the active certificate"
  else
    fail "Incomplete certificate pair was not rejected safely"
  fi

  cp "$fixture/mismatched.key" "$source_node/pveproxy-ssl.key"
  rm -f "$call_log"
  if ! (
    PMX_CERT_HELPER_ONLY=1
    source "$CLUSTER_APPLY"
    _restore_pveproxy_certificate "$source_node"
  ) >>"$REPORT_FILE" 2>&1 \
    && [[ ! -e "$call_log" ]] \
    && [[ "$active_before" == "$(openssl x509 -in "$PMX_PVEPROXY_CERT_PATH" -noout -sha256 -fingerprint)" ]]; then
    pass "Mismatched certificate pair is rejected without changing the active certificate"
  else
    fail "Mismatched certificate pair was not rejected safely"
  fi

  local replacement_node="$fixture/replacement-node"
  mkdir -p "$replacement_node"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=proxmenux-rollback-test' \
    -keyout "$replacement_node/pveproxy-ssl.key" \
    -out "$replacement_node/pveproxy-ssl.pem" >>"$REPORT_FILE" 2>&1
  rm -f "$call_log"
  export PMX_TEST_SERVICE_INACTIVE=1
  if ! (
    PMX_CERT_HELPER_ONLY=1
    source "$CLUSTER_APPLY"
    _restore_pveproxy_certificate "$replacement_node"
  ) >>"$REPORT_FILE" 2>&1 \
    && [[ "$active_before" == "$(openssl x509 -in "$PMX_PVEPROXY_CERT_PATH" -noout -sha256 -fingerprint)" ]] \
    && [[ "$(grep -c '^cert set ' "$call_log" 2>/dev/null)" == "2" ]]; then
    pass "Failed post-install verification restores the previous certificate"
  else
    fail "Certificate rollback did not restore the previous active pair"
  fi
  unset PMX_TEST_SERVICE_INACTIVE

  unset PMX_PVENODE_BIN PMX_SYSTEMCTL_BIN PMX_PVEPROXY_CERT_PATH \
    PMX_PVEPROXY_KEY_PATH PMX_TEST_CALL_LOG PMX_PVEPROXY_VERIFY_ATTEMPTS
}

staging_state_tests() {
  log "\n=== Staging state and custom paths ==="
  # shellcheck source=/dev/null
  source "$LIB_SCRIPT"

  if hb_default_profile_paths | grep -Fxq '/var/lib/proxmenux/backup-jobs'; then
    pass "Default profile includes scheduled backup job definitions"
  else
    fail "Default profile does not include scheduled backup job definitions"
  fi

  if ! help mapfile >/dev/null 2>&1; then
    skip "Staging copy tests require bash >= 4 and GNU rsync."
    return
  fi

  local jobs_dir="$TMP_ROOT/staging-jobs"
  local custom_dir="$TMP_ROOT/custom-state"
  local stage_root="$TMP_ROOT/staging-output"
  local previous_jobs_dir="$HB_BACKUP_JOBS_DIR"
  local previous_state_dir="$HB_STATE_DIR"
  mkdir -p "$jobs_dir" "$custom_dir/images" "$custom_dir/tmp"
  echo "custom-state" > "$custom_dir/images/application.conf"
  echo "audit" > "$custom_dir/application.log"
  echo "temporary-but-selected" > "$custom_dir/tmp/state"
  cat > "$jobs_dir/staging-test.env" <<EOJ
JOB_ID=staging-test
BACKEND=local
ON_CALENDAR=daily
PROFILE_MODE=custom
ENABLED=1
LOCAL_DEST_DIR=/var/lib/vz/dump
LOCAL_ARCHIVE_EXT=tar.gz
EOJ
  echo "$custom_dir" > "$jobs_dir/staging-test.paths"

  HB_BACKUP_JOBS_DIR="$jobs_dir"
  HB_STATE_DIR="$TMP_ROOT/operator-state"
  mkdir -p "$HB_STATE_DIR"
  printf '/root\n' > "$(hb_extra_paths_file)"
  if hb_path_is_operator_added /root && hb_path_is_operator_added "$custom_dir"; then
    pass "Persisted and non-default paths are classified as operator-added"
  else
    fail "Operator-added path classification failed"
  fi
  if PMX_BACKUP_NO_SYSTEMCTL=1 hb_prepare_staging "$stage_root" "$custom_dir" >>"$REPORT_FILE" 2>&1; then
    pass "Custom payload stages successfully"
  else
    fail "Custom payload staging failed"
  fi

  if [[ -f "$stage_root/rootfs/${custom_dir#/}/images/application.conf" && \
        -f "$stage_root/rootfs/${custom_dir#/}/application.log" && \
        -f "$stage_root/rootfs/${custom_dir#/}/tmp/state" ]]; then
    pass "Custom path content is copied without generic exclusions"
  else
    fail "Custom path content was silently excluded from staging"
  fi
  if [[ -f "$stage_root/rootfs/${jobs_dir#/}/staging-test.env" ]]; then
    pass "Job definitions are included with a custom profile"
  else
    fail "Job definitions were not added to the custom profile"
  fi
  if [[ ! -s "$stage_root/metadata/failed_paths.txt" ]]; then
    pass "Successful staging has no failed paths"
  else
    fail "Successful staging unexpectedly reports failed paths"
  fi
  HB_BACKUP_JOBS_DIR="$previous_jobs_dir"
  HB_STATE_DIR="$previous_state_dir"
}

restored_job_reconcile_tests() {
  log "\n=== Restored job reconciliation (sandbox) ==="
  local jobs_dir="$TMP_ROOT/reconcile-jobs"
  local logs_dir="$TMP_ROOT/reconcile-logs"
  local systemd_dir="$TMP_ROOT/reconcile-systemd"
  local marker="$TMP_ROOT/unsafe-evaluated"
  mkdir -p "$jobs_dir" "$logs_dir" "$systemd_dir"

  cat > "$jobs_dir/enabled.env" <<'EOJ'
JOB_ID=enabled
BACKEND=local
ON_CALENDAR=Mon..Fri\ 03:00
PROFILE_MODE=custom
ENABLED=1
LOCAL_DEST_DIR=/var/lib/vz/dump
LOCAL_ARCHIVE_EXT=tar.gz
EOJ
  echo "/etc/hosts" > "$jobs_dir/enabled.paths"

  cat > "$jobs_dir/attached.env" <<'EOJ'
JOB_ID=attached
BACKEND=pbs
PVE_PARENT_JOB=backup-1
PVE_STORAGE=pbs-main
PROFILE_MODE=default
ENABLED=1
PBS_REPOSITORY=root@pam@pbs.example:datastore
PBS_PASSWORD=''
PBS_BACKUP_ID=hostcfg-test
EOJ
  echo "/etc/hosts" > "$jobs_dir/attached.paths"

  cat > "$jobs_dir/unsafe.env" <<EOJ
JOB_ID=unsafe
BACKEND=local
ON_CALENDAR=daily
PROFILE_MODE=custom
ENABLED=1
LOCAL_DEST_DIR=/var/lib/vz/dump
LOCAL_ARCHIVE_EXT=tar.gz
EVIL=\$(touch "$marker")
EOJ
  echo "/etc/hosts" > "$jobs_dir/unsafe.paths"

  if PMX_BACKUP_JOBS_DIR="$jobs_dir" PMX_BACKUP_LOG_DIR="$logs_dir" \
     PMX_BACKUP_SYSTEMD_DIR="$systemd_dir" PMX_BACKUP_NO_SYSTEMCTL=1 \
     bash "$SCHED_SCRIPT" --reconcile-restored >>"$REPORT_FILE" 2>&1; then
    fail "Reconciliation should report the invalid restored job"
  else
    pass "Reconciliation rejects an invalid restored job"
  fi

  if assert_file_contains "$systemd_dir/proxmenux-backup-enabled.timer" "OnCalendar=Mon..Fri 03:00"; then
    pass "Valid standalone job timer is reconstructed"
  else
    fail "Valid standalone job timer was not reconstructed"
  fi
  if [[ ! -e "$systemd_dir/proxmenux-backup-attached.timer" ]]; then
    pass "PVE-attached job is not converted into a duplicate timer"
  else
    fail "PVE-attached job unexpectedly created a timer"
  fi
  if [[ ! -e "$systemd_dir/proxmenux-backup-unsafe.timer" && ! -e "$marker" ]]; then
    pass "Rejected job cannot create a unit or execute shell content"
  else
    fail "Rejected job produced side effects"
  fi
}

scheduler_e2e_tests() {
  log "\n=== Scheduler E2E (sandbox) ==="
  if ! help mapfile >/dev/null 2>&1; then
    skip "Scheduler E2E skipped: current bash does not provide mapfile (requires bash >= 4)."
    return
  fi

  local jobs_dir="$TMP_ROOT/backup-jobs"
  local logs_dir="$TMP_ROOT/backup-jobs-logs"
  local lock_dir="$TMP_ROOT/locks"
  local archives_dir="$TMP_ROOT/archives"

  mkdir -p "$jobs_dir" "$logs_dir" "$lock_dir" "$archives_dir"

  cat > "$jobs_dir/t1.env" <<EOJ
JOB_ID=t1
BACKEND=local
PROFILE_MODE=custom
LOCAL_DEST_DIR=${archives_dir}
LOCAL_ARCHIVE_EXT=tar.gz
KEEP_LAST=2
KEEP_HOURLY=0
KEEP_DAILY=0
KEEP_WEEKLY=0
KEEP_MONTHLY=0
KEEP_YEARLY=0
EOJ

  cat > "$jobs_dir/t1.paths" <<EOP
/etc/hosts
/etc/resolv.conf
EOP

  local i
  for i in 1 2 3; do
    if PMX_BACKUP_JOBS_DIR="$jobs_dir" PMX_BACKUP_LOG_DIR="$logs_dir" PMX_BACKUP_LOCK_DIR="$lock_dir" \
      bash "$RUNNER" t1 >>"$REPORT_FILE" 2>&1; then
      :
    else
      fail "Runner execution #$i for t1"
      return
    fi
    sleep 1
  done

  local archive_count
  archive_count="$(find "$archives_dir" -maxdepth 1 -type f -name 't1-*.tar.gz' | wc -l | tr -d ' ')"
  if [[ "$archive_count" == "2" ]]; then
    pass "Retention KEEP_LAST=2 keeps exactly 2 archives"
  else
    fail "Retention expected 2 archives, got $archive_count"
  fi

  if assert_file_contains "$logs_dir/t1-last.status" "RESULT=ok"; then
    pass "t1-last.status reports RESULT=ok"
  else
    fail "t1-last.status does not report RESULT=ok"
  fi

  cat > "$jobs_dir/tbad.env" <<EOJ
JOB_ID=tbad
BACKEND=invalid
PROFILE_MODE=custom
KEEP_LAST=1
EOJ
  echo "/etc/hosts" > "$jobs_dir/tbad.paths"

  run_cmd_expect_fail "Invalid backend fails" \
    env PMX_BACKUP_JOBS_DIR="$jobs_dir" PMX_BACKUP_LOG_DIR="$logs_dir" PMX_BACKUP_LOCK_DIR="$lock_dir" \
    bash "$RUNNER" tbad

  if assert_file_contains "$logs_dir/tbad-last.status" "RESULT=failed"; then
    pass "tbad-last.status reports RESULT=failed"
  else
    fail "tbad-last.status does not report RESULT=failed"
  fi

  cat > "$jobs_dir/tempty.env" <<EOJ
JOB_ID=tempty
BACKEND=local
PROFILE_MODE=custom
LOCAL_DEST_DIR=${archives_dir}
LOCAL_ARCHIVE_EXT=tar.gz
KEEP_LAST=1
EOJ
  : > "$jobs_dir/tempty.paths"

  run_cmd_expect_fail "Empty paths fails" \
    env PMX_BACKUP_JOBS_DIR="$jobs_dir" PMX_BACKUP_LOG_DIR="$logs_dir" PMX_BACKUP_LOCK_DIR="$lock_dir" \
    bash "$RUNNER" tempty

  if assert_file_contains "$logs_dir/tempty-last.status" "RESULT=failed"; then
    pass "tempty-last.status reports RESULT=failed"
  else
    fail "tempty-last.status does not report RESULT=failed"
  fi
}

pending_restore_tests() {
  log "\n=== Pending restore E2E (sandbox) ==="
  local pending_base="$TMP_ROOT/restore-pending"
  local logs_dir="$TMP_ROOT/restore-logs"
  local target_root="$TMP_ROOT/target"
  local pre_backup_base="$TMP_ROOT/pre-restore"
  local recovery_base="$TMP_ROOT/recovery"

  mkdir -p "$pending_base/r1/rootfs/etc/pve" "$pending_base/r1/rootfs/etc/zfs" "$pending_base/r1/rootfs/etc" "$target_root/etc"

  echo "new-value" > "$pending_base/r1/rootfs/etc/test.conf"
  echo "cluster-data" > "$pending_base/r1/rootfs/etc/pve/cluster.cfg"
  echo "zfs-data" > "$pending_base/r1/rootfs/etc/zfs/zpool.cache"
  echo "old-value" > "$target_root/etc/test.conf"

  cat > "$pending_base/r1/apply-on-boot.list" <<EOL
etc/test.conf
etc/pve/cluster.cfg
etc/zfs/zpool.cache
EOL

  cat > "$pending_base/r1/plan.env" <<EOP
HB_RESTORE_INCLUDE_ZFS=0
EOP

  ln -sfn "$pending_base/r1" "$pending_base/current"

  if PMX_RESTORE_PENDING_BASE="$pending_base" PMX_RESTORE_LOG_DIR="$logs_dir" \
     PMX_RESTORE_DEST_PREFIX="$target_root" PMX_RESTORE_PRE_BACKUP_BASE="$pre_backup_base" \
     PMX_RESTORE_RECOVERY_BASE="$recovery_base" \
     bash "$APPLY_ONBOOT" >>"$REPORT_FILE" 2>&1; then
    pass "apply_pending_restore completes"
  else
    fail "apply_pending_restore completes"
    return
  fi

  if assert_file_contains "$target_root/etc/test.conf" "new-value"; then
    pass "Regular file restored into target prefix"
  else
    fail "Regular file was not restored"
  fi

  if [[ -e "$target_root/etc/pve/cluster.cfg" ]]; then
    fail "Cluster file should not be restored live"
  else
    pass "Cluster file skipped from live restore"
  fi

  if find "$recovery_base" -type f -name cluster.cfg 2>/dev/null | grep -q .; then
    pass "Cluster file extracted to recovery directory"
  else
    fail "Cluster file not found in recovery directory"
  fi

  if assert_file_contains "$pending_base/completed/r1/state" "completed"; then
    pass "Pending restore state marked completed"
  else
    fail "Pending restore state not marked completed"
  fi

  if [[ -e "$pending_base/current" ]]; then
    fail "current symlink should be removed"
  else
    pass "current symlink removed"
  fi
}

pending_jobs_restore_tests() {
  log "\n=== Pending restore of scheduled jobs (sandbox) ==="
  if ! help mapfile >/dev/null 2>&1; then
    skip "Pending scheduled-job restore test requires the Linux runtime."
    return
  fi
  local pending_base="$TMP_ROOT/jobs-restore-pending"
  local logs_dir="$TMP_ROOT/jobs-restore-logs"
  local target_root="$TMP_ROOT/jobs-restore-target"
  local pre_backup_base="$TMP_ROOT/jobs-pre-restore"
  local recovery_base="$TMP_ROOT/jobs-recovery"
  local restored_jobs="$target_root/var/lib/proxmenux/backup-jobs"
  local source_jobs="$pending_base/r2/rootfs/var/lib/proxmenux/backup-jobs"

  mkdir -p "$source_jobs" "$target_root"
  cat > "$source_jobs/restored.env" <<'EOJ'
JOB_ID=restored
BACKEND=local
ON_CALENDAR=daily
PROFILE_MODE=custom
ENABLED=1
LOCAL_DEST_DIR=/var/lib/vz/dump
LOCAL_ARCHIVE_EXT=tar.gz
EOJ
  echo "/etc/hosts" > "$source_jobs/restored.paths"
  echo "var/lib/proxmenux/backup-jobs" > "$pending_base/r2/apply-on-boot.list"
  echo "HB_RESTORE_INCLUDE_ZFS=0" > "$pending_base/r2/plan.env"
  ln -sfn "$pending_base/r2" "$pending_base/current"

  if PMX_RESTORE_PENDING_BASE="$pending_base" PMX_RESTORE_LOG_DIR="$logs_dir" \
     PMX_RESTORE_DEST_PREFIX="$target_root" PMX_RESTORE_PRE_BACKUP_BASE="$pre_backup_base" \
     PMX_RESTORE_RECOVERY_BASE="$recovery_base" \
     bash "$APPLY_ONBOOT" >>"$REPORT_FILE" 2>&1; then
    pass "Pending restore applies scheduled job definitions"
  else
    fail "Pending restore failed while applying scheduled job definitions"
    return
  fi

  if [[ -f "$restored_jobs/restored.env" && \
        -f "$target_root/etc/systemd/system/proxmenux-backup-restored.timer" ]]; then
    pass "Pending restore reconstructs the scheduled timer"
  else
    fail "Pending restore did not reconstruct the scheduled timer"
  fi
}

main() {
  log "ProxMenux backup/restore test matrix"
  log "Report: $REPORT_FILE"
  log "Temp root: $TMP_ROOT"

  syntax_tests
  certificate_restore_tests
  staging_state_tests
  restored_job_reconcile_tests
  scheduler_e2e_tests
  pending_restore_tests
  pending_jobs_restore_tests

  log "\n=== Summary ==="
  log "PASS=$PASS"
  log "FAIL=$FAIL"
  log "SKIP=$SKIP"

  if [[ "$FAIL" -eq 0 ]]; then
    log "RESULT=OK"
    exit 0
  else
    log "RESULT=FAILED"
    exit 1
  fi
}

main "$@"
