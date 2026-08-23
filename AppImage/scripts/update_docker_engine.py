#!/usr/bin/env python3
"""Update only the Docker Engine stack inside one Proxmox LXC.

This intentionally does not run the community-scripts Docker updater:
that updater also performs a full apt/apk upgrade.  ProxMenux resolves a
small allow-list of Docker packages that are already installed and asks the
guest package manager to upgrade only those packages (and required
dependencies).  Static/manual installations without a supported package
manager fail closed instead of guessing how they were installed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


APT_PACKAGES = (
    "docker-ce",
    "docker-ce-cli",
    "docker-ce-rootless-extras",
    "docker-buildx-plugin",
    "docker-compose-plugin",
    "docker-model-plugin",
    "containerd.io",
    "docker.io",
    "docker-compose-v2",
    "docker-compose",
    "docker-buildx",
    "docker-cli",
    "containerd",
    "runc",
    "moby-engine",
    "moby-cli",
    "moby-buildx",
    "moby-compose",
    "moby-containerd",
)

APK_PACKAGES = (
    "docker",
    "docker-cli",
    "docker-openrc",
    "docker-cli-buildx",
    "docker-cli-compose",
    "docker-compose",
    "containerd",
    "runc",
)

RPM_PACKAGES = (
    "docker-ce",
    "docker-ce-cli",
    "docker-ce-rootless-extras",
    "docker-buildx-plugin",
    "docker-compose-plugin",
    "containerd.io",
    "moby-engine",
    "moby-cli",
    "moby-buildx",
    "moby-compose",
    "moby-containerd",
)


def pct(vmid: int, argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/sbin/pct", "exec", str(vmid), "--", *argv],
        text=True,
        capture_output=capture,
        check=False,
    )


def command_exists(vmid: int, name: str) -> bool:
    return pct(vmid, ["sh", "-c", f"command -v {name} >/dev/null 2>&1"]).returncode == 0


def docker_version(vmid: int) -> str:
    result = pct(vmid, ["docker", "version", "--format", "{{.Server.Version}}"], capture=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def apt_installed(vmid: int) -> list[str]:
    installed: list[str] = []
    for package in APT_PACKAGES:
        result = pct(
            vmid,
            ["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package],
            capture=True,
        )
        if result.returncode == 0 and result.stdout.startswith("ii"):
            installed.append(package)
    return installed


def apk_installed(vmid: int) -> list[str]:
    return [package for package in APK_PACKAGES if pct(vmid, ["apk", "info", "-e", package], capture=True).returncode == 0]


def rpm_installed(vmid: int) -> list[str]:
    return [package for package in RPM_PACKAGES if pct(vmid, ["rpm", "-q", package], capture=True).returncode == 0]


def resolve_method(vmid: int) -> tuple[str, list[str]]:
    if command_exists(vmid, "apt-get") and command_exists(vmid, "dpkg-query"):
        return "apt", apt_installed(vmid)
    if command_exists(vmid, "apk"):
        return "apk", apk_installed(vmid)
    if command_exists(vmid, "dnf") and command_exists(vmid, "rpm"):
        return "dnf", rpm_installed(vmid)
    if command_exists(vmid, "snap") and pct(vmid, ["snap", "list", "docker"], capture=True).returncode == 0:
        return "snap", ["docker"]
    return "unsupported", []


def run_update(vmid: int, method: str, packages: list[str]) -> int:
    if method == "apt":
        if pct(vmid, ["apt-get", "update"]).returncode != 0:
            return 1
        return pct(
            vmid,
            [
                "env",
                "DEBIAN_FRONTEND=noninteractive",
                "apt-get",
                "-y",
                "-o",
                "Dpkg::Options::=--force-confold",
                "install",
                "--only-upgrade",
                *packages,
            ],
        ).returncode
    if method == "apk":
        if pct(vmid, ["apk", "update"]).returncode != 0:
            return 1
        return pct(vmid, ["apk", "upgrade", "--no-cache", *packages]).returncode
    if method == "dnf":
        return pct(vmid, ["dnf", "-y", "upgrade", *packages]).returncode
    if method == "snap":
        return pct(vmid, ["snap", "refresh", "docker"]).returncode
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vmid", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.vmid <= 0:
        parser.error("--vmid must be a positive integer")

    before = docker_version(args.vmid)
    if not before:
        print("ERROR: Docker Engine is not running or was not detected in this container.", file=sys.stderr)
        return 2

    method, packages = resolve_method(args.vmid)
    if method == "unsupported" or not packages:
        print(
            "ERROR: Docker was detected, but no supported packaged installation was found. "
            "Configure a custom update command for this installation.",
            file=sys.stderr,
        )
        return 3

    print(f"Docker Engine before: {before}")
    print(f"Update method: {method}")
    print("Installed Docker stack: " + ", ".join(packages))
    if args.dry_run:
        print("Dry run: no packages were changed.")
        return 0

    print("--- Updating only the installed Docker Engine stack ---")
    if run_update(args.vmid, method, packages) != 0:
        print("ERROR: the Docker package update failed.", file=sys.stderr)
        return 4

    after = ""
    for _ in range(12):
        after = docker_version(args.vmid)
        if after:
            break
        time.sleep(1)
    if not after:
        print("ERROR: Docker did not become available again after the package update.", file=sys.stderr)
        return 5

    print(f"Docker Engine after:  {after}")
    if after == before:
        print("Docker Engine was already at the newest package version available.")
    else:
        print("Docker Engine updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
