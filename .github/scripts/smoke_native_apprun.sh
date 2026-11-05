#!/bin/bash
# Exercise the extracted launcher and its real native Python environment,
# intercepting only the final server exec so no host-monitoring server starts.
set -eu
appdir="$1"
export PMX_SMOKE_PYTHON
PMX_SMOKE_PYTHON="$(command -v python)"
fixture_bin="$(mktemp -d)"
trap 'rm -rf "$fixture_bin"' EXIT
cat > "$fixture_bin/python3" <<'WRAPPER'
#!/bin/sh
case "$1" in
    */flask_server.py)
        exec "$PMX_SMOKE_PYTHON" -c 'import gevent, greenlet, geventwebsocket, zope.interface; from PIL import Image; from gevent import pywsgi; print("PASS: extracted AppRun native runtime")'
        ;;
    *) exec "$PMX_SMOKE_PYTHON" "$@" ;;
esac
WRAPPER
chmod +x "$fixture_bin/python3"
PATH="$fixture_bin:$PATH" bash "$appdir/AppRun"
