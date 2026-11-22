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
# Manage private registry accounts from the native OCI menu.
# Check image access, download verified archives and hand image
# installation to the existing ProxMenux LXC wizard.
# ==========================================================

"""Private image registry accounts in the native ProxMenux OCI menu."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import errno
import importlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys

from .i18n import translate
from .registry_auth import (RegistryAuth, RegistryError, clean, require_root,
                            validate_registry, validate_image, registry_of,
                            registry_error, registry_environment)

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_QUERY_TIMEOUT = 30


@contextmanager
def image_queries(reference):
    """Keep the native resolver while retaining safe, useful transport errors."""
    images = importlib.import_module('oci_installation_state')
    original = images.command
    registry = registry_of(reference)

    def query(*args):
        if args[:2] != ('skopeo', 'inspect'):
            return original(*args)
        try:
            result = subprocess.run(args, capture_output=True, timeout=REGISTRY_QUERY_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise RegistryError(translate('{registry} did not respond within {timeout} seconds. Try again later.').format(registry=registry, timeout=REGISTRY_QUERY_TIMEOUT)) from None
        except FileNotFoundError:
            raise RegistryError(translate('Skopeo is not available. Restore the ProxMenux OCI dependencies and try again.')) from None
        if result.returncode:
            raise RegistryError(registry_error(registry, result.stderr.decode(errors='replace')))
        return result.stdout

    images.command = query
    try:
        yield images
    finally:
        images.command = original


def bytes_label(size):
    value = float(size)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def host_architecture():
    architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(os.uname().machine)
    if not architecture:
        raise RegistryError(translate('This host architecture is not supported by the OCI image importer.'))
    return architecture


def image_template(reference):
    reference = validate_image(reference)
    custom = importlib.import_module('proxmenux_oci.custom')
    try:
        compose = custom.compose_from_image(reference)
    except (custom.ConversionError, subprocess.TimeoutExpired, ValueError) as error:
        raise RegistryError(registry_error(registry_of(reference), error)) from None
    try:
        template = custom.template_from_compose(compose)
        custom._ask_secrets(template)
    except custom.ConversionError:
        raise RegistryError(translate('ProxMenux could not translate this image. Try importing its Compose file from OCI manager Apps.')) from None
    return template


def inspect_registry_image(reference):
    reference = validate_image(reference)
    try:
        with registry_environment(), image_queries(reference) as images:
            candidate = images.resolve_candidate(reference, host_architecture())
    except RegistryError:
        raise
    except ValueError as error:
        detail = str(error).casefold()
        if 'platform' in detail or 'architecture' in detail:
            raise RegistryError(translate('This image has no compatible Linux image for this host ({architecture}).').format(architecture=host_architecture())) from None
        if 'manifest does not match' in detail or 'integrity' in detail:
            raise RegistryError(translate('The image manifest failed integrity verification. Try again or contact the image publisher.')) from None
        raise RegistryError(translate('The registry returned invalid or unsupported image metadata.')) from None
    except (KeyError, AttributeError, TypeError):
        raise RegistryError(translate('The registry returned incomplete or unsupported image metadata.')) from None
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise RegistryError(registry_error(registry_of(reference), error)) from None
    return {'reference': reference, 'architecture': host_architecture(), 'version': clean(candidate.get('version')) or None,
            'digest': candidate['manifest_digest'], 'size': candidate.get('size') or 0}


def download_registry_image(reference, storage):
    """Download and verify with the exact native updater cache implementation."""
    reference = validate_image(reference)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', storage):
        raise RegistryError(translate('Invalid template storage name.'))
    inspect_registry_image(reference)
    native = importlib.import_module('oci_update_current')
    desired = {'template': {'container_contract': {'image': {'reference': reference}}},
               'deployment': {'template_storage': storage}}
    try:
        with native.instances.locked(native.instances.ROOT), registry_environment(), redirect_stdout(io.StringIO()):
            path, digest = native.resolve_archive(desired, f'arch: {host_architecture()}\n'.encode())
    except BlockingIOError:
        raise RegistryError(translate('Another ProxMenux OCI operation is running. Try again when it finishes.')) from None
    except RegistryError:
        raise
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        detail = str(error).casefold()
        if getattr(error, 'errno', None) == errno.ENOSPC or 'does not fit' in detail or 'no space left' in detail:
            raise RegistryError(translate('Not enough free space on {storage}. Free some space or select another storage.').format(storage=storage)) from None
        if isinstance(error, PermissionError) or getattr(error, 'errno', None) == errno.EROFS:
            raise RegistryError(translate('Cannot write the image archive to {storage}. Check storage access and mount status.').format(storage=storage)) from None
        if 'unsafe' in detail or 'symbolic link' in detail:
            raise RegistryError(translate('The image cache path is unsafe. Check the template storage before trying again.')) from None
        if 'integrity' in detail or 'intact image' in detail:
            raise RegistryError(translate('Image integrity verification failed. The partial download was discarded; try again.')) from None
        raise RegistryError(translate('The image could not be downloaded or verified. Check registry and storage access, then try again.')) from None
    return {'reference': reference, 'archive': str(path), 'digest': digest, 'storage': storage,
            'size': Path(path).stat().st_size, 'architecture': host_architecture()}


def registry_accounts_menu(ui, engine=ENGINE_ROOT, auth=None):
    """Manage private registry accounts and images in ProxMenux."""
    require_root()
    engine = Path(engine)
    if str(engine / 'remote') not in sys.path:
        sys.path.insert(0, str(engine / 'remote'))
    auth = auth or RegistryAuth()
    cancelled = importlib.import_module('proxmenux_oci.ui').UserCancelled
    title = translate('Registry accounts')
    while True:
        # A broken authfile must let the user return to ProxMenux instead of
        # showing the same error indefinitely before a menu can be displayed.
        try:
            rows = auth.accounts()
        except (RegistryError, OSError, ValueError) as error:
            ui.message(clean(error, 600), title)
            return
        try:
            options = [('add', translate('Sign in to a registry'))]
            options += [(f'account-{index}', f"{row['registry']:<28}  [{translate('saved')}]")
                        for index, row in enumerate(rows)]
            options += [('storage', translate('Credential storage and access'))]
            count = translate('{count} saved account.') if len(rows) == 1 else translate('{count} saved accounts.')
            choice = ui.choose(translate('Manage private image registries.\n'
                                        'Saved credentials let ProxMenux access your private images.')
                               + '\n\n' + count.format(count=len(rows)),
                               options, 'account-0' if rows else 'add', title=title, show_tags=False)
            if choice is None:
                return
            row = None
            if choice.startswith('account-'):
                try:
                    row = rows[int(choice.partition('-')[2])]
                except (ValueError, IndexError):
                    continue
                choice = ui.choose(translate('Registry: {registry}\nAccount: {account}\n'
                                             'Authentication: {method}\n\n'
                                             'Saved credentials are verified when an image is accessed.').format(
                                        registry=row['registry'], account=row['account'] or translate('Credential helper'),
                                        method=row['method']),
                                   [('inspect', translate('Check access to an image')),
                                    ('download', translate('Download an image to template storage')),
                                    ('install', translate('Install an image as a native LXC')),
                                    ('login', translate('Update credentials')),
                                    ('logout', translate('Remove saved credentials'))], 'inspect', title=title, show_tags=False)
                if choice is None:
                    continue
            if choice == 'storage':
                ui.message(translate('Credentials file:\n{path}\n\n'
                           'Owned by root; directory mode 700 and file mode 600.\n'
                           'Basic credentials are base64 encoded, not encrypted.\n'
                           'Credential helpers use their own storage.\n\n'
                           'Use an access token with permission to pull images.\n'
                           'Every node of the cluster uses the accounts saved here.').format(path=auth.path), title)
            elif choice in {'add', 'login'}:
                registry = row['registry'].split('/', 1)[0] if row else ui.ask(translate('Registry hostname'), 'ghcr.io')
                try:
                    registry = validate_registry(registry)
                except RegistryError as error:
                    raise RegistryError(str(error)) from None
                username = ui.ask(translate('Username'), row['account'] if row else None)
                password = ui.password(translate('Password / access token (image pull permission)'))
                ui.info(translate('Verifying registry access. Please wait...'))
                auth.login(registry, username, password)
                del password
                ui.message(translate('Signed in to {registry} as {username}.\n\n'
                           'Credentials are saved for ProxMenux.\n'
                           'Select the account to check, download or install an image.').format(
                               registry=registry, username=clean(username)), title)
            elif choice == 'logout' and row:
                registry = row['registry'].split('/', 1)[0]
                if ui.confirm(translate('Remove the saved credentials for {registry}?\nRunning apps will keep working.').format(registry=registry),
                              False, title=title):
                    auth.logout(registry)
                    ui.message(translate('Saved credentials for {registry} were removed.\n'
                                         'Other Skopeo/Docker credential files are managed separately.').format(registry=registry), title)
            elif choice in {'inspect', 'download', 'install'} and row:
                registry = row['registry'].split('/', 1)[0]
                owner = row['account'] or 'owner'
                reference = validate_image(ui.ask(translate('Image reference'), f'{registry}/{owner}/app:latest'))
                if registry_of(reference) != registry:
                    raise RegistryError(translate('This account is for {registry}. Enter an image from that registry.').format(registry=registry))
                if choice == 'inspect':
                    ui.info(translate('Checking image access and metadata. Please wait...'))
                    result = inspect_registry_image(reference)
                    ui.message(translate('Image access confirmed.\n\n{reference}\n\n'
                                         'Architecture: {architecture}\nVersion: {version}\n'
                                         'Download size: {size}\nDigest: {digest}').format(
                                    reference=reference, architecture=result['architecture'],
                                    version=result['version'] or translate('Not declared'),
                                    size=bytes_label(result['size']), digest=result['digest']), title)
                elif choice == 'download':
                    host = importlib.import_module('proxmenux_oci.host')
                    storages = host.storages('vztmpl')
                    if not storages:
                        raise RegistryError(translate('No active Proxmox storage accepts OCI template archives.'))
                    names = [item['storage'] for item in storages]
                    storage = ui.choose(translate('Choose storage for the downloaded image.'),
                                        [(item['storage'], f"{item['storage']}  ({bytes_label(item.get('avail', 0))} {translate('available')})")
                                         for item in storages], 'local' if 'local' in names else names[0], title=title)
                    if storage is None:
                        continue
                    ui.info(translate('Downloading and verifying the image.\nThis can take a few minutes. Please wait...'))
                    result = download_registry_image(reference, storage)
                    ui.message(translate('Image downloaded and verified.\n\n{reference}\n\n'
                                         'Storage: {storage}\nArchive size: {size}\n'
                                         'Archive: {archive}\n\nNo container was created.\n'
                                         'ProxMenux removes unused cached images after successful updates.').format(
                                    reference=reference, storage=storage, size=bytes_label(result['size']),
                                    archive=result['archive']), title)
                else:
                    ui.info(translate('Reading image metadata. Please wait...'))
                    with registry_environment():
                        template = image_template(reference)
                        if not template.get('compatibility', {}).get('automatic_install_candidate'):
                            raise RegistryError(translate('ProxMenux cannot install this image automatically. Import its Compose file instead.'))
                        installer = importlib.import_module('proxmenux_oci.installer')
                        native_cli = importlib.import_module('proxmenux_oci.cli')
                        mode = ui.choose(translate('Installation settings'), [(installer.DEFAULT_MODE, translate('Default settings')),
                                         (installer.ADVANCED_MODE, translate('Advanced settings'))], installer.DEFAULT_MODE, title=title)
                        if mode is not None:
                            native_cli.install_template(ui, template, template['id'], mode)
        except cancelled:
            continue
        except (RegistryError, OSError, ValueError) as error:
            ui.message(clean(error, 600), title)


def open_registry_accounts(ui):
    try:
        registry_accounts_menu(ui)
    except (RegistryError, OSError, ValueError) as error:
        ui.message(clean(error, 600), translate('Registry accounts'))


def offer_sign_in(ui, reference, title=None):
    """When a registry refuses an image, an account for it can be added on the
    spot; the image is then read again with it."""
    try:
        registry = validate_registry(registry_of(reference))
    except RegistryError:
        return False
    question = translate('{registry} refused access to this image:\n{reference}\n\n'
                         'If the image is private, sign in with an account that can pull it.\n\n'
                         'Sign in now?').format(registry=registry, reference=clean(reference, 300))
    if not ui.confirm(question, True, title=title):
        return False
    cancelled = importlib.import_module('proxmenux_oci.ui').UserCancelled
    try:
        require_root()
        username = ui.ask(translate('Username'))
        password = ui.password(translate('Password / access token (image pull permission)'))
        ui.info(translate('Verifying registry access. Please wait...'))
        RegistryAuth().login(registry, username, password)
        del password
    except cancelled:
        return False
    except (RegistryError, OSError, ValueError) as error:
        ui.message(clean(error, 600), title)
        return False
    return True
