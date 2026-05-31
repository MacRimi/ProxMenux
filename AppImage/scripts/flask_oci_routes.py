#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux OCI Routes

REST API endpoints for OCI container app management.
"""

import logging
from flask import Blueprint, jsonify, request

import oci_manager
from jwt_middleware import require_auth

# Logging
logger = logging.getLogger("proxmenux.oci.routes")

# Blueprint
oci_bp = Blueprint("oci", __name__, url_prefix="/api/oci")


# =================================================================
# Catalog Endpoints
# =================================================================

@oci_bp.route("/catalog", methods=["GET"])
@require_auth
def get_catalog():
    """
    List all available apps from the catalog.
    
    Returns:
        List of apps with basic info and installation status.
    """
    try:
        apps = oci_manager.list_available_apps()
        return jsonify({
            "success": True,
            "apps": apps
        })
    except Exception as e:
        logger.error(f"Failed to get catalog: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/catalog/<app_id>", methods=["GET"])
@require_auth
def get_app_definition(app_id: str):
    """
    Get the full definition for a specific app.
    
    Args:
        app_id: The app identifier
    
    Returns:
        Full app definition including config schema.
    """
    try:
        app_def = oci_manager.get_app_definition(app_id)
        
        if not app_def:
            return jsonify({
                "success": False,
                "message": f"App '{app_id}' not found in catalog"
            }), 404
        
        return jsonify({
            "success": True,
            "app": app_def,
            "installed": oci_manager.is_installed(app_id)
        })
    except Exception as e:
        logger.error(f"Failed to get app definition: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/storages", methods=["GET"])
@require_auth
def get_storages():
    """
    Get list of available storages for LXC rootfs.
    
    Returns:
        List of storages with capacity info and recommendations.
    """
    try:
        storages = oci_manager.get_available_storages()
        return jsonify({
            "success": True,
            "storages": storages
        })
    except Exception as e:
        logger.error(f"Failed to get storages: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/catalog/<app_id>/schema", methods=["GET"])
@require_auth
def get_app_schema(app_id: str):
    """
    Get only the config schema for an app.
    
    Args:
        app_id: The app identifier
    
    Returns:
        Config schema for building dynamic forms.
    """
    try:
        app_def = oci_manager.get_app_definition(app_id)
        
        if not app_def:
            return jsonify({
                "success": False,
                "message": f"App '{app_id}' not found in catalog"
            }), 404
        
        return jsonify({
            "success": True,
            "app_id": app_id,
            "name": app_def.get("name", app_id),
            "schema": app_def.get("config_schema", {})
        })
    except Exception as e:
        logger.error(f"Failed to get app schema: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =================================================================
# Installed Apps Endpoints
# =================================================================

@oci_bp.route("/installed", methods=["GET"])
@require_auth
def list_installed():
    """
    List all installed apps with their current status.
    
    Returns:
        List of installed apps with status info.
    """
    try:
        apps = oci_manager.list_installed_apps()
        return jsonify({
            "success": True,
            "instances": apps
        })
    except Exception as e:
        logger.error(f"Failed to list installed apps: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>", methods=["GET"])
@require_auth
def get_installed_app(app_id: str):
    """
    Get details of an installed app including current status.
    
    Args:
        app_id: The app identifier
    
    Returns:
        Installed app details with container info and status.
    """
    try:
        app = oci_manager.get_installed_app(app_id)
        
        if not app:
            return jsonify({
                "success": False,
                "message": f"App '{app_id}' is not installed"
            }), 404
        
        return jsonify({
            "success": True,
            "instance": app
        })
    except Exception as e:
        logger.error(f"Failed to get installed app: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>/logs", methods=["GET"])
@require_auth
def get_app_logs(app_id: str):
    """
    Get recent logs from an app's container.
    
    Args:
        app_id: The app identifier
    
    Query params:
        lines: Number of lines to return (default 100)
    
    Returns:
        Container logs.
    """
    try:
        lines = request.args.get("lines", 100, type=int)
        result = oci_manager.get_app_logs(app_id, lines=lines)
        
        if not result.get("success"):
            return jsonify(result), 404 if "not installed" in result.get("message", "") else 500
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to get app logs: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =================================================================
# Deployment Endpoint
# =================================================================

@oci_bp.route("/deploy", methods=["POST"])
@require_auth
def deploy_app():
    """
    Deploy an OCI app with the given configuration.
    
    Body:
        {
            "app_id": "secure-gateway",
            "config": {
                "auth_key": "tskey-auth-xxx",
                "hostname": "proxmox-gateway",
                ...
            }
        }
    
    Returns:
        Deployment result with container ID if successful.
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "success": False,
                "message": "Request body is required"
            }), 400
        
        app_id = data.get("app_id")
        config = data.get("config", {})
        
        if not app_id:
            return jsonify({
                "success": False,
                "message": "app_id is required"
            }), 400
        
        logger.info(f"Deploy request: app_id={app_id}, config_keys={list(config.keys())}")
        
        result = oci_manager.deploy_app(app_id, config, installed_by="web")
        
        logger.info(f"Deploy result: {result}")
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Failed to deploy app: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =================================================================
# Lifecycle Action Endpoints
# =================================================================

@oci_bp.route("/installed/<app_id>/start", methods=["POST"])
@require_auth
def start_app(app_id: str):
    """Start an installed app's container."""
    try:
        result = oci_manager.start_app(app_id)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to start app: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>/stop", methods=["POST"])
@require_auth
def stop_app(app_id: str):
    """Stop an installed app's container."""
    try:
        result = oci_manager.stop_app(app_id)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to stop app: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>/restart", methods=["POST"])
@require_auth
def restart_app(app_id: str):
    """Restart an installed app's container."""
    try:
        result = oci_manager.restart_app(app_id)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to restart app: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>", methods=["DELETE"])
@require_auth
def remove_app(app_id: str):
    """
    Remove an installed app.
    
    Query params:
        remove_data: If true, also remove persistent data (default false)
    """
    try:
        remove_data = request.args.get("remove_data", "false").lower() == "true"
        result = oci_manager.remove_app(app_id, remove_data=remove_data)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to remove app: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =================================================================
# Configuration Update Endpoint
# =================================================================

@oci_bp.route("/installed/<app_id>/config", methods=["PUT"])
@require_auth
def update_app_config(app_id: str):
    """
    Update an app's configuration and recreate the container.
    
    Body:
        {
            "config": { ... new config values ... }
        }
    """
    try:
        data = request.get_json()
        
        if not data or "config" not in data:
            return jsonify({
                "success": False,
                "message": "config is required in request body"
            }), 400
        
        result = oci_manager.update_app_config(app_id, data["config"])
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Failed to update app config: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =================================================================
# Utility Endpoints
# =================================================================

@oci_bp.route("/networks", methods=["GET"])
@require_auth
def get_networks():
    """
    Get available networks for VPN routing.
    
    Returns:
        List of detected network interfaces with their subnets.
    """
    try:
        networks = oci_manager.detect_networks()
        return jsonify({
            "success": True,
            "networks": networks
        })
    except Exception as e:
        logger.error(f"Failed to detect networks: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/runtime", methods=["GET"])
@require_auth
def get_runtime():
    """
    Get container runtime information.
    
    Returns:
        Runtime type (podman/docker), version, and availability.
    """
    try:
        runtime_info = oci_manager.detect_runtime()
        return jsonify({
            "success": True,
            **runtime_info
        })
    except Exception as e:
        logger.error(f"Failed to detect runtime: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/runtime/install-script", methods=["GET"])
@require_auth
def get_runtime_install_script():
    """
    Get the path to the runtime installation script.
    
    Returns:
        Script path for installing Podman.
    """
    import os
    
    # Check possible paths for the install script
    possible_paths = [
        "/usr/local/share/proxmenux/scripts/oci/install_runtime.sh",
        os.path.join(os.path.dirname(__file__), "..", "..", "Scripts", "oci", "install_runtime.sh"),
    ]
    
    for script_path in possible_paths:
        if os.path.exists(script_path):
            return jsonify({
                "success": True,
                "script_path": os.path.abspath(script_path)
            })
    
    return jsonify({
        "success": False,
        "message": "Runtime installation script not found"
    }), 404


@oci_bp.route("/status/<app_id>", methods=["GET"])
@require_auth
def get_app_status(app_id: str):
    """
    Get the current status of an app's container.
    
    Returns:
        Container state, health, and uptime.
    """
    try:
        status = oci_manager.get_app_status(app_id)
        return jsonify({
            "success": True,
            "app_id": app_id,
            "status": status
        })
    except Exception as e:
        logger.error(f"Failed to get app status: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>/update-auth-key", methods=["POST"])
@require_auth
def update_auth_key(app_id: str):
    """
    Update the Tailscale auth key for an installed gateway.
    
    This is useful when the auth key expires and the gateway needs to re-authenticate.
    
    Body:
        {
            "auth_key": "tskey-auth-xxx"
        }
    
    Returns:
        Success status and message.
    """
    try:
        data = request.get_json()
        
        if not data or "auth_key" not in data:
            return jsonify({
                "success": False,
                "message": "auth_key is required in request body"
            }), 400
        
        auth_key = data["auth_key"]
        
        if not auth_key.startswith("tskey-"):
            return jsonify({
                "success": False,
                "message": "Invalid auth key format. Should start with 'tskey-'"
            }), 400
        
        result = oci_manager.update_auth_key(app_id, auth_key)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Failed to update auth key: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@oci_bp.route("/installed/<app_id>/update-check", methods=["GET"])
@require_auth
def installed_update_check(app_id: str):
    """Check whether the LXC behind ``app_id`` has package updates
    pending. Cached 24h server-side; pass ``?force=1`` to bypass.

    The frontend renders the result as either an inline "Last checked:
    HH:MM · No updates available" string or, when ``available`` is
    true, the prominent purple "Update to vX.Y.Z" button.
    """
    try:
        force = request.args.get("force", "").lower() in ("1", "true", "yes")
        result = oci_manager.check_app_update_available(app_id, force=force)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Failed to check app update for {app_id}: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@oci_bp.route("/installed/<app_id>/update", methods=["POST"])
@require_auth
def installed_update_apply(app_id: str):
    """Run `apk upgrade` inside the LXC. Restarts tailscale only if
    its package was actually upgraded — restarting on every cycle
    would cause an unnecessary brief disconnect."""
    try:
        result = oci_manager.update_app(app_id)
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to apply update for {app_id}: {e}")
        return jsonify({
            "success": False,
            "message": str(e),
            "app_id": app_id,
        }), 500
