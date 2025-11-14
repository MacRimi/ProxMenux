#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

import requests

# ---------- Config ----------
API_URL = "https://api.github.com/repos/community-scripts/ProxmoxVE/contents/frontend/public/json"
SCRIPT_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"

# Escribimos siempre en <raiz_repo>/json/helpers_cache.json, independientemente del cwd
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = REPO_ROOT / "json" / "helpers_cache.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
# ----------------------------


def to_mirror_url(raw_url: str) -> str:
    """
    Convierte una URL raw de GitHub al raw del mirror.
    GH : https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/docker.sh
    MIR: https://git.community-scripts.org/community-scripts/ProxmoxVE/raw/branch/main/ct/docker.sh
    """
    m = re.match(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$", raw_url or "")
    if not m:
        return ""
    org, repo, branch, path = m.groups()
    if org.lower() != "community-scripts" or repo != "ProxmoxVE":
        return ""
    return f"https://git.community-scripts.org/community-scripts/ProxmoxVE/raw/branch/{branch}/{path}"


def guess_os_from_script_path(script_path: str) -> str | None:
    """
    Heurística suave cuando el JSON no publica resources.os:
      - tools/pve/*   -> proxmox
      - ct/alpine-*   -> alpine
      - tools/addon/* -> generic (suele ejecutarse sobre LXC existente)
      - ct/*          -> debian (por defecto para CTs)
    """
    if not script_path:
        return None
    if script_path.startswith("tools/pve/") or script_path == "tools/pve/host-backup.sh" or script_path.startswith("vm/"):
        return "proxmox"
    if "/alpine-" in script_path or script_path.startswith("ct/alpine-"):
        return "alpine"
    if script_path.startswith("tools/addon/"):
        return "generic"
    if script_path.startswith("ct/"):
        return "debian"
    return None


def fetch_directory_json(api_url: str) -> list[dict]:
    r = requests.get(api_url, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError("GitHub API no devolvió una lista.")
    return data


def main() -> int:
    try:
        directory = fetch_directory_json(API_URL)
    except Exception as e:
        print(f"ERROR: No se pudo leer el índice de JSONs: {e}", file=sys.stderr)
        return 1

    cache: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (slug, script) para evitar duplicados

    total_items = len(directory)
    processed = 0
    kept = 0

    for item in directory:
        url = item.get("download_url")
        name_in_dir = item.get("name", "")
        if not url or not url.endswith(".json"):
            continue

        try:
            raw = requests.get(url, timeout=30).json()
            if not isinstance(raw, dict):
                continue
        except Exception:
            print(f"❌ Error al obtener/parsing {name_in_dir}", file=sys.stderr)
            continue

        processed += 1

        name = raw.get("name", "")
        slug = raw.get("slug")
        type_ = raw.get("type", "")
        desc = raw.get("description", "")
        categories = raw.get("categories", [])
        notes = [n.get("text", "") for n in raw.get("notes", []) if isinstance(n, dict)]

        # Credenciales (si existen, se copian tal cual)
        credentials = raw.get("default_credentials", {})
        cred_username = credentials.get("username") if isinstance(credentials, dict) else None
        cred_password = credentials.get("password") if isinstance(credentials, dict) else None
        add_credentials = any([
            cred_username not in (None, ""),
            cred_password not in (None, "")
        ])

        install_methods = raw.get("install_methods", [])
        if not isinstance(install_methods, list) or not install_methods:
            # Sin install_methods válidos -> continuamos
            continue

        for im in install_methods:
            if not isinstance(im, dict):
                continue
            script = im.get("script", "")
            if not script:
                continue

            # OS desde resources u heurística
            resources = im.get("resources", {}) if isinstance(im, dict) else {}
            os_name = resources.get("os") if isinstance(resources, dict) else None
            if not os_name:
                os_name = guess_os_from_script_path(script)
            if isinstance(os_name, str):
                os_name = os_name.strip().lower()

            full_script_url = f"{SCRIPT_BASE}/{script}"
            script_url_mirror = to_mirror_url(full_script_url)

            key = (slug or "", script)
            if key in seen:
                continue
            seen.add(key)

            entry = {
                "name": name,
                "slug": slug,
                "desc": desc,
                "script": script,
                "script_url": full_script_url,
                "script_url_mirror": script_url_mirror,  # nuevo
                "os": os_name,                            # nuevo
                "categories": categories,
                "notes": notes,
                "type": type_,
            }
            if add_credentials:
                entry["default_credentials"] = {
                    "username": cred_username,
                    "password": cred_password,
                }

            cache.append(entry)
            kept += 1

            # Progreso ligero
            print(f"[{kept:03d}] {slug or name:<24} → {script:<28} os={os_name or 'n/a'} src={'GH+MR' if script_url_mirror else 'GH'}")

    # Orden estable para commits reproducibles
    cache.sort(key=lambda x: (x.get("slug") or "", x.get("script") or ""))

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n✅ helpers_cache.json → {OUTPUT_FILE}")
    print(f"   Total JSON en índice: {total_items}")
    print(f"   Procesados: {processed} | Guardados: {kept} | Únicos (slug,script): {len(seen)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
