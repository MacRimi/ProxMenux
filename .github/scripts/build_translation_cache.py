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
import asyncio
import inspect
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
    # Kernel driver and subsystem names. Left to a translator, `nouveau`
    # becomes the adjective it is borrowed from — "el nuevo controlador"
    # in Spanish, "Jugendstil" in German — and the reader is told about a
    # driver that does not exist instead of the one being blacklisted.
    "nvidia-container-toolkit",
    "nvidia-smi",
    "initramfs",
    "nouveau",
    "vfio-pci",
    "modprobe",
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
    # Vendor, API and acceleration names. A label like "NVIDIA (NVDEC/CUDA)"
    # is a product name end to end: every provider hands it back as it came,
    # and without these entries that correct answer is read as a failure and
    # the string is dropped from the catalogue.
    "VA-API",
    "NVIDIA",
    "NVDEC",
    "NVENC",
    "WebUI",
    "Intel",
    "CUDA",
    "KFD",
    "GPU",
    "CPU",
    "AMD",
    # Proxmox's own words for a container and a virtual machine. Read as
    # initials they get reordered — "CT" comes back as "TC" in Spanish —
    # and the reader is told about something Proxmox does not call that.
    "CT",
    "VM",
    # Open Container Initiative. Read as a word it becomes "BEC" in French,
    # which named nothing, across thirty-one strings of the OCI section.
    "OCI manager Apps",
    "OCI",
    "beta",
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
# Same shape the Monitor's generator uses, so a message reads identically
# whichever of the two catalogues it comes from.
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
# Literals a reader copies and runs. Translated as words they stop working:
# /dev/apex_0 came back as "/dev/apex 0", --auto-uninstall as "desinstalación
# automática", and "pct config 110" as "configuration PCT 110". A glossary can
# only hold what someone listed; these are recognised by shape.
STRUCTURAL_LITERAL_RE = re.compile(
    r"""
      /(?:dev|etc|usr|var|opt|srv|proc|sys|run|boot|tmp)/[\w./+-]*[\w/+-]
    | (?<![\w-])--[A-Za-z][\w-]*
    | \b[\w.-]+\.(?:sh|py|json|yml|yaml|conf|service|timer|func|cfg|list|log)\b
    | \b(?:pct|qm|pvesm|pveam|pveum|pvecm|apt-get|dpkg|systemctl|journalctl
        |zpool|smartctl|modprobe|blkid|lsblk|mkfs)\s+[a-z][\w-]*
    """,
    re.VERBOSE,
)
# Providers that answer the same thing every time for the same input, so a
# second attempt cannot produce a different result. `appimage` shells out to a
# binary that may reach a network service, so it is not on the list.
DETERMINISTIC_PROVIDERS = frozenset({"argos"})


def protect_catalog_titles(directories) -> None:
    """Add every application name in the catalog to the protected glossary.

    They are product names, and a translator treats them as words: "HAOS One"
    comes back as "HAOS Man". Protecting them costs nothing and the failure it
    prevents reaches the reader as an application that does not exist.
    """
    global TECHNICAL_TERM_RE
    titles: set[str] = set()
    for directory in directories:
        for path in sorted(Path(directory).rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            title = ((data.get("catalog_ui") or {}).get("title") or {}).get("en_US")
            if isinstance(title, str) and title.strip():
                titles.add(title.strip())
    if not titles:
        return
    terms = tuple(sorted(set(PROTECTED_TECHNICAL_TERMS) | titles, key=len, reverse=True))
    # Same word boundaries as the module-level pattern. Without them a short
    # term matches inside longer words, and every application title in the
    # catalogue joins the glossary here.
    TECHNICAL_TERM_RE = re.compile(
        "|".join(
            rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
            for term in terms
        ),
        re.IGNORECASE,
    )
    print(f"Protected application names: {len(titles)}", flush=True)


def protect_placeholders(text: str) -> tuple[str, list[str]]:
    """Replace each ``{name}`` with a token before translation.

    A provider reads the name inside the braces as a word and translates
    it: ``{count}`` comes back as ``{conta}`` in Portuguese and ``{počet}``
    in Slovak. The consumer then finds no placeholder to substitute and
    falls back to English, so the translation was paid for and never used.
    The token carries no underscores because argos splits on them.
    """
    found: list[str] = []

    def _swap(match: re.Match[str]) -> str:
        found.append(match.group(0))
        return f"PMXPH{len(found) - 1:03d}"

    return PLACEHOLDER_RE.sub(_swap, text), found


def restore_placeholders(text: str, found: list[str]) -> str:
    """Put the original ``{name}`` back where each token landed."""
    for index, original in enumerate(found):
        text = text.replace(f"PMXPH{index:03d}", original)
    return text


def protect_technical_terms(text: str) -> tuple[str, list[str]]:
    """Replace glossary terms with stable tokens before translation.

    Structural literals go first. A glossary can only list what someone
    thought of, and what reaches the reader as a broken command is never on
    that list: an absolute path, a long option, a filename. They are
    recognised by shape instead, which also covers the next one added.
    """
    protected: list[str] = []

    def _swap(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"PMXTERM{len(protected) - 1:03d}"

    text = STRUCTURAL_LITERAL_RE.sub(_swap, text)
    return TECHNICAL_TERM_RE.sub(_swap, text), protected


def restore_technical_terms(text: str, protected: list[str]) -> str:
    """Restore glossary terms exactly as they appeared in the source."""
    for index, original in enumerate(protected):
        text = text.replace(f"PMXTERM{index:03d}", original)
    return text


# A provider can alter a token instead of carrying it through: argos returned
# MPXTERM000 for PMXTERM000, the replace found nothing, and the token shipped
# to the reader — "MPXTERM000 configuré" is in the French catalogue now.
SENTINEL_RESIDUE_RE = re.compile(r"[MP][MPX]X?\s?(?:TERM|PH)\s?\d{2,4}", re.IGNORECASE)


def assert_no_sentinel_residue(text: str) -> None:
    """Fail the translation when a protection token did not survive intact.

    Leaving the key out is recoverable: the next run tries again. Storing a
    string with a token in it is not, because nothing looks at a value that
    already exists.
    """
    found = SENTINEL_RESIDUE_RE.search(text)
    if found:
        raise RuntimeError(f"the provider altered a protection token: {found.group(0)!r}")


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


PYTHON_TRANSLATE_CALLS = {"translate", "N_"}
CATALOG_TEXT_KEYS = {"prompt", "enable_prompt", "path_prompt", "size_prompt", "label", "warning"}
CATALOG_TEXT_LISTS = {"stack_completion_notes", "completion_notes"}


def extract_python_texts(directories: Iterable[Path]) -> list[str]:
    """translate("...") and N_("...") calls with a literal argument. The parser
    joins implicitly concatenated literals, so wrapped strings are found whole."""
    found: dict[str, None] = {}
    for directory in directories:
        for path in sorted(directory.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in PYTHON_TRANSLATE_CALLS
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    text = node.args[0].value.strip()
                    if text:
                        found.setdefault(text, None)
    return sorted(found)


def extract_catalog_texts(directories: Iterable[Path]) -> list[str]:
    """User-visible text stored in the OCI catalog JSON: prompts, labels,
    warnings, completion notes, category labels and descriptive usernames."""
    found: dict[str, None] = {}

    def add(value: object) -> None:
        if isinstance(value, str) and value.strip():
            found.setdefault(value.strip(), None)

    def walk(value: object, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                if child_key in CATALOG_TEXT_KEYS:
                    add(child)
                elif child_key in CATALOG_TEXT_LISTS and isinstance(child, list):
                    for item in child:
                        add(item)
                elif child_key == "username" and isinstance(child, str) and " " in child:
                    add(child)
                elif child_key == "catalog_ui" and isinstance(child, dict):
                    # What the application detail screen shows: the tagline,
                    # and the description only where there is no tagline. The
                    # catalog stores the source English; the translation lives
                    # in the language cache with every other string.
                    tagline = (child.get("tagline") or {}).get("en_US")
                    add(tagline or (child.get("description") or {}).get("en_US"))
                elif child_key == "labels" and key == "" and isinstance(child, dict):
                    for item in child.values():
                        add(item)
                walk(child, child_key)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)

    for directory in directories:
        for path in sorted(directory.rglob("*.json")):
            try:
                walk(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return sorted(found)


def translate_argos(text: str, dest_lang: str) -> str:
    """LibreTranslate's engine, running locally.

    A public endpoint answers a few thousand strings and then starts
    refusing — and the library wrapper around it returns the English
    unchanged rather than raising, which writes the source text into the
    catalogue as if it were a translation. Local models have no quota and
    no silent failure mode.
    """
    try:
        import argostranslate.translate as argos  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "argostranslate is not installed. Install argostranslate and the "
            "en->target packages, or run with another provider."
        ) from exc
    return argos.translate(text, "en", dest_lang)


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
    result = translator.translate(full_text, dest=dest_lang)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result.text


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


# Lowercase-or-digit, then the mark, then an uppercase letter: that is a
# sentence boundary and not `8.0`, `storage.cfg` or `proxmox.com/docs`.
_SENTENCE_RUN = re.compile(
    "(?<=[a-z0-9\u00e0-\u00ff\u0107\u010d\u011b\u013e\u0148\u0159\u0161\u0165\u016f\u017a\u017e])"
    "([.?!])"
    "(?=[A-Z\u00c0-\u00de\u0106\u010c\u011a\u013d\u0147\u0158\u0160\u0164\u016e\u0179\u017d])"
)


def restore_sentence_spacing(text: str) -> str:
    """Every provider drops the blank between sentences it translated apart."""
    return _SENTENCE_RUN.sub(r"\1 ", text)


def translate_text(
    text: str,
    dest_lang: str,
    provider: str,
    context: str,
    timeout: int,
    appimage_path: Path,
) -> str:
    protected_text, placeholders = protect_placeholders(text)
    protected_text, protected_terms = protect_technical_terms(protected_text)
    if provider == "argos":
        translated = translate_argos(protected_text, dest_lang)
    elif provider == "googletrans":
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
    translated = restore_placeholders(translated, placeholders)
    assert_no_sentinel_residue(translated)
    return restore_sentence_spacing(translated) if translated else text


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


def is_fully_protected(source: str) -> bool:
    """Whether the string is glossary terms and punctuation, nothing else.

    "Docker Volume Backup" and "NVIDIA (NVDEC/CUDA)" are product and API
    names from end to end. Coming back unchanged is the right answer for
    them, so the guard below must not read it as a silent failure and throw
    the result away.
    """
    return not re.search(r"[A-Za-z]{2,}", TECHNICAL_TERM_RE.sub(" ", source))


def looks_untranslated(source: str, result: str) -> bool:
    """Whether a provider handed back the text it was given.

    A single technical word legitimately survives translation — Docker, GPU,
    LXC — but a sentence coming back byte-identical means the provider failed
    without saying so. Accepting it writes English into the catalogue, where
    it counts as translated and is never looked at again.
    """
    if source.strip() != result.strip():
        return False
    if is_fully_protected(source):
        return False
    return len([word for word in re.findall(r"[A-Za-z]{2,}", source)]) >= 3


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
        "--extra-dir",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Extra directory scanned for translate calls in .sh files. Repeatable.",
    )
    parser.add_argument(
        "--python-dir",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Directory scanned for translate()/N_() calls in .py files. Repeatable.",
    )
    parser.add_argument(
        "--catalog-dir",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Directory of OCI catalog JSON files with user-visible text. Repeatable.",
    )
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
        choices=("argos", "appimage", "googletrans", "google-web"),
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
    parser.add_argument("--retries", default=4, type=int,
                        help="Attempts per string before giving up on it.")
    parser.add_argument("--retry-wait", default=15, type=float,
                        help="Seconds before the first retry; it doubles each time.")
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
    for directory in args.extra_dir:
        if directory.is_dir():
            texts += extract_translate_texts(directory.resolve())
    texts += extract_python_texts(d.resolve() for d in args.python_dir if d.is_dir())
    catalog_dirs = [d.resolve() for d in args.catalog_dir if d.is_dir()]
    protect_catalog_titles(catalog_dirs)
    texts += extract_catalog_texts(catalog_dirs)
    texts = sorted(dict.fromkeys(text for text in texts if "$" not in text and "`" not in text))
    if args.limit > 0:
        texts = texts[: args.limit]
    existing_by_lang = {
        lang: load_language_cache(output_dir / f"{lang}.json")
        for lang in languages
    }
    # Seeded with what is already translated so a periodic save — or an
    # interrupted run — writes a superset of the file it replaces, never a
    # truncated one.
    next_by_lang: dict[str, dict[str, str]] = {
        lang: dict(existing_by_lang.get(lang, {})) for lang in languages
    }
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
            # A rate limit is a "come back later", not an answer. Retrying with
            # a growing wait recovers it; giving up on the first one is what
            # left thousands of strings untranslated.
            value, last_error = None, None
            for attempt in range(1, args.retries + 1):
                unchanged = False
                try:
                    value = translate_text(
                        text,
                        lang,
                        args.provider,
                        args.context,
                        args.timeout,
                        args.appimage_path,
                    )
                    if looks_untranslated(text, value):
                        value = None
                        unchanged = True
                        raise RuntimeError("the provider returned the source text unchanged")
                    break
                except Exception as exc:
                    last_error = exc
                    # Unchanged text from a remote provider is how a rate limit
                    # shows up, so it is worth waiting for. A local engine is
                    # deterministic: asking again returns the same string, and
                    # the backoff only buys minutes of sleeping per phrase.
                    if unchanged and args.provider in DETERMINISTIC_PROVIDERS:
                        break
                    if attempt < args.retries:
                        wait = args.retry_wait * (2 ** (attempt - 1))
                        print(f"  retry {attempt}/{args.retries - 1} in {wait}s: {exc}",
                              file=sys.stderr, flush=True)
                        time.sleep(wait)
            if value is not None:
                next_by_lang[lang][text] = value
                print(f"  => {value[:100]}", flush=True)
            else:
                # The key is left out on purpose. Writing the English here
                # would count as a translation on the next run and the string
                # would never be translated again.
                previous = existing.get(text)
                if previous:
                    next_by_lang[lang][text] = previous
                failures.append((text, lang, str(last_error)))
                print(f"  failed: {last_error}", file=sys.stderr, flush=True)
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
