#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux Security Manager
Handles Proxmox firewall status, rules, and security tool detection.
"""

import os
import json
import subprocess
import re

# =================================================================
# Proxmox Firewall Management
# =================================================================

# Proxmox firewall config paths
CLUSTER_FW = "/etc/pve/firewall/cluster.fw"
HOST_FW_DIR = "/etc/pve/local"  # host.fw is per-node

def _run_cmd(cmd, timeout=10):
    """Run a shell command and return (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


def get_firewall_status():
    """
    Get the overall Proxmox firewall status.
    Returns dict with status info.
    """
    result = {
        "pve_firewall_installed": False,
        "pve_firewall_active": False,
        "cluster_fw_enabled": False,
        "host_fw_enabled": False,
        "rules_count": 0,
        "rules": [],
        "monitor_port_open": False,
    }

    # Check if pve-firewall service exists
    rc, out, _ = _run_cmd(["systemctl", "is-active", "pve-firewall"])
    result["pve_firewall_installed"] = rc == 0 or "inactive" in out or "active" in out
    result["pve_firewall_active"] = (rc == 0 and out == "active")

    # If not installed or inactive, check if the service unit exists
    if not result["pve_firewall_installed"]:
        rc2, _, _ = _run_cmd(["systemctl", "cat", "pve-firewall"])
        result["pve_firewall_installed"] = rc2 == 0

    # Parse cluster firewall config
    if os.path.isfile(CLUSTER_FW):
        try:
            with open(CLUSTER_FW, 'r') as f:
                content = f.read()
            # Check if firewall is enabled at cluster level
            for line in content.splitlines():
                line = line.strip()
                if line.lower().startswith("enable:"):
                    val = line.split(":", 1)[1].strip()
                    result["cluster_fw_enabled"] = val == "1"
                    break
        except Exception:
            pass

    # Parse host firewall config
    host_fw = os.path.join(HOST_FW_DIR, "host.fw")
    if os.path.isfile(host_fw):
        try:
            with open(host_fw, 'r') as f:
                content = f.read()
            for line in content.splitlines():
                line = line.strip()
                if line.lower().startswith("enable:"):
                    val = line.split(":", 1)[1].strip()
                    result["host_fw_enabled"] = val == "1"
                    break
        except Exception:
            pass

    # Get rules
    rules = _parse_firewall_rules()
    result["rules"] = rules
    result["rules_count"] = len(rules)

    # Check if port 8008 is allowed
    for rule in rules:
        dport = str(rule.get("dport", ""))
        if "8008" in dport and rule.get("action", "").upper() == "ACCEPT":
            result["monitor_port_open"] = True
            break

    return result


def _parse_firewall_rules():
    """Parse all firewall rules from cluster and host configs"""
    rules = []
    rule_idx_by_file = {}  # Track rule index per file for deletion

    for fw_file, source in [(CLUSTER_FW, "cluster"), (os.path.join(HOST_FW_DIR, "host.fw"), "host")]:
        if not os.path.isfile(fw_file):
            continue
        rule_idx_by_file[source] = 0
        try:
            with open(fw_file, 'r') as f:
                content = f.read()

            in_rules = False
            section = ""
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Detect section headers
                if line.startswith('['):
                    section_match = re.match(r'\[(\w+)\]', line)
                    if section_match:
                        section = section_match.group(1).upper()
                        in_rules = section in ("RULES", "IN", "OUT")
                    continue

                if in_rules or section in ("RULES", "IN", "OUT"):
                    rule = _parse_rule_line(line, source, section)
                    if rule:
                        rule["rule_index"] = rule_idx_by_file[source]
                        rules.append(rule)
                    rule_idx_by_file[source] += 1
        except Exception:
            pass

    return rules


def _parse_rule_line(line, source, section):
    """Parse a single firewall rule line"""
    # Proxmox rule format: |ACTION MACRO(params) -option value ...
    # or: IN/OUT ACTION -p proto -dport port -source addr
    parts = line.split()
    if len(parts) < 2:
        return None

    rule = {
        "raw": line,
        "source_file": source,
        "section": section,
    }

    idx = 0
    # Direction
    if parts[0].upper() in ("IN", "OUT"):
        rule["direction"] = parts[0].upper()
        idx = 1
    elif section in ("IN",):
        rule["direction"] = "IN"
    elif section in ("OUT",):
        rule["direction"] = "OUT"

    if idx < len(parts):
        rule["action"] = parts[idx].upper()
        idx += 1

    # Parse options
    while idx < len(parts):
        opt = parts[idx]
        if opt.startswith("-") and idx + 1 < len(parts):
            key = opt.lstrip("-")
            val = parts[idx + 1]
            rule[key] = val
            idx += 2
        else:
            idx += 1

    return rule


def add_firewall_rule(direction="IN", action="ACCEPT", protocol="tcp", dport="", sport="",
                      source="", dest="", iface="", comment="", level="host"):
    """
    Add a custom firewall rule to host or cluster firewall config.
    Returns (success, message)
    """
    # Validate inputs
    action = action.upper()
    if action not in ("ACCEPT", "DROP", "REJECT"):
        return False, f"Invalid action: {action}. Must be ACCEPT, DROP, or REJECT"
    
    direction = direction.upper()
    if direction not in ("IN", "OUT"):
        return False, f"Invalid direction: {direction}. Must be IN or OUT"

    # Build rule line
    parts = [direction, action]

    if protocol:
        parts.extend(["-p", protocol.lower()])
    if dport:
        # Validate port
        if not re.match(r'^[\d:,]+$', dport):
            return False, f"Invalid destination port: {dport}"
        parts.extend(["-dport", dport])
    if sport:
        if not re.match(r'^[\d:,]+$', sport):
            return False, f"Invalid source port: {sport}"
        parts.extend(["-sport", sport])
    if source:
        parts.extend(["-source", source])
    if dest:
        parts.extend(["-dest", dest])
    if iface:
        parts.extend(["-i", iface])

    parts.extend(["-log", "nolog"])

    if comment:
        # Sanitize comment
        safe_comment = re.sub(r'[^\w\s\-._/():]', '', comment)
        parts.append(f"# {safe_comment}")

    rule_line = " ".join(parts)

    # Determine target file
    if level == "cluster":
        fw_file = CLUSTER_FW
    else:
        fw_file = os.path.join(HOST_FW_DIR, "host.fw")

    try:
        content = ""
        has_rules_section = False

        if os.path.isfile(fw_file):
            with open(fw_file, 'r') as f:
                content = f.read()
            has_rules_section = "[RULES]" in content

        if has_rules_section:
            lines = content.splitlines()
            new_lines = []
            inserted = False
            for line in lines:
                new_lines.append(line)
                if not inserted and line.strip() == "[RULES]":
                    new_lines.append(rule_line)
                    inserted = True
            content = "\n".join(new_lines) + "\n"
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += "\n[RULES]\n"
            content += rule_line + "\n"

        os.makedirs(os.path.dirname(fw_file), exist_ok=True)
        with open(fw_file, 'w') as f:
            f.write(content)

        _run_cmd(["pve-firewall", "reload"])

        return True, f"Firewall rule added: {direction} {action} {protocol}{':' + dport if dport else ''}"
    except PermissionError:
        return False, "Permission denied. Cannot write to firewall config."
    except Exception as e:
        return False, f"Failed to add firewall rule: {str(e)}"


def delete_firewall_rule(rule_index, level="host"):
    """
    Delete a firewall rule by index from host or cluster config.
    The index corresponds to the order of rules in [RULES] section.
    Returns (success, message)
    """
    if level == "cluster":
        fw_file = CLUSTER_FW
    else:
        fw_file = os.path.join(HOST_FW_DIR, "host.fw")

    if not os.path.isfile(fw_file):
        return False, "Firewall config file not found"

    try:
        with open(fw_file, 'r') as f:
            content = f.read()

        lines = content.splitlines()
        new_lines = []
        in_rules = False
        current_rule_idx = 0
        removed_rule = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('['):
                section_match = re.match(r'\[(\w+)\]', stripped)
                if section_match:
                    section = section_match.group(1).upper()
                    in_rules = section in ("RULES", "IN", "OUT")

            if in_rules and stripped and not stripped.startswith('#') and not stripped.startswith('['):
                # This is a rule line
                if current_rule_idx == rule_index:
                    removed_rule = stripped
                    current_rule_idx += 1
                    continue  # Skip this line (delete it)
                current_rule_idx += 1

            new_lines.append(line)

        if removed_rule is None:
            return False, f"Rule index {rule_index} not found"

        with open(fw_file, 'w') as f:
            f.write("\n".join(new_lines) + "\n")

        _run_cmd(["pve-firewall", "reload"])

        return True, f"Firewall rule deleted: {removed_rule}"
    except PermissionError:
        return False, "Permission denied. Cannot modify firewall config."
    except Exception as e:
        return False, f"Failed to delete rule: {str(e)}"


def add_monitor_port_rule():
    """
    Add a firewall rule to allow port 8008 (ProxMenux Monitor) on the host.
    Returns (success, message)
    """
    host_fw = os.path.join(HOST_FW_DIR, "host.fw")

    # Check if rule already exists
    status = get_firewall_status()
    if status.get("monitor_port_open"):
        return True, "Port 8008 is already allowed in the firewall"

    try:
        content = ""
        has_rules_section = False

        if os.path.isfile(host_fw):
            with open(host_fw, 'r') as f:
                content = f.read()
            has_rules_section = "[RULES]" in content

        rule_line = "IN ACCEPT -p tcp -dport 8008 -log nolog # ProxMenux Monitor"

        if has_rules_section:
            # Add rule after [RULES] section header
            lines = content.splitlines()
            new_lines = []
            inserted = False
            for line in lines:
                new_lines.append(line)
                if not inserted and line.strip() == "[RULES]":
                    new_lines.append(rule_line)
                    inserted = True
            content = "\n".join(new_lines) + "\n"
        else:
            # Add [RULES] section
            if content and not content.endswith("\n"):
                content += "\n"
            content += "\n[RULES]\n"
            content += rule_line + "\n"

        with open(host_fw, 'w') as f:
            f.write(content)

        # Reload firewall
        _run_cmd(["pve-firewall", "reload"])

        return True, "Firewall rule added: port 8008 (TCP) allowed for ProxMenux Monitor"
    except PermissionError:
        return False, "Permission denied. Cannot write to firewall config."
    except Exception as e:
        return False, f"Failed to add firewall rule: {str(e)}"


def remove_monitor_port_rule():
    """
    Remove the ProxMenux Monitor port 8008 rule from host firewall.
    Returns (success, message)
    """
    host_fw = os.path.join(HOST_FW_DIR, "host.fw")

    if not os.path.isfile(host_fw):
        return True, "No host firewall config found"

    try:
        with open(host_fw, 'r') as f:
            lines = f.readlines()

        new_lines = []
        removed = False
        for line in lines:
            if "8008" in line and "ProxMenux" in line:
                removed = True
                continue
            new_lines.append(line)

        if not removed:
            return True, "No ProxMenux Monitor rule found to remove"

        with open(host_fw, 'w') as f:
            f.writelines(new_lines)

        _run_cmd(["pve-firewall", "reload"])

        return True, "ProxMenux Monitor firewall rule removed"
    except Exception as e:
        return False, f"Failed to remove firewall rule: {str(e)}"


def enable_firewall(level="host"):
    """
    Enable the Proxmox firewall at host or cluster level.
    Returns (success, message)
    """
    if level == "cluster":
        return _set_firewall_enabled(CLUSTER_FW, True)
    else:
        host_fw = os.path.join(HOST_FW_DIR, "host.fw")
        return _set_firewall_enabled(host_fw, True)


def disable_firewall(level="host"):
    """
    Disable the Proxmox firewall at host or cluster level.
    Returns (success, message)
    """
    if level == "cluster":
        return _set_firewall_enabled(CLUSTER_FW, False)
    else:
        host_fw = os.path.join(HOST_FW_DIR, "host.fw")
        return _set_firewall_enabled(host_fw, False)


def _set_firewall_enabled(fw_file, enabled):
    """Set enable: 1 or enable: 0 in firewall config"""
    try:
        content = ""
        if os.path.isfile(fw_file):
            with open(fw_file, 'r') as f:
                content = f.read()

        enable_val = "1" if enabled else "0"
        has_options = "[OPTIONS]" in content
        has_enable = False

        lines = content.splitlines()
        new_lines = []
        in_options = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("["):
                in_options = stripped == "[OPTIONS]"

            if in_options and stripped.lower().startswith("enable:"):
                new_lines.append(f"enable: {enable_val}")
                has_enable = True
            else:
                new_lines.append(line)

        if not has_enable:
            if has_options:
                # Add enable line after [OPTIONS]
                final_lines = []
                for line in new_lines:
                    final_lines.append(line)
                    if line.strip() == "[OPTIONS]":
                        final_lines.append(f"enable: {enable_val}")
                new_lines = final_lines
            else:
                # Add [OPTIONS] section at the beginning
                new_lines.insert(0, "[OPTIONS]")
                new_lines.insert(1, f"enable: {enable_val}")
                new_lines.insert(2, "")

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(fw_file), exist_ok=True)

        with open(fw_file, 'w') as f:
            f.write("\n".join(new_lines) + "\n")

        # Reload or start the firewall service
        if enabled:
            _run_cmd(["systemctl", "enable", "pve-firewall"])
            _run_cmd(["systemctl", "start", "pve-firewall"])
        
        _run_cmd(["pve-firewall", "reload"])

        state = "enabled" if enabled else "disabled"
        level = "cluster" if fw_file == CLUSTER_FW else "host"
        return True, f"Firewall {state} at {level} level"
    except PermissionError:
        return False, "Permission denied. Cannot modify firewall config."
    except Exception as e:
        return False, f"Failed to modify firewall: {str(e)}"


# =================================================================
# Security Tools Detection
# =================================================================

# =================================================================
# Fail2Ban Detailed Management
# =================================================================

def get_fail2ban_details():
    """
    Get detailed Fail2Ban info: per-jail banned IPs, ban times, etc.
    Returns dict with detailed jail information.
    """
    result = {
        "installed": False,
        "active": False,
        "version": "",
        "jails": [],
    }

    rc, out, _ = _run_cmd(["fail2ban-client", "--version"])
    if rc != 0:
        return result

    result["installed"] = True
    result["version"] = out.split("\n")[0].strip() if out else ""

    rc2, out2, _ = _run_cmd(["systemctl", "is-active", "fail2ban"])
    result["active"] = (rc2 == 0 and out2 == "active")

    if not result["active"]:
        return result

    # Get jail list
    rc3, out3, _ = _run_cmd(["fail2ban-client", "status"])
    jail_names = []
    if rc3 == 0:
        for line in out3.splitlines():
            if "Jail list:" in line:
                jails_str = line.split(":", 1)[1].strip()
                jail_names = [j.strip() for j in jails_str.split(",") if j.strip()]

    # Get detailed info per jail
    for jail_name in jail_names:
        jail_info = {
            "name": jail_name,
            "currently_failed": 0,
            "total_failed": 0,
            "currently_banned": 0,
            "total_banned": 0,
            "banned_ips": [],
            "findtime": "",
            "bantime": "",
            "maxretry": "",
        }

        rc4, out4, _ = _run_cmd(["fail2ban-client", "status", jail_name])
        if rc4 == 0:
            for line in out4.splitlines():
                line = line.strip()
                if "Currently failed:" in line:
                    try:
                        jail_info["currently_failed"] = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif "Total failed:" in line:
                    try:
                        jail_info["total_failed"] = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif "Currently banned:" in line:
                    try:
                        jail_info["currently_banned"] = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif "Total banned:" in line:
                    try:
                        jail_info["total_banned"] = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif "Banned IP list:" in line:
                    ips_str = line.split(":", 1)[1].strip()
                    if ips_str:
                        raw_ips = [ip.strip() for ip in ips_str.split() if ip.strip()]
                        jail_info["banned_ips"] = [
                            {"ip": ip, "type": classify_ip(ip)} for ip in raw_ips
                        ]

        # Get jail config values
        for key in ["findtime", "bantime", "maxretry"]:
            rc5, out5, _ = _run_cmd(["fail2ban-client", "get", jail_name, key])
            if rc5 == 0 and out5:
                jail_info[key] = out5.strip()

        result["jails"].append(jail_info)

    return result


def classify_ip(ip_address):
    """
    Classify an IP address as 'local' or 'external'.
    Local: 10.x.x.x, 172.16-31.x.x, 192.168.x.x, 127.x.x.x, fd00::/8, fe80::/10, ::1
    """
    if not ip_address:
        return "unknown"

    ip = ip_address.strip()

    # IPv4 private ranges
    if ip.startswith("10.") or ip.startswith("127.") or ip.startswith("192.168."):
        return "local"
    if ip.startswith("172."):
        try:
            second_octet = int(ip.split(".")[1])
            if 16 <= second_octet <= 31:
                return "local"
        except (ValueError, IndexError):
            pass

    # IPv6 private/link-local
    ip_lower = ip.lower()
    if ip_lower == "::1" or ip_lower.startswith("fd") or ip_lower.startswith("fe80"):
        return "local"

    return "external"


def update_jail_config(jail_name, maxretry=None, bantime=None, findtime=None):
    """
    Update Fail2Ban jail configuration (maxretry, bantime, findtime).
    Uses fail2ban-client set commands for live changes, and also writes
    to the jail.local file for persistence.

    bantime = -1 means permanent ban.
    Returns (success, message)
    """
    if not jail_name:
        return False, "Jail name is required"

    changes = []
    errors = []

    # Apply live changes via fail2ban-client
    if maxretry is not None:
        try:
            val = int(maxretry)
            if val < 1:
                return False, "Max retries must be at least 1"
            rc, _, err = _run_cmd(["fail2ban-client", "set", jail_name, "maxretry", str(val)])
            if rc == 0:
                changes.append(f"maxretry={val}")
            else:
                errors.append(f"maxretry: {err}")
        except ValueError:
            errors.append("maxretry must be a number")

    if bantime is not None:
        try:
            val = int(bantime)
            # -1 = permanent, otherwise must be positive
            if val < -1 or val == 0:
                return False, "Ban time must be positive seconds or -1 for permanent"
            rc, _, err = _run_cmd(["fail2ban-client", "set", jail_name, "bantime", str(val)])
            if rc == 0:
                changes.append(f"bantime={val}")
            else:
                errors.append(f"bantime: {err}")
        except ValueError:
            errors.append("bantime must be a number")

    if findtime is not None:
        try:
            val = int(findtime)
            if val < 1:
                return False, "Find time must be positive"
            rc, _, err = _run_cmd(["fail2ban-client", "set", jail_name, "findtime", str(val)])
            if rc == 0:
                changes.append(f"findtime={val}")
            else:
                errors.append(f"findtime: {err}")
        except ValueError:
            errors.append("findtime must be a number")

    # Also persist to jail.local so changes survive restart
    if changes:
        _persist_jail_config(jail_name, maxretry, bantime, findtime)

    if errors:
        return False, "Errors: " + "; ".join(errors)

    if changes:
        return True, f"Jail '{jail_name}' updated: {', '.join(changes)}"

    return False, "No changes specified"


def _persist_jail_config(jail_name, maxretry=None, bantime=None, findtime=None):
    """
    Write jail config changes to /etc/fail2ban/jail.local for persistence.
    """
    jail_local = "/etc/fail2ban/jail.local"

    try:
        content = ""
        if os.path.isfile(jail_local):
            with open(jail_local, 'r') as f:
                content = f.read()

        lines = content.splitlines() if content else []

        # Find or create the jail section
        jail_section = f"[{jail_name}]"
        section_start = -1
        section_end = len(lines)

        for i, line in enumerate(lines):
            if line.strip() == jail_section:
                section_start = i
            elif section_start >= 0 and line.strip().startswith("[") and i > section_start:
                section_end = i
                break

        # Build settings to update
        settings = {}
        if maxretry is not None:
            settings["maxretry"] = str(int(maxretry))
        if bantime is not None:
            settings["bantime"] = str(int(bantime))
        if findtime is not None:
            settings["findtime"] = str(int(findtime))

        if section_start >= 0:
            # Update existing section
            for key, val in settings.items():
                found = False
                for i in range(section_start + 1, section_end):
                    stripped = lines[i].strip()
                    if stripped.startswith(f"{key}") and "=" in stripped:
                        lines[i] = f"{key} = {val}"
                        found = True
                        break
                if not found:
                    lines.insert(section_start + 1, f"{key} = {val}")
                    section_end += 1
        else:
            # Create new section
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(jail_section)
            for key, val in settings.items():
                lines.append(f"{key} = {val}")

        with open(jail_local, 'w') as f:
            f.write("\n".join(lines) + "\n")

    except Exception:
        pass  # Best effort persistence


def unban_ip(jail_name, ip_address):
    """
    Unban a specific IP from a Fail2Ban jail.
    Returns (success, message)
    """
    if not jail_name or not ip_address:
        return False, "Jail name and IP address are required"

    # Validate IP format (basic check)
    if not re.match(r'^[\d.:a-fA-F]+$', ip_address):
        return False, f"Invalid IP address format: {ip_address}"

    rc, out, err = _run_cmd(["fail2ban-client", "set", jail_name, "unbanip", ip_address])
    if rc == 0:
        return True, f"IP {ip_address} has been unbanned from jail '{jail_name}'"
    else:
        return False, f"Failed to unban IP: {err or out}"


def get_fail2ban_recent_activity(lines=50):
    """
    Get recent Fail2Ban log activity (bans and unbans).
    Returns list of recent events.
    """
    events = []

    log_file = "/var/log/fail2ban.log"
    if not os.path.isfile(log_file):
        return events

    try:
        # Read last N lines using tail
        rc, out, _ = _run_cmd(["tail", f"-{lines}", log_file], timeout=5)
        if rc != 0 or not out:
            return events

        for line in out.splitlines():
            event = None

            # Parse ban events
            ban_match = re.search(
                r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})[,\d]*\s+.*\[(\w+)\]\s+Ban\s+([\d.:a-fA-F]+)',
                line
            )
            if ban_match:
                event = {
                    "timestamp": ban_match.group(1),
                    "jail": ban_match.group(2),
                    "ip": ban_match.group(3),
                    "action": "ban",
                }

            # Parse unban events
            if not event:
                unban_match = re.search(
                    r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})[,\d]*\s+.*\[(\w+)\]\s+Unban\s+([\d.:a-fA-F]+)',
                    line
                )
                if unban_match:
                    event = {
                        "timestamp": unban_match.group(1),
                        "jail": unban_match.group(2),
                        "ip": unban_match.group(3),
                        "action": "unban",
                    }

            # Parse found (failed attempt) events
            if not event:
                found_match = re.search(
                    r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})[,\d]*\s+.*\[(\w+)\]\s+Found\s+([\d.:a-fA-F]+)',
                    line
                )
                if found_match:
                    event = {
                        "timestamp": found_match.group(1),
                        "jail": found_match.group(2),
                        "ip": found_match.group(3),
                        "action": "found",
                    }

            if event:
                events.append(event)

        # Return most recent first
        events.reverse()

    except Exception:
        pass

    return events


def detect_security_tools():
    """
    Detect installed security tools on the system.
    Returns dict with tool status info.
    """
    tools = {}

    # Fail2Ban
    tools["fail2ban"] = _detect_fail2ban()

    # Lynis
    tools["lynis"] = _detect_lynis()

    return tools


def _detect_fail2ban():
    """Detect Fail2Ban installation and status"""
    info = {
        "installed": False,
        "active": False,
        "version": "",
        "jails": [],
        "banned_ips_count": 0,
    }

    rc, out, _ = _run_cmd(["fail2ban-client", "--version"])
    if rc == 0:
        info["installed"] = True
        info["version"] = out.split("\n")[0].strip() if out else ""

        # Check service status
        rc2, out2, _ = _run_cmd(["systemctl", "is-active", "fail2ban"])
        info["active"] = (rc2 == 0 and out2 == "active")

        if info["active"]:
            # Get jails
            rc3, out3, _ = _run_cmd(["fail2ban-client", "status"])
            if rc3 == 0:
                for line in out3.splitlines():
                    if "Jail list:" in line:
                        jails_str = line.split(":", 1)[1].strip()
                        info["jails"] = [j.strip() for j in jails_str.split(",") if j.strip()]

            # Count banned IPs across all jails
            total_banned = 0
            for jail in info["jails"]:
                rc4, out4, _ = _run_cmd(["fail2ban-client", "status", jail])
                if rc4 == 0:
                    for line in out4.splitlines():
                        if "Currently banned:" in line:
                            try:
                                count = int(line.split(":", 1)[1].strip())
                                total_banned += count
                            except ValueError:
                                pass
            info["banned_ips_count"] = total_banned

    return info


def _detect_lynis():
    """Detect Lynis installation and status"""
    info = {
        "installed": False,
        "version": "",
        "last_scan": None,
        "hardening_index": None,
    }

    # Check both locations
    lynis_cmd = None
    for path in ["/usr/local/bin/lynis", "/opt/lynis/lynis", "/usr/bin/lynis"]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            lynis_cmd = path
            break

    if lynis_cmd:
        info["installed"] = True
        rc, out, _ = _run_cmd([lynis_cmd, "show", "version"])
        if rc == 0:
            info["version"] = out.strip()

        # Check for last scan report
        report_file = "/var/log/lynis-report.dat"
        if os.path.isfile(report_file):
            try:
                with open(report_file, 'r') as f:
                    for line in f:
                        if line.startswith("report_datetime_start="):
                            info["last_scan"] = line.split("=", 1)[1].strip()
                        elif line.startswith("hardening_index="):
                            try:
                                info["hardening_index"] = int(line.split("=", 1)[1].strip())
                            except ValueError:
                                pass
            except Exception:
                pass

    return info
