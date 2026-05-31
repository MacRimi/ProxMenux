#!/bin/bash
# ==========================================================
# ProxMenux - Fail2Ban Installer & Configurator
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.0
# ==========================================================
# Description:
# Installs and configures Fail2Ban to protect SSH, the Proxmox VE
# web UI (port 8006) and the ProxMenux Monitor (port 8008 + reverse
# proxy) against brute-force attacks. Hybrid runtime: works from
# terminal dialogs and from the ProxMenux web panel.
#
# Features:
#   - Adjusts journald MaxLevelStore if Proxmox default ('warning')
#     would silently drop SSH/PAM auth events.
#   - Creates two journal-to-file logger services so Fail2Ban can use
#     the reliable file backend instead of systemd journal (avoids
#     known issues with pvedaemon worker / sshd journal reads).
#   - Three jails: [sshd] (aggressive, 2 retries / 9h ban),
#     [proxmox] (8006, 3 retries / 1h ban), [proxmenux] (8008 +
#     http/https, 3 retries / 1h ban).
#   - Auto-detects firewall backend (nftables preferred, iptables
#     fallback) and sets the matching ban actions.
#   - SSH hardening: sets MaxAuthTries=3 (Lynis SSH-7408 recommendation),
#     backing up the original value for clean restore on uninstall.
#   - Reinstall flow rewrites all jails with current defaults.
#   - Clean uninstall: removes jails, logger services, journald drop-in
#     and restores the original SSH MaxAuthTries.
#   - Component status tracked in components_status.json.
# ==========================================================
# Hybrid script: works from terminal (dialog) and web panel (ScriptTerminalModal)

SCRIPT_TITLE="Fail2Ban Installer for Proxmox VE"

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
COMPONENTS_STATUS_FILE="$BASE_DIR/components_status.json"

export BASE_DIR
export COMPONENTS_STATUS_FILE

if [[ -f "$UTILS_FILE" ]]; then
  source "$UTILS_FILE"
fi

if [[ ! -f "$COMPONENTS_STATUS_FILE" ]]; then
  echo "{}" > "$COMPONENTS_STATUS_FILE"
fi

load_language
initialize_cache


# ==========================================================
# Detection
# ==========================================================
detect_fail2ban() {
  FAIL2BAN_INSTALLED=false
  FAIL2BAN_VERSION=""
  FAIL2BAN_ACTIVE=false

  if command -v fail2ban-client >/dev/null 2>&1; then
    FAIL2BAN_INSTALLED=true
    FAIL2BAN_VERSION=$(fail2ban-client --version 2>/dev/null | head -n1 | tr -d '[:space:]' || echo "unknown")

    if systemctl is-active --quiet fail2ban 2>/dev/null; then
      FAIL2BAN_ACTIVE=true
    fi
  fi
}


# ==========================================================
# Installation
# ==========================================================
install_fail2ban() {
  show_proxmenux_logo
  msg_title "$(translate "$SCRIPT_TITLE")"
  msg_info2 "$(translate "Installing and configuring Fail2Ban to protect Proxmox web interface and SSH...")"

  # Ensure Debian repositories are available
  local deb_codename
  deb_codename=$(grep -oP '^VERSION_CODENAME=\K.*' /etc/os-release 2>/dev/null)

  if ! grep -RqsE "debian.*(bookworm|trixie)" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
    msg_warn "$(translate "Debian repositories missing; creating default source file")"
    local src="/etc/apt/sources.list.d/debian.sources"
    cat > "$src" <<EOF
Types: deb
URIs: http://deb.debian.org/debian
Suites: ${deb_codename} ${deb_codename}-updates
Components: main contrib non-free non-free-firmware

Types: deb
URIs: http://security.debian.org/debian-security
Suites: ${deb_codename}-security
Components: main contrib non-free non-free-firmware
EOF
    msg_ok "$(translate "Debian repositories configured for ${deb_codename}")"
  fi

  # Install Fail2Ban
  msg_info "$(translate "Installing Fail2Ban...")"
  if ! DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1 || \
     ! DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban >/dev/null 2>&1; then
    msg_error "$(translate "Failed to install Fail2Ban")"
    return 1
  fi
  msg_ok "$(translate "Fail2Ban installed successfully")"

  # ── Ensure journald stores auth-level messages ──
  # Proxmox sets MaxLevelStore=warning by default, which silently drops
  # info/notice messages. SSH auth failures (PAM) are logged at info/notice,
  # so Fail2Ban with backend=systemd will never see them.
  local journald_conf="/etc/systemd/journald.conf"
  local journald_changed=false

  if [[ -f "$journald_conf" ]]; then
    local current_max
    current_max=$(grep -i '^MaxLevelStore=' "$journald_conf" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

    # Levels that are too restrictive for auth logging (need at least info)
    case "$current_max" in
      emerg|alert|crit|err|warning)
        msg_warn "$(translate "journald MaxLevelStore is '${current_max}' - SSH auth failures are not being stored")"
        msg_info "$(translate "Updating journald to store info-level messages...")"

        # Create a drop-in so we don't break other Proxmox settings
        mkdir -p /etc/systemd/journald.conf.d
        cat > /etc/systemd/journald.conf.d/proxmenux-loglevel.conf <<'JEOF'
# ProxMenux: Allow auth/info messages so Fail2Ban can detect SSH failures
# Proxmox default MaxLevelStore=warning drops PAM/SSH auth events
[Journal]
MaxLevelStore=info
MaxLevelSyslog=info
JEOF
        journald_changed=true
        msg_ok "$(translate "journald drop-in created: /etc/systemd/journald.conf.d/proxmenux-loglevel.conf")"
        ;;
      *)
        msg_ok "$(translate "journald MaxLevelStore is adequate for auth logging")"
        ;;
    esac

    if $journald_changed; then
      systemctl restart systemd-journald
      sleep 1
      msg_ok "$(translate "journald restarted - auth messages will now be stored")"
    fi
  fi

  # ── Journal-to-file logger services for Fail2Ban ──
  # Fail2Ban's systemd backend has a known issue: it cannot reliably read
  # journal entries in real-time from certain services (pvedaemon workers,
  # and intermittently sshd). The solution is to create small systemd services
  # that tail the journal and write to log files, then fail2ban monitors those
  # files with the reliable backend=auto.

  # -- Proxmox UI auth logger (pvedaemon) --
  msg_info "$(translate "Creating Proxmox auth logger service...")"
  cat > /etc/systemd/system/proxmox-auth-logger.service <<'EOF'
[Unit]
Description=Proxmox Auth Logger for Fail2Ban
Documentation=https://github.com/MacRimi/ProxMenux
After=pvedaemon.service
PartOf=fail2ban.service

[Service]
Type=simple
ExecStart=/bin/bash -c 'journalctl -f _SYSTEMD_UNIT=pvedaemon.service -o short-iso --no-pager >> /var/log/proxmox-auth.log'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  touch /var/log/proxmox-auth.log
  chmod 640 /var/log/proxmox-auth.log
  chown root:adm /var/log/proxmox-auth.log 2>/dev/null || true

  systemctl daemon-reload
  systemctl enable --now proxmox-auth-logger.service >/dev/null 2>&1
  msg_ok "$(translate "Proxmox auth logger service created and started")"

  # -- SSH auth logger --
  msg_info "$(translate "Creating SSH auth logger service...")"
  cat > /etc/systemd/system/ssh-auth-logger.service <<'EOF'
[Unit]
Description=SSH Auth Logger for Fail2Ban
Documentation=https://github.com/MacRimi/ProxMenux
After=ssh.service
PartOf=fail2ban.service

[Service]
Type=simple
ExecStart=/bin/bash -c 'journalctl -f _SYSTEMD_UNIT=ssh.service -o short-iso --no-pager >> /var/log/ssh-auth.log'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  touch /var/log/ssh-auth.log
  chmod 640 /var/log/ssh-auth.log
  chown root:adm /var/log/ssh-auth.log 2>/dev/null || true

  systemctl daemon-reload
  systemctl enable --now ssh-auth-logger.service >/dev/null 2>&1
  msg_ok "$(translate "SSH auth logger service created and started")"

  # Configure Proxmox filter
  mkdir -p /etc/fail2ban/filter.d /etc/fail2ban/jail.d
  msg_info "$(translate "Configuring Proxmox filter...")"
  cat > /etc/fail2ban/filter.d/proxmox.conf <<'EOF'
[Definition]
# The proxmox-auth-logger service writes journal lines to /var/log/proxmox-auth.log
# in short-iso format: 2026-02-10T19:36:08+01:00 host pvedaemon[PID]: message
# Proxmox logs IPs as ::ffff:x.x.x.x (IPv4-mapped IPv6).
failregex = authentication (failure|error); rhost=(::ffff:)?<HOST> user=.* msg=.*
ignoreregex =
datepattern = ^%%Y-%%m-%%dT%%H:%%M:%%S
EOF
  msg_ok "$(translate "Proxmox filter configured")"

  # Configure Proxmox jail (file-based backend)
  msg_info "$(translate "Configuring Proxmox jail...")"
  cat > /etc/fail2ban/jail.d/proxmox.conf <<'EOF'
[proxmox]
enabled = true
port = 8006
filter = proxmox
backend = auto
logpath = /var/log/proxmox-auth.log
maxretry = 3
bantime = 3600
findtime = 600
EOF
  msg_ok "$(translate "Proxmox jail configured")"

  # Configure ProxMenux Monitor filter
  # This reads from a file written directly by the Flask app (not syslog/journal),
  # so it uses a datepattern that matches Python's logging format.
  msg_info "$(translate "Configuring ProxMenux Monitor filter...")"
  cat > /etc/fail2ban/filter.d/proxmenux.conf <<'EOF'
[Definition]
failregex = ^.*proxmenux-auth: authentication failure; rhost=<HOST> user=.*$
ignoreregex =
datepattern = ^%%Y-%%m-%%d %%H:%%M:%%S
EOF
  msg_ok "$(translate "ProxMenux Monitor filter configured")"

  # Configure ProxMenux Monitor jail (port 8008 + http/https for reverse proxy)
  # Uses backend=auto with logpath because the Flask app writes directly to this file.
  msg_info "$(translate "Configuring ProxMenux Monitor jail...")"
  cat > /etc/fail2ban/jail.d/proxmenux.conf <<'EOF'
[proxmenux]
enabled = true
port = 8008,http,https
filter = proxmenux
backend = auto
logpath = /var/log/proxmenux-auth.log
maxretry = 3
bantime = 3600
findtime = 600
EOF
  msg_ok "$(translate "ProxMenux Monitor jail configured")"

  # Ensure ProxMenux auth log exists (Flask writes here directly)
  touch /var/log/proxmenux-auth.log
  chmod 640 /var/log/proxmenux-auth.log 2>/dev/null || true

  # Detect firewall backend (nftables preferred, fallback to iptables)
  local ban_action="iptables-multiport"
  local ban_action_all="iptables-allports"
  if command -v nft >/dev/null 2>&1 && nft list ruleset >/dev/null 2>&1; then
    ban_action="nftables"
    ban_action_all="nftables[type=allports]"
    msg_ok "$(translate "Detected nftables - using nftables ban action")"
  else
    msg_info "$(translate "nftables not available - using iptables ban action")"
  fi

  # Configure global settings and SSH jail
  msg_info "$(translate "Configuring global Fail2Ban settings and SSH jail...")"
  cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1
ignoreself = true
bantime = 86400
maxretry = 2
findtime = 1800
backend = auto
banaction = ${ban_action}
banaction_allports = ${ban_action_all}

[sshd]
enabled = true
filter = sshd[mode=aggressive]
backend = auto
logpath = /var/log/ssh-auth.log
maxretry = 2
findtime = 3600
bantime = 32400
EOF
  msg_ok "$(translate "Global settings and SSH jail configured")"

  # ── SSH Hardening: MaxAuthTries ──
  # Lynis (SSH-7408) recommends MaxAuthTries=3. With fail2ban maxretry=2,
  # SSH will never reach 3 attempts, but setting it satisfies the audit
  # and adds defense-in-depth. Backup original value for clean restore.
  local sshd_config="/etc/ssh/sshd_config"
  if [[ -f "$sshd_config" ]]; then
    # Save original MaxAuthTries value for restore on uninstall
    local original_max_auth
    original_max_auth=$(grep -i '^MaxAuthTries' "$sshd_config" 2>/dev/null | awk '{print $2}' || echo "6")
    if [[ -z "$original_max_auth" ]]; then
      original_max_auth="6"
    fi

    # Store original value in our config directory
    echo "$original_max_auth" > "${BASE_DIR}/sshd_maxauthtries_backup"

    msg_info "$(translate "Hardening SSH: setting MaxAuthTries to 3...")"
    if grep -qi '^MaxAuthTries' "$sshd_config"; then
      sed -i 's/^MaxAuthTries.*/MaxAuthTries 3/' "$sshd_config"
    elif grep -qi '^#MaxAuthTries' "$sshd_config"; then
      sed -i 's/^#MaxAuthTries.*/MaxAuthTries 3/' "$sshd_config"
    else
      echo "MaxAuthTries 3" >> "$sshd_config"
    fi

    # Reload SSH to apply the change (reload, not restart, to keep existing sessions)
    systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
    msg_ok "$(translate "SSH MaxAuthTries set to 3 (original: ${original_max_auth})")"
  fi

  # Enable and restart the service (restart ensures new jails are loaded
  # even if fail2ban was already running from a previous install)
  systemctl daemon-reload
  systemctl enable fail2ban >/dev/null 2>&1
  systemctl restart fail2ban >/dev/null 2>&1
  sleep 3

  # Verify
  if systemctl is-active --quiet fail2ban; then
    msg_ok "$(translate "Fail2Ban is running correctly")"
  else
    msg_error "$(translate "Fail2Ban is NOT running!")"
    journalctl -u fail2ban --no-pager -n 10
  fi

  if fail2ban-client ping >/dev/null 2>&1; then
    msg_ok "$(translate "fail2ban-client successfully communicated with the server")"
  else
    msg_error "$(translate "fail2ban-client could not communicate with the server")"
  fi

  update_component_status "fail2ban" "installed" "$(fail2ban-client --version 2>/dev/null | head -n1)" "security" '{}'

  msg_success "$(translate "Fail2Ban installation and configuration completed successfully!")"
}


# ==========================================================
# Uninstall
# ==========================================================
uninstall_fail2ban() {
  show_proxmenux_logo
  msg_title "$(translate "$SCRIPT_TITLE")"
  msg_info2 "$(translate "Removing Fail2Ban...")"

  systemctl stop fail2ban 2>/dev/null || true
  systemctl disable fail2ban 2>/dev/null || true

  # Stop and remove the auth logger services
  systemctl stop proxmox-auth-logger.service 2>/dev/null || true
  systemctl disable proxmox-auth-logger.service 2>/dev/null || true
  rm -f /etc/systemd/system/proxmox-auth-logger.service
  systemctl stop ssh-auth-logger.service 2>/dev/null || true
  systemctl disable ssh-auth-logger.service 2>/dev/null || true
  rm -f /etc/systemd/system/ssh-auth-logger.service
  systemctl daemon-reload 2>/dev/null || true
  rm -f /var/log/proxmox-auth.log /var/log/ssh-auth.log
  
  DEBIAN_FRONTEND=noninteractive apt-get purge -y fail2ban >/dev/null 2>&1
  rm -f /etc/fail2ban/jail.d/proxmox.conf
  rm -f /etc/fail2ban/jail.d/proxmenux.conf
  rm -f /etc/fail2ban/filter.d/proxmox.conf
  rm -f /etc/fail2ban/filter.d/proxmenux.conf
  rm -f /etc/fail2ban/jail.local

  # ── Restore SSH MaxAuthTries to original value ──
  local sshd_config="/etc/ssh/sshd_config"
  local backup_file="${BASE_DIR}/sshd_maxauthtries_backup"
  if [[ -f "$backup_file" && -f "$sshd_config" ]]; then
    local original_val
    original_val=$(cat "$backup_file" 2>/dev/null | tr -d '[:space:]')
    if [[ -n "$original_val" ]]; then
      msg_info "$(translate "Restoring SSH MaxAuthTries to ${original_val}...")"
      if grep -qi '^MaxAuthTries' "$sshd_config"; then
        sed -i "s/^MaxAuthTries.*/MaxAuthTries ${original_val}/" "$sshd_config"
      fi
      systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
      msg_ok "$(translate "SSH MaxAuthTries restored to ${original_val}")"
    fi
    rm -f "$backup_file"
  fi

  # Remove journald drop-in and restore original log level
  if [[ -f /etc/systemd/journald.conf.d/proxmenux-loglevel.conf ]]; then
    rm -f /etc/systemd/journald.conf.d/proxmenux-loglevel.conf
    systemctl restart systemd-journald 2>/dev/null || true
    msg_ok "$(translate "journald log level restored")"
  fi

  update_component_status "fail2ban" "removed" "" "security" '{}'

  msg_ok "$(translate "Fail2Ban has been removed")"
  msg_success "$(translate "Uninstallation completed. Press Enter to continue...")"
  read -r
}


# ==========================================================
# Main
# ==========================================================
main() {
  detect_fail2ban

  if $FAIL2BAN_INSTALLED; then
    # Already installed - show action menu
    local action_text
    action_text="\n$(translate 'Fail2Ban is currently installed.')\n"
    action_text+="$(translate 'Version:') $FAIL2BAN_VERSION\n"
    action_text+="$(translate 'Status:') $(if $FAIL2BAN_ACTIVE; then translate 'Active'; else translate 'Inactive'; fi)\n\n"
    action_text+="$(translate 'What would you like to do?')"

    local ACTION
    ACTION=$(hybrid_menu "$(translate 'Fail2Ban Management')" "$action_text" 18 70 3 \
      "reinstall" "$(translate 'Reinstall and reconfigure Fail2Ban')" \
      "remove" "$(translate 'Uninstall Fail2Ban')" \
      "cancel" "$(translate 'Cancel')" \
    ) || ACTION="cancel"

    case "$ACTION" in
      reinstall)
        if hybrid_yesno "$(translate 'Reinstall Fail2Ban')" \
          "\n\n$(translate 'This will reinstall and reconfigure Fail2Ban with the default ProxMenux settings. Continue?')" 12 70; then
          install_fail2ban
        fi
        ;;
      remove)
        if hybrid_yesno "$(translate 'Remove Fail2Ban')" \
          "\n\n$(translate 'This will completely remove Fail2Ban and its configuration. Continue?')" 12 70; then
          uninstall_fail2ban
        fi
        ;;
      cancel|*)
        exit 0
        ;;
    esac
  else
    # Not installed - confirm and install
    local info_text
    info_text="\n$(translate 'Fail2Ban is not installed on this system.')\n\n"
    info_text+="$(translate 'This will install and configure Fail2Ban with:')\n\n"
    info_text+="  - $(translate 'SSH protection (aggressive mode)') (max 2 $(translate 'retries'), 9h $(translate 'ban'))\n"
    info_text+="  - $(translate 'Proxmox web interface protection') ($(translate 'port') 8006, max 3 $(translate 'retries'), 1h $(translate 'ban'))\n"
    info_text+="  - $(translate 'ProxMenux Monitor protection') ($(translate 'port') 8008 + $(translate 'reverse proxy'), max 3 $(translate 'retries'), 1h $(translate 'ban'))\n"
    info_text+="  - $(translate 'Auto-detected firewall backend (nftables/iptables)')\n"
    info_text+="  - $(translate 'Adjusts journald log level if needed (Proxmox defaults may block auth logs)')\n"
    info_text+="  - $(translate 'SSH hardening: MaxAuthTries set to 3 (Lynis recommendation)')\n\n"
    info_text+="$(translate 'Do you want to proceed?')"

    if hybrid_yesno "$(translate 'Install Fail2Ban')" "$info_text" 20 70; then
      install_fail2ban
    else
      exit 0
    fi
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi
