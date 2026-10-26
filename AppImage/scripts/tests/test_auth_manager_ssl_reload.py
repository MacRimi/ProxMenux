import importlib.util
import json
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "auth_manager.py"
SPEC = importlib.util.spec_from_file_location("auth_manager_ssl_under_test", MODULE_PATH)
auth_manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth_manager)


class _FakeSslSocket:
    def __init__(self, context):
        self.context = context


class ProxmoxCertificateHotReloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("openssl") is None:
            raise unittest.SkipTest("openssl is required for TLS fixture generation")
        cls.fixture_dir = tempfile.TemporaryDirectory()
        fixture_path = Path(cls.fixture_dir.name)
        cls.pairs = []
        for name in ("original", "renewed"):
            cert_path = fixture_path / f"{name}.pem"
            key_path = fixture_path / f"{name}.key"
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048",
                    "-nodes", "-days", "1", "-subj", f"/CN={name}.test",
                    "-keyout", str(key_path), "-out", str(cert_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls.pairs.append((cert_path, key_path))

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        temp_path = Path(self.temp_dir.name)
        self.active_cert = temp_path / "pveproxy-ssl.pem"
        self.active_key = temp_path / "pveproxy-ssl.key"
        self.ssl_config = temp_path / "ssl_config.json"
        self._install_pair(0)
        self._write_config("proxmox")

        self.patch = mock.patch.multiple(
            auth_manager,
            SSL_CONFIG_FILE=self.ssl_config,
            PROXMOX_CUSTOM_CERT_PATH=str(self.active_cert),
            PROXMOX_CUSTOM_KEY_PATH=str(self.active_key),
            PROXMOX_CERT_PATH=str(temp_path / "missing-pve-ssl.pem"),
            PROXMOX_KEY_PATH=str(temp_path / "missing-pve-ssl.key"),
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self._reset_runtime)

    def _reset_runtime(self):
        with auth_manager._SSL_RUNTIME_LOCK:
            auth_manager._SSL_RUNTIME_CONTEXT = None
            auth_manager._SSL_RUNTIME_FINGERPRINT = ""
            auth_manager._SSL_RUNTIME_CERT_PATH = ""
            auth_manager._SSL_RUNTIME_KEY_PATH = ""
            auth_manager._SSL_RUNTIME_SOURCE = "none"
            auth_manager._SSL_RUNTIME_LAST_REFRESH_ERROR = ""

    def _install_pair(self, index):
        cert_path, key_path = self.pairs[index]
        shutil.copyfile(cert_path, self.active_cert)
        shutil.copyfile(key_path, self.active_key)

    def _write_config(self, source):
        self.ssl_config.write_text(json.dumps({
            "enabled": True,
            "cert_path": str(self.active_cert),
            "key_path": str(self.active_key),
            "source": source,
        }))

    def _create_context(self):
        return auth_manager.create_reloadable_ssl_context(
            str(self.active_cert), str(self.active_key)
        )

    def test_unchanged_pair_does_not_rebuild_the_context(self):
        context = self._create_context()
        ssl_socket = _FakeSslSocket(context)

        with mock.patch.object(
            auth_manager,
            "reload_server_ssl_context",
            wraps=auth_manager.reload_server_ssl_context,
        ) as reload_mock:
            context.sni_callback(ssl_socket, "proxmenux.test", context)

        reload_mock.assert_not_called()
        self.assertIs(ssl_socket.context, context)

    def test_valid_renewed_pair_is_activated_during_the_handshake(self):
        context = self._create_context()
        previous_fingerprint = auth_manager._SSL_RUNTIME_FINGERPRINT
        self._install_pair(1)
        ssl_socket = _FakeSslSocket(context)

        context.sni_callback(ssl_socket, "proxmenux.test", context)

        self.assertNotEqual(previous_fingerprint, auth_manager._SSL_RUNTIME_FINGERPRINT)
        self.assertIs(ssl_socket.context, auth_manager._SSL_RUNTIME_CONTEXT)
        self.assertIsNot(ssl_socket.context, context)
        self.assertEqual(auth_manager._SSL_RUNTIME_LAST_REFRESH_ERROR, "")

    def test_mismatched_pair_keeps_the_previous_context(self):
        context = self._create_context()
        previous_fingerprint = auth_manager._SSL_RUNTIME_FINGERPRINT
        shutil.copyfile(self.pairs[1][0], self.active_cert)
        ssl_socket = _FakeSslSocket(context)

        context.sni_callback(ssl_socket, "proxmenux.test", context)

        self.assertEqual(previous_fingerprint, auth_manager._SSL_RUNTIME_FINGERPRINT)
        self.assertIs(auth_manager._SSL_RUNTIME_CONTEXT, context)
        self.assertIs(ssl_socket.context, context)
        self.assertTrue(auth_manager._SSL_RUNTIME_LAST_REFRESH_ERROR)

    def test_custom_certificate_source_is_not_examined_automatically(self):
        self._write_config("custom")
        context = self._create_context()
        previous_fingerprint = auth_manager._SSL_RUNTIME_FINGERPRINT
        self._install_pair(1)
        ssl_socket = _FakeSslSocket(context)

        context.sni_callback(ssl_socket, "proxmenux.test", context)

        self.assertEqual(previous_fingerprint, auth_manager._SSL_RUNTIME_FINGERPRINT)
        self.assertIs(ssl_socket.context, context)

    def test_first_real_tls_connection_receives_the_renewed_certificate(self):
        server_context = self._create_context()
        self._install_pair(1)
        server_socket, client_socket = socket.socketpair()
        server_socket.settimeout(5)
        client_socket.settimeout(5)
        server_error = []

        def serve_once():
            try:
                with server_context.wrap_socket(server_socket, server_side=True) as tls_socket:
                    tls_socket.recv(1)
            except Exception as error:  # pragma: no cover - asserted below
                server_error.append(error)

        thread = threading.Thread(target=serve_once)
        thread.start()
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_NONE
        with client_context.wrap_socket(
            client_socket, server_hostname="proxmenux.test"
        ) as tls_client:
            received_der = tls_client.getpeercert(binary_form=True)
            tls_client.sendall(b"x")
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(server_error, [])
        renewed_pem = self.pairs[1][0].read_text()
        self.assertEqual(received_der, ssl.PEM_cert_to_DER_cert(renewed_pem))

    def test_tls_connection_without_sni_also_receives_the_renewed_certificate(self):
        server_context = self._create_context()
        self._install_pair(1)
        server_socket, client_socket = socket.socketpair()
        server_socket.settimeout(5)
        client_socket.settimeout(5)
        server_error = []

        def serve_once():
            try:
                with server_context.wrap_socket(server_socket, server_side=True) as tls_socket:
                    tls_socket.recv(1)
            except Exception as error:  # pragma: no cover - asserted below
                server_error.append(error)

        thread = threading.Thread(target=serve_once)
        thread.start()
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_NONE
        with client_context.wrap_socket(client_socket) as tls_client:
            received_der = tls_client.getpeercert(binary_form=True)
            tls_client.sendall(b"x")
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(server_error, [])
        renewed_pem = self.pairs[1][0].read_text()
        self.assertEqual(received_der, ssl.PEM_cert_to_DER_cert(renewed_pem))


if __name__ == "__main__":
    unittest.main()
