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
from jwt_middleware import require_auth

audit_bp = Blueprint('audit', __name__)

try:
    import audit_store
    import audit_checks
    import audit_checks_pve  # noqa: F401 — importing registers the checks
except ImportError:
    audit_store = None
    audit_checks = None

# One assessment at a time. The flag is also what the interface polls to
# know a run is still in progress.
_run_lock = threading.Lock()
_running: dict = {'active': False, 'run_id': None, 'started_at': 0}


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
    if not audit_store:
        return _unavailable()
    try:
        latest = audit_store.latest_run()
        summary = {}
        if latest:
            for f in audit_store.get_findings(latest['run_id']):
                summary[f['state']] = summary.get(f['state'], 0) + 1
        return jsonify({
            "success": True,
            "running": _running['active'],
            "latest": latest,
            "summary": summary,
            "baseline": audit_store.get_baseline(),
            "exceptions": len(audit_store.active_exceptions()),
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/run', methods=['POST'])
@require_auth
def run():
    """Start an assessment in the background.

    The response returns immediately with the run identifier; the
    interface polls ``/api/audit/status``. A full assessment is short but
    runs against a production host, so it must not hold an HTTP worker.
    """
    if not audit_checks:
        return _unavailable()

    data = request.get_json(silent=True) or {}
    profile = str(data.get('profile') or 'full')
    areas = data.get('areas')
    only = set(areas) if isinstance(areas, list) and areas else None

    with _run_lock:
        if _running['active']:
            return jsonify({
                "success": False,
                "message": "An assessment is already running",
                "run_id": _running['run_id'],
            }), 409
        _running.update({'active': True, 'run_id': None,
                         'started_at': time.time()})

    def worker():
        try:
            run_id = audit_checks.run_assessment(profile, only_areas=only)
            _running['run_id'] = run_id
            audit_store.prune_runs()
        except Exception as e:
            print(f"[audit] assessment failed: {e}")
        finally:
            _running['active'] = False

    threading.Thread(target=worker, daemon=True, name='audit-run').start()
    return jsonify({"success": True, "started": True})


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
        exceptions = audit_store.active_exceptions()
        findings = audit_store.get_findings(run_id)
        for f in findings:
            f['exception'] = exceptions.get(f['check_id'])
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
@require_auth
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
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/exceptions', methods=['POST'])
@require_auth
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

        expires_at = None
        days = data.get('expires_in_days')
        if days:
            try:
                expires_at = int(time.time()) + int(days) * 86400
            except (TypeError, ValueError):
                return jsonify({"success": False,
                                "message": "Invalid expiry"}), 400

        audit_store.accept_risk(
            check_id, reason,
            accepted_by=str(data.get('accepted_by') or 'admin'),
            expires_at=expires_at,
        )
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@audit_bp.route('/api/audit/exceptions/<path:check_id>', methods=['DELETE'])
@require_auth
def revoke_exception(check_id):
    if not audit_store:
        return _unavailable()
    try:
        removed = audit_store.revoke_risk(check_id)
        if not removed:
            return jsonify({"success": False,
                            "message": "Exception not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
