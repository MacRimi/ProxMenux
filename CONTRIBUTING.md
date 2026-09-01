# Contributing to ProxMenux

Thank you for your interest in contributing to **ProxMenux**! This document covers everything you need to know to write scripts that integrate correctly with the project's interface, conventions, and design policy.

---

## Table of Contents

1. [Script Header Template](#1-script-header-template)
2. [Project Structure](#2-project-structure)
3. [UI Design Policy](#3-ui-design-policy)
   - [The Two Phases](#the-two-phases)
   - [Phase 1 — Selection Phase](#phase-1--selection-phase)
   - [Phase 2 — Execution Phase](#phase-2--execution-phase)
   - [Flow Diagram](#flow-diagram)
   - [When Phase 1 Has No Silent Work](#when-phase-1-has-no-silent-work)
4. [dialog vs whiptail — when to use each](#4-dialog-vs-whiptail--when-to-use-each)
5. [Message Functions Reference](#5-message-functions-reference)
6. [dialog Conventions](#6-dialog-conventions)
7. [Translation Policy](#7-translation-policy)
8. [Variable & Style Conventions](#8-variable--style-conventions)
9. [Do's and Don'ts](#9-dos-and-donts)
10. [Submitting a Contribution](#10-submitting-a-contribution)
11. [Contributing to the Monitor](#11-contributing-to-the-monitor)

---

## 1. Script Header Template

Every script in ProxMenux opens with **two adjacent comment blocks** that together form the header. They are both required:

- **Top block — metadata.** Identifies who wrote the script, the optional GitHub / Sponsor links of the contributor, the maintainer, copyright, license, version and last-updated date.
- **Bottom block — description.** A short paragraph in plain English explaining what the script does. This is what users read **before** opening the code — it must be self-contained enough that someone who only sees the header understands the purpose of the script.

The `GitHub` and `Sponsor` lines are optional. Author / GitHub / Sponsor are how contributor recognition works in ProxMenux: when you write a new script, your name goes here, and you can include a link to your personal page (GitHub) and a sponsor profile (Ko-fi, GitHub Sponsors, Buy Me a Coffee, etc.).

> **The license line is fixed — GPL-3.0.** ProxMenux is published under the GNU General Public License v3.0. Every script in the project ships under that same license; the `License` line in the header is always the GPL-3.0 reference shown in the example below — it is not a per-script choice. By contributing a script you agree to release it under GPL-3.0, which means anyone can read it, modify it and redistribute it (including modifications) as long as they keep it under the same license. The full text lives at [`MacRimi/ProxMenux/LICENSE`](https://github.com/MacRimi/ProxMenux/blob/main/LICENSE).

```bash
#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : Your Name
# GitHub      : github.com/yourhandle
# Sponsor     : ko-fi.com/yourhandle
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: DD/MM/YYYY
# ==========================================================
# Description:
# Short paragraph explaining what the script does.
# Mention the main actions (e.g. "creates a ZFS pool",
# "configures IOMMU and reboots", "imports an ISO into a VM"),
# the resources it touches, and any prerequisites the user
# should be aware of before running it.
# ==========================================================

# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"
BACKTITLE="ProxMenux"

# Standard dialog dimensions
UI_MENU_H=20
UI_MENU_W=84
UI_MENU_LIST_H=10
UI_SHORT_MENU_H=16
UI_SHORT_MENU_W=72
UI_SHORT_MENU_LIST_H=6
UI_MSG_H=10
UI_MSG_W=72
UI_YESNO_H=12
UI_YESNO_W=72
UI_RESULT_H=14
UI_RESULT_W=86

[[ -f "$UTILS_FILE" ]] && source "$UTILS_FILE"
load_language
initialize_cache
# Configuration ============================================
```

---

## 2. Project Structure

ProxMenux is split into two main trees: the **shell scripts** (menu-driven CLI, covered by this guide) and the **Monitor** (Next.js + Flask web dashboard, covered in [§11](#11-contributing-to-the-monitor)).

```
scripts/                # Shell scripts — CLI tree (this guide, sections 1–10)
├── menus/              # Top-level menu scripts (entry points)
├── storage/            # Disk, storage and passthrough scripts
├── share/              # NFS, Samba, local share scripts
├── vm/                 # VM creation and configuration scripts
├── gpu_tpu/            # GPU/TPU passthrough scripts
├── post_install/       # Post-install automation scripts
├── backup_restore/     # Backup and restore scripts
├── utilities/          # System utility scripts
├── global/             # Shared helper libraries (sourced by other scripts)
├── utils.sh            # Shared utility functions and message helpers
└── help_info_menu.sh   # Interactive help and command reference

AppImage/               # Monitor — web dashboard (§11)
├── app/                # Next.js app routes
├── components/         # React components (shadcn + Tailwind)
├── lib/i18n/           # i18n provider + language registry
├── messages/<lang>/    # Per-locale JSON catalogs (Monitor UI strings)
├── scripts/            # Flask backend, health monitor, notification manager
└── scripts/build_appimage.sh  # AppImage build script

lang/<lang>.json        # Per-locale translation cache — CLI shell strings
```

Every shell script sources `utils.sh` to get access to the message functions, spinner, color variables, and translation system.

**Shared helper libraries** (in `scripts/global/`) must be sourced explicitly:

```bash
if [[ -f "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_LOCAL/global/vm_storage_helpers.sh"
elif [[ -f "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh" ]]; then
  source "$LOCAL_SCRIPTS_DEFAULT/global/vm_storage_helpers.sh"
fi
```

---

## 3. UI Design Policy

This is the most important section. ProxMenux scripts follow a strict two-phase design. **All contributors must follow this policy.**

### The Two Phases

Every script is divided into exactly two phases:

| Phase | Purpose | Screen state |
|---|---|---|
| **Phase 1 — Selection** | Collect all user decisions and register preparatory data | `dialog` overlays + silent work |
| **Phase 2 — Execution** | Execute all operations and display full progress | messages accumulate |

---

### Phase 1 — Selection Phase

Phase 1 gathers everything the script needs before any real action begins. It has two kinds of activity:

**1a. Dialog menus** — ask the user to select devices, options, parameters. Use `dialog` freely.

**1b. Silent preparatory work** — between dialogs, some checks or scans may be needed (e.g., listing VMs, detecting disk assignments, checking CT status). These use `msg_info` + `stop_spinner`:

- `msg_info` shows a spinner while the work runs.
- `stop_spinner` kills the spinner and **clears the line** — the result is *not* shown visually.
- The result is stored in a variable or array for later use.
- This is intentional: Phase 1 is not a display phase. The user sees dialogs, not progress messages.

```bash
# Silent preparatory work between dialogs
msg_info "$(translate "Checking disk assignments...")"
ASSIGNED_TO=$(check_assignments "$DISK")   # can take time
stop_spinner   # ← clears line silently, result saved in variable

# Next dialog can now use ASSIGNED_TO
if [ -n "$ASSIGNED_TO" ]; then
    dialog --yesno "$(translate "Disk already assigned. Continue?")" ...
fi
```

**Rules for Phase 1:**
- If a `msg_info` spinner is currently running and you need to open a `dialog` or `whiptail` menu, call `stop_spinner` first — the spinner can't coexist with the overlay drawn by either tool. If no spinner is active, you don't need to call it.
- Use `show_proxmenux_logo` + `msg_title` + `msg_info` when you want to give the user visual context for a long-running operation in Phase 1 (e.g. a probe that takes 5+ seconds). The function includes a screen clear, so don't call `clear` before it.
- Don't call `show_proxmenux_logo` between dialog menus where there's nothing to display — clearing the screen for an empty terminal is just visual noise.
- Store all decisions and probe results in variables or parallel arrays. The visible recap happens at the start of Phase 2, not in Phase 1.
- When multiple dialogs are needed per item, collect all decisions into parallel arrays:

```bash
declare -a DISK_LIST=()
declare -a DISK_FORMAT_TYPES=()
declare -a DISK_MOUNT_POINTS=()

for DISK in $SELECTED; do
    DISK="${DISK//\"/}"

    # Silent check (preparatory work)
    msg_info "$(translate "Analyzing disk...")"
    CURRENT_FS=$(lsblk -no FSTYPE "$DISK" | xargs)
    stop_spinner   # result stored, not shown

    # Dialog using the checked result
    FORMAT=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Select Filesystem")" \
        --menu "..." $UI_SHORT_MENU_H $UI_SHORT_MENU_W $UI_SHORT_MENU_LIST_H \
        "ext4" "..." "xfs" "..." "btrfs" "..." \
        2>&1 >/dev/tty)
    [ -z "$FORMAT" ] && continue

    MOUNT=$(dialog --backtitle "$BACKTITLE" \
        --title "$(translate "Mount Point")" \
        --inputbox "..." $UI_MSG_H $UI_MSG_W "/mnt/data" \
        2>&1 >/dev/tty)
    [ -z "$MOUNT" ] && continue

    DISK_LIST+=("$DISK")
    DISK_FORMAT_TYPES+=("$FORMAT")
    DISK_MOUNT_POINTS+=("$MOUNT")
done
```

---

### Phase 2 — Execution Phase

Phase 2 executes all operations and displays a full, accumulating progress history. This is what the user sees as the "result" of the script.

**Opening Phase 2:**

Always start with `show_proxmenux_logo + msg_title`. Then immediately show **as `msg_ok` lines** the key results from Phase 1 preparatory work — things the user did not see because `stop_spinner` cleared them silently. This gives full context before any new operations begin.

```bash
# ── PHASE 2 — EXECUTION ───────────────────────────────────
show_proxmenux_logo
msg_title "$(translate "My Script Title")"

# Recap Phase 1 preparatory results — show what was already done
msg_ok "$(translate "CT $CTID selected.")"
msg_ok "$(translate "Repositories verified.")"
msg_ok "$(translate "Disks to process: ${#DISK_LIST[@]}")"

# Now execute operations
for i in "${!DISK_LIST[@]}"; do
    DISK="${DISK_LIST[$i]}"
    FORMAT="${DISK_FORMAT_TYPES[$i]}"
    MOUNT="${DISK_MOUNT_POINTS[$i]}"

    msg_info "$(translate "Formatting") $DISK $(translate "as") $FORMAT..."
    mkfs."$FORMAT" "$DISK" >/dev/null 2>&1
    msg_ok "$(translate "Formatted.")"

    msg_info "$(translate "Applying passthrough...")"
    pct set "$CTID" -mp0 "$DISK,mp=$MOUNT" >/dev/null 2>&1
    msg_ok "$(translate "Disk assigned at") $MOUNT."
done

msg_ok "$(translate "Completed. ${#DISK_LIST[@]} disk(s) added.")"
msg_success "$(translate "Press Enter to return to menu...")"
read -r
```

**Rules for Phase 2:**
- Always start with `show_proxmenux_logo + msg_title`.
- Immediately after `msg_title`, show `msg_ok` lines recapping Phase 1 results.
- Never call `show_proxmenux_logo` again — it clears all accumulated progress.
- Never call `dialog` in Phase 2. All decisions must have been collected in Phase 1.
- If a user interaction is absolutely unavoidable at execution time (a situation that could not be known in Phase 1), use `whiptail` — a lighter tool that does not clear the terminal context. See [Reboot Dialog Pattern](#reboot-dialog-pattern).
- Use `msg_info → msg_ok` for every operation.

**If no items were collected in Phase 1:**

```bash
if [ "${#DISK_LIST[@]}" -eq 0 ]; then
    show_proxmenux_logo
    msg_title "$(translate "My Script Title")"
    msg_warn "$(translate "No items were configured for processing.")"
    echo ""
    msg_success "$(translate "Press Enter to return to menu...")"
    read -r
    exit 0
fi
```

#### Reboot Dialog Pattern

When a reboot may be required at the end of Phase 2 (e.g., IOMMU enabled, VFIO configured), use `whiptail` — never `dialog`. Always:

1. Use `msg_ok` (not `msg_warn`) to report the state change — enabling a feature is a success.
2. Build the reboot reason dynamically based on what actually changed.
3. Always include a "No" branch that warns the user not to start the VM until rebooted.
4. Place the reboot dialog **before** `msg_success "Press Enter..."`.

```bash
local HOST_REBOOT_REQUIRED="no"
local REBOOT_REASONS=""

if [[ "${IOMMU_PENDING_REBOOT:-0}" == "1" ]]; then
  HOST_REBOOT_REQUIRED="yes"
  msg_ok "$(translate "IOMMU has been enabled — a system reboot is required")"
  REBOOT_REASONS+="$(translate "IOMMU has been enabled on this system.")\n"
fi
if [[ "$SOME_OTHER_CHANGE" == "yes" ]]; then
  HOST_REBOOT_REQUIRED="yes"
  REBOOT_REASONS+="$(translate "Other changes require a host reboot.")\n"
fi

if [[ "$HOST_REBOOT_REQUIRED" == "yes" ]]; then
  echo ""
  if whiptail --title "$(translate "Reboot Required")" --yesno \
"\n${REBOOT_REASONS}\n$(translate "A host reboot is required before starting the VM. Reboot now?")" 13 78; then
    msg_warn "$(translate "Rebooting the system...")"
    reboot
  else
    echo ""
    msg_info2 "$(translate "To use the VM without issues, the host must be restarted before starting it.")"
    msg_info2 "$(translate "Do not start the VM until the system has been rebooted.")"
  fi
fi

msg_success "$(translate "Press Enter to return to menu...")"
read -r
```

---

### Flow Diagram

```
Script starts
     │
     ▼
╔════════════════════════════════════╗
║  PHASE 1 — SELECTION               ║
║                                    ║
║  dialog (select CT)                ║  ← user input
║                                    ║
║  msg_info "Checking privileges..."  ║  ← silent work
║  check_privileges                  ║
║  stop_spinner  [result saved]      ║  ← no visual output
║                                    ║
║  dialog (unprivileged? convert?)   ║  ← user input
║                                    ║
║  msg_info "Scanning disks..."      ║  ← silent work
║  scan_disks                        ║
║  stop_spinner  [result saved]      ║  ← no visual output
║                                    ║
║  dialog (select disks)             ║  ← user input
║                                    ║
║  for each disk:                    ║
║    msg_info "Analyzing..."         ║  ← silent work
║    stop_spinner  [result saved]    ║  ← no visual output
║    dialog (select filesystem)      ║  ← user input
║    dialog (WARNING: format?)       ║  ← user input
║    dialog (mount point)            ║  ← user input
║    → store in parallel arrays      ║
╚══════════════════╦═════════════════╝
                   ║  all input collected
                   ▼
╔════════════════════════════════════╗
║  PHASE 2 — EXECUTION               ║
║                                    ║
║  show_proxmenux_logo + msg_title   ║  ← opens visual context (ONCE)
║                                    ║
║  msg_ok "CT selected."             ║  ← recap Phase 1 work
║  msg_ok "Privileges verified."     ║  ← recap Phase 1 work
║  msg_ok "N disks to process."      ║  ← recap Phase 1 work
║                                    ║
║  for each disk:                    ║
║    msg_info "Formatting..."        ║
║    format_disk                     ║
║    msg_ok "Formatted."             ║
║    msg_info "Applying..."          ║
║    pct set                         ║
║    msg_ok "Assigned at /mnt/..."   ║
║                                    ║
║  [whiptail reboot dialog if needed]║  ← only if reboot required
║                                    ║
║  msg_ok "Completed."               ║
║  msg_success "Press Enter..."      ║
║  read -r                           ║
╚════════════════════════════════════╝
```

> **Key insight:** The user never sees the Phase 1 preparatory work as it happens (it runs silently under `stop_spinner`). Phase 2 must make it visible by recapping those results as `msg_ok` lines at the start. This gives the user full context before the main operations begin.

---

### When Phase 1 Has No Silent Work

Some scripts have only immediate dialogs with no preparatory checks. In that case, there is nothing to recap — Phase 2 starts directly with the summary of user selections:

```bash
# Phase 1 — only dialogs, no silent work
VMID=$(dialog ... 2>&1 >/dev/tty)
STORAGE=$(dialog ... 2>&1 >/dev/tty)

# Phase 2
show_proxmenux_logo
msg_title "$(translate "Import Disk")"
msg_ok "$(translate "VM: $VMID")"          # recap user selection
msg_ok "$(translate "Storage: $STORAGE")"  # recap user selection

msg_info "$(translate "Importing disk...")"
...
```

---

## 4. dialog vs whiptail — when to use each

ProxMenux uses both tools, but for very different purposes. Picking the wrong one breaks the visual flow of the script.

| Tool | When to use it | Effect on screen |
|---|---|---|
| `dialog` | **Always in Phase 1.** Default tool for any interactive menu (selection, input, yes/no, checklist). | Clears the screen and takes full control. When it closes, the previous terminal state is restored. |
| `whiptail` | **Only in Phase 2, and only if unavoidable** — the typical case is a reboot prompt at the end of a script. | Draws a lighter overlay that does **not** erase the terminal history. The `msg_ok` log stays visible behind it. |

**Why the distinction?** If you call `dialog` in Phase 2, it wipes the entire `msg_info → msg_ok` history the user has been watching — they lose all context about what the script actually did. `whiptail` keeps that visual context intact: the user can still read the progress log while answering the prompt.

> See [Reboot Dialog Pattern](#reboot-dialog-pattern) for the canonical Phase 2 `whiptail` example.

The reverse rule also holds: don't reach for `whiptail` in Phase 1 just because the syntax is shorter. Phase 1 is the `dialog` phase by convention — mixing both makes the visual style of the project drift.

---

## 5. Message Functions Reference

All functions are defined in `utils.sh` and available after sourcing it. Use them as the default for any user-visible output — consistent visuals across scripts is the whole point. If your script needs a new function that doesn't fit the existing set (a new severity level, a new layout helper, etc.), propose it in your Pull Request — it will be reviewed and added to `utils.sh` if it's broadly useful.

| Function | Description | Spinner |
|---|---|---|
| `msg_info "text"` | Yellow text + starts spinner | Starts |
| `stop_spinner` | Kills spinner, clears line | Stops |
| `msg_ok "text"` | Green ✓ + text, kills spinner | Stops |
| `msg_error "text"` | Red [ERROR] + text, kills spinner | Stops |
| `msg_warn "text"` | Yellow bold text, kills spinner | Stops |
| `msg_info2 "text"` | Cyan informational line, kills spinner | Stops |
| `msg_success "text"` | Blue bold text, kills spinner | Stops |
| `msg_title "text"` | Bold title with built-in spacing | — |
| `show_proxmenux_logo` | Clears screen, shows logo | — |

**Message severity semantics — use the right function:**

| Situation | Function |
|---|---|
| Operation in progress | `msg_info` |
| Operation succeeded | `msg_ok` |
| Feature enabled (even if reboot needed) | `msg_ok` |
| Feature was already active/up to date | `msg_ok` |
| Non-blocking advisory (e.g., "don't start VM until reboot") | `msg_info2` |
| Actual warning or degraded state | `msg_warn` |
| Fatal error | `msg_error` |
| Final "Press Enter" prompt | `msg_success` |

> **Important:** `msg_ok` is correct even when a reboot is required. A feature being enabled is a success — the reboot requirement is communicated separately via a `whiptail` dialog or `msg_info2`. Never use `msg_warn` to report that something was successfully configured.

**Important notes:**

- `msg_info` launches `spinner &` in the background. Never call `dialog` while `msg_info` is active — always call `stop_spinner` first.
- `msg_ok`, `msg_error`, `msg_warn`, and `msg_success` all kill the spinner automatically.
- `msg_title` includes `\n` before and after — do **not** add `echo ""` around it.
- `stop_spinner` is used between dialogs (leaves no visible mark). Use `msg_ok` to visibly confirm completion before moving to the terminal phase.

**Example — correct sequence:**

```bash
msg_info "$(translate "Scanning disks...")"
DISKS=$(lsblk ...)        # work while spinner runs
stop_spinner              # stop before dialog

SELECTED=$(dialog ... 2>&1 >/dev/tty)   # now dialog is safe

# Later, in terminal phase:
msg_info "$(translate "Formatting disk...")"
mkfs.ext4 "$DISK" >/dev/null 2>&1
msg_ok "$(translate "Disk formatted.")"
```

---

## 6. dialog Conventions

- Always pass `--backtitle "$BACKTITLE"` to every `dialog` and `whiptail` call. `$BACKTITLE` is always `"ProxMenux"` — set once at the script header and never overridden. The user must always see the project name as the framing context, never the script's own title.
- Always wrap titles and messages with `$(translate "...")`.
- Always redirect `dialog` output with `2>&1 >/dev/tty` to capture the selection.
- Use the standard UI dimension variables (`$UI_MENU_H`, `$UI_MSG_W`, etc.) for consistent sizing.
- Check for empty/cancelled selections and handle them gracefully:

```bash
VMID=$(dialog --backtitle "$BACKTITLE" \
              --title "$(translate "Select VM")" \
              --menu "..." $UI_MENU_H $UI_MENU_W $UI_MENU_LIST_H \
              $VM_LIST \
              2>&1 >/dev/tty)

if [ -z "$VMID" ]; then
    exit 0    # user cancelled — exit silently
fi
```

**Colored dialogs** — for compatibility notices or risk warnings, use `dialog --colors` with ANSI color codes:

```bash
dialog --colors --backtitle "$BACKTITLE" \
  --title "$(translate "Compatibility Notice")" \
  --msgbox "\n\Zb\Z4$(translate "Title line in blue bold")\Zn\n\n\Z1$(translate "Risk factor in red")\Zn\n\n$(translate "Normal text")" \
  $UI_MSG_H $UI_MSG_W
```

Color codes: `\Z1` = red, `\Z4` = blue, `\Zb` = bold, `\Zn` = reset.

---

## 7. Translation Policy

All user-visible strings must be wrapped with the `translate` function:

```bash
msg_ok "$(translate "Operation completed successfully.")"
msg_error "$(translate "Failed to start container") $CTID."
dialog --title "$(translate "Select Storage")" ...
```

**Rules:**
- Write strings in English — translation is handled automatically.
- Keep strings concise. Avoid embedding variables inside long sentences where possible.
- Do **not** translate variable names, paths, or technical identifiers.

---

## 8. Variable & Style Conventions

- Use `UPPER_CASE` for script-level variables.
- Use `lower_case` for local function variables (declare with `local`).
- Quote all variable expansions: `"$VAR"` not `$VAR`.
- Use `[[ ]]` for conditionals, not `[ ]`, except where POSIX compatibility is required.
- `show_proxmenux_logo` is the appropriate way to clear the screen — it includes the clear and shows the project logo so the user always has visual context. Call it once at the start of Phase 2 (and optionally before a long Phase 1 spinner block).

### Redirecting tool output during Phase 2

Phase 2 displays a clean log of `msg_info → msg_ok` lines accumulating on screen. If a tool you call (apt, mkfs, qm, pct, dd, etc.) writes its own output to stdout/stderr, it scrolls past your messages and breaks the visual flow.

Two patterns to choose from:

- **Discard the output** when you don't need it — fastest, simplest:
  ```bash
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" >/dev/null 2>&1
  ```
- **Send the output to a log file** when you may want to inspect it later (debugging a failed install, checking what dpkg actually did). Preferred pattern for any apt operation:
  ```bash
  apt-get install -y "$package" >> "$log_file" 2>&1
  ```

The script `scripts/global/update-pve9_2.sh` is a reference implementation — every `apt-get` call sends output to a log file so the user only sees the clean `msg_info → msg_ok` flow, while the log on disk lets you reconstruct exactly what apt did if anything goes wrong.

**Standard UI variable names:**

```bash
CTID        # container ID
VMID        # virtual machine ID
DISK        # device path e.g. /dev/sdb
PARTITION   # partition path e.g. /dev/sdb1
STORAGE     # Proxmox storage name
MOUNT_POINT # filesystem mount path
```

---

## 9. Do's and Don'ts

### Do's

```bash
# ✅ stop_spinner when a spinner is running and a dialog is about to open
msg_info "$(translate "Scanning disks...")"
DISKS=$(scan_disks)
stop_spinner   # ← clears line, result saved in variable
SELECTED=$(dialog ... 2>&1 >/dev/tty)   # dialog is now safe

# ✅ Phase 2 starts with show_proxmenux_logo + msg_title + recap
show_proxmenux_logo
msg_title "$(translate "My Script")"
msg_ok "$(translate "CT $CTID selected.")"        # recap Phase 1
msg_ok "$(translate "Repositories verified.")"    # recap Phase 1
msg_ok "$(translate "Disks to process: $N")"      # recap Phase 1
msg_info "$(translate "Formatting disk...")"       # Phase 2 operation starts

# ✅ msg_ok for successfully enabled features (even with pending reboot)
msg_ok "$(translate "IOMMU has been enabled — reboot required")"   # CORRECT
# msg_warn "$(translate "IOMMU was enabled...")"                   # WRONG

# ✅ msg_info2 for non-blocking advisories
msg_info2 "$(translate "Do not start the VM until the system has been rebooted.")"

# ✅ whiptail for post-execution dialogs (not dialog)
if whiptail --title "$(translate "Reboot Required")" --yesno \
  "\n${REBOOT_REASONS}\n$(translate "Reboot now?")" 13 78; then
  reboot
else
  msg_info2 "$(translate "Do not start the VM until the system has been rebooted.")"
fi

# ✅ Always include a "No" branch in reboot dialogs
if whiptail --yesno "...reboot?" ...; then
  reboot
else
  msg_info2 "$(translate "Do not start the VM until the system has been rebooted.")"
fi

# ✅ Guard VM list to exclude LXC containers
[[ -f "/etc/pve/qemu-server/${vmid}.conf" ]] || continue

# ✅ Add hostpciN to boot order after controller assignment
BOOT_ORDER="${BOOT_ORDER:+$BOOT_ORDER;}hostpci${hostpci_idx}"

# ✅ Use ensure_repositories before installing packages
ensure_repositories || true
apt-get install -y "$PACKAGE" >/dev/null 2>&1

# ✅ Consistent variable name between set and read for conflict actions
SWITCH_VM_ACTION="keep_gpu_disable_onboot"   # set in dialog phase
...
if [[ "$SWITCH_VM_ACTION" == "keep_gpu_disable_onboot" ]]; then ...   # read in apply phase

# ✅ parallel arrays when each item needs multiple dialogs in Phase 1
declare -a DISK_LIST=()
declare -a FORMAT_LIST=()
for DISK in $SELECTED; do
    msg_info "$(translate "Analyzing...")"
    CURRENT_FS=$(lsblk -no FSTYPE "$DISK" | xargs)
    stop_spinner
    FORMAT=$(dialog ... 2>&1 >/dev/tty)
    [ -z "$FORMAT" ] && continue
    DISK_LIST+=("$DISK")
    FORMAT_LIST+=("$FORMAT")
done
```

### Don'ts

```bash
# ❌ calling dialog while spinner is active
msg_info "$(translate "Loading...")"
dialog ...   # WRONG — call stop_spinner first

# ❌ skipping the Phase 1 recap in Phase 2
show_proxmenux_logo
msg_title "..."
msg_info "$(translate "Formatting...")"   # WRONG — no recap

# ❌ calling show_proxmenux_logo while Phase 2 messages are accumulating
show_proxmenux_logo
msg_ok "Step 1 done."
show_proxmenux_logo   # WRONG — erases "Step 1 done"

# ❌ using dialog in Phase 2
msg_ok "Phase 1 recap..."
dialog --yesno "$(translate "Format disk?")" ...   # WRONG — belongs in Phase 1

# ❌ bare clear
clear   # WRONG — only show_proxmenux_logo is allowed to clear the screen

# ❌ echo "" around msg_title
echo ""
msg_title "$(translate "Title")"   # WRONG — msg_title already includes spacing
echo ""

# ❌ msg_warn for successfully enabled features
msg_warn "$(translate "IOMMU was enabled. Reboot required.")"   # WRONG — use msg_ok

# ❌ reboot dialog with no "No" branch
if whiptail --yesno "Reboot?" ...; then reboot; fi   # WRONG — missing No branch

# ❌ unconditional apt-get update
apt-get update && apt-get install -y "$PACKAGE"   # WRONG — use ensure_repositories

# ❌ adding controllers to LXC containers
# Controllers/NVMe PCIe can only be added to VMs — always check:
# [[ -f "/etc/pve/qemu-server/${vmid}.conf" ]] || continue

# ❌ inconsistent variable names between dialog and apply phases
SWITCH_VM_ACTION="keep_gpu_disable_onboot"   # set here
...
if [[ "$VM_SWITCH_ACTION" == "keep_gpu_disable_onboot" ]]; then   # WRONG — different name
```

---

## 10. Submitting a Contribution

Code is submitted via a standard branch-based GitHub workflow. Before touching code, take a minute to signal intent — it makes coordination easier and prevents parallel work on the same thing.

### Where to look and where to signal

ProxMenux has three coordination surfaces, each with a clear purpose:

- **[ProxMenux Roadmap project](https://github.com/users/MacRimi/projects/1)** — the strategic direction. Six pillars (multi-node, workload authoring, multi-user & clustering, operational maturity, domain expansion, and in-flight items) group the work the project is investing in. Cards on the board show what's being worked on right now and by whom.
- **[Issues](https://github.com/MacRimi/ProxMenux/issues)** — bug reports and specific feature requests. Any issue with an assignee is already being worked on by that person.
- **[Discussions → Contributor Coordination](https://github.com/MacRimi/ProxMenux/discussions/categories/contributor-coordination)** — the room where contributors announce they're picking up a piece of work, ask for input before opening a PR, or coordinate around larger changes. The [pinned "How we coordinate work"](https://github.com/MacRimi/ProxMenux/discussions/286) thread is the living guide.

Rule of thumb: **any contribution likely to take more than an hour is worth a short heads-up in Contributor Coordination** — even one sentence saying you're on it. That way nobody else picks up the same work in parallel.

For general questions (not bug reports, not coordination), use [Discussions → Q&A](https://github.com/MacRimi/ProxMenux/discussions/categories/q-a).

### Branch model

ProxMenux uses three branch levels:

| Branch | Purpose |
|---|---|
| `main` | Stable, public-facing version that end users install. Only reviewed and validated code lands here. |
| `develop` | Active integration branch — the **beta** channel. Every new feature is merged here first. |
| `feature/*` | Short-lived branches for individual features or fixes. They branch off `develop` and merge back into `develop` after review. |

### Workflow in 5 steps

**1. Create your branch from `develop`:**

```bash
# Clone the repository (if you haven't already)
git clone https://github.com/MacRimi/ProxMenux.git
cd ProxMenux

# Sync and switch to the integration branch
git checkout develop
git pull origin develop

# Create your branch for the new feature
git checkout -b feature/add-tailscale-script
```

**2. Write and commit your changes:**

```bash
# ...write your code, follow this guide, test on a real Proxmox host...
git add scripts/utilities/my-new-script.sh
git commit -m "Add a script to install Tailscale"
```

**3. Push your branch to GitHub:**

```bash
git push -u origin feature/add-tailscale-script
```

**4. Open a Pull Request targeting `develop`:**

In GitHub, click "Compare & pull request". **Make sure the base branch is `develop`, NOT `main`** — PRs opened against `main` will be asked to re-target `develop`. In the PR description, explain what your script does and which Proxmox VE version you tested it on.

**5. Review and merge:**

Your PR will be reviewed against this guide. Once approved, it is merged into `develop` and ships in the next beta build. After enough validation in `develop`, the changes are promoted to `main` as part of a stable release.

### Before opening the PR — checklist

- [ ] Script follows the [two-phase UI design](#3-ui-design-policy)
- [ ] `dialog` only in Phase 1, `whiptail` only in Phase 2 (see [§4](#4-dialog-vs-whiptail--when-to-use-each))
- [ ] All user-visible strings wrapped in `$(translate "...")`
- [ ] Header block present with author / GitHub / Sponsor / GPL-3.0 license
- [ ] Tested on a real Proxmox VE instance (mention the version in the PR)
- [ ] Respects the [Code of Conduct](./CODE_OF_CONDUCT.md)

For security issues, see [SECURITY.md](./SECURITY.md).

### Documentation

Bug fixes usually don't need doc changes — the release notes cover the visible impact. But when your PR adds a new feature (a script, a Monitor view, an API endpoint, a workflow), you're in the best position to explain what it does — you built it. If you can, adding a page or paragraph to the [docs site](https://proxmenux.com/en/docs/introduction) alongside the code lands the whole thing in one PR. If you'd rather focus on the code, that's fine too — just flag it in the PR description so the docs pass is picked up separately.

The docs site lives in `/web/` and follows its own conventions — see [`web/CONTRIBUTING-TRANSLATIONS.md`](web/CONTRIBUTING-TRANSLATIONS.md) for structure and the translation flow.

---

## 11. Contributing to the Monitor

The Monitor is the web dashboard shipped as a self-contained AppImage. It has a different architecture from the shell scripts, so contributions to that side of the project follow different conventions. The coordination flow ([§10 — Where to look and where to signal](#where-to-look-and-where-to-signal)) is the same.

### Architecture

- **Frontend** — Next.js 15 with static export, TypeScript, React, [shadcn/ui](https://ui.shadcn.com/) components on top of Tailwind. Code lives in `AppImage/app/` (routes) and `AppImage/components/`.
- **Backend** — Flask, exposed on port 8008 on the Proxmox host. Route modules live in `AppImage/scripts/flask_*_routes.py`; the main server is `AppImage/scripts/flask_server.py`. Persistence is SQLite (`health_monitor.db`).
- **Packaging** — everything gets bundled into a single `ProxMenux-<version>.AppImage` by `AppImage/scripts/build_appimage.sh` and runs as a systemd service (`proxmenux-monitor.service`).

### UI conventions

- **All user-visible strings go through the i18n hook** — never hard-code labels. Use `useT()` when the component only needs the translation function (`const t = useT()`), or `useI18n()` when it also needs the current language / setter (`const { language, setLanguage, t } = useI18n()`). Both are exported from `lib/i18n/provider.tsx`. Missing keys fall back to English at runtime.
- **shadcn components** are the baseline (Card, Badge, Select, Switch, Dialog, etc.). Do not roll custom equivalents when a shadcn one exists.
- **Design tokens** live in Tailwind config; use them (`bg-blue-600`, `border-border`) rather than raw hex values.
- **Dark + light theme** must both work. Use tokens that respond to `data-theme` and `prefers-color-scheme`; don't hard-code palette values.

### Backend conventions

- **Authentication** — every mutating route (`POST` / `PUT` / `DELETE`) must be decorated with `@require_auth`. Read-only routes accept any authenticated caller. Never expose an admin endpoint without the decorator.
- **Notifications** — new notification event types are registered in `AppImage/scripts/notification_templates.py` (add to the `TEMPLATES` dict, pick a group, set `default_enabled`). Channel dispatch, filtering, and Quiet Hours handling are already handled by `notification_manager.py`.
- **Health checks** — `AppImage/scripts/health_monitor.py` is the single entry point for background checks. New checks slot into the existing scheduler cadence, respect the per-category thresholds in `settings.healthThresholds`, and emit through the notification manager when they cross a level.

### Adding a new locale

1. Add the locale code to `LanguageCode` and to `SUPPORTED_LANGUAGES` in `AppImage/lib/i18n/languages.ts`.
2. Import the JSON in `AppImage/lib/i18n/provider.tsx` and add it to `MESSAGE_CATALOG` (order: EN first, then alphabetical by native name).
3. Add `AppImage/messages/<lang>/common.json` — copy the structure from `en/common.json` and translate the values. Placeholders like `{vmid}`, `{count}` must stay unchanged.
4. Rebuild the AppImage and verify the language appears in Settings → Interface language.

For CLI shell strings, the translation cache lives in `lang/<lang>.json` — see [§7 (Translation Policy)](#7-translation-policy).

### Local dev

The AppImage builds on any Debian/Ubuntu host with Node 20+ and Python 3.11+ installed, but is normally built on a Proxmox host so the packaged Python matches the target runtime:

```bash
cd /path/to/ProxMenux
bash AppImage/scripts/build_appimage.sh
# → produces AppImage/dist/ProxMenux-<version>.AppImage
```

The practical iteration cycle for most changes is: edit code → `build_appimage.sh` → deploy the resulting AppImage to a Proxmox test host → restart `proxmenux-monitor.service` → refresh the browser. Rebuild + deploy takes a few minutes on a normal host.

For cosmetic UI-only iteration you can run the Next.js dev server directly:

```bash
cd AppImage
npm install
npm run dev  # → http://localhost:3000
```

Note that the dev server has no Flask backend on the same host by default: the app is a static export (`output: 'export'`) with relative `/api/*` calls, so the UI renders but all data endpoints fail unless you set up a proxy to a running Monitor. For anything beyond isolated styling / component work, the full build + deploy cycle above is the honest path.

### Testing

- **Python tests** — under `AppImage/scripts/tests/`. Run with `python3 -m unittest discover -s AppImage/scripts/tests`. Add a test file when you add non-trivial backend logic (auth, notifications, background checks).
- **UI smoke test** — deploy the built AppImage to a test host, restart `proxmenux-monitor.service`, and walk through the affected views in the browser. There is no formal e2e suite yet; a real-host smoke pass is expected for any UI change.
- **JSON parse** — after editing any i18n catalog, verify it parses: `python3 -c "import json; json.load(open('AppImage/messages/<lang>/common.json'))"`.

---

*For general questions use [Discussions → Q&A](https://github.com/MacRimi/ProxMenux/discussions/categories/q-a). For bug reports open an Issue. Direct contact: proxmenux@macrimi.pro*
