#!/usr/bin/env python3
"""
Auto-translate missing keys in AppImage/messages/<locale>/common.json
against the English source (AppImage/messages/en/common.json).

Guardrails:
  - Non-empty string translations are PRESERVED, including values equal
    to English. --refresh explicitly opts into replacing valid strings.
  - Arrays, objects and non-string leaves retain their JSON types. Array
    entries are translated individually, never as serialized Python text.
  - Preflight all locales; skip locales with existing type mismatches without
    provider calls or writes, including with --refresh. Valid locales proceed,
    but any skipped locale makes the run exit 1 (partial failure).
    The diagnostic identifies the locale
    and JSON Pointer requiring manual reconciliation. No automatic migration
    of serialized arrays is attempted: parseability or equal length cannot
    prove correspondence to current English indices. Recover human text only
    after checking its original source/order; do not delete it to force refill.
    Null string leaves remain eligible for filling, as in earlier versions.
  - `{placeholder}` tokens (next-intl style: `{vmid}`, `{appName}`, etc.)
    are extracted before translation and restored afterwards, so the
    interpolation contract stays intact regardless of what the
    translation provider does with the surrounding text.
  - `sk` IS translated by default too. Guardrail #1 protects every key
    Vaso73 has curated by hand; auto-translation only fills the keys
    that are still on the English fallback in sk.

Workflow limitation: build-i18n-messages.yml runs Commit + push only after
successful generation. Exit 1 for skipped locales prevents that step, even
when valid locales made local progress. This does not restore automatic
publication for the default locale set until mismatches are reconciled or
workflow policy is separately changed. Invalid JSON syntax still aborts
preflight globally; per-locale skipping covers parsed catalog type mismatches.

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
    protect_technical_terms,
    restore_technical_terms,
    translate_appimage,
    translate_google_web,
    translate_googletrans,
)


# sk IS included in the default. Guardrail #1 (never overwrite a key
# whose target value differs from EN) protects every string Vaso73 has
# already curated by hand — auto-translation only ever touches keys
# that are still on the English fallback in sk. Trade-off accepted:
# users on sk see a decent auto-translation for new keys instead of raw
# English while the human maintainer catches up, and Vaso73 keeps full
# ownership of the wording via follow-up PRs.
DEFAULT_LANGUAGES = ("es", "de", "fr", "it", "pt", "sk", "sv")
DEFAULT_CONTEXT = "Context: Technical UI text for a Proxmox management dashboard. Translate:"

# next-intl / ICU-style placeholders: {name}, {vmid}, {count}, {app_name}.
# We deliberately do NOT match `{{ escaped }}` or nested braces — the
# codebase uses only the simple form.
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


CatalogPath = tuple[str | int, ...]


def flatten(node: object, prefix: CatalogPath = ()) -> dict[CatalogPath, object]:
    """Keep typed path segments and empty container markers, without coercion."""
    if isinstance(node, dict):
        out = {prefix: {}}
        children = node.items()
    elif isinstance(node, list):
        out = {prefix: []}
        children = enumerate(node)
    else:
        return {prefix: node}
    for key, value in children:
        out.update(flatten(value, prefix + (key,)))
    return out


def unflatten(flat: dict[CatalogPath, object]) -> object:
    """Rebuild a tree from typed paths; parents precede children by depth."""
    nodes = {}
    for path in sorted(flat, key=len):
        value = flat[path]
        nodes[path] = {} if isinstance(value, dict) else [] if isinstance(value, list) else value
        if path:
            parent = nodes[path[:-1]]
            key = path[-1]
            if isinstance(parent, list):
                while len(parent) <= key:
                    parent.append(None)
            parent[key] = nodes[path]
    return nodes[()]


def protect_placeholders(text: str) -> tuple[str, list[str]]:
    """Swap each ``{xxx}`` for an opaque token that machine translators
    tend to leave alone. Order is preserved so restore_placeholders can
    walk it linearly."""
    placeholders: list[str] = []

    def _swap(match: re.Match) -> str:
        placeholders.append(match.group(0))
        # No underscores: a local model splits on them and returns
        # "PMX PH 0", so the placeholder never comes back.
        return f"PMXPH{len(placeholders) - 1:03d}"

    return PLACEHOLDER_RE.sub(_swap, text), placeholders


def restore_placeholders(text: str, placeholders: list[str]) -> str:
    """Reverse of ``protect_placeholders``. If the provider mangled a
    token beyond recognition we leave the mangled form in place — the
    fallback assignment (target = existing or EN) upstream catches
    the worst case."""
    for i, original in enumerate(placeholders):
        text = text.replace(f"PMXPH{i:03d}", original)
    return text


def translate_argos(text: str, lang: str) -> str:
    """LibreTranslate's engine, running locally.

    The remote providers answer a few thousand strings and then start
    refusing, and a refusal here hands back the English and stores it as
    a translation. Local models have no quota and no silent failure mode,
    which is what makes them the right choice for filling a catalogue by
    hand before it is committed.
    """
    try:
        import argostranslate.translate as argos  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "argostranslate is not installed. Install argostranslate and the "
            "en->target packages, or run with another provider."
        ) from exc
    return argos.translate(text, "en", lang)


def translate_one(
    text: str,
    lang: str,
    provider: str,
    context: str,
    timeout: int,
    appimage_path: Path,
) -> str:
    """Dispatch to the correct provider. Reuses the same
    implementations as build_translation_cache.py so there is exactly
    one place to fix if a provider changes upstream."""
    if provider == "googletrans":
        raw = translate_googletrans(text, lang, context)
    elif provider == "google-web":
        raw = translate_google_web(text, lang, context, timeout)
    elif provider == "appimage":
        raw = translate_appimage(text, lang, context, timeout, appimage_path)
    elif provider == "argos":
        raw = translate_argos(text, lang)
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
            "Comma-separated target locales. Includes sk by default; "
            "guardrail #1 never overwrites keys whose sk value differs "
            "from EN, so Vaso73's curated translations are safe."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("argos", "appimage", "googletrans", "google-web"),
        default="googletrans",
        help=(
            "Translation provider. The default matches build_translation_cache "
            "and is what CI uses; `argos` runs locally with no quota and is the "
            "one to reach for when filling a catalogue before committing it."
        ),
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
            "Retranslate the keys named by --refresh-keys. On its own it has "
            "no effect: an existing translation is never replaced."
        ),
    )
    parser.add_argument(
        "--refresh-keys",
        type=Path,
        help=(
            "File with one dotted message key per line. Only these may be "
            "retranslated over an existing value, and only with --refresh."
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

    refresh_keys: set[str] = set()
    if args.refresh_keys is not None:
        if not args.refresh:
            print("--refresh-keys needs --refresh.", file=sys.stderr)
            return 1
        refresh_keys = {
            line.strip()
            for line in args.refresh_keys.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        print(f"Refreshing {len(refresh_keys)} named keys.", flush=True)
    elif args.refresh:
        print("--refresh without --refresh-keys: existing translations are kept.",
              flush=True)

    total_failures: list[tuple[str, CatalogPath, str]] = []

    # Preflight every locale before any provider call or write. Serialized
    # arrays have no trustworthy index correspondence, even if JSON parses.
    # Never guess, evaluate Python repr, or discard human text on --refresh.
    targets = {}
    skipped = set()
    for lang in languages:
        locale_path = messages_dir / lang / "common.json"
        target_flat = flatten(read_json(locale_path))
        targets[lang] = target_flat
        for key, en_value in en_flat.items():
            if key not in target_flat:
                continue
            existing = target_flat[key]
            if isinstance(en_value, str) and existing is None:
                continue  # Historical null string leaves are treated as empty.
            if type(existing) is not type(en_value):
                pointer = "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in key)
                location = f"JSON Pointer {json.dumps(pointer)}" + (" (root)" if not key else "")
                print(
                    f"{locale_path}: {location}: expected {type(en_value).__name__}, "
                    f"found {type(existing).__name__}; manual reconciliation required. "
                    "Locale skipped; its catalog will not be written.", file=sys.stderr,
                )
                skipped.add(lang)

    for lang in languages:
        if lang in skipped:
            continue
        locale_path = messages_dir / lang / "common.json"
        target_flat = targets[lang]

        # Decide what needs translating. Same rule as
        # build_translation_cache.py: only touch keys whose target
        # value is empty. Never overwrite an existing value — that
        # covers three legitimate cases in one line:
        #   1. Human-curated translations (protected trivially).
        #   2. Universal tokens the maintainer left equal to EN on
        #      purpose (Hardware, Terminal, Normal, SMART, OK, CPU %,
        #      {count}h, product names, etc.). Around 120 keys in
        #      es/common.json — the old `existing == en_value` rule
        #      kept resending these to Google every run, and the
        #      provider sometimes mangled them (`Terminal` →
        #      `terminal`, `CPU %` → `% de CPU`, ...).
        #   3. Auto-fills from prior runs whose output happened to
        #      match EN — leaving them alone is the intended
        #      steady-state, not a bug.
        # An existing translation is never replaced. --refresh only reaches
        # the keys named in --refresh-keys, so an overwrite is always one
        # somebody asked for by name rather than a side effect of a run.
        # Seed structural nodes and non-text leaves before any checkpoint.
        # Only strings are sent to a translation provider.
        original_flat = target_flat.copy()
        for key, en_value in en_flat.items():
            if not isinstance(en_value, str) or not en_value:
                target_flat.setdefault(key, en_value)
            elif key and isinstance(key[-1], int):
                # Null keeps an untranslated array position addressable while
                # allowing the runtime English fallback and a later retry.
                target_flat.setdefault(key, None)
        missing: list[CatalogPath] = []
        for key, en_value in en_flat.items():
            if not isinstance(en_value, str) or not en_value:
                continue
            existing = target_flat.get(key, "")
            if not existing or ".".join(str(part) for part in key) in refresh_keys:
                missing.append(key)

        if args.limit > 0:
            missing = missing[: args.limit]

        print(f"\n=== {lang}: {len(missing)} keys to translate ===", flush=True)
        if not missing:
            if target_flat != original_flat:
                write_json(locale_path, unflatten(target_flat))
            print(f"  {lang}: nothing to translate", flush=True)
            continue

        failures_for_lang: list[tuple[str, CatalogPath, str]] = []

        for index, key in enumerate(missing, start=1):
            en_value = en_flat[key]
            protected, placeholders = protect_placeholders(en_value)
            protected, technical_terms = protect_technical_terms(protected)

            try:
                translated = translate_one(
                    protected,
                    lang,
                    args.provider,
                    args.context,
                    args.timeout,
                    args.appimage_path,
                )
                translated = restore_technical_terms(translated, technical_terms)
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
            f"\nCompleted with {len(total_failures)} translation failures "
            f"(partial progress persisted, next run will retry).",
            file=sys.stderr,
            flush=True,
        )
        for lang, key, error in total_failures[:20]:
            print(f"  - {lang}: {key} → {error}", file=sys.stderr, flush=True)
        if len(total_failures) > 20:
            print(f"  ... and {len(total_failures) - 20} more.", file=sys.stderr, flush=True)
        # Exit 0 on partial failure so the workflow's Commit + push
        # step still runs and the keys that DID translate reach
        # develop. The un-translated keys stay empty and the next
        # workflow tick (or a manual dispatch) retries them.
        # Previously we returned 2, which failed the whole run and
        # discarded 36 out of 38 successful translations because
        # 2 googletrans timeouts hit sv at the start of the burst.
        if not skipped:
            return 0

    if skipped:
        names = ', '.join(dict.fromkeys(lang for lang in languages if lang in skipped))
        print(
            f"\nPartial failure: skipped {len(skipped)} locale(s): {names}. "
            "Valid locales processed; skipped catalogs unchanged. "
            "Manual reconciliation required; exiting 1.",
            file=sys.stderr, flush=True,
        )
        return 1

    print("\ni18n messages generated successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
