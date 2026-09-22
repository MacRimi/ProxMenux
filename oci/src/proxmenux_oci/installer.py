from __future__ import annotations

import base64
import copy
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from . import host
from . import network as access
from .i18n import translate
from .ui import DialogUI, TerminalUI, UserCancelled
from .custom_mounts import ask_custom_mounts


class InstallError(RuntimeError):
    pass


DEFAULT_MODE = "default"
ADVANCED_MODE = "advanced"


def _example_default(name: str, example: str | None, timezone: str | None = None) -> str | None:
    defaults = {"PUID": "1000", "PGID": "1000", "TZ": timezone or host.timezone()}
    if name in defaults:
        return defaults[name]
    if not example:
        return None
    variable = re.fullmatch(r"\$\{?[A-Za-z_][A-Za-z0-9_]*(?::-(.*?))?\}?", example)
    if variable:
        return variable.group(1)
    return example


def _hostname_default(value: str) -> str:
    hostname = re.sub(r"[^a-z0-9-]+", "-", value.casefold()).strip("-")[:63].rstrip("-")
    return hostname or "oci-app"


def _cpu_units_default(cpu_shares: int) -> int:
    # Docker uses 1024 and modern Proxmox uses 100 as their neutral relative weight.
    return max(8, min(10000, round(cpu_shares * 100 / 1024)))


def _is_system_bind(item: dict[str, Any]) -> bool:
    target = item["container_path"]
    source = str(item.get("compose_source_example") or "")
    exact_system_files = {"/etc/localtime", "/etc/timezone", "/etc/hosts", "/etc/resolv.conf"}
    system_prefixes = ("/dev/", "/proc/", "/sys/", "/run/", "/var/run/")
    return target in exact_system_files or target.startswith(system_prefixes) or source.startswith(system_prefixes)


def _shared_host_path_default(template: dict[str, Any], item: dict[str, Any]) -> str:
    if _is_system_bind(item):
        return str(item.get("compose_source_example") or item["container_path"])
    app_id = template["id"].removeprefix("image-")
    app_id = app_id.removeprefix("linuxserver-")
    volume_name = re.sub(r"[^a-z0-9]+", "-", item["container_path"].casefold()).strip("-")
    return f"/mnt/oci-shared/{app_id}/{volume_name or 'data'}"


def _ask_size(ui, container_path: str, default: int) -> int:
    """Size in whole GB of a container volume."""
    while True:
        answer = str(ui.ask(f"{translate('Size in GB of')} {container_path}", str(default))).strip()
        if answer.isdigit() and int(answer) >= 1:
            return int(answer)
        ui.message(f"{translate('Enter the size in whole GB, for example')} {default}.")


def ask_storage(ui, text: str, content: str, default: str, mode: str = ADVANCED_MODE) -> str:
    """A storage of this node that accepts `content`, picked from a list; in
    default mode the preferred one when it exists, otherwise the one with most
    free space."""
    if mode == DEFAULT_MODE:
        return host.default_storage(content, default)
    rows = host.storages(content)
    if not rows:
        return ui.ask(text, default)
    options = [(row["storage"], f"{row.get('type', '')}  {host.gib(row.get('avail'))} GB {translate('free')}")
               for row in rows]
    names = [name for name, _ in options]
    selected = ui.choose(text, options, default if default in names else names[0])
    if selected is None:
        raise UserCancelled(text)
    return selected


def ask_bridge(ui, text: str, default: str, mode: str = ADVANCED_MODE) -> str:
    if mode == DEFAULT_MODE:
        return host.default_bridge(default)
    rows = host.bridges()
    if not rows:
        return ui.ask(text, default)
    options = [(row["iface"], row.get("cidr") or (row.get("comments") or "").strip() or "-") for row in rows]
    names = [name for name, _ in options]
    selected = ui.choose(text, options, default if default in names else names[0])
    if selected is None:
        raise UserCancelled(text)
    return selected


def _confirm_warning(ui, warning: str | None, fallback: str, question: str) -> bool:
    return ui.confirm(f"{translate(warning) if warning else translate(fallback)}\n\n{translate(question)}", False)


def build_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI | None = None,
    mode: str = ADVANCED_MODE,
) -> dict[str, Any]:
    ui = ui or TerminalUI()
    if template.get('proxmox', {}).get('installer_profile', {}).get('stack_driver') == 'arr-suite':
        from .arr_suite import build_suite
        return build_suite(template, ui)
    if template.get('proxmox', {}).get('installer_profile', {}).get('stack_driver') == 'generic-multi-lxc-stack':
        from .stack import build_stack
        return build_stack(template, ui)
    if template.get("id") == "image-immich":
        return _build_immich_deployment(template, ui)
    if template.get("id") == "image-nextcloud-stack":
        return _build_nextcloud_stack_deployment(template, ui)
    if template.get("id") == "image-paperless-ngx":
        return _build_paperless_stack_deployment(template, ui)
    if template.get("id") == "image-tandoor":
        return _build_tandoor_stack_deployment(template, ui)
    if template.get("id") == "image-rclone":
        return _build_rclone_deployment(template, ui)
    advanced = mode != DEFAULT_MODE
    defaults = template["proxmox"]["defaults"]
    installer_profile = template["proxmox"].get("installer_profile", {})
    security_profile = template["proxmox"].get("security_profile", {})
    host_monitor = installer_profile.get("host_monitor")
    monitor_scope = "host" if host_monitor else None
    if host_monitor:
        expected = {"image-glances": "glances", "image-netdata": "netdata"}
        if host_monitor != expected.get(template.get("id")):
            raise InstallError(translate("Unrecognized host monitor profile"))
        fallback = host_monitor == "glances" and installer_profile.get("host_monitor_optional", False)
        alternative = ("\n\n" + translate("If you answer No, Glances is installed without privileges and "
                                          "monitors ONLY its own LXC, not Proxmox.") if fallback else "")
        if not ui.confirm(translate("This monitor uses a privileged LXC, shares processes and network with "
                                    "Proxmox and disables AppArmor in the CT. It uses the IP address and "
                                    "firewall of the host. A compromised image could affect the host; do not "
                                    "expose its web UI to the Internet.")
                          + alternative + "\n\n" + translate("Accept this host monitoring profile?"), False):
            if not fallback:
                raise UserCancelled(translate("Host monitoring declined"))
            host_monitor = None
            monitor_scope = "container"
            defaults = {**defaults, "unprivileged": True}
            security_profile = {}
            installer_profile = {**installer_profile, "security": {},
                                 "host_monitor": None, "host_monitor_mounts": []}
    if installer_profile.get("haos_healthcheck"):
        if not ui.confirm(translate("HAOS One is a community image that runs Docker inside the container. The "
                                    "LXC stays unprivileged, but the inner AppArmor profiles may not be "
                                    "available. The first start downloads Home Assistant Core and its add-ons. "
                                    "If the check fails, the CT and /mnt/data are kept for diagnosis.")
                          + "\n\n" + translate("Continue with the experimental HAOS One profile?"), False):
            raise UserCancelled(translate("HAOS One profile declined"))
    unprivileged = False if host_monitor else bool(defaults.get("unprivileged", True))
    privileged_acknowledged = bool(host_monitor)
    security_relaxation_acknowledged = bool(host_monitor)
    if security_profile.get("requires_host_pid_namespace") and not host_monitor:
        raise InstallError(translate("This template requests the host PID namespace, which has no validated "
                                     "safe LXC translation yet"))
    if security_profile.get("optional_privileged_lxc") and not host_monitor:
        if _confirm_warning(ui, security_profile.get("warning"),
                            "The source Compose requests privileged mode as a compatibility option.",
                            "Use the optional privileged mode requested by the source Compose?"):
            unprivileged = False
            privileged_acknowledged = True
    if security_profile.get("requires_privileged_lxc") and not host_monitor:
        if not _confirm_warning(ui, security_profile.get("warning"),
                                "This image requests a configuration with less isolation from the host.",
                                "Create this LXC in privileged mode?"):
            raise UserCancelled(translate("Privileged installation declined"))
        unprivileged = False
        privileged_acknowledged = True
    if security_profile.get("requires_relaxed_confinement") and not host_monitor:
        if not _confirm_warning(ui, security_profile.get("warning"),
                                "This image needs to reduce the AppArmor or seccomp confinement.",
                                "Apply this required security relaxation?"):
            raise UserCancelled(translate("Security relaxation declined"))
        security_relaxation_acknowledged = True

    selected_security_options = dict(
        installer_profile.get("security", {}).get("options", {})
    )
    for item in installer_profile.get("security", {}).get("optional_relaxations", []):
        enabled = (ui.confirm(translate(item["enable_prompt"]), item.get("enabled_default", False))
                   if advanced else item.get("enabled_default", False))
        if enabled:
            selected_security_options.update(item.get("options", {}))
            security_relaxation_acknowledged = True
    runtime_profile = installer_profile.get("runtime", {})
    hostname_default = _hostname_default(runtime_profile.get("hostname")
                                         or template["container_contract"]["container_name"])
    cpu_shares = installer_profile.get("resources", {}).get("cpu_shares")
    memory_default = installer_profile.get('resources', {}).get('memory_default_mb', defaults['memory_mb'])
    mac_address = installer_profile.get("network", {}).get("mac_address")
    timezone = host.timezone()
    if advanced:
        vmid_text = ui.ask(translate("VMID (empty = next free)"), "", required=False)
        hostname = ui.ask(translate("Hostname"), hostname_default)
        rootfs_storage = ask_storage(ui, translate("Storage for rootfs"), "rootdir", defaults["rootfs_storage"])
        volume_storage = ask_storage(ui, translate("Storage for persistent data"), "rootdir",
                                     defaults["volume_storage"])
        template_storage = ask_storage(ui, translate("Storage for the OCI image cache"), "vztmpl",
                                       defaults["template_storage"])
        rootfs_size = int(ui.ask(translate("Rootfs size in GB"), str(defaults["rootfs_size_gb"])))
        cores = int(ui.ask(translate("CPU cores"), str(defaults["cores"])))
        cpu_units = (int(ui.ask(translate("Relative CPU priority (cpuunits)"),
                                str(_cpu_units_default(int(cpu_shares)))))
                     if cpu_shares is not None else None)
        memory = int(ui.ask(translate("Memory in MB"), str(memory_default)))
        swap = int(ui.ask(translate("Swap in MB"), str(defaults["swap_mb"])))
        bridge = ask_bridge(ui, translate("Network bridge"), defaults["bridge"])
        if mac_address:
            mac_address = ui.ask(translate("MAC address"), mac_address)
        if host_monitor:
            ipv4, gateway = "host", None
        else:
            ipv4, gateway = access.ask_ipv4(ui, bridge)
        onboot = ui.confirm(translate("Start with Proxmox"), defaults["onboot"])
        start_after = ui.confirm(translate("Start when finished"), True)
    else:
        vmid_text = ""
        hostname = hostname_default
        rootfs_storage = ask_storage(ui, "", "rootdir", defaults["rootfs_storage"], DEFAULT_MODE)
        volume_storage = ask_storage(ui, "", "rootdir", defaults["volume_storage"], DEFAULT_MODE)
        template_storage = ask_storage(ui, "", "vztmpl", defaults["template_storage"], DEFAULT_MODE)
        rootfs_size = int(defaults["rootfs_size_gb"])
        cores = int(defaults["cores"])
        cpu_units = _cpu_units_default(int(cpu_shares)) if cpu_shares is not None else None
        memory = int(memory_default)
        swap = int(defaults["swap_mb"])
        bridge = ask_bridge(ui, "", defaults["bridge"], DEFAULT_MODE)
        ipv4 = "host" if host_monitor else defaults["ipv4"]
        gateway = None
        onboot = bool(defaults["onboot"])
        start_after = True

    environment: list[dict[str, str]] = []
    for item in template["container_contract"]["environment"]:
        name = item["name"]
        if item.get("prompt"):
            label = translate(item["prompt"])
        elif item["sensitive"]:
            label = f"{translate('Password or secret')} ({name})"
        else:
            label = f"{translate('Value for')} {name}"
        default = _example_default(name, item["example"], timezone)
        generated = installer_profile.get("generated_sensitive_environment", {}).get(name)
        if item.get("prompt_user", True) is False:
            if default in (None, "") and item["required"]:
                raise InstallError(f"{name}: {translate('no declarative value')}")
            if default not in (None, "") or item["required"]:
                environment.append({"name": name, "value": default or "", "sensitive": item["sensitive"]})
            continue
        if not item["required"]:
            # The image keeps its own default for every optional setting.
            if not advanced:
                continue
            if default in (None, "") and not ui.confirm(f"{translate('Configure')} {label}", False):
                continue
        if item["sensitive"]:
            if generated and (not advanced or not generated.get("prompt", True)):
                value = ""
            else:
                prompt = f"{label} ({translate('empty = generate')})" if generated else label
                value = ui.password(prompt, required=item["required"] and not generated)
            if not value and generated:
                if generated.get("strategy") != "token-hex":
                    raise InstallError(f"{name}: {translate('unsupported credential generator')}")
                value = secrets.token_hex(int(generated.get("bytes", 16)))
            if not value and item["required"]:
                raise InstallError(f"{name}: {translate('a value is required')}")
        elif not advanced and default not in (None, ""):
            value = default
        else:
            value = ui.ask(label, default, required=item["required"])
        if value or item["required"]:
            environment.append({"name": name, "value": value, "sensitive": item["sensitive"]})

    mounts: list[dict[str, Any]] = []
    host_bind_policies = installer_profile.get("host_bind_policies", {})
    labels = {"managed-volume": translate("Container volume (included in backups)"),
              "host-bind": translate("Host directory (not included in Proxmox backups)"),
              "skip": translate("Do not mount")}
    for item in template["container_contract"]["volumes"]:
        choices = item["installation_choice"]
        # A path that holds content of the user accepts a container volume or a
        # host directory, and that decision is the user's in both modes; a path
        # with a single option is never asked outside the advanced mode.
        offered = list(choices)
        chosen = advanced or {"managed-volume", "host-bind"} <= set(choices)
        if chosen:
            # The answer is the user's: a host directory is never proposed.
            proposed = "managed-volume" if item["default"] == "host-bind" else item["default"]
            volume_mode = ui.choose(f"{translate('Where to store')} {item['container_path']}",
                                    [(choice, labels[choice]) for choice in offered], proposed)
            if volume_mode is None:
                raise UserCancelled(translate("Volume configuration cancelled"))
        else:
            volume_mode = item["default"]
        if volume_mode == "skip":
            continue
        if volume_mode == "managed-volume":
            size = item["managed_volume"]["default_size_gb"]
            # Whoever chooses a container volume also chooses how big it is.
            if advanced or chosen:
                size = _ask_size(ui, item["container_path"], size)
            source = volume_storage
            backup = item["managed_volume"]["backup"]
        else:
            source = _shared_host_path_default(template, item)
            if chosen:
                source = ui.ask(f"{translate('Host path for')} {item['container_path']}", source)
            size = None
            backup = False
        policy = host_bind_policies.get(item["container_path"], {})
        mounts.append(
            {
                "type": volume_mode,
                "container_path": item["container_path"],
                "source": source,
                "size_gb": size,
                "backup": backup,
                "read_only": item["read_only"],
                "create_if_missing": bool(
                    policy.get("create_if_missing", not _is_system_bind(item))
                ),
            }
        )

    if advanced:
        mounts = ask_custom_mounts(ui, mounts, volume_storage)

    if host_monitor:
        for item in installer_profile.get("host_monitor_mounts", []):
            mounts.append({"type": "host-bind", "container_path": item["target"],
                           "source": item["source"], "size_gb": None, "backup": False,
                           "read_only": True, "create_if_missing": False})

    tmpfs_mounts: list[dict[str, Any]] = []
    for item in installer_profile.get("tmpfs_mounts", []):
        size_mb = int(item["default_size_mb"])
        if advanced and item.get("prompt_size", True):
            size_prompt = (translate(item["size_prompt"]) if item.get("size_prompt")
                           else f"{translate('tmpfs size in MB for')} {item['container_path']}")
            size_mb = int(ui.ask(size_prompt, str(size_mb)))
        if size_mb < int(item.get("minimum_size_mb", 1)):
            raise InstallError(f"{translate('tmpfs size too small for')} {item['container_path']}")
        tmpfs_mounts.append(
            {
                "container_path": item["container_path"],
                "size_mb": size_mb,
                "mount_options": item.get("mount_options", ["rw", "nosuid", "nodev"]),
            }
        )

    devices, selected_hardware_profile, post_start_configurations, environment = configure_acceleration(
        installer_profile, environment, unprivileged, ui, mode)

    from .gpu import apply_profile_image
    apply_profile_image(template, selected_hardware_profile)

    if post_start_configurations and not start_after:
        if not ui.confirm(translate("The application configuration needs a first start to complete.")
                          + "\n\n" + translate("Start the LXC when finished to apply the selected configuration?"),
                          True):
            raise UserCancelled(translate("The post-start configuration cannot be applied with the LXC stopped"))
        start_after = True

    host_modules: list[str] = []
    for item in installer_profile.get("security", {}).get("host_modules", []):
        enabled = (ui.confirm(translate(item["enable_prompt"]), item.get("enabled_default", True))
                   if advanced else item.get("enabled_default", True) or item.get("required_by_compose"))
        if not enabled:
            if item.get("required_by_compose"):
                raise UserCancelled(f"{translate('This image requires the host module')} {item['name']}")
            continue
        host_modules.append(item["name"])

    if installer_profile.get("haos_healthcheck"):
        data = [m for m in mounts if m['container_path'] == '/mnt/data']
        if (not unprivileged or defaults.get('ostype') != 'unmanaged'
                or not {'nesting=1', 'keyctl=1'}.issubset(defaults.get('features', []))
                or len(data) != 1 or data[0]['type'] != 'managed-volume'
                or not data[0]['backup'] or data[0]['size_gb'] < 16
                or memory < 2048 or cores < 2 or rootfs_size < 12):
            raise InstallError(translate("HAOS One requires an unprivileged unmanaged LXC with nesting and "
                                         "keyctl, 2 cores, 2048 MB RAM, rootfs of at least 12 GB and /mnt/data "
                                         "of at least 16 GB on a container volume included in backups"))

    return {
        "host_monitor": host_monitor,
        "monitor_scope": monitor_scope,
        "vmid": int(vmid_text) if vmid_text else None,
        "ostype": defaults.get("ostype", "auto-from-image"),
        "hostname": hostname,
        "template_storage": template_storage,
        "rootfs": {"storage": rootfs_storage, "size_gb": rootfs_size},
        "resources": {
            "cores": cores,
            "memory_mb": memory,
            "swap_mb": swap,
            "cpu_units": cpu_units,
            "rlimits": installer_profile.get('resources', {}).get('rlimits', []),
        },
        "network": {
            "bridge": bridge,
            "ipv4": ipv4,
            "gateway": gateway,
            "firewall": defaults["firewall"],
            "host_managed": defaults["host_managed_network"],
            "mac_address": mac_address,
        },
        "features": defaults.get("features", []),
        "security": {
            "unprivileged": unprivileged,
            "privileged_acknowledged": privileged_acknowledged,
            "relaxation_acknowledged": (
                security_relaxation_acknowledged or privileged_acknowledged
            ),
            "required_capabilities": installer_profile.get("security", {}).get(
                "required_capabilities", []
            ),
            "sysctls": installer_profile.get("security", {}).get("sysctls", []),
            "options": selected_security_options,
            "host_modules": host_modules,
        },
        "shutdown_timeout_seconds": defaults.get("shutdown_timeout_seconds", 30),
        "onboot": onboot,
        "start_after_create": start_after,
        "environment": environment,
        "mounts": mounts,
        "tmpfs_mounts": tmpfs_mounts,
        "devices": devices,
        "hardware_profile": selected_hardware_profile,
        "device_permissions": installer_profile.get("device_permissions") if devices else None,
        "post_start_configurations": post_start_configurations,
        "extra_hosts": installer_profile.get("extra_hosts", []),
    }


def _build_rclone_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI,
) -> dict[str, Any]:
    schema = template["proxmox"]["laboratory_contract"]["configuration_schema"]
    defaults = template["proxmox"]["defaults"]
    if not ui.confirm(translate("Rclone mount needs a privileged LXC with FUSE access. The container is "
                                "dedicated to Rclone and its web UI must not be exposed to untrusted networks.")
                      + "\n\n" + translate("Create this LXC in privileged mode?"), False):
        raise UserCancelled(translate("Privileged installation declined"))

    vmid_text = ui.ask(translate("VMID (empty = next free)"), "", required=False)
    hostname = ui.ask(translate("Hostname"), schema["hostname"]["default"])
    rootfs_storage = ask_storage(ui, translate("Storage for rootfs"), "rootdir", schema["rootfs_storage"]["default"])
    config_storage = ask_storage(ui, translate("Storage for the persistent configuration"), "rootdir",
                                 schema["config_storage"]["default"])
    template_storage = ask_storage(ui, translate("Storage for the OCI image cache"), "vztmpl",
                                   defaults["template_storage"])
    rootfs_size = int(ui.ask(translate("Rootfs size in GB"), str(schema["rootfs_size_gb"]["default"])))
    config_size = int(ui.ask(translate("Configuration size in GB"), str(schema["config_size_gb"]["default"])))
    if rootfs_size < schema["rootfs_size_gb"]["minimum"]:
        raise InstallError(translate("The Rclone rootfs needs at least 2 GB"))
    if config_size < schema["config_size_gb"]["minimum"]:
        raise InstallError(translate("The Rclone configuration needs at least 1 GB"))
    data_host_path = ui.ask(translate("Shared directory for copy/sync operations"),
                            schema["data_host_path"]["default"])
    username = ui.ask(translate("Web UI user"), schema["webui_username"]["default"])
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username):
        raise InstallError(translate("The web UI user contains characters that are not allowed"))
    password = ui.password(f"{translate('Web UI password')} ({translate('empty = generate')})", required=False)
    if not password:
        password = secrets.token_hex(16)
    if len(password) < 24:
        raise InstallError(translate("The web UI password must have at least 24 characters"))
    bridge = ask_bridge(ui, translate("Network bridge"), schema["bridge"]["default"])
    ipv4, gateway = access.ask_ipv4(ui, bridge)

    return {
        "vmid": int(vmid_text) if vmid_text else None,
        "hostname": hostname,
        "template_storage": template_storage,
        "rootfs": {"storage": rootfs_storage, "size_gb": rootfs_size},
        "resources": {
            "cores": defaults["cores"],
            "memory_mb": defaults["memory_mb"],
            "swap_mb": defaults["swap_mb"],
            "cpu_units": None,
        },
        "network": {
            "bridge": bridge,
            "ipv4": ipv4,
            "gateway": gateway,
            "firewall": defaults["firewall"],
            "host_managed": defaults["host_managed_network"],
            "mac_address": None,
        },
        "features": defaults["features"],
        "security": {
            "unprivileged": False,
            "privileged_acknowledged": True,
            "relaxation_acknowledged": True,
            "required_capabilities": ["SYS_ADMIN"],
            "sysctls": [],
            "options": {},
            "host_modules": [],
        },
        "shutdown_timeout_seconds": defaults["shutdown_timeout_seconds"],
        "onboot": ui.confirm(translate("Start with Proxmox"), defaults["onboot"]),
        "start_after_create": ui.confirm(translate("Start when finished"), True),
        "environment": [
            {"name": "XDG_CONFIG_HOME", "value": "/config", "sensitive": False},
            {"name": "RCLONE_RC_USER", "value": username, "sensitive": False},
            {"name": "RCLONE_RC_PASS", "value": password, "sensitive": True},
        ],
        "mounts": [
            {
                "type": "managed-volume",
                "container_path": "/config/rclone",
                "source": config_storage,
                "size_gb": config_size,
                "backup": True,
                "read_only": False,
                "create_if_missing": False,
            },
            {
                "type": "host-bind",
                "container_path": "/data",
                "source": data_host_path,
                "size_gb": None,
                "backup": False,
                "read_only": False,
                "create_if_missing": True,
            },
        ],
        "tmpfs_mounts": [],
        "devices": [],
        "extra_hosts": [],
    }


def build_rclone_mount_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI | None = None,
) -> dict[str, Any]:
    ui = ui or TerminalUI()
    schema = template["proxmox"]["laboratory_contract"]["configuration_schema"]
    ui.message(translate("The remote must already be created and authorized in the Rclone web UI. This "
                         "operation restarts the CT and publishes two FUSE views on the host."))
    vmid = int(ui.ask(translate("VMID of the Rclone OCI container")))
    remote_name = ui.ask(translate("Exact name of the remote"))
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", remote_name):
        raise InstallError(translate("Invalid remote name"))
    remote_path = ui.ask(translate("Path inside the remote (empty = root)"), "", required=False)
    if "\n" in remote_path or "\r" in remote_path or remote_path.startswith("/"):
        raise InstallError(translate("The remote path must be relative and cannot contain line breaks"))
    mount_name = ui.ask(translate("Mount name"), remote_name)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", mount_name):
        raise InstallError(translate("Invalid mount name"))
    vfs_cache_mode = ui.choose(
        translate("VFS cache mode"),
        [(value, value) for value in schema["vfs_cache_mode"]["options"]],
        schema["vfs_cache_mode"]["default"],
    )
    if vfs_cache_mode is None:
        raise UserCancelled(translate("Mount configuration cancelled"))
    shared_parent = ui.ask(translate("Common root for the published views"),
                           schema["shared_mount_root_parent"]["default"])
    shared_rw = ui.ask(translate("Directory for the read/write view"), schema["shared_mount_root"]["default"])
    shared_ro = ui.ask(translate("Directory for the read-only view"),
                       schema["shared_mount_read_only_root"]["default"])
    if not ui.confirm(translate("Enable this FUSE mount now and restart the CT?"), False):
        raise UserCancelled(translate("Mount activation cancelled"))
    return {
        "deployment_kind": "rclone-mount-activation",
        "vmid": vmid,
        "remote_name": remote_name,
        "remote_path": remote_path,
        "mount_name": mount_name,
        "vfs_cache_mode": vfs_cache_mode,
        "shared_mount_root_parent": shared_parent,
        "shared_mount_root": shared_rw,
        "shared_mount_read_only_root": shared_ro,
    }


def _build_immich_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI,
) -> dict[str, Any]:
    defaults = template["proxmox"]["laboratory_contract"]["defaults"]
    pve_defaults = template["proxmox"]["defaults"]
    vmid_text = ui.ask(translate("Base VMID of the server (empty = next free block)"), "", required=False)
    stack_name = ui.ask(translate("Stack name"), defaults["stack_name"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", stack_name):
        raise InstallError(translate("The stack name only accepts lowercase letters, numbers and hyphens"))
    rootfs_storage = ask_storage(ui, translate("Storage for rootfs"), "rootdir", defaults["rootfs_storage"])
    database_storage = ask_storage(ui, translate("Local storage for PostgreSQL"), "rootdir", defaults["database_storage"])
    template_storage = ask_storage(ui, translate("Storage for the OCI image cache"), "vztmpl", pve_defaults["template_storage"])
    media_mode = ui.choose(
        translate("Storage for the Immich library"),
        [
            ("managed-volume", translate("Dedicated container volume (included in backups)")),
            ("host-bind", translate("Shared host directory (not included in Proxmox backups)")),
        ],
        "managed-volume",
    )
    if media_mode is None:
        raise UserCancelled(translate("Immich configuration cancelled"))
    if media_mode == "managed-volume":
        media_storage = ask_storage(ui, translate("Storage for the Immich library"), "rootdir", pve_defaults["volume_storage"])
        media_size = int(ui.ask(translate("Library size in GB"), "100"))
        if media_size < 8:
            raise InstallError(translate("The Immich library needs at least 8 GB"))
        media_root = None
    else:
        media_default = defaults["shared_media_root"].replace("${stack_name}", stack_name)
        media_root = ui.ask(translate("Shared host directory"), media_default)
        media_storage = None
        media_size = None
    database_size = int(
        ui.ask(translate("PostgreSQL volume size in GB"), str(defaults["database_size_gb"]))
    )
    if database_size < 8:
        raise InstallError(translate("The PostgreSQL volume needs at least 8 GB"))
    frontend_bridge = ask_bridge(ui, translate("Access bridge for Immich"), defaults["frontend_network"]["bridge"])
    addresses, frontend_gateway = access.ask_addresses(
        ui, frontend_bridge, [translate("Immich server"), translate("Immich machine learning")])
    server_ipv4, ml_ipv4 = addresses.values()
    timezone = ui.ask(translate("Timezone"), host.timezone())
    video_acceleration = ui.choose(
        translate("Video transcoding acceleration"),
        [("vaapi", "VA-API"), ("cpu", "CPU")],
        defaults["video_transcoding"]["acceleration"],
    )
    if video_acceleration is None:
        raise UserCancelled(translate("Immich configuration cancelled"))
    render_device = None
    vaapi_driver = "auto"
    if video_acceleration == "vaapi":
        render_device = ui.ask(
            translate("VA-API render device"), defaults["video_transcoding"]["render_device"]
        )
        vaapi_driver = ui.choose(
            translate("VA-API driver"),
            [("auto", translate("Automatic detection")), ("radeonsi", "AMD radeonsi"), ("iHD", "Intel iHD"), ("i965", "Intel i965")],
            defaults["video_transcoding"]["driver"],
        )
        if vaapi_driver is None:
            raise UserCancelled(translate("Immich configuration cancelled"))
    ml_acceleration = ui.choose(
        translate("Acceleration for Immich smart recognition"),
        [("cpu", "CPU"), ("openvino", "Intel GPU / OpenVINO"),
         ("cuda", translate("NVIDIA GPU / CUDA (Toolkit on the host)"))],
        "cpu",
    )
    if ml_acceleration is None:
        raise UserCancelled(translate("Immich configuration cancelled"))
    if ml_acceleration not in ("cpu", "openvino", "cuda"):
        raise InstallError(translate("Recognition profile not implemented"))
    ml_render = None
    if ml_acceleration == "openvino":
        ml_render = ui.ask(translate("Intel render device for recognition"), "/dev/dri/renderD128")
        if not re.fullmatch(r"/dev/dri/renderD[0-9]+", ml_render):
            raise InstallError(translate("Invalid Intel render path"))
    if ml_acceleration != "cpu":
        ui.message(translate("GPU recognition uses 8 GB of RAM and a limit of 4 CPU equivalents. These resources "
                             "were tested in the lab and are not a universal minimum. Compatibility depends on the "
                             "GPU, the models and the kernel. NVIDIA uses the GPUs of the Toolkit inventory; Intel "
                             "keeps the CPU topology."))
    return {
        "deployment_kind": "immich-four-lxc-stack",
        "base_vmid": int(vmid_text) if vmid_text else None,
        "stack_name": stack_name,
        "template_storage": template_storage,
        "rootfs_storage": rootfs_storage,
        "database_storage": database_storage,
        "database_size_gb": database_size,
        "media": {
            "mode": media_mode,
            "storage": media_storage,
            "size_gb": media_size,
            "host_path": media_root,
            "backup": media_mode == "managed-volume",
        },
        "timezone": timezone,
        "onboot": ui.confirm(translate("Start the stack with Proxmox"), pve_defaults["onboot"]),
        "start_after_create": ui.confirm(translate("Start when finished"), True),
        "network": {
            "frontend_bridge": frontend_bridge,
            "frontend_ipv4": server_ipv4,
            "machine_learning_frontend_ipv4": ml_ipv4,
            "frontend_gateway": frontend_gateway,
            "private_allocation": "automatic",
            "private_bridge": defaults["private_network"]["bridge"],
            "private_subnet": defaults["private_network"]["subnet"],
            "private_host_address": defaults["private_network"]["host_address"],
            "server_address": defaults["private_network"]["server_address"],
            "machine_learning_address": defaults["private_network"]["machine_learning_address"],
            "database_address": defaults["private_network"]["database_address"],
            "valkey_address": defaults["private_network"]["valkey_address"],
        },
        "video_transcoding": {
            "acceleration": video_acceleration,
            "render_device": render_device,
            "driver": vaapi_driver,
        },
        "machine_learning": {"acceleration": ml_acceleration, "render_device": ml_render,
                             "model_cache_size_gb": 8,
                             "resources": {"cores": 2 if ml_acceleration == "cpu" else 4,
                                           "memory_mb": 2048 if ml_acceleration == "cpu" else 8192,
                                           "swap_mb": 1024,
                                           "cpu_allocation": "quota" if ml_acceleration == "openvino" else "cpuset"}},
    }


def _build_nextcloud_stack_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI,
) -> dict[str, Any]:
    defaults = template["proxmox"]["laboratory_contract"]["defaults"]
    pve_defaults = template["proxmox"]["defaults"]
    vmid_text = ui.ask(
        translate("Base VMID of Nextcloud (empty = next free block)"), "", required=False
    )
    stack_name = ui.ask(translate("Stack name"), defaults["stack_name"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", stack_name):
        raise InstallError(translate("The stack name only accepts lowercase letters, numbers and hyphens"))

    rootfs_storage = ask_storage(ui, translate("Storage for rootfs"), "rootdir", defaults["rootfs_storage"])
    template_storage = ask_storage(ui, translate("Storage for the OCI image cache"), "vztmpl", pve_defaults["template_storage"])
    application_mode = ui.choose(
        translate("Storage for Nextcloud files, configuration and data"),
        [
            ("managed-volume", translate("Dedicated container volume (included in backups)")),
            ("host-bind", translate("Shared host directory (not included in Proxmox backups)")),
        ],
        "managed-volume",
    )
    if application_mode is None:
        raise UserCancelled(translate("Nextcloud configuration cancelled"))
    if application_mode == "managed-volume":
        application_storage = ask_storage(ui, translate("Storage for the Nextcloud data"), "rootdir", defaults["application_storage"])
        application_size = int(
            ui.ask(
                translate("Nextcloud volume size in GB"),
                str(defaults["application_volume_size_gb"]),
            )
        )
        if application_size < 8:
            raise InstallError(translate("The Nextcloud volume needs at least 8 GB"))
        application_root = None
    else:
        shared_default = defaults["shared_application_root"].replace(
            "${stack_name}", stack_name
        )
        application_root = ui.ask(translate("Shared host directory"), shared_default)
        application_storage = None
        application_size = None

    database_storage = ask_storage(ui, translate("Local storage for PostgreSQL"), "rootdir", defaults["database_storage"])
    database_size = int(
        ui.ask(
            translate("PostgreSQL volume size in GB"),
            str(defaults["database_volume_size_gb"]),
        )
    )
    if database_size < 8:
        raise InstallError(translate("The PostgreSQL volume needs at least 8 GB"))

    frontend_bridge = ask_bridge(ui, translate("Access bridge for Nextcloud"), defaults["frontend_network"]["bridge"])
    addresses, frontend_gateway = access.ask_addresses(ui, frontend_bridge, [""])
    timezone = ui.ask(translate("Timezone"), host.timezone())
    admin_username = ui.ask(
        translate("Initial administrator user"), defaults["application"]["admin_username"]
    )
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", admin_username):
        raise InstallError(translate("The administrator user contains characters that are not allowed"))

    private = defaults["private_network"]
    return {
        "deployment_kind": "nextcloud-three-lxc-stack",
        "base_vmid": int(vmid_text) if vmid_text else None,
        "stack_name": stack_name,
        "template_storage": template_storage,
        "rootfs_storage": rootfs_storage,
        "application": {
            "mode": application_mode,
            "storage": application_storage,
            "size_gb": application_size,
            "host_path": application_root,
            "backup": application_mode == "managed-volume",
            "admin_username": admin_username,
            "php_memory_limit": defaults["application"]["php_memory_limit"],
            "php_upload_limit": defaults["application"]["php_upload_limit"],
            "apache_body_limit": defaults["application"]["apache_body_limit"],
        },
        "database_storage": database_storage,
        "database_size_gb": database_size,
        "timezone": timezone,
        "maintenance_window_start_utc": defaults["maintenance_window_start_utc"],
        "default_phone_region": defaults["default_phone_region"],
        "onboot": ui.confirm(translate("Start the stack with Proxmox"), pve_defaults["onboot"]),
        "start_after_create": ui.confirm(translate("Start when finished"), True),
        "network": {
            "frontend_bridge": frontend_bridge,
            "frontend_ipv4": addresses[""],
            "frontend_gateway": frontend_gateway,
            "private_allocation": "automatic",
            "private_bridge": private["bridge"],
            "private_subnet": private["subnet"],
            "private_host_address": private["host_address"],
            "application_address": private["application_address"],
            "database_address": private["database_address"],
            "cache_address": private["cache_address"],
        },
    }


def _build_paperless_stack_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI,
) -> dict[str, Any]:
    defaults = template["proxmox"]["laboratory_contract"]["defaults"]
    pve_defaults = template["proxmox"]["defaults"]
    vmid_text = ui.ask(
        translate("Base VMID of Paperless (empty = next free block)"), "", required=False
    )
    stack_name = ui.ask(translate("Stack name"), defaults["stack_name"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", stack_name):
        raise InstallError(translate("The stack name only accepts lowercase letters, numbers and hyphens"))

    rootfs_storage = ask_storage(ui, translate("Storage for rootfs"), "rootdir", defaults["rootfs_storage"])
    application_storage = ask_storage(ui, translate("Storage for Paperless data and documents"), "rootdir", defaults["application_storage"])
    database_storage = ask_storage(ui, translate("Local storage for PostgreSQL"), "rootdir", defaults["database_storage"])
    template_storage = ask_storage(ui, translate("Storage for the OCI image cache"), "vztmpl", pve_defaults["template_storage"])

    data_size = int(
        ui.ask(translate("Data volume size in GB"), str(defaults["data_volume_size_gb"]))
    )
    media_size = int(
        ui.ask(
            translate("Documents volume size in GB"),
            str(defaults["media_volume_size_gb"]),
        )
    )
    database_size = int(
        ui.ask(
            translate("PostgreSQL volume size in GB"),
            str(defaults["database_volume_size_gb"]),
        )
    )
    if min(data_size, database_size) < 8 or media_size < 8:
        raise InstallError(translate("The Paperless persistent volumes need at least 8 GB"))

    transfer_mode = ui.choose(
        translate("Storage for the consume and export folders"),
        [
            ("host-bind", translate("Shared host directories (not included in Proxmox backups)")),
            ("managed-volume", translate("Dedicated container volumes (included in backups)")),
        ],
        "host-bind",
    )
    if transfer_mode is None:
        raise UserCancelled(translate("Paperless configuration cancelled"))
    transfer_size = None
    transfer_root = None
    if transfer_mode == "managed-volume":
        transfer_size = int(
            ui.ask(
                translate("Size of each consume/export volume in GB"),
                str(defaults["transfer_volume_size_gb"]),
            )
        )
        if transfer_size < 1:
            raise InstallError(translate("The consume/export volumes need at least 1 GB"))
    else:
        transfer_default = defaults["shared_transfer_root"].replace(
            "${stack_name}", stack_name
        )
        transfer_root = ui.ask(
            translate("Shared directory for consume and export"), transfer_default
        )

    frontend_bridge = ask_bridge(ui, translate("Access bridge for Paperless"), defaults["frontend_network"]["bridge"])
    addresses, frontend_gateway = access.ask_addresses(ui, frontend_bridge, [""])
    timezone = ui.ask(translate("Timezone"), host.timezone())
    ocr_language = ui.ask(translate("OCR language (Tesseract code)"), defaults["ocr_language"])
    if not re.fullmatch(r"[a-z]{3}(?:\+[a-z]{3})*", ocr_language):
        raise InstallError(translate("The OCR language must use Tesseract codes, for example eng or eng+spa"))
    admin_username = ui.ask(
        translate("Initial administrator user"), defaults["application"]["admin_username"]
    )
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", admin_username):
        raise InstallError(translate("The administrator user contains characters that are not allowed"))

    private = defaults["private_network"]
    return {
        "deployment_kind": "paperless-three-lxc-stack",
        "base_vmid": int(vmid_text) if vmid_text else None,
        "stack_name": stack_name,
        "template_storage": template_storage,
        "rootfs_storage": rootfs_storage,
        "application_storage": application_storage,
        "data_size_gb": data_size,
        "media_size_gb": media_size,
        "database_storage": database_storage,
        "database_size_gb": database_size,
        "broker_size_gb": defaults["broker_volume_size_gb"],
        "transfer": {
            "mode": transfer_mode,
            "storage": application_storage if transfer_mode == "managed-volume" else None,
            "size_gb": transfer_size,
            "host_path": transfer_root,
            "backup": transfer_mode == "managed-volume",
        },
        "application": {
            "admin_username": admin_username,
            "ocr_language": ocr_language,
        },
        "timezone": timezone,
        "onboot": ui.confirm(translate("Start the stack with Proxmox"), pve_defaults["onboot"]),
        "start_after_create": ui.confirm(translate("Start when finished"), True),
        "network": {
            "frontend_bridge": frontend_bridge,
            "frontend_ipv4": addresses[""],
            "frontend_gateway": frontend_gateway,
            "private_allocation": "automatic",
            "private_bridge": private["bridge"],
            "private_subnet": private["subnet"],
            "private_host_address": private["host_address"],
            "application_address": private["application_address"],
            "database_address": private["database_address"],
            "broker_address": private["broker_address"],
        },
    }


def _build_tandoor_stack_deployment(
    template: dict[str, Any],
    ui: TerminalUI | DialogUI,
) -> dict[str, Any]:
    defaults = template["proxmox"]["laboratory_contract"]["defaults"]
    pve_defaults = template["proxmox"]["defaults"]
    vmid_text = ui.ask(
        translate("Base VMID of Tandoor (empty = next free block)"), "", required=False
    )
    stack_name = ui.ask(translate("Stack name"), defaults["stack_name"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", stack_name):
        raise InstallError(translate("The stack name only accepts lowercase letters, numbers and hyphens"))

    rootfs_storage = ask_storage(ui, translate("Storage for rootfs"), "rootdir", defaults["rootfs_storage"])
    database_storage = ask_storage(ui, translate("Local storage for PostgreSQL"), "rootdir", defaults["database_storage"])
    template_storage = ask_storage(ui, translate("Storage for the OCI image cache"), "vztmpl", pve_defaults["template_storage"])

    media_mode = ui.choose(
        translate("Storage for recipe images and files"),
        [
            ("managed-volume", translate("Dedicated container volume (included in backups)")),
            ("host-bind", translate("Shared host directory (not included in Proxmox backups)")),
        ],
        "managed-volume",
    )
    if media_mode is None:
        raise UserCancelled(translate("Tandoor configuration cancelled"))
    if media_mode == "managed-volume":
        media_storage = ask_storage(ui, translate("Storage for Tandoor files"), "rootdir", defaults["application_storage"])
        media_size = int(
            ui.ask(
                translate("Files volume size in GB"),
                str(defaults["media_volume_size_gb"]),
            )
        )
        if media_size < 2:
            raise InstallError(translate("The Tandoor files volume needs at least 2 GB"))
        media_root = None
    else:
        media_default = defaults["shared_media_root"].replace(
            "${stack_name}", stack_name
        )
        media_root = ui.ask(translate("Shared host directory"), media_default)
        media_storage = None
        media_size = None

    static_size = int(
        ui.ask(
            translate("staticfiles volume size in GB"),
            str(defaults["static_volume_size_gb"]),
        )
    )
    database_size = int(
        ui.ask(
            translate("PostgreSQL volume size in GB"),
            str(defaults["database_volume_size_gb"]),
        )
    )
    if static_size < 1 or database_size < 4:
        raise InstallError(
            translate("Tandoor needs at least 1 GB for staticfiles and 4 GB for PostgreSQL")
        )

    frontend_bridge = ask_bridge(ui, translate("Access bridge for Tandoor"), defaults["frontend_network"]["bridge"])
    addresses, frontend_gateway = access.ask_addresses(ui, frontend_bridge, [""])
    timezone = ui.ask(translate("Timezone"), host.timezone())
    allowed_hosts = ui.ask(
        translate("Allowed hosts (comma separated; * allows access through the assigned IP)"),
        defaults["allowed_hosts"],
    )
    if any(character in allowed_hosts for character in "\r\n"):
        raise InstallError(translate("ALLOWED_HOSTS cannot contain line breaks"))
    admin_username = ui.ask(
        translate("Initial administrator user"), defaults["application"]["admin_username"]
    )
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", admin_username):
        raise InstallError(translate("The administrator user contains characters that are not allowed"))
    admin_email = ui.ask(
        translate("Administrator email"), defaults["application"]["admin_email"]
    )
    if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", admin_email):
        raise InstallError(translate("The administrator email is not valid"))

    start_after = ui.confirm(translate("Start when finished"), True)
    if not start_after:
        raise UserCancelled(
            translate("Tandoor needs to complete its first start to create the initial administrator")
        )

    private = defaults["private_network"]
    return {
        "deployment_kind": "tandoor-two-lxc-stack",
        "base_vmid": int(vmid_text) if vmid_text else None,
        "stack_name": stack_name,
        "template_storage": template_storage,
        "rootfs_storage": rootfs_storage,
        "application_storage": defaults["application_storage"],
        "static_size_gb": static_size,
        "database_storage": database_storage,
        "database_size_gb": database_size,
        "media": {
            "mode": media_mode,
            "storage": media_storage,
            "size_gb": media_size,
            "host_path": media_root,
            "backup": media_mode == "managed-volume",
        },
        "application": {
            "allowed_hosts": allowed_hosts,
            "admin_username": admin_username,
            "admin_email": admin_email,
        },
        "timezone": timezone,
        "onboot": ui.confirm(translate("Start the stack with Proxmox"), pve_defaults["onboot"]),
        "start_after_create": start_after,
        "network": {
            "frontend_bridge": frontend_bridge,
            "frontend_ipv4": addresses[""],
            "frontend_gateway": frontend_gateway,
            "private_allocation": "automatic",
            "private_bridge": private["bridge"],
            "private_subnet": private["subnet"],
            "private_host_address": private["host_address"],
            "application_address": private["application_address"],
            "database_address": private["database_address"],
        },
    }


def redacted(deployment: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(deployment))
    for item in payload.get("environment", []):
        if item.pop("sensitive", False):
            item["value"] = "********"
    for service in payload.get('services', []):
        if 'setup_credentials' in service:
            service['setup_credentials']['password'] = '********'
        if 'deployment' in service:
            service['deployment'] = redacted(service['deployment'])
        if 'template' in service:
            service['template'] = {'id':service['template'].get('id')}
    return payload


def run_remote_install(project_root, template_source, deployment, ssh_target, dry_run=False):
    from .gpu import apply_profile_image
    template = (copy.deepcopy(template_source) if isinstance(template_source, dict)
                else json.loads(template_source.read_text()))
    apply_profile_image(template, deployment.get('hardware_profile'))
    with tempfile.TemporaryDirectory() as directory:
        effective = Path(directory) / 'template.json'
        effective.write_text(json.dumps(template))
        return _run_remote_install(project_root, effective, deployment, ssh_target, dry_run)


def _run_remote_install(
    project_root: Path,
    template_path: Path,
    deployment: dict[str, Any],
    ssh_target: str,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    deployment_kind = deployment.get("deployment_kind")
    stack_installers = {
        "generic-multi-lxc-stack": "install_generic_stack.sh",
        "immich-four-lxc-stack": "install_immich_stack.sh",
        "nextcloud-three-lxc-stack": "install_nextcloud_stack.sh",
        "paperless-three-lxc-stack": "install_paperless_stack.sh",
        "tandoor-two-lxc-stack": "install_tandoor_stack.sh",
    }
    remote_script = project_root / "remote" / stack_installers.get(
        deployment_kind, "install_oci.sh"
    )
    archive_verifier = project_root / "remote" / "verify_oci_archive.py"
    runtime_resolver = project_root / "remote" / "oci_runtime.py"
    rootfs_unshifter = project_root / "remote" / "unshift_oci_rootfs.py"
    jellyfin_configurator = project_root / "remote" / "configure_jellyfin_encoding.py"
    private_network_allocator = project_root / "remote" / "allocate_private_network.py"
    stack_dependency_hook = project_root / "remote" / "stack_dependency_hook.sh"
    deployment_bytes = (json.dumps(deployment, ensure_ascii=True, indent=2) + "\n").encode()
    if ssh_target == "auto":
        if os.geteuid() != 0 or not shutil.which("pct"):
            raise InstallError(translate("The installation runs on the Proxmox node itself, as root"))
        ssh_target = "local"
    if ssh_target == "local":
        with tempfile.TemporaryDirectory(prefix="proxmenux-oci-") as directory:
            temporary = Path(directory)
            script_copy = temporary / remote_script.name
            verifier_copy = temporary / "verify_oci_archive.py"
            resolver_copy = temporary / "oci_runtime.py"
            unshifter_copy = temporary / "unshift_oci_rootfs.py"
            jellyfin_configurator_copy = temporary / "configure_jellyfin_encoding.py"
            private_network_allocator_copy = temporary / "allocate_private_network.py"
            stack_dependency_hook_copy = temporary / "stack_dependency_hook.sh"
            template_copy = temporary / "template.json"
            deployment_copy = temporary / "deployment.json"
            shutil.copy2(remote_script, script_copy)
            shutil.copy2(archive_verifier, verifier_copy)
            shutil.copy2(runtime_resolver, resolver_copy)
            shutil.copy2(rootfs_unshifter, unshifter_copy)
            shutil.copy2(jellyfin_configurator, jellyfin_configurator_copy)
            shutil.copy2(private_network_allocator, private_network_allocator_copy)
            shutil.copy2(stack_dependency_hook, stack_dependency_hook_copy)
            shutil.copy2(project_root / 'remote' / 'haos_healthcheck.py', temporary / 'haos_healthcheck.py')
            shutil.copy2(project_root / 'remote' / 'oci_installation_state.py', temporary / 'oci_installation_state.py')
            shutil.copy2(project_root / 'remote' / 'oci_instances.py', temporary / 'oci_instances.py')
            for helper in ('oci_ui.sh', 'oci_ui.py', 'oci_native_stack.py', 'oci_native_stack.sh', 'oci_instance_transaction.py', 'oci_host_mounts.py', 'oci_runtime_settings.py', 'oci_gpu_devices.py', 'oci_accelerators.py', 'oci_nvidia_runtime.py', 'oci_nvidia_refresh.py', 'oci_nvidia_dynamic.py', 'oci_update_current.py', 'oci_stack_replay.py', 'oci_stack_plan.py', 'oci_stack_transaction.py', 'oci_stack_native.py', 'oci_image_cache.py', 'nvidia_lxc_mount_lab.sh', 'oci_nvidia_setup.sh', 'oci_immich_ml.sh'):
                shutil.copy2(project_root / 'remote' / helper, temporary / helper)
            if deployment_kind == 'generic-multi-lxc-stack':
                shutil.copy2(project_root / 'remote' / 'install_generic_stack.py', temporary / 'install_generic_stack.py')
                shutil.copy2(project_root / 'remote' / 'install_oci.sh', temporary / 'install_oci.sh')
            shutil.copy2(template_path, template_copy)
            deployment_copy.write_bytes(deployment_bytes)
            deployment_copy.chmod(0o600)
            result = _stream_process(
                [
                    "bash",
                    str(script_copy),
                    str(template_copy),
                    str(deployment_copy),
                    "1" if dry_run else "0",
                ]
            )
            if result is not None and not dry_run:
                subprocess.run([sys.executable, str(temporary / "oci_image_cache.py")],
                               capture_output=True, check=False)
            return result

    with io.BytesIO() as buffer:
        with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
            archive.add(remote_script, arcname=remote_script.name)
            archive.add(archive_verifier, arcname="verify_oci_archive.py")
            archive.add(runtime_resolver, arcname="oci_runtime.py")
            archive.add(rootfs_unshifter, arcname="unshift_oci_rootfs.py")
            archive.add(
                jellyfin_configurator,
                arcname="configure_jellyfin_encoding.py",
            )
            archive.add(private_network_allocator, arcname="allocate_private_network.py")
            archive.add(stack_dependency_hook, arcname="stack_dependency_hook.sh")
            archive.add(project_root / 'remote' / 'haos_healthcheck.py', arcname='haos_healthcheck.py')
            archive.add(project_root / 'remote' / 'oci_installation_state.py', arcname='oci_installation_state.py')
            archive.add(project_root / 'remote' / 'oci_instances.py', arcname='oci_instances.py')
            for helper in ('oci_ui.sh', 'oci_ui.py', 'oci_native_stack.py', 'oci_native_stack.sh', 'oci_instance_transaction.py', 'oci_host_mounts.py', 'oci_runtime_settings.py', 'oci_gpu_devices.py', 'oci_accelerators.py', 'oci_nvidia_runtime.py', 'oci_nvidia_refresh.py', 'oci_nvidia_dynamic.py', 'oci_update_current.py', 'oci_stack_replay.py', 'oci_stack_plan.py', 'oci_stack_transaction.py', 'oci_stack_native.py', 'oci_image_cache.py', 'nvidia_lxc_mount_lab.sh', 'oci_nvidia_setup.sh', 'oci_immich_ml.sh'):
                archive.add(project_root / 'remote' / helper, arcname=helper)
            if deployment_kind == 'generic-multi-lxc-stack':
                archive.add(project_root / 'remote' / 'install_generic_stack.py', arcname='install_generic_stack.py')
                archive.add(project_root / 'remote' / 'install_oci.sh', arcname='install_oci.sh')
            archive.add(template_path, arcname="template.json")
            info = tarfile.TarInfo("deployment.json")
            info.size = len(deployment_bytes)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(deployment_bytes))
        archive_bytes = buffer.getvalue()

    command = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        ssh_target,
        "tmp=$(mktemp -d /tmp/proxmenux-oci.XXXXXX); trap 'rm -rf \"$tmp\"' EXIT; "
        f"tar -xzf - -C \"$tmp\"; bash \"$tmp/{remote_script.name}\" \"$tmp/template.json\" "
        f"\"$tmp/deployment.json\" {'1' if dry_run else '0'}; status=$?; "
        + ("" if dry_run else "[ $status -ne 0 ] || python3 \"$tmp/oci_image_cache.py\" >/dev/null 2>&1; ")
        + "exit $status",
    ]
    return _stream_process(command, archive_bytes)


def run_remote_rclone_mount(project_root, template_source, deployment, ssh_target, dry_run=False):
    if not isinstance(template_source, dict):
        return _run_remote_rclone_mount(project_root, template_source, deployment, ssh_target, dry_run)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'template.json'
        path.write_text(json.dumps(template_source))
        return _run_remote_rclone_mount(project_root, path, deployment, ssh_target, dry_run)


def _run_remote_rclone_mount(
    project_root: Path,
    template_path: Path,
    deployment: dict[str, Any],
    ssh_target: str,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    remote_script = project_root / "remote" / "configure_rclone_mount.sh"
    publisher = project_root / "remote" / "rclone_mount_publish.py"
    deployment_bytes = (json.dumps(deployment, ensure_ascii=True, indent=2) + "\n").encode()
    if ssh_target == "auto":
        if os.geteuid() != 0 or not shutil.which("pct"):
            raise InstallError(translate("The installation runs on the Proxmox node itself, as root"))
        ssh_target = "local"
    if ssh_target == "local":
        with tempfile.TemporaryDirectory(prefix="proxmenux-rclone-") as directory:
            temporary = Path(directory)
            script_copy = temporary / remote_script.name
            publisher_copy = temporary / publisher.name
            template_copy = temporary / "template.json"
            deployment_copy = temporary / "deployment.json"
            shutil.copy2(remote_script, script_copy)
            shutil.copy2(publisher, publisher_copy)
            for helper in ('oci_ui.sh', 'oci_ui.py'):
                shutil.copy2(project_root / 'remote' / helper, temporary / helper)
            shutil.copy2(template_path, template_copy)
            deployment_copy.write_bytes(deployment_bytes)
            deployment_copy.chmod(0o600)
            return _stream_process(
                [
                    "bash",
                    str(script_copy),
                    str(template_copy),
                    str(deployment_copy),
                    "1" if dry_run else "0",
                ]
            )

    with io.BytesIO() as buffer:
        with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
            archive.add(remote_script, arcname=remote_script.name)
            archive.add(publisher, arcname=publisher.name)
            for helper in ('oci_ui.sh', 'oci_ui.py'):
                archive.add(project_root / 'remote' / helper, arcname=helper)
            archive.add(template_path, arcname="template.json")
            info = tarfile.TarInfo("deployment.json")
            info.size = len(deployment_bytes)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(deployment_bytes))
        archive_bytes = buffer.getvalue()
    command = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        ssh_target,
        "tmp=$(mktemp -d /tmp/proxmenux-rclone.XXXXXX); trap 'rm -rf \"$tmp\"' EXIT; "
        f"tar -xzf - -C \"$tmp\"; bash \"$tmp/{remote_script.name}\" "
        f"\"$tmp/template.json\" \"$tmp/deployment.json\" {'1' if dry_run else '0'}",
    ]
    return _stream_process(command, archive_bytes)


def _stream_process(command: list[str], standard_input: bytes | None = None) -> dict[str, Any] | None:
    environment = os.environ.copy()
    environment["OCI_SPINNER"] = "1" if sys.stdout.isatty() else "0"
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if standard_input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        env=environment,
    )
    if standard_input is not None:
        assert process.stdin is not None
        process.stdin.write(standard_input)
        process.stdin.close()
    result: dict[str, Any] | None = None
    assert process.stdout is not None
    pending = b""
    binary_output = getattr(sys.stdout, "buffer", None)

    def emit(data: bytes) -> None:
        if binary_output is not None:
            binary_output.write(data)
            binary_output.flush()
        else:
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()

    while True:
        chunk = os.read(process.stdout.fileno(), 1024)
        if not chunk:
            break
        pending += chunk
        while True:
            newline = pending.find(b"\n")
            carriage = pending.find(b"\r")
            separators = [position for position in (newline, carriage) if position >= 0]
            if not separators:
                break
            position = min(separators)
            raw_line = pending[:position]
            if pending[position : position + 2] == b"\r\n":
                separator = b"\n"
                pending = pending[position + 2 :]
            else:
                separator = pending[position : position + 1]
                pending = pending[position + 1 :]
            if raw_line.startswith(b"PROXMENUX_RESULT="):
                encoded = raw_line.split(b"=", 1)[1]
                result = json.loads(base64.b64decode(encoded).decode("utf-8"))
            else:
                emit(raw_line + separator)
    if pending:
        if pending.startswith(b"PROXMENUX_RESULT="):
            encoded = pending.split(b"=", 1)[1]
            result = json.loads(base64.b64decode(encoded).decode("utf-8"))
        else:
            emit(pending)
    process.stdout.close()
    return_code = process.wait()
    if return_code != 0:
        raise InstallError(f"{translate('The installation ended with exit code')} {return_code}")
    return result

def configure_acceleration(installer_profile, environment, unprivileged, ui, mode=ADVANCED_MODE):
    advanced = mode != DEFAULT_MODE
    devices: list[dict[str, Any]] = []
    selected_hardware_profile: str | None = None
    selected_profile: dict[str, Any] | None = None
    profile_device_requests: list[dict[str, Any]] = []
    post_start_configurations: list[dict[str, Any]] = []
    hardware = installer_profile.get("hardware_acceleration")
    if hardware:
        profiles = hardware.get("profiles", [])
        options = [(item["id"], item["label"]) for item in profiles]
        selected_hardware_profile = ui.choose(
            translate(hardware.get("prompt", "Hardware acceleration")),
            [(tag, translate(label)) for tag, label in options],
            hardware.get("default", profiles[0]["id"] if profiles else None),
        )
        if selected_hardware_profile is None:
            raise UserCancelled(translate("Acceleration configuration cancelled"))
        selected_profile = next(
            (item for item in profiles if item["id"] == selected_hardware_profile),
            None,
        )
        if selected_profile is None:
            raise InstallError(translate("Invalid acceleration profile"))
        profile_device_requests = [
            {**item, "selected_by_hardware_profile": True}
            for item in selected_profile.get("device_requests", [])
        ]
        for env_item in selected_profile.get("environment", []):
            environment = [
                entry for entry in environment if entry["name"] != env_item["name"]
            ]
            environment.append(
                {
                    "name": env_item["name"],
                    "value": str(env_item["value"]),
                    "sensitive": bool(env_item.get("sensitive", False)),
                }
            )
        for configuration in selected_profile.get("post_start_configurations", []):
            prompt = (translate(configuration["enable_prompt"]) if configuration.get("enable_prompt")
                      else f"{translate('Apply configuration')} {configuration['id']}")
            enabled = (ui.confirm(prompt, configuration.get("enabled_default", True)) if advanced
                       else configuration.get("enabled_default", True))
            if enabled:
                post_start_configurations.append(copy.deepcopy(configuration))

    device_requests = [
        *installer_profile.get("optional_devices", []),
        *installer_profile.get("device_requests", []),
        *profile_device_requests,
    ]
    for item in device_requests:
        enabled = item.get("selected_by_hardware_profile", False) or (
            ui.confirm(translate(item["enable_prompt"]), item.get("enabled_default", False)) if advanced
            else item.get("enabled_default", False) or item.get("required_for_runtime", False))
        if not enabled:
            if item.get("required_for_runtime"):
                raise UserCancelled(f"{translate('This variant requires the device')} {item['id']}")
            continue
        kind = item.get("kind", "character-device")
        if kind == "nvidia-runtime":
            device = {
                "id": item["id"],
                "kind": kind,
                "device_selection": item.get("device_selection", "all-requested-by-compose"),
                "runtime_mode": "dynamic" if unprivileged else "static",
            }
            if not unprivileged:
                ui.message(translate("Dynamic NVIDIA is only validated for unprivileged containers. This profile "
                                     "uses static mounts and must be recreated after the host driver changes."))
            if item.get("append_host_device_gid_to_environment"):
                device["append_host_device_gid_to_environment"] = item[
                    "append_host_device_gid_to_environment"
                ]
            devices.append(device)
        else:
            host_path = (ui.ask(translate(item["path_prompt"]), item["host_path_default"]) if advanced
                         else item["host_path_default"])
            container_path = (
                host_path
                if item.get("container_path_strategy") == "same-as-host"
                else item.get("container_path", host_path)
            )
            device = {
                "id": item["id"],
                "kind": kind,
                "host_path": host_path,
                "container_path": container_path,
                "mode": item.get("mode", "0660"),
                "deny_write": item.get("deny_write", False),
                "gid_strategy": item.get("gid_strategy", "host-device-gid"),
            }
            if item.get("append_host_device_gid_to_environment"):
                device["append_host_device_gid_to_environment"] = item[
                    "append_host_device_gid_to_environment"
                ]
            if item.get("drm_vendor_ids"):
                device["drm_vendor_ids"] = item["drm_vendor_ids"]
            if item.get("uid_from_environment"):
                name = item["uid_from_environment"]
                uid = next((entry["value"] for entry in environment if entry["name"] == name), "")
                if not re.fullmatch(r"[0-9]+", str(uid)) or int(uid) >= 4294967295:
                    raise InstallError(f"{name}: {translate('must contain a valid numeric UID for the GPU')}")
                device["uid"] = int(uid)
            devices.append(device)
        for env_item in item.get("environment", []):
            selected = (ui.choose(translate(env_item["prompt"]),
                                  [(value, value) for value in env_item["choices"]],
                                  env_item.get("default")) if advanced else env_item.get("default"))
            if selected is None:
                raise UserCancelled(translate("Device configuration cancelled"))
            if selected in env_item.get("omit_values", []):
                continue
            environment = [entry for entry in environment if entry["name"] != env_item["name"]]
            environment.append(
                {"name": env_item["name"], "value": selected, "sensitive": False}
            )

    device_paths = {
        item["id"]: item.get("container_path")
        for item in devices
        if item.get("container_path")
    }
    # LSIO's native permission init needs explicit paths for PVE devN mounts:
    # recursive find -type c can see the regular-file mountpoint d_type instead.
    for name, identifiers in (selected_profile or {}).get("environment_from_devices", {}).items():
        paths = [device_paths.get(identifier) for identifier in identifiers]
        if not paths or any(
            not path or not re.fullmatch(r"/dev/[A-Za-z0-9_/.-]+", path)
            or ".." in path.split("/") for path in paths
        ):
            raise InstallError(f"{translate('Invalid device paths for')} {name}")
        environment = [entry for entry in environment if entry["name"] != name]
        environment.append({"name": name, "value": " ".join(paths), "sensitive": False})
    for configuration in post_start_configurations:
        for setting, value in list(configuration.get("settings", {}).items()):
            if not isinstance(value, dict) or "device_path_from" not in value:
                continue
            device_id = value["device_path_from"]
            device_path = device_paths.get(device_id)
            if not device_path:
                raise InstallError(
                    f"{configuration['id']}: {translate('this configuration needs the device')} {device_id}"
                )
            configuration["settings"][setting] = device_path

    return devices, selected_hardware_profile, post_start_configurations, environment
