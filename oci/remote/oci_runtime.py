#!/usr/bin/env python3
"""Resolve the effective OCI process after Compose runtime overrides."""

from __future__ import annotations

import json
import shlex
import sys
import tarfile
from pathlib import Path
from typing import Any

from oci_ui import translate


class RuntimeResolutionError(RuntimeError):
    pass


def _member(archive: tarfile.TarFile, name: str) -> tarfile.TarInfo:
    for item in archive.getmembers():
        if item.name.lstrip("./") == name:
            return item
    raise RuntimeResolutionError(f"{translate('Not found in the OCI archive:')} {name}")


def _json_member(archive: tarfile.TarFile, name: str) -> dict[str, Any]:
    source = archive.extractfile(_member(archive, name))
    if source is None:
        raise RuntimeResolutionError(f"{translate('Cannot read')} {name}")
    value = json.load(source)
    if not isinstance(value, dict):
        raise RuntimeResolutionError(f"{translate('Not a JSON object:')} {name}")
    return value


def _blob_name(digest: str) -> str:
    algorithm, separator, value = digest.partition(":")
    if separator != ":" or algorithm != "sha256" or len(value) != 64:
        raise RuntimeResolutionError(f"{translate('Unsupported OCI digest:')} {digest}")
    return f"blobs/sha256/{value}"


def image_entrypoint(archive_path: Path) -> list[str]:
    with tarfile.open(archive_path, mode="r:*") as archive:
        index = _json_member(archive, "index.json")
        manifests = index.get("manifests") or []
        if len(manifests) != 1:
            raise RuntimeResolutionError(translate("The OCI archive does not contain exactly one manifest"))
        manifest = _json_member(archive, _blob_name(str(manifests[0]["digest"])))
        config = _json_member(archive, _blob_name(str(manifest["config"]["digest"])))
    entrypoint = (config.get("config") or {}).get("Entrypoint") or []
    if isinstance(entrypoint, str):
        return [entrypoint]
    if not isinstance(entrypoint, list) or not all(isinstance(item, str) for item in entrypoint):
        raise RuntimeResolutionError(translate("Invalid OCI Entrypoint"))
    return entrypoint


def _arguments(value: Any, label: str) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise RuntimeResolutionError(f"{translate('The Compose value must be text or a list:')} {label}")


def effective_entrypoint(
    archive_path: Path,
    command: Any,
    compose_entrypoint: Any = None,
) -> str:
    entrypoint = (
        image_entrypoint(archive_path)
        if compose_entrypoint is None
        else _arguments(compose_entrypoint, "entrypoint")
    )
    if command is None:
        arguments: list[str] = []
    elif isinstance(command, str):
        arguments = shlex.split(command)
    elif isinstance(command, list) and all(isinstance(item, str) for item in command):
        arguments = command
    else:
        raise RuntimeResolutionError(f"{translate('The Compose value must be text or a list:')} command")
    process = entrypoint + arguments
    if not process:
        raise RuntimeResolutionError(translate("The Entrypoint/Cmd combination is empty"))
    return " ".join(shlex.quote(item) for item in process)


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(
            f"{translate('Usage:')} {sys.argv[0]} OCI_ARCHIVE COMMAND_JSON [ENTRYPOINT_JSON]",
            file=sys.stderr,
        )
        return 2
    try:
        command = json.loads(sys.argv[2])
        compose_entrypoint = json.loads(sys.argv[3]) if len(sys.argv) == 4 else None
        print(effective_entrypoint(Path(sys.argv[1]), command, compose_entrypoint))
    except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError, RuntimeResolutionError) as exc:
        print(f"{translate('Cannot apply the Compose command:')} {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
