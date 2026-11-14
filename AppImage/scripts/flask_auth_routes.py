"""
Flask Authentication Routes
Provides REST API endpoints for authentication management
"""

import logging
import logging.handlers
import os
import subprocess
import threading
import time
from collections import defaultdict, deque
from flask import Blueprint, g, jsonify, request
import auth_manager
from jwt_middleware import require_auth, require_admin_scope, permission_error
import jwt
import datetime


# ─── Login rate limiter (audit Tier 3 #21) ───────────────────────────────
#
# Limits failed-login storms even on installations without Fail2Ban. Sliding
# window: 5 attempts per IP per 5 minutes. After the limit, the endpoint
# returns 429 until the oldest attempt ages out of the window. Counts ALL
# /api/auth/login POSTs (we don't know success vs failure until after auth)
# — a legitimate user has ample headroom for typos.
class _LoginRateLimiter:
    def __init__(self, max_attempts=5, window_seconds=300):
        self._max = max_attempts
        self._window = window_seconds
        self._buckets = defaultdict(deque)  # ip -> deque[ts]
        self._lock = threading.Lock()

    def check_and_record(self, ip):
        """Returns (allowed: bool, retry_after_seconds: int)."""
        if not ip:
            ip = "unknown"
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets[ip]
            # Drop stale entries
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                # Reject; advise client when to try again.
                retry = max(1, int(self._window - (now - bucket[0])))
                return False, retry
            bucket.append(now)
            # Bound memory in pathological scans by reaping idle IPs occasionally.
            if len(self._buckets) > 1024:
                stale = [k for k, q in self._buckets.items() if not q or q[-1] < cutoff]
                for k in stale:
                    self._buckets.pop(k, None)
            return True, 0


_login_limiter = _LoginRateLimiter(max_attempts=5, window_seconds=300)

# Dedicated logger for auth failures (Fail2Ban reads this file)
auth_logger = logging.getLogger("proxmenux-auth")
auth_logger.setLevel(logging.WARNING)

# Handler 1: File for Fail2Ban
_auth_file_handler = logging.FileHandler("/var/log/proxmenux-auth.log")
_auth_file_handler.setFormatter(logging.Formatter("%(asctime)s proxmenux-auth: %(message)s"))
auth_logger.addHandler(_auth_file_handler)

# Handler 2: Syslog for JournalWatcher notifications
# This sends to the systemd journal so notification_events.py can detect auth failures
try:
    _auth_syslog_handler = logging.handlers.SysLogHandler(address='/dev/log', facility=logging.handlers.SysLogHandler.LOG_AUTH)
    _auth_syslog_handler.setFormatter(logging.Formatter("proxmenux-auth: %(message)s"))
    _auth_syslog_handler.ident = "proxmenux-auth"
    auth_logger.addHandler(_auth_syslog_handler)
except Exception:
    pass  # Syslog may not be available in all environments


# Only honor XFF when the operator has explicitly opted in via env var.
# Without this, a remote client can send `X-Forwarded-For: 1.2.3.4` to make
# each failed login look like it came from a different IP, defeating the
# Fail2Ban brute-force jail and polluting the auth log used by F2B. See
# audit Tier 3 #20.
_TRUST_PROXY = os.environ.get("PROXMENUX_TRUST_PROXY", "0") == "1"


def _get_client_ip():
    """Get the real client IP. Honors XFF/X-Real-IP only when PROXMENUX_TRUST_PROXY=1."""
    if _TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # First IP in the chain is the real client
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip.strip()
    return request.remote_addr or "unknown"

# Choosing how to reach a Monitor without an account asks for the setup code
# when there is one: the same limit as signing in, and a wrong code is logged
# as an authentication failure, so the Fail2Ban jail covers it too.
_setup_code_limiter = _LoginRateLimiter(max_attempts=5, window_seconds=300)


def _setup_code_error(data):
    """The response refusing a first-run decision without the setup code, or None."""
    if not auth_manager.setup_code_required():
        return None
    client_ip = _get_client_ip()
    allowed, retry_after = _setup_code_limiter.check_and_record(client_ip)
    if not allowed:
        return jsonify({"success": False, "error": "setup_code_rate_limited",
                        "message": "Too many attempts. Please wait and try again.",
                        "retry_after": retry_after}), 429
    if auth_manager.check_setup_code((data or {}).get("setup_code")):
        return None
    auth_logger.warning("authentication failure; rhost=%s user=setup-code", client_ip)
    return jsonify({"success": False, "error": "setup_code_invalid",
                    "message": "The setup code is not valid"}), 403


def _choose_mode(mode, data):
    """Leave the Monitor read-only or open, or let Proxmox VE accounts sign in:
    with an account, its full session decides; without one, the setup code
    when one is required."""
    if mode not in ("read_only", "open", "proxmox"):
        return jsonify({"success": False, "message": "Unknown access mode"}), 400
    if auth_manager.access_mode() in ("password", "proxmox"):
        error = permission_error("admin")
        if error:
            return error
    else:
        error = _setup_code_error(data)
        if error:
            return error
    if mode == "proxmox":
        success, message = auth_manager.set_pve_auth(True)
    else:
        success, message = auth_manager.choose_access_mode(mode)
    if not success:
        return jsonify({"success": False, "message": message}), 500
    auth_manager.consume_setup_code()
    return jsonify({"success": True, "message": message, "access_mode": mode})


def _session_username():
    """The account of the request, as its decorator found it: None without
    one (an open or read-only Monitor)."""
    identity = getattr(g, "identity", None)
    return identity["username"] if identity else None


def _tokens_owner(username, scope):
    """Whose API tokens a session manages: an administrator, every one."""
    profile = auth_manager.profile_for(auth_manager.access_mode(), username, scope)
    return None if profile == "admin" else username


auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Get current authentication status"""
    try:
        status = auth_manager.get_auth_status()

        if status["access_mode"] in ("password", "proxmox"):
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            if token:
                username, scope = auth_manager.verify_token_full(token)
                if username:
                    import pve_auth
                    status['authenticated'] = True
                    status['username'] = username
                    status['auth_method'] = "pve" if pve_auth.is_ticket(token) else "local"
                    profile = auth_manager.profile_for(status["access_mode"], username, scope)
                    status['capabilities'] = auth_manager.capabilities(status["access_mode"], profile=profile)
                    # A custom profile names its choices in the capabilities.
                    status['profile'] = profile.split(":", 1)[0] if profile else None
                    user = auth_manager.find_user(username)
                    status['local_user'] = user is not None
                    status['totp_enabled'] = bool(user and user.get("totp_enabled"))

        return jsonify(status)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------------------------------------------------------
# SSL/HTTPS Certificate Management
# -------------------------------------------------------------------

@auth_bp.route('/api/ssl/status', methods=['GET'])
@require_auth
def ssl_status():
    """Get current SSL configuration status and detect available certificates"""
    try:
        config = auth_manager.load_ssl_config()
        detection = auth_manager.detect_proxmox_certificates()
        
        return jsonify({
            "success": True,
            "ssl_enabled": config.get("enabled", False),
            "source": config.get("source", "none"),
            "cert_path": config.get("cert_path", ""),
            "key_path": config.get("key_path", ""),
            "proxmox_available": detection.get("proxmox_available", False),
            "proxmox_cert": detection.get("proxmox_cert", ""),
            "proxmox_key": detection.get("proxmox_key", ""),
            "cert_info": detection.get("cert_info")
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _schedule_service_restart(delay=1.5):
    """Schedule a restart of the monitor service via systemctl after a short delay.
    This gives time for the HTTP response to reach the client before the process restarts."""
    def _do_restart():
        time.sleep(delay)
        print("[ProxMenux] Restarting monitor service to apply SSL changes...")
        # Use systemctl restart which properly stops and starts the service.
        # This works because systemd manages proxmenux-monitor.service.
        try:
            subprocess.Popen(
                ["systemctl", "restart", "proxmenux-monitor"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[ProxMenux] Failed to restart via systemctl: {e}")
            # Fallback: try to restart the process directly
            os.kill(os.getpid(), 15)  # SIGTERM
    
    t = threading.Thread(target=_do_restart, daemon=True)
    t.start()


@auth_bp.route('/api/ssl/configure', methods=['POST'])
@require_auth
def ssl_configure():
    """Configure SSL with Proxmox or custom certificates"""
    try:
        data = request.json or {}
        source = data.get("source", "proxmox")
        auto_restart = data.get("auto_restart", True)
        
        if source == "proxmox":
            # Sprint 11.8 / Issue #181: prefer the ACME-uploaded cert
            # (pveproxy-ssl.pem) over the self-signed default (pve-ssl.pem)
            # by going through the detector. detect_proxmox_certificates()
            # returns the path PVE itself uses, which is what the user sees
            # in the "Available" status — `ssl_configure` was hard-coding
            # the self-signed default and silently downgrading the cert.
            detection = auth_manager.detect_proxmox_certificates()
            if detection.get("proxmox_available"):
                cert_path = detection.get("proxmox_cert") or auth_manager.PROXMOX_CERT_PATH
                key_path = detection.get("proxmox_key") or auth_manager.PROXMOX_KEY_PATH
            else:
                cert_path = auth_manager.PROXMOX_CERT_PATH
                key_path = auth_manager.PROXMOX_KEY_PATH
        elif source == "custom":
            cert_path = data.get("cert_path", "")
            key_path = data.get("key_path", "")
        else:
            return jsonify({"success": False, "message": "Invalid source. Use 'proxmox' or 'custom'."}), 400
        
        success, message = auth_manager.configure_ssl(cert_path, key_path, source)

        if success:
            # Issue #194 cross-detection: if the user already configured
            # the PVE notifications webhook, the registered URL still
            # points at `http://...`. Re-register it now (before the
            # service restart) so PVE picks up the new https:// scheme
            # the moment Flask comes back up. NO-OP when no webhook is
            # registered yet.
            _refresh_pve_webhook_for_ssl_change()

            if auto_restart:
                _schedule_service_restart()
            return jsonify({
                "success": True,
                "message": "SSL enabled. The service is restarting...",
                "restarting": auto_restart,
                "new_protocol": "https"
            })
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/ssl/disable', methods=['POST'])
@require_auth
def ssl_disable():
    """Disable SSL and return to HTTP"""
    try:
        data = request.json or {}
        auto_restart = data.get("auto_restart", True)

        success, message = auth_manager.disable_ssl()

        if success:
            # Same cross-detection as `ssl_configure`: rewrite the PVE
            # webhook URL back to http:// so PVE doesn't keep posting
            # to an https:// endpoint that no longer answers.
            _refresh_pve_webhook_for_ssl_change()

            if auto_restart:
                _schedule_service_restart()
            return jsonify({
                "success": True,
                "message": "SSL disabled. The service is restarting...",
                "restarting": auto_restart,
                "new_protocol": "http"
            })
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/ssl/reload', methods=['POST'])
@require_auth
def ssl_reload():
    """Reload the configured certificate without restarting the Monitor."""
    config = auth_manager.load_ssl_config()
    if not config.get("enabled"):
        return jsonify({
            "success": False,
            "code": "ssl_not_enabled",
            "message": "HTTPS is not enabled",
        }), 400

    source = config.get("source", "custom")
    cert_info = None
    if source == "proxmox":
        detection = auth_manager.detect_proxmox_certificates()
        if not detection.get("proxmox_available"):
            return jsonify({
                "success": False,
                "code": "certificate_unavailable",
                "message": "No Proxmox certificate was detected",
            }), 404
        cert_path = detection.get("proxmox_cert", "")
        key_path = detection.get("proxmox_key", "")
        cert_info = detection.get("cert_info")
    else:
        cert_path = config.get("cert_path", "")
        key_path = config.get("key_path", "")

    valid, validation_message = auth_manager.validate_certificate_files(cert_path, key_path)
    if not valid:
        return jsonify({
            "success": False,
            "code": "certificate_invalid",
            "message": validation_message,
        }), 400

    paths_changed = (
        cert_path != config.get("cert_path", "") or
        key_path != config.get("key_path", "")
    )
    if paths_changed:
        updated_config = dict(config)
        updated_config["cert_path"] = cert_path
        updated_config["key_path"] = key_path
        if not auth_manager.save_ssl_config(updated_config):
            return jsonify({
                "success": False,
                "code": "config_save_failed",
                "message": "Failed to save the renewed certificate paths",
            }), 500

    try:
        changed = auth_manager.reload_server_ssl_context(cert_path, key_path)
    except Exception as e:
        if paths_changed:
            auth_manager.save_ssl_config(config)
        return jsonify({
            "success": False,
            "code": "runtime_reload_failed",
            "message": str(e),
        }), 409

    return jsonify({
        "success": True,
        "changed": changed,
        "cert_path": cert_path,
        "key_path": key_path,
        "cert_info": cert_info,
    })


def _refresh_pve_webhook_for_ssl_change():
    """Helper used by both `ssl_configure` and `ssl_disable`.

    Wraps the deferred import and the try/except so an unrelated
    notifications-stack hiccup never fails the SSL toggle itself.
    Logs but doesn't raise on any error path.
    """
    try:
        from flask_notification_routes import refresh_pve_webhook_url_if_registered
        result = refresh_pve_webhook_url_if_registered()
        if result.get('skipped'):
            return  # Nothing to do — no webhook registered yet.
        if result.get('error'):
            print(f"[ssl] webhook refresh after SSL change had a non-fatal "
                  f"error: {result['error']}")
    except Exception as e:
        print(f"[ssl] failed to refresh PVE webhook after SSL change: {e}")


@auth_bp.route('/api/ssl/validate', methods=['POST'])
@require_auth
def ssl_validate():
    """Validate custom certificate and key file paths"""
    try:
        data = request.json or {}
        cert_path = data.get("cert_path", "")
        key_path = data.get("key_path", "")
        
        valid, message = auth_manager.validate_certificate_files(cert_path, key_path)
        
        return jsonify({"success": valid, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



@auth_bp.route('/api/auth/decline', methods=['POST'])
def auth_decline():
    """Decline authentication setup.

    Reachable without auth so a fresh install can opt out before any user is
    created — but ONCE auth has been configured, this endpoint must reject:
    otherwise an unauth attacker can `decline` post-setup and turn off the
    requirement to authenticate. See audit Tier 1 #5.
    """
    try:
        if auth_manager.access_mode() != "undecided":
            return jsonify({
                "success": False,
                "message": "Authentication is already configured; cannot decline."
            }), 403
        return _choose_mode("open", request.get_json(silent=True))
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Authenticate user and return JWT token"""
    try:
        # Application-level rate limit (5 tries per IP per 5 min). Hits BEFORE
        # auth so the cost of the attempt — bcrypt-equivalent password check
        # plus DB read — isn't paid by the attacker. Audit Tier 3 #21.
        client_ip = _get_client_ip()
        allowed, retry_after = _login_limiter.check_and_record(client_ip)
        if not allowed:
            auth_logger.warning(
                "login rate limit exceeded; rhost=%s retry_after=%ds",
                client_ip, retry_after,
            )
            return jsonify({
                "success": False,
                "message": "Too many login attempts. Please wait and try again.",
                "retry_after": retry_after,
            }), 429

        data = request.json
        username = data.get('username')
        password = data.get('password')
        totp_token = data.get('totp_token')  # Optional 2FA token

        success, token, requires_totp, message = auth_manager.authenticate(username, password, totp_token)
        
        if success:
            return jsonify({"success": True, "token": token, "message": message})
        elif requires_totp:
            # First step: password OK, requesting TOTP code (not a failure)
            return jsonify({"success": False, "requires_totp": True, "message": message}), 200
        else:
            # Authentication failure (wrong password or wrong TOTP code).
            # `client_ip` was already resolved at the top for rate-limiting.
            auth_logger.warning(
                "authentication failure; rhost=%s user=%s",
                client_ip, username or "unknown"
            )
            # If user submitted a TOTP token that was wrong, tell frontend
            # to keep showing the TOTP field (not go back to password step)
            is_totp_failure = totp_token and "2FA" in message
            return jsonify({
                "success": False,
                "message": message,
                "requires_totp": is_totp_failure
            }), 401
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/setup', methods=['POST'])
def auth_setup():
    """Set up authentication with username and password (create user + enable auth)"""
    try:
        data = request.get_json(silent=True) or {}
        username = data.get('username')
        password = data.get('password')

        mode = auth_manager.access_mode()
        if mode == "proxmox":
            # Proxmox VE accounts sign in here: only an administrator adds a local one.
            error = permission_error("admin")
            if error:
                return error
        elif mode != "password":
            error = _setup_code_error(data)
            if error:
                return error

        success, message = auth_manager.setup_auth(username, password)

        if success:
            auth_manager.consume_setup_code()
            # Generate a token so the user is logged in immediately
            token = auth_manager.generate_token(username)
            return jsonify({"success": True, "token": token, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/enable', methods=['POST'])
@require_admin_scope
def auth_enable():
    """Enable authentication (must already be configured)"""
    try:
        success, message = auth_manager.enable_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/disable', methods=['POST'])
@require_admin_scope
def auth_disable():
    """Disable authentication

    Guarded by require_admin_scope: turning auth off is an administrative
    action, so a read-only API token must not reach it. The decorator
    validates the token and its full_admin scope before the body runs.
    """
    try:
        mode = (request.get_json(silent=True) or {}).get("mode") or "read_only"
        success, message = auth_manager.disable_auth(mode)
        
        if success:
            return jsonify({"success": True, "message": message, "access_mode": mode})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@require_auth
def auth_change_password():
    """Change authentication password.

    Accepts an optional `totp_code` in the JSON body. When the account has
    2FA enabled, that code is mandatory — see auth_manager.change_password.
    """
    try:
        data = request.json or {}
        # `old_password` is the canonical API field. Accept the original
        # frontend name as a compatibility alias so an already-open browser
        # tab can still complete the request after a Monitor update.
        old_password = data.get('old_password')
        if old_password is None:
            old_password = data.get('current_password')
        new_password = data.get('new_password')
        totp_code = data.get('totp_code')

        if not isinstance(old_password, str) or not isinstance(new_password, str):
            return jsonify({
                "success": False,
                "message": "Current password and new password are required",
            }), 400
        if totp_code is not None and not isinstance(totp_code, str):
            return jsonify({
                "success": False,
                "message": "Invalid 2FA code",
            }), 400

        success, message = auth_manager.change_password(_session_username(), old_password, new_password, totp_code)

        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ── Proxmox VE accounts ──────────────────────────────────────────────
# The ticket stays the session: these routes only obtain, read or renew it
# from the local Proxmox VE API. See pve_auth.py.

def _pve_enabled():
    return bool(auth_manager.load_auth_config().get("pve_auth"))


def _pve_answer(result):
    response = jsonify({"success": True, **result})
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.route('/api/auth/pve/realms', methods=['GET'])
def pve_realms():
    import pve_auth
    if not _pve_enabled():
        return jsonify({"enabled": False, "realms": []})
    return jsonify({"enabled": True, "realms": pve_auth.realms()})


@auth_bp.route('/api/auth/pve/login', methods=['POST'])
def pve_login():
    """Sign in with a Proxmox VE account: the user, password and realm, then
    the second factor when Proxmox VE asks for one."""
    import pve_auth
    if not _pve_enabled():
        return jsonify({"success": False, "message": "Proxmox VE accounts are not enabled"}), 404
    client_ip = _get_client_ip()
    allowed, retry_after = _login_limiter.check_and_record(client_ip)
    if not allowed:
        return jsonify({"success": False, "message": "Too many login attempts. Please wait and try again.",
                        "retry_after": retry_after}), 429
    data = request.get_json(silent=True) or {}
    try:
        if data.get("challenge"):
            result = pve_auth.second_factor(data.get("username"), data.get("challenge"), data.get("code"))
        else:
            result = pve_auth.login(data.get("username"), data.get("password"), data.get("realm"))
    except pve_auth.PVEAuthError as exc:
        auth_logger.warning("authentication failure; rhost=%s user=%s", client_ip,
                            str(data.get("username") or "unknown")[:80])
        return jsonify({"success": False, "message": str(exc)}), 401
    return _pve_answer(result)


@auth_bp.route('/api/auth/pve/session', methods=['GET'])
def pve_session():
    """The Proxmox VE session of this browser: the cookie the Proxmox VE web
    interface keeps for this host reaches the Monitor when both are opened over
    HTTPS by the same name."""
    import pve_auth
    ticket = request.cookies.get("PVEAuthCookie", "")
    if not _pve_enabled() or not ticket:
        return jsonify({"success": False}), 404
    username, scope = pve_auth.validate(ticket)
    if not username:
        return jsonify({"success": False}), 401
    return _pve_answer({"ticket": ticket, "username": username, "scope": scope})


@auth_bp.route('/api/auth/pve/renew', methods=['POST'])
def pve_renew():
    """A fresh ticket for the one in use, before it expires."""
    import pve_auth
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not _pve_enabled() or not pve_auth.is_ticket(token):
        return jsonify({"success": False}), 401
    try:
        return _pve_answer(pve_auth.renew(token))
    except pve_auth.PVEAuthError:
        return jsonify({"success": False}), 401


@auth_bp.route('/api/auth/pve/config', methods=['PUT'])
@require_admin_scope
def pve_config():
    """Let Proxmox VE accounts sign in next to the local account, or not."""
    enabled = (request.get_json(silent=True) or {}).get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"success": False, "message": "An enabled flag is required"}), 400
    success, message = auth_manager.set_pve_auth(enabled)
    return jsonify({"success": success, "message": message}), (200 if success else 409)


@auth_bp.route('/api/auth/mode', methods=['POST'])
def auth_mode():
    """Choose how the Monitor is reached without an account: read-only or open."""
    try:
        data = request.get_json(silent=True) or {}
        return _choose_mode(data.get("mode"), data)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/skip', methods=['POST'])
def auth_skip():
    """Skip authentication setup (same as decline).

    Same hardening as /api/auth/decline: once auth is configured, this is
    locked. See audit Tier 1 #5.
    """
    try:
        if auth_manager.access_mode() != "undecided":
            return jsonify({
                "success": False,
                "message": "Authentication is already configured; cannot skip."
            }), 403
        return _choose_mode("open", request.get_json(silent=True))
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/totp/setup', methods=['POST'])
def totp_setup():
    """Initialize TOTP setup for a user"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username, scope = auth_manager.verify_token_full(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if scope != 'full_admin':
            return jsonify({"success": False, "message": "This action requires a full_admin token"}), 403
        
        success, secret, qr_code, backup_codes, message = auth_manager.setup_totp(username)
        
        if success:
            return jsonify({
                "success": True,
                "secret": secret,
                "qr_code": qr_code,
                "backup_codes": backup_codes,
                "message": message
            })
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/totp/enable', methods=['POST'])
def totp_enable():
    """Enable TOTP after verification"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username, scope = auth_manager.verify_token_full(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if scope != 'full_admin':
            return jsonify({"success": False, "message": "This action requires a full_admin token"}), 403
        
        data = request.json
        verification_token = data.get('token')
        
        if not verification_token:
            return jsonify({"success": False, "message": "Verification token required"}), 400
        
        success, message = auth_manager.enable_totp(username, verification_token)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/totp/disable', methods=['POST'])
def totp_disable():
    """Disable TOTP (requires password confirmation)"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username, scope = auth_manager.verify_token_full(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if scope != 'full_admin':
            return jsonify({"success": False, "message": "This action requires a full_admin token"}), 403
        
        data = request.json or {}
        password = data.get('password')
        totp_code = data.get('totp_code')

        if not password:
            return jsonify({"success": False, "message": "Password required"}), 400

        success, message = auth_manager.disable_totp(username, password, totp_code)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/generate-api-token', methods=['POST'])
def generate_api_token():
    """Generate a long-lived API token for external integrations (Homepage, Home Assistant, etc.)"""
    try:
        # API tokens are scoped to a real authenticated user. Without
        # auth configured there is no user to attach the token to —
        # surface that as a 400 with a clear message rather than 401,
        # so the UI can show "configure auth first" instead of bouncing
        # the user to a login page that doesn't exist yet.
        config = auth_manager.load_auth_config()
        if not config.get("enabled", False) or config.get("declined", False):
            return jsonify({"success": False, "message": "Authentication must be configured before generating API tokens"}), 400

        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '')

        if not token:
            return jsonify({"success": False, "message": "Unauthorized. Please log in first."}), 401
        
        username, scope = auth_manager.verify_token_full(token)
        
        if not username:
            return jsonify({"success": False, "message": "Invalid or expired session. Please log in again."}), 401
        if scope != 'full_admin':
            return jsonify({"success": False, "message": "This action requires a full_admin token"}), 403
        
        data = request.json
        password = data.get('password')
        totp_token = data.get('totp_token')  # Optional 2FA token
        token_name = data.get('token_name', 'API Token')  # Optional token description
        # `scope` narrows what the token can do. Defaults to `read_only` —
        # which is the safe choice for the most common integration cases
        # (Homepage / Home Assistant dashboards just read metrics). Caller
        # can opt into `full_admin` explicitly. Audit Tier 6 — Tokens API
        # JWT 365 días sin scope.
        scope = data.get('scope', 'read_only')
        if scope not in ('read_only', 'full_admin'):
            return jsonify({"success": False, "message": "Invalid scope (read_only|full_admin)"}), 400

        if not password:
            return jsonify({"success": False, "message": "Password is required"}), 400
        
        # Authenticate user with password and optional 2FA
        success, _, requires_totp, message = auth_manager.authenticate(username, password, totp_token)
        
        if success:
            # Generate a long-lived token (1 year expiration)
            # `auth_manager.JWT_SECRET` (capitalised constant) was removed when
            # the per-install secret moved into `auth.json`; the helper
            # `_get_jwt_secret()` is the public way to read it. Without this
            # call the route AttributeError'd on every API-token generation.
            # iss/aud match the values the verifier expects in Sprint 10E.
            api_token = jwt.encode({
                'username': username,
                'uid': auth_manager.find_user(username)['uid'],
                'token_name': token_name,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=365),
                'iat': datetime.datetime.utcnow(),
                'iss': auth_manager.JWT_ISSUER,
                'aud': auth_manager.JWT_AUDIENCE,
                'scope': scope,
            }, auth_manager._get_jwt_secret(), algorithm='HS256')
            
            # Store token metadata for listing and revocation
            auth_manager.store_api_token_metadata(api_token, token_name, scope=scope, owner=username)
            
            return jsonify({
                "success": True, 
                "token": api_token,
                "token_name": token_name,
                "expires_in": "365 days",
                "message": "API token generated successfully. Store this token securely, it will not be shown again."
            })
        elif requires_totp:
            return jsonify({"success": False, "requires_totp": True, "message": message}), 200
        else:
            return jsonify({"success": False, "message": message}), 401
    except Exception as e:
        print(f"[ERROR] generate_api_token: {str(e)}")  # Log error for debugging
        return jsonify({"success": False, "message": f"Internal error: {str(e)}"}), 500


@auth_bp.route('/api/auth/api-tokens', methods=['GET'])
def list_api_tokens():
    """List all generated API tokens (metadata only, no actual token values).

    When auth is not configured (fresh install) or has been declined, no
    tokens can exist and the endpoint should return an empty list instead
    of 401. Returning 401 here trips the frontend's `fetchApi` redirect
    to `/`, which silently boots the user out of the Security page on
    any host without auth set up — see bug reported 2026-05-07.
    """
    try:
        config = auth_manager.load_auth_config()
        if not config.get("enabled", False) or config.get("declined", False):
            return jsonify({"success": True, "tokens": []})

        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username, scope = auth_manager.verify_token_full(token) if token else (None, None)
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        tokens = auth_manager.list_api_tokens(owner=_tokens_owner(username, scope))
        return jsonify({"success": True, "tokens": tokens})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/api-tokens/<token_id>', methods=['DELETE'])
def revoke_api_token_route(token_id):
    """Revoke an API token by its ID."""
    try:
        config = auth_manager.load_auth_config()
        # Without configured auth there are no tokens to revoke; surface
        # that as a clean 400 instead of an unhelpful 401.
        if not config.get("enabled", False) or config.get("declined", False):
            return jsonify({"success": False, "message": "Authentication is not configured"}), 400

        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username, scope = auth_manager.verify_token_full(token) if token else (None, None)
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if scope != 'full_admin':
            return jsonify({"success": False, "message": "This action requires a full_admin token"}), 403

        success, message = auth_manager.revoke_api_token(token_id, owner=_tokens_owner(username, scope))

        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# User profile endpoints (Fase 2, v1.2.2)
# ---------------------------------------------------------------------------
#
# GET    /api/auth/profile          → username + display_name + has_avatar
# PUT    /api/auth/profile          → update display_name (body: {display_name})
# GET    /api/auth/profile/avatar   → serve the avatar bytes (image/*)
# POST   /api/auth/profile/avatar   → upload new avatar (multipart 'file')
# DELETE /api/auth/profile/avatar   → remove the stored avatar
#
# All four require auth via @require_auth. The avatar GET also requires
# auth because the file lives next to the auth state on disk and we
# don't want it leaked to arbitrary callers — the avatar URL is meant
# to be fetched by an already-authenticated session.


@auth_bp.route('/api/auth/profile', methods=['GET'])
@require_auth
def get_profile():
    """Return the active user's profile (username + display name + avatar
    metadata). Falls back to None values when auth isn't configured."""
    try:
        profile = auth_manager.get_user_profile(_session_username())
        return jsonify({
            "success": True,
            **profile,
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/profile', methods=['PUT'])
@require_auth
def update_profile():
    """Update display_name. Body: {"display_name": "..."}. Empty string
    clears it (the dropdown then renders the raw username)."""
    try:
        data = request.get_json(silent=True) or {}
        if "display_name" not in data:
            return jsonify({
                "success": False,
                "message": "Missing 'display_name' field",
            }), 400
        ok, message = auth_manager.set_display_name(data.get("display_name") or "", _session_username())
        if not ok:
            return jsonify({"success": False, "message": message}), 400
        # Return the fresh profile so the frontend can update without a
        # second roundtrip.
        return jsonify({"success": True, "message": message, **auth_manager.get_user_profile(_session_username())})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/profile/avatar', methods=['GET'])
@require_auth
def get_avatar():
    """Serve the stored avatar bytes. Returns 404 if no avatar set."""
    try:
        from flask import Response
        data, content_type = auth_manager.get_avatar_bytes(_session_username())
        if data is None:
            return jsonify({"success": False, "message": "No avatar set"}), 404
        return Response(
            data,
            mimetype=content_type,
            headers={
                # Allow short-window caching keyed by the URL — the
                # frontend appends `?v=<mtime>` so any update busts the
                # cache automatically.
                "Cache-Control": "private, max-age=60",
            },
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/profile/avatar', methods=['POST'])
@require_auth
def upload_avatar():
    """Upload a new avatar image. Accepts either:
      • multipart/form-data with a `file` field (preferred), or
      • a raw image body with Content-Type set to image/png|jpeg|webp|gif.
    The size cap (2 MB) and the magic-number sniff happen in
    auth_manager.save_avatar — failures come back as 400 with a
    human-readable message."""
    try:
        content_bytes = None
        content_type = None

        # Multipart path
        if request.files:
            file_storage = request.files.get("file")
            if file_storage is not None:
                content_bytes = file_storage.read()
                content_type = (file_storage.mimetype or "").lower()

        # Raw body fallback
        if content_bytes is None:
            content_bytes = request.get_data(cache=False)
            content_type = (request.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()

        if not content_bytes:
            return jsonify({"success": False, "message": "No image data received"}), 400

        ok, message = auth_manager.save_avatar(content_bytes, content_type, _session_username())
        if not ok:
            return jsonify({"success": False, "message": message}), 400
        return jsonify({"success": True, "message": message, **auth_manager.get_user_profile(_session_username())})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/profile/avatar', methods=['DELETE'])
@require_auth
def remove_avatar():
    """Remove the stored avatar (no-op if none set)."""
    try:
        ok, message = auth_manager.delete_avatar(_session_username())
        if not ok:
            return jsonify({"success": False, "message": message}), 400
        return jsonify({"success": True, "message": message, **auth_manager.get_user_profile(_session_username())})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Local users: an administrator adds them, chooses their profile, sets a new
# password or removes a lost second factor. The Monitor always keeps one
# administrator. See auth_manager (local accounts) and permissions.py.
# ---------------------------------------------------------------------------

_USER_ERRORS = {
    "The username can have up to 32 letters, digits, dots, dashes and underscores": "username_invalid",
    "That username is already in use": "username_taken",
    "Unknown profile": "profile_unknown",
    "Choose at least one area, and only the listed areas and actions": "custom_invalid",
    "The Monitor needs at least one administrator": "last_admin",
    "User not found": "user_not_found",
    "You cannot remove your own account": "remove_self",
    "Password must be at least 10 characters": "password_short",
    "Password must mix at least 3 of: lowercase, uppercase, digits, symbols": "password_mix",
    "That password is in the common-passwords list — pick something else": "password_common",
}


def _answer(result, status=400):
    success, message = result
    if success:
        return jsonify({"success": True, "message": message, "users": auth_manager.list_users()})
    # A known refusal has a code the interface translates; any other, such
    # as a weak password, is shown as it is.
    return jsonify({"success": False, "message": message,
                    "error": _USER_ERRORS.get(message, "user_change_failed")}), status


@auth_bp.route('/api/auth/users', methods=['GET'])
@require_admin_scope
def users_list():
    return jsonify({"success": True, "users": auth_manager.list_users(),
                    "profiles": list(auth_manager.permissions.PROFILES) + [auth_manager.permissions.CUSTOM],
                    "areas": list(auth_manager.permissions.AREAS),
                    "custom_actions": list(auth_manager.permissions.CUSTOM_ACTIONS)})


@auth_bp.route('/api/auth/users', methods=['POST'])
@require_admin_scope
def users_create():
    data = request.get_json(silent=True) or {}
    return _answer(auth_manager.create_user(data.get("username"), data.get("password"),
                                            data.get("profile"), custom=data.get("custom")))


@auth_bp.route('/api/auth/users/<username>', methods=['PUT'])
@require_admin_scope
def users_update(username):
    data = request.get_json(silent=True) or {}
    return _answer(auth_manager.update_user(username, profile=data.get("profile"),
                                            password=data.get("password"),
                                            reset_totp=data.get("reset_totp") is True,
                                            custom=data.get("custom")),
                   404 if not auth_manager.find_user(username) else 400)


@auth_bp.route('/api/auth/users/<username>', methods=['DELETE'])
@require_admin_scope
def users_delete(username):
    if username == _session_username():
        return _answer((False, "You cannot remove your own account"))
    return _answer(auth_manager.delete_user(username),
                   404 if not auth_manager.find_user(username) else 400)
