from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

import yaml

from .github_source import Repository


SUPPORTED_SERVICE_KEYS = {
    "cap_add",
    "command",
    "container_name",
    "cpu_shares",
    "devices",
    "entrypoint",
    "environment",
    "extra_hosts",
    "group_add",
    "healthcheck",
    "hostname",
    "image",
    "init",
    "ipc",
    "labels",
    "logging",
    "mac_address",
    "mem_limit",
    "networks",
    "network_mode",
    "ports",
    "privileged",
    "restart",
    "runtime",
    "security_opt",
    "shm_size",
    "stdin_open",
    "stop_grace_period",
    "sysctls",
    "tty",
    "ulimits",
    "user",
    "volumes",
    "working_dir",
}

LINUX_CAPABILITIES = {
    "AUDIT_CONTROL", "AUDIT_READ", "AUDIT_WRITE", "BLOCK_SUSPEND", "BPF",
    "CHECKPOINT_RESTORE", "CHOWN", "DAC_OVERRIDE", "DAC_READ_SEARCH", "FOWNER",
    "FSETID", "IPC_LOCK", "IPC_OWNER", "KILL", "LEASE", "LINUX_IMMUTABLE",
    "MAC_ADMIN", "MAC_OVERRIDE", "MKNOD", "NET_ADMIN", "NET_BIND_SERVICE",
    "NET_BROADCAST", "NET_RAW", "PERFMON", "SETFCAP", "SETGID", "SETPCAP",
    "SETUID", "SYS_ADMIN", "SYS_BOOT", "SYS_CHROOT", "SYS_MODULE", "SYS_NICE",
    "SYS_PACCT", "SYS_PTRACE", "SYS_RAWIO", "SYS_RESOURCE", "SYS_TIME",
    "SYS_TTY_CONFIG", "SYSLOG", "WAKE_ALARM",
}

SENSITIVE_NAME = re.compile(
    r"(?:PASS|PASSWORD|TOKEN|SECRET|API_?KEY|PRIVATE_KEY|CREDENTIAL|(?:^|_)KEY(?:$|_))",
    re.I,
)


class ConversionError(RuntimeError):
    pass


def extract_compose(readme: str) -> str:
    lines = readme.splitlines()
    heading_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^#{2,5}\s+docker-compose\b", line.strip(), flags=re.I)
        ),
        None,
    )
    if heading_index is None:
        raise ConversionError("El README no contiene una seccion docker-compose reconocible")

    fence_start = next(
        (index for index in range(heading_index + 1, len(lines)) if lines[index].strip().startswith("```")),
        None,
    )
    if fence_start is None:
        raise ConversionError("La seccion docker-compose no contiene un bloque de codigo")
    fence_end = next(
        (index for index in range(fence_start + 1, len(lines)) if lines[index].strip() == "```"),
        None,
    )
    if fence_end is None:
        raise ConversionError("El bloque docker-compose no esta cerrado")

    compose = "\n".join(lines[fence_start + 1 : fence_end]).strip() + "\n"
    if "services:" not in compose:
        raise ConversionError("El bloque encontrado no parece un Docker Compose")
    return compose


def _optional_markers(compose: str) -> dict[str, set[str]]:
    markers: dict[str, set[str]] = {
        key: set()
        for key in ("environment", "volumes", "ports", "devices", "security_opt")
    }
    active: str | None = None
    active_indent = -1
    for line in compose.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        section_match = re.match(
            r"^(environment|volumes|ports|devices|security_opt):\s*$", stripped
        )
        if section_match:
            active = section_match.group(1)
            active_indent = indent
            continue
        if active and stripped and indent <= active_indent:
            active = None
        if active and "optional" in stripped.casefold() and "#" in stripped:
            value = stripped.split("#", 1)[0].strip().removeprefix("- ").strip("'\"")
            markers[active].add(value)
            if active == "environment" and "=" in value:
                markers[active].add(value.split("=", 1)[0])
    return markers


def _environment_contract(value: Any, optional: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if value is None:
        return result
    entries: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, list):
        for item in value:
            text = str(item)
            name, separator, raw_value = text.partition("=")
            entries.append((name, raw_value if separator else None))
    else:
        raise ConversionError("environment debe ser una lista o un objeto")

    for name, raw_value in entries:
        name = str(name)
        result.append(
            {
                "name": name,
                "example": None if raw_value is None else str(raw_value),
                "required": name not in optional,
                "sensitive": bool(SENSITIVE_NAME.search(name)),
                "source": "linuxserver-compose",
            }
        )
    return result


def _environment_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(name) for name in value}
    if isinstance(value, list):
        return {str(item).partition("=")[0] for item in value}
    return set()


def _split_short_mount(value: str) -> tuple[str | None, str, str | None]:
    parts = value.split(":")
    if len(parts) == 1:
        return None, parts[0], None
    if len(parts) == 2:
        return parts[0], parts[1], None
    return ":".join(parts[:-2]), parts[-2], parts[-1]


def _mount_contract(value: Any, optional: set[str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConversionError("volumes debe ser una lista")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            source = item.get("source")
            target = item.get("target")
            read_only = bool(item.get("read_only", False))
            raw = str(target or "")
        else:
            raw = str(item)
            source, target, mode = _split_short_mount(raw)
            read_only = mode == "ro"
        if not target or not str(target).startswith("/"):
            raise ConversionError(f"Ruta de volumen no valida: {item!r}")
        target = str(target)
        runtime_socket = target in {"/var/run/docker.sock", "/run/docker.sock"}
        source_text = str(source or "")
        system_files = {
            "/etc/group", "/etc/hosts", "/etc/localtime", "/etc/os-release",
            "/etc/passwd", "/etc/resolv.conf", "/etc/timezone", "/lib/modules",
        }
        system_prefixes = ("/dev/", "/proc/", "/sys/", "/run/", "/var/run/")
        system_bind = (
            target in system_files
            or source_text in system_files
            or target.startswith(system_prefixes)
            or source_text.startswith(system_prefixes)
        )
        is_optional = runtime_socket or raw in optional or any(
            marker.endswith(f":{target}") for marker in optional
        )
        private_default = target == "/config" or not is_optional
        choices = (
            ["host-bind", "skip"]
            if runtime_socket or (system_bind and is_optional)
            else ["host-bind"]
            if system_bind
            else ["managed-volume", "host-bind"] + (["skip"] if is_optional else [])
        )
        result.append(
            {
                "id": f"volume-{index}",
                "container_path": target,
                "compose_source_example": None if source is None else str(source),
                "read_only": read_only,
                "required": not is_optional,
                "installation_choice": choices,
                "default": (
                    "host-bind"
                    if system_bind and not is_optional
                    else "managed-volume"
                    if private_default
                    else "skip"
                ),
                "managed_volume": {
                    "backup": target not in {"/cache", "/tmp", "/transcode"},
                    "default_size_gb": 4 if target == "/config" else 8,
                },
            }
        )
    return result


def _port_contract(value: Any, optional: set[str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConversionError("ports debe ser una lista")
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            container = item.get("target")
            published = item.get("published")
            protocol = item.get("protocol", "tcp")
            raw = str(container)
        else:
            raw = str(item)
            port_text, slash, protocol = raw.rpartition("/")
            if not slash:
                port_text, protocol = raw, "tcp"
            parts = port_text.split(":")
            container = parts[-1]
            published = parts[-2] if len(parts) > 1 else None
        def port_span(raw_port: Any) -> tuple[int, int | None]:
            text = str(raw_port)
            if "-" in text:
                start_text, end_text = text.split("-", 1)
                start, end = int(start_text), int(end_text)
                if end < start:
                    raise ValueError
                return start, end
            return int(text), None

        try:
            container_port, container_port_end = port_span(container)
            if published is None:
                published_port, published_port_end = None, None
            else:
                published_port, published_port_end = port_span(published)
        except ValueError as exc:
            raise ConversionError(f"Puerto no valido: {item!r}") from exc
        contract = {
            "container_port": container_port,
            "published_example": published_port,
            "protocol": str(protocol),
            "required": raw not in optional,
            "proxmox_behavior": "listener-on-dedicated-lxc-address-no-nat",
        }
        if container_port_end is not None:
            contract["container_port_end"] = container_port_end
        if published_port_end is not None:
            contract["published_example_end"] = published_port_end
        result.append(contract)
    return result


def _image_contract(image: str) -> dict[str, Any]:
    digest = None
    without_digest = image
    if "@" in image:
        without_digest, digest = image.rsplit("@", 1)
    slash_index = without_digest.rfind("/")
    colon_index = without_digest.rfind(":")
    if colon_index > slash_index:
        repository, tag = without_digest[:colon_index], without_digest[colon_index + 1 :]
        reference = image
    else:
        repository, tag = without_digest, "latest"
        reference = f"{repository}:latest" if digest is None else image
    registry = repository.split("/", 1)[0] if "." in repository.split("/", 1)[0] else "docker.io"
    return {
        "reference": reference,
        "registry": registry,
        "repository": repository,
        "tag": tag,
        "digest": digest,
        "pull_policy": "resolve-selected-tag-to-architecture-digest-at-install",
    }


def _image_name(image: Any) -> str:
    value = str(image or "").split("@", 1)[0]
    return value.rsplit("/", 1)[-1].split(":", 1)[0]


def _catalog_identifier(app_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", app_id.casefold()).strip("-")
    if not normalized:
        raise ConversionError(f"No se puede normalizar el identificador: {app_id!r}")
    return f"linuxserver-{normalized}"


def _duration_seconds(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().casefold()
    units = {"s": 1, "m": 60, "h": 3600}
    matches = list(re.finditer(r"(\d+)([smh])", text))
    if not matches or "".join(match.group(0) for match in matches) != text:
        return None
    return sum(int(match.group(1)) * units[match.group(2)] for match in matches)


def _shm_size_mb(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return None
        return max(1, math.ceil(float(value) / (1024 * 1024))) if value > 0 else None
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(b|k|kb|ki|kib|m|mb|mi|mib|g|gb|gi|gib)?\s*",
        str(value),
        flags=re.I,
    )
    if not match:
        return None
    number = float(match.group(1))
    if number <= 0:
        return None
    unit = (match.group(2) or "b").casefold()
    factors = {
        "b": 1 / (1024 * 1024),
        "k": 1 / 1024,
        "kb": 1 / 1024,
        "ki": 1 / 1024,
        "kib": 1 / 1024,
        "m": 1,
        "mb": 1,
        "mi": 1,
        "mib": 1,
        "g": 1024,
        "gb": 1024,
        "gi": 1024,
        "gib": 1024,
    }
    return max(1, math.ceil(number * factors[unit]))


def _shm_installer_profile(value: Any) -> dict[str, Any]:
    size_mb = _shm_size_mb(value)
    if size_mb is None:
        return {}
    return {
        "tmpfs_mounts": [
            {
                "id": "compose-shm",
                "container_path": "/dev/shm",
                "default_size_mb": size_mb,
                "minimum_size_mb": 1,
                "size_prompt": "Size of the /dev/shm shared memory in MB",
                "mount_options": ["rw", "nosuid", "nodev"],
            }
        ]
    }


def _healthcheck_installer_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("disable") is True:
        return {}
    test = value.get("test")
    if isinstance(test, list):
        command = " ".join(str(item) for item in test)
    elif isinstance(test, str):
        command = test
    else:
        return {}
    if re.search(r"(?:^|\s)NONE(?:\s|$)", command, flags=re.I):
        return {}
    match = re.search(
        r"https?://(?:localhost|127\.0\.0\.1)(?::(?P<port>\d+))?(?P<path>/[^\s'\"]*)?",
        command,
        flags=re.I,
    )
    if not match:
        return {}
    scheme = match.group(0).split(":", 1)[0].casefold()
    port = int(match.group("port") or (443 if scheme == "https" else 80))
    if not 1 <= port <= 65535:
        return {}
    interval = _duration_seconds(value.get("interval")) or 30
    request_timeout = _duration_seconds(value.get("timeout")) or 5
    start_period = _duration_seconds(value.get("start_period")) or 0
    try:
        retries = max(1, int(value.get("retries", 3)))
    except (TypeError, ValueError):
        return {}
    return {
        "startup_healthcheck": {
            "type": "http",
            "scheme": scheme,
            "port": port,
            "path": match.group("path") or "/",
            "timeout_seconds": max(30, start_period + interval * retries),
            "request_timeout_seconds": max(1, request_timeout),
            "stability_seconds": 0,
            "verify_tls": scheme != "https",
            "required": True,
            "source": "compose-healthcheck",
        }
    }


def _extra_hosts(value: Any) -> list[dict[str, str]] | None:
    if value is None:
        return []
    entries: list[tuple[Any, Any]] = []
    if isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                return None
            host, separator, address = item.partition("=")
            if not separator:
                host, separator, address = item.partition(":")
            if not separator:
                return None
            entries.append((host, address))
    else:
        return None
    result: list[dict[str, str]] = []
    for raw_host, raw_address in entries:
        host = str(raw_host).strip()
        address = str(raw_address).strip()
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            return None
        if address != "host-gateway" and not re.fullmatch(r"[0-9A-Fa-f:.]+", address):
            return None
        result.append({"hostname": host, "address": address})
    return result


def _device_mapping(item: Any) -> tuple[str, str] | None:
    if isinstance(item, str):
        source, target, _ = _split_short_mount(item)
        source = source or target
    elif isinstance(item, dict):
        source = item.get("source") or item.get("path")
        target = item.get("target") or source
    else:
        return None
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source.startswith("/dev/") or not target.startswith("/dev/"):
        return None
    if any(part == ".." for part in source.split("/")) or any(
        part == ".." for part in target.split("/")
    ):
        return None
    return source, target


def _nvidia_requested(service: dict[str, Any]) -> bool:
    if str(service.get("runtime") or "").casefold() == "nvidia":
        return True
    reservations = (
        (((service.get("deploy") or {}).get("resources") or {}).get("reservations") or {})
        .get("devices")
        or []
    )
    return any(
        isinstance(item, dict)
        and str(item.get("driver") or "").casefold() == "nvidia"
        and "gpu" in {str(value).casefold() for value in item.get("capabilities") or []}
        for item in reservations
    )


def _device_request(
    source: str,
    target: str,
    *,
    optional: bool,
    nvidia_requested: bool,
) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", source.casefold()).strip("-")
    labels = {
        "/dev/dri": ("VA-API video acceleration", "GPU render device"),
        "/dev/snd": ("Host audio devices", "Audio device directory"),
        "/dev/dvb": ("Host DVB tuners", "DVB device directory"),
        "/dev/bus/usb": ("Host USB bus", "USB bus directory"),
    }
    if source == "/dev/dri":
        return {
            "id": "vaapi-render",
            "kind": "character-device",
            "purpose": "vaapi",
            "enable_prompt": labels[source][0],
            "enabled_default": not optional and not nvidia_requested,
            "required_by_compose": not optional,
            "path_prompt": labels[source][1],
            "host_path_default": "/dev/dri/renderD128",
            "container_path_strategy": "same-as-host",
            "mode": "0660",
            "deny_write": False,
            "gid_strategy": "host-device-gid",
            "source_mapping": f"{source}:{target}",
        }
    if source in {"/dev/snd", "/dev/dvb", "/dev/bus/usb"}:
        enable_label, path_label = labels[source]
        return {
            "id": slug,
            "kind": "character-device-tree",
            "purpose": {
                "/dev/snd": "audio",
                "/dev/dvb": "dvb",
                "/dev/bus/usb": "usb",
            }[source],
            "enable_prompt": enable_label,
            "enabled_default": not optional,
            "required_by_compose": not optional,
            "path_prompt": path_label,
            "host_path_default": source,
            "container_path": target,
            "mode": "preserve-host",
            "deny_write": False,
            "gid_strategy": "host-device-gid",
            "source_mapping": f"{source}:{target}",
        }
    purpose = "generic-device"
    if source == "/dev/kvm":
        purpose = "kvm"
    elif source == "/dev/net/tun":
        purpose = "tun"
    elif source == "/dev/fuse":
        purpose = "fuse"
    elif source.startswith("/dev/video"):
        purpose = "video-capture"
    elif source.startswith("/dev/tty"):
        purpose = "serial"
    elif source in {"/dev/vchiq", "/dev/vcsm"}:
        purpose = "raspberry-pi-media"
    return {
        "id": slug,
        "kind": "character-device",
        "purpose": purpose,
        "enable_prompt": f"Pass {source} to the LXC",
        "enabled_default": not optional,
        "required_by_compose": not optional,
        "path_prompt": f"Host device for {source}",
        "host_path_default": source,
        "container_path": target,
        "mode": "preserve-host",
        "deny_write": False,
        "gid_strategy": "host-device-gid",
        "source_mapping": f"{source}:{target}",
    }


def _device_installer_profile(
    service: dict[str, Any], optional: set[str] | None = None
) -> tuple[dict[str, Any], list[str]]:
    optional = optional or set()
    raw_devices = service.get("devices")
    requests: list[dict[str, Any]] = []
    blockers: list[str] = []
    nvidia_requested = _nvidia_requested(service)
    if raw_devices is not None:
        if not isinstance(raw_devices, list):
            blockers.append("devices-format")
        else:
            for item in raw_devices:
                raw = str(item).split("#", 1)[0].strip().strip("'\"")
                if "/path/to/device" in raw:
                    is_optional = raw in optional
                    requests.append(
                        {
                            "id": "user-selected-device",
                            "kind": "character-device",
                            "purpose": "user-selected-device",
                            "enable_prompt": "Pass a host device to the LXC",
                            "enabled_default": not is_optional,
                            "required_by_compose": not is_optional,
                            "path_prompt": "Actual device path on the host",
                            "host_path_default": "/dev/ttyUSB0",
                            "container_path_strategy": "same-as-host",
                            "mode": "preserve-host",
                            "deny_write": False,
                            "gid_strategy": "host-device-gid",
                            "source_mapping": raw,
                        }
                    )
                    continue
                mapping = _device_mapping(item)
                if mapping is None:
                    blockers.append(f"device-mapping:{item}")
                    continue
                source, target = mapping
                is_optional = raw in optional or any(
                    marker.startswith(f"{source}:") for marker in optional
                )
                request = _device_request(
                    source,
                    target,
                    optional=is_optional,
                    nvidia_requested=nvidia_requested,
                )
                if request["id"] not in {item["id"] for item in requests}:
                    requests.append(request)
    if nvidia_requested:
        requests.insert(
            0,
            {
                "id": "nvidia-runtime",
                "kind": "nvidia-runtime",
                "purpose": "nvidia-cuda-nvenc-nvdec",
                "enable_prompt": "Enable the NVIDIA GPU requested by the image",
                "enabled_default": True,
                "required_by_compose": True,
                "risk_level": "hardware-access",
                "device_selection": "all-requested-by-compose",
                "driver_libraries": "bind-compatible-host-driver-libraries-read-only",
            },
        )
    return ({"device_requests": requests} if requests else {}), blockers


def _merge_installer_profile(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, list):
            target.setdefault(key, []).extend(value)
        elif isinstance(value, dict):
            target.setdefault(key, {}).update(value)
        else:
            target[key] = value


def _network_mode(value: Any) -> str | None:
    if value in (None, ""):
        return None
    mode = str(value).casefold()
    return mode if mode in {"bridge", "default", "host"} else ""


def _capability_contract(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        capability = str(item).strip().upper().removeprefix("CAP_")
        if capability not in LINUX_CAPABILITIES:
            return None
        if capability not in result:
            result.append(capability)
    return result


def _host_module_requirements(
    service: dict[str, Any], capabilities: list[str] | None
) -> list[dict[str, Any]] | None:
    if not capabilities or "SYS_MODULE" not in capabilities:
        return []
    image = str(service.get("image") or "").casefold()
    if any(marker in image for marker in ("wireguard", "wg-easy", "uusec/firefly")):
        return [
            {
                "name": "wireguard",
                "enable_prompt": "Load and verify the WireGuard module on the Proxmox host",
                "enabled_default": True,
                "required_by_compose": True,
            }
        ]
    return None


def _sysctl_contract(value: Any) -> list[dict[str, str]] | None:
    if value is None:
        return []
    entries: list[tuple[Any, Any]] = []
    if isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                return None
            name, separator, raw_value = item.partition("=")
            if not separator:
                return None
            entries.append((name, raw_value))
    else:
        return None
    result: list[dict[str, str]] = []
    for raw_name, raw_value in entries:
        name = str(raw_name).strip()
        sysctl_value = str(raw_value).strip()
        # Restrict this generic adapter to kernel settings known to be
        # namespaced; host-global sysctls need an application review.
        if not re.fullmatch(r"net\.(?:ipv4|ipv6)\.[A-Za-z0-9_.-]+", name):
            return None
        if not sysctl_value or any(char in sysctl_value for char in "\r\n"):
            return None
        result.append({"name": name, "value": sysctl_value})
    return result


def _security_options_contract(value: Any) -> dict[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, list):
        return None
    result: dict[str, Any] = {}
    for item in value:
        option = str(item).strip().casefold()
        if option in {"no-new-privileges:true", "no-new-privileges=true"}:
            result["no_new_privileges"] = True
        elif option == "seccomp:unconfined":
            result["seccomp_profile"] = "unconfined"
        elif option == "apparmor:unconfined":
            result["apparmor_profile"] = "unconfined"
        elif option == "apparmor:rootlesskit":
            result["apparmor_profile"] = "unconfined"
            result["apparmor_source_profile"] = "rootlesskit"
        elif option == "label:disable":
            result["selinux_label_disabled"] = True
        else:
            return None
    return result


def _security_option_sets(
    value: Any, optional: set[str] | None = None
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    if value is None:
        return {}, []
    if not isinstance(value, list):
        return None, None
    optional = {item.casefold() for item in (optional or set())}
    required_items: list[Any] = []
    optional_items: list[Any] = []
    for item in value:
        target = optional_items if str(item).strip().casefold() in optional else required_items
        target.append(item)
    required = _security_options_contract(required_items)
    if required is None:
        return None, None
    optional_contracts: list[dict[str, Any]] = []
    for item in optional_items:
        options = _security_options_contract([item])
        if options is None:
            return None, None
        slug = re.sub(r"[^a-z0-9]+", "-", str(item).casefold()).strip("-")
        optional_contracts.append(
            {
                "id": slug,
                "enable_prompt": f"Apply optional security relaxation {item}",
                "enabled_default": False,
                "options": options,
            }
        )
    return required, optional_contracts


def _supplemental_groups(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        group = str(item).strip()
        if not re.fullmatch(r"(?:[0-9]+|[A-Za-z_][A-Za-z0-9_.-]*)", group):
            return None
        if group not in result:
            result.append(group)
    return result


RLIMIT_NAMES = {'as', 'core', 'cpu', 'data', 'fsize', 'locks', 'memlock',
                'msgqueue', 'nice', 'nofile', 'nproc', 'rss', 'rtprio',
                'rttime', 'sigpending', 'stack'}


def _ulimits_contract(value: Any) -> list[dict[str, str]] | None:
    if value is None:
        return []
    if not isinstance(value, dict):
        return None
    result = []
    for name, limit in value.items():
        if name not in RLIMIT_NAMES:
            return None
        pair = limit if isinstance(limit, dict) else {'soft': limit, 'hard': limit}
        if set(pair) != {'soft', 'hard'}:
            return None
        if any(type(v) is not int or not -1 <= v <= 999999999999999999 for v in pair.values()):
            return None
        soft, hard = pair['soft'], pair['hard']
        if hard != -1 and (soft == -1 or soft > hard):
            return None
        result.append({'name': name, 'soft': 'unlimited' if soft == -1 else str(soft),
                       'hard': 'unlimited' if hard == -1 else str(hard)})
    return result


def _compose_option_blockers(
    service: dict[str, Any], optional_devices: set[str] | None = None
) -> list[str]:
    blockers: list[str] = []
    if service.get('mem_limit') is not None:
        memory = _shm_size_mb(service['mem_limit'])
        if memory is None or memory < 16:
            blockers.append('mem-limit-format-or-below-proxmox-minimum')
        deploy_memory = (((service.get('deploy') or {}).get('resources') or {}).get('limits') or {}).get('memory')
        if deploy_memory is not None and str(service['mem_limit']) != str(deploy_memory):
            blockers.append('mem-limit-deploy-consistency-review')
    if _ulimits_contract(service.get('ulimits')) is None:
        blockers.append('ulimits-format-or-resource')
    if service.get("healthcheck") is not None and not _healthcheck_installer_profile(
        service["healthcheck"]
    ):
        healthcheck = service["healthcheck"]
        if not (isinstance(healthcheck, dict) and healthcheck.get("disable") is True):
            blockers.append("healthcheck-format")
    if service.get("extra_hosts") is not None and _extra_hosts(service["extra_hosts"]) is None:
        blockers.append("extra-hosts-format")
    if service.get("cpu_shares") is not None:
        try:
            if int(service["cpu_shares"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            blockers.append("cpu-shares-format")
    if service.get("user") is not None and not isinstance(service["user"], (str, int)):
        blockers.append("user-format")
    if service.get("entrypoint") is not None and not (
        isinstance(service["entrypoint"], str)
        or (
            isinstance(service["entrypoint"], list)
            and all(isinstance(item, str) for item in service["entrypoint"])
        )
    ):
        blockers.append("entrypoint-format")
    if service.get("working_dir") is not None and not re.fullmatch(
        r"/[^\r\n]*", str(service["working_dir"])
    ):
        blockers.append("working-dir-format")
    logging = service.get("logging")
    if logging is not None and not (
        isinstance(logging, dict)
        and logging.get("driver", "json-file") in {"json-file", "local"}
    ):
        blockers.append("logging-driver")
    mac_address = service.get("mac_address")
    if mac_address is not None and not re.fullmatch(
        r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", str(mac_address)
    ):
        blockers.append("mac-address-format")
    _, device_blockers = _device_installer_profile(service, optional_devices)
    blockers.extend(device_blockers)
    runtime = service.get("runtime")
    if runtime is not None and str(runtime).casefold() != "nvidia":
        blockers.append(f"runtime-value:{runtime}")
    ipc = service.get("ipc")
    if ipc is not None and str(ipc).casefold() != "host":
        blockers.append(f"ipc-value:{ipc}")
    if service.get("network_mode") is not None and _network_mode(service["network_mode"]) == "":
        blockers.append(f"network-mode-value:{service['network_mode']}")
    capabilities = _capability_contract(service.get("cap_add"))
    if capabilities is None:
        blockers.append("cap-add-format")
    elif _host_module_requirements(service, capabilities) is None:
        blockers.append("capability-host-global:SYS_MODULE")
    if service.get("sysctls") is not None and _sysctl_contract(service["sysctls"]) is None:
        blockers.append("sysctls-format-or-nonnamespaced")
    if service.get("security_opt") is not None and _security_options_contract(
        service["security_opt"]
    ) is None:
        blockers.append("security-options-value")
    if service.get("group_add") is not None and _supplemental_groups(
        service["group_add"]
    ) is None:
        blockers.append("group-add-format")
    return blockers


def _compose_installer_profile(
    service: dict[str, Any],
    optional_devices: set[str] | None = None,
    optional_security: set[str] | None = None,
) -> dict[str, Any]:
    profile = _shm_installer_profile(service.get("shm_size"))
    if str(service.get("image", "")).split("@", 1)[0].split(":", 1)[0] == "lscr.io/linuxserver/libreoffice":
        # LXC's volatile /run hides the directory shipped in the OCI rootfs.
        profile.setdefault("tmpfs_mounts", []).append({
            "id": "nginx-runtime",
            "container_path": "/run/nginx",
            "default_size_mb": 1,
            "minimum_size_mb": 1,
            "prompt_size": False,
            "mount_options": ["rw", "nosuid", "nodev", "mode=0755"],
        })
        profile["startup_healthcheck"] = {
            "scheme": "https", "port": 3001, "path": "/",
            "timeout_seconds": 180, "request_timeout_seconds": 10,
            "stability_seconds": 4, "verify_tls": False,
        }
    memory = _shm_size_mb(service.get('mem_limit'))
    if memory is not None and memory >= 16:
        profile.setdefault('resources', {})['memory_default_mb'] = memory
    limits = _ulimits_contract(service.get('ulimits'))
    if limits:
        profile.setdefault('resources', {})['rlimits'] = limits
    healthcheck = _healthcheck_installer_profile(service.get("healthcheck"))
    if healthcheck:
        profile.update(healthcheck)
    if "command" in service and service["command"] is not None:
        profile.setdefault("runtime", {})["command"] = service["command"]
    if "entrypoint" in service and service["entrypoint"] is not None:
        profile.setdefault("runtime", {})["compose_entrypoint"] = service["entrypoint"]
    if service.get("working_dir") is not None:
        profile.setdefault("runtime", {})["working_directory"] = str(service["working_dir"])
    if service.get("user") is not None:
        profile.setdefault("runtime", {})["user"] = str(service["user"])
    supplemental_groups = _supplemental_groups(service.get("group_add"))
    if supplemental_groups:
        profile.setdefault("runtime", {})["supplemental_groups"] = supplemental_groups
    if service.get("hostname") is not None:
        profile.setdefault("runtime", {})["hostname"] = str(service["hostname"])
    if service.get("cpu_shares") is not None:
        profile.setdefault("resources", {})["cpu_shares"] = int(service["cpu_shares"])
    extra_hosts = _extra_hosts(service.get("extra_hosts"))
    if extra_hosts:
        profile["extra_hosts"] = extra_hosts
    mac_address = str(service.get("mac_address") or "")
    if mac_address and mac_address != "00:00:00:00:00:00":
        profile.setdefault("network", {})["mac_address"] = mac_address.casefold()
    if "SETTINGS_ENCRYPTION_KEY" in _environment_names(service.get("environment")):
        profile.setdefault("generated_sensitive_environment", {})[
            "SETTINGS_ENCRYPTION_KEY"
        ] = {"strategy": "token-hex", "bytes": 16, "prompt": False}
    device_profile, _ = _device_installer_profile(service, optional_devices)
    _merge_installer_profile(profile, device_profile)
    if str(service.get("ipc") or "").casefold() == "host" and "tmpfs_mounts" not in profile:
        profile["tmpfs_mounts"] = [
            {
                "id": "compose-ipc-shm",
                "container_path": "/dev/shm",
                "default_size_mb": 1024,
                "minimum_size_mb": 64,
                "size_prompt": "Shared memory size for the GPU workload in MB",
                "mount_options": ["rw", "nosuid", "nodev"],
            }
        ]
    network_mode = _network_mode(service.get("network_mode"))
    if network_mode:
        profile.setdefault("network", {})["compose_mode"] = network_mode
    capabilities = _capability_contract(service.get("cap_add"))
    sysctls = _sysctl_contract(service.get("sysctls"))
    if capabilities:
        profile.setdefault("security", {})["required_capabilities"] = capabilities
        host_modules = _host_module_requirements(service, capabilities)
        if host_modules:
            profile.setdefault("security", {})["host_modules"] = host_modules
    if sysctls:
        profile.setdefault("security", {})["sysctls"] = sysctls
    security_options, optional_relaxations = _security_option_sets(
        service.get("security_opt"), optional_security
    )
    if security_options:
        profile.setdefault("security", {})["options"] = security_options
    if optional_relaxations:
        profile.setdefault("security", {})["optional_relaxations"] = optional_relaxations
    return profile


def _compose_requests_privileged_lxc(service: dict[str, Any]) -> bool:
    return service.get("privileged") in (True, 1, "true", "True")


def _compose_security_profile(
    service: dict[str, Any], optional_security: set[str] | None = None
) -> dict[str, Any]:
    requests_privileged = _compose_requests_privileged_lxc(service)
    requests_host_pid = str(service.get("pid") or "").casefold() == "host"
    options, optional_relaxations = _security_option_sets(
        service.get("security_opt"), optional_security
    )
    options = options or {}
    optional_relaxations = optional_relaxations or []
    requires_relaxed = options.get("apparmor_profile") == "unconfined" or options.get(
        "seccomp_profile"
    ) == "unconfined"
    optional_relaxed = any(
        item["options"].get("apparmor_profile") == "unconfined"
        or item["options"].get("seccomp_profile") == "unconfined"
        for item in optional_relaxations
    )
    if not requests_privileged and not requests_host_pid and not requires_relaxed and not optional_relaxed:
        return {}
    warnings: list[str] = []
    if requests_privileged:
        warnings.append(
            "The source Compose requests privileged: true, but this does not prove "
            "that the image needs a privileged LXC. ProxMenux will use an unprivileged "
            "LXC by default and will offer the broad mode only as an option."
        )
    if requests_host_pid:
        warnings.append(
            "The Compose requests pid: host to observe host processes. This is "
            "namespace access distinct from privileged and does not yet have a "
            "validated safe translation for LXC."
        )
    if requires_relaxed:
        warnings.append(
            "The image requests disabling part of the AppArmor or seccomp confinement."
        )
    if optional_relaxed:
        warnings.append(
            "The Compose offers an optional AppArmor or seccomp relaxation; it will stay "
            "disabled unless the user selects it."
        )
    all_security_options = [options, *(item["options"] for item in optional_relaxations)]
    if any(item.get("apparmor_source_profile") == "rootlesskit" for item in all_security_options):
        warnings.append(
            "The Docker rootlesskit profile does not exist in LXC and will be replaced by "
            "AppArmor unconfined, which is less restrictive."
        )
    return {
        "requires_privileged_lxc": False,
        "source_requests_privileged_lxc": requests_privileged,
        "optional_privileged_lxc": requests_privileged,
        "requires_host_pid_namespace": requests_host_pid,
        "source_requests_relaxed_confinement": requires_relaxed or optional_relaxed,
        "requires_relaxed_confinement": requires_relaxed,
        "optional_relaxed_confinement": optional_relaxed,
        "risk_level": "high",
        "confirmation_required": requires_relaxed,
        "warning": " ".join(warnings) + " Continue only if you trust the image and accept this risk.",
    }


def _compose_runtime_adaptations(service: dict[str, Any]) -> list[dict[str, str]]:
    def state(*keys: str) -> str:
        return (
            "pending-per-application"
            if any(key in service for key in keys)
            else "not-requested-by-compose"
        )

    return [
        {
            "id": "compose-process-runtime",
            "upstream_behavior": "Compose can replace Entrypoint, User and WorkingDir and request an init process or interactive terminal.",
            "native_lxc_behavior": "ProxMenux applies the process overrides through native LXC init directives; lxc-init provides PID 1 supervision and the CT console provides terminal access.",
            "reason": "The OCI process must start with the same identity, command and working directory without Docker.",
            "behavioral_impact": "Compose stdin_open and tty become access through the Proxmox LXC console.",
            "validation": state(
                "entrypoint", "user", "group_add", "working_dir", "init", "stdin_open", "tty"
            ),
        },
        {
            "id": "compose-healthcheck",
            "upstream_behavior": "Docker periodically executes the declared container healthcheck.",
            "native_lxc_behavior": "For a single-service LXC, ProxMenux translates HTTP localhost checks into a mandatory first-start service check.",
            "reason": "Proxmox has no persistent Docker health state, while the installer still must detect a failed first boot.",
            "behavioral_impact": "The check runs during installation rather than continuously after installation.",
            "validation": state("healthcheck"),
        },
        {
            "id": "compose-cpu-priority",
            "upstream_behavior": "Docker cpu_shares sets a relative scheduling weight with 1024 as its neutral value.",
            "native_lxc_behavior": "ProxMenux converts the relative weight to Proxmox cpuunits with 100 as its neutral value and lets the user review it.",
            "reason": "Both settings express relative CPU priority on different scales.",
            "behavioral_impact": "Rounding and Proxmox minimum limits can slightly change very low weights.",
            "validation": state("cpu_shares"),
        },
        {
            "id": "compose-resource-limits",
            "upstream_behavior": "mem_limit sets the memory ceiling; ulimits sets process soft/hard resource limits.",
            "native_lxc_behavior": "mem_limit supplies the editable Proxmox memory default, rounded up to MiB; ulimits maps to lxc.prlimit with -1 represented as unlimited.",
            "reason": "Use native Proxmox memory and LXC prlimits, without a wrapper or changing the host kernel configuration.",
            "behavioral_impact": "User-selected memory overrides Compose. Swap is a separate choice. Kernel restrictions still apply; nproc counts processes by real UID, not by container.",
            "validation": state("mem_limit", "ulimits"),
        },
        {
            "id": "compose-network-identity",
            "upstream_behavior": "Compose can set hostname, MAC address, extra hosts and attach a service to Docker networks.",
            "native_lxc_behavior": "ProxMenux applies hostname and MAC to net0, writes additional host aliases into the LXC and uses its dedicated bridge connection for single-service networks.",
            "reason": "A dedicated LXC has its own network namespace and does not need a Docker bridge per service.",
            "behavioral_impact": "host-gateway resolves to the IPv4 address of the selected Proxmox bridge.",
            "validation": state("hostname", "mac_address", "extra_hosts", "networks"),
        },
        {
            "id": "compose-network-mode",
            "upstream_behavior": "Docker host mode removes Docker network isolation; bridge and default use a Docker-managed network.",
            "native_lxc_behavior": "The OCI process uses the dedicated LXC network namespace directly, so host, bridge and default all listen on the LXC address without Docker NAT.",
            "reason": "The LXC is the application host and already has its own address and port namespace.",
            "behavioral_impact": "host means the LXC host, never the Proxmox host; this preserves Proxmox network isolation.",
            "validation": state("network_mode"),
        },
        {
            "id": "compose-capabilities-and-sysctls",
            "upstream_behavior": "Compose can add Linux capabilities and set kernel parameters in the container network namespace.",
            "native_lxc_behavior": "ProxMenux validates requested capabilities against the native LXC capability set and writes namespaced network settings as lxc.sysctl directives.",
            "reason": "A native OCI-LXC already starts with the namespaced capability set; lxc.cap.keep would incorrectly discard unrelated required capabilities.",
            "behavioral_impact": "Host-global capabilities such as SYS_MODULE remain blocked until their host prerequisite is explicitly adapted.",
            "validation": state("cap_add", "sysctls"),
        },
        {
            "id": "docker-engine-metadata",
            "upstream_behavior": "Compose labels annotate Docker objects and the json-file logging driver rotates Docker-managed logs.",
            "native_lxc_behavior": "Labels remain source metadata; Docker json-file settings are not applied because the OCI process runs directly under LXC.",
            "reason": "There is no Docker object or Docker json-file log behind a native OCI-LXC application.",
            "behavioral_impact": "Docker-only label consumers and Docker log-driver rotation do not exist in the native deployment.",
            "validation": state("labels", "logging"),
        },
        {
            "id": "compose-device-passthrough",
            "upstream_behavior": "Compose passes host character devices or requests an NVIDIA runtime GPU.",
            "native_lxc_behavior": "ProxMenux converts recognized device declarations to native Proxmox dev resources; NVIDIA profiles also inject compatible host driver libraries read-only.",
            "reason": "Native OCI-LXC does not execute Docker device or NVIDIA runtime hooks.",
            "behavioral_impact": "Hardware is exposed only after explicit user confirmation and host-path validation.",
            "validation": state("devices", "runtime"),
        },
        {
            "id": "compose-host-ipc",
            "upstream_behavior": "ipc: host shares the Docker host IPC namespace, commonly to avoid Docker's small default shared-memory allocation.",
            "native_lxc_behavior": "The application keeps the LXC IPC namespace and receives a configurable 1 GiB /dev/shm instead of sharing Proxmox host IPC.",
            "reason": "Processes in a single native LXC already share one IPC namespace; retaining isolation is safer than exposing host IPC.",
            "behavioral_impact": "The application cannot exchange IPC objects with processes on the Proxmox host.",
            "validation": state("ipc"),
        },
    ]


def _title_from_readme(readme: str, fallback: str) -> str:
    for line in readme.splitlines():
        match = re.match(r"^#\s+\[(?:linuxserver/)?([^\]]+)\]", line, flags=re.I)
        if not match:
            match = re.match(r"^#\s+(?:linuxserver/)?(.+?)\s*$", line, flags=re.I)
        if match:
            return match.group(1).strip().replace("-", " ").title()
    return fallback.replace("-", " ").title()


def _application_intro(readme: str) -> tuple[str, str | None]:
    found_title = False
    for line in readme.splitlines():
        if not found_title:
            if re.match(r"^#\s+", line):
                found_title = True
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("[![") or stripped.startswith("<!--"):
            continue
        if stripped.startswith("## "):
            break
        if stripped.startswith("[") and "](" in stripped and not stripped.startswith("[!["):
            website_match = re.match(r"^\[[^\]]+\]\((https?://[^)]+)\)", stripped)
            website = website_match.group(1) if website_match else None
            plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", stripped)
            plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain).strip()
            if plain:
                return plain, website
    return "", None


def _architectures(readme: str) -> list[str]:
    mappings = {
        "x86-64": "amd64",
        "x86_64": "amd64",
        "amd64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    result: list[str] = []
    in_section = False
    for line in readme.splitlines():
        if re.match(r"^##\s+Supported Architectures\s*$", line.strip(), flags=re.I):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or "|" not in line:
            continue
        cells = [cell.strip().casefold() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        architecture = mappings.get(cells[0])
        available = len(cells) < 2 or "❌" not in cells[1]
        if architecture and available and architecture not in result:
            result.append(architecture)
    return result or ["amd64"]


def _mini_changelog(readme: str, limit: int = 5) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    in_versions = False
    for line in readme.splitlines():
        if re.match(r"^##\s+Versions\s*$", line.strip(), flags=re.I):
            in_versions = True
            continue
        if in_versions and line.startswith("## "):
            break
        if not in_versions:
            continue
        match = re.match(
            r"^\s*[-*]\s+\*{0,2}(\d{2}\.\d{2}\.\d{2,4}):?\*{0,2}\s*-?\s*(.+?)\s*$",
            line,
        )
        if not match:
            continue
        raw_date, note = match.groups()
        day, month, year = raw_date.split(".")
        if len(year) == 2:
            year = f"20{year}"
        entries.append({"date": f"{year}-{month}-{day}", "note": note})
        if len(entries) >= limit:
            break
    return entries


def _markdown_section(readme: str, title: str) -> str:
    lines = readme.splitlines()
    heading_level: int | None = None
    content: list[str] = []
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.strip())
        if heading_level is None:
            if heading and heading.group(2).strip().casefold() == title.casefold():
                heading_level = len(heading.group(1))
            continue
        if heading and len(heading.group(1)) <= heading_level:
            break
        content.append(line)
    return "\n".join(content).strip()


def _clean_credential(value: str) -> str:
    return value.strip().strip("`*_[](){}<>.,;:'\"")


def _default_credentials(setup: str) -> list[dict[str, Any]]:
    plain = re.sub(r"[`*_]", "", setup)
    compact = re.sub(r"\s+", " ", plain).strip()
    patterns = [
        re.compile(
            r"default(?:\s+admin)?\s+login\s*:?\s*username\s*[:=]\s*(\S+)\s+password\s*[:=]\s*(\S+)",
            re.I,
        ),
        re.compile(
            r"default\s+user(?:name)?/password\s+(?:of|is|:)\s*(\S+?)/(\S+)",
            re.I,
        ),
        re.compile(
            r"default\s+username\s+(?:is|:)\s*(\S+).*?\bpassword\s+(?:is|:)\s*(\S+)",
            re.I,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(compact)
        if not match:
            continue
        username, password = (_clean_credential(value) for value in match.groups())
        placeholders = {"", "user", "username", "pass", "password", "none", "changeme"}
        if username.casefold() in placeholders or password.casefold() in placeholders:
            continue
        return [
            {
                "label": "Default login",
                "type": "static-default",
                "username": username,
                "password": password,
                "change_required": True,
                "source": "linuxserver-readme-application-setup",
                "retrieval": None,
            }
        ]
    return []


def _runtime_credentials(setup: str) -> list[dict[str, Any]]:
    plain = re.sub(r"[`*_]", "", setup)
    compact = re.sub(r"\s+", " ", plain).strip()
    match = re.search(
        r"temporary password for the\s+([A-Za-z0-9_.-]+)\s+user will be printed to the container log",
        compact,
        flags=re.I,
    )
    if not match:
        return []
    return [
        {
            "label": "Temporary login",
            "type": "runtime-generated",
            "username": _clean_credential(match.group(1)),
            "password": None,
            "change_required": True,
            "source": "linuxserver-readme-application-setup",
            "retrieval": {
                "method": "container-console-pattern",
                "pattern_id": "linuxserver-temporary-password",
                "timeout_seconds": 90,
            },
        }
    ]


def _first_run_contract(
    readme: str,
    ports: list[dict[str, Any]],
    repo: Repository,
) -> dict[str, Any]:
    setup = _markdown_section(readme, "Application Setup")
    tcp_ports = {item["container_port"] for item in ports if item["protocol"] == "tcp"}
    endpoints: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    url_pattern = re.compile(
        r"\b(https?)://[^\s`<>()]+?(?::(\d{1,5}))(?P<path>/[^\s`<>()]*)?",
        re.I,
    )
    for match in url_pattern.finditer(setup):
        scheme = match.group(1).casefold()
        port = int(match.group(2))
        path = match.group("path") or "/"
        if port not in tcp_ports or not 1 <= port <= 65535:
            continue
        key = (scheme, port, path)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(
            {
                "label": "Web UI",
                "scheme": scheme,
                "port": port,
                "path": path,
                "source": "linuxserver-readme-application-setup",
            }
        )

    if not endpoints:
        web_port = next((item["container_port"] for item in ports if item["protocol"] == "tcp"), None)
        if web_port is not None:
            endpoints.append(
                {
                    "label": "Web UI",
                    "scheme": "https" if web_port == 443 else "http",
                    "port": web_port,
                    "path": "/",
                    "source": "compose-first-tcp-port-fallback",
                }
            )

    for index, endpoint in enumerate(endpoints, 1):
        if len(endpoints) > 1:
            endpoint["label"] = f"Web UI {index}"
    credentials = _default_credentials(setup) or _runtime_credentials(setup)
    return {
        "endpoints": endpoints,
        "credentials": credentials,
    }


def summarize_readme(repo: Repository, readme: str) -> dict[str, Any]:
    # Parsing the Compose block here also removes infrastructure repositories
    # that happen to share LinuxServer's docker-* naming convention.
    compose_text = extract_compose(readme)
    try:
        compose = yaml.safe_load(compose_text)
    except yaml.YAMLError as exc:
        raise ConversionError(f"Docker Compose no valido: {exc}") from exc
    services = compose.get("services") if isinstance(compose, dict) else None
    if not isinstance(services, dict) or not services:
        raise ConversionError("El Compose no contiene services")
    candidates = [
        value
        for value in services.values()
        if isinstance(value, dict) and _image_name(value.get("image")) == repo.app_id
    ]
    if len(services) == 1:
        main_service = next(iter(services.values()))
    elif len(candidates) == 1:
        main_service = candidates[0]
    else:
        raise ConversionError("No se puede identificar la imagen principal del Compose")
    if not isinstance(main_service, dict) or not main_service.get("image"):
        raise ConversionError("El servicio principal no declara una imagen")
    title = _title_from_readme(readme, repo.app_id)
    description, website = _application_intro(readme)
    architectures = _architectures(readme)
    changelog = _mini_changelog(readme, limit=1)
    return {
        "title": title,
        "description": description or repo.description,
        "website": website,
        "architectures": architectures,
        "icon": f"https://raw.githubusercontent.com/linuxserver/docker-templates/master/linuxserver.io/img/{repo.app_id}-icon.png",
        "updated_at": changelog[0]["date"] if changelog else repo.pushed_at,
        "main_image": str(main_service["image"]),
    }


def convert_readme(
    repo: Repository,
    readme: str,
    revision: str,
    raw_url: str,
) -> dict[str, Any]:
    compose_text = extract_compose(readme)
    try:
        compose = yaml.safe_load(compose_text)
    except yaml.YAMLError as exc:
        raise ConversionError(f"Docker Compose no valido: {exc}") from exc
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict):
        raise ConversionError("El Compose no contiene services")
    services = compose["services"]
    multi_service = len(services) > 1
    if multi_service:
        candidates = [
            (name, value)
            for name, value in services.items()
            if isinstance(value, dict) and _image_name(value.get("image")) == repo.app_id
        ]
        if len(candidates) != 1:
            raise ConversionError("No se puede identificar de forma univoca el servicio principal del Compose")
        service_name, service = candidates[0]
    else:
        service_name, service = next(iter(services.items()))
    if not isinstance(service, dict) or not service.get("image"):
        raise ConversionError("El servicio no declara una imagen")

    related_services = [
        {"name": str(name), "image": str(value.get("image")) if isinstance(value, dict) and value.get("image") else None}
        for name, value in services.items()
        if name != service_name
    ]

    markers = _optional_markers(compose_text)
    service_keys = set(service)
    unsupported = sorted(service_keys - SUPPORTED_SERVICE_KEYS)
    blockers = [f"compose-key:{key}" for key in unsupported]
    blockers.extend(_compose_option_blockers(service, markers["devices"]))
    if multi_service:
        blockers.insert(0, "multi-service-compose")
    stop_grace_period = service.get("stop_grace_period")
    stop_grace_seconds = _duration_seconds(stop_grace_period)
    if stop_grace_period is not None and stop_grace_seconds is None:
        blockers.append("stop-grace-period-format")
    if service.get("shm_size") is not None and _shm_size_mb(service["shm_size"]) is None:
        blockers.append("shm-size-format")
    if compose.get("networks"):
        blockers.append("top-level-networks")
    if compose.get("volumes"):
        # Named volumes are supported only after their service attachment is reviewed.
        blockers.append("top-level-named-volumes")

    ports = _port_contract(service.get("ports"), markers["ports"])
    first_run = _first_run_contract(readme, ports, repo)
    primary_endpoint = next(iter(first_run["endpoints"]), None)
    web_port = primary_endpoint["port"] if primary_endpoint else None
    scheme = primary_endpoint["scheme"] if primary_endpoint else "http"
    launch_path = primary_endpoint["path"] if primary_endpoint else "/"
    title = _title_from_readme(readme, repo.app_id)
    description, website = _application_intro(readme)
    changelog = _mini_changelog(readme)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    template = {
        "schema_version": "0.4.0",
        "kind": "proxmenux.oci-template",
        "id": _catalog_identifier(repo.app_id),
        "status": "generated-unvalidated" if not blockers else "generated-review-required",
        "catalog_ui": {
            "title": {"en_US": title, "es_ES": title},
            "tagline": {"en_US": description or repo.description},
            "description": {"en_US": description or repo.description},
            "category": repo.category,
            "category_label": repo.category_label,
            "author": "LinuxServer.io",
            "developer": None,
            "icon": f"https://raw.githubusercontent.com/linuxserver/docker-templates/master/linuxserver.io/img/{repo.app_id}-icon.png",
            "thumbnail": f"https://raw.githubusercontent.com/linuxserver/docker-templates/master/linuxserver.io/img/{repo.app_id}-banner.png",
            "screenshots": [],
            "architectures": _architectures(readme),
            "launch": {"scheme": scheme, "port": web_port, "path": launch_path},
            "website": website,
            "documentation": f"https://docs.linuxserver.io/images/docker-{repo.app_id}/",
            "repository": repo.html_url,
            "tips": [],
            "mini_changelog": changelog,
            "display_version": None,
            "updated_at": changelog[0]["date"] if changelog else repo.pushed_at,
        },
        "source": {
            "provider": "linuxserver.io",
            "repository": repo.html_url,
            "default_branch": repo.default_branch,
            "revision": revision,
            "readme_raw_url": raw_url,
            "readme_pushed_at": repo.pushed_at,
            "compose_sha256": hashlib.sha256(compose_text.encode("utf-8")).hexdigest(),
            "generated_at": generated_at,
        },
        "container_contract": {
            "service_name": service_name,
            "container_name": service.get("container_name", service_name),
            "image": _image_contract(str(service["image"])),
            "environment": _environment_contract(service.get("environment"), markers["environment"]),
            "volumes": _mount_contract(service.get("volumes"), markers["volumes"]),
            "ports": ports,
            "related_services": related_services,
            "restart": service.get("restart"),
            "stop_grace_period": None if stop_grace_period is None else str(stop_grace_period),
            "original_compose": compose_text,
        },
        "first_run": first_run,
        "proxmox": {
            "runtime": "native-oci-lxc",
            "technology_status": "proxmox-technology-preview",
            "defaults": {
                "unprivileged": True,
                "ostype": "auto-from-image",
                "cores": 2,
                "memory_mb": 1024,
                "swap_mb": 512,
                "rootfs_size_gb": 8,
                "rootfs_storage": "local-lvm",
                "volume_storage": "local-lvm",
                "template_storage": "local",
                "bridge": "vmbr0",
                "ipv4": "dhcp",
                "firewall": True,
                "host_managed_network": True,
                "onboot": False,
                "features": ["nesting=1"],
                "shutdown_timeout_seconds": stop_grace_seconds or 30,
            },
            "image_metadata_policy": {
                "entrypoint": "import-from-oci-image",
                "cmd": "import-from-oci-image",
                "environment": "import-image-env-then-apply-compose-overrides",
                "user": "import-from-oci-image",
                "working_dir": "import-from-oci-image",
                "stop_signal": "import-from-oci-image",
            },
            **(
                {"installer_profile": _compose_installer_profile(service, markers["devices"], markers["security_opt"])}
                if _compose_installer_profile(service, markers["devices"], markers["security_opt"])
                else {}
            ),
            **(
                {"security_profile": _compose_security_profile(service, markers["security_opt"])}
                if _compose_security_profile(service, markers["security_opt"])
                else {}
            ),
            "adaptations": [
                {
                    "id": "dedicated-lxc-network",
                    "upstream_behavior": "Docker publishes selected container ports on the Docker host.",
                    "native_lxc_behavior": "The application listens on the same container ports at its dedicated LXC address.",
                    "reason": "A native LXC has its own address and does not require Docker port NAT.",
                    "behavioral_impact": "Users open the LXC address instead of the Proxmox host address.",
                    "validation": "pending-per-application",
                },
                {
                    "id": "compose-environment-overlay",
                    "upstream_behavior": "Compose environment values override OCI image environment values.",
                    "native_lxc_behavior": "ProxMenux merges the same values into lxc.environment.runtime while the CT is stopped.",
                    "reason": "PVE imports image Env automatically; Compose values still need to override it.",
                    "behavioral_impact": "None expected.",
                    "validation": "pending-per-application",
                },
                {
                    "id": "stop-grace-period",
                    "upstream_behavior": "Docker waits for Compose stop_grace_period before forcing termination.",
                    "native_lxc_behavior": "ProxMenux records the same timeout for its pct shutdown lifecycle operations.",
                    "reason": "Proxmox has no equivalent per-CT persistent restart-policy field; startup.down is not a shutdown timeout.",
                    "behavioral_impact": "Normal Proxmox node shutdown remains governed by the node-wide shutdown policy.",
                    "validation": "pending-per-application" if stop_grace_period is not None else "not-requested-by-compose",
                },
                {
                    "id": "compose-shm-size",
                    "upstream_behavior": "Compose sets the size of the container /dev/shm tmpfs.",
                    "native_lxc_behavior": "ProxMenux mounts a native LXC tmpfs at /dev/shm with the same requested capacity.",
                    "reason": "The OCI image runs directly as an LXC and therefore needs the equivalent Proxmox mount entry.",
                    "behavioral_impact": "None expected.",
                    "validation": "pending-per-application" if service.get("shm_size") is not None else "not-requested-by-compose",
                },
                {
                    "id": "compose-command",
                    "upstream_behavior": "Compose replaces the image Cmd while retaining its Entrypoint.",
                    "native_lxc_behavior": "ProxMenux reads the official OCI Entrypoint and combines it with the Compose command as the native LXC init command.",
                    "reason": "Proxmox stores the effective OCI process as one entrypoint string.",
                    "behavioral_impact": "None expected.",
                    "validation": "pending-per-application" if service.get("command") is not None else "not-requested-by-compose",
                },
                *_compose_runtime_adaptations(service),
            ],
        },
        "compatibility": {
            "automatic_install_candidate": not blockers,
            "validated": False,
            "supported_compose_keys": sorted(SUPPORTED_SERVICE_KEYS),
            "untranslated_blockers": blockers,
            "policy": "A generated template is never promoted to validated without install, health, restart and persistence tests.",
        },
        "validation": {
            "schema": "passed-at-generation",
            "clean_install": "pending",
            "service_health": "pending",
            "restart_persistence": "pending",
            "backup_restore": "pending",
            "update_preserves_data": "pending",
        },
        "lifecycle": {
            "update_strategy": "replace-rootfs-from-new-oci-image-preserve-managed-volumes",
            "registry_state": {
                "resolved_architecture": None,
                "resolved_digest": None,
                "image_version_label": None,
                "image_created": None,
            },
            "change_detection": "compare-resolved-architecture-digest",
            "automatic_unattended_updates": False,
        },
    }
    if multi_service:
        from .casaos import _compose_stack_contract
        template['compose_stack'] = _compose_stack_contract(compose, compose, service_name, markers)
        template['compatibility']['untranslated_blockers'].append('native-multi-lxc-orchestrator-not-yet-implemented')
    return template
