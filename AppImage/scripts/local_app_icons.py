"""Explicit LXC icon lookup. No guest execution, background scan or app writes.

Untrusted HTTP and image parsing run in a bounded child. Cache objects are
immutable: fetching a draft cannot overwrite a registered application's icon.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

CACHE = Path('/etc/proxmenux/apps/logo-cache')
APPS = Path('/etc/proxmenux/apps')
CONFIG = Path('/etc/pve/lxc')
MAX_BYTES = 256 * 1024
MAX_ENTRIES = 32
MAX_DIMENSION = 2048
MAX_PIXELS = 1024 * 1024
WORKER_TIMEOUT = 8
UNUSED_TTL = 24 * 3600
SLOTS = threading.BoundedSemaphore(4)
TOKEN = re.compile(r'^[a-f0-9]{32}$')
URL = re.compile(r'^/api/vms/([1-9][0-9]*)/apps/logo-cache/([a-f0-9]{32})$')
MIMES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp',
         'image/x-icon', 'image/vnd.microsoft.icon', 'image/svg+xml'}


class IconError(ValueError):
    def __init__(self, message, code='local_logo_unavailable'):
        super().__init__(message)
        self.code = code


def valid_url(vmid, value):
    match = URL.fullmatch(value) if isinstance(value, str) else None
    return bool(match and vmid is not None and int(match[1]) == int(vmid))


def _private_ip(value):
    try:
        address = ipaddress.ip_address(value)
        networks = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16') if address.version == 4 else ('fc00::/7',)
        return any(address in ipaddress.ip_network(n) for n in networks)
    except ValueError:
        return False


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as exc:
        raise IconError('container address unavailable') from exc
    if result.returncode:
        raise IconError('container address unavailable')
    return result.stdout


def _origin(vmid, payload):
    if (not isinstance(payload, dict) or set(payload) - {'port', 'scheme'}
            or type(payload.get('port')) is not int or not 1 <= payload['port'] <= 65535
            or payload.get('scheme') not in ('http', 'https')):
        raise IconError('select a valid web port and scheme')
    try:
        config = (CONFIG / f'{int(vmid)}.conf').read_text().split('\n[', 1)[0]
    except OSError as exc:
        raise IconError('container network unavailable') from exc
    if (not re.search(r'^net\d+:', config, re.M) or 'proxmenux/host-monitor' in config
            or re.search(r'^lxc\.net\.', config, re.M)):
        raise IconError('container needs an isolated network')
    if _run(['/usr/sbin/pct', 'status', str(vmid)]).strip() != 'status: running':
        raise IconError('container is not running', 'local_logo_stopped')
    ips = _run(['lxc-info', '-n', str(vmid), '-iH']).split()
    try:
        host_data = json.loads(_run(['ip', '-json', 'address', 'show']))
        host_ips = {str(ipaddress.ip_address(a['local'])) for interface in host_data
                    for a in interface.get('addr_info', []) if 'local' in a}
    except (ValueError, TypeError, KeyError) as exc:
        raise IconError('host address check unavailable') from exc
    addresses = sorted({str(ipaddress.ip_address(ip)) for ip in ips if _private_ip(ip)}, key=lambda ip: ':' in ip)
    addresses = [ip for ip in addresses if ip not in host_ips]
    if not addresses:
        raise IconError('container has no isolated private address')
    host = addresses[0]
    return f"{payload['scheme']}://{'[' + host + ']' if ':' in host else host}:{payload['port']}"


def _same_origin(left, right):
    try:
        a, b = urllib.parse.urlsplit(left), urllib.parse.urlsplit(right)
        return (a.username is None and b.username is None and a.password is None and b.password is None
                and (a.scheme, a.hostname, a.port or (443 if a.scheme == 'https' else 80))
                == (b.scheme, b.hostname, b.port or (443 if b.scheme == 'https' else 80)))
    except ValueError:
        return False


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin, page):
        self.origin, self.remaining = origin, int(page)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.remaining or not _same_origin(self.origin, newurl):
            raise IconError('redirect outside selected application')
        self.remaining -= 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, page=False):
    # Deliberately do not inherit HTTP(S)_PROXY or credentials/cookies.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        _Redirect(url, page), urllib.request.HTTPSHandler(context=context))
    return opener.open(urllib.request.Request(url, headers={
        'User-Agent': 'ProxMenux-Monitor/local-icon', 'Accept-Encoding': 'identity',
    }), timeout=3)


def _read(response):
    body = response.read(MAX_BYTES + 1)
    if not body or len(body) > MAX_BYTES:
        raise IconError('empty or oversized icon response')
    return body


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == 'link' and set((values.get('rel') or '').lower().split()) & {'icon', 'apple-touch-icon'}:
            self.links.append(values.get('href') or '')


def _svg(body):
    from defusedxml import ElementTree as safe_xml
    from xml.etree import ElementTree as xml
    try:
        original = safe_xml.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as exc:
        raise IconError('invalid SVG') from exc
    ns = 'http://www.w3.org/2000/svg'
    tags = {'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
            'polygon', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'title', 'desc'}
    attrs = {'viewBox', 'width', 'height', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy',
             'r', 'rx', 'ry', 'd', 'points', 'fill', 'stroke', 'stroke-width', 'opacity',
             'fill-opacity', 'stroke-opacity', 'fill-rule', 'clip-rule', 'stroke-linecap',
             'stroke-linejoin', 'stroke-miterlimit', 'transform', 'id', 'offset',
             'stop-color', 'stop-opacity', 'gradientUnits', 'gradientTransform', 'fx', 'fy', 'clip-path'}
    if original.tag not in ('svg', '{' + ns + '}svg'):
        raise IconError('invalid SVG root')
    count = 0
    def clean(node, depth=0):
        nonlocal count
        count += 1
        if depth > 32 or count > 2048:
            raise IconError('SVG complexity limit')
        name = node.tag.removeprefix('{' + ns + '}')
        if name not in tags:
            return None
        out = xml.Element('{' + ns + '}' + name)
        for key, value in node.attrib.items():
            if key not in attrs or len(value) > 32768:
                continue
            # Only local fragment paint/clip references; no CSS, href, events,
            # foreign namespaces, entities, animation, images, filters or use.
            if re.search(r'url\s*\(', value, re.I):
                if not re.fullmatch(r'url\(#[A-Za-z_][\w.-]*\)', value):
                    continue
            elif any(char in value for char in ('\\', ':', '<', '>', '&')):
                continue
            if key in ('width', 'height') and name == 'svg':
                if not re.fullmatch(r'\d+(?:\.\d+)?(?:px)?', value) or not 0 < float(value.removesuffix('px')) <= MAX_DIMENSION:
                    continue
            out.set(key, value)
        if name in ('title', 'desc'):
            out.text = (node.text or '')[:512]
        for child in node:
            cleaned = clean(child, depth + 1)
            if cleaned is not None:
                out.append(cleaned)
        return out
    result = clean(original)
    xml.register_namespace('', ns)
    output = xml.tostring(result, encoding='utf-8')
    if len(output) > MAX_BYTES:
        raise IconError('normalized SVG too large')
    return output, 'image/svg+xml'


def normalize(body, mime):
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES or mime not in MIMES:
        raise IconError('invalid icon type or size')
    if mime == 'image/svg+xml':
        return _svg(body)
    from PIL import Image
    expected = {'image/png': 'PNG', 'image/jpeg': 'JPEG', 'image/gif': 'GIF',
                'image/webp': 'WEBP', 'image/x-icon': 'ICO', 'image/vnd.microsoft.icon': 'ICO'}
    try:
        with Image.open(io.BytesIO(body)) as picture:
            if picture.format != expected[mime]:
                raise IconError('image format does not match content type')
            w, h = picture.size
            if not 0 < w <= MAX_DIMENSION or not 0 < h <= MAX_DIMENSION or w * h > MAX_PIXELS:
                raise IconError('image dimensions too large')
            picture.load()
            out = io.BytesIO()
            picture.convert('RGBA').save(out, format='PNG')
        result = out.getvalue()
        if len(result) > MAX_BYTES:
            raise IconError('normalized icon too large')
        return result, 'image/png'
    except IconError:
        raise
    except Exception as exc:
        raise IconError('invalid image data') from exc


def _fetch(origin):
    parsed = urllib.parse.urlsplit(origin)
    if (parsed.scheme not in ('http', 'https') or not _private_ip(parsed.hostname or '')
            or parsed.username is not None or parsed.password is not None or parsed.path
            or parsed.query or parsed.fragment or not parsed.port):
        raise IconError('invalid local origin')
    with _open(origin + '/', page=True) as response:
        final = response.geturl()
        if not _same_origin(origin, final) or response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
            raise IconError('invalid application page')
        document = _read(response)
    parser = _Links()
    parser.feed(document.decode('utf-8', errors='replace'))
    links = [urllib.parse.urljoin(final, link) for link in parser.links if link]
    candidates = [link for link in links if _same_origin(origin, link)]
    if links and not candidates:
        raise IconError('external icon not permitted')
    icon_url = candidates[0] if candidates else origin + '/favicon.ico'
    with _open(icon_url) as response:
        if response.geturl() != icon_url:
            raise IconError('icon redirect not permitted')
        return normalize(_read(response), response.headers.get_content_type())


def _worker(origin):
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--fetch', origin],
            capture_output=True, timeout=WORKER_TIMEOUT)
        if result.returncode or len(result.stdout) > MAX_BYTES * 2:
            raise IconError('local icon unavailable')
        data = json.loads(result.stdout)
        body = base64.b64decode(data['body'], validate=True)
        if not body or len(body) > MAX_BYTES or data['mime'] not in ('image/png', 'image/svg+xml'):
            raise IconError('invalid image worker response')
        return body, data['mime']
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise IconError('local icon unavailable') from exc


@contextlib.contextmanager
def _cache_lock(vmid):
    directory = CACHE / str(int(vmid))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(directory / '.lock', 'a') as handle:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise IconError('local icon cache busy')
                time.sleep(0.02)
        yield directory


def _references(sidecar):
    apps = sidecar['apps']
    if not isinstance(apps, list):
        raise ValueError('invalid apps')
    refs = {a.get('logo_url') for a in apps}
    refs.update(p.get('logo_url') for a in apps for p in a.get('ports', []))
    return refs


@contextlib.contextmanager
def protect_references(vmid, sidecar):
    """Serialize persistence against GC; an expired draft cannot save a dead URL.

    Existing missing references are preserved so unrelated checks/edits can
    still save. Only newly introduced local URLs require a readable object.
    Callers hold this lock through their atomic sidecar replacement.
    """
    refs = {url for url in _references(sidecar) if valid_url(vmid, url)}
    if not refs:
        yield
        return
    with _cache_lock(vmid):
        try:
            previous = _references(json.loads((APPS / f'{vmid}.json').read_text()))
        except FileNotFoundError:
            previous = set()
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise IconError('cannot verify saved icon references') from exc
        for url in refs - previous:
            if read(vmid, url.rsplit('/', 1)[1]) is None:
                raise IconError('cached icon expired; find the icon again')
        yield


def _prune(vmid, directory):
    # Read failure means unknown references: retain everything.
    try:
        sidecar = json.loads((APPS / f'{vmid}.json').read_text())
        refs = _references(sidecar)
    except FileNotFoundError:
        refs = set()
    except (ValueError, KeyError, TypeError, OSError, AttributeError):
        return
    for path in directory.glob('*.icon'):
        url = f'/api/vms/{vmid}/apps/logo-cache/{path.stem}'
        if url not in refs and time.time() - path.stat().st_mtime > UNUSED_TTL:
            path.unlink()


def store(vmid, body, mime):
    token = hashlib.sha256(str(vmid).encode() + b'\0' + mime.encode() + b'\0' + body).hexdigest()[:32]
    with _cache_lock(vmid) as directory:
        dest = directory / (token + '.icon')
        if dest.exists():
            # Renew the draft's lease without changing immutable image bytes.
            # Re-finding an old orphan must give the editor a full save window.
            os.utime(dest, None)
        else:
            _prune(vmid, directory)
            if len(list(directory.glob('*.icon'))) >= MAX_ENTRIES:
                raise IconError('local icon cache is full')
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as handle:
                    tmp = handle.name
                    json.dump({'mime': mime, 'body': base64.b64encode(body).decode()}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, dest)
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)
    return f'/api/vms/{vmid}/apps/logo-cache/{token}'


def discover(vmid, payload):
    if not SLOTS.acquire(blocking=False):
        raise IconError('local icon lookup busy')
    try:
        origin = _origin(vmid, payload)
        body, mime = _worker(origin)
        # Confirm that the guest still owns the chosen address before caching.
        if _origin(vmid, payload) != origin:
            raise IconError('container address changed')
        return {'logo_url': store(vmid, body, mime)}
    except OSError as exc:
        raise IconError('could not cache the icon') from exc
    finally:
        SLOTS.release()


def read(vmid, token):
    """Cache-only read, including validation of older testhost cache objects."""
    if not TOKEN.fullmatch(token):
        return None
    directory = CACHE / str(int(vmid))
    try:
        path = directory / (token + '.icon')
        if path.exists():
            with path.open('rb') as handle:
                raw = handle.read(MAX_BYTES * 2 + 1)
            if len(raw) > MAX_BYTES * 2:
                return None
            data = json.loads(raw)
            body, mime = base64.b64decode(data['body'], validate=True), data['mime']
        else:
            # Compatibility with earlier local builds; never serve legacy raw SVG.
            with (directory / (token + '.json')).open('rb') as handle:
                meta = json.loads(handle.read(4096))
            with (directory / (token + '.bin')).open('rb') as handle:
                body = handle.read(MAX_BYTES + 1)
            mime = meta['content_type']
        return normalize(body, mime)
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return None


if __name__ == '__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    try:
        if len(sys.argv) != 3 or sys.argv[1] != '--fetch':
            raise IconError('invalid worker arguments')
        body, mime = _fetch(sys.argv[2])
        print(json.dumps({'mime': mime, 'body': base64.b64encode(body).decode()}))
    except Exception:
        sys.exit(1)
