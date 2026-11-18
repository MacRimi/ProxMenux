# Shared NVIDIA runtime setup for native OCI installers.
# Sourced by the installers: uses their msg_*, translate, oci_log and die.
source "${SCRIPT_DIR}/lxc_nvidia_setup.sh"
configure_nvidia_runtime() {
  local inventory path source target runtime_mode hook_hash hook_path capabilities
  local device_count=0 mount_count=0
  declare -A configured_paths=()
  msg_info "$(translate "Preparing the NVIDIA GPU...")"
  command -v nvidia-smi >/dev/null 2>&1 \
    || die "$(translate "The image requests NVIDIA, but the host has no working NVIDIA driver")"
  nvidia-smi -L >/dev/null 2>&1 \
    || die "$(translate "The host NVIDIA driver is not responding correctly")"
  command -v nvidia-container-cli >/dev/null 2>&1 \
    || die "$(translate "NVIDIA Container Toolkit is missing on the host (nvidia-container-cli)")"
  runtime_mode=$(jq -r '.runtime_mode // "static"' <<<"$DEVICE")
  [[ $runtime_mode == static || $runtime_mode == dynamic ]] \
    || die "$(translate "Unsupported NVIDIA mode:") $runtime_mode"
  if [[ $runtime_mode == dynamic ]]; then
    [[ $UNPRIVILEGED_FLAG == 1 ]] || die "$(translate "The dynamic NVIDIA profile requires an unprivileged LXC")"
    [[ -f ${SCRIPT_DIR}/nvidia_lxc_mount_lab.sh ]] || die "$(translate "The dynamic NVIDIA hook is missing")"
    capabilities=$(jq -r '[.environment[]? | select(.name == "NVIDIA_DRIVER_CAPABILITIES") | .value] | last // "compute,utility,video"' "$DEPLOYMENT_FILE")
    [[ $capabilities == all || $capabilities =~ ^(compute|utility|video|graphics|display|compat32)(,(compute|utility|video|graphics|display|compat32))*$ ]] \
      || die "$(translate "Unsupported dynamic NVIDIA capabilities:") $capabilities"
    hook_hash=$(sha256sum "${SCRIPT_DIR}/nvidia_lxc_mount_lab.sh" | awk '{print $1}')
    hook_path="/usr/local/lib/proxmenux/oci/nvidia-mount-${hook_hash}.sh"
    hook_path=$(lxc_install_nvidia_hook "${SCRIPT_DIR}/nvidia_lxc_mount_lab.sh" "$hook_hash") \
      || die "$(translate "The persistent NVIDIA hook does not match the installer:") /usr/local/lib/proxmenux/oci/nvidia-mount-${hook_hash}.sh"
    printf 'lxc.environment: NVIDIA_VISIBLE_DEVICES=all\nlxc.environment: NVIDIA_DRIVER_CAPABILITIES=%s\nlxc.hook.mount: %s\n' \
      "$capabilities" "$hook_path" >>"$CONF"
  fi

  inventory=$(mktemp /tmp/proxmenux-nvidia-inventory.XXXXXX)
  if ! nvidia-container-cli list --device all --libraries --binaries --firmwares --ipcs \
    2>>"${OCI_LOG:-/dev/null}" | sort -u >"$inventory"; then
    rm -f "$inventory"
    die "$(translate "NVIDIA Container Toolkit could not generate the runtime inventory")"
  fi
  while IFS= read -r path; do
    [[ $path == /* && $path != *[[:space:]]* && $path != *","* ]] || continue
    [[ -z ${configured_paths[$path]+x} ]] || continue
    if [[ -c $path ]]; then
      add_character_device "$path" preserve-host host-device-gid 0
      if [[ -n ${NVIDIA_GID_ENV:-} ]]; then
        append_deployment_environment_csv "$NVIDIA_GID_ENV" "$(stat -c '%g' "$path")"
      fi
      device_count=$((device_count + 1))
    elif [[ -f $path ]]; then
      if [[ $runtime_mode == dynamic ]]; then
        continue
      fi
      source=$(readlink -f "$path")
      [[ -f $source ]] || continue
      target=$path
      prepare_file_mount_target "$target"
      target=$PREPARED_FILE_TARGET
      prepare_nvidia_driver_links "$source" "$target"
      printf 'lxc.mount.entry: %s %s none ro,bind,create=file 0 0\n' \
        "$source" "${target#/}" >>"$CONF"
      mount_count=$((mount_count + 1))
    else
      continue
    fi
    configured_paths[$path]=1
  done <"$inventory"
  rm -f "$inventory"
  (( device_count > 0 )) || die "$(translate "The official inventory contains no NVIDIA devices")"
  [[ $runtime_mode == dynamic ]] || (( mount_count > 0 )) \
    || die "$(translate "The official inventory contains no NVIDIA driver components")"
  NVIDIA_RUNTIME_CONFIGURED=1
  if [[ $runtime_mode == dynamic ]]; then
    oci_log "Dynamic NVIDIA runtime prepared: $device_count native devices; libraries resolved by the Toolkit at every start"
    msg_ok "$(translate "NVIDIA GPU prepared:") $device_count $(translate "devices (dynamic runtime)")"
    return
  fi
  oci_log "NVIDIA runtime prepared from NVIDIA Container Toolkit: $device_count devices and $mount_count read-only components"
  msg_ok "$(translate "NVIDIA GPU prepared:") $device_count $(translate "devices") · $mount_count $(translate "driver components")"
}
