"""The catalog entry of the OCI menu: it names the new applications and leads
to them; a refresh the user asks for says when it could not be done."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from proxmenux_oci import cli


APPS = [{'id': 'alpha', 'title': 'Alpha', 'architectures': ['amd64']},
        {'id': 'beta', 'title': 'Beta', 'architectures': ['amd64']}]


class NewApplicationsListTests(unittest.TestCase):
    def test_opening_the_list_acknowledges_the_new_apps_and_offers_them(self):
        refresh = Mock()
        ui = Mock()
        ui.choose.side_effect = ['1', None]
        with patch.object(cli, '_app_detail') as detail:
            self.assertFalse(cli._new_applications(Mock(), ui, APPS, refresh))
        refresh.mark_seen.assert_called_once_with()
        detail.assert_called_once()
        options = ui.choose.call_args_list[0].args[1]
        self.assertEqual(options[0], ('refresh', 'Refresh catalog'))
        self.assertIn('New applications (2)', ui.choose.call_args_list[0].kwargs['title'])

    def test_its_refresh_line_asks_for_a_refresh(self):
        ui = Mock()
        ui.choose.return_value = 'refresh'
        self.assertTrue(cli._new_applications(Mock(), ui, APPS, Mock()))


class ManualRefreshTests(unittest.TestCase):
    def run_menu(self, failed):
        status = Mock(failed=failed)
        status.consume.return_value = False
        status.new_ids.return_value = []
        status.label.return_value = 'Refresh catalog'
        context = Mock()
        context.__enter__ = Mock(return_value=status)
        context.__exit__ = Mock(return_value=False)
        checker = Mock(active=False)
        checker.status.return_value = {'available': []}
        checker.notice.return_value = ''
        checker.label.return_value = 'Check for updates'
        checker_context = Mock()
        checker_context.__enter__ = Mock(return_value=checker)
        checker_context.__exit__ = Mock(return_value=False)
        ui = Mock(live_refresh=True)
        ui.choose.side_effect = ['refresh', None]
        catalog = Mock()
        catalog.index_path.exists.return_value = True
        catalog.load_index.return_value = {'applications': []}
        with patch('proxmenux_oci.catalog_refresh.menu_catalog', return_value=({'applications': []}, {})), \
                patch('proxmenux_oci.catalog_refresh.CatalogRefresh', return_value=context), \
                patch('proxmenux_oci.updates.UpdateCheck', return_value=checker_context), \
                patch.object(cli, 'interactive_ui', return_value=ui):
            self.assertEqual(cli.interactive(catalog), 0)
        status.start.assert_called_once_with(force=True)
        status.wait.assert_called_once_with()
        return [call.args[0] for call in ui.message.call_args_list]

    def test_a_failed_refresh_asked_for_is_reported(self):
        self.assertEqual(self.run_menu(True), ['Catalog refresh unavailable; using the local catalog.'])

    def test_a_successful_one_says_nothing(self):
        self.assertEqual(self.run_menu(False), [])


class AlignedCountsTests(unittest.TestCase):
    def test_counts_line_up_two_spaces_past_the_longest_counted_entry(self):
        entries = cli._aligned([('all', 'All applications (554)'),
                                ('manage', 'Gestionar aplicaciones OCI instaladas (32)'),
                                ('updates', 'Checking for updates (3/28)'), ('1', 'DNS (2)')])
        self.assertEqual(entries[0][1], f"{'All applications':<39}(554)")
        self.assertEqual(entries[1][1], 'Gestionar aplicaciones OCI instaladas  ( 32)')
        self.assertEqual(entries[2][1], 'Checking for updates (3/28)')  # progress keeps its form
        self.assertEqual(entries[3][1], f"{'DNS':<39}(  2)")

    def test_the_installed_count_is_left_out_while_the_registry_is_busy(self):
        with patch('proxmenux_oci.management.saved_inventory', side_effect=BlockingIOError):
            self.assertIsNone(cli._installed_count())
        with patch('proxmenux_oci.management.saved_inventory', return_value=[{}, {}]):
            self.assertEqual(cli._installed_count(), 2)


if __name__ == '__main__':
    unittest.main()
