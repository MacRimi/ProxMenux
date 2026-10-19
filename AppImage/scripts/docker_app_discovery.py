#!/usr/bin/env python3
"""Explicit Docker endpoint discovery; no registry, updater or registration.

The Docker inventory remains the owner of image updates. These candidates
describe running containers with published TCP endpoints for user review.
Only selected inspect fields leave the guest; Config.Env is never collected.
"""
import copy
from contextlib import suppress
import hashlib
import ipaddress
import json
import os
import re
import selectors
import signal
import subprocess
import threading
import time

import native_app_discovery as native

MAX_CONTAINERS = 50
OUTPUT_BYTES = 256 * 1024
TOTAL_SECONDS = 20
PROBE_SECONDS = 8
CACHE_SECONDS = 300
SNAPSHOT_SECONDS = 60
# Port hints prefill only common web endpoints; other TCP ports remain evidence.
WEB_PORTS = {80, 443, 3000, 3001, 5000, 5001, 8000, 8008, 8080, 8081, 8083, 8090, 8096, 8123, 8443, 9000, 9090, 9443}
_cache = {}
_locks = {}
_generations = {}
_mutex = threading.RLock()
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_ID = re.compile(r'[0-9a-f]{12,64}\Z')
_VERSION = re.compile(r'v?\d+(?:\.\d+){1,4}(?:[-+._][A-Za-z0-9.-]+)?\Z')
_SUPPORT = re.compile(r'(?:postgres(?:ql)?|mysql|mariadb|redis|valkey|memcached|mongo(?:db)?|rabbitmq|watchtower)(?:[_.-].*)?\Z', re.I)
# A template is evaluated for each object even when another ID disappears.
# Docker CLI inspect/inspect.go writes successful objects before returning an
# error for failed IDs. Parse stdout and retain those objects as partial data.
INSPECT_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Config.Image}},'
    '"running":{{json .State.Running}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"title":{{json (index .Config.Labels "org.opencontainers.image.title")}},'
    '"version":{{json (index .Config.Labels "org.opencontainers.image.version")}},'
    '"bindings":{{json .HostConfig.PortBindings}},"ports":{{json .NetworkSettings.Ports}}}'
)


def read(argv, deadline):
    """Bound combined stdout/stderr during collection, including failed CLI calls."""
    remaining = min(PROBE_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        raise native.ProbeError('deadline')
    end = time.monotonic() + remaining
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except OSError:
        raise native.ProbeError('unavailable') from None
    outputs = [bytearray(), bytearray()]
    try:
        with selectors.DefaultSelector() as poll:
            for index, stream in enumerate((proc.stdout, proc.stderr)):
                os.set_blocking(stream.fileno(), False)
                poll.register(stream, selectors.EVENT_READ, index)
            while poll.get_map():
                wait = end - time.monotonic()
                if wait <= 0:
                    raise native.ProbeError('timeout')
                for key, _ in poll.select(wait):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if not block:
                        poll.unregister(key.fileobj)
                        continue
                    if sum(map(len, outputs)) + len(block) > OUTPUT_BYTES:
                        raise native.ProbeError('output_limit')
                    outputs[key.data].extend(block)
            try:
                proc.wait(timeout=max(0.001, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise native.ProbeError('timeout') from None
        return proc.returncode, outputs[0].decode('utf-8', errors='strict')
    except UnicodeError:
        raise native.ProbeError('invalid_data') from None
    finally:
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def _text(value, limit=128):
    return value if isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 for c in value) else ''


def public_ports(record):
    """Published TCP mappings, excluding the full IPv4/IPv6 loopback ranges."""
    bindings, live = record.get('bindings'), record.get('ports')
    if bindings is not None and not isinstance(bindings, dict) or live is not None and not isinstance(live, dict):
        raise ValueError('invalid ports')
    ports = dict(bindings or {})
    ports.update({key: value for key, value in (live or {}).items() if value})
    result = {}
    for endpoint, values in ports.items():
        if not re.fullmatch(r'\d{1,5}/tcp', endpoint) or values is None:
            continue
        inner = int(endpoint.split('/')[0])
        if not 1 <= inner <= 65535 or not isinstance(values, list):
            raise ValueError('invalid binding')
        for value in values:
            if not isinstance(value, dict):
                raise ValueError('invalid binding')
            address = value.get('HostIp') or '0.0.0.0'
            raw = value.get('HostPort')
            # An unassigned ("") or ranged host port is not a single address.
            if not isinstance(raw, str) or not raw.isdecimal():
                continue
            try:
                ip = ipaddress.ip_address(address)
            except (ValueError, TypeError):
                continue
            if ip.is_loopback or getattr(ip, 'ipv4_mapped', None) and ip.ipv4_mapped.is_loopback:
                continue
            outer = int(raw)
            if not 1 <= outer <= 65535:
                continue
            result[outer] = {'host_port': outer, 'container_port': inner,
                             'scheme': 'https' if inner in {443, 4443, 8443, 9443} or outer in {443, 4443, 8443, 9443} else 'http'}
    return sorted(result.values(), key=lambda item: item['host_port'])


def parse_record(value):
    if not isinstance(value, dict):
        raise ValueError('invalid record')
    name = _text(value.get('name')).lstrip('/')
    image = _text(value.get('image'), 512)
    if not _ID.fullmatch(_text(value.get('id'))) or not _NAME.fullmatch(name) or not image or not isinstance(value.get('running'), bool):
        raise ValueError('invalid identity')
    project, service = _text(value.get('project')), _text(value.get('service'))
    if project and not _NAME.fullmatch(project) or service and not _NAME.fullmatch(service):
        raise ValueError('invalid compose identity')
    version = _text(value.get('version'), 64)
    return {'id': value['id'], 'name': name, 'image': image, 'running': value['running'],
            'project': project, 'service': service, 'title': _text(value.get('title')),
            'version': version if _VERSION.fullmatch(version) else None,
            'endpoints': public_ports(value)}


def _candidate(vmid, record):
    base = record['image'].split('@')[0].rsplit('/')[-1].split(':')[0]
    if not record['running'] or not record['endpoints'] or _SUPPORT.fullmatch(base) or _SUPPORT.fullmatch(record['service']):
        return None
    key = ':'.join([record['project'], record['service']]) if record['project'] and record['service'] else record['name']
    identity = 'docker-' + hashlib.sha256(f'{vmid}:{key}'.encode()).hexdigest()[:24]
    # A display name is metadata, not proof of application identity/version.
    name = record['title'] or record['service'] or record['name']
    evidence = [{'kind': 'docker_container', 'value': record['name']},
                {'kind': 'docker_image', 'value': record['image']}]
    if record['project']:
        evidence.append({'kind': 'compose_project', 'value': record['project']})
    evidence.extend({'kind': 'tcp_listener', 'value': str(port['host_port'])} for port in record['endpoints'])
    return {'slug': identity, 'discovery_id': identity, 'source': 'docker_metadata',
            'container_name': record['name'], 'name': name,
            'installed_version': record['version'], 'evidence': evidence,
            'default_ports': [port['host_port'] for port in record['endpoints'] if port['container_port'] in WEB_PORTS],
            'port_details': [{'port': port['host_port'], 'scheme': port['scheme'], 'path': None,
                              'description': '', 'logo_url': ''}
                             for port in record['endpoints'] if port['container_port'] in WEB_PORTS] or None,
            'tracking_suggestion': None}


def scan(vmid, run=read, guard_run=native.bounded_run):
    deadline = time.monotonic() + TOTAL_SECONDS
    native._guard(vmid, deadline, guard_run)
    with native._scan_reservation(vmid):
        prefix = ['pct', 'exec', str(vmid), '--']
        rc, _ = run(prefix + ['sh', '-c', 'command -v docker >/dev/null 2>&1'], deadline)
        if rc not in (0, 1):
            raise native.ProbeError('read_failed')
        records, issues = [], []
        if rc == 0:
            rc, output = run(prefix + ['docker', 'ps', '-aq', '--no-trunc'], deadline)
            if rc:
                raise native.ProbeError('docker_unavailable')
            ids = list(dict.fromkeys(output.splitlines()))
            if any(not _ID.fullmatch(value) for value in ids):
                raise native.ProbeError('invalid_data')
            if len(ids) > MAX_CONTAINERS:
                issues.append('container_limit')
            ids = ids[:MAX_CONTAINERS]
            if ids:
                rc, output = run(prefix + ['docker', 'inspect', '--format', INSPECT_FORMAT, *ids], deadline)
                if rc:
                    issues.append('inspect_failed')
                seen = set()
                for line in output.splitlines():
                    try:
                        record = parse_record(json.loads(line))
                        if record['id'] not in ids or record['id'] in seen:
                            raise ValueError('unexpected record')
                        seen.add(record['id'])
                        records.append(record)
                    except (ValueError, TypeError):
                        issues.append('invalid_data')
                if seen != set(ids):
                    issues.append('incomplete_inspect')
        native._guard(vmid, deadline, guard_run)
        candidates = {}
        for record in records:
            candidate = _candidate(vmid, record)
            if candidate:
                candidates.setdefault(candidate['slug'], candidate)
        return {'vmid': vmid, 'status': 'partial' if issues else 'complete',
                'issues': sorted(set(issues)), 'stale': False, 'scanned_at': time.time(),
                'candidates': list(candidates.values()), '_containers': records}


def cached(vmid):
    with _mutex:
        value = copy.deepcopy(_cache.get(int(vmid)))
    if value is None:
        return {'vmid': int(vmid), 'status': 'not_scanned', 'candidates': [], 'stale': False, 'issues': []}
    if time.time() - value['scanned_at'] >= CACHE_SECONDS:
        value['stale'] = True
    return {key: val for key, val in value.items() if not key.startswith('_')}


def mark_stale(vmid):
    with _mutex:
        _generations[int(vmid)] = _generations.get(int(vmid), 0) + 1
        if int(vmid) in _cache:
            _cache[int(vmid)]['stale'] = True
            _cache[int(vmid)]['_retired'] = True


def discover(vmid):
    vmid = int(vmid)
    with _mutex:
        lock = _locks.setdefault(vmid, threading.Lock())
    if not lock.acquire(blocking=False):
        return {**cached(vmid), 'status': 'busy', 'stale': True}
    try:
        with _mutex:
            generation = _generations.get(vmid, 0)
        try:
            result = scan(vmid)
        except native.ProbeError as exc:
            result = {**cached(vmid), 'status': 'error', 'issues': [str(exc)], 'stale': True}
            result.setdefault('scanned_at', time.time())
        with _mutex:
            previous = copy.deepcopy(_cache.get(vmid))
            if generation != _generations.get(vmid, 0):
                return {**cached(vmid), 'status': 'error', 'issues': ['guest_changed'], 'stale': True}
            if result['status'] != 'complete' and previous:
                known = {item['discovery_id'] for item in result['candidates']}
                result['candidates'].extend(item for item in previous['candidates'] if item['discovery_id'] not in known)
                result['candidates'] = result['candidates'][:MAX_CONTAINERS]
                containers = {item['name']: item for item in previous.get('_containers', [])}
                containers.update({item['name']: item for item in result.get('_containers', [])})
                result['_containers'] = list(containers.values())[:MAX_CONTAINERS]
                result['stale'] = True
                result['scanned_at'] = previous['scanned_at']
            result['_attempt_at'] = time.time()
            _cache[vmid] = copy.deepcopy(result)
        return cached(vmid)
    finally:
        lock.release()


def cached_web_links(vmid, lookup):
    """Reuse a Find snapshot in existing web-link suggestions without another scan."""
    with _mutex:
        value = copy.deepcopy(_cache.get(int(vmid)))
    # Only a complete search lists every container; otherwise probe as before.
    if (not value or value.get('_retired') or value.get('status') != 'complete'
            or time.time() - value['_attempt_at'] >= SNAPSHOT_SECONDS):
        return None
    result = []
    for record in value.get('_containers', []):
        meta = lookup(record['service'], record['name'], record['image'])
        for endpoint in record['endpoints']:
            result.append({**endpoint, 'container_name': record['name'],
                           'service_name': meta['name'], 'service_slug': meta['slug'],
                           'image': record['image'], 'web_path': '/', 'logo_url': meta['logo_url']})
    return sorted(result, key=lambda item: (item["service_name"].lower(), item["host_port"]))


def filter_candidates(result, suggestions, apps):
    """Suppress existing registrations/catalog entries; no probe or persistence."""
    known = [item for item in [*apps, *(suggestions.get('docker_workloads') or []), *(suggestions.get('extras') or [])] if isinstance(item, dict)]
    ids = {item.get('discovery_id') for item in known}
    containers = {item.get('container_name') or (item.get('tracking_suggestion') or {}).get('container_name') for item in known}
    ports = {p.get('port') for app in apps if isinstance(app, dict) for p in app.get('ports') or [] if isinstance(p, dict)}
    return {**result, 'candidates': [item for item in result['candidates']
            if item['discovery_id'] not in ids and item['container_name'] not in containers
            and not (item['default_ports'] and set(item['default_ports']).issubset(ports))]}
