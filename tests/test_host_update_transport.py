"""Real HTTP + WebSocket + PTY under the same gevent patch as Monitor.

Authentication boundaries use synthetic identities; full JWT verification is
covered separately. The sole executable is an inert temporary shell script.
"""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def wire_fixture():
    import json
    import shlex
    import tempfile
    import time
    from types import ModuleType
    import requests
    from flask import Flask
    from gevent.pywsgi import WSGIServer
    from simple_websocket import Client
    sys.path.insert(0, str(ROOT / 'AppImage/scripts'))
    auth = ModuleType('auth_manager')
    auth.load_auth_config = lambda: {'enabled': True}
    auth.verify_token = lambda token: 'fixture' if token == 'valid' else None
    auth.verify_token_full = lambda token: ('fixture', 'full_admin') if token == 'valid' else ('fixture', 'read_only') if token == 'read-only' else (None, None)
    sys.modules['auth_manager'] = auth
    import flask_terminal_routes as routes
    import host_update_jobs as jobs
    callbacks = []
    routes._host_update_completed = lambda *args: callbacks.append(args)
    app = Flask(__name__)
    app.register_blueprint(routes.terminal_bp)
    routes.sock.init_app(app)
    server = WSGIServer(('127.0.0.1', 0), app, log=None)
    server.start()
    base = f'http://127.0.0.1:{server.server_port}'
    headers = {'Authorization': 'Bearer valid'}
    def wait(predicate):
        end = time.monotonic() + 5
        while not predicate():
            assert time.monotonic() < end, 'fixture timeout'
            time.sleep(.01)
    def ticket():
        response = requests.post(base + '/api/terminal/ticket', headers=headers, timeout=3)
        assert response.status_code == 200
        return response.json()['ticket']
    def connect(identity, resume):
        client = Client(base.replace('http:', 'ws:') + '/ws/host-update/' + identity + '?ticket=' + ticket())
        client.send(json.dumps(dict(resume=resume, offset=0)))
        return client
    try:
        with tempfile.TemporaryDirectory(prefix='host-update-wire-') as folder:
            folder = Path(folder)
            gate, events, script = [folder / n for n in ('release', 'events', 'update.sh')]
            script.write_text(f'echo start >> {shlex.quote(str(events))}\n'
                              f'while [ ! -f {shlex.quote(str(gate))} ]; do sleep .02; done\n'
                              f'echo poststep >> {shlex.quote(str(events))}\necho completed\n')
            jobs.SCRIPT = str(script)
            viewer = connect('one-host-run', False)
            wait(events.exists)
            if viewer.connected:
                viewer.close()
            assert requests.get(base + '/api/host-update-jobs', headers={'Authorization': 'Bearer expired'}, timeout=3).status_code == 401
            assert requests.post(base + '/api/terminal/ticket', headers={'Authorization': 'Bearer read-only'}, timeout=3).status_code == 403
            listed = requests.get(base + '/api/host-update-jobs', headers=headers, timeout=3).json()['jobs']
            assert listed[0]['id'] == 'one-host-run'
            viewer = connect('one-host-run', True)
            gate.touch()
            frames = []
            while not frames or frames[-1]['type'] != 'script_complete':
                message = viewer.receive(timeout=5)
                assert message is not None
                frames.append(json.loads(message))
            assert frames[-1]['exit_code'] == 0
            assert events.read_text().splitlines() == ['start', 'poststep']
            assert len(callbacks) == 1
            assert 'completed' in ''.join(frame.get('text', '') for frame in frames)
            saved=requests.get(base+'/api/host-update-jobs/one-host-run/result',headers=headers,timeout=3)
            assert saved.status_code==200 and saved.headers['Cache-Control']=='no-store'
            assert saved.json()['exit_code']==0 and 'completed' in saved.json()['text']
            assert events.read_text().splitlines()==['start','poststep'] and len(callbacks)==1
            if viewer.connected:
                viewer.close()
            viewer = connect('missing-host-run', True)
            assert json.loads(viewer.receive(timeout=3))['type'] == 'job_unavailable'
            if viewer.connected:
                viewer.close()
            assert len(jobs.list_jobs()) == 1
            assert len(callbacks) == 1
    finally:
        server.stop(timeout=2)
    print('PASS real gevent HTTP/WS disconnect, 401, relogin, resume, PTY poststep and missing-ID no restart')


class HostWire(unittest.TestCase):
    def test_actual_gevent_transport_survives_viewer_loss(self):
        command = ('from gevent import monkey; monkey.patch_all(); '
                   'import runpy,sys; runpy.run_path(sys.argv[1],run_name="__wire__")')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', command, str(Path(__file__).resolve())],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS real gevent', result.stdout)


if __name__ == '__wire__':
    wire_fixture()
elif __name__ == '__main__':
    unittest.main(verbosity=2)
