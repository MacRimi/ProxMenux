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
        
        success, token, message = auth_manager.authenticate(username, password)
        
        if success:
            return jsonify({"success": True, "token": token, "message": message})
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
