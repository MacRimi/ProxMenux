#!/usr/bin/env python3
"""
ProxMenux Terminal WebSocket Routes
Provides a WebSocket endpoint for interactive terminal sessions
"""

from flask import Blueprint
from flask_sock import Sock
import subprocess
import os
import pty
import select
import struct
import fcntl
import termios
import signal

terminal_bp = Blueprint('terminal', __name__)
sock = Sock()

# Active terminal sessions
active_sessions = {}

@terminal_bp.route('/api/terminal/health', methods=['GET'])
def terminal_health():
    """Health check for terminal service"""
    return {'success': True, 'active_sessions': len(active_sessions)}

def set_winsize(fd, rows, cols):
    """Set terminal window size"""
    try:
        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception as e:
        print(f"Error setting window size: {e}")

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
    set_winsize(master_fd, 24, 80)
    
    try:
        while True:
            # Use select to wait for data from either WebSocket or PTY
            readable, _, _ = select.select([ws.sock, master_fd], [], [], 0.1)
            
            # Read from WebSocket (user input)
            if ws.sock in readable:
                try:
                    data = ws.receive(timeout=0)
                    if data is None:
                        break
                    
                    # Handle special commands (optional)
                    if data.startswith('\x1b[8;'):  # Terminal resize
                        # Parse resize: ESC[8;{rows};{cols}t
                        try:
                            parts = data[4:-1].split(';')
                            rows, cols = int(parts[0]), int(parts[1])
                            set_winsize(master_fd, rows, cols)
                        except:
                            pass
                    else:
                        # Send input to bash
                        os.write(master_fd, data.encode('utf-8'))
                except:
                    break
            
            # Read from PTY (bash output)
            if master_fd in readable:
                try:
                    output = os.read(master_fd, 4096)
                    if output:
                        ws.send(output.decode('utf-8', errors='ignore'))
                except OSError:
                    # PTY closed
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
            shell_process.kill()
        
        os.close(master_fd)
        os.close(slave_fd)
        
        if session_id in active_sessions:
            del active_sessions[session_id]
        
        ws.close()

def init_terminal_routes(app):
    """Initialize terminal routes with Flask app"""
    sock.init_app(app)
    app.register_blueprint(terminal_bp)
