#!/bin/bash
# Canonical detection is shared with the Monitor; never infer PBS from a client package.
pmx_platform_field() {
    python3 "$(dirname "${BASH_SOURCE[0]}")/proxmox_platform.py" --field "$1"
}

pmx_is_pbs() {
    [[ "$(pmx_platform_field product)" == pbs ]]
}

# Only a host known to be PBS is refused: if the package list cannot be read,
# the PVE scripts keep working as they did before PBS support.
pmx_require_pve() {
    if pmx_is_pbs; then
        msg_error "$(translate 'This operation requires a Proxmox VE host. Use the PBS menu on Proxmox Backup Server.')"
        return 1
    fi
}
