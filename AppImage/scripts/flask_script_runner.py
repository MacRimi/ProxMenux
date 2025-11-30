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
        
        # Prepare environment
        env = os.environ.copy()
        env['EXECUTION_MODE'] = 'web'
        env['LOG_FILE'] = log_file
        
        if env_vars:
            env.update(env_vars)
        
        # Initialize log file
        with open(log_file, 'w') as f:
            f.write(json.dumps({
                'type': 'init',
                'session_id': session_id,
                'script': script_path,
                'timestamp': int(time.time())
            }) + '\n')
        
        try:
            # Execute script
            session['status'] = 'running'
            process = subprocess.Popen(
                ['/bin/bash', script_path],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            session['process'] = process
            
            # Monitor output for interactions
            def monitor_output():
                for line in process.stdout:
                    with open(log_file, 'a') as f:
                        f.write(line)
                    
                    # Check for interaction requests
                    try:
                        if line.strip().startswith('{'):
                            data = json.loads(line.strip())
                            if data.get('type') == 'interaction_request':
                                session['pending_interaction'] = data
                    except json.JSONDecodeError:
                        pass
            
            monitor_thread = threading.Thread(target=monitor_output, daemon=True)
            monitor_thread.start()
            
            # Wait for completion
            process.wait()
            monitor_thread.join(timeout=5)
            
            session['exit_code'] = process.returncode
            session['status'] = 'completed' if process.returncode == 0 else 'failed'
            session['end_time'] = datetime.now().isoformat()
            
            return {
                'success': True,
                'session_id': session_id,
                'exit_code': process.returncode,
                'log_file': log_file
            }
            
        except Exception as e:
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
