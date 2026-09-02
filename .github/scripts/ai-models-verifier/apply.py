#!/usr/bin/env python3
"""Apply a verifier report to ``AppImage/config/verified_ai_models.json``.

Reads the machine-readable report emitted by ``verify.py --json-out`` and
merges the passing models into the on-disk catalog. Preserves the
maintainer's editorial curation across three axes:

* ``_exclude``: per-provider list of model IDs (exact match) that must
  never appear in the surfaced ``models`` list even when the verifier
  passes them. Meant for models that respond correctly to the technical
  test but are the wrong fit for notification translation — Arabic-only
  bases, Chinese-first fine-tunes, safety-classifier variants,
  agentic-only endpoints, legacy dated snapshots, etc.
* ``recommended``: if the current recommendation is still in the
  passing (and non-excluded) set, it is preserved. Only when the
  previous recommendation disappears (deprecated upstream, or newly
  excluded) is a fallback chosen — the fastest passing model.
* ``_note`` / ``_deprecated``: never touched. Those are maintainer
  annotations that outlive any single verifier run.

Fail-safe rules:
* Providers absent from the report (no API key configured in the
  Action for that run) are left untouched.
* Providers whose report carries an error are left untouched.
* If the ``_exclude`` filter drops every passing model, the block is
  left untouched — an empty models list would silently kill the
  provider in the UI; keeping the previous list is more forgiving
  than shipping "nothing works".
* ``_updated`` bumps to today's date only when the merge actually
  changed something. A no-op run leaves the file byte-identical.

Exits 0 when the file is unchanged, 10 when it was updated. The
workflow uses that exit code to decide whether to commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def _is_excluded(model: str, patterns: list[str]) -> bool:
    """Match a model against the ``_exclude`` list. Supports exact
    matches and shell-style globs (``gpt-4o-*``, ``*-2024-*``, ...) so
    a provider that periodically publishes dated snapshots can be
    covered by a single pattern instead of one entry per date."""
    for pat in patterns:
        if pat == model or fnmatch.fnmatchcase(model, pat):
            return True
    return False


def _passing_models(provider_report: dict, exclude: list[str]) -> list[str]:
    """Passing models minus the editorial exclusion list, fastest first."""
    passing = [
        r for r in provider_report.get("results", [])
        if r.get("verdict") == "pass" and not _is_excluded(r.get("model", ""), exclude)
    ]
    passing.sort(key=lambda r: r.get("latency_s", 999))
    return [r["model"] for r in passing]


def apply_report(report_path: Path, catalog_path: Path, today: str) -> bool:
    """Rewrite the catalog from the report. Returns True if it changed."""
    report = _load_json(report_path)
    catalog = _load_json(catalog_path) if catalog_path.exists() else {}

    changed = False
    for provider_report in report:
        name = provider_report.get("provider")
        if not name:
            continue
        if provider_report.get("error"):
            print(f"[{name}] skipped — verifier reported error: {provider_report['error']}",
                  file=sys.stderr)
            continue

        block = catalog.setdefault(name, {})
        exclude = list(block.get("_exclude", []))
        passing = _passing_models(provider_report, exclude)

        if not passing:
            # Either the verifier returned no passes for this provider,
            # or every pass got filtered by _exclude. Both cases mean
            # "no signal we can trust to overwrite the curated list";
            # leaving the block alone is safer than blanking it.
            print(f"[{name}] skipped — no passing models after exclude filter",
                  file=sys.stderr)
            continue

        prev_models = list(block.get("models", []))
        prev_recommended = block.get("recommended", "")
        # Preserve the maintainer's choice of recommended when it is
        # still valid. Only fall back to fastest when the previous
        # value disappeared from the passing set.
        recommended = prev_recommended if prev_recommended in passing else passing[0]

        if sorted(prev_models) != sorted(passing) or prev_recommended != recommended:
            block["models"] = passing
            block["recommended"] = recommended
            changed = True
            print(f"[{name}] updated — {len(passing)} models, recommended={recommended}")
        else:
            print(f"[{name}] unchanged — {len(passing)} models")

    if changed:
        catalog["_updated"] = today
        _save_json(catalog_path, catalog)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, help="verify.py --json-out path")
    ap.add_argument("--catalog", required=True,
                    help="AppImage/config/verified_ai_models.json path")
    ap.add_argument("--today", default=None,
                    help="Override the date written into _updated (YYYY-MM-DD).")
    args = ap.parse_args()

    today = args.today or dt.datetime.utcnow().strftime("%Y-%m-%d")
    changed = apply_report(Path(args.report), Path(args.catalog), today)
    return 10 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
