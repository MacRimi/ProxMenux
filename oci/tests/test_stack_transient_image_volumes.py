"""Image paths a stack's oci-compose states hold no data reach the template
of every container of the stack, where updates and Modify read them."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.stack import apply_stack_support, build_stack, DefaultsUI


class StackTransientImageVolumesTests(unittest.TestCase):
    def test_each_container_of_romm_receives_the_transient_paths(self):
        result = build_stack(Catalog(ROOT).compose("romm"), DefaultsUI(), mode="simple")
        for service in result["services"]:
            profile = service["template"]["proxmox"]["installer_profile"]
            self.assertEqual(profile.get("non_persistent_image_volumes"), ["/romm"], service["name"])

    def test_the_stack_profile_keeps_them_when_it_is_rewritten(self):
        template = copy.deepcopy(Catalog(ROOT).compose("romm"))
        template["proxmox"]["installer_profile"]["stack_driver"] = "generic-multi-lxc-stack"
        apply_stack_support(template)
        self.assertEqual(template["proxmox"]["installer_profile"].get("non_persistent_image_volumes"), ["/romm"])


if __name__ == "__main__":
    unittest.main()
