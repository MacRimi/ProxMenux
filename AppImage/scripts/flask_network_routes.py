from flask import Blueprint, jsonify, request
from jwt_middleware import require_auth
import network_monitor

# Definimos el Blueprint para las rutas de red
network_bp = Blueprint('network', __name__)

@network_bp.route('/api/network', methods=['GET'])
@require_auth
def api_network():
    """
    Obtiene información completa de todas las interfaces de red.
    Incluye interfaces físicas, virtuales, puentes, bonds y tráfico actual.
    """
    try:
        data = network_monitor.get_network_info()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_bp.route('/api/network/summary', methods=['GET'])
@require_auth
def api_network_summary():
    """
    Obtiene un resumen optimizado de la red.
    Ideal para paneles de control donde no se requiere detalle profundo de cada configuración.
    """
    try:
        data = network_monitor.get_network_summary()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@network_bp.route('/api/network/<interface_name>/metrics', methods=['GET'])
@require_auth
def api_network_interface_metrics(interface_name):
    """
    Obtiene métricas históricas (RRD) para una interfaz específica.
    Soporta diferentes periodos de tiempo (hour, day, week, month, year).
    """
    try:
        timeframe = request.args.get('timeframe', 'day')
        # Validar timeframe básico para evitar errores en pvesh
        if timeframe not in ['hour', 'day', 'week', 'month', 'year']:
            return jsonify({'error': 'Invalid timeframe'}), 400
            
        data = network_monitor.get_interface_metrics(interface_name, timeframe)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500