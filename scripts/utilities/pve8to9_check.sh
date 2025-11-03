#!/bin/bash
# ==========================================================
# ProxMenuX - Upgrade PVE 8 → 9 (Simplified, per official guide)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 14/08/2025
# ==========================================================

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"


if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache


# ==========================================================

LOG="/var/log/pve8-a-pve9-$(date +%Y%m%d-%H%M%S).log"
: > "$LOG"

disable_translation_post_upgrade() {
  translate() { echo "$1"; }
}
disable_translation_post_upgrade

if [[ "$pve_version" -ge 9 ]]; then
  disable_translation_post_upgrade
fi



run_pve8to9_check2() {
  local tmp
  tmp="$(mktemp)"
  echo -e
  set -o pipefail
  pve8to9 --full 2>&1 | tee -a "$LOG" | tee "$tmp"
  local rc=${PIPESTATUS[0]}

  local fails warns
  fails=$(grep -c 'FAIL:' "$tmp" || true)
  warns=$(grep -c 'WARN:' "$tmp" || true)


    if (( fails > 0 )); then
      echo -e
      echo -e "${BFR}${RD}[ERROR] $(translate "Pre-check found") $fails $(translate "blocking issue(s).")\n$(translate "Please resolve the problem(s) as described above, then re-run the upgrade script.")${CL}"
      echo -e
      
      local repair_commands=()
      local repair_descriptions=()
      
      # Error 1: systemd-boot meta-package
      if grep -q 'systemd-boot meta-package installed' "$tmp"; then
        repair_commands+=("apt install systemd-boot-efi systemd-boot-tools -y && apt remove systemd-boot -y")
        repair_descriptions+=("$(translate "Fix systemd-boot meta-package conflict")")
        echo -e "${YW}$(translate "Fix systemd-boot:") ${CL}apt install systemd-boot-efi systemd-boot-tools -y && apt remove systemd-boot -y"
      fi
      
      
      # Error 2: Ceph version incompatible
      if grep -q -E '(ceph.*version|ceph.*incompatible)' "$tmp"; then
        repair_commands+=("ceph versions && pveceph upgrade")
        repair_descriptions+=("$(translate "Upgrade Ceph to compatible version")")
        echo -e "${YW}$(translate "Fix Ceph version:") ${CL}ceph versions && pveceph upgrade"
      fi
      
      # Error 3: Repository configuration issues
      if grep -q -E '(repository.*issue|repo.*problem|sources.*error)' "$tmp"; then
        repair_commands+=("cleanup_duplicate_repos && configure_repositories")
        repair_descriptions+=("$(translate "Fix repository configuration")")
        echo -e "${YW}$(translate "Fix repositories:") ${CL}cleanup_duplicate_repos && configure_repositories"
      fi
      
      # Error 4: Package conflicts
      if grep -q -E '(package.*conflict|dependency.*problem)' "$tmp"; then
        repair_commands+=("apt update && apt autoremove -y && apt autoclean")
        repair_descriptions+=("$(translate "Resolve package conflicts")")
        echo -e "${YW}$(translate "Fix package conflicts:") ${CL}apt update && apt autoremove -y && apt autoclean"
      fi
      
      # Error 5: Disk space issues
      if grep -q -E '(disk.*space|storage.*full|no.*space)' "$tmp"; then
        repair_commands+=("apt clean && apt autoremove -y && journalctl --vacuum-time=7d")
        repair_descriptions+=("$(translate "Free up disk space")")
        echo -e "${YW}$(translate "Fix disk space:") ${CL}apt clean && apt autoremove -y && journalctl --vacuum-time=7d"
      fi
      
      # Error 6: Network/DNS issues
      if grep -q -E '(network.*error|dns.*problem|connection.*failed)' "$tmp"; then
        repair_commands+=("systemctl restart networking && systemctl restart systemd-resolved")
        repair_descriptions+=("$(translate "Fix network connectivity")")
        echo -e "${YW}$(translate "Fix network:") ${CL}systemctl restart networking && systemctl restart systemd-resolved"
      fi
      
      echo -e
      

      if [[ ${#repair_commands[@]} -gt 0 ]]; then
        echo -e "${BFR}${CY}$(translate "Repair Options:")${CL}"
        echo -e "${TAB}${GN}1.${CL} $(translate "Try automatic repair of detected issues")"
        echo -e "${TAB}${GN}2.${CL} $(translate "Show manual repair commands")"
        echo -e
        echo -n "$(translate "Select option [1-2] (default: 2): ")"
        read -r repair_choice
        
        case "$repair_choice" in
          1)
            echo -e
            msg_info2 "$(translate "Attempting automatic repair...")"
            local repair_success=0
            for i in "${!repair_commands[@]}"; do
              echo -e "${TAB}${YW}$(translate "Executing:") ${repair_descriptions[$i]}${CL}"
              if eval "${repair_commands[$i]}"; then
                msg_ok "${repair_descriptions[$i]} - $(translate "Success")"
              else
                msg_error "${repair_descriptions[$i]} - $(translate "Failed")"
                repair_success=1
              fi
            done
            
            if [[ $repair_success -eq 0 ]]; then
              echo -e
              msg_info2 "$(translate "Re-running pre-check after repairs...")"
              sleep 2
              run_pve8to9_check
              return $?
            else
              echo -e
              msg_error "$(translate "Some repairs failed. Please fix manually and re-run the script.")"
            fi
            ;;
            2)
            echo -e
            echo -e "$(translate "${BFR}${CY}Manual Repair Commands:${CL}")"
            for i in "${!repair_commands[@]}"; do
              echo -e "${TAB}${BL}# ${repair_descriptions[$i]}${CL}"
              echo -e
              echo -e "${TAB}${repair_commands[$i]}"
              echo -e
            done
            echo -e
            msg_info2 "$(translate "Once finished, re-run the script 'PVE 8 to 9 check' to verify that all issues.")"
            echo -e
            msg_success "$(translate "Press Enter to exit the script after reading instructions...")"
            read -r
            rm -f "$tmp"
            exit 1
            ;;
        esac
      fi
      
      msg_success "$(translate "Press Enter to continue")"
      read -r
    fi
    
    echo -e
    msg_ok "$(translate "Checklist post-upgrade finished. Warnings:") $warns"
    echo -e
    msg_success "$(translate "Press Enter to continue")"
    read -r
    rm -f "$tmp"
    return $rc

}

show_proxmenux_logo
msg_title "$(translate "Run PVE 8 to 9 check")"
run_pve8to9_check2


