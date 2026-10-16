"""The VM wizard must not accept failed ISO downloads as installation media.

Run its function logic against a loopback HTTP fixture. Redirect the fixed
native ISO directory only in the loaded test copy and stub Proxmox/UI services.
No product script is sourced, no guest operation runs, and no public network
or real ISO storage is accessed.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[3]
CREATOR = ROOT / "scripts/vm/vm_creator.sh"
PAYLOAD = b"fixture installation media\x00\x01\n"
REAL_WGET = shutil.which("wget")


class MediaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/missing.iso":
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/partial.iso":
            self.send_response(200)
            self.send_header("Content-Length", "1024")
            self.end_headers()
            self.wfile.write(b"partial")
            self.close_connection = True
            return
        body = b"" if self.path == "/empty.iso" else PAYLOAD
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", 'attachment; filename="remote-name.iso"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class VmIsoDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REAL_WGET is None:
            raise RuntimeError("These offline tests require wget, as the VM wizard does")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MediaHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.http = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vm-iso-download-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.iso = self.directory / "installation media.iso"
        self.qm_log = self.directory / "qm.log"
        self.wget_log = self.directory / "wget.log"
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        # Route only the optional fixed VirtIO/SourceForge endpoints to our
        # fixture. Wget still performs the actual HTTP transfer and file I/O.
        assert REAL_WGET is not None
        wrapper = self.bin / "wget"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$*" >> "$WGET_LOG"\n'
            'args=("$@")\n'
            'for i in "${!args[@]}"; do\n'
            ' case "${args[$i]}" in\n'
            '  https://fedorapeople.org/*) args[$i]="$VIRTIO_FIXTURE_URL";;\n'
            '  https://sourceforge.net/*) args[$i]="$HTTP_FIXTURE/success.iso";;\n'
            ' esac\n'
            ' if [[ "${args[$i]}" == http://* || "${args[$i]}" == https://* ]]; then\n'
            '  [[ "${args[$i]}" == "$HTTP_FIXTURE"/* ]] || exit 98\n'
            ' fi\n'
            'done\n'
            'for i in "${!args[@]}"; do\n'
            ' if [[ "${args[$i]}" == -O ]]; then\n'
            '  case "${args[$((i+1))]}" in "$FIXTURE_DIR"/*) ;; *) exit 97;; esac\n'
            ' fi\n'
            'done\n'
            f"exec {shlex.quote(REAL_WGET)} --no-config --no-proxy --tries=1 --timeout=1 "
            '"${args[@]}"\n'
        )
        wrapper.chmod(0o755)

    def run_wizard(self, route="/success.iso", windows=False, overwrite=True, url=None,
                   caller_iso_dir=None):
        source = CREATOR.read_text()
        functions = "\n\n".join(re.findall(r"^function \w+\(\) \{\n.*?^\}", source, re.M | re.S))
        self.assertIn("function create_vm()", functions)
        # Only relocate this external filesystem anchor. Keep all predicates,
        # transfers and promotion logic unchanged, without a production hook.
        self.assertIn("/var/lib/vz/template/iso", functions)
        functions = functions.replace("/var/lib/vz/template/iso", "${FIXTURE_DIR}")
        prelude = r'''
            translate() { printf '%s' "$1"; }
            msg_ok() { printf 'OK:%s\n' "$*"; }
            msg_error() { printf 'ERROR:%s\n' "$*"; }
            msg_warn() { printf 'WARN:%s\n' "$*"; }
            msg_info() { :; }
            msg_success() { :; }
            qm() { printf '%q ' "$@" >> "$QM_LOG"; printf '\n' >> "$QM_LOG"; }
            pvesm() { printf 'Name Type Status\nfixture dir active\n'; }
            select_storage_target() { printf fixture; }
            # No next menu, start, or guest-facing process is launched.
            bash() { :; }
            whiptail() {
                if [[ " $* " == *' --yesno '* ]]; then
                    return "$OVERWRITE_STATUS"
                fi
                if [[ ! -f "$DIALOG_ONCE" ]]; then
                    : > "$DIALOG_ONCE"
                    printf '1' >&2
                    return 0
                fi
                return 1
            }
            IMPORT_DISKS=(); PASSTHROUGH_DISKS=(); VIRTUAL_DISKS=(); CONTROLLER_NVME_PCIS=()
            VMID=99999; HN=fixture; CORE_COUNT=1; RAM_SIZE=512; BRG=fixture
            MAC='02:00:00:00:00:01'; VLAN=''; MTU=''; BIOS_TYPE=''; CPU_TYPE=''
            MACHINE=''; SERIAL_PORT=''; START_VM=no; WIZARD_ADD_GPU=no
            TAB=''; GN=''; CL=''
            create_vm
        '''
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                   ISO_PATH=str(self.iso), ISO_URL=url if url is not None else self.http + route,
                   ISO_VOLID="local:iso/installation media.iso",
                   OS_TYPE="2" if windows else "3",
                   QM_LOG=str(self.qm_log), WGET_LOG=str(self.wget_log),
                   DIALOG_ONCE=str(self.directory / "dialog-once"), FIXTURE_DIR=str(self.directory),
                   OVERWRITE_STATUS="0" if overwrite else "1", HTTP_FIXTURE=self.http,
                   VIRTIO_FIXTURE_URL=self.http + route)
        env.pop("ISO_DIR", None)
        if caller_iso_dir is not None:
            env["ISO_DIR"] = str(caller_iso_dir)
        return subprocess.run(["bash", "--noprofile", "--norc", "-c", functions + prelude],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=15)

    def qm_calls(self):
        return self.qm_log.read_text() if self.qm_log.exists() else ""

    def test_http_failure_stops_before_creating_a_guest(self):
        result = self.run_wizard("/missing.iso")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.qm_calls(), "")
        self.assertNotIn("OK:ISO image downloaded", result.stdout)
        self.assertIn("ERROR:Failed to download ISO image", result.stdout)

    def test_partial_transfer_is_not_published_as_cached_media(self):
        result = self.run_wizard("/partial.iso")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.qm_calls(), "")
        self.assertFalse(self.iso.exists(), "A failed transfer must not become reusable media")

    def test_an_empty_cached_download_is_retried(self):
        self.iso.write_bytes(b"")
        result = self.run_wizard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.iso.read_bytes(), PAYLOAD)
        self.assertIn("create ", self.qm_calls())

    def test_virtio_download_keeps_native_storage_despite_caller_environment(self):
        self.iso.write_bytes(PAYLOAD)
        unrelated = self.directory / "unrelated directory"
        unrelated.mkdir()
        result = self.run_wizard(windows=True, caller_iso_dir=unrelated)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        driver = self.directory / "virtio-win.iso"
        self.assertTrue(driver.is_file(), result.stdout + result.stderr)
        self.assertEqual(driver.read_bytes(), PAYLOAD)
        self.assertIn("-ide3 ", self.qm_calls())
        self.assertEqual(list(unrelated.iterdir()), [])

    def test_failed_virtio_fetch_is_not_selected_for_attachment(self):
        self.iso.write_bytes(PAYLOAD)
        result = self.run_wizard("/missing.iso", windows=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("-ide3 ", self.qm_calls())
        self.assertNotIn("OK:VirtIO driver ISO downloaded successfully.", result.stdout)
        self.assertIn("ERROR:Failed to download VirtIO driver ISO.", result.stdout)
        self.assertFalse((self.directory / "virtio-win.iso").exists())


    def test_successful_virtio_replacement_preserves_existing_permissions(self):
        self.iso.write_bytes(PAYLOAD)
        driver = self.directory / "virtio-win.iso"
        driver.write_bytes(b"previous driver")
        driver.chmod(0o640)
        result = self.run_wizard(windows=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(driver.read_bytes(), PAYLOAD)
        self.assertEqual(driver.stat().st_mode & 0o777, 0o640)

    def test_empty_http_success_is_rejected(self):
        result = self.run_wizard("/empty.iso")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.qm_calls(), "")
        self.assertFalse(self.iso.exists())
        self.assertEqual({p.name for p in self.directory.iterdir()}, {"bin", "wget.log"})

    def test_existing_nonempty_media_is_reused_without_fetching(self):
        self.iso.write_bytes(b"existing installation media")
        result = self.run_wizard("/missing.iso")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.iso.read_bytes(), b"existing installation media")
        self.assertFalse(self.wget_log.exists())
        self.assertIn("-ide2 ", self.qm_calls())

    def test_sourceforge_download_keeps_the_selected_destination_name(self):
        result = self.run_wizard(url="https://sourceforge.net/projects/fixture/iso/download")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.iso.read_bytes(), PAYLOAD)
        self.assertFalse((self.directory / "remote-name.iso").exists())
        self.assertEqual({p.name for p in self.directory.iterdir()},
                         {"bin", "wget.log", "qm.log", self.iso.name})

    def test_failed_virtio_replacement_preserves_previous_media(self):
        self.iso.write_bytes(PAYLOAD)
        driver = self.directory / "virtio-win.iso"
        driver.write_bytes(b"previous driver")
        driver.chmod(0o640)
        result = self.run_wizard("/partial.iso", windows=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(driver.read_bytes(), b"previous driver")
        self.assertEqual(driver.stat().st_mode & 0o777, 0o640)
        self.assertNotIn("-ide3 ", self.qm_calls())
        self.assertNotIn("OK:VirtIO driver ISO downloaded successfully.", result.stdout)

    def test_declining_virtio_replacement_reuses_previous_media(self):
        self.iso.write_bytes(PAYLOAD)
        driver = self.directory / "virtio-win.iso"
        driver.write_bytes(b"previous driver")
        result = self.run_wizard("/missing.iso", windows=True, overwrite=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(driver.read_bytes(), b"previous driver")
        self.assertFalse(self.wget_log.exists())
        self.assertIn("-ide3 ", self.qm_calls())

    def test_empty_cached_virtio_media_is_retried_not_attached(self):
        self.iso.write_bytes(PAYLOAD)
        driver = self.directory / "virtio-win.iso"
        driver.write_bytes(b"")
        result = self.run_wizard("/missing.iso", windows=True, overwrite=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.wget_log.exists())
        self.assertNotIn("-ide3 ", self.qm_calls())
        self.assertIn("ERROR:Failed to download VirtIO driver ISO.", result.stdout)

    def test_a_directory_cannot_be_published_as_media(self):
        self.iso.mkdir()
        result = self.run_wizard()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.qm_calls(), "")
        self.assertTrue(self.iso.is_dir())
        self.assertEqual(list(self.iso.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
