"""ProxMenux LinuxServer-to-Proxmox OCI laboratory tools."""

from .registry_auth import use_cluster_auth_file as _use_cluster_auth_file

__version__ = "0.1.0"

# Every skopeo call of the engine reads the registry accounts kept for the cluster.
_use_cluster_auth_file()
