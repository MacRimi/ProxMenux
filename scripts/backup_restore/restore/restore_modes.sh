#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — mode presets
# ==========================================================
# Defines the five canonical restore modes. Each mode is a
# declarative filter over the manifest:
#
#   full          — restore everything from the backup
#   storage_only  — only PVE storages, ZFS pools, mounts
#   network_only  — only /etc/network, hostname, hosts, firewall
#   base          — full minus network (operator keeps current LAN)
#   custom        — pass-through; the caller decides paths/components
#
# Each mode takes the manifest on stdin and prints a plan JSON
# to stdout. The plan tells run_restore.sh which paths to extract,
# which components to reinstall, and whether to apply storage /
# network actions.
#
# Plan schema:
#   {
#     mode:                "full" | ... ,
#     paths_include:       [string, ...],   // paths to extract
#     paths_exclude:       [string, ...],   // paths to skip
#     components_include:  [string, ...],   // component ids to reinstall
#     storage_apply:       bool,
#     network_apply:       bool,
#     hostname_apply:      bool
#   }
#
# Usage as a library:
#   source restore_modes.sh
#   plan="$(mode_plan_full < manifest.json)"
#
# Usage as a CLI:
#   restore_modes.sh <mode> <manifest>
#
# Modes consume the manifest's paths_archived list — they don't
# invent paths. Anything you didn't archive can't be restored.
# ==========================================================
set -euo pipefail

# Paths that belong to the "network" concern, used by base/network_only
# modes. We match prefixes (e.g. /etc/network covers everything under it).
_NETWORK_PATH_PREFIXES=(
  "/etc/network"
  "/etc/hosts"
  "/etc/hostname"
  "/etc/resolv.conf"
  "/etc/pve/firewall"
  "/etc/pve/nodes"
  "/etc/pve/.members"
)

# Paths that belong to the "storage" concern.
_STORAGE_PATH_PREFIXES=(
  "/etc/pve/storage.cfg"
  "/etc/pve/priv/storage"
  "/etc/fstab"
  "/etc/iscsi"
  "/etc/multipath"
  "/etc/multipath.conf"
  "/etc/zfs"
  "/etc/lvm"
)

# Internal: returns 0 if $1 starts with any of the prefixes in the
# named array.
_path_matches_any() {
  local path="$1"; shift
  local prefix
  for prefix in "$@"; do
    case "$path" in
      "$prefix"|"$prefix"/*) return 0 ;;
    esac
  done
  return 1
}

# Internal: emit a JSON array of paths from paths_archived that pass the
# given path predicate function name.
_filter_paths() {
  local predicate="$1" manifest="$2"
  local out='[]'
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    if $predicate "$p"; then
      out="$(jq --argjson acc "$out" --arg p "$p" -n '$acc + [$p]')"
    fi
  done < <(printf '%s' "$manifest" | jq -r '.backup_metadata.paths_archived[]?')
  printf '%s' "$out"
}

_is_network_path()  { _path_matches_any "$1" "${_NETWORK_PATH_PREFIXES[@]}"; }
_is_storage_path()  { _path_matches_any "$1" "${_STORAGE_PATH_PREFIXES[@]}"; }
_is_not_network()   { ! _is_network_path "$1"; }

# Internal: emit the component-ids array, optionally filtered.
# Args:
#   $1 = manifest JSON
#   $2 = "all" | "none"
_components_for_mode() {
  local manifest="$1" policy="$2"
  case "$policy" in
    all)
      printf '%s' "$manifest" | jq '[.proxmenux_installed_components[]?.id]'
      ;;
    none)
      echo '[]'
      ;;
  esac
}

# Public: emit a plan JSON for the requested mode given the manifest
# on stdin or as $1.
emit_plan() {
  local mode="$1" manifest="$2"

  local include exclude components storage_apply network_apply hostname_apply

  case "$mode" in
    full)
      include="$(printf '%s' "$manifest" | jq '.backup_metadata.paths_archived // []')"
      exclude='[]'
      components="$(_components_for_mode "$manifest" all)"
      storage_apply=true; network_apply=true; hostname_apply=true
      ;;

    storage_only)
      include="$(_filter_paths _is_storage_path "$manifest")"
      exclude='[]'
      components='[]'
      storage_apply=true; network_apply=false; hostname_apply=false
      ;;

    network_only)
      include="$(_filter_paths _is_network_path "$manifest")"
      exclude='[]'
      components='[]'
      storage_apply=false; network_apply=true; hostname_apply=true
      ;;

    base)
      # everything except the network paths
      include="$(_filter_paths _is_not_network "$manifest")"
      # Explicitly enumerate excluded prefixes so the operator sees them
      exclude="$(printf '%s\n' "${_NETWORK_PATH_PREFIXES[@]}" | jq -R . | jq -s .)"
      components="$(_components_for_mode "$manifest" all)"
      storage_apply=true; network_apply=false; hostname_apply=false
      ;;

    custom)
      # Pass-through: include nothing, exclude nothing — caller fills in.
      include='[]'
      exclude='[]'
      components='[]'
      storage_apply=false; network_apply=false; hostname_apply=false
      ;;

    *)
      printf 'restore_modes: unknown mode "%s" (expected full|storage_only|network_only|base|custom)\n' "$mode" >&2
      return 64
      ;;
  esac

  jq -n \
    --arg mode "$mode" \
    --argjson include "$include" \
    --argjson exclude "$exclude" \
    --argjson components "$components" \
    --argjson storage_apply "$storage_apply" \
    --argjson network_apply "$network_apply" \
    --argjson hostname_apply "$hostname_apply" \
    '{
      mode:               $mode,
      paths_include:      $include,
      paths_exclude:      $exclude,
      components_include: $components,
      storage_apply:      $storage_apply,
      network_apply:      $network_apply,
      hostname_apply:     $hostname_apply
    }'
}

# Public: human-friendly label per mode, used by CLI/UI.
mode_label() {
  case "$1" in
    full)         echo "Full restore — apply everything from the backup" ;;
    storage_only) echo "Storage only — PVE storages, ZFS, fstab, iSCSI, multipath" ;;
    network_only) echo "Network only — interfaces, hosts, hostname, firewall" ;;
    base)         echo "Base (no network) — everything except network changes" ;;
    custom)       echo "Custom — operator picks paths and components manually" ;;
    *)            echo "Unknown mode" ;;
  esac
}

# CLI mode if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  MODE="${1:-}"
  SOURCE="${2:-}"
  if [[ -z "$MODE" || -z "$SOURCE" ]]; then
    cat <<EOF >&2
restore_modes.sh — restore mode preset definitions

Usage:
  restore_modes.sh <mode> <manifest-or-archive>

Modes:
  full          — $(mode_label full)
  storage_only  — $(mode_label storage_only)
  network_only  — $(mode_label network_only)
  base          — $(mode_label base)
  custom        — $(mode_label custom)
EOF
    exit 64
  fi

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  manifest="$(bash "$SCRIPT_DIR/parse_manifest.sh" "$SOURCE")"
  emit_plan "$MODE" "$manifest"
fi
