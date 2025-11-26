#!/usr/bin/env python3
"""
Hardware Monitor - RAPL Power Monitoring

This module provides CPU power consumption monitoring using Intel RAPL
(Running Average Power Limit) interface when IPMI is not available.

Only contains get_power_info() - all other hardware monitoring is handled
by flask_server.py to avoid code duplication.
"""

import os
import time
from typing import Dict, Any, Optional

# Global variable to store previous energy reading for power calculation
_last_energy_reading = {'energy_uj': None, 'timestamp': None}


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
