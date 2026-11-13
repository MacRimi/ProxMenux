"""
JWT Middleware Module
Decorators that protect the Flask routes according to the access mode of the
Monitor (see `auth_manager.access_mode`):

- undecided: nothing is served until someone chooses how to reach the Monitor.
- password:  a valid token is required; `read_only` tokens may only read.
- read_only: no account; every request may read, nothing else.
- open:      no account and no limits, chosen knowing the risk.
"""

from flask import request, jsonify, g
from functools import wraps
from auth_manager import load_auth_config, verify_token_full, access_mode

_READ_METHODS = ('GET', 'HEAD', 'OPTIONS')


def _setup_required():
    return jsonify({"error": "setup_required",
                    "message": "Choose how to access ProxMenux Monitor first"}), 403


def _insufficient(scope):
    if scope == 'read_only':
        return jsonify({"error": "Insufficient scope",
                        "message": "This action is not available with read-only access"}), 403
    return jsonify({"error": "Insufficient scope",
                    "message": f"This action requires a full_admin token (your token: {scope})"}), 403


def _token_scope():
    """(scope, error response) for the Bearer token of the request, when the
    Monitor has an account."""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        verify_token_full(None)  # Guarded, credential-free rejection diagnostic.
        return None, (jsonify({"error": "Authentication required",
                               "message": "No authorization header provided"}), 401)
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        verify_token_full(None)
        return None, (jsonify({"error": "Invalid authorization header",
                               "message": "Authorization header must be in format: Bearer <token>"}), 401)
    username, scope = verify_token_full(parts[1])
    if not username:
        return None, (jsonify({"error": "Invalid or expired token",
                               "message": "Please log in again"}), 401)
    return scope, None


def request_scope():
    """(mode, scope, error response) of the current request. `scope` is
    'full_admin', 'read_only' or None; in read-only and open modes a token is
    not needed and not looked at."""
    mode = access_mode(load_auth_config())
    if mode == 'undecided':
        return mode, None, _setup_required()
    if mode == 'open':
        return mode, 'full_admin', None
    if mode == 'read_only':
        return mode, 'read_only', None
    scope, error = _token_scope()
    return mode, scope, error


def has_full_access():
    """Whether the current request has full access: for routes that leave out
    secrets, such as passwords on a command line, when the access is read-only."""
    try:
        if getattr(g, '_internal_call', False):
            return True
    except RuntimeError:
        pass
    _mode, scope, error = request_scope()
    return error is None and scope == 'full_admin'


def require_auth(f):
    """
    Decorator to protect Flask routes.

    Reading methods are served to any accepted request; a method that can
    change state needs full access (a `full_admin` token, or an open Monitor).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Internal calls (background prewarmers, in-process cache
        # refresh) bypass auth. Set `g._internal_call = True` inside
        # an `app.test_request_context()` block before invoking a
        # decorated handler — the flag lives only for that context so
        # a real HTTP request can never accidentally inherit it.
        try:
            if getattr(g, '_internal_call', False):
                return f(*args, **kwargs)
        except RuntimeError:
            pass  # No request context yet — treat as normal auth flow.

        _mode, scope, error = request_scope()
        if error:
            return error
        # read_only access may only read; any method that can change
        # state needs full_admin.
        if request.method not in _READ_METHODS and scope != 'full_admin':
            return _insufficient(scope)
        return f(*args, **kwargs)

    return decorated_function


def require_admin_or_ticket(f):
    """Like `require_auth`, for downloads that carry secrets, such as the PBS
    encryption key and host backups: full access is required. A single-use
    `?ticket=...` is accepted too, since only full access can get one; an
    <a download> link cannot send the Authorization header."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        mode = access_mode(load_auth_config())
        if mode == 'undecided':
            return _setup_required()
        if mode == 'open':
            return f(*args, **kwargs)

        if mode == 'password':
            auth_header = request.headers.get('Authorization')
            if auth_header:
                parts = auth_header.split()
                if len(parts) == 2 and parts[0].lower() == 'bearer':
                    username, scope = verify_token_full(parts[1])
                    if username and scope == 'full_admin':
                        return f(*args, **kwargs)
                    if username:
                        return _insufficient(scope)

        try:
            from flask_terminal_routes import _consume_terminal_ticket
            if _consume_terminal_ticket(request.args.get('ticket', '')):
                return f(*args, **kwargs)
        except ImportError:
            pass

        if mode == 'read_only':
            return _insufficient('read_only')
        return jsonify({
            "error": "Authentication required",
            "message": "Provide a full_admin Bearer token in the Authorization header or a fresh ?ticket=... from /api/terminal/ticket"
        }), 401

    return decorated_function


def require_admin_scope(f):
    """Like `require_auth` but full access is required for every method,
    reading ones included.

    Use on actions and on readings that carry secrets, which read-only access
    (a `read_only` token or a read-only Monitor) must not reach. Tokens
    generated by the session login flow inherit `full_admin` implicitly;
    long-lived API tokens default to `read_only` unless the caller
    opted in. Audit Tier 6 — Tokens API JWT 365 días sin scope.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        _mode, scope, error = request_scope()
        if error:
            return error
        if scope != 'full_admin':
            return _insufficient(scope)
        return f(*args, **kwargs)
    return decorated_function
