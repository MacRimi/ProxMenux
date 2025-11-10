"""
Flask routes for health monitoring with persistence support
"""

from flask import Blueprint, jsonify, request
from health_monitor import health_monitor
from health_persistence import health_persistence

health_bp = Blueprint('health', __name__)

@health_bp.route('/api/health/status', methods=['GET'])
def get_health_status():
    """Get overall health status summary"""
    try:
        status = health_monitor.get_overall_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/details', methods=['GET'])
def get_health_details():
    """Get detailed health status with all checks"""
    try:
        details = health_monitor.get_detailed_status()
        return jsonify(details)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/system-info', methods=['GET'])
def get_system_info():
    """
    Get lightweight system info for header display.
    Returns: hostname, uptime, and health status with proper structure.
    """
    try:
        info = health_monitor.get_system_info()
        
        if 'health' in info:
            status_map = {
                'OK': 'healthy',
                'WARNING': 'warning',
                'CRITICAL': 'critical',
                'UNKNOWN': 'warning'
            }
            current_status = info['health'].get('status', 'OK').upper()
            info['health']['status'] = status_map.get(current_status, 'healthy')
        
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/acknowledge', methods=['POST'])
def acknowledge_error():
    """Acknowledge an error manually (user dismissed it)"""
    try:
        data = request.get_json()
        if not data or 'error_key' not in data:
            return jsonify({'error': 'error_key is required'}), 400
        
        error_key = data['error_key']
        health_persistence.acknowledge_error(error_key)
        return jsonify({'success': True, 'message': 'Error acknowledged'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/active-errors', methods=['GET'])
def get_active_errors():
    """Get all active persistent errors"""
    try:
        category = request.args.get('category')
        errors = health_persistence.get_active_errors(category)
        return jsonify({'errors': errors})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
