#!/bin/bash

# ProxMenux Monitor AppImage Builder
# This script creates a single AppImage with Flask server, Next.js dashboard, and translation support

set -e

WORK_DIR="/tmp/proxmenux_build"
APP_DIR="$WORK_DIR/ProxMenux.AppDir"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/../dist"

VERSION=$(sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' "$SCRIPT_DIR/../package.json")
APPIMAGE_NAME="ProxMenux-${VERSION}.AppImage"

echo "🚀 Building ProxMenux Monitor AppImage v${VERSION} with translation support..."

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
if [ -d "$SCRIPT_DIR/../../.next" ]; then
    cp -r "$SCRIPT_DIR/../../.next" "$APP_DIR/web/"
    cp -r "$SCRIPT_DIR/../../web/public" "$APP_DIR/web/"
    cp "$SCRIPT_DIR/../package.json" "$APP_DIR/web/"
    echo "✅ Next.js build copied successfully"
else
    echo "⚠️  Warning: Next.js build not found. Run 'npm run build' first."
    echo "📋 Creating minimal web structure..."
    mkdir -p "$APP_DIR/web/public/images"
    if [ -f "$SCRIPT_DIR/../../web/public/images/proxmenux-logo.png" ]; then
        cp "$SCRIPT_DIR/../../web/public/images/proxmenux-logo.png" "$APP_DIR/web/public/images/"
    fi
fi

# Create AppRun script
cat > "$APP_DIR/AppRun" << 'EOF'
#!/bin/bash

# Get the directory where this AppImage is located
HERE="$(dirname "$(readlink -f "${0}")")"

# Set Python path
export PYTHONPATH="$HERE/usr/lib/python3/dist-packages:$PYTHONPATH"
export PATH="$HERE/usr/bin:$PATH"

# Check if translation mode is requested
if [ "$1" = "--translate" ]; then
    shift
    exec python3 "$HERE/usr/bin/translate_cli.py" "$@"
fi

# Start Flask server in background
echo "🚀 Starting ProxMenux Monitor..."
echo "📊 Dashboard will be available at: http://localhost:8008"

cd "$HERE"
python3 "$HERE/usr/bin/flask_server.py" &
FLASK_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "🛑 Stopping ProxMenux Monitor..."
    kill $FLASK_PID 2>/dev/null || true
    exit 0
}

# Set trap for cleanup
trap cleanup SIGINT SIGTERM EXIT

# Wait for Flask to start
sleep 3

# Try to open browser
if command -v xdg-open > /dev/null; then
    xdg-open "http://localhost:8008" 2>/dev/null || true
elif command -v firefox > /dev/null; then
    firefox "http://localhost:8008" 2>/dev/null || true
elif command -v chromium > /dev/null; then
    chromium "http://localhost:8008" 2>/dev/null || true
elif command -v google-chrome > /dev/null; then
    google-chrome "http://localhost:8008" 2>/dev/null || true
fi

echo "✅ ProxMenux Monitor is running!"
echo "📝 Press Ctrl+C to stop"
echo "🌐 Access dashboard at: http://localhost:8008"
echo "🌍 Translation available with: ./ProxMenux-Monitor.AppImage --translate"

# Keep the script running
wait $FLASK_PID
EOF

chmod +x "$APP_DIR/AppRun"

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
if [ -f "$SCRIPT_DIR/../../web/public/images/proxmenux-logo.png" ]; then
    cp "$SCRIPT_DIR/../../web/public/images/proxmenux-logo.png" "$APP_DIR/proxmenux-monitor.png"
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

# Build AppImage
echo "🔨 Building unified AppImage v${VERSION}..."
cd "$WORK_DIR"
ARCH=x86_64 ./appimagetool "$APP_DIR" "$APPIMAGE_NAME"

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
