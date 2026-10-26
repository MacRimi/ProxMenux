"""Offline acquisition fixtures; never source or run the administrative script.

Requires Bash, jq, curl, wget, gzip and unzip. Only bounded native functions
are loaded; HTTP clients are confined to a loopback fixture server. No host
package manager, Proxmox command, installer or VM is executed.
"""

from contextlib import contextmanager
import gzip
import http.server
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scripts/vm/synology.sh"
RAW = b"tiny offline loader fixture\x00\x01\x02" * 8
PLAIN = "alpine-redpill.v1.4.5.6.m-shell.img.gz"
VARIANTS = [
    "alpine-redpill.v1.4.5.6.m-shell-5GB.img.gz",
    "alpine-redpill.v1.4.5.6.xtcrp.img.gz",
    "alpine-redpill.v1.4.5.6.m-shell.vmdk.gz",
    "alpine-redpill.v1.4.5.6.xtcrp-5GB.img.gz",
]


def native_function(name):
    match = re.search(
        rf"^function {re.escape(name)}\(\) \{{\n.*?^\}}",
        SOURCE.read_text(), re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"Native function not found: {name}")
    return match.group()


def asset(name):
    return {"name": name, "browser_download_url": f"https://fixtures.invalid/{name}"}


def zip_bytes(member, payload=RAW, extras=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, payload)
        for name, content in extras:
            archive.writestr(name, content)
    return buffer.getvalue()


@contextmanager
def fixture_server(metadata, payload, *, metadata_status=200, asset_status=200,
                   partial=False):
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            is_metadata = self.path.startswith("/metadata/")
            body = metadata if is_metadata else payload
            status = metadata_status if is_metadata else asset_status
            self.send_response(status)
            self.send_header("Content-Length", str(len(body) + (
                37 if partial and not is_metadata else 0)))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class SynologyLoaderTests(unittest.TestCase):
    def run_loader(self, loader="tinycore", *, names=None, metadata=None,
                   payload=None, pretty=True, before="", invoke="download_loader",
                   functions=(), **server_options):
        if names is None:
            names = [PLAIN, *VARIANTS]
        if metadata is None:
            metadata = json.dumps({"assets": [asset(name) for name in names]},
                                  indent=2 if pretty else None).encode()
        if payload is None:
            payload = gzip.compress(RAW)
        expected = {"arc": "arc.img", "redpill": "rr.img", "tinycore": "tinycore.img"}[loader]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            images = base / "images with spaces"
            images.mkdir()
            previous = images / expected
            previous.write_bytes(b"previous verified image")
            bin_dir = base / "bin"
            bin_dir.mkdir()
            for command in ("bash", "jq", "curl", "wget", "gzip", "unzip"):
                self.assertIsNotNone(shutil.which(command), f"Install test prerequisite: {command}")
            with fixture_server(metadata, payload, **server_options) as (url, requests):
                for command in ("curl", "wget"):
                    real = shutil.which(command)
                    client_options = ["--no-config", "--tries=1"] if command == "wget" else ["-q"]
                    wrapper = bin_dir / command
                    wrapper.write_text(
                        f"#!{sys.executable}\n"
                        "import os, sys\n"
                        "args = sys.argv[1:]\n"
                        "skip = False\n"
                        "for arg in args:\n"
                        "    if skip:\n"
                        "        skip = False\n"
                        "        continue\n"
                        "    if arg in ('-O', '--connect-timeout', '--max-time'):\n"
                        "        skip = True\n"
                        "    elif not arg.startswith('-') and not arg.startswith(('https://api.github.com/repos/', 'https://fixtures.invalid/')):\n"
                        "        sys.exit('Forbidden non-fixture argument: ' + arg)\n"
                        "for i, arg in enumerate(args):\n"
                        "    if arg.startswith('https://api.github.com/repos/'):\n"
                        f"        args[i] = {url!r} + '/metadata/' + arg.split('/repos/', 1)[1]\n"
                        "    elif arg.startswith('https://fixtures.invalid/'):\n"
                        f"        args[i] = {url!r} + '/asset/' + arg.rsplit('/', 1)[1]\n"
                        "    elif '://' in arg:\n"
                        "        sys.exit('Forbidden non-fixture URL: ' + arg)\n"
                        "os.environ['no_proxy'] = os.environ['NO_PROXY'] = '127.0.0.1'\n"
                        f"os.execv({real!r}, [{real!r}, *{client_options!r}, *args])\n"
                    )
                    wrapper.chmod(0o755)
                # Administrative boundaries are fail-closed even if a test regresses.
                for command in ("apt-get", "qm", "pct", "pvesm", "pvesh"):
                    wrapper = bin_dir / command
                    wrapper.write_text("#!/bin/bash\nprintf 'FORBIDDEN %s\\n' \"$0\" >&2\nexit 97\n")
                    wrapper.chmod(0o755)
                definitions = "\n".join(native_function(name) for name in
                                        dict.fromkeys(("download_loader", *functions)))
                script = r'''
translate() { printf '%s' "$1"; }
msg_info() { printf 'INFO:%s\n' "$*"; }
msg_ok() { printf 'OK:%s\n' "$*"; }
msg_error() { printf 'ERROR:%s\n' "$*"; }
msg_warn() { printf 'WARN:%s\n' "$*"; }
stop_spinner() { :; }
sleep() { :; }
select_loader() { printf 'UNEXPECTED_RECURSION\n'; return 91; }
'''
                script += definitions + "\n" + before + "\n"
                script += invoke + r'''
result=$?
printf 'RESULT:%s\nFILE:%s\nLOADER_FILE:%s\nLOADER_TYPE:%s\nLOADER_NAME:%s\n' "$result" "$FILE" "$LOADER_FILE" "$LOADER_TYPE" "$LOADER_NAME"
exit "$result"
'''
                environment = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
                                   IMAGES_DIR=str(images), LOADER_TYPE=loader,
                                   LOADER_NAME="fixture loader", FILE="stale.img",
                                   LOADER_FILE="/stale.img")
                result = subprocess.run(["bash", "-c", script], env=environment,
                                        cwd=base, capture_output=True, text=True, timeout=15)
                state = dict(re.findall(r"^(RESULT|FILE|LOADER_FILE|LOADER_TYPE|LOADER_NAME):(.*)$", result.stdout, re.MULTILINE))
                return result, state, previous.read_bytes(), list(requests), sorted(
                    str(path.relative_to(images)) for path in images.rglob("*"))

    def test_plain_alpine_selection_ignores_competing_variants(self):
        for pretty, names in ((True, [*VARIANTS, PLAIN]),
                              (False, [VARIANTS[2], PLAIN, *VARIANTS[:2], VARIANTS[3]])):
            with self.subTest(pretty=pretty):
                result, state, contents, requests, files = self.run_loader(names=names, pretty=pretty)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(contents, RAW)
                self.assertEqual(state["FILE"], "tinycore.img")
                self.assertTrue(state["LOADER_FILE"].endswith("/tinycore.img"))
                self.assertEqual([path for path in requests if path.startswith("/asset/")],
                                 [f"/asset/{PLAIN}"])
                self.assertEqual(files, ["tinycore.img"])

    def assert_failed_acquisition(self, outcome, expected="tinycore.img"):
        result, state, contents, requests, files = outcome
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(state["FILE"], "", result.stdout)
        self.assertEqual(state["LOADER_FILE"], "", result.stdout)
        self.assertEqual(contents, b"previous verified image")
        self.assertNotIn("OK:", result.stdout)
        self.assertNotIn("UNEXPECTED_RECURSION", result.stdout)
        self.assertNotIn("FORBIDDEN", result.stderr)
        self.assertEqual(files, [expected])
        return requests

    def test_zip_loaders_parse_minified_metadata(self):
        for loader, name, member in (("arc", "arc-26.10.img.zip", "arc.img"),
                                     ("redpill", "rr-26.10.img.zip", "rr.img")):
            with self.subTest(loader=loader):
                result, state, contents, requests, files = self.run_loader(
                    loader, names=["README.txt", name], pretty=False,
                    payload=zip_bytes(member))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(contents, RAW)
                self.assertEqual(state["FILE"], member)
                self.assertTrue(state["LOADER_FILE"].endswith("/" + member))
                self.assertEqual(files, [member])
                self.assertEqual(requests[-1], "/asset/" + name)

    def test_metadata_requires_one_typed_unambiguous_asset(self):
        for loader, name, member in (("tinycore", PLAIN, "tinycore.img"),
                                     ("arc", "arc-26.10.img.zip", "arc.img"),
                                     ("redpill", "rr-26.10.img.zip", "rr.img")):
            cases = {
                "none": {"assets": []},
                "duplicate": {"assets": [asset(name), asset(name)]},
                "two_versions": {"assets": [asset(name), asset(name.replace("v1.4.5.6", "v2.0.0") if loader == "tinycore" else "another.img.zip")]},
                "null_name": {"assets": [{"name": None, "browser_download_url": asset(name)["browser_download_url"]}]},
                "numeric_name": {"assets": [{"name": 7, "browser_download_url": asset(name)["browser_download_url"]}]},
                "missing_name": {"assets": [{"browser_download_url": asset(name)["browser_download_url"]}]},
                "null_url": {"assets": [{"name": name, "browser_download_url": None}]},
                "numeric_url": {"assets": [{"name": name, "browser_download_url": 7}]},
                "empty_url": {"assets": [{"name": name, "browser_download_url": ""}]},
                "http_url": {"assets": [{"name": name, "browser_download_url": "http://bad/" + name}]},
                "mismatched_url": {"assets": [{"name": name, "browser_download_url": "https://bad/other.img.gz"}]},
                "whitespace_url": {"assets": [{"name": name, "browser_download_url": "https://bad/ has space/" + name}]},
                "control_url": {"assets": [{"name": name, "browser_download_url": "https://fixtures.invalid/\u0000/" + name}]},
                "wrong_assets_type": {"assets": {}},
                "array_root": [asset(name)],
                "error_object": {"message": "API rate limit exceeded"},
            }
            for case, document in cases.items():
                with self.subTest(loader=loader, case=case):
                    requests = self.assert_failed_acquisition(self.run_loader(
                        loader, metadata=json.dumps(document).encode()), member)
                    self.assertFalse(any(path.startswith("/asset/") for path in requests))

    def test_metadata_transport_or_json_failure_is_not_success(self):
        for label, metadata, status in (
            ("http_failure_with_valid_body", json.dumps({"assets": [asset(PLAIN)]}).encode(), 503),
            ("html_error_body", b"<html>unavailable</html>", 200),
            ("truncated_json", b'{"assets":[', 200),
            ("multiple_documents", json.dumps({"assets": [asset(PLAIN)]}).encode() * 2, 200),
        ):
            with self.subTest(case=label):
                requests = self.assert_failed_acquisition(self.run_loader(
                    metadata=metadata, metadata_status=status))
                self.assertFalse(any(path.startswith("/asset/") for path in requests))

    def test_failed_empty_or_partial_download_preserves_previous_image(self):
        for loader, name, member in (("tinycore", PLAIN, "tinycore.img"),
                                     ("arc", "arc-26.10.img.zip", "arc.img"),
                                     ("redpill", "rr-26.10.img.zip", "rr.img")):
            payload = gzip.compress(RAW) if loader == "tinycore" else zip_bytes(member)
            for label, body, options in (
                ("http_error_with_archive_body", payload, {"asset_status": 503}),
                ("empty_download", b"", {}),
                ("partial_download", payload, {"partial": True}),
            ):
                with self.subTest(loader=loader, case=label):
                    requests = self.assert_failed_acquisition(self.run_loader(
                        loader, names=[name], payload=body, **options), member)
                    self.assertEqual(requests[-1], "/asset/" + name)

    def test_invalid_or_empty_compressed_image_cannot_replace_cached_image(self):
        valid_gzip = gzip.compress(RAW)
        crc_gzip = valid_gzip[:-8] + bytes([valid_gzip[-8] ^ 1]) + valid_gzip[-7:]
        for label, payload in (
            ("not_gzip", b"<html>not an image</html>"),
            ("truncated_gzip", valid_gzip[:-6]),
            ("gzip_crc_failure", crc_gzip),
            ("empty_raw_image", gzip.compress(b"")),
        ):
            with self.subTest(case=label):
                self.assert_failed_acquisition(self.run_loader(payload=payload))

        for loader, name, member in (("arc", "arc-26.10.img.zip", "arc.img"),
                                     ("redpill", "rr-26.10.img.zip", "rr.img")):
            stored = io.BytesIO()
            with zipfile.ZipFile(stored, "w", zipfile.ZIP_STORED) as archive:
                archive.writestr(member, RAW)
            crc_zip = stored.getvalue().replace(RAW, b"?" + RAW[1:], 1)
            valid_zip = zip_bytes(member)
            for label, payload in (
                ("not_zip", b"<html>not an archive</html>"),
                ("truncated_zip", valid_zip[:-30]),
                ("zip_crc_failure", crc_zip),
                ("empty_raw_image", zip_bytes(member, b"")),
                ("missing_member", zip_bytes("other.img")),
                ("nested_member", zip_bytes("subdirectory/" + member)),
            ):
                with self.subTest(loader=loader, case=label):
                    self.assert_failed_acquisition(self.run_loader(
                        loader, names=[name], payload=payload), member)

    def test_alpine_menu_and_selection_name_preserve_internal_contract(self):
        result, state, contents, requests, files = self.run_loader(
            functions=("select_loader",), invoke="select_loader",
            before=r'''whiptail() { printf 'MENU:%s\n' "$*"; printf '3' >&2; }''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Alpine RedPill Loader (PeterSuh-Q3 M-shell)", result.stderr)
        self.assertIn("Selected Loader: Alpine RedPill M-shell", result.stdout)
        self.assertNotIn("TinyCore RedPill", result.stderr)
        self.assertEqual(contents, RAW)
        self.assertEqual(state["FILE"], "tinycore.img")
        self.assertIn("/metadata/PeterSuh-Q3/tinycore-redpill/releases/latest", requests)

    def test_zip_expected_member_must_be_unique(self):
        for loader, name, member in (("arc", "arc-26.10.img.zip", "arc.img"),
                                     ("redpill", "rr-26.10.img.zip", "rr.img")):
            duplicate = io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(duplicate, "w") as archive:
                    archive.writestr(member, RAW)
                    archive.writestr(member, b"competing image")
            with self.subTest(loader=loader):
                self.assert_failed_acquisition(self.run_loader(
                    loader, names=[name], payload=duplicate.getvalue()), member)

    def run_wizard(self, loader, mode, *, main=False, **options):
        functions = (
            "select_loader", "select_disk_type", "_build_storage_plan_summary",
            "default_settings", "advanced_settings", "start_script", "create_vm",
        )
        before = f"WIZARD_MODE={mode}\nLOADER_CHOICE={ {'arc': 1, 'redpill': 2, 'tinycore': 3}[loader] }\n"
        # Only UI/storage-entry/capture/host boundaries are replaced. The actual
        # loader -> disk plan -> settings -> start_script chain runs in Bash.
        before += r'''
NEXTID=123
NAME='Synology VM'
GEN_MAC='02:00:00:00:00:01'
header_info() { :; }
start_vm_wizard_capture() { :; }
stop_vm_wizard_capture() { :; }
prompt_optional_gpu_passthrough() { printf 'GPU_BOUNDARY\n'; }
select_virtual_disk() { VIRTUAL_DISKS+=('local:32'); }
pct() { return 1; }
qm() {
  [[ "$1" == status ]] && return 1
  printf 'QM_BOUNDARY:%s\n' "$*"
  return 97
}
whiptail() {
  case "$*" in
    *'--title SETTINGS --yesno'*) [[ "$WIZARD_MODE" == default ]]; return ;;
    *'VIRTUAL MACHINE ID'*) printf '123' >&2 ;;
    *'MACHINE TYPE'*) printf 'q35' >&2 ;;
    *'BIOS TYPE'*) printf 'ovmf' >&2 ;;
    *'HOSTNAME'*) printf 'Synology-DSM' >&2 ;;
    *'CPU MODEL'*) printf '1' >&2 ;;
    *'CORE COUNT'*) printf '2' >&2 ;;
    *'--title RAM '*) printf '4096' >&2 ;;
    *'--title BRIDGE '*) printf 'vmbr0' >&2 ;;
    *'MAC ADDRESS'*) printf '02:00:00:00:00:01' >&2 ;;
    *'STORAGE PLAN'*)
      if [[ ${#VIRTUAL_DISKS[@]} -eq 0 ]]; then printf 'a' >&2; else printf 'd' >&2; fi ;;
    *'SELECT LOADER'*) printf '%s' "$LOADER_CHOICE" >&2 ;;
  esac
  return 0
}
'''
        invoke = "start_script"
        if main:
            match = re.search(r"^# Main execution\n# =+\n(.*)", SOURCE.read_text(),
                              re.MULTILINE | re.DOTALL)
            if match is None:
                self.fail("Native main gate not found")
            invoke = match.group(1)
        return self.run_loader(loader, functions=functions, before=before,
                               invoke=invoke, **options)

    def test_native_settings_chain_propagates_loader_failure(self):
        for mode in ("default", "advanced"):
            for loader, name, member in (("tinycore", PLAIN, "tinycore.img"),
                                         ("arc", "arc-26.10.img.zip", "arc.img"),
                                         ("redpill", "rr-26.10.img.zip", "rr.img")):
                for failure in ("metadata", "archive", "download"):
                    with self.subTest(mode=mode, loader=loader, failure=failure):
                        result, state, contents, requests, files = self.run_wizard(
                            loader, mode, names=[name],
                            metadata=b'{"assets":[]}' if failure == "metadata" else None,
                            payload=b"invalid compressed image",
                            asset_status=503 if failure == "download" else 200)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(state["FILE"], "")
                        self.assertEqual(state["LOADER_FILE"], "")
                        self.assertEqual(contents, b"previous verified image")
                        self.assertNotIn("Downloaded", result.stdout)
                        self.assertNotIn("QM_BOUNDARY", result.stdout)
                        self.assertNotIn("FORBIDDEN", result.stderr)
                        self.assertEqual(files, [member])

    def test_native_main_gate_never_reaches_qm_create_after_loader_failure(self):
        for mode in ("default", "advanced"):
            for loader in ("tinycore", "arc", "redpill"):
                with self.subTest(mode=mode, loader=loader):
                    result, state, contents, requests, files = self.run_wizard(
                        loader, mode, main=True, metadata=b'{"assets":[]}')
                    # The existing cancellation convention exits zero; failure
                    # must still stop the native main before GPU or VM creation.
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("VM creation cancelled before disk planning.", result.stdout)
                    self.assertNotIn("QM_BOUNDARY", result.stdout)
                    self.assertNotIn("GPU_BOUNDARY", result.stdout)
                    self.assertNotIn("FORBIDDEN", result.stderr)
                    self.assertEqual(contents, b"previous verified image")

    def test_native_main_positive_control_reaches_only_stubbed_qm_boundary(self):
        for mode in ("default", "advanced"):
            with self.subTest(mode=mode):
                result, state, contents, requests, files = self.run_wizard("tinycore", mode, main=True)
                self.assertEqual(result.stdout.count("QM_BOUNDARY:create "), 1, result.stdout + result.stderr)
                self.assertIn("GPU_BOUNDARY", result.stdout)
                self.assertEqual(contents, RAW)

    def test_custom_loader_selection_keeps_existing_path_without_network(self):
        result, state, contents, requests, files = self.run_loader(
            functions=("select_loader", "select_custom_image"), invoke="select_loader",
            before=r'''
whiptail() {
  if [[ "$*" == *'SELECT CUSTOM IMAGE'* ]]; then
    printf '%s/tinycore.img' "$IMAGES_DIR" >&2
  else
    printf '4' >&2
  fi
}
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(state["LOADER_TYPE"], "custom")
        self.assertEqual(state["FILE"], "tinycore.img")
        self.assertTrue(state["LOADER_FILE"].endswith("/tinycore.img"))
        self.assertEqual(contents, b"previous verified image")
        self.assertEqual(requests, [])
        self.assertEqual(files, ["tinycore.img"])

    def test_zip_extracts_only_expected_image_not_sibling_files(self):
        for loader, name, member in (("arc", "arc-26.10.img.zip", "arc.img"),
                                     ("redpill", "rr-26.10.img.zip", "rr.img")):
            with self.subTest(loader=loader):
                result, state, contents, requests, files = self.run_loader(
                    loader, names=[name], payload=zip_bytes(member, extras=(
                        ("sha256sum", b"fixture checksum text"),
                        ("other.img", b"must not be published"))))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(contents, RAW)
                self.assertEqual(files, [member])

    def test_alpine_selection_is_not_pinned_to_current_release(self):
        name = "alpine-redpill.v2.0.1.m-shell.img.gz"
        result, state, contents, requests, files = self.run_loader(names=[name, *VARIANTS])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(contents, RAW)
        self.assertEqual(requests[-1], "/asset/" + name)

    def test_variants_or_legacy_family_never_substitute_for_plain_alpine(self):
        self.assert_failed_acquisition(self.run_loader(
            names=[*VARIANTS, "tinycore-redpill.v1.0.0.m-shell.img.gz"]))

    def test_staging_or_promotion_failure_keeps_previous_image(self):
        for boundary in ("mktemp", "mv"):
            with self.subTest(boundary=boundary):
                self.assert_failed_acquisition(self.run_loader(
                    before=f"{boundary}() {{ return 1; }}"))


if __name__ == "__main__":
    unittest.main()
