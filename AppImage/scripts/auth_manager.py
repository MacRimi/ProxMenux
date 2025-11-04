"""
Authentication Manager Module
Handles all authentication-related operations including:
- Loading/saving auth configuration
- Password hashing and verification
- JWT token generation and validation
- Auth status checking
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    print("Warning: PyJWT not available. Authentication features will be limited.")

# Configuration
CONFIG_DIR = Path.home() / ".config" / "proxmenux-monitor"
AUTH_CONFIG_FILE = CONFIG_DIR / "auth.json"
JWT_SECRET = "proxmenux-monitor-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRATION_HOURS = 24


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
        "declined": bool,  # True if user explicitly declined auth
        "configured": bool  # True if auth has been set up (enabled or declined)
    }
    """
    if not AUTH_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "username": None,
            "password_hash": None,
            "declined": False,
            "configured": False
        }
    
    try:
        with open(AUTH_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Ensure all required fields exist
            config.setdefault("declined", False)
            config.setdefault("configured", config.get("enabled", False) or config.get("declined", False))
            return config
    except Exception as e:
        print(f"Error loading auth config: {e}")
        return {
            "enabled": False,
            "username": None,
            "password_hash": None,
            "declined": False,
            "configured": False
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


def hash_password(password):
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password, password_hash):
    """Verify a password against its hash"""
    return hash_password(password) == password_hash


def generate_token(username):
    """Generate a JWT token for the given username"""
    if not JWT_AVAILABLE:
        return None
    
    payload = {
        'username': username,
        'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    
    try:
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return token
    except Exception as e:
        print(f"Error generating token: {e}")
        return None


def verify_token(token):
    """
    Verify a JWT token
    Returns username if valid, None otherwise
    """
    if not JWT_AVAILABLE or not token:
        return None
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('username')
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None


def get_auth_status():
    """
    Get current authentication status
    Returns dict with:
    {
        "enabled": bool,
        "configured": bool,
        "declined": bool,
        "username": str or None
    }
    """
    config = load_auth_config()
    return {
        "enabled": config.get("enabled", False),
        "configured": config.get("configured", False),
        "declined": config.get("declined", False),
        "username": config.get("username") if config.get("enabled") else None
    }


def setup_auth(username, password):
    """
    Set up authentication with username and password
    Returns (success: bool, message: str)
    """
    if not username or not password:
        return False, "Username and password are required"
    
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    
    config = {
        "enabled": True,
        "username": username,
        "password_hash": hash_password(password),
        "declined": False,
        "configured": True
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
    # Keep configured=True and don't set declined=True
    # This allows re-enabling without showing the setup modal again
    
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


def change_password(old_password, new_password):
    """
    Change the authentication password
    Returns (success: bool, message: str)
    """
    config = load_auth_config()
    
    if not config.get("enabled"):
        return False, "Authentication is not enabled"
    
    if not verify_password(old_password, config.get("password_hash", "")):
        return False, "Current password is incorrect"
    
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters"
    
    config["password_hash"] = hash_password(new_password)
    
    if save_auth_config(config):
        return True, "Password changed successfully"
    else:
        return False, "Failed to save new password"


def authenticate(username, password):
    """
    Authenticate a user with username and password
    Returns (success: bool, token: str or None, message: str)
    """
    config = load_auth_config()
    
    if not config.get("enabled"):
        return False, None, "Authentication is not enabled"
    
    if username != config.get("username"):
        return False, None, "Invalid username or password"
    
    if not verify_password(password, config.get("password_hash", "")):
        return False, None, "Invalid username or password"
    
    token = generate_token(username)
    if token:
        return True, token, "Authentication successful"
    else:
        return False, None, "Failed to generate authentication token"
