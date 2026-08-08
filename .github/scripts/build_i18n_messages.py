#!/usr/bin/env python3
"""
Auto-translate missing keys in AppImage/messages/<locale>/common.json
against the English source (AppImage/messages/en/common.json).

Guardrails:
  - Keys already translated in a target locale are PRESERVED. A key is
    considered "already translated" when the target value is non-empty
    AND differs from the English source. This protects human-curated
    locales (Vaso73's sk) from being overwritten.
  - `{placeholder}` tokens (next-intl style: `{vmid}`, `{appName}`, etc.)
    are extracted before translation and restored afterwards, so the
    interpolation contract stays intact regardless of what the
    translation provider does with the surrounding text.
  - `sk` is skipped by default; override with --languages es,de,fr,it,pt,sk
    if you ever want to include it (which will only fill missing keys,
    not overwrite the existing 3632).

Reuses the same translation providers as build_translation_cache.py so
the CI environment (googletrans pinning, AppImage provider) stays
identical.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Reuse providers + cleaner from the CLI translation script.
sys.path.insert(0, str(Path(__file__).parent))
from build_translation_cache import (  # noqa: E402
    clean_translation,
    translate_appimage,
    translate_google_web,
    translate_googletrans,
)


# sk is human-curated (Vaso73); default set excludes it so a naive
# workflow run cannot accidentally overwrite curated strings. Users can
# still pass --languages ...,sk if they want auto-fill for missing keys.
DEFAULT_LANGUAGES = ("es", "de", "fr", "it", "pt")
DEFAULT_CONTEXT = "Context: Technical UI text for a Proxmox management dashboard. Translate:"

# next-intl / ICU-style placeholders: {name}, {vmid}, {count}, {app_name}.
# We deliberately do NOT match `{{ escaped }}` or nested braces — the
# codebase uses only the simple form.
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def flatten(node: dict, prefix: str = "") -> dict[str, str]:
    """Depth-first flatten of a nested dict into ``{"a.b.c": "value"}``.
    Non-string leaves are coerced to str (should not happen in messages
    catalogs, but keeps the function total)."""
    out: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            out.update(flatten(value, path))
        elif value is None:
            out[path] = ""
        else:
            out[path] = str(value)
    return out


def unflatten(flat: dict[str, str]) -> dict:
    """Inverse of ``flatten``: rebuild nested structure from dotted keys."""
    out: dict = {}
    for path, value in flat.items():
        parts = path.split(".")
        cursor = out
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = value
    return out


def protect_placeholders(text: str) -> tuple[str, list[str]]:
    """Swap each ``{xxx}`` for an opaque token that machine translators
    tend to leave alone. Order is preserved so restore_placeholders can
    walk it linearly."""
    placeholders: list[str] = []

    def _swap(match: re.Match) -> str:
        placeholders.append(match.group(0))
        return f"__PMX_PH_{len(placeholders) - 1}__"

    return PLACEHOLDER_RE.sub(_swap, text), placeholders


def restore_placeholders(text: str, placeholders: list[str]) -> str:
    """Reverse of ``protect_placeholders``. If the provider mangled a
    token beyond recognition we leave the mangled form in place — the
    fallback assignment (target = existing or EN) upstream catches
    the worst case."""
    for i, original in enumerate(placeholders):
        text = text.replace(f"__PMX_PH_{i}__", original)
    return text


def translate_one(
    text: str,
    lang: str,
    provider: str,
    context: str,
    timeout: int,
    appimage_path: Path,
) -> str:
    """Dispatch to the correct provider. Reuses the same three
    implementations as build_translation_cache.py so there is exactly
    one place to fix if a provider changes upstream."""
    if provider == "googletrans":
        raw = translate_googletrans(text, lang, context)
    elif provider == "google-web":
        raw = translate_google_web(text, lang, context, timeout)
    elif provider == "appimage":
        raw = translate_appimage(text, lang, context, timeout, appimage_path)
    else:
        raise ValueError(f"Unknown provider: {provider}")
    return clean_translation(raw) or text


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON at {path}: {exc}") from exc


def write_json(path: Path, data: dict) -> None:
    """Write with indent=2, no sort_keys — we want to keep the same
    top-level ordering the maintainer uses in en/common.json so diffs
    stay readable side-by-side."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("AppImage/messages/en/common.json"),
        help="Path to the English source catalog.",
    )
    parser.add_argument(
        "--messages-dir",
        type=Path,
        default=Path("AppImage/messages"),
        help="Directory that contains per-locale subdirectories.",
    )
    parser.add_argument(
        "--languages",
        default=",".join(DEFAULT_LANGUAGES),
        help=(
            "Comma-separated target locales. Default excludes sk "
            "(human-curated by Vaso73). Adding sk here only fills "
            "keys that are still identical to the English fallback."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("appimage", "googletrans", "google-web"),
        default="googletrans",
        help="Translation provider. Default matches build_translation_cache.",
    )
    parser.add_argument(
        "--appimage-path",
        type=Path,
        default=Path("/usr/local/share/proxmenux/ProxMenux-Monitor.AppImage"),
    )
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Re-translate EVERY key, ignoring existing translations. "
            "Dangerous: this DOES overwrite human-curated strings. "
            "Use only when you know what you are doing."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only translate the first N missing keys per locale (test runs).",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=50,
        help="Write the locale JSON every N translated keys so a crash mid-run leaves partial progress on disk.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    source = args.source.resolve()
    messages_dir = args.messages_dir.resolve()
    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]

    if not source.is_file():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1
    if not languages:
        print("No destination languages selected.", file=sys.stderr)
        return 1

    en_nested = read_json(source)
    en_flat = flatten(en_nested)
    print(f"Source: {source}", flush=True)
    print(f"EN keys: {len(en_flat)}", flush=True)
    print(f"Target locales: {', '.join(languages)}", flush=True)
    print(f"Provider: {args.provider}", flush=True)
    print(f"Sleep between calls: {args.sleep}s", flush=True)

    total_failures: list[tuple[str, str, str]] = []

    for lang in languages:
        locale_path = messages_dir / lang / "common.json"
        target_flat = flatten(read_json(locale_path))

        # Decide what needs translating.
        #   - refresh=True  → every EN key
        #   - refresh=False → only keys where target is empty OR equals EN
        #                     (i.e. "not yet translated by a human")
        missing: list[str] = []
        for key, en_value in en_flat.items():
            if not en_value:
                continue
            existing = target_flat.get(key, "")
            if args.refresh:
                missing.append(key)
            elif not existing or existing == en_value:
                missing.append(key)

        if args.limit > 0:
            missing = missing[: args.limit]

        print(f"\n=== {lang}: {len(missing)} keys to translate ===", flush=True)
        if not missing:
            print(f"  {lang}: nothing to do", flush=True)
            continue

        failures_for_lang: list[tuple[str, str, str]] = []

        for index, key in enumerate(missing, start=1):
            en_value = en_flat[key]
            protected, placeholders = protect_placeholders(en_value)

            try:
                translated = translate_one(
                    protected,
                    lang,
                    args.provider,
                    args.context,
                    args.timeout,
                    args.appimage_path,
                )
                target_flat[key] = restore_placeholders(translated, placeholders)
                print(
                    f"  [{lang} {index}/{len(missing)}] {key}: "
                    f"{en_value[:60]!r} → {target_flat[key][:60]!r}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                # Fall back to whatever we already had (or EN) so the
                # runtime fallback still kicks in for this key.
                target_flat[key] = target_flat.get(key) or en_value
                failures_for_lang.append((lang, key, str(exc)))
                print(f"  [{lang}] {key}: FAILED — {exc}", file=sys.stderr, flush=True)

            if args.save_every > 0 and index % args.save_every == 0:
                # Preserve keys already in target_flat + write partial progress.
                write_json(locale_path, unflatten(target_flat))
            time.sleep(args.sleep)

        write_json(locale_path, unflatten(target_flat))
        print(f"  wrote {locale_path}", flush=True)
        total_failures.extend(failures_for_lang)

    if total_failures:
        print(
            f"\nCompleted with {len(total_failures)} translation failures.",
            file=sys.stderr,
            flush=True,
        )
        for lang, key, error in total_failures[:20]:
            print(f"  - {lang}: {key} → {error}", file=sys.stderr, flush=True)
        if len(total_failures) > 20:
            print(f"  ... and {len(total_failures) - 20} more.", file=sys.stderr, flush=True)
        return 2

    print("\ni18n messages generated successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
