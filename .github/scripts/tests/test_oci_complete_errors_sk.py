"""Human diagnostics translate; IDs, JSON, error types and forbidden effects do not."""
from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_oci_complete_ui_sk as fixtures
from proxmenux_oci import casaos, cli, converter, i18n
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.github_source import GitHubSource, SourceError
import oci_image_cache
import oci_dhcp_lease
import oci_rocm_check
import oci_ui
import oci_watchdog
import configure_jellyfin_encoding


class TechnicalMessages(unittest.TestCase):
    setUp = fixtures.CompleteUI.setUp
    patch = fixtures.CompleteUI.patch

    def remote_language(self):
        self.patch(oci_ui, '_language', 'sk')
        self.patch(oci_ui, '_cache', self.sk)

    def test_real_readme_errors_translate_only_at_the_display_boundary(self):
        for text, expected in [('# App', 'README neobsahuje'),
                ('## docker-compose\nplain text', 'Sekcia docker-compose neobsahuje blok kódu'),
                ('## docker-compose\n```yaml\nservices: {}', 'Blok docker-compose nie je ukončený'),
                ('## docker-compose\n```yaml\nnot-compose\n```', 'Nájdený blok nevyzerá')]:
            with self.subTest(text=text), self.assertRaises(converter.ConversionError) as caught:
                converter.extract_compose(text)
            raw = str(caught.exception)
            self.assertIn(expected, i18n.diagnostic(caught.exception))
            self.assertEqual(str(caught.exception), raw)

    def test_schema_error_keeps_field_details_and_original_exception(self):
        with self.assertRaises(converter.ConversionError) as caught:
            self.catalog.validate({})
        raw = str(caught.exception)
        self.assertTrue(raw.startswith('La plantilla generada no cumple el esquema:'))
        self.assertEqual(i18n.diagnostic(caught.exception), 'Vygenerovaná šablóna nezodpovedá schéme:' + raw.split(':', 1)[1])

    def test_missing_schema_validator_is_distinct_from_invalid_schema_without_effects(self):
        template = {}
        read = self.patch(Path, 'read_text', side_effect=AssertionError('schema must not be read without a validator'))
        with patch.dict(sys.modules, {'jsonschema': None}):
            with self.assertRaises(converter.ConversionError) as caught:
                self.catalog.validate(template)
            raw = 'python3-jsonschema is required to generate templates'
            self.assertEqual(str(caught.exception), raw)
            self.assertEqual(i18n.diagnostic(caught.exception), 'Na generovanie šablón je potrebný python3-jsonschema')
            self.assertEqual(str(caught.exception), raw)
            self.assertIsNone(self.catalog.validate(template, required=False))
        read.assert_not_called()
        self.assertEqual(template, {})
        for effect in self.effects:
            effect.assert_not_called()

    def test_real_casaos_error_preserves_the_protocol_and_localizes_the_message(self):
        with self.assertRaises(converter.ConversionError) as caught:
            casaos.parse_casaos_compose('[]')
        self.assertEqual(str(caught.exception), 'The CasaOS document is not a Compose mapping')
        self.assertEqual(i18n.diagnostic(caught.exception), 'Dokument Compose musí byť mapa kľúčov a hodnôt.')

    def test_github_rate_limit_keeps_url_and_token_variable_without_a_network_call(self):
        url = 'https://fiction.invalid/catalogue?ref=example'
        error = urllib.error.HTTPError(url, 403, 'Forbidden', {'X-RateLimit-Remaining': '0'}, None)
        request = self.patch(__import__('urllib.request', fromlist=['urlopen']), 'urlopen', side_effect=error)
        with self.assertRaises(SourceError) as caught:
            GitHubSource(token='fictional-token')._request(url)
        request.assert_called_once()
        text = i18n.diagnostic(caught.exception)
        self.assertIn('GitHub vrátil HTTP 403', text)
        self.assertIn(url, text)
        self.assertIn('GITHUB_TOKEN', text)
        self.assertNotIn('fictional-token', text)

    def test_github_timeout_retains_external_reason_and_three_attempts(self):
        request = self.patch(__import__('urllib.request', fromlist=['urlopen']), 'urlopen',
            side_effect=urllib.error.URLError('fictional external transport reason'))
        self.patch(__import__('time'), 'sleep')
        with self.assertRaises(SourceError) as caught:
            GitHubSource()._request('https://fiction.invalid/template')
        self.assertEqual(request.call_count, 3)
        self.assertIn('ani po 3 pokusoch: fictional external transport reason', i18n.diagnostic(caught.exception))

    def test_unknown_diagnostics_and_machine_codes_pass_through_unchanged(self):
        for value in ['service:db:healthcheck-format', 'external tool: failure at 0x1234',
                      'Check failed', 'Invalid cache', 'Ambiguous application', 'private-operation-id']:
            self.assertEqual(i18n.diagnostic(value), value)

    def test_cli_help_preserves_flags_actions_defaults_and_numeric_types(self):
        argv = ['manage', '104', '--action', 'recreate', '--unattended', '--min-image-age-days', '7']
        slovak = cli.build_parser()
        self.assertIn('Vypísať aplikácie', slovak.format_help())
        with patch.object(i18n, '_language', 'en'):
            english = cli.build_parser()
            self.assertIn('List applications', english.format_help())
            self.assertEqual(vars(english.parse_args(argv)), vars(slovak.parse_args(argv)))

    def test_cli_summary_preserves_image_reference_ports_mount_paths_and_status_code(self):
        template = self.catalog.compose('tandoor')
        saved = copy.deepcopy(template)
        text = cli._template_summary_text(template)
        self.assertIn('Obraz: ' + template['container_contract']['image']['reference'], text)
        self.assertIn('Dátové zväzky:', text)
        self.assertIn('Stav: ' + template['status'], text)
        for mount in template['container_contract']['volumes']:
            self.assertIn(mount['container_path'], text)
        self.assertEqual(template, saved)

    def test_install_cli_no_stays_successful_cancellation_without_dispatch(self):
        template = self.catalog.compose('jellyfin')
        saved = copy.deepcopy(template)
        self.patch(cli.Catalog, 'compose', return_value=template)
        self.patch(cli, 'build_deployment', return_value={'fiction': True})
        self.patch(cli, '_deployment_summary_text', return_value='Fiktívny plán')
        answer = self.patch(__import__('builtins'), 'input', return_value='n')
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(cli.main(['install', 'jellyfin']), 0)
        self.assertIn('Nainštalovať? [y/N]:', answer.call_args.args[0])
        self.assertEqual(output.getvalue().count('Inštalácia bola zrušená.'), 1)
        self.assertEqual(template, saved)

    def test_blocked_install_remains_error_one_and_never_asks_to_install(self):
        template = self.catalog.compose('jellyfin')
        template['compatibility'].update(automatic_install_candidate=False, untranslated_blockers=['fiction-blocker-code'])
        self.patch(cli.Catalog, 'compose', return_value=template)
        answer = self.patch(__import__('builtins'), 'input', side_effect=AssertionError('blocked installation asked a question'))
        output = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(output):
            self.assertEqual(cli.main(['install', 'jellyfin']), 1)
        self.assertIn('Inštalácia je zablokovaná: fiction-blocker-code', output.getvalue())
        answer.assert_not_called()

    def test_watchdog_manual_stop_stays_stopped_without_start_or_notice(self):
        self.remote_language()
        identity = '11111111-1111-4111-8111-111111111111'
        self.patch(oci_watchdog, 'watched', return_value={777: ('Fiction', identity)})
        self.patch(oci_watchdog.instances, 'locked', side_effect=lambda *a: nullcontext())
        self.patch(oci_watchdog, 'same_installation', return_value=True)
        self.patch(oci_watchdog, 'is_running', return_value=False)
        self.patch(oci_watchdog, 'is_busy', return_value=False)
        self.patch(oci_watchdog, 'read_tasks', return_value=[('vzshutdown', '777', 75)])
        start = self.patch(oci_watchdog, 'start', side_effect=AssertionError('manual stop was undone'))
        notice = self.patch(oci_watchdog.oci_operation_notice, 'notify')
        state = oci_watchdog.new_state(identity); state['seen'] = 50
        output = io.StringIO()
        with redirect_stdout(output): oci_watchdog.look({777: state}, 100)
        self.assertTrue(state['settled'])
        self.assertEqual(output.getvalue(), '')
        start.assert_not_called(); notice.assert_not_called()

    def test_watchdog_localization_does_not_change_retry_state_or_notification_payload(self):
        identity = '11111111-1111-4111-8111-111111111111'
        self.patch(oci_watchdog, 'watched', return_value={777: ('Fiction', identity)})
        self.patch(oci_watchdog.instances, 'locked', side_effect=lambda *a: nullcontext())
        self.patch(oci_watchdog, 'same_installation', return_value=True)
        self.patch(oci_watchdog, 'is_running', return_value=False)
        self.patch(oci_watchdog, 'is_busy', return_value=False)
        self.patch(oci_watchdog, 'read_tasks', return_value=[])
        start = self.patch(oci_watchdog, 'start', return_value=True)
        notice = self.patch(oci_watchdog.oci_operation_notice, 'notify')
        outcomes = []
        for locale in ('en', 'sk'):
            with patch.object(oci_ui, '_language', locale), patch.object(oci_ui, '_cache', self.sk):
                state = oci_watchdog.new_state(identity); state['seen'] = 50
                text = io.StringIO()
                with redirect_stdout(text): oci_watchdog.look({777: state}, 100)
                outcomes.append((copy.deepcopy(state), notice.call_args, start.call_args))
                self.assertIn('CT 777 (Fiction)', text.getvalue())
                if locale == 'sk': self.assertIn('spúšťa sa znova (pokus 1)', text.getvalue())
        self.assertEqual(outcomes[0], outcomes[1])

    def test_image_cache_json_contract_and_invalid_command_have_no_mutations(self):
        self.remote_language()
        self.patch(oci_image_cache.instances, 'locked', side_effect=lambda *a: nullcontext())
        self.patch(oci_image_cache, 'archives_of', return_value={})
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(oci_image_cache.main(['list', '777']), 0)
        self.assertEqual(json.loads(output.getvalue()), {'archives': [], 'freed': 0})
        error = io.StringIO()
        with redirect_stderr(error): self.assertEqual(oci_image_cache.main(['invalid']), 2)
        self.assertIn('Použitie: oci_image_cache.py [prune | list VMID... | remove VMID...]', error.getvalue())

    def test_rocm_timeout_localizes_but_external_gpu_errors_are_preserved(self):
        self.remote_language()
        self.patch(sys, 'argv', ['oci_rocm_check.py', '777'])
        for raw, expected in [('the GPU did not answer in time', 'GPU neodpovedalo včas'),
                              ('external provider exception 0x123', 'external provider exception 0x123')]:
            with self.subTest(raw=raw), patch.object(oci_rocm_check, 'check', side_effect=RuntimeError(raw)):
                output = io.StringIO()
                with redirect_stderr(output): self.assertEqual(oci_rocm_check.main(), 1)
                self.assertEqual(output.getvalue().strip(), expected)

    def test_jellyfin_completion_distinguishes_changed_from_already_applied(self):
        self.remote_language()
        self.patch(sys, 'argv', ['configure_jellyfin_encoding.py', '/fiction-root', '{}'])
        for changed, expected in [(True, 'Nastavenia Jellyfin boli aktualizované:'),
                                   (False, 'Nastavenia Jellyfin už boli použité:')]:
            with self.subTest(changed=changed), patch.object(configure_jellyfin_encoding, 'update_encoding',
                    return_value=(Path('/fiction-root/config/encoding.xml'), changed)):
                output = io.StringIO()
                with redirect_stdout(output): configure_jellyfin_encoding.main()
                self.assertEqual(output.getvalue().strip(), expected + ' /config/encoding.xml')

    def test_dhcp_completion_keeps_interface_and_ip_version_without_repairing_a_guest(self):
        self.remote_language()
        self.patch(oci_dhcp_lease, 'LOCKS', MagicMock())
        self.patch(oci_dhcp_lease.fcntl, 'flock')
        repair = self.patch(oci_dhcp_lease, 'repair', return_value=[('eth0', 4)])
        output = io.StringIO()
        with redirect_stdout(output): oci_dhcp_lease.check(777, 0)
        repair.assert_called_once_with(777, 0)
        self.assertEqual(output.getvalue().strip(), 'CT 777: klient DHCP rozhrania eth0 (IPv4) bol znova spustený')


class StandalonePublisher(unittest.TestCase):
    def test_mount_error_keeps_host_language_after_entering_the_container_root(self):
        spec = importlib.util.spec_from_file_location('fiction_namespace_publisher',
            fixtures.ROOT / 'oci/remote/rclone_mount_publish.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        inside = False
        def chroot(path):
            nonlocal inside
            inside = True
        def read(path, **kwargs):
            if inside:
                raise FileNotFoundError('Host language catalog is outside the container root')
            return ('{"language":"sk"}' if path.name == 'config.json' else
                    '{"clone source mount tree":"naklonovať strom zdrojového pripojenia"}')
        libc = Mock(); libc.setns.return_value = 0; libc.syscall.return_value = -1
        with ExitStack() as guards:
            for target, name, options in [
                    (sys, 'argv', {'new': ['publisher.py', '777', '/fiction-source', '/fiction-target', 'ro']}),
                    (module.platform, 'machine', {'return_value': 'x86_64'}),
                    (Path, 'read_text', {'autospec': True, 'side_effect': read}),
                    (module.ctypes, 'CDLL', {'return_value': libc}),
                    (module.ctypes, 'get_errno', {'return_value': 13}),
                    (module.os, 'open', {'return_value': 42}),
                    (module.os, 'close', {}), (module.os, 'fchdir', {}),
                    (module.os, 'chroot', {'side_effect': chroot}), (module.os, 'chdir', {})]:
                guards.enter_context(patch.object(target, name, **options))
            with self.assertRaises(OSError) as caught:
                module.main()
        self.assertTrue(inside)
        self.assertEqual(caught.exception.errno, 13)
        self.assertIn('naklonovať strom zdrojového pripojenia', str(caught.exception))
        self.assertEqual(libc.syscall.call_args.args[0], module.SYSCALLS['x86_64'][0])

    def test_copied_helper_has_localized_errors_without_engine_import_or_mount_syscalls(self):
        with tempfile.TemporaryDirectory(prefix='oci-publisher-language-') as directory:
            root = Path(directory); (root / 'lang').mkdir()
            (root / 'config.json').write_text('{"language":"sk"}')
            (root / 'lang/sk.json').write_text(json.dumps({'Usage:': 'Použitie:', 'Unsupported host architecture:': 'Nepodporovaná architektúra hostiteľa:'}))
            source = fixtures.ROOT / 'oci/remote/rclone_mount_publish.py'
            copied = root / 'publisher.py'; copied.write_bytes(source.read_bytes())
            spec = importlib.util.spec_from_file_location('fiction_standalone_publisher', copied)
            module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {'oci_ui': None}), patch.dict(__import__('os').environ, {'PMX_BASE_DIR': str(root)}):
                spec.loader.exec_module(module)
                with patch.object(module.ctypes, 'CDLL', side_effect=AssertionError('mount syscall path entered')) as syscall:
                    with patch.object(sys, 'argv', ['publisher.py']), redirect_stderr(io.StringIO()) as output:
                        self.assertEqual(module.main(), 2)
                    self.assertIn('Použitie: publisher.py PID SOURCE TARGET rw|ro', output.getvalue())
                    with patch.object(sys, 'argv', ['publisher.py', '1', '/fiction-source', '/fiction-target', 'ro']), \
                         patch.object(module.platform, 'machine', return_value='fiction-architecture'), redirect_stderr(io.StringIO()) as output:
                        self.assertEqual(module.main(), 2)
                    self.assertIn('Nepodporovaná architektúra hostiteľa: fiction-architecture', output.getvalue())
                    syscall.assert_not_called()
                (root / 'config.json').write_text('invalid json')
                module._messages.cache_clear()
                self.assertEqual(module.translate('Usage:'), 'Usage:')
                (root / 'config.json').write_text('{"language":"en"}')
                module._messages.cache_clear()
                self.assertEqual(module.translate('Usage:'), 'Usage:')


if __name__ == '__main__': unittest.main()
