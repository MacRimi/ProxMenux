export const LANGUAGE_STORAGE_KEY = "proxmenux-ui-language"
export const DEFAULT_LANGUAGE = "en"

export type LanguageCode = "en" | "es" | "fr" | "de" | "it" | "pt" | "sk"

export type LanguageStatus = "complete" | "partial" | "needs-translation"

export interface SupportedLanguage {
  code: LanguageCode
  englishName: string
  nativeName: string
  status: LanguageStatus
}

export const SUPPORTED_LANGUAGES: SupportedLanguage[] = [
  { code: "en", englishName: "English", nativeName: "English", status: "complete" },
  { code: "sk", englishName: "Slovak", nativeName: "Slovenčina", status: "complete" },
  { code: "es", englishName: "Spanish", nativeName: "Español", status: "needs-translation" },
  { code: "fr", englishName: "French", nativeName: "Français", status: "needs-translation" },
  { code: "de", englishName: "German", nativeName: "Deutsch", status: "needs-translation" },
  { code: "it", englishName: "Italian", nativeName: "Italiano", status: "needs-translation" },
  { code: "pt", englishName: "Portuguese", nativeName: "Português", status: "needs-translation" },
]

export function isSupportedLanguage(value: string | null | undefined): value is LanguageCode {
  return SUPPORTED_LANGUAGES.some((language) => language.code === value)
}

export function detectBrowserLanguage(): LanguageCode {
  if (typeof navigator === "undefined") return DEFAULT_LANGUAGE

  const candidates = [navigator.language, ...(navigator.languages || [])]
  for (const candidate of candidates) {
    const code = candidate?.split("-")[0]?.toLowerCase()
    if (isSupportedLanguage(code)) return code
  }

  return DEFAULT_LANGUAGE
}
