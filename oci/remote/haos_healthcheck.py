"""Verify the nested HAOS runtime without accepting its temporary landing page."""
import argparse
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request

from oci_ui import log, msg_progress, translate


REQUIRED = ('hassio_supervisor', 'homeassistant', 'hassio_cli', 'hassio_dns',
            'hassio_audio', 'hassio_multicast', 'hassio_observer')
OCI_LOG = os.environ.get('OCI_LOG')


class Pending(RuntimeError):
    """A known first-boot stage, safe to show without printing container secrets."""


def note(text):
    """Detail for the run log; without one, for stderr."""
    try:
        if OCI_LOG:
            log(OCI_LOG, text)
            return
    except OSError:
        pass
    print(text, file=sys.stderr, flush=True)


def show_progress(elapsed, timeout, reason):
    text = f"{translate('Waiting for Home Assistant OS...')} {elapsed}/{timeout} s · {reason}"
    width = max(20, shutil.get_terminal_size((80, 24)).columns - 6)
    if len(text) > width:
        text = text[:width - 1] + '…'
    msg_progress(text)


def pending_reason(items, supervisor_logs=''):
    if 'No Supervisor connectivity' in supervisor_logs:
        return translate('Supervisor reports no connectivity; retrying to get versions and install components')
    running = {i.get('Name', '').lstrip('/') for i in items
               if isinstance(i, dict) and i.get('State', {}).get('Running') is True}
    missing = [name for name in REQUIRED if name not in running]
    if missing:
        return translate('Pending components:') + ' ' + ', '.join(missing)
    return translate('Core is still on the initial installation page')


def capture(argv, timeout=15, merge_stderr=False):
    return subprocess.run(argv, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE, text=True,
                          timeout=timeout).stdout


def supervisor_ready(value):
    return (isinstance(value, dict) and value.get('result') == 'ok'
            and isinstance(value.get('data'), dict)
            and value.get('data', {}).get('healthy') is True
            and value.get('data', {}).get('supported') is True)


def containers_ready(items):
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        return False
    by_name = {item.get('Name', '').lstrip('/'): item for item in items}
    return (all(by_name.get(name, {}).get('State', {}).get('Running') is True
                for name in REQUIRED)
            and 'landingpage' not in by_name['homeassistant'].get('Config', {}).get('Image', '').lower()
            and bool(by_name['homeassistant'].get('Config', {}).get('Image')))


def http_ready(url, timeout=5):
    # Do not route private healthchecks through an environment HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def probe(vmid, ip, remaining):
    def run(args):
        return capture(args, timeout=max(0.1, min(15, remaining())))
    if run(['pct', 'status', str(vmid)]).strip() != 'status: running':
        raise RuntimeError(translate('The LXC has stopped'))
    docker = ['pct', 'exec', str(vmid), '--', 'docker', '-H', 'unix:///run/docker-real.sock']
    try:
        containers = json.loads(run(docker + ['inspect', *REQUIRED]))
    except subprocess.CalledProcessError as error:
        # docker inspect returns existing objects and exit 1 for missing names.
        containers = json.loads(error.stdout or '[]')
    if not containers_ready(containers):
        logs = ''
        try:
            logs = capture(docker + ['logs', '--tail', '25', 'hassio_supervisor'],
                           timeout=max(0.1, min(15, remaining())), merge_stderr=True)
        except subprocess.SubprocessError:
            pass
        raise Pending(pending_reason(containers, logs))
    supervisor = json.loads(run(docker + ['exec', 'hassio_cli', 'ha', '--raw-json', 'supervisor', 'info']))
    if not supervisor_ready(supervisor):
        raise Pending(translate('Supervisor does not confirm healthy and supported yet'))
    if not http_ready(f'http://{ip}:4357/', max(0.1, min(5, remaining()))):
        raise Pending(translate('Observer is not responding on port 4357'))
    for port in (80, 8123):
        if http_ready(f'http://{ip}:{port}/', max(0.1, min(5, remaining()))):
            return [{'label': 'Home Assistant', 'url': f'http://{ip}:{port}/'},
                    {'label': 'Home Assistant Observer', 'url': f'http://{ip}:4357/'}]
    raise Pending(translate('Core is running, but not responding over HTTP on 80/8123'))


def wait_ready(vmid, ip, timeout):
    started = time.monotonic()
    remaining = lambda: timeout - (time.monotonic() - started)
    last_reason = None
    while remaining() > 0:
        reason = translate('Docker/CLI not available yet or no valid answer')
        try:
            urls = probe(vmid, ip, remaining)
            if urls and remaining() > 0:
                note('HAOS: Supervisor healthy/supported, Core and internal services running.')
                return urls
        except Pending as error:
            reason = str(error)
        except (subprocess.SubprocessError, ValueError, KeyError, TypeError):
            # Missing CLI/containers are expected while upstream pulls its images.
            pass
        elapsed = int(time.monotonic() - started)
        if reason != last_reason:
            note(f'Waiting for HAOS: {elapsed}/{timeout}s; {reason}.')
            last_reason = reason
        show_progress(elapsed, timeout, reason)
        time.sleep(max(0, min(5, remaining())))
    raise RuntimeError(translate('Time is up; Home Assistant OS could not be confirmed as running'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vmid', type=int, required=True)
    parser.add_argument('--ip', required=True)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    # stdout carries only the JSON result; progress lines go to stderr.
    result_stream = sys.stdout
    sys.stdout = sys.stderr
    try:
        ipaddress.IPv4Address(args.ip)
        if args.vmid < 100 or not 60 <= args.timeout <= 3600:
            parser.error(translate('Invalid VMID or timeout'))
        urls = wait_ready(args.vmid, args.ip, args.timeout)
    except RuntimeError as error:
        note(str(error))
        return 1
    except Exception:
        note(traceback.format_exc())
        return 1
    finally:
        sys.stdout = result_stream
    print(json.dumps(urls))
    return 0


if __name__ == '__main__':
    sys.exit(main())
