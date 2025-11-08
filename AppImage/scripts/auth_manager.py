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
import secrets
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
        "declined": bool,
        "configured": bool,
        "totp_enabled": bool,  # 2FA enabled flag
        "totp_secret": str,    # TOTP secret key
        "backup_codes": list   # List of backup codes
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
            "backup_codes": []
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
            "backup_codes": []
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
    if not username or not password:
        return False, "Username and password are required"
    
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    
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
    
    # Check TOTP token
    totp = pyotp.TOTP(config.get("totp_secret"))
    if totp.verify(token, valid_window=1):  # Allow 1 time step tolerance
        return True, "2FA verification successful"
    else:
        return False, "Invalid 2FA code"


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


def disable_totp(username, password):
    """
    Disable TOTP (requires password confirmation)
    Returns (success: bool, message: str)
    """
    config = load_auth_config()
    
    if config.get("username") != username:
        return False, "Invalid username"
    
    if not verify_password(password, config.get("password_hash", "")):
        return False, "Invalid password"
    
    config["totp_enabled"] = False
    config["totp_secret"] = None
    config["backup_codes"] = []
    
    if save_auth_config(config):
        return True, "2FA disabled successfully"
    else:
        return False, "Failed to disable 2FA"


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
    
    if config.get("totp_enabled"):
        if not totp_token:
            return False, None, True, "2FA code required"
        
        # Verify TOTP token or backup code
        success, message = verify_totp(username, totp_token, use_backup=len(totp_token) == 9)  # Backup codes are formatted XXXX-XXXX
        if not success:
            return False, None, True, message
    
    token = generate_token(username)
    if token:
        return True, token, False, "Authentication successful"
    else:
        return False, None, False, "Failed to generate authentication token"
