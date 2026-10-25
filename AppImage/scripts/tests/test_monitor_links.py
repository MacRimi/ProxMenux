import json
import socket
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "AppImage/scripts"))

import monitor_links as links


class MonitorLinksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        storage = self.root / "storage.cfg"
        storage.write_text("dir: local\n\tpath /var/lib/vz\n\npbs: Lab\n\tdatastore store1\n\tserver 10.0.0.49\n\n"
                           "pbs: Cloud\n\tdatastore x\n\tserver pbs.example.com\n\tport 8443\n")
        patches = [
            mock.patch.object(links, "LINKS_FILE", self.root / "links.json"),
            mock.patch.object(links, "SSL_CONFIG_FILE", self.root / "ssl.json"),
            mock.patch.object(links, "STORAGE_CFG", storage),
            mock.patch.object(links, "_own_addresses", return_value=set()),
            mock.patch.object(links.socket, "getaddrinfo", side_effect=self.fixture_addresses),
            mock.patch.object(links.pbs_manager, "get_platform", return_value={"product": "pve", "hostname": "amd"}),
            mock.patch.object(links.pbs_manager, "public_servers", return_value=[]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        links._probe_cache.clear()
        cluster = [{"type": "cluster", "name": "Casa"},
                   {"type": "node", "name": "amd", "ip": "10.0.0.55", "local": 1},
                   {"type": "node", "name": "constructor", "ip": "10.0.0.50", "local": 0}]
        self.run_patch = mock.patch.object(links.subprocess, "run",
                                           return_value=SimpleNamespace(returncode=0, stdout=json.dumps(cluster)))
        self.run_patch.start()
        self.addCleanup(self.run_patch.stop)

    @staticmethod
    def fixture_addresses(host: str, _port):
        address = {"localhost": "127.0.0.1", "pbs.example.com": "203.0.113.49"}.get(host, host)
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, 0))]

    def test_normalize_url_keeps_only_the_origin_and_rejects_credentials(self):
        self.assertEqual(links.normalize_url("192.168.0.49:8008/dashboard?x=1"), "https://192.168.0.49:8008")
        self.assertEqual(links.normalize_url("http://pve.lan"), "http://pve.lan")
        for bad in ("", "ftp://host", "https://user:pass@host", "https://host:99999", "javascript:alert(1)"):
            with self.subTest(bad=bad), self.assertRaises(links.LinkError):
                links.normalize_url(bad)

    def test_discovers_other_cluster_nodes_and_pbs_without_the_local_node(self):
        probed = []
        with mock.patch.object(links, "_probe", side_effect=lambda url: probed.append(url) or url.endswith("10.0.0.50:8008")), \
                mock.patch.object(links, "_is_private", side_effect=lambda host: host.startswith("10.")):
            result = links.list_links()
        by_key = {row["key"]: row for row in result["links"]}
        self.assertEqual(result["self"]["name"], "amd")
        self.assertNotIn("cluster:amd", by_key)
        self.assertEqual(by_key["cluster:constructor"]["status"], "online")
        self.assertEqual(by_key["pbs:10.0.0.49"]["native_url"], "https://10.0.0.49:8007")
        self.assertEqual(by_key["pbs:10.0.0.49"]["status"], "offline")
        # A public PBS is listed with its own interface but never probed unasked.
        self.assertEqual(by_key["pbs:pbs.example.com"]["status"], "unknown")
        self.assertEqual(by_key["pbs:pbs.example.com"]["native_url"], "https://pbs.example.com:8443")
        self.assertFalse(any("example.com" in url for url in probed))

    def test_pbs_installed_on_this_host_opens_its_own_interface_and_is_never_probed(self):
        links.STORAGE_CFG.write_text("pbs: PBS\n\tdatastore PBS\n\tserver localhost\n\n"
                                     "pbs: Same\n\tdatastore x\n\tserver 10.0.0.55\n\n"
                                     "pbs: Lab\n\tdatastore store1\n\tserver 10.0.0.49\n")
        probed = []
        with mock.patch.object(links, "_own_addresses", return_value={"10.0.0.55"}), \
                mock.patch.object(links, "_probe", side_effect=lambda url: probed.append(url) or False), \
                mock.patch.object(links, "_is_private", return_value=True):
            result = links.list_links()
        pbs_rows = [row for row in result["links"] if row["group"] == "pbs"]
        self.assertEqual([row["key"] for row in pbs_rows], ["pbs:local", "pbs:10.0.0.49"])
        local = pbs_rows[0]
        self.assertEqual((local["name"], local["local"], local["url"], local["status"]), ("PBS", True, None, "local"))
        self.assertIsNone(local["native_url"])
        self.assertFalse(any("localhost" in url or "10.0.0.55" in url for url in probed))
        self.assertFalse(pbs_rows[1]["local"])

    def test_loopback_names_are_this_host(self):
        with mock.patch.object(links, "_own_addresses", return_value=set()):
            self.assertTrue(links._is_this_host("127.0.0.1"))
            self.assertTrue(links._is_this_host("::1"))
            self.assertFalse(links._is_this_host("10.0.0.49"))

    def test_pbs_host_lists_only_manual_entries(self):
        links.pbs_manager.get_platform.return_value = {"product": "pbs", "hostname": "pbs-lab"}
        links.add_link({"name": "amd", "url": "https://10.0.0.55:8008", "product": "pve"})
        with mock.patch.object(links, "_probe", return_value=True):
            result = links.list_links()
        self.assertEqual([row["name"] for row in result["links"]], ["amd"])
        self.links_run_not_called()

    def links_run_not_called(self):
        self.assertFalse(any(call.args and call.args[0][:1] == ["pvesh"] for call in links.subprocess.run.call_args_list))

    def test_manual_entries_overrides_and_hidden_detected_nodes(self):
        key = links.add_link({"name": "lab", "url": "10.0.0.46:8008", "product": "pve"})
        with self.assertRaises(links.LinkError):
            links.add_link({"url": "https://10.0.0.46:8008"})
        links.update_link("cluster:constructor", {"url": "https://constructor.lan:8008"})
        links.update_link("pbs:10.0.0.49", {"hidden": True})
        with mock.patch.object(links, "_probe", return_value=False), \
                mock.patch.object(links, "_is_private", return_value=True):
            visible = {row["key"]: row for row in links.list_links()["links"]}
            everything = {row["key"]: row for row in links.list_links(include_hidden=True)["links"]}
        self.assertEqual(visible[key]["url"], "https://10.0.0.46:8008")
        self.assertEqual(visible["cluster:constructor"]["url"], "https://constructor.lan:8008")
        self.assertNotIn("pbs:10.0.0.49", visible)
        self.assertTrue(everything["pbs:10.0.0.49"]["hidden"])
        with self.assertRaises(links.LinkError):
            links.delete_link("cluster:constructor")
        links.delete_link(key)
        self.assertEqual(json.loads((self.root / "links.json").read_text())["manual"], [])
        self.assertEqual((self.root / "links.json").stat().st_mode & 0o777, 0o600)

    def test_cached_list_is_served_without_new_probes_and_renewed_when_stale(self):
        links._snapshot.update(at=0.0, data=None)
        self.addCleanup(links._snapshot.update, at=0.0, data=None)
        links.update_link("pbs:10.0.0.49", {"hidden": True})
        with mock.patch.object(links, "_probe", return_value=True) as probe, \
                mock.patch.object(links, "_is_private", return_value=True):
            first = links.cached_links()
            calls = probe.call_count
            again = links.cached_links()
            self.assertEqual(probe.call_count, calls)
            self.assertEqual(first, again)
            self.assertNotIn("pbs:10.0.0.49", [row["key"] for row in first["links"]])
            self.assertIn("pbs:10.0.0.49", [row["key"] for row in links.cached_links(include_hidden=True)["links"]])
            links._snapshot["at"] -= links.PROBE_TTL + 1
            with mock.patch.object(links.threading, "Thread") as thread:
                stale = links.cached_links()
            self.assertEqual(stale, first)
            thread.assert_called_once()

    def test_unknown_keys_are_rejected(self):
        for key in ("other:x", "cluster:../../etc", "manual:nope"):
            with self.subTest(key=key), self.assertRaises(links.LinkError):
                links.update_link(key, {"hidden": True})

    def test_probe_sends_no_credentials_and_needs_a_monitor_answer(self):
        seen = []

        class Response:
            status = 200

            def __init__(self, body):
                self.body = body

            def read(self, _size):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def urlopen(request, timeout, context):
            seen.append(request)
            return Response(b'{"auth_enabled": true}' if "monitor" in request.full_url else b"<html>")

        with mock.patch.object(links.urllib.request, "urlopen", side_effect=urlopen):
            self.assertTrue(links._probe("https://monitor:8008"))
            self.assertFalse(links._probe("https://other:8008"))
        self.assertTrue(all(request.full_url.endswith("/api/auth/status") for request in seen))
        self.assertTrue(all("Authorization" not in request.headers for request in seen))


if __name__ == "__main__":
    unittest.main()
