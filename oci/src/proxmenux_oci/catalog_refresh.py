"""Refresh the reviewed ProxMenux catalog without blocking the OCI menu.

GitHub's catalog commit and tree form the manifest. Files are fetched from
that immutable commit and checked against their Git blob IDs. Runtime code is
never downloaded. An installed engine always retains its bundled fallback.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

from .i18n import N_, translate

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
            value = read_json(base / name)
            channel = value.get("channel") or value.get("install_branch")
            if channel in ("main", "develop"):
                return channel
            beta = value.get("beta_program")
            if isinstance(beta, dict) and beta.get("status") == "active":
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


def bundle_hash(root):
    # Cheap menu-time engine-update detection; no scan of the bundled recipes.
    return hashlib.sha256((Path(root) / "catalog/index.json").read_bytes()).hexdigest()


@contextmanager
def snapshot_lock(root):
    cache = cache_root(root)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "snapshots.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def pin_catalog(root, directory=None):
    """Select and lease atomically against pruning; no network/worker wait."""
    explicit = directory
    directory = Path(directory) if directory is not None else current_catalog(root)
    if (directory.parent != cache_root(root) / "snapshots"
            or not re.fullmatch(r"[0-9a-f]{40}(?:-[0-9a-f]{12})?", directory.name)):
        return directory, None
    with snapshot_lock(root):
        directory = Path(explicit) if explicit is not None else current_catalog(root)
        snapshots = cache_root(root) / "snapshots"
        if directory.parent != snapshots or not directory.is_dir():
            return directory, None
        leases = cache_root(root) / "leases"
        leases.mkdir(exist_ok=True)
        lease = (leases / directory.name).open("a")
        fcntl.flock(lease, fcntl.LOCK_SH)
        return directory, lease


def prune_snapshots(root):
    """Retain channel pointers and live readers; locks survive PID reuse/crashes."""
    cache = cache_root(root)
    with snapshot_lock(root):
        keep = {read_json(p).get("snapshot", read_json(p).get("revision"))
                for p in cache.glob("*-current.json")}
        leases = cache / "leases"
        leases.mkdir(exist_ok=True)
        for directory in (cache / "snapshots").glob("*"):
            if (not SHA.fullmatch(directory.name.split("-")[0])
                    or directory.name in keep or directory.is_symlink() or not directory.is_dir()):
                continue
            lease_path = leases / directory.name
            with lease_path.open("a") as lease:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(directory)
                lease_path.unlink(missing_ok=True)


def supported_profile_keys(root):
    keys = set()
    for folder in ("apps", "curated", "overlays"):
        for path in (Path(root) / "catalog" / folder).glob("*.json"):
            value = json.loads(path.read_text())
            keys.update(value.get("proxmox", {}).get("installer_profile", {}))
    return keys


def filter_compatible_recipes(root, directory, previous):
    """Silently defer new engine capabilities, retaining compatible old apps."""
    from .catalog import Catalog
    supported = supported_profile_keys(root)
    candidate = Catalog(Path(root), catalog_dir=directory)
    old = Catalog(Path(root), catalog_dir=previous)
    old_items = {item["id"]: item for item in old.load_index()["applications"]}
    effective_items = {item["id"]: item for item in candidate.load_index()["applications"]}
    index = json.loads((directory / "index.json").read_text())
    accepted = []
    old_fingerprints = None
    for item in index["applications"]:
        effective = effective_items[item["id"]]
        if effective.get("hidden") or not effective.get("automatic_install_candidate"):
            accepted.append(item)
            continue
        template = candidate._compose_item(item)
        profile = template.get("proxmox", {}).get("installer_profile", {})
        if set(profile) <= supported:
            accepted.append(item)
            continue
        fallback = old_items.get(item["id"])
        if fallback is None:
            continue
        template = old._compose_item(fallback)
        if not set(template.get("proxmox", {}).get("installer_profile", {})) <= supported:
            continue
        # Materialize the previously composed contract: its old overlay/volume
        # policy must not be combined with a newly downloaded incompatible one.
        app_id = item["id"]
        for folder in ("apps", "curated"):
            path = directory / folder / f"{app_id}.json"
            path.parent.mkdir(exist_ok=True)
            write_json(path, template)
        (directory / "overlays" / f"{app_id}.json").unlink(missing_ok=True)
        if old_fingerprints is None:
            old_fingerprints = visible_recipes(old)
        fallback = dict(fallback, _retained_recipe_hash=old_fingerprints.get(app_id), template_family="curated-profile",
                        curated_path=f"catalog/curated/{app_id}.json",
                        _retained_recipe=True)
        accepted.append(fallback)
    index["applications"] = accepted
    write_json(directory / "index.json", index)


def current_catalog(root, channel=None):
    root = Path(root)
    channel = channel or channel_for(root)
    value = read_json(cache_root(root) / f"{channel}-current.json")
    revision = value.get("revision", "")
    if (isinstance(revision, str) and SHA.fullmatch(revision)
            and value.get("schema_hash") == schema_hash(root)
            and value.get("engine_api") == CATALOG_API
            and value.get("bundle_hash") == bundle_hash(root)):
        snapshot = value.get("snapshot", revision)
        if not isinstance(snapshot, str) or not re.fullmatch(revision + r"(?:-[0-9a-f]{12})?", snapshot):
            return root / "catalog"
        path = cache_root(root) / "snapshots" / snapshot
        index = read_json(path / "index.json")
        if (index.get("kind") == "proxmenux.oci-catalog-index"
                and isinstance(index.get("applications"), list)):
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
        error.close()
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


def validate_snapshot(root, directory, *, allow_empty=False):
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
    if not ids and not allow_empty:
        raise ValueError("The remote catalog is empty")
    catalog = Catalog(Path(root), catalog_dir=directory)
    for item in catalog.load_index()["applications"]:
        if not item.get("hidden") and item.get("automatic_install_candidate"):
            validator.validate(catalog._compose_item(item))


def progress_path(root, channel):
    return cache_root(root) / f"{channel}-progress.json"


def read_progress(root, channel):
    """The step the refresh worker last reported, as (percent, translated text)."""
    state = read_json(progress_path(root, channel))
    percent = state.get("percent")
    if type(percent) is not int or not 0 <= percent <= 100 or not isinstance(state.get("message"), str):
        return 0, translate("Refreshing the application catalog...")
    values = state.get("values") if isinstance(state.get("values"), dict) else {}
    try:
        return percent, translate(state["message"]).format(**values)
    except (KeyError, IndexError, ValueError):
        return percent, translate(state["message"])


def synchronize(root, channel, fetch=request, force=False, progress=None):
    """Download changed JSON files into a private snapshot, then publish once."""
    report = progress or (lambda percent, message, **values: None)
    root = Path(root)
    cache = cache_root(root)
    cache.mkdir(parents=True, exist_ok=True)
    pointer = cache / f"{channel}-current.json"
    previous = read_json(pointer)
    active = current_catalog(root, channel)
    capabilities = hashlib.sha256(json.dumps(sorted(supported_profile_keys(root))).encode()).hexdigest()
    force = force or previous.get("profile_capabilities") != capabilities
    etag = previous.get("etag") if active != root / "catalog" and not force else None
    url = f"https://api.github.com/repos/{REPOSITORY}/commits?sha={channel}&path=oci/catalog&per_page=1"
    report(5, N_("Checking the catalog version..."))
    body, etag = fetch(url, etag)
    if body is None:
        return False
    commits = json.loads(body)
    revision = commits[0]["sha"]
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("Invalid catalog revision")
    if previous.get("revision") == revision and active != root / "catalog" and not force:
        write_json(pointer, {**previous, "etag": etag})
        return False
    report(15, N_("Reading the list of catalog files..."))
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
        if relative in entries:
            raise ValueError("Duplicate catalog manifest path")
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
        deadline = time.monotonic() + 90
        total = len(entries)
        downloaded = [0]
        counter = threading.Lock()
        report(20, N_("Downloading the catalog files ({done}/{total})..."), done=0, total=total)

        def download(pair):
            if time.monotonic() > deadline:
                raise TimeoutError("Catalog download exceeded its time limit")
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
            with counter:
                downloaded[0] += 1
                report(20 + 65 * downloaded[0] // total, N_("Downloading the catalog files ({done}/{total})..."),
                       done=downloaded[0], total=total)

        pool = ThreadPoolExecutor(max_workers=4)
        try:
            list(pool.map(download, entries.items()))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        report(88, N_("Checking the downloaded applications..."))
        validate_snapshot(root, staging)
        filter_compatible_recipes(root, staging, active)
        validate_snapshot(root, staging, allow_empty=True)
        destination = (active if previous.get("revision") == revision and active != root / "catalog"
                       else snapshots / revision)
        if destination.exists():
            staged_files = {str(p.relative_to(staging)) for p in staging.rglob("*.json")}
            intact = all((destination / relative).is_file()
                         and not (destination / relative).is_symlink()
                         and (destination / relative).read_bytes() == (staging / relative).read_bytes()
                         for relative in staged_files)
            existing = {str(p.relative_to(destination)) for p in destination.rglob("*.json")}
            if not intact or existing != staged_files:
                # Repair without removing a snapshot another wizard may still hold.
                destination = snapshots / (revision + "-" + uuid.uuid4().hex[:12])
        report(95, N_("Applying the new catalog..."))
        with snapshot_lock(root):
            if not destination.exists():
                os.replace(staging, destination)
            write_json(pointer, {"revision": revision, "snapshot": destination.name, "etag": etag,
                       "schema_hash": schema_hash(root), "engine_api": CATALOG_API,
                       "bundle_hash": bundle_hash(root), "profile_capabilities": capabilities})
    return destination != active


def worker(root, channel, force=False):
    cache = cache_root(root)
    cache.mkdir(parents=True, exist_ok=True)
    last = {"percent": -1, "time": 0.0}

    def report(percent, message, **values):
        # Every new percent is written; the same one at most a few times a second.
        now = time.monotonic()
        if percent == last["percent"] and now - last["time"] < 0.25:
            return
        last.update(percent=percent, time=now)
        try:
            write_json(progress_path(root, channel), {"percent": percent, "message": message, "values": values})
        except OSError:
            pass
    with (cache / "refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            for partial in (cache / "snapshots").glob(".download-*"):
                if partial.is_dir() and not partial.is_symlink():
                    shutil.rmtree(partial)
            changed = synchronize(root, channel, force=force, progress=report)
            write_json(cache / f"{channel}-result.json", {"ok": True, "changed": changed})
        except Exception as error:
            write_json(cache / f"{channel}-result.json", {"ok": False, "error": str(error)[:400]})
        finally:
            prune_snapshots(root)


def visible_recipes(catalog, applications=None):
    """Same availability rule as the menu; count new IDs, not net growth."""
    result = {}
    policies = {}
    if applications is None:
        applications = catalog.load_index()["applications"]
    for item in applications:
        if item.get("hidden") or not item.get("automatic_install_candidate"):
            continue
        if item.get("_retained_recipe") and item.get("_retained_recipe_hash"):
            result[item["id"]] = item["_retained_recipe_hash"]
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


def menu_catalog(catalog):
    """Reuse menu metadata while every recipe and policy input is unchanged.

    This caches display data only. Installation still reads and validates the
    selected recipe normally. No TTL can hide a newly published local file.
    """
    def signature():
        directories = {catalog.catalog_dir}
        if catalog._include_local and source_settings(catalog.root).get('local_apps'):
            directories.add(catalog.root / 'catalog')
        paths = {Path(__file__), Path(__file__).with_name('catalog.py'),
                 catalog.schema_path, catalog.root.parent / 'catalog-source.json'}
        for directory in directories:
            paths.update(directory / name for name in ROOT_FILES)
            for folder in ('apps', 'curated', 'overlays'):
                paths.update((directory / folder).glob('*.json'))
        rows = []
        for path in sorted(paths):
            try:
                s = path.stat()
                rows.append((str(path), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns))
            except FileNotFoundError:
                rows.append((str(path), None))
        return hashlib.sha256(json.dumps([str(catalog.catalog_dir), rows]).encode()).hexdigest()

    cache = cache_root(catalog.root) / ('menu-' + channel_for(catalog.root) + '.json')
    try:
        before = signature()
        value = read_json(cache)
        if value.get('version') == 1 and value.get('signature') == before:
            payload, recipes = value['index'], value['recipes']
            apps = payload['applications']
            local = value['local_app_ids']
            if (isinstance(apps, list) and all(isinstance(app, dict) and isinstance(app.get('id'), str) for app in apps)
                    and isinstance(recipes, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in recipes.items())
                    and isinstance(local, list) and all(isinstance(v, str) for v in local)):
                catalog.local_app_ids = set(local)
                return payload, recipes
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        before = None
    payload = catalog.load_index()
    recipes = visible_recipes(catalog, payload['applications'])
    try:
        if before is not None and signature() == before:
            write_json(cache, {'version': 1, 'signature': before, 'index': payload,
                               'recipes': recipes, 'local_app_ids': sorted(catalog.local_app_ids)})
    except OSError:
        pass  # A read-only cache must never prevent opening OCI.
    return payload, recipes


class CatalogRefresh:
    def __init__(self, root, catalog, applications=None, recipes=None):
        self.root = Path(root)
        self.channel = channel_for(root)
        self.seen_path = cache_root(root) / f"{self.channel}-seen.json"
        self.recipes = visible_recipes(catalog, applications) if recipes is None else recipes
        self.displayed_directory = catalog.catalog_dir
        baseline = read_json(self.seen_path).get("recipes")
        self.process = None
        self.failed = False
        self._finished = False
        if isinstance(baseline, dict):
            self.baseline = baseline
        else:
            # The first visit sets what counts as already known.
            self.baseline = self.recipes.copy()
            self.mark_seen()

    def __enter__(self):
        self.start()
        return self

    def start(self, force=False):
        if self.active:
            return False
        self._finished = False
        self.failed = False
        environment = dict(os.environ, PYTHONPATH=str(self.root / "src"))
        try:
            # A new refresh starts from zero, never from the last one's steps.
            write_json(progress_path(self.root, self.channel),
                       {"percent": 0, "message": N_("Refreshing the application catalog..."), "values": {}})
        except OSError:
            pass
        try:
            command = [sys.executable, "-m", __name__, str(self.root), self.channel]
            if force:
                command.append("--force")
            self.process = subprocess.Popen(command,
                                            env=environment, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            start_new_session=True)
        except OSError:
            self.failed = True
            self._finished = True
            return False
        return True

    def __exit__(self, *args):
        # The worker can finish downloading after the user leaves. Its new
        # applications stay new until the user opens their list.
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
        directory = current_catalog(self.root, self.channel)
        changed = directory != self.displayed_directory
        if changed:
            self.displayed_directory = directory
        return changed

    def new_ids(self):
        """The applications added since the user last opened the list of new ones."""
        return sorted(self.recipes.keys() - self.baseline.keys())

    def label(self):
        added = len(self.new_ids())
        return (translate("New applications ({count})").format(count=added) if added
                else translate("Refresh catalog"))

    def wait(self):
        if self.process is not None and not self._finished:
            self.process.wait()

    def progress(self):
        """(percent, text) while the worker runs, None once it has finished."""
        if self.process is None or self._finished or self.process.poll() is not None:
            return None
        return read_progress(self.root, self.channel)

    def mark_seen(self):
        """Opening the list of new applications makes them known."""
        self.baseline = self.recipes.copy()
        try:
            write_json(self.seen_path, {"recipes": self.recipes})
        except OSError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("channel", choices=("main", "develop"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    worker(args.root, args.channel, args.force)
