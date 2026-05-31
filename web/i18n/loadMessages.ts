import fs from "fs"
import path from "path"

/**
 * Recursively load every translation JSON under `messages/<locale>/`
 * and assemble them into a single nested object that next-intl can
 * read via `useTranslations(namespace)`.
 *
 * Convention:
 *   - `common.json` or `index.json` at any folder → its keys are merged
 *     at the current level (no extra namespace).
 *   - any other `<name>.json` → its content becomes a nested key under
 *     `<name>`.
 *   - subdirectories become nested keys themselves.
 *
 * Example:
 *   messages/en/common.json                 → root  (nav.home, footer.*)
 *   messages/en/docs/monitor/index.json     → docs.monitor.*
 *   messages/en/docs/monitor/access-auth.json → docs.monitor.accessAuth.*
 *
 * This runs at build time (Next.js `getRequestConfig` is invoked during
 * static generation under `output: "export"`) so the filesystem walk is
 * fine — no runtime cost.
 */
export function loadMessages(locale: string): Record<string, unknown> {
  const root = path.join(process.cwd(), "messages", locale)
  if (!fs.existsSync(root)) return {}
  return readDir(root)
}

function readDir(dir: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name)

    if (entry.isDirectory()) {
      // Sub-directory becomes a nested namespace keyed by its name,
      // with a kebab-to-camelCase conversion so the JS API stays
      // ergonomic (e.g. access-auth → accessAuth).
      const key = toCamel(entry.name)
      out[key] = readDir(fullPath)
      continue
    }

    if (!entry.name.endsWith(".json")) continue

    const parsed = JSON.parse(fs.readFileSync(fullPath, "utf-8"))
    const base = entry.name.replace(/\.json$/, "")

    if (base === "common" || base === "index") {
      // Merge at the current level — no extra namespace.
      Object.assign(out, parsed)
    } else {
      out[toCamel(base)] = parsed
    }
  }

  return out
}

function toCamel(name: string): string {
  return name.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase())
}
