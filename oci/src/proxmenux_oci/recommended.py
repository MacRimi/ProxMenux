"""Settings a newer catalog recipe recommends for an installed application.

Only values still at the default of the installed recipe are proposed: what
the user changed, in ProxMenux or in Proxmox, is kept."""
from __future__ import annotations

import copy
from pathlib import Path
import re
from typing import Any

from .i18n import translate
from .installer import (cache_size_factor, context_budget, fit_memory_to_host, proportional_cores,
                        value_for_memory)


def latest_template(project: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """The current catalog recipe of the installed application, if it is the
    same application and image."""
    from .catalog import Catalog
    old = record.get('template', {})
    template_id = old.get('id', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]+', template_id) or not old.get('container_contract', {}).get('image'):
        return None
    catalog = Catalog(project)
    matching = [item for item in catalog.load_index()['applications'] if item.get('template_id') == template_id]
    if len(matching) != 1:
        return None
    latest = catalog.compose(matching[0]['id'])
    if (latest.get('id') != template_id or latest['container_contract']['image'].get('repository')
            != old['container_contract']['image'].get('repository')):
        return None
    return latest


def _memory_default(template: dict[str, Any]) -> int | None:
    proxmox = template.get('proxmox', {})
    value = proxmox.get('installer_profile', {}).get('resources', {}).get(
        'memory_default_mb', proxmox.get('defaults', {}).get('memory_mb'))
    return int(value) if value else None


def recommendation(record: dict[str, Any], latest: dict[str, Any],
                   host_mb: int | None, host_cpus: int | None,
                   gpu: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The candidate record with the recommended values, and what changes.
    `gpu` is the memory of the GPU the installation uses (host.gpu_memory)."""
    if any(key in record for key in ('stack', 'stack_member', 'native_stack_intent')):
        return None
    old_template = record.get('template', {})
    candidate = copy.deepcopy(record)
    deployment = candidate['deployment']
    resources = deployment.setdefault('resources', {})
    details = []

    memory = int(resources.get('memory_mb') or 0)
    old_memory, new_memory = _memory_default(old_template), _memory_default(latest)
    if memory and old_memory and memory == old_memory and new_memory and new_memory > memory:
        fitted, _ = fit_memory_to_host(new_memory, host_mb)
        if fitted > memory:
            details.append(f"{translate('Memory in MB')}: {memory} → {fitted}")
            resources['memory_mb'] = memory = fitted

    cores = int(resources.get('cores') or 0)
    old_cores = old_template.get('proxmox', {}).get('defaults', {}).get('cores')
    if cores and old_cores and cores == int(old_cores):
        wanted = proportional_cores(int(latest.get('proxmox', {}).get('defaults', {}).get('cores', cores)),
                                    memory, host_cpus)
        if wanted > cores:
            details.append(f"{translate('CPU cores')}: {cores} → {wanted}")
            resources['cores'] = wanted

    environment = deployment.setdefault('environment', [])
    current = {item['name']: item for item in environment}
    budget = context_budget(memory, gpu)
    # What the installed acceleration profile now sets and the installation
    # does not have yet, such as a compressed context cache on the CPU.
    profile = deployment.get('hardware_profile')

    def profile_environment(template):
        profiles = template.get('proxmox', {}).get('installer_profile', {}).get(
            'hardware_acceleration', {}).get('profiles', [])
        return next((p.get('environment') or [] for p in profiles if p.get('id') == profile), [])

    before = {entry['name'] for entry in profile_environment(old_template)}
    for entry in profile_environment(latest):
        if entry['name'] not in before and entry['name'] not in current and not entry.get('sensitive'):
            item = {'name': entry['name'], 'value': str(entry['value']), 'sensitive': False}
            environment.append(item)
            current[entry['name']] = item
            details.append(f"{entry['name']}={entry['value']}")
    old_examples = {item['name']: item.get('example')
                    for item in old_template.get('container_contract', {}).get('environment', [])}
    # Settings that depend on the memory come last, once the cache type they
    # are sized for is known.
    for item in sorted(latest['container_contract'].get('environment', []),
                       key=lambda entry: bool(entry.get('default_by_memory_mb'))):
        name = item['name']
        if item.get('sensitive') or (item.get('source') != 'proxmenux-overlay' and not item.get('default_by_memory_mb')):
            continue
        effective = int(budget / cache_size_factor(name, environment))
        value = value_for_memory(item.get('default_by_memory_mb'), effective) or item.get('example')
        if not value:
            continue
        if name not in current:
            environment.append({'name': name, 'value': value, 'sensitive': False})
            details.append(f"{name}={value}")
        elif (item.get('default_by_memory_mb') and current[name].get('value') == old_examples.get(name)
                and current[name].get('value') != value):
            details.append(f"{name}: {current[name].get('value')} → {value}")
            current[name]['value'] = value

    # A value still at the old recipe's default whose default has changed,
    # such as llama.cpp's GPU layers going from 999 to auto.
    for item in latest['container_contract'].get('environment', []):
        name, example = item['name'], item.get('example')
        if (item.get('sensitive') or item.get('default_by_memory_mb') or not example or name not in current
                or name not in old_examples or old_examples[name] in (None, '') or old_examples[name] == example):
            continue
        if current[name].get('value') == old_examples[name]:
            details.append(f"{name}: {current[name].get('value')} → {example}")
            current[name]['value'] = example

    if not details:
        return None
    return {'candidate': candidate, 'details': details}
