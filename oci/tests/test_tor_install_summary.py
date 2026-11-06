"""Protocol-only services explain their addresses without inventing a web UI."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from proxmenux_oci import i18n
from proxmenux_oci.cli import _print_installation_summary


class TorSummaryTests(unittest.TestCase):
    def test_final_summary_explains_proxy_settings_in_spanish(self):
        template=json.loads((ROOT/'catalog/curated/tor.json').read_text())
        self.assertFalse(template['first_run']['endpoints'])
        self.assertIsNone(template['catalog_ui']['launch']['port'])
        notes=template['proxmox']['installer_profile']['completion_notes']
        language_file=next(path for path in (ROOT.parent/'lang/es.json',ROOT.parent.parent/'lang/es.json')
                           if path.is_file())
        translations=json.loads(language_file.read_text())
        for note in notes:
            self.assertIn(note,translations)
        with patch.object(i18n,'language',return_value='es'), patch.object(i18n,'_cache',translations), \
                patch('proxmenux_oci.cli.console') as console:
            _print_installation_summary({
                'vmid':129,'ip':'192.0.2.24','urls':[],
                'service_addresses':['192.0.2.24:9050','192.0.2.24:8118'],
                'completion_notes':notes})
        shown=[call.args[0] for call in console.msg_note.call_args_list]
        self.assertIn('Tor es un proxy, no una página web. No tiene interfaz web.',shown)
        self.assertTrue(any('SOCKS5' in line and '9050' in line for line in shown))
        self.assertTrue(any('HTTP CONNECT' in line and '8118' in line for line in shown))
        self.assertTrue(any('Solo las aplicaciones configuradas' in line for line in shown))


if __name__=='__main__':
    unittest.main()
