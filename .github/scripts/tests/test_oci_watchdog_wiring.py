"""The watchdog of an OCI application is reachable from the Monitor and worded in every language."""
import ast
import copy
import json
from pathlib import Path
import re
from unittest import TestCase
from unittest.mock import Mock
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
LOCALES = ('en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv')


class OciWatchdogWiring(TestCase):
    def test_changing_it_needs_an_administrator_and_goes_through_the_engine(self):
        server = (ROOT / 'AppImage/scripts/flask_server.py').read_text()
        route = re.search(r"@app\.route\('/api/lxc/<int:vmid>/oci-watchdog', methods=\['POST'\]\)\n@(\w+)\ndef (\w+)", server)
        self.assertEqual(route.group(1), 'require_admin_scope')
        body = server[route.end():server.index("@app.route('/api/vms/<int:vmid>/logs'")]
        self.assertIn("if not isinstance(enabled, bool):", body)
        self.assertIn("oci/engine/remote/oci_watchdog.py',", body)
        self.assertNotIn('shell=True', body)
        self.assertIn('"watchdog": False,', (ROOT / 'AppImage/scripts/oci_instance_info.py').read_text())

    def test_the_toggle_is_only_offered_for_an_oci_application(self):
        modal = (ROOT / 'AppImage/components/virtual-machines.tsx').read_text()
        block = modal[modal.index('{/* Watchdog of an OCI application'):]
        self.assertTrue(block.split('\n', 3)[2].strip().startswith('{ociInstance?.oci_instance && ('))
        self.assertIn('t("vmLxc.details.watchdog")', block)
        self.assertIn('`/api/lxc/${selectedVM.vmid}/oci-watchdog`', modal)

    def test_every_language_names_and_explains_it(self):
        for locale in LOCALES:
            details = json.loads((ROOT / f'AppImage/messages/{locale}/common.json').read_text())['vmLxc']['details']
            self.assertTrue(details['watchdog'].strip(), locale)
            self.assertTrue(details['watchdogHelp'].strip(), locale)

    def test_the_engine_restarts_its_service_when_proxmenux_replaces_it(self):
        for installer in ('install_proxmenux.sh', 'install_proxmenux_beta.sh'):
            self.assertIn('systemctl try-restart proxmenux-oci-watchdog.service', (ROOT / installer).read_text(), installer)
        engine = (ROOT / 'oci/remote/oci_watchdog.py').read_text()
        self.assertIn("UNIT = 'proxmenux-oci-watchdog.service'", engine)


class OciWatchdogInstaller(TestCase):
    CLI = (ROOT / 'oci/src/proxmenux_oci/cli.py').read_text()
    MENU = (ROOT / 'oci/src/proxmenux_oci/management.py').read_text()

    def default(self, template):
        node = next(item for item in ast.parse(self.CLI).body
                    if isinstance(item, ast.FunctionDef) and item.name == 'watchdog_default')
        scope = {'Any': object}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'cli.py', 'exec'), scope)
        return scope['watchdog_default'](template)

    def test_the_recipe_decides_what_is_proposed(self):
        self.assertTrue(self.default({'container_contract': {'restart': 'unless-stopped'}}))
        self.assertTrue(self.default({'container_contract': {'restart': 'always'}}))
        self.assertTrue(self.default({'compose_stack': {'services': [{'compose': {}}, {'compose': {'restart': 'on-failure'}}]}}))
        self.assertFalse(self.default({'container_contract': {'restart': None}}))
        self.assertFalse(self.default({'container_contract': {'restart': 'no'}, 'compose_stack': {'services': [{'compose': {'restart': 'no'}}]}}))
        self.assertFalse(self.default({}))

    def test_every_installation_asks_it_and_the_engine_never_receives_the_answer(self):
        install = self.CLI[self.CLI.index('def install_template('):self.CLI.index('def _rclone_mount(')]
        asked = install.index('deployment["watchdog"] = wizard.confirm(')
        self.assertLess(install.index('deployment = build_deployment(candidate, wizard, mode)'), asked)
        self.assertLess(asked, install.index('approved = wizard.review('))
        self.assertLess(install.index('watchdog = bool(deployment.pop("watchdog", False))'), install.index('run_remote_install('))
        self._assert_jobs_are_excluded_from_installed_watchdog()
        self.assertIn('row(translate("Watchdog"), _yes_no(plan["watchdog"]))', self.CLI)

    def _assert_jobs_are_excluded_from_installed_watchdog(self):
        node = next(item for item in ast.parse(self.CLI).body
                    if isinstance(item, ast.FunctionDef) and item.name == 'install_template')
        class InertImports(ast.NodeTransformer):
            def visit_ImportFrom(self, item):
                return None
        node = InertImports().visit(node)
        deployment = {'services': [
            {'name': 'migration', 'deployment': {'execution_mode': 'one-shot'}},
            {'name': 'database', 'deployment': {}},
            {'name': 'worker', 'deployment': {}}]}
        result = {'vmid': 4800, 'stack_vmids': {'web': 4800, 'migration': 4801,
                                              'database': 4802, 'worker': 4803}}
        set_watchdog = Mock(return_value=True)
        class UI:
            def confirm(self, *args, **kwargs): return True
            def review(self, *args, **kwargs): return True
            def close(self): pass
        def install(project, template, plan, target):
            self.assertNotIn('watchdog', plan)
            return result
        scope = {'Any': Any, 'copy': copy, 'BacktrackUI': lambda ui: ui,
                 'RestartWizard': RuntimeError, 'InstallError': ValueError,
                 'build_deployment': lambda *args: copy.deepcopy(deployment),
                 'watchdog_default': lambda *args: False,
                 'translate': lambda value: value, '_deployment_summary_text': lambda *args: '',
                 'PROJECT_ROOT': Path('/inert'), 'source_text': lambda value: 'test', 'APP_TITLE': 'test',
                 'console': SimpleNamespace(**{name: lambda *args: None for name in
                     ('show_logo', 'msg_title', 'msg_error', 'msg_ok', 'msg_warn', 'wait_for_enter')}),
                 'run_remote_install': install, 'carry_records': lambda *args, **kwargs: None,
                 'images': SimpleNamespace(offer_removal=lambda *args: (False, None)),
                 '_print_installation_summary': lambda *args: None, 'set_watchdog': set_watchdog}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'cli.py', 'exec'), scope)
        scope['install_template'](UI(), {'catalog_ui': {'title': {'en_US': 'test'}}}, 'test', 'advanced')
        set_watchdog.assert_called_once_with(Path('/inert'), [4800, 4802, 4803], True)

    def test_both_management_menus_offer_it(self):
        self.assertEqual(self.MENU.count("('watchdog', "), 2)
        self.assertEqual(self.MENU.count("if action == 'watchdog':"), 2)

    def test_the_service_is_written_through_the_change_journal(self):
        engine = (ROOT / 'oci/remote/oci_watchdog.py').read_text()
        self.assertIn('pmx_write_file "$2" && systemctl daemon-reload && pmx_enable_service "$3"', engine)
        journal = (ROOT / 'scripts/global/pmx_journal.sh').read_text()
        for helper in ('pmx_journal_context()', 'pmx_write_file()', 'pmx_enable_service()'):
            self.assertIn(helper, journal)
