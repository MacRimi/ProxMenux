"""What each profile may do in the Monitor, and what each route needs.

A profile is a set of permissions: the areas it sees and the actions below.
Every protected route needs one of them, found from its rule and method:

  view      read the dashboard, without secrets, in the areas of the route
  execute   run scripts and tools
  guests    control VMs and LXC
  backup    manage backups
  update    update the host, guests and ProxMenux
  terminal  open terminals
  admin     administer the Monitor: accounts, settings and secrets

Readings need `view` unless listed in _READING, and `view` is met in the
areas _AREA gives the route: any of them, or any area at all for what every
page uses (the header, the health of the host, the own account, settings).
Anything else is found in _ACTION by the longest matching prefix; a route
that matches none needs `admin`, and a test keeps every route listed.
"""

AREAS = ("general", "apps", "menux", "guests", "node", "backup", "logs")
ACTIONS = ("execute", "guests", "backup", "update", "terminal", "admin")
PERMISSIONS = ("view",) + ACTIONS
_ALL_AREAS = frozenset("area." + area for area in AREAS)

PROFILES = {
    "admin": frozenset(PERMISSIONS) | _ALL_AREAS,
    "observer": frozenset({"view"}) | _ALL_AREAS,
    "operator": frozenset({"view", "execute", "guests", "backup", "update", "terminal"}) | _ALL_AREAS,
    "operator_no_terminal": frozenset({"view", "execute", "guests", "backup", "update"}) | _ALL_AREAS,
}

# A custom profile chooses its areas and actions. Administering is not one
# of them: whoever administers can give themselves any profile, which is
# what the Administrator profile already is.
CUSTOM = "custom"
CUSTOM_ACTIONS = tuple(action for action in ACTIONS if action != "admin")


def custom_profile(areas, actions):
    """The profile of a custom choice, as a session carries it:
    custom:<areas>:<actions>. None when the choice is not valid."""
    areas = [a for a in AREAS if a in set(areas or ())]
    actions = [a for a in CUSTOM_ACTIONS if a in set(actions or ())]
    if not areas or set(areas or ()) - set(AREAS):
        return None
    return f"{CUSTOM}:{','.join(areas)}:{','.join(actions)}"


def parse_custom(profile):
    """(areas, actions) of a custom profile, else None."""
    if not isinstance(profile, str) or not profile.startswith(CUSTOM + ":"):
        return None
    parts = profile.split(":")
    if len(parts) != 3:
        return None
    areas = [a for a in parts[1].split(",") if a in AREAS]
    actions = [a for a in parts[2].split(",") if a in CUSTOM_ACTIONS]
    return (areas, actions) if areas else None


# Special needs, not permissions of a profile:
#   self    a signed-in account changing itself: password, profile, avatar.
#   ticket  a single-use ticket for a WebSocket or a download; it carries the
#           permissions of whoever asked for it, and each use checks its own.
SELF = "self"
TICKET = "ticket"

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Readings that carry secrets or another action's output.
_READING = {
    "/api/auth/oidc/config": "admin",
    "/api/audit/changes": "admin",
    "/api/audit/checks": "admin",
    "/api/audit/compare": "admin",
    "/api/audit/exceptions": "admin",
    "/api/audit/inventory": "admin",
    "/api/audit/lynis-readiness": "admin",
    "/api/audit/policy": "admin",
    "/api/audit/profiles": "admin",
    "/api/audit/runs": "admin",
    "/api/audit/runs/<run_id>": "admin",
    "/api/audit/status": "admin",
    "/api/auth/users": "admin",
    "/api/notifications/settings": "admin",
    "/api/notifications/proxmox/read-cfg": "admin",
    "/api/proxmenux/snippets-storage": "admin",
    "/api/terminal/search-command": "terminal",
    "/api/host-update-jobs": "update",
    "/api/host-update-jobs/<run_id>/result": "update",
    "/api/lxc-update-jobs": "update",
    "/api/health/reboot-after-update/status": "update",
    "/api/health/reboot-context": "update",
    "/api/vms/<int:vmid>/backups/delete-status": "backup",
    "/api/host-backups/archives/<path:archive_id>/download": "backup",
    "/api/host-backups/pbs-encryption/download-keyfile": "backup",
    "/api/host-backups/remote-archives/export/<task_id>/download": "backup",
}

# The areas whose pages read a route, by rule prefix: the longest one that
# matches wins. BASE is read by every page, whatever its areas.
BASE = ()
_AREA = {
    # The header, the health of the host, the own account and the pages of
    # the Admin menu every session has (Security, Settings, About).
    "/api/auth/": BASE,
    "/api/health": BASE,
    "/api/info": BASE,
    "/api/platform": BASE,
    "/api/system": BASE,
    "/api/monitor-links": BASE,
    "/api/proxmenux/": BASE,
    "/api/updates/post-install": BASE,
    "/api/security/": BASE,
    "/api/ssl/": BASE,
    "/api/terminal/": BASE,
    "/api/scripts/": BASE,
    "/api/lxc-updates/": BASE,
    "/api/apps/github-token": BASE,
    "/api/apps/categories": BASE,
    "/api/notifications/status": BASE,
    "/api/notifications/history": BASE,
    # General, and the pages that show the same data.
    "/api/storage/summary": ("general",),
    "/api/network/summary": ("general",),
    "/api/temperature/": ("general",),
    "/api/processes": ("general",),
    "/api/prometheus": ("general",),
    "/api/node/metrics": ("general", "node"),
    "/api/network/<interface_name>/metrics": ("general", "node"),
    "/api/proxmox-storage": ("general", "node"),
    "/api/pbs/status": ("general", "backup"),
    "/api/vms": ("general", "guests", "apps"),
    # Apps and the Menux catalog.
    "/api/apps/": ("apps", "guests", "menux"),
    "/api/apps/custom-links": ("apps",),
    "/api/catalog/": ("menux",),
    "/api/oci/": ("apps", "menux"),
    "/api/vms/modal-cache-all": ("guests", "apps", "menux"),
    "/api/vms/<int:vmid>": ("guests", "apps", "menux"),
    "/api/vms/<int:vmid>/apps": ("guests", "apps", "menux"),
    # VMs and LXC.
    "/api/vms/<int:vmid>/": ("guests",),
    "/api/lxc/": ("guests",),
    "/api/backup-storages": ("guests", "backup"),
    # Node: storage, network and hardware.
    "/api/storage": ("node",),
    "/api/network": ("node",),
    "/api/hardware": ("node",),
    "/api/gpu/": ("node",),
    "/api/disk/": ("node",),
    "/api/mounts": ("node",),
    "/api/managed-installs": ("node",),
    # Backups.
    "/api/host-backups/": ("backup",),
    "/api/vm-backup-jobs": ("backup",),
    "/api/vm-backup-storages": ("backup",),
    "/api/pbs/servers": ("backup",),
    "/api/backups": ("backup", "logs"),
    # Logs.
    "/api/logs": ("logs",),
    "/api/events": ("logs",),
    "/api/task-log/": ("logs", "guests"),
    "/api/notifications": ("logs",),
}

# Everything else, by rule prefix: the longest one that matches wins.
_ACTION = {
    # Accounts and the Monitor itself.
    "/api/auth/": "admin",
    "/api/auth/change-password": SELF,
    "/api/auth/profile": SELF,
    "/api/ssl/": "admin",
    "/api/monitor-links": "admin",
    "/api/apps/custom-links": "admin",
    "/api/apps/github-token": "admin",
    "/api/notifications/": "admin",
    "/api/health/": "admin",
    "/api/health/reboot-after-update": "update",
    "/api/security/": "admin",
    "/api/security/lynis/": "execute",
    "/api/audit/": "admin",
    "/api/audit/run": "execute",
    "/api/proxmenux/snippets-storage": "admin",
    "/api/system/power/": "admin",
    # Scripts and tools.
    "/api/scripts/": "execute",
    "/api/storage/smart/": "execute",
    "/api/managed-installs/refresh": "execute",
    "/api/oci/deploy": "execute",
    # VMs, LXC and their apps.
    "/api/vms/<int:vmid>/": "guests",
    "/api/lxc/<int:vmid>/": "guests",
    "/api/oci/installed/": "guests",
    # Backups.
    "/api/host-backups/": "backup",
    "/api/vm-backup-jobs": "backup",
    "/api/vm-backup-storages/": "backup",
    "/api/pbs/servers": "backup",
    "/api/vms/<int:vmid>/backup": "backup",
    "/api/vms/<int:vmid>/backups/": "backup",
    # Updates.
    "/api/system/pve-update": "update",
    "/api/proxmenux/self-update/": "update",
    "/api/lxc-updates/": "update",
    "/api/lxc-apps/dockerhub-tag-preview": "update",
    "/api/vms/<int:vmid>/updates/": "update",
    "/api/vms/<int:vmid>/bulk-update": "update",
    "/api/oci/installed/<app_id>/update": "update",
    # Terminals, scripts and updates ask for a ticket first.
    "/api/terminal/ticket": TICKET,
}


def permissions_of(profile):
    custom = parse_custom(profile)
    if custom is not None:
        areas, actions = custom
        return frozenset({"view"} | {"area." + a for a in areas} | set(actions))
    return PROFILES.get(profile, frozenset())


def _longest(table, rule):
    matches = [prefix for prefix in table if rule == prefix or rule.startswith(prefix)
               and (prefix.endswith("/") or rule[len(prefix)] == "/")]
    return max(matches, key=len) if matches else None


def read_areas(rule):
    """The areas whose pages read `rule` (BASE for every page), or None when
    the route is not listed."""
    prefix = _longest(_AREA, rule)
    return _AREA[prefix] if prefix is not None else None


def classify(rule, method):
    """The need of a route, or None when it is not listed."""
    method = (method or "GET").upper()
    if method in _READ_METHODS:
        return _READING.get(rule, "view")
    prefix = _longest(_ACTION, rule)
    return _ACTION[prefix] if prefix is not None else None


def required(rule, method):
    """The need of a route: what is not listed needs `admin`."""
    return classify(rule, method) or "admin"


def allows(permissions, need, signed_in=False, areas=BASE):
    """Whether `permissions` meet `need`; a reading needs one of `areas`, or
    any area for BASE."""
    if need == "view":
        if "view" not in permissions:
            return False
        return not areas or any("area." + area in permissions for area in areas)
    if need == SELF:
        return signed_in or "admin" in permissions
    if need == TICKET:
        return bool(permissions & {"execute", "update", "terminal", "backup"})
    return need in permissions
