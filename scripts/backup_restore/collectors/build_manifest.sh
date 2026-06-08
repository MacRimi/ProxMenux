#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest orchestrator
# ==========================================================
# Composes the six collectors into one manifest.json that
# validates against schema/manifest.schema.json. Designed to
# be called by backup_host.sh during a backup run. Read-only
# (no side effects on the host).
#
# Usage:
#   build_manifest.sh [--paths-archived <path1> <path2> ...]
#   build_manifest.sh --validate  (re-runs the JSON Schema validation)
#
# Stdout: pretty-printed manifest JSON.
# Stderr: progress + warnings.
# ==========================================================
set -euo pipefail

COLLECTORS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_FILE="$COLLECTORS_DIR/../schema/manifest.schema.json"

# Parse flags
paths_archived='null'
do_validate=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --paths-archived)
      shift
      tmp='[]'
      while [[ $# -gt 0 && "$1" != --* ]]; do
        tmp="$(jq --argjson a "$tmp" --arg p "$1" -n '$a + [$p]')"
        shift
      done
      paths_archived="$tmp"
      ;;
    --validate)
      do_validate=1; shift ;;
    -h|--help)
      sed -nE '/^# Usage:/,/^# Stderr:/p' "$0" | sed -E 's/^# ?//' >&2
      exit 0
      ;;
    *) shift ;;
  esac
done

# Run each collector. If a collector fails we fall back to a safe default
# (empty array / null object) and warn — the manifest is still useful even
# if one section is incomplete.
run_collector() {
  local name="$1" fallback="$2"
  local out
  if out="$(bash "$COLLECTORS_DIR/$name" 2>>/tmp/proxmenux-manifest-stderr.log)"; then
    printf '%s' "$out"
  else
    printf 'warning: collector %s failed; using fallback\n' "$name" >&2
    printf '%s' "$fallback"
  fi
}

# Empty error log first so we can attribute failures to this run.
: >/tmp/proxmenux-manifest-stderr.log

source_host="$(run_collector            collect_source_host.sh     '{}')"
hardware_inventory="$(run_collector     collect_hardware.sh        '{"gpu":[],"tpu":[],"nic":[],"wireless":[]}')"
storage_inventory="$(run_collector      collect_storage.sh         '{"zfs_pools":[],"lvm":{"vgs":[]},"physical_disks":[],"pve_storage_cfg":[],"mounts":[]}')"
installed_components="$(run_collector   collect_proxmenux_state.sh '[]')"
kernel_params="$(run_collector          collect_kernel.sh          '{"cmdline_extra":[],"modules_loaded_at_boot":[],"modprobe_d_files":[]}')"
guests="$(run_collector                 collect_guests.sh          '{"vms":[],"lxcs":[]}')"

created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Compose the final manifest. The wrapper key matches the schema:
# the top level is a single "proxmenux_backup_manifest" object.
manifest="$(jq -n \
  --arg created_at           "$created_at" \
  --arg created_by           "proxmenux-host-backup/1.3.0" \
  --argjson source_host      "$source_host" \
  --argjson hardware         "$hardware_inventory" \
  --argjson storage          "$storage_inventory" \
  --argjson components       "$installed_components" \
  --argjson kernel           "$kernel_params" \
  --argjson guests           "$guests" \
  --argjson paths_archived   "$paths_archived" \
  '{
    proxmenux_backup_manifest: {
      schema_version:                  1,
      created_at:                      $created_at,
      created_by:                      $created_by,
      source_host:                     $source_host,
      hardware_inventory:              $hardware,
      storage_inventory:               $storage,
      proxmenux_installed_components:  $components,
      kernel_params:                   $kernel,
      vms_lxcs_at_backup:              $guests,
      backup_metadata: {
        encrypted:          false,
        encryption_format:  null,
        compression:        "zstd",
        paths_archived:     $paths_archived,
        sha256_archive:     null,
        size_bytes:         null
      }
    }
  }')"

# Optional validation step. If python3 + jsonschema are available, run
# them; otherwise silently skip (validation is mostly a developer aid).
if [[ "$do_validate" == 1 ]]; then
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import jsonschema' 2>/dev/null; then
    printf '%s' "$manifest" | python3 -c "
import json, sys, jsonschema
schema = json.load(open('$SCHEMA_FILE'))
inst   = json.load(sys.stdin)
try:
    jsonschema.validate(instance=inst, schema=schema)
    print('manifest: validates against schema', file=sys.stderr)
except jsonschema.exceptions.ValidationError as e:
    print(f'manifest: SCHEMA VIOLATION at {list(e.absolute_path)}: {e.message}', file=sys.stderr)
    sys.exit(1)
"
  else
    printf 'manifest: jsonschema python module not present; skipping validation\n' >&2
  fi
fi

printf '%s\n' "$manifest"
