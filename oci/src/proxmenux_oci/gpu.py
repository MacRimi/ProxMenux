"""Image-specific GPU contracts, applied after catalog overlays on regeneration."""
from __future__ import annotations

from typing import Any

from .i18n import translate


LSIO_DEVICE_INIT = {"boinc", "emby", "jellyfin", "plex", "tvheadend"}


def apply_gpu_contract(template: dict[str, Any]) -> None:
    profile = template.get("proxmox", {}).get("installer_profile", {})
    if profile.get('selkies'):
        apply_selkies_contract(template)
    groups = [profile, *profile.get("hardware_acceleration", {}).get("profiles", [])]
    requests = [item for group in groups for key in ("device_requests", "optional_devices")
                for item in group.get(key, [])]
    gpu = [item for item in requests if item.get("kind") == "nvidia-runtime"
           or str(item.get("host_path_default", "")).startswith(("/dev/dri", "/dev/kfd"))]
    if not gpu:
        return
    image = template.get("container_contract", {}).get("image", {}).get("reference", "")
    repository = image.split("@", 1)[0].split(":", 1)[0]
    for item in gpu:
        if str(item.get("host_path_default", "")).startswith("/dev/dri/renderD"):
            item["container_path_strategy"] = "same-as-host"
    profile["gpu_validation"] = {
        "device_inventory": "host-sysfs-and-stat",
        "application_acceleration": "requires-workload-test",
        "tone_mapping": "not-implied-by-device-access",
    }
    if repository in {"lscr.io/linuxserver/" + app for app in LSIO_DEVICE_INIT} or profile.get('selkies'):
        profile["device_permissions"] = {
            "strategy": "linuxserver-native-init",
            "service_user": "abc",
            "environment": "ATTACHED_DEVICES_PERMS",
            "paths": "all-resolved-selected-character-devices",
        }
    elif repository == "jlesage/handbrake":
        for item in gpu:
            item["append_host_device_gid_to_environment"] = "SUP_GROUP_IDS"


def apply_selkies_contract(template):
    profile = template['proxmox']['installer_profile']
    if not template['container_contract']['image']['reference'].startswith('lscr.io/linuxserver/'):
        raise ValueError(translate('The Selkies profile requires a verified LinuxServer image'))
    environment = template['container_contract']['environment']
    if not any(e['name'] == 'LC_ALL' for e in environment):
        environment.append({'name': 'LC_ALL', 'example': '', 'required': False,
                            'sensitive': False, 'source': 'upstream-documentation',
                            'prompt': 'Language/locale (e.g. es_ES.UTF-8; translation of every application is not guaranteed)'})
    mounts = profile.setdefault('tmpfs_mounts', [])
    if not any(m['container_path'] == '/run/nginx' for m in mounts):
        mounts.append({'id': 'nginx-runtime', 'container_path': '/run/nginx',
                       'default_size_mb': 1, 'minimum_size_mb': 1, 'prompt_size': False,
                       'mount_options': ['rw', 'nosuid', 'nodev', 'mode=0755']})
    if profile.get('hardware_acceleration') or profile.get('device_requests'):
        return
    profile['optional_devices'] = [d for d in profile.get('optional_devices', [])
                                   if not str(d.get('host_path_default', '')).startswith('/dev/dri')]
    profile['hardware_acceleration'] = {
        'prompt': 'Selkies desktop and streaming acceleration', 'default': 'none',
        'profiles': [
            {'id': 'none', 'label': 'No GPU (CPU)', 'device_requests': [],
             'environment': [{'name': 'AUTO_GPU', 'value': 'false'}]},
            {'id': 'vaapi', 'label': 'Intel/AMD (streaming rendering and encoding)',
             'device_requests': [{'id': 'selkies-render', 'kind': 'character-device',
                 'path_prompt': 'Intel/AMD render node', 'host_path_default': '/dev/dri/renderD128',
                 'container_path_strategy': 'same-as-host', 'mode': '0660',
                 'deny_write': False, 'gid_strategy': 'host-device-gid',
                 'drm_vendor_ids': ['0x8086', '0x1002']}],
             'environment': [{'name': 'PIXELFLUX_WAYLAND', 'value': 'true'},
                             {'name': 'AUTO_GPU', 'value': 'false'}],
             'environment_from_devices': {'DRINODE': ['selkies-render'],
                                          'DRI_NODE': ['selkies-render'],
                                          'ATTACHED_DEVICES_PERMS': ['selkies-render']}}
        ]}


def apply_profile_image(template, hardware_profile):
    """Resolve an upstream image channel declared by the selected GPU profile."""
    import copy
    profiles = template.get('proxmox', {}).get('installer_profile', {}).get('hardware_acceleration', {}).get('profiles', [])
    selected = next((profile for profile in profiles if profile['id'] == hardware_profile), {})
    if selected.get('image'):
        template['container_contract']['image'] = copy.deepcopy(selected['image'])
