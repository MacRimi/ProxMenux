"""
JWT Middleware Module
Provides decorator to protect Flask routes with JWT authentication
Automatically checks auth status and validates tokens
"""

from flask import request, jsonify
from functools import wraps
from auth_manager import load_auth_config, verify_token


def require_auth(f):
    """
    Decorator to protect Flask routes with JWT authentication
    
    Behavior:
    - If auth is disabled or declined: Allow access (no token required)
    - If auth is enabled: Require valid JWT token in Authorization header
    - Returns 401 if auth required but token missing/invalid
    
    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            return jsonify({"data": "secret"})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if authentication is enabled
        config = load_auth_config()
        
        # If auth is disabled or declined, allow access
        if not config.get("enabled", False) or config.get("declined", False):
            return f(*args, **kwargs)
        
        # Auth is enabled, require token
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({
                "error": "Authentication required",
                "message": "No authorization header provided"
            }), 401
        
        # Extract token from "Bearer <token>" format
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({
                "error": "Invalid authorization header",
                "message": "Authorization header must be in format: Bearer <token>"
            }), 401
        
        token = parts[1]
        
        # Verify token
        username = verify_token(token)
        if not username:
            return jsonify({
                "error": "Invalid or expired token",
                "message": "Please log in again"
            }), 401
        
        # Token is valid, allow access
        return f(*args, **kwargs)
    
    return decorated_function


def optional_auth(f):
    """
    Decorator for routes that can optionally use auth
    Passes username if authenticated, None otherwise
    
    Usage:
        @app.route('/api/optional')
        @optional_auth
        def optional_route(username=None):
            if username:
                return jsonify({"message": f"Hello {username}"})
            return jsonify({"message": "Hello guest"})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = load_auth_config()
        username = None
        
        if config.get("enabled", False):
            auth_header = request.headers.get('Authorization')
            if auth_header:
                parts = auth_header.split()
                if len(parts) == 2 and parts[0].lower() == 'bearer':
                    username = verify_token(parts[1])
        
        # Inject username into kwargs
        kwargs['username'] = username
        return f(*args, **kwargs)
    
    return decorated_function
