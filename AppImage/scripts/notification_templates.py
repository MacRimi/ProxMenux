"""
ProxMenux Notification Templates
Message templates for all event types with per-channel formatting.

Templates use Python str.format() variables:
  {hostname}, {severity}, {category}, {reason}, {summary},
  {previous}, {current}, {vmid}, {vmname}, {timestamp}, etc.

Optional AI enhancement enriches messages with context/suggestions.

Author: MacRimi
"""

import json
import re
import socket
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List, Tuple


# ─── vzdump message parser ───────────────────────────────────────

def _parse_vzdump_message(message: str) -> Optional[Dict[str, Any]]:
    """Parse a PVE vzdump notification message into structured data.
    
    Supports two formats:
    1. Local storage: table with columns VMID Name Status Time Size Filename
    2. PBS storage: log-style output with 'Finished Backup of VM NNN (HH:MM:SS)'
       and sizes in lines like 'root.pxar: had to backup X of Y' or 'transferred X'
    
    Returns dict with 'vms' list, 'total_time', 'total_size', or None.
    """
    if not message:
        return None
    
    vms: List[Dict[str, str]] = []
    total_time = ''
    total_size = ''
    
    lines = message.split('\n')
    
    # ── Strategy 1: classic table (local/NFS/CIFS storage) ──
    header_idx = -1
    for i, line in enumerate(lines):
        if re.match(r'\s*VMID\s+Name\s+Status', line, re.IGNORECASE):
            header_idx = i
            break
    
    if header_idx >= 0:
        # Use column positions from the header to slice each row.
        # Header: "VMID    Name           Status    Time      Size          Filename"
        header = lines[header_idx]
        col_starts = []
        for col_name in ['VMID', 'Name', 'Status', 'Time', 'Size', 'Filename']:
            idx = header.find(col_name)
            if idx >= 0:
                col_starts.append(idx)
        
        if len(col_starts) == 6:
            for line in lines[header_idx + 1:]:
                stripped = line.strip()
                if not stripped or stripped.startswith('Total') or stripped.startswith('Logs') or stripped.startswith('='):
                    break
                # Pad line to avoid index errors
                padded = line.ljust(col_starts[-1] + 50)
                vmid = padded[col_starts[0]:col_starts[1]].strip()
                name = padded[col_starts[1]:col_starts[2]].strip()
                status = padded[col_starts[2]:col_starts[3]].strip()
                time_val = padded[col_starts[3]:col_starts[4]].strip()
                size = padded[col_starts[4]:col_starts[5]].strip()
                filename = padded[col_starts[5]:].strip()
                
                if vmid and vmid.isdigit():
                    # Infer type from filename (vzdump-lxc-NNN or vzdump-qemu-NNN)
                    vm_type = ''
                    if 'lxc' in filename:
                        vm_type = 'lxc'
                    elif 'qemu' in filename:
                        vm_type = 'qemu'
                    vms.append({
                        'vmid': vmid,
                        'name': name,
                        'status': status,
                        'time': time_val,
                        'size': size,
                        'filename': filename,
                        'type': vm_type,
                    })
    
    # ── Strategy 2: log-style (PBS / Proxmox Backup Server) ──
    # Parse from the full vzdump log lines.
    # Look for patterns:
    #   "Starting Backup of VM NNN (lxc/qemu)"  -> detect guest
    #   "CT Name: xxx" or "VM Name: xxx"         -> guest name
    #   "Finished Backup of VM NNN (HH:MM:SS)"   -> duration + status=ok
    #   "root.pxar: had to backup X of Y"         -> size (CT)
    #   "transferred X in N seconds"              -> size (QEMU)
    #   "creating ... archive 'ct/100/2026-..'"   -> archive name for PBS
    #   "TASK ERROR:" or "ERROR:"                 -> status=error
    if not vms:
        current_vm: Optional[Dict[str, str]] = None
        
        for line in lines:
            # Remove "INFO: " prefix that PVE adds
            clean = re.sub(r'^(?:INFO|WARNING|ERROR):\s*', '', line.strip())
            
            # Start of a new VM backup
            m_start = re.match(
                r'Starting Backup of VM (\d+)\s+\((lxc|qemu)\)', clean)
            if m_start:
                if current_vm:
                    vms.append(current_vm)
                current_vm = {
                    'vmid': m_start.group(1),
                    'name': '',
                    'status': 'ok',
                    'time': '',
                    'size': '',
                    'filename': '',
                    'type': m_start.group(2),
                }
                continue
            
            if current_vm:
                # Guest name
                m_name = re.match(r'(?:CT|VM) Name:\s*(.+)', clean)
                if m_name:
                    current_vm['name'] = m_name.group(1).strip()
                    continue
                
                # PBS archive path -> extract as filename
                m_archive = re.search(
                    r"creating .+ archive '([^']+)'", clean)
                if m_archive:
                    current_vm['filename'] = m_archive.group(1)
                    continue
                
                # Size for containers (pxar)
                m_pxar = re.search(
                    r'root\.pxar:.*?of\s+([\d.]+\s+\S+)', clean)
                if m_pxar:
                    current_vm['size'] = m_pxar.group(1)
                    continue
                
                # Size for QEMU (transferred)
                m_transfer = re.search(
                    r'transferred\s+([\d.]+\s+\S+)', clean)
                if m_transfer:
                    current_vm['size'] = m_transfer.group(1)
                    continue
                
                # Finished -> duration
                m_finish = re.match(
                    r'Finished Backup of VM (\d+)\s+\(([^)]+)\)', clean)
                if m_finish:
                    current_vm['time'] = m_finish.group(2)
                    current_vm['status'] = 'ok'
                    vms.append(current_vm)
                    current_vm = None
                    continue
                
                # Error
                if clean.startswith('ERROR:') or clean.startswith('TASK ERROR'):
                    if current_vm:
                        current_vm['status'] = 'error'
        
        # Don't forget the last VM if it wasn't finished
        if current_vm:
            vms.append(current_vm)
    
    # ── Extract totals ──
    for line in lines:
        m_time = re.search(r'Total running time:\s*(.+)', line)
        if m_time:
            total_time = m_time.group(1).strip()
        m_size = re.search(r'Total size:\s*(.+)', line)
        if m_size:
            total_size = m_size.group(1).strip()
    
    # For PBS: calculate total size if not explicitly stated
    if not total_size and vms:
        # Sum individual sizes if they share units
        sizes_gib = 0.0
        for vm in vms:
            s = vm.get('size', '')
            m = re.match(r'([\d.]+)\s+(.*)', s)
            if m:
                val = float(m.group(1))
                unit = m.group(2).strip().upper()
                if 'GIB' in unit or 'GB' in unit:
                    sizes_gib += val
                elif 'MIB' in unit or 'MB' in unit:
                    sizes_gib += val / 1024
                elif 'TIB' in unit or 'TB' in unit:
                    sizes_gib += val * 1024
        if sizes_gib > 0:
            if sizes_gib >= 1024:
                total_size = f"{sizes_gib / 1024:.3f} TiB"
            elif sizes_gib >= 1:
                total_size = f"{sizes_gib:.3f} GiB"
            else:
                total_size = f"{sizes_gib * 1024:.3f} MiB"
    
    # For PBS: calculate total time if not stated
    if not total_time and vms:
        total_secs = 0
        for vm in vms:
            t = vm.get('time', '')
            # Parse HH:MM:SS format
            m = re.match(r'(\d+):(\d+):(\d+)', t)
            if m:
                total_secs += int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        if total_secs > 0:
            hours = total_secs // 3600
            mins = (total_secs % 3600) // 60
            secs = total_secs % 60
            if hours:
                total_time = f"{hours}h {mins}m {secs}s"
            elif mins:
                total_time = f"{mins}m {secs}s"
            else:
                total_time = f"{secs}s"
    
    # ── Extract the storage target name (PBS, PBS-Cloud, local, …) ──
    # PVE logs the full command on the first line:
    #   "INFO: starting new backup job: vzdump 104 105 --storage PBS-Cloud --mode stop"
    # We surface it so the notification body can say "PBS-Cloud: vm/104/…"
    # instead of the generic "PBS:" prefix when multiple PBS endpoints
    # are configured. Reported by JC Miñarro 18/05.
    storage_name = ''
    for line in lines:
        m_storage = re.search(r'--storage\s+(\S+)', line)
        if m_storage:
            storage_name = m_storage.group(1).strip()
            break

    if not vms and not total_size:
        return None

    return {
        'vms': vms,
        'total_time': total_time,
        'total_size': total_size,
        'vm_count': len(vms),
        'storage_name': storage_name,
    }


def _format_vzdump_body(parsed: Dict[str, Any], is_success: bool) -> str:
    """Format parsed vzdump data into a clean Telegram-friendly message."""
    parts = []
    
    for vm in parsed.get('vms', []):
        status = vm.get('status', '').lower()
        icon = '\u2705' if status == 'ok' else '\u274C'
        
        # Determine VM/CT type prefix
        vm_type = vm.get('type', '')
        if vm_type == 'lxc':
            prefix = 'CT'
        elif vm_type == 'qemu':
            prefix = 'VM'
        else:
            # Try to infer from filename (vzdump-lxc-NNN or vzdump-qemu-NNN)
            fname = vm.get('filename', '')
            if 'lxc' in fname or fname.startswith('ct/'):
                prefix = 'CT'
            elif 'qemu' in fname or fname.startswith('vm/'):
                prefix = 'VM'
            else:
                prefix = ''
        
        # Format: "VM Name (ID)" or "CT Name (ID)" -- name first
        name = vm.get('name', '')
        vmid = vm.get('vmid', '')
        if prefix and name:
            parts.append(f"{icon} {prefix} {name} ({vmid})")
        elif name:
            parts.append(f"{icon} {name} ({vmid})")
        else:
            parts.append(f"{icon} ID {vmid}")
        
        # Size and Duration on same line with icons
        detail_line = []
        if vm.get('size'):
            detail_line.append(f"\U0001F4CF Size: {vm['size']}")
        if vm.get('time'):
            detail_line.append(f"\u23F1\uFE0F Duration: {vm['time']}")
        if detail_line:
            parts.append(' | '.join(detail_line))
        
        # PBS/File on separate line with icon. When we know the
        # storage name (e.g. "PBS-Cloud", "PBS-Office") prefix it so
        # the user can tell which destination this archive lives in \u2014
        # critical when there are multiple PBS endpoints configured.
        if vm.get('filename'):
            fname = vm['filename']
            storage_name = parsed.get('storage_name', '') or ''
            if re.match(r'^(?:ct|vm)/\d+/', fname):
                label = storage_name if storage_name else 'PBS'
                parts.append(f"\U0001F5C4\uFE0F {label}: {fname}")
            else:
                label = storage_name if storage_name else 'File'
                parts.append(f"\U0001F4C1 {label}: {fname}")
        
        # Error reason if failed
        if status != 'ok' and vm.get('error'):
            parts.append(f"\u26A0\uFE0F {vm['error']}")
        
        parts.append('')  # blank line between VMs
    
    # Summary line with icons
    vm_count = parsed.get('vm_count', 0)
    if vm_count > 0 or parsed.get('total_size'):
        ok_count = sum(1 for v in parsed.get('vms', [])
                       if v.get('status', '').lower() == 'ok')
        fail_count = vm_count - ok_count
        
        summary_parts = []
        if vm_count:
            summary_parts.append(f"\U0001F4CA {vm_count} backups")
        if fail_count:
            summary_parts.append(f"\u274C {fail_count} failed")
        if parsed.get('total_size'):
            summary_parts.append(f"\U0001F4E6 Total: {parsed['total_size']}")
        if parsed.get('total_time'):
            summary_parts.append(f"\u23F1\uFE0F Time: {parsed['total_time']}")
        
        if summary_parts:
            parts.append(' | '.join(summary_parts))
    
    return '\n'.join(parts)


def _format_system_startup(data: Dict[str, Any]) -> Tuple[str, str]:
    """
    Format comprehensive system startup report.
    
    Returns (title, body) tuple for the notification.
    Handles both simple startups (all OK) and those with issues.
    """
    hostname = data.get('hostname', 'unknown')
    has_issues = data.get('has_issues', False)
    
    # Build title
    if has_issues:
        total_issues = (
            data.get('total_failed', 0) +
            len(data.get('services_failed', [])) +
            len(data.get('storage_unavailable', []))
        )
        title = f"{hostname}: System startup - {total_issues} issue(s) detected"
    else:
        title = f"{hostname}: System startup completed"
    
    # Build body
    parts = []
    
    # Overall status
    if not has_issues:
        parts.append("All systems operational.")
    
    # VMs/CTs started
    vms_ok = len(data.get('vms_started', []))
    cts_ok = len(data.get('cts_started', []))
    if vms_ok or cts_ok:
        count_parts = []
        if vms_ok:
            count_parts.append(f"{vms_ok} VM{'s' if vms_ok > 1 else ''}")
        if cts_ok:
            count_parts.append(f"{cts_ok} CT{'s' if cts_ok > 1 else ''}")
        
        # List names (up to 5)
        names = []
        for vm in data.get('vms_started', [])[:3]:
            names.append(f"{vm['name']} ({vm['vmid']})")
        for ct in data.get('cts_started', [])[:3]:
            names.append(f"{ct['name']} ({ct['vmid']})")
        
        line = f"\u2705 {' and '.join(count_parts)} started"
        if names:
            if len(names) <= 5:
                line += f": {', '.join(names)}"
            else:
                line += f": {', '.join(names[:5])}..."
        parts.append(line)
    
    # Failed VMs/CTs
    for vm in data.get('vms_failed', []):
        reason = vm.get('reason', 'unknown error')
        parts.append(f"\u274C VM failed: {vm['name']} - {reason}")
    
    for ct in data.get('cts_failed', []):
        reason = ct.get('reason', 'unknown error')
        parts.append(f"\u274C CT failed: {ct['name']} - {reason}")
    
    # Storage issues
    storage_unavailable = data.get('storage_unavailable', [])
    if storage_unavailable:
        names = [s['name'] for s in storage_unavailable[:3]]
        parts.append(f"\u26A0\uFE0F Storage: {len(storage_unavailable)} unavailable ({', '.join(names)})")
    
    # Service issues  
    services_failed = data.get('services_failed', [])
    if services_failed:
        names = [s['name'] for s in services_failed[:3]]
        parts.append(f"\u26A0\uFE0F Services: {len(services_failed)} failed ({', '.join(names)})")
    
    # Startup duration
    duration = data.get('startup_duration_seconds', 0)
    if duration:
        minutes = int(duration // 60)
        parts.append(f"\u23F1\uFE0F Startup completed in {minutes} min")
    
    body = '\n'.join(parts)
    return title, body


# ─── Severity Icons ──────────────────────────────────────────────

SEVERITY_ICONS = {
    'CRITICAL': '\U0001F534',
    'WARNING':  '\U0001F7E1',
    'INFO':     '\U0001F535',
    'OK':       '\U0001F7E2',
    'UNKNOWN':  '\u26AA',
}

SEVERITY_ICONS_DISCORD = {
    'CRITICAL': ':red_circle:',
    'WARNING':  ':yellow_circle:',
    'INFO':     ':blue_circle:',
    'OK':       ':green_circle:',
    'UNKNOWN':  ':white_circle:',
}


# ─── Event Templates ─────────────────────────────────────────────
# Each template has a 'title' and 'body' with {variable} placeholders.
# 'group' is used for UI event filter grouping.
# 'default_enabled' controls initial state in settings.

TEMPLATES = {
    # ── Health Monitor state changes ──
    # NOTE: state_change is disabled by default -- it fires on every
    # status oscillation (OK->WARNING->OK) which creates noise.
    # The health_persistent and new_error templates cover this better.
    'state_change': {
        'title': '{hostname}: {category} changed to {current}',
        'body': '{category} status changed from {previous} to {current}.\n{reason}',
        'label': 'Health state changed',
        'group': 'health',
        'default_enabled': False,
    },
    'new_error': {
        'title': '{hostname}: New {severity} - {category}',
        'body': '{reason}',
        'label': 'New health issue',
        'group': 'health',
        'default_enabled': True,
    },
    'error_resolved': {
        'title': '{hostname}: Resolved - {category}',
        'body': 'The {category} issue has been resolved.\n{reason}\n\U0001F6A6 Previous severity: {original_severity}\n\u23F1\uFE0F Duration: {duration}',
        'label': 'Recovery notification',
        'group': 'health',
        'default_enabled': True,
    },
    'error_escalated': {
        'title': '{hostname}: Escalated to {severity} - {category}',
        'body': '{reason}',
        'label': 'Health issue escalated',
        'group': 'health',
        'default_enabled': True,
    },
    'health_degraded': {
        'title': '{hostname}: Health check degraded',
        'body': '{reason}',
        'label': 'Health check degraded',
        'group': 'health',
        'default_enabled': True,
    },
    
    # ── VM / CT events ──
    # Phase 1: apt-based update detection inside running Debian/Ubuntu
    # LXCs. Grouped — one notification per cycle covers every CT with
    # pending updates. Opt-in (default_enabled=False) because the check
    # uses `pct exec` to inspect package state inside the user's CTs.
    # Phase 2 (community-scripts metadata) will extend this without
    # changing the event type.
    'lxc_updates_available': {
        'title': '{hostname}: {count} LXC(s) with package updates available',
        'body': (
            '📊 {count} LXC(s) with pending package updates '
            '(📦 {total_packages} total, 🔒 {security_count} security):\n\n'
            '{ct_list}'
        ),
        'label': 'LXC updates available (experimental)',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'vm_start': {
        'title': '{hostname}: VM {vmname} ({vmid}) started',
        'body': 'Virtual machine {vmname} (ID: {vmid}) is now running.',
        'label': 'VM started',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'vm_start_warning': {
        'title': '{hostname}: VM {vmname} ({vmid}) started with warnings',
        'body': 'Virtual machine {vmname} (ID: {vmid}) started successfully but has warnings.\nWarnings: {reason}',
        'label': 'VM started (warnings)',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'vm_stop': {
        'title': '{hostname}: VM {vmname} ({vmid}) stopped',
        'body': 'Virtual machine {vmname} (ID: {vmid}) has been stopped.',
        'label': 'VM stopped',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'vm_shutdown': {
        'title': '{hostname}: VM {vmname} ({vmid}) shut down',
        'body': 'Virtual machine {vmname} (ID: {vmid}) has been cleanly shut down.',
        'label': 'VM shutdown',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'vm_fail': {
        'title': '{hostname}: VM {vmname} ({vmid}) FAILED',
        'body': 'Virtual machine {vmname} (ID: {vmid}) has crashed or failed to start.\nReason: {reason}',
        'label': 'VM FAILED',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'vm_restart': {
        'title': '{hostname}: VM {vmname} ({vmid}) restarted',
        'body': 'Virtual machine {vmname} (ID: {vmid}) has been restarted.',
        'label': 'VM restarted',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'ct_start': {
        'title': '{hostname}: CT {vmname} ({vmid}) started',
        'body': 'Container {vmname} (ID: {vmid}) is now running.',
        'label': 'CT started',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'ct_start_warning': {
        'title': '{hostname}: CT {vmname} ({vmid}) started with warnings',
        'body': 'Container {vmname} (ID: {vmid}) started successfully but has warnings.\nWarnings: {reason}',
        'label': 'CT started (warnings)',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'ct_stop': {
        'title': '{hostname}: CT {vmname} ({vmid}) stopped',
        'body': 'Container {vmname} (ID: {vmid}) has been stopped.',
        'label': 'CT stopped',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'ct_shutdown': {
        'title': '{hostname}: CT {vmname} ({vmid}) shut down',
        'body': 'Container {vmname} (ID: {vmid}) has been cleanly shut down.',
        'label': 'CT shutdown',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'ct_restart': {
        'title': '{hostname}: CT {vmname} ({vmid}) restarted',
        'body': 'Container {vmname} (ID: {vmid}) has been restarted.',
        'label': 'CT restarted',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    'ct_fail': {
        'title': '{hostname}: CT {vmname} ({vmid}) FAILED',
        'body': 'Container {vmname} (ID: {vmid}) has crashed or failed to start.\nReason: {reason}',
        'label': 'CT FAILED',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'migration_start': {
        'title': '{hostname}: Migration started — {vmname} ({vmid})',
        'body': 'Live migration of {vmname} (ID: {vmid}) to node {target_node} has started.',
        'label': 'Migration started',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'migration_complete': {
        'title': '{hostname}: Migration complete — {vmname} ({vmid})',
        'body': '{vmname} (ID: {vmid}) successfully migrated to node {target_node}.',
        'label': 'Migration complete',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'migration_warning': {
        'title': '{hostname}: Migration complete with warnings — {vmname} ({vmid})',
        'body': '{vmname} (ID: {vmid}) migrated to node {target_node} but encountered warnings.\nWarnings: {reason}',
        'label': 'Migration (warnings)',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'migration_fail': {
        'title': '{hostname}: Migration FAILED — {vmname} ({vmid})',
        'body': 'Migration of {vmname} (ID: {vmid}) to node {target_node} failed.\nReason: {reason}',
        'label': 'Migration FAILED',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'replication_fail': {
        'title': '{hostname}: Replication FAILED — {vmname} ({vmid})',
        'body': 'Replication of {vmname} (ID: {vmid}) failed.\nReason: {reason}',
        'label': 'Replication FAILED',
        'group': 'vm_ct',
        'default_enabled': True,
    },
    'replication_complete': {
        'title': '{hostname}: Replication complete — {vmname} ({vmid})',
        'body': 'Replication of {vmname} (ID: {vmid}) completed successfully.',
        'label': 'Replication complete',
        'group': 'vm_ct',
        'default_enabled': False,
    },
    
    # ── Backup / Snapshot events ──
    'backup_start': {
        'title': '{hostname}: Backup started on {storage}',
        'body': 'Backup job started on storage {storage}.\n{reason}',
        'label': 'Backup started',
        'group': 'backup',
        'default_enabled': False,
    },
    'backup_complete': {
        'title': '{hostname}: Backup complete — {vmname} ({vmid})',
        'body': 'Backup of {vmname} (ID: {vmid}) completed successfully.\nSize: {size}',
        'label': 'Backup complete',
        'group': 'backup',
        'default_enabled': True,
    },
    'backup_warning': {
        'title': '{hostname}: Backup complete with warnings — {vmname} ({vmid})',
        'body': 'Backup of {vmname} (ID: {vmid}) completed but encountered warnings.\nWarnings: {reason}',
        'label': 'Backup (warnings)',
        'group': 'backup',
        'default_enabled': True,
    },
    'backup_fail': {
        'title': '{hostname}: Backup FAILED — {vmname} ({vmid})',
        'body': 'Backup of {vmname} (ID: {vmid}) failed.\nReason: {reason}',
        'label': 'Backup FAILED',
        'group': 'backup',
        'default_enabled': True,
    },
    'snapshot_complete': {
        'title': '{hostname}: Snapshot created — {vmname} ({vmid})',
        'body': 'Snapshot "{snapshot_name}" created for {vmname} (ID: {vmid}).',
        'label': 'Snapshot created',
        'group': 'backup',
        'default_enabled': False,
    },
    'snapshot_fail': {
        'title': '{hostname}: Snapshot FAILED — {vmname} ({vmid})',
        'body': 'Snapshot creation for {vmname} (ID: {vmid}) failed.\nReason: {reason}',
        'label': 'Snapshot FAILED',
        'group': 'backup',
        'default_enabled': True,
    },
    
    # ── Resource events (from Health Monitor) ──
    'cpu_high': {
        'title': '{hostname}: High CPU usage — {value}%',
        'body': 'CPU usage has reached {value}% on {cores} cores.\n{details}',
        'label': 'High CPU usage',
        'group': 'resources',
        'default_enabled': True,
    },
    'ram_high': {
        'title': '{hostname}: High memory usage — {value}%',
        'body': 'Memory usage: {used} / {total} ({value}%).\n{details}',
        'label': 'High memory usage',
        'group': 'resources',
        'default_enabled': True,
    },
    'temp_high': {
        'title': '{hostname}: High CPU temperature — {value}°C',
        'body': 'CPU temperature has reached {value}°C (threshold: {threshold}°C).\n{details}',
        'label': 'High temperature',
        'group': 'resources',
        'default_enabled': True,
    },
    'disk_space_low': {
        'title': '{hostname}: Low disk space on {mount}',
        'body': 'Filesystem {mount}: {used}% used ({available} available).\nFree up disk space to avoid service disruption.',
        'label': 'Low disk space',
        'group': 'storage',
        'default_enabled': True,
    },
    'disk_io_error': {
        'title': '{hostname}: Disk failure detected — {device}',
        'body': 'I/O error or disk failure detected on device {device}.\n{reason}',
        'label': 'Disk failure / I/O error',
        'group': 'storage',
        'default_enabled': True,
    },
    'storage_unavailable': {
        'title': '{hostname}: Storage unavailable — {storage_name}',
        'body': 'PVE storage "{storage_name}" (type: {storage_type}) is not accessible.\nReason: {reason}',
        'label': 'Storage unavailable',
        'group': 'storage',
        'default_enabled': True,
    },
    'smart_test_complete': {
        'title': '{hostname}: SMART test completed — {device}',
        'body': 'SMART {test_type} test on /dev/{device} has completed.\nResult: {result}\nDuration: {duration}',
        'label': 'SMART test completed',
        'group': 'storage',
        'default_enabled': True,
    },
    'smart_test_failed': {
        'title': '{hostname}: SMART test FAILED — {device}',
        'body': 'SMART {test_type} test on /dev/{device} has failed.\nResult: {result}\nReason: {reason}',
        'label': 'SMART test FAILED',
        'group': 'storage',
        'default_enabled': True,
    },
    
    # ── GPU / PCIe passthrough events ──
    'gpu_mode_switch': {
        'title': '{hostname}: GPU mode changed to {new_mode}',
        'body': (
            'GPU passthrough mode has been switched.\n'
            'GPU: {gpu_name} ({gpu_pci})\n'
            'Previous mode: {old_mode}\n'
            'New mode: {new_mode}\n'
            '{details}'
        ),
        'label': 'GPU mode switched',
        'group': 'hardware',
        'default_enabled': True,
    },
    'gpu_passthrough_blocked': {
        'title': '{hostname}: {guest_type} {guest_id} blocked at startup',
        'body': (
            'PCIe passthrough guard prevented {guest_type} {guest_id} ({guest_name}) from starting.\n'
            'Reason: {reason}\n'
            '{details}'
        ),
        'label': 'GPU passthrough blocked',
        'group': 'hardware',
        'default_enabled': True,
    },
    'pci_passthrough_conflict': {
        'title': '{hostname}: PCIe device conflict detected',
        'body': (
            'A PCIe device is assigned to multiple guests.\n'
            'Device: {device_pci}\n'
            'Conflicting guests: {guest_list}\n'
            'Action required: Stop one of the guests or reassign the device.'
        ),
        'label': 'PCIe device conflict',
        'group': 'hardware',
        'default_enabled': True,
    },
    
    'load_high': {
        'title': '{hostname}: High system load — {value}',
        'body': 'System load average is {value} on {cores} cores.\n{details}',
        'label': 'High system load',
        'group': 'resources',
        'default_enabled': True,
    },
    
    # ── Network events ──
    'network_down': {
        'title': '{hostname}: Network connectivity lost',
        'body': 'The node has lost network connectivity.\nReason: {reason}',
        'label': 'Network connectivity lost',
        'group': 'network',
        'default_enabled': True,
    },
    'network_latency': {
        'title': '{hostname}: High network latency — {value}ms',
        'body': 'Latency to gateway: {value}ms (threshold: {threshold}ms).\nThis may indicate network congestion or hardware issues.',
        'label': 'High network latency',
        'group': 'network',
        'default_enabled': False,
    },
    
    # ── Security events ──
    'auth_fail': {
        'title': '{hostname}: Authentication failure',
        'body': 'Failed login attempt detected.\nSource IP: {source_ip}\nUser: {username}\nService: {service}',
        'label': 'Authentication failure',
        'group': 'security',
        'default_enabled': True,
    },
    'ip_block': {
        'title': '{hostname}: IP blocked by Fail2Ban',
        'body': 'IP address {source_ip} has been banned.\nJail: {jail}\nFailed attempts: {failures}',
        'label': 'IP blocked by Fail2Ban',
        'group': 'security',
        'default_enabled': True,
    },
    'firewall_issue': {
        'title': '{hostname}: Firewall issue detected',
        'body': 'A firewall configuration issue has been detected.\nReason: {reason}',
        'label': 'Firewall issue detected',
        'group': 'security',
        'default_enabled': True,
    },
    'user_permission_change': {
        'title': '{hostname}: User permission changed',
        'body': 'User: {username}\nChange: {change_details}',
        'label': 'User permission changed',
        'group': 'security',
        'default_enabled': True,
    },
    
    # ── Cluster events ──
    'split_brain': {
        'title': '{hostname}: SPLIT-BRAIN detected',
        'body': 'A cluster split-brain condition has been detected. Quorum may be lost.\nQuorum status: {quorum}',
        'label': 'SPLIT-BRAIN detected',
        'group': 'cluster',
        'default_enabled': True,
    },
    'node_disconnect': {
        'title': '{hostname}: Node {node_name} disconnected',
        'body': 'Node {node_name} has disconnected from the cluster.',
        'label': 'Node disconnected',
        'group': 'cluster',
        'default_enabled': True,
    },
    'node_reconnect': {
        'title': '{hostname}: Node {node_name} reconnected',
        'body': 'Node {node_name} has rejoined the cluster successfully.',
        'label': 'Node reconnected',
        'group': 'cluster',
        'default_enabled': True,
    },
    
    # ── Services events ──
    'system_startup': {
        'title': '{hostname}: {reason}',
        'body': '{summary}',
        'label': 'System startup report',
        'group': 'services',
        'default_enabled': True,
        'formatter': '_format_system_startup',
    },
    'system_shutdown': {
        'title': '{hostname}: System shutting down',
        'body': 'The node is shutting down.\n{reason}',
        'label': 'System shutting down',
        'group': 'services',
        'default_enabled': True,
    },
    'system_reboot': {
        'title': '{hostname}: System rebooting',
        'body': 'The node is rebooting.\n{reason}',
        'label': 'System rebooting',
        'group': 'services',
        'default_enabled': True,
    },
    'system_problem': {
        'title': '{hostname}: System problem detected',
        'body': 'A system-level problem has been detected.\nReason: {reason}',
        'label': 'System problem detected',
        'group': 'services',
        'default_enabled': True,
    },
    'service_fail': {
        'title': '{hostname}: Service failed — {service_name}',
        'body': 'System service "{service_name}" has failed.\nReason: {reason}',
        'label': 'Service failed',
        'group': 'services',
        'default_enabled': True,
    },
    'oom_kill': {
        'title': '{hostname}: OOM Kill — {process}',
        'body': 'Process "{process}" was killed by the Out-of-Memory manager.\n{reason}',
        'label': 'Out of memory kill',
        'group': 'services',
        'default_enabled': True,
    },
    
    # ── Hidden internal templates (not shown in UI) ──
    'service_fail_batch': {
        'title': '{hostname}: {service_count} services failed',
        'body': '{reason}',
        'label': 'Service fail batch',
        'group': 'services',
        'default_enabled': True,
        'hidden': True,
    },
    'system_mail': {
        'title': '{hostname}: {pve_title}',
        'body': '{reason}',
        'label': 'PVE system mail',
        'group': 'other',
        'default_enabled': True,
        'hidden': True,
    },
    'webhook_test': {
        'title': '{hostname}: Webhook test received',
        'body': 'PVE webhook connectivity test successful.\n{reason}',
        'label': 'Webhook test',
        'group': 'other',
        'default_enabled': True,
        'hidden': True,
    },
    'update_available': {
        'title': '{hostname}: Updates available',
        'body': 'Total updates: {total_count}\nSecurity: {security_count}\nProxmox: {pve_count}\nKernel: {kernel_count}\nImportant packages:\n{important_list}',
        'label': 'Updates available (legacy)',
        'group': 'updates',
        'default_enabled': False,
        'hidden': True,
    },
    'unknown_persistent': {
        'title': '{hostname}: Check unavailable - {category}',
        'body': 'Health check for {category} has been unavailable for 3+ cycles.\n{reason}',
        'label': 'Check unavailable',
        'group': 'health',
        'default_enabled': False,
        'hidden': True,
    },
    
    # ── Health Monitor events ──
    'health_persistent': {
        'title': '{hostname}: {count} active health issue(s)',
        'body': 'The following health issues remain unresolved:\n{issue_list}\n\nThis digest is sent once every 24 hours while issues persist.',
        'label': 'Active health issues (daily)',
        'group': 'health',
        'default_enabled': True,
    },
    'health_issue_new': {
        'title': '{hostname}: New health issue — {category}',
        'body': 'New {severity} issue detected in: {category}\nDetails: {reason}',
        'label': 'New health issue',
        'group': 'health',
        'default_enabled': True,
    },
    'health_issue_resolved': {
        'title': '{hostname}: Resolved - {category}',
        'body': '{category} issue has been resolved.\n{reason}\nDuration: {duration}',
        'label': 'Health issue resolved',
        'group': 'health',
        'default_enabled': True,
        'hidden': True,  # Use error_resolved instead (avoids duplicate in UI)
    },
    
    # ── Update notifications ──
    'update_summary': {
        'title': '{hostname}: Updates available',
        'body': (
            'Total updates: {total_count}\n'
            'Security updates: {security_count}\n'
            'Proxmox-related updates: {pve_count}\n'
            'Kernel updates: {kernel_count}\n'
            'Important packages:\n{important_list}'
        ),
        'label': 'Updates available',
        'group': 'updates',
        'default_enabled': True,
    },
    'pve_update': {
        'title': '{hostname}: Proxmox VE {new_version} available',
        'body': 'A new Proxmox VE release is available.\nCurrent: {current_version}\nNew: {new_version}\n{details}',
        'label': 'Proxmox VE update available',
        'group': 'updates',
        'default_enabled': True,
    },
    'update_complete': {
        'title': '{hostname}: System update completed',
        'body': 'System packages have been successfully updated.\n{details}',
        'label': 'Update completed',
        'group': 'updates',
        'default_enabled': False,
    },
    
    # ── AI model migration ──
    'ai_model_migrated': {
        'title': '{hostname}: AI model updated',
        'body': (
            'The AI model for notifications has been automatically updated.\n'
            'Provider: {provider}\n'
            'Previous model: {old_model}\n'
            'New model: {new_model}\n\n'
            '{message}'
        ),
        'label': 'AI model auto-updated',
        'group': 'system',
        'severity': 'info',
        'default_enabled': True,
    },
    
    # ── ProxMenux updates ──
    'proxmenux_update': {
        'title': '{hostname}: ProxMenux {new_version} available',
        'body': (
            'A new version of ProxMenux is available.\n'
            'Current: {current_version}\n'
            'New: {new_version}'
        ),
        'label': 'ProxMenux update available',
        'group': 'updates',
        'default_enabled': True,
    },

    # ── Remote mount health (Sprint 13) ──
    # `mount_stale` is the high-severity case — the mount looks
    # present in /proc/mounts but every access blocks/ESTALEs, and
    # writes silently land on the underlying directory of the host
    # (or the container's rootfs in the LXC variant), eventually
    # filling the disk. The body includes the source so the operator
    # can match against /etc/fstab without ssh, and the LXC fields
    # surface inside-container scope when present (Sprint 13.27).
    # Variables ``lxc_id`` / ``lxc_name`` resolve to empty strings on
    # host mounts thanks to the SafeDict in render_template — the
    # surrounding text is phrased so an empty value reads naturally.
    'mount_stale': {
        'title': '{hostname}: stale remote mount {mount_target}',
        'body': (
            'Remote mount {mount_target} ({fstype}) from {mount_source} is stale{lxc_scope}.\n'
            'Stat timed out or returned an error: {error}\n\n'
            'Apps writing to this path will silently land on the underlying filesystem '
            'and may fill the disk. Remount or fix connectivity ASAP.'
        ),
        'label': 'Remote mount stale',
        'group': 'storage',
        'default_enabled': True,
    },
    'mount_readonly': {
        'title': '{hostname}: remote mount {mount_target} is read-only',
        'body': (
            'Remote mount {mount_target} ({fstype}) from {mount_source} is mounted '
            'read-only{lxc_scope}. Writes will fail. If this was unintentional, remount with rw.'
        ),
        'label': 'Remote mount read-only',
        'group': 'storage',
        'default_enabled': True,
    },

    # Sprint 13.30: per-LXC rootfs filling up.
    # Catches the classic "CT runs out of disk and stops booting"
    # before it actually happens — fires at 85% (WARNING) and 95%
    # (CRITICAL), same thresholds as the host disk check. Body
    # includes both percentage and the absolute MB so the operator
    # can decide between "expand the rootfs" and "free up logs".
    'lxc_disk_low': {
        'title': '{hostname}: CT {vmid} rootfs at {usage_percent}%',
        'body': (
            'CT {vmid} ({name}) rootfs is at {usage_percent}% '
            '({disk_bytes} / {maxdisk_bytes}).\n\n'
            'A full LXC rootfs prevents the container from booting cleanly. '
            'Either expand the rootfs (pct resize {vmid} rootfs +1G) or free '
            'space inside the container.'
        ),
        'label': 'LXC rootfs near full',
        'group': 'storage',
        'default_enabled': True,
    },

    # ── Phase 3 capacity events (Sprint 14.5) ─────────────────────────
    # Three new events that complete the storage-monitoring picture.
    # Each fires at the user-configured warning/critical thresholds
    # (defaults 85/95). Wording mentions both the percentage and a
    # path/identifier so the operator can act without opening the
    # dashboard first.

    'lxc_mount_low': {
        'title': '{hostname}: CT {vmid} mount {mount} at {usage_percent}%',
        'body': (
            'Mount {mount} inside CT {vmid} ({name}) is at {usage_percent}% used.\n'
            'Filesystem type: {fstype}\n\n'
            'A full mount inside a container often blocks the application '
            'silently — writes either fail or, worse, land on the rootfs '
            'and trigger the rootfs alert next. Free up space on the mount '
            'or expand it.'
        ),
        'label': 'LXC mount near full',
        'group': 'storage',
        'default_enabled': True,
    },

    'pve_storage_full': {
        'title': '{hostname}: PVE storage {storage_name} at {usage_percent}%',
        'body': (
            'Proxmox storage "{storage_name}" (type: {storage_type}) is at '
            '{usage_percent}% used.\n\n'
            'Once full, no new VM/CT can be provisioned and existing guests '
            'may fail to write. Move/delete unused volumes or expand the '
            'underlying pool/LV/RBD image.'
        ),
        'label': 'PVE storage near full',
        'group': 'storage',
        'default_enabled': True,
    },

    'zfs_pool_full': {
        'title': '{hostname}: ZFS pool {pool_name} at {usage_percent}%',
        'body': (
            'ZFS pool "{pool_name}" is at {usage_percent}% capacity.\n\n'
            'ZFS performance and write reliability degrade sharply above '
            '~80% capacity (CoW needs free space for new blocks). Free up '
            'snapshots, prune old datasets, or add more vdevs to the pool.'
        ),
        'label': 'ZFS pool near full',
        'group': 'storage',
        'default_enabled': True,
    },

    # ── Post-install function updates (Sprint 12D) ──
    # Fired once per *changed* set of available post-install function
    # updates. The body lists each tool with its before/after version so
    # the operator sees exactly what's about to change without opening
    # the Monitor.
    'post_install_update': {
        'title': '{hostname}: {count} ProxMenux optimization update(s) available',
        'body': (
            '{count} optimization update(s) detected on this host.\n\n'
            '🛠️ Tools:\n{tool_list}\n\n'
            '💡 How to apply:\n'
            '  • ProxMenux Monitor → Settings → ProxMenux Optimizations\n'
            '  • Or run the post-install menu (option 2) → "Apply available updates"'
        ),
        'label': 'ProxMenux optimization updates available',
        'group': 'updates',
        'default_enabled': True,
    },

    # Sprint 14.6: Secure Gateway / OCI app updates. Fired when a
    # ProxMenux-managed LXC (currently the Tailscale gateway, but
    # designed to extend to future OCI apps) has package upgrades
    # pending. The user applies the update with one click in the
    # Monitor — no shell access required. {package_count} + the
    # bullet list make sure the operator sees exactly what's moving
    # without opening the dashboard first.
    'secure_gateway_update_available': {
        'title': '{hostname}: {app_name} update available — v{latest_version}',
        'body': (
            '{app_name} (managed by ProxMenux) has 📦 {package_count} package update(s) '
            'pending in its container.\n'
            '🔹 Current Tailscale: v{current_version}  →  🟢 Latest: v{latest_version}\n\n'
            '💡 Open ProxMenux Monitor > Settings > Secure Gateway and click '
            '"Update" to apply.\n\n'
            '🗂️ Packages:\n{package_list}'
        ),
        'label': 'Secure Gateway update available',
        'group': 'updates',
        'default_enabled': True,
    },

    # Sprint 14.7: host-side NVIDIA driver. Unlike the Tailscale flow,
    # there's no in-dashboard "Apply update" button — installing an
    'nvidia_driver_update_available': {
        'title': '{hostname}: NVIDIA driver update available — v{latest_version}',
        'body': (
            'A newer NVIDIA driver compatible with kernel {kernel} is available.\n'
            '🔹 Currently installed: v{current_version}\n'
            '🟢 Latest available:    v{latest_version}\n\n'
            '{upgrade_reason}\n\n'
            '💡 To reinstall:\n'
            '  • From the ProxMenux post-install menu: {menu_label}\n\n'
            'Reinstalling rebuilds the DKMS module against the running kernel and '
            'requires a reboot to load the new driver.'
        ),
        'label': 'NVIDIA driver update available',
        'group': 'updates',
        'default_enabled': True,
    },

    # Sprint 14.7 follow-up: host-side Coral TPU driver. Mirrors the
    # NVIDIA flow — there's no in-dashboard "Apply update" button; the
    # operator reruns the installer from the post-install menu. The
    # PCIe (gasket-dkms) and USB (libedgetpu1-*) variants share one
    # template and use {variant_label} to surface which is moving so
    # the body stays readable in either case.
    'coral_driver_update_available': {
        'title': '{hostname}: Coral TPU driver update available — {latest_version}',
        'body': (
            'A newer {variant_label} is available.\n'
            '🔹 Currently installed: {current_version}\n'
            '🟢 Latest available:    {latest_version}\n\n'
            '{upgrade_reason}\n\n'
            '💡 To reinstall:\n'
            '  • From the ProxMenux post-install menu: {menu_label}\n\n'
            '{reboot_note}'
        ),
        'label': 'Coral TPU driver update available',
        'group': 'updates',
        'default_enabled': True,
    },
    
    # ── Burst aggregation summaries (hidden -- auto-generated by BurstAggregator) ──
    # These inherit enabled state from their parent event type at dispatch time.
    #
    # IMPORTANT — `{count}` here is the count of *additional* events that
    # arrived AFTER the first one was already sent individually on the
    # fast-alert path (see notification_manager.py:_create_summary). It is
    # NOT the total event count in the window; that lives in `{total_count}`.
    # The wording must reflect "more / additional" so the user does not
    # mistake a 2-event burst for a duplicate of the initial individual
    # notification. The first event has already been delivered when this
    # summary fires.
    'burst_auth_fail': {
        'title': '{hostname}: +{count} more auth failures in {window}',
        'body': '+{count} additional authentication failures detected in {window} ({total_count} total).\nSources: {entity_list}',
        'label': 'Auth failures burst',
        'group': 'security',
        'default_enabled': True,
        'hidden': True,
    },
    'burst_ip_block': {
        'title': '{hostname}: Fail2Ban banned +{count} more IPs in {window}',
        'body': '+{count} additional IPs banned by Fail2Ban in {window} ({total_count} total).\nIPs: {entity_list}',
        'label': 'IP block burst',
        'group': 'security',
        'default_enabled': True,
        'hidden': True,
    },
    'burst_disk_io': {
        'title': '{hostname}: +{count} more disk I/O errors on {entity_list}',
        'body': '+{count} additional I/O errors detected in {window} ({total_count} total).\nDevices: {entity_list}',
        'label': 'Disk I/O burst',
        'group': 'storage',
        'default_enabled': True,
        'hidden': True,
    },
    'burst_cluster': {
        'title': '{hostname}: Cluster flapping detected (+{count} more changes)',
        'body': 'Cluster state changed +{count} more times in {window} ({total_count} total).\nNodes: {entity_list}',
        'label': 'Cluster flapping burst',
        'group': 'cluster',
        'default_enabled': True,
        'hidden': True,
    },
    'burst_service_fail': {
        'title': '{hostname}: +{count} more services failed in {window}',
        'body': '+{count} additional service failures detected in {window} ({total_count} total).\nThis typically indicates a node reboot or PVE service restart.\n\nAdditional failures:\n{details}',
        'label': 'Service fail burst',
        'group': 'services',
        'default_enabled': True,
        'hidden': True,
    },
    'burst_system': {
        'title': '{hostname}: +{count} more system problems in {window}',
        'body': '+{count} additional system problems detected in {window} ({total_count} total).\n\nAdditional issues:\n{details}',
        'label': 'System problems burst',
        'group': 'services',
        'default_enabled': True,
        'hidden': True,
    },
    'burst_generic': {
        'title': '{hostname}: +{count} more {event_type} events in {window}',
        'body': '+{count} additional events of type {event_type} in {window} ({total_count} total).\n\nAdditional events:\n{details}',
        'label': 'Generic burst',
        'group': 'other',
        'default_enabled': True,
        'hidden': True,
    },
}

# ─── Event Groups (for UI filtering) ─────────────────────────────

EVENT_GROUPS = {
    'vm_ct':     {'label': 'VM / CT',         'description': 'Start, stop, crash, migration'},
    'backup':    {'label': 'Backups',         'description': 'Backup start, complete, fail'},
    'resources': {'label': 'Resources',       'description': 'CPU, memory, temperature'},
    'storage':   {'label': 'Storage',         'description': 'Disk space, I/O, SMART'},
    'network':   {'label': 'Network',         'description': 'Connectivity, bond, latency'},
    'security':  {'label': 'Security',        'description': 'Auth failures, Fail2Ban, firewall'},
    'cluster':   {'label': 'Cluster',         'description': 'Quorum, split-brain, HA fencing'},
    'services':  {'label': 'Services',        'description': 'System services, shutdown, reboot'},
    'health':    {'label': 'Health Monitor',  'description': 'Health checks, degradation, recovery'},
    'updates':   {'label': 'Updates',         'description': 'System and PVE updates'},
    'other':     {'label': 'Other',           'description': 'Uncategorized notifications'},
}


# ─── Template Renderer ───────────────────────────────────────────

def _get_hostname() -> str:
    """Get hostname for message titles.

    Honors the user-configured Display Name (notification settings `hostname` key) and
    falls back to the system FQDN. The hostname is NOT truncated at the first dot —
    multi-node deployments need the full FQDN to disambiguate which host emitted the
    notification. Resolution is delegated to `notification_manager._resolve_display_hostname`.
    """
    try:
        from notification_manager import _resolve_display_hostname
        return _resolve_display_hostname()
    except Exception:
        try:
            return socket.gethostname()
        except Exception:
            return 'proxmox'


def render_template(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Render a template into a structured notification object.
    
    Returns structured output usable by all channels:
        title, body (text), body_text, body_html (escaped), fields, tags, severity, group
    """
    import html as html_mod
    
    template = TEMPLATES.get(event_type)
    if not template:
        # Catch-all: unknown event types always get delivered (group 'other')
        # so no Proxmox notification is ever silently dropped.
        fallback_body = data.get('message', data.get('reason', str(data)))
        severity = data.get('severity', 'INFO')
        return {
            'title': f"{_get_hostname()}: {event_type}",
            'body': fallback_body, 'body_text': fallback_body,
            'body_html': f'<p>{html_mod.escape(str(fallback_body))}</p>',
            'fields': [], 'tags': [severity, 'other', event_type],
            'severity': severity, 'group': 'other',
        }
    
    # Ensure hostname is always available
    variables = {
        'hostname': _get_hostname(),
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'severity': data.get('severity', 'INFO'),
        # Burst event variables
        'window': '', 'entity_list': '',
        # Common defaults
        'vmid': '', 'vmname': '', 'reason': '', 'summary': '',
        'details': '', 'category': '', 'previous': '', 'current': '',
        'duration': '', 'value': '', 'threshold': '',
        'source_ip': '', 'username': '', 'service': '', 'service_name': '',
        'node_name': '', 'target_node': '', 'mount': '', 'device': '',
        'used': '', 'total': '', 'available': '', 'cores': '',
        'count': '', 'size': '', 'snapshot_name': '', 'jail': '',
        'failures': '', 'quorum': '', 'change_details': '', 'message': '',
        'security_count': '0', 'total_count': '0', 'package_list': '',
        'packages': '', 'pve_packages': '', 'version': '',
        'issue_list': '', 'error_key': '',
        'storage_name': '', 'storage_type': '',
        'important_list': 'none',
    }
    variables.update(data)
    
    # Ensure important_list is never blank (fallback to 'none')
    if not variables.get('important_list', '').strip():
        variables['important_list'] = 'none'
    
    # `format_map` with a SafeDict avoids the KeyError → "show raw template
    # with `{placeholder}` literal" failure mode. If a template gets a new
    # field that nobody populated in `data`/`variables`, the user sees the
    # field elided rather than the raw `{new_field}` string. Audit Tier 6.
    class _SafeDict(dict):
        def __missing__(self, key):
            return ''

    safe_vars = _SafeDict(variables)
    try:
        title = template['title'].format_map(safe_vars)
    except (ValueError, IndexError):
        title = template['title']
    
    # ── PVE vzdump special formatting ──
    # When the event came from PVE webhook with a full vzdump message,
    # parse the table/logs and format a rich body instead of the sparse template.
    pve_message = data.get('pve_message', '')
    pve_title = data.get('pve_title', '')
    
    # Check for custom formatter function
    formatter_name = template.get('formatter')
    if formatter_name and formatter_name in globals():
        formatter_func = globals()[formatter_name]
        try:
            title, body_text = formatter_func(data)
        except Exception:
            # Fallback to standard formatting if formatter fails
            try:
                body_text = template['body'].format_map(safe_vars)
            except (ValueError, IndexError):
                body_text = template['body']
    elif event_type in ('backup_complete', 'backup_fail') and pve_message:
        parsed = _parse_vzdump_message(pve_message)
        if parsed:
            is_success = (event_type == 'backup_complete')
            body_text = _format_vzdump_body(parsed, is_success)
            # Use PVE's own title if available (contains hostname and status)
            if pve_title:
                title = pve_title
        else:
            # Couldn't parse -- use PVE raw message as body
            body_text = pve_message.strip()
    elif event_type == 'system_mail' and pve_message:
        # System mail -- use PVE message directly (mail bounce, cron, smartd)
        body_text = pve_message.strip()[:1000]
    else:
        try:
            body_text = template['body'].format_map(safe_vars)
        except (ValueError, IndexError):
            body_text = template['body']
    
    # Clean up: collapse runs of 3+ blank lines into 1, remove trailing whitespace
    import re as _re
    body_text = _re.sub(r'\n{3,}', '\n\n', body_text.strip())
    
    severity = variables.get('severity', 'INFO')
    group = template.get('group', 'system')
    
    # Build structured fields for Discord embeds / rich notifications
    fields = []
    field_map = [
        ('vmid', 'VM/CT'), ('vmname', 'Name'), ('device', 'Device'),
        ('source_ip', 'Source IP'), ('node_name', 'Node'), ('category', 'Category'),
        ('service_name', 'Service'), ('jail', 'Jail'), ('username', 'User'),
        ('count', 'Count'), ('window', 'Window'), ('entity_list', 'Affected'),
    ]
    for key, label in field_map:
        val = variables.get(key, '')
        if val:
            fields.append((label, str(val)))
    
    # Build HTML body with escaped content
    body_html_parts = []
    for line in body_text.split('\n'):
        if line.strip():
            body_html_parts.append(f'<p>{html_mod.escape(line)}</p>')
    body_html = '\n'.join(body_html_parts) if body_html_parts else f'<p>{html_mod.escape(body_text)}</p>'
    
    return {
        'title': title,
        'body': body_text,         # backward compat
        'body_text': body_text,
        'body_html': body_html,
        'fields': fields,
        'tags': [severity, group, event_type],
        'severity': severity,
        'group': group,
    }


def get_event_types_by_group() -> Dict[str, list]:
    """Get all event types organized by group, for UI rendering.
    
    Hidden templates (burst aggregations, internal types) are excluded
    from the UI. They still work in the backend and inherit enabled
    state from their parent event type.
    
    Returns:
        {group_key: [{'type': event_type, 'title': label, 
                       'default_enabled': bool}, ...]}
    """
    result = {}
    for event_type, template in TEMPLATES.items():
        # Skip hidden templates (bursts, internal, deprecated)
        if template.get('hidden', False):
            continue
        
        group = template.get('group', 'other')
        if group not in result:
            result[group] = []
        
        # Use explicit label if available, otherwise derive from title
        label = template.get('label', '')
        if not label:
            import re
            label = template['title'].replace('{hostname}', '').strip(': ')
            label = re.sub(r'\s*\{[^}]+\}', '', label).strip(' -:')
        if not label:
            label = event_type.replace('_', ' ').title()
        
        result[group].append({
            'type': event_type,
            'title': label,
            'default_enabled': template.get('default_enabled', True),
        })
    return result


def get_default_enabled_events() -> Dict[str, bool]:
    """Get the default enabled state for all event types."""
    return {
        event_type: template.get('default_enabled', True)
        for event_type, template in TEMPLATES.items()
    }


# ─── Emoji Enrichment (per-channel opt-in) ──────────────────────

# Category-level header icons
CATEGORY_EMOJI = {
    'vm_ct':     '\U0001F5A5\uFE0F',   # desktop computer
    'backup':    '\U0001F4BE',           # floppy disk (backup)
    'resources': '\U0001F4CA',           # bar chart
    'storage':   '\U0001F4BD',           # minidisc / hard disk
    'network':   '\U0001F310',           # globe with meridians
    'security':  '\U0001F6E1\uFE0F',    # shield
    'cluster':   '\U0001F517',           # chain link
    'services':  '\u2699\uFE0F',         # gear
    'health':    '\U0001FA7A',           # stethoscope
    'updates':   '\U0001F504',           # counterclockwise arrows (update)
    'hardware':  '\U0001F3AE',           # video game controller (GPU/PCIe hardware)
    'other':     '\U0001F4E8',           # incoming envelope
}

# Event-specific title icons  (override category default when present)
EVENT_EMOJI = {
    # VM / CT
    'lxc_updates_available': '\U0001F4E6',     # \uD83D\uDCE6 package \u2014 pending CT updates
    'vm_start':             '\u25B6\uFE0F',    # play button
    'vm_start_warning':     '\u26A0\uFE0F',     # warning sign - started with warnings
    'vm_stop':              '\u23F9\uFE0F',     # stop button
    'vm_shutdown':          '\u23CF\uFE0F',     # eject
    'vm_fail':              '\U0001F4A5',        # collision (crash)
    'vm_restart':           '\U0001F504',        # cycle
    'ct_start':             '\u25B6\uFE0F',
    'ct_start_warning':     '\u26A0\uFE0F',     # warning sign - started with warnings
    'ct_stop':              '\u23F9\uFE0F',
    'ct_shutdown':          '\u23CF\uFE0F',
    'ct_restart':           '\U0001F504',
    'ct_fail':              '\U0001F4A5',
    'migration_start':      '\U0001F69A',        # moving truck
    'migration_complete':   '\u2705',            # check mark
    'migration_warning':    '\U0001F69A\u26A0\uFE0F', # 🚚⚠️ truck + warning
    'migration_fail':       '\u274C',            # cross mark
    'replication_fail':     '\u274C',
    'replication_complete': '\u2705',
    # Backups
    'backup_start':         '\U0001F4BE\U0001F680',  # 💾🚀 floppy + rocket
    'backup_complete':      '\U0001F4BE\u2705',       # 💾✅ floppy + check
    'backup_warning':       '\U0001F4BE\u26A0\uFE0F', # 💾⚠️ floppy + warning
    'backup_fail':          '\U0001F4BE\u274C',       # 💾❌ floppy + cross
    'snapshot_complete':    '\U0001F4F8',         # camera with flash
    'snapshot_fail':        '\u274C',
    # Resources
    'cpu_high':             '\U0001F525',         # fire
    'ram_high':             '\U0001F4A7',         # droplet
    'temp_high':            '\U0001F321\uFE0F',   # thermometer
    'load_high':            '\u26A0\uFE0F',       # warning
    # Storage
    'disk_space_low':       '\U0001F4C9',         # chart decreasing
    'disk_io_error':        '\U0001F4A5',
    'storage_unavailable':  '\U0001F6AB',         # prohibited
    # Sprint 13 — remote mount events
    'mount_stale':          '\U0001F517',         # link (broken connection feel)
    'mount_readonly':       '\U0001F512',         # lock
    'lxc_disk_low':         '\U0001F4BE',         # floppy disk (near-full)
    'lxc_mount_low':        '\U0001F4C2',         # 📂 folder near-full
    'pve_storage_full':     '\U0001F4E6',         # 📦 package (running out)
    'zfs_pool_full':        '\U0001F30A',         # 🌊 wave (pool is full)
    # Network
    'network_down':         '\U0001F50C',         # electric plug
    'network_latency':      '\U0001F422',         # turtle (slow)
    # Security
    'auth_fail':            '\U0001F6A8',         # police light
    'ip_block':             '\U0001F6B7',         # no pedestrians (banned)
    'firewall_issue':       '\U0001F525',
    'user_permission_change': '\U0001F511',       # key
    # Cluster
    'split_brain':          '\U0001F4A2',         # anger symbol
    'node_disconnect':      '\U0001F50C',
    'node_reconnect':       '\u2705',
    # Services
    'system_startup':       '\U0001F680',         # rocket (startup)
    'system_shutdown':      '\u23FB\uFE0F',       # power symbol (Unicode)
    'system_reboot':        '\U0001F504',
    'system_problem':       '\u26A0\uFE0F',
    'service_fail':         '\u274C',
    'oom_kill':             '\U0001F4A3',         # bomb
    # Health
    'new_error':            '\U0001F198',         # SOS
    'error_resolved':       '\u2705',
    'error_escalated':      '\U0001F53A',         # red triangle up
    'health_degraded':      '\u26A0\uFE0F',
    'health_persistent':    '\U0001F4CB',         # clipboard
    # Updates
    'update_summary':       '\U0001F4E6',
    'pve_update':           '\U0001F195',         # NEW
    'update_complete':      '\u2705',
    'proxmenux_update':     '\U0001F195',         # NEW
    # Sprint 12D: post-install function updates use the sparkle icon to
    # differentiate them visually from a full ProxMenux release update.
    'post_install_update':  '✨',              # sparkles
    'secure_gateway_update_available': '\U0001F510',  # 🔐 closed lock with key
    'nvidia_driver_update_available':  '\U0001F3AE',  # 🎮 video game (GPU)
    'coral_driver_update_available':   '\U0001F9E0',  # 🧠 brain (TPU/inference)
    # AI
    'ai_model_migrated':    '\U0001F504',         # arrows counterclockwise (refresh/update)
    # GPU / PCIe
    'gpu_mode_switch':      '\U0001F3AE',         # video game controller (represents GPU)
    'gpu_passthrough_blocked': '\U0001F6AB',      # prohibited sign (blocked)
    'pci_passthrough_conflict': '\u26A0\uFE0F',   # warning triangle (conflict)
}

# Decorative field-level icons for body text enrichment
FIELD_EMOJI = {
    'hostname':     '\U0001F4BB',   # laptop
    'vmid':         '\U0001F194',   # ID button
    'vmname':       '\U0001F3F7\uFE0F',  # label
    'device':       '\U0001F4BD',   # disk
    'mount':        '\U0001F4C2',   # open folder
    'source_ip':    '\U0001F310',   # globe
    'username':     '\U0001F464',   # bust in silhouette
    'service_name': '\u2699\uFE0F', # gear
    'node_name':    '\U0001F5A5\uFE0F',  # computer
    'target_node':  '\U0001F3AF',   # direct hit (target)
    'category':     '\U0001F4CC',   # pushpin
    'severity':     '\U0001F6A6',   # traffic light
    'duration':     '\u23F1\uFE0F', # stopwatch
    'timestamp':    '\U0001F552',   # clock three
    'size':         '\U0001F4CF',   # ruler
    'reason':       '\U0001F4DD',   # memo
    'value':        '\U0001F4CA',   # chart
    'threshold':    '\U0001F6A7',   # construction
    'jail':         '\U0001F512',   # lock
    'failures':     '\U0001F522',   # input numbers
    'quorum':       '\U0001F465',   # busts in silhouette
    'total_count':  '\U0001F4E6',   # package
    'security_count': '\U0001F6E1\uFE0F',  # shield
    'pve_count':    '\U0001F4E6',
    'kernel_count': '\u2699\uFE0F',
    'important_list': '\U0001F4CB',  # clipboard
    'current_version': '\U0001F4E6',  # package \u2014 installed version
    'latest_version': '\U0001F195',   # NEW button \u2014 upstream version
    'kernel':       '\u2699\uFE0F',    # gear \u2014 running kernel
    'menu_label':   '\U0001F4D6',      # open book \u2014 menu navigation hint
}


def enrich_with_emojis(event_type: str, title: str, body: str,
                       data: Dict[str, Any]) -> tuple:
    """Replace the plain title/body with emoji-enriched versions.
    
    Returns (enriched_title, enriched_body).
    The function is idempotent: if the title already starts with an emoji,
    it is returned unchanged.
    """
    import re
    
    # Pick the best title icon: event-specific > category > severity circle
    template = TEMPLATES.get(event_type, {})
    group = template.get('group', 'other')
    severity = data.get('severity', 'INFO')
    
    icon = EVENT_EMOJI.get(event_type) or CATEGORY_EMOJI.get(group) or SEVERITY_ICONS.get(severity, '')
    
    # Build enriched title: replace severity circle with event-specific icon
    # Current format: "hostname: Something"  -> "ICON hostname: Something"
    # If title already starts with an emoji (from a previous pass), skip.
    enriched_title = title
    if icon and not any(title.startswith(e) for e in SEVERITY_ICONS.values()):
        enriched_title = f'{icon} {title}'
    elif icon:
        # Replace existing severity circle with richer icon
        for sev_icon in SEVERITY_ICONS.values():
            if title.startswith(sev_icon):
                enriched_title = title.replace(sev_icon, icon, 1)
                break
    
    # ── Preprocess body: add line breaks before known patterns ──
    # This helps when everything comes concatenated
    preprocessed = body
    
    # First, clean up duplicated device references like "/dev/sda: /dev/sda: /dev/sda [SAT]"
    # Convert to just "/dev/sda [SAT]" or "/dev/sda:"
    preprocessed = re.sub(r'(/dev/\w+):\s*\1:\s*\1', r'\1', preprocessed)
    preprocessed = re.sub(r'(/dev/\w+):\s*\1', r'\1', preprocessed)
    
    # Patterns that should start on a new line
    line_break_patterns = [
        (r';\s*/dev/', '\n/dev/'),                    # ;/dev/sdb -> newline + /dev/sdb
        (r'(?<=[a-z])\s+/dev/', '\n/dev/'),           # "sectors /dev/sdb" -> newline before /dev/
        (r'(?<=\))\s*/dev/', '\n/dev/'),              # ") /dev/sdb" -> newline before /dev/
        (r'\bDevice:', '\nDevice:'),                  # Device: on new line
        (r'\bError:', '\nError:'),                    # Error: on new line
        (r'\bAction:', '\nAction:'),                  # Action: on new line
        (r'\bAffected:', '\nAffected:'),              # Affected: on new line
        (r'Device not currently', '\nDevice not currently'),  # Note about missing device
        (r'\bSMART:', '\nSMART:'),                    # SMART status
    ]
    
    for pattern, replacement in line_break_patterns:
        preprocessed = re.sub(pattern, replacement, preprocessed)
    
    # Clean up multiple newlines and leading newlines
    preprocessed = re.sub(r'\n{3,}', '\n\n', preprocessed)
    preprocessed = re.sub(r'^\n+', '', preprocessed)
    preprocessed = preprocessed.strip()
    
    # ── Extended emoji mappings for health/disk messages ──
    HEALTH_EMOJI_MAP = {
        # Disk patterns
        '/dev/': '\U0001F4BF',      # DVD disk
        'Device:': '\U0001F4BF',    # DVD disk
        'Error:': '\u274C',         # Red X
        'Action:': '\U0001F4A1',    # Light bulb (tip)
        'Affected:': '\U0001F3AF',  # Target
        'SMART:': '\U0001F4CA',     # Chart
        'Device not currently': '\U0001F4CC',  # Pushpin (note)
        # Status patterns
        'unreadable': '\u26A0\uFE0F',  # Warning
        'pending': '\u26A0\uFE0F',     # Warning
        'FAILED': '\u274C',            # Red X
        'PASSED': '\u2705',            # Green check
        # Update / install bodies
        'Tools:': '\U0001F6E0\uFE0F',  # hammer and wrench
        'Packages:': '\U0001F4E6',     # package
        'How to apply:': '\U0001F4A1', # Light bulb (tip)
    }
    
    # Build enriched body: prepend field emojis to recognizable lines
    lines = preprocessed.split('\n')
    enriched_lines = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            enriched_lines.append(line)
            continue
        
        # First, check health-specific patterns
        health_enriched = False
        for pattern, emoji in HEALTH_EMOJI_MAP.items():
            if stripped.startswith(pattern):
                # Don't double-add emoji if already present
                if not stripped.startswith(emoji):
                    enriched_lines.append(f'{emoji} {stripped}')
                else:
                    enriched_lines.append(stripped)
                health_enriched = True
                break
        
        if health_enriched:
            continue
        
        # Try to match "FieldName: value" patterns
        enriched = False
        for field_key, field_icon in FIELD_EMOJI.items():
            # Match common label patterns: "Device:", "Duration:", "Size:", etc.
            label_variants = [
                field_key.replace('_', ' ').title(),  # "Source Ip" -> not great
                field_key.replace('_', ' '),           # "source ip"
            ]
            # Also add specific known labels
            _LABEL_MAP = {
                'vmid': 'VM/CT', 'vmname': 'Name', 'source_ip': 'Source IP',
                'service_name': 'Service', 'node_name': 'Node',
                'target_node': 'Target', 'total_count': 'Total updates',
                'security_count': 'Security updates', 'pve_count': 'Proxmox-related updates',
                'kernel_count': 'Kernel updates', 'important_list': 'Important packages',
                'duration': 'Duration', 'severity': 'Previous severity',
                'original_severity': 'Previous severity',
                'current_version': 'Currently installed',
                'latest_version': 'Latest available',
                'menu_label': 'From the ProxMenux post-install menu',
            }
            if field_key in _LABEL_MAP:
                label_variants.append(_LABEL_MAP[field_key])
            
            for label in label_variants:
                if stripped.lower().startswith(label.lower() + ':'):
                    enriched_lines.append(f'{field_icon} {stripped}')
                    enriched = True
                    break
                elif stripped.lower().startswith(label.lower() + ' '):
                    enriched_lines.append(f'{field_icon} {stripped}')
                    enriched = True
                    break
            if enriched:
                break
        
        if not enriched:
            enriched_lines.append(line)
    
    enriched_body = '\n'.join(enriched_lines)
    
    return enriched_title, enriched_body


# ─── AI Enhancement (Optional) ───────────────────────────────────

# Supported languages for AI translation
AI_LANGUAGES = {
    'en': 'English',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'pt': 'Portuguese',
    'it': 'Italian',
    'ru': 'Russian',
    'sv': 'Swedish',
    'no': 'Norwegian',
    'ja': 'Japanese',
    'zh': 'Chinese',
    'nl': 'Dutch',
}

# Token limits for different detail levels
# max_tokens is a LIMIT, not fixed consumption - you only pay for tokens actually generated
# Note: Some providers (especially Gemini) may have lower default limits, so we use generous values
AI_DETAIL_TOKENS = {
    'brief': 500,      # Short messages, 2-3 lines
    'standard': 1500,  # Standard messages, sufficient for 15-20 VMs
    'detailed': 3000,  # Complete technical reports with all details
}

# System prompt template - optimized hybrid version
AI_SYSTEM_PROMPT = """You are a notification FORMATTER for ProxMenux Monitor (Proxmox VE).
Your job: translate alerts into {language} and enrich them with context when provided.

═══ ABSOLUTE CONSTRAINTS (NO EXCEPTIONS) ═══
- NO HALLUCINATIONS: Do not invent causes, solutions, or facts not present in the provided data
- NO SPECULATION: If something is unclear, state what IS known, not what MIGHT be
- NO FILLER LINES: Every output line must derive from the input message, the journal context,
  or the known-error database. NEVER add generic statements like "Event detected during normal
  operation", "No further issues", or padding lines just to fill space. If a field has no evidence,
  OMIT it — a shorter output is always better than invented content.
- 📝 Log lines: ONLY include when the journal context contains an actual relevant log line.
  Convey its meaning faithfully, do not invent one. If no relevant log exists, OMIT the 📝 line.
- ⏱️ Duration/timing lines: ONLY for backup/migration durations explicitly present in the input.
  NEVER use ⏱️ for vague "event detected at X" filler.
- NO CONVERSATIONAL TEXT: Never write "Here is...", "I've translated...", "Let me explain..."
- ONLY use information from: the message, journal context, and known error database (if provided)

═══ WHAT TO TRANSLATE ═══
Translate: labels, descriptions, status words, units (GB→Go in French, etc.)
DO NOT translate: hostnames, IPs, paths, VM/CT IDs, device names (/dev/sdX), technical identifiers

═══ CORE RULES ═══
1. Plain text only — NO markdown, no **bold**, no `code`, no bullet lists (use "• " for packages only)
2. Preserve severity: "failed" stays "failed", "warning" stays "warning" — never soften errors
3. Preserve structure: keep same fields and line order, only translate content
4. Detail level "{detail_level}" - controls AMOUNT OF EVENT INFO (not tips/suggestions):
   - brief: 1-2 lines max. Only: what happened + where
   - standard: 3-6 lines. Include: what, where, cause, affected devices
   - detailed: Full report with ALL info: what, where, cause, affected, logs, SMART data, history
5. DEDUPLICATION: merge duplicate facts from multiple sources into one clear statement
6. EMPTY LISTS: write translated "none" after label, never leave blank
7. Keep "hostname:" prefix in title — translate only the descriptive part
8. DO NOT add recommendations or suggestions UNLESS AI Suggestions mode is enabled below
9. ENRICHED CONTEXT: You may receive additional context data including:
   - "System uptime: X days (stable system)" → helps distinguish startup issues from runtime failures
   - "Event frequency: N occurrences, first seen X ago" → indicates recurring vs one-time issues
   - "SMART Health: PASSED/FAILED" with disk attributes → critical for disk errors
   - "KNOWN PROXMOX ERROR DETECTED" with cause/solution → YOU MUST USE this exact information
   
   How to use enriched context:
   - If uptime is <10min and error is service-related → mention "occurred shortly after boot"
   - If frequency shows recurring pattern → mention "recurring issue (N times in X hours)"
   - If SMART shows FAILED → treat as CRITICAL: "Disk failing - immediate attention required"
   - If KNOWN ERROR is provided → YOU MUST incorporate its Cause and Solution (translate, don't copy verbatim)

10. JOURNAL CONTEXT EXTRACTION: When journal logs are provided:
   - Extract specific IDs (VM/CT numbers, disk devices, service names)
   - Include relevant timestamps if they help explain the timeline
   - Identify root cause when logs clearly show it (e.g., "exit-code 255" -> "process crashed")
   - Translate technical terms: "Emask 0x10" -> "ATA bus error", "DRDY ERR" -> "drive not ready"
   - If logs show the same error repeating, state frequency: "occurred 15 times in 10 minutes"
   - IGNORE journal entries unrelated to the main event
11. OUTPUT ONLY the final result — no "Original:", no before/after comparisons
12. Unknown input: preserve as closely as possible, translate what you can
13. REDUNDANCY: Never repeat the same information twice. If title says "CT 103 failed", body should not start with "Container 103 failed"
{suggestions_addon}
═══ PROXMOX MAPPINGS (use directly, never explain) ═══
pve-container@XXXX → "CT XXXX" | qemu-server@XXXX → "VM XXXX" | vzdump → "backup"
pveproxy/pvedaemon/pvestatd → "Proxmox service" | corosync → "cluster service"
"ata8.00: exception Emask..." → "ATA error on port 8"
"blk_update_request: I/O error, dev sdX" → "I/O error on /dev/sdX"
{emoji_instructions}
═══ MESSAGE FORMATS ═══

BACKUP: List each VM/CT with status/size/duration/storage. End with summary.
  - Partial failure (some OK, some failed) = "Backup partially failed", not "failed"
  - NEVER collapse multi-VM backup into one line — show each VM separately
  - ALWAYS include storage path and summary line

UPDATES: Counts on own lines. Packages use "• " under header. No redundant summary.

DISK/SMART: Device + specific error. Deduplicate repeated info.

HEALTH: Category + severity + what changed. Duration if resolved.

VM/CT LIFECYCLE: Confirm event with key facts (1-2 lines).

═══ OUTPUT FORMAT (CRITICAL - MUST FOLLOW EXACTLY) ═══

Your response MUST have EXACTLY this structure:
[TITLE]
your translated title text
[BODY]
your translated body text

ABSOLUTE RULES (violations break the parser):
1. [TITLE] and [BODY] are INVISIBLE PARSING MARKERS — they separate title from body
2. Your actual title/body content must NEVER contain the words "[TITLE]" or "[BODY]"
3. Your actual title/body content must NEVER contain "Title:" or "Body:" prefixes
4. Line 1: write exactly [TITLE]
5. Line 2: write your title text (emoji + hostname: description)
6. Line 3: write exactly [BODY]
7. Line 4+: write your body text

WRONG (markers appear in content):
[TITLE]
🔵 server: [TITLE] Updates available
[BODY]
[BODY] 153 updates available

CORRECT (markers are separators only):
[TITLE]
🔵 server: Updates available
[BODY]
153 updates available

- Output ONLY the formatted result — no explanations, no "Original:", no commentary"""

# Addon for experimental suggestions mode
AI_SUGGESTIONS_ADDON = """
═══ AI SUGGESTIONS MODE (ENABLED) ═══
You MAY add ONE brief, actionable tip at the END of the body using this exact format:

💡 Tip: [your concise suggestion here]

Rules for the tip:
- ONLY include if the log context or Known Error database clearly points to a specific fix
- Keep under 100 characters
- Be specific: "Run 'pvecm status' to check quorum" NOT "Check cluster status"
- If Known Error provides a solution, YOU MUST USE IT (don't invent your own)
- Never guess — skip the tip if the cause/solution is unclear
"""

# Emoji instructions injected into AI_SYSTEM_PROMPT for rich channels (Telegram, Discord, Pushover)
AI_EMOJI_INSTRUCTIONS = """
═══ EMOJI ENRICHMENT (VISUAL CLARITY) ═══
Your goal is to maintain the original structure of the message while using emojis to add visual clarity,
ESPECIALLY when adding new context, formatting technical data, or writing tips.

RULES:
1. PRESERVE BASE STRUCTURE AND INPUT EMOJIS: Respect the original fields and layout provided in
   the input message. **CRITICAL: every emoji already present in the input (📊, 🏷️, 📦, 🔒, 🛠️,
   💡, ⚠️, ✨, 🌐, 🔥, 💧, 📝, ⏱️, etc.) MUST appear in the output, in the same position relative
   to its label.** Translating the surrounding words is fine; deleting or relocating the emoji is
   not. You may add additional context-appropriate emojis from BODY EMOJIS below, but never strip
   the ones the template already provides.
2. ENHANCE WITH ICONS: Place emojis at the START of a line to identify the data type.
3. NEW CONTEXT: When adding journal info, SMART data, or known errors, use appropriate icons to make it readable.
4. NO SPAM: Do not put emojis in the middle or end of sentences. Use 1-3 emojis at START of lines where they add clarity. Combine when meaningful (💾✅ backup ok).
  5. HIGHLIGHT ONLY: Use emojis to highlight, not as filler. Blank lines = completely empty.

TITLE EMOJIS:
✅ success  ❌ failed  💥 crash  🆘 critical  📦 updates  🆕 pve-update  🚚 migration
⏹️ stop  🔽 shutdown  ⚠️ warning  💢 split-brain  🔌 disconnect  🚨 auth-fail  🚷 banned  📋 digest
🚀 = something STARTS (VM/CT start, backup start, server boot, task begin)
Combine: 💾🚀 backup-start  🖥️🚀 system-boot  🚀 VM/CT-start

BODY EMOJIS:
🏷️ VM/CT name  ✔️ ok  ❌ error  💽 size  💾 total  ⏱️ duration  🗄️ storage  📊 summary
📦 updates  🔒 security  🔄 proxmox  ⚙️ kernel  🗂️ packages  💿 disk  📝 reason/log
🌐 IP  👤 user  🌡️ temp  🔥 CPU  💧 RAM  🎯 target  🔹 current  🟢 new  📌 item

BLANK LINES: Insert between logical sections (VM entries, before summary, before packages block).

═══ EXAMPLES (follow these formats) ═══

BACKUP START:
[TITLE]
💾🚀 constructor: Backup started
[BODY]
Backup job starting on storage PBS.
🏷️ VMs: web01 (100)

🗄️ Storage: PBS  |  ⚙️ Mode: stop

BACKUP COMPLETE:
[TITLE]
💾✅ amd: Backup complete
[BODY]
Backup job finished on storage local-bak.

🏷️ VM web01 (ID: 100)
✔️ Status: ok
💽 Size: 12.3 GiB
⏱️ Duration: 00:04:21
🗄️ Storage: vm/100/2026-03-17T22:00:08Z

📊 Total: 1 backup | 💾 12.3 GiB | ⏱️ 00:04:21

BACKUP PARTIAL FAIL:
[TITLE]
💾❌ pve05: Backup partially failed
[BODY]
Backup job finished with errors.

🏷️ VM web01 (ID: 100)
✔️ Status: ok
💽 Size: 12.3 GiB

🏷️ VM broken (ID: 102)
❌ Status: error

📊 Total: 2 backups | ❌ 1 failed

UPDATES:
[TITLE]
📦 amd: Updates available
[BODY]
📦 Total updates: 24
🔒 Security updates: 6
🔄 Proxmox updates: 0

🗂️ Important packages:
• none

VM/CT START:
[TITLE]
🚀 pve01: VM arch-linux (100) started
[BODY]
🏷️ Virtual machine arch-linux (ID: 100)
✔️ Now running

HEALTH DEGRADED:
[TITLE]
⚠️ constructor: Health warning — Disk I/O
[BODY]
💿 Device: /dev/sda
⚠️ 1 sector unreadable (pending)
📝 Log: process crashed (exit-code 255)
⚠️ Recurring: 5 times in 24h
💡 Tip: Run 'systemctl status pvedaemon'"""


# No emoji instructions for email/plain text channels
AI_NO_EMOJI_INSTRUCTIONS = """
DO NOT use any emojis or special Unicode symbols. Plain ASCII text only for email compatibility."""


class AIEnhancer:
    """AI message enhancement using pluggable providers.
    
    Supports 6 providers: Groq, OpenAI, Anthropic, Gemini, Ollama, OpenRouter.
    Translates and formats notifications based on configured language and detail level.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize AIEnhancer with configuration.
        
        Args:
            config: Dictionary containing:
                - ai_provider: Provider name (groq, openai, anthropic, gemini, ollama, openrouter)
                - ai_api_key: API key (not required for ollama)
                - ai_model: Optional model override
                - ai_language: Target language code (en, es, fr, etc.)
                - ai_ollama_url: URL for Ollama server (optional)
        """
        self.config = config
        self._provider = None
        self._init_provider()
    
    def _init_provider(self):
        """Initialize the AI provider based on configuration."""
        try:
            # Import here to avoid circular imports
            import sys
            import os
            
            # Add script directory to path for ai_providers import
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            
            from ai_providers import get_provider
            
            provider_name = self.config.get('ai_provider', 'groq')
            
            # Determine base_url based on provider
            if provider_name == 'ollama':
                base_url = self.config.get('ai_ollama_url', '')
            elif provider_name == 'openai':
                base_url = self.config.get('ai_openai_base_url', '')
            else:
                base_url = ''
            
            self._provider = get_provider(
                provider_name,
                api_key=self.config.get('ai_api_key', ''),
                model=self.config.get('ai_model', ''),
                base_url=base_url,
            )
        except Exception as e:
            print(f"[AIEnhancer] Failed to initialize provider: {e}")
            self._provider = None
    
    @property
    def enabled(self) -> bool:
        """Check if AI enhancement is available."""
        return self._provider is not None
    
    def enhance(self, title: str, body: str, severity: str,
                detail_level: str = 'standard',
                journal_context: str = '',
                use_emojis: bool = False) -> Optional[Dict[str, str]]:
        """Enhance/translate notification with AI.
        
        Args:
            title: Notification title
            body: Notification body text
            severity: Severity level (info, warning, critical)
            detail_level: Level of detail (brief, standard, detailed)
            journal_context: Optional journal log lines for context
            use_emojis: Whether to include emojis in the response (for push channels)
            
        Returns:
            Dict with 'title' and 'body' keys, or None if failed
        """
        if not self._provider:
            return None
        
        # Get language settings
        language_code = self.config.get('ai_language', 'en')
        language_name = AI_LANGUAGES.get(language_code, 'English')
        
        # Check for custom prompt mode
        prompt_mode = self.config.get('ai_prompt_mode', 'default')
        custom_prompt = self.config.get('ai_custom_prompt', '')
        
        if prompt_mode == 'custom' and custom_prompt.strip():
            # Custom prompt: user controls everything, use higher token limit
            system_prompt = custom_prompt
            max_tokens = 500  # Allow more tokens for custom prompts
        else:
            # Default prompt: use detail level and emoji settings
            max_tokens = AI_DETAIL_TOKENS.get(detail_level, 200)
            emoji_instructions = AI_EMOJI_INSTRUCTIONS if use_emojis else AI_NO_EMOJI_INSTRUCTIONS
            
            # Check if experimental suggestions mode is enabled
            allow_suggestions = self.config.get('ai_allow_suggestions', 'false')
            if isinstance(allow_suggestions, str):
                allow_suggestions = allow_suggestions.lower() == 'true'
            suggestions_addon = AI_SUGGESTIONS_ADDON if allow_suggestions else ''
            
            system_prompt = AI_SYSTEM_PROMPT.format(
                language=language_name,
                detail_level=detail_level,
                emoji_instructions=emoji_instructions,
                suggestions_addon=suggestions_addon
            )
        
        # Build user message
        user_msg = f"Severity: {severity}\nTitle: {title}\nMessage:\n{body}"
        if journal_context:
            user_msg += f"\n\nJournal log context:\n{journal_context}"
        
        try:
            result = self._provider.generate(system_prompt, user_msg, max_tokens)
            if result is None:
                print(f"[AIEnhancer] Provider returned None - possible timeout or connection issue")
                return None
            return self._parse_ai_response(result, title, body)
        except Exception as e:
            print(f"[AIEnhancer] Enhancement failed: {e}")
            return None
    
    def _parse_ai_response(self, response: str, original_title: str, original_body: str) -> Dict[str, str]:
        """Parse AI response to extract title and body.
        
        Args:
            response: Raw AI response text
            original_title: Original title as fallback
            original_body: Original body as fallback
            
        Returns:
            Dict with 'title' and 'body' keys
        """
        if not response:
            return {'title': original_title, 'body': original_body}
        
        import re
        
        # Try to parse [TITLE] and [BODY] markers (case-insensitive, multiline)
        title_match = re.search(r'\[TITLE\]\s*(.*?)\s*\[BODY\]', response, re.DOTALL | re.IGNORECASE)
        body_match = re.search(r'\[BODY\]\s*(.*)', response, re.DOTALL | re.IGNORECASE)
        
        if title_match and body_match:
            title_content = title_match.group(1).strip()
            body_content = body_match.group(1).strip()
            
            # Remove any "Original message/text" sections the AI might have added.
            # Anchored at start-of-line (`(?:^|\n)\s*`) so legitimate prose
            # like "we received the original message earlier" mid-paragraph
            # is NOT truncated. Without the anchor, `.*` under DOTALL would
            # eat everything from the first matching word to end-of-string.
            # `\Z` matches end-of-string. Audit Tier 6 — `_parse_ai_response`.
            original_patterns = [
                r'(?:^|\n)\s*-{3,}\s*\n+\s*Original message:.*\Z',
                r'(?:^|\n)\s*-{3,}\s*\n+\s*Original:.*\Z',
                r'(?:^|\n)\s*-{3,}\s*\n+\s*Source:.*\Z',
                r'(?:^|\n)\s*-{3,}\s*\n+\s*Mensaje original:.*\Z',
                r'(?:^|\n)\s*Original message:.*\Z',
                r'(?:^|\n)\s*Original text:.*\Z',
                r'(?:^|\n)\s*Mensaje original:.*\Z',
                r'(?:^|\n)\s*Texto original:.*\Z',
            ]
            for pattern in original_patterns:
                body_content = re.sub(pattern, '', body_content, flags=re.DOTALL | re.IGNORECASE).strip()
            
            return {
                'title': title_content if title_content else original_title,
                'body': body_content if body_content else original_body
            }
        
        # No `[TITLE]`/`[BODY]` markers — DO NOT silently substitute the
        # raw response for the body. Some providers return refusal
        # boilerplate ("I can't help with that") or completely off-topic
        # text when the prompt confuses them; using that as the
        # notification body misleads the user. Treat it as a parse failure
        # and fall back to the original template. Audit Tier 7 — `_parse_ai_response`
        # swallowea respuestas sin marcadores.
        return {
            'title': original_title,
            'body': original_body,
        }
    
    def test_connection(self) -> Dict[str, Any]:
        """Test the AI provider connection.
        
        Returns:
            Dict with success, message, and model info
        """
        if not self._provider:
            return {
                'success': False,
                'message': 'Provider not initialized',
                'model': ''
            }
        return self._provider.test_connection()


def format_with_ai(title: str, body: str, severity: str,
                   ai_config: Dict[str, Any],
                   detail_level: str = 'standard',
                   journal_context: str = '',
                   use_emojis: bool = False) -> str:
    """Format a message with AI enhancement/translation.
    
    Replaces the message body with AI-processed version if successful.
    Falls back to original body if AI is unavailable or fails.
    
    Args:
        title: Notification title
        body: Notification body
        severity: Severity level
        ai_config: Configuration dictionary with AI settings
        detail_level: Level of detail (brief, standard, detailed)
        journal_context: Optional journal log context
        use_emojis: Whether to include emojis (for push channels like Telegram/Discord)
    
    Returns:
        Enhanced body string or original if AI fails
    """
    result = format_with_ai_full(title, body, severity, ai_config, detail_level, journal_context, use_emojis)
    return result.get('body', body)


# LRU-style response cache for `format_with_ai_full`. A burst summary
# (e.g. "5 segfaults in 90s") with the same title/body fires once per
# channel + once per detail-level — without a cache that's N identical
# AI calls back-to-back. 60s TTL covers the burst window without
# letting a stale rewrite outlive the original event. Audit Tier 7 —
# Sin response cache.
import time as _time_ai_cache
import hashlib as _hash_ai_cache
import threading as _threading_ai_cache
_AI_CACHE_LOCK = _threading_ai_cache.Lock()
_AI_CACHE: Dict[str, tuple] = {}  # key → (ts, result_dict)
_AI_CACHE_TTL = 60.0
_AI_CACHE_MAX = 256


def _ai_cache_key(title, body, ai_config, detail_level, use_emojis):
    parts = [
        title or '', '\x1f', body or '', '\x1f',
        str(ai_config.get('ai_provider', '')), '\x1f',
        str(ai_config.get('ai_model', '')), '\x1f',
        str(ai_config.get('ai_language', '')), '\x1f',
        detail_level, '\x1f', '1' if use_emojis else '0',
    ]
    return _hash_ai_cache.sha256(''.join(parts).encode('utf-8', 'replace')).hexdigest()


def format_with_ai_full(title: str, body: str, severity: str,
                        ai_config: Dict[str, Any],
                        detail_level: str = 'standard',
                        journal_context: str = '',
                        use_emojis: bool = False) -> Dict[str, str]:
    """Format a message with AI enhancement/translation, returning both title and body.

    Args:
        title: Notification title
        body: Notification body
        severity: Severity level
        ai_config: Configuration dictionary with AI settings
        detail_level: Level of detail (brief, standard, detailed)
        journal_context: Optional journal log context
        use_emojis: Whether to include emojis (for push channels like Telegram/Discord)

    Returns:
        Dict with 'title' and 'body' keys (translated/enhanced)
    """
    default_result = {'title': title, 'body': body}

    # Check if AI is enabled
    ai_enabled = ai_config.get('ai_enabled')
    if isinstance(ai_enabled, str):
        ai_enabled = ai_enabled.lower() == 'true'

    if not ai_enabled:
        return default_result

    # Per-severity gating: skip the AI rewrite when the event severity is
    # below `ai_min_severity` (config). Useful to limit cost/latency to
    # only the events that benefit from a rewrite. Default `info` keeps
    # the previous behaviour of rewriting everything. Audit Tier 7 — sin
    # per-event/per-severity AI gating.
    _SEVERITY_RANK = {
        'info': 0, 'INFO': 0, 'OK': 0,
        'warning': 1, 'WARNING': 1, 'WARN': 1,
        'error': 2, 'ERROR': 2,
        'critical': 3, 'CRITICAL': 3,
    }
    min_sev = (ai_config.get('ai_min_severity') or 'info').lower()
    if min_sev not in _SEVERITY_RANK:
        min_sev = 'info'
    event_rank = _SEVERITY_RANK.get(severity, _SEVERITY_RANK.get((severity or '').lower(), 0))
    min_rank = _SEVERITY_RANK[min_sev]
    if event_rank < min_rank:
        return default_result

    # Check for API key (not required for Ollama)
    provider = ai_config.get('ai_provider', 'groq')
    if provider != 'ollama' and not ai_config.get('ai_api_key'):
        return default_result

    # For Ollama, check URL is configured
    if provider == 'ollama' and not ai_config.get('ai_ollama_url'):
        return default_result

    # Cache lookup — same title/body/provider/model/lang/detail_level
    # within 60s reuses the previous rewrite. journal_context is
    # intentionally NOT part of the key (it changes per dispatch but
    # the AI rewrite is dominated by title/body anyway).
    cache_key = _ai_cache_key(title, body, ai_config, detail_level, use_emojis)
    now = _time_ai_cache.monotonic()
    with _AI_CACHE_LOCK:
        cached = _AI_CACHE.get(cache_key)
        if cached and now - cached[0] < _AI_CACHE_TTL:
            return dict(cached[1])

    # Create enhancer and process
    enhancer = AIEnhancer(ai_config)
    enhanced = enhancer.enhance(
        title, body, severity,
        detail_level=detail_level,
        journal_context=journal_context,
        use_emojis=use_emojis
    )
    
    # Return enhanced result if successful, otherwise original
    if enhanced and isinstance(enhanced, dict):
        result_title = enhanced.get('title', title)
        result_body = enhanced.get('body', body)
        
        # For email channel with detailed level, append original message for reference
        # This ensures full technical data is available even after AI processing
        # Only for email - other channels (Telegram, Discord, Gotify) should not get duplicates
        channel_type = ai_config.get('channel_type', '').lower()
        is_email = channel_type == 'email'
        
        if is_email and detail_level == 'detailed' and body and len(body) > 50:
            # Only append if original has substantial content
            result_body += "\n\n" + "-" * 40 + "\n"
            result_body += "Original message:\n"
            result_body += body

        result = {'title': result_title, 'body': result_body}
        with _AI_CACHE_LOCK:
            # Bound the cache size — drop the oldest entry if we exceed
            # the cap (we accept slight staleness over unbounded growth).
            if len(_AI_CACHE) >= _AI_CACHE_MAX:
                oldest = min(_AI_CACHE.items(), key=lambda kv: kv[1][0])[0]
                _AI_CACHE.pop(oldest, None)
            _AI_CACHE[cache_key] = (now, result)
        return result

    return default_result
