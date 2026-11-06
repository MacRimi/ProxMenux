#!/usr/bin/env bash
set -Eeuo pipefail

PATH=/usr/sbin:/usr/bin:/sbin:/bin

HOOK_NAME=proxmenux-stack-dependencies.sh
COMPOSE_JOB_HELPER=/var/lib/vz/snippets/proxmenux-compose-jobs.py
# Longest wait for a dependency that is being backed up, and for any other lock.
BACKUP_LOCK_WAIT=${PROXMENUX_STACK_BACKUP_LOCK_WAIT:-14400}
OTHER_LOCK_WAIT=${PROXMENUX_STACK_OTHER_LOCK_WAIT:-300}
# vzdump starts again a guest that was running before its backup right after releasing it.
RESTART_GRACE=${PROXMENUX_STACK_RESTART_GRACE:-20}
POLL=${PROXMENUX_STACK_POLL:-5}
# Earlier published versions of this script, replaced on update.
PREVIOUS_RELEASES=(
  4bc477bcc35e229d1c964c9372838f0973cbe6f1e3e41f0fb486e9b724247310
  243b0dca81b1b155ca169a4d0e11cdb8ca55974c65ede6a4a9be8f4d536a141e
  c28b69acd7cc8e66d3aec3e8b2ec86bda0e4f91193ec78549f1965f2c859c0d1
  02c50ef17f2411ef22f4d382c51b34a7a0974a446d4a155ecb63fb1e805a7c59
)

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

find_snippet_storage() {
  local storage
  if pvesm status --content snippets 2>/dev/null \
    | awk 'NR > 1 && $1 == "local" && $3 == "active" {found=1} END {exit !found}'; then
    printf 'local'
    return
  fi
  storage=$(pvesm status --content snippets 2>/dev/null \
    | awk 'NR > 1 && $3 == "active" {print $1; exit}')
  if [[ -z $storage ]]; then
    # A new Proxmox installation accepts no snippets on any storage.
    enable_local_snippets || die "No active storage supports snippets"
    storage=local
  fi
  printf '%s' "$storage"
}

enable_local_snippets() {
  local content
  content=$(pvesh get /storage/local --output-format json 2>/dev/null | jq -r '.content // empty')
  [[ -n $content ]] || return 1
  pvesm set local --content "${content},snippets" >/dev/null 2>&1 || return 1
  pvesm status --content snippets 2>/dev/null \
    | awk 'NR > 1 && $1 == "local" && $3 == "active" {found=1} END {exit !found}'
}

install_hook() {
  local main_id=${1:?missing main VMID} source_config=${2:?missing lifecycle JSON}
  local storage hook_volume hook_path target_config
  [[ $main_id =~ ^[0-9]+$ ]] || die "Invalid main VMID"
  jq -e '
    .schema == 1 and
    (.dependencies | type == "array") and
    (.dependencies | length > 0) and
    (all(.dependencies[];
      (.vmid | type == "number") and
      (.label | type == "string") and
      (.healthcheck.type | IN("exec", "http", "running", "tcp", "completed")) and
      (.healthcheck.timeout_seconds | type == "number") and
      (if .healthcheck.type == "tcp" then
        (.healthcheck.host | type == "string") and
        (.healthcheck.host | test("^([0-9]{1,3}\\.){3}[0-9]{1,3}$")) and
        (.healthcheck.host | split(".") | all(.[]; tonumber < 256)) and
        (.healthcheck.port | type == "number") and
        (.healthcheck.port > 0 and .healthcheck.port < 65536 and .healthcheck.port == (.healthcheck.port | floor))
       elif .healthcheck.type == "completed" then
        (.healthcheck.job | type == "object") and
        (.healthcheck.job.installation_id | type == "string") and
        (.healthcheck.job.installation_id | test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")) and
        (.healthcheck.job.image_digest | type == "string") and
        (.healthcheck.job.image_digest | test("^sha256:[0-9a-f]{64}$")) and
        (.healthcheck.job.expected_config_fingerprint | type == "string") and
        (.healthcheck.job.expected_config_fingerprint | test("^[0-9a-f]{64}$")) and
        (.healthcheck.job.timeout_seconds == .healthcheck.timeout_seconds) and
        (.healthcheck.timeout_seconds >= 30 and .healthcheck.timeout_seconds <= 3600 and .healthcheck.timeout_seconds == (.healthcheck.timeout_seconds | floor))
       else true end)
    ))
  ' "$source_config" >/dev/null || die "Invalid dependency contract"

  if jq -e 'any(.dependencies[]; .healthcheck.type == "completed")' "$source_config" >/dev/null; then
    local helper_source helper_temporary
    helper_source="$(dirname -- "$0")/oci_compose_jobs.py"
    [[ -f $helper_source && ! -L $helper_source ]] || die "Native OCI job helper is missing"
    install -d -m 0755 "$(dirname -- "$COMPOSE_JOB_HELPER")"
    helper_temporary=$(mktemp "${COMPOSE_JOB_HELPER}.XXXXXX")
    if ! install -m 0755 "$helper_source" "$helper_temporary" || ! mv -f -- "$helper_temporary" "$COMPOSE_JOB_HELPER"; then
      rm -f -- "$helper_temporary"
      die "Could not install the persistent native OCI job helper"
    fi
  fi

  storage=$(find_snippet_storage)
  hook_volume="${storage}:snippets/${HOOK_NAME}"
  hook_path=$(pvesm path "$hook_volume")
  install -D -m 0755 "$0" "$hook_path"

  target_config="/etc/pve/priv/proxmenux-stack-${main_id}.json"
  umask 077
  cat "$source_config" >"$target_config"
  pct set "$main_id" --hookscript "$hook_volume" >/dev/null
  printf 'Proxmox hookscript installed: CT %s starts its dependencies through %s\n' \
    "$main_id" "$hook_volume"
}

# The installed copies of an earlier release take this version; a copy
# changed by hand is left as it is.
refresh_hooks() {
  local volume path current known
  while IFS= read -r volume; do
    path=$(pvesm path "$volume" 2>/dev/null) || continue
    [[ -f $path && ! -L $path ]] || continue
    current=$(sha256sum "$path" | cut -d' ' -f1)
    for known in "${PREVIOUS_RELEASES[@]}"; do
      if [[ $current == "$known" ]]; then
        install -m 0755 "$0" "$path.new" && mv -f "$path.new" "$path"
        printf 'Updated %s\n' "$path"
        break
      fi
    done
  done < <(sed -n "s/^hookscript:[[:space:]]*\([^[:space:]]*:snippets\/${HOOK_NAME//./\\.}\)[[:space:]]*$/\1/p" \
             /etc/pve/lxc/*.conf 2>/dev/null | sort -u)
}

is_running() {
  [[ $(pct status "$1" 2>/dev/null || true) == "status: running" ]]
}

container_lock() {
  pct config "$1" 2>/dev/null | sed -n '/^lock:/{s/^lock:[[:space:]]*//p;q;}' || true
}

# A dependency stopped for its own backup stays locked until vzdump has
# saved it, and vzdump starts it again when it was running before.
wait_for_release() {
  local id=$1 label=$2 lock limit waited=0
  lock=$(container_lock "$id")
  [[ -n $lock ]] || return 0
  limit=$OTHER_LOCK_WAIT
  if [[ $lock == backup ]]; then
    limit=$BACKUP_LOCK_WAIT
  fi
  printf 'Dependency %s (CT %s) is locked (%s); waiting until it is released...\n' "$label" "$id" "$lock"
  while lock=$(container_lock "$id"); [[ -n $lock ]]; do
    (( waited < limit )) || die "$label (CT $id) is still locked ($lock) after ${waited}s"
    sleep "$POLL"
    waited=$((waited + POLL))
  done
  printf 'Dependency %s (CT %s) was released.\n' "$label" "$id"
  waited=0
  while (( waited < RESTART_GRACE )) && ! is_running "$id"; do
    sleep 2
    waited=$((waited + 2))
  done
}

dependency_is_healthy() {
  local id=$1 healthcheck=$2 type url
  type=$(jq -r '.type' <<<"$healthcheck")
  case "$type" in
    running)
      [[ $(pct status "$id" 2>/dev/null || true) == "status: running" ]]
      ;;
    exec)
      local -a command=()
      mapfile -t command < <(jq -r '.argv[]' <<<"$healthcheck")
      ((${#command[@]} > 0)) || return 1
      pct exec "$id" -- "${command[@]}" >/dev/null 2>&1 9>&-
      ;;
    http)
      url=$(jq -r '.url' <<<"$healthcheck")
      curl -fsS --max-time 3 "$url" >/dev/null 2>&1
      ;;
    tcp)
      local host port
      host=$(jq -r '.host' <<<"$healthcheck")
      port=$(jq -r '.port' <<<"$healthcheck")
      python3 - "$host" "$port" <<'PYTCP' >/dev/null 2>&1
import ipaddress, socket, sys
host = str(ipaddress.IPv4Address(sys.argv[1]))
port = int(sys.argv[2])
if not 0 < port < 65536:
    raise ValueError('Invalid TCP port')
with socket.create_connection((host, port), timeout=3):
    pass
PYTCP
      ;;
    *) return 1 ;;
  esac
}

start_dependencies() {
  local main_id=$1 config="/etc/pve/priv/proxmenux-stack-${1}.json"
  local encoded dependency id label healthcheck timeout elapsed
  [[ -r $config ]] || die "Missing dependency contract for main CT $main_id"

  exec 9>"/run/lock/proxmenux-stack-${main_id}.lock"
  flock 9
  while IFS= read -r encoded; do
    [[ -n $encoded ]] || continue
    dependency=$(base64 -d <<<"$encoded")
    id=$(jq -r '.vmid' <<<"$dependency")
    label=$(jq -r '.label' <<<"$dependency")
    healthcheck=$(jq -c '.healthcheck' <<<"$dependency")
    timeout=$(jq -r '.healthcheck.timeout_seconds' <<<"$dependency")
    [[ $id =~ ^[0-9]+$ && $timeout =~ ^[0-9]+$ && $timeout -gt 0 ]] \
      || die "Invalid dependency in $config"
    pct config "$id" >/dev/null 2>&1 \
      || die "Dependency $label (CT $id) does not exist"

    if [[ $(jq -r '.type' <<<"$healthcheck") == completed ]]; then
      [[ -f $COMPOSE_JOB_HELPER && ! -L $COMPOSE_JOB_HELPER ]] || die "Native OCI job helper is missing"
      local helper_owner helper_mode
      helper_owner=$(stat -c '%u' "$COMPOSE_JOB_HELPER")
      helper_mode=$(stat -c '%a' "$COMPOSE_JOB_HELPER")
      [[ $helper_owner == 0 && $helper_mode =~ ^[0-7]{3,4}$ ]] && (( (8#$helper_mode & 8#022) == 0 )) \
        || die "Native OCI job helper is not owned safely by root"
      printf 'Waiting for completed job %s (CT %s)...\n' "$label" "$id"
      python3 -I "$COMPOSE_JOB_HELPER" ensure "$id" --spec-json "$(jq -c '.job' <<<"$healthcheck")" >/dev/null 9>&- \
        || die "Job $label (CT $id) did not complete successfully"
      printf 'Dependency %s (CT %s): ready.\n' "$label" "$id"
      continue
    fi

    is_running "$id" || wait_for_release "$id" "$label"
    if ! is_running "$id"; then
      printf 'Starting dependency %s (CT %s)...\n' "$label" "$id"
      # What pct start leaves running, such as the DHCP client, must not keep the lock.
      pct start "$id" 9>&- || is_running "$id" || die "Could not start $label (CT $id)"
    else
      printf 'Dependency %s (CT %s) was already running.\n' "$label" "$id"
    fi

    elapsed=0
    while (( elapsed < timeout )); do
      if dependency_is_healthy "$id" "$healthcheck"; then
        printf 'Dependency %s (CT %s): ready.\n' "$label" "$id"
        break
      fi
      [[ $(pct status "$id" 2>/dev/null || true) == "status: running" ]] \
        || die "$label (CT $id) stopped while starting"
      sleep 2
      elapsed=$((elapsed + 2))
    done
    (( elapsed < timeout )) \
      || die "$label (CT $id) did not pass its health check within ${timeout}s"
  done < <(jq -r '.dependencies[] | @base64' "$config")
}

if [[ ${1:-} == "--install" ]]; then
  shift
  install_hook "$@"
  exit 0
fi
if [[ ${1:-} == "--refresh" ]]; then
  refresh_hooks
  exit 0
fi

vmid=${1:?missing VMID}
phase=${2:?missing lifecycle phase}
case "$phase" in
  pre-start) start_dependencies "$vmid" ;;
  post-start|pre-stop|post-stop) ;;
  *) die "Unknown lifecycle phase: $phase" ;;
esac
