#!/usr/bin/env python3
"""Resolve the effective OCI process after Compose runtime overrides."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
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


def _layer_entries(archive: tarfile.TarFile, descriptor: dict[str, Any]):
    """Names in one image layer, decompressed as its media type says."""
    member = _member(archive, _blob_name(str(descriptor["digest"])))
    source = archive.extractfile(member)
    if source is None:
        raise RuntimeResolutionError(f"{translate('Cannot read')} {member.name}")
    media = str(descriptor.get("mediaType", ""))
    if "zstd" in media:
        process = subprocess.Popen(["zstd", "-dc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        feeder = threading.Thread(target=lambda: (shutil.copyfileobj(source, process.stdin), process.stdin.close()),
                                  daemon=True)
        feeder.start()
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as layer:
                for item in layer:
                    yield item
        finally:
            process.stdout.close()
            process.wait()
            feeder.join()
        return
    with tarfile.open(fileobj=source, mode="r|gz" if "gzip" in media else "r|") as layer:
        for item in layer:
            yield item


def missing_user_databases(archive_path: Path) -> list[str]:
    """Files Proxmox needs to resolve the image User, absent from its rootfs.

    Proxmox VE resolves a User through /etc/passwd and /etc/group inside the
    image, even a numeric one, and refuses to create the container without
    them. An image built from scratch often has neither."""
    with tarfile.open(archive_path, mode="r:*") as archive:
        index = _json_member(archive, "index.json")
        manifests = index.get("manifests") or []
        if len(manifests) != 1:
            raise RuntimeResolutionError(translate("The OCI archive does not contain exactly one manifest"))
        manifest = _json_member(archive, _blob_name(str(manifests[0]["digest"])))
        config = _json_member(archive, _blob_name(str(manifest["config"]["digest"])))
        if not (config.get("config") or {}).get("User"):
            return []
        state = {"etc/passwd": None, "etc/group": None}
        # The topmost layer that names a path decides whether it exists.
        for descriptor in reversed(manifest.get("layers") or []):
            pending = [path for path, found in state.items() if found is None]
            if not pending:
                break
            names = {item.name.removeprefix("./").strip("/") for item in _layer_entries(archive, descriptor)}
            for path in pending:
                folder, _, leaf = path.rpartition("/")
                if path in names:
                    state[path] = True
                elif (f"{folder}/.wh.{leaf}" in names or f"{folder}/.wh..wh..opq" in names
                      or f".wh.{folder}" in names):
                    state[path] = False
        return ["/" + path for path, found in state.items() if not found]


USER_DATABASES = {
    "etc/passwd": b"root:x:0:0:root:/root:/sbin/nologin\n",
    "etc/group": b"root:x:0:\n",
}


def _tar_entry(name: str, kind: bytes, mode: int, size: int = 0) -> tarfile.TarInfo:
    entry = tarfile.TarInfo(name)
    entry.type, entry.mode, entry.size = kind, mode, size
    entry.uid = entry.gid = entry.mtime = 0
    entry.uname = entry.gname = "root"
    return entry


def add_user_databases(source: Path, destination: Path) -> list[str]:
    """Copy of an image with a top layer that adds the /etc/passwd and
    /etc/group it lacks, holding only root.

    Only a numeric User is resolved this way: Proxmox VE then applies the
    UID and GID as given, as Docker does for a user absent from the image."""
    missing = missing_user_databases(source)
    if not missing:
        return []
    with tarfile.open(source, mode="r:*") as archive:
        index = _json_member(archive, "index.json")
        manifest_descriptor = (index.get("manifests") or [{}])[0]
        manifest = _json_member(archive, _blob_name(str(manifest_descriptor["digest"])))
        config = _json_member(archive, _blob_name(str(manifest["config"]["digest"])))
        user = str((config.get("config") or {}).get("User", ""))
        if not all(part.isdigit() for part in user.split(":", 1)):
            raise RuntimeResolutionError(translate("The image user is not numeric:") + " " + user)

        layer = io.BytesIO()
        with tarfile.open(fileobj=layer, mode="w", format=tarfile.PAX_FORMAT) as files:
            files.addfile(_tar_entry("etc", tarfile.DIRTYPE, 0o755))
            for path in missing:
                body = USER_DATABASES[path.lstrip("/")]
                files.addfile(_tar_entry(path.lstrip("/"), tarfile.REGTYPE, 0o644, len(body)), io.BytesIO(body))
        blobs: dict[str, bytes] = {}

        def blob(data: bytes) -> dict[str, Any]:
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            blobs[digest] = data
            return {"digest": digest, "size": len(data)}

        layer_data = layer.getvalue()
        docker = "docker" in str(manifest.get("mediaType", ""))
        layer_descriptor = blob(layer_data)
        layer_descriptor["mediaType"] = ("application/vnd.docker.image.rootfs.diff.tar" if docker
                                         else "application/vnd.oci.image.layer.v1.tar")
        config.setdefault("rootfs", {"type": "layers", "diff_ids": []}).setdefault("diff_ids", []).append(
            layer_descriptor["digest"])
        if isinstance(config.get("history"), list):
            config["history"].append({"created_by": "ProxMenux: " + " ".join(missing) + " for Proxmox VE"})
        manifest["layers"] = list(manifest.get("layers") or []) + [layer_descriptor]
        manifest["config"] = {**manifest["config"], **blob(json.dumps(config).encode())}
        index["manifests"] = [{**manifest_descriptor, **blob(json.dumps(manifest).encode())}]
        index_data = json.dumps(index).encode()

        partial = destination.with_name(destination.name + ".partial")
        try:
            with tarfile.open(partial, mode="w", format=tarfile.PAX_FORMAT) as output:
                for member in archive:
                    if member.name.removeprefix("./") == "index.json":
                        continue
                    output.addfile(member, archive.extractfile(member) if member.isfile() else None)
                for digest, data in blobs.items():
                    output.addfile(_tar_entry(_blob_name(digest), tarfile.REGTYPE, 0o644, len(data)), io.BytesIO(data))
                output.addfile(_tar_entry("index.json", tarfile.REGTYPE, 0o644, len(index_data)),
                               io.BytesIO(index_data))
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
    return missing


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


def home_directory(passwd_path: Path, uid: int) -> str | None:
    """Read a regular image passwd file; only an absent UID defaults to /."""
    if uid < 0:
        return None
    # The caller supplies <mounted rootfs>/etc/passwd. Pin etc so an image
    # symlink or a rename during lookup cannot redirect the host-side read.
    directory = os.open(passwd_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.stat(passwd_path.name, dir_fd=directory, follow_symlinks=False).st_mode):
            return None
        descriptor = os.open(
            passwd_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory,
        )
        try:
            # Recheck the opened object, not its name; a FIFO replacement
            # must neither block open() nor reach a read operation.
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return None
            with os.fdopen(descriptor, encoding="utf-8", closefd=False) as stream:
                content = stream.read()
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    for line in content.splitlines():
        fields = line.split(":")
        if len(fields) < 3 or fields[2] != str(uid):
            continue
        if len(fields) != 7:
            return None
        home = fields[5]
        safe = home.startswith("/") and not any(ord(char) < 32 or ord(char) == 127 for char in home)
        return home if safe else None
    return "/"


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--home":
        try:
            uid = int(sys.argv[3])
            home = home_directory(Path(sys.argv[2]), uid)
        except (OSError, ValueError) as exc:
            print(f"{translate('Cannot resolve the container home directory:')} {exc}", file=sys.stderr)
            return 1
        if home is None:
            return 1
        print(home)
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--user-databases":
        try:
            missing = missing_user_databases(Path(sys.argv[2]))
        except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError, RuntimeResolutionError) as exc:
            print(f"{translate('Cannot read the OCI archive:')} {exc}", file=sys.stderr)
            return 1
        if missing:
            print(" ".join(missing))
            return 3
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "--add-user-databases":
        try:
            print(" ".join(add_user_databases(Path(sys.argv[2]), Path(sys.argv[3]))))
        except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError, RuntimeResolutionError) as exc:
            print(f"{translate('Cannot prepare the OCI archive:')} {exc}", file=sys.stderr)
            return 1
        return 0
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
