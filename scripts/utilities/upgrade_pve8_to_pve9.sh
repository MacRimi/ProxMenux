#!/bin/bash
# ==========================================================
# ProxMenuX - Upgrade PVE 8 → 9 (Simplified, per official guide)
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 14/08/2025
# ==========================================================

REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
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


REPO_MODE="no-subscription"   
DISABLE_AUDIT="1"
ASSUME_YES="0"                
CEPH_ENFORCE="auto"          


for arg in "$@"; do
  case "$arg" in
    --enterprise) REPO_MODE="enterprise" ;;
    --no-subscription) REPO_MODE="no-subscription" ;;
    --skip-audit-disable) DISABLE_AUDIT="0" ;;
    --assume-yes|-y) ASSUME_YES="1" ;;
    --ignore-ceph-check) CEPH_ENFORCE="skip" ;;
    --warn-ceph-check) CEPH_ENFORCE="warn" ;;
    *) ;;
  esac
done

# ==========================================================


run_manual_guide() {
    local url="$REPO_URL/scripts/utilities/proxmox-upgrade-pve8-to-pve9-manual-guide.sh"
    if command -v curl >/dev/null 2>&1; then
        bash <(curl -fsSL "$url")
    else
        bash <(wget -qO- "$url")
    fi
}

ask_run_mode() {

    if [[ "${ASSUME_YES:-0}" == "1" ]]; then
        msg_ok "$(translate "Run mode: Unattended")"
        export DEBIAN_FRONTEND=noninteractive
        export APT_LISTCHANGES_FRONTEND=none
        return 0
    fi


    while true; do
        if command -v dialog >/dev/null 2>&1; then
            local title text choice status
            title="$(translate "Select run mode")"; [[ -z "$title" ]] && title="Select run mode"
            text="$(translate "Choose how to perform the upgrade:")"; [[ -z "$text" ]] && text="Choose how to perform the upgrade:"
            title=${title//$'\r'/}; title=${title//$'\n'/' '}
            text=${text//$'\r'/};  text=${text//$'\n'/' '}

            choice=$(
                dialog --backtitle "ProxMenux" \
                       --title "$title" \
                       --menu "$text" 17 78 3 \
                       1 "$(translate "Automatic/Unattended")" \
                       2 "$(translate "Interactive (guided, prompts visible)")" \
                       3 "$(translate "Manual upgrade guide step by step")" \
                       3>&1 1>&2 2>&3
            ); status=$?


            if [[ $status -ne 0 ]]; then
                show_proxmenux_logo || true
                msg_warn "$(translate "Action canceled by user")"
                exit 0
            fi

            case "$choice" in
                1)
                    ASSUME_YES="1"
                    show_proxmenux_logo || true
                    msg_title "$(translate "Upgrade assistant: Proxmox VE 8 → 9 (Trixie)")"
                    msg_info2 "$(translate "Run mode selected: Unattended")"
                    export DEBIAN_FRONTEND=noninteractive
                    export APT_LISTCHANGES_FRONTEND=none
                    break   
                    ;;
                3)
                    run_manual_guide
                    continue  
                    ;;
                *)
                    show_proxmenux_logo || true
                    msg_title "$(translate "Upgrade assistant: Proxmox VE 8 → 9 (Trixie)")"
                    msg_info2 "$(translate "Run mode selected: Interactive")"
                    break   
                    ;;
            esac

        elif command -v whiptail >/dev/null 2>&1; then
            local choice
            if ! choice=$(
                whiptail --title "$(translate "Select run mode")" \
                         --menu "$(translate "Choose how to perform the upgrade:")" 17 78 3 \
                         "1" "$(translate "Automatic/Unattended")" \
                         "2" "$(translate "Interactive (guided, prompts visible)")" \
                         "3" "$(translate "Manual upgrade guide step by step")" \
                         3>&1 1>&2 2>&3
            ); then
                show_proxmenux_logo || true
                msg_warn "$(translate "Action canceled by user")"
                exit 0
            fi

            case "$choice" in
                1)
                    ASSUME_YES="1"
                    show_proxmenux_logo || true
                    msg_title "$(translate "Upgrade assistant: Proxmox VE 8 → 9 (Trixie)")"
                    msg_info2 "$(translate "Run mode selected: Unattended")"
                    export DEBIAN_FRONTEND=noninteractive
                    export APT_LISTCHANGES_FRONTEND=none
                    break
                    ;;
                3)
                    run_manual_guide
                    continue
                    ;;
                *)
                    show_proxmenux_logo || true
                    msg_title "$(translate "Upgrade assistant: Proxmox VE 8 → 9 (Trixie)")"
                    msg_info2 "$(translate "Run mode selected: Interactive")"
                    break
                    ;;
            esac

        else
            printf "%s" "$(translate "Select run mode: [1]unattended / [2]interactive / [3]manual guide? (default: 2): ")"
            read -r ans
            case "$ans" in
                1)
                    ASSUME_YES="1"
                    show_proxmenux_logo || true
                    msg_title "$(translate "Upgrade assistant: Proxmox VE 8 → 9 (Trixie)")"
                    msg_info2 "$(translate "Run mode selected: Unattended")"
                    export DEBIAN_FRONTEND=noninteractive
                    export APT_LISTCHANGES_FRONTEND=none
                    break
                    ;;
                3)
                    run_manual_guide
                    continue
                    ;;
                *)
                    show_proxmenux_logo || true
                    msg_title "$(translate "Upgrade assistant: Proxmox VE 8 → 9 (Trixie)")"
                    msg_info2 "$(translate "Run mode selected: Interactive")"
                    break
                    ;;
            esac
        fi
    done

}




# ==========================================================


confirm() {
  local prompt="$1"
  if [[ "$ASSUME_YES" == "1" ]]; then
    return 0
  fi
  if command -v whiptail >/dev/null 2>&1; then
    whiptail --title "$(translate "Confirmation")" --yesno "$prompt" 14 80
  else
    echo -n "$(translate "$prompt") [y/N]: "
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]]
  fi
}

ask_choice_auto_or_manual() {
  if [[ "$ASSUME_YES" == "1" ]]; then
    echo "auto"; return 0
  fi
  if command -v whiptail >/dev/null 2>&1; then
    if whiptail --title "$(translate "Cluster upgrade mode")" --yesno "$(translate "Pending upgrades detected on a clustered node.\n\nTo proceed safely, update this node to the latest Proxmox VE 8.x before switching to Trixie/PVE 9.\n\nSelect Yes for AUTOMATIC upgrade (recommended), or No for MANUAL instructions.")" 16 78; then
      echo "auto"
    else
      echo "manual"
    fi
  else
    echo -n "$(translate "Pending upgrades detected on a clustered node. Perform AUTOMATIC upgrade now? (y = automatic, n = manual): ")"
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]] && echo "auto" || echo "manual"
  fi
}



run_step() {

  local pre="$1"; local ok="$2"; local cmd="$3"
  echo -ne "${TAB}${YW}$(translate "$pre")${CL}"
  if bash -lc "set -o pipefail; $cmd 2>&1 | tee -a \"$LOG\""; then
    echo -e "${BFR}${TAB}${CM}${GN}$(translate "$ok")${CL}"
    return 0
  else
    echo -e "${BFR}${TAB}${RD}[ERROR] $(translate "Failed. See log:") $LOG${CL}"
    exit 1
  fi
}

run_step_interactive() {

  local pre="$1"; local ok="$2"; shift 2
  echo -ne "${TAB}${YW}$(translate "$pre")${CL}"
  if "$@"; then
    echo -e "${BFR}${TAB}${CM}${GN}$(translate "$ok")${CL}"
    return 0
  else
    echo -e "${BFR}${TAB}${RD}[ERROR] $(translate "Failed. See log:") $LOG${CL}"
    exit 1
  fi
}

append_step() {

  local pre="$1"; local ok="$2"; local cmd="$3"
  echo -ne "${TAB}${YW}$(translate "$pre")${CL}"
  if bash -lc "set -o pipefail; $cmd 2>&1 | tee -a \"$LOG\""; then
    echo -e "${BFR}${TAB}${CM}${GN}$(translate "$ok")${CL}"
  else
    echo -e "${BFR}${TAB}${CM}${GN}$(translate "$ok")${CL}"
  fi
}

file_contains() {
  local file="$1"
  local pattern="$2"
  grep -qE "$pattern" "$file" 2>/dev/null
}

is_cluster_node() {
  if command -v pvecm >/dev/null 2>&1 && pvecm status >> "$LOG" 2>&1; then
    return 0
  fi
  return 1
}

is_hyperconverged_ceph_node() {
  if command -v pveceph >/dev/null 2>&1; then
    if pveceph status >> "$LOG" 2>&1; then
      return 0
    fi
  fi
  if systemctl list-units --type=service --all 2>/dev/null | grep -Eq 'ceph-(mon|osd|mgr)@'; then
    return 0
  fi
  if ls /var/lib/ceph/osd/ceph-* >/dev/null 2>&1; then
    return 0
  fi
  if [[ -f /etc/pve/ceph.conf ]]; then
    return 0
  fi
  return 1
}


# ==========================================================


create_pve_repo_enterprise_if_missing() {
  local f="/etc/apt/sources.list.d/pve-enterprise.sources"
  [[ -f "$f" ]] && return 0
  cat > "$f" << 'EOF'
Types: deb
URIs: https://enterprise.proxmox.com/debian/pve
Suites: trixie
Components: pve-enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
  chmod 644 "$f"
}

create_pve_repo_nosub_if_missing() {
  local f="/etc/apt/sources.list.d/proxmox.sources"
  [[ -f "$f" ]] && return 0
  cat > "$f" << 'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
  chmod 644 "$f"
}

create_ceph_repo_enterprise_if_missing() {
  local f="/etc/apt/sources.list.d/ceph.sources"
  [[ -f "$f" ]] && return 0
  cat > "$f" << 'EOF'
Types: deb
URIs: https://enterprise.proxmox.com/debian/ceph-squid
Suites: trixie
Components: enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
  chmod 644 "$f"
}

create_ceph_repo_nosub_if_missing() {
  local f="/etc/apt/sources.list.d/ceph.sources"
  [[ -f "$f" ]] && return 0
  cat > "$f" << 'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/ceph-squid
Suites: trixie
Components: no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
  chmod 644 "$f"
}

disable_enterprise_repo_if_present() {
  local s="/etc/apt/sources.list.d/pve-enterprise.sources"
  local l="/etc/apt/sources.list.d/pve-enterprise.list"
  if [[ -f "$s" ]]; then
    if grep -qi '^Enabled:' "$s"; then
      sed -i 's/^Enabled:.*/Enabled: false/i' "$s"
    else
      echo "Enabled: false" >> "$s"
    fi
  fi
  if [[ -f "$l" ]]; then
    sed -i 's/^[[:space:]]*deb/# deb/' "$l"
  fi
}

comment_legacy_pve8_lists() {
  for f in /etc/apt/sources.list.d/pve-public-repo.list /etc/apt/sources.list.d/pve-install-repo.list; do
    [[ -f "$f" ]] || continue
    sed -i 's/^[[:space:]]*deb/# deb/' "$f" || true
  done
}

comment_legacy_ceph_list() {
  local f="/etc/apt/sources.list.d/ceph.list"
  [[ -f "$f" ]] || return 0
  sed -i 's/^[[:space:]]*deb/# deb/' "$f" || true
}

apt_update_with_repo_fallback() {

  local output status
  output="$(apt-get update >/dev/null 2>&1 | tee -a "$LOG")"; status=${PIPESTATUS[0]}
  if [[ $status -eq 0 ]]; then
    msg_ok2 "$(translate "APT indexes updated for Trixie")"
    return 0
  fi
  if [[ "$REPO_MODE" == "enterprise" ]] && { echo "$output" | grep -qE '401[[:space:]]+Unauthorized' || echo "$output" | grep -qi 'enterprise\.proxmox\.com'; }; then
    if [[ "$ASSUME_YES" == "1" ]] || confirm "$(translate "Enterprise repository returned 401 Unauthorized (no valid subscription). Switch to the no-subscription repository and retry?")"; then

      disable_enterprise_repo_if_present
      create_pve_repo_nosub_if_missing
      if [[ -f /etc/apt/sources.list.d/ceph.sources ]]; then
        create_ceph_repo_nosub_if_missing
      fi
      REPO_MODE="no-subscription"
      msg_ok2 "$(translate "Repositories switched to no-subscription")"

      if apt-get update >> "$LOG" >/dev/null 2>&1; then
        msg_ok2 "$(translate "APT indexes updated for Trixie (no-subscription)")"
        return 0
      else
        echo -e "${BFR}${TAB}${RD}[ERROR] $(translate "APT index update failed after switching to no-subscription. See log:") $LOG${CL}"
        exit 1
      fi
    else
      echo -e "${BFR}${TAB}${RD}[ERROR] $(translate "Enterprise repository unauthorized and fallback declined by user") $LOG${CL}"
      exit 1
    fi
  fi
  echo -e "${BFR}${TAB}${RD}[ERROR] $(translate "APT index update failed. See log:") $LOG${CL}"
  exit 1
}

# ==========================================================

proxmox_repo_candidate_ok() {
  local cand
  cand="$(apt-cache policy proxmox-ve 2>/dev/null | awk -F': ' '/Candidate:/{print $2}')"
  [[ -n "$cand" && "$cand" != "(none)" && "$cand" =~ ^9 ]]
}


simulate_would_remove_proxmox_ve() {
  apt-get -s dist-upgrade >/dev/null 2>&1 | grep -Eq 'Remv[[:space:]]+proxmox-ve|The following packages will be REMOVED:.*proxmox-ve'
}


guard_against_proxmox_ve_removal() {
  msg_info "$(translate "Validating Proxmox 9 repositories (checking 'proxmox-ve' candidate)...")"
  if proxmox_repo_candidate_ok; then
    msg_ok "$(translate "Proxmox repository OK (candidate is 9.x)")"
  else
    if [[ "$REPO_MODE" == "enterprise" ]]; then
      msg_warn "$(translate "Proxmox enterprise repo might be missing or inaccessible. Trying to switch to no-subscription...")"
      disable_enterprise_repo_if_present
      create_pve_repo_nosub_if_missing
      REPO_MODE="no-subscription"
      apt_update_with_repo_fallback
      if proxmox_repo_candidate_ok; then
        msg_ok "$(translate "Proxmox repository fixed (no-subscription, candidate is 9.x)")"
      else
        msg_error "$(translate "Could not find a valid 'proxmox-ve' 9.x candidate after switching to no-subscription. Please verify your repository configuration and network, then retry.")"
        exit 1
      fi
    else
      msg_error "$(translate "Invalid 'proxmox-ve' candidate (not 9.x or none). Please verify your repository configuration and network, then retry.")"
      exit 1
    fi
  fi
  msg_info "$(translate "Running pre-upgrade simulation to verify 'proxmox-ve' will remain installed...")"
  if simulate_would_remove_proxmox_ve; then
    msg_error "$(translate "Pre-upgrade check FAILED: the simulation shows that 'proxmox-ve' would be REMOVED.\n    This indicates a repository or dependency issue and upgrading now could break your Proxmox installation.")"
    echo "---- $(translate "Recommended diagnostic commands") ----"
    echo "apt-cache policy proxmox-ve"
    echo "apt policy | sed -n '1,120p'"
    echo "cat /etc/apt/sources.list"
    echo "ls -l /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources"
    exit 1
  else
    msg_ok "$(translate "Pre-upgrade simulation passed: 'proxmox-ve' will be kept or upgraded safely.")"
  fi

}


# ==========================================================


check_not_web_terminal() {
    [[ "${PVE_ALLOW_WEBTERM:-0}" = "1" ]] && return 0

    [[ -n "${SSH_CONNECTION:-}" ]] && return 0

    local pid ppid comm args i
    pid=$$

    show_web_terminal_block_msg() {
    local title msg_line1 msg_line2 msg

    title="$(translate "Unsupported Terminal")"
    msg_line1="$(translate "This script cannot be executed from the Proxmox web terminal.")"
    msg_line2="$(translate "Please use an SSH session (Linux, macOS, Windows/PuTTY) or a physical console to perform the upgrade.")"

    msg="${msg_line1}"$'\n\n'"${msg_line2}"

    whiptail --title "$title" --msgbox "$msg" 12 72
}

    for i in {1..12}; do
        ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
        [[ -z "$ppid" || "$ppid" -le 1 ]] && break

        comm=$(ps -o comm= -p "$ppid" 2>/dev/null || true)
        args=$(ps -o args= -p "$ppid" 2>/dev/null || true)

        if echo "$comm $args" | grep -Eqi 'termproxy|vncshell'; then
            show_web_terminal_block_msg
            msg_warn "$(translate "Upgrade canceled by user")"
            exit 1
        fi

        pid="$ppid"
    done
}

ask_run_mode

check_not_web_terminal



export NCURSES_NO_UTF8_ACS=1

show_upgrade_confirm() {

  local title
  title="$(translate "Upgrade to Proxmox VE 9")"

  local intro req l1 l2 l3 l4 cont
  intro="$(translate "This will upgrade this node to Proxmox VE 9 on Debian Trixie.")"
  req="$(translate "REQUIREMENTS:")"
  l1="$(translate "Valid backups for all VMs/CTs")"
  l2="$(translate "Run from console, or SSH inside tmux/screen")"
  l3="$(translate "Migrate away any guests that must keep running")"
  l4=""  
  cont="$(translate "Continue?")"


  local bullet="•"
  if ! locale charmap 2>/dev/null | grep -qi 'utf-8'; then
    bullet="-"
  fi

  local msg
  msg="${intro}"$'\n\n'"${req}"$'\n'
  msg+="${bullet} ${l1}"$'\n'
  msg+="${bullet} ${l2}"$'\n'
  msg+="${bullet} ${l3}"

  [[ -n "$l4" ]] && msg+=$'\n'"${bullet} ${l4}"
  msg+=$'\n\n'"${cont}"

  local cols width height
  cols=$(tput cols 2>/dev/null || echo 80)
  width=$(( cols < 78 ? (cols>40?cols-2:40) : 78 ))
  height=18

  if whiptail --title "$title" --yesno "$msg" "$height" "$width"; then
    return 0
  else
    msg_warn "$(translate "Upgrade canceled by user")"
    exit 0
  fi
}

show_upgrade_confirm




# ---------------------------
# Step 1
# ---------------------------


apt_upgrade() {
    local pve_version
    pve_version=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+' | head -1)

    if [[ -z "$pve_version" ]]; then
        msg_error "Unable to detect Proxmox version."
        return 1
    fi

    if [[ "$pve_version" -ge 9 ]]; then
        msg_info2 "$(translate "Proxmox 9 system update allready")"
        msg_success "$(translate "Press Enter to return to menu...")"
        read -r
        exit 1

    else
        bash <(curl -fsSL "$REPO_URL/scripts/global/update-pve8.sh")
        hash -r

    fi
}

apt_upgrade

# ---------------------------

regenerate_pve_cache() {
  msg_info "$(translate "Regenerating PVE package cache...")"
  
  mkdir -p /var/lib/pve-manager
  chmod 755 /var/lib/pve-manager
  
  systemctl restart pve-manager 2>/dev/null || true
  
  sleep 2
  
  timeout 10 pvesh get /nodes/localhost/apt/update 2>/dev/null || true
  
  msg_ok "$(translate "PVE cache regenerated")"
}

regenerate_pve_cache

# ---------------------------

run_pve8to9_check() {
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
      
      # Error 2: Kernel version mismatch
      if grep -q -E '(kernel.*mismatch|kernel.*version)' "$tmp"; then
        repair_commands+=("update-grub")
        repair_descriptions+=("$(translate "Update kernel to compatible version")")
        echo -e "${YW}$(translate "Fix kernel version:") ${CL}update-grub"
      fi
      
      # Error 3: Ceph version incompatible
      if grep -q -E '(ceph.*version|ceph.*incompatible)' "$tmp"; then
        repair_commands+=("ceph versions && pveceph upgrade")
        repair_descriptions+=("$(translate "Upgrade Ceph to compatible version")")
        echo -e "${YW}$(translate "Fix Ceph version:") ${CL}ceph versions && pveceph upgrade"
      fi
      
      # Error 4: Repository configuration issues
      if grep -q -E '(repository.*issue|repo.*problem|sources.*error)' "$tmp"; then
        repair_commands+=("cleanup_duplicate_repos && configure_repositories")
        repair_descriptions+=("$(translate "Fix repository configuration")")
        echo -e "${YW}$(translate "Fix repositories:") ${CL}cleanup_duplicate_repos && configure_repositories"
      fi
      
      # Error 5: Package conflicts
      if grep -q -E '(package.*conflict|dependency.*problem)' "$tmp"; then
        repair_commands+=("apt update && apt autoremove -y && apt autoclean")
        repair_descriptions+=("$(translate "Resolve package conflicts")")
        echo -e "${YW}$(translate "Fix package conflicts:") ${CL}apt update && apt autoremove -y && apt autoclean"
      fi
      
      # Error 6: Disk space issues
      if grep -q -E '(disk.*space|storage.*full|no.*space)' "$tmp"; then
        repair_commands+=("apt clean && apt autoremove -y && journalctl --vacuum-time=7d")
        repair_descriptions+=("$(translate "Free up disk space")")
        echo -e "${YW}$(translate "Fix disk space:") ${CL}apt clean && apt autoremove -y && journalctl --vacuum-time=7d"
      fi
      
      # Error 7: Network/DNS issues
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
        echo -e "${TAB}${GN}3.${CL} $(translate "Exit and repair manually")"
        echo -e
        echo -n "$(translate "Select option [1-3] (default: 3): ")"
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
            msg_info2 "$(translate "Once finished, re-run 'PVE 8 to 9 check' to verify that all issues are resolved \n    before executing the PVE 8 → PVE 9 upgrade.")"
            echo -e
            msg_success "$(translate "Press Enter to exit the script after reading instructions...")"
            read -r
            rm -f "$tmp"
            exit 1
            ;;
          *)
            echo -e
            msg_info2 "$(translate "Exiting for manual repair...")"
            ;;
        esac
      fi
      
      msg_success "$(translate "Press Enter to exit and repair")"
      read -r
      rm -f "$tmp"
      exit 1
    fi
    
    echo -e
    msg_ok "$(translate "Checklist pre-check finished. Warnings:") $warns"
    rm -f "$tmp"
    return $rc

}

run_pve8to9_check





# ---------------------------
# Step 2
# ---------------------------

run_step \
  "" \
  "Connectivity to Proxmox repository OK" \
  "ping -c1 -W2 download.proxmox.com >/dev/null"


msg_info "$(translate "Checking free space in /var/cache/apt/archives...")"
FREE_MB=$(df /var/cache/apt/archives | awk 'NR==2 {print int($4/1024)}')
if [[ "${FREE_MB:-0}" -lt 1024 ]]; then
  msg_error "$(translate "Insufficient space:") ${FREE_MB}MB $(translate "(need ≥ 1024MB)")"
  exit 1
else
  msg_ok "$(translate "Free space OK:") ${FREE_MB}MB"
fi


if [[ "$DISABLE_AUDIT" == "1" ]]; then
  append_step \
    "" \
    "Audit socket disabled or not required" \
    "systemctl disable --now systemd-journald-audit.socket >/dev/null 2>&1 || true"
fi




# ---------------------------
# Step 3
# ---------------------------

if command -v ceph >/dev/null 2>&1; then
  if [[ "$CEPH_ENFORCE" == "skip" ]]; then
    msg_ok2 "$(translate "Ceph check skipped by user flag (--ignore-ceph-check)")"
  else
    if is_hyperconverged_ceph_node; then
      msg_info "$(translate "Ceph detected as hyper-converged on this node. Checking version (require 19.x Squid)...")"
      CEPH_V=$(ceph --version 2>/dev/null | head -1 || true)
      if echo "$CEPH_V" | grep -Eq 'ceph.*(version 19|squid)'; then
        msg_ok "$(translate "Ceph version OK:") $CEPH_V"
      else
        if [[ "$CEPH_ENFORCE" == "warn" ]]; then
          msg_warn "$(translate "Ceph is not 19.x (Squid). Proceeding due to --warn-ceph-check. Detected:") ${CEPH_V:-N/A}"
        else
          msg_error "$(translate "Ceph is not 19.x (Squid). Upgrade Ceph first. Detected:") ${CEPH_V:-N/A}"
          exit 1
        fi
      fi
    else
      CEPH_V=$(ceph --version 2>/dev/null | head -1 || true)
      echo -e "${BFR}${TAB}${CM}${GN}${CEPH_V:-N/A}${CL}"
    fi
  fi
fi




# ---------------------------
# Step 4
# ---------------------------

OS_FILE="/etc/apt/sources.list"
if [[ -f "$OS_FILE" ]]; then
  msg_info "$(translate "Updating Debian Bookworm → Trixie in sources.list...")"
  if sed -i 's/bookworm/trixie/g' "$OS_FILE"; then
    msg_ok "$(translate "sources.list updated to Trixie")"
  else
    msg_ok "$(translate "sources.list update skipped (no change)")"
  fi
else
  msg_ok "$(translate "No main sources.list present (skipped)")"
fi

PVE_ENT_LIST="/etc/apt/sources.list.d/pve-enterprise.list"
msg_info "$(translate "Updating pve-enterprise.list (if present) to Trixie...")"
if [[ -f "$PVE_ENT_LIST" ]]; then
  if sed -i 's/bookworm/trixie/g' "$PVE_ENT_LIST"; then
    msg_ok "$(translate "pve-enterprise.list updated to Trixie")"
  else
    msg_ok "$(translate "pve-enterprise.list update skipped (no change)")"
  fi
else
  msg_ok "$(translate "No pve-enterprise.list present (skipped)")"
fi


msg_info "$(translate "Commenting any residual Bookworm lines in *.list...")"
for f in /etc/apt/sources.list.d/*.list; do
  [[ -f "$f" ]] || continue
  sed -i '/bookworm/s/^/# /' "$f" || true
done
sed -i '/bookworm/s/^/# /' "$OS_FILE" 2>/dev/null || true
msg_ok "$(translate "Residual Bookworm entries commented where applicable")"




# ---------------------------
# Step 5
# ---------------------------

if [[ "$REPO_MODE" == "enterprise" ]]; then
  msg_info "$(translate "Ensuring pve-enterprise.sources (PVE 9, deb822) is present...")"
  create_pve_repo_enterprise_if_missing
  msg_ok "$(translate "Enterprise repository present")"
else
  msg_info "$(translate "Ensuring proxmox.sources (PVE 9, no-subscription, deb822) is present...")"
  create_pve_repo_nosub_if_missing
  msg_ok "$(translate "No-subscription repository present")"
fi


msg_info "$(translate "Commenting legacy PVE 8 repository .list files (if any)...")"
comment_legacy_pve8_lists
msg_ok "$(translate "Legacy PVE 8 .list files commented or not present")"




# ---------------------------
# Step 6
# ---------------------------

if command -v ceph >/dev/null 2>&1; then
  if [[ "$REPO_MODE" == "enterprise" ]]; then
    msg_info "$(translate "Ensuring ceph.sources (enterprise, Trixie) is present...")"
    create_ceph_repo_enterprise_if_missing
    msg_ok "$(translate "Ceph enterprise repository present")"
  else
    msg_info "$(translate "Ensuring ceph.sources (no-subscription, Trixie) is present...")"
    create_ceph_repo_nosub_if_missing
    msg_ok "$(translate "Ceph no-subscription repository present")"
  fi

  msg_info "$(translate "Commenting legacy ceph.list (if present)...")"
  comment_legacy_ceph_list
  msg_ok "$(translate "Legacy ceph.list commented or not present")"
fi




# ---------------------------
# Step 7
# ---------------------------

apt_update_with_repo_fallback

run_step \
  "" \
  "Repository verification completed (see log)" \
  "apt policy >/dev/null 2>&1"





# ---------------------------
# Step 8
# ---------------------------

guard_against_proxmox_ve_removal

disable_translation_post_upgrade() {
  translate() { echo "$1"; }
}
disable_translation_post_upgrade



# ==========================================================


# ---------------------------
# Step 9
# ---------------------------

if [[ "$ASSUME_YES" == "1" ]]; then
  run_step \
    "" \
    "System upgraded to Trixie/PVE 9" \
    "DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none apt-get -y -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold' dist-upgrade"
else
  run_step_interactive \
    "" \
    "System upgraded to Trixie/PVE 9" \
    bash -lc "apt-get dist-upgrade"
fi



# ==========================================================




# ---------------------------
# Step 10
# ---------------------------
if [[ -d /sys/firmware/efi ]]; then
  if [[ "$ASSUME_YES" == "1" ]]; then
    append_step \
      "Installing grub-efi-amd64" \
      "grub-efi-amd64 installed or already present" \
      "apt-get install -y grub-efi-amd64 >/dev/null 2>&1"
  else
    run_step \
      "Installing grub-efi-amd64" \
      "grub-efi-amd64 installed or already present" \
      "apt-get install grub-efi-amd64 >/dev/null 2>&1"
  fi
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
            msg_info2 "$(translate "Once finished, re-run the script 'PVE 8 to 9 check' to verify that all issues are resolved \n   before rebooting.")"
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
    rm -f "$tmp"
    return $rc

}

run_pve8to9_check2


# ---------------------------


echo
echo
echo
echo "════════════════════════════════════════════════════════════════"
echo "      UPGRADE TO PVE 9 COMPLETED (reboot required)            "
echo "════════════════════════════════════════════════════════════════"
echo
echo
echo

msg_success "Press Enter to continue..."
read -r

whiptail --title "Reboot Required" \
  --yesno "It is RECOMMENDED to reboot now to load the new kernel and services.\n\nReboot now?" \
  12 70

if [ $? -eq 0 ]; then
  echo -e
  msg_warn "Rebooting the system..."
  echo -e
  reboot
else
  msg_info2 "You can reboot later manually."
  echo -e
  msg_success "Press Enter to exit"
  read -r
fi

exit 0
