#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux - Proxmox Storage Monitor
Monitors configured Proxmox storages and tracks unavailable storages
"""

import json
import subprocess
import socket
import time
from typing import Dict, List, Any, Optional


class ProxmoxStorageMonitor:
    """Monitor Proxmox storage configuration and status"""
    
    # Cache TTL: 177 seconds (~3 min) - offset to avoid sync with other processes
    _CACHE_TTL = 177
    
    def __init__(self):
        self.configured_storages: Dict[str, Dict[str, Any]] = {}
        self._node_name_cache = {'name': None, 'time': 0}
        self._storage_status_cache = {'data': None, 'time': 0}
        self._config_cache_time = 0  # Track when config was last loaded
        self._load_configured_storages()
    
    def _get_node_name(self) -> str:
        """Get current Proxmox node name (cached)"""
        current_time = time.time()
        cache = self._node_name_cache
        
        # Return cached result if fresh
        if cache['name'] and (current_time - cache['time']) < self._CACHE_TTL:
            return cache['name']
        
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
                        cache['name'] = hostname
                        cache['time'] = current_time
                        return hostname
                if nodes:
                    name = nodes[0].get('node', hostname)
                    cache['name'] = name
                    cache['time'] = current_time
                    return name
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
        Get storage status, including unavailable storages (cached)
        
        Returns:
            {
                'available': [...],
                'unavailable': [...]
            }
        """
        current_time = time.time()
        cache = self._storage_status_cache
        
        # Return cached result if fresh
        if cache['data'] and (current_time - cache['time']) < self._CACHE_TTL:
            return cache['data']
        
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
                
                # Check if storage is available.
                #
                # "jc-pbs-friendly" mode (Sprint 11.6): a remote PBS where
                # the user only has DatastoreAdmin on their own namespace
                # reports `status=available` + `total=0` — the storage IS
                # reachable, the user just can't list the datastore size.
                # Treat that combination as INFO (namespace-restricted)
                # instead of CRITICAL so we don't spam the operator with
                # "almacenamiento no disponible" every poll. Real outages
                # still flag because they come back with `status != available`.
                if total == 0 and status.lower() == "available" and storage_type == 'pbs':
                    storage_info['status'] = 'namespace_restricted'
                    storage_info['status_detail'] = 'namespace_restricted'
                    available_storages.append(storage_info)
                elif total == 0 or status.lower() != "available":
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
            
            result_data = {
                'available': available_storages,
                'unavailable': unavailable_storages
            }
            
            # Cache the result
            cache['data'] = result_data
            cache['time'] = current_time
            
            return result_data
        
        except Exception:
            return {
                'available': [],
                'unavailable': list(self.configured_storages.values())
            }
    
    def get_unavailable_count(self) -> int:
        """Get count of unavailable storages"""
        status = self.get_storage_status()
        return len(status['unavailable'])
    
    def reload_configuration(self, force: bool = False) -> None:
        """Reload storage configuration from Proxmox (cached)
        
        Args:
            force: If True, bypass cache and force reload
        """
        current_time = time.time()
        
        # Skip reload if cache is still fresh (unless forced)
        if not force and (current_time - self._config_cache_time) < self._CACHE_TTL:
            return
        
        self.configured_storages.clear()
        self._load_configured_storages()
        self._config_cache_time = current_time


# Global instance
proxmox_storage_monitor = ProxmoxStorageMonitor()
