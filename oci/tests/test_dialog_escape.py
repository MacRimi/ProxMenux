"""Escape delay is scoped to dialog and preserves terminal-specific overrides."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci.ui import DialogUI, UserCancelled


class DialogEscapeTests(unittest.TestCase):
    def test_escape_uses_short_delay_without_changing_parent_environment(self):
        with patch.dict(os.environ, {'TERM': 'xterm'}, clear=True), \
                patch('proxmenux_oci.ui.subprocess.run', return_value=subprocess.CompletedProcess([], 255, stderr='')) as run:
            self.assertIsNone(DialogUI().choose('Menu', [('1', 'First')]))
            self.assertEqual(run.call_args.kwargs['env']['ESCDELAY'], '150')
            self.assertNotIn('ESCDELAY', os.environ)

    def test_explicit_delay_is_preserved(self):
        with patch.dict(os.environ, {'ESCDELAY': '900'}), \
                patch('proxmenux_oci.ui.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stderr='1')) as run:
            self.assertEqual(DialogUI().choose('Menu', [('1', 'First')]), '1')
            self.assertEqual(run.call_args.kwargs['env']['ESCDELAY'], '900')

    def test_escape_in_search_input_keeps_cancellation_behavior(self):
        with patch('proxmenux_oci.ui.subprocess.run', return_value=subprocess.CompletedProcess([], 255, stderr='')):
            with self.assertRaises(UserCancelled):
                DialogUI().ask('Search')


if __name__ == '__main__':
    unittest.main()
