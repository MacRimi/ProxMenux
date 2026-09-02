#!/usr/bin/env python3
"""Apply a verifier report to ``AppImage/config/verified_ai_models.json``.

Reads the machine-readable report emitted by ``verify.py --json-out`` and
merges the passing models into the on-disk catalog:

* Passing models per provider replace the existing ``models`` list.
* ``recommended`` is set to the fastest passing model.
* Existing ``_note`` / ``_deprecated`` / provider metadata is preserved
  when unchanged so the file's manual annotations survive the automated
  refresh.
* Providers absent from the report (e.g. no API key configured in the
  GitHub Action for that run) are left untouched — the goal is
  additive maintenance, not silent removal.
* ``_updated`` bumps to today's date only when the model set actually
  changes; a no-op run leaves the file byte-identical.

Exits 0 when the file is unchanged, 10 when it was updated. The
workflow uses that exit code to decide whether to commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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


def _passing_models(provider_report: dict) -> list[str]:
    """Return the passing models for one provider, fastest first."""
    passing = [r for r in provider_report.get("results", []) if r.get("verdict") == "pass"]
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
        passing = _passing_models(provider_report)
        if not passing:
            print(f"[{name}] no passing models this run — leaving catalog untouched",
                  file=sys.stderr)
            continue

        block = catalog.setdefault(name, {})
        prev_models = list(block.get("models", []))
        prev_recommended = block.get("recommended", "")

        if sorted(prev_models) != sorted(passing) or prev_recommended != passing[0]:
            block["models"] = passing
            block["recommended"] = passing[0]
            changed = True
            print(f"[{name}] updated — {len(passing)} models, recommended={passing[0]}")
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
