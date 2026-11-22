"""Resolve explicitly supplied Compose inputs without inheriting the host environment.

No command substitutions, shell evaluation or image-specific rewrites are performed.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import yaml

from .converter import ConversionError, _split_short_mount
from .i18n import translate

NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
SECRET = re.compile(r'pass|secret|token|key|credential|url', re.I)
LIMIT = 256 * 1024


class Interpolator:
    def __init__(self, values=None, missing=None):
        self.values = dict(values or {})
        self.missing = missing

    def expand(self, value, depth=0):
        if depth > 20:
            raise ConversionError(translate('Unresolved variable:') + ' nesting')
        result, i = [], 0
        while i < len(value):
            if value[i] != '$':
                result.append(value[i]); i += 1; continue
            if value[i:i+2] == '$$':
                result.append('$'); i += 2; continue
            if value[i:i+2] == '${':
                end, nested = i+2, 1
                while end < len(value) and nested:
                    if value[end:end+2] == '${':
                        nested += 1; end += 2; continue
                    if value[end] == '}':
                        nested -= 1
                    end += 1
                if nested:
                    raise ConversionError(translate('Unresolved variable:') + ' ${...}')
                expression = value[i+2:end-1]
                match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-+?])(.*))?', expression, re.S)
                if not match:
                    raise ConversionError(translate('Unresolved variable:') + ' ${...}')
                name, op, argument = match.groups()
                i = end
            else:
                match = NAME.match(value, i+1)
                if not match:
                    result.append('$'); i += 1; continue
                name, op, argument = match[0], None, None
                i = match.end()
            present = name in self.values
            nonempty = present and self.values[name] != ''
            use = nonempty if op and op.startswith(':') else present
            if op and op.endswith('-'):
                replacement = self.values[name] if use else self.expand(argument, depth+1)
            elif op and op.endswith('+'):
                replacement = self.expand(argument, depth+1) if use else ''
            elif op and op.endswith('?'):
                if not use:
                    raise ConversionError(translate('Unresolved variable:') + ' ' + name)
                replacement = self.values[name]
            elif present:
                replacement = self.values[name]
            elif self.missing is not None:
                replacement = self.missing(name)
                self.values[name] = replacement
            else:
                raise ConversionError(translate('Unresolved variable:') + ' ' + name)
            result.append(str(replacement))
        return ''.join(result)

    def walk(self, value):
        if isinstance(value, str):
            return self.expand(value)
        if isinstance(value, dict):
            return {key: self.walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.walk(item) for item in value]
        return value


def dotenv(text, interpolator):
    """The common KEY=value dotenv grammar; quoted values are never executed."""
    result = {}
    local = Interpolator(interpolator.values, interpolator.missing)
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith('#'):
            continue
        if raw.startswith('export '):
            raw = raw[7:].lstrip()
        key, separator, value = raw.partition('=')
        key = key.strip()
        if not NAME.fullmatch(key):
            raise ConversionError(translate('Invalid environment variable name:') + ' ' + key)
        if not separator:
            result[key] = None
            continue
        value = value.strip()
        if value.startswith("'"):
            end, quoted = 1, []
            while end < len(value):
                if value[end:end+2] == "\\'":
                    quoted.append("'"); end += 2; continue
                if value[end] == "'":
                    break
                quoted.append(value[end]); end += 1
            if end >= len(value) or (value[end+1:].strip() and not value[end+1:].lstrip().startswith('#')):
                raise ConversionError(translate('Invalid environment variable name:') + ' ' + key)
            value = ''.join(quoted)
        else:
            if value.startswith('"'):
                quoted = value
                try:
                    value, end = json.JSONDecoder().raw_decode(value)
                    if not isinstance(value, str):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ConversionError(translate('Invalid environment variable name:') + ' ' + key) from None
                suffix = quoted[end:].strip()
                if suffix and not suffix.startswith('#'):
                    raise ConversionError(translate('Invalid environment variable name:') + ' ' + key)
            else:
                value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
            value = local.expand(value)
        result[key] = value
        local.values[key] = value
    return result


def resolve_document(document, project=None, env_files=None, missing=None):
    """Pure preparation of a full document; preserve every service and image."""
    resolver = Interpolator(project, missing)
    result = resolver.walk(document)
    for service in result.get('services', {}).values():
        if not isinstance(service, dict):
            raise ConversionError(translate('The Compose file does not contain a Compose document'))
        merged = {}
        files = service.pop('env_file', [])
        if isinstance(files, str):
            files = [files]
        if not isinstance(files, list):
            raise ConversionError(translate('Unresolved variable:') + ' env_file')
        for item in files:
            if isinstance(item, dict):
                if set(item) - {'path', 'required'}:
                    raise ConversionError(translate('Unresolved variable:') + ' env_file')
                filename, required = item.get('path'), item.get('required', True)
            else:
                filename, required = item, True
            if not isinstance(filename, str) or not filename:
                raise ConversionError(translate('Unresolved variable:') + ' env_file')
            if filename not in (env_files or {}):
                if not required:
                    continue
                raise ConversionError(translate('Unresolved variable:') + ' ' + filename)
            merged.update(dotenv(env_files[filename], resolver))
        environment = service.get('environment', {})
        if isinstance(environment, list):
            if any(not isinstance(item, str) for item in environment):
                raise ConversionError('environment must be a list or a mapping')
            pairs = [item.partition('=') for item in environment]
            environment = {key: value if separator else resolver.values.get(key)
                           for key, separator, value in pairs}
        if not isinstance(environment, dict):
            raise ConversionError('environment must be a list or a mapping')
        for key, value in environment.items():
            merged[key] = resolver.values.get(str(key)) if value is None else value
        service['environment'] = {key: value for key, value in merged.items() if value is not None}
    return result


def prepare(ui, document, directory=None, *, metadata=None):
    """Read companion files explicitly, then ask once for each missing value."""
    directory = Path(directory) if directory is not None else None
    cache = {}
    entered = {}

    def read(path):
        try:
            data = Path(path).expanduser().read_bytes()
        except OSError as error:
            raise ConversionError(translate('The file could not be read:') + ' ' + str(path)) from error
        if len(data) > LIMIT:
            raise ConversionError(translate('The Compose file is too large'))
        try:
            return data.decode('utf-8-sig')
        except UnicodeError:
            raise ConversionError(translate('The Compose file is not valid YAML:') + ' UTF-8') from None

    def missing(name):
        if name not in entered:
            prompt = translate('Value for') + ' ' + name
            entered[name] = (ui.password(prompt, required=True) if SECRET.search(name)
                             else ui.ask(prompt, '', required=True))
        return entered[name]

    resolver = Interpolator(missing=missing)
    default = directory / '.env' if directory else None
    if default is not None and default.is_file():
        cache['.env'] = read(default)
        resolver.values.update({k: v for k, v in dotenv(cache['.env'], resolver).items() if v is not None})
    elif re.search(r'\$(?:\{|[A-Za-z_])', yaml.safe_dump(document)):
        path = ui.ask(translate('Project environment file (.env), or leave empty to enter values'), '', required=False)
        if path:
            cache['.env'] = read(path)
            resolver.values.update({k: v for k, v in dotenv(cache['.env'], resolver).items() if v is not None})
    for service in document.get('services', {}).values():
        files = service.get('env_file', []) if isinstance(service, dict) else []
        if isinstance(files, str):
            files = [files]
        if not isinstance(files, list):
            raise ConversionError(translate('Unresolved variable:') + ' env_file')
        for item in files:
            raw = item.get('path', '') if isinstance(item, dict) else item
            if not isinstance(raw, str) or not raw:
                raise ConversionError(translate('Unresolved variable:') + ' env_file')
            filename = resolver.expand(raw)
            if filename in cache:
                continue
            candidate = directory / filename if directory and not Path(filename).is_absolute() else None
            if candidate is not None and candidate.resolve().is_relative_to(directory.resolve()) and candidate.is_file():
                cache[filename] = read(candidate)
                continue
            required = item.get('required', True) if isinstance(item, dict) else True
            if type(required) is not bool:
                raise ConversionError(translate('Unresolved variable:') + ' env_file.required')
            if not required:
                continue
            path = ui.ask(translate('Path of environment file') + ': ' + filename,
                          str(candidate or filename), required=required)
            if path:
                cache[filename] = read(path)
    result = resolve_document(document, resolver.values, cache, missing)
    for service in result.get('services', {}).values():
        mounts = []
        for mount in service.get('volumes') or []:
            if isinstance(mount, str):
                source, target, mode = _split_short_mount(mount)
                flags = (mode or '').split(',')
                if any(flag in {'z', 'Z'} for flag in flags):
                    if any(flag not in {'', 'ro', 'rw', 'z', 'Z'} for flag in flags) or {'ro','rw'} <= set(flags) or {'z','Z'} <= set(flags):
                        raise ConversionError(translate('Unsupported volume options:') + ' ' + str(mode))
                    mount = {'target':target, 'read_only':'ro' in flags}
                    if source is not None:
                        mount['source'] = source
                    if metadata is not None:
                        metadata['selinux_labels'] = True
            mounts.append(mount)
        if 'volumes' in service:
            service['volumes'] = mounts
    return result
