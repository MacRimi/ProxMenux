#!/usr/bin/env python3
"""Safely recreate one standalone Docker container inside an LXC.

The container's create-time Config/HostConfig is read from Docker's API,
the referenced image is pulled, and a replacement is validated before the
old container is removed. If create/start/validation fails, the original
container name and running state are restored.

Compose-owned containers are deliberately rejected: their declarative
project is the authoritative and safer update path.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def pct_exec(vmid: int, argv: list[str], *, input_text: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/usr/sbin/pct", "exec", str(vmid), "--", *argv],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def checked(vmid: int, argv: list[str], *, input_text: str | None = None, timeout: int = 300) -> str:
    result = pct_exec(vmid, argv, input_text=input_text, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"{' '.join(argv[:3])}: {detail}")
    return result.stdout or ""


def inspect_one(vmid: int, name: str) -> dict:
    payload = json.loads(checked(vmid, ["docker", "inspect", name], timeout=30))
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError("docker inspect returned an unexpected response")
    return payload[0]


def create_payload(inspect: dict, image: str) -> dict:
    config = dict(inspect.get("Config") or {})
    config["Image"] = image
    host_config = dict(inspect.get("HostConfig") or {})
    if host_config.get("AutoRemove"):
        raise RuntimeError("containers with AutoRemove cannot be recreated safely")

    endpoints: dict[str, dict] = {}
    for network_name, endpoint in ((inspect.get("NetworkSettings") or {}).get("Networks") or {}).items():
        if not NAME_RE.match(str(network_name)):
            continue
        # Preserve names/aliases and driver options, but deliberately let
        # Docker allocate a fresh IP while the stopped rollback container
        # still owns its old endpoint.
        target: dict = {}
        for key in ("Aliases", "Links", "DriverOpts"):
            if endpoint.get(key) is not None:
                target[key] = endpoint[key]
        endpoints[str(network_name)] = target

    return {
        **config,
        "HostConfig": host_config,
        "NetworkingConfig": {"EndpointsConfig": endpoints},
    }


def api_create(vmid: int, name: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"))
    result = pct_exec(
        vmid,
        [
            "curl", "--silent", "--show-error", "--fail-with-body",
            "--unix-socket", "/var/run/docker.sock",
            "-H", "Content-Type: application/json",
            "-X", "POST", "--data-binary", "@-",
            f"http://localhost/v1.41/containers/create?name={name}",
        ],
        input_text=body,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Docker create API failed").strip())
    response = json.loads(result.stdout or "{}")
    container_id = str(response.get("Id") or "")
    if not container_id:
        raise RuntimeError(str(response.get("message") or "Docker create API returned no container id"))
    return container_id


def recreate(vmid: int, name: str) -> None:
    original = inspect_one(vmid, name)
    labels = ((original.get("Config") or {}).get("Labels") or {})
    if labels.get("com.docker.compose.project"):
        raise RuntimeError("container belongs to Docker Compose; use its project update action")
    image = str((original.get("Config") or {}).get("Image") or "").strip()
    if not image:
        raise RuntimeError("container has no reusable image reference")
    was_running = bool((original.get("State") or {}).get("Running"))
    backup_name = f"{name}.proxmenux-rollback-{int(time.time())}"
    replacement_created = False

    print(f"=== Docker protected recreation: CT {vmid} / {name} ===", flush=True)
    print(f"Image: {image}", flush=True)
    print("Pulling the referenced image…", flush=True)
    pull = pct_exec(vmid, ["docker", "pull", image], timeout=1800)
    if pull.stdout:
        print(pull.stdout.rstrip(), flush=True)
    if pull.returncode != 0:
        raise RuntimeError((pull.stderr or "docker pull failed").strip())

    payload = create_payload(original, image)
    try:
        if was_running:
            print("Stopping the original container…", flush=True)
            checked(vmid, ["docker", "stop", "--time", "30", name], timeout=60)
        print(f"Keeping rollback container as {backup_name}…", flush=True)
        checked(vmid, ["docker", "rename", name, backup_name], timeout=30)

        print("Creating replacement from the inspected configuration…", flush=True)
        api_create(vmid, name, payload)
        replacement_created = True
        if was_running:
            checked(vmid, ["docker", "start", name], timeout=60)
            deadline = time.time() + 20
            while True:
                state = inspect_one(vmid, name).get("State") or {}
                if not state.get("Running"):
                    raise RuntimeError(str(state.get("Error") or "replacement stopped during validation"))
                health = ((state.get("Health") or {}).get("Status") or "").lower()
                if health == "unhealthy":
                    raise RuntimeError("replacement healthcheck is unhealthy")
                if health != "starting" or time.time() >= deadline:
                    break
                time.sleep(2)

        print("Replacement validated; removing rollback container…", flush=True)
        checked(vmid, ["docker", "rm", "-f", backup_name], timeout=60)
        print("Docker container recreation completed successfully.", flush=True)
    except Exception:
        print("Recreation failed; restoring the original container…", file=sys.stderr, flush=True)
        if replacement_created:
            pct_exec(vmid, ["docker", "rm", "-f", name], timeout=60)
        pct_exec(vmid, ["docker", "rename", backup_name, name], timeout=30)
        if was_running:
            pct_exec(vmid, ["docker", "start", name], timeout=60)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vmid", required=True, type=int)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    if args.vmid <= 0 or not NAME_RE.match(args.container):
        parser.error("invalid VMID or container name")
    try:
        recreate(args.vmid, args.container)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
