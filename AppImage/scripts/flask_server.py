#!/usr/bin/env python3
"""
ProxMenux Flask Server

- Provides REST API endpoints for Proxmox monitoring (system, storage, network, VMs, etc.)
- Serves the Next.js dashboard as static files
- Integrates a web terminal powered by xterm.js
"""

import glob
import json
import logging
import math
import os
import platform
import re
import select
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import threading
import urllib.parse
import hardware_monitor
from health_persistence import health_persistence
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import jwt
import psutil
from flask import Flask, jsonify, request, send_file, send_from_directory, Response
from flask_cors import CORS

# Ensure local imports work even if working directory changes
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask_script_runner import script_runner
import threading
from proxmox_storage_monitor import proxmox_storage_monitor
from flask_terminal_routes import terminal_bp, init_terminal_routes  # noqa: E402
from flask_health_routes import health_bp  # noqa: E402
from flask_auth_routes import auth_bp  # noqa: E402
from flask_proxmenux_routes import proxmenux_bp  # noqa: E402
from flask_security_routes import security_bp  # noqa: E402
from flask_notification_routes import notification_bp  # noqa: E402
from flask_oci_routes import oci_bp  # noqa: E402
from notification_manager import notification_manager  # noqa: E402
import post_install_versions  # noqa: E402  — Sprint 12A: detect post-install function updates
from jwt_middleware import require_auth  # noqa: E402
import auth_manager  # noqa: E402

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
logger = logging.getLogger("proxmenux.flask")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# -------------------------------------------------------------------
# Proxmox node name cache
# -------------------------------------------------------------------
_PROXMOX_NODE_CACHE = {"name": None, "timestamp": 0.0}
_PROXMOX_NODE_CACHE_TTL = 300  # seconds (5 minutes)


def get_proxmox_node_name() -> str:
    """
    Retrieve the real Proxmox node name for the LOCAL node.

    - First tries reading from: `pvesh get /nodes`
    - In a cluster, matches the local hostname against the node list
    - Uses an in-memory cache to avoid repeated API calls
    - Falls back to the short hostname if the API call fails
    """
    now = time.time()
    cached_name = _PROXMOX_NODE_CACHE.get("name")
    cached_ts = _PROXMOX_NODE_CACHE.get("timestamp", 0.0)

    # Cache hit
    if cached_name and (now - float(cached_ts)) < _PROXMOX_NODE_CACHE_TTL:
        return str(cached_name)

    # Get local hostname for matching
    local_hostname = socket.gethostname().split(".", 1)[0].lower()

    # Try Proxmox API
    try:
        result = subprocess.run(
            ["pvesh", "get", "/nodes", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode == 0 and result.stdout:
            nodes = json.loads(result.stdout)
            if isinstance(nodes, list) and nodes:
                # In a cluster, find the node that matches local hostname
                # Node names in Proxmox typically match the hostname
                for node_info in nodes:
                    node_name = node_info.get("node", "")
                    if node_name.lower() == local_hostname:
                        _PROXMOX_NODE_CACHE["name"] = node_name
                        _PROXMOX_NODE_CACHE["timestamp"] = now
                        return node_name
                
                # If no exact match, try partial match (hostname might be truncated)
                for node_info in nodes:
                    node_name = node_info.get("node", "")
                    if local_hostname.startswith(node_name.lower()) or node_name.lower().startswith(local_hostname):
                        _PROXMOX_NODE_CACHE["name"] = node_name
                        _PROXMOX_NODE_CACHE["timestamp"] = now
                        return node_name
                
                # Last resort: if single node cluster, use that node
                if len(nodes) == 1:
                    node_name = nodes[0].get("node")
                    if node_name:
                        _PROXMOX_NODE_CACHE["name"] = node_name
                        _PROXMOX_NODE_CACHE["timestamp"] = now
                        return node_name

    except Exception as exc:
        logger.warning("Failed to get Proxmox node name from API: %s", exc)

    # Fallback: short hostname (without domain)
    return local_hostname


# -------------------------------------------------------------------
# Flask application and Blueprints
# -------------------------------------------------------------------
app = Flask(__name__)
# DoS / cost-amplification cap (audit Tier 3.1 — sin body-size cap en POSTs).
# Without this an authenticated client could POST a 100 MB body to /api/notifications/test-ai
# (or any other AI endpoint) and stall the dispatch thread plus rack up real
# money on the configured AI provider. 1 MB is generous for any legitimate
# request — settings payloads top out around 50 KB, AI prompts at 8 KB.
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1 MB

# Restrict CORS to known origins (audit Tier 3 #18). The previous wide-open
# `CORS(app)` enabled drive-by attacks: any malicious site visited by an
# admin's browser could call the API directly.
#
# In production the AppImage serves both Flask AND the Next.js static export
# from the same origin — CORS isn't actually needed for the dashboard itself
# in that case. We keep the dev origin (`localhost:3000` for `npm run dev`)
# always allowed, and let operators add their own deployment URL via the
# PROXMENUX_CORS_ORIGINS env var (comma-separated).
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8008",
    "http://127.0.0.1:8008",
    "https://localhost:8008",
    "https://127.0.0.1:8008",
]
_extra_origins = os.environ.get("PROXMENUX_CORS_ORIGINS", "").strip()
if _extra_origins:
    _cors_origins.extend(o.strip() for o in _extra_origins.split(",") if o.strip())
CORS(app, origins=_cors_origins, supports_credentials=True)

# Sprint 12A: scan for post-install function updates BEFORE the rest of
# the update-check pipeline (Proxmox upgrade poll, ProxMenux self-update
# check) kicks in. The scan parses the on-disk auto/customizable post-
# install scripts and compares each declared `# version:` against the
# version recorded in installed_tools.json — anything bumped is cached
# in memory + written to updates_available.json so the bash menu and
# the notification poller can read it without re-parsing.
post_install_versions.scan_at_startup()

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(health_bp)
app.register_blueprint(proxmenux_bp)
app.register_blueprint(security_bp)
app.register_blueprint(notification_bp)
app.register_blueprint(oci_bp)

# Initialize terminal / WebSocket routes
init_terminal_routes(app)


# -------------------------------------------------------------------
# Security headers — defense-in-depth (audit Tier 2 #16)
# -------------------------------------------------------------------
# Defense-in-depth header policy. The XSS sinks in the React frontend are
# closed (audit Tier 2 #13/#14/#17b — VM notes, Lynis report, terminal
# interaction message). This header layer is the second line of defense.
#
# `script-src 'self' 'unsafe-inline' 'unsafe-eval'`:
#   - `'unsafe-inline'` is REQUIRED because Next.js static export injects
#     `<script id="__NEXT_DATA__">` and a small bootstrap inline script for
#     hydration. Without it the dashboard renders a blank page.
#   - `'unsafe-eval'` is also required because the Next.js client runtime
#     uses `Function()` for some lazy-loaded chunks.
#   A nonce-based CSP would let us drop these, but it requires per-request
#   nonce generation that the static export doesn't support — switching to
#   nonces is a build-system change, not a header change.
# `style-src 'self' 'unsafe-inline'`: shadcn components and the Lynis
#   printable report use inline styles by design.
# `connect-src` includes `wss:` for terminal WebSockets and `https:` for
#   third-party AI providers (OpenAI / Anthropic).
@app.after_request
def _apply_security_headers(response):
    # Don't override if a downstream handler already set a custom CSP.
    if 'Content-Security-Policy' not in response.headers:
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss: https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    return response


# -------------------------------------------------------------------
# Fail2Ban application-level ban check (for reverse proxy scenarios)
# -------------------------------------------------------------------
# When users access via a reverse proxy, iptables/nftables cannot block
# the real client IP because the TCP connection comes from the proxy.
# This middleware checks if the client's real IP (from X-Forwarded-For)
# is banned in the 'proxmenux' fail2ban jail and blocks at app level.
import subprocess as _f2b_subprocess
import time as _f2b_time

# Cache banned IPs for 30 seconds to avoid calling fail2ban-client on every request
_f2b_banned_cache = {"ips": set(), "ts": 0, "ttl": 30}

def _f2b_get_banned_ips():
    """Get currently banned IPs from the proxmenux jail, with caching."""
    now = _f2b_time.time()
    if now - _f2b_banned_cache["ts"] < _f2b_banned_cache["ttl"]:
        return _f2b_banned_cache["ips"]
    try:
        result = _f2b_subprocess.run(
            ["fail2ban-client", "status", "proxmenux"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "Banned IP list:" in line:
                    ip_str = line.split(":", 1)[1].strip()
                    banned = set(ip.strip() for ip in ip_str.split() if ip.strip())
                    _f2b_banned_cache["ips"] = banned
                    _f2b_banned_cache["ts"] = now
                    return banned
    except Exception:
        pass
    return _f2b_banned_cache["ips"]

# XFF / X-Real-IP are only honored when the operator opts in by setting
# PROXMENUX_TRUST_PROXY=1 (deployment is behind a real reverse proxy that the
# admin controls). The previous unconditional trust let any client spoof
# `X-Forwarded-For: 1.2.3.4` to bypass Fail2Ban (each request appears to
# come from a different IP, so the per-IP attempt counter never trips) and
# poison the access logs. See audit Tier 3 #20.
_TRUST_PROXY = os.environ.get("PROXMENUX_TRUST_PROXY", "0") == "1"


def _f2b_get_client_ip():
    """Get the real client IP, supporting reverse proxies only when explicitly trusted."""
    if _TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip.strip()
    return request.remote_addr or "unknown"

@app.before_request
def check_fail2ban_ban():
    """Block requests from IPs banned by fail2ban (works with reverse proxies)."""
    client_ip = _f2b_get_client_ip()
    banned_ips = _f2b_get_banned_ips()
    if client_ip in banned_ips:
        return jsonify({
            "success": False,
            "message": "Access denied. Your IP has been temporarily banned due to too many failed login attempts."
        }), 403


def identify_gpu_type(name, vendor=None, bus=None, driver=None):
    """
    Returns: 'Integrated' or 'PCI' (discrete)
    - name: full device name (e.g. 'AMD/ATI Phoenix3 (rev b3)')
    - vendor: 'Intel', 'AMD', 'NVIDIA', 'ASPEED', 'Matrox'... (optional)
    - bus: address such as '0000:65:00.0' or '65:00.0' (optional)
    - driver: e.g. 'i915', 'amdgpu', 'nvidia' (optional)
    """

    n = (name or "").lower()
    v = (vendor or "").lower()
    d = (driver or "").lower()
    b = (bus or "")

    bmc_keywords = ['aspeed', 'ast', 'matrox g200', 'g200e', 'g200eh', 'mgag200']
    if any(k in n for k in bmc_keywords) or v in ['aspeed', 'matrox']:
        return 'Integrated'

    intel_igpu_words = ['uhd graphics', 'iris', 'integrated graphics controller']
    if v == 'intel' or 'intel corporation' in n:
        if d == 'i915' or any(w in n for w in intel_igpu_words):
            return 'Integrated'
        if b.startswith('0000:00:02.0') or b.startswith('00:02.0'):
            return 'Integrated'
        return 'Integrated'

    amd_apu_keywords = [
        'phoenix', 'rembrandt', 'cezanne', 'lucienne', 'renoir', 'picasso', 'raven',
        'dali', 'barcelo', 'van gogh', 'mendocino', 'hawk point', 'strix point',
        'radeon 780m', 'radeon 760m', 'radeon 680m', 'radeon 660m',
        'vega 3', 'vega 6', 'vega 7', 'vega 8', 'vega 10', 'vega 11'
    ]
    if v.startswith('advanced micro devices') or v == 'amd' or 'amd/ati' in n:
        if any(k in n for k in amd_apu_keywords):
            return 'Integrated'
        if 'radeon graphics' in n:
            return 'Integrated'
        discrete_markers = ['rx ', 'rx-', 'radeon pro', 'w5', 'w6', 'polaris', 'navi', 'xt ', 'xt-']
        if d == 'amdgpu' and not any(m in n for m in discrete_markers):
            return 'Integrated'
        return 'PCI'

    if v == 'nvidia' or 'nvidia corporation' in n:
        if 'tegra' in n:
            return 'Integrated'
        return 'PCI'

    soc_keywords = ['tegra', 'mali', 'adreno', 'powervr', 'videocore']
    if any(k in n for k in soc_keywords):
        return 'Integrated'

    if b.startswith('0000:00:') or b.startswith('00:'):
        return 'Integrated'

    # Fallback
    return 'PCI'


def parse_lxc_hardware_config(vmid, node):
    """Parse LXC configuration file to detect hardware passthrough"""
    hardware_info = {
        'privileged': None,
        'gpu_passthrough': [],
        'devices': []
    }
    
    try:
        config_path = f'/etc/pve/lxc/{vmid}.conf'
        
        if not os.path.exists(config_path):
            return hardware_info
        
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Check if privileged or unprivileged
        if 'unprivileged: 1' in config_content:
            hardware_info['privileged'] = False
        elif 'unprivileged: 0' in config_content:
            hardware_info['privileged'] = True
        else:
            # Check for lxc.cap.drop (empty means privileged)
            if 'lxc.cap.drop:' in config_content and 'lxc.cap.drop: \n' in config_content:
                hardware_info['privileged'] = True
            elif 'lxc.cgroup2.devices.allow: a' in config_content:
                hardware_info['privileged'] = True
        
        # Detect GPU passthrough
        gpu_types = []
        
        if '/dev/dri' in config_content or 'renderD128' in config_content:
            if 'Intel/AMD GPU' not in gpu_types:
                gpu_types.append('Intel/AMD GPU')
        
        # NVIDIA GPU detection
        if 'nvidia' in config_content.lower():
            if any(x in config_content for x in ['nvidia0', 'nvidiactl', 'nvidia-uvm']):
                if 'NVIDIA GPU' not in gpu_types:
                    gpu_types.append('NVIDIA GPU')
        
        hardware_info['gpu_passthrough'] = gpu_types
        
        # Detect other hardware devices
        devices = []
        
        # Coral TPU detection
        if 'apex' in config_content.lower() or 'coral' in config_content.lower():
            devices.append('Coral TPU')
        
        # USB devices detection
        if 'ttyUSB' in config_content or 'ttyACM' in config_content:
            devices.append('USB Serial Devices')
        
        if '/dev/bus/usb' in config_content:
            devices.append('USB Passthrough')
        
        # Framebuffer detection
        if '/dev/fb0' in config_content:
            devices.append('Framebuffer')
        
        # Audio devices detection
        if '/dev/snd' in config_content:
            devices.append('Audio Devices')
        
        # Input devices detection
        if '/dev/input' in config_content:
            devices.append('Input Devices')
        
        # TTY detection
        if 'tty7' in config_content:
            devices.append('TTY Console')
        
        hardware_info['devices'] = devices
        
    except Exception as e:
        pass
    
    return hardware_info


def get_lxc_ip_from_lxc_info(vmid):
    """Get LXC IP addresses using lxc-info command (for DHCP containers)
    Returns a dict with all IPs and classification"""
    try:
        result = subprocess.run(
            ['lxc-info', '-n', str(vmid), '-iH'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            ips_str = result.stdout.strip()
            if ips_str and ips_str != '':
                # Split multiple IPs (space-separated)
                ips = ips_str.split()
                
                # Classify IPs
                real_ips = []
                docker_ips = []
                
                for ip in ips:
                    # Docker bridge IPs typically start with 172.
                    if ip.startswith('172.'):
                        docker_ips.append(ip)
                    else:
                        # Real network IPs (192.168.x.x, 10.x.x.x, etc.)
                        real_ips.append(ip)
                
                return {
                    'all_ips': ips,
                    'real_ips': real_ips,
                    'docker_ips': docker_ips,
                    'primary_ip': real_ips[0] if real_ips else (docker_ips[0] if docker_ips else ips[0])
                }
        return None
    except Exception:
        # Silently fail if lxc-info is not available or fails
        return None

# Helper function to format bytes into human-readable string
def format_bytes(size_in_bytes):
    """Converts bytes to a human-readable string (KB, MB, GB, TB)."""
    if size_in_bytes is None:
        return "N/A"
    if size_in_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    return f"{s} {size_name[i]}"

# Helper functions for system info
def get_cpu_temperature():
    """Get CPU temperature using psutil if available, otherwise return 0."""
    temp = 0
    try:
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                # Priority order for temperature sensors:
                # - coretemp: Intel CPU sensor
                # - k10temp: AMD CPU sensor (Ryzen, EPYC, etc.)
                # - cpu_thermal: Generic CPU thermal sensor
                # - zenpower: Alternative AMD sensor (if zenpower driver is used)
                # - acpitz: ACPI thermal zone (fallback, usually motherboard)
                sensor_priority = ['coretemp', 'k10temp', 'cpu_thermal', 'zenpower', 'acpitz']
                for sensor_name in sensor_priority:
                    if sensor_name in temps and temps[sensor_name]:
                        temp = temps[sensor_name][0].current

                        break
                
                # If no priority sensor found, use first available
                if temp == 0:
                    for name, entries in temps.items():
                        if entries:
                            temp = entries[0].current

                            break
    except Exception as e:
        # print(f"Warning: Error reading temperature sensors: {e}")
        pass
    return temp

# ── Temperature History (SQLite) ──────────────────────────────────────────────
# Stores CPU temperature readings every 60s in a lightweight SQLite database.
# Data is persisted in /usr/local/share/proxmenux/ alongside config.json.
# Retention: 30 days max, cleaned up every hour.

TEMP_DB_DIR = "/usr/local/share/proxmenux"
TEMP_DB_PATH = os.path.join(TEMP_DB_DIR, "monitor.db")

def _get_temp_db():
    """Get a SQLite connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(TEMP_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_temperature_db():
    """Create the temperature_history table if it doesn't exist."""
    try:
        os.makedirs(TEMP_DB_DIR, exist_ok=True)
        conn = _get_temp_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS temperature_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                value REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_temp_timestamp 
            ON temperature_history(timestamp)
        """)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[ProxMenux] Temperature DB init failed: {e}")
        return False

def _record_temperature():
    """Insert a single temperature reading into the DB."""
    try:
        temp = get_cpu_temperature()
        if temp and temp > 0:
            conn = _get_temp_db()
            conn.execute(
                "INSERT INTO temperature_history (timestamp, value) VALUES (?, ?)",
                (int(time.time()), round(temp, 1))
            )
            conn.commit()
            conn.close()
    except Exception:
        pass

def _cleanup_old_temperature_data():
    """Remove temperature records older than 30 days."""
    try:
        cutoff = int(time.time()) - (30 * 24 * 3600)
        conn = _get_temp_db()
        conn.execute("DELETE FROM temperature_history WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_temperature_sparkline(minutes=60):
    """Get recent temperature data for the overview sparkline."""
    try:
        since = int(time.time()) - (minutes * 60)
        conn = _get_temp_db()
        cursor = conn.execute(
            "SELECT timestamp, value FROM temperature_history WHERE timestamp >= ? ORDER BY timestamp ASC",
            (since,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"timestamp": r[0], "value": r[1]} for r in rows]
    except Exception:
        return []

def get_temperature_history(timeframe="hour"):
    """Get temperature history with downsampling for longer timeframes."""
    try:
        now = int(time.time())
        if timeframe == "hour":
            since = now - 3600
            interval = None  # All points (~60)
        elif timeframe == "day":
            since = now - 86400
            interval = 300  # 5 min avg (288 points)
        elif timeframe == "week":
            since = now - 7 * 86400
            interval = 1800  # 30 min avg (336 points)
        elif timeframe == "month":
            since = now - 30 * 86400
            interval = 7200  # 2h avg (360 points)
        else:
            since = now - 3600
            interval = None
        
        conn = _get_temp_db()
        
        if interval is None:
            cursor = conn.execute(
                "SELECT timestamp, value FROM temperature_history WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since,)
            )
            rows = cursor.fetchall()
            data = [{"timestamp": r[0], "value": r[1]} for r in rows]
        else:
            # Downsample: average value per interval bucket
            cursor = conn.execute(
                """SELECT (timestamp / ?) * ? as bucket, 
                          ROUND(AVG(value), 1) as avg_val,
                          ROUND(MIN(value), 1) as min_val,
                          ROUND(MAX(value), 1) as max_val
                   FROM temperature_history 
                   WHERE timestamp >= ? 
                   GROUP BY bucket 
                   ORDER BY bucket ASC""",
                (interval, interval, since)
            )
            rows = cursor.fetchall()
            data = [{"timestamp": r[0], "value": r[1], "min": r[2], "max": r[3]} for r in rows]
        
        conn.close()
        
        # Compute stats
        if data:
            values = [d["value"] for d in data]
            # For downsampled data, use actual min/max from each bucket
            # (not min/max of the averages, which would be wrong)
            if interval is not None and "min" in data[0]:
                actual_min = min(d["min"] for d in data)
                actual_max = max(d["max"] for d in data)
            else:
                actual_min = min(values)
                actual_max = max(values)
            stats = {
                "min": round(actual_min, 1),
                "max": round(actual_max, 1),
                "avg": round(sum(values) / len(values), 1),
                "current": values[-1]
            }
        else:
            stats = {"min": 0, "max": 0, "avg": 0, "current": 0}
        
        return {"data": data, "stats": stats}
    except Exception as e:
        return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0, "current": 0}}

def _temperature_collector_loop():
    """Background thread: collect temperature and latency with staggered timing.
    
    Staggered schedule to avoid CPU spikes:
    - Temperature record: every 60s at offset 40s
    - Latency pings: every 60s at offset 25s  
    - Cleanup: every 60 min at offset 120s
    """
    import time as _time
    
    RECORD_INTERVAL = 60
    TEMP_OFFSET = 40      # Record temp at :40 of each minute
    LATENCY_OFFSET = 25   # Record latency at :25 of each minute
    CLEANUP_INTERVAL = 3600  # 60 minutes
    CLEANUP_OFFSET = 120  # Cleanup at 2 min after the hour mark
    
    # Initial delays to stagger from other collectors
    _time.sleep(LATENCY_OFFSET)  # Start latency first
    
    last_temp = _time.monotonic()
    last_latency = _time.monotonic()
    last_cleanup = _time.monotonic() - CLEANUP_INTERVAL + CLEANUP_OFFSET  # First cleanup after offset
    
    while True:
        now = _time.monotonic()
        
        # Latency pings (offset 25s - runs first in each cycle)
        if now - last_latency >= RECORD_INTERVAL:
            _record_latency()
            last_latency = now
        
        # Temperature record (offset 40s - 15s after latency)
        _time.sleep(15)
        _record_temperature()
        # Sprint 14: piggy-back the per-disk temperature sampler on
        # the same minute tick. The sampler enumerates non-USB
        # disks and writes a row each via smartctl; total cost is
        # well under a second on typical hosts. Wrapped in a
        # try-block so a stuck smartctl call can't break the
        # CPU/latency pipeline.
        try:
            import disk_temperature_history
            disk_temperature_history.record_all_disk_temperatures()
        except Exception as e:
            print(f"[ProxMenux] Disk temperature sample failed: {e}")
        last_temp = _time.monotonic()

        # Cleanup check (every hour, offset from main cycles)
        if _time.monotonic() - last_cleanup >= CLEANUP_INTERVAL:
            _cleanup_old_temperature_data()
            _cleanup_old_latency_data()
            try:
                import disk_temperature_history
                disk_temperature_history.cleanup_old_disk_temperature_data()
            except Exception:
                pass
            last_cleanup = _time.monotonic()
        
        # Sleep remaining time until next cycle
        elapsed = _time.monotonic() - last_latency
        remaining = max(RECORD_INTERVAL - elapsed, 1)
        _time.sleep(remaining)


# ── Latency History (SQLite) ──────────────────────────────────────────────────
# Stores network latency readings every 60s in the same database as temperature.
# Supports multiple targets (gateway, cloudflare, google).
# Retention: 7 days max, cleaned up every hour.

LATENCY_TARGETS = {
    'gateway': None,  # Auto-detect default gateway
    'cloudflare': '1.1.1.1',
    'google': '8.8.8.8',
}

def _get_default_gateway():
    """Get the default gateway IP address."""
    try:
        result = subprocess.run(
            ['ip', 'route', 'show', 'default'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse: "default via 192.168.1.1 dev eth0"
            parts = result.stdout.strip().split()
            if 'via' in parts:
                idx = parts.index('via')
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    except Exception:
        pass
    return '192.168.1.1'  # Fallback

def init_latency_db():
    """Create the latency_history table if it doesn't exist."""
    try:
        conn = _get_temp_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS latency_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                target TEXT NOT NULL,
                latency_avg REAL,
                latency_min REAL,
                latency_max REAL,
                packet_loss REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_latency_timestamp_target 
            ON latency_history(timestamp, target)
        """)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[ProxMenux] Latency DB init failed: {e}")
        return False

def _measure_latency(target_ip: str) -> dict:
    """Ping a target and return latency stats."""
    try:
        result = subprocess.run(
            ['ping', '-c', '3', '-W', '2', target_ip],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            latencies = []
            for line in result.stdout.split('\n'):
                if 'time=' in line:
                    try:
                        latency_str = line.split('time=')[1].split()[0]
                        latencies.append(float(latency_str))
                    except:
                        pass
            
            if latencies:
                return {
                    'success': True,
                    'avg': round(sum(latencies) / len(latencies), 1),
                    'min': round(min(latencies), 1),
                    'max': round(max(latencies), 1),
                    'packet_loss': round((3 - len(latencies)) / 3 * 100, 1)
                }
        
        # Ping failed - 100% packet loss
        return {'success': False, 'avg': None, 'min': None, 'max': None, 'packet_loss': 100.0}
    except Exception:
        return {'success': False, 'avg': None, 'min': None, 'max': None, 'packet_loss': 100.0}

def _record_latency():
    """Record latency to the default gateway."""
    try:
        gateway = _get_default_gateway()
        stats = _measure_latency(gateway)
        
        conn = _get_temp_db()
        conn.execute(
            """INSERT INTO latency_history 
               (timestamp, target, latency_avg, latency_min, latency_max, packet_loss) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (int(time.time()), 'gateway', stats['avg'], stats['min'], stats['max'], stats['packet_loss'])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def _cleanup_old_latency_data():
    """Remove latency records older than 7 days."""
    try:
        cutoff = int(time.time()) - (7 * 24 * 3600)
        conn = _get_temp_db()
        conn.execute("DELETE FROM latency_history WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_latency_history(target='gateway', timeframe='hour'):
    """Get latency history with downsampling for longer timeframes."""
    try:
        now = int(time.time())
        if timeframe == "hour":
            since = now - 3600
            interval = None  # All points (~60)
        elif timeframe == "6hour":
            since = now - 6 * 3600
            interval = 300  # 5 min avg
        elif timeframe == "day":
            since = now - 86400
            interval = 600  # 10 min avg
        elif timeframe == "3day":
            since = now - 3 * 86400
            interval = 1800  # 30 min avg
        elif timeframe == "week":
            since = now - 7 * 86400
            interval = 3600  # 1h avg
        else:
            since = now - 3600
            interval = None
        
        conn = _get_temp_db()
        
        if interval is None:
            cursor = conn.execute(
                """SELECT timestamp, latency_avg, latency_min, latency_max, packet_loss 
                   FROM latency_history 
                   WHERE timestamp >= ? AND target = ? 
                   ORDER BY timestamp ASC""",
                (since, target)
            )
            rows = cursor.fetchall()
            data = [{"timestamp": r[0], "value": r[1], "min": r[2], "max": r[3], "packet_loss": r[4]} for r in rows if r[1] is not None]
        else:
            cursor = conn.execute(
                """SELECT (timestamp / ?) * ? as bucket, 
                          ROUND(AVG(latency_avg), 1) as avg_val,
                          ROUND(MIN(latency_min), 1) as min_val,
                          ROUND(MAX(latency_max), 1) as max_val,
                          ROUND(AVG(packet_loss), 1) as avg_loss
                   FROM latency_history 
                   WHERE timestamp >= ? AND target = ?
                   GROUP BY bucket 
                   ORDER BY bucket ASC""",
                (interval, interval, since, target)
            )
            rows = cursor.fetchall()
            data = [{"timestamp": r[0], "value": r[1], "min": r[2], "max": r[3], "packet_loss": r[4]} for r in rows if r[1] is not None]
        
        conn.close()
        
        # Compute stats - always use actual min/max values to preserve spikes
        if data:
            values = [d["value"] for d in data if d["value"] is not None]
            mins = [d["min"] for d in data if d.get("min") is not None]
            maxs = [d["max"] for d in data if d.get("max") is not None]
            
            if values:
                stats = {
                    # Use actual min from all samples (preserves lowest value)
                    "min": round(min(mins) if mins else min(values), 1),
                    # Use actual max from all samples (preserves spikes)
                    "max": round(max(maxs) if maxs else max(values), 1),
                    "avg": round(sum(values) / len(values), 1),
                    "current": values[-1] if values else 0
                }
            else:
                stats = {"min": 0, "max": 0, "avg": 0, "current": 0}
        else:
            stats = {"min": 0, "max": 0, "avg": 0, "current": 0}
        
        return {"data": data, "stats": stats, "target": target}
    except Exception as e:
        return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0, "current": 0}, "target": target}

def get_current_latency(target='gateway'):
    """Get the most recent latency measurement for a target."""
    try:
        # If gateway, resolve to actual IP
        if target == 'gateway':
            target_ip = _get_default_gateway()
        else:
            target_ip = LATENCY_TARGETS.get(target, target)
        
        stats = _measure_latency(target_ip)
        return {
            'target': target,
            'target_ip': target_ip,
            'latency_avg': stats['avg'],
            'latency_min': stats['min'],
            'latency_max': stats['max'],
            'packet_loss': stats['packet_loss'],
            'status': 'ok' if stats['success'] and stats['avg'] and stats['avg'] < 100 else 'warning' if stats['success'] else 'error'
        }
    except Exception:
        return {'target': target, 'latency_avg': None, 'status': 'error'}


def _capture_health_journal_context(categories: list, reason: str = '') -> str:
    """Capture journal context relevant to health issues.
    
    Maps health categories to specific journal keywords so the AI
    receives relevant system logs for diagnosis.
    
    Args:
        categories: List of health category keys (e.g., ['storage', 'network'])
        reason: The reason string from health check (used to extract more keywords)
    
    Returns:
        Filtered journal output as string
    """
    import subprocess
    import re
    
    # Map health categories to relevant journal keywords
    CATEGORY_KEYWORDS = {
        'storage': ['mount', 'nfs', 'cifs', 'smb', 'zfs', 'lvm', 'disk', 'nvme', 
                    'sata', 'ata', 'I/O error', 'read error', 'write error',
                    'filesystem', 'ext4', 'xfs', 'btrfs', 'pbs', 'datastore'],
        'disks': ['smartd', 'smart', 'ata', 'sata', 'nvme', 'disk', 'I/O error',
                  'bad sector', 'reallocated', 'pending sector', 'uncorrectable'],
        'network': ['bond', 'bridge', 'vmbr', 'eth', 'network', 'link down',
                    'carrier', 'no route', 'unreachable', 'timeout', 'connection'],
        'services': ['pveproxy', 'pvedaemon', 'pvestatd', 'corosync', 'ceph',
                     'systemd', 'failed', 'service', 'unit', 'start', 'stop'],
        'vms': ['qemu', 'kvm', 'lxc', 'vzdump', 'qm', 'pct', 'guest agent',
                'qemu-ga', 'migration', 'snapshot', 'pve-container', 'vzstart',
                'failed to start', 'start error', 'activation failed', 'cannot start',
                'qemu-server', 'CT ', 'VM '],
        'memory': ['oom', 'out of memory', 'killed process', 'swap', 'memory'],
        'cpu': ['thermal', 'temperature', 'throttl', 'mce', 'machine check'],
        'updates': ['apt', 'dpkg', 'upgrade', 'update', 'package'],
        'certificates': ['ssl', 'certificate', 'cert', 'expired', 'pve-ssl'],
        'logs': ['rsyslog', 'journal', 'log rotation'],
        'latency': ['ping', 'latency', 'timeout', 'unreachable', 'network'],
    }
    
    # Collect keywords for all degraded categories
    keywords = set()
    for cat in categories:
        cat_lower = cat.lower()
        if cat_lower in CATEGORY_KEYWORDS:
            keywords.update(CATEGORY_KEYWORDS[cat_lower])
    
    # Extract additional keywords from reason (IPs, hostnames, storage names)
    if reason:
        # Find IP addresses
        ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', reason)
        keywords.update(ips)
        
        # Find storage/service names (words in quotes or after colon)
        quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", reason)
        for match in quoted:
            keywords.update(w for w in match if w)
    
    if not keywords:
        return ""
    
    try:
        # Build grep pattern
        pattern = "|".join(re.escape(k) for k in keywords if k)
        if not pattern:
            return ""
        
        # Capture recent journal entries matching keywords.
        # Use -b 0 to only include logs from the current boot.
        # Filter out the Monitor's own stdout (AppRun, [HealthPersistence],
        # proxmenux-auth, etc.) BEFORE keyword matching — otherwise a startup
        # line like "[HealthPersistence] Database initialized with 13 tables"
        # leaks into the AI context because grep -iE 'ata' matches the
        # substring "ata" in "dATAbase". Self-logs are never system evidence.
        #
        # Also exclude systemd actions on the proxmenux-monitor unit itself
        # (e.g. "proxmenux-monitor.service: Killed process 2010621 with
        # signal SIGKILL"). When a kernel event fires within the same
        # 10-min window as one of our own watchdog kills, the SIGKILL
        # line would otherwise leak into the journal_context and the AI
        # would paste it under the unrelated event as "📝 Log: …".
        cmd = (
            f"journalctl -b 0 --since='10 minutes ago' --no-pager -n 500 2>/dev/null | "
            f"grep -vE 'AppRun\\[|proxmenux-auth|\\[HealthPersistence\\]|\\[ProxMenux\\]|\\[NotificationManager\\]|\\[AIEnhancer\\]|proxmenux-monitor\\.service' | "
            f"grep -iE '{pattern}' | tail -n 30"
        )
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return ""
    except Exception:
        return ""


def _health_collector_loop():
    """Background thread: run full health checks every 5 minutes.
    Keeps the health cache always fresh and records events/errors in the DB.
    Also emits notifications when a health category degrades (OK -> WARNING/CRITICAL).
    
    Staggered: starts at 55s offset to avoid collision with other collectors."""
    from health_monitor import health_monitor
    
    # Wait 55s after startup (staggered from other collectors: temp=40s, latency=25s)
    time.sleep(55)
    
    # Track previous status per category to detect transitions
    _prev_statuses = {}
    # Severity ranking for comparison
    _SEV_RANK = {'OK': 0, 'INFO': 0, 'UNKNOWN': 1, 'WARNING': 2, 'CRITICAL': 3}
    # Human-readable category names
    _CAT_NAMES = {
        'cpu': 'CPU Usage & Temperature',
        'memory': 'Memory & Swap',
        'storage': 'Storage Mounts & Space',
        'disks': 'Disk I/O & Errors',
        'network': 'Network Interfaces',
        'vms': 'VMs & Containers',
        'services': 'PVE Services',
        'logs': 'System Logs',
        'updates': 'System Updates',
        'security': 'Security',
    }
    # Import centralized startup grace management
    import startup_grace
    
    while True:
        try:
            # Run full health check (results get cached internally + recorded in DB)
            result = health_monitor.get_detailed_status()
            
            # Update the quick-status cache so the header stays fresh without extra work
            overall = result.get('overall', 'OK')
            summary = result.get('summary', 'All systems operational')
            health_monitor.cached_results['_bg_overall'] = {
                'status': overall,
                'summary': summary
            }
            # Cache the full detailed result so the modal can return it instantly
            health_monitor.cached_results['_bg_detailed'] = result
            health_monitor.last_check_times['_bg_overall'] = time.time()
            health_monitor.last_check_times['_bg_detailed'] = time.time()
            
            # ── Health degradation notifications ──
            # Compare each category's current status to previous cycle.
            # Notify when a category DEGRADES (OK->WARNING, WARNING->CRITICAL, etc.)
            # Include the detailed 'reason' so the user knows exactly what triggered it.
            # 
            # IMPORTANT: Some health categories map to specific notification toggles:
            #   - network + latency issue -> 'network_latency' toggle
            #   - network + connectivity issue -> 'network_down' toggle
            # If the specific toggle is disabled, skip that notification.
            details = result.get('details', {})
            degraded = []
            
            # Map health categories to specific event types for toggle checks.
            # `_CATEGORY_EVENT_MAP` is keyword-based for sub-types (network_down vs
            # network_latency). `_BROAD_CATEGORY_TO_EVENT` is the catch-all fallback
            # used when no keyword matches: if the user has muted the direct
            # Resources/Storage event for a category (e.g. ram_high, cpu_high), do
            # not re-emit the same condition under the Health Monitor banner. This
            # closes the "muted ram_high but still got health_degraded for memory"
            # double-event reported by users.
            _CATEGORY_EVENT_MAP = {
                # (category, reason_contains) -> event_type to check
                ('network', 'latency'): 'network_latency',
                ('network', 'connectivity'): 'network_down',
                ('network', 'unreachable'): 'network_down',
            }
            _BROAD_CATEGORY_TO_EVENT = {
                'cpu': 'cpu_high',
                'memory': 'ram_high',
                'load': 'load_high',
                'temperature': 'temp_high',
                'disk': 'disk_space_low',
                'disks': 'disk_io_error',
                'smart': 'disk_io_error',
                'zfs': 'disk_io_error',
                'storage': 'storage_unavailable',
                # 'network' intentionally not here — handled by the keyword map above.
                'pve_services': 'service_fail',
                'security': 'auth_fail',
                'updates': 'update_summary',
            }

            # Sub-categories already rolled up into details['storage']
            # by _check_proxmox_storage_status. Emitting them as their
            # own health_degraded entries duplicates the same warning
            # (e.g. "Storage Mounts & Space" + "PVE Storage Capacity"
            # both saying "PBS-Cloud (pbs) usage ≥70%"). Skip them at
            # the notification layer — they still update _prev_statuses
            # so a future degradation transition is detected normally.
            _STORAGE_SUBCATEGORIES = {
                'pve_storage_capacity', 'zfs_pool_capacity',
                'lxc_disk', 'lxc_mounts', 'remote_mounts',
            }

            for cat_key, cat_data in details.items():
                cur_status = cat_data.get('status', 'OK')
                prev_status = _prev_statuses.get(cat_key, 'OK')
                cur_rank = _SEV_RANK.get(cur_status, 0)
                prev_rank = _SEV_RANK.get(prev_status, 0)

                if cat_key in _STORAGE_SUBCATEGORIES:
                    _prev_statuses[cat_key] = cur_status
                    continue

                if cur_rank > prev_rank and cur_rank >= 2:  # WARNING or CRITICAL
                    reason = cat_data.get('reason', f'{cat_key} status changed to {cur_status}')
                    reason_lower = reason.lower()
                    cat_name = _CAT_NAMES.get(cat_key, cat_key)

                    # Check if this specific notification type is enabled.
                    skip_notification = False
                    keyword_matched = False
                    for (map_cat, map_keyword), event_type in _CATEGORY_EVENT_MAP.items():
                        if cat_key == map_cat and map_keyword in reason_lower:
                            keyword_matched = True
                            if not notification_manager.is_event_enabled(event_type):
                                skip_notification = True
                            break

                    # Broad category fallback — only when no keyword sub-type matched.
                    # If the user explicitly muted the linked Resources/Storage event,
                    # don't surface the same condition through health_degraded.
                    if not keyword_matched and not skip_notification:
                        broad_event = _BROAD_CATEGORY_TO_EVENT.get(cat_key)
                        if broad_event and not notification_manager.is_event_enabled(broad_event):
                            skip_notification = True

                    # Startup grace period: skip transient issues from categories
                    # that typically need time to stabilize after boot
                    if startup_grace.should_suppress_category(cat_key):
                        skip_notification = True
                    
                    if not skip_notification:
                        degraded.append({
                            'cat_key': cat_key,  # Original key for journal capture
                            'category': cat_name,
                            'status': cur_status,
                            'reason': reason,
                        })
                
                _prev_statuses[cat_key] = cur_status
            
            # Send grouped notification if any categories degraded
            if degraded and notification_manager._enabled:
                hostname = result.get('hostname', '')
                if not hostname:
                    import socket as _sock
                    hostname = _sock.gethostname()
                
                # Capture journal context for AI enrichment
                # Extract category keys and reasons for keyword matching
                cat_keys = [d.get('cat_key', d.get('category', '').lower()) for d in degraded]
                all_reasons = ' '.join(d.get('reason', '') for d in degraded)
                journal_context = _capture_health_journal_context(cat_keys, all_reasons)
                
                if len(degraded) == 1:
                    d = degraded[0]
                    title = f"{hostname}: Health {d['status']} - {d['category']}"
                    body = d['reason']
                    severity = d['status']
                else:
                    # Multiple categories degraded at once -- group them
                    max_sev = max(degraded, key=lambda x: _SEV_RANK.get(x['status'], 0))['status']
                    title = f"{hostname}: {len(degraded)} health checks degraded"
                    lines = []
                    for d in degraded:
                        lines.append(f"  [{d['status']}] {d['category']}: {d['reason']}")
                    body = '\n'.join(lines)
                    severity = max_sev
                
                try:
                    # Use emit_event (not send_notification) so the
                    # 24h fingerprint cooldown applies. send_notification
                    # was bypassing the cooldown — every 5-min run of
                    # this loop fired a fresh notification, producing a
                    # cascade like "PVE storage ≥85%" every 6-10 min for
                    # the same condition. The fingerprint includes the
                    # set of degraded categories, so a *different*
                    # category degrading later still notifies.
                    cat_signature = ','.join(sorted(
                        d.get('cat_key', d.get('category', '').lower())
                        for d in degraded
                    ))
                    notification_manager.emit_event(
                        event_type='health_degraded',
                        severity=severity,
                        data={
                            'hostname': hostname,
                            'count': str(len(degraded)),
                            'title': title,
                            'reason': body,
                            '_journal_context': journal_context,
                        },
                        source='health_monitor',
                        entity='node',
                        entity_id=f'health_{cat_signature}',
                    )
                except Exception as e:
                    print(f"[ProxMenux] Health notification error: {e}")
        except Exception as e:
            print(f"[ProxMenux] Health collector error: {e}")

        time.sleep(300)  # Every 5 minutes


def _vital_signs_sampler():
    """Dedicated thread for rapid CPU, memory & temperature sampling.

    Runs independently of the 5-min health collector loop.
    - CPU usage:   sampled every 30s  (10 samples in 5 min for sustained detection)
    - Memory:      sampled every 30s  (10 samples in 5 min for sustained detection)
    - Temperature: sampled every 15s  (12 samples in 3 min for temporal logic)
    Uses time.monotonic() to avoid drift.

    Staggered intervals to avoid collision: CPU at 0, Temp at +7s, Mem at +15s.
    """
    from health_monitor import health_monitor

    # Wait 15s after startup for sensors to be ready
    time.sleep(15)

    TEMP_INTERVAL = 15   # seconds (was 10s - reduced frequency by 33%)
    CPU_INTERVAL  = 30   # seconds
    MEM_INTERVAL  = 30   # seconds (aligned with CPU for sustained-RAM detection)

    # Stagger: CPU starts immediately, Temp after 7s, Mem after 15s
    next_cpu  = time.monotonic()
    next_temp = time.monotonic() + 7
    next_mem  = time.monotonic() + 15

    print("[ProxMenux] Vital signs sampler started (CPU: 30s, Mem: 30s, Temp: 15s)")

    while True:
        try:
            now = time.monotonic()

            if now >= next_temp:
                health_monitor._sample_cpu_temperature()
                next_temp = now + TEMP_INTERVAL

            if now >= next_cpu:
                health_monitor._sample_cpu_usage()
                next_cpu = now + CPU_INTERVAL

            if now >= next_mem:
                health_monitor._sample_memory_usage()
                next_mem = now + MEM_INTERVAL

            # Sleep until the next earliest event (with 0.5s min to avoid busy-loop)
            sleep_until = min(next_temp, next_cpu, next_mem) - time.monotonic()
            time.sleep(max(sleep_until, 0.5))
        except Exception as e:
            print(f"[ProxMenux] Vital signs sampler error: {e}")
            time.sleep(10)


def get_uptime():
    """Get system uptime in a human-readable format."""
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        return str(timedelta(seconds=int(uptime_seconds)))
    except Exception as e:
        # print(f"Warning: Error getting uptime: {e}")
        pass
        return "N/A"

# Cache for expensive system info calls (pveversion, apt updates)
_system_info_cache = {
    'proxmox_version': None,
    'proxmox_version_time': 0,
    'available_updates': 0,
    'available_updates_time': 0,
}
_SYSTEM_INFO_CACHE_TTL = 21600  # 6 hours - update notifications are sent once per 24h

# Cache for pvesh cluster resources (reduces repeated API calls)
_pvesh_cache = {
    'cluster_resources_vm': None,
    'cluster_resources_vm_time': 0,
    'cluster_resources_storage': None,
    'cluster_resources_storage_time': 0,
    'storage_list': None,
    'storage_list_time': 0,
}
_PVESH_CACHE_TTL = 2  # 2 seconds - near real-time, single consistent data source for list + modal

# Cache for sensors output (temperature readings)
_sensors_cache = {
    'output': None,
    'time': 0,
}
_SENSORS_CACHE_TTL = 10  # 10 seconds - temperature changes slowly

# Cache for ipmitool sensor output (shared between fans, power supplies, power meter)
# ipmitool is slow (1-3s per call) and was called twice per /api/hardware hit.
_ipmi_cache = {
    'output': None,
    'time': 0,
    'unavailable': False,  # set True if ipmitool is missing, avoid retrying
}
_IPMI_CACHE_TTL = 10  # 10 seconds

# Cache for `lsusb -v` output. Parsed for the USB devices section and the Coral
# USB detector. USB plug/unplug events are rare enough that a 60s TTL is safe.
_lsusb_cache = {
    'simple': None,        # output of `lsusb` (short form)
    'simple_time': 0,
    'verbose': None,       # output of `lsusb -v` (detailed form with speed, driver)
    'verbose_time': 0,
    'unavailable': False,  # set True if lsusb is missing
}
_LSUSB_CACHE_TTL = 60  # 60 seconds

# Cache for hardware info (lspci, dmidecode, lsblk)
_hardware_cache = {
    'lspci': None,
    'lspci_time': 0,
    'dmidecode': None,
    'dmidecode_time': 0,
    'lsblk': None,
    'lsblk_time': 0,
}
_HARDWARE_CACHE_TTL = 300  # 5 minutes - hardware doesn't change


def get_cached_pvesh_cluster_resources_vm():
    """Get cluster VM resources with 30s cache."""
    global _pvesh_cache
    now = time.time()

    if _pvesh_cache['cluster_resources_vm'] is not None and \
       now - _pvesh_cache['cluster_resources_vm_time'] < _PVESH_CACHE_TTL:
        return _pvesh_cache['cluster_resources_vm']

    try:
        result = subprocess.run(
            ['pvesh', 'get', '/cluster/resources', '--type', 'vm', '--output-format', 'json'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            _pvesh_cache['cluster_resources_vm'] = data
            _pvesh_cache['cluster_resources_vm_time'] = now
            return data
    except Exception:
        pass
    return _pvesh_cache['cluster_resources_vm'] or []


# Sprint 14 perf pass: three backup endpoints (`/api/backups`,
# `/api/backup-storages`, `/api/vms/<id>/backups`) all enumerate storages
# via `pvesh get /storage`, each independently. Each invocation is
# ~860 ms, and the dashboard's Backups tab triggers all three in quick
# succession. A 30 s TTL is far below the rate of change for storage
# config (operators add storages once a quarter at most) and turns
# three sequential calls into one cached read.
_PVESH_STORAGE_LIST_TTL = 30


def get_cached_pvesh_storage_list():
    """Get the cluster-wide list of configured storages with 30s cache.
    Returns the raw `pvesh get /storage` JSON (a list of dicts with
    storage, type, content, etc.). Returns [] if pvesh is unavailable
    rather than raising — callers iterate the list and tolerate empty.
    """
    global _pvesh_cache
    now = time.time()

    if _pvesh_cache['storage_list'] is not None and \
       now - _pvesh_cache['storage_list_time'] < _PVESH_STORAGE_LIST_TTL:
        return _pvesh_cache['storage_list']

    try:
        result = subprocess.run(
            ['pvesh', 'get', '/storage', '--output-format', 'json'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            _pvesh_cache['storage_list'] = data
            _pvesh_cache['storage_list_time'] = now
            return data
    except Exception:
        pass
    return _pvesh_cache['storage_list'] or []


def get_cached_sensors_output():
    """Get sensors output with 10s cache."""
    global _sensors_cache
    now = time.time()
    
    if _sensors_cache['output'] is not None and \
       now - _sensors_cache['time'] < _SENSORS_CACHE_TTL:
        return _sensors_cache['output']
    
    try:
        result = subprocess.run(['sensors'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            _sensors_cache['output'] = result.stdout
            _sensors_cache['time'] = now
            return result.stdout
    except Exception:
        pass
    return _sensors_cache['output'] or ''


def get_cached_lspci():
    """Get lspci output with 5 minute cache."""
    global _hardware_cache
    now = time.time()
    
    if _hardware_cache['lspci'] is not None and \
       now - _hardware_cache['lspci_time'] < _HARDWARE_CACHE_TTL:
        return _hardware_cache['lspci']
    
    try:
        result = subprocess.run(['lspci'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            _hardware_cache['lspci'] = result.stdout
            _hardware_cache['lspci_time'] = now
            return result.stdout
    except Exception:
        pass
    return _hardware_cache['lspci'] or ''


def get_cached_lspci_vmm():
    """Get lspci -vmm output with 5 minute cache."""
    global _hardware_cache
    now = time.time()
    
    cache_key = 'lspci_vmm'
    if cache_key not in _hardware_cache:
        _hardware_cache[cache_key] = None
        _hardware_cache[cache_key + '_time'] = 0
    
    if _hardware_cache[cache_key] is not None and \
       now - _hardware_cache[cache_key + '_time'] < _HARDWARE_CACHE_TTL:
        return _hardware_cache[cache_key]
    
    try:
        result = subprocess.run(['lspci', '-vmm'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            _hardware_cache[cache_key] = result.stdout
            _hardware_cache[cache_key + '_time'] = now
            return result.stdout
    except Exception:
        pass
    return _hardware_cache[cache_key] or ''


def get_cached_lspci_k():
    """Get lspci -k output with 5 minute cache."""
    global _hardware_cache
    now = time.time()

    cache_key = 'lspci_k'
    if cache_key not in _hardware_cache:
        _hardware_cache[cache_key] = None
        _hardware_cache[cache_key + '_time'] = 0

    if _hardware_cache[cache_key] is not None and \
       now - _hardware_cache[cache_key + '_time'] < _HARDWARE_CACHE_TTL:
        return _hardware_cache[cache_key]

    try:
        result = subprocess.run(['lspci', '-k'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            _hardware_cache[cache_key] = result.stdout
            _hardware_cache[cache_key + '_time'] = now
            return result.stdout
    except Exception:
        pass
    return _hardware_cache[cache_key] or ''


# ============================================================================
# USB device enumeration (used by both USB section and Coral USB detector)
# ============================================================================

def get_cached_lsusb():
    """Get plain `lsusb` output with 60s cache. Lightweight; just IDs + names."""
    global _lsusb_cache
    now = time.time()

    if _lsusb_cache['unavailable']:
        return ''

    if _lsusb_cache['simple'] is not None and \
       now - _lsusb_cache['simple_time'] < _LSUSB_CACHE_TTL:
        return _lsusb_cache['simple']

    try:
        result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            _lsusb_cache['simple'] = result.stdout
            _lsusb_cache['simple_time'] = now
            return result.stdout
    except FileNotFoundError:
        _lsusb_cache['unavailable'] = True
        return ''
    except Exception:
        pass
    return _lsusb_cache['simple'] or ''


def _usb_speed_label(mbps):
    """Map USB sysfs speed (Mbps) to a human-readable label."""
    try:
        m = int(mbps)
    except (ValueError, TypeError):
        return ''
    # These are the standard USB generation speeds.
    if m >= 20000:
        return 'USB 3.2 Gen 2x2'
    if m >= 10000:
        return 'USB 3.1 Gen 2'
    if m >= 5000:
        return 'USB 3.0'
    if m >= 480:
        return 'USB 2.0'
    if m >= 12:
        return 'USB 1.1'
    return 'USB 1.0'


_USB_CLASS_LABELS = {
    '00': 'Device Specific',
    '01': 'Audio',
    '02': 'Communications',
    '03': 'HID',
    '05': 'Physical',
    '06': 'Imaging',
    '07': 'Printer',
    '08': 'Mass Storage',
    '09': 'Hub',
    '0a': 'CDC Data',
    '0b': 'Smart Card',
    '0d': 'Content Security',
    '0e': 'Video',
    '0f': 'Personal Healthcare',
    '10': 'Audio/Video',
    '11': 'Billboard',
    'dc': 'Diagnostic',
    'e0': 'Wireless Controller',
    'ef': 'Miscellaneous',
    'fe': 'Application Specific',
    'ff': 'Vendor Specific',
}

# USB vendor IDs of known UPS manufacturers. UPSs communicate via HID (USB
# class 0x03) using the "Power Device" usage page, so raw class detection
# labels them as generic "HID" — which is technically correct but useless
# for the user. When the device class is HID and the vendor matches this
# set, we relabel as "UPS".
_USB_UPS_VENDORS = {
    '0463',  # MGE UPS Systems / Eaton (Ellipse, Pulsar, 5P, 9PX, Protection Station)
    '051d',  # American Power Conversion (APC) / Schneider (Back-UPS, Smart-UPS)
    '0764',  # CyberPower Systems
    '0d9f',  # PowerCom
    '06da',  # Phoenixtec Power / Liebert (some models)
    '09ae',  # Tripp Lite
    '047c',  # Dell (select UPS models)
    '075d',  # Salicru
    '10af',  # Liebert / Vertiv
    '0665',  # Cypress Semi (OEM silicon in several UPS brands)
}


def _read_sysfs(path, default=''):
    """Read and trim a sysfs attribute file. Returns default on error."""
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except Exception:
        return default


def _interface_class_from_usb_device(dev_path):
    """When bDeviceClass is 00, the device delegates classification to the
    first interface. Read bInterfaceClass from <dev>/<dev>:1.0/bInterfaceClass.
    """
    try:
        # Sysfs names interfaces as <busnum>-<portpath>:1.0 etc.
        base = os.path.basename(dev_path)
        iface_file = os.path.join(dev_path, f'{base}:1.0', 'bInterfaceClass')
        return _read_sysfs(iface_file, '')
    except Exception:
        return ''


def _get_usb_driver(dev_path):
    """Best-effort bound driver name for a USB device.

    USB drivers are usually bound at the *interface* level (:1.0, :1.1...),
    not the device level. We peek at the first interface.
    """
    try:
        base = os.path.basename(dev_path)
        for ifnum in ('1.0', '1.1', '1.2'):
            drv_link = os.path.join(dev_path, f'{base}:{ifnum}', 'driver')
            if os.path.islink(drv_link):
                return os.path.basename(os.readlink(drv_link))
    except Exception:
        pass
    return ''


def get_usb_devices():
    """Enumerate physically connected USB peripherals.

    Skips virtual root hubs (vendor 1d6b = Linux Foundation). Each entry is
    a dict with fields suited to the "USB Devices" section in the hardware UI.
    """
    devices = []
    usb_root = '/sys/bus/usb/devices'
    if not os.path.isdir(usb_root):
        return devices

    # Human-readable vendor/product names live in `lsusb` simple output.
    # Build a quick lookup by "bus:dev".
    name_map = {}
    try:
        for line in get_cached_lsusb().split('\n'):
            m = re.match(
                r'Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-f]{4}):([0-9a-f]{4})\s+(.*)',
                line, re.IGNORECASE)
            if m:
                bus, dev, _vid, _pid, rest = m.groups()
                name_map[f'{int(bus):03d}:{int(dev):03d}'] = rest.strip()
    except Exception:
        pass

    try:
        for entry in sorted(os.listdir(usb_root)):
            dev_path = os.path.join(usb_root, entry)
            # Interface nodes look like "1-0:1.0" — skip, we only want devices.
            if ':' in entry:
                continue

            vendor_id = _read_sysfs(os.path.join(dev_path, 'idVendor'))
            product_id = _read_sysfs(os.path.join(dev_path, 'idProduct'))
            if not vendor_id or not product_id:
                continue

            # Skip virtual root hubs (Linux Foundation hubs).
            if vendor_id.lower() == '1d6b':
                continue

            busnum = _read_sysfs(os.path.join(dev_path, 'busnum'), '0')
            devnum = _read_sysfs(os.path.join(dev_path, 'devnum'), '0')
            bus_device = f'{int(busnum):03d}:{int(devnum):03d}'

            manufacturer = _read_sysfs(os.path.join(dev_path, 'manufacturer'))
            product_name = _read_sysfs(os.path.join(dev_path, 'product'))

            # Fall back to lsusb-derived name when sysfs strings are absent.
            lsusb_name = name_map.get(bus_device, '')
            display_name = product_name or lsusb_name or f'USB device {vendor_id}:{product_id}'
            display_vendor = manufacturer or (lsusb_name.split()[0] if lsusb_name else '')

            speed_raw = _read_sysfs(os.path.join(dev_path, 'speed'))
            speed_label = _usb_speed_label(speed_raw)

            device_class = _read_sysfs(os.path.join(dev_path, 'bDeviceClass'), '00').lower()
            if device_class == '00':
                device_class = _interface_class_from_usb_device(dev_path).lower()
            class_label = _USB_CLASS_LABELS.get(device_class, 'Unknown')

            # Refine HID → UPS for known UPS vendors. USB UPSs advertise class
            # HID with a Power Device usage page; labeling them "HID" looks wrong.
            if device_class == '03' and vendor_id.lower() in _USB_UPS_VENDORS:
                class_label = 'UPS'

            serial = _read_sysfs(os.path.join(dev_path, 'serial'))
            driver = _get_usb_driver(dev_path)

            devices.append({
                'bus_device': bus_device,
                'vendor_id': vendor_id.lower(),
                'product_id': product_id.lower(),
                'vendor': display_vendor,
                'name': display_name,
                'class_code': device_class,
                'class_label': class_label,
                'speed_mbps': int(speed_raw) if speed_raw.isdigit() else 0,
                'speed_label': speed_label,
                'serial': serial,
                'driver': driver,
            })
    except Exception:
        # Never break the hardware payload just because USB enumeration fails.
        pass

    return devices


# ============================================================================
# Coral TPU (Edge TPU) detection — M.2 / PCIe + USB
# Google Edge TPU USB IDs:
#   1a6e:089a  Global Unichip Corp.  (unprogrammed — before runtime loads fw)
#   18d1:9302  Google Inc.           (programmed   — after runtime talks to it)
# M.2 / Mini PCIe Coral uses vendor 0x1ac1 (Global Unichip Corp.).
# ============================================================================

CORAL_USB_IDS = {('1a6e', '089a'), ('18d1', '9302')}
CORAL_PCI_VENDOR = '0x1ac1'


def _coral_kernel_modules_loaded():
    """Returns (gasket_loaded, apex_loaded) based on /proc/modules."""
    gasket = apex = False
    try:
        with open('/proc/modules', 'r') as f:
            for line in f:
                name = line.split(' ', 1)[0]
                if name == 'gasket':
                    gasket = True
                elif name == 'apex':
                    apex = True
    except Exception:
        pass
    return gasket, apex


def _coral_device_nodes():
    """Find /dev/apex_* device nodes (PCIe Coral creates these)."""
    try:
        from glob import glob
        return sorted(glob('/dev/apex_*'))
    except Exception:
        return []


def _coral_edgetpu_runtime_version():
    """Return the installed libedgetpu1 package version, or empty string.

    Checks both -std and -max variants (max enables full clock; std is default).
    """
    for pkg in ('libedgetpu1-std', 'libedgetpu1-max'):
        try:
            result = subprocess.run(
                ['dpkg-query', '-W', '-f=${Version}', pkg],
                capture_output=True, text=True, timeout=3)
            if result.returncode == 0 and result.stdout.strip():
                return f'{pkg} {result.stdout.strip()}'
        except Exception:
            continue
    return ''


def _coral_pcie_name_from_lspci(slot):
    """Best-effort human name for a PCIe Coral from cached lspci output."""
    try:
        # Match either full slot (0000:0c:00.0) or short form (0c:00.0).
        short = slot.split(':', 1)[1] if slot.count(':') >= 2 else slot
        for line in get_cached_lspci().split('\n'):
            if line.startswith(short):
                # Format: "0c:00.0 <class>: <vendor> <device>"
                parts = line.split(':', 2)
                if len(parts) >= 3:
                    return parts[2].strip()
    except Exception:
        pass
    return 'Coral Edge TPU'


def _coral_pci_form_factor(dev_path):
    """Heuristic form factor for a Coral PCIe/M.2 device.

    Without a perfectly reliable sysfs indicator we key off the PCIe link
    width: Coral M.2 modules are always x1. This keeps the label simple and
    accurate for the common cases without over-promising.
    """
    try:
        width = _read_sysfs(os.path.join(dev_path, 'current_link_width'), '')
        if width == '1':
            return 'M.2 / Mini PCIe (x1)'
    except Exception:
        pass
    return 'PCIe'


def _coral_pci_speed(dev_path):
    try:
        speed = _read_sysfs(os.path.join(dev_path, 'current_link_speed'), '')
        width = _read_sysfs(os.path.join(dev_path, 'current_link_width'), '')
        if speed and width:
            return f'PCIe {speed} x{width}'
    except Exception:
        pass
    return ''


def _coral_parse_temp_value(raw):
    """Interpret a sysfs temperature reading as float °C.

    The apex driver reports millidegrees (e.g. 54050 → 54.0 °C). Hwmon nodes
    also use millidegrees. Plain integers like "42" are treated as °C.
    Returns None on unparsable / empty input.
    """
    if not raw:
        return None
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return None
    if abs(val) >= 1000:
        return round(val / 1000.0, 1)
    return float(val)


def _coral_pcie_thermal(pci_dev_path):
    """Read full thermal picture for a PCIe Coral via the apex driver's sysfs.

    The gasket/apex driver exposes (at least on current feranick / kernel 6.12):
      temp              current die temperature (millidegrees)
      trip_point{0..2}_temp  configured alarm thresholds (millidegrees)
      hw_temp_warn{1,2}      hardware-signalled warning thresholds
      hw_temp_warn{1,2}_en   whether those hw warnings are enabled

    Returns a dict with the fields our payload needs, or an empty dict when
    no apex_N entry matches this PCI slot (e.g. drivers not loaded, or a USB
    Coral where this whole sysfs tree doesn't exist).
    """
    result = {'temperature': None, 'temperature_trips': None, 'thermal_warnings': None}
    try:
        apex_root = '/sys/class/apex'
        if not os.path.isdir(apex_root):
            return result

        target_pci = os.path.basename(pci_dev_path)
        for apex_name in os.listdir(apex_root):
            apex_path = os.path.join(apex_root, apex_name)
            device_link = os.path.join(apex_path, 'device')
            if not os.path.islink(device_link):
                continue
            resolved = os.path.realpath(device_link)
            if os.path.basename(resolved) != target_pci:
                continue

            # ── Current temperature (prefer direct attr, fall back to hwmon)
            candidates = [
                os.path.join(apex_path, 'temp'),
                os.path.join(apex_path, 'device', 'temp'),
            ]
            hwmon_dir = os.path.join(apex_path, 'device', 'hwmon')
            if os.path.isdir(hwmon_dir):
                try:
                    for hwmon in os.listdir(hwmon_dir):
                        candidates.append(os.path.join(hwmon_dir, hwmon, 'temp1_input'))
                except Exception:
                    pass

            for c in candidates:
                temp = _coral_parse_temp_value(_read_sysfs(c, ''))
                if temp is not None:
                    result['temperature'] = temp
                    break

            # ── Trip points (alarm thresholds). Typically 3 ascending values:
            # warn / throttle / critical. Kept ordered as-reported by the driver.
            trips = []
            for i in range(3):
                t = _coral_parse_temp_value(
                    _read_sysfs(os.path.join(apex_path, f'trip_point{i}_temp'), ''))
                if t is not None:
                    trips.append(t)
            if trips:
                result['temperature_trips'] = trips

            # ── Hardware warnings (threshold + enabled flag). Surface only the
            # pairs that are actually configured so the UI can show a badge
            # when a warning is enabled.
            warnings = []
            for i in (1, 2):
                threshold = _coral_parse_temp_value(
                    _read_sysfs(os.path.join(apex_path, f'hw_temp_warn{i}'), ''))
                enabled_raw = _read_sysfs(
                    os.path.join(apex_path, f'hw_temp_warn{i}_en'), '')
                enabled = enabled_raw.strip() in ('1', 'true', 'yes')
                if threshold is not None or enabled_raw:
                    warnings.append({
                        'name': f'hw_temp_warn{i}',
                        'threshold_c': threshold,
                        'enabled': enabled,
                    })
            if warnings:
                result['thermal_warnings'] = warnings

            return result
    except Exception:
        pass
    return result


def get_coral_info():
    """Detect Coral TPU accelerators (PCIe/M.2 + USB).

    Returns a list of dicts — empty if no Coral is present. The payload is
    intentionally minimal: Coral exposes no temperature/utilization/power
    counters, so the UI only needs identity + driver/runtime state.
    """
    coral_devices = []
    gasket_loaded, apex_loaded = _coral_kernel_modules_loaded()
    device_nodes = _coral_device_nodes()
    runtime = _coral_edgetpu_runtime_version()

    # ── PCIe / M.2 Coral ────────────────────────────────────────────────
    try:
        for dev_path in sorted(glob.glob('/sys/bus/pci/devices/*')):
            vendor = _read_sysfs(os.path.join(dev_path, 'vendor'))
            if vendor.lower() != CORAL_PCI_VENDOR:
                continue

            slot = os.path.basename(dev_path)
            device_id = _read_sysfs(os.path.join(dev_path, 'device'), '').replace('0x', '')
            vendor_id = vendor.replace('0x', '')

            driver_name = ''
            drv_link = os.path.join(dev_path, 'driver')
            if os.path.islink(drv_link):
                driver_name = os.path.basename(os.readlink(drv_link))

            # "drivers_ready" for PCIe = apex bound and kernel modules present
            drivers_ready = (driver_name == 'apex') and apex_loaded

            thermal = _coral_pcie_thermal(dev_path)

            coral_devices.append({
                'type': 'pcie',
                'name': _coral_pcie_name_from_lspci(slot),
                'vendor': 'Global Unichip Corp.',
                'vendor_id': vendor_id,
                'device_id': device_id,
                'slot': slot,
                'form_factor': _coral_pci_form_factor(dev_path),
                'interface_speed': _coral_pci_speed(dev_path),
                'kernel_driver': driver_name or None,
                'kernel_modules': {
                    'gasket': gasket_loaded,
                    'apex': apex_loaded,
                },
                'device_nodes': device_nodes,
                'edgetpu_runtime': runtime,
                'drivers_ready': drivers_ready,
                # PCIe/M.2 Coral thermal data from the apex driver (same source
                # Frigate reads). All null when drivers aren't loaded.
                'temperature': thermal.get('temperature'),
                'temperature_trips': thermal.get('temperature_trips'),
                'thermal_warnings': thermal.get('thermal_warnings'),
            })
    except Exception:
        pass

    # ── USB Coral Accelerator ───────────────────────────────────────────
    try:
        for line in get_cached_lsusb().split('\n'):
            m = re.match(
                r'Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-f]{4}):([0-9a-f]{4})\s+(.*)',
                line, re.IGNORECASE)
            if not m:
                continue
            bus, dev, vid, pid, rest = m.groups()
            vid = vid.lower()
            pid = pid.lower()
            if (vid, pid) not in CORAL_USB_IDS:
                continue

            programmed = (vid == '18d1')  # switched-state vendor/product after fw load

            # Best-effort sysfs path for USB speed.
            bus_device = f'{int(bus):03d}:{int(dev):03d}'
            usb_speed_label = ''
            usb_driver = ''
            try:
                for usb_dev_dir in glob.glob('/sys/bus/usb/devices/*'):
                    base = os.path.basename(usb_dev_dir)
                    if ':' in base:
                        continue
                    b = _read_sysfs(os.path.join(usb_dev_dir, 'busnum'), '0')
                    d = _read_sysfs(os.path.join(usb_dev_dir, 'devnum'), '0')
                    if f'{int(b):03d}:{int(d):03d}' == bus_device:
                        usb_speed_label = _usb_speed_label(
                            _read_sysfs(os.path.join(usb_dev_dir, 'speed'), ''))
                        usb_driver = _get_usb_driver(usb_dev_dir)
                        break
            except Exception:
                pass

            # "drivers_ready" for USB = edgetpu runtime is installed.
            # The USB Accelerator does not use a kernel driver; it speaks libusb
            # straight to userspace via the libedgetpu1 library.
            drivers_ready = bool(runtime)

            coral_devices.append({
                'type': 'usb',
                'name': 'Coral USB Accelerator',
                'vendor': rest.strip() or 'Google Inc.',
                'vendor_id': vid,
                'device_id': pid,
                'bus_device': bus_device,
                'form_factor': 'USB Accelerator',
                'interface_speed': usb_speed_label,
                'programmed': programmed,
                'usb_driver': usb_driver or None,
                'kernel_driver': None,   # USB Coral uses libusb in userspace
                'kernel_modules': {'gasket': gasket_loaded, 'apex': apex_loaded},
                'device_nodes': [],       # No /dev/apex_* for USB
                'edgetpu_runtime': runtime,
                'drivers_ready': drivers_ready,
                # USB Coral does not expose temperature, trip points or hardware
                # warnings via sysfs; those are only readable from within the Edge
                # TPU runtime through libusb (Frigate and similar get them there).
                'temperature': None,
                'temperature_trips': None,
                'thermal_warnings': None,
            })
    except Exception:
        pass

    return coral_devices


def get_proxmox_version():
    """Get Proxmox version if available. Cached for 6 hours."""
    global _system_info_cache
    
    now = time.time()
    if _system_info_cache['proxmox_version'] is not None and \
       now - _system_info_cache['proxmox_version_time'] < _SYSTEM_INFO_CACHE_TTL:
        return _system_info_cache['proxmox_version']
    
    proxmox_version = None
    try:
        result = subprocess.run(['pveversion'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse output like "pve-manager/9.0.6/..."
            version_line = result.stdout.strip().split('\n')[0]
            if '/' in version_line:
                proxmox_version = version_line.split('/')[1]
    except FileNotFoundError:
        pass
    except Exception as e:
        pass
    
    _system_info_cache['proxmox_version'] = proxmox_version
    _system_info_cache['proxmox_version_time'] = now
    return proxmox_version

def get_available_updates():
    """Get the number of available package updates. Cached for 6 hours."""
    global _system_info_cache
    
    now = time.time()
    if _system_info_cache['available_updates_time'] > 0 and \
       now - _system_info_cache['available_updates_time'] < _SYSTEM_INFO_CACHE_TTL:
        return _system_info_cache['available_updates']
    
    available_updates = 0
    try:
        # Use apt list --upgradable to count available updates
        result = subprocess.run(['apt', 'list', '--upgradable'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # Count lines minus the header line
            lines = result.stdout.strip().split('\n')
            available_updates = max(0, len(lines) - 1)
    except FileNotFoundError:
        pass
    except Exception as e:
        pass
    
    _system_info_cache['available_updates'] = available_updates
    _system_info_cache['available_updates_time'] = now
    return available_updates

# AGREGANDO FUNCIÓN PARA PARSEAR PROCESOS DE INTEL_GPU_TOP (SIN -J)
def get_intel_gpu_processes_from_text():
    """Parse processes from intel_gpu_top text output (more reliable than JSON)"""
    try:
        # print(f"[v0] Executing intel_gpu_top (text mode) to capture processes...", flush=True)
        pass
        try:
            process = subprocess.Popen(
                ['intel_gpu_top'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        except FileNotFoundError:
            # intel_gpu_top no está instalado, retornar lista vacía
            return []
        
        # Wait 2 seconds for intel_gpu_top to collect data
        time.sleep(2)
        
        # Terminate and get output
        process.terminate()
        try:
            stdout, _ = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate()
        
        processes = []
        lines = stdout.split('\n')
        
        # Find the process table header
        header_found = False
        for i, line in enumerate(lines):
            if 'PID' in line and 'NAME' in line and 'Render/3D' in line:
                header_found = True
                # Process lines after header
                for proc_line in lines[i+1:]:
                    proc_line = proc_line.strip()
                    if not proc_line or proc_line.startswith('intel-gpu-top'):
                        continue
                    
                    # Parse process line
                    # Format: PID MEM RSS Render/3D Blitter Video VideoEnhance NAME
                    parts = proc_line.split()
                    if len(parts) >= 8:
                        try:
                            pid = parts[0]
                            mem_str = parts[1]  # e.g., "177568K"
                            rss_str = parts[2]  # e.g., "116500K"
                            
                            # Convert memory values (remove 'K' and convert to bytes)
                            mem_total = int(mem_str.replace('K', '')) * 1024 if 'K' in mem_str else 0
                            mem_resident = int(rss_str.replace('K', '')) * 1024 if 'K' in rss_str else 0
                            
                            # Find the process name (last element)
                            name = parts[-1]
                            
                            # Parse engine utilization from the bars
                            # The bars are between the memory and name
                            # We'll estimate utilization based on bar characters
                            engines = {}
                            engine_names = ['Render/3D', 'Blitter', 'Video', 'VideoEnhance']
                            bar_section = " ".join(parts[3:-1]) # Extract the bar section dynamically

                            bar_sections = bar_section.split('||')
                            
                            for idx, engine_name in enumerate(engine_names):
                                if idx < len(bar_sections):
                                    bar_str = bar_sections[idx]
                                    # Count filled bar characters
                                    filled_chars = bar_str.count('█') + bar_str.count('▎') * 0.25
                                    # Estimate percentage (assuming ~50 chars = 100%)
                                    utilization = min(100.0, (filled_chars / 50.0) * 100.0)
                                    if utilization > 0:
                                        engines[engine_name] = f"{utilization:.1f}%"
                                        
                                    if engine_name == 'Render/3D' and utilization > 0:
                                        engine_names[0] = f"Render/3D ({utilization:.1f}%)"
                                    elif engine_name == 'Blitter' and utilization > 0:
                                        engine_names[1] = f"Blitter ({utilization:.1f}%)"
                                    elif engine_name == 'Video' and utilization > 0:
                                        engine_names[2] = f"Video ({utilization:.1f}%)"
                                    elif engine_name == 'VideoEnhance' and utilization > 0:
                                        engine_names[3] = f"VideoEnhance ({utilization:.1f}%)"

                            if engines:  # Only add if there's some GPU activity
                                process_info = {
                                    'name': name,
                                    'pid': pid,
                                    'memory': {
                                        'total': mem_total,
                                        'shared': 0,  # Not available in text output
                                        'resident': mem_resident
                                    },
                                    'engines': engines
                                }
                                processes.append(process_info)

                        except (ValueError, IndexError) as e:
                            # print(f"[v0] Error parsing process line: {e}")
                            pass
                            continue
                break
        
        if not header_found:
            # print(f"[v0] No process table found in intel_gpu_top output")
            pass
        
        return processes
    except Exception as e:
        # print(f"[v0] Error getting processes from intel_gpu_top text: {e}")
        pass
        import traceback
        traceback.print_exc()
        return []

def extract_vmid_from_interface(interface_name):
    """Extract VMID from virtual interface name (veth100i0 -> 100, tap105i0 -> 105)"""
    try:
        match = re.match(r'(veth|tap)(\d+)i\d+', interface_name)
        if match:
            vmid = int(match.group(2))
            interface_type = 'lxc' if match.group(1) == 'veth' else 'vm'
            return vmid, interface_type
        return None, None
    except Exception as e:
        # print(f"[v0] Error extracting VMID from {interface_name}: {e}")
        pass
        return None, None

def get_vm_lxc_names():
    """Get VM and LXC names from Proxmox API (only from local node)"""
    vm_lxc_map = {}
    
    try:
        # local_node = socket.gethostname()
        local_node = get_proxmox_node_name()
        
        resources = get_cached_pvesh_cluster_resources_vm()
        if resources:
            for resource in resources:
                node = resource.get('node', '')
                if node != local_node:
                    continue
                
                vmid = resource.get('vmid')
                name = resource.get('name', f'VM-{vmid}')
                vm_type = resource.get('type', 'unknown')  # 'qemu' or 'lxc'
                status = resource.get('status', 'unknown')
                
                if vmid:
                    vm_lxc_map[vmid] = {
                        'name': name,
                        'type': 'lxc' if vm_type == 'lxc' else 'vm',
                        'status': status
                    }

        else:
            # print(f"[v0] pvesh command failed: {result.stderr}")
            pass
    except FileNotFoundError:
        # print("[v0] pvesh command not found - Proxmox not installed")
        pass
    except Exception as e:
        # print(f"[v0] Error getting VM/LXC names: {e}")
        pass
    
    return vm_lxc_map

@app.route('/')
def serve_dashboard():
    """Serve the main dashboard page from Next.js build"""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            # Fallback: detect from script location
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                # We're in usr/bin/, go up 2 levels to AppImage root
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                # Fallback: assume we're in the root
                appimage_root = os.path.dirname(base_dir)
        
        # print(f"[v0] Detected AppImage root: {appimage_root}")
        pass
        
        index_path = os.path.join(appimage_root, 'web', 'index.html')
        abs_path = os.path.abspath(index_path)
        
        # print(f"[v0] Looking for index.html at: {abs_path}")
        pass
        
        if os.path.exists(abs_path):
            # print(f"[v0] ✅ Found index.html, serving from: {abs_path}")
            pass
            return send_file(abs_path)
        
        # If not found, show detailed error


        web_dir = os.path.join(appimage_root, 'web')
        if os.path.exists(web_dir):
            # print(f"[v0] Contents of {web_dir}:")
            pass
            for item in os.listdir(web_dir):
                # print(f"[v0]   - {item}")
                pass
        else:
            # print(f"[v0] Web directory does not exist: {web_dir}")
            pass
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head><title>ProxMenux Monitor - Build Error</title></head>
        <body style="font-family: Arial; padding: 2rem; background: #0a0a0a; color: #fff;">
            <h1>🚨 ProxMenux Monitor - Build Error</h1>
            <p>Next.js application not found. The AppImage may not have been built correctly.</p>
            <p>Expected path: {abs_path}</p>
            <p>APPDIR: {appimage_root}</p>
            <p>API endpoints are still available:</p>
            <ul>
                <li><a href="/api/system" style="color: #4f46e5;">/api/system</a></li>
                <li><a href="/api/system-info" style="color: #4f46e5;">/api/system-info</a></li>
                <li><a href="/api/storage" style="color: #4f46e5;">/api/storage</a></li>
                <li><a href="/api/network" style="color: #4f46e5;">/api/network</a></li>
                <li><a href="/api/vms" style="color: #4f46e5;">/api/vms</a></li>
                <li><a href="/api/health" style="color: #4f46e5;">/api/health</a></li>
            </ul>
        </body>
        </html>
        ''', 500
        
    except Exception as e:
        # print(f"Error serving dashboard: {e}")
        pass
        return jsonify({'error': f'Dashboard not available: {str(e)}'}), 500

@app.route('/manifest.json')
def serve_manifest():
    """Serve PWA manifest"""
    try:
        manifest_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'web', 'public', 'manifest.json'),
            os.path.join(os.path.dirname(__file__), '..', 'public', 'manifest.json')
        ]
        
        for manifest_path in manifest_paths:
            if os.path.exists(manifest_path):
                return send_file(manifest_path)
        
        # Return default manifest if not found
        return jsonify({
            "name": "ProxMenux Monitor",
            "short_name": "ProxMenux",
            "description": "Proxmox System Monitoring Dashboard",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0a0a0a",
            "theme_color": "#4f46e5",
            "icons": [
                {
                    "src": "/images/proxmenux-logo.png",
                    "sizes": "256x256",
                    "type": "image/png"
                }
            ]
        })
    except Exception as e:
        # print(f"Error serving manifest: {e}")
        pass
        return jsonify({}), 404

@app.route('/sw.js')
def serve_sw():
    """Serve service worker"""
    return '''
    const CACHE_NAME = 'proxmenux-v1';
    const urlsToCache = [
        '/',
        '/api/system',
        '/api/storage',
        '/api/network',
        '/api/health'
    ];

    self.addEventListener('install', event => {
        event.waitUntil(
            caches.open(CACHE_NAME)
                .then(cache => cache.addAll(urlsToCache))
        );
    });

    self.addEventListener('fetch', event => {
        event.respondWith(
            caches.match(event.request)
                .then(response => response || fetch(event.request))
        );
    });
    ''', 200, {'Content-Type': 'application/javascript'}

@app.route('/_next/<path:filename>')
def serve_next_static(filename):
    """Serve Next.js static files"""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        static_dir = os.path.join(appimage_root, 'web', '_next')
        file_path = os.path.join(static_dir, filename)
        
        if os.path.exists(file_path):
            return send_file(file_path)
        
        # print(f"[v0] ❌ Next.js static file not found: {file_path}")
        pass
        return '', 404
    except Exception as e:
        # print(f"Error serving Next.js static file {filename}: {e}")
        pass
        return '', 404

@app.route('/<path:filename>')
def serve_static_files(filename):
    """Serve static files (icons, etc.)"""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        web_dir = os.path.join(appimage_root, 'web')
        file_path = os.path.join(web_dir, filename)
        
        if os.path.exists(file_path):
            return send_from_directory(web_dir, filename)
        
        return '', 404
    except Exception as e:
        # print(f"Error serving static file {filename}: {e}")
        pass
        return '', 404

@app.route('/images/<path:filename>')
def serve_images(filename):
    """Serve image files"""
    try:
        appimage_root = os.environ.get('APPDIR')
        if not appimage_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if base_dir.endswith('usr/bin'):
                appimage_root = os.path.dirname(os.path.dirname(base_dir))
            else:
                appimage_root = os.path.dirname(base_dir)
        
        image_dir = os.path.join(appimage_root, 'web', 'images')
        file_path = os.path.join(image_dir, filename)
        abs_path = os.path.abspath(file_path)
        
        # print(f"[v0] Looking for image: {filename} at {abs_path}")
        pass
        
        if os.path.exists(abs_path):
            # print(f"[v0] ✅ Serving image from: {abs_path}")
            pass
            return send_from_directory(image_dir, filename)
        
        # print(f"[v0] ❌ Image not found: {abs_path}")
        pass
        return '', 404
    except Exception as e:
        # print(f"Error serving image {filename}: {e}")
        pass
        return '', 404

# Moved helper functions for system info up
# def get_system_info(): ... (moved up)

def get_disk_connection_type(disk_name):
    """Detect how a disk is connected: usb, sata, nvme, sas, or unknown.
    
    Uses /sys/block/<disk>/device symlink to resolve the bus path.
    Examples:
      /sys/.../usb3/...   -> 'usb'
      /sys/.../ata2/...   -> 'sata'
      nvme0n1             -> 'nvme'
      /sys/.../host0/...  -> 'sas' (SAS/SCSI)
    """
    try:
        if disk_name.startswith('nvme'):
            return 'nvme'
        
        device_path = f'/sys/block/{disk_name}/device'
        if os.path.exists(device_path):
            real_path = os.path.realpath(device_path)
            if '/usb' in real_path:
                return 'usb'
            if '/ata' in real_path:
                return 'sata'
            if '/sas' in real_path:
                return 'sas'
        
        # Fallback: check removable flag
        removable_path = f'/sys/block/{disk_name}/removable'
        if os.path.exists(removable_path):
            with open(removable_path) as f:
                if f.read().strip() == '1':
                    return 'usb'
        
        return 'internal'
    except Exception:
        return 'unknown'


def is_disk_removable(disk_name):
    """Check if a disk is removable (USB sticks, external drives, etc.)."""
    try:
        removable_path = f'/sys/block/{disk_name}/removable'
        if os.path.exists(removable_path):
            with open(removable_path) as f:
                return f.read().strip() == '1'
        return False
    except Exception:
        return False


def _is_system_mount(mountpoint):
    """Check if mountpoint is a critical system path (matching bash scripts logic)."""
    system_mounts = ('/', '/boot', '/boot/efi', '/efi', '/usr', '/var', '/etc', 
                     '/lib', '/lib64', '/run', '/proc', '/sys')
    if mountpoint in system_mounts:
        return True
    # Also check if it's under these paths
    for prefix in ('/usr/', '/var/', '/lib/', '/lib64/'):
        if mountpoint.startswith(prefix):
            return True
    return False


def _get_zfs_root_pool():
    """Get the ZFS pool containing the root filesystem, if any (matches bash _get_zfs_root_pool)."""
    try:
        result = subprocess.run(['df', '/'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                root_fs = lines[1].split()[0]
                # A ZFS dataset looks like "rpool/ROOT/pve-1" — not /dev/
                if not root_fs.startswith('/dev/') and '/' in root_fs:
                    return root_fs.split('/')[0]
    except Exception:
        pass
    return None


def _resolve_zfs_entry(entry):
    """
    Resolve a ZFS device entry to a base disk name.
    Handles: /dev/paths, by-id names, short kernel names (matches bash _resolve_zfs_entry).
    """
    path = None
    
    try:
        if entry.startswith('/dev/'):
            path = os.path.realpath(entry)
        elif os.path.exists(f'/dev/disk/by-id/{entry}'):
            path = os.path.realpath(f'/dev/disk/by-id/{entry}')
        elif os.path.exists(f'/dev/{entry}'):
            path = os.path.realpath(f'/dev/{entry}')
        
        if path:
            # Get parent disk (base disk without partition number)
            result = subprocess.run(
                ['lsblk', '-no', 'PKNAME', path],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            # If no parent, path is the base disk itself
            return os.path.basename(path)
    except Exception:
        pass
    return None


def get_system_disks():
    """
    Detect which physical disks are used by the system (Proxmox).
    
    Returns a dict mapping disk names to their system usage info:
    {
        'sda': {'is_system': True, 'usage': ['root', 'boot']},
        'nvme0n1': {'is_system': True, 'usage': ['zfs:rpool']},
    }
    
    Detects (matching logic from disk-passthrough.sh, format-disk.sh, disk_host.sh):
    - Root filesystem (/) and critical system mounts (/boot, /usr, /var, etc.)
    - Boot partition (/boot, /boot/efi)
    - Active swap partitions
    - ZFS pools (especially root pool - these disks are critical)
    - LVM physical volumes (especially 'pve' volume group)
    - RAID members (mdadm)
    - Disks with Proxmox partition labels
    """
    system_disks = {}
    
    def add_usage(disk_name, usage_type):
        """Helper to add a usage type to a disk."""
        if not disk_name:
            return
        # Normalize disk name (strip partition numbers to get base disk)
        base_disk = disk_name
        if disk_name and disk_name[-1].isdigit():
            if 'nvme' in disk_name or 'mmcblk' in disk_name:
                # NVMe/eMMC: nvme0n1p1 -> nvme0n1
                if 'p' in disk_name:
                    base_disk = disk_name.rsplit('p', 1)[0]
            else:
                # SATA/SAS: sda1 -> sda
                base_disk = disk_name.rstrip('0123456789')
        
        if base_disk not in system_disks:
            system_disks[base_disk] = {'is_system': True, 'usage': []}
        if usage_type not in system_disks[base_disk]['usage']:
            system_disks[base_disk]['usage'].append(usage_type)
    
    # Get ZFS root pool first (critical - these disks should never be touched)
    zfs_root_pool = _get_zfs_root_pool()
    
    try:
        # 1. Check mounted filesystems for system-critical mounts
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                device, mountpoint = parts[0], parts[1]
                
                # Skip non-block devices
                if not device.startswith('/dev/'):
                    continue
                
                disk_name = device.replace('/dev/', '').replace('mapper/', '')
                
                # Identify system mountpoints (expanded from bash _is_system_mount)
                if _is_system_mount(mountpoint):
                    if mountpoint == '/':
                        add_usage(disk_name, 'root')
                    elif mountpoint.startswith('/boot'):
                        add_usage(disk_name, 'boot')
                    else:
                        add_usage(disk_name, 'system')
    except Exception:
        pass
    
    try:
        # 2. Check active swap partitions
        result = subprocess.run(
            ['swapon', '--noheadings', '--raw', '--show=NAME'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                device = line.strip()
                if device.startswith('/dev/'):
                    disk_name = device.replace('/dev/', '')
                    add_usage(disk_name, 'swap')
    except Exception:
        # Fallback to /proc/swaps
        try:
            with open('/proc/swaps', 'r') as f:
                lines = f.readlines()[1:]  # Skip header
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 1:
                        device = parts[0]
                        if device.startswith('/dev/'):
                            disk_name = device.replace('/dev/', '').replace('mapper/', '')
                            add_usage(disk_name, 'swap')
        except Exception:
            pass
    
    try:
        # 3. Check ZFS pools using zpool list -v -H (matches bash _build_pool_disks)
        result = subprocess.run(
            ['zpool', 'list', '-v', '-H'],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0:
            current_pool = None
            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if not parts:
                    continue
                
                # First column is pool name or device
                entry = parts[0]
                
                # Skip metadata entries
                if entry in ('-', 'mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'spare', 'log', 'cache'):
                    continue
                
                # Check if this is a pool name (pools have no leading whitespace)
                if not line.startswith('\t') and not line.startswith(' '):
                    current_pool = entry
                    continue
                
                # This is a device entry - resolve it
                base_disk = _resolve_zfs_entry(entry)
                if base_disk:
                    pool_label = current_pool or 'unknown'
                    # Mark root pool specially
                    if zfs_root_pool and pool_label == zfs_root_pool:
                        add_usage(base_disk, f'zfs:{pool_label} (root)')
                    else:
                        add_usage(base_disk, f'zfs:{pool_label}')
    except Exception:
        pass
    
    try:
        # 4. Check LVM physical volumes
        result = subprocess.run(
            ['pvs', '--noheadings', '-o', 'pv_name,vg_name'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        pv_device = parts[0]
                        vg_name = parts[1]
                        if pv_device.startswith('/dev/'):
                            # Resolve to real path
                            try:
                                real_path = os.path.realpath(pv_device)
                                disk_name = os.path.basename(real_path)
                            except Exception:
                                disk_name = pv_device.replace('/dev/', '')
                            
                            # Proxmox typically uses 'pve' volume group
                            if 'pve' in vg_name.lower():
                                add_usage(disk_name, f'lvm:{vg_name} (pve)')
                            else:
                                add_usage(disk_name, f'lvm:{vg_name}')
    except Exception:
        pass
    
    try:
        # 5. Check active RAID arrays
        if os.path.exists('/proc/mdstat'):
            with open('/proc/mdstat', 'r') as f:
                content = f.read()
                if 'active' in content:
                    # Parse mdstat for active arrays
                    for line in content.split('\n'):
                        if 'active raid' in line:
                            # Extract device names from line like "md0 : active raid1 sda1[0] sdb1[1]"
                            parts = line.split()
                            for part in parts:
                                if '[' in part:
                                    dev = part.split('[')[0]
                                    add_usage(dev, 'raid')
    except Exception:
        pass
    
    try:
        # 6. Check for disks with Proxmox/system partition labels
        result = subprocess.run(
            ['lsblk', '-o', 'NAME,PARTLABEL', '-n', '-l'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    disk_name = parts[0]
                    partlabel = parts[1].lower() if len(parts) > 1 else ''
                    # Proxmox-specific and system partition labels
                    system_labels = ['pve', 'proxmox', 'bios', 'esp', 'efi', 'boot', 'grub']
                    if any(label in partlabel for label in system_labels):
                        add_usage(disk_name, 'system-partition')
    except Exception:
        pass
    
    return system_disks


def get_storage_info():
    """Get storage and disk information"""
    try:
        storage_data = {
            'total': 0,
            'used': 0,
            'available': 0,
            'disks': [],
            'zfs_pools': [],
            'disk_count': 0,
            'healthy_disks': 0,
            'warning_disks': 0,
            'critical_disks': 0
        }
        
        physical_disks = {}
        total_disk_size_bytes = 0
        
        # Get system disk information (disks used by Proxmox)
        system_disks = get_system_disks()
        
        try:
            # List all block devices
            result = subprocess.run(['lsblk', '-b', '-d', '-n', '-o', 'NAME,SIZE,TYPE'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] == 'disk':
                        disk_name = parts[0]
                        
                        # Skip virtual/RAM-based block devices
                        if disk_name.startswith('zd'):
                            # ZFS zvol devices
                            continue
                        if disk_name.startswith('zram'):
                            # zram compressed RAM devices (used by log2ram, etc.)
                            continue
                        
                        disk_size_bytes = int(parts[1])
                        disk_size_gb = disk_size_bytes / (1024**3)
                        disk_size_tb = disk_size_bytes / (1024**4)
                        
                        total_disk_size_bytes += disk_size_bytes
                        
                        # Get SMART data for this disk
                        # print(f"[v0] Getting SMART data for {disk_name}...")
                        pass
                        smart_data = get_smart_data(disk_name)
                        # print(f"[v0] SMART data for {disk_name}: {smart_data}")
                        pass
                        
                        disk_size_kb = disk_size_bytes / 1024
                        
                        if disk_size_tb >= 1:
                            size_str = f"{disk_size_tb:.1f}T"
                        else:
                            size_str = f"{disk_size_gb:.1f}G"
                        
                        conn_type = get_disk_connection_type(disk_name)
                        removable = is_disk_removable(disk_name)
                        
                        # Check if this disk is used by the system
                        sys_info = system_disks.get(disk_name, {})
                        is_system_disk = sys_info.get('is_system', False)
                        system_usage = sys_info.get('usage', [])
                        
                        physical_disks[disk_name] = {
                            'name': disk_name,
                            'size': disk_size_kb,  # In KB for formatMemory() in Storage Summary
                            'size_formatted': size_str,  # Added formatted size string for Storage section
                            'size_bytes': disk_size_bytes,
                            'temperature': smart_data.get('temperature', 0),
                            'health': smart_data.get('health', 'unknown'),
                            'power_on_hours': smart_data.get('power_on_hours', 0),
                            'smart_status': smart_data.get('smart_status', 'unknown'),
                            'model': smart_data.get('model', 'Unknown'),
                            'serial': smart_data.get('serial', 'Unknown'),
                            'reallocated_sectors': smart_data.get('reallocated_sectors', 0),
                            'pending_sectors': smart_data.get('pending_sectors', 0),
                            'crc_errors': smart_data.get('crc_errors', 0),
                            'rotation_rate': smart_data.get('rotation_rate', 0),
                            'power_cycles': smart_data.get('power_cycles', 0),
                            'percentage_used': smart_data.get('percentage_used'),
                            'media_wearout_indicator': smart_data.get('media_wearout_indicator'),
                            'wear_leveling_count': smart_data.get('wear_leveling_count'),
                            'total_lbas_written': smart_data.get('total_lbas_written'),
                            'ssd_life_left': smart_data.get('ssd_life_left'),
                            'connection_type': conn_type,
                            'removable': removable,
                            'is_system_disk': is_system_disk,
                            'system_usage': system_usage,
                        }
                        
        except Exception as e:
            pass
        
        # Enrich physical disks with active I/O errors from health_persistence.
        # This is the single source of truth -- health_monitor detects ATA/SCSI/IO
        # errors via dmesg, records them in health_persistence, and we read them here.
        try:
            active_disk_errors = health_persistence.get_active_errors(category='disks')
            for err in active_disk_errors:
                details = err.get('details', {})
                if isinstance(details, str):
                    try:
                        details = json.loads(details)
                    except (json.JSONDecodeError, TypeError):
                        details = {}
                
                err_device = details.get('disk', '')
                # Prefer the pre-resolved block device name (e.g. 'sdh' instead of 'ata8')
                block_device = details.get('block_device', '')
                err_serial = details.get('serial', '')
                error_count = details.get('error_count', 0)
                sample = details.get('sample', '')
                severity = err.get('severity', 'WARNING')
                
                # Match error to physical disk.
                # Priority: block_device > serial > err_device > ATA resolution
                matched_disk = None
                
                # 1. Direct match via pre-resolved block_device
                if block_device and block_device in physical_disks:
                    matched_disk = block_device
                
                # 2. Match by serial (most reliable across reboots/device renaming)
                if not matched_disk and err_serial:
                    for dk, dinfo in physical_disks.items():
                        if dinfo.get('serial', '').lower() == err_serial.lower():
                            matched_disk = dk
                            break
                
                # 3. Direct match via err_device
                if not matched_disk and err_device in physical_disks:
                    matched_disk = err_device
                
                # 4. Partial match
                if not matched_disk:
                    for dk in physical_disks:
                        if dk == err_device or err_device.startswith(dk):
                            matched_disk = dk
                            break
                
                # 5. ATA name resolution as last resort: 'ata8' -> 'sdh' via /sys
                if not matched_disk and err_device.startswith('ata'):
                    # Method A: Use /sys/class/ata_port to find the block device
                    try:
                        ata_path = f'/sys/class/ata_port/{err_device}'
                        if os.path.exists(ata_path):
                            device_path = os.path.realpath(ata_path)
                            for root, dirs, files in os.walk(os.path.dirname(device_path)):
                                if 'block' in dirs:
                                    devs = os.listdir(os.path.join(root, 'block'))
                                    for bd in devs:
                                        if bd in physical_disks:
                                            matched_disk = bd
                                            break
                                if matched_disk:
                                    break
                    except (OSError, IOError):
                        pass
                    # Method B: Walk /sys/block/sd* and check if ataX in device path
                    if not matched_disk:
                        try:
                            for sd in os.listdir('/sys/block'):
                                if not sd.startswith('sd'):
                                    continue
                                dev_link = f'/sys/block/{sd}/device'
                                if os.path.islink(dev_link):
                                    real_p = os.path.realpath(dev_link)
                                    if f'/{err_device}/' in real_p:
                                        if sd in physical_disks:
                                            matched_disk = sd
                                            break
                        except (OSError, IOError):
                            pass
                    # Method C: Check error details for display name hint
                    if not matched_disk:
                        display = details.get('display', '')
                        if display.startswith('/dev/'):
                            dev_hint = display.replace('/dev/', '')
                            if dev_hint in physical_disks:
                                matched_disk = dev_hint
                
                if matched_disk:
                    physical_disks[matched_disk]['io_errors'] = {
                        'count': error_count,
                        'severity': severity,
                        'sample': sample,
                        'reason': err.get('reason', ''),
                        'error_type': details.get('error_type', 'io'),
                    }
                    # Override health status if I/O errors are more severe
                    current_health = physical_disks[matched_disk].get('health', 'unknown').lower()
                    if severity == 'CRITICAL' and current_health != 'critical':
                        physical_disks[matched_disk]['health'] = 'critical'
                    elif severity == 'WARNING' and current_health in ('healthy', 'unknown'):
                        physical_disks[matched_disk]['health'] = 'warning'
                # If err_device doesn't match any physical disk, the error still
                # lives in the health monitor (Disk I/O & System Logs sections).
                # We don't create virtual disks -- Physical Disks shows real hardware only.
        except Exception:
            pass
        
        # Count disk health states AFTER I/O error enrichment
        for disk_name, disk_info in physical_disks.items():
            storage_data['disk_count'] += 1
            health = disk_info.get('health', 'unknown').lower()
            if health == 'healthy':
                storage_data['healthy_disks'] += 1
            elif health == 'warning':
                storage_data['warning_disks'] += 1
            elif health in ['critical', 'failed']:
                storage_data['critical_disks'] += 1
        
        storage_data['total'] = round(total_disk_size_bytes / (1024**4), 1)
        
        # Get disk usage for mounted partitions
        try:
            disk_partitions = psutil.disk_partitions()
            total_used = 0
            total_available = 0
            
            zfs_disks = set()
            
            for partition in disk_partitions:
                try:
                    # Skip special filesystems
                    if partition.fstype in ['tmpfs', 'devtmpfs', 'squashfs', 'overlay']:
                        continue
                    
                    if partition.fstype == 'zfs':
                        # print(f"[v0] Skipping ZFS filesystem {partition.mountpoint}, will count from pool data")
                        pass
                        continue
                    
                    partition_usage = psutil.disk_usage(partition.mountpoint)
                    total_used += partition_usage.used
                    total_available += partition_usage.free
                    
                    # Extract disk name from partition device
                    device_name = partition.device.replace('/dev/', '')
                    if device_name[-1].isdigit():
                        if 'nvme' in device_name or 'mmcblk' in device_name:
                            base_disk = device_name.rsplit('p', 1)[0]
                        else:
                            base_disk = device_name.rstrip('0123456789')
                    else:
                        base_disk = device_name
                    
                    # Find corresponding physical disk
                    disk_info = physical_disks.get(base_disk)
                    if disk_info and 'mountpoint' not in disk_info:
                        disk_info['mountpoint'] = partition.mountpoint
                        disk_info['fstype'] = partition.fstype
                        disk_info['total'] = round(partition_usage.total / (1024**3), 1)
                        disk_info['used'] = round(partition_usage.used / (1024**3), 1)
                        disk_info['available'] = round(partition_usage.free / (1024**3), 1)
                        disk_info['usage_percent'] = round(partition_usage.percent, 1)
                        
                except PermissionError:
                    continue
                except Exception as e:
                    # print(f"Error accessing partition {partition.device}: {e}")
                    pass
                    continue
            
            try:
                result = subprocess.run(['zpool', 'list', '-H', '-p', '-o', 'name,size,alloc,free,health'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            parts = line.split('\t')
                            if len(parts) >= 5:
                                pool_name = parts[0]
                                pool_size_bytes = int(parts[1])
                                pool_alloc_bytes = int(parts[2])
                                pool_free_bytes = int(parts[3])
                                pool_health = parts[4]
                                
                                total_used += pool_alloc_bytes
                                total_available += pool_free_bytes
                                
                                # print(f"[v0] ZFS Pool {pool_name}: allocated={pool_alloc_bytes / (1024**3):.2f}GB, free={pool_free_bytes / (1024**3):.2f}GB")
                                pass
                                
                                def format_zfs_size(size_bytes):
                                    size_tb = size_bytes / (1024**4)
                                    size_gb = size_bytes / (1024**3)
                                    if size_tb >= 1:
                                        return f"{size_tb:.1f}T"
                                    else:
                                        return f"{size_gb:.1f}G"
                                
                                pool_info = {
                                    'name': pool_name,
                                    'size': format_zfs_size(pool_size_bytes),
                                    'allocated': format_zfs_size(pool_alloc_bytes),
                                    'free': format_zfs_size(pool_free_bytes),
                                    'health': pool_health
                                }
                                storage_data['zfs_pools'].append(pool_info)
                                
                                try:
                                    pool_status = subprocess.run(['zpool', 'status', pool_name], 
                                                               capture_output=True, text=True, timeout=5)
                                    if pool_status.returncode == 0:
                                        for status_line in pool_status.stdout.split('\n'):
                                            for disk_name in physical_disks.keys():
                                                if disk_name in status_line:
                                                    zfs_disks.add(disk_name)
                                except Exception as e:
                                    # print(f"Error getting ZFS pool status for {pool_name}: {e}")
                                    pass
                                    
            except FileNotFoundError:
                # print("[v0] Note: ZFS not installed")
                pass
            except Exception as e:
                # print(f"[v0] Note: ZFS not available or no pools: {e}")
                pass
            
            storage_data['used'] = round(total_used / (1024**3), 1)
            storage_data['available'] = round(total_available / (1024**3), 1)
            
            # print(f"[v0] Total storage used: {storage_data['used']}GB (including ZFS pools)")
            pass
        
        except Exception as e:
            # print(f"Error getting partition info: {e}")
            pass
        
        # ── Register disks in observation system + enrich with observation counts ──
        try:
            active_dev_names = list(physical_disks.keys())
            
            # Register disks FIRST so that old ATA-named entries get
            # consolidated into block device names via serial matching.
            for disk_name, disk_info in physical_disks.items():
                health_persistence.register_disk(
                    device_name=disk_name,
                    serial=disk_info.get('serial', ''),
                    model=disk_info.get('model', ''),
                    size_bytes=disk_info.get('size_bytes'),
                )
            
            # Fetch observation counts AFTER registration so consolidated
            # entries are already merged (ata8 -> sdh).
            obs_counts = health_persistence.get_disks_observation_counts()
            
            for disk_name, disk_info in physical_disks.items():
                # Attach observation count: try serial match first, then device name
                serial = disk_info.get('serial', '')
                count = obs_counts.get(f'serial:{serial}', 0) if serial else 0
                if count == 0:
                    count = obs_counts.get(disk_name, 0)
                disk_info['observations_count'] = count
            
            # Mark disks no longer present as removed
            health_persistence.mark_removed_disks(active_dev_names)
            # Auto-dismiss stale observations (> 30 days old)
            health_persistence.cleanup_stale_observations()
        except Exception:
            pass
        
        storage_data['disks'] = list(physical_disks.values())
        
        return storage_data
        
    except Exception as e:
        # print(f"Error getting storage info: {e}")
        pass
        return {
            'error': f'Unable to access storage information: {str(e)}',
            'total': 0,
            'used': 0,
            'available': 0,
            'disks': [],
            'zfs_pools': [],
            'disk_count': 0,
            'healthy_disks': 0,
            'warning_disks': 0,
            'critical_disks': 0
        }

# Define get_disk_hardware_info (stub for now, will be replaced by lsblk parsing)
def get_disk_hardware_info(disk_name):
    """Placeholder for disk hardware info - to be populated by lsblk later."""
    return {}

def get_pcie_link_speed(disk_name):
    """Get PCIe link speed information for NVMe drives"""
    pcie_info = {
        'pcie_gen': None,
        'pcie_width': None,
        'pcie_max_gen': None,
        'pcie_max_width': None
    }
    
    try:
        # For NVMe drives, get PCIe information from sysfs
        if disk_name.startswith('nvme'):
            # Extract controller name properly using regex
            import re
            match = re.match(r'(nvme\d+)n\d+', disk_name)
            if not match:
                # print(f"[v0] Could not extract controller from {disk_name}")
                pass
                return pcie_info
            
            controller = match.group(1)  # nvme0n1 -> nvme0
            # print(f"[v0] Getting PCIe info for {disk_name}, controller: {controller}")
            pass
            
            # Path to PCIe device in sysfs
            sys_path = f'/sys/class/nvme/{controller}/device'
            
            # print(f"[v0] Checking sys_path: {sys_path}, exists: {os.path.exists(sys_path)}")
            pass
            
            if os.path.exists(sys_path):
                try:
                    pci_address = os.path.basename(os.readlink(sys_path))
                    # print(f"[v0] PCI address for {disk_name}: {pci_address}")
                    pass
                    
                    # Use lspci to get detailed PCIe information
                    result = subprocess.run(['lspci', '-vvv', '-s', pci_address], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        # print(f"[v0] lspci output for {pci_address}:")
                        pass
                        for line in result.stdout.split('\n'):
                            # Look for "LnkSta:" line which shows current link status
                            if 'LnkSta:' in line:
                                # print(f"[v0] Found LnkSta: {line}")
                                pass
                                # Example: "LnkSta: Speed 8GT/s, Width x4"
                                if 'Speed' in line:
                                    speed_match = re.search(r'Speed\s+([\d.]+)GT/s', line)
                                    if speed_match:
                                        gt_s = float(speed_match.group(1))
                                        if gt_s <= 2.5:
                                            pcie_info['pcie_gen'] = '1.0'
                                        elif gt_s <= 5.0:
                                            pcie_info['pcie_gen'] = '2.0'
                                        elif gt_s <= 8.0:
                                            pcie_info['pcie_gen'] = '3.0'
                                        elif gt_s <= 16.0:
                                            pcie_info['pcie_gen'] = '4.0'
                                        else:
                                            pcie_info['pcie_gen'] = '5.0'
                                        # print(f"[v0] Current PCIe gen: {pcie_info['pcie_gen']}")
                                        pass
                                
                                if 'Width' in line:
                                    width_match = re.search(r'Width\s+x(\d+)', line)
                                    if width_match:
                                        pcie_info['pcie_width'] = f'x{width_match.group(1)}'
                                        # print(f"[v0] Current PCIe width: {pcie_info['pcie_width']}")
                                        pass
                            
                            # Look for "LnkCap:" line which shows maximum capabilities
                            elif 'LnkCap:' in line:
                                # print(f"[v0] Found LnkCap: {line}")
                                pass
                                if 'Speed' in line:
                                    speed_match = re.search(r'Speed\s+([\d.]+)GT/s', line)
                                    if speed_match:
                                        gt_s = float(speed_match.group(1))
                                        if gt_s <= 2.5:
                                            pcie_info['pcie_max_gen'] = '1.0'
                                        elif gt_s <= 5.0:
                                            pcie_info['pcie_max_gen'] = '2.0'
                                        elif gt_s <= 8.0:
                                            pcie_info['pcie_max_gen'] = '3.0'
                                        elif gt_s <= 16.0:
                                            pcie_info['pcie_max_gen'] = '4.0'
                                        else:
                                            pcie_info['pcie_max_gen'] = '5.0'
                                        # print(f"[v0] Max PCIe gen: {pcie_info['pcie_max_gen']}")
                                        pass
                                
                                if 'Width' in line:
                                    width_match = re.search(r'Width\s+x(\d+)', line)
                                    if width_match:
                                        pcie_info['pcie_max_width'] = f'x{width_match.group(1)}'
                                        # print(f"[v0] Max PCIe width: {pcie_info['pcie_max_width']}")
                                        pass
                    else:
                        # print(f"[v0] lspci failed with return code: {result.returncode}")
                        pass
                except Exception as e:
                    # print(f"[v0] Error getting PCIe info via lspci: {e}")
                    pass
                    import traceback
                    traceback.print_exc()
            else:
                # print(f"[v0] sys_path does not exist: {sys_path}")
                pass
                alt_sys_path = f'/sys/block/{disk_name}/device/device'
                # print(f"[v0] Trying alternative path: {alt_sys_path}, exists: {os.path.exists(alt_sys_path)}")
                pass
                
                if os.path.exists(alt_sys_path):
                    try:
                        # Get PCI address from the alternative path
                        pci_address = os.path.basename(os.readlink(alt_sys_path))
                        # print(f"[v0] PCI address from alt path for {disk_name}: {pci_address}")
                        pass
                        
                        # Use lspci to get detailed PCIe information
                        result = subprocess.run(['lspci', '-vvv', '-s', pci_address], 
                                              capture_output=True, text=True, timeout=5)
                        if result.returncode == 0:
                            # print(f"[v0] lspci output for {pci_address} (from alt path):")
                            pass
                            for line in result.stdout.split('\n'):
                                # Look for "LnkSta:" line which shows current link status
                                if 'LnkSta:' in line:
                                    # print(f"[v0] Found LnkSta: {line}")
                                    pass
                                    if 'Speed' in line:
                                        speed_match = re.search(r'Speed\s+([\d.]+)GT/s', line)
                                        if speed_match:
                                            gt_s = float(speed_match.group(1))
                                            if gt_s <= 2.5:
                                                pcie_info['pcie_gen'] = '1.0'
                                            elif gt_s <= 5.0:
                                                pcie_info['pcie_gen'] = '2.0'
                                            elif gt_s <= 8.0:
                                                pcie_info['pcie_gen'] = '3.0'
                                            elif gt_s <= 16.0:
                                                pcie_info['pcie_gen'] = '4.0'
                                            else:
                                                pcie_info['pcie_gen'] = '5.0'
                                            # print(f"[v0] Current PCIe gen: {pcie_info['pcie_gen']}")
                                            pass
                                    
                                    if 'Width' in line:
                                        width_match = re.search(r'Width\s+x(\d+)', line)
                                        if width_match:
                                            pcie_info['pcie_width'] = f'x{width_match.group(1)}'
                                            # print(f"[v0] Current PCIe width: {pcie_info['pcie_width']}")
                                            pass
                                
                                # Look for "LnkCap:" line which shows maximum capabilities
                                elif 'LnkCap:' in line:
                                    # print(f"[v0] Found LnkCap: {line}")
                                    pass
                                    if 'Speed' in line:
                                        speed_match = re.search(r'Speed\s+([\d.]+)GT/s', line)
                                        if speed_match:
                                            gt_s = float(speed_match.group(1))
                                            if gt_s <= 2.5:
                                                pcie_info['pcie_max_gen'] = '1.0'
                                            elif gt_s <= 5.0:
                                                pcie_info['pcie_max_gen'] = '2.0'
                                            elif gt_s <= 8.0:
                                                pcie_info['pcie_max_gen'] = '3.0'
                                            elif gt_s <= 16.0:
                                                pcie_info['pcie_max_gen'] = '4.0'
                                            else:
                                                pcie_info['pcie_max_gen'] = '5.0'
                                            # print(f"[v0] Max PCIe gen: {pcie_info['pcie_max_gen']}")
                                            pass
                                    
                                    if 'Width' in line:
                                        width_match = re.search(r'Width\s+x(\d+)', line)
                                        if width_match:
                                            pcie_info['pcie_max_width'] = f'x{width_match.group(1)}'
                                            # print(f"[v0] Max PCIe width: {pcie_info['pcie_max_width']}")
                                            pass
                        else:
                            # print(f"[v0] lspci failed with return code: {result.returncode}")
                            pass
                    except Exception as e:
                        # print(f"[v0] Error getting PCIe info from alt path: {e}")
                        pass
                        import traceback
                        traceback.print_exc()
    
    except Exception as e:
        # print(f"[v0] Error in get_pcie_link_speed for {disk_name}: {e}")
        pass
        import traceback
        traceback.print_exc()
    
    # print(f"[v0] Final PCIe info for {disk_name}: {pcie_info}")
    pass
    return pcie_info

# get_pcie_link_speed function definition ends here

# ─── SMART data cache (Sprint 14 perf pass) ──────────────────────────────────
#
# `_get_smart_data_uncached` cycles through up to 14 smartctl variants per
# disk to find one that works. The Storage page polls /api/storage every few
# seconds, so without caching that was 4× <variants> smartctl forks every
# poll on a typical 4-disk host. Three caches mirror the pattern proven in
# `disk_temperature_history`:
#
#   * `_smart_probe_cache`  — remembers the smartctl args that worked for
#                             each disk. Subsequent calls skip the fallback
#                             chain.
#   * `_smart_result_cache` — memoises the parsed dict for 30 s. SMART
#                             counters (temp, sectors) change slowly enough
#                             that this is invisible to the user.
#   * `_smart_fail_backoff` — disks that keep failing every variant get
#                             re-probed at most once an hour.
_SMART_RESULT_TTL = 30
_SMART_FAIL_BACKOFF_SEC = 3600
_SMART_FAIL_THRESHOLD = 3
_SMART_TIMEOUT = 5

_smart_probe_cache: dict[str, list] = {}
_smart_result_cache: dict[str, tuple] = {}
_smart_fail_counts: dict[str, int] = {}
_smart_fail_backoff: dict[str, float] = {}


def _smart_default_payload() -> dict:
    """Empty SMART payload shared by cache-miss and probe-fail paths."""
    return {
        'temperature': 0,
        'health': 'unknown',
        'power_on_hours': 0,
        'smart_status': 'unknown',
        'model': 'Unknown',
        'serial': 'Unknown',
        'reallocated_sectors': 0,
        'pending_sectors': 0,
        'crc_errors': 0,
        'rotation_rate': 0,
        'power_cycles': 0,
        'percentage_used': None,
        'media_wearout_indicator': None,
        'wear_leveling_count': None,
        'total_lbas_written': None,
        'ssd_life_left': None,
        'firmware': None,
        'family': None,
        'sata_version': None,
        'form_factor': None,
    }


def _smart_data_useful(d: dict) -> bool:
    """Did the probe return anything actionable? Used to decide if the
    result is worth caching and to drive the failure backoff."""
    return (
        d.get('model', 'Unknown') != 'Unknown'
        or d.get('serial', 'Unknown') != 'Unknown'
        or (d.get('temperature') or 0) > 0
        or d.get('smart_status', 'unknown') not in ('unknown', '')
    )


def get_smart_data(disk_name):
    """Cached wrapper around the underlying smartctl probe.

    Three short-circuits stack on top of the original 14-variant
    fallback chain:
      1. Result cache — within 30 s of a successful probe, return the
         memoised payload immediately. This is the by-far hottest path
         because the dashboard polls /api/storage every few seconds.
      2. Failure backoff — after 3 consecutive failures, return an
         empty payload for an hour instead of re-running every variant.
      3. Probe cache (inside the implementation) — once one smartctl
         invocation works for a disk, memoise its argv so the next call
         tries that command first instead of cycling through all 14.
    """
    now = time.time()

    cached = _smart_result_cache.get(disk_name)
    if cached and now - cached[0] < _SMART_RESULT_TTL:
        return dict(cached[1])

    retry_at = _smart_fail_backoff.get(disk_name, 0)
    if retry_at > now:
        return dict(cached[1]) if cached else _smart_default_payload()

    result = _get_smart_data_uncached(disk_name)

    if _smart_data_useful(result):
        _smart_result_cache[disk_name] = (now, dict(result))
        _smart_fail_counts.pop(disk_name, None)
        _smart_fail_backoff.pop(disk_name, None)
    else:
        n = _smart_fail_counts.get(disk_name, 0) + 1
        _smart_fail_counts[disk_name] = n
        if n >= _SMART_FAIL_THRESHOLD:
            _smart_fail_backoff[disk_name] = now + _SMART_FAIL_BACKOFF_SEC
            _smart_probe_cache.pop(disk_name, None)
    return result


def _get_smart_data_uncached(disk_name):
    """Original 14-variant smartctl probe — the slow path. Wrapped by
    `get_smart_data` for caching. Probe-cache lives inside this fn so a
    successful run also remembers which command worked."""
    smart_data = _smart_default_payload()


    
    try:
        all_commands = [
            ['smartctl', '-a', '-j', f'/dev/{disk_name}'],  # JSON auto-detect (preferred)
            ['smartctl', '-a', '-j', '-d', 'scsi', f'/dev/{disk_name}'],  # JSON SCSI/SAS (early for SAS disks)
            ['smartctl', '-a', '-d', 'ata', f'/dev/{disk_name}'],  # JSON with ATA device type
            ['smartctl', '-a', '-d', 'sat', f'/dev/{disk_name}'],  # JSON with SAT device type
            ['smartctl', '-a', f'/dev/{disk_name}'],  # Text output (fallback)
            ['smartctl', '-a', '-d', 'ata', f'/dev/{disk_name}'],  # Text with ATA device type
            ['smartctl', '-a', '-d', 'sat', f'/dev/{disk_name}'],  # Text with SAT device type
            ['smartctl', '-i', '-H', '-A', f'/dev/{disk_name}'],  # Info + Health + Attributes
            ['smartctl', '-i', '-H', '-A', '-d', 'ata', f'/dev/{disk_name}'],  # With ATA
            ['smartctl', '-i', '-H', '-A', '-d', 'sat', f'/dev/{disk_name}'],  # With SAT
            ['smartctl', '-a', '-j', '-d', 'sat,12', f'/dev/{disk_name}'],  # SAT with 12-byte commands
            ['smartctl', '-a', '-j', '-d', 'sat,16', f'/dev/{disk_name}'],  # SAT with 16-byte commands
            ['smartctl', '-a', '-d', 'sat,12', f'/dev/{disk_name}'],  # Text SAT with 12-byte commands
            ['smartctl', '-a', '-d', 'sat,16', f'/dev/{disk_name}'],  # Text SAT with 16-byte commands
        ]

        # Probe-cache: if we already know which command works for this
        # disk, try that first. The fallback chain is still kept after
        # in case the cached probe stops working (kernel upgrade swapped
        # the auto-detect path, drive replaced, etc.) — we'll catch the
        # change and re-cache below.
        cached_cmd = _smart_probe_cache.get(disk_name)
        if cached_cmd is not None:
            commands_to_try = [cached_cmd] + [c for c in all_commands if c != cached_cmd]
        else:
            commands_to_try = all_commands

        process = None # Initialize process to None
        for cmd_index, cmd in enumerate(commands_to_try):
            # print(f"[v0] Attempt {cmd_index + 1}/{len(commands_to_try)}: Running command: {' '.join(cmd)}")
            pass
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                # Use communicate with a timeout to avoid hanging if the process doesn't exit
                stdout, stderr = process.communicate(timeout=_SMART_TIMEOUT)
                result_code = process.returncode
                
                # print(f"[v0] Command return code: {result_code}")
                pass
                
                if stderr:
                    stderr_preview = stderr[:200].replace('\n', ' ')
                    # print(f"[v0] stderr: {stderr_preview}")
                    pass
                
                has_output = stdout and len(stdout.strip()) > 50
                
                if has_output:

                    
                    # Try JSON parsing first (if -j flag was used)
                    if '-j' in cmd:
                        try:

                            data = json.loads(stdout)

                            
                            # Extract model
                            if 'model_name' in data:
                                smart_data['model'] = data['model_name']

                            elif 'model_family' in data:
                                smart_data['model'] = data['model_family']

                            
                            # Extract serial
                            if 'serial_number' in data:
                                smart_data['serial'] = data['serial_number']

                            
                            if 'rotation_rate' in data:
                                smart_data['rotation_rate'] = data['rotation_rate']

                            
                            # Extract SMART status
                            if 'smart_status' in data and 'passed' in data['smart_status']:
                                smart_data['smart_status'] = 'passed' if data['smart_status']['passed'] else 'failed'
                                smart_data['health'] = 'healthy' if data['smart_status']['passed'] else 'critical'

                            
                            # Extract temperature
                            if 'temperature' in data and 'current' in data['temperature']:
                                smart_data['temperature'] = data['temperature']['current']

                            
                            # Parse NVMe SMART data
                            if 'nvme_smart_health_information_log' in data:

                                nvme_data = data['nvme_smart_health_information_log']
                                if 'temperature' in nvme_data:
                                    smart_data['temperature'] = nvme_data['temperature']

                                if 'power_on_hours' in nvme_data:
                                    smart_data['power_on_hours'] = nvme_data['power_on_hours']

                                if 'power_cycles' in nvme_data:
                                    smart_data['power_cycles'] = nvme_data['power_cycles']

                                if 'percentage_used' in nvme_data:
                                    smart_data['percentage_used'] = nvme_data['percentage_used']

                                if 'data_units_written' in nvme_data:
                                    # NVMe spec (NVM Command Set, Log Page 02h "SMART/Health Information"):
                                    # data_units_written is reported in THOUSANDS of 512-byte units
                                    # (1 unit = 1000 * 512 bytes = 512,000 bytes), rounded up.
                                    # The previous comment ("unidades de 512KB") was wrong and the
                                    # resulting value was ~2.4% under the real bytes written.
                                    data_units = nvme_data['data_units_written']
                                    total_bytes = data_units * 1000 * 512
                                    total_gb = total_bytes / (1024 ** 3)
                                    smart_data['total_lbas_written'] = round(total_gb, 2)

                            
                            # Parse SCSI/SAS SMART data (no ATA attribute IDs)
                            device_protocol = data.get('device', {}).get('protocol', '')
                            if device_protocol == 'SCSI' or 'scsi_error_counter_log' in data:
                                # Temperature
                                if 'temperature' in data and 'current' in data['temperature']:
                                    smart_data['temperature'] = data['temperature']['current']
                                # Power-on hours
                                if 'power_on_time' in data:
                                    smart_data['power_on_hours'] = data['power_on_time'].get('hours', 0)
                                # Power cycles from start-stop counter
                                scsi_ssc = data.get('scsi_start_stop_cycle_counter', {})
                                if 'accumulated_start_stop_cycles' in scsi_ssc:
                                    smart_data['power_cycles'] = scsi_ssc['accumulated_start_stop_cycles']
                                # Grown defect list (equivalent to reallocated sectors)
                                gdl = data.get('scsi_grown_defect_list', 0)
                                if isinstance(gdl, dict):
                                    gdl = gdl.get('count', 0)
                                smart_data['reallocated_sectors'] = gdl
                                # Read/write errors from error counter log
                                ecl = data.get('scsi_error_counter_log', {})
                                read_errors = ecl.get('read', {}).get('errors_corrected_by_eccfast', 0) + \
                                              ecl.get('read', {}).get('errors_corrected_by_eccdelayed', 0) + \
                                              ecl.get('read', {}).get('total_errors_corrected', 0)
                                write_errors = ecl.get('write', {}).get('total_errors_corrected', 0)
                                # Uncorrected = potential data loss
                                uncorrected_read = ecl.get('read', {}).get('total_uncorrected_errors', 0)
                                uncorrected_write = ecl.get('write', {}).get('total_uncorrected_errors', 0)
                                smart_data['pending_sectors'] = uncorrected_read + uncorrected_write
                                # CRC errors not applicable for SAS, keep at 0

                            # Parse ATA SMART attributes
                            elif 'ata_smart_attributes' in data and 'table' in data['ata_smart_attributes']:

                                for attr in data['ata_smart_attributes']['table']:
                                    attr_id = attr.get('id')
                                    raw_value = attr.get('raw', {}).get('value', 0)
                                    normalized_value = attr.get('value', 0)  # Normalized value (0-100)
                                    
                                    if attr_id == 9:  # Power_On_Hours
                                        # Some drives encode extra data in high bytes, causing absurd values
                                        # Max reasonable value: ~1,000,000 hours = 114 years continuous use
                                        poh = raw_value
                                        if poh > 1000000:
                                            # Try extracting lower 24 bits (common encoding)
                                            poh = raw_value & 0xFFFFFF
                                            if poh > 1000000:
                                                # Still absurd, try lower 16 bits
                                                poh = raw_value & 0xFFFF
                                                if poh > 1000000:
                                                    # Give up, set to 0 (frontend shows N/A)
                                                    poh = 0
                                        smart_data['power_on_hours'] = poh

                                    elif attr_id == 12:  # Power_Cycle_Count
                                        smart_data['power_cycles'] = raw_value

                                    elif attr_id == 194:  # Temperature_Celsius
                                        if smart_data['temperature'] == 0:
                                            smart_data['temperature'] = raw_value

                                    elif attr_id == 190:  # Airflow_Temperature_Cel
                                        if smart_data['temperature'] == 0:
                                            smart_data['temperature'] = raw_value

                                    elif attr_id == 5:  # Reallocated_Sector_Ct
                                        smart_data['reallocated_sectors'] = raw_value

                                    elif attr_id == 197:  # Current_Pending_Sector
                                        smart_data['pending_sectors'] = raw_value

                                    elif attr_id == 199:  # UDMA_CRC_Error_Count
                                        smart_data['crc_errors'] = raw_value

                                    # --- SSD/NVMe wear & lifetime — NAME-based detection ---
                                    # Same SMART ID means different things on different manufacturers.
                                    # Always check attr name to avoid cross-manufacturer misinterpretation.
                                    elif attr_id in (177, 202, 230, 231, 233, 241):
                                        attr_name = attr.get('name', '').lower()

                                        # --- Wear / Life indicators ---
                                        if attr_id == 230 and ('wearout' in attr_name or 'media' in attr_name):
                                            # WD/SanDisk Media_Wearout_Indicator: value = endurance used %
                                            smart_data['media_wearout_indicator'] = normalized_value
                                            smart_data['ssd_life_left'] = max(0, 100 - normalized_value)

                                        elif attr_id == 233 and ('wearout' in attr_name or 'media' in attr_name):
                                            # Intel/Samsung Media_Wearout_Indicator: value = life remaining %
                                            # Skip if already set by ID 230 (prevents overwrite)
                                            if smart_data.get('media_wearout_indicator') is None:
                                                smart_data['media_wearout_indicator'] = 100 - normalized_value

                                        elif attr_id == 177 and ('wear' in attr_name or 'leveling' in attr_name):
                                            # Samsung/Crucial Wear_Leveling_Count: value = life remaining %
                                            smart_data['wear_leveling_count'] = 100 - normalized_value

                                        elif attr_id == 202 and ('lifetime' in attr_name or 'life' in attr_name):
                                            # Micron/Crucial Percent_Lifetime_Remain: value = life remaining %
                                            smart_data['ssd_life_left'] = normalized_value

                                        elif attr_id == 231 and ('life' in attr_name):
                                            # Kingston/Phison SSD_Life_Left: value = life remaining %
                                            smart_data['ssd_life_left'] = normalized_value

                                        # --- Data written ---
                                        elif attr_id == 241:
                                            if 'gib' in attr_name or '_gb' in attr_name or 'writes_g' in attr_name:
                                                # WD/Kingston: raw value already in GiB
                                                smart_data['total_lbas_written'] = round(raw_value, 2)
                                            elif 'lba' in attr_name or 'written' in attr_name:
                                                # Seagate/Standard: raw value in LBA sectors (512 bytes)
                                                try:
                                                    total_gb = (raw_value * 512) / (1024 * 1024 * 1024)
                                                    smart_data['total_lbas_written'] = round(total_gb, 2)
                                                except (ValueError, TypeError):
                                                    pass
                            
                            # If we got good data, break out of the loop and
                            # memoise this command so subsequent calls skip
                            # straight to it instead of re-trying the chain.
                            if smart_data['model'] != 'Unknown' and smart_data['serial'] != 'Unknown':
                                _smart_probe_cache[disk_name] = list(cmd)
                                break
                                
                        except json.JSONDecodeError as e:
                            # print(f"[v0] JSON parse failed: {e}, trying text parsing...")
                            pass
                    
                    if smart_data['model'] == 'Unknown' or smart_data['serial'] == 'Unknown' or smart_data['temperature'] == 0:
                        # print(f"[v0] Parsing text output (model={smart_data['model']}, serial={smart_data['serial']}, temp={smart_data['temperature']})...")
                        pass
                        output = stdout
                        
                        # Get basic info
                        for line in output.split('\n'):
                            line = line.strip()
                            
                            # Model detection
                            if (line.startswith('Device Model:') or line.startswith('Model Number:')) and smart_data['model'] == 'Unknown':
                                smart_data['model'] = line.split(':', 1)[1].strip()
                                # print(f"[v0] Found model: {smart_data['model']}")
                                pass
                            elif line.startswith('Model Family:') and smart_data['model'] == 'Unknown':
                                smart_data['model'] = line.split(':', 1)[1].strip()
                                # print(f"[v0] Found model family: {smart_data['model']}")
                                pass
                            
                            # Serial detection
                            elif line.startswith('Serial Number:') and smart_data['serial'] == 'Unknown':
                                smart_data['serial'] = line.split(':', 1)[1].strip()
                                # print(f"[v0] Found serial: {smart_data['serial']}")
                                pass
                            
                            elif line.startswith('Rotation Rate:') and smart_data['rotation_rate'] == 0:
                                rate_str = line.split(':', 1)[1].strip()
                                if 'rpm' in rate_str.lower():
                                    try:
                                        smart_data['rotation_rate'] = int(rate_str.split()[0])
                                        # print(f"[v0] Found rotation rate: {smart_data['rotation_rate']} RPM")
                                        pass
                                    except (ValueError, IndexError):
                                        pass
                                elif 'Solid State Device' in rate_str:
                                    smart_data['rotation_rate'] = 0  # SSD
                                    # print(f"[v0] Found SSD (no rotation)")
                                    pass
                            
                            # SMART status detection
                            elif 'SMART overall-health self-assessment test result:' in line:
                                if 'PASSED' in line:
                                    smart_data['smart_status'] = 'passed'
                                    smart_data['health'] = 'healthy'
                                    # print(f"[v0] SMART status: PASSED")
                                    pass
                                elif 'FAILED' in line:
                                    smart_data['smart_status'] = 'failed'
                                    smart_data['health'] = 'critical'
                                    # print(f"[v0] SMART status: FAILED")
                                    pass
                            
                            # NVMe health
                            elif 'SMART Health Status:' in line:
                                if 'OK' in line:
                                    smart_data['smart_status'] = 'passed'
                                    smart_data['health'] = 'healthy'
                                    # print(f"[v0] NVMe Health: OK")
                                    pass
                            
                            # Temperature detection (various formats)
                            elif 'Current Temperature:' in line and smart_data['temperature'] == 0:
                                try:
                                    temp_str = line.split(':')[1].strip().split()[0]
                                    smart_data['temperature'] = int(temp_str)
                                    # print(f"[v0] Found temperature: {smart_data['temperature']}°C")
                                    pass
                                except (ValueError, IndexError):
                                    pass
                        
                        # Parse SMART attributes table
                        in_attributes = False
                        for line in output.split('\n'):
                            line = line.strip()
                            
                            if 'ID# ATTRIBUTE_NAME' in line or 'ID#' in line and 'ATTRIBUTE_NAME' in line:
                                in_attributes = True
                                # print(f"[v0] Found SMART attributes table")
                                pass
                                continue
                            
                            if in_attributes:
                                # Stop at empty line or next section
                                if not line or line.startswith('SMART') or line.startswith('==='):
                                    in_attributes = False
                                    continue
                                
                                parts = line.split()
                                if len(parts) >= 10:
                                    try:
                                        attr_id = parts[0]
                                        # Raw value is typically the last column
                                        raw_value = parts[-1]
                                        
                                        # Parse based on attribute ID
                                        if attr_id == '9':  # Power On Hours
                                            raw_clean = raw_value.split()[0].replace('h', '').replace(',', '')
                                            smart_data['power_on_hours'] = int(raw_clean)
                                            # print(f"[v0] Power On Hours: {smart_data['power_on_hours']}")
                                            pass
                                        elif attr_id == '12':  # Power Cycle Count
                                            raw_clean = raw_value.split()[0].replace(',', '')
                                            smart_data['power_cycles'] = int(raw_clean)
                                            # print(f"[v0] Power Cycles: {smart_data['power_cycles']}")
                                            pass
                                        elif attr_id == '194' and smart_data['temperature'] == 0:  # Temperature
                                            temp_str = raw_value.split()[0]
                                            smart_data['temperature'] = int(temp_str)
                                            # print(f"[v0] Temperature (attr 194): {smart_data['temperature']}°C")
                                            pass
                                        elif attr_id == '190' and smart_data['temperature'] == 0:  # Airflow Temperature
                                            temp_str = raw_value.split()[0]
                                            smart_data['temperature'] = int(temp_str)
                                            # print(f"[v0] Airflow Temperature (attr 190): {smart_data['temperature']}°C")
                                            pass
                                        elif attr_id == '5':  # Reallocated Sectors
                                            smart_data['reallocated_sectors'] = int(raw_value)
                                            # print(f"[v0] Reallocated Sectors: {smart_data['reallocated_sectors']}")
                                            pass
                                        elif attr_id == '197':  # Pending Sectors
                                            smart_data['pending_sectors'] = int(raw_value)
                                            # print(f"[v0] Pending Sectors: {smart_data['pending_sectors']}")
                                            pass
                                        elif attr_id == '199':  # CRC Errors
                                            smart_data['crc_errors'] = int(raw_value)
                                            # print(f"[v0] CRC Errors: {smart_data['crc_errors']}")
                                            pass
                                        # --- SSD wear & data written (text path) — NAME-based ---
                                        elif attr_id in ('177', '202', '230', '231', '233', '241'):
                                            a_name = parts[1].lower() if len(parts) > 1 else ''
                                            nv = int(parts[3]) if len(parts) > 3 else 100

                                            if attr_id == '230' and ('wearout' in a_name or 'media' in a_name):
                                                # WD/SanDisk: value = endurance used %
                                                smart_data['media_wearout_indicator'] = nv
                                                smart_data['ssd_life_left'] = max(0, 100 - nv)

                                            elif attr_id == '233' and ('wearout' in a_name or 'media' in a_name):
                                                # Intel/Samsung: value = life remaining %
                                                if smart_data.get('media_wearout_indicator') is None:
                                                    smart_data['media_wearout_indicator'] = 100 - nv

                                            elif attr_id == '177' and ('wear' in a_name or 'leveling' in a_name):
                                                smart_data['wear_leveling_count'] = 100 - nv

                                            elif attr_id == '202' and ('lifetime' in a_name or 'life' in a_name):
                                                smart_data['ssd_life_left'] = nv

                                            elif attr_id == '231' and 'life' in a_name:
                                                smart_data['ssd_life_left'] = nv

                                            elif attr_id == '241':
                                                try:
                                                    raw_int = int(raw_value.replace(',', ''))
                                                    if 'gib' in a_name or '_gb' in a_name or 'writes_g' in a_name:
                                                        smart_data['total_lbas_written'] = round(raw_int, 2)
                                                    elif 'lba' in a_name or 'written' in a_name:
                                                        total_gb = (raw_int * 512) / (1024 * 1024 * 1024)
                                                        smart_data['total_lbas_written'] = round(total_gb, 2)
                                                except ValueError:
                                                    pass
                                            
                                    except (ValueError, IndexError) as e:
                                        # print(f"[v0] Error parsing attribute line '{line}': {e}")
                                        pass
                                        continue

                        # If we got complete data, break and memoise the
                        # winning command for the next call.
                        if smart_data['model'] != 'Unknown' and smart_data['serial'] != 'Unknown':
                            _smart_probe_cache[disk_name] = list(cmd)
                            break
                        elif smart_data['model'] != 'Unknown' or smart_data['serial'] != 'Unknown':
                            # print(f"[v0] Extracted partial data from text output, continuing to next attempt...")
                            pass
                else:
                    # print(f"[v0] No usable output (return code {result_code}), trying next command...")
                    pass
            
            except subprocess.TimeoutExpired:
                # print(f"[v0] Command timeout for attempt {cmd_index + 1}, trying next...")
                pass
                if process and process.returncode is None:
                    process.kill()
                continue
            except Exception as e:
                # print(f"[v0] Error in attempt {cmd_index + 1}: {type(e).__name__}: {e}")
                pass
                if process and process.returncode is None:
                    process.kill()
                continue
            finally:
                # Ensure the process is terminated if it's still running
                if process and process.poll() is None: 
                    try:
                        process.kill()
                        # print(f"[v0] Process killed for command: {' '.join(cmd)}")
                        pass
                    except Exception as kill_err:
                        # print(f"[v0] Error killing process: {kill_err}")
                        pass


        if smart_data['reallocated_sectors'] > 0 or smart_data['pending_sectors'] > 0:
            if smart_data['health'] == 'healthy':
                smart_data['health'] = 'warning'
            # print(f"[v0] Health: WARNING (reallocated/pending sectors)")
            pass
        if smart_data['reallocated_sectors'] > 10 or smart_data['pending_sectors'] > 10:
            smart_data['health'] = 'critical'
            # print(f"[v0] Health: CRITICAL (high sector count)")
            pass
        if smart_data['smart_status'] == 'failed':
            smart_data['health'] = 'critical'
            # print(f"[v0] Health: CRITICAL (SMART failed)")
            pass
        
        # Temperature-based health (only if we have a valid temperature)
        # Thresholds differ by disk class (HDD/SSD/NVMe/SAS) and are
        # user-configurable via health_thresholds; the values below are
        # the recommended defaults that ship out of the box.
        if smart_data['health'] == 'healthy' and smart_data['temperature'] > 0:
            temp = smart_data['temperature']
            try:
                import health_thresholds as _ht
                if disk_name.startswith('nvme'):
                    cls = 'nvme'
                    fb_warn, fb_crit = 80, 85
                elif smart_data['rotation_rate'] == 0:
                    cls = 'ssd'
                    fb_warn, fb_crit = 70, 75
                else:
                    cls = 'hdd'
                    fb_warn, fb_crit = 60, 65
                warn = _ht.get('disk_temperature', cls, 'warning', default=fb_warn)
                crit = _ht.get('disk_temperature', cls, 'critical', default=fb_crit)
            except Exception:
                if disk_name.startswith('nvme'):
                    warn, crit = 80, 85
                elif smart_data['rotation_rate'] == 0:
                    warn, crit = 70, 75
                else:
                    warn, crit = 60, 65
            if temp > crit:
                smart_data['health'] = 'critical'
            elif temp > warn:
                smart_data['health'] = 'warning'

        # CHANGE: Use -1 to indicate HDD with unknown RPM instead of inventing 7200 RPM
        # Fallback: Check kernel's rotational flag if smartctl didn't provide rotation_rate
        # This fixes detection for older disks that don't report RPM via smartctl
        if smart_data['rotation_rate'] == 0:
            try:
                rotational_path = f"/sys/block/{disk_name}/queue/rotational"
                if os.path.exists(rotational_path):
                    with open(rotational_path, 'r') as f:
                        rotational = int(f.read().strip())
                        if rotational == 1:
                            # Disk is rotational (HDD), use -1 to indicate "HDD but RPM unknown"
                            smart_data['rotation_rate'] = -1
                        # If rotational == 0, it's an SSD, keep rotation_rate as 0
            except Exception as e:
                pass  # If we can't read the file, leave rotation_rate as is

            
    except FileNotFoundError:
        # print(f"[v0] ERROR: smartctl not found - install smartmontools for disk monitoring.")
        pass
    except Exception as e:
        # print(f"[v0] ERROR: Unexpected exception for {disk_name}: {type(e).__name__}: {e}")
        pass
        import traceback
        traceback.print_exc()
    

    return smart_data

# ─── Proxmox storage cache (Sprint 14 perf pass) ─────────────────────────────
#
# `_get_proxmox_storage_uncached` does a pvesh /cluster/resources --type storage
# subprocess call (~860 ms on a typical cluster). Without caching, every hit
# on /api/proxmox-storage paid that cost — and the dashboard's Storage page
# polls it on an interval. A 30 s TTL is well below the rate of change for
# storage state (capacity, mount status) and matches the result-cache window
# we use for SMART data.
_PROXMOX_STORAGE_TTL = 30
_proxmox_storage_cache: dict = {'data': None, 'time': 0.0}


def get_proxmox_storage():
    """Cached wrapper. The Storage page polls this every few seconds; the
    underlying pvesh call costs ~860 ms, so the wrapper memoises the
    fully-post-processed result for 30 s."""
    now = time.time()
    cached = _proxmox_storage_cache
    if cached['data'] is not None and now - cached['time'] < _PROXMOX_STORAGE_TTL:
        return cached['data']
    result = _get_proxmox_storage_uncached()
    # Only cache successful responses — error payloads should retry sooner
    # so a transient pvesh hiccup doesn't pin "pvesh not available" on the
    # UI for a full TTL window.
    if isinstance(result, dict) and 'error' not in result:
        cached['data'] = result
        cached['time'] = now
    return result


# START OF CHANGES FOR get_proxmox_storage
def _get_proxmox_storage_uncached():
    """Get Proxmox storage information using pvesh (filtered by local node)"""
    try:
        # local_node = socket.gethostname()
        local_node = get_proxmox_node_name()
        
        result = subprocess.run(['pvesh', 'get', '/cluster/resources', '--type', 'storage', '--output-format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            # print(f"[v0] pvesh command failed with return code {result.returncode}")
            pass
            # print(f"[v0] stderr: {result.stderr}")
            pass
            return {
                'error': 'pvesh command not available or failed',
                'storage': []
            }
        
        storage_list = []
        resources = json.loads(result.stdout)
        
        for resource in resources:
            node = resource.get('node', '')
            
            # Filtrar solo storage del nodo local
            if node != local_node:
                # print(f"[v0] Skipping storage {resource.get('storage')} from remote node: {node}")
                pass
                continue
            
            name = resource.get('storage', 'unknown')
            storage_type = resource.get('plugintype', 'unknown')
            status = resource.get('status', 'unknown')
            
            try:
                total = int(resource.get('maxdisk', 0))
                used = int(resource.get('disk', 0))
                available = total - used if total > 0 else 0
            except (ValueError, TypeError):
                # print(f"[v0] Skipping storage {name} - invalid numeric data")
                pass
                continue
            
            # No filtrar storages no disponibles - mantenerlos para mostrar errores
            # Calcular porcentaje
            percent = (used / total * 100) if total > 0 else 0.0
            
            # Convert bytes to GB
            total_gb = round(total / (1024**3), 2)
            used_gb = round(used / (1024**3), 2)
            available_gb = round(available / (1024**3), 2)
            
            # Determine storage status. Sprint 11.6: a remote PBS where the
            # user only has DatastoreAdmin on their own namespace reports
            # `status=available` + `total=0` — the storage IS reachable, the
            # ACL just hides the datastore size. Surface as
            # 'namespace_restricted' so the UI can render INFO instead of
            # CRITICAL. Real outages still flag (status != available).
            if total == 0 and status.lower() == "available" and storage_type == 'pbs':
                storage_status = 'namespace_restricted'
            elif total == 0:
                storage_status = 'error'
            elif status.lower() != "available":
                storage_status = 'error'
            else:
                storage_status = 'active'
            
            storage_info = {
                'name': name,
                'type': storage_type,
                'status': storage_status,  # Usar el status determinado (active o error)
                'total': total_gb,
                'used': used_gb,
                'available': available_gb,
                'percent': round(percent, 2),
                'node': node  # Incluir información del nodo
            }
            

            storage_list.append(storage_info)
        
        # Get unavailable storages from monitor
        storage_status_data = proxmox_storage_monitor.get_storage_status()
        unavailable_storages = storage_status_data.get('unavailable', [])
        
        # Get list of storage names already added
        existing_storage_names = {s['name'] for s in storage_list}
        
        # Add unavailable storages to the list (only if not already present)
        for unavailable_storage in unavailable_storages:
            if unavailable_storage['name'] not in existing_storage_names:
                storage_list.append(unavailable_storage)
        
        # Get storage exclusions to mark excluded storages
        try:
            excluded_health = health_persistence.get_excluded_storage_names('health')
            remote_types = health_persistence.REMOTE_STORAGE_TYPES
            
            for storage in storage_list:
                storage_name = storage.get('name', '')
                storage_type = storage.get('type', '').lower()
                
                # Mark if this is a remote storage type
                storage['is_remote'] = storage_type in remote_types
                
                # Mark if excluded from health monitoring
                storage['excluded'] = storage_name in excluded_health
        except Exception:
            # If exclusion check fails, continue without it
            pass

        return {'storage': storage_list}
        
    except FileNotFoundError:
        # print("[v0] pvesh command not found - Proxmox not installed or not in PATH")
        pass
        return {
            'error': 'pvesh command not found - Proxmox not installed',
            'storage': []
        }
    except Exception as e:
        # print(f"[v0] Error getting Proxmox storage: {type(e).__name__}: {e}")
        pass
        import traceback
        traceback.print_exc()
        return {
            'error': f'Unable to get Proxmox storage: {str(e)}',
            'storage': []
        }
# END OF CHANGES FOR get_proxmox_storage

@app.route('/api/storage/summary', methods=['GET'])
@require_auth
def api_storage_summary():
    """Get storage summary without SMART data (optimized for Overview page)"""
    try:
        storage_data = {
            'total': 0,
            'used': 0,
            'available': 0,
            'disk_count': 0
        }
        
        total_disk_size_bytes = 0
        
        # List all block devices without SMART data
        result = subprocess.run(['lsblk', '-b', '-d', '-n', '-o', 'NAME,SIZE,TYPE'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 3 and parts[2] == 'disk':
                    disk_name = parts[0]
                    
                    # Skip virtual/RAM-based block devices
                    if disk_name.startswith('zd'):
                        continue
                    if disk_name.startswith('zram'):
                        continue
                    
                    disk_size_bytes = int(parts[1])
                    total_disk_size_bytes += disk_size_bytes
                    storage_data['disk_count'] += 1
        
        storage_data['total'] = round(total_disk_size_bytes / (1024**4), 1)
        
        # Get disk usage for mounted partitions (without ZFS)
        disk_partitions = psutil.disk_partitions()
        total_used = 0
        total_available = 0
        
        for partition in disk_partitions:
            try:
                # Skip special filesystems and ZFS
                if partition.fstype in ['tmpfs', 'devtmpfs', 'squashfs', 'overlay', 'zfs']:
                    continue
                
                partition_usage = psutil.disk_usage(partition.mountpoint)
                total_used += partition_usage.used
                total_available += partition_usage.free
            except (PermissionError, OSError):
                continue
        
        # Get ZFS pool data
        try:
            result = subprocess.run(['zpool', 'list', '-H', '-p', '-o', 'name,size,alloc,free'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split()
                        if len(parts) >= 4:
                            pool_alloc = int(parts[2])
                            pool_free = int(parts[3])
                            total_used += pool_alloc
                            total_available += pool_free
        except Exception:
            pass
        
        storage_data['used'] = round(total_used / (1024**3), 1)
        storage_data['available'] = round(total_available / (1024**3), 1)
        
        return jsonify(storage_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    # END OF CHANGE FOR /api/storage/summary

@app.route('/api/storage/observations', methods=['GET'])
@require_auth
def api_storage_observations():
    """Get disk observations (permanent error history) for a specific disk or all disks."""
    try:
        device = request.args.get('device', '')
        serial = request.args.get('serial', '')
        
        # Strip /dev/ prefix if present
        if device.startswith('/dev/'):
            device = device[5:]
        
        observations = health_persistence.get_disk_observations(
            device_name=device or None,
            serial=serial or None
        )
        
        return jsonify({'observations': observations})
    except Exception as e:
        return jsonify({'observations': [], 'error': str(e)}), 500

def get_interface_type(interface_name):
    """Detect the type of network interface"""
    try:
        # Skip loopback
        if interface_name == 'lo':
            return 'skip'
        
        if interface_name.startswith(('veth', 'tap')):
            return 'vm_lxc'
        
        # Skip other virtual interfaces
        if interface_name.startswith(('tun', 'vnet', 'docker', 'virbr')):
            return 'skip'
        
        # Check if it's a bond
        if interface_name.startswith('bond'):
            return 'bond'
        
        # Check if it's a bridge (but not virbr which we skip above)
        if interface_name.startswith(('vmbr', 'br')):
            return 'bridge'
        
        # Check if it's a VLAN (contains a dot)
        if '.' in interface_name:
            return 'vlan'
        
        # Check if interface has a real device symlink in /sys/class/net
        # This catches all physical interfaces including USB, regardless of naming
        sys_path = f'/sys/class/net/{interface_name}/device'
        if os.path.exists(sys_path):
            # It's a physical interface (PCI, USB, etc.)
            return 'physical'
        
        # This handles cases where /sys might not be available
        if interface_name.startswith(('enp', 'eth', 'eno', 'ens', 'enx', 'wlan', 'wlp', 'wlo', 'usb')):
            return 'physical'
        
        # Default to skip for unknown types
        return 'skip'
    except Exception as e:
        # print(f"[v0] Error detecting interface type for {interface_name}: {e}")
        pass
        return 'skip'

def get_bond_info(bond_name):
    """Get detailed information about a bonding interface"""
    bond_info = {
        'mode': 'unknown',
        'slaves': [],
        'active_slave': None
    }
    
    try:
        bond_file = f'/proc/net/bonding/{bond_name}'
        if os.path.exists(bond_file):
            with open(bond_file, 'r') as f:
                content = f.read()
                
                # Parse bonding mode
                for line in content.split('\n'):
                    if 'Bonding Mode:' in line:
                        bond_info['mode'] = line.split(':', 1)[1].strip()
                    elif 'Slave Interface:' in line:
                        slave_name = line.split(':', 1)[1].strip()
                        bond_info['slaves'].append(slave_name)
                    elif 'Currently Active Slave:' in line:
                        bond_info['active_slave'] = line.split(':', 1)[1].strip()
                
                # print(f"[v0] Bond {bond_name} info: mode={bond_info['mode']}, slaves={bond_info['slaves']}")
                pass
    except Exception as e:
        # print(f"[v0] Error reading bond info for {bond_name}: {e}")
        pass
    
    return bond_info

def get_bridge_info(bridge_name):
    """Get detailed information about a bridge interface"""
    bridge_info = {
        'members': [],
        'physical_interface': None,
        'physical_duplex': 'unknown',  # Added physical_duplex field
        # Added bond_slaves to show physical interfaces
        'bond_slaves': []
    }
    
    try:
        # Try to read bridge members from /sys/class/net/<bridge>/brif/
        brif_path = f'/sys/class/net/{bridge_name}/brif'
        if os.path.exists(brif_path):
            members = os.listdir(brif_path)
            bridge_info['members'] = members
            
            for member in members:
                # Check if member is a bond first
                if member.startswith('bond'):
                    bridge_info['physical_interface'] = member
                    # print(f"[v0] Bridge {bridge_name} connected to bond: {member}")
                    pass
                    
                    bond_info = get_bond_info(member)
                    if bond_info['slaves']:
                        bridge_info['bond_slaves'] = bond_info['slaves']
                        # print(f"[v0] Bond {member} slaves: {bond_info['slaves']}")
                        pass
                    
                    # Get duplex from bond's active slave
                    if bond_info['active_slave']:
                        try:
                            net_if_stats = psutil.net_if_stats()
                            if bond_info['active_slave'] in net_if_stats:
                                stats = net_if_stats[bond_info['active_slave']]
                                bridge_info['physical_duplex'] = 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown'
                                # print(f"[v0] Bond {member} active slave {bond_info['active_slave']} duplex: {bridge_info['physical_duplex']}")
                                pass
                        except Exception as e:
                            # print(f"[v0] Error getting duplex for bond slave {bond_info['active_slave']}: {e}")
                            pass
                    break
                # Check if member is a physical interface
                elif member.startswith(('enp', 'eth', 'eno', 'ens', 'wlan', 'wlp')):
                    bridge_info['physical_interface'] = member
                    # print(f"[v0] Bridge {bridge_name} physical interface: {member}")
                    pass
                    
                    # Get duplex from physical interface
                    try:
                        net_if_stats = psutil.net_if_stats()
                        if member in net_if_stats:
                            stats = net_if_stats[member]
                            bridge_info['physical_duplex'] = 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown'
                            # print(f"[v0] Physical interface {member} duplex: {bridge_info['physical_duplex']}")
                            pass
                    except Exception as e:
                        # print(f"[v0] Error getting duplex for {member}: {e}")
                        pass
                    
                    break
            
            # print(f"[v0] Bridge {bridge_name} members: {members}")
            pass
    except Exception as e:
        # print(f"[v0] Error reading bridge info for {bridge_name}: {e}")
        pass
    
    return bridge_info

def get_network_info():
    """Get network interface information - Enhanced with VM/LXC interface separation"""
    try:
        network_data = {
            'interfaces': [],
            'physical_interfaces': [],  # Added separate list for physical interfaces
            'bridge_interfaces': [],    # Added separate list for bridge interfaces
            'vm_lxc_interfaces': [],
            'traffic': {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0},
            # 'hostname': socket.gethostname(),
            'hostname': get_proxmox_node_name(),
            'domain': None,
            'dns_servers': []
        }
        
        try:
            with open('/etc/resolv.conf', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('nameserver'):
                        dns_server = line.split()[1]
                        network_data['dns_servers'].append(dns_server)
                    elif line.startswith('domain'):
                        network_data['domain'] = line.split()[1]
                    elif line.startswith('search') and not network_data['domain']:
                        # Use first search domain if no domain is set
                        domains = line.split()[1:]
                        if domains:
                            network_data['domain'] = domains[0]
        except Exception as e:
            # print(f"[v0] Error reading DNS configuration: {e}")
            pass
        
        try:
            fqdn = socket.getfqdn()
            if '.' in fqdn and fqdn != network_data['hostname']:
                # Extract domain from FQDN if not already set
                if not network_data['domain']:
                    network_data['domain'] = fqdn.split('.', 1)[1]
        except Exception as e:
            # print(f"[v0] Error getting FQDN: {e}")
            pass
        
        vm_lxc_map = get_vm_lxc_names()
        
        # Get network interfaces
        net_if_addrs = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        
        try:
            net_io_per_nic = psutil.net_io_counters(pernic=True)
        except Exception as e:
            # print(f"[v0] Error getting per-NIC stats: {e}")
            pass
            net_io_per_nic = {}
        
        physical_active_count = 0
        physical_total_count = 0
        bridge_active_count = 0
        bridge_total_count = 0
        vm_lxc_active_count = 0
        vm_lxc_total_count = 0
        
        for interface_name, interface_addresses in net_if_addrs.items():
            interface_type = get_interface_type(interface_name)
            
            if interface_type == 'skip':
                # print(f"[v0] Skipping interface: {interface_name} (type: {interface_type})")
                pass
                continue
            
            stats = net_if_stats.get(interface_name)
            if not stats:
                continue
            
            if interface_type == 'vm_lxc':
                vm_lxc_total_count += 1
                if stats.isup:
                    vm_lxc_active_count += 1
            elif interface_type == 'physical':
                physical_total_count += 1
                if stats.isup:
                    physical_active_count += 1
            elif interface_type == 'bridge':
                bridge_total_count += 1
                if stats.isup:
                    bridge_active_count += 1
            
            interface_info = {
                'name': interface_name,
                'type': interface_type,
                'status': 'up' if stats.isup else 'down',
                'speed': stats.speed if stats.speed > 0 else 0,
                'duplex': 'full' if stats.duplex == 2 else 'half' if stats.duplex == 1 else 'unknown',
                'mtu': stats.mtu,
                'addresses': [],
                'mac_address': None,
            }
            
            if interface_type == 'vm_lxc':
                vmid, vm_type = extract_vmid_from_interface(interface_name)
                if vmid and vmid in vm_lxc_map:
                    interface_info['vmid'] = vmid
                    interface_info['vm_name'] = vm_lxc_map[vmid]['name']
                    interface_info['vm_type'] = vm_lxc_map[vmid]['type']
                    interface_info['vm_status'] = vm_lxc_map[vmid]['status']
                elif vmid:
                    interface_info['vmid'] = vmid
                    interface_info['vm_name'] = f'{"LXC" if vm_type == "lxc" else "VM"} {vmid}'
                    interface_info['vm_type'] = vm_type
                    interface_info['vm_status'] = 'unknown'
            
            for address in interface_addresses:
                if address.family == 2:  # IPv4
                    interface_info['addresses'].append({
                        'ip': address.address,
                        'netmask': address.netmask
                    })
                elif address.family == 17:  # AF_PACKET (MAC address on Linux)
                    interface_info['mac_address'] = address.address
            
            if interface_name in net_io_per_nic:
                io_stats = net_io_per_nic[interface_name]
                
                # because psutil reports from host perspective, not VM/LXC perspective
                if interface_type == 'vm_lxc':
                    # From VM/LXC perspective: host's sent = VM received, host's recv = VM sent
                    interface_info['bytes_sent'] = io_stats.bytes_recv
                    interface_info['bytes_recv'] = io_stats.bytes_sent
                    interface_info['packets_sent'] = io_stats.packets_recv
                    interface_info['packets_recv'] = io_stats.packets_sent
                else:
                    interface_info['bytes_sent'] = io_stats.bytes_sent
                    interface_info['bytes_recv'] = io_stats.bytes_recv
                    interface_info['packets_sent'] = io_stats.packets_sent
                    interface_info['packets_recv'] = io_stats.packets_recv
                
                interface_info['errors_in'] = io_stats.errin
                interface_info['errors_out'] = io_stats.errout
                interface_info['drops_in'] = io_stats.dropin
                interface_info['drops_out'] = io_stats.dropout
            
            if interface_type == 'bond':
                bond_info = get_bond_info(interface_name)
                interface_info['bond_mode'] = bond_info['mode']
                interface_info['bond_slaves'] = bond_info['slaves']
                interface_info['bond_active_slave'] = bond_info['active_slave']
            
            if interface_type == 'bridge':
                bridge_info = get_bridge_info(interface_name)
                interface_info['bridge_members'] = bridge_info['members']
                interface_info['bridge_physical_interface'] = bridge_info['physical_interface']
                interface_info['bridge_physical_duplex'] = bridge_info['physical_duplex']
                interface_info['bridge_bond_slaves'] = bridge_info['bond_slaves']
                # Override bridge duplex with physical interface duplex
                if bridge_info['physical_duplex'] != 'unknown':
                    interface_info['duplex'] = bridge_info['physical_duplex']
            
            if interface_type == 'vm_lxc':
                network_data['vm_lxc_interfaces'].append(interface_info)
            elif interface_type == 'physical':
                network_data['physical_interfaces'].append(interface_info)
            elif interface_type == 'bridge':
                network_data['bridge_interfaces'].append(interface_info)
            else:
                # Keep other types in the general interfaces list for backward compatibility
                network_data['interfaces'].append(interface_info)
        
        network_data['physical_active_count'] = physical_active_count
        network_data['physical_total_count'] = physical_total_count
        network_data['bridge_active_count'] = bridge_active_count
        network_data['bridge_total_count'] = bridge_total_count
        network_data['vm_lxc_active_count'] = vm_lxc_active_count
        network_data['vm_lxc_total_count'] = vm_lxc_total_count
        
        # print(f"[v0] Physical interfaces: {physical_active_count} active out of {physical_total_count} total")
        pass
        # print(f"[v0] Bridge interfaces: {bridge_active_count} active out of {bridge_total_count} total")
        pass
        # print(f"[v0] VM/LXC interfaces: {vm_lxc_active_count} active out of {vm_lxc_total_count} total")
        pass
        
        # Get network I/O statistics (global)
        net_io = psutil.net_io_counters()
        network_data['traffic'] = {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv,
            'errin': net_io.errin,
            'errout': net_io.errout,
            'dropin': net_io.dropin,
            'dropout': net_io.dropout
        }
        
        total_packets_in = net_io.packets_recv + net_io.dropin
        total_packets_out = net_io.packets_sent + net_io.dropout
        
        if total_packets_in > 0:
            network_data['traffic']['packet_loss_in'] = round((net_io.dropin / total_packets_in) * 100, 2)
        else:
            network_data['traffic']['packet_loss_in'] = 0
            
        if total_packets_out > 0:
            network_data['traffic']['packet_loss_out'] = round((io_stats.dropout / total_packets_out) * 100, 2)
        else:
            network_data['traffic']['packet_loss_out'] = 0
        
        return network_data
    except Exception as e:
        # print(f"Error getting network info: {e}")
        pass
        import traceback
        traceback.print_exc()
        return {
            'error': f'Unable to access network information: {str(e)}',
            'interfaces': [],
            'physical_interfaces': [],
            'bridge_interfaces': [],
            'vm_lxc_interfaces': [],
            'traffic': {'bytes_sent': 0, 'bytes_recv': 0, 'packets_sent': 0, 'packets_recv': 0},
            'active_count': 0,
            'total_count': 0,
            'physical_active_count': 0,
            'physical_total_count': 0,
            'bridge_active_count': 0,
            'bridge_total_count': 0,
            'vm_lxc_active_count': 0,
            'vm_lxc_total_count': 0
        }

def _get_lxc_update_status_map() -> dict:
    """Read the managed_installs registry and project the LXC update
    state into a quick lookup ``{vmid: {available, count, security_count,
    last_check, packages[]}}``. Used to decorate ``/api/vms`` output
    without forcing the frontend to fetch a second endpoint.

    Returns an empty dict if the registry module isn't available or
    nothing is registered — callers must treat absence as "no info".
    """
    try:
        import managed_installs
    except Exception:
        return {}
    try:
        active = managed_installs.get_active_items() or []
    except Exception:
        return {}

    out: dict = {}
    for it in active:
        if it.get('type') != 'lxc':
            continue
        vmid = it.get('_vmid') or it.get('id', '').removeprefix('lxc:')
        if not vmid:
            continue
        update = it.get('update_check') or {}
        out[str(vmid)] = {
            'available': bool(update.get('available')),
            'count': int(update.get('_count') or 0),
            'security_count': int(update.get('_security_count') or 0),
            'last_check': update.get('last_check'),
            'latest': update.get('latest'),
            'error': update.get('error'),
            # Cap packages list shipped to UI — modal uses first 30 max
            'packages': (update.get('_packages') or [])[:30],
        }
    return out


def get_proxmox_vms():
    """Get Proxmox VM and LXC information (requires pvesh command) - only from local node"""
    try:
        all_vms = []
        lxc_updates_map = _get_lxc_update_status_map()

        try:
            # local_node = socket.gethostname()
            local_node = get_proxmox_node_name()
            # print(f"[v0] Local node detected: {local_node}")

            resources = get_cached_pvesh_cluster_resources_vm()
            if resources:
                for resource in resources:
                    node = resource.get('node', '')
                    if node != local_node:
                        # print(f"[v0] Skipping VM {resource.get('vmid')} from remote node: {node}")
                        continue

                    vm_type = 'lxc' if resource.get('type') == 'lxc' else 'qemu'
                    vm_data = {
                        'vmid': resource.get('vmid'),
                        'name': resource.get('name', f"VM-{resource.get('vmid')}"),
                        'status': resource.get('status', 'unknown'),
                        'type': vm_type,
                        'cpu': resource.get('cpu', 0),
                        'mem': resource.get('mem', 0),
                        'maxmem': resource.get('maxmem', 0),
                        'disk': resource.get('disk', 0),
                        'maxdisk': resource.get('maxdisk', 0),
                        'uptime': resource.get('uptime', 0),
                        'netin': resource.get('netin', 0),
                        'netout': resource.get('netout', 0),
                        'diskread': resource.get('diskread', 0),
                        'diskwrite': resource.get('diskwrite', 0)
                    }
                    # Decorate LXC rows with the apt update status if the
                    # managed_installs registry has it. Absent key means
                    # either the user hasn't enabled the feature or the
                    # CT isn't running / isn't Debian/Ubuntu.
                    if vm_type == 'lxc':
                        upd = lxc_updates_map.get(str(resource.get('vmid')))
                        if upd is not None:
                            vm_data['update_check'] = upd
                    all_vms.append(vm_data)

                return all_vms
            else:
                # Return empty array instead of error object - frontend expects array
                return []
        except Exception as e:
            # print(f"[v0] Error getting VM/LXC info: {e}")
            pass
            # Return empty array instead of error object - frontend expects array
            return []
    except Exception as e:
        # print(f"Error getting VM info: {e}")
        pass
        # Return empty array instead of error object - frontend expects array
        return []

def get_cached_ipmi_sensors():
    """Get ipmitool sensor output with 10s cache. Shared between fans/power parsers.

    Returns empty string if ipmitool is unavailable (cached to avoid repeated FileNotFoundError).
    """
    global _ipmi_cache
    now = time.time()

    if _ipmi_cache['unavailable']:
        return ''

    if _ipmi_cache['output'] is not None and \
       now - _ipmi_cache['time'] < _IPMI_CACHE_TTL:
        return _ipmi_cache['output']

    try:
        result = subprocess.run(['ipmitool', 'sensor'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            _ipmi_cache['output'] = result.stdout
            _ipmi_cache['time'] = now
            return result.stdout
    except FileNotFoundError:
        _ipmi_cache['unavailable'] = True
        return ''
    except Exception:
        pass
    return _ipmi_cache['output'] or ''


def get_ipmi_fans():
    """Get fan information from IPMI (uses cached sensor output)."""
    fans = []
    try:
        output = get_cached_ipmi_sensors()
        if output:
            for line in output.split('\n'):
                if 'fan' in line.lower() and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        name = parts[0]
                        value_str = parts[1]
                        unit = parts[2] if len(parts) > 2 else ''
                        
                        # Skip "DutyCycle" and "Presence" entries
                        if 'dutycycle' in name.lower() or 'presence' in name.lower():
                            continue
                        
                        try:
                            value = float(value_str)
                            fans.append({
                                'name': name,
                                'speed': value,
                                'unit': unit
                            })
                            # print(f"[v0] IPMI Fan: {name} = {value} {unit}")
                            pass
                        except ValueError:
                            continue
        
        # print(f"[v0] Found {len(fans)} IPMI fans")
        pass
    except FileNotFoundError:
        # print("[v0] ipmitool not found")
        pass
    except Exception as e:
        # print(f"[v0] Error getting IPMI fans: {e}")
        pass
    
    return fans

def get_ipmi_power():
    """Get power supply information from IPMI (uses cached sensor output)."""
    power_supplies = []
    power_meter = None

    try:
        output = get_cached_ipmi_sensors()
        if output:
            for line in output.split('\n'):
                if ('power supply' in line.lower() or 'power meter' in line.lower()) and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        name = parts[0]
                        value_str = parts[1]
                        unit = parts[2] if len(parts) > 2 else ''
                        
                        try:
                            value = float(value_str)
                            
                            if 'power meter' in name.lower():
                                power_meter = {
                                    'name': name,
                                    'watts': value,
                                    'unit': unit
                                }
                                # print(f"[v0] IPMI Power Meter: {value} {unit}")
                                pass
                            else:
                                power_supplies.append({
                                    'name': name,
                                    'watts': value,
                                    'unit': unit,
                                    'status': 'ok' if value > 0 else 'off'
                                })
                                # print(f"[v0] IPMI PSU: {name} = {value} {unit}")
                                pass
                        except ValueError:
                            continue
        
        # print(f"[v0] Found {len(power_supplies)} IPMI power supplies")
        pass
    except FileNotFoundError:
        # print("[v0] ipmitool not found")
        pass
    except Exception as e:
        # print(f"[v0] Error getting IPMI power: {e}")
        pass
    
    return {
        'power_supplies': power_supplies,
        'power_meter': power_meter
    }


# START OF CHANGES FOR get_ups_info
def get_ups_info():
    """Get UPS information from NUT (upsc) - supports both local and remote UPS"""
    ups_list = []
    
    try:
        configured_ups = {}
        try:
            with open('/etc/nut/upsmon.conf', 'r') as f:
                for line in f:
                    line = line.strip()
                    # Look for MONITOR lines: MONITOR ups@host powervalue username password type
                    if line.startswith('MONITOR') and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 2:
                            ups_spec = parts[1]  # Format: upsname@hostname or just upsname
                            if '@' in ups_spec:
                                ups_name, ups_host = ups_spec.split('@', 1)
                                configured_ups[ups_spec] = {
                                    'name': ups_name,
                                    'host': ups_host,
                                    'is_remote': ups_host not in ['localhost', '127.0.0.1', '::1']
                                }
                            else:
                                configured_ups[ups_spec] = {
                                    'name': ups_spec,
                                    'host': 'localhost',
                                    'is_remote': False
                                }
        except FileNotFoundError:
            # print("[v0] /etc/nut/upsmon.conf not found")
            pass
        except Exception as e:
            # print(f"[v0] Error reading upsmon.conf: {e}")
            pass
        
        # Get list of locally available UPS
        local_ups = []
        try:
            result = subprocess.run(['upsc', '-l'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                local_ups = [ups.strip() for ups in result.stdout.strip().split('\n') if ups.strip()]
        except Exception as e:
            # print(f"[v0] Error listing local UPS: {e}")
            pass
        
        all_ups = {}
        
        # Add configured UPS first (priority)
        for ups_spec, ups_info in configured_ups.items():
            ups_name = ups_info['name']
            all_ups[ups_name] = (ups_spec, ups_info['host'], ups_info['is_remote'])
        
        # Add local UPS only if not already in configured list
        for ups_name in local_ups:
            if ups_name not in all_ups:
                all_ups[ups_name] = (ups_name, 'localhost', False)
        
        # Get detailed info for each UPS
        for ups_name, (ups_spec, ups_host, is_remote) in all_ups.items():
            try:
                ups_data = {
                    'name': ups_spec.split('@')[0] if '@' in ups_spec else ups_spec,
                    'host': ups_host,
                    'is_remote': is_remote,
                    'connection_type': 'Remote (NUT)' if is_remote else 'Local'
                }
                
                # Get detailed UPS info using upsc
                cmd = ['upsc', ups_spec] if '@' in ups_spec else ['upsc', ups_spec, ups_host] if is_remote else ['upsc', ups_spec]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Store all UPS variables for detailed modal
                            ups_data[key] = value
                            
                            # Map common variables for quick access
                            if key == 'device.model':
                                ups_data['model'] = value
                            elif key == 'device.mfr':
                                ups_data['manufacturer'] = value
                            elif key == 'device.serial':
                                ups_data['serial'] = value
                            elif key == 'device.type':
                                ups_data['device_type'] = value
                            elif key == 'ups.status':
                                ups_data['status'] = value
                            elif key == 'battery.charge':
                                ups_data['battery_charge'] = f"{value}%"
                                try:
                                    ups_data['battery_charge_raw'] = float(value)
                                except ValueError:
                                    ups_data['battery_charge_raw'] = None
                            elif key == 'battery.runtime':
                                try:
                                    runtime_sec = int(value)
                                    runtime_min = runtime_sec // 60
                                    ups_data['time_left'] = f"{runtime_min} minutes"
                                    ups_data['time_left_seconds'] = runtime_sec
                                except ValueError:
                                    ups_data['time_left'] = value
                                    ups_data['time_left_seconds'] = None
                            elif key == 'battery.voltage':
                                ups_data['battery_voltage'] = f"{value}V"
                            elif key == 'battery.date':
                                ups_data['battery_date'] = value
                            elif key == 'ups.load':
                                ups_data['load_percent'] = f"{value}%"
                                try:
                                    ups_data['load_percent_raw'] = float(value)
                                except ValueError:
                                    ups_data['load_percent_raw'] = None
                            elif key == 'input.voltage':
                                ups_data['input_voltage'] = f"{value}V"
                            elif key == 'input.frequency':
                                ups_data['input_frequency'] = f"{value}Hz"
                            elif key == 'output.voltage':
                                ups_data['output_voltage'] = f"{value}V"
                            elif key == 'output.frequency':
                                ups_data['output_frequency'] = f"{value}Hz"
                            elif key == 'ups.realpower':
                                ups_data['real_power'] = f"{value}W"
                            elif key == 'ups.power':
                                ups_data['apparent_power'] = f"{value}VA"
                            elif key == 'ups.firmware':
                                ups_data['firmware'] = value
                            elif key == 'driver.name':
                                ups_data['driver'] = value
                    
                    ups_list.append(ups_data)
                    # print(f"[v0] UPS found: {ups_data.get('model', 'Unknown')} ({ups_data['connection_type']})")
                    pass
                else:
                    # print(f"[v0] Failed to get info for UPS: {ups_spec}")
                    pass
                    
            except Exception as e:
                # print(f"[v0] Error getting UPS info for {ups_spec}: {e}")
                pass
        
    except FileNotFoundError:
        # print("[v0] upsc not found")
        pass
    except Exception as e:
        # print(f"[v0] Error in get_ups_info: {e}")
        pass
    
    return ups_list
# END OF CHANGES FOR get_ups_info


def identify_temperature_sensor(sensor_name, adapter, chip_name=None):
    """Identify what a temperature sensor corresponds to"""
    sensor_lower = sensor_name.lower()
    adapter_lower = adapter.lower() if adapter else ""
    chip_lower = chip_name.lower() if chip_name else ""
    
    # CPU/Package temperatures
    if "package" in sensor_lower or "tctl" in sensor_lower or "tccd" in sensor_lower:
        return "CPU Package"
    if "core" in sensor_lower:
        core_num = re.search(r'(\d+)', sensor_name)
        return f"CPU Core {core_num.group(1)}" if core_num else "CPU Core"

    if "spd5118" in chip_lower or ("smbus" in adapter_lower and "temp1" in sensor_lower):
        # Try to identify which DIMM slot
        # Example: spd5118-i2c-0-50 -> i2c bus 0, address 0x50 (DIMM A1)
        # Addresses: 0x50=DIMM1, 0x51=DIMM2, 0x52=DIMM3, 0x53=DIMM4, etc.
        dimm_match = re.search(r'i2c-\d+-([0-9a-f]+)', chip_lower)
        if dimm_match:
            i2c_addr = int(dimm_match.group(1), 16)
            dimm_num = (i2c_addr - 0x50) + 1
            return f"DDR5 DIMM {dimm_num}"
        return "DDR5 Memory"   
    
    # Motherboard/Chipset
    if "temp1" in sensor_lower and ("isa" in adapter_lower or "acpi" in adapter_lower):
        return "Motherboard/Chipset"
    if "pch" in sensor_lower or "chipset" in sensor_lower:
        return "Chipset"
    
    # Storage (NVMe, SATA)
    if "nvme" in sensor_lower or "composite" in sensor_lower:
        return "NVMe SSD"
    if "sata" in sensor_lower or "ata" in sensor_lower:
        return "SATA Drive"
    
    # GPU - Enhanced detection using both adapter and chip name
    if any(gpu_driver in (adapter_lower + " " + chip_lower) for gpu_driver in ["nouveau", "amdgpu", "radeon", "i915"]):
        gpu_vendor = None
        
        # Determine GPU vendor from driver
        if "nouveau" in adapter_lower or "nouveau" in chip_lower:
            gpu_vendor = "NVIDIA"
        elif "amdgpu" in adapter_lower or "amdgpu" in chip_lower or "radeon" in adapter_lower or "radeon" in chip_lower:
            gpu_vendor = "AMD"
        elif "i915" in adapter_lower or "i915" in chip_lower:
            gpu_vendor = "Intel"
        
        # Try to get detailed GPU name from lspci if possible
        if gpu_vendor:
            # Extract PCI address from chip name or adapter
            pci_match = re.search(r'pci-([0-9a-f]{4})', adapter_lower + " " + chip_lower)
            
            if pci_match:
                pci_code = pci_match.group(1)
                pci_address = f"{pci_code[0:2]}:{pci_code[2:4]}.0"
                
                # Try to get detailed GPU name from hardware_monitor
                try:
                    gpu_map = hardware_monitor.get_pci_gpu_map()
                    if pci_address in gpu_map:
                        gpu_info = gpu_map[pci_address]
                        return f"GPU {gpu_info['vendor']} {gpu_info['name']}"
                except Exception:
                    pass
            
            # Fallback: return vendor name only
            return f"GPU {gpu_vendor}"
        
        return "GPU"
    
    # Network adapters and other PCI devices
    if "pci" in adapter_lower and "temp" in sensor_lower:
        return "PCI Device"
    
    return sensor_name


def identify_fan(sensor_name, adapter, chip_name=None):
    """Identify what a fan sensor corresponds to, using hardware_monitor for GPU detection"""
    sensor_lower = sensor_name.lower()
    adapter_lower = adapter.lower() if adapter else ""
    chip_lower = chip_name.lower() if chip_name else ""  # Add chip name

    # GPU fans - Check both adapter and chip name for GPU drivers
    if "pci adapter" in adapter_lower or "pci adapter" in chip_lower or any(gpu_driver in adapter_lower + chip_lower for gpu_driver in ["nouveau", "amdgpu", "radeon", "i915"]):
        gpu_vendor = None
        
        # Determine GPU vendor from driver
        if "nouveau" in adapter_lower or "nouveau" in chip_lower:
            gpu_vendor = "NVIDIA"
        elif "amdgpu" in adapter_lower or "amdgpu" in chip_lower or "radeon" in adapter_lower or "radeon" in chip_lower:
            gpu_vendor = "AMD"
        elif "i915" in adapter_lower or "i915" in chip_lower:
            gpu_vendor = "Intel"
        
        # Try to get detailed GPU name from lspci if possible
        if gpu_vendor:
            # Extract PCI address from adapter string
            # Example: "nouveau-pci-0200" -> "02:00.0"
            pci_match = re.search(r'pci-([0-9a-f]{4})', adapter_lower + " " + chip_lower)
            
            if pci_match:
                pci_code = pci_match.group(1)
                pci_address = f"{pci_code[0:2]}:{pci_code[2:4]}.0"
                
                # Try to get detailed GPU name from hardware_monitor
                try:
                    gpu_map = hardware_monitor.get_pci_gpu_map()
                    if pci_address in gpu_map:
                        gpu_info = gpu_map[pci_address]
                        return f"GPU {gpu_info['vendor']} {gpu_info['name']}"
                except Exception:
                    pass
            
            # Fallback: return vendor name only
            return f"GPU {gpu_vendor}"
        
        # Ultimate fallback if vendor detection fails
        return "GPU"
    
    # CPU/System fans - keep original name
    if any(cpu_fan in sensor_lower for cpu_fan in ["cpu_fan", "cpufan", "sys_fan", "sysfan"]):
        return sensor_name
    
    # Chassis fans - keep original name
    if "chassis" in sensor_lower or "case" in sensor_lower:
        return sensor_name
    
    # Default: return original name
    return sensor_name


def _parse_sensor_fans(sensors_output):
    """Parse fan entries from `sensors` output. Extracted for reuse between
    get_hardware_info (static full payload) and get_hardware_live_info (live endpoint)."""
    fans = []
    if not sensors_output:
        return fans
    current_adapter = None
    current_chip = None
    for line in sensors_output.split('\n'):
        line = line.strip()
        if not line:
            continue
        if not ':' in line and not line.startswith(' ') and not line.startswith('Adapter'):
            current_chip = line
            continue
        if line.startswith('Adapter:'):
            current_adapter = line.replace('Adapter:', '').strip()
            continue
        if ':' in line and not line.startswith(' '):
            parts = line.split(':', 1)
            sensor_name = parts[0].strip()
            value_part = parts[1].strip()
            if 'RPM' in value_part:
                rpm_match = re.search(r'([\d.]+)\s*RPM', value_part)
                if rpm_match:
                    fan_speed = int(float(rpm_match.group(1)))
                    identified_name = identify_fan(sensor_name, current_adapter, current_chip)
                    fans.append({
                        'name': identified_name,
                        'original_name': sensor_name,
                        'speed': fan_speed,
                        'unit': 'RPM',
                        'adapter': current_adapter
                    })
    return fans


def get_hardware_live_info():
    """Build only the live/dynamic hardware fields for /api/hardware/live.

    Skips all the heavy static collection (lscpu, dmidecode, lsblk, smartctl, lspci...).
    Uses cached sensors + cached ipmitool output to stay cheap under 5s polling.
    """
    result = {
        'temperatures': [],
        'fans': [],
        'power_meter': None,
        'power_supplies': [],
        'ups': None,
        'coral_tpus': [],
        'usb_devices': [],
    }

    try:
        temp_info = get_temperature_info()
        result['temperatures'] = temp_info.get('temperatures', [])
        result['power_meter'] = temp_info.get('power_meter')
    except Exception:
        pass

    try:
        sensor_fans = _parse_sensor_fans(get_cached_sensors_output())
    except Exception:
        sensor_fans = []

    try:
        ipmi_fans = get_ipmi_fans()
    except Exception:
        ipmi_fans = []

    result['fans'] = sensor_fans + ipmi_fans

    try:
        ipmi_power = get_ipmi_power()
        if ipmi_power:
            result['power_supplies'] = ipmi_power.get('power_supplies', [])
            # Fallback: if sensors didn't provide a power_meter, use IPMI's
            if result['power_meter'] is None and ipmi_power.get('power_meter'):
                result['power_meter'] = ipmi_power['power_meter']
    except Exception:
        pass

    try:
        ups_info = get_ups_info()
        if ups_info:
            result['ups'] = ups_info
    except Exception:
        pass

    # Coral TPU and USB devices are cheap (sysfs reads + cached lsusb) and we
    # want them live so the "Install Drivers" button disappears as soon as the
    # user finishes running install_coral.sh without needing a reload.
    try:
        result['coral_tpus'] = get_coral_info()
    except Exception:
        pass

    try:
        result['usb_devices'] = get_usb_devices()
    except Exception:
        pass

    return result


def get_temperature_info():
    """Get detailed temperature information from sensors command"""
    temperatures = []
    power_meter = None
    
    try:
        sensors_output = get_cached_sensors_output()
        if sensors_output:
            current_adapter = None
            current_chip = None
            current_sensor = None
            
            for line in sensors_output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Detect chip name (e.g., "nouveau-pci-0200")
                if not ':' in line and not line.startswith(' ') and not line.startswith('Adapter'):
                    current_chip = line
                    continue

                # Detect adapter line
                if line.startswith('Adapter:'):
                    current_adapter = line.replace('Adapter:', '').strip()
                    continue

                # Detect sensor name (lines without ':' at the start are sensor names)
                if ':' in line and not line.startswith(' '):
                    parts = line.split(':', 1)
                    sensor_name = parts[0].strip()
                    value_part = parts[1].strip()
                    
                    if 'power' in sensor_name.lower() and 'W' in value_part:
                        try:
                            # Extract power value (e.g., "182.00 W" -> 182.00)
                            power_match = re.search(r'([\d.]+)\s*W', value_part)
                            if power_match:
                                power_value = float(power_match.group(1))
                                power_meter = {
                                    'name': sensor_name,
                                    'watts': power_value,
                                    'adapter': current_adapter
                                }
                                # print(f"[v0] Power meter sensor: {sensor_name} = {power_value}W")
                                pass
                        except ValueError:
                            pass
                    
                    # Parse temperature sensors
                    elif '°C' in value_part or 'C' in value_part:
                        try:
                            # Extract temperature value
                            temp_match = re.search(r'([+-]?[\d.]+)\s*°?C', value_part)
                            if temp_match:
                                temp_value = float(temp_match.group(1))
                                
                                # Extract high and critical values if present
                                high_match = re.search(r'high\s*=\s*([+-]?[\d.]+)', value_part)
                                crit_match = re.search(r'crit\s*=\s*([+-]?[\d.]+)', value_part)
                                
                                high_value = float(high_match.group(1)) if high_match else 0
                                crit_value = float(crit_match.group(1)) if crit_match else 0
                                # Skip internal NVMe sensors (only keep Composite)
                                if current_chip and 'nvme' in current_chip.lower():
                                    sensor_lower_check = sensor_name.lower()
                                    # Skip "Sensor 1", "Sensor 2", "Sensor 8", etc. (keep only "Composite")
                                    if sensor_lower_check.startswith('sensor') and sensor_lower_check.replace('sensor', '').strip().split()[0].isdigit():
                                        continue                                
                                
                                identified_name = identify_temperature_sensor(sensor_name, current_adapter, current_chip)
                                
                                temperatures.append({
                                    'name': identified_name,
                                    'original_name': sensor_name,
                                    'current': temp_value,
                                    'high': high_value,
                                    'critical': crit_value,
                                    'adapter': current_adapter
                                })
                        except ValueError:
                            pass
        
        # print(f"[v0] Found {len(temperatures)} temperature sensors")
        pass
        if power_meter:
            # print(f"[v0] Found power meter: {power_meter['watts']}W")
            pass
            
    except FileNotFoundError:
        # print("[v0] sensors command not found")
        pass
    except Exception as e:
        # print(f"[v0] Error getting temperature info: {e}")
        pass

    if power_meter is None:
        try:
            rapl_power = hardware_monitor.get_power_info()
            if rapl_power:
                power_meter = rapl_power
                # print(f"[v0] Power meter from RAPL: {power_meter.get('watts', 0)}W")
                pass
        except Exception as e:
            # print(f"[v0] Error getting RAPL power info: {e}")
            pass   
    
    
    try:
        hba_temps = hardware_monitor.get_hba_temperatures()
        for hba_temp in hba_temps:
            temperatures.append({
                'name': hba_temp['name'],
                'value': hba_temp['temperature'],
                'adapter': hba_temp['adapter']
            })
    except Exception:
        pass

    return {
        'temperatures': temperatures,
        'power_meter': power_meter
    }


# --- GPU Monitoring Functions ---

def get_detailed_gpu_info(gpu):
    """Get detailed monitoring information for a GPU"""
    vendor = gpu.get('vendor', '').lower()
    slot = gpu.get('slot', '')
    
    # print(f"[v0] ===== get_detailed_gpu_info called for GPU {slot} (vendor: {vendor}) =====", flush=True)
    pass
    
    detailed_info = {
        'has_monitoring_tool': False,
        'temperature': None,
        'fan_speed': None,
        'fan_unit': None,
        'utilization_gpu': None,
        'utilization_memory': None,
        'memory_used': None,
        'memory_total': None,
        'memory_free': None,
        'power_draw': None,
        'power_limit': None,
        'clock_graphics': None,
        'clock_memory': None,
        'processes': [],
        'engine_render': None,
        'engine_blitter': None,
        'engine_video': None,
        'engine_video_enhance': None,
        # Added for NVIDIA/AMD specific engine info if available
        'engine_encoder': None,
        'engine_decoder': None,
        'driver_version': None # Added driver_version
    }
    
    # Intel GPU monitoring with intel_gpu_top
    if 'intel' in vendor:
        # print(f"[v0] Intel GPU detected, checking for intel_gpu_top...", flush=True)
        pass
        
        intel_gpu_top_path = None
        system_paths = ['/usr/bin/intel_gpu_top', '/usr/local/bin/intel_gpu_top']
        for path in system_paths:
            if os.path.exists(path):
                intel_gpu_top_path = path
                # print(f"[v0] Found system intel_gpu_top at: {path}", flush=True)
                pass
                break
        
        # Fallback to shutil.which if not found in system paths
        if not intel_gpu_top_path:
            intel_gpu_top_path = shutil.which('intel_gpu_top')
            if intel_gpu_top_path:
                # print(f"[v0] Using intel_gpu_top from PATH: {intel_gpu_top_path}", flush=True)
                pass
        
        if intel_gpu_top_path:
            # print(f"[v0] intel_gpu_top found, executing...", flush=True)
            pass
            try:
                # print(f"[v0] Current user: {os.getenv('USER', 'unknown')}, UID: {os.getuid()}, GID: {os.getgid()}", flush=True)
                pass
                # print(f"[v0] Current working directory: {os.getcwd()}", flush=True)
                pass
                
                drm_devices = ['/dev/dri/card0', '/dev/dri/renderD128']
                for drm_dev in drm_devices:
                    if os.path.exists(drm_dev):
                        stat_info = os.stat(drm_dev)
                        readable = os.access(drm_dev, os.R_OK)
                        writable = os.access(drm_dev, os.W_OK)
                        # print(f"[v0] {drm_dev}: mode={oct(stat_info.st_mode)}, uid={stat_info.st_uid}, gid={stat_info.st_gid}, readable={readable}, writable={writable}", flush=True)
                        pass
                
                # Prepare environment with all necessary variables
                env = os.environ.copy()
                env['TERM'] = 'xterm'  # Ensure terminal type is set
                
                cmd = f'{intel_gpu_top_path} -J' # Use the found path
                # print(f"[v0] Executing command: {cmd}", flush=True)
                pass
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    shell=True,
                    env=env,
                    cwd='/'  # Ejecutar desde root en lugar de dentro del AppImage
                )
                
                # print(f"[v0] Process started with PID: {process.pid}", flush=True)
                pass
                
                # print(f"[v0] Waiting 1 second for intel_gpu_top to initialize and detect processes...", flush=True)
                pass
                time.sleep(1)
                
                start_time = time.time()
                timeout = 3
                json_objects = []
                buffer = ""
                brace_count = 0
                in_json = False
                
                # print(f"[v0] Reading output from intel_gpu_top...", flush=True)
                pass
                
                while time.time() - start_time < timeout:
                    if process.poll() is not None:
                        # print(f"[v0] Process terminated early with code: {process.poll()}", flush=True)
                        pass
                        break
                    
                    try:
                        # Use non-blocking read with select to avoid hanging
                        ready, _, _ = select.select([process.stdout], [], [], 0.1)
                        if process.stdout in ready:
                            line = process.stdout.readline()
                            if not line:
                                time.sleep(0.01)
                                continue
                        else:
                            time.sleep(0.01)
                            continue

                        for char in line:
                            if char == '{':
                                if brace_count == 0:
                                    in_json = True
                                    buffer = char
                                else:
                                    buffer += char
                                brace_count += 1
                            elif char == '}':
                                buffer += char
                                brace_count -= 1
                                if brace_count == 0 and in_json:
                                    try:
                                        json_data = json.loads(buffer)
                                        json_objects.append(json_data)

                                        
                                        if 'clients' in json_data:
                                            client_count = len(json_data['clients'])
   
                                            for client_id, client_data in json_data['clients']:
                                                client_name = client_data.get('name', 'Unknown')
                                                client_pid = client_data.get('pid', 'Unknown')

                                        else:
                                            # print(f"[v0] No 'clients' key in this JSON object", flush=True)
                                            pass
                                        
                                        if len(json_objects) >= 5:
                                            # print(f"[v0] Collected 5 JSON objects, stopping...", flush=True)
                                            pass
                                            break
                                    except json.JSONDecodeError:
                                        pass
                                    buffer = ""
                                    in_json = False
                            elif in_json:
                                buffer += char
                    except Exception as e:
                        # print(f"[v0] Error reading line: {e}", flush=True)
                        pass
                        break
                
                # Terminate process
                try:
                    process.terminate()
                    _, stderr_output = process.communicate(timeout=0.5) 
                    if stderr_output:
                        # print(f"[v0] intel_gpu_top stderr: {stderr_output}", flush=True)
                        pass
                except subprocess.TimeoutExpired:
                    process.kill()
                    # print("[v0] Process killed after terminate timeout.", flush=True)
                    pass
                except Exception as e:
                    # print(f"[v0] Error during process termination: {e}", flush=True)
                    pass

                # print(f"[v0] Collected {len(json_objects)} JSON objects total", flush=True)
                pass
                
                best_json = None
                
                # First priority: Find JSON with populated clients
                for json_obj in reversed(json_objects):
                    if 'clients' in json_obj:
                        clients_data = json_obj['clients']
                        if clients_data and len(clients_data) > 0:

                            best_json = json_obj
                            break
                
                # Second priority: Use most recent JSON
                if not best_json and json_objects:
                    best_json = json_objects[-1]


                if best_json:

                    data_retrieved = False
                    
                    # Initialize engine totals
                    engine_totals = {
                        'Render/3D': 0.0,
                        'Blitter': 0.0,
                        'Video': 0.0,
                        'VideoEnhance': 0.0
                    }
                    client_engine_totals = {
                        'Render/3D': 0.0,
                        'Blitter': 0.0,
                        'Video': 0.0,
                        'VideoEnhance': 0.0
                    }
                    
                    # Parse clients section (processes using GPU)
                    if 'clients' in best_json:
                        # print(f"[v0] Parsing clients section...", flush=True)
                        pass
                        clients = best_json['clients']
                        processes = []
                        
                        for client_id, client_data in clients.items():
                            process_info = {
                                'name': client_data.get('name', 'Unknown'),
                                'pid': client_data.get('pid', 'Unknown'),
                                'memory': {
                                    'total': client_data.get('memory', {}).get('system', {}).get('total', 0),
                                    'shared': client_data.get('memory', {}).get('system', {}).get('shared', 0),
                                    'resident': client_data.get('memory', {}).get('system', {}).get('resident', 0)
                                },
                                'engines': {}
                            }
                            
                            # Parse engine utilization for this process
                            engine_classes = client_data.get('engine-classes', {})
                            for engine_name, engine_data in engine_classes.items():
                                busy_value = float(engine_data.get('busy', 0))
                                process_info['engines'][engine_name] = f"{busy_value:.1f}%"
                                
                                # Sum up engine utilization across all processes
                                if engine_name in client_engine_totals:
                                    client_engine_totals[engine_name] += busy_value
                            
                            processes.append(process_info)
                            # print(f"[v0] Added process: {process_info['name']} (PID: {process_info['pid']})", flush=True)
                            pass
                        
                        detailed_info['processes'] = processes
                        # print(f"[v0] Total processes found: {len(processes)}", flush=True)
                        pass
                    else:
                        # print(f"[v0] WARNING: No 'clients' section in selected JSON", flush=True)
                        pass
                    
                    # Parse global engines section
                    if 'engines' in best_json:
                        # print(f"[v0] Parsing engines section...", flush=True)
                        pass
                        engines = best_json['engines']
                        
                        for engine_name, engine_data in engines.items():
                            # Remove the /0 suffix if present
                            clean_name = engine_name.replace('/0', '')
                            busy_value = float(engine_data.get('busy', 0))
                            
                            if clean_name in engine_totals:
                                engine_totals[clean_name] = busy_value
                    
                    # Use client engine totals if available, otherwise use global engines
                    final_engines = client_engine_totals if any(v > 0 for v in client_engine_totals.values()) else engine_totals
                    
                    detailed_info['engine_render'] = f"{final_engines['Render/3D']:.1f}%"
                    detailed_info['engine_blitter'] = f"{final_engines['Blitter']:.1f}%"
                    detailed_info['engine_video'] = f"{final_engines['Video']:.1f}%"
                    detailed_info['engine_video_enhance'] = f"{final_engines['VideoEnhance']:.1f}%"
                    
                    # Calculate overall GPU utilization (max of all engines)
                    max_utilization = max(final_engines.values())
                    detailed_info['utilization_gpu'] = f"{max_utilization:.1f}%"
                    
                    # Parse frequency
                    if 'frequency' in best_json:
                        freq_data = best_json['frequency']
                        actual_freq = freq_data.get('actual', 0)
                        detailed_info['clock_graphics'] = f"{actual_freq} MHz"
                        data_retrieved = True
                    
                    # Parse power
                    if 'power' in best_json:
                        power_data = best_json['power']
                        gpu_power = power_data.get('GPU', 0)
                        package_power = power_data.get('Package', 0)
                        # Use Package power as the main power draw since GPU is always 0.0 for integrated GPUs
                        detailed_info['power_draw'] = f"{package_power:.2f} W"
                        # Keep power_limit as a separate field (could be used for TDP limit in the future)
                        detailed_info['power_limit'] = f"{package_power:.2f} W"
                        data_retrieved = True
                    
                    if data_retrieved:
                        detailed_info['has_monitoring_tool'] = True
                        # print(f"[v0] Intel GPU monitoring successful", flush=True)
                        pass
                        # print(f"[v0] - Utilization: {detailed_info['utilization_gpu']}", flush=True)
                        pass
                        # print(f"[v0] - Engines: R={detailed_info['engine_render']}, B={detailed_info['engine_blitter']}, V={detailed_info['engine_video']}, VE={detailed_info['engine_video_enhance']}", flush=True)
                        pass
                        # print(f"[v0] - Processes: {len(detailed_info['processes'])}", flush=True)
                        pass
                        
                        if len(detailed_info['processes']) == 0:
                            # print(f"[v0] No processes found in JSON, trying text output...", flush=True)
                            pass
                            text_processes = get_intel_gpu_processes_from_text()
                            if text_processes:
                                detailed_info['processes'] = text_processes
                                # print(f"[v0] Found {len(text_processes)} processes from text output", flush=True)
                                pass
                    else:
                        # print(f"[v0] WARNING: No data retrieved from intel_gpu_top", flush=True)
                        pass
                else:
                    # print(f"[v0] WARNING: No valid JSON objects found", flush=True)
                    pass
                    # CHANGE: Evitar bloqueo al leer stderr - usar communicate() con timeout
                    try:
                        # Use communicate() with timeout instead of read() to avoid blocking
                        _, stderr_output = process.communicate(timeout=0.5)
                        if stderr_output:
                            # print(f"[v0] intel_gpu_top stderr: {stderr_output}", flush=True)
                            pass
                    except subprocess.TimeoutExpired:
                        process.kill()
                        # print(f"[v0] Process killed after timeout", flush=True)
                        pass
                    except Exception as e:
                        # print(f"[v0] Error reading stderr: {e}", flush=True)
                        pass
            
            except Exception as e:
                # print(f"[v0] Error running intel_gpu_top: {e}", flush=True)
                pass
                import traceback
                traceback.print_exc()
        else:
            # print(f"[v0] intel_gpu_top not found in PATH", flush=True)
            pass
            # Fallback to text parsing if JSON parsing fails or -J is not available
            # print("[v0] Trying intel_gpu_top text output for process parsing...", flush=True)
            pass
            detailed_info['processes'] = get_intel_gpu_processes_from_text()
            if detailed_info['processes']:
                detailed_info['has_monitoring_tool'] = True
                # print(f"[v0] Intel GPU process monitoring (text mode) successful.", flush=True)
                pass
            else:
                # print(f"[v0] Intel GPU process monitoring (text mode) failed.", flush=True)
                pass

    # NVIDIA GPU monitoring with nvidia-smi
    elif 'nvidia' in vendor:
        # print(f"[v0] NVIDIA GPU detected, checking for nvidia-smi...", flush=True)
        pass
        if shutil.which('nvidia-smi'):
            # print(f"[v0] nvidia-smi found, executing with XML output...", flush=True)
            pass
            try:
                cmd = ['nvidia-smi', '-q', '-x']
                # print(f"[v0] Executing command: {' '.join(cmd)}", flush=True)
                pass
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0 and result.stdout.strip():
                    # print(f"[v0] nvidia-smi XML output received, parsing...", flush=True)
                    pass
                    
                    try:
                        # Parse XML
                        root = ET.fromstring(result.stdout)
                        
                        # Get first GPU (assuming single GPU or taking first one)
                        gpu_elem = root.find('gpu')
                        
                        if gpu_elem is not None:
                            # print(f"[v0] Processing NVIDIA GPU XML data...", flush=True)
                            pass
                            data_retrieved = False
                            
                            driver_version_elem = gpu_elem.find('.//driver_version')
                            if driver_version_elem is not None and driver_version_elem.text:
                                detailed_info['driver_version'] = driver_version_elem.text.strip()
                                # print(f"[v0] Driver Version: {detailed_info['driver_version']}", flush=True)
                                pass
                            
                            # Parse temperature
                            temp_elem = gpu_elem.find('.//temperature/gpu_temp')
                            if temp_elem is not None and temp_elem.text:
                                try:
                                    # Remove ' C' suffix and convert to int
                                    temp_str = temp_elem.text.replace(' C', '').strip()
                                    detailed_info['temperature'] = int(temp_str)
                                    # print(f"[v0] Temperature: {detailed_info['temperature']}°C", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse fan speed
                            fan_elem = gpu_elem.find('.//fan_speed')
                            if fan_elem is not None and fan_elem.text and fan_elem.text != 'N/A':
                                try:
                                    # Remove ' %' suffix and convert to int
                                    fan_str = fan_elem.text.replace(' %', '').strip()
                                    detailed_info['fan_speed'] = int(fan_str)
                                    detailed_info['fan_unit'] = '%'
                                    # print(f"[v0] Fan Speed: {detailed_info['fan_speed']}%", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse power draw
                            power_elem = gpu_elem.find('.//gpu_power_readings/power_state')
                            instant_power_elem = gpu_elem.find('.//gpu_power_readings/instant_power_draw')
                            if instant_power_elem is not None and instant_power_elem.text and instant_power_elem.text != 'N/A':
                                try:
                                    # Remove ' W' suffix and convert to float
                                    power_str = instant_power_elem.text.replace(' W', '').strip()
                                    detailed_info['power_draw'] = float(power_str)
                                    # print(f"[v0] Power Draw: {detailed_info['power_draw']} W", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse power limit
                            power_limit_elem = gpu_elem.find('.//gpu_power_readings/current_power_limit')
                            if power_limit_elem is not None and power_limit_elem.text and power_limit_elem.text != 'N/A':
                                try:
                                    power_limit_str = power_limit_elem.text.replace(' W', '').strip()
                                    detailed_info['power_limit'] = float(power_limit_str)
                                    # print(f"[v0] Power Limit: {detailed_info['power_limit']} W", flush=True)
                                    pass
                                except ValueError:
                                    pass
                            
                            # Parse GPU utilization
                            gpu_util_elem = gpu_elem.find('.//utilization/gpu_util')
                            if gpu_util_elem is not None and gpu_util_elem.text:
                                try:
                                    util_str = gpu_util_elem.text.replace(' %', '').strip()
                                    detailed_info['utilization_gpu'] = int(util_str)
                                    # print(f"[v0] GPU Utilization: {detailed_info['utilization_gpu']}%", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse memory utilization
                            mem_util_elem = gpu_elem.find('.//utilization/memory_util')
                            if mem_util_elem is not None and mem_util_elem.text:
                                try:
                                    mem_util_str = mem_util_elem.text.replace(' %', '').strip()
                                    detailed_info['utilization_memory'] = int(mem_util_str)
                                    # print(f"[v0] Memory Utilization: {detailed_info['utilization_memory']}%", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse encoder utilization
                            encoder_util_elem = gpu_elem.find('.//utilization/encoder_util')
                            if encoder_util_elem is not None and encoder_util_elem.text and encoder_util_elem.text != 'N/A':
                                try:
                                    encoder_str = encoder_util_elem.text.replace(' %', '').strip()
                                    detailed_info['engine_encoder'] = int(encoder_str)
                                    # print(f"[v0] Encoder Utilization: {detailed_info['engine_encoder']}%", flush=True)
                                    pass
                                except ValueError:
                                    pass
                            
                            # Parse decoder utilization
                            decoder_util_elem = gpu_elem.find('.//utilization/decoder_util')
                            if decoder_util_elem is not None and decoder_util_elem.text and decoder_util_elem.text != 'N/A':
                                try:
                                    decoder_str = decoder_util_elem.text.replace(' %', '').strip()
                                    detailed_info['engine_decoder'] = int(decoder_str)
                                    # print(f"[v0] Decoder Utilization: {detailed_info['engine_decoder']}%", flush=True)
                                    pass
                                except ValueError:
                                    pass
                            
                            # Parse clocks
                            graphics_clock_elem = gpu_elem.find('.//clocks/graphics_clock')
                            if graphics_clock_elem is not None and graphics_clock_elem.text:
                                try:
                                    clock_str = graphics_clock_elem.text.replace(' MHz', '').strip()
                                    detailed_info['clock_graphics'] = int(clock_str)
                                    # print(f"[v0] Graphics Clock: {detailed_info['clock_graphics']} MHz", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            mem_clock_elem = gpu_elem.find('.//clocks/mem_clock')
                            if mem_clock_elem is not None and mem_clock_elem.text:
                                try:
                                    mem_clock_str = mem_clock_elem.text.replace(' MHz', '').strip()
                                    detailed_info['clock_memory'] = int(mem_clock_str)
                                    # print(f"[v0] Memory Clock: {detailed_info['clock_memory']} MHz", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            # Parse memory usage
                            mem_total_elem = gpu_elem.find('.//fb_memory_usage/total')
                            if mem_total_elem is not None and mem_total_elem.text:
                                try:
                                    mem_total_str = mem_total_elem.text.replace(' MiB', '').strip()
                                    detailed_info['memory_total'] = int(mem_total_str)
                                    # print(f"[v0] Memory Total: {detailed_info['memory_total']} MB", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            mem_used_elem = gpu_elem.find('.//fb_memory_usage/used')
                            if mem_used_elem is not None and mem_used_elem.text:
                                try:
                                    mem_used_str = mem_used_elem.text.replace(' MiB', '').strip()
                                    detailed_info['memory_used'] = int(mem_used_str)
                                    # print(f"[v0] Memory Used: {detailed_info['memory_used']} MB", flush=True)
                                    pass
                                    data_retrieved = True
                                except ValueError:
                                    pass
                            
                            mem_free_elem = gpu_elem.find('.//fb_memory_usage/free')
                            if mem_free_elem is not None and mem_free_elem.text:
                                try:
                                    mem_free_str = mem_free_elem.text.replace(' MiB', '').strip()
                                    detailed_info['memory_free'] = int(mem_free_str)
                                    # print(f"[v0] Memory Free: {detailed_info['memory_free']} MB", flush=True)
                                    pass
                                except ValueError:
                                    pass
                            
                            if (detailed_info['utilization_memory'] is None or detailed_info['utilization_memory'] == 0) and \
                               detailed_info['memory_used'] is not None and detailed_info['memory_total'] is not None and \
                               detailed_info['memory_total'] > 0:
                                mem_util = (detailed_info['memory_used'] / detailed_info['memory_total']) * 100
                                detailed_info['utilization_memory'] = round(mem_util, 1)
                                # print(f"[v0] Memory Utilization (calculated): {detailed_info['utilization_memory']}%", flush=True)
                                pass
                            
                            # Parse processes
                            processes_elem = gpu_elem.find('.//processes')
                            if processes_elem is not None:
                                processes = []
                                for process_elem in processes_elem.findall('process_info'):
                                    try:
                                        pid_elem = process_elem.find('pid')
                                        name_elem = process_elem.find('process_name')
                                        mem_elem = process_elem.find('used_memory')
                                        type_elem = process_elem.find('type')
                                        
                                        if pid_elem is not None and name_elem is not None and mem_elem is not None:
                                            pid = pid_elem.text.strip()
                                            name = name_elem.text.strip()
                                            
                                            # Parse memory (format: "362 MiB")
                                            mem_str = mem_elem.text.replace(' MiB', '').strip()
                                            memory_mb = int(mem_str)
                                            
                                            memory_kb = memory_mb * 1024
                                            
                                            # Get process type (C=Compute, G=Graphics)
                                            proc_type = type_elem.text.strip() if type_elem is not None else 'C'
                                            
                                            process_info = {
                                                'pid': pid,
                                                'name': name,
                                                'memory': memory_kb,  # Now in KB instead of MB
                                                'engines': {}  # Leave engines empty for NVIDIA since we don't have per-process utilization
                                            }
                                            
                                            # The process type (C/G) is informational only
                                            
                                            processes.append(process_info)
                                            # print(f"[v0] Found process: {name} (PID: {pid}, Memory: {memory_mb} MB)", flush=True)
                                            pass
                                    except (ValueError, AttributeError) as e:
                                        # print(f"[v0] Error parsing process: {e}", flush=True)
                                        pass
                                        continue
                                
                                detailed_info['processes'] = processes
                                # print(f"[v0] Found {len(processes)} NVIDIA GPU processes", flush=True)
                                pass
                            
                            if data_retrieved:
                                detailed_info['has_monitoring_tool'] = True
                                # print(f"[v0] NVIDIA GPU monitoring successful", flush=True)
                                pass
                            else:
                                # print(f"[v0] NVIDIA GPU monitoring failed - no data retrieved", flush=True)
                                pass
                        else:
                            # print(f"[v0] No GPU element found in XML", flush=True)
                            pass
                    
                    except ET.ParseError as e:
                        # print(f"[v0] Error parsing nvidia-smi XML: {e}", flush=True)
                        pass
                        import traceback
                        traceback.print_exc()
                else:
                    # print(f"[v0] nvidia-smi returned error or empty output", flush=True)
                    pass

            except subprocess.TimeoutExpired:
                # print(f"[v0] nvidia-smi timed out - marking tool as unavailable", flush=True)
                pass
            except Exception as e:
                # print(f"[v0] Error running nvidia-smi: {e}", flush=True)
                pass
                import traceback
                traceback.print_exc()
        else:
            # print(f"[v0] nvidia-smi not found in PATH", flush=True)
            pass

    # AMD GPU monitoring (placeholder, requires radeontop or similar)
    elif 'amd' in vendor:
        # print(f"[v0] AMD GPU detected, checking for amdgpu_top...", flush=True)
        pass
        
        amdgpu_top_path = shutil.which('amdgpu_top')
        
        if amdgpu_top_path:
            # print(f"[v0] amdgpu_top found at: {amdgpu_top_path}, executing...", flush=True)
            pass
            try:
                # Execute amdgpu_top with JSON output and single snapshot
                cmd = [amdgpu_top_path, '--json', '-n', '1']
                # print(f"[v0] Executing command: {' '.join(cmd)}", flush=True)
                pass
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    # print(f"[v0] amdgpu_top output received, parsing JSON...", flush=True)
                    pass
                    
                    try:
                        amd_data = json.loads(result.stdout)
                        # print(f"[v0] JSON parsed successfully", flush=True)
                        pass
                        
                        # Check if we have devices array
                        if 'devices' in amd_data and len(amd_data['devices']) > 0:
                            device = amd_data['devices'][0]  # Get first device
                            # print(f"[v0] Processing AMD GPU device data...", flush=True)
                            pass
                            
                            data_retrieved = False
                            
                            # CHANGE: Initialize sensors variable to None to avoid UnboundLocalError
                            sensors = None
                            
                            # Parse temperature (Edge Temperature from sensors)
                            if 'sensors' in device:
                                sensors = device['sensors']
                                if 'Edge Temperature' in sensors:
                                    edge_temp = sensors['Edge Temperature']
                                    if 'value' in edge_temp:
                                        detailed_info['temperature'] = int(edge_temp['value'])
                                        # print(f"[v0] Temperature: {detailed_info['temperature']}°C", flush=True)
                                        pass
                                        data_retrieved = True
                            
                            # CHANGE: Added check to ensure sensors is not None before accessing
                            # Parse power draw (GFX Power or average_socket_power)
                            if sensors and 'GFX Power' in sensors:
                                gfx_power = sensors['GFX Power']
                                if 'value' in gfx_power:
                                    detailed_info['power_draw'] = f"{gfx_power['value']:.2f} W"
                                    # print(f"[v0] Power Draw: {detailed_info['power_draw']}", flush=True)
                                    pass
                                    data_retrieved = True
                            elif sensors and 'average_socket_power' in sensors:
                                socket_power = sensors['average_socket_power']
                                if 'value' in socket_power:
                                    detailed_info['power_draw'] = f"{socket_power['value']:.2f} W"
                                    # print(f"[v0] Power Draw: {detailed_info['power_draw']}", flush=True)
                                    pass
                                    data_retrieved = True
                            
                            # Parse clocks (GFX_SCLK for graphics, GFX_MCLK for memory)
                            if 'Clocks' in device:
                                clocks = device['Clocks']
                                if 'GFX_SCLK' in clocks:
                                    gfx_clock = clocks['GFX_SCLK']
                                    if 'value' in gfx_clock:
                                        detailed_info['clock_graphics'] = f"{gfx_clock['value']} MHz"
                                        # print(f"[v0] Graphics Clock: {detailed_info['clock_graphics']} MHz", flush=True)
                                        pass
                                        data_retrieved = True
                                
                                if 'GFX_MCLK' in clocks:
                                    mem_clock = clocks['GFX_MCLK']
                                    if 'value' in mem_clock:
                                        detailed_info['clock_memory'] = f"{mem_clock['value']} MHz"
                                        # print(f"[v0] Memory Clock: {detailed_info['clock_memory']} MHz", flush=True)
                                        pass
                                        data_retrieved = True
                            
                            # Parse GPU activity (gpu_activity.GFX)
                            if 'gpu_activity' in device:
                                gpu_activity = device['gpu_activity']
                                if 'GFX' in gpu_activity:
                                    gfx_activity = gpu_activity['GFX']
                                    if 'value' in gfx_activity:
                                        utilization = gfx_activity['value']
                                        detailed_info['utilization_gpu'] = f"{utilization:.1f}%"
                                        detailed_info['engine_render'] = f"{utilization:.1f}%"
                                        # print(f"[v0] GPU Utilization: {detailed_info['utilization_gpu']}", flush=True)
                                        pass
                                        data_retrieved = True
                            
                            # Parse VRAM usage
                            if 'VRAM' in device:
                                vram = device['VRAM']
                                if 'Total VRAM Usage' in vram:
                                    total_usage = vram['Total VRAM Usage']
                                    if 'value' in total_usage:
                                        # Value is in MB
                                        mem_used_mb = int(total_usage['value'])
                                        detailed_info['memory_used'] = f"{mem_used_mb} MB"
                                        # print(f"[v0] VRAM Used: {detailed_info['memory_used']}", flush=True)
                                        pass
                                        data_retrieved = True
                                
                                if 'Total VRAM' in vram:
                                    total_vram = vram['Total VRAM']
                                    if 'value' in total_vram:
                                        # Value is in MB
                                        mem_total_mb = int(total_vram['value'])
                                        detailed_info['memory_total'] = f"{mem_total_mb} MB"
                                        
                                        # Calculate free memory
                                        if detailed_info['memory_used']:
                                            mem_used_mb = int(detailed_info['memory_used'].replace(' MB', ''))
                                            mem_free_mb = mem_total_mb - mem_used_mb
                                            detailed_info['memory_free'] = f"{mem_free_mb} MB"
                                        
                                        # print(f"[v0] VRAM Total: {detailed_info['memory_total']}", flush=True)
                                        pass
                                        data_retrieved = True
                            
                            # Calculate memory utilization percentage
                            if detailed_info['memory_used'] and detailed_info['memory_total']:
                                mem_used = int(detailed_info['memory_used'].replace(' MB', ''))
                                mem_total = int(detailed_info['memory_total'].replace(' MB', ''))
                                if mem_total > 0:
                                    mem_util = (mem_used / mem_total) * 100
                                    detailed_info['utilization_memory'] = round(mem_util, 1)
                                    # print(f"[v0] Memory Utilization: {detailed_info['utilization_memory']}%", flush=True)
                                    pass
                            
                            # Parse GRBM (Graphics Register Bus Manager) for engine utilization
                            if 'GRBM' in device:
                                grbm = device['GRBM']
                                
                                # Graphics Pipe (similar to Render/3D)
                                if 'Graphics Pipe' in grbm:
                                    gfx_pipe = grbm['Graphics Pipe']
                                    if 'value' in gfx_pipe:
                                        detailed_info['engine_render'] = f"{gfx_pipe['value']:.1f}%"
                            
                            # Parse GRBM2 for additional engine info
                            if 'GRBM2' in device:
                                grbm2 = device['GRBM2']
                                
                                # Texture Cache (similar to Blitter)
                                if 'Texture Cache' in grbm2:
                                    tex_cache = grbm2['Texture Cache']
                                    if 'value' in tex_cache:
                                        detailed_info['engine_blitter'] = f"{tex_cache['value']:.1f}%"
                            
                            # Parse processes (fdinfo)
                            if 'fdinfo' in device:
                                fdinfo = device['fdinfo']
                                processes = []
                                
                                # print(f"[v0] Parsing fdinfo with {len(fdinfo)} entries", flush=True)
                                pass
                                
                                # CHANGE: Corregir parseo de fdinfo con estructura anidada
                                # fdinfo es un diccionario donde las claves son los PIDs (como strings)
                                for pid_str, proc_data in fdinfo.items():
                                    try:
                                        process_info = {
                                            'name': proc_data.get('name', 'Unknown'),
                                            'pid': pid_str,  # El PID ya es la clave
                                            'memory': {},
                                            'engines': {}
                                        }
                                        
                                        # print(f"[v0] Processing fdinfo entry: PID={pid_str}, Name={process_info['name']}", flush=True)
                                        pass
                                        
                                        # La estructura real es: proc_data -> usage -> usage -> datos
                                        # Acceder al segundo nivel de 'usage'
                                        usage_outer = proc_data.get('usage', {})
                                        usage_data = usage_outer.get('usage', {})
                                        
                                        # print(f"[v0]   Usage data keys: {list(usage_data.keys())}", flush=True)
                                        pass
                                        
                                        # Parse VRAM usage for this process (está dentro de usage.usage)
                                        if 'VRAM' in usage_data:
                                            vram_data = usage_data['VRAM']
                                            if isinstance(vram_data, dict) and 'value' in vram_data:
                                                vram_mb = vram_data['value']
                                                process_info['memory'] = {
                                                    'total': int(vram_mb * 1024 * 1024),  # MB to bytes
                                                    'shared': 0,
                                                    'resident': int(vram_mb * 1024 * 1024)
                                                }
                                                # print(f"[v0]     VRAM: {vram_mb} MB", flush=True)
                                                pass
                                        
                                        # Parse GTT (Graphics Translation Table) usage (está dentro de usage.usage)
                                        if 'GTT' in usage_data:
                                            gtt_data = usage_data['GTT']
                                            if isinstance(gtt_data, dict) and 'value' in gtt_data:
                                                gtt_mb = gtt_data['value']
                                                # Add GTT to total memory if not already counted
                                                if 'total' not in process_info['memory']:
                                                    process_info['memory']['total'] = int(gtt_mb * 1024 * 1024)
                                                else:
                                                    # Add GTT to existing VRAM
                                                    process_info['memory']['total'] += int(gtt_mb * 1024 * 1024)
                                                # print(f"[v0]     GTT: {gtt_mb} MB", flush=True)
                                                pass
                                        
                                        # Parse engine utilization for this process (están dentro de usage.usage)
                                        # GFX (Graphics/Render)
                                        if 'GFX' in usage_data:
                                            gfx_usage = usage_data['GFX']
                                            if isinstance(gfx_usage, dict) and 'value' in gfx_usage:
                                                val = gfx_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Render/3D'] = f"{val:.1f}%"
                                                    # print(f"[v0]     GFX: {val}%", flush=True)
                                                    pass
                                        
                                        # Compute
                                        if 'Compute' in usage_data:
                                            comp_usage = usage_data['Compute']
                                            if isinstance(comp_usage, dict) and 'value' in comp_usage:
                                                val = comp_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Compute'] = f"{val:.1f}%"
                                                    # print(f"[v0]     Compute: {val}%", flush=True)
                                                    pass
                                        
                                        # DMA (Direct Memory Access)
                                        if 'DMA' in usage_data:
                                            dma_usage = usage_data['DMA']
                                            if isinstance(dma_usage, dict) and 'value' in dma_usage:
                                                val = dma_usage['value']
                                                if val > 0:
                                                    process_info['engines']['DMA'] = f"{val:.1f}%"
                                                    # print(f"[v0]     DMA: {val}%", flush=True)
                                                    pass
                                        
                                        # Decode (Video Decode)
                                        if 'Decode' in usage_data:
                                            dec_usage = usage_data['Decode']
                                            if isinstance(dec_usage, dict) and 'value' in dec_usage:
                                                val = dec_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Video'] = f"{val:.1f}%"
                                                    # print(f"[v0]     Decode: {val}%", flush=True)
                                                    pass
                                        
                                        # Encode (Video Encode)
                                        if 'Encode' in usage_data:
                                            enc_usage = usage_data['Encode']
                                            if isinstance(enc_usage, dict) and 'value' in enc_usage:
                                                val = enc_usage['value']
                                                if val > 0:
                                                    process_info['engines']['VideoEncode'] = f"{val:.1f}%"
                                                    # print(f"[v0]     Encode: {val}%", flush=True)
                                                    pass
                                        
                                        # Media (Media Engine)
                                        if 'Media' in usage_data:
                                            media_usage = usage_data['Media']
                                            if isinstance(media_usage, dict) and 'value' in media_usage:
                                                val = media_usage['value']
                                                if val > 0:
                                                    process_info['engines']['Media'] = f"{val:.1f}%"
                                                    # print(f"[v0]     Media: {val}%", flush=True)
                                                    pass
                                        
                                        # CPU (CPU usage by GPU driver)
                                        if 'CPU' in usage_data:
                                            cpu_usage = usage_data['CPU']
                                            if isinstance(cpu_usage, dict) and 'value' in cpu_usage:
                                                val = cpu_usage['value']
                                                if val > 0:
                                                    process_info['engines']['CPU'] = f"{val:.1f}%"
                                                    # print(f"[v0]     CPU: {val}%", flush=True)
                                                    pass
                                        
                                        # VCN_JPEG (JPEG Decode)
                                        if 'VCN_JPEG' in usage_data:
                                            jpeg_usage = usage_data['VCN_JPEG']
                                            if isinstance(jpeg_usage, dict) and 'value' in jpeg_usage:
                                                val = jpeg_usage['value']
                                                if val > 0:
                                                    process_info['engines']['JPEG'] = f"{val:.1f}%"
                                                    # print(f"[v0]     VCN_JPEG: {val}%", flush=True)
                                                    pass
                                        
                                        # Add the process even if it has no active engines at this moment
                                        # (may have allocated memory but is not actively using the GPU)
                                        if process_info['memory'] or process_info['engines']:
                                            processes.append(process_info)
                                            # print(f"[v0] Added AMD GPU process: {process_info['name']} (PID: {process_info['pid']}) - Memory: {process_info['memory']}, Engines: {process_info['engines']}", flush=True)
                                            pass
                                        else:
                                            # print(f"[v0] Skipped process {process_info['name']} - no memory or engine usage", flush=True)
                                            pass
                                    
                                    except Exception as e:
                                        # print(f"[v0] Error parsing fdinfo entry for PID {pid_str}: {e}", flush=True)
                                        pass
                                        import traceback
                                        traceback.print_exc()
                                
                                detailed_info['processes'] = processes
                                # print(f"[v0] Total AMD GPU processes: {len(processes)}", flush=True)
                                pass
                            else:
                                # print(f"[v0] No fdinfo section found in device data", flush=True)
                                pass
                            
                            if data_retrieved:
                                detailed_info['has_monitoring_tool'] = True
                                # print(f"[v0] AMD GPU monitoring successful", flush=True)
                                pass
                            else:
                                # print(f"[v0] WARNING: No data retrieved from amdgpu_top", flush=True)
                                pass
                        else:
                            # print(f"[v0] WARNING: No devices found in amdgpu_top output", flush=True)
                            pass
                    
                    except json.JSONDecodeError as e:
                        # print(f"[v0] Error parsing amdgpu_top JSON: {e}", flush=True)
                        pass
                        # print(f"[v0] Raw output: {result.stdout[:500]}", flush=True)
                        pass
            
            except subprocess.TimeoutExpired:
                # print(f"[v0] amdgpu_top timed out", flush=True)
                pass
            except Exception as e:
                # print(f"[v0] Error running amdgpu_top: {e}", flush=True)
                pass
                import traceback
                traceback.print_exc()
        else:
            # print(f"[v0] amdgpu_top not found in PATH", flush=True)
            pass
            # print(f"[v0] To enable AMD GPU monitoring, install amdgpu_top:", flush=True)
            pass
            # print(f"[v0]   wget -O amdgpu-top_0.11.0-1_amd64.deb https://github.com/Umio-Yasuno/amdgpu_top/releases/download/v0.11.0/amdgpu-top_0.11.0-1_amd64.deb", flush=True)
            pass
            # print(f"[v0]   apt install ./amdgpu-top_0.11.0-1_amd64.deb", flush=True)
            pass
        
    else:
        # print(f"[v0] Unsupported GPU vendor: {vendor}", flush=True)
        pass

    # print(f"[v0] ===== Exiting get_detailed_gpu_info for GPU {slot} =====", flush=True)
    pass
    return detailed_info


def get_pci_device_info(pci_slot):
    """Get detailed PCI device information for a given slot"""
    pci_info = {}
    try:
        # Use lspci -vmm for detailed information
        result = subprocess.run(['lspci', '-vmm', '-s', pci_slot], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    pci_info[key.strip().lower().replace(' ', '_')] = value.strip()
        
        # Now get driver information with lspci -k
        result_k = subprocess.run(['lspci', '-k', '-s', pci_slot], 
                                capture_output=True, text=True, timeout=5)
        if result_k.returncode == 0:
            for line in result_k.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Kernel driver in use:'):
                    pci_info['driver'] = line.split(':', 1)[1].strip()
                elif line.startswith('Kernel modules:'):
                    pci_info['kernel_module'] = line.split(':', 1)[1].strip()
                    
    except Exception as e:
        # print(f"[v0] Error getting PCI device info for {pci_slot}: {e}")
        pass
    return pci_info

def get_network_hardware_info(pci_slot):
    """Get detailed hardware information for a network interface"""
    net_info = {}
    
    try:
        # Get detailed PCI info
        result = subprocess.run(['lspci', '-v', '-s', pci_slot], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Kernel driver in use:' in line:
                    net_info['driver'] = line.split(':', 1)[1].strip()
                elif 'Kernel modules:' in line:
                    net_info['kernel_modules'] = line.split(':', 1)[1].strip()
                elif 'Subsystem:' in line:
                    net_info['subsystem'] = line.split(':', 1)[1].strip()
                elif 'LnkCap:' in line:
                    # Parse link capabilities
                    speed_match = re.search(r'Speed (\S+)', line)
                    width_match = re.search(r'Width x(\d+)', line)
                    if speed_match:
                        net_info['max_link_speed'] = speed_match.group(1)
                    if width_match:
                        net_info['max_link_width'] = f"x{width_match.group(1)}"
                elif 'LnkSta:' in line:
                    # Parse current link status
                    speed_match = re.search(r'Speed (\S+)', line)
                    width_match = re.search(r'Width x(\d+)', line)
                    if speed_match:
                        net_info['current_link_speed'] = speed_match.group(1)
                    if width_match:
                        net_info['current_link_width'] = f"x{width_match.group(1)}"
        
        # Get interface name and status
        try:
            result = subprocess.run(['ls', '/sys/class/net/'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                interfaces = result.stdout.strip().split('\n')
                for iface in interfaces:
                    # Check if this interface corresponds to the PCI slot
                    device_path = f"/sys/class/net/{iface}/device"
                    if os.path.exists(device_path):
                        real_path = os.path.realpath(device_path)
                        if pci_slot in real_path:
                            net_info['interface_name'] = iface
                            
                            # Get interface speed
                            speed_file = f"/sys/class/net/{iface}/speed"
                            if os.path.exists(speed_file):
                                with open(speed_file, 'r') as f:
                                    speed = f.read().strip()
                                    if speed != '-1':
                                        net_info['interface_speed'] = f"{speed} Mbps"
                            
                            # Get MAC address
                            mac_file = f"/sys/class/net/{iface}/address"
                            if os.path.exists(mac_file):
                                with open(mac_file, 'r') as f:
                                    net_info['mac_address'] = f.read().strip()
                            
                            break
        except Exception as e:
            # print(f"[v0] Error getting network interface info: {e}")
            pass
            
    except Exception as e:
        # print(f"[v0] Error getting network hardware info: {e}")
        pass
    
    return net_info

def _get_sriov_info(slot):
    """Return SR-IOV role for a PCI slot via sysfs.

    Reads /sys/bus/pci/devices/<BDF>/ for:
      - physfn symlink    → slot is a Virtual Function; link target is its PF
      - sriov_numvfs      → active VF count if slot is a Physical Function
      - sriov_totalvfs    → maximum VFs this PF can spawn

    Returns a dict ready to merge into the GPU object, or {} on any error.
    The 'role' key uses the same vocabulary as _pci_sriov_role in the
    bash helpers (pci_passthrough_helpers.sh): vf | pf-active | pf-idle | none.
    """
    try:
        bdf = slot if slot.startswith('0000:') else f'0000:{slot}'
        base = f'/sys/bus/pci/devices/{bdf}'
        if not os.path.isdir(base):
            return {}

        physfn = os.path.join(base, 'physfn')
        if os.path.islink(physfn):
            parent = os.path.basename(os.path.realpath(physfn))
            return {
                'sriov_role': 'vf',
                'sriov_physfn': parent,
            }

        totalvfs_path = os.path.join(base, 'sriov_totalvfs')
        if not os.path.isfile(totalvfs_path):
            return {'sriov_role': 'none'}

        try:
            totalvfs = int((open(totalvfs_path).read() or '0').strip() or 0)
        except (ValueError, OSError):
            totalvfs = 0
        if totalvfs <= 0:
            return {'sriov_role': 'none'}

        try:
            numvfs = int((open(os.path.join(base, 'sriov_numvfs')).read() or '0').strip() or 0)
        except (ValueError, OSError):
            numvfs = 0

        return {
            'sriov_role': 'pf-active' if numvfs > 0 else 'pf-idle',
            'sriov_vf_count': numvfs,
            'sriov_totalvfs': totalvfs,
        }
    except Exception:
        return {}


def _sriov_list_vfs_of_pf(pf_bdf):
    """Return sorted list of VF BDFs that belong to a Physical Function.
    Reads /sys/bus/pci/devices/<PF>/virtfn<N> symlinks (one per VF).
    """
    try:
        pf_full = pf_bdf if pf_bdf.startswith('0000:') else f'0000:{pf_bdf}'
        base = f'/sys/bus/pci/devices/{pf_full}'
        if not os.path.isdir(base):
            return []
        # virtfn links are numbered (virtfn0, virtfn1, ...) and point to the VF.
        entries = sorted(glob.glob(f'{base}/virtfn*'),
                         key=lambda p: int(re.search(r'virtfn(\d+)', p).group(1))
                         if re.search(r'virtfn(\d+)', p) else 0)
        return [os.path.basename(os.path.realpath(p)) for p in entries]
    except Exception:
        return []


def _sriov_pci_driver(bdf):
    """Return the current driver bound to a PCI BDF, '' if unbound."""
    try:
        link = f'/sys/bus/pci/devices/{bdf}/driver'
        if os.path.islink(link):
            return os.path.basename(os.path.realpath(link))
    except Exception:
        pass
    return ''


def _sriov_pci_render_node(bdf):
    """If the device exposes a DRM render node, return '/dev/dri/renderDX'.
    LXC containers consume GPUs through these nodes, so this lets us
    cross-reference an LXC's `dev<N>: /dev/dri/renderD<N>` config line
    back to a specific VF.
    """
    try:
        drm_dir = f'/sys/bus/pci/devices/{bdf}/drm'
        if not os.path.isdir(drm_dir):
            return ''
        for name in sorted(os.listdir(drm_dir)):
            if name.startswith('renderD'):
                return f'/dev/dri/{name}'
    except Exception:
        pass
    return ''


def _sriov_guest_running(guest_type, gid):
    """Best-effort status check. Returns True if running, False otherwise."""
    try:
        cmd = ['qm' if guest_type == 'vm' else 'pct', 'status', str(gid)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        return 'running' in (r.stdout or '').lower()
    except Exception:
        return False


def _sriov_find_guest_consumer(bdf):
    """Find the VM or LXC that consumes a given VF (or PF) on the host.

    VMs: scan /etc/pve/qemu-server/*.conf for a `hostpci<N>: ` line that
         references the BDF (short or full form, possibly alongside other
         ids separated by ';' and trailing options after ',').
    LXCs: resolve the BDF to its DRM render node (if any) and scan
         /etc/pve/lxc/*.conf for `dev<N>:` or `lxc.mount.entry:` lines that
         reference that node.

    Returns {type, id, name, running} or None.
    """
    short_bdf = bdf[5:] if bdf.startswith('0000:') else bdf
    full_bdf = bdf if bdf.startswith('0000:') else f'0000:{bdf}'

    # ── VM scan ──
    try:
        for conf in sorted(glob.glob('/etc/pve/qemu-server/*.conf')):
            try:
                with open(conf, 'r') as f:
                    text = f.read()
            except OSError:
                continue
            if re.search(
                rf'^hostpci\d+:\s*[^\n]*(?:0000:)?{re.escape(short_bdf)}(?:[,;\s]|$)',
                text, re.MULTILINE,
            ):
                vmid = os.path.basename(conf)[:-5]  # strip '.conf'
                nm = re.search(r'^name:\s*(\S+)', text, re.MULTILINE)
                name = nm.group(1) if nm else ''
                return {
                    'type': 'vm',
                    'id': vmid,
                    'name': name,
                    'running': _sriov_guest_running('vm', vmid),
                }
    except Exception:
        pass

    # ── LXC scan (via render node) ──
    render_node = _sriov_pci_render_node(full_bdf)
    if render_node:
        try:
            for conf in sorted(glob.glob('/etc/pve/lxc/*.conf')):
                try:
                    with open(conf, 'r') as f:
                        text = f.read()
                except OSError:
                    continue
                if re.search(
                    rf'^(?:dev\d+|lxc\.mount\.entry):\s*[^\n]*{re.escape(render_node)}(?:[,;\s]|$)',
                    text, re.MULTILINE,
                ):
                    ctid = os.path.basename(conf)[:-5]
                    nm = re.search(r'^hostname:\s*(\S+)', text, re.MULTILINE)
                    name = nm.group(1) if nm else ''
                    return {
                        'type': 'lxc',
                        'id': ctid,
                        'name': name,
                        'running': _sriov_guest_running('lxc', ctid),
                    }
        except Exception:
            pass

    return None


def _sriov_enrich_detail(gpu):
    """On-demand enrichment for the GPU detail modal.

    For a PF with active VFs, populates gpu['sriov_vfs'] with per-VF driver
    and consumer info. For a VF, populates gpu['sriov_consumer'] with the
    guest (if any) currently referencing it. Heavier than _get_sriov_info()
    because it scans guest configs, so it is NOT called from the hardware
    snapshot path — only from the realtime endpoint.
    """
    role = gpu.get('sriov_role')
    slot = gpu.get('slot', '')
    if not slot:
        return
    full_bdf = slot if slot.startswith('0000:') else f'0000:{slot}'

    if role == 'pf-active':
        vf_list = []
        for vf_bdf in _sriov_list_vfs_of_pf(full_bdf):
            vf_list.append({
                'bdf': vf_bdf,
                'driver': _sriov_pci_driver(vf_bdf) or '',
                'render_node': _sriov_pci_render_node(vf_bdf) or '',
                'consumer': _sriov_find_guest_consumer(vf_bdf),
            })
        gpu['sriov_vfs'] = vf_list
    elif role == 'vf':
        gpu['sriov_consumer'] = _sriov_find_guest_consumer(full_bdf)


def get_gpu_info():
    """Detect and return information about GPUs in the system"""
    gpus = []
    
    try:
        lspci_output = get_cached_lspci()
        if lspci_output:
            for line in lspci_output.split('\n'):
                # Match VGA, 3D, Display controllers
                if any(keyword in line for keyword in ['VGA compatible controller', '3D controller', 'Display controller']):

                    parts = line.split(' ', 1)
                    if len(parts) >= 2:
                        slot = parts[0].strip()  
                        remaining = parts[1]
                        
                        if ':' in remaining:
                            class_and_name = remaining.split(':', 1)
                            gpu_name = class_and_name[1].strip() if len(class_and_name) > 1 else remaining.strip()
                        else:
                            gpu_name = remaining.strip()
                        
                        # Determine vendor
                        vendor = 'Unknown'
                        if 'NVIDIA' in gpu_name or 'nVidia' in gpu_name:
                            vendor = 'NVIDIA'
                        elif 'AMD' in gpu_name or 'ATI' in gpu_name or 'Radeon' in gpu_name:
                            vendor = 'AMD'
                        elif 'Intel' in gpu_name:
                            vendor = 'Intel'
                        elif 'Matrox' in gpu_name:
                            vendor = 'Matrox'
                        
                        gpu = {
                            'slot': slot,
                            'name': gpu_name,
                            'vendor': vendor,
                            'type': identify_gpu_type(gpu_name)
                        }
                        
                        pci_info = get_pci_device_info(slot)
                        if pci_info:
                            gpu['pci_class'] = pci_info.get('class', '')
                            gpu['pci_driver'] = pci_info.get('driver', '')
                            gpu['pci_kernel_module'] = pci_info.get('kernel_module', '')

                        sriov_fields = _get_sriov_info(slot)
                        if sriov_fields:
                            gpu.update(sriov_fields)

                        # detailed_info = get_detailed_gpu_info(gpu) # Removed this call here
                        # gpu.update(detailed_info)             # It will be called later in api_gpu_realtime
                        
                        gpus.append(gpu)
                        # print(f"[v0] Found GPU: {gpu_name} ({vendor}) at slot {slot}")
                        pass

    except Exception as e:
        # print(f"[v0] Error detecting GPUs from lspci: {e}")
        pass
    
    try:
        sensors_output = get_cached_sensors_output()
        if sensors_output:
            current_adapter = None
            
            for line in sensors_output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Detect adapter line
                if line.startswith('Adapter:'):
                    current_adapter = line.replace('Adapter:', '').strip()
                    continue
                
                # Look for GPU-related sensors (nouveau, amdgpu, radeon, i915)
                if ':' in line and not line.startswith(' '):
                    parts = line.split(':', 1)
                    sensor_name = parts[0].strip()
                    value_part = parts[1].strip()
                    
                    # Check if this is a GPU sensor
                    gpu_sensor_keywords = ['nouveau', 'amdgpu', 'radeon', 'i915']
                    is_gpu_sensor = any(keyword in current_adapter.lower() if current_adapter else False for keyword in gpu_sensor_keywords)
                    
                    if is_gpu_sensor:
                        # Try to match this sensor to a GPU
                        for gpu in gpus:
                            # Match nouveau to NVIDIA, amdgpu/radeon to AMD, i915 to Intel
                            if (('nouveau' in current_adapter.lower() and gpu['vendor'] == 'NVIDIA') or
                                (('amdgpu' in current_adapter.lower() or 'radeon' in current_adapter.lower()) and gpu['vendor'] == 'AMD') or
                                ('i915' in current_adapter.lower() and gpu['vendor'] == 'Intel')):
                                
                                # Parse temperature (only if not already set by nvidia-smi)
                                if 'temperature' not in gpu or gpu['temperature'] is None:
                                    if '°C' in value_part or 'C' in value_part:
                                        temp_match = re.search(r'([+-]?[\d.]+)\s*°?C', value_part)
                                        if temp_match:
                                            gpu['temperature'] = float(temp_match.group(1))
                                            # print(f"[v0] GPU {gpu['name']}: Temperature = {gpu['temperature']}°C")
                                            pass
                                
                                # Parse fan speed
                                elif 'RPM' in value_part:
                                    rpm_match = re.search(r'([\d.]+)\s*RPM', value_part)
                                    if rpm_match:
                                        gpu['fan_speed'] = int(float(rpm_match.group(1)))
                                        gpu['fan_unit'] = 'RPM'
                                        # print(f"[v0] GPU {gpu['name']}: Fan = {gpu['fan_speed']} RPM")
                                        pass
    except Exception as e:
        # print(f"[v0] Error enriching GPU data from sensors: {e}")
        pass
    
    return gpus

# ─── Hardware info cache (Sprint 14 perf pass) ───────────────────────────────
#
# `_get_hardware_info_uncached` runs ~51 subprocess calls per invocation
# (lscpu, dmidecode ×3, lsblk ×2, smartctl per disk, nvidia-smi, lspci, ...)
# for a total of ~985 ms on a typical Proxmox host. The Hardware page hits
# /api/hardware on every load and tab switch, and almost nothing in the
# returned payload changes at runtime — same CPU model, same RAM modules,
# same motherboard, same NICs. The dynamic bits (temperatures, fans,
# power, UPS, coral, usb) are already split into /api/hardware/live which
# the active page polls every 3-5 s, so caching the full /api/hardware
# response for a minute is invisible to the user.
#
# A USB plug/unplug or a hot-added device will be reflected on the next
# cache miss (within 60 s) — well within the noticeable lag budget for
# manual hardware changes.
_HARDWARE_INFO_TTL = 60  # seconds
_hardware_info_cache: dict = {'data': None, 'time': 0.0}


def get_hardware_info():
    """Cached wrapper around the heavy hardware enumeration."""
    now = time.time()
    cached = _hardware_info_cache
    if cached['data'] is not None and now - cached['time'] < _HARDWARE_INFO_TTL:
        return cached['data']
    data = _get_hardware_info_uncached()
    if isinstance(data, dict) and data:
        cached['data'] = data
        cached['time'] = now
    return data


def _get_hardware_info_uncached():
    """Get comprehensive hardware information"""
    try:
        # Initialize with default structure, including the new power_meter field
        hardware_data = {
            'cpu': {},
            'motherboard': {},
            'memory_modules': [],
            'storage_devices': [],
            'network_cards': [],
            'graphics_cards': [],
            'gpus': [],  # Added dedicated GPU array
            'pci_devices': [],
            'sensors': {
                'temperatures': [],
                'fans': []
            },
            'power': {}, # This might be overwritten by ipmi_power or ups
            'ipmi_fans': [],  # Added IPMI fans
            'ipmi_power': {},  # Added IPMI power
            'ups': {},  # Added UPS info
            'power_meter': None # Added placeholder for sensors power meter
        }
        
        # CPU Information
        try:
            result = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                cpu_info = {}
                for line in result.stdout.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'Model name':
                            cpu_info['model'] = value
                        elif key == 'CPU(s)':
                            cpu_info['total_threads'] = int(value)
                        elif key == 'Core(s) per socket':
                            cpu_info['cores_per_socket'] = int(value)
                        elif key == 'Socket(s)':
                            cpu_info['sockets'] = int(value)
                        elif key == 'CPU MHz':
                            cpu_info['current_mhz'] = float(value)
                        elif key == 'CPU max MHz':
                            cpu_info['max_mhz'] = float(value)
                        elif key == 'CPU min MHz':
                            cpu_info['min_mhz'] = float(value)
                        elif key == 'Virtualization':
                            cpu_info['virtualization'] = value
                        elif key == 'L1d cache':
                            cpu_info['l1d_cache'] = value
                        elif key == 'L1i cache':
                            cpu_info['l1i_cache'] = value
                        elif key == 'L2 cache':
                            cpu_info['l2_cache'] = value
                        elif key == 'L3 cache':
                            cpu_info['l3_cache'] = value
                
                hardware_data['cpu'] = cpu_info
                # print(f"[v0] CPU: {cpu_info.get('model', 'Unknown')}")
                pass
        except Exception as e:
            # print(f"[v0] Error getting CPU info: {e}")
            pass
        
        # Motherboard Information
        try:
            result = subprocess.run(['dmidecode', '-t', 'baseboard'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                mb_info = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('Manufacturer:'):
                        mb_info['manufacturer'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Product Name:'):
                        mb_info['model'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Version:'):
                        mb_info['version'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Serial Number:'):
                        mb_info['serial'] = line.split(':', 1)[1].strip()
                
                hardware_data['motherboard'] = mb_info
                # print(f"[v0] Motherboard: {mb_info.get('manufacturer', 'Unknown')} {mb_info.get('model', 'Unknown')}")
                pass
        except Exception as e:
            # print(f"[v0] Error getting motherboard info: {e}")
            pass
        
        # BIOS Information
        try:
            result = subprocess.run(['dmidecode', '-t', 'bios'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                bios_info = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('Vendor:'):
                        bios_info['vendor'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Version:'):
                        bios_info['version'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Release Date:'):
                        bios_info['date'] = line.split(':', 1)[1].strip()
                
                hardware_data['motherboard']['bios'] = bios_info
                # print(f"[v0] BIOS: {bios_info.get('vendor', 'Unknown')} {bios_info.get('version', 'Unknown')}")
                pass
        except Exception as e:
            # print(f"[v0] Error getting BIOS info: {e}")
            pass
        
        # Memory Modules
        try:
            result = subprocess.run(['dmidecode', '-t', 'memory'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                current_module = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    
                    if line.startswith('Memory Device'):
                        # Ensure only modules with size and not 'No Module Installed' are appended
                        if current_module and current_module.get('size') and current_module.get('size') != 'No Module Installed' and current_module.get('size') != 0:
                            hardware_data['memory_modules'].append(current_module)
                        current_module = {}
                    elif line.startswith('Size:'):
                        size_str = line.split(':', 1)[1].strip()
                        if size_str and size_str != 'No Module Installed' and size_str != 'Not Specified':
                            try:
                                # Parse size like "32768 MB" or "32 GB"
                                parts = size_str.split()
                                if len(parts) >= 2:
                                    value = float(parts[0])
                                    unit = parts[1].upper()
                                    
                                    # Convert to KB
                                    if unit == 'GB':
                                        size_kb = value * 1024 * 1024
                                    elif unit == 'MB':
                                        size_kb = value * 1024
                                    elif unit == 'KB':
                                        size_kb = value
                                    else:
                                        size_kb = value  # Assume KB if no unit
                                    
                                    current_module['size'] = size_kb
                                    # print(f"[v0] Parsed memory size: {size_str} -> {size_kb} KB")
                                    pass
                                else:
                                    # Handle cases where unit might be missing but value is present
                                    current_module['size'] = float(size_str) if size_str else 0
                                    # print(f"[v0] Parsed memory size (no unit): {size_str} -> {current_module['size']} KB")
                                    pass
                            except (ValueError, IndexError) as e:
                                # print(f"[v0] Error parsing memory size '{size_str}': {e}")
                                pass
                                current_module['size'] = 0 # Default to 0 if parsing fails
                        else:
                            current_module['size'] = 0 # Default to 0 if no size or explicitly 'No Module Installed'
                    elif line.startswith('Type:'):
                        current_module['type'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Configured Memory Speed:'):
                        current_module['configured_speed'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Speed:'):
                        current_module['max_speed'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Manufacturer:'):
                        current_module['manufacturer'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Serial Number:'):
                        current_module['serial'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Locator:'):
                        current_module['slot'] = line.split(':', 1)[1].strip()
                
                # Append the last module if it's valid
                if current_module and current_module.get('size') and current_module.get('size') != 'No Module Installed' and current_module.get('size') != 0:
                    hardware_data['memory_modules'].append(current_module)
                
                # print(f"[v0] Memory modules: {len(hardware_data['memory_modules'])} installed")
                pass
        except Exception as e:
            # print(f"[v0] Error getting memory info: {e}")
            pass
        
        # Storage Devices - simplified version without hardware info
        try:
            result = subprocess.run(['lsblk', '-J', '-o', 'NAME,SIZE,TYPE,MOUNTPOINT,MODEL'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                import json
                lsblk_data = json.loads(result.stdout)
                storage_devices = []
                for device in lsblk_data.get('blockdevices', []):
                    if device.get('type') == 'disk':
                        storage_devices.append({
                            'name': device.get('name', ''),
                            'size': device.get('size', ''),
                            'model': device.get('model', 'Unknown'),
                            'type': device.get('type', 'disk')
                        })
                hardware_data['storage_devices'] = storage_devices
                # print(f"[v0] Storage devices: {len(storage_devices)} found")
                pass
        except Exception as e:
            # print(f"[v0] Error getting storage info: {e}")
            pass
        

        try:
            result = subprocess.run(['lsblk', '-J', '-o', 'NAME,SIZE,TYPE,MOUNTPOINT,MODEL'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                import json
                lsblk_data = json.loads(result.stdout)
                storage_devices = []
                for device in lsblk_data.get('blockdevices', []):
                    if device.get('type') == 'disk':
                        disk_name = device.get('name', '')
                        
                        # Get SMART data for this disk
                        smart_data = get_smart_data(disk_name)
                        
                        # Determine interface type
                        interface_type = None
                        if disk_name.startswith('nvme'):
                            interface_type = 'PCIe/NVMe'
                        elif disk_name.startswith('sd'):
                            interface_type = 'ATA'
                        elif disk_name.startswith('hd'):
                            interface_type = 'IDE'
                        
                        # Get driver information
                        driver = None
                        try:
                            sys_block_path = f'/sys/block/{disk_name}'
                            if os.path.exists(sys_block_path):
                                device_path = os.path.join(sys_block_path, 'device')
                                if os.path.exists(device_path):
                                    driver_path = os.path.join(device_path, 'driver')
                                    if os.path.exists(driver_path):
                                        driver = os.path.basename(os.readlink(driver_path))
                        except:
                            pass
                        
                        # Parse SATA version from smartctl output
                        sata_version = None
                        try:
                            result_smart = subprocess.run(['smartctl', '-i', f'/dev/{disk_name}'], 
                                                        capture_output=True, text=True, timeout=5)
                            if result_smart.returncode == 0:
                                for line in result_smart.stdout.split('\n'):
                                    if 'SATA Version is:' in line:
                                        sata_version = line.split(':', 1)[1].strip()
                                        break
                        except:
                            pass
                        
                        # Parse form factor from smartctl output
                        form_factor = None
                        try:
                            result_smart = subprocess.run(['smartctl', '-i', f'/dev/{disk_name}'], 
                                                        capture_output=True, text=True, timeout=5)
                            if result_smart.returncode == 0:
                                for line in result_smart.stdout.split('\n'):
                                    if 'Form Factor:' in line:
                                        form_factor = line.split(':', 1)[1].strip()
                                        break
                        except:
                            pass
                        
                        pcie_info = {}
                        if disk_name.startswith('nvme'):
                            pcie_info = get_pcie_link_speed(disk_name)
                        
                        # Build storage device with all available information
                        storage_device = {
                            'name': disk_name,
                            'size': device.get('size', ''),
                            'model': smart_data.get('model', device.get('model', 'Unknown')),
                            'type': device.get('type', 'disk'),
                            'serial': smart_data.get('serial', 'Unknown'),
                            'firmware': smart_data.get('firmware'),
                            'interface': interface_type,
                            'driver': driver,
                            'rotation_rate': smart_data.get('rotation_rate', 0),
                            'form_factor': form_factor,
                            'sata_version': sata_version,
                        }
                        
                        if pcie_info:
                            storage_device.update(pcie_info)
                        
                        # Add family if available (from smartctl)
                        try:
                            result_smart = subprocess.run(['smartctl', '-i', f'/dev/{disk_name}'], 
                                                        capture_output=True, text=True, timeout=5)
                            if result_smart.returncode == 0:
                                for line in result_smart.stdout.split('\n'):
                                    if 'Model Family:' in line:
                                        storage_device['family'] = line.split(':', 1)[1].strip()
                                        break
                        except:
                            pass
                        
                        storage_devices.append(storage_device)
                
                hardware_data['storage_devices'] = storage_devices
                # print(f"[v0] Storage devices: {len(storage_devices)} found with full SMART data")
                pass
        except Exception as e:
            # print(f"[v0] Error getting storage info: {e}")
            pass

        # Graphics Cards
        try:
            # Try nvidia-smi first
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,temperature.gpu,power.draw,utilization.gpu,utilization.memory,clocks.graphics,clocks.memory', '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for i, line in enumerate(result.stdout.strip().split('\n')):
                    if line:
                        parts = line.split(',')
                        if len(parts) >= 9: # Adjusted to match the query fields
                            gpu_name = parts[0]
                            mem_total = parts[1]
                            mem_used = parts[2]
                            temp = parts[3] if parts[3] != 'N/A' else None
                            power = parts[4] if parts[4] != 'N/A' else None
                            gpu_util = parts[5] if parts[5] != 'N/A' else None
                            mem_util = parts[6] if parts[6] != 'N/A' else None
                            graphics_clock = parts[7] if parts[7] != 'N/A' else None
                            memory_clock = parts[8] if parts[8] != 'N/A' else None
                            
                            # Try to find the corresponding PCI slot using nvidia-smi -L
                            try:
                                list_gpus_cmd = ['nvidia-smi', '-L']
                                list_gpus_result = subprocess.run(list_gpus_cmd, capture_output=True, text=True, timeout=5)
                                pci_slot = None
                                if list_gpus_result.returncode == 0:
                                    for gpu_line in list_gpus_result.stdout.strip().split('\n'):
                                        if gpu_name in gpu_line:
                                            slot_match = re.search(r'PCI Device (\S+):', gpu_line)
                                            if slot_match:
                                                pci_slot = slot_match.group(1)
                                                break
                            except:
                                pass # Ignore errors here, pci_slot will remain None
                            
                            hardware_data['graphics_cards'].append({
                                'name': gpu_name,
                                'vendor': 'NVIDIA',
                                'slot': pci_slot,
                                'memory_total': mem_total,
                                'memory_used': mem_used,
                                'temperature': int(temp) if temp else None,
                                'power_draw': power,
                                'utilization_gpu': gpu_util,
                                'utilization_memory': mem_util,
                                'clock_graphics': graphics_clock,
                                'clock_memory': memory_clock,
                            })
            
            # Always check lspci for all GPUs (integrated and discrete)
            lspci_output = get_cached_lspci()
            if lspci_output:
                for line in lspci_output.split('\n'):
                    # Match VGA, 3D, Display controllers
                    if any(keyword in line for keyword in ['VGA compatible controller', '3D controller', 'Display controller']):
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            slot = parts[0].strip()
                            gpu_name = parts[2].strip()
                            
                            # Determine vendor
                            vendor = 'Unknown'
                            if 'NVIDIA' in gpu_name or 'nVidia' in gpu_name:
                                vendor = 'NVIDIA'
                            elif 'AMD' in gpu_name or 'ATI' in gpu_name or 'Radeon' in gpu_name:
                                vendor = 'AMD'
                            elif 'Intel' in gpu_name:
                                vendor = 'Intel'
                            elif 'Matrox' in gpu_name:
                                vendor = 'Matrox'
                            
                            # Check if this GPU is already in the list (from nvidia-smi)
                            already_exists = False
                            for existing_gpu in hardware_data['graphics_cards']:
                                if gpu_name in existing_gpu['name'] or existing_gpu['name'] in gpu_name:
                                    already_exists = True
                                    # Update vendor if it was previously unknown
                                    if existing_gpu['vendor'] == 'Unknown':
                                        existing_gpu['vendor'] = vendor
                                    # Update slot if not already set
                                    if not existing_gpu.get('slot') and slot:
                                        existing_gpu['slot'] = slot
                                    break
                            
                            if not already_exists:
                                hardware_data['graphics_cards'].append({
                                    'name': gpu_name,
                                    'vendor': vendor,
                                    'slot': slot
                                })
                                # print(f"[v0] Found GPU: {gpu_name} ({vendor}) at slot {slot}")
                                pass
            
            # print(f"[v0] Graphics cards: {len(hardware_data['graphics_cards'])} found")
            pass
        except Exception as e:
            # print(f"[v0] Error getting graphics cards: {e}")
            pass
        
        # PCI Devices
        try:
            # print("[v0] Getting PCI devices with driver information...")
            pass
            # First get basic device info with lspci -vmm
            lspci_vmm_output = get_cached_lspci_vmm()
            if lspci_vmm_output:
                current_device = {}
                for line in lspci_vmm_output.split('\n'):
                    line = line.strip()
                    
                    if not line:
                        # Empty line = end of device
                        if current_device and 'Class' in current_device:
                            device_class = current_device.get('Class', '')
                            device_name = current_device.get('Device', '')
                            vendor = current_device.get('Vendor', '')
                            slot = current_device.get('Slot', 'Unknown')
                            
                            # Categorize and add important devices
                            device_type = 'Other'
                            include_device = False
                            network_subtype = None
                            
                            # Graphics/Display devices
                            if any(keyword in device_class for keyword in ['VGA', 'Display', '3D']):
                                device_type = 'Graphics Card'
                                include_device = True
                            # Storage controllers (including SCSI/SAS HBA cards like LSI 9400-16i)
                            elif any(keyword in device_class for keyword in ['SATA', 'RAID', 'Mass storage', 'Non-Volatile memory', 'SCSI', 'Serial Attached SCSI', 'SAS']):
                                device_type = 'Storage Controller'
                                include_device = True
                            # Network controllers
                            elif 'Ethernet' in device_class or 'Network' in device_class:
                                device_type = 'Network Controller'
                                include_device = True
                                device_lower = device_name.lower()
                                if any(keyword in device_lower for keyword in ['wireless', 'wifi', 'wi-fi', '802.11', 'wlan']):
                                    network_subtype = 'Wireless'
                                else:
                                    network_subtype = 'Ethernet'
                            # USB controllers
                            elif 'USB' in device_class:
                                device_type = 'USB Controller'
                                include_device = True
                            # Audio devices
                            elif 'Audio' in device_class or 'Multimedia' in device_class:
                                device_type = 'Audio Controller'
                                include_device = True
                            # Special devices (Coral TPU, etc.)
                            elif any(keyword in device_name.lower() for keyword in ['coral', 'tpu', 'edge']):
                                device_type = 'AI Accelerator'
                                include_device = True
                            # PCI bridges (usually not interesting for users)
                            elif 'Bridge' in device_class:
                                include_device = False
                            
                            if include_device:
                                pci_device = {
                                    'slot': slot,
                                    'type': device_type,
                                    'vendor': vendor,
                                    'device': device_name,
                                    'class': device_class
                                }
                                # Add subsystem device name if available (e.g., "HBA 9400-16i" for SAS controllers)
                                sdevice = current_device.get('SDevice', '')
                                if sdevice:
                                    pci_device['sdevice'] = sdevice
                                if network_subtype:
                                    pci_device['network_subtype'] = network_subtype
                                hardware_data['pci_devices'].append(pci_device)
                        
                        current_device = {}
                    elif ':' in line:
                        key, value = line.split(':', 1)
                        current_device[key.strip()] = value.strip()
            
            # Now get driver information with lspci -k
            lspci_k_output = get_cached_lspci_k()
            if lspci_k_output:
                current_slot = None
                current_driver = None
                current_module = None
                
                for line in lspci_k_output.split('\n'):
                    # Match PCI slot line (e.g., "00:1f.2 SATA controller: ...")
                    if line and not line.startswith('\t'):
                        parts = line.split(' ', 1)
                        if parts:
                            current_slot = parts[0]
                            current_driver = None
                            current_module = None
                    # Match driver lines (indented with tab)
                    elif line.startswith('\t'):
                        line = line.strip()
                        if line.startswith('Kernel driver in use:'):
                            current_driver = line.split(':', 1)[1].strip()
                        elif line.startswith('Kernel modules:'):
                            current_module = line.split(':', 1)[1].strip()
                        
                        # Update the corresponding PCI device
                        if current_slot and (current_driver or current_module):
                            for device in hardware_data['pci_devices']:
                                if device['slot'] == current_slot:
                                    if current_driver:
                                        device['driver'] = current_driver
                                    if current_module:
                                        device['kernel_module'] = current_module
                                    break
            
            # print(f"[v0] Total PCI devices found: {len(hardware_data['pci_devices'])}")
            pass
        except Exception as e:
            # print(f"[v0] Error getting PCI devices: {e}")
            pass
        
        # Sensors (Temperature and Fans)
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for sensor_name, entries in temps.items():
                        for entry in entries:
                            # Use identify_temperature_sensor to make names more user-friendly
                            identified_name = identify_temperature_sensor(entry.label if entry.label else sensor_name, sensor_name)
                            
                            hardware_data['sensors']['temperatures'].append({
                                'name': identified_name,
                                'original_name': entry.label if entry.label else sensor_name,
                                'current': entry.current,
                                'high': entry.high if entry.high else 0,
                                'critical': entry.critical if entry.critical else 0
                            })
        except Exception as e:
            # print(f"[v0] Error getting temperature sensors: {e}")
            pass
        
        try:
            hardware_data['sensors']['fans'] = _parse_sensor_fans(get_cached_sensors_output())
        except Exception:
            pass
        
        # Power Supply / UPS
        try:
            result = subprocess.run(['apcaccess'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ups_info = {}
                for line in result.stdout.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'MODEL':
                            ups_info['model'] = value
                        elif key == 'STATUS':
                            ups_info['status'] = value
                        elif key == 'BCHARGE':
                            ups_info['battery_charge'] = value
                        elif key == 'TIMELEFT':
                            ups_info['time_left'] = value
                        elif key == 'LOADPCT':
                            ups_info['load_percent'] = value
                        elif key == 'LINEV':
                            ups_info['line_voltage'] = value
                
                if ups_info:
                    hardware_data['power'] = ups_info
                    # print(f"[v0] UPS found: {ups_info.get('model', 'Unknown')}")
                    pass
        except FileNotFoundError:
            # print("[v0] apcaccess not found - no UPS monitoring")
            pass
        except Exception as e:
            # print(f"[v0] Error getting UPS info: {e}")
            pass
        
        temp_info = get_temperature_info()
        hardware_data['sensors']['temperatures'] = temp_info['temperatures']
        hardware_data['power_meter'] = temp_info['power_meter']
        
        ipmi_fans = get_ipmi_fans()
        if ipmi_fans:
            hardware_data['ipmi_fans'] = ipmi_fans
        
        ipmi_power = get_ipmi_power()
        if ipmi_power['power_supplies'] or ipmi_power['power_meter']:
            hardware_data['ipmi_power'] = ipmi_power
        
        ups_info = get_ups_info()
        if ups_info:
            hardware_data['ups'] = ups_info
        
        hardware_data['gpus'] = get_gpu_info()

        # Enrich PCI devices with GPU info where applicable
        for pci_device in hardware_data['pci_devices']:
            if pci_device.get('type') == 'Graphics Card':
                for gpu in hardware_data['gpus']:
                    if pci_device.get('slot') == gpu.get('slot'):
                        pci_device['gpu_info'] = gpu # Add the detected GPU info directly
                        break

        # Coral TPU (Edge TPU) — dedicated section in the Hardware UI.
        # Empty list when no Coral is connected; the frontend skips the section.
        hardware_data['coral_tpus'] = get_coral_info()

        # USB peripherals currently plugged into the host. Lists non-hub
        # devices (Coral USB accelerators, UPSs, keyboards/mice, pendrives,
        # serial adapters, etc.). Empty list on headless servers.
        hardware_data['usb_devices'] = get_usb_devices()

        return hardware_data
        
    except Exception as e:
        # print(f"[v0] Error in get_hardware_info: {e}")
        pass
        import traceback
        traceback.print_exc()
        return {}


@app.route('/api/system', methods=['GET'])
@require_auth
def api_system():
    """Get system information including CPU, memory, and temperature"""
    try:
        # Non-blocking: returns %CPU since the last psutil call (sampler or prior API hit).
        # The background vital-signs sampler keeps psutil's internal state primed.
        cpu_usage = psutil.cpu_percent(interval=0)
        
        memory = psutil.virtual_memory()
        memory_used_gb = memory.used / (1024 ** 3)
        memory_total_gb = memory.total / (1024 ** 3)
        memory_usage_percent = memory.percent
        
        # Get temperature
        temp = get_cpu_temperature()
        
        # Get uptime
        uptime = get_uptime()
        
        # Get load average
        load_avg = os.getloadavg()
        
        # Get CPU cores
        cpu_cores = psutil.cpu_count(logical=False)
        
        cpu_threads = psutil.cpu_count(logical=True)
        
        # Get Proxmox version
        proxmox_version = get_proxmox_version()
        
        # Get kernel version
        kernel_version = platform.release()
        
        # Get available updates
        available_updates = get_available_updates()
        
        # Get temperature sparkline (last 1h) for overview mini chart
        temp_sparkline = get_temperature_sparkline(60)

        return jsonify({
            'cpu_usage': round(cpu_usage, 1),
            'memory_usage': round(memory_usage_percent, 1),
            'memory_total': round(memory_total_gb, 1),
            'memory_used': round(memory_used_gb, 1),
            'temperature': temp,
            'temperature_sparkline': temp_sparkline,
            'uptime': uptime,
            'load_average': list(load_avg),
            'hostname': socket.gethostname(),
            'proxmox_node': get_proxmox_node_name(),
            'node_id': socket.gethostname(),
            'timestamp': datetime.now().isoformat(),
            'cpu_cores': cpu_cores,
            'cpu_threads': cpu_threads,
            'proxmox_version': proxmox_version,
            'kernel_version': kernel_version,
            'available_updates': available_updates
        })
    except Exception as e:
        # print(f"Error getting system info: {e}")
        pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/temperature/history', methods=['GET'])
@require_auth
def api_temperature_history():
    """Get temperature history for charts. Timeframe: hour, day, week, month"""
    try:
        timeframe = request.args.get('timeframe', 'hour')
        if timeframe not in ('hour', 'day', 'week', 'month'):
            timeframe = 'hour'
        result = get_temperature_history(timeframe)
        return jsonify(result)
    except Exception as e:
        return jsonify({'data': [], 'stats': {'min': 0, 'max': 0, 'avg': 0, 'current': 0}}), 500


@app.route('/api/disk/<disk_name>/temperature/history', methods=['GET'])
@require_auth
def api_disk_temperature_history(disk_name):
    """Sprint 14: per-disk temperature history.

    Mirrors the CPU temperature endpoint shape so the frontend can
    reuse the same chart component / hook with just a different URL.
    The disk_name is whitelisted inside the helper to keep the
    sqlite query parameter-only.
    """
    empty = {'data': [], 'stats': {'min': 0, 'max': 0, 'avg': 0, 'current': 0}}
    try:
        import disk_temperature_history
    except ImportError:
        return jsonify(empty)
    try:
        timeframe = request.args.get('timeframe', 'hour')
        if timeframe not in ('hour', 'day', 'week', 'month'):
            timeframe = 'hour'
        result = disk_temperature_history.get_disk_temperature_history(disk_name, timeframe)
        return jsonify(result)
    except Exception:
        return jsonify(empty), 500


@app.route('/api/network/latency/history', methods=['GET'])
@require_auth
def api_latency_history():
    """Get latency history for charts. 
    
    Query params:
        target: gateway (default), cloudflare, google
        timeframe: hour, 6hour, day, 3day, week
    """
    try:
        target = request.args.get('target', 'gateway')
        if target not in ('gateway', 'cloudflare', 'google'):
            target = 'gateway'
        timeframe = request.args.get('timeframe', 'hour')
        if timeframe not in ('hour', '6hour', 'day', '3day', 'week'):
            timeframe = 'hour'
        result = get_latency_history(target, timeframe)
        return jsonify(result)
    except Exception as e:
        return jsonify({'data': [], 'stats': {'min': 0, 'max': 0, 'avg': 0, 'current': 0}, 'target': 'gateway'}), 500


@app.route('/api/network/latency/current', methods=['GET'])
@require_auth
def api_latency_current():
    """Get current latency measurement for a target.
    
    Query params:
        target: gateway (default), cloudflare, google, or custom IP
    """
    try:
        target = request.args.get('target', 'gateway')
        result = get_current_latency(target)
        return jsonify(result)
    except Exception as e:
        return jsonify({'target': target, 'latency_avg': None, 'status': 'error'}), 500


@app.route('/api/storage', methods=['GET'])
@require_auth
def api_storage():
    """Get storage information"""
    return jsonify(get_storage_info())

@app.route('/api/proxmox-storage', methods=['GET'])
@require_auth
def api_proxmox_storage():
    """Get Proxmox storage information"""
    return jsonify(get_proxmox_storage())


# ─── SMART Disk Testing API ───────────────────────────────────────────────────

SMART_DIR = '/usr/local/share/proxmenux/smart'
SMART_CONFIG_DIR = '/usr/local/share/proxmenux/smart/config'
DEFAULT_SMART_RETENTION = 10  # Keep last 10 JSON files per disk by default

def _is_nvme(disk_name):
    """Check if disk is NVMe (supports names like nvme0n1, nvme0n1p1)."""
    return 'nvme' in disk_name

def _get_smart_disk_dir(disk_name):
    """Get directory path for a disk's SMART JSON files."""
    return os.path.join(SMART_DIR, disk_name)

def _get_smart_json_path(disk_name, test_type='short'):
    """Get path to a new SMART JSON file for a disk with timestamp."""
    disk_dir = _get_smart_disk_dir(disk_name)
    os.makedirs(disk_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
    return os.path.join(disk_dir, f"{timestamp}_{test_type}.json")

def _get_latest_smart_json(disk_name):
    """Get the most recent SMART JSON file for a disk."""
    disk_dir = _get_smart_disk_dir(disk_name)
    if not os.path.exists(disk_dir):
        return None
    
    json_files = sorted(
        [f for f in os.listdir(disk_dir) if f.endswith('.json')],
        reverse=True  # Most recent first (timestamp-based naming)
    )
    
    if json_files:
        return os.path.join(disk_dir, json_files[0])
    return None

def _get_smart_history(disk_name, limit=None):
    """Get list of all SMART JSON files for a disk, sorted by date (newest first)."""
    disk_dir = _get_smart_disk_dir(disk_name)
    if not os.path.exists(disk_dir):
        return []
    
    json_files = sorted(
        [f for f in os.listdir(disk_dir) if f.endswith('.json')],
        reverse=True
    )
    
    if limit:
        json_files = json_files[:limit]
    
    result = []
    for filename in json_files:
        # Parse timestamp and test type from filename: 2026-04-13T10-30-00_short.json
        parts = filename.replace('.json', '').split('_')
        if len(parts) >= 2:
            timestamp_str = parts[0]
            test_type = parts[1]
            try:
                # Convert back to readable format
                dt = datetime.strptime(timestamp_str, '%Y-%m-%dT%H-%M-%S')
                result.append({
                    'filename': filename,
                    'path': os.path.join(disk_dir, filename),
                    'timestamp': dt.isoformat(),
                    'test_type': test_type,
                    'date_readable': dt.strftime('%Y-%m-%d %H:%M:%S')
                })
            except ValueError:
                # Filename doesn't match expected format, skip
                pass
    
    return result

def _cleanup_old_smart_jsons(disk_name, retention=None):
    """Remove old SMART JSON files, keeping only the most recent ones."""
    if retention is None:
        retention = DEFAULT_SMART_RETENTION
    
    if retention <= 0:  # 0 or negative means keep all
        return 0
    
    disk_dir = _get_smart_disk_dir(disk_name)
    if not os.path.exists(disk_dir):
        return 0
    
    json_files = sorted(
        [f for f in os.listdir(disk_dir) if f.endswith('.json')],
        reverse=True  # Most recent first
    )
    
    removed = 0
    # Keep first 'retention' files, delete the rest
    for old_file in json_files[retention:]:
        try:
            os.remove(os.path.join(disk_dir, old_file))
            removed += 1
        except Exception:
            pass
    
    return removed

def _ensure_smart_tools(install_if_missing=False):
    """Check if SMART tools are installed and optionally install them."""
    has_smartctl = shutil.which('smartctl') is not None
    has_nvme = shutil.which('nvme') is not None
    
    installed = {'smartctl': False, 'nvme': False}
    install_errors = []
    
    if install_if_missing and (not has_smartctl or not has_nvme):
        # Run apt-get update first
        try:
            subprocess.run(
                ['apt-get', 'update'],
                capture_output=True, text=True, timeout=60
            )
        except Exception:
            pass
        
        if not has_smartctl:
            try:
                # Install smartmontools
                proc = subprocess.run(
                    ['apt-get', 'install', '-y', 'smartmontools'],
                    capture_output=True, text=True, timeout=120
                )
                if proc.returncode == 0:
                    has_smartctl = shutil.which('smartctl') is not None
                    installed['smartctl'] = has_smartctl
                else:
                    install_errors.append(f"smartmontools: {proc.stderr.strip()}")
            except Exception as e:
                install_errors.append(f"smartmontools: {str(e)}")
        
        if not has_nvme:
            try:
                # Install nvme-cli
                proc = subprocess.run(
                    ['apt-get', 'install', '-y', 'nvme-cli'],
                    capture_output=True, text=True, timeout=120
                )
                if proc.returncode == 0:
                    has_nvme = shutil.which('nvme') is not None
                    installed['nvme'] = has_nvme
                else:
                    install_errors.append(f"nvme-cli: {proc.stderr.strip()}")
            except Exception as e:
                install_errors.append(f"nvme-cli: {str(e)}")
    
    return {
        'smartctl': has_smartctl, 
        'nvme': has_nvme,
        'just_installed': installed,
        'install_errors': install_errors
    }

def _parse_smart_attributes(output_lines):
    """Parse SMART attributes from smartctl output."""
    attributes = []
    in_attrs = False
    for line in output_lines:
        if 'ID#' in line and 'ATTRIBUTE_NAME' in line:
            in_attrs = True
            continue
        if in_attrs:
            if not line.strip():
                break
            parts = line.split()
            if len(parts) >= 10 and parts[0].isdigit():
                attr_id = int(parts[0])
                attr_name = parts[1]
                value = int(parts[3]) if parts[3].isdigit() else 0
                worst = int(parts[4]) if parts[4].isdigit() else 0
                threshold = int(parts[5]) if parts[5].isdigit() else 0
                raw_value = parts[9] if len(parts) > 9 else ''
                
                # Determine status
                status = 'ok'
                if threshold > 0 and value <= threshold:
                    status = 'critical'
                elif threshold > 0 and value <= threshold + 10:
                    status = 'warning'
                
                attributes.append({
                    'id': attr_id,
                    'name': attr_name,
                    'value': value,
                    'worst': worst,
                    'threshold': threshold,
                    'raw_value': raw_value,
                    'status': status
                })
    return attributes

@app.route('/api/storage/smart/<disk_name>', methods=['GET'])
@require_auth
def api_smart_status(disk_name):
    """Get SMART status and data for a specific disk."""
    try:
        # Validate disk name (security)
        if not re.match(r'^[a-zA-Z0-9]+$', disk_name):
            return jsonify({'error': 'Invalid disk name'}), 400
        
        device = f'/dev/{disk_name}'
        if not os.path.exists(device):
            return jsonify({'error': 'Device not found'}), 404
        
        tools = _ensure_smart_tools()
        result = {
            'status': 'idle',
            'tools_installed': tools
        }
        
        # Check if tools are available
        is_nvme = _is_nvme(disk_name)
        if is_nvme and not tools['nvme']:
            result['error'] = 'nvme-cli not installed'
            return jsonify(result)
        if not is_nvme and not tools['smartctl']:
            result['error'] = 'smartmontools not installed'
            return jsonify(result)
        
        # Check for existing JSON file (from previous test) - get most recent
        json_path = _get_latest_smart_json(disk_name)
        if json_path and os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    saved_data = json.load(f)
                    result['saved_data'] = saved_data
                    result['saved_timestamp'] = os.path.getmtime(json_path)
                    result['saved_path'] = json_path
                    # Get test history
                    result['test_history'] = _get_smart_history(disk_name, limit=10)
            except (json.JSONDecodeError, IOError):
                pass

        # Get device identity via smartctl (works for both NVMe and SATA)
        _sctl_identity = {}
        try:
            _sctl_proc = subprocess.run(
                ['smartctl', '-a', '--json=c', device],
                capture_output=True, text=True, timeout=15
            )
            _sctl_data = json.loads(_sctl_proc.stdout)
            _sctl_identity = {
                'model': _sctl_data.get('model_name', ''),
                'serial': _sctl_data.get('serial_number', ''),
                'firmware': _sctl_data.get('firmware_version', ''),
                'nvme_version': _sctl_data.get('nvme_version', {}).get('string', ''),
                'capacity_bytes': _sctl_data.get('user_capacity', {}).get('bytes', 0),
                'smart_passed': _sctl_data.get('smart_status', {}).get('passed'),
                'smartctl_messages': [m.get('string', '') for m in _sctl_data.get('smartctl', {}).get('messages', [])],
            }
        except Exception:
            pass

        # Get current SMART status
        if is_nvme:
            # NVMe: Check for running test and get self-test log using JSON format
            try:
                proc = subprocess.run(
                    ['nvme', 'self-test-log', device, '-o', 'json'],
                    capture_output=True, text=True, timeout=10
                )
                if proc.returncode == 0:
                    try:
                        selftest_data = json.loads(proc.stdout)
                        # Check if test is in progress
                        # "Current Device Self-Test Operation": 0=none, 1=short, 2=extended
                        current_op = selftest_data.get('Current Device Self-Test Operation', 0)
                        if current_op > 0:
                            result['status'] = 'running'
                            result['test_type'] = 'short' if current_op == 1 else 'long'
                            # Get completion percentage
                            completion = selftest_data.get('Current Device Self-Test Completion', 0)
                            result['progress'] = completion
                        
                        # Parse last test result from self-test log
                        valid_reports = selftest_data.get('List of Valid Reports', [])
                        if valid_reports:
                            # Find most recent completed test (result != 15 which means not run)
                            for report in valid_reports:
                                test_result = report.get('Self test result', 15)
                                if test_result != 15:  # 15 = entry not used
                                    test_code = report.get('Self test code', 0)
                                    test_type = 'short' if test_code == 1 else 'long' if test_code == 2 else 'unknown'
                                    # 0 = completed without error, other values = error
                                    test_status = 'passed' if test_result == 0 else 'failed'
                                    result['last_test'] = {
                                        'type': test_type,
                                        'status': test_status,
                                        'timestamp': 'Completed without error' if test_result == 0 else f'Failed (code {test_result})',
                                        'lifetime_hours': report.get('Power on hours')
                                    }
                                    break
                    except json.JSONDecodeError:
                        # Fallback to text parsing if JSON fails
                        output = proc.stdout
                        # Check Current operation field
                        op_match = re.search(r'Current operation\s*:\s*(0x[0-9a-fA-F]+|\d+)', output)
                        if op_match:
                            op_val = int(op_match.group(1), 0)
                            if op_val > 0:
                                result['status'] = 'running'
                                result['test_type'] = 'short' if op_val == 1 else 'long'
                                # Try to extract progress percentage
                                prog_match = re.search(r'Current Completion\s*:\s*(\d+)%', output)
                                if prog_match:
                                    result['progress'] = int(prog_match.group(1))
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass

            # NVMe always supports progress reporting via nvme self-test-log
            result['supports_progress_reporting'] = True
            result['supports_self_test'] = True

            # Get smart-log data (JSON format)
            try:
                proc = subprocess.run(
                    ['nvme', 'smart-log', '-o', 'json', device],
                    capture_output=True, text=True, timeout=10
                )
                if proc.returncode == 0:
                    try:
                        nvme_data = json.loads(proc.stdout)
                    except json.JSONDecodeError:
                        nvme_data = {}

                    # Normalise temperature: nvme-cli reports in Kelvin when > 200
                    raw_temp = nvme_data.get('temperature', 0)
                    temp_celsius = raw_temp - 273 if raw_temp > 200 else raw_temp

                    # Check health: critical_warning == 0 and media_errors == 0 is ideal
                    crit_warn = nvme_data.get('critical_warning', 0)
                    media_err = nvme_data.get('media_errors', 0)
                    if crit_warn != 0 or media_err != 0:
                        result['smart_status'] = 'warning' if crit_warn != 0 else 'passed'
                    else:
                        result['smart_status'] = 'passed'
                    # Override with smartctl smart_status if available
                    if _sctl_identity.get('smart_passed') is True:
                        result['smart_status'] = 'passed'
                    elif _sctl_identity.get('smart_passed') is False:
                        result['smart_status'] = 'failed'

                    # Convert NVMe data to attributes format for UI compatibility
                    nvme_attrs = []
                    nvme_field_map = [
                        ('critical_warning',                    'Critical Warning',         lambda v: 'OK' if v == 0 else f'0x{v:02X}'),
                        ('temperature',                         'Temperature',              lambda v: f"{v - 273 if v > 200 else v}°C"),
                        ('avail_spare',                         'Available Spare',          lambda v: f"{v}%"),
                        ('spare_thresh',                        'Available Spare Threshold',lambda v: f"{v}%"),
                        ('percent_used',                        'Percentage Used',          lambda v: f"{v}%"),
                        ('endurance_grp_critical_warning_summary', 'Endurance Group Warning', lambda v: 'OK' if v == 0 else f'0x{v:02X}'),
                        ('data_units_read',                     'Data Units Read',          lambda v: f"{v:,}"),
                        ('data_units_written',                  'Data Units Written',       lambda v: f"{v:,}"),
                        ('host_read_commands',                  'Host Read Commands',       lambda v: f"{v:,}"),
                        ('host_write_commands',                 'Host Write Commands',      lambda v: f"{v:,}"),
                        ('controller_busy_time',                'Controller Busy Time',     lambda v: f"{v:,} min"),
                        ('power_cycles',                        'Power Cycles',             lambda v: f"{v:,}"),
                        ('power_on_hours',                      'Power On Hours',           lambda v: f"{v:,}"),
                        ('unsafe_shutdowns',                    'Unsafe Shutdowns',         lambda v: f"{v:,}"),
                        ('media_errors',                        'Media Errors',             lambda v: f"{v:,}"),
                        ('num_err_log_entries',                 'Error Log Entries',        lambda v: f"{v:,}"),
                        ('warning_temp_time',                   'Warning Temp Time',        lambda v: f"{v:,} min"),
                        ('critical_comp_time',                  'Critical Temp Time',       lambda v: f"{v:,} min"),
                    ]

                    for i, (field, name, formatter) in enumerate(nvme_field_map, start=1):
                        if field in nvme_data:
                            raw_val = nvme_data[field]
                            if field == 'critical_warning':
                                status = 'ok' if raw_val == 0 else 'critical'
                            elif field == 'media_errors':
                                status = 'ok' if raw_val == 0 else 'critical'
                            elif field == 'percent_used':
                                status = 'ok' if raw_val < 90 else 'warning' if raw_val < 100 else 'critical'
                            elif field == 'avail_spare':
                                thresh = nvme_data.get('spare_thresh', 10)
                                status = 'ok' if raw_val > thresh else 'warning'
                            elif field == 'unsafe_shutdowns':
                                status = 'ok' if raw_val < 100 else 'warning'
                            elif field in ('warning_temp_time', 'critical_comp_time'):
                                status = 'ok' if raw_val == 0 else 'warning'
                            elif field == 'endurance_grp_critical_warning_summary':
                                status = 'ok' if raw_val == 0 else 'warning'
                            else:
                                status = 'ok'

                            nvme_attrs.append({
                                'id': i,
                                'name': name,
                                'value': formatter(raw_val),
                                'worst': '-',
                                'threshold': '-',
                                'raw_value': str(raw_val),
                                'status': status
                            })

                    # Temperature sensors array (composite + hotspot)
                    temp_sensors = nvme_data.get('temperature_sensors', [])
                    temp_sensors_celsius = []
                    for s in temp_sensors:
                        if s is not None:
                            temp_sensors_celsius.append(s - 273 if s > 200 else s)
                        else:
                            temp_sensors_celsius.append(None)

                    result['smart_data'] = {
                        'device': disk_name,
                        'model': _sctl_identity.get('model', 'Unknown'),
                        'serial': _sctl_identity.get('serial', 'Unknown'),
                        'firmware': _sctl_identity.get('firmware', 'Unknown'),
                        'nvme_version': _sctl_identity.get('nvme_version', ''),
                        'smart_status': result.get('smart_status', 'unknown'),
                        'temperature': temp_celsius,
                        'temperature_sensors': temp_sensors_celsius,
                        'power_on_hours': nvme_data.get('power_on_hours', 0),
                        'power_cycles': nvme_data.get('power_cycles', 0),
                        'supports_progress_reporting': True,
                        'attributes': nvme_attrs,
                        'nvme_raw': {
                            'critical_warning':                     nvme_data.get('critical_warning', 0),
                            'temperature':                          temp_celsius,
                            'avail_spare':                          nvme_data.get('avail_spare', 100),
                            'spare_thresh':                         nvme_data.get('spare_thresh', 10),
                            'percent_used':                         nvme_data.get('percent_used', 0),
                            'endurance_grp_critical_warning_summary': nvme_data.get('endurance_grp_critical_warning_summary', 0),
                            'data_units_read':                      nvme_data.get('data_units_read', 0),
                            'data_units_written':                   nvme_data.get('data_units_written', 0),
                            'host_read_commands':                   nvme_data.get('host_read_commands', 0),
                            'host_write_commands':                  nvme_data.get('host_write_commands', 0),
                            'controller_busy_time':                 nvme_data.get('controller_busy_time', 0),
                            'power_cycles':                         nvme_data.get('power_cycles', 0),
                            'power_on_hours':                       nvme_data.get('power_on_hours', 0),
                            'unsafe_shutdowns':                     nvme_data.get('unsafe_shutdowns', 0),
                            'media_errors':                         nvme_data.get('media_errors', 0),
                            'num_err_log_entries':                  nvme_data.get('num_err_log_entries', 0),
                            'warning_temp_time':                    nvme_data.get('warning_temp_time', 0),
                            'critical_comp_time':                   nvme_data.get('critical_comp_time', 0),
                            'temperature_sensors':                  temp_sensors_celsius,
                        }
                    }

                    # Update last_test with power_on_hours if available
                    if 'last_test' in result and nvme_data.get('power_on_hours'):
                        result['last_test']['lifetime_hours'] = nvme_data['power_on_hours']
                else:
                    result['nvme_error'] = proc.stderr.strip() or 'Failed to read SMART data'
            except subprocess.TimeoutExpired:
                result['nvme_error'] = 'Command timeout'
            except Exception as e:
                result['nvme_error'] = str(e)
        else:
            # SATA/SAS/SSD: Single JSON call gives all data at once
            proc = subprocess.run(
                ['smartctl', '-a', '--json=c', device],
                capture_output=True, text=True, timeout=30
            )
            # Parse JSON regardless of exit code — smartctl uses bit-flags for non-fatal conditions
            data = {}
            try:
                data = json.loads(proc.stdout)
            except (json.JSONDecodeError, ValueError):
                pass

            # --- Detect device protocol (ATA vs SCSI/SAS) ---
            device_protocol = data.get('device', {}).get('protocol', '')
            is_scsi = device_protocol == 'SCSI' or 'scsi_error_counter_log' in data or 'scsi_grown_defect_list' in data

            ata_data = data.get('ata_smart_data', {})
            capabilities = ata_data.get('capabilities', {})

            # --- Detect test in progress ---
            if is_scsi:
                # SCSI: check background self-test status
                scsi_selftest_status = data.get('scsi_self_test', {}).get('status', {})
                scsi_st_value = scsi_selftest_status.get('value', 0)
                # value 15 = in progress on SCSI
                if scsi_st_value == 15:
                    result['status'] = 'running'
                    remaining_pct = scsi_selftest_status.get('remaining_percent')
                    if remaining_pct is not None:
                        result['progress'] = 100 - remaining_pct
            else:
                self_test_block = ata_data.get('self_test', {})
                st_status = self_test_block.get('status', {})
                st_value = st_status.get('value', 0)
                remaining_pct = st_status.get('remaining_percent')
                # smartctl status value 241 (0xF1) = self-test in progress
                if st_value == 241 or (remaining_pct is not None and 0 < remaining_pct <= 100):
                    result['status'] = 'running'
                    if remaining_pct is not None:
                        result['progress'] = 100 - remaining_pct

            # Fallback text detection in case JSON misses it
            if result['status'] != 'running':
                try:
                    cproc = subprocess.run(['smartctl', '-c', device], capture_output=True, text=True, timeout=10)
                    if 'Self-test routine in progress' in cproc.stdout or '% of test remaining' in cproc.stdout:
                        result['status'] = 'running'
                        match = re.search(r'(\d+)% of test remaining', cproc.stdout)
                        if match:
                            result['progress'] = 100 - int(match.group(1))
                except Exception:
                    pass

            # --- Progress reporting capability ---
            if is_scsi:
                # SAS drives generally support self-test progress via SCSI log pages
                result['supports_progress_reporting'] = True
                result['supports_self_test'] = True
            else:
                has_self_test_block = 'self_test' in ata_data
                supports_self_test = capabilities.get('self_tests_supported', False) or has_self_test_block
                result['supports_progress_reporting'] = has_self_test_block
                result['supports_self_test'] = supports_self_test

            # --- SMART health status ---
            if data.get('smart_status', {}).get('passed') is True:
                result['smart_status'] = 'passed'
            elif data.get('smart_status', {}).get('passed') is False:
                result['smart_status'] = 'failed'
            else:
                result['smart_status'] = 'unknown'

            # --- Device identity fields ---
            model_family = data.get('model_family', '')
            form_factor = data.get('form_factor', {}).get('name', '')
            physical_block_size = data.get('physical_block_size', 512)
            trim_supported = data.get('trim', {}).get('supported', False)
            sata_version = data.get('sata_version', {}).get('string', '')
            interface_speed = data.get('interface_speed', {}).get('current', {}).get('string', '')
            # SAS-specific: scsi_transport_protocol and logical_block_size
            scsi_transport = data.get('scsi_transport_protocol', {}).get('name', '')
            scsi_product = data.get('scsi_product', '')
            scsi_vendor = data.get('scsi_vendor', '')
            scsi_revision = data.get('scsi_revision', '')
            logical_block_size = data.get('logical_block_size', 512)

            # --- Self-test polling times ---
            if is_scsi:
                polling_short = None
                polling_extended = None
            else:
                self_test_block = ata_data.get('self_test', {})
                polling_short = self_test_block.get('polling_minutes', {}).get('short')
                polling_extended = self_test_block.get('polling_minutes', {}).get('extended')

            # --- Error log count ---
            if is_scsi:
                # For SCSI, sum uncorrected errors across read/write/verify
                ecl = data.get('scsi_error_counter_log', {})
                error_log_count = (
                    ecl.get('read', {}).get('total_uncorrected_errors', 0) +
                    ecl.get('write', {}).get('total_uncorrected_errors', 0) +
                    ecl.get('verify', {}).get('total_uncorrected_errors', 0)
                )
            else:
                error_log_count = data.get('ata_smart_error_log', {}).get('summary', {}).get('count', 0)

            # --- Self-test history ---
            self_test_history = []
            if is_scsi:
                # SCSI self-test log format
                scsi_st_table = data.get('scsi_self_test_log', {}).get('table', [])
                for entry in scsi_st_table:
                    code = entry.get('code', {})
                    type_str = code.get('string', 'Unknown')
                    t_norm = 'short' if 'Short' in type_str or 'short' in type_str else 'long' if ('Extended' in type_str or 'Long' in type_str or 'long' in type_str) else 'other'
                    result_val = entry.get('result', {}).get('value', 0)
                    passed_flag = result_val == 0  # 0 = completed without error
                    result_str = entry.get('result', {}).get('string', '')
                    self_test_history.append({
                        'type': t_norm,
                        'type_str': type_str,
                        'status': 'passed' if passed_flag else 'failed',
                        'status_str': result_str,
                        'lifetime_hours': entry.get('power_on_time', {}).get('hours'),
                    })
            else:
                st_table = data.get('ata_smart_self_test_log', {}).get('standard', {}).get('table', [])
                for entry in st_table:
                    type_str = entry.get('type', {}).get('string', 'Unknown')
                    t_norm = 'short' if 'Short' in type_str else 'long' if ('Extended' in type_str or 'Long' in type_str) else 'other'
                    st_entry = entry.get('status', {})
                    # Never default to True — if 'passed' field is missing, determine from status string
                    if 'passed' in st_entry:
                        passed_flag = st_entry['passed']
                    else:
                        status_string = st_entry.get('string', '').lower()
                        passed_flag = 'without error' in status_string or 'completed' in status_string
                    self_test_history.append({
                        'type': t_norm,
                        'type_str': type_str,
                        'status': 'passed' if passed_flag else 'failed',
                        'status_str': st_entry.get('string', ''),
                        'lifetime_hours': entry.get('lifetime_hours'),
                    })

            if self_test_history:
                result['last_test'] = {
                    'type': self_test_history[0]['type'],
                    'status': self_test_history[0]['status'],
                    'timestamp': self_test_history[0]['status_str'] or 'Completed',
                    'lifetime_hours': self_test_history[0]['lifetime_hours']
                }

            # --- Parse SMART attributes ---
            attrs = []

            if is_scsi:
                # SCSI/SAS: Build virtual attributes from SCSI log pages
                # These disks don't have ATA attribute IDs — we synthesize a table
                ecl = data.get('scsi_error_counter_log', {})
                attr_idx = 1

                # Grown Defect List (equivalent to Reallocated Sectors)
                gdl = data.get('scsi_grown_defect_list', 0)
                if isinstance(gdl, dict):
                    gdl = gdl.get('count', 0)
                gdl_status = 'ok' if gdl == 0 else ('warning' if gdl < 50 else 'critical')
                attrs.append({
                    'id': attr_idx, 'name': 'Grown Defect List',
                    'value': '-', 'worst': '-', 'threshold': '-',
                    'raw_value': str(gdl), 'status': gdl_status
                })
                attr_idx += 1

                # Read Error Counters
                read_log = ecl.get('read', {})
                read_corrected_fast = read_log.get('errors_corrected_by_eccfast', 0)
                read_corrected_delayed = read_log.get('errors_corrected_by_eccdelayed', 0)
                read_total_corrected = read_log.get('total_errors_corrected', 0)
                read_uncorrected = read_log.get('total_uncorrected_errors', 0)
                read_processed = read_log.get('gigabytes_processed', 0)

                attrs.append({
                    'id': attr_idx, 'name': 'Read Errors Corrected',
                    'value': '-', 'worst': '-', 'threshold': '-',
                    'raw_value': f'{read_total_corrected:,}', 'status': 'ok'
                })
                attr_idx += 1

                if read_corrected_fast or read_corrected_delayed:
                    attrs.append({
                        'id': attr_idx, 'name': 'Read ECC Fast',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{read_corrected_fast:,}', 'status': 'ok'
                    })
                    attr_idx += 1
                    attrs.append({
                        'id': attr_idx, 'name': 'Read ECC Delayed',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{read_corrected_delayed:,}',
                        'status': 'ok' if read_corrected_delayed == 0 else 'warning'
                    })
                    attr_idx += 1

                read_unc_status = 'ok' if read_uncorrected == 0 else 'critical'
                attrs.append({
                    'id': attr_idx, 'name': 'Read Uncorrected Errors',
                    'value': '-', 'worst': '-', 'threshold': '-',
                    'raw_value': str(read_uncorrected), 'status': read_unc_status
                })
                attr_idx += 1

                if read_processed:
                    attrs.append({
                        'id': attr_idx, 'name': 'Read Data Processed',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{read_processed:,.2f} GB', 'status': 'ok'
                    })
                    attr_idx += 1

                # Write Error Counters
                write_log = ecl.get('write', {})
                write_total_corrected = write_log.get('total_errors_corrected', 0)
                write_uncorrected = write_log.get('total_uncorrected_errors', 0)
                write_processed = write_log.get('gigabytes_processed', 0)

                attrs.append({
                    'id': attr_idx, 'name': 'Write Errors Corrected',
                    'value': '-', 'worst': '-', 'threshold': '-',
                    'raw_value': f'{write_total_corrected:,}', 'status': 'ok'
                })
                attr_idx += 1

                write_unc_status = 'ok' if write_uncorrected == 0 else 'critical'
                attrs.append({
                    'id': attr_idx, 'name': 'Write Uncorrected Errors',
                    'value': '-', 'worst': '-', 'threshold': '-',
                    'raw_value': str(write_uncorrected), 'status': write_unc_status
                })
                attr_idx += 1

                if write_processed:
                    attrs.append({
                        'id': attr_idx, 'name': 'Write Data Processed',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{write_processed:,.2f} GB', 'status': 'ok'
                    })
                    attr_idx += 1

                # Verify Error Counters (background verify operations)
                verify_log = ecl.get('verify', {})
                if verify_log:
                    verify_total_corrected = verify_log.get('total_errors_corrected', 0)
                    verify_uncorrected = verify_log.get('total_uncorrected_errors', 0)

                    attrs.append({
                        'id': attr_idx, 'name': 'Verify Errors Corrected',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{verify_total_corrected:,}', 'status': 'ok'
                    })
                    attr_idx += 1

                    verify_unc_status = 'ok' if verify_uncorrected == 0 else 'critical'
                    attrs.append({
                        'id': attr_idx, 'name': 'Verify Uncorrected Errors',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': str(verify_uncorrected), 'status': verify_unc_status
                    })
                    attr_idx += 1

                # Non-medium errors (controller/bus errors, not media-related)
                non_medium = data.get('scsi_error_counter_log', {}).get('non_medium_error', {}).get('count')
                if non_medium is not None:
                    nm_status = 'ok' if non_medium < 100 else 'warning'
                    attrs.append({
                        'id': attr_idx, 'name': 'Non-Medium Errors',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{non_medium:,}', 'status': nm_status
                    })
                    attr_idx += 1

                # Temperature
                temp_val = data.get('temperature', {}).get('current', 0)
                if temp_val > 0:
                    temp_status = 'ok' if temp_val <= 55 else ('warning' if temp_val <= 65 else 'critical')
                    attrs.append({
                        'id': attr_idx, 'name': 'Temperature',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{temp_val}°C', 'status': temp_status
                    })
                    attr_idx += 1

                # Power-On Hours
                poh_val = data.get('power_on_time', {}).get('hours', 0)
                if poh_val > 0:
                    attrs.append({
                        'id': attr_idx, 'name': 'Power On Hours',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{poh_val:,}', 'status': 'ok'
                    })
                    attr_idx += 1

                # Start-Stop Cycle Counter
                scsi_ssc = data.get('scsi_start_stop_cycle_counter', {})
                acc_cycles = scsi_ssc.get('accumulated_start_stop_cycles')
                spec_cycles = scsi_ssc.get('specified_cycle_count_over_device_lifetime')
                if acc_cycles is not None:
                    cycle_status = 'ok'
                    if spec_cycles and spec_cycles > 0:
                        usage_ratio = acc_cycles / spec_cycles
                        cycle_status = 'ok' if usage_ratio < 0.8 else ('warning' if usage_ratio < 0.95 else 'critical')
                    attrs.append({
                        'id': attr_idx, 'name': 'Start-Stop Cycles',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{acc_cycles:,}' + (f' / {spec_cycles:,}' if spec_cycles else ''),
                        'status': cycle_status
                    })
                    attr_idx += 1

                # Load-Unload Cycle Counter (for SAS HDDs)
                acc_load = scsi_ssc.get('accumulated_load_unload_cycles')
                spec_load = scsi_ssc.get('specified_load_unload_count_over_device_lifetime')
                if acc_load is not None:
                    load_status = 'ok'
                    if spec_load and spec_load > 0:
                        load_ratio = acc_load / spec_load
                        load_status = 'ok' if load_ratio < 0.8 else ('warning' if load_ratio < 0.95 else 'critical')
                    attrs.append({
                        'id': attr_idx, 'name': 'Load-Unload Cycles',
                        'value': '-', 'worst': '-', 'threshold': '-',
                        'raw_value': f'{acc_load:,}' + (f' / {spec_load:,}' if spec_load else ''),
                        'status': load_status
                    })
                    attr_idx += 1

                # Background scan results
                bg_scan = data.get('scsi_background_scan_results', {})
                if bg_scan:
                    bg_status_val = bg_scan.get('status', {}).get('value', 0)
                    bg_scan_progress = bg_scan.get('status', {}).get('string', '')
                    scan_errors = bg_scan.get('number_of_background_medium_scans_performed', 0)
                    bg_media_errors = bg_scan.get('number_of_background_scans_performed', 0)

                    if 'scan_errors' in bg_scan or bg_status_val > 0:
                        attrs.append({
                            'id': attr_idx, 'name': 'Background Scan Status',
                            'value': '-', 'worst': '-', 'threshold': '-',
                            'raw_value': bg_scan_progress or 'OK',
                            'status': 'ok' if bg_status_val == 0 else 'warning'
                        })
                        attr_idx += 1

                # SAS PHY log (link errors)
                sas_phy = data.get('sas_phy_event_counter_log', [])
                if sas_phy:
                    for phy_entry in sas_phy[:1]:  # First PHY only
                        events = phy_entry.get('phy_event_counters', [])
                        for ev in events:
                            ev_name = ev.get('name', '')
                            ev_value = ev.get('value', 0)
                            if ev_value > 0 and ('error' in ev_name.lower() or 'invalid' in ev_name.lower()):
                                attrs.append({
                                    'id': attr_idx, 'name': ev_name[:40],
                                    'value': '-', 'worst': '-', 'threshold': '-',
                                    'raw_value': f'{ev_value:,}',
                                    'status': 'warning' if ev_value < 100 else 'critical'
                                })
                                attr_idx += 1

            else:
                # ATA: Parse SMART attributes from JSON
                ata_attrs = data.get('ata_smart_attributes', {}).get('table', [])
                for attr in ata_attrs:
                    attr_id = attr.get('id')
                    name = attr.get('name', '')
                    value = attr.get('value', 0)
                    worst = attr.get('worst', 0)
                    thresh = attr.get('thresh', 0)
                    raw_obj = attr.get('raw', {})
                    raw_value = raw_obj.get('string', str(raw_obj.get('value', 0)))
                    flags = attr.get('flags', {})
                    prefailure = flags.get('prefailure', False)
                    when_failed = attr.get('when_failed', '')

                    if when_failed == 'now':
                        status = 'critical'
                    elif prefailure and thresh > 0 and value <= thresh:
                        status = 'critical'
                    elif prefailure and thresh > 0:
                        # Proportional margin: smaller when thresh is close to 100
                        # thresh=97 → margin 2, thresh=50 → margin 10, thresh=10 → margin 10
                        warn_margin = min(10, max(2, (100 - thresh) // 3))
                        status = 'warning' if value <= thresh + warn_margin else 'ok'
                    else:
                        status = 'ok'

                    attrs.append({
                        'id': attr_id,
                        'name': name,
                        'value': value,
                        'worst': worst,
                        'threshold': thresh,
                        'raw_value': raw_value,
                        'status': status,
                        'prefailure': prefailure,
                        'flags': flags.get('string', '').strip()
                    })

                # Fallback: if JSON gave no attributes, try text parser
                if not attrs:
                    try:
                        aproc = subprocess.run(['smartctl', '-A', device], capture_output=True, text=True, timeout=10)
                        if aproc.returncode == 0:
                            attrs = _parse_smart_attributes(aproc.stdout.split('\n'))
                    except Exception:
                        pass

            # --- Build enriched smart_data ---
            temp = data.get('temperature', {}).get('current', 0)
            poh = data.get('power_on_time', {}).get('hours', 0)
            cycles = data.get('power_cycle_count', 0)
            if cycles == 0 and is_scsi:
                cycles = data.get('scsi_start_stop_cycle_counter', {}).get('accumulated_start_stop_cycles', 0)

            result['smart_data'] = {
                'device': disk_name,
                'model': data.get('model_name', '') or (f'{scsi_vendor} {scsi_product}'.strip() if is_scsi else 'Unknown'),
                'model_family': model_family,
                'serial': data.get('serial_number', 'Unknown'),
                'firmware': data.get('firmware_version', '') or scsi_revision or 'Unknown',
                'smart_status': result.get('smart_status', 'unknown'),
                'temperature': temp,
                'power_on_hours': poh,
                'power_cycles': cycles,
                'rotation_rate': data.get('rotation_rate', 0),
                'form_factor': form_factor,
                'physical_block_size': physical_block_size,
                'trim_supported': trim_supported,
                'sata_version': sata_version if not is_scsi else '',
                'interface_speed': interface_speed or (scsi_transport if is_scsi else ''),
                'polling_minutes_short': polling_short,
                'polling_minutes_extended': polling_extended,
                'supports_progress_reporting': result.get('supports_progress_reporting', False),
                'error_log_count': error_log_count,
                'self_test_history': self_test_history,
                'attributes': attrs,
                'is_sas': is_scsi,
                'logical_block_size': logical_block_size if is_scsi else None,
            }
        
        return jsonify(result)
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/<disk_name>/history', methods=['GET'])
@require_auth
def api_smart_history(disk_name):
    """Get SMART test history for a disk."""
    try:
        # Validate disk name (security)
        if not re.match(r'^[a-zA-Z0-9]+$', disk_name):
            return jsonify({'error': 'Invalid disk name'}), 400
        
        limit = request.args.get('limit', 20, type=int)
        history = _get_smart_history(disk_name, limit=limit)
        
        return jsonify({
            'disk': disk_name,
            'history': history,
            'total': len(history)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/<disk_name>/history/<filename>', methods=['GET'])
@require_auth
def api_smart_history_download(disk_name, filename):
    """Download a specific SMART test JSON file."""
    try:
        if not re.match(r'^[a-zA-Z0-9]+$', disk_name):
            return jsonify({'error': 'Invalid disk name'}), 400
        if not re.match(r'^[\w\-\.]+\.json$', filename):
            return jsonify({'error': 'Invalid filename'}), 400
        disk_dir = _get_smart_disk_dir(disk_name)
        filepath = os.path.join(disk_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        if not os.path.realpath(filepath).startswith(os.path.realpath(disk_dir)):
            return jsonify({'error': 'Invalid path'}), 403
        return send_file(filepath, as_attachment=True, download_name=f'{disk_name}_{filename}')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/<disk_name>/history/<filename>', methods=['DELETE'])
@require_auth
def api_smart_history_delete(disk_name, filename):
    """Delete a specific SMART test JSON file."""
    try:
        if not re.match(r'^[a-zA-Z0-9]+$', disk_name):
            return jsonify({'error': 'Invalid disk name'}), 400
        if not re.match(r'^[\w\-\.]+\.json$', filename):
            return jsonify({'error': 'Invalid filename'}), 400
        disk_dir = _get_smart_disk_dir(disk_name)
        filepath = os.path.join(disk_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        # Ensure path stays within smart directory (prevent traversal)
        if not os.path.realpath(filepath).startswith(os.path.realpath(disk_dir)):
            return jsonify({'error': 'Invalid path'}), 403
        os.remove(filepath)
        return jsonify({'success': True, 'deleted': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/<disk_name>/latest', methods=['GET'])
@require_auth
def api_smart_latest(disk_name):
    """Get the most recent SMART JSON data for a disk."""
    try:
        # Validate disk name (security)
        if not re.match(r'^[a-zA-Z0-9]+$', disk_name):
            return jsonify({'error': 'Invalid disk name'}), 400
        
        json_path = _get_latest_smart_json(disk_name)
        if not json_path or not os.path.exists(json_path):
            return jsonify({
                'disk': disk_name,
                'has_data': False,
                'message': 'No SMART test data available. Run a SMART test first.'
            })
        
        with open(json_path, 'r') as f:
            smart_data = json.load(f)
        
        # Extract timestamp from filename
        filename = os.path.basename(json_path)
        parts = filename.replace('.json', '').split('_')
        timestamp = None
        test_type = 'unknown'
        if len(parts) >= 2:
            try:
                dt = datetime.strptime(parts[0], '%Y-%m-%dT%H-%M-%S')
                timestamp = dt.isoformat()
                test_type = parts[1]
            except ValueError:
                pass
        
        return jsonify({
            'disk': disk_name,
            'has_data': True,
            'data': smart_data,
            'timestamp': timestamp,
            'test_type': test_type,
            'path': json_path
        })
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON data in saved file'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/<disk_name>/test', methods=['POST'])
@require_auth
def api_smart_run_test(disk_name):
    """Start a SMART self-test on a disk."""
    try:
        # Validate disk name (security)
        if not re.match(r'^[a-zA-Z0-9]+$', disk_name):
            return jsonify({'error': 'Invalid disk name'}), 400
        
        device = f'/dev/{disk_name}'
        if not os.path.exists(device):
            return jsonify({'error': 'Device not found'}), 404
        
        data = request.get_json() or {}
        test_type = data.get('test_type', 'short')
        
        if test_type not in ('short', 'long'):
            return jsonify({'error': 'Invalid test type. Use "short" or "long"'}), 400
        
        is_nvme = _is_nvme(disk_name)
        
        # Check tools and auto-install if missing
        tools = _ensure_smart_tools(install_if_missing=True)
        
        # Ensure SMART directory exists and get path for new JSON file
        os.makedirs(SMART_DIR, exist_ok=True)
        json_path = _get_smart_json_path(disk_name, test_type)
        
        # Cleanup old JSON files based on retention policy
        _cleanup_old_smart_jsons(disk_name)
        
        if is_nvme:
            if not tools['nvme']:
                return jsonify({'error': 'nvme-cli not installed. Please run: apt-get install nvme-cli'}), 400
            
            # NVMe: self-test-code 1=short, 2=long
            code = 1 if test_type == 'short' else 2
            
            # First check if device is accessible
            check_proc = subprocess.run(
                ['nvme', 'id-ctrl', device],
                capture_output=True, text=True, timeout=10
            )
            if check_proc.returncode != 0:
                return jsonify({'error': f'Cannot access NVMe device: {check_proc.stderr.strip() or "Device not responding"}'}), 500
            
            # Check if device supports self-test by looking at OACS field
            # OACS bit 4 (0x10) indicates Device Self-test support
            oacs_output = check_proc.stdout
            supports_selftest = True  # Assume supported by default
            for line in oacs_output.split('\n'):
                if 'oacs' in line.lower():
                    try:
                        # Parse OACS value (usually in hex)
                        oacs_val = int(line.split(':')[-1].strip(), 0)
                        if not (oacs_val & 0x10):
                            supports_selftest = False
                    except (ValueError, IndexError):
                        pass
                    break
            
            if not supports_selftest:
                return jsonify({'error': 'This NVMe device does not support self-test (OACS bit 4 not set)'}), 400
            
            proc = subprocess.run(
                ['nvme', 'device-self-test', device, f'--self-test-code={code}'],
                capture_output=True, text=True, timeout=30
            )
            
            if proc.returncode != 0:
                error_msg = proc.stderr.strip() or proc.stdout.strip() or 'Unknown error'
                # Test already in progress - return success so frontend shows progress
                if 'in progress' in error_msg.lower() or '0x211d' in error_msg.lower():
                    return jsonify({
                        'success': True,
                        'message': 'Test started successfully',
                        'test_type': test_type
                    }), 200
                # Some NVMe devices don't support self-test
                if 'not support' in error_msg.lower() or 'invalid' in error_msg.lower():
                    return jsonify({'error': f'This NVMe device does not support self-test: {error_msg}'}), 400
                # Check for permission errors
                if 'permission' in error_msg.lower() or 'operation not permitted' in error_msg.lower():
                    return jsonify({'error': f'Permission denied. Run as root: {error_msg}'}), 403
                return jsonify({'error': f'Failed to start test: {error_msg}'}), 500
            
            # Start background monitor to save JSON when test completes
            # Check 'Current Device Self-Test Operation' field - if > 0, test is running
            sleep_interval = 10 if test_type == 'short' else 60
            subprocess.Popen(
                f'''
                sleep 5
                while true; do
                    op=$(nvme self-test-log {device} -o json 2>/dev/null | grep -o '"Current Device Self-Test Operation":[0-9]*' | grep -o '[0-9]*$')
                    [ -z "$op" ] || [ "$op" -eq 0 ] && break
                    sleep {sleep_interval}
                done
                # Save complete data: smartctl gives device info + health + self-test log in one JSON
                smartctl -a --json=c {device} > {json_path} 2>/dev/null
                # Fallback to nvme smart-log if smartctl fails
                [ ! -s {json_path} ] && nvme smart-log -o json {device} > {json_path} 2>/dev/null
                ''',
                shell=True, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            if not tools['smartctl']:
                return jsonify({'error': 'smartmontools not installed. Please run: apt-get install smartmontools'}), 400
            
            test_flag = '-t short' if test_type == 'short' else '-t long'
            proc = subprocess.run(
                ['smartctl'] + test_flag.split() + [device],
                capture_output=True, text=True, timeout=30
            )
            
            if proc.returncode not in (0, 4):  # 4 = test started successfully
                return jsonify({'error': f'Failed to start test: {proc.stderr}'}), 500
            
            # Start background monitor to save JSON when test completes
            sleep_interval = 10 if test_type == 'short' else 60
            subprocess.Popen(
                f'''
                sleep 5
                while smartctl -c {device} 2>/dev/null | grep -qiE 'Self-test routine in progress|[1-9][0-9]?% of test remaining'; do
                    sleep {sleep_interval}
                done
                smartctl -a --json=c {device} > {json_path} 2>/dev/null
                ''',
                shell=True, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        
        return jsonify({
            'success': True,
            'test_type': test_type,
            'device': device,
            'message': f'{test_type.capitalize()} test started on {device}'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── SMART Schedule API ───────────────────────────────────────────────────────

SMART_SCHEDULE_FILE = os.path.join(SMART_CONFIG_DIR, 'smart-schedule.json')
SMART_CRON_FILE = '/etc/cron.d/proxmenux-smart'

def _load_smart_schedules():
    """Load SMART test schedules from config file."""
    os.makedirs(SMART_CONFIG_DIR, exist_ok=True)
    if os.path.exists(SMART_SCHEDULE_FILE):
        try:
            with open(SMART_SCHEDULE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {'enabled': True, 'schedules': []}

def _save_smart_schedules(config):
    """Save SMART test schedules to config file."""
    os.makedirs(SMART_CONFIG_DIR, exist_ok=True)
    with open(SMART_SCHEDULE_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def _update_smart_cron():
    """Update cron file based on current schedules."""
    config = _load_smart_schedules()
    
    if not config.get('enabled') or not config.get('schedules'):
        # Remove cron file if disabled or no schedules
        if os.path.exists(SMART_CRON_FILE):
            os.remove(SMART_CRON_FILE)
        return
    
    cron_lines = [
        '# ProxMenux SMART Scheduled Tests',
        '# Auto-generated - do not edit manually',
        'SHELL=/bin/bash',
        'PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin',
        ''
    ]
    
    for schedule in config['schedules']:
        if not schedule.get('active', True):
            continue
        
        schedule_id = schedule.get('id', 'unknown')
        hour = schedule.get('hour', 3)
        minute = schedule.get('minute', 0)
        frequency = schedule.get('frequency', 'weekly')
        
        # Build cron time specification
        if frequency == 'daily':
            cron_time = f'{minute} {hour} * * *'
        elif frequency == 'weekly':
            dow = schedule.get('day_of_week', 0)  # 0=Sunday
            cron_time = f'{minute} {hour} * * {dow}'
        elif frequency == 'monthly':
            dom = schedule.get('day_of_month', 1)
            cron_time = f'{minute} {hour} {dom} * *'
        else:
            continue
        
        # Build command
        disks = schedule.get('disks', ['all'])
        test_type = schedule.get('test_type', 'short')
        retention = schedule.get('retention', 10)
        
        cmd = f'/usr/local/share/proxmenux/scripts/smart-scheduled-test.sh --schedule-id {schedule_id} --test-type {test_type} --retention {retention}'
        if disks != ['all']:
            cmd += f" --disks '{','.join(disks)}'"
        
        cron_lines.append(f'{cron_time} root {cmd} >> /var/log/proxmenux/smart-schedule.log 2>&1')
    
    cron_lines.append('')  # Empty line at end
    
    with open(SMART_CRON_FILE, 'w') as f:
        f.write('\n'.join(cron_lines))
    
    # Set proper permissions
    os.chmod(SMART_CRON_FILE, 0o644)


@app.route('/api/storage/smart/schedules', methods=['GET'])
@require_auth
def api_smart_schedules_list():
    """Get all SMART test schedules."""
    config = _load_smart_schedules()
    return jsonify(config)


@app.route('/api/storage/smart/schedules', methods=['POST'])
@require_auth
def api_smart_schedules_create():
    """Create or update a SMART test schedule."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        config = _load_smart_schedules()
        
        # Generate ID if not provided
        schedule_id = data.get('id') or f"schedule-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        data['id'] = schedule_id
        
        # Set defaults
        data.setdefault('active', True)
        data.setdefault('test_type', 'short')
        data.setdefault('frequency', 'weekly')
        data.setdefault('hour', 3)
        data.setdefault('minute', 0)
        data.setdefault('day_of_week', 0)
        data.setdefault('day_of_month', 1)
        data.setdefault('disks', ['all'])
        data.setdefault('retention', 10)
        data.setdefault('notify_on_complete', True)
        data.setdefault('notify_only_on_failure', False)
        
        # Update existing or add new
        existing_idx = next((i for i, s in enumerate(config['schedules']) if s['id'] == schedule_id), None)
        if existing_idx is not None:
            config['schedules'][existing_idx] = data
        else:
            config['schedules'].append(data)
        
        _save_smart_schedules(config)
        _update_smart_cron()
        
        return jsonify({
            'success': True,
            'schedule': data,
            'message': 'Schedule saved successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/schedules/<schedule_id>', methods=['DELETE'])
@require_auth
def api_smart_schedules_delete(schedule_id):
    """Delete a SMART test schedule."""
    try:
        config = _load_smart_schedules()
        
        original_len = len(config['schedules'])
        config['schedules'] = [s for s in config['schedules'] if s['id'] != schedule_id]
        
        if len(config['schedules']) == original_len:
            return jsonify({'error': 'Schedule not found'}), 404
        
        _save_smart_schedules(config)
        _update_smart_cron()
        
        return jsonify({
            'success': True,
            'message': 'Schedule deleted successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/schedules/toggle', methods=['POST'])
@require_auth
def api_smart_schedules_toggle():
    """Enable or disable all SMART test schedules."""
    try:
        data = request.get_json() or {}
        enabled = data.get('enabled', True)
        
        config = _load_smart_schedules()
        config['enabled'] = enabled
        
        _save_smart_schedules(config)
        _update_smart_cron()
        
        return jsonify({
            'success': True,
            'enabled': enabled,
            'message': f'SMART schedules {"enabled" if enabled else "disabled"}'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/storage/smart/tools', methods=['GET'])
@require_auth
def api_smart_tools_status():
    """Check if SMART tools are installed."""
    tools = _ensure_smart_tools()
    return jsonify(tools)


@app.route('/api/storage/smart/tools/install', methods=['POST'])
@require_auth
def api_smart_tools_install():
    """Install SMART tools (smartmontools and nvme-cli)."""
    try:
        data = request.get_json() or {}
        install_all = data.get('install_all', False)
        packages = data.get('packages', ['smartmontools', 'nvme-cli'] if install_all else [])
        
        if not packages and install_all:
            packages = ['smartmontools', 'nvme-cli']
        
        if not packages:
            return jsonify({'error': 'No packages specified'}), 400
        
        # Serialise concurrent installs by holding the dpkg lock-frontend.
        # Two parallel `apt-get install` calls otherwise race for it and one
        # silently fails with "Could not get lock" — which we'd return as
        # "Installation failed" with no further detail. Audit Tier 6 —
        # `/api/storage/smart/tools/install` ignora `apt-get update` returncode.
        import fcntl as _fcntl_apt
        _LOCK_PATH = '/var/lib/dpkg/lock-frontend'
        try:
            _lockfd = os.open(_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o640)
        except Exception as e:
            return jsonify({'error': f'cannot open dpkg lock: {e}'}), 500

        try:
            try:
                _fcntl_apt.flock(_lockfd, _fcntl_apt.LOCK_EX | _fcntl_apt.LOCK_NB)
            except BlockingIOError:
                return jsonify({'error': 'apt is busy (another install in progress)'}), 409

            try:
                # Run apt-get update first. Surface its returncode — silently
                # continuing with a stale package cache made post-Bookworm
                # installs fail in confusing ways for the user.
                update_proc = subprocess.run(
                    ['apt-get', 'update'],
                    capture_output=True, text=True, timeout=60
                )
                if update_proc.returncode != 0:
                    return jsonify({
                        'success': False,
                        'error': 'apt-get update failed',
                        'output': (update_proc.stderr or update_proc.stdout)[:1000],
                    }), 500

                results = {}
                all_success = True
                for pkg in packages:
                    if pkg not in ('smartmontools', 'nvme-cli'):
                        results[pkg] = {'success': False, 'error': 'Invalid package name'}
                        all_success = False
                        continue

                    proc = subprocess.run(
                        ['apt-get', 'install', '-y', pkg],
                        capture_output=True, text=True, timeout=120
                    )
                    success = proc.returncode == 0
                    results[pkg] = {
                        'success': success,
                        'output': proc.stdout if success else proc.stderr
                    }
                    if not success:
                        all_success = False

                tools = _ensure_smart_tools()

                return jsonify({
                    'success': all_success,
                    'results': results,
                    'tools': tools
                })
            finally:
                try:
                    _fcntl_apt.flock(_lockfd, _fcntl_apt.LOCK_UN)
                except Exception:
                    pass
        finally:
            try:
                os.close(_lockfd)
            except Exception:
                pass
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Installation timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── END SMART API ────────────────────────────────────────────────────────────


@app.route('/api/network', methods=['GET'])
@require_auth
def api_network():
    """Get network information"""
    return jsonify(get_network_info())

@app.route('/api/network/summary', methods=['GET'])
@require_auth
def api_network_summary():
    """Optimized network summary endpoint - returns basic network info without detailed analysis"""
    try:
        net_io = psutil.net_io_counters()
        net_if_stats = psutil.net_if_stats()
        net_if_addrs = psutil.net_if_addrs()
        
        # Count active interfaces by type
        physical_active = 0
        physical_total = 0
        bridge_active = 0
        bridge_total = 0
        
        physical_interfaces = []
        bridge_interfaces = []
        
        for interface_name, stats in net_if_stats.items():
            # Skip loopback and special interfaces
            if interface_name in ['lo', 'docker0'] or interface_name.startswith(('veth', 'tap', 'fw')):
                continue
            
            is_up = stats.isup
            
            # Classify interface type
            if interface_name.startswith(('enp', 'eth', 'eno', 'ens', 'wlan', 'wlp')):
                physical_total += 1
                if is_up:
                    physical_active += 1
                    # Get IP addresses
                    addresses = []
                    if interface_name in net_if_addrs:
                        for addr in net_if_addrs[interface_name]:
                            if addr.family == socket.AF_INET:
                                addresses.append({'ip': addr.address, 'netmask': addr.netmask})
                    
                    physical_interfaces.append({
                        'name': interface_name,
                        'status': 'up' if is_up else 'down',
                        'addresses': addresses
                    })
            
            elif interface_name.startswith(('vmbr', 'br')):
                bridge_total += 1
                if is_up:
                    bridge_active += 1
                    # Get IP addresses
                    addresses = []
                    if interface_name in net_if_addrs:
                        for addr in net_if_addrs[interface_name]:
                            if addr.family == socket.AF_INET:
                                addresses.append({'ip': addr.address, 'netmask': addr.netmask})
                    
                    bridge_interfaces.append({
                        'name': interface_name,
                        'status': 'up' if is_up else 'down',
                        'addresses': addresses
                    })
        
        return jsonify({
            'physical_active_count': physical_active,
            'physical_total_count': physical_total,
            'bridge_active_count': bridge_active,
            'bridge_total_count': bridge_total,
            'physical_interfaces': physical_interfaces,
            'bridge_interfaces': bridge_interfaces,
            'traffic': {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
        })
    except Exception as e:
        # print(f"[v0] Error in api_network_summary: {e}")
        pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/network/<interface_name>/metrics', methods=['GET'])
@require_auth
def api_network_interface_metrics(interface_name):
    """Get historical metrics (RRD data) for a specific network interface"""
    try:
        timeframe = request.args.get('timeframe', 'day')  # hour, day, week, month, year
        

        
        # Validate timeframe
        valid_timeframes = ['hour', 'day', 'week', 'month', 'year']
        if timeframe not in valid_timeframes:
            # print(f"[v0] ERROR: Invalid timeframe: {timeframe}")
            pass
            return jsonify({'error': f'Invalid timeframe. Must be one of: {", ".join(valid_timeframes)}'}), 400
        
        # Get local node name
        # local_node = socket.gethostname()
        local_node = get_proxmox_node_name()

        
        # Determine interface type and get appropriate RRD data
        interface_type = get_interface_type(interface_name)

        
        rrd_data = []
        
        rrd_error = None
        
        if interface_type == 'vm_lxc':
            # For VM/LXC interfaces, get data from the VM/LXC RRD
            vmid, vm_type = extract_vmid_from_interface(interface_name)
            if vmid:

                rrd_result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/{vm_type}/{vmid}/rrddata',
                                            '--timeframe', timeframe, '--output-format', 'json'],
                                           capture_output=True, text=True, timeout=10)
                
                if rrd_result.returncode == 0:
                    try:
                        all_data = json.loads(rrd_result.stdout)
                        # Filter to only network-related fields
                        for point in all_data:
                            filtered_point = {'time': point.get('time')}
                            # Add network fields if they exist
                            for key in ['netin', 'netout']:
                                if key in point:
                                    filtered_point[key] = point[key]
                            rrd_data.append(filtered_point)
                    except json.JSONDecodeError:
                        rrd_error = f'RRD data for {vm_type.upper()} {vmid} is empty or corrupted'
                else:
                    rrd_error = f'Failed to get RRD data: {rrd_result.stderr}'
        else:
            # For physical/bridge interfaces, get data from node RRD

            rrd_result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/rrddata', 
                                        '--timeframe', timeframe, '--output-format', 'json'],
                                       capture_output=True, text=True, timeout=10)
            
            if rrd_result.returncode == 0:
                try:
                    all_data = json.loads(rrd_result.stdout)
                    # Filter to only network-related fields for this interface
                    for point in all_data:
                        filtered_point = {'time': point.get('time')}
                        # Add network fields if they exist
                        for key in ['netin', 'netout']:
                            if key in point:
                                filtered_point[key] = point[key]
                        rrd_data.append(filtered_point)
                except json.JSONDecodeError:
                    rrd_error = 'Node RRD data is empty or corrupted'
            else:
                rrd_error = f'Failed to get RRD data: {rrd_result.stderr}'
        

        # If there was an RRD error and no data collected, return error with details
        if rrd_error and not rrd_data:
            return jsonify({
                'error': 'RRD data not available',
                'details': rrd_error,
                'suggestion': 'The RRD database may be empty or corrupted. Try: systemctl restart rrdcached'
            }), 503
        
        return jsonify({
            'interface': interface_name,
            'type': interface_type,
            'timeframe': timeframe,
            'data': rrd_data,
            'warning': rrd_error if rrd_error else None  # Include warning if there was an error but some data exists
        })
            
    except Exception as e:

        return jsonify({'error': str(e)}), 500

@app.route('/api/vms', methods=['GET'])
@require_auth
def api_vms():
    """Get virtual machine information"""
    return jsonify(get_proxmox_vms())


@app.route('/api/vms/<int:vmid>/metrics', methods=['GET'])
@require_auth
def api_vm_metrics(vmid):
    """Get historical metrics (RRD data) for a specific VM/LXC"""
    try:
        timeframe = request.args.get('timeframe', 'week')  # hour, day, week, month, year
        

        
        # Validate timeframe
        valid_timeframes = ['hour', 'day', 'week', 'month', 'year']
        if timeframe not in valid_timeframes:
            # print(f"[v0] ERROR: Invalid timeframe: {timeframe}")
            pass
            return jsonify({'error': f'Invalid timeframe. Must be one of: {", ".join(valid_timeframes)}'}), 400
        
        # Get local node name
        local_node = get_proxmox_node_name()

        # Determine if it's a qemu VM or lxc container.
        #
        # Previously this fired up to two `pvesh ... status/current` calls
        # just to find out which one — for an LXC that's ~1.7 s of pure
        # probing overhead before the actual RRD fetch. The cluster
        # resources cache (refreshed every 2 s, populated by /api/vms,
        # /api/cluster, /api/health, etc.) already knows the type of
        # every guest on every node, so we look it up there and skip
        # the probes entirely on the hot path. We only fall back to the
        # subprocess probes when the vmid isn't in the cache — that
        # handles the narrow race window where someone created a guest
        # in the last 2 s and the dashboard tries to chart it before
        # the next cache refresh.
        vm_type = None
        try:
            for resource in (get_cached_pvesh_cluster_resources_vm() or []):
                if resource.get('node') != local_node:
                    continue
                if resource.get('vmid') == vmid:
                    rtype = resource.get('type')
                    if rtype == 'lxc':
                        vm_type = 'lxc'
                    elif rtype in ('qemu', 'vm'):
                        vm_type = 'qemu'
                    break
        except Exception:
            pass

        if vm_type is None:
            # Cache miss / brand-new guest — fall back to the original
            # qemu-then-lxc probe.
            result = subprocess.run(
                ['pvesh', 'get', f'/nodes/{local_node}/qemu/{vmid}/status/current', '--output-format', 'json'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                vm_type = 'qemu'
            else:
                result = subprocess.run(
                    ['pvesh', 'get', f'/nodes/{local_node}/lxc/{vmid}/status/current', '--output-format', 'json'],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    vm_type = 'lxc'
                else:
                    return jsonify({'error': f'VM/LXC {vmid} not found'}), 404

        # Get RRD data
        rrd_result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/{vm_type}/{vmid}/rrddata',
                                    '--timeframe', timeframe, '--output-format', 'json'],
                                   capture_output=True, text=True, timeout=10)
        
        if rrd_result.returncode == 0:

            rrd_data = json.loads(rrd_result.stdout)

            return jsonify({
                'vmid': vmid,
                'type': vm_type,
                'timeframe': timeframe,
                'data': rrd_data
            })
        else:
            # Check if RRD file is empty or corrupted
            stderr_lower = rrd_result.stderr.lower() if rrd_result.stderr else ''
            if 'rrd' in stderr_lower or 'no such file' in stderr_lower or 'empty' in stderr_lower:
                return jsonify({
                    'error': 'RRD data not available',
                    'details': f'The RRD database for {vm_type.upper()} {vmid} may be empty or corrupted.',
                    'suggestion': 'Try restarting rrdcached: systemctl restart rrdcached'
                }), 503
            return jsonify({'error': f'Failed to get RRD data: {rrd_result.stderr}'}), 500
    
    except json.JSONDecodeError:
        return jsonify({
            'error': 'RRD data not available',
            'details': f'Unable to parse metrics data for VM/LXC {vmid}.',
            'suggestion': 'Try restarting rrdcached: systemctl restart rrdcached'
        }), 503
    except Exception as e:

        return jsonify({'error': str(e)}), 500

@app.route('/api/node/metrics', methods=['GET'])
@require_auth
def api_node_metrics():
    """Get historical metrics (RRD data) for the node"""
    try:
        timeframe = request.args.get('timeframe', 'week')  # hour, day, week, month, year
        

        
        # Validate timeframe
        valid_timeframes = ['hour', 'day', 'week', 'month', 'year']
        if timeframe not in valid_timeframes:
            # print(f"[v0] ERROR: Invalid timeframe: {timeframe}")
            pass
            return jsonify({'error': f'Invalid timeframe. Must be one of: {", ".join(valid_timeframes)}'}), 400
        
        # Get local node name
        # local_node = socket.gethostname()
        local_node = get_proxmox_node_name()

        # print(f"[v0] Local node: {local_node}")
        pass
        

        zfs_arc_size = 0
        try:
            with open('/proc/spl/kstat/zfs/arcstats', 'r') as f:
                for line in f:
                    if line.startswith('size'):
                        parts = line.split()
                        if len(parts) >= 3:
                            zfs_arc_size = int(parts[2])
                            break
        except (FileNotFoundError, PermissionError, ValueError):
            # ZFS not available or no access
            pass

        # Get RRD data for the node

        rrd_result = subprocess.run(['pvesh', 'get', f'/nodes/{local_node}/rrddata', 
                                    '--timeframe', timeframe, '--output-format', 'json'],
                                   capture_output=True, text=True, timeout=10)
        
        if rrd_result.returncode == 0:
            rrd_data = json.loads(rrd_result.stdout)
            
            if zfs_arc_size > 0:
                for item in rrd_data:
                    # If zfsarc field is missing or 0, add current value
                    if 'zfsarc' not in item or item.get('zfsarc', 0) == 0:
                        item['zfsarc'] = zfs_arc_size
            
            return jsonify({
                'node': local_node,
                'timeframe': timeframe,
                'data': rrd_data
            })
        else:
            # Check if RRD file is empty or corrupted
            stderr_lower = rrd_result.stderr.lower() if rrd_result.stderr else ''
            if 'rrd' in stderr_lower or 'no such file' in stderr_lower or 'empty' in stderr_lower:
                return jsonify({
                    'error': 'RRD data not available',
                    'details': 'The RRD database file may be empty or corrupted. This can happen if rrdcached was not running properly after Proxmox installation.',
                    'suggestion': 'Try restarting rrdcached: systemctl restart rrdcached'
                }), 503  # Service Unavailable - more appropriate than 500
            return jsonify({'error': f'Failed to get RRD data: {rrd_result.stderr}'}), 500
            
    except json.JSONDecodeError:
        # pvesh returned invalid JSON - likely empty RRD
        return jsonify({
            'error': 'RRD data not available',
            'details': 'Unable to parse metrics data. The RRD database may be empty or corrupted.',
            'suggestion': 'Try restarting rrdcached: systemctl restart rrdcached'
        }), 503
    except Exception as e:

        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
@require_auth
def api_logs():
    """Get system logs"""
    try:
        limit = request.args.get('limit', '200')
        priority = request.args.get('priority', None)  # 0-7 (0=emerg, 3=err, 4=warning, 6=info)
        service = request.args.get('service', None)
        since_days = request.args.get('since_days', None)
        
        if since_days:
            try:
                days = int(since_days)
                # Cap at 90 days to prevent excessive queries
                days = min(days, 90)
                # No -n limit when using --since: the time range already bounds the query.
                # A hard -n 10000 was masking differences between date ranges on busy servers.
                cmd = ['journalctl', '--since', f'{days} days ago', '--output', 'json', '--no-pager']
            except ValueError:
                cmd = ['journalctl', '-n', limit, '--output', 'json', '--no-pager']
        else:
            cmd = ['journalctl', '-n', limit, '--output', 'json', '--no-pager']
        
        # Add priority filter if specified
        if priority:
            cmd.extend(['-p', priority])
        
        # Add service filter by SYSLOG_IDENTIFIER (not -u which filters by systemd unit)
        # We filter after fetching since journalctl doesn't have a direct SYSLOG_IDENTIFIER flag
        service_filter = service
        
        # Longer timeout for date-range queries which may return many entries
        query_timeout = 120 if since_days else 30
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=query_timeout)

        if result.returncode == 0:
            logs = []
            priority_map = {
                '0': 'emergency', '1': 'alert', '2': 'critical', '3': 'error',
                '4': 'warning', '5': 'notice', '6': 'info', '7': 'debug'
            }
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        log_entry = json.loads(line)
                        timestamp_us = int(log_entry.get('__REALTIME_TIMESTAMP', '0'))
                        timestamp = datetime.fromtimestamp(timestamp_us / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                        
                        priority_num = str(log_entry.get('PRIORITY', '6'))
                        level = priority_map.get(priority_num, 'info')
                        
                        syslog_id = log_entry.get('SYSLOG_IDENTIFIER', '')
                        systemd_unit = log_entry.get('_SYSTEMD_UNIT', '')
                        service_name = syslog_id or systemd_unit or 'system'
                        
                        if service_filter and service_name != service_filter:
                            continue
                        
                        logs.append({
                            'timestamp': timestamp,
                            'level': level,
                            'service': service_name,
                            'unit': systemd_unit,
                            'message': log_entry.get('MESSAGE', ''),
                            'source': 'journal',
                            'pid': log_entry.get('_PID', ''),
                            'hostname': log_entry.get('_HOSTNAME', '')
                        })
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            return jsonify({'logs': logs, 'total': len(logs)})
        else:
            return jsonify({
                'error': 'journalctl not available or failed',
                'logs': [],
                'total': 0
            })
    except Exception as e:
        return jsonify({
            'error': f'Unable to access system logs: {str(e)}',
            'logs': [],
            'total': 0
        })

@app.route('/api/logs/download', methods=['GET'])
@require_auth
def api_logs_download():
    """Download system logs as a text file"""
    try:
        log_type = request.args.get('type', 'system')
        hours = int(request.args.get('hours', '48'))
        level = request.args.get('level', 'all')
        service = request.args.get('service', 'all')
        since_days = request.args.get('since_days', None)
        
        if since_days:
            days = min(int(since_days), 90)
            cmd = ['journalctl', '--since', f'{days} days ago', '--no-pager']
        else:
            cmd = ['journalctl', '--since', f'{hours} hours ago', '--no-pager']
        
        if log_type == 'kernel':
            cmd.extend(['-k'])
            filename = 'kernel.log'
        elif log_type == 'auth':
            cmd.extend(['-u', 'ssh', '-u', 'sshd'])
            filename = 'auth.log'
        else:
            filename = 'system.log'
        
        # Apply level filter
        if level != 'all':
            cmd.extend(['-p', level])
        
        # Apply service filter using SYSLOG_IDENTIFIER grep
        # Note: We use --grep to match the service name in the log output
        # since journalctl doesn't have a direct SYSLOG_IDENTIFIER filter flag
        if service != 'all':
            cmd.extend(['--grep', service])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            import tempfile
            time_desc = f"{since_days} days" if since_days else f"{hours}h"
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
                f.write(f"ProxMenux Log ({log_type}, since {time_desc}) - Generated: {datetime.now().isoformat()}\n")
                f.write("=" * 80 + "\n\n")
                f.write(result.stdout)
                temp_path = f.name
            
            return send_file(
                temp_path,
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'proxmox_{filename}'
            )
        else:
            return jsonify({'error': 'Failed to generate log file'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications', methods=['GET'])
@require_auth
def api_notifications():
    """Get Proxmox notification history"""
    try:
        notifications = []
        
        # 1. Get notifications from journalctl (Proxmox notification service)
        try:
            cmd = [
                'journalctl',
                '-u', 'pve-ha-lrm',
                '-u', 'pve-ha-crm',
                '-u', 'pvedaemon',
                '-u', 'pveproxy',
                '-u', 'pvestatd',
                '--grep', 'notification|email|webhook|alert|notify',
                '-n', '100',
                '--output', 'json',
                '--no-pager'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            log_entry = json.loads(line)
                            timestamp_us = int(log_entry.get('__REALTIME_TIMESTAMP', '0'))
                            timestamp = datetime.fromtimestamp(timestamp_us / 1000000).strftime('%Y-%m-%d %H:%M:%S')
                            
                            message = log_entry.get('MESSAGE', '')
                            
                            # Determine notification type from message
                            notif_type = 'info'
                            if 'email' in message.lower():
                                notif_type = 'email'
                            elif 'webhook' in message.lower():
                                notif_type = 'webhook'
                            elif 'alert' in message.lower() or 'warning' in message.lower():
                                notif_type = 'alert'
                            elif 'error' in message.lower() or 'fail' in message.lower():
                                notif_type = 'error'
                            
                            notifications.append({
                                'timestamp': timestamp,
                                'type': notif_type,
                                'service': log_entry.get('SYSLOG_IDENTIFIER', log_entry.get('_SYSTEMD_UNIT', 'proxmox')),
                                'message': message,
                                'source': 'journal'
                            })
                        except (json.JSONDecodeError, ValueError):
                            continue
        except Exception as e:
            # print(f"Error reading notification logs: {e}")
            pass
        
        # 2. Try to read Proxmox notification configuration
        try:
            notif_config_path = '/etc/pve/notifications.cfg'
            if os.path.exists(notif_config_path):
                with open(notif_config_path, 'r') as f:
                    config_content = f.read()
                    # Parse notification targets (emails, webhooks, etc.)
                    for line in config_content.split('\n'):
                        if line.strip() and not line.startswith('#'):
                            notifications.append({
                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'type': 'config',
                                'service': 'notification-config',
                                'message': f'Notification target configured: {line.strip()}',
                                'source': 'config'
                            })
        except Exception as e:
            # print(f"Error reading notification config: {e}")
            pass
        
        # 3. Get backup notifications from task log
        try:
            cmd = ['pvesh', 'get', '/cluster/tasks', '--output-format', 'json']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                tasks = json.loads(result.stdout)
                for task in tasks:
                    if task.get('type') in ['vzdump', 'backup']:
                        status = task.get('status', 'unknown')
                        notif_type = 'success' if status == 'OK' else 'error' if status == 'stopped' else 'info'
                        
                        notifications.append({
                            'timestamp': datetime.fromtimestamp(task.get('starttime', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                            'type': notif_type,
                            'service': 'backup',
                            'message': f"Backup task {task.get('upid', 'unknown')}: {status}",
                            'source': 'task-log'
                        })
        except Exception as e:
            # print(f"Error reading task notifications: {e}")
            pass
        
        # Sort by timestamp (newest first)
        notifications.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'notifications': notifications[:100],  # Limit to 100 most recent
            'total': len(notifications)
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'notifications': [],
            'total': 0
        })

@app.route('/api/notifications/download', methods=['GET'])
@require_auth
def api_notifications_download():
    """Download complete log for a specific notification"""
    try:
        timestamp = request.args.get('timestamp', '')
        
        if not timestamp:
            return jsonify({'error': 'Timestamp parameter required'}), 400
        
        from datetime import datetime, timedelta
        
        try:
            # Parse timestamp format: "2025-10-11 14:27:35"
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            # Use a very small time window (2 minutes) to get just this notification
            since_time = (dt - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
            until_time = (dt + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            # If parsing fails, use a default range
            since_time = "2 minutes ago"
            until_time = "now"
        
        # Get logs around the specific timestamp
        cmd = [
            'journalctl',
            '--since', since_time,
            '--until', until_time,
            '-n', '50',  # Limit to 50 lines around the notification
            '--no-pager'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
                f.write(f"ProxMenux Notification Log (around {timestamp}) - Generated: {datetime.now().isoformat()}\n")
                f.write("=" * 80 + "\n\n")
                f.write(result.stdout)
                temp_path = f.name
            
            return send_file(
                temp_path,
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'notification_{timestamp.replace(":", "_").replace(" ", "_")}.log'
            )
        else:
            return jsonify({'error': 'Failed to generate log file'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/backups', methods=['GET'])
@require_auth
def api_backups():
    """Get list of all backup files from Proxmox storage"""
    try:
        backups = []

        # Get list of storage locations (shared 30s cache — same
        # underlying call also serves /api/backup-storages and
        # /api/vms/<id>/backups).
        try:
            storages = get_cached_pvesh_storage_list()
            if storages:
                # For each storage, get backup files
                for storage in storages:
                    storage_id = storage.get('storage')
                    storage_type = storage.get('type')
                    
                    # Only check storages that can contain backups
                    if storage_type in ['dir', 'nfs', 'cifs', 'pbs']:
                        try:
                            # Get content of storage
                            content_result = subprocess.run(
                                ['pvesh', 'get', f'/nodes/localhost/storage/{storage_id}/content', '--output-format', 'json'],
                                capture_output=True, text=True, timeout=10)
                            
                            if content_result.returncode == 0:
                                contents = json.loads(content_result.stdout)
                                
                                for item in contents:
                                    if item.get('content') == 'backup':
                                        # Parse backup information
                                        volid = item.get('volid', '')
                                        size = item.get('size', 0)
                                        ctime = item.get('ctime', 0)
                                        
                                        # Extract VMID from volid (format: storage:backup/vzdump-qemu-100-...)
                                        vmid = None
                                        backup_type = None
                                        if 'vzdump-qemu-' in volid:
                                            backup_type = 'qemu'
                                            try:
                                                vmid = volid.split('vzdump-qemu-')[1].split('-')[0]
                                            except:
                                                pass
                                        elif 'vzdump-lxc-' in volid:
                                            backup_type = 'lxc'
                                            try:
                                                vmid = volid.split('vzdump-lxc-')[1].split('-')[0]
                                            except:
                                                pass
                                        
                                        backups.append({
                                            'volid': volid,
                                            'storage': storage_id,
                                            'vmid': vmid,
                                            'type': backup_type,
                                            'size': size,
                                            'size_human': format_bytes(size),
                                            'created': datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M:%S'),
                                            'timestamp': ctime
                                        })
                        except Exception as e:
                            # print(f"Error getting content for storage {storage_id}: {e}")
                            pass
                            continue
        except Exception as e:
            # print(f"Error getting storage list: {e}")
            pass
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'backups': backups,
            'total': len(backups)
        })
        
    except Exception as e:
        # print(f"Error getting backups: {e}")
        pass
        return jsonify({
            'error': str(e),
            'backups': [],
            'total': 0
        })

@app.route('/api/backup-storages', methods=['GET'])
@require_auth
def api_backup_storages():
    """Get list of storages available for backups"""
    try:
        storages = []
        
        # Get current node name
        node_result = subprocess.run(['hostname'], capture_output=True, text=True, timeout=5)
        node = node_result.stdout.strip() if node_result.returncode == 0 else 'localhost'

        # Get all storages (shared 30s cache)
        all_storages = get_cached_pvesh_storage_list()
        if all_storages:
            for storage in all_storages:
                storage_id = storage.get('storage', '')
                content = storage.get('content', '')
                storage_type = storage.get('type', '')

                # Only include storages that support backup content
                if 'backup' in content or storage_type == 'pbs':
                    # Get storage status for space info - use correct path with node
                    try:
                        status_result = subprocess.run(
                            ['pvesh', 'get', f'/nodes/{node}/storage/{storage_id}/status', '--output-format', 'json'],
                            capture_output=True, text=True, timeout=10
                        )
                        
                        total = 0
                        used = 0
                        avail = 0
                        
                        if status_result.returncode == 0:
                            status = json.loads(status_result.stdout)
                            total = status.get('total', 0)
                            used = status.get('used', 0)
                            avail = status.get('avail', 0)
                        
                        storages.append({
                            'storage': storage_id,
                            'type': storage_type,
                            'content': content,
                            'total': total,
                            'used': used,
                            'avail': avail,
                            'total_human': format_bytes(total),
                            'used_human': format_bytes(used),
                            'avail_human': format_bytes(avail)
                        })
                    except:
                        storages.append({
                            'storage': storage_id,
                            'type': storage_type,
                            'content': content,
                            'total': 0,
                            'used': 0,
                            'avail': 0
                        })
        
        return jsonify({'storages': storages})
        
    except Exception as e:
        return jsonify({'error': str(e), 'storages': []})

@app.route('/api/vms/<int:vmid>/backup', methods=['POST'])
@require_auth
def api_create_backup(vmid):
    """Create a backup for a VM or LXC container using Proxmox API"""
    try:
        data = request.get_json() or {}
        storage = data.get('storage', 'local')
        mode = data.get('mode', 'snapshot')  # snapshot, suspend, stop
        compress = data.get('compress', 'zstd')  # none, lzo, gzip, zstd
        protected = data.get('protected', False)  # True/False
        notification = data.get('notification', 'auto')  # always, failure, never, auto
        notes = data.get('notes', '')  # Backup notes/description
        pbs_change_detection = data.get('pbs_change_detection', None)  # default, legacy, data (for PBS + LXC)
        
        # Get node and VM type for this VM
        node = None
        vm_type = None
        vm_name = None
        
        # Try to find VM in cluster resources
        try:
            vms = get_cached_pvesh_cluster_resources_vm()
            if vms:
                for vm in vms:
                    if vm.get('vmid') == vmid:
                        node = vm.get('node')
                        vm_type = vm.get('type')  # 'qemu' or 'lxc'
                        vm_name = vm.get('name', '')
                        break
        except:
            pass
        
        if not node:
            return jsonify({'error': 'VM not found'}), 404
        
        # Process notes template variables
        if notes:
            notes = notes.replace('{{guestname}}', vm_name or '')
            notes = notes.replace('{{vmid}}', str(vmid))
            notes = notes.replace('{{node}}', node or '')
        
        # Check if storage is PBS (Proxmox Backup Server)
        is_pbs = False
        try:
            storage_result = subprocess.run(
                ['pvesh', 'get', f'/storage/{storage}', '--output-format', 'json'],
                capture_output=True, text=True, timeout=10
            )
            if storage_result.returncode == 0:
                storage_info = json.loads(storage_result.stdout)
                is_pbs = storage_info.get('type') == 'pbs'
        except:
            pass
        
        # Build pvesh command: pvesh create /nodes/<NODE>/vzdump --vmid <ID> --storage <STORAGE> --mode <MODE> [--compress <COMPRESS>]
        cmd = [
            'pvesh', 'create', f'/nodes/{node}/vzdump',
            '--vmid', str(vmid),
            '--storage', storage,
            '--mode', mode
        ]
        
        # Only add --compress for non-PBS storage (PBS handles compression/deduplication internally)
        if not is_pbs:
            cmd.extend(['--compress', compress])
        
        # Add protected flag if enabled (use 1 for true)
        if protected:
            cmd.extend(['--protected', '1'])
        
        # Add notes if provided
        if notes:
            cmd.extend(['--notes-template', notes])
        
        # Add PBS change detection mode (only for LXC with PBS storage)
        if pbs_change_detection and pbs_change_detection != 'default' and vm_type == 'lxc':
            cmd.extend(['--pbs-change-detection-mode', pbs_change_detection])
        
        # Execute pvesh command - this creates a task in Proxmox
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            return jsonify({
                'success': False,
                'error': f'Backup failed: {error_msg}',
                'command': ' '.join(cmd)
            }), 500
        
        return jsonify({
            'success': True,
            'message': f'Backup task started for {vm_type.upper()} {vmid}',
            'storage': storage,
            'mode': mode,
            'compress': compress,
            'protected': protected,
            'notes': notes,
            'task': result.stdout.strip() if result.stdout else None
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>/backups', methods=['GET'])
@require_auth
def api_vm_backups(vmid):
    """Get list of backups for a specific VM/LXC"""
    try:
        backups = []
        
        # Get current node name
        node_result = subprocess.run(['hostname'], capture_output=True, text=True, timeout=5)
        node = node_result.stdout.strip() if node_result.returncode == 0 else 'localhost'

        # Get list of storage locations (shared 30s cache)
        storages = get_cached_pvesh_storage_list()
        if storages:
            for storage in storages:
                storage_id = storage.get('storage')
                storage_type = storage.get('type')
                content = storage.get('content', '')

                # Only check storages that can contain backups
                if 'backup' in content or storage_type == 'pbs':
                    try:
                        # Use --vmid filter to get only backups for this VM
                        content_result = subprocess.run(
                            ['pvesh', 'get', f'/nodes/{node}/storage/{storage_id}/content', 
                             '--vmid', str(vmid), '--output-format', 'json'],
                            capture_output=True, text=True, timeout=30
                        )
                        
                        if content_result.returncode == 0:
                            contents = json.loads(content_result.stdout)
                            
                            for item in contents:
                                if item.get('content') == 'backup':
                                    # Get backup type from subtype field (PBS) or parse volid (local)
                                    backup_type = item.get('subtype', '')
                                    if not backup_type:
                                        volid = item.get('volid', '')
                                        if 'vzdump-qemu-' in volid:
                                            backup_type = 'qemu'
                                        elif 'vzdump-lxc-' in volid:
                                            backup_type = 'lxc'
                                    
                                    size = item.get('size', 0)
                                    ctime = item.get('ctime', 0)
                                    notes = item.get('notes', '')
                                    
                                    backups.append({
                                        'volid': item.get('volid', ''),
                                        'storage': storage_id,
                                        'type': backup_type,
                                        'size': size,
                                        'size_human': format_bytes(size),
                                        'timestamp': ctime,
                                        'date': datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M') if ctime else '',
                                        'notes': notes
                                    })
                    except Exception as e:
                        continue
        
        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'backups': backups,
            'vmid': vmid,
            'total': len(backups)
        })
        
    except Exception as e:
        return jsonify({'error': str(e), 'backups': [], 'total': 0})

@app.route('/api/events', methods=['GET'])
@require_auth
def api_events():
    """Get recent Proxmox events and tasks"""
    try:
        limit = request.args.get('limit', '50')
        events = []
        
        try:
            result = subprocess.run(['pvesh', 'get', '/cluster/tasks', '--output-format', 'json'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                tasks = json.loads(result.stdout)
                
                for task in tasks[:int(limit)]:
                    upid = task.get('upid', '')
                    task_type = task.get('type', 'unknown')
                    status = task.get('status', 'unknown')
                    node = task.get('node', 'unknown')
                    user = task.get('user', 'unknown')
                    vmid = task.get('id', '')
                    starttime = task.get('starttime', 0)
                    endtime = task.get('endtime', 0)
                    
                    # Calculate duration
                    duration = ''
                    if endtime and starttime:
                        duration_sec = endtime - starttime
                        if duration_sec < 60:
                            duration = f"{duration_sec}s"
                        elif duration_sec < 3600:
                            duration = f"{duration_sec // 60}m {duration_sec % 60}s"
                        else:
                            hours = duration_sec // 3600
                            minutes = (duration_sec % 3600) // 60
                            duration = f"{hours}h {minutes}m"
                    
                    # Determine level based on status
                    level = 'info'
                    if status == 'OK':
                        level = 'info'
                    elif status in ['stopped', 'error']:
                        level = 'error'
                    elif status == 'running':
                        level = 'warning'
                    
                    events.append({
                        'upid': upid,
                        'type': task_type,
                        'status': status,
                        'level': level,
                        'node': node,
                        'user': user,
                        'vmid': str(vmid) if vmid else '',
                        'starttime': datetime.fromtimestamp(starttime).strftime('%Y-%m-%d %H:%M:%S') if starttime else '',
                        'endtime': datetime.fromtimestamp(endtime).strftime('%Y-%m-%d %H:%M:%S') if endtime else 'Running',
                        'duration': duration
                    })
        except Exception as e:
            # print(f"Error getting events: {e}")
            pass
        
        return jsonify({
            'events': events,
            'total': len(events)
        })
        
    except Exception as e:
        # print(f"Error getting events: {e}")
        pass
        return jsonify({
            'error': str(e),
            'events': [],
            'total': 0
        })

@app.route('/api/task-log/<path:upid>')
@require_auth
def get_task_log(upid):
    """Get complete task log from Proxmox using UPID."""
    # Confine all log reads to /var/log/pve/tasks/. The route uses <path:upid>
    # so slashes pass through unchanged, and `upid` is later interpolated into
    # a filesystem path. Without this guard a crafted UPID containing `..`
    # segments could read arbitrary files as root (e.g. /etc/shadow,
    # /etc/pve/priv/*). See audit Tier 1 #12.
    _PVE_TASKS_DIR = '/var/log/pve/tasks'
    # Resolve the prefix once so that on hosts where /var/log is a symlink
    # (some test boxes, BSDs, macOS dev setups) the candidate's resolved path
    # and the prefix are compared on the same canonical form.
    try:
        _PVE_TASKS_DIR_REAL = os.path.realpath(_PVE_TASKS_DIR)
    except (OSError, ValueError):
        _PVE_TASKS_DIR_REAL = _PVE_TASKS_DIR

    def _confined_path(candidate):
        """Return the candidate path if it stays inside _PVE_TASKS_DIR, else None."""
        try:
            resolved = os.path.realpath(candidate)
        except (OSError, ValueError):
            return None
        # `os.path.realpath` collapses `..` and resolves symlinks. We then
        # verify the result is inside the allowed prefix using a path-aware
        # comparison (commonpath) so that `/var/log/pve/tasks-evil` doesn't
        # pass a naive startswith check.
        try:
            if os.path.commonpath([resolved, _PVE_TASKS_DIR_REAL]) != _PVE_TASKS_DIR_REAL:
                return None
        except ValueError:
            return None
        return resolved

    try:
        # print(f"[v0] Getting task log for UPID: {upid}")
        pass

        # Proxmox stores files without trailing :: but API may include them
        upid_clean = upid.rstrip(':')
        # print(f"[v0] Cleaned UPID: {upid_clean}")
        pass
        
        # Parse UPID to extract node name and calculate index
        # UPID format: UPID:node:pid:pstart:starttime:type:id:user:
        parts = upid_clean.split(':')
        if len(parts) < 5:
            # print(f"[v0] Invalid UPID format: {upid_clean}")
            pass
            return jsonify({'error': 'Invalid UPID format'}), 400
        
        node = parts[1]
        starttime = parts[4]
        
        # Calculate index (last character of starttime in hex, lowercase)
        index = starttime[-1].lower()
        
        # print(f"[v0] Extracted node: {node}, starttime: {starttime}, index: {index}")
        pass
        
        # Try with cleaned UPID (no trailing colons)
        log_file_path = _confined_path(f"{_PVE_TASKS_DIR}/{index}/{upid_clean}")
        if log_file_path and os.path.exists(log_file_path):
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
            return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

        # Try with single trailing colon
        log_file_path_single = _confined_path(f"{_PVE_TASKS_DIR}/{index}/{upid_clean}:")
        if log_file_path_single and os.path.exists(log_file_path_single):
            with open(log_file_path_single, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
            return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

        # Try with uppercase index
        log_file_path_upper = _confined_path(f"{_PVE_TASKS_DIR}/{index.upper()}/{upid_clean}")
        if log_file_path_upper and os.path.exists(log_file_path_upper):
            with open(log_file_path_upper, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
            return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
        # List available files in the directory for debugging
        tasks_dir = _confined_path(f"{_PVE_TASKS_DIR}/{index}")
        if tasks_dir and os.path.isdir(tasks_dir):
            available_files = os.listdir(tasks_dir)
            upid_prefix = ':'.join(parts[:5])  # Get first 5 parts of UPID
            for filename in available_files:
                if filename.startswith(upid_prefix):
                    matched_file = _confined_path(f"{tasks_dir}/{filename}")
                    if not matched_file:
                        continue
                    with open(matched_file, 'r', encoding='utf-8', errors='ignore') as f:
                        log_text = f.read()
                    return log_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

        return jsonify({'error': 'Log file not found'}), 404
            
    except Exception as e:
        # print(f"[v0] Error fetching task log for UPID {upid}: {type(e).__name__}: {e}")
        pass
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
@require_auth
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.2.1.2-beta'
    })

# ─── User-configurable health thresholds ─────────────────────────────────────
# GET   /api/health/thresholds                    — effective tree (defaults + overrides)
# PUT   /api/health/thresholds                    — partial save with validation
# POST  /api/health/thresholds/reset              — wipe all overrides
# POST  /api/health/thresholds/reset?section=cpu  — wipe one section's overrides
#
# All routes require auth via @require_auth (the decorator transparently
# bypasses when auth isn't configured, matching every other route).

# ─── ProxMenux-managed installs registry (Sprint 14.7) ──────────────────────
# GET  /api/managed-installs
#   Active items (no removed_at) with their latest update_check state.
#   The Hardware tab uses this to render "Update available: vX.Y.Z"
#   inline next to detected GPU/Tailscale entries.
# POST /api/managed-installs/refresh
#   Force a fresh detect_and_register + check_for_updates run, bypassing
#   the per-source caches. Useful for the user clicking a manual
#   "re-check" button.

@app.route('/api/managed-installs', methods=['GET'])
@require_auth
def api_managed_installs_get():
    try:
        import managed_installs
        items = managed_installs.get_active_items()
        # Strip private fields (anything starting with `_`) before
        # exposing — they're internal helpers for the checker chain,
        # not part of the public API contract.
        cleaned = []
        for it in items:
            cleaned_it = {k: v for k, v in it.items() if not k.startswith('_')}
            uc = cleaned_it.get('update_check')
            if isinstance(uc, dict):
                cleaned_it['update_check'] = {
                    k: v for k, v in uc.items() if not k.startswith('_')
                }
            cleaned.append(cleaned_it)
        return jsonify({'success': True, 'items': cleaned})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/managed-installs/refresh', methods=['POST'])
@require_auth
def api_managed_installs_refresh():
    try:
        import managed_installs
        managed_installs.detect_and_register()
        managed_installs.check_for_updates(force=True)
        return api_managed_installs_get()
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/health/thresholds', methods=['GET'])
@require_auth
def api_health_thresholds_get():
    """Return the effective threshold tree (defaults merged with the
    user's overrides). Each leaf carries `value`, `recommended`,
    `customised`, `unit`, `min`, `max`, `step` so the UI can render
    inputs and badges without re-fetching the schema."""
    try:
        import health_thresholds as ht
        return jsonify({
            'success': True,
            'thresholds': ht.load_effective(),
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/health/thresholds', methods=['PUT'])
@require_auth
def api_health_thresholds_put():
    """Save a partial threshold payload. Body shape mirrors DEFAULTS
    but the leaves are bare numbers, not metadata dicts. Sections not
    in the payload keep their existing overrides."""
    try:
        import health_thresholds as ht
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'success': False, 'message': 'Body must be a JSON object'}), 400
        try:
            effective = ht.save(payload)
        except ht.ThresholdValidationError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        return jsonify({'success': True, 'thresholds': effective})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/health/thresholds/reset', methods=['POST'])
@require_auth
def api_health_thresholds_reset():
    """Reset thresholds. ?section=<name> resets one section, no
    parameter resets everything to recommended."""
    try:
        import health_thresholds as ht
        section = request.args.get('section', '').strip()
        try:
            if section:
                effective = ht.reset_section(section)
            else:
                effective = ht.reset_all()
        except ht.ThresholdValidationError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        return jsonify({'success': True, 'thresholds': effective})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/health/acknowledge', methods=['POST'])
@require_auth
def api_health_acknowledge():
    """Acknowledge/dismiss a health error by error_key."""
    try:
        data = request.get_json()
        error_key = data.get('error_key', '')
        if not error_key:
            return jsonify({'error': 'error_key is required'}), 400
        
        result = health_persistence.acknowledge_error(error_key)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prometheus', methods=['GET'])
@require_auth
def api_prometheus():
    """Export metrics in Prometheus format"""
    try:
        metrics = []
        timestamp = int(datetime.now().timestamp() * 1000)
        node = socket.gethostname()

        # Non-blocking: returns %CPU since the last psutil call (sampler keeps state primed).
        # Avoids 500ms worker block on each Prometheus scrape.
        cpu_usage = psutil.cpu_percent(interval=0)
        memory = psutil.virtual_memory()
        load_avg = os.getloadavg()
        uptime_seconds = time.time() - psutil.boot_time()
        
        # System metrics
        metrics.append(f'# HELP proxmox_cpu_usage CPU usage percentage')
        metrics.append(f'# TYPE proxmox_cpu_usage gauge')
        metrics.append(f'proxmox_cpu_usage{{node="{node}"}} {cpu_usage} {timestamp}')
        
        metrics.append(f'# HELP proxmox_memory_total_bytes Total memory in bytes')
        metrics.append(f'# TYPE proxmox_memory_total_bytes gauge')
        metrics.append(f'proxmox_memory_total_bytes{{node="{node}"}} {memory.total} {timestamp}')
        
        metrics.append(f'# HELP proxmox_memory_used_bytes Used memory in bytes')
        metrics.append(f'# TYPE proxmox_memory_used_bytes gauge')
        metrics.append(f'proxmox_memory_used_bytes{{node="{node}"}} {memory.used} {timestamp}')
        
        metrics.append(f'# HELP proxmox_memory_usage_percent Memory usage percentage')
        metrics.append(f'# TYPE proxmox_memory_usage_percent gauge')
        metrics.append(f'proxmox_memory_usage_percent{{node="{node}"}} {memory.percent} {timestamp}')
        
        metrics.append(f'# HELP proxmox_load_average System load average')
        metrics.append(f'# TYPE proxmox_load_average gauge')
        metrics.append(f'proxmox_load_average{{node="{node}",period="1m"}} {load_avg[0]} {timestamp}')
        metrics.append(f'proxmox_load_average{{node="{node}",period="5m"}} {load_avg[1]} {timestamp}')
        metrics.append(f'proxmox_load_average{{node="{node}",period="15m"}} {load_avg[2]} {timestamp}')
        
        metrics.append(f'# HELP proxmox_uptime_seconds System uptime in seconds')
        metrics.append(f'# TYPE proxmox_uptime_seconds counter')
        metrics.append(f'proxmox_uptime_seconds{{node="{node}"}} {uptime_seconds} {timestamp}')
        
        # Temperature
        temp = get_cpu_temperature()
        if temp:
            metrics.append(f'# HELP proxmox_cpu_temperature_celsius CPU temperature in Celsius')
            metrics.append(f'# TYPE proxmox_cpu_temperature_celsius gauge')
            metrics.append(f'proxmox_cpu_temperature_celsius{{node="{node}"}} {temp} {timestamp}')
        
        # Storage metrics
        storage_info = get_storage_info()
        for disk in storage_info.get('disks', []):
            disk_name = disk.get('name', 'unknown')
            metrics.append(f'# HELP proxmox_disk_total_bytes Total disk space in bytes')
            metrics.append(f'# TYPE proxmox_disk_total_bytes gauge')
            metrics.append(f'proxmox_disk_total_bytes{{node="{node}",disk="{disk_name}"}} {disk.get("total", 0)} {timestamp}')
            
            metrics.append(f'# HELP proxmox_disk_used_bytes Used disk space in bytes')
            metrics.append(f'# TYPE proxmox_disk_used_bytes gauge')
            metrics.append(f'proxmox_disk_used_bytes{{node="{node}",disk="{disk_name}"}} {disk.get("used", 0)} {timestamp}')
            
            metrics.append(f'# HELP proxmox_disk_usage_percent Disk usage percentage')
            metrics.append(f'# TYPE proxmox_disk_usage_percent gauge')
            metrics.append(f'proxmox_disk_usage_percent{{node="{node}",disk="{disk_name}"}} {disk.get("usage_percent", 0)} {timestamp}')
        
        # Network metrics
        network_info = get_network_info()
        if 'traffic' in network_info:
            metrics.append(f'# HELP proxmox_network_bytes_sent_total Total bytes sent')
            metrics.append(f'# TYPE proxmox_network_bytes_sent_total counter')
            metrics.append(f'proxmox_network_bytes_sent_total{{node="{node}"}} {network_info["traffic"].get("bytes_sent", 0)} {timestamp}')
            
            metrics.append(f'# HELP proxmox_network_bytes_received_total Total bytes received')
            metrics.append(f'# TYPE proxmox_network_bytes_received_total counter')
            metrics.append(f'proxmox_network_bytes_received_total{{node="{node}"}} {network_info["traffic"].get("bytes_recv", 0)} {timestamp}')
        
        # Per-interface network metrics
        for interface in network_info.get('interfaces', []):
            iface_name = interface.get('name', 'unknown')
            if interface.get('status') == 'up':
                metrics.append(f'# HELP proxmox_interface_bytes_sent_total Bytes sent per interface')
                metrics.append(f'# TYPE proxmox_interface_bytes_sent_total counter')
                metrics.append(f'proxmox_interface_bytes_sent_total{{node="{node}",interface="{iface_name}"}} {interface.get("bytes_sent", 0)} {timestamp}')
                
                metrics.append(f'# HELP proxmox_interface_bytes_received_total Bytes received per interface')
                metrics.append(f'# TYPE proxmox_interface_bytes_received_total counter')
                metrics.append(f'proxmox_interface_bytes_received_total{{node="{node}",interface="{iface_name}"}} {interface.get("bytes_recv", 0)} {timestamp}')
        
        # VM metrics
        vms_data = get_proxmox_vms()
        if isinstance(vms_data, list):
            vms = vms_data
            total_vms = len(vms)
            running_vms = sum(1 for vm in vms if vm.get('status') == 'running')
            stopped_vms = sum(1 for vm in vms if vm.get('status') == 'stopped')
            
            metrics.append(f'# HELP proxmox_vms_total Total number of VMs and LXCs')
            metrics.append(f'# TYPE proxmox_vms_total gauge')
            metrics.append(f'proxmox_vms_total{{node="{node}"}} {total_vms} {timestamp}')
            
            metrics.append(f'# HELP proxmox_vms_running Number of running VMs and LXCs')
            metrics.append(f'# TYPE proxmox_vms_running gauge')
            metrics.append(f'proxmox_vms_running{{node="{node}"}} {running_vms} {timestamp}')
            
            metrics.append(f'# HELP proxmox_vms_stopped Number of stopped VMs and LXCs')
            metrics.append(f'# TYPE proxmox_vms_stopped gauge')
            metrics.append(f'proxmox_vms_stopped{{node="{node}"}} {stopped_vms} {timestamp}')
            
            # Per-VM metrics
            for vm in vms:
                vmid = vm.get('vmid', 'unknown')
                vm_name = vm.get('name', f'vm-{vmid}')
                vm_status = 1 if vm.get('status') == 'running' else 0
                
                metrics.append(f'# HELP proxmox_vm_status VM status (1=running, 0=stopped)')
                metrics.append(f'# TYPE proxmox_vm_status gauge')
                metrics.append(f'proxmox_vm_status{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm_status} {timestamp}')
                
                if vm.get('status') == 'running':
                    metrics.append(f'# HELP proxmox_vm_cpu_usage VM CPU usage')
                    metrics.append(f'# TYPE proxmox_vm_cpu_usage gauge')
                    metrics.append(f'proxmox_vm_cpu_usage{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm.get("cpu", 0)} {timestamp}')
                    
                    metrics.append(f'# HELP proxmox_vm_memory_used_bytes VM memory used in bytes')
                    metrics.append(f'# TYPE proxmox_vm_memory_used_bytes gauge')
                    metrics.append(f'proxmox_vm_memory_used_bytes{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm.get("mem", 0)} {timestamp}')
                    
                    metrics.append(f'# HELP proxmox_vm_memory_max_bytes VM memory max in bytes')
                    metrics.append(f'# TYPE proxmox_vm_memory_max_bytes gauge')
                    metrics.append(f'proxmox_vm_memory_max_bytes{{node="{node}",vmid="{vmid}",name="{vm_name}"}} {vm.get("maxmem", 0)} {timestamp}')
        
        # Hardware metrics (temperature, fans, UPS, GPU)
        try:
            hardware_info = get_hardware_info()
            
            # Disk temperatures
            for device in hardware_info.get('storage_devices', []):
                if device.get('temperature'):
                    disk_name = device.get('name', 'unknown')
                    metrics.append(f'# HELP proxmox_disk_temperature_celsius Disk temperature in Celsius')
                    metrics.append(f'# TYPE proxmox_disk_temperature_celsius gauge')
                    metrics.append(f'proxmox_disk_temperature_celsius{{node="{node}",disk="{disk_name}"}} {device["temperature"]} {timestamp}')
            
            # Fan speeds
            all_fans = hardware_info.get('sensors', {}).get('fans', [])
            all_fans.extend(hardware_info.get('ipmi_fans', []))
            for fan in all_fans:
                fan_name = fan.get('name', 'unknown').replace(' ', '_')
                if fan.get('speed') is not None:
                    metrics.append(f'# HELP proxmox_fan_speed_rpm Fan speed in RPM')
                    metrics.append(f'# TYPE proxmox_fan_speed_rpm gauge')
                    metrics.append(f'proxmox_fan_speed_rpm{{node="{node}",fan="{fan_name}"}} {fan["speed"]} {timestamp}')
            
            # GPU metrics
            for gpu in hardware_info.get('gpus', []): # Changed from pci_devices to gpus
                gpu_name = gpu.get('name', 'unknown').replace(' ', '_')
                gpu_vendor = gpu.get('vendor', 'unknown')
                gpu_slot = gpu.get('slot', 'unknown') # Use slot for matching
                
                # GPU Temperature
                if gpu.get('temperature') is not None:
                    metrics.append(f'# HELP proxmox_gpu_temperature_celsius GPU temperature in Celsius')
                    metrics.append(f'# TYPE proxmox_gpu_temperature_celsius gauge')
                    metrics.append(f'proxmox_gpu_temperature_celsius{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {gpu["temperature"]} {timestamp}')
                
                # GPU Utilization
                if gpu.get('utilization_gpu') is not None:
                    metrics.append(f'# HELP proxmox_gpu_utilization_percent GPU utilization percentage')
                    metrics.append(f'# TYPE proxmox_gpu_utilization_percent gauge')
                    metrics.append(f'proxmox_gpu_utilization_percent{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {gpu["utilization_gpu"]} {timestamp}')
                
                # GPU Memory
                if gpu.get('memory_used') and gpu.get('memory_total'):
                    try:
                        # Extract numeric values from strings like "1024 MiB"
                        mem_used = float(gpu['memory_used'].split()[0])
                        mem_total = float(gpu['memory_total'].split()[0])
                        mem_used_bytes = mem_used * 1024 * 1024  # Convert MiB to bytes
                        mem_total_bytes = mem_total * 1024 * 1024
                        
                        metrics.append(f'# HELP proxmox_gpu_memory_total_bytes GPU memory total in bytes')
                        metrics.append(f'# TYPE proxmox_gpu_memory_total_bytes gauge')
                        metrics.append(f'proxmox_gpu_memory_total_bytes{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {mem_total_bytes} {timestamp}')
                    except (ValueError, IndexError):
                        pass
                
                # GPU Power Draw (NVIDIA only)
                if gpu.get('power_draw'):
                    try:
                        # Extract numeric value from string like "75.5 W"
                        power_draw = float(gpu['power_draw'].split()[0])
                        metrics.append(f'# HELP proxmox_gpu_power_draw_watts GPU power draw in watts')
                        metrics.append(f'# TYPE proxmox_gpu_power_draw_watts gauge')
                        metrics.append(f'proxmox_gpu_power_draw_watts{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {power_draw} {timestamp}')
                    except (ValueError, IndexError):
                        pass
                
                # GPU Clock Speeds (NVIDIA only)
                if gpu.get('clock_graphics'):
                    try:
                        # Extract numeric value from string like "1500 MHz"
                        clock_speed = float(gpu['clock_graphics'].split()[0])
                        metrics.append(f'# HELP proxmox_gpu_clock_speed_mhz GPU clock speed in MHz')
                        metrics.append(f'# TYPE proxmox_gpu_clock_speed_mhz gauge')
                        metrics.append(f'proxmox_gpu_clock_speed_mhz{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {clock_speed} {timestamp}')
                    except (ValueError, IndexError):
                        pass
                
                if gpu.get('clock_memory'):
                    try:
                        # Extract numeric value from string like "5001 MHz"
                        mem_clock = float(gpu['clock_memory'].split()[0])
                        metrics.append(f'# HELP proxmox_gpu_memory_clock_mhz GPU memory clock speed in MHz')
                        metrics.append(f'# TYPE proxmox_gpu_memory_clock_mhz gauge')
                        metrics.append(f'proxmox_gpu_memory_clock_mhz{{node="{node}",gpu="{gpu_name}",vendor="{gpu_vendor}",slot="{gpu_slot}"}} {mem_clock} {timestamp}')
                    except (ValueError, IndexError):
                        pass
            
            # UPS metrics
            ups = hardware_info.get('ups')
            if ups:
                ups_name = ups.get('name', 'ups').replace(' ', '_')
                
                if ups.get('battery_charge') is not None:
                    metrics.append(f'# HELP proxmox_ups_battery_charge_percent UPS battery charge percentage')
                    metrics.append(f'# TYPE proxmox_ups_battery_charge_percent gauge')
                    metrics.append(f'proxmox_ups_battery_charge_percent{{node="{node}",ups="{ups_name}"}} {ups["battery_charge_raw"]} {timestamp}')
                
                if ups.get('load') is not None:
                    metrics.append(f'# HELP proxmox_ups_load_percent UPS load percentage')
                    metrics.append(f'# TYPE proxmox_ups_load_percent gauge')
                    metrics.append(f'proxmox_ups_load_percent{{node="{node}",ups="{ups_name}"}} {ups["load_percent_raw"]} {timestamp}')
                
                if ups.get('time_left_seconds') is not None: # Use seconds for counter
                    metrics.append(f'# HELP proxmox_ups_runtime_seconds UPS runtime in seconds')
                    metrics.append(f'# TYPE proxmox_ups_runtime_seconds gauge') # Use gauge if it's current remaining time
                    metrics.append(f'proxmox_ups_runtime_seconds{{node="{node}",ups="{ups_name}"}} {ups["time_left_seconds"]} {timestamp}')
                
                if ups.get('input_voltage') is not None:
                    metrics.append(f'# HELP proxmox_ups_input_voltage_volts UPS input voltage in volts')
                    metrics.append(f'# TYPE proxmox_ups_input_voltage_volts gauge')
                    metrics.append(f'proxmox_ups_input_voltage_volts{{node="{node}",ups="{ups_name}"}} {ups["input_voltage"]} {timestamp}')
        except Exception as e:
            # print(f"[v0] Error getting hardware metrics for Prometheus: {e}")
            pass
        
        # Return metrics in Prometheus format
        return '\n'.join(metrics) + '\n', 200, {'Content-Type': 'text/plain; version=0.0.4; charset=utf-8'}
        
    except Exception as e:
        # print(f"Error generating Prometheus metrics: {e}")
        pass
        import traceback
        traceback.print_exc()
        return f'# Error generating metrics: {str(e)}\n', 500, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/api/info', methods=['GET'])
@require_auth
def api_info():
    """Root endpoint with API information"""
    return jsonify({
        'name': 'ProxMenux Monitor API',
        'version': '1.2.1.2-beta',
        'endpoints': [
            '/api/system',
            '/api/system-info',
            '/api/storage', 
            '/api/proxmox-storage',
            '/api/network',
            '/api/network/summary', # Added network summary
            '/api/vms',
            '/api/vms/<vmid>/metrics', # Added endpoint for RRD data
            '/api/node/metrics', # Added node metrics endpoint
            '/api/logs',
            '/api/health',
            '/api/hardware',
            '/api/gpu/<slot>/realtime', # Added endpoint for GPU monitoring
            '/api/backups', # Added backup endpoint
            '/api/events', # Added events endpoint
            '/api/notifications', # Added notifications endpoint
            '/api/task-log/<upid>', # Added task log endpoint
            '/api/prometheus' # Added prometheus endpoint
        ]
    })

@app.route('/api/hardware', methods=['GET'])
@require_auth
def api_hardware():
    """Get hardware information"""
    try:
        hardware_info = get_hardware_info()
        
        all_fans = hardware_info.get('sensors', {}).get('fans', [])
        ipmi_fans = hardware_info.get('ipmi_fans', [])
        all_fans.extend(ipmi_fans)
        
        # Format data for frontend
        formatted_data = {
            'cpu': hardware_info.get('cpu', {}),
            'motherboard': hardware_info.get('motherboard', {}), # Corrected: use hardware_info
            'bios': hardware_info.get('motherboard', {}).get('bios', {}), # Extract BIOS info
            'memory_modules': hardware_info.get('memory_modules', []),
            'storage_devices': hardware_info.get('storage_devices', []), # Fixed: use hardware_info
            'pci_devices': hardware_info.get('pci_devices', []),  # Fixed: use hardware_info
            'temperatures': hardware_info.get('sensors', {}).get('temperatures', []),
            'fans': all_fans, # Return combined fans (sensors + IPMI)
            'power_supplies': hardware_info.get('ipmi_power', {}).get('power_supplies', []),
            'power_meter': hardware_info.get('power_meter'),
            'ups': hardware_info.get('ups') if hardware_info.get('ups') else None,
            'gpus': hardware_info.get('gpus', []),
            'coral_tpus': hardware_info.get('coral_tpus', []),
            'usb_devices': hardware_info.get('usb_devices', []),
        }
        

        
        return jsonify(formatted_data)
    except Exception as e:
        # print(f"[v0] Error in api_hardware: {e}")
        pass
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/hardware/live', methods=['GET'])
@require_auth
def api_hardware_live():
    """Lightweight endpoint: only dynamic hardware fields (temps, fans, power, UPS).

    Designed for the active Hardware page to poll every 3-5s without re-running the
    expensive static collectors (lscpu, dmidecode, lsblk, smartctl). ipmitool output
    is cached internally (10s) so repeated polls don't hammer the BMC.
    """
    try:
        return jsonify(get_hardware_live_info())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/gpu/<slot>/realtime', methods=['GET'])
@require_auth
def api_gpu_realtime(slot):
    """Get real-time GPU monitoring data for a specific GPU"""
    try:
        # print(f"[v0] /api/gpu/{slot}/realtime - Getting GPU info...")
        pass
        
        gpus = get_gpu_info()
        
        gpu = None
        for g in gpus:
            # Match by slot or if the slot is a substring of the GPU's slot (e.g., '00:01.0' matching '00:01')
            if g.get('slot') == slot or slot in g.get('slot', ''):
                gpu = g
                break
        
        if not gpu:
            # print(f"[v0] GPU with slot matching '{slot}' not found")
            pass
            return jsonify({'error': 'GPU not found'}), 404
        
        # print(f"[v0] Getting detailed monitoring data for GPU at slot {gpu.get('slot')}...")
        pass
        detailed_info = get_detailed_gpu_info(gpu)
        gpu.update(detailed_info)

        # SR-IOV detail is only relevant when the modal is actually open,
        # so we build it on demand here (not in get_gpu_info) to avoid
        # scanning every guest config on the hardware snapshot path.
        _sriov_enrich_detail(gpu)

        # Extract only the monitoring-related fields
        realtime_data = {
            'has_monitoring_tool': gpu.get('has_monitoring_tool', False),
            'temperature': gpu.get('temperature'),
            'fan_speed': gpu.get('fan_speed'),
            'fan_unit': gpu.get('fan_unit'),
            'utilization_gpu': gpu.get('utilization_gpu'),
            'utilization_memory': gpu.get('utilization_memory'),
            'memory_used': gpu.get('memory_used'),
            'memory_total': gpu.get('memory_total'),
            'memory_free': gpu.get('memory_free'),
            'power_draw': gpu.get('power_draw'),
            'power_limit': gpu.get('power_limit'),
            'clock_graphics': gpu.get('clock_graphics'),
            'clock_memory': gpu.get('clock_memory'),
            'processes': gpu.get('processes', []),
            # Intel/AMD specific engine utilization
            'engine_render': gpu.get('engine_render'),
            'engine_blitter': gpu.get('engine_blitter'),
            'engine_video': gpu.get('engine_video'),
            'engine_video_enhance': gpu.get('engine_video_enhance'),
            # Added for NVIDIA/AMD specific engine info if available
            'engine_encoder': gpu.get('engine_encoder'),
            'engine_decoder': gpu.get('engine_decoder'),
            'driver_version': gpu.get('driver_version'), # Added driver_version
            # SR-IOV modal detail (populated only when the GPU is an SR-IOV
            # Physical Function with active VFs, or a Virtual Function).
            'sriov_role': gpu.get('sriov_role'),
            'sriov_physfn': gpu.get('sriov_physfn'),
            'sriov_vf_count': gpu.get('sriov_vf_count'),
            'sriov_totalvfs': gpu.get('sriov_totalvfs'),
            'sriov_vfs': gpu.get('sriov_vfs'),
            'sriov_consumer': gpu.get('sriov_consumer'),
        }

        return jsonify(realtime_data)
    except Exception as e:
        # print(f"[v0] Error getting real-time GPU data: {e}")
        pass
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# CHANGE: Modificar el endpoint para incluir la información completa de IPs
@app.route('/api/vms/<int:vmid>', methods=['GET'])
@require_auth
def get_vm_config(vmid):
    """Get detailed configuration for a specific VM/LXC"""
    try:
        # Get VM/LXC configuration
        # node = socket.gethostname() # Get node name
        node = get_proxmox_node_name()
        
        result = subprocess.run(
            ['pvesh', 'get', f'/nodes/{node}/qemu/{vmid}/config', '--output-format', 'json'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        vm_type = 'qemu'
        if result.returncode != 0:
            # Try LXC
            result = subprocess.run(
                ['pvesh', 'get', f'/nodes/{node}/lxc/{vmid}/config', '--output-format', 'json'],
                capture_output=True,
                text=True,
                timeout=10
            )
            vm_type = 'lxc'
        
        if result.returncode == 0:
            config = json.loads(result.stdout)
            
            # Get VM/LXC status to check if it's running
            status_result = subprocess.run(
                ['pvesh', 'get', f'/nodes/{node}/{vm_type}/{vmid}/status/current', '--output-format', 'json'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            status = 'stopped'
            if status_result.returncode == 0:
                status_data = json.loads(status_result.stdout)
                status = status_data.get('status', 'stopped')
            
            response_data = {
                'vmid': vmid,
                'config': config,
                'node': node,
                'vm_type': vm_type
            }
            
            # For LXC, try to get IP from lxc-info if running
            if vm_type == 'lxc' and status == 'running':
                lxc_ip_info = get_lxc_ip_from_lxc_info(vmid)
                if lxc_ip_info:
                    response_data['lxc_ip_info'] = lxc_ip_info
            
            # Get OS information for LXC
            os_info = {}
            if vm_type == 'lxc' and status == 'running':
                try:
                    os_release_result = subprocess.run(
                        ['pct', 'exec', str(vmid), '--', 'cat', '/etc/os-release'],
                        capture_output=True, text=True, timeout=5)
                    
                    if os_release_result.returncode == 0:
                        for line in os_release_result.stdout.split('\n'):
                            line = line.strip()
                            if line.startswith('ID='):
                                os_info['id'] = line.split('=', 1)[1].strip('"').strip("'")
                            elif line.startswith('VERSION_ID='):
                                os_info['version_id'] = line.split('=', 1)[1].strip('"').strip("'")
                            elif line.startswith('NAME='):
                                os_info['name'] = line.split('=', 1)[1].strip('"').strip("'")
                            elif line.startswith('PRETTY_NAME='):
                                os_info['pretty_name'] = line.split('=', 1)[1].strip('"').strip("'")
                except Exception as e:
                    pass # Silently handle errors
            
            # Get hardware information for LXC
            hardware_info = {}
            if vm_type == 'lxc':
                hardware_info = parse_lxc_hardware_config(vmid, node)
            
            # Add OS info and hardware info to response
            if os_info:
                response_data['os_info'] = os_info
            if hardware_info:
                response_data['hardware_info'] = hardware_info
            
            return jsonify(response_data)
        
        return jsonify({'error': 'VM/LXC not found'}), 404
        
    except Exception as e:
        # print(f"Error getting VM config: {e}")
        pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/lxc/<int:vmid>/mount-points', methods=['GET'])
@require_auth
def api_lxc_mount_points(vmid):
    """Sprint 13.29: per-LXC mount points enumeration.

    Returns the parsed ``mpX:`` entries from the container config plus,
    when the container is running, runtime status (mounted/not, real
    fstype, options, stale detection) and any ad-hoc NFS/CIFS/SMB the
    user mounted from inside the CT. Capacity is always populated from
    the host-side source (PVE storage or `df` of the host path) so the
    info is meaningful even on stopped containers.
    """
    try:
        import lxc_mount_points
    except ImportError as e:
        return jsonify({"ok": False, "error": f"helper unavailable: {e}"}), 503
    try:
        result = lxc_mount_points.get_lxc_mount_points(str(vmid))
        if not result.get("ok"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/api/vms/<int:vmid>/logs', methods=['GET'])
@require_auth
def api_vm_logs(vmid):
    """Download real logs for a specific VM/LXC (not task history)"""
    try:
        # Get VM type and node
        resources = get_cached_pvesh_cluster_resources_vm()
        
        if resources:
            vm_info = None
            for resource in resources:
                if resource.get('vmid') == vmid:
                    vm_info = resource
                    break
            
            if not vm_info:
                return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
            
            vm_type = 'lxc' if vm_info.get('type') == 'lxc' else 'qemu'
            node = vm_info.get('node', 'pve')
            
            # Get real logs from the container/VM (last 1000 lines)
            log_result = subprocess.run(
                ['pvesh', 'get', f'/nodes/{node}/{vm_type}/{vmid}/log', '--start', '0', '--limit', '1000'],
                capture_output=True, text=True, timeout=10)
            
            logs = []
            if log_result.returncode == 0:
                # Parse as plain text (each line is a log entry)
                for i, line in enumerate(log_result.stdout.split('\n')):
                    if line.strip():
                        logs.append({'n': i, 't': line})
            
            return jsonify({
                'vmid': vmid,
                'name': vm_info.get('name'),
                'type': vm_type,
                'node': node,
                'log_lines': len(logs),
                'logs': logs
            })
        else:
            return jsonify({'error': 'Failed to get VM logs'}), 500
    except Exception as e:
        # print(f"Error getting VM logs: {e}")
        pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>/control', methods=['POST'])
@require_auth
def api_vm_control(vmid):
    """Control VM/LXC (start, stop, shutdown, reboot)"""
    try:
        data = request.get_json()
        action = data.get('action')  # start, stop, shutdown, reboot
        
        if action not in ['start', 'stop', 'shutdown', 'reboot']:
            return jsonify({'error': 'Invalid action'}), 400
        
        # Get VM type and node
        resources = get_cached_pvesh_cluster_resources_vm()
        
        if resources:
            vm_info = None
            for resource in resources:
                if resource.get('vmid') == vmid:
                    vm_info = resource
                    break
            
            if not vm_info:
                return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
            
            vm_type = 'lxc' if vm_info.get('type') == 'lxc' else 'qemu'
            node = vm_info.get('node', 'pve')
            
            # Execute action
            control_result = subprocess.run(
                ['pvesh', 'create', f'/nodes/{node}/{vm_type}/{vmid}/status/{action}'],
                capture_output=True, text=True, timeout=30)

            if control_result.returncode == 0:
                # Invalidate VM resources cache so the next /api/vms call
                # returns fresh status instead of the pre-action snapshot.
                _pvesh_cache['cluster_resources_vm_time'] = 0
                return jsonify({
                    'success': True,
                    'vmid': vmid,
                    'action': action,
                    'message': f'Successfully executed {action} on {vm_info.get("name")}'
                })
            else:
                # `pvesh` failed → fire the matching vm_fail / ct_fail
                # notification so the user gets paged on their channels
                # too, not just an in-dashboard alert. Previously this
                # path silently returned a 500 to the browser and lost
                # the event entirely (reported on .1.10: tried to start
                # VM 106 while log2ram tmpfs was full → 500 in the UI
                # but no Telegram message). The stderr is the most
                # useful single line we have — `pvesh` reliably prints
                # the underlying daemon failure there (e.g.
                # "start failed: command '/usr/bin/kvm …' failed with
                # exit code 1: no space left on device").
                err_text = (control_result.stderr or '').strip() \
                    or (control_result.stdout or '').strip() \
                    or f'{action} returned exit code {control_result.returncode}'
                # Truncate runaway stderr (some pvesh failures dump
                # multi-KB tracebacks) — keep the notification readable.
                if len(err_text) > 500:
                    err_text = err_text[:500] + ' …'

                try:
                    from notification_manager import notification_manager as _nm
                    import socket as _sock
                    _host = _sock.gethostname()
                    event_type = 'ct_fail' if vm_type == 'lxc' else 'vm_fail'
                    _nm.emit_event(
                        event_type=event_type,
                        severity='CRITICAL',
                        data={
                            'hostname': _host,
                            'vmid': str(vmid),
                            'vmname': vm_info.get('name') or f'{vm_type}-{vmid}',
                            'reason': f'{action} failed: {err_text}',
                            'action': action,
                        },
                        source='dashboard',
                        entity='vm',
                        entity_id=str(vmid),
                    )
                except Exception as _emit_err:
                    print(f"[api_vm_control] failed to emit {vm_type}_fail "
                          f"notification: {type(_emit_err).__name__}: {_emit_err}")

                return jsonify({
                    'success': False,
                    'vmid': vmid,
                    'action': action,
                    'error': err_text,
                }), 500
        else:
            return jsonify({'error': 'Failed to get VM details'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vms/<int:vmid>/description', methods=['PUT'])
@app.route('/api/vms/<int:vmid>/config', methods=['PUT'])  # legacy alias
@require_auth
def api_vm_config_update(vmid):
    """Update VM/LXC description (notes).

    The endpoint is named `/description` because that's all it touches —
    the legacy `/config` URL kept for backward compatibility with older
    frontends. Audit Tier 7 — `PUT /api/vms/<vmid>/config` mal nombrado.
    """
    try:
        data = request.get_json()
        description = data.get('description', '')
        
        # Get VM type and node
        resources = get_cached_pvesh_cluster_resources_vm()
        
        if resources:
            vm_info = None
            for resource in resources:
                if resource.get('vmid') == vmid:
                    vm_info = resource
                    break
            
            if not vm_info:
                return jsonify({'error': f'VM/LXC {vmid} not found'}), 404
            
            vm_type = 'lxc' if vm_info.get('type') == 'lxc' else 'qemu'
            node = vm_info.get('node', 'pve')
            
            # Update configuration with description
            config_result = subprocess.run(
                ['pvesh', 'set', f'/nodes/{node}/{vm_type}/{vmid}/config', '-description', description],
                capture_output=True, text=True, timeout=30)
            
            if config_result.returncode == 0:
                return jsonify({
                    'success': True,
                    'vmid': vmid,
                    'message': f'Successfully updated configuration for {vm_info.get("name")}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': config_result.stderr
                }), 500
        else:
            return jsonify({'error': 'Failed to get VM details'}), 500
    except Exception as e:
        # print(f"Error updating VM configuration: {e}")
        pass
        return jsonify({'error': str(e)}), 500


@app.route('/api/scripts/execute', methods=['POST'])
@require_auth
def execute_script():
    """Execute a script with real-time logging"""
    try:
        data = request.json
        script_name = data.get('script_name')
        script_params = data.get('params', {})
        

        script_relative_path = data.get('script_relative_path')

        if not script_relative_path:
            return jsonify({'error': 'script_relative_path is required'}), 400


        BASE_SCRIPTS_DIR = '/usr/local/share/proxmenux/scripts'
        script_path = os.path.join(BASE_SCRIPTS_DIR, script_relative_path)


        script_path = os.path.abspath(script_path)
        if not script_path.startswith(BASE_SCRIPTS_DIR):
            return jsonify({'error': 'Invalid script path'}), 403

        
        if not os.path.exists(script_path):
            return jsonify({'success': False, 'error': 'Script file not found'}), 404
        
        # Create session and start execution in background thread
        session_id = script_runner.create_session(script_name)
        
        def run_script():
            script_runner.execute_script(script_path, session_id, script_params)
        
        thread = threading.Thread(target=run_script, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scripts/status/<session_id>', methods=['GET'])
@require_auth
def get_script_status(session_id):
    """Get status of a running script"""
    try:
        status = script_runner.get_session_status(session_id)
        return jsonify(status)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scripts/respond', methods=['POST'])
@require_auth
def respond_to_script():
    """Respond to script interaction"""
    try:
        data = request.json
        session_id = data.get('session_id')
        interaction_id = data.get('interaction_id')
        value = data.get('value')
        
        result = script_runner.respond_to_interaction(session_id, interaction_id, value)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scripts/logs/<session_id>', methods=['GET'])
@require_auth
def stream_script_logs(session_id):
    """Stream logs from a running script"""
    try:
        def generate():
            for log_entry in script_runner.stream_logs(session_id):
                yield f"data: {log_entry}\n\n"
        
        return Response(generate(), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    import sys
    import logging
    
    # Custom filter to suppress TLS handshake noise when running HTTP
    # (browsers may cache HTTPS and keep sending TLS ClientHello to an HTTP server)
    class TLSNoiseFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage() if record else ""
            if "Bad request version" in msg or "Bad request syntax" in msg:
                return False
            return True
    
    # Silence werkzeug logger and add TLS noise filter
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    log.addFilter(TLSNoiseFilter())
    
    # Silence Flask CLI banner
    cli = sys.modules['flask.cli']
    cli.show_server_banner = lambda *x: None
    
    # ── Ensure journald stores info-level messages ──
    # Proxmox defaults MaxLevelStore=warning which drops info/notice entries.
    # This causes System Logs to show almost identical counts across date ranges
    # (since most log activity is info-level and gets silently discarded).
    # We create a drop-in to raise the level to info so logs are properly stored.
    try:
        journald_conf = "/etc/systemd/journald.conf"
        dropin_dir = "/etc/systemd/journald.conf.d"
        dropin_file = f"{dropin_dir}/proxmenux-loglevel.conf"
        
        if os.path.isfile(journald_conf) and not os.path.isfile(dropin_file):
            # Read current MaxLevelStore
            current_max = ""
            with open(journald_conf, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MaxLevelStore="):
                        current_max = line.split("=", 1)[1].strip().lower()
            
            restrictive_levels = {"emerg", "alert", "crit", "err", "warning"}
            if current_max in restrictive_levels:
                os.makedirs(dropin_dir, exist_ok=True)
                with open(dropin_file, 'w') as f:
                    f.write("# ProxMenux: Allow info-level messages for proper log display\n")
                    f.write("# Proxmox default MaxLevelStore=warning drops most system logs\n")
                    f.write("[Journal]\n")
                    f.write("MaxLevelStore=info\n")
                    f.write("MaxLevelSyslog=info\n")
                subprocess.run(["systemctl", "restart", "systemd-journald"], 
                             capture_output=True, timeout=10)
                print("[ProxMenux] Fixed journald MaxLevelStore (was too restrictive for log display)")
    except Exception as e:
        print(f"[ProxMenux] journald check skipped: {e}")
    
    # ── Temperature & Latency history collector ──
    # Initialize SQLite DB and start background thread to record CPU temp + latency every 60s
    if init_temperature_db() and init_latency_db():
        # Record initial readings immediately
        _record_temperature()
        _record_latency()
        # Sprint 14: per-disk temperature history shares the same DB
        # and the same 60s collector loop — initialize the table and
        # take a baseline sample so the first chart draw isn't empty.
        try:
            import disk_temperature_history
            if disk_temperature_history.init_disk_temperature_db():
                disk_temperature_history.record_all_disk_temperatures()
        except Exception as e:
            print(f"[ProxMenux] Disk temperature history init failed: {e}")

        # Sprint 14.7: managed-installs registry. Run a detection
        # sweep at startup so manual NVIDIA/Tailscale installs that
        # predated this build show up immediately — without waiting
        # for the first 24h notification cycle to populate the file.
        try:
            import managed_installs
            managed_installs.detect_and_register()
            print("[ProxMenux] Managed-installs registry initialised")
        except Exception as e:
            print(f"[ProxMenux] managed_installs init failed: {e}")

        # Self-healing maintenance run on every startup. Two passes, both
        # idempotent and safe to run repeatedly. They exist because issues
        # observed in the field (see comments below) silently corrupt user
        # data and were until now only fixable by manual SQL surgery.
        try:
            import sqlite3
            from pathlib import Path
            MONITOR_VERSION = '1.2.1.2-beta'
            db_path = Path('/usr/local/share/proxmenux/health_monitor.db')
            if db_path.exists():
                conn = sqlite3.connect(str(db_path), timeout=10)
                conn.execute('PRAGMA journal_mode=WAL')

                # Pass 1 — backfill resolution_type on orphan errors.
                # Some legacy code paths set `resolved_at` without setting
                # `resolution_type`, which leaves the rows in a half-resolved
                # state. The Monitor's overall-status badge counts them as
                # ACTIVE while the per-error list endpoint hides them
                # (resolved_at is non-NULL), producing a "Warning badge with
                # an empty modal" that the user has no way to clear from
                # the UI. We backfill `resolution_type='auto_cleanup'` so
                # both queries agree.
                orphans = conn.execute(
                    "UPDATE errors SET resolution_type = 'auto_cleanup', "
                    "resolution_reason = COALESCE(resolution_reason, "
                    "'Backfilled at startup — resolved_at present without "
                    "resolution_type') "
                    "WHERE resolved_at IS NOT NULL AND "
                    "(resolution_type IS NULL OR resolution_type = '')"
                ).rowcount

                # Pass 2 — version-bump cooldown reset.
                # When the AppImage is updated, drop the per-fingerprint
                # cooldowns for the "updates available" family so the first
                # poll cycle of the new build emits its initial summary
                # again. Without this, the global 24h cooldown (added in
                # 1.2.1.1-beta) silently swallows that ping — users who
                # relied on it as a "Monitor restarted OK" signal stopped
                # seeing anything after a redeploy. Only fires when the
                # version actually changed.
                row = conn.execute(
                    "SELECT setting_value FROM user_settings "
                    "WHERE setting_key = 'last_known_monitor_version'"
                ).fetchone()
                last_version = row[0] if row else ''
                cleared = 0
                if last_version != MONITOR_VERSION:
                    cleared = conn.execute(
                        "DELETE FROM notification_last_sent WHERE "
                        "fingerprint LIKE '%update_summary%' OR "
                        "fingerprint LIKE '%nvidia_driver_update_available%' OR "
                        "fingerprint LIKE '%post_install_update%' OR "
                        "fingerprint LIKE '%secure_gateway_update_available%'"
                    ).rowcount
                    conn.execute(
                        "INSERT OR REPLACE INTO user_settings "
                        "(setting_key, setting_value, updated_at) VALUES (?, ?, ?)",
                        ('last_known_monitor_version', MONITOR_VERSION,
                         datetime.now().isoformat())
                    )

                conn.commit()
                conn.close()

                if orphans:
                    print(f"[ProxMenux] startup: backfilled "
                          f"{orphans} orphan error(s) (resolved_at set "
                          f"without resolution_type)")
                if cleared:
                    print(f"[ProxMenux] startup: Monitor version bumped "
                          f"({last_version or '<none>'} → {MONITOR_VERSION}); "
                          f"cleared {cleared} update-related cooldown(s)")
        except Exception as e:
            print(f"[ProxMenux] startup self-heal failed: {e}")
        # Start background collector thread (handles both temp and latency)
        temp_thread = threading.Thread(target=_temperature_collector_loop, daemon=True)
        temp_thread.start()
        print("[ProxMenux] Temperature & Latency history collector started (60s interval)")
    else:
        print("[ProxMenux] Temperature/Latency history disabled (DB init failed)")

    # ── Background Health Monitor ──
    # Run full health checks every 5 min, keeping cache fresh and recording events for notifications
    try:
        health_thread = threading.Thread(target=_health_collector_loop, daemon=True)
        health_thread.start()
        print("[ProxMenux] Background health monitor started (5 min interval)")
    except Exception as e:
        print(f"[ProxMenux] Background health monitor failed to start: {e}")

    # ── Vital Signs Sampler (rapid CPU + Temperature) ──
    try:
        vital_thread = threading.Thread(target=_vital_signs_sampler, daemon=True)
        vital_thread.start()
    except Exception as e:
        print(f"[ProxMenux] Vital signs sampler failed to start: {e}")

    # ── Notification Service ──
    try:
        notification_manager.start()
        if notification_manager._enabled:
            print(f"[ProxMenux] Notification service started (channels: {list(notification_manager._channels.keys())})")
        else:
            print("[ProxMenux] Notification service loaded (disabled - configure in Settings)")
    except Exception as e:
        print(f"[ProxMenux] Notification service failed to start: {e}")

    # Check for SSL configuration
    ssl_ctx = None
    ssl_cert = None
    ssl_key = None
    try:
        ssl_ctx = auth_manager.get_ssl_context()
        if ssl_ctx:
            ssl_cert, ssl_key = ssl_ctx
            print(f"[ProxMenux] Starting with HTTPS (cert: {ssl_cert})")
        else:
            print("[ProxMenux] Starting with HTTP (no SSL configured)")
    except Exception as e:
        print(f"[ProxMenux] SSL config error, falling back to HTTP: {e}")
        ssl_ctx = None
    
    # Use gevent for SSL+WebSocket support, or fallback to Flask dev server
    gevent_available = False
    ssl_loaded = False
    
    if ssl_ctx:
        # Validate SSL certificates before starting server
        try:
            import ssl
            import os
            
            # Check certificate files exist and are readable
            if not os.path.isfile(ssl_cert):
                raise FileNotFoundError(f"SSL certificate not found: {ssl_cert}")
            if not os.path.isfile(ssl_key):
                raise FileNotFoundError(f"SSL key not found: {ssl_key}")
            
            # Try to load the certificate to validate it
            test_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            test_ctx.load_cert_chain(ssl_cert, ssl_key)
            ssl_loaded = True
            print(f"[ProxMenux] SSL certificates validated successfully")
        except Exception as e:
            print(f"[ProxMenux] SSL certificate error: {e}")
            print(f"[ProxMenux] Falling back to HTTP mode (SSL disabled)")
            ssl_ctx = None
    
    try:
        if ssl_ctx and ssl_loaded:
            # Try gevent with SSL for proper WebSocket (WSS) support
            try:
                from gevent import pywsgi
                from geventwebsocket.handler import WebSocketHandler
                import ssl
                
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(ssl_cert, ssl_key)
                
                print("[ProxMenux] Starting gevent server with SSL/WSS support...")
                # `::` binds IPv6 + IPv4 (v4-mapped) on Linux when
                # net.ipv6.bindv6only=0 (the default). Issue #192 — IPv4-only
                # listening broke ProxMenux on dual-stack / v6-only hosts.
                server = pywsgi.WSGIServer(
                    ('::', 8008),
                    app,
                    handler_class=WebSocketHandler,
                    ssl_context=ssl_context
                )
                gevent_available = True
                server.serve_forever()
            except ImportError as e:
                print(f"[ProxMenux] gevent not available ({e})")
                # Fallback: Flask dev server with SSL - flask-sock handles WebSockets
                import ssl
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(ssl_cert, ssl_key)
                print("[ProxMenux] Starting Flask server with SSL (using flask-sock for WebSockets)...")
                app.run(host='::', port=8008, debug=False, ssl_context=ssl_context)
        else:
            # HTTP mode - use Flask dev server (simpler, works fine without SSL)
            print("[ProxMenux] Starting Flask server with HTTP...")
            app.run(host='::', port=8008, debug=False)
    except Exception as e:
        if ssl_ctx and not gevent_available:
            print(f"[ProxMenux] SSL startup failed ({e}), falling back to HTTP")
            app.run(host='::', port=8008, debug=False)
        else:
            raise e
