"use client"

import { useEffect } from "react"

/**
 * Updates `<html lang>` to the active locale after hydration. The
 * static root layout hard-codes lang="en" because next-intl's dynamic
 * locale lives inside [locale]/ where we can't own the <html> tag
 * anymore. Without this sync, screen readers and crawlers that respect
 * the `lang` attribute would see "en" on every page.
 */
export function LocaleHtmlSync({ locale }: { locale: string }) {
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale
    }
  }, [locale])
  return null
}
