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
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/api/auth/setup', methods=['POST'])
def auth_setup():
    """Set up authentication with username and password"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        success, message = auth_manager.setup_auth(username, password)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
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
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        username = auth_manager.verify_token(token)
        
        if not username:
            return jsonify({"success": False, "message": "Unauthorized. Please log in first."}), 401
        
        data = request.json
        password = data.get('password')
        totp_token = data.get('totp_token')  # Optional 2FA token
        token_name = data.get('token_name', 'API Token')  # Optional token description
        
        # Authenticate user with password and optional 2FA
        success, _, requires_totp, message = auth_manager.authenticate(username, password, totp_token)
        
        if success:
            # Generate a long-lived token (1 year expiration)
            api_token = jwt.encode({
                'username': username,
                'token_name': token_name,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=365),
                'iat': datetime.datetime.utcnow()
            }, auth_manager.SECRET_KEY, algorithm='HS256')
            
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
        return jsonify({"success": False, "message": str(e)}), 500
