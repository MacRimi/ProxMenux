#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux OCI Manager

Manages deployment and lifecycle of OCI container applications using Proxmox VE 9.1+
native LXC from OCI images functionality.

Usage:
    - As library: import oci_manager; oci_manager.deploy_app(...)
    - As CLI: python oci_manager.py deploy --app-id secure-gateway --config '{...}'
"""

import base64
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Note: We use a simple XOR-based encryption for local token storage
# This avoids the cryptography dependency which has Python version compatibility issues
# (PyO3 modules compiled for specific Python versions cause ImportError on different versions)
ENCRYPTION_AVAILABLE = False

# Logging
logger = logging.getLogger("proxmenux.oci")

# =================================================================
# Paths
# =================================================================
OCI_BASE_DIR = "/usr/local/share/proxmenux/oci"
CATALOG_FILE = os.path.join(OCI_BASE_DIR, "catalog.json")
INSTALLED_FILE = os.path.join(OCI_BASE_DIR, "installed.json")
INSTANCES_DIR = os.path.join(OCI_BASE_DIR, "instances")

# Source catalog from Scripts (bundled with ProxMenux)
SCRIPTS_CATALOG = "/usr/local/share/proxmenux/scripts/oci/catalog.json"
DEV_SCRIPTS_CATALOG = os.path.join(os.path.dirname(__file__), "..", "..", "Scripts", "oci", "catalog.json")

# Encryption key file
ENCRYPTION_KEY_FILE = os.path.join(OCI_BASE_DIR, ".encryption_key")

# Default storage for templates
DEFAULT_STORAGE = "local"

# Default storage for rootfs (will be auto-detected)
DEFAULT_ROOTFS_STORAGE = "local-lvm"

# VMID range for OCI containers (9000-9999 to avoid conflicts)
OCI_VMID_START = 9000
OCI_VMID_END = 9999


# =================================================================
# Encryption Functions for Sensitive Data
# =================================================================
def _get_or_create_encryption_key() -> bytes:
    """Get or create the encryption key for sensitive data."""
    if os.path.exists(ENCRYPTION_KEY_FILE):
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()
    
    # Generate a 32-byte random key
    key = secrets.token_bytes(32)
    
    os.makedirs(os.path.dirname(ENCRYPTION_KEY_FILE), exist_ok=True)
    with open(ENCRYPTION_KEY_FILE, 'wb') as f:
        f.write(key)
    os.chmod(ENCRYPTION_KEY_FILE, 0o600)
    
    return key


def encrypt_sensitive_value(value: str) -> str:
    """
    Encrypt a sensitive value using XOR with a random key.
    Returns base64-encoded string with 'ENC:' prefix.
    
    Note: Uses XOR encryption which is sufficient for local token storage
    and avoids cryptography library compatibility issues across Python versions.
    """
    if not value:
        return value
    
    key = _get_or_create_encryption_key()
    value_bytes = value.encode()
    encrypted = bytes(v ^ key[i % len(key)] for i, v in enumerate(value_bytes))
    return "ENC:" + base64.b64encode(encrypted).decode()


def decrypt_sensitive_value(encrypted: str) -> str:
    """Decrypt a sensitive value."""
    if not encrypted or not encrypted.startswith("ENC:"):
        return encrypted
    
    encrypted_data = encrypted[4:]
    key = _get_or_create_encryption_key()
    
    try:
        encrypted_bytes = base64.b64decode(encrypted_data)
        decrypted = bytes(v ^ key[i % len(key)] for i, v in enumerate(encrypted_bytes))
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Failed to decrypt value: {e}")
        return encrypted


def encrypt_config_sensitive_fields(config: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt sensitive fields in config based on schema."""
    encrypted_config = config.copy()
    for field_name, field_schema in schema.items():
        if field_schema.get("sensitive") and field_name in encrypted_config:
            value = encrypted_config[field_name]
            if value and not str(value).startswith("ENC:"):
                encrypted_config[field_name] = encrypt_sensitive_value(str(value))
    return encrypted_config


def decrypt_config_sensitive_fields(config: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt sensitive fields in config based on schema."""
    decrypted_config = config.copy()
    for field_name, field_schema in schema.items():
        if field_schema.get("sensitive") and field_name in decrypted_config:
            value = decrypted_config[field_name]
            if value and str(value).startswith("ENC:"):
                decrypted_config[field_name] = decrypt_sensitive_value(str(value))
    return decrypted_config


# =================================================================
# Directory Management
# =================================================================
def ensure_oci_directories():
    """Ensure OCI directories exist and catalog is available."""
    os.makedirs(OCI_BASE_DIR, exist_ok=True)
    os.makedirs(INSTANCES_DIR, exist_ok=True)
    
    if not os.path.exists(CATALOG_FILE):
        if os.path.exists(SCRIPTS_CATALOG):
            shutil.copy2(SCRIPTS_CATALOG, CATALOG_FILE)
        elif os.path.exists(DEV_SCRIPTS_CATALOG):
            shutil.copy2(DEV_SCRIPTS_CATALOG, CATALOG_FILE)
    
    if not os.path.exists(INSTALLED_FILE):
        with open(INSTALLED_FILE, 'w') as f:
            json.dump({"version": "1.0.0", "instances": {}}, f, indent=2)


# =================================================================
# Proxmox VE Detection and Compatibility
# =================================================================
def check_proxmox_version() -> Dict[str, Any]:
    """Check Proxmox VE version and OCI support."""
    result = {
        "is_proxmox": False,
        "version": None,
        "oci_support": False,
        "error": None
    }
    
    try:
        # Check if pveversion exists
        if not shutil.which("pveversion"):
            result["error"] = "Not running on Proxmox VE"
            return result
        
        proc = subprocess.run(
            ["pveversion"],
            capture_output=True, text=True, timeout=5
        )
        
        if proc.returncode != 0:
            result["error"] = "Failed to get Proxmox version"
            return result
        
        # Parse version: "pve-manager/9.1-2/abc123..."
        version_str = proc.stdout.strip()
        result["is_proxmox"] = True
        
        match = re.search(r'pve-manager/(\d+)\.(\d+)', version_str)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            result["version"] = f"{major}.{minor}"
            # OCI support requires Proxmox VE 9.1+
            result["oci_support"] = (major > 9) or (major == 9 and minor >= 1)
        
        # Also check if skopeo is available (required for OCI)
        if result["oci_support"] and not shutil.which("skopeo"):
            result["oci_support"] = False
            result["error"] = "skopeo not found. Install with: apt install skopeo"
        
        if not result["oci_support"] and not result.get("error"):
            result["error"] = f"OCI support requires Proxmox VE 9.1+, found {result['version']}"
            
    except Exception as e:
        result["error"] = str(e)
    
    return result


def _run_pve_cmd(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    """Run a Proxmox VE command."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


# =================================================================
# VMID Management
# =================================================================
def _get_next_vmid() -> int:
    """Get next available VMID in OCI range (9000-9999)."""
    try:
        # Get list of all VMIDs in use
        rc, out, _ = _run_pve_cmd(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"])
        
        if rc != 0:
            # Fallback: try pct list
            rc, out, _ = _run_pve_cmd(["pct", "list"])
            used_vmids = set()
            if rc == 0:
                for line in out.splitlines()[1:]:  # Skip header
                    parts = line.split()
                    if parts:
                        try:
                            used_vmids.add(int(parts[0]))
                        except ValueError:
                            pass
        else:
            resources = json.loads(out)
            used_vmids = {r.get("vmid") for r in resources if r.get("vmid")}
        
        # Find first available in OCI range
        for vmid in range(OCI_VMID_START, OCI_VMID_END + 1):
            if vmid not in used_vmids:
                return vmid
        
        raise RuntimeError("No available VMID in OCI range (9000-9999)")
        
    except Exception as e:
        logger.error(f"Failed to get next VMID: {e}")
        # Return a high number and hope for the best
        return OCI_VMID_START + int(time.time()) % 1000


def _get_vmid_for_app(app_id: str) -> Optional[int]:
    """Get the VMID for an installed app."""
    installed = _load_installed()
    instance = installed.get("instances", {}).get(app_id)
    return instance.get("vmid") if instance else None


def get_available_storages() -> List[Dict[str, Any]]:
    """Get list of storages available for LXC rootfs.
    
    Returns storages that support 'images' or 'rootdir' content types,
    which are required for LXC container disks.
    """
    storages = []
    
    try:
        # Use pvesm status to get all storages (parse text output for compatibility)
        rc, out, err = _run_pve_cmd(["pvesm", "status"])
        if rc != 0:
            logger.error(f"Failed to get storage status: {err}")
            return storages
        
        # Parse text output: Name Type Status Total Used Available %
        # Example: local-lvm lvmthin active 464031744 15491072 448540672 3.34%
        lines = out.strip().split('\n')
        for line in lines[1:]:  # Skip header
            parts = line.split()
            if len(parts) < 4:
                continue
            
            storage_name = parts[0]
            storage_type = parts[1]
            status = parts[2]
            
            # Skip if storage is not active
            if status != "active":
                continue
            
            # Get capacity info
            total_bytes = int(parts[3]) * 1024 if len(parts) > 3 and parts[3].isdigit() else 0
            used_bytes = int(parts[4]) * 1024 if len(parts) > 4 and parts[4].isdigit() else 0
            avail_bytes = int(parts[5]) * 1024 if len(parts) > 5 and parts[5].isdigit() else total_bytes - used_bytes
            
            # Check if storage supports rootdir/images content (for LXC)
            # Read from /etc/pve/storage.cfg directly for compatibility
            content = ""
            try:
                with open("/etc/pve/storage.cfg", "r") as f:
                    cfg_content = f.read()
                    # Find the storage section
                    import re
                    pattern = rf'{storage_type}:\s*{re.escape(storage_name)}\s*\n((?:\s+[^\n]+\n)*)'
                    match = re.search(pattern, cfg_content)
                    if match:
                        section = match.group(1)
                        content_match = re.search(r'content\s+(\S+)', section)
                        if content_match:
                            content = content_match.group(1)
            except Exception:
                # Fallback: assume block storages support images
                if storage_type in ("lvm", "lvmthin", "zfspool", "rbd"):
                    content = "images,rootdir"
                elif storage_type in ("dir", "nfs", "cifs", "btrfs"):
                    content = "rootdir,images"
            
            # Storage must support "images" or "rootdir" for LXC rootfs
            if "images" in content or "rootdir" in content:
                # Determine recommendation priority
                # Prefer: zfspool > lvmthin > btrfs > lvm > others
                priority = 99
                if storage_type == "zfspool":
                    priority = 1
                elif storage_type == "lvmthin":
                    priority = 2
                elif storage_type == "btrfs":
                    priority = 3
                elif storage_type == "lvm":
                    priority = 4
                elif storage_type in ("dir", "nfs", "cifs"):
                    priority = 10
                
                storages.append({
                    "name": storage_name,
                    "type": storage_type,
                    "total": total_bytes,
                    "used": used_bytes,
                    "avail": avail_bytes,
                    "active": True,
                    "enabled": True,
                    "priority": priority,
                    "recommended": False  # Will be set after sorting
                })
        
        # Sort by priority (lower = better), then by available space
        storages.sort(key=lambda s: (s.get("priority", 99), -s.get("avail", 0)))
        
        # Mark the first one as recommended
        if storages:
            storages[0]["recommended"] = True
            
    except Exception as e:
        logger.error(f"Failed to get available storages: {e}")
    
    return storages


def _download_alpine_template(storage: str = DEFAULT_STORAGE) -> bool:
    """Download the latest Alpine LXC template using pveam."""
    print("[*] Downloading Alpine Linux template...")
    logger.info("Downloading Alpine template via pveam")
    
    # Update template list first
    rc, out, err = _run_pve_cmd(["pveam", "update"], timeout=60)
    if rc != 0:
        logger.warning(f"Failed to update template list: {err}")
    
    # Get available Alpine templates
    rc, out, err = _run_pve_cmd(["pveam", "available", "--section", "system"], timeout=30)
    if rc != 0:
        logger.error(f"Failed to list available templates: {err}")
        return False
    
    # Find latest Alpine template
    alpine_template = None
    for line in out.strip().split('\n'):
        if 'alpine-' in line.lower():
            parts = line.split()
            if len(parts) >= 2:
                alpine_template = parts[1]  # Template name is usually second column
    
    if not alpine_template:
        logger.error("No Alpine template found in available templates")
        return False
    
    # Download the template
    print(f"[*] Downloading template: {alpine_template}")
    rc, out, err = _run_pve_cmd(["pveam", "download", storage, alpine_template], timeout=300)
    if rc != 0:
        logger.error(f"Failed to download template: {err}")
        return False
    
    print("[+] Alpine template downloaded successfully")
    logger.info(f"Successfully downloaded Alpine template: {alpine_template}")
    return True


def _find_alpine_template(storage: str = DEFAULT_STORAGE, auto_download: bool = True) -> Optional[str]:
    """Find an available Alpine LXC template, optionally downloading if not found."""
    template_dir = "/var/lib/vz/template/cache"
    
    # Try to get correct path from storage config
    rc, out, _ = _run_pve_cmd(["pvesm", "path", f"{storage}:vztmpl/test"])
    if rc == 0 and out.strip():
        template_dir = os.path.dirname(out.strip())
    
    # Look for Alpine templates
    try:
        templates = os.listdir(template_dir)
        alpine_templates = [t for t in templates if t.startswith("alpine-") and t.endswith((".tar.xz", ".tar.gz", ".tar"))]
        
        if alpine_templates:
            # Sort to get latest version
            alpine_templates.sort(reverse=True)
            return f"{storage}:vztmpl/{alpine_templates[0]}"
    except Exception as e:
        logger.error(f"Failed to find Alpine template: {e}")
    
    # Template not found - try to download it automatically
    if auto_download:
        logger.info("Alpine template not found, attempting to download...")
        if _download_alpine_template(storage):
            # Try to find it again after download
            return _find_alpine_template(storage, auto_download=False)
    
    return None


def _install_packages_in_lxc(vmid: int, packages: List[str], install_method: str = "apk") -> bool:
    """Install packages inside an LXC container."""
    if not packages:
        return True
    
    print(f"[*] Installing packages: {', '.join(packages)}")
    
    if install_method == "apk":
        # Alpine Linux
        cmd = ["pct", "exec", str(vmid), "--", "apk", "add"] + packages
    elif install_method == "apt":
        # Debian/Ubuntu
        _run_pve_cmd(["pct", "exec", str(vmid), "--", "apt-get", "update"], timeout=120)
        cmd = ["pct", "exec", str(vmid), "--", "apt-get", "install", "-y"] + packages
    else:
        logger.error(f"Unknown install method: {install_method}")
        return False
    
    rc, out, err = _run_pve_cmd(cmd, timeout=300)
    
    if rc != 0:
        logger.error(f"Failed to install packages: {err}")
        return False
    
    print(f"[OK] Packages installed")
    return True


def _enable_services_in_lxc(vmid: int, services: List[str], install_method: str = "apk") -> bool:
    """Enable and start services inside an LXC container."""
    if not services:
        return True
    
    print(f"[*] Enabling services: {', '.join(services)}")
    
    for service in services:
        if install_method == "apk":
            # Alpine uses OpenRC
            _run_pve_cmd(["pct", "exec", str(vmid), "--", "rc-update", "add", service], timeout=30)
            _run_pve_cmd(["pct", "exec", str(vmid), "--", "service", service, "start"], timeout=30)
        else:
            # Debian/Ubuntu uses systemd
            _run_pve_cmd(["pct", "exec", str(vmid), "--", "systemctl", "enable", service], timeout=30)
            _run_pve_cmd(["pct", "exec", str(vmid), "--", "systemctl", "start", service], timeout=30)
    
    print(f"[OK] Services enabled")
    return True


def _configure_tailscale(vmid: int, config: Dict[str, Any]) -> bool:
    """Configure Tailscale inside the container."""
    auth_key = config.get("auth_key", "")
    if not auth_key:
        logger.warning("No auth_key provided for Tailscale")
        return False
    
    print(f"[*] Configuring Tailscale...")
    
    # Build tailscale up command
    ts_cmd = ["tailscale", "up", f"--authkey={auth_key}"]
    
    hostname = config.get("hostname")
    if hostname:
        ts_cmd.append(f"--hostname={hostname}")
    
    advertise_routes = config.get("advertise_routes")
    if advertise_routes:
        if isinstance(advertise_routes, list):
            advertise_routes = ",".join(advertise_routes)
        ts_cmd.append(f"--advertise-routes={advertise_routes}")
    
    if config.get("exit_node"):
        ts_cmd.append("--advertise-exit-node")
    
    if config.get("accept_routes"):
        ts_cmd.append("--accept-routes")
    
    # Run tailscale up
    rc, out, err = _run_pve_cmd(["pct", "exec", str(vmid), "--"] + ts_cmd, timeout=60)
    
    if rc != 0:
        logger.error(f"Tailscale configuration failed: {err}")
        print(f"[!] Tailscale error: {err}")
        return False
    
    print(f"[OK] Tailscale configured")
    return True


# =================================================================
# OCI Image Management
# =================================================================
def pull_oci_image(image: str, tag: str = "latest", storage: str = DEFAULT_STORAGE) -> Dict[str, Any]:
    """
    Pull an OCI image from a registry and store as LXC template.
    Uses Proxmox's pvesh API to download OCI images (same as GUI).
    
    Args:
        image: Image name (e.g., "docker.io/tailscale/tailscale")
        tag: Image tag (e.g., "stable")
        storage: Proxmox storage to save template
    
    Returns:
        Dict with success status and template path
    """
    result = {
        "success": False,
        "message": "",
        "template": None
    }
    
    # Check Proxmox OCI support
    pve_info = check_proxmox_version()
    if not pve_info["oci_support"]:
        result["message"] = pve_info.get("error", "OCI not supported")
        return result
    
    # Normalize image name - ensure full registry path
    if not image.startswith(("docker.io/", "ghcr.io/", "quay.io/", "registry.")):
        image = f"docker.io/{image}"
    
    # For docker.io, library images need explicit library/ prefix
    parts = image.split("/")
    if parts[0] == "docker.io" and len(parts) == 2:
        image = f"docker.io/library/{parts[1]}"
    
    full_ref = f"{image}:{tag}"
    
    logger.info(f"Pulling OCI image: {full_ref}")
    print(f"[*] Pulling OCI image: {full_ref}")
    
    # Create a safe filename from the image reference
    # e.g., docker.io/tailscale/tailscale:stable -> tailscale-tailscale-stable.tar
    # Note: Use .tar extension (not .tar.zst) - skopeo creates uncompressed tar
    filename = image.replace("docker.io/", "").replace("ghcr.io/", "").replace("library/", "").replace("/", "-")
    filename = f"{filename}-{tag}.tar"
    
    # Get hostname for API
    hostname = os.uname().nodename
    
    # Use Proxmox's pvesh API to download the OCI image
    # This is exactly what the GUI does
    rc, out, err = _run_pve_cmd([
        "pvesh", "create", 
        f"/nodes/{hostname}/storage/{storage}/download-url",
        "--content", "vztmpl",
        "--filename", filename,
        "--url", f"docker://{full_ref}"
    ], timeout=600)
    
    if rc != 0:
        # Fallback: try direct skopeo if pvesh API fails
        logger.warning(f"pvesh download failed: {err}, trying skopeo fallback")
        
        if not shutil.which("skopeo"):
            result["message"] = f"Failed to pull image via API: {err}"
            return result
        
        # Get template directory
        template_dir = "/var/lib/vz/template/cache"
        rc2, out2, _ = _run_pve_cmd(["pvesm", "path", f"{storage}:vztmpl/test"])
        if rc2 == 0 and out2.strip():
            template_dir = os.path.dirname(out2.strip())
        
        template_path = os.path.join(template_dir, filename)
        
        # Use skopeo with docker-archive format (works with multi-layer images in Proxmox 9.1)
        # Note: oci-archive fails with multi-layer images, docker-archive works
        try:
            proc = subprocess.run(
                ["skopeo", "copy", "--override-os", "linux", "--override-arch", "amd64",
                 f"docker://{full_ref}", f"docker-archive:{template_path}"],
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if proc.returncode != 0:
                result["message"] = f"Failed to pull image: {proc.stderr}"
                logger.error(f"skopeo copy failed: {proc.stderr}")
                return result
        except subprocess.TimeoutExpired:
            result["message"] = "Image pull timed out after 10 minutes"
            return result
        except Exception as e:
            result["message"] = f"Failed to pull image: {e}"
            logger.error(f"Pull failed: {e}")
            return result
    
    # Template was created via API or skopeo
    result["success"] = True
    result["template"] = f"{storage}:vztmpl/{filename}"
    result["message"] = "Image pulled successfully"
    print(f"[OK] Image pulled: {result['template']}")
    
    return result


# =================================================================
# Catalog Management
# =================================================================
def load_catalog() -> Dict[str, Any]:
    """Load the OCI app catalog."""
    ensure_oci_directories()
    
    for path in [CATALOG_FILE, SCRIPTS_CATALOG, DEV_SCRIPTS_CATALOG]:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load catalog from {path}: {e}")
    
    return {"version": "1.0.0", "apps": {}}


def get_app_definition(app_id: str) -> Optional[Dict[str, Any]]:
    """Get the definition for a specific app."""
    catalog = load_catalog()
    return catalog.get("apps", {}).get(app_id)


def list_available_apps() -> List[Dict[str, Any]]:
    """List all available apps from the catalog."""
    catalog = load_catalog()
    apps = []
    for app_id, app_def in catalog.get("apps", {}).items():
        apps.append({
            "id": app_id,
            "name": app_def.get("name", app_id),
            "short_name": app_def.get("short_name", app_def.get("name", app_id)),
            "category": app_def.get("category", "uncategorized"),
            "subcategory": app_def.get("subcategory", ""),
            "icon": app_def.get("icon", "box"),
            "color": app_def.get("color", "#6366F1"),
            "summary": app_def.get("summary", ""),
            "installed": is_installed(app_id)
        })
    return apps


# =================================================================
# Installed Apps Management
# =================================================================
def _load_installed() -> Dict[str, Any]:
    """Load the installed apps registry."""
    ensure_oci_directories()
    if not os.path.exists(INSTALLED_FILE):
        return {"version": "1.0.0", "instances": {}}
    try:
        with open(INSTALLED_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"version": "1.0.0", "instances": {}}


def _save_installed(data: Dict[str, Any]) -> bool:
    """Save the installed apps registry."""
    try:
        with open(INSTALLED_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save installed: {e}")
        return False


def is_installed(app_id: str) -> bool:
    """Check if an app is installed."""
    installed = _load_installed()
    return app_id in installed.get("instances", {})


def list_installed_apps() -> List[Dict[str, Any]]:
    """List all installed apps with their status."""
    installed = _load_installed()
    apps = []
    for app_id, instance in installed.get("instances", {}).items():
        status = get_app_status(app_id)
        apps.append({
            "id": app_id,
            "instance_name": instance.get("instance_name", app_id),
            "vmid": instance.get("vmid"),
            "installed_at": instance.get("installed_at"),
            "installed_by": instance.get("installed_by", "unknown"),
            "status": status
        })
    return apps


def get_installed_app(app_id: str) -> Optional[Dict[str, Any]]:
    """Get details of an installed app."""
    installed = _load_installed()
    instance = installed.get("instances", {}).get(app_id)
    if not instance:
        return None
    instance["status"] = get_app_status(app_id)
    return instance


# =================================================================
# Container Status
# =================================================================
def get_app_status(app_id: str) -> Dict[str, Any]:
    """Get the current status of an app's LXC container."""
    result = {
        "state": "not_installed",
        "health": "unknown",
        "uptime_seconds": 0,
        "last_check": datetime.now().isoformat()
    }
    
    if not is_installed(app_id):
        return result
    
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["state"] = "error"
        result["health"] = "unknown"
        return result
    
    # Get LXC status using pct
    rc, out, _ = _run_pve_cmd(["pct", "status", str(vmid)])
    
    if rc != 0:
        result["state"] = "error"
        result["health"] = "unhealthy"
        return result
    
    # Parse status: "status: running" or "status: stopped"
    if "running" in out.lower():
        result["state"] = "running"
        result["health"] = "healthy"
        
        # Get uptime
        rc, out, _ = _run_pve_cmd(["pct", "exec", str(vmid), "--", "cat", "/proc/uptime"])
        if rc == 0:
            try:
                uptime = float(out.split()[0])
                result["uptime_seconds"] = int(uptime)
            except:
                pass
    elif "stopped" in out.lower():
        result["state"] = "stopped"
        result["health"] = "stopped"
    else:
        result["state"] = "unknown"
    
    return result


# =================================================================
# Deployment
# =================================================================
def deploy_app(app_id: str, config: Dict[str, Any], installed_by: str = "web") -> Dict[str, Any]:
    """
    Deploy an OCI app as a Proxmox LXC container.
    
    Args:
        app_id: ID of the app from the catalog
        config: User configuration values (includes 'storage' for rootfs location)
        installed_by: Source of installation ('web' or 'cli')
    
    Returns:
        Dict with success status and details
    """
    result = {
        "success": False,
        "message": "",
        "app_id": app_id,
        "vmid": None
    }
    
    # Note: We don't require PVE 9.1+ here because secure-gateway uses standard LXC,
    # not OCI containers. OCI support will be checked when deploying actual OCI apps.
    
    # Get app definition
    app_def = get_app_definition(app_id)
    if not app_def:
        result["message"] = f"App '{app_id}' not found in catalog"
        return result
    
    # Check if already installed
    if is_installed(app_id):
        result["message"] = f"App '{app_id}' is already installed"
        return result
    
    container_def = app_def.get("container", {})
    container_type = container_def.get("type", "oci")
    
    # Get storage for rootfs - from config or auto-detect
    rootfs_storage = config.get("storage")
    if not rootfs_storage:
        # Auto-detect available storage
        available = get_available_storages()
        if available:
            # Use the first one (should be recommended)
            rootfs_storage = available[0]["name"]
            logger.info(f"Auto-detected rootfs storage: {rootfs_storage}")
        else:
            rootfs_storage = DEFAULT_ROOTFS_STORAGE
            logger.warning(f"No storage detected, using default: {rootfs_storage}")
    
    # Get next available VMID
    vmid = _get_next_vmid()
    result["vmid"] = vmid
    
    hostname = config.get("hostname", f"proxmenux-{app_id}")
    
    logger.info(f"Deploying {app_id} as LXC {vmid}")
    print(f"[*] Deploying {app_id} as LXC container (VMID: {vmid})")
    
    # Determine deployment method: LXC traditional or OCI image
    if container_type == "lxc":
        # Use traditional LXC with Alpine template + package installation
        # This is more reliable than OCI images which have bugs in Proxmox 9.1
        template = _find_alpine_template()
        if not template:
            result["message"] = "Alpine template not found. Please download it from CT Templates."
            return result
        
        print(f"[*] Using LXC template: {template}")
        use_oci = False
    else:
        # OCI image deployment (may have issues with multi-layer images)
        image = container_def.get("image", "")
        if not image:
            result["message"] = "No container image specified in app definition"
            return result
        
        if ":" in image:
            image_name, tag = image.rsplit(":", 1)
        else:
            image_name, tag = image, "latest"
        
        print(f"[*] Pulling OCI image: {image}")
        pull_result = pull_oci_image(image_name, tag)
        
        if not pull_result["success"]:
            result["message"] = pull_result["message"]
            return result
        
        template = pull_result["template"]
        use_oci = True
    
    # Step 2: Create LXC container
    print(f"[*] Creating LXC container...")
    
    pct_cmd = [
        "pct", "create", str(vmid), template,
        "--hostname", hostname,
        "--memory", str(container_def.get("memory", 512)),
        "--cores", str(container_def.get("cores", 1)),
        "--rootfs", f"{rootfs_storage}:{container_def.get('disk_size', 4)}",
        "--unprivileged", "0" if container_def.get("privileged") else "1",
        "--onboot", "1"
    ]
    
    # Add ostype for OCI containers
    if use_oci:
        pct_cmd.extend(["--ostype", "unmanaged"])
    
    # Add features (nesting, etc.)
    features = container_def.get("features", [])
    if features:
        pct_cmd.extend(["--features", ",".join(features)])
    
    # Network configuration - use simple bridge with DHCP
    pct_cmd.extend(["--net0", "name=eth0,bridge=vmbr0,ip=dhcp"])
    
    # Run pct create
    rc, out, err = _run_pve_cmd(pct_cmd, timeout=120)
    
    if rc != 0:
        result["message"] = f"Failed to create container: {err}"
        logger.error(f"pct create failed: {err}")
        return result
    
    # Step 3: Apply extra LXC configuration (for unprivileged containers)
    lxc_config = container_def.get("lxc_config", [])
    if lxc_config:
        conf_file = f"/etc/pve/lxc/{vmid}.conf"
        try:
            with open(conf_file, 'a') as f:
                f.write("\n# ProxMenux OCI extra config\n")
                for config_line in lxc_config:
                    f.write(f"{config_line}\n")
            logger.info(f"Applied extra LXC config to {conf_file}")
        except Exception as e:
            logger.warning(f"Could not apply extra LXC config: {e}")
    
    # Step 3.1: Set HTML description for Proxmox Notes panel
    html_desc = _generate_html_description(app_def, container_def, hostname)
    if html_desc:
        rc, _, err = _run_pve_cmd(["pct", "set", str(vmid), "-description", html_desc])
        if rc == 0:
            logger.info(f"Set HTML description for container {vmid}")
        else:
            logger.warning(f"Could not set description: {err}")
    
    # Step 4: Configure environment variables (only for OCI containers)
    if use_oci:
        env_vars = []
        for env in container_def.get("environment", []):
            env_name = env.get("name", "")
            env_value = env.get("value", "")
            
            if env_value.startswith("$"):
                config_key = env_value[1:]
                env_value = config.get(config_key, env.get("default", ""))
            
            if env_name and env_value:
                env_vars.append(f"{env_name}={env_value}")
        
        if env_vars:
            for env in env_vars:
                _run_pve_cmd(["pct", "set", str(vmid), f"--lxc.environment", env])
    
    # Step 5: Enable IP forwarding if needed (for VPN containers)
    if container_def.get("requires_ip_forward"):
        _enable_host_ip_forwarding()
    
    # Step 6: Start the container
    print(f"[*] Starting container...")
    rc, _, err = _run_pve_cmd(["pct", "start", str(vmid)])
    
    if rc != 0:
        result["message"] = f"Container created but failed to start: {err}"
        logger.error(f"pct start failed: {err}")
        return result
    
    # Step 7: For LXC containers, install packages and configure
    if not use_oci:
        packages = container_def.get("packages", [])
        install_method = container_def.get("install_method", "apk")
        
        if packages:
            if not _install_packages_in_lxc(vmid, packages, install_method):
                result["message"] = "Container created but package installation failed"
                return result
        
        services = container_def.get("services", [])
        if services:
            _enable_services_in_lxc(vmid, services, install_method)
        
        # Special handling for Tailscale
        if "tailscale" in packages:
            _configure_tailscale(vmid, config)
    
    # Step 8: Save instance data
    instance_dir = os.path.join(INSTANCES_DIR, app_id)
    os.makedirs(instance_dir, exist_ok=True)
    
    config_file = os.path.join(instance_dir, "config.json")
    config_schema = app_def.get("config_schema", {})
    encrypted_config = encrypt_config_sensitive_fields(config, config_schema)
    
    with open(config_file, 'w') as f:
        json.dump({
            "app_id": app_id,
            "vmid": vmid,
            "created_at": datetime.now().isoformat(),
            "values": encrypted_config
        }, f, indent=2)
    os.chmod(config_file, 0o600)
    
    # Update installed registry
    installed = _load_installed()
    installed["instances"][app_id] = {
        "app_id": app_id,
        "vmid": vmid,
        "instance_name": hostname,
        "installed_at": datetime.now().isoformat(),
        "installed_by": installed_by,
        "template": template,
        "container_type": container_type
    }
    _save_installed(installed)
    
    result["success"] = True
    result["message"] = f"App deployed successfully as LXC {vmid}"
    print(f"[OK] Container {vmid} ({hostname}) deployed successfully!")
    
    return result


def _generate_html_description(app_def: Dict, container_def: Dict, hostname: str) -> str:
    """
    Generate HTML description for Proxmox Notes panel.
    
    Tries to use the shared description_templates module if available,
    otherwise falls back to inline implementation.
    """
    try:
        # Try to import the shared templates module
        import sys
        templates_path = Path("/usr/local/share/proxmenux/scripts/oci")
        if templates_path.exists():
            sys.path.insert(0, str(templates_path))
        
        from description_templates import generate_description
        return generate_description(app_def, container_def, hostname)
    except ImportError:
        pass
    
    # Fallback: inline implementation
    import urllib.parse
    
    app_name = app_def.get("name", "ProxMenux App")
    app_subtitle = app_def.get("subtitle", app_def.get("short_name", ""))
    app_color = app_def.get("color", "#0EA5E9")
    app_icon_type = app_def.get("icon_type", "default")
    doc_url = app_def.get("documentation_url", "https://macrimi.github.io/ProxMenux/")
    code_url = app_def.get("code_url", "https://github.com/MacRimi/ProxMenux")
    installer_url = app_def.get("installer_url", "")
    
    # Generate icon based on type
    if app_icon_type == "shield":
        icon_svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 24 24' fill='none' stroke='{app_color}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/><path d='M9 12l2 2 4-4'/></svg>"""
    else:
        icon_svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 24 24' fill='none' stroke='{app_color}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z'/><polyline points='3.27 6.96 12 12.01 20.73 6.96'/><line x1='12' y1='22.08' x2='12' y2='12'/></svg>"""
    
    icon_data = "data:image/svg+xml," + urllib.parse.quote(icon_svg)
    
    # Build badges
    badges = [
        f"<a href='{doc_url}' target='_blank'><img src='https://img.shields.io/badge/📚_Docs-blue' alt='Docs'></a>",
        f"<a href='{code_url}' target='_blank'><img src='https://img.shields.io/badge/💻_Code-green' alt='Code'></a>",
    ]
    if installer_url:
        badges.append(f"<a href='{installer_url}' target='_blank'><img src='https://img.shields.io/badge/📦_Installer-orange' alt='Installer'></a>")
    badges.append("<a href='https://ko-fi.com/macrimi' target='_blank'><img src='https://img.shields.io/badge/☕_Ko--fi-red' alt='Ko-fi'></a>")
    
    badges_html = "\n".join(badges)
    
    html_desc = f"""<div align='center'>
<table style='width: 100%; border-collapse: collapse;'>
<tr>
<td style='width: 100px; vertical-align: middle;'>
<img src="/images/design-mode/logo_desc.png" alt='ProxMenux Logo' style='height: 100px;'>
</td>
<td style='vertical-align: middle;'>
<h1 style='margin: 0;'>{app_name}</h1>
<p style='margin: 0;'>Created with ProxMenux</p>
</td>
</tr>
</table>

<div style='margin: 15px 0; padding: 10px; background: #2d2d2d; border-radius: 8px; display: inline-block;'>
<table style='border-collapse: collapse;'>
<tr>
<td style='vertical-align: middle; padding-right: 10px;'>
<img src='{icon_data}' alt='Icon' style='height: 48px;'>
</td>
<td style='vertical-align: middle; text-align: left;'>
<span style='font-size: 18px; font-weight: bold; color: {app_color};'>{app_name}</span><br>
<span style='color: #9ca3af;'>{app_subtitle}</span>
</td>
</tr>
</table>
</div>

<p>
{badges_html}
</p>

<p style='color: #6b7280; font-size: 12px;'>
Hostname: {hostname}
</p>
</div>"""
    
    return html_desc


def _enable_host_ip_forwarding() -> bool:
    """Enable IP forwarding on the Proxmox host."""
    logger.info("Enabling IP forwarding on host")
    print("[*] Enabling IP forwarding...")
    
    try:
        # Enable IPv4 forwarding
        with open("/proc/sys/net/ipv4/ip_forward", 'w') as f:
            f.write('1')
        
        # Enable IPv6 forwarding
        ipv6_path = "/proc/sys/net/ipv6/conf/all/forwarding"
        if os.path.exists(ipv6_path):
            with open(ipv6_path, 'w') as f:
                f.write('1')
        
        # Make persistent
        sysctl_d = "/etc/sysctl.d/99-proxmenux-ip-forward.conf"
        with open(sysctl_d, 'w') as f:
            f.write("net.ipv4.ip_forward = 1\n")
            f.write("net.ipv6.conf.all.forwarding = 1\n")
        
        subprocess.run(["sysctl", "-p", sysctl_d], capture_output=True)
        return True
        
    except Exception as e:
        logger.warning(f"Could not enable IP forwarding: {e}")
        return False


# =================================================================
# Container Control
# =================================================================
def start_app(app_id: str) -> Dict[str, Any]:
    """Start an app's LXC container."""
    result = {"success": False, "message": ""}
    
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["message"] = f"App '{app_id}' not found"
        return result
    
    rc, _, err = _run_pve_cmd(["pct", "start", str(vmid)])
    
    if rc == 0:
        result["success"] = True
        result["message"] = f"Container {vmid} started"
    else:
        result["message"] = f"Failed to start: {err}"
    
    return result


def stop_app(app_id: str) -> Dict[str, Any]:
    """Stop an app's LXC container."""
    result = {"success": False, "message": ""}
    
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["message"] = f"App '{app_id}' not found"
        return result
    
    rc, _, err = _run_pve_cmd(["pct", "stop", str(vmid)])
    
    if rc == 0:
        result["success"] = True
        result["message"] = f"Container {vmid} stopped"
    else:
        result["message"] = f"Failed to stop: {err}"
    
    return result


def restart_app(app_id: str) -> Dict[str, Any]:
    """Restart an app's LXC container."""
    result = {"success": False, "message": ""}
    
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["message"] = f"App '{app_id}' not found"
        return result
    
    rc, _, err = _run_pve_cmd(["pct", "reboot", str(vmid)])
    
    if rc == 0:
        result["success"] = True
        result["message"] = f"Container {vmid} restarted"
    else:
        result["message"] = f"Failed to restart: {err}"
    
    return result


def remove_app(app_id: str, remove_data: bool = True) -> Dict[str, Any]:
    """Remove an app's LXC container."""
    result = {"success": False, "message": ""}
    
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["message"] = f"App '{app_id}' not found"
        return result
    
    logger.info(f"Removing app {app_id} (VMID: {vmid})")
    
    # Stop if running
    _run_pve_cmd(["pct", "stop", str(vmid)])
    time.sleep(2)
    
    # Destroy container
    rc, _, err = _run_pve_cmd(["pct", "destroy", str(vmid), "--purge"])
    
    if rc != 0:
        result["message"] = f"Failed to destroy container: {err}"
        return result
    
    # Remove from installed registry
    installed = _load_installed()
    if app_id in installed.get("instances", {}):
        del installed["instances"][app_id]
        _save_installed(installed)
    
    # Remove instance data
    if remove_data:
        instance_dir = os.path.join(INSTANCES_DIR, app_id)
        if os.path.exists(instance_dir):
            shutil.rmtree(instance_dir)
    
    result["success"] = True
    result["message"] = f"App {app_id} removed successfully"
    
    return result


def get_app_logs(app_id: str, lines: int = 100) -> Dict[str, Any]:
    """Get logs from an app's LXC container."""
    result = {"success": False, "message": "", "logs": ""}
    
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["message"] = f"App '{app_id}' not found"
        return result
    
    # Try to get logs from inside container
    rc, out, err = _run_pve_cmd([
        "pct", "exec", str(vmid), "--",
        "tail", "-n", str(lines), "/var/log/messages"
    ])
    
    if rc != 0:
        # Try journalctl
        rc, out, err = _run_pve_cmd([
            "pct", "exec", str(vmid), "--",
            "journalctl", "-n", str(lines), "--no-pager"
        ])
    
    if rc == 0:
        result["success"] = True
        result["logs"] = out
    else:
        result["message"] = f"Failed to get logs: {err}"
        result["logs"] = err
    
    return result


# =================================================================
# Network Detection
# =================================================================
def detect_host_networks() -> List[Dict[str, Any]]:
    """Detect available networks on the Proxmox host."""
    networks = []
    
    try:
        # Get bridges from Proxmox
        rc, out, _ = _run_pve_cmd(["pvesh", "get", "/nodes/localhost/network", "--output-format", "json"])
        
        if rc == 0:
            ifaces = json.loads(out)
            for iface in ifaces:
                if iface.get("type") == "bridge":
                    networks.append({
                        "interface": iface.get("iface", ""),
                        "type": "bridge",
                        "address": iface.get("address", ""),
                        "cidr": iface.get("cidr", ""),
                        "recommended": True
                    })
        
    except Exception as e:
        logger.error(f"Failed to detect networks: {e}")
    
    return networks


# =================================================================
# Network Detection
# =================================================================
def detect_networks() -> List[Dict[str, str]]:
    """
    Detect available network interfaces and their subnets.
    Used for suggesting routes to advertise via Tailscale.
    
    Returns:
        List of dicts with interface name and subnet.
    """
    networks = []
    
    try:
        # Use ip command to get interfaces and their addresses
        proc = subprocess.run(
            ["ip", "-j", "addr", "show"],
            capture_output=True,
            text=True
        )
        
        if proc.returncode == 0:
            interfaces = json.loads(proc.stdout)
            
            for iface in interfaces:
                name = iface.get("ifname", "")
                
                # Skip loopback and virtual interfaces
                if name in ("lo", "docker0") or name.startswith(("veth", "br-", "tap", "fwbr", "fwpr")):
                    continue
                
                # Get IPv4 addresses
                for addr_info in iface.get("addr_info", []):
                    if addr_info.get("family") == "inet":
                        ip = addr_info.get("local", "")
                        prefix = addr_info.get("prefixlen", 24)
                        if ip and not ip.startswith("127."):
                            # Calculate network address
                            ip_parts = ip.split(".")
                            if len(ip_parts) == 4:
                                # Simple network calculation
                                if prefix >= 24:
                                    network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/{prefix}"
                                elif prefix >= 16:
                                    network = f"{ip_parts[0]}.{ip_parts[1]}.0.0/{prefix}"
                                else:
                                    network = f"{ip_parts[0]}.0.0.0/{prefix}"
                                networks.append({
                                    "interface": name,
                                    "subnet": network,
                                    "ip": ip
                                })
    except Exception as e:
        logger.error(f"Failed to detect networks: {e}")
    
    return networks


# =================================================================
# Update Auth Key (for Tailscale re-authentication)
# =================================================================
# ─── Update / upgrade subsystem ──────────────────────────────────────────────
#
# Sprint 14.6: the Tailscale gateway lives in a tiny Alpine LXC. Alpine
# itself doesn't ship a lot of moving parts, but the `tailscale` package
# does cut a release every few weeks (CVE fixes, MagicDNS tweaks, derp
# protocol bumps). We expose two operations:
#
#   * `check_app_update_available(app_id)` — readonly probe. Runs
#     `apk update` (refresh package index) followed by
#     `apk version -l '<' tailscale` (ask: is the installed version
#     older than the upstream one?). Returns the current/latest pair.
#     The raw probe takes ~2 seconds inside the CT, so we cache the
#     result for 24 h (per app_id) — the periodic notification poll
#     and the UI re-uses the same cache.
#
#   * `update_app(app_id)` — applies the upgrade. Runs `apk upgrade`
#     so Alpine + tailscale + libs all roll forward together. If the
#     tailscale package itself moved, we restart the service so the
#     new daemon picks up.

_APP_UPDATE_CACHE_TTL = 86400  # 24h — Tailscale ships maybe twice a month
_app_update_cache: Dict[str, Dict[str, Any]] = {}


def _check_running(app_id: str) -> Tuple[bool, Optional[int], str]:
    """Resolve vmid + check the CT is running. Shared prelude for the
    update helpers below — both bail with the same message shape."""
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        return False, None, f"App {app_id} not found or not installed"
    status = get_app_status(app_id)
    if status.get("state") != "running":
        return False, vmid, "Container must be running"
    return True, vmid, ""


def check_app_update_available(app_id: str, force: bool = False) -> Dict[str, Any]:
    """Probe whether the LXC has package updates pending.

    Returns ``{available, current_version, latest_version, packages,
    last_checked_iso, error}``. ``packages`` is the full list of
    upgradable packages so the UI can show a tooltip; ``available`` is
    a convenience boolean that's true whenever ``packages`` is
    non-empty.

    ``force`` bypasses the 24h cache. The notification poll calls with
    ``force=False`` so it doesn't hammer apk; the user clicking
    "re-check" in the UI passes ``force=True``.
    """
    import datetime as _dt

    now = time.time()
    cached = _app_update_cache.get(app_id)
    if not force and cached and now - cached.get("_cached_at", 0) < _APP_UPDATE_CACHE_TTL:
        return cached

    result: Dict[str, Any] = {
        "app_id": app_id,
        "available": False,
        "current_version": None,
        "latest_version": None,
        "packages": [],
        "last_checked_iso": _dt.datetime.utcnow().isoformat() + "Z",
        "error": None,
        "_cached_at": now,
    }

    ok, vmid, msg = _check_running(app_id)
    if not ok:
        result["error"] = msg
        return result

    # Step 1: refresh the apk index. Without this `apk version` checks
    # against whatever was cached at install time and reports stale data.
    rc, _, err = _run_pve_cmd(
        ["pct", "exec", str(vmid), "--", "apk", "update"], timeout=30,
    )
    if rc != 0:
        result["error"] = f"apk update failed: {err.strip()[:200]}"
        return result

    # Step 2: list packages whose installed version is < upstream.
    # `apk version -l '<'` outputs lines like:
    #   tailscale-1.74.0-r1                      < 1.78.3-r0
    rc, out, err = _run_pve_cmd(
        ["pct", "exec", str(vmid), "--", "apk", "version", "-l", "<"],
        timeout=30,
    )
    if rc != 0:
        result["error"] = f"apk version failed: {err.strip()[:200]}"
        return result

    packages: List[Dict[str, str]] = []
    import re as _re
    for line in (out or "").splitlines():
        line = line.strip()
        if not line or line.startswith("Installed:") or "<" not in line:
            continue
        # Split on `<` — left side is the installed pkg, right side is
        # the upstream version string.
        left, _, right = line.partition("<")
        left = left.strip()
        right = right.strip()
        # Left looks like `tailscale-1.74.0-r1` — the package name is
        # everything before the first `-<digit>` chunk.
        m = _re.match(r"^(.+?)-(\d.+)$", left)
        if not m:
            continue
        name = m.group(1)
        current = m.group(2)
        packages.append({"name": name, "current": current, "latest": right})
        if name == "tailscale":
            result["current_version"] = current
            result["latest_version"] = right

    result["packages"] = packages
    result["available"] = bool(packages)

    # Always surface the *installed* tailscale version, even when there
    # is no update pending — the UI uses it for the "Tailscale v… · No
    # updates available" line so the operator sees what's running
    # without scrolling through `pct exec`. Cheap (~50ms) so we run it
    # unconditionally; fail-soft keeps the rest of the result valid if
    # tailscale isn't installed in the CT for some reason.
    #
    # `apk info tailscale` (without -v) prints lines like:
    #   tailscale-1.90.9-r5 description:
    #   ...
    # The version comes off the first whitespace-separated token. We
    # avoid `apk info -v` here because on recent Alpine that flag
    # outputs the description+URL+size, not the version+release.
    if not result["current_version"]:
        try:
            rc_v, out_v, _ = _run_pve_cmd(
                ["pct", "exec", str(vmid), "--", "apk", "info", "tailscale"],
                timeout=10,
            )
            if rc_v == 0:
                for ln in (out_v or "").splitlines():
                    token = ln.strip().split()[0] if ln.strip() else ""
                    m_v = _re.match(r"^tailscale-(\d.+)$", token)
                    if m_v:
                        result["current_version"] = m_v.group(1)
                        break
        except Exception:
            pass

    _app_update_cache[app_id] = result
    return result


def update_app(app_id: str) -> Dict[str, Any]:
    """Run `apk upgrade` inside the LXC and restart the tailscale
    service if its package was updated.

    Returns ``{success, message, packages_updated, tailscale_restarted}``.
    Cache for `check_app_update_available` is invalidated on success
    so the next status read reflects reality.
    """
    result: Dict[str, Any] = {
        "app_id": app_id,
        "success": False,
        "message": "",
        "packages_updated": [],
        "tailscale_restarted": False,
    }

    ok, vmid, msg = _check_running(app_id)
    if not ok:
        result["message"] = msg
        return result

    # Snapshot of what's about to change so we can report back.
    pre = check_app_update_available(app_id, force=True)
    if pre.get("error"):
        result["message"] = pre["error"]
        return result
    pending = pre.get("packages", [])
    if not pending:
        # Even when there's nothing to apply, drop the cached result.
        # The frontend's "is there an update?" check might still be
        # serving an older "available: true" entry from before another
        # process or admin upgraded the CT manually — invalidating
        # ensures the next probe rebuilds from reality.
        _app_update_cache.pop(app_id, None)
        result["success"] = True
        result["message"] = "No updates pending"
        return result

    # Refresh + upgrade in a single shell so transient apk lock issues
    # surface only once. `--no-cache` skips persisting the index — the
    # CT is small, we don't want to bloat it.
    print(f"[*] Running apk upgrade in CT {vmid} for app {app_id}...")
    rc, out, err = _run_pve_cmd(
        ["pct", "exec", str(vmid), "--", "sh", "-c",
         "apk update && apk upgrade --no-cache"],
        timeout=300,  # bigger packages can take a minute or two on slow links
    )
    if rc != 0:
        result["message"] = f"apk upgrade failed: {err.strip()[:300] or out.strip()[:300]}"
        return result

    result["packages_updated"] = pending
    tailscale_changed = any(p["name"] == "tailscale" for p in pending)

    # Restart only when tailscale was the one that moved. Restarting
    # always would force a brief disconnect every cycle even when only
    # libs changed.
    if tailscale_changed:
        rc2, _, err2 = _run_pve_cmd(
            ["pct", "exec", str(vmid), "--", "rc-service", "tailscale", "restart"],
            timeout=60,
        )
        if rc2 == 0:
            result["tailscale_restarted"] = True
        else:
            # Upgrade itself succeeded; service restart didn't. Surface
            # both bits so the UI can show a partial-success banner.
            result["message"] = (
                f"Upgrade applied but tailscale restart failed: "
                f"{err2.strip()[:200]}"
            )

    # Drop the cached availability so the next probe picks up the new
    # state. Don't re-probe synchronously — the user just spent up to a
    # few minutes waiting; the UI can fetch when it's ready.
    _app_update_cache.pop(app_id, None)

    result["success"] = True
    if not result["message"]:
        n = len(pending)
        result["message"] = f"{n} package{'s' if n != 1 else ''} updated"
    return result


def update_auth_key(app_id: str, auth_key: str) -> Dict[str, Any]:
    """Update the Tailscale auth key for a running gateway."""
    result = {"success": False, "message": "", "app_id": app_id}
    
    # Get VMID for the app
    vmid = _get_vmid_for_app(app_id)
    if not vmid:
        result["message"] = f"App {app_id} not found or not installed"
        return result
    
    # Check if container is running
    status = get_app_status(app_id)
    if status.get("state") != "running":
        result["message"] = "Container must be running to update auth key"
        return result
    
    logger.info(f"Updating auth key for {app_id} (VMID: {vmid})")
    print(f"[*] Updating auth key for {app_id}...")
    
    # Run tailscale logout first to clear existing state
    print(f"[*] Logging out of Tailscale...")
    _run_pve_cmd(["pct", "exec", str(vmid), "--", "tailscale", "logout"], timeout=30)
    
    # Wait a moment for logout to complete
    import time
    time.sleep(2)
    
    # Run tailscale up with new auth key
    print(f"[*] Authenticating with new key...")
    
    # Load saved config to get original settings
    config_file = os.path.join(INSTANCES_DIR, app_id, "config.json")
    config = {}
    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                saved_config = json.load(f)
                config = saved_config.get("values", {})
        except:
            pass
    
    # Build tailscale up command
    ts_cmd = ["tailscale", "up", f"--authkey={auth_key}"]
    
    hostname = config.get("hostname")
    if hostname:
        ts_cmd.append(f"--hostname={hostname}")
    
    advertise_routes = config.get("advertise_routes")
    if advertise_routes:
        if isinstance(advertise_routes, list):
            advertise_routes = ",".join(advertise_routes)
        ts_cmd.append(f"--advertise-routes={advertise_routes}")
    
    if config.get("exit_node"):
        ts_cmd.append("--advertise-exit-node")
    
    if config.get("accept_routes"):
        ts_cmd.append("--accept-routes")
    
    rc, out, err = _run_pve_cmd(["pct", "exec", str(vmid), "--"] + ts_cmd, timeout=60)
    
    if rc != 0:
        logger.error(f"Failed to update auth key: {err}")
        result["message"] = f"Failed to authenticate: {err}"
        return result
    
    print(f"[OK] Auth key updated successfully")
    result["success"] = True
    result["message"] = "Auth key updated successfully"
    return result


# =================================================================
# Runtime Detection (for backward compatibility)
# =================================================================
def detect_runtime() -> Dict[str, Any]:
    """Check if Proxmox OCI support is available."""
    pve_info = check_proxmox_version()
    
    return {
        "available": pve_info["oci_support"],
        "runtime": "proxmox-lxc" if pve_info["oci_support"] else None,
        "version": pve_info.get("version"),
        "path": shutil.which("pct"),
        "error": pve_info.get("error")
    }


# =================================================================
# CLI Interface
# =================================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ProxMenux OCI Manager")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy an app")
    deploy_parser.add_argument("--app-id", required=True, help="App ID")
    deploy_parser.add_argument("--config", default="{}", help="JSON config")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Get app status")
    status_parser.add_argument("--app-id", required=True, help="App ID")
    
    # Control commands
    start_parser = subparsers.add_parser("start", help="Start app")
    start_parser.add_argument("--app-id", required=True)
    
    stop_parser = subparsers.add_parser("stop", help="Stop app")
    stop_parser.add_argument("--app-id", required=True)
    
    remove_parser = subparsers.add_parser("remove", help="Remove app")
    remove_parser.add_argument("--app-id", required=True)
    
    # List commands
    subparsers.add_parser("list", help="List available apps")
    subparsers.add_parser("installed", help="List installed apps")
    subparsers.add_parser("runtime", help="Check runtime")
    
    args = parser.parse_args()
    
    if args.command == "deploy":
        config = json.loads(args.config)
        result = deploy_app(args.app_id, config, "cli")
        print(json.dumps(result, indent=2))
    elif args.command == "status":
        print(json.dumps(get_app_status(args.app_id), indent=2))
    elif args.command == "start":
        print(json.dumps(start_app(args.app_id), indent=2))
    elif args.command == "stop":
        print(json.dumps(stop_app(args.app_id), indent=2))
    elif args.command == "remove":
        print(json.dumps(remove_app(args.app_id), indent=2))
    elif args.command == "list":
        print(json.dumps(list_available_apps(), indent=2))
    elif args.command == "installed":
        print(json.dumps(list_installed_apps(), indent=2))
    elif args.command == "runtime":
        print(json.dumps(detect_runtime(), indent=2))
    else:
        parser.print_help()
