"""Resolving the version a Docker image pull would install.

The registry answers the question the Updates tab actually asks: not "what is
the newest upstream release" but "what do I get if I re-pull this tag". These
tests pin the rules that keep that number honest — and the cases where the
honest answer is no number at all.
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lxc_apps


def _blob(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode("utf-8")
    return body, "sha256:" + hashlib.sha256(body).hexdigest()


def _image_index(platform_digest: str) -> dict:
    """An index shaped like the real ones: platforms plus attestations."""
    return {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"digest": platform_digest,
             "platform": {"os": "linux", "architecture": "amd64"}},
            {"digest": "sha256:" + "b" * 64,
             "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
            {"digest": "sha256:" + "c" * 64,
             "platform": {"os": "unknown", "architecture": "unknown"},
             "annotations": {"vnd.docker.reference.type": "attestation-manifest"}},
        ],
    }


def _manifest(config_digest: str) -> dict:
    return {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
        },
    }


class RemoteImageVersionTests(unittest.TestCase):
    def setUp(self):
        with lxc_apps._docker_remote_config_lock:
            lxc_apps._docker_remote_config_cache.clear()

    def _wire(self, remote_version="3.1.0", labels=None, config_media_type=None):
        """Serve a three-hop index -> manifest -> config walk from memory."""
        config_payload = {"config": {"Labels": labels if labels is not None else {
            "org.opencontainers.image.version": remote_version,
        }}}
        config_body, config_digest = _blob(config_payload)
        manifest = _manifest(config_digest)
        if config_media_type is not None:
            manifest["config"]["mediaType"] = config_media_type
        manifest_body, manifest_digest = _blob(manifest)
        index_body, index_digest = _blob(_image_index(manifest_digest))
        documents = {
            index_digest: index_body,
            manifest_digest: manifest_body,
            config_digest: config_body,
        }
        calls = []

        def fake_request(url, headers, method="HEAD", token=None, max_bytes=0,
                         follow_redirect=True):
            calls.append(url)
            digest = url.rsplit("/", 1)[-1]
            if digest in documents:
                return {}, documents[digest], "token", None
            return None, None, token, f"registry HTTP 404 for {digest}"

        return index_digest, calls, mock.patch.object(lxc_apps, "_registry_request", fake_request)

    def _item(self, index_digest, **overrides):
        item = {
            "api_host": "ghcr.io",
            "repository": "immich-app/immich-server",
            "reference": "ghcr.io/immich-app/immich-server:release",
            "remote_digest": index_digest,
            "installed_version": "3.0.1",
            "installed_version_source": "image_label:org.opencontainers.image.version",
            "platform": {"os": "linux", "architecture": "amd64", "variant": ""},
        }
        item.update(overrides)
        return item

    def test_resolves_version_from_the_remote_image_config(self):
        index_digest, calls, patch = self._wire()
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest))
        self.assertEqual(version, "3.1.0")
        self.assertEqual(source, "remote_image_label:org.opencontainers.image.version")
        self.assertEqual(len(calls), 3, "index, platform manifest and config blob")

    def test_attestation_manifest_is_never_selected(self):
        """Its config is a provenance document, not an image."""
        digest = lxc_apps._select_platform_manifest(
            _image_index("sha256:" + "a" * 64),
            {"os": "linux", "architecture": "amd64"},
        )
        self.assertEqual(digest, "sha256:" + "a" * 64)

    def test_arm64_v8_matches_bare_arm64(self):
        digest = lxc_apps._select_platform_manifest(
            _image_index("sha256:" + "a" * 64),
            {"os": "linux", "architecture": "arm64", "variant": ""},
        )
        self.assertEqual(digest, "sha256:" + "b" * 64)

    def test_missing_platform_yields_no_version(self):
        """No build for this host means a pull would fail; claim nothing."""
        index_digest, _calls, patch = self._wire()
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest, platform={"os": "linux", "architecture": "riscv64"}))
        self.assertIsNone(version)
        self.assertEqual(source, "remote_platform_missing")

    def test_same_version_rebuilt_reports_no_number(self):
        index_digest, _calls, patch = self._wire(remote_version="3.0.1")
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest))
        self.assertIsNone(version)
        self.assertEqual(source, "version_not_comparable")

    def test_lower_remote_version_is_rejected(self):
        index_digest, _calls, patch = self._wire(remote_version="2.9.0")
        with patch:
            version, _source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest))
        self.assertIsNone(version)

    def test_linuxserver_build_suffix_is_an_update(self):
        """LinuxServer bumps the -lsNNN build; the app version may not move.

        Label shape taken from the live lscr.io/linuxserver/radarr image.
        """
        index_digest, _calls, patch = self._wire(
            labels={"org.opencontainers.image.version": "6.3.0.10514-ls314",
                    "build_version": "Linuxserver.io version:- 6.3.0.10514-ls314"})
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest, installed_version="6.3.0.10514-ls313"))
        self.assertEqual(version, "6.3.0.10514-ls314")
        self.assertEqual(source, "remote_image_label:org.opencontainers.image.version")

    def test_label_key_must_match_the_installed_side(self):
        """Two publishers' label schemes are not a comparison."""
        index_digest, _calls, patch = self._wire()
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest, installed_version_source="image_label:Version"))
        self.assertIsNone(version)
        self.assertEqual(source, "version_source_mismatch")

    def test_config_without_labels_reports_no_version(self):
        index_digest, _calls, patch = self._wire(labels={})
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest))
        self.assertIsNone(version)
        self.assertEqual(source, "remote_no_labels")

    def test_moving_tag_label_is_rejected(self):
        index_digest, _calls, patch = self._wire(
            labels={"org.opencontainers.image.version": "main"})
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest))
        self.assertIsNone(version)
        self.assertEqual(source, "remote_no_labels")

    def test_non_image_artifact_is_unsupported(self):
        index_digest, _calls, patch = self._wire(
            config_media_type="application/vnd.cncf.helm.config.v1+json")
        with patch:
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item(index_digest))
        self.assertIsNone(version)
        self.assertEqual(source, "remote_unsupported_manifest")

    def test_tampered_document_is_discarded(self):
        """Documents are content-addressed; a mismatch is not trusted."""
        def fake_request(url, headers, method="HEAD", token=None, max_bytes=0,
                         follow_redirect=True):
            return {}, b'{"mediaType": "application/vnd.oci.image.manifest.v1+json"}', "t", None

        with mock.patch.object(lxc_apps, "_registry_request", fake_request):
            version, source = lxc_apps._docker_available_version_from_registry(
                self._item("sha256:" + "f" * 64))
        self.assertIsNone(version)
        self.assertEqual(source, "remote_fetch_error")

    def test_registry_error_leaves_the_digest_verdict_alone(self):
        def fake_request(url, headers, method="HEAD", token=None, max_bytes=0,
                         follow_redirect=True):
            return None, None, None, "registry network error: timed out"

        item = self._item("sha256:" + "e" * 64, update_available=True)
        with mock.patch.object(lxc_apps, "_registry_request", fake_request):
            version, source = lxc_apps._docker_available_version_from_registry(item)
        self.assertIsNone(version)
        self.assertEqual(source, "remote_fetch_error")
        self.assertIs(item["update_available"], True, "the digest verdict stands on its own")

    def test_second_image_with_the_same_digest_is_served_from_cache(self):
        index_digest, calls, patch = self._wire()
        with patch:
            lxc_apps._docker_available_version_from_registry(self._item(index_digest))
            lxc_apps._docker_available_version_from_registry(self._item(index_digest))
        self.assertEqual(len(calls), 3, "the second lookup must not hit the registry")


class RegistryRedirectTests(unittest.TestCase):
    def test_authorization_is_dropped_on_the_cdn_hop(self):
        """Signed storage URLs reject a second auth mechanism."""
        seen = []

        def fake_open(url, headers, method, max_bytes):
            seen.append((url, dict(headers)))
            if "blobs" in url:
                return {"Location": "https://cdn.example/blob"}, None, 307, "https://cdn.example/blob", None
            return {}, b"{}", 200, None, None

        with mock.patch.object(lxc_apps, "_registry_open", fake_open):
            lxc_apps._registry_request(
                "https://ghcr.io/v2/x/y/blobs/sha256:abc",
                {"User-Agent": "ProxMenux-Monitor", "Authorization": "Bearer secret"},
                method="GET", max_bytes=1024,
            )
        self.assertEqual(len(seen), 2)
        self.assertIn("Authorization", seen[0][1])
        self.assertNotIn("Authorization", seen[1][1])

    def test_digest_request_keeps_its_contract(self):
        def fake_open(url, headers, method, max_bytes):
            return {"Docker-Content-Digest": "sha256:deadbeef"}, None, 200, None, None

        with mock.patch.object(lxc_apps, "_registry_open", fake_open):
            digest, error = lxc_apps._registry_digest_request("https://ghcr.io/v2/x/y/manifests/latest", {})
        self.assertEqual(digest, "sha256:deadbeef")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()


class ContainerIdentityTests(unittest.TestCase):
    """A container's catalog identity comes from a detector that declares it."""

    HINTS = {
        "immich": {
            "installed_via": "file",
            "file_path": "/root/.immich",
            "logo": "https://example.invalid/immich.webp",
            "alt_detectors": [
                {"installed_via": "docker_label", "container_name": "immich_server",
                 "label": "org.opencontainers.image.version"},
            ],
        },
        "netalertx": {
            "installed_via": "docker_label",
            "container_name": "netalertx",
            "label": "org.opencontainers.image.version",
        },
        "postgresql": {"installed_via": "dpkg", "package": "postgresql"},
    }

    def test_index_covers_primary_and_alternate_detectors(self):
        with mock.patch.object(lxc_apps, "_fetch_tracking_hints", lambda: self.HINTS):
            index = lxc_apps._docker_container_slug_index()
        self.assertEqual(index.get("immich_server"), "immich")
        self.assertEqual(index.get("netalertx"), "netalertx")

    def test_unclaimed_container_names_stay_out(self):
        """A container merely called postgres is not an application claim."""
        with mock.patch.object(lxc_apps, "_fetch_tracking_hints", lambda: self.HINTS):
            index = lxc_apps._docker_container_slug_index()
        self.assertNotIn("postgres", index)

    def test_declared_container_resolves_a_name_heuristics_cannot(self):
        with mock.patch.object(lxc_apps, "_fetch_tracking_hints", lambda: self.HINTS), \
             mock.patch.object(lxc_apps, "_catalog_lookup", lambda slug: {"name": "Immich"} if slug == "immich" else None):
            meta = lxc_apps._docker_service_catalog_meta(
                "immich-server", "immich_server",
                "ghcr.io/immich-app/immich-server:release",
            )
        self.assertEqual(meta["slug"], "immich")
        self.assertEqual(meta["name"], "Immich")
        self.assertEqual(meta["logo_url"], "https://example.invalid/immich.webp")


class UpdateNotificationWordingTests(unittest.TestCase):
    def test_alert_leads_with_the_application_name(self):
        payload = lxc_apps._docker_stack_notification_payload(
            102,
            {"state": {}},
            {"images": [{
                "reference": "vaultwarden/server:latest",
                "display_name": "Vaultwarden",
                "installed_version": "1.37.2",
                "available_version": "1.38.0",
                "update_available": True,
                "remote_digest": "sha256:" + "a" * 64,
            }]},
            "vaultwarden",
        )
        self.assertIsNotNone(payload)
        self.assertIn("• Vaultwarden (vaultwarden/server:latest): 1.37.2 → 1.38.0", payload["details"])

    def test_unnamed_image_keeps_its_reference(self):
        payload = lxc_apps._docker_stack_notification_payload(
            102,
            {"state": {}},
            {"images": [{
                "reference": "valkey/valkey:8-bookworm",
                "installed_version": None,
                "available_version": None,
                "update_available": True,
                "remote_digest": "sha256:" + "b" * 64,
            }]},
            "immich",
        )
        self.assertIn("• valkey/valkey:8-bookworm: new registry digest", payload["details"])
