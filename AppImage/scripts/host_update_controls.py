"""Guarded reboot-after-update context; existing power API is unchanged."""
import fcntl
import os
from pathlib import Path
import socket
import stat

from kernel_reboot import reboot_status
from host_update_jobs import list_jobs

LOCK = '/run/proxmenux-host-update.lock'
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
UNIT = 'proxmenux-action-reboot-after-update'
# The unit obtains the SAME lock as CLI/legacy/web updates. Holding it for
# the shutdown transition closes the precheck-to-launch race. If an updater
# wins that race, flock exits75 and systemctl reboot is never invoked.
COMMAND = ['/usr/bin/flock', '-n', '-E', '75', LOCK, '/bin/sh', '-c',
           '/bin/systemctl reboot && /bin/sleep 60']


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
