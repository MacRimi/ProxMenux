"""Read-only PBS status and administrative connection management."""

from flask import Blueprint, jsonify, request
import auth_manager
import pbs_manager as pbs
from jwt_middleware import require_auth, require_admin_scope

pbs_bp = Blueprint("pbs", __name__)


@pbs_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@pbs_bp.route("/api/platform")
@require_auth
def platform():
    return jsonify(pbs.get_platform())


@pbs_bp.route("/api/pbs/servers")
@require_auth
def servers():
    try:
        return jsonify(servers=pbs.public_servers(), local_available=pbs.is_pbs_host())
    except pbs.PBSError as exc:
        return jsonify(error=str(exc)), 500


def _protected_configuration():
    local = auth_manager.load_auth_config()
    return local.get("enabled") and not local.get("declined") and local.get("password_hash")


@pbs_bp.route("/api/pbs/servers", methods=["POST"])
@require_admin_scope
def save_server():
    if not _protected_configuration():
        return jsonify(error="Enable local authentication before saving remote PBS credentials."), 409
    try:
        identifier = pbs.save_server(request.get_json(silent=True))
        return jsonify(success=True, id=identifier, servers=pbs.public_servers())
    except pbs.PBSError as exc:
        return jsonify(error=str(exc)), 400
    except OSError:
        return jsonify(error="Could not save PBS connection."), 500


@pbs_bp.route("/api/pbs/servers/<identifier>", methods=["DELETE"])
@require_admin_scope
def delete_server(identifier):
    if not _protected_configuration():
        return jsonify(error="Enable local authentication before changing PBS connections."), 409
    try:
        pbs.delete_server(identifier)
        return jsonify(success=True)
    except pbs.PBSError as exc:
        return jsonify(error=str(exc)), 400
    except OSError:
        return jsonify(error="Could not remove PBS connection."), 500


@pbs_bp.route("/api/pbs/status")
@require_auth
def status():
    try:
        return jsonify(pbs.get_status(request.args.get("server", "local")))
    except pbs.PBSError as exc:
        return jsonify(error=str(exc)), 502
