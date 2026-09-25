from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass

from .i18n import translate


class UserCancelled(RuntimeError):
    pass


class BackRequested(RuntimeError):
    pass


class RestartWizard(RuntimeError):
    pass


class BacktrackUI:
    """Replay prior answers when returning to a previous wizard question."""

    def __init__(self, base):
        self.base = base
        self.answers = []
        self.cursor = 0
        self.previous_back_enabled = getattr(base, 'back_enabled', False)
        base.back_enabled = True

    def __getattr__(self, name):
        return getattr(self.base, name)

    def close(self):
        self.base.back_enabled = self.previous_back_enabled

    def restart(self):
        self.cursor = 0

    def _call(self, name, *args, **kwargs):
        if self.cursor < len(self.answers):
            saved_name, value = self.answers[self.cursor]
            if saved_name != name:
                self.answers = self.answers[:self.cursor]
            else:
                self.cursor += 1
                return value
        try:
            value = getattr(self.base, name)(*args, **kwargs)
        except BackRequested:
            if self.cursor:
                self.answers = self.answers[:self.cursor - 1]
                self.cursor = 0
                raise RestartWizard()
            raise UserCancelled(translate('Wizard cancelled'))
        self.answers.append((name, value))
        self.cursor += 1
        return value

    def ask(self, *args, **kwargs):
        return self._call('ask', *args, **kwargs)

    def password(self, *args, **kwargs):
        return self._call('password', *args, **kwargs)

    def confirm(self, *args, **kwargs):
        return self._call('confirm', *args, **kwargs)

    def choose(self, *args, **kwargs):
        return self._call('choose', *args, **kwargs)

    def checklist(self, *args, **kwargs):
        return self._call('checklist', *args, **kwargs)

    def detail_menu(self, *args, **kwargs):
        return self._call('detail_menu', *args, **kwargs)

    def review(self, *args, **kwargs):
        try:
            return self.base.review(*args, **kwargs)
        except BackRequested:
            if self.cursor:
                self.answers = self.answers[:self.cursor - 1]
                self.cursor = 0
                raise RestartWizard()
            raise UserCancelled(translate('Wizard cancelled'))


APP_TITLE = "OCI manager Apps (beta)"


@dataclass
class TerminalUI:
    title: str = APP_TITLE
    back_enabled: bool = False

    def ask(self, text: str, default: str | None = None, required: bool = True) -> str:
        suffix = f" [{default}]" if default not in (None, "") else ""
        while True:
            value = input(f"{text}{suffix}: ").strip()
            if self.back_enabled and value == ':back':
                raise BackRequested()
            if value:
                return value
            if default is not None:
                return default
            if not required:
                return ""
            print(translate("This value is required."))

    def password(self, text: str, required: bool = True) -> str:
        while True:
            value = getpass.getpass(f"{text}: ")
            if self.back_enabled and value == ':back':
                raise BackRequested()
            if not value:
                if not required:
                    return ""
                print(translate("This value is required."))
                continue
            repeated = getpass.getpass(f"{translate('Repeat to confirm')}: ")
            if self.back_enabled and repeated == ':back':
                raise BackRequested()
            if value == repeated:
                return value
            print(translate("The values do not match. Enter them again."))

    def confirm(self, text: str, default: bool = False) -> bool:
        suffix = " [Y/n]" if default else " [y/N]"
        value = input(f"{text}{suffix}: ").strip().casefold()
        if self.back_enabled and value == ':back':
            raise BackRequested()
        if not value:
            return default
        return value in {"y", "yes", "s", "si"}

    def choose(self, text: str, options: list[tuple[str, str]], default: str | None = None,
               title: str | None = None, show_tags: bool = True,
               size: tuple[int, int, int] | None = None, colors: bool = False) -> str | None:
        options = [(tag, re.sub(r"\\Z.", "", label)) for tag, label in options if tag]
        print(text)
        for index, (_, label) in enumerate(options, 1):
            print(f"{index:2}. {label}")
        default_index = next((index for index, (tag, _) in enumerate(options, 1) if tag == default), None)
        selected = self.ask(translate("Selection"), str(default_index) if default_index else None, required=False)
        if selected.isdigit() and 1 <= int(selected) <= len(options):
            return options[int(selected) - 1][0]
        return None

    def checklist(self, text, options, defaults):
        return [tag for tag, label in options if self.confirm(label, tag in defaults)]

    def detail_menu(self, text: str, options: list[tuple[str, str]], default: str | None = None,
                    title: str | None = None) -> str | None:
        return self.choose(re.sub(r"\\Z.", "", text), options, default, title=title)

    def message(self, text: str, title: str | None = None) -> None:
        print(f"\n{title or self.title}\n{text}")

    def review(self, text: str, title: str | None = None, question: str | None = None,
               default: bool = True) -> bool:
        self.message(text, title)
        return self.confirm(question or translate("Continue?"), default)

    def info(self, text: str) -> None:
        print(text)


@dataclass
class DialogUI:
    """dialog widgets with the ProxMenux backtitle, used for every menu shown
    before the installation starts."""

    title: str = APP_TITLE
    backtitle: str = "ProxMenux"
    back_enabled: bool = False

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("dialog") and sys.stdin.isatty() and sys.stdout.isatty())

    def _run(self, widget: list[str], title: str | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if environment.get("TERM", "").casefold() in {"", "dumb", "unknown"}:
            environment["TERM"] = "xterm-256color"
        # dialog draws on the terminal and writes the selection to stderr.
        back_widget = ['--extra-button', '--extra-label', 'Volver'] if self.back_enabled and any(
            flag in widget for flag in ('--inputbox', '--passwordbox', '--yesno', '--menu', '--checklist')) else []
        result = subprocess.run(
            ["dialog", "--no-collapse", "--backtitle", self.backtitle, "--title", title or self.title,
             *back_widget, *widget],
            stdout=None, stderr=subprocess.PIPE, text=True, check=False, env=environment,
        )
        if result.returncode == 3 and back_widget:
            raise BackRequested()
        return result

    @staticmethod
    def _size(text: str, min_height: int, width: int, extra: int = 6) -> tuple[str, str]:
        terminal = shutil.get_terminal_size((100, 30))
        width = max(50, min(width, terminal.columns - 4))
        lines = sum(max(1, len(textwrap.wrap(line, max(20, width - 6)) or [""])) for line in text.splitlines() or [""])
        height = max(min_height, min(lines + extra, terminal.lines - 2))
        return str(height), str(width)

    def ask(self, text: str, default: str | None = None, required: bool = True, title: str | None = None) -> str:
        while True:
            height, width = self._size(text, 10, 78, 7)
            result = self._run(["--inputbox", f"\n{text}", height, width, default or ""], title)
            if result.returncode != 0:
                raise UserCancelled(text)
            value = result.stderr.strip()
            if value or not required or default is not None:
                return value or default or ""
            self.message(translate("This value is required."))

    def password(self, text: str, required: bool = True, title: str | None = None) -> str:
        while True:
            height, width = self._size(text, 10, 78, 7)
            result = self._run(["--insecure", "--passwordbox", f"\n{text}", height, width], title)
            if result.returncode != 0:
                raise UserCancelled(text)
            value = result.stderr.rstrip("\n")
            if not value:
                if not required:
                    return ""
                self.message(translate("This value is required."))
                continue
            repeated = self._run(["--insecure", "--passwordbox", f"\n{translate('Repeat to confirm')}", height, width], title)
            if repeated.returncode != 0:
                raise UserCancelled(text)
            if value == repeated.stderr.rstrip("\n"):
                return value
            self.message(translate("The values do not match. Enter them again."))

    def confirm(self, text: str, default: bool = False, title: str | None = None) -> bool:
        height, width = self._size(text, 9, 78, 6)
        widget = ["--yesno", f"\n{text}", height, width]
        if not default:
            widget = ["--defaultno", *widget]
        return self._run(widget, title).returncode == 0

    def choose(self, text: str, options: list[tuple[str, str]], default: str | None = None,
               title: str | None = None, show_tags: bool = True,
               size: tuple[int, int, int] | None = None, colors: bool = False) -> str | None:
        if size:
            widget = ["--colors"] if colors else []
            widget += ["--default-item", default] if default else []
            widget += ["--menu", text, *map(str, size)]
            for tag, label in options:
                widget += [tag, label]
            result = self._run(widget, title)
            return result.stderr.strip() if result.returncode == 0 else None
        terminal = shutil.get_terminal_size((100, 30))
        tag_width = max((len(tag) for tag, _ in options), default=0) + 2 if show_tags else 0
        width = min(max(60, max((len(label) for _, label in options), default=0) + tag_width + 14,
                        max((len(line) for line in text.splitlines()), default=0) + 6),
                    terminal.columns - 4, 110)
        text_lines = sum(max(1, len(textwrap.wrap(line, width - 6) or [""])) for line in text.splitlines() or [""])
        height = min(max(len(options) + text_lines + 8, 14), terminal.lines - 2)
        menu_height = max(3, min(len(options), height - text_lines - 8))
        widget = ["--default-item", default] if default else []
        if not show_tags:
            widget.append("--no-tags")
        widget += ["--menu", f"\n{text}", str(height), str(width), str(menu_height)]
        for tag, label in options:
            widget += [tag, label]
        result = self._run(widget, title)
        return result.stderr.strip() if result.returncode == 0 else None

    def detail_menu(self, text: str, options: list[tuple[str, str]], default: str | None = None,
                    title: str | None = None) -> str | None:
        """A tall menu under a block of information. When the information does
        not fit on screen it is shown first in a scrollable box."""
        terminal = shutil.get_terminal_size((100, 30))
        width = min(terminal.columns - 4, 104)
        text_lines = sum(max(1, len(textwrap.wrap(line, width - 6) or [""])) for line in text.splitlines() or [""])
        available = terminal.lines - 2
        needed = text_lines + len(options) + 9
        if needed > available:
            self._run(["--colors", "--msgbox", f"\n{text}", str(available), str(width)], title)
            text, needed = translate("Select an option"), len(options) + 10
        height = min(available, needed)
        widget = ["--colors"] + (["--default-item", default] if default else [])
        widget += ["--menu", f"\n{text}", str(height), str(width), str(len(options))]
        for tag, label in options:
            widget += [tag, label]
        result = self._run(widget, title)
        return result.stderr.strip() if result.returncode == 0 else None

    def checklist(self, text, options, defaults, title: str | None = None):
        terminal = shutil.get_terminal_size((100, 30))
        height = min(max(len(options) + 9, 14), terminal.lines - 2)
        widget = ["--separate-output", "--checklist", f"\n{text}", str(height), "78",
                  str(max(4, min(len(options), height - 8)))]
        for tag, label in options:
            widget += [tag, label, "on" if tag in defaults else "off"]
        result = self._run(widget, title)
        if result.returncode != 0:
            raise UserCancelled(text)
        return result.stderr.split()

    def message(self, text: str, title: str | None = None) -> None:
        height, width = self._size(text, 8, 84, 6)
        self._run(["--msgbox", f"\n{text}", height, width], title)

    def review(self, text: str, title: str | None = None, question: str | None = None,
               default: bool = True) -> bool:
        body = f"{text}\n\n{question or translate('Continue?')}"
        height, width = self._size(body, 12, 90, 6)
        widget = ["--yesno", f"\n{body}", height, width]
        if not default:
            widget = ["--defaultno", *widget]
        return self._run(widget, title).returncode == 0

    def info(self, text: str, title: str | None = None) -> None:
        height, width = self._size(text, 6, 70, 5)
        self._run(["--infobox", f"\n{text}", height, width], title)


def interactive_ui() -> TerminalUI | DialogUI:
    return DialogUI() if DialogUI.available() else TerminalUI()
