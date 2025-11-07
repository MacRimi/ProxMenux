"""
Flask Authentication Routes
Provides REST API endpoints for authentication management
"""

from flask import Blueprint, jsonify, request
import auth_manager

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
        
        if not username or not password:
            return jsonify({"success": False, "error": "Username and password are required"}), 400
        
        success, message = auth_manager.setup_auth(username, password)
        
        if success:
            # Generate token for immediate login
            token = auth_manager.generate_token(username)
            return jsonify({"success": True, "message": message, "token": token})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/skip', methods=['POST'])
def auth_skip():
    """Skip authentication setup (user declined)"""
    try:
        success, message = auth_manager.decline_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/decline', methods=['POST'])
def auth_decline():
    """Decline authentication setup (deprecated, use /api/auth/skip)"""
    try:
        success, message = auth_manager.decline_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Authenticate user and return JWT token"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        remember_me = data.get('remember_me', False)  # Soporte para "recordar contraseña"
        
        success, token, message = auth_manager.authenticate(username, password, remember_me)
        
        if success:
            response_data = {"success": True, "token": token, "message": message}
            if remember_me:
                response_data["remember_me"] = True  # Indicar al frontend que guarde las credenciales
            return jsonify(response_data)
        else:
            return jsonify({"success": False, "error": message}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/enable', methods=['POST'])
def auth_enable():
    """Enable authentication"""
    try:
        success, message = auth_manager.enable_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/disable', methods=['POST'])
def auth_disable():
    """Disable authentication"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({"success": False, "error": "Authentication required"}), 401
        
        username = auth_manager.verify_token(token)
        if not username:
            return jsonify({"success": False, "error": "Invalid or expired token"}), 401
        
        success, message = auth_manager.disable_auth()
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/change-password', methods=['POST'])
def auth_change_password():
    """Change authentication password"""
    try:
        data = request.json
        current_password = data.get('current_password')  # Corregido el nombre del campo
        new_password = data.get('new_password')
        
        # Verify current authentication
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({"success": False, "error": "Authentication required"}), 401
        
        username = auth_manager.verify_token(token)
        if not username:
            return jsonify({"success": False, "error": "Invalid or expired token"}), 401
        
        success, message = auth_manager.change_password(current_password, new_password)
        
        if success:
            # Generate new token
            new_token = auth_manager.generate_token(username)
            return jsonify({"success": True, "message": message, "token": new_token})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
