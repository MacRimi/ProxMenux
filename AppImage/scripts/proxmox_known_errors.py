#!/usr/bin/env python3
"""
Database of known Proxmox/Linux errors with causes, solutions, and severity levels.

This provides the AI with accurate, pre-verified information about common errors,
reducing hallucinations and ensuring consistent, helpful responses.

Each entry includes:
- pattern: regex pattern to match against error messages/logs
- cause: brief explanation of what causes this error
- cause_detailed: more comprehensive explanation for detailed mode
- severity: info, warning, critical
- solution: brief actionable solution
- solution_detailed: step-by-step solution for detailed mode
- url: optional documentation link
"""

import re
from typing import Optional, Dict, Any, List

# Known error patterns with causes and solutions
PROXMOX_KNOWN_ERRORS: List[Dict[str, Any]] = [
    # ==================== SUBSCRIPTION/LICENSE ====================
    {
        "pattern": r"no valid subscription|subscription.*invalid|not subscribed",
        "cause": "Proxmox enterprise repository requires paid subscription",
        "cause_detailed": "Proxmox VE uses a subscription model for enterprise features. Without a valid subscription key, access to the enterprise repository is denied. This is normal for home/lab users.",
        "severity": "info",
        "solution": "Use no-subscription repository or purchase subscription",
        "solution_detailed": "For home/lab use: Switch to the no-subscription repository by editing /etc/apt/sources.list.d/pve-enterprise.list. For production: Purchase a subscription at proxmox.com/pricing",
        "url": "https://pve.proxmox.com/wiki/Package_Repositories",
        "category": "updates"
    },
    
    # ==================== CLUSTER/COROSYNC ====================
    {
        "pattern": r"quorum.*lost|lost.*quorum|not.*quorate",
        "cause": "Cluster lost majority of voting nodes",
        "cause_detailed": "Corosync cluster requires more than 50% of configured votes to maintain quorum. When quorum is lost, the cluster becomes read-only to prevent split-brain scenarios.",
        "severity": "critical",
        "solution": "Check network connectivity between nodes; ensure majority of nodes are online",
        "solution_detailed": "1. Verify network connectivity: ping all cluster nodes\n2. Check corosync status: systemctl status corosync\n3. View cluster status: pvecm status\n4. If nodes are unreachable, check firewall rules (ports 5405-5412 UDP)\n5. For emergency single-node operation: pvecm expected 1",
        "url": "https://pve.proxmox.com/wiki/Cluster_Manager",
        "category": "cluster"
    },
    {
        "pattern": r"corosync.*qdevice.*error|qdevice.*connection.*failed|qdevice.*not.*connected",
        "cause": "QDevice helper node is unreachable",
        "cause_detailed": "The Corosync QDevice provides an additional vote for 2-node clusters. When it cannot connect, the cluster may lose quorum if one node fails.",
        "severity": "warning",
        "solution": "Check QDevice server connectivity and corosync-qnetd service",
        "solution_detailed": "1. Verify QDevice server is running: systemctl status corosync-qnetd (on QDevice host)\n2. Check connectivity: nc -zv <qdevice-ip> 5403\n3. Restart qdevice: systemctl restart corosync-qdevice\n4. Check certificates: corosync-qdevice-net-certutil -s",
        "url": "https://pve.proxmox.com/wiki/Cluster_Manager#_corosync_external_vote_support",
        "category": "cluster"
    },
    {
        "pattern": r"corosync.*retransmit|corosync.*token.*timeout|ring.*mark.*faulty",
        "cause": "Network latency or packet loss between cluster nodes",
        "cause_detailed": "Corosync uses multicast/unicast for cluster communication. High latency, packet loss, or network congestion causes token timeouts and retransmissions, potentially leading to node eviction.",
        "severity": "warning",
        "solution": "Check network quality between nodes; consider increasing token timeout",
        "solution_detailed": "1. Test network latency: ping -c 100 <other-node>\n2. Check for packet loss between nodes\n3. Verify MTU settings match on all interfaces\n4. Increase token timeout in /etc/pve/corosync.conf if needed (default 1000ms)\n5. Check switch/router for congestion",
        "category": "cluster"
    },
    
    # ==================== DISK/STORAGE ====================
    {
        "pattern": r"SMART.*FAILED|smart.*failed.*health|Pre-fail|Old_age.*FAILING",
        "cause": "Disk SMART health check failed - disk is failing",
        "cause_detailed": "SMART (Self-Monitoring, Analysis and Reporting Technology) detected critical disk health issues. The disk is likely failing and data loss is imminent.",
        "severity": "critical",
        "solution": "IMMEDIATELY backup data and replace disk",
        "solution_detailed": "1. URGENT: Backup all data from this disk immediately\n2. Check SMART details: smartctl -a /dev/sdX\n3. Note the failing attributes (Reallocated_Sector_Ct, Current_Pending_Sector, etc.)\n4. Plan disk replacement\n5. If in RAID/ZFS: initiate disk replacement procedure",
        "category": "disks"
    },
    {
        "pattern": r"Reallocated_Sector_Ct.*threshold|reallocated.*sectors?.*exceeded",
        "cause": "Disk has excessive bad sectors being remapped",
        "cause_detailed": "The disk firmware has remapped multiple bad sectors to spare areas. While the disk is still functioning, this indicates physical degradation and eventual failure.",
        "severity": "warning",
        "solution": "Monitor closely and plan disk replacement",
        "solution_detailed": "1. Check current value: smartctl -A /dev/sdX | grep Reallocated\n2. If value is increasing, plan immediate replacement\n3. Backup important data\n4. Run extended SMART test: smartctl -t long /dev/sdX",
        "category": "disks"
    },
    {
        "pattern": r"\bata\d.*\berror\b|\bATA\b.*bus.*error|Emask.*0x|DRDY.*ERR|\bUNC\b.*error",
        "cause": "ATA communication error with disk",
        "cause_detailed": "The SATA/ATA controller encountered communication errors with the disk. This can indicate cable issues, controller problems, or disk failure.",
        "severity": "warning",
        "solution": "Check SATA cables and connections; verify disk health with smartctl",
        "solution_detailed": "1. Check SMART health: smartctl -H /dev/sdX\n2. Inspect and reseat SATA cables\n3. Try different SATA port\n4. Check dmesg for pattern of errors\n5. If errors persist, disk may be failing",
        "category": "disks"
    },
    {
        "pattern": r"I/O.*error|blk_update_request.*error|Buffer I/O error",
        "cause": "Disk I/O operation failed",
        "cause_detailed": "The kernel failed to read or write data to the disk. This can be caused by disk failure, cable issues, or filesystem corruption.",
        "severity": "critical",
        "solution": "Check disk health and connections immediately",
        "solution_detailed": "1. Check SMART status: smartctl -H /dev/sdX\n2. Check dmesg for related errors: dmesg | grep -i error\n3. Verify disk is still accessible: lsblk\n4. If ZFS: check pool status with zpool status\n5. Consider filesystem check if safe to unmount",
        "category": "disks"
    },
    {
        "pattern": r"zfs.*pool.*DEGRADED|pool.*is.*degraded",
        "cause": "ZFS pool has reduced redundancy",
        "cause_detailed": "One or more devices in the ZFS pool are unavailable or experiencing errors. The pool is still functional but without full redundancy.",
        "severity": "warning",
        "solution": "Identify failed device with 'zpool status' and replace",
        "solution_detailed": "1. Check pool status: zpool status <pool>\n2. Identify the DEGRADED or UNAVAIL device\n3. If device is present but erroring: zpool scrub <pool>\n4. To replace: zpool replace <pool> <old-device> <new-device>\n5. Monitor resilver progress: zpool status",
        "category": "storage"
    },
    {
        "pattern": r"zfs.*pool.*FAULTED|pool.*is.*faulted",
        "cause": "ZFS pool is inaccessible",
        "cause_detailed": "The ZFS pool has lost too many devices and cannot maintain data integrity. Data may be inaccessible.",
        "severity": "critical",
        "solution": "Check failed devices; may need data recovery",
        "solution_detailed": "1. Check status: zpool status <pool>\n2. Identify all failed devices\n3. Attempt to online devices: zpool online <pool> <device>\n4. If drives are physically present, try zpool clear <pool>\n5. May require data recovery if multiple drives failed",
        "category": "storage"
    },
    
    # ==================== CEPH ====================
    {
        "pattern": r"ceph.*OSD.*down|osd\.\d+.*down|ceph.*osd.*failed",
        "cause": "Ceph OSD daemon is not running",
        "cause_detailed": "A Ceph Object Storage Daemon (OSD) has stopped or crashed. This reduces storage redundancy and may trigger data rebalancing.",
        "severity": "warning",
        "solution": "Check disk health and restart OSD service",
        "solution_detailed": "1. Check OSD status: ceph osd tree\n2. View OSD logs: journalctl -u ceph-osd@<id>\n3. Check underlying disk: smartctl -H /dev/sdX\n4. Restart OSD: systemctl start ceph-osd@<id>\n5. If OSD keeps crashing, check for disk failure",
        "category": "storage"
    },
    {
        "pattern": r"ceph.*health.*WARN|HEALTH_WARN",
        "cause": "Ceph cluster has warnings",
        "cause_detailed": "Ceph detected issues that don't prevent operation but should be addressed. Common causes: degraded PGs, clock skew, full OSDs.",
        "severity": "warning",
        "solution": "Run 'ceph health detail' for specific issues",
        "solution_detailed": "1. Get details: ceph health detail\n2. Common fixes:\n   - Degraded PGs: wait for recovery or add capacity\n   - Clock skew: sync NTP on all nodes\n   - Full OSDs: add storage or delete data\n3. Check: ceph status",
        "category": "storage"
    },
    {
        "pattern": r"ceph.*health.*ERR|HEALTH_ERR",
        "cause": "Ceph cluster has critical errors",
        "cause_detailed": "Ceph has detected critical issues that may affect data availability or integrity. Immediate attention required.",
        "severity": "critical",
        "solution": "Run 'ceph health detail' and address errors immediately",
        "solution_detailed": "1. Get details: ceph health detail\n2. Check OSD status: ceph osd tree\n3. Check MON status: ceph mon stat\n4. View PG status: ceph pg stat\n5. Address each error shown in health detail",
        "category": "storage"
    },
    
    # ==================== VM/CT ERRORS ====================
    {
        "pattern": r"TASK ERROR.*failed to get exclusive lock|lock.*timeout|couldn't acquire lock",
        "cause": "Resource is locked by another operation",
        "cause_detailed": "Another task is currently holding a lock on this VM/CT. This prevents concurrent modifications that could cause corruption.",
        "severity": "info",
        "solution": "Wait for other task to complete or check for stuck tasks",
        "solution_detailed": "1. Check running tasks: cat /var/log/pve/tasks/active\n2. Wait for task completion\n3. If task is stuck (>1h), check process: ps aux | grep <vmid>\n4. As last resort, remove lock file: rm /var/lock/qemu-server/lock-<vmid>.conf",
        "category": "vms"
    },
    {
        "pattern": r"kvm.*not.*available|kvm.*disabled|hardware.*virtualization.*disabled",
        "cause": "KVM/hardware virtualization not available",
        "cause_detailed": "The CPU's hardware virtualization extensions (Intel VT-x or AMD-V) are either not supported, not enabled in BIOS, or blocked by another hypervisor.",
        "severity": "warning",
        "solution": "Enable VT-x/AMD-V in BIOS settings",
        "solution_detailed": "1. Reboot into BIOS/UEFI\n2. Find Virtualization settings (often in CPU or Advanced section)\n3. Enable Intel VT-x or AMD-V/SVM\n4. Save and reboot\n5. Verify: grep -E 'vmx|svm' /proc/cpuinfo",
        "category": "vms"
    },
    {
        "pattern": r"out of memory|OOM.*kill|cannot allocate memory|memory.*exhausted",
        "cause": "System or VM ran out of memory",
        "cause_detailed": "The Linux OOM (Out Of Memory) killer terminated a process to free memory. This indicates memory pressure from overcommitment or memory leaks.",
        "severity": "critical",
        "solution": "Increase memory allocation or reduce VM memory usage",
        "solution_detailed": "1. Check what was killed: dmesg | grep -i oom\n2. Review memory usage: free -h\n3. Check balloon driver status for VMs\n4. Consider adding swap or RAM\n5. Review VM memory allocations for overcommitment",
        "category": "memory"
    },
    
    # ==================== NETWORK ====================
    {
        "pattern": r"bond.*slave.*link.*down|bond.*no.*active.*slave",
        "cause": "Network bond lost a slave interface",
        "cause_detailed": "One or more physical interfaces in a network bond have lost link. Depending on bond mode, this may reduce bandwidth or affect failover.",
        "severity": "warning",
        "solution": "Check physical cable connections and switch ports",
        "solution_detailed": "1. Check bond status: cat /proc/net/bonding/bond0\n2. Identify down slave interface\n3. Check physical cable connection\n4. Check switch port status and errors\n5. Verify interface: ethtool <slave-iface>",
        "category": "network"
    },
    {
        "pattern": r"link.*not.*ready|carrier.*lost|link.*down|NIC.*Link.*Down",
        "cause": "Network interface lost link",
        "cause_detailed": "The physical or virtual network interface has lost its connection. This could be a cable issue, switch problem, or driver issue.",
        "severity": "warning",
        "solution": "Check cable, switch port, and interface status",
        "solution_detailed": "1. Check interface: ip link show <iface>\n2. Check cable connection\n3. Check switch port LEDs\n4. Try: ip link set <iface> down && ip link set <iface> up\n5. Check driver: ethtool -i <iface>",
        "category": "network"
    },
    {
        "pattern": r"bridge.*STP.*blocked|spanning.*tree.*blocked",
        "cause": "Spanning Tree Protocol blocked a port",
        "cause_detailed": "STP detected a potential network loop and blocked a bridge port to prevent broadcast storms. This is normal behavior but may indicate network topology issues.",
        "severity": "info",
        "solution": "Review network topology; this may be expected behavior",
        "solution_detailed": "1. Check bridge status: brctl show\n2. View STP state: brctl showstp <bridge>\n3. If unexpected, review network topology for loops\n4. Consider disabling STP if network is simple: brctl stp <bridge> off",
        "category": "network"
    },
    
    # ==================== SERVICES ====================
    {
        "pattern": r"pvedaemon.*failed|pveproxy.*failed|pvestatd.*failed",
        "cause": "Critical Proxmox service failed",
        "cause_detailed": "One of the core Proxmox daemons has crashed or failed to start. This may affect web GUI access or API functionality.",
        "severity": "critical",
        "solution": "Restart the failed service; check logs for cause",
        "solution_detailed": "1. Check status: systemctl status <service>\n2. View logs: journalctl -u <service> -n 50\n3. Restart: systemctl restart <service>\n4. If persistent, check: /var/log/pveproxy/access.log",
        "category": "pve_services"
    },
    {
        "pattern": r"failed to start.*service|service.*start.*failed|service.*activation.*failed",
        "cause": "System service failed to start",
        "cause_detailed": "A systemd service unit failed during startup. This could be due to configuration errors, missing dependencies, or resource issues.",
        "severity": "warning",
        "solution": "Check service logs with journalctl -u <service>",
        "solution_detailed": "1. Check status: systemctl status <service>\n2. View logs: journalctl -xeu <service>\n3. Check config: systemctl cat <service>\n4. Verify dependencies: systemctl list-dependencies <service>\n5. Try restart: systemctl restart <service>",
        "category": "services"
    },
    
    # ==================== BACKUP ====================
    {
        "pattern": r"backup.*failed|vzdump.*error|backup.*job.*failed",
        "cause": "Backup job failed",
        "cause_detailed": "A scheduled or manual backup operation failed. Common causes: storage full, VM locked, network issues for remote storage.",
        "severity": "warning",
        "solution": "Check backup storage space and VM status",
        "solution_detailed": "1. Check backup log in Datacenter > Backup\n2. Verify storage space: df -h\n3. Check if VM is locked: qm list or pct list\n4. Verify backup storage is accessible\n5. Try manual backup to identify specific error",
        "category": "backups"
    },
    
    # ==================== CERTIFICATES ====================
    {
        "pattern": r"certificate.*expired|SSL.*certificate.*expired|cert.*expir",
        "cause": "SSL/TLS certificate has expired",
        "cause_detailed": "An SSL certificate used for secure communication has passed its expiration date. This may cause connection failures or security warnings.",
        "severity": "warning",
        "solution": "Renew the certificate using pvenode cert set or Let's Encrypt",
        "solution_detailed": "1. Check certificate: pvenode cert info\n2. For self-signed renewal: pvecm updatecerts\n3. For Let's Encrypt: pvenode acme cert order\n4. Restart pveproxy after renewal: systemctl restart pveproxy",
        "url": "https://pve.proxmox.com/wiki/Certificate_Management",
        "category": "security"
    },
    
    # ==================== HARDWARE/TEMPERATURE ====================
    {
        "pattern": r"temperature.*critical|thermal.*critical|CPU.*overheating|temp.*above.*threshold",
        "cause": "Component temperature critical",
        "cause_detailed": "A hardware component (CPU, disk, etc.) has reached a dangerous temperature. Sustained high temperatures can cause hardware damage or system shutdowns.",
        "severity": "critical",
        "solution": "Check cooling system immediately; clean dust, verify fans",
        "solution_detailed": "1. Check current temps: sensors\n2. Verify all fans are running\n3. Clean dust from heatsinks and filters\n4. Ensure adequate airflow\n5. Consider reapplying thermal paste if CPU\n6. Check ambient room temperature",
        "category": "temperature"
    },
    
    # ==================== AUTHENTICATION ====================
    {
        "pattern": r"authentication.*failed|login.*failed|invalid.*credentials|access.*denied",
        "cause": "Authentication failure",
        "cause_detailed": "A login attempt failed due to invalid credentials or permissions. Multiple failures may indicate a brute-force attack.",
        "severity": "info",
        "solution": "Verify credentials; check for unauthorized access attempts",
        "solution_detailed": "1. Review auth logs: journalctl -u pvedaemon | grep auth\n2. Check for multiple failures from same IP\n3. Verify user exists: pveum user list\n4. If attack suspected, consider fail2ban\n5. Reset password if needed: pveum passwd <user>",
        "category": "security"
    },
]


def find_matching_error(text: str, category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Find a known error that matches the given text.
    
    Args:
        text: Error message or log content to match against
        category: Optional category to filter by
        
    Returns:
        Matching error dict or None
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    for error in PROXMOX_KNOWN_ERRORS:
        # Filter by category if specified
        if category and error.get("category") != category:
            continue
            
        try:
            if re.search(error["pattern"], text_lower, re.IGNORECASE):
                return error
        except re.error:
            continue
    
    return None


def get_error_context(text: str, category: Optional[str] = None, detail_level: str = "standard") -> Optional[str]:
    """Get formatted context for a known error.
    
    Args:
        text: Error message to match
        category: Optional category filter
        detail_level: "minimal", "standard", or "detailed"
        
    Returns:
        Formatted context string or None
    """
    error = find_matching_error(text, category)
    if not error:
        return None
    
    if detail_level == "minimal":
        return f"Known issue: {error['cause']}"
    
    elif detail_level == "standard":
        lines = [
            f"KNOWN PROXMOX ERROR DETECTED:",
            f"  Cause: {error['cause']}",
            f"  Severity: {error['severity'].upper()}",
            f"  Solution: {error['solution']}"
        ]
        if error.get("url"):
            lines.append(f"  Docs: {error['url']}")
        return "\n".join(lines)
    
    else:  # detailed
        lines = [
            f"KNOWN PROXMOX ERROR DETECTED:",
            f"  Cause: {error.get('cause_detailed', error['cause'])}",
            f"  Severity: {error['severity'].upper()}",
            f"  Solution: {error.get('solution_detailed', error['solution'])}"
        ]
        if error.get("url"):
            lines.append(f"  Documentation: {error['url']}")
        return "\n".join(lines)


def get_all_patterns() -> List[str]:
    """Get all error patterns for external use."""
    return [error["pattern"] for error in PROXMOX_KNOWN_ERRORS]
