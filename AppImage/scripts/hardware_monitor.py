#!/usr/bin/env python3
"""
Hardware Monitor - RAPL Power Monitoring and GPU Identification

This module provides:
1. CPU power consumption monitoring using Intel RAPL (Running Average Power Limit)
2. PCI GPU identification for better fan labeling
3. HBA controller detection and temperature monitoring

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


def get_hba_info() -> list[Dict[str, Any]]:
    """
    Detect HBA/RAID controllers from lspci.
    
    This function identifies LSI/Broadcom, Adaptec, and other RAID/HBA controllers
    present in the system via lspci output.
    
    Returns:
        list: List of HBA controller dictionaries
              Example: [
                  {
                      'pci_address': '01:00.0',
                      'vendor': 'LSI/Broadcom',
                      'model': 'SAS3008 PCI-Express Fusion-MPT SAS-3',
                      'controller_id': 0
                  }
              ]
    """
    hba_list = []
    
    try:
        # Run lspci to find RAID/SAS controllers
        result = subprocess.run(
            ['lspci', '-nn'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            controller_id = 0
            for line in result.stdout.split('\n'):
                # Look for RAID bus controller, SCSI storage controller, Serial Attached SCSI controller
                if any(keyword in line for keyword in ['RAID bus controller', 'SCSI storage controller', 'Serial Attached SCSI']):
                    # Example: "01:00.0 RAID bus controller [0104]: Broadcom / LSI SAS3008 PCI-Express Fusion-MPT SAS-3 [1000:0097]"
                    match = re.match(r'^([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s+.*:\s+(.+?)\s+\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    
                    if match:
                        pci_address = match.group(1)
                        device_name = match.group(2).strip()
                        
                        # Extract vendor
                        vendor = 'Unknown'
                        if 'LSI' in device_name.upper() or 'BROADCOM' in device_name.upper() or 'AVAGO' in device_name.upper():
                            vendor = 'LSI/Broadcom'
                        elif 'ADAPTEC' in device_name.upper():
                            vendor = 'Adaptec'
                        elif 'ARECA' in device_name.upper():
                            vendor = 'Areca'
                        elif 'HIGHPOINT' in device_name.upper():
                            vendor = 'HighPoint'
                        elif 'DELL' in device_name.upper():
                            vendor = 'Dell'
                        elif 'HP' in device_name.upper() or 'HEWLETT' in device_name.upper():
                            vendor = 'HP'
                        
                        # Extract model name
                        model_name = device_name
                        # Remove vendor prefix if present
                        for v in ['Broadcom / LSI', 'Broadcom', 'LSI Logic', 'LSI', 'Adaptec', 'Areca', 'HighPoint', 'Dell', 'HP', 'Hewlett-Packard']:
                            if model_name.startswith(v):
                                model_name = model_name[len(v):].strip()
                        
                        hba_list.append({
                            'pci_address': pci_address,
                            'vendor': vendor,
                            'model': model_name,
                            'controller_id': controller_id,
                            'full_name': device_name
                        })
                        controller_id += 1
    
    except Exception:
        pass
    
    return hba_list


def get_hba_temperatures() -> list[Dict[str, Any]]:
    """
    Get HBA controller temperatures using storcli64 or megacli.
    
    This function attempts to read temperature data from LSI/Broadcom RAID controllers
    using the storcli64 tool (preferred) or megacli as fallback.
    
    Returns:
        list: List of temperature dictionaries
              Example: [
                  {
                      'name': 'HBA Controller 0',
                      'temperature': 65,
                      'adapter': 'LSI/Broadcom SAS3008'
                  }
              ]
    """
    temperatures = []
    
    # Check which tool is available
    storcli_paths = [
        '/opt/MegaRAID/storcli/storcli64',
        '/usr/sbin/storcli64',
        '/usr/local/sbin/storcli64',
        'storcli64'
    ]
    
    megacli_paths = [
        '/opt/MegaRAID/MegaCli/MegaCli64',
        '/usr/sbin/megacli',
        '/usr/local/sbin/megacli',
        'megacli'
    ]
    
    storcli_path = None
    megacli_path = None
    
    # Find storcli64
    for path in storcli_paths:
        try:
            result = subprocess.run([path, '-v'], capture_output=True, timeout=2)
            if result.returncode == 0:
                storcli_path = path
                break
        except:
            continue
    
    # Try storcli64 first (preferred)
    if storcli_path:
        try:
            # Get list of controllers
            result = subprocess.run(
                [storcli_path, 'show'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Parse controller IDs
                controller_ids = []
                for line in result.stdout.split('\n'):
                    match = re.search(r'^\s*(\d+)\s+', line)
                    if match and 'Ctl' in line:
                        controller_ids.append(match.group(1))
                
                # Get temperature for each controller
                for ctrl_id in controller_ids:
                    try:
                        temp_result = subprocess.run(
                            [storcli_path, f'/c{ctrl_id}', 'show', 'temperature'],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        
                        if temp_result.returncode == 0:
                            # Parse temperature from output
                            for line in temp_result.stdout.split('\n'):
                                if 'ROC temperature' in line or 'Controller Temp' in line:
                                    temp_match = re.search(r'(\d+)\s*C', line)
                                    if temp_match:
                                        temp_c = int(temp_match.group(1))
                                        
                                        # Get HBA info for better naming
                                        hba_list = get_hba_info()
                                        adapter_name = 'LSI/Broadcom Controller'
                                        if int(ctrl_id) < len(hba_list):
                                            hba = hba_list[int(ctrl_id)]
                                            adapter_name = f"{hba['vendor']} {hba['model']}"
                                        
                                        temperatures.append({
                                            'name': f'HBA Controller {ctrl_id}',
                                            'temperature': temp_c,
                                            'adapter': adapter_name
                                        })
                                        break
                    except:
                        continue
        except:
            pass
    
    # Fallback to megacli if storcli not available
    elif not temperatures:
        for path in megacli_paths:
            try:
                result = subprocess.run([path, '-v'], capture_output=True, timeout=2)
                if result.returncode == 0:
                    megacli_path = path
                    break
            except:
                continue
        
        if megacli_path:
            try:
                # Get adapter count
                result = subprocess.run(
                    [megacli_path, '-adpCount'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    # Parse adapter count
                    adapter_count = 0
                    for line in result.stdout.split('\n'):
                        if 'Controller Count' in line:
                            count_match = re.search(r'(\d+)', line)
                            if count_match:
                                adapter_count = int(count_match.group(1))
                                break
                    
                    # Get temperature for each adapter
                    for adapter_id in range(adapter_count):
                        try:
                            temp_result = subprocess.run(
                                [megacli_path, '-AdpAllInfo', f'-a{adapter_id}'],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )
                            
                            if temp_result.returncode == 0:
                                # Parse temperature
                                for line in temp_result.stdout.split('\n'):
                                    if 'ROC temperature' in line or 'Controller Temp' in line:
                                        temp_match = re.search(r'(\d+)\s*C', line)
                                        if temp_match:
                                            temp_c = int(temp_match.group(1))
                                            
                                            # Get HBA info for better naming
                                            hba_list = get_hba_info()
                                            adapter_name = 'LSI/Broadcom Controller'
                                            if adapter_id < len(hba_list):
                                                hba = hba_list[adapter_id]
                                                adapter_name = f"{hba['vendor']} {hba['model']}"
                                            
                                            temperatures.append({
                                                'name': f'HBA Controller {adapter_id}',
                                                'temperature': temp_c,
                                                'adapter': adapter_name
                                            })
                                            break
                        except:
                            continue
            except:
                pass
    
    return temperatures
