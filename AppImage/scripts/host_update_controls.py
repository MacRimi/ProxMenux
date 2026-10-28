"""Guarded reboot-after-update context; existing power API is unchanged."""
import fcntl
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

from kernel_reboot import reboot_status
from host_update_jobs import list_jobs

LOCK = '/run/proxmenux-host-update.lock'
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
PROC = Path('/proc')
PACKAGE_LOCKS = ('/var/lib/dpkg/lock-frontend', '/var/lib/dpkg/lock')
UNIT = 'proxmenux-action-reboot-after-update'
# The unit obtains the SAME lock as CLI/legacy/web updates. Holding it for
# the shutdown transition closes the precheck-to-launch race. If an updater
# wins that race, flock exits75 and systemctl reboot is never invoked.
COMMAND = ['/usr/bin/flock', '-n', '-E', '75', LOCK, '/usr/bin/python3',
           '/usr/local/share/proxmenux/monitor-app/usr/bin/host_update_controls.py', '--execute-reboot']


def package_process_active():
    try:
        for path in PROC.iterdir():
            if not path.name.isdigit():
                continue
            try:
                if (path/'comm').read_text().strip() in ('apt', 'apt-get', 'dpkg', 'unattended-upgr'):
                    return True
            except (FileNotFoundError, ProcessLookupError):
                continue
    except OSError:
        return True
    return False


def execute_reboot():
    """Unit-only final guard: POSIX dpkg locks also protect direct APT callers.

    Do not use flock for these files: APT/dpkg use POSIX record locks. The
    parent retains both locks while systemctl runs and during shutdown.
    """
    handles = []
    try:
        for path in PACKAGE_LOCKS:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
            handles.append(fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return 76
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if reboot_status()['state'] != 'required':
            return 77
        subprocess.run(['/bin/systemctl', 'reboot'], check=True, timeout=10)
        time.sleep(60)
        return 0
    except (OSError, subprocess.SubprocessError):
        return 75
    finally:
        for fd in handles:
            os.close(fd)


def reboot_context():
    result = dict(hostname=socket.gethostname(), allowed=False, reason='unknown')
    try:
        boot_id = BOOT_ID.read_text().strip()
        if not boot_id:
            return result
        result['boot_id'] = boot_id
    except OSError:
        return result
    try:
        jobs = list_jobs()
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            return result
    except Exception:
        return result
    if any(job.get('state') != 'complete' for job in jobs):
        return dict(result, reason='busy')
    if package_process_active():
        return dict(result, reason='busy')
    try:
        fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        fd = None
    except OSError:
        return result
    if fd is not None:
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return result
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(result, reason='busy')
        except OSError:
            return result
        finally:
            os.close(fd)
    reboot = reboot_status()
    return dict(result, allowed=reboot['state']=='required',
                reason='required' if reboot['state']=='required' else 'current' if reboot['state']=='current' else 'unknown')


if __name__ == '__main__':
    sys.exit(execute_reboot() if sys.argv[1:] == ['--execute-reboot'] else 2)
