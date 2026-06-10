#!/usr/bin/env python3
"""
Build the ProxMenux translation cache from translate calls in scripts/.

The generated JSON keeps the same shape used by scripts/utils.sh:

{
  "Original English text": {
    "es": "Translated text",
    "fr": "Translated text"
  }
}
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import re
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_LANGUAGES = ("es", "fr", "de", "it", "pt")
DEFAULT_CONTEXT = "Context: Technical message for Proxmox and IT. Translate:"
TRANSLATE_CALL_RE = re.compile(
    r"""translate\s+(?P<quote>["'])(?P<text>(?:\\.|(?! (?P=quote) ).)*?)(?P=quote)""",
    re.VERBOSE | re.DOTALL,
)


def iter_script_files(scripts_dir: Path) -> Iterable[Path]:
    for path in sorted(scripts_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "utils.sh":
            continue
        if path.suffix not in {".sh", ".func"}:
            continue
        yield path


def decode_shell_string(raw: str, quote_char: str) -> str:
    if quote_char == "'":
        return raw
    try:
        return ast.literal_eval(f'"{raw}"')
    except Exception:
        return raw.replace(r"\"", '"').replace(r"\\", "\\")


def extract_translate_texts(scripts_dir: Path) -> list[str]:
    found: dict[str, None] = {}
    for path in iter_script_files(scripts_dir):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")

        for match in TRANSLATE_CALL_RE.finditer(content):
            text = decode_shell_string(match.group("text"), match.group("quote"))
            text = text.strip()
            if text and "$" not in text and "`" not in text:
                found.setdefault(text, None)

    return sorted(found)


def translate_googletrans(text: str, dest_lang: str, context: str) -> str:
    try:
        from googletrans import Translator  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "googletrans is not installed. Install googletrans==4.0.0-rc1 "
            "or run with --provider google-web."
        ) from exc

    translator = Translator()
    full_text = f"{context} {text}".strip()
    return translator.translate(full_text, dest=dest_lang).text


def translate_google_web(text: str, dest_lang: str, context: str, timeout: int) -> str:
    # The public Google endpoint is not prompt-aware: if we prepend context,
    # it often translates and returns that context as part of the result.
    full_text = text
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=en&tl={quote(dest_lang)}&dt=t&q={quote(full_text)}"
    )
    req = Request(url, headers={"User-Agent": "ProxMenux translation cache builder"})
    with urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return "".join(part[0] for part in payload[0] if part and part[0])


def translate_appimage(
    text: str,
    dest_lang: str,
    context: str,
    timeout: int,
    appimage_path: Path,
) -> str:
    if not appimage_path.exists():
        prev_path = appimage_path.with_name(appimage_path.name + ".prev")
        if prev_path.exists():
            appimage_path = prev_path
        else:
            raise FileNotFoundError(f"AppImage not found: {appimage_path}")

    req = {
        "text": text,
        "dest_lang": dest_lang,
        "context": context,
        "cache_file": "",
    }
    env = os.environ.copy()
    env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    completed = subprocess.run(
        [str(appimage_path), "--translate"],
        input=json.dumps(req, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())

    # AppRun may print a startup line before translate_cli.py emits JSON.
    for line in reversed(completed.stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        payload = json.loads(line)
        if payload.get("success"):
            return str(payload.get("text", text))
        raise RuntimeError(str(payload.get("error", "unknown AppImage translation error")))

    raise RuntimeError(f"AppImage did not return JSON: {completed.stdout.strip()}")


def clean_translation(value: str) -> str:
    separator = r"[\s\u00a0]*[:：]"
    translate_labels = "Translate|Traducir|Traduire|Übersetzen|Tradurre|Traduci|Traduzir"
    context_labels = "Context|Contexto|Contexte|Kontext|Contesto"
    value = re.sub(
        rf"^.*?({translate_labels}){separator}",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    value = re.sub(
        rf"^.*?({context_labels}){separator}.*?({translate_labels}){separator}",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    value = re.sub(
        rf"^.*?({context_labels}){separator}",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return value.strip()


def translate_text(
    text: str,
    dest_lang: str,
    provider: str,
    context: str,
    timeout: int,
    appimage_path: Path,
) -> str:
    if provider == "googletrans":
        translated = translate_googletrans(text, dest_lang, context)
    elif provider == "google-web":
        translated = translate_google_web(text, dest_lang, context, timeout)
    elif provider == "appimage":
        translated = translate_appimage(text, dest_lang, context, timeout, appimage_path)
    else:
        raise ValueError(f"Unknown provider: {provider}")
    return clean_translation(translated) or text


def load_language_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(text): str(value) for text, value in data.items()}


def write_language_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract translate calls from scripts/ and build json/cache.json."
    )
    parser.add_argument("--scripts-dir", default="scripts", type=Path)
    parser.add_argument(
        "--output-dir",
        default=Path("lang"),
        type=Path,
        help="Directory where per-language JSON files are written. Default: lang",
    )
    parser.add_argument(
        "--output",
        default=None,
        type=Path,
        help="Deprecated combined cache path. If used, per-language files are written next to it under its parent directory.",
    )
    parser.add_argument(
        "--languages",
        default=",".join(DEFAULT_LANGUAGES),
        help="Comma-separated destination languages. Default: es,fr,de,it,pt",
    )
    parser.add_argument(
        "--provider",
        choices=("appimage", "googletrans", "google-web"),
        default="appimage",
        help="Translation provider to use. Default: appimage",
    )
    parser.add_argument(
        "--appimage-path",
        default=Path("/usr/local/share/proxmenux/ProxMenux-Monitor.AppImage"),
        type=Path,
        help="Path to the ProxMenux AppImage when using --provider appimage.",
    )
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--timeout", default=30, type=int)
    parser.add_argument("--sleep", default=0.15, type=float)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Translate all entries again instead of reusing existing cache values.",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only update the cache keys; missing translations are left empty.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process the first N extracted strings. Useful for test runs.",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=1,
        help="Write the output JSON every N translated items. Default: 1",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    scripts_dir = args.scripts_dir.resolve()
    if args.output is not None:
        output_dir = args.output.resolve().parent / "lang"
    else:
        output_dir = args.output_dir.resolve()
    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]

    if not scripts_dir.is_dir():
        print(f"Scripts directory not found: {scripts_dir}", file=sys.stderr)
        return 1
    if not languages:
        print("No destination languages selected.", file=sys.stderr)
        return 1

    texts = extract_translate_texts(scripts_dir)
    if args.limit > 0:
        texts = texts[: args.limit]
    existing_by_lang = {
        lang: load_language_cache(output_dir / f"{lang}.json")
        for lang in languages
    }
    next_by_lang: dict[str, dict[str, str]] = {lang: {} for lang in languages}
    print(f"Found {len(texts)} unique translate strings.", flush=True)
    print(f"Output directory: {output_dir}", flush=True)
    print(f"Languages: {', '.join(languages)}", flush=True)

    failures: list[tuple[str, str, str]] = []
    total = len(texts) * len(languages)
    done = 0

    for lang in languages:
        existing = existing_by_lang.get(lang, {})
        print(f"Starting language: {lang}", flush=True)

        for index, text in enumerate(texts, start=1):
            done += 1
            if not args.refresh and existing.get(text):
                next_by_lang[lang][text] = existing[text]
                continue
            if args.extract_only:
                next_by_lang[lang][text] = existing.get(text, "")
                continue

            print(f"[{done}/{total}] {lang} ({index}/{len(texts)}): {text[:80]}", flush=True)
            try:
                next_by_lang[lang][text] = translate_text(
                    text,
                    lang,
                    args.provider,
                    args.context,
                    args.timeout,
                    args.appimage_path,
                )
                print(f"  => {next_by_lang[lang][text][:100]}", flush=True)
            except Exception as exc:
                next_by_lang[lang][text] = existing.get(text, text)
                failures.append((text, lang, str(exc)))
                print(f"  failed: {exc}", file=sys.stderr, flush=True)
            if args.save_every > 0 and index % args.save_every == 0:
                write_language_cache(output_dir / f"{lang}.json", next_by_lang[lang])
            time.sleep(args.sleep)

        write_language_cache(output_dir / f"{lang}.json", next_by_lang[lang])
        print(f"Completed language: {lang}", flush=True)

    for lang, cache in next_by_lang.items():
        write_language_cache(output_dir / f"{lang}.json", cache)

    if failures:
        print(f"Completed with {len(failures)} translation failures.", file=sys.stderr, flush=True)
        for text, lang, error in failures[:20]:
            print(f"- {lang}: {text[:80]} -> {error}", file=sys.stderr, flush=True)
        if len(failures) > 20:
            print(f"... and {len(failures) - 20} more.", file=sys.stderr, flush=True)
        return 2

    print("Translation cache generated successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
