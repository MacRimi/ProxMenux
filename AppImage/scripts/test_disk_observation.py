#!/usr/bin/env python3
"""
Test script to simulate a disk error and verify observation recording.
Usage: python3 test_disk_observation.py [device_name] [error_type]

Examples:
  python3 test_disk_observation.py sdh io_error
  python3 test_disk_observation.py sdh smart_error
  python3 test_disk_observation.py sdh fs_error
"""

import sys
import os

# Add possible module locations to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
sys.path.insert(0, '/usr/local/share/proxmenux')
sys.path.insert(0, '/tmp/.mount_ProxMeztyU13/usr/bin')  # AppImage mount point

# Try to find the module
for path in sys.path:
    if os.path.exists(os.path.join(path, 'health_persistence.py')):
        print(f"[INFO] Found health_persistence.py in: {path}")
        break

from health_persistence import HealthPersistence
from datetime import datetime

def main():
    device_name = sys.argv[1] if len(sys.argv) > 1 else 'sdh'
    error_type = sys.argv[2] if len(sys.argv) > 2 else 'io_error'
    
    # Known serial for sdh (WDC 2TB)
    serial_map = {
        'sdh': 'WD-WX72A30AA72R',
        'nvme0n1': '2241E675EA6C',
        'nvme1n1': '2241E675EBE6',
        'sda': '22440F443504',
        'sdb': 'WWZ1SJ18',
        'sdc': '52X0A0D9FZ1G',
        'sdd': '50026B7784446E63',
        'sde': '22440F442105',
        'sdf': 'WRQ0X2GP',
        'sdg': '23Q0A0MPFZ1G',
    }
    
    serial = serial_map.get(device_name, None)
    
    # Error messages by type
    error_messages = {
        'io_error': f'Test I/O error on /dev/{device_name}: sector read failed at LBA 12345678',
        'smart_error': f'/dev/{device_name}: SMART warning - 1 Currently unreadable (pending) sectors detected',
        'fs_error': f'EXT4-fs error (device {device_name}1): inode 123456: block 789012: error reading data',
    }
    
    error_signatures = {
        'io_error': f'io_test_{device_name}',
        'smart_error': f'smart_test_{device_name}',
        'fs_error': f'fs_test_{device_name}',
    }
    
    message = error_messages.get(error_type, f'Test error on /dev/{device_name}')
    signature = error_signatures.get(error_type, f'test_{device_name}')
    
    print(f"\n{'='*60}")
    print(f"Testing Disk Observation Recording")
    print(f"{'='*60}")
    print(f"Device:     /dev/{device_name}")
    print(f"Serial:     {serial or 'Unknown'}")
    print(f"Error Type: {error_type}")
    print(f"Message:    {message}")
    print(f"Signature:  {signature}")
    print(f"{'='*60}\n")
    
    # Initialize persistence
    hp = HealthPersistence()
    
    # Record the observation
    print("[1] Recording observation...")
    hp.record_disk_observation(
        device_name=device_name,
        serial=serial,
        error_type=error_type,
        error_signature=signature,
        raw_message=message,
        severity='warning'
    )
    print("    OK - Observation recorded\n")
    
    # Query observations for this device
    print("[2] Querying observations for this device...")
    observations = hp.get_disk_observations(device_name=device_name, serial=serial)
    
    if observations:
        print(f"    Found {len(observations)} observation(s):\n")
        for obs in observations:
            print(f"    ID: {obs['id']}")
            print(f"    Type: {obs['error_type']}")
            print(f"    Signature: {obs['error_signature']}")
            print(f"    Message: {obs['raw_message'][:80]}...")
            print(f"    Severity: {obs['severity']}")
            print(f"    First: {obs['first_occurrence']}")
            print(f"    Last: {obs['last_occurrence']}")
            print(f"    Count: {obs['occurrence_count']}")
            print()
    else:
        print("    No observations found!\n")
    
    # Also show the disk registry
    print("[3] Checking disk registry...")
    all_devices = hp.get_all_observed_devices()
    for dev in all_devices:
        if dev.get('device_name') == device_name or dev.get('serial') == serial:
            print(f"    Found in registry:")
            print(f"    ID: {dev.get('id')}")
            print(f"    Device: {dev.get('device_name')}")
            print(f"    Serial: {dev.get('serial')}")
            print(f"    First seen: {dev.get('first_seen')}")
            print(f"    Last seen: {dev.get('last_seen')}")
            print()
    
    print(f"{'='*60}")
    print("Test complete! Check the Storage section in the UI.")
    print(f"The disk /dev/{device_name} should now show an observations badge.")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
