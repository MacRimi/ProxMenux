from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
PROXMENUX_HELPERS_URL = (
    "https://raw.githubusercontent.com/MacRimi/ProxMenux/develop/json/helpers_cache.json"
)
CASAOS_REPOSITORY = "IceWhaleTech/CasaOS-AppStore"
CASAOS_REPOSITORY_URL = f"https://github.com/{CASAOS_REPOSITORY}"

CATEGORY_TAGS = {
    "*Arr Suite": "arr",
    "AI / Coding & Dev-Tools": "ai",
    "Adblock & DNS": "adblock",
    "Authentication & Security": "security",
    "Automation & Scheduling": "automation",
    "Backup & Recovery": "backup",
    "Business & ERP": "business",
    "Communication & Community": "communication",
    "Containers & Docker": "containers",
    "Dashboards & Frontends": "dashboards",
    "Databases": "databases",
    "Documents & Notes": "documents",
    "Files & Downloads": "downloads",
    "Finance & Budgeting": "finance",
    "Gaming & Leisure": "gaming",
    "Host Management": "management",
    "IoT & Smart Home": "smarthome",
    "Media & Streaming": "media",
    "Messaging & Queues": "messaging",
    "Miscellaneous": "misc",
    "Monitoring & Analytics": "monitoring",
    "NVR & Cameras": "nvr",
    "Network & Firewall": "network",
    "Operating Systems & Appliances": "systems",
    "Productivity & Workflows": "productivity",
    "Remote Access & VPN": "remote",
    "Webservers & Proxies": "web",
    "ZigBee, Z-Wave & Matter": "zigbee",
}


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Repository:
    name: str
    description: str
    default_branch: str
    html_url: str
    pushed_at: str
    category: str = "misc"
    category_label: str = "Miscellaneous"

    @property
    def app_id(self) -> str:
        return self.name.removeprefix("docker-")


class GitHubSource:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _request(self, url: str, accept: str = "application/vnd.github+json") -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "ProxMenux-OCI-Lab/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        last_error: Exception | None = None
        for attempt in range(3):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last_error = exc
                remaining = exc.headers.get("X-RateLimit-Remaining")
                if exc.code == 403 and remaining == "0":
                    raise SourceError(
                        f"GitHub returned HTTP 403 for {url}. "
                        "Set GITHUB_TOKEN to raise the API rate limit."
                    ) from exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise SourceError(f"GitHub returned HTTP {exc.code} para {url}.") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        reason = getattr(last_error, "reason", last_error)
        raise SourceError(f"No se pudo acceder a {url} despues de 3 intentos: {reason}") from last_error

    def get_json(self, path_or_url: str) -> Any:
        url = path_or_url if path_or_url.startswith("https://") else f"{API_ROOT}{path_or_url}"
        return json.loads(self._request(url).decode("utf-8"))

    def get_text(self, url: str) -> str:
        return self._request(url, accept="text/plain").decode("utf-8")

    def list_linuxserver_repositories(self) -> list[Repository]:
        repos: list[Repository] = []
        page = 1
        while True:
            payload = self.get_json(
                f"/orgs/linuxserver/repos?type=public&sort=full_name&per_page=100&page={page}"
            )
            if not payload:
                break
            for item in payload:
                name = item.get("name", "")
                if not self._is_application_repository(item, name):
                    continue
                repos.append(
                    Repository(
                        name=name,
                        description=item.get("description") or "",
                        default_branch=item.get("default_branch") or "master",
                        html_url=item.get("html_url") or f"https://github.com/linuxserver/{name}",
                        pushed_at=item.get("pushed_at") or "",
                    )
                )
            if len(payload) < 100:
                break
            page += 1
        return sorted(repos, key=lambda repo: repo.app_id.casefold())

    def proxmenux_app_metadata(self) -> dict[str, dict[str, Any]]:
        payload = self.get_json(PROXMENUX_HELPERS_URL)
        if not isinstance(payload, list):
            raise SourceError("The ProxMenux application catalogue is not a list")
        result: dict[str, dict[str, Any]] = {}
        for item in payload:
            if not isinstance(item, dict) or not item.get("slug"):
                continue
            category_names = item.get("category_names") or []
            category_label = category_names[0] if category_names else "Miscellaneous"
            result[str(item["slug"]).casefold()] = {
                "category": CATEGORY_TAGS.get(category_label, "misc"),
                "category_label": category_label,
            }
        return result

    def casaos_state(self) -> dict[str, Any]:
        commit = self.get_json(f"/repos/{CASAOS_REPOSITORY}/commits/main")
        revision = str(commit["sha"])
        tree = self.get_json(f"/repos/{CASAOS_REPOSITORY}/git/trees/{revision}?recursive=1")
        if tree.get("truncated"):
            raise SourceError("GitHub returned a truncated tree for the CasaOS catalogue")
        paths = sorted(
            str(item["path"])
            for item in tree.get("tree", [])
            if item.get("type") == "blob"
            and re.fullmatch(r"Apps/[^/]+/docker-compose\.yml", str(item.get("path", "")))
        )
        if not paths:
            raise SourceError("No Compose files were found in the CasaOS catalogue")
        return {
            "repository": CASAOS_REPOSITORY_URL,
            "revision": revision,
            "pushed_at": str(commit.get("commit", {}).get("committer", {}).get("date") or ""),
            "paths": paths,
        }

    def casaos_compose(self, path: str, revision: str) -> tuple[str, str]:
        encoded_path = urllib.parse.quote(path, safe="/")
        raw_url = f"{RAW_ROOT}/{CASAOS_REPOSITORY}/{revision}/{encoded_path}"
        return self.get_text(raw_url), raw_url

    @staticmethod
    def _is_application_repository(item: dict[str, Any], name: str) -> bool:
        if item.get("archived") or item.get("fork") or not name.startswith("docker-"):
            return False
        infrastructure_prefixes = (
            "docker-baseimage-",
            "docker-ci",
            "docker-jenkins",
            "docker-mod",
            "docker-qemu",
        )
        return not name.startswith(infrastructure_prefixes)

    def readme(self, repo: Repository) -> tuple[str, str, str]:
        commit = self.get_json(f"/repos/linuxserver/{repo.name}/commits/{repo.default_branch}")
        revision = commit["sha"]
        raw_url = f"{RAW_ROOT}/linuxserver/{repo.name}/{revision}/README.md"
        return self.get_text(raw_url), revision, raw_url

    def readme_at_branch(self, repo: Repository) -> str:
        raw_url = f"{RAW_ROOT}/linuxserver/{repo.name}/{repo.default_branch}/README.md"
        return self.get_text(raw_url)
