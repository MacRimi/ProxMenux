#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
tmp=$(mktemp -d "${QF_ADHOC_DIR:-/tmp}/monitor-tui.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/dropins" "$tmp/run" "$tmp/etc"
export PROXMENUX_TUI_BASE_DIR="$tmp/base"
export PROXMENUX_TUI_BIN_DIR="$tmp/bin"
export PROXMENUX_TUI_DROPIN_DIR="$tmp/dropins"
export PROXMENUX_TUI_TMPFILES="$tmp/etc/tmpfiles.conf"
export PROXMENUX_TUI_RUN_DIR="$tmp/run/monitor"
export PROXMENUX_TUI_TMPDIR="$tmp/run"
export PROXMENUX_TUI_STATE="$tmp/base/monitor-tui.disabled"
export GROUP_STATE="$tmp/group"

cat > "$tmp/bin/getent" <<'SH'
#!/bin/sh
if [ -f "$GROUP_STATE" ]; then cat "$GROUP_STATE"; exit 0; fi
exit 2
SH
cat > "$tmp/bin/groupadd" <<'SH'
#!/bin/sh
echo 'proxmenux-monitor:x:10001:' > "$GROUP_STATE"
SH
cat > "$tmp/bin/groupdel" <<'SH'
#!/bin/sh
[ "${FAIL_GROUPDEL:-0}" = 1 ] && exit 1
rm -f "$GROUP_STATE"
SH
cat > "$tmp/bin/systemd-tmpfiles" <<'SH'
#!/bin/sh
exit 0
SH
cat > "$tmp/bin/systemctl" <<'SH'
#!/bin/sh
echo "$*" >> "$SYSTEMCTL_LOG"
if [ "${FAIL_DAEMON_RELOAD:-0}" = 1 ] && [ "$*" = 'daemon-reload' ]; then exit 1; fi
SH
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH"
export SYSTEMCTL_LOG="$tmp/systemctl.log"

# Ownership claims require the exact marker line; incidental text cannot
# authorize overwriting another component's launcher.
printf '%s\n' '# note: ProxMenux-owned text is not an ownership marker' > "$tmp/bin/proxmenux-monitor"
if "$ROOT/scripts/monitor_tui/lifecycle.sh" install; then
  echo "expected refusal to take over an unowned launcher" >&2; exit 1
fi
grep -q '^# note: ProxMenux-owned text is not an ownership marker$' "$tmp/bin/proxmenux-monitor"
[[ ! -e "$tmp/dropins/90-proxmenux-monitor-tui.conf" ]]
[[ ! -e "$tmp/bin/proxmenux-monitor-tui" ]]
[[ ! -e "$tmp/bin/proxmenux-monitor-getty-pre" ]]
[[ ! -e "$tmp/etc/tmpfiles.conf" ]]
[[ ! -e "$tmp/group" ]]
rm -f "$tmp/bin/proxmenux-monitor"
printf '%s\n' 'foreign getty configuration' > "$tmp/dropins/90-proxmenux-monitor-tui.conf"
if "$ROOT/scripts/monitor_tui/lifecycle.sh" install; then
  echo "expected refusal to take over an unowned getty drop-in" >&2; exit 1
fi
[[ -f "$tmp/dropins/90-proxmenux-monitor-tui.conf" ]]
grep -qx 'foreign getty configuration' "$tmp/dropins/90-proxmenux-monitor-tui.conf"
[[ ! -e "$tmp/bin/proxmenux-monitor" ]]
[[ ! -e "$tmp/bin/proxmenux-monitor-tui" ]]
[[ ! -e "$tmp/etc/tmpfiles.conf" ]]
[[ ! -e "$tmp/group" ]]
"$ROOT/scripts/monitor_tui/lifecycle.sh" uninstall
grep -qx 'foreign getty configuration' "$tmp/dropins/90-proxmenux-monitor-tui.conf"
rm -f "$tmp/dropins/90-proxmenux-monitor-tui.conf"

"$ROOT/scripts/monitor_tui/lifecycle.sh" install
[[ -x "$tmp/bin/proxmenux-monitor" ]]
[[ -f "$tmp/dropins/90-proxmenux-monitor-tui.conf" ]]
grep -q "ExecStartPre=$tmp/bin/proxmenux-monitor-getty-pre" "$tmp/dropins/90-proxmenux-monitor-tui.conf"
grep -q '^TimeoutStartSec=0$' "$tmp/dropins/90-proxmenux-monitor-tui.conf"
! grep -q '^ExecStart=' "$tmp/dropins/90-proxmenux-monitor-tui.conf"
! grep -Eq 'restart|getty@tty1 start' "$SYSTEMCTL_LOG"
cp "$tmp/dropins/90-proxmenux-monitor-tui.conf" "$tmp/dropins/saved.conf"
printf '%s\n' 'foreign modification' > "$tmp/dropins/90-proxmenux-monitor-tui.conf"
if "$ROOT/scripts/monitor_tui/lifecycle.sh" uninstall; then
  echo "expected refusal to delete the getty wrapper beside an unowned drop-in" >&2; exit 1
fi
[[ -x "$tmp/bin/proxmenux-monitor-getty-pre" ]]
grep -qx 'foreign modification' "$tmp/dropins/90-proxmenux-monitor-tui.conf"
mv "$tmp/dropins/saved.conf" "$tmp/dropins/90-proxmenux-monitor-tui.conf"
printf '%s\n' '# ProxMenux-owned TTY1 opt-out state.' > "$tmp/base/monitor-tui.disabled"
"$ROOT/scripts/monitor_tui/lifecycle.sh" install
[[ -f "$tmp/base/monitor-tui.disabled" ]]
"$tmp/bin/proxmenux-monitor-tui" status | grep -qx disabled
"$tmp/bin/proxmenux-monitor-tui" enable
[[ ! -e "$tmp/base/monitor-tui.disabled" ]]
"$tmp/bin/proxmenux-monitor-tui" disable
[[ -f "$tmp/base/monitor-tui.disabled" ]]
printf '%s\n' 'unowned' > "$tmp/base/monitor-tui.disabled"
"$tmp/bin/proxmenux-monitor-tui" status | grep -qx enabled
if "$tmp/bin/proxmenux-monitor-tui" enable; then
  echo "expected refusal to remove unowned opt-out state" >&2; exit 1
fi
printf '%s\n' '# ProxMenux-owned TTY1 opt-out state.' > "$tmp/base/monitor-tui.disabled"
install -d "$tmp/run/monitor"
printf 'foreign snapshot\n' > "$tmp/run/monitor/console.json"
printf 'foreign state\n' > "$tmp/run/monitor/tty1-seen"
"$ROOT/scripts/monitor_tui/lifecycle.sh" uninstall
[[ ! -e "$tmp/dropins/90-proxmenux-monitor-tui.conf" ]]
[[ ! -e "$tmp/bin/proxmenux-monitor-getty-pre" ]]
[[ ! -e "$tmp/base/monitor-tui.disabled" ]]
[[ ! -e "$tmp/group" ]]
[[ -f "$tmp/run/monitor/console.json" ]]
[[ -f "$tmp/run/monitor/tty1-seen" ]]
rm -f "$tmp/run/monitor/console.json" "$tmp/run/monitor/tty1-seen"

"$ROOT/scripts/monitor_tui/lifecycle.sh" install
printf '%s\n' '{"schema_version":1,"publisher":"proxmenux-monitor"}' > "$tmp/run/monitor/console.json"
printf '%s\n' 'ProxMenux TTY1 attempted this boot.' > "$tmp/run/monitor/tty1-seen"
export FAIL_GROUPDEL=1
if "$ROOT/scripts/monitor_tui/lifecycle.sh" uninstall; then
  echo "expected group deletion failure to be reported" >&2; exit 1
fi
[[ -f "$tmp/base/monitor-tui.group-owned" ]]
[[ -f "$tmp/group" ]]
[[ "$(grep -c '^daemon-reload$' "$SYSTEMCTL_LOG")" -ge 2 ]]
unset FAIL_GROUPDEL
"$ROOT/scripts/monitor_tui/lifecycle.sh" uninstall
[[ ! -e "$tmp/run/monitor/console.json" ]]
[[ ! -e "$tmp/run/monitor/tty1-seen" ]]

# The pre-start hook returns to systemd's original getty after opt-out,
# normal exit, and crash; the unit's original ExecStart remains untouched.
cat > "$tmp/bin/fake-tui" <<'SH'
#!/bin/sh
echo "tui:$*" >> "$GETTY_LOG"
exit "${TUI_EXIT:-0}"
SH
cat > "$tmp/bin/fake-getty" <<'SH'
#!/bin/sh
echo "getty:$*" >> "$GETTY_LOG"
SH
cat > "$tmp/bin/fake-setpriv" <<'SH'
#!/bin/sh
if [ "${SETPRIV_FAIL:-0}" = 1 ]; then exit 1; fi
if [ "$1" = --no-new-privs ] && [ "$2" = --reuid=65534 ] &&
   [ "$3" = --regid=65534 ] && [ "$4" = --groups=proxmenux-monitor ] &&
   [ "$5" = --inh-caps=-all ] && [ "$6" = --bounding-set=-all ]; then
  args=$*
else
  exit 90
fi
while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done
shift
if [ "$1" = /bin/true ]; then exit 0; fi
echo "setpriv:$args" >> "$GETTY_LOG"
exec "$@"
SH
cat > "$tmp/bin/fake-runuser" <<'SH'
#!/bin/sh
if [ "$1" != --user ] || [ "$2" != nobody ] || [ "$3" != --group ] || [ "$4" != proxmenux-monitor ]; then exit 91; fi
echo "runuser:$*" >> "$GETTY_LOG"
while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done
shift
exec "$@"
SH
chmod +x "$tmp/bin/fake-tui" "$tmp/bin/fake-getty" "$tmp/bin/fake-setpriv" "$tmp/bin/fake-runuser"
export GETTY_LOG="$tmp/getty.log"
cat > "$tmp/bin/fake-app-run" <<'SH'
#!/bin/sh
echo "manual:$*" >> "$GETTY_LOG"
SH
cat > "$tmp/bin/id" <<'SH'
#!/bin/sh
[ "${1:-}" = -u ] && { echo 0; exit 0; }
exit 1
SH
sed "s|/usr/local/share/proxmenux/monitor-app/AppRun|$tmp/bin/fake-app-run|" \
  "$ROOT/scripts/monitor_tui/proxmenux-monitor" > "$tmp/bin/manual-wrapper"
cp "$tmp/bin/fake-setpriv" "$tmp/bin/setpriv"
chmod +x "$tmp/bin/fake-app-run" "$tmp/bin/id" "$tmp/bin/manual-wrapper" "$tmp/bin/setpriv"
"$tmp/bin/manual-wrapper"
grep -q '^setpriv:--no-new-privs --reuid=65534 --regid=65534 --groups=proxmenux-monitor --inh-caps=-all --bounding-set=-all --' "$GETTY_LOG"
grep -q '^manual:--tui$' "$GETTY_LOG"
rm -f "$tmp/bin/id" "$tmp/bin/setpriv" "$GETTY_LOG"
export PROXMENUX_TUI_STATE="$tmp/base/monitor-tui.disabled"
export PROXMENUX_TUI_SEEN_STATE="$tmp/run/monitor/tty1-seen"
export PROXMENUX_TUI_LAUNCHER="$tmp/bin/fake-tui"
export PROXMENUX_TUI_SETPRIV="$tmp/bin/fake-setpriv"
printf '%s\n' 'unowned state' > "$PROXMENUX_TUI_STATE"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
grep -q '^tui:--tui' "$GETTY_LOG"
rm -f "$GETTY_LOG" "$PROXMENUX_TUI_SEEN_STATE" "$PROXMENUX_TUI_STATE"
printf '%s\n' '# ProxMenux-owned TTY1 opt-out state.' > "$PROXMENUX_TUI_STATE"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
"$tmp/bin/fake-getty" original-getty
grep -q '^getty:original-getty' "$GETTY_LOG"
[[ ! -e "$GETTY_LOG" ]] || ! grep -q '^tui:' "$GETTY_LOG"
rm -f "$GETTY_LOG" "$PROXMENUX_TUI_STATE"
touch "$tmp/not-a-directory"
export PROXMENUX_TUI_SEEN_STATE="$tmp/not-a-directory/seen"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
[[ ! -e "$GETTY_LOG" ]]
rm -f "$tmp/not-a-directory"
export PROXMENUX_TUI_SEEN_STATE="$tmp/run/monitor/tty1-seen"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
"$tmp/bin/fake-getty" original-getty
grep -q '^tui:' "$GETTY_LOG"
grep -q '^getty:original-getty' "$GETTY_LOG"
grep -q '^tui:--tui' "$GETTY_LOG"
grep -q '^setpriv:--no-new-privs --reuid=65534 --regid=65534 --groups=proxmenux-monitor --inh-caps=-all --bounding-set=-all --' "$GETTY_LOG"
# Ctrl-C in the attached TUI must not terminate the ExecStartPre shell.
cat > "$tmp/bin/interrupt-tui" <<'SH'
#!/bin/sh
echo started >> "$GETTY_LOG"
trap 'echo interrupted >> "$GETTY_LOG"; exit 0' INT
while :; do sleep 0.1; done
SH
chmod +x "$tmp/bin/interrupt-tui"
export PROXMENUX_TUI_LAUNCHER="$tmp/bin/interrupt-tui"
export HOOK="$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
export PROXMENUX_TUI_SEEN_STATE="$tmp/run/monitor/tty1-seen"
export PROXMENUX_TUI_SETPRIV="$tmp/bin/fake-setpriv"
rm -f "$GETTY_LOG" "$PROXMENUX_TUI_SEEN_STATE"
python3 - <<'PY'
import fcntl, os, pty, select, signal, struct, termios, time
pid, fd = pty.fork()
if pid == 0:
    os.execv(os.environ["HOOK"], [os.environ["HOOK"]])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
deadline = time.time() + 5
while time.time() < deadline and not os.path.exists(os.environ["GETTY_LOG"]):
    time.sleep(0.05)
time.sleep(0.2)
os.write(fd, b"\x03")
deadline = time.time() + 5
status = None
while time.time() < deadline:
    select.select([fd], [], [], 0.1)
    done, value = os.waitpid(pid, os.WNOHANG)
    if done:
        status = value
        break
if status is None:
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    raise SystemExit("getty pre-start hook did not exit after Ctrl-C")
if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
    raise SystemExit("getty pre-start failed after Ctrl-C: " + repr(status))
with open(os.environ["GETTY_LOG"], encoding="utf-8") as stream:
    log = stream.read()
if "started" not in log or "interrupted" not in log:
    raise SystemExit("TUI did not receive and handle terminal Ctrl-C: " + log)
print("getty pre-start survives foreground Ctrl-C")
PY
rm -f "$GETTY_LOG" "$PROXMENUX_TUI_SEEN_STATE"
export PROXMENUX_TUI_LAUNCHER="$tmp/bin/fake-tui"

# Later TTY1 activations in the same boot do not interrupt subsequent logins.
rm -f "$GETTY_LOG"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
"$tmp/bin/fake-getty" original-getty
! grep -q '^tui:' "$GETTY_LOG"
grep -q '^getty:original-getty' "$GETTY_LOG"
rm -f "$GETTY_LOG"
rm -f "$PROXMENUX_TUI_SEEN_STATE"
export TUI_EXIT=42
export SETPRIV_FAIL=1
export PROXMENUX_TUI_SETPRIV="$tmp/bin/fake-setpriv"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
"$tmp/bin/fake-getty" original-getty
grep -q '^getty:original-getty' "$GETTY_LOG"
! grep -q '^runuser:' "$GETTY_LOG"
! grep -q '^tui:' "$GETTY_LOG"
[[ ! -e "$PROXMENUX_TUI_SEEN_STATE" ]]
unset SETPRIV_FAIL
export TUI_EXIT=0

# A missing runtime skips TUI launch without consuming the boot attempt, so a
# later install/update can make it available on the next getty start.
rm -f "$PROXMENUX_TUI_SEEN_STATE" "$GETTY_LOG"
export PROXMENUX_TUI_LAUNCHER="$tmp/bin/missing-tui"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
[[ ! -e "$PROXMENUX_TUI_SEEN_STATE" ]]
export PROXMENUX_TUI_LAUNCHER="$tmp/bin/fake-tui"
"$ROOT/scripts/monitor_tui/proxmenux-monitor-getty-pre"
[[ -f "$PROXMENUX_TUI_SEEN_STATE" ]]
grep -q '^tui:--tui' "$GETTY_LOG"

# Failure after creating the owned drop-in rolls back only ProxMenux files.
rm -f "$SYSTEMCTL_LOG"
export FAIL_DAEMON_RELOAD=1
if "$ROOT/scripts/monitor_tui/lifecycle.sh" install; then
  echo "expected lifecycle install failure" >&2; exit 1
fi
[[ ! -e "$tmp/dropins/90-proxmenux-monitor-tui.conf" ]]
[[ ! -e "$tmp/bin/proxmenux-monitor-getty-pre" ]]

echo "Monitor TUI lifecycle fixtures passed"
