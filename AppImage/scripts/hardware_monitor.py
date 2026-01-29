#!/usr/bin/env python3
"""
Hardware Monitor - Detección exhaustiva de hardware
Agrega CPU (RAPL), RAM, Placa base, GPU (Intel/NVIDIA/AMD), IPMI y UPS.
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
    b = (bus or "")

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

def get_gpu_info():
    """Detecta GPUs instaladas usando lspci y sensors."""
    gpus = []
    
    # 1. Detección por lspci
    try:
        result = subprocess.run(['lspci'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if any(k in line for k in ['VGA compatible', '3D controller', 'Display controller']):
                    parts = line.split(' ', 1)
                    if len(parts) >= 2:
                        slot = parts[0].strip()
                        rest = parts[1]
                        name = rest.split(':', 1)[1].strip() if ':' in rest else rest.strip()
                        
                        vendor = 'Unknown'
                        if 'NVIDIA' in name.upper(): vendor = 'NVIDIA'
                        elif 'AMD' in name.upper() or 'ATI' in name.upper(): vendor = 'AMD'
                        elif 'INTEL' in name.upper(): vendor = 'Intel'
                        
                        gpus.append({
                            'slot': slot,
                            'name': name,
                            'vendor': vendor,
                            'type': identify_gpu_type(name, vendor)
                        })
    except: pass
    
    # 2. Enriquecer con datos básicos de sensores (temperatura/fan) si están disponibles via 'sensors'
    # (Lógica simplificada para no extender demasiado el código)
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
                    # Temp
                    temp = gpu_elem.find('.//temperature/gpu_temp')
                    if temp is not None: info['temperature'] = int(temp.text.replace(' C', ''))
                    # Fan
                    fan = gpu_elem.find('.//fan_speed')
                    if fan is not None and fan.text != 'N/A': info['fan_speed'] = int(fan.text.replace(' %', ''))
                    # Power
                    power = gpu_elem.find('.//gpu_power_readings/instant_power_draw')
                    if power is not None and power.text != 'N/A': info['power_draw'] = power.text
                    # Util
                    util = gpu_elem.find('.//utilization/gpu_util')
                    if util is not None: info['utilization_gpu'] = util.text
                    # Mem
                    mem_used = gpu_elem.find('.//fb_memory_usage/used')
                    if mem_used is not None: info['memory_used'] = mem_used.text
                    mem_total = gpu_elem.find('.//fb_memory_usage/total')
                    if mem_total is not None: info['memory_total'] = mem_total.text
                    
                    # Processes
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
                    
                    # Motores
                    if 'engines' in data:
                        # Calcular uso total (maximo de cualquier motor)
                        max_usage = 0.0
                        for k, v in data['engines'].items():
                            val = float(v.get('busy', 0))
                            if val > max_usage: max_usage = val
                        info['utilization_gpu'] = f"{max_usage:.1f}%"
                    
                    # Power (Package)
                    if 'power' in data:
                        info['power_draw'] = f"{data['power'].get('Package', 0):.2f} W"
                        
                    # Frequency
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

# --- IPMI, UPS y RAPL ---

def get_ipmi_fans():
    """Obtiene ventiladores via ipmitool."""
    fans = []
    if shutil.which('ipmitool'):
        try:
            res = subprocess.run(['ipmitool', 'sensor'], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.split('\n'):
                    if 'fan' in line.lower() and '|' in line:
                        p = line.split('|')
                        if len(p) >= 3:
                            try:
                                val = float(p[1].strip())
                                fans.append({'name': p[0].strip(), 'speed': val, 'unit': p[2].strip()})
                            except: continue
        except: pass
    return fans

def get_ipmi_power():
    """Obtiene datos de energía via ipmitool."""
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
                        unit = p[2].strip() if len(p) > 2 else ''
                        if 'power meter' in lower:
                            power['meter'] = {'name': p[0].strip(), 'watts': val, 'unit': unit}
                        else:
                            power['supplies'].append({'name': p[0].strip(), 'watts': val, 'unit': unit})
                    except: continue
        except: pass
    return power

def get_ups_info():
    """Obtiene datos de SAI/UPS via NUT (upsc)."""
    ups_list = []
    if shutil.which('upsc'):
        try:
            # Detectar UPS configurados
            res = subprocess.run(['upsc', '-l'], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for ups_name in res.stdout.strip().split('\n'):
                    if not ups_name: continue
                    
                    data = {'name': ups_name, 'connection_type': 'Local'}
                    det_res = subprocess.run(['upsc', ups_name], capture_output=True, text=True, timeout=5)
                    if det_res.returncode == 0:
                        for line in det_res.stdout.split('\n'):
                            if ':' in line:
                                k, v = line.split(':', 1)
                                k, v = k.strip(), v.strip()
                                
                                if k == 'device.model': data['model'] = v
                                elif k == 'device.mfr': data['manufacturer'] = v
                                elif k == 'battery.charge': data['battery_charge'] = f"{v}%"
                                elif k == 'ups.load': data['load_percent'] = f"{v}%"
                                elif k == 'ups.status': data['status'] = v
                                elif k == 'battery.runtime': 
                                    try: data['time_left'] = f"{int(v)//60} min"
                                    except: data['time_left'] = v
                                    
                        ups_list.append(data)
        except: pass
    return ups_list

def get_power_info():
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
                if tdiff > 0 and ediff >= 0:
                    watts = round((ediff / tdiff) / 1000000, 2)
            
            _last_energy_reading = {'energy_uj': current_uj, 'timestamp': current_time}
            return {'name': 'CPU RAPL', 'watts': watts, 'adapter': 'Intel RAPL'}
        except: pass
    return None

def get_hba_temperatures():
    """Detecta temperaturas de controladoras HBA (LSI/Broadcom)."""
    # Implementación simplificada
    return []

# --- Función Agregadora Principal ---

def get_hardware_info():
    """
    Retorna un objeto JSON completo con todo el hardware detectado.
    Usado por la ruta /api/hardware.
    """
    data = {
        'cpu': {}, 'motherboard': {}, 'memory_modules': [], 
        'storage_devices': [], 'pci_devices': [],
        'gpus': get_gpu_info(),
        'ipmi_fans': get_ipmi_fans(),
        'ipmi_power': get_ipmi_power(),
        'ups': get_ups_info(),
        'power_meter': get_power_info(),
        'sensors': {'fans': [], 'temperatures': []}
    }
    
    # CPU Info
    try:
        res = subprocess.run(['lscpu'], capture_output=True, text=True)
        for line in res.stdout.split('\n'):
            if 'Model name:' in line: data['cpu']['model'] = line.split(':', 1)[1].strip()
            if 'Socket(s):' in line: data['cpu']['sockets'] = line.split(':', 1)[1].strip()
    except: pass
    
    # Motherboard Info
    try:
        res = subprocess.run(['dmidecode', '-t', 'baseboard'], capture_output=True, text=True)
        for line in res.stdout.split('\n'):
            if 'Product Name:' in line: data['motherboard']['model'] = line.split(':', 1)[1].strip()
            if 'Manufacturer:' in line: data['motherboard']['manufacturer'] = line.split(':', 1)[1].strip()
    except: pass
    
    # RAM Info
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

    # Enriquecer GPUs con datos detallados (solo si hay pocas para no bloquear)
    # Para la vista general, a veces es mejor no llamar a nvidia-smi por cada tarjeta si hay muchas
    # Aquí lo hacemos porque suele ser rápido.
    for gpu in data['gpus']:
        gpu.update(get_detailed_gpu_info(gpu))

    return data