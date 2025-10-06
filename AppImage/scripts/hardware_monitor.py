#!/usr/bin/env python3
import json
import subprocess
import re
import os
from typing import Dict, List, Any, Optional

def run_command(cmd: List[str]) -> str:
    """Run a command and return its output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout
    except Exception:
        return ""

def get_nvidia_gpu_info() -> List[Dict[str, Any]]:
    """Get detailed NVIDIA GPU information using nvidia-smi."""
    gpus = []
    
    # Check if nvidia-smi is available
    if not os.path.exists('/usr/bin/nvidia-smi'):
        return gpus
    
    try:
        # Query all GPU metrics at once
        query_fields = [
            'index',
            'name',
            'driver_version',
            'memory.total',
            'memory.used',
            'memory.free',
            'temperature.gpu',
            'utilization.gpu',
            'utilization.memory',
            'power.draw',
            'power.limit',
            'clocks.current.graphics',
            'clocks.current.memory',
            'pcie.link.gen.current',
            'pcie.link.width.current'
        ]
        
        cmd = ['nvidia-smi', '--query-gpu=' + ','.join(query_fields), '--format=csv,noheader,nounits']
        output = run_command(cmd)
        
        if not output:
            return gpus
        
        for line in output.strip().split('\n'):
            if not line:
                continue
                
            values = [v.strip() for v in line.split(',')]
            if len(values) < len(query_fields):
                continue
            
            gpu_info = {
                'index': values[0],
                'name': values[1],
                'driver_version': values[2],
                'memory_total': f"{values[3]} MiB",
                'memory_used': f"{values[4]} MiB",
                'memory_free': f"{values[5]} MiB",
                'temperature': values[6],
                'utilization_gpu': values[7],
                'utilization_memory': values[8],
                'power_draw': f"{values[9]} W",
                'power_limit': f"{values[10]} W",
                'clock_graphics': f"{values[11]} MHz",
                'clock_memory': f"{values[12]} MHz",
                'pcie_gen': values[13],
                'pcie_width': f"x{values[14]}"
            }
            
            # Get CUDA version if available
            cuda_output = run_command(['nvidia-smi', '--query-gpu=compute_cap', '--format=csv,noheader', '-i', values[0]])
            if cuda_output:
                gpu_info['compute_capability'] = cuda_output.strip()
            
            gpus.append(gpu_info)
            
    except Exception as e:
        print(f"Error getting NVIDIA GPU info: {e}", file=sys.stderr)
    
    return gpus

def get_amd_gpu_info() -> List[Dict[str, Any]]:
    """Get AMD GPU information using rocm-smi."""
    gpus = []
    
    # Check if rocm-smi is available
    if not os.path.exists('/opt/rocm/bin/rocm-smi'):
        return gpus
    
    try:
        # Get basic GPU info
        output = run_command(['/opt/rocm/bin/rocm-smi', '--showid', '--showtemp', '--showuse', '--showmeminfo', 'vram'])
        
        if not output:
            return gpus
        
        # Parse rocm-smi output (format varies, this is a basic parser)
        current_gpu = None
        for line in output.split('\n'):
            if 'GPU[' in line:
                if current_gpu:
                    gpus.append(current_gpu)
                current_gpu = {'index': line.split('[')[1].split(']')[0]}
            elif current_gpu:
                if 'Temperature' in line:
                    temp_match = re.search(r'(\d+\.?\d*)', line)
                    if temp_match:
                        current_gpu['temperature'] = temp_match.group(1)
                elif 'GPU use' in line:
                    use_match = re.search(r'(\d+)%', line)
                    if use_match:
                        current_gpu['utilization_gpu'] = use_match.group(1)
                elif 'VRAM' in line:
                    mem_match = re.search(r'(\d+)MB / (\d+)MB', line)
                    if mem_match:
                        current_gpu['memory_used'] = f"{mem_match.group(1)} MiB"
                        current_gpu['memory_total'] = f"{mem_match.group(2)} MiB"
        
        if current_gpu:
            gpus.append(current_gpu)
            
    except Exception as e:
        print(f"Error getting AMD GPU info: {e}", file=sys.stderr)
    
    return gpus

def get_temperatures() -> List[Dict[str, Any]]:
    """Get temperature readings from sensors."""
    temps = []
    output = run_command(['sensors', '-A', '-u'])
    
    current_adapter = None
    current_sensor = None
    
    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        if line.endswith(':') and not line.startswith(' '):
            current_adapter = line[:-1]
        elif '_input:' in line and current_adapter:
            parts = line.split(':')
            if len(parts) == 2:
                sensor_name = parts[0].replace('_input', '').replace('_', ' ').title()
                try:
                    temp_value = float(parts[1].strip())
                    temps.append({
                        'name': sensor_name,
                        'current': round(temp_value, 1),
                        'adapter': current_adapter
                    })
                except ValueError:
                    pass
    
    return temps

def get_fans() -> List[Dict[str, Any]]:
    """Get fan speed readings."""
    fans = []
    output = run_command(['sensors', '-A', '-u'])
    
    current_adapter = None
    
    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        if line.endswith(':') and not line.startswith(' '):
            current_adapter = line[:-1]
        elif 'fan' in line.lower() and '_input:' in line and current_adapter:
            parts = line.split(':')
            if len(parts) == 2:
                fan_name = parts[0].replace('_input', '').replace('_', ' ').title()
                try:
                    speed = float(parts[1].strip())
                    fans.append({
                        'name': fan_name,
                        'speed': int(speed),
                        'unit': 'RPM'
                    })
                except ValueError:
                    pass
    
    return fans

def get_network_cards() -> List[Dict[str, Any]]:
    """Get network interface information."""
    cards = []
    output = run_command(['ip', '-o', 'link', 'show'])
    
    for line in output.split('\n'):
        if not line or 'lo:' in line:
            continue
            
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1].rstrip(':')
            state = 'UP' if 'UP' in line else 'DOWN'
            
            # Get interface type
            iface_type = 'Unknown'
            if 'ether' in line:
                iface_type = 'Ethernet'
            elif 'wlan' in name or 'wifi' in name:
                iface_type = 'WiFi'
            
            # Try to get speed
            speed = None
            speed_output = run_command(['ethtool', name])
            speed_match = re.search(r'Speed: (\d+\w+)', speed_output)
            if speed_match:
                speed = speed_match.group(1)
            
            cards.append({
                'name': name,
                'type': iface_type,
                'status': state,
                'speed': speed
            })
    
    return cards

def get_storage_devices() -> List[Dict[str, Any]]:
    """Get storage device information."""
    devices = []
    output = run_command(['lsblk', '-d', '-o', 'NAME,TYPE,SIZE,MODEL', '-n'])
    
    for line in output.split('\n'):
        if not line:
            continue
            
        parts = line.split(None, 3)
        if len(parts) >= 3:
            name = parts[0]
            dev_type = parts[1]
            size = parts[2]
            model = parts[3] if len(parts) > 3 else 'Unknown'
            
            if dev_type in ['disk', 'nvme']:
                devices.append({
                    'name': name,
                    'type': dev_type,
                    'size': size,
                    'model': model.strip()
                })
    
    return devices

def get_pci_devices() -> List[Dict[str, Any]]:
    """Get PCI device information including GPUs."""
    devices = []
    output = run_command(['lspci', '-vmm'])
    
    current_device = {}
    
    for line in output.split('\n'):
        line = line.strip()
        
        if not line:
            if current_device:
                devices.append(current_device)
                current_device = {}
            continue
        
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()
            current_device[key] = value
    
    if current_device:
        devices.append(current_device)
    
    # Enhance GPU devices with monitoring data
    nvidia_gpus = get_nvidia_gpu_info()
    amd_gpus = get_amd_gpu_info()
    
    nvidia_idx = 0
    amd_idx = 0
    
    for device in devices:
        # Check if it's a GPU
        device_class = device.get('class', '').lower()
        vendor = device.get('vendor', '').lower()
        
        if 'vga' in device_class or 'display' in device_class or '3d' in device_class:
            device['type'] = 'GPU'
            
            # Add NVIDIA GPU monitoring data
            if 'nvidia' in vendor and nvidia_idx < len(nvidia_gpus):
                gpu_data = nvidia_gpus[nvidia_idx]
                device['gpu_memory'] = gpu_data.get('memory_total')
                device['gpu_driver_version'] = gpu_data.get('driver_version')
                device['gpu_compute_capability'] = gpu_data.get('compute_capability')
                device['gpu_power_draw'] = gpu_data.get('power_draw')
                device['gpu_temperature'] = float(gpu_data.get('temperature', 0))
                device['gpu_utilization'] = float(gpu_data.get('utilization_gpu', 0))
                device['gpu_memory_used'] = gpu_data.get('memory_used')
                device['gpu_memory_total'] = gpu_data.get('memory_total')
                device['gpu_clock_speed'] = gpu_data.get('clock_graphics')
                device['gpu_memory_clock'] = gpu_data.get('clock_memory')
                nvidia_idx += 1
            
            # Add AMD GPU monitoring data
            elif 'amd' in vendor and amd_idx < len(amd_gpus):
                gpu_data = amd_gpus[amd_idx]
                device['gpu_temperature'] = float(gpu_data.get('temperature', 0))
                device['gpu_utilization'] = float(gpu_data.get('utilization_gpu', 0))
                device['gpu_memory_used'] = gpu_data.get('memory_used')
                device['gpu_memory_total'] = gpu_data.get('memory_total')
                amd_idx += 1
        elif 'network' in device_class or 'ethernet' in device_class:
            device['type'] = 'Network'
        elif 'storage' in device_class or 'sata' in device_class or 'nvme' in device_class:
            device['type'] = 'Storage'
        else:
            device['type'] = 'Other'
    
    return devices

def get_power_info() -> Optional[Dict[str, Any]]:
    """Get power consumption information if available."""
    # Try to get system power from RAPL (Running Average Power Limit)
    rapl_path = '/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj'
    
    if os.path.exists(rapl_path):
        try:
            with open(rapl_path, 'r') as f:
                energy_uj = int(f.read().strip())
            
            # This is cumulative energy, would need to track over time for watts
            # For now, just indicate power monitoring is available
            return {
                'name': 'System Power',
                'watts': 0,  # Would need time-based calculation
                'adapter': 'RAPL'
            }
        except Exception:
            pass
    
    return None

def main():
    """Main function to gather all hardware information."""
    data = {
        'temperatures': get_temperatures(),
        'fans': get_fans(),
        'network_cards': get_network_cards(),
        'storage_devices': get_storage_devices(),
        'pci_devices': get_pci_devices(),
    }
    
    power_info = get_power_info()
    if power_info:
        data['power_meter'] = power_info
    
    print(json.dumps(data, indent=2))

if __name__ == '__main__':
    import sys
    main()
