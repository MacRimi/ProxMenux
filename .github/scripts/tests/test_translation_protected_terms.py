"""A label made only of product and API names is right when it comes back
unchanged, so the translation bot keeps it instead of retrying and dropping it."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_translation_cache as cache  # noqa: E402


class ProtectedTermsTests(unittest.TestCase):
    def test_acceleration_profile_labels_are_kept_unchanged(self):
        for label in ("Intel/AMD (Vulkan)", "AMD (ROCm)", "Intel (SYCL)", "NVIDIA (CUDA)",
                      "Intel/AMD (VA-API)", "Intel (OpenVINO)"):
            with self.subTest(label=label):
                self.assertTrue(cache.is_fully_protected(label))
                self.assertFalse(cache.looks_untranslated(label, label))

    def test_a_sentence_coming_back_unchanged_is_still_a_failure(self):
        sentence = "The GPU is used through Vulkan when it is available"
        self.assertTrue(cache.looks_untranslated(sentence, sentence))


if __name__ == "__main__":
    unittest.main()
