"""Items of the Monitor's Catalog tab.

The tab lists, in one place, the applications of the OCI catalog the engine is
using and the scripts of Community Scripts, and opens a sheet for each one.
Nothing here installs anything: the sheet's button runs the same terminal flow
as the menu.
"""
from __future__ import annotations

import copy
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request

import lxc_apps
import managed_installs

# Two spellings the OCI index still carries for categories that Community
# Scripts names in full, and a category of Community Scripts that ProxMenux
# lists inside a wider one, as its menu does. An installed script keeps the
# category Community Scripts gives it.
_CATEGORY_ALIASES = {"Monitoring": "Monitoring & Analytics", "Media": "Media & Streaming",
                     "ZigBee, Z-Wave & Matter": "IoT & Smart Home"}
_SCRIPT_TYPES = {"lxc": "lxc", "vm": "vm", "pve": "host", "addon": "addon", "turnkey": "lxc"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_scripts_lock = threading.Lock()
_scripts_cache: tuple[float, list] | None = None
_SCRIPTS_TTL = 6 * 3600
_SCRIPTS_DISK = "/var/lib/proxmenux/catalog_scripts.json"

_details_lock = threading.Lock()
_details_cache: dict[str, tuple[float, dict]] = {}
_DETAILS_TTL = 24 * 3600
_POCKETBASE = "https://db.community-scripts.org/api/collections/script_scripts/records"


_LANG_DIR = "/usr/local/share/proxmenux/lang"
_lang_lock = threading.Lock()
_lang_cache: dict[str, tuple[float, dict]] = {}


def _translations(language: str) -> dict:
    """The translations the ProxMenux menu uses for the catalog texts, so the
    tab shows a tagline in the same words as the menu."""
    if language == "en":
        return {}
    with _lang_lock:
        cached = _lang_cache.get(language)
        if cached and time.time() - cached[0] < 600:
            return cached[1]
    loaded = _read_json(os.path.join(_LANG_DIR, f"{language}.json"))
    table = loaded if isinstance(loaded, dict) else {}
    with _lang_lock:
        _lang_cache[language] = (time.time(), table)
    return table


def _tr(table: dict, text) -> str:
    text = str(text or "").strip()
    value = table.get(text)
    return value.strip() if isinstance(value, str) and value.strip() else text


def _category(value) -> str:
    value = str(value or "").strip()
    return _CATEGORY_ALIASES.get(value, value) or "Miscellaneous"


_TAG = re.compile(r"<[^>]+>")


def _plain(value) -> str:
    """Community Scripts writes some texts in HTML; the sheet shows plain text."""
    text = html.unescape(_TAG.sub(" ", str(value or "")))
    return re.sub(r"[ \t]+", " ", text).strip()


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# OCI catalog
# ---------------------------------------------------------------------------

def _oci_index() -> list:
    data = _read_json(os.path.join(lxc_apps.oci_catalog_dir(), "index.json")) or {}
    return [item for item in data.get("applications", []) if isinstance(item, dict)]


def _publisher(item: dict) -> dict:
    """Who publishes the image: the project itself, LinuxServer.io or another
    publisher, by the same rule as the OCI menu."""
    provider = str(item.get("provider") or "")
    app_id = str(item.get("id") or "").casefold()
    if provider == "official" or (provider and app_id.startswith(provider.casefold())):
        return {"kind": "official", "name": ""}
    if provider in ("linuxserver.io", "linuxserver"):
        return {"kind": "linuxserver", "name": "LinuxServer.io"}
    return {"kind": "other", "name": provider}


def _oci_item(item: dict, table: dict | None = None) -> dict:
    tested = (item.get("template_status") == "laboratory-validated"
              or bool((item.get("community_tested") or {}).get("by")))
    return {
        "key": f"oci:{item['id']}",
        "kind": "oci",
        "id": item["id"],
        "name": item.get("title") or item["id"],
        "summary": _tr(table or {}, item.get("description")),
        "icon": item.get("icon") or "",
        "category": _category(item.get("category_label")),
        "architectures": item.get("architectures") or [],
        "group": "app",
        # An application of several services installs one LXC for each.
        "containers": _catalog_recipes()[2].get(item["id"], 1),
        "multi": bool(item.get("multi_container")) or _catalog_recipes()[2].get(item["id"], 1) > 1,
        "publisher": _publisher(item),
        "shot": _shot(f"oci:{item['id']}"),
        "tested": tested,
        "privileged": bool(item.get("requires_privileged_lxc")),
    }


def _deep_merge(target: dict, overlay: dict) -> None:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _oci_template(item: dict) -> dict:
    """The recipe of an application with its overlay applied, as the engine
    composes it, limited to what the sheet shows."""
    root = lxc_apps.oci_catalog_dir()
    relative = item.get("template") or ""
    if not relative and str(item.get("curated_path") or "").startswith("catalog/"):
        relative = item["curated_path"][len("catalog/"):]
    template = _read_json(os.path.join(root, relative)) if relative else None
    template = template if isinstance(template, dict) else {}
    overlay = _read_json(os.path.join(root, "overlays", f"{item['id']}.json"))
    if isinstance(overlay, dict):
        overlay = {k: v for k, v in overlay.items() if k not in ("environment_overrides", "environment_additions")}
        _deep_merge(template, overlay)
    return template


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("en_US") or next(iter(value.values()), "") or "").strip()
    return str(value or "").strip()


_shots_lock = threading.Lock()
_shots_cache: tuple[str, dict, dict, dict] = ("", {}, {}, {})


def _app_key(name: str) -> str:
    """The name of an application compared across sources: without case,
    accents or punctuation, nor "Media Server" or "Dashboard" at the end, as
    the tab compares them to offer the same application from another source."""
    key = "".join(c for c in unicodedata.normalize("NFKD", str(name).casefold()) if not unicodedata.combining(c))
    key = re.sub(r"[^a-z0-9]", "", key)
    # Community Scripts names its Alpine builds "Alpine-<application>".
    if key.startswith("alpine") and len(key) > len("alpine") + 2:
        key = key[len("alpine"):]
    for suffix in ("mediaserver", "dashboard"):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            key = key[:-len(suffix)]
    return key


def _catalog_recipes() -> tuple[dict, dict, dict]:
    """What the cards need from the recipes, read once for each version of
    the catalog: the screenshots of every application that has them, the
    applications by their compared name, and how many containers each one
    installs."""
    global _shots_cache
    root = lxc_apps.oci_catalog_dir()
    with _shots_lock:
        if _shots_cache[0] == root:
            return _shots_cache[1], _shots_cache[2], _shots_cache[3]
    shots: dict = {}
    by_name: dict = {}
    containers: dict = {}
    for item in _oci_index():
        if not item.get("id") or item.get("hidden") or not item.get("automatic_install_candidate"):
            continue
        template = _oci_template(item)
        ui = template.get("catalog_ui") or {}
        services = [x for x in (template.get("compose_stack") or {}).get("services") or [] if isinstance(x, dict)]
        containers[item["id"]] = max(len(services), 1)
        listed = [u for u in ui.get("screenshots") or [] if isinstance(u, str) and u.startswith("https://")]
        if listed:
            shots[item["id"]] = listed
        by_name.setdefault(_app_key(item.get("title") or item["id"]), []).append(item)
    # The project's own image first, as the tab lists them.
    rank = {"official": 0, "linuxserver": 1, "other": 2}
    for items in by_name.values():
        items.sort(key=lambda i: rank[_publisher(i)["kind"]])
    with _shots_lock:
        _shots_cache = (root, shots, {key: [i["id"] for i in items] for key, items in by_name.items()}, containers)
    return shots, _shots_cache[2], containers


def _catalog_shots() -> tuple[dict, dict]:
    shots, by_name, _ = _catalog_recipes()
    return shots, by_name


def _oci_screens(app_id: str) -> list:
    """The screenshots of an OCI application, from its recipe."""
    return _catalog_shots()[0].get(app_id, [])


def _cs_screens(slug: str, name: str) -> list:
    """The screenshots of a Community Scripts script: those of the same
    application in the OCI catalog."""
    for app_id in _catalog_shots()[1].get(_app_key(name), []):
        screens = _oci_screens(app_id)
        if screens:
            return screens
    return []


def _credit(url: str, repository: str = "", given: dict | None = None) -> dict:
    """Where a screenshot comes from, cited under the image: its repository,
    the site of the project, or the author and license a file carries."""
    if given:
        parts = ["Wikimedia Commons" if "wikimedia.org" in url else "", given.get("author") or "", given.get("license") or ""]
        return {"label": " · ".join(p for p in parts if p), "url": given.get("page") or url}
    match = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", url)
    if match:
        return {"label": f"github.com/{match.group(1)}/{match.group(2)}",
                "url": f"https://github.com/{match.group(1)}/{match.group(2)}"}
    if re.match(r"https://(user-images\.githubusercontent\.com|private-user-images\.githubusercontent\.com|github\.com/user-attachments)/", url):
        # Attached to a README: the project's repository, when the sheet
        # links the project and not the image that packages it.
        found = re.match(r"https://github\.com/([^/]+)/([^/#?]+)", repository or "")
        if found and found.group(1).lower() not in ("linuxserver", "hotio", "jlesage"):
            return {"label": f"github.com/{found.group(1)}/{found.group(2)}",
                    "url": f"https://github.com/{found.group(1)}/{found.group(2)}"}
        return {"label": "GitHub", "url": url}
    host = urllib.parse.urlparse(url).netloc
    return {"label": host[4:] if host.startswith("www.") else host, "url": f"https://{host}/"}


def _screens(entries, repository: str = "") -> tuple[list, list]:
    """The screenshots of a sheet and the credit of each one. An entry is its
    address, or an object with the address and its own credit."""
    shots, credits = [], []
    for entry in entries or []:
        given = entry if isinstance(entry, dict) else None
        url = given.get("url") if given else entry
        if isinstance(url, str) and url.startswith("https://") and url not in shots:
            shots.append(url)
            credits.append(_credit(url, repository, given))
    return shots, credits


def _shot(key: str, name: str = "") -> str:
    """The first screenshot of an item, for the featured banner."""
    kind, _, item_id = key.partition(":")
    screens = _oci_screens(item_id) if kind == "oci" else _cs_screens(item_id, name)
    return screens[0] if screens else ""


def _oci_detail(app_id: str, language: str = "en") -> dict | None:
    item = next((i for i in _oci_index() if i.get("id") == app_id and not i.get("hidden")), None)
    if not item:
        return None
    template = _oci_template(item)
    table = _translations(language)
    ui = template.get("catalog_ui") or {}
    contract = template.get("container_contract") or {}
    defaults = (template.get("proxmox") or {}).get("defaults") or {}
    stack = template.get("compose_stack") or {}
    services = [s for s in stack.get("services") or [] if isinstance(s, dict)]
    volumes = []
    for volume in contract.get("volumes") or []:
        if not isinstance(volume, dict) or not volume.get("container_path"):
            continue
        volumes.append({
            "path": volume["container_path"],
            "mode": volume.get("default") or "",
            "size_gb": (volume.get("managed_volume") or {}).get("default_size_gb"),
            "choices": volume.get("installation_choice") or [],
        })
    # A suite installs the applications the user picks, each in its own LXC:
    # what the recipe says of its first container is not the suite's.
    profile = (template.get("proxmox") or {}).get("installer_profile") or {}
    suite = None
    if profile.get("stack_driver") == "arr-suite":
        titles = {i.get("id"): i.get("title") for i in _oci_index()}
        defaults = set(profile.get("default_applications") or [])
        players = (profile.get("media_players") or {}).get("choices") or ["jellyfin", "plex", "emby"]
        suite = {
            "applications": [{"name": titles.get(a) or a.capitalize(), "default": a in defaults}
                             for a in profile.get("applications") or [] if isinstance(a, str)],
            "players": [titles.get(a) or a.capitalize() for a in players if isinstance(a, str) and a != "none"],
        }
        contract, defaults, volumes = {}, {}, []
    detail = {
        **_oci_item(item, table),
        "suite": suite,
        "tagline": _tr(table, _text(ui.get("tagline"))),
        "about": _tr(table, _text(ui.get("description")) or item.get("description")),
        "notes": [_tr(table, t) for t in ui.get("tips") or [] if str(t).strip()],
        **dict(zip(("screenshots", "screenshot_credits"),
                   _screens(ui.get("screenshots"), ui.get("repository") or item.get("repository") or ""))),
        "links": {
            "website": ui.get("website") or item.get("website") or "",
            "documentation": ui.get("documentation") or "",
            "repository": ui.get("repository") or item.get("repository") or "",
        },
        "image": "" if suite else ((contract.get("image") or {}).get("reference")) or item.get("main_image") or "",
        "ports": [{"port": p.get("container_port"), "protocol": p.get("protocol") or "tcp"}
                  for p in contract.get("ports") or [] if isinstance(p, dict) and p.get("container_port")],
        "resources": {
            "cores": defaults.get("cores"),
            "memory_mb": defaults.get("memory_mb"),
            "swap_mb": defaults.get("swap_mb"),
            "disk_gb": defaults.get("rootfs_size_gb"),
        },
        "unprivileged": defaults.get("unprivileged", True) is not False,
        "volumes": volumes,
        "services": [{"name": s.get("name"), "role": s.get("role") or ("main" if s.get("is_main") else ""),
                      "main": bool(s.get("is_main")), "image": str(s.get("image") or "")}
                     for s in sorted(services, key=lambda x: (not x.get("is_main"), x.get("vmid_offset") or 0))],
        "credentials": [c.get("label") for c in (template.get("first_run") or {}).get("credentials") or []
                        if isinstance(c, dict) and c.get("label")],
        "installable": bool(item.get("automatic_install_candidate")),
    }
    return detail


# ---------------------------------------------------------------------------
# Community Scripts
# ---------------------------------------------------------------------------

def _scripts_raw() -> list:
    """The full Community Scripts catalog ProxMenux publishes, the same file
    the menu reads, kept for six hours and on disk across restarts."""
    global _scripts_cache
    with _scripts_lock:
        now = time.time()
        if _scripts_cache and now - _scripts_cache[0] < _SCRIPTS_TTL:
            return _scripts_cache[1]
        try:
            request = urllib.request.Request(managed_installs._HELPERS_CACHE_URL,
                                             headers={"User-Agent": "ProxMenux-Monitor"})
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
            if not isinstance(raw, list):
                raise ValueError("unexpected catalog")
            _scripts_cache = (now, raw)
            try:
                os.makedirs(os.path.dirname(_SCRIPTS_DISK), exist_ok=True)
                tmp = f"{_SCRIPTS_DISK}.tmp.{os.getpid()}"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump({"ts": now, "scripts": raw}, handle)
                os.replace(tmp, _SCRIPTS_DISK)
            except OSError:
                pass
            return raw
        except Exception:
            if _scripts_cache:
                return _scripts_cache[1]
            disk = _read_json(_SCRIPTS_DISK) or {}
            raw = disk.get("scripts") if isinstance(disk.get("scripts"), list) else []
            _scripts_cache = (now - _SCRIPTS_TTL + 300, raw)
            return raw


def _script_entries() -> dict:
    """One entry per script; a script with several OS variants is listed once."""
    entries: dict = {}
    for entry in _scripts_raw():
        if isinstance(entry, dict) and entry.get("slug") and entry.get("slug") not in entries:
            entries[entry["slug"]] = entry
    return entries


# Tools of Community Scripts: the scripts run on the host. Each category of
# Community Scripts is a section of its own in the tab.
_CS_SECTION_PREFIX = "cs:"


def _script_item(entry: dict) -> dict:
    names = entry.get("category_names") or []
    kind = _SCRIPT_TYPES.get(str(entry.get("type") or ""), "lxc")
    # A script run on the host is a tool, in the section of its category; any
    # other script, an add-on included, is an application.
    tool = kind == "host"
    return {
        "key": f"cs:{entry['slug']}",
        "kind": "cs",
        "id": entry["slug"],
        "name": entry.get("name") or entry["slug"],
        "summary": _plain(entry.get("desc")),
        "icon": entry.get("logo") or "",
        "category": _category(names[0] if names else ""),
        "architectures": ["amd64", "arm64"] if entry.get("has_arm") else ["amd64"],
        "type": kind,
        "group": "tool" if tool else "app",
        "section": f"{_CS_SECTION_PREFIX}{names[0] if names else ''}" if tool else "",
        "runs_in": [str(x) for x in entry.get("execute_in") or [] if isinstance(x, str)],
        "shot": _shot(f"cs:{entry['slug']}", entry.get("name") or entry["slug"]),
        "updateable": bool(entry.get("updateable")),
        "privileged": bool(entry.get("privileged")),
    }


def _pocketbase(slug: str) -> dict:
    """The full record of a script from the Community Scripts database:
    resources, version and dates the published catalog leaves out."""
    with _details_lock:
        cached = _details_cache.get(slug)
        if cached and time.time() - cached[0] < _DETAILS_TTL:
            return cached[1]
    record: dict = {}
    try:
        query = urllib.parse.urlencode({"filter": f"(slug='{slug}')", "perPage": 1})
        request = urllib.request.Request(f"{_POCKETBASE}?{query}", headers={"User-Agent": "ProxMenux-Monitor"})
        with urllib.request.urlopen(request, timeout=10) as response:
            items = json.loads(response.read().decode("utf-8")).get("items") or []
        record = items[0] if items and isinstance(items[0], dict) else {}
    except Exception:
        record = {}
    with _details_lock:
        _details_cache[slug] = (time.time(), record)
    return record


def _script_detail(slug: str) -> dict | None:
    entry = _script_entries().get(slug)
    if not entry:
        return None
    record = _pocketbase(slug)
    method = next((m for m in record.get("install_methods") or [] if isinstance(m, dict)), {})
    resources = method.get("resources") or {}
    notes = [{"type": "warning", "text": _plain(n)} for n in entry.get("warnings") or [] if _plain(n)]
    notes += [{"type": "info", "text": _plain(n)} for n in entry.get("notes") or [] if _plain(n)]
    credentials = entry.get("default_credentials") if isinstance(entry.get("default_credentials"), dict) else {}
    script = entry.get("script") or ""
    return {
        **_script_item(entry),
        "about": _plain(entry.get("desc")),
        "notes": notes,
        # Their texts are kept; only the application's own screenshots are added.
        **dict(zip(("screenshots", "screenshot_credits"), _screens(_cs_screens(slug, entry.get("name") or slug)))),
        "links": {
            "community": f"https://community-scripts.org/scripts/{urllib.parse.quote(slug)}",
            "website": entry.get("website") or record.get("website") or "",
            "documentation": entry.get("documentation") or record.get("documentation") or "",
            "repository": record.get("repository") or "",
            "script": f"https://github.com/community-scripts/ProxmoxVE/blob/main/{script}" if script else "",
        },
        "ports": [{"port": entry.get("port"), "protocol": "tcp"}] if entry.get("port") else [],
        "resources": {
            "cores": resources.get("cpu"),
            "memory_mb": resources.get("ram"),
            "disk_gb": resources.get("hdd"),
            "os": " ".join(str(v) for v in (resources.get("os"), resources.get("version")) if v),
        },
        "config_path": entry.get("config_path") or method.get("config_path") or "",
        "version": (record.get("repository_data") or {}).get("version") or "",
        "last_change": record.get("last_update_commit") or "",
        "updated": record.get("script_updated") or "",
        "default_login": ({"username": str(credentials.get("username") or ""),
                           "password": str(credentials.get("password") or "")}
                          if credentials.get("username") or credentials.get("password") else None),
    }


# ---------------------------------------------------------------------------
# ProxMenux options: the same list the menu search uses
# ---------------------------------------------------------------------------

_MENUS = "/usr/local/share/proxmenux/scripts/menus"
_options_lock = threading.Lock()
_options_cache: dict[str, tuple[float, list]] = {}
_OPTIONS_TTL = 600
_DOCS_BASE = "https://proxmenux.com"


def _language(value) -> str:
    value = str(value or "en").split("-", 1)[0].lower()
    return value if re.fullmatch(r"[a-z]{2}", value) else "en"


def _options(language: str) -> list:
    """The menu's own options, as the menu search lists them, in a language."""
    with _options_lock:
        cached = _options_cache.get(language)
        if cached and time.time() - cached[0] < _OPTIONS_TTL:
            return cached[1]
    options: list = []
    try:
        result = subprocess.run([sys.executable, os.path.join(_MENUS, "search_menu.py"), "--list", "--language", language],
                                capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            loaded = json.loads(result.stdout)
            options = [o for o in loaded if isinstance(o, dict) and o.get("key")]
    except (OSError, subprocess.SubprocessError, ValueError):
        options = []
    with _options_lock:
        _options_cache[language] = (time.time(), options)
    return options


_sections_lock = threading.Lock()
_sections_cache: dict[str, tuple[float, list]] = {}


def _sections(language: str) -> list:
    """The sections of the main menu the tab shows, in the menu's order, with
    the Community Scripts scripts each menu offers itself."""
    with _sections_lock:
        cached = _sections_cache.get(language)
        if cached and time.time() - cached[0] < _OPTIONS_TTL:
            return cached[1]
    sections: list = []
    try:
        result = subprocess.run([sys.executable, os.path.join(_MENUS, "search_menu.py"), "--sections", "--language", language],
                                capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            loaded = json.loads(result.stdout)
            sections = [s for s in loaded if isinstance(s, dict) and s.get("name")]
    except (OSError, subprocess.SubprocessError, ValueError):
        sections = []
    with _sections_lock:
        _sections_cache[language] = (time.time(), sections)
    return sections


_docs_cache: tuple[float, dict] = (0.0, {})


def _docs_text(page: str, language: str) -> str:
    """The short description of a documentation page, in a language."""
    global _docs_cache
    path = os.path.join(_MENUS, "option_docs.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    if mtime != _docs_cache[0]:
        loaded = _read_json(path)
        _docs_cache = (mtime, loaded if isinstance(loaded, dict) else {})
    texts = _docs_cache[1].get(page) or {}
    return texts.get(language) or texts.get("en") or ""


def _option_text(option: dict, language: str) -> str:
    """What the docs say of an option: the section that explains it, or else
    its page."""
    return _docs_text(option.get("explains") or "", language) or _docs_text(option.get("docs") or "", language)


def _includes(option: dict) -> list:
    """The names of the settings a script applies or offers, by group."""
    groups = []
    for group in option.get("includes") or []:
        if not isinstance(group, dict):
            continue
        items = [i for i in group.get("items") or [] if isinstance(i, str) and i.strip()]
        if items:
            groups.append({"group": str(group.get("group") or ""), "items": items})
    return groups


def _maintainer(value) -> dict | None:
    if not isinstance(value, dict) or not value.get("name"):
        return None
    url = str(value.get("url") or "")
    return {"name": str(value["name"]), "url": url if url.startswith("https://") else ""}


def _option_item(option: dict, language: str = "en") -> dict:
    # A VM the menu creates is an application, with its logo and category;
    # any other option is a task, shown with its menu as category.
    app = option.get("group") == "app"
    icon = str(option.get("icon") or "")
    return {
        "key": f"pmx:{option['key']}",
        "kind": "pmx",
        "id": option["key"],
        "name": option.get("name") or option.get("title") or "",
        "summary": option.get("description") or _option_text(option, language),
        "icon": icon if icon.startswith("https://") else "",
        "category": (option.get("category") if app else "") or option.get("kind") or "",
        "architectures": [],
        "type": option.get("type") or "",
        "group": "app" if app else "tool",
        # The section of the main menu it belongs to; opening the section
        # lists it when its menu does, a search finds it anyway. A VM its
        # menu lists, as macOS, is there as well as in its category.
        "section": option.get("section") or "",
        "browse": bool(option.get("browse")),
        "order": option.get("order") if isinstance(option.get("order"), int) else 0,
        # Listed apart, as the menu lists its external scripts; and who
        # maintains it, when the script is not in the ProxMenux repository.
        "apart": bool(option.get("apart")),
        "third_party": _maintainer(option.get("third_party")),
        "terms": option.get("terms") or "",
    }


def _option_detail(key: str, language: str) -> dict | None:
    option = next((o for o in _options(language) if o.get("key") == key), None)
    if not option:
        return None
    page = option.get("docs") or ""
    explained = _option_text(option, language)
    resources = option.get("resources") if isinstance(option.get("resources"), dict) else {}
    return {
        **_option_item(option, language),
        # A VM says what the system is, then what ProxMenux does; the page of
        # the documentation is shared by every system of its kind, so it stays
        # a link. Any other option is explained by its page.
        "about": option.get("about") or option.get("description") or explained,
        "explained": option.get("description") if option.get("about")
        else ("" if option.get("group") == "app" else explained if option.get("description") else ""),
        "notes": [{"type": "info", "text": n} for n in option.get("notes") or [] if isinstance(n, str) and n.strip()],
        "releases": [r for r in option.get("releases") or [] if isinstance(r, str)],
        # Third-party scripts it runs in one of its steps.
        "uses_third_party": [m for m in (_maintainer(u) for u in option.get("uses") or []) if m],
        # The settings of the automated and of the customizable post-install.
        "includes": _includes(option),
        "includes_kind": "applies" if page == "post-install/automated" else "offers",
        **dict(zip(("screenshots", "screenshot_credits"),
                   _screens(option.get("screenshots"), str((option.get("links") or {}).get("repository") or "")))),
        # The system's own pages, then the ProxMenux page of the option.
        "links": {
            **{key: url for key, url in (option.get("links") if isinstance(option.get("links"), dict) else {}).items()
               if key in ("website", "documentation", "repository") and isinstance(url, str) and url.startswith("https://")},
            "proxmenux": f"{_DOCS_BASE}/{language}/docs/{re.sub(r'/?index$', '', page)}" if page else "",
        },
        "ports": [],
        "resources": {k: v for k, v in resources.items() if k in ("cores", "memory_mb", "disk_gb") and isinstance(v, int)},
        # Where an option lives in the menu helps to find it there; a system
        # is opened from its card.
        "menu": "" if option.get("group") == "app" else option.get("kind") or "",
    }


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def _product() -> str:
    """The Proxmox product of this host: pve, or pbs for a Backup Server."""
    try:
        import pbs_manager
        return "pbs" if pbs_manager.is_pbs_host() else "pve"
    except Exception:
        return "pve"


def _runs_here(entry: dict, product: str) -> bool:
    """Whether a Community Scripts script is meant for this host: PVE runs the
    ones for itself and the ones installed in its containers and VMs; a PBS,
    PMG or PDM script is left out on any other product."""
    where = {str(x) for x in entry.get("execute_in") or [] if isinstance(x, str)}
    if not where:
        return product == "pve"
    return product in where or (product == "pve" and bool(where & {"lxc", "vm"}))


def list_items(language: str = "en") -> dict:
    """Every item of the tab and the sections of its tools, with what the
    search, the cards and the tiles need."""
    language = _language(language)
    product = _product()
    scripts = [_script_item(e) for e in _script_entries().values() if _runs_here(e, product)]
    cs_sections = sorted({i["section"] for i in scripts if i["group"] == "tool" and i["section"]})
    cs = [{"key": key, "kind": "cs", "title": key[len(_CS_SECTION_PREFIX):], "external": []} for key in cs_sections]
    if product != "pve":
        # A Backup Server runs no containers: only its own scripts.
        return {"items": [i for i in scripts if i["group"] == "tool"], "sections": cs}
    table = _translations(language)
    oci = [_oci_item(i, table) for i in _oci_index()
           if i.get("id") and not i.get("hidden") and i.get("automatic_install_candidate")]
    # A VM the menu creates with a Community Scripts installer, or an option
    # that runs one, is already listed as that script.
    sections = _sections(language)
    shown = {section["name"] for section in sections}
    options = [_option_item(o, language) for o in _options(language)
               if o.get("via") != "community-scripts" and (o.get("group") == "app" or o.get("section") in shown)]
    pmx = [{"key": section["name"], "kind": "pmx", "title": section.get("title") or section["name"],
            "external": [key for key in section.get("external") or []
                         if isinstance(key, str) and key.startswith(("cs:", "pmx:"))]}
           for section in sections]
    return {"items": oci + scripts + options, "sections": pmx + cs}


def item_detail(kind: str, item_id: str, language: str = "en") -> dict | None:
    if not _SAFE_ID.match(item_id or ""):
        return None
    if kind == "oci":
        return _oci_detail(item_id, _language(language))
    if kind == "cs":
        return _script_detail(item_id)
    if kind == "pmx":
        return _option_detail(item_id, _language(language))
    return None
