"use client"

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import enMessages from "../../messages/en/common.json"
import deMessages from "../../messages/de/common.json"
import esMessages from "../../messages/es/common.json"
import frMessages from "../../messages/fr/common.json"
import itMessages from "../../messages/it/common.json"
import ptMessages from "../../messages/pt/common.json"
import skMessages from "../../messages/sk/common.json"
import svMessages from "../../messages/sv/common.json"
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  type LanguageCode,
  SUPPORTED_LANGUAGES,
  detectBrowserLanguage,
  isSupportedLanguage,
} from "./languages"

type MessageTree = Record<string, unknown>
type TranslationParams = Record<string, string | number>

const MESSAGE_CATALOG: Record<LanguageCode, MessageTree> = {
  en: enMessages as MessageTree,
  de: deMessages as MessageTree,
  es: esMessages as MessageTree,
  fr: frMessages as MessageTree,
  it: itMessages as MessageTree,
  pt: ptMessages as MessageTree,
  sk: skMessages as MessageTree,
  sv: svMessages as MessageTree,
}

interface I18nContextValue {
  language: LanguageCode
  setLanguage: (language: LanguageCode) => void
  t: (key: string, params?: TranslationParams) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function getInitialLanguage(): LanguageCode {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE

  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (isSupportedLanguage(stored)) return stored
  } catch {
    // localStorage may be unavailable in private browsing.
  }

  return detectBrowserLanguage()
}

function getMessage(messages: MessageTree, key: string): string | undefined {
  const value = key.split(".").reduce<unknown>((cursor, segment) => {
    if (!cursor || typeof cursor !== "object") return undefined
    return (cursor as Record<string, unknown>)[segment]
  }, messages)

  return typeof value === "string" ? value : undefined
}

function interpolate(template: string, params?: TranslationParams): string {
  if (!params) return template

  return template.replace(/\{(\w+)\}/g, (match, name) => {
    const value = params[name]
    return value === undefined ? match : String(value)
  })
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState<LanguageCode>(DEFAULT_LANGUAGE)
  const [isHydrated, setIsHydrated] = useState(false)

  useEffect(() => {
    setLanguageState(getInitialLanguage())
    setIsHydrated(true)
  }, [])

  useEffect(() => {
    if (!isHydrated) return

    document.documentElement.lang = language
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
    } catch {
      // Best-effort; the in-memory language still works for this session.
    }
  }, [isHydrated, language])

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === LANGUAGE_STORAGE_KEY && isSupportedLanguage(event.newValue)) {
        setLanguageState(event.newValue)
      }
    }

    window.addEventListener("storage", onStorage)
    return () => window.removeEventListener("storage", onStorage)
  }, [])

  const setLanguage = useCallback((nextLanguage: LanguageCode) => {
    setLanguageState(nextLanguage)
  }, [])

  const t = useCallback(
    (key: string, params?: TranslationParams) => {
      const localized = getMessage(MESSAGE_CATALOG[language], key)
      const fallback = getMessage(MESSAGE_CATALOG.en, key)
      return interpolate(localized ?? fallback ?? key, params)
    },
    [language],
  )

  const value = useMemo<I18nContextValue>(() => ({ language, setLanguage, t }), [language, setLanguage, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = useContext(I18nContext)
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider")
  }
  return context
}

export function useT() {
  return useI18n().t
}

export function getCountFormKey(language: LanguageCode, key: string, count: number): string {
  if (language !== "sk") return key

  const absoluteCount = Math.abs(count)
  const lastDigit = absoluteCount % 10
  const lastTwoDigits = absoluteCount % 100

  if (lastDigit === 1 && lastTwoDigits !== 11) return `${key}One`
  if (lastDigit >= 2 && lastDigit <= 4 && !(lastTwoDigits >= 12 && lastTwoDigits <= 14)) {
    return `${key}Few`
  }
  return `${key}Many`
}

export { SUPPORTED_LANGUAGES }
