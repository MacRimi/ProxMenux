"""Offline VM source regressions; execute bounded real functions, never selectors.

Fixtures are reduced official metadata excerpts captured 2026-10-16. Network
commands are shell stubs: no ISO downloads, utils sourcing, or host changes.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
LINUX = ROOT / "scripts/vm/select_linux_iso.sh"
NAS = ROOT / "scripts/vm/select_nas_iso.sh"
FIELDS = ("ISO_NAME", "ISO_TYPE", "ISO_URL", "ISO_FILE", "ISO_PATH", "HN")


def extract_function(path, name):
    """Only top-level function definitions with an unindented closing brace."""
    match = re.search(
        rf"^function {re.escape(name)}\(\) \{{\n.*?^\}}(?=\n|$)",
        path.read_text(), re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Missing bounded function: {name}")
    return match.group(0)


class IsoSourceTests(unittest.TestCase):
    def run_selector(self, path, function, *, menu_name="", metadata="",
                     metadata_url="", fetch_status=0, has_curl=True):
        with tempfile.TemporaryDirectory(prefix="vm-iso-sources-") as directory:
            temp = Path(directory)
            fixture = temp / "metadata.html"
            fixture.write_text(metadata)
            trace = temp / "fetches.txt"
            trace.touch()
            iso_dir = temp / "iso"
            iso_dir.mkdir()
            env = os.environ.copy()
            env.update(ISO_DIR=str(iso_dir), MENU_NAME=menu_name,
                       METADATA_FILE=str(fixture), METADATA_URL=metadata_url,
                       FETCH_STATUS=str(fetch_status), FETCH_TRACE=str(trace))
            helpers = "\n".join(
                extract_function(NAS, name)
                for name in ("_has_curl", "_latest_version_from_lines")
            )
            script = helpers + r'''
translate() { printf '%s' "$1"; }
curl() {
    local url="${@: -1}"
    printf '%s\n' "$url" >> "$FETCH_TRACE"
    [[ "$url" == "$METADATA_URL" ]] || return 97
    [[ "$FETCH_STATUS" == 0 ]] || return "$FETCH_STATUS"
    cat "$METADATA_FILE"
}
wget() { return 97; }
dialog() {
    local arg previous="" name
    for arg in "$@"; do
        name="${arg%%│*}"
        name="${name%"${name##*[![:space:]]}"}"
        if [[ "$name" == "$MENU_NAME" ]]; then
            printf '%s' "$previous" >&2
            return 0
        fi
        previous="$arg"
    done
    return 1
}
'''
            if not has_curl:
                script += "\n_has_curl() { return 1; }\n"
            script += extract_function(path, function)
            script += f"\n{function} || exit $?\n"
            script += 'printf \'%s\\0\' ' + " ".join(
                f'"${{{field}:-}}"' for field in FIELDS
            )
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", script],
                env=env, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            values = result.stdout.decode().split("\0")
            self.assertEqual(len(values), len(FIELDS) + 1, result.stdout)
            selected = dict(zip(FIELDS, values))
            self.assertEqual(selected["ISO_PATH"], str(iso_dir / selected["ISO_FILE"]))
            return selected, trace.read_text().splitlines()

    def test_debian13_dvd_uses_fixed_official_archive(self):
        selected, calls = self.run_selector(
            LINUX, "select_linux_iso_official", menu_name="Debian 13",
        )
        self.assertEqual(selected["ISO_URL"],
                         "https://cdimage.debian.org/cdimage/archive/13.6.0/amd64/iso-dvd/"
                         "debian-13.6.0-amd64-DVD-1.iso")
        self.assertEqual(selected["ISO_TYPE"], "Desktop")
        self.assertEqual(selected["ISO_FILE"], "debian-13.6.0-amd64-DVD-1.iso")
        self.assertEqual(calls, [])

    def test_debian13_netinst_uses_fixed_official_archive(self):
        selected, calls = self.run_selector(
            LINUX, "select_linux_iso_official", menu_name="Debian 13 Netinst",
        )
        self.assertEqual(selected["ISO_URL"],
                         "https://cdimage.debian.org/cdimage/archive/13.6.0/amd64/iso-cd/"
                         "debian-13.6.0-amd64-netinst.iso")
        self.assertEqual(selected["ISO_TYPE"], "CLI")
        self.assertEqual(selected["ISO_FILE"], "debian-13.6.0-amd64-netinst.iso")
        self.assertEqual(calls, [])

    def test_omv_metadata_unavailable_uses_verified_fallback(self):
        url = "https://sourceforge.net/projects/openmediavault/files/iso/"
        for has_curl, fetch_status, metadata in (
            (False, 0, ""), (True, 22, ""),
            (True, 0, "<html>No release links</html>"),
        ):
            with self.subTest(has_curl=has_curl, fetch_status=fetch_status):
                selected, calls = self.run_selector(
                    NAS, "resolve_omv_iso", metadata_url=url, has_curl=has_curl,
                    fetch_status=fetch_status, metadata=metadata,
                )
                self.assertEqual(selected["ISO_URL"],
                                 url + "8.3.1/openmediavault_8.3.1-amd64.iso/download")
                self.assertEqual(selected["ISO_NAME"], "OpenMediaVault 8.3.1")
                self.assertEqual(selected["ISO_FILE"], "openmediavault_8.3.1-amd64.iso")
                self.assertEqual(calls, [url] if has_curl else [])

    def test_rockstor_resolves_official_landing_without_directory_listing(self):
        # Exact installer anchor excerpt from https://rockstor.com/dls/index.html.
        url = "https://rockstor.com/dls/index.html"
        metadata = (
            '<a href="https://rockstor.com/downloads/installer/leap/15.6/x86_64/'
            'Rockstor-Leap15.6-generic.x86_64-5.1.0-0.install.iso">'
            'Rockstor-Leap15.6-generic.x86_64-5.1.0-0.install.iso</a> <br/>'
        )
        selected, calls = self.run_selector(
            NAS, "resolve_rockstor_iso", metadata_url=url, metadata=metadata,
        )
        self.assertEqual(selected["ISO_URL"],
                         "https://rockstor.com/downloads/installer/leap/15.6/x86_64/"
                         "Rockstor-Leap15.6-generic.x86_64-5.1.0-0.install.iso")
        self.assertEqual(selected["ISO_FILE"],
                         "Rockstor-Leap15.6-generic.x86_64-5.1.0-0.install.iso")
        self.assertEqual(selected["HN"], "Rockstor")
        self.assertEqual(calls, [url])

    def test_rockstor_metadata_unavailable_uses_verified_fallback(self):
        url = "https://rockstor.com/dls/index.html"
        for has_curl, fetch_status, metadata in (
            (False, 0, ""), (True, 22, ""),
            (True, 0, "<html>No installer links</html>"),
        ):
            with self.subTest(has_curl=has_curl, fetch_status=fetch_status):
                selected, calls = self.run_selector(
                    NAS, "resolve_rockstor_iso", metadata_url=url, has_curl=has_curl,
                    fetch_status=fetch_status, metadata=metadata,
                )
                self.assertEqual(selected["ISO_URL"],
                                 "https://rockstor.com/downloads/installer/leap/15.6/x86_64/"
                                 "Rockstor-Leap15.6-generic.x86_64-5.1.0-0.install.iso")
                self.assertEqual(selected["ISO_NAME"], "Rockstor")
                self.assertEqual(selected["ISO_FILE"],
                                 "Rockstor-Leap15.6-generic.x86_64-5.1.0-0.install.iso")
                self.assertEqual(calls, [url] if has_curl else [])

    def test_omv_current_metadata_resolution_is_preserved(self):
        # Reduced release links from the official SourceForge ISO index.
        url = "https://sourceforge.net/projects/openmediavault/files/iso/"
        metadata = (
            '<a href="/projects/openmediavault/files/iso/8.3.1/" '
            'title="Click to enter 8.3.1">8.3.1</a>\n'
            '<a href="/projects/openmediavault/files/iso/7.4.17/" '
            'title="Click to enter 7.4.17">7.4.17</a>'
        )
        selected, calls = self.run_selector(
            NAS, "resolve_omv_iso", metadata_url=url, metadata=metadata,
        )
        self.assertEqual(selected["ISO_URL"],
                         url + "8.3.1/openmediavault_8.3.1-amd64.iso/download")
        self.assertEqual(calls, [url])

    def test_omv_detected_release_takes_precedence_over_fallback(self):
        url = "https://sourceforge.net/projects/openmediavault/files/iso/"
        # Synthetic ordering case: must execute the real version parser.
        metadata = ('<a href="/projects/openmediavault/files/iso/8.10.0/">new</a>'
                    '<a href="/projects/openmediavault/files/iso/8.9.0/">old</a>')
        selected, calls = self.run_selector(
            NAS, "resolve_omv_iso", metadata_url=url, metadata=metadata,
        )
        self.assertEqual(selected["ISO_URL"],
                         url + "8.10.0/openmediavault_8.10.0-amd64.iso/download")
        self.assertEqual(calls, [url])

    def test_rockstor_retains_generic_x86_64_leap156_edition(self):
        url = "https://rockstor.com/dls/index.html"
        # Synthetic ordering / edition cases; not claims of published images.
        metadata = "\n".join((
            "Rockstor-Leap15.6-generic.x86_64-5.10.0-0.install.iso",
            "Rockstor-Leap15.6-generic.x86_64-5.9.0-0.install.iso",
            "Rockstor-Leap15.6-generic.aarch64-9.0.0-0.install.iso",
            "Rockstor-Leap16.0-generic.x86_64-9.0.0-0.install.iso",
            "Rockstor-Leap15.5-generic.x86_64-9.0.0-0.install.iso",
        ))
        selected, calls = self.run_selector(
            NAS, "resolve_rockstor_iso", metadata_url=url, metadata=metadata,
        )
        self.assertEqual(selected["ISO_URL"],
                         "https://rockstor.com/downloads/installer/leap/15.6/x86_64/"
                         "Rockstor-Leap15.6-generic.x86_64-5.10.0-0.install.iso")
        self.assertEqual(calls, [url])


if __name__ == "__main__":
    unittest.main()
