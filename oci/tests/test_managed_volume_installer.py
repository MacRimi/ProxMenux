"""Exercise actual installer and persisted hook entrypoints with local fixtures."""
from pathlib import Path
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FirstInstallTests(unittest.TestCase):
    def run_case(self, mount_type='managed-volume', read_only=False, stack=False,
                 invalid=False, empty=False):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); rootfs = base / 'rootfs'
            lost = rootfs / 'config/lost+found'; lost.mkdir(parents=True, mode=0o700)
            sentinel = rootfs / 'config/keep'; sentinel.write_text('application data')
            deployment = {'stack_managed': stack, 'mounts': [] if empty else [{
                'type': mount_type, 'container_path': 'relative' if invalid else '/config',
                'backup': True, 'read_only': read_only}]}
            plan = base / 'deployment.json'; plan.write_text(json.dumps(deployment))
            wrapper = base / 'python3'
            wrapper.write_text('#!' + sys.executable + '\n' +
                'import sys\nsys.path[:0]=' + repr([str(ROOT / 'remote'), str(ROOT / 'tests')]) + '\n' +
                'from test_managed_volume_startup import ext4_metadata\n' +
                'import oci_managed_volumes\nsys.argv=sys.argv[1:]\n' +
                'with ext4_metadata():\n raise SystemExit(oci_managed_volumes.main())\n')
            wrapper.chmod(0o700)
            source = (ROOT / 'remote/install_oci.sh').read_text()
            start = source.index('prepare_managed_format_directories() {')
            end = source.index('\nprepare_managed_format_directories "/var/lib/lxc/', start)
            function = source[start:end]
            script = '''set -Eeuo pipefail
VMID=1000
MOUNT_ENTRIES=$COUNT
mount_ct_rootfs() { printf 'MOUNT\n'; }
oci_quiet() {
  if [[ $1 == pct ]]; then printf 'UNMOUNT\n'; else "$@"; fi
}
translate() { printf '%s' "$1"; }
die() { printf 'FAILURE\n'; exit 70; }
''' + function + '\nprepare_managed_format_directories "$ROOTFS"\n'
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=10,
                env=dict(os.environ, PATH=str(base) + ':' + os.environ['PATH'],
                         SCRIPT_DIR=str(ROOT / 'remote'), DEPLOYMENT_FILE=str(plan),
                         ROOTFS=str(rootfs), COUNT='0' if empty else '1'))
            self.assertEqual(sentinel.read_text(), 'application data')
            return result, lost.exists()

    def test_unannotated_config_volume_is_prepared_before_first_start(self):
        result, exists = self.run_case()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(exists)
        self.assertEqual(result.stdout.splitlines(), ['MOUNT', 'UNMOUNT'])

    def test_readonly_and_bind_sources_are_unchanged(self):
        for options in ({'read_only': True}, {'mount_type': 'host-bind'}):
            with self.subTest(options=options):
                result, exists = self.run_case(**options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(exists)

    def test_cleanup_failure_unmounts_and_stops_before_start(self):
        result, exists = self.run_case(invalid=True)
        self.assertEqual(result.returncode, 70)
        self.assertEqual(result.stdout.splitlines(), ['MOUNT', 'UNMOUNT', 'FAILURE'])
        self.assertTrue(exists)

    def test_stack_member_and_empty_mount_list_have_no_mount_or_cleanup_calls(self):
        for options in ({'stack': True}, {'empty': True}):
            with self.subTest(options=options):
                result, exists = self.run_case(**options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertTrue(exists)


class PersistedHookTests(unittest.TestCase):
    def run_case(self, *, failure=False, helper=True, invalid=False, timeout=False):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); marker = base / '1000.console.log'; events = base / 'events'
            source = (ROOT / 'remote/oci_console_mark.sh').read_text()
            source = source.replace('/var/log/proxmenux/oci/', str(base) + '/')
            script = base / 'oci_console_mark.sh'; script.write_text(source)
            (base / 'oci_dhcp_lease.py').touch()
            if helper: (base / 'oci_managed_volumes.py').touch()
            python = base / 'python3'
            python.write_text('#!/bin/sh\n' +
                'test ! -f "$MARKER" || exit 80\n' +
                'printf "cleanup %s\\n" "$3" >> "$EVENTS"\n' +
                ('sleep 30\n' if timeout else '') + ('exit 1\n' if failure else 'exit 0\n'))
            python.chmod(0o700)
            timer = base / 'systemd-run'
            timer.write_text('#!/bin/sh\ntest -s "$MARKER" || exit 81\nprintf "dhcp\\n" >> "$EVENTS"\n')
            timer.chmod(0o700)
            result = subprocess.run(['sh', str(script), 'invalid;id' if invalid else '1000'],
                capture_output=True, text=True, timeout=15,
                env=dict(os.environ, PATH=str(base) + ':' + os.environ['PATH'],
                         MARKER=str(marker), EVENTS=str(events)))
            return result, marker.exists(), events.read_text().splitlines() if events.exists() else []

    def test_cleanup_precedes_console_marker_and_dhcp_timer(self):
        result, marker, events = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker)
        self.assertEqual(events, ['cleanup 1000', 'dhcp'])

    def test_missing_or_failed_helper_keeps_marker_and_dhcp(self):
        for options, expected in (({'helper': False}, ['dhcp']),
                                  ({'failure': True}, ['cleanup 1000', 'dhcp'])):
            with self.subTest(options=options):
                result, marker, events = self.run_case(**options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(marker)
                self.assertEqual(events, expected)

    def test_hung_cleanup_is_bounded_and_dhcp_still_runs(self):
        result, marker, events = self.run_case(timeout=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker)
        self.assertEqual(events, ['cleanup 1000', 'dhcp'])

    def test_invalid_vmid_has_no_cleanup_marker_or_timer(self):
        result, marker, events = self.run_case(invalid=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(marker)
        self.assertEqual(events, [])


class InstallerTransportTests(unittest.TestCase):
    def test_local_and_ssh_staging_include_the_guarded_helper_without_host_calls(self):
        import io
        import tarfile
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / 'src'))
        from proxmenux_oci import installer
        expected = (ROOT / 'remote/oci_managed_volumes.py').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / 'template.json'; template.write_text('{}')
            for transport in ('local', 'unused-test-host'):
                for kind in (None, 'generic-multi-lxc-stack'):
                    with self.subTest(transport=transport, kind=kind):
                        def inspect(command, payload=None):
                            if transport == 'local':
                                folder = Path(command[1]).parent
                                self.assertEqual((folder / 'oci_managed_volumes.py').read_bytes(), expected)
                            else:
                                with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
                                    self.assertEqual(archive.extractfile('oci_managed_volumes.py').read(), expected)
                            return {'checked': True}
                        with patch.object(installer, '_stream_process', side_effect=inspect), \
                                patch.object(installer.subprocess, 'run') as host:
                            self.assertEqual(installer._run_remote_install(ROOT, template,
                                {'deployment_kind': kind}, transport, dry_run=True), {'checked': True})
                            host.assert_not_called()


if __name__ == '__main__':
    unittest.main()
