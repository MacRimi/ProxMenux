"""AdGuard Home Sync serves its API on the port API_PORT names, or not at all
when it is 0. The check after an update or a recovery follows it, so a turned
off API does not leave the operation waiting for a port that never opens."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "remote"), str(ROOT / "src")]

import oci_instance_transaction as transaction  # noqa: E402

TEMPLATE = {
    "id": "linuxserver-adguardhome-sync",
    "first_run": {"endpoints": [{"label": "Web UI", "scheme": "http", "port": 8080, "path": "/"}]},
    "proxmox": {"installer_profile": {}},
}


class PortVariableTests(unittest.TestCase):
    def test_the_web_port_is_checked_by_default(self):
        self.assertEqual(transaction.effective_healthcheck(TEMPLATE)["port"], 8080)
        self.assertEqual(transaction.effective_healthcheck(TEMPLATE, {"TZ": "Etc/UTC"})["port"], 8080)

    def test_a_turned_off_api_only_needs_the_container_running(self):
        check = transaction.effective_healthcheck(TEMPLATE, {"API_PORT": "0"})
        self.assertEqual(check["type"], "running")

    def test_another_port_is_checked_there(self):
        self.assertEqual(transaction.effective_healthcheck(TEMPLATE, {"API_PORT": "9090"})["port"], 9090)
        self.assertEqual(transaction.effective_healthcheck(TEMPLATE, {"API_PORT": "abc"})["port"], 8080)

    def test_other_applications_ignore_the_variable(self):
        other = dict(TEMPLATE, id="image-something-else")
        self.assertEqual(transaction.effective_healthcheck(other, {"API_PORT": "0"})["port"], 8080)

    def test_the_variables_come_from_the_plan_and_from_the_container(self):
        contract = {"template": {**TEMPLATE, "proxmox": {"installer_profile": {}}},
                    "deployment": {"environment": [{"name": "API_PORT", "value": "0"}]}}
        injected = transaction.with_default_healthcheck(contract)["template"]["proxmox"]["installer_profile"]
        self.assertEqual(injected["startup_healthcheck"]["type"], "running")
        config = b"arch: amd64\nlxc.environment.runtime: API_PORT=0\nlxc.environment.runtime: TZ=Etc/UTC\n"
        self.assertEqual(transaction.config_environment(config), {"API_PORT": "0", "TZ": "Etc/UTC"})


if __name__ == "__main__":
    unittest.main()
