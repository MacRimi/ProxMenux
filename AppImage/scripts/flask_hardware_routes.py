from flask import Blueprint, jsonify
from jwt_middleware import require_auth
import hardware_monitor

# Definimos el Blueprint
hardware_bp = Blueprint('hardware', __name__)

@hardware_bp.route('/api/hardware', methods=['GET'])
@require_auth
def api_hardware():
    """
    Obtiene información completa y agregada de todo el hardware.
    Incluye CPU, Placa Base, RAM, Discos, GPUs, IPMI y UPS.
    """
    try:
        data = hardware_monitor.get_hardware_info()
        return jsonify(data)
    except Exception as e:
        # En caso de error crítico, devolvemos un 500 pero intentamos ser descriptivos
        return jsonify({'error': str(e)}), 500

@hardware_bp.route('/api/gpu/<slot>/realtime', methods=['GET'])
@require_auth
def api_gpu_realtime(slot):
    """
    Obtiene métricas en tiempo real (uso, temperatura, memoria) para una GPU específica.
    El 'slot' es la dirección PCI (ej: '01:00.0').
    """
    try:
        data = hardware_monitor.get_gpu_realtime_data(slot)
        
        if not data:
            return jsonify({'error': 'GPU not found'}), 404
            
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500