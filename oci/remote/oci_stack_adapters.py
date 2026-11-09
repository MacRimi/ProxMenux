"""The dedicated adapters of multi-container applications, declared once.

An adapter installs a stack with its own script and translates its members for
a coordinated update. The rest of the engine asks this table instead of keeping
its own list, so a new adapter is one entry here. Everything an adapter does
not declare (resources, variables, network, the changes the user makes in
Proxmox) is handled the same way as for any other container."""
from __future__ import annotations

import oci_stack_replay as replay

ADAPTERS = {
    'install_nextcloud_stack.sh': {
        'name': 'nextcloud', 'label': 'Nextcloud', 'record': replay.nextcloud_record,
        # The member the stack is opened from, the others in their start order,
        # and how the application tells it is ready after an update.
        'main_role': 'application', 'dependencies': ('database', 'cache'),
        'healthcheck': ['php', '-r',
                        '$s=json_decode(file_get_contents("http://127.0.0.1/status.php"),true);'
                        'exit(is_array($s)&&!empty($s["installed"])&&empty($s["maintenance"])'
                        '&&empty($s["needsDbUpgrade"])?0:1);'],
        'menu_ready': replay.nextcloud_menu_ready, 'prerequisites': replay.nextcloud_prerequisites,
        # The paths its application container keeps its own data in.
        'application_paths': ('/var/www/html',),
    },
    'install_paperless_stack.sh': {
        'name': 'paperless', 'label': 'Paperless', 'record': replay.paperless_record,
        'main_role': 'application', 'dependencies': ('database', 'broker'),
        'healthcheck': ['python3', '-c',
                        'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10).read(1)'],
        'menu_ready': replay.paperless_menu_ready, 'prerequisites': replay.paperless_prerequisites,
        'application_paths': ('/usr/src/paperless/data', '/usr/src/paperless/media',
                              '/usr/src/paperless/consume', '/usr/src/paperless/export'),
    },
    'install_tandoor_stack.sh': {
        'name': 'tandoor', 'label': 'Tandoor', 'record': replay.tandoor_record,
        'main_role': 'application', 'dependencies': ('database',),
        'healthcheck': ['python3', '-c',
                        'import urllib.request; urllib.request.urlopen("http://127.0.0.1/", timeout=10).read(1)'],
        'menu_ready': replay.tandoor_menu_ready, 'prerequisites': replay.tandoor_prerequisites,
        'application_paths': ('/opt/recipes/mediafiles', '/opt/recipes/staticfiles'),
    },
    'install_immich_stack.sh': {
        'name': 'immich', 'label': 'Immich', 'record': replay.immich_record,
        'main_role': 'server', 'dependencies': ('database', 'valkey', 'machine-learning'),
        'healthcheck': ['node', '-e',
                        'fetch("http://127.0.0.1:2283/api/server/ping").then(r=>{if(!r.ok)process.exit(1)})'
                        '.catch(()=>process.exit(1))'],
        'menu_ready': replay.immich_menu_ready, 'prerequisites': replay.immich_prerequisites,
        'application_paths': ('/data',),
        # Values kept in step with a resource of the same container, by role:
        # the server sizes its workers with CPU_CORES.
        'derived': {'server': {'CPU_CORES': 'cores'}},
    },
}

# The mark a coordinated plan carries for the adapter that translates it.
REPLAY_FLAGS = tuple(f"{adapter['name']}_replay" for adapter in ADAPTERS.values())


def converters():
    """The translation of a member, by adapter script."""
    return {script: adapter['record'] for script, adapter in ADAPTERS.items()}


def menu_ready(primary):
    """Whether one of the adapters can update this stack from the menu."""
    return any(adapter['menu_ready'](primary) for adapter in ADAPTERS.values())


def flagged(plan):
    """The adapter whose mark a coordinated plan carries, or None."""
    return next((adapter for adapter in ADAPTERS.values() if plan.get(f"{adapter['name']}_replay")), None)


def derived(script, role):
    """The variables an adapter derives from the resources of a member."""
    return ADAPTERS.get(script, {}).get('derived', {}).get(role, {})


def application_paths(script):
    """The paths the application container of an adapter keeps its own data in."""
    return ADAPTERS.get(script, {}).get('application_paths')
