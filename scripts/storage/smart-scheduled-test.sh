#!/bin/bash

# ==========================================================
# ProxMenux - SMART Scheduled Test Runner
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 1.0
# Last Updated: 13/04/2026
# ==========================================================
# Description:
# Runs scheduled SMART tests based on configuration.
# Called by cron jobs created by ProxMenux Monitor.
# ==========================================================

# Configuration
SMART_DIR="/usr/local/share/proxmenux/smart"
LOG_DIR="/var/log/proxmenux"
SCRIPT_NAME="smart-scheduled-test"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$SCRIPT_NAME] $1"
}

# Parse arguments
SCHEDULE_ID=""
TEST_TYPE="short"
RETENTION=10
DISKS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --schedule-id)
            SCHEDULE_ID="$2"
            shift 2
            ;;
        --test-type)
            TEST_TYPE="$2"
            shift 2
            ;;
        --retention)
            RETENTION="$2"
            shift 2
            ;;
        --disks)
            DISKS="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

log "Starting scheduled SMART test: schedule=$SCHEDULE_ID, type=$TEST_TYPE, retention=$RETENTION"

# Helper functions
_is_nvme() {
    [[ "$1" == *nvme* ]]
}

SMARTCTL_TYPE_ARGS=()

_resolve_smart_type() {
    local disk="$1" base real dtype output
    SMARTCTL_TYPE_ARGS=()
    _is_nvme "$disk" && return
    base=$(basename "$disk")
    real=$(readlink -f "/sys/block/$base" 2>/dev/null)
    [[ "$real" != */usb* ]] && return

    for dtype in sat sat,12 sat,16; do
        output=$(smartctl -i -j -d "$dtype" "$disk" 2>/dev/null)
        if printf '%s' "$output" | grep -qE '"(model_name|model_family|serial_number)"'; then
            SMARTCTL_TYPE_ARGS=(-d "$dtype")
            return
        fi
    done
}

_get_json_path() {
    local disk="$1"
    local test_type="$2"
    local disk_name
    disk_name=$(basename "$disk")
    local disk_dir="${SMART_DIR}/${disk_name}"
    local timestamp
    timestamp=$(date +%Y-%m-%dT%H-%M-%S)
    
    mkdir -p "$disk_dir"
    echo "${disk_dir}/${timestamp}_${test_type}.json"
}

_cleanup_old_jsons() {
    local disk="$1"
    local retention="$2"
    local disk_name
    disk_name=$(basename "$disk")
    local disk_dir="${SMART_DIR}/${disk_name}"
    
    if [[ -d "$disk_dir" && "$retention" -gt 0 ]]; then
        ls -1 "${disk_dir}"/*.json 2>/dev/null | sort -r | tail -n +$((retention + 1)) | xargs -r rm -f
    fi
}

_run_test() {
    local disk="$1"
    local test_type="$2"
    local json_path="$3"
    
    log "Running $test_type test on $disk"
    
    if _is_nvme "$disk"; then
        # NVMe test
        local code=1
        [[ "$test_type" == "long" ]] && code=2
        
        nvme device-self-test "$disk" --self-test-code=$code 2>/dev/null
        if [[ $? -ne 0 ]]; then
            log "ERROR: Failed to start NVMe test on $disk"
            return 1
        fi
        
        # Wait for test to complete
        local sleep_interval=10
        [[ "$test_type" == "long" ]] && sleep_interval=60
        
        sleep 5
        while true; do
            local op
            op=$(nvme self-test-log "$disk" -o json 2>/dev/null | grep -o '"Current Device Self-Test Operation":[0-9]*' | grep -o '[0-9]*$')
            [[ -z "$op" || "$op" -eq 0 ]] && break
            sleep $sleep_interval
        done
        
        # Save results
        nvme smart-log -o json "$disk" > "$json_path" 2>/dev/null
    else
        # SATA/SAS test
        local test_flag="-t short"
        [[ "$test_type" == "long" ]] && test_flag="-t long"
        _resolve_smart_type "$disk"
        
        smartctl $test_flag "${SMARTCTL_TYPE_ARGS[@]}" "$disk" 2>/dev/null
        local test_rc=$?
        if [[ $test_rc -ne 0 && $test_rc -ne 4 ]]; then
            log "ERROR: Failed to start SMART test on $disk"
            return 1
        fi
        
        # Wait for test to complete
        local sleep_interval=10
        [[ "$test_type" == "long" ]] && sleep_interval=60
        
        sleep 5
        while smartctl -c "${SMARTCTL_TYPE_ARGS[@]}" "$disk" 2>/dev/null | grep -qiE 'Self-test routine in progress|[1-9][0-9]?% of test remaining'; do
            sleep $sleep_interval
        done
        
        # Save results
        smartctl -a --json=c "${SMARTCTL_TYPE_ARGS[@]}" "$disk" > "$json_path" 2>/dev/null
    fi
    
    log "Test completed on $disk, results saved to $json_path"
    return 0
}

# Get list of disks to test
get_disk_list() {
    if [[ -n "$DISKS" && "$DISKS" != "all" ]]; then
        # Use specified disks
        echo "$DISKS" | tr ',' '\n'
    else
        # Get all physical disks
        lsblk -dpno NAME,TYPE 2>/dev/null | awk '$2=="disk"{print $1}'
    fi
}

# Main execution
DISK_LIST=$(get_disk_list)
TOTAL_DISKS=$(echo "$DISK_LIST" | wc -l)
SUCCESS_COUNT=0
FAIL_COUNT=0

log "Found $TOTAL_DISKS disk(s) to test"

for disk in $DISK_LIST; do
    # Accept both full paths and basenames. Older cron entries written
    # before the Monitor prepended /dev/ passed disk names as bare
    # basenames (sdb, nvme0n1), which then failed the block-device
    # check below. Normalising here keeps those legacy entries working
    # after the update without forcing the operator to recreate them.
    [[ "$disk" != /* ]] && disk="/dev/$disk"

    # Skip if disk doesn't exist
    if [[ ! -b "$disk" ]]; then
        log "WARNING: Disk $disk not found, skipping"
        continue
    fi
    
    # Get JSON path and cleanup old files
    JSON_PATH=$(_get_json_path "$disk" "$TEST_TYPE")
    _cleanup_old_jsons "$disk" "$RETENTION"
    
    # Run the test
    if _run_test "$disk" "$TEST_TYPE" "$JSON_PATH"; then
        ((SUCCESS_COUNT++))
    else
        ((FAIL_COUNT++))
    fi
done

log "Scheduled test complete: $SUCCESS_COUNT succeeded, $FAIL_COUNT failed"

# TODO: Send notification if configured
# This would integrate with the notification system

exit 0
