# Sourced by the dedicated installers after image resolution, before CT creation.
oci_native_begin() {
  OCI_NATIVE_PRIMARY=$1
  shift
  local root=/usr/local/share/proxmenux/oci/instances
  [[ ! -L $root && ! -L $root/.lock ]] || die "$(translate "The instance registry is not safe")"
  oci_quiet install -d -m 0700 "$root"
  exec 8>>"$root/.lock"
  chmod 600 "$root/.lock"
  flock -n 8 || die "$(translate "Another OCI operation is using the instance registry")"
  export PROXMENUX_INSTANCE_LOCK_FD=8
  oci_quiet python3 "$SCRIPT_DIR/oci_native_stack.py" begin "$OCI_NATIVE_PRIMARY" \
    --template "$TEMPLATE_FILE" --deployment "$DEPLOYMENT_FILE" \
    --adapter "$0" "$@"
  OCI_NATIVE_ACTIVE=1
}

# A failure returns to the caller instead of exiting inside a redirected call,
# so the caller's error report reaches the terminal and not the log.
pct() {
  if [[ ${1:-} == unmount && ${OCI_NATIVE_ACTIVE:-0} == 1 ]]; then
    if ! python3 "$SCRIPT_DIR/oci_native_stack.py" capture-rootfs "$2"; then
      command pct unmount "$2" 8>&- 9>&- || true
      return 1
    fi
  fi
  if [[ ${1:-} == create && ${OCI_NATIVE_ACTIVE:-0} == 1 ]]; then
    shift
    python3 "$SCRIPT_DIR/oci_native_stack.py" create "$@" || return
  else
    command pct "$@" 8>&- 9>&- || return
  fi
}

oci_native_finalize() {
  oci_quiet python3 "$SCRIPT_DIR/oci_native_stack.py" finalize "$OCI_NATIVE_PRIMARY"
}

oci_native_failed() {
  [[ ${OCI_NATIVE_ACTIVE:-0} == 1 ]] || return 0
  oci_quiet python3 "$SCRIPT_DIR/oci_native_stack.py" failed "$OCI_NATIVE_PRIMARY" || true
}
