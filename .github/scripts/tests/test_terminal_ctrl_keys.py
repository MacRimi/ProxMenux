"""Every web terminal of the Monitor can send Ctrl+D from its Ctrl menu, so
a pasted text can be finished from a phone or a tablet."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
TERMINALS = {
    'terminal-panel': 'sendSequence',
    'script-terminal-modal': 'sendCommand',
    'lxc-terminal-modal': 'sendKey',
}


class TerminalCtrlKeysTests(unittest.TestCase):
    def test_each_terminal_sends_ctrl_d(self):
        for name, send in TERMINALS.items():
            source = (ROOT / f'AppImage/components/{name}.tsx').read_text(encoding='utf-8')
            with self.subTest(terminal=name):
                self.assertIn(f'onSelect={{() => {send}("\\x04")}}', source)
                self.assertIn('t("scriptTerminal.endOfInput")', source)

    def test_the_label_exists_in_english_and_spanish(self):
        for language in ('en', 'es'):
            catalog = json.loads((ROOT / f'AppImage/messages/{language}/common.json').read_text(encoding='utf-8'))
            with self.subTest(language=language):
                self.assertTrue(catalog['scriptTerminal'].get('endOfInput'))


if __name__ == '__main__':
    unittest.main()
