#!/usr/bin/env bash
# ==========================================================
# ProxMenux backup manifest collector — hardware_inventory
# ==========================================================
# Detects GPUs (with vendor → ProxMenux installer mapping),
# TPUs (Coral PCIe/USB), NICs (with bridge membership), and
# Wireless interfaces. Read-only. Schema:
# scripts/backup_restore/schema/manifest.schema.json
# ==========================================================
set -euo pipefail

# Vendor → installer path mapping. Update when ProxMenux adds new
# installers for hardware that depends on out-of-tree drivers.
# Vendors WITHOUT a mapping get null (e.g. Intel/AMD iGPUs work with
# in-tree drivers, no special installer needed).
gpu_installer_for() {
  case "$1" in
    NVIDIA) echo "scripts/gpu_tpu/nvidia_installer.sh" ;;
    *)      echo "" ;;
  esac
}

# ── GPUs ──
# lspci -nnD outputs:
#   0000:01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GP107GL [Quadro P620] [10de:1cb6] (rev a1)
# We pick anything classified as VGA/3D/Display (display controllers).
gpu_array='[]'
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  pci_address="$(printf '%s' "$line" | awk '{print $1}')"
  pci_id="$(printf '%s' "$line" | grep -oE '\[[0-9a-f]{4}:[0-9a-f]{4}\]' | tail -1 | tr -d '[]')"
  # Description: everything between the "controller]:" header and the
  # final "[pci_id]" tag. For AMD this includes the [AMD/ATI] tag; for
  # NVIDIA/Intel it's just vendor + model.
  desc="$(printf '%s' "$line" | sed -nE "s@.*\]:[[:space:]]*(.*)[[:space:]]+\[[0-9a-f]{4}:[0-9a-f]{4}\].*@\1@p")"

  # Vendor classification
  case "$desc" in
    *NVIDIA*)                          vendor="NVIDIA" ;;
    *"Advanced Micro Devices"*|*AMD*)  vendor="AMD" ;;
    *"Intel Corporation"*|*Intel*)     vendor="Intel" ;;
    *)                                  vendor="Other" ;;
  esac

  # Model: strip every known vendor prefix from desc. Order matters —
  # the longest specific prefix (AMD's "Inc. [AMD/ATI]") must come before
  # the generic short one.
  model="$(printf '%s' "$desc" | sed -E '
    s/^Advanced Micro Devices, Inc\. \[AMD\/ATI\][[:space:]]+//
    s/^Advanced Micro Devices(, Inc\.)?[[:space:]]+//
    s/^NVIDIA Corporation[[:space:]]+//
    s/^Intel Corporation[[:space:]]+//
    s/[[:space:]]+$//
  ')"
  # Kernel driver in use (may be empty if module not loaded yet)
  kernel_driver="$(lspci -nnks "$pci_address" 2>/dev/null | awk -F: '/Kernel driver in use/{sub(/^[ \t]+/,"",$2); print $2; exit}')"
  # Passthrough eligible if the GPU is bound to vfio-pci OR it's a discrete
  # secondary GPU (not the primary console). Pragmatic heuristic: discrete
  # GPUs are usually eligible; iGPUs (Intel HD/UHD, AMD APU iGPUs) usually not
  # because they drive the host console.
  passthrough_eligible=false
  case "$kernel_driver" in
    vfio-pci) passthrough_eligible=true ;;
    nvidia|nouveau) passthrough_eligible=true ;;  # discrete by definition
  esac

  # ProxMenux installer for this GPU vendor
  proxmenux_installer="$(gpu_installer_for "$vendor")"

  # Installed driver version from the managed_installs registry
  installed_driver_version=""
  if [[ "$vendor" == "NVIDIA" ]] && [[ -f /usr/local/share/proxmenux/managed_installs.json ]]; then
    installed_driver_version="$(jq -r '
      .items[]
      | select(.removed_at == null and .type == "nvidia_xfree86")
      | .current_version // ""
    ' /usr/local/share/proxmenux/managed_installs.json 2>/dev/null | head -1)"
  fi

  gpu_array="$(jq --argjson acc "$gpu_array" \
    --arg vendor "$vendor" \
    --arg model "$model" \
    --arg pci_address "$pci_address" \
    --arg pci_id "$pci_id" \
    --arg kernel_driver "$kernel_driver" \
    --argjson passthrough_eligible "$passthrough_eligible" \
    --arg proxmenux_installer "$proxmenux_installer" \
    --arg installed_driver_version "$installed_driver_version" \
    -n '
    $acc + [{
      vendor:                   $vendor,
      model:                    $model,
      pci_address:              $pci_address,
      pci_id:                   $pci_id,
      kernel_driver:            (if $kernel_driver == "" then null else $kernel_driver end),
      passthrough_eligible:     $passthrough_eligible,
      proxmenux_installer:      (if $proxmenux_installer == "" then null else $proxmenux_installer end),
      installed_driver_version: (if $installed_driver_version == "" then null else $installed_driver_version end)
    }]
    ')"
done < <(lspci -nnD 2>/dev/null | grep -E 'VGA compatible|3D controller|Display controller' || true)

# ── TPUs (Google Coral) ──
# PCIe variant: vendor 1ac1 (Global Unichip Corp) is the Coral M.2 / mPCIe.
# USB variant:  vendor 18d1 product 9302 (Google).
tpu_array='[]'

# PCIe Coral
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  pci_address="$(printf '%s' "$line" | awk '{print $1}')"
  pci_id="$(printf '%s' "$line" | grep -oE '\[[0-9a-f]{4}:[0-9a-f]{4}\]' | tail -1 | tr -d '[]')"
  tpu_array="$(jq --argjson acc "$tpu_array" \
    --arg model "Coral PCIe" \
    --arg pci_address "$pci_address" \
    -n '
    $acc + [{
      vendor:              "Google",
      model:               $model,
      bus:                 "PCIe",
      pci_address:         $pci_address,
      proxmenux_installer: "scripts/gpu_tpu/install_coral.sh",
      installed_version:   null
    }]
    ')"
done < <(lspci -nnD 2>/dev/null | grep -iE '1ac1:|global unichip' || true)

# USB Coral
if command -v lsusb >/dev/null 2>&1; then
  if lsusb 2>/dev/null | grep -qE '18d1:9302|Google.*Coral'; then
    tpu_array="$(jq --argjson acc "$tpu_array" \
      -n '
      $acc + [{
        vendor:              "Google",
        model:               "Coral USB",
        bus:                 "USB",
        pci_address:         null,
        proxmenux_installer: "scripts/gpu_tpu/install_coral.sh",
        installed_version:   null
      }]
      ')"
  fi
fi

# ── NICs ──
# We want PHYSICAL interfaces (skip lo, veth*, tap*, fwln*, fwbr*, fwpr*).
# Also distinguish wired from wireless.
nic_array='[]'
wireless_array='[]'

# Map each interface → its bridge by walking /sys/class/net/<bridge>/brif/.
# We use bash glob expansion instead of `find -path` because find doesn't
# follow the symlinks under /sys cleanly.
declare -A bridge_for
for brif_dir in /sys/class/net/*/brif; do
  [[ -d "$brif_dir" ]] || continue
  bridge="$(basename "$(dirname "$brif_dir")")"
  for member_link in "$brif_dir"/*; do
    [[ -e "$member_link" ]] || continue
    member="$(basename "$member_link")"
    bridge_for["$member"]="$bridge"
  done
done

# Iterate over each physical net device
for dev_path in /sys/class/net/*; do
  ifname="$(basename "$dev_path")"
  case "$ifname" in
    lo|veth*|tap*|fwln*|fwbr*|fwpr*|vmbr*|bond*) continue ;;
  esac
  # Bridges and bonds we record as their own thing; PHY interfaces only here.
  # Detect virtual interfaces (no device symlink → virtual)
  [[ ! -e "$dev_path/device" ]] && continue

  mac="$(cat "$dev_path/address" 2>/dev/null || echo "")"
  [[ -z "$mac" ]] && continue
  operstate="$(cat "$dev_path/operstate" 2>/dev/null | tr '[:lower:]' '[:upper:]' || echo "UNKNOWN")"
  case "$operstate" in
    UP|DOWN) ;;
    *) operstate="UNKNOWN" ;;
  esac
  kernel_driver="$(basename "$(readlink "$dev_path/device/driver" 2>/dev/null || echo "")")"

  # Wireless detection
  if [[ -d "$dev_path/wireless" ]] || [[ -d "$dev_path/phy80211" ]]; then
    wireless_array="$(jq --argjson acc "$wireless_array" \
      --arg ifname "$ifname" \
      --arg mac "$mac" \
      -n '$acc + [{ifname: $ifname, mac: $mac}]')"
    continue
  fi

  # Bridge membership: which vmbr* contains this NIC?
  in_bridges_json='[]'
  if [[ -n "${bridge_for[$ifname]:-}" ]]; then
    in_bridges_json="$(jq -n --arg b "${bridge_for[$ifname]}" '[$b]')"
  fi

  nic_array="$(jq --argjson acc "$nic_array" \
    --arg ifname "$ifname" \
    --arg mac "$mac" \
    --arg kernel_driver "$kernel_driver" \
    --argjson in_bridges "$in_bridges_json" \
    --arg operstate "$operstate" \
    -n '
    $acc + [{
      ifname:        $ifname,
      mac:           $mac,
      kernel_driver: (if $kernel_driver == "" then null else $kernel_driver end),
      in_bridges:    $in_bridges,
      operstate:     $operstate
    }]
    ')"
done

# Compose the final object
jq -n \
  --argjson gpu "$gpu_array" \
  --argjson tpu "$tpu_array" \
  --argjson nic "$nic_array" \
  --argjson wireless "$wireless_array" \
  '{ gpu: $gpu, tpu: $tpu, nic: $nic, wireless: $wireless }'
