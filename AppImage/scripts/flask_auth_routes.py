"""
Flask Authentication Routes
Provides REST API endpoints for authentication management
"""

from flask import Blueprint, jsonify, request
import auth_manager
import jwt
import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Get current authentication status"""
    try:
        status = auth_manager.get_auth_status()
        
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if token:
            username = auth_manager.verify_token(token)
            if username:
                status['authenticated'] = True
        
        return jsonify(status)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------------------------------------------------------
# SSL/HTTPS Certificate Management
# -------------------------------------------------------------------

@auth_bp.route('/api/ssl/status', methods=['GET'])
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


@auth_bp.route('/api/ssl/configure', methods=['POST'])
def ssl_configure():
    """Configure SSL with Proxmox or custom certificates"""
    try:
        data = request.json or {}
        source = data.get("source", "proxmox")
        
        if source == "proxmox":
            cert_path = auth_manager.PROXMOX_CERT_PATH
            key_path = auth_manager.PROXMOX_KEY_PATH
        elif source == "custom":
            cert_path = data.get("cert_path", "")
            key_path = data.get("key_path", "")
        else:
            return jsonify({"success": False, "message": "Invalid source. Use 'proxmox' or 'custom'."}), 400
        
        success, message = auth_manager.configure_ssl(cert_path, key_path, source)
        
        if success:
            return jsonify({"success": True, "message": message, "requires_restart": True})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/ssl/disable', methods=['POST'])
def ssl_disable():
    """Disable SSL and return to HTTP"""
    try:
        success, message = auth_manager.disable_ssl()
        
        if success:
            return jsonify({"success": True, "message": message, "requires_restart": True})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/ssl/validate', methods=['POST'])
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
    """Decline authentication setup"""
    try:
        success, message = auth_manager.decline_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Authenticate user and return JWT token"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        totp_token = data.get('totp_token')  # Optional 2FA token
        
        success, token, requires_totp, message = auth_manager.authenticate(username, password, totp_token)
        
        if success:
            return jsonify({"success": True, "token": token, "message": message})
        elif requires_totp:
            return jsonify({"success": False, "requires_totp": True, "message": message}), 200
        else:
            return jsonify({"success": False, "message": message}), 401
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/enable', methods=['POST'])
def auth_enable():
    """Enable authentication"""
    try:
        success, message = auth_manager.enable_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/disable', methods=['POST'])
def auth_disable():
    """Disable authentication"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token or not auth_manager.verify_token(token):
            return jsonify({"success": False, "message": "Unauthorized"}), 401
            
        success, message = auth_manager.disable_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/change-password', methods=['POST'])
def auth_change_password():
    """Change authentication password"""
    try:
        data = request.json
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        
        success, message = auth_manager.change_password(old_password, new_password)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/skip', methods=['POST'])
def auth_skip():
    """Skip authentication setup (same as decline)"""
    try:
        success, message = auth_manager.decline_auth()
        
        if success:
            # Return success with clear indication that APIs should be accessible
            return jsonify({
                "success": True, 
                "message": message,
                "auth_declined": True  # Add explicit flag for frontend
            })
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/totp/setup', methods=['POST'])
def totp_setup():
    """Initialize TOTP setup for a user"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username = auth_manager.verify_token(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
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
        username = auth_manager.verify_token(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
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
        username = auth_manager.verify_token(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
        data = request.json
        password = data.get('password')
        
        if not password:
            return jsonify({"success": False, "message": "Password required"}), 400
        
        success, message = auth_manager.disable_totp(username, password)
        
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
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '')
        
        if not token:
            return jsonify({"success": False, "message": "Unauthorized. Please log in first."}), 401
        
        username = auth_manager.verify_token(token)
        
        if not username:
            return jsonify({"success": False, "message": "Invalid or expired session. Please log in again."}), 401
        
        data = request.json
        password = data.get('password')
        totp_token = data.get('totp_token')  # Optional 2FA token
        token_name = data.get('token_name', 'API Token')  # Optional token description
        
        if not password:
            return jsonify({"success": False, "message": "Password is required"}), 400
        
        # Authenticate user with password and optional 2FA
        success, _, requires_totp, message = auth_manager.authenticate(username, password, totp_token)
        
        if success:
            # Generate a long-lived token (1 year expiration)
            api_token = jwt.encode({
                'username': username,
                'token_name': token_name,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=365),
                'iat': datetime.datetime.utcnow()
            }, auth_manager.JWT_SECRET, algorithm='HS256')
            
            # Store token metadata for listing and revocation
            auth_manager.store_api_token_metadata(api_token, token_name)
            
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
    """List all generated API tokens (metadata only, no actual token values)"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token or not auth_manager.verify_token(token):
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
        tokens = auth_manager.list_api_tokens()
        return jsonify({"success": True, "tokens": tokens})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@auth_bp.route('/api/auth/api-tokens/<token_id>', methods=['DELETE'])
def revoke_api_token_route(token_id):
    """Revoke an API token by its ID"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token or not auth_manager.verify_token(token):
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
        success, message = auth_manager.revoke_api_token(token_id)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
