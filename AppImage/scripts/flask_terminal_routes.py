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
import re
import secrets
import select
import struct
import fcntl
import termios
import threading
import time
import requests
import json
import tempfile
import base64

from jwt_middleware import require_auth

# Allowed shape for interaction_id used as a file path component when writing
# the response file. Bounded length, no separators, no path traversal. See
# audit Tier 1 #11.
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# ─── WebSocket auth ticket pattern ───────────────────────────────────────
#
# The WebSocket browser API does not allow custom request headers, so we
# cannot send `Authorization: Bearer <jwt>` on the handshake. Instead the
# client first POSTs to /api/terminal/ticket (which DOES require the JWT) to
# receive a single-use, short-lived ticket. The ticket is then passed as a
# `?ticket=...` query string when opening the WebSocket. The handshake
# atomically consumes the ticket — if the ticket is missing, expired, or
# already used, the WS is closed immediately.
#
# Tickets live in an in-memory dict guarded by a lock. TTL is intentionally
# short (5 s) — the client should issue and use the ticket immediately.
# See audit Tier 1 #2 + #17d.

_TERMINAL_TICKETS = {}     # ticket (str) -> created_at_ts (float)
_TICKETS_LOCK = threading.Lock()
_TICKET_TTL = 5            # seconds
_TICKET_MAX_INFLIGHT = 256 # sanity cap to keep memory bounded


def _issue_terminal_ticket():
    """Issue a fresh ticket and prune expired entries while holding the lock."""
    now = time.time()
    cutoff = now - _TICKET_TTL
    ticket = secrets.token_urlsafe(32)
    with _TICKETS_LOCK:
        # Prune expired tickets first.
        if _TERMINAL_TICKETS:
            for k in [k for k, v in _TERMINAL_TICKETS.items() if v < cutoff]:
                _TERMINAL_TICKETS.pop(k, None)
        # Hard cap as a defense against accidental leaks.
        if len(_TERMINAL_TICKETS) >= _TICKET_MAX_INFLIGHT:
            # Drop the oldest to make room (FIFO-ish; dict preserves insertion order).
            try:
                oldest = next(iter(_TERMINAL_TICKETS))
                _TERMINAL_TICKETS.pop(oldest, None)
            except StopIteration:
                pass
        _TERMINAL_TICKETS[ticket] = now
    return ticket


def _consume_terminal_ticket(ticket):
    """Validate and atomically consume a ticket. Returns True iff valid + fresh."""
    if not ticket or not isinstance(ticket, str):
        return False
    now = time.time()
    with _TICKETS_LOCK:
        ts = _TERMINAL_TICKETS.pop(ticket, None)
    if ts is None:
        return False
    return (now - ts) <= _TICKET_TTL


def _ws_auth_check():
    """Return True iff the current WebSocket handshake is authorized to proceed.

    When auth is enabled and not declined, require a single-use ticket in the
    `ticket` query parameter. When auth is disabled (fresh install or user
    explicitly skipped setup), allow the handshake to proceed unauthenticated
    — same semantics as the @require_auth decorator on REST routes.
    """
    try:
        from auth_manager import load_auth_config
        config = load_auth_config()
        if not config.get("enabled", False) or config.get("declined", False):
            return True
    except Exception:
        # If auth status can't be loaded (DB error / missing module), fail
        # closed — better to refuse a terminal than to grant root unauth.
        return False
    return _consume_terminal_ticket(request.args.get('ticket', ''))

terminal_bp = Blueprint('terminal', __name__)
sock = Sock()

# Active terminal sessions
active_sessions = {}

@terminal_bp.route('/api/terminal/health', methods=['GET'])
def terminal_health():
    """Health check for terminal service"""
    return {'success': True, 'active_sessions': len(active_sessions)}


@terminal_bp.route('/api/terminal/ticket', methods=['POST'])
@require_auth
def issue_terminal_ticket_route():
    """Issue a single-use, short-lived ticket for opening a terminal WebSocket.

    The browser WebSocket API doesn't support custom request headers, so the
    Bearer token we use for REST calls cannot be sent on the handshake. The
    client POSTs here (with the Bearer token), receives a one-shot ticket,
    and immediately opens the WS appending `?ticket=<value>`. See audit
    Tier 1 #17d.
    """
    return jsonify({
        'success': True,
        'ticket': _issue_terminal_ticket(),
        'ttl_seconds': _TICKET_TTL,
    })

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

    # Validate the single-use auth ticket BEFORE opening any pty / spawning bash.
    # If the ticket is missing or invalid (and auth is enabled), refuse the
    # handshake — otherwise this endpoint is a root shell available to anyone
    # who can reach the port. See audit Tier 1 #2.
    if not _ws_auth_check():
        try:
            ws.send(json.dumps({"type": "error", "message": "Unauthorized"}))
        except Exception:
            pass
        try:
            ws.close()
        except Exception:
            pass
        return

    # Create pseudo-terminal
    master_fd, slave_fd = pty.openpty()

    # Start bash process. Issue #182:
    # - `-li` (login + interactive) so /etc/profile + ~/.bash_profile +
    #   ~/.profile + ~/.bashrc all run — without this, Starship / atuin /
    #   ble.sh / nerd font configurations never load.
    # - PS1 was hardcoded in env, which overrode the user's ~/.bashrc
    #   PS1 every time. Drop it so the user's prompt wins.
    # - COLORTERM=truecolor unlocks 24-bit (true color) rendering in
    #   xterm.js, required by Nerd Fonts / Starship icons.
    # - LANG/LC_ALL UTF-8 fallback so non-ASCII glyphs (Nerd Font icons,
    #   accented hostnames) render correctly even on systems where the
    #   user's profile didn't already set a locale.
    _term_env = os.environ.copy()
    _term_env.setdefault('TERM', 'xterm-256color')
    _term_env.setdefault('COLORTERM', 'truecolor')
    _term_env.setdefault('LANG', 'C.UTF-8')
    _term_env.setdefault('LC_ALL', 'C.UTF-8')
    _term_env.pop('PS1', None)
    _home = _term_env.get('HOME') or os.path.expanduser('~') or '/root'

    shell_process = subprocess.Popen(
        ['/bin/bash', '-li'],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        cwd=_home,
        env=_term_env,
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

                if isinstance(msg, dict):
                    msg_type = msg.get('type')
                    
                    # Handle ping messages (heartbeat to keep connection alive)
                    if msg_type == 'ping':
                        try:
                            ws.send(json.dumps({'type': 'pong'}))
                        except:
                            pass
                        handled = True
                    
                    # Handle resize messages
                    elif msg_type == 'resize':
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

    # Auth gate first — see /ws/terminal for the rationale. Without this an
    # unauth attacker who can craft an `init_data` payload pointing at any
    # bash script gets remote code execution as root. See audit Tier 1 #2.
    if not _ws_auth_check():
        try:
            ws.send('{"type": "error", "message": "Unauthorized"}\r\n')
        except Exception:
            pass
        try:
            ws.close()
        except Exception:
            pass
        return

    # Limit script execution to a known directory. The previous code accepted
    # any absolute path and ran it as root via `bash <path>`. See audit Tier 1 #3.
    BASE_SCRIPTS_DIR = '/usr/local/share/proxmenux/scripts'
    try:
        _SCRIPTS_DIR_REAL = os.path.realpath(BASE_SCRIPTS_DIR)
    except (OSError, ValueError):
        _SCRIPTS_DIR_REAL = BASE_SCRIPTS_DIR

    try:
        init_data = ws.receive(timeout=10)

        if not init_data:
            error_msg = '{"type": "error", "message": "No script data received"}\r\n'
            ws.send(error_msg)
            return

        script_data = json.loads(init_data)

        script_path = script_data.get('script_path')
        params = script_data.get('params', {})

        if not script_path or not isinstance(script_path, str):
            error_msg = '{"type": "error", "message": "No script_path provided"}\r\n'
            ws.send(error_msg)
            return

        # Confine script_path to BASE_SCRIPTS_DIR. realpath collapses `..`
        # and resolves symlinks; commonpath catches both `/some/other/dir`
        # and `/usr/local/share/proxmenux/scripts-evil` (which a startswith
        # check would miss).
        try:
            real_script = os.path.realpath(script_path)
            if os.path.commonpath([real_script, _SCRIPTS_DIR_REAL]) != _SCRIPTS_DIR_REAL:
                ws.send('{"type": "error", "message": "Script path is outside the allowed directory"}\r\n')
                return
        except (OSError, ValueError):
            ws.send('{"type": "error", "message": "Invalid script path"}\r\n')
            return

        if not os.path.exists(real_script):
            error_msg = '{"type": "error", "message": "Script not found"}\r\n'
            ws.send(error_msg)
            return
        # Use the resolved path for execution downstream so a symlink swap
        # between this check and Popen() cannot redirect us elsewhere.
        script_path = real_script

    except Exception as e:
        error_msg = f'{{"type": "error", "message": "Invalid init data: {str(e)}"}}\r\n'
        ws.send(error_msg)
        return
    
    web_log_fd, web_log_path = tempfile.mkstemp(suffix='.log', prefix='proxmenux_web_')
    
    # Create pseudo-terminal for script execution
    master_fd, slave_fd = pty.openpty()
    
    env = os.environ.copy()
    env['EXECUTION_MODE'] = 'web'
    env['WEB_LOG'] = web_log_path
    for key, value in params.items():
        env[key] = str(value)
    env['PYTHONUNBUFFERED'] = '1'
    env['TERM'] = 'xterm-256color'
    
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
    
    def monitor_web_log():
        last_position = 0
        
        while script_process.poll() is None:
            try:
                if os.path.exists(web_log_path):
                    with open(web_log_path, 'r') as f:
                        f.seek(last_position)
                        new_lines = f.readlines()
                        last_position = f.tell()
                        
                        for line in new_lines:
                            line = line.strip()
                            if line.startswith('WEB_INTERACTION:'):
                                try:
                                    # Parse: WEB_INTERACTION:type:id:title_b64:message_b64[:options_json]
                                    parts = line[16:].split(':', 4)
                                    interaction_type = parts[0]
                                    interaction_id = parts[1]
                                    title_b64 = parts[2]
                                    message_b64 = parts[3]
                                    
                                    title = base64.b64decode(title_b64).decode('utf-8')
                                    message = base64.b64decode(message_b64).decode('utf-8')
                                    
                                    interaction_data = {
                                        'type': 'web_interaction',
                                        'interaction': {
                                            'type': interaction_type,
                                            'id': interaction_id,
                                            'title': title,
                                            'message': message
                                        }
                                    }
                                    
                                    # Parse options for menu
                                    if interaction_type == 'menu' and len(parts) > 4:
                                        options_json = parts[4]
                                        interaction_data['interaction']['options'] = json.loads(options_json)
                                    
                                    # Parse default for inputbox
                                    if interaction_type == 'inputbox' and len(parts) > 4:
                                        default_b64 = parts[4]
                                        interaction_data['interaction']['default'] = base64.b64decode(default_b64).decode('utf-8')
                                    
                                    # Send interaction to WebSocket
                                    ws.send(json.dumps(interaction_data))
                                    
                                except Exception as e:
                                    pass
                
                time.sleep(0.01)
            except Exception as e:
                break
    
    web_log_thread = threading.Thread(target=monitor_web_log, daemon=True)
    web_log_thread.start()
    
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
                        
                        # Send raw text to terminal
                        try:
                            ws.send(text)
                        except Exception as e:
                            break
                            
                    except OSError as e:
                        break
            except Exception as e:
                break
        
        script_process.wait()
        exit_code = script_process.returncode if script_process.returncode is not None else 0
        
        try:
            ws.send(f'\r\n[Script exited with code {exit_code}]\r\n')
        except Exception as e:
            pass
    
    output_thread = threading.Thread(target=read_script_output, daemon=True)
    output_thread.start()
    
    try:
        while True:
            data = ws.receive(timeout=None)
            
            if data is None:
                break
            
            try:
                msg = json.loads(data)
                
                if msg.get('type') == 'interaction_response':
                    interaction_id = msg.get('id')
                    value = msg.get('value')

                    # interaction_id is interpolated into a /tmp/ filename; if
                    # the client supplies traversal characters they could write
                    # arbitrary files as root (e.g. poison /etc/proxmenux/auth.json).
                    # Reject anything that doesn't match the safe-id shape.
                    if not isinstance(interaction_id, str) or not _SAFE_ID_RE.match(interaction_id):
                        continue
                    if not isinstance(value, str):
                        continue

                    # Write response to the file the script is waiting for.
                    response_file = f"/tmp/proxmenux_response_{interaction_id}"

                    with open(response_file, 'w') as f:
                        f.write(value)

                    continue
                
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
                except OSError as e:
                    break
            
            if script_process.poll() is not None:
                break
                
    except Exception as e:
        pass
    finally:
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
        
        try:
            os.close(web_log_fd)
            os.unlink(web_log_path)
        except:
            pass

def init_terminal_routes(app):
    """Initialize terminal routes with Flask app"""
    sock.init_app(app)
    app.register_blueprint(terminal_bp)
