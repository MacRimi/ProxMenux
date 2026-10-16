#!/bin/bash
# Canonical detection is shared with the Monitor; never infer PBS from a client package.
pmx_platform_field() {
    python3 "$(dirname "${BASH_SOURCE[0]}")/proxmox_platform.py" --field "$1"
}

pmx_is_pbs() {
    [[ "$(pmx_platform_field product)" == pbs ]]
}

pmx_require_pve() {
    if [[ "$(pmx_platform_field product)" != pve ]]; then
        msg_error "$(translate 'This operation requires a Proxmox VE host. Use the PBS menu on Proxmox Backup Server.')"
        return 1
    fi
}
