"""An image published with a Docker-format manifest is saved for Proxmox
under another digest than the one its registry serves. Its installed version
and its updates are read through the digest the registry knows."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import lxc_apps

ARCHIVE = "sha256:" + "a1" * 32
INDEX = "sha256:" + "b2" * 32
PLATFORM = "sha256:" + "c3" * 32
NEWER = "sha256:" + "d4" * 32


class Registry:
    """A registry that knows the index and the platform manifest, never the archive."""

    def __init__(self, tag=PLATFORM):
        self.tag, self.asked = tag, []

    def resolve_candidate(self, reference, architecture):
        self.asked.append(reference)
        if reference.endswith("@" + ARCHIVE):
            raise RuntimeError("manifest unknown")
        digest = self.tag if "@" not in reference else PLATFORM
        return {"manifest_digest": digest, "version": "12.1" if digest == PLATFORM else "12.2",
                "created": "2026-09-15T01:13:55Z"}


class DockerManifestVersionTests(unittest.TestCase):
    def versions(self, registry, registry_digest=INDEX, known=None):
        meta = {"image_reference": "jellyfin/jellyfin:latest", "installed_digest": ARCHIVE,
                "registry_digest": registry_digest, "architecture": "amd64", "repository": None}
        with patch.object(lxc_apps, "_oci_operation_running", return_value=False), \
                patch.object(lxc_apps, "_oci_instance_meta", return_value=meta), \
                patch.object(lxc_apps, "_oci_state_module", return_value=registry), \
                patch.object(lxc_apps.time, "sleep"):
            return lxc_apps._oci_image_versions(105, known=known)

    def test_the_installed_image_is_read_by_the_digest_the_registry_served(self):
        registry = Registry()
        result = self.versions(registry)
        self.assertNotIn("error", result)
        self.assertEqual(registry.asked[0], "jellyfin/jellyfin@" + INDEX)
        self.assertEqual((result["installed_version"], result["installed_registry_digest"]), ("12.1", PLATFORM))
        self.assertFalse(result["update_available"])
        self.assertEqual(result["installed_digest"], ARCHIVE)

    def test_a_new_image_under_the_tag_is_an_update(self):
        result = self.versions(Registry(tag=NEWER))
        self.assertTrue(result["update_available"])
        self.assertEqual((result["latest_digest"], result["latest_version"]), (NEWER, "12.2"))

    def test_a_previous_answer_is_reused_with_its_registry_digest(self):
        registry = Registry()
        known = {"installed_digest": ARCHIVE, "installed_registry_digest": PLATFORM, "installed_version": "12.1",
                 "image_created": "2026-09-15T01:13:55Z"}
        result = self.versions(registry, known=known)
        self.assertEqual(registry.asked, ["jellyfin/jellyfin:latest"])
        self.assertFalse(result["update_available"])
        # An answer saved without the registry digest is asked again.
        registry = Registry()
        self.versions(registry, known={key: value for key, value in known.items() if key != "installed_registry_digest"})
        self.assertEqual(registry.asked[0], "jellyfin/jellyfin@" + INDEX)

    def test_a_record_without_the_registry_digest_is_read_by_its_own(self):
        registry = Registry()
        result = self.versions(registry, registry_digest=None)
        self.assertEqual(registry.asked[0], "jellyfin/jellyfin@" + ARCHIVE)
        self.assertEqual(result["error"], "registry unreachable")


class Silent(Registry):
    """A registry that stops answering for the tag."""

    def resolve_candidate(self, reference, architecture):
        if "@" not in reference:
            self.asked.append(reference)
            raise RuntimeError("skopeo failed with exit code 1")
        return super().resolve_candidate(reference, architecture)


class RegistryUnreachableTests(unittest.TestCase):
    versions = DockerManifestVersionTests.versions

    KNOWN = {"installed_digest": ARCHIVE, "installed_registry_digest": PLATFORM, "installed_version": "12.1",
             "image_created": "2026-09-15T01:13:55Z", "latest_digest": NEWER, "latest_version": "12.2",
             "latest_image_created": "2026-09-20T00:00:00Z", "update_available": True}

    def test_the_last_answer_stands_when_the_registry_does_not_answer(self):
        result = self.versions(Silent(), known=self.KNOWN)
        self.assertNotIn("error", result)
        self.assertEqual((result["latest_digest"], result["latest_version"], result["update_available"]),
                         (NEWER, "12.2", True))
        self.assertTrue(result["registry_retry"])

    def test_without_a_previous_answer_the_panel_is_told_in_a_way_it_can_translate(self):
        result = self.versions(Silent())
        self.assertEqual(result["error"], "registry unreachable")
        self.assertTrue(result["registry_retry"])
        self.assertEqual((result["installed_version"], result["installed_digest"]), ("12.1", ARCHIVE))

    def test_an_answer_for_another_image_is_not_reused(self):
        other = dict(self.KNOWN, installed_digest="sha256:" + "e5" * 32)
        self.assertEqual(self.versions(Silent(), known=other)["error"], "registry unreachable")

    def test_the_registry_is_asked_again_until_it_answers(self):
        states = [{"registry_retry": True}, {"registry_retry": False}]
        checks, waits = [], []

        def check(vmid, app_id, force=False):
            checks.append((vmid, app_id, force))
            return {"apps": [{"id": app_id, "state": states[len(checks) - 1]}]}

        started = []
        with patch.object(lxc_apps, "check_app", side_effect=check), \
                patch.object(lxc_apps.time, "sleep", side_effect=waits.append), \
                patch.object(lxc_apps.threading, "Thread", side_effect=lambda target, **_: started.append(target) or self):
            self.start = lambda: None
            lxc_apps._retry_oci_registry(105, "jellyfin")
            lxc_apps._retry_oci_registry(105, "jellyfin")
            self.assertEqual(len(started), 1)
            started[0]()
        self.assertEqual(checks, [(105, "jellyfin", True)] * 2)
        self.assertEqual(waits, list(lxc_apps._OCI_REGISTRY_RETRY_WAITS[:2]))
        self.assertNotIn((105, "jellyfin"), lxc_apps._oci_registry_retries)


if __name__ == "__main__":
    unittest.main()
