"""Refresh the reviewed ProxMenux catalog without blocking the OCI menu.

GitHub's catalog commit and tree form the manifest. Files are fetched from
that immutable commit and checked against their Git blob IDs. Runtime code is
never downloaded. An installed engine always retains its bundled fallback.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

from .i18n import translate

REPOSITORY = "MacRimi/ProxMenux"
CATALOG_API = 1
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 40 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}")
ROOT_FILES = {"index.json", "categories.json", "volume-policy.json",
              "exclusions.json", "verification.json", "compatibility.json"}


def source_settings(root):
    root = Path(root)
    base = (root.parent.parent if root.name == "engine" else
            root.parent if root.name == "oci" else root)
    return read_json(base / "oci/catalog-source.json")


def channel_for(root):
    """Keep stable and beta catalogs separate; allow a local channel choice."""
    root = Path(root)
    base = (root.parent.parent if root.name == "engine" else
            root.parent if root.name == "oci" else root)
    for name in ("oci/catalog-source.json", "config.json"):
        try:
            value = json.loads((base / name).read_text())
            channel = value.get("channel") or value.get("install_branch")
            if channel in ("main", "develop"):
                return channel
            if (value.get("beta_program") or {}).get("status") == "active":
                return "develop"
        except (OSError, ValueError, TypeError):
            pass
    return "develop" if (base / "beta_version.txt").exists() else "main"


def cache_root(root):
    root = Path(root)
    return root.parent / "catalog-cache" if root.name == "engine" else root / ".catalog-cache"


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text())
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    return {} if default is None else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def schema_hash(root):
    return hashlib.sha256((Path(root) / "schemas/oci-template.schema.json").read_bytes()).hexdigest()


def current_catalog(root, channel=None):
    root = Path(root)
    channel = channel or channel_for(root)
    value = read_json(cache_root(root) / f"{channel}-current.json")
    revision = value.get("revision", "")
    if (isinstance(revision, str) and SHA.fullmatch(revision)
            and value.get("schema_hash") == schema_hash(root)
            and value.get("engine_api") == CATALOG_API):
        path = cache_root(root) / "snapshots" / revision
        index = read_json(path / "index.json")
        if (index.get("kind") == "proxmenux.oci-catalog-index"
                and isinstance(index.get("applications"), list) and index["applications"]):
            return path
    return root / "catalog"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def request(url, etag=None, limit=MAX_FILE):
    headers = {"User-Agent": "ProxMenux-OCI-Catalog", "Accept": "application/vnd.github+json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError("Catalog response exceeds the size limit")
            return body, response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, etag
        raise


def catalog_path(name):
    path = PurePosixPath(name)
    if (str(path) != name or path.is_absolute() or ".." in path.parts
            or path.suffix != ".json"):
        raise ValueError("Invalid catalog file path")
    if name not in ROOT_FILES and not (len(path.parts) == 2 and path.parts[0] in
                                                      ("apps", "curated", "overlays")):
        raise ValueError("Unsupported catalog file path")
    return path


def validate_snapshot(root, directory):
    from .catalog import Catalog
    from jsonschema import Draft202012Validator
    compatibility = (json.loads((directory / "compatibility.json").read_text())
                     if (directory / "compatibility.json").exists() else {"engine_api": 1})
    if compatibility.get("engine_api") != CATALOG_API:
        raise ValueError("This catalog requires a newer OCI engine")
    validator = Draft202012Validator(json.loads((Path(root) / "schemas/oci-template.schema.json").read_text()))
    for folder in ("apps", "curated"):
        for file in (directory / folder).glob("*.json"):
            validator.validate(json.loads(file.read_text()))
    index = json.loads((directory / "index.json").read_text())
    if index.get("kind") != "proxmenux.oci-catalog-index":
        raise ValueError("Invalid catalog index")
    ids = set()
    for item in index.get("applications", []):
        app_id = item.get("id", "")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", app_id) or app_id in ids:
            raise ValueError("Invalid or duplicate catalog application")
        ids.add(app_id)
        if item.get("template_family") == "curated-profile":
            curated = item.get("curated_path", "")
            if not curated.startswith("catalog/"):
                raise ValueError("Invalid curated recipe path")
            catalog_path(curated.removeprefix("catalog/"))
    if not ids:
        raise ValueError("The remote catalog is empty")
    catalog = Catalog(Path(root), catalog_dir=directory)
    for item in catalog.load_index()["applications"]:
        if not item.get("hidden") and item.get("automatic_install_candidate"):
            validator.validate(catalog._compose_item(item))


def synchronize(root, channel, fetch=request):
    """Download changed JSON files into a private snapshot, then publish once."""
    root = Path(root)
    cache = cache_root(root)
    cache.mkdir(parents=True, exist_ok=True)
    metadata_path = cache / f"{channel}-remote.json"
    previous = read_json(metadata_path)
    active = current_catalog(root, channel)
    etag = previous.get("etag") if active != root / "catalog" else None
    url = f"https://api.github.com/repos/{REPOSITORY}/commits?sha={channel}&path=oci/catalog&per_page=1"
    body, etag = fetch(url, etag)
    if body is None:
        return False
    commits = json.loads(body)
    revision = commits[0]["sha"]
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("Invalid catalog revision")
    if active.name == revision:
        write_json(metadata_path, {"etag": etag})
        return False
    body, _ = fetch(f"https://api.github.com/repos/{REPOSITORY}/git/trees/{revision}?recursive=1")
    tree = json.loads(body)
    if tree.get("truncated"):
        raise ValueError("GitHub returned an incomplete catalog manifest")
    entries = {}
    schema = None
    for entry in tree["tree"]:
        name = entry["path"]
        if name == "oci/schemas/oci-template.schema.json":
            schema = entry["sha"]
        if not name.startswith("oci/catalog/") or entry.get("type") != "blob":
            continue
        relative = name.removeprefix("oci/catalog/")
        if relative.startswith("generation-report"):
            continue
        catalog_path(relative)
        if entry.get("mode") != "100644" or not SHA.fullmatch(entry.get("sha", "")):
            raise ValueError("Invalid catalog manifest entry")
        if type(entry.get("size")) is not int or not 0 <= entry["size"] <= MAX_FILE:
            raise ValueError("Invalid catalog file size")
        entries[relative] = entry
    if schema != git_blob((root / "schemas/oci-template.schema.json").read_bytes()):
        raise ValueError("Catalog schema changed; update ProxMenux first")
    if not entries or len(entries) > 3000 or sum(e["size"] for e in entries.values()) > MAX_TOTAL:
        raise ValueError("Catalog exceeds the size limit")
    if not {"index.json", "categories.json", "volume-policy.json", "verification.json"} <= entries.keys():
        raise ValueError("Catalog manifest is incomplete")
    snapshots = cache / "snapshots"
    snapshots.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=snapshots) as name:
        staging = Path(name)

        def download(pair):
            relative, entry = pair
            old = active / relative
            data = old.read_bytes() if old.is_file() else b""
            if git_blob(data) != entry["sha"]:
                data, _ = fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/oci/catalog/{relative}")
            if data is None or len(data) != entry["size"] or git_blob(data) != entry["sha"]:
                raise ValueError("Catalog file failed its integrity check")
            json.loads(data)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(download, entries.items()))
        validate_snapshot(root, staging)
        destination = snapshots / revision
        if destination.exists():
            # Revalidate an existing immutable snapshot after an interrupted publication.
            validate_snapshot(root, destination)
        else:
            os.replace(staging, destination)
        write_json(cache / f"{channel}-current.json", {"revision": revision,
                   "schema_hash": schema_hash(root), "engine_api": CATALOG_API})
        write_json(metadata_path, {"etag": etag})
    return True


def worker(root, channel):
    cache = cache_root(root)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            changed = synchronize(root, channel)
            write_json(cache / f"{channel}-result.json", {"ok": True, "changed": changed})
        except Exception as error:
            write_json(cache / f"{channel}-result.json", {"ok": False, "error": str(error)[:400]})


def visible_recipes(catalog):
    """Same availability rule as the menu; count new IDs, not net growth."""
    result = {}
    policies = {}
    for item in catalog.load_index()["applications"]:
        if item.get("hidden") or not item.get("automatic_install_candidate"):
            continue
        directory = catalog.root / "catalog" if item["id"] in catalog.local_app_ids else catalog.catalog_dir
        if item.get("template_family") == "curated-profile":
            path = directory / item["curated_path"].removeprefix("catalog/")
        else:
            path = directory / "apps" / f"{item['id']}.json"
        overlay = directory / "overlays" / f"{item['id']}.json"
        recipe = json.loads(path.read_text()) if path.exists() else {}
        # Formatting and regenerated source timestamps are not recipe changes.
        recipe.pop("source", None)
        recipe.pop("validation", None)
        correction = json.loads(overlay.read_text()) if overlay.exists() else {}
        if directory not in policies:
            policies[directory] = read_json(directory / "volume-policy.json")
        policy = policies[directory]
        paths = {volume.get("container_path") for volume in recipe.get("container_contract", {}).get("volumes", [])}
        relevant = {"shared_paths": sorted(paths & set(policy.get("shared_paths", []))),
                    "application": policy.get("applications", {}).get(item["id"], []),
                    "sizes": policy.get("sizes", {}).get(item["id"], {})}
        data = json.dumps([recipe, correction, relevant, item.get("category"), item.get("category_label")],
                          sort_keys=True, separators=(",", ":")).encode()
        result[item["id"]] = hashlib.sha256(data).hexdigest()
    return result


class CatalogRefresh:
    def __init__(self, root, catalog):
        self.root = Path(root)
        self.channel = channel_for(root)
        self.seen_path = cache_root(root) / f"{self.channel}-seen.json"
        self.recipes = visible_recipes(catalog)
        baseline = read_json(self.seen_path).get("recipes")
        self.baseline = baseline if isinstance(baseline, dict) else self.recipes.copy()
        self.process = None
        self.failed = False
        self._finished = False

    def __enter__(self):
        self.start()
        return self

    def start(self):
        if self.active:
            return False
        self._finished = False
        self.failed = False
        environment = dict(os.environ, PYTHONPATH=str(self.root / "src"))
        try:
            self.process = subprocess.Popen([sys.executable, "-m", __name__, str(self.root), self.channel],
                                            env=environment, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            start_new_session=True)
        except OSError:
            self.failed = True
            self._finished = True
            return False
        return True

    def __exit__(self, *args):
        # The worker can finish downloading after the user leaves. Its result
        # is not marked seen until a later menu actually displays that catalog.
        if self.process and self.process.poll() is not None:
            self.process.wait()
        elif self.process:
            threading.Thread(target=self.process.wait, daemon=True).start()

    @property
    def active(self):
        return self.process is not None and not self._finished

    def changed(self):
        return self.active and self.process.poll() is not None

    def consume(self):
        if not self.changed():
            return False
        self._finished = True
        result = read_json(cache_root(self.root) / f"{self.channel}-result.json")
        self.failed = self.process.returncode != 0 or not result.get("ok")
        return not self.failed and bool(result.get("changed"))

    def describe(self):
        text = translate("Available applications: {count}").format(count=len(self.recipes))
        added = len(self.recipes.keys() - self.baseline.keys())
        updated = sum(self.recipes[key] != self.baseline[key] for key in self.recipes.keys() & self.baseline.keys())
        text += "\n" + translate("New applications since your last visit: {count}").format(count=added)
        if updated:
            text += "\n" + translate("Updated recipes since your last visit: {count}").format(count=updated)
        if self.active:
            text += "\n" + translate("Refreshing the application catalog...")
        elif self.failed:
            text += "\n" + translate("Catalog refresh unavailable; using the local catalog.")
        return text

    def mark_seen(self):
        try:
            write_json(self.seen_path, {"recipes": self.recipes})
        except OSError:
            self.failed = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("channel", choices=("main", "develop"))
    args = parser.parse_args()
    worker(args.root, args.channel)
