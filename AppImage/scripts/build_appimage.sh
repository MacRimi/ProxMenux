#!/bin/bash

# ProxMenux Monitor AppImage Builder
# This script creates a single AppImage with Flask server, Next.js dashboard, and translation support

set -e

WORK_DIR="${PROXMENUX_MONITOR_BUILD_DIR:-/tmp/proxmenux_build}"
DEFAULT_WORK_DIR=/tmp/proxmenux_build
if [[ -n "${QF_ADHOC_DIR:-}" ]]; then
    QF_ADHOC_ROOT=$(realpath -e /srv/quantum-qa/adhoc)
    QF_ADHOC_REAL=$(realpath -e "$QF_ADHOC_DIR")
    if [[ "$QF_ADHOC_REAL" != "$QF_ADHOC_ROOT"/* ||
          "$WORK_DIR" != "$QF_ADHOC_REAL/build" ]]; then
        echo "❌ Refusing unsafe build directory outside the active qf-test adhoc run" >&2
        exit 1
    fi
elif [[ "$WORK_DIR" != "$DEFAULT_WORK_DIR" ]]; then
    echo "❌ Refusing unsafe build directory; use $DEFAULT_WORK_DIR or an active qf-test adhoc run" >&2
    exit 1
fi
APP_DIR="$WORK_DIR/ProxMenux.AppDir"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${PROXMENUX_MONITOR_DIST_DIR:-$SCRIPT_DIR/../dist}"
APPIMAGE_ROOT="$SCRIPT_DIR/.."
if [[ -n "${QF_ADHOC_DIR:-}" ]]; then
    EXPECTED_DIST_DIR="$QF_ADHOC_REAL/artifacts/dist"
    DIST_DIR_REAL=$(realpath -m "$DIST_DIR")
    if [[ "$DIST_DIR_REAL" != "$EXPECTED_DIST_DIR" ]]; then
        echo "❌ Refusing unsafe AppImage output directory outside the active qf-test adhoc run" >&2
        exit 1
    fi
fi

# PVE 8 and PVE 9 execute the AppImage with host CPython 3.11 and 3.13.

VERSION=$(node -p "require('$APPIMAGE_ROOT/package.json').version")
APPIMAGE_NAME="ProxMenux-${VERSION}.AppImage"

echo "🚀 Building ProxMenux Monitor AppImage v${VERSION} with hardware monitoring tools..."

# Cache the downloaded appimagetool across builds. Prefer the XDG user
# cache so this works the same way under root (local .50 build) and
# under the non-root GitHub Actions runner — previously hardcoded to
# /var/cache/, which the CI user can't write to (mkdir Permission
# denied → build aborted before doing any actual work).
APPIMAGETOOL_VERSION=1.9.1
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
TYPE2_RUNTIME_VERSION=20251108
TYPE2_RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
APPIMAGETOOL_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/proxmenux-build/appimagetool-$APPIMAGETOOL_VERSION"
TYPE2_RUNTIME_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/proxmenux-build/runtime-x86_64-$TYPE2_RUNTIME_VERSION"

# Preserve a cached copy of appimagetool across builds. wget -q has bitten
# us repeatedly when GitHub momentarily rate-limits or the runner has no
# network — the result is a 0-byte file that passes the `[ -f ]` check on
# the next run and breaks the build silently.
if [ -f "$WORK_DIR/appimagetool" ] && [ -s "$WORK_DIR/appimagetool" ] && \
   echo "$APPIMAGETOOL_SHA256  $WORK_DIR/appimagetool" | sha256sum -c --status; then
    mkdir -p "$(dirname "$APPIMAGETOOL_CACHE")"
    cp -f "$WORK_DIR/appimagetool" "$APPIMAGETOOL_CACHE"
fi
if [ -f "$WORK_DIR/runtime-x86_64" ] && [ -s "$WORK_DIR/runtime-x86_64" ] && \
   echo "$TYPE2_RUNTIME_SHA256  $WORK_DIR/runtime-x86_64" | sha256sum -c --status; then
    mkdir -p "$(dirname "$TYPE2_RUNTIME_CACHE")"
    cp -f "$WORK_DIR/runtime-x86_64" "$TYPE2_RUNTIME_CACHE"
fi

# Clean and create work directory
rm -rf "$WORK_DIR"
mkdir -p "$APP_DIR"
mkdir -p "$DIST_DIR"

# appimagetool 1.9.1 otherwise fetches a moving runtime at package time.
# Pin and verify it; reuse a verified cache for offline rebuilds.
if [ -s "$TYPE2_RUNTIME_CACHE" ] && \
   echo "$TYPE2_RUNTIME_SHA256  $TYPE2_RUNTIME_CACHE" | sha256sum -c --status; then
    cp "$TYPE2_RUNTIME_CACHE" "$WORK_DIR/runtime-x86_64"
else
    wget --tries=3 --timeout=60 \
        "https://github.com/AppImage/type2-runtime/releases/download/$TYPE2_RUNTIME_VERSION/runtime-x86_64" \
        -O "$WORK_DIR/runtime-x86_64"
    if ! echo "$TYPE2_RUNTIME_SHA256  $WORK_DIR/runtime-x86_64" | sha256sum -c --status; then
        echo "❌ AppImage runtime SHA256 verification failed" >&2
        rm -f "$WORK_DIR/runtime-x86_64"
        exit 1
    fi
    mkdir -p "$(dirname "$TYPE2_RUNTIME_CACHE")"
    cp -f "$WORK_DIR/runtime-x86_64" "$TYPE2_RUNTIME_CACHE"
fi

# Restore appimagetool from cache if available, otherwise download.
if [ -s "$APPIMAGETOOL_CACHE" ] && \
   echo "$APPIMAGETOOL_SHA256  $APPIMAGETOOL_CACHE" | sha256sum -c --status; then
    echo "📦 Reusing cached appimagetool"
    cp "$APPIMAGETOOL_CACHE" "$WORK_DIR/appimagetool"
    chmod +x "$WORK_DIR/appimagetool"
fi
if [ ! -s "$WORK_DIR/appimagetool" ] || \
   ! echo "$APPIMAGETOOL_SHA256  $WORK_DIR/appimagetool" | sha256sum -c --status; then
    echo "📥 Downloading appimagetool..."
    rm -f "$WORK_DIR/appimagetool"
    wget --tries=3 --timeout=60 "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage" -O "$WORK_DIR/appimagetool" || true
    if [ ! -s "$WORK_DIR/appimagetool" ]; then
        echo "❌ Failed to download appimagetool" >&2
        exit 1
    fi
    if ! echo "$APPIMAGETOOL_SHA256  $WORK_DIR/appimagetool" | sha256sum -c --status; then
        echo "❌ appimagetool SHA256 verification failed" >&2
        rm -f "$WORK_DIR/appimagetool"
        exit 1
    fi
    chmod +x "$WORK_DIR/appimagetool"
    mkdir -p "$(dirname "$APPIMAGETOOL_CACHE")"
    cp -f "$WORK_DIR/appimagetool" "$APPIMAGETOOL_CACHE"
fi

# Create directory structure
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/lib/python3/dist-packages"
mkdir -p "$APP_DIR/usr/lib/python3/vendor"
mkdir -p "$APP_DIR/usr/share/applications"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/web"

# Ship the Linux virtual-console terminfo entry used by Proxmox local consoles.
# _curses is supplied by the host's already-required CPython runtime; no host
# package is installed by ProxMenux. Build validation checks that runtime.
if command -v infocmp >/dev/null 2>&1 && command -v tic >/dev/null 2>&1; then
    mkdir -p "$APP_DIR/usr/share/terminfo"
    infocmp -x linux | tic -x -o "$APP_DIR/usr/share/terminfo" -
else
    echo "❌ infocmp/tic are required to package the TERM=linux console entry" >&2
    exit 1
fi
if ! TERMINFO="$APP_DIR/usr/share/terminfo" TERM=linux python3 -c \
    'import _curses, curses; curses.setupterm(term="linux"); assert _curses' >/dev/null 2>&1; then
    echo "❌ Python _curses cannot load the packaged TERM=linux entry" >&2
    exit 1
fi

echo "🔨 Building Next.js application..."
cd "$APPIMAGE_ROOT"
if [ ! -f "package.json" ]; then
    echo "❌ Error: package.json not found in AppImage directory"
    exit 1
fi

# Always reconcile node_modules against the lockfile. The previous
# guard (`if [ ! -d "node_modules" ]`) skipped install when an older
# tree existed on disk — so a bump in package.json silently shipped
# with the cached version. We hit this when bumping Next.js
# 15.1.6 -> 15.1.9 for CVE-2025-55182: the build succeeded with the
# stale node_modules and the AppImage still carried 15.1.6. `npm ci`
# enforces the committed lockfile and fails on any mismatch. `--legacy-peer-deps` is required
# because vaul@0.9.9 (and a few others) still declare peer-deps for
# React ≤18 while we are on React 19; npm 7+ refuses by default.
# The actual runtime works fine with React 19.
echo "📦 Reconciling dependencies against the lockfile..."
npm ci --legacy-peer-deps

echo "🏗️  Building Next.js static export..."
npm run export

echo "🔍 Checking export results..."
if [ -d "out" ]; then
    echo "✅ Export directory found"
    echo "📁 Contents of out directory:"
    ls -la out/
    if [ -f "out/index.html" ]; then
        echo "✅ index.html found in out directory"
    else
        echo "❌ index.html NOT found in out directory"
        echo "📁 Looking for HTML files:"
        find out/ -name "*.html" -type f || echo "No HTML files found"
    fi
else
    echo "❌ Error: Next.js export failed - out directory not found"
    echo "📁 Current directory contents:"
    ls -la
    echo "📁 Looking for any build outputs:"
    find . -name "*.html" -type f 2>/dev/null || echo "No HTML files found anywhere"
    exit 1
fi

# Return to script directory
cd "$SCRIPT_DIR"

# Copy Flask server
echo "📋 Copying Flask server..."
cp "$SCRIPT_DIR/flask_server.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/monitor_console.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/proxmenux_monitor_tui.py" "$APP_DIR/usr/bin/"
chmod 0755 "$APP_DIR/usr/bin/proxmenux_monitor_tui.py"
cp "$SCRIPT_DIR/flask_auth_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_auth_routes.py not found"
cp "$SCRIPT_DIR/auth_manager.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  auth_manager.py not found"
cp "$SCRIPT_DIR/jwt_middleware.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  jwt_middleware.py not found"
cp "$SCRIPT_DIR/health_monitor.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  health_monitor.py not found"
cp "$SCRIPT_DIR/health_persistence.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  health_persistence.py not found"
cp "$SCRIPT_DIR/flask_health_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_health_routes.py not found"
cp "$SCRIPT_DIR/flask_proxmenux_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_proxmenux_routes.py not found"
cp "$SCRIPT_DIR/post_install_versions.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  post_install_versions.py not found"
cp "$SCRIPT_DIR/mount_monitor.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  mount_monitor.py not found"
cp "$SCRIPT_DIR/lxc_mount_points.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  lxc_mount_points.py not found"
cp "$SCRIPT_DIR/oci_console_logs.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  oci_console_logs.py not found"
cp "$SCRIPT_DIR/oci_instance_info.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  oci_instance_info.py not found"
cp "$SCRIPT_DIR/oci_operations.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  oci_operations.py not found"
cp "$SCRIPT_DIR/disk_temperature_history.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  disk_temperature_history.py not found"
cp "$SCRIPT_DIR/lvm_device_scope.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/smartctl_resolver.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  smartctl_resolver.py not found"
cp "$SCRIPT_DIR/disk_identity.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  disk_identity.py not found"
cp "$SCRIPT_DIR/health_thresholds.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  health_thresholds.py not found"
cp "$SCRIPT_DIR/managed_installs.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  managed_installs.py not found"
cp "$SCRIPT_DIR/lxc_update_observation.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/lxc_update_finalization.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/lxc_check_job.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/lxc_apps.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  lxc_apps.py not found"
cp "$SCRIPT_DIR/custom_links.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  custom_links.py not found"
cp "$SCRIPT_DIR/recreate_docker_container.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  recreate_docker_container.py not found"
chmod +x "$APP_DIR/usr/bin/recreate_docker_container.py" 2>/dev/null || true
cp "$SCRIPT_DIR/update_docker_engine.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  update_docker_engine.py not found"
chmod +x "$APP_DIR/usr/bin/update_docker_engine.py" 2>/dev/null || true
cp "$APPIMAGE_ROOT/../json/app_tracking_hints.json" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  app_tracking_hints.json not found"
cp "$APPIMAGE_ROOT/../json/runtime_verified_overrides.json" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  runtime_verified_overrides.json not found"
cp "$SCRIPT_DIR/flask_terminal_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_terminal_routes.py not found"
cp "$SCRIPT_DIR/hardware_monitor.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  hardware_monitor.py not found"
cp "$SCRIPT_DIR/temperature_sensor_resolver.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  temperature_sensor_resolver.py not found"
cp "$SCRIPT_DIR/proxmox_storage_monitor.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  proxmox_storage_monitor.py not found"
cp "$SCRIPT_DIR/pbs_manager.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/flask_pbs_routes.py" "$APP_DIR/usr/bin/"
cp "$APPIMAGE_ROOT/../scripts/global/proxmox_platform.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/flask_script_runner.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_script_runner.py not found"
cp "$SCRIPT_DIR/security_manager.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  security_manager.py not found"
cp "$SCRIPT_DIR/flask_security_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_security_routes.py not found"
cp "$SCRIPT_DIR/notification_manager.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  notification_manager.py not found"
cp "$SCRIPT_DIR/notification_channels.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  notification_channels.py not found"
cp "$SCRIPT_DIR/notification_templates.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  notification_templates.py not found"
cp "$SCRIPT_DIR/notification_events.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  notification_events.py not found"
cp "$SCRIPT_DIR/proxmox_known_errors.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  proxmox_known_errors.py not found"
cp "$SCRIPT_DIR/ai_context_enrichment.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  ai_context_enrichment.py not found"
cp "$SCRIPT_DIR/startup_grace.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  startup_grace.py not found"
cp "$SCRIPT_DIR/flask_notification_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_notification_routes.py not found"
# Backend notification rendering reuses the canonical Monitor catalogs.
# Keep every supported locale in the bundle so the runtime selector and its
# fallback behavior exactly match the Monitor UI.
for locale in en de es fr it pt sk sv; do
    mkdir -p "$APP_DIR/usr/share/proxmenux/messages/$locale"
    cp "$APPIMAGE_ROOT/messages/$locale/common.json" "$APP_DIR/usr/share/proxmenux/messages/$locale/common.json"
done
cp "$SCRIPT_DIR/oci_manager.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  oci_manager.py not found"
cp "$SCRIPT_DIR/flask_oci_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_oci_routes.py not found"
cp "$SCRIPT_DIR/flask_vm_backup_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_vm_backup_routes.py not found"
cp "$SCRIPT_DIR/guest_backup_archives.py" "$APP_DIR/usr/bin/"
cp "$SCRIPT_DIR/flask_audit_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_audit_routes.py not found"
cp "$SCRIPT_DIR/audit_store.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  audit_store.py not found"
cp "$SCRIPT_DIR/audit_checks.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  audit_checks.py not found"
cp "$SCRIPT_DIR/audit_profiles.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  audit_profiles.py not found"
cp "$SCRIPT_DIR/audit_policy.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  audit_policy.py not found"
cp "$SCRIPT_DIR/changes_journal.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  changes_journal.py not found"
cp "$SCRIPT_DIR/audit_inventory.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  audit_inventory.py not found"
cp "$SCRIPT_DIR/audit_checks_pve.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  audit_checks_pve.py not found"
# Preserve the existing build version as assessment provenance; no version bump.
cp "$APPIMAGE_ROOT/package.json" "$APP_DIR/package.json"
cp "$SCRIPT_DIR/oci/description_templates.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  description_templates.py not found"

# Copy AI providers module for notification enhancement
echo "📋 Copying AI providers module..."
if [ -d "$SCRIPT_DIR/ai_providers" ]; then
    mkdir -p "$APP_DIR/usr/bin/ai_providers"
    cp "$SCRIPT_DIR/ai_providers/"*.py "$APP_DIR/usr/bin/ai_providers/"
    echo "✅ AI providers module copied"
else
    echo "⚠️  ai_providers directory not found"
fi

# Copy config files (verified AI models, prompts, etc.)
echo "📋 Copying config files..."
CONFIG_DIR="$APPIMAGE_ROOT/config"
if [ -d "$CONFIG_DIR" ]; then
    mkdir -p "$APP_DIR/usr/bin/config"
    cp "$CONFIG_DIR/"*.json "$APP_DIR/usr/bin/config/" 2>/dev/null || true
    cp "$CONFIG_DIR/"*.txt "$APP_DIR/usr/bin/config/" 2>/dev/null || true
    echo "✅ Config files copied"
else
    echo "⚠️  config directory not found"
fi

# Translation handling lives in scripts/utils.sh now. It reads
# /usr/local/share/proxmenux/lang/<lang>.json (pre-built by the
# build_translation_cache.py CI job) and falls back to the English
# source string on miss. The Monitor AppImage no longer ships the
# runtime translate_cli.py — the JSON files belong to the host install,
# not to the Flask dashboard.

# ── Borg standalone binary ─────────────────────────────────────────
# Ship the official borg standalone binary inside the AppImage so the
# host-backup / restore workflows can run without an internet round-trip
# at install time. Pinned to the same version that proxmenux's
# hb_ensure_borg used to download on demand — kept in lockstep so both
# code paths see the same version semantics. SHA256 is the upstream
# release checksum; bump both together.
BORG_VERSION="1.2.8"
BORG_URL="https://github.com/borgbackup/borg/releases/download/${BORG_VERSION}/borg-linux64"
BORG_SHA256="cfa50fb704a93d3a4fa258120966345fddb394f960dca7c47fcb774d0172f40b"
echo "📦 Downloading borg ${BORG_VERSION} into AppImage..."
BORG_TARGET="$APP_DIR/usr/bin/borg"
# GitHub releases serve borg-linux64 via a 302 redirect to a signed
# release-assets.githubusercontent.com URL. wget -qO silently dropped
# the redirect once during the 2026-06-15 build, killing the AppImage
# pipeline. curl -L --retry 3 is more robust and falls back to wget
# only when curl is missing.
if command -v curl >/dev/null 2>&1; then
    DOWNLOAD_OK=0
    if curl -sSL --retry 3 --retry-delay 2 --max-time 120 -o "$BORG_TARGET" "$BORG_URL"; then
        DOWNLOAD_OK=1
    fi
else
    DOWNLOAD_OK=0
    if wget -qO "$BORG_TARGET" "$BORG_URL"; then
        DOWNLOAD_OK=1
    fi
fi
if [ "$DOWNLOAD_OK" = "1" ]; then
    if echo "${BORG_SHA256}  ${BORG_TARGET}" | sha256sum -c - >/dev/null 2>&1; then
        chmod +x "$BORG_TARGET"
        echo "✅ borg ${BORG_VERSION} bundled (sha256 verified)"
    else
        echo "❌ borg sha256 verification failed — removing"
        rm -f "$BORG_TARGET"
        exit 1
    fi
else
    echo "❌ borg download failed from $BORG_URL"
    exit 1
fi

# Copy Next.js build
echo "📋 Copying web dashboard..."
if [ -d "$APPIMAGE_ROOT/out" ]; then
    mkdir -p "$APP_DIR/web"
    echo "📁 Copying from $APPIMAGE_ROOT/out to $APP_DIR/web"
    cp -r "$APPIMAGE_ROOT/out"/* "$APP_DIR/web/"
    
    if [ -f "$APP_DIR/web/index.html" ]; then
        echo "✅ index.html copied successfully to $APP_DIR/web/"
    else
        echo "❌ index.html NOT found after copying"
        echo "📁 Contents of $APP_DIR/web:"
        ls -la "$APP_DIR/web/" || echo "Directory is empty or doesn't exist"
    fi
    
    if [ -d "$APPIMAGE_ROOT/public" ]; then
        cp -r "$APPIMAGE_ROOT/public"/* "$APP_DIR/web/" 2>/dev/null || true
    fi
    cp "$APPIMAGE_ROOT/package.json" "$APP_DIR/web/"
    
    echo "✅ Next.js static export copied successfully"
else
    echo "❌ Error: Next.js export not found even after building"
    exit 1
fi

# Copy AppRun script
echo "📋 Copying AppRun script..."
if [ -f "$SCRIPT_DIR/AppRun" ]; then
    cp "$SCRIPT_DIR/AppRun" "$APP_DIR/AppRun"
    chmod +x "$APP_DIR/AppRun"
    echo "✅ AppRun script copied successfully"
else
    echo "❌ Error: AppRun script not found at $SCRIPT_DIR/AppRun"
    exit 1
fi

# Create desktop file
cat > "$APP_DIR/proxmenux-monitor.desktop" << EOF
[Desktop Entry]
Type=Application
Name=ProxMenux Monitor
Comment=Proxmox System Monitoring Dashboard
Exec=AppRun
Icon=proxmenux-monitor
Categories=System;Monitor;
Terminal=false
StartupNotify=true
EOF

# Copy desktop file to applications directory
cp "$APP_DIR/proxmenux-monitor.desktop" "$APP_DIR/usr/share/applications/"

# Download and set icon
echo "🎨 Setting up icon..."
if [ -f "$APPIMAGE_ROOT/public/images/proxmenux-logo.png" ]; then
    cp "$APPIMAGE_ROOT/public/images/proxmenux-logo.png" "$APP_DIR/proxmenux-monitor.png"
else
    echo "⚠️  Local Monitor logo not found; building without an icon."
fi

if [ -f "$APP_DIR/proxmenux-monitor.png" ]; then
    cp "$APP_DIR/proxmenux-monitor.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/"
fi

echo "📦 Installing Python dependencies..."
# Install the complete hash-locked runtime separately for each supported ABI.
# This keeps native extensions from the build runner out of PVE's Python trees.
install_monitor_runtime() {
    local python_version="$1"
    local abi="$2"
    local target="$APP_DIR/usr/lib/python3/vendor/$abi"

    echo "📦 Installing hash-locked Python runtime for ${abi} (Python ${python_version})..."
    mkdir -p "$target"
    python3 -m pip install \
        --disable-pip-version-check \
        --target "$target" \
        --upgrade \
        --only-binary=:all: \
        --platform manylinux_2_28_x86_64 \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version "$python_version" \
        --abi "$abi" \
        --no-deps \
        --require-hashes \
        -r "$SCRIPT_DIR/requirements-monitor.lock"
}

install_monitor_runtime "3.11" "cp311"
install_monitor_runtime "3.13" "cp313"

echo "🔍 Verifying bundled Python ABI extensions..."
for abi in cp311 cp313; do
    abi_digits="${abi#cp}"
    abi_dir="$APP_DIR/usr/lib/python3/vendor/$abi"
    for extension in \
        "gevent/_gevent_c_hub_local.cpython-${abi_digits}-*.so" \
        "greenlet/_greenlet.cpython-${abi_digits}-*.so" \
        "zope/interface/_zope_interface_coptimizations.cpython-${abi_digits}-*.so"; do
        if ! compgen -G "$abi_dir/$extension" >/dev/null; then
            echo "❌ Missing ${abi} extension: ${extension}" >&2
            exit 1
        fi
    done
    if [ ! -f "$abi_dir/geventwebsocket/__init__.py" ]; then
        echo "❌ Missing gevent-websocket runtime for ${abi}" >&2
        exit 1
    fi
    if ! compgen -G "$abi_dir/psutil/_psutil_linux.abi3.so" >/dev/null; then
        echo "❌ Missing ABI-compatible psutil extension for ${abi}" >&2
        exit 1
    fi
    echo "  ✅ ${abi} runtime complete"
done

cat > "$APP_DIR/usr/lib/python3/dist-packages/cgi.py" << 'PYEOF'
from typing import Tuple, Dict
try:
    from html import escape as _html_escape
except Exception:
    def _html_escape(s, quote=True): return s

__all__ = ["parse_header", "escape"]

def escape(s, quote=True):
    return _html_escape(s, quote=quote)

def parse_header(value: str) -> Tuple[str, Dict[str, str]]:
    if not isinstance(value, str):
        value = str(value or "")
    parts = [p.strip() for p in value.split(";")]
    if not parts:
        return "", {}
    key = parts[0].lower()
    params: Dict[str, str] = {}
    for item in parts[1:]:
        if not item:
            continue
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip().lower()
            v = v.strip().strip('"').strip("'")
            params[k] = v
        else:
            params[item.strip().lower()] = ""
    return key, params
PYEOF

echo "🔧 Installing hardware monitoring tools..."
mkdir -p "$WORK_DIR/debs"
cd "$WORK_DIR/debs"

echo "📥 Downloading hardware monitoring tools (dynamic via APT)..."

dl_pkg() {
  local out="$1"; shift
  local pkg deb_file
  for pkg in "$@"; do
    echo "  - trying: $pkg"
    if apt-get download -y "$pkg" >/dev/null 2>&1; then
      deb_file="$(ls -1 ${pkg}_*.deb 2>/dev/null | head -n1)"
      if [ -n "$deb_file" ] && [ -f "$deb_file" ]; then
        mv "$deb_file" "$out"
        echo "    ✅ downloaded: $pkg -> $out"
        return 0
      fi
    fi
  done

  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    echo "  ↻ retry with sudo apt-get update && download"
    sudo apt-get update -qq || true
    for pkg in "$@"; do
      echo "  - trying (sudo): $pkg"
      if sudo apt-get download -y "$pkg" >/dev/null 2>&1; then
        deb_file="$(ls -1 ${pkg}_*.deb 2>/dev/null | head -n1)"
        if [ -n "$deb_file" ] && [ -f "$deb_file" ]; then
          mv "$deb_file" "$out"
          echo "    ✅ downloaded (sudo): $pkg -> $out"
          return 0
        fi
      fi
    done
  fi
  echo "    ⚠️  none of the candidates could be downloaded for $out"
  return 1
}

dl_pkg "ipmitool.deb"        "ipmitool"                         || true
dl_pkg "libfreeipmi17.deb"   "libfreeipmi17"                    || true
dl_pkg "lm-sensors.deb"      "lm-sensors"                       || true
dl_pkg "nut-client.deb"      "nut-client"                       || true
dl_pkg "libupsclient.deb"    "libupsclient6t64" "libupsclient6" "libupsclient5" "libupsclient4" || true

echo "📦 Extracting .deb packages into AppDir..."
extracted_count=0
shopt -s nullglob
for deb in *.deb; do
  echo "  -> $deb"
  if file "$deb" | grep -q "Debian binary package"; then
    dpkg-deb -x "$deb" "$APP_DIR" && extracted_count=$((extracted_count + 1))
  else
    echo "    ⚠️  $deb is not a valid .deb, skipping"
  fi
done
shopt -u nullglob

if [ $extracted_count -eq 0 ]; then
  echo "⚠️  No packages extracted; hardware/GPU monitoring may be unavailable"
else
  echo "✅ Extracted $extracted_count package(s)"
fi

if [ -d "$APP_DIR/bin" ]; then
  echo "📋 Normalizing /bin -> /usr/bin"
  mkdir -p "$APP_DIR/usr/bin"
  cp -r "$APP_DIR/bin/"* "$APP_DIR/usr/bin/" 2>/dev/null || true
  rm -rf "$APP_DIR/bin"
fi

echo "🔍 Sanity check (ldd + presence of libfreeipmi)"
export LD_LIBRARY_PATH="$APP_DIR/lib:$APP_DIR/lib/x86_64-linux-gnu:$APP_DIR/usr/lib:$APP_DIR/usr/lib/x86_64-linux-gnu"

if ! find "$APP_DIR/usr/lib" "$APP_DIR/lib" -maxdepth 3 -name 'libfreeipmi.so.17*' | grep -q .; then
  echo "❌ libfreeipmi.so.17 not found inside AppDir (ipmitool will fail)"
  exit 1
fi

if [ -x "$APP_DIR/usr/bin/ipmitool" ] && ldd "$APP_DIR/usr/bin/ipmitool" | grep -q 'not found'; then
  echo "❌ ipmitool has unresolved libs:"
  ldd "$APP_DIR/usr/bin/ipmitool" | grep 'not found' || true
  exit 1
fi

if [ -x "$APP_DIR/usr/bin/upsc" ] && ldd "$APP_DIR/usr/bin/upsc" | grep -q 'not found'; then
  echo "⚠️ upsc has unresolved libs, trying to auto-fix..."
  missing="$(ldd "$APP_DIR/usr/bin/upsc" | awk '/not found/{print $1}' | tr -d ' ')"
  echo "   missing: $missing"
  case "$missing" in
    # Debian 13+ ships the t64 transitional package — try it first.
    libupsclient.so.6) need_pkgs="libupsclient6t64 libupsclient6" ;;
    libupsclient.so.5) need_pkgs="libupsclient5" ;;
    libupsclient.so.4) need_pkgs="libupsclient4" ;;
    *) need_pkgs="" ;;
  esac

  if [ -n "$need_pkgs" ]; then
    echo "   downloading: $need_pkgs"
    dl_pkg "libupsclient_autofix.deb" $need_pkgs || true
    if [ -f "libupsclient_autofix.deb" ]; then
      dpkg-deb -x "libupsclient_autofix.deb" "$APP_DIR"
      echo "   re-checking ldd for upsc..."
      if ldd "$APP_DIR/usr/bin/upsc" | grep -q 'not found'; then
        echo "❌ upsc still has unresolved libs:"
        ldd "$APP_DIR/usr/bin/upsc" | grep 'not found' || true
        exit 1
      fi
    else
      echo "❌ could not download any of: $need_pkgs"
      exit 1
    fi
  else
    echo "❌ unknown missing library for upsc: $missing"
    exit 1
  fi
fi

echo "✅ Sanity check OK (ipmitool/upsc ready; libfreeipmi present)"

# Info rápida
[ -x "$APP_DIR/usr/bin/sensors" ]         && echo "  • sensors: OK"            || echo "  • sensors: missing"
[ -x "$APP_DIR/usr/bin/ipmitool" ]        && echo "  • ipmitool: OK"           || echo "  • ipmitool: missing"
[ -x "$APP_DIR/usr/bin/upsc" ]            && echo "  • upsc: OK"               || echo "  • upsc: missing"
[ -x "$APP_DIR/usr/bin/nvidia-smi" ]      && echo "  • nvidia-smi: OK"         || echo "  • nvidia-smi: missing"
[ -x "$APP_DIR/usr/bin/intel_gpu_top" ]   && echo "  • intel-gpu-tools: OK"    || echo "  • intel-gpu-tools: missing"
[ -x "$APP_DIR/usr/bin/radeontop" ]       && echo "  • radeontop: OK"          || echo "  • radeontop: missing"

# Build AppImage
echo "🔨 Building unified AppImage v${VERSION}..."
cd "$WORK_DIR"
export NO_CLEANUP=1
export APPIMAGE_EXTRACT_AND_RUN=1
ARCH=x86_64 ./appimagetool --no-appstream --verbose \
    --runtime-file "$WORK_DIR/runtime-x86_64" "$APP_DIR" "$APPIMAGE_NAME"

# Move to dist directory
mv "$APPIMAGE_NAME" "$DIST_DIR/"

echo "✅ Unified AppImage created: $DIST_DIR/$APPIMAGE_NAME"
echo ""
echo "📋 Usage:"
echo "   Dashboard: ./$APPIMAGE_NAME"
echo "   Translation: ./$APPIMAGE_NAME --translate"
echo ""
echo "🚀 Installation:"
echo "   sudo cp $DIST_DIR/$APPIMAGE_NAME /usr/local/bin/proxmenux-monitor"
echo "   sudo chmod +x /usr/local/bin/proxmenux-monitor"
