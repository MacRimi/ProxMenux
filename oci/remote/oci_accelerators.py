"""Preservation profiles for native DRM devices and NVIDIA Toolkit runtimes."""
from __future__ import annotations

import re
import oci_runtime_settings as runtime_settings
import oci_nvidia_dynamic as dynamic
import oci_gpu_devices as drm
import oci_nvidia_runtime as nvidia
from oci_ui import translate


def dynamic_mode(deployment):
    return any(d.get('kind') == 'nvidia-runtime' and d.get('runtime_mode') == 'dynamic'
               for d in deployment.get('devices', []))


def check_dynamic(config, value, deployment):
    hooks = [line.split(': ', 1)[1] for line in config.decode().splitlines()
             if line.startswith('lxc.hook.mount: ')]
    if len(hooks) != 1:
        raise ValueError(translate('The dynamic NVIDIA hook is missing or duplicated'))
    match = re.fullmatch(r'/usr/local/lib/proxmenux/oci/nvidia-mount-([a-f0-9]{64})\.sh', hooks[0])
    if not match:
        raise ValueError(translate('The NVIDIA hook path does not belong to the installer'))
    capabilities = next((e['value'] for e in reversed(deployment.get('environment', []))
                         if e['name'] == 'NVIDIA_DRIVER_CAPABILITIES'), 'compute,utility,video')
    return dynamic.validate(config, value, value, hooks[0], match[1], capabilities)


def verify_baseline(expected, deployment):
    if not dynamic_mode(deployment):
        verify(expected)
        return
    drm.verify({p: v for p, v in expected.items() if p != nvidia.KEY})
    if dynamic.gpu_identity(expected[nvidia.KEY]) != dynamic.gpu_identity(nvidia.snapshot()):
        raise ValueError(translate('The selected GPU changed'))


def drm_plan(deployment):
    return dict(deployment, devices=[d for d in deployment.get('devices', []) if d.get('kind') != 'nvidia-runtime'])


def planned(deployment):
    result = drm.planned(drm_plan(deployment))
    if nvidia.enabled(deployment):
        value = nvidia.snapshot()
        if set(result) & set(value['devices']):
            raise ValueError(translate('Duplicated NVIDIA devices'))
        result[nvidia.KEY] = value
    return result


def verify(expected):
    drm.verify({p: v for p, v in expected.items() if p != nvidia.KEY})
    if nvidia.KEY in expected:
        nvidia.verify(expected[nvidia.KEY])


def check(config, deployment):
    config = runtime_settings.filter_config(config, deployment)
    expected = planned(deployment)
    value = expected.get(nvidia.KEY)
    if value:
        nvidia.check_devices(config, value)
        if dynamic_mode(deployment):
            check_dynamic(config, value, deployment)
        else:
            nvidia.check_mounts(config, value)
        filtered = []
        for line in config.splitlines(keepends=True):
            if re.match(rb'dev[0-9]+: ', line):
                fields = dict(part.split('=', 1) for part in line.decode().strip().split(': ', 1)[1].split(','))
                if fields.get('path') in value['devices']:
                    continue
            filtered.append(line)
        filtered = b''.join(filtered)
        drm.check(filtered, drm_plan(deployment))
    else:
        if nvidia.mount_lines(config):
            raise ValueError(translate('LXC entries outside the selected acceleration profile'))
        drm.check(config, deployment)
    return expected


def capture(config):
    result = drm.capture(config)
    if any(isinstance(p, str) and p.startswith('/dev/nvidia') for p in drm.actual_devices(config)):
        result[nvidia.KEY] = nvidia.snapshot()
    return result


def verify_observation(expected, observed):
    if observed.get('gpu_devices', {}) != expected:
        raise ValueError(translate('The acceleration evidence differs from the verified inventory'))
    verify(expected)


def validate_runtime(vmid, deployment):
    if nvidia.enabled(deployment):
        value = nvidia.snapshot()
        if dynamic_mode(deployment):
            rows = nvidia.command('pct', 'exec', str(vmid), '--', 'nvidia-smi', nvidia.QUERY, '--format=csv,noheader')
            if sorted(line.strip() for line in rows.splitlines() if line.strip()) != value['gpus']:
                raise ValueError(translate('NVML does not match the current host driver'))
        else:
            nvidia.validate_runtime(vmid, value)


def check_recovery_entries(config, state):
    runtime_settings.check_recovery(config, state)
    for key in ('record', 'candidate_contract'):
        config = runtime_settings.filter_config(config, state.get(key, {}).get('deployment', {}))
    entries = nvidia.mount_lines(config)
    if not entries:
        return
    values = [state.get(key, {}).get(nvidia.KEY) for key in ('original_gpu_devices', 'desired_gpu_devices')]
    for value in values:
        if value:
            try:
                nvidia.check_mounts(config, value, complete=False)
                return
            except ValueError:
                continue
    raise ValueError(translate('LXC entries outside the NVIDIA inventory of the journal'))
