# AI models verifier (public copy)

Standalone verifier used by the daily GitHub Action to refresh
`AppImage/config/verified_ai_models.json`.

The code lives here so the Action can execute it. API keys are read from
GitHub Secrets at run time and never written to disk.

Local dev runs (interactive verifier over your own keys) can keep using
the private copy — `verify.py` is identical.

## What the Action does

Each run:

1. Loads keys from Secrets into environment variables.
2. Runs `verify.py --json-out /tmp/report.json` against every provider that
   has a key set.
3. Rewrites `AppImage/config/verified_ai_models.json` with the passing
   models, sorted with the recommended one first per provider.
4. Bumps the `_updated` field to the current date.
5. If the file changed, commits directly to `main` as a bot commit.

## Adding provider keys

- Repository → Settings → Secrets and variables → Actions.
- Add each key with the exact name expected by `verify.py`:
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
  `OPENROUTER_API_KEY`.
- Any provider without a key is silently skipped — the Action logs a
  warning and continues with the rest.

## Running the Action on demand

The workflow accepts `workflow_dispatch`, so you can trigger a refresh
manually from the Actions tab. Useful when a new model has just been
released upstream and you don't want to wait for the daily cron.
