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

# Download .deb packages with better error handling
echo "📥 Downloading hardware monitoring tools..."

# Function to download and verify .deb package
download_deb() {
    local url=$1
    local output=$2
    local name=$3
    
    echo "  Downloading $name..."
    if wget -q --timeout=30 "$url" -O "$output"; then
        # Verify it's a valid .deb file
        if file "$output" | grep -q "Debian binary package"; then
            echo "  ✅ $name downloaded successfully"
            return 0
        else
            echo "  ⚠️  $name: Invalid .deb file, skipping"
            rm -f "$output"
            return 1
        fi
    else
        echo "  ⚠️  $name: Download failed, skipping"
        rm -f "$output"
        return 1
    fi
}

# Try to download packages (non-fatal if they fail)
download_deb "http://deb.debian.org/debian/pool/main/i/ipmitool/ipmitool_1.8.19-4+deb12u2_amd64.deb" "ipmitool.deb" "ipmitool" || true
download_deb "http://deb.debian.org/debian/pool/main/f/freeipmi/libfreeipmi17_1.6.10-3_amd64.deb" "libfreeipmi17.deb" "libfreeipmi17" || true
download_deb "http://deb.debian.org/debian/pool/main/l/lm-sensors/lm-sensors_3.6.0-7.1_amd64.deb" "lm-sensors.deb" "lm-sensors" || true
download_deb "http://deb.debian.org/debian/pool/main/n/nut/nut-client_2.8.0-7_amd64.deb" "nut-client.deb" "nut-client" || true
download_deb "http://deb.debian.org/debian/pool/main/n/nut/libupsclient6_2.8.0-7_amd64.deb" "libupsclient6.deb" "libupsclient6" || true

# Extract binaries from .deb packages
echo "📦 Extracting binaries from downloaded packages..."
extracted_count=0
for deb in *.deb; do
    if [ -f "$deb" ] && file "$deb" | grep -q "Debian binary package"; then
        echo "  Extracting $deb..."
        dpkg-deb -x "$deb" "$WORK_DIR/extracted" && extracted_count=$((extracted_count + 1))
    fi
done

if [ $extracted_count -eq 0 ]; then
    echo "⚠️  No hardware monitoring tools were downloaded successfully"
    echo "   The AppImage will work but without IPMI/sensors support"
else
    echo "✅ Extracted $extracted_count package(s)"
    
    # Copy binaries to AppDir
    echo "📋 Copying monitoring tools to AppDir..."
    
    # Copy from usr/bin
    if [ -d "$WORK_DIR/extracted/usr/bin" ]; then
        cp -r "$WORK_DIR/extracted/usr/bin"/* "$APP_DIR/usr/bin/" 2>/dev/null || true
    fi
    
    # Copy from usr/sbin
    if [ -d "$WORK_DIR/extracted/usr/sbin" ]; then
        cp -r "$WORK_DIR/extracted/usr/sbin"/* "$APP_DIR/usr/bin/" 2>/dev/null || true
    fi
    
    if [ -d "$WORK_DIR/extracted/bin" ]; then
        echo "  Moving binaries from /bin to usr/bin..."
        cp -r "$WORK_DIR/extracted/bin"/* "$APP_DIR/usr/bin/" 2>/dev/null || true
    fi
    
    if [ -d "$WORK_DIR/extracted/usr/lib" ]; then
        mkdir -p "$APP_DIR/usr/lib"
        cp -r "$WORK_DIR/extracted/usr/lib"/* "$APP_DIR/usr/lib/" 2>/dev/null || true
    fi
    
    if [ -d "$WORK_DIR/extracted/lib" ]; then
        mkdir -p "$APP_DIR/usr/lib"
        cp -r "$WORK_DIR/extracted/lib"/* "$APP_DIR/usr/lib/" 2>/dev/null || true
    fi
    
    if [ -d "$APP_DIR/usr/lib/x86_64-linux-gnu" ]; then
        echo "  Creating library symlinks..."
        
        # Link libupsclient
        if [ -f "$APP_DIR/usr/lib/x86_64-linux-gnu/libupsclient.so.6" ]; then
            ln -sf "$APP_DIR/usr/lib/x86_64-linux-gnu/libupsclient.so.6" "$APP_DIR/usr/lib/libupsclient.so.6" 2>/dev/null || true
            ln -sf "x86_64-linux-gnu/libupsclient.so.6" "$APP_DIR/usr/lib/x86_64-linux-gnu/libupsclient.so" 2>/dev/null || true
        fi
        
        # Link libfreeipmi - create multiple symlinks to ensure it's found
        if [ -f "$APP_DIR/usr/lib/x86_64-linux-gnu/libfreeipmi.so.17" ]; then
            echo "  ✅ Found libfreeipmi.so.17, creating symlinks..."
            ln -sf "$APP_DIR/usr/lib/x86_64-linux-gnu/libfreeipmi.so.17" "$APP_DIR/usr/lib/libfreeipmi.so.17" 2>/dev/null || true
            ln -sf "x86_64-linux-gnu/libfreeipmi.so.17" "$APP_DIR/usr/lib/x86_64-linux-gnu/libfreeipmi.so" 2>/dev/null || true
            
            # Also copy to root lib directory as fallback
            mkdir -p "$APP_DIR/lib/x86_64-linux-gnu"
            cp "$APP_DIR/usr/lib/x86_64-linux-gnu/libfreeipmi.so.17"* "$APP_DIR/lib/x86_64-linux-gnu/" 2>/dev/null || true
        else
            echo "  ⚠️  libfreeipmi.so.17 not found after extraction"
        fi
        
        # Copy all libfreeipmi dependencies
        if ls "$APP_DIR/usr/lib/x86_64-linux-gnu"/libfreeipmi* 1> /dev/null 2>&1; then
            echo "  Copying all libfreeipmi libraries..."
            for lib in "$APP_DIR/usr/lib/x86_64-linux-gnu"/libfreeipmi*; do
                libname=$(basename "$lib")
                ln -sf "$APP_DIR/usr/lib/x86_64-linux-gnu/$libname" "$APP_DIR/usr/lib/$libname" 2>/dev/null || true
            done
        fi
    fi
    
    echo "✅ Hardware monitoring tools installed successfully"
    echo "📋 Installed tools:"
    [ -f "$APP_DIR/usr/bin/ipmitool" ] && echo "  ✅ ipmitool" || echo "  ⚠️  ipmitool not found"
    [ -f "$APP_DIR/usr/bin/sensors" ] && echo "  ✅ sensors (lm-sensors)" || echo "  ⚠️  sensors not found"
    [ -f "$APP_DIR/usr/bin/upsc" ] && echo "  ✅ upsc (nut-client)" || echo "  ⚠️  upsc not found"
    
    echo "📋 Verifying libraries:"
    if [ -f "$APP_DIR/usr/lib/x86_64-linux-gnu/libfreeipmi.so.17" ]; then
        echo "  ✅ libfreeipmi.so.17 found"
    else
        echo "  ⚠️  libfreeipmi.so.17 NOT found - ipmitool may not work"
    fi
fi

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
