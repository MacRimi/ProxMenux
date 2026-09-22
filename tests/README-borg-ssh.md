# Borg SSH guidance checks

These standalone checks are separate from the Python i18n suite. They do not
contact a Proxmox host or generate SSH keys.

## JSX/provider regression

Prerequisites: Node **22.14+** and installed `AppImage` dependencies (including
React, React DOM and TypeScript). From the repository root:

```bash
node tests/test_borg_ssh_guidance.cjs
```

The test extracts the actual SSH branch from `AddDestinationDialog`, renders it
with React, and executes the actual provider's lookup/interpolation callback.
Basic control wrappers replace shadcn components only in this fast test. It covers
all shipped catalogs, unconditional missing-key English fallback, synthetic
whole-message translations and reordered placeholders, initial/result/loading
states, account escaping, blank/custom paths and literal public-key output.
The optional `account` argument isolates the remote-account instruction.

## Real-component browser fixture

Additional prerequisites: `esbuild`, `playwright`, its Chromium browser and a
successful full Monitor frontend build. The validation runtime used esbuild
0.28.2 and Playwright 1.63.0. If these optional tools are not installed, install
them locally without changing the project manifests/lockfile:

```bash
cd AppImage
npm install --no-save --package-lock=false --legacy-peer-deps esbuild@0.28.2 playwright@1.63.0
node node_modules/playwright/cli.js install chromium
npm run build
cd ..
node tests/test_borg_ssh_browser.cjs /absolute/path/to/borg-browser-evidence
```

The fixture bundles the actual complete `AddDestinationDialog`, real shadcn
components, real API helper and `I18nProvider`, with CSS from `AppImage/out` by default. Set `BORG_SSH_CSS_DIR` to the
`_next/static/css` directory of an archived full build to reuse that build's CSS.
A test-only in-memory export exposes the unexported dialog; production source is
not rewritten. Browser locale fixtures omit the six new keys from Italian and
supply expanded/reordered synthetic messages in German **in memory only**.
They are not proposed translations.

All requests are intercepted **before navigation**. Known static resources and
read endpoints are fulfilled from fixtures; key preparation POSTs receive inert
fresh/existing/error responses. All other requests, including Save, are aborted
and make the run fail. No server is needed. The test checks current request
payloads and characterizes unchanged last-response retention after field edits
and errors; mocked fresh/existing responses are not a backend generation test.

The matrix is desktop/mobile (1440×1000, 390×844), light/dark, English/forced
Italian fallback/synthetic expansion. It writes initial/result screenshots and
`browser-results.json`, and asserts message/button horizontal fit. The modal is
scrolled to show the relevant panel; this is not whole-dashboard acceptance.

## Other gates

```bash
python3 -m unittest discover -s .github/scripts/tests -v
cd AppImage
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

Run typechecking separately: the production build skips it. Compare diagnostics
against the unchanged baseline with the same dependencies; a successful build
is not a clean typecheck. CONTRIBUTING's real-Proxmox deployment smoke test is a
separate integration gate and is not replaced by these fixtures.
