#!/usr/bin/env bash
# ==========================================================
# ProxMenux — list backup paths actually present in staging
# ==========================================================
# Reads <staging>/metadata/selected_paths.txt (the canonical
# record of WHICH paths went into this backup) and emits a JSON
# array of those that still exist under <staging>/rootfs/.
#
# This replaces the 13-component grouping used previously: the
# Custom restore checklist now shows one entry per real path
# (default profile + any operator-added extras), so what you
# backed up is exactly what you can restore.
#
# Usage:
#   list_paths.sh <staging-directory>
#
# Output: JSON array of paths with a leading slash, e.g.:
#   ["/etc/pve","/etc/network","/opt/mistuff"]
# ==========================================================
set -e

STAGING="${1:-}"
if [[ -z "$STAGING" || ! -d "$STAGING" ]]; then
  printf 'list_paths: usage: %s <staging-directory>\n' "$0" >&2
  exit 64
fi

SELECTED="$STAGING/metadata/selected_paths.txt"
ROOTFS="$STAGING/rootfs"

paths=()
if [[ -f "$SELECTED" ]]; then
  # The file stores paths without the leading slash (etc/pve,
  # var/lib/pve-cluster, ...). Filter to only those that are
  # actually present in the staged rootfs/ — anything in
  # missing_paths.txt at backup time would otherwise show up
  # here even though there's nothing to restore.
  while IFS= read -r rel; do
    [[ -z "$rel" ]] && continue
    rel="${rel#/}"
    if [[ -e "$ROOTFS/$rel" ]]; then
      paths+=("/$rel")
    fi
  done < "$SELECTED"
else
  # No selected_paths.txt sidecar — backup might be from a
  # pre-metadata era. Walk rootfs/ at depth 1-2 and use those
  # as the path list. Best-effort fallback.
  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    paths+=("/${entry#./}")
  done < <(cd "$ROOTFS" 2>/dev/null && find . -mindepth 1 -maxdepth 2 -print 2>/dev/null | sed 's|^\./||')
fi

# Emit JSON array — keep it dependency-free (no jq).
printf '['
first=1
for p in "${paths[@]}"; do
  esc="${p//\\/\\\\}"
  esc="${esc//\"/\\\"}"
  if (( first )); then
    printf '"%s"' "$esc"
    first=0
  else
    printf ',"%s"' "$esc"
  fi
done
printf ']\n'
