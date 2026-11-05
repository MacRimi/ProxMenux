"""Real JWT verification, synthetic keys only; never imports live auth config."""
import ast
import contextlib
from datetime import datetime, timedelta
import hashlib
import io
from pathlib import Path
import threading
import time
import unittest

import jwt

ROOT = Path(__file__).resolve().parents[1]


class AuthReasons(unittest.TestCase):
    def setUp(self):
        source = ast.parse((ROOT / 'AppImage/scripts/auth_manager.py').read_text())
        names = {'verify_token_full', '_log_auth_failure_throttled', 'generate_token'}
        nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names]
        constants = {n.targets[0].id: ast.literal_eval(n.value) for n in source.body
                     if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                     and n.targets[0].id in {'TOKEN_EXPIRATION_HOURS', 'JWT_ALGORITHM', 'JWT_ISSUER', 'JWT_AUDIENCE'}}
        self.revoked = set()
        self.scope = dict(jwt=jwt, JWT_AVAILABLE=True, hashlib=hashlib, time=time,
                          _get_jwt_secret=lambda: 'fixture-only-secret-for-offline-auth-tests',
                          _get_revoked_tokens_cached=lambda: self.revoked,
                          _AUTH_LOG_LOCK=threading.Lock(),
                          _AUTH_LOG_RATE=dict(last_ts=0., suppressed=0, last_msg=''),
                          datetime=datetime, timedelta=timedelta, **constants)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'actual-auth', 'exec'), self.scope)

    def token(self, **values):
        claims = dict(username='fixture-admin', exp=time.time()+120,
                      iss=self.scope['JWT_ISSUER'], aud=self.scope['JWT_AUDIENCE'])
        claims.update(values)
        return jwt.encode(claims, self.scope['_get_jwt_secret'](), algorithm='HS256')

    def rejection(self, token, reason):
        self.scope['_AUTH_LOG_RATE'].update(last_ts=0., suppressed=0, last_msg='')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = self.scope['verify_token_full'](token)
        self.assertEqual(result, (None, None))
        log = out.getvalue()
        self.assertIn(reason, log)
        for secret in (self.scope['_get_jwt_secret'](), token or 'not-present', 'fixture-admin'):
            self.assertNotIn(secret, log)

    def test_expired_invalid_revoked_and_missing_are_safe_categories(self):
        self.rejection(self.token(exp=time.time()-10), 'expired')
        self.rejection('fixture.invalid.token', 'invalid')
        token = self.token()
        self.revoked.add(hashlib.sha256(token.encode()).hexdigest())
        self.rejection(token, 'revoked')
        self.rejection(None, 'missing token')

    def test_valid_and_legacy_scopes_keep_existing_contract(self):
        verify = self.scope['verify_token_full']
        self.assertEqual(verify(self.token()), ('fixture-admin', 'full_admin'))
        self.assertEqual(verify(self.token(scope='read_only')), ('fixture-admin', 'read_only'))
        legacy = jwt.encode(dict(username='fixture-admin', exp=time.time()+120),
                            self.scope['_get_jwt_secret'](), algorithm='HS256')
        self.assertEqual(verify(legacy), ('fixture-admin', 'full_admin'))

    def test_normal_session_lifetime_remains_24_hours(self):
        self.assertEqual(self.scope['TOKEN_EXPIRATION_HOURS'], 24)
        token = self.scope['generate_token']('fixture-admin')
        payload = jwt.decode(token, self.scope['_get_jwt_secret'](), algorithms=['HS256'],
                             audience=self.scope['JWT_AUDIENCE'], issuer=self.scope['JWT_ISSUER'])
        self.assertAlmostEqual(payload['exp']-payload['iat'], 86400, delta=1)

    def test_repeated_auth_failures_are_rate_limited_without_secrets(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for _ in range(100):
                self.scope['verify_token_full']('fixture.invalid.token')
        self.assertEqual(out.getvalue().count('[auth]'), 1)
        self.assertNotIn('fixture.invalid.token', out.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
