import enMessages from "../messages/en/common.json"
import skMessages from "../messages/sk/common.json"
import { detectBrowserLanguage, LANGUAGE_STORAGE_KEY } from "./i18n/languages"

type Failure = keyof typeof enMessages.apiErrors

// fetchApi also runs outside React hooks. Read the provider's current document
// language, with its stored/browser preference as a fallback.
export function apiFailure(key: Failure, params: Record<string, string | number> = {}): string {
  let language = typeof document === "undefined" ? "" : document.documentElement?.lang
  if (!language && typeof window !== "undefined") {
    try { language = window.localStorage.getItem(LANGUAGE_STORAGE_KEY) || "" } catch { /* private browsing */ }
  }
  language ||= detectBrowserLanguage()
  const messages = language === "sk" ? skMessages.apiErrors : enMessages.apiErrors
  return messages[key].replace(/\{(\w+)\}/g, (match, name) => params[name] === undefined ? match : String(params[name]))
}
