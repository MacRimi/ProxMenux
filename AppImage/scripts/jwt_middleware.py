"""
JWT Middleware Module
Decorators that protect the Flask routes according to the access mode of the
Monitor (see `auth_manager.access_mode`) and the profile of the request (see
permissions.py):

- undecided: nothing is served until someone chooses how to reach the Monitor.
- password:  a valid token is required; its profile decides what it can do.
- proxmox:   the same, with Proxmox VE tickets (see pve_auth.py).
- read_only: no account; every request observes, nothing else.
- open:      no account and no limits, chosen knowing the risk.

Each route needs the permission permissions.py lists for its rule and method;
the decorators only say that a route is protected.
"""

from flask import request, jsonify, g
from functools import wraps
import permissions
from auth_manager import load_auth_config, verify_token_full, access_mode, profile_for


def _setup_required():
    return jsonify({"error": "setup_required",
                    "message": "Choose how to access ProxMenux Monitor first"}), 403


def _insufficient(identity, need):
    # Every refusal is written with the account that tried it.
    try:
        import access_log
        rule = request.url_rule.rule if request.url_rule is not None else request.path
        access_log.refused((identity or {}).get("username"), request.method, rule, need)
    except RuntimeError:
        pass
    if identity and identity["profile"] == "observer":
        message = "This action is not available with read-only access"
    else:
        message = "Your profile does not allow this action"
    return jsonify({"error": "Insufficient scope", "message": message, "permission": need}), 403


def _token_identity():
    """(username, scope, error response) for the Bearer token of the request,
    when the Monitor has an account."""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        verify_token_full(None)  # Guarded, credential-free rejection diagnostic.
        return None, None, (jsonify({"error": "Authentication required",
                                     "message": "No authorization header provided"}), 401)
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        verify_token_full(None)
        return None, None, (jsonify({"error": "Invalid authorization header",
                                     "message": "Authorization header must be in format: Bearer <token>"}), 401)
    username, scope = verify_token_full(parts[1])
    if not username:
        return None, None, (jsonify({"error": "Invalid or expired token",
                                     "message": "Please log in again"}), 401)
    return username, scope, None


def _identity(username, profile):
    return {"username": username, "profile": profile,
            "permissions": permissions.permissions_of(profile)}


def request_identity():
    """(mode, identity, error response) of the current request. The identity
    holds `username` (None without an account), `profile` and `permissions`;
    in read-only and open modes a token is not needed and not looked at."""
    mode = access_mode(load_auth_config())
    if mode == 'undecided':
        return mode, None, _setup_required()
    if mode in ('open', 'read_only'):
        return mode, _identity(None, profile_for(mode)), None
    username, scope, error = _token_identity()
    if error:
        return mode, None, error
    profile = profile_for(mode, username, scope)
    if not profile:
        return mode, None, (jsonify({"error": "Invalid or expired token",
                                     "message": "Please log in again"}), 401)
    return mode, _identity(username, profile), None


def _internal_call():
    """Internal calls (background prewarmers, in-process cache refresh) set
    `g._internal_call = True` inside an `app.test_request_context()` block;
    the flag lives only for that context, so a real HTTP request can never
    inherit it."""
    try:
        return bool(getattr(g, '_internal_call', False))
    except RuntimeError:
        return False  # No request context yet: the normal checks apply.


def permission_error(need, areas=permissions.BASE):
    """The response refusing the current request `need`, or None when it may.
    A reading (`view`) is allowed in `areas`."""
    _mode, identity, error = request_identity()
    if error:
        return error
    g.identity = identity
    if not permissions.allows(identity["permissions"], need, signed_in=bool(identity["username"]), areas=areas):
        return _insufficient(identity, need)
    return None


def has_permission(need):
    """Whether the current request has `need`: for routes that leave out what
    only some profiles may see, such as passwords on a command line."""
    if _internal_call():
        return True
    _mode, identity, error = request_identity()
    return error is None and need in identity["permissions"]


def has_full_access():
    """Whether the current request may see secrets."""
    return has_permission("admin")


def _rule():
    return request.url_rule.rule if request.url_rule is not None else request.path


def _need(floor_view):
    need = permissions.required(_rule(), request.method)
    # A route marked for more than reading never falls back to it.
    return "admin" if floor_view and need == "view" else need


def _protect(f, floor_view):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if _internal_call():
            return f(*args, **kwargs)
        need = _need(floor_view)
        # A reading not listed is read as before areas existed; a test keeps
        # every route of the Monitor listed.
        areas = (permissions.read_areas(_rule()) or permissions.BASE) if need == "view" else permissions.BASE
        error = permission_error(need, areas)
        return error or f(*args, **kwargs)
    return decorated_function


def require_auth(f):
    """Decorator to protect Flask routes: the request needs the permission of
    its route (see permissions.py)."""
    return _protect(f, floor_view=False)


def require_admin_scope(f):
    """Like `require_auth`, for actions and readings that carry secrets: such
    a route never needs only `view`, whatever its method."""
    return _protect(f, floor_view=True)


def require_admin_or_ticket(f):
    """Like `require_admin_scope`, for downloads that carry secrets, such as
    the PBS encryption key and host backups. A single-use `?ticket=...` is
    accepted too, with the permissions of whoever asked for it; an
    <a download> link cannot send the Authorization header."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        need = _need(floor_view=True)
        mode = access_mode(load_auth_config())
        if mode == 'undecided':
            return _setup_required()
        if mode == 'open':
            return f(*args, **kwargs)

        if mode in ('password', 'proxmox') and request.headers.get('Authorization'):
            _mode, identity, _error = request_identity()
            if identity is not None:
                g.identity = identity
                if permissions.allows(identity["permissions"], need):
                    return f(*args, **kwargs)
                return _insufficient(identity, need)

        try:
            from flask_terminal_routes import _consume_terminal_ticket
            if _consume_terminal_ticket(request.args.get('ticket', ''), need):
                return f(*args, **kwargs)
        except ImportError:
            pass

        if mode == 'read_only':
            return _insufficient(_identity(None, "observer"), need)
        return jsonify({
            "error": "Authentication required",
            "message": "Provide a Bearer token in the Authorization header or a fresh ?ticket=... from /api/terminal/ticket"
        }), 401

    return decorated_function
