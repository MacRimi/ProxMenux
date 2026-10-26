"""Applications that run inside Docker: registrable, but updated by their image.

Such an app is a real application — name, logo, links, installed version — and
is registered like any other. What it does not get is an update path of its
own: the image it comes from already has one, and two would mean two badges,
two notifications and two buttons for a single release.
"""

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps


class DelegationValidationTests(unittest.TestCase):
    BASE = {
        "name": "Vaultwarden",
        "installed_via": "docker_exec",
        "container_name": "vaultwarden",
        "binary_path": "/vaultwarden",
        "binary_args": ["--version"],
        "installed_regex": r"(?im)^Vaultwarden\s+v?(\d+\.\d+\.\d+)",
    }

    def test_delegation_is_accepted_with_a_docker_detector(self):
        ok, conf = lxc_apps.validate_config({**self.BASE, "update_via": "docker"})
        self.assertTrue(ok, conf)
        self.assertEqual(conf["update_via"], "docker")
        self.assertEqual(conf["container_name"], "vaultwarden")

    def test_delegation_requires_a_docker_detector(self):
        ok, error = lxc_apps.validate_config({
            "name": "Vaultwarden", "installed_via": "dpkg",
            "package": "vaultwarden", "update_via": "docker",
        })
        self.assertFalse(ok)
        self.assertIn("docker_label or docker_exec", str(error))

    def test_delegation_rejects_an_upstream_instead_of_stripping_it(self):
        """Silently dropping it would register an app that checks GitHub
        behind a delegation promising it will not."""
        ok, error = lxc_apps.validate_config({
            **self.BASE, "update_via": "docker",
            "repo": "dani-garcia/vaultwarden", "github_source": "releases",
        })
        self.assertFalse(ok)
        self.assertIn("repo", str(error))

    def test_an_undelegated_docker_app_still_works(self):
        """Someone who wired their own updater keeps it."""
        ok, conf = lxc_apps.validate_config({
            **self.BASE, "repo": "dani-garcia/vaultwarden",
            "github_source": "releases", "tag_regex": r"v?(\d+\.\d+\.\d+)",
        })
        self.assertTrue(ok, conf)
        self.assertNotIn("update_via", conf)
        self.assertEqual(conf["repo"], "dani-garcia/vaultwarden")


class UnitResolutionTests(unittest.TestCase):
    INVENTORY = {
        "available": True,
        "containers": [
            {"name": "vaultwarden", "compose": None},
            {"name": "immich_server", "compose": {"project": "immich", "service": "immich-server"}},
            {"name": "immich_redis", "compose": {"project": "immich", "service": "redis"}},
        ],
        "images": [
            {"reference": "vaultwarden/server:latest", "used_by": ["vaultwarden"]},
            {"reference": "ghcr.io/immich-app/immich-server:release", "used_by": ["immich_server"]},
        ],
        "update_units": [
            {"id": "standalone:vaultwarden", "kind": "standalone",
             "standalone_containers": ["vaultwarden"]},
            {"id": "compose:immich", "kind": "compose", "project": "immich",
             "services": ["immich-server", "redis", "postgres"]},
        ],
    }

    def test_standalone_container_resolves_to_its_image(self):
        got = lxc_apps.resolve_docker_image_for_app(
            {"container_name": "vaultwarden"}, self.INVENTORY)
        self.assertEqual(got["image_reference"], "vaultwarden/server:latest")
        self.assertIsNone(got["error"])

    def test_compose_service_resolves_to_its_own_image(self):
        """Immich is four containers; only the one the app declares counts."""
        got = lxc_apps.resolve_docker_image_for_app(
            {"container_name": "immich_server"}, self.INVENTORY)
        self.assertEqual(got["image_reference"], "ghcr.io/immich-app/immich-server:release")

    def test_renamed_container_says_so(self):
        got = lxc_apps.resolve_docker_image_for_app(
            {"container_name": "vaultwarden-old"}, self.INVENTORY)
        self.assertIsNone(got["image_reference"])
        self.assertEqual(got["error"], "container_not_in_inventory")

    def test_inventory_not_ready_is_not_a_missing_container(self):
        got = lxc_apps.resolve_docker_image_for_app(
            {"container_name": "vaultwarden"}, {"available": False})
        self.assertEqual(got["error"], "inventory_unavailable")

    def test_app_without_a_container_declares_it(self):
        got = lxc_apps.resolve_docker_image_for_app({}, self.INVENTORY)
        self.assertEqual(got["error"], "no_container_declared")


class SchedulingExclusionTests(unittest.TestCase):
    def test_delegated_app_never_holds_the_schedule(self):
        """It has no release date, so gating on one defers it forever."""
        gated_ids, _deferred = lxc_apps.partition_scheduled_release_targets(
            ["app:a1", "app:a2"],
            [
                {"id": "a1", "name": "Vaultwarden", "installed_via": "docker_exec",
                 "update_via": "docker", "container_name": "vaultwarden"},
                {"id": "a2", "name": "Paperless", "installed_via": "file"},
            ],
        )
        self.assertNotIn("a1", gated_ids)
        self.assertIn("a2", gated_ids)


class AnnotationTests(unittest.TestCase):
    """The annotation writes into dicts that live in event-invalidated caches."""

    INVENTORY = {
        "available": True,
        "images": [{
            "reference": "jokobsk/netalertx:latest", "used_by": ["netalertx"],
            "available_version": "26.9.0", "update_available": True,
        }],
        "containers": [{"name": "netalertx", "compose": None}],
        "update_units": [],
    }

    def _app(self, **overrides):
        app = {"id": "a1", "name": "netalertx", "update_via": "docker",
               "container_name": "netalertx"}
        app.update(overrides)
        return app

    def test_delegated_app_receives_its_image_version(self):
        apps = [self._app()]
        lxc_apps.annotate_delegated_apps(apps, self.INVENTORY)
        self.assertEqual(apps[0]["docker_available_version"], "26.9.0")
        self.assertIs(apps[0]["docker_update_available"], True)

    def test_stale_version_is_cleared_when_the_container_disappears(self):
        """A renamed container must not keep advertising its old image."""
        apps = [self._app(docker_available_version="26.9.0", docker_update_available=True)]
        gone = {"available": True, "images": [], "containers": [], "update_units": []}
        lxc_apps.annotate_delegated_apps(apps, gone)
        self.assertIsNone(apps[0]["docker_available_version"])
        self.assertIsNone(apps[0]["docker_update_available"])

    def test_apps_that_do_not_delegate_are_untouched(self):
        apps = [{"id": "b1", "name": "Paperless", "installed_via": "file",
                 "state": {"latest_version": "2.9.0"}}]
        lxc_apps.annotate_delegated_apps(apps, self.INVENTORY)
        self.assertNotIn("docker_available_version", apps[0])

    def test_a_broken_inventory_never_raises(self):
        """Decoration must not be able to cost the caller its response."""
        apps = [self._app()]
        lxc_apps.annotate_delegated_apps(apps, {"available": True, "images": "not-a-list"})
        self.assertIsNone(apps[0].get("docker_available_version"))


if __name__ == "__main__":
    unittest.main()
