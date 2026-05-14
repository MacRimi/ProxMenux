#!/usr/bin/env bash

# ==========================================================
# ProxMenux - ISO Storage Helpers
# ==========================================================
# Shared helpers for VM ISO selection. Proxmox identifies ISO media by
# volume ID (for example: local:iso/debian.iso or nas:iso/win11.iso);
# using the volid lets VMs boot ISOs stored on local, NFS, CIFS or any
# other storage that advertises content=iso.
# ==========================================================

ISO_FALLBACK_DIR="${ISO_FALLBACK_DIR:-/var/lib/vz/template/iso}"

iso_name_from_volid() {
  local volid="$1"
  local rel="${volid#*:}"
  basename "${rel#iso/}"
}

iso_storage_from_volid() {
  local volid="$1"
  echo "${volid%%:*}"
}

iso_volid_matches_filter() {
  local volid="$1"
  local filter="${2:-all}"
  local name lower

  name=$(iso_name_from_volid "$volid")
  lower=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
  [[ "$lower" == *.iso ]] || return 1

  case "$filter" in
    windows)
      [[ "$lower" != virtio*.iso ]]
      ;;
    virtio)
      [[ "$lower" == virtio*.iso ]]
      ;;
    all|*)
      return 0
      ;;
  esac
}

iso_path_to_volid() {
  local path="$1"
  local rest storage file

  case "$path" in
    /var/lib/vz/template/iso/*)
      echo "local:iso/$(basename "$path")"
      return 0
      ;;
    /mnt/pve/*/template/iso/*)
      rest="${path#/mnt/pve/}"
      storage="${rest%%/*}"
      file="$(basename "$path")"
      echo "${storage}:iso/${file}"
      return 0
      ;;
  esac

  return 1
}

iso_volid_to_path() {
  local volid="$1"
  local storage rel file path

  if command -v pvesm >/dev/null 2>&1; then
    path=$(pvesm path "$volid" 2>/dev/null || true)
    if [[ -n "$path" ]]; then
      echo "$path"
      return 0
    fi
  fi

  storage=$(iso_storage_from_volid "$volid")
  rel="${volid#*:}"
  file="$(basename "${rel#iso/}")"

  if [[ "$storage" == "local" ]]; then
    echo "/var/lib/vz/template/iso/$file"
  else
    echo "/mnt/pve/$storage/template/iso/$file"
  fi
}

iso_list_volids() {
  local filter="${1:-all}"
  local storage volid path
  local -a volids=()

  if command -v pvesm >/dev/null 2>&1; then
    while read -r storage; do
      [[ -z "$storage" ]] && continue
      while read -r volid; do
        [[ -z "$volid" ]] && continue
        if iso_volid_matches_filter "$volid" "$filter"; then
          volids+=("$volid")
        fi
      done < <(pvesm list "$storage" --content iso 2>/dev/null | awk 'NR>1 {print $1}')
    done < <(pvesm status -content iso 2>/dev/null | awk 'NR>1 && $3 == "active" {print $1}')
  fi

  if [[ ${#volids[@]} -eq 0 && -d "$ISO_FALLBACK_DIR" ]]; then
    while read -r path; do
      volid=$(iso_path_to_volid "$path" 2>/dev/null || true)
      [[ -z "$volid" ]] && continue
      if iso_volid_matches_filter "$volid" "$filter"; then
        volids+=("$volid")
      fi
    done < <(find "$ISO_FALLBACK_DIR" -maxdepth 1 -type f -iname "*.iso" | sort)
  fi

  [[ ${#volids[@]} -gt 0 ]] && printf '%s\n' "${volids[@]}" | sort -u
}

iso_human_size() {
  local path="$1"
  local bytes

  [[ -f "$path" ]] || { echo "-"; return 0; }

  if command -v du >/dev/null 2>&1; then
    du -h "$path" 2>/dev/null | awk '{print $1}'
    return 0
  fi

  bytes=$(wc -c < "$path" 2>/dev/null || echo "")
  [[ -n "$bytes" ]] && echo "${bytes}B" || echo "-"
}

iso_dialog_description() {
  local volid="$1"
  local name storage path size

  name=$(iso_name_from_volid "$volid")
  storage=$(iso_storage_from_volid "$volid")
  path=$(iso_volid_to_path "$volid")
  size=$(iso_human_size "$path")

  printf '%-42s │ %-14s │ %s' "$name" "$storage" "$size"
}
