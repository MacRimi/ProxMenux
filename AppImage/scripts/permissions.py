"""What each profile may do in the Monitor, and what each route needs.

A profile is a set of permissions: `view` and the actions below. Every
protected route needs exactly one of them, found from its rule and method:

  view      read the dashboard, without secrets
  execute   run scripts and tools
  guests    control VMs and LXC
  backup    manage backups
  update    update the host, guests and ProxMenux
  terminal  open terminals
  admin     administer the Monitor: accounts, settings and secrets

Readings need `view` unless listed in _READING. Anything else is found in
_ACTION by the longest matching prefix; a route that matches none needs
`admin`, and a test keeps every route listed.
"""

ACTIONS = ("execute", "guests", "backup", "update", "terminal", "admin")
PERMISSIONS = ("view",) + ACTIONS

PROFILES = {
    "admin": frozenset(PERMISSIONS),
    "observer": frozenset({"view"}),
    "operator": frozenset({"view", "execute", "guests", "backup", "update", "terminal"}),
    "operator_no_terminal": frozenset({"view", "execute", "guests", "backup", "update"}),
}

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
    return PROFILES.get(profile, frozenset())


def classify(rule, method):
    """The need of a route, or None when it is not listed."""
    method = (method or "GET").upper()
    if method in _READ_METHODS:
        return _READING.get(rule, "view")
    matches = [prefix for prefix in _ACTION if rule == prefix or rule.startswith(prefix)
               and (prefix.endswith("/") or rule[len(prefix)] == "/")]
    return _ACTION[max(matches, key=len)] if matches else None


def required(rule, method):
    """The need of a route: what is not listed needs `admin`."""
    return classify(rule, method) or "admin"


def allows(permissions, need, signed_in=False):
    """Whether `permissions` meet `need`."""
    if need == SELF:
        return signed_in or "admin" in permissions
    if need == TICKET:
        return bool(permissions & {"execute", "update", "terminal", "backup"})
    return need in permissions
