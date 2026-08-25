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


DEFAULT_LANGUAGES = ("es", "fr", "de", "it", "pt", "sk", "sv")
DEFAULT_CONTEXT = "Context: Technical message for Proxmox and IT. Translate:"
# googletrans and the public Google endpoint used by this workflow do not
# support Cloud Translation glossaries. Protect product names, package names
# and command identifiers with opaque tokens before sending text to any
# provider, then restore the exact source spelling afterwards. Keep longer
# terms first so ``gasket`` cannot consume part of ``gasket-dkms``.
PROTECTED_TECHNICAL_TERMS = (
    "google/gasket-driver",
    "feranick/gasket-driver",
    "libedgetpu1-std",
    "Proxmox VE Helper-Scripts",
    "Docker Compose",
    "gasket-driver",
    "gasket-dkms",
    "libedgetpu1",
    "libedgetpu",
    "Google Coral",
    "Edge TPU",
    "ProxMenux",
    "Proxmox",
    "AppImage",
    "smartctl",
    "systemctl",
    "pveproxy",
    "apt-get",
    "Frigate",
    "Docker",
    "Coral",
    "gasket",
    "apex",
    "lspci",
    "dpkg",
    "DKMS",
    "QEMU",
    "LXC",
    "ZFS",
    "SSH",
    "fork",
)
TECHNICAL_TERM_RE = re.compile(
    "|".join(
        rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        for term in sorted(PROTECTED_TECHNICAL_TERMS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)
TRANSLATE_CALL_RE = re.compile(
    r"""translate\s+(?P<quote>["'])(?P<text>(?:\\.|(?! (?P=quote) ).)*?)(?P=quote)""",
    re.VERBOSE | re.DOTALL,
)


def protect_technical_terms(text: str) -> tuple[str, list[str]]:
    """Replace glossary terms with stable tokens before translation."""
    protected: list[str] = []

    def _swap(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__PMX_TERM_{len(protected) - 1}__"

    return TECHNICAL_TERM_RE.sub(_swap, text), protected


def restore_technical_terms(text: str, protected: list[str]) -> str:
    """Restore glossary terms exactly as they appeared in the source."""
    for index, original in enumerate(protected):
        text = text.replace(f"__PMX_TERM_{index}__", original)
    return text


def iter_script_files(
    scripts_dir: Path, extra_files: Iterable[Path] = ()
) -> Iterable[Path]:
    # Walk the main scripts tree.
    for path in sorted(scripts_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "utils.sh":
            continue
        if path.suffix not in {".sh", ".func"}:
            continue
        yield path
    # Yield additional files passed explicitly (e.g. the root-level `menu`
    # entry point or install_proxmenux*.sh). These live outside scripts/
    # but still contain translate "..." calls we want in the cache.
    # No extension filter and no utils.sh skip — the caller decided
    # they belong, we just check the file actually exists.
    for extra in extra_files:
        if extra.is_file():
            yield extra


def decode_shell_string(raw: str, quote_char: str) -> str:
    if quote_char == "'":
        return raw
    try:
        return ast.literal_eval(f'"{raw}"')
    except Exception:
        return raw.replace(r"\"", '"').replace(r"\\", "\\")


def extract_translate_texts(
    scripts_dir: Path, extra_files: Iterable[Path] = ()
) -> list[str]:
    found: dict[str, None] = {}
    for path in iter_script_files(scripts_dir, extra_files):
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
    # `Translate` pivot in every locale currently supported. Without
    # the target-language variant here, the cleaner can't locate the
    # boundary between the context prompt and the real translation,
    # and the whole payload leaks through as the translated context.
    # Caught on the 2026-08-14 workflow run — every sk / sv key ended
    # up as "Technický text používateľského rozhrania…" or
    # "Teknisk gränssnittstext för en Proxmox-hanteringspanel.Övers"
    # because Preložiť / Översätt / Översätta were missing.
    translate_labels = (
        "Translate|Traducir|Traduire|Übersetzen|Tradurre|Traduci|Traduzir"
        "|Preložiť|Prelož|Preloz"          # sk
        "|Översätta|Översätt"              # sv
    )
    context_labels = (
        "Context|Contexto|Contexte|Kontext|Contesto"
        "|Sammanhang"                      # sv alternate
    )
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
    protected_text, protected_terms = protect_technical_terms(text)
    if provider == "googletrans":
        translated = translate_googletrans(protected_text, dest_lang, context)
    elif provider == "google-web":
        translated = translate_google_web(protected_text, dest_lang, context, timeout)
    elif provider == "appimage":
        translated = translate_appimage(
            protected_text, dest_lang, context, timeout, appimage_path
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
    translated = restore_technical_terms(clean_translation(translated), protected_terms)
    return translated or text


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
        "--extra-file",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help=(
            "Extra individual files to scan for translate calls in addition "
            "to --scripts-dir. Useful for the root-level `menu` entry point "
            "and install_proxmenux*.sh, which sit outside scripts/. "
            "Pass multiple times to add more than one file."
        ),
    )
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
        help="Comma-separated destination languages. Default: es,fr,de,it,pt,sk",
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

    texts = extract_translate_texts(scripts_dir, args.extra_file)
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
        print(
            f"Completed with {len(failures)} translation failures "
            f"(partial progress persisted, next run will retry).",
            file=sys.stderr, flush=True,
        )
        for text, lang, error in failures[:20]:
            print(f"- {lang}: {text[:80]} -> {error}", file=sys.stderr, flush=True)
        if len(failures) > 20:
            print(f"... and {len(failures) - 20} more.", file=sys.stderr, flush=True)
        # Exit 0 on partial failure so the workflow's Commit + push
        # step still runs. Otherwise a couple of transient googletrans
        # timeouts would fail the whole workflow and discard every
        # successful translation from the same batch.
        return 0

    print("Translation cache generated successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
