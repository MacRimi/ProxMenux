#!/usr/bin/env python3
"""Check documentation translation structure and literal contracts offline.

Missing locales/leaves are allowed by default because the website falls back
to English. Use --require-complete when validating a catalog completion PR.
This checks data integrity, not translation fluency or linguistic accuracy.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from build_web_docs_i18n import (
    DEFAULT_LANGUAGES,
    get_at_path,
    iter_leaves,
    literal_values_match,
    read_json,
    schema_matches,
    source_files,
)
from check_terminal_catalogs import validate_message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages-dir", type=Path, default=Path("web/messages"))
    parser.add_argument("--languages", default=",".join(DEFAULT_LANGUAGES))
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    root = args.messages_dir.resolve()
    files = source_files(root / "en", ".")
    errors = 0
    for language in args.languages.split(","):
        language = language.strip()
        if language not in DEFAULT_LANGUAGES:
            parser.error(f"Unsupported locale: {language}")
        missing = checked = present_files = 0
        for file in files:
            relative = file.relative_to(root / "en")
            source = read_json(file)
            target = read_json(root / language / relative)
            if target is not None:
                present_files += 1
            if args.require_complete and not schema_matches(source, target):
                print(f"[{language}] {relative}: source/target schema differs")
                errors += 1
            for leaf in iter_leaves(source):
                localized = get_at_path(target, leaf.path)
                if not isinstance(localized, str) or (leaf.source.strip() and not localized.strip()):
                    missing += 1
                    continue
                try:
                    validate_message(
                        leaf.source, localized,
                        title_separator=bool(
                            leaf.path and leaf.path[0] == "meta"
                            and leaf.path[-1] in ("title", "ogTitle", "twitterTitle")
                        ),
                    )
                except ValueError as exc:
                    print(f"[{language}] {relative}:{'.'.join(map(str, leaf.path))}: {exc}")
                    errors += 1
                checked += 1
            if args.require_complete and not literal_values_match(source, target):
                print(f"[{language}] {relative}: literal commands or rendering metadata differ")
                errors += 1
        print(f"[{language}] files={present_files}/{len(files)} strings={checked} missing={missing}")
        if args.require_complete and missing:
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
