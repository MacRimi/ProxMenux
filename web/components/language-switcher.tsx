"use client"

import { useLocale, useTranslations } from "next-intl"
import { useRouter, usePathname } from "@/i18n/navigation"
import { Languages } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu"
import { routing } from "@/i18n/routing"

/**
 * Language switcher dropdown for the navbar.
 *
 * Reads the active locale from next-intl and replaces it in the URL on
 * selection. The locale-aware `usePathname` and `useRouter` from
 * @/i18n/navigation strip the current `[locale]` prefix when reading
 * and re-add the chosen one when navigating, so the user stays on the
 * same logical page after switching language.
 */
export function LanguageSwitcher() {
  const t = useTranslations("language")
  const locale = useLocale()
  const router = useRouter()
  const pathname = usePathname()

  const labels: Record<string, string> = {
    en: t("en"),
    es: t("es"),
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-secondary transition-colors text-sm font-medium" aria-label={t("switcher")}>
        <Languages className="h-4 w-4" />
        <span className="uppercase">{locale}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {routing.locales.map((loc) => (
          <DropdownMenuItem
            key={loc}
            onSelect={() => router.replace(pathname, { locale: loc })}
            className={loc === locale ? "font-semibold" : ""}
          >
            {labels[loc] || loc}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
