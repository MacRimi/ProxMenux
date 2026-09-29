"""Regression test for volume_preparations survival through the generic
multi-LXC stack pipeline (apply_stack_support + service_template).

install_generic_stack.py::create_service() writes each service's own
service['template'] to a per-service template.json and runs install_oci.sh
against that file independently — the parent stack template's
installer_profile is never read at install time. So the fix must land in
each service's own template, not just the parent's top-level
installer_profile (that alone would be a cosmetic data match with no real
effect). This is the regression guard for the stack volume_preparations
loss first found via read-only audit (2026-09-29): apply_stack_support()
replaced installer_profile wholesale and silently dropped
volume_preparations for every stack app (Blinko, Kimai, Linkwarden, Monica
Official, Petio, Qui, RomM, Teable).
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.stack import build_stack, DefaultsUI


class StackVolumePreparationsTests(unittest.TestCase):
    def test_stack_service_receives_only_its_own_volume_preparation(self):
        """Blinko (2-service stack: blinko + blinko-postgres). The real
        build_stack() output — what create_service() actually writes to
        each service's template.json — must carry the preparation for
        /app/.blinko into the blinko service's own template, scoped to
        only_when_mount_type: managed-volume, and must NOT leak it (or any
        other service's paths) into blinko-postgres's template, which has
        no volume_preparations entry of its own in the source catalog."""
        template = Catalog(ROOT).compose("blinko")
        result = build_stack(template, DefaultsUI(), mode="simple")

        services_by_name = {s["name"]: s for s in result["services"]}
        self.assertEqual(set(services_by_name), {"blinko", "blinko-postgres"})

        blinko_preps = services_by_name["blinko"]["template"]["proxmox"] \
            .get("installer_profile", {}).get("volume_preparations", [])
        self.assertEqual(len(blinko_preps), 1)
        self.assertEqual(blinko_preps[0]["container_path"], "/app/.blinko")
        self.assertEqual(blinko_preps[0]["only_when_mount_type"], "managed-volume")

        postgres_preps = services_by_name["blinko-postgres"]["template"]["proxmox"] \
            .get("installer_profile", {}).get("volume_preparations", [])
        self.assertEqual(postgres_preps, [])

    def test_synthetic_dependency_volume_preparation_reaches_only_that_service(self):
        """Blinko's postgres dependency service (blinko-postgres, image
        postgres:latest) has its own Compose-declared mount,
        /var/lib/postgresql/data, which build_stack() normalizes to
        /var/lib/postgresql for PostgreSQL 18+ (see the 'Official
        PostgreSQL 18+' comment in build_stack()) — this mount is NOT one
        of the DEPENDENCY_VOLUMES fallback entries, it comes straight from
        the source Compose file. A synthetic volume_preparations entry for
        the final, normalized mount target (/var/lib/postgresql) is
        injected on the parent template to verify it reaches only the
        postgres service's own template — not blinko's, and not lost. This
        test is only about correct metadata transfer through
        service_template()/build_stack(); it makes no claim about whether
        preparing a database data directory this way is runtime-appropriate."""
        template = Catalog(ROOT).compose("blinko")
        template["proxmox"]["installer_profile"].setdefault("volume_preparations", [])
        template["proxmox"]["installer_profile"]["volume_preparations"].append({
            "container_path": "/var/lib/postgresql",
            "remove_lost_found": True,
            "owner_strategy": "mapped-root",
            "only_when_mount_type": "managed-volume",
        })

        result = build_stack(template, DefaultsUI(), mode="simple")
        services_by_name = {s["name"]: s for s in result["services"]}

        postgres_preps = services_by_name["blinko-postgres"]["template"]["proxmox"] \
            .get("installer_profile", {}).get("volume_preparations", [])
        self.assertEqual(
            [p["container_path"] for p in postgres_preps],
            ["/var/lib/postgresql"],
            "The synthetic preparation for the final, normalized postgres "
            "mount target must reach the postgres service's own template.",
        )
        self.assertEqual(
            postgres_preps[0]["container_path"],
            services_by_name["blinko-postgres"]["template"]["container_contract"]["volumes"][0]["container_path"],
            "The preparation's container_path must match the service's own "
            "final mount path exactly, not an intermediate/pre-rename form.",
        )

        blinko_preps = services_by_name["blinko"]["template"]["proxmox"] \
            .get("installer_profile", {}).get("volume_preparations", [])
        self.assertEqual(
            [p["container_path"] for p in blinko_preps],
            ["/app/.blinko"],
            "The synthetic postgres-only preparation must not leak into "
            "blinko's own template.",
        )

    def test_synthetic_dependency_volume_preparation_keyed_to_the_pre_rename_path_is_also_normalized(self):
        """The same postgres mount, but the synthetic preparation is keyed
        to the pre-rename Compose path (/var/lib/postgresql/data) instead
        of the final one. It must still reach blinko-postgres's own
        template, remapped to the same final container_path
        (/var/lib/postgresql) that build_stack() actually mounts — a
        preparation entry whose path no longer matches any real mount is
        dead configuration at install time. This test is only about
        correct metadata transfer; it makes no claim about runtime
        appropriateness."""
        template = Catalog(ROOT).compose("blinko")
        template["proxmox"]["installer_profile"].setdefault("volume_preparations", [])
        template["proxmox"]["installer_profile"]["volume_preparations"].append({
            "container_path": "/var/lib/postgresql/data",
            "remove_lost_found": True,
            "owner_strategy": "mapped-root",
            "only_when_mount_type": "managed-volume",
        })

        result = build_stack(template, DefaultsUI(), mode="simple")
        services_by_name = {s["name"]: s for s in result["services"]}

        postgres_preps = services_by_name["blinko-postgres"]["template"]["proxmox"] \
            .get("installer_profile", {}).get("volume_preparations", [])
        self.assertEqual(
            [p["container_path"] for p in postgres_preps],
            ["/var/lib/postgresql"],
            "A preparation keyed to the pre-rename Compose path must be "
            "remapped to the same final path build_stack() actually mounts, "
            "not silently dropped and not left pointing at the stale path.",
        )
        self.assertEqual(
            postgres_preps[0]["container_path"],
            services_by_name["blinko-postgres"]["template"]["container_contract"]["volumes"][0]["container_path"],
        )


if __name__ == "__main__":
    unittest.main()
