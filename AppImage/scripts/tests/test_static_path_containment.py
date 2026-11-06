"""The routes that serve the Monitor's own files never return a file from
outside their folder, whatever the request path says."""
import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify, send_file, send_from_directory

SCRIPTS = Path(__file__).resolve().parents[1]
HANDLERS = {'serve_next_static', 'serve_static_files', 'serve_images'}
ESCAPES = (
    '../../secret.txt', '..%2f..%2fsecret.txt', '..%2F..%2Fsecret.txt',
    '%2e%2e/%2e%2e/secret.txt', '....//....//secret.txt', '/../../secret.txt',
    '..\\..\\secret.txt', '%2e%2e%2f%2e%2e%2fsecret.txt',
)


def app_with_handlers():
    """The real route functions of flask_server.py on a bare Flask app."""
    tree = ast.parse((SCRIPTS / 'flask_server.py').read_text())
    app = Flask(__name__)
    namespace = {'os': os, 'app': app, 'send_file': send_file,
                 'send_from_directory': send_from_directory, 'jsonify': jsonify}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in HANDLERS]
    if {n.name for n in nodes} != HANDLERS:
        raise AssertionError('static handlers not found')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'flask_server.py', 'exec'), namespace)
    for node in nodes:
        for decorator in node.decorator_list:
            rule = decorator.args[0].value
            app.add_url_rule(rule, node.name, namespace[node.name])
    return app


class StaticPathContainment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.appdir = root / 'appdir'
        (self.appdir / 'web/_next/static').mkdir(parents=True)
        (self.appdir / 'web/images').mkdir(parents=True)
        (self.appdir / 'web/_next/static/app.js').write_text('next-asset')
        (self.appdir / 'web/images/logo.png').write_text('image-asset')
        (self.appdir / 'web/index.txt').write_text('web-asset')
        # Harmless markers just outside each served folder and at the root.
        for marker in (root / 'secret.txt', self.appdir / 'secret.txt', self.appdir / 'web/secret.txt'):
            marker.write_text('outside-marker')
        patcher = patch.dict(os.environ, {'APPDIR': str(self.appdir)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app_with_handlers().test_client()

    def test_files_inside_the_folders_are_served(self):
        for path, body in (('/_next/static/app.js', b'next-asset'), ('/images/logo.png', b'image-asset'),
                           ('/index.txt', b'web-asset')):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual((response.status_code, response.get_data()), (200, body))
                response.close()

    def test_no_path_leaves_the_folder(self):
        for prefix in ('/_next/', '/images/', '/'):
            for escape in ESCAPES:
                if prefix == '/' and escape.startswith('/'):
                    continue  # '//' would be read as a host by the test client
                with self.subTest(path=prefix + escape):
                    response = self.client.get(prefix + escape)
                    self.assertNotIn(b'outside-marker', response.get_data())
                    self.assertNotEqual(response.status_code, 200)
                    response.close()

    def test_an_absolute_path_is_not_served(self):
        response = self.client.get('/_next/' + str(self.appdir / 'secret.txt'))
        self.assertNotIn(b'outside-marker', response.get_data())
        response.close()


if __name__ == '__main__':
    unittest.main()
