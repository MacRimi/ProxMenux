#!/bin/bash

# ProxMenux Monitor AppImage Builder
# This script creates a single AppImage with Flask server, Next.js dashboard, and translation support

set -e

WORK_DIR="/tmp/proxmenux_build"
APP_DIR="$WORK_DIR/ProxMenux.AppDir"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/../dist"
APPIMAGE_ROOT="$SCRIPT_DIR/.."

VERSION=$(node -p "require('$APPIMAGE_ROOT/package.json').version")
APPIMAGE_NAME="ProxMenux-${VERSION}.AppImage"

echo "🚀 Building ProxMenux Monitor AppImage v${VERSION} with hardware monitoring tools..."

# Clean and create work directory
rm -rf "$WORK_DIR"
mkdir -p "$APP_DIR"
mkdir -p "$DIST_DIR"

# Download appimagetool if not exists
if [ ! -f "$WORK_DIR/appimagetool" ]; then
    echo "📥 Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O "$WORK_DIR/appimagetool"
    chmod +x "$WORK_DIR/appimagetool"
fi

# Create directory structure
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/lib/python3/dist-packages"
mkdir -p "$APP_DIR/usr/share/applications"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/web"

echo "🔨 Building Next.js application..."
cd "$APPIMAGE_ROOT"
if [ ! -f "package.json" ]; then
    echo "❌ Error: package.json not found in AppImage directory"
    exit 1
fi

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

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
cp "$SCRIPT_DIR/flask_auth_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_auth_routes.py not found"
cp "$SCRIPT_DIR/auth_manager.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  auth_manager.py not found"
cp "$SCRIPT_DIR/health_monitor.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  health_monitor.py not found"
cp "$SCRIPT_DIR/health_persistence.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  health_persistence.py not found"
cp "$SCRIPT_DIR/flask_health_routes.py" "$APP_DIR/usr/bin/" 2>/dev/null || echo "⚠️  flask_health_routes.py not found"

echo "📋 Adding translation support..."
cat > "$APP_DIR/usr/bin/translate_cli.py" << 'PYEOF'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxMenux translate CLI
stdin JSON -> {"text":"...", "dest_lang":"es", "context":"...", "cache_file":"/usr/local/share/proxmenux/cache.json"}
stdout JSON -> {"success":true,"text":"..."} or {"success":false,"error":"..."}
"""
import sys, json, re
from pathlib import Path

# Ensure embedded site-packages are discoverable
HERE = Path(__file__).resolve().parents[2]  # .../AppDir
DIST = HERE / "usr" / "lib" / "python3" / "dist-packages"
SITE = HERE / "usr" / "lib" / "python3" / "site-packages"
for p in (str(DIST), str(SITE)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Python 3.13 compat: inline 'cgi' shim
try:
    import cgi
except Exception:
    import types, html
    def _parse_header(value: str):
        value = str(value or "")
        parts = [p.strip() for p in value.split(";")]
        if not parts:
            return "", {}
        key = parts[0].lower()
        params = {}
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
    cgi = types.SimpleNamespace(parse_header=_parse_header, escape=html.escape)

try:
    from googletrans import Translator
except Exception as e:
    print(json.dumps({"success": False, "error": f"ImportError: {e}"}))
    sys.exit(0)

def load_json_stdin():
    try:
        return json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(0)

def ensure_cache(path: Path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        path.write_text("{}", encoding="utf-8")

def read_cache(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}

def write_cache(path: Path, cache: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def clean_translated(s: str) -> str:
    s = re.sub(r'^.*?(Translate:|Traducir:|Traduire:|Übersetzen:|Tradurre:|Traduzir:|翻译:|翻訳:)', '', s, flags=re.IGNORECASE | re.DOTALL).strip()
    s = re.sub(r'^.*?(Context:|Contexto:|Contexte:|Kontext:|Contesto:|上下文：|コンテキスト：).*?:', '', s, flags=re.IGNORECASE | re.DOTALL).strip()
    return s.strip()

def main():
    req = load_json_stdin()
    text = req.get("text", "")
    dest = req.get("dest_lang", "en") or "en"
    context = req.get("context", "")
    cache_file = Path(req.get("cache_file", "")) if req.get("cache_file") else None

    if dest == "en":
        print(json.dumps({"success": True, "text": text}))
        return

    cache = {}
    if cache_file:
        ensure_cache(cache_file)
        cache = read_cache(cache_file)
        if text in cache and (dest in cache[text] or "notranslate" in cache[text]):
            found = cache[text].get(dest) or cache[text].get("notranslate")
            print(json.dumps({"success": True, "text": found}))
            return

    try:
        full = (context + " " + text).strip() if context else text
        tr = Translator()
        result = tr.translate(full, dest=dest).text
        result = clean_translated(result)

        if cache_file:
            cache.setdefault(text, {})
            cache[text][dest] = result
            write_cache(cache_file, cache)

        print(json.dumps({"success": True, "text": result}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

if __name__ == "__main__":
    main()
PYEOF

chmod +x "$APP_DIR/usr/bin/translate_cli.py"

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
Comment=Proxmox System Monitoring Dashboard with Translation Support
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
    wget -q "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo.png" -O "$APP_DIR/proxmenux-monitor.png" || {
        echo "⚠️  Could not download logo, creating placeholder..."
        convert -size 256x256 xc:blue -fill white -gravity center -pointsize 24 -annotate +0+0 "PM" "$APP_DIR/proxmenux-monitor.png" 2>/dev/null || {
            echo "⚠️  ImageMagick not available, skipping icon creation"
        }
    }
fi

if [ -f "$APP_DIR/proxmenux-monitor.png" ]; then
    cp "$APP_DIR/proxmenux-monitor.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/"
fi

echo "📦 Installing Python dependencies..."
pip3 install --target "$APP_DIR/usr/lib/python3/dist-packages" \
    flask \
    flask-cors \
    psutil \
    requests \
    PyJWT \
    pyotp \
    segno \
    googletrans==4.0.0-rc1 \
    httpx==0.13.3 \
    httpcore==0.9.1 \
    beautifulsoup4

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
dl_pkg "libupsclient.deb"    "libupsclient6" "libupsclient5" "libupsclient4" || true

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
    libupsclient.so.6) need_pkg="libupsclient6" ;;
    libupsclient.so.5) need_pkg="libupsclient5" ;;
    libupsclient.so.4) need_pkg="libupsclient4" ;;
    *) need_pkg="" ;;
  esac

  if [ -n "$need_pkg" ]; then
    echo "   downloading: $need_pkg"
    dl_pkg "libupsclient_autofix.deb" "$need_pkg" || true
    if [ -f "libupsclient_autofix.deb" ]; then
      dpkg-deb -x "libupsclient_autofix.deb" "$APP_DIR"
      echo "   re-checking ldd for upsc..."
      if ldd "$APP_DIR/usr/bin/upsc" | grep -q 'not found'; then
        echo "❌ upsc still has unresolved libs:"
        ldd "$APP_DIR/usr/bin/upsc" | grep 'not found' || true
        exit 1
      fi
    else
      echo "❌ could not download $need_pkg automatically"
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
ARCH=x86_64 ./appimagetool --no-appstream --verbose "$APP_DIR" "$APPIMAGE_NAME"

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
