#!/usr/bin/env python3
"""OCI validation record: renders oci/VALIDATION.md from verification.json,
checks the record, checks who a pull request credits, and records a reviewed
validation report."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
VERIFICATION = ROOT / "oci/catalog/verification.json"
INDEX = ROOT / "oci/catalog/index.json"
OUTPUT = ROOT / "oci/VALIDATION.md"
REVIEWERS = ROOT / ".github/oci-validation-reviewers"

REPO = "https://github.com/MacRimi/ProxMenux"
BOARD = "https://github.com/users/MacRimi/projects/1"
FORM = f"{REPO}/issues/new?template=oci-validation.yml"
DISCUSSION = f"{REPO}/discussions/360"
MAINTAINERS = {"macrimi"}
LAB = "laboratory-validated"

USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
REPORT_RE = re.compile(r"^https://github\.com/MacRimi/ProxMenux/"
                       r"(issues/[0-9]+|discussions/[0-9]+(#discussioncomment-[0-9]+)?)$")
ENTRY_KEYS = {"status", "community_tested"}
COMMUNITY_KEYS = {"by", "date", "report", "digest", "scenario"}
DIGEST_RE = re.compile(r"^[a-f0-9]{8,64}$")
# Form fields that describe the tested scenario, in the order they are read.
SCENARIO_FIELDS = ("Install mode", "Data storage", "Network", "GPU")
NO_RESPONSE = "_No response_"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def applications(index):
    return {item["id"]: item for item in index.get("applications", [])}


def lab_validated(entry, item):
    # Same rule as the catalog: an application that cannot be installed is not verified.
    return entry.get("status") == LAB and bool(item.get("automatic_install_candidate"))


def community(entry):
    tested = entry.get("community_tested")
    return tested if isinstance(tested, dict) and tested.get("by") else None


def cell(text):
    return str(text).replace("|", "\\|").strip()


def render(verification, index):
    apps = applications(index)
    entries = {app: entry for app, entry in verification.get("applications", {}).items()
               if app in apps and isinstance(entry, dict)}
    lab = sorted((app for app, entry in entries.items() if lab_validated(entry, apps[app])),
                 key=lambda app: str(apps[app].get("title") or app).casefold())
    tested = sorted((app for app, entry in entries.items() if community(entry)),
                    key=lambda app: str(apps[app].get("title") or app).casefold())
    visible = sum(1 for item in apps.values() if not item.get("hidden"))
    verified = len(set(lab) | set(tested))
    lines = [
        "# OCI application validation",
        "",
        "<!-- Generated from oci/catalog/verification.json by .github/scripts/oci_validation.py. Do not edit by hand. -->",
        "",
        f"{verified} of {visible} applications in the OCI catalog have been tested for real: "
        f"{len(lab)} in the ProxMenux lab and {len(tested)} by the community. "
        "The OCI installer shows them as verified, with a ✓ in the lists.",
        "",
        "Each test describes the scenario that was run and names the image it ran on. It does not cover every possible "
        "configuration of the application, and a newer image has not been tested until someone reports it.",
        "",
        "## Taking part",
        "",
        "Any application that is not listed here is open for testing.",
        "",
        f"1. Check the [ProxMenux Roadmap]({BOARD}) to see which applications someone is already testing. "
        "With access to the board, create a card for the application and move it to In progress while you test it.",
        f"2. Test the application with the OCI manager and fill in the [OCI validation report]({FORM}). "
        "The report records the image and the exact scenario: install mode, storage, network and GPU.",
        "3. A reviewer reads the report and comments `/validated` on it. The application is then added to this list "
        "with your GitHub user and shown as verified in the OCI installer, and the report is closed.",
        "",
        "Reviewers are listed in [.github/oci-validation-reviewers](../.github/oci-validation-reviewers), and a "
        "reviewer does not validate their own report. A validation can also be added with a pull request that adds "
        "the entry to `oci/catalog/verification.json` and regenerates this file with "
        "`python3 .github/scripts/oci_validation.py render`; CI checks that the entry credits the author of the pull request.",
        "",
        "An application that cannot be validated for a reason outside the tester's hands — hardware nobody has, something "
        "only Docker provides, a fix still pending in ProxMenux — moves to Blocked on the board, with a line saying why "
        "and what would make it worth trying again.",
        "",
        f"Questions and ideas about OCI testing go in [discussion #360]({DISCUSSION}).",
        "",
        "## Tested by the community",
        "",
    ]
    if tested:
        lines += ["| Application | Tested by | Date | Image | Scenario | Report |", "|---|---|---|---|---|---|"]
        for app in tested:
            entry = community(entries[app])
            report = f"[Report]({entry['report']})" if entry.get("report") else "—"
            image = f"`{entry['digest'][:12]}`" if entry.get("digest") else "—"
            lines.append(f"| {cell(apps[app].get('title') or app)} | [@{entry['by']}](https://github.com/{entry['by']}) "
                         f"| {entry.get('date') or '—'} | {image} | {cell(entry.get('scenario') or '—')} | {report} |")
    else:
        lines.append("No application has been tested by the community yet.")
    lines += ["", "## Tested in the ProxMenux lab", ""]
    if lab:
        lines += ["| Application | Category |", "|---|---|"]
        for app in lab:
            lines.append(f"| {cell(apps[app].get('title') or app)} | {cell(apps[app].get('category_label') or '—')} |")
    else:
        lines.append("No application has been tested in the ProxMenux lab yet.")
    return "\n".join(lines) + "\n"


def problems(verification, index, rendered=None, today=None):
    today = today or datetime.date.today()
    apps = applications(index)
    found = []
    entries = verification.get("applications") if isinstance(verification, dict) else None
    if not isinstance(entries, dict):
        return ["verification.json must hold an \"applications\" object"]
    for app, entry in entries.items():
        where = f"verification.json: {app}"
        if app not in apps:
            found.append(f"{where}: not an application of the OCI catalog")
        if not isinstance(entry, dict) or not entry:
            found.append(f"{where}: the entry must be a non-empty object")
            continue
        if set(entry) - ENTRY_KEYS:
            found.append(f"{where}: unknown keys {sorted(set(entry) - ENTRY_KEYS)}")
        if "status" in entry and entry["status"] != LAB:
            found.append(f"{where}: status can only be \"{LAB}\"")
        if "community_tested" not in entry:
            continue
        tested = entry["community_tested"]
        if not isinstance(tested, dict):
            found.append(f"{where}: community_tested must be an object")
            continue
        if set(tested) - COMMUNITY_KEYS:
            found.append(f"{where}: unknown community_tested keys {sorted(set(tested) - COMMUNITY_KEYS)}")
        if not USER_RE.fullmatch(str(tested.get("by", ""))):
            found.append(f"{where}: \"by\" must be a GitHub user name")
        try:
            date = datetime.date.fromisoformat(str(tested.get("date", "")))
            if date > today + datetime.timedelta(days=1):
                found.append(f"{where}: the date is in the future")
        except ValueError:
            found.append(f"{where}: \"date\" must be YYYY-MM-DD")
        if "report" in tested and not REPORT_RE.fullmatch(str(tested["report"])):
            found.append(f"{where}: \"report\" must link to an issue or discussion of MacRimi/ProxMenux")
        if "digest" in tested and not DIGEST_RE.fullmatch(str(tested["digest"])):
            found.append(f"{where}: \"digest\" must be 8 to 64 lowercase hex characters of the image digest")
        if "scenario" in tested and (not isinstance(tested["scenario"], str) or len(tested["scenario"]) > 300):
            found.append(f"{where}: \"scenario\" must be text of at most 300 characters")
    if rendered is not None and rendered != render(verification, index):
        found.append("oci/VALIDATION.md is out of date: run python3 .github/scripts/oci_validation.py render")
    return found


def author_problems(base, head, author):
    """A pull request only adds or changes community tests credited to its author."""
    if author.casefold() in MAINTAINERS:
        return []
    found = []
    before = base.get("applications", {}) if isinstance(base, dict) else {}
    after = head.get("applications", {})
    for app in sorted(set(before) | set(after)):
        old = before.get(app) if isinstance(before.get(app), dict) else {}
        new = after.get(app) if isinstance(after.get(app), dict) else {}
        if old.get("status") != new.get("status"):
            found.append(f"{app}: the ProxMenux lab status is changed by the maintainer only")
        if old.get("community_tested") == new.get("community_tested"):
            continue
        credited = community(new)
        if not credited:
            found.append(f"{app}: a community test is removed by the maintainer only")
        elif str(credited["by"]).casefold() != author.casefold():
            found.append(f"{app}: credits @{credited['by']}, but the pull request is from @{author}")
    return found


def parse_form(body):
    """Issue form answers, keyed by the field label."""
    fields, label, lines = {}, None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            if label is not None:
                fields[label] = "\n".join(lines).strip()
            label, lines = line[4:].strip(), []
        elif label is not None:
            lines.append(line)
    if label is not None:
        fields[label] = "\n".join(lines).strip()
    return {key: ("" if value == NO_RESPONSE else value) for key, value in fields.items()}


def resolve(name, index):
    wanted = " ".join(name.split()).casefold()
    matches = [item["id"] for item in index.get("applications", [])
               if wanted in (str(item["id"]).casefold(), " ".join(str(item.get("title") or "").split()).casefold())]
    return matches[0] if len(matches) == 1 else None


def image_digest(text):
    """The digest as the Monitor shows it (b1f339cf) or in full (sha256:b1f3...)."""
    value = str(text or "").strip().lower()
    value = value.split("·")[-1].strip()
    value = value[7:] if value.startswith("sha256:") else value
    return value if DIGEST_RE.fullmatch(value) else None


def scenario(fields):
    parts = [fields.get(name, "") for name in SCENARIO_FIELDS]
    if fields.get("Proxmox VE version"):
        parts.append(f"Proxmox VE {fields['Proxmox VE version']}")
    if fields.get("Image version"):
        parts.append(f"image {fields['Image version']}")
    text = " · ".join(part.strip() for part in parts if part and part.strip())
    if fields.get("Result") == "Works with problems":
        text = f"Works with problems: {text}"
    return text[:300]


def reviewers(text):
    """User names of the reviewer list, one per line; # starts a comment."""
    names = {line.split("#", 1)[0].strip() for line in text.splitlines()}
    return {name.casefold() for name in names if USER_RE.fullmatch(name)}


def record(event, verification, index, today, allowed=frozenset()):
    """Returns (verification, app id, message); raises ValueError with the reason to refuse.

    A label can only be added by someone with write access to the repository.
    A /validated comment is accepted from the reviewer list, never from the
    report's own author unless it is the maintainer."""
    issue = event.get("issue") or {}
    labels = {label.get("name") for label in issue.get("labels", [])}
    if "oci-validation" not in labels:
        raise ValueError("This issue is not an OCI validation report.")
    author = str((issue.get("user") or {}).get("login", ""))
    report = str(issue.get("html_url", ""))
    if not USER_RE.fullmatch(author) or not REPORT_RE.fullmatch(report):
        raise ValueError("The report author or link could not be read.")
    reviewer = str(((event.get("comment") or {}).get("user") or {}).get("login", ""))
    if event.get("comment") is not None:
        if reviewer.casefold() not in allowed:
            raise ValueError(f"@{reviewer} is not in the list of OCI validation reviewers "
                             "(.github/oci-validation-reviewers), so the report is not recorded.")
        if reviewer.casefold() == author.casefold() and reviewer.casefold() not in MAINTAINERS:
            raise ValueError("A report is validated by a reviewer other than its author.")
    fields = parse_form(issue.get("body"))
    name = fields.get("Application", "")
    app = resolve(name, index)
    if app is None:
        raise ValueError(f"\"{name}\" does not match one application of the OCI catalog. "
                         "Edit the Application field with its name or ID as shown in the catalog, then add the label again.")
    if fields.get("Result") == "Does not work":
        raise ValueError("The report says the application does not work, so it is not recorded as verified.")
    digest = image_digest(fields.get("Image digest"))
    if digest is None:
        raise ValueError("The Image digest field does not hold an image digest. Edit it with the digest shown in the "
                         "App tab of the Monitor, for example b1f339cf, then add the label again.")
    data = json.loads(json.dumps(verification))
    entries = data.setdefault("applications", {})
    entry = entries.setdefault(app, {})
    previous = community(entry)
    entry["community_tested"] = {"by": author, "date": today.isoformat(), "report": report,
                                 "digest": digest, "scenario": scenario(fields)}
    data["applications"] = dict(sorted(entries.items()))
    title = applications(index)[app].get("title") or app
    validated = f" Validated by @{reviewer}." if reviewer else ""
    message = (f"Thank you, @{author}! {title} is now recorded as verified.{validated} "
               f"It shows with a ✓ in the OCI installer and is listed in [oci/VALIDATION.md]({REPO}/blob/develop/oci/VALIDATION.md).")
    if previous and previous.get("by") != author:
        message += f" This report replaces the previous one from @{previous['by']}."
    return data, app, message


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("render", help="Write oci/VALIDATION.md")
    commands.add_parser("check", help="Check verification.json and that oci/VALIDATION.md is current")
    authors = commands.add_parser("authors", help="Check who a pull request credits")
    authors.add_argument("--base", required=True, help="verification.json of the base branch; may be missing")
    authors.add_argument("--author", required=True)
    rec = commands.add_parser("record", help="Record a reviewed validation report")
    rec.add_argument("--event", required=True)
    rec.add_argument("--message", required=True, help="File that receives the reply for the issue")
    args = parser.parse_args(argv)

    verification, index = load(VERIFICATION), load(INDEX)
    if args.command == "render":
        OUTPUT.write_text(render(verification, index), encoding="utf-8")
        return 0
    if args.command == "check":
        rendered = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        found = problems(verification, index, rendered)
    elif args.command == "authors":
        base = load(args.base) if Path(args.base).exists() and Path(args.base).stat().st_size else {}
        found = author_problems(base, verification, args.author)
    else:
        try:
            allowed = reviewers(REVIEWERS.read_text(encoding="utf-8")) if REVIEWERS.exists() else frozenset()
            data, app, message = record(load(args.event), verification, index, datetime.date.today(), allowed)
        except ValueError as error:
            Path(args.message).write_text(str(error) + "\n", encoding="utf-8")
            return 2
        VERIFICATION.write_text(dump(data), encoding="utf-8")
        OUTPUT.write_text(render(data, index), encoding="utf-8")
        Path(args.message).write_text(message + "\n", encoding="utf-8")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"app={app}\n")
        return 0
    for problem in found:
        print(f"::error::{problem}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
