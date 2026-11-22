"""Read-only reboot evidence, independent of APT pending-update caches."""
import os
import copy
from pathlib import Path
import re
import subprocess

_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)-(\d+)-pve$")
_PACKAGE = re.compile(r"^(?:proxmox|pve)-kernel-(\d+\.\d+\.\d+-\d+-pve)(?:-signed)?(?::[a-z0-9]+)?$")


def reboot_status():
    """No package refresh, installation, mount or bootloader operation."""
    try:
        running = os.uname().release
    except OSError:
        return dict(state="unknown", running_kernel=None, installed_kernel=None)
    result = dict(state="unknown", running_kernel=running, installed_kernel=None)
    if not isinstance(running, str) or not re.fullmatch(r'\d+\.\d+[A-Za-z0-9_.+\-]*', running):
        return result
    try:
        if Path('/run/reboot-required').exists():
            return dict(result, state="required", reason="marker")
    except OSError:
        return result
    match = _RELEASE.fullmatch(running)
    if not match:
        if running.endswith('-pve'):
            return result
        return dict(result, state="not_applicable")
    try:
        proc = subprocess.run(
            ['dpkg-query', '-W', '-f=${db:Status-Status}\t${binary:Package}\n'],
            capture_output=True, text=True, timeout=5)
        if proc.returncode != 0 or not proc.stdout.strip():
            return result
        installed = []
        valid_states = {'installed', 'config-files', 'not-installed', 'unpacked',
                        'half-configured', 'half-installed', 'triggers-awaited', 'triggers-pending'}
        for line in proc.stdout.splitlines():
            fields = line.split('\t')
            if len(fields) != 2 or fields[0] not in valid_states:
                return result
            state, package = fields
            kernel = _PACKAGE.fullmatch(package)
            if kernel:
                if state in ('unpacked', 'half-configured', 'half-installed', 'triggers-awaited', 'triggers-pending'):
                    return result
                if state == 'installed':
                    installed.append(kernel.group(1))
        if not installed:
            return result
        newest = max(installed, key=lambda v: tuple(map(int, _RELEASE.fullmatch(v).groups())))
        newer = tuple(map(int, _RELEASE.fullmatch(newest).groups())) > tuple(map(int, match.groups()))
        return dict(result, state="required" if newer else "current", installed_kernel=newest,
                    reason="kernel" if newer else None)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return result


def with_reboot_status(updates, reboot):
    """Copy, never rewrite a cached package result or hide its existing error."""
    if reboot['state'] == 'not_applicable':
        return updates
    result = dict(updates or dict(status='UNKNOWN', count=None, checks={}))
    result['checks'] = dict(result.get('checks') or {})
    # Keep the package result separate so a later reboot-only overlay can
    # clear its own INFO/UNKNOWN without hiding a package-check failure.
    base_status = result.get('package_status', result.get('status', 'UNKNOWN'))
    if result.get('all_dismissed'):
        base_status = 'OK'
    result['package_status'] = base_status
    result['status'] = base_status
    required = reboot['state'] == 'required'
    unknown = reboot['state'] == 'unknown'
    result['reboot_required'] = True if required else None if unknown else False
    result['reboot_state'] = dict(reboot)
    if required:
        detail = (f"Reboot required: running {reboot['running_kernel']}; installed {reboot['installed_kernel']}"
                  if reboot.get('installed_kernel') else 'Reboot required by the operating system')
    else:
        detail = 'Could not determine whether a reboot is required' if unknown else 'No reboot required'
    result['checks']['reboot_required'] = dict(status='INFO' if required else 'UNKNOWN' if unknown else 'OK',
                                               detail=detail, error_key='reboot_required')
    if result.get('status') == 'OK' and (required or unknown):
        result['status'] = 'INFO' if required else 'UNKNOWN'
    return result


def refresh_health_reboot(snapshot):
    """Refresh only reboot evidence on an immutable, dated health snapshot.

    Never runs the full health check, APT, persistence writes or lifecycle
    commands. Other categories and the audit timestamp retain their age.
    """
    result = copy.deepcopy(snapshot)
    details = result.get('details')
    if not isinstance(details, dict) or not isinstance(details.get('updates'), dict):
        raise ValueError('Health snapshot has no updates result')
    details['updates'] = with_reboot_status(details['updates'], reboot_status())
    if details['updates']['status'] == snapshot['details']['updates']['status']:
        return result
    issues = {status: [] for status in ('CRITICAL', 'WARNING', 'UNKNOWN', 'INFO')}
    for key, block in details.items():
        if not isinstance(block, dict):
            continue
        status = block.get('status', 'UNKNOWN')
        if status in issues:
            label = key.replace('_', ' ').capitalize()
            reason = block.get('reason')
            if key == 'updates' and not reason:
                # Reuse the existing localized reboot detail contract rather
                # than introducing an untranslated, context-free "Updates".
                issues[status].append(block['checks']['reboot_required']['detail'])
            else:
                issues[status].append(f'{label}: {reason}' if reason else label)
    result['overall'] = ('CRITICAL' if issues['CRITICAL'] else 'WARNING'
                         if issues['WARNING'] or issues['UNKNOWN'] else 'OK')
    primary = next((values for values in issues.values() if values), [])
    result['summary'] = '; '.join(primary) if primary else 'All systems operational'
    return result
