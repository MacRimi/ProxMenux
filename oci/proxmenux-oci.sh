#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$ROOT_DIR/.venv"
REQUIREMENTS="$ROOT_DIR/requirements.txt"
STAMP="$VENV_DIR/.requirements.sha256"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR: Python 3 is required." >&2
  exit 1
}

if python3 -c 'import yaml, jsonschema' >/dev/null 2>&1; then
  PYTHON=python3
else
  if [[ ! -x "$VENV_DIR/bin/python" ]] || ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "Preparing the local Python environment..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR" || {
      echo "ERROR: could not create the virtual environment. On Debian, install python3-venv, python3-yaml and python3-jsonschema." >&2
      exit 1
    }
  fi
  if command -v shasum >/dev/null 2>&1; then
    CURRENT_HASH=$(shasum -a 256 "$REQUIREMENTS" | awk '{print $1}')
  else
    CURRENT_HASH=$(sha256sum "$REQUIREMENTS" | awk '{print $1}')
  fi
  INSTALLED_HASH=$(cat "$STAMP" 2>/dev/null || true)
  if [[ "$CURRENT_HASH" != "$INSTALLED_HASH" ]]; then
    echo "Installing the converter dependencies..."
    "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r "$REQUIREMENTS"
    printf '%s\n' "$CURRENT_HASH" >"$STAMP"
  fi
  PYTHON="$VENV_DIR/bin/python"
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m proxmenux_oci "$@"
