#!/usr/bin/env python3
"""
Hardware Monitor - Detección exhaustiva de hardware
Fusiona:
1. Consumo de CPU (RAPL)
2. Detección de GPU (Intel/NVIDIA/AMD) y métricas detalladas
3. Controladoras HBA/RAID y sus temperaturas
4. Sensores IPMI (Ventiladores/Energía) y UPS (NUT)
5. Información base (CPU, RAM, Placa base)
"""

import os
import time
import subprocess
import re
import json
import shutil
import select
import psutil
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional

# --- Variables Globales ---
_last_energy_reading = {'energy_uj': None, 'timestamp': None}

# --- Funciones Auxiliares de GPU ---

def identify_gpu_type(name, vendor=None, bus=None, driver=None):
    """Determina si una GPU es Integrada o Dedicada (PCI)."""
    n = (name or "").lower()
    v = (vendor or "").lower()
    d = (driver or "").lower()
    
    bmc_keywords = ['aspeed', 'ast', 'matrox g200', 'g200e', 'mgag200']
    if any(k in n for k in bmc_keywords) or v in ['aspeed', 'matrox']:
        return 'Integrated'

    if 'intel' in v or 'intel corporation' in n:
        if d == 'i915' or any(w in n for w in ['uhd graphics', 'iris', 'integrated']):
            return 'Integrated'
        return 'Integrated' # Asumir integrada por defecto para Intel en servidores

    amd_apu = ['radeon 780m', 'vega', 'renoir', 'cezanne', 'rembrandt']
    if 'amd' in v and any(k in n for k in amd_apu):
        return 'Integrated'

    return 'PCI'

def get_intel_gpu_processes_from_text():
    """
    Parsea procesos de intel_gpu_top desde salida de texto
    (fallback cuando JSON falla).
    """
    try:
        process = subprocess.Popen(['intel_gpu_top'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        time.sleep(2)
        process.terminate()
        try: stdout, _ = process.communicate(timeout=1)
        except: 
            process.kill()
            stdout, _ = process.communicate()
        
        processes = []
        lines = stdout.split('\n')
        header_found = False
        
        for i, line in enumerate(lines):
            if 'PID' in line and 'NAME' in line:
                header_found = True
                for proc_line in lines[i+1:]:
                    parts = proc_line.split()
                    if len(parts) >= 8:
                        try:
                            # Parseo simplificado
                            name = parts[-1]
                            pid = parts[0]
                            if pid.isdigit():
                                processes.append({
                                    'name': name, 'pid': pid,
                                    'memory': {'total': 0, 'resident': 0},
                                    'engines': {'Render/3D': 'Active'} # Estimado
                                })
                        except: continue
                break
        return processes
    except: return []

# --- Funciones Principales de GPU ---

def get_pci_gpu_map() -> Dict[str, Dict[str, str]]:
    """
    Obtiene un mapa detallado de GPUs desde lspci.
    Útil para enriquecer datos con nombres completos de dispositivos.
    """
    gpu_map = {}
    try:
        result = subprocess.run(['lspci', '-nn'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if any(k in line for k in ['VGA compatible', '3D controller', 'Display controller']):
                    match = re.match(r'^([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s+.*:\s+(.+?)\s+\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    if match:
                        pci = match.group(1)
                        name = match.group(2).strip()
                        vendor = 'Unknown'
                        if 'NVIDIA' in name.upper(): vendor = 'NVIDIA'
                        elif 'AMD' in name.upper() or 'ATI' in name.upper(): vendor = 'AMD'
                        elif 'INTEL' in name.upper(): vendor = 'Intel'
                        
                        gpu_map[pci] = {'vendor': vendor, 'name': name, 'full_name': line}
    except Exception: pass
    return gpu_map

def get_gpu_info():
    """Detecta GPUs instaladas para la API."""
    gpus = []
    try:
        res = subprocess.run(['lspci'], capture_output=True, text=True)
        for line in res.stdout.split('\n'):
            if any(x in line for x in ['VGA', '3D', 'Display']):
                parts = line.split(' ', 1)
                if len(parts) >= 2:
                    slot = parts[0]
                    rest = parts[1]
                    name = rest.split(':', 1)[1].strip() if ':' in rest else rest.strip()
                    
                    vendor = 'Unknown'
                    if 'NVIDIA' in name.upper(): vendor = 'NVIDIA'
                    elif 'AMD' in name.upper(): vendor = 'AMD'
                    elif 'INTEL' in name.upper(): vendor = 'Intel'
                    
                    gpus.append({
                        'slot': slot,
                        'name': name,
                        'vendor': vendor,
                        'type': identify_gpu_type(name, vendor)
                    })
    except: pass
    return gpus

def get_detailed_gpu_info(gpu):
    """
    Obtiene métricas en tiempo real (Temp, Uso, VRAM, Power) 
    usando herramientas específicas del vendor (nvidia-smi, intel_gpu_top).
    """
    vendor = gpu.get('vendor', '').lower()
    info = {
        'has_monitoring_tool': False, 'temperature': None, 'fan_speed': None,
        'utilization_gpu': None, 'memory_used': None, 'memory_total': None,
        'power_draw': None, 'processes': []
    }
    
    # --- NVIDIA ---
    if 'nvidia' in vendor and shutil.which('nvidia-smi'):
        try:
            cmd = ['nvidia-smi', '-q', '-x']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                root = ET.fromstring(res.stdout)
                gpu_elem = root.find('gpu')
                if gpu_elem:
                    info['has_monitoring_tool'] = True
                    temp = gpu_elem.find('.//temperature/gpu_temp')
                    if temp is not None: info['temperature'] = int(temp.text.replace(' C', ''))
                    fan = gpu_elem.find('.//fan_speed')
                    if fan is not None and fan.text != 'N/A': info['fan_speed'] = int(fan.text.replace(' %', ''))
                    power = gpu_elem.find('.//gpu_power_readings/instant_power_draw')
                    if power is not None and power.text != 'N/A': info['power_draw'] = power.text
                    util = gpu_elem.find('.//utilization/gpu_util')
                    if util is not None: info['utilization_gpu'] = util.text
                    mem_used = gpu_elem.find('.//fb_memory_usage/used')
                    if mem_used is not None: info['memory_used'] = mem_used.text
                    mem_total = gpu_elem.find('.//fb_memory_usage/total')
                    if mem_total is not None: info['memory_total'] = mem_total.text
                    
                    procs = gpu_elem.find('.//processes')
                    if procs is not None:
                        for p in procs.findall('process_info'):
                            info['processes'].append({
                                'pid': p.find('pid').text,
                                'name': p.find('process_name').text,
                                'memory': p.find('used_memory').text
                            })
        except: pass

    # --- INTEL ---
    elif 'intel' in vendor:
        tool = shutil.which('intel_gpu_top')
        if tool:
            try:
                # Intenta ejecutar JSON output
                env = os.environ.copy()
                env['TERM'] = 'xterm'
                proc = subprocess.Popen([tool, '-J'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                
                # Leer brevemente
                time.sleep(1.5)
                proc.terminate()
                try: stdout, _ = proc.communicate(timeout=0.5)
                except: 
                    proc.kill()
                    stdout, _ = proc.communicate()

                # Parsear último JSON válido
                json_objs = []
                buffer = ""
                brace = 0
                for char in stdout:
                    if char == '{': brace += 1
                    if brace > 0: buffer += char
                    if char == '}': 
                        brace -= 1
                        if brace == 0: 
                            try: json_objs.append(json.loads(buffer))
                            except: pass
                            buffer = ""
                
                if json_objs:
                    data = json_objs[-1]
                    info['has_monitoring_tool'] = True
                    
                    if 'engines' in data:
                        max_usage = 0.0
                        for k, v in data['engines'].items():
                            val = float(v.get('busy', 0))
                            if val > max_usage: max_usage = val
                        info['utilization_gpu'] = f"{max_usage:.1f}%"
                    
                    if 'power' in data:
                        info['power_draw'] = f"{data['power'].get('Package', 0):.2f} W"
                        
                    if 'frequency' in data:
                        info['clock_graphics'] = f"{data['frequency'].get('actual', 0)} MHz"
            except:
                # Fallback procesos texto
                info['processes'] = get_intel_gpu_processes_from_text()
                if info['processes']: info['has_monitoring_tool'] = True

    return info

def get_gpu_realtime_data(slot):
    """Encuentra una GPU por slot y devuelve sus datos en tiempo real."""
    gpus = get_gpu_info()
    target = None
    for g in gpus:
        if g['slot'] == slot or slot in g.get('slot', ''):
            target = g
            break
            
    if target:
        details = get_detailed_gpu_info(target)
        target.update(details)
        return target
    return None

# --- RAPL Power (CPU) ---

def get_power_info() -> Optional[Dict[str, Any]]:
    """Obtiene consumo de CPU Intel via RAPL."""
    global _last_energy_reading
    rapl_path = '/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj'
    
    if os.path.exists(rapl_path):
        try:
            with open(rapl_path, 'r') as f: current_uj = int(f.read().strip())
            current_time = time.time()
            watts = 0.0
            
            if _last_energy_reading['energy_uj'] and _last_energy_reading['timestamp']:
                tdiff = current_time - _last_energy_reading['timestamp']
                ediff = current_uj - _last_energy_reading['energy_uj']
                if tdiff > 0:
                    if ediff < 0: ediff = current_uj # Overflow handling
                    watts = round((ediff / tdiff) / 1000000, 2)
            
            _last_energy_reading = {'energy_uj': current_uj, 'timestamp': current_time}
            
            cpu_vendor = 'CPU'
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    if 'GenuineIntel' in f.read(): cpu_vendor = 'Intel'
                    else: cpu_vendor = 'AMD'
            except: pass
            
            return {'name': 'CPU Power', 'watts': watts, 'adapter': f'{cpu_vendor} RAPL'}
        except: pass
    return None

# --- HBA / RAID Logic ---

def get_hba_info() -> list[Dict[str, Any]]:
    """Detecta controladoras HBA/RAID."""
    hba_list = []
    try:
        result = subprocess.run(['lspci', '-nn'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            controller_id = 0
            for line in result.stdout.split('\n'):
                if any(k in line for k in ['RAID bus controller', 'SCSI storage controller', 'Serial Attached SCSI']):
                    match = re.match(r'^([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s+.*:\s+(.+?)\s+\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    if match:
                        pci = match.group(1)
                        name = match.group(2).strip()
                        vendor = 'Unknown'
                        if 'LSI' in name.upper() or 'BROADCOM' in name.upper() or 'AVAGO' in name.upper(): vendor = 'LSI/Broadcom'
                        elif 'ADAPTEC' in name.upper(): vendor = 'Adaptec'
                        elif 'HP' in name.upper(): vendor = 'HP'
                        elif 'DELL' in name.upper(): vendor = 'Dell'
                        
                        model = name
                        for v in ['Broadcom / LSI', 'Broadcom', 'LSI Logic', 'LSI']:
                            if model.startswith(v): model = model[len(v):].strip()
                            
                        hba_list.append({
                            'pci_address': pci, 'vendor': vendor, 'model': model,
                            'controller_id': controller_id, 'full_name': name
                        })
                        controller_id += 1
    except: pass
    return hba_list

def get_hba_temperatures() -> list[Dict[str, Any]]:
    """Obtiene temperaturas de HBA (storcli/megacli)."""
    temperatures = []
    storcli_paths = ['/usr/sbin/storcli64', '/opt/MegaRAID/storcli/storcli64', 'storcli64']
    storcli = next((p for p in storcli_paths if shutil.which(p) or os.path.exists(p)), None)
    
    if storcli:
        try:
            # Intenta leer el controlador 0 como ejemplo básico
            res = subprocess.run([storcli, '/c0', 'show', 'temperature'], capture_output=True, text=True, timeout=5)
            for line in res.stdout.split('\n'):
                if 'ROC temperature' in line or 'Controller Temp' in line:
                    match = re.search(r'(\d+)\s*C', line)
                    if match:
                        temperatures.append({
                            'name': 'HBA Controller 0',
                            'temperature': int(match.group(1)),
                            'adapter': 'LSI/Broadcom'
                        })
        except: pass
    return temperatures

# --- IPMI & UPS ---

def get_ipmi_fans():
    """Obtiene ventiladores via ipmitool."""
    fans = []
    if shutil.which('ipmitool'):
        try:
            res = subprocess.run(['ipmitool', 'sensor'], capture_output=True, text=True, timeout=5)
            for line in res.stdout.split('\n'):
                if 'fan' in line.lower() and '|' in line:
                    p = line.split('|')
                    try: fans.append({'name': p[0].strip(), 'speed': float(p[1].strip()), 'unit': p[2].strip()})
                    except: continue
        except: pass
    return fans

def get_ipmi_power():
    """Obtiene datos de energía IPMI."""
    power = {'supplies': [], 'meter': None}
    if shutil.which('ipmitool'):
        try:
            res = subprocess.run(['ipmitool', 'sensor'], capture_output=True, text=True, timeout=5)
            for line in res.stdout.split('\n'):
                lower = line.lower()
                if ('power supply' in lower or 'power meter' in lower) and '|' in line:
                    p = line.split('|')
                    try:
                        val = float(p[1].strip())
                        unit = p[2].strip()
                        if 'power meter' in lower:
                            power['meter'] = {'name': p[0].strip(), 'watts': val, 'unit': unit}
                        else:
                            power['supplies'].append({'name': p[0].strip(), 'watts': val, 'unit': unit})
                    except: continue
        except: pass
    return power

def get_ups_info():
    """Obtiene datos de UPS via NUT."""
    ups_list = []
    if shutil.which('upsc'):
        try:
            res = subprocess.run(['upsc', '-l'], capture_output=True, text=True, timeout=5)
            for ups in res.stdout.strip().split('\n'):
                if ups:
                    data = {'name': ups, 'connection_type': 'Local'}
                    d_res = subprocess.run(['upsc', ups], capture_output=True, text=True, timeout=5)
                    for line in d_res.stdout.split('\n'):
                        if ':' in line:
                            k, v = line.split(':', 1)
                            data[k.strip()] = v.strip()
                    ups_list.append(data)
        except: pass
    return ups_list

# --- Main Hardware Aggregator ---

def get_hardware_info():
    """Agrega toda la información de hardware para la API."""
    data = {
        'cpu': {}, 'motherboard': {}, 'memory_modules': [], 
        'storage_devices': [], 'pci_devices': [], 
        'gpus': get_gpu_info(),
        'ipmi_fans': get_ipmi_fans(),
        'ipmi_power': get_ipmi_power(),
        'ups': get_ups_info(),
        'power_meter': get_power_info(),
        'hba': get_hba_info(),
        'sensors': {'fans': [], 'temperatures': get_hba_temperatures()} 
    }
    
    # CPU Info
    try:
        res = subprocess.run(['lscpu'], capture_output=True, text=True)
        for line in res.stdout.split('\n'):
            if 'Model name:' in line: data['cpu']['model'] = line.split(':', 1)[1].strip()
            if 'Socket(s):' in line: data['cpu']['sockets'] = line.split(':', 1)[1].strip()
    except: pass
    
    # Motherboard
    try:
        res = subprocess.run(['dmidecode', '-t', 'baseboard'], capture_output=True, text=True)
        for line in res.stdout.split('\n'):
            if 'Product Name:' in line: data['motherboard']['model'] = line.split(':', 1)[1].strip()
            if 'Manufacturer:' in line: data['motherboard']['manufacturer'] = line.split(':', 1)[1].strip()
    except: pass
    
    # RAM
    try:
        res = subprocess.run(['dmidecode', '-t', 'memory'], capture_output=True, text=True)
        mod = {}
        for line in res.stdout.split('\n'):
            line = line.strip()
            if 'Memory Device' in line:
                if mod.get('size', 0) > 0: data['memory_modules'].append(mod)
                mod = {'size': 0}
            elif 'Size:' in line:
                parts = line.split(':', 1)[1].strip().split()
                if len(parts) >= 2 and parts[0].isdigit():
                    val = int(parts[0])
                    unit = parts[1].upper()
                    if unit == 'GB': mod['size'] = val * 1024 * 1024
                    elif unit == 'MB': mod['size'] = val * 1024
            elif 'Type:' in line: mod['type'] = line.split(':', 1)[1].strip()
            elif 'Speed:' in line: mod['speed'] = line.split(':', 1)[1].strip()
        if mod.get('size', 0) > 0: data['memory_modules'].append(mod)
    except: pass

    # Enrich GPUs with details
    for gpu in data['gpus']:
        gpu.update(get_detailed_gpu_info(gpu))

    return data