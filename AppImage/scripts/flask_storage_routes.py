from flask import Blueprint, jsonify
from jwt_middleware import require_auth
import storage_monitor

storage_bp = Blueprint('storage', __name__)

@storage_bp.route('/api/storage', methods=['GET'])
@require_auth
def api_storage():
    try:
        data = storage_monitor.get_storage_info()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@storage_bp.route('/api/storage/summary', methods=['GET'])
@require_auth
def api_storage_summary():
    try:
        data = storage_monitor.get_storage_summary()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@storage_bp.route('/api/proxmox-storage', methods=['GET'])
@require_auth
def api_proxmox_storage():
    try:
        data = storage_monitor.get_proxmox_storage()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@storage_bp.route('/api/backups', methods=['GET'])
@require_auth
def api_backups():
    try:
        data = storage_monitor.get_backups()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500