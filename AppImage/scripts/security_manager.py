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


def apply_missing_jails():
    """
    Check for missing Fail2Ban jails (proxmox, proxmenux) and create them.
    Returns (success, message, applied_jails).
    """
    applied = []
    errors = []

    # Check which jails are currently active
    rc, out, _ = _run_cmd(["fail2ban-client", "status"])
    if rc != 0:
        return False, "Cannot communicate with fail2ban-client", []

    current_jails = []
    for line in out.splitlines():
        if "Jail list:" in line:
            jails_str = line.split(":", 1)[1].strip()
            current_jails = [j.strip().lower() for j in jails_str.split(",") if j.strip()]

    # --- Proxmox jail (port 8006) ---
    if "proxmox" not in current_jails:
        try:
            # Create filter
            filter_content = """[Definition]
failregex = pvedaemon\\[.*authentication failure; rhost=<HOST> user=.* msg=.*
ignoreregex =
"""
            with open("/etc/fail2ban/filter.d/proxmox.conf", "w") as f:
                f.write(filter_content)

            # Create jail
            jail_content = """[proxmox]
enabled = true
port = 8006
filter = proxmox
logpath = /var/log/daemon.log
maxretry = 3
bantime = 3600
findtime = 600
"""
            with open("/etc/fail2ban/jail.d/proxmox.conf", "w") as f:
                f.write(jail_content)

            applied.append("proxmox")
        except Exception as e:
            errors.append(f"proxmox: {str(e)}")

    # --- ProxMenux Monitor jail (port 8008 + reverse proxy) ---
    if "proxmenux" not in current_jails:
        try:
            # Create filter
            filter_content = """[Definition]
failregex = proxmenux-auth: authentication failure; rhost=<HOST> user=.*
ignoreregex =
"""
            with open("/etc/fail2ban/filter.d/proxmenux.conf", "w") as f:
                f.write(filter_content)

            # Create jail
            jail_content = """[proxmenux]
enabled = true
port = 8008,http,https
filter = proxmenux
logpath = /var/log/proxmenux-auth.log
maxretry = 3
bantime = 3600
findtime = 600
"""
            with open("/etc/fail2ban/jail.d/proxmenux.conf", "w") as f:
                f.write(jail_content)

            # Ensure log file exists
            if not os.path.isfile("/var/log/proxmenux-auth.log"):
                with open("/var/log/proxmenux-auth.log", "w") as f:
                    pass
                os.chmod("/var/log/proxmenux-auth.log", 0o640)

            applied.append("proxmenux")
        except Exception as e:
            errors.append(f"proxmenux: {str(e)}")

    if not applied and not errors:
        return True, "All jails are already configured", []

    if applied:
        # Restart fail2ban to load new jails
        _run_cmd(["systemctl", "restart", "fail2ban"])
        import time
        time.sleep(2)

    if errors:
        return False, "Errors: " + "; ".join(errors), applied

    return True, f"Applied jails: {', '.join(applied)}", applied


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


def _find_lynis_cmd():
    """Find the lynis binary path"""
    for path in ["/usr/local/bin/lynis", "/opt/lynis/lynis", "/usr/bin/lynis"]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _detect_lynis():
    """Detect Lynis installation and status"""
    info = {
        "installed": False,
        "version": "",
        "last_scan": None,
        "hardening_index": None,
    }

    lynis_cmd = _find_lynis_cmd()

    if lynis_cmd:
        info["installed"] = True
        rc, out, _ = _run_cmd([lynis_cmd, "show", "version"])
        if rc == 0:
            info["version"] = out.strip()

        # Check for last scan report - use full parser for accurate data
        report = parse_lynis_report()
        if report:
            info["last_scan"] = report.get("datetime_start", None)
            info["hardening_index"] = report.get("hardening_index", None)
        else:
            # Fallback: quick read of report.dat
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


# Track running audit
_lynis_audit_running = False
_lynis_audit_progress = ""


def run_lynis_audit():
    """
    Run lynis audit system in the background.
    Returns (success, message).
    """
    global _lynis_audit_running, _lynis_audit_progress

    if _lynis_audit_running:
        return False, "An audit is already running"

    lynis_cmd = _find_lynis_cmd()
    if not lynis_cmd:
        return False, "Lynis is not installed"

    _lynis_audit_running = True
    _lynis_audit_progress = "starting"

    import threading

    def _run_audit():
        global _lynis_audit_running, _lynis_audit_progress
        try:
            _lynis_audit_progress = "running"
            # Remove old report so lynis creates a fresh one
            report_file = "/var/log/lynis-report.dat"
            if os.path.isfile(report_file):
                os.remove(report_file)

            # Capture full formatted output. Lynis suppresses its nice
            # formatted output ([+] sections) when stdout is not a tty.
            # Use 'script' to simulate a terminal so Lynis outputs everything.
            output_log = "/var/log/lynis-output.log"
            rc = -1
            out = ""
            err = ""

            # Method 1: Use 'script -qc' (simulates tty)
            try:
                script_cmd = [
                    "script", "-qec",
                    f"{lynis_cmd} audit system --no-colors --quick",
                    output_log
                ]
                result = subprocess.run(
                    script_cmd,
                    capture_output=True, text=True, timeout=600,
                    env={**os.environ, "TERM": "dumb"}
                )
                rc = result.returncode
                out = result.stdout.strip()
                err = result.stderr.strip()
            except Exception:
                pass

            # If script failed or output file is too small, try direct method
            output_ok = (
                os.path.isfile(output_log)
                and os.path.getsize(output_log) > 500
            )
            if not output_ok:
                try:
                    rc, out, err = _run_cmd(
                        [lynis_cmd, "audit", "system", "--no-colors", "--quick"],
                        timeout=600
                    )
                    if out:
                        with open(output_log, "w") as fout:
                            fout.write(out)
                except Exception:
                    pass

            # Clean ALL ANSI/terminal escape codes and control chars from output
            if os.path.isfile(output_log):
                try:
                    import re as _re
                    with open(output_log, 'r', errors='replace') as fout:
                        raw = fout.read()
                    # Remove ALL ANSI escape sequences comprehensively:
                    # CSI sequences: \x1b[ ... (letter)  e.g. \x1b[0m, \x1b[?25h
                    cleaned = _re.sub(r'\x1b\[[\x20-\x3f]*[\x40-\x7e]', '', raw)
                    # OSC sequences: \x1b] ... \x07 or \x1b\\
                    cleaned = _re.sub(r'\x1b\].*?(?:\x07|\x1b\\)', '', cleaned)
                    # Other escape sequences: \x1b followed by one char
                    cleaned = _re.sub(r'\x1b[\x20-\x7e]', '', cleaned)
                    # Remove remaining control characters except \n and \t
                    cleaned = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', cleaned)
                    # Remove carriage returns
                    cleaned = cleaned.replace('\r', '')
                    # Remove 'Script started/done' lines added by script cmd
                    lines = cleaned.splitlines()
                    lines = [l for l in lines
                             if not l.strip().startswith('Script started')
                             and not l.strip().startswith('Script done')]
                    # Remove empty lines at start/end
                    while lines and not lines[0].strip():
                        lines.pop(0)
                    while lines and not lines[-1].strip():
                        lines.pop()
                    cleaned = '\n'.join(lines)
                    with open(output_log, 'w') as fout:
                        fout.write(cleaned)
                except Exception:
                    pass

            # Lynis returns the hardening index as exit code (e.g. 65)
            # Any non-negative code means the audit ran successfully
            if rc >= 0:
                _lynis_audit_progress = "completed"
            else:
                _lynis_audit_progress = f"error: {err[:200] if err else 'unknown error'}"
        except Exception as e:
            _lynis_audit_progress = f"error: {str(e)}"
        finally:
            _lynis_audit_running = False

    t = threading.Thread(target=_run_audit, daemon=True)
    t.start()
    return True, "Audit started"


def get_lynis_audit_status():
    """Get current audit status"""
    return {
        "running": _lynis_audit_running,
        "progress": _lynis_audit_progress,
    }


def parse_lynis_report():
    """
    Parse /var/log/lynis-report.dat into structured report data.
    Also enriches with data from lynis.log when report.dat is sparse.
    Returns a dict with all audit findings.
    """
    report_file = "/var/log/lynis-report.dat"
    output_file = "/var/log/lynis-output.log"
    # Need at least one data source
    if not os.path.isfile(report_file) and not os.path.isfile(output_file):
        return None

    report = {
        "datetime_start": "",
        "datetime_end": "",
        "lynis_version": "",
        "os_name": "",
        "os_version": "",
        "os_fullname": "",
        "hostname": "",
        "hardening_index": None,
        "tests_performed": 0,
        "warnings": [],
        "suggestions": [],
        "categories": {},
        "installed_packages": 0,
        "kernel_version": "",
        "firewall_active": False,
        "malware_scanner": False,
    }

    # Collect all raw key-value pairs first for flexible matching
    raw_data = {}
    warnings_raw = []
    suggestions_raw = []

    if os.path.isfile(report_file):
        try:
            with open(report_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("["):
                        continue

                    if "=" not in line:
                        continue

                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()

                    if key == "warning[]":
                        warnings_raw.append(value)
                    elif key == "suggestion[]":
                        suggestions_raw.append(value)
                    else:
                        # Last value wins (some keys appear multiple times)
                        raw_data[key] = value
        except Exception:
            pass  # Continue with output.log data

    # Map known fields (Lynis uses varied naming across versions)
    report["datetime_start"] = raw_data.get("report_datetime_start", "")
    report["datetime_end"] = raw_data.get("report_datetime_end", "")
    report["lynis_version"] = raw_data.get("lynis_version", "")
    report["hostname"] = raw_data.get("hostname", "")

    # OS name - try multiple fields
    report["os_name"] = (raw_data.get("os_name", "") or
                         raw_data.get("os", "") or
                         raw_data.get("os_fullname", ""))
    report["os_version"] = (raw_data.get("os_version", "") or
                            raw_data.get("os_version_id", ""))
    report["os_fullname"] = raw_data.get("os_fullname", "")

    # Kernel - try multiple field names
    report["kernel_version"] = (raw_data.get("os_kernel_version_full", "") or
                                raw_data.get("os_kernel_version", "") or
                                raw_data.get("linux_kernel_version", "") or
                                raw_data.get("linux_version", "") or
                                raw_data.get("os_kernelversion_full", "") or
                                raw_data.get("os_kernelversion", ""))

    # Hardening index
    for k in ["hardening_index", "hpindex", "hp_index"]:
        if k in raw_data:
            try:
                report["hardening_index"] = int(raw_data[k])
                break
            except ValueError:
                pass

    # Tests performed
    for k in ["tests_performed", "ctests_performed", "total_tests"]:
        if k in raw_data:
            try:
                val = int(raw_data[k])
                if val > report["tests_performed"]:
                    report["tests_performed"] = val
            except ValueError:
                pass

    # Installed packages
    for k in ["installed_packages", "installed_packages_array"]:
        if k in raw_data:
            try:
                report["installed_packages"] = int(raw_data[k])
            except ValueError:
                # Might be a string like "package1,package2" - count them
                pkgs = raw_data[k]
                if pkgs:
                    report["installed_packages"] = len(pkgs.split(","))

    # Firewall
    for k in ["firewall_active", "firewall_installed"]:
        if k in raw_data and raw_data[k] in ("1", "true", "yes"):
            report["firewall_active"] = True
            break

    # Malware scanner
    for k in ["malware_scanner_installed", "malware_scanner"]:
        if k in raw_data and raw_data[k] in ("1", "true", "yes"):
            report["malware_scanner"] = True
            break

    # Parse warnings
    for w in warnings_raw:
        parts = w.split("|")
        if len(parts) >= 2:
            report["warnings"].append({
                "test_id": parts[0].strip() if len(parts) > 0 else "",
                "severity": parts[1].strip() if len(parts) > 1 else "",
                "description": parts[2].strip() if len(parts) > 2 else parts[1].strip(),
                "solution": parts[3].strip() if len(parts) > 3 else "",
            })

    # Parse suggestions
    for s in suggestions_raw:
        parts = s.split("|")
        if len(parts) >= 2:
            report["suggestions"].append({
                "test_id": parts[0].strip() if len(parts) > 0 else "",
                "description": parts[1].strip() if len(parts) > 1 else "",
                "solution": parts[2].strip() if len(parts) > 2 else "",
                "details": parts[3].strip() if len(parts) > 3 else "",
            })

    # Parse lynis-output.log (stdout) for section checks, fallback to lynis.log
    report["sections"] = []
    # Prefer the stdout output which has clean formatted sections
    output_file = "/var/log/lynis-output.log"
    log_file = output_file if os.path.isfile(output_file) else "/var/log/lynis.log"
    if os.path.isfile(log_file):
        try:
            import re
            with open(log_file, 'r') as f:
                log_lines = f.readlines()

            current_section = None
            current_checks = []

            for line in log_lines:
                line = line.rstrip('\n')
                stripped = line.strip()

                # Detect section headers: "[+] Boot and services"
                # Use 'in' check first for speed, then regex for extraction
                if '[+]' in stripped:
                    section_match = re.search(r'\[\+\]\s+(.+)', stripped)
                    if section_match:
                        # Save previous section
                        if current_section and current_checks:
                            report["sections"].append({
                                "name": current_section,
                                "checks": current_checks,
                            })
                        current_section = section_match.group(1).strip()
                        # Remove trailing dashes from names like "Boot and services ------"
                        current_section = re.sub(r'\s*-+\s*$', '', current_section)
                        current_checks = []
                        continue

                # Skip separator lines, empty, banner lines
                if stripped.startswith('---') or not stripped:
                    continue
                if stripped.startswith('===') or stripped.startswith('#'):
                    current_section = None  # Stop parsing after results summary
                    continue

                # Detect any line with [ STATUS ] pattern (covers -, File:, Directory:, etc.)
                # After ANSI cleaning, cursor-positioning sequences are removed so
                # there may be only 1 space between the name and [ STATUS ].
                # Strategy: find the LAST occurrence of [ ... ] on the line.
                bracket_match = re.search(r'\[\s*([A-Za-z0-9_ /.:!-]+?)\s*\]\s*$', stripped)
                if bracket_match and current_section:
                    # Everything before the bracket is the check name
                    bracket_start = bracket_match.start()
                    check_name = stripped[:bracket_start].strip()
                    check_status = bracket_match.group(1).strip()
                    # Remove leading - or * from name
                    check_name = re.sub(r'^[-*]+\s*', '', check_name).strip()
                    # Skip noise lines (too short, dots-only, plugin progress)
                    if (check_name
                            and not check_name.startswith('..')
                            and len(check_name) > 2
                            and check_name not in ('..', '...', '....')):
                        current_checks.append({
                            "name": check_name,
                            "status": check_status,
                        })
                    continue

                # Detect sub-results: "      Result: found 35 running services"
                # After strip(), line becomes "Result: ..." (no leading spaces)
                if stripped.startswith("Result:") and current_section and current_checks:
                    detail = stripped[7:].strip()
                    if detail:
                        current_checks[-1]["detail"] = detail
                    continue

                # Extract key data from the info block and summary
                # Format: "Key:           value" or "Key : value"
                if ":" in stripped:
                    if not report["hardening_index"] and "Hardening index" in stripped:
                        m = re.search(r'Hardening index\s*:\s*(\d+)', stripped)
                        if m:
                            report["hardening_index"] = int(m.group(1))
                    elif report["tests_performed"] == 0 and "Tests performed" in stripped:
                        m = re.search(r'Tests performed\s*:\s*(\d+)', stripped)
                        if m:
                            report["tests_performed"] = int(m.group(1))
                    elif not report["kernel_version"] and "Kernel version" in stripped:
                        m = re.search(r'Kernel version\s*:\s*(.+)', stripped)
                        if m:
                            report["kernel_version"] = m.group(1).strip()
                    elif not report["hostname"] and stripped.startswith("Hostname"):
                        m = re.search(r'Hostname\s*:\s*(.+)', stripped)
                        if m:
                            val = m.group(1).strip()
                            if val and val != "N/A":
                                report["hostname"] = val
                    elif not report["os_name"] and "Operating system name" in stripped:
                        m = re.search(r'Operating system name\s*:\s*(.+)', stripped)
                        if m:
                            report["os_name"] = m.group(1).strip()
                    elif not report["os_version"] and "Operating system version" in stripped:
                        m = re.search(r'Operating system version\s*:\s*(.+)', stripped)
                        if m:
                            report["os_version"] = m.group(1).strip()
                    elif not report["os_fullname"] and "Operating system:" in stripped:
                        m = re.search(r'Operating system\s*:\s*(.+)', stripped)
                        if m:
                            report["os_fullname"] = m.group(1).strip()
                    elif not report["lynis_version"] and "Program version" in stripped:
                        m = re.search(r'Program version\s*:\s*(.+)', stripped)
                        if m:
                            report["lynis_version"] = m.group(1).strip()
                    elif not report["datetime_start"] and "report_datetime_start" in stripped:
                        pass  # already from .dat

            # Save last section
            if current_section and current_checks:
                report["sections"].append({
                    "name": current_section,
                    "checks": current_checks,
                })

            # Filter out sections with no meaningful checks
            report["sections"] = [
                s for s in report["sections"]
                if len(s["checks"]) > 0
            ]

            # Store debug info about parsing
            report["_parse_debug"] = {
                "source": log_file,
                "total_lines": len(log_lines),
                "sections_found": len(report["sections"]),
                "section_names": [s["name"] for s in report["sections"]],
            }

        except Exception as e:
            report["sections"] = []
            report["_parse_debug"] = {"error": str(e)}

    # Post-processing: extract firewall/malware status from parsed sections
    # This catches cases where report.dat doesn't have firewall_active but the
    # stdout shows "Checking host based firewall [ ACTIVE ]"
    if not report["firewall_active"] and report["sections"]:
        for section in report["sections"]:
            section_lower = section["name"].lower()
            if "firewall" in section_lower:
                for check in section["checks"]:
                    name_lower = check["name"].lower()
                    status_upper = check["status"].upper()
                    if "host based firewall" in name_lower or "checking host" in name_lower:
                        if status_upper in ("ACTIVE", "ENABLED", "FOUND", "OK"):
                            report["firewall_active"] = True
                            break
                    if "iptables" in name_lower and status_upper in ("ACTIVE", "FOUND", "OK"):
                        report["firewall_active"] = True
                        break
                if report["firewall_active"]:
                    break

    # Also check pve-firewall directly (Proxmox uses its own firewall service)
    if not report["firewall_active"]:
        try:
            rc, out, _ = _run_cmd(["systemctl", "is-active", "pve-firewall"])
            if rc == 0 and out.strip() == "active":
                report["firewall_active"] = True
        except Exception:
            pass

    # Extract malware scanner status from sections
    if not report["malware_scanner"] and report["sections"]:
        for section in report["sections"]:
            for check in section["checks"]:
                name_lower = check["name"].lower()
                status_upper = check["status"].upper()
                if any(x in name_lower for x in ["malware", "clamav", "rkhunter", "chkrootkit"]):
                    if status_upper in ("FOUND", "INSTALLED", "OK"):
                        report["malware_scanner"] = True
                        break
            if report["malware_scanner"]:
                break

    # Always parse lynis-output.log for warnings, suggestions, software
    # components. The report.dat is often sparse/empty on many systems.
    output_file = "/var/log/lynis-output.log"
    _log = output_file if os.path.isfile(output_file) else "/var/log/lynis.log"
    if os.path.isfile(_log):
        try:
            import re
            with open(_log, 'r') as f:
                stdout_lines = f.readlines()

            in_warnings = False
            in_suggestions = False
            in_software = False
            stdout_warnings = []
            stdout_suggestions = []
            last_suggestion = None

            for sline in stdout_lines:
                sline = sline.rstrip('\n')
                sstripped = sline.strip()

                # Detect "Warnings (N):" header
                if re.match(r'^Warnings\s*\(\d+\)\s*:', sstripped):
                    in_warnings = True
                    in_suggestions = False
                    in_software = False
                    last_suggestion = None
                    continue
                # Detect "Suggestions (N):" header
                if re.match(r'^Suggestions\s*\(\d+\)\s*:', sstripped):
                    in_suggestions = True
                    in_warnings = False
                    in_software = False
                    last_suggestion = None
                    continue
                # Detect "Software components:" section
                if "Software components:" in sstripped:
                    in_software = True
                    in_warnings = False
                    in_suggestions = False
                    last_suggestion = None
                    continue
                # End of sections on major separators
                if sstripped.startswith('==='):
                    in_warnings = False
                    in_suggestions = False
                    in_software = False
                    last_suggestion = None
                    continue

                # Parse "Software components" for firewall/malware
                # Format: "- Firewall               [V]" or "[X]"
                if in_software:
                    sw_match = re.match(r'^-\s+(.+?)\s+\[([VX])\]', sstripped)
                    if sw_match:
                        sw_name = sw_match.group(1).strip().lower()
                        sw_status = sw_match.group(2)
                        if "firewall" in sw_name and sw_status == "V":
                            report["firewall_active"] = True
                        if "malware" in sw_name and sw_status == "V":
                            report["malware_scanner"] = True

                # Parse warning lines: "! Warning text [TEST-ID]"
                if in_warnings and sstripped.startswith('!'):
                    wm = re.match(r'^!\s+(.+?)\s+\[([A-Z0-9_-]+)\]', sstripped)
                    if wm:
                        stdout_warnings.append({
                            "test_id": wm.group(2),
                            "severity": "Warning",
                            "description": wm.group(1).strip(),
                            "solution": "",
                        })

                # Parse suggestion lines: "* Suggestion text [TEST-ID]"
                if in_suggestions:
                    if sstripped.startswith('*'):
                        sm = re.match(r'^\*\s+(.+?)\s+\[([A-Z0-9_-]+)\]', sstripped)
                        if sm:
                            last_suggestion = {
                                "test_id": sm.group(2),
                                "description": sm.group(1).strip(),
                                "solution": "",
                                "details": "",
                            }
                            stdout_suggestions.append(last_suggestion)
                    elif last_suggestion and sstripped.startswith('- Details'):
                        dm = re.match(r'^-\s*Details\s*:\s*(.+)', sstripped)
                        if dm:
                            last_suggestion["details"] = dm.group(1).strip()
                    elif last_suggestion and sstripped.startswith('- Solution'):
                        sm2 = re.match(r'^-\s*Solution\s*:\s*(.+)', sstripped)
                        if sm2:
                            last_suggestion["solution"] = sm2.group(1).strip()

            # Use stdout data if report.dat had none
            if len(report["warnings"]) == 0 and stdout_warnings:
                report["warnings"] = stdout_warnings
            if len(report["suggestions"]) == 0 and stdout_suggestions:
                report["suggestions"] = stdout_suggestions

        except Exception:
            pass

    # Fallback: datetime from file modification time
    if not report["datetime_start"]:
        for fpath in ["/var/log/lynis-output.log", "/var/log/lynis-report.dat"]:
            if os.path.isfile(fpath):
                try:
                    import time
                    mtime = os.path.getmtime(fpath)
                    report["datetime_start"] = time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(mtime)
                    )
                    break
                except Exception:
                    pass

    # Fallback: get kernel from uname if still empty
    if not report["kernel_version"]:
        try:
            rc, out, _ = _run_cmd(["uname", "-r"])
            if rc == 0 and out.strip():
                report["kernel_version"] = out.strip()
        except Exception:
            pass

    # Fallback: get hostname from system
    if not report["hostname"]:
        try:
            import socket
            report["hostname"] = socket.gethostname()
        except Exception:
            pass

    # Fallback: get installed packages count
    if report["installed_packages"] == 0:
        try:
            rc, out, _ = _run_cmd(["dpkg", "-l"])
            if rc == 0 and out:
                # Count lines that start with "ii " (installed packages)
                count = sum(1 for l in out.splitlines() if l.startswith("ii "))
                if count > 0:
                    report["installed_packages"] = count
        except Exception:
            pass

    # ── Proxmox Context: classify warnings/suggestions ────────────────
    # Proxmox VE is a hypervisor with specific requirements that cause
    # Lynis to flag items that are normal/expected in this environment.
    # We classify each finding and calculate an adjusted score.

    PVE_WARNING_CONTEXT = {
        "FIRE-4512": {
            "reason": "Proxmox uses pve-firewall which manages iptables/nftables rules dynamically. Direct iptables rules are not used.",
            "expected": True,
        },
        "NETW-3015": {
            "reason": "Network bridges (vmbr*) operate in promiscuous mode by design to forward traffic between VMs/containers.",
            "expected": True,
        },
        "MAIL-8818": {
            "reason": "Postfix is used by Proxmox for system notifications. The SMTP banner can be customized but is low risk on an internal server.",
            "expected": False,
            "severity_override": "low",
        },
        "NETW-2705": {
            "reason": "Single DNS server is common in home/lab environments. Add a secondary DNS in /etc/resolv.conf if possible.",
            "expected": False,
            "severity_override": "low",
        },
        "PKGS-7392": {
            "reason": "Package updates should be applied regularly. Check if the 'vulnerable' packages are Proxmox-specific packages pending a PVE update.",
            "expected": False,
        },
    }

    PVE_SUGGESTION_CONTEXT = {
        "BOOT-5122": {
            "reason": "GRUB password is recommended for physical servers but less critical for headless/remote Proxmox nodes.",
            "expected": False,
            "severity_override": "low",
        },
        "BOOT-5264": {
            "reason": "Many Proxmox core services (pve-*, corosync, spiceproxy, etc.) run without systemd hardening. This is by design as they need broad system access.",
            "expected": True,
        },
        "KRNL-5788": {
            "reason": "Proxmox uses its own kernel (pve-kernel) which may not place vmlinuz in the standard location.",
            "expected": True,
        },
        "AUTH-9282": {
            "reason": "Proxmox system accounts (www-data, backup, etc.) don't use password expiry. Only applies to interactive user accounts.",
            "expected": True,
        },
        "AUTH-9284": {
            "reason": "Locked system accounts are normal in Proxmox (daemon, nobody, etc.).",
            "expected": True,
        },
        "USB-1000": {
            "reason": "USB passthrough to VMs may require USB drivers. Disable only if USB passthrough is not needed.",
            "expected": False,
            "severity_override": "low",
        },
        "STRG-1846": {
            "reason": "FireWire is typically not used in modern servers. Safe to disable.",
            "expected": False,
            "severity_override": "low",
        },
        "NETW-3200": {
            "reason": "Protocols dccp, sctp, rds, tipc are typically not needed. Can be disabled via modprobe blacklist.",
            "expected": False,
        },
        "SSH-7408": {
            "reason": "SSH hardening is recommended but PermitRootLogin is required for Proxmox API/CLI management. Other SSH settings can be tuned.",
            "expected": False,
        },
        "FILE-6310": {
            "reason": "Separate partitions for /home and /var are best practice but Proxmox typically uses a simple partition layout with LVM-thin for VM storage.",
            "expected": True,
        },
        "KRNL-6000": {
            "reason": "Some sysctl values differ because Proxmox needs IP forwarding, bridge-nf-call, and relaxed kernel settings for VM/container networking.",
            "expected": True,
        },
        "HRDN-7230": {
            "reason": "A malware scanner (rkhunter, ClamAV) is recommended but optional for a dedicated hypervisor.",
            "expected": False,
            "severity_override": "low",
        },
        "HRDN-7222": {
            "reason": "Restricting compiler access is good practice on production servers. Less critical on a hypervisor where only root has access.",
            "expected": False,
            "severity_override": "low",
        },
        "FINT-4350": {
            "reason": "File integrity monitoring (AIDE, Tripwire) is recommended for production but optional for home/lab environments.",
            "expected": False,
            "severity_override": "low",
        },
        "ACCT-9622": {
            "reason": "Process accounting is useful for forensics but not required for a hypervisor.",
            "expected": False,
            "severity_override": "low",
        },
        "ACCT-9626": {
            "reason": "Sysstat is useful for performance monitoring but not a security requirement.",
            "expected": False,
            "severity_override": "low",
        },
        "ACCT-9628": {
            "reason": "Auditd provides detailed audit logging. Recommended for production, optional for home/lab.",
            "expected": False,
            "severity_override": "low",
        },
        "TOOL-5002": {
            "reason": "Automation tools (Ansible, Puppet) are useful for multi-node clusters but not required for single-node setups.",
            "expected": True,
        },
        "LOGG-2154": {
            "reason": "External logging is recommended for production but optional for single-node environments.",
            "expected": False,
            "severity_override": "low",
        },
        "BANN-7126": {
            "reason": "Legal banners in /etc/issue are recommended for compliance but not a security risk.",
            "expected": False,
            "severity_override": "low",
        },
        "BANN-7130": {
            "reason": "Legal banners in /etc/issue.net are recommended for compliance but not a security risk.",
            "expected": False,
            "severity_override": "low",
        },
    }

    # Apply Proxmox context to warnings
    pve_expected_warnings = 0
    for w in report["warnings"]:
        tid = w.get("test_id", "")
        ctx = PVE_WARNING_CONTEXT.get(tid)
        if ctx:
            w["proxmox_context"] = ctx["reason"]
            w["proxmox_expected"] = ctx.get("expected", False)
            if ctx.get("severity_override"):
                w["proxmox_severity"] = ctx["severity_override"]
            if ctx.get("expected", False):
                pve_expected_warnings += 1
        else:
            w["proxmox_context"] = ""
            w["proxmox_expected"] = False

    # Apply Proxmox context to suggestions
    pve_expected_suggestions = 0
    for s in report["suggestions"]:
        tid = s.get("test_id", "")
        ctx = PVE_SUGGESTION_CONTEXT.get(tid)
        if ctx:
            s["proxmox_context"] = ctx["reason"]
            s["proxmox_expected"] = ctx.get("expected", False)
            if ctx.get("severity_override"):
                s["proxmox_severity"] = ctx["severity_override"]
            if ctx.get("expected", False):
                pve_expected_suggestions += 1
        else:
            s["proxmox_context"] = ""
            s["proxmox_expected"] = False

    # Calculate Proxmox-adjusted score
    # Lynis score is based on total tests and findings.
    # We boost the score proportionally to the expected items.
    raw_score = report["hardening_index"] or 0
    total_findings = len(report["warnings"]) + len(report["suggestions"])
    expected_findings = pve_expected_warnings + pve_expected_suggestions
    if total_findings > 0 and raw_score > 0:
        # Each finding roughly reduces the score. Expected findings should
        # not penalize. We estimate the boost proportionally.
        penalty_per_finding = (100 - raw_score) / max(total_findings, 1)
        boost = int(penalty_per_finding * expected_findings * 0.8)
        adjusted_score = min(100, raw_score + boost)
    else:
        adjusted_score = raw_score

    report["proxmox_adjusted_score"] = adjusted_score
    report["proxmox_expected_warnings"] = pve_expected_warnings
    report["proxmox_expected_suggestions"] = pve_expected_suggestions
    report["proxmox_context_applied"] = True

    return report
