"""What a Compose file reserves for an application is the least it is promised,
not the most it may use. A container limited to that figure is stopped by the
kernel as soon as the application needs more."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.casaos import _memory_mb
from proxmenux_oci.catalog import Catalog


def service(reservation=None, limit=None):
    resources = {}
    if reservation:
        resources["reservations"] = {"memory": reservation}
    if limit:
        resources["limits"] = {"memory": limit}
    return {"deploy": {"resources": resources}} if resources else {}


class ContainerMemoryTests(unittest.TestCase):
    def test_a_reservation_is_not_the_memory_of_the_container(self):
        self.assertEqual(_memory_mb(service(reservation="64M")), 1024)
        self.assertEqual(_memory_mb(service(reservation="256M")), 1024)

    def test_a_larger_reservation_raises_it(self):
        self.assertEqual(_memory_mb(service(reservation="2G")), 2048)

    def test_a_limit_the_file_sets_is_the_memory_of_the_container(self):
        self.assertEqual(_memory_mb(service(limit="512M")), 512)
        self.assertEqual(_memory_mb(service(reservation="128M", limit="128M")), 128)

    def test_nothing_stated_is_the_default(self):
        self.assertEqual(_memory_mb({}), 1024)

    def test_the_recipes_that_only_reserve_memory_get_the_default(self):
        catalog = Catalog(ROOT)
        for app in ("homeassistant-official", "unifi-controller", "grafana", "gitea", "vaultwarden", "uptimekuma"):
            self.assertGreaterEqual(catalog.compose(app)["proxmox"]["defaults"]["memory_mb"], 1024, app)


if __name__ == "__main__":
    unittest.main()
