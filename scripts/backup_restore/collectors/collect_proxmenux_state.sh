#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest collector — proxmenux_installed_components
# ==========================================================
# Reads ProxMenux's managed_installs registry + post-install
# tools marker file and emits the installed components array.
# Read-only. Schema:
# scripts/backup_restore/schema/manifest.schema.json
# ==========================================================
set -euo pipefail

REGISTRY="/usr/local/share/proxmenux/managed_installs.json"
INSTALLED_TOOLS="/usr/local/share/proxmenux/installed_tools.json"

components='[]'

# ── managed_installs registry ──
# Each entry already carries the installer path under `menu_script`,
# so we trust the registry as the single source of truth. We skip LXC
# entries because containers are restored via vzdump, not via the
# host-config restore path.
if [[ -r "$REGISTRY" ]]; then
  while IFS= read -r item; do
    [[ -z "$item" ]] && continue
    id="$(printf '%s' "$item" | jq -r '.id')"
    type="$(printf '%s' "$item" | jq -r '.type // ""')"
    version="$(printf '%s' "$item" | jq -r '.current_version // ""')"
    # menu_script in the registry is null for components that handle their
    # own update lifecycle (e.g. OCI apps via the secure-gateway runtime).
    # We keep that null forward: restore won't try to reinstall those —
    # the user reconfigures them after restore.
    installer="$(printf '%s' "$item" | jq -r '.menu_script // ""')"

    components="$(jq --argjson acc "$components" \
      --arg id "$id" --arg type "$type" --arg version "$version" --arg installer "$installer" \
      -n '
      $acc + [{
        id:                  $id,
        type:                $type,
        version_at_backup:   (if $version   == "" then null else $version end),
        proxmenux_installer: (if $installer == "" then null else $installer end),
        applied_settings:    []
      }]
      ')"
  done < <(jq -c '.items[]? | select(.removed_at == null) | select(.type != "lxc")' "$REGISTRY" 2>/dev/null || true)
fi

# ── installed_tools.json (post-install optimizations) ──
# Format: array of {name: ..., installed_at: ...} or similar. The exact
# shape varies across ProxMenux versions; we emit one synthetic component
# named "post_install_optimizations" with the applied_settings list.
if [[ -r "$INSTALLED_TOOLS" ]]; then
  applied_settings="$(jq -c '
    if type == "object" then
      (.tools // .installed // [] | map(.name // .id // tostring))
    elif type == "array" then
      map(.name // .id // tostring)
    else []
    end
  ' "$INSTALLED_TOOLS" 2>/dev/null || echo '[]')"

  # Only emit if we have at least one applied setting — otherwise the
  # component would be noise.
  count="$(printf '%s' "$applied_settings" | jq 'length' 2>/dev/null || echo 0)"
  if [[ "${count:-0}" -gt 0 ]]; then
    components="$(jq --argjson acc "$components" --argjson s "$applied_settings" \
      -n '
      $acc + [{
        id:                  "post_install_optimizations",
        type:                "proxmenux_post_install",
        version_at_backup:   null,
        proxmenux_installer: "scripts/post_install/customizable_post_install.sh",
        applied_settings:    $s
      }]
      ')"
  fi
fi

# Output: bare array (not wrapped in an object — the orchestrator places
# this under .proxmenux_installed_components).
printf '%s\n' "$components"
