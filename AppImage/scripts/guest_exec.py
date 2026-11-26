"""Commands inside a local LXC without starting `pct`.

`pct exec` and `pct status` start a Perl interpreter that costs about half a
second of CPU per call, even for a stopped container. `pct exec` only checks
that the container is running, sets PATH to the system directories, removes
SSL_CERT_FILE and SSL_CERT_DIR and runs `lxc-attach --keep-env`; `pct status
--verbose` reads the same state and init PID as `lxc-info`. The Monitor probes
many containers in the background, so it calls those tools directly with the
same environment.
"""

import subprocess

LXC_ATTACH = "/usr/bin/lxc-attach"
LXC_INFO = "/usr/bin/lxc-info"
# The environment pct gives lxc-attach. The container still applies its own
# variables, PATH included, on top of it.
PCT_ENVIRONMENT = ["/usr/bin/env", "-u", "SSL_CERT_FILE", "-u", "SSL_CERT_DIR",
                   "PATH=/sbin:/bin:/usr/sbin:/usr/bin"]


def command(vmid, argv):
    """The argv that runs `argv` inside container `vmid`, as `pct exec` does.
    A stopped or missing container makes it exit with a non-zero status."""
    return [*PCT_ENVIRONMENT, LXC_ATTACH, "-n", str(vmid), "--keep-env", "--", *argv]


def is_command(argv):
    """Whether `argv` was built by command()."""
    return list(argv[:len(PCT_ENVIRONMENT) + 1]) == [*PCT_ENVIRONMENT, LXC_ATTACH]


def status(vmid, timeout=5):
    """(running, init_pid) of a local container; (False, "") when unknown."""
    try:
        proc = subprocess.run([LXC_INFO, "-n", str(vmid), "-s", "-p"],
                              capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return False, ""
    if proc.returncode != 0:
        return False, ""
    running, pid = False, ""
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key == "state":
            running = value.strip().upper() == "RUNNING"
        elif key == "pid":
            pid = value.strip()
    return running, pid if running else ""
