from flask import Blueprint, jsonify, request, Response
from flask_script_runner import script_runner
import threading
import os

# Definimos el Blueprint
script_bp = Blueprint('script', __name__)

@script_bp.route('/api/scripts/execute', methods=['POST'])
def execute_script():
    """
    Ejecuta un script de bash con logs en tiempo real.
    Valida que el script esté dentro del directorio permitido.
    """
    try:
        data = request.json
        script_name = data.get('script_name')
        script_params = data.get('params', {})
        script_relative_path = data.get('script_relative_path')

        if not script_relative_path:
            return jsonify({'error': 'script_relative_path is required'}), 400

        # Directorio base seguro
        BASE_SCRIPTS_DIR = '/usr/local/share/proxmenux/scripts'
        script_path = os.path.join(BASE_SCRIPTS_DIR, script_relative_path)

        # Validación de seguridad básica (evitar path traversal)
        script_path = os.path.abspath(script_path)
        if not script_path.startswith(BASE_SCRIPTS_DIR):
            return jsonify({'error': 'Invalid script path'}), 403
        
        if not os.path.exists(script_path):
            return jsonify({'success': False, 'error': 'Script file not found'}), 404
        
        # Crear sesión y ejecutar en hilo separado
        session_id = script_runner.create_session(script_name)
        
        def run_script():
            script_runner.execute_script(script_path, session_id, script_params)
        
        thread = threading.Thread(target=run_script, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@script_bp.route('/api/scripts/status/<session_id>', methods=['GET'])
def get_script_status(session_id):
    """Obtiene el estado actual de una sesión de script."""
    try:
        status = script_runner.get_session_status(session_id)
        return jsonify(status)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@script_bp.route('/api/scripts/respond', methods=['POST'])
def respond_to_script():
    """
    Envía una respuesta (input de usuario) a un script interactivo
    que está esperando datos.
    """
    try:
        data = request.json
        session_id = data.get('session_id')
        interaction_id = data.get('interaction_id')
        value = data.get('value')
        
        result = script_runner.respond_to_interaction(session_id, interaction_id, value)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@script_bp.route('/api/scripts/logs/<session_id>', methods=['GET'])
def stream_script_logs(session_id):
    """
    Transmite los logs del script en tiempo real usando Server-Sent Events (SSE).
    """
    try:
        def generate():
            for log_entry in script_runner.stream_logs(session_id):
                yield f"data: {log_entry}\n\n"
        
        return Response(generate(), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500