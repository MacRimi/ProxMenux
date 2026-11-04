"""Exercise native architecture wiring without building or changing the host."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'AppImage/scripts'


class AppImageArchitectureTests(unittest.TestCase):
    def configure(self, machine):
        return subprocess.run(['bash', '-c',
            'source "$1"; pmx_appimage_arch "$2" || exit; '
            'printf "%s|%s|%s" "$PMX_APPIMAGE_ARCH" "$PMX_APPIMAGE_TRIPLET" "$PMX_APPIMAGE_SUFFIX"',
            'fixture', str(SCRIPTS / 'appimage_arch.sh'), machine], capture_output=True, text=True)

    def test_supported_native_architectures_and_aliases(self):
        for machine in ['x86_64', 'amd64']:
            self.assertEqual(self.configure(machine).stdout, 'x86_64|x86_64-linux-gnu|')
        for machine in ['aarch64', 'arm64']:
            self.assertEqual(self.configure(machine).stdout, 'aarch64|aarch64-linux-gnu|-aarch64')

    def test_unsupported_architecture_fails_before_build_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'uname'
            binary.write_text('#!/bin/sh\necho loongarch64\n')
            binary.chmod(0o755)
            result = subprocess.run(['bash', str(SCRIPTS / 'build_appimage.sh')],
                env={**os.environ, 'PATH': folder + ':' + os.environ['PATH']}, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported Monitor AppImage architecture: loongarch64', result.stderr)
        self.assertNotIn('Building ProxMenux', result.stdout)

    def test_gevent_wheel_installer_uses_native_platform_for_both_abis(self):
        source = (SCRIPTS / 'build_appimage.sh').read_text()
        function = source[source.index('install_gevent_runtime() {'):source.index('\ninstall_gevent_runtime "3.11"')]
        for machine in ['x86_64', 'aarch64']:
            with tempfile.TemporaryDirectory() as folder:
                command = ('source "$1"; pmx_appimage_arch "$2"; APP_DIR="$3"; '
                           'python3() { printf "%s\\n" "$*"; }; ' + function +
                           '\ninstall_gevent_runtime 3.11 cp311\ninstall_gevent_runtime 3.13 cp313')
                result = subprocess.run(['bash', '-c', command, 'fixture', str(SCRIPTS / 'appimage_arch.sh'), machine, folder],
                                        capture_output=True, text=True, check=True)
            for platform in ['manylinux_2_28_', 'manylinux_2_27_', 'manylinux2014_']:
                self.assertEqual(result.stdout.count('--platform ' + platform + machine), 2)
            for abi in ['cp311', 'cp313']:
                self.assertIn('--abi ' + abi, result.stdout)

    def test_apprun_uses_native_library_paths_and_matching_host_python_tree(self):
        for machine in ['x86_64', 'aarch64']:
            with tempfile.TemporaryDirectory() as folder:
                app = Path(folder)
                (app / 'usr/bin').mkdir(parents=True)
                (app / 'usr/lib/python3/vendor/cp311').mkdir(parents=True)
                shutil.copy(SCRIPTS / 'appimage_arch.sh', app / 'usr/bin')
                shutil.copy(SCRIPTS / 'AppRun', app / 'AppRun')
                for name, body in {
                    'uname': 'echo ' + machine,
                    'readlink': 'printf "%s\\n" "$2"',
                    'python3': 'if [ "$1" = -c ]; then echo cp311; else printf "LIB=%s\\nPY=%s\\n" "$LD_LIBRARY_PATH" "$PYTHONPATH"; fi',
                }.items():
                    file = app / 'usr/bin' / name
                    file.write_text('#!/bin/sh\n' + body + '\n')
                    file.chmod(0o755)
                result = subprocess.run(['bash', str(app / 'AppRun'), '--translate'],
                    env={**os.environ, 'PATH': str(app / 'usr/bin') + ':' + os.environ['PATH']},
                    capture_output=True, text=True, check=True)
                self.assertIn(str(app / ('usr/lib/' + machine + '-linux-gnu')), result.stdout)
                self.assertIn(str(app / 'usr/lib/python3/vendor/cp311'), result.stdout)


if __name__ == '__main__':
    unittest.main()
