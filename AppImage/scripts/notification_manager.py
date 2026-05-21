"""
ProxMenux Notification Manager
Central orchestrator for the notification service.

Connects:
- notification_channels.py  (transport: Telegram, Gotify, Discord)
- notification_templates.py (message formatting + optional AI)
- notification_events.py    (event detection: Journal, Task, Polling watchers)
- health_persistence.py     (DB: config storage, notification_history)

Two interfaces consume this module:
1. Server mode: Flask imports and calls start()/stop()/send_notification()
2. CLI mode:    `python3 notification_manager.py --action send --type vm_fail ...`
                Scripts .sh in /usr/local/share/proxmenux/scripts call this directly.

Author: MacRimi
"""

import concurrent.futures
import ipaddress
import json
import os
import sys
import time
import socket
import sqlite3
import threading
import base64
from queue import Queue, Empty
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from urllib.parse import urlparse

# Ensure local imports work
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from notification_channels import create_channel, CHANNEL_TYPES
from notification_templates import (
    render_template, format_with_ai, format_with_ai_full, enrich_with_emojis, TEMPLATES,
    EVENT_GROUPS, get_event_types_by_group, get_default_enabled_events
)
from notification_events import (
    JournalWatcher, TaskWatcher, PollingCollector, NotificationEvent,
    ProxmoxHookWatcher,
)

# AI context enrichment (uptime, frequency, SMART data, known errors)
try:
    from ai_context_enrichment import enrich_context_for_ai
except ImportError:
    def enrich_context_for_ai(title, body, event_type, data, journal_context='', detail_level='standard'):
        return journal_context


# ─── Constants ────────────────────────────────────────────────────

DB_PATH = Path('/usr/local/share/proxmenux/health_monitor.db')
SETTINGS_PREFIX = 'notification.'
ENCRYPTION_KEY_FILE = Path('/usr/local/share/proxmenux/.notification_key')

# Keys that contain sensitive data and should be encrypted
SENSITIVE_KEYS = {
    'ai_api_key',  # Legacy - kept for migration
    'ai_api_key_groq',
    'ai_api_key_gemini',
    'ai_api_key_anthropic',
    'ai_api_key_openai',
    'ai_api_key_openrouter',
    'telegram.token',
    'gotify.token',
    'discord.webhook_url',
    'email.password',
    'webhook_secret',
}

# Sentinel string sent to the UI in place of any populated sensitive value.
# When the UI POSTs settings back, fields whose value equals the placeholder
# are treated as "unchanged" and skipped — avoiding the bug where the user
# loaded the page (got placeholders), saved an unrelated field, and we wrote
# the placeholder over the real key. See audit Tier 2 #17c.
SENSITIVE_PLACEHOLDER = '************'


def _mask_if_set(value):
    """Return the placeholder when `value` looks populated, else empty string."""
    if value is None:
        return ''
    s = str(value)
    if not s:
        return ''
    return SENSITIVE_PLACEHOLDER


# ─── SSRF guard for user-supplied URLs (audit Tier 3 #19) ───────────────
#
# Used by both the REST routes (test-ai, provider-models) and `save_settings`
# below — so that storing a malicious `ai_ollama_url` or `ai_openai_base_url`
# is rejected at the boundary, not just when the user clicks "Test". The
# AI providers themselves consume these URLs in the dispatch path; if we
# only validated at test time, an attacker could persist `file://...` and
# it would fire every notification later.
_SSRF_BLOCKED_HOSTS = frozenset({
    'metadata.google.internal',
    'metadata.azure.com',
    'metadata.aws.amazon.com',
    'instance-data',
})


def validate_external_url(url, *, allow_loopback=False, max_len=512):
    """Return (ok: bool, error_msg: str). Refuses obviously-dangerous URLs.

    `allow_loopback=True` is appropriate for local services like Ollama where
    the documented default is `http://localhost:11434`. For any URL pointing
    at a third-party API (OpenAI, Anthropic, ...) keep `allow_loopback=False`.
    """
    if not url or not isinstance(url, str):
        return False, "URL is required"
    if len(url) > max_len:
        return False, f"URL exceeds {max_len} characters"
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL is malformed"
    if parsed.scheme not in ('http', 'https'):
        return False, "Only http:// and https:// are accepted"
    host = (parsed.hostname or '').lower()
    if not host:
        return False, "URL is missing a hostname"
    if host in _SSRF_BLOCKED_HOSTS:
        return False, "Hostname is blocked (cloud metadata service)"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_link_local:
            return False, "Link-local addresses are not allowed"
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, "Reserved IP address class is not allowed"
        if not allow_loopback and ip.is_loopback:
            return False, "Loopback addresses are not allowed"
        if not allow_loopback and ip.is_private:
            return False, "Private (RFC1918) addresses are not allowed"
    elif not allow_loopback and host in ('localhost', 'localhost.localdomain', 'ip6-localhost'):
        return False, "Loopback hostnames are not allowed"
    return True, ""


# ─── Hostname Resolution ─────────────────────────────────────────

def _resolve_display_hostname(config: Optional[Dict[str, str]] = None) -> str:
    """Resolve the hostname to use in notification titles/data.

    Order of precedence:
      1. The user-configured "Display Name" in notification settings (`hostname` key).
      2. The system FQDN from `socket.gethostname()` — kept whole, NOT truncated at the
         first dot. Multi-node deployments need the full FQDN to disambiguate hosts.

    If `config` is None, the value is read from the SQLite settings table directly so
    callers without a NotificationManager instance (e.g. EmailChannel.test) can use it.
    """
    configured = ''
    if config is not None:
        configured = (config.get('hostname') or '').strip()
    else:
        try:
            if DB_PATH.exists():
                conn = sqlite3.connect(str(DB_PATH), timeout=5)
                conn.execute('PRAGMA busy_timeout=2000')
                row = conn.execute(
                    'SELECT setting_value FROM user_settings WHERE setting_key = ?',
                    (f'{SETTINGS_PREFIX}hostname',),
                ).fetchone()
                conn.close()
                if row and row[0]:
                    configured = str(row[0]).strip()
        except Exception:
            # If the DB is locked / missing / corrupt, silently fall through to FQDN.
            configured = ''
    if configured:
        return configured
    return socket.gethostname()


# ─── Encryption for Sensitive Data ───────────────────────────────
#
# Audit Tier 4 #24 flagged the previous implementation as trivially reversible:
# fixed-key XOR with a single global key, no authentication, no salting. Any
# attacker who got the DB plus `.notification_key` could decrypt every secret
# in seconds — and worse, two values encrypted under the same key let an
# attacker XOR their ciphertexts to recover (plaintext_a XOR plaintext_b),
# which often discloses both.
#
# We replace that with a stdlib-only authenticated-encryption scheme based on
# encrypt-then-MAC primitives we DO have (`hashlib.pbkdf2_hmac`, `hmac.new`):
#
#   1. Per-value 16-byte random salt.
#   2. Derive 64 bytes from the master key via PBKDF2-HMAC-SHA256 (50k iters).
#      First 32B = stream key, last 32B = MAC key.
#   3. Build a keystream by HMAC-SHA256 in counter mode over the stream key
#      and XOR it against the plaintext.
#   4. MAC := HMAC-SHA256(mac_key, salt || ciphertext).
#   5. Persist as `ENC2:<salt_b64>:<ciphertext_b64>:<mac_b64>`.
#
# Decryption verifies the MAC FIRST in constant time (hmac.compare_digest)
# and bails on mismatch, so tampered ciphertexts never produce output.
#
# Cross-value security: each value uses a fresh salt → different stream key,
# so XOR-pair recovery is closed. `cryptography` (Fernet/AES-GCM) is not
# bundled in the AppImage build today (see build_appimage.sh comment about
# PyO3 issues); when it is added, this scheme should be replaced — but the
# current implementation is light-years better than what it replaces.

# Old format prefix kept for read compatibility (lazy migration on save).
_LEGACY_ENC_PREFIX = "ENC:"
_NEW_ENC_PREFIX = "ENC2:"
_ENC_KDF_ITERS = 50000  # 50k is plenty given the master key is already random
_ENC_SALT_BYTES = 16


def _get_or_create_encryption_key() -> bytes:
    """Get or create the master encryption key for sensitive notification data."""
    if ENCRYPTION_KEY_FILE.exists():
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()

    # Create new random key. Use os.open with O_CREAT|O_EXCL|0o600 so the
    # file is created with restrictive perms atomically — the previous
    # `open(..., 'wb')` then `os.chmod` left a TOCTOU window where any
    # other UID on the host could read the master key during the few
    # milliseconds between create and chmod (umask defaults to 0o022,
    # so the file briefly held mode 0o644). Audit Tier 6.
    import secrets as _secrets
    key = _secrets.token_bytes(32)
    ENCRYPTION_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(
            str(ENCRYPTION_KEY_FILE),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        return key
    except FileExistsError:
        # Another worker raced us — read what they wrote.
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()


def _derive_subkeys(master: bytes, salt: bytes) -> tuple:
    """Derive (stream_key, mac_key) from master+salt via PBKDF2-HMAC-SHA256."""
    import hashlib as _hashlib
    derived = _hashlib.pbkdf2_hmac('sha256', master, salt, _ENC_KDF_ITERS, dklen=64)
    return derived[:32], derived[32:]


def _hmac_keystream(stream_key: bytes, length: int) -> bytes:
    """Produce `length` bytes of keystream via HMAC-SHA256 in counter mode."""
    import hmac as _hmac
    import hashlib as _hashlib
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = _hmac.new(stream_key, counter.to_bytes(8, 'big'), _hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_sensitive_value(value: str) -> str:
    """Encrypt a sensitive value with authenticated encryption.

    Returns `ENC2:<salt_b64>:<ciphertext_b64>:<mac_b64>`. Idempotent: passing
    an already-encrypted string in either ENC: or ENC2: form returns it as-is.
    """
    if not value:
        return value
    if value.startswith(_NEW_ENC_PREFIX) or value.startswith(_LEGACY_ENC_PREFIX):
        return value

    import hmac as _hmac
    import hashlib as _hashlib
    import secrets as _secrets

    master = _get_or_create_encryption_key()
    salt = _secrets.token_bytes(_ENC_SALT_BYTES)
    stream_key, mac_key = _derive_subkeys(master, salt)

    plaintext = value.encode('utf-8')
    keystream = _hmac_keystream(stream_key, len(plaintext))
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream))

    mac = _hmac.new(mac_key, salt + ciphertext, _hashlib.sha256).digest()

    return (
        f"{_NEW_ENC_PREFIX}"
        f"{base64.b64encode(salt).decode('ascii')}:"
        f"{base64.b64encode(ciphertext).decode('ascii')}:"
        f"{base64.b64encode(mac).decode('ascii')}"
    )


def _decrypt_legacy_xor(encrypted_b64: str) -> str:
    """Decrypt the old fixed-key XOR format. Used for one-time read on migration."""
    key = _get_or_create_encryption_key()
    encrypted_bytes = base64.b64decode(encrypted_b64)
    decrypted = bytes(v ^ key[i % len(key)] for i, v in enumerate(encrypted_bytes))
    return decrypted.decode('utf-8')


def decrypt_sensitive_value(encrypted: str) -> str:
    """Decrypt a sensitive value. Recognizes both ENC2 (new) and ENC (legacy)."""
    if not encrypted:
        return encrypted

    import hmac as _hmac
    import hashlib as _hashlib

    # New authenticated format.
    if encrypted.startswith(_NEW_ENC_PREFIX):
        try:
            body = encrypted[len(_NEW_ENC_PREFIX):]
            salt_b64, ct_b64, mac_b64 = body.split(':', 2)
            salt = base64.b64decode(salt_b64)
            ciphertext = base64.b64decode(ct_b64)
            received_mac = base64.b64decode(mac_b64)
        except Exception as e:
            print(f"[NotificationManager] Malformed ENC2 value: {e}")
            return ''

        master = _get_or_create_encryption_key()
        stream_key, mac_key = _derive_subkeys(master, salt)
        expected_mac = _hmac.new(mac_key, salt + ciphertext, _hashlib.sha256).digest()
        if not _hmac.compare_digest(expected_mac, received_mac):
            print("[NotificationManager] MAC verification failed — refusing to decrypt")
            return ''

        keystream = _hmac_keystream(stream_key, len(ciphertext))
        try:
            return bytes(c ^ k for c, k in zip(ciphertext, keystream)).decode('utf-8')
        except Exception as e:
            print(f"[NotificationManager] ENC2 decode error: {e}")
            return ''

    # Legacy XOR — kept for one-shot read so values stored under the old scheme
    # can still be loaded. They get re-encrypted into ENC2 on the next save_settings.
    if encrypted.startswith(_LEGACY_ENC_PREFIX):
        try:
            return _decrypt_legacy_xor(encrypted[len(_LEGACY_ENC_PREFIX):])
        except Exception as e:
            print(f"[NotificationManager] Failed to decrypt legacy ENC: {e}")
            return ''

    # No recognized prefix — caller stored the value cleartext (legacy data
    # from before encryption was introduced). Return as-is.
    return encrypted


# Cooldown defaults (seconds). Project-wide rule: an event with the same
# fingerprint never fires twice within 24h. If the underlying issue
# clears, no further pings; if it persists past the window, the next
# occurrence surfaces normally — exactly once per 24h. The narrow
# overrides further down in `_passes_cooldown` keep events that the user
# wants to see every time (backups completed, VM start/stop, shutdown)
# at their short cooldowns.
DEFAULT_COOLDOWNS = {
    'CRITICAL': 86400,
    'WARNING':  86400,
    'INFO':     86400,
    'resources': 86400,
    'updates':  86400,
}


# ─── Storm Protection ────────────────────────────────────────────

GROUP_RATE_LIMITS = {
    'security':  {'max_per_minute': 5,  'max_per_hour': 30},
    'storage':   {'max_per_minute': 3,  'max_per_hour': 20},
    'cluster':   {'max_per_minute': 5,  'max_per_hour': 20},
    'network':   {'max_per_minute': 3,  'max_per_hour': 15},
    'resources': {'max_per_minute': 3,  'max_per_hour': 20},
    'vm_ct':     {'max_per_minute': 10, 'max_per_hour': 60},
    'backup':    {'max_per_minute': 5,  'max_per_hour': 30},
    'services':  {'max_per_minute': 5,  'max_per_hour': 30},
    'health':    {'max_per_minute': 3,  'max_per_hour': 20},
    'updates':   {'max_per_minute': 3,  'max_per_hour': 15},
    'other':     {'max_per_minute': 5,  'max_per_hour': 30},
}

# Default fallback for unknown groups
_DEFAULT_RATE_LIMIT = {'max_per_minute': 5, 'max_per_hour': 30}


class GroupRateLimiter:
    """Rate limiter per event group. Prevents notification storms.

    Thread-safe: allow() can be called concurrently from the dispatch thread,
    journal watcher, polling collector, and webhook handler. Without the lock
    the deques produced IndexError under storm conditions and the counts went
    inconsistent (event A's prune saw event B's append mid-flight). Audit
    Tier 6 (Notification stack #5).
    """

    def __init__(self):
        from collections import deque
        self._deque = deque
        self._minute_counts: Dict[str, Any] = {}  # group -> deque[timestamp]
        self._hour_counts: Dict[str, Any] = {}    # group -> deque[timestamp]
        self._lock = threading.Lock()

    def allow(self, group: str) -> bool:
        """Check if group rate limit allows this event."""
        limits = GROUP_RATE_LIMITS.get(group, _DEFAULT_RATE_LIMIT)
        now = time.time()

        with self._lock:
            # Initialize if needed
            if group not in self._minute_counts:
                self._minute_counts[group] = self._deque()
                self._hour_counts[group] = self._deque()

            # Prune old entries
            minute_q = self._minute_counts[group]
            hour_q = self._hour_counts[group]
            while minute_q and now - minute_q[0] > 60:
                minute_q.popleft()
            while hour_q and now - hour_q[0] > 3600:
                hour_q.popleft()

            # Check limits
            if len(minute_q) >= limits['max_per_minute']:
                return False
            if len(hour_q) >= limits['max_per_hour']:
                return False

            # Record
            minute_q.append(now)
            hour_q.append(now)
            return True
    
    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Return current rate stats per group."""
        now = time.time()
        stats = {}
        with self._lock:
            # Snapshot under the lock so allow() concurrent mutations don't
            # corrupt the iteration.
            groups = list(self._minute_counts.keys())
            snapshots = {
                g: (list(self._minute_counts.get(g, [])), list(self._hour_counts.get(g, [])))
                for g in groups
            }
        for group, (minute_q, hour_q) in snapshots.items():
            stats[group] = {
                'last_minute': sum(1 for t in minute_q if now - t <= 60),
                'last_hour': sum(1 for t in hour_q if now - t <= 3600),
            }
        return stats


AGGREGATION_RULES = {
    'auth_fail':       {'window': 120, 'min_count': 3,  'burst_type': 'burst_auth_fail'},
    'ip_block':        {'window': 120, 'min_count': 3,  'burst_type': 'burst_ip_block'},
    'disk_io_error':   {'window': 60,  'min_count': 3,  'burst_type': 'burst_disk_io'},
    'split_brain':     {'window': 300, 'min_count': 2,  'burst_type': 'burst_cluster'},
    'node_disconnect': {'window': 300, 'min_count': 2,  'burst_type': 'burst_cluster'},
    'service_fail':    {'window': 90,  'min_count': 2,  'burst_type': 'burst_service_fail'},
    'service_fail_batch': {'window': 90, 'min_count': 2, 'burst_type': 'burst_service_fail'},
    'system_problem':  {'window': 90,  'min_count': 2,  'burst_type': 'burst_system'},
    'oom_kill':        {'window': 60,  'min_count': 2,  'burst_type': 'burst_generic'},
    'firewall_issue':  {'window': 60,  'min_count': 2,  'burst_type': 'burst_generic'},
}

# Default catch-all rule for any event type NOT listed above.
# This ensures that even unlisted event types get grouped when they
# burst, avoiding notification floods from any source.
_DEFAULT_AGGREGATION = {'window': 60, 'min_count': 2, 'burst_type': 'burst_generic'}

# Event types the burst aggregator must never group. The default
# catch-all (`_DEFAULT_AGGREGATION`) treats anything unlisted as
# group-able, which is the right default for *negative* signals
# (failures, errors, intrusion attempts) but produces noise when
# applied to positive / informational events the user wants to see
# individually.
#
# Concrete failure mode that motivated this list: on 2026-05-21 a
# post-restart resolved-detection batch emitted two `error_resolved`
# events for two stale keys at the same time. The aggregator paired
# them and the user received a useless "+1 error_resolved en 0s
# (2 en total) — Eventos adicionales: Condición resuelta" burst on
# top of the original recovery message. The signal value of a
# recovery is per-event; collapsing them adds zero information.
_AGGREGATION_EXEMPT_EVENTS = frozenset({
    'error_resolved',
})


class BurstAggregator:
    """Accumulates similar events in a time window, then sends a single summary.

    Examples:
    - "Fail2Ban banned 17 IPs in 2 minutes"
    - "Disk I/O errors: 34 events on /dev/sdb in 60s"

    Memory caps (audit Tier 6 — `BurstAggregator` sin cap de memoria):
      - At most `_MAX_EVENTS_PER_BUCKET` events kept per bucket. Beyond that
        we increment a counter but drop the event payload, so a runaway
        cascade can't OOM the dispatch process.
      - At most `_MAX_BUCKETS` open buckets at any time. Beyond that, the
        oldest bucket is force-flushed.
    """

    _MAX_EVENTS_PER_BUCKET = 500    # Plenty for any reasonable burst window
    _MAX_BUCKETS = 200              # Different (event_type, host) combinations

    def __init__(self):
        self._buckets: Dict[str, List] = {}         # bucket_key -> [events]
        self._deadlines: Dict[str, float] = {}      # bucket_key -> flush_deadline
        self._dropped: Dict[str, int] = {}          # bucket_key -> count of events dropped past cap
        self._lock = threading.Lock()

    def ingest(self, event: NotificationEvent) -> Optional[NotificationEvent]:
        """Add event to aggregation. Returns:
        - None if event is being buffered (wait for window)
        - Original event if first in its bucket (sent immediately)

        ALL event types are aggregated: specific rules from AGGREGATION_RULES
        take priority, otherwise the _DEFAULT_AGGREGATION catch-all applies.
        This prevents notification floods from any source.

        Exception: event types listed in `_AGGREGATION_EXEMPT_EVENTS`
        bypass aggregation entirely and are returned to the dispatcher
        as-is. Used for positive/informational events (recoveries,
        scheduled-task completions) where collapsing into a burst
        summary destroys signal value.
        """
        if event.event_type in _AGGREGATION_EXEMPT_EVENTS:
            return event

        rule = AGGREGATION_RULES.get(event.event_type, _DEFAULT_AGGREGATION)

        bucket_key = f"{event.event_type}:{event.data.get('hostname', '')}"

        with self._lock:
            if bucket_key not in self._buckets:
                # Cap on number of distinct buckets — drop the oldest if we
                # would exceed it. Without this, a worm-style attacker emitting
                # events with random hostnames could create unbounded buckets.
                if len(self._buckets) >= self._MAX_BUCKETS:
                    oldest_key = min(self._deadlines, key=self._deadlines.get)
                    self._buckets.pop(oldest_key, None)
                    self._deadlines.pop(oldest_key, None)
                    self._dropped.pop(oldest_key, None)
                self._buckets[bucket_key] = []
                self._deadlines[bucket_key] = time.time() + rule['window']

            # Cap events-per-bucket. If we hit the limit, increment a drop
            # counter so the eventual summary can say "+N more dropped".
            if len(self._buckets[bucket_key]) >= self._MAX_EVENTS_PER_BUCKET:
                self._dropped[bucket_key] = self._dropped.get(bucket_key, 0) + 1
                return None

            self._buckets[bucket_key].append(event)
            
            # First event in bucket: pass through immediately so user gets fast alert
            if len(self._buckets[bucket_key]) == 1:
                return event
            
            # Subsequent events: buffer (will be flushed as summary)
            return None
    
    def flush_expired(self) -> List[NotificationEvent]:
        """Flush all buckets past their deadline. Returns summary events."""
        now = time.time()
        summaries = []
        
        with self._lock:
            expired_keys = [k for k, d in self._deadlines.items() if now >= d]
            
            for key in expired_keys:
                events = self._buckets.pop(key, [])
                del self._deadlines[key]
                
                if len(events) < 2:
                    continue  # Single event already sent on ingest, no summary needed
                
                rule_type = key.split(':')[0]
                rule = AGGREGATION_RULES.get(rule_type, {})
                min_count = rule.get('min_count', 2)
                
                if len(events) < min_count:
                    continue  # Not enough events for a summary
                
                summary = self._create_summary(events, rule)
                if summary:
                    summaries.append(summary)
        
        return summaries
    
    def _create_summary(self, events: List[NotificationEvent],
                        rule: dict) -> Optional[NotificationEvent]:
        """Create a single summary event from multiple events.
        
        Includes individual detail lines so the grouped message is
        self-contained and the user can see exactly what happened.
        """
        if not events:
            return None
        
        first = events[0]
        # Determine highest severity
        sev_order = {'INFO': 0, 'WARNING': 1, 'CRITICAL': 2}
        max_severity = max(events, key=lambda e: sev_order.get(e.severity, 0)).severity
        
        # Collect unique entity_ids
        entity_ids = list(set(e.entity_id for e in events if e.entity_id))
        entity_list = ', '.join(entity_ids[:10]) if entity_ids else 'multiple sources'
        if len(entity_ids) > 10:
            entity_list += f' (+{len(entity_ids) - 10} more)'
        
        # Calculate window
        window_secs = events[-1].ts_epoch - events[0].ts_epoch
        if window_secs < 120:
            window_str = f'{int(window_secs)}s'
        else:
            window_str = f'{int(window_secs / 60)}m'
        
        burst_type = rule.get('burst_type', 'burst_generic')
        
        # Build detail lines from individual events.
        # For each event we extract the most informative field to show
        # a concise one-line summary (e.g. "- service_fail: pvestatd").
        detail_lines = []
        for ev in events[1:]:  # Skip first (already sent individually)
            line = self._summarize_event(ev)
            if line:
                detail_lines.append(f"  - {line}")
        
        # Cap detail lines to avoid extremely long messages
        details = ''
        if detail_lines:
            if len(detail_lines) > 15:
                shown = detail_lines[:15]
                shown.append(f"  ... +{len(detail_lines) - 15} more")
                details = '\n'.join(shown)
            else:
                details = '\n'.join(detail_lines)
        
        # The first event in the bucket was already sent individually on
        # ingest (see line 547 — "fast alert" path). The burst summary
        # must therefore describe the *additional* events that arrived
        # after that initial alert, otherwise the user receives both a
        # "1 system problem" individual notification AND a "2 system
        # problems" burst summary that double-counts the first event.
        # `count` reports the additional count; `total_count` is exposed
        # for templates that want to show "N more (X total in window)".
        additional_count = max(len(events) - 1, 1)
        data = {
            'hostname': first.data.get('hostname') or _resolve_display_hostname(self._config),
            'count': str(additional_count),
            'total_count': str(len(events)),
            'window': window_str,
            'entity_list': entity_list,
            'event_type': first.event_type,
            'details': details,
        }
        
        return NotificationEvent(
            event_type=burst_type,
            severity=max_severity,
            data=data,
            source='aggregator',
            entity=first.entity,
            entity_id='burst',
        )
    
    @staticmethod
    def _summarize_event(event: NotificationEvent) -> str:
        """Extract a concise one-line summary from an event's data."""
        d = event.data
        etype = event.event_type
        
        # Service failures: show service name
        if etype in ('service_fail', 'service_fail_batch'):
            return d.get('service_name', d.get('display_name', etype))
        
        # System problems: first 120 chars of reason
        if 'reason' in d:
            reason = d['reason'].split('\n')[0][:120]
            return reason
        
        # Auth / IP: show username or IP
        if 'username' in d:
            return f"{etype}: {d['username']}"
        if 'ip' in d:
            return f"{etype}: {d['ip']}"
        
        # VM/CT events: show vmid + name
        if 'vmid' in d:
            name = d.get('vmname', '')
            return f"{etype}: {name} ({d['vmid']})" if name else f"{etype}: {d['vmid']}"
        
        # Fallback: event type + entity_id
        if event.entity_id:
            return f"{etype}: {event.entity_id}"
        return etype


# ─── AI rewrite timeout ────────────────────────────────────────────
# Hard cap on how long the AI rewrite can stall the dispatch thread.
# Ollama on slow CPUs can take 90-120 s per request; leaving the dispatch
# loop blocked that long delays every other event in the queue. We give up
# on the rewrite at AI_REWRITE_TIMEOUT_SECONDS and ship the non-AI version.
# Audit Tier 3.2 #2.
AI_REWRITE_TIMEOUT_SECONDS = 25

# A small dedicated pool so an in-flight AI call never starves the dispatch
# thread itself. One worker is enough — events serialize through the dispatch
# loop already.
_ai_rewrite_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix='ai-rewrite'
)


def _format_with_ai_bounded(format_fn, *args, timeout=AI_REWRITE_TIMEOUT_SECONDS, **kwargs):
    """Run an AI rewrite with a hard wall-clock timeout.

    Returns the rewriter's result on success, or `None` on timeout / exception.
    The caller then keeps the original (non-AI) title/body. The future itself
    is not cancelled — Python can't cancel an in-flight HTTP call cleanly —
    but its result is discarded and the dispatch thread proceeds.
    """
    future = _ai_rewrite_pool.submit(format_fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        print(f"[NotificationManager] AI rewrite exceeded {timeout}s — falling back to template")
        return None
    except Exception as e:
        print(f"[NotificationManager] AI rewrite raised {type(e).__name__}: {e}")
        return None


# ─── Notification Manager ─────────────────────────────────────────

class NotificationManager:
    """Central notification orchestrator.
    
    Manages channels, event watchers, deduplication, and dispatch.
    Can run in server mode (background threads) or CLI mode (one-shot).
    """
    
    def __init__(self):
        self._channels: Dict[str, Any] = {}  # channel_name -> channel_instance
        self._event_queue: Queue = Queue()
        self._running = False
        self._config: Dict[str, str] = {}
        self._enabled = False
        self._lock = threading.Lock()
        
        # Watchers
        self._journal_watcher: Optional[JournalWatcher] = None
        self._task_watcher: Optional[TaskWatcher] = None
        self._polling_collector: Optional[PollingCollector] = None
        self._dispatch_thread: Optional[threading.Thread] = None
        
        # Webhook receiver (no thread, passive)
        self._hook_watcher: Optional[ProxmoxHookWatcher] = None
        
        # Cooldown tracking: {fingerprint: last_sent_timestamp}
        self._cooldowns: Dict[str, float] = {}
        
        # Storm protection
        self._group_limiter = GroupRateLimiter()
        self._aggregator = BurstAggregator()
        self._aggregation_thread: Optional[threading.Thread] = None
        
        # Stats
        self._stats = {
            'started_at': None,
            'total_sent': 0,
            'total_errors': 0,
            'last_sent_at': None,
        }
    
    # ─── Configuration ──────────────────────────────────────────
    
    def _load_config(self):
        """Load notification settings from the shared SQLite database."""
        self._config = {}
        # Pairs of (full_key, plaintext) that were stored under the legacy ENC:
        # XOR scheme. We re-encrypt them in ENC2 and persist atomically below.
        # Audit Tier 4 #24.
        legacy_migrations = []
        try:
            if not DB_PATH.exists():
                return

            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            cursor = conn.cursor()
            cursor.execute(
                'SELECT setting_key, setting_value FROM user_settings WHERE setting_key LIKE ?',
                (f'{SETTINGS_PREFIX}%',)
            )
            for key, value in cursor.fetchall():
                # Strip prefix for internal use
                short_key = key[len(SETTINGS_PREFIX):]
                if short_key in SENSITIVE_KEYS and value:
                    if value.startswith(_LEGACY_ENC_PREFIX):
                        # Decrypt the legacy XOR value, queue a re-encrypt to ENC2
                        plaintext = decrypt_sensitive_value(value)
                        legacy_migrations.append((key, plaintext))
                        value = plaintext
                    elif value.startswith(_NEW_ENC_PREFIX):
                        value = decrypt_sensitive_value(value)
                self._config[short_key] = value

            # Persist any legacy → ENC2 upgrades from this load. Done in the
            # same connection so a partial migration can't leave half ENC, half
            # ENC2 — either all writes commit or we fall through to the next
            # load attempt.
            if legacy_migrations:
                now_iso = datetime.now().isoformat()
                migrated = 0
                for full_key, plaintext in legacy_migrations:
                    try:
                        new_value = encrypt_sensitive_value(plaintext)
                        cursor.execute(
                            'INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at) VALUES (?, ?, ?)',
                            (full_key, new_value, now_iso),
                        )
                        migrated += 1
                    except Exception as e:
                        print(f"[NotificationManager] Failed to migrate {full_key} to ENC2: {e}")
                conn.commit()
                if migrated:
                    print(f"[NotificationManager] Migrated {migrated} legacy ENC values to ENC2")
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] Failed to load config: {e}")
        
        # Reconcile per-event toggles with current template defaults.
        # If a template's default_enabled was changed (e.g. state_change False),
        # but the DB has a stale 'true' from a previous default, fix it now.
        # Only override if the user hasn't explicitly set it (we track this with
        # a sentinel: if the value came from auto-save of defaults, it may be stale).
        for event_type, tmpl in TEMPLATES.items():
            key = f'event.{event_type}'
            if key in self._config:
                db_val = self._config[key] == 'true'
                tmpl_default = tmpl.get('default_enabled', True)
                # If template says disabled but DB says enabled, AND there's no
                # explicit user marker, enforce the template default.
                if not tmpl_default and db_val:
                    # Check if user explicitly enabled it (look for a marker)
                    marker = f'event_explicit.{event_type}'
                    if marker not in self._config:
                        self._config[key] = 'false'
        
        self._enabled = self._config.get('enabled', 'false') == 'true'
        self._rebuild_channels()
    
    def _save_setting(self, key: str, value: str):
        """Save a single notification setting to the database."""
        full_key = f'{SETTINGS_PREFIX}{key}'
        now = datetime.now().isoformat()
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
            ''', (full_key, value, now))
            conn.commit()
            conn.close()
            self._config[key] = value
        except Exception as e:
            print(f"[NotificationManager] Failed to save setting {key}: {e}")
    
    def _rebuild_channels(self):
        """Rebuild channel instances from current config.

        Builds the new dict in a local variable first, then atomically swaps
        `self._channels` under the lock. Without this, a dispatch thread that
        iterated `self._channels.items()` mid-rebuild could see a half-empty
        dict and silently drop notifications. Audit Tier 6 (Notification
        stack #6 — `_config`/`_channels` accedidos sin lock).
        """
        new_channels: Dict[str, Any] = {}

        for ch_type in CHANNEL_TYPES:
            enabled_key = f'{ch_type}.enabled'
            if self._config.get(enabled_key) != 'true':
                continue

            # Gather config keys for this channel
            ch_config = {}
            for config_key in CHANNEL_TYPES[ch_type]['config_keys']:
                full_key = f'{ch_type}.{config_key}'
                ch_config[config_key] = self._config.get(full_key, '')

            channel = create_channel(ch_type, ch_config)
            if channel:
                valid, err = channel.validate_config()
                if valid:
                    new_channels[ch_type] = channel
                else:
                    print(f"[NotificationManager] Channel {ch_type} invalid: {err}")

        with self._lock:
            self._channels = new_channels
    
    def reload_config(self):
        """Reload config from DB without restarting."""
        with self._lock:
            self._load_config()
        return {'success': True, 'channels': list(self._channels.keys())}
    
    # ─── Server Mode (Background) ──────────────────────────────
    
    def start(self):
        """Start the notification service in server mode.
        
        Launches watchers and dispatch loop as daemon threads.
        Called by flask_server.py on startup.
        """
        if self._running:
            return
        
        self._load_config()
        self._load_cooldowns_from_db()
        
        if not self._enabled:
            print("[NotificationManager] Service is disabled. Skipping start.")
            return
        
        self._running = True
        self._stats['started_at'] = datetime.now().isoformat()

        # Reset cooldowns for the curated event-type set so the user gets
        # a fresh status report (update_summary, …) and a fresh security
        # signal (auth_fail) after every Monitor deploy/restart. The 24h
        # anti-spam cooldown serves the steady-state use case; the
        # explicit service restart is the signal that "I want to see the
        # current state, not yesterday's silence". High-frequency
        # sources (log_critical_*, disk errors, smart_*) keep their
        # cooldown across restarts to prevent inbox floods.
        self._reset_cooldowns_on_start()

        # Ensure PVE webhook is configured (repairs priv config if missing)
        try:
            from flask_notification_routes import setup_pve_webhook_core
            wh_result = setup_pve_webhook_core()
            if wh_result.get('configured'):
                print("[NotificationManager] PVE webhook configured OK.")
            elif wh_result.get('error'):
                print(f"[NotificationManager] PVE webhook warning: {wh_result['error']}")
        except ImportError:
            pass  # flask_notification_routes not loaded yet (early startup)
        except Exception as e:
            print(f"[NotificationManager] PVE webhook setup error: {e}")
        
        # Start event watchers
        self._journal_watcher = JournalWatcher(self._event_queue)
        self._task_watcher = TaskWatcher(self._event_queue)
        self._polling_collector = PollingCollector(self._event_queue)
        
        self._journal_watcher.start()
        self._task_watcher.start()
        self._polling_collector.start()
        
        # Start dispatch loop
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name='notification-dispatch'
        )
        self._dispatch_thread.start()
        
        print(f"[NotificationManager] Started with channels: {list(self._channels.keys())}")
    
    def stop(self):
        """Stop the notification service cleanly."""
        self._running = False
        
        if self._journal_watcher:
            self._journal_watcher.stop()
        if self._task_watcher:
            self._task_watcher.stop()
        if self._polling_collector:
            self._polling_collector.stop()
        
        print("[NotificationManager] Stopped.")
    
    def _dispatch_loop(self):
        """Main dispatch loop: reads queue -> filters -> formats -> sends -> records."""
        last_cleanup = time.monotonic()
        last_flush = time.monotonic()
        last_digest_check = time.monotonic()
        cleanup_interval = 3600  # Cleanup cooldowns every hour
        flush_interval = 5       # Flush aggregation buckets every 5s
        digest_check_interval = 60  # Re-evaluate digest schedule every minute
        last_quiet_check = 0.0
        quiet_check_interval = 60   # Re-evaluate per-channel quiet window every minute

        while self._running:
            try:
                event = self._event_queue.get(timeout=2)
            except Empty:
                # Periodic maintenance during idle
                now_mono = time.monotonic()
                if now_mono - last_cleanup > cleanup_interval:
                    self._cleanup_old_cooldowns()
                    last_cleanup = now_mono
                # Flush expired aggregation buckets
                if now_mono - last_flush > flush_interval:
                    self._flush_aggregation()
                    last_flush = now_mono
                if now_mono - last_digest_check > digest_check_interval:
                    self._maybe_flush_digests()
                    last_digest_check = now_mono
                # Quiet Hours close → flush buffered sub-CRITICAL events
                # as a single grouped summary. Has to run even when the
                # queue is idle, otherwise users who don't generate any
                # events post-window would never see their summary.
                if now_mono - last_quiet_check > quiet_check_interval:
                    self._maybe_flush_quiet_hours()
                    last_quiet_check = now_mono
                continue
            
            try:
                self._process_event(event)
            except Exception as e:
                print(f"[NotificationManager] Dispatch error: {e}")

            # Also flush aggregation after each event
            now_mono = time.monotonic()
            if now_mono - last_flush > flush_interval:
                self._flush_aggregation()
                last_flush = now_mono
            # Re-check digest schedule after each event too. The idle-only
            # check above misses the daily flush window when the queue stays
            # busy through the digest_time minute (rare but real: a burst of
            # journal events arriving at the same minute as the target). The
            # 23h guard inside _maybe_flush_digests keeps it idempotent.
            if now_mono - last_digest_check > digest_check_interval:
                self._maybe_flush_digests()
                last_digest_check = now_mono
            if now_mono - last_quiet_check > quiet_check_interval:
                self._maybe_flush_quiet_hours()
                last_quiet_check = now_mono
    
    def _flush_aggregation(self):
        """Flush expired aggregation buckets and dispatch summaries."""
        try:
            summaries = self._aggregator.flush_expired()
            for summary_event in summaries:
                # Burst summaries bypass aggregator but still pass cooldown + rate limit
                self._process_event_direct(summary_event)
        except Exception as e:
            print(f"[NotificationManager] Aggregation flush error: {e}")
    
    def _process_event(self, event: NotificationEvent):
        """Process a single event: aggregate -> cooldown -> rate limit -> dispatch.
        
        Per-channel category/event filters are applied in _dispatch_to_channels().
        No global category/event filter exists -- each channel decides independently.
        """
        if not self._enabled:
            return
        
        # Try aggregation (may buffer the event)
        result = self._aggregator.ingest(event)
        if result is None:
            return  # Buffered, will be flushed as summary later
        event = result  # Use original event (first in burst passes through)
        
        # From here, proceed with dispatch (shared with _process_event_direct)
        self._dispatch_event(event)
    
    def _process_event_direct(self, event: NotificationEvent):
        """Process a burst summary event. Bypasses aggregator but applies cooldown + rate limit."""
        if not self._enabled:
            return
        
        self._dispatch_event(event)
    
    def _dispatch_event(self, event: NotificationEvent):
        """Shared dispatch pipeline: cooldown -> rate limit -> render -> send."""
        # Suppress VM/CT start/stop during active backups (second layer of defense).
        # The primary filter is in TaskWatcher, but timing gaps can let events
        # slip through. This catch-all filter checks at dispatch time.
        # Exception: CRITICAL and WARNING events should always be notified.
        _BACKUP_NOISE_TYPES = {'vm_start', 'vm_stop', 'vm_shutdown', 'vm_restart',
                                'ct_start', 'ct_stop', 'ct_shutdown', 'ct_restart'}
        if event.event_type in _BACKUP_NOISE_TYPES and event.severity not in ('CRITICAL', 'WARNING'):
            if self._is_backup_running():
                return
        
        # Check storage exclusions for storage-related events.
        # If the storage is excluded from notifications, suppress the event entirely.
        _STORAGE_EVENTS = {'storage_unavailable', 'storage_low_space', 'storage_warning', 'storage_error'}
        if event.event_type in _STORAGE_EVENTS:
            storage_name = event.data.get('storage_name') or event.data.get('name')
            if storage_name:
                try:
                    from health_persistence import health_persistence
                    if health_persistence.is_storage_excluded(storage_name, 'notifications'):
                        return  # Storage is excluded from notifications, skip silently
                except Exception:
                    pass  # Continue if check fails
        
        # Cooldown check (does NOT stamp yet — see audit Tier 6, cooldown order).
        # If we stamped here, a rate-limit hit or a "no channel enabled for this
        # event_type" situation would burn a 24h cooldown on a delivery that
        # never reached anyone.
        if not self._passes_cooldown(event):
            return

        # Group rate limit check.
        template = TEMPLATES.get(event.event_type, {})
        group = template.get('group', 'other')
        if not self._group_limiter.allow(group):
            return
        
        # Use the properly mapped severity from the event, not from template defaults.
        # event.severity was set by _map_severity which normalises to CRITICAL/WARNING/INFO.
        severity = event.severity
        
        # Inject the canonical severity into data so templates see it too.
        event.data['severity'] = severity
        
        # Render message from template (structured output)
        rendered = render_template(event.event_type, event.data)
        
        # Enrich data with structured fields for channels that support them
        enriched_data = dict(event.data)
        enriched_data['_rendered_fields'] = rendered.get('fields', [])
        enriched_data['_body_html'] = rendered.get('body_html', '')
        enriched_data['_event_type'] = event.event_type
        enriched_data['_group'] = TEMPLATES.get(event.event_type, {}).get('group', 'other')
        
        # Pass journal context if available (for AI enrichment)
        if '_journal_context' in event.data:
            enriched_data['_journal_context'] = event.data['_journal_context']
        
        # Send through all active channels (AI applied per-channel with detail_level).
        # Stamp cooldown only if at least one channel actually delivered — otherwise
        # a misconfigured per-channel toggle would silently lock the event under a
        # 24h cooldown until someone re-enables it. Audit Tier 6.
        delivered = self._dispatch_to_channels(
            rendered['title'], rendered['body'], severity,
            event.event_type, enriched_data, event.source
        )
        if delivered:
            self._record_cooldown(event.fingerprint)
    
    def _dispatch_to_channels(self, title: str, body: str, severity: str,
                               event_type: str, data: Dict, source: str) -> bool:
        """Send notification through configured channels, respecting per-channel filters.

        Each channel owns its own category/event preferences:
          - {channel}.events.{group}  = "true"/"false"  (category toggle, default "true")
          - {channel}.event.{type}    = "true"/"false"  (per-event toggle, default from template)
        No global fallback -- each channel decides independently what it receives.

        AI enhancement is applied per-channel with configurable detail level:
          - {channel}.ai_detail_level = "brief" | "standard" | "detailed"

        Returns True iff at least one channel actually delivered (success). The
        caller uses this to decide whether to stamp the cooldown — see audit
        Tier 6 (cooldown order interacts with per-channel toggles).
        """
        delivered = False
        with self._lock:
            channels = dict(self._channels)
        
        template = TEMPLATES.get(event_type, {})
        event_group = template.get('group', 'other')
        default_event_enabled = 'true' if template.get('default_enabled', True) else 'false'
        
        # Build AI config once (shared across channels, detail_level varies)
        # Use per-provider API key
        ai_provider = self._config.get('ai_provider', 'groq')
        ai_api_key = self._config.get(f'ai_api_key_{ai_provider}', '') or self._config.get('ai_api_key', '')
        ai_config = {
            'ai_enabled': self._config.get('ai_enabled', 'false'),
            'ai_provider': ai_provider,
            'ai_api_key': ai_api_key,
            'ai_model': self._config.get('ai_model', ''),
            'ai_language': self._config.get('ai_language', 'en'),
            'ai_ollama_url': self._config.get('ai_ollama_url', ''),
            # `ai_openai_base_url` was previously dropped from this dict and
            # the downstream `notification_templates.AIRewriter` read it from
            # the dict — meaning a user who configured LiteLLM / Azure as a
            # custom base_url passed the "Test AI" check (which DOES pass it)
            # but every real notification silently went to api.openai.com.
            # Privacy + UX deception bug. Audit Tier 3.2 #1.
            'ai_openai_base_url': self._config.get('ai_openai_base_url', ''),
            'ai_prompt_mode': self._config.get('ai_prompt_mode', 'default'),
            'ai_custom_prompt': self._config.get('ai_custom_prompt', ''),
        }
        
        # Get journal context if available (will be enriched per-channel based on detail_level)
        raw_journal_context = data.get('_journal_context', '')
        
        for ch_name, channel in channels.items():
            # ── Per-channel category check ──
            # Default: category enabled (true) unless explicitly disabled.
            ch_group_key = f'{ch_name}.events.{event_group}'
            if self._config.get(ch_group_key, 'true') == 'false':
                continue  # Channel has this category disabled

            # ── Per-channel event check ──
            # Default: from template default_enabled, unless explicitly set.
            ch_event_key = f'{ch_name}.event.{event_type}'
            if self._config.get(ch_event_key, default_event_enabled) == 'false':
                continue  # Channel has this specific event disabled

            # ── Per-channel quiet hours ──
            # The user marks a window (e.g. 22:00 → 06:00) during which only
            # CRITICAL events reach this channel. Sub-CRITICAL events are
            # **buffered** to `quiet_pending` and flushed as a SINGLE grouped
            # summary when the window closes — so the user doesn't get
            # paged at 3 AM but also doesn't lose 8h of activity overnight.
            # CRITICAL always wins. The window is configured per-channel.
            # See _in_quiet_hours() for boundary semantics.
            # `_dispatch_to_channels` does NOT receive the NotificationEvent
            # object — only the rendered primitives. Using `event.X` here
            # raised `NameError` for every event passing through, silenced
            # by the dispatch loop's broad except → no notifications EVER
            # delivered after Quiet Hours + Daily Digest were merged.
            if severity != 'CRITICAL' and self._in_quiet_hours(ch_name):
                self._buffer_quiet_event(ch_name, event_type, event_group,
                                          severity, title, body)
                continue

            # ── Per-channel daily digest ──
            # If the user has digest mode on for this channel, generic INFO
            # events (backup_complete, update_summary, …) are buffered to a
            # SQLite table instead of firing immediately. A single grouped
            # summary is sent once a day at the configured time. CRITICAL
            # and WARNING never wait — they always pass through. Events
            # the user explicitly wants to see live (vm_start, etc.) are
            # excluded from the digest by `_DIGEST_EXEMPT_EVENTS`.
            if self._should_buffer_for_digest(ch_name, severity, event_type):
                self._buffer_digest_event(ch_name, event_type, event_group,
                                          severity, title, body)
                continue
            
            try:
                ch_title, ch_body = title, body
                
                # ── Per-channel settings ──
                # Email defaults to 'detailed' (technical report), others to 'standard'
                detail_level_key = f'{ch_name}.ai_detail_level'
                default_detail = 'detailed' if ch_name == 'email' else 'standard'
                detail_level = self._config.get(detail_level_key, default_detail)
                
                # Rich format (emojis) is a user preference per channel
                rich_key = f'{ch_name}.rich_format'
                use_rich_format = self._config.get(rich_key, 'false') == 'true'
                
                # ── Per-channel AI enhancement ──
                # Apply AI with channel-specific detail level and emoji setting
                # If AI is enabled AND rich_format is on, AI will include emojis directly
                # Pass channel_type so AI knows whether to append original (email only)
                channel_ai_config = {**ai_config, 'channel_type': ch_name}

                # Isolate the AI/enrich block in its own try so a failure
                # here (raised from enrich_context_for_ai or any other
                # helper not protected by _format_with_ai_bounded) does NOT
                # abort the channel.send() below — the user still gets the
                # raw template-formatted notification. Audit Tier 6 —
                # `_dispatch_to_channels`: AI failure dropped the notification.
                try:
                    enriched_context = enrich_context_for_ai(
                        title=ch_title,
                        body=ch_body,
                        event_type=event_type,
                        data=data,
                        journal_context=raw_journal_context,
                        detail_level=detail_level
                    )

                    # Wrap the AI rewrite with a hard timeout so a slow Ollama
                    # call (90-120 s on slow CPUs) doesn't stall the dispatch
                    # thread and delay every other queued event. On timeout we
                    # ship the non-AI title/body — the user still gets the
                    # notification, just without LLM polish. Audit Tier 3.2 #2.
                    ai_result = _format_with_ai_bounded(
                        format_with_ai_full,
                        ch_title, ch_body, severity, channel_ai_config,
                        detail_level=detail_level,
                        journal_context=enriched_context,
                        use_emojis=use_rich_format,
                    )
                    if ai_result is not None:
                        ch_title = ai_result.get('title', ch_title)
                        ch_body = ai_result.get('body', ch_body)
                except Exception as ai_err:
                    print(f"[NotificationManager] AI enrich/rewrite failed for {ch_name}: "
                          f"{type(ai_err).__name__}: {ai_err} — sending template")
                
                # Fallback emoji enrichment only if AI is disabled but rich_format is on
                # (If AI processed the message with emojis, this is skipped)
                ai_enabled_str = ai_config.get('ai_enabled', 'false')
                ai_enabled = ai_enabled_str == 'true' if isinstance(ai_enabled_str, str) else bool(ai_enabled_str)
                
                if use_rich_format and not ai_enabled:
                    ch_title, ch_body = enrich_with_emojis(
                        event_type, ch_title, ch_body, data
                    )
                
                result = channel.send(ch_title, ch_body, severity, data)
                self._record_history(
                    event_type, ch_name, ch_title, ch_body, severity,
                    result.get('success', False),
                    result.get('error', ''),
                    source
                )
                
                if result.get('success'):
                    self._stats['total_sent'] += 1
                    self._stats['last_sent_at'] = datetime.now().isoformat()
                    delivered = True
                else:
                    self._stats['total_errors'] += 1
                    print(f"[NotificationManager] Send failed ({ch_name}): {result.get('error')}")

            except Exception as e:
                self._stats['total_errors'] += 1
                self._record_history(
                    event_type, ch_name, title, body, severity,
                    False, str(e), source
                )

        return delivered

    # ─── Cooldown / Dedup ───────────────────────────────────────
    
    def _is_backup_running(self) -> bool:
        """Quick check if any vzdump process is currently active.
        
        Reads /var/log/pve/tasks/active and also checks for vzdump processes.
        """
        import os
        # Method 1: Check active tasks file
        try:
            with open('/var/log/pve/tasks/active', 'r') as f:
                for line in f:
                    if ':vzdump:' in line:
                        parts = line.strip().split(':')
                        if len(parts) >= 3:
                            try:
                                # PID in UPID is HEXADECIMAL
                                pid = int(parts[2], 16)
                                os.kill(pid, 0)
                                return True
                            except (ValueError, ProcessLookupError, PermissionError):
                                pass
        except (OSError, IOError):
            pass
        
        # Method 2: Check for running vzdump processes directly
        import subprocess
        try:
            result = subprocess.run(
                ['pgrep', '-x', 'vzdump'],
                capture_output=True, timeout=2
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        
        return False
    
    def _in_quiet_hours(self, ch_name: str) -> bool:
        """True if the channel's quiet-hours window is active right now.

        Settings keys (per channel, all strings in user_settings):
            <ch>.quiet_enabled  — "true" / "false"  (default: "false")
            <ch>.quiet_start    — "HH:MM"           (default: "22:00")
            <ch>.quiet_end      — "HH:MM"           (default: "06:00")

        The window is half-open [start, end) and may cross midnight
        (start > end means "from tonight to tomorrow morning"). If start
        equals end the window is treated as disabled — that's the only
        way to express "no quiet hours" without a separate boolean. The
        wall-clock comparison uses the host's local time (datetime.now())
        so a user setting "22:00–06:00" gets exactly that in their own
        timezone, regardless of the Monitor's container TZ.
        """
        if self._config.get(f'{ch_name}.quiet_enabled', 'false') != 'true':
            return False
        try:
            start_s = self._config.get(f'{ch_name}.quiet_start', '22:00')
            end_s = self._config.get(f'{ch_name}.quiet_end', '06:00')
            sh, sm = (int(x) for x in start_s.split(':', 1))
            eh, em = (int(x) for x in end_s.split(':', 1))
        except (ValueError, AttributeError):
            return False
        if (sh, sm) == (eh, em):
            return False
        now = datetime.now()
        cur = now.hour * 60 + now.minute
        start = sh * 60 + sm
        end = eh * 60 + em
        if start < end:
            return start <= cur < end
        return cur >= start or cur < end

    # Events that should NEVER be buffered into a digest — they are
    # short-cooldown action / state events the user explicitly opted in
    # to see live. Folding them into a daily digest would defeat that
    # opt-in. Mirrors the same lists from _passes_cooldown.
    _DIGEST_EXEMPT_EVENTS = frozenset({
        'backup_complete', 'backup_fail', 'backup_start',
        'replication_complete', 'replication_fail',
        'vm_start', 'vm_stop', 'vm_shutdown', 'vm_restart',
        'ct_start', 'ct_stop', 'ct_shutdown', 'ct_restart',
        'vm_fail', 'ct_fail',
        'system_shutdown', 'system_reboot',
    })

    def _should_buffer_for_digest(self, ch_name: str, severity: str,
                                  event_type: str) -> bool:
        """Decide if this event should go to the channel's digest buffer
        instead of firing immediately. Only applies to generic INFO
        events; CRITICAL and WARNING always pass through.

        Takes primitives (severity, event_type) rather than a
        NotificationEvent — the caller in `_dispatch_to_channels` only
        has the rendered fields, not the event object.
        """
        if severity != 'INFO':
            return False
        if event_type in self._DIGEST_EXEMPT_EVENTS:
            return False
        if self._config.get(f'{ch_name}.digest_enabled', 'false') != 'true':
            return False
        return True

    def _buffer_digest_event(self, ch_name: str, event_type: str,
                             event_group: str, severity: str,
                             title: str, body: str) -> None:
        """Append an event to the channel's digest buffer in SQLite.

        Primitives only — same reason as `_should_buffer_for_digest`.
        """
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute(
                'INSERT INTO digest_pending '
                '(channel, event_type, event_group, severity, ts, title, body) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (ch_name, event_type, event_group, severity,
                 int(time.time()), title, body),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] digest buffer write failed: {e}")

    def _maybe_flush_digests(self) -> None:
        """Per-channel: if the local clock has reached the configured
        digest_time and we haven't flushed in the last 23h, send a
        grouped summary of the buffered INFO events and clear the rows.
        Idempotent — safe to call every minute from the dispatch loop.
        """
        now = datetime.now()
        cur_minute = now.hour * 60 + now.minute
        for ch_name, channel in list(self._channels.items()):
            if self._config.get(f'{ch_name}.digest_enabled', 'false') != 'true':
                continue
            time_str = self._config.get(f'{ch_name}.digest_time', '09:00')
            try:
                dh, dm = (int(x) for x in time_str.split(':', 1))
            except (ValueError, AttributeError):
                continue
            target = dh * 60 + dm
            # Fire when we're at the target minute *or* up to 5 min after,
            # so a brief skip in the loop (busy dispatch) doesn't lose the
            # day's digest. The last_at guard makes this idempotent.
            if not (target <= cur_minute < target + 5):
                continue
            last_iso = self._config.get(f'{ch_name}.digest_last_at', '')
            if last_iso:
                try:
                    last_dt = datetime.fromisoformat(last_iso)
                    if (now - last_dt).total_seconds() < 23 * 3600:
                        continue  # Already sent today
                except ValueError:
                    pass
            try:
                self._flush_digest_for_channel(ch_name, channel, now)
            except Exception as e:
                print(f"[NotificationManager] digest flush failed for "
                      f"{ch_name}: {e}")

    def _flush_digest_for_channel(self, ch_name: str, channel: Any,
                                  now: datetime) -> None:
        """Read pending rows for the channel, render a grouped summary,
        send it, and delete the buffer entries on success."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, event_type, event_group, ts, title, body '
                'FROM digest_pending WHERE channel = ? ORDER BY ts ASC',
                (ch_name,),
            )
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] digest read failed for {ch_name}: {e}")
            return

        # Mark `last_at` even if there's nothing to send — otherwise an
        # empty buffer keeps re-triggering the 5-minute window for hours.
        self._save_setting(f'{ch_name}.digest_last_at', now.isoformat())

        if not rows:
            return

        host = _hostname(self._config)
        summary_title = (
            f"{host}: 24h summary ({now.strftime('%Y-%m-%d %H:%M')})"
        )
        summary_body = self._compose_digest_body(rows)

        try:
            channel.send(summary_title, summary_body, severity='INFO',
                         data={'_digest': True, '_count': len(rows)})
        except Exception as e:
            print(f"[NotificationManager] digest send failed for "
                  f"{ch_name}: {e}")
            return

        # Delete only after a successful send so a transient failure
        # doesn't lose the day's data.
        try:
            ids = [r[0] for r in rows]
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            placeholders = ','.join('?' * len(ids))
            conn.execute(
                f'DELETE FROM digest_pending WHERE id IN ({placeholders})',
                ids,
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] digest cleanup failed for "
                  f"{ch_name}: {e}")

    def _compose_digest_body(self, rows: list) -> str:
        """Render a grouped summary body. rows is a list of
        (id, event_type, event_group, ts, title, body) tuples ordered
        by timestamp ASC.
        """
        from collections import OrderedDict
        groups: OrderedDict[str, list] = OrderedDict()
        for _id, ev_type, group, ts, title, body in rows:
            label = group or 'other'
            groups.setdefault(label, []).append((ts, ev_type, title))

        lines = [f"{len(rows)} INFO events grouped by category:\n"]
        for group, items in groups.items():
            lines.append(f"{group.title()}: {len(items)}")
            for ts, ev_type, title in items[:8]:
                hhmm = datetime.fromtimestamp(ts).strftime('%H:%M')
                short_title = title.split(': ', 1)[-1] if ': ' in title else title
                lines.append(f"  • {hhmm}  {short_title}")
            if len(items) > 8:
                lines.append(f"  • … and {len(items) - 8} more")
            lines.append('')
        lines.append(
            '(Critical/Warning events arrived at the time they happened, '
            'not in this digest.)'
        )
        return '\n'.join(lines).rstrip() + '\n'

    # ─── Quiet Hours buffer + flush ────────────────────────────
    # Reused infrastructure: `quiet_pending` table (created in
    # health_persistence) has the same shape as `digest_pending`, so
    # `_compose_digest_body` renders the summary unchanged. What
    # differs is the lifecycle — quiet_pending flushes when each
    # channel's window CLOSES, not at a fixed daily time. We track
    # that transition via `self._was_in_quiet_hours[ch_name]`.

    def _buffer_quiet_event(self, ch_name: str, event_type: str,
                            event_group: str, severity: str,
                            title: str, body: str) -> None:
        """Append a sub-CRITICAL event to the channel's quiet-hours
        buffer in SQLite. Mirrors `_buffer_digest_event` — same shape,
        different table.
        """
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute(
                'INSERT INTO quiet_pending '
                '(channel, event_type, event_group, severity, ts, title, body) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (ch_name, event_type, event_group, severity,
                 int(time.time()), title, body),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] quiet_pending write failed: {e}")

    def _maybe_flush_quiet_hours(self) -> None:
        """Detect per-channel quiet-hours close (in→out transition) and
        emit one summary notification with everything buffered during
        the window. Called every ~60s from the dispatch loop.

        State held in-memory: `self._was_in_quiet_hours[ch_name]`. On
        first run after restart all channels start as "unknown" — we
        seed with the current window status WITHOUT firing a summary
        when the channel is currently IN its quiet window (a Monitor
        restart mid-window must not look like a "close" transition).

        Recovery seed: if the channel is currently OUT of the quiet
        window AND there are leftover rows in `quiet_pending`, those
        rows belong to a window that closed during a restart — they
        would otherwise stay buffered forever because the seed marks
        the channel as "out" without ever seeing the in→out edge.
        Flush them now so the user gets their overnight summary even
        when an update lands right as the window closes.
        """
        if not hasattr(self, '_was_in_quiet_hours'):
            self._was_in_quiet_hours = {}

        for ch_name, channel in list(self._channels.items()):
            currently_in = self._in_quiet_hours(ch_name)
            previously_in = self._was_in_quiet_hours.get(ch_name)
            self._was_in_quiet_hours[ch_name] = currently_in

            # Seed run (no prior state).
            if previously_in is None:
                # Recovery: leftover buffer from a window that closed
                # during a restart must still reach the user.
                if not currently_in and self._has_pending_quiet_rows(ch_name):
                    try:
                        self._flush_quiet_for_channel(ch_name, channel)
                    except Exception as e:
                        print(f"[NotificationManager] quiet recovery flush "
                              f"failed for {ch_name}: {e}")
                continue
            # Still in the window → just buffer.
            if currently_in:
                continue
            # Was in window, now out → close transition → flush.
            if previously_in and not currently_in:
                try:
                    self._flush_quiet_for_channel(ch_name, channel)
                except Exception as e:
                    print(f"[NotificationManager] quiet flush failed for "
                          f"{ch_name}: {e}")

    def _has_pending_quiet_rows(self, ch_name: str) -> bool:
        """Cheap existence check used by the recovery branch of
        `_maybe_flush_quiet_hours`. We don't reuse `_flush_*` for this
        because a no-op flush call would still open a connection and
        do the SELECT — a single COUNT keeps the seed pass O(1) per
        channel when nothing is pending."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            cursor.execute(
                'SELECT 1 FROM quiet_pending WHERE channel = ? LIMIT 1',
                (ch_name,),
            )
            row = cursor.fetchone()
            conn.close()
            return row is not None
        except Exception as e:
            print(f"[NotificationManager] quiet pending probe failed for "
                  f"{ch_name}: {e}")
            return False

    def _flush_quiet_for_channel(self, ch_name: str, channel: Any) -> None:
        """Send a single grouped summary of everything buffered for
        `ch_name` during the just-closed quiet window, then drop the
        buffer rows. Reuses `_compose_digest_body` for rendering since
        the row shape is identical.
        """
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, event_type, event_group, ts, title, body '
                'FROM quiet_pending WHERE channel = ? ORDER BY ts ASC',
                (ch_name,),
            )
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] quiet read failed for {ch_name}: {e}")
            return

        if not rows:
            return

        host = _hostname(self._config)
        summary_title = (
            f"{host}: {len(rows)} events buffered during Quiet Hours"
        )
        summary_body = self._compose_digest_body(rows)

        try:
            channel.send(summary_title, summary_body, severity='INFO',
                         data={'_quiet_hours_summary': True, '_count': len(rows)})
        except Exception as e:
            print(f"[NotificationManager] quiet send failed for "
                  f"{ch_name}: {e}")
            return

        # Only drop the rows after a successful send so a transient
        # transport failure (Telegram timeout, SMTP outage) doesn't
        # lose the user's overnight context.
        try:
            ids = [r[0] for r in rows]
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            placeholders = ','.join('?' * len(ids))
            conn.execute(
                f'DELETE FROM quiet_pending WHERE id IN ({placeholders})',
                ids,
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] quiet cleanup failed for "
                  f"{ch_name}: {e}")

    def _passes_cooldown(self, event: NotificationEvent) -> bool:
        """Check if the event passes cooldown rules WITHOUT stamping.

        Splits the historical `_check_cooldown` into a pure predicate plus
        `_record_cooldown` (separate stamp). Lets the caller check rate-limit
        and per-channel filters first — if any of those drop the event, we
        avoid burning a 24h cooldown on a delivery that never happened.
        Audit Tier 6 (Notification stack #4 + cooldown/per-channel interaction).
        """
        now = time.time()
        
        # Determine cooldown period
        template = TEMPLATES.get(event.event_type, {})
        group = template.get('group', 'system')
        
        # Priority: per-type config > per-severity > default
        cooldown_key = f'cooldown.{event.event_type}'
        cooldown_str = self._config.get(cooldown_key)
        
        if cooldown_str is None:
            cooldown_key_group = f'cooldown.{group}'
            cooldown_str = self._config.get(cooldown_key_group)
        
        if cooldown_str is not None:
            cooldown = int(cooldown_str)
        else:
            cooldown = DEFAULT_COOLDOWNS.get(event.severity, 86400)

        # Health state-change events (CPU at 95%, memory full, temperature
        # critical, disk near capacity, ...) describe a SUSTAINED state, not
        # a one-shot bug. Sitting at 24h means the user gets one ping when
        # the threshold trips and then silence even if the condition lasts
        # for days; the 30min/1h cadence here keeps them reminded while the
        # condition persists, but coarse enough to not flood the channel.
        # The 24h default takes over for unique bug/error events
        # (system_problem, auth_fail, ...) that get nothing from being
        # repeated.
        _HEALTH_CATEGORY_COOLDOWNS = {
            'disks': 86400, 'smart': 86400, 'zfs': 86400, 'updates': 86400,
            'storage': 3600, 'temperature': 3600, 'logs': 3600,
            'security': 3600, 'disk': 3600,
            'network': 1800, 'pve_services': 1800,
            'vms': 1800, 'cpu': 1800, 'memory': 1800,
        }
        if event.event_type == 'state_change' and event.source == 'health':
            cat = (event.data or {}).get('category', '')
            cat_cd = _HEALTH_CATEGORY_COOLDOWNS.get(cat)
            if cat_cd is not None and cooldown_str is None:
                cooldown = cat_cd

        # Backup/replication events: each execution is unique and should
        # always be delivered. A 10s cooldown prevents exact duplicates
        # (webhook + tasks) but allows repeated backup jobs to report.
        _ALWAYS_DELIVER = {'backup_complete', 'backup_fail', 'backup_start',
                           'replication_complete', 'replication_fail'}
        if event.event_type in _ALWAYS_DELIVER and cooldown_str is None:
            cooldown = 10
        
        # VM/CT state changes are real user actions that should always be
        # delivered. Each start/stop/shutdown is a distinct event.  A 5s
        # cooldown prevents exact duplicates from concurrent watchers.
        _STATE_EVENTS = {
            'vm_start', 'vm_stop', 'vm_shutdown', 'vm_restart',
            'ct_start', 'ct_stop', 'ct_shutdown', 'ct_restart',
            'vm_fail', 'ct_fail',
        }
        if event.event_type in _STATE_EVENTS and cooldown_str is None:
            cooldown = 5
        
        # System shutdown/reboot must be delivered immediately -- the node
        # is going down and there may be only seconds to send the message.
        _URGENT_EVENTS = {'system_shutdown', 'system_reboot'}
        if event.event_type in _URGENT_EVENTS and cooldown_str is None:
            cooldown = 5
        
        # Check against last sent time using stable fingerprint. Stamp is
        # deferred to `_record_cooldown()` — only invoked once the event has
        # passed rate-limit AND at least one channel actually delivered it.
        last_sent = self._cooldowns.get(event.fingerprint, 0)
        if now - last_sent < cooldown:
            return False
        return True

    def _record_cooldown(self, fingerprint: str):
        """Stamp the cooldown for a fingerprint that was actually delivered."""
        now = time.time()
        self._cooldowns[fingerprint] = now
        self._persist_cooldown(fingerprint, now)
    
    # Event types whose cooldown should be cleared at every service start.
    # Two reasons to be on this list:
    #   (a) "Status report" events — user expects a fresh report after a
    #       deploy/restart even if 24h hasn't passed. update_summary &
    #       friends fall here.
    #   (b) "User-actionable security events" where the cooldown surviving
    #       a Monitor reinstall would silence a real attack. auth_fail —
    #       if a login failure happens right after an upgrade we want it
    #       delivered, not swallowed by yesterday's cooldown for the same
    #       source IP.
    # Anything NOT on this list keeps its 24h cooldown across restarts
    # (log_critical_*, disk errors, smart_*, …) — preserves the
    # anti-flood guarantee for sources that can burst.
    _EVENT_TYPES_RESET_ON_START = (
        # Update-status reports
        'update_summary',
        'proxmenux_update',
        'post_install_update',
        'pve_update',
        'update_available',
        'nvidia_driver_update_available',
        'secure_gateway_update_available',
        # Security events that must not be silenced by stale cooldowns
        # following a Monitor reinstall (Pedro Rico, 19/05).
        'auth_fail',
    )

    def _reset_cooldowns_on_start(self):
        """Clear DB rows in notification_last_sent for the curated set of
        event types listed in `_EVENT_TYPES_RESET_ON_START`.

        Fingerprint format used by `_passes_cooldown` is
        `<host>:<entity>:<event_type>[:<entity_id>]`. We match by the
        event_type segment with LIKE patterns covering both the
        trailing-colon case (`…:update_summary:`) and the no-suffix case
        (`…:nvidia_driver_update_available`) for managed-install events.
        Also clear the in-memory cache so the running dispatcher
        immediately sees the reset, without waiting for the next
        `_load_cooldowns_from_db()`.
        """
        try:
            if not DB_PATH.exists():
                return
            patterns = []
            for et in self._EVENT_TYPES_RESET_ON_START:
                patterns.append(f'%:{et}:%')  # entity_id non-empty form
                patterns.append(f'%:{et}')    # entity_id empty / managed-install form
            where = ' OR '.join('fingerprint LIKE ?' for _ in patterns)
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            cursor.execute(f'DELETE FROM notification_last_sent WHERE {where}', patterns)
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            # Mirror the DB delete in the in-memory cache so the
            # dispatch thread doesn't keep ghost cooldowns until the
            # next reload.
            for fp in list(self._cooldowns.keys()):
                for et in self._EVENT_TYPES_RESET_ON_START:
                    if f':{et}:' in fp or fp.endswith(f':{et}'):
                        self._cooldowns.pop(fp, None)
                        break
            if deleted > 0:
                print(f"[NotificationManager] Reset {deleted} cooldowns on startup")
        except Exception as e:
            print(f"[NotificationManager] Failed to reset cooldowns on start: {e}")

    def _load_cooldowns_from_db(self):
        """Load persistent cooldown state from SQLite (up to 48h).

        The `notification_last_sent` table is shared with PollingCollector
        (`health_*` prefix) and JournalWatcher (`diskio_*`, `fs_*`,
        `fs_serial_*`, plain device names). The manager's own fingerprints
        always look like `<host>:<entity>:<...>:<event_type>` (contain `:`).
        Loading the OTHER modules' fingerprints into `self._cooldowns` made
        the manager's own dispatch see ghost cooldowns from rows it never
        wrote — which then failed `_passes_cooldown` and dropped events
        that should have gone through. Audit Tier 6 (Notification stack —
        `_load_cooldowns_from_db` carga TODOS los fingerprints).
        """
        try:
            if not DB_PATH.exists():
                return
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            cursor.execute('SELECT fingerprint, last_sent_ts FROM notification_last_sent')
            now = time.time()
            _OTHER_PREFIXES = ('health_', 'diskio_', 'fs_', 'fs_serial_')
            loaded = 0
            for fp, ts in cursor.fetchall():
                if not fp:
                    continue
                # Skip rows owned by other producers; they manage their own state.
                if fp.startswith(_OTHER_PREFIXES):
                    continue
                # The manager's fingerprint format always contains `:`.
                if ':' not in fp:
                    continue
                if now - ts < 172800:  # 48h window
                    self._cooldowns[fp] = ts
                    loaded += 1
            conn.close()
            if loaded:
                print(f"[NotificationManager] Loaded {loaded} cooldowns from DB")
        except Exception as e:
            print(f"[NotificationManager] Failed to load cooldowns: {e}")
    
    def _persist_cooldown(self, fingerprint: str, ts: float):
        """Save cooldown timestamp to SQLite for restart persistence."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute('''
                INSERT OR REPLACE INTO notification_last_sent (fingerprint, last_sent_ts, count)
                VALUES (?, ?, COALESCE(
                    (SELECT count + 1 FROM notification_last_sent WHERE fingerprint = ?), 1
                ))
            ''', (fingerprint, int(ts), fingerprint))
            conn.commit()
            conn.close()
        except Exception:
            pass  # Non-critical, in-memory cooldown still works
    
    def _cleanup_old_cooldowns(self):
        """Remove cooldown entries older than 48h from both memory and DB."""
        cutoff = time.time() - 172800  # 48h
        self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > cutoff}
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('DELETE FROM notification_last_sent WHERE last_sent_ts < ?', (int(cutoff),))
            conn.commit()
            conn.close()
        except Exception:
            pass
    
    # ─── History Recording ──────────────────────────────────────
    
    def _record_history(self, event_type: str, channel: str, title: str,
                        message: str, severity: str, success: bool,
                        error_message: str, source: str):
        """Record a notification attempt in the history table."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notification_history
                (event_type, channel, title, message, severity, sent_at, success, error_message, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_type, channel, title, message[:500], severity,
                datetime.now().isoformat(), 1 if success else 0,
                error_message[:500] if error_message else None, source
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[NotificationManager] History record error: {e}")
    
    # ─── Public API (used by Flask routes and CLI) ──────────────
    
    def emit_event(self, event_type: str, severity: str, data: Dict,
                   source: str = 'api', entity: str = 'node', entity_id: str = '') -> Dict[str, Any]:
        """Emit an event through the notification system.
        
        This creates a NotificationEvent and processes it through the normal pipeline,
        including toggle checks, template rendering, and cooldown.
        
        Used by internal endpoints like the shutdown notification hook.
        
        Args:
            event_type: Type of event (must match TEMPLATES key)
            severity: INFO, WARNING, CRITICAL
            data: Event data for template rendering
            source: Origin of event
            entity: Entity type (node, vm, ct, storage, etc.)
            entity_id: Entity identifier
        """
        from notification_events import NotificationEvent
        
        event = NotificationEvent(
            event_type=event_type,
            severity=severity,
            data=data,
            source=source,
            entity=entity,
            entity_id=entity_id,
        )
        
        # For urgent events (shutdown/reboot), dispatch directly to ensure
        # immediate delivery before the system goes down.
        # For other events, use the normal pipeline with aggregation.
        _URGENT_EVENTS = {'system_shutdown', 'system_reboot'}
        if event_type in _URGENT_EVENTS:
            self._dispatch_event(event)
            return {'success': True, 'event_type': event_type, 'dispatched': 'direct'}
        else:
            self._process_event(event)
            return {'success': True, 'event_type': event_type, 'dispatched': 'queued'}
    
    def send_notification(self, event_type: str, severity: str,
                          title: str, message: str,
                          data: Optional[Dict] = None,
                          source: str = 'api',
                          skip_toggle_check: bool = False) -> Dict[str, Any]:
        """Send a notification directly (bypasses queue and cooldown).
        
        Used by CLI and API for explicit sends.
        
        Args:
            event_type: Type of event (must match TEMPLATES key)
            severity: INFO, WARNING, CRITICAL
            title: Notification title
            message: Notification body
            data: Extra data for template rendering
            source: Origin of notification (api, cli, health_monitor, etc.)
            skip_toggle_check: If True, send even if event toggle is disabled.
                               Use for 'custom' or 'other' events that should always send.
        """
        if not self._channels:
            self._load_config()
        
        if not self._channels:
            return {
                'success': False,
                'error': 'No channels configured or enabled',
                'channels_sent': [],
            }
        
        # Check if this event type is enabled (unless explicitly skipped)
        # 'custom' and 'other' events always send (used for manual/script notifications)
        if not skip_toggle_check and event_type not in ('custom', 'other'):
            if not self.is_event_enabled(event_type):
                return {
                    'success': False,
                    'error': f'Event type "{event_type}" is disabled in notification settings',
                    'channels_sent': [],
                    'skipped': True,
                }
        
        # Render template if available
        if event_type in TEMPLATES and not message:
            rendered = render_template(event_type, data or {})
            title = title or rendered['title']
            message = rendered['body']
            severity = severity or rendered['severity']
        
        # AI config for enhancement - use per-provider API key
        ai_provider = self._config.get('ai_provider', 'groq')
        ai_api_key = self._config.get(f'ai_api_key_{ai_provider}', '') or self._config.get('ai_api_key', '')
        ai_config = {
            'ai_enabled': self._config.get('ai_enabled', 'false'),
            'ai_provider': ai_provider,
            'ai_api_key': ai_api_key,
            'ai_model': self._config.get('ai_model', ''),
            'ai_language': self._config.get('ai_language', 'en'),
            'ai_ollama_url': self._config.get('ai_ollama_url', ''),
            # `ai_openai_base_url` was previously dropped from this dict and
            # the downstream `notification_templates.AIRewriter` read it from
            # the dict — meaning a user who configured LiteLLM / Azure as a
            # custom base_url passed the "Test AI" check (which DOES pass it)
            # but every real notification silently went to api.openai.com.
            # Privacy + UX deception bug. Audit Tier 3.2 #1.
            'ai_openai_base_url': self._config.get('ai_openai_base_url', ''),
            'ai_prompt_mode': self._config.get('ai_prompt_mode', 'default'),
            'ai_custom_prompt': self._config.get('ai_custom_prompt', ''),
        }
        
        results = {}
        channels_sent = []
        errors = []
        
        with self._lock:
            channels = dict(self._channels)
        
        for ch_name, channel in channels.items():
            try:
                # Apply AI enhancement per channel with its detail level and emoji setting
                detail_level_key = f'{ch_name}.ai_detail_level'
                detail_level = self._config.get(detail_level_key, 'standard')
                
                rich_key = f'{ch_name}.rich_format'
                use_rich_format = self._config.get(rich_key, 'false') == 'true'
                
                # Pass channel_type so AI knows whether to append original (email only)
                channel_ai_config = {**ai_config, 'channel_type': ch_name}
                ai_result = format_with_ai_full(
                    title, message, severity, channel_ai_config,
                    detail_level=detail_level,
                    use_emojis=use_rich_format
                )
                ch_title = ai_result.get('title', title)
                ch_message = ai_result.get('body', message)
                
                result = channel.send(ch_title, ch_message, severity, data)
                results[ch_name] = result
                
                self._record_history(
                    event_type, ch_name, ch_title, ch_message, severity,
                    result.get('success', False),
                    result.get('error', ''),
                    source
                )
                
                if result.get('success'):
                    channels_sent.append(ch_name)
                else:
                    errors.append(f"{ch_name}: {result.get('error')}")
            except Exception as e:
                errors.append(f"{ch_name}: {str(e)}")
        
        return {
            'success': len(channels_sent) > 0,
            'channels_sent': channels_sent,
            'errors': errors,
            'total_channels': len(channels),
        }
    
    def send_raw(self, title: str, message: str,
                 severity: str = 'INFO',
                 source: str = 'api') -> Dict[str, Any]:
        """Send a raw message without template (for custom scripts)."""
        return self.send_notification(
            'custom', severity, title, message, source=source
        )
    
    def test_channel(self, channel_name: str = 'all') -> Dict[str, Any]:
        """Test one or all configured channels with AI enhancement."""
        if not self._channels:
            self._load_config()
        
        if not self._channels:
            return {'success': False, 'error': 'No channels configured'}
        
        results = {}
        
        if channel_name == 'all':
            targets = dict(self._channels)
        elif channel_name in self._channels:
            targets = {channel_name: self._channels[channel_name]}
        else:
            # Try to create channel from config even if not enabled
            ch_config = {}
            for config_key in CHANNEL_TYPES.get(channel_name, {}).get('config_keys', []):
                ch_config[config_key] = self._config.get(f'{channel_name}.{config_key}', '')
            
            channel = create_channel(channel_name, ch_config)
            if channel:
                targets = {channel_name: channel}
            else:
                return {'success': False, 'error': f'Channel {channel_name} not configured'}
        
        # AI config for enhancement - use per-provider API key
        ai_provider = self._config.get('ai_provider', 'groq')
        ai_api_key = self._config.get(f'ai_api_key_{ai_provider}', '') or self._config.get('ai_api_key', '')
        ai_config = {
            'ai_enabled': self._config.get('ai_enabled', 'false'),
            'ai_provider': ai_provider,
            'ai_api_key': ai_api_key,
            'ai_model': self._config.get('ai_model', ''),
            'ai_language': self._config.get('ai_language', 'en'),
            'ai_ollama_url': self._config.get('ai_ollama_url', ''),
            # `ai_openai_base_url` was previously dropped from this dict and
            # the downstream `notification_templates.AIRewriter` read it from
            # the dict — meaning a user who configured LiteLLM / Azure as a
            # custom base_url passed the "Test AI" check (which DOES pass it)
            # but every real notification silently went to api.openai.com.
            # Privacy + UX deception bug. Audit Tier 3.2 #1.
            'ai_openai_base_url': self._config.get('ai_openai_base_url', ''),
            'ai_prompt_mode': self._config.get('ai_prompt_mode', 'default'),
            'ai_custom_prompt': self._config.get('ai_custom_prompt', ''),
        }
        
        ai_enabled = self._config.get('ai_enabled', 'false')
        if isinstance(ai_enabled, str):
            ai_enabled = ai_enabled.lower() == 'true'
        ai_language = self._config.get('ai_language', 'en')
        ai_prompt_mode = self._config.get('ai_prompt_mode', 'default')
        
        # Determine AI info string based on prompt mode
        if ai_prompt_mode == 'custom':
            ai_info = f'{ai_provider} / custom prompt'
        else:
            ai_info = f'{ai_provider} / {ai_language}'
        
        # ProxMenux logo for welcome message
        logo_url = 'https://proxmenux.com/telegram.png'
        logo_caption = 'You can use this image as the profile photo for your notification bot.'
        
        for ch_name, channel in targets.items():
            try:
                # Get per-channel settings
                detail_level_key = f'{ch_name}.ai_detail_level'
                detail_level = self._config.get(detail_level_key, 'standard')
                
                rich_key = f'{ch_name}.rich_format'
                use_rich_format = self._config.get(rich_key, 'false') == 'true'
                
                # Build status indicators for icons and AI, adapted to channel format
                if use_rich_format:
                    icon_status  = '✅ Icons: enabled'
                    ai_status    = f'✅ AI: enabled ({ai_info})' if ai_enabled else '❌ AI: disabled'
                else:
                    icon_status  = 'Icons: disabled'
                    ai_status    = f'AI: enabled ({ai_info})' if ai_enabled else 'AI: disabled'
                
                # Base test message — shows current channel config
                # NOTE: narrative lines are intentionally unlabeled so the AI
                # does not prepend "Message:" or other spurious field labels.
                base_title = 'ProxMenux Test'
                base_message = (
                    'Welcome to ProxMenux Monitor!\n\n'
                    'This is a test message to verify your notification channel is working correctly.\n\n'
                    'Channel configuration:\n'
                    f'{icon_status}\n'
                    f'{ai_status}\n\n'
                    'You will receive alerts about system events, health status changes, and security incidents.'
                )
                
                # Apply AI enhancement (translates to configured language)
                # Pass channel_type so AI knows whether to append original (email only)
                channel_ai_config = {**ai_config, 'channel_type': ch_name}
                ai_result = format_with_ai_full(
                    base_title, base_message, 'INFO', channel_ai_config,
                    detail_level=detail_level,
                    use_emojis=use_rich_format
                )
                enhanced_title = ai_result.get('title', base_title)
                enhanced_message = ai_result.get('body', base_message)
                
                # Send message
                send_result = channel.send(enhanced_title, enhanced_message, 'INFO')
                success = send_result.get('success', False)
                error = send_result.get('error', '')
                
                # For Telegram: send logo with caption suggesting it as bot profile photo
                if success and ch_name == 'telegram' and hasattr(channel, 'send_photo'):
                    # Translate caption if AI is active
                    if ai_enabled:
                        caption_result = format_with_ai_full(
                            '', logo_caption, 'INFO', channel_ai_config,
                            detail_level='brief', use_emojis=use_rich_format
                        )
                        caption = caption_result.get('body', logo_caption)
                    else:
                        caption = logo_caption
                    try:
                        channel.send_photo(logo_url, caption=caption)
                    except TypeError:
                        # Fallback if send_photo doesn't support caption parameter
                        channel.send_photo(logo_url)
                
                results[ch_name] = {'success': success, 'error': error}
                
                self._record_history(
                    'test', ch_name, enhanced_title,
                    enhanced_message[:500], 'INFO',
                    success, error, 'api'
                )
                
            except Exception as e:
                results[ch_name] = {'success': False, 'error': str(e)}
        
        overall_success = any(r['success'] for r in results.values())
        return {
            'success': overall_success,
            'results': results,
        }
    
    # ─── Proxmox Webhook ──────────────────────────────────────────
    
    def process_webhook(self, payload: dict) -> dict:
        """Process incoming Proxmox webhook. Delegates to ProxmoxHookWatcher."""
        if not self._hook_watcher:
            self._hook_watcher = ProxmoxHookWatcher(self._event_queue)
        return self._hook_watcher.process_webhook(payload)
    
    def get_webhook_secret(self) -> str:
        """Get configured webhook secret, or empty string if none."""
        if not self._config:
            self._load_config()
        return self._config.get('webhook_secret', '')
    
    def get_webhook_allowed_ips(self) -> list:
        """Get list of allowed IPs for webhook, or empty list (allow all)."""
        if not self._config:
            self._load_config()
        raw = self._config.get('webhook_allowed_ips', '')
        if not raw:
            return []
        return [ip.strip() for ip in str(raw).split(',') if ip.strip()]
    
    # ─── Status & Settings ──────────────────────────────────────
    
    def get_status(self) -> Dict[str, Any]:
        """Get current service status."""
        if not self._config:
            self._load_config()
        
        return {
            'enabled': self._enabled,
            'running': self._running,
            'channels': {
                name: {
                    'type': name,
                    'connected': True,
                }
                for name in self._channels
            },
            'stats': self._stats,
            'watchers': {
                'journal': self._journal_watcher is not None and self._running,
                'task': self._task_watcher is not None and self._running,
                'polling': self._polling_collector is not None and self._running,
            },
        }
    
    def set_enabled(self, enabled: bool) -> Dict[str, Any]:
        """Enable or disable the notification service."""
        self._save_setting('enabled', 'true' if enabled else 'false')
        self._enabled = enabled
        
        if enabled and not self._running:
            self.start()
        elif not enabled and self._running:
            self.stop()
        
        return {'success': True, 'enabled': enabled}
    
    def is_event_enabled(self, event_type: str) -> bool:
        """Check if a specific event type is enabled for notifications.
        
        Returns True if ANY active channel has this event enabled.
        Returns False only if ALL channels have explicitly disabled this event.
        Used by callers like health_polling_thread to skip notifications
        for disabled events.
        
        The UI stores toggles per-channel as '{channel}.event.{event_type}'.
        We check all configured channels - if any has it enabled, return True.
        """
        if not self._config:
            self._load_config()
        
        # Get template info for default state
        tmpl = TEMPLATES.get(event_type, {})
        default_enabled = 'true' if tmpl.get('default_enabled', True) else 'false'
        event_group = tmpl.get('group', 'other')
        
        # Check each configured channel. The list MUST come from CHANNEL_TYPES
        # (the canonical registry of channel implementations) — a hardcoded
        # list with `ntfy`/`pushover`/`slack` referenced channels that don't
        # exist as implementations, leaving events checked against `.enabled`
        # toggles that nobody could toggle. Audit Tier 6 (Notification stack #7).
        channel_types = list(CHANNEL_TYPES.keys())
        active_channels = []
        
        for ch_name in channel_types:
            if self._config.get(f'{ch_name}.enabled', 'false') == 'true':
                active_channels.append(ch_name)
        
        # If no channels are configured, consider events as "disabled"
        # (no point generating notifications with no destination)
        if not active_channels:
            return False
        
        # Check if ANY active channel has this event enabled
        for ch_name in active_channels:
            # First check category toggle for this channel
            ch_group_key = f'{ch_name}.events.{event_group}'
            if self._config.get(ch_group_key, 'true') == 'false':
                continue  # Category disabled for this channel
            
            # Then check event-specific toggle
            ch_event_key = f'{ch_name}.event.{event_type}'
            if self._config.get(ch_event_key, default_enabled) == 'true':
                return True  # At least one channel has it enabled
        
        # All active channels have this event disabled
        return False
    
    def list_channels(self) -> Dict[str, Any]:
        """List all channel types with their configuration status."""
        if not self._config:
            self._load_config()
        
        channels_info = {}
        for ch_type, info in CHANNEL_TYPES.items():
            enabled = self._config.get(f'{ch_type}.enabled', 'false') == 'true'
            configured = all(
                bool(self._config.get(f'{ch_type}.{k}', ''))
                for k in info['config_keys']
            )
            channels_info[ch_type] = {
                'name': info['name'],
                'enabled': enabled,
                'configured': configured,
                'active': ch_type in self._channels,
            }
        
        return {'channels': channels_info}
    
    def get_history(self, limit: int = 50, offset: int = 0,
                    severity: str = '', channel: str = '') -> Dict[str, Any]:
        """Get notification history with optional filters."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = 'SELECT * FROM notification_history WHERE 1=1'
            params: list = []
            
            if severity:
                query += ' AND severity = ?'
                params.append(severity)
            if channel:
                query += ' AND channel = ?'
                params.append(channel)
            
            query += ' ORDER BY sent_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            
            # Get total count
            count_query = 'SELECT COUNT(*) FROM notification_history WHERE 1=1'
            count_params: list = []
            if severity:
                count_query += ' AND severity = ?'
                count_params.append(severity)
            if channel:
                count_query += ' AND channel = ?'
                count_params.append(channel)
            
            cursor.execute(count_query, count_params)
            total = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'history': rows,
                'total': total,
                'limit': limit,
                'offset': offset,
            }
        except Exception as e:
            return {'history': [], 'total': 0, 'error': str(e)}
    
    def clear_history(self) -> Dict[str, Any]:
        """Clear all notification history."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute('DELETE FROM notification_history')
            conn.commit()
            conn.close()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_settings(self) -> Dict[str, Any]:
        """Get all notification settings for the UI.
        
        Returns a structure matching the frontend's NotificationConfig shape
        so the round-trip (GET -> edit -> POST) is seamless.
        """
        if not self._config:
            self._load_config()
        
        # Build nested channels object matching frontend ChannelConfig.
        # Any per-channel key that is also in SENSITIVE_KEYS (e.g. telegram.token,
        # email.password, discord.webhook_url) is masked with SENSITIVE_PLACEHOLDER
        # when populated — so the secret never leaves the server in cleartext just
        # because the UI loaded the settings page. The frontend treats the
        # placeholder as "unchanged" on save.
        channels = {}
        for ch_type, info in CHANNEL_TYPES.items():
            ch_cfg: Dict[str, Any] = {
                'enabled': self._config.get(f'{ch_type}.enabled', 'false') == 'true',
                'rich_format': self._config.get(f'{ch_type}.rich_format', 'false') == 'true',
                # Quiet Hours + Daily Digest live in the same per-channel
                # namespace but weren't being projected back to the UI —
                # the toggles round-tripped through POST but the GET only
                # returned `enabled`/`rich_format` plus channel-specific
                # config_keys, so after a reload the user saw the toggle
                # off even though the DB had it on. Reported on .1.10
                # along with the post-window delivery bug.
                'quiet_enabled': self._config.get(f'{ch_type}.quiet_enabled', 'false') == 'true',
                'quiet_start': self._config.get(f'{ch_type}.quiet_start', '22:00'),
                'quiet_end': self._config.get(f'{ch_type}.quiet_end', '06:00'),
                'digest_enabled': self._config.get(f'{ch_type}.digest_enabled', 'false') == 'true',
                'digest_time': self._config.get(f'{ch_type}.digest_time', '09:00'),
            }
            for config_key in info['config_keys']:
                full_key = f'{ch_type}.{config_key}'
                raw = self._config.get(full_key, '')
                if full_key in SENSITIVE_KEYS:
                    ch_cfg[config_key] = _mask_if_set(raw)
                else:
                    ch_cfg[config_key] = raw
            channels[ch_type] = ch_cfg
        
        # Build event_types_by_group for UI rendering
        event_types_by_group = get_event_types_by_group()
        
        # Build per-channel overrides
        # Each channel independently owns its category and event toggles.
        # Keys: {channel}.events.{group} and {channel}.event.{event_type}
        # Defaults: categories default to true, events default to template default_enabled.
        channel_overrides = {}
        for ch_type in CHANNEL_TYPES:
            ch_overrides = {'categories': {}, 'events': {}}
            for group_key in EVENT_GROUPS:
                saved = self._config.get(f'{ch_type}.events.{group_key}')
                ch_overrides['categories'][group_key] = (saved or 'true') == 'true'
            for event_type_key, tmpl in TEMPLATES.items():
                default = 'true' if tmpl.get('default_enabled', True) else 'false'
                saved = self._config.get(f'{ch_type}.event.{event_type_key}')
                ch_overrides['events'][event_type_key] = (saved or default) == 'true'
            channel_overrides[ch_type] = ch_overrides
        
        # Build AI detail levels per channel
        ai_detail_levels = {}
        for ch_type in CHANNEL_TYPES:
            ai_detail_levels[ch_type] = self._config.get(f'ai_detail_level_{ch_type}', 'standard')
        
        # Note: Model migration for deprecated models is handled by the periodic
        # verify_and_update_ai_model() check. Users now load models dynamically
        # from providers using the "Load" button in the UI.
        
        # Capture raw API key state before masking — needed for the legacy
        # migration check below, otherwise the mask placeholder would make
        # `not ai_api_keys[current_provider]` look populated and skip migration.
        current_provider = self._config.get('ai_provider', 'groq')
        _raw_keys = {
            'groq': self._config.get('ai_api_key_groq', ''),
            'gemini': self._config.get('ai_api_key_gemini', ''),
            'anthropic': self._config.get('ai_api_key_anthropic', ''),
            'openai': self._config.get('ai_api_key_openai', ''),
            'openrouter': self._config.get('ai_api_key_openrouter', ''),
        }
        ai_api_keys = {
            'groq': _mask_if_set(_raw_keys['groq']),
            'ollama': '',  # Ollama doesn't need API key
            'gemini': _mask_if_set(_raw_keys['gemini']),
            'anthropic': _mask_if_set(_raw_keys['anthropic']),
            'openai': _mask_if_set(_raw_keys['openai']),
            'openrouter': _mask_if_set(_raw_keys['openrouter']),
        }

        # Get per-provider selected models
        ai_models = {
            'groq': self._config.get('ai_model_groq', ''),
            'ollama': self._config.get('ai_model_ollama', ''),
            'gemini': self._config.get('ai_model_gemini', ''),
            'anthropic': self._config.get('ai_model_anthropic', ''),
            'openai': self._config.get('ai_model_openai', ''),
            'openrouter': self._config.get('ai_model_openrouter', ''),
        }

        # Migrate legacy ai_api_key to per-provider key if exists. Use the raw
        # (unmasked) key state so the check is accurate.
        legacy_api_key = self._config.get('ai_api_key', '')
        if legacy_api_key and not _raw_keys.get(current_provider, ''):
            # Migrate legacy key to current provider — but report it masked.
            ai_api_keys[current_provider] = SENSITIVE_PLACEHOLDER
            try:
                conn = sqlite3.connect(str(DB_PATH), timeout=10)
                cursor = conn.cursor()
                # Save migrated key
                migrated_key = encrypt_sensitive_value(legacy_api_key) if legacy_api_key else ''
                cursor.execute('''
                    INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                ''', (f'{SETTINGS_PREFIX}ai_api_key_{current_provider}', migrated_key, datetime.now().isoformat()))
                # Clear legacy key
                cursor.execute('''
                    DELETE FROM user_settings WHERE setting_key = ?
                ''', (f'{SETTINGS_PREFIX}ai_api_key',))
                conn.commit()
                conn.close()
                self._config[f'ai_api_key_{current_provider}'] = legacy_api_key
                del self._config['ai_api_key']
                print(f"[NotificationManager] Migrated legacy API key to {current_provider}")
            except Exception as e:
                print(f"[NotificationManager] Failed to migrate legacy API key: {e}")
        
        config = {
            'enabled': self._enabled,
            'channels': channels,
            'event_categories': {},
            'event_toggles': {},
            'event_types_by_group': event_types_by_group,
            'channel_overrides': channel_overrides,
            'ai_enabled': self._config.get('ai_enabled', 'false') == 'true',
            'ai_provider': current_provider,
            'ai_api_keys': ai_api_keys,
            'ai_models': ai_models,
            'ai_model': self._config.get('ai_model', ''),
            'ai_language': self._config.get('ai_language', 'en'),
            'ai_ollama_url': self._config.get('ai_ollama_url', 'http://localhost:11434'),
            'ai_openai_base_url': self._config.get('ai_openai_base_url', ''),
            'ai_prompt_mode': self._config.get('ai_prompt_mode', 'default'),
            'ai_custom_prompt': self._config.get('ai_custom_prompt', ''),
            'ai_allow_suggestions': self._config.get('ai_allow_suggestions', 'false') == 'true',
            'ai_detail_levels': ai_detail_levels,
            'hostname': self._config.get('hostname', ''),
            'webhook_secret': _mask_if_set(self._config.get('webhook_secret', '')),
            'webhook_allowed_ips': self._config.get('webhook_allowed_ips', ''),
            'pbs_host': self._config.get('pbs_host', ''),
            'pve_host': self._config.get('pve_host', ''),
            'pbs_trusted_sources': self._config.get('pbs_trusted_sources', ''),
        }
        
        return {
            'success': True,
            'config': config,
        }
    
    def save_settings(self, settings: Dict[str, str]) -> Dict[str, Any]:
        """Save multiple notification settings at once."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            for key, value in settings.items():
                # Accept both prefixed and unprefixed keys
                full_key = key if key.startswith(SETTINGS_PREFIX) else f'{SETTINGS_PREFIX}{key}'
                short_key = full_key[len(SETTINGS_PREFIX):]

                # Skip placeholder writes for sensitive fields. The UI receives a
                # masked placeholder for any populated secret on GET; if it sends
                # the placeholder back unchanged we must not overwrite the real
                # stored value. See audit Tier 2 #17c.
                if short_key in SENSITIVE_KEYS and str(value) == SENSITIVE_PLACEHOLDER:
                    continue

                # SSRF guard at the storage boundary. Without this an
                # attacker who reaches save_settings could persist a malicious
                # `ai_ollama_url` (e.g. file:///etc/shadow or http://127.0.0.1:8006)
                # and have it consumed silently in the dispatch path on every
                # subsequent notification — even without ever calling test-ai.
                # Audit Tier 3 #19.
                if short_key == 'ai_ollama_url' and str(value):
                    ok, err = validate_external_url(str(value), allow_loopback=True)
                    if not ok:
                        raise ValueError(f"Invalid ai_ollama_url: {err}")
                if short_key == 'ai_openai_base_url' and str(value):
                    ok, err = validate_external_url(str(value), allow_loopback=False)
                    if not ok:
                        raise ValueError(f"Invalid ai_openai_base_url: {err}")

                # Cap ai_custom_prompt to a sane size. Without this, a caller
                # who reaches save_settings can store a 10 MB prompt that gets
                # injected into every AI call: cost amplification, latency
                # blow-up, and easier prompt-injection by sheer volume. 8 KB
                # is plenty for any reasonable system prompt. Audit Tier 3.2 #3.
                if short_key == 'ai_custom_prompt' and isinstance(value, str) and len(value) > 8192:
                    raise ValueError("ai_custom_prompt exceeds 8 KB cap")

                # Whitelist enums that flow into AI prompt template variables
                # (detail_level controls instruction phrasing, ai_language picks
                # the response language). Without validation a soft prompt
                # injection lands in the system prompt verbatim. Audit Tier 3.2 #4.
                _ALLOWED_DETAIL_LEVELS = ('brief', 'standard', 'detailed')
                _ALLOWED_AI_LANGUAGES = (
                    'en', 'es', 'fr', 'de', 'it', 'pt', 'ru',
                    'ja', 'zh', 'ko', 'pl', 'nl', 'tr', 'ar',
                )
                if short_key.endswith('.ai_detail_level') or short_key == 'ai_detail_level':
                    if str(value) not in _ALLOWED_DETAIL_LEVELS:
                        raise ValueError(f"Invalid ai_detail_level: must be one of {_ALLOWED_DETAIL_LEVELS}")
                if short_key == 'ai_language':
                    if str(value) not in _ALLOWED_AI_LANGUAGES:
                        raise ValueError(f"Invalid ai_language: must be one of {_ALLOWED_AI_LANGUAGES}")

                # Encrypt sensitive values before storing. Skip if the value is
                # already in either encrypted form — `encrypt_sensitive_value`
                # is idempotent on its own input but the explicit check avoids
                # a wasted PBKDF2 derivation when round-tripping unchanged values.
                store_value = str(value)
                if (short_key in SENSITIVE_KEYS and store_value
                        and not store_value.startswith(_NEW_ENC_PREFIX)
                        and not store_value.startswith(_LEGACY_ENC_PREFIX)):
                    store_value = encrypt_sensitive_value(store_value)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                ''', (full_key, store_value, now))
                
                # Keep decrypted value in memory for runtime use
                self._config[short_key] = str(value)
                
                # If user is explicitly enabling an event that defaults to disabled,
                # mark it so _load_config reconciliation won't override it later.
                if short_key.startswith('event.') and str(value) == 'true':
                    event_type = short_key[6:]  # strip 'event.'
                    tmpl = TEMPLATES.get(event_type, {})
                    if not tmpl.get('default_enabled', True):
                        marker_key = f'{SETTINGS_PREFIX}event_explicit.{event_type}'
                        cursor.execute('''
                            INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at)
                            VALUES (?, ?, ?)
                        ''', (marker_key, 'true', now))
                        self._config[f'event_explicit.{event_type}'] = 'true'
            
            conn.commit()
            conn.close()
            
            # Rebuild channels with new config
            was_enabled = self._enabled
            self._enabled = self._config.get('enabled', 'false') == 'true'
            self._rebuild_channels()
            
            # Start/stop service and auto-configure PVE webhook
            pve_webhook_result = None
            if self._enabled and not was_enabled:
                # Notifications just got ENABLED -> start service + setup PVE webhook
                if not self._running:
                    self.start()
                try:
                    from flask_notification_routes import setup_pve_webhook_core
                    pve_webhook_result = setup_pve_webhook_core()
                except ImportError:
                    pass  # flask_notification_routes not available (CLI mode)
                except Exception as e:
                    pve_webhook_result = {'configured': False, 'error': str(e)}
            elif not self._enabled and was_enabled:
                # Notifications just got DISABLED -> stop service + cleanup PVE webhook
                if self._running:
                    self.stop()
                try:
                    from flask_notification_routes import cleanup_pve_webhook_core
                    cleanup_pve_webhook_core()
                except ImportError:
                    pass
                except Exception:
                    pass
            
            result = {'success': True, 'channels_active': list(self._channels.keys())}
            if pve_webhook_result:
                result['pve_webhook'] = pve_webhook_result
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}


    def verify_and_update_ai_model(self) -> Dict[str, Any]:
        """Verify current AI model is available, update if deprecated.
        
        This method checks if the configured AI model is still available
        from the provider. If not, it automatically migrates to the best
        available fallback model and notifies the administrator.
        
        Should be called periodically (e.g., every 24 hours) to catch
        model deprecations before they cause notification failures.
        
        Returns:
            Dict with:
                - checked: bool - whether check was performed
                - migrated: bool - whether model was changed
                - old_model: str - previous model (if migrated)
                - new_model: str - current/new model
                - message: str - status message
        """
        if self._config.get('ai_enabled', 'false') != 'true':
            return {'checked': False, 'migrated': False, 'message': 'AI not enabled'}
        
        provider_name = self._config.get('ai_provider', 'groq')
        current_model = self._config.get('ai_model', '')
        
        # Skip Ollama - user manages their own models
        if provider_name == 'ollama':
            return {'checked': False, 'migrated': False, 'message': 'Ollama models managed locally'}
        
        # Get the API key for this provider
        api_key = self._config.get(f'ai_api_key_{provider_name}', '') or self._config.get('ai_api_key', '')
        if not api_key:
            return {'checked': False, 'migrated': False, 'message': 'No API key configured'}
        
        try:
            # Load verified models from config
            verified_models = []
            recommended_model = ''
            try:
                # Try AppImage path first (scripts and config both in /usr/bin/)
                script_dir = Path(__file__).parent
                config_path = script_dir / 'config' / 'verified_ai_models.json'
                
                if not config_path.exists():
                    # Try development path (AppImage/scripts/ -> AppImage/config/)
                    config_path = script_dir.parent / 'config' / 'verified_ai_models.json'
                
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        verified_config = json.load(f)
                        provider_config = verified_config.get(provider_name, {})
                        verified_models = provider_config.get('models', [])
                        recommended_model = provider_config.get('recommended', '')
            except Exception as e:
                print(f"[NotificationManager] Failed to load verified models: {e}")
            
            from ai_providers import get_provider
            provider = get_provider(provider_name, api_key=api_key, model=current_model)
            
            if not provider:
                return {'checked': False, 'migrated': False, 'message': f'Unknown provider: {provider_name}'}
            
            # Get available models from API
            api_models = provider.list_models()
            
            # Combine: use verified models that are also in API (or all verified if API fails)
            if api_models and verified_models:
                available_models = [m for m in verified_models if m in api_models]
            elif verified_models:
                available_models = verified_models
            elif api_models:
                available_models = api_models
            else:
                return {'checked': True, 'migrated': False, 'message': 'Could not retrieve model list'}
            
            # Check if current model is available
            if current_model in available_models:
                return {
                    'checked': True,
                    'migrated': False,
                    'new_model': current_model,
                    'message': f'Model {current_model} is available'
                }
            
            # Model not available - use recommended or first available
            recommended = recommended_model if recommended_model in available_models else (available_models[0] if available_models else '')
            
            if not recommended or recommended == current_model:
                return {
                    'checked': True,
                    'migrated': False,
                    'new_model': current_model,
                    'message': f'Model {current_model} not in list but no alternative found'
                }
            
            # Migrate to new model
            old_model = current_model
            try:
                conn = sqlite3.connect(str(DB_PATH), timeout=10)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO user_settings (setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                ''', (f'{SETTINGS_PREFIX}ai_model', recommended, datetime.now().isoformat()))
                conn.commit()
                conn.close()
                self._config['ai_model'] = recommended
                
                print(f"[NotificationManager] AI model migrated: {old_model} -> {recommended}")
                
                return {
                    'checked': True,
                    'migrated': True,
                    'old_model': old_model,
                    'new_model': recommended,
                    'message': f'Model migrated from {old_model} to {recommended}'
                }
            except Exception as e:
                return {
                    'checked': True,
                    'migrated': False,
                    'message': f'Failed to save new model: {e}'
                }
                
        except Exception as e:
            print(f"[NotificationManager] Model verification failed: {e}")
            return {'checked': False, 'migrated': False, 'message': str(e)}


# ─── Singleton (for server mode) ─────────────────────────────────

notification_manager = NotificationManager()


# ─── CLI Interface ────────────────────────────────────────────────

def _print_result(result: Dict, as_json: bool):
    """Print CLI result in human-readable or JSON format."""
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    
    if result.get('success'):
        print(f"OK: ", end='')
    elif 'success' in result and not result['success']:
        print(f"ERROR: ", end='')
    
    # Format based on content
    if 'channels_sent' in result:
        sent = result.get('channels_sent', [])
        print(f"Sent via: {', '.join(sent) if sent else 'none'}")
        if result.get('errors'):
            for err in result['errors']:
                print(f"  Error: {err}")
    elif 'results' in result:
        for ch, r in result['results'].items():
            status = 'OK' if r['success'] else f"FAILED: {r['error']}"
            print(f"  {ch}: {status}")
    elif 'channels' in result:
        for ch, info in result['channels'].items():
            status = 'active' if info.get('active') else ('configured' if info.get('configured') else 'not configured')
            enabled = 'enabled' if info.get('enabled') else 'disabled'
            print(f"  {info['name']}: {enabled}, {status}")
    elif 'enabled' in result and 'running' in result:
        print(f"Enabled: {result['enabled']}, Running: {result['running']}")
        if result.get('stats'):
            stats = result['stats']
            print(f"  Total sent: {stats.get('total_sent', 0)}")
            print(f"  Total errors: {stats.get('total_errors', 0)}")
            if stats.get('last_sent_at'):
                print(f"  Last sent: {stats['last_sent_at']}")
    elif 'enabled' in result:
        print(f"Service {'enabled' if result['enabled'] else 'disabled'}")
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ProxMenux Notification Manager CLI',
        epilog='Example: python3 notification_manager.py --action send --type vm_fail --severity CRITICAL --title "VM 100 failed" --message "QEMU process crashed"'
    )
    parser.add_argument('--action', required=True,
                        choices=['send', 'send-raw', 'test', 'status',
                                 'enable', 'disable', 'list-channels'],
                        help='Action to perform')
    parser.add_argument('--type', help='Event type for send action (e.g. vm_fail, backup_complete)')
    parser.add_argument('--severity', default='INFO',
                        choices=['INFO', 'WARNING', 'CRITICAL'],
                        help='Notification severity (default: INFO)')
    parser.add_argument('--title', help='Notification title')
    parser.add_argument('--message', help='Notification message body')
    parser.add_argument('--channel', default='all',
                        help='Specific channel for test (default: all)')
    parser.add_argument('--json', action='store_true',
                        help='Output result as JSON')
    
    args = parser.parse_args()
    
    mgr = NotificationManager()
    mgr._load_config()
    
    if args.action == 'send':
        if not args.type:
            parser.error('--type is required for send action')
        result = mgr.send_notification(
            args.type, args.severity,
            args.title or '', args.message or '',
            data={
                'hostname': _resolve_display_hostname(mgr._config),
                'reason': args.message or '',
            },
            source='cli'
        )
    
    elif args.action == 'send-raw':
        if not args.title or not args.message:
            parser.error('--title and --message are required for send-raw')
        result = mgr.send_raw(args.title, args.message, args.severity, source='cli')
    
    elif args.action == 'test':
        result = mgr.test_channel(args.channel)
    
    elif args.action == 'status':
        result = mgr.get_status()
    
    elif args.action == 'enable':
        result = mgr.set_enabled(True)
    
    elif args.action == 'disable':
        result = mgr.set_enabled(False)
    
    elif args.action == 'list-channels':
        result = mgr.list_channels()
    
    else:
        result = {'error': f'Unknown action: {args.action}'}
    
    _print_result(result, args.json)
    
    # Exit with appropriate code
    sys.exit(0 if result.get('success', True) else 1)
