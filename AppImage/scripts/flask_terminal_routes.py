#!/usr/bin/env python3
"""
ProxMenux Terminal WebSocket Routes
Provides a WebSocket endpoint for interactive terminal sessions
"""

from flask import Blueprint, jsonify, request
from flask_sock import Sock
import subprocess
import os
import pty
import select
import struct
import fcntl
import termios
import threading
import time
import requests
import json

terminal_bp = Blueprint('terminal', __name__)
sock = Sock()

# Active terminal sessions
active_sessions = {}

@terminal_bp.route('/api/terminal/health', methods=['GET'])
def terminal_health():
    """Health check for terminal service"""
    return {'success': True, 'active_sessions': len(active_sessions)}

@terminal_bp.route('/api/terminal/search-command', methods=['GET'])
def search_command():
    """Proxy endpoint for cheat.sh API to avoid CORS issues"""
    query = request.args.get('q', '')
    
    if not query or len(query) < 2:
        return jsonify({'error': 'Query too short'}), 400
    
    try:
        url = f'https://cht.sh/{query.replace(" ", "+")}?QT'
        headers = {
            'User-Agent': 'curl/7.68.0'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            content = response.text
            examples = []
            current_description = []
            
            for line in content.split('\n'):
                stripped = line.strip()
                
                # Ignorar líneas vacías
                if not stripped:
                    continue
                
                # Si es un comentario
                if stripped.startswith('#'):
                    # Acumular descripciones
                    current_description.append(stripped[1:].strip())
                # Si no es comentario, es un comando
                elif stripped and not stripped.startswith('http'):
                    # Unir las descripciones acumuladas
                    description = ' '.join(current_description) if current_description else ''
                    
                    examples.append({
                        'description': description,
                        'command': stripped
                    })
                    
                    # Resetear descripciones para el siguiente comando
                    current_description = []
            
            return jsonify({
                'success': True,
                'examples': examples
            })
        else:
            return jsonify({
                'success': False,
                'error': f'API returned status {response.status_code}'
            }), response.status_code
            
    except requests.Timeout:
        return jsonify({
            'success': False,
            'error': 'Request timeout'
        }), 504
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def set_winsize(fd, rows, cols):
    """Set terminal window size"""
    try:
        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception as e:
        print(f"Error setting window size: {e}")

def read_and_forward_output(master_fd, ws):
    """Read from PTY and send to WebSocket"""
    while True:
        try:
            # Use select with timeout to check if data is available
            r, _, _ = select.select([master_fd], [], [], 0.01)
            if master_fd in r:
                try:
                    data = os.read(master_fd, 4096)
                    if data:
                        ws.send(data.decode('utf-8', errors='ignore'))
                    else:
                        break
                except OSError:
                    break
        except Exception as e:
            print(f"Error reading from PTY: {e}")
            break

@sock.route('/ws/terminal')
def terminal_websocket(ws):
    """WebSocket endpoint for terminal sessions"""
    
    # Create pseudo-terminal
    master_fd, slave_fd = pty.openpty()
    
    # Start bash process
    shell_process = subprocess.Popen(
        ['/bin/bash', '-i'],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        cwd='/',
        env=dict(os.environ, TERM='xterm-256color', PS1='\\u@\\h:\\w\\$ ')
    )
    
    session_id = id(ws)
    active_sessions[session_id] = {
        'process': shell_process,
        'master_fd': master_fd
    }
    
    # Set non-blocking mode for master_fd
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    
    # Set initial terminal size
    set_winsize(master_fd, 30, 120)
    
    # Start thread to read PTY output and forward to WebSocket
    output_thread = threading.Thread(
        target=read_and_forward_output,
        args=(master_fd, ws),
        daemon=True
    )
    output_thread.start()
    
    try:
        while True:
            # Receive data from WebSocket (blocking)
            data = ws.receive(timeout=None)
            
            if data is None:
                # Client closed connection
                break

            handled = False

            # Try to handle JSON control messages (e.g. resize)
            if isinstance(data, str):
                try:
                    msg = json.loads(data)
                except Exception:
                    msg = None

                if isinstance(msg, dict) and msg.get('type') == 'resize':
                    cols = int(msg.get('cols', 120))
                    rows = int(msg.get('rows', 30))
                    set_winsize(master_fd, rows, cols)
                    handled = True

            if handled:
                # Control message processed, do not send to bash
                continue

            # Optional: legacy resize escape sequence support
            if isinstance(data, str) and data.startswith('\x1b[8;'):
                try:
                    parts = data[4:-1].split(';')
                    rows, cols = int(parts[0]), int(parts[1])
                    set_winsize(master_fd, rows, cols)
                    continue
                except Exception:
                    pass
            
            # Send input to bash
            try:
                os.write(master_fd, data.encode('utf-8'))
            except OSError as e:
                print(f"Error writing to PTY: {e}")
                break
            
            # Check if process is still alive
            if shell_process.poll() is not None:
                break
                
    except Exception as e:
        print(f"Terminal session error: {e}")
    finally:
        # Cleanup
        try:
            shell_process.terminate()
            shell_process.wait(timeout=1)
        except:
            try:
                shell_process.kill()
            except:
                pass
        
        try:
            os.close(master_fd)
        except:
            pass
        
        try:
            os.close(slave_fd)
        except:
            pass
        
        if session_id in active_sessions:
            del active_sessions[session_id]

@sock.route('/ws/script/<session_id>')
def script_websocket(ws, session_id):
    """WebSocket endpoint for executing scripts with hybrid web mode"""
    
    try:
        init_data = ws.receive(timeout=10)
        if not init_data:
            ws.send('{"type": "error", "message": "No script data received"}\r\n')
            return
            
        script_data = json.loads(init_data)
        script_path = script_data.get('script_path')
        params = script_data.get('params', {})
        
        if not script_path:
            ws.send('{"type": "error", "message": "No script_path provided"}\r\n')
            return
            
    except Exception as e:
        ws.send(f'{{"type": "error", "message": "Invalid init data: {str(e)}"}}\r\n')
        return
    
    # Create pseudo-terminal for script execution
    master_fd, slave_fd = pty.openpty()
    
    # Build environment variables from params
    env = os.environ.copy()
    for key, value in params.items():
        env[key] = str(value)
    
    # Start script process with PTY
    script_process = subprocess.Popen(
        ['/bin/bash', script_path],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        env=env
    )
    
    # Set non-blocking mode for master_fd
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    
    # Set terminal size
    set_winsize(master_fd, 30, 120)
    
    # Thread to read script output and forward to WebSocket
    def read_script_output():
        while True:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.01)
                if master_fd in r:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        
                        text = data.decode('utf-8', errors='ignore')
                        
                        # Send raw text to terminal (TerminalPanel expects plain text)
                        try:
                            ws.send(text)
                        except Exception:
                            break
                            
                    except OSError:
                        break
            except Exception as e:
                print(f"Error reading script output: {e}")
                break
        
        script_process.wait()
        exit_code = script_process.returncode if script_process.returncode is not None else 0
        
        # Only send exit message if WebSocket is still open
        try:
            ws.send(f'\r\n[Script exited with code {exit_code}]\r\n')
        except Exception:
            pass
    
    output_thread = threading.Thread(target=read_script_output, daemon=True)
    output_thread.start()
    
    try:
        while True:
            # Receive user input or interaction responses
            data = ws.receive(timeout=None)
            
            if data is None:
                break
            
            try:
                msg = json.loads(data)
                
                # Handle resize
                if msg.get('type') == 'resize':
                    cols = int(msg.get('cols', 120))
                    rows = int(msg.get('rows', 30))
                    set_winsize(master_fd, rows, cols)
                    continue
                    
            except json.JSONDecodeError:
                # Raw text input, send to script
                try:
                    os.write(master_fd, data.encode('utf-8'))
                except OSError:
                    break
            
            # Check if process is still alive
            if script_process.poll() is not None:
                break
                
    except Exception as e:
        print(f"Script session error: Connection closed: {e}")
    finally:
        # Cleanup
        try:
            script_process.terminate()
            script_process.wait(timeout=1)
        except:
            try:
                script_process.kill()
            except:
                pass
        
        try:
            os.close(master_fd)
        except:
            pass
        
        try:
            os.close(slave_fd)
        except:
            pass

def init_terminal_routes(app):
    """Initialize terminal routes with Flask app"""
    sock.init_app(app)
    app.register_blueprint(terminal_bp)
