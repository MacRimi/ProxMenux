#!/usr/bin/env python3
"""Checks a journal migration without reading the whole script.

Migrating a function to the change journal must not change what the
function does — only how it writes. That is a narrow claim, and a narrow
claim can be verified mechanically, which is the point of this: reviewing
a four-thousand-line shell script by eye is how a byte-level difference
in a configuration file gets shipped.

Run it against the pre-migration version of the same file:

    verify_journal_migration.py --before original.sh --after migrated.sh

The pre-migration version is whatever the repository had before the work
started, for example:

    git show HEAD:scripts/post_install/customizable_post_install.sh
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Writes that reach the host. A heredoc into /tmp is a composition step,
# not a change, so paths under /tmp are excluded from the search.
DIRECT_WRITE = re.compile(
    r"""(?x)
    (?:cat|printf|echo|tee)\s*(?:<<-?\s*['"]?\w+['"]?\s*)?>{1,2}\s*["']?(?:/etc|/usr|/var|/boot|/root|\$\{?(?:config_file|sysctl_conf|conf|target))
    | sed\s+-i(?!\s+[^|;&]*\s/tmp/)
    | systemctl\s+(?:enable|disable)\s+--now
    """)

# A heredoc body: what the function actually writes. The delimiter is
# usually followed by a redirection on the same line — `<<EOF > "$file"`
# — so everything up to the newline is skipped before the body starts.
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)^\1\s*$", re.M | re.S)

# A backup the uninstaller may restore from. The path is often a
# variable — `cp -n "$conf" "$backup_conf"` — so the copy itself is what
# is matched, not the .bak suffix.
BACKUP = re.compile(r"cp\s+(?:-n\s+)?[^\n]*(?:\.bak|backup_conf|_backup|\bbackup\b)")


# Both declaration forms bash accepts, because a file written in the
# `function name() {` style used to yield no functions at all: the
# walker saw none, the sanity check counted none, the two agreed, and
# the file passed without a single one of its bodies being read.
FUNC_START = re.compile(
    r"^(?:function\s+([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\(\))?"
    r"|([A-Za-z_][A-Za-z0-9_-]*)\s*\(\))\s*\{\s*$", re.M)
HEREDOC_START = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")


def functions(source: str) -> list[tuple[str, str]]:
    """Every top-level shell function and its body, in declaration order.

    A list rather than a mapping because a script may declare the same
    name twice — the later definition is the one bash keeps, but both are
    in the file. Keyed by name, the first body vanished and its lines
    were then counted as top-level code that nothing had recorded.

    Walked line by line rather than matched with a regular expression,
    because these scripts embed whole files in heredocs and several of
    those contain a closing brace in the first column — a systemd unit,
    an awk program, a shell script being installed. A regex that ends the
    function at the first such line cuts it in half, and everything after
    the cut looks like top-level code that nothing is checking.
    """
    found: list[tuple[str, str]] = []
    lines = source.splitlines()
    i, total = 0, len(lines)
    while i < total:
        match = FUNC_START.match(lines[i])
        if not match:
            i += 1
            continue
        name = match.group(1) or match.group(2)
        body, depth, delimiter = [], 1, None
        i += 1
        while i < total and depth > 0:
            line = lines[i]
            if delimiter is not None:
                # Inside a heredoc nothing counts as shell syntax. The
                # closing line is usually the delimiter alone, but these
                # scripts also nest heredocs inside quoted strings passed
                # to `pct exec`, where the terminator carries the closing
                # quote: `EOF"`. Treating only the exact form as a close
                # swallows the rest of the file and silently merges every
                # function after it.
                stripped = line.strip()
                if stripped == delimiter or (
                        stripped.startswith(delimiter)
                        and stripped[len(delimiter):].strip(" \"';)") == ""):
                    delimiter = None
            else:
                opened = HEREDOC_START.search(line)
                if opened:
                    delimiter = opened.group(1)
                elif line == "}":
                    depth -= 1
                    if depth == 0:
                        break
            body.append(line)
            i += 1
        found.append((name, "\n".join(body)))
        i += 1
    return found


def heredocs(body: str) -> list[str]:
    """Contents written by a function, in order, ignoring the delimiters."""
    return [text for _, text in HEREDOC.findall(body)]


def _without_heredocs(source: str) -> str:
    """The script with heredoc bodies removed, line count preserved.

    What a script writes into a file is content, not code: a function
    declared inside a heredoc belongs to the file being installed.
    """
    out, delimiter = [], None
    for line in source.splitlines():
        if delimiter is not None:
            stripped = line.strip()
            if stripped == delimiter or (
                    stripped.startswith(delimiter)
                    and stripped[len(delimiter):].strip(" \"';)") == ""):
                delimiter = None
            out.append("")
            continue
        opened = HEREDOC_START.search(line)
        out.append(line)
        if opened:
            delimiter = opened.group(1)
    return "\n".join(out)


def _top_level(source: str) -> str:
    """The script with every function body removed.

    Built by subtracting the bodies the walker found, so a heredoc
    containing a closing brace cannot make half a function look like
    top-level code.
    """
    remaining = source
    for _, body in functions(source):
        if body:
            remaining = remaining.replace(body, "", 1)
    return remaining


def _heredocs_of(source: str) -> list[str]:
    return [text for _, text in HEREDOC.findall(source)]


def check(before_path: Path, after_path: Path) -> int:
    before = functions(before_path.read_text())
    after = functions(after_path.read_text())
    problems: list[str] = []
    migrated: list[str] = []

    # The file has to be valid shell before anything else is worth saying.
    syntax = subprocess.run(["bash", "-n", str(after_path)],
                            capture_output=True, text=True)
    if syntax.returncode != 0:
        print(f"FAIL  bash -n: {syntax.stderr.strip()}")
        return 1

    before_by_name: dict[str, list[str]] = {}
    for name, body in before:
        before_by_name.setdefault(name, []).append(body)
    after_by_name: dict[str, list[str]] = {}
    for name, body in after:
        after_by_name.setdefault(name, []).append(body)

    gone = sorted(set(before_by_name) - set(after_by_name))
    if gone:
        problems.append(f"functions removed: {', '.join(gone)}")

    # A name declared more than once is a property of the script, not a
    # fault in the migration. Stated so the reader knows which body the
    # results below belong to, and not counted against the file.
    repeated = sorted(n for n, bodies in after_by_name.items() if len(bodies) > 1)
    for name in repeated:
        print(f"note: {name} is declared {len(after_by_name[name])} times; "
              f"each declaration is checked against its own original")

    # Sanity: the walker must find every function the file declares. If
    # it finds fewer, it merged some, and everything it reported about
    # them is unreliable — a green result on a file it did not read.
    #
    # Counted with the heredocs removed, because these scripts install
    # other scripts by writing them out, and a function declared inside
    # one of those belongs to the installed file, not to this one.
    declared = len(FUNC_START.findall(_without_heredocs(after_path.read_text())))
    if declared != len(after):
        problems.append(
            f"parser found {len(after)} functions but the file declares "
            f"{declared}; the result cannot be trusted")

    # Everything above only looks inside functions. A script that acts at
    # the top level — and several do — was invisible to this check, which
    # is exactly where an unrecorded write would hide.
    outside_before = _top_level(before_path.read_text())
    outside_after = _top_level(after_path.read_text())
    if "pmx_journal" in outside_after or any(
            "pmx_journal_context" in body for _, body in after):
        # Scanned with the heredoc bodies blanked: a script that installs
        # another script writes that script's own `sed -i` lines as
        # content, and the contract forbids touching what is written.
        direct = [m.group(0).strip()
                  for m in DIRECT_WRITE.finditer(_without_heredocs(outside_after))]
        if direct:
            problems.append(
                f"top level: {len(direct)} write(s) still reach the host directly — "
                f"{direct[0][:70]}")
    if _heredocs_of(outside_before) != _heredocs_of(outside_after):
        problems.append("top level: the content written outside any function changed")

    occurrence: dict[str, int] = {}
    for name, body in after:
        index = occurrence.get(name, 0)
        occurrence[name] = index + 1
        if "pmx_journal_context" not in body:
            continue
        migrated.append(name if index == 0 else f"{name} (declaration {index + 1})")
        originals = before_by_name.get(name, [])
        if index >= len(originals):
            problems.append(f"{name}: declaration {index + 1} was not present "
                            f"before the migration")
            continue
        original = originals[index]

        # 1. One context, naming the function it sits in.
        contexts = re.findall(r'pmx_journal_context\s+"([^"]+)"', body)
        if len(contexts) != 1:
            problems.append(f"{name}: {len(contexts)} calls to pmx_journal_context, expected 1")
        elif contexts[0] != name:
            problems.append(f"{name}: context declares '{contexts[0]}'")

        # 2. Nothing still writes to the host directly. The heredoc
        #    bodies are blanked first: a `sed -i` inside a script this
        #    function installs is that script's line, not this one's, and
        #    rewriting it is exactly what the contract forbids.
        direct = [m.group(0).strip()
                  for m in DIRECT_WRITE.finditer(_without_heredocs(body))]
        if direct:
            problems.append(f"{name}: still writes directly — {direct[0][:70]}")

        # 3. What it writes has to be what it wrote before. This is the
        #    check that matters: a migration that alters a configuration
        #    file by one byte is a behaviour change wearing a refactor.
        if heredocs(original) != heredocs(body):
            before_docs, after_docs = heredocs(original), heredocs(body)
            if len(before_docs) != len(after_docs):
                problems.append(
                    f"{name}: wrote {len(before_docs)} block(s) before, {len(after_docs)} now")
            else:
                for i, (was, now) in enumerate(zip(before_docs, after_docs)):
                    if was != now:
                        problems.append(f"{name}: content of block {i + 1} changed")

        # 4. A backup the uninstaller depends on must survive.
        if BACKUP.search(original) and not BACKUP.search(body):
            problems.append(f"{name}: the .bak copy was removed; "
                            f"uninstall-tools.sh restores from it")

        # 5. Registration is untouched.
        if original.count("register_tool") != body.count("register_tool"):
            problems.append(f"{name}: register_tool calls changed")

    print(f"functions migrated: {len(migrated)}")
    for name in migrated:
        print(f"  {name}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("\nno problems found")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    args = parser.parse_args()
    return check(args.before, args.after)


if __name__ == "__main__":
    sys.exit(main())
