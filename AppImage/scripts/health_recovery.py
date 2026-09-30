"""Bounded recovery metadata admission, without importing monitor singletons.

Native persistence additionally binds the exact incident and closure. Manual
notifications remain authenticated caller assertions: shape validation cannot
establish that an asserted measurement actually happened.
"""
import math
import time
from typing import TypeGuard


def _finite_number(value) -> TypeGuard[int | float]:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, ValueError, TypeError):
        return False


def valid_check_evidence(error_key, proof, *, now=None):
    """Validate a supported measurement contract, not its external authenticity."""
    if not isinstance(proof, dict) or proof.get('check') != error_key:
        return False
    checked = proof.get('checked_at')
    now = time.time() if now is None else now
    if not _finite_number(checked) or not _finite_number(now) or not 0 <= now-checked <= 7200:
        return False
    if error_key == 'cpu_usage':
        policy = proof.get('policy')
        if not isinstance(policy, dict) or set(policy) != {'warning', 'critical', 'recovery'}:
            return False
        if not all(_finite_number(v) and 1 <= v <= 100 for v in policy.values()):
            return False
        if policy['warning'] > policy['critical']:
            return False
        value, maximum, count = proof.get('value'), proof.get('max_sample'), proof.get('normal_samples')
        return (_finite_number(value) and _finite_number(maximum)
                and 0 <= value <= maximum < min(policy['warning'], policy['recovery'])
                and isinstance(count, int) and not isinstance(count, bool) and count >= 10)
    if isinstance(error_key, str) and error_key.startswith('pve_service_'):
        service = error_key[len('pve_service_'):]
        return (bool(service) and proof.get('service') == service
                and proof.get('state') == 'active'
                and type(proof.get('returncode')) is int and proof['returncode'] == 0)
    return False


def presents_recovery(data):
    """One presentation predicate shared by template, icon and email badge."""
    return (isinstance(data, dict) and data.get('recovery_outcome') == 'resolved'
            and data.get('is_recovery') is True
            and valid_check_evidence(data.get('error_key'), data.get('check_evidence')))
