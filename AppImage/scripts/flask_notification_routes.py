"""
Flask routes for notification service configuration and management.
Blueprint pattern matching flask_health_routes.py / flask_security_routes.py.
"""

import hmac
import time
import json
import hashlib
from pathlib import Path
from collections import deque
from flask import Blueprint, jsonify, request
from notification_manager import notification_manager, SENSITIVE_PLACEHOLDER, validate_external_url
from jwt_middleware import require_auth


def _resolve_masked_api_key(provider, api_key):
    """If the UI sent the masked placeholder back, fall back to the stored key.

    The settings endpoint masks sensitive values on GET (audit Tier 2 #17c).
    For test-ai and provider-models we want the user to be able to "Test"
    without re-entering the key — so when we see the placeholder we look up
    the real stored key by provider name. Returns the resolved key or the
    original input if no substitution is needed.
    """
    if api_key != SENSITIVE_PLACEHOLDER:
        return api_key
    try:
        if not notification_manager._config:
            notification_manager._load_config()
        return notification_manager._config.get(f'ai_api_key_{provider}', '') or ''
    except Exception:
        return ''


# ─── Webhook Hardening Helpers ───────────────────────────────────

class WebhookRateLimiter:
    """Per-IP sliding-window rate limiter for the webhook endpoint.

    Was a single global bucket, which let one noisy/abusive caller fill it
    and starve legitimate PVE webhooks. Each remote IP now gets its own
    deque; total tracked IPs is capped to avoid memory growth from
    drive-by random-IP probing. Thread-safe — Flask routes run in worker
    threads.
    """

    _MAX_IPS = 1024

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        import threading as _threading
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict = {}
        self._lock = _threading.Lock()

    def allow(self, ip: str = '') -> bool:
        key = ip or '_unknown'
        now = time.time()
        with self._lock:
            # Drop the LRU IP (longest-idle bucket) before exceeding the cap.
            if key not in self._buckets and len(self._buckets) >= self._MAX_IPS:
                stale = min(
                    self._buckets,
                    key=lambda k: self._buckets[k][-1] if self._buckets[k] else 0
                )
                self._buckets.pop(stale, None)
            bucket = self._buckets.setdefault(key, deque())
            while bucket and now - bucket[0] > self._window:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True


class ReplayCache:
    """Replay-detection cache backed by SQLite.

    The previous in-memory `OrderedDict` was per-process: when Flask
    runs with multiple worker processes (gunicorn -w N) each worker
    keeps its own table, so the same signed body can be replayed N
    times before any one worker has seen it. Persisting to SQLite
    shares state across workers (and survives reloads). The
    `OrderedDict` is kept as an in-memory fast path for hot dedup
    within a single request burst — we still hit the DB to be sure.
    Audit Tier 3.1 — Replay cache per-process.
    """

    _MAX_SIZE = 2000  # In-memory hot-path cap

    def __init__(self, ttl: int = 60, db_path: str = '/usr/local/share/proxmenux/health_monitor.db'):
        from collections import OrderedDict as _OrderedDict
        import threading as _threading_rc
        self._ttl = ttl
        self._db_path = db_path
        self._seen: _OrderedDict = _OrderedDict()
        self._lock = _threading_rc.Lock()
        self._init_db()

    def _init_db(self):
        try:
            import sqlite3 as _sqlite
            from pathlib import Path as _Path
            _Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = _sqlite.connect(self._db_path, timeout=5)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS webhook_replay_cache (
                    signature TEXT PRIMARY KEY,
                    seen_ts REAL NOT NULL
                )
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ReplayCache] DB init failed: {e}")

    def check_and_record(self, signature: str) -> bool:
        """Return True if this signature was already seen (replay). Records it otherwise."""
        now = time.time()
        cutoff = now - self._ttl

        # In-memory fast path (lock-protected).
        with self._lock:
            while self._seen:
                oldest_key = next(iter(self._seen))
                if self._seen[oldest_key] > cutoff:
                    break
                self._seen.popitem(last=False)
            if signature in self._seen and now - self._seen[signature] < self._ttl:
                return True
            # Tentatively reserve in memory; if DB confirms we're first,
            # this stands. Hard cap defends against runaway growth.
            self._seen[signature] = now
            while len(self._seen) > self._MAX_SIZE:
                self._seen.popitem(last=False)

        # Cross-worker check via SQLite. If another worker already
        # recorded the signature within the TTL window, treat as replay.
        try:
            import sqlite3 as _sqlite
            conn = _sqlite.connect(self._db_path, timeout=2)
            cur = conn.cursor()
            # Opportunistic cleanup of stale rows.
            cur.execute('DELETE FROM webhook_replay_cache WHERE seen_ts < ?', (cutoff,))
            cur.execute(
                'SELECT seen_ts FROM webhook_replay_cache WHERE signature = ?',
                (signature,),
            )
            row = cur.fetchone()
            if row and now - row[0] < self._ttl:
                conn.commit()
                conn.close()
                return True
            cur.execute(
                'INSERT OR REPLACE INTO webhook_replay_cache (signature, seen_ts) VALUES (?, ?)',
                (signature, now),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            # If the DB is unavailable, the in-memory check above still
            # catches replays within a single worker — log and continue.
            print(f"[ReplayCache] DB check failed (in-memory only): {e}")
        return False


# Module-level singletons (one per process)
_webhook_limiter = WebhookRateLimiter(max_requests=60, window_seconds=60)
_replay_cache = ReplayCache(ttl=60)

# Timestamp validation window (seconds)
_TIMESTAMP_MAX_DRIFT = 60

# ─── Input validation whitelists ──────────────────────────────────
# Used by the mutating routes (test, send) and the history filter.
# `severity` is small enough to whitelist; `channel` mirrors
# `notification_channels.CHANNEL_TYPES` plus 'all' for test_channel.
# `event_type` is bounded by length + charset rather than enumerated —
# the catalogue has 70+ entries and `render_template` already handles
# unknown event types via a fallback. Audit Tier 3.1 — sin validación
# de event_type/severity/channel en rutas mutantes.
_VALID_SEVERITIES = {'info', 'warning', 'critical', 'error', 'INFO', 'WARNING', 'CRITICAL', 'ERROR'}
_VALID_CHANNELS = {'all', 'telegram', 'gotify', 'discord', 'email'}
import re as _re_validate
_EVENT_TYPE_RE = _re_validate.compile(r'^[a-zA-Z0-9_]{1,64}$')


def _bad_request(msg: str):
    return jsonify({'error': msg}), 400


def _is_loopback_addr(value: str) -> bool:
    """Return True for IPv4, IPv6 and IPv4-mapped loopback addresses.

    When Flask is bound to ``::`` for dual-stack support, an HTTP request
    sent to ``127.0.0.1`` can be reported as ``::ffff:127.0.0.1``. Treat it
    as local so the PVE webhook keeps the intended localhost trust path.
    """
    try:
        import ipaddress
        addr = ipaddress.ip_address(value)
        if addr.is_loopback:
            return True
        ipv4_mapped = getattr(addr, 'ipv4_mapped', None)
        return bool(ipv4_mapped and ipv4_mapped.is_loopback)
    except ValueError:
        return value == 'localhost'


def _validate_event_type(value: str) -> bool:
    return isinstance(value, str) and bool(_EVENT_TYPE_RE.match(value))


def _validate_severity(value: str, allow_empty: bool = False) -> bool:
    if allow_empty and value == '':
        return True
    return value in _VALID_SEVERITIES


def _validate_channel(value: str, allow_empty: bool = False) -> bool:
    if allow_empty and value == '':
        return True
    return value in _VALID_CHANNELS

notification_bp = Blueprint('notifications', __name__)


@notification_bp.route('/api/notifications/settings', methods=['GET'])
@require_auth
def get_notification_settings():
    """Get all notification settings for the UI."""
    try:
        settings = notification_manager.get_settings()
        return jsonify(settings)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


@notification_bp.route('/api/notifications/settings', methods=['POST'])
@require_auth
def save_notification_settings():
    """Save notification settings from the UI."""
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({'error': 'No data provided'}), 400
        
        result = notification_manager.save_settings(payload)
        return jsonify(result)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


@notification_bp.route('/api/notifications/test', methods=['POST'])
@require_auth
def test_notification():
    """Send a test notification to one or all channels."""
    try:
        data = request.get_json() or {}
        channel = data.get('channel', 'all')

        if not _validate_channel(channel):
            return _bad_request('Invalid channel')

        result = notification_manager.test_channel(channel)
        return jsonify(result)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


def load_verified_models():
    """Load verified models from config file.
    
    Checks multiple paths:
    1. Same directory as script (AppImage: /usr/bin/config/)
    2. Parent directory config folder (dev: AppImage/config/)
    """
    try:
        # Try AppImage path first (scripts and config both in /usr/bin/)
        script_dir = Path(__file__).parent
        config_path = script_dir / 'config' / 'verified_ai_models.json'
        
        if not config_path.exists():
            # Try development path (AppImage/scripts/ -> AppImage/config/)
            config_path = script_dir.parent / 'config' / 'verified_ai_models.json'
        
        if config_path.exists():
            with open(config_path, 'r') as f:
                return json.load(f)
        else:
            print(f"[flask_notification_routes] Config not found at {config_path}")
    except Exception as e:
        print(f"[flask_notification_routes] Failed to load verified models: {e}")
    return {}


@notification_bp.route('/api/notifications/provider-models', methods=['POST'])
@require_auth
def get_provider_models():
    """Fetch available models from AI provider, filtered by verified models list.
    
    Only returns models that:
    1. Are available from the provider's API
    2. Are in our verified_ai_models.json list (tested to work)
    
    Request body:
        {
            "provider": "gemini|groq|openai|openrouter|ollama|anthropic",
            "api_key": "your-api-key",  // Not needed for ollama
            "ollama_url": "http://localhost:11434",  // Only for ollama
            "openai_base_url": "https://custom.endpoint/v1"  // Optional for openai
        }
    
    Returns:
        {
            "success": true/false,
            "models": ["model1", "model2", ...],
            "recommended": "recommended-model",
            "message": "status message"
        }
    """
    try:
        data = request.get_json() or {}
        provider = data.get('provider', '')
        api_key = _resolve_masked_api_key(provider, data.get('api_key', ''))
        ollama_url = data.get('ollama_url', 'http://localhost:11434')
        openai_base_url = data.get('openai_base_url', '')

        if not provider:
            return jsonify({'success': False, 'models': [], 'message': 'Provider not specified'})

        # SSRF guard before we touch the URL. Ollama is local-by-design so
        # loopback is allowed there; OpenAI base URL must be a real external
        # endpoint so loopback / RFC1918 are blocked.
        if provider == 'ollama':
            ok, err = validate_external_url(ollama_url, allow_loopback=True)
            if not ok:
                return jsonify({'success': False, 'models': [], 'message': f'Invalid ollama_url: {err}'}), 400
        if provider == 'openai' and openai_base_url:
            ok, err = validate_external_url(openai_base_url, allow_loopback=False)
            if not ok:
                return jsonify({'success': False, 'models': [], 'message': f'Invalid openai_base_url: {err}'}), 400
        
        # Load verified models config
        verified_config = load_verified_models()
        provider_config = verified_config.get(provider, {})
        verified_models = set(provider_config.get('models', []))
        recommended = provider_config.get('recommended', '')
        
        # Handle Ollama separately (local, no filtering)
        if provider == 'ollama':
            import urllib.request
            import urllib.error
            
            url = f"{ollama_url.rstrip('/')}/api/tags"
            req = urllib.request.Request(url, method='GET')
            req.add_header('User-Agent', 'ProxMenux-Monitor/1.1')
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                models = [m.get('name', '') for m in result.get('models', []) if m.get('name')]
                models = sorted(models)
                return jsonify({
                    'success': True,
                    'models': models,
                    'recommended': models[0] if models else '',
                    'message': f'Found {len(models)} local models'
                })
        
        # Handle Anthropic - no models list API, return verified models directly
        if provider == 'anthropic':
            models = list(verified_models) if verified_models else [
                'claude-3-5-haiku-latest',
                'claude-3-5-sonnet-latest',
                'claude-3-opus-latest',
            ]
            return jsonify({
                'success': True,
                'models': sorted(models),
                'recommended': recommended or models[0],
                'message': f'{len(models)} verified models'
            })
        
        # For other providers, fetch from API and filter by verified list.
        # Custom OpenAI-compatible endpoints (LiteLLM, opencode.ai, vLLM,
        # LocalAI…) often expose `/v1/models` without authentication, so
        # we only require an api_key when there's no custom base URL to
        # consult. Issue #11.5 — OpenCode provider Custom Base URL fetch.
        if not api_key and not (provider == 'openai' and openai_base_url):
            return jsonify({'success': False, 'models': [], 'message': 'API key required'})
        
        from ai_providers import get_provider
        ai_provider = get_provider(
            provider, 
            api_key=api_key, 
            model='', 
            base_url=openai_base_url if provider == 'openai' else None
        )
        
        if not ai_provider:
            return jsonify({'success': False, 'models': [], 'message': f'Unknown provider: {provider}'})
        
        # Get all models from provider API
        api_models = ai_provider.list_models()

        # OpenAI with a custom base URL means an OpenAI-compatible endpoint
        # (LiteLLM, MLX, LM Studio, vLLM, LocalAI, Ollama-proxy...). The
        # verified_ai_models.json list only contains official OpenAI IDs
        # (gpt-4o-mini etc.), so intersecting against it would strip every
        # model the user actually serves. Treat the custom-endpoint case
        # like Ollama: return whatever the endpoint advertises, no filter.
        is_openai_compat = (provider == 'openai' and bool(openai_base_url))

        if not api_models:
            # API failed, fall back to verified list only (but not for
            # custom endpoints — we don't know what the endpoint serves,
            # so "gpt-4o-mini" as a fallback would be misleading).
            if verified_models and not is_openai_compat:
                models = sorted(verified_models)
                return jsonify({
                    'success': True,
                    'models': models,
                    'recommended': recommended or models[0],
                    'message': f'{len(models)} verified models (API unavailable)'
                })
            return jsonify({
                'success': False,
                'models': [],
                'message': 'Could not retrieve models. Check your API key and endpoint URL.'
            })

        if is_openai_compat:
            # Custom OpenAI-compatible endpoint: surface every model the
            # endpoint reports. No verified-list intersection.
            models = sorted(api_models)
            return jsonify({
                'success': True,
                'models': models,
                'recommended': models[0] if models else '',
                'message': f'Found {len(models)} models on custom endpoint'
            })

        # Filter: only models that are BOTH in API and verified list
        if verified_models:
            api_models_set = set(api_models)
            filtered_models = [m for m in verified_models if m in api_models_set]

            if not filtered_models:
                # No intersection - maybe verified list is outdated
                # Return verified list anyway (will fail on use if truly unavailable)
                filtered_models = list(verified_models)

            # Sort with recommended first
            def sort_key(m):
                if m == recommended:
                    return (0, m)
                return (1, m)

            models = sorted(filtered_models, key=sort_key)
        else:
            # No verified list for this provider, return all from API
            models = sorted(api_models)
        
        return jsonify({
            'success': True,
            'models': models,
            'recommended': recommended if recommended in models else (models[0] if models else ''),
            'message': f'{len(models)} verified models available'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'models': [],
            'message': f'Error: {str(e)}'
        })


@notification_bp.route('/api/notifications/test-ai', methods=['POST'])
@require_auth
def test_ai_connection():
    """Test AI provider connection and configuration.
    
    Request body:
        {
            "provider": "groq" | "openai" | "anthropic" | "gemini" | "ollama" | "openrouter",
            "api_key": "...",
            "model": "..." (optional),
            "ollama_url": "http://localhost:11434" (optional, for ollama)
        }
    
    Returns:
        {
            "success": true/false,
            "message": "Connection successful" or error message,
            "model": "model used for test"
        }
    """
    try:
        data = request.get_json() or {}

        provider = data.get('provider', 'groq')
        api_key = _resolve_masked_api_key(provider, data.get('api_key', ''))
        model = data.get('model', '')
        ollama_url = data.get('ollama_url', 'http://localhost:11434')
        openai_base_url = data.get('openai_base_url', '')

        # Provider whitelist + bounds. Without these `provider` flows into
        # `get_provider()` (importable name), `api_key` into HTTP headers
        # (could be megabytes), and `model` into the path of paid LLM
        # requests. Audit Tier 3.1 — `test-ai` validation gap.
        _ALLOWED_PROVIDERS = {'groq', 'openai', 'anthropic', 'gemini', 'ollama', 'openrouter'}
        if provider not in _ALLOWED_PROVIDERS:
            return jsonify({'success': False, 'message': 'Unsupported provider', 'model': ''}), 400
        if not isinstance(api_key, str) or len(api_key) > 512:
            return jsonify({'success': False, 'message': 'api_key too long (max 512 chars)', 'model': ''}), 400
        if not isinstance(model, str) or len(model) > 128:
            return jsonify({'success': False, 'message': 'model too long (max 128 chars)', 'model': ''}), 400

        # Validate required fields
        if provider != 'ollama' and not api_key:
            return jsonify({
                'success': False,
                'message': 'API key is required',
                'model': ''
            }), 400

        # SSRF guard — same policy as provider-models.
        if provider == 'ollama':
            ok, err = validate_external_url(ollama_url, allow_loopback=True)
            if not ok:
                return jsonify({'success': False, 'message': f'Invalid ollama_url: {err}', 'model': ''}), 400
        if provider == 'openai' and openai_base_url:
            ok, err = validate_external_url(openai_base_url, allow_loopback=False)
            if not ok:
                return jsonify({'success': False, 'message': f'Invalid openai_base_url: {err}', 'model': ''}), 400

        if provider == 'ollama' and not ollama_url:
            return jsonify({
                'success': False,
                'message': 'Ollama URL is required',
                'model': ''
            }), 400
        
        # Import and use the AI providers module
        import sys
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        
        from ai_providers import get_provider, AIProviderError
        
        # Determine base_url based on provider
        if provider == 'ollama':
            base_url = ollama_url
        elif provider == 'openai':
            base_url = openai_base_url  # Empty string means use default OpenAI API
        else:
            base_url = ''
        
        try:
            ai_provider = get_provider(
                provider,
                api_key=api_key,
                model=model,
                base_url=base_url
            )
            
            result = ai_provider.test_connection()
            return jsonify(result)
            
        except AIProviderError as e:
            return jsonify({
                'success': False,
                'message': str(e),
                'model': model
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}',
            'model': ''
        }), 500


@notification_bp.route('/api/notifications/status', methods=['GET'])
@require_auth
def get_notification_status():
    """Get notification service status."""
    try:
        status = notification_manager.get_status()
        return jsonify(status)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


@notification_bp.route('/api/notifications/history', methods=['GET'])
@require_auth
def get_notification_history():
    """Get notification history with optional filters.

    `limit` is capped at 500 to prevent memory blow-up. The audit (Tier 3.1)
    flagged that without a cap, an authenticated client could request
    `?limit=1000000` and force the manager to load the entire history table
    into RAM and serialize it to JSON. Audit Tier 3.1 #5.
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        severity = request.args.get('severity', '')
        channel = request.args.get('channel', '')

        # Sane bounds — clamp instead of erroring so well-behaved clients
        # asking for "all" just get a reasonable page.
        if limit is None or limit < 1:
            limit = 100
        if limit > 500:
            limit = 500
        if offset is None or offset < 0:
            offset = 0

        # Filter strings: whitelist or empty. Without this an attacker who
        # finds a downstream sink that interpolates these (template,
        # filename, log) gets a free string-injection vector.
        if not _validate_severity(severity, allow_empty=True):
            return _bad_request('Invalid severity filter')
        if not _validate_channel(channel, allow_empty=True):
            return _bad_request('Invalid channel filter')

        result = notification_manager.get_history(limit, offset, severity, channel)
        return jsonify(result)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


@notification_bp.route('/api/notifications/history', methods=['DELETE'])
@require_auth
def clear_notification_history():
    """Clear all notification history."""
    try:
        result = notification_manager.clear_history()
        return jsonify(result)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


@notification_bp.route('/api/notifications/send', methods=['POST'])
@require_auth
def send_notification():
    """Send a notification via API (for testing or external triggers)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        event_type = data.get('event_type', 'custom')
        severity = data.get('severity', 'INFO')
        if not _validate_event_type(event_type):
            return _bad_request('Invalid event_type (alphanumeric/underscore, 1-64 chars)')
        if not _validate_severity(severity):
            return _bad_request('Invalid severity')

        result = notification_manager.send_notification(
            event_type=event_type,
            severity=severity,
            title=data.get('title', ''),
            message=data.get('message', ''),
            data=data.get('data', {}),
            source='api'
        )
        return jsonify(result)
    except Exception as e:
        # Sanitize: include only the exception type, never the message,
        # which can leak filesystem paths, internal class names and (in
        # AI provider errors) reflected user prompts. Audit Tier 3.1 #7.
        print(f"[notification_routes] {request.path} failed: {type(e).__name__}: {e}")
        return jsonify({'error': f'Internal error ({type(e).__name__})'}), 500


# ── PVE config constants ──
_PVE_ENDPOINT_ID = 'proxmenux-webhook'
_PVE_MATCHER_ID = 'proxmenux-default'
_PVE_NOTIFICATIONS_CFG = '/etc/pve/notifications.cfg'
_PVE_PRIV_CFG = '/etc/pve/priv/notifications.cfg'
_PVE_OUR_HEADERS = {
    f'webhook: {_PVE_ENDPOINT_ID}',
    f'matcher: {_PVE_MATCHER_ID}',
}


def _pve_webhook_url() -> str:
    """Return http:// or https:// based on the current SSL config.

    Hardcoded `http://...` previously broke webhook delivery whenever the
    user enabled SSL — Flask only listened on HTTPS, so PVE got connection
    refused and notifications stopped. Issue #194. PVE may still need
    `update-ca-certificates` if the cert is self-signed; that's a doc
    step on the user side.
    """
    try:
        from auth_manager import load_ssl_config
        cfg = load_ssl_config() or {}
        if cfg.get('enabled'):
            return 'https://127.0.0.1:8008/api/notifications/webhook'
    except Exception:
        pass
    return 'http://127.0.0.1:8008/api/notifications/webhook'


# Backward-compat alias for callers that read this at import time. Most
# call sites now use `_pve_webhook_url()` to pick up SSL state at write
# time. This constant reflects the state at module-load only.
_PVE_WEBHOOK_URL = _pve_webhook_url()


def _pve_read_file(path):
    """Read file, return (content, error). Content is '' if missing."""
    try:
        with open(path, 'r') as f:
            return f.read(), None
    except FileNotFoundError:
        return '', None
    except PermissionError:
        return None, f'Permission denied reading {path}'
    except Exception as e:
        return None, str(e)


def _pve_backup_file(path):
    """Create timestamped backup if file exists. Never fails fatally."""
    import os, shutil
    from datetime import datetime
    try:
        if os.path.exists(path):
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup = f"{path}.proxmenux_backup_{ts}"
            shutil.copy2(path, backup)
    except Exception:
        pass


# Recognised PVE notifications.cfg header keywords. A header line begins
# unindented with `<keyword>:` and the value names the entry. Anything
# that doesn't match this regex is not treated as a header — that fixes
# the previous parser which any unindented line with `:` (a third-party
# `description: foo: bar` continuation, a comment with `:` in it, etc.)
# could trigger as a header and corrupt user content. Audit Tier 3.1 —
# `_pve_remove_our_blocks` parser frágil.
import re as _re_pve_cfg
_PVE_HEADER_RE = _re_pve_cfg.compile(
    r'^(?P<kw>webhook|matcher|gotify|smtp|sendmail|ntfy):\s*(?P<name>[A-Za-z0-9_.\-]+)\s*$'
)


def _pve_remove_our_blocks(text, headers_to_remove):
    """Remove only blocks whose header line matches one of ours.

    Preserves ALL other content byte-for-byte.
    A block = header line + indented continuation lines + trailing blank line.
    """
    lines = text.splitlines(keepends=True)
    cleaned = []
    skip_block = False

    for line in lines:
        stripped = line.strip()
        is_header = (
            bool(stripped)
            and not line[0:1].isspace()
            and bool(_PVE_HEADER_RE.match(stripped))
        )

        if is_header:
            if stripped in headers_to_remove:
                skip_block = True
                continue
            else:
                skip_block = False

        if skip_block:
            if not stripped:
                # Blank line ends our block; consume it so we don't leave
                # a double blank gap in the output.
                skip_block = False
                continue
            if line[0:1].isspace():
                # Indented continuation line of the block we're removing.
                continue
            # Non-blank, unindented, but not recognised as a header by
            # the regex — leave the next iteration to figure it out.
            skip_block = False

        cleaned.append(line)

    return ''.join(cleaned)


def _build_webhook_fallback():
    """Build fallback manual commands for webhook setup."""
    import base64
    body_tpl = '{"title":"{{ escape title }}","message":"{{ escape message }}","severity":"{{ severity }}","timestamp":"{{ timestamp }}","fields":{{ json fields }}}'
    body_b64 = base64.b64encode(body_tpl.encode()).decode()
    return [
        "# 1. Append to END of /etc/pve/notifications.cfg",
        "#    (do NOT delete existing content):",
        "",
        f"webhook: {_PVE_ENDPOINT_ID}",
        f"\tbody {body_b64}",
        f"\tmethod post",
        f"\turl {_pve_webhook_url()}",
        "",
        f"matcher: {_PVE_MATCHER_ID}",
        f"\ttarget {_PVE_ENDPOINT_ID}",
        "\tmode all",
        "",
        "# 2. Append to /etc/pve/priv/notifications.cfg :",
        f"webhook: {_PVE_ENDPOINT_ID}",
    ]


def _is_proxmenux_webhook_registered() -> bool:
    """Cheap check: is our webhook block currently present in
    /etc/pve/notifications.cfg? Used by `refresh_pve_webhook_url_if_registered`
    to avoid auto-registering a webhook for users who never enabled
    notifications."""
    try:
        text, err = _pve_read_file(_PVE_NOTIFICATIONS_CFG)
        if err or not text:
            return False
        # Match the block header line as a whole word boundary so we
        # don't false-positive on a substring inside another endpoint's
        # config.
        return f'webhook: {_PVE_ENDPOINT_ID}' in text
    except Exception:
        return False


def refresh_pve_webhook_url_if_registered() -> dict:
    """Re-register the webhook block in PVE notifications.cfg with the
    URL scheme that matches the *current* SSL config.

    Called from the SSL configure/disable routes so a user toggling
    SSL while notifications are already set up doesn't end up with a
    stale `http://` (or `https://`) URL in PVE that PVE then can't
    reach. Idempotent and safe to call when nothing is registered —
    in that case it returns `{'configured': False, 'skipped': True}`
    without touching the cfg.

    Returns the same shape as `setup_pve_webhook_core` plus an
    optional `skipped` flag.
    """
    if not _is_proxmenux_webhook_registered():
        return {
            'configured': False,
            'skipped': True,
            'reason': 'no proxmenux webhook currently registered in PVE',
        }
    return setup_pve_webhook_core()


def setup_pve_webhook_core() -> dict:
    """Core logic to configure PVE webhook. Callable from anywhere.
    
    Returns dict with 'configured', 'error', 'fallback_commands' keys.
    Idempotent: safe to call multiple times.
    """
    import secrets as secrets_mod
    
    result = {
        'configured': False,
        'endpoint_id': _PVE_ENDPOINT_ID,
        'matcher_id': _PVE_MATCHER_ID,
        'url': _pve_webhook_url(),
        'fallback_commands': [],
        'error': None,
    }
    
    try:
        # ── Step 1: Ensure webhook secret exists (for our own internal use) ──
        secret = notification_manager.get_webhook_secret()
        if not secret:
            secret = secrets_mod.token_urlsafe(32)
            notification_manager._save_setting('webhook_secret', secret)
        
        # ── Step 2: Read main config ──
        cfg_text, err = _pve_read_file(_PVE_NOTIFICATIONS_CFG)
        if err:
            result['error'] = err
            result['fallback_commands'] = _build_webhook_fallback()
            return result
        
        # ── Step 3: Read priv config (to clean up any broken blocks we wrote before) ──
        priv_text, err = _pve_read_file(_PVE_PRIV_CFG)
        if err:
            priv_text = None
        
        # ── Step 4: Create backups before ANY modification ──
        _pve_backup_file(_PVE_NOTIFICATIONS_CFG)
        if priv_text is not None:
            _pve_backup_file(_PVE_PRIV_CFG)
        
        # ── Step 5: Remove any previous proxmenux blocks from BOTH files ──
        cleaned_cfg = _pve_remove_our_blocks(cfg_text, _PVE_OUR_HEADERS)
        
        if priv_text is not None:
            cleaned_priv = _pve_remove_our_blocks(priv_text, _PVE_OUR_HEADERS)
        
        # ── Step 6: Build new blocks ──
        # Exact format from a real working PVE server:
        #   webhook: name
        #   \tmethod post
        #   \turl http://...
        #
        # NO header lines -- localhost webhook doesn't need them.
        # PVE header format is: header name=X-Key,value=<base64>
        # PVE secret format is: secret name=key,value=<base64>
        # Neither is needed for localhost calls.
        
        # PVE stores body as base64 in the config file.
        # {{ escape title/message }} -- JSON-safe escaping of quotes/newlines.
        # {{ json fields }} -- renders ALL PVE metadata as a JSON object
        #   (type, hostname, job-id). This is a single Handlebars helper
        #   that always works, even if fields is empty (renders {}).
        import base64
        body_template = '{"title":"{{ escape title }}","message":"{{ escape message }}","severity":"{{ severity }}","timestamp":"{{ timestamp }}","fields":{{ json fields }}}'
        body_b64 = base64.b64encode(body_template.encode()).decode()
        
        endpoint_block = (
            f"webhook: {_PVE_ENDPOINT_ID}\n"
            f"\tbody {body_b64}\n"
            f"\tmethod post\n"
            f"\turl {_pve_webhook_url()}\n"
        )
        
        matcher_block = (
            f"matcher: {_PVE_MATCHER_ID}\n"
            f"\ttarget {_PVE_ENDPOINT_ID}\n"
            f"\tmode all\n"
        )
        
        # ── Step 7: Append our blocks to cleaned main config ──
        if cleaned_cfg and not cleaned_cfg.endswith('\n'):
            cleaned_cfg += '\n'
        if cleaned_cfg and not cleaned_cfg.endswith('\n\n'):
            cleaned_cfg += '\n'
        
        new_cfg = cleaned_cfg + endpoint_block + '\n' + matcher_block
        
        # ── Step 8: Write main config ──
        try:
            with open(_PVE_NOTIFICATIONS_CFG, 'w') as f:
                f.write(new_cfg)
        except PermissionError:
            result['error'] = f'Permission denied writing {_PVE_NOTIFICATIONS_CFG}'
            result['fallback_commands'] = _build_webhook_fallback()
            return result
        except Exception as e:
            try:
                with open(_PVE_NOTIFICATIONS_CFG, 'w') as f:
                    f.write(cfg_text)
            except Exception:
                pass
            result['error'] = str(e)
            result['fallback_commands'] = _build_webhook_fallback()
            return result
        
        # ── Step 9: Write priv config with our webhook entry ──
        # PVE REQUIRES a matching block in priv/notifications.cfg for every
        # webhook endpoint, even if it has no secrets. Without it PVE throws:
        #   "Could not instantiate endpoint: private config does not exist"
        # Include the `secret` line so PVE actually sends the
        # `X-Webhook-Secret` header on each delivery — without it the
        # endpoint depends entirely on the localhost-bypass and any move
        # to a non-loopback bind silently breaks auth. Audit Tier 3.1 —
        # `setup_pve_webhook_core` no escribe secret en priv cfg.
        #
        # PVE stores `secret value=` in STANDARD base64 and decodes it
        # before emitting the header. Writing the raw token here triggered
        # `could not decode UTF8 string from base64, key 'X-Webhook-Secret' (500)`
        # whenever `token_urlsafe` produced `-` or `_` chars (GH #198).
        secret_b64 = base64.b64encode(secret.encode()).decode()
        priv_block = (
            f"webhook: {_PVE_ENDPOINT_ID}\n"
            f"        secret name=X-Webhook-Secret,value={secret_b64}\n"
        )
        
        if priv_text is not None:
            # Start from cleaned priv (our old blocks removed)
            if cleaned_priv and not cleaned_priv.endswith('\n'):
                cleaned_priv += '\n'
            if cleaned_priv and not cleaned_priv.endswith('\n\n'):
                cleaned_priv += '\n'
            new_priv = cleaned_priv + priv_block
        else:
            new_priv = priv_block
        
        try:
            with open(_PVE_PRIV_CFG, 'w') as f:
                f.write(new_priv)
        except PermissionError:
            result['error'] = f'Permission denied writing {_PVE_PRIV_CFG}'
            result['fallback_commands'] = _build_webhook_fallback()
            return result
        except Exception:
            pass
        
        result['configured'] = True
        result['secret'] = secret
        return result
    
    except Exception as e:
        result['error'] = str(e)
        result['fallback_commands'] = _build_webhook_fallback()
        return result


@notification_bp.route('/api/notifications/proxmox/setup-webhook', methods=['POST'])
@require_auth
def setup_proxmox_webhook():
    """HTTP endpoint wrapper for webhook setup."""
    return jsonify(setup_pve_webhook_core()), 200


def cleanup_pve_webhook_core() -> dict:
    """Core logic to remove PVE webhook blocks. Callable from anywhere.
    
    Returns dict with 'cleaned', 'error' keys.
    Only removes blocks named 'proxmenux-webhook' / 'proxmenux-default'.
    """
    result = {'cleaned': False, 'error': None}
    
    try:
        # Read both files
        cfg_text, err = _pve_read_file(_PVE_NOTIFICATIONS_CFG)
        if err:
            result['error'] = err
            return result
        
        priv_text, err = _pve_read_file(_PVE_PRIV_CFG)
        if err:
            priv_text = None
        
        # Check if our blocks actually exist before doing anything
        has_our_blocks = any(
            h in cfg_text for h in [f'webhook: {_PVE_ENDPOINT_ID}', f'matcher: {_PVE_MATCHER_ID}']
        )
        has_priv_blocks = priv_text and f'webhook: {_PVE_ENDPOINT_ID}' in priv_text
        
        if not has_our_blocks and not has_priv_blocks:
            result['cleaned'] = True
            return result
        
        # Backup before modification
        _pve_backup_file(_PVE_NOTIFICATIONS_CFG)
        if priv_text is not None:
            _pve_backup_file(_PVE_PRIV_CFG)
        
        # Remove our blocks
        if has_our_blocks:
            cleaned_cfg = _pve_remove_our_blocks(cfg_text, _PVE_OUR_HEADERS)
            try:
                with open(_PVE_NOTIFICATIONS_CFG, 'w') as f:
                    f.write(cleaned_cfg)
            except PermissionError:
                result['error'] = f'Permission denied writing {_PVE_NOTIFICATIONS_CFG}'
                return result
            except Exception as e:
                # Rollback
                try:
                    with open(_PVE_NOTIFICATIONS_CFG, 'w') as f:
                        f.write(cfg_text)
                except Exception:
                    pass
                result['error'] = str(e)
                return result
        
        if has_priv_blocks and priv_text is not None:
            cleaned_priv = _pve_remove_our_blocks(priv_text, _PVE_OUR_HEADERS)
            try:
                with open(_PVE_PRIV_CFG, 'w') as f:
                    f.write(cleaned_priv)
            except Exception:
                pass  # Best-effort
        
        result['cleaned'] = True
        return result
    
    except Exception as e:
        result['error'] = str(e)
        return result


@notification_bp.route('/api/notifications/proxmox/cleanup-webhook', methods=['POST'])
@require_auth
def cleanup_proxmox_webhook():
    """HTTP endpoint wrapper for webhook cleanup."""
    return jsonify(cleanup_pve_webhook_core()), 200


@notification_bp.route('/api/notifications/proxmox/read-cfg', methods=['GET'])
@require_auth
def read_pve_notification_cfg():
    """Diagnostic: return raw content of PVE notification config files.
    
    GET /api/notifications/proxmox/read-cfg
    Returns both notifications.cfg and priv/notifications.cfg content.
    """
    import os
    
    files = {
        'notifications_cfg': '/etc/pve/notifications.cfg',
        'priv_cfg': '/etc/pve/priv/notifications.cfg',
    }
    
    # Also look for any backups we created
    backup_dir = '/etc/pve'
    priv_backup_dir = '/etc/pve/priv'
    
    result = {}
    for key, path in files.items():
        try:
            with open(path, 'r') as f:
                result[key] = {
                    'path': path,
                    'content': f.read(),
                    'size': os.path.getsize(path),
                    'error': None,
                }
        except FileNotFoundError:
            result[key] = {'path': path, 'content': None, 'size': 0, 'error': 'file_not_found'}
        except PermissionError:
            result[key] = {'path': path, 'content': None, 'size': 0, 'error': 'permission_denied'}
        except Exception as e:
            result[key] = {'path': path, 'content': None, 'size': 0, 'error': str(e)}
    
    # Find backups
    backups = []
    for d in [backup_dir, priv_backup_dir]:
        try:
            for fname in sorted(os.listdir(d)):
                if 'proxmenux_backup' in fname:
                    fpath = os.path.join(d, fname)
                    try:
                        with open(fpath, 'r') as f:
                            backups.append({
                                'path': fpath,
                                'content': f.read(),
                                'size': os.path.getsize(fpath),
                            })
                    except Exception:
                        backups.append({'path': fpath, 'content': None, 'error': 'read_failed'})
        except Exception:
            pass
    
    result['backups'] = backups
    return jsonify(result), 200


@notification_bp.route('/api/notifications/proxmox/restore-cfg', methods=['POST'])
@require_auth
def restore_pve_notification_cfg():
    """Restore PVE notification config from our backup.
    
    POST /api/notifications/proxmox/restore-cfg
    Finds the most recent proxmenux_backup and restores it.
    """
    import os
    import shutil
    
    files_to_restore = {
        '/etc/pve': '/etc/pve/notifications.cfg',
        '/etc/pve/priv': '/etc/pve/priv/notifications.cfg',
    }
    
    restored = []
    errors = []
    
    for search_dir, target_path in files_to_restore.items():
        try:
            # Pick the most recent backup by mtime, not lexicographic name.
            # An attacker (or accidental rename) with a write primitive
            # could craft `notifications.cfg.proxmenux_backup_99999999_999999`
            # and have it sort first, hijacking the restore. mtime tracks
            # the actual file age so renamed/touched files don't fool us.
            # Audit Tier 3.1 — restore-cfg sort lexicográfico.
            candidates = [
                f for f in os.listdir(search_dir)
                if 'proxmenux_backup' in f and f.startswith('notifications.cfg')
            ]

            if candidates:
                candidates.sort(
                    key=lambda f: os.path.getmtime(os.path.join(search_dir, f)),
                    reverse=True,
                )
                backup_path = os.path.join(search_dir, candidates[0])
                shutil.copy2(backup_path, target_path)
                restored.append({'target': target_path, 'from_backup': backup_path})
            else:
                errors.append({'target': target_path, 'error': 'no_backup_found'})
        except Exception as e:
            errors.append({'target': target_path, 'error': str(e)})
    
    return jsonify({
        'restored': restored,
        'errors': errors,
        'success': len(errors) == 0 and len(restored) > 0,
    }), 200


@notification_bp.route('/api/notifications/webhook', methods=['POST'])
def proxmox_webhook():
    """Receive native Proxmox VE notification webhooks (hardened).
    
    Security layers:
      Localhost (127.0.0.1 / ::1): rate limiting only.
        PVE calls us on localhost and cannot send custom auth headers,
        so we trust the loopback interface (only local processes can reach it).
      Remote: rate limiting + shared secret + timestamp + replay + IP allowlist.
    """
    _reject = lambda code, error, status: (jsonify({'accepted': False, 'error': error}), status)

    client_ip = request.remote_addr or ''
    is_localhost = _is_loopback_addr(client_ip)

    # CSRF defence-in-depth: reject `application/x-www-form-urlencoded`
    # bodies. PVE always sends `application/json`; form-encoded bodies
    # are how a browser session would POST cross-origin without preflight,
    # so accepting them here would open a CSRF vector once the route gets
    # auth wrapped in the future. Audit Tier 6 — webhook acepta form bodies.
    ct = (request.content_type or '').lower()
    if ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
        return _reject(415, 'unsupported_content_type', 415)

    # ── Layer 1: Rate limiting (per-IP, always) ──
    if not _webhook_limiter.allow(client_ip):
        resp = jsonify({'accepted': False, 'error': 'rate_limited'})
        resp.headers['Retry-After'] = '60'
        return resp, 429
    
    # ── Layers 2-5: Remote-only checks ──
    if not is_localhost:
        # Layer 2: Shared secret
        try:
            configured_secret = notification_manager.get_webhook_secret()
        except Exception:
            configured_secret = ''
        
        if configured_secret:
            request_secret = request.headers.get('X-Webhook-Secret', '')
            if not request_secret:
                return _reject(401, 'missing_secret', 401)
            if not hmac.compare_digest(configured_secret, request_secret):
                return _reject(401, 'invalid_secret', 401)
        
        # Layer 3: Anti-replay timestamp
        ts_header = request.headers.get('X-ProxMenux-Timestamp', '')
        if not ts_header:
            return _reject(401, 'missing_timestamp', 401)
        try:
            ts_value = int(ts_header)
        except (ValueError, TypeError):
            return _reject(401, 'invalid_timestamp', 401)
        if abs(time.time() - ts_value) > _TIMESTAMP_MAX_DRIFT:
            return _reject(401, 'timestamp_expired', 401)
        
        # Layer 4: Replay cache
        raw_body = request.get_data(as_text=True) or ''
        signature = hashlib.sha256(f"{ts_value}:{raw_body}".encode(errors='replace')).hexdigest()
        if _replay_cache.check_and_record(signature):
            return _reject(409, 'replay_detected', 409)
        
        # Layer 5: IP allowlist
        try:
            allowed_ips = notification_manager.get_webhook_allowed_ips()
            if allowed_ips and client_ip not in allowed_ips:
                return _reject(403, 'forbidden_ip', 403)
        except Exception:
            pass
    
    # ── Parse and process payload ──
    try:
        raw_data = request.get_data(as_text=True) or ''

        # Try JSON first (with the newline-repair pass that PVE actually
        # benefits from — its `{{ message }}` template inserts unescaped
        # newlines that break strict JSON parsing).
        payload = request.get_json(silent=True) or {}
        if not payload and raw_data:
            import json
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, ValueError):
                try:
                    repaired = raw_data.replace('\n', '\\n').replace('\r', '\\r')
                    payload = json.loads(repaired)
                except (json.JSONDecodeError, ValueError):
                    payload = {}

        # The previous regex-from-broken-JSON path and the raw-body
        # fallback let arbitrary opaque bodies into `process_webhook` —
        # an attacker who reaches the webhook (post-auth bypass) could
        # smuggle arbitrary `title`/`severity`/`body` strings into the
        # downstream pipeline. Audit Tier 3.1 — webhook payload schema.
        if not isinstance(payload, dict) or not payload:
            return _reject(400, 'invalid_payload', 400)

        # Required fields: enforce type + non-empty title/message.
        title = payload.get('title') or payload.get('subject')
        message = payload.get('message') or payload.get('body') or payload.get('text')
        if not isinstance(title, str) or not title.strip():
            return _reject(400, 'missing_title', 400)
        if not isinstance(message, str):
            message = str(message) if message is not None else ''
        # Bound runaway sizes — webhooks shouldn't exceed a few KB of text.
        if len(title) > 256:
            payload['title'] = title[:256]
        if len(message) > 4096:
            payload['message'] = message[:4096]
        # Severity normalisation: accept the canonical set, default to 'info'.
        sev = (payload.get('severity') or '').lower()
        if sev not in {'info', 'warning', 'critical', 'error', 'notice'}:
            payload['severity'] = 'info'
        else:
            payload['severity'] = sev

        result = notification_manager.process_webhook(payload)
        # Always return 200 to PVE -- a non-200 makes PVE report the webhook as broken.
        # The 'accepted' field in the JSON body indicates actual processing status.
        return jsonify(result), 200
    except Exception as e:
        # Still return 200 to avoid PVE flagging the webhook as broken
        return jsonify({'accepted': False, 'error': 'internal_error', 'detail': str(e)}), 200


# ─── Internal Shutdown Event Endpoint ─────────────────────────────

@notification_bp.route('/api/internal/shutdown-event', methods=['POST'])
def internal_shutdown_event():
    """
    Internal endpoint called by systemd ExecStop script to emit shutdown/reboot notification.
    This allows the service to send a notification BEFORE it terminates.
    
    Only accepts requests from localhost (127.0.0.1) for security.
    """
    # Security: Only allow localhost
    remote_addr = request.remote_addr
    if remote_addr not in ('127.0.0.1', '::1', 'localhost'):
        return jsonify({'error': 'forbidden', 'detail': 'localhost only'}), 403
    
    try:
        data = request.get_json(silent=True) or {}
        event_type = data.get('event_type', 'system_shutdown')
        hostname = data.get('hostname', 'unknown')
        reason = data.get('reason', 'System is shutting down.')
        
        # Validate event type
        if event_type not in ('system_shutdown', 'system_reboot'):
            return jsonify({'error': 'invalid_event_type'}), 400
        
        # Emit the notification directly through notification_manager
        notification_manager.emit_event(
            event_type=event_type,
            severity='INFO',
            data={
                'hostname': hostname,
                'reason': reason,
            },
            source='systemd',
            entity='node',
            entity_id='',
        )
        
        return jsonify({'success': True, 'event_type': event_type}), 200
    except Exception as e:
        return jsonify({'error': 'internal_error', 'detail': str(e)}), 500
