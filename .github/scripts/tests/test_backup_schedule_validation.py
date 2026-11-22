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


STUB_ANALYZE = '#!/bin/sh\ncase "$2" in daily\\ *|weekly\\ *|monthly\\ *) exit 1;; esac\nexit 0\n'
JOBS = {
    'nas': 'ON_CALENDAR=daily\\ 02:00\nENABLED=1\n',
    'week': 'ON_CALENDAR=weekly\\ 03:15\nENABLED=1\n',
    'month': 'ON_CALENDAR=monthly\\ 04:00\nENABLED=0\n',
    'good': 'ON_CALENDAR=Mon..Fri\\ 03:00\nENABLED=1\n',
    'manual': 'ON_CALENDAR=daily\\ 05:00\nMANUAL_RUN=1\n',
    'attached': 'ON_CALENDAR=daily\\ 06:00\nPVE_STORAGE=local\n',
    'custom': 'ON_CALENDAR=every\\ night\nENABLED=1\n',
}


class ScheduleRepair(unittest.TestCase):
    def run_repair(self):
        names = ('_calendar_is_valid', '_scheduler_systemctl', '_job_env_get', '_job_is_attached',
                 '_write_job_units', '_repaired_calendar', '_repair_job_schedules')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        for name, body in (('systemd-analyze', STUB_ANALYZE),
                           ('systemctl', f'#!/bin/sh\necho "$@" >> {root}/systemctl.log\n')):
            (root / name).write_text(body)
            (root / name).chmod(0o755)
        jobs, units = root / 'jobs', root / 'units'
        jobs.mkdir()
        for job, body in JOBS.items():
            (jobs / f'{job}.env').write_text(f'JOB_ID={job}\n{body}')
        script = (f'JOBS_DIR={jobs}\nSYSTEMD_DIR={units}\nLOCAL_SCRIPTS={root}\nSCRIPT_DIR={root}\n'
                  '_job_file() { echo "${JOBS_DIR}/$1.env"; }\n'
                  '_service_file() { echo "${SYSTEMD_DIR}/proxmenux-backup-$1.service"; }\n'
                  '_timer_file() { echo "${SYSTEMD_DIR}/proxmenux-backup-$1.timer"; }\n'
                  + ''.join(function(name) for name in names) + '_repair_job_schedules\n')
        subprocess.run(['/bin/bash', '-c', script], check=True,
                       env={'PATH': f'{root}:/usr/bin:/bin'})
        return jobs, units, root

    def test_a_time_after_daily_weekly_or_monthly_is_repaired(self):
        jobs, units, root = self.run_repair()
        self.assertIn('ON_CALENDAR=02:00\n', (jobs / 'nas.env').read_text())
        self.assertIn('OnCalendar=02:00\n', (units / 'proxmenux-backup-nas.timer').read_text())
        self.assertIn('OnCalendar=Mon 03:15\n', (units / 'proxmenux-backup-week.timer').read_text())
        self.assertIn('OnCalendar=*-*-01 04:00\n', (units / 'proxmenux-backup-month.timer').read_text())
        log = (root / 'systemctl.log').read_text()
        self.assertIn('enable --now proxmenux-backup-nas.timer', log)
        self.assertNotIn('proxmenux-backup-month.timer', log)

    def test_the_rest_of_the_jobs_are_left_as_they_are(self):
        jobs, units, _ = self.run_repair()
        for job in ('good', 'manual', 'attached', 'custom'):
            self.assertEqual((jobs / f'{job}.env').read_text(), f'JOB_ID={job}\n{JOBS[job]}', job)
            self.assertFalse((units / f'proxmenux-backup-{job}.timer').exists(), job)

    def test_both_installers_repair_on_update(self):
        root = SCHEDULER.parents[2]
        for installer in ('install_proxmenux.sh', 'install_proxmenux_beta.sh'):
            self.assertIn('backup_scheduler.sh" --repair-schedules', (root / installer).read_text())


if __name__ == '__main__':
    unittest.main()
