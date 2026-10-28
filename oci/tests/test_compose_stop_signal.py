"""Explicit Compose stop signals override OCI image metadata without guessing."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci.custom import template_from_compose
from proxmenux_oci.stack import assess, service_template
from proxmenux_oci.converter import _stop_signal

SOURCE = '''services:
  web:
    image: nginx:alpine
    ports: ['8080:80']
    depends_on: [worker]
  worker:
    image: example/worker:latest
    entrypoint: /worker.sh
'''

class ComposeStopSignalTests(unittest.TestCase):
    def test_explicit_worker_signal_reaches_native_runtime(self):
        template = template_from_compose(SOURCE + '    stop_signal: SIGTERM\n')
        self.assertEqual(assess(template), [])
        worker = next(s for s in template['compose_stack']['services'] if s['name'] == 'worker')
        native = service_template(template, worker)
        self.assertEqual(native['proxmox']['installer_profile']['runtime']['halt_signal'], 'SIGTERM')
        self.assertEqual(native['proxmox']['installer_profile']['runtime']['compose_entrypoint'], '/worker.sh')

    def test_main_signal_is_applied_too(self):
        document = SOURCE.replace("    ports: ['8080:80']", "    ports: ['8080:80']\n    stop_signal: SIGQUIT")
        template = template_from_compose(document)
        web = next(s for s in template['compose_stack']['services'] if s['name'] == 'web')
        native = service_template(template, web)
        self.assertEqual(native['proxmox']['installer_profile']['runtime']['halt_signal'], 'SIGQUIT')
        self.assertEqual(native['proxmox']['image_metadata_policy']['stop_signal'], 'apply-compose-override')

    def test_absent_signal_does_not_guess_from_entrypoint_override(self):
        template = template_from_compose(SOURCE)
        worker = next(s for s in template['compose_stack']['services'] if s['name'] == 'worker')
        self.assertNotIn('halt_signal', service_template(template, worker)['proxmox']['installer_profile']['runtime'])

    def test_invalid_signal_is_a_review_blocker(self):
        for value in ('SIGTYPO', 'SIGTERM;touch /tmp/x', '', 99, None):
            with self.subTest(value=value):
                document = SOURCE + '    stop_signal: ' + (repr(value) if isinstance(value, str) else str(value).lower()) + '\n'
                template = template_from_compose(document)
                self.assertTrue(any('stop-signal-format' in e for e in assess(template)))

    def test_named_linux_signals_normalize_independent_of_host_os(self):
        self.assertEqual(_stop_signal('term'), 'SIGTERM')
        self.assertEqual(_stop_signal('SIGWINCH'), 'SIGWINCH')
        self.assertEqual(_stop_signal('SIGPWR'), 'SIGPWR')
        self.assertIsNone(_stop_signal('SIGWINCH\nSIGTERM'))

if __name__ == '__main__':
    unittest.main()
