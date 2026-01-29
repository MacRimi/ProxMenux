from flask import Blueprint, jsonify, request, send_file
from jwt_middleware import require_auth
import system_monitor
import os

system_bp = Blueprint('system', __name__)

@system_bp.route('/api/system', methods=['GET'])
@require_auth
def api_system():
    try:
        data = system_monitor.get_system_info()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@system_bp.route('/api/logs', methods=['GET'])
@require_auth
def api_logs():
    try:
        limit = request.args.get('limit', '200')
        priority = request.args.get('priority')
        service = request.args.get('service')
        since_days = request.args.get('since_days')
        
        data = system_monitor.get_logs(limit, priority, service, since_days)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@system_bp.route('/api/logs/download', methods=['GET'])
@require_auth
def api_logs_download():
    try:
        log_type = request.args.get('type', 'system')
        hours = int(request.args.get('hours', '48'))
        level = request.args.get('level', 'all')
        service = request.args.get('service', 'all')
        since_days = request.args.get('since_days', None)
        
        file_path = system_monitor.generate_log_file(log_type, hours, level, service, since_days)
        
        if file_path and os.path.exists(file_path):
            return send_file(
                file_path,
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'proxmox_{log_type}.log'
            )
        else:
            return jsonify({'error': 'Failed to generate log file'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@system_bp.route('/api/events', methods=['GET'])
@require_auth
def api_events():
    try:
        limit = request.args.get('limit', '50')
        data = system_monitor.get_events(limit)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@system_bp.route('/api/notifications', methods=['GET'])
@require_auth
def api_notifications():
    try:
        data = system_monitor.get_notifications()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@system_bp.route('/api/notifications/download', methods=['GET'])
@require_auth
def api_notifications_download():
    return jsonify({'error': 'Not implemented in modular version yet'}), 501

@system_bp.route('/api/node/metrics', methods=['GET'])
@require_auth
def api_node_metrics():
    try:
        timeframe = request.args.get('timeframe', 'week')
        data = system_monitor.get_node_metrics(timeframe)
        if 'error' in data:
            return jsonify(data), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@system_bp.route('/api/prometheus', methods=['GET'])
@require_auth
def api_prometheus():
    try:
        metrics, content_type = system_monitor.get_prometheus_metrics()
        return metrics, 200, content_type
    except Exception as e:
        return f'# Error generating metrics: {str(e)}\n', 500, {'Content-Type': 'text/plain'}