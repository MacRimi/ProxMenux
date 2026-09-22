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
INSTALL_STARTED_AT=$(date --iso-8601=seconds)

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

set_lxc_directive() {
  local id=$1 key=$2 value=$3 config="/etc/pve/lxc/${1}.conf" escaped_key
  escaped_key=${key//./\.}
  sed -i -E "/^${escaped_key}:/d" "$config"
  printf '%s: %s\n' "$key" "$value" >>"$config"
}

print_first_boot_diagnostics() {
  local id=$1 label=$2
  {
    printf '=== %s CT %s: Proxmox service ===\n' "$label" "$id"
    journalctl -u "pve-container@${id}.service" --since "$INSTALL_STARTED_AT" \
      --no-pager -n 120 2>&1 || true
    printf '\n=== Host: serious errors since the installation started ===\n'
    journalctl -k --since "$INSTALL_STARTED_AT" --no-pager 2>&1 \
      | grep -iE 'segfault|general protection fault|mce:|hardware error|memory failure|out of memory|oom-kill' \
      | tail -n 120 || true
  } >>"$OCI_LOG"
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
oci_log_init "$(jq -r '.stack_name // "tandoor"' "$DEPLOYMENT_FILE" 2>/dev/null || printf tandoor)"
for command in pct qm pvesh pvesm skopeo jq openssl python3 curl ip stat dpkg base64 mktemp lxc-info flock journalctl tee; do
  require_command "$command"
done
[[ -r $VERIFY_OCI_ARCHIVE ]] || die "$(translate "The OCI archive verifier was not found")"
[[ -r $ALLOCATE_PRIVATE_NETWORK ]] || die "$(translate "The private network allocator was not found")"
[[ -r $STACK_DEPENDENCY_HOOK ]] || die "$(translate "The stack startup hook was not found")"

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
APPLICATION_STORAGE=$(jqr '.application_storage')
STATIC_SIZE=$(jqr '.static_size_gb')
DATABASE_STORAGE=$(jqr '.database_storage')
DATABASE_SIZE=$(jqr '.database_size_gb')
MEDIA_MODE=$(jqr '.media.mode')
MEDIA_STORAGE=$(jq -r '.media.storage // empty' "$DEPLOYMENT_FILE")
MEDIA_SIZE=$(jq -r '.media.size_gb // empty' "$DEPLOYMENT_FILE")
MEDIA_ROOT=$(jq -r '.media.host_path // empty' "$DEPLOYMENT_FILE")
ALLOWED_HOSTS=$(jqr '.application.allowed_hosts')
ADMIN_USERNAME=$(jqr '.application.admin_username')
ADMIN_EMAIL=$(jqr '.application.admin_email')
TIMEZONE=$(jqr '.timezone')
ONBOOT=$(jqr '.onboot | if . then 1 else 0 end')
START_AFTER=$(jqr '.start_after_create | if . then 1 else 0 end')
FRONTEND_BRIDGE=$(jqr '.network.frontend_bridge')
FRONTEND_IPV4=$(jqr '.network.frontend_ipv4')
FRONTEND_GATEWAY=$(jq -r '.network.frontend_gateway // empty' "$DEPLOYMENT_FILE")
oci_access_net "$FRONTEND_IPV4" "$FRONTEND_GATEWAY" \
  || die "$(translate "Invalid access address:") $FRONTEND_IPV4 $FRONTEND_GATEWAY"
FRONTEND_NET=$OCI_ACCESS_NET
PRIVATE_BRIDGE=$(jqr '.network.private_bridge')
PRIVATE_SUBNET=$(jqr '.network.private_subnet')
PRIVATE_HOST_ADDRESS=$(jqr '.network.private_host_address')
APPLICATION_ADDRESS=$(jqr '.network.application_address')
DATABASE_ADDRESS=$(jqr '.network.database_address')
APPLICATION_IP=${APPLICATION_ADDRESS%/*}
DATABASE_IP=${DATABASE_ADDRESS%/*}

[[ $STATIC_SIZE =~ ^[0-9]+$ ]] && (( STATIC_SIZE >= 1 )) \
  || die "$(translate "The staticfiles volume needs at least 1 GB")"
[[ $DATABASE_SIZE =~ ^[0-9]+$ ]] && (( DATABASE_SIZE >= 4 )) \
  || die "$(translate "The PostgreSQL volume needs at least 4 GB")"
[[ $ALLOWED_HOSTS != *$'\n'* && $ALLOWED_HOSTS != *$'\r'* ]] \
  || die "$(translate "Invalid ALLOWED_HOSTS value")"
[[ $ADMIN_USERNAME =~ ^[A-Za-z0-9_.@-]+$ ]] || die "$(translate "Invalid administrator user name")"
[[ $ADMIN_EMAIL =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] \
  || die "$(translate "Invalid administrator email")"
case "$MEDIA_MODE" in
  managed-volume)
    [[ -n $MEDIA_STORAGE && $MEDIA_SIZE =~ ^[0-9]+$ ]] \
      && (( MEDIA_SIZE >= 2 )) || die "$(translate "Invalid mediafiles volume")"
    ;;
  host-bind)
    [[ $MEDIA_ROOT == /* && $MEDIA_ROOT != *","* && $MEDIA_ROOT != *$'\n'* ]] \
      || die "$(translate "Invalid shared path")"
    ;;
  *) die "$(translate "Unsupported storage mode:") $MEDIA_MODE" ;;
esac
[[ $PRIVATE_BRIDGE =~ ^vmbr[0-9]+$ ]] || die "$(translate "Invalid private bridge")"
[[ $PRIVATE_SUBNET =~ ^10\.77\.[0-9]{1,3}\.0/24$ ]] || die "$(translate "Invalid private network")"

vmid_block_free() {
  local candidate=$1 offset
  for offset in 0 1; do
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
vmid_block_free "$BASE_VMID" || die "$(translate "These VMIDs are not free:") ${BASE_VMID}-$((BASE_VMID + 1))"

APPLICATION_ID=$BASE_VMID
DATABASE_ID=$((BASE_VMID + 1))
oci_log "Stack: $STACK_NAME; VMIDs: Tandoor=$APPLICATION_ID, PostgreSQL=$DATABASE_ID"
oci_log "Private network: $PRIVATE_SUBNET on $PRIVATE_BRIDGE"

if [[ $DRY_RUN == 1 ]]; then
  msg_info2 "$(translate "Stack:") $STACK_NAME · CT ${APPLICATION_ID}-${DATABASE_ID}"
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
for address in "$APPLICATION_ADDRESS" "$DATABASE_ADDRESS"; do
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
  local partial log pid bytes elapsed status
  msg_info "$(translate "Checking the image in the registry...")"
  oci_log "Resolving ${key}: ${image}"
  transport_image=$(skopeo_transport_reference "$image")
  inspect=$(resolve_image_manifest "$key" "$transport_image") \
    || die "$(translate "Could not resolve the OCI manifest:") $image"
  digest=$(jq -er '.Digest' <<<"$inspect")
  oci_log "Selected digest for ${key}: ${digest}"
  short=${digest#sha256:}
  short=${short:0:16}
  archive_name="image-tandoor-${key}_${ARCH}_${short}.tar"
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
    partial="${archive_path}.partial.$$"
    log="${partial}.log"
    oci_log "Downloading ${image} by digest ${digest}"
    skopeo copy --override-os linux --override-arch "$ARCH" --retry-times 3 \
      --retry-delay 5s --image-parallel-copies 1 \
      "docker://${transport_image}" "oci-archive:${partial}:image-tandoor-${key}" >"$log" 2>&1 &
    pid=$!
    elapsed=0
    while kill -0 "$pid" 2>/dev/null; do
      bytes=$(stat -c %s "$partial" 2>/dev/null || printf 0)
      msg_progress "$(translate "Downloading the image:") ${key} · $((bytes / 1048576)) MiB · ${elapsed}s"
      sleep 2
      elapsed=$((elapsed + 2))
    done
    status=0
    wait "$pid" || status=$?
    cat "$log" >>"$OCI_LOG"
    rm -f "$log"
    (( status == 0 )) || { rm -f "$partial"; die "$(translate "Image download failed:") $image"; }
    msg_info "$(translate "Verifying the image integrity...")"
    oci_quiet python3 "$VERIFY_OCI_ARCHIVE" "$partial" \
      || { rm -f "$partial"; die "$(translate "The downloaded image is corrupt:") $image"; }
    mv -f "$partial" "$archive_path"
  fi
  msg_ok "$(translate "Image:") $image"
  RESOLVED_ARCHIVE=$archive_volume
  RESOLVED_DIGEST=$digest
}

APPLICATION_IMAGE=$(jq -er '.container_contract.image.reference' "$TEMPLATE_FILE")
DATABASE_IMAGE=$(jq -er '.compose_stack.services[] | select(.name == "db_recipes") | .image' "$TEMPLATE_FILE")
ensure_image application "$APPLICATION_IMAGE"
APPLICATION_ARCHIVE=$RESOLVED_ARCHIVE
APPLICATION_DIGEST=$RESOLVED_DIGEST
ensure_image database "$DATABASE_IMAGE"
DATABASE_ARCHIVE=$RESOLVED_ARCHIVE
DATABASE_DIGEST=$RESOLVED_DIGEST

source "$SCRIPT_DIR/oci_native_stack.sh"
oci_native_begin "$APPLICATION_ID" \
  --member application "$APPLICATION_ID" "$APPLICATION_IMAGE" "$APPLICATION_ARCHIVE" \
  --member database "$DATABASE_ID" "$DATABASE_IMAGE" "$DATABASE_ARCHIVE"

DB_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 48)
ADMIN_PASSWORD=$(openssl rand -hex 16)
if [[ $MEDIA_MODE == host-bind ]]; then
  install -d -m 0775 -o 100000 -g 100000 "$MEDIA_ROOT"
  MEDIA_MOUNT="${MEDIA_ROOT},mp=/opt/recipes/mediafiles,backup=0"
else
  MEDIA_MOUNT="${MEDIA_STORAGE}:${MEDIA_SIZE},mp=/opt/recipes/mediafiles,backup=1"
fi
TAGS="productivity;oci;proxmenux"

msg_info "$(translate "Creating the container...")"
oci_quiet pct create "$DATABASE_ID" "$DATABASE_ARCHIVE" --rootfs "${ROOTFS_STORAGE}:4" \
  --mp0 "${DATABASE_STORAGE}:${DATABASE_SIZE},mp=/var/lib/postgresql/data,backup=1" \
  --hostname "${STACK_NAME}-db" --cores 2 --memory 1024 --swap 512 \
  --net0 "name=eth0,bridge=${PRIVATE_BRIDGE},firewall=1,host-managed=1,ip=${DATABASE_ADDRESS},type=veth" \
  --unprivileged 1 --features nesting=1 --cmode console --onboot "$ONBOOT" \
  --startup order=10,up=10,down=30 --tags "$TAGS" \
  --description 'Tandoor PostgreSQL native OCI'
created_ids+=("$DATABASE_ID")

oci_quiet pct mount "$DATABASE_ID"
DATABASE_ROOT="/var/lib/lxc/${DATABASE_ID}/rootfs"
POSTGRES_UID=$(awk -F: '$1 == "postgres" {print $3}' "$DATABASE_ROOT/etc/passwd")
POSTGRES_GID=$(awk -F: '$1 == "postgres" {print $4}' "$DATABASE_ROOT/etc/passwd")
[[ -n $POSTGRES_UID && -n $POSTGRES_GID ]] || die "$(translate "The postgres user was not found in the image")"
rm -rf "$DATABASE_ROOT/var/lib/postgresql/data/lost+found"
install -d -m 0700 -o "$((100000 + POSTGRES_UID))" -g "$((100000 + POSTGRES_GID))" \
  "$DATABASE_ROOT/var/lib/postgresql/data/pgdata"
cat >"$DATABASE_ROOT/usr/local/bin/tandoor-postgres-lxc-start" <<EOF
#!/bin/sh
set -eu
exec docker-entrypoint.sh postgres -c 'listen_addresses=127.0.0.1,${DATABASE_IP}'
EOF
chmod 0755 "$DATABASE_ROOT/usr/local/bin/tandoor-postgres-lxc-start"
chown 100000:100000 "$DATABASE_ROOT/usr/local/bin/tandoor-postgres-lxc-start"
oci_quiet pct unmount "$DATABASE_ID"
oci_quiet pct set "$DATABASE_ID" --entrypoint /usr/local/bin/tandoor-postgres-lxc-start
set_lxc_directive "$DATABASE_ID" lxc.init.cwd /
set_lxc_directive "$DATABASE_ID" lxc.signal.halt SIGINT
set_runtime_env "$DATABASE_ID" POSTGRES_DB djangodb
set_runtime_env "$DATABASE_ID" POSTGRES_USER djangouser
set_runtime_env "$DATABASE_ID" POSTGRES_PASSWORD "$DB_PASSWORD"
set_runtime_env "$DATABASE_ID" POSTGRES_INITDB_ARGS --data-checksums
set_runtime_env "$DATABASE_ID" PGDATA /var/lib/postgresql/data/pgdata
set_runtime_env "$DATABASE_ID" TZ "$TIMEZONE"
msg_ok "$(translate "Container created:") CT $DATABASE_ID (PostgreSQL)"

msg_info "$(translate "Creating the container...")"
oci_quiet pct create "$APPLICATION_ID" "$APPLICATION_ARCHIVE" --rootfs "${ROOTFS_STORAGE}:8" \
  --mp0 "${APPLICATION_STORAGE}:${STATIC_SIZE},mp=/opt/recipes/staticfiles,backup=1" \
  --mp1 "$MEDIA_MOUNT" --hostname "$STACK_NAME" \
  --cores 2 --memory 2048 --swap 512 \
  --net0 "name=eth0,bridge=${FRONTEND_BRIDGE},firewall=1,host-managed=1,${FRONTEND_NET},type=veth" \
  --net1 "name=eth1,bridge=${PRIVATE_BRIDGE},firewall=1,host-managed=1,ip=${APPLICATION_ADDRESS},type=veth" \
  --unprivileged 1 --features nesting=1 --cmode console --onboot "$ONBOOT" \
  --startup order=20,up=15,down=30 --tags "$TAGS" \
  --description 'Tandoor Recipes native OCI'
created_ids+=("$APPLICATION_ID")

oci_quiet pct mount "$APPLICATION_ID"
APPLICATION_ROOTFS="/var/lib/lxc/${APPLICATION_ID}/rootfs"
rm -rf "$APPLICATION_ROOTFS/opt/recipes/staticfiles/lost+found"
rm -rf "$APPLICATION_ROOTFS/opt/recipes/mediafiles/lost+found"
oci_quiet pct unmount "$APPLICATION_ID"
set_runtime_env "$APPLICATION_ID" SECRET_KEY "$SECRET_KEY"
set_runtime_env "$APPLICATION_ID" TZ "$TIMEZONE"
set_runtime_env "$APPLICATION_ID" ALLOWED_HOSTS "$ALLOWED_HOSTS"
set_runtime_env "$APPLICATION_ID" DB_ENGINE django.db.backends.postgresql
set_runtime_env "$APPLICATION_ID" POSTGRES_HOST "$DATABASE_IP"
set_runtime_env "$APPLICATION_ID" POSTGRES_DB djangodb
set_runtime_env "$APPLICATION_ID" POSTGRES_PORT 5432
set_runtime_env "$APPLICATION_ID" POSTGRES_USER djangouser
set_runtime_env "$APPLICATION_ID" POSTGRES_PASSWORD "$DB_PASSWORD"
msg_ok "$(translate "Container created:") CT $APPLICATION_ID (Tandoor)"

msg_info "$(translate "Installing the stack startup hook...")"
LIFECYCLE_SPEC=$(mktemp /tmp/proxmenux-stack-lifecycle.XXXXXX)
jq -nc --arg stack "$STACK_NAME" --argjson db "$DATABASE_ID" --arg db_ip "$DATABASE_IP" '
  {
    schema: 1,
    stack: $stack,
    dependencies: [
      {vmid: $db, label: "PostgreSQL", healthcheck: {
        type: "exec", timeout_seconds: 120,
        argv: ["pg_isready", "-h", $db_ip, "-U", "djangouser", "-d", "djangodb"]
      }}
    ]
  }' >"$LIFECYCLE_SPEC"
LIFECYCLE_CONFIG_PATH="/etc/pve/priv/proxmenux-stack-${APPLICATION_ID}.json"
if ! oci_quiet bash "$STACK_DEPENDENCY_HOOK" --install "$APPLICATION_ID" "$LIFECYCLE_SPEC"; then
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

APPLICATION_LAN_IP=""
if (( START_AFTER == 1 )); then
  msg_info "$(translate "Starting the service:") PostgreSQL"
  oci_quiet pct start "$DATABASE_ID"
  wait_command PostgreSQL 60 pct exec "$DATABASE_ID" -- \
    pg_isready -h "$DATABASE_IP" -U djangouser -d djangodb
  msg_ok "$(translate "Service ready:") PostgreSQL"
  msg_info "$(translate "Starting the service:") Tandoor"
  oci_quiet pct start "$APPLICATION_ID"

  msg_info "$(translate "Waiting for the application to respond...")"
  for _ in $(seq 1 180); do
    APPLICATION_LAN_IP=$(lxc-info -n "$APPLICATION_ID" -iH 2>/dev/null \
      | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
      | grep -vFx "$APPLICATION_IP" | head -n 1 || true)
    if [[ -n $APPLICATION_LAN_IP ]] \
      && curl -fsS "http://${APPLICATION_LAN_IP}/" >/dev/null 2>&1; then
      break
    fi
    if [[ $(pct status "$APPLICATION_ID" 2>/dev/null) != *running* ]]; then
      print_first_boot_diagnostics "$APPLICATION_ID" tandoor
      die "$(translate "The application stopped during its first start:") Tandoor"
    fi
    sleep 2
  done
  if [[ -z $APPLICATION_LAN_IP ]]; then
    print_first_boot_diagnostics "$APPLICATION_ID" tandoor
    die "$(translate "The application did not get an address on the access network:") Tandoor"
  fi
  curl -fsS "http://${APPLICATION_LAN_IP}/" >/dev/null 2>>"$OCI_LOG" \
    || { print_first_boot_diagnostics "$APPLICATION_ID" tandoor; \
      die "$(translate "The application did not complete its initial setup:") Tandoor"; }
  msg_ok "$(translate "Application responding:") http://${APPLICATION_LAN_IP}/"
  msg_info "$(translate "Creating the initial administrator...")"
  oci_quiet pct exec "$APPLICATION_ID" -- env DJANGO_SUPERUSER_PASSWORD="$ADMIN_PASSWORD" \
    DJANGO_SUPERUSER_USERNAME="$ADMIN_USERNAME" DJANGO_SUPERUSER_EMAIL="$ADMIN_EMAIL" \
    /bin/sh -c 'cd /opt/recipes && . venv/bin/activate && python manage.py createsuperuser --noinput' \
    || { print_first_boot_diagnostics "$APPLICATION_ID" tandoor; \
      die "$(translate "Could not create the initial administrator")"; }
  msg_ok "$(translate "Initial administrator created:") $ADMIN_USERNAME"
fi

RESULT=$(jq -nc \
  --argjson vmid "$APPLICATION_ID" \
  --arg ip "$APPLICATION_LAN_IP" \
  --argjson application_id "$APPLICATION_ID" \
  --argjson database_id "$DATABASE_ID" \
  --arg application_digest "$APPLICATION_DIGEST" \
  --arg database_digest "$DATABASE_DIGEST" \
  --arg admin_user "$ADMIN_USERNAME" \
  --arg admin_password "$ADMIN_PASSWORD" \
  --arg admin_label "$(translate "Initial Tandoor administrator")" \
  --arg log "$OCI_LOG" \
  '{
    vmid: $vmid,
    ip: (if $ip == "" then null else $ip end),
    stack_vmids: {tandoor: $application_id, database: $database_id},
    urls: (if $ip == "" then [] else [{label: "Tandoor WebUI", url: ("http://" + $ip + "/")}] end),
    credentials: [{
      label: $admin_label,
      username: $admin_user,
      password: $admin_password,
      change_required: true
    }],
    image_digests: {application: $application_digest, database: $database_digest},
    log: $log
  }')
INSTALL_COMPLETE=1
oci_native_finalize
printf 'PROXMENUX_RESULT=%s\n' "$(printf '%s' "$RESULT" | base64 -w0)"
