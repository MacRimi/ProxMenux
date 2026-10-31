"""PBS platform, HTTPS protocol, authorization and isolated AppImage regressions."""

import ast
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "AppImage/scripts"))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from flask import Flask
import jwt
import auth_manager
import pbs_manager as pbs
from flask_pbs_routes import pbs_bp


class PlatformTests(unittest.TestCase):
    def test_supported_platforms_and_partial_dpkg_failure(self):
        module = pbs.detect_platform.__globals__
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "os-release"
            for package, version, suite, product in (
                ("pve-manager", "8.4.15", "bookworm", "pve"),
                ("pve-manager", "9.2.1", "trixie", "pve"),
                ("proxmox-backup-server", "3.4.0-1", "bookworm", "pbs"),
                ("proxmox-backup-server", "4.2.5-1", "trixie", "pbs"),
            ):
                release.write_text(f'VERSION_CODENAME="{suite}"\n')
                output = f"{package}\tinstall ok installed\t{version}\n"
                with self.subTest(product=product, version=version), \
                        mock.patch.dict(module, {"OS_RELEASE": release}), \
                        mock.patch.object(subprocess, "run", return_value=SimpleNamespace(stdout=output, returncode=1)):
                    detected = pbs.detect_platform()
                self.assertEqual(detected["product"], product)
                self.assertEqual(detected["version"], version)
                self.assertTrue(detected["supported"])

    def test_client_only_and_removed_server_are_not_pbs(self):
        for output in ("proxmox-backup-client\tinstall ok installed\t4.2.5\n",
                       "proxmox-backup-server\tdeinstall ok config-files\t4.2.5\n", ""):
            with self.subTest(output=output), mock.patch.object(subprocess, "run", return_value=SimpleNamespace(stdout=output)):
                self.assertEqual(pbs.detect_platform()["product"], "unknown")

    def test_pbs_utilities_preserve_sources_and_never_call_pve_policy(self):
        helper = ROOT / "scripts/global/repository-functions.sh"
        for supported in (True, False):
            harness = f'''
source {shlex.quote(str(helper))}
pmx_platform_field() {{ if [[ "$1" == product ]]; then echo pbs; else echo {str(supported).lower()}; fi; }}
msg_info() {{ :; }}
msg_error() {{ :; }}
translate() {{ printf '%s' "$1"; }}
pveversion() {{ echo 'FORBIDDEN: pveversion'; return 90; }}
repository_policy() {{ echo 'FORBIDDEN: repository mutation'; return 90; }}
apt-get() {{ echo 'FORBIDDEN: apt'; return 90; }}
ensure_repositories
'''
            result = subprocess.run(["bash"], input=harness, text=True, capture_output=True)
            self.assertNotIn("FORBIDDEN", result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0 if supported else 1)


class PBSManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        import monitor_links
        storage = self.root / 'storage.cfg'
        storage.write_text('')
        for boundary in (
            mock.patch.object(pbs, 'get_platform', return_value={'product': 'pve', 'hostname': 'fixture'}),
            mock.patch.object(pbs.shutil, 'which', return_value=None),
            mock.patch.object(monitor_links, 'STORAGE_CFG', storage),
            mock.patch.object(monitor_links, '_own_addresses', return_value=set()),
        ):
            boundary.start()
            self.addCleanup(boundary.stop)
        patch = mock.patch.multiple(auth_manager, CONFIG_DIR=self.root, AUTH_CONFIG_FILE=self.root / "auth.json")
        patch.start(); self.addCleanup(patch.stop)
        auth_manager.save_auth_config({"enabled": True, "username": "admin", "password_hash": "configured",
                                       "jwt_secret": "s" * 48, "api_tokens": [], "revoked_tokens": []})
        auth_manager._invalidate_revoked_cache()
        pbs._status_cache.clear()
        self.server = {"name": "Backup", "url": "https://pbs.test:8007", "token_id": "audit@pbs!monitor",
                       "token_secret": "fixture-token-secret", "fingerprint": "a" * 64}
        app = Flask(__name__); app.register_blueprint(pbs_bp)
        self.client = app.test_client()
        self.headers = {"Authorization": "Bearer " + auth_manager.generate_token("admin")}

    def test_save_redacts_secret_and_probes_authenticated_endpoint(self):
        with mock.patch.object(pbs, "_remote_get", return_value=[]) as request:
            identifier = pbs.save_server(self.server)
            request.assert_called_once()
            self.assertEqual(request.call_args.args[1], "/status/datastore-usage")
        self.assertEqual((self.root / "pbs_servers.json").stat().st_mode & 0o777, 0o600)
        public = pbs.public_servers()
        self.assertEqual(public[0]["id"], identifier)
        self.assertNotIn("fixture-token-secret", json.dumps(public))
        self.assertTrue(public[0]["has_token"])
        with mock.patch.object(pbs, "_remote_get", return_value=[]):
            pbs.save_server({"id": identifier, "name": "Renamed"})
        self.assertEqual(pbs._load_servers()[0]["token_secret"], "fixture-token-secret")
        pbs.delete_server(identifier)
        self.assertEqual(pbs.public_servers(), [])

    def test_failed_credentials_or_invalid_config_do_not_replace_saved_connection(self):
        with mock.patch.object(pbs, "_remote_get", return_value=[]):
            identifier = pbs.save_server(self.server)
        original = (self.root / "pbs_servers.json").read_bytes()
        with mock.patch.object(pbs, "_remote_get", side_effect=pbs.PBSError("Rejected token")):
            with self.assertRaises(pbs.PBSError):
                pbs.save_server({**self.server, "id": identifier, "token_secret": "wrong"})
        for changes in ({"url": "http://pbs.test"}, {"url": "https://user:pass@pbs.test"},
                        {"fingerprint": "bad-pin"}, {"token_id": "not-a-token"},
                        {"token_secret": "line\nbreak"}):
            with self.subTest(changes=changes), self.assertRaises(pbs.PBSError):
                pbs.save_server({**self.server, **changes, "id": identifier})
        self.assertEqual((self.root / "pbs_servers.json").read_bytes(), original)

    def test_remote_partial_failure_is_unknown_instead_of_zero(self):
        def remote(server, endpoint):
            if endpoint == "/version": return {"version": "4.2.5"}
            if endpoint == "/status/datastore-usage": return [{"store": "backup", "total": 100, "used": 30, "avail": 70}]
            if endpoint == "/admin/verify": raise pbs.PBSError("Permission denied")
            return []
        with mock.patch.object(pbs, "_remote_get", side_effect=remote) as request:
            identifier = pbs.save_server(self.server)
            result = pbs.get_status(identifier)
            count = request.call_count
            self.assertEqual(pbs.get_status(identifier), result)
            self.assertEqual(request.call_count, count)
        self.assertEqual(result["datastores"][0]["name"], "backup")
        self.assertIsNone(result["verify"])
        self.assertIn("verify", result["errors"])

    def test_unmounted_removable_datastore_has_no_fabricated_capacity(self):
        with mock.patch.object(pbs, "_cli", return_value=[{"name": "removable", "path": "/not-mounted", "backing-device": "uuid"}]), \
                mock.patch.object(pbs.os.path, "ismount", return_value=False), \
                mock.patch.object(pbs.shutil, "disk_usage") as usage:
            result = pbs._local_datastores()
        usage.assert_not_called()
        self.assertIsNone(result[0]["total"])
        self.assertIn("error", result[0])

    def test_local_status_reads_pbs_commands_and_filesystem_capacity(self):
        def run(command, **kwargs):
            self.assertNotIn("shell", kwargs)
            self.assertIn(command[0], ("proxmox-backup-manager", "proxmox-backup-debug"))
            self.assertEqual(command[-2:], ["--output-format", "json"])
            data = [{"name": "backup", "path": str(self.root)}] if command[1:3] == ["datastore", "list"] else []
            if command[:4] == ["proxmox-backup-debug", "api", "get", "/admin/verify"]:
                data = [{"id": "v-1", "store": "backup", "schedule": "daily", "last-run-state": "OK"}]
            return SimpleNamespace(stdout=json.dumps(data), returncode=0)
        with mock.patch.object(pbs, "get_platform", return_value={"product": "pbs", "version": "4.2.5"}), \
                mock.patch.object(pbs, "_local_services", return_value={key: "active" for key in pbs.PBS_SERVICES}), \
                mock.patch.object(pbs.subprocess, "run", side_effect=run), \
                mock.patch.object(pbs.shutil, "disk_usage", return_value=SimpleNamespace(total=100, used=30, free=70)):
            result = pbs.get_status("local")
        self.assertEqual(result["version"], "4.2.5")
        self.assertEqual(result["errors"], {})
        self.assertEqual(result["datastores"][0]["used"], 30)
        self.assertEqual(set(result["services"]), set(pbs.PBS_SERVICES))
        # Jobs come from the API, which carries the state of their last run.
        self.assertEqual(result["verify"][0]["last-run-state"], "OK")

    def test_pbs_installed_next_to_pve_is_read_locally_with_its_own_version(self):
        def run(command, **kwargs):
            if command[0] == "dpkg-query":
                return SimpleNamespace(stdout="4.2.8-1", returncode=0)
            return SimpleNamespace(stdout="[]", returncode=0)
        with mock.patch.object(pbs, "get_platform", return_value={"product": "pve", "version": "9.1.4", "hostname": "rimegra"}), \
                mock.patch.object(pbs.shutil, "which", return_value="/usr/sbin/proxmox-backup-manager"), \
                mock.patch.object(pbs.Path, "exists", return_value=True), \
                mock.patch.object(pbs, "_local_services", return_value={key: "active" for key in pbs.PBS_SERVICES}), \
                mock.patch.object(pbs.subprocess, "run", side_effect=run):
            self.assertTrue(pbs.local_available())
            result = pbs.get_status("local")
        self.assertEqual((result["name"], result["version"]), ("rimegra", "4.2.8-1"))
        with mock.patch.object(pbs, "get_platform", return_value={"product": "pve"}), \
                mock.patch.object(pbs.shutil, "which", return_value=None):
            self.assertFalse(pbs.local_available())

    def test_storage_pbs_without_a_connection_is_offered_with_its_address_and_fingerprint(self):
        import monitor_links
        storage = self.root / "storage.cfg"
        storage.write_text("pbs: Local\n\tserver localhost\n\tdatastore a\n\n"
                           "pbs: Lab\n\tserver 10.0.0.49\n\tdatastore b\n\tfingerprint AA:BB\n\n"
                           "pbs: Known\n\tserver pbs.test\n\tdatastore c\n\tport 8007\n")
        with mock.patch.object(monitor_links, "STORAGE_CFG", storage), \
                mock.patch.object(monitor_links, "_own_addresses", return_value=set()), \
                mock.patch.object(pbs, "is_pbs_host", return_value=False), \
                mock.patch.object(pbs, "local_available", return_value=False), \
                mock.patch.object(pbs, "_remote_get", return_value=[]):
            pbs.save_server(self.server)
            response = self.client.get("/api/pbs/servers", headers=self.headers)
        self.assertEqual(response.json["detected"],
                         [{"name": "Lab", "url": "https://10.0.0.49:8007", "fingerprint": "AA:BB"}])

    def test_password_sign_in_keeps_only_a_read_only_token(self):
        calls = []
        def request(server, method, endpoint, headers, form=None, rejected="", **kwargs):
            calls.append((method, endpoint, form))
            if endpoint == "/access/ticket":
                return {"ticket": "PBS:root@pam:ticket", "CSRFPreventionToken": "csrf", "username": "root@pam"}
            if "/token/" in endpoint and method == "POST":
                self.assertEqual(headers["CSRFPreventionToken"], "csrf")
                return {"tokenid": "root@pam!proxmenux-1", "value": "generated-secret"}
            return None
        login = {"name": "Lab", "url": "https://pbs.test:8007", "fingerprint": "a" * 64,
                 "username": "root@pam", "password": "fixture-password"}
        with mock.patch.object(pbs, "_remote_request", side_effect=request), \
                mock.patch.object(pbs, "_remote_get", return_value=[]):
            identifier = pbs.connect_with_password(login)
        self.assertIn(("PUT", "/access/acl", {"path": "/", "role": "Audit", "auth-id": "root@pam!proxmenux-1", "propagate": "1"}),
                      calls)
        stored = (self.root / "pbs_servers.json").read_text()
        self.assertNotIn("fixture-password", stored)
        self.assertIn("generated-secret", stored)
        self.assertEqual(pbs.public_servers()[0]["id"], identifier)

    def test_password_sign_in_removes_its_token_when_the_role_cannot_be_granted(self):
        calls = []
        def request(server, method, endpoint, headers, form=None, rejected="", **kwargs):
            calls.append((method, endpoint))
            if endpoint == "/access/ticket":
                return {"ticket": "t", "CSRFPreventionToken": "c"}
            if method == "POST":
                return {"tokenid": "audit@pbs!proxmenux-1", "value": "secret"}
            if method == "PUT":
                raise pbs.PBSError(rejected)
            return None
        with mock.patch.object(pbs, "_remote_request", side_effect=request):
            with self.assertRaisesRegex(pbs.PBSError, "Audit"):
                pbs.connect_with_password({"name": "Lab", "url": "https://pbs.test:8007", "fingerprint": "",
                                           "username": "audit@pbs", "password": "x"})
        self.assertEqual(calls[-1][0], "DELETE")
        self.assertEqual(pbs.public_servers(), [])

    def test_connection_api_requires_full_admin_and_does_not_return_secret(self):
        self.assertEqual(self.client.get("/api/pbs/servers").status_code, 401)
        with mock.patch.object(pbs, "_remote_get", return_value=[]):
            response = self.client.post("/api/pbs/servers", headers=self.headers, json=self.server)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("fixture-token-secret", response.text)
        payload = jwt.decode(self.headers["Authorization"].split()[1], "s" * 48,
                             algorithms=["HS256"], audience=auth_manager.JWT_AUDIENCE)
        payload["scope"] = "read_only"
        read_only = {"Authorization": "Bearer " + jwt.encode(payload, "s" * 48, algorithm="HS256")}
        self.assertEqual(self.client.post("/api/pbs/servers", headers=read_only, json=self.server).status_code, 403)
        self.assertEqual(self.client.get("/api/pbs/servers", headers=read_only).status_code, 200)
        auth_manager.save_auth_config({"enabled": False})
        self.assertEqual(self.client.post("/api/pbs/servers", json=self.server).status_code, 409)

    def test_health_uses_pbs_services_and_skips_pve_only_checks(self):
        source = ast.parse((ROOT / "AppImage/scripts/health_monitor.py").read_text())
        names = ("_check_pve_services", "_check_vms_cts_optimized", "_check_vms_cts_with_persistence",
                 "_check_proxmox_storages", "_check_proxmox_storage", "_check_lxc_disk_usage",
                 "_check_vm_disk_usage", "_check_lxc_mount_capacity", "_check_pve_storage_capacity")
        functions = [node for node in ast.walk(source) if isinstance(node, ast.FunctionDef)
                     and node.name in (*names, "_service_state")]
        persistence = mock.Mock(); persistence.is_error_active.return_value = False
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="active\n"))
        namespace = {"Dict": dict, "Any": object, "Optional": __import__('typing').Optional,
                     "PBS_SERVICES": pbs.PBS_SERVICES, "health_persistence": persistence,
                     "subprocess": SimpleNamespace(run=run), "os": __import__('os'), "time": __import__('time')}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<health-pbs-test>', 'exec'), namespace)
        instance = SimpleNamespace(platform_type="pbs", PVE_SERVICES=["pveproxy", "pvedaemon", "pvestatd", "pve-cluster"])
        instance.SERVICE_TRANSIENT_STATES, instance.SERVICE_SETTLE_SECONDS = (), 0
        instance._service_state = lambda service: namespace["_service_state"](instance, service)
        services = namespace["_check_pve_services"](instance)
        self.assertEqual(services["status"], "OK")
        self.assertEqual([call.args[0][2] for call in run.call_args_list], list(pbs.PBS_SERVICES))
        for name in names[1:]:
            result = namespace[name](instance)
            self.assertTrue(result is None or result.get("not_applicable"))

    def test_appimage_copies_and_imports_pbs_dependencies_outside_source_tree(self):
        builder = (ROOT / "AppImage/scripts/build_appimage.sh").read_text()
        modules = ("pbs_manager", "flask_pbs_routes", "auth_manager", "jwt_middleware")
        copies = []
        for name in modules:
            matches = [line for line in builder.splitlines() if line.startswith(f'cp "$SCRIPT_DIR/{name}.py"')]
            self.assertEqual(len(matches), 1, name)
            copies.extend(matches)
        copies.extend(line for line in builder.splitlines() if line.startswith('cp "$APPIMAGE_ROOT/../scripts/global/proxmox_platform.py"'))
        self.assertEqual(len(copies), len(modules) + 1)
        app = self.root / 'AppDir'; (app / 'usr/bin').mkdir(parents=True)
        q = shlex.quote
        shell = f'APP_DIR={q(str(app))}\nSCRIPT_DIR={q(str(ROOT / "AppImage/scripts"))}\nAPPIMAGE_ROOT={q(str(ROOT / "AppImage"))}\n' + '\n'.join(copies)
        subprocess.run(['bash', '-e', '-c', shell], check=True)
        code = f'import sys; sys.path.insert(0, {str(app / "usr/bin")!r}); import pbs_manager, flask_pbs_routes, proxmox_platform'
        subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=self.root, check=True, capture_output=True)


class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
                       .not_valid_after(datetime.now(timezone.utc) + timedelta(hours=1))
                       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                       .sign(key, hashes.SHA256()))
        cert_path, key_path = root / 'server.pem', root / 'server.key'
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cls.fingerprint = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
        cls.requests = []
        cls.response_status = 200

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except ConnectionResetError:
                    pass  # A rejected TLS pin closes before any HTTP request.

            def do_GET(self):
                cls.requests.append((self.path, self.headers.get("Authorization")))
                body = json.dumps({"data": []}).encode()
                self.send_response(cls.response_status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def log_message(self, *args): pass

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert_path, key_path)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5); cls.temporary.cleanup()

    def setUp(self):
        self.requests.clear(); type(self).response_status = 200
        self.connection = {"url": f'https://127.0.0.1:{self.server.server_port}',
                           "fingerprint": self.fingerprint, "token_id": "audit@pbs!monitor", "token_secret": "fake-secret"}

    def test_real_tls_matching_pin_sends_correct_pbs_authorization(self):
        self.assertEqual(pbs._remote_get(self.connection, '/status/datastore-usage'), [])
        self.assertEqual(self.requests, [('/api2/json/status/datastore-usage', 'PBSAPIToken=audit@pbs!monitor:fake-secret')])

    def test_bad_pin_and_untrusted_ca_send_no_http_credentials(self):
        for fingerprint in ('0' * 64, ''):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(pbs.PBSError) as caught:
                pbs._remote_get({**self.connection, "fingerprint": fingerprint}, '/status/datastore-usage')
            self.assertEqual(caught.exception.code, "pbs_fingerprint_mismatch" if fingerprint else "pbs_connect_failed")
            self.assertEqual(self.requests, [])

    def test_bad_credentials_and_redirects_are_rejected(self):
        for status in (401, 403, 302):
            type(self).response_status = status
            with self.subTest(status=status), self.assertRaises(pbs.PBSError) as caught:
                pbs._remote_get(self.connection, '/status/datastore-usage')
            self.assertEqual(caught.exception.code, "pbs_token_rejected" if status in (401, 403) else "pbs_invalid_response")


if __name__ == '__main__':
    unittest.main()
