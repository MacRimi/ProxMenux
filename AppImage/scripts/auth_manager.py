"""
Authentication Manager Module
Handles all authentication-related operations including:
- Loading/saving auth configuration
- Password hashing and verification
- JWT token generation and validation
- Auth status checking
- Two-Factor Authentication (2FA/TOTP)
"""

import os
import json
import hashlib
import hmac
import secrets
import base64
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    print("Warning: PyJWT not available. Authentication features will be limited.")

try:
    import pyotp
    import segno
    import io
    import base64
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    print("Warning: pyotp/segno not available. 2FA features will be disabled.")

# Configuration
CONFIG_DIR = Path.home() / ".config" / "proxmenux-monitor"
AUTH_CONFIG_FILE = CONFIG_DIR / "auth.json"
# Sentinel for legacy installs that started under the hardcoded JWT_SECRET.
# The audit (Tier 4 #22) flagged that constant — anyone with access to the
# public repo could forge JWTs against any deployment. We now generate a
# random per-install secret on first use and persist it in auth.json. Tokens
# issued under the legacy secret stop verifying once the migration runs;
# users have to log in once. That's intentional and accepted by the audit.
_LEGACY_JWT_SECRET = "proxmenux-monitor-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRATION_HOURS = 24
# Audit Tier 5: bind tokens to issuer/audience so they can't be cross-used
# against another deployment / service that happens to share the same
# JWT_SECRET. Verified in `verify_token` with a permissive fallback for
# tokens issued before the rollout.
JWT_ISSUER = "proxmenux-monitor"
JWT_AUDIENCE = "api"

# Password-hashing format: pbkdf2_sha256 with 600k iterations (OWASP 2023+
# baseline). Uses only stdlib (`hashlib.pbkdf2_hmac`), no external deps.
# Format on disk: "pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>".
# Legacy SHA-256 (single-line 64 hex chars) is still recognized for one final
# verify and re-hashed on the next successful login (lazy migration).
_PWD_PBKDF2_ITERS = 600000
_PWD_PBKDF2_PREFIX = "pbkdf2_sha256$"


def ensure_config_dir():
    """Ensure the configuration directory exists"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_auth_config():
    """
    Load authentication configuration from file
    Returns dict with structure:
    {
        "enabled": bool,
        "username": str,
        "password_hash": str,
        "declined": bool,
        "configured": bool,
        "totp_enabled": bool,  # 2FA enabled flag
        "totp_secret": str,    # TOTP secret key
        "backup_codes": list,  # List of backup codes
        "api_tokens": list,    # List of stored API token metadata
        "revoked_tokens": list # List of revoked token hashes
    }
    """
    if not AUTH_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "username": None,
            "password_hash": None,
            "declined": False,
            "configured": False,
            "totp_enabled": False,
            "totp_secret": None,
            "backup_codes": [],
            "api_tokens": [],
            "revoked_tokens": []
        }
    
    try:
        with open(AUTH_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Ensure all required fields exist
            config.setdefault("declined", False)
            config.setdefault("configured", config.get("enabled", False) or config.get("declined", False))
            config.setdefault("totp_enabled", False)
            config.setdefault("totp_secret", None)
            config.setdefault("backup_codes", [])
            config.setdefault("api_tokens", [])
            config.setdefault("revoked_tokens", [])
            return config
    except Exception as e:
        print(f"Error loading auth config: {e}")
        return {
            "enabled": False,
            "username": None,
            "password_hash": None,
            "declined": False,
            "configured": False,
            "totp_enabled": False,
            "totp_secret": None,
            "backup_codes": [],
            "api_tokens": [],
            "revoked_tokens": []
        }


def save_auth_config(config):
    """Save authentication configuration to file"""
    ensure_config_dir()
    try:
        with open(AUTH_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving auth config: {e}")
        return False


def _get_jwt_secret():
    """Return the per-install JWT signing secret, generating one on first use.

    The secret lives in `auth.json` under the `jwt_secret` key. On a fresh
    install or when migrating from the legacy hardcoded constant, we mint
    a new `secrets.token_urlsafe(32)`-derived value and persist it. Once
    persisted it never changes (rotation would log out every active session).
    Audit Tier 4 #22.
    """
    config = load_auth_config()
    sec = config.get("jwt_secret")
    if isinstance(sec, str) and len(sec) >= 32:
        _audit_api_tokens_against_jwt_secret(sec)
        return sec
    new_secret = secrets.token_urlsafe(48)
    config["jwt_secret"] = new_secret
    save_auth_config(config)
    _audit_api_tokens_against_jwt_secret(new_secret)
    return new_secret


# One-shot startup audit: warn the operator (in journal) when stored
# api_tokens were minted under a previous jwt_secret. Those tokens
# remain in `api_tokens` metadata but their JWTs no longer verify, so
# the user's HTTP client (Home Assistant, custom script, …) gets a 401
# while the token "looks valid" in the UI. We log once per process to
# make the failure mode searchable in journalctl without spamming.
_TOKEN_AUDIT_DONE = False
_TOKEN_AUDIT_LOCK = threading.Lock()


def _audit_api_tokens_against_jwt_secret(current_secret: str) -> None:
    """One-time warning when stored api_tokens were signed under a
    previous jwt_secret. Cheap: returns immediately after the first
    successful run. Logs to stdout/stderr so the message lands in the
    Monitor's journalctl output.
    """
    global _TOKEN_AUDIT_DONE
    with _TOKEN_AUDIT_LOCK:
        if _TOKEN_AUDIT_DONE:
            return
        _TOKEN_AUDIT_DONE = True

    try:
        config = load_auth_config()
        tokens = config.get("api_tokens", [])
        if not tokens:
            return
        current_fp = hashlib.sha256(current_secret.encode()).hexdigest()[:16]
        stale = [t for t in tokens
                 if t.get("signed_with") is not None
                 and t.get("signed_with") != current_fp]
        legacy = [t for t in tokens if t.get("signed_with") is None]
        if stale:
            ids = ", ".join(t.get("id", "?") for t in stale)
            print(f"[ProxMenux][auth] WARNING: {len(stale)} API token(s) "
                  f"signed with a previous jwt_secret — they will return "
                  f"401 'Invalid or expired token'. Revoke and regenerate "
                  f"from Settings → API Tokens. Affected IDs: {ids}")
        if legacy:
            ids = ", ".join(t.get("id", "?") for t in legacy)
            print(f"[ProxMenux][auth] NOTE: {len(legacy)} API token(s) "
                  f"have no signing-secret fingerprint (created before "
                  f"the tracking field was added). Their validity can "
                  f"only be confirmed by an actual auth attempt. "
                  f"Legacy IDs: {ids}")
    except Exception as e:
        # Audit is best-effort — failure must never break startup.
        print(f"[ProxMenux][auth] token audit skipped: {e}")


# Server-side mirror of the frontend's `validatePasswordStrength`. Defense
# in depth: the UI enforces these rules but a direct API caller (curl,
# scripted setup, custom client) bypasses the JS — so the same minimum has
# to be enforced here. Audit Tier 6 — Política de password débil.
_OBVIOUS_PASSWORDS = {
    "password", "password1", "password123",
    "12345678", "123456789", "1234567890",
    "qwerty", "qwertyuiop", "letmein", "welcome",
    "admin", "administrator", "root", "proxmox", "proxmenux",
    "changeme", "abcdefgh",
}


def _validate_password_strength(pw):
    """Return None if `pw` passes policy, otherwise a human-readable reason."""
    if not isinstance(pw, str) or len(pw) < 10:
        return "Password must be at least 10 characters"
    categories = sum([
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ])
    if categories < 3:
        return "Password must mix at least 3 of: lowercase, uppercase, digits, symbols"
    if pw.lower() in _OBVIOUS_PASSWORDS:
        return "That password is in the common-passwords list — pick something else"
    return None


def hash_password(password):
    """Hash a password with PBKDF2-HMAC-SHA256.

    Format: `pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>`. Per-password 16-byte
    random salt; 600k iterations (OWASP 2023+ baseline). Stdlib only — no
    bcrypt / argon2-cffi dependency added to the AppImage build. See audit
    Tier 4 #23.
    """
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, _PWD_PBKDF2_ITERS, dklen=32)
    return (
        f"{_PWD_PBKDF2_PREFIX}{_PWD_PBKDF2_ITERS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(derived).decode('ascii')}"
    )


def _verify_pbkdf2(password, stored):
    """Verify a PBKDF2 hash. Returns True on match, False on any failure."""
    try:
        # `pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>`
        body = stored[len(_PWD_PBKDF2_PREFIX):]
        iters_str, salt_b64, hash_b64 = body.split('$', 2)
        iters = int(iters_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iters, dklen=len(expected))
    return hmac.compare_digest(derived, expected)


def _is_legacy_sha256(stored):
    """True if `stored` looks like the old unsalted SHA-256 hex digest."""
    if not isinstance(stored, str):
        return False
    if len(stored) != 64:
        return False
    return all(c in '0123456789abcdef' for c in stored.lower())


def verify_password(password, password_hash):
    """Verify a password against its hash.

    Recognizes both the new PBKDF2 format and the legacy unsalted SHA-256.
    The legacy path is kept around for one final verify so existing accounts
    can log in once and trigger a rehash via `_maybe_rehash_password` —
    see lazy migration in `authenticate()`.
    """
    if not isinstance(password_hash, str) or not password_hash:
        return False
    if password_hash.startswith(_PWD_PBKDF2_PREFIX):
        return _verify_pbkdf2(password, password_hash)
    if _is_legacy_sha256(password_hash):
        legacy = hashlib.sha256(password.encode('utf-8')).hexdigest()
        return hmac.compare_digest(legacy, password_hash)
    return False


def _maybe_rehash_password(password, current_hash):
    """If the stored hash is legacy SHA-256, return a fresh PBKDF2 hash to persist.

    Returns None when no rehash is needed (already PBKDF2 or unrecognized).
    Caller is responsible for saving the new hash back to auth.json.
    """
    if _is_legacy_sha256(current_hash):
        return hash_password(password)
    return None


def generate_token(username):
    """Generate a JWT token for the given username"""
    if not JWT_AVAILABLE:
        return None

    payload = {
        'username': username,
        'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS),
        'iat': datetime.utcnow(),
        'iss': JWT_ISSUER,
        'aud': JWT_AUDIENCE,
    }

    try:
        token = jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)
        return token
    except Exception as e:
        print(f"Error generating token: {e}")
        return None


# In-memory cache for revoked_tokens to avoid hitting disk on every request.
# Invalidated by both TTL and the auth.json mtime so a revocation from another
# process/restart still propagates within seconds.
_REVOKED_CACHE = {'set': None, 'mtime': 0.0, 'fetched_at': 0.0}
_REVOKED_TTL = 30.0


def _get_revoked_tokens_cached():
    """Return a frozenset of revoked-token hashes, cached for ~30s."""
    import time
    now = time.monotonic()
    try:
        mtime = AUTH_CONFIG_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0
    if (
        _REVOKED_CACHE['set'] is not None
        and now - _REVOKED_CACHE['fetched_at'] < _REVOKED_TTL
        and mtime == _REVOKED_CACHE['mtime']
    ):
        return _REVOKED_CACHE['set']
    config = load_auth_config()
    revoked = frozenset(config.get("revoked_tokens", []))
    _REVOKED_CACHE['set'] = revoked
    _REVOKED_CACHE['mtime'] = mtime
    _REVOKED_CACHE['fetched_at'] = now
    return revoked


def _invalidate_revoked_cache():
    """Force a re-read on the next verify_token call."""
    _REVOKED_CACHE['set'] = None


def verify_token_full(token):
    """Like `verify_token` but also returns the `scope` claim.

    Returns `(username, scope)` on success, `(None, None)` otherwise.
    Tokens issued before scope was added (no claim) get `'full_admin'`
    so legacy sessions keep working unchanged. Audit Tier 6 — Tokens
    API JWT 365 días sin scope.
    """
    if not JWT_AVAILABLE or not token:
        return None, None
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if token_hash in _get_revoked_tokens_cached():
            return None, None
        try:
            payload = jwt.decode(
                token, _get_jwt_secret(),
                algorithms=[JWT_ALGORITHM],
                audience=JWT_AUDIENCE, issuer=JWT_ISSUER,
            )
        except (jwt.MissingRequiredClaimError, jwt.InvalidAudienceError, jwt.InvalidIssuerError):
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return payload.get('username'), payload.get('scope', 'full_admin')
    except jwt.ExpiredSignatureError:
        return None, None
    except jwt.InvalidTokenError:
        return None, None


_AUTH_LOG_RATE = {'last_ts': 0.0, 'suppressed': 0, 'last_msg': ''}
_AUTH_LOG_LOCK = threading.Lock()


def _log_auth_failure_throttled(msg):
    """Log a JWT verification failure at most once every 30 seconds.

    A browser whose token was invalidated by a jwt_secret rotation can
    fire dozens of authenticated requests per page load (SWR fetches +
    WebSocket reconnects); without throttling this floods the journal
    with hundreds of identical 'Invalid token: Signature verification
    failed' lines per second and stalls journald. We keep the first
    occurrence verbatim and emit one summary line every 30s with the
    suppressed count, so the operator still has visibility of the
    issue without the cascade.
    """
    now = time.time()
    with _AUTH_LOG_LOCK:
        elapsed = now - _AUTH_LOG_RATE['last_ts']
        if elapsed >= 30:
            if _AUTH_LOG_RATE['suppressed']:
                print(f"[auth] {_AUTH_LOG_RATE['last_msg']} "
                      f"(+{_AUTH_LOG_RATE['suppressed']} more in last "
                      f"{int(elapsed)}s)")
            else:
                print(f"[auth] {msg}")
            _AUTH_LOG_RATE['last_ts'] = now
            _AUTH_LOG_RATE['suppressed'] = 0
            _AUTH_LOG_RATE['last_msg'] = msg
        else:
            _AUTH_LOG_RATE['suppressed'] += 1
            _AUTH_LOG_RATE['last_msg'] = msg


def verify_token(token):
    """
    Verify a JWT token
    Returns username if valid, None otherwise
    Also checks if the token has been revoked
    """
    if not JWT_AVAILABLE or not token:
        return None

    try:
        # Revoked-token list is cached in memory (TTL + mtime) so high-RPS
        # endpoints don't reread auth.json from disk on every @require_auth call.
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if token_hash in _get_revoked_tokens_cached():
            return None

        # Verify against the per-install secret first. Tokens issued under the
        # legacy hardcoded secret were forgeable by anyone with read access to
        # the public repo — those are intentionally rejected so users get a
        # one-time relogin to mint a fresh token.
        # `iss`/`aud` claims are validated when present; tokens issued before
        # the iss/aud rollout (no claims) fall back to a permissive decode so
        # active sessions don't break on upgrade.
        try:
            payload = jwt.decode(
                token,
                _get_jwt_secret(),
                algorithms=[JWT_ALGORITHM],
                audience=JWT_AUDIENCE,
                issuer=JWT_ISSUER,
            )
        except (jwt.MissingRequiredClaimError, jwt.InvalidAudienceError, jwt.InvalidIssuerError):
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return payload.get('username')
    except jwt.ExpiredSignatureError:
        _log_auth_failure_throttled("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        _log_auth_failure_throttled(f"Invalid token: {e}")
        return None


def _jwt_secret_fingerprint(secret: str = None) -> str:
    """Stable fingerprint of the active jwt_secret.

    First 16 hex chars of SHA256(secret). Used to detect whether a stored
    api-token was minted under the *current* jwt_secret or under a
    previous one (in which case the JWT can no longer be verified).
    Never returns the secret itself.
    """
    sec = secret if secret is not None else _get_jwt_secret()
    if not sec:
        return ""
    return hashlib.sha256(sec.encode()).hexdigest()[:16]


def store_api_token_metadata(token, token_name="API Token"):
    """
    Store API token metadata (hash, name, creation date) for listing and revocation.
    The actual token is never stored - only a hash for identification.

    Also records the fingerprint of the jwt_secret that minted this token
    (`signed_with`). At list time we compare this against the current
    fingerprint so the UI can flag tokens whose signing secret has been
    rotated since — those JWTs no longer verify and the operator needs
    to regenerate them (see `list_api_tokens`).
    """
    config = load_auth_config()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    token_id = token_hash[:16]

    token_entry = {
        "id": token_id,
        "name": token_name,
        "token_hash": token_hash,
        "token_prefix": token[:12] + "...",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "expires_at": (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z",
        "signed_with": _jwt_secret_fingerprint(),
    }

    config.setdefault("api_tokens", [])
    config["api_tokens"].append(token_entry)
    save_auth_config(config)
    return token_entry


def list_api_tokens():
    """List stored API token metadata (no actual tokens are returned).

    Each entry carries:
      * `revoked`  — token hash is in the revocation list.
      * `valid`    — JWT can still be verified with the current secret.
                     `True` when `signed_with` matches the current
                     fingerprint, `False` when it doesn't (jwt_secret
                     rotated → JWT signature broken), `None` for legacy
                     entries created before this field existed (status
                     can only be confirmed by attempting a verify with
                     the real token, which we never see at list time).
      * `invalidation_reason` — human-readable explanation when
                                `valid is False`, otherwise absent.

    The UI uses these flags to flag tokens that look stored but no
    longer authenticate — preventing the "I have the token but it
    returns 401" rabbit hole.
    """
    config = load_auth_config()
    tokens = config.get("api_tokens", [])
    revoked = set(config.get("revoked_tokens", []))
    current_fp = _jwt_secret_fingerprint()

    result = []
    for t in tokens:
        signed_with = t.get("signed_with")
        if signed_with is None:
            valid = None  # legacy entry — unknown
            reason = None
        elif signed_with == current_fp:
            valid = True
            reason = None
        else:
            valid = False
            reason = ("Signed with a previous jwt_secret. The signing "
                      "secret has been rotated since this token was "
                      "issued — its JWT can no longer be verified. "
                      "Revoke this token and generate a new one.")

        entry = {
            "id": t.get("id"),
            "name": t.get("name", "API Token"),
            "token_prefix": t.get("token_prefix", "***"),
            "created_at": t.get("created_at"),
            "expires_at": t.get("expires_at"),
            "revoked": t.get("token_hash") in revoked,
            "valid": valid,
        }
        if reason:
            entry["invalidation_reason"] = reason
        result.append(entry)
    return result


def revoke_api_token(token_id):
    """
    Revoke an API token by its ID.
    Adds the token hash to the revoked list so it fails verification.
    Returns (success: bool, message: str)
    """
    config = load_auth_config()
    tokens = config.get("api_tokens", [])
    
    target = None
    for t in tokens:
        if t.get("id") == token_id:
            target = t
            break
    
    if not target:
        return False, "Token not found"
    
    token_hash = target.get("token_hash")
    config.setdefault("revoked_tokens", [])
    
    if token_hash in config["revoked_tokens"]:
        return False, "Token is already revoked"
    
    config["revoked_tokens"].append(token_hash)
    
    # Remove from the active tokens list
    config["api_tokens"] = [t for t in tokens if t.get("id") != token_id]
    
    if save_auth_config(config):
        _invalidate_revoked_cache()
        return True, "Token revoked successfully"
    else:
        return False, "Failed to save configuration"


def get_auth_status():
    """
    Get current authentication status
    Returns dict with:
    {
        "auth_enabled": bool,
        "auth_configured": bool,
        "declined": bool,
        "username": str or None,
        "authenticated": bool,
        "totp_enabled": bool  # 2FA status
    }
    """
    config = load_auth_config()
    return {
        "auth_enabled": config.get("enabled", False),
        "auth_configured": config.get("configured", False),
        "declined": config.get("declined", False),
        "username": config.get("username") if config.get("enabled") else None,
        "authenticated": False,
        "totp_enabled": config.get("totp_enabled", False)  # Include 2FA status
    }


def setup_auth(username, password):
    """
    Set up authentication with username and password
    Returns (success: bool, message: str)
    """
    # Refuse if auth has already been configured. Without this guard an
    # unauthenticated POST to /api/auth/setup would let an attacker overwrite
    # the existing admin credentials and take over the account. See audit
    # Tier 1 #4.
    existing = load_auth_config()
    if existing.get("configured", False):
        return False, "Authentication is already configured"

    if not username or not password:
        return False, "Username and password are required"

    pw_err = _validate_password_strength(password)
    if pw_err:
        return False, pw_err

    config = {
        "enabled": True,
        "username": username,
        "password_hash": hash_password(password),
        "declined": False,
        "configured": True,
        "totp_enabled": False,
        "totp_secret": None,
        "backup_codes": []
    }

    if save_auth_config(config):
        return True, "Authentication configured successfully"
    else:
        return False, "Failed to save authentication configuration"


def decline_auth():
    """
    Mark authentication as declined by user
    Returns (success: bool, message: str)
    """
    config = load_auth_config()
    config["enabled"] = False
    config["declined"] = True
    config["configured"] = True
    config["username"] = None
    config["password_hash"] = None
    config["totp_enabled"] = False
    config["totp_secret"] = None
    config["backup_codes"] = []
    
    if save_auth_config(config):
        return True, "Authentication declined"
    else:
        return False, "Failed to save configuration"


def disable_auth():
    """
    Disable authentication (different from decline - can be re-enabled)
    Returns (success: bool, message: str)
    """
    config = load_auth_config()
    config["enabled"] = False
    config["username"] = None
    config["password_hash"] = None
    config["declined"] = False
    config["configured"] = False
    config["totp_enabled"] = False
    config["totp_secret"] = None
    config["backup_codes"] = []
    # Intentionally preserve `api_tokens` and `revoked_tokens` across
    # disable→re-enable cycles. Wiping them allowed a previously revoked
    # token to verify again because nothing on the deny-list would reject
    # it. Audit Tier 5 — disable_auth() borra revoked_tokens.
    _invalidate_revoked_cache()

    if save_auth_config(config):
        return True, "Authentication disabled"
    else:
        return False, "Failed to save configuration"


def enable_auth():
    """
    Enable authentication (must already be configured)
    Returns (success: bool, message: str)
    """
    config = load_auth_config()
    
    if not config.get("username") or not config.get("password_hash"):
        return False, "Authentication not configured. Please set up username and password first."
    
    config["enabled"] = True
    config["declined"] = False
    
    if save_auth_config(config):
        return True, "Authentication enabled"
    else:
        return False, "Failed to save configuration"


def change_password(old_password, new_password, totp_code=None):
    """
    Change the authentication password.

    When 2FA is enabled on the account, a valid TOTP code (or backup code) is
    REQUIRED in addition to the current password — otherwise an attacker who
    obtained the password (e.g. via shoulder-surfing or phishing) could rotate
    it without the second factor and lock the legitimate user out. See audit
    Tier 1 #10.

    Returns (success: bool, message: str).
    """
    config = load_auth_config()

    if not config.get("enabled"):
        return False, "Authentication is not enabled"

    if not verify_password(old_password, config.get("password_hash", "")):
        return False, "Current password is incorrect"

    pw_err = _validate_password_strength(new_password)
    if pw_err:
        return False, f"New {pw_err[0].lower()}{pw_err[1:]}"

    # 2FA gate: if the account has TOTP enabled, the caller must prove they
    # also hold the second factor.
    if config.get("totp_enabled"):
        username = config.get("username")
        if not totp_code:
            return False, "2FA code required to change password"
        # Try TOTP first, then fall back to backup code (same UX as login).
        ok, _ = verify_totp(username, totp_code, use_backup=False)
        if not ok:
            ok, _ = verify_totp(username, totp_code, use_backup=True)
        if not ok:
            return False, "Invalid 2FA code"
        # Reload after possible backup-code consumption inside verify_totp.
        config = load_auth_config()

    config["password_hash"] = hash_password(new_password)

    if save_auth_config(config):
        return True, "Password changed successfully"
    else:
        return False, "Failed to save new password"


def generate_totp_secret():
    """Generate a new TOTP secret key"""
    if not TOTP_AVAILABLE:
        return None
    return pyotp.random_base32()


def generate_totp_qr(username, secret):
    """
    Generate a QR code for TOTP setup
    Returns base64 encoded SVG image
    """
    if not TOTP_AVAILABLE:
        return None
    
    try:
        # Create TOTP URI
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(
            name=username,
            issuer_name="ProxMenux Monitor"
        )
        
        qr = segno.make(uri)
        
        # Convert to SVG string
        buffer = io.BytesIO()
        qr.save(buffer, kind='svg', scale=4, border=2)
        svg_bytes = buffer.getvalue()
        svg_content = svg_bytes.decode('utf-8')
        
        # Return as data URL
        svg_base64 = base64.b64encode(svg_content.encode()).decode('utf-8')
        return f"data:image/svg+xml;base64,{svg_base64}"
    except Exception as e:
        print(f"Error generating QR code: {e}")
        return None


def generate_backup_codes(count=8):
    """Generate backup codes for 2FA recovery"""
    codes = []
    for _ in range(count):
        # Generate 8-character alphanumeric code
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        # Format as XXXX-XXXX for readability
        formatted = f"{code[:4]}-{code[4:]}"
        codes.append({
            "code": hashlib.sha256(formatted.encode()).hexdigest(),
            "used": False
        })
    return codes


def setup_totp(username):
    """
    Set up TOTP for a user
    Returns (success: bool, secret: str, qr_code: str, backup_codes: list, message: str)
    """
    if not TOTP_AVAILABLE:
        return False, None, None, None, "2FA is not available (pyotp/segno not installed)"
    
    config = load_auth_config()
    
    if not config.get("enabled"):
        return False, None, None, None, "Authentication must be enabled first"
    
    if config.get("username") != username:
        return False, None, None, None, "Invalid username"
    
    # Generate new secret and backup codes
    secret = generate_totp_secret()
    qr_code = generate_totp_qr(username, secret)
    backup_codes_plain = []
    backup_codes_hashed = generate_backup_codes()
    
    # Generate plain text backup codes for display (only returned once)
    for i in range(8):
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        formatted = f"{code[:4]}-{code[4:]}"
        backup_codes_plain.append(formatted)
        backup_codes_hashed[i]["code"] = hashlib.sha256(formatted.encode()).hexdigest()
    
    # Store secret and hashed backup codes (not enabled yet until verified)
    config["totp_secret"] = secret
    config["backup_codes"] = backup_codes_hashed
    
    if save_auth_config(config):
        return True, secret, qr_code, backup_codes_plain, "2FA setup initiated"
    else:
        return False, None, None, None, "Failed to save 2FA configuration"


def verify_totp(username, token, use_backup=False):
    """
    Verify a TOTP token or backup code
    Returns (success: bool, message: str)
    """
    if not TOTP_AVAILABLE and not use_backup:
        return False, "2FA is not available"
    
    config = load_auth_config()
    
    if not config.get("totp_enabled"):
        return False, "2FA is not enabled"
    
    if config.get("username") != username:
        return False, "Invalid username"
    
    # Check backup code
    if use_backup:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        for backup_code in config.get("backup_codes", []):
            if backup_code["code"] == token_hash and not backup_code["used"]:
                backup_code["used"] = True
                save_auth_config(config)
                return True, "Backup code accepted"
        return False, "Invalid or already used backup code"
    
    # Check TOTP token. `valid_window=1` accepts the previous, current and
    # next 30s timesteps, which is friendly to clock skew but lets a leaked
    # OTP be replayed for up to ~90s. Track the last successfully-used
    # timestep counter per account and reject anything <= that.
    import time as _time
    totp = pyotp.TOTP(config.get("totp_secret"))
    if not totp.verify(token, valid_window=1):
        return False, "Invalid 2FA code"

    # Find which counter the OTP corresponds to (one of current ± 1).
    # CRITICAL: `pyotp.TOTP.at(t)` takes a UNIX timestamp (seconds), NOT
    # a counter — passing the counter makes `at()` interpret it as a
    # tiny timestamp near the epoch and the same OTP comes back for
    # every step, so this loop never matched and verify_totp always
    # fell into the "fail closed" branch below, locking every 2FA user
    # out. We pass timestamps spaced by `interval` seconds and derive
    # the counter from the matched timestamp.
    interval = getattr(totp, 'interval', 30)
    now_ts = _time.time()
    matched_counter = None
    for delta_steps in (-1, 0, 1):
        probe_ts = now_ts + delta_steps * interval
        try:
            if totp.at(int(probe_ts)) == token:
                matched_counter = int(probe_ts) // interval
                break
        except Exception:
            continue
    if matched_counter is None:
        # `verify()` succeeded but we couldn't map to a counter — fail closed.
        return False, "Invalid 2FA code"

    # `last_counter` may be stored as `null` in auth.json for accounts
    # that haven't authenticated since the anti-replay tracking was
    # introduced. `dict.get(k, default)` only returns the default when
    # the key is MISSING, not when it's present-but-None — so `null`
    # would slip through as Python None and crash the `<=` comparison
    # below. Normalise to -1 (meaning "no previous counter").
    last_counter = config.get("last_totp_counter")
    if last_counter is None:
        last_counter = -1
    if matched_counter <= last_counter:
        return False, "2FA code already used; wait for the next one"

    config["last_totp_counter"] = matched_counter
    save_auth_config(config)
    return True, "2FA verification successful"


def enable_totp(username, verification_token):
    """
    Enable TOTP after successful verification
    Returns (success: bool, message: str)
    """
    if not TOTP_AVAILABLE:
        return False, "2FA is not available"
    
    config = load_auth_config()
    
    if not config.get("totp_secret"):
        return False, "2FA has not been set up. Please set up 2FA first."
    
    if config.get("username") != username:
        return False, "Invalid username"
    
    # Verify the token before enabling
    totp = pyotp.TOTP(config.get("totp_secret"))
    if not totp.verify(verification_token, valid_window=1):
        return False, "Invalid verification code. Please try again."
    
    config["totp_enabled"] = True
    
    if save_auth_config(config):
        return True, "2FA enabled successfully"
    else:
        return False, "Failed to enable 2FA"


def disable_totp(username, password, totp_code=None):
    """
    Disable TOTP (requires password confirmation AND a valid 2FA code).

    Previously this endpoint only required the password, which meant an
    attacker who phished or replayed the password could turn off the user's
    second factor entirely. Per audit Tier 1 #10 and the related frontend
    finding ("Disable 2FA solo password"), we now also demand a valid TOTP
    code (or backup code) to disable the protection it represents.

    Returns (success: bool, message: str).
    """
    config = load_auth_config()

    if config.get("username") != username:
        return False, "Invalid username"

    if not verify_password(password, config.get("password_hash", "")):
        return False, "Invalid password"

    # If TOTP is currently active, require the second factor to disable it.
    if config.get("totp_enabled"):
        if not totp_code:
            return False, "2FA code required to disable 2FA"
        ok, _ = verify_totp(username, totp_code, use_backup=False)
        if not ok:
            ok, _ = verify_totp(username, totp_code, use_backup=True)
        if not ok:
            return False, "Invalid 2FA code"
        # Reload in case a backup code was consumed.
        config = load_auth_config()

    config["totp_enabled"] = False
    config["totp_secret"] = None
    config["backup_codes"] = []

    if save_auth_config(config):
        return True, "2FA disabled successfully"
    else:
        return False, "Failed to disable 2FA"


# -------------------------------------------------------------------
# SSL/HTTPS Certificate Management
# -------------------------------------------------------------------

SSL_CONFIG_FILE = Path(os.environ.get("PROXMENUX_SSL_CONFIG", "/etc/proxmenux/ssl_config.json"))

# Default Proxmox certificate paths
PROXMOX_CERT_PATH = "/etc/pve/local/pve-ssl.pem"
PROXMOX_KEY_PATH = "/etc/pve/local/pve-ssl.key"
# When the admin uploads a custom certificate via the PVE UI, it's written
# to `pveproxy-ssl.pem` instead and PVE itself prefers it. We do the same so
# `detect_proxmox_certificates` reflects the cert the user actually wants
# served. Issue #181.
PROXMOX_CUSTOM_CERT_PATH = "/etc/pve/local/pveproxy-ssl.pem"
PROXMOX_CUSTOM_KEY_PATH = "/etc/pve/local/pveproxy-ssl.key"


def load_ssl_config():
    """Load SSL configuration from file"""
    if not SSL_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "cert_path": "",
            "key_path": "",
            "source": "none"  # "none", "proxmox", "custom"
        }
    
    try:
        with open(SSL_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            config.setdefault("enabled", False)
            config.setdefault("cert_path", "")
            config.setdefault("key_path", "")
            config.setdefault("source", "none")
            return config
    except Exception:
        return {
            "enabled": False,
            "cert_path": "",
            "key_path": "",
            "source": "none"
        }


def save_ssl_config(config):
    """Save SSL configuration to file"""
    try:
        SSL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SSL_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving SSL config: {e}")
        return False


def detect_proxmox_certificates():
    """
    Detect available Proxmox certificates.
    Returns dict with detection results.

    Prefers the custom-uploaded `pveproxy-ssl.pem` (what PVE itself uses
    when the admin uploaded a Let's Encrypt / commercial cert via the UI)
    and falls back to the default self-signed `pve-ssl.pem`. Issue #181 —
    detector solo encontraba pve-ssl.pem.
    """
    result = {
        "proxmox_available": False,
        "proxmox_cert": PROXMOX_CERT_PATH,
        "proxmox_key": PROXMOX_KEY_PATH,
        "cert_info": None
    }

    if os.path.isfile(PROXMOX_CUSTOM_CERT_PATH) and os.path.isfile(PROXMOX_CUSTOM_KEY_PATH):
        result["proxmox_cert"] = PROXMOX_CUSTOM_CERT_PATH
        result["proxmox_key"] = PROXMOX_CUSTOM_KEY_PATH
        result["proxmox_available"] = True
    elif os.path.isfile(PROXMOX_CERT_PATH) and os.path.isfile(PROXMOX_KEY_PATH):
        result["proxmox_available"] = True

    if result["proxmox_available"]:
        # Try to get certificate info from whichever cert we picked.
        try:
            import subprocess
            cert_output = subprocess.run(
                ["openssl", "x509", "-in", result["proxmox_cert"], "-noout", "-subject", "-enddate", "-issuer"],
                capture_output=True, text=True, timeout=5
            )
            if cert_output.returncode == 0:
                lines = cert_output.stdout.strip().split('\n')
                info = {}
                for line in lines:
                    if line.startswith("subject="):
                        info["subject"] = line.replace("subject=", "").strip()
                    elif line.startswith("notAfter="):
                        info["expires"] = line.replace("notAfter=", "").strip()
                    elif line.startswith("issuer="):
                        issuer = line.replace("issuer=", "").strip()
                        info["issuer"] = issuer
                        info["is_self_signed"] = info.get("subject", "") == issuer
                result["cert_info"] = info
        except Exception:
            pass
    
    return result


def validate_certificate_files(cert_path, key_path):
    """
    Validate that cert and key files exist and are readable.
    Returns (valid: bool, message: str)
    """
    if not cert_path or not key_path:
        return False, "Certificate and key paths are required"
    
    if not os.path.isfile(cert_path):
        return False, f"Certificate file not found: {cert_path}"
    
    if not os.path.isfile(key_path):
        return False, f"Key file not found: {key_path}"
    
    # Verify files are readable
    try:
        with open(cert_path, 'r') as f:
            content = f.read(100)
            if "BEGIN CERTIFICATE" not in content and "BEGIN TRUSTED CERTIFICATE" not in content:
                return False, "Certificate file does not appear to be a valid PEM certificate"
        
        with open(key_path, 'r') as f:
            content = f.read(100)
            if "BEGIN" not in content or "KEY" not in content:
                return False, "Key file does not appear to be a valid PEM key"
    except PermissionError:
        return False, "Cannot read certificate files. Check file permissions."
    except Exception as e:
        return False, f"Error reading certificate files: {str(e)}"
    
    # Verify cert and key match
    try:
        import subprocess
        cert_mod = subprocess.run(
            ["openssl", "x509", "-noout", "-modulus", "-in", cert_path],
            capture_output=True, text=True, timeout=5
        )
        key_mod = subprocess.run(
            ["openssl", "rsa", "-noout", "-modulus", "-in", key_path],
            capture_output=True, text=True, timeout=5
        )
        if cert_mod.returncode == 0 and key_mod.returncode == 0:
            if cert_mod.stdout.strip() != key_mod.stdout.strip():
                return False, "Certificate and key do not match"
    except Exception:
        pass  # Non-critical, proceed anyway
    
    return True, "Certificate files are valid"


def configure_ssl(cert_path, key_path, source="custom"):
    """
    Configure SSL with given certificate and key paths.
    Returns (success: bool, message: str)
    """
    valid, message = validate_certificate_files(cert_path, key_path)
    if not valid:
        return False, message
    
    config = {
        "enabled": True,
        "cert_path": cert_path,
        "key_path": key_path,
        "source": source
    }
    
    if save_ssl_config(config):
        return True, "SSL configured successfully. Restart the monitor service to apply changes."
    else:
        return False, "Failed to save SSL configuration"


def disable_ssl():
    """Disable SSL and return to HTTP"""
    config = {
        "enabled": False,
        "cert_path": "",
        "key_path": "",
        "source": "none"
    }
    
    if save_ssl_config(config):
        return True, "SSL disabled. Restart the monitor service to apply changes."
    else:
        return False, "Failed to save SSL configuration"


def get_ssl_context():
    """
    Get SSL context for Flask if SSL is configured and enabled.
    Returns tuple (cert_path, key_path) or None
    """
    config = load_ssl_config()
    
    if not config.get("enabled"):
        return None
    
    cert_path = config.get("cert_path", "")
    key_path = config.get("key_path", "")
    
    if cert_path and key_path and os.path.isfile(cert_path) and os.path.isfile(key_path):
        return (cert_path, key_path)
    
    return None


def authenticate(username, password, totp_token=None):
    """
    Authenticate a user with username, password, and optional TOTP
    Returns (success: bool, token: str or None, requires_totp: bool, message: str)
    """
    config = load_auth_config()
    
    if not config.get("enabled"):
        return False, None, False, "Authentication is not enabled"
    
    if username != config.get("username"):
        return False, None, False, "Invalid username or password"
    
    if not verify_password(password, config.get("password_hash", "")):
        return False, None, False, "Invalid username or password"

    # Lazy migration: if the stored hash is the legacy unsalted SHA-256, replace
    # it with a fresh PBKDF2 hash now that we have the cleartext in hand. The
    # next login uses the new hash; the legacy code path stays around only as
    # the recognition entry in `verify_password`. Audit Tier 4 #23.
    upgraded = _maybe_rehash_password(password, config.get("password_hash", ""))
    if upgraded:
        config["password_hash"] = upgraded
        try:
            save_auth_config(config)
        except Exception as e:
            # Don't block login if persistence fails — the user is still
            # authenticated and we can rehash on a future login attempt.
            print(f"[auth] Failed to persist rehashed password: {e}")

    if config.get("totp_enabled"):
        if not totp_token:
            # First step: password OK, now request TOTP code (not a failure)
            return False, None, True, "2FA code required"
        
        # Verify TOTP token or backup code
        success, message = verify_totp(username, totp_token, use_backup=len(totp_token) == 9)  # Backup codes are formatted XXXX-XXXX
        if not success:
            # TOTP code is wrong: return requires_totp=False so the caller
            # logs it as a real authentication failure for Fail2Ban
            return False, None, False, "Invalid 2FA code"
    
    token = generate_token(username)
    if token:
        return True, token, False, "Authentication successful"
    else:
        return False, None, False, "Failed to generate authentication token"
