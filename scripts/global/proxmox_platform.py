"""Shared PVE/PBS platform detection for the menus and the Monitor (stdlib only)."""

import argparse
import json
from pathlib import Path
import re
import subprocess

OS_RELEASE = Path("/etc/os-release")
SUPPORTED = {("pve", 8): "bookworm", ("pve", 9): "trixie",
             ("pbs", 3): "bookworm", ("pbs", 4): "trixie"}
# Downstream builds keep the upstream package names and versions; only a few
# rebuilt packages carry a marker (PXVIRT: `9.0.4+pxvirt1`, `10.0.2-4+port1`).
VARIANT_PACKAGES = ("proxmox-kernel-helper", "pve-qemu-kvm")
VARIANT_MARKERS = {re.compile(r"\+pxvirt|\+port\d*$"): "pxvirt"}


def detect_platform():
    codename = ""
    try:
        match = re.search(r'^VERSION_CODENAME=["\']?([a-z0-9-]+)', OS_RELEASE.read_text(), re.M)
        codename = match.group(1) if match else ""
    except OSError:
        pass
    installed = {}
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}\t${Status}\t${Version}\n",
             "pve-manager", "proxmox-backup-server", *VARIANT_PACKAGES],
            capture_output=True, text=True, timeout=5,
        )
        # dpkg returns nonzero if ONE requested package is missing; its other
        # installed rows remain authoritative. A PBS client alone is not PBS.
        for line in result.stdout.splitlines():
            columns = line.split("\t")
            if len(columns) == 3 and columns[1] == "install ok installed":
                installed[columns[0]] = columns[2]
    except (OSError, subprocess.TimeoutExpired):
        pass
    variant = ""
    for package in VARIANT_PACKAGES:
        for marker, name in VARIANT_MARKERS.items():
            if marker.search(installed.get(package, "")):
                variant = name
    for package, product in (("pve-manager", "pve"), ("proxmox-backup-server", "pbs")):
        version = installed.get(package, "")
        match = re.fullmatch(r"(?:[0-9]+:)?([0-9]+)\.[0-9]+(?:\.[0-9]+)?(?:[-+~.a-zA-Z0-9]*)", version)
        if match:
            major = int(match.group(1))
            return {"product": product, "version": version, "major": major, "variant": variant,
                    "codename": codename, "supported": SUPPORTED.get((product, major)) == codename}
    return {"product": "unknown", "version": None, "major": None, "variant": variant,
            "codename": codename, "supported": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--field", choices=("product", "version", "major", "variant", "codename", "supported"))
    arguments = parser.parse_args()
    data = detect_platform()
    value = data.get(arguments.field) if arguments.field else data
    print(value if isinstance(value, str) else json.dumps(value))


if __name__ == "__main__":
    main()
