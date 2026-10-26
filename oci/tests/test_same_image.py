"""An image is the same in the registry and in the archive made from it,
whichever format the registry publishes its manifest in."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))

from oci_installation_state import same_image

REGISTRY = "sha256:" + "a" * 64
ARCHIVE = "sha256:" + "b" * 64
LAYERS = ["sha256:" + "c" * 64, "sha256:" + "d" * 64]
BUILT = "2026-09-15T01:13:55.019799592Z"


class SameImageTests(unittest.TestCase):
    def test_an_oci_manifest_keeps_its_digest(self):
        self.assertTrue(same_image({"manifest_digest": REGISTRY}, {"manifest_digest": REGISTRY}))

    def test_a_docker_manifest_is_recognised_by_its_layers_and_when_it_was_built(self):
        self.assertTrue(same_image({"manifest_digest": REGISTRY, "layers": LAYERS, "created": BUILT},
                                   {"manifest_digest": ARCHIVE, "layers": list(LAYERS), "created": BUILT}))

    def test_another_image_is_not_the_same(self):
        candidate = {"manifest_digest": REGISTRY, "layers": LAYERS, "created": BUILT}
        self.assertFalse(same_image(candidate, {"manifest_digest": ARCHIVE, "layers": LAYERS[:1], "created": BUILT}))
        self.assertFalse(same_image(candidate, {"manifest_digest": ARCHIVE, "layers": LAYERS[::-1], "created": BUILT}))
        # The same layers rebuilt with another configuration are another image.
        self.assertFalse(same_image(candidate, {"manifest_digest": ARCHIVE, "layers": LAYERS,
                                                "created": "2026-10-01T00:00:00Z"}))

    def test_what_is_missing_never_matches(self):
        self.assertFalse(same_image({"manifest_digest": REGISTRY}, {"manifest_digest": ARCHIVE}))
        self.assertFalse(same_image({"manifest_digest": REGISTRY, "layers": [], "created": BUILT},
                                    {"manifest_digest": ARCHIVE, "layers": [], "created": BUILT}))
        self.assertFalse(same_image({"manifest_digest": REGISTRY, "layers": LAYERS, "created": None},
                                    {"manifest_digest": ARCHIVE, "layers": LAYERS, "created": None}))
        # A record saved before the layers were kept is compared by its digest alone.
        self.assertFalse(same_image({"manifest_digest": REGISTRY, "layers": LAYERS, "created": BUILT},
                                    {"manifest_digest": ARCHIVE}))


if __name__ == "__main__":
    unittest.main()
