#!/usr/bin/env python3

# ==========================================================
# ProxMenux - Plain LXC console creation
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Guided console interface for the shared plain LXC JSON command.
# Collects and reviews settings before a separately confirmed operation.
# ==========================================================
"""Dialog adapter for the local, versioned plain LXC command."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import unicodedata
from tempfile import TemporaryDirectory, TemporaryFile
from uuid import uuid4


def N_(text):
    """Mark English strings for the existing translation-cache extractor."""
    return text


SCRIPTS = Path(__file__).resolve().parents[1]
ENGINE = SCRIPTS / "lxc" / "plain_lxc.py"
TITLES = (N_("System"), N_("Access"), N_("Resources"), N_("Network and DNS"), N_("Review"))
ERRORS = {
    "hardware_requires_v2": N_("Hardware selection requires a fresh plan from the current wizard."),
    "architecture_unsupported": N_("This node architecture is outside the supported scope."),
    "bridge_unavailable": N_("The chosen bridge or VLAN is unavailable."),
    "catalog_unavailable": N_("Proxmox could not read its local template index."),
    "disk_space_insufficient": N_("The chosen storage has insufficient space."),
    "invalid_field": N_("Check the value in the indicated field."),
    "invalid_ssh_key": N_("Enter a valid OpenSSH public key."),
    "node_capacity_exceeded": N_("The CPU or memory request exceeds the capacity of this node."),
    "plan_changed": N_("The configuration changed. Review a fresh plan before creating the container."),
    "pve_unavailable": N_("Proxmox could not complete the requested check."),
    "root_required": N_("Open the wizard as root."),
    "storage_unavailable": N_("The chosen storage is unavailable for this purpose."),
    "target_operation_pending": N_("An earlier operation for this target still needs to be checked."),
    "task_log_unavailable": N_("The Proxmox task log could not be read."),
    "template_already_present": N_("A file with this template name already exists on the storage."),
    "template_checksum_mismatch": N_("The template checksum differs from the official index."),
    "template_unverified": N_("The template could not be verified against the official index."),
    'template_unavailable': N_("The selected template file could not be read safely."),
    "template_architecture_required": N_("Choose the architecture of this local template explicitly."),
    "template_architecture_mismatch": N_("The template architecture does not match this node."),
    "vmid_in_use": N_("This VMID is already in use in the cluster."),
    "operation_controller_active": N_("The original controller is still running. Wait before recovering this operation."),
    'resource_unavailable': N_("The chosen mount source or device is unavailable or changed. Review a fresh plan."),
    'resource_in_use': N_("The selected device is already assigned to another guest."),
    'resource_unsupported': N_("This Proxmox version does not support the selected mount points or device passthrough."),
}
RESULTS = {
    "succeeded": N_("Operation completed."),
    "failed": N_("The Proxmox task failed."),
    "partial": N_("The operation completed only in part."),
    "running": N_("The Proxmox task is still running."),
    "unknown": N_("The result is uncertain. Check the operation before taking further action."),
    "start_failed": N_("The container was created. Its start task failed."),
    "start_not_submitted": N_("The container was created. Starting it requires a separate action."),
    "preparation_failed": N_("The container was created, but first-boot preparation failed. It was not started. Check the task log."),
    "preparation_not_submitted": N_("The container was created, but first-boot preparation was not submitted. Check the operation before starting it."),
    "create_failed": N_("Proxmox reported a create error. Check the resulting VMID and storage."),
    "download_failed": N_("Proxmox reported a download error."),
    "recovery_wait": N_("The safety waiting period has not ended. Check this operation again later."),
    "recovery_unavailable": N_("Recovery could not prove that the target is idle. The reservation was kept."),
    "recovered_not_submitted": N_("The reservation was released without repeating the operation or deleting resources."),
    "recovered_requires_review": N_("The reservation was released. Inspect the VMID and storage before taking further action; no resources were changed."),
    "recovered_download": N_("The original template checksum was verified and the reservation released."),
}
ACCESS = {
    "password": N_("Root password"),
    "ssh_key": N_("SSH public key"),
    "both": N_("Root password and SSH public key"),
}
PHASES = {
    "create": N_("Creating the container..."),
    "start": N_("Starting the container..."),
    "prepare": N_("Preparing the container for its first start..."),
    "download": N_("Downloading the template…"),
}
TASK_LOGS = {
    "create": N_("View creation task log"),
    "start": N_("View start task log"),
    "prepare": N_("View preparation task log"),
}
TASK_WARNINGS = {
    "create": N_("Warnings during creation."),
    "start": N_("Warnings during start."),
    "prepare": N_("Warnings during preparation."),
    "download": N_("Warnings during template download."),
}
NESTING_NOTICE = N_("Nesting exposes additional host /proc and /sys information to this unprivileged container. Enable it only when needed, for example for newer systemd versions.")
NESTING_COMPATIBILITY_NOTICE = N_("Some templates, such as Debian 13 with systemd 257, may fail to mount /tmp, /run/lock or /dev/mqueue when nesting is disabled. Check whether your template needs nesting before continuing.")
PLAN_WARNINGS = {
    'no_network': N_("The container will be created without a network interface."),
    'nesting_enabled': NESTING_NOTICE,
    'custom_template': N_("This is a local template supplied by the administrator. Its checksum identifies the selected file; it does not certify its publisher or contents."),
    'storage_overcommit': N_("The logical disk limit exceeds current free space. Thin storage allocates data as it is written; extraction or later writes can fail if the pool fills up."),
    'bind_mount': N_("Bind mounts expose host data and are not included in container backups. Permissions are kept unchanged; an unprivileged container may need existing UID/GID permissions."),
    'device_passthrough': N_("Device passthrough uses the existing host drivers and shares the selected device nodes. Required software inside the container is not installed automatically. USB device paths can change after reconnecting."),
}


class Cancelled(Exception):
    pass


class Back(Exception):
    pass


class Rewind(Exception):
    pass


class FormNavigation:
    """Replay only answers while moving between fields, never an operation.

    A template download is one separately confirmed action outside this replay;
    its completed selection is cached as one answer. Passwords stay in memory
    and are never prefilled, passed on argv, or included in a summary.
    """
    def __init__(self, ui):
        self.ui = ui
        self.answers, self.previous, self.defaults = [], {}, {}
        self.index = 0
        self.context = None

    def __getattr__(self, name):
        return getattr(self.ui, name)

    def run(self, build):
        while True:
            self.index = 0
            try:
                return build()
            except Rewind:
                continue

    def ask(self, kind, prompt, default, field):
        index = self.index
        self.index += 1
        key = kind, prompt, index
        if index < len(self.answers):
            return deepcopy(self.answers[index])
        previous = self.previous.get(key, default)
        if previous == self.defaults.get(key, default):
            previous = default
        try:
            answer = field(previous)
        except Back:
            self.answers = self.answers[:max(0, index-1)]
            if not index:
                raise
            raise Rewind() from None
        self.previous[key], self.defaults[key] = deepcopy(answer), deepcopy(default)
        self.answers.append(deepcopy(answer))
        return answer

    def input(self, step, prompt, default='', hidden=False):
        return self.ask('input', prompt, default,
                        lambda previous: self.ui.input(step, prompt, '' if hidden else previous, hidden=hidden))

    def number(self, step, prompt, default, optional=False):
        return self.ask('number', prompt, default,
                        lambda previous: self.ui.number(step, prompt, '' if previous is None else previous, optional=optional))

    def choose(self, step, prompt, choices, default=''):
        return self.ask('choose', prompt, default,
                        lambda previous: self.ui.choose(step, prompt, choices, default=previous))

    def confirm(self, step, text, *, default=False):
        return self.ask('confirm', text, default, lambda previous: self.ui.confirm(step, text, default=previous))

    def template(self, context, default):
        if self.context is None:
            self.context = context
        def select(previous):
            volume, current = select_template(self.ui, self.context, previous[0] if isinstance(previous, tuple) else previous)
            self.context = current
            return volume, current
        return self.ask('template', 'template', default, select)


class WizardError(Exception):
    def __init__(self, code, field=None):
        self.code, self.field = code, field


def error_text(ui, error):
    text = ui.t(ERRORS.get(error.code, N_("The wizard could not complete the operation.")))
    return f"{text} ({error.field})" if error.field else text


def stream_response(command, body, on_phase):
    with subprocess.Popen([*command, "--progress"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        with process.stdin:
            process.stdin.write(body)
        for line in process.stdout:
            frame = json.loads(line)
            if type(frame) is not dict or frame.get("schema_version") != 1:
                raise ValueError("Invalid progress response")
            if frame.get("event") != "phase":
                return frame
            if frame.get("phase") in PHASES:
                on_phase(frame["phase"])
    raise ValueError("Missing operation result")


def call(action, *, on_phase=None, **payload):
    body = json.dumps({"schema_version": 2, "action": action, **payload}).encode()
    command = ["/usr/bin/python3", "-I", "-B", str(ENGINE)]
    try:
        if on_phase is None:
            result = subprocess.run(command, input=body, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            envelope = json.loads(result.stdout)
        else:
            envelope = stream_response(command, body, on_phase)
        if not envelope["ok"]:
            raise WizardError(envelope["error"], envelope.get("field"))
        return envelope["data"]
    except (OSError, ValueError, KeyError, TypeError):
        raise WizardError("local_operation_error") from None


class NamedChoices(list):
    """Display device names while retaining opaque selection IDs internally."""


class Dialog:
    def __init__(self, language):
        self.translations = {}
        self._paint_directory = None
        self._paint_environment = None
        if re.fullmatch(r"[a-z]{2}", language):
            try:
                path = SCRIPTS.parent / "lang" / f"{language}.json"
                values = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(values, dict):
                    self.translations = values
            except (OSError, ValueError):
                pass

    def t(self, text):
        value = self.translations.get(text)
        return value if isinstance(value, str) and value else text

    def button_labels(self):
        # Native dialog defaults do not use the application's language catalog.
        return ["--ok-label", self.t(N_("OK")), "--cancel-label", self.t(N_("Cancel")),
                "--yes-label", self.t(N_("Yes")), "--no-label", self.t(N_("No")),
                "--exit-label", self.t(N_("Close"))]

    # Match the existing main menu. Native dialog still owns wrapping,
    # centering, scrolling and keyboard handling.
    BASE_WIDTH = 75
    BASE_HEIGHT = 24

    def paint_environment(self):
        if self._paint_environment is not None:
            return self._paint_environment
        environment = os.environ.copy()
        terminal = environment.get("TERM", "")
        if not re.fullmatch(r"xterm(?:[-a-zA-Z0-9]*)", terminal):
            return environment
        # Keep this terminal's keys/colors, but paint colored cells explicitly.
        # Erase/repeat optimizations and alternate-screen switches can leave
        # stale stripes through terminal bridges such as ConPTY. The private
        # entry is compiled once per wizard; the shell's TERM is never changed.
        directory = TemporaryDirectory(prefix="proxmenux-dialog-")
        try:
            result = subprocess.run(["/usr/bin/infocmp", "-1", terminal],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, timeout=5, check=True)
            capabilities = {"bce", "ech", "rep", "el", "el1", "ed", "smcup", "rmcup"}
            source = "\n".join(line for line in result.stdout.splitlines()
                               if re.split(r"[=#,]", line.strip(), maxsplit=1)[0] not in capabilities) + "\n"
            subprocess.run(["/usr/bin/tic", "-o", directory.name, "-"], input=source,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           text=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError):
            directory.cleanup()
            raise WizardError("dialog_error") from None
        environment.update(TERMINFO=directory.name, NCURSES_NO_HARD_TABS="1")
        self._paint_directory = directory
        self._paint_environment = environment
        return environment

    def terminal_size(self):
        try:
            return os.get_terminal_size(sys.stdout.fileno())
        except (OSError, ValueError):
            return shutil.get_terminal_size(fallback=(80, 24))

    @staticmethod
    def text_rows(text, width):
        # Measure conservatively for deciding when a detail needs more room;
        # the original text is always passed unchanged to native dialog.
        measured = "".join("" if unicodedata.category(char) in ("Mn", "Me", "Cf") else
                           "xx" if unicodedata.east_asian_width(char) in ("W", "F") else char
                           for char in text)
        return sum(max(1, len(textwrap.wrap(line, max(1, width - 8), break_on_hyphens=False)))
                   for line in measured.split("\n"))

    def dimensions(self, text, *, detail=False, menu_rows=0):
        columns, lines = self.terminal_size()
        width = min(self.BASE_WIDTH, max(1, columns - 4))
        available = max(1, lines - 2)
        height = min(self.BASE_HEIGHT, available)
        needed = self.text_rows(text, width) + 8 + menu_rows
        if detail or needed > height:
            height = min(available, max(height, needed))
        return str(height), str(width)

    def run(self, step, widget, text, *args, pass_fds=(), default_item="", dimensions=None, hide_tags=False):
        title = f"{step}/5  {self.t(TITLES[step - 1])}"
        mask = ["--insecure"] if widget == "--passwordbox" else []
        selection = ["--default-item", default_item] if default_item else []
        presentation = ["--no-tags"] if hide_tags else []
        if dimensions is None:
            menu_rows = min((len(args) - 1) // 2, 8) if widget == "--menu" else 0
            dimensions = self.dimensions(text, detail=step == 5 and "\n" in text, menu_rows=menu_rows)
        if widget == "--menu":
            # As in the main menu, reserve text/buttons explicitly. Native
            # menu-height=0 can otherwise enlarge an already fixed frame.
            visible_rows = max(1, int(dimensions[0]) - 7 - self.text_rows(text, int(dimensions[1])))
            args = (str(visible_rows), *args[1:])
        navigation = ['--extra-button', '--extra-label', self.t(N_('Back'))] if widget in ('--menu', '--inputbox', '--passwordbox') else []
        result = subprocess.run(["dialog", "--clear", "--backtitle", "ProxMenux", "--title", title,
                                 *self.button_labels(), *selection, *presentation, *navigation,
                                 *mask, widget, text, *dimensions, *args],
                                stderr=subprocess.PIPE, text=True, pass_fds=pass_fds,
                                env=self.paint_environment())
        if result.returncode == 3:
            raise Back()
        if result.returncode not in (0, 1, 255):
            raise WizardError("dialog_error")
        return result.returncode, result.stderr

    def input(self, step, prompt, default="", hidden=False):
        code, value = self.run(step, "--passwordbox" if hidden else "--inputbox", self.t(prompt), str(default))
        if code:
            raise Cancelled()
        return value

    def number(self, step, prompt, default, optional=False):
        while True:
            value = self.input(step, prompt, default).strip()
            if optional and not value:
                return None
            if re.fullmatch(r"[0-9]{1,9}", value):
                return int(value)
            self.message(step, self.t(N_("Enter a whole number.")))

    def choose(self, step, prompt, choices, default=""):
        text = self.t(prompt)
        height, width = self.dimensions(text, detail=step == 5, menu_rows=min(len(choices), 8))
        if step == 5 and self.text_rows(text, int(width)) + 8 + min(len(choices), 8) > int(height):
            # A low terminal cannot show a full review and its action list at
            # once. Keep the complete review scrollable, then show the same
            # actions. Esc on the detail page cancels without an action.
            # Native textbox does not wrap long lines. Keep review prose readable
            # without horizontal scrolling; task-log content remains unchanged.
            wrapped = '\n'.join(textwrap.fill(line, max(1, int(width) - 8),
                                             break_long_words=False, break_on_hyphens=False)
                                for line in text.split('\n'))
            if not self.task_log(step, wrapped):
                raise Cancelled()
            prompt = N_("Choose what to do next.")
        # Template/storage menus may mix identifier-only rows with a labelled
        # action. Keep their full identifier in one display column while
        # native dialog still returns the original, unchanged tag.
        one_column = any(not label for _, label in choices)
        args = [value for key, label in choices for value in (key, label or key if one_column else label)]
        selected = default if default in dict(choices) else ""
        code, choice = self.run(step, "--menu", self.t(prompt), "0", *args,
                                default_item=selected, hide_tags=one_column or isinstance(choices, NamedChoices))
        if code or choice not in {key for key, _ in choices}:
            raise Cancelled()
        return choice

    def confirm(self, step, text, *, default=False):
        # A new mutation requires an intentional Yes. Enter defaults to No.
        title = f"{step}/5  {self.t(TITLES[step - 1])}"
        selection = [] if default else ["--defaultno"]
        result = subprocess.run(["dialog", "--clear", *self.button_labels(), *selection, '--extra-button', '--extra-label', self.t(N_('Back')), "--title", title,
                                 "--yesno", text, *self.dimensions(text, detail="\n" in text)],
                                env=self.paint_environment())
        if result.returncode == 3:
            raise Back()
        if result.returncode == 255:
            raise Cancelled()
        if result.returncode not in (0, 1):
            raise WizardError("dialog_error")
        return result.returncode == 0

    def message(self, step, text, widget="--msgbox"):
        self.run(step, widget, text)

    def task_log(self, step, text):
        with TemporaryFile() as content:
            content.write(text.encode())
            content.seek(0)
            fd = content.fileno()
            code, _ = self.run(step, "--textbox", f"/proc/self/fd/{fd}", pass_fds=(fd,),
                               dimensions=self.dimensions(text, detail=True))
            return code == 0

    def restore_terminal(self):
        if self._paint_directory is not None:
            self._paint_directory.cleanup()
            self._paint_directory = self._paint_environment = None
        if sys.stdout.isatty():
            try:
                # Reset attributes before repainting the visible screen. Keep scrollback.
                subprocess.run(["/usr/bin/tput", "-x", "-S"], input="sgr0\nclear\n",
                               text=True, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    @contextmanager
    def progress(self, step, text, *, height="0"):
        # Accept the legacy height argument; the uniform frame takes precedence.
        title = f"{step}/5  {self.t(TITLES[step - 1])}"
        text = self.t(text)
        dimensions = self.dimensions(text)
        # The open pipe keeps the window visible. EOF closes it before the
        # summary or error dialog takes over.
        with subprocess.Popen(["dialog", "--backtitle", "ProxMenux", "--title", title, *self.button_labels(),
                               "--progressbox", text, *dimensions],
                              stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=self.paint_environment()) as display:
            def write_line(line):
                try:
                    display.stdin.write((line + "\n").encode())
                    display.stdin.flush()
                except BrokenPipeError:
                    pass

            try:
                yield write_line
            finally:
                try:
                    display.stdin.close()
                except BrokenPipeError:
                    pass
                try:
                    display.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    display.kill()


def show_task_log(ui, step, request_id, phase, password):
    offset = 0
    while True:
        try:
            log = call("task_log", request_id=request_id, phase=phase, offset=offset)
        except WizardError:
            ui.message(step, ui.t(ERRORS["task_log_unavailable"]))
            return
        text = "\n".join(log["lines"])
        if password:
            text = text.replace(password, "[…]")
        if not log["lines"]:
            ui.message(step, ui.t(N_("The task log has no lines yet.")))
            return
        title = ui.t(TASK_LOGS[phase])
        if not ui.task_log(step, f"{title}\n{log['upid']}\n\n{text}\n"):
            return
        offset = log["next_offset"]
        if offset is None or not ui.confirm(step, ui.t(N_("Show more log lines?"))):
            return


def operation(ui, step, action, **payload):
    request_id = uuid4().hex
    request_label = f"{ui.t(N_('Request ID'))}: {request_id}"
    try:
        with ui.progress(step, f"{ui.t(N_('Operation in progress'))} — {request_label}", height="10") as update:
            result = call(action, on_phase=lambda phase: update(ui.t(PHASES[phase])),
                          request_id=request_id, confirmed=True, **payload)
    except WizardError as error:
        if error.code not in ("local_operation_error", "operation_store_unavailable"):
            raise
        result = {"status": "unknown"}
    while True:
        status = result["status"]
        message = ui.t(RESULTS[status])
        reason = result.get("reason")
        if reason in RESULTS or reason in ERRORS:
            message += "\n" + ui.t(RESULTS.get(reason) or ERRORS[reason])
        warning_phases = result.get("task_warning_phases", {})
        if any(warning_phases.values()) or result.get("task_warnings"):
            message += "\n" + ui.t(N_("Proxmox reported task warnings. Check the task logs; OS health was not checked."))
            for phase in ("create", "prepare", "start", "download"):
                if warning_phases.get(phase):
                    message += "\n" + ui.t(TASK_WARNINGS[phase])
        if result.get("vmid") is not None:
            message += f"\nVMID: {result['vmid']}"
        if result.get("upid"):
            message += f"\n{ui.t(N_('Proxmox task'))}: {result['upid']}"
        if result.get("create_upid"):
            message += f"\n{ui.t(N_('Proxmox create task'))}: {result['create_upid']}"
        message += f"\n{request_label}"
        choices = [("close", ui.t(N_("Close")))]
        if status in ("running", "unknown"):
            choices.append(("status", ui.t(N_("Check the operation status now?"))))
        if status == 'unknown':
            choices.append(('recover', ui.t(N_("Check and recover the reservation"))))
        if action == "create":
            if result.get("create_upid") or (result.get("phase") == "create" and result.get("upid")):
                choices.append(("create", ui.t(TASK_LOGS["create"])))
            if result.get("phase") == "start" and result.get("upid"):
                choices.append(("start", ui.t(TASK_LOGS["start"])))
            if result.get("phase") == "prepare" and result.get("upid"):
                choices.append(("prepare", ui.t(TASK_LOGS["prepare"])))
        if len(choices) == 1:
            ui.message(step, message)
            return status
        try:
            choice = ui.choose(step, message, choices)
            if choice in TASK_LOGS:
                show_task_log(ui, step, request_id, choice, payload.get("secret", {}).get("password"))
                continue
        except Cancelled:
            return status
        if choice == "close":
            return status
        if choice == 'recover' and not ui.confirm(step, ui.t(N_("Recover this reservation without repeating the operation?")) + '\n' + request_label):
            continue
        try:
            with ui.progress(step, ui.t(N_("Checking the operation status…"))):
                result = call('recover', request_id=request_id, confirmed=True) if choice == 'recover' else call("status", request_id=request_id)
        except WizardError as error:
            ui.message(step, ui.t(ERRORS.get(error.code, N_("The operation could not be checked."))) +
                       f" ({ui.t(N_('Request ID'))}: {request_id})")
            return "unknown"


def select_template(ui, context, default=""):
    while True:
        templates = context["templates"]
        choices = [(volume, "") for volume in sorted(templates)]
        stores = [name for name, storage in context["storages"].items() if "vztmpl" in storage["content"]]
        if context["catalog"] and stores:
            choices.append(("download", ui.t(N_("Download an official template"))))
        if not choices:
            if context["catalog_state"] == "unavailable":
                raise WizardError("catalog_unavailable")
            ui.message(1, ui.t(N_("No verified template choices are available on this node.")))
            raise Cancelled()
        choice = ui.choose(1, N_("Select a system template"), choices, default=default)
        if choice != "download":
            return choice, context
        form = FormNavigation(ui)
        def download_fields():
            name = form.choose(1, N_("Select a template to download"), [(name, "") for name in sorted(context["catalog"])])
            storage = form.choose(1, N_("Select template storage"), [(name, "") for name in sorted(stores)])
            question = ui.t(N_("Download this template?")) + f"\n\n{name}\n{context['node']} / {storage}"
            return name, storage, form.confirm(1, question)
        try:
            name, storage, confirmed = form.run(download_fields)
        except Back:
            continue
        if confirmed:
            status = operation(ui, 1, "download_template", node=context["node"], catalog_id=name,
                               template_storage=storage)
            if status != "succeeded":
                raise Cancelled()
            context = call("context")
            default = storage + ':vztmpl/' + name


def access_fields(ui, current=None):
    current = current or {}
    mode = ui.choose(2, N_("Choose how to access the container"), [(key, ui.t(label)) for key, label in ACCESS.items()],
                     default=current.get("mode", ""))
    access = {"mode": mode, "ssh_public_keys": []}
    if mode in ("ssh_key", "both"):
        access["ssh_public_keys"] = [ui.input(2, N_("Paste an OpenSSH public key"), key)
                                     for key in current.get("ssh_public_keys", [])] or [
                                         ui.input(2, N_("Paste an OpenSSH public key"))]
        while len(access["ssh_public_keys"]) < 32 and ui.confirm(2, ui.t(N_("Add another public key?"))):
            access["ssh_public_keys"].append(ui.input(2, N_("Paste an OpenSSH public key")))
    return access


def password_fields(ui):
    while True:
        password = ui.input(2, N_("Enter the root password"), hidden=True)
        confirmation = ui.input(2, N_("Repeat the root password"), hidden=True)
        if password == confirmation and 5 <= len(password) <= 256:
            return password
        ui.message(2, ui.t(N_("Use 5 to 256 characters and enter the same password twice.")))


def network_fields(ui, context, current=None, dns=None):
    dns = dns or {}
    bridges = context["bridges"]
    choices = [("none", ui.t(N_("No network interface")))] + [
        ("bridge:" + key, key) for key in sorted(bridges)
    ]
    choice = ui.choose(4, N_("Choose the container network"), choices,
                       default="bridge:" + current["bridge"] if current else "none")
    if choice == "none":
        return None, {}
    bridge = choice.removeprefix("bridge:")
    previous_ipv4 = (current or {}).get("ipv4", {})
    mode = ui.choose(4, N_("Choose IPv4 configuration"), [("dhcp", "DHCP"), ("static", ui.t(N_("Static IPv4")))],
                     default=previous_ipv4.get("mode", "dhcp"))
    ipv4 = {"mode": mode}
    if mode == "static":
        ipv4["cidr"] = ui.input(4, N_("IPv4 address and prefix, for example 192.0.2.10/24"), previous_ipv4.get("cidr", ""))
        gateway = ui.input(4, N_("IPv4 gateway (optional)"), previous_ipv4.get("gateway", "")).strip()
        if gateway:
            ipv4["gateway"] = gateway
    network = {"bridge": bridge, "ipv4": ipv4}
    if bridges[bridge]["vlan_supported"]:
        vlan = ui.number(4, N_("VLAN tag (optional)"), (current or {}).get("vlan_tag", ""), optional=True)
        if vlan is not None:
            network["vlan_tag"] = vlan
    dns = {
        "nameservers": ui.input(4, N_("IPv4 DNS servers, separated by spaces (optional)"), " ".join(dns.get("nameservers", []))).split(),
        "search_domains": ui.input(4, N_("DNS search domains, separated by spaces (optional)"), " ".join(dns.get("search_domains", []))).split(),
    }
    return network, dns


def summary(ui, plan):
    spec = plan["spec"]
    rootfs, network = spec["rootfs"], spec["network"]
    yes_no = {True: ui.t(N_("Yes")), False: ui.t(N_("No"))}
    items = [
        (N_("Node"), spec["node"]), ("VMID", spec["vmid"]), (N_("Hostname"), spec["hostname"]),
        (N_("Template"), spec["template"]["volume_id"]),
        (N_("Template architecture"), plan['resources']['template']['architecture']),
        (N_("Access"), ui.t(ACCESS[spec["access"]["mode"]])),
        (N_("SSH public keys"), len(spec["access"]["ssh_public_keys"])),
        (N_("Unprivileged"), yes_no[plan["unprivileged"]]), (N_("Nesting"), yes_no[plan["nesting"]]),
        (N_("Root disk"), f'{rootfs["storage"]} / {rootfs["size_gib"]} GiB'),
        (N_("CPU cores"), spec["cpu"]["cores"]),
        (N_("RAM / swap"), f'{spec["memory"]["ram_mib"]} / {spec["memory"]["swap_mib"]} MiB'),
        (N_("Start on boot"), yes_no[spec["onboot"]]),
        (N_("Start after creation"), yes_no[spec["start_after_create"]]),
        (N_("Prepare the system for its first boot"), yes_no[spec['prepare_system']]),
    ]
    if network is None:
        items.append((N_("Network"), ui.t(N_("No network interface"))))
    else:
        items += [(N_("Bridge"), network["bridge"]), ("IPv4", network["ipv4"].get("cidr", "DHCP"))]
        for name, value in ((N_("IPv4 gateway"), network["ipv4"].get("gateway")), (N_("VLAN tag"), network.get("vlan_tag")),
                            (N_("DNS servers"), " ".join(spec["dns"]["nameservers"])),
                            (N_("DNS search domains"), " ".join(spec["dns"]["search_domains"]))):
            if value:
                items.append((name, value))
    for index, mount in enumerate(spec['mounts']):
        source = f"{mount['storage']} / {mount['size_gib']} GiB" if mount['type'] == 'volume' else mount['source']
        items.append((ui.t(N_('Mount point')) + f' {index+1}',
                      f"{source} → {mount['path']} / {ui.t(N_('Read only'))}: {yes_no[mount['read_only']]} / {ui.t(N_('Backup'))}: {yes_no[mount['backup']]}"))
    for device in plan['resources']['attachments'].get('hardware', []):
        items.append((N_('Hardware'), hardware_label(ui,device)))
    text = "\n".join(f"{ui.t(label)}: {value}" for label, value in items)
    if not plan['nesting']:
        text += '\n\n' + ui.t(NESTING_COMPATIBILITY_NOTICE)
        text += '\n' + ui.t(N_("To change nesting, open System."))
    return text


EDIT_GROUPS = (("system", 1), ("access", 2), ("resources", 3), ('mounts',3), ('devices',3), ("network", 4), ("startup", 5))


def mount_fields(ui, spec, context):
    mounts = deepcopy(spec.get('mounts', []))
    if not mounts and not ui.confirm(3, ui.t(N_('Add mount points?'))):
        return []
    while True:
        choices = [('done',ui.t(N_('Continue')))]
        if len(mounts) < context['capabilities']['mount_points']:
            choices += [('volume',ui.t(N_('Add a new storage volume'))), ('bind',ui.t(N_('Bind an existing host directory')))]
        choices += [(f'remove:{index}',ui.t(N_('Remove from plan')) + ' ' + mount['path']) for index,mount in enumerate(mounts)]
        text = ui.t(N_('Mount points')) + '\n' + '\n'.join(mount['path'] for mount in mounts)
        choice = ui.choose(3, text, choices)
        if choice == 'done':
            return mounts
        if choice.startswith('remove:'):
            del mounts[int(choice.split(':')[1])]
            continue
        mount = {'type':choice}
        if choice == 'volume':
            stores = [(name,name) for name,item in sorted(context['storages'].items()) if 'rootdir' in item['content']]
            mount['storage'] = ui.choose(3,N_('Select mount point storage'),stores)
            mount['size_gib'] = ui.number(3,N_('Mount point size (GiB)'),8)
        else:
            mount['source'] = ui.input(3,N_('Existing host directory (absolute path, no symlinks)'))
        mount['path'] = ui.input(3,N_('Mount path inside the container'),'/data')
        mount['read_only'] = ui.confirm(3,ui.t(N_('Mount this directory read only?')),default=choice=='bind')
        mount['backup'] = ui.confirm(3,ui.t(N_('Include this volume in container backups?')),default=True) if choice=='volume' else False
        mounts.append(mount)


HARDWARE_LABELS = {
    'intel-drm': N_('Intel GPU'), 'amd-drm': N_('AMD GPU'),
    'amd-rocm': N_('AMD GPU (ROCm)'), 'nvidia-runtime': N_('NVIDIA GPU (all host NVIDIA GPUs)'),
    'coral': N_('Coral TPU'), 'npu': N_('NPU'), 'usb': N_('USB or serial device'),
}


def hardware_label(ui, item):
    label = ui.t(HARDWARE_LABELS[item['profile']])
    if item['profile'] == 'nvidia-runtime':
        return label
    if item['profile'] in ('intel-drm','amd-drm','amd-rocm'):
        pci = next(row['pci_path'] for row in item['evidence'].values() if 'pci_path' in row)
        return label+' · '+Path(pci).name
    return label+' · '+item['name']


def device_fields(ui, spec, context):
    selected = deepcopy(spec.get('hardware', []))
    available = context['hardware']
    if context.get('hardware_errors'):
        ui.message(3, ui.t(N_('Some hardware could not be checked. Unverified devices are not offered. Check the host drivers and device access.')))
    if not selected and not available:
        ui.message(3,ui.t(N_('No supported device nodes are available. Existing host drivers and native Proxmox device support are required.')))
        return []
    if not selected and not ui.confirm(3,ui.t(N_('Add hardware passthrough?'))):
        return []
    while True:
        occupied = {device['path'] for selection in selected
                    for device in available.get(selection['selection_id'],{}).get('devices',[])}
        choices = NamedChoices([('done',ui.t(N_('Continue')))])
        choices += [(key,hardware_label(ui,item)) for key,item in sorted(available.items())
                    if not occupied.intersection(d['path'] for d in item['devices'])]
        choices += [(f'remove:{index}',ui.t(N_('Remove from plan'))+' '+
                     available.get(item['selection_id'],{}).get('name',item['selection_id']))
                    for index,item in enumerate(selected)]
        choice = ui.choose(3,N_('Select optional hardware'),choices)
        if choice == 'done':
            return selected
        if choice.startswith('remove:'):
            del selected[int(choice.split(':')[1])]
            continue
        item = available[choice]
        if item['profile'] == 'nvidia-runtime':
            ui.message(3,ui.t(N_('NVIDIA includes all host GPUs and their driver runtime. The host driver and NVIDIA Container Toolkit must already work.')))
        if item['profile'] in ('usb','coral') and any('/bus/usb/' in row['path'] for row in item['devices']):
            ui.message(3,ui.t(N_('USB bus numbers can change after reconnecting or rebooting.')))
        selected.append({'profile':item['profile'],'selection_id':choice})


def suggested_hostname(volume):
    name = volume.rsplit('/', 1)[-1].split('_', 1)[0].lower()
    release = re.match(r'([a-z][a-z0-9]*-[0-9]+(?:\.[0-9]+)*)', name)
    if release:
        name = release[1]
    else:
        name = re.sub(r'\.(?:tar.*|tgz)$', '', name)
        name = re.sub(r'[^a-z0-9-]+', '-', name).strip('-')[:63].strip('-')
    return name or 'container'


def edit_group(ui, group, spec, secret, context, navigation=None):
    form = navigation or FormNavigation(ui)
    return form.run(lambda: _edit_group(form, group, spec, secret, context))


def _edit_group(ui, group, spec, secret, context):
    # Commit a group only when all its questions completed. Never prefill a password.
    draft, credentials = deepcopy(spec), deepcopy(secret)
    if group == "system":
        draft["vmid"] = ui.number(1, N_("Container ID (VMID)"), spec.get("vmid", context["next_vmid"]))
        volume, context = ui.template(context, spec.get("template", {}).get("volume_id", ""))
        draft["template"] = {"volume_id": volume}
        if context['templates'][volume]['origin'] == 'local':
            draft['template']['architecture'] = ui.choose(1, N_("Choose the local template architecture"),
                [('amd64', 'amd64'), ('arm64', 'arm64')], default=spec.get('template', {}).get('architecture', context['architecture']))
        old_volume = spec.get('template', {}).get('volume_id', '')
        hostname = spec.get('hostname', '')
        if not hostname or hostname == suggested_hostname(old_volume):
            hostname = suggested_hostname(volume)
        draft['hostname'] = ui.input(1, N_("Container hostname"), hostname)
        nesting_prompt = '\n\n'.join(ui.t(text) for text in
                                     (N_("Enable nesting?"), NESTING_NOTICE, NESTING_COMPATIBILITY_NOTICE))
        draft["nesting"] = ui.confirm(1, nesting_prompt,
                                      default=spec.get("nesting", context["defaults"]["nesting"]))
    elif group == "access":
        draft["access"] = access_fields(ui, spec.get("access"))
        if draft["access"]["mode"] in ("password", "both"):
            if not credentials or not ui.confirm(2, ui.t(N_("Keep the current root password?")), default=True):
                credentials = {"secret": {"password": password_fields(ui)}}
        else:
            credentials = {}
    elif group == "resources":
        defaults = context["defaults"]
        stores = [(name, f'{data["available_bytes"] // (1024 ** 3)} GiB') for name, data in
                  sorted(context["storages"].items()) if "rootdir" in data["content"]]
        if not stores:
            raise WizardError("storage_unavailable")
        rootfs, cpu, memory = spec.get("rootfs", {}), spec.get("cpu", {}), spec.get("memory", {})
        storage = ui.choose(3, N_("Select root disk storage"), stores, default=rootfs.get("storage", ""))
        size = ui.number(3, N_("Root disk size (GiB)"), rootfs.get("size_gib", defaults["rootfs"]["size_gib"]))
        cores = ui.number(3, N_("CPU cores"), cpu.get("cores", defaults["cpu"]["cores"]))
        ram = ui.number(3, N_("RAM (MiB)"), memory.get("ram_mib", defaults["memory"]["ram_mib"]))
        swap = ui.number(3, N_("Swap (MiB)"), memory.get("swap_mib", defaults["memory"]["swap_mib"]))
        draft.update(rootfs={"storage": storage, "size_gib": size}, cpu={"cores": cores},
                     memory={"ram_mib": ram, "swap_mib": swap})
    elif group == "network":
        draft["network"], draft["dns"] = network_fields(ui, context, spec.get("network"), spec.get("dns"))
    elif group == 'mounts':
        draft['mounts'] = mount_fields(ui,spec,context)
    elif group == 'devices':
        draft['hardware'] = device_fields(ui,spec,context)
    elif group == "startup":
        for field, prompt in (("onboot", N_("Start this container when the host boots?")),
                              ("start_after_create", N_("Start this container after creation?")),
                              ("prepare_system", N_("Prepare the system for its first boot? This optional step modifies known systemd units inside the container."))):
            draft[field] = ui.confirm(5, ui.t(prompt), default=spec.get(field, context["defaults"][field]))
    return draft, credentials, context


def review_choice(ui, text, valid):
    choices = [("create", ui.t(N_("Continue to creation confirmation")))] if valid else [
        ("retry", ui.t(N_("Check the configuration again")))]
    labels = {'mounts':N_('Mount points'), 'devices':N_('Hardware')}
    choices += [(key, ui.t(labels.get(key, TITLES[step - 1] if step < 5 else N_("Start options"))))
                for key, step in EDIT_GROUPS]
    choices.append(("close", ui.t(N_("Cancel"))))
    return ui.choose(5, text + "\n\n" + ui.t(N_("Choose what to do next.")), choices, default=choices[0][0])


def load_context(ui):
    with ui.progress(1, N_("Loading Proxmox configuration…")):
        return call("context")


def wizard(ui):
    context = load_context(ui)
    if context.get('operations'):
        pending_operations(ui, context)
        context = load_context(ui)
    spec, secret = {"node": context["node"]}, {}
    index, navigation = 0, {}
    while index < len(EDIT_GROUPS):
        group = EDIT_GROUPS[index][0]
        form = navigation.setdefault(group, FormNavigation(ui))
        try:
            spec, secret, context = edit_group(ui, group, spec, secret, context, form)
        except Back:
            if not index:
                return
            index -= 1
            navigation[EDIT_GROUPS[index][0]].answers = []
            continue
        index += 1
    while True:
        checked = None
        try:
            with ui.progress(5, N_("Checking container configuration…")):
                checked = call("plan", spec=spec)
            plan = checked["plan"]
            spec = deepcopy(plan["spec"])
            review = summary(ui, plan)
            for warning in plan['warnings']:
                review += '\n\n' + ui.t(PLAN_WARNINGS[warning])
        except WizardError as error:
            review = error_text(ui, error)
            ui.message(5, review)
        try:
            choice = review_choice(ui, review, checked is not None)
        except Back:
            choice = 'startup'
        if choice == "close":
            return
        if choice == "create":
            # Invalid drafts never carry a previously checked plan to an action.
            if checked is None:
                continue
            try:
                if ui.confirm(5, ui.t(N_("Create this container?"))):
                    operation(ui, 5, "create", **checked, accepted_warnings=plan["warnings"], **secret)
            except Back:
                continue
            return
        if choice == "retry":
            try:
                context = load_context(ui)
            except WizardError as error:
                ui.message(5, error_text(ui, error))
            continue
        if choice not in dict(EDIT_GROUPS):
            raise Cancelled()
        try:
            # This snapshot only fills the questions. The next plan and the
            # create preflight always obtain and validate a fresh inventory.
            if choice == "system" or checked is None:
                context = load_context(ui)
            spec, secret, context = edit_group(ui, choice, spec, secret, context)
        except (Cancelled, Back):
            # Group edits are transactional; revalidate the unchanged draft.
            pass
        except WizardError as error:
            ui.message(5, error_text(ui, error))


def pending_operations(ui, context):
    for item in context['operations']:
        request_id = item['request_id']
        text = f"{ui.t(N_('Request ID'))}: {request_id}\n" + str(item.get('vmid', item.get('volume_id', '')))
        try:
            choice = ui.choose(5, ui.t(N_("An earlier operation needs to be checked.")) + '\n\n' + text,
                               [('continue', ui.t(N_("Continue to the wizard"))),
                                ('status', ui.t(N_("Check the operation status now?"))),
                                ('recover', ui.t(N_("Check and recover the reservation")))])
            if choice == 'continue':
                continue
            if choice == 'recover' and not ui.confirm(5, ui.t(N_("Recover this reservation without repeating the operation?")) + '\n' + text):
                continue
            result = call('recover', request_id=request_id, confirmed=True) if choice == 'recover' else call('status', request_id=request_id)
            ui.message(5, ui.t(RESULTS[result['status']]) + '\n' + ui.t(RESULTS.get(result.get('reason'), '')) + '\n' + text)
        except WizardError as error:
            ui.message(5, error_text(ui, error))


def main():
    ui = Dialog(sys.argv[1] if len(sys.argv) > 1 else "en")
    try:
        wizard(ui)
    except (Cancelled, KeyboardInterrupt):
        pass
    except WizardError as error:
        ui.message(5, error_text(ui, error))
    finally:
        ui.restore_terminal()


if __name__ == "__main__":
    main()
