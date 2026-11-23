"""Read native firewall data in an interpreter outside the Monitor's event loop."""

import json
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def collect(base, node_path, read):
    with ThreadPoolExecutor(max_workers=3) as pool:
        host_read = pool.submit(read, f'{node_path}/firewall/options', dict)
        guest_read = pool.submit(read, f'{base}/firewall/options', dict)
        cluster_read = pool.submit(read, '/cluster/firewall/options', dict)
        config_read = pool.submit(read, f'{base}/pending', list)
        host = host_read.result()
        nftables = host.get('nftables', 0) if host is not None else None
        value = {1: 'proxmox-firewall', '1': 'proxmox-firewall', 0: 'pve-firewall', '0': 'pve-firewall'}
        service = value.get(nftables) if isinstance(nftables, (int, str)) else None
        service_read = pool.submit(read, f'{node_path}/services/{service}/state', dict) if service else None
        return {
            'guest': guest_read.result(),
            'cluster': cluster_read.result(),
            'host': host,
            'config': config_read.result(),
            'service': service_read.result() if service_read else None,
        }


def _pvesh_read(path, expected_type):
    try:
        result = subprocess.run(['pvesh', 'get', path, '--output-format', 'json'],
                                capture_output=True, text=True, timeout=6, check=True)
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return data if isinstance(data, expected_type) else None


def read_overview(node, guest_type, vmid):
    if node == socket.gethostname().split('.', 1)[0]:
        helper = Path(__file__).with_name('guest_firewall_overview.pl')
        try:
            result = subprocess.run(['perl', str(helper), node, guest_type, vmid],
                                    capture_output=True, text=True, timeout=4, check=True)
            data = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            data = None
        types = {'guest': dict, 'host': dict, 'cluster': dict, 'config': list, 'service': dict}
        if (isinstance(data, dict) and data.keys() == types.keys() and isinstance(data['guest'], dict)
                and all(data[key] is None or isinstance(data[key], kind) for key, kind in types.items())):
            return data

    # Keep the supported CLI path for remote nodes and older PVE packages.
    node_path = f'/nodes/{node}'
    return collect(f'{node_path}/{guest_type}/{vmid}', node_path, _pvesh_read)


if __name__ == '__main__':
    node, guest_type, vmid = sys.argv[1:]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', node) or guest_type not in ('qemu', 'lxc') or not vmid.isdecimal():
        sys.exit(2)
    print(json.dumps(read_overview(node, guest_type, vmid)))
