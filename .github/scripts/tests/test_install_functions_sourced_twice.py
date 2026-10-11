"""The shared install functions are sourced by both post-install flows. An
update that runs functions of the two sources the file twice in one shell,
which has to be as quiet as the first time."""

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "scripts/global/utils-install-functions.sh"


@unittest.skipUnless(shutil.which("bash"), "bash is needed")
class SourcedTwiceTests(unittest.TestCase):
    def source(self, times):
        script = "; ".join([f'source "{SHARED}"'] * times) + '; echo "${PMX_NIC_LINK_DIR}|${#PMX_DKMS_COMPONENTS[@]}"'
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)

    def test_a_second_source_prints_nothing(self):
        once, twice = self.source(1), self.source(2)
        self.assertEqual(twice.stderr, once.stderr)
        self.assertNotIn("readonly variable", twice.stderr)
        self.assertEqual(twice.returncode, 0)

    def test_the_values_are_the_same_and_stay_read_only(self):
        self.assertEqual(self.source(2).stdout.strip(), "/etc/systemd/network|2")
        attempt = subprocess.run(["bash", "-c", f'source "{SHARED}"; PMX_NIC_LINK_DIR=/tmp'],
                                 capture_output=True, text=True, check=False)
        self.assertIn("readonly variable", attempt.stderr)

    def test_no_other_shared_file_declares_a_read_only_variable_unguarded(self):
        for path in sorted((ROOT / "scripts/global").glob("*.sh")) + [ROOT / "scripts/utils.sh"]:
            for line in path.read_text(errors="replace").splitlines():
                self.assertFalse(line.startswith(("readonly ", "declare -r ")), f"{path.name}: {line[:60]}")


if __name__ == "__main__":
    unittest.main()
