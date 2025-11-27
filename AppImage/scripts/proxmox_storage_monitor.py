#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux - Proxmox Storage Monitor
Monitors configured Proxmox storages and tracks unavailable storages
"""

import json
import subprocess
import socket
from typing import Dict, List, Any, Optional


class ProxmoxStorageMonitor:
    """Monitor Proxmox storage configuration and status"""
    
    def __init__(self):
        self.configured_storages: Dict[str, Dict[str, Any]] = {}
        self._load_configured_storages()
    
    def _get_node_name(self) -> str:
        """Get current Proxmox node name"""
        try:
            result = subprocess.run(
                ['pvesh', 'get', '/nodes', '--output-format', 'json'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                nodes = json.loads(result.stdout)
                hostname = socket.gethostname()
                for node in nodes:
                    if node.get('node') == hostname:
                        return hostname
                if nodes:
                    return nodes[0].get('node', hostname)
            return socket.gethostname()
        except Exception:
            return socket.gethostname()
    
    def _load_configured_storages(self) -> None:
        """Load configured storages from Proxmox configuration"""
        try:
            local_node = self._get_node_name()
            
            # Read storage configuration from pvesh
            result = subprocess.run(
                ['pvesh', 'get', '/storage', '--output-format', 'json'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return
            
            storages = json.loads(result.stdout)
            
            for storage in storages:
                storage_id = storage.get('storage')
                if not storage_id:
                    continue
                
                # Check if storage is enabled for this node
                nodes = storage.get('nodes')
                if nodes and local_node not in nodes.split(','):
                    continue
                
                disabled = storage.get('disable', 0)
                if disabled == 1:
                    continue
                
                self.configured_storages[storage_id] = {
                    'name': storage_id,
                    'type': storage.get('type', 'unknown'),
                    'content': storage.get('content', ''),
                    'path': storage.get('path', ''),
                    'enabled': True
                }
        
        except Exception:
            pass
    
    def get_storage_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get storage status, including unavailable storages
        
        Returns:
            {
                'available': [...],
                'unavailable': [...]
            }
        """
        try:
            local_node = self._get_node_name()
            
            # Get current storage status from pvesh
            result = subprocess.run(
                ['pvesh', 'get', '/cluster/resources', '--type', 'storage', '--output-format', 'json'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return {'available': [], 'unavailable': list(self.configured_storages.values())}
            
            resources = json.loads(result.stdout)
            
            # Track which configured storages are available
            available_storages = []
            unavailable_storages = []
            seen_storage_names = set()
            
            for resource in resources:
                node = resource.get('node', '')
                
                # Filter only local node storages
                if node != local_node:
                    continue
                
                name = resource.get('storage', 'unknown')
                seen_storage_names.add(name)
                storage_type = resource.get('plugintype', 'unknown')
                status = resource.get('status', 'unknown')
                
                try:
                    total = int(resource.get('maxdisk', 0))
                    used = int(resource.get('disk', 0))
                    available = total - used if total > 0 else 0
                except (ValueError, TypeError):
                    total = 0
                    used = 0
                    available = 0
                
                # Calculate percentage
                percent = (used / total * 100) if total > 0 else 0.0
                
                # Convert bytes to GB
                total_gb = round(total / (1024**3), 2)
                used_gb = round(used / (1024**3), 2)
                available_gb = round(available / (1024**3), 2)
                
                storage_info = {
                    'name': name,
                    'type': storage_type,
                    'total': total_gb,
                    'used': used_gb,
                    'available': available_gb,
                    'percent': round(percent, 2),
                    'node': node
                }
                
                # Check if storage is available
                if total == 0 or status.lower() != "available":
                    storage_info['status'] = 'error'
                    storage_info['status_detail'] = 'unavailable' if total == 0 else status
                    unavailable_storages.append(storage_info)
                else:
                    storage_info['status'] = 'active'
                    available_storages.append(storage_info)
            
            # Check for configured storages that are completely missing
            for storage_name, storage_config in self.configured_storages.items():
                if storage_name not in seen_storage_names:
                    unavailable_storages.append({
                        'name': storage_name,
                        'type': storage_config['type'],
                        'status': 'error',
                        'status_detail': 'not_found',
                        'total': 0,
                        'used': 0,
                        'available': 0,
                        'percent': 0,
                        'node': local_node
                    })
            
            return {
                'available': available_storages,
                'unavailable': unavailable_storages
            }
        
        except Exception:
            return {
                'available': [],
                'unavailable': list(self.configured_storages.values())
            }
    
    def get_unavailable_count(self) -> int:
        """Get count of unavailable storages"""
        status = self.get_storage_status()
        return len(status['unavailable'])
    
    def reload_configuration(self) -> None:
        """Reload storage configuration from Proxmox"""
        self.configured_storages.clear()
        self._load_configured_storages()


# Global instance
proxmox_storage_monitor = ProxmoxStorageMonitor()
