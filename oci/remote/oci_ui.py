"""Output helpers for the OCI host helpers written in Python: the look of the
ProxMenux utils.sh messages and the same translation cache (lang/<language>.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading

BASE_DIR = Path(os.environ.get("PMX_BASE_DIR", "/usr/local/share/proxmenux"))

MG = "\033[1;35m"
GN = "\033[1;92m"
RD = "\033[01;31m"
YW = "\033[33m"
YWB = "\033[1;33m"
BOLD = "\033[1m"
CL = "\033[m"
TAB = "    "
FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_language: str | None = None
_cache: dict[str, str] | None = None
_spinner: tuple[threading.Thread, threading.Event] | None = None


def _load_language() -> str:
    global _language
    if _language is None:
        try:
            value = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8")).get("language")
        except (OSError, ValueError, AttributeError):
            value = None
        _language = value if isinstance(value, str) and value else "en"
    return _language


def translate(text: str) -> str:
    global _cache
    if _load_language() == "en":
        return text
    if _cache is None:
        try:
            data = json.loads((BASE_DIR / "lang" / f"{_load_language()}.json").read_text(encoding="utf-8"))
            _cache = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache.get(text) or text


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _spin(stop: threading.Event) -> None:
    index = 0
    _write("\033[?25l")
    while not stop.wait(0.1):
        _write(f"\r {MG}{FRAMES[index]}{CL}")
        index = (index + 1) % len(FRAMES)


def stop_spinner() -> None:
    global _spinner
    if _spinner is not None:
        thread, stop = _spinner
        stop.set()
        thread.join()
        _spinner = None
    _write("\033[?25h")


def msg_info(text: str) -> None:
    global _spinner
    stop_spinner()
    _write(f"\r\033[K{TAB}{MG}-{text}{CL}")
    if sys.stdout.isatty() or os.environ.get("OCI_SPINNER") == "1":
        stop = threading.Event()
        thread = threading.Thread(target=_spin, args=(stop,), daemon=True)
        _spinner = (thread, stop)
        thread.start()
    else:
        _write("\n")


def msg_progress(text: str) -> None:
    stop_spinner()
    _write(f"\r\033[K{TAB}{MG}-{text}{CL}")


def msg_ok(text: str) -> None:
    stop_spinner()
    _write(f"\r\033[K{TAB}{GN}✓ {CL}{GN}{text}{CL}\n")


def msg_warn(text: str) -> None:
    stop_spinner()
    _write(f"\r\033[K{TAB}{CL} {YWB}{text}{CL}\n")


def msg_error(text: str) -> None:
    stop_spinner()
    _write(f"\r\033[K{TAB}{RD}[ERROR] {text}{CL}\n")


def msg_info2(text: str) -> None:
    stop_spinner()
    _write(f"\r\033[K{TAB}{BOLD}{YW}- {text}{CL}\n")


def log(path: str | os.PathLike | None, text: str) -> None:
    """Appends a line to a private log; output that the user does not need goes here."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text.rstrip("\n") + "\n")
