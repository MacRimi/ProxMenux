"""
ProxMenux Notification Channels
Provides transport adapters for Telegram, Gotify, and Discord.

Each channel implements send() and test() with:
- Retry with exponential backoff (3 attempts)
- Request timeout of 10s
- Rate limiting (max 30 msg/min per channel)

Author: MacRimi
"""

import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from abc import ABC, abstractmethod
from collections import deque
from typing import Tuple, Optional, Dict, Any, List


# Server-side defense-in-depth for user-supplied URLs in channel configs.
# `notification_manager.validate_external_url` rejects RFC1918 / loopback,
# but Gotify is commonly self-hosted on a LAN so we relax that — and only
# reject well-known SSRF targets (cloud metadata + the local PVE API).
# Audit Tier 6 — sin validación SSRF en URLs de webhooks/canales.
_KNOWN_SSRF_TARGETS = {
    '169.254.169.254',  # AWS/GCE/Azure metadata
    'metadata.google.internal',
    'metadata.aws.internal',
}
_BLOCKED_LOOPBACK_PORTS = {'8006', '8007'}  # PVE API HTTPS / HTTPS-alt


def _validate_user_webhook_url(url: str) -> Tuple[bool, str]:
    """Lightweight SSRF guard for Gotify-style channels.

    Allows RFC1918 / loopback hosts (legit self-hosting), but rejects:
      - schemes other than http(s)
      - cloud-metadata IPs and well-known internal hostnames
      - loopback paired with the PVE API ports — typical pivot target
    """
    if not isinstance(url, str) or not url:
        return False, "URL is required"
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False, "URL is malformed"
    if parsed.scheme not in ('http', 'https'):
        return False, "Only http:// and https:// are accepted"
    host = (parsed.hostname or '').lower()
    if not host:
        return False, "URL is missing a hostname"
    if host in _KNOWN_SSRF_TARGETS:
        return False, f"Host {host} is a known cloud-metadata endpoint"
    port = parsed.port
    if (host in ('localhost', '127.0.0.1', '::1')
            and str(port or '') in _BLOCKED_LOOPBACK_PORTS):
        return False, f"Cannot point at the local PVE API ({host}:{port})"
    return True, ""


# ─── Rate Limiter ────────────────────────────────────────────────

class RateLimiter:
    """Token-bucket rate limiter: max N messages per window.

    Thread-safe: `allow()` and `wait_time()` are called from the dispatch
    thread plus channel test paths concurrently. Without the lock the deque
    could throw IndexError on concurrent popleft / append, and the count
    could go inconsistent. Audit Tier 6 (Notification stack — `RateLimiter.allow()`
    no thread-safe).
    """

    def __init__(self, max_calls: int = 30, window_seconds: int = 60):
        import threading as _threading
        self.max_calls = max_calls
        self.window = window_seconds
        self._timestamps: deque = deque()
        self._lock = _threading.Lock()
        # Counter of events dropped while over the rate limit. Surfaced via
        # `consume_drop_count()` so the dispatch loop can periodically log
        # "X events suppressed by rate-limit" instead of letting them
        # disappear silently. Audit Tier 6 — `RateLimiter` descarta
        # silenciosamente eventos sobre el límite.
        self._dropped: int = 0

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._timestamps and now - self._timestamps[0] > self.window:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_calls:
                self._dropped += 1
                return False
            self._timestamps.append(now)
            return True

    def consume_drop_count(self) -> int:
        """Return the number of drops since the last call and reset to 0."""
        with self._lock:
            n = self._dropped
            self._dropped = 0
            return n

    def wait_time(self) -> float:
        with self._lock:
            if not self._timestamps:
                return 0.0
            return max(0.0, self.window - (time.monotonic() - self._timestamps[0]))


# ─── Base Channel ────────────────────────────────────────────────

class NotificationChannel(ABC):
    """Abstract base for all notification channels."""
    
    MAX_RETRIES = 3
    RETRY_DELAYS = [2, 4, 8]  # exponential backoff seconds
    REQUEST_TIMEOUT = 10
    
    def __init__(self):
        self._rate_limiter = RateLimiter(max_calls=30, window_seconds=60)
    
    @abstractmethod
    def send(self, title: str, message: str, severity: str = 'INFO',
             data: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a notification. Returns {success, error, channel}."""
        pass
    
    @abstractmethod
    def test(self) -> Tuple[bool, str]:
        """Send a test message. Returns (success, error_message)."""
        pass
    
    @abstractmethod
    def validate_config(self) -> Tuple[bool, str]:
        """Check if config is valid without sending. Returns (valid, error)."""
        pass
    
    def _http_request(self, url: str, data: bytes, headers: Dict[str, str],
                      method: str = 'POST') -> Tuple[int, str]:
        """Execute HTTP request with timeout. Returns (status_code, body)."""
        # Ensure User-Agent is set to avoid Cloudflare 1010 errors
        if 'User-Agent' not in headers:
            headers['User-Agent'] = 'ProxMenux-Monitor/1.1'
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                body = resp.read().decode('utf-8', errors='replace')
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
            return e.code, body
        except urllib.error.URLError as e:
            return 0, str(e.reason)
        except Exception as e:
            return 0, str(e)
    
    def _send_with_retry(self, send_fn) -> Dict[str, Any]:
        """Wrap a send function with rate limiting and retry logic."""
        if not self._rate_limiter.allow():
            wait = self._rate_limiter.wait_time()
            # Surface the cumulative drop count every ~10 events so the
            # operator notices that they're losing notifications. Calling
            # consume_drop_count() resets the counter so the next bucket
            # of drops gets its own summary.
            try:
                dropped = self._rate_limiter.consume_drop_count()
                if dropped >= 10:
                    print(f"[{self.__class__.__name__}] Rate-limit suppressed {dropped} events in the last window")
            except Exception:
                pass
            return {
                'success': False,
                'error': f'Rate limited. Retry in {wait:.0f}s',
                'rate_limited': True
            }
        
        last_error = ''
        for attempt in range(self.MAX_RETRIES):
            try:
                status, body = send_fn()
                if 200 <= status < 300:
                    return {'success': True, 'error': None}
                last_error = f'HTTP {status}: {body[:200]}'
            except Exception as e:
                last_error = str(e)
            
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(self.RETRY_DELAYS[attempt])
        
        return {'success': False, 'error': last_error}


# ─── Telegram ────────────────────────────────────────────────────

class TelegramChannel(NotificationChannel):
    """Telegram Bot API channel using HTML parse mode."""
    
    API_BASE = 'https://api.telegram.org/bot{token}/sendMessage'
    API_PHOTO = 'https://api.telegram.org/bot{token}/sendPhoto'
    MAX_LENGTH = 4096
    
    SEVERITY_ICONS = {
        'CRITICAL': '\U0001F534',  # red circle
        'WARNING':  '\U0001F7E1',  # yellow circle
        'INFO':     '\U0001F535',  # blue circle
        'OK':       '\U0001F7E2',  # green circle
        'UNKNOWN':  '\u26AA',      # white circle
    }
    
    def __init__(self, bot_token: str, chat_id: str, topic_id: str = ''):
        super().__init__()
        token = bot_token.strip()
        # Strip 'bot' prefix if user included it (API_BASE already adds it)
        if token.lower().startswith('bot') and ':' in token[3:]:
            token = token[3:]
        self.bot_token = token
        self.chat_id = chat_id.strip()
        # Topic ID for supergroups with topics enabled (message_thread_id)
        self.topic_id = topic_id.strip() if topic_id else ''
    
    def validate_config(self) -> Tuple[bool, str]:
        if not self.bot_token:
            return False, 'Bot token is required'
        if not self.chat_id:
            return False, 'Chat ID is required'
        if ':' not in self.bot_token:
            return False, 'Invalid bot token format (expected BOT_ID:TOKEN)'
        return True, ''
    
    def send(self, title: str, message: str, severity: str = 'INFO',
             data: Optional[Dict] = None) -> Dict[str, Any]:
        icon = self.SEVERITY_ICONS.get(severity, self.SEVERITY_ICONS['INFO'])
        html_msg = f"<b>{icon} {self._escape_html(title)}</b>\n\n{self._escape_html(message)}"
        
        # Split long messages
        chunks = self._split_message(html_msg)
        result = {'success': True, 'error': None, 'channel': 'telegram'}
        
        for chunk in chunks:
            res = self._send_with_retry(lambda c=chunk: self._post_message(c))
            if not res['success']:
                result = {**res, 'channel': 'telegram'}
                break
        
        return result
    
    def send_photo(self, photo_url: str, caption: str = '') -> Dict[str, Any]:
        """Send a photo to Telegram chat."""
        url = self.API_PHOTO.format(token=self.bot_token)
        payload = {
            'chat_id': self.chat_id,
            'photo': photo_url,
        }
        # Add topic ID for supergroups with topics enabled
        if self.topic_id:
            try:
                payload['message_thread_id'] = int(self.topic_id)
            except ValueError:
                pass
        if caption:
            payload['caption'] = caption[:1024]  # Telegram caption limit
            payload['parse_mode'] = 'HTML'
        
        body = json.dumps(payload).encode()
        headers = {'Content-Type': 'application/json'}
        
        result = self._send_with_retry(
            lambda: self._http_request(url, body, headers)
        )
        result['channel'] = 'telegram'
        return result
    
    def test(self) -> Tuple[bool, str]:
        valid, err = self.validate_config()
        if not valid:
            return False, err
        
        result = self.send(
            'ProxMenux Test',
            'Notification service is working correctly.\nThis is a test message from ProxMenux Monitor.',
            'INFO'
        )
        return result['success'], result.get('error', '')
    
    def _post_message(self, text: str) -> Tuple[int, str]:
        url = self.API_BASE.format(token=self.bot_token)
        payload_dict = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
        # Add topic ID for supergroups with topics enabled
        if self.topic_id:
            try:
                payload_dict['message_thread_id'] = int(self.topic_id)
            except ValueError:
                pass  # Invalid topic_id, skip
        
        payload = json.dumps(payload_dict).encode('utf-8')
        return self._http_request(url, payload, {'Content-Type': 'application/json'})
    
    def _split_message(self, text: str) -> list:
        if len(text) <= self.MAX_LENGTH:
            return [text]
        chunks = []
        while text:
            if len(text) <= self.MAX_LENGTH:
                chunks.append(text)
                break
            split_at = text.rfind('\n', 0, self.MAX_LENGTH)
            if split_at == -1:
                split_at = self.MAX_LENGTH
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip('\n')
        return chunks
    
    @staticmethod
    def _escape_html(text: str) -> str:
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))


# ─── Gotify ──────────────────────────────────────────────────────

class GotifyChannel(NotificationChannel):
    """Gotify push notification channel with priority mapping."""
    
    PRIORITY_MAP = {
        'OK':       1,
        'INFO':     2,
        'UNKNOWN':  3,
        'WARNING':  5,
        'CRITICAL': 10,
    }
    
    def __init__(self, server_url: str, app_token: str):
        super().__init__()
        self.server_url = server_url.rstrip('/').strip()
        self.app_token = app_token.strip()
    
    def validate_config(self) -> Tuple[bool, str]:
        if not self.server_url:
            return False, 'Server URL is required'
        if not self.app_token:
            return False, 'Application token is required'
        ok, err = _validate_user_webhook_url(self.server_url)
        if not ok:
            return False, f'Invalid Gotify URL: {err}'
        return True, ''
    
    def send(self, title: str, message: str, severity: str = 'INFO',
             data: Optional[Dict] = None) -> Dict[str, Any]:
        priority = self.PRIORITY_MAP.get(severity, 2)
        
        result = self._send_with_retry(
            lambda: self._post_message(title, message, priority)
        )
        result['channel'] = 'gotify'
        return result
    
    def test(self) -> Tuple[bool, str]:
        valid, err = self.validate_config()
        if not valid:
            return False, err
        
        result = self.send(
            'ProxMenux Test',
            'Notification service is working correctly.\nThis is a test message from ProxMenux Monitor.',
            'INFO'
        )
        return result['success'], result.get('error', '')
    
    def _post_message(self, title: str, message: str, priority: int) -> Tuple[int, str]:
        url = f"{self.server_url}/message?token={self.app_token}"
        payload = json.dumps({
            'title': title,
            'message': message,
            'priority': priority,
            'extras': {
                'client::display': {'contentType': 'text/markdown'}
            }
        }).encode('utf-8')
        
        return self._http_request(url, payload, {'Content-Type': 'application/json'})


# ─── Discord ─────────────────────────────────────────────────────

class DiscordChannel(NotificationChannel):
    """Discord webhook channel with color-coded embeds."""
    
    MAX_EMBED_DESC = 2048
    
    SEVERITY_COLORS = {
        'CRITICAL': 0xED4245,   # red
        'WARNING':  0xFEE75C,   # yellow
        'INFO':     0x5865F2,   # blurple
        'OK':       0x57F287,   # green
        'UNKNOWN':  0x99AAB5,   # grey
    }
    
    def __init__(self, webhook_url: str):
        super().__init__()
        self.webhook_url = webhook_url.strip()
    
    _DISCORD_HOSTS = {
        'discord.com', 'discordapp.com',
        'ptb.discord.com', 'canary.discord.com',
    }

    def validate_config(self) -> Tuple[bool, str]:
        if not self.webhook_url:
            return False, 'Webhook URL is required'
        # Substring match (`'discord.com/api/webhooks/' in url`) accepted
        # crafted URLs like `http://attacker.example/proxy?u=https://discord.com/api/webhooks/...`.
        # Parse properly: require https + exact discord hostname + the
        # /api/webhooks/<id>/<token> path.
        try:
            from urllib.parse import urlparse as _urlparse
            parsed = _urlparse(self.webhook_url)
        except Exception:
            return False, 'Invalid Discord webhook URL'
        if parsed.scheme != 'https':
            return False, 'Discord webhook must use https://'
        if (parsed.hostname or '').lower() not in self._DISCORD_HOSTS:
            return False, 'Invalid Discord webhook URL (host must be discord.com)'
        if not parsed.path.startswith('/api/webhooks/'):
            return False, 'Invalid Discord webhook URL (path must be /api/webhooks/...)'
        return True, ''
    
    def send(self, title: str, message: str, severity: str = 'INFO',
             data: Optional[Dict] = None) -> Dict[str, Any]:
        color = self.SEVERITY_COLORS.get(severity, 0x5865F2)
        
        desc = message[:self.MAX_EMBED_DESC] if len(message) > self.MAX_EMBED_DESC else message
        
        embed = {
            'title': title,
            'description': desc,
            'color': color,
            'footer': {'text': 'ProxMenux Monitor'},
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        
        # Use structured fields from render_template if available
        rendered_fields = (data or {}).get('_rendered_fields', [])
        if rendered_fields:
            embed['fields'] = [
                {'name': name, 'value': val[:1024], 'inline': True}
                for name, val in rendered_fields[:25]  # Discord limit: 25 fields
            ]
        elif data:
            fields = []
            if data.get('category'):
                fields.append({'name': 'Category', 'value': data['category'], 'inline': True})
            if data.get('hostname'):
                fields.append({'name': 'Host', 'value': data['hostname'], 'inline': True})
            if data.get('severity'):
                fields.append({'name': 'Severity', 'value': data['severity'], 'inline': True})
            if fields:
                embed['fields'] = fields
        
        result = self._send_with_retry(
            lambda: self._post_webhook(embed)
        )
        result['channel'] = 'discord'
        return result
    
    def test(self) -> Tuple[bool, str]:
        valid, err = self.validate_config()
        if not valid:
            return False, err
        
        result = self.send(
            'ProxMenux Test',
            'Notification service is working correctly.\nThis is a test message from ProxMenux Monitor.',
            'INFO'
        )
        return result['success'], result.get('error', '')
    
    def _post_webhook(self, embed: Dict) -> Tuple[int, str]:
        payload = json.dumps({
            'username': 'ProxMenux',
            'embeds': [embed]
        }).encode('utf-8')
        
        return self._http_request(
            self.webhook_url, payload, {'Content-Type': 'application/json'}
        )


# ─── Email Channel ──────────────────────────────────────────────

class EmailChannel(NotificationChannel):
    """Email notification channel using SMTP (smtplib) or sendmail fallback.
    
    Config keys:
      host, port, username, password, tls_mode (none|starttls|ssl),
      from_address, to_addresses (comma-separated), subject_prefix, timeout
    """
    
    def __init__(self, config: Dict[str, str]):
        super().__init__()
        self.host = (config.get('host', '') or '').strip()
        self.port = int(config.get('port', 587) or 587)
        self.username = config.get('username', '') or ''
        self.password = config.get('password', '') or ''
        # `dict.get(k, default)` only returns default when the key is MISSING;
        # if the user previously saved an empty string or null, we'd end up
        # with `tls_mode=''` and silently skip STARTTLS — which causes
        # `SMTPNotSupportedError: SMTP AUTH extension not supported by server`
        # on Gmail/Outlook because they only advertise AUTH post-STARTTLS.
        tls_raw = (config.get('tls_mode') or 'starttls').strip().lower()
        if tls_raw not in ('none', 'starttls', 'ssl'):
            tls_raw = 'starttls'
        self.tls_mode = tls_raw
        self.from_address = config.get('from_address', '') or ''
        self.to_addresses = self._parse_recipients(config.get('to_addresses', ''))
        self.subject_prefix = config.get('subject_prefix', '[ProxMenux]') or '[ProxMenux]'
        self.timeout = int(config.get('timeout', 10) or 10)
    
    @staticmethod
    def _parse_recipients(raw) -> list:
        if isinstance(raw, list):
            return [a.strip() for a in raw if a.strip()]
        return [addr.strip() for addr in str(raw).split(',') if addr.strip()]
    
    def validate_config(self) -> Tuple[bool, str]:
        if not self.to_addresses:
            return False, 'No recipients configured'
        if not self.from_address:
            return False, 'No from address configured'
        # Credentials without an explicit SMTP host would silently fall back to
        # `/usr/sbin/sendmail`, which ignores username/password entirely — the
        # test returns OK because Postfix queued the message, but the relay is
        # never authenticated and the mail rots in the local mailq. Reported by
        # Ignacio Seijo: "dejando host/puerto en blanco el test pasa pero el
        # correo nunca llega".
        if (self.username or self.password) and not self.host:
            return False, ('SMTP credentials provided but no host configured. '
                           'Set host (e.g. smtp.gmail.com) and port (587) — '
                           'without a host the message goes to the local MTA '
                           'and your username/password are ignored.')
        # Must have SMTP host OR local sendmail available
        if not self.host:
            import os
            if not os.path.exists('/usr/sbin/sendmail'):
                return False, 'No SMTP host configured and /usr/sbin/sendmail not found'
        # Reject configurations that would send credentials in cleartext over
        # the network. Loopback (`localhost` / `127.0.0.1`) and the local-only
        # sendmail path are exempt — those don't traverse a wire that an
        # attacker could sniff. Audit Tier 6 (Notification stack — SMTP TLS).
        host_lower = (self.host or '').lower()
        is_local = host_lower in ('', 'localhost', 'localhost.localdomain', '127.0.0.1', '::1')
        if (self.tls_mode == 'none' and self.username and self.password and not is_local):
            return False, ('SMTP TLS is disabled but credentials would travel over plain '
                           'text. Use STARTTLS or SSL/TLS, or remove the username/password.')
        return True, ''
    
    def send(self, title: str, message: str, severity: str = 'INFO',
             data: Optional[Dict] = None) -> Dict[str, Any]:
        subject = f"{self.subject_prefix} [{severity}] {title}"
        
        def _do_send():
            if self.host:
                return self._send_smtp(subject, message, severity, data)
            else:
                return self._send_sendmail(subject, message, severity, data)
        
        return self._send_with_retry(_do_send)
    
    def _send_smtp(self, subject: str, body: str, severity: str,
                   data: Optional[Dict] = None) -> Tuple[int, str]:
        import smtplib
        from email.message import EmailMessage
        
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = self.from_address
        msg['To'] = ', '.join(self.to_addresses)
        msg.set_content(body)
        
        # Add HTML alternative
        html_body = self._format_html(subject, body, severity, data)
        if html_body:
            msg.add_alternative(html_body, subtype='html')
        
        server = None
        try:
            import ssl as _ssl
            
            if self.tls_mode == 'ssl':
                ctx = _ssl.create_default_context()
                server = smtplib.SMTP_SSL(self.host, self.port,
                                          timeout=self.timeout, context=ctx)
                server.ehlo()
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                server.ehlo()
                if self.tls_mode == 'starttls':
                    ctx = _ssl.create_default_context()
                    server.starttls(context=ctx)
                    server.ehlo()  # Re-identify after TLS -- server re-announces AUTH
            
            if self.username and self.password:
                # If the server doesn't advertise AUTH after our EHLO sequence,
                # smtplib's `login()` raises `SMTPNotSupportedError` with the
                # opaque message "SMTP AUTH extension not supported by server".
                # That fired for users who left tls_mode blank or pointed at
                # port 587 without STARTTLS — Gmail only advertises AUTH after
                # the TLS handshake. Surface the real reason here.
                if not server.has_extn('auth'):
                    hint = (
                        f"server={self.host}:{self.port} tls_mode={self.tls_mode}"
                    )
                    if self.tls_mode == 'none':
                        return 0, (
                            'SMTP server did not advertise AUTH after EHLO. '
                            'TLS is disabled — most providers (Gmail, Outlook, '
                            'Office365) only allow login after STARTTLS or SSL. '
                            f'Switch TLS Mode to STARTTLS (port 587) or SSL/TLS '
                            f'(port 465). [{hint}]'
                        )
                    return 0, (
                        'SMTP server did not advertise AUTH after EHLO. '
                        'Verify the host/port/TLS combination. For Gmail use '
                        'smtp.gmail.com:587 with STARTTLS and an App Password '
                        '(https://myaccount.google.com/apppasswords); for '
                        f'Outlook use smtp.office365.com:587 with STARTTLS. [{hint}]'
                    )
                server.login(self.username, self.password)

            server.send_message(msg)
            server.quit()
            server = None
            return 200, 'OK'
        except smtplib.SMTPAuthenticationError as e:
            return 0, f'SMTP authentication failed (check username/password or app-specific password): {e}'
        except smtplib.SMTPNotSupportedError as e:
            return 0, (f'SMTP AUTH not supported by server. '
                       f'TLS mode: {self.tls_mode}, port: {self.port}. '
                       f'Gmail/Outlook require STARTTLS on 587 or SSL/TLS on 465. '
                       f'For Gmail, generate an App Password at '
                       f'https://myaccount.google.com/apppasswords. Detail: {e}')
        except smtplib.SMTPConnectError as e:
            return 0, f'SMTP connection failed: {e}'
        except smtplib.SMTPException as e:
            return 0, f'SMTP error: {e}'
        except _ssl.SSLError as e:
            return 0, f'TLS/SSL error (check TLS mode and port): {e}'
        except (OSError, TimeoutError) as e:
            return 0, f'Connection error: {e}'
        finally:
            if server:
                try:
                    server.quit()
                except Exception:
                    pass
    
    def _send_sendmail(self, subject: str, body: str, severity: str,
                       data: Optional[Dict] = None) -> Tuple[int, str]:
        import os
        import subprocess
        from email.message import EmailMessage
        
        sendmail = '/usr/sbin/sendmail'
        if not os.path.exists(sendmail):
            return 0, 'sendmail not found at /usr/sbin/sendmail'
        
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = self.from_address or 'proxmenux@localhost'
        msg['To'] = ', '.join(self.to_addresses)
        msg.set_content(body)
        
        # Add HTML alternative
        html_body = self._format_html(subject, body, severity, data)
        if html_body:
            msg.add_alternative(html_body, subtype='html')
        
        try:
            proc = subprocess.run(
                [sendmail, '-t', '-oi'],
                input=msg.as_string(), capture_output=True, text=True, timeout=30
            )
            if proc.returncode == 0:
                return 200, 'OK'
            return 0, f'sendmail failed (rc={proc.returncode}): {proc.stderr[:200]}'
        except subprocess.TimeoutExpired:
            return 0, 'sendmail timed out after 30s'
        except Exception as e:
            return 0, f'sendmail error: {e}'
    
    # Severity -> accent colour + label
    _SEV_STYLE = {
        'CRITICAL': {'color': '#dc2626', 'bg': '#fef2f2', 'border': '#fecaca', 'label': 'Critical'},
        'WARNING':  {'color': '#d97706', 'bg': '#fffbeb', 'border': '#fde68a', 'label': 'Warning'},
        'INFO':     {'color': '#2563eb', 'bg': '#eff6ff', 'border': '#bfdbfe', 'label': 'Information'},
        'OK':       {'color': '#16a34a', 'bg': '#f0fdf4', 'border': '#bbf7d0', 'label': 'Resolved'},
    }
    _SEV_DEFAULT = {'color': '#6b7280', 'bg': '#f9fafb', 'border': '#e5e7eb', 'label': 'Notice'}

    # Group -> human-readable section header for the email
    _GROUP_LABELS = {
        'vm_ct':     'Virtual Machine / Container',
        'backup':    'Backup & Snapshot',
        'resources': 'System Resources',
        'storage':   'Storage',
        'network':   'Network',
        'security':  'Security',
        'cluster':   'Cluster',
        'services':  'System Services',
        'health':    'Health Monitor',
        'updates':   'System Updates',
        'other':     'System Notification',
    }

    def _format_html(self, subject: str, body: str, severity: str,
                     data: Optional[Dict] = None) -> str:
        """Build a professional HTML email with structured data sections."""
        import html as html_mod
        import time as _time

        data = data or {}
        sev = self._SEV_STYLE.get(severity, self._SEV_DEFAULT)

        # Determine group for section header
        event_type = data.get('_event_type', '')
        group = data.get('_group', 'other')
        section_label = self._GROUP_LABELS.get(group, 'System Notification')

        # Timestamp
        ts = data.get('timestamp', '') or _time.strftime('%Y-%m-%d %H:%M:%S UTC', _time.gmtime())

        # ── Build structured detail rows from known data fields ──
        detail_rows = self._build_detail_rows(data, event_type, group, html_mod)

        # ── Fallback: if no structured rows, render body text lines ──
        if not detail_rows:
            for line in body.split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                # Try to split "Label: value" patterns
                if ':' in stripped:
                    lbl, _, val = stripped.partition(':')
                    if val.strip() and len(lbl) < 40:
                        detail_rows.append((html_mod.escape(lbl.strip()), html_mod.escape(val.strip())))
                        continue
                detail_rows.append(('', html_mod.escape(stripped)))

        # ── Render detail rows as HTML table ──
        rows_html = ''
        for label, value in detail_rows:
            if label:
                rows_html += f'''<tr>
  <td style="padding:8px 12px;font-size:13px;color:#374151;font-weight:500;white-space:nowrap;vertical-align:top;border-bottom:1px solid #e5e7eb;">{label}</td>
  <td style="padding:8px 12px;font-size:13px;color:#111827;border-bottom:1px solid #e5e7eb;">{value}</td>
</tr>'''
            else:
                # Full-width row (no label, just description text)
                rows_html += f'''<tr>
  <td colspan="2" style="padding:8px 12px;font-size:13px;color:#1f2937;border-bottom:1px solid #e5e7eb;">{value}</td>
</tr>'''

        # ── Reason / details block (long text, displayed separately) ──
        reason = data.get('reason', '')
        reason_html = ''
        if reason and len(reason) > 80:
            reason_html = f'''
<div style="margin:16px 0 0;padding:12px 16px;border:1px solid #d1d5db;border-radius:6px;">
  <p style="margin:0 0 4px;font-size:11px;font-weight:600;color:#374151;text-transform:uppercase;letter-spacing:0.05em;">Details</p>
  <p style="margin:0;font-size:13px;color:#1f2937;line-height:1.6;white-space:pre-wrap;">{html_mod.escape(reason)}</p>
</div>'''

        # ── Clean subject for display (remove prefix if present) ──
        display_title = subject
        for prefix in [self.subject_prefix, '[CRITICAL]', '[WARNING]', '[INFO]', '[OK]']:
            display_title = display_title.replace(prefix, '').strip()

        return f'''<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<div style="max-width:640px;margin:24px auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);border:1px solid #d1d5db;">

  <!-- Header -->
  <div style="padding:20px 28px;background:#f8f9fa;border-bottom:1px solid {sev['border']};">
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td>
          <h1 style="margin:0;font-size:18px;font-weight:700;color:#111827;letter-spacing:-0.02em;">ProxMenux Monitor</h1>
          <p style="margin:4px 0 0;font-size:12px;color:#4b5563;">{html_mod.escape(section_label)} Report</p>
        </td>
        <td style="text-align:right;vertical-align:top;">
          <span style="display:inline-block;padding:4px 12px;border-radius:4px;font-size:11px;font-weight:600;letter-spacing:0.05em;color:{sev['color']};background:{sev['bg']};border:1px solid {sev['border']};">{sev['label'].upper()}</span>
        </td>
      </tr>
    </table>
  </div>

  <!-- Title bar -->
  <div style="padding:16px 28px;background:{sev['bg']};border-bottom:1px solid {sev['border']};">
    <h2 style="margin:0;font-size:15px;font-weight:600;color:{sev['color']};">{html_mod.escape(display_title)}</h2>
  </div>

  <!-- Body -->
  <div style="padding:24px 28px;">
    <!-- Metadata -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px;">
      <tr>
        <td style="font-size:12px;color:#4b5563;">
          Host: <strong style="color:#111827;">{html_mod.escape(data.get('hostname', ''))}</strong>
        </td>
        <td style="font-size:12px;color:#4b5563;text-align:right;">
          {html_mod.escape(ts)}
        </td>
      </tr>
    </table>

    <!-- Detail table -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #d1d5db;border-radius:6px;overflow:hidden;">
      {rows_html}
    </table>

    {reason_html}
  </div>

  <!-- Footer -->
  <div style="padding:14px 28px;border-top:1px solid #d1d5db;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td style="font-size:11px;color:#4b5563;">ProxMenux Notification Service</td>
        <td style="font-size:11px;color:#4b5563;text-align:right;">proxmenux.com</td>
      </tr>
    </table>
  </div>

</div>
</body>
</html>'''

    @staticmethod
    def _build_detail_rows(data: Dict, event_type: str, group: str,
                           html_mod) -> list:
        """Build structured (label, value) rows from event data.
        
        Returns list of (label_html, value_html) tuples.
        An empty label means a full-width descriptive row.
        """
        esc = html_mod.escape
        rows = []
        
        def _add(label: str, value, fmt: str = ''):
            """Add a row if value is truthy."""
            v = str(value).strip() if value else ''
            if not v or v == '0' and label not in ('Failures',):
                return
            if fmt == 'severity':
                sev_colors = {
                    'CRITICAL': '#dc2626', 'WARNING': '#d97706',
                    'INFO': '#2563eb', 'OK': '#16a34a',
                }
                c = sev_colors.get(v, '#6b7280')
                rows.append((esc(label), f'<span style="color:{c};font-weight:600;">{esc(v)}</span>'))
            elif fmt == 'code':
                rows.append((esc(label), f'<code style="padding:2px 6px;background:#f3f4f6;border-radius:3px;font-family:monospace;font-size:12px;">{esc(v)}</code>'))
            elif fmt == 'bold':
                rows.append((esc(label), f'<strong>{esc(v)}</strong>'))
            else:
                rows.append((esc(label), esc(v)))

        # ── Common fields present in most events ──
        
        # ── VM / CT events ──
        if group == 'vm_ct':
            _add('VM/CT ID', data.get('vmid'), 'code')
            _add('Name', data.get('vmname'), 'bold')
            _add('Action', event_type.replace('_', ' ').replace('vm ', 'VM ').replace('ct ', 'CT ').title())
            _add('Target Node', data.get('target_node'))
            _add('Reason', data.get('reason'))

        # ── Backup events ──
        elif group == 'backup':
            _add('VM/CT ID', data.get('vmid'), 'code')
            _add('Name', data.get('vmname'), 'bold')
            _add('Status', 'Failed' if 'fail' in event_type else 'Completed' if 'complete' in event_type else 'Started',
                 'severity' if 'fail' in event_type else '')
            _add('Size', data.get('size'))
            _add('Duration', data.get('duration'))
            _add('Snapshot', data.get('snapshot_name'), 'code')
            # For backup_complete/fail with parsed body, add short reason only
            reason = data.get('reason', '')
            if reason and len(reason) <= 80:
                _add('Details', reason)

        # ── Resources ──
        elif group == 'resources':
            _add('Metric', event_type.replace('_', ' ').title())
            _add('Current Value', data.get('value'), 'bold')
            _add('Threshold', data.get('threshold'))
            _add('CPU Cores', data.get('cores'))
            _add('Memory', f"{data.get('used', '')} / {data.get('total', '')}" if data.get('used') else '')
            _add('Temperature', f"{data.get('value')}C" if 'temp' in event_type else '')

        # ── Storage ──
        elif group == 'storage':
            if 'disk_space' in event_type:
                _add('Mount Point', data.get('mount'), 'code')
                _add('Usage', f"{data.get('used')}%", 'bold')
                _add('Available', data.get('available'))
            elif 'io_error' in event_type:
                _add('Device', data.get('device'), 'code')
                _add('Severity', data.get('severity', ''), 'severity')
            elif 'unavailable' in event_type:
                _add('Storage Name', data.get('storage_name'), 'bold')
                _add('Type', data.get('storage_type'), 'code')
                reason = data.get('reason', '')
                if reason and len(reason) <= 80:
                    _add('Details', reason)

        # ── Network ──
        elif group == 'network':
            _add('Interface', data.get('interface'), 'code')
            _add('Latency', f"{data.get('value')}ms" if data.get('value') else '')
            _add('Threshold', f"{data.get('threshold')}ms" if data.get('threshold') else '')
            reason = data.get('reason', '')
            if reason and len(reason) <= 80:
                _add('Details', reason)

        # ── Security ──
        elif group == 'security':
            _add('Event', event_type.replace('_', ' ').title())
            _add('Source IP', data.get('source_ip'), 'code')
            _add('Username', data.get('username'), 'code')
            _add('Service', data.get('service'))
            _add('Jail', data.get('jail'), 'code')
            _add('Failures', data.get('failures'))
            _add('Change', data.get('change_details'))

        # ── Cluster ──
        elif group == 'cluster':
            _add('Event', event_type.replace('_', ' ').title())
            _add('Node', data.get('node_name'), 'bold')
            _add('Quorum', data.get('quorum'))
            _add('Nodes Affected', data.get('entity_list'))

        # ── Services ──
        elif group == 'services':
            _add('Service', data.get('service_name'), 'code')
            _add('Process', data.get('process'), 'code')
            _add('Event', event_type.replace('_', ' ').title())
            reason = data.get('reason', '')
            if reason and len(reason) <= 80:
                _add('Details', reason)

        # ── Health monitor ──
        elif group == 'health':
            _add('Category', data.get('category'), 'bold')
            _add('Severity', data.get('severity', ''), 'severity')
            if data.get('original_severity'):
                _add('Previous Severity', data.get('original_severity'), 'severity')
            _add('Duration', data.get('duration'))
            _add('Active Issues', data.get('count'))
            reason = data.get('reason', '')
            if reason and len(reason) <= 80:
                _add('Details', reason)

        # ── Updates ──
        elif group == 'updates':
            _add('Total Updates', data.get('total_count'), 'bold')
            _add('Security Updates', data.get('security_count'))
            _add('Proxmox Updates', data.get('pve_count'))
            _add('Kernel Updates', data.get('kernel_count'))
            imp = data.get('important_list', '')
            if imp and imp != 'none':
                # Render each package on its own line inside a single cell
                pkg_lines = [l.strip() for l in imp.split('\n') if l.strip()]
                if pkg_lines:
                    pkg_html = '<br>'.join(
                        f'<code style="padding:1px 5px;background:#f3f4f6;border-radius:3px;font-family:monospace;font-size:12px;">{esc(p)}</code>'
                        for p in pkg_lines
                    )
                    rows.append((esc('Important Packages'), pkg_html))
            _add('Current Version', data.get('current_version'), 'code')
            _add('New Version', data.get('new_version'), 'code')

        # ── Other / unknown ──
        else:
            reason = data.get('reason', '')
            if reason and len(reason) <= 80:
                _add('Details', reason)

        return rows
    
    def test(self) -> Tuple[bool, str]:
        # Lazy import to avoid a circular dependency with notification_manager,
        # which already imports from this module at load time.
        from notification_manager import _resolve_display_hostname
        hostname = _resolve_display_hostname()
        result = self.send(
            'ProxMenux Test Notification',
            'This is a test notification from ProxMenux Monitor.\n'
            'If you received this, your email channel is working correctly.',
            'INFO',
            data={
                'hostname': hostname,
                '_event_type': 'webhook_test',
                '_group': 'other',
                'reason': 'Email notification channel connectivity verified successfully. '
                          'You will receive alerts from ProxMenux Monitor at this address.',
            }
        )
        return result.get('success', False), result.get('error', '')


# ─── Apprise ─────────────────────────────────────────────────────

class _AppriseLogCapture(logging.Handler):
    """Buffers records emitted by the `apprise` logger during a single
    notify() call so the surrounding channel can surface the real
    failure reason — e.g. "error=400" plus the destination's response
    body — instead of the opaque "transport failure" string
    apprise.notify() leaves behind on a False return.

    Captures everything at DEBUG so the response body (which apprise's
    custom_json plugin logs only at DEBUG) is available; `summary()`
    keeps the output bounded for UI display."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(record)
        except Exception:
            pass

    def summary(self) -> str:
        """Concise digest of the captured records — WARNING+ messages
        first (the failure reason), then a single "Response Details"
        DEBUG line if present (the destination's reply body, useful for
        decoding 400s like `{"error": "field X missing"}`). Capped per
        line so a noisy plugin can't blow past the 200-char truncation
        `_send_with_retry` applies on the way out."""
        warn_msgs: List[str] = []
        response_body: str = ''
        for r in self.records:
            try:
                msg = r.getMessage()
            except Exception:
                continue
            if not msg:
                continue
            if r.levelno >= logging.WARNING:
                if msg not in warn_msgs:
                    warn_msgs.append(msg[:160])
            elif 'Response Details' in msg and not response_body:
                # Plugin logs the body as `Response Details:\r\n%r` — the
                # %r already wraps the bytes in repr(b'…'), strip it for
                # readability.
                body = msg.split('Response Details:', 1)[1].strip()
                if body.startswith(("b'", 'b"')):
                    body = body[2:]
                if body.endswith(("'", '"')):
                    body = body[:-1]
                body = body.replace('\\r\\n', ' ').replace('\\n', ' ').strip()
                if body:
                    response_body = body[:300]
        parts: List[str] = []
        if warn_msgs:
            parts.extend(warn_msgs)
        if response_body:
            parts.append(f'response: {response_body}')
        return ' | '.join(parts)


class AppriseChannel(NotificationChannel):
    """Apprise meta-channel — a single URL talks to ~80 services.

    Apprise (https://github.com/caronc/apprise) is a Python library that
    normalises a wide catalogue of notification destinations behind a
    single URL scheme: `tgram://`, `discord://`, `slack://`, `gotify://`,
    `ntfy://`, `matrix://`, `mailto://`, `pushover://`, `signal://`, etc.
    The operator pastes one URL and ProxMenux delegates the transport.

    Requested in issue #207 by @0berkampf. Implemented as a *separate
    channel type* (not a replacement for the native Telegram / Gotify /
    Discord / Email channels), so installs that already have a working
    native channel don't need to migrate — Apprise is opt-in for users
    who want to reach a service we don't support natively.

    The library is loaded lazily on first send. Older deployments that
    haven't installed it yet surface a clean validation error instead
    of crashing the notification manager at import time.
    """

    def __init__(self, url: str):
        super().__init__()
        self.url = (url or '').strip()

    # Lazy import so installs that haven't picked up the new dep yet
    # don't crash on module load. Each call re-imports cheaply — Python
    # caches the module reference after the first hit.
    def _load_apprise(self):
        try:
            import apprise  # type: ignore
            return apprise
        except ImportError:
            return None

    def validate_config(self) -> Tuple[bool, str]:
        if not self.url:
            return False, 'Apprise URL is required'
        apprise = self._load_apprise()
        if apprise is None:
            return False, (
                'apprise library not installed in this deployment. '
                'Reinstall ProxMenux Monitor or run `pip install apprise` '
                'inside the AppImage environment.'
            )
        # `add(url)` returns True only if Apprise recognised the scheme
        # — useful as a syntactic validation without sending anything.
        try:
            apobj = apprise.Apprise()
            ok = apobj.add(self.url)
            if not ok:
                return False, 'Apprise rejected the URL (unrecognised scheme or bad format)'
        except Exception as e:
            return False, f'Apprise rejected the URL: {e}'
        return True, ''

    def _severity_to_notify_type(self, apprise_mod, severity: str):
        """Map ProxMenux severities to Apprise NotifyType constants so
        services that render severity (e.g. Pushover priority, ntfy
        priority headers) get the right indicator."""
        sev = (severity or '').upper()
        if sev == 'CRITICAL':
            return apprise_mod.NotifyType.FAILURE
        if sev == 'WARNING':
            return apprise_mod.NotifyType.WARNING
        if sev == 'SUCCESS':
            return apprise_mod.NotifyType.SUCCESS
        return apprise_mod.NotifyType.INFO

    def send(self, title: str, message: str, severity: str = 'INFO',
             data: Optional[Dict] = None) -> Dict[str, Any]:
        ok, err = self.validate_config()
        if not ok:
            return {'success': False, 'error': err, 'channel': 'apprise'}

        # Rate limit (shared with the other channels) before dispatch.
        def _send_via_apprise() -> Tuple[int, str]:
            apprise = self._load_apprise()
            if apprise is None:
                # Shouldn't happen — validate_config caught it above —
                # but defend in depth so the retry loop reports cleanly.
                return 0, 'apprise library not available'

            # Capture Apprise's internal logger during notify(). When the
            # plugin (jsons://, ntfy://, slack://, ...) gets a non-2xx
            # from the destination it logs at WARNING with the HTTP
            # status code — e.g. "Failed to send JSON POST notification:
            # error=400.". Without this capture, `notify()` just returns
            # False and we'd surface a useless "transport failure" with
            # no clue why. Reported by a beta user on 2026-05-30: jsons://
            # → HTTP 400 from their webhook, no way to see the 400 in
            # the Monitor UI.
            apprise_logger = logging.getLogger('apprise')
            handler = _AppriseLogCapture()
            handler.setLevel(logging.DEBUG)
            prev_level = apprise_logger.level
            apprise_logger.addHandler(handler)
            # Drop the logger to DEBUG only while notify() runs so we
            # also capture the destination's response body (apprise
            # plugins emit that line at DEBUG). _AppriseLogCapture.summary
            # caps the included output, so this doesn't flood the UI.
            apprise_logger.setLevel(logging.DEBUG)
            try:
                apobj = apprise.Apprise()
                apobj.add(self.url)
                sent = apobj.notify(
                    body=message or '',
                    title=title or '',
                    notify_type=self._severity_to_notify_type(apprise, severity),
                )
            except Exception as e:
                apprise_logger.removeHandler(handler)
                apprise_logger.setLevel(prev_level)
                return 0, str(e)
            apprise_logger.removeHandler(handler)
            apprise_logger.setLevel(prev_level)

            if sent:
                return 200, ''

            # `notify` returns False iff every URL endpoint rejected.
            # Surface the warnings the apprise plugin emitted so the
            # operator can see the actual HTTP status / reason.
            detail = handler.summary()
            if not detail:
                detail = 'destination rejected the notification (no detail from apprise)'
            return 500, detail

        result = self._send_with_retry(_send_via_apprise)
        result['channel'] = 'apprise'
        return result

    def test(self) -> Tuple[bool, str]:
        result = self.send(
            title='ProxMenux Monitor — Test',
            message='Apprise channel is configured correctly. If you can read this, the URL is valid and the service accepted the notification.',
            severity='INFO',
        )
        return bool(result.get('success')), result.get('error') or ''


# ─── Channel Factory ─────────────────────────────────────────────

CHANNEL_TYPES = {
    'telegram': {
        'name': 'Telegram',
        'config_keys': ['bot_token', 'chat_id', 'topic_id'],
        'class': TelegramChannel,
    },
    'gotify': {
        'name': 'Gotify',
        'config_keys': ['url', 'token'],
        'class': GotifyChannel,
    },
    'discord': {
        'name': 'Discord',
        'config_keys': ['webhook_url'],
        'class': DiscordChannel,
    },
    'email': {
        'name': 'Email (SMTP)',
        'config_keys': ['host', 'port', 'username', 'password', 'tls_mode',
                        'from_address', 'to_addresses', 'subject_prefix'],
        'class': EmailChannel,
    },
    'apprise': {
        'name': 'Apprise',
        'config_keys': ['url'],
        'class': AppriseChannel,
    },
}


def create_channel(channel_type: str, config: Dict[str, str]) -> Optional[NotificationChannel]:
    """Create a channel instance from type name and config dict.

    Args:
        channel_type: 'telegram', 'gotify', 'discord', 'email', or 'apprise'
        config: Dict with channel-specific keys (see CHANNEL_TYPES)

    Returns:
        Channel instance or None if creation fails
    """
    try:
        if channel_type == 'telegram':
            return TelegramChannel(
                bot_token=config.get('bot_token', ''),
                chat_id=config.get('chat_id', ''),
                topic_id=config.get('topic_id', '')
            )
        elif channel_type == 'gotify':
            return GotifyChannel(
                server_url=config.get('url', ''),
                app_token=config.get('token', '')
            )
        elif channel_type == 'discord':
            return DiscordChannel(
                webhook_url=config.get('webhook_url', '')
            )
        elif channel_type == 'email':
            return EmailChannel(config)
        elif channel_type == 'apprise':
            return AppriseChannel(url=config.get('url', ''))
    except Exception as e:
        print(f"[NotificationChannels] Failed to create {channel_type}: {e}")
    return None
