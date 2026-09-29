#!/usr/bin/env python3
"""Verify blob digests and gzip integrity in an OCI image archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tarfile
import zlib
from pathlib import Path

from oci_ui import log, translate


CHUNK_SIZE = 4 * 1024 * 1024
PROGRESS_STEP = 128 * 1024 * 1024


class VerificationError(RuntimeError):
    pass


def human_mib(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MiB"


def progress(text: str) -> None:
    """Per-blob detail belongs to the run log, never to the terminal."""
    try:
        log(os.environ.get("OCI_LOG"), text)
    except OSError:
        pass


def verify_blob(archive: tarfile.TarFile, member: tarfile.TarInfo, position: int, total: int) -> None:
    expected_digest = member.name.rsplit("/", 1)[-1]
    source = archive.extractfile(member)
    if source is None:
        raise VerificationError(f"{translate('Cannot read')} {member.name}")

    progress(f"  Verifying blob {position}/{total}: {expected_digest[:12]} ({human_mib(member.size)})")
    digest = hashlib.sha256()
    decompressor: zlib.Decompress | None = None
    processed = 0
    next_progress = PROGRESS_STEP

    while True:
        chunk = source.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        if processed == 0 and chunk.startswith(b"\x1f\x8b"):
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        if decompressor is not None:
            try:
                decompressor.decompress(chunk)
            except zlib.error as exc:
                raise VerificationError(
                    f"{translate('Corrupted gzip layer')} {expected_digest[:16]}: {exc}"
                ) from exc
        processed += len(chunk)
        if member.size >= PROGRESS_STEP and processed >= next_progress:
            percentage = min(100, processed * 100 // member.size)
            progress(f"    {human_mib(processed)} / {human_mib(member.size)} ({percentage}%)")
            next_progress += PROGRESS_STEP

    if processed != member.size:
        raise VerificationError(
            f"{translate('Wrong size in')} {expected_digest[:16]}: {processed} != {member.size}"
        )
    actual_digest = digest.hexdigest()
    if actual_digest != expected_digest:
        raise VerificationError(
            f"{translate('Wrong SHA-256 in')} {expected_digest[:16]}: {actual_digest[:16]}"
        )
    if decompressor is not None:
        try:
            decompressor.flush()
        except zlib.error as exc:
            raise VerificationError(
                f"{translate('Corrupted gzip layer')} {expected_digest[:16]}: {exc}"
            ) from exc
        if not decompressor.eof:
            raise VerificationError(f"{translate('Incomplete gzip layer')} {expected_digest[:16]}")


def verify_archive(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise VerificationError(f"{translate('The OCI archive does not exist or is empty:')} {path}")

    try:
        with tarfile.open(path, mode="r:*") as archive:
            members = archive.getmembers()
            names = {member.name.lstrip("./") for member in members}
            missing = {"index.json", "oci-layout"} - names
            if missing:
                raise VerificationError(
                    f"{translate('Missing OCI metadata:')} " + ", ".join(sorted(missing))
                )
            blobs = [
                member
                for member in members
                if member.isfile()
                and member.name.lstrip("./").startswith("blobs/sha256/")
            ]
            if not blobs:
                raise VerificationError(translate("The OCI archive contains no SHA-256 blobs"))
            for position, member in enumerate(blobs, start=1):
                verify_blob(archive, member, position, len(blobs))
    except (tarfile.TarError, OSError) as exc:
        raise VerificationError(f"{translate('Cannot read the OCI archive:')} {exc}") from exc
    progress(f"OCI integrity verified: {path}")


def _layer_extracted_size(raw, member: tarfile.TarInfo) -> int | None:
    """What a layer takes once unpacked: the gzip trailer, the frame header of
    zstd or the tar itself."""
    raw.seek(member.offset_data)
    head = raw.read(18)
    if head.startswith(b"\x1f\x8b"):
        raw.seek(member.offset_data + member.size - 4)
        size = struct.unpack("<I", raw.read(4))[0]
        # The trailer keeps the size modulo 4 GiB.
        while size < member.size:
            size += 1 << 32
        return size
    if head.startswith(b"\x28\xb5\x2f\xfd") and len(head) >= 6:
        descriptor = head[4]
        single_segment = descriptor >> 5 & 1
        field = (1 if single_segment else 0, 2, 4, 8)[descriptor >> 6]
        if not field:
            return None
        start = 5 + (0 if single_segment else 1) + (0, 1, 2, 4)[descriptor & 3]
        value = int.from_bytes(head[start:start + field], "little")
        return value + 256 if field == 2 else value
    return member.size


def extracted_size(path: Path) -> int | None:
    """Estimated size of the image once its layers are unpacked, or None when
    a layer does not record it."""
    with tarfile.open(path, mode="r:") as archive, path.open("rb") as raw:
        members = {member.name.lstrip("./"): member for member in archive.getmembers()}

        def blob(digest: str) -> tarfile.TarInfo:
            return members["blobs/" + digest.replace(":", "/")]

        index = json.load(archive.extractfile(members["index.json"]))
        manifest = json.load(archive.extractfile(blob(index["manifests"][0]["digest"])))
        total = 0
        for layer in manifest.get("layers", []):
            size = _layer_extracted_size(raw, blob(layer["digest"]))
            if size is None:
                return None
            total += size
        return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--extracted-mib", action="store_true",
                        help="print the estimated unpacked size in MiB (0 when unknown)")
    args = parser.parse_args()
    if args.extracted_mib:
        try:
            size = extracted_size(args.archive)
        except (tarfile.TarError, OSError, KeyError, ValueError, IndexError):
            size = None
        print((size or 0) >> 20)
        return 0
    try:
        verify_archive(args.archive)
    except VerificationError as exc:
        print(f"{translate('OCI verification failed:')} {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
