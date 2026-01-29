from flask import Blueprint, jsonify, request
from jwt_middleware import require_auth
import vm_monitor

# Definimos el Blueprint para las rutas de VM
vm_bp = Blueprint('vm', __name__)

@vm_bp.route('/api/vms', methods=['GET'])
@require_auth
def api_vms():
    """
    Obtiene la lista de todas las máquinas virtuales y contenedores LXC.
    """
    try:
        data = vm_monitor.get_proxmox_vms()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@vm_bp.route('/api/vms/<int:vmid>', methods=['GET'])
@require_auth
def get_vm_config(vmid):
    """
    Obtiene la configuración detallada de una VM específica.
    Incluye hardware, estado y datos de red.
    """
    try:
        data = vm_monitor.get_vm_config(vmid)
        if not data:
            return jsonify({'error': 'VM/LXC not found'}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@vm_bp.route('/api/vms/<int:vmid>/control', methods=['POST'])
@require_auth
def api_vm_control(vmid):
    """
    Controla el estado de una VM (start, stop, shutdown, reboot).
    """
    try:
        data = request.get_json()
        action = data.get('action')
        
        result = vm_monitor.control_vm(vmid, action)
        
        if result.get('success'):
            return jsonify(result)
        else:
            return jsonify(result), 500 if 'error' in result else 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@vm_bp.route('/api/vms/<int:vmid>/config', methods=['PUT'])
@require_auth
def api_vm_config_update(vmid):
    """
    Actualiza la configuración de una VM (por ejemplo, las notas/descripción).
    """
    try:
        data = request.get_json()
        description = data.get('description', '')
        
        result = vm_monitor.update_vm_config(vmid, description)
        
        if result.get('success'):
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@vm_bp.route('/api/vms/<int:vmid>/metrics', methods=['GET'])
@require_auth
def api_vm_metrics(vmid):
    """
    Obtiene métricas históricas (RRD) de CPU, Memoria y Red para una VM.
    """
    try:
        timeframe = request.args.get('timeframe', 'week')
        if timeframe not in ['hour', 'day', 'week', 'month', 'year']:
            return jsonify({'error': 'Invalid timeframe'}), 400
            
        data = vm_monitor.get_vm_metrics(vmid, timeframe)
        if 'error' in data:
            return jsonify(data), 500 if 'Failed' in data['error'] else 404
            
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@vm_bp.route('/api/vms/<int:vmid>/logs', methods=['GET'])
@require_auth
def api_vm_logs(vmid):
    """
    Obtiene los logs internos (consola/serial) de la VM/LXC.
    """
    try:
        data = vm_monitor.get_vm_logs(vmid)
        if 'error' in data:
            return jsonify(data), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@vm_bp.route('/api/task-log/<path:upid>', methods=['GET'])
@require_auth
def get_task_log(upid):
    """
    Obtiene el log completo de una tarea de Proxmox (ej. un backup o inicio de VM).
    El UPID es el identificador único de la tarea.
    """
    try:
        log_text = vm_monitor.get_task_log(upid)
        if log_text.startswith("Error") or log_text.startswith("Log file not found"):
             return jsonify({'error': log_text}), 404
             
        return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return jsonify({'error': str(e)}), 500