"use client"

import NextLink from "next/link"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { Book, GitBranch, FileText, Github, Menu, Rss } from "lucide-react"
import { useState } from "react"
import { useLocale, useTranslations } from "next-intl"
import { SearchDialog } from "./search-dialog"
import { LanguageSwitcher } from "./language-switcher"

export default function Navbar() {
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const t = useTranslations("nav")
  const locale = useLocale()
  // English keeps the canonical root /rss.xml; other locales use the
  // per-locale feed at /{locale}/rss.xml (mirrors components/rss-link.tsx).
  const rssUrl =
    locale === "en"
      ? "https://proxmenux.com/rss.xml"
      : `https://proxmenux.com/${locale}/rss.xml`

  // Internal hrefs use the locale-aware Link from @/i18n/navigation,
  // so the active /[locale]/ segment is added automatically. External
  // URLs (GitHub) stay as `next/link` via NextLink to avoid the
  // locale prefix. Labels read from messages/<locale>/common.json
  // under the `nav.*` namespace.
  const navItems = [
    { href: "/docs/introduction", icon: <Book className="h-4 w-4" />, label: t("documentation"), external: false },
    { href: "/changelog", icon: <FileText className="h-4 w-4" />, label: t("changelog"), external: false },
    { href: "/guides", icon: <GitBranch className="h-4 w-4" />, label: t("guides"), external: false },
    { href: "https://github.com/MacRimi/ProxMenux", icon: <Github className="h-4 w-4" />, label: t("github"), external: true },
  ]

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-background/95 backdrop-blur border-b border-border/40">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center space-x-2">
            <Image
              src="https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo.png"
              alt="ProxMenux Logo"
              width={32}
              height={32}
              className="w-8 h-8"
              unoptimized
            />
            <span className="text-xl font-bold">ProxMenux</span>
          </Link>

          {/* Right side — search (responsive) + desktop nav + mobile menu button */}
          <div className="flex items-center gap-3 lg:gap-6">
            {/* Search — always visible: icon only on mobile/tablet, full button on lg+ */}
            <SearchDialog />

            {/* Desktop menu — only on lg+ to avoid overlap with the logo on tablet portrait */}
            <nav className="hidden lg:flex items-center space-x-6 text-sm font-medium">
              {navItems.map((item) =>
                item.external ? (
                  <NextLink
                    key={item.href}
                    href={item.href}
                    className="flex items-center space-x-2 transition-colors hover:text-primary"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NextLink>
                ) : (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex items-center space-x-2 transition-colors hover:text-primary"
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </Link>
                ),
              )}

              {/* RSS Feed Link */}
              <NextLink
                href={rssUrl}
                className="flex items-center space-x-2 transition-colors hover:text-primary text-orange-600 hover:text-orange-700"
                target="_blank"
                rel="noopener noreferrer"
                title={t("rssTitle")}
              >
                <Rss className="h-4 w-4" />
                <span>{t("rss")}</span>
              </NextLink>

              <LanguageSwitcher />
            </nav>

            {/* Mobile + tablet menu button — visible until lg breakpoint */}
            <button
              className="lg:hidden p-2"
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              aria-label={t("menuOpen")}
            >
              <Menu className="h-6 w-6" />
            </button>
          </div>
        </div>

        {/* Mobile + tablet menu */}
        {isMenuOpen && (
          <nav className="lg:hidden py-4">
            {navItems.map((item) =>
              item.external ? (
                <NextLink
                  key={item.href}
                  href={item.href}
                  className="flex items-center space-x-2 py-2 transition-colors hover:text-primary"
                  onClick={() => setIsMenuOpen(false)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {item.icon}
                  <span>{item.label}</span>
                </NextLink>
              ) : (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex items-center space-x-2 py-2 transition-colors hover:text-primary"
                  onClick={() => setIsMenuOpen(false)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </Link>
              ),
            )}

            {/* RSS Feed Link - Mobile */}
            <NextLink
              href={rssUrl}
              className="flex items-center space-x-2 py-2 transition-colors hover:text-primary text-orange-600 hover:text-orange-700"
              onClick={() => setIsMenuOpen(false)}
              target="_blank"
              rel="noopener noreferrer"
              title={t("rssTitle")}
            >
              <Rss className="h-4 w-4" />
              <span>{t("rss")}</span>
            </NextLink>

            <div className="py-2">
              <LanguageSwitcher />
            </div>
          </nav>
        )}
      </div>
    </header>
  )
}
