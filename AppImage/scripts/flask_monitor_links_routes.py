"""Links between ProxMenux Monitors for the node selector in the header."""

from flask import Blueprint, jsonify, request
import monitor_links
from jwt_middleware import require_auth, require_admin_scope

monitor_links_bp = Blueprint("monitor_links", __name__)


def link_error(exc):
    payload = {"error": str(exc), "code": exc.code}
    if exc.params:
        payload["params"] = exc.params
    return jsonify(payload), 400


@monitor_links_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@monitor_links_bp.route("/api/monitor-links")
@require_auth
def list_links():
    return jsonify(monitor_links.cached_links(include_hidden=request.args.get("all") == "1"))


@monitor_links_bp.route("/api/monitor-links", methods=["POST"])
@require_admin_scope
def add_link():
    try:
        key = monitor_links.add_link(request.get_json(silent=True))
        monitor_links.refresh()
        return jsonify(success=True, key=key)
    except monitor_links.LinkError as exc:
        return link_error(exc)
    except OSError:
        return jsonify(error="Could not save the node list.", code="monitor_links_save_failed"), 500


@monitor_links_bp.route("/api/monitor-links/<path:key>", methods=["PATCH"])
@require_admin_scope
def update_link(key):
    try:
        monitor_links.update_link(key, request.get_json(silent=True))
        monitor_links.refresh()
        return jsonify(success=True)
    except monitor_links.LinkError as exc:
        return link_error(exc)
    except OSError:
        return jsonify(error="Could not save the node list.", code="monitor_links_save_failed"), 500


@monitor_links_bp.route("/api/monitor-links/<path:key>", methods=["DELETE"])
@require_admin_scope
def delete_link(key):
    try:
        monitor_links.delete_link(key)
        monitor_links.refresh()
        return jsonify(success=True)
    except monitor_links.LinkError as exc:
        return link_error(exc)
    except OSError:
        return jsonify(error="Could not save the node list.", code="monitor_links_save_failed"), 500
