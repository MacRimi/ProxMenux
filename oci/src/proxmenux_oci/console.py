"""Terminal output in the ProxMenux style of utils.sh (msg_info, msg_ok, ...)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import threading

from .i18n import BASE_DIR

MG = "\033[1;35m"
GN = "\033[1;92m"
RD = "\033[01;31m"
YW = "\033[33m"
YWB = "\033[1;33m"
BL = "\033[36m"
BOLD = "\033[1m"
CL = "\033[m"
BFR = "\r\033[K"
TAB = "    "
HOLD = "-"
CM = f"{GN}✓ {CL}"
FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_spinner: tuple[threading.Thread, threading.Event] | None = None


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _spin(stop: threading.Event) -> None:
    index = 0
    _write("\033[?25l")
    while not stop.wait(0.1):
        _write(f"\r {MG}{FRAMES[index]}{CL}")
        index = (index + 1) % len(FRAMES)


def stop_spinner(clear_line: bool = True) -> None:
    global _spinner
    if _spinner is not None:
        thread, stop = _spinner
        stop.set()
        thread.join()
        _spinner = None
        if clear_line:
            _write("\r\033[K")
    _write("\033[?25h")


def msg_info(text: str) -> None:
    global _spinner
    stop_spinner()
    _write(f"{TAB}{MG}{HOLD}{text}")
    if sys.stdout.isatty():
        stop = threading.Event()
        thread = threading.Thread(target=_spin, args=(stop,), daemon=True)
        _spinner = (thread, stop)
        thread.start()
    else:
        _write("\n")


def msg_ok(text: str) -> None:
    stop_spinner(clear_line=False)
    _write(f"{BFR}{TAB}{CM}{GN}{text}{CL}\n")


def msg_warn(text: str) -> None:
    stop_spinner(clear_line=False)
    _write(f"{BFR}{TAB}{CL} {YWB}{text}{CL}\n")


def msg_error(text: str) -> None:
    stop_spinner(clear_line=False)
    _write(f"{BFR}{TAB}{RD}[ERROR] {text}{CL}\n")


def msg_info2(text: str) -> None:
    _write(f"{TAB}{BOLD}{YW}{HOLD} {text}{CL}\n")


def msg_note(text: str) -> None:
    """Closing information, in the colour ProxMenux uses for paths and values."""
    stop_spinner(clear_line=False)
    _write(f"{TAB}{BL}{text}{CL}\n")


def msg_success(text: str) -> None:
    stop_spinner(clear_line=False)
    _write(f"{TAB}{BOLD}{BL}{HOLD}{text}{CL}\n\n")


def ask_yes_no(text: str, default_yes: bool = True) -> bool:
    """A question asked in the middle of the output: whiptail draws over the
    terminal and restores it, so what was printed stays on screen."""
    width = 74
    lines = sum(max(1, len(textwrap.wrap(line, width - 6) or [''])) for line in text.splitlines() or [''])
    widget = ['whiptail', '--backtitle', 'ProxMenux', '--title', 'ProxMenux',
              '--yesno', text, str(min(lines + 8, 20)), str(width)]
    if not default_yes:
        widget.insert(1, '--defaultno')
    if shutil.which('whiptail'):
        environment = dict(os.environ, NEWT_COLORS_FILE='/dev/null')
        return subprocess.run(widget, env=environment, check=False).returncode == 0
    answer = input(f"{text} [{'Y/n' if default_yes else 'y/N'}]: ").strip().casefold()
    return default_yes if not answer else answer in {'y', 'yes', 's', 'si'}


def msg_title(text: str) -> None:
    _write(f"\n\n{TAB}{BOLD}{HOLD} | {text} | {HOLD}{CL}\n\n\n")


def show_logo() -> None:
    """The ProxMenux banner; like show_proxmenux_logo it clears the screen."""
    stop_spinner()
    utils = BASE_DIR / "utils.sh"
    if utils.is_file() and sys.stdout.isatty():
        subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; show_proxmenux_logo', "_", str(utils)],
                       check=False)
    elif sys.stdout.isatty():
        _write("\033[H\033[2J")


def wait_for_enter(text: str) -> None:
    msg_success(text)
    try:
        input()
    except EOFError:
        pass
