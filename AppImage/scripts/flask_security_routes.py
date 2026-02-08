#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux Security Routes
Flask blueprint for firewall management and security tool detection.
"""

from flask import Blueprint, jsonify, request

security_bp = Blueprint('security', __name__)

try:
    import security_manager
except ImportError:
    security_manager = None


# -------------------------------------------------------------------
# Proxmox Firewall
# -------------------------------------------------------------------

@security_bp.route('/api/security/firewall/status', methods=['GET'])
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


@security_bp.route('/api/security/firewall/monitor-port', methods=['POST'])
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


@security_bp.route('/api/security/fail2ban/activity', methods=['GET'])
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
# Security Tools Detection
# -------------------------------------------------------------------

@security_bp.route('/api/security/tools', methods=['GET'])
def security_tools():
    """Detect installed security tools (Fail2Ban, Lynis, etc.)"""
    if not security_manager:
        return jsonify({"success": False, "message": "Security manager not available"}), 500
    try:
        tools = security_manager.detect_security_tools()
        return jsonify({"success": True, "tools": tools})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
