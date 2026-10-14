"""Trusted, run-scoped package observation captured before a temporary CT stops.

The runner only writes this private handoff, not the shared registry. The
Monitor consumes it under its existing registry lock after the process exits.
Never accepted as an HTTP payload and never refreshes package indexes.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

import managed_installs

OBSERVATION_DIR = Path("/run/proxmenux/lxc-update-observations")
MAX_AGE = 3600
MAX_BYTES = 2 * 1024 * 1024


def _path(vmid: int, run_id: str) -> Path:
    if int(vmid) <= 0 or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", run_id):
        raise ValueError("invalid LXC update identity")
    return OBSERVATION_DIR / f"{int(vmid)}-{run_id}.json"


def _started_path(vmid: int, run_id: str) -> Path:
    _path(vmid, run_id)
    return OBSERVATION_DIR / f"{int(vmid)}-{run_id}.started"


def _private_directory(*, create=True) -> None:
    if create:
        OBSERVATION_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = OBSERVATION_DIR.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise OSError("unsafe LXC observation directory")


def mark_started(vmid: int, run_id: str) -> None:
    """Record that this run started a stopped CT before it can change state."""
    path = _started_path(vmid, run_id)
    _private_directory()
    payload = {
        "vmid": int(vmid),
        "run_id": run_id,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    fd, temporary = tempfile.mkstemp(prefix=".started-", dir=OBSERVATION_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, path)
        print(f"[ProxMenux] LXC update started: vmid={int(vmid)} run_id={run_id}", flush=True)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_started(vmid: int, run_id: str) -> bool | None:
    """Return True for a trusted start marker, False when absent, else None."""
    path = _started_path(vmid, run_id)

    def reject(reason: str) -> None:
        print(f"[ProxMenux] LXC update start marker rejected: vmid={int(vmid)} "
              f"run_id={run_id} reason={reason}", flush=True)
        return None

    try:
        _private_directory(create=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        return reject(type(exc).__name__)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    except OSError as exc:
        return reject(type(exc).__name__)
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > MAX_BYTES):
                return reject('unsafe-file')
            marker = json.load(handle)
        started = datetime.datetime.fromisoformat(marker["started_at"])
        age = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()
        if (not isinstance(marker, dict) or marker.get("vmid") != int(vmid)
                or marker.get("run_id") != run_id or not 0 <= age <= MAX_AGE):
            return reject('identity-age-or-shape')
        return True
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        return reject(type(exc).__name__)


def capture(vmid: int, run_id: str, *, refresh_indexes: bool = False,
            include_apps: bool = False) -> dict:
    path = _path(vmid, run_id)
    _private_directory()
    # Remove only obsolete private handoffs left by terminated backend runs.
    now = datetime.datetime.now(datetime.timezone.utc)
    for old in OBSERVATION_DIR.iterdir():
        info = old.lstat()
        if (re.fullmatch(r"[1-9][0-9]*-[A-Za-z0-9._:-]{1,128}(?:\.json|\.started)", old.name)
                and stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and now.timestamp() - info.st_mtime > MAX_AGE):
            old.unlink()
    entry = {"id": f"lxc:{int(vmid)}", "type": "lxc", "_vmid": str(int(vmid))}
    native_detected = False
    try:
        detected = managed_installs._detect_lxc_containers(only_vmid=int(vmid))
        if not detected:
            raise RuntimeError("running LXC detection unavailable or disabled")
        entry = detected[0]
        native_detected = not (entry.get('_is_oci') or entry.get('_managed_oci_app'))
        if refresh_indexes:
            # This is a separate, explicitly requested maintenance action,
            # never the read-only button or the normal post-update capture.
            if entry.get('_is_oci') or entry.get('_managed_oci_app'):
                raise RuntimeError('OCI containers require their own updater')
            family = managed_installs._probe_lxc_os(str(vmid))
            commands = {'debian': ['apt-get', 'update', '--error-on=any'],
                        'ubuntu': ['apt-get', 'update', '--error-on=any'],
                        'alpine': ['apk', 'update']}
            if family not in commands:
                raise RuntimeError('unsupported or unknown current OS')
            refreshed = subprocess.run([managed_installs._PCT_BIN, 'exec', str(vmid),
                '--', *commands[family]], capture_output=True, text=True,
                timeout=managed_installs._LXC_CACHE_REFRESH_TIMEOUT_SEC)
            if refreshed.returncode != 0:
                raise RuntimeError('package index refresh failed; no installation was attempted')
        result = managed_installs._check_lxc_updates(entry, refresh_package_cache=False)
    except Exception as exc:
        entry["_os_family"] = None
        result = {"available": False, "last_check": managed_installs._now_iso(),
                  "error": f"post-update package check failed: {exc}"}
    observation = {"vmid": int(vmid), "run_id": run_id,
                   "captured_at": now.isoformat(), "entry": entry, "result": result}
    # Only the post-install runner requests app probes. Check-only and the
    # maintenance preflight keep their original OS-only contract; OCI never
    # enters the generic app probe path, even when explicitly requested.
    if include_apps and not refresh_indexes and native_detected:
        try:
            import lxc_apps
            observation['apps'] = lxc_apps.capture_installed_observations(vmid)
        except Exception:
            observation['apps'] = None
    fd, temporary = tempfile.mkstemp(prefix=".observation-", dir=OBSERVATION_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(observation, handle)
        os.replace(temporary, path)
        print(f"[ProxMenux] LXC observation captured: vmid={int(vmid)} "
              f"run_id={run_id} os={entry.get('_os_family')} "
              f"count={result.get('_count')} error={bool(result.get('error'))}", flush=True)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return observation


def read(vmid: int, run_id: str) -> dict | None:
    path = _path(vmid, run_id)
    def reject(reason: str) -> None:
        # Only identity and a fixed reason, never the guest's payload or secrets.
        print(f"[ProxMenux] LXC observation rejected: vmid={int(vmid)} "
              f"run_id={run_id} reason={reason}", flush=True)
        return None
    try:
        _private_directory(create=False)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > MAX_BYTES):
                return reject('unsafe-file')
            observation = json.load(handle)
        if not isinstance(observation, dict):
            return reject('invalid-document')
        captured = datetime.datetime.fromisoformat(observation["captured_at"])
        age = (datetime.datetime.now(datetime.timezone.utc) - captured).total_seconds()
        entry, result = observation["entry"], observation["result"]
        if (observation["vmid"] != int(vmid) or observation["run_id"] != run_id
                or not 0 <= age <= MAX_AGE or not isinstance(entry, dict)
                or entry.get("id") != f"lxc:{int(vmid)}" or entry.get("type") != "lxc"
                or str(entry.get("_vmid")) != str(int(vmid)) or not isinstance(result, dict)):
            return reject('identity-age-or-shape')
        if not result.get("error"):
            # An incomplete result is unknown, not an implicitly successful zero.
            is_oci = bool(entry.get('_is_oci') or entry.get('_managed_oci_app'))
            if ((not is_oci and entry.get("_os_family") not in managed_installs._SUPPORTED_OS_FAMILIES)
                    or not isinstance(result.get("available"), bool)
                    or not result.get("last_check")
                    or any(type(result.get(key)) is not int or result[key] < 0
                           for key in ("_count", "_security_count"))
                    or not isinstance(result.get("_packages"), list)):
                return reject('incomplete-success')
            # OCI skips the generic OS probe, so no family is required. Its
            # trusted result must nevertheless be the complete skipped zero.
            if is_oci and (result['available'] or result['_count'] != 0
                    or result['_security_count'] != 0 or result['_packages']):
                return reject('invalid-oci-skip')
        print(f"[ProxMenux] LXC observation accepted: vmid={int(vmid)} "
              f"run_id={run_id} count={result.get('_count')} "
              f"error={bool(result.get('error'))}", flush=True)
        return observation
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        return reject(type(exc).__name__)


def discard(vmid: int, run_id: str) -> None:
    try:
        _private_directory(create=False)
        for path in (_path(vmid, run_id), _started_path(vmid, run_id)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vmid", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument('--mark-started', action='store_true',
                        help='Record that this run started a previously stopped CT')
    parser.add_argument('--include-apps', action='store_true',
                        help='Capture registered installed versions after an update')
    args = parser.parse_args(argv)
    try:
        if args.mark_started:
            mark_started(args.vmid, args.run_id)
            return 0
        capture(args.vmid, args.run_id, include_apps=args.include_apps)
        return 0
    except Exception as exc:
        print(f"Post-update package observation unavailable: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
