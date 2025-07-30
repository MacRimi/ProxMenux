#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : MIT (https://raw.githubusercontent.com/MacRimi/ProxMenux/main/LICENSE)
# Version     : 1.0
# Last Updated: 30/06/2025
# ==========================================================
# Description:
# This script provides an interactive system utilities installer with a 
# comprehensive dialog-based interface for Proxmox VE and Linux systems.
# It simplifies the installation and management of essential command-line 
# tools and utilities commonly used in server environments.
#
# The script offers both individual utility selection and predefined groups
# for different use cases, ensuring administrators can quickly set up their
# preferred toolset without manual package management.
#
# Supported utility categories:
# - Basic utilities: grc, htop, tree, curl, wget
# - Development tools: git, vim, nano, dos2unix
# - Compression tools: zip, unzip, rsync, cabextract
# - Network tools: iperf3, nmap, tcpdump, nethogs, iptraf-ng, sshpass
# - Analysis tools: jq, ncdu, iotop, btop, iftop
# - System tools: mlocate, net-tools, ipset, msr-tools
# - Virtualization tools: libguestfs-tools, wimtools, genisoimage, chntpw
# - Download tools: axel, aria2
#
# The script automatically handles package name differences across distributions
# and provides detailed feedback on installation success, warnings, and failures.
# It includes built-in troubleshooting for common PATH and command availability
# issues that may occur after package installation.
#
# Configuration ============================================

REPO_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/main"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi
load_language
initialize_cache

# ==========================================================



install_system_utils() {
    
    

    command_exists() {
        command -v "$1" >/dev/null 2>&1
    }
    

    install_single_package() {
        local package="$1"
        local command_name="${2:-$package}"
        local description="$3"
        
        msg_info "$(translate "Installing") $package ($description)..."
        

        local install_success=false
        
        if command_exists apt; then
            if apt update >/dev/null 2>&1 && apt install -y "$package" >/dev/null 2>&1; then
                install_success=true
            fi
        elif command_exists yum; then
            if yum install -y "$package" >/dev/null 2>&1; then
                install_success=true
            fi
        elif command_exists dnf; then
            if dnf install -y "$package" >/dev/null 2>&1; then
                install_success=true
            fi
        elif command_exists pacman; then
            if pacman -S --noconfirm "$package" >/dev/null 2>&1; then
                install_success=true
            fi
        elif command_exists zypper; then
            if zypper install -y "$package" >/dev/null 2>&1; then
                install_success=true
            fi
        else
            cleanup
            msg_error "$(translate "No compatible package manager detected")"
            return 1
        fi
        
        cleanup
        

        if [ "$install_success" = true ]; then

            hash -r 2>/dev/null
            sleep 1
            
            if command_exists "$command_name"; then
                msg_ok "$package $(translate "installed correctly and available")"
                return 0
            else
                msg_warn "$package $(translate "installed but command not immediately available")"
                msg_info2 "$(translate "May need to restart terminal")"
                return 2
            fi
        else
            msg_error "$(translate "Error installing") $package"
            return 1
        fi
    }
    

    show_main_utilities_menu() {
        local choice
        choice=$(dialog --clear --backtitle "ProxMenux" \
                       --title "$(translate "Utilities Installation Menu")" \
                       --menu "$(translate "Select an option"):" 20 70 12 \
                       "1" "$(translate "Custom selection")" \
                       "2" "$(translate "Install ALL utilities")" \
                       "3" "$(translate "Install basic utilities") (grc, htop, tree, curl, wget)" \
                       "4" "$(translate "Install development tools") (git, vim, nano)" \
                       "5" "$(translate "Install compression tools") (zip, unzip, rsync)" \
                       "6" "$(translate "Install terminal multiplexers") (screen, tmux)" \
                       "7" "$(translate "Install analysis tools") (jq, ncdu, iotop)" \
                       "8" "$(translate "Install network tools") (nethogs, nmap, tcpdump, lsof)" \
                       "9" "$(translate "Verify installations")" \
                       "0" "$(translate "Return to main menu")" 2>&1 >/dev/tty)
        
        echo "$choice"
    }
    

    show_custom_selection() {
        local utilities=(
            "axel" "$(translate "Download accelerator")" "OFF"
            "dos2unix" "$(translate "Convert DOS/Unix text files")" "OFF"
            "grc" "$(translate "Generic log/command colorizer")" "OFF"
            "htop" "$(translate "Interactive process viewer")" "OFF"
            "btop" "$(translate "Modern resource monitor")" "OFF"
            "iftop" "$(translate "Real-time network usage")" "OFF"
            "iotop" "$(translate "Monitor disk I/O usage")" "OFF"
            "iperf3" "$(translate "Network performance testing")" "OFF"
            "ipset" "$(translate "Manage IP sets")" "OFF"
            "iptraf-ng" "$(translate "Network monitoring tool")" "OFF"
            "mlocate" "$(translate "Locate files quickly")" "OFF"
            "msr-tools" "$(translate "Access CPU MSRs")" "OFF"
            "net-tools" "$(translate "Legacy networking tools")" "OFF"
            "sshpass" "$(translate "Non-interactive SSH login")" "OFF"
            "tmux" "$(translate "Terminal multiplexer")" "OFF"
            "unzip" "$(translate "Extract ZIP files")" "OFF"
            "zip" "$(translate "Create ZIP files")" "OFF"
            "libguestfs-tools" "$(translate "VM disk utilities")" "OFF"
            "aria2" "$(translate "Multi-source downloader")" "OFF"
            "cabextract" "$(translate "Extract CAB files")" "OFF"
            "wimtools" "$(translate "Manage WIM images")" "OFF"
            "genisoimage" "$(translate "Create ISO images")" "OFF"
            "chntpw" "$(translate "Edit Windows registry/passwords")" "OFF"
        )
        
        local selected
        selected=$(dialog --clear --backtitle "ProxMenux" \
                         --title "$(translate "Select utilities to install")" \
                         --checklist "$(translate "Use SPACE to select/deselect, ENTER to confirm")" \
                         25 80 20 "${utilities[@]}" 2>&1 >/dev/tty)
        
        echo "$selected"
    }
    

    install_utility_group() {
        local group_name="$1"
        shift
        local utilities=("$@")
       
        clear
        show_proxmenux_logo        
        msg_title "$(translate "Installing group"): $group_name"
        
        local failed=0
        local success=0
        local warning=0
        

        declare -A package_to_command=(
            ["mlocate"]="locate"
            ["msr-tools"]="rdmsr"
            ["net-tools"]="netstat"
            ["libguestfs-tools"]="virt-filesystems"
            ["aria2"]="aria2c"
            ["wimtools"]="wimlib-imagex"
        )
        
        for util_info in "${utilities[@]}"; do
            IFS=':' read -r package command description <<< "$util_info"
            

            local verify_command="${package_to_command[$package]:-$command}"
            

            install_single_package "$package" "$verify_command" "$description"
            local install_result=$?
            
            case $install_result in
                0) success=$((success + 1)) ;;
                1) failed=$((failed + 1)) ;;
                2) warning=$((warning + 1)) ;;
            esac
        done
        
        echo
        msg_info2 "$(translate "Installation summary") - $group_name:"
        msg_ok "$(translate "Successful"): $success"
        [ $warning -gt 0 ] && msg_warn "$(translate "With warnings"): $warning"
        [ $failed -gt 0 ] && msg_error "$(translate "Failed"): $failed"
        
        dialog --clear --backtitle "ProxMenux" \
               --title "$(translate "Installation Complete")" \
               --msgbox "$(translate "Group"): $group_name\n$(translate "Successful"): $success\n$(translate "With warnings"): $warning\n$(translate "Failed"): $failed" 10 50
    }
    

    install_selected_utilities() {
        local selected="$1"
        
        if [ -z "$selected" ]; then
            dialog --clear --backtitle "ProxMenux" \
                   --title "$(translate "No Selection")" \
                   --msgbox "$(translate "No utilities were selected")" 8 40
            return
        fi

        clear
        show_proxmenux_logo        
        msg_title "$(translate "Installing selected utilities")"
        
        local failed=0
        local success=0
        local warning=0
        

        local selected_array
        IFS=' ' read -ra selected_array <<< "$selected"
        

        declare -A package_to_command=(
            ["mlocate"]="locate"
            ["msr-tools"]="rdmsr"
            ["net-tools"]="netstat"
            ["libguestfs-tools"]="virt-filesystems"
            ["aria2"]="aria2c"
            ["wimtools"]="wimlib-imagex"
        )
        
        for util in "${selected_array[@]}"; do

            util=$(echo "$util" | tr -d '"')
            

            local verify_command="${package_to_command[$util]:-$util}"
            

            install_single_package "$util" "$verify_command" "$util"
            local install_result=$?
            
            case $install_result in
                0) success=$((success + 1)) ;;
                1) failed=$((failed + 1)) ;;
                2) warning=$((warning + 1)) ;;
            esac
        done
        

        if [ -f ~/.bashrc ]; then
            source ~/.bashrc >/dev/null 2>&1
        fi
        hash -r 2>/dev/null
        
        echo
        msg_info2 "$(translate "Installation summary"):"
        msg_ok "$(translate "Successful"): $success"
        [ $warning -gt 0 ] && msg_warn "$(translate "With warnings"): $warning"
        [ $failed -gt 0 ] && msg_error "$(translate "Failed"): $failed"
        
        dialog --clear --backtitle "ProxMenux" \
               --title "$(translate "Installation Complete")" \
               --msgbox "$(translate "Selected utilities installation completed")\n$(translate "Successful"): $success\n$(translate "With warnings"): $warning\n$(translate "Failed"): $failed" 12 60
    }
    

    verify_installations() {
        clear
        show_proxmenux_logo
        msg_info "$(translate "Verifying all utilities status")..."
        
        local utilities=(
            "axel:Download accelerator"
            "dialog:Console GUI dialogs"
            "dos2unix:Convert DOS/Unix text files"
            "grc:Generic log/command colorizer"
            "htop:Interactive process viewer"
            "btop:Modern resource monitor"
            "iftop:Real-time network usage"
            "iotop:Monitor disk I/O usage"
            "iperf3:Network performance testing"
            "ipset:Manage IP sets"
            "iptraf-ng:Network monitoring tool"
            "locate:Locate files quickly"
            "rdmsr:Access CPU MSRs"
            "netstat:Legacy networking tools"
            "sshpass:Non-interactive SSH login"
            "tmux:Terminal multiplexer"
            "unzip:Extract ZIP files"
            "zip:Create ZIP files"
            "virt-filesystems:VM disk utilities"
            "aria2c:Multi-source downloader"
            "cabextract:Extract CAB files"
            "wimlib-imagex:Manage WIM images"
            "genisoimage:Create ISO images"
            "chntpw:Edit Windows registry/passwords"
        )
        
        local available=0
        local missing=0
        local status_text=""
        
        for util in "${utilities[@]}"; do
            IFS=':' read -r cmd desc <<< "$util"
            if command_exists "$cmd"; then
                status_text+="\n✓ $cmd - $desc"
                available=$((available + 1))
            else
                status_text+="\n✗ $cmd - $desc"
                missing=$((missing + 1))
            fi
        done
        
        cleanup
        
        local summary="$(translate "Total"): $((available + missing))\n$(translate "Available"): $available\n$(translate "Missing"): $missing"
        
        dialog --clear --backtitle "ProxMenux" \
               --title "$(translate "Utilities Verification")" \
               --msgbox "$summary$status_text" 25 80
    }
    

    

    while true; do
        choice=$(show_main_utilities_menu)
        
        case $choice in
            1)

                selected=$(show_custom_selection)
                install_selected_utilities "$selected"
                ;;
            2)

                all_utils=(
                    "axel:axel:Download accelerator"
                    "dos2unix:dos2unix:Convert DOS/Unix text files"
                    "grc:grc:Generic log/command colorizer"
                    "htop:htop:Interactive process viewer"
                    "btop:btop:Modern resource monitor"
                    "iftop:iftop:Real-time network usage"
                    "iotop:iotop:Monitor disk I/O usage"
                    "iperf3:iperf3:Network performance testing"
                    "ipset:ipset:Manage IP sets"
                    "iptraf-ng:iptraf-ng:Network monitoring tool"
                    "mlocate:locate:Locate files quickly"
                    "msr-tools:rdmsr:Access CPU MSRs"
                    "net-tools:netstat:Legacy networking tools"
                    "sshpass:sshpass:Non-interactive SSH login"
                    "tmux:tmux:Terminal multiplexer"
                    "unzip:unzip:Extract ZIP files"
                    "zip:zip:Create ZIP files"
                    "libguestfs-tools:virt-filesystems:VM disk utilities"
                    "aria2:aria2c:Multi-source downloader"
                    "cabextract:cabextract:Extract CAB files"
                    "wimtools:wimlib-imagex:Manage WIM images"
                    "genisoimage:genisoimage:Create ISO images"
                    "chntpw:chntpw:Edit Windows registry/passwords"
                )
                install_utility_group "$(translate "ALL Utilities")" "${all_utils[@]}"
                ;;    
            3)

                basic_utils=(
                    "grc:grc:Generic Colouriser"
                    "htop:htop:Process monitor"
                    "tree:tree:Directory structure"
                    "curl:curl:Data transfer"
                    "wget:wget:Web downloader"
                )
                install_utility_group "$(translate "Basic Utilities")" "${basic_utils[@]}"
                ;;
            4)

                dev_utils=(
                    "git:git:Version control"
                    "vim:vim:Advanced editor"
                    "nano:nano:Simple editor"
                )
                install_utility_group "$(translate "Development Tools")" "${dev_utils[@]}"
                ;;
            5)

                compress_utils=(
                    "zip:zip:ZIP compressor"
                    "unzip:unzip:ZIP extractor"
                    "rsync:rsync:File synchronizer"
                )
                install_utility_group "$(translate "Compression Tools")" "${compress_utils[@]}"
                ;;
            6)

                multiplex_utils=(
                    "screen:screen:Terminal multiplexer"
                    "tmux:tmux:Advanced multiplexer"
                )
                install_utility_group "$(translate "Terminal Multiplexers")" "${multiplex_utils[@]}"
                ;;
            7)

                analysis_utils=(
                    "jq:jq:JSON processor"
                    "ncdu:ncdu:Disk analyzer"
                    "iotop:iotop:I/O monitor"
                )
                install_utility_group "$(translate "Analysis Tools")" "${analysis_utils[@]}"
                ;;
            8)

                network_utils=(
                    "nethogs:nethogs:Network monitor"
                    "nmap:nmap:Network scanner"
                    "tcpdump:tcpdump:Packet analyzer"
                    "lsof:lsof:Open files"
                )
                install_utility_group "$(translate "Network Tools")" "${network_utils[@]}"
                ;;
            9)
                verify_installations
                ;;
            0|"")
                break
                ;;
            *)
                dialog --clear --backtitle "ProxMenux" \
                       --title "$(translate "Invalid Option")" \
                       --msgbox "$(translate "Please select a valid option")" 8 40
                ;;
        esac
    done
    
    clear
}


install_system_utils