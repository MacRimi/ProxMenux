"""A script writes a line break as \\n inside the text it translates; the
language files store that text with a real line break."""
import json
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]


def function(text, name):
    start = text.index(name + '() {')
    return text[start:text.index('\n}\n', start) + 3]


class TranslateLineBreaks(TestCase):
    def translate(self, text, catalog):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'xx.json').write_text(json.dumps(catalog))
            script = (f'LANGUAGE=xx LANG_DIR={folder}\n' + function((ROOT / 'scripts/utils.sh').read_text(), 'translate')
                      + 'translate "$1"\n')
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', script, 'bash', text],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stderr), (0, ''))
            return result.stdout.rstrip('\n')

    def test_a_text_stored_with_a_real_line_break_is_found(self):
        catalog = {'Restore this backup?\nThe configuration is overwritten.': '¿Restaurar?\nSe sobrescribe.'}
        self.assertEqual(self.translate('Restore this backup?\\nThe configuration is overwritten.', catalog),
                         '¿Restaurar?\nSe sobrescribe.')

    def test_the_exact_text_is_preferred_and_a_missing_one_comes_back_unchanged(self):
        catalog = {'one\\ntwo': 'LITERAL', 'one\ntwo': 'REAL', 'plain': 'simple'}
        self.assertEqual(self.translate('one\\ntwo', catalog), 'LITERAL')
        self.assertEqual(self.translate('plain', catalog), 'simple')
        self.assertEqual(self.translate('not\\nthere', catalog), 'not\\nthere')

    def test_the_shipped_texts_with_a_line_break_reach_the_spanish_file(self):
        spanish = json.loads((ROOT / 'lang/es.json').read_text())
        text = 'Are you sure you want to restore this backup?\\nCurrent configuration will be overwritten.'
        self.assertEqual(self.translate(text, spanish), spanish[text.replace('\\n', '\n')])
