from flask import Blueprint, jsonify, request
import json
import os
import re

from jwt_middleware import require_auth

# Sprint 12A: dynamic post-install version detector. The TOOL_METADATA
# table below still owns the user-facing display names + deprecated
# flags + has-source-on-disk hints, but the actual versions and short
# descriptions now come from the live `# version:` / `# description:`
# comments parsed from the on-disk post-install scripts.
import post_install_versions

proxmenux_bp = Blueprint('proxmenux', __name__)

# Tool metadata: description, function name in bash script, and version
# version: current version of the optimization function
# function: the bash function name that implements this optimization
TOOL_METADATA = {
    'subscription_banner':  {'name': 'Subscription Banner Removal',           'function': 'remove_subscription_banner',   'version': '1.0'},
    'time_sync':            {'name': 'Time Synchronization',                  'function': 'configure_time_sync',          'version': '1.0'},
    'apt_languages':        {'name': 'APT Language Skip',                     'function': 'skip_apt_languages',           'version': '1.0'},
    'journald':             {'name': 'Journald Optimization',                 'function': 'optimize_journald',            'version': '1.1'},
    'logrotate':            {'name': 'Logrotate Optimization',                'function': 'optimize_logrotate',           'version': '1.1'},
    'system_limits':        {'name': 'System Limits Increase',                'function': 'increase_system_limits',       'version': '1.1'},
    # entropy removed — modern kernels 5.6+ have built-in entropy generation, haveged no longer needed
    'memory_settings':      {'name': 'Memory Settings Optimization',          'function': 'optimize_memory_settings',     'version': '1.1'},
    'kernel_panic':         {'name': 'Kernel Panic Configuration',            'function': 'configure_kernel_panic',       'version': '1.0'},
    'apt_ipv4':             {'name': 'APT IPv4 Force',                        'function': 'force_apt_ipv4',               'version': '1.0'},
    'kexec':                {'name': 'kexec for quick reboots',               'function': 'enable_kexec',                 'version': '1.0'},
    'network_optimization': {'name': 'Network Optimizations',                 'function': 'apply_network_optimizations',  'version': '1.0'},
    'bashrc_custom':        {'name': 'Bashrc Customization',                  'function': 'customize_bashrc',             'version': '1.0'},
    'figurine':             {'name': 'Figurine',                              'function': 'configure_figurine',           'version': '1.0'},
    'fastfetch':            {'name': 'Fastfetch',                             'function': 'configure_fastfetch',          'version': '1.0'},
    'log2ram':              {'name': 'Log2ram (SSD Protection)',               'function': 'configure_log2ram',            'version': '1.0'},
    'amd_fixes':            {'name': 'AMD CPU (Ryzen/EPYC) fixes',            'function': 'apply_amd_fixes',              'version': '1.0'},
    'persistent_network':   {'name': 'Setting persistent network interfaces', 'function': 'setup_persistent_network',     'version': '1.0'},
    'vfio_iommu':           {'name': 'VFIO/IOMMU Passthrough',                'function': 'enable_vfio_iommu',            'version': '1.0'},
    'lvm_repair':           {'name': 'LVM PV Headers Repair',                 'function': 'repair_lvm_headers',           'version': '1.0'},
    'repo_cleanup':         {'name': 'Repository Cleanup',                    'function': 'cleanup_repos',                'version': '1.0'},
    # ── Legacy / Deprecated entries ──
    # These optimizations were applied by previous ProxMenux versions but are
    # no longer needed or have been removed from the current scripts. We still
    # expose their source code for transparency with existing users.
    'entropy':              {'name': 'Entropy Generation (haveged)',           'function': 'configure_entropy',            'version': '1.0', 'deprecated': True},
}

# Backward-compatible description mapping (used by get_installed_tools)
TOOL_DESCRIPTIONS = {k: v['name'] for k, v in TOOL_METADATA.items()}

# Source code preserved for deprecated/removed optimization functions.
# When a function is removed from the active bash scripts (because it's
# no longer needed, e.g. obsoleted by kernel improvements), keep its code
# here so users who installed it in the past can still inspect what ran.
DEPRECATED_SOURCES = {
    'configure_entropy': {
        'script': 'customizable_post_install.sh (legacy)',
        'source': '''# ─────────────────────────────────────────────────────────────────
# NOTE: This optimization has been REMOVED from current ProxMenux versions.
# Modern Linux kernels (5.6+, shipped with Proxmox VE 7.x and 8.x) include
# built-in entropy generation via the Jitter RNG and CRNG, making haveged
# unnecessary. The function below is preserved here for transparency so
# users who applied it in the past can see exactly what was installed.
# New ProxMenux installations no longer include this optimization.
# ─────────────────────────────────────────────────────────────────

configure_entropy() {
    msg_info2 "$(translate "Configuring entropy generation to prevent slowdowns...")"

    # Install haveged
    msg_info "$(translate "Installing haveged...")"
    /usr/bin/env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' install haveged > /dev/null 2>&1
    msg_ok "$(translate "haveged installed successfully")"

    # Configure haveged
    msg_info "$(translate "Configuring haveged...")"
    cat <<EOF > /etc/default/haveged
#   -w sets low entropy watermark (in bits)
DAEMON_ARGS="-w 1024"
EOF

    # Reload systemd daemon
    systemctl daemon-reload > /dev/null 2>&1

    # Enable haveged service
    systemctl enable haveged > /dev/null 2>&1
    msg_ok "$(translate "haveged service enabled successfully")"

    register_tool "entropy" true
    msg_success "$(translate "Entropy generation configuration completed")"
}
''',
    },
}

# Scripts to search for function source code (in order of preference)
_SCRIPT_PATHS = [
    '/usr/local/share/proxmenux/scripts/post_install/customizable_post_install.sh',
    '/usr/local/share/proxmenux/scripts/post_install/auto_post_install.sh',
]


def _extract_bash_function(function_name: str) -> dict:
    """Extract a bash function's source code.

    Checks DEPRECATED_SOURCES first (for functions removed from active scripts),
    then searches the live bash scripts for `function_name() {` and captures
    everything until the matching closing `}`, respecting brace nesting.

    Returns {'source': str, 'script': str, 'line_start': int, 'line_end': int}
    or {'source': '', 'error': '...'} on failure.
    """
    # Check preserved deprecated source code first
    if function_name in DEPRECATED_SOURCES:
        entry = DEPRECATED_SOURCES[function_name]
        source = entry['source']
        return {
            'source': source,
            'script': entry['script'],
            'line_start': 1,
            'line_end': len(source.split('\n')),
        }

    for script_path in _SCRIPT_PATHS:
        if not os.path.isfile(script_path):
            continue
        try:
            with open(script_path, 'r') as f:
                lines = f.readlines()

            # Find function start: "function_name() {" or "function_name () {"
            pattern = re.compile(rf'^{re.escape(function_name)}\s*\(\)\s*\{{')
            start_idx = None
            for i, line in enumerate(lines):
                if pattern.match(line):
                    start_idx = i
                    break

            if start_idx is None:
                continue  # Try next script

            # Capture until the closing } at indent level 0
            brace_depth = 0
            end_idx = start_idx
            for i in range(start_idx, len(lines)):
                brace_depth += lines[i].count('{') - lines[i].count('}')
                if brace_depth <= 0:
                    end_idx = i
                    break

            source = ''.join(lines[start_idx:end_idx + 1])
            script_name = os.path.basename(script_path)

            return {
                'source': source,
                'script': script_name,
                'line_start': start_idx + 1,
                'line_end': end_idx + 1,
            }
        except Exception:
            continue

    return {'source': '', 'error': 'Function not found in available scripts'}

@proxmenux_bp.route('/api/proxmenux/update-status', methods=['GET'])
def get_update_status():
    """Get ProxMenux update availability status from config.json"""
    config_path = '/usr/local/share/proxmenux/config.json'
    
    try:
        if not os.path.exists(config_path):
            return jsonify({
                'success': True,
                'update_available': {
                    'stable': False,
                    'stable_version': '',
                    'beta': False,
                    'beta_version': ''
                }
            })
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        update_status = config.get('update_available', {
            'stable': False,
            'stable_version': '',
            'beta': False,
            'beta_version': ''
        })
        
        return jsonify({
            'success': True,
            'update_available': update_status
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@proxmenux_bp.route('/api/proxmenux/installed-tools', methods=['GET'])
def get_installed_tools():
    """Get list of installed ProxMenux tools/optimizations.

    Sprint 12A: each entry now carries both the version the user has
    installed (read from installed_tools.json — accepts the legacy
    boolean shape and the new structured object shape) and the version
    currently declared in the on-disk post-install script. ``has_update``
    is true when the declared version is higher than the installed one,
    which is what the Settings → ProxMenux Optimizations card uses to
    flag the tool as updateable.
    """
    installed_tools_path = '/usr/local/share/proxmenux/installed_tools.json'

    try:
        if not os.path.exists(installed_tools_path):
            return jsonify({
                'success': True,
                'installed_tools': [],
                'updates_available_count': 0,
                'message': 'No ProxMenux optimizations installed yet'
            })

        with open(installed_tools_path, 'r') as f:
            raw = json.load(f)

        # Sprint 12A: index update list by tool key for has_update lookup.
        try:
            piv_snapshot = post_install_versions.get_snapshot()
        except Exception:
            piv_snapshot = {'updates': []}
        update_by_key = {u['key']: u for u in piv_snapshot.get('updates', [])}

        tools = []
        for tool_key, value in raw.items():
            # Normalize legacy bool vs new structured entry.
            if isinstance(value, bool):
                if not value:
                    continue
                installed_version = '1.0'
                source = ''
            elif isinstance(value, dict):
                if not value.get('installed', False):
                    continue
                installed_version = str(value.get('version', '1.0')) or '1.0'
                source = str(value.get('source', '') or '')
            else:
                continue

            # Hard-coded display metadata (display name, deprecated flag).
            meta = TOOL_METADATA.get(tool_key, {})

            # Live metadata from parsed scripts (version + description) —
            # picks the entry matching the recorded source. We also pull
            # the per-flow function names directly out of the snapshot so
            # the frontend's picker can route to the right script when a
            # legacy bool entry has to choose between auto and custom.
            live = post_install_versions.get_metadata_for_tool(tool_key)
            auto_meta = piv_snapshot.get('auto', {}).get(tool_key) or {}
            custom_meta = piv_snapshot.get('custom', {}).get(tool_key) or {}

            available_version = live['version'] if live else meta.get('version', installed_version)
            description = live['description'] if live else ''

            update_info = update_by_key.get(tool_key)

            tools.append({
                'key': tool_key,
                'name': meta.get('name', tool_key.replace('_', ' ').title()),
                'enabled': True,
                'version': installed_version,
                'available_version': available_version,
                'description': description,
                'source': source,
                # Sprint 12B: function name the wrapper should run for the
                # active source (live), plus the per-flow names so the
                # legacy-bool picker can choose between auto and custom.
                'function': (live.get('function') if live else '') or meta.get('function', ''),
                'function_auto': auto_meta.get('function', ''),
                'function_custom': custom_meta.get('function', ''),
                'has_source': bool(meta.get('function')) or bool(live),
                'deprecated': bool(meta.get('deprecated', False)),
                'has_update': update_info is not None,
                'update_source_certain': bool(update_info.get('source_certain', False)) if update_info else True,
            })

        tools.sort(key=lambda x: x['name'])

        return jsonify({
            'success': True,
            'installed_tools': tools,
            'total_count': len(tools),
            'updates_available_count': sum(1 for t in tools if t['has_update']),
        })

    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'error': 'Invalid JSON format in installed_tools.json'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@proxmenux_bp.route('/api/updates/post-install', methods=['GET'])
def get_post_install_updates():
    """Sprint 12A: list of post-install function updates available.

    Returns the cached scan result populated at AppImage startup. Each
    entry carries enough info for the UI to decide which function to
    invoke when the user clicks "Update": tool key, source (auto/custom),
    function name, before/after versions and a human description.

    ``source_certain`` is false for tools whose installed entry was a
    legacy boolean (no source recorded) — the UI should ask the user
    which flow to run before triggering the update.
    """
    try:
        snapshot = post_install_versions.get_snapshot()
        return jsonify({
            'success': True,
            'scanned_at': snapshot.get('scanned_at', 0),
            'updates': snapshot.get('updates', []),
            'total': len(snapshot.get('updates', [])),
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'updates': [],
        }), 500


@proxmenux_bp.route('/api/updates/post-install/scan', methods=['POST'])
def rescan_post_install_updates():
    """Sprint 12A: force a re-scan of the post-install scripts.

    Used by the Monitor's "refresh" affordance and by the bash menu
    when the user has just finished applying updates. The scan parses
    both post-install scripts and re-reads installed_tools.json, so it
    picks up version bumps applied by a `git pull` or by a previous
    Update click in the same session.
    """
    try:
        snapshot = post_install_versions.scan(persist=True)
        return jsonify({
            'success': True,
            'scanned_at': snapshot.get('scanned_at', 0),
            'updates': snapshot.get('updates', []),
            'total': len(snapshot.get('updates', [])),
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
        }), 500


@proxmenux_bp.route('/api/proxmenux/snippets-storage', methods=['GET'])
def get_snippets_storage():
    """Sprint 13 / issue #195: list candidate storages for snippets and
    the currently selected preference.

    Reads `pvesm status -content snippets` to enumerate the storages
    that accept hookscripts on this host. Reads
    `/usr/local/share/proxmenux/config.json -> snippets_storage` to
    return whichever the user has previously chosen (the bash flow auto-
    saves it the first time GPU passthrough is configured on a host
    with multiple shared storages).
    """
    config_path = '/usr/local/share/proxmenux/config.json'
    selected = ''
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                cfg = json.load(f)
            selected = str(cfg.get('snippets_storage', '') or '')
    except Exception:
        selected = ''

    import subprocess

    def _list() -> list[dict[str, str]]:
        try:
            proc = subprocess.run(
                ['pvesm', 'status', '-content', 'snippets'],
                capture_output=True, text=True, timeout=10
            )
            if proc.returncode != 0:
                return []
            out: list[dict[str, str]] = []
            for line in proc.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) < 3:
                    continue
                name, stype, status = parts[0], parts[1], parts[2]
                out.append({
                    'name': name,
                    'type': stype,
                    'active': status == 'active',
                })
            return out
        except Exception:
            return []

    candidates = _list()

    # PVE 9 ships `local` without `snippets` in its content list, so a
    # fresh install lists zero candidates here. Mirror what the bash
    # helper does — auto-enable snippets on local — so the Monitor's
    # selector isn't perpetually empty before the user runs GPU
    # passthrough for the first time.
    if not candidates:
        try:
            subprocess.run(
                ['pvesm', 'set', 'local', '--content', 'vztmpl,iso,import,backup,snippets'],
                capture_output=True, text=True, timeout=10, check=False,
            )
            candidates = _list()
        except Exception:
            pass

    return jsonify({
        'success': True,
        'selected': selected,
        'candidates': candidates,
    })


@proxmenux_bp.route('/api/proxmenux/snippets-storage', methods=['POST'])
@require_auth
def set_snippets_storage():
    """Sprint 13 / issue #195: persist the user's snippets storage
    preference in config.json. The bash helper reads this value next
    time it needs to install a hookscript so the user only has to pick
    once."""
    try:
        data = request.get_json(silent=True) or {}
        storage = str(data.get('storage', '') or '').strip()
        if not storage:
            return jsonify({'success': False, 'error': 'storage is required'}), 400

        # Validate the storage actually exists with content=snippets.
        # Otherwise a typo here would silently break GPU passthrough
        # next time a user runs it. Better to reject up front.
        import subprocess
        proc = subprocess.run(
            ['pvesm', 'status', '-content', 'snippets'],
            capture_output=True, text=True, timeout=10
        )
        valid_names: set[str] = set()
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if parts:
                    valid_names.add(parts[0])

        if storage not in valid_names:
            return jsonify({
                'success': False,
                'error': f"Storage '{storage}' is not active or doesn't support snippets content",
                'available': sorted(valid_names),
            }), 400

        config_path = '/usr/local/share/proxmenux/config.json'
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            cfg: dict = {}
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    cfg = json.load(f) or {}
            cfg['snippets_storage'] = storage
            with open(config_path, 'w') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to persist preference: {e}'}), 500

        return jsonify({'success': True, 'selected': storage})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@proxmenux_bp.route('/api/proxmenux/tool-source/<tool_key>', methods=['GET'])
def get_tool_source(tool_key):
    """Get the bash source code of a specific optimization function.

    Returns the function body extracted from the post-install scripts,
    so users can see exactly what code was executed on their server.
    """
    try:
        meta = TOOL_METADATA.get(tool_key)
        if not meta:
            return jsonify({
                'success': False,
                'error': f'Unknown tool: {tool_key}'
            }), 404

        func_name = meta.get('function')
        if not func_name:
            return jsonify({
                'success': False,
                'error': f'No function mapping for {tool_key}'
            }), 404

        result = _extract_bash_function(func_name)

        if not result.get('source'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Source code not available'),
                'tool': tool_key,
                'function': func_name,
            }), 404

        return jsonify({
            'success': True,
            'tool': tool_key,
            'name': meta['name'],
            'version': meta.get('version', '1.0'),
            'deprecated': bool(meta.get('deprecated', False)),
            'function': func_name,
            'source': result['source'],
            'script': result['script'],
            'line_start': result['line_start'],
            'line_end': result['line_end'],
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
