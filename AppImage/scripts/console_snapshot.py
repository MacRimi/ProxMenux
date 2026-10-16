"""Lease-gated Proxmox snapshot shared by the Monitor and console TUI."""

import grp
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time


DEFAULT_PATH = Path("/run/proxmenux-monitor/console.json")
DEFAULT_STATE_DIR = Path("/run/proxmenux-console")
_STATUS = {"starting", "ok", "stale", "unavailable", "error"}
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|.)")
_MAX_BYTES = 1024 * 1024


def _fields(raw, names):
    return {name: raw.get(name) for name in names}


def normalize_resources(raw):
    """Map the all-types /cluster/resources response to schema 1 data."""
    if not isinstance(raw, list):
        raise ValueError("resources response is not a list")
    nodes, guests, storages = [], [], []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "node":
            node = _fields(item, ("status", "cpu", "maxcpu", "mem", "maxmem",
                                  "disk", "maxdisk", "uptime", "level"))
            node["name"] = item.get("node")
            node["cgroup_mode"] = item.get("cgroup-mode", item.get("cgroup_mode"))
            nodes.append(node)
        elif kind in ("qemu", "lxc"):
            guest = _fields(item, ("vmid", "name", "node", "status", "cpu", "maxcpu",
                                   "mem", "maxmem", "disk", "maxdisk", "uptime",
                                   "netin", "netout", "diskread", "diskwrite",
                                   "hastate", "template", "lock"))
            guest["type"] = kind
            tags = item.get("tags")
            guest["tags"] = tags.split(";") if isinstance(tags, str) else []
            if guest["template"] is not None:
                guest["template"] = bool(guest["template"])
            guests.append(guest)
        elif kind == "storage":
            storage = _fields(item, ("id", "storage", "node", "plugintype", "shared",
                                     "status", "disk", "maxdisk"))
            if storage["shared"] is not None:
                storage["shared"] = bool(storage["shared"])
            content = item.get("content")
            storage["content"] = content.split(",") if isinstance(content, str) else (
                content if isinstance(content, list) else [])
            storages.append(storage)
    guests.sort(key=lambda row: (
        -(row["cpu"] or 0) * (row["maxcpu"] or 0), -(row["mem"] or 0)))
    truncated = len(guests) > 2000
    return {"nodes": nodes, "guests": guests[:2000], "storages": storages,
            "truncated": truncated}


def normalize_cluster_status(raw):
    """Map /cluster/status, including standalone and non-quorate states."""
    if not isinstance(raw, list):
        raise ValueError("cluster status response is not a list")
    cluster = next((item for item in raw if isinstance(item, dict) and
                    item.get("type") == "cluster"), None)
    members = []
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "node":
            continue
        member = _fields(item, ("name", "nodeid", "ip", "level"))
        member["online"] = bool(item["online"]) if "online" in item else None
        member["local"] = bool(item["local"]) if "local" in item else None
        members.append(member)
    return {
        "is_cluster": cluster is not None,
        "name": cluster.get("name") if cluster else None,
        "quorate": bool(cluster["quorate"]) if cluster and "quorate" in cluster else None,
        "nodes_total": cluster.get("nodes") if cluster else len(members),
        "nodes_online": sum(member["online"] is True for member in members),
        "config_version": cluster.get("version") if cluster else None,
        "members": members,
    }


def _empty_cluster():
    return {"status": "starting", "observed_at": None, "is_cluster": None,
            "name": None, "quorate": None, "nodes_total": None,
            "nodes_online": None, "config_version": None, "members": [], "error": None}


def _empty_resources():
    return {"status": "starting", "observed_at": None, "truncated": False,
            "nodes": [], "guests": [], "storages": [], "error": None}


def write_snapshot(data, path=DEFAULT_PATH):
    """Replace a snapshot atomically, rechecking the optional console group."""
    path = Path(path)
    try:
        gid = grp.getgrnam("proxmenux-console").gr_gid
    except KeyError:
        gid = None
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o750 if gid is not None else 0o700)
    if gid is not None:
        os.chown(directory, -1, gid)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            os.fchmod(stream.fileno(), 0o640 if gid is not None else 0o600)
            if gid is not None:
                os.fchown(stream.fileno(), -1, gid)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def _fit_document(data):
    """Keep large guest inventories under the snapshot size contract."""
    def size():
        return len(json.dumps(data, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))

    if size() <= _MAX_BYTES:
        return data
    data["resources"] = dict(data["resources"])
    data["resources"]["truncated"] = True
    for section, key in (("resources", "guests"), ("resources", "storages"),
                         ("resources", "nodes"), ("cluster", "members")):
        if section == "cluster":
            data["cluster"] = dict(data["cluster"])
        rows = data[section][key]
        low, high = 0, len(rows)
        while low < high:
            middle = (low + high + 1) // 2
            data[section][key] = rows[:middle]
            if size() <= _MAX_BYTES:
                low = middle
            else:
                high = middle - 1
        data[section][key] = rows[:low]
        if size() <= _MAX_BYTES:
            return data
    raise ValueError("snapshot exceeds 1 MiB")


def touch_lease(state_dir=DEFAULT_STATE_DIR, now=None):
    """Create or refresh the TUI's client lease."""
    lease = Path(state_dir) / "client" / "lease"
    lease.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lease, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("lease is not a regular file")
    finally:
        os.close(descriptor)
    stamp = time.time() if now is None else now
    os.utime(lease, (stamp, stamp), follow_symlinks=False)
    return lease


class _Source:
    def __init__(self, empty):
        self.data = empty()
        self.failures = 0

    def succeed(self, data, now):
        self.data.update(data)
        self.data.update(status="ok", observed_at=now, error=None)
        self.failures = 0

    def fail(self, exc):
        self.failures += 1
        self.data["error"] = str(exc)[:200]
        if self.failures >= 3:
            self.data["status"] = "error"
        elif self.data["observed_at"] is None:
            self.data["status"] = "unavailable"
        else:
            self.data["status"] = "stale"


class Publisher:
    """One publisher instance; publish_once supports deterministic callers."""

    def __init__(self, get_node_name, get_resources, run_pvesh, read_language,
                 path=DEFAULT_PATH, state_dir=DEFAULT_STATE_DIR, clock=time.time,
                 get_pve_version=None, version=None):
        self.get_node_name = get_node_name
        self.get_resources = get_resources
        self.run_pvesh = run_pvesh
        self.read_language = read_language
        self.get_pve_version = get_pve_version
        self.version = version
        self.path = Path(path)
        self.lease = Path(state_dir) / "client" / "lease"
        self.clock = clock
        self.cluster = _Source(_empty_cluster)
        self.resources = _Source(_empty_resources)
        self.last_publish = None
        self.last_cluster_call = None
        self.lease_active = False
        self._pve_version = None
        self._pve_version_at = None

    def _node(self, now):
        try:
            name = self.get_node_name()
        except Exception as exc:
            return {"status": "error", "observed_at": None, "name": None,
                    "pve_version": None, "error": str(exc)[:200]}
        if (self.get_pve_version is not None and
                (self._pve_version_at is None or now - self._pve_version_at >= 300)):
            try:
                self._pve_version = self.get_pve_version()
            except Exception:
                self._pve_version = None
            self._pve_version_at = now
        return {"status": "ok", "observed_at": now, "name": name,
                "pve_version": self._pve_version, "error": None}

    def _document(self, now):
        try:
            language = self.read_language() or "en"
        except Exception:
            language = "en"
        return {"schema": 1,
                "generator": {"name": "proxmenux-monitor", "version": self.version,
                              "pid": os.getpid()},
                "observed_at": now, "publish_interval_s": 5,
                "language": language, "node": self._node(now),
                "cluster": self.cluster.data, "resources": self.resources.data}

    def write_initial(self, now=None):
        now = self.clock() if now is None else now
        write_snapshot(_fit_document(self._document(now)), self.path)

    def _fresh_lease(self, now):
        try:
            info = os.lstat(self.lease)
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and 0 <= now - info.st_mtime < 15

    def publish_once(self, now=None):
        now = self.clock() if now is None else now
        active = self._fresh_lease(now)
        if not active:
            self.lease_active = False
            return False
        due = (not self.lease_active or self.last_publish is None or
               now - self.last_publish >= 5)
        self.lease_active = True
        if not due:
            return False
        try:
            self.resources.succeed(normalize_resources(self.get_resources()), now)
        except Exception as exc:
            self.resources.fail(exc)
        if self.last_cluster_call is None or now - self.last_cluster_call >= 10:
            self.last_cluster_call = now
            try:
                self.cluster.succeed(normalize_cluster_status(self.run_pvesh()), now)
            except Exception as exc:
                self.cluster.fail(exc)
        write_snapshot(_fit_document(self._document(now)), self.path)
        self.last_publish = now
        return True

    def run(self):
        while True:
            try:
                self.publish_once()
            except Exception:
                pass
            time.sleep(2 if not self.lease_active else 1)


_publisher = None
_publisher_lock = threading.Lock()


def ensure_publisher(get_node_name, get_resources, run_pvesh, read_language,
                     path=DEFAULT_PATH, state_dir=DEFAULT_STATE_DIR,
                     clock=time.time, get_pve_version=None, version=None):
    """Write STARTING immediately and start exactly one daemon publisher."""
    global _publisher
    with _publisher_lock:
        if _publisher is not None:
            return _publisher
        publisher = Publisher(get_node_name, get_resources, run_pvesh,
                              read_language, path, state_dir, clock,
                              get_pve_version, version)
        try:
            publisher.write_initial()
        except Exception:
            pass
        thread = threading.Thread(target=publisher.run, daemon=True)
        thread.start()
        _publisher = publisher
        return publisher


def _text(value, limit):
    if not isinstance(value, str):
        return None
    value = _ANSI.sub("", value)
    return "".join(char for char in value
                   if ord(char) >= 32 and not 127 <= ord(char) <= 159)[:limit]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _boolean(value):
    return value if isinstance(value, bool) else None


def _clean_row(row, fields):
    if not isinstance(row, dict):
        return None
    result = {}
    for name, kind in fields.items():
        value = row.get(name)
        if kind == "name":
            result[name] = _text(value, 64)
        elif kind == "text":
            result[name] = _text(value, 200)
        elif kind == "number":
            result[name] = _number(value)
        elif kind == "bool":
            result[name] = _boolean(value)
    return result


_NODE_FIELDS = {"name": "name", "pve_version": "text", "error": "text"}
_MEMBER_FIELDS = {"name": "name", "nodeid": "number", "online": "bool",
                  "local": "bool", "ip": "text", "level": "text"}
_RESOURCE_NODE_FIELDS = {"name": "name", "status": "text", "cpu": "number",
                         "maxcpu": "number", "mem": "number", "maxmem": "number",
                         "disk": "number", "maxdisk": "number", "uptime": "number",
                         "level": "text", "cgroup_mode": "number"}
_GUEST_FIELDS = {"vmid": "number", "type": "text", "name": "name",
                 "node": "name", "status": "text", "cpu": "number",
                 "maxcpu": "number", "mem": "number", "maxmem": "number",
                 "disk": "number", "maxdisk": "number", "uptime": "number",
                 "netin": "number", "netout": "number", "diskread": "number",
                 "diskwrite": "number", "hastate": "text", "template": "bool",
                 "lock": "text"}
_STORAGE_FIELDS = {"id": "text", "storage": "name", "node": "name",
                   "plugintype": "text", "shared": "bool", "status": "text",
                   "disk": "number", "maxdisk": "number"}


class Snapshot:
    """Validated data with attribute access for top-level sections."""

    def __init__(self, data, age_s, reason=None):
        self.data = data
        self.age_s = age_s
        self.reason = reason

    def __getitem__(self, key):
        return self.data[key]

    def __getattr__(self, key):
        try:
            return self.data[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    @classmethod
    def unavailable(cls, reason):
        return cls({"schema": 1, "generator": {"name": None, "version": None,
                                               "pid": None},
                    "observed_at": None, "publish_interval_s": 5,
                    "language": "en",
                    "node": {"status": "error", "observed_at": None,
                             "name": None, "pve_version": None, "error": reason},
                    "cluster": {**_empty_cluster(), "status": "unavailable"},
                    "resources": {**_empty_resources(), "status": "unavailable"}},
                   None, reason)


def load_snapshot(path=DEFAULT_PATH, now=None):
    """Read untrusted snapshot data without leaking errors to curses."""
    now = time.time() if now is None else now
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
            raise ValueError("unsupported schema")
        if not all(isinstance(data.get(key), dict) for key in
                   ("generator", "node", "cluster", "resources")):
            raise ValueError("invalid sections")
        if not all(isinstance(data["resources"].get(key), list) for key in
                   ("nodes", "guests", "storages")):
            raise ValueError("invalid resource lists")
        if not isinstance(data["cluster"].get("members"), list):
            raise ValueError("invalid members")
        for source in ("cluster", "resources"):
            if data[source].get("status") not in _STATUS:
                raise ValueError("invalid source status")
        if data["node"].get("status") not in ("ok", "error"):
            raise ValueError("invalid node status")
        cleaned = {"schema": 1,
                   "generator": _clean_row(data["generator"],
                                           {"name": "text", "version": "text", "pid": "number"}),
                   "observed_at": _number(data.get("observed_at")),
                   "publish_interval_s": _number(data.get("publish_interval_s")),
                   "language": _text(data.get("language"), 16) or "en"}
        cleaned["node"] = _clean_row(data["node"], _NODE_FIELDS)
        cleaned["node"].update(status=data["node"]["status"],
                               observed_at=_number(data["node"].get("observed_at")))
        cluster = data["cluster"]
        cleaned["cluster"] = _clean_row(cluster,
            {"is_cluster": "bool", "name": "name", "quorate": "bool",
             "nodes_total": "number", "nodes_online": "number",
             "config_version": "number", "error": "text"})
        cleaned["cluster"].update(status=cluster["status"],
            observed_at=_number(cluster.get("observed_at")),
            members=[row for item in cluster["members"][:2000]
                     if (row := _clean_row(item, _MEMBER_FIELDS)) is not None])
        resources = data["resources"]
        cleaned["resources"] = {"status": resources["status"],
                                "observed_at": _number(resources.get("observed_at")),
                                "truncated": _boolean(resources.get("truncated")) or False,
                                "error": _text(resources.get("error"), 200)}
        for key, fields in (("nodes", _RESOURCE_NODE_FIELDS),
                            ("guests", _GUEST_FIELDS), ("storages", _STORAGE_FIELDS)):
            limit = 2000 if key == "guests" else 10000
            cleaned_rows = []
            for item in resources[key][:limit]:
                row = _clean_row(item, fields)
                if row is None:
                    continue
                if key == "guests":
                    tags = item.get("tags")
                    row["tags"] = ([_text(tag, 32) for tag in tags[:16]
                                    if isinstance(tag, str)] if isinstance(tags, list) else [])
                elif key == "storages":
                    content = item.get("content")
                    row["content"] = ([_text(part, 64) for part in content[:32]
                                       if isinstance(part, str)] if isinstance(content, list) else [])
                cleaned_rows.append(row)
            cleaned["resources"][key] = cleaned_rows
        observed = cleaned["observed_at"]
        return Snapshot(cleaned, max(0, now - observed) if observed is not None else None)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return Snapshot.unavailable(str(exc)[:200])
