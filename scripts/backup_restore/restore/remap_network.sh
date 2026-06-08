#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup restore — NIC remap by MAC
# ==========================================================
# Compares the manifest's NIC list (ifname + MAC + bridges) against
# the destination's current state and produces a remap table.
#
# Decision rules per NIC:
#   - MAC found on the SAME ifname        → keep (no action)
#   - MAC found on a DIFFERENT ifname     → rename or rewrite bridge config
#   - MAC NOT found at all                → orphan: bridge member needs
#                                            human decision
#   - Destination has a NIC not in manifest → new hardware: no action
#                                              needed for restore, but
#                                              operator may want to add
#                                              to a bridge afterwards
#
# Usage:
#   remap_network.sh <manifest-json-path-or-archive>
#
# Output: JSON {keep: [...], remap: [...], orphan: [...], new: [...]}.
# ==========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:-}"
[[ -z "$SOURCE" ]] && { printf 'remap_network: missing manifest source\n' >&2; exit 64; }

manifest="$(bash "$SCRIPT_DIR/parse_manifest.sh" "$SOURCE")"

# Snapshot destination NICs.
dest_nics='[]'
for dev_path in /sys/class/net/*; do
  ifname="$(basename "$dev_path")"
  case "$ifname" in
    lo|veth*|tap*|fwln*|fwbr*|fwpr*|vmbr*|bond*) continue ;;
  esac
  [[ -e "$dev_path/device" ]] || continue
  mac="$(cat "$dev_path/address" 2>/dev/null || true)"
  [[ -z "$mac" ]] && continue
  dest_nics="$(jq --argjson acc "$dest_nics" --arg n "$ifname" --arg m "$mac" \
    -n '$acc + [{ifname: $n, mac: $m}]')"
done

# Manifest NICs
manifest_nics="$(printf '%s' "$manifest" | jq -c '.hardware_inventory.nic // []')"

keep='[]'
remap='[]'
orphan='[]'

# Iterate manifest NICs
while IFS= read -r src_nic; do
  [[ -z "$src_nic" ]] && continue
  src_if="$(printf '%s' "$src_nic" | jq -r '.ifname')"
  src_mac="$(printf '%s' "$src_nic" | jq -r '.mac')"
  src_bridges="$(printf '%s' "$src_nic" | jq -c '.in_bridges // []')"

  # Look up the same MAC on destination
  match="$(printf '%s' "$dest_nics" | jq -c --arg m "$src_mac" '.[] | select(.mac == $m)' | head -1)"
  if [[ -z "$match" ]]; then
    # MAC not found at all → orphan
    orphan="$(jq --argjson acc "$orphan" \
      --arg if "$src_if" --arg mac "$src_mac" --argjson b "$src_bridges" \
      -n '$acc + [{
        source_ifname: $if,
        source_mac:    $mac,
        in_bridges:    $b
      }]')"
    continue
  fi
  dest_if="$(printf '%s' "$match" | jq -r '.ifname')"
  if [[ "$dest_if" == "$src_if" ]]; then
    keep="$(jq --argjson acc "$keep" \
      --arg if "$src_if" --arg mac "$src_mac" \
      -n '$acc + [{ifname: $if, mac: $mac}]')"
  else
    remap="$(jq --argjson acc "$remap" \
      --arg si "$src_if" --arg di "$dest_if" --arg mac "$src_mac" --argjson b "$src_bridges" \
      -n '$acc + [{
        source_ifname:      $si,
        destination_ifname: $di,
        mac:                $mac,
        in_bridges:         $b
      }]')"
  fi
done < <(printf '%s' "$manifest_nics" | jq -c '.[]')

# Destination NICs that weren't in the manifest at all → new hardware
manifest_macs="$(printf '%s' "$manifest_nics" | jq -r '.[].mac')"
new='[]'
while IFS= read -r dest_nic; do
  [[ -z "$dest_nic" ]] && continue
  dest_mac="$(printf '%s' "$dest_nic" | jq -r '.mac')"
  if ! printf '%s\n' "$manifest_macs" | grep -qFx "$dest_mac"; then
    new="$(jq --argjson acc "$new" --argjson n "$dest_nic" -n '$acc + [$n]')"
  fi
done < <(printf '%s' "$dest_nics" | jq -c '.[]')

jq -n \
  --argjson keep "$keep" \
  --argjson remap "$remap" \
  --argjson orphan "$orphan" \
  --argjson new "$new" \
  '{ keep: $keep, remap: $remap, orphan: $orphan, new: $new }'
