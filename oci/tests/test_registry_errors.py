"""A registry that fails for a moment is asked again, and a failure says why."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REMOTE = Path(__file__).resolve().parents[1] / 'remote'
sys.path.insert(0, str(REMOTE))
import oci_installation_state as state

RATE = (b'time="2026-10-26T08:35:58Z" level=fatal msg="Error parsing image name \\"docker://gtstef/filebrowser:latest\\": '
        b'reading manifest latest in docker.io/gtstef/filebrowser: toomanyrequests: You have reached your unauthenticated pull rate limit."')
OFFLINE = (b'level=fatal msg="Error parsing image name: pinging container registry registry-1.docker.io: '
           b'Get \\"https://registry-1.docker.io/v2/\\": dial tcp: lookup registry-1.docker.io: no such host"')
DENIED = b'level=fatal msg="reading manifest latest in ghcr.io/example/private: unauthorized: authentication required"'
MISSING = b'level=fatal msg="reading manifest nope in docker.io/library/alpine: manifest unknown"'
FORBIDDEN = (b'level=fatal msg="Error parsing image name \\"docker://ghcr.io/example/private:latest\\": '
             b'Requesting bearer token: invalid status code from registry 403 (Forbidden)"')


def failed(stderr):
    return subprocess.CompletedProcess([], 1, stdout=b'', stderr=stderr)


class RegistryErrorTests(unittest.TestCase):
    def test_an_image_lookup_is_retried_by_skopeo(self):
        with patch.object(state.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{}', b'')) as run:
            state.command('skopeo', 'inspect', '--raw', 'docker://example/app:latest')
        self.assertEqual(run.call_args.args[0], ('skopeo', 'inspect', '--retry-times', '3', '--retry-delay', '5s',
                                                 '--raw', 'docker://example/app:latest'))

    def test_other_commands_are_run_as_given(self):
        with patch.object(state.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
            state.command('pct', 'config', '101')
        self.assertEqual(run.call_args.args[0], ('pct', 'config', '101'))

    def test_a_failure_names_its_cause_without_the_output_of_skopeo(self):
        cases = {RATE: 'The registry limited the requests',
                 OFFLINE: 'The registry could not be reached',
                 DENIED: 'The registry refused access to the image',
                 FORBIDDEN: 'The registry refused access to the image',
                 MISSING: 'does not exist in the registry'}
        for stderr, expected in cases.items():
            with self.subTest(expected=expected), patch.object(state.subprocess, 'run', return_value=failed(stderr)), \
                    patch.object(state, 'translate', side_effect=lambda text: text):
                with self.assertRaises(RuntimeError) as raised:
                    state.command('skopeo', 'inspect', '--raw', 'docker://example/app:latest')
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn('docker.io', str(raised.exception))

    def test_an_unknown_failure_keeps_the_exit_code_message(self):
        with patch.object(state.subprocess, 'run', return_value=failed(b'level=fatal msg="something else"')), \
                patch.object(state, 'translate', side_effect=lambda text: text):
            with self.assertRaises(RuntimeError) as raised:
                state.command('skopeo', 'inspect', '--raw', 'docker://example/app:latest')
        self.assertEqual(str(raised.exception), 'skopeo failed with exit code 1')

    def test_a_digest_that_contains_error_codes_is_not_a_cause(self):
        stderr = b'level=fatal msg="reading blob sha256:4290404401429ab403: unexpected status"'
        self.assertIsNone(state.registry_error(stderr))

    def test_the_update_logs_the_reason_as_one_line(self):
        tree = ast.parse((REMOTE / 'oci_update_current.py').read_text())
        code = next(ast.literal_eval(node.value) for node in ast.walk(tree)
                    if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'code')
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'oci_installation_state.py').write_text(
                'def resolve_candidate(reference, architecture):\n'
                '    raise RuntimeError("The registry could not be reached. Check the connection and try again.")\n')
            result = subprocess.run([sys.executable, '-c', code, 'example/app:latest', 'amd64'],
                                    capture_output=True, text=True, cwd=folder, env={'PYTHONPATH': folder})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.strip(), 'The registry could not be reached. Check the connection and try again.')
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
