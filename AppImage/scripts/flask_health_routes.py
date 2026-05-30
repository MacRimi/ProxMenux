"""
Flask routes for health monitoring with persistence support
"""

from flask import Blueprint, jsonify, request
from health_monitor import health_monitor
from health_persistence import health_persistence

# Sprint 13: remote-mount monitor (NFS/CIFS/SMB) — separate module so a
# missing helper doesn't crash the health blueprint.
try:
    import mount_monitor
    MOUNT_MONITOR_AVAILABLE = True
except ImportError:
    MOUNT_MONITOR_AVAILABLE = False

health_bp = Blueprint('health', __name__)

@health_bp.route('/api/health/status', methods=['GET'])
def get_health_status():
    """Get overall health status summary"""
    try:
        status = health_monitor.get_overall_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/details', methods=['GET'])
def get_health_details():
    """Get detailed health status with all checks"""
    try:
        details = health_monitor.get_detailed_status()
        return jsonify(details)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/system-info', methods=['GET'])
def get_system_info():
    """
    Get lightweight system info for header display.
    Returns: hostname, uptime, and health status with proper structure.
    """
    try:
        info = health_monitor.get_system_info()
        
        if 'health' in info:
            status_map = {
                'OK': 'healthy',
                'WARNING': 'warning',
                'CRITICAL': 'critical',
                'UNKNOWN': 'warning'
            }
            current_status = info['health'].get('status', 'OK').upper()
            info['health']['status'] = status_map.get(current_status, 'healthy')
        
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/acknowledge', methods=['POST'])
def acknowledge_error():
    """
    Acknowledge/dismiss an error manually.
    Returns details about the acknowledged error including original severity
    and suppression period info.

    Body accepts an optional ``suppression_hours`` field — if omitted the
    server uses the user-configured value for the error's category (current
    behavior). When provided, the value overrides the category default for
    this specific dismiss:
      - positive integer N → silence for N hours
      - ``-1`` → silence permanently (only revertible from
        Settings → Active Suppressions)
    """
    try:
        data = request.get_json()
        if not data or 'error_key' not in data:
            return jsonify({'error': 'error_key is required'}), 400

        error_key = data['error_key']
        sup_override = None
        if 'suppression_hours' in data and data['suppression_hours'] is not None:
            try:
                sup_override = int(data['suppression_hours'])
                # Accept positive durations and the permanent sentinel (-1)
                # only. Zero / other negatives would be nonsensical here.
                if sup_override < -1 or sup_override == 0:
                    return jsonify({'error': 'suppression_hours must be a positive integer or -1 (permanent)'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'suppression_hours must be an integer'}), 400
        result = health_persistence.acknowledge_error(error_key, suppression_hours=sup_override)
        
        if result.get('success'):
            # Invalidate cached health results so next fetch reflects the dismiss
            # Use the error's category to clear the correct cache
            category = result.get('category', '')
            cache_key_map = {
                'logs': 'logs_analysis',
                'pve_services': 'pve_services',
                'updates': 'updates_check',
                'security': 'security_check',
                'temperature': 'cpu_check',
                'network': 'network_check',
                'disks': 'storage_check',
                'vms': 'vms_check',
            }
            cache_key = cache_key_map.get(category)
            if cache_key:
                health_monitor.last_check_times.pop(cache_key, None)
                health_monitor.cached_results.pop(cache_key, None)
            
            # Also invalidate ALL background/overall caches so next fetch reflects dismiss
            for ck in ['_bg_overall', '_bg_detailed', 'overall_health']:
                health_monitor.last_check_times.pop(ck, None)
                health_monitor.cached_results.pop(ck, None)
            
            # Use the per-record suppression hours from acknowledge_error()
            sup_hours = result.get('suppression_hours', 24)
            if sup_hours == -1:
                suppression_label = 'permanently'
            elif sup_hours >= 8760:
                suppression_label = f'{sup_hours // 8760} year(s)'
            elif sup_hours >= 720:
                suppression_label = f'{sup_hours // 720} month(s)'
            elif sup_hours >= 168:
                suppression_label = f'{sup_hours // 168} week(s)'
            elif sup_hours >= 72:
                suppression_label = f'{sup_hours // 24} day(s)'
            else:
                suppression_label = f'{sup_hours} hours'
            
            return jsonify({
                'success': True,
                'message': f'Error dismissed for {suppression_label}',
                'error_key': error_key,
                'original_severity': result.get('original_severity', 'WARNING'),
                'category': category,
                'suppression_hours': sup_hours,
                'suppression_label': suppression_label,
                'acknowledged_at': result.get('acknowledged_at')
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Error not found or already dismissed',
                'error_key': error_key
            }), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/un-acknowledge', methods=['POST'])
def unacknowledge_error():
    """
    Re-enable a previously dismissed error.

    Used by Settings → Active Suppressions when the user explicitly removes
    a suppression (time-limited or permanent). After this call the error
    becomes eligible to re-emit and re-notify on the next health scan if
    the underlying condition is still present.

    Body: ``{"error_key": "<key>"}``
    """
    try:
        data = request.get_json()
        if not data or 'error_key' not in data:
            return jsonify({'error': 'error_key is required'}), 400
        error_key = data['error_key']
        result = health_persistence.unacknowledge_error(error_key)

        # Invalidate caches so the next health fetch reflects the new state
        # (the alert may re-appear immediately if the condition still holds).
        category = result.get('category', '')
        cache_key_map = {
            'logs': 'logs_analysis',
            'pve_services': 'pve_services',
            'updates': 'updates_check',
            'security': 'security_check',
            'temperature': 'cpu_check',
            'network': 'network_check',
            'disks': 'storage_check',
            'vms': 'vms_check',
        }
        cache_key = cache_key_map.get(category)
        if cache_key:
            health_monitor.last_check_times.pop(cache_key, None)
            health_monitor.cached_results.pop(cache_key, None)
        for ck in ['_bg_overall', '_bg_detailed', 'overall_health']:
            health_monitor.last_check_times.pop(ck, None)
            health_monitor.cached_results.pop(ck, None)

        if not result.get('success'):
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/active-errors', methods=['GET'])
def get_active_errors():
    """Get all active persistent errors"""
    try:
        category = request.args.get('category')
        errors = health_persistence.get_active_errors(category)
        return jsonify({'errors': errors})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/dismissed', methods=['GET'])
def get_dismissed_errors():
    """
    Get dismissed errors that are still within their suppression period.
    These are shown as INFO items with a 'Dismissed' badge in the frontend.
    """
    try:
        dismissed = health_persistence.get_dismissed_errors()
        return jsonify({'dismissed': dismissed})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/full', methods=['GET'])
def get_full_health():
    """
    Get complete health data in a single request: detailed status + active errors + dismissed.
    Uses background-cached results if fresh (< 6 min) for instant response,
    otherwise runs a fresh check.
    """
    import time as _time
    try:
        # Try to use the background-cached detailed result for instant response
        bg_key = '_bg_detailed'
        bg_last = health_monitor.last_check_times.get(bg_key, 0)
        bg_age = _time.time() - bg_last
        
        if bg_age < 360 and bg_key in health_monitor.cached_results:
            # Use cached result (at most ~5 min old)
            details = health_monitor.cached_results[bg_key]
        else:
            # No fresh cache, run live (first load or cache expired)
            details = health_monitor.get_detailed_status()
        
        active_errors = health_persistence.get_active_errors()
        dismissed = health_persistence.get_dismissed_errors()
        custom_suppressions = health_persistence.get_custom_suppressions()
        
        return jsonify({
            'health': details,
            'active_errors': active_errors,
            'dismissed': dismissed,
            'custom_suppressions': custom_suppressions,
            'timestamp': details.get('timestamp')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/cleanup-orphans', methods=['POST'])
def cleanup_orphan_errors():
    """
    Clean up errors for devices that no longer exist in the system.
    Useful when USB drives or temporary devices are disconnected.
    """
    import os
    import re
    try:
        cleaned = []
        # Get all active disk errors
        disk_errors = health_persistence.get_active_errors(category='disks')
        
        for err in disk_errors:
            err_key = err.get('error_key', '')
            details = err.get('details', {})
            if isinstance(details, str):
                try:
                    import json as _json
                    details = _json.loads(details)
                except Exception:
                    details = {}
            
            device = details.get('device', '')
            base_disk = details.get('disk', '')
            
            # Try to determine the device path
            dev_path = None
            if base_disk:
                dev_path = f'/dev/{base_disk}'
            elif device:
                dev_path = device if device.startswith('/dev/') else f'/dev/{device}'
            elif err_key.startswith('disk_'):
                # Extract device from error_key
                dev_name = err_key.replace('disk_fs_', '').replace('disk_', '')
                dev_name = re.sub(r'_.*$', '', dev_name)  # Remove suffix
                if dev_name:
                    dev_path = f'/dev/{dev_name}'
            
            if dev_path:
                # Also check base disk (remove partition number)
                base_path = re.sub(r'\d+$', '', dev_path)
                if not os.path.exists(dev_path) and not os.path.exists(base_path):
                    health_persistence.resolve_error(err_key, 'Device no longer present (manual cleanup)')
                    cleaned.append({'error_key': err_key, 'device': dev_path})
        
        # Also cleanup disk_observations for non-existent devices
        try:
            health_persistence.cleanup_orphan_observations()
        except Exception:
            pass
        
        return jsonify({
            'success': True,
            'cleaned_count': len(cleaned),
            'cleaned_errors': cleaned
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/pending-notifications', methods=['GET'])
def get_pending_notifications():
    """
    Get events pending notification (for future Telegram/Gotify/Discord integration).
    This endpoint will be consumed by the Notification Service (Bloque A).
    """
    try:
        pending = health_persistence.get_pending_notifications()
        return jsonify({'pending': pending, 'count': len(pending)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@health_bp.route('/api/health/mark-notified', methods=['POST'])
def mark_events_notified():
    """
    Mark events as notified after notification was sent successfully.
    Used by the Notification Service (Bloque A) after sending alerts.
    """
    try:
        data = request.get_json()
        if not data or 'event_ids' not in data:
            return jsonify({'error': 'event_ids array is required'}), 400
        
        event_ids = data['event_ids']
        if not isinstance(event_ids, list):
            return jsonify({'error': 'event_ids must be an array'}), 400
        
        health_persistence.mark_events_notified(event_ids)
        return jsonify({'success': True, 'marked_count': len(event_ids)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/settings', methods=['GET'])
def get_health_settings():
    """
    Get per-category suppression duration settings.
    Returns all health categories with their current configured hours.
    """
    try:
        categories = health_persistence.get_suppression_categories()
        return jsonify({'categories': categories})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/settings', methods=['POST'])
def save_health_settings():
    """
    Save per-category suppression duration settings.
    Expects JSON body with key-value pairs like: {"suppress_cpu": "168", "suppress_memory": "-1"}
    Valid values: 24, 72, 168, 720, 8760, -1 (permanent), or any positive integer for custom.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No settings provided'}), 400
        
        valid_keys = set(health_persistence.CATEGORY_SETTING_MAP.values())
        updated = []
        
        for key, value in data.items():
            if key not in valid_keys:
                continue
            
            try:
                hours = int(value)
                # Validate: must be -1 (permanent) or positive
                if hours != -1 and hours < 1:
                    continue
                health_persistence.set_setting(key, str(hours))
                updated.append(key)
            except (ValueError, TypeError):
                continue
        
        # Retroactively sync all existing dismissed errors
        # so changes are effective immediately, not just on next dismiss
        synced_count = health_persistence.sync_dismissed_suppression()
        
        return jsonify({
            'success': True,
            'updated': updated,
            'count': len(updated),
            'synced_dismissed': synced_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Remote Storage Exclusions Endpoints ──

@health_bp.route('/api/health/remote-storages', methods=['GET'])
def get_remote_storages():
    """
    Get list of all remote storages with their exclusion status.
    Remote storages are those that can be offline (PBS, NFS, CIFS, etc.)
    """
    try:
        from proxmox_storage_monitor import proxmox_storage_monitor
        
        # Get current storage status
        storage_status = proxmox_storage_monitor.get_storage_status()
        all_storages = storage_status.get('available', []) + storage_status.get('unavailable', [])
        
        # Filter to only remote types
        remote_types = health_persistence.REMOTE_STORAGE_TYPES
        remote_storages = [s for s in all_storages if s.get('type', '').lower() in remote_types]
        
        # Get current exclusions
        exclusions = {e['storage_name']: e for e in health_persistence.get_excluded_storages()}
        
        # Combine info
        result = []
        for storage in remote_storages:
            name = storage.get('name', '')
            exclusion = exclusions.get(name, {})
            result.append({
                'name': name,
                'type': storage.get('type', 'unknown'),
                'status': storage.get('status', 'unknown'),
                'total': storage.get('total', 0),
                'used': storage.get('used', 0),
                'available': storage.get('available', 0),
                'percent': storage.get('percent', 0),
                'exclude_health': exclusion.get('exclude_health', 0) == 1,
                'exclude_notifications': exclusion.get('exclude_notifications', 0) == 1,
                'excluded_at': exclusion.get('excluded_at'),
                'reason': exclusion.get('reason')
            })
        
        return jsonify({
            'storages': result,
            'remote_types': list(remote_types)
        })
    except ImportError:
        return jsonify({'error': 'Storage monitor not available', 'storages': []}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/storage-exclusions', methods=['GET'])
def get_storage_exclusions():
    """Get all storage exclusions."""
    try:
        exclusions = health_persistence.get_excluded_storages()
        return jsonify({'exclusions': exclusions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/storage-exclusions', methods=['POST'])
def save_storage_exclusion():
    """
    Add or update a storage exclusion.
    
    Request body:
    {
        "storage_name": "pbs-backup",
        "storage_type": "pbs",
        "exclude_health": true,
        "exclude_notifications": true,
        "reason": "PBS server is offline daily"
    }
    """
    try:
        data = request.get_json()
        if not data or 'storage_name' not in data:
            return jsonify({'error': 'storage_name is required'}), 400
        
        storage_name = data['storage_name']
        storage_type = data.get('storage_type', 'unknown')
        exclude_health = data.get('exclude_health', True)
        exclude_notifications = data.get('exclude_notifications', True)
        reason = data.get('reason')
        
        # Check if already excluded
        existing = health_persistence.get_excluded_storages()
        exists = any(e['storage_name'] == storage_name for e in existing)
        
        if exists:
            # Update existing
            success = health_persistence.update_storage_exclusion(
                storage_name, exclude_health, exclude_notifications
            )
        else:
            # Add new
            success = health_persistence.exclude_storage(
                storage_name, storage_type, exclude_health, exclude_notifications, reason
            )
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Storage {storage_name} exclusion saved',
                'storage_name': storage_name
            })
        else:
            return jsonify({'error': 'Failed to save exclusion'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/storage-exclusions/<storage_name>', methods=['DELETE'])
def delete_storage_exclusion(storage_name):
    """Remove a storage from the exclusion list."""
    try:
        success = health_persistence.remove_storage_exclusion(storage_name)
        if success:
            return jsonify({
                'success': True,
                'message': f'Storage {storage_name} removed from exclusions'
            })
        else:
            return jsonify({'error': 'Storage not found in exclusions'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# NETWORK INTERFACE EXCLUSION ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@health_bp.route('/api/health/interfaces', methods=['GET'])
def get_network_interfaces():
    """Get all network interfaces with their exclusion status."""
    try:
        import psutil
        
        # Get all interfaces
        net_if_stats = psutil.net_if_stats()
        net_if_addrs = psutil.net_if_addrs()
        
        # Get current exclusions
        exclusions = {e['interface_name']: e for e in health_persistence.get_excluded_interfaces()}
        
        result = []
        for iface, stats in net_if_stats.items():
            if iface == 'lo':
                continue
            
            # Determine interface type
            if iface.startswith('vmbr'):
                iface_type = 'bridge'
            elif iface.startswith('bond'):
                iface_type = 'bond'
            elif iface.startswith(('vlan', 'veth')):
                iface_type = 'vlan'
            elif iface.startswith(('eth', 'ens', 'enp', 'eno')):
                iface_type = 'physical'
            else:
                iface_type = 'other'
            
            # Get IP address if any
            ip_addr = None
            if iface in net_if_addrs:
                for addr in net_if_addrs[iface]:
                    if addr.family == 2:  # IPv4
                        ip_addr = addr.address
                        break
            
            exclusion = exclusions.get(iface, {})
            result.append({
                'name': iface,
                'type': iface_type,
                'is_up': stats.isup,
                'speed': stats.speed,
                'ip_address': ip_addr,
                'exclude_health': exclusion.get('exclude_health', 0) == 1,
                'exclude_notifications': exclusion.get('exclude_notifications', 0) == 1,
                'excluded_at': exclusion.get('excluded_at'),
                'reason': exclusion.get('reason')
            })
        
        # Sort: bridges first, then physical, then others
        type_order = {'bridge': 0, 'bond': 1, 'physical': 2, 'vlan': 3, 'other': 4}
        result.sort(key=lambda x: (type_order.get(x['type'], 5), x['name']))
        
        return jsonify({'interfaces': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/interface-exclusions', methods=['GET'])
def get_interface_exclusions():
    """Get all interface exclusions."""
    try:
        exclusions = health_persistence.get_excluded_interfaces()
        return jsonify({'exclusions': exclusions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/interface-exclusions', methods=['POST'])
def save_interface_exclusion():
    """
    Add or update an interface exclusion.
    
    Request body:
    {
        "interface_name": "vmbr0",
        "interface_type": "bridge",
        "exclude_health": true,
        "exclude_notifications": true,
        "reason": "Intentionally disabled bridge"
    }
    """
    try:
        data = request.get_json()
        if not data or 'interface_name' not in data:
            return jsonify({'error': 'interface_name is required'}), 400
        
        interface_name = data['interface_name']
        interface_type = data.get('interface_type', 'unknown')
        exclude_health = data.get('exclude_health', True)
        exclude_notifications = data.get('exclude_notifications', True)
        reason = data.get('reason')
        
        # Check if already excluded
        existing = health_persistence.get_excluded_interfaces()
        exists = any(e['interface_name'] == interface_name for e in existing)
        
        if exists:
            # Update existing
            success = health_persistence.update_interface_exclusion(
                interface_name, exclude_health, exclude_notifications
            )
        else:
            # Add new
            success = health_persistence.exclude_interface(
                interface_name, interface_type, exclude_health, exclude_notifications, reason
            )
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Interface {interface_name} exclusion saved',
                'interface_name': interface_name
            })
        else:
            return jsonify({'error': 'Failed to save exclusion'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/health/interface-exclusions/<interface_name>', methods=['DELETE'])
def delete_interface_exclusion(interface_name):
    """Remove an interface from the exclusion list."""
    try:
        success = health_persistence.remove_interface_exclusion(interface_name)
        if success:
            return jsonify({
                'success': True,
                'message': f'Interface {interface_name} removed from exclusions'
            })
        else:
            return jsonify({'error': 'Interface not found in exclusions'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@health_bp.route('/api/mounts', methods=['GET'])
def get_remote_mounts():
    """Sprint 13: list NFS/CIFS/SMB mounts on the host AND inside every
    running LXC, with per-mount health (reachable / stale / read-only).

    Returns:
      ``mounts`` — host-level remote mounts (Sprint 13.11)
      ``lxc_mounts`` — mounts inside running LXCs (Sprint 13.24)

    Both lists share the same per-row shape; LXC entries add three
    extra fields (lxc_id, lxc_name, lxc_pid). The frontend renders
    them in two separate cards so the user immediately knows whether
    the mount lives on the host or inside a container.
    """
    if not MOUNT_MONITOR_AVAILABLE:
        return jsonify({
            'mounts': [],
            'lxc_mounts': [],
            'available': False,
        })

    try:
        mounts = mount_monitor.scan_remote_mounts()
        # LXC scan is wrapped separately so a flaky `pct exec` doesn't
        # blank the host list. The host scan is cheap and reliable;
        # LXC scan can hit timeouts on stuck containers.
        try:
            lxc_mounts = mount_monitor.scan_lxc_mounts()
        except Exception as lxc_err:
            print(f"[flask_health_routes] LXC mount scan failed: {lxc_err}")
            lxc_mounts = []
        return jsonify({
            'mounts': mounts,
            'lxc_mounts': lxc_mounts,
            'available': True,
        })
    except Exception as e:
        return jsonify({
            'mounts': [],
            'lxc_mounts': [],
            'available': True,
            'error': str(e),
        }), 500
