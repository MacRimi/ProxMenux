#!/usr/bin/env bash
set -Eeuo pipefail

TEMPLATE_FILE=${1:?template JSON required}
DEPLOYMENT_FILE=${2:?deployment JSON required}
DRY_RUN=${3:-0}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/oci_ui.sh"
VERIFY_OCI_ARCHIVE="${SCRIPT_DIR}/verify_oci_archive.py"
ALLOCATE_PRIVATE_NETWORK="${SCRIPT_DIR}/allocate_private_network.py"
STACK_DEPENDENCY_HOOK="${SCRIPT_DIR}/stack_dependency_hook.sh"

die() {
  stop_spinner
  msg_error "$*"
  if [[ -n ${OCI_LOG:-} && -s ${OCI_LOG:-} ]]; then
    oci_log_tail 12 >&2
    printf '    %s %s\n' "$(translate "Full log:")" "$OCI_LOG" >&2
  fi
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$(translate "Missing required command:") $1"
}

jqr() {
  jq -er "$1" "$DEPLOYMENT_FILE"
}

set_runtime_env() {
  local id=$1 key=$2 value=$3 config="/etc/pve/lxc/${1}.conf"
  sed -i -E "/^lxc\.environment\.runtime: ${key}=/d" "$config"
  printf 'lxc.environment.runtime: %s=%s\n' "$key" "$value" >>"$config"
}

unset_runtime_env() {
  local id=$1 key=$2 config="/etc/pve/lxc/${1}.conf"
  sed -i -E "/^lxc\.environment\.runtime: ${key}=/d" "$config"
}

set_lxc_directive() {
  local id=$1 key=$2 value=$3 config="/etc/pve/lxc/${1}.conf" escaped_key
  escaped_key=${key//./\.}
  sed -i -E "/^${escaped_key}:/d" "$config"
  printf '%s: %s\n' "$key" "$value" >>"$config"
}

created_ids=()
INSTALL_COMPLETE=0
PRIVATE_BRIDGE_CREATED=0
LIFECYCLE_CONFIG_PATH=""
UNEXPECTED_FAILURE=0
rollback() {
  local status=$? index id
  stop_spinner
  if (( status != 0 && UNEXPECTED_FAILURE == 1 )); then
    msg_error "$(translate "The installation stopped because of an unexpected error")"
    if [[ -n ${OCI_LOG:-} && -s ${OCI_LOG:-} ]]; then
      oci_log_tail 12 >&2
      printf '    %s %s\n' "$(translate "Full log:")" "$OCI_LOG" >&2
    fi
  fi
  if (( status != 0 && INSTALL_COMPLETE == 0 )); then
    if declare -F oci_native_failed >/dev/null; then oci_native_failed; fi
    if (( ${#created_ids[@]} > 0 || PRIVATE_BRIDGE_CREATED == 1 )); then
      msg_info "$(translate "Removing the incomplete stack...")"
    fi
    for ((index=${#created_ids[@]}-1; index>=0; index--)); do
      id=${created_ids[index]}
      pct stop "$id" --skiplock 1 >/dev/null 2>&1 || true
      pct destroy "$id" --force 1 --purge 1 >/dev/null 2>&1 \
        || pct destroy "$id" --purge 1 >/dev/null 2>&1 \
        || true
    done
    if (( PRIVATE_BRIDGE_CREATED == 1 )); then
      oci_log "Removing the private bridge created by this installation"
      ip link delete "$PRIVATE_BRIDGE" type bridge >/dev/null 2>&1 || true
      pvesh delete "/nodes/${NODE}/network/${PRIVATE_BRIDGE}" >/dev/null 2>&1 || true
    fi
    [[ -z $LIFECYCLE_CONFIG_PATH ]] || rm -f "$LIFECYCLE_CONFIG_PATH"
    if (( ${#created_ids[@]} > 0 || PRIVATE_BRIDGE_CREATED == 1 )); then
      msg_ok "$(translate "Incomplete stack removed")"
    fi
  fi
  exit "$status"
}
trap rollback EXIT
trap 'UNEXPECTED_FAILURE=1; oci_log "Command failed at line $LINENO (${FUNCNAME[0]:-main})"' ERR

[[ $EUID -eq 0 ]] || die "$(translate "The installer must run as root on Proxmox VE")"
oci_log_init "$(jq -r '.stack_name // "immich"' "$DEPLOYMENT_FILE" 2>/dev/null || printf immich)"
for command in pct qm pvesh pvesm skopeo jq openssl python3 curl ip stat dpkg base64 mktemp flock; do
  require_command "$command"
done
[[ -r $VERIFY_OCI_ARCHIVE ]] || die "$(translate "The OCI archive verifier was not found")"
[[ -r $ALLOCATE_PRIVATE_NETWORK ]] || die "$(translate "The private network allocator was not found")"
[[ -r $STACK_DEPENDENCY_HOOK ]] || die "$(translate "The stack startup hook was not found")"

ML_ACCELERATION=$(jq -er '.machine_learning.acceleration // "cpu"' "$DEPLOYMENT_FILE")
source "$SCRIPT_DIR/oci_nvidia_setup.sh"
source "$SCRIPT_DIR/oci_immich_ml.sh"
validate_immich_ml_profile

msg_info "$(translate "Reserving a private network...")"
exec 9>/run/lock/proxmenux-private-network.lock
flock 9
oci_quiet python3 "$ALLOCATE_PRIVATE_NETWORK" "$DEPLOYMENT_FILE" \
  || die "$(translate "Could not reserve a private network for the stack")"

STACK_NAME=$(jqr '.stack_name')
[[ $STACK_NAME =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || die "$(translate "Invalid stack name")"
BASE_VMID=$(jq -r '.base_vmid // empty' "$DEPLOYMENT_FILE")
TEMPLATE_STORAGE=$(jqr '.template_storage')
ROOTFS_STORAGE=$(jqr '.rootfs_storage')
DATABASE_STORAGE=$(jqr '.database_storage')
DATABASE_SIZE=$(jqr '.database_size_gb')
MEDIA_MODE=$(jqr '.media.mode')
MEDIA_STORAGE=$(jq -r '.media.storage // empty' "$DEPLOYMENT_FILE")
MEDIA_SIZE=$(jq -r '.media.size_gb // empty' "$DEPLOYMENT_FILE")
MEDIA_ROOT=$(jq -r '.media.host_path // empty' "$DEPLOYMENT_FILE")
TIMEZONE=$(jqr '.timezone')
ONBOOT=$(jqr '.onboot | if . then 1 else 0 end')
START_AFTER=$(jqr '.start_after_create | if . then 1 else 0 end')
FRONTEND_BRIDGE=$(jqr '.network.frontend_bridge')
FRONTEND_IPV4=$(jq -r '.network.frontend_ipv4 // "dhcp"' "$DEPLOYMENT_FILE")
ML_FRONTEND_IPV4=$(jq -r '.network.machine_learning_frontend_ipv4 // "dhcp"' "$DEPLOYMENT_FILE")
FRONTEND_GATEWAY=$(jq -r '.network.frontend_gateway // empty' "$DEPLOYMENT_FILE")
oci_access_net "$FRONTEND_IPV4" "$FRONTEND_GATEWAY" \
  || die "$(translate "Invalid access address:") $FRONTEND_IPV4 $FRONTEND_GATEWAY"
FRONTEND_NET=$OCI_ACCESS_NET
oci_access_net "$ML_FRONTEND_IPV4" "$FRONTEND_GATEWAY" \
  || die "$(translate "Invalid access address:") $ML_FRONTEND_IPV4 $FRONTEND_GATEWAY"
ML_FRONTEND_NET=$OCI_ACCESS_NET
PRIVATE_BRIDGE=$(jqr '.network.private_bridge')
PRIVATE_SUBNET=$(jqr '.network.private_subnet')
PRIVATE_HOST_ADDRESS=$(jqr '.network.private_host_address')
SERVER_ADDRESS=$(jqr '.network.server_address')
ML_ADDRESS=$(jqr '.network.machine_learning_address')
DB_ADDRESS=$(jqr '.network.database_address')
VALKEY_ADDRESS=$(jqr '.network.valkey_address')
SERVER_IP=${SERVER_ADDRESS%/*}
ML_IP=${ML_ADDRESS%/*}
DB_IP=${DB_ADDRESS%/*}
VALKEY_IP=${VALKEY_ADDRESS%/*}
VIDEO_ACCELERATION=$(jqr '.video_transcoding.acceleration')
RENDER_DEVICE=$(jq -r '.video_transcoding.render_device // empty' "$DEPLOYMENT_FILE")
VAAPI_DRIVER=$(jqr '.video_transcoding.driver')
MODEL_CACHE_SIZE=$(jqr '.machine_learning.model_cache_size_gb')

[[ $DATABASE_SIZE =~ ^[0-9]+$ ]] && (( DATABASE_SIZE >= 8 )) \
  || die "$(translate "The PostgreSQL volume needs at least 8 GB")"
case "$MEDIA_MODE" in
  managed-volume)
    [[ -n $MEDIA_STORAGE && $MEDIA_SIZE =~ ^[0-9]+$ ]] && (( MEDIA_SIZE >= 8 )) \
      || die "$(translate "Invalid media volume")"
    ;;
  host-bind)
    [[ $MEDIA_ROOT == /* && $MEDIA_ROOT != *","* && $MEDIA_ROOT != *$'\n'* ]] \
      || die "$(translate "Invalid media path")"
    ;;
  *) die "$(translate "Unsupported media storage mode:") $MEDIA_MODE" ;;
esac
[[ $PRIVATE_BRIDGE =~ ^vmbr[0-9]+$ ]] || die "$(translate "Invalid private bridge")"
[[ $PRIVATE_SUBNET =~ ^10\.77\.[0-9]{1,3}\.0/24$ ]] || die "$(translate "Invalid private network")"

vmid_block_free() {
  local candidate=$1 offset
  for offset in 0 1 2 3; do
    pct config "$((candidate + offset))" >/dev/null 2>&1 && return 1
    qm config "$((candidate + offset))" >/dev/null 2>&1 && return 1
  done
  return 0
}

if [[ -z $BASE_VMID ]]; then
  BASE_VMID=$(pvesh get /cluster/nextid)
  while ! vmid_block_free "$BASE_VMID"; do
    BASE_VMID=$((BASE_VMID + 1))
  done
fi
[[ $BASE_VMID =~ ^[0-9]+$ ]] || die "$(translate "Invalid base VMID")"
vmid_block_free "$BASE_VMID" || die "$(translate "These VMIDs are not free:") ${BASE_VMID}-$((BASE_VMID + 3))"

SERVER_ID=$BASE_VMID
ML_ID=$((BASE_VMID + 1))
DB_ID=$((BASE_VMID + 2))
VALKEY_ID=$((BASE_VMID + 3))

oci_log "Stack: $STACK_NAME; VMIDs: server=$SERVER_ID, machine-learning=$ML_ID, PostgreSQL=$DB_ID, Valkey=$VALKEY_ID"
oci_log "Private network: $PRIVATE_SUBNET on $PRIVATE_BRIDGE"

if [[ $DRY_RUN == 1 ]]; then
  msg_info2 "$(translate "Stack:") $STACK_NAME · CT ${SERVER_ID}-${VALKEY_ID}"
  msg_info2 "$(translate "Private network:") $PRIVATE_BRIDGE ($PRIVATE_SUBNET)"
  msg_ok "$(translate "Dry run completed; no containers were created.")"
  exit 0
fi

NODE=$(hostname)
if ! pvesh get "/nodes/${NODE}/network/${PRIVATE_BRIDGE}" >/dev/null 2>&1; then
  oci_log "Creating the persistent configuration for $PRIVATE_BRIDGE"
  oci_quiet pvesh create "/nodes/${NODE}/network" --iface "$PRIVATE_BRIDGE" --type bridge \
    --autostart 1 --cidr "$PRIVATE_HOST_ADDRESS"
  PRIVATE_BRIDGE_CREATED=1
fi
if ! ip link show "$PRIVATE_BRIDGE" >/dev/null 2>&1; then
  oci_log "Activating the private bridge $PRIVATE_BRIDGE"
  oci_quiet ip link add name "$PRIVATE_BRIDGE" type bridge
  oci_quiet ip address add "$PRIVATE_HOST_ADDRESS" dev "$PRIVATE_BRIDGE"
  oci_quiet ip link set "$PRIVATE_BRIDGE" up
fi
ip -4 address show dev "$PRIVATE_BRIDGE" | grep -Fq "${PRIVATE_HOST_ADDRESS%/*}/" \
  || die "$(translate "The private bridge does not have the expected address:") $PRIVATE_BRIDGE ($PRIVATE_HOST_ADDRESS)"

for address in "$SERVER_ADDRESS" "$ML_ADDRESS" "$DB_ADDRESS" "$VALKEY_ADDRESS"; do
  if grep -RqsF "ip=${address}" /etc/pve/lxc/*.conf 2>/dev/null; then
    die "$(translate "The private address is already assigned to another container:") ${address%/*}"
  fi
done
flock -u 9
msg_ok "$(translate "Private network:") $PRIVATE_BRIDGE ($PRIVATE_SUBNET)"

ARCH=$(dpkg --print-architecture)
case "$ARCH" in amd64|arm64) ;; *) die "$(translate "Unsupported architecture:") $ARCH" ;; esac

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
  local label=$1 image=$2 manifest_file error_file pid elapsed=0 status=0
  manifest_file=$(mktemp /tmp/proxmenux-oci-inspect.XXXXXX)
  error_file="${manifest_file}.err"
  oci_log "Querying the OCI registry for ${label}: ${image}"
  skopeo inspect --no-tags --override-os linux --override-arch "$ARCH" \
    "docker://${image}" >"$manifest_file" 2>"$error_file" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    sleep 2
    elapsed=$((elapsed + 2))
  done
  wait "$pid" || status=$?
  if (( status != 0 )); then
    cat "$error_file" >>"$OCI_LOG"
    rm -f "$manifest_file" "$error_file"
    return "$status"
  fi
  oci_log "Manifest for ${label} resolved in ${elapsed}s"
  cat "$manifest_file"
  rm -f "$manifest_file" "$error_file"
}

ensure_image() {
  local key=$1 image=$2 transport_image inspect digest short archive_name archive_volume archive_path
  local partial log pid bytes elapsed status process_bytes pull_name attempt
  msg_info "$(translate "Checking the image in the registry...")"
  oci_log "Resolving ${key}: ${image}"
  transport_image=$(skopeo_transport_reference "$image")
  if [[ $transport_image != "$image" ]]; then
    oci_log "Digest-pinned reference in skopeo format: ${transport_image}"
  fi
  inspect=$(resolve_image_manifest "$key" "$transport_image") \
    || die "$(translate "Could not resolve the OCI manifest:") $image"
  digest=$(jq -er '.Digest' <<<"$inspect")
  oci_log "Selected digest for ${key}: ${digest}"
  short=${digest#sha256:}
  short=${short:0:16}
  archive_name="image-immich-${key}_${ARCH}_${short}.tar"
  archive_volume="${TEMPLATE_STORAGE}:vztmpl/${archive_name}"
  archive_path=$(pvesm path "$archive_volume")
  mkdir -p "$(dirname "$archive_path")"
  if [[ -s $archive_path ]]; then
    msg_info "$(translate "Verifying the image integrity...")"
  fi
  if [[ -s $archive_path ]] && oci_quiet python3 "$VERIFY_OCI_ARCHIVE" "$archive_path"; then
    oci_log "Reusing ${archive_volume}"
  else
    rm -f "$archive_path"
    # A download can come back complete yet damaged when the connection drops
    # and the transfer resumes; the integrity check catches it, and a second
    # download is what repairs it.
    for attempt in 1 2; do
      partial="${archive_path}.partial.$$"
      log="${partial}.log"
      oci_log "Downloading ${image} by digest ${digest} (attempt ${attempt}/2)"
      pull_name=${transport_image%@sha256:*}
      [[ ${pull_name##*/} != *:* ]] || pull_name=${pull_name%:*}
      skopeo copy --override-os linux --override-arch "$ARCH" --retry-times 3 \
        --retry-delay 5s --image-parallel-copies 1 \
        "docker://${pull_name}@${digest}" "oci-archive:${partial}:image-immich-${key}" >"$log" 2>&1 &
      pid=$!
      elapsed=0
      while kill -0 "$pid" 2>/dev/null; do
        bytes=$(stat -c %s "$partial" 2>/dev/null || printf 0)
        process_bytes=$(awk '$1 == "rchar:" { print $2 }' "/proc/${pid}/io" 2>/dev/null || printf 0)
        process_bytes=${process_bytes:-0}
        (( process_bytes <= bytes )) || bytes=$process_bytes
        msg_progress "$(translate "Downloading the image:") ${key} · $((bytes / 1048576)) MiB · ${elapsed}s"
        sleep 2
        elapsed=$((elapsed + 2))
      done
      status=0
      wait "$pid" || status=$?
      cat "$log" >>"$OCI_LOG"
      rm -f "$log"
      if (( status != 0 )); then
        rm -f "$partial"
        (( attempt < 2 )) || die "$(translate "Image download failed:") $image"
        msg_warn "$(translate "The image download did not complete correctly; downloading it again...")"
        continue
      fi
      msg_info "$(translate "Verifying the image integrity...")"
      if ! oci_quiet python3 "$VERIFY_OCI_ARCHIVE" "$partial"; then
        rm -f "$partial"
        (( attempt < 2 )) || die "$(translate "The downloaded image is corrupt:") $image"
        msg_warn "$(translate "The image download did not complete correctly; downloading it again...")"
        continue
      fi
      mv -f "$partial" "$archive_path"
      break
    done
  fi
  msg_ok "$(translate "Image:") $image"
  RESOLVED_ARCHIVE=$archive_volume
  RESOLVED_DIGEST=$digest
}

SERVER_IMAGE=$(jq -er '.container_contract.image.reference' "$TEMPLATE_FILE")
ML_IMAGE=$(jq -er --arg profile "$ML_ACCELERATION" '.proxmox.application_options.machine_learning.profile_images[$profile]' "$TEMPLATE_FILE")
DB_IMAGE=$(jq -er '.compose_stack.services[] | select(.name == "database") | .image' "$TEMPLATE_FILE")
VALKEY_IMAGE=$(jq -er '.compose_stack.services[] | select(.name == "redis") | .image' "$TEMPLATE_FILE")

ensure_image server "$SERVER_IMAGE"; SERVER_ARCHIVE=$RESOLVED_ARCHIVE; SERVER_DIGEST=$RESOLVED_DIGEST
ensure_image machine-learning "$ML_IMAGE"; ML_ARCHIVE=$RESOLVED_ARCHIVE
ensure_image postgres "$DB_IMAGE"; DB_ARCHIVE=$RESOLVED_ARCHIVE
ensure_image valkey "$VALKEY_IMAGE"; VALKEY_ARCHIVE=$RESOLVED_ARCHIVE

source "$SCRIPT_DIR/oci_native_stack.sh"
oci_native_begin "$SERVER_ID" \
  --member server "$SERVER_ID" "$SERVER_IMAGE" "$SERVER_ARCHIVE" \
  --member machine-learning "$ML_ID" "$ML_IMAGE" "$ML_ARCHIVE" \
  --member database "$DB_ID" "$DB_IMAGE" "$DB_ARCHIVE" \
  --member valkey "$VALKEY_ID" "$VALKEY_IMAGE" "$VALKEY_ARCHIVE"

DB_PASSWORD=$(openssl rand -hex 24)
if [[ $MEDIA_MODE == host-bind ]]; then
  install -d -m 0750 -o 100000 -g 100000 "$MEDIA_ROOT"
  SERVER_MEDIA_MOUNT="${MEDIA_ROOT},mp=/data,backup=0"
else
  SERVER_MEDIA_MOUNT="${MEDIA_STORAGE}:${MEDIA_SIZE},mp=/data,backup=1"
fi
TAGS="media;oci;proxmenux"

msg_info "$(translate "Creating the container...")"
oci_quiet pct create "$DB_ID" "$DB_ARCHIVE" --rootfs "${ROOTFS_STORAGE}:8" \
  --mp0 "${DATABASE_STORAGE}:${DATABASE_SIZE},mp=/var/lib/postgresql/data,backup=1" \
  --hostname "${STACK_NAME}-db" --cores 2 --memory 2048 --swap 512 \
  --net0 "name=eth0,bridge=${PRIVATE_BRIDGE},firewall=1,host-managed=1,ip=${DB_ADDRESS},type=veth" \
  --unprivileged 1 --features nesting=1 --cmode console --onboot "$ONBOOT" \
  --startup order=10,up=10,down=30 --tags "$TAGS" \
  --description 'Immich PostgreSQL VectorChord native OCI'
created_ids+=("$DB_ID")
oci_quiet pct set "$DB_ID" --entrypoint "/usr/local/bin/immich-docker-entrypoint.sh postgres -c config_file=/etc/postgresql/postgresql.conf -c listen_addresses=127.0.0.1,${DB_IP}"
set_lxc_directive "$DB_ID" lxc.init.cwd /
set_lxc_directive "$DB_ID" lxc.signal.halt SIGINT
set_runtime_env "$DB_ID" POSTGRES_USER postgres
set_runtime_env "$DB_ID" POSTGRES_DB immich
set_runtime_env "$DB_ID" POSTGRES_INITDB_ARGS --data-checksums
set_runtime_env "$DB_ID" PGDATA /var/lib/postgresql/data/pgdata
set_runtime_env "$DB_ID" DB_STORAGE_TYPE SSD
set_runtime_env "$DB_ID" POSTGRES_PASSWORD "$DB_PASSWORD"
oci_quiet pct mount "$DB_ID"
DB_ROOT="/var/lib/lxc/${DB_ID}/rootfs"
POSTGRES_UID=$(awk -F: '$1 == "postgres" {print $3}' "$DB_ROOT/etc/passwd")
POSTGRES_GID=$(awk -F: '$1 == "postgres" {print $4}' "$DB_ROOT/etc/passwd")
[[ -n $POSTGRES_UID && -n $POSTGRES_GID ]] || die "$(translate "The postgres user was not found in the image")"
rm -rf "$DB_ROOT/var/lib/postgresql/data/lost+found"
install -d -m 0700 -o "$((100000 + POSTGRES_UID))" -g "$((100000 + POSTGRES_GID))" \
  "$DB_ROOT/var/lib/postgresql/data/pgdata"
oci_quiet pct unmount "$DB_ID"
msg_ok "$(translate "Container created:") CT $DB_ID (PostgreSQL)"

msg_info "$(translate "Creating the container...")"
oci_quiet pct create "$VALKEY_ID" "$VALKEY_ARCHIVE" --rootfs "${ROOTFS_STORAGE}:4" \
  --mp0 "${ROOTFS_STORAGE}:4,mp=/data,backup=1" \
  --hostname "${STACK_NAME}-valkey" --cores 1 --memory 512 --swap 256 \
  --net0 "name=eth0,bridge=${PRIVATE_BRIDGE},firewall=1,host-managed=1,ip=${VALKEY_ADDRESS},type=veth" \
  --unprivileged 1 --features nesting=1 --cmode console --onboot "$ONBOOT" \
  --startup order=20,up=5,down=15 --tags "$TAGS" --description 'Immich Valkey native OCI'
created_ids+=("$VALKEY_ID")
oci_quiet pct mount "$VALKEY_ID"
VALKEY_FACTORY_DIR="/var/lib/lxc/${VALKEY_ID}/rootfs/data/lost+found"
# Only remove the empty directory created by formatting this new managed disk.
if [[ -d $VALKEY_FACTORY_DIR && ! -L $VALKEY_FACTORY_DIR ]]; then
  [[ $(stat -c '%i:%u:%g:%a' "$VALKEY_FACTORY_DIR") == 11:0:0:700 ]] \
    || die "$(translate "Unexpected formatting directory in the new Valkey volume")"
  rmdir "$VALKEY_FACTORY_DIR" 2>>"$OCI_LOG" || die "$(translate "The new Valkey volume contains unexpected data")"
fi
oci_quiet pct unmount "$VALKEY_ID"
oci_quiet pct set "$VALKEY_ID" --entrypoint 'docker-entrypoint.sh valkey-server'
set_lxc_directive "$VALKEY_ID" lxc.init.cwd /data
set_lxc_directive "$VALKEY_ID" lxc.signal.halt SIGTERM
msg_ok "$(translate "Container created:") CT $VALKEY_ID (Valkey)"

msg_info "$(translate "Creating the container...")"
oci_quiet pct create "$ML_ID" "$ML_ARCHIVE" --rootfs "${ROOTFS_STORAGE}:12" \
  --mp0 "${ROOTFS_STORAGE}:${MODEL_CACHE_SIZE},mp=/cache,backup=1" \
  --hostname "${STACK_NAME}-ml" "${ML_CPU_ARGS[@]}" --memory "$ML_MEMORY" --swap "$ML_SWAP" \
  --net0 "name=eth0,bridge=${FRONTEND_BRIDGE},firewall=1,host-managed=1,${ML_FRONTEND_NET},type=veth" \
  --net1 "name=eth1,bridge=${PRIVATE_BRIDGE},firewall=1,host-managed=1,ip=${ML_ADDRESS},type=veth" \
  --unprivileged 1 --features nesting=1 --cmode console --onboot "$ONBOOT" \
  --startup order=30,up=10,down=30 --tags "$TAGS" --description "Immich machine learning ${ML_ACCELERATION} native OCI"
created_ids+=("$ML_ID")
unset_runtime_env "$ML_ID" LD_PRELOAD
oci_quiet pct set "$ML_ID" --entrypoint 'env LD_PRELOAD=/usr/lib/libmimalloc.so.2 tini -- python -m immich_ml'
set_lxc_directive "$ML_ID" lxc.init.cwd /usr/src
set_lxc_directive "$ML_ID" lxc.signal.halt SIGTERM
set_runtime_env "$ML_ID" IMMICH_HOST "$ML_IP"
set_runtime_env "$ML_ID" IMMICH_PORT 3003
set_runtime_env "$ML_ID" MACHINE_LEARNING_CACHE_FOLDER /cache
set_runtime_env "$ML_ID" TRANSFORMERS_CACHE /cache
set_runtime_env "$ML_ID" MACHINE_LEARNING_MODEL_INTRA_OP_THREADS 2
set_runtime_env "$ML_ID" MACHINE_LEARNING_MODEL_INTER_OP_THREADS 1
configure_immich_ml_gpu
oci_quiet pct mount "$ML_ID"
ML_ROOT="/var/lib/lxc/${ML_ID}/rootfs"
rm -rf "$ML_ROOT/cache/lost+found"
chown 100000:100000 "$ML_ROOT/cache"
chmod 0755 "$ML_ROOT/cache"
oci_quiet pct unmount "$ML_ID"
msg_ok "$(translate "Container created:") CT $ML_ID ($(translate "Machine learning"))"

SERVER_DEVICE_ARGS=()
if [[ $VIDEO_ACCELERATION == vaapi ]]; then
  [[ -c $RENDER_DEVICE ]] || die "$(translate "The VA-API device does not exist:") $RENDER_DEVICE"
  RENDER_GID=$(stat -c %g "$RENDER_DEVICE")
  SERVER_DEVICE_ARGS+=(--dev0 "path=${RENDER_DEVICE},gid=${RENDER_GID},mode=0660")
fi

msg_info "$(translate "Creating the container...")"
oci_quiet pct create "$SERVER_ID" "$SERVER_ARCHIVE" --rootfs "${ROOTFS_STORAGE}:16" \
  --mp0 "$SERVER_MEDIA_MOUNT" --hostname "${STACK_NAME}-server" \
  --cores 4 --memory 3072 --swap 1024 \
  --net0 "name=eth0,bridge=${FRONTEND_BRIDGE},firewall=1,host-managed=1,${FRONTEND_NET},type=veth" \
  --net1 "name=eth1,bridge=${PRIVATE_BRIDGE},firewall=1,host-managed=1,ip=${SERVER_ADDRESS},type=veth" \
  "${SERVER_DEVICE_ARGS[@]}" --unprivileged 1 --features nesting=1 --cmode console \
  --onboot "$ONBOOT" --startup order=40,up=10,down=30 --tags "$TAGS" \
  --description 'Immich server native OCI'
created_ids+=("$SERVER_ID")

oci_quiet pct mount "$SERVER_ID"
SERVER_ROOT="/var/lib/lxc/${SERVER_ID}/rootfs"
cat >"$SERVER_ROOT/usr/local/bin/immich-lxc-start" <<'EOF'
#!/bin/bash
set -e
for attempt in $(seq 1 60); do
  if grep -qE '^eth0[[:space:]]+00000000[[:space:]]' /proc/net/route; then
    sleep 3
    exec /bin/bash -c 'start.sh'
  fi
  sleep 1
done
echo 'Immich frontend route was not ready after 60 seconds' >&2
exit 1
EOF
chmod 0755 "$SERVER_ROOT/usr/local/bin/immich-lxc-start"
chown 100000:100000 "$SERVER_ROOT/usr/local/bin/immich-lxc-start"
oci_quiet pct unmount "$SERVER_ID"

oci_quiet pct set "$SERVER_ID" --entrypoint 'tini -- /usr/local/bin/immich-lxc-start'
set_lxc_directive "$SERVER_ID" lxc.init.cwd /usr/src/app
set_lxc_directive "$SERVER_ID" lxc.signal.halt SIGTERM
set_runtime_env "$SERVER_ID" TZ "$TIMEZONE"
set_runtime_env "$SERVER_ID" CPU_CORES 4
set_runtime_env "$SERVER_ID" IMMICH_HOST 0.0.0.0
set_runtime_env "$SERVER_ID" IMMICH_PORT 2283
set_runtime_env "$SERVER_ID" DB_HOSTNAME "$DB_IP"
set_runtime_env "$SERVER_ID" DB_PORT 5432
set_runtime_env "$SERVER_ID" DB_USERNAME postgres
set_runtime_env "$SERVER_ID" DB_DATABASE_NAME immich
set_runtime_env "$SERVER_ID" DB_VECTOR_EXTENSION vectorchord
set_runtime_env "$SERVER_ID" REDIS_HOSTNAME "$VALKEY_IP"
set_runtime_env "$SERVER_ID" REDIS_PORT 6379
set_runtime_env "$SERVER_ID" IMMICH_MACHINE_LEARNING_URL "http://${ML_IP}:3003"
if [[ $VIDEO_ACCELERATION == vaapi && $VAAPI_DRIVER != auto ]]; then
  set_runtime_env "$SERVER_ID" LIBVA_DRIVER_NAME "$VAAPI_DRIVER"
fi
set_runtime_env "$SERVER_ID" DB_PASSWORD "$DB_PASSWORD"
msg_ok "$(translate "Container created:") CT $SERVER_ID (Immich)"

msg_info "$(translate "Installing the stack startup hook...")"
LIFECYCLE_SPEC=$(mktemp /tmp/proxmenux-stack-lifecycle.XXXXXX)
jq -nc --arg stack "$STACK_NAME" --argjson db "$DB_ID" --arg db_ip "$DB_IP" \
  --argjson valkey "$VALKEY_ID" --arg valkey_ip "$VALKEY_IP" \
  --argjson ml "$ML_ID" --arg ml_ip "$ML_IP" '
  {
    schema: 1,
    stack: $stack,
    dependencies: [
      {vmid: $db, label: "PostgreSQL", healthcheck: {
        type: "exec", timeout_seconds: 90,
        argv: ["pg_isready", "-h", $db_ip, "-p", "5432", "-U", "postgres", "-d", "immich"]
      }},
      {vmid: $valkey, label: "Valkey", healthcheck: {
        type: "exec", timeout_seconds: 60,
        argv: ["valkey-cli", "-h", $valkey_ip, "ping"]
      }},
      {vmid: $ml, label: "Immich Machine Learning", healthcheck: {
        type: "http", timeout_seconds: 180, url: ("http://" + $ml_ip + ":3003/ping")
      }}
    ]
  }' >"$LIFECYCLE_SPEC"
LIFECYCLE_CONFIG_PATH="/etc/pve/priv/proxmenux-stack-${SERVER_ID}.json"
if ! oci_quiet bash "$STACK_DEPENDENCY_HOOK" --install "$SERVER_ID" "$LIFECYCLE_SPEC"; then
  rm -f "$LIFECYCLE_SPEC"
  die "$(translate "Could not install the stack startup hook")"
fi
rm -f "$LIFECYCLE_SPEC"
msg_ok "$(translate "Stack startup hook installed")"

wait_command() {
  local label=$1 retries=$2
  shift 2
  local attempt
  for attempt in $(seq 1 "$retries"); do
    "$@" >/dev/null 2>&1 && return 0
    sleep 2
  done
  die "$(translate "Health check failed:") $label"
}

SERVER_LAN_IP=""
if (( START_AFTER == 1 )); then
  msg_info "$(translate "Starting the service:") PostgreSQL"
  oci_quiet pct start "$DB_ID"
  wait_command PostgreSQL 45 pct exec "$DB_ID" -- pg_isready -h "$DB_IP" -p 5432 -U postgres -d immich
  msg_ok "$(translate "Service ready:") PostgreSQL"
  msg_info "$(translate "Starting the service:") Valkey"
  oci_quiet pct start "$VALKEY_ID"
  wait_command Valkey 30 pct exec "$VALKEY_ID" -- valkey-cli -h "$VALKEY_IP" ping
  msg_ok "$(translate "Service ready:") Valkey"
  ML_LABEL=$(translate "Machine learning")
  msg_info "$(translate "Starting the service:") $ML_LABEL"
  oci_quiet pct start "$ML_ID"
  wait_command "$ML_LABEL" 60 curl -fsS "http://${ML_IP}:3003/ping"
  msg_ok "$(translate "Service ready:") $ML_LABEL"
  validate_immich_ml_runtime \
    || die "$(translate "The requested machine learning GPU profile is not working; it is not replaced by CPU")"
  msg_info "$(translate "Starting the service:") Immich"
  oci_quiet pct start "$SERVER_ID"
  msg_info "$(translate "Waiting for the application to respond...")"
  wait_command Immich 90 curl -fsS "http://${SERVER_IP}:2283/api/server/ping"
  SERVER_LAN_IP=$(pct exec "$SERVER_ID" -- node -e '
    const os = require("node:os");
    for (const addresses of Object.values(os.networkInterfaces())) {
      for (const address of addresses ?? []) {
        if (address.family === "IPv4" && !address.internal && !address.address.startsWith("10.77.")) {
          process.stdout.write(address.address); process.exit(0);
        }
      }
    }
    process.exit(1);
  ')
  msg_ok "$(translate "Application responding:") http://${SERVER_LAN_IP}:2283/"
fi

RESULT=$(jq -cn \
  --argjson vmid "$SERVER_ID" --argjson ml "$ML_ID" --argjson db "$DB_ID" \
  --argjson valkey "$VALKEY_ID" --arg ip "$SERVER_LAN_IP" --arg arch "$ARCH" \
  --arg digest "$SERVER_DIGEST" --arg log "$OCI_LOG" \
  '{vmid:$vmid,stack_vmids:{server:$vmid,machine_learning:$ml,database:$db,valkey:$valkey},ip:$ip,architecture:$arch,digest:$digest,urls:(if ($ip|length)>0 then [{label:"Immich WebUI",url:("http://"+$ip+":2283/")}] else [] end),credentials:[],log:$log}')
INSTALL_COMPLETE=1
oci_native_finalize
printf 'PROXMENUX_RESULT=%s\n' "$(printf '%s' "$RESULT" | base64 -w0)"
INSTALL_COMPLETE=1
trap - EXIT
