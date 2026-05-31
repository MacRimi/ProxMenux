#!/bin/bash

# ==========================================================
# ProxMenux - SMART Disk Health & Test Tool
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 12/04/2026
# ==========================================================
# Description:
# SMART health check and disk testing tool for Proxmox VE.
# Supports SATA/SAS disks (smartmontools) and NVMe drives (nvme-cli).
# Exports results as JSON to /usr/local/share/proxmenux/smart/
# for ProxMenux Monitor integration.
# Long tests run on the drive hardware and persist after terminal close.
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
BACKTITLE="ProxMenux"
SMART_DIR="$BASE_DIR/smart"
UI_MENU_H=22
UI_MENU_W=84
UI_MENU_LIST_H=12
UI_SHORT_MENU_H=16
UI_SHORT_MENU_W=72
UI_SHORT_MENU_LIST_H=6
UI_MSG_H=10
UI_MSG_W=72
UI_RESULT_H=14
UI_RESULT_W=86

# shellcheck source=/dev/null
[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache

SCRIPT_DIR_SMART="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPTS_LOCAL="$(cd "$SCRIPT_DIR_SMART/.." && pwd)"
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS_LOCAL/global/utils-install-functions.sh"
elif [[ -f "$LOCAL_SCRIPTS/global/utils-install-functions.sh" ]]; then
    source "$LOCAL_SCRIPTS/global/utils-install-functions.sh"
fi
# Configuration ============================================


# ==========================================================
# Helpers
# ==========================================================

_smart_is_nvme() {
  [[ "$1" == *nvme* ]]
}

_smart_disk_label() {
  local disk="$1"
  local model size
  model=$(lsblk -dn -o MODEL "$disk" 2>/dev/null | xargs)
  size=$(lsblk -dn -o SIZE  "$disk" 2>/dev/null | xargs)
  [[ -z "$model" ]] && model="Unknown"
  [[ -z "$size"  ]] && size="?"
  printf '%-8s — %s' "$size" "$model"
}

_smart_json_path() {
  local disk="$1"
  local test_type="${2:-short}"
  local disk_name
  disk_name=$(basename "$disk")
  local disk_dir="${SMART_DIR}/${disk_name}"
  local timestamp
  timestamp=$(date +%Y-%m-%dT%H-%M-%S)
  
  # Create disk directory if it doesn't exist
  mkdir -p "$disk_dir"
  
  echo "${disk_dir}/${timestamp}_${test_type}.json"
}

_smart_get_latest_json() {
  local disk="$1"
  local disk_name
  disk_name=$(basename "$disk")
  local disk_dir="${SMART_DIR}/${disk_name}"
  
  if [[ -d "$disk_dir" ]]; then
    # Get most recent JSON file (sorted by name = sorted by timestamp)
    ls -1 "${disk_dir}"/*.json 2>/dev/null | sort -r | head -1
  fi
}

_smart_cleanup_old_jsons() {
  local disk="$1"
  local retention="${2:-10}"  # Default: keep last 10
  local disk_name
  disk_name=$(basename "$disk")
  local disk_dir="${SMART_DIR}/${disk_name}"
  
  if [[ -d "$disk_dir" && "$retention" -gt 0 ]]; then
    # List all JSON files sorted by name (oldest last), skip first $retention, delete rest
    ls -1 "${disk_dir}"/*.json 2>/dev/null | sort -r | tail -n +$((retention + 1)) | xargs -r rm -f
  fi
}

_smart_ensure_packages() {
  local need_smartctl=0 need_nvme=0
  command -v smartctl >/dev/null 2>&1 || need_smartctl=1
  command -v nvme     >/dev/null 2>&1 || need_nvme=1
  if [[ $need_smartctl -eq 1 || $need_nvme -eq 1 ]]; then
    show_proxmenux_logo
    msg_title "$(translate 'SMART Disk Health & Test')"
    ensure_repositories
    [[ $need_smartctl -eq 1 ]] && install_single_package "smartmontools" "smartctl" "SMART monitoring tools"
    [[ $need_nvme -eq 1     ]] && install_single_package "nvme-cli"      "nvme"     "NVMe management tools"
  fi
}


# ==========================================================
# PHASE 1 — SELECTION
# All dialogs run here. No execution, no show_proxmenux_logo.
# ==========================================================

# ── Install packages if missing ───────────────────────────
_smart_ensure_packages

# ── Step 1: Detect disks ──────────────────────────────────
DISK_OPTIONS=()
while read -r disk; do
  [[ -z "$disk" ]] && continue
  [[ "$disk" =~ ^/dev/zd ]] && continue
  label=$(_smart_disk_label "$disk")
  DISK_OPTIONS+=("$disk" "$label")
done < <(lsblk -dn -e 7,11 -o PATH 2>/dev/null | grep -E '^/dev/(sd|nvme|vd|hd)')
stop_spinner

if [[ ${#DISK_OPTIONS[@]} -eq 0 ]]; then
  dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'No Disks Found')" \
    --msgbox "\n$(translate 'No physical disks detected for SMART testing.')" \
    $UI_MSG_H $UI_MSG_W
  exit 1
fi

# ── Step 2: Select disk ───────────────────────────────────
SELECTED_DISK=$(dialog --backtitle "$BACKTITLE" \
  --title "$(translate 'Select Disk')" \
  --menu "\n$(translate 'Select the disk to test or inspect:')" \
  $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
  "${DISK_OPTIONS[@]}" \
  2>&1 >/dev/tty)
[[ -z "$SELECTED_DISK" ]] && exit 0

# ── Steps 3+: Action loop for the selected disk ───────────
DISK_LABEL=$(_smart_disk_label "$SELECTED_DISK")
mkdir -p "$SMART_DIR"

while true; do

  # ── Select action ───────────────────────────────────────
  ACTION=$(dialog --backtitle "$BACKTITLE" \
    --title "$(translate 'SMART Action') — $(basename "$SELECTED_DISK") (${DISK_LABEL})" \
    --menu "\n$(translate 'Select what to do with this disk:')" \
    $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
    "status"   "$(translate 'Quick health status   — overall SMART result + key attributes')" \
    "report"   "$(translate 'Full report           — complete SMART data (scrollable)')" \
    "short"    "$(translate 'Short test            — ~2 minutes, basic surface check')" \
    "long"     "$(translate 'Long test             — full scan, runs in background if closed')" \
    "progress" "$(translate 'Check test progress   — show active or last test result')" \
    2>&1 >/dev/tty)
  [[ -z "$ACTION" ]] && exit 0

  # ── Long test confirmation ───────────────────────────────
  if [[ "$ACTION" == "long" ]]; then
    DISK_SIZE=$(lsblk -dn -o SIZE "$SELECTED_DISK" 2>/dev/null | xargs)
    if ! dialog --backtitle "$BACKTITLE" \
      --title "$(translate 'Long Test — Background')" \
      --yesno "\n$(translate 'The long test runs directly on the disk hardware.')\n\n$(translate 'Disk:') $SELECTED_DISK ($DISK_SIZE)\n\n$(translate 'The test will continue even if you close this terminal.')\n$(translate 'Results will be saved automatically to:')\n$(_smart_json_path "$SELECTED_DISK" "long")\n\n$(translate 'Start long test now?')" \
      16 $UI_RESULT_W; then
      continue
    fi
  fi


  # ========================================================
  # PHASE 2 — EXECUTION
  # show_proxmenux_logo appears here exactly once per action.
  # No dialogs from this point until "Press Enter".
  # ========================================================

  show_proxmenux_logo
  msg_title "$(translate 'SMART Disk Health & Test')"
  msg_ok "$(translate 'Disk:') ${BL}${SELECTED_DISK} — ${DISK_LABEL}${CL}"
  echo ""

  case "$ACTION" in

    # ── Quick status ────────────────────────────────────────
    status)
      if _smart_is_nvme "$SELECTED_DISK"; then
        msg_info "$(translate 'Reading NVMe SMART data...')"
        OUTPUT=$(nvme smart-log "$SELECTED_DISK" 2>/dev/null)
        stop_spinner
        if [[ -z "$OUTPUT" ]]; then
          msg_error "$(translate 'Could not read SMART data from') $SELECTED_DISK"
        else
          HEALTH=$(echo "$OUTPUT" | grep -i "critical_warning" | awk '{print $NF}')
          if [[ "$HEALTH" == "0" ]]; then
            msg_ok "$(translate 'NVMe health status: PASSED')"
          else
            msg_warn "$(translate 'NVMe health status: WARNING (critical_warning =') $HEALTH)"
          fi
          echo ""
          echo "$OUTPUT" | head -20
        fi
      else
        msg_info "$(translate 'Reading SMART data...')"
        HEALTH=$(smartctl -H "$SELECTED_DISK" 2>/dev/null | grep -i "overall-health")
        ATTRS=$(smartctl -A "$SELECTED_DISK" 2>/dev/null)
        stop_spinner
        if [[ -z "$HEALTH" ]]; then
          msg_error "$(translate 'Could not read SMART data from') $SELECTED_DISK"
        else
          if echo "$HEALTH" | grep -qi "PASSED"; then
            msg_ok "$(translate 'SMART health status: PASSED')"
          else
            msg_warn "$HEALTH"
          fi
          echo ""
          echo "$ATTRS" | awk 'NR==1 || /Reallocated_Sector|Current_Pending|Uncorrectable|Temperature_Celsius|Power_On_Hours|Wear_Leveling|Media_Wearout/'
        fi
      fi
      ;;

    # ── Full report (scrollable) ────────────────────────────
    report)
      msg_info "$(translate 'Reading full SMART report...')"
      TMPFILE=$(mktemp)
      if _smart_is_nvme "$SELECTED_DISK"; then
        nvme smart-log "$SELECTED_DISK" > "$TMPFILE" 2>/dev/null
        nvme id-ctrl  "$SELECTED_DISK" >> "$TMPFILE" 2>/dev/null
      else
        smartctl -x "$SELECTED_DISK" > "$TMPFILE" 2>/dev/null
      fi
      stop_spinner
      if [[ -s "$TMPFILE" ]]; then
        dialog --backtitle "$BACKTITLE" \
          --title "$(translate 'Full SMART Report') — $SELECTED_DISK" \
          --textbox "$TMPFILE" 40 $UI_RESULT_W
      else
        msg_error "$(translate 'Could not read SMART data from') $SELECTED_DISK"
      fi
      rm -f "$TMPFILE"
      ;;

    # ── Short test ──────────────────────────────────────────
    short)
      if _smart_is_nvme "$SELECTED_DISK"; then
        msg_info "$(translate 'Starting NVMe short self-test...')"
        if nvme device-self-test "$SELECTED_DISK" --self-test-code=1 >/dev/null 2>&1; then
          stop_spinner
          msg_ok "$(translate 'Short self-test started on') $SELECTED_DISK"
          msg_ok "$(translate 'Test typically completes in ~2 minutes.')"
          msg_ok "$(translate 'Use "Check test progress" to see results.')"
        else
          stop_spinner
          msg_error "$(translate 'Failed to start self-test on') $SELECTED_DISK"
        fi
      else
        msg_info "$(translate 'Starting SMART short self-test...')"
        OUTPUT=$(smartctl -t short "$SELECTED_DISK" 2>/dev/null)
        stop_spinner
        if echo "$OUTPUT" | grep -qi "Test will complete"; then
          msg_ok "$(translate 'Short self-test started on') $SELECTED_DISK"
          ESTIMATE=$(echo "$OUTPUT" | grep -i "complete after" | head -1)
          [[ -n "$ESTIMATE" ]] && msg_ok "$ESTIMATE"
          msg_ok "$(translate 'Use "Check test progress" to see results.')"
        else
          msg_error "$(translate 'Failed to start self-test on') $SELECTED_DISK"
          echo "$OUTPUT" | tail -5
        fi
      fi
      ;;

  # ── Long test (background) ──────────────────────────────
  long)
    JSON_PATH=$(_smart_json_path "$SELECTED_DISK" "long")
    _smart_cleanup_old_jsons "$SELECTED_DISK"
      DISK_SAFE=$(printf '%q' "$SELECTED_DISK")
      JSON_SAFE=$(printf '%q' "$JSON_PATH")

      if _smart_is_nvme "$SELECTED_DISK"; then
        msg_info "$(translate 'Starting NVMe long self-test...')"
        if nvme device-self-test "$SELECTED_DISK" --self-test-code=2 >/dev/null 2>&1; then
          stop_spinner
          msg_ok "$(translate 'Long self-test started on') $SELECTED_DISK"
          DISK_LABEL_SAFE=$(printf '%q' "$DISK_LABEL")
          NOTIFY_SCRIPT="/usr/bin/notification_manager.py"
          nohup bash -c "
            while nvme device-self-test ${DISK_SAFE} --self-test-code=0 2>/dev/null | grep -qi 'in progress'; do
              sleep 60
            done
            nvme smart-log -o json ${DISK_SAFE} > ${JSON_SAFE} 2>/dev/null
            
            # Send notification when test completes
            if [[ -f \"${NOTIFY_SCRIPT}\" ]]; then
              HOSTNAME=\$(hostname -s)
              TEST_RESULT=\$(nvme self-test-log ${DISK_SAFE} 2>/dev/null | head -20)
              if echo \"\$TEST_RESULT\" | grep -qi 'completed without error\|success'; then
                python3 \"${NOTIFY_SCRIPT}\" --action send-raw --severity INFO \
                  --title \"\${HOSTNAME}: SMART Long Test Completed\" \
                  --message \"NVMe disk ${DISK_SAFE} (${DISK_LABEL_SAFE}) - Long self-test completed successfully.\" 2>/dev/null || true
              else
                python3 \"${NOTIFY_SCRIPT}\" --action send-raw --severity WARNING \
                  --title \"\${HOSTNAME}: SMART Long Test Completed\" \
                  --message \"NVMe disk ${DISK_SAFE} (${DISK_LABEL_SAFE}) - Long self-test completed. Check results for details.\" 2>/dev/null || true
              fi
            fi
          " >/dev/null 2>&1 &
          disown $!
        else
          stop_spinner
          msg_error "$(translate 'Failed to start long self-test on') $SELECTED_DISK"
        fi
      else
        msg_info "$(translate 'Starting SMART long self-test...')"
        OUTPUT=$(smartctl -t long "$SELECTED_DISK" 2>/dev/null)
        stop_spinner
        if echo "$OUTPUT" | grep -qi "Test will complete"; then
          msg_ok "$(translate 'Long self-test started on') $SELECTED_DISK"
          ESTIMATE=$(echo "$OUTPUT" | grep -i "complete after" | head -1)
          [[ -n "$ESTIMATE" ]] && msg_ok "$ESTIMATE"
          echo ""
          msg_ok "$(translate 'Test runs on the drive hardware — safe to close this terminal.')"
          msg_ok "$(translate 'Results will be saved to:') $JSON_PATH"
          DISK_LABEL_SAFE=$(printf '%q' "$DISK_LABEL")
          NOTIFY_SCRIPT="/usr/bin/notification_manager.py"
          nohup bash -c "
            while smartctl -c ${DISK_SAFE} 2>/dev/null | grep -qiE 'Self-test routine in progress|[1-9][0-9]?% of test remaining'; do
              sleep 60
            done
            smartctl -a --json=c ${DISK_SAFE} > ${JSON_SAFE} 2>/dev/null
            
            # Send notification when test completes
            if [[ -f \"${NOTIFY_SCRIPT}\" ]]; then
              HOSTNAME=\$(hostname -s)
              TEST_RESULT=\$(smartctl -l selftest ${DISK_SAFE} 2>/dev/null | grep -E '^# ?1')
              if echo \"\$TEST_RESULT\" | grep -qi 'Completed without error'; then
                python3 \"${NOTIFY_SCRIPT}\" --action send-raw --severity INFO \
                  --title \"\${HOSTNAME}: SMART Long Test Completed\" \
                  --message \"Disk ${DISK_SAFE} (${DISK_LABEL_SAFE}) - Long self-test completed successfully.\" 2>/dev/null || true
              elif echo \"\$TEST_RESULT\" | grep -qi 'error\|fail'; then
                python3 \"${NOTIFY_SCRIPT}\" --action send-raw --severity CRITICAL \
                  --title \"\${HOSTNAME}: SMART Long Test FAILED\" \
                  --message \"Disk ${DISK_SAFE} (${DISK_LABEL_SAFE}) - Long self-test completed with ERRORS. Check disk health immediately.\" 2>/dev/null || true
              else
                python3 \"${NOTIFY_SCRIPT}\" --action send-raw --severity INFO \
                  --title \"\${HOSTNAME}: SMART Long Test Completed\" \
                  --message \"Disk ${DISK_SAFE} (${DISK_LABEL_SAFE}) - Long self-test completed. Check results for details.\" 2>/dev/null || true
              fi
            fi
          " >/dev/null 2>&1 &
          disown $!
        else
          msg_error "$(translate 'Failed to start long self-test on') $SELECTED_DISK"
          echo "$OUTPUT" | tail -5
        fi
      fi
      ;;

    # ── Check progress ──────────────────────────────────────
    progress)
      if _smart_is_nvme "$SELECTED_DISK"; then
        msg_info "$(translate 'Reading NVMe self-test log...')"
        OUTPUT=$(nvme self-test-log "$SELECTED_DISK" 2>/dev/null)
        stop_spinner
        if [[ -z "$OUTPUT" ]]; then
          msg_warn "$(translate 'No self-test log available for') $SELECTED_DISK"
        else
          echo "$OUTPUT" | head -30
        fi
      else
        msg_info "$(translate 'Reading SMART self-test log...')"
        # Active test: only "X% of test remaining" appears when a test is actually running
        ACTIVE=$(smartctl -c "$SELECTED_DISK" 2>/dev/null | grep -iE "[1-9][0-9]?% of test remaining|Self-test routine in progress")
        # Log: grab only result rows (^# N ...) and the column header (^Num)
        LOG_OUT=$(smartctl -l selftest "$SELECTED_DISK" 2>/dev/null)
        LOG_HEADER=$(echo "$LOG_OUT" | grep -E "^Num")
        LOG_ENTRIES=$(echo "$LOG_OUT" | grep -E "^# ?[0-9]")
        stop_spinner
        if [[ -n "$ACTIVE" ]]; then
          msg_ok "$(translate 'Test in progress:')"
          echo "$ACTIVE"
          echo ""
        else
          msg_ok "$(translate 'No test currently running')"
          echo ""
        fi
        if [[ -n "$LOG_ENTRIES" ]]; then
          msg_ok "$(translate 'Recent test results:')"
          [[ -n "$LOG_HEADER" ]] && echo "$LOG_HEADER"
          echo "$LOG_ENTRIES"
        else
          msg_warn "$(translate 'No self-test history found for') $SELECTED_DISK"
        fi
      fi
      ;;

  esac

  # ── Auto-export JSON (except long — handled by background monitor)
  if [[ "$ACTION" != "long" && "$ACTION" != "report" ]]; then
    # Determine test type from ACTION (short test or status check).
    # NOTE: no 'local' here — this block runs inside the top-level while loop,
    # not inside a function, so 'local' would print a bash warning at runtime.
    json_test_type="short"
    [[ "$ACTION" == "status" ]] && json_test_type="status"
    
    JSON_PATH=$(_smart_json_path "$SELECTED_DISK" "$json_test_type")
    _smart_cleanup_old_jsons "$SELECTED_DISK"
    
    if _smart_is_nvme "$SELECTED_DISK"; then
      nvme smart-log -o json "$SELECTED_DISK" > "$JSON_PATH" 2>/dev/null
    else
      smartctl -a --json=c "$SELECTED_DISK" > "$JSON_PATH" 2>/dev/null
    fi
    [[ -s "$JSON_PATH" ]] || rm -f "$JSON_PATH"
  fi

  # ── "report" uses dialog --textbox, no Press Enter needed
  if [[ "$ACTION" != "report" ]]; then
    echo ""
    msg_success "$(translate 'Press Enter to continue...')"
    read -r
  fi

done
