"""Read-only version information. No installer or configuration writes."""
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import time
import urllib.request

ROOT = Path('/usr/local/share/proxmenux')
URLS = {
    'stable': 'https://raw.githubusercontent.com/MacRimi/ProxMenux/main/version.txt',
    'beta': 'https://raw.githubusercontent.com/MacRimi/ProxMenux/develop/beta_version.txt',
}
TTL = 1800
RETRY = 60
_lock = threading.Lock()
_cache = {}


def _version(text):
    if not isinstance(text, str) or not re.fullmatch(r'\d{1,8}(?:\.\d{1,8}){1,5}', text):
        raise ValueError('Invalid version')
    parts = tuple(map(int, text.split('.')))
    return parts + (0,) * (6-len(parts))


def version_status():
    result = dict(state='unknown', installed=None, available=None, checked_at=None, channel='stable')
    try:
        beta = ROOT/'beta_version.txt'
        channel = 'beta' if beta.exists() else 'stable'
        result['channel'] = channel
        installed = (beta if channel == 'beta' else ROOT/'version.txt').read_text().strip()
        _version(installed)
        result.update(installed=installed, channel=channel)
    except (OSError, ValueError):
        return result  # No remote probe without a usable installed version.
    with _lock:
        now = time.monotonic()
        cache = _cache.get(channel, {})
        age = now-cache.get('attempt', -float('inf'))
        if not 0 <= age < (RETRY if cache.get('failed') else TTL):
            try:
                req = urllib.request.Request(URLS[channel], headers={'User-Agent': 'ProxMenux-Monitor'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    latest = response.read(129).decode('utf-8').strip()
                _version(latest)
                cache = dict(attempt=time.monotonic(), version=latest, failed=False,
                             checked_at=datetime.now(timezone.utc).isoformat())
            except (OSError, ValueError, UnicodeError):
                cache = dict(cache, attempt=time.monotonic(), failed=True)
            _cache[channel] = cache
        result.update(available=cache.get('version'), checked_at=cache.get('checked_at'))
        if cache.get('version') and not cache.get('failed'):
            result['state'] = 'available' if _version(cache['version']) > _version(installed) else 'current'
        return result
