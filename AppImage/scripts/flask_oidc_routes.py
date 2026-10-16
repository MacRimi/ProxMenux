"""OIDC configuration and browser login endpoints."""

import logging
import os
from flask import Blueprint, jsonify, request, redirect
import auth_manager
import oidc_manager as oidc
from jwt_middleware import require_admin_scope

oidc_bp = Blueprint("oidc", __name__)


def _client_ip():
    peer = request.remote_addr or "unknown"
    if os.environ.get("PROXMENUX_TRUST_PROXY", "0") == "1":
        peer = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or request.headers.get("X-Real-IP", "").strip() or peer)
    return peer


def _private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@oidc_bp.route("/api/auth/oidc/status")
def status():
    try:
        config = oidc.enabled_config()
        return _private(jsonify(enabled=True, provider_name=config["provider_name"],
                                login_url=config["public_url"] + "/api/auth/oidc/start"))
    except oidc.OIDCError:
        return _private(jsonify(enabled=False))


@oidc_bp.route("/api/auth/oidc/config", methods=["GET", "PUT"])
@require_admin_scope
def configuration():
    local = auth_manager.load_auth_config()
    if not local.get("enabled") or not local.get("password_hash") or local.get("declined"):
        return jsonify(error="Configure and enable local password authentication first."), 409
    try:
        data = oidc.save_config(request.get_json(silent=True)) if request.method == "PUT" else oidc.public_config()
        return _private(jsonify(success=True, **data))
    except oidc.OIDCError as exc:
        return _private(jsonify(error=str(exc))), 400
    except OSError:
        return _private(jsonify(error="Could not save OIDC configuration.")), 500


@oidc_bp.route("/api/auth/oidc/start")
def start():
    try:
        location, binding = oidc.begin_login()
        response = redirect(location, code=302)
        response.set_cookie(oidc.COOKIE, binding, max_age=oidc.FLOW_TTL,
                            secure=True, httponly=True, samesite="Lax", path="/")
        return _private(response)
    except oidc.OIDCError as exc:
        return _private(jsonify(error=str(exc))), 400


@oidc_bp.route("/api/auth/oidc/callback")
def callback():
    try:
        if request.args.get("error"):
            raise oidc.OIDCError("Provider declined sign-in.")
        location = oidc.finish_login(request.args.get("state"), request.cookies.get(oidc.COOKIE),
                                     request.args.get("code"))
        return _private(redirect(location, code=303))
    except oidc.OIDCError:
        logging.getLogger("proxmenux-auth").warning(
            "OIDC authentication failure; rhost=%s", _client_ip())
        config = oidc.load_config()
        response = redirect(config["public_url"] + "/#oidc_error=login_failed", code=303) if config.get("public_url") else jsonify(error="OIDC sign-in failed.")
        response.delete_cookie(oidc.COOKIE, secure=True, httponly=True, samesite="Lax", path="/")
        return _private(response)


@oidc_bp.route("/api/auth/oidc/exchange", methods=["POST"])
def exchange():
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise oidc.OIDCError("Invalid sign-in exchange.")
        token = oidc.exchange(data.get("code"), request.cookies.get(oidc.COOKIE))
        response = jsonify(success=True, token=token)
        response.delete_cookie(oidc.COOKIE, secure=True, httponly=True, samesite="Lax", path="/")
        return _private(response)
    except oidc.OIDCError as exc:
        return _private(jsonify(error=str(exc))), 401
