"""Run only the Bashrc functions, with all root files in a private fixture."""

import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
FLOWS = ("auto_post_install.sh", "customizable_post_install.sh")
BEGIN = b"# BEGIN PMX_CORE_BASHRC\n"
END = b"# END PMX_CORE_BASHRC\n"
# The unmarked block shipped in v1.1.3 (fc974995), without its leading blank line.
LEGACY = rb'''# ProxMenux customizations
export HISTTIMEFORMAT="%d/%m/%y %T "
export PS1="\[\e[31m\][\[\e[m\]\[\e[38;5;172m\]\u\[\e[m\]@\[\e[38;5;153m\]\h\[\e[m\] \[\e[38;5;214m\]\W\[\e[m\]\[\e[31m\]]\[\e[m\]\\$ "
alias l='ls -CF'
alias la='ls -A'
alias ll='ls -alF'
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'
source /etc/profile.d/bash_completion.sh
'''


def extract(source, name):
    match = re.search(rf"(?ms)^{name}\(\) \{{\n.*?^\}}$", source)
    if match is None:
        raise AssertionError(f"missing function: {name}")
    return match.group()


class BashrcMigrationTests(unittest.TestCase):
    def run_flow(self, flow, original, times=1, injection="", style=""):
        with tempfile.TemporaryDirectory(prefix="bashrc-migration-") as temporary:
            work = Path(temporary)
            bashrc = work / ".bashrc"
            bashrc.write_bytes(original)
            bashrc.chmod(0o640)
            before = bashrc.stat()
            (work / "bin").mkdir()
            # The embedded Python must use the interpreter running this test.
            (work / "bin/python3").symlink_to(sys.executable)
            source = (ROOT / "scripts/post_install" / flow).read_text()
            functions = "\n".join(extract(source, name) for name in
                                  ("_migrate_proxmenux_bashrc", "customize_bashrc"))
            # Relocate only the fixture copy; never source the administrative script.
            functions = functions.replace("/root/", str(work) + "/")
            prelude = f'source {shlex.quote(str(ROOT / "scripts/global/pmx_journal.sh"))}\n'
            prelude += r'''
translate() { printf '%s' "$1"; }
msg_info() { :; }
msg_info2() { :; }
msg_warn() { :; }
msg_error() { printf '%s\n' "$*" >&2; }
msg_ok() { printf 'success\n' >> "$FIXTURE_ROOT/messages"; }
register_tool() { printf '%s|%s|%s\n' "$@" >> "$FIXTURE_ROOT/registry"; }
'''
            calls = "\n".join(
                f'customize_bashrc; rc=$?; printf "%s\\n" "$rc" >> "$FIXTURE_ROOT/status"; '
                f'cp "$FIXTURE_ROOT/.bashrc" "$FIXTURE_ROOT/pass-{i}"'
                for i in range(times))
            env = os.environ.copy()
            env.update(HOME=str(work), FIXTURE_ROOT=str(work), TMPDIR=str(work),
                       PMX_JOURNAL_ROOT=str(work / "journal"), PMX_BASHRC_PATH_STYLE=style,
                       PATH=str(work / "bin") + os.pathsep + env.get("PATH", ""))
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c",
                 prelude + functions + "\n" + injection + "\n" + calls],
                cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = bashrc.stat()
            def read(name):
                path = work / name
                return path.read_bytes() if path.exists() else b""
            return {
                "passes": [read(f"pass-{i}") for i in range(times)],
                "status": read("status").splitlines(), "registry": read("registry"),
                "messages": read("messages"), "backup": read(".bashrc.bak"),
                "profile": read(".bash_profile"), "stderr": result.stderr,
                "detected_style": read("style"),
                "before": (stat.S_IMODE(before.st_mode), before.st_uid, before.st_gid),
                "after": (stat.S_IMODE(after.st_mode), after.st_uid, after.st_gid),
                "inode_before": before.st_ino, "inode_after": after.st_ino,
                "leftovers": [p.name for p in work.iterdir() if "proxmenux" in p.name],
                "journal": [json.loads(p.read_text()) for p in
                            sorted((work / "journal/spool").glob("*.json"))],
            }

    def test_inspect_detects_style_without_rewriting_the_original(self):
        for flow in FLOWS:
            for block in (LEGACY, LEGACY.replace(rb"\W", rb"\w")):
                with self.subTest(flow=flow, full=rb"\w" in block):
                    injection = r'''customize_bashrc() {
    _migrate_proxmenux_bashrc "$FIXTURE_ROOT/.bashrc" inspect > "$FIXTURE_ROOT/style"
}'''
                    run = self.run_flow(flow, block, injection=injection)
                    self.assertEqual(run["status"], [b"0"], run["stderr"])
                    self.assertEqual(run["passes"], [block])
                    self.assertEqual(run["detected_style"], b"full\n" if rb"\w" in block else b"short\n")
                    self.assertEqual(run["inode_before"], run["inode_after"])
                    self.assertEqual(run["backup"], b"")
                    self.assertEqual(run["registry"], b"")
                    self.assertEqual(run["journal"], [])

    def test_historical_blocks_migrate_once_with_prompt_backup_and_journal(self):
        for flow in FLOWS:
            for full in (False, True):
                legacy = LEGACY.replace(rb"\W", rb"\w") if full else LEGACY
                blocks = (legacy, b"${marker_begin}\n" + legacy + b"${marker_end}\n",
                          BEGIN + legacy + END, legacy + BEGIN + legacy + END)
                for block in blocks:
                    with self.subTest(flow=flow, full=full, block=block[:40]):
                        original = b"# user prefix\n" + block + b"# user suffix\n"
                        run = self.run_flow(flow, original, times=2)
                        self.assertEqual(run["status"], [b"0", b"0"], run["stderr"])
                        first, second = run["passes"]
                        self.assertEqual(first, second)
                        self.assertTrue(first.startswith(b"# user prefix\n# user suffix\n"))
                        self.assertEqual(first.count(BEGIN), 1)
                        self.assertEqual(first.count(END), 1)
                        self.assertEqual(first.count(b"alias ll="), 1)
                        self.assertNotIn(b"${marker_", first)
                        self.assertIn(rb"\w" if full else rb"\W", first)
                        self.assertEqual(run["backup"], original)
                        self.assertEqual(len(run["profile"].splitlines()), 1)
                        self.assertEqual(run["registry"], b"bashrc_custom|true|1.3\n" * 2)
                        self.assertEqual(run["before"], run["after"])
                        self.assertEqual(run["leftovers"], [])
                        entries = [e for e in run["journal"] if e["target"].endswith("/.bashrc")]
                        self.assertEqual(len(entries), 1)
                        entry = entries[0]
                        self.assertEqual(entry["operation"], "write_file")
                        self.assertEqual(entry["exactness"], "exact")
                        self.assertEqual(entry["capture"], "present")
                        self.assertNotEqual(entry["before"], entry["after"])
                        self.assertTrue(all("proxmenux." not in e["target"] for e in run["journal"]))
                        syntax = subprocess.run(["bash", "-n"], input=first, capture_output=True)
                        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_incomplete_and_oversized_ranges_are_preserved_on_rerun(self):
        fragments = (LEGACY.rsplit(b"source", 1)[0], END,
                     b"${marker_begin}\n# user\n", b"${marker_end}\n",
                     BEGIN + b"# user\n" * 33 + END,
                     b"${marker_begin}\n" + b"# user\n" * 33 + b"${marker_end}\n",
                     BEGIN + b"# user\n${marker_begin}\n# inner\n${marker_end}\n# suffix\n")
        for flow in FLOWS:
            for fragment in fragments:
                with self.subTest(flow=flow, fragment=fragment[:40]):
                    run = self.run_flow(flow, fragment, times=2)
                    self.assertEqual(run["status"], [b"0", b"0"], run["stderr"])
                    # Complete inner ranges can migrate, but their outer prefix cannot.
                    preserved = BEGIN + b"# user\n# suffix\n" if b"# inner" in fragment else fragment
                    self.assertTrue(run["passes"][0].startswith(preserved))
                    self.assertEqual(run["passes"][0], run["passes"][1])

    def test_nested_ranges_with_outer_end_are_preserved_on_repeated_runs(self):
        markers = ((BEGIN, END), (b"${marker_begin}\n", b"${marker_end}\n"))
        for flow in FLOWS:
            for outer_begin, outer_end in markers:
                for inner_begin, inner_end in markers:
                    with self.subTest(flow=flow, outer=outer_begin, inner=inner_begin):
                        original = (outer_begin + b"# OUTER_USER_PREFIX\n"
                                    b"user_function() { :; }\n" + inner_begin
                                    + b"# old inner block\n" + inner_end
                                    + b"# OUTER_USER_SUFFIX\n" + outer_end)
                        run = self.run_flow(flow, original, times=3)
                        self.assertEqual(run["status"], [b"0"] * 3, run["stderr"])
                        for content in run["passes"]:
                            self.assertTrue(content.startswith(original), content)
                            self.assertEqual(content.count(BEGIN), original.count(BEGIN) + 1)
                            self.assertEqual(content.count(END), original.count(END) + 1)
                            self.assertEqual(content.count(b"# ProxMenux core customizations\n"), 1)
                        self.assertEqual(run["passes"], [run["passes"][0]] * 3)
                        self.assertEqual(run["backup"], original)

    def test_crossed_marker_families_preserve_every_byte_on_repeated_runs(self):
        markers = ((BEGIN, END), (b"${marker_begin}\n", b"${marker_end}\n"))
        for flow in FLOWS:
            canonical = self.run_flow(flow, b"")["passes"][0]
            for outer, inner in (markers, markers[::-1]):
                for newline in (b"\n", b"\r\n"):
                    with self.subTest(flow=flow, outer=outer[0], newline=newline):
                        original = (outer[0] + b"user_prefix() { :; } # \xff\n"
                                    + inner[0] + outer[1]
                                    + b"user_suffix() { :; }\n" + inner[1])
                        original = original.replace(b"\n", newline)
                        run = self.run_flow(flow, original, times=3)
                        self.assertEqual(run["status"], [b"0"] * 3, run["stderr"])
                        self.assertEqual(run["passes"], [original + canonical] * 3)
                        self.assertEqual(run["backup"], original)
                        self.assertEqual(run["registry"], b"bashrc_custom|true|1.3\n" * 3)

    def test_marker_ambiguity_matrix_preserves_spans_without_capturing_separate_blocks(self):
        markers = ((BEGIN, END), (b"${marker_begin}\n", b"${marker_end}\n"))
        prefix = b"user_prefix() { :; }\n"
        suffix = b"user_suffix() { :; }\n"
        for flow in FLOWS:
            canonical = self.run_flow(flow, b"")["passes"][0]
            for (begin, end), (foreign_begin, foreign_end) in (markers, markers[::-1]):
                # Each malformed complete span is ambiguous, even if the foreign
                # token has no partner. Never expose its user bytes on a rerun.
                ambiguous = {
                    "unmatched-inner-begin": begin + prefix + foreign_begin + suffix + end,
                    "unmatched-foreign-end": begin + prefix + foreign_end + suffix + end,
                    "inner-begin-extra-end": begin + prefix + foreign_begin + end + suffix + end,
                    "nested-with-stray-end": (begin + prefix + foreign_begin + end
                                              + foreign_end + suffix + end),
                    "overlap-chain": (begin + prefix + foreign_begin + end + begin
                                      + foreign_end + suffix + end),
                    "ambiguous-legacy-signature": (begin + prefix + foreign_end
                                                   + LEGACY + suffix + end),
                    "oversized-ambiguous-span": (begin + prefix + foreign_end
                                                 + b"# user\n" * 33 + suffix + end),
                }
                cases = [(name, fragment, fragment) for name, fragment in ambiguous.items()]
                # An unclosed old BEGIN is not an enclosing range. Its prefix
                # must survive, but independent complete blocks must still migrate.
                cases.extend([
                    ("orphan-before-same-family", begin + prefix + begin + b"old\n" + end + suffix,
                     begin + prefix + suffix),
                    ("orphan-before-other-family", begin + prefix + foreign_begin + b"old\n"
                     + foreign_end + suffix, begin + prefix + suffix),
                    ("missing-outer-end", begin + prefix + foreign_begin + b"old\n"
                     + foreign_end + suffix + foreign_end, begin + prefix + suffix + foreign_end),
                    ("separated-valid-blocks", foreign_end + prefix + begin + b"old\n" + end
                     + suffix + foreign_begin + b"old\n" + foreign_end + foreign_begin,
                     foreign_end + prefix + suffix + foreign_begin),
                    ("limit-32", begin + b"# old\n" * 31 + end + suffix, suffix),
                    ("over-limit-33", begin + b"# user\n" * 32 + end + suffix,
                     begin + b"# user\n" * 32 + end + suffix),
                ])
                for name, original, preserved in cases:
                    with self.subTest(flow=flow, family=begin, case=name):
                        run = self.run_flow(flow, original, times=3)
                        self.assertEqual(run["status"], [b"0"] * 3, run["stderr"])
                        self.assertEqual(run["passes"], [preserved + canonical] * 3)
                        self.assertEqual(run["backup"], original)
                        self.assertEqual(run["before"], run["after"])
                        self.assertEqual(run["leftovers"], [])

    def test_path_override_and_empty_install_remain_idempotent(self):
        for flow in FLOWS:
            for style in ("short", "full"):
                with self.subTest(flow=flow, style=style):
                    run = self.run_flow(flow, b"", times=2, style=style)
                    self.assertEqual(run["status"], [b"0", b"0"], run["stderr"])
                    self.assertEqual(run["passes"][0], run["passes"][1])
                    self.assertIn(rb"\w" if style == "full" else rb"\W", run["passes"][0])

    def test_preparation_and_commit_failures_leave_bashrc_untouched(self):
        failures = {
            "inspect": 'python3() { [[ "$3" == inspect ]] && return 71; command python3 "$@"; }',
            "migrate": 'python3() { [[ "$3" == migrate ]] && return 71; command python3 "$@"; }',
            "replace": '''python3() {
                command python3 -c 'import os, sys
sys.argv = sys.argv[1:]
def fail(*args):
    raise OSError("injected replace failure")
os.replace = fail
exec(sys.stdin.read())' "$@"
            }''',
            "backup": 'cp() { [[ "${@: -1}" == *.bak ]] && return 71; command cp "$@"; }',
            "mktemp": 'mktemp() { return 71; }',
            "copy": 'cp() { if [[ "$1" == -p ]]; then printf partial > "$3"; return 71; fi; command cp "$@"; }',
            "profile": 'pmx_append_file() { return 71; }',
            "commit": 'mv() { [[ "${@: -1}" == "$FIXTURE_ROOT/.bashrc" ]] && return 71; command mv "$@"; }',
        }
        original = b"# user\n" + LEGACY
        for flow in FLOWS:
            for failure, injection in failures.items():
                with self.subTest(flow=flow, failure=failure):
                    run = self.run_flow(flow, original, injection=injection)
                    self.assertNotEqual(run["status"], [b"0"], run["stderr"])
                    self.assertEqual(run["passes"], [original])
                    self.assertEqual(run["before"], run["after"])
                    self.assertEqual(run["inode_before"], run["inode_after"])
                    self.assertEqual(run["registry"], b"")
                    self.assertEqual(run["messages"], b"")
                    self.assertEqual(run["leftovers"], [])
                    self.assertFalse(any(e["target"].endswith("/.bashrc") for e in run["journal"]))
            with self.subTest(flow=flow, failure="invalid-style"):
                run = self.run_flow(flow, original, style="invalid")
                self.assertNotEqual(run["status"], [b"0"])
                self.assertEqual(run["passes"], [original])
                self.assertEqual(run["registry"], b"")

    def test_migration_preserves_unrelated_non_utf8_bytes_and_line_endings(self):
        prefix = b"# user bytes: \xff\r\n"
        suffix = b"user_function() { :; }\r\n"
        original = prefix + BEGIN + b"old block\n" + END + suffix
        for flow in FLOWS:
            with self.subTest(flow=flow):
                run = self.run_flow(flow, original, times=2)
                self.assertEqual(run["status"], [b"0", b"0"], run["stderr"])
                self.assertTrue(run["passes"][0].startswith(prefix + suffix))
                self.assertEqual(run["passes"][0], run["passes"][1])
                self.assertEqual(run["before"], run["after"])

    def test_failed_block_write_preserves_original_without_success(self):
        original = b"# user content\n" + BEGIN + b"old managed block\n" + END
        # Fail the real stdin writer after a partial canonical-block write.
        # The override is confined to this shell fixture, not production.
        injection = r'''
cat() {
    if [[ $# == 0 ]]; then
        local first
        IFS= read -r first
        if [[ "$first" == '# BEGIN PMX_CORE_BASHRC' ]]; then
            printf '# partial block'
            return 71
        fi
        printf '%s\n' "$first"
    fi
    command cat "$@"
}
'''
        for flow in FLOWS:
            with self.subTest(flow=flow):
                run = self.run_flow(flow, original, injection=injection)
                self.assertNotEqual(run["status"], [b"0"], run["stderr"])
                self.assertEqual(run["passes"], [original])
                self.assertEqual(run["before"], run["after"])
                self.assertEqual(run["inode_before"], run["inode_after"])
                self.assertEqual(run["registry"], b"")
                self.assertEqual(run["messages"], b"")
                self.assertEqual(run["leftovers"], [])

    def test_orphan_begin_cannot_consume_user_content_on_rerun(self):
        original = BEGIN + b"user_function() { :; }\n# user suffix\n"
        for flow in FLOWS:
            with self.subTest(flow=flow):
                run = self.run_flow(flow, original, times=2)
                self.assertEqual(run["status"], [b"0", b"0"], run["stderr"])
                for content in run["passes"]:
                    self.assertTrue(content.startswith(original), content)
                self.assertEqual(run["passes"][0], run["passes"][1])


if __name__ == "__main__":
    unittest.main()
