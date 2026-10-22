import { MESSAGE_CATALOG } from "./i18n/catalogs"
import { detectBrowserLanguage, isSupportedLanguage, LANGUAGE_STORAGE_KEY } from "./i18n/languages"

type Failure = keyof (typeof import("../messages/en/common.json"))["apiErrors"]

// fetchApi also runs outside React hooks. Read the provider's current document
// language, with its stored/browser preference as a fallback.
export function apiFailure(key: Failure, params: Record<string, string | number> = {}): string {
  let preference = typeof document === "undefined" ? "" : document.documentElement?.lang
  if (!isSupportedLanguage(preference) && typeof window !== "undefined") {
    try { preference = window.localStorage.getItem(LANGUAGE_STORAGE_KEY) || "" } catch { /* private browsing */ }
  }
  const language = isSupportedLanguage(preference) ? preference : detectBrowserLanguage()
  const messages = MESSAGE_CATALOG[language].apiErrors
  const localized = messages && typeof messages === "object" ? (messages as Record<string, unknown>)[key] : undefined
  const fallback = (MESSAGE_CATALOG.en.apiErrors as Record<Failure, string>)[key]
  const template = typeof localized === "string" ? localized : fallback
  return template.replace(/\{(\w+)\}/g, (match, name) => params[name] === undefined ? match : String(params[name]))
}
