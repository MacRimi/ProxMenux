"""Regression tests for apply_nginx_runtime_contract (BARE_NGINX_RUNTIME_INIT).

Covers the Stremio /run/nginx fix: images that run a bare nginx without an
s6-overlay/LinuxServer init or a Selkies profile need /run/nginx recreated
as a tmpfs mount, because LXC's volatile /run hides the directory shipped in
the OCI rootfs (nginx: [emerg] open() "/run/nginx/nginx.pid" failed).
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.gpu import apply_nginx_runtime_contract


class BareNginxRuntimeContractTests(unittest.TestCase):
    def test_bare_nginx_app_gets_run_mount(self):
        """Stremio (curated, tsaridas/stremio-docker) gets exactly one
        /run/nginx tmpfs mount in proxmox.installer_profile.tmpfs_mounts."""
        template = Catalog(ROOT).compose("stremio")

        mounts = template["proxmox"]["installer_profile"]["tmpfs_mounts"]
        nginx_mounts = [m for m in mounts if m.get("container_path") == "/run/nginx"]
        self.assertEqual(len(nginx_mounts), 1)
        self.assertEqual(nginx_mounts[0]["id"], "nginx-runtime")

    def test_non_target_app_unaffected(self):
        """Jellyfin Official (curated, image jellyfin/jellyfin — not in
        BARE_NGINX_RUNTIME_INIT) must not get a new tmpfs mount."""
        template = Catalog(ROOT).compose("jellyfin-official")

        profile = template["proxmox"]["installer_profile"]
        self.assertNotIn("tmpfs_mounts", profile)

    def test_contract_is_idempotent_on_stremio_template(self):
        """Re-applying apply_nginx_runtime_contract() a second time on top
        of an already-processed Stremio template (as compose() would do if
        called again, or if the fix runs more than once in a pipeline) must
        not duplicate the mount — exactly one /run/nginx entry survives.
        This does not simulate a hand-authored /run/nginx entry or 2FAuth's
        own pre-existing catalog mount; it only covers repeated application
        of this specific contract function on its own prior output."""
        template = Catalog(ROOT).compose("stremio")

        # Call the contract function again on its own already-processed
        # output, simulating repeated application in a pipeline.
        apply_nginx_runtime_contract(template)
        apply_nginx_runtime_contract(template)

        mounts = template["proxmox"]["installer_profile"]["tmpfs_mounts"]
        nginx_mounts = [m for m in mounts if m.get("container_path") == "/run/nginx"]
        self.assertEqual(len(nginx_mounts), 1)


if __name__ == "__main__":
    unittest.main()
