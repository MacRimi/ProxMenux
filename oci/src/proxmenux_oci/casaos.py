from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any

import yaml

from .converter import (
    SENSITIVE_NAME,
    SUPPORTED_SERVICE_KEYS,
    ConversionError,
    _compose_installer_profile,
    _compose_option_blockers,
    _compose_security_profile,
    _compose_runtime_adaptations,
    _duration_seconds,
    _environment_contract,
    _image_contract,
    _mount_contract,
    _optional_markers,
    _port_contract,
    _compose_requests_privileged_lxc,
    _shm_size_mb,
)


CASAOS_CATEGORY_MAP = {
    "AI": ("ai", "AI / Coding & Dev-Tools"),
    "Developer": ("ai", "AI / Coding & Dev-Tools"),
    "Finance": ("finance", "Finance & Budgeting"),
    "Home": ("smarthome", "IoT & Smart Home"),
    "Media": ("media", "Media & Streaming"),
    "Networking": ("network", "Network & Firewall"),
    "Productivity": ("productivity", "Productivity & Workflows"),
    "Social": ("communication", "Communication & Community"),
}

ARCHITECTURE_MAP = {
    "amd64": "amd64",
    "arm64": "arm64",
}

CASAOS_TRANSLATED_SERVICE_KEYS = SUPPORTED_SERVICE_KEYS | {"deploy", "network_mode"}


def normalize_app_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not normalized:
        raise ConversionError(f"Cannot normalise the CasaOS identifier: {value!r}")
    return normalized


def _localized(value: Any, fallback: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        result = {str(key): str(text) for key, text in value.items() if text not in (None, "")}
        if "en_US" not in result:
            result["en_US"] = next(iter(result.values()), fallback)
        return result
    if value not in (None, ""):
        return {"en_US": str(value)}
    return {"en_US": fallback}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _main_service(compose: dict[str, Any], metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    services = compose.get("services")
    if not isinstance(services, dict) or not services:
        raise ConversionError("The CasaOS Compose file has no services")
    service_name = metadata.get("main")
    if not service_name and len(services) == 1:
        service_name = next(iter(services))
    if not service_name or service_name not in services:
        raise ConversionError("x-casaos.main no identifica un servicio valido")
    service = services[service_name]
    if not isinstance(service, dict) or not service.get("image"):
        raise ConversionError("The main CasaOS service declares no image")
    return str(service_name), service


def _image_tail(image: str) -> str:
    return normalize_app_id(canonical_image_repository(image).rsplit("/", 1)[-1])


def image_repository(image: str) -> str:
    reference = image.strip().split("@", 1)[0]
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    return reference[:colon] if colon > slash else reference


def canonical_image_repository(image: str) -> str:
    repository = image_repository(image).casefold()
    for prefix in ("lscr.io/linuxserver/", "ghcr.io/linuxserver/", "docker.io/linuxserver/"):
        if repository.startswith(prefix):
            return f"linuxserver/{repository.rsplit('/', 1)[-1]}"
    return repository


def latest_image_reference(image: str) -> str:
    return f"{image_repository(image)}:latest"


def image_repository_url(image: str) -> str:
    repository = image_repository(image)
    parts = repository.split("/")
    if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
        registry = parts[0]
        path = "/".join(parts[1:])
    else:
        registry = "docker.io"
        path = repository
    if registry == "docker.io":
        if "/" in path:
            return f"https://hub.docker.com/r/{path}"
        return f"https://hub.docker.com/_/{path}"
    return f"https://{registry}/{path}"


def _variant(app_id: str, service: dict[str, Any]) -> str | None:
    folded = app_id.casefold()
    names = {
        "nvidia": "nvidia",
        "cuda": "nvidia",
        "amd": "amd",
        "rocm": "amd",
        "intel": "intel",
        "openvino": "intel",
        "gpu": "gpu",
    }
    for marker, variant in names.items():
        if re.search(rf"(?:^|[-_]){marker}(?:$|[-_])", folded):
            return variant
    hardware_text = str(
        {
            "devices": service.get("devices"),
            "runtime": service.get("runtime"),
            "environment": service.get("environment"),
            "deploy": service.get("deploy"),
        }
    ).casefold()
    if "nvidia" in hardware_text or "cuda" in hardware_text:
        return "nvidia"
    if "rocm" in hardware_text or "/dev/kfd" in hardware_text:
        return "amd"
    if "openvino" in hardware_text:
        return "intel"
    if "/dev/dri" in hardware_text or "/dev/video" in hardware_text:
        return "vaapi"
    reservations = (((service.get("deploy") or {}).get("resources") or {}).get("reservations") or {})
    if reservations.get("devices"):
        return "gpu"
    return None


def _base_app_id(app_id: str) -> str:
    return re.sub(r"-(?:nvidia|cuda|amd|rocm|intel|openvino|gpu)$", "", app_id, flags=re.I)


def _functional_base_id(app_id: str, distribution: str) -> str:
    base_id = _base_app_id(app_id)
    if base_id.startswith("icewhale-"):
        base_id = base_id.removeprefix("icewhale-")
    if distribution in {"official", "linuxserver"} or "-" not in base_id:
        return base_id
    prefix, remainder = base_id.split("-", 1)
    if len(prefix) >= 5 and (distribution.startswith(prefix) or prefix.startswith(distribution)):
        return remainder
    return base_id


def image_distributor(image: str, base_app_id: str) -> str:
    repository = canonical_image_repository(image)
    if repository.startswith("linuxserver/"):
        return "linuxserver"
    parts = repository.split("/")
    if len(parts) == 1:
        return "official"
    if "." in parts[0] and len(parts) > 1:
        owner = parts[1]
    else:
        owner = parts[0]
    owner_id = normalize_app_id(owner)
    compact_owner = owner_id.replace("-", "")
    compact_app = base_app_id.replace("-", "")
    if compact_owner in compact_app or compact_app in compact_owner:
        return "official"
    return owner_id


def image_provider(distribution: str) -> str:
    return "linuxserver.io" if distribution == "linuxserver" else distribution


def image_documentation_url(image: str) -> str | None:
    if canonical_image_repository(image).startswith("linuxserver/"):
        return f"https://docs.linuxserver.io/images/docker-{_image_tail(image)}/"
    return None


def parse_casaos_compose(compose_text: str) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    try:
        compose = yaml.safe_load(compose_text)
    except yaml.YAMLError as exc:
        raise ConversionError(f"Docker Compose CasaOS no valido: {exc}") from exc
    if not isinstance(compose, dict):
        raise ConversionError("The CasaOS document is not a Compose mapping")
    metadata = compose.get("x-casaos")
    if not isinstance(metadata, dict):
        raise ConversionError("The Compose file has no x-casaos metadata")
    service_name, service = _main_service(compose, metadata)
    return compose, metadata, service_name, service


def summarize_casaos_compose(compose_text: str, source_path: str) -> dict[str, Any]:
    compose, metadata, service_name, service = parse_casaos_compose(compose_text)
    app_id = normalize_app_id(str(compose.get("name") or source_path.split("/")[-2]))
    title = _localized(metadata.get("title"), app_id)["en_US"]
    architectures = []
    for raw in metadata.get("architectures") or ["amd64"]:
        architecture = ARCHITECTURE_MAP.get(str(raw).casefold())
        if architecture and architecture not in architectures:
            architectures.append(architecture)
    image = str(service["image"])
    identity_candidates = {
        app_id,
        normalize_app_id(service_name),
        normalize_app_id(title),
        _image_tail(image),
    }
    store_id = str(metadata.get("id") or "")
    if store_id:
        identity_candidates.add(normalize_app_id(store_id.rsplit(".", 1)[-1]))
    distribution = image_distributor(image, _base_app_id(app_id))
    return {
        "id": app_id,
        "base_id": _functional_base_id(app_id, distribution),
        "title": title,
        "description": _neutral_localized(metadata.get("description"), "")["en_US"],
        "website": metadata.get("website"),
        "repository": metadata.get("repo"),
        "icon": None,
        "architectures": architectures or ["amd64"],
        "updated_at": str(metadata.get("update_at") or ""),
        "version": str(metadata.get("version") or ""),
        "store_id": store_id,
        "main_service": service_name,
        "main_image": image,
        "main_image_repository": canonical_image_repository(image),
        "selected_image": latest_image_reference(image),
        "variant": _variant(app_id, service),
        "distribution": distribution,
        "identity_candidates": sorted(identity_candidates),
    }


def _endpoint(metadata: dict[str, Any], service: dict[str, Any]) -> list[dict[str, Any]]:
    raw_port = metadata.get("port_map")
    if raw_port in (None, ""):
        return []
    try:
        published_port = int(str(raw_port))
    except ValueError:
        return []
    container_port = published_port
    for item in service.get("ports") or []:
        if isinstance(item, dict):
            published = item.get("published")
            target = item.get("target")
        else:
            port_text = str(item).split("/", 1)[0]
            parts = port_text.split(":")
            published = parts[-2] if len(parts) > 1 else None
            target = parts[-1]
        if str(published) == str(published_port):
            try:
                container_port = int(str(target))
            except ValueError:
                pass
            break
    scheme = str(metadata.get("scheme") or "http").casefold()
    if scheme not in {"http", "https"}:
        scheme = "http"
    path = str(metadata.get("index") or "/")
    if re.search(r"casaos|zimaos|zima", path, re.I):
        path = "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return [
        {
            "label": "Web UI",
            "scheme": scheme,
            "port": container_port,
            "path": path,
            "source": "compose-metadata",
        }
    ]


def _credentials(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    tips = metadata.get("tips") or {}
    if not isinstance(tips, dict):
        return []
    before_install = tips.get("before_install") or {}
    text = before_install.get("en_US", "") if isinstance(before_install, dict) else str(before_install)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        cells = [cell.strip().strip("`* ") for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or "user" not in cells[0].casefold() or "pass" not in cells[1].casefold():
            continue
        for row in lines[index + 1 :]:
            values = [cell.strip().strip("`* ") for cell in row.strip().strip("|").split("|")]
            if len(values) < 2:
                break
            if all(re.fullmatch(r"[-: ]+", value or "-") for value in values[:2]):
                continue
            username, password = values[:2]
            if not username or not password:
                continue
            dynamic = any(marker in password.casefold() for marker in ("from log", "in the log", "generated"))
            if dynamic:
                return []
            return [
                {
                    "label": "Default login",
                    "type": "static-default",
                    "username": username,
                    "password": password,
                    "change_required": True,
                    "source": "casaos-x-casaos-tips",
                    "retrieval": None,
                }
            ]
    return []


def _tips(metadata: dict[str, Any]) -> list[str]:
    result: list[str] = []
    tips = metadata.get("tips") or {}
    if not isinstance(tips, dict):
        return result
    for value in tips.values():
        if isinstance(value, dict):
            text = value.get("en_US") or next(iter(value.values()), "")
        else:
            text = value
        if text:
            result.append(str(text))
    return result


def _neutral_localized(value: Any, fallback: str = "") -> dict[str, str]:
    """The source English of a catalog field, with the upstream product name
    neutralised.

    Only the source is kept. Copying the English into a second locale when
    upstream carried no translation made the field look translated, which is
    what stops it from ever being translated. Whatever reaches the reader goes
    through `translate()` instead, like every other string in ProxMenux.
    """
    english = _localized(value, fallback).get("en_US") or fallback
    return {"en_US": re.sub(r"(?:CasaOS|ZimaOS|Zima)", "self-hosted server",
                            english, flags=re.I)}


def _neutral_scalar(value: Any, fallback: str | None = None) -> str | None:
    if value in (None, ""):
        return fallback
    text = re.sub(r"(?:CasaOS|ZimaOS|Zima)", "", str(value), flags=re.I).strip(" -")
    return text or fallback


def _neutralize_discovery_value(value: Any, replacement: str) -> Any:
    if isinstance(value, dict):
        return {
            str(key): item if str(key) == "image" else _neutralize_discovery_value(item, replacement)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_neutralize_discovery_value(item, replacement) for item in value]
    if not isinstance(value, str):
        return value
    return re.sub(r"(?:CasaOS|ZimaOS|Zima)", replacement, value, flags=re.I)


def _environment_entries(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [(str(name), raw) for name, raw in value.items()]
    if isinstance(value, list):
        return [
            (str(item).partition("=")[0], str(item).partition("=")[2])
            for item in value
            if str(item).partition("=")[1]
        ]
    return []


def _secret_binding_ids(services: dict[str, Any]) -> dict[tuple[str, str], str]:
    records: list[tuple[str, str, str, tuple[str, ...]]] = []
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        for name, raw in _environment_entries(service.get("environment")):
            if not SENSITIVE_NAME.search(name):
                continue
            text = str(raw or "")
            reference = re.fullmatch(
                r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}?", text
            )
            normalized_name = normalize_app_id(name)
            database_password_names = {
                "db-password",
                "database-password",
                "postgres-password",
                "postgresql-password",
                "mysql-password",
                "mariadb-password",
            }
            family = "database-password" if normalized_name in database_password_names else normalized_name
            group = (
                ("reference", reference.group(1))
                if reference
                else ("literal", family, text)
            )
            records.append((str(service_name), name, text, group))

    grouped: dict[tuple[str, ...], list[tuple[str, str, str, tuple[str, ...]]]] = {}
    for record in records:
        grouped.setdefault(record[3], []).append(record)

    result: dict[tuple[str, str], str] = {}
    for group, members in grouped.items():
        if group[0] == "reference":
            secret_id = normalize_app_id(group[1])
        elif len(members) > 1:
            names = [normalize_app_id(member[1]) for member in members]
            secret_id = "db-password" if "db-password" in names else min(names, key=len)
        else:
            secret_id = normalize_app_id(members[0][1])
        for service_name, name, _, _ in members:
            result[(service_name, name)] = secret_id
    return result


def _generated_environment(
    value: Any,
    replacement: str,
    service_name: str,
    secret_ids: dict[tuple[str, str], str],
) -> Any:
    def secret_placeholder(name: str) -> str:
        secret_id = secret_ids[(service_name, name)].replace("-", "_").upper()
        return f"${{GENERATED_{secret_id}}}"

    if isinstance(value, dict):
        result = {}
        for name, raw in value.items():
            name = str(name)
            result[name] = (
                secret_placeholder(name)
                if SENSITIVE_NAME.search(name)
                else _neutralize_discovery_value(raw, replacement)
            )
        return result
    if isinstance(value, list):
        result = []
        for raw in value:
            name, separator, setting = str(raw).partition("=")
            if separator and SENSITIVE_NAME.search(name):
                result.append(f"{name}={secret_placeholder(name)}")
            else:
                result.append(_neutralize_discovery_value(raw, replacement))
        return result
    return _neutralize_discovery_value(value, replacement)


def _normalized_compose(compose: dict[str, Any], project_name: str) -> tuple[dict[str, Any], str]:
    normalized = _json_safe(compose)
    normalized.pop("x-casaos", None)
    secret_ids = _secret_binding_ids(compose.get("services") or {})
    for service_name, service in (normalized.get("services") or {}).items():
        if not isinstance(service, dict):
            continue
        service.pop("x-casaos", None)
        if service.get("image"):
            service["image"] = latest_image_reference(str(service["image"]))
        if "environment" in service:
            service["environment"] = _generated_environment(
                service["environment"], project_name, str(service_name), secret_ids
            )
        labels = service.get("labels")
        if labels:
            encoded_labels = str(labels)
            if re.search(r"casaos|zimaos|icewhaletech/casaos-appstore", encoded_labels, re.I):
                service.pop("labels", None)
    normalized = _neutralize_discovery_value(normalized, project_name)
    text = yaml.safe_dump(normalized, sort_keys=False, allow_unicode=False)
    return normalized, text


def _generated_secrets(services: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: dict[str, list[dict[str, str]]] = {}
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        environment = service.get("environment") or {}
        if isinstance(environment, dict):
            entries = [(str(name), str(value or "")) for name, value in environment.items()]
        elif isinstance(environment, list):
            entries = [
                (str(item).partition("=")[0], str(item).partition("=")[2])
                for item in environment
            ]
        else:
            entries = []
        for name, value in entries:
            match = re.fullmatch(r"\$\{GENERATED_([A-Z0-9_]+)\}", value)
            if match:
                bindings.setdefault(match.group(1).casefold().replace("_", "-"), []).append(
                    {"service": str(service_name), "environment_variable": name}
                )
    return [
        {
            "id": secret_id,
            "strategy": "generate-cryptographically-random-at-install",
            "bindings": secret_bindings,
        }
        for secret_id, secret_bindings in sorted(bindings.items())
    ]


def _dependency_names(service: dict[str, Any], service_names: set[str]) -> list[str]:
    value = service.get("depends_on") or []
    names = value.keys() if isinstance(value, dict) else value
    return sorted({str(name) for name in names if str(name) in service_names})


def _service_order(services: dict[str, Any], main_service: str) -> list[str]:
    names = set(services)
    dependencies = {
        str(name): _dependency_names(service, names) if isinstance(service, dict) else []
        for name, service in services.items()
    }
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in ordered or name in visiting:
            return
        visiting.add(name)
        for dependency in dependencies[name]:
            visit(dependency)
        visiting.remove(name)
        ordered.append(name)

    for name in sorted(names - {main_service}):
        visit(name)
    visit(main_service)
    return ordered


def _stack_storage(services: dict[str, Any], markers: dict[str, set[str]]) -> list[dict[str, Any]]:
    storage: list[dict[str, Any]] = []
    shared_targets = re.compile(
        r"^/(?:data|downloads?|media|movies?|music|photos?|pictures?|recordings?|tv|videos?)(?:/|$)|/(?:library|uploads?)(?:/|$)",
        re.I,
    )
    disposable_targets = {"/cache", "/tmp", "/transcode"}
    system_targets = {"/etc/localtime", "/etc/timezone"}
    runtime_targets = {"/var/run/docker.sock", "/run/docker.sock"}
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        mounts = _mount_contract(service.get("volumes"), markers["volumes"])
        for mount in mounts:
            target = mount["container_path"]
            source = mount.get("compose_source_example")
            system_bind = target in system_targets
            runtime_bind = target in runtime_targets
            shareable = bool(
                not system_bind
                and not runtime_bind
                and source
                and str(source).startswith("/")
                and shared_targets.search(target)
            )
            if system_bind:
                mode = "system-bind"
            elif runtime_bind:
                mode = "runtime-bind"
            elif shareable:
                mode = "host-bind"
            else:
                mode = "managed-volume"
            storage.append(
                {
                    "id": f"{normalize_app_id(str(service_name))}-{mount['id']}",
                    "service": str(service_name),
                    "container_path": target,
                    "mode": mode,
                    "user_selectable": shareable,
                    "backup": mode == "managed-volume" and target not in disposable_targets,
                    "shared_with_other_lxc": shareable,
                    "source_path": str(source) if system_bind else None,
                    "source_path_prompt": (
                        f"Host directory for {service_name}:{target}" if shareable else None
                    ),
                }
            )
    return storage


def _compose_stack_contract(
    compose: dict[str, Any],
    normalized_compose: dict[str, Any],
    main_service: str,
    markers: dict[str, set[str]],
) -> dict[str, Any]:
    services = compose["services"]
    names = set(services)
    start_order = _service_order(services, main_service)
    service_contracts = []
    vmid_offsets = {main_service: 0}
    vmid_offsets.update(
        {name: offset for offset, name in enumerate((n for n in start_order if n != main_service), 1)}
    )
    for name in start_order:
        value = services[name]
        normalized_service = normalized_compose["services"][name]
        ports = value.get("ports") or [] if isinstance(value, dict) else []
        service_contracts.append(
            {
                "name": str(name),
                "image": latest_image_reference(str(value.get("image")))
                if isinstance(value, dict) and value.get("image")
                else None,
                "is_main": name == main_service,
                "role": "frontend" if name == main_service else "dependency",
                "vmid_offset": vmid_offsets[name],
                "depends_on": _dependency_names(value, names) if isinstance(value, dict) else [],
                "frontend_network": bool(name == main_service or ports),
                "private_network": len(services) > 1,
                "compose": _json_safe(normalized_service),
            }
        )
    return {
        "project_name": str(compose.get("name") or main_service),
        "deployment_model": "one-native-oci-lxc-per-compose-service",
        "user_experience": "single-application-install",
        "main_service": main_service,
        "service_count": len(services),
        "services": service_contracts,
        "top_level": _json_safe(
            {key: value for key, value in normalized_compose.items() if key != "services"}
        ),
        "networking": {
            "frontend": "selected-proxmox-bridge",
            "private_required": len(services) > 1,
            "private_creation": "automatic-create-if-missing",
            "private_address_allocation": "automatic-static-address-per-service",
            "service_discovery": "private-addresses-with-compose-service-host-aliases",
            "dependency_external_access": "disabled-unless-service-publishes-ports",
            "prompt_user_for_private_network": False,
        },
        "storage": _stack_storage(normalized_compose["services"], markers),
        "orchestration": {
            "reserve_vmids_atomically": len(services),
            "start_order": start_order,
            "stop_order": list(reversed(start_order)),
            "dependency_readiness": "compose-healthcheck-then-port-or-process-fallback",
            "rollback_on_failure": "remove-new-rootfs-preserve-created-persistent-volumes",
        },
        "installer_inputs": {
            "prompted": [
                "stack_name",
                "base_vmid",
                "rootfs_storage",
                "persistent_data_destinations",
                "frontend_bridge",
                "frontend_ipv4_mode",
            ],
            "automatic": [
                "dependent_vmids",
                "private_bridge",
                "private_subnet",
                "private_service_addresses",
                "compose_service_aliases",
                "generated_secrets",
                "dependency_start_and_stop_order",
            ],
            "generated_secrets": _generated_secrets(normalized_compose["services"]),
        },
    }


def _memory_mb(service: dict[str, Any]) -> int:
    value = (((service.get("deploy") or {}).get("resources") or {}).get("reservations") or {}).get("memory")
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMG]?)B?\s*", str(value or ""), re.I)
    if not match:
        return 1024
    number = float(match.group(1))
    unit = match.group(2).upper()
    factors = {"": 1 / (1024 * 1024), "K": 1 / 1024, "M": 1, "G": 1024}
    return max(128, int(number * factors[unit]))


def _blockers(
    compose: dict[str, Any],
    main_service: str,
    optional_devices: set[str] | None = None,
) -> list[str]:
    blockers: list[str] = []
    services = compose.get("services") or {}
    if len(services) > 1:
        blockers.append("multi-service-compose")
    for name, service in services.items():
        if not isinstance(service, dict):
            blockers.append(f"service:{name}:invalid-definition")
            continue
        if not service.get("image"):
            blockers.append(f"service:{name}:missing-image")
        prefix = "" if name == main_service else f"service:{name}:"
        unsupported = set(service) - CASAOS_TRANSLATED_SERVICE_KEYS - {"x-casaos"}
        for key in sorted(unsupported):
            blockers.append(f"{prefix}compose-key:{key}")
        blockers.extend(
            f"{prefix}{item}"
            for item in _compose_option_blockers(
                service,
                optional_devices if name == main_service else None,
            )
        )
    for key in ("configs",):
        if compose.get(key):
            blockers.append(f"top-level-{key}")
    return list(dict.fromkeys(blockers))


def convert_casaos_compose(
    compose_text: str,
    revision: str,
    raw_url: str,
    source_path: str,
    pushed_at: str,
    category: str | None = None,
    category_label: str | None = None,
    catalog_id: str | None = None,
) -> dict[str, Any]:
    compose, metadata, service_name, service = parse_casaos_compose(compose_text)
    summary = summarize_casaos_compose(compose_text, source_path)
    markers = _optional_markers(compose_text)
    ports = _port_contract(service.get("ports"), markers["ports"])
    endpoints = _endpoint(metadata, service)
    primary_endpoint = endpoints[0] if endpoints else None
    raw_category = str(metadata.get("category") or "")
    fallback_category, fallback_label = CASAOS_CATEGORY_MAP.get(raw_category, ("misc", "Miscellaneous"))
    category = category or fallback_category
    category_label = category_label or fallback_label
    stop_grace_period = service.get("stop_grace_period")
    stop_grace_seconds = _duration_seconds(stop_grace_period)
    blockers = _blockers(compose, service_name, markers["devices"])
    if stop_grace_period is not None and stop_grace_seconds is None:
        blockers.append("stop-grace-period-format")
    if service.get("shm_size") is not None and _shm_size_mb(service["shm_size"]) is None:
        blockers.append("shm-size-format")
    services = compose["services"]
    untranslated_blockers = blockers + (
        ["native-multi-lxc-orchestrator-not-yet-implemented"]
        if len(services) > 1
        else []
    )
    project_name = normalize_app_id(str(compose.get("name") or summary["id"]))
    normalized_compose, normalized_compose_text = _normalized_compose(compose, project_name)
    normalized_service = normalized_compose["services"][service_name]
    related_services = [
        {
            "name": str(name),
            "image": str(normalized_compose["services"][name].get("image"))
            if isinstance(value, dict) and value.get("image")
            else None,
        }
        for name, value in services.items()
        if name != service_name
    ]
    definition_hash = hashlib.sha256(normalized_compose_text.encode("utf-8")).hexdigest()
    architectures = summary["architectures"]
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    source_image = str(service["image"])
    image = latest_image_reference(source_image)
    repository_url = image_repository_url(source_image)
    provider = image_provider(summary["distribution"])
    return {
        "schema_version": "0.5.0",
        "kind": "proxmenux.oci-template",
        "id": f"image-{catalog_id or summary['id']}",
        "status": (
            "generated-unvalidated"
            if not untranslated_blockers
            else "generated-review-required"
        ),
        "catalog_ui": {
            "title": _neutral_localized(metadata.get("title"), summary["title"]),
            "tagline": _neutral_localized(metadata.get("tagline"), summary["description"]),
            "description": _neutral_localized(metadata.get("description"), summary["description"]),
            "category": category,
            "category_label": category_label,
            "author": _neutral_scalar(metadata.get("developer"), provider),
            "developer": _neutral_scalar(metadata.get("developer")),
            "icon": None,
            "thumbnail": None,
            "screenshots": [],
            "architectures": architectures,
            "launch": {
                "scheme": primary_endpoint["scheme"] if primary_endpoint else "http",
                "port": primary_endpoint["port"] if primary_endpoint else None,
                "path": primary_endpoint["path"] if primary_endpoint else "/",
            },
            "website": metadata.get("website"),
            "documentation": image_documentation_url(source_image),
            "repository": repository_url,
            "tips": [],
            "mini_changelog": [],
            "display_version": None,
            "updated_at": None,
        },
        "source": {
            "provider": provider,
            "repository": repository_url,
            "revision": definition_hash,
            "image_repository_url": repository_url,
            "readme_pushed_at": pushed_at,
            "compose_sha256": definition_hash,
            "generated_at": generated_at,
        },
        "container_contract": {
            "service_name": service_name,
            "container_name": service.get("container_name", service_name),
            "image": _image_contract(image),
            "environment": [
                {**item, "source": "docker-compose"}
                for item in _environment_contract(
                    normalized_service.get("environment"), markers["environment"]
                )
            ],
            "volumes": _mount_contract(normalized_service.get("volumes"), markers["volumes"]),
            "ports": ports,
            "related_services": [
                {
                    "name": item["name"],
                    "image": item["image"],
                }
                for item in related_services
            ],
            "restart": service.get("restart"),
            "stop_grace_period": None if stop_grace_period is None else str(stop_grace_period),
            "original_compose": normalized_compose_text,
        },
        "compose_stack": _compose_stack_contract(
            compose, normalized_compose, service_name, markers
        ),
        "first_run": {"endpoints": endpoints, "credentials": []},
        "proxmox": {
            "runtime": "native-oci-lxc",
            "technology_status": "proxmox-technology-preview",
            "defaults": {
                "unprivileged": True,
                "ostype": "auto-from-image",
                "cores": 2,
                "memory_mb": _memory_mb(service),
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
                    "id": "imported-compose-source",
                    "upstream_behavior": "The source definition deploys the complete Docker Compose application model.",
                    "native_lxc_behavior": "The source model is preserved and remains blocked until every service option has a reviewed native Proxmox mapping.",
                    "reason": "Catalog import must not imply runtime compatibility.",
                    "behavioral_impact": "No automatic installation before review.",
                    "validation": "pending-per-application",
                },
                {
                    "id": "rolling-latest-image",
                    "upstream_behavior": "A discovered Compose may pin a release tag or digest.",
                    "native_lxc_behavior": "ProxMenux selects the same image repository with the latest tag for catalog installations.",
                    "reason": "The automatic catalog intentionally offers rolling latest images; pinned versions belong to the future manual installer.",
                    "behavioral_impact": "The installed release can be newer than the discovered Compose revision.",
                    "validation": "pending-per-application",
                },
                {
                    "id": "dedicated-lxc-network",
                    "upstream_behavior": "Docker publishes selected container ports on the Docker host.",
                    "native_lxc_behavior": "A reviewed native application will listen on its original container ports at a dedicated LXC address.",
                    "reason": "A native LXC has its own address and does not require Docker port NAT.",
                    "behavioral_impact": "Published ports are metadata; ProxMenux URLs use the matching container target port.",
                    "validation": "pending-per-application",
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
                {
                    "id": "compose-privileged-mode",
                    "upstream_behavior": "Compose selects whether the container runs in privileged mode.",
                    "native_lxc_behavior": "ProxMenux keeps the LXC unprivileged by default and exposes the broad Compose privilege request only as an explicit compatibility option.",
                    "reason": "A Compose privilege request is source metadata, not proof that the image technically requires a privileged LXC.",
                    "behavioral_impact": "A privileged LXC has weaker isolation from the Proxmox host.",
                    "validation": "optional-explicit-user-consent" if _compose_requests_privileged_lxc(service) else "native-equivalent",
                },
                *_compose_runtime_adaptations(service),
            ],
        },
        "compatibility": {
            "automatic_install_candidate": not untranslated_blockers,
            "validated": False,
            "supported_compose_keys": sorted(CASAOS_TRANSLATED_SERVICE_KEYS),
            "untranslated_blockers": untranslated_blockers,
            "policy": "Single-image definitions are installable when every declared Compose option has a native Proxmox translation. Multi-image and unsupported runtime features remain blocked until their orchestrator or mapping is available.",
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
            "update_strategy": "resolve-latest-image-then-apply-reviewed-native-lxc-update",
            "registry_state": {
                "resolved_architecture": None,
                "resolved_digest": None,
                "image_version_label": None,
                "image_created": None,
            },
            "change_detection": "compare-compose-sha256-and-resolved-latest-image-digest",
            "automatic_unattended_updates": False,
        },
    }
