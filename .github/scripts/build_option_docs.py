#!/usr/bin/env python3
"""Copy the short description of each documentation page a menu option links
to into scripts/menus/option_docs.json, in every language of the docs.

The Monitor's Catalog tab shows it in the sheet of a ProxMenux option. The text
lives in the website docs and is translated there; this file only carries it
to the host, where the website is not installed.

    python3 .github/scripts/build_option_docs.py          # write the file
    python3 .github/scripts/build_option_docs.py --check  # fail if it is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "web/messages"
INDEX = ROOT / "scripts/menus/search_index.json"
SEARCH = ROOT / "scripts/menus/search_menu.py"
OUTPUT = ROOT / "scripts/menus/option_docs.json"


def linked_pages() -> set[str]:
    pages = {item["docs"] for item in json.loads(INDEX.read_text(encoding="utf-8")) if item.get("docs")}
    source = SEARCH.read_text(encoding="utf-8")
    block = re.search(r"POST_INSTALL_DOCS = \{(.*?)\}", source, re.S)
    pages |= set(re.findall(r"'(post-install/[a-z-]+)'", block.group(1) if block else ""))
    pages |= set(re.findall(r"docs='([a-z0-9/-]+)'", source))
    # A setting of the post-installation script is explained by its section.
    block = re.search(r"POST_INSTALL_SECTIONS = \{(.*?)\}", source, re.S)
    pages |= set(re.findall(r"'(post-install/[a-z-]+#[A-Za-z0-9]+)'", block.group(1) if block else ""))
    return pages


def plain(text: str) -> str:
    """A rich message of the docs as plain text: without its tags and with the
    braces it quotes."""
    text = re.sub(r"<[^>]+>", "", text).replace("'{'", "{").replace("'}'", "}").replace("''", "'")
    return re.sub(r"\s+", " ", text).strip()


def page_text(page: str, language: str) -> str:
    """The description of a page, or the introduction of one of its sections."""
    name, _, section = page.partition("#")
    try:
        content = json.loads((DOCS / language / "docs" / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if section:
        part = content.get(section)
        return plain(str(part.get("intro") or "")) if isinstance(part, dict) else ""
    return str((content.get("meta") or {}).get("description") or "").strip()


def build() -> dict:
    languages = sorted(p.name for p in DOCS.iterdir() if (p / "docs").is_dir())
    result: dict = {}
    for page in sorted(linked_pages()):
        texts = {}
        for language in languages:
            text = page_text(page, language)
            if text:
                texts[language] = text
        if "en" not in texts:
            raise SystemExit(f"{page}: the English page has no description")
        result[page] = texts
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print("scripts/menus/option_docs.json is out of date: run python3 .github/scripts/build_option_docs.py")
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(json.loads(text))} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
