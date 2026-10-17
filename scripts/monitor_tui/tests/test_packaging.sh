#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
BUILDER="$ROOT/AppImage/scripts/build_appimage.sh"
APP_RUN="$ROOT/AppImage/scripts/AppRun"
grep -Fq 'monitor_console.py' "$BUILDER"
grep -Fq 'proxmenux_monitor_tui.py' "$BUILDER"
grep -Fq 'infocmp -x linux' "$BUILDER"
grep -Fq '"--tui"' "$APP_RUN"
grep -Fq 'exec python3' "$APP_RUN"
grep -Fq 'import curses' "$ROOT/AppImage/scripts/proxmenux_monitor_tui.py"
grep -Fq 'curses.setupterm' "$ROOT/AppImage/scripts/proxmenux_monitor_tui.py"
grep -Fq 'APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0' "$BUILDER"
grep -Fq 'TYPE2_RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d' "$BUILDER"
grep -Fq 'sha256sum -c --status' "$BUILDER"
grep -Fq 'Refusing unsafe build directory' "$BUILDER"
grep -Fq 'npm ci --legacy-peer-deps' "$BUILDER"
grep -Fq 'requirements-monitor.lock' "$BUILDER"
grep -Fq 'setpriv --no-new-privs --reuid=65534' "$ROOT/scripts/monitor_tui/proxmenux-monitor"
grep -Fq 'setpriv --no-new-privs --reuid=65534' "$APP_RUN"
! grep -Fq 'runuser --user nobody' "$ROOT/scripts/monitor_tui/proxmenux-monitor"
! grep -Fq 'runuser --user nobody' "$APP_RUN"
ABI_LINE=$(grep -nF 'export PYTHONPATH="${PYTHON_ABI_DIR}' "$APP_RUN" | cut -d: -f1)
TUI_LINE=$(grep -nF 'if [[ "${1:-}" == "--tui" ]]' "$APP_RUN" | cut -d: -f1)
[[ "$ABI_LINE" -lt "$TUI_LINE" ]]
test -s "$ROOT/AppImage/scripts/requirements-monitor.lock"
grep -Fq -- '--require-hashes' "$BUILDER"
grep -Fq 'Flask==3.1.3' "$ROOT/AppImage/scripts/requirements-monitor.in"
if PROXMENUX_MONITOR_BUILD_DIR=/ bash "$BUILDER" >/dev/null 2>&1; then
    echo "builder accepted an unsafe recursive-delete target" >&2
    exit 1
fi
if PROXMENUX_MONITOR_BUILD_DIR="${QF_ADHOC_DIR:-/tmp}/build" PROXMENUX_MONITOR_DIST_DIR=/ bash "$BUILDER" >/dev/null 2>&1; then
    echo "builder accepted an unsafe AppImage output directory" >&2
    exit 1
fi
grep -Fq 'PYTHON_ABI_DIR' "$APP_RUN"
grep -Fq 'PYTHONPATH="${PYTHON_ABI_DIR}' "$APP_RUN"
grep -Fq 'lifecycle.sh" install' "$ROOT/install_proxmenux.sh"
grep -Fq 'lifecycle.sh" install' "$ROOT/install_proxmenux_beta.sh"
grep -Fq 'cp -r "./scripts/"* "$BASE_DIR/scripts/"' "$ROOT/install_proxmenux.sh"
grep -Fq 'cp -r "./scripts/"* "$BASE_DIR/scripts/"' "$ROOT/install_proxmenux_beta.sh"
tmp=$(mktemp -d "${QF_ADHOC_DIR:-/tmp}/monitor-tui-terminfo.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
infocmp -x linux | tic -x -o "$tmp" -
TERMINFO="$tmp" TERM=linux python3 -c 'import _curses, curses; curses.setupterm(term="linux"); print("_curses and TERM=linux terminfo available")'
if [[ -n "${PROXMENUX_MONITOR_BUILT_APPIMAGE:-}" ]]; then
    package_tmp="$tmp/package"
    mkdir -p "$package_tmp"
    (
        cd "$package_tmp"
        APPIMAGE_EXTRACT_AND_RUN=1 "$PROXMENUX_MONITOR_BUILT_APPIMAGE" --appimage-extract >/dev/null
    )
    packaged="$package_tmp/squashfs-root"
    test -f "$packaged/usr/bin/proxmenux_monitor_tui.py"
    test -f "$packaged/usr/bin/monitor_console.py"
    test -f "$packaged/usr/share/terminfo/l/linux"
    for abi in cp311 cp313; do
        test -f "$packaged/usr/lib/python3/vendor/$abi/flask/__init__.py"
        test -f "$packaged/usr/lib/python3/vendor/$abi/psutil/_psutil_linux.abi3.so"
    done
fi
echo "Monitor TUI packaging fixtures passed"
