# Contributing translations

The ProxMenux documentation site is built with Next.js (App Router) and
serves every page under two URLs:

- `/en/<path>` — English, the source of truth
- `/es/<path>` — Spanish, in progress

We use [`next-intl`](https://next-intl.dev) for the i18n plumbing. Anyone
can translate the docs without writing TypeScript: most of the work is
filling in a JSON file. This guide explains the workflow end to end.

> **Default policy: small, focused PRs.** One page per pull request. Big
> bundles of "I translated 30 pages at once" are hard to review and
> merge cleanly when several contributors are working in parallel.

---

## What's already wired

Out of the box you get:

- Routing under `app/[locale]/...` — every page already renders at both
  `/en/...` and `/es/...`.
- Locale-aware navigation via `@/i18n/navigation` (`<Link>`, `useRouter`,
  `usePathname`). Use these instead of `next/link` for internal hrefs so
  the active `[locale]` prefix is preserved.
- A language switcher in the navbar (`<LanguageSwitcher />`).
- Automatic message discovery: any JSON file under
  `messages/<locale>/...` is loaded and merged into a single namespace
  tree. **You never need to register a new file anywhere**, the build
  picks it up automatically.
- Fallback to English when a translation is missing — pages render in
  English instead of breaking with a `MISSING_MESSAGE` placeholder.

---

## File layout

```
web/
├── i18n/
│   ├── routing.ts          # supported locales + default
│   ├── request.ts          # per-request config (uses loadMessages)
│   ├── loadMessages.ts     # walks messages/<locale>/ and builds the tree
│   └── navigation.ts       # locale-aware Link, useRouter, etc.
├── messages/
│   ├── en/
│   │   ├── common.json     # shared strings (nav, footer, language switcher)
│   │   └── docs/
│   │       └── monitor/
│   │           └── index.json   # page-specific strings for /docs/monitor
│   └── es/
│       ├── common.json
│       └── docs/
│           └── monitor/
│               └── index.json
└── app/[locale]/
    └── docs/
        └── monitor/
            └── page.tsx    # the page itself
```

### Naming convention

- `common.json` and `index.json` at any folder level → keys are merged
  at the current namespace level (no extra nesting). Use these for
  "this whole folder" or "this whole section" defaults.
- `<name>.json` at any folder level → keys go under the `<name>`
  namespace.
- Sub-directories nest as additional namespaces, with **kebab-case
  converted to camelCase** in the JS API. So
  `messages/en/docs/monitor/access-auth.json` is consumed as
  `getTranslations({ namespace: 'docs.monitor.accessAuth' })`.

---

## Workflow: translate one page

### 1. Pick a page

Browse `app/[locale]/docs/` and find a page that:

- Has no entry yet under `messages/es/<same-path>/` (Spanish), **and**
- Is not already mid-translation by someone else (check open PRs).

If you're translating to a new locale, start with the smallest pages so
you can submit early PRs and get feedback before tackling the big ones.

### 2. Check whether the page is already i18n-ready

There are two cases:

**Case A — the page already uses `getTranslations()`** (look for an
`import` from `next-intl/server` and `t()` calls in JSX). Your job is
straightforward: only create the `messages/<locale>/<path>.json` file
with the translated strings. **You don't touch the `.tsx` file at all**.

**Case B — the page still has hard-coded English strings in JSX.** You
need both:

1. Refactor the page to read its strings from a JSON file (this part
   touches the `.tsx`).
2. Provide the English JSON (the source of truth) **and** the
   translated JSON.

The pilot page `app/[locale]/docs/monitor/page.tsx` is the reference
implementation for case B — copy its patterns.

### 3. Add the JSON

Create `messages/<locale>/<same-path-as-page>.json` (or `index.json` if
the page is the section index). Mirror the English file's structure
exactly — every key must exist in both, only the values change.

If a key contains inline HTML-style tags (`<code>`, `<strong>`,
`<em>`, `<link>`, `<linkApi>`, etc.), keep them in the same positions
in your translation. They're not real HTML — they're placeholders that
the page renders via `t.rich()` and substitutes for real React nodes.
Example:

```json
{
  "intro": "Eight first-class sections, backed by their own API endpoints."
}
```

```json
{
  "intro": "Ocho secciones principales, respaldadas por sus propios endpoints de API."
}
```

```json
{
  "footer": "See the <link>Architecture</link> page for details."
}
```

```json
{
  "footer": "Mira la página de <link>Architecture</link> para más detalles."
}
```

### 4. Test locally

```bash
cd web
npm run dev
```

Open `http://localhost:3000/<locale>/<page-path>` and check that:

- All your translated strings render correctly.
- No `MISSING_MESSAGE` text appears (means a key is in the page's
  `.tsx` but missing from your JSON).
- The page still passes `npm run build` cleanly.

### 5. Open the PR

One page per PR is the convention. Title format:

```
docs(i18n/<locale>): translate <route>
```

Examples:

- `docs(i18n/es): translate /docs/monitor`
- `docs(i18n/fr): translate /docs/monitor/notifications`

In the description, mention which page you translated and whether you
also had to refactor the `.tsx` (case B) or only added JSON (case A).

---

## Workflow: convert a page from hard-coded English to i18n (case B)

This is the more involved path. Use the pilot
`app/[locale]/docs/monitor/page.tsx` as the reference.

### High-level changes to the `.tsx`

1. Make the page an **async Server Component** that receives
   `params: Promise<{ locale: string }>`.
2. Add `generateStaticParams()` that returns one entry per locale (see
   `routing.locales` in `i18n/routing.ts`).
3. If the page exports `metadata`, replace it with `generateMetadata()`
   that reads from `getTranslations({ namespace: '<page>.meta' })`.
4. Call `setRequestLocale(locale)` near the top of the component body.
5. Call `await getTranslations({ locale, namespace: 'docs.<section>.<page>' })`
   and rename it to `t`.
6. Replace every English string in JSX with `t('key')` (plain text) or
   `t.rich('key', { code, strong, em, link, ... })` for strings with
   inline tags.
7. For lists / tables of structured items (e.g. table rows, nav items),
   pull the array from `getMessages()` and iterate.

### JSON file structure

Use the pilot's `messages/en/docs/monitor/index.json` as the template.
The high-level shape is:

```json
{
  "meta": {
    "title": "...",
    "description": "...",
    "ogTitle": "...",
    "ogDescription": "...",
    "twitterTitle": "...",
    "twitterDescription": "..."
  },
  "header": {
    "title": "...",
    "description": "...",
    "section": "..."
  },
  "<section1>": { ... },
  "<section2>": { ... }
}
```

Group keys by the section they appear in. Keep nesting shallow (2-3
levels max) so the JSON stays readable for translators.

### Rich-text placeholder tags

When a paragraph contains inline elements like `<code>` or `<strong>`,
encode them in the JSON exactly as you want them to appear — but
remember they're **placeholders**, not real HTML. The `.tsx` registers
React renderers for each tag name in the call:

```tsx
t.rich("intro", {
  code: (chunks) => <code>{chunks}</code>,
  strong: (chunks) => <strong>{chunks}</strong>,
  link: (chunks) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  ),
})
```

Translators just have to keep the tags in roughly the same positions.
Don't introduce new tag names in the JSON unless the `.tsx` also
registers a renderer for them.

---

## What's intentionally NOT translatable

- **Code blocks** (inside `CopyableCode` etc.) — only the comment lines
  (`# Comment here`) should be moved to JSON if they're explanatory.
  Don't translate code keywords, command names or paths.
- **URLs and paths** (`/docs/monitor`, `https://github.com/...`) —
  these stay identical across locales.
- **External link labels** like "GitHub", "ProxMenux" — proper nouns
  and product names stay in their original form.
- **Variable names, environment variables, file names** (`auth.json`,
  `MONITOR_VERSION`, `/var/log/journal/`) — never translated.

---

## Adding a new locale

If you want to add a language that isn't in the project yet:

1. Add the locale code to `routing.ts`:
   ```ts
   export const routing = defineRouting({
     locales: ["en", "es", "fr"],  // add your code here
     defaultLocale: "en",
     localePrefix: "always",
   })
   ```
2. Create the `messages/<locale>/` folder.
3. Copy `messages/en/common.json` over and translate it. **This is
   mandatory** — without it the navbar and footer fall back to English
   on every page.
4. Start translating individual pages one PR at a time.
5. Mention in your first PR that you're seeding the locale so reviewers
   know to expect a follow-up batch.

---

## FAQ

### My translated page still shows English text. Why?

Three common causes:

1. The page file is **case A** (uses `getTranslations()`) and your JSON
   path doesn't match the namespace it expects. Check the page's
   `getTranslations({ namespace: '...' })` call and mirror it in your
   folder structure.
2. The page is **case B** (still hard-coded). It needs the `.tsx`
   refactored first — that part is a developer task, not a translator
   task.
3. The dev server is serving cached output. Stop it (Ctrl+C), remove
   `web/.next/`, and run `npm run dev` again.

### What about translations of the Monitor (the AppImage), not just the docs?

This guide only covers the **public documentation site** in `web/`.
The Monitor's dashboard UI in `AppImage/` is a separate project and
not currently i18n-enabled. Translating the Monitor would require a
parallel effort.

### Where can I see what's missing?

Compare the directory trees:

```bash
diff -rq web/messages/en web/messages/es
```

Anything listed as "Only in en" still needs a Spanish version. (Swap
`es` for your locale.)

### My PR conflicts with another translator's PR.

Because we keep one page per PR, the only realistic conflict zone is
`messages/<locale>/common.json` (shared strings) or
`app/[locale]/docs/<section>/page.tsx` (refactored at the same time).
Rebase on `develop` and re-resolve; ping the other contributor in the
PR thread if the merge is non-obvious.
