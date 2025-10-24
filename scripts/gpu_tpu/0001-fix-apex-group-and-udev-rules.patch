diff --git a/install_coral_pve9.sh b/install_coral_pve9.sh
index 1111111..2222222 100755
--- a/install_coral_pve9.sh
+++ b/install_coral_pve9.sh
@@ -1,5 +1,58 @@
 #!/usr/bin/env bash
 # ==========================================================
 # ProxMenux - Coral TPU Installer for Proxmox VE 9
 # ==========================================================

+# ----------------------------------------------------------
+# Ensure apex group and udev rules are present
+# ----------------------------------------------------------
+ensure_apex_group_and_udev() {
+  msg_info "Ensuring apex group and udev rules..."
+
+  # Create the apex group if it doesn't exist
+  if ! getent group apex >/dev/null; then
+    groupadd --system apex
+    msg_ok "System group 'apex' created"
+  else
+    msg_ok "System group 'apex' already exists"
+  fi
+
+  # Add or replace local udev rule for Coral / APEX TPU
+  cat >/etc/udev/rules.d/99-coral-apex.rules <<'EOF'
+# Coral / Google APEX TPU (M.2 / PCIe)
+# Assigns group "apex" and safe permissions to device nodes
+KERNEL=="apex_*", GROUP="apex", MODE="0660"
+SUBSYSTEM=="apex", GROUP="apex", MODE="0660"
+EOF
+
+  # If gasket-dkms rule exists, make sure it uses the correct group
+  if [[ -f /usr/lib/udev/rules.d/60-gasket-dkms.rules ]]; then
+    sed -i 's/GROUP="[^"]*"/GROUP="apex"/g' /usr/lib/udev/rules.d/60-gasket-dkms.rules || true
+  fi
+
+  # Reload and apply udev rules
+  udevadm control --reload-rules
+  udevadm trigger --subsystem-match=apex || true
+
+  msg_ok "apex group and udev rules are in place"
+
+  # Verify device nodes after reload
+  if ls -l /dev/apex_* 2>/dev/null | grep -q ' apex '; then
+    msg_ok "Coral TPU device nodes detected with correct group (apex)"
+  else
+    msg_warn "apex device node not found yet; a reboot may be required"
+  fi
+}
+
+
@@ -210,6 +263,10 @@ install_coral_host() {
     msg_ok "DKMS module built and installed successfully"
   fi

+  # Ensure group and udev setup before loading drivers
+  ensure_apex_group_and_udev
+
+  # Load kernel modules
   modprobe gasket >>"$LOG_FILE" 2>&1 || true
   modprobe apex   >>"$LOG_FILE" 2>&1 || true
   sleep 1
