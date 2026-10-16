# ==========================================================
# ProxMenux - Private OCI registry accounts
# ==========================================================
# Author      : Jonatan
# GitHub      : github.com/jcastro
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 16/10/2026
# ==========================================================
# Description:
# Manage persistent Skopeo credentials for private registries.
# Validate accounts without exposing tokens and preserve saved
# file credentials when authentication fails.
# ==========================================================

"""Persistent Skopeo authentication for private ProxMenux OCI images."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .i18n import translate

ANSI = re.compile(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')


class RegistryError(RuntimeError):
    pass


def clean(value, limit=180):
    text = ANSI.sub('', str(value or ''))
    return ''.join(c for c in text if ord(c) >= 32 and ord(c) != 127)[:limit]


def image_repository(reference):
    repository = reference.split('@', 1)[0]
    if ':' in repository.rsplit('/', 1)[-1]:
        repository = repository.rsplit(':', 1)[0]
    return repository


def require_root():
    if os.geteuid() != 0:
        raise RegistryError(translate('Manage registry accounts as root on the Proxmox node.'))


def validate_registry(value):
    """Accept a registry authority, never a URL, image path or credentials."""
    value = str(value).strip().lower()
    invalid = translate('Use a registry hostname, for example ghcr.io or registry.example.com:5000.')
    if not value or len(value) > 260 or any(c in value for c in '/@?#\\'):
        raise RegistryError(invalid)
    if value.startswith('['):
        match = re.fullmatch(r'\[([^]]+)\](?::([0-9]+))?', value)
        try:
            if not match or ipaddress.ip_address(match[1]).version != 6:
                raise ValueError()
        except ValueError:
            raise RegistryError(invalid) from None
        port = match[2]
    else:
        match = re.fullmatch(r'([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::([0-9]+))?', value)
        if not match or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
                            for part in match[1].split('.')):
            raise RegistryError(invalid)
        port = match[2]
    if port and not 1 <= int(port) <= 65535:
        raise RegistryError(invalid)
    return {'index.docker.io': 'docker.io', 'registry-1.docker.io': 'docker.io'}.get(value, value)


def credential_key(value):
    """Compare existing Docker aliases without exposing credential contents."""
    value = str(value).removeprefix('https://').removeprefix('http://').rstrip('/')
    return {'index.docker.io/v1': 'docker.io', 'index.docker.io': 'docker.io',
            'registry-1.docker.io': 'docker.io'}.get(value, value)


def registry_of(reference):
    first = image_repository(reference).split('/', 1)[0]
    if '/' in reference and ('.' in first or ':' in first or first == 'localhost'):
        return first
    return 'docker.io'


def validate_image(value):
    """Validate before the native importer, including registry ports and IPv6."""
    invalid = translate('Use an image reference, for example ghcr.io/owner/app:latest.')
    if not value or len(value) > 512 or any(c.isspace() or ord(c) < 32 for c in value):
        raise RegistryError(invalid)
    name, separator, digest = value.partition('@')
    if separator and not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise RegistryError(translate('Only a full sha256 image digest is supported.'))
    last = name.rsplit('/', 1)[-1]
    if ':' in last:
        name, tag = name.rsplit(':', 1)
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9._-]{0,127}', tag):
            raise RegistryError(translate('Invalid image tag.'))
    parts = name.split('/')
    if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0] or parts[0] == 'localhost'):
        try:
            validate_registry(parts.pop(0))
        except RegistryError:
            raise RegistryError(invalid) from None
    component = r'[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*'
    if not parts or len(name) > 255 or any(not re.fullmatch(component, part) for part in parts):
        raise RegistryError(invalid)
    return value


def registry_error(registry, error='', login=False):
    """Classify errors without echoing registry-controlled text or a token."""
    detail = str(error).casefold()
    if any(word in detail for word in ('credential helper', 'docker-credential-', 'error getting credentials', 'error storing credentials')):
        return translate('The configured credential helper could not be used. Check its installation and credential store.')
    if any(word in detail for word in ('too many requests', 'toomanyrequests', 'statuscode: 429', 'status code: 429', 'status: 429')):
        return translate('{registry} is rate limiting requests. Wait a while and try again.').format(registry=registry)
    if any(word in detail for word in ('statuscode: 500', 'status code: 500', 'status: 500',
                                      'statuscode: 502', 'status code: 502', 'status: 502',
                                      'statuscode: 503', 'status code: 503', 'status: 503',
                                      'statuscode: 504', 'status code: 504', 'status: 504',
                                      'internal server error', 'service unavailable', 'bad gateway')):
        return translate('{registry} reported a server error. Try again later.').format(registry=registry)
    if any(word in detail for word in ('unauthorized', 'authentication required', 'denied', 'forbidden', 'invalid username',
                                      'invalid password', 'invalid credentials', 'username/password',
                                      'statuscode: 401', 'statuscode: 403', 'status code from registry 401',
                                      'status code from registry 403')):
        return (translate('Authentication failed for {registry}. Check the account and token permissions.').format(registry=registry) if login else
                translate('Access denied by {registry}. Check the image name and sign in from Registry accounts.').format(registry=registry))
    if any(word in detail for word in ('http response to https client',
                                      'first record does not look like a tls handshake')):
        return translate('{registry} answered with plain HTTP. Use a registry with HTTPS; TLS verification remains enabled.').format(registry=registry)
    if any(word in detail for word in ('x509', 'certificate', 'tls handshake')):
        return translate('TLS verification failed for {registry}. Install the registry CA in /etc/containers/certs.d/{registry}/ca.crt.').format(registry=registry)
    if any(word in detail for word in ('no such host', 'connection refused', 'deadline exceeded', 'timeout', 'timed out',
                                      'network is unreachable', 'connection reset', 'unexpected eof')):
        return translate('Could not reach {registry}. Check its address, DNS and network access.').format(registry=registry)
    if any(word in detail for word in ('manifest unknown', 'name unknown', 'not found', 'statuscode: 404', 'status code: 404')):
        return (translate('No registry API was found at {registry}. Check the hostname and port.').format(registry=registry) if login else
                translate('The image or tag was not found on {registry}, or this account cannot access it. Check the reference.').format(registry=registry))
    if any(word in detail for word in ('invalid manifest', 'invalid character', 'unsupported manifest', 'unsupported schema')):
        return translate('{registry} returned invalid or unsupported image metadata.').format(registry=registry)
    return (translate('Could not sign in to {registry}. Check registry access and token permissions.').format(registry=registry) if login else
            translate('Could not read the image from {registry}. Check the reference and sign in from Registry accounts.').format(registry=registry))


class RegistryAuth:
    """Persistent Skopeo credentials for the native ProxMenux menu.

    Only the selected authfile is managed. Login is staged so failed attempts
    never replace saved file credentials. Skopeo still manages credential helpers.
    """
    def __init__(self, path=None):
        configured = os.environ.get('REGISTRY_AUTH_FILE')
        config_home = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        self.path = Path(path if path is not None else configured or config_home / 'containers/auth.json')
        if not self.path.is_absolute() or '..' in self.path.parts:
            raise RegistryError(translate('The registry authentication file must have an absolute path.'))

    def _validate_path(self):
        for path in [self.path, *self.path.parents]:
            if path.is_symlink():
                raise RegistryError(translate('The registry authentication path cannot contain symbolic links.'))
        for path in self.path.parents:
            if not path.exists():
                continue
            info = path.stat()
            shared_temporary = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                    or info.st_mode & 0o022 and not shared_temporary):
                raise RegistryError(translate('The registry authentication path has an unsafe parent directory.'))
        parent = self.path.parent
        if parent.exists():
            info = parent.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise RegistryError(translate('The registry credential directory must be owned by root with mode 700.'))

    def _read(self):
        self._validate_path()
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {}, None
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise RegistryError(translate('The registry authentication file must be owned by root with mode 600.'))
            raw = source.read(1024 * 1024 + 1)
        try:
            data = json.loads(raw) if len(raw) <= 1024 * 1024 else None
        except ValueError:
            data = None
        if not isinstance(data, dict) or any(not isinstance(data.get(key, {}), dict) for key in ('auths', 'credHelpers')):
            raise RegistryError(translate('The registry authentication file is invalid; it was not changed.'))
        return data, raw

    def accounts(self):
        data, _ = self._read()
        rows = {}
        for key, credential in data.get('auths', {}).items():
            if not isinstance(credential, dict):
                continue
            username = None
            encoded = credential.get('auth')
            if isinstance(encoded, str) and len(encoded) < 65536:
                try:
                    decoded = base64.b64decode(encoded, validate=True).decode('utf-8')
                    if ':' in decoded:
                        username = clean(decoded.split(':', 1)[0], 120)
                except (ValueError, UnicodeError):
                    pass
            if encoded or credential.get('identitytoken') or credential.get('registrytoken'):
                rows[credential_key(key)] = {'registry': clean(credential_key(key), 320), 'account': username,
                                           'method': translate('Token') if not encoded else translate('Username / token'), 'status': 'Saved'}
        for key, helper in data.get('credHelpers', {}).items():
            rows[credential_key(key)] = {'registry': clean(credential_key(key), 320), 'account': None,
                                      'method': translate('Helper:') + ' ' + clean(helper, 80), 'status': 'Configured'}
        return sorted(rows.values(), key=lambda row: row['registry'])

    @contextmanager
    def _staged(self):
        self._validate_path()
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._validate_path()
        lock = self.path.with_name('.' + self.path.name + '.proxmenux.lock')
        fd = os.open(lock, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise RegistryError(translate('Unsafe registry credential lock.'))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RegistryError(translate('Another registry account operation is running. Try again when it finishes.')) from None
            data, before = self._read()
            stage_fd, name = tempfile.mkstemp(prefix='.proxmenux-auth-', dir=self.path.parent)
            stage = Path(name)
            try:
                with os.fdopen(stage_fd, 'wb') as out:
                    out.write(before if before is not None else b'{"auths":{}}\n')
                yield stage, data
                self._read_stage(stage)
                if self._read()[1] != before:
                    raise RegistryError(translate('The credential file changed during this operation. Try again; it was not overwritten.'))
                stage.chmod(0o600)
                with stage.open('rb') as saved:
                    os.fsync(saved.fileno())
                os.replace(stage, self.path)
            finally:
                stage.unlink(missing_ok=True)
        finally:
            os.close(fd)

    @staticmethod
    def _read_stage(stage):
        try:
            data = json.loads(stage.read_text())
            if not isinstance(data, dict) or any(not isinstance(data.get(k, {}), dict) for k in ('auths', 'credHelpers')):
                raise ValueError()
            return data
        except (OSError, ValueError):
            raise RegistryError(translate('Skopeo returned an invalid credential file; saved credentials were not changed.')) from None

    def login(self, registry, username, password, timeout=45):
        registry = validate_registry(registry)
        if not username or not username.strip() or len(username) > 512 or any(ord(c) < 32 or ord(c) == 127 or c == ':' for c in username):
            raise RegistryError(translate('Enter a valid registry username.'))
        if not password or len(password) > 65536 or any(c in password for c in '\r\n\0'):
            raise RegistryError(translate('Enter a non-empty password or access token on a single line.'))
        with self._staged() as (stage, _):
            try:
                process = subprocess.run(['skopeo', 'login', '--authfile', str(stage), '--username', username,
                                          '--password-stdin', registry], input=password + '\n', text=True,
                                         capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise RegistryError(translate('Login to {registry} timed out. Saved credentials were not changed.').format(registry=registry)) from None
            except FileNotFoundError:
                raise RegistryError(translate('Skopeo is not available. Restore the ProxMenux OCI dependencies and try again.')) from None
            if process.returncode:
                raise RegistryError(registry_error(registry, process.stderr, login=True))

    def logout(self, registry):
        registry = validate_registry(registry)
        data, _ = self._read()
        matches = lambda key: credential_key(key).split('/', 1)[0] == registry
        if not any(matches(key) for group in ('auths', 'credHelpers') for key in data.get(group, {})):
            return False
        with self._staged() as (stage, data):
            # Skopeo logs out the authority itself; entries scoped to a
            # repository are also removed from this managed authfile below.
            if any(credential_key(key) == registry for group in ('auths', 'credHelpers') for key in data.get(group, {})):
                try:
                    process = subprocess.run(['skopeo', 'logout', '--authfile', str(stage), registry],
                                             capture_output=True, text=True, timeout=30)
                except subprocess.TimeoutExpired:
                    raise RegistryError(translate('Logout from {registry} timed out. Saved file credentials were not changed.').format(registry=registry)) from None
                except FileNotFoundError:
                    raise RegistryError(translate('Skopeo is not available. Restore the ProxMenux OCI dependencies and try again.')) from None
                if process.returncode:
                    raise RegistryError(translate('Could not remove credentials for {registry}; saved file credentials were not changed.').format(registry=registry))
            data = self._read_stage(stage)
            for group in ('auths', 'credHelpers'):
                data[group] = {key: value for key, value in data.get(group, {}).items() if not matches(key)}
            stage.write_text(json.dumps(data))
        return True


@contextmanager
def registry_environment():
    """Use durable credentials for every descendant, including update probes."""
    previous = os.environ.get('REGISTRY_AUTH_FILE')
    auth = RegistryAuth()
    if auth.path.exists():
        auth._read()
        os.environ['REGISTRY_AUTH_FILE'] = str(auth.path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('REGISTRY_AUTH_FILE', None)
        else:
            os.environ['REGISTRY_AUTH_FILE'] = previous
