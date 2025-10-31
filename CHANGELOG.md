## 2025-09-04

### New version v1.1.7

### Added

- **ProxMenux Monitor**  
  Your new monitoring tool for Proxmox. Discover all the features that will help you manage and supervise your infrastructure efficiently.

  ProxMenux Monitor is designed to support future updates where **actions can be triggered without using the terminal**, and managed through a **user-friendly interface** accessible across multiple formats and devices.

  Access it at: **http://your-server-ip:8008**

  ![ProxMenux Monitor](https://macrimi.github.io/ProxMenux/monitor/welcome.png)
- **New Banner Removal Method**  
  A new function to disable the Proxmox subscription message with improved safety:
  - Creates a full backup before modifying any files
  - Shows a clear warning that breaking changes may occur with future GUI updates
  - If the GUI fails to load, the user can revert changes via SSH from the post-install menu using the **"Uninstall Options → Restore Banner"** tool

  Special thanks to **@eryonki** for providing the improved method.

---

### Improved

- **CORAL TPU Installer Updated for PVE 9**  
  The CORAL TPU driver installer now supports both **Proxmox VE 8 and VE 9**, ensuring compatibility with the latest kernels and udev rules.

- **Log2RAM Installation & Integration**  
  - Log2RAM installation is now idempotent and can be safely run multiple times.
  - Automatically adjusts `journald` configuration to align with the size and behavior of Log2RAM.
  - Ensures journaling is correctly tuned to avoid overflows or RAM exhaustion on low-memory systems.

- **Network Optimization Function (LXC + NFS)**  
  Improved to prevent “martian source” warnings in setups where **LXC containers share storage with VMs** over NFS within the same server.

- **APT Upgrade Progress**  
  When running full system upgrades via ProxMenux, a **real-time progress bar** is now displayed, giving the user clear visibility into the update process.

---

### Fixed

- Other small improvements and fixes to optimize runtime performance and eliminate minor bugs.



## 2025-01-10

### New version v1.1.6

![Shared Resources Menu](https://macrimi.github.io/ProxMenux/share/main-menu.png)


### Added

- **New Menu: Mount and Share Manager**  
  Introduced a comprehensive new menu for managing shared resources between Proxmox host and LXC containers:

  **Host Configuration Options:**
  - **Configure NFS Shared on Host** - Add, view, and remove NFS shared resources on the Proxmox server with automatic export management
  - **Configure Samba Shared on Host** - Add, view, and remove Samba/CIFS shared resources on the Proxmox server with share configuration  
  - **Configure Local Shared on Host** - Create and manage local shared directories with proper permissions on the Proxmox host

  **LXC Integration Options:**
  - **Configure LXC Mount Points (Host ↔ Container)** - **Core feature** that enables mounting host directories into LXC containers with automatic permission handling. Includes the ability to **view existing mount points** for each container in a clear, organized way and **remove mount points** with proper verification that the process completed successfully. Especially optimized for **unprivileged containers** where UID/GID mapping is critical.
  - **Configure NFS Client in LXC** - Set up NFS client inside privileged containers
  - **Configure Samba Client in LXC** - Set up Samba client inside privileged containers  
  - **Configure NFS Server in LXC** - Install NFS server inside privileged containers
  - **Configure Samba Server in LXC** - Install Samba server inside privileged containers

  **Documentation & Support:**
  - **Help & Info (commands)** - Comprehensive guides with step-by-step manual instructions for all sharing scenarios

  The entire system is built around the **LXC Mount Points** functionality, which automatically detects filesystem types, handles permission mapping between host and container users, and provides seamless integration for both privileged and unprivileged containers.

---

### Improved

- **Log2RAM Auto-Detection Enhancement**  
  In the automatic post-install script, the Log2RAM installation function now prompts the user when automatic disk ssd/m2 detection fails.
  This ensures Log2RAM can still be installed on systems where automatic disk detection doesn't work properly.

---

### Fixed

- **Proxmox Update Repository Verification**  
  Fixed an issue in the Proxmox update function where empty repository source files would cause errors during conflict verification. The function now properly handles empty `/etc/apt/sources.list.d/` files without throwing false warnings.

  Thanks to **@JF_Car** for reporting this issue.

---

### Acknowledgments

Special thanks to **@JF_Car**, **@ghosthvj**, and **@jonatanc** for their testing, valuable feedback, and suggestions that helped refine the shared resources functionality and improve the overall user experience.



## 2025-08-20

### New version v1.1.5

### Added

- **New Script: Upgrade PVE 8 to PVE 9**  
  Added a full upgrade tool located under `Utilities and Tools`. It provides:
  1. **Automatic upgrade** from PVE 8 to 9
  2. **Interactive upgrade** with step-by-step confirmations
  3. **Check-only mode** using `check-pve8to9`
  4. **Manual instructions** shown in order for users who prefer to upgrade manually

- **New Tools in System Utilities**
  - [`s-tui`](https://github.com/amanusk/s-tui): Terminal-based CPU monitoring with graphs
  - [`intel-gpu-tools`](https://gitlab.freedesktop.org/drm/igt-gpu-tools): Useful for Intel GPU diagnostics

---

### Improved

- **APT Upgrade Handling**  
  The PVE upgrade function now blocks the process if any package prompts for manual confirmation. This avoids partial upgrades and ensures consistency.

- **Network Optimization (sysctl)**  
  - Obsolete kernel parameters removed (e.g., `tcp_tw_recycle`, `nf_conntrack_helper`) to prevent warnings in **Proxmox 9 / kernel 6.14**
  - Now generates only valid, up-to-date sysctl parameters

- **AMD CPU Patch Handling**  
  - Now applies correct `idle=nomwait` and KVM options (`ignore_msrs=1`, `report_ignored_msrs=0`)
  - Expected warning is now documented and safely handled for stability with Ryzen/EPYC

- **Timezone & NTP Fixes**  
  - Automatically detects timezone using public IP geolocation
  - Falls back to UTC if detection fails
  - Restarts Postfix after timezone set → resolves `/var/spool/postfix/etc/localtime` mismatch warning

- **Repository & Package Installer Logic**  
  - Now verifies that working repositories exist before installing any package
  - If none are available, adds a fallback **Debian stable** repository
  - Replaces deprecated `mlocate` with `plocate` (compatible with Debian 13 and Proxmox 9)

- **Improved Logs and User Feedback**  
  - Actions that fail now provide precise messages (instead of falsely marking as success)
  - Helps users clearly understand what's been applied or skipped



## 2025-08-06

### New version v1.1.4

### Added

- **Proxmox 9 Compatibility Preparation**  
  This version prepares **ProxMenux** for the upcoming **Proxmox VE 9**:
  - The function to add the official Proxmox repositories now supports the new `.sources` format used in Proxmox 9, while maintaining backward compatibility with Proxmox 8.
  - Banner removal is now optionally supported for Proxmox 9.

- **xshok-proxmox Detection**  
  Added a check to detect if the `xshok-proxmox` post-install script has already been executed.  
  If detected, a warning is shown to avoid conflicting adjustments:

  ```
  It appears that you have already executed the xshok-proxmox post-install script on this system.

  If you continue, some adjustments may be duplicated or conflict with those already made by xshok.

  Do you want to continue anyway?
  ```

---

### Improved

- **Banner Removal (Proxmox 8.4.9+)**  
  Updated the logic for removing the subscription banner in **Proxmox 8.4.9**, due to changes in `proxmoxlib.js`.

- **LXC Disk Passthrough (Persistent UUID)**  
  The function to add a physical disk to an LXC container now uses **UUID-based persistent paths**.  
  This ensures that disks remain correctly mounted, even if the `/dev/sdX` order changes due to new hardware.

  ```bash
  PERSISTENT_DISK=$(get_persistent_path "$DISK")
  if [[ "$PERSISTENT_DISK" != "$DISK" ]] ...
  ```

- **System Utilities Installer**  
  Now checks whether APT sources are available before installing selected tools.  
  If a new Proxmox installation has no active repos, it will **automatically add the default sources** to avoid installation failure.

- **IOMMU Activation on ZFS Systems**  
  The function that enables IOMMU for passthrough now verifies existing kernel parameters to avoid duplication if the user has already configured them manually.

---

### Fixed

- Minor code cleanup and improved runtime performance across several modules.



## 2025-07-20

### Changed

- **Subscription Banner Removal (Proxmox 8.4.5+)**  
  Improved the `remove_subscription_banner` function to ensure compatibility with Proxmox 8.4.5, where the banner removal method was failing after clean installations.

- **Improved Log2RAM Detection**  
  In both the automatic and customizable post-install scripts, the logic for Log2RAM installation has been improved.  
  Now it correctly detects if Log2RAM is already configured and avoids triggering errors or reconfiguration.

- **Optimized Figurine Installation**  
  The `install_figurine` function now avoids duplicating `.bashrc` entries if the customization for the root prompt already exists.


### Added

- **New Function: Persistent Network Interface Naming**  
  Added a new function `setup_persistent_network` to create stable network interface names using `.link` files based on MAC addresses.  
  This avoids unpredictable renaming (e.g., `enp2s0` becoming `enp3s0`) when hardware changes, PCI topology shifts, or passthrough configurations are applied.

  **Why use `.link` files?**  
  Because predictable interface names in `systemd` can change with hardware reordering or replacement. Using static `.link` files bound to MAC addresses ensures consistency, especially on systems with multiple NICs or passthrough setups.

  Special thanks to [@Andres_Eduardo_Rojas_Moya] for contributing the persistent  
  network naming function and for the original idea.

```bash
[Match]
MACAddress=XX:XX:XX:XX:XX:XX

[Link]
Name=eth0
```


## 2025-07-01

### New version v1.1.3

![Installer Menu](https://macrimi.github.io/ProxMenux/install/install.png)

- **Dual Installation Modes for ProxMenux**  
  The installer now offers two distinct modes:  
  1. **Lite version (no translations):** Only installs two official Debian packages (`dialog`, `jq`) to enable menus and JSON parsing. No files are written beyond the configuration directory.  
  2. **Full version (with translations):** Uses a virtual environment and allows selecting the interface language during installation.  

  When updating, if the user switches from full to lite, the old version will be **automatically removed** for a clean transition.

### Added

- **New Script: Automated Post-Installation Setup**  
  A new minimal post-install script that performs essential setup automatically:  
  - System upgrade and sync  
  - Remove enterprise banner  
  - Optimize APT, journald, logrotate, system limits  
  - Improve kernel panic handling, memory settings, entropy, network  
  - Add `.bashrc` tweaks and **Log2RAM auto-install** (if SSD/M.2 is detected)

- **New Function: Log2RAM Configuration**  
  Now available in both the customizable and automatic post-install scripts.  
  On systems with SSD/NVMe, Log2RAM is **enabled automatically** to preserve disk life.

- **New Menus:**
  - 🧰 **System Utilities Menu**  
    Lets users select and install useful CLI tools with proper command validation.
  - 🌐 **Network Configuration & Repair**  
    A new interactive menu for analyzing and repairing network interfaces.

### Improved

- **Post-Install Menu Logic**  
  Options are now grouped more logically for better usability.

- **VM Creation Menu**  
  Enhanced with improved CPU model support and custom options.

- **UUP Dump ISO Creator Script**  
  - Added option to **customize the temporary folder location**  
  - Fixed issue where entire temp folder was deleted instead of just contents  
    💡 Suggested by [@igrokit](https://github.com/igrokit)  
    [#17](https://github.com/MacRimi/ProxMenux/issues/17), [#11](https://github.com/MacRimi/ProxMenux/issues/11)

- **Physical Disk to LXC Script**  
  Now handles **XFS-formatted disks** correctly.  
  Thanks to [@antroxin](https://github.com/antroxin) for reporting and testing!

- **System Utilities Installer**  
  Rewritten to **verify command availability** after installation, ensuring tools work as expected.  
  🐛 Fix for [#18](https://github.com/MacRimi/ProxMenux/issues/18) by [@DST73](https://github.com/DST73)

### Fixed

- **Enable IOMMU on ZFS**  
  The detection and configuration for enabling IOMMU on ZFS-based systems is now fully functional.  
  🐛 Fix for [#15](https://github.com/MacRimi/ProxMenux/issues/15) by [@troponaut](https://github.com/troponaut)

### Other

- Performance and code cleanup improvements across several modules.



## 2025-06-06

### Added

- **New Menu: Proxmox PVE Helper Scripts**  
  Officially introduced the new **Proxmox PVE Helper Scripts** menu, replacing the previous: Esenciales Proxmox.  
  This new menu includes:
  - Script search by name in real time
  - Category-based browsing

  It’s a cleaner, faster, and more functional way to access community scripts in Proxmox.

  ![Helper Scripts Menu](https://macrimi.github.io/ProxMenux/menu-helpers-script.png)


- **New CPU Models in VM Creation**  
  The CPU selection menu in VM creation has been greatly expanded to support advanced QEMU and x86-64 CPU profiles.  
  This allows better compatibility with modern guest systems and fine-tuning performance for specific workloads, including nested virtualization and hardware-assisted features.


  ![CPU Config](https://macrimi.github.io/ProxMenux/vm/config-cpu.png)

  Thanks to **@Nida Légé (Nidouille)** for suggesting this enhancement.


- **Support for `.raw` Disk Images**  
  The disk import tool for VMs now supports `.raw` files, in addition to `.img`, `.qcow2`, and `.vmdk`.  
  This improves compatibility when working with disk exports from other hypervisors or backup tools.

  💡 Suggested by **@guilloking** in [GitHub Issue #5](https://github.com/MacRimi/ProxMenux/issues/5)


- **Locale Detection in Language Skipping**  
  The function that disables extra APT languages now includes:
  - Automatic locale detection (`LANG`)
  - Auto-generation of `en_US.UTF-8` if none is found
  - Prevents warnings during script execution due to undefined locale


### Improved

- **APT Language Skipping Logic**  
  Improved locale handling ensures system compatibility before disabling translations:
  ```bash
  if ! locale -a | grep -qi "^${default_locale//-/_}$"; then
      echo "$default_locale UTF-8" >> /etc/locale.gen
      locale-gen "$default_locale"
  fi
  ```

- **System Update Speed**  
  Post-install system upgrades are now faster:  
  - The upgrade process (`dist-upgrade`) is separated from container template index updates.
  - Index refresh is now an optional feature selected in the script.



## 2025-05-27

### Fixed
- **Kali Linux ISO URL Updated**  
  Fixed the incorrect download URL for Kali Linux ISO in the Linux installer module. The new correct path is:  
  ```
  https://cdimage.kali.org/kali-2025.1c/kali-linux-2025.1c-installer-amd64.iso
  ```

### Improved
- **Faster Dialog Menu Transitions**  
  Improved UI responsiveness across all interactive menus by replacing `whiptail` with `dialog`, offering faster transitions and smoother navigation.

- **Coral USB Support in LXC**  
  Improved the logic for configuring Coral USB TPU passthrough into LXC containers:
  - Refactored configuration into modular blocks with better structure and inline comments.
  - Clear separation of Coral USB (`/dev/coral`) and Coral M.2 (`/dev/apex_0`) logic.
  - Maintains backward compatibility with existing LXC configurations.
  - Introduced persistent Coral USB passthrough using a udev rule:
    ```bash
    # Create udev rule for Coral USB
    SUBSYSTEM=="usb", ATTRS{idVendor}=="18d1", ATTRS{idProduct}=="9302", MODE="0666", TAG+="uaccess", SYMLINK+="coral"
    
    # Map /dev/coral if it exists
    if [ -e /dev/coral ]; then
        echo "lxc.mount.entry: /dev/coral dev/coral none bind,optional,create=file" >> "$CONFIG_FILE"
    fi
    ```
  - Special thanks to **@Blaspt** for validating the persistent Coral USB passthrough and suggesting the use of `/dev/coral` symbolic link.


### Added
- **Persistent Coral USB Passthrough Support**  
  Added udev rule support for Coral USB devices to persistently map them as `/dev/coral`, enabling consistent passthrough across reboots. This path is automatically detected and mapped in the container configuration.

- **RSS Feed Integration**  
  Added support for generating an RSS feed for the changelog, allowing users to stay informed of updates through news clients.

- **Release Service Automation**  
  Implemented a new release management service to automate publishing and tagging of versions, starting with version **v1.1.2**.


## 2025-05-13

### Fixed

- **Startup Fix on Newer Proxmox Versions**\
  Fixed an issue where some recent Proxmox installations lacked the `/usr/local/bin` directory, causing errors when installing the execution menu. The script now creates the directory if it does not exist before downloading the main menu.\
  Thanks to **@danielmateos** for detecting and reporting this issue.

### Improved

- **Updated Lynis Installation Logic in Post-Install Settings**\
  The `install_lynis()` function was improved to always install the **latest version** of Lynis by cloning the official GitHub repository:
  ```
  https://github.com/CISOfy/lynis.git
  ```
  The installation process now ensures the latest version is always fetched and linked properly within the system path.

  Thanks to **@Kamunhas** for reporting this enhancement opportunity.

- **Balanced Memory Optimization for Low-Memory Systems**  
  Improved the default memory settings to better support systems with limited RAM. The previous configuration could prevent low-spec servers from booting. Now, a more balanced set of kernel parameters is used, and memory compaction is enabled if supported by the system.

  ```bash
  cat <<EOF | sudo tee /etc/sysctl.d/99-memory.conf
  # Balanced Memory Optimization
  vm.swappiness = 10
  vm.dirty_ratio = 15
  vm.dirty_background_ratio = 5
  vm.overcommit_memory = 1
  vm.max_map_count = 65530
  EOF

  # Enable memory compaction if supported by the system
  if [ -f /proc/sys/vm/compaction_proactiveness ]; then
    echo "vm.compaction_proactiveness = 20" | sudo tee -a /etc/sysctl.d/99-memory.conf
  fi

  # Apply settings
  sudo sysctl -p /etc/sysctl.d/99-memory.conf
  ```

  These values help maintain responsiveness and system stability even under constrained memory conditions.

  Thanks to **@chesspeto** for pointing out this issue and helping refine the optimization.


## 2025-05-04

### Added
- **Interactive Help & Info Menu**  
  Added a new script called `Help and Info`, which provides an interactive command reference menu for Proxmox VE through a dialog-based interface.  
  This tool offers users a quick way to browse and copy useful commands for managing and maintaining their Proxmox server, all in one centralized location.

  ![Help and Info Menu](https://macrimi.github.io/ProxMenux/help/help-info-menu.png)

  *Figure 1: Help and Info interactive command reference menu.*

- **Uninstaller for Post-Install Utilities**  
  A new script has been added to the **Post-Installation** menu, allowing users to uninstall utilities or packages that were previously installed through the post-install script.

### Improved
- **Utility Selection Menu in Post-Installation Script**  
  The `Install Common System Utilities` section now includes a menu where users can choose which utilities to install, instead of installing all by default. This gives more control over what gets added to the system.

- **Old PV Header Detection and Auto-Fix**  
  After updating the system, the post-update script now includes a security check for physical disks with outdated LVM PV (Physical Volume) headers.  
  This issue can occur when virtual machines have passthrough access to disks and unintentionally modify volume metadata. The script now detects and automatically updates these headers.  
  If any error occurs during the process, a warning is shown to the user.

- **Faster Translations in Menus**  
  Several post-installation menus with auto-translations have been optimized to reduce loading times and improve user experience.


## 2025-04-14

### Added
- **New Script: Disk Passthrough to a CT**
Introduced a new script that enables assigning a dedicated physical disk to a container (CT) in Proxmox VE.
This utility lists available physical disks (excluding system and mounted disks), allows the user to select a container and one disk, and then formats or reuses the disk before mounting it inside the CT at a specified path.
It supports detection of existing filesystems and ensures permissions are properly configured. Ideal for use cases such as Samba, Nextcloud, or video surveillance containers.

### Improved  
- Visual Identification of Disks for Passthrough to VMs
Enhanced the disk detection logic in the Disk Passthrough to a VM script by including visual indicators and metadata.
Disks now display tags like ⚠ In use, ⚠ RAID, ⚠ LVM, or ⚠ ZFS, making it easier to recognize their current status at a glance. This helps prevent selection mistakes and improves clarity for the user.

## 2025-03-24  
### Improved  
- Improved the logic for detecting physical disks in the **Disk Passthrough to a VM** script. Previously, the script would display disks that were already mounted in the system on some setups. This update ensures that only unmounted disks are shown in Proxmox, preventing confusion and potential conflicts.  

- This improvement ensures that disks already mounted or assigned to other VMs are excluded from the list of available disks, providing a more accurate and reliable selection process.

## [1.1.1] - 2025-03-21
### Improved
- Improved the logic of the post-install script to prevent overwriting or adding duplicate settings if similar settings are already configured by the user.
- Added a warning note to the documentation explaining that using different post-installation scripts is not recommended to avoid conflicts and duplicated settings.

### Added
- **Create Synology DSM VM**:  
  A new script that creates a VM to install Synology DSM. The script automates the process of downloading three different loaders with the option to use a custom loader provided by the user from the local storage options.  
  Additionally, it allows the use of both virtual and physical disks, which are automatically assigned by the script.  

  ![VM description](https://macrimi.github.io/ProxMenux/vm/synology/dsm_desc.png)
  
  *Figure 1: Synology DSM VM setup overview.*

- **New VM Creation Menu**:  
  A new menu has been created to enable VM creation from templates or custom scripts.

- **Main Menu Update**:  
  Added a new entry to the main menu for accessing the VM creation menu from templates or scripts.

## 2025-03-06
### Added
- Completed the web documentation section to expand information on updated scripts.

## [1.1.0] - 2025-03-04
### Added
- Created a customizable post-install script for Proxmox with 10 sections and 35 different selectable options.

## [1.0.7] - 2025-02-17
### Added
- Created a menu with essential scripts from the Proxmox VE Helper-Scripts community.

## [1.0.6] - 2025-02-10
### Added
- Added real-time translation support using Google Translate.
- Modified existing scripts to support multiple languages.
- Updated installation script to install and configure:
  - `jq` (for handling JSON data)
  - Python 3 and virtual environment (required for translations)
  - Google Translate (`googletrans`) (for multi-language support)
- Introduced support for the following languages:
  - English
  - Spanish
  - French
  - German
  - Italian
  - Portuguese
- Created a utility script for auxiliary functions that support the execution of menus and scripts.

## [1.0.5] - 2025-01-31
### Added
- Added the **Repair Network** script, which includes:
  - Verify Network
  - Show IP Information
- Created the **Network Menu** to manage network-related functions.

## [1.0.4] - 2025-01-20
### Added
- Created a script to add a passthrough disk to a VM.
- Created the **Storage Menu** to manage storage-related functions.

## [1.0.3] - 2025-01-13
### Added
- Created a script to import disk images into a VM.

## [1.0.2] - 2025-01-09
### Modified
- Updated the **Coral TPU configuration script** to:
  - Also include Intel iGPU setup.
  - Install GPU drivers for video surveillance applications to support VAAPI and QuickSync.
- Added a function to **uninstall ProxMenux**.

## [1.0.1] - 2025-01-03
### Added
- Created a script to add **Coral TPU support in an LXC** for use in video surveillance programs.

## [1.0.0] - 2024-12-18
### Added
- Initial release of **ProxMenux**.
- Created a script to add **Coral TPU drivers** to Proxmox.
