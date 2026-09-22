#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from oci_ui import translate


def fail(message: str) -> None:
    raise SystemExit(message)


def resolve_path(rootfs: Path, candidates: list[str]) -> Path:
    rootfs = rootfs.resolve()
    for candidate in candidates:
        if not candidate.startswith("/") or "\x00" in candidate:
            fail(f"{translate('Invalid configuration path:')} {candidate!r}")
        resolved = (rootfs / candidate.lstrip("/")).resolve()
        if rootfs not in resolved.parents:
            fail(f"{translate('The path escapes the rootfs:')} {candidate}")
        if resolved.is_file():
            return resolved
    fail(translate("Jellyfin has not created encoding.xml in any declared path"))


def update_encoding(rootfs: Path, configuration: dict[str, object]) -> tuple[Path, bool]:
    path = resolve_path(rootfs, list(configuration.get("candidate_paths", [])))
    tree = ET.parse(path)
    root = tree.getroot()
    changed = False

    for tag, requested in dict(configuration.get("settings", {})).items():
        if not isinstance(requested, str):
            fail(f"{translate('The setting has no final value:')} {tag}")
        element = root.find(tag)
        if element is None:
            element = ET.SubElement(root, tag)
            changed = True
        if (element.text or "") != requested:
            element.text = requested
            changed = True

    for tag, requested_values in dict(configuration.get("lists", {})).items():
        if not isinstance(requested_values, list) or not all(
            isinstance(value, str) for value in requested_values
        ):
            fail(f"{translate('Invalid list:')} {tag}")
        element = root.find(tag)
        if element is None:
            element = ET.SubElement(root, tag)
            changed = True
        existing = [child.text or "" for child in list(element)]
        if existing != requested_values:
            for child in list(element):
                element.remove(child)
            for value in requested_values:
                ET.SubElement(element, "string").text = value
            changed = True

    if not changed:
        return path, False

    backup = path.with_name(f"{path.name}.bak-proxmenux")
    if not backup.exists():
        shutil.copy2(path, backup)
        os.chown(backup, path.stat().st_uid, path.stat().st_gid)

    stat = path.stat()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            tree.write(stream, encoding="utf-8", xml_declaration=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.st_mode)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path, True


def main() -> None:
    if len(sys.argv) != 3:
        fail(f"{translate('Usage:')} configure_jellyfin_encoding.py ROOTFS CONFIGURATION_JSON")
    rootfs = Path(sys.argv[1])
    configuration = json.loads(sys.argv[2])
    path, changed = update_encoding(rootfs, configuration)
    state = "updated" if changed else "already applied"
    print(f"Jellyfin configuration {state}: /{path.relative_to(rootfs.resolve())}")


if __name__ == "__main__":
    main()
