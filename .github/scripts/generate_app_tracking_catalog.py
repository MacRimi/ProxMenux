#!/usr/bin/env python3
"""Build a verified ProxMenux LXC application-version tracking catalog.

The source of truth is a pinned snapshot of community-scripts/ProxmoxVE,
downloaded through the GitHub REST API.  Only ct/*.sh launchers are considered.

An operational hint is emitted only when two independent pieces of the helper
scripts agree:

* file: the LXC update script reads the cache written by the shared deploy
  helper, and the matching install script deploys the same app/repository; or
* dpkg/apk: the package is installed by the install script and checked or
  explicitly upgraded by the LXC update script.

Everything else is retained in the audit report rather than guessed into the
runtime JSON.  The script uses only Python's standard library and runs on macOS.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_REPOSITORY = "community-scripts/ProxmoxVE"
DEFAULT_REF = "main"
API_VERSION = "2022-11-28"
USER_AGENT = "ProxMenux-app-tracking-catalog/1.0"

# Both the helper cache and common GitHub tags are handled.  The first capture
# group is deliberately the normalized version consumed by lxc_apps.py.
DEFAULT_VERSION_REGEX = (
    r"(?i)(?:v|release[-_/]?)?"
    r"(\d+(?:\.\d+){1,3}(?:[-+._][0-9A-Za-z.-]+)?)"
)
VERSION_FORMATS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'(?i)^v?\d{6,14}$'), r"(?i)v?(\d{6,14})"),
    (
        re.compile(r'(?i)^\d{6,14}-[0-9a-f]{6,40}$'),
        r"(?i)(\d{6,14}(?:-[0-9a-f]{6,40})?)",
    ),
    (re.compile(r'(?i)^r\d{4,}$'), r"(?i)r?(\d{4,})"),
    (
        re.compile(r'(?i)^SQUID_\d+(?:_\d+){1,3}$'),
        r"(?i)(?:SQUID_)?(\d+(?:[._]\d+){1,3})",
    ),
    (
        re.compile(r'(?i)^release\.\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z(?:\.\d+)?$'),
        r"(?i)(?:release\.)?(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z(?:\.\d+)?)",
    ),
]

APP_RE = re.compile(r'^\s*APP=["\']([^"\']+)["\']', re.MULTILINE)
CHECK_RE = re.compile(
    r'\bcheck_for_gh_release\s+["\']([^"\']+)["\']\s+["\']'
    r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)["\']'
)
FETCH_RE = re.compile(
    r'\bfetch_and_deploy_gh_release\s+["\']([^"\']+)["\']\s+["\']'
    r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)["\']'
)
HEADER_GITHUB_RE = re.compile(
    r'Github:\s*https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)',
    re.IGNORECASE,
)
HEADER_SOURCE_RE = re.compile(r'^\s*#\s*Source:\s*(https?://\S+)', re.IGNORECASE | re.MULTILINE)
EXPLICIT_VERSION_FILE_RE = re.compile(
    r'(?:>|tee\s+)(?:["\']?)'
    r'(?:~|\$HOME|\$\{HOME\})/(\.[A-Za-z0-9_.-]+)'
)
DOCKER_IMAGE_RE = re.compile(
    r'(?:docker\s+(?:run|pull)\b[\s\S]{0,800}?)'
    r'((?:ghcr\.io|docker\.io|quay\.io|lscr\.io)/[A-Za-z0-9_./-]+:[A-Za-z0-9_.-]+)',
    re.IGNORECASE,
)
DOCKER_NAME_RE = re.compile(r'\bdocker\s+run\b[\s\S]{0,1200}?--name(?:=|\s+)([A-Za-z0-9_.-]+)', re.IGNORECASE)
EXECSTART_RE = re.compile(r'^\s*ExecStart=(/[A-Za-z0-9_./+@:-]+)', re.MULTILINE)
EXISTENCE_PATH_RE = re.compile(r'\[\[?[^\n]{0,80}?!?\s+-[fx]\s+(/[A-Za-z0-9_./+@:-]+)')
PACKAGE_TOKEN_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.+:@_-]*$')


class CatalogError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.rate_remaining: str | None = None

    def request(self, url: str, *, accept: str = "application/vnd.github+json") -> bytes:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                self.rate_remaining = response.headers.get("X-RateLimit-Remaining")
                return response.read()
        except urllib.error.HTTPError as exc:
            remaining = exc.headers.get("X-RateLimit-Remaining")
            if exc.code == 403 and remaining == "0":
                raise CatalogError(
                    "GitHub API rate limit exhausted. Set GITHUB_TOKEN (or GH_TOKEN) "
                    "and run again."
                ) from exc
            raise CatalogError(f"GitHub API HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"Cannot reach GitHub API: {exc}") from exc

    def json(self, path: str) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        return json.loads(self.request(url).decode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_tar(payload: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            relative = Path(*parts[1:])
            target = (destination / relative).resolve()
            if target != root and root not in target.parents:
                raise CatalogError(f"Unsafe path in GitHub tarball: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise CatalogError(f"Unsupported link/device in GitHub tarball: {member.name}")
            if not (member.isfile() or member.isdir()):
                continue
            member.name = str(relative)
            if member.name != ".":
                # Python 3.9 (the system Python on several macOS releases)
                # predates tarfile's `filter=` argument.  Paths and special
                # members have already been validated above.
                archive.extract(member, destination)


def obtain_snapshot(
    client: GitHubClient,
    repository: str,
    ref: str,
    cache_dir: Path,
) -> tuple[Path, str, str]:
    commit = client.json(f"/repos/{repository}/commits/{ref}")
    commit_sha = str(commit.get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise CatalogError(f"Unexpected commit SHA for {repository}@{ref}")

    snapshot_dir = cache_dir / repository.replace("/", "--") / commit_sha
    marker = snapshot_dir / ".snapshot-complete"
    if marker.exists() and (snapshot_dir / "ct").is_dir():
        return snapshot_dir, commit_sha, marker.read_text(encoding="utf-8").strip()

    payload = client.request(
        f"https://api.github.com/repos/{repository}/tarball/{commit_sha}",
        accept="application/vnd.github+json",
    )
    archive_sha = hashlib.sha256(payload).hexdigest()
    temp_parent = snapshot_dir.parent
    temp_parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{commit_sha}.tmp-", dir=temp_parent))
    try:
        safe_extract_tar(payload, temp_dir)
        (temp_dir / ".snapshot-complete").write_text(archive_sha + "\n", encoding="utf-8")
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        temp_dir.rename(snapshot_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return snapshot_dir, commit_sha, archive_sha


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def cache_key(app: str) -> str:
    # Mirrors tools.func: lower-case then `tr -d ' '`.
    return app.lower().replace(" ", "")


def version_regex_for_tag(tag: str) -> str:
    if not tag or re.search(DEFAULT_VERSION_REGEX, tag):
        return DEFAULT_VERSION_REGEX
    for matcher, pattern in VERSION_FORMATS:
        if matcher.fullmatch(tag):
            return pattern
    return DEFAULT_VERSION_REGEX


def read_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def marker_stores_url(text: str, marker: str) -> bool:
    marker_pattern = re.escape(marker)
    for line in text.splitlines():
        if not re.search(rf'(?:~|\$HOME|\$\{{HOME\}})/{marker_pattern}\b', line):
            continue
        variable = re.search(r'echo\s+["\']?\$\{?([A-Za-z_][A-Za-z0-9_]*)', line)
        if not variable:
            continue
        assignment = re.search(
            rf'^\s*{re.escape(variable.group(1))}=([^\n]*(?:\n(?![A-Za-z_][A-Za-z0-9_]*=)[^\n]*){{0,3}})',
            text,
            re.MULTILINE,
        )
        if assignment and re.search(r"grep\s+-o[^\n]*https?://|DownloadLocation", assignment.group(0), re.IGNORECASE):
            return True
    return False


def unique_pairs(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item[0], item[1].lower())
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def extract_command_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        block = line
        while block.rstrip().endswith("\\") and i + 1 < len(lines):
            block = block.rstrip()[:-1] + " " + lines[i + 1].strip()
            i += 1
        blocks.append(block)
        i += 1
    return blocks


def packages_from_command(text: str, manager: str) -> set[str]:
    packages: set[str] = set()
    command_re = (
        re.compile(r'\b(?:apt|apt-get)\b[^\n]*?\b(?:install|upgrade)\b\s+(.+)$')
        if manager == "dpkg"
        else re.compile(r'\bapk\b[^\n]*?\b(?:add|upgrade)\b\s+(.+)$')
    )
    for block in extract_command_blocks(text):
        match = command_re.search(block)
        if not match:
            continue
        for token in re.split(r"\s+", match.group(1)):
            token = token.strip("'\"")
            if (
                not token
                or token.startswith("-")
                or token.startswith("$")
                or "/" in token
                or "=" in token
                or not PACKAGE_TOKEN_RE.fullmatch(token)
            ):
                continue
            packages.add(token)
    return packages


def checked_packages(text: str, manager: str) -> set[str]:
    patterns = (
        [r'\bdpkg\s+-s\s+([A-Za-z0-9.+:@_-]+)', r'\bdpkg-query\b[^\n]*?\s([A-Za-z0-9.+:@_-]+)\s*(?:[>&]|$)']
        if manager == "dpkg"
        else [r'\bapk\s+info\b[^\n]*?\s([A-Za-z0-9.+:@_-]+)\s*(?:[>&]|$)']
    )
    result: set[str] = set()
    for pattern in patterns:
        result.update(re.findall(pattern, text))
    return result


def load_helper_catalog(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise CatalogError("helpers_cache.json must contain a list")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "lxc":
            continue
        slug = str(item.get("slug") or "")
        if slug and slug not in result:
            result[slug] = item
    return result


@dataclass
class Candidate:
    app: str
    repo: str
    score: int
    reasons: list[str] = field(default_factory=list)
    install_fetch: bool = False
    update_fetch: bool = False


def select_release_candidate(
    slug: str,
    app_name: str,
    launcher: str,
    installer: str,
) -> tuple[Candidate | None, list[dict[str, Any]], str | None]:
    checks = unique_pairs(CHECK_RE.findall(launcher))
    update_fetches = {(a, r.lower()) for a, r in FETCH_RE.findall(launcher)}
    install_fetches = {(a, r.lower()) for a, r in FETCH_RE.findall(installer)}
    candidates: list[Candidate] = []

    for app, repo in checks:
        key = (app, repo.lower())
        score = 0
        identity_score = 0
        reasons: list[str] = []
        n_app, n_slug, n_name = normalize(app), normalize(slug), normalize(app_name)
        n_repo = normalize(repo.split("/", 1)[1])
        if n_app == n_slug:
            score += 100
            identity_score += 100
            reasons.append("check app name matches LXC slug")
        elif n_app and (n_app in n_slug or n_slug in n_app):
            score += 55
            identity_score += 55
            reasons.append("check app name closely matches LXC slug")
        if n_app == n_name:
            score += 45
            identity_score += 45
            reasons.append("check app name matches APP label")
        if n_repo == n_slug or (n_repo and (n_repo in n_slug or n_slug in n_repo)):
            score += 30
            identity_score += 30
            reasons.append("repository name matches LXC slug")
        install_fetch = key in install_fetches
        update_fetch = key in update_fetches
        if install_fetch:
            score += 80
            reasons.append("matching deploy call exists in install script")
        if update_fetch:
            score += 30
            reasons.append("matching deploy call exists in update script")
        if identity_score == 0:
            # Auxiliary components (Ollama inside Open WebUI, web vault
            # assets inside Vaultwarden, etc.) must never become the primary
            # application merely because their deploy helper is present.
            score -= 1000
            reasons.append("does not identify the primary LXC application")
        candidates.append(Candidate(app, repo, score, reasons, install_fetch, update_fetch))

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    audit_candidates = [
        {
            "app": c.app,
            "repo": c.repo,
            "cache_file": f"/root/.{cache_key(c.app)}",
            "score": c.score,
            "install_fetch": c.install_fetch,
            "update_fetch": c.update_fetch,
            "reasons": c.reasons,
        }
        for c in candidates
    ]
    if not candidates:
        return None, audit_candidates, "no literal check_for_gh_release call"
    winner = candidates[0]
    if winner.score < 70:
        return None, audit_candidates, "no release check identifies the primary LXC application"
    if len(candidates) > 1 and winner.score == candidates[1].score:
        return None, audit_candidates, "ambiguous primary GitHub application"
    if not winner.install_fetch:
        return None, audit_candidates, "version cache is not proven to exist immediately after installation"
    return winner, audit_candidates, None


def select_install_only_release(
    slug: str,
    app_name: str,
    installer: str,
    header_repos: list[str],
) -> Candidate | None:
    candidates: list[Candidate] = []
    for app, repo in unique_pairs(FETCH_RE.findall(installer)):
        n_app, n_slug, n_name = normalize(app), normalize(slug), normalize(app_name)
        n_repo = normalize(repo.split("/", 1)[1])
        score = 0
        reasons: list[str] = []
        if n_app == n_slug:
            score += 100
            reasons.append("deploy app matches LXC slug")
        elif n_app and (n_app in n_slug or n_slug in n_app):
            score += 50
            reasons.append("deploy app closely matches LXC slug")
        if n_app == n_name:
            score += 45
            reasons.append("deploy app matches APP label")
        if n_repo == n_slug or (n_repo and (n_repo in n_slug or n_slug in n_repo)):
            score += 30
            reasons.append("repository name matches LXC slug")
        if repo.lower() in {item.lower() for item in header_repos}:
            score += 20
            reasons.append("repository matches script header")
        candidates.append(Candidate(app, repo, score, reasons, install_fetch=True))
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    if not candidates or candidates[0].score < 70:
        return None
    if len(candidates) > 1 and candidates[0].score == candidates[1].score:
        return None
    return candidates[0]


def choose_package(
    slug: str,
    app_name: str,
    launcher: str,
    installer: str,
    manager: str,
) -> tuple[str | None, dict[str, Any]]:
    installed = packages_from_command(installer, manager)
    updated = packages_from_command(launcher, manager)
    checked = checked_packages(launcher, manager)
    raw_proven = installed & (updated | checked)
    # Some official repositories are updated with a plain `apt upgrade` or
    # `apk upgrade`, so the package is not repeated in the update command.
    # Accept only an exact app/slug match in that case; dependencies remain
    # excluded.
    has_generic_upgrade = bool(
        re.search(r'\b(?:apt|apt-get)\b[^\n]*\bupgrade\b', launcher)
        if manager == "dpkg"
        else re.search(r'\bapk\b[^\n]*\bupgrade\b', launcher)
    )
    if has_generic_upgrade:
        expected = {normalize(slug), normalize(app_name)}
        raw_proven.update(package for package in installed if normalize(package) in expected)
    expected = {normalize(slug), normalize(app_name)}

    def is_app_package(package: str) -> bool:
        normalized = normalize(package)
        return any(
            candidate and (
                normalized == candidate
                or normalized in candidate
                or candidate in normalized
            )
            for candidate in expected
        )

    proven = {package for package in raw_proven if is_app_package(package)}
    evidence = {
        "installed_packages": sorted(installed),
        "updated_packages": sorted(updated),
        "checked_packages": sorted(checked),
        "proven_packages": sorted(proven),
        "rejected_unrelated_packages": sorted(raw_proven - proven),
        "generic_upgrade": has_generic_upgrade,
    }
    if not proven:
        return None, evidence

    def score(package: str) -> tuple[int, int, str]:
        n_pkg = normalize(package)
        n_slug = normalize(slug)
        n_name = normalize(app_name)
        value = 0
        if n_pkg == n_slug:
            value += 100
        elif n_pkg in n_slug or n_slug in n_pkg:
            value += 45
        if n_pkg == n_name:
            value += 50
        if package in checked:
            value += 30
        return value, -len(package), package

    ranked = sorted(proven, key=score, reverse=True)
    if len(ranked) > 1 and score(ranked[0])[:2] == score(ranked[1])[:2]:
        return None, evidence
    return ranked[0], evidence


def repo_from_helper(item: dict[str, Any]) -> str:
    repo = str(item.get("github_repo") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return repo
    raw = str(item.get("github") or "").strip()
    match = re.search(r'(?:github\.com/)?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', raw)
    return match.group(1) if match else ""


def build_catalog(
    source: Path,
    helpers: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog: dict[str, Any] = {}
    v2_apps: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    launchers = sorted((source / "ct").glob("*.sh"))
    tools_func = source / "misc" / "tools.func"
    tools_text = read_text(tools_func)
    shared_helper_verified = bool(
        re.search(r'local version_file="\$HOME/\.\$\{app_lc\}"', tools_text)
        and re.search(r'echo "\$version" >"\$version_file"', tools_text)
        and re.search(r'local current_file="\$HOME/\.\$\{app_lc\}"', tools_text)
    )
    if not shared_helper_verified:
        raise CatalogError("Could not verify the shared GitHub release cache contract in misc/tools.func")

    for launcher_path in launchers:
        slug = launcher_path.stem
        launcher = read_text(launcher_path)
        installer_path = source / "install" / f"{slug}-install.sh"
        installer = read_text(installer_path)
        app_match = APP_RE.search(launcher)
        app_name = app_match.group(1) if app_match else slug
        helper_item = helpers.get(slug, {})
        helper_repo = repo_from_helper(helper_item)
        helper_version = str(helper_item.get("github_version") or "").strip()
        version_regex = version_regex_for_tag(helper_version)
        header_repos = HEADER_GITHUB_RE.findall(launcher + "\n" + installer)
        official_sources = sorted(set(HEADER_SOURCE_RE.findall(launcher + "\n" + installer)))
        docker_images = sorted(set(DOCKER_IMAGE_RE.findall(installer)))
        docker_names = sorted(set(DOCKER_NAME_RE.findall(installer)))
        launcher_version_files = set(EXPLICIT_VERSION_FILE_RE.findall(launcher))
        installer_version_files = set(EXPLICIT_VERSION_FILE_RE.findall(installer))
        explicit_files = sorted(launcher_version_files | installer_version_files)
        relevant_markers = sorted(
            marker
            for marker in launcher_version_files & installer_version_files
            if normalize(marker.lstrip(".")) in {normalize(slug), normalize(app_name)}
            and not marker_stores_url(launcher, marker)
            and not marker_stores_url(installer, marker)
        )

        package_evidence: dict[str, Any] = {}
        package_detectors: list[dict[str, Any]] = []
        for manager in ("dpkg", "apk"):
            package, evidence = choose_package(slug, app_name, launcher, installer, manager)
            package_evidence[manager] = evidence
            if package and helper_repo:
                upstream_verified = bool(
                    helper_version and re.search(version_regex, helper_version)
                )
                package_detectors.append(
                    {
                        "installed_via": manager,
                        "package": package,
                        "repo": helper_repo,
                        "github_source": "releases",
                        "tag_regex": version_regex,
                        "install_scope": ["community-script", "manual-if-same-package"],
                        "verification": (
                            "verified-static"
                            if upstream_verified
                            else "candidate-needs-upstream-verification"
                        ),
                        "evidence": {
                            "install": f"install/{installer_path.name}: package installation",
                            "update": f"ct/{launcher_path.name}: package check or named upgrade",
                        },
                    }
                )

        binary_paths = sorted(set(EXECSTART_RE.findall(installer)) & set(EXISTENCE_PATH_RE.findall(launcher)))
        binary_detectors = [
            {
                "installed_via": "binary",
                "binary_path": path,
                "binary_args": ["--version"],
                "repo": helper_repo or None,
                "github_source": "releases",
                "tag_regex": version_regex,
                "install_scope": ["community-script", "manual-if-same-path"],
                "verification": "candidate-needs-version-probe",
                "evidence": {
                    "install": f"install/{installer_path.name}: systemd ExecStart",
                    "update": f"ct/{launcher_path.name}: installation existence check",
                },
            }
            for path in binary_paths
        ]

        docker_detectors: list[dict[str, Any]] = []
        if docker_names or docker_images:
            # Keep all discovered data when a script has multiple containers;
            # pairing by shell position is intentionally left to an override.
            docker_detectors.append(
                {
                    "installed_via": "docker",
                    "container_names": docker_names,
                    "images": docker_images,
                    "version_sources": [
                        {"type": "oci_label", "name": "org.opencontainers.image.version"},
                        {"type": "image_ref_tag"},
                    ],
                    "repo": helper_repo or None,
                    "github_source": "releases",
                    "tag_regex": version_regex,
                    "install_scope": ["community-script", "manual-docker"],
                    "verification": "requires-detector-change",
                    "evidence": {"install": f"install/{installer_path.name}: docker run/pull"},
                }
            )

        record: dict[str, Any] = {
            "slug": slug,
            "name": app_name,
            "launcher": f"ct/{launcher_path.name}",
            "installer": f"install/{installer_path.name}" if installer_path.is_file() else None,
            "status": "excluded",
            "method": None,
            "reason": None,
            "helper_repo": helper_repo or None,
            "helper_upstream_version": helper_version or None,
            "header_repositories": header_repos,
            "official_sources": official_sources,
            "docker_images": docker_images,
            "docker_names": docker_names,
            "explicit_version_files": [f"/root/{item}" for item in explicit_files],
        }

        release, release_candidates, release_error = select_release_candidate(
            slug, app_name, launcher, installer
        )
        install_only_release = select_install_only_release(
            slug, app_name, installer, header_repos
        ) if release is None else None
        record["release_candidates"] = release_candidates
        v2_detectors: list[dict[str, Any]] = []
        if release is not None:
            hint = {
                "installed_via": "file",
                "file_path": f"/root/.{cache_key(release.app)}",
                "file_regex": DEFAULT_VERSION_REGEX,
                "repo": release.repo,
                "github_source": "releases",
                "tag_regex": version_regex,
            }
            hint["file_regex"] = version_regex
            catalog[slug] = hint
            v2_detectors.append(
                {
                    **hint,
                    "install_scope": ["community-script"],
                    "verification": "verified-static",
                    "evidence": {
                        "install": f"install/{installer_path.name}: matching deploy helper",
                        "update": f"ct/{launcher_path.name}: matching release check",
                        "contract": "misc/tools.func: shared version-cache contract",
                    },
                }
            )
            v2_detectors.extend(package_detectors)
            v2_detectors.extend(binary_detectors)
            v2_detectors.extend(docker_detectors)
            record.update(
                {
                    "status": "verified",
                    "method": "file",
                    "reason": "install deploy and update check share the same helper cache",
                    "selected": hint,
                    "evidence": {
                        "install": f"install/{installer_path.name}: fetch_and_deploy_gh_release({release.app}, {release.repo})",
                        "update": f"ct/{launcher_path.name}: check_for_gh_release({release.app}, {release.repo})",
                        "contract": "misc/tools.func writes and reads /root/.<normalized-app>",
                    },
                }
            )
            records.append(record)
            v2_apps[slug] = {
                "name": app_name,
                "repo": release.repo,
                "official_sources": official_sources,
                "detectors": v2_detectors,
            }
            continue

        if len(relevant_markers) == 1 and helper_repo and helper_version:
            marker = relevant_markers[0]
            hint = {
                "installed_via": "file",
                "file_path": f"/root/{marker}",
                "file_regex": version_regex,
                "repo": helper_repo,
                "github_source": "releases",
                "tag_regex": version_regex,
            }
            catalog[slug] = hint
            v2_detectors.append(
                {
                    **hint,
                    "install_scope": ["community-script"],
                    "verification": "verified-static",
                    "evidence": {
                        "install": f"install/{installer_path.name}: writes {hint['file_path']}",
                        "update": f"ct/{launcher_path.name}: writes {hint['file_path']}",
                    },
                }
            )
            v2_detectors.extend(package_detectors)
            v2_detectors.extend(binary_detectors)
            v2_detectors.extend(docker_detectors)
            record.update(
                {
                    "status": "verified",
                    "method": "file",
                    "reason": "install and update scripts write the same app-specific version marker",
                    "selected": hint,
                    "evidence": v2_detectors[0]["evidence"],
                }
            )
            records.append(record)
            v2_apps[slug] = {
                "name": app_name,
                "repo": helper_repo,
                "official_sources": official_sources,
                "detectors": v2_detectors,
            }
            continue

        if install_only_release is not None:
            v2_detectors.append(
                {
                    "installed_via": "file",
                    "file_path": f"/root/.{cache_key(install_only_release.app)}",
                    "file_regex": version_regex,
                    "repo": install_only_release.repo,
                    "github_source": "releases",
                    "tag_regex": version_regex,
                    "install_scope": ["community-script"],
                    "verification": "candidate-install-cache-may-stale",
                    "evidence": {
                        "install": f"install/{installer_path.name}: deploy helper writes the version cache",
                        "limitation": "no matching update check proves that later updates refresh this cache",
                    },
                }
            )

        package_selected = False
        for detector in package_detectors:
            manager = detector["installed_via"]
            if not package_selected and detector["verification"] == "verified-static":
                hint = {key: value for key, value in detector.items() if key in {
                    "installed_via", "package", "repo", "github_source", "tag_regex"
                }}
                catalog[slug] = hint
                record.update(
                    {
                        "status": "verified",
                        "method": manager,
                        "reason": "package is present in both install and update/check paths",
                        "selected": hint,
                        "evidence": package_evidence[manager],
                    }
                )
                package_selected = True
        record["package_evidence"] = package_evidence
        if package_selected:
            v2_detectors.extend(package_detectors)
            v2_detectors.extend(binary_detectors)
            v2_detectors.extend(docker_detectors)
            records.append(record)
            v2_apps[slug] = {
                "name": app_name,
                "repo": helper_repo or None,
                "official_sources": official_sources,
                "detectors": v2_detectors,
            }
            continue

        if docker_images or re.search(r'\bsetup_docker\b|\bdocker\s+(?:run|compose|pull)\b', installer):
            record["reason"] = "Docker installation requires detector support not present in lxc_apps.py"
            record["required_detector"] = "docker"
        elif release_error:
            record["reason"] = release_error
        elif not installer_path.is_file():
            record["reason"] = "no matching install script"
        elif helper_repo and any(
            item["proven_packages"] for item in package_evidence.values()
        ):
            record["reason"] = "package detector needs upstream repository/release verification"
        elif not helper_repo:
            record["reason"] = "no verified upstream GitHub repository for package tracking"
        else:
            record["reason"] = "no supported detection method could be proven from both scripts"
        records.append(record)
        v2_detectors.extend(package_detectors)
        v2_detectors.extend(binary_detectors)
        v2_detectors.extend(docker_detectors)
        v2_apps[slug] = {
            "name": app_name,
            "repo": helper_repo or (header_repos[0] if header_repos else None),
            "official_sources": official_sources,
            "detectors": v2_detectors,
        }

    status_counts: dict[str, int] = {}
    method_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    tag_validation = {"matched": 0, "missing": 0, "mismatched": []}
    for record in records:
        status_counts[record["status"]] = status_counts.get(record["status"], 0) + 1
        method = record.get("method") or "none"
        method_counts[method] = method_counts.get(method, 0) + 1
        reason = record.get("reason") or "none"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if record.get("status") == "verified":
            upstream = record.get("helper_upstream_version")
            pattern = (record.get("selected") or {}).get("tag_regex")
            if not upstream:
                tag_validation["missing"] += 1
            elif pattern and re.search(pattern, upstream):
                tag_validation["matched"] += 1
            else:
                tag_validation["mismatched"].append(
                    {"slug": record["slug"], "version": upstream, "tag_regex": pattern}
                )

    audit = {
        "summary": {
            "lxc_launchers": len(launchers),
            "operational_hints": len(catalog),
            "coverage_percent": round((len(catalog) / len(launchers) * 100), 2) if launchers else 0,
            "status_counts": status_counts,
            "method_counts": method_counts,
            "reason_counts": reason_counts,
            "shared_release_cache_contract_verified": shared_helper_verified,
            "helper_upstream_tag_validation": tag_validation,
        },
        "records": records,
    }
    v2 = {
        "schema_version": 2,
        "detector_policy": {
            "strategy": "try detectors in order and retain the first successful detector",
            "operational_verification": ["verified-static", "verified-runtime"],
            "non_operational_verification": [
                "candidate-needs-version-probe",
                "requires-detector-change",
                "candidate-needs-runtime-validation",
                "candidate-install-cache-may-stale",
                "candidate-needs-upstream-verification",
                "candidate-helper-marker",
            ],
        },
        "apps": dict(sorted(v2_apps.items())),
    }
    return dict(sorted(catalog.items())), audit, v2


def compare_existing(generated: dict[str, Any], existing_path: Path | None) -> dict[str, Any]:
    if existing_path is None or not existing_path.is_file():
        return {"existing_file": None, "added": sorted(generated), "removed": [], "changed": []}
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    if not isinstance(existing, dict):
        raise CatalogError("Existing catalog must be a JSON object")
    return {
        "existing_file": str(existing_path),
        "added": sorted(set(generated) - set(existing)),
        "removed": sorted(set(existing) - set(generated)),
        "changed": sorted(
            slug for slug in set(existing) & set(generated) if existing[slug] != generated[slug]
        ),
        "unchanged": sorted(
            slug for slug in set(existing) & set(generated) if existing[slug] == generated[slug]
        ),
    }


def demote_generic_helper_markers(
    catalog: dict[str, Any],
    v2: dict[str, Any],
    audit: dict[str, Any],
) -> list[str]:
    """Remove generic /root/.app caches from the operational catalog.

    Even when install and update scripts both write the marker, it records
    helper/update state rather than interrogating the installed application.
    Runtime checks also found these files absent on legacy and manually
    updated LXC. They remain useful candidates/fallbacks in v2, not verified
    primary detectors.
    """
    demoted: list[str] = []
    apps = v2.get("apps", {})
    for record in audit.get("records", []):
        slug = record.get("slug")
        hint = catalog.get(slug)
        if not isinstance(hint, dict):
            continue
        path = hint.get("file_path")
        if hint.get("installed_via") != "file" or not isinstance(path, str):
            continue
        if not re.fullmatch(r"/root/\.[A-Za-z0-9_.-]+", path):
            continue
        catalog.pop(slug, None)
        record["status"] = "candidate"
        record["reason"] = "generic helper marker is not guaranteed on legacy/manual installations"
        for detector in (apps.get(slug) or {}).get("detectors", []):
            if detector.get("installed_via") == "file" and detector.get("file_path") == path:
                detector["verification"] = "candidate-helper-marker"
                detector["limitation"] = (
                    "Observed absent on legacy/manual LXC; use only as fallback or after runtime probe"
                )
        demoted.append(slug)
    return sorted(demoted)


def verify_upstream_releases(
    client: GitHubClient,
    catalog: dict[str, Any],
    cache_dir: Path,
) -> dict[str, Any]:
    """Verify repositories and current tags directly with the GitHub API."""
    repos = sorted({hint["repo"] for hint in catalog.values() if hint.get("repo")})
    if len(repos) > 40 and not client.token:
        raise CatalogError(
            f"--verify-upstream needs GITHUB_TOKEN or GH_TOKEN for {len(repos)} repositories "
            "(the anonymous GitHub API limit is only 60 requests/hour)."
        )
    cache_file = cache_dir / "upstream-releases.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, json.JSONDecodeError):
        cache = {}

    now = int(time.time())
    results: dict[str, Any] = {}
    for index, repo in enumerate(repos, start=1):
        cached = cache.get(repo, {})
        if isinstance(cached, dict) and now - int(cached.get("fetched_at", 0)) < 24 * 3600:
            results[repo] = cached
            continue
        tag = ""
        source = "releases"
        error = ""
        try:
            payload = client.json(f"/repos/{repo}/releases/latest")
            if isinstance(payload, dict):
                tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
        except CatalogError as exc:
            error = str(exc)
            try:
                tags = client.json(f"/repos/{repo}/tags?per_page=30")
                if isinstance(tags, list) and tags and isinstance(tags[0], dict):
                    tag = str(tags[0].get("name") or "").strip()
                    source = "tags"
                    error = ""
            except CatalogError as tag_exc:
                error = f"release: {exc}; tags: {tag_exc}"
        results[repo] = {
            "tag": tag or None,
            "source": source,
            "error": error or None,
            "fetched_at": now,
        }
        if index % 25 == 0:
            print(f"Verified upstream repositories: {index}/{len(repos)}", file=sys.stderr)
    cache_file.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    matched: list[dict[str, str]] = []
    mismatched: list[dict[str, str]] = []
    unavailable: list[dict[str, str]] = []
    for slug, hint in catalog.items():
        result = results.get(hint.get("repo"), {})
        tag = result.get("tag")
        if not tag:
            unavailable.append({"slug": slug, "repo": hint.get("repo", ""), "error": result.get("error") or "no tag"})
        elif re.search(hint["tag_regex"], tag):
            matched.append({"slug": slug, "repo": hint["repo"], "tag": tag})
        else:
            mismatched.append(
                {"slug": slug, "repo": hint["repo"], "tag": tag, "tag_regex": hint["tag_regex"]}
            )
    return {
        "repositories_queried": len(repos),
        "matched": len(matched),
        "mismatched": mismatched,
        "unavailable": unavailable,
        "results": results,
    }


def merge_existing_as_runtime_candidates(v2: dict[str, Any], existing_path: Path | None) -> dict[str, Any]:
    """Retain hand-curated/manual-install hints without declaring them proven.

    Existing entries are valuable for official/manual layouts, but static
    analysis found that several no longer match current Community Scripts.
    They therefore enter v2 as runtime-validation candidates and never enter
    the compatible v1 output automatically.
    """
    result = {"merged": [], "unmatched": [], "skipped_duplicates": []}
    if existing_path is None or not existing_path.is_file():
        return result
    raw = json.loads(existing_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return result
    apps = v2.get("apps", {})
    allowed = {
        "installed_via", "package", "file_path", "file_regex", "binary_path",
        "repo", "github_source", "tag_regex",
    }
    for slug, hint in raw.items():
        if slug not in apps or not isinstance(hint, dict):
            result["unmatched"].append(slug)
            continue
        detector = {key: value for key, value in hint.items() if key in allowed}
        if not detector.get("installed_via"):
            continue
        signature = json.dumps(detector, sort_keys=True)
        existing_signatures = {
            json.dumps({key: value for key, value in item.items() if key in allowed}, sort_keys=True)
            for item in apps[slug]["detectors"]
        }
        if signature in existing_signatures:
            result["skipped_duplicates"].append(slug)
            continue
        detector.update(
            {
                "install_scope": ["manual", "legacy-catalog"],
                "verification": "candidate-needs-runtime-validation",
                "evidence": {"catalog": str(existing_path)},
            }
        )
        apps[slug]["detectors"].append(detector)
        result["merged"].append(slug)
    for key in result:
        result[key].sort()
    return result


def enrich_catalog_metadata(
    catalog: dict[str, Any],
    v2: dict[str, Any],
    helpers: dict[str, dict[str, Any]],
    existing_path: Path | None,
) -> dict[str, int]:
    """Add presentation metadata without weakening detector verification.

    Community Scripts provides one primary port and a curated logo. Existing
    manual `default_ports` take precedence because they may describe multi-port
    applications. Detector fields and their evidence remain untouched.
    """
    existing: dict[str, Any] = {}
    if existing_path and existing_path.is_file():
        try:
            payload = json.loads(existing_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except (OSError, json.JSONDecodeError):
            pass

    counts = {"apps_with_ports": 0, "apps_with_logos": 0, "selfhst_logos": 0}
    apps = v2.get("apps", {})
    for slug, app in apps.items():
        helper = helpers.get(slug, {})
        prior = existing.get(slug, {}) if isinstance(existing.get(slug), dict) else {}

        ports: list[int] = []
        prior_ports = prior.get("default_ports")
        if isinstance(prior_ports, list):
            for value in prior_ports:
                try:
                    port = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= port <= 65535 and port not in ports:
                    ports.append(port)
        if not ports:
            raw_port = helper.get("port")
            if isinstance(raw_port, int) and 1 <= raw_port <= 65535:
                ports.append(raw_port)

        logo = str(prior.get("logo") or helper.get("logo") or "").strip()
        if logo and not re.match(r"^https://[A-Za-z0-9.-]+/", logo):
            logo = ""
        website = str(helper.get("website") or "").strip()

        if ports:
            app["default_ports"] = ports
            counts["apps_with_ports"] += 1
        if logo:
            app["logo"] = logo
            app["logo_source"] = (
                "selfh.st/icons via jsDelivr"
                if "cdn.jsdelivr.net/gh/selfhst/icons@" in logo
                else "community-scripts catalog"
            )
            counts["apps_with_logos"] += 1
            if app["logo_source"].startswith("selfh.st"):
                counts["selfhst_logos"] += 1
        if website.startswith("https://"):
            app["website"] = website

        # v1 only contains operationally verified apps. Extra metadata is
        # ignored safely by validate_config but is available to suggestions/UI.
        if slug in catalog:
            if ports:
                catalog[slug]["default_ports"] = ports
            if logo:
                catalog[slug]["logo"] = logo
            if website.startswith("https://"):
                catalog[slug]["website"] = website
    return counts


def apply_runtime_overrides(
    catalog: dict[str, Any],
    v2: dict[str, Any],
    overrides_path: Path | None,
) -> dict[str, Any]:
    """Apply detectors proven against real containers.

    The generated/static catalog is intentionally conservative. This optional
    overlay promotes only detectors carrying runtime evidence. Unsupported
    future methods (for example ``python_dist`` or ``docker_label``) are kept
    in v2 but are not written to the current-compatible v1 catalog.
    """
    result: dict[str, Any] = {
        "file": str(overrides_path) if overrides_path else None,
        "promoted_to_v1": [],
        "v2_only": [],
        "invalid": [],
    }
    if overrides_path is None or not overrides_path.is_file():
        return result
    raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    apps_raw = raw.get("apps") if isinstance(raw, dict) else None
    if not isinstance(apps_raw, dict):
        raise CatalogError("runtime overrides must contain an 'apps' object")

    supported_v1 = {"dpkg", "apk", "file", "binary"}
    v2_apps = v2.get("apps", {})
    detector_keys = {
        "installed_via", "package", "file_path", "file_regex",
        "binary_path", "binary_args", "python_path", "distribution",
        "container_name", "label", "repo", "github_source", "tag_regex",
        "installed_regex",
    }
    passthrough_keys = {
        "file_fallbacks", "alt_detectors", "default_ports", "logo", "website",
    }
    for slug, spec in apps_raw.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("detector"), dict):
            result["invalid"].append(slug)
            continue
        detector = {k: v for k, v in spec["detector"].items() if k in detector_keys}
        method = detector.get("installed_via")
        if not isinstance(method, str) or not method:
            result["invalid"].append(slug)
            continue
        evidence = spec.get("evidence") if isinstance(spec.get("evidence"), list) else []
        v2_detector = {
            **detector,
            "install_scope": spec.get("install_scope") or ["runtime-observed"],
            "verification": "verified-runtime",
            "evidence": evidence,
        }
        app = v2_apps.get(slug)
        if not isinstance(app, dict):
            result["invalid"].append(slug)
            continue
        app.setdefault("detectors", []).insert(0, v2_detector)
        app["runtime_evidence"] = evidence

        if bool(spec.get("remove_from_v1")):
            catalog.pop(slug, None)

        operational = bool(spec.get("operational", True))
        if operational and method in supported_v1:
            # Preserve presentation metadata already enriched from helpers.
            presentation_source = dict(app)
            presentation_source.update(catalog.get(slug, {}))
            presentation = {
                key: value
                for key, value in presentation_source.items()
                if key in {"default_ports", "logo", "website"}
            }
            hint = {k: v for k, v in detector.items() if k not in {
                "binary_args", "python_path", "distribution", "container_name",
                "label", "installed_regex",
            }}
            for key in passthrough_keys:
                if key in spec:
                    hint[key] = spec[key]
            hint.update(presentation)
            catalog[slug] = hint
            result["promoted_to_v1"].append(slug)
        else:
            result["v2_only"].append(slug)

    for key in ("promoted_to_v1", "v2_only", "invalid"):
        result[key].sort()
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Analyze an existing checkout/snapshot instead of downloading through GitHub API",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "proxmenux-app-tracking",
    )
    parser.add_argument("--helpers-cache", type=Path)
    parser.add_argument("--existing", type=Path)
    parser.add_argument(
        "--runtime-overrides",
        type=Path,
        help="JSON overlay with detectors verified against real LXC installations",
    )
    parser.add_argument(
        "--include-helper-markers",
        action="store_true",
        help="Keep generic /root/.app helper caches in v1 (not recommended for legacy/manual LXC)",
    )
    parser.add_argument("--output", type=Path, default=Path("app_tracking_hints.generated.json"))
    parser.add_argument("--audit-output", type=Path, default=Path("app_tracking_hints.audit.json"))
    parser.add_argument("--v2-output", type=Path, default=Path("app_tracking_catalog.v2.json"))
    parser.add_argument(
        "--verify-upstream",
        action="store_true",
        help="Verify every repository's current release/tag directly through GitHub API (token recommended)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    started = time.time()
    client = GitHubClient()
    commit_sha = "local-source"
    archive_sha = "not-applicable"
    try:
        if args.source_dir:
            source = args.source_dir.resolve()
            if re.fullmatch(r"[0-9a-fA-F]{40}", source.name):
                commit_sha = source.name.lower()
        else:
            source, commit_sha, archive_sha = obtain_snapshot(
                client, args.repository, args.ref, args.cache_dir.expanduser().resolve()
            )
        if not (source / "ct").is_dir() or not (source / "misc" / "tools.func").is_file():
            raise CatalogError(f"Not a valid ProxmoxVE source tree: {source}")
        helpers = load_helper_catalog(args.helpers_cache)
        catalog, audit, v2 = build_catalog(source, helpers)
        audit["demoted_helper_markers"] = (
            [] if args.include_helper_markers else demote_generic_helper_markers(catalog, v2, audit)
        )
        audit["metadata"] = enrich_catalog_metadata(catalog, v2, helpers, args.existing)
        audit["v2_existing_candidates"] = merge_existing_as_runtime_candidates(v2, args.existing)
        audit["runtime_overrides"] = apply_runtime_overrides(
            catalog, v2, args.runtime_overrides
        )
        if args.verify_upstream:
            audit["github_upstream_verification"] = verify_upstream_releases(
                client, catalog, args.cache_dir.expanduser().resolve()
            )
        audit["provenance"] = {
            "repository": args.repository,
            "ref": args.ref,
            "commit_sha": commit_sha,
            "archive_sha256": archive_sha,
            "source_dir": str(source),
            "generated_at_unix": int(time.time()),
            "generator_sha256": sha256_file(Path(__file__).resolve()),
            "github_api_rate_remaining": client.rate_remaining,
            "helpers_cache": str(args.helpers_cache) if args.helpers_cache else None,
        }
        audit["existing_comparison"] = compare_existing(catalog, args.existing)
        audit["summary"]["operational_hints"] = len(catalog)
        audit["summary"]["coverage_percent"] = round(
            len(catalog) / max(1, audit["summary"]["lxc_launchers"]) * 100, 2
        )
        method_counts: dict[str, int] = {}
        for hint in catalog.values():
            method = str(hint.get("installed_via") or "none")
            method_counts[method] = method_counts.get(method, 0) + 1
        method_counts["none"] = max(
            0, audit["summary"]["lxc_launchers"] - len(catalog)
        )
        audit["summary"]["method_counts"] = method_counts
        audit["summary"]["elapsed_seconds"] = round(time.time() - started, 3)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.v2_output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        v2["provenance"] = audit["provenance"]
        args.v2_output.write_text(json.dumps(v2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (CatalogError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = audit["summary"]
    print(f"Pinned source: {args.repository}@{commit_sha}")
    print(f"LXC launchers analyzed: {summary['lxc_launchers']}")
    print(f"Verified operational hints: {summary['operational_hints']} ({summary['coverage_percent']}%)")
    print(f"Methods: {summary['method_counts']}")
    print(f"Catalog: {args.output.resolve()}")
    print(f"Audit: {args.audit_output.resolve()}")
    print(f"Multi-detector catalog v2: {args.v2_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
