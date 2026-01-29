#!/usr/bin/env python3
"""
ProxMenux Flask Server (Entry Point)

Este script es el punto de entrada principal. Su función es:
1. Inicializar la aplicación Flask.
2. Configurar CORS.
3. Registrar todos los módulos (Blueprints) que hemos separado.
4. Servir la interfaz web (Frontend).
"""

import os
import sys
import logging
from flask import Flask, jsonify, send_file, send_from_directory
from flask_cors import CORS

# --- Importar Blueprints Existentes (Los que ya tenías y no hemos tocado) ---
from flask_auth_routes import auth_bp
from flask_health_routes import health_bp
from flask_proxmenux_routes import proxmenux_bp
from flask_terminal_routes import terminal_bp, init_terminal_routes

# --- Importar Nuevos Blueprints (Los 5 módulos que acabas de crear) ---
# Asegúrate de que los archivos .py se llamen exactamente así para que funcionen los imports:
from flask_system_routes import system_bp
from flask_storage_routes import storage_bp
from flask_network_routes import network_bp
from flask_vm_routes import vm_bp
from flask_hardware_routes import hardware_bp
from flask_script_routes import script_bp

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("proxmenux.server")

# Inicializar Flask
app = Flask(__name__)
CORS(app)  # Habilitar CORS para permitir peticiones desde el frontend

# -------------------------------------------------------------------
# Registro de Módulos (Blueprints)
# Aquí es donde "conectamos" todos los archivos separados a la app principal
# -------------------------------------------------------------------

# 1. Módulos de Utilidad y Autenticación
app.register_blueprint(auth_bp)
app.register_blueprint(health_bp)
app.register_blueprint(proxmenux_bp)
app.register_blueprint(terminal_bp)

# 2. Módulos Principales de Monitorización (Nuevos)
app.register_blueprint(system_bp)     # Rutas: /api/system, /api/logs, /api/events
app.register_blueprint(storage_bp)    # Rutas: /api/storage, /api/backups
app.register_blueprint(network_bp)    # Rutas: /api/network
app.register_blueprint(vm_bp)         # Rutas: /api/vms
app.register_blueprint(hardware_bp)   # Rutas: /api/hardware, /api/gpu
app.register_blueprint(script_bp)     # Rutas: /api/scripts

# Inicializar WebSocket para la terminal y ejecución de scripts
init_terminal_routes(app)

# -------------------------------------------------------------------
# Rutas del Frontend (Servir Dashboard Next.js estático)
# -------------------------------------------------------------------

@app.route('/')
def serve_dashboard():
    """Sirve la página principal (index.html) del dashboard."""
    try:
        # Detectar la raíz del AppImage o directorio actual
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            # Fallback para desarrollo: detectar ruta relativa
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        index_path = os.path.join(appimage_root, 'web', 'index.html')
        
        if os.path.exists(index_path):
            return send_file(index_path)
        
        # Si no encuentra el dashboard, mostrar mensaje de error útil en el navegador
        return f"""
        <html><body style="background:#111;color:#eee;font-family:sans-serif;padding:2rem;">
            <h1>ProxMenux Monitor</h1>
            <p>Dashboard not found at: {index_path}</p>
            <p>The API is running correctly. Check your AppImage build structure.</p>
        </body></html>
        """, 404
        
    except Exception as e:
        return jsonify({'error': f'Dashboard error: {str(e)}'}), 500

@app.route('/_next/<path:filename>')
def serve_next_static(filename):
    """Sirve archivos estáticos de Next.js (_next/static/...)."""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
                
        static_dir = os.path.join(appimage_root, 'web', '_next')
        return send_from_directory(static_dir, filename)
    except Exception:
        return '', 404

@app.route('/images/<path:filename>')
def serve_images(filename):
    """Sirve imágenes estáticas."""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
                
        image_dir = os.path.join(appimage_root, 'web', 'images')
        return send_from_directory(image_dir, filename)
    except Exception:
        return '', 404

@app.route('/<path:filename>')
def serve_static_files(filename):
    """Sirve archivos raíz (favicon, manifest, etc.)."""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
                
        web_dir = os.path.join(appimage_root, 'web')
        return send_from_directory(web_dir, filename)
    except Exception:
        return '', 404

@app.route('/api/info', methods=['GET'])
def api_info():
    """Endpoint raíz de la API para verificar funcionamiento y listar endpoints disponibles."""
    return jsonify({
        'name': 'ProxMenux Monitor API',
        'version': '1.0.3 (Modular)',
        'status': 'online',
        'endpoints': [
            '/api/system', 
            '/api/storage', 
            '/api/network', 
            '/api/vms', 
            '/api/hardware',
            '/api/gpu/realtime'
        ]
    })

if __name__ == '__main__':
    # Silenciar banner de Flask CLI para mantener logs limpios en la consola
    import sys
    try:
        cli = sys.modules['flask.cli']
        cli.show_server_banner = lambda *x: None
    except: pass
    
    # Iniciar servidor en el puerto 8008
    print("🚀 ProxMenux Monitor API (Modular) running on port 8008...")
    app.run(host='0.0.0.0', port=8008, debug=False)