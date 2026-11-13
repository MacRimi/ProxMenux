"""OIDC authorization-code login with PKCE and explicit administrator subjects.

Provider tokens never become Monitor API tokens. A verified, allowed subject is
mapped to the existing local administrator; its password/2FA remains available.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit, quote_plus

import jwt
import requests
import auth_manager

ALGORITHMS = ("RS256", "ES256")
FLOW_TTL = 300
EXCHANGE_TTL = 30
COOKIE = "proxmenux_oidc_flow"
_lock = threading.RLock()
_flows = {}
_exchanges = {}
_documents = {}


class OIDCError(ValueError):
    pass


def available():
    return all(alg in jwt.algorithms.get_default_algorithms() for alg in ALGORITHMS)


def _config_path():
    return auth_manager.CONFIG_DIR / "oidc.json"


def load_config():
    try:
        with _config_path().open() as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _url(value, *, origin=False):
    if not isinstance(value, str) or len(value) > 2048:
        raise OIDCError("Enter a valid HTTPS URL.")
    try:
        parts = urlsplit(value)
        parts.port
    except ValueError as exc:
        raise OIDCError("Invalid URL.") from exc
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.fragment or (origin and parts.query)):
        raise OIDCError("Use HTTPS URLs without credentials or fragments.")
    return value


def public_config():
    config = load_config()
    return {**{key: config.get(key, default) for key, default in (
        ("enabled", False), ("provider_name", "OpenID Connect"),
        ("issuer", ""), ("client_id", ""), ("public_url", ""),
        ("allowed_subjects", []), ("token_auth_method", "client_secret_basic"),
    )}, "has_client_secret": bool(config.get("client_secret")), "available": available()}


def _request_json(method, url, **kwargs):
    try:
        response = requests.request(method, _url(url), timeout=10, allow_redirects=False, **kwargs)
        if response.status_code != 200 or len(response.content) > 1024 * 1024:
            raise OIDCError("The identity provider returned an invalid response.")
        document = response.json()
        if not isinstance(document, dict):
            raise OIDCError("The identity provider returned an invalid document.")
        return document
    except (requests.RequestException, ValueError) as exc:
        # Do not reflect token responses, credentials or provider error bodies.
        raise OIDCError("Could not contact or validate the identity provider.") from exc


def _document(url, *, refresh=False):
    with _lock:
        cached = _documents.get(url)
        if not refresh and cached and cached[0] > time.monotonic():
            return cached[1]
    data = _request_json("GET", url)
    with _lock:
        if len(_documents) >= 16:
            _documents.clear()
        _documents[url] = (time.monotonic() + 300, data)
    return data


def discovery(config, *, refresh=False):
    issuer = _url(config["issuer"], origin=True)
    data = _document(issuer.rstrip("/") + "/.well-known/openid-configuration", refresh=refresh)
    if data.get("issuer") != issuer:
        raise OIDCError("Discovery issuer does not exactly match the configured issuer.")
    for endpoint in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        _url(data.get(endpoint))
    if "code" not in data.get("response_types_supported", []):
        raise OIDCError("The provider must support the authorization code flow.")
    methods = data.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise OIDCError("The provider must support S256 PKCE.")
    if not set(data.get("id_token_signing_alg_values_supported", ["RS256"])) & set(ALGORITHMS):
        raise OIDCError("The provider must support RS256 or ES256 ID tokens.")
    if config["token_auth_method"] not in data.get(
            "token_endpoint_auth_methods_supported", ["client_secret_basic"]):
        raise OIDCError("The selected client authentication method is not supported by the provider.")
    return data


def save_config(data):
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
        raise OIDCError("An enabled flag is required.")
    previous = load_config()
    config = {key: data.get(key, previous.get(key, default)) for key, default in (
        ("provider_name", "OpenID Connect"), ("issuer", ""), ("client_id", ""),
        ("public_url", ""), ("allowed_subjects", []), ("client_secret", ""),
        ("token_auth_method", "client_secret_basic"),
    )}
    config["enabled"] = data["enabled"]
    config["revision"] = secrets.token_hex(16)
    for field in ("provider_name", "client_id", "client_secret", "issuer", "public_url"):
        value = config[field]
        if not isinstance(value, str) or len(value) > (4096 if field == "client_secret" else 2048):
            raise OIDCError("Invalid provider name, URL or client credentials.")
    for field in ("issuer", "public_url"):
        if config[field]:
            config[field] = _url(config[field], origin=True)
    config["public_url"] = config["public_url"].rstrip("/")
    subjects = config["allowed_subjects"]
    if (not isinstance(subjects, list) or len(subjects) > 128
            or any(not isinstance(s, str) or not s.strip() or len(s) > 256 for s in subjects)):
        raise OIDCError("Specify allowed immutable subjects (sub), one per line.")
    config["allowed_subjects"] = list(dict.fromkeys(s.strip() for s in subjects))
    if config["token_auth_method"] not in ("client_secret_basic", "client_secret_post", "none"):
        raise OIDCError("Invalid client authentication method.")
    if config["token_auth_method"] == "none":
        config["client_secret"] = ""
    if config["enabled"]:
        if not available():
            raise OIDCError("OIDC requires the Monitor build with its cryptography runtime.")
        if not config["client_id"].strip() or not config["provider_name"].strip():
            raise OIDCError("Provider name and client ID are required.")
        if not config["issuer"] or not config["public_url"]:
            raise OIDCError("Issuer and public dashboard HTTPS URLs are required.")
        if not subjects:
            raise OIDCError("Specify at least one allowed immutable subject (sub), one per line.")
        if config["token_auth_method"] != "none" and not config["client_secret"]:
            raise OIDCError("A client secret is required for this authentication method.")
        discovery(config, refresh=True)
    auth_manager.ensure_config_dir()
    descriptor, staging = tempfile.mkstemp(prefix=".oidc-", dir=auth_manager.CONFIG_DIR)
    try:
        with os.fdopen(descriptor, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(config, handle, indent=2)
        os.replace(staging, _config_path())
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
    with _lock:
        _flows.clear()
        _exchanges.clear()
    return public_config()


def enabled_config():
    local = auth_manager.load_auth_config()
    config = load_config()
    if (not local.get("enabled") or local.get("declined") or not local.get("password_hash")
            or not config.get("enabled") or not available()):
        raise OIDCError("OpenID Connect is not enabled.")
    return config


def is_current_session(subject, revision):
    try:
        config = enabled_config()
        return revision == config.get("revision") and subject in config.get("allowed_subjects", [])
    except OIDCError:
        return False


def _prune():
    now = time.monotonic()
    for cache in (_flows, _exchanges):
        for key in list(cache):
            if cache[key]["expires"] <= now:
                del cache[key]


def begin_login():
    config = enabled_config()
    metadata = discovery(config)
    state, binding, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with _lock:
        _prune()
        if len(_flows) >= 1024:
            raise OIDCError("Too many sign-in requests. Try again later.")
        _flows[state] = {"binding": binding, "nonce": nonce, "verifier": verifier,
                         "revision": config["revision"], "expires": time.monotonic() + FLOW_TTL}
    parameters = urlencode({
        "client_id": config["client_id"], "redirect_uri": config["public_url"] + "/api/auth/oidc/callback",
        "response_type": "code", "scope": "openid profile", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    endpoint = metadata["authorization_endpoint"]
    return endpoint + ("&" if "?" in endpoint else "?") + parameters, binding


def _verify_id_token(encoded, config, metadata, nonce):
    if not isinstance(encoded, str) or len(encoded) > 65536:
        raise OIDCError("The provider did not return a valid ID token.")
    try:
        header = jwt.get_unverified_header(encoded)
        algorithm, kid = header.get("alg"), header.get("kid")
        if algorithm not in ALGORITHMS or not isinstance(kid, str) or not 1 <= len(kid) <= 256:
            raise OIDCError("Unsupported ID token signing algorithm or key.")
        for refresh in (False, True):
            keys = _document(metadata["jwks_uri"], refresh=refresh).get("keys", [])
            candidates = [key for key in keys if isinstance(key, dict)
                          and key.get("kid") == kid and key.get("use", "sig") == "sig"
                          and key.get("alg", algorithm) == algorithm]
            if len(candidates) == 1:
                break
        if len(candidates) != 1:
            raise OIDCError("No unique signing key was found for the ID token.")
        key = jwt.PyJWK.from_dict(candidates[0], algorithm=algorithm)
        claims = jwt.decode(encoded, key.key, algorithms=list(ALGORITHMS),
                            audience=config["client_id"], issuer=config["issuer"], leeway=30,
                            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]})
        if (claims.get("azp", config["client_id"]) != config["client_id"]
                or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and "azp" not in claims)):
            raise OIDCError("Invalid authorized party in ID token.")
        if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise OIDCError("The ID token nonce does not match this sign-in.")
        if claims["sub"] not in config["allowed_subjects"]:
            raise OIDCError("This provider account is not authorized for Monitor.")
        return claims["sub"]
    except (jwt.PyJWTError, TypeError, KeyError, AttributeError) as exc:
        raise OIDCError("The ID token could not be verified.") from exc


def finish_login(state, binding, code):
    if not all(isinstance(value, str) and value.isascii() and 0 < len(value) <= 4096 for value in (state, binding, code)):
        raise OIDCError("Missing or invalid sign-in response.")
    config = enabled_config()
    with _lock:
        _prune()
        flow = _flows.get(state)
        if not flow or not hmac.compare_digest(flow["binding"], binding):
            raise OIDCError("The sign-in has expired or belongs to another browser.")
        del _flows[state]  # A callback can only be attempted once, including failures.
    if flow["revision"] != config["revision"]:
        raise OIDCError("OIDC configuration changed. Start sign-in again.")
    metadata = discovery(config)
    data = {"grant_type": "authorization_code", "code": code,
            "redirect_uri": config["public_url"] + "/api/auth/oidc/callback",
            "code_verifier": flow["verifier"]}
    options = {}
    if config["token_auth_method"] == "client_secret_basic":
        options["auth"] = (quote_plus(config["client_id"], safe=""), quote_plus(config["client_secret"], safe=""))
    else:
        data["client_id"] = config["client_id"]
        if config["token_auth_method"] == "client_secret_post":
            data["client_secret"] = config["client_secret"]
    response = _request_json("POST", metadata["token_endpoint"], data=data, **options)
    subject = _verify_id_token(response.get("id_token"), config, metadata, flow["nonce"])
    token = auth_manager.generate_token(auth_manager.load_auth_config()["username"],
                                        oidc_identity={"sub": subject, "revision": config["revision"]})
    if not token:
        raise OIDCError("Could not create a Monitor session.")
    ticket = secrets.token_urlsafe(32)
    with _lock:
        _prune()
        if len(_exchanges) >= 1024:
            raise OIDCError("Too many sign-in requests. Try again later.")
        _exchanges[ticket] = {"binding": binding, "token": token,
                              "expires": time.monotonic() + EXCHANGE_TTL}
    return config["public_url"] + "/#oidc_code=" + ticket


def exchange(ticket, binding):
    if not isinstance(ticket, str) or not isinstance(binding, str) or not binding.isascii():
        raise OIDCError("Missing sign-in exchange.")
    with _lock:
        _prune()
        session = _exchanges.get(ticket)
        if not session or not hmac.compare_digest(session["binding"], binding):
            raise OIDCError("The sign-in exchange has expired or belongs to another browser.")
        del _exchanges[ticket]
    if not auth_manager.verify_token(session["token"]):
        raise OIDCError("The sign-in session is no longer authorized.")
    return session["token"]
