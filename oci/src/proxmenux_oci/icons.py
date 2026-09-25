"""Application icons for the catalog, resolved against the jsdelivr icon sets.

The icon a catalog entry carries used to be a URL built from the application
id, which nobody ever requested: seven out of ten answered 404, so the panel
drew a broken image instead of a plain placeholder. These two sets publish an
index, so an entry only keeps an icon that is known to exist, and every icon
comes from the same CDN as the rest of the interface.
"""
from __future__ import annotations

import json
import re
import urllib.request

SELFHST_INDEX = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/index.json"
SELFHST_ICON = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/{name}.webp"
HOMARR_INDEX = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons@main/tree.json"
HOMARR_ICON = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons@main/webp/{name}.webp"
# The two sources the catalog itself is built from publish their icons beside
# the application, and both are served by the same CDN. Their file names are
# read from the repository tree rather than derived: linuxserver names them
# `<id>-logo.png`, and the `-icon.png` this catalog used to build answered 404
# for seven entries out of ten.
PUBLISHER_TREES = (
    ("https://api.github.com/repos/IceWhaleTech/CasaOS-AppStore/git/trees/main?recursive=1",
     r"Apps/(?P<name>[^/]+)/icon\.(?:svg|png|webp)",
     "https://cdn.jsdelivr.net/gh/IceWhaleTech/CasaOS-AppStore@main/{path}"),
    ("https://api.github.com/repos/linuxserver/docker-templates/git/trees/master?recursive=1",
     r"linuxserver\.io/img/(?P<name>.+?)-(?:logo|icon)\.(?:png|svg|jpg|webp)",
     "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/{path}"),
)
TIMEOUT = 30
VARIANT_SUFFIX_RE = re.compile(r"-(?:dark|light)$")
# Catalog ids carry the publisher or the accelerator when the same application
# ships under several images: emby-official, open-webui-cuda, kavita-jvmilazz0.
# They are the same application and they wear the same icon.
QUALIFIER_RE = re.compile(
    r"[-_](?:official|stack|nvidia|cuda|rocm|gpu|ollama|jlesage|jvmilazz0)$")


# Applications neither icon set names, resolved by hand and verified. A few are
# only ProxMenux compositions, so they borrow the icon of what they assemble:
# HAOS One wears Home Assistant's, and the Arr suite wears Servarr's.
CURATED = {
    "blade-of-agony": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/boa-logo.png",
    "budge": "https://cdn.jsdelivr.net/gh/linuxserver/budge@master/frontend/public/logo512.png",
    "changedetection.io": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/changedetection-icon.png",
    "dosbox-staging": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/dosbox-logo.png",
    "dsh-harness": "https://cdn.jsdelivr.net/gh/deepseek-ai/deepseek-harness@master/apps/web/public/favicon.svg",
    "faster-whisper": "https://cdn.jsdelivr.net/gh/home-assistant/brands@master/core_integrations/wyoming/icon.png",
    "haos-one": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/home-assistant.webp",
    "luanti": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/minetest-icon.png",
    "msedge": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/edge-logo.png",
    "pyload-ng": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/pyload-logo.png",
    "stable-diffusion-webui-nvidia": "https://cdn.jsdelivr.net/gh/IceWhaleTech/CasaOS-AppStore@main/Apps/StableDiffusionWebUI/icon.svg",
    "suite-arr": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons@main/svg/servarr.svg",
    # SWAG publishes no icon of its own; what sits under its name is a 424 KB
    # animated banner. The publisher's mark stands in for it.
    "swag": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/linuxserver-ls-logo.png",
    "vscodium-web": "https://cdn.jsdelivr.net/gh/linuxserver/docker-templates@master/linuxserver.io/img/vscodium-icon.png",
}


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _read(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "ProxMenux"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


class IconResolver:
    """Resolve an application id and title to an icon on cdn.jsdelivr.net.

    selfh.st is preferred because most of the interface already draws from it;
    dashboard-icons covers what it lacks. Both are consulted by exact id, then
    by id and title with separators removed, which is what recovers
    ``homeassistant`` from ``home-assistant`` and ``actualbudget`` from
    ``actual-budget``.
    """

    def __init__(self, selfhst: object | None = None, homarr: object | None = None,
                 publishers: list[object] | None = None) -> None:
        self._sets: list[tuple[dict[str, str], set[str], str]] = []
        self._load_selfhst(selfhst if selfhst is not None else _read(SELFHST_INDEX))
        self._load_homarr(homarr if homarr is not None else _read(HOMARR_INDEX))
        for position, (url, pattern, template) in enumerate(PUBLISHER_TREES):
            tree = publishers[position] if publishers is not None else None
            if tree is None:
                try:
                    tree = _read(url)
                except Exception:
                    # A publisher tree that cannot be read costs coverage, not
                    # correctness: the generic sets already answered first.
                    continue
            self._load_publisher(tree, pattern, template)

    def _load_publisher(self, tree: object, pattern: str, template: str) -> None:
        expression = re.compile(pattern)
        names: dict[str, str] = {}
        entries = tree.get("tree") if isinstance(tree, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            match = expression.fullmatch(str(entry.get("path") or ""))
            if not match:
                continue
            name = match.group("name")
            for candidate in (name.lower(), _key(name)):
                if candidate:
                    names.setdefault(candidate, entry["path"])
        self._sets.append((names, set(), template.replace("{path}", "{name}")))

    def _load_selfhst(self, index: object) -> None:
        names: dict[str, str] = {}
        themed: set[str] = set()
        for entry in index if isinstance(index, list) else []:
            if not isinstance(entry, dict) or entry.get("WebP") != "Yes":
                continue
            reference = str(entry.get("Reference") or "").strip()
            if not reference:
                continue
            for candidate in (reference.lower(), _key(reference), _key(entry.get("Name"))):
                if candidate:
                    names.setdefault(candidate, reference)
            if entry.get("Dark") == "Yes" or entry.get("Light") == "Yes":
                themed.add(reference)
        self._sets.append((names, themed, SELFHST_ICON))

    def _load_homarr(self, tree: object) -> None:
        names: dict[str, str] = {}
        themed: set[str] = set()
        files = tree.get("webp") if isinstance(tree, dict) else None
        for filename in files if isinstance(files, list) else []:
            stem = str(filename)
            if not stem.endswith(".webp"):
                continue
            stem = stem[: -len(".webp")]
            base = VARIANT_SUFFIX_RE.sub("", stem)
            if base != stem:
                themed.add(base)
                continue
            for candidate in (base.lower(), _key(base)):
                if candidate:
                    names.setdefault(candidate, base)
        self._sets.append((names, themed, HOMARR_ICON))

    @staticmethod
    def reachable(url: str | None) -> bool:
        """Whether a URL inherited from a publisher still serves an image.

        The linuxserver templates URL was built from the application id and
        answers 404 for seven out of ten entries, so it is only kept for the
        ones where the file is really there.
        """
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return False
        request = urllib.request.Request(url, method="HEAD",
                                        headers={"User-Agent": "ProxMenux"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status == 200
        except Exception:
            return False

    def resolve(self, app_id: str | None, title: str | None = None) -> dict[str, object] | None:
        """The icon for one application, or None when neither set has it."""
        base = str(app_id or "").strip().lower()
        if base in CURATED:
            return {"url": CURATED[base], "themed": False}
        trimmed = base
        while True:
            shorter = QUALIFIER_RE.sub("", trimmed)
            if shorter == trimmed:
                break
            trimmed = shorter
        lookups = [base, _key(app_id), _key(title)]
        if trimmed != base:
            lookups += [trimmed, _key(trimmed)]
        for names, themed, pattern in self._sets:
            for lookup in lookups:
                name = names.get(lookup) if lookup else None
                if name:
                    return {"url": pattern.format(name=name), "themed": name in themed}
        return None
