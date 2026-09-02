#!/usr/bin/env python3
"""ProxMenux AI-model verifier.

Runs a standardized translate+explain test against every model each
provider currently advertises, and emits a per-model verdict so the
verified_ai_models.json list can be refreshed with confidence.

Not packaged with the AppImage — keep this in a private repo alongside
the API keys.

Usage:
    cp .env.example .env                       # fill in the API keys you have
    python3 verify.py                          # test all providers with keys
    python3 verify.py --provider groq          # just one
    python3 verify.py --provider openai --limit 5    # only first 5 models
    python3 verify.py --json-out report.json   # machine-readable output too
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from prompts import DOMAIN_HINTS, REQUIRED_SPANISH_HINTS, SYSTEM_PROMPT, USER_MESSAGE
from providers import PROVIDERS, make_provider


# Non-chat model name patterns. Skipping these saves test time and keeps
# the report focused on models that could actually serve notifications.
SKIP_PATTERNS = (
    "embedding", "whisper", "tts", "dall-e", "dalle", "image",
    "realtime", "audio", "moderation", "search",
    "code-search", "text-similarity", "babbage", "davinci",
    "curie", "ada", "transcribe",
)


def load_env(env_path: Path) -> Dict[str, str]:
    """Minimal .env loader (avoids a python-dotenv dependency)."""
    if not env_path.exists():
        return {}
    env: Dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def should_skip_model(model: str) -> bool:
    m = model.lower()
    return any(p in m for p in SKIP_PATTERNS)


def assess_response(text: str) -> Tuple[str, List[str]]:
    """Classify the model output. Returns (verdict, reasons).

    verdict is one of:
      - 'pass':  Spanish, on-topic, reasonable length
      - 'warn':  responded but one heuristic failed (borderline)
      - 'fail':  empty, wrong language, or off-topic
    """
    reasons: List[str] = []
    if not text or len(text) < 30:
        return "fail", ["empty or too short response"]

    text_low = " " + text.lower() + " "
    spanish_hits = sum(1 for h in REQUIRED_SPANISH_HINTS if h in text_low)
    domain_hits = sum(1 for h in DOMAIN_HINTS if h.lower() in text_low)

    if spanish_hits < 3:
        reasons.append(f"not Spanish ({spanish_hits}/{len(REQUIRED_SPANISH_HINTS)} hints)")
    if domain_hits < 1:
        reasons.append("did not engage with the domain")
    if len(text) > 1500:
        reasons.append("response unusually long")

    if not reasons:
        return "pass", []
    # Responded and engaged, but one signal missed → warn (keep in list
    # with a caveat; don't auto-include).
    if domain_hits >= 1 and spanish_hits >= 1:
        return "warn", reasons
    return "fail", reasons


def run_model(provider, model: str, timeout: int) -> dict:
    t0 = time.time()
    try:
        out = provider.generate(
            model, SYSTEM_PROMPT, USER_MESSAGE,
            max_tokens=250, timeout=timeout,
        )
        latency = time.time() - t0
        verdict, reasons = assess_response(out)
        return {
            "model": model,
            "verdict": verdict,
            "latency_s": round(latency, 2),
            "reasons": reasons,
            "sample": (out[:140] if out else "").replace("\n", " "),
            "error": None,
        }
    except Exception as exc:  # HTTPError, ProviderError, timeouts
        return {
            "model": model,
            "verdict": "fail",
            "latency_s": round(time.time() - t0, 2),
            "reasons": [],
            "sample": "",
            "error": str(exc)[:200],
        }


def tag(verdict: str) -> str:
    return {"pass": "✓", "warn": "⚠", "fail": "✗"}.get(verdict, "?")


def run_provider(name: str, api_key: str, base_url: Optional[str],
                 timeout: int, limit: Optional[int]) -> dict:
    print(f"\n=== {name} ===")
    try:
        provider = make_provider(name, api_key, base_url=base_url)
        models = provider.list_models()
    except Exception as exc:
        print(f"  list_models() failed: {exc}")
        return {"provider": name, "error": str(exc), "results": []}

    models = [m for m in models if not should_skip_model(m)]
    if limit:
        models = models[:limit]
    if not models:
        print("  (no eligible models)")
        return {"provider": name, "error": None, "results": []}

    print(f"  discovered {len(models)} model(s)")
    results: List[dict] = []
    for m in models:
        r = run_model(provider, m, timeout)
        results.append(r)
        latency = f"{r['latency_s']}s"
        if r["error"]:
            suffix = f" — {r['error']}"
        elif r["reasons"]:
            suffix = f" — {'; '.join(r['reasons'])}"
        else:
            suffix = ""
        print(f"  {tag(r['verdict'])} {m:<50} {latency:>6}{suffix}")

    return {"provider": name, "error": None, "results": results}


def summarize(all_results: List[dict]) -> None:
    print("\n" + "=" * 64)
    print("Suggested verified_ai_models.json entries (passing models only)")
    print("=" * 64)
    any_output = False
    for pr in all_results:
        if pr.get("error"):
            continue
        passed = [r for r in pr["results"] if r["verdict"] == "pass"]
        if not passed:
            continue
        any_output = True
        passed_sorted = sorted(passed, key=lambda x: x["latency_s"])
        print(f'\n  "{pr["provider"]}": {{')
        print('    "models": [')
        for r in passed_sorted:
            print(f'      "{r["model"]}",')
        print("    ],")
        print(f'    "recommended": "{passed_sorted[0]["model"]}"')
        print("  },")

    warn_total = sum(
        1 for pr in all_results for r in pr["results"]
        if r["verdict"] == "warn"
    )
    if warn_total:
        print(f"\n  Note: {warn_total} model(s) came back as ⚠ (warn) — review those manually.")
    if not any_output:
        print("\n  (no models passed; check keys and network)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify AI models for ProxMenux notification enrichment."
    )
    ap.add_argument("--env", default=".env", help=".env file path")
    ap.add_argument("--provider", action="append", default=[],
                    help="run a specific provider (repeat to add more)")
    ap.add_argument("--timeout", type=int, default=30,
                    help="seconds per request (default: 30)")
    ap.add_argument("--limit", type=int, default=None,
                    help="test at most N models per provider (debug)")
    ap.add_argument("--json-out", default=None,
                    help="write machine-readable report to this path")
    args = ap.parse_args()

    env = {**os.environ, **load_env(Path(args.env))}

    provider_list = args.provider or list(PROVIDERS.keys())
    tested: List[dict] = []
    for name in provider_list:
        if name not in PROVIDERS:
            print(f"unknown provider: {name}", file=sys.stderr)
            continue
        key_var = f"{name.upper()}_API_KEY"
        url_var = f"{name.upper()}_BASE_URL"
        api_key = env.get(key_var, "")
        base_url = env.get(url_var) or None
        if not api_key:
            print(f"\n=== {name} ===\n  skipped — {key_var} not set")
            continue
        tested.append(run_provider(name, api_key, base_url, args.timeout, args.limit))

    summarize(tested)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(tested, indent=2))
        print(f"\nReport written to {args.json_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
