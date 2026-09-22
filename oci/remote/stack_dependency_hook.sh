#!/usr/bin/env bash
set -Eeuo pipefail

PATH=/usr/sbin:/usr/bin:/sbin:/bin

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
  [[ -n $storage ]] || die "No active storage supports snippets"
  printf '%s' "$storage"
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
      (.healthcheck.type | IN("exec", "http", "running")) and
      (.healthcheck.timeout_seconds | type == "number")
    ))
  ' "$source_config" >/dev/null || die "Invalid dependency contract"

  storage=$(find_snippet_storage)
  hook_volume="${storage}:snippets/proxmenux-stack-dependencies.sh"
  hook_path=$(pvesm path "$hook_volume")
  install -D -m 0755 "$0" "$hook_path"

  target_config="/etc/pve/priv/proxmenux-stack-${main_id}.json"
  umask 077
  cat "$source_config" >"$target_config"
  pct set "$main_id" --hookscript "$hook_volume" >/dev/null
  printf 'Proxmox hookscript installed: CT %s starts its dependencies through %s\n' \
    "$main_id" "$hook_volume"
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
      pct exec "$id" -- "${command[@]}" >/dev/null 2>&1
      ;;
    http)
      url=$(jq -r '.url' <<<"$healthcheck")
      curl -fsS --max-time 3 "$url" >/dev/null 2>&1
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

    if [[ $(pct status "$id" 2>/dev/null || true) != "status: running" ]]; then
      printf 'Starting dependency %s (CT %s)...\n' "$label" "$id"
      pct start "$id" || die "Could not start $label (CT $id)"
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

vmid=${1:?missing VMID}
phase=${2:?missing lifecycle phase}
case "$phase" in
  pre-start) start_dependencies "$vmid" ;;
  post-start|pre-stop|post-stop) ;;
  *) die "Unknown lifecycle phase: $phase" ;;
esac
