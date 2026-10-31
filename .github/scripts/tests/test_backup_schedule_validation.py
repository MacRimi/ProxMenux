"""A schedule systemd rejects leaves a timer that never fires and reports no
error, so the wizard asks for it again instead of saving it."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SCHEDULER = Path(__file__).resolve().parents[3] / 'scripts/backup_restore/backup_scheduler.sh'
ANALYZE = '#!/bin/sh\ncase "$2" in "daily 02:00") exit 1;; esac\nexit 0\n'


def function(name):
    text = SCHEDULER.read_text()
    start = text.index(name + '() {')
    return text[start:text.index('\n}', start) + 2] + '\n'


class ScheduleValidation(unittest.TestCase):
    def valid(self, expression, **environment):
        with tempfile.TemporaryDirectory() as directory:
            analyze = Path(directory) / 'systemd-analyze'
            analyze.write_text(ANALYZE)
            analyze.chmod(0o755)
            return subprocess.run(
                ['/bin/bash', '-c', function('_calendar_is_valid') + '_calendar_is_valid "$1"', 'test', expression],
                env={'PATH': f'{directory}:/usr/bin:/bin', **environment},
            ).returncode == 0

    def test_systemd_decides_what_is_valid(self):
        self.assertTrue(self.valid('02:30'))
        self.assertFalse(self.valid('daily 02:00'))

    def test_a_scheduler_without_systemctl_is_not_checked(self):
        self.assertTrue(self.valid('daily 02:00', PMX_BACKUP_NO_SYSTEMCTL='1'))

    def test_the_wizard_asks_again_before_saving_the_job(self):
        text = SCHEDULER.read_text()
        check = text.index('while ! _calendar_is_valid "$on_calendar"; do')
        self.assertLess(check, text.index('"ON_CALENDAR=$on_calendar"'))
        self.assertGreater(check, text.index('on_calendar=$(dialog'))


if __name__ == '__main__':
    unittest.main()
