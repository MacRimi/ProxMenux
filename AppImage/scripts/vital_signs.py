"""The host's vital signs, read once and shared by the whole Monitor.

CPU usage is measured only by the vital-signs sampler, from the /proc/stat
counters since its previous reading; everything else takes that reading.
Memory and sensor temperatures go through one shared cache: the sampler
reads them at its own pace, and the dashboard, the health checks and the
exporters reuse the latest reading whenever it is recent enough for them.
"""

import math
import threading
import time

import psutil

# How often the sampler reads each value, in seconds.
CPU_INTERVAL = 5
TEMPERATURE_INTERVAL = 15
MEMORY_INTERVAL = 30

# What a page that polls every few seconds accepts as current.
LIVE_MAX_AGE = 5

_lock = threading.Lock()
_readings = {}
_cpu_counters = None

# Intel, AMD (two drivers), generic ARM, then the ACPI thermal zone, which
# is usually the motherboard.
_CPU_SENSORS = ('coretemp', 'k10temp', 'cpu_thermal', 'zenpower', 'acpitz')


def samples_for(seconds, interval):
    """How many readings taken every `interval` seconds cover `seconds`."""
    return max(1, math.ceil(seconds / interval))


def _remember(name, value):
    with _lock:
        _readings[name] = (time.monotonic(), value)
    return value


def _recent(name, max_age):
    with _lock:
        entry = _readings.get(name)
    if entry is not None and time.monotonic() - entry[0] <= max_age:
        return entry[1]
    return None


def _usage_between(previous, current):
    """CPU use between two psutil.cpu_times() snapshots, or None."""
    def field(sample, name):
        return getattr(sample, name, 0) or 0

    def total(sample):
        # guest time is already counted in user and nice
        return sum(sample) - field(sample, 'guest') - field(sample, 'guest_nice')

    elapsed = total(current) - total(previous)
    if elapsed <= 0:
        return None

    def share(*names):
        spent = sum(field(current, n) - field(previous, n) for n in names)
        return round(min(100.0, max(0.0, spent * 100.0 / elapsed)), 1)

    return {
        'value': round(100.0 - share('idle', 'iowait'), 1),
        'user': share('user', 'nice'),
        'system': share('system', 'irq', 'softirq'),
    }


def sample_cpu():
    """CPU use since the previous call. Only the sampler calls this."""
    global _cpu_counters
    counters = psutil.cpu_times()
    with _lock:
        previous, _cpu_counters = _cpu_counters, counters
    usage = _usage_between(previous, counters) if previous is not None else None
    return _remember('cpu', usage) if usage else None


def cpu():
    """The latest CPU reading of the sampler. Before its first reading, or
    if it stopped, a short measurement of its own."""
    usage = _recent('cpu', 3 * CPU_INTERVAL)
    if usage is None:
        first = psutil.cpu_times()
        time.sleep(0.1)
        usage = _usage_between(first, psutil.cpu_times()) or {'value': 0.0, 'user': 0.0, 'system': 0.0}
    return usage


def memory(max_age=LIVE_MAX_AGE):
    """(virtual memory, swap) as psutil reports them."""
    reading = _recent('memory', max_age)
    if reading is None:
        reading = _remember('memory', (psutil.virtual_memory(), psutil.swap_memory()))
    return reading


def temperatures(max_age=LIVE_MAX_AGE):
    """psutil.sensors_temperatures(), or {} on a host without sensors."""
    reading = _recent('temperatures', max_age)
    if reading is None:
        try:
            reading = psutil.sensors_temperatures() or {}
        except (AttributeError, OSError):
            reading = {}
        _remember('temperatures', reading)
    return reading


def cpu_temperature(readings=None):
    """The CPU's own sensor, or the first one reported; 0 without sensors."""
    readings = temperatures() if readings is None else readings
    for name in _CPU_SENSORS:
        if readings.get(name):
            return readings[name][0].current
    for entries in readings.values():
        if entries:
            return entries[0].current
    return 0


def highest_temperature(readings=None):
    """The highest temperature any sensor reports, or None."""
    readings = temperatures() if readings is None else readings
    values = [float(entry.current) for entries in readings.values() for entry in entries
              if isinstance(entry.current, (int, float)) and 0 < entry.current < 150]
    return max(values) if values else None
