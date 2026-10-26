"""Report profiles for Audit & Report.

A profile answers one question, so it selects the checks and the
inventory sections that bear on it. The alternative — always producing
everything — leaves the reader to find the relevant part, and is how a
report grows section by section until nobody reads it.

Profiles are declared as data rather than as code so the backend and the
interface work from the same definition, and so adding a check does not
require revisiting every profile: a profile names areas, and only names
individual checks when it needs one that lives elsewhere.
"""
from __future__ import annotations

from typing import Any, Optional

# Every inventory section the composer can produce. A profile lists the
# subset its question needs.
ALL_SECTIONS = (
    "identity", "cluster", "hardware", "network", "latency", "storages", "guests",
    "passthrough", "applications", "custom_links", "proxmenux",
)

PROFILES: dict[str, dict[str, Any]] = {
    # The whole picture. What an assessment produces when no narrower
    # question has been asked.
    "full": {
        "areas": None,          # None means every area
        "include": (),
        "sections": ALL_SECTIONS,
    },

    # Everything is assessed and almost nothing is printed. The reader
    # of this one is deciding what to do in the next few minutes, so it
    # carries the findings that ask for a decision and the readings that
    # could not be taken, and leaves out the inventory, the diagrams and
    # the annex. Scope stays full deliberately: a short report that
    # skipped checks would be quick and untrustworthy.
    "diagnostic": {
        "areas": None,
        "include": (),
        "sections": ("identity",),
        "brief": True,
    },

    # Describes the node without judging it. Runs no checks, so it is
    # available on a host that has never been assessed.
    "inventory": {
        "areas": (),            # empty means no checks
        "include": (),
        "sections": ALL_SECTIONS,
    },

    # Exposure and access. Container privilege and the enterprise
    # repository sit in other areas but bear on the same question.
    "security": {
        "areas": ("security",),
        "include": (
            "guests.privileged_containers",
            "system.security_updates",
            "system.enterprise_repo_without_subscription",
            "system.update_chain",
        ),
        "sections": ("identity", "cluster", "network", "latency", "guests"),
    },

    # Whether guests are protected, and whether the protection is real.
    # Storage is included because a destination that cannot be reached
    # accepts no backup.
    "backup": {
        "areas": ("backup",),
        "include": ("storage.connected_storage", "system.notification_delivery"),
        "sections": ("identity", "cluster", "guests", "storages"),
    },

    # Room to grow and the age of what it grows on.
    "capacity": {
        "areas": ("storage", "hardware"),
        "include": ("system.memory_overcommit", "system.journal_size",
                    "system.swap_configured", "system.filesystem_capacity"),
        "sections": ("identity", "cluster", "hardware", "storages", "guests"),
    },
}

DEFAULT_PROFILE = "full"


def is_known(profile: str) -> bool:
    return profile in PROFILES


def selected_checks(profile: str, checks) -> list:
    """Checks a profile runs, from the registered catalogue.

    ``areas`` of ``None`` selects everything and an empty tuple selects
    nothing, which is what lets the inventory profile produce a document
    without assessing the host.
    """
    spec = PROFILES.get(profile) or PROFILES[DEFAULT_PROFILE]
    areas = spec["areas"]
    include = set(spec["include"])
    if areas is None:
        return list(checks)
    areas = set(areas)
    return [c for c in checks if c.area in areas or c.check_id in include]


def sections(profile: str) -> tuple:
    spec = PROFILES.get(profile) or PROFILES[DEFAULT_PROFILE]
    return tuple(spec["sections"])


def describe() -> list[dict[str, Any]]:
    """Profile catalogue for the interface, without any host data."""
    return [
        {
            "id": name,
            "areas": None if spec["areas"] is None else list(spec["areas"]),
            "include": list(spec["include"]),
            "sections": list(spec["sections"]),
            "runs_checks": spec["areas"] != (),
            "brief": bool(spec.get("brief")),
        }
        for name, spec in PROFILES.items()
    ]
