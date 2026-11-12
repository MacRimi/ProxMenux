#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

SCRIPT_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"
POCKETBASE_BASE = "https://db.community-scripts.org/api/collections"
SCRIPT_COLLECTION_URL = f"{POCKETBASE_BASE}/script_scripts/records"
CATEGORY_COLLECTION_URL = f"{POCKETBASE_BASE}/script_categories/records"

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = REPO_ROOT / "json" / "helpers_cache.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

TYPE_TO_PATH_PREFIX = {
    "lxc": "ct",
    "vm": "vm",
    "addon": "tools/addon",
    "pve": "tools/pve",
}


def to_mirror_url(raw_url: str) -> str:
    m = re.match(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$", raw_url or "")
    if not m:
        return ""
    org, repo, branch, path = m.groups()
    if org.lower() != "community-scripts" or repo != "ProxmoxVE":
        return ""
    return f"https://git.community-scripts.org/community-scripts/ProxmoxVE/raw/branch/{branch}/{path}"


def fetch_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response from {url}: expected object")
    return data


def fetch_all_records(url: str, *, expand: str | None = None, per_page: int = 500) -> list[dict[str, Any]]:
    page = 1
    items: list[dict[str, Any]] = []

    while True:
        params: dict[str, Any] = {"page": page, "perPage": per_page}
        if expand:
            params["expand"] = expand

        data = fetch_json(url, params=params)
        page_items = data.get("items", [])
        if not isinstance(page_items, list):
            raise RuntimeError(f"Unexpected items list from {url}")

        items.extend(page_items)

        total_pages = data.get("totalPages", page)
        if not isinstance(total_pages, int) or page >= total_pages:
            break
        page += 1

    return items


def normalize_os_variants(install_methods: list[dict[str, Any]]) -> list[str]:
    os_values: list[str] = []
    for item in install_methods:
        if not isinstance(item, dict):
            continue
        resources = item.get("resources", {})
        if not isinstance(resources, dict):
            continue
        os_name = resources.get("os")
        if isinstance(os_name, str) and os_name.strip():
            normalized = os_name.strip().lower()
            if normalized not in os_values:
                os_values.append(normalized)
    return os_values


def split_notes(notes_raw: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Split PocketBase notes into (info_notes, warnings).

    Each entry has shape ``{"text": str, "type": "warning"|...}``. Anything
    flagged ``type == "warning"`` lands in the warnings list so the bash
    menu can render those in red with a dedicated WARNINGS header. Other
    notes go to the regular notes list.
    """
    info: list[str] = []
    warns: list[str] = []
    for note in notes_raw or []:
        if not isinstance(note, dict):
            continue
        text = note.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()
        ntype = (note.get("type") or "").strip().lower()
        if ntype == "warning":
            warns.append(text)
        else:
            info.append(text)
    return info, warns


def build_script_path(type_name: str, slug: str) -> str:
    type_name = (type_name or "").strip().lower()
    slug = (slug or "").strip()

    if type_name == "turnkey":
        return "turnkey/turnkey.sh"

    prefix = TYPE_TO_PATH_PREFIX.get(type_name)
    if not prefix or not slug:
        return ""

    return f"{prefix}/{slug}.sh"


def _icon_tools():
    """The engine's icon checks, loaded from their file so the engine package
    and its registry setup are not imported. None without Pillow."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return None
    path = REPO_ROOT / "oci/src/proxmenux_oci/icons.py"
    spec = importlib.util.spec_from_file_location("proxmenux_icons", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_dark_logos(cache: list[dict[str, Any]], previous: list[dict[str, Any]], icons=None, resolver=None) -> int:
    """Give each logo its version for the dark theme of the Monitor.

    A logo drawn as a black mark on a transparent background disappears on
    the dark theme, so its entry carries ``logo_dark``: the light version its
    icon set publishes, or "invert" when there is none. A logo that shows on
    both themes carries an empty ``logo_dark``. A logo already checked in the
    previous file keeps its answer, so a run only reads the new logos. Without
    Pillow the previous answers are kept and nothing new is checked.
    """
    known = {e["logo"]: e["logo_dark"] for e in previous
             if isinstance(e, dict) and e.get("logo") and isinstance(e.get("logo_dark"), str)}
    pending = sorted({e["logo"] for e in cache if e.get("logo") and e["logo"] not in known})
    if pending and icons is not None:
        resolver = resolver or icons.IconResolver()

        def check(logo: str) -> tuple[str, str]:
            data = icons.fetch_icon(logo)
            if data is None:
                return logo, None
            return logo, resolver.dark_theme_icon(logo, data) or ""

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            for logo, dark in pool.map(check, pending):
                if dark is not None:
                    known[logo] = dark
    dark_count = 0
    for entry in cache:
        logo = entry.get("logo")
        if logo in known:
            entry["logo_dark"] = known[logo]
            dark_count += bool(known[logo])
    return dark_count


def main() -> int:
    try:
        scripts = fetch_all_records(SCRIPT_COLLECTION_URL, expand="type,categories")
        categories = fetch_all_records(CATEGORY_COLLECTION_URL)
    except Exception as e:
        print(f"ERROR: Unable to fetch PocketBase data: {e}", file=sys.stderr)
        return 1

    category_map: dict[str, dict[str, Any]] = {}
    for category in categories:
        category_id = category.get("id")
        if isinstance(category_id, str) and category_id:
            category_map[category_id] = category

    cache: list[dict[str, Any]] = []

    print(f"Fetched {len(scripts)} scripts and {len(category_map)} categories")

    for idx, raw in enumerate(scripts, start=1):
        if not isinstance(raw, dict):
            continue

        slug = raw.get("slug")
        name = raw.get("name", "")
        desc = raw.get("description", "")

        if not isinstance(slug, str) or not slug.strip():
            continue

        expand = raw.get("expand", {}) if isinstance(raw.get("expand"), dict) else {}
        type_expanded = expand.get("type", {}) if isinstance(expand.get("type"), dict) else {}
        type_name = type_expanded.get("type", "") if isinstance(type_expanded.get("type"), str) else ""

        script_path = build_script_path(type_name, slug)
        if not script_path:
            print(f"[{idx:03d}] WARNING: Unable to build script path for slug={slug} type={type_name!r}", file=sys.stderr)
            continue

        full_script_url = f"{SCRIPT_BASE}/{script_path}"
        script_url_mirror = to_mirror_url(full_script_url)

        # Sprint 11.7: PocketBase exposes these as `install_methods` and
        # `notes`, not `install_methods_json` / `notes_json`. The legacy field
        # names silently returned [] for every entry, which is why the cache
        # had empty notes and missing OS variants for every script.
        install_methods = raw.get("install_methods", [])
        if not isinstance(install_methods, list):
            install_methods = []

        notes_raw = raw.get("notes", [])
        if not isinstance(notes_raw, list):
            notes_raw = []

        notes, warnings = split_notes(notes_raw)

        category_ids = raw.get("categories", [])
        if not isinstance(category_ids, list):
            category_ids = []

        expanded_categories = expand.get("categories", []) if isinstance(expand.get("categories"), list) else []
        category_names: list[str] = []
        for cat in expanded_categories:
            if isinstance(cat, dict):
                cat_name = cat.get("name")
                if isinstance(cat_name, str) and cat_name.strip():
                    category_names.append(cat_name.strip())

        if not category_names:
            for cat_id in category_ids:
                cat = category_map.get(cat_id, {})
                cat_name = cat.get("name")
                if isinstance(cat_name, str) and cat_name.strip():
                    category_names.append(cat_name.strip())

        # Shared fields across all install method entries
        default_user = raw.get("default_user")
        default_passwd = raw.get("default_passwd")
        default_credentials: dict[str, str] | None = None
        if (isinstance(default_user, str) and default_user.strip()) or (isinstance(default_passwd, str) and default_passwd.strip()):
            default_credentials = {
                "username": default_user if isinstance(default_user, str) else "",
                "password": default_passwd if isinstance(default_passwd, str) else "",
            }

        base_entry: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "desc": desc,
            "script": script_path,
            "script_url": full_script_url,
            "script_url_mirror": script_url_mirror,
            "type": type_name,
            "type_id": raw.get("type", ""),
            "categories": category_ids,
            "category_names": category_names,
            "notes": notes,
            "warnings": warnings,
            "port": raw.get("port", 0),
            "website": raw.get("website", ""),
            "documentation": raw.get("documentation", ""),
            "logo": raw.get("logo", ""),
            "updateable": bool(raw.get("updateable", False)),
            "privileged": bool(raw.get("privileged", False)),
            "has_arm": bool(raw.get("has_arm", False)),
            "is_dev": bool(raw.get("is_dev", False)),
            "execute_in": raw.get("execute_in", []),
            "config_path": raw.get("config_path", ""),
        }
        if default_credentials:
            base_entry["default_credentials"] = default_credentials

        # Emit one entry per install method so the menu shell can offer an
        # explicit OS choice. When there is only one method (or none), a
        # single entry is emitted with os="" (script decides at runtime).
        os_variants = normalize_os_variants(install_methods)

        if len(os_variants) > 1:
            for os_name in os_variants:
                entry = {**base_entry, "os": os_name}
                cache.append(entry)
                print(f"[{len(cache):03d}] {slug:<24} → {script_path:<28} type={type_name:<7} os={os_name}")
        else:
            os_name = os_variants[0] if os_variants else ""
            entry = {**base_entry, "os": os_name}
            cache.append(entry)
            print(f"[{len(cache):03d}] {slug:<24} → {script_path:<28} type={type_name:<7} os={os_name or 'n/a'}")

    cache.sort(key=lambda x: (x.get("slug") or "", x.get("script") or ""))

    try:
        previous = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = []
    dark = apply_dark_logos(cache, previous if isinstance(previous, list) else [], _icon_tools())
    print(f"   Black logos with a version for the dark theme: {dark}")

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    total_notes = sum(len(e.get("notes", [])) for e in cache)
    total_warns = sum(len(e.get("warnings", [])) for e in cache)
    print(f"\n✅ helpers_cache.json → {OUTPUT_FILE}")
    print(f"   Guardados: {len(cache)} entries, {total_notes} notes, {total_warns} warnings")

    return 0

if __name__ == "__main__":
    sys.exit(main())
