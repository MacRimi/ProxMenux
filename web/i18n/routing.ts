import { defineRouting } from "next-intl/routing"

/**
 * i18n routing configuration for the ProxMenux web docs.
 *
 * - English is the default locale: the docs grew up in English and the
 *   homelab/Proxmox audience is primarily international. New locales
 *   land progressively; missing translations should fall back to the
 *   English message rather than 404.
 *
 * - `localePrefix: "always"` is required for `output: "export"` static
 *   builds and gives cleaner SEO: every URL carries an explicit locale
 *   segment (`/en/docs/...`, `/es/docs/...`) so hreflang and Google's
 *   per-language indexing work without ambiguity.
 *
 * - When adding a new locale here, also create
 *   `messages/<locale>/common.json` (mandatory) and start
 *   page-specific files under `messages/<locale>/docs/...`. See
 *   `CONTRIBUTING-TRANSLATIONS.md`.
 */
export const routing = defineRouting({
  locales: ["en", "es"],
  defaultLocale: "en",
  localePrefix: "always",
})

export type Locale = (typeof routing.locales)[number]
