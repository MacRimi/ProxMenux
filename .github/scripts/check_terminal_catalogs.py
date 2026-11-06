#!/usr/bin/env python3
"""Check active terminal translations offline, without generating any text.

Validates formatting fields and literal commands/identifiers. Missing values
can retain English fallback; --require-complete makes them errors. This does
not establish the accuracy or fluency of the translated prose.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from build_translation_cache import (
    DEFAULT_LANGUAGES, STRUCTURAL_LITERAL_RE, extract_catalog_texts,
    extract_python_texts, extract_translate_texts,
)
from build_web_docs_i18n import read_json, validate_contract


def active_sources(root: Path) -> list[str]:
    # Match build-translation-cache.yml, including launchers outside scripts/.
    extras = [root / name for name in ('menu', 'install_proxmenux.sh', 'install_proxmenux_beta.sh')]
    texts = extract_translate_texts(root / 'scripts', extras)
    texts += extract_translate_texts(root / 'oci/remote')
    texts += extract_python_texts([root / 'scripts', root / 'oci/src', root / 'oci/remote'])
    texts += extract_catalog_texts([root / 'oci/catalog'])
    return sorted({text for text in texts if '$' not in text and '`' not in text})


def validate_message(source: str, target: str, *, title_separator: bool = False) -> None:
    validate_contract(source, target)
    for match in STRUCTURAL_LITERAL_RE.finditer(source):
        literal = match.group()
        # A page title may replace its decorative separator with a dash.
        # In command examples, a pipe remains a shell operator.
        if title_separator and literal == '|':
            continue
        # DNS hostnames are case-insensitive. Paths, field names and command
        # names are not, so do not case-fold those to hide a broken example.
        is_hostname = re.fullmatch(r'[A-Za-z0-9.-]+\.(?:com|org|net|io)', literal)
        if literal not in target and not (is_hostname and literal.casefold() in target.casefold()):
            raise ValueError(f'literal command or identifier changed: {literal}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--languages', default=','.join(DEFAULT_LANGUAGES))
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    texts = active_sources(root)
    errors = 0
    for language in args.languages.split(','):
        if language not in DEFAULT_LANGUAGES:
            parser.error(f'Unsupported locale: {language}')
        catalog = read_json(root / 'lang' / f'{language}.json') or {}
        missing = 0
        for source in texts:
            target = catalog.get(source)
            if not isinstance(target, str) or not target.strip():
                missing += 1
                continue
            try:
                validate_message(source, target)
            except ValueError as error:
                print(f'[{language}] {source!r}: {error}')
                errors += 1
        print(f'[{language}] active={len(texts)} missing={missing}')
        if args.require_complete and missing:
            errors += 1
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
