import { hasLocale } from "next-intl"
import { getRequestConfig } from "next-intl/server"
import { routing } from "./routing"
import { loadMessages } from "./loadMessages"

/**
 * Per-request i18n config consumed by next-intl on every page render.
 *
 * Loads the entire translation tree for the active locale by walking
 * `messages/<locale>/` (see loadMessages.ts). Conventions:
 *
 *   - `common.json` / `index.json`         → keys merged at root
 *   - `<name>.json`                        → namespace `<name>.*`
 *   - sub-directories                      → nested namespace
 *
 * Missing translations transparently fall back to English. When a
 * translator hasn't finished a section yet the user sees the English
 * text instead of a broken `MISSING_MESSAGE` placeholder.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale

  const enMessages = loadMessages("en")
  const localeMessages = locale === "en" ? {} : loadMessages(locale)

  return {
    locale,
    messages: deepMerge(enMessages, localeMessages),
  }
})

/**
 * Deep-merge two message trees so the locale's translations override
 * the English defaults while still falling back to English for any
 * key the translator hasn't filled in yet.
 */
function deepMerge(
  base: Record<string, unknown>,
  override: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base }
  for (const [k, v] of Object.entries(override)) {
    if (
      v &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      typeof out[k] === "object" &&
      out[k] !== null &&
      !Array.isArray(out[k])
    ) {
      out[k] = deepMerge(
        out[k] as Record<string, unknown>,
        v as Record<string, unknown>,
      )
    } else {
      out[k] = v
    }
  }
  return out
}
