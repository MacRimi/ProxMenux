"""OCI manager Apps: catalog menus, installation flow and maintenance commands."""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import unicodedata
from pathlib import Path
from typing import Any

from . import console, images
from .catalog import Catalog
from .converter import ConversionError
from .github_source import SourceError
from .i18n import N_, source_text, translate
from .installer import (
    ADVANCED_MODE,
    DEFAULT_MODE,
    InstallError,
    build_deployment,
    build_rclone_mount_deployment,
    redacted,
    run_remote_install,
    run_remote_rclone_mount,
)
from .ui import APP_TITLE, UserCancelled, interactive_ui


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISPLAY_ARCHITECTURES = ("amd64", "arm64")
PUBLISHERS = {"linuxserver.io": "LinuxServer", "official": N_("Official image")}
STACK_LABELS = {
    "server": N_("Server"),
    "application": N_("Application"),
    "machine_learning": N_("Machine learning"),
    "database": "PostgreSQL",
    "valkey": "Valkey",
    "cache": "Redis",
    "paperless": "Paperless-ngx",
    "broker": "Valkey",
    "tandoor": "Tandoor",
}


def _display_architectures(item: dict[str, Any]) -> str:
    supported = [a for a in DISPLAY_ARCHITECTURES if a in item.get("architectures", [])]
    return "/".join(supported) or "?"


def publisher(item: dict[str, Any]) -> str:
    provider = str(item.get("provider") or "")
    app_id = str(item.get("id") or "").casefold()
    # A project that publishes its own image (immich, frigate, nextcloud...) is its official image.
    if provider == "official" or (provider and app_id.startswith(provider.casefold())):
        return translate(PUBLISHERS["official"])
    return PUBLISHERS.get(provider, provider or "?")


def is_tested(item: dict[str, Any]) -> bool:
    return item.get("template_status") == "laboratory-validated"


MENU_SIZE = (22, 75, 15)
MULTI_LABEL = r"\Z4MULTI\Zn"
TESTED_LABEL = r"\Z2✓\Zn"


def _installable(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in applications if not item.get("hidden") and item.get("automatic_install_candidate")]


NAME_WIDTH, ARCH_WIDTH, SOURCE_WIDTH = 26, 12, 14
ROW_WIDTH = 72


def _app_menu(applications: list[dict[str, Any]], keep_order: bool = False
              ) -> tuple[list[tuple[str, str]], dict[str, dict[str, Any]], str]:
    """Numbered rows in the Helper Scripts layout (name, architecture, source,
    verified) and the column header aligned with them."""
    options: list[tuple[str, str]] = []
    index: dict[str, dict[str, Any]] = {}
    ordered = applications if keep_order else sorted(
        applications, key=lambda entry: str(entry.get("title") or entry["id"]).casefold())
    for number, item in enumerate(ordered, 1):
        title = str(item.get("title") or item["id"])
        name = " ".join("".join(ch for ch in title if unicodedata.category(ch) != "So").split())
        if item.get("multi_container"):
            name = name[:NAME_WIDTH - 6]
            cell = f"{name} {MULTI_LABEL}" + " " * (NAME_WIDTH - len(name) - 6)
        else:
            cell = f"{name[:NAME_WIDTH]:<{NAME_WIDTH}}"
        row = f"{cell} {_display_architectures(item):<{ARCH_WIDTH}} {publisher(item)[:SOURCE_WIDTH]:<{SOURCE_WIDTH}}"
        if is_tested(item):
            row += f" {TESTED_LABEL}"
        # Rows as wide as the list: dialog centers narrower lists, which would move them off the header.
        options.append((str(number), f"{row:<{ROW_WIDTH}}"))
        index[str(number)] = item
    # dialog draws the rows after the list border and the tag column.
    offset = " " * (len(str(len(ordered))) + 3)
    header = (f"{offset}{translate('Name')[:NAME_WIDTH]:<{NAME_WIDTH}} "
              f"{translate('Architecture')[:ARCH_WIDTH]:<{ARCH_WIDTH}} "
              f"{translate('Source')[:SOURCE_WIDTH]:<{SOURCE_WIDTH}} {translate('Verified')}")
    return options, index, header


def _yes_no(value: Any) -> str:
    return translate("yes") if value else translate("no")


# ---------------------------------------------------------------- summaries

DETAIL_WIDTH = 92
SERVICE_KINDS = (("postgres", "PostgreSQL"), ("valkey", "Valkey"), ("redis", "Redis"), ("mariadb", "MariaDB"),
                 ("mysql", "MySQL"), ("mongo", "MongoDB"), ("meilisearch", "Meilisearch"))


def _image_label(reference: str) -> str:
    return str(reference or "").split("@", 1)[0]


def _service_kind(service: dict[str, Any]) -> str:
    image = str(service.get("image") or "").casefold()
    name = str(service.get("name") or "").casefold()
    if service.get("is_main"):
        return translate("Application")
    if "machine-learning" in name or "machine-learning" in image:
        return translate("Machine learning")
    for key, label in SERVICE_KINDS:
        if key in image:
            return label
    return translate("Service")


def _recommended_storage(volume: dict[str, Any]) -> str:
    """What the installation uses for this path, and the alternative when the
    user can choose; the recommended one comes first."""
    choices = set(volume.get("installation_choice", []))
    default = volume.get("default")
    if {"managed-volume", "host-bind"} <= choices:
        both = f"{translate('Container volume')} / {translate('Host directory')}"
        return f"{translate('Optional')}: {both}" if default == "skip" else both
    if default == "skip":
        return translate("Optional, not mounted by default")
    return translate("Host system path") if default == "host-bind" else translate("Container volume")


def _app_detail_text(catalog: Catalog, item: dict[str, Any], template: dict[str, Any]) -> str:
    ui = template["catalog_ui"]
    contract = template["container_contract"]
    profile = template.get("proxmox", {}).get("installer_profile", {})
    lines = [rf"\Zb{source_text(ui.get('title')) or item['id']}\Zn", ""]
    # The one-line tagline, not the full upstream description: it is what the
    # reader needs to know what this is, it survives translation without
    # drifting, and it goes through translate() like every other string.
    description = translate(source_text(ui.get("tagline")) or source_text(ui.get("description")))
    if description:
        wrapped = textwrap.wrap(description, DETAIL_WIDTH)
        if len(wrapped) > 8:
            wrapped = wrapped[:8]
            wrapped[-1] = wrapped[-1].rstrip(" .,;") + "…"
        lines += wrapped + [""]

    def row(label: str, value: str) -> None:
        lines.append(f"{label + ':':<17} {value}")

    row(translate("Source"), publisher(item))
    row(translate("Status"), translate("Verified by ProxMenux") if is_tested(item)
        else translate("Not yet verified by ProxMenux (beta)"))
    row(translate("Architectures"), _display_architectures(ui))
    endpoints = template.get("first_run", {}).get("endpoints", [])
    if endpoints:
        row(translate("Web access"), ", ".join(
            f"{e.get('scheme', 'http')}://<IP>:{e.get('port')}{e.get('path') or '/'}" for e in endpoints))

    if profile.get("stack_driver") == "arr-suite":
        row(translate("Type"), translate("Application suite: one independent LXC per selected application"))
        defaults = set(profile.get("default_applications") or ("prowlarr", "sonarr", "radarr", "qbittorrent"))
        lines += ["", translate("Applications you can choose:")]
        for app_id in profile.get("applications") or []:
            try:
                child = catalog.compose(app_id)
                image = child["container_contract"]["image"]["reference"]
                name = source_text(child["catalog_ui"]["title"]) or app_id
            except (ConversionError, OSError, ValueError, KeyError):
                image, name = "", app_id
            mark = f" ({translate('selected by default')})" if app_id in defaults else ""
            lines.append(f"  {name + mark:<34} {_image_label(image)}")
        lines.append(f"  {translate('Media server') + ':':<34} Jellyfin, Plex, Emby {translate('or none')}")
    elif item.get("multi_container"):
        services = template.get("compose_stack", {}).get("services", [])
        row(translate("Type"), translate("Multi-container application (experimental)"))
        lines += ["", translate("Containers that will be created (one LXC per service, on a private network):")]
        for service in services:
            lines.append(f"  {_service_kind(service):<20} {_image_label(service.get('image'))}")
    else:
        row(translate("Image"), _image_label(contract["image"]["reference"]))
        volumes = contract.get("volumes", [])
        if volumes:
            width = max(28, *(len(volume["container_path"]) + 2 for volume in volumes))
            lines += ["", f"{translate('Persistent data:'):<{width + 2}} {translate('Recommended')}"]
            for volume in volumes:
                lines.append(f"  {volume['container_path']:<{width}} {_recommended_storage(volume)}")
            if any({"managed-volume", "host-bind"} <= set(volume.get("installation_choice", []))
                   for volume in volumes):
                lines.append(translate("The installation asks which one to use for these paths."))

    hardware = profile.get("hardware_acceleration", {}).get("profiles", [])
    if hardware:
        lines += ["", translate("Hardware acceleration options:")]
        lines += [f"  {' '.join(translate(p.get('label', p['id'])).split())}" for p in hardware]
    security = template.get("proxmox", {}).get("security_profile", {})
    if security.get("requires_privileged_lxc"):
        lines += ["", f"{translate('Security') + ':':<17} {translate('needs a privileged LXC')}"]
    elif security.get("requires_relaxed_confinement"):
        lines += ["", f"{translate('Security') + ':':<17} {translate('needs a relaxed AppArmor or seccomp profile')}"]
    return "\n".join(lines)


def _deployment_summary_text(template: dict[str, Any], deployment: dict[str, Any]) -> str:
    plan = redacted(deployment)
    title = source_text(template["catalog_ui"]["title"]) or template["id"]
    lines = [title, ""]

    def row(label: str, value: Any) -> None:
        lines.append(f"{label + ':':<16} {value}")

    on = translate("on")
    if plan.get("suite_arr"):
        lines.append(translate("Independent applications, without a main container."))
    else:
        row(translate("Image"), template["container_contract"]["image"]["reference"])

    if plan.get("deployment_kind"):
        base_vmid = plan.get("base_vmid")
        row(translate("Stack"), plan.get("stack_name", title))
        row(translate("Base VMID"), base_vmid if base_vmid is not None else translate("next free block"))
        services = template.get("compose_stack", {}).get("services", [])
        if plan.get("deployment_kind") == "generic-multi-lxc-stack":
            services = [dict(s, vmid_offset=s["offset"]) for s in plan["services"]]
        for service in sorted(services, key=lambda item: item.get("vmid_offset", 0)):
            offset = service.get("vmid_offset", 0)
            vmid = base_vmid + offset if base_vmid is not None else f"base+{offset}"
            lines.append(f"  - {service['name']}: CT {vmid}")
        lines.append("")
        row("Rootfs", plan.get("rootfs_storage", "-"))
        row(translate("Image cache"), plan.get("template_storage", "-"))
        if plan.get("database_storage"):
            row("PostgreSQL", f"{plan.get('database_size_gb', '-')} GB {on} {plan['database_storage']}")
        for service in plan.get("services", []):
            child = service["deployment"]
            lines.append(f"  {service['name']}: {child['resources']['cores']} CPU, "
                         f"{child['resources']['memory_mb']} MB RAM")
            for mount in child["mounts"]:
                target = (f"{mount['size_gb']} GB {on} {mount['source']}"
                          if mount["type"] == "managed-volume" else mount["source"])
                lines.append(f"    {mount['container_path']} → {target}")
        for key, label in (("media", "Library"), ("application", "Application data"), ("transfer", "Consume/export")):
            storage = plan.get(key)
            if isinstance(storage, dict) and "mode" in storage:
                if storage["mode"] == "host-bind":
                    row(translate(label), f"{translate('host directory')} {storage.get('host_path', '-')}")
                else:
                    row(translate(label), f"{storage.get('size_gb', '-')} GB {on} {storage.get('storage', '-')}")
    else:
        row(translate("Container"), f"CT {plan.get('vmid') or translate('next free')} · {plan.get('hostname', '-')}")

    resources = plan.get("resources", {})
    if resources:
        row(translate("Resources"), f"{resources.get('cores', '-')} CPU · {resources.get('memory_mb', '-')} MB RAM · "
                                    f"{resources.get('swap_mb', '-')} MB swap")
    rootfs = plan.get("rootfs")
    if rootfs:
        row(translate("Storage"), f"rootfs {rootfs['size_gb']} GB {on} {rootfs['storage']} · "
                                  f"{translate('image cache on')} {plan.get('template_storage', '-')}")
    mounts = plan.get("mounts", [])
    if mounts:
        lines.append(f"{translate('Data') + ':':<16}")
        for mount in mounts:
            if mount["type"] == "host-bind":
                target = f"{translate('host directory')} {mount['source']}"
            else:
                target = f"{translate('Container volume')} {mount.get('size_gb', '-')} GB {on} {mount['source']}"
                if mount.get("backup"):
                    target += f" ({translate('in backups')})"
            if mount.get("read_only"):
                target += f" ({translate('read-only')})"
            lines.append(f"  {mount['container_path']} → {target}")
    network = plan.get("network", {})
    if plan.get("host_monitor"):
        row(translate("Network"), translate("IP address and firewall of the host"))
    elif "frontend_bridge" in network:
        addresses = [network[key] for key in ("frontend_ipv4", "machine_learning_frontend_ipv4") if network.get(key)]
        addresses += [service["frontend_ipv4"] for service in plan.get("services", []) if service.get("frontend_ipv4")]
        static = [address for address in addresses if address != "dhcp"]
        row(translate("Network"), f"{network['frontend_bridge']} · {', '.join(static) if static else 'DHCP'}"
                                  + (f" · gw {network['frontend_gateway']}" if network.get("frontend_gateway") else "")
                                  + f" · {translate('private network assigned automatically')}")
    elif network:
        ipv4 = network.get("ipv4", "dhcp")
        row(translate("Network"), f"{network.get('bridge', '-')} · {'DHCP' if ipv4 == 'dhcp' else ipv4}"
                                  + (f" · gw {network['gateway']}" if network.get("gateway") else ""))
    devices = plan.get("devices", [])
    if plan.get("hardware_profile") or devices:
        profiles = (template.get("proxmox", {}).get("installer_profile", {})
                    .get("hardware_acceleration", {}).get("profiles", []))
        selected = next((p for p in profiles if p["id"] == plan.get("hardware_profile")), None)
        profile_label = (translate(selected["label"]).split("  ")[0] if selected
                         else plan.get("hardware_profile") or translate("custom"))
        row(translate("Acceleration"),
            ", ".join([profile_label, *[d.get("host_path") or d.get("kind", "-") for d in devices]]))
    security = plan.get("security")
    if security:
        row(translate("Security"),
            translate("unprivileged LXC") if security.get("unprivileged") else translate("privileged LXC"))
    environment = plan.get("environment", [])
    if environment:
        row(translate("Variables"), ", ".join(f"{item['name']}={item['value']}" for item in environment))
    if plan.get("suite_arr"):
        lines += ["", *[translate(note) for note in plan.get("completion_notes", [])]]
    lines.append("")
    row(translate("Start"), f"{translate('when finished')}: {_yes_no(plan.get('start_after_create'))} · "
                            f"{translate('with Proxmox')}: {_yes_no(plan.get('onboot'))}")
    return "\n".join(lines)


def _print_installation_summary(result: dict[str, Any], images_removed: str | None = None) -> None:
    console.msg_title(translate("Installation completed"))
    if result.get("suite_arr"):
        console.msg_ok(translate("Independent LXC applications installed"))
    else:
        console.msg_ok(f"CT {result['vmid']} · {translate('IP address')}: "
                       f"{result.get('ip') or translate('not available yet')}")
    for name, vmid in (result.get("stack_vmids") or {}).items():
        console.msg_ok(f"{translate(STACK_LABELS.get(name, name))}: CT {vmid}")
    for item in result.get("urls") or []:
        console.msg_ok(f"{translate(item['label'])}: {item['url']}")
    for item in result.get("credentials") or []:
        console.msg_info2(translate(item["label"]))
        username = str(item["username"])
        console.msg_ok(f"{translate('User')}: {translate(username) if ' ' in username else username}")
        if item.get("password") is not None:
            console.msg_ok(f"{translate('Password')}: {item['password'] or translate('(empty)')}")
        else:
            console.msg_warn(translate("The password could not be retrieved automatically"))
        if item.get("change_required"):
            console.msg_warn(translate("Change it after the first login."))
    if images_removed:
        console.msg_ok(images_removed)
    for note in result.get("completion_notes") or []:
        console.msg_note(translate(note))
    if result.get("log"):
        console.msg_note(f"{translate('Installation log:')} {result['log']}")
    print()
    console.msg_note(translate("OCI manager Apps is a beta: if something does not work as expected, "
                               "please report it on GitHub with the application name."))


# ---------------------------------------------------------------- menus

def _install(catalog: Catalog, ui, item: dict[str, Any], mode: str) -> None:
    install_template(ui, catalog.compose(item["id"]), item["id"], mode)


def install_template(ui, template: dict[str, Any], identifier: str, mode: str) -> dict[str, Any] | None:
    """Configures and installs one template, from the catalog or written from a
    definition the user gave."""
    from .ui import BacktrackUI, RestartWizard
    wizard = BacktrackUI(ui)
    try:
        while True:
            candidate = copy.deepcopy(template)
            try:
                deployment = build_deployment(candidate, wizard, mode)
                approved = wizard.review(_deployment_summary_text(candidate, deployment),
                                         translate("Installation summary"),
                                         question=translate("Install with this configuration?"))
                break
            except RestartWizard:
                wizard.restart()
    finally:
        wizard.close()
    if not approved:
        return None
    template = candidate
    console.show_logo()
    console.msg_title(f"{source_text(template['catalog_ui']['title']) or identifier} · {APP_TITLE}")
    try:
        result = run_remote_install(PROJECT_ROOT, template, deployment, "auto")
    except InstallError as exc:
        console.msg_error(str(exc))
        console.wait_for_enter(translate("Press Enter to return to the menu..."))
        return None
    if result:
        vmids = {int(v) for v in [result.get("vmid"), *(result.get("stack_vmids") or {}).values()] if v}
        _, removed = images.offer_removal(ui, sorted(vmids))
        _print_installation_summary(result, removed)
    console.wait_for_enter(translate("Press Enter to return to the menu..."))
    return result


def _rclone_mount(catalog: Catalog, ui) -> None:
    template = catalog.compose("rclone")
    deployment = build_rclone_mount_deployment(template, ui)
    console.show_logo()
    console.msg_title(translate("Rclone mount"))
    result = run_remote_rclone_mount(PROJECT_ROOT, template, deployment, "auto")
    if result:
        console.msg_ok(f"Remote: {result['remote']}:")
        console.msg_ok(f"{translate('Read/write')}: {result['read_write_path']}")
        console.msg_ok(f"{translate('Read-only')}: {result['read_only_path']}")
    console.wait_for_enter(translate("Press Enter to return to the menu..."))


def _app_detail(catalog: Catalog, ui, item: dict[str, Any]) -> None:
    template = catalog.compose(item["id"])
    actions = []
    actions += [("default", translate("Install with default settings")),
                ("advanced", translate("Install with advanced settings"))]
    if item["id"] == "rclone":
        actions.append(("mount", translate("Enable a mount on an existing Rclone OCI container")))
    numbered = {str(number): action for number, (action, _) in enumerate(actions, 1)}
    options = [(str(number), label) for number, (_, label) in enumerate(actions, 1)]
    title = source_text(template["catalog_ui"]["title"]) or item["id"]
    selection = ui.detail_menu(_app_detail_text(catalog, item, template), options, "1", title=title)
    action = numbered.get(selection or "")
    if action is None:
        return
    if action == "mount":
        _rclone_mount(catalog, ui)
        return
    _install(catalog, ui, item, DEFAULT_MODE if action == "default" else ADVANCED_MODE)


def _app_list(catalog: Catalog, ui, applications: list[dict[str, Any]], title: str,
              keep_order: bool = False) -> None:
    options, index, header = _app_menu(applications, keep_order)
    selection = None
    while True:
        selection = ui.choose(header, options, selection, title=title, size=MENU_SIZE, colors=True)
        if selection is None:
            return
        if selection in index:
            _app_detail(catalog, ui, index[selection])


def _search(catalog: Catalog, ui, applications: list[dict[str, Any]]) -> None:
    query = ui.ask(translate("Name or part of the description of the application"), required=False).strip()
    if not query:
        return
    folded = query.casefold()

    def rank(item: dict[str, Any]) -> int | None:
        names = (item["id"].casefold(), str(item.get("title") or "").casefold())
        if folded in names:
            return 0
        if any(name.startswith(folded) for name in names):
            return 1
        if any(folded in name for name in names):
            return 2
        return 3 if folded in str(item.get("description") or "").casefold() else None

    ranked = sorted(((rank(item), str(item.get("title") or item["id"]).casefold(), item) for item in applications
                     if rank(item) is not None), key=lambda entry: entry[:2])
    matches = [item for _, _, item in ranked]
    if not matches:
        ui.message(f"{translate('No applications match')}: '{query}'")
        return
    _app_list(catalog, ui, matches, f"{translate('Search results for:')} '{query}' ({len(matches)})",
              keep_order=True)


def interactive(catalog: Catalog) -> int:
    ui = interactive_ui()
    if not catalog.index_path.exists():
        ui.message(translate("The OCI catalog is not installed. Update ProxMenux and try again."))
        return 1
    applications = _installable(catalog.load_index()["applications"])
    categories: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for item in applications:
        key = item.get("category") or "misc"
        categories.setdefault(key, []).append(item)
        labels[key] = item.get("category_label") or key
    order = sorted(categories, key=lambda key: (key == "misc", translate(labels[key]).casefold()))
    category_by_index = {str(number): key for number, key in enumerate(order, 1)}
    options = [
        ("search", translate("Search applications")),
        ("all", f"{translate('All applications'):<35} ({len(applications):>3})"),
        ("manage", translate("Manage installed OCI applications")),
        ("custom", translate("Install an image that is not in the catalog")),
        ("", ""),
    ] + [(number, f"{translate(labels[key]):<35} ({len(categories[key]):>3})")
         for number, key in category_by_index.items()]
    selection = "search"
    while True:
        selection = ui.choose(translate("Select a category or search for applications:"), options, selection,
                              size=MENU_SIZE)
        if selection is None:
            return 0
        try:
            if selection == "search":
                _search(catalog, ui, applications)
            elif selection == "all":
                _app_list(catalog, ui, applications,
                          f"{translate('All applications')} ({len(applications)})")
            elif selection == "manage":
                from .management import interactive_management
                interactive_management(PROJECT_ROOT, ui)
            elif selection == "custom":
                from .custom import explore
                explore(ui)
            elif selection in category_by_index:
                key = category_by_index[selection]
                _app_list(catalog, ui, categories[key], translate(labels[key]))
        except UserCancelled:
            continue
        except (ConversionError, InstallError, OSError, ValueError) as exc:
            console.stop_spinner()
            ui.message(f"{translate('The operation could not be completed')}:\n\n{exc}")


# ---------------------------------------------------------------- maintenance CLI

def _template_summary_text(template: dict[str, Any]) -> str:
    contract = template["container_contract"]
    lines = [
        source_text(template["catalog_ui"]["title"]),
        f"Image: {contract['image']['reference']}",
        f"Status: {template['status']}",
        "Ports: " + (", ".join(f"{p['container_port']}/{p['protocol']}" for p in contract["ports"]) or "none"),
        "Volumes: " + (", ".join(v["container_path"] for v in contract["volumes"]) or "none"),
    ]
    blockers = template["compatibility"]["untranslated_blockers"]
    if blockers:
        lines.append(f"Blockers: {', '.join(blockers)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oci_manager_apps.sh",
                                     description="ProxMenux OCI manager Apps (beta)")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("sync", help="Refresh the index from the image sources")
    list_parser = subparsers.add_parser("list", help="List applications")
    list_parser.add_argument("--filter", default="")
    generate_parser = subparsers.add_parser("generate", help="Regenerate the template of one application")
    generate_parser.add_argument("app")
    generate_all_parser = subparsers.add_parser("generate-all", help="Regenerate the catalog templates")
    generate_all_parser.add_argument("--provider", choices=["all", "linuxserver.io", "imported", "curated"],
                                     default="all")
    subparsers.add_parser("apply-icons", help="Resolve catalog icons against the jsdelivr icon sets")
    show_parser = subparsers.add_parser("show", help="Show the summary of a template")
    show_parser.add_argument("app")
    install_parser = subparsers.add_parser("install", help="Configure and install an application")
    install_parser.add_argument("app")
    install_parser.add_argument("--host", default="auto", help="'auto'/'local', or root@IP for development")
    install_parser.add_argument("--advanced", action="store_true")
    install_parser.add_argument("--dry-run", action="store_true")
    rclone_parser = subparsers.add_parser("rclone-mount", help="Enable a mount on an installed Rclone OCI")
    rclone_parser.add_argument("--host", default="auto")
    rclone_parser.add_argument("--dry-run", action="store_true")
    manage_parser = subparsers.add_parser("manage", help="Update or recreate one installed OCI instance")
    manage_parser.add_argument("vmid", type=int)
    manage_parser.add_argument("--action", choices=("update", "recreate"), required=True)
    manage_parser.add_argument("--keep-backup", metavar="STORAGE",
                               help="Keep the backup taken before the update in this Proxmox storage")
    manage_parser.add_argument("--unattended", action="store_true",
                               help="Scheduled run: no questions; stops where a person has to decide")
    manage_parser.add_argument("--acknowledge-external-data", action="store_true",
                               help="Host directories are not reverted by the backup (confirmed beforehand)")
    manage_parser.add_argument("--min-image-age-days", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = Catalog(PROJECT_ROOT)
    try:
        if not args.command:
            return interactive(catalog)
        if args.command == "sync":
            payload = catalog.sync_index()
            print(f"Index updated: {len(payload['applications'])} candidate applications")
            return 0
        if args.command == "list":
            query = args.filter.casefold()
            for item in catalog.load_index()["applications"]:
                if not item.get("hidden", False) and query in item["id"].casefold():
                    candidate = item.get("automatic_install_candidate")
                    status = ("installable" if candidate else "pending adaptation" if candidate is False
                              else item.get("template_status") or "not generated")
                    print(f"{item['id']:<30} {_display_architectures(item):<12} {publisher(item):<14} {status}")
            return 0
        if args.command == "generate":
            path, template = catalog.generate(args.app)
            print(f"{_template_summary_text(template)}\n\n{path}")
            return 0
        if args.command == "generate-all":
            def progress(current: int, total: int, app_id: str, outcome: str) -> None:
                marker = "OK" if outcome == "ok" else "ERROR"
                print(f"\r[{current:3}/{total}] {marker:<5} {app_id:<32}", end="", flush=True)

            report = catalog.generate_all(progress=progress, provider=args.provider)
            print(f"\nGenerated: {report['generated_count']}; failed: {report['failed_count']}; "
                  f"family: {args.provider}")
            return 0 if not report["failed"] else 2
        if args.command == "apply-icons":
            report = catalog.apply_icons()
            print(f"Icons resolved: {report['resolved']}; cleared: {report['cleared']}; "
                  f"unchanged: {report['unchanged']}; with a theme variant: {report['themed']}")
            return 0
        if args.command == "show":
            print(_template_summary_text(catalog.compose(args.app)))
            return 0
        if args.command == "install":
            template = catalog.compose(args.app)
            if not template["compatibility"]["automatic_install_candidate"]:
                raise InstallError("Installation blocked: " + ", ".join(template["compatibility"]["untranslated_blockers"]))
            deployment = build_deployment(template, None, ADVANCED_MODE if args.advanced else DEFAULT_MODE)
            print(_deployment_summary_text(template, deployment))
            if not args.dry_run and input("\nInstall? [y/N]: ").strip().casefold() not in {"y", "yes"}:
                print("Installation cancelled.")
                return 0
            result = run_remote_install(PROJECT_ROOT, template, deployment, args.host, args.dry_run)
            if result:
                _print_installation_summary(result)
            return 0
        if args.command == "manage":
            from .management import direct_management
            lifecycle_args = []
            if args.keep_backup:
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.keep_backup):
                    raise InstallError(translate("Invalid storage name"))
                lifecycle_args += ["--keep-backup", args.keep_backup]
            if args.acknowledge_external_data:
                lifecycle_args.append("--acknowledge-external-data")
            return direct_management(PROJECT_ROOT, args.vmid, args.action, lifecycle_args,
                                     args.unattended, max(0, args.min_image_age_days))
        if args.command == "rclone-mount":
            template = catalog.compose("rclone")
            deployment = build_rclone_mount_deployment(template)
            print(json.dumps(deployment, ensure_ascii=False, indent=2))
            result = run_remote_rclone_mount(PROJECT_ROOT, template, deployment, args.host, args.dry_run)
            if result:
                print(f"Read/write: {result['read_write_path']}\nRead-only: {result['read_only_path']}")
            return 0
        return 1
    except (KeyboardInterrupt, UserCancelled):
        console.stop_spinner()
        print(f"\n{translate('Operation cancelled.')}")
        return 130
    except (ConversionError, SourceError, InstallError, OSError, ValueError) as exc:
        console.stop_spinner()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
