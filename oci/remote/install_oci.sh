#!/usr/bin/env bash
set -Eeuo pipefail

TEMPLATE_FILE=${1:?template JSON required}
DEPLOYMENT_FILE=${2:?deployment JSON required}
DRY_RUN=${3:-0}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/oci_ui.sh"
# A transaction captures this output in a private file: no spinner there.
[[ -z ${PROXMENUX_OCI_TRANSACTION:-} ]] || OCI_SPINNER=0

die() {
  stop_spinner
  msg_error "$*"
  if [[ -n ${OCI_LOG:-} && -s ${OCI_LOG:-} ]]; then
    oci_log_tail 12 >&2
    printf '    %s %s\n' "$(translate "Full log:")" "$OCI_LOG" >&2
  fi
  exit 1
}

container_is_running() {
  local status attempt
  for (( attempt=1; attempt<=3; attempt++ )); do
    if status=$(pct status "$VMID" 2>/dev/null); then
      case "$status" in
        'status: running') return 0 ;;
        'status: stopped') return 1 ;;
      esac
    fi
    # A failed pct probe must not be mistaken for a stopped container.
    oci_log "pct status could not confirm CT $VMID (attempt $attempt); checking lxc-info"
    if status=$(lxc-info -n "$VMID" -sH 2>/dev/null); then
      case "$status" in
        RUNNING) return 0 ;;
        STOPPED) return 1 ;;
      esac
    fi
    (( attempt < 3 )) && sleep 1
  done
  return 1
}

mount_ct_rootfs() {
  oci_quiet pct mount "$VMID" || die "$(translate "Could not mount the container filesystem:") CT $VMID"
}

merge_json_defaults() {
  jq -n --slurpfile existing "$1" --slurpfile defaults "$2" '
    def fill($d):
      if type != "object" then error("Existing JSON section is not an object")
      else reduce ($d | keys_unsorted[]) as $key (.;
        if has($key) then
          if ($d[$key] | type) == "object" then .[$key] |= fill($d[$key]) else . end
        else .[$key] = $d[$key] end)
      end;
    if ($existing | length) != 1 or ($defaults | length) != 1
       or ($defaults[0] | type) != "object"
    then error("Expected one JSON object per file")
    else $existing[0] | fill($defaults[0]) end'
}

gpu_vendor_name() {
  case "$1" in
    0x1002) printf 'AMD' ;;
    0x8086) printf 'Intel' ;;
    0x10de) printf 'NVIDIA' ;;
    *) printf '%s' "$1" ;;
  esac
}

validate_gpu_vendors() {
  local device path node vendor
  while IFS= read -r device; do
    path=$(jq -er '.host_path' <<<"$device")
    [[ $path =~ ^/dev/dri/renderD[0-9]+$ && -c $path ]] \
      || die "$(translate "The selected render device does not exist:") $path"
    node=${path##*/}
    vendor=$(cat "/sys/class/drm/${node}/device/vendor" 2>/dev/null) \
      || die "$(translate "Cannot identify the vendor of the device:") $path"
    jq -e --arg vendor "$vendor" '.drm_vendor_ids | index($vendor) != null' <<<"$device" >/dev/null \
      || die "$(translate "The GPU vendor does not match the selected GPU profile:") $path ($vendor)"
    msg_ok "$(translate "GPU verified:") $path ($(gpu_vendor_name "$vendor"), GID $(stat -c '%g' "$path"))"
  done < <(jq -c '.devices[]? | select(.drm_vendor_ids != null)' "$DEPLOYMENT_FILE")
}

show_gpu_inventory() {
  jq -e '.devices[]? | select(.kind == "nvidia-runtime" or
    ((.host_path // "") | startswith("/dev/dri")) or .host_path == "/dev/kfd")' \
    "$DEPLOYMENT_FILE" >/dev/null || return 0
  local node vendor kind
  oci_log "Host DRM inventory (additional GPUs are not passed through automatically):"
  for node in /dev/dri/renderD*; do
    [[ -c $node ]] || continue
    vendor=$(cat "/sys/class/drm/${node##*/}/device/vendor" 2>/dev/null || true)
    oci_log "  $node vendor=${vendor:-unknown} uid=$(stat -c '%u' "$node") gid=$(stat -c '%g' "$node") mode=$(stat -c '%a' "$node")"
  done
  while IFS=$'\t' read -r node kind; do
    if [[ $kind == character-device-tree ]]; then
      [[ -d $node ]] || die "$(translate "The selected GPU directory does not exist:") $node"
    else
      [[ -c $node ]] || die "$(translate "The selected GPU device does not exist:") $node"
    fi
  done < <(jq -r '.devices[]? | select(
    ((.host_path // "") | startswith("/dev/dri")) or .host_path == "/dev/kfd") |
    [.host_path, (.kind // "character-device")] | @tsv' "$DEPLOYMENT_FILE")
}

apply_native_device_permissions() {
  [[ $(jq -r '.device_permissions.strategy // empty' "$DEPLOYMENT_FILE") == linuxserver-native-init ]] || return 0
  (( ${#RESOLVED_CHARACTER_DEVICES[@]} > 0 )) || return 0
  # Expand after NVIDIA/DVB discovery: directories and fixed renderD128 miss devices.
  local value temporary
  value=$(IFS=' '; printf '%s' "${RESOLVED_CHARACTER_DEVICES[*]}")
  temporary=$(mktemp)
  jq --arg value "$value" '.environment =
    ([.environment[] | select(.name != "ATTACHED_DEVICES_PERMS")] +
    [{name:"ATTACHED_DEVICES_PERMS", value:$value, sensitive:false}])' \
    "$DEPLOYMENT_FILE" >"$temporary"
  cat "$temporary" >"$DEPLOYMENT_FILE"
  rm -f "$temporary"
}

check_native_device_permissions() {
  [[ $(jq -r '.device_permissions.strategy // empty' "$DEPLOYMENT_FILE") == linuxserver-native-init ]] || return 0
  (( ${#RESOLVED_CHARACTER_DEVICES[@]} > 0 )) || return 0
  local attempt
  msg_info "$(translate "Checking the device permissions for the application user...")"
  oci_log "Checking device access as abc (this is not a codec test)."
  for (( attempt=0; attempt<60; attempt++ )); do
    container_is_running \
      || die "$(translate "The container stopped before the GPU permissions were verified:") CT $VMID"
    if pct exec "$VMID" -- s6-setuidgid abc sh -c \
      'for path do test -r "$path" && test -w "$path" || exit 1; done' \
      check "${RESOLVED_CHARACTER_DEVICES[@]}" >/dev/null 2>&1; then
      msg_ok "$(translate "Device permissions verified for the application user")"
      return 0
    fi
    sleep 2
  done
  die "$(translate "The image did not grant the application user access to the devices; check its native init. Host permissions were not relaxed.")"
}

configure_cpu_allocation() {
  local mode
  mode=$(jq -er '.proxmox.installer_profile.cpu_allocation // "cpuset"' "$TEMPLATE_FILE")
  case "$mode" in
    cpuset|quota) ;;
    *) die "$(translate "Unsupported CPU allocation mode:") $mode" ;;
  esac
  if [[ $mode == quota || -n ${HOST_MONITOR:-} ]]; then
    CPU_CREATE_ARGS=(--cpulimit "$CORES")
  else
    CPU_CREATE_ARGS=(--cores "$CORES")
  fi
}

validate_rlimits() {
  local name soft hard
  jq -e '(.resources.rlimits // []) | type == "array" and
    (all(.[]; type == "object" and (.name|type)=="string" and
      (.soft|type)=="string" and (.hard|type)=="string")) and
    ((map(.name)|unique|length) == length)' "$DEPLOYMENT_FILE" >/dev/null \
    || die "$(translate "Invalid process limits format")"
  while IFS=$'\t' read -r name soft hard; do
    [[ $name =~ ^(as|core|cpu|data|fsize|locks|memlock|msgqueue|nice|nofile|nproc|rss|rtprio|rttime|sigpending|stack)$ ]] \
      || die "$(translate "Unsupported prlimit resource")"
    [[ $soft =~ ^(unlimited|0|[1-9][0-9]{0,17})$ && $hard =~ ^(unlimited|0|[1-9][0-9]{0,17})$ ]] \
      || die "$(translate "Invalid prlimit value")"
    if [[ $hard != unlimited ]]; then
      [[ $soft != unlimited ]] && (( soft <= hard )) || die "$(translate "The prlimit soft value exceeds the hard value")"
    fi
  done < <(jq -r '.resources.rlimits[]? | [.name,.soft,.hard] | @tsv' "$DEPLOYMENT_FILE")
}

apply_rlimits() {
  local name soft hard
  while IFS=$'\t' read -r name soft hard; do
    set_lxc_directive "lxc.prlimit.${name}" "${soft}:${hard}"
  done < <(jq -r '.resources.rlimits[]? | [.name,.soft,.hard] | @tsv' "$DEPLOYMENT_FILE")
}

validate_host_monitor() {
  HOST_MONITOR=$(jq -r '.host_monitor // empty' "$DEPLOYMENT_FILE")
  [[ -n $HOST_MONITOR ]] || return 0
  local expected port
  case "$HOST_MONITOR" in
    glances) expected=nicolargo/glances:latest; port=61208 ;;
    netdata) expected=netdata/netdata:latest; port=19999 ;;
    *) die "$(translate "Unknown host monitor")" ;;
  esac
  [[ $APP_ID == "image-${HOST_MONITOR}" && $IMAGE_REF == "$expected" ]] \
    || die "$(translate "Image not allowed for the host monitor profile")"
  [[ $(jq -r '.proxmox.installer_profile.host_monitor // empty' "$TEMPLATE_FILE") == "$HOST_MONITOR" ]] \
    || die "$(translate "Inconsistent host monitor profile")"
  jq -e '.security.unprivileged == false and .security.privileged_acknowledged == true' "$DEPLOYMENT_FILE" >/dev/null \
    || die "$(translate "The host monitor needs consent for privileged access to the host")"
  [[ $IPV4 == host && -z $MAC_ADDRESS && -z $GATEWAY ]] \
    || die "$(translate "The host monitor uses the host network, without DHCP or its own gateway")"
  HOST_MONITOR_IP=$(ip -4 -o addr show dev "$BRIDGE" scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')
  [[ -n $HOST_MONITOR_IP ]] || die "$(translate "The host has no IPv4 address on the selected bridge")"
  require_command ss
  [[ -z $(ss -H -ltn "sport = :${port}") ]] || die "$(translate "The host port is already in use:") ${port}"
}

apply_host_monitor() {
  [[ -n ${HOST_MONITOR:-} ]] || return 0
  # PVE permits lxc.include but not namespace keys directly in the CT config.
  # This static, cluster-persistent companion must accompany cross-host restores.
  local include=/etc/pve/lxc/proxmenux-host-monitor native
  native=$'lxc.namespace.share.pid = 1\nlxc.namespace.share.net = 1'
  if [[ -e $include ]]; then
    [[ $(cat "$include") == "$native" ]] || die "$(translate "A different host monitor include already exists; it is not overwritten:") $include"
  else
    printf '%s\n' "$native" >"$include"
  fi
  [[ -z ${SYSCTL_INCLUDE:-} ]] || die "$(translate "The host monitor profile does not support another sysctl include")"
  set_lxc_directive lxc.include "$include"
  set_lxc_directive lxc.net.0.type none
  # LXCFS reports cgroup-limited values, which would misrepresent the monitored host.
  # Do not remove the Proxmox pre-start, autodev or post-stop hooks.
  set_lxc_directive lxc.hook.mount ""
  msg_ok "$(translate "Host monitor configured: shared PID and network namespaces, LXCFS disabled in this container")"
  msg_info2 "$(translate "To restore it on another host, keep this file (not included in the vzdump backup):") $include"
}

verify_host_monitor() {
  [[ -n ${HOST_MONITOR:-} ]] || return 0
  local pid namespace actual
  pid=$(lxc-info -n "$VMID" -pH)
  [[ $pid =~ ^[0-9]+$ && $pid -gt 1 ]] || die "$(translate "Invalid host monitor PID")"
  for namespace in pid net; do
    actual=$(readlink "/proc/$pid/ns/$namespace")
    [[ $actual == "$(readlink "/proc/1/ns/$namespace")" ]] \
      || die "$(translate "The host monitor does not share this host namespace:") $namespace"
  done
  [[ $(pct exec "$VMID" -- cat /proc/meminfo | sed -n '/^MemTotal:/p') == "$(sed -n '/^MemTotal:/p' /proc/meminfo)" ]] \
    || die "$(translate "The host monitor does not see the real host memory")"
  msg_ok "$(translate "Host monitor verified: PID and network namespaces and memory match the host")"
}

RUNTIME_CONSOLE_LOG=""
SYSCTL_INCLUDE=""
SECCOMP_PROFILE_FILE=""
CT_CREATED=0
INSTALL_COMPLETE=0
PRESERVE_FAILED_CT=0

cleanup_runtime_console_log() {
  # The console log is the container's own log from here on, and its line in
  # the configuration stays with it: there is nothing to undo. A failed
  # installation keeps the file too, since it holds why the application did
  # not come up.
  RUNTIME_CONSOLE_LOG=""
}

# A derived check accepts any HTTP answer below 500: the application is up,
# even when its first page is a redirect or asks for a login.
healthcheck_probe() {
  if [[ ${HC_ANY_STATUS:-false} == true ]]; then
    local code
    code=$(curl "${CURL_ARGS[@]}" "$HC_URL" 2>/dev/null) || return 1
    [[ $code =~ ^[1-4][0-9][0-9]$ ]]
  else
    curl "${CURL_ARGS[@]}" "$HC_URL" 2>/dev/null
  fi
}

cleanup_failed_install() {
  local status=$?
  stop_spinner
  if [[ -n ${PROXMENUX_OCI_TRANSACTION:-} ]]; then
    # The transaction owns recovery. Destroying this CT could destroy reused data.
    cleanup_runtime_console_log || true
    return "$status"
  fi
  if (( status != 0 )) && [[ -n ${INSTANCE_ID:-} ]]; then
    oci_quiet python3 "${SCRIPT_DIR}/oci_instances.py" failed "$VMID" || true
  fi
  # A step may fail while the rootfs is mounted; the mount lock would block
  # both keeping the CT usable and destroying it.
  if (( status != 0 && CT_CREATED == 1 )); then
    pct unmount "$VMID" >/dev/null 2>&1 || true
  fi
  if (( status != 0 && CT_CREATED == 1 && INSTALL_COMPLETE == 0 && PRESERVE_FAILED_CT == 1 )); then
    oci_log "Container kept for inspection; console log: $RUNTIME_CONSOLE_LOG"
    msg_warn "$(translate "Container kept with its data; the installation was not validated:") CT $VMID · $(translate "Full log:") ${OCI_LOG:-$RUNTIME_CONSOLE_LOG}"
    [[ -z $RUNTIME_CONSOLE_LOG ]] || msg_info2 "$(translate "Console log:") $RUNTIME_CONSOLE_LOG"
    return "$status"
  fi
  cleanup_runtime_console_log || true
  if (( status != 0 && CT_CREATED == 1 && INSTALL_COMPLETE == 0 )); then
    msg_info "$(translate "Rolling back the incomplete container") CT $VMID..."
    oci_quiet pct stop "$VMID" || true
    if oci_quiet pct destroy "$VMID" --purge 1 || oci_quiet pct destroy "$VMID"; then
      msg_ok "$(translate "Incomplete container removed:") CT $VMID"
    else
      msg_warn "$(translate "The container could not be removed automatically:") CT $VMID"
    fi
  fi
  # The include files belong to the CT: only remove them once it is gone.
  if (( status != 0 )) && ! { [[ -n ${VMID:-} ]] && pct config "$VMID" >/dev/null 2>&1; }; then
    [[ -z $SYSCTL_INCLUDE ]] || rm -f "$SYSCTL_INCLUDE"
    [[ -z $SECCOMP_PROFILE_FILE ]] || rm -f "$SECCOMP_PROFILE_FILE"
  fi
  return "$status"
}

ensure_rootfs_directory() {
  local rootfs=$1 directory=$2 current parent i
  local -a missing=()
  [[ $directory == "$rootfs" || $directory == "$rootfs"/* ]] \
    || die "$(translate "The prepared directory escapes the rootfs:") $directory"
  current=$directory
  while [[ ! -e $current ]]; do
    missing+=("$current")
    current=$(dirname "$current")
  done
  [[ -d $current ]] || die "$(translate "The parent of the target is not a directory:") $current"
  for ((i = ${#missing[@]} - 1; i >= 0; i--)); do
    parent=$(dirname "${missing[$i]}")
    mkdir "${missing[$i]}"
    chown --reference="$parent" "${missing[$i]}"
    chmod 0755 "${missing[$i]}"
  done
}

prepare_file_mount_target() {
  local requested_target=$1
  local rootfs="/var/lib/lxc/${VMID}/rootfs"
  local requested_parent resolved_parent target_path
  local failed=0

  mount_ct_rootfs
  requested_parent=$(dirname "$requested_target")
  resolved_parent=$(readlink -m "${rootfs}${requested_parent}")
  if [[ $resolved_parent != "$rootfs" && $resolved_parent != "$rootfs"/* ]]; then
    oci_quiet pct unmount "$VMID" || true
    die "$(translate "The bind mount target escapes the rootfs:") $requested_target"
  fi
  target_path="${resolved_parent}/$(basename "$requested_target")"
  PREPARED_FILE_TARGET="/${target_path#"${rootfs}/"}"
  ensure_rootfs_directory "$rootfs" "$(dirname "$target_path")"
  if [[ -L $target_path ]]; then
    rm -f "$target_path" || failed=1
  elif [[ -e $target_path && ! -f $target_path ]]; then
    oci_log "The file bind mount target cannot be replaced: $requested_target"
    failed=1
  fi
  if (( failed == 0 )) && [[ ! -e $target_path ]]; then
    : >"$target_path" || failed=1
    chown --reference="$(dirname "$target_path")" "$target_path" || failed=1
    chmod 0644 "$target_path" || failed=1
  fi
  oci_quiet pct unmount "$VMID" || failed=1
  (( failed == 0 )) \
    || die "$(translate "Could not prepare the file bind mount target:") $requested_target"
}

run_pre_start_repair() {
  local repair_json=$1
  local repair_id check_type python_path module check_package minimum_version
  local repair_type package index_url target_version break_system_packages no_dependencies
  local rootfs="/var/lib/lxc/${VMID}/rootfs"
  local check_passed=0 failed=0 repaired=0
  local -a pip_args

  repair_id=$(jq -er '.id' <<<"$repair_json")
  if ! jq -e --arg architecture "$ARCH" '.architectures | index($architecture) != null' \
    <<<"$repair_json" >/dev/null; then
    oci_log "Skipping repair $repair_id for architecture $ARCH"
    return 0
  fi
  check_type=$(jq -er '.check.type' <<<"$repair_json")
  python_path=$(jq -er '.check.python_path' <<<"$repair_json")
  repair_type=$(jq -er '.repair.type' <<<"$repair_json")
  package=$(jq -er '.repair.package' <<<"$repair_json")
  index_url=$(jq -er '.repair.index' <<<"$repair_json")
  break_system_packages=$(jq -r '.repair.break_system_packages // false' <<<"$repair_json")
  no_dependencies=$(jq -r '.repair.no_dependencies // false' <<<"$repair_json")
  [[ $python_path == /* && $python_path != *[[:space:]]* ]] \
    || die "$(translate "Invalid Python path in the repair:") $repair_id"
  [[ $package =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "$(translate "Invalid Python package:") $package"
  [[ $index_url == https://* && $index_url != *[[:space:]]* ]] \
    || die "$(translate "Invalid Python index:") $index_url"
  [[ $break_system_packages == true && $no_dependencies == true ]] \
    || die "$(translate "The repair must preserve the image dependencies:") $repair_id"

  case "$check_type" in
    python-import)
      module=$(jq -er '.check.module' <<<"$repair_json")
      [[ $module =~ ^[A-Za-z_][A-Za-z0-9_.]*$ ]] || die "$(translate "Invalid Python module:") $module"
      ;;
    python-package-minimum-version)
      check_package=$(jq -er '.check.package' <<<"$repair_json")
      minimum_version=$(jq -er '.check.minimum_version' <<<"$repair_json")
      [[ $check_package =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
        || die "$(translate "Invalid check package:") $check_package"
      [[ $minimum_version =~ ^[0-9]+([.][0-9]+)*$ ]] \
        || die "$(translate "Invalid minimum version:") $minimum_version"
      ;;
    *) die "$(translate "Unsupported pre-start check:") $check_type" ;;
  esac

  case "$repair_type" in
    pip-reinstall-installed-version) ;;
    pip-install-exact-version)
      target_version=$(jq -er '.repair.version' <<<"$repair_json")
      [[ $target_version =~ ^[A-Za-z0-9][A-Za-z0-9.+_-]*$ ]] \
        || die "$(translate "Invalid repair version:") $target_version"
      ;;
    *) die "$(translate "Unsupported pre-start repair:") $repair_type" ;;
  esac

  mount_ct_rootfs
  msg_info "$(translate "Checking the image compatibility:") $repair_id..."
  case "$check_type" in
    python-import)
      chroot "$rootfs" "$python_path" -c "import ${module}" >/dev/null 2>&1 \
        && check_passed=1
      ;;
    python-package-minimum-version)
      chroot "$rootfs" "$python_path" -c \
        'from importlib.metadata import version; from packaging.version import Version; import sys; sys.exit(0 if Version(version(sys.argv[1])) >= Version(sys.argv[2]) else 1)' \
        "$check_package" "$minimum_version" >/dev/null 2>&1 && check_passed=1
      ;;
  esac

  if (( check_passed == 1 )); then
    oci_log "Compatibility check passed for $repair_id; no changes applied"
  else
    if [[ $repair_type == pip-reinstall-installed-version ]]; then
      target_version=$(chroot "$rootfs" "$python_path" -c \
        'import importlib.metadata,sys; print(importlib.metadata.version(sys.argv[1]))' \
        "$package" 2>/dev/null) || failed=1
      if (( failed == 0 )) && [[ ! $target_version =~ ^[A-Za-z0-9][A-Za-z0-9.+_-]*$ ]]; then
        oci_log "Invalid package version for $package: $target_version"
        failed=1
      fi
    fi
    if (( failed == 0 )); then
      oci_log "Compatibility check failed; installing ${package}==${target_version} without changing dependencies"
      pip_args=(--disable-pip-version-check --no-cache-dir --force-reinstall)
      [[ $break_system_packages == true ]] && pip_args+=(--break-system-packages)
      [[ $no_dependencies == true ]] && pip_args+=(--no-deps)
      oci_quiet chroot "$rootfs" "$python_path" -m pip install "${pip_args[@]}" \
        --index-url "$index_url" "${package}==${target_version}" || failed=1
    fi
    if (( failed == 0 )); then
      check_passed=0
      case "$check_type" in
        python-import)
          chroot "$rootfs" "$python_path" -c "import ${module}" >/dev/null 2>&1 \
            && check_passed=1
          ;;
        python-package-minimum-version)
          chroot "$rootfs" "$python_path" -c \
            'from importlib.metadata import version; from packaging.version import Version; import sys; sys.exit(0 if Version(version(sys.argv[1])) >= Version(sys.argv[2]) else 1)' \
            "$check_package" "$minimum_version" >/dev/null 2>&1 && check_passed=1
          ;;
      esac
      (( check_passed == 1 )) || failed=1
      repaired=1
    fi
  fi
  oci_quiet pct unmount "$VMID" || failed=1
  (( failed == 0 )) || die "$(translate "Could not apply the pre-start repair:") $repair_id"
  if (( repaired == 1 )); then
    msg_ok "$(translate "Image compatibility restored:") ${package}==${target_version}"
  else
    msg_ok "$(translate "Image compatibility verified:") $repair_id"
  fi
}

apply_post_start_configuration() {
  local configuration=$1 type configuration_id timeout required path found=0 elapsed=0
  local rootfs="/var/lib/lxc/${VMID}/rootfs" mounted=0 failed=0
  configuration_id=$(jq -er '.id' <<<"$configuration")
  type=$(jq -er '.type' <<<"$configuration")
  timeout=$(jq -r '.timeout_seconds // 120' <<<"$configuration")
  required=$(jq -r '.required // true' <<<"$configuration")
  [[ $timeout =~ ^[0-9]+$ && $timeout -gt 0 ]] \
    || die "$(translate "Invalid post-start timeout in the configuration:") $configuration_id"

  case "$type" in
    jellyfin-encoding-xml)
      msg_info "$(translate "Waiting for the initial Jellyfin configuration...")"
      while (( elapsed < timeout )); do
        while IFS= read -r path; do
          [[ $path == /* && $path != *[[:space:]]* ]] \
            || die "$(translate "Invalid Jellyfin path:") $path"
          if pct exec "$VMID" -- test -f "$path" >/dev/null 2>&1; then
            found=1
            break
          fi
        done < <(jq -r '.candidate_paths[]?' <<<"$configuration")
        (( found == 1 )) && break
        sleep 2
        elapsed=$((elapsed + 2))
        msg_progress "$(translate "Waiting for the initial Jellyfin configuration...") ${elapsed}/${timeout} s"
      done
      if (( found == 0 )); then
        if [[ $required == true ]]; then
          die "$(translate "Jellyfin did not create encoding.xml before the timeout")"
        fi
        msg_warn "$(translate "Skipped because Jellyfin did not create encoding.xml:") $configuration_id"
        return 0
      fi

      msg_info "$(translate "Applying the Jellyfin configuration:") $configuration_id..."
      if ! pct shutdown "$VMID" --timeout "$SHUTDOWN_TIMEOUT" >/dev/null 2>&1; then
        if [[ $(pct status "$VMID" 2>/dev/null || true) == "status: running" ]]; then
          oci_quiet pct stop "$VMID" \
            || die "$(translate "The container did not stop to update its persistent configuration:") CT $VMID"
        fi
      fi
      [[ $(pct status "$VMID" 2>/dev/null || true) == "status: stopped" ]] \
        || die "$(translate "The container did not stop to update its persistent configuration:") CT $VMID"
      mount_ct_rootfs
      mounted=1
      oci_quiet python3 "$JELLYFIN_CONFIGURATOR" "$rootfs" "$configuration" || failed=1
      oci_quiet pct unmount "$VMID" || failed=1
      mounted=0
      if (( failed != 0 )); then
        (( mounted == 0 )) || pct unmount "$VMID" >/dev/null 2>&1 || true
        die "$(translate "Could not apply the Jellyfin configuration:") $configuration_id"
      fi
      oci_quiet pct start "$VMID" || die "$(translate "The container could not be started:") CT $VMID"
      msg_ok "$(translate "Jellyfin configuration applied:") $configuration_id"
      ;;
    *) die "$(translate "Unsupported post-start configuration:") $type" ;;
  esac
}

# $1: optional result label shown before the address.
detect_container_ipv4() {
  local attempt addresses label=${1:-}
  if [[ -n ${HOST_MONITOR:-} ]]; then
    IP=$HOST_MONITOR_IP
    msg_ok "${label:+$label · }$(translate "IP address:") $IP"
    return 0
  fi
  IP=""
  for attempt in $(seq 1 15); do
    IP=$(lxc-info -n "$VMID" -iH 2>/dev/null | grep -m1 -E '^[0-9]+\.' || true)
    if [[ -z $IP ]]; then
      addresses=$(pct exec "$VMID" -- hostname -I 2>/dev/null || true)
      IP=$(tr ' ' '\n' <<<"$addresses" | grep -m1 -E '^[0-9]+\.' || true)
    fi
    [[ -n $IP ]] && break
    msg_progress "$(translate "Waiting for the network address...") $((attempt * 2))/30 s"
    sleep 2
  done
  if [[ -n $IP ]]; then
    msg_ok "${label:+$label · }$(translate "IP address:") $IP"
  else
    [[ -z $label ]] || msg_ok "$label"
    msg_warn "$(translate "No IPv4 address was detected after 30 seconds.")"
  fi
}

trap cleanup_failed_install EXIT

# A credential the image prints on its boot console, captured with the regular
# expression of the template (one capture group, the last match wins).
capture_console_credential() {
  local logfile=$1 pattern=$2 timeout=$3
  local elapsed=0 password=""
  while (( elapsed < timeout )); do
    if [[ -s $logfile ]]; then
      password=$(tr -d '\r' <"$logfile" | python3 -c 'import re, sys
matches = re.findall(sys.argv[1], sys.stdin.read())
print(matches[-1] if matches else "")' "$pattern")
      [[ -n $password ]] && break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
    msg_progress "$(translate "Waiting for the temporary password...") ${elapsed}/${timeout} s" >&2
  done
  printf '%s' "$password"
}

# A credential that the application writes into a file of its own container.
capture_container_file_credential() {
  local vmid=$1 path=$2 pattern=$3 timeout=$4
  local elapsed=0 content="" value=""
  while (( elapsed < timeout )); do
    content=$(pct exec "$vmid" -- cat "$path" 2>/dev/null) || content=""
    if [[ -n $content ]]; then
      if [[ -n $pattern ]]; then
        value=$(printf '%s' "$content" | python3 -c 'import re, sys
match = re.search(sys.argv[1], sys.stdin.read(), re.M)
print(match.group(1) if match else "")' "$pattern")
      else
        value=$(head -n 1 <<<"$content")
      fi
      value=$(tr -d '\r\n' <<<"$value")
      [[ -n $value ]] && { printf '%s' "$value"; return 0; }
    fi
    sleep 3
    elapsed=$((elapsed + 3))
    msg_progress "$(translate "Waiting for the password of the application...") ${elapsed}/${timeout} s" >&2
  done
  return 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$(translate "Required command not found:") $1"
}

json_value() {
  jq -er "$1" "$2"
}

append_deployment_environment_csv() {
  local name=$1 value=$2 temporary
  temporary=$(mktemp)
  jq --arg name "$name" --arg value "$value" '
    .environment = ((.environment // []) as $environment |
      if ($environment | any(.name == $name)) then
        $environment | map(
          if .name == $name then
            .value = (((.value // "") | split(",")) + [$value]
              | map(select(length > 0)) | unique | join(","))
          else . end
        )
      else
        $environment + [{name: $name, value: $value, sensitive: false}]
      end)
  ' "$DEPLOYMENT_FILE" >"$temporary"
  cat "$temporary" >"$DEPLOYMENT_FILE"
  rm -f "$temporary"
}

set_lxc_directive() {
  local key=$1 value=$2 escaped_key temporary_conf
  escaped_key=${key//./\.}
  temporary_conf=$(mktemp)
  sed -E "/^${escaped_key}:/d" "$CONF" >"$temporary_conf"
  printf '%s: %s\n' "$key" "$value" >>"$temporary_conf"
  cat "$temporary_conf" >"$CONF"
  rm -f "$temporary_conf"
}

add_device() {
  local host_path=$1 expected_type=$2 mode_spec=$3 gid_strategy=$4 deny_write=$5
  local device_uid=${6:-}
  local mode gid dev_value
  [[ $host_path == /dev/* && $host_path != *[[:space:]]* && $host_path != *","* ]] \
    || die "$(translate "Invalid device path:") $host_path"
  if [[ $expected_type == character ]]; then
    [[ -c $host_path ]] || die "$(translate "The character device does not exist:") $host_path"
  elif [[ $expected_type == block ]]; then
    [[ -b $host_path ]] || die "$(translate "The block device does not exist:") $host_path"
  else
    die "$(translate "Unsupported native device type:") $expected_type"
  fi
  if [[ $mode_spec == preserve-host ]]; then
    mode=$(stat -c '%a' "$host_path")
    mode="0${mode}"
  else
    mode=$mode_spec
  fi
  [[ $mode =~ ^0?[0-7]{3}$ ]] || die "$(translate "Invalid device mode:") $mode"
  dev_value="path=${host_path},mode=${mode},deny-write=${deny_write}"
  if [[ -n $device_uid ]]; then
    [[ $device_uid =~ ^[0-9]{1,10}$ ]] && (( device_uid < 4294967295 )) \
      || die "$(translate "Invalid device UID:") $device_uid"
    dev_value="${dev_value},uid=${device_uid}"
  fi
  if [[ $gid_strategy == host-device-gid ]]; then
    gid=$(stat -c '%g' "$host_path")
    dev_value="${dev_value},gid=${gid}"
  elif [[ $gid_strategy != none ]]; then
    die "$(translate "Unsupported GID strategy:") $gid_strategy"
  fi
  oci_quiet pct set "$VMID" "--dev${DEVICE_INDEX}" "$dev_value" \
    || die "$(translate "Could not add the device to the container:") $host_path"
  if [[ $expected_type == character ]]; then
    RESOLVED_CHARACTER_DEVICES+=("$host_path")
  fi
  DEVICE_INDEX=$((DEVICE_INDEX + 1))
}

add_character_device() {
  add_device "$1" character "$2" "$3" "$4" "${5:-}"
}

prepare_nvidia_driver_links() {
  local source=$1 target=$2
  local rootfs="/var/lib/lxc/${VMID}/rootfs"
  local host_link link_target container_link failed=0
  [[ $target == /usr/lib/* ]] || return 0

  mount_ct_rootfs
  while IFS= read -r host_link; do
    [[ $(readlink -f "$host_link") == "$source" ]] || continue
    link_target=$(readlink "$host_link")
    container_link="${rootfs}${host_link}"
    if [[ -e $container_link && ! -f $container_link && ! -L $container_link ]]; then
      oci_log "The NVIDIA link cannot replace this target: $host_link"
      failed=1
      break
    fi
    ensure_rootfs_directory "$rootfs" "$(dirname "$container_link")" || failed=1
    rm -f "$container_link" || failed=1
    ln -s "$link_target" "$container_link" || failed=1
  done < <(find "$(dirname "$target")" -maxdepth 1 -type l -print 2>/dev/null | sort)
  oci_quiet pct unmount "$VMID" || failed=1
  (( failed == 0 )) || die "$(translate "Could not prepare the NVIDIA driver links")"
}

source "$SCRIPT_DIR/oci_nvidia_setup.sh"

apply_extra_hosts() {
  local count rootfs hosts_file temporary address hostname bridge_address failed=0
  count=$(jq '.extra_hosts? // [] | length' "$DEPLOYMENT_FILE")
  (( count > 0 )) || return 0
  rootfs="/var/lib/lxc/${VMID}/rootfs"
  hosts_file="${rootfs}/etc/hosts"
  bridge_address=$(ip -4 -o addr show dev "$BRIDGE" 2>/dev/null \
    | awk '{split($4, parts, "/"); print parts[1]; exit}')
  mount_ct_rootfs
  if [[ ! -e $hosts_file ]]; then
    install -D -m 0644 /dev/null "$hosts_file" || failed=1
  fi
  temporary=$(mktemp)
  awk '
    $0 == "# BEGIN PROXMENUX EXTRA HOSTS" {skip=1; next}
    $0 == "# END PROXMENUX EXTRA HOSTS" {skip=0; next}
    !skip {print}
  ' "$hosts_file" >"$temporary" || failed=1
  if (( failed == 0 )); then
    printf '\n# BEGIN PROXMENUX EXTRA HOSTS\n' >>"$temporary"
    while IFS=$'\t' read -r hostname address; do
      [[ -n $hostname ]] || continue
      if [[ $address == host-gateway ]]; then
        [[ -n $bridge_address ]] \
          || { oci_log "Could not resolve host-gateway on $BRIDGE"; failed=1; break; }
        address=$bridge_address
      fi
      [[ $hostname =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] \
        || { oci_log "Invalid extra hostname: $hostname"; failed=1; break; }
      [[ $address =~ ^[0-9A-Fa-f:.]+$ ]] \
        || { oci_log "Invalid extra host address: $address"; failed=1; break; }
      printf '%s %s\n' "$address" "$hostname" >>"$temporary"
    done < <(jq -r '.extra_hosts[]? | [.hostname,.address] | @tsv' "$DEPLOYMENT_FILE")
    printf '# END PROXMENUX EXTRA HOSTS\n' >>"$temporary"
  fi
  if (( failed == 0 )); then
    cat "$temporary" >"$hosts_file" || failed=1
    chown "$HOST_ROOT_UID:$HOST_ROOT_GID" "$hosts_file" || failed=1
  fi
  rm -f "$temporary"
  oci_quiet pct unmount "$VMID" || failed=1
  (( failed == 0 )) || die "$(translate "Could not apply the Compose extra hosts")"
}

# Settings an update gives back to the rebuilt container before it starts:
# the LAN leg of a suite or stack member and its start order.
apply_kept_settings() {
  local key value
  while IFS=$'\t' read -r key value; do
    [[ -n $key ]] || continue
    [[ $key == net1 || $key == startup ]] \
      || die "$(translate "Unsupported kept setting:") $key"
    oci_quiet pct set "$VMID" "--$key" "$value" \
      || die "$(translate "Could not restore the container setting:") $key"
  done < <(jq -r '.kept_proxmox_settings // {} | to_entries[] | [.key, .value] | @tsv' "$DEPLOYMENT_FILE")
}

apply_runtime_user() {
  local user_spec=$1 rootfs passwd_file group_file user_part group_part uid gid failed=0
  rootfs="/var/lib/lxc/${VMID}/rootfs"
  passwd_file="${rootfs}/etc/passwd"
  group_file="${rootfs}/etc/group"
  user_part=${user_spec%%:*}
  group_part=""
  [[ $user_spec == *:* ]] && group_part=${user_spec#*:}
  mount_ct_rootfs
  if [[ $user_part =~ ^[0-9]+$ ]]; then
    uid=$user_part
    gid=$(awk -F: -v id="$uid" '$3 == id {print $4; exit}' "$passwd_file" 2>/dev/null || true)
  else
    uid=$(awk -F: -v name="$user_part" '$1 == name {print $3; exit}' "$passwd_file" 2>/dev/null || true)
    gid=$(awk -F: -v name="$user_part" '$1 == name {print $4; exit}' "$passwd_file" 2>/dev/null || true)
  fi
  if [[ -n $group_part ]]; then
    if [[ $group_part =~ ^[0-9]+$ ]]; then
      gid=$group_part
    else
      gid=$(awk -F: -v name="$group_part" '$1 == name {print $3; exit}' "$group_file" 2>/dev/null || true)
    fi
  fi
  oci_quiet pct unmount "$VMID" || failed=1
  [[ $uid =~ ^[0-9]+$ && $gid =~ ^[0-9]+$ ]] || failed=1
  (( failed == 0 )) || die "$(translate "Could not resolve the Compose user:") $user_spec"
  set_lxc_directive lxc.init.uid "$uid"
  set_lxc_directive lxc.init.gid "$gid"
}

apply_runtime_groups() {
  local groups_csv=$1 rootfs="/var/lib/lxc/${VMID}/rootfs"
  local group_file="${rootfs}/etc/group" existing resolved group failed=0
  local combined=""
  existing=$(awk -F': ' '$1 == "lxc.init.groups" {print $2; exit}' "$CONF" 2>/dev/null || true)
  [[ -n $existing ]] && combined=$existing
  mount_ct_rootfs
  IFS=',' read -ra GROUP_SPECS <<<"$groups_csv"
  for group in "${GROUP_SPECS[@]}"; do
    [[ -n $group ]] || continue
    if [[ $group =~ ^[0-9]+$ ]]; then
      resolved=$group
    else
      resolved=$(awk -F: -v name="$group" '$1 == name {print $3; exit}' "$group_file" 2>/dev/null || true)
    fi
    if [[ ! $resolved =~ ^[0-9]+$ ]]; then
      oci_log "Could not resolve the Compose supplementary group: $group"
      failed=1
      break
    fi
    if [[ ",${combined}," != *",${resolved},"* ]]; then
      combined="${combined:+${combined},}${resolved}"
    fi
  done
  oci_quiet pct unmount "$VMID" || failed=1
  (( failed == 0 )) || die "$(translate "Could not apply the Compose supplementary groups")"
  [[ -n $combined ]] && set_lxc_directive lxc.init.groups "$combined"
}

apply_installer_profile() {
  local generated_count preparation_count tls_count mounted=0 failed=0
  local rootfs="/var/lib/lxc/${VMID}/rootfs"
  local encoded item path mode owner destination target remove_lost_found owner_strategy
  local only_when_mount_type selected_mount_type
  local entrypoint working_directory halt_signal command_json compose_entrypoint_json user_spec
  local supplemental_groups tls_config cert_path key_path cert_destination key_destination
  local tls_directory valid_days common_name san
  local generated_created=0 volumes_prepared=0 tls_state=""

  generated_count=$(jq '.proxmox.installer_profile.generated_files? // [] | length' "$TEMPLATE_FILE")
  preparation_count=$(jq '.proxmox.installer_profile.volume_preparations? // [] | length' "$TEMPLATE_FILE")
  tls_count=$(jq 'if .proxmox.installer_profile.self_signed_tls? then 1 else 0 end' "$TEMPLATE_FILE")
  if (( generated_count > 0 || preparation_count > 0 || tls_count > 0 )); then
    mount_ct_rootfs
    mounted=1
  fi

  while IFS= read -r encoded; do
    [[ -n $encoded ]] || continue
    item=$(printf '%s' "$encoded" | base64 -d)
    path=$(jq -er '.container_path' <<<"$item")
    mode=$(jq -er '.mode' <<<"$item")
    owner=$(jq -er '.owner' <<<"$item")
    [[ $path == /* && $path != *[[:space:]]* && $path != *","* ]] \
      || { oci_log "Invalid generated file path: $path"; failed=1; break; }
    [[ $mode =~ ^0?[0-7]{3}$ ]] \
      || { oci_log "Invalid generated file mode: $mode"; failed=1; break; }
    destination="${rootfs}${path}"
    [[ ! -L $destination ]] \
      || { oci_log "A generated file is not written over a link: $path"; failed=1; break; }
    [[ ! -e $destination || -f $destination ]] \
      || { oci_log "The generated file target is not a regular file: $path"; failed=1; break; }
    if [[ $(jq -r '.json_defaults // false' <<<"$item") == true ]]; then
      local merged_file
      merged_file=$(mktemp)
      if ! merge_json_defaults \
        <(if [[ -e $destination ]]; then cat "$destination"; else printf '{}'; fi) \
        <(jq -er '.content' <<<"$item") >"$merged_file" 2>>"${OCI_LOG:-/dev/stderr}"; then
        rm -f "$merged_file"
        oci_log "Cannot merge the default JSON values: $path"
        failed=1; break
      fi
      item=$(jq --rawfile content "$merged_file" '.content=$content | .only_if_missing=false' <<<"$item")
      rm -f "$merged_file"
    fi
    if [[ $(jq -r '.only_if_missing // false' <<<"$item") == true && -e $destination ]]; then
      oci_log "Keeping the existing persistent file: $path"
      continue
    fi
    install -D -m "$mode" /dev/null "$destination" || { failed=1; break; }
    jq -er '.content' <<<"$item" >"$destination" || { failed=1; break; }
    case "$owner" in
      mapped-root) chown "$HOST_ROOT_UID:$HOST_ROOT_GID" "$destination" || failed=1 ;;
      mapped-application-user) chown "$HOST_BIND_UID:$HOST_BIND_GID" "$destination" || failed=1 ;;
      *) oci_log "Unsupported generated file owner: $owner"; failed=1 ;;
    esac
    (( failed == 0 )) || break
    oci_log "Generated file created: $path"
    generated_created=$((generated_created + 1))
  done < <(jq -r '.proxmox.installer_profile.generated_files[]? | @base64' "$TEMPLATE_FILE")

  if (( failed == 0 )); then
    while IFS= read -r encoded; do
      [[ -n $encoded ]] || continue
      item=$(printf '%s' "$encoded" | base64 -d)
      target=$(jq -er '.container_path' <<<"$item")
      remove_lost_found=$(jq -r '.remove_lost_found // false' <<<"$item")
      owner_strategy=$(jq -er '.owner_strategy' <<<"$item")
      only_when_mount_type=$(jq -r '.only_when_mount_type // empty' <<<"$item")
      [[ $target == /* && $target != *[[:space:]]* && $target != *","* ]] \
        || { oci_log "Invalid volume preparation path: $target"; failed=1; break; }
      if [[ -n $only_when_mount_type ]]; then
        selected_mount_type=$(jq -r --arg target "$target" \
          '[.mounts[]? | select(.container_path == $target) | .type] | first // empty' \
          "$DEPLOYMENT_FILE")
        if [[ $selected_mount_type != "$only_when_mount_type" ]]; then
          oci_log "Skipping the preparation of $target for mount type ${selected_mount_type:-none}"
          continue
        fi
      fi
      [[ -d ${rootfs}${target} ]] \
        || { oci_log "The volume to prepare does not exist: $target"; failed=1; break; }
      if [[ $remove_lost_found == true ]]; then
        rm -rf "${rootfs}${target}/lost+found" || { failed=1; break; }
      fi
      case "$owner_strategy" in
        mapped-root) chown "$HOST_ROOT_UID:$HOST_ROOT_GID" "${rootfs}${target}" || failed=1 ;;
        mapped-application-user)
          chown "$HOST_BIND_UID:$HOST_BIND_GID" "${rootfs}${target}" || failed=1
          ;;
        *) oci_log "Unsupported owner strategy: $owner_strategy"; failed=1 ;;
      esac
      (( failed == 0 )) || break
      oci_log "Volume prepared before the first start: $target"
      volumes_prepared=$((volumes_prepared + 1))
    done < <(jq -r '.proxmox.installer_profile.volume_preparations[]? | @base64' "$TEMPLATE_FILE")
  fi

  if (( failed == 0 && tls_count == 1 )); then
    require_command openssl
    tls_config=$(jq -c '.proxmox.installer_profile.self_signed_tls' "$TEMPLATE_FILE")
    cert_path=$(jq -er '.certificate_path' <<<"$tls_config")
    key_path=$(jq -er '.private_key_path' <<<"$tls_config")
    valid_days=$(jq -er '.valid_days' <<<"$tls_config")
    [[ $cert_path == /* && $key_path == /* ]] \
      || { oci_log "The TLS paths must be absolute"; failed=1; }
    [[ $valid_days =~ ^[0-9]+$ && $valid_days -ge 1 ]] \
      || { oci_log "Invalid TLS validity"; failed=1; }
    cert_destination="${rootfs}${cert_path}"
    key_destination="${rootfs}${key_path}"
    tls_directory=$(dirname "$cert_destination")
    install -d -m 0700 "$tls_directory" || failed=1
    if (( failed == 0 )); then
      chown "$HOST_ROOT_UID:$HOST_ROOT_GID" "$tls_directory" || failed=1
    fi
    if (( failed == 0 )) && [[ ! -s $cert_destination || ! -s $key_destination ]]; then
      common_name=$HOSTNAME
      san="DNS:${HOSTNAME},DNS:${HOSTNAME}.local"
      if [[ $IPV4 != dhcp ]]; then
        san="${san},IP:${IPV4%%/*}"
      fi
      if (( failed == 0 )); then
        openssl req -x509 -newkey rsa:3072 -sha256 -nodes \
          -days "$valid_days" -subj "/CN=${common_name}" \
          -addext "subjectAltName=${san}" \
          -keyout "$key_destination" -out "$cert_destination" >/dev/null 2>&1 \
          || failed=1
      fi
      (( failed != 0 )) || tls_state=created
    else
      tls_state=reused
    fi
    if (( failed == 0 )); then
      chmod 0600 "$key_destination"
      chmod 0644 "$cert_destination"
      chown "$HOST_ROOT_UID:$HOST_ROOT_GID" "$key_destination" "$cert_destination"
    fi
  fi

  if (( mounted == 1 )); then
    oci_quiet pct unmount "$VMID" || failed=1
  fi
  (( failed == 0 )) || die "$(translate "Could not apply the installer profile")"
  if (( generated_created > 0 )); then
    msg_ok "$(translate "Configuration files generated:") $generated_created"
  fi
  if (( volumes_prepared > 0 )); then
    msg_ok "$(translate "Volumes prepared for the first start:") $volumes_prepared"
  fi
  case "$tls_state" in
    created) msg_ok "$(translate "Self-signed TLS certificate created:") $cert_path" ;;
    reused) msg_ok "$(translate "Existing TLS certificate reused:") $cert_path" ;;
  esac

  entrypoint=$(jq -r '.proxmox.installer_profile.runtime.entrypoint // empty' "$TEMPLATE_FILE")
  # An empty Compose command is no command at all: the image keeps its own.
  command_json=$(jq -c '(.proxmox.installer_profile.runtime? // {}) as $runtime
    | if ($runtime | has("command")) and ($runtime.command != null)
        and ((($runtime.command | type) != "array") or (($runtime.command | length) > 0))
      then $runtime.command else null end' "$TEMPLATE_FILE")
  compose_entrypoint_json=$(jq -c 'if (.proxmox.installer_profile.runtime? // {}) | has("compose_entrypoint") then .proxmox.installer_profile.runtime.compose_entrypoint else null end' "$TEMPLATE_FILE")
  working_directory=$(jq -r '.proxmox.installer_profile.runtime.working_directory // empty' "$TEMPLATE_FILE")
  user_spec=$(jq -r '.proxmox.installer_profile.runtime.user // empty' "$TEMPLATE_FILE")
  supplemental_groups=$(jq -r '.proxmox.installer_profile.runtime.supplemental_groups? // [] | join(",")' "$TEMPLATE_FILE")
  halt_signal=$(jq -r '.proxmox.installer_profile.runtime.halt_signal // empty' "$TEMPLATE_FILE")
  if [[ -n $entrypoint ]]; then
    [[ $entrypoint == /* && $entrypoint != *$'\n'* ]] || die "$(translate "Invalid declarative entrypoint")"
    oci_quiet pct set "$VMID" --entrypoint "$entrypoint" \
      || die "$(translate "Could not set the container entrypoint")"
  elif [[ $command_json != null || $compose_entrypoint_json != null ]]; then
    entrypoint=$(python3 "$OCI_RUNTIME_RESOLVER" "$ARCHIVE_PATH" \
      "$command_json" "$compose_entrypoint_json" 2>>"${OCI_LOG:-/dev/stderr}") \
      || die "$(translate "Could not translate the Compose command/entrypoint")"
    oci_quiet pct set "$VMID" --entrypoint "$entrypoint" \
      || die "$(translate "Could not set the container entrypoint")"
  fi
  if [[ -n $working_directory ]]; then
    [[ $working_directory == /* && $working_directory != *[[:space:]]* ]] \
      || die "$(translate "Invalid declarative working directory")"
    set_lxc_directive lxc.init.cwd "$working_directory"
  fi
  if [[ -n $user_spec ]]; then
    apply_runtime_user "$user_spec"
  fi
  if [[ -n $supplemental_groups ]]; then
    apply_runtime_groups "$supplemental_groups"
  fi
  if [[ -n $halt_signal ]]; then
    [[ $halt_signal =~ ^SIG[A-Z0-9]+$ ]] || die "$(translate "Invalid declarative stop signal")"
    set_lxc_directive lxc.signal.halt "$halt_signal"
  fi
}

[[ $EUID -eq 0 ]] || die "$(translate "The remote installer must run as root on Proxmox VE")"
for command in pct pvesh pvesm skopeo jq sha256sum python3 mktemp flock; do
  require_command "$command"
done

VERIFY_OCI_ARCHIVE="${SCRIPT_DIR}/verify_oci_archive.py"
OCI_RUNTIME_RESOLVER="${SCRIPT_DIR}/oci_runtime.py"
OCI_ROOTFS_UNSHIFTER="${SCRIPT_DIR}/unshift_oci_rootfs.py"
JELLYFIN_CONFIGURATOR="${SCRIPT_DIR}/configure_jellyfin_encoding.py"
[[ -r $VERIFY_OCI_ARCHIVE ]] || die "$(translate "Installer file not found:") $VERIFY_OCI_ARCHIVE"
[[ -r $OCI_RUNTIME_RESOLVER ]] || die "$(translate "Installer file not found:") $OCI_RUNTIME_RESOLVER"
[[ -r $OCI_ROOTFS_UNSHIFTER ]] || die "$(translate "Installer file not found:") $OCI_ROOTFS_UNSHIFTER"
[[ -r $JELLYFIN_CONFIGURATOR ]] || die "$(translate "Installer file not found:") $JELLYFIN_CONFIGURATOR"

APP_ID=$(json_value '.id' "$TEMPLATE_FILE")
LOG_NAME=${APP_ID#image-}
oci_log_init "${LOG_NAME#linuxserver-}"
oci_log "OCI install: $APP_ID (dry run: $DRY_RUN)"
STATUS=$(json_value '.status' "$TEMPLATE_FILE")
IMAGE_REF=$(json_value '.container_contract.image.reference' "$TEMPLATE_FILE")
REVISION=$(json_value '.source.revision' "$TEMPLATE_FILE")
PROVIDER=$(jq -r '.source.provider // "unknown"' "$TEMPLATE_FILE")
CATEGORY=$(jq -r '.catalog_ui.category // "misc"' "$TEMPLATE_FILE")
CATEGORY=$(tr '[:upper:]' '[:lower:]' <<<"$CATEGORY" | tr -cs 'a-z0-9_.-' '-')
CATEGORY=${CATEGORY#-}
CATEGORY=${CATEGORY%-}
[[ -n $CATEGORY && $CATEGORY != linuxserver ]] || CATEGORY="misc"
STARTUP_HEALTHCHECK=$(jq -c '.proxmox.installer_profile.startup_healthcheck? // null' "$TEMPLATE_FILE")
HAOS_HEALTHCHECK=$(jq -r '.proxmox.installer_profile.haos_healthcheck.timeout_seconds? // 0' "$TEMPLATE_FILE")
if [[ $HAOS_HEALTHCHECK != 0 ]]; then
  [[ $HAOS_HEALTHCHECK =~ ^[0-9]+$ && $HAOS_HEALTHCHECK -ge 60 && $HAOS_HEALTHCHECK -le 3600 ]] || die "$(translate "Invalid Home Assistant OS check timeout")"
  [[ -r ${SCRIPT_DIR}/haos_healthcheck.py ]] || die "$(translate "Installer file not found:") ${SCRIPT_DIR}/haos_healthcheck.py"
fi
HAS_STARTUP_HEALTHCHECK=$(jq -r 'if . == null then 0 else 1 end' <<<"$STARTUP_HEALTHCHECK")
HAS_RUNNING_CHECK=0
if [[ $HAS_STARTUP_HEALTHCHECK == 1 && $(jq -r '.type // "http"' <<<"$STARTUP_HEALTHCHECK") == running ]]; then
  HAS_STARTUP_HEALTHCHECK=0
  HAS_RUNNING_CHECK=1
fi
if [[ $HAS_STARTUP_HEALTHCHECK == 1 ]]; then
  require_command curl
fi
HOST_MODULE_COUNT=$(jq '.security.host_modules? // [] | length' "$DEPLOYMENT_FILE")
if (( HOST_MODULE_COUNT > 0 )); then
  require_command modprobe
  while IFS= read -r HOST_MODULE; do
    [[ $HOST_MODULE =~ ^[A-Za-z0-9_-]+$ ]] \
      || die "$(translate "Invalid host kernel module name:") $HOST_MODULE"
    msg_info "$(translate "Loading the host kernel module:") $HOST_MODULE..."
    oci_quiet modprobe "$HOST_MODULE" || die "$(translate "Could not load the host kernel module:") $HOST_MODULE"
    MODULE_SYSFS=${HOST_MODULE//-/_}
    [[ -d /sys/module/$MODULE_SYSFS ]] \
      || die "$(translate "The kernel module is not active:") $HOST_MODULE"
    msg_ok "$(translate "Host kernel module loaded:") $HOST_MODULE"
  done < <(jq -r '.security.host_modules[]?' "$DEPLOYMENT_FILE")
fi
VMID=$(jq -r '.vmid // empty' "$DEPLOYMENT_FILE")
if [[ -z $VMID ]]; then
  VMID=$(pvesh get /cluster/nextid)
fi
[[ $VMID =~ ^[0-9]+$ ]] || die "$(translate "Invalid VMID:") $VMID"
pct config "$VMID" >/dev/null 2>&1 && die "$(translate "The CT already exists:") $VMID"

HOSTNAME=$(json_value '.hostname' "$DEPLOYMENT_FILE")
ROOTFS_STORAGE=$(json_value '.rootfs.storage' "$DEPLOYMENT_FILE")
ROOTFS_SIZE=$(json_value '.rootfs.size_gb' "$DEPLOYMENT_FILE")
TEMPLATE_STORAGE=$(json_value '.template_storage' "$DEPLOYMENT_FILE")
CORES=$(json_value '.resources.cores' "$DEPLOYMENT_FILE")
CPU_UNITS=$(jq -r '.resources.cpu_units // empty' "$DEPLOYMENT_FILE")
MEMORY=$(json_value '.resources.memory_mb' "$DEPLOYMENT_FILE")
validate_rlimits
SWAP=$(json_value '.resources.swap_mb' "$DEPLOYMENT_FILE")
BRIDGE=$(json_value '.network.bridge' "$DEPLOYMENT_FILE")
IPV4=$(json_value '.network.ipv4' "$DEPLOYMENT_FILE")
MAC_ADDRESS=$(jq -r '.network.mac_address // empty' "$DEPLOYMENT_FILE")
GATEWAY=$(jq -r '.network.gateway // empty' "$DEPLOYMENT_FILE")
FIREWALL=$(json_value '.network.firewall | if . then 1 else 0 end' "$DEPLOYMENT_FILE")
validate_host_monitor
ONBOOT=$(json_value '.onboot | if . then 1 else 0 end' "$DEPLOYMENT_FILE")
START_AFTER=$(json_value '.start_after_create | if . then 1 else 0 end' "$DEPLOYMENT_FILE")
SHUTDOWN_TIMEOUT=$(json_value '.shutdown_timeout_seconds' "$DEPLOYMENT_FILE")
[[ $SHUTDOWN_TIMEOUT =~ ^[0-9]+$ && $SHUTDOWN_TIMEOUT -gt 0 ]] \
  || die "$(translate "Invalid shutdown timeout")"
ARCH=$(dpkg --print-architecture)
case "$ARCH" in
  amd64|arm64) ;;
  *) die "$(translate "Unsupported architecture:") $ARCH" ;;
esac
jq -e --arg architecture "$ARCH" '.catalog_ui.architectures | index($architecture) != null' \
  "$TEMPLATE_FILE" >/dev/null || die "$(translate "The image does not declare support for this architecture:") $ARCH"
SELECTED_HARDWARE_PROFILE=$(jq -r '.hardware_profile // empty' "$DEPLOYMENT_FILE")
if [[ -n $SELECTED_HARDWARE_PROFILE ]]; then
  jq -e --arg profile "$SELECTED_HARDWARE_PROFILE" --arg architecture "$ARCH" '
    [.proxmox.installer_profile.hardware_acceleration.profiles[]?
      | select(.id == $profile)]
    | if length == 1 then
        ((.[0].architectures // ["amd64", "arm64"]) | index($architecture) != null)
      else false end
  ' "$TEMPLATE_FILE" >/dev/null \
    || die "$(translate "The acceleration profile does not support this architecture:") $SELECTED_HARDWARE_PROFILE ($ARCH)"
fi

show_gpu_inventory
validate_gpu_vendors
oci_log "Application: $APP_ID; image: $IMAGE_REF; CT $VMID ($HOSTNAME); architecture: $ARCH"

if [[ $DRY_RUN == 1 ]]; then
  msg_info2 "$(translate "Application:") $APP_ID"
  msg_info2 "$(translate "Image:") $IMAGE_REF"
  msg_info2 "CT $VMID ($HOSTNAME)"
  msg_info2 "$(translate "Architecture:") $ARCH"
  msg_ok "$(translate "Remote dry run completed; no container was created.")"
  exit 0
fi

# Hold the registry lock through installation so reconciliation cannot race it.
INSTANCE_ROOT=${PROXMENUX_OCI_INSTANCE_ROOT:-/usr/local/share/proxmenux/oci/instances}
if [[ -n ${PROXMENUX_OCI_TRANSACTION:-} ]]; then
  INSTANCE_ID=$(python3 "${SCRIPT_DIR}/oci_instance_transaction.py" --root "$INSTANCE_ROOT" \
    authorize-candidate "$VMID" --journal "$PROXMENUX_OCI_TRANSACTION" \
    --template "$TEMPLATE_FILE" --deployment "$DEPLOYMENT_FILE")
else
[[ ! -L $INSTANCE_ROOT && ! -L $INSTANCE_ROOT/.lock ]] || die "$(translate "The instance registry is not safe")"
install -d -m 0700 "$INSTANCE_ROOT"
exec 9>>"$INSTANCE_ROOT/.lock"
chmod 600 "$INSTANCE_ROOT/.lock"
flock -n 9 || die "$(translate "Another OCI operation is using the instance registry")"
export PROXMENUX_INSTANCE_LOCK_FD=9
# pct start spawns long-lived monitors; they must not retain our registry lock.
pct() { command pct "$@" 9>&-; }
INSTANCE_ID=$(python3 "${SCRIPT_DIR}/oci_instances.py" prepare "$VMID" \
  --template "$TEMPLATE_FILE" --deployment "$DEPLOYMENT_FILE")
INSTANCE_CONTRACT="$INSTANCE_ROOT/$VMID/oci-compose.json"
# The persisted contract is the source for the actual installation inputs.
jq '.template' "$INSTANCE_CONTRACT" >"$TEMPLATE_FILE"
jq '.deployment' "$INSTANCE_CONTRACT" >"$DEPLOYMENT_FILE"
fi

skopeo_transport_reference() {
  local reference=$1 name digest
  if [[ $reference == *@sha256:* ]]; then
    name=${reference%@sha256:*}
    digest="sha256:${reference##*@sha256:}"
    [[ ${name##*/} == *:* ]] && name=${name%:*}
    printf '%s@%s' "$name" "$digest"
  else
    printf '%s' "$reference"
  fi
}

resolve_image_manifest() {
  local image=$1 manifest_file error_file pid elapsed=0 status=0
  manifest_file=$(mktemp /tmp/proxmenux-oci-inspect.XXXXXX)
  error_file="${manifest_file}.err"
  oci_log "Querying the registry for ${image} (${ARCH})"
  skopeo inspect --no-tags --override-os linux --override-arch "$ARCH" \
    "docker://${image}" >"$manifest_file" 2>"$error_file" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    sleep 2
    elapsed=$((elapsed + 2))
  done
  wait "$pid" || status=$?
  if (( status != 0 )); then
    [[ -z ${OCI_LOG:-} ]] || cat "$error_file" >>"$OCI_LOG"
    rm -f "$manifest_file" "$error_file"
    return "$status"
  fi
  oci_log "Manifest resolved in ${elapsed}s"
  cat "$manifest_file"
  rm -f "$manifest_file" "$error_file"
}

if [[ -n ${PROXMENUX_OCI_TRANSACTION:-} ]]; then
  ARCHIVE_PATH=$(jq -er '.archive' "$PROXMENUX_OCI_TRANSACTION")
  ARCHIVE_VOLUME=$ARCHIVE_PATH
  DIGEST=$(jq -er '.registry_digest' "$PROXMENUX_OCI_TRANSACTION")
  CREATED=""
  IMAGE_VERSION=""
  msg_ok "$(translate "Using the image verified by the transaction")"
else
SKOPEO_IMAGE_REF=$(skopeo_transport_reference "$IMAGE_REF")
if [[ $SKOPEO_IMAGE_REF != "$IMAGE_REF" ]]; then
  oci_log "Digest-pinned reference; Skopeo-compatible form: $SKOPEO_IMAGE_REF"
fi
msg_info "$(translate "Checking the image in the registry...")"
INSPECT=$(resolve_image_manifest "$SKOPEO_IMAGE_REF") \
  || die "$(translate "Could not resolve the OCI manifest of the image:") $IMAGE_REF"
DIGEST=$(jq -er '.Digest' <<<"$INSPECT")
oci_log "Selected digest: $DIGEST"
CREATED=$(jq -r '.Created // empty' <<<"$INSPECT")
IMAGE_VERSION=$(jq -r '.Labels["org.opencontainers.image.version"] // .Labels.build_version // empty' <<<"$INSPECT")
TOTAL_LAYER_BYTES=$(jq -r '[.LayersData[]?.Size] | add // 0' <<<"$INSPECT")
TOTAL_LAYER_COUNT=$(jq -r '[.LayersData[]?] | length' <<<"$INSPECT")
DIGEST_SHORT=${DIGEST#sha256:}
DIGEST_SHORT=${DIGEST_SHORT:0:16}
msg_ok "$(translate "Image:") $IMAGE_REF (${IMAGE_VERSION:-sha256:${DIGEST_SHORT:0:12}})"
SAFE_APP=$(tr -cs 'a-zA-Z0-9._-' '_' <<<"$APP_ID" | sed 's/_$//')
ARCHIVE_NAME="${SAFE_APP}_${ARCH}_${DIGEST_SHORT}.tar"
ARCHIVE_VOLUME="${TEMPLATE_STORAGE}:vztmpl/${ARCHIVE_NAME}"
ARCHIVE_PATH=$(pvesm path "$ARCHIVE_VOLUME")
mkdir -p "$(dirname "$ARCHIVE_PATH")"

download_and_verify_archive() {
  local attempt=$1
  local partial_path="${ARCHIVE_PATH}.partial.$$"
  local download_log="${partial_path}.log"
  local copy_pid elapsed current_bytes process_bytes display_bytes current_mib total_mib
  local percentage copy_status started_layers last_bytes=-1 stalled_seconds=0
  local stall_timeout_seconds=180

  rm -f "$partial_path" "$download_log"
  oci_log "Downloading $IMAGE_REF by digest $DIGEST (attempt $attempt/2)"
  skopeo copy --override-os linux --override-arch "$ARCH" \
    --retry-times 3 --retry-delay 5s --image-parallel-copies 1 \
    "docker://$SKOPEO_IMAGE_REF" "oci-archive:${partial_path}:${APP_ID}" \
    >"$download_log" 2>&1 &
  copy_pid=$!
  elapsed=0
  total_mib=$(( (TOTAL_LAYER_BYTES + 1048575) / 1048576 ))
  while kill -0 "$copy_pid" 2>/dev/null; do
    current_bytes=$(stat -c %s "$partial_path" 2>/dev/null || printf '0')
    process_bytes=$(awk '$1 == "rchar:" { print $2 }' "/proc/${copy_pid}/io" 2>/dev/null || printf '0')
    if (( process_bytes > current_bytes )); then
      current_bytes=$process_bytes
    fi
    if (( current_bytes > last_bytes )); then
      last_bytes=$current_bytes
      stalled_seconds=0
    else
      stalled_seconds=$((stalled_seconds + 2))
    fi
    started_layers=$(awk '/^Copying blob / { count++ } END { print count + 0 }' "$download_log" 2>/dev/null || printf '0')
    if (( TOTAL_LAYER_BYTES > 0 )); then
      display_bytes=$current_bytes
      if (( display_bytes >= TOTAL_LAYER_BYTES )); then
        display_bytes=$((TOTAL_LAYER_BYTES * 99 / 100))
      fi
      current_mib=$(( display_bytes / 1048576 ))
      percentage=$(( display_bytes * 100 / TOTAL_LAYER_BYTES ))
      if (( started_layers > TOTAL_LAYER_COUNT )); then
        started_layers=$TOTAL_LAYER_COUNT
      fi
      if (( percentage > 99 )); then
        percentage=99
      fi
      msg_progress "$(translate "Downloading the image:") ${current_mib} / ${total_mib} MiB (${percentage}%), $(translate "layers") ${started_layers}/${TOTAL_LAYER_COUNT}, ${elapsed}s"
    else
      current_mib=$(( current_bytes / 1048576 ))
      msg_progress "$(translate "Downloading the image:") ${current_mib} MiB, ${elapsed}s"
    fi
    if (( stalled_seconds >= stall_timeout_seconds )); then
      oci_log "The download made no progress for ${stall_timeout_seconds}s; cancelling this attempt"
      msg_warn "$(translate "The download stopped progressing; cancelling this attempt.")"
      kill "$copy_pid" 2>/dev/null || true
      sleep 2
      kill -9 "$copy_pid" 2>/dev/null || true
      break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  copy_status=0
  wait "$copy_pid" || copy_status=$?
  if (( copy_status != 0 )); then
    [[ -z ${OCI_LOG:-} ]] || cat "$download_log" >>"$OCI_LOG"
    rm -f "$partial_path" "$download_log"
    oci_log "The image download failed (exit code $copy_status)"
    return 1
  fi
  [[ -z ${OCI_LOG:-} ]] || cat "$download_log" >>"$OCI_LOG"
  rm -f "$download_log"
  msg_ok "$(translate "Image downloaded") ($(( ($(stat -c %s "$partial_path") + 1048575) / 1048576 )) MiB)"
  msg_info "$(translate "Verifying the image integrity...")"
  if ! oci_quiet python3 "$VERIFY_OCI_ARCHIVE" "$partial_path"; then
    rm -f "$partial_path"
    return 1
  fi
  mv -f "$partial_path" "$ARCHIVE_PATH"
  msg_ok "$(translate "Image integrity verified")"
  return 0
}

if [[ -s $ARCHIVE_PATH ]]; then
  oci_log "Verifying the cached image: $ARCHIVE_VOLUME"
  msg_info "$(translate "Verifying the image integrity...")"
  if oci_quiet python3 "$VERIFY_OCI_ARCHIVE" "$ARCHIVE_PATH"; then
    msg_ok "$(translate "Using the verified image from the cache")"
  else
    msg_warn "$(translate "The cached image is damaged; it will be downloaded again.")"
    rm -f "$ARCHIVE_PATH"
  fi
fi

if [[ ! -s $ARCHIVE_PATH ]]; then
  for attempt in 1 2; do
    download_and_verify_archive "$attempt" && break
    if (( attempt == 2 )); then
      die "$(translate "Could not obtain an intact image after two attempts")"
    fi
    msg_warn "$(translate "The image download did not complete correctly; downloading it again...")"
  done
fi
fi

DESCRIPTION="proxmenux-instance=${INSTANCE_ID}"
UNPRIVILEGED=$(jq -r 'if .security | has("unprivileged") then .security.unprivileged else true end' "$DEPLOYMENT_FILE")
case "$UNPRIVILEGED" in
  true) UNPRIVILEGED_FLAG=1 ;;
  false) UNPRIVILEGED_FLAG=0 ;;
  *) die "$(translate "Invalid security.unprivileged value:") $UNPRIVILEGED" ;;
esac
if [[ $UNPRIVILEGED_FLAG == 0 ]] && \
   [[ $(jq -r '.security.privileged_acknowledged // false' "$DEPLOYMENT_FILE") != true ]]; then
  die "$(translate "The privileged deployment does not include the required explicit consent")"
fi
PVE_TAGS="${CATEGORY};oci"
if [[ $PROVIDER == linuxserver.io ]]; then
  PVE_TAGS="linuxserver;${PVE_TAGS}"
fi
PVE_TAGS="${PVE_TAGS};proxmenux"
NET="name=eth0,bridge=${BRIDGE},firewall=${FIREWALL},host-managed=1,ip=${IPV4},type=veth"
if [[ -n $GATEWAY ]]; then
  NET="${NET},gw=${GATEWAY}"
fi
if [[ -n $MAC_ADDRESS ]]; then
  [[ $MAC_ADDRESS =~ ^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$ ]] \
    || die "$(translate "Invalid MAC address:") $MAC_ADDRESS"
  NET="${NET},hwaddr=${MAC_ADDRESS}"
fi

CREATE_UNPRIVILEGED_FLAG=$UNPRIVILEGED_FLAG
if [[ $UNPRIVILEGED_FLAG == 0 ]]; then
  # Proxmox 9.2 cannot extract OCI archives directly as privileged LXCs.
  # Import with the standard idmap, unshift once while stopped, then switch the config.
  CREATE_UNPRIVILEGED_FLAG=1
fi
CREATE_ARGS=(
  "$VMID" "$ARCHIVE_VOLUME"
  --hostname "$HOSTNAME"
  --rootfs "${ROOTFS_STORAGE}:${ROOTFS_SIZE}"
  --memory "$MEMORY"
  --swap "$SWAP"
  --unprivileged "$CREATE_UNPRIVILEGED_FLAG"
  --onboot "$ONBOOT"
  --description "$DESCRIPTION"
  --tags "$PVE_TAGS"
)
configure_cpu_allocation
CREATE_ARGS+=("${CPU_CREATE_ARGS[@]}")
if [[ -z $HOST_MONITOR ]]; then
  CREATE_ARGS+=(--net0 "$NET")
fi

OSTYPE=$(jq -r '.ostype // "auto-from-image"' "$DEPLOYMENT_FILE")
case "$OSTYPE" in
  auto-from-image) ;;
  unmanaged) CREATE_ARGS+=(--ostype unmanaged) ;;
  *) die "$(translate "Unsupported declarative ostype:") $OSTYPE" ;;
esac

if [[ -n $CPU_UNITS ]]; then
  [[ $CPU_UNITS =~ ^[0-9]+$ && $CPU_UNITS -ge 8 && $CPU_UNITS -le 10000 ]] \
    || die "$(translate "cpuunits must be between 8 and 10000")"
  CREATE_ARGS+=(--cpuunits "$CPU_UNITS")
fi

FEATURES=$(jq -r '.features | join(",")' "$DEPLOYMENT_FILE")
if [[ -n $FEATURES ]]; then
  CREATE_ARGS+=(--features "$FEATURES")
fi

# pct keeps the OCI Entrypoint/Cmd/Env/User/WorkingDir/StopSignal metadata.
msg_info "$(translate "Creating the container...")"
oci_quiet pct create "${CREATE_ARGS[@]}" \
  || die "$(translate "Could not create the container:") CT $VMID"
CT_CREATED=1
msg_ok "$(translate "Container created:") CT $VMID ($HOSTNAME)"

CONF="/etc/pve/lxc/${VMID}.conf"
if [[ $UNPRIVILEGED_FLAG == 0 ]]; then
  msg_info "$(translate "Converting the container to privileged...")"
  mount_ct_rootfs
  oci_quiet python3 "$OCI_ROOTFS_UNSHIFTER" "/var/lib/lxc/${VMID}/rootfs" || {
    pct unmount "$VMID" >/dev/null 2>&1 || true
    die "$(translate "Could not convert the OCI rootfs to privileged")"
  }
  oci_quiet pct unmount "$VMID" \
    || die "$(translate "Could not unmount the container filesystem:") CT $VMID"
  sed -i -E 's/^unprivileged: 1$/unprivileged: 0/' "$CONF"
  grep -q '^unprivileged: 0$' "$CONF" \
    || die "$(translate "Could not enable the privileged profile before the first start")"
  msg_ok "$(translate "Container converted to privileged")"
fi
MOUNT_INDEX=0
CONTAINER_PUID=$(jq -r '[.environment[]? | select(.name == "PUID" or .name == "USER_ID" or .name == "UID") | .value] | last // "0"' "$DEPLOYMENT_FILE")
CONTAINER_PGID=$(jq -r '[.environment[]? | select(.name == "PGID" or .name == "GROUP_ID" or .name == "GID") | .value] | last // "0"' "$DEPLOYMENT_FILE")
IMAGE_VOLUME_UID=$(jq -r '.proxmox.installer_profile.volume_owner.uid // empty' "$TEMPLATE_FILE")
IMAGE_VOLUME_GID=$(jq -r '.proxmox.installer_profile.volume_owner.gid // empty' "$TEMPLATE_FILE")
[[ -z $IMAGE_VOLUME_UID ]] || CONTAINER_PUID=$IMAGE_VOLUME_UID
[[ -z $IMAGE_VOLUME_GID ]] || CONTAINER_PGID=$IMAGE_VOLUME_GID
[[ $CONTAINER_PUID =~ ^[0-9]+$ ]] || CONTAINER_PUID=0
[[ $CONTAINER_PGID =~ ^[0-9]+$ ]] || CONTAINER_PGID=0
if [[ $UNPRIVILEGED_FLAG == 1 ]]; then
  HOST_ROOT_UID=100000
  HOST_ROOT_GID=100000
  HOST_BIND_UID=$((100000 + CONTAINER_PUID))
  HOST_BIND_GID=$((100000 + CONTAINER_PGID))
else
  HOST_ROOT_UID=0
  HOST_ROOT_GID=0
  HOST_BIND_UID=$CONTAINER_PUID
  HOST_BIND_GID=$CONTAINER_PGID
fi

SYSCTL_COUNT=$(jq '.security.sysctls? // [] | length' "$DEPLOYMENT_FILE")
if (( SYSCTL_COUNT > 0 )); then
  SYSCTL_INCLUDE="/etc/pve/lxc/${VMID}.proxmenux-sysctls"
  SYSCTL_TEMP=$(mktemp)
  while IFS=$'\t' read -r SYSCTL_NAME SYSCTL_VALUE; do
    [[ -n $SYSCTL_NAME ]] || continue
    [[ $SYSCTL_NAME =~ ^net\.(ipv4|ipv6)\.[A-Za-z0-9_.-]+$ ]] \
      || die "$(translate "Sysctl not namespaced or not valid:") $SYSCTL_NAME"
    [[ -n $SYSCTL_VALUE && $SYSCTL_VALUE != *$'\n'* && $SYSCTL_VALUE != *$'\r'* ]] \
      || die "$(translate "Invalid sysctl value:") $SYSCTL_NAME"
    printf 'lxc.sysctl.%s = %s\n' "$SYSCTL_NAME" "$SYSCTL_VALUE" >>"$SYSCTL_TEMP"
    oci_log "Network sysctl prepared: ${SYSCTL_NAME}=${SYSCTL_VALUE}"
  done < <(jq -r '.security.sysctls[]? | [.name,.value] | @tsv' "$DEPLOYMENT_FILE")
  [[ ! -L $SYSCTL_INCLUDE ]] || die "$(translate "The sysctl include is a link:") $SYSCTL_INCLUDE"
  # pmxcfs assigns its own permissions and rejects chmod.
  cat "$SYSCTL_TEMP" >"$SYSCTL_INCLUDE"
  rm -f "$SYSCTL_TEMP"
  set_lxc_directive "lxc.include" "$SYSCTL_INCLUDE"
  msg_ok "$(translate "Network sysctls prepared:") $SYSCTL_COUNT"
fi

REQUIRED_CAPABILITIES=$(jq -r '.security.required_capabilities? // [] | join(",")' "$DEPLOYMENT_FILE")
if [[ -n $REQUIRED_CAPABILITIES ]]; then
  msg_ok "$(translate "Compose capabilities validated in the LXC user namespace:") $REQUIRED_CAPABILITIES"
fi

NO_NEW_PRIVILEGES=$(jq -r '.security.options.no_new_privileges? // false' "$DEPLOYMENT_FILE")
APPARMOR_PROFILE=$(jq -r '.security.options.apparmor_profile? // empty' "$DEPLOYMENT_FILE")
SECCOMP_PROFILE=$(jq -r '.security.options.seccomp_profile? // empty' "$DEPLOYMENT_FILE")
SELINUX_LABEL_DISABLED=$(jq -r '.security.options.selinux_label_disabled? // false' "$DEPLOYMENT_FILE")
if [[ $NO_NEW_PRIVILEGES == true ]]; then
  set_lxc_directive "lxc.no_new_privs" "1"
fi
if [[ $(jq -r '.security.options.drop_all_capabilities? // false' "$DEPLOYMENT_FILE") == true ]]; then
  [[ -z $REQUIRED_CAPABILITIES ]] || die "$(translate "Capabilities cannot be kept and all dropped at the same time")"
  set_lxc_directive "lxc.cap.drop" ""
  set_lxc_directive "lxc.cap.keep" "none"
fi
if [[ -n $APPARMOR_PROFILE || -n $SECCOMP_PROFILE ]]; then
  [[ $(jq -r '.security.relaxation_acknowledged // false' "$DEPLOYMENT_FILE") == true ]] \
    || die "$(translate "The AppArmor/seccomp relaxation does not include the required consent")"
fi
if [[ -n $APPARMOR_PROFILE ]]; then
  [[ $APPARMOR_PROFILE == unconfined ]] \
    || die "$(translate "Unsupported OCI-LXC AppArmor profile:") $APPARMOR_PROFILE"
  set_lxc_directive "lxc.apparmor.profile" "unconfined"
fi
if [[ -n $SECCOMP_PROFILE ]]; then
  [[ $SECCOMP_PROFILE == unconfined ]] \
    || die "$(translate "Unsupported OCI-LXC seccomp profile:") $SECCOMP_PROFILE"
  SECCOMP_PROFILE_FILE="/etc/pve/lxc/${VMID}.proxmenux-seccomp"
  printf '2\ndenylist\n[all]\n' >"$SECCOMP_PROFILE_FILE"
  chmod 0640 "$SECCOMP_PROFILE_FILE"
  set_lxc_directive "lxc.seccomp.profile" "$SECCOMP_PROFILE_FILE"
fi
if [[ $SELINUX_LABEL_DISABLED == true ]]; then
  oci_log "label:disable kept as metadata; Proxmox uses AppArmor, not SELinux, for this LXC"
fi
MOUNT_ENTRIES=$(jq '.mounts | if type == "array" then length else 0 end' "$DEPLOYMENT_FILE")
MOUNT_NOTES=()
if (( MOUNT_ENTRIES > 0 )); then
  msg_info "$(translate "Adding the mount points...")"
fi
while IFS=$'\t' read -r TYPE TARGET SOURCE SIZE BACKUP READ_ONLY CREATE_IF_MISSING; do
  [[ -n $TYPE ]] || continue
  [[ $TARGET == /* && $TARGET != *","* ]] || die "$(translate "Invalid container path:") $TARGET"
  RO_OPT=""
  [[ $READ_ONLY == true ]] && RO_OPT=",ro=1"
  if [[ $TYPE == managed-volume ]]; then
    [[ $SIZE =~ ^[0-9]+$ ]] || die "$(translate "Invalid volume size:") $TARGET"
    if [[ -n ${PROXMENUX_OCI_TRANSACTION:-} ]]; then
      REUSE_KEY=$(jq -r --arg path "$TARGET" \
        '.transaction_reuse_mounts[]? | select(.container_path == $path) | .key' "$DEPLOYMENT_FILE")
      if [[ -n $REUSE_KEY ]]; then
        REUSE_VMID=$(jq -er '.transaction_source_vmid' "$DEPLOYMENT_FILE")
        oci_quiet pct move-volume "$REUSE_VMID" "$REUSE_KEY" --target-vmid "$VMID" \
          --target-volume "mp${MOUNT_INDEX}" \
          || die "$(translate "Could not reuse the persistent disk:") $TARGET"
        MP_VALUE=$(pct config "$VMID" | awk -v key="mp${MOUNT_INDEX}: " \
          'index($0,key)==1 { print substr($0,length(key)+1) }')
        REUSED_VOLUME=${MP_VALUE%%,*}
        [[ -n $REUSED_VOLUME ]] || die "$(translate "Cannot verify the reused disk:") $TARGET"
        oci_quiet pct set "$VMID" "--mp${MOUNT_INDEX}" \
          "${REUSED_VOLUME},mp=${TARGET},backup=${BACKUP}${RO_OPT}" \
          || die "$(translate "Could not add the mount point:") $TARGET"
        oci_log "Persistent disk reused: $TARGET"
        MOUNT_NOTES+=("$(translate "Persistent disk reused:") $TARGET")
        MOUNT_INDEX=$((MOUNT_INDEX + 1))
        continue
      fi
    fi
    MP_VALUE="${SOURCE}:${SIZE},mp=${TARGET},backup=${BACKUP}${RO_OPT}"
  elif [[ $TYPE == host-bind ]]; then
    [[ $SOURCE == /* && $SOURCE != *","* ]] || die "$(translate "Invalid host path:") $SOURCE"
    if [[ ! -e $SOURCE && $CREATE_IF_MISSING == true ]]; then
      install -d -m 0775 -o "$HOST_BIND_UID" -g "$HOST_BIND_GID" "$SOURCE"
      oci_log "Shared directory created: $SOURCE (uid=$HOST_BIND_UID gid=$HOST_BIND_GID)"
      MOUNT_NOTES+=("$(translate "Shared directory created:") $SOURCE")
    fi
    [[ -e $SOURCE ]] || die "$(translate "The host bind source does not exist:") $SOURCE"
    if [[ -d $SOURCE ]]; then
      if [[ -n ${PROXMENUX_OCI_TRANSACTION:-} ]]; then
        python3 "${SCRIPT_DIR}/oci_instance_transaction.py" --root "$INSTANCE_ROOT" \
          pin-host-source "$VMID" --journal "$PROXMENUX_OCI_TRANSACTION" --source "$SOURCE"
      fi
      MP_VALUE="${SOURCE},mp=${TARGET},backup=0${RO_OPT}"
    elif [[ -f $SOURCE ]]; then
      [[ $SOURCE != *[[:space:]]* && $TARGET != *[[:space:]]* ]] \
        || die "$(translate "File bind mounts do not support spaces:") $SOURCE -> $TARGET"
      prepare_file_mount_target "$TARGET"
      TARGET=$PREPARED_FILE_TARGET
      TARGET_RELATIVE=${TARGET#/}
      FILE_OPTIONS="bind,create=file"
      [[ $READ_ONLY == true ]] && FILE_OPTIONS="${FILE_OPTIONS},ro"
      printf 'lxc.mount.entry: %s %s none %s 0 0\n' \
        "$SOURCE" "$TARGET_RELATIVE" "$FILE_OPTIONS" >>"$CONF"
      continue
    else
      die "$(translate "The host bind source is not a regular file or directory:") $SOURCE"
    fi
  else
    die "$(translate "Unsupported mount type:") $TYPE"
  fi
  oci_quiet pct set "$VMID" "--mp${MOUNT_INDEX}" "$MP_VALUE" \
    || die "$(translate "Could not add the mount point:") $TARGET"
  MOUNT_INDEX=$((MOUNT_INDEX + 1))
done < <(jq -r '.mounts[] | [.type,.container_path,.source,(.size_gb // "-"),(.backup | if . then 1 else 0 end),.read_only,(.create_if_missing // false)] | @tsv' "$DEPLOYMENT_FILE")
if (( MOUNT_ENTRIES > 0 )); then
  msg_ok "$(translate "Mount points added:") $MOUNT_ENTRIES"
fi
for MOUNT_NOTE in ${MOUNT_NOTES[@]+"${MOUNT_NOTES[@]}"}; do
  msg_ok "$MOUNT_NOTE"
done

while IFS=$'\t' read -r TARGET SIZE_MB OPTIONS; do
  [[ -n $TARGET ]] || continue
  [[ $TARGET == /* && $TARGET != *","* && $TARGET != *[[:space:]]* ]] \
    || die "$(translate "Invalid tmpfs path:") $TARGET"
  [[ $SIZE_MB =~ ^[0-9]+$ && $SIZE_MB -gt 0 ]] || die "$(translate "Invalid tmpfs size:") $TARGET"
  [[ $OPTIONS =~ ^(rw|ro|nosuid|nodev|noexec|mode=0[0-7]{3})(,(rw|ro|nosuid|nodev|noexec|mode=0[0-7]{3}))*$ ]] || die "$(translate "Invalid tmpfs options:") $TARGET"
  TARGET_RELATIVE=${TARGET#/}
  printf 'lxc.mount.entry: tmpfs %s tmpfs %s,size=%sM,create=dir 0 0\n' \
    "$TARGET_RELATIVE" "$OPTIONS" "$SIZE_MB" >>"$CONF"
done < <(jq -r '.tmpfs_mounts[]? | [.container_path,.size_mb,(.mount_options | join(","))] | @tsv' "$DEPLOYMENT_FILE")

DEVICE_INDEX=0
RESOLVED_CHARACTER_DEVICES=()
NVIDIA_RUNTIME_CONFIGURED=0
NVIDIA_GID_ENV=""
NVIDIA_DEVICE_COUNT=0
while IFS= read -r DEVICE_ENCODED; do
  [[ -n $DEVICE_ENCODED ]] || continue
  DEVICE=$(printf '%s' "$DEVICE_ENCODED" | base64 -d)
  DEVICE_KIND=$(jq -r '.kind // "character-device"' <<<"$DEVICE")
  DEVICE_GID_ENV=$(jq -r '.append_host_device_gid_to_environment // empty' <<<"$DEVICE")
  if [[ $DEVICE_KIND == nvidia-runtime ]]; then
    NVIDIA_GID_ENV=$DEVICE_GID_ENV
    if (( NVIDIA_RUNTIME_CONFIGURED == 0 )); then
      NVIDIA_FIRST_INDEX=$DEVICE_INDEX
      configure_nvidia_runtime
      NVIDIA_DEVICE_COUNT=$((DEVICE_INDEX - NVIDIA_FIRST_INDEX))
    fi
    continue
  fi
  HOST_PATH=$(jq -er '.host_path' <<<"$DEVICE")
  CONTAINER_PATH=$(jq -er '.container_path' <<<"$DEVICE")
  MODE=$(jq -er '.mode' <<<"$DEVICE")
  DENY_WRITE=$(jq -r '.deny_write | if . then 1 else 0 end' <<<"$DEVICE")
  GID_STRATEGY=$(jq -er '.gid_strategy' <<<"$DEVICE")
  [[ $HOST_PATH == /dev/* && $HOST_PATH == "$CONTAINER_PATH" ]] \
    || die "$(translate "The device must keep its /dev path inside the LXC:") $HOST_PATH"
  case "$DEVICE_KIND" in
    character-device)
      DEVICE_UID=$(jq -r '.uid // empty' <<<"$DEVICE")
      add_character_device "$HOST_PATH" "$MODE" "$GID_STRATEGY" "$DENY_WRITE" "$DEVICE_UID"
      if [[ -n $DEVICE_GID_ENV ]]; then
        append_deployment_environment_csv "$DEVICE_GID_ENV" "$(stat -c '%g' "$HOST_PATH")"
      fi
      ;;
    block-device)
      add_device "$HOST_PATH" block "$MODE" "$GID_STRATEGY" "$DENY_WRITE"
      if [[ -n $DEVICE_GID_ENV ]]; then
        append_deployment_environment_csv "$DEVICE_GID_ENV" "$(stat -c '%g' "$HOST_PATH")"
      fi
      ;;
    character-device-tree)
      [[ -d $HOST_PATH ]] || die "$(translate "The device directory does not exist:") $HOST_PATH"
      FOUND_TREE_DEVICE=0
      while IFS= read -r TREE_DEVICE; do
        [[ -n $TREE_DEVICE ]] || continue
        add_character_device "$TREE_DEVICE" "$MODE" "$GID_STRATEGY" "$DENY_WRITE"
        FOUND_TREE_DEVICE=1
      done < <(find "$HOST_PATH" -print 2>/dev/null | while IFS= read -r path; do
        [[ -c $path ]] && printf '%s\n' "$path"
      done | sort)
      (( FOUND_TREE_DEVICE == 1 )) \
        || die "$(translate "The directory contains no character devices:") $HOST_PATH"
      ;;
    *) die "$(translate "Unsupported device type:") $DEVICE_KIND" ;;
  esac
done < <(jq -r '.devices[]? | @base64' "$DEPLOYMENT_FILE")
if (( DEVICE_INDEX > NVIDIA_DEVICE_COUNT )); then
  msg_ok "$(translate "Devices added to the container:") $((DEVICE_INDEX - NVIDIA_DEVICE_COUNT))"
fi

apply_native_device_permissions

# PVE represents the public env property as repeated native LXC runtime lines.
# Merge only Compose overrides while the newly-created CT is stopped.
while IFS=$'\t' read -r NAME ENCODED; do
  [[ $NAME =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "$(translate "Invalid variable name:") $NAME"
  VALUE=$(printf '%s' "$ENCODED" | base64 -d)
  [[ $VALUE != *$'\n'* && $VALUE != *$'\r'* ]] || die "$(translate "The variable contains line breaks:") $NAME"
  if LC_ALL=C grep -q '[[:cntrl:]]' <<<"$VALUE"; then
    die "$(translate "The variable contains control characters:") $NAME"
  fi
  TEMP_CONF=$(mktemp)
  awk -v prefix="lxc.environment.runtime: ${NAME}=" 'index($0, prefix) != 1' "$CONF" >"$TEMP_CONF"
  printf 'lxc.environment.runtime: %s=%s\n' "$NAME" "$VALUE" >>"$TEMP_CONF"
  cat "$TEMP_CONF" >"$CONF"
  rm -f "$TEMP_CONF"
done < <(jq -r '.environment[] | [.name, (.value | @base64)] | @tsv' "$DEPLOYMENT_FILE")

apply_extra_hosts
apply_installer_profile
apply_rlimits
apply_host_monitor
apply_kept_settings

while IFS= read -r REPAIR_ENCODED; do
  [[ -n $REPAIR_ENCODED ]] || continue
  run_pre_start_repair "$(printf '%s' "$REPAIR_ENCODED" | base64 -d)"
done < <(jq -r '.proxmox.installer_profile.pre_start_repairs[]? | @base64' "$TEMPLATE_FILE")

DEPLOYMENT_ENVIRONMENT=$(jq -c '.environment // []' "$DEPLOYMENT_FILE")
CREDENTIALS=$(jq -c --argjson environment "$DEPLOYMENT_ENVIRONMENT" '
  def env_value($name):
    [$environment[]? | select(.name == $name) | .value] | last // null;
  [.first_run.credentials[]? |
    if .username_environment? then
      .username = (env_value(.username_environment) // .username)
    else . end |
    if .password_environment? then
      .password = (env_value(.password_environment) // .password)
    else . end |
    del(.username_environment, .password_environment)
  ]
' "$TEMPLATE_FILE")
RUNTIME_CREDENTIALS=$(jq '[.[] | select(.retrieval.method? == "container-console-pattern")] | length' <<<"$CREDENTIALS")

# The console of the container is kept as its log, the way `docker logs` keeps
# it, and the Proxmox console opens a shell when the image has one. Both are
# set before the configuration is recorded, so the record carries them and an
# update, which rebuilds the container through this installer, sets them again.
# The first-boot credentials are read from the same log.
CONSOLE_STATE=$(python3 "${SCRIPT_DIR}/oci_console.py" configure "$VMID") \
  || die "$(translate "The console of the container could not be configured")"
RUNTIME_CONSOLE_LOG=$(jq -r '.log' <<<"$CONSOLE_STATE")

oci_log "Configuration created for CT $VMID"
PASSWORD_STATE=""
if [[ $START_AFTER == 1 ]]; then
  [[ $HAOS_HEALTHCHECK == 0 ]] || PRESERVE_FAILED_CT=1
  msg_info "$(translate "Starting the container...")"
  oci_quiet pct start "$VMID" || die "$(translate "The container could not be started:") CT $VMID"
  verify_host_monitor
  if (( RUNTIME_CREDENTIALS > 0 )); then
    while IFS= read -r encoded; do
      [[ -n $encoded ]] || continue
      credential=$(printf '%s' "$encoded" | base64 -d)
      credential_label=$(jq -r '.label' <<<"$credential")
      credential_pattern=$(jq -r '.retrieval.pattern // empty' <<<"$credential")
      credential_timeout=$(jq -r '.retrieval.timeout_seconds // 90' <<<"$credential")
      if [[ -z $credential_pattern ]]; then
        case "$(jq -r '.retrieval.pattern_id // empty' <<<"$credential")" in
          linuxserver-temporary-password)
            credential_pattern='A temporary password is provided for this session:\s*(\S+)' ;;
          *) die "$(translate "Unsupported credential pattern:") $credential_label" ;;
        esac
      fi
      oci_log "Capturing the credential of ${credential_label} from the boot console"
      msg_progress "$(translate "Waiting for the temporary password...")"
      credential_value=$(capture_console_credential "$RUNTIME_CONSOLE_LOG" "$credential_pattern" "$credential_timeout")
      if [[ -n $credential_value ]]; then
        CREDENTIALS=$(jq -c --arg label "$credential_label" --arg password "$credential_value" \
          'map(if .label == $label and .retrieval.method? == "container-console-pattern" then .password = $password else . end)' \
          <<<"$CREDENTIALS")
        PASSWORD_STATE=retrieved
      else
        CREDENTIALS=$(jq -c --arg label "$credential_label" \
          'map(if .label == $label and .retrieval.method? == "container-console-pattern" then
             . + {retrieval_error: "The credential could not be retrieved from the boot console"} else . end)' \
          <<<"$CREDENTIALS")
        oci_log "The credential of ${credential_label} could not be read from the console"
        PASSWORD_STATE=missing
      fi
    done < <(jq -r '.[] | select(.retrieval.method? == "container-console-pattern") | @base64' <<<"$CREDENTIALS")
  fi
  FILE_CREDENTIALS=$(jq '[.[] | select(.retrieval.method? == "container-file")] | length' <<<"$CREDENTIALS")
  if (( FILE_CREDENTIALS > 0 )); then
    while IFS= read -r encoded; do
      [[ -n $encoded ]] || continue
      credential=$(printf '%s' "$encoded" | base64 -d)
      credential_label=$(jq -r '.label' <<<"$credential")
      credential_path=$(jq -r '.retrieval.path' <<<"$credential")
      credential_pattern=$(jq -r '.retrieval.pattern // empty' <<<"$credential")
      credential_timeout=$(jq -r '.retrieval.timeout_seconds // 180' <<<"$credential")
      [[ $credential_path == /* && $credential_path != *[[:space:]]* ]] \
        || die "$(translate "Invalid credential file path:") $credential_path"
      oci_log "Reading the credential of ${credential_label} from ${credential_path}"
      if credential_value=$(capture_container_file_credential \
            "$VMID" "$credential_path" "$credential_pattern" "$credential_timeout"); then
        CREDENTIALS=$(jq -c --arg label "$credential_label" --arg password "$credential_value" \
          'map(if .label == $label and .retrieval.method? == "container-file" then .password = $password else . end)' \
          <<<"$CREDENTIALS")
        PASSWORD_STATE=retrieved
      else
        CREDENTIALS=$(jq -c --arg label "$credential_label" \
          'map(if .label == $label and .retrieval.method? == "container-file" then
             . + {retrieval_error: "The credential could not be read from the container"} else . end)' \
          <<<"$CREDENTIALS")
        oci_log "The credential of ${credential_label} could not be read"
        PASSWORD_STATE=missing
      fi
    done < <(jq -r '.[] | select(.retrieval.method? == "container-file") | @base64' <<<"$CREDENTIALS")
  fi
  detect_container_ipv4 "$(translate "Container started")"
  case "$PASSWORD_STATE" in
    retrieved) msg_ok "$(translate "Temporary password retrieved")" ;;
    missing) msg_warn "$(translate "The temporary password could not be retrieved.")" ;;
  esac
else
  IP=""
  msg_ok "$(translate "Container configured (not started):") CT $VMID"
fi

if [[ -z $IP && $IPV4 != dhcp ]]; then
  IP=${IPV4%%/*}
fi

POST_START_CONFIGURATION_COUNT=$(jq '.post_start_configurations? // [] | length' "$DEPLOYMENT_FILE")
if (( POST_START_CONFIGURATION_COUNT > 0 )); then
  (( START_AFTER == 1 )) \
    || die "$(translate "The selected configuration needs to start the LXC during the installation")"
  while IFS= read -r CONFIGURATION_ENCODED; do
    [[ -n $CONFIGURATION_ENCODED ]] || continue
    apply_post_start_configuration "$(printf '%s' "$CONFIGURATION_ENCODED" | base64 -d)"
  done < <(jq -r '.post_start_configurations[]? | @base64' "$DEPLOYMENT_FILE")
  msg_info "$(translate "Waiting for the network address...")"
  detect_container_ipv4
  if [[ -z $IP && $IPV4 != dhcp ]]; then
    IP=${IPV4%%/*}
  fi
fi

if [[ $START_AFTER == 1 && $HAS_STARTUP_HEALTHCHECK == 1 ]]; then
  HC_SCHEME=$(jq -er '.scheme' <<<"$STARTUP_HEALTHCHECK")
  HC_PORT=$(jq -er '.port' <<<"$STARTUP_HEALTHCHECK")
  HC_PATH=$(jq -er '.path' <<<"$STARTUP_HEALTHCHECK")
  HC_TIMEOUT=$(jq -er '.timeout_seconds' <<<"$STARTUP_HEALTHCHECK")
  HC_REQUEST_TIMEOUT=$(jq -er '.request_timeout_seconds' <<<"$STARTUP_HEALTHCHECK")
  HC_STABILITY=$(jq -r '.stability_seconds // 0' <<<"$STARTUP_HEALTHCHECK")
  HC_VERIFY_TLS=$(jq -r '.verify_tls' <<<"$STARTUP_HEALTHCHECK")
  [[ $HC_SCHEME == http || $HC_SCHEME == https ]] || die "$(translate "Invalid healthcheck scheme")"
  [[ $HC_PORT =~ ^[0-9]+$ && $HC_PORT -ge 1 && $HC_PORT -le 65535 ]] \
    || die "$(translate "Invalid healthcheck port")"
  [[ $HC_PATH == /* && $HC_PATH != *[[:space:]]* ]] || die "$(translate "Invalid healthcheck path")"
  [[ $HC_TIMEOUT =~ ^[0-9]+$ && $HC_TIMEOUT -gt 0 ]] || die "$(translate "Invalid healthcheck timeout")"
  [[ $HC_REQUEST_TIMEOUT =~ ^[0-9]+$ && $HC_REQUEST_TIMEOUT -gt 0 ]] \
    || die "$(translate "Invalid healthcheck request timeout")"
  [[ $HC_STABILITY =~ ^[0-9]+$ ]] || die "$(translate "Invalid healthcheck stability period")"
  (( HC_STABILITY < HC_TIMEOUT )) \
    || die "$(translate "The stability period must be shorter than the healthcheck timeout")"
  [[ -n $IP ]] || die "$(translate "The healthcheck cannot run without an IP address")"
  HC_URL="${HC_SCHEME}://${IP}:${HC_PORT}${HC_PATH}"
  HC_ANY_STATUS=$(jq -r '.accept_any_status // false' <<<"$STARTUP_HEALTHCHECK")
  if [[ $HC_ANY_STATUS == true ]]; then
    CURL_ARGS=(-sS --noproxy '*' -o /dev/null -w '%{http_code}' --max-time "$HC_REQUEST_TIMEOUT")
  else
    CURL_ARGS=(-fsS --noproxy '*' -o /dev/null --max-time "$HC_REQUEST_TIMEOUT")
  fi
  [[ $HC_VERIFY_TLS == true ]] || CURL_ARGS+=(-k)
  HC_OK=0
  HC_ELAPSED=0
  HC_STABLE_ELAPSED=0
  HC_STABLE_SINCE=0
  oci_log "Waiting for the service: $HC_URL"
  msg_info "$(translate "Waiting for the application to respond...")"
  while (( HC_ELAPSED < HC_TIMEOUT )); do
    if ! container_is_running; then
      oci_log "The container stopped during its first start. Last console messages:"
      [[ -s $RUNTIME_CONSOLE_LOG ]] && tr -d '\r' <"$RUNTIME_CONSOLE_LOG" | tail -n 100 >>"${OCI_LOG:-/dev/stderr}"
      die "$(translate "The container stopped before the application responded:") CT $VMID"
    fi
    if healthcheck_probe; then
      if (( HC_STABILITY == 0 )); then
        HC_OK=1
        break
      fi
      HC_NOW=$(date +%s)
      if (( HC_STABLE_SINCE == 0 )); then
        HC_STABLE_SINCE=$HC_NOW
      fi
      HC_STABLE_ELAPSED=$((HC_NOW - HC_STABLE_SINCE))
      if (( HC_STABLE_ELAPSED >= HC_STABILITY )); then
        HC_OK=1
        break
      fi
    else
      HC_STABLE_ELAPSED=0
      HC_STABLE_SINCE=0
    fi
    sleep 2
    HC_ELAPSED=$((HC_ELAPSED + 2))
    if (( HC_STABLE_ELAPSED > 0 )); then
      msg_progress "$(translate "Application responding; checking its stability...") ${HC_STABLE_ELAPSED}/${HC_STABILITY} s"
    else
      msg_progress "$(translate "Waiting for the application to respond...") ${HC_ELAPSED}/${HC_TIMEOUT} s"
    fi
  done
  if [[ $HC_OK != 1 ]]; then
    oci_log "The service did not pass the healthcheck. Last console messages:"
    [[ -s $RUNTIME_CONSOLE_LOG ]] && tr -d '\r' <"$RUNTIME_CONSOLE_LOG" | tail -n 100 >>"${OCI_LOG:-/dev/stderr}"
    die "$(translate "The application did not respond in time:") $HC_URL"
  fi
  msg_ok "$(translate "Application responding:") $HC_URL"
fi

# Applications without a web address: the container must keep running.
if [[ $START_AFTER == 1 && $HAS_RUNNING_CHECK == 1 ]]; then
  RC_STABILITY=$(jq -r '.stability_seconds // 20' <<<"$STARTUP_HEALTHCHECK")
  [[ $RC_STABILITY =~ ^[0-9]+$ && $RC_STABILITY -le 600 ]] || die "$(translate "Invalid healthcheck stability period")"
  msg_info "$(translate "Checking that the container keeps running...")"
  RC_START=$(date +%s)
  while (( $(date +%s) - RC_START < RC_STABILITY )); do
    if ! container_is_running; then
      oci_log "The container stopped after starting. Last console messages:"
      [[ -s $RUNTIME_CONSOLE_LOG ]] && tr -d '\r' <"$RUNTIME_CONSOLE_LOG" | tail -n 100 >>"${OCI_LOG:-/dev/stderr}"
      die "$(translate "The container stopped after starting:") CT $VMID"
    fi
    sleep 2
  done
  msg_ok "$(translate "Container running steadily")"
fi

HAOS_URLS=""
if [[ $START_AFTER == 1 && $HAOS_HEALTHCHECK != 0 ]]; then
  PRESERVE_FAILED_CT=1
  [[ -n $IP ]] || die "$(translate "Home Assistant OS cannot be checked without an IP address")"
  # The checker rewrites this line with its own progress on stderr.
  msg_progress "$(translate "Waiting for Home Assistant OS...")"
  HAOS_URLS=$(python3 "${SCRIPT_DIR}/haos_healthcheck.py" --vmid "$VMID" --ip "$IP" --timeout "$HAOS_HEALTHCHECK") \
    || die "$(translate "Home Assistant OS did not pass the Supervisor, Core and Observer checks")"
  msg_ok "$(translate "Home Assistant OS ready: Supervisor, Core and Observer running")"
fi

cleanup_runtime_console_log

UPDATED_DESCRIPTION=$(python3 "${SCRIPT_DIR}/oci_description.py" --template "$TEMPLATE_FILE" \
  --digest "$DIGEST" --instance "$INSTANCE_ID" --ip "$IP") \
  || die "Could not prepare the OCI notes"
oci_quiet pct set "$VMID" --description "$UPDATED_DESCRIPTION" \
  || die "Could not write the OCI notes in Proxmox"

URLS=$(jq -c --arg ip "$IP" '
  if $ip == "" then []
  elif (.first_run.endpoints? // []) | length > 0 then
    [.first_run.endpoints[] | {
      label: .label,
      url: (.scheme + "://" + $ip + ":" + (.port | tostring) + .path)
    }]
  elif .catalog_ui.launch.port != null then
    [{
      label: "Web UI",
      url: (.catalog_ui.launch.scheme + "://" + $ip + ":" + (.catalog_ui.launch.port | tostring) + .catalog_ui.launch.path)
    }]
  else [] end
' "$TEMPLATE_FILE")
if [[ -n $HAOS_URLS ]]; then
  URLS=$HAOS_URLS
elif [[ $HAOS_HEALTHCHECK != 0 ]]; then
  URLS='[]'
  msg_info2 "$(translate "Home Assistant OS was not started: its addresses will be known once Core is running.")"
fi
INSTALL_COMPLETE=1
if [[ $(jq -r '.stack_managed // false' "$DEPLOYMENT_FILE") == true ]]; then
  msg_ok "$(translate "Container prepared for the stack:") CT $VMID ($HOSTNAME)"
elif [[ $START_AFTER == 1 ]]; then
  check_native_device_permissions
fi
if [[ -z ${PROXMENUX_OCI_TRANSACTION:-} ]] && ! oci_quiet python3 "${SCRIPT_DIR}/oci_instances.py" complete "$VMID" \
  --archive "$ARCHIVE_PATH" --digest "$DIGEST"; then
  msg_warn "$(translate "Container installed, but without a verifiable record for future updates.")"
fi
COMPLETION_NOTES=$(jq -c '.proxmox.installer_profile.completion_notes // []' "$TEMPLATE_FILE")
RESULT=$(jq -cn \
  --arg app_id "$APP_ID" \
  --arg image "$IMAGE_REF" \
  --arg digest "$DIGEST" \
  --arg architecture "$ARCH" \
  --arg image_version "$IMAGE_VERSION" \
  --arg image_created "$CREATED" \
  --arg ip "$IP" \
  --argjson urls "$URLS" \
  --argjson credentials "$CREDENTIALS" \
  --argjson completion_notes "$COMPLETION_NOTES" \
  --argjson vmid "$VMID" \
  --arg log "${OCI_LOG:-}" \
  '{app_id:$app_id,vmid:$vmid,image:$image,digest:$digest,architecture:$architecture,image_version:$image_version,image_created:$image_created,ip:$ip,urls:$urls,credentials:$credentials,completion_notes:$completion_notes,log:$log}')
printf 'PROXMENUX_RESULT=%s\n' "$(printf '%s' "$RESULT" | base64 | tr -d '\n')"
