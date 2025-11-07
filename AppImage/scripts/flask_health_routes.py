"""
Flask routes for health monitoring
"""

from flask import Blueprint, jsonify
from health_monitor import health_monitor

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
    Returns: hostname, uptime, and cached health status.
    This is optimized for minimal server impact.
    """
    try:
        info = health_monitor.get_system_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
