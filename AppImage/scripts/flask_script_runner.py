#!/usr/bin/env python3
"""
Script Runner System for ProxMenux
Executes bash scripts and provides real-time log streaming with interactive menu support
"""

import os
import sys
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
import uuid

class ScriptRunner:
    """Manages script execution with real-time log streaming and menu interactions"""
    
    def __init__(self):
        self.active_sessions = {}
        self.log_dir = Path("/var/log/proxmenux/scripts")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.interaction_handlers = {}
    
    def create_session(self, script_name):
        """Create a new script execution session"""
        session_id = str(uuid.uuid4())[:8]
        log_file = self.log_dir / f"{script_name}_{session_id}_{int(time.time())}.log"
        
        self.active_sessions[session_id] = {
            'script_name': script_name,
            'log_file': str(log_file),
            'start_time': datetime.now().isoformat(),
            'status': 'initializing',
            'process': None,
            'exit_code': None,
            'pending_interaction': None
        }
        
        return session_id
    
    def execute_script(self, script_path, session_id, env_vars=None):
        """Execute a script in web mode with logging"""
        if session_id not in self.active_sessions:
            return {'success': False, 'error': 'Invalid session ID'}
        
        session = self.active_sessions[session_id]
        log_file = session['log_file']
        
        print(f"[DEBUG] execute_script called for session {session_id}", file=sys.stderr, flush=True)
        print(f"[DEBUG] Script path: {script_path}", file=sys.stderr, flush=True)
        print(f"[DEBUG] Log file: {log_file}", file=sys.stderr, flush=True)
        
        # Prepare environment
        env = os.environ.copy()
        env['EXECUTION_MODE'] = 'web'
        env['LOG_FILE'] = log_file
        
        if env_vars:
            env.update(env_vars)
        
        print(f"[DEBUG] Environment variables set: EXECUTION_MODE=web, LOG_FILE={log_file}", file=sys.stderr, flush=True)
        
        # Initialize log file
        with open(log_file, 'w') as f:
            init_line = json.dumps({
                'type': 'init',
                'session_id': session_id,
                'script': script_path,
                'timestamp': int(time.time())
            }) + '\n'
            f.write(init_line)
            print(f"[DEBUG] Wrote init line to log: {init_line.strip()}", file=sys.stderr, flush=True)
        
        try:
            # Execute script
            session['status'] = 'running'
            print(f"[DEBUG] Starting subprocess with /bin/bash {script_path}", file=sys.stderr, flush=True)
            
            process = subprocess.Popen(
                ['/bin/bash', script_path],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0  # Unbuffered
            )
            
            print(f"[DEBUG] Process started with PID: {process.pid}", file=sys.stderr, flush=True)
            session['process'] = process
            
            lines_read = [0]  # Lista para compartir entre threads
            
            def monitor_output():
                print(f"[DEBUG] monitor_output thread started for session {session_id}", file=sys.stderr, flush=True)
                print(f"[DEBUG] Will monitor log file: {log_file}", file=sys.stderr, flush=True)
                
                try:
                    # Read log file in real-time (similar to tail -f)
                    last_position = 0
                    
                    # Wait a moment for script to start writing
                    time.sleep(0.5)
                    
                    while process.poll() is None or last_position < os.path.getsize(log_file):
                        try:
                            if os.path.exists(log_file):
                                with open(log_file, 'r') as log_f:
                                    log_f.seek(last_position)
                                    new_lines = log_f.readlines()
                                    
                                    for line in new_lines:
                                        decoded_line = line.rstrip()
                                        if decoded_line:  # Skip empty lines
                                            lines_read[0] += 1
                                            print(f"[DEBUG] Read line {lines_read[0]} from log: {decoded_line[:100]}...", file=sys.stderr, flush=True)
                                            
                                            # Check for interaction requests in the line
                                            if 'WEB_INTERACTION:' in decoded_line:
                                                print(f"[DEBUG] Detected WEB_INTERACTION line: {decoded_line}", file=sys.stderr, flush=True)
                                                session['pending_interaction'] = decoded_line
                                    
                                    last_position = log_f.tell()
                        
                        except Exception as e:
                            print(f"[DEBUG ERROR] Error reading log file: {e}", file=sys.stderr, flush=True)
                        
                        time.sleep(0.1)  # Poll every 100ms
                    
                    print(f"[DEBUG] monitor_output thread finished. Total lines read: {lines_read[0]}", file=sys.stderr, flush=True)
                    
                except Exception as e:
                    print(f"[DEBUG ERROR] Exception in monitor_output: {e}", file=sys.stderr, flush=True)
            
            monitor_thread = threading.Thread(target=monitor_output, daemon=False)
            monitor_thread.start()
            
            print(f"[DEBUG] Waiting for process to complete...", file=sys.stderr, flush=True)
            
            # Wait for completion
            process.wait()
            print(f"[DEBUG] Process exited with code: {process.returncode}", file=sys.stderr, flush=True)
            
            monitor_thread.join(timeout=30)
            if monitor_thread.is_alive():
                print(f"[DEBUG WARNING] monitor_thread still alive after 30s timeout", file=sys.stderr, flush=True)
            else:
                print(f"[DEBUG] monitor_thread joined successfully", file=sys.stderr, flush=True)
            
            session['exit_code'] = process.returncode
            session['status'] = 'completed' if process.returncode == 0 else 'failed'
            session['end_time'] = datetime.now().isoformat()
            
            print(f"[DEBUG] Script execution completed. Lines captured: {lines_read[0]}", file=sys.stderr, flush=True)
            
            return {
                'success': True,
                'session_id': session_id,
                'exit_code': process.returncode,
                'log_file': log_file
            }
            
        except Exception as e:
            print(f"[DEBUG ERROR] Exception in execute_script: {e}", file=sys.stderr, flush=True)
            session['status'] = 'error'
            session['error'] = str(e)
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_session_status(self, session_id):
        """Get current status of a script execution session"""
        if session_id not in self.active_sessions:
            return {'success': False, 'error': 'Session not found'}
        
        session = self.active_sessions[session_id]
        return {
            'success': True,
            'session_id': session_id,
            'status': session['status'],
            'start_time': session['start_time'],
            'script_name': session['script_name'],
            'exit_code': session['exit_code'],
            'pending_interaction': session.get('pending_interaction')
        }
    
    def respond_to_interaction(self, session_id, interaction_id, value):
        """Respond to a script interaction request"""
        if session_id not in self.active_sessions:
            return {'success': False, 'error': 'Session not found'}
        
        session = self.active_sessions[session_id]
        
        # Write response to file that script is waiting for
        response_file = f"/tmp/nvidia_response_{interaction_id}.json"
        with open(response_file, 'w') as f:
            json.dump({
                'interaction_id': interaction_id,
                'value': value,
                'timestamp': int(time.time())
            }, f)
        
        # Clear pending interaction
        session['pending_interaction'] = None
        
        return {'success': True}
    
    def stream_logs(self, session_id):
        """Generator that yields log entries as they are written"""
        if session_id not in self.active_sessions:
            yield json.dumps({'type': 'error', 'message': 'Invalid session ID'})
            return
        
        session = self.active_sessions[session_id]
        log_file = session['log_file']
        
        # Wait for log file to be created
        timeout = 10
        start = time.time()
        while not os.path.exists(log_file) and (time.time() - start) < timeout:
            time.sleep(0.1)
        
        if not os.path.exists(log_file):
            yield json.dumps({'type': 'error', 'message': 'Log file not created'})
            return
        
        # Stream log file
        with open(log_file, 'r') as f:
            # Start from beginning
            f.seek(0)
            
            while session['status'] in ['initializing', 'running']:
                line = f.readline()
                if line:
                    # Try to parse as JSON, yield as-is if not JSON
                    try:
                        log_entry = json.loads(line.strip())
                        yield json.dumps(log_entry)
                    except json.JSONDecodeError:
                        yield json.dumps({'type': 'raw', 'message': line.strip()})
                else:
                    time.sleep(0.1)
            
            # Read any remaining lines after completion
            for line in f:
                try:
                    log_entry = json.loads(line.strip())
                    yield json.dumps(log_entry)
                except json.JSONDecodeError:
                    yield json.dumps({'type': 'raw', 'message': line.strip()})
    
    def cleanup_session(self, session_id):
        """Clean up a completed session"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            return {'success': True}
        return {'success': False, 'error': 'Session not found'}

# Global instance
script_runner = ScriptRunner()
