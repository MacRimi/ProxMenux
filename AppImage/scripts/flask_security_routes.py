#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux Security Routes
Flask blueprint for firewall management and security tool detection.
"""

from flask import Blueprint, jsonify, request
from jwt_middleware import require_auth

security_bp = Blueprint('security', __name__)

try:
    import security_manager
except ImportError:
    security_manager = None


# -------------------------------------------------------------------
# Proxmox Firewall
# -------------------------------------------------------------------

@security_bp.route('/api/security/firewall/status', methods=['GET'])
@require_auth
def firewall_status():
    """Get Proxmox firewall status, rules, and port 8008 status"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        status = security_manager.get_firewall_status()
        return jsonify({"success": True, **status})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/enable', methods=['POST'])
@require_auth
def firewall_enable():
    """Enable Proxmox firewall at host or cluster level"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        level = data.get("level", "host")
        success, message = security_manager.enable_firewall(level)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/disable', methods=['POST'])
@require_auth
def firewall_disable():
    """Disable Proxmox firewall at host or cluster level"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        level = data.get("level", "host")
        success, message = security_manager.disable_firewall(level)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/rules', methods=['POST'])
@require_auth
def firewall_add_rule():
    """Add a custom firewall rule"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        success, message = security_manager.add_firewall_rule(
            direction=data.get("direction", "IN"),
            action=data.get("action", "ACCEPT"),
            protocol=data.get("protocol", "tcp"),
            dport=data.get("dport", ""),
            sport=data.get("sport", ""),
            source=data.get("source", ""),
            dest=data.get("dest", ""),
            iface=data.get("iface", ""),
            comment=data.get("comment", ""),
            level=data.get("level", "host"),
        )
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/rules', methods=['DELETE'])
@require_auth
def firewall_delete_rule():
    """Delete a firewall rule by index"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        rule_index = data.get("rule_index")
        level = data.get("level", "host")
        if rule_index is None:
            return jsonify({"success": False, "message": "rule_index is required"}), 400
        success, message = security_manager.delete_firewall_rule(int(rule_index), level)
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/rules/edit', methods=['PUT'])
@require_auth
def firewall_edit_rule():
    """Edit an existing firewall rule (delete old + insert new at same position)"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        rule_index = data.get("rule_index")
        level = data.get("level", "host")
        new_rule = data.get("new_rule", {})
        if rule_index is None:
            return jsonify({"success": False, "message": "rule_index is required"}), 400

        success, message = security_manager.edit_firewall_rule(
            rule_index=int(rule_index),
            level=level,
            direction=new_rule.get("direction", "IN"),
            action=new_rule.get("action", "ACCEPT"),
            protocol=new_rule.get("protocol", "tcp"),
            dport=new_rule.get("dport", ""),
            sport=new_rule.get("sport", ""),
            source=new_rule.get("source", ""),
            dest=new_rule.get("dest", ""),
            iface=new_rule.get("iface", ""),
            comment=new_rule.get("comment", ""),
        )
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/monitor-port', methods=['POST'])
@require_auth
def firewall_add_monitor_port():
    """Add firewall rule to allow port 8008 for ProxMenux Monitor"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        success, message = security_manager.add_monitor_port_rule()
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/firewall/monitor-port', methods=['DELETE'])
@require_auth
def firewall_remove_monitor_port():
    """Remove the ProxMenux Monitor port 8008 rule"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        success, message = security_manager.remove_monitor_port_rule()
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------------------------------------------------------
# Fail2Ban Detailed Management
# -------------------------------------------------------------------

@security_bp.route('/api/security/fail2ban/details', methods=['GET'])
@require_auth
def fail2ban_details():
    """Get detailed Fail2Ban info: per-jail banned IPs, stats, config"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        details = security_manager.get_fail2ban_details()
        return jsonify({"success": True, **details})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/fail2ban/unban', methods=['POST'])
@require_auth
def fail2ban_unban():
    """Unban a specific IP from a Fail2Ban jail"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        jail = data.get("jail", "")
        ip = data.get("ip", "")
        success, message = security_manager.unban_ip(jail, ip)
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/fail2ban/jail/config', methods=['PUT'])
@require_auth
def fail2ban_jail_config():
    """Update jail configuration (maxretry, bantime, findtime)"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        data = request.json or {}
        jail = data.get("jail", "")
        if not jail:
            return jsonify({"success": False, "message": "Jail name is required"}), 400
        success, message = security_manager.update_jail_config(
            jail,
            maxretry=data.get("maxretry"),
            bantime=data.get("bantime"),
            findtime=data.get("findtime"),
        )
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/fail2ban/apply-jails', methods=['POST'])
@require_auth
def fail2ban_apply_jails():
    """Apply missing Fail2Ban jails (proxmox, proxmenux)"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        success, message, applied = security_manager.apply_missing_jails()
        return jsonify({"success": success, "message": message, "applied": applied})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/fail2ban/activity', methods=['GET'])
@require_auth
def fail2ban_activity():
    """Get recent Fail2Ban log activity"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        events = security_manager.get_fail2ban_recent_activity()
        return jsonify({"success": True, "events": events})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------------------------------------------------------
# Lynis Audit
# -------------------------------------------------------------------

@security_bp.route('/api/security/lynis/run', methods=['POST'])
@require_auth
def lynis_run_audit():
    """Start a Lynis audit (runs in background)"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        success, message = security_manager.run_lynis_audit()
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/lynis/status', methods=['GET'])
@require_auth
def lynis_audit_status():
    """Get Lynis audit running status"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        status = security_manager.get_lynis_audit_status()
        return jsonify({"success": True, **status})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/lynis/report', methods=['GET'])
@require_auth
def lynis_report():
    """Get parsed Lynis audit report"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        report = security_manager.parse_lynis_report()
        if report:
            return jsonify({"success": True, "report": report})
        else:
            return jsonify({"success": False, "message": "No report available. Run an audit first."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/lynis/report', methods=['DELETE'])
@require_auth
def lynis_report_delete():
    """Delete Lynis audit report files"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        import os
        deleted = []
        for f in ["/var/log/lynis-report.dat", "/var/log/lynis.log", "/var/log/lynis-output.log"]:
            if os.path.isfile(f):
                os.remove(f)
                deleted.append(f)
        if deleted:
            return jsonify({"success": True, "message": f"Deleted: {', '.join(deleted)}"})
        else:
            return jsonify({"success": False, "message": "No report files found to delete"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------------------------------------------------------
# Security Tools Uninstall
# -------------------------------------------------------------------

@security_bp.route('/api/security/fail2ban/uninstall', methods=['POST'])
@require_auth
def fail2ban_uninstall():
    """Uninstall Fail2Ban and clean up configuration"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        success, message = security_manager.uninstall_fail2ban()
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@security_bp.route('/api/security/lynis/uninstall', methods=['POST'])
@require_auth
def lynis_uninstall():
    """Uninstall Lynis and clean up files"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        success, message = security_manager.uninstall_lynis()
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------------------------------------------------------
# Security Tools Detection
# -------------------------------------------------------------------

@security_bp.route('/api/security/tools', methods=['GET'])
@require_auth
def security_tools():
    """Detect installed security tools (Fail2Ban, Lynis, etc.)"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        tools = security_manager.detect_security_tools()
        return jsonify({"success": True, "tools": tools})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
