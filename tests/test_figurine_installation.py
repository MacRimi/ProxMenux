"""Exercise the real Figurine installer with isolated files and no network/root access."""

import ast
import importlib.util
import io
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/post_install/customizable_post_install.sh"
FUNCTION = re.search(
    r"^configure_figurine\(\) \{\n.*?^\}", SCRIPT.read_text(), re.M | re.S
).group(0)
VERSION = re.search(r'FIGURINE_VERSION:-([^}]+)', FUNCTION).group(1)
FUNCTION_VERSION = re.search(r'local FUNC_VERSION="([^"]+)"', FUNCTION).group(1)


class FigurineInstallation(unittest.TestCase):
    def run_installer(self, arch="amd64", *, kernel="x86_64", dpkg_exit=0,
                      release=None, download_exit=0, package="valid", existing=True):
        with tempfile.TemporaryDirectory(prefix="figurine-test-") as directory:
            root = Path(directory)
            binary_dir = root / "bin"
            profile_dir = root / "profile.d"
            binary_dir.mkdir()
            profile_dir.mkdir()
            (root / "tmp").mkdir()
            binary = binary_dir / "figurine"
            profile = profile_dir / "figurine.sh"
            bashrc = root / "bashrc"
            if existing:
                binary.write_text("previous binary\n")
                binary.chmod(0o755)
                profile.write_text("previous profile\n")
                bashrc.write_text("# previous bashrc\n")
            archive = root / "fixture.tar.gz"
            payload = b"#!/bin/sh\nprintf 'fixture Figurine\\n'\n"
            if package == "corrupt":
                archive.write_bytes(b"invalid tarball")
            else:
                with tarfile.open(archive, "w:gz") as tar:
                    name = "deploy/figurine" if package == "valid" else "README"
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    tar.addfile(member, io.BytesIO(payload))

            # Relocate every installer filesystem boundary, including its login script.
            function = (FUNCTION.replace("/usr/local/bin", str(binary_dir))
                        .replace("/etc/profile.d", str(profile_dir))
                        .replace("/root/.bashrc", str(bashrc)))
            harness = r'''
translate() { printf '%s' "$1"; }
msg_info2() { :; }
msg_info() { :; }
msg_ok() { :; }
msg_success() { :; }
msg_error() { printf '%s\n' "$*" >&2; }
pmx_journal_context() { :; }
pmx_write_file() { cat > "$1"; }
pmx_append_file() { cat >> "$1"; }
pmx_edit_file() { :; }
chown() { :; }
dpkg() {
    [[ "$TEST_DPKG_EXIT" == 0 ]] || return "$TEST_DPKG_EXIT"
    printf '%s\n' "$TEST_ARCH"
}
uname() { printf '%s\n' "$TEST_KERNEL"; }
wget() {
    [[ "$1" == -qO ]] || return 90
    printf '%s\n' "$3" >> "$TEST_ROOT/downloads"
    [[ "$TEST_DOWNLOAD_EXIT" == 0 ]] || return "$TEST_DOWNLOAD_EXIT"
    cp "$TEST_ROOT/fixture.tar.gz" "$2"
}
register_tool() { printf '%s\n' "$*" > "$TEST_ROOT/registered"; }
'''
            harness += function + "\nconfigure_figurine\nexit \"$?\"\n"
            environment = {
                "PATH": f"{binary_dir}:/usr/bin:/bin",
                "HOME": str(root),
                "TMPDIR": str(root / "tmp"),
                "LC_ALL": "C",
                "TEST_ROOT": str(root),
                "TEST_ARCH": arch,
                "TEST_DPKG_EXIT": str(dpkg_exit),
                "TEST_KERNEL": kernel,
                "TEST_DOWNLOAD_EXIT": str(download_exit),
            }
            if release is not None:
                environment["FIGURINE_VERSION"] = release
            result = subprocess.run(
                ["/bin/bash", "--noprofile", "--norc"], input=harness,
                text=True, capture_output=True, env=environment, timeout=10,
            )
            return {
                "result": result,
                "binary": binary.read_bytes(),
                "mode": binary.stat().st_mode & 0o777,
                "profile": profile.read_text(),
                "bashrc": bashrc.read_text(),
                "downloads": (root / "downloads").read_text() if (root / "downloads").exists() else "",
                "registered": (root / "registered").read_text() if (root / "registered").exists() else "",
                "payload": payload,
                "binary_path": str(binary),
            }

    def test_installs_release_matching_debian_userspace(self):
        for arch, asset in (("amd64", "amd64"), ("arm64", "arm64"), ("armhf", "arm")):
            with self.subTest(arch=arch):
                state = self.run_installer(arch)
                self.assertEqual(state["result"].returncode, 0, state["result"].stderr)
                self.assertEqual(state["downloads"],
                                 f"https://github.com/arsham/figurine/releases/download/v{VERSION}/"
                                 f"figurine_linux_{asset}_v{VERSION}.tar.gz\n")
                self.assertEqual(state["binary"], state["payload"])
                self.assertEqual(state["mode"], 0o755)
                self.assertIn(f'{state["binary_path"]} -f "3d.flf" $(hostname)', state["profile"])
                self.assertEqual(state["registered"], f"figurine true {FUNCTION_VERSION}\n")

    def test_falls_back_to_kernel_when_dpkg_is_unavailable(self):
        for kernel, asset in (("x86_64", "amd64"), ("aarch64", "arm64"),
                              ("armv7l", "arm"), ("armv8l", "arm")):
            with self.subTest(kernel=kernel):
                state = self.run_installer("", kernel=kernel, dpkg_exit=127)
                self.assertEqual(state["result"].returncode, 0, state["result"].stderr)
                self.assertIn(f"figurine_linux_{asset}_v{VERSION}.tar.gz", state["downloads"])

    def test_userspace_takes_precedence_over_kernel(self):
        state = self.run_installer("armhf", kernel="aarch64")
        self.assertEqual(state["result"].returncode, 0, state["result"].stderr)
        self.assertIn(f"figurine_linux_arm_v{VERSION}.tar.gz", state["downloads"])

    def test_fresh_install_creates_binary_banner_and_aliases(self):
        state = self.run_installer(existing=False)
        self.assertEqual(state["result"].returncode, 0, state["result"].stderr)
        self.assertEqual(state["binary"], state["payload"])
        self.assertIn(' -f "3d.flf" $(hostname)', state["profile"])
        self.assertIn("shopt -s expand_aliases", state["bashrc"])
        self.assertIn("alias aptup='apt update && apt dist-upgrade'", state["bashrc"])
        self.assertEqual(state["registered"], f"figurine true {FUNCTION_VERSION}\n")

    def test_unsupported_architecture_fails_before_changes_or_download(self):
        for arch in ("i386", "riscv64", "armel", "armv6l", "ppc64el", ""):
            with self.subTest(arch=arch):
                state = self.run_installer(arch)
                self.assertNotEqual(state["result"].returncode, 0)
                self.assertIn("Unsupported architecture for Figurine:", state["result"].stderr)
                self.assertEqual(state["downloads"], "")
                self.assert_preserved(state)
                self.assertEqual(state["bashrc"], "# previous bashrc\n")

    def assert_preserved(self, state):
        self.assertEqual(state["binary"], b"previous binary\n")
        self.assertEqual(state["profile"], "previous profile\n")
        self.assertEqual(state["registered"], "")

    def test_download_failure_preserves_previous_installation(self):
        state = self.run_installer(download_exit=8)
        self.assertNotEqual(state["result"].returncode, 0)
        self.assertIn("Failed to download Figurine", state["result"].stderr)
        self.assert_preserved(state)

    def test_invalid_packages_preserve_previous_installation(self):
        for package, error in (("corrupt", "Failed to extract package"),
                               ("missing", "Binary not found in extracted content.")):
            with self.subTest(package=package):
                state = self.run_installer(package=package)
                self.assertNotEqual(state["result"].returncode, 0)
                self.assertIn(error, state["result"].stderr)
                self.assert_preserved(state)

    def test_release_override_is_preserved(self):
        state = self.run_installer("arm64", release="2.1.0")
        self.assertEqual(state["result"].returncode, 0, state["result"].stderr)
        self.assertIn("/v2.1.0/figurine_linux_arm64_v2.1.0.tar.gz", state["downloads"])

    def test_existing_installation_is_offered_the_update_once(self):
        spec = importlib.util.spec_from_file_location(
            "post_install_versions", ROOT / "AppImage/scripts/post_install_versions.py")
        versions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(versions)
        metadata = versions.parse_post_install_script(SCRIPT)
        installed = {"figurine": {"installed": True, "version": "1.1", "source": "custom"}}
        updates = versions._detect_updates({}, metadata, installed)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["available_version"], FUNCTION_VERSION)
        self.assertEqual(updates[0]["function"], "configure_figurine")
        installed["figurine"]["version"] = FUNCTION_VERSION
        self.assertEqual(versions._detect_updates({}, metadata, installed), [])

        tree = ast.parse((ROOT / "AppImage/scripts/flask_proxmenux_routes.py").read_text())
        fallback = next(ast.literal_eval(node.value) for node in tree.body
                        if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "TOOL_METADATA"
                                for t in node.targets))
        self.assertEqual(fallback["figurine"]["version"], FUNCTION_VERSION)


if __name__ == "__main__":
    unittest.main()
