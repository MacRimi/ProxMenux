"""The container creation progress knows how big the image is once unpacked."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

from verify_oci_archive import extracted_size


def zstd_frame(content_size: int) -> bytes:
    # Magic, a descriptor with an 8-byte content size and single segment, the size.
    return b"\x28\xb5\x2f\xfd" + bytes([0b11100000]) + content_size.to_bytes(8, "little") + b"\x00" * 16


class ExtractedSizeTests(unittest.TestCase):
    def archive(self, layers):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "image.tar"
        blobs = {}

        def add(data: bytes) -> str:
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            blobs[digest] = data
            return digest

        manifest = {"layers": [{"digest": add(data), "mediaType": "x"} for data in layers]}
        index = {"manifests": [{"digest": add(json.dumps(manifest).encode())}]}
        with tarfile.open(path, "w") as tar:
            for name, data in [("oci-layout", b"{}"), ("index.json", json.dumps(index).encode()),
                               *((f"blobs/{d.replace(':', '/')}", b) for d, b in blobs.items())]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path

    def test_gzip_zstd_and_plain_layers_add_up(self):
        path = self.archive([gzip.compress(b"a" * 300_000), zstd_frame(5 << 20), b"p" * 1000])
        self.assertEqual(extracted_size(path), 300_000 + (5 << 20) + 1000)

    def test_zstd_layer_without_content_size_is_unknown(self):
        frame = b"\x28\xb5\x2f\xfd" + bytes([0b00000000, 0x50]) + b"\x00" * 16
        self.assertIsNone(extracted_size(self.archive([frame])))


if __name__ == "__main__":
    unittest.main()
