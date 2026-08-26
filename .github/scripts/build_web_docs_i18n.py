#!/usr/bin/env python3
"""Build missing translations for the ProxMenux documentation catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).parent))
from build_translation_cache import (  # noqa: E402
    clean_translation,
    translate_appimage,
    translate_google_web,
    translate_googletrans,
)


DEFAULT_LANGUAGES = ("es", "de", "fr", "it", "pt", "sk", "sv")
DEFAULT_CONTEXT = (
    "Context: ProxMenux technical documentation for Proxmox VE users. "
    "Preserve product names, commands, paths, variables and placeholders. Translate:"
)

TECHNICAL_TERMS = (
    "Proxmox VE Helper-Scripts",
    "Proxmox Backup Server",
    "Proxmox Mail Gateway",
    "Proxmox VE",
    "ProxMenux Monitor",
    "ProxMenux Scripts",
    "Docker Compose",
    "Docker Engine",
    "Google Coral",
    "Edge TPU",
    "Let's Encrypt",
    "Cloudflare",
    "Pushover",
    "Telegram",
    "Discord",
    "Microsoft Teams",
    "GitHub",
    "Gotify",
    "Apprise",
    "Frigate",
    "Vaultwarden",
    "Portainer",
    "ProxMenux",
    "AppImage",
    "systemctl",
    "journalctl",
    "smartctl",
    "pveproxy",
    "apt-get",
    "gasket-dkms",
    "libedgetpu",
    "QEMU",
    "LXC",
    "ZFS",
    "Ceph",
    "Docker",
    "OpenAI",
    "WebSocket",
    "OAuth",
    "DKMS",
    "SSH",
    "API",
)

PROTECTED_PATTERNS = (
    # Keep rich-text tags visible to Google Translate. It preserves their
    # structure while translating the enclosed prose, whereas replacing
    # opening/closing tags with adjacent sentinels can make the provider drop
    # one side of the pair. The contract is validated after translation.
    re.compile(r"`[^`]+`"),
    re.compile(r"https?://[^\s<>]+"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_.-]*\}"),
    re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"),
    re.compile(r"(?<![\w-])--[A-Za-z0-9][A-Za-z0-9_-]*"),
    re.compile(r"(?<![A-Za-z0-9<])/(?:[A-Za-z0-9._~:@%+=-]+/)*[A-Za-z0-9._~:@%+=-]+"),
    re.compile(r"\b[A-Za-z0-9_.-]+\.(?:json|ya?ml|toml|conf|service|socket|sh|py|tsx?|jsx?|md)\b"),
)
LITERAL_TAG_RE = re.compile(
    r"<(code|kbd|pre)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

TERM_RE = re.compile(
    "|".join(
        rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        for term in sorted(TECHNICAL_TERMS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)
TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9]*)>")
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_.-]*\}")
NON_TRANSLATABLE_KEYS = {
    "command",
    "code",
    "href",
    "icon",
    "id",
    "path",
    "route",
    "slug",
    "src",
    "url",
}
SOURCE_STATE_VERSION = 1


@dataclass(frozen=True)
class Leaf:
    path: tuple[str | int, ...]
    source: str


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def iter_leaves(node: Any, path: tuple[str | int, ...] = ()) -> list[Leaf]:
    leaves: list[Leaf] = []
    if isinstance(node, dict):
        for key, value in node.items():
            leaves.extend(iter_leaves(value, path + (key,)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            leaves.extend(iter_leaves(value, path + (index,)))
    elif isinstance(node, str):
        leaves.append(Leaf(path, node))
    return leaves


def get_at_path(node: Any, path: tuple[str | int, ...]) -> Any:
    current = node
    try:
        for part in path:
            if isinstance(part, int):
                if not isinstance(current, list):
                    return None
                current = current[part]
            else:
                if not isinstance(current, dict):
                    return None
                current = current[part]
    except (IndexError, KeyError, TypeError):
        return None
    return current


def path_key(path: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in path)


def should_copy(source: str, path: tuple[str | int, ...]) -> bool:
    if not source.strip() or not re.search(r"[A-Za-z]", source):
        return True
    last = str(path[-1]).lower() if path else ""
    if last in NON_TRANSLATABLE_KEYS or any(
        last.endswith(suffix)
        for suffix in ("url", "href", "path", "command", "code", "icon")
    ):
        return True
    if re.fullmatch(r"https?://\S+", source) or re.fullmatch(r"/[A-Za-z0-9_./:@%+=-]+", source):
        return True
    if re.fullmatch(r"[A-Z0-9_.:/+-]{2,}", source):
        return True
    return False


def leaf_token(path: tuple[str | int, ...]) -> str:
    return json.dumps(path, ensure_ascii=False, separators=(",", ":"))


def source_fingerprints(source: Any) -> dict[str, str]:
    return {
        leaf_token(leaf.path): hashlib.sha256(leaf.source.encode("utf-8")).hexdigest()[:20]
        for leaf in iter_leaves(source)
    }


def needs_translation(
    source: str,
    target: Any,
    path: tuple[str | int, ...],
    refresh: bool,
    forced_tokens: set[str] | None = None,
) -> bool:
    if should_copy(source, path):
        return False
    if refresh:
        return True
    if forced_tokens and leaf_token(path) in forced_tokens:
        return True
    return not isinstance(target, str) or not target.strip() or target == source


def protect_rich_tags(text: str) -> tuple[str, dict[str, str]]:
    """Give translatable rich-text tags opaque names during translation.

    Google can remove semantic tags such as ``strong`` or ``em`` after
    translating their contents. Unknown tag names are retained, so rename
    non-literal tags temporarily and restore them before contract validation.
    Literal ``code``, ``kbd`` and ``pre`` elements stay untouched because the
    provider preserves both their markup and their contents.
    """

    names: dict[str, str] = {}
    reverse: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        original = match.group(1)
        if original.lower() in {"code", "kbd", "pre"}:
            return match.group(0)
        key = original.lower()
        internal = names.get(key)
        if internal is None:
            internal = f"pmxrich{len(names):04d}"
            names[key] = internal
            reverse[internal] = original
        slash = "/" if match.group(0).startswith("</") else ""
        return f"<{slash}{internal}>"

    return TAG_RE.sub(replace, text), reverse


def restore_rich_tags(text: str, mapping: dict[str, str]) -> str:
    for internal, original in mapping.items():
        text = re.sub(
            rf"<(/?){re.escape(internal)}>",
            lambda match: f"<{match.group(1)}{original}>",
            text,
            flags=re.IGNORECASE,
        )
    return text


def protect_text(text: str) -> tuple[str, dict[str, str]]:
    # Google already keeps both the markup and the contents of literal rich-
    # text blocks. Replacing a filename or path inside one of these blocks can
    # leave the sentinel as its only child, which the provider may discard.
    literal_ranges = [(match.start(), match.end()) for match in LITERAL_TAG_RE.finditer(text)]

    def overlaps_literal(start: int, end: int) -> bool:
        return any(start < literal_end and end > literal_start for literal_start, literal_end in literal_ranges)

    candidates: list[tuple[int, int]] = []
    for pattern in PROTECTED_PATTERNS:
        candidates.extend(
            (match.start(), match.end())
            for match in pattern.finditer(text)
            if not overlaps_literal(match.start(), match.end())
        )
    candidates.extend(
        (match.start(), match.end())
        for match in TERM_RE.finditer(text)
        if not overlaps_literal(match.start(), match.end())
    )
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    selected: list[tuple[int, int]] = []
    cursor = -1
    for start, end in candidates:
        if start >= cursor:
            selected.append((start, end))
            cursor = end

    mapping: dict[str, str] = {}
    chunks: list[str] = []
    cursor = 0
    for index, (start, end) in enumerate(selected):
        # Google Translate can drop underscore-delimited sentinels when they
        # sit directly beside inline markup (for example an opening <em>
        # token followed by translated prose). Triple brackets remain opaque
        # in that position and preserve the complete rich-text contract.
        token = f"[[[PMXDOC{index:04d}]]]"
        chunks.append(text[cursor:start])
        chunks.append(token)
        mapping[token] = text[start:end]
        cursor = end
    chunks.append(text[cursor:])
    return "".join(chunks), mapping


def restore_text(text: str, mapping: dict[str, str]) -> str:
    missing = [token for token in mapping if token not in text]
    if missing:
        raise ValueError(f"translation provider changed protected token {missing[0]}")
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


def validate_contract(source: str, target: str) -> None:
    if sorted(TAG_RE.findall(source)) != sorted(TAG_RE.findall(target)):
        raise ValueError("rich-text tag contract changed")
    if sorted(PLACEHOLDER_RE.findall(source)) != sorted(PLACEHOLDER_RE.findall(target)):
        raise ValueError("placeholder contract changed")


def provider_function(args: argparse.Namespace) -> Callable[[str, str], str]:
    def translate(text: str, language: str) -> str:
        if args.provider == "googletrans":
            raw = translate_googletrans(text, language, args.context)
        elif args.provider == "google-web":
            raw = translate_google_web(text, language, args.context, args.timeout)
        else:
            raw = translate_appimage(
                text,
                language,
                args.context,
                args.timeout,
                args.appimage_path,
            )
        return clean_translation(raw).strip()

    return translate


def translate_with_retry(
    source: str,
    language: str,
    translate: Callable[[str, str], str],
    retries: int,
    delay: float,
) -> str:
    rich_text, rich_mapping = protect_rich_tags(source)
    protected, mapping = protect_text(rich_text)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            translated = translate(protected, language)
            if not translated:
                raise ValueError("translation provider returned an empty value")
            translated = restore_text(translated, mapping)
            translated = restore_rich_tags(translated, rich_mapping)
            validate_contract(source, translated)
            return translated
        except Exception as exc:  # network/provider errors are retried together
            last_error = exc
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
    raise RuntimeError(str(last_error)) from last_error


def merge_tree(
    source: Any,
    target: Any,
    translations: dict[tuple[str | int, ...], str],
    path: tuple[str | int, ...] = (),
) -> Any:
    if isinstance(source, dict):
        target_dict = target if isinstance(target, dict) else {}
        return {
            key: merge_tree(value, target_dict.get(key), translations, path + (key,))
            for key, value in source.items()
        }
    if isinstance(source, list):
        target_list = target if isinstance(target, list) else []
        return [
            merge_tree(
                value,
                target_list[index] if index < len(target_list) else None,
                translations,
                path + (index,),
            )
            for index, value in enumerate(source)
        ]
    if isinstance(source, str):
        if path in translations:
            return translations[path]
        if should_copy(source, path):
            return source
        if isinstance(target, str) and target.strip():
            return target
        return source
    return source


def source_files(source_root: Path, section: str) -> list[Path]:
    scope = (source_root / section).resolve()
    root = source_root.resolve()
    if scope != root and root not in scope.parents:
        raise ValueError("section must stay inside the English messages directory")
    if scope.is_file():
        if scope.suffix != ".json":
            raise ValueError("section file must be JSON")
        return [scope]
    if not scope.is_dir():
        raise ValueError(f"section does not exist: {scope}")
    return sorted(
        path
        for path in scope.rglob("*.json")
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def collect_memory(source_root: Path, messages_root: Path, language: str) -> dict[str, str]:
    memory: dict[str, str] = {}
    conflicts: set[str] = set()
    for source_path in sorted(source_root.rglob("*.json")):
        if any(part.startswith(".") for part in source_path.relative_to(source_root).parts):
            continue
        target_path = messages_root / language / source_path.relative_to(source_root)
        source = read_json(source_path)
        target = read_json(target_path)
        if target is None:
            continue
        for leaf in iter_leaves(source):
            translated = get_at_path(target, leaf.path)
            if not isinstance(translated, str) or not translated.strip() or translated == leaf.source:
                continue
            previous = memory.get(leaf.source)
            if previous is not None and previous != translated:
                conflicts.add(leaf.source)
            else:
                memory[leaf.source] = translated
    for source in conflicts:
        memory.pop(source, None)
    return memory


def pending_leaves(
    source: Any,
    target: Any,
    refresh: bool,
    forced_tokens: set[str] | None = None,
) -> list[Leaf]:
    return [
        leaf
        for leaf in iter_leaves(source)
        if needs_translation(
            leaf.source,
            get_at_path(target, leaf.path),
            leaf.path,
            refresh,
            forced_tokens,
        )
    ]


def schema_matches(source: Any, target: Any) -> bool:
    if type(source) is not type(target):
        return False
    if isinstance(source, dict):
        return list(source) == list(target) and all(
            schema_matches(source[key], target[key]) for key in source
        )
    if isinstance(source, list):
        return len(source) == len(target) and all(
            schema_matches(left, right) for left, right in zip(source, target)
        )
    if isinstance(source, str):
        # Localized strings intentionally differ from the English source.
        return True
    # Booleans, numbers and null values are structural data and must stay in
    # sync with the English catalog instead of retaining an obsolete value.
    return source == target


def empty_source_state() -> dict[str, Any]:
    return {
        "version": SOURCE_STATE_VERSION,
        "initialized": False,
        "source": {},
        "pending": {},
    }


def load_source_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_source_state()
    try:
        value = read_json(path)
    except ValueError:
        return empty_source_state()
    if not isinstance(value, dict) or value.get("version") != SOURCE_STATE_VERSION:
        return empty_source_state()
    if not isinstance(value.get("source"), dict) or not isinstance(value.get("pending"), dict):
        return empty_source_state()
    value.setdefault("initialized", True)
    return value


def state_pending_tokens(state: dict[str, Any], language: str, relative: str) -> set[str]:
    language_state = state.setdefault("pending", {}).setdefault(language, {})
    values = language_state.get(relative, [])
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values}


def set_state_pending_tokens(
    state: dict[str, Any], language: str, relative: str, tokens: set[str]
) -> None:
    language_state = state.setdefault("pending", {}).setdefault(language, {})
    if tokens:
        language_state[relative] = sorted(tokens)
    else:
        language_state.pop(relative, None)
    if not language_state:
        state["pending"].pop(language, None)


def translate_file(
    source: Any,
    target: Any,
    leaves: list[Leaf],
    language: str,
    memory: dict[str, str],
    translate: Callable[[str, str], str],
    args: argparse.Namespace,
) -> tuple[Any | None, list[str], int]:
    resolved: dict[tuple[str | int, ...], str] = {}
    failures: list[str] = []
    jobs: dict[str, list[tuple[str | int, ...]]] = {}

    for leaf in leaves:
        if not args.refresh and leaf.source in memory:
            resolved[leaf.path] = memory[leaf.source]
            continue
        jobs.setdefault(leaf.source, []).append(leaf.path)

    if jobs:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    translate_with_retry,
                    text,
                    language,
                    translate,
                    args.retries,
                    args.retry_delay,
                ): text
                for text in jobs
            }
            for future in as_completed(futures):
                text = futures[future]
                try:
                    translated = future.result()
                    memory[text] = translated
                    for path in jobs[text]:
                        resolved[path] = translated
                except Exception as exc:
                    failures.append(f"{text[:90]}: {exc}")
                if args.sleep:
                    time.sleep(args.sleep)

    if failures:
        return None, failures, len(jobs)
    return merge_tree(source, target, resolved), [], len(jobs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("web/messages/en"))
    parser.add_argument("--messages-dir", type=Path, default=Path("web/messages"))
    parser.add_argument("--languages", default=",".join(DEFAULT_LANGUAGES))
    parser.add_argument(
        "--section",
        default=".",
        help="Relative file or directory below the English messages directory.",
    )
    parser.add_argument(
        "--provider",
        choices=("google-web", "googletrans", "appimage"),
        default="googletrans",
    )
    parser.add_argument("--appimage-path", type=Path, default=Path("ProxMenux-Monitor.AppImage"))
    parser.add_argument(
        "--source-state",
        type=Path,
        default=None,
        help=(
            "Source fingerprint state used to detect changed English strings. "
            "Defaults to <messages-dir>/.docs-i18n-source-state.json."
        ),
    )
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Maximum pending files per locale; zero processes all files.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Overwrite existing translations in the selected scope.",
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.workers < 1 or args.retries < 0 or args.max_files < 0:
        print("workers must be positive; retries and max-files cannot be negative", file=sys.stderr)
        return 2

    source_root = args.source_dir.resolve()
    messages_root = args.messages_dir.resolve()
    source_state_path = (
        args.source_state.resolve()
        if args.source_state is not None
        else messages_root / ".docs-i18n-source-state.json"
    )
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    try:
        files = source_files(source_root, args.section)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if not languages:
        print("No target languages selected.", file=sys.stderr)
        return 2
    if args.refresh:
        print("WARNING: --refresh overwrites existing translations in the selected scope.")

    translate = provider_function(args)
    state = load_source_state(source_state_path)
    state_was_initialized = bool(state.get("initialized"))
    previous_source_state = state.setdefault("source", {})

    file_info: dict[
        str, tuple[Path, Any, dict[str, str], set[str], set[str]]
    ] = {}
    selected_relatives: set[str] = set()
    for source_path in files:
        relative = source_path.relative_to(source_root).as_posix()
        selected_relatives.add(relative)
        source = read_json(source_path)
        current_fingerprints = source_fingerprints(source)
        translatable_tokens = {
            leaf_token(leaf.path)
            for leaf in iter_leaves(source)
            if not should_copy(leaf.source, leaf.path)
        }
        previous_fingerprints = previous_source_state.get(relative, {})
        if not isinstance(previous_fingerprints, dict):
            previous_fingerprints = {}
        if state_was_initialized:
            changed_tokens = {
                token
                for token, fingerprint in current_fingerprints.items()
                if token in translatable_tokens
                # Existing English leaves whose text changed must be sent to
                # the provider even when the target still contains the old,
                # non-empty translation. New leaves are handled by the usual
                # missing-target detection, preserving a translation supplied
                # manually in the same commit.
                and token in previous_fingerprints
                and previous_fingerprints[token] != fingerprint
            }
        else:
            # The first run establishes the baseline without replacing
            # existing human/Codex translations. Missing target values are
            # still discovered separately for every locale below.
            changed_tokens = set()
        file_info[relative] = (
            source_path,
            source,
            current_fingerprints,
            changed_tokens,
            translatable_tokens,
        )

    # Materialize every locale's pending queue before advancing the shared
    # English baseline. If the runner stops halfway through, unprocessed
    # locales retain the exact changed leaf tokens for the next run.
    for language in languages:
        for relative, (
            _,
            source,
            _,
            changed_tokens,
            translatable_tokens,
        ) in file_info.items():
            target_path = messages_root / language / relative
            target = read_json(target_path)
            pending_tokens = (
                state_pending_tokens(state, language, relative)
                & translatable_tokens
            )
            pending_tokens.update(changed_tokens)
            pending_tokens.update(
                leaf_token(leaf.path)
                for leaf in pending_leaves(source, target, args.refresh)
            )
            set_state_pending_tokens(state, language, relative, pending_tokens)

    for relative, (_, _, current_fingerprints, _, _) in file_info.items():
        previous_source_state[relative] = current_fingerprints
    state["initialized"] = True

    # A complete run also mirrors deletion of an English catalog. Partial
    # --section runs deliberately leave unrelated paths untouched.
    if args.section in (".", ""):
        removed_files = set(previous_source_state) - selected_relatives
        for relative in sorted(removed_files):
            for language in languages:
                target_path = messages_root / language / relative
                if target_path.exists() and not (args.check or args.dry_run):
                    target_path.unlink()
                    print(f"[{language}] removed obsolete catalog {target_path}")
                set_state_pending_tokens(state, language, relative, set())
            previous_source_state.pop(relative, None)

    if not (args.check or args.dry_run):
        write_json(source_state_path, state)

    total_failures = 0
    total_written = 0
    print(f"English files: {len(files)} | locales: {', '.join(languages)}")

    for language in languages:
        memory = collect_memory(source_root, messages_root, language)
        # A target value paired with a newly changed English source is the old
        # translation, not valid translation memory for the new sentence.
        # Remove every queued source text before provider reuse; successful
        # translations repopulate memory normally for later files.
        queued_source_texts: set[str] = set()
        for relative_key, (_, source, _, _, _) in file_info.items():
            queued_tokens = state_pending_tokens(state, language, relative_key)
            queued_source_texts.update(
                leaf.source
                for leaf in iter_leaves(source)
                if leaf_token(leaf.path) in queued_tokens
            )
        for source_text in queued_source_texts:
            memory.pop(source_text, None)
        pending: list[
            tuple[Path, Path, Any, Any, list[Leaf], set[str], bool]
        ] = []
        total_strings = 0
        missing_strings = 0

        for source_path in files:
            relative = source_path.relative_to(source_root)
            relative_key = relative.as_posix()
            target_path = messages_root / language / relative
            source = file_info[relative_key][1]
            target = read_json(target_path)
            queued_tokens = state_pending_tokens(state, language, relative_key)
            leaves = pending_leaves(source, target, args.refresh, queued_tokens)
            total_strings += len(iter_leaves(source))
            missing_strings += len(leaves)
            schema_changed = not schema_matches(source, target)
            if leaves or schema_changed:
                pending.append(
                    (
                        source_path,
                        target_path,
                        source,
                        target,
                        leaves,
                        queued_tokens,
                        schema_changed,
                    )
                )

        print(
            f"[{language}] {missing_strings}/{total_strings} strings pending "
            f"across {len(pending)} files; reusable translations: {len(memory)}"
        )
        if args.check or args.dry_run:
            continue
        if args.max_files:
            pending = pending[: args.max_files]

        for index, (
            source_path,
            target_path,
            source,
            target,
            leaves,
            queued_tokens,
            schema_changed,
        ) in enumerate(pending, 1):
            relative = source_path.relative_to(source_root)
            relative_key = relative.as_posix()
            suffix = " + schema sync" if schema_changed else ""
            print(
                f"[{language} {index}/{len(pending)}] {relative} "
                f"({len(leaves)} strings{suffix})",
                flush=True,
            )
            built, failures, calls = translate_file(
                source,
                target,
                leaves,
                language,
                memory,
                translate,
                args,
            )
            if failures:
                total_failures += len(failures)
                set_state_pending_tokens(state, language, relative_key, queued_tokens)
                write_json(source_state_path, state)
                print(
                    f"  skipped atomically after {len(failures)} failures "
                    f"({calls} calls)",
                    file=sys.stderr,
                )
                for failure in failures[:5]:
                    print(f"  - {failure}", file=sys.stderr)
                continue
            write_json(target_path, built)
            set_state_pending_tokens(state, language, relative_key, set())
            write_json(source_state_path, state)
            total_written += 1
            print(f"  wrote {target_path} ({calls} provider calls)", flush=True)

    if args.check or args.dry_run:
        return 0
    print(f"Completed: {total_written} files written; {total_failures} failed strings.")
    return 1 if args.strict and total_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
