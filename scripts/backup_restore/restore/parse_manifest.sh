#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — manifest reader
# ==========================================================
# Reads the JSON manifest from a ProxMenux host backup. Supports:
#   - A loose manifest.json file path
#   - A backup archive (.tar.gz / .tar.zst / .tar)
#   - A pre-extracted backup directory
#
# Emits the manifest's `proxmenux_backup_manifest` sub-object as
# JSON to stdout (i.e. unwraps the top-level key) so downstream
# scripts can use `jq '.source_host'` directly. Exit 0 on success,
# non-zero with a message on stderr if the manifest can't be found.
#
# Usage:
#   parse_manifest.sh <archive-or-dir-or-manifest> [--with-wrapper]
#
# --with-wrapper keeps the outer { proxmenux_backup_manifest: { ... } }
#                wrap (useful when piping to jsonschema validation).
# ==========================================================
set -euo pipefail

SOURCE="${1:-}"
KEEP_WRAPPER=0
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-wrapper) KEEP_WRAPPER=1 ;;
  esac
  shift
done

if [[ -z "$SOURCE" ]]; then
  printf 'parse_manifest: missing source path\n' >&2
  exit 64
fi

# Locate the manifest. Three input shapes:
manifest_json=""
case "$SOURCE" in
  *.tar.gz|*.tgz|*.tar.zst|*.tar)
    # Archive — extract just the manifest entry to stdout. We tolerate
    # the manifest sitting at the root OR under any meta/ subdirectory.
    extractor=()
    case "$SOURCE" in
      *.tar.zst) extractor=(zstd -d --long=27 -c "$SOURCE") ;;
      *.tar.gz|*.tgz) extractor=(gzip -dc "$SOURCE") ;;
      *.tar) extractor=(cat "$SOURCE") ;;
    esac
    # Use --wildcards so the manifest is found at any depth. We extract
    # to stdout and stop at the first match.
    if ! manifest_json="$("${extractor[@]}" | tar -xO --wildcards '*manifest.json' 2>/dev/null | head -c 4194304)"; then
      printf 'parse_manifest: no manifest.json found inside %s\n' "$SOURCE" >&2
      exit 65
    fi
    ;;
  *)
    if [[ -f "$SOURCE" ]]; then
      manifest_json="$(cat "$SOURCE")"
    elif [[ -d "$SOURCE" ]]; then
      # Pre-extracted directory — try common paths first, then a search.
      for candidate in "$SOURCE/manifest.json" "$SOURCE/meta/manifest.json"; do
        if [[ -f "$candidate" ]]; then
          manifest_json="$(cat "$candidate")"; break
        fi
      done
      if [[ -z "$manifest_json" ]]; then
        found="$(find "$SOURCE" -maxdepth 3 -name 'manifest.json' -print -quit 2>/dev/null || true)"
        [[ -n "$found" ]] && manifest_json="$(cat "$found")"
      fi
      if [[ -z "$manifest_json" ]]; then
        printf 'parse_manifest: no manifest.json under %s\n' "$SOURCE" >&2
        exit 65
      fi
    else
      printf 'parse_manifest: %s is neither archive, dir, nor file\n' "$SOURCE" >&2
      exit 66
    fi
    ;;
esac

# Verify it's at least valid JSON before unwrapping.
if ! printf '%s' "$manifest_json" | jq -e 'type == "object"' >/dev/null 2>&1; then
  printf 'parse_manifest: contents are not a JSON object\n' >&2
  exit 67
fi

# Check the wrapper key is present.
if ! printf '%s' "$manifest_json" | jq -e '.proxmenux_backup_manifest' >/dev/null 2>&1; then
  printf 'parse_manifest: missing proxmenux_backup_manifest key (not a ProxMenux manifest?)\n' >&2
  exit 68
fi

if [[ "$KEEP_WRAPPER" == 1 ]]; then
  printf '%s' "$manifest_json"
else
  printf '%s' "$manifest_json" | jq '.proxmenux_backup_manifest'
fi
