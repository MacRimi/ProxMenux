"""A new volume starts with what the image has at its path, and a recipe may
write its own starting file in it. The file of the recipe wins over the copy of
the image; a file the user already had, in a reused volume or a host
directory, is kept."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog

INSTALLER = (ROOT / "remote/install_oci.sh").read_text()


def function(name):
    found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", INSTALLER, re.S | re.M)
    assert found, name
    return found.group(0)


class GeneratedFileTests(unittest.TestCase):
    def filled(self, path, *volumes):
        script = f'VOLUME_SEEDED_NOW=({" ".join(volumes)})\n{function("filled_from_the_image")}\nfilled_from_the_image "$1" && echo yes || echo no'
        done = subprocess.run(["bash", "-c", script, "bash", path], capture_output=True, text=True, check=False)
        self.assertEqual(done.stderr, "")
        return done.stdout.strip()

    @unittest.skipUnless(shutil.which("bash"), "bash is needed")
    def test_a_file_in_a_volume_just_filled_is_the_copy_of_the_image(self):
        self.assertEqual(self.filled("/home/filebrowser/data/config.yaml", "/home/filebrowser/data"), "yes")
        self.assertEqual(self.filled("/config/app/settings.yml", "/data", "/config"), "yes")

    @unittest.skipUnless(shutil.which("bash"), "bash is needed")
    def test_a_file_anywhere_else_is_not(self):
        self.assertEqual(self.filled("/home/filebrowser/data/config.yaml"), "no")
        self.assertEqual(self.filled("/home/filebrowser/database/config.yaml", "/home/filebrowser/data"), "no")
        self.assertEqual(self.filled("/home/filebrowser/data", "/home/filebrowser/data"), "no")

    def test_only_a_volume_that_was_filled_is_recorded(self):
        body = function("apply_volume_seeds")
        copied = body.index('cp -a -- "${stage}/." "${destination}/"')
        self.assertLess(copied, body.index('VOLUME_SEEDED_NOW+=("$target")'))
        # A host directory that already holds data is kept and not recorded.
        self.assertLess(body.index("Keeping existing host data without seeding it"), copied)

    def test_the_recipe_file_is_written_over_the_copy_of_the_image_only(self):
        step = INSTALLER[INSTALLER.index("generated_count=$(jq"):INSTALLER.index("generated_created=$((generated_created + 1))")]
        self.assertLess(step.index("apply_volume_seeds"), step.index("only_if_missing"))
        kept = step.index('if ! filled_from_the_image "$path"; then')
        self.assertLess(kept, step.index("Keeping the existing persistent file"))
        self.assertLess(step.index("Keeping the existing persistent file"), step.index("The generated file replaces the one of the image"))

    def test_filebrowser_quantum_serves_the_folder_it_mounts(self):
        template = Catalog(ROOT).compose("filebrowser-quantum")
        volumes = [item["container_path"] for item in template["container_contract"]["volumes"]]
        generated = template["proxmox"]["installer_profile"]["generated_files"][0]
        served = re.search(r"sources:\s*\n\s*- path: (\S+)", generated["content"]).group(1)
        self.assertIn(served, volumes)
        self.assertTrue(any(generated["container_path"].startswith(volume + "/") for volume in volumes))
        self.assertTrue(generated["only_if_missing"])
        # FileBrowser Quantum 2 reads the port under http, not under server.
        self.assertRegex(generated["content"], r"(?m)^http:\n  port: 80$")
        self.assertNotRegex(generated["content"], r"(?m)^server:\n  port:")


if __name__ == "__main__":
    unittest.main()
