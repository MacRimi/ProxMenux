#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux Audit Routes
Flask blueprint for the Audit & Report assessment engine.

An assessment reads the host and records findings; it never modifies
anything. The run endpoint is therefore the only POST that does real
work, and it is deliberately serialised: two concurrent assessments would
compete for the same collectors without producing a better answer.
"""

import threading
import time

from flask import Blueprint, jsonify, request
from jwt_middleware import require_auth, require_admin_scope
from auth_manager import verify_token, load_auth_config

audit_bp = Blueprint('audit', __name__)

try:
    import audit_store
    import audit_checks
    import audit_checks_pve  # noqa: F401 — importing registers the checks
    import audit_inventory
    import audit_profiles
    import audit_policy
    import changes_journal
except ImportError:
    audit_store = None
    audit_checks = None
    audit_inventory = None
    audit_profiles = None
    audit_policy = None
    changes_journal = None

# One assessment at a time. The flag is also what the interface polls to
# know a run is still in progress.
_run_lock = threading.Lock()
_running: dict = {'active': False, 'run_id': None, 'started_at': 0}
_startup_error = None


def _actor():
    config = load_auth_config()
    if not config.get('enabled') or config.get('declined'):
        return 'local-admin (authentication disabled)'
    parts = request.headers.get('Authorization', '').split()
    return verify_token(parts[1]) if len(parts) == 2 else 'unknown'


def _progress(run_id, completed, total, check_id):
    _running.update(run_id=run_id, completed=completed, total=total, check_id=check_id)


@audit_bp.record_once
def _on_register(state):
    global _startup_error
    if audit_store:
        try:
            audit_store.recover_interrupted_runs()
        except Exception as exc:
            # An audit DB problem must never prevent the Monitor starting.
            _startup_error = str(exc)
            print(f"[audit] persistence unavailable: {exc}")


def _unavailable():
    return jsonify({
        "success": False,
        "message": "Audit engine not available",
    }), 500


@audit_bp.route('/api/audit/checks', methods=['GET'])
@require_auth
def list_checks():
    """Catalogue of registered checks, independent of any run."""
    if not audit_checks:
        return _unavailable()
    try:
        return jsonify({
            "success": True,
            "areas": list(audit_checks.AREAS),
            "checks": [
                {
                    "check_id": c.check_id,
                    "area": c.area,
                    "severity": c.severity,
                }
                for c in audit_checks.registered_checks()
            ],
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/status', methods=['GET'])
@require_auth
def status():
    """Latest run, whether an assessment is in progress, and the baseline."""
    if not audit_store or _startup_error:
        return _unavailable()
    try:
        latest = audit_store.latest_run()
        summary = {}
        if latest:
            for f in audit_store.effective_findings(latest['run_id']):
                # An accepted finding is counted as a decision, not as the
                # problem it still technically is, so the counters and the
                # list a reader sees agree with each other.
                key = (f.get('decision') or f['classification'])
                summary[key] = summary.get(key, 0) + 1
        return jsonify({
            "success": True,
            "running": _running['active'],
            "progress": {k: _running.get(k) for k in ('run_id', 'completed', 'total', 'check_id')},
            "latest": latest,
            "summary": summary,
            "baseline": audit_store.get_baseline(),
            "exceptions": len(audit_store.active_exceptions()),
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/run', methods=['POST'])
@require_admin_scope
def run():
    """Start an assessment in the background.

    The response returns immediately with the run identifier; the
    interface polls ``/api/audit/status``. A full assessment is short but
    runs against a production host, so it must not hold an HTTP worker.
    """
    if not audit_checks or _startup_error:
        return _unavailable()

    data = request.get_json(silent=True) or {}
    profile = str(data.get('profile') or 'full')
    areas = data.get('areas')
    if (not audit_profiles.is_known(profile) or (areas is not None and
            (not isinstance(areas, list) or not areas or
             any(not isinstance(a, str) or a not in audit_checks.AREAS for a in areas)))):
        return jsonify(success=False, message="Unsupported audit profile or areas"), 400
    only = set(areas) if areas is not None else None

    with _run_lock:
        if _running['active']:
            return jsonify({
                "success": False,
                "message": "An assessment is already running",
                "run_id": _running['run_id'],
            }), 409
        run_id = audit_store.start_run(profile)
        _running.update({'active': True, 'run_id': run_id,
                         'started_at': time.time(), 'completed': 0, 'total': 0, 'check_id': None})

    def worker():
        try:
            audit_checks.run_assessment(profile, only_areas=only, run_id=run_id, progress=_progress)
            audit_store.prune_runs()
        except Exception as e:
            audit_store.finish_run(run_id, checks_total=_running.get('completed', 0), error=str(e))
            print(f"[audit] assessment failed: {e}")
        finally:
            _running['active'] = False

    try:
        threading.Thread(target=worker, daemon=True, name='audit-run').start()
    except Exception as e:
        _running['active'] = False
        audit_store.finish_run(run_id, checks_total=0, error=str(e))
        return jsonify(success=False, message="Unable to start assessment"), 500
    return jsonify({"success": True, "started": True, "run_id": run_id})


@audit_bp.route('/api/audit/runs', methods=['GET'])
@require_auth
def runs():
    if not audit_store:
        return _unavailable()
    try:
        limit = min(int(request.args.get('limit', 20)), 100)
        return jsonify({"success": True, "runs": audit_store.list_runs(limit)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/runs/<run_id>', methods=['GET'])
@require_auth
def run_detail(run_id):
    """Findings of one run, with the accepted-risk record attached.

    Accepted findings are returned like any other so the interface can
    show them muted rather than dropping them: hiding an accepted risk
    turns the register into a way of forgetting decisions.
    """
    if not audit_store:
        return _unavailable()
    try:
        run = audit_store.get_run(run_id)
        if not run:
            return jsonify({"success": False, "message": "Run not found"}), 404
        # History is immutable by default. The live view explicitly asks
        # for current decisions, so acceptance/revocation needs no scan.
        findings = (audit_store.effective_findings(run_id) if request.args.get('effective') == '1'
                    else audit_store.get_findings(run_id))
        return jsonify({"success": True, "run": run, "findings": findings})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/compare', methods=['GET'])
@require_auth
def compare():
    """Difference between two runs, defaulting the base to the baseline."""
    if not audit_store:
        return _unavailable()
    try:
        other = request.args.get('to')
        base = request.args.get('from')
        if not base:
            baseline = audit_store.get_baseline()
            base = baseline['run_id'] if baseline else None
        if not other:
            latest = audit_store.latest_run()
            other = latest['run_id'] if latest else None
        if not base or not other:
            return jsonify({
                "success": False,
                "reason": "insufficient_runs",
                "message": "Two runs are required to compare",
            }), 400
        return jsonify({
            "success": True,
            "from": base,
            "to": other,
            **audit_checks.compare_runs(base, other),
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/baseline', methods=['POST'])
@require_admin_scope
def set_baseline():
    if not audit_store:
        return _unavailable()
    try:
        data = request.get_json(silent=True) or {}
        run_id = data.get('run_id')
        if not run_id or not audit_store.get_run(run_id):
            return jsonify({"success": False, "message": "Run not found"}), 404
        audit_store.set_baseline(run_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/exceptions', methods=['GET'])
@require_auth
def list_exceptions():
    if not audit_store:
        return _unavailable()
    try:
        return jsonify({
            "success": True,
            "exceptions": audit_store.all_exceptions(),
            "history": audit_store.exception_history(),
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/exceptions', methods=['POST'])
@require_admin_scope
def accept_exception():
    """Record a finding as a deliberate decision.

    The reason is mandatory. An acceptance without one cannot be
    distinguished later from having silenced the check, which is the
    outcome this register exists to prevent.
    """
    if not audit_store:
        return _unavailable()
    try:
        data = request.get_json(silent=True) or {}
        check_id = (data.get('check_id') or '').strip()
        reason = (data.get('reason') or '').strip()
        if not check_id:
            return jsonify({"success": False,
                            "message": "check_id is required"}), 400
        if not reason:
            return jsonify({"success": False,
                            "message": "A reason is required"}), 400
        latest = audit_store.latest_run()
        if not latest or data.get('run_id') != latest['run_id']:
            return jsonify(success=False, message="Reload the latest assessment before accepting a risk"), 409
        finding = next((f for f in audit_store.get_findings(latest['run_id']) if f['check_id'] == check_id), None)
        if (not finding or finding.get('raw_classification') not in audit_store.CLASS_PROBLEMS or
                finding.get('incomplete') or not finding.get('scope')):
            return jsonify(success=False, message="This finding cannot be accepted"), 400

        expires_at = None
        days = data.get('expires_in_days')
        if days is not None:
            try:
                if isinstance(days, bool) or int(days) != float(days) or not 1 <= int(days) <= 3650:
                    raise ValueError("invalid expiry")
                expires_at = int(time.time()) + int(days) * 86400
            except (TypeError, ValueError):
                return jsonify({"success": False,
                                "message": "Invalid expiry"}), 400

        audit_store.accept_risk(
            check_id, reason,
            accepted_by=_actor(),
            expires_at=expires_at,
            scope=finding['scope'],
        )
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/exceptions/<path:check_id>', methods=['DELETE'])
@require_admin_scope
def revoke_exception(check_id):
    if not audit_store:
        return _unavailable()
    try:
        removed = audit_store.revoke_risk(check_id, _actor())
        if not removed:
            return jsonify({"success": False,
                            "message": "Exception not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/inventory', methods=['GET'])
@require_auth
def inventory():
    """Structural inventory of the node.

    Composed from collectors the Monitor already runs; the assessment and
    the inventory answer different questions and neither depends on the
    other, so this endpoint does not require a run to exist.
    """
    if not audit_inventory:
        return _unavailable()
    try:
        profile = request.args.get('profile') or audit_profiles.DEFAULT_PROFILE
        if not audit_profiles.is_known(profile):
            return jsonify(success=False, message="Unsupported report profile"), 400
        ctx = audit_checks.AuditContext()
        ctx.begin_check()
        inventory = audit_inventory.collect(ctx, sections=audit_profiles.sections(profile))
        return jsonify({"success": True, "profile": profile, "inventory": inventory})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/profiles', methods=['GET'])
@require_auth
def profiles():
    """Report profiles this build offers, without touching the host."""
    if not audit_profiles:
        return _unavailable()
    try:
        return jsonify({"success": True, "default": audit_profiles.DEFAULT_PROFILE,
                        "profiles": audit_profiles.describe()})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/policy', methods=['GET'])
@require_auth
def policy():
    """The declaration, and what a declaration can say.

    The vocabulary travels with the declaration so the interface offers
    exactly the expectations and thresholds this build understands,
    rather than a list written twice and drifting apart.
    """
    if not audit_policy:
        return _unavailable()
    try:
        current = audit_policy.load()
        if current.error:
            return jsonify(success=False, message=current.error), 422
        return jsonify({
            "success": True,
            "policy": {
                "guests": current._guests,
                "storages": current._storages,
                "defaults": current._defaults,
                "thresholds": current._thresholds,
            },
            "summary": current.describe(),
            "vocabulary": {
                "expectations": list(audit_policy._EXPECTATIONS),
                "roles": list(audit_policy._ROLES),
                "thresholds": audit_policy.DEFAULT_THRESHOLDS,
            },
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/policy', methods=['PUT'])
@require_admin_scope
def save_policy():
    """Replace the declaration.

    Validation is the store's, not this endpoint's: a declaration that
    cannot be understood is refused with the reason rather than written
    and reinterpreted later.
    """
    if not audit_policy:
        return _unavailable()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False, message="A policy object is required"), 400
    revision = payload.get("expected_revision")
    if not isinstance(revision, str) or not revision:
        return jsonify(success=False, message="A policy revision is required"), 428
    try:
        saved = audit_policy.save(payload, expected_revision=revision)
    except audit_policy.PolicyConflict as e:
        return jsonify(success=False, message=str(e)), 409
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    return jsonify({"success": True, "summary": saved.describe()})


@audit_bp.route('/api/audit/changes', methods=['GET'])
@require_auth
def changes():
    """What ProxMenux changed on this host, and what was there before.

    The diff of each configuration change travels with it: a function may
    run to hundreds of lines and alter two values, and it is the two
    values the reader is owed.
    """
    if not changes_journal:
        return _unavailable()
    try:
        limit = min(int(request.args.get('limit', 200)), 1000)
        entries = changes_journal.changes(
            limit=limit,
            offset=int(request.args.get('offset', 0)),
            function=request.args.get('function', ''),
            klass=request.args.get('class', ''),
        )
        for entry in entries:
            entry["diff"] = changes_journal.diff_of(entry)
        return jsonify({"success": True, "changes": entries,
                        "summary": changes_journal.summary()})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
