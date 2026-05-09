#!/bin/bash
# ==========================================================
# ProxMenux - GPU and TPU Menu
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
# Version     : 2.0
# Last Updated: 01/04/2026
# ==========================================================

# Configuration
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache

# ==========================================================

while true; do
    OPTION=$(dialog --colors --backtitle "ProxMenux" \
        --title "$(translate "GPUs and Coral-TPU Menu")" \
        --menu "\n$(translate "Select an option:")" 26 78 16 \
            ""  "\Z4──────────────────────── HOST ─────────────────────────\Zn" \
            "1"         "$(translate "Install/Update NVIDIA Drivers (Host + LXC)")" \
            "2"         "$(translate "Install/Update Coral TPU on Host")" \
            ""          "" \
            ""  "\Z4──────────────────────── LXC ──────────────────────────\Zn" \
            "3"         "$(translate "Add GPU to LXC   (Intel | AMD | NVIDIA)")  \Zb\Z4Switch Mode\Zn" \
            "4"         "$(translate "Add Coral TPU to LXC")" \
            ""          "" \
            ""  "\Z4──────────────────────── VM ───────────────────────────\Zn" \
            "5"         "$(translate "Add GPU to VM    (Intel | AMD | NVIDIA)")  \Zb\Z4Switch Mode\Zn" \
            ""          "" \
            ""  "\Z4──────────────────── SWICHT MODE ───────────────────────\Zn" \
            "6"         "$(translate "Switch GPU Mode  (VM <-> LXC)")" \
            ""  "" \
            ""  "\Z4────────────────────── Utilities ───────────────────────\Zn" \
            "7"         "$(translate "Manual CLI Guide (GPU/TPU)")" \
            "0"         "$(translate "Return to Main Menu")" \
            2>&1 >/dev/tty
    ) || { exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"; }

    case "$OPTION" in
        1)
            bash "$LOCAL_SCRIPTS/gpu_tpu/nvidia_installer.sh"
            ;;
        2)
            bash "$LOCAL_SCRIPTS/gpu_tpu/install_coral.sh"
            ;;
        3)
            bash "$LOCAL_SCRIPTS/gpu_tpu/add_gpu_lxc.sh"
            ;;
        4)
            bash "$LOCAL_SCRIPTS/gpu_tpu/install_coral_lxc.sh"
            ;;
        5)
            bash "$LOCAL_SCRIPTS/gpu_tpu/add_gpu_vm.sh"
            ;;
        6)
            bash "$LOCAL_SCRIPTS/gpu_tpu/switch_gpu_mode.sh"
            ;;
        7)
            bash "$LOCAL_SCRIPTS/gpu_tpu/gpu-tpu-manual-guide.sh"
            ;;
        0)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
        *)
            exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
            ;;
    esac
done
