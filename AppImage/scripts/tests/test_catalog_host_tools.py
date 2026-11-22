"""The tools of Community Scripts are the scripts that manage the host itself.
A host script Community Scripts files under another category, such as the
Scrutiny collector under Monitoring & Analytics, is an application of that
category, not a section of tools of its own."""
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import catalog_tab  # noqa: E402


def item(**entry):
    return catalog_tab._script_item({"slug": "example", "name": "Example", **entry})


class HostToolsTests(unittest.TestCase):
    def test_a_host_management_script_is_a_tool(self):
        tool = item(type="pve", category_names=["Host Management"])
        self.assertEqual((tool["group"], tool["section"]), ("tool", "cs:Host Management"))

    def test_an_unfiled_host_script_joins_the_host_tools(self):
        tool = item(type="pve", category_names=[])
        self.assertEqual((tool["group"], tool["section"]), ("tool", "cs:Host Management"))

    def test_a_host_script_of_another_category_is_an_application(self):
        app = item(slug="scrutiny-collector", type="pve", category_names=["Monitoring & Analytics"])
        self.assertEqual((app["group"], app["section"], app["category"], app["type"]),
                         ("app", "", "Monitoring & Analytics", "host"))

    def test_a_container_script_stays_an_application(self):
        app = item(type="lxc", category_names=["Monitoring & Analytics"])
        self.assertEqual((app["group"], app["category"]), ("app", "Monitoring & Analytics"))


if __name__ == "__main__":
    unittest.main()
