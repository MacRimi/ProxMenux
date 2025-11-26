#!/usr/bin/env python3
"""
Hardware Monitor - RAPL Power Monitoring and GPU Identification

This module provides:
1. CPU power consumption monitoring using Intel RAPL (Running Average Power Limit)
2. PCI GPU identification for better fan labeling

Only contains these specialized functions - all other hardware monitoring 
is handled by flask_server.py to avoid code duplication.
"""

import os
import time
import subprocess
import re
from typing import Dict, Any, Optional

# Global variable to store previous energy reading for power calculation
_last_energy_reading = {'energy_uj': None, 'timestamp': None}


def get_pci_gpu_map() -> Dict[str, Dict[str, str]]:
    """
    Get a mapping of PCI addresses to GPU names from lspci.
    
    This function parses lspci output to identify GPU models by their PCI addresses,
    which allows us to provide meaningful names for GPU fans in sensors output.
    
    Returns:
        dict: Mapping of PCI addresses (e.g., '02:00.0') to GPU info
              Example: {
                  '02:00.0': {
                      'vendor': 'NVIDIA', 
                      'name': 'GeForce GTX 1080',
                      'full_name': 'NVIDIA Corporation GP104 [GeForce GTX 1080]'
                  }
              }
    """
    gpu_map = {}
    
    try:
        # Run lspci to get VGA/3D/Display controllers
        result = subprocess.run(
            ['lspci', '-nn'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'VGA compatible controller' in line or '3D controller' in line or 'Display controller' in line:
                    # Example line: "02:00.0 VGA compatible controller [0300]: NVIDIA Corporation GP104 [GeForce GTX 1080] [10de:1b80]"
                    match = re.match(r'^([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s+.*:\s+(.+?)\s+\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    
                    if match:
                        pci_address = match.group(1)
                        device_name = match.group(2).strip()
                        
                        # Extract vendor
                        vendor = None
                        if 'NVIDIA' in device_name.upper() or 'GEFORCE' in device_name.upper() or 'QUADRO' in device_name.upper():
                            vendor = 'NVIDIA'
                        elif 'AMD' in device_name.upper() or 'RADEON' in device_name.upper():
                            vendor = 'AMD'
                        elif 'INTEL' in device_name.upper() or 'ARC' in device_name.upper():
                            vendor = 'Intel'
                        
                        # Extract model name (text between brackets is usually the commercial name)
                        bracket_match = re.search(r'\[([^\]]+)\]', device_name)
                        if bracket_match:
                            model_name = bracket_match.group(1)
                        else:
                            # Fallback: use everything after the vendor name
                            if vendor:
                                model_name = device_name.split(vendor)[-1].strip()
                            else:
                                model_name = device_name
                        
                        gpu_map[pci_address] = {
                            'vendor': vendor if vendor else 'Unknown',
                            'name': model_name,
                            'full_name': device_name
                        }
    
    except Exception:
        pass
    
    return gpu_map


def get_power_info() -> Optional[Dict[str, Any]]:
    """
    Get CPU power consumption using Intel RAPL interface.
    
    This function measures power consumption by reading energy counters
    from /sys/class/powercap/intel-rapl interfaces and calculating
    the power draw based on the change in energy over time.
    
    Used as fallback when IPMI power monitoring is not available.
    
    Returns:
        dict: Power meter information with 'name', 'watts', and 'adapter' keys
              or None if RAPL interface is unavailable
              
    Example:
        {
            'name': 'CPU Power',
            'watts': 45.32,
            'adapter': 'Intel RAPL (CPU only)'
        }
    """
    global _last_energy_reading
    
    rapl_path = '/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj'
    
    if os.path.exists(rapl_path):
        try:
            # Read current energy value in microjoules
            with open(rapl_path, 'r') as f:
                current_energy_uj = int(f.read().strip())
            current_time = time.time()
            
            watts = 0.0
            
            # Calculate power if we have a previous reading
            if _last_energy_reading['energy_uj'] is not None and _last_energy_reading['timestamp'] is not None:
                time_diff = current_time - _last_energy_reading['timestamp']
                if time_diff > 0:
                    energy_diff = current_energy_uj - _last_energy_reading['energy_uj']
                    # Handle counter overflow (wraps around at max value)
                    if energy_diff < 0:
                        energy_diff = current_energy_uj
                    # Power (W) = Energy (µJ) / time (s) / 1,000,000
                    watts = round((energy_diff / time_diff) / 1000000, 2)
            
            # Store current reading for next calculation
            _last_energy_reading['energy_uj'] = current_energy_uj
            _last_energy_reading['timestamp'] = current_time
            
            # Detect CPU vendor for display purposes
            cpu_vendor = 'CPU'
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                    if 'GenuineIntel' in cpuinfo:
                        cpu_vendor = 'Intel'
                    elif 'AuthenticAMD' in cpuinfo:
                        cpu_vendor = 'AMD'
            except:
                pass
            
            return {
                'name': 'CPU Power',
                'watts': watts,
                'adapter': f'{cpu_vendor} RAPL (CPU only)'
            }
        except Exception:
            pass
    
    return None
