"use client"

// Use the locale-aware Link + usePathname from next-intl. With the
// plain `next/link` and `next/navigation` imports the hrefs were
// emitted without a locale (404s) AND the active-page detection
// failed because `pathname` carried the `/en/` prefix while sidebar
// items don't, so findIndex always returned -1 → no Previous/Next
// buttons. See app/[locale]/docs/layout.tsx for the wider context.
import { Link, usePathname } from "@/i18n/navigation"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { useTranslations } from "next-intl"
import { useEffect, useState } from "react"
import { sidebarItems } from "@/components/DocSidebar"

interface DocNavigationProps {
  className?: string
}

interface SubMenuItem {
  title: string
  i18nKey?: string
  href: string
  submenu?: SubMenuItem[]
}

interface FlatPage {
  title: string
  i18nKey?: string
  href: string
  section?: string
  sectionI18nKey?: string
}

function walkSubmenu(
  items: SubMenuItem[],
  section: string,
  sectionI18nKey: string | undefined,
  out: FlatPage[],
) {
  items.forEach((sub) => {
    out.push({
      title: sub.title,
      i18nKey: sub.i18nKey,
      href: sub.href,
      section,
      sectionI18nKey,
    })
    if (sub.submenu && sub.submenu.length > 0) {
      walkSubmenu(sub.submenu, section, sectionI18nKey, out)
    }
  })
}

export function DocNavigation({ className }: DocNavigationProps) {
  const pathname = usePathname()
  const tNav = useTranslations("docNav")
  const tSidebar = useTranslations("docSidebar")

  // Capture the URL hash (`#host`, `#lxc-net`, …) on the client so we
  // can disambiguate Previous/Next when a single doc page hosts several
  // sidebar entries via in-page anchors (Storage Share Manager is the
  // canonical case: /docs/storage-share + /docs/storage-share#host +
  // /docs/storage-share#lxc-net are three distinct sidebar items but a
  // single physical page; usePathname() returns the same string for
  // all three because the fragment is not part of the path).
  //
  // SSR can't see the hash, so we hydrate with an empty string and
  // refresh on mount + on hashchange. The brief render before
  // hydration just shows the navigation as if the user were at the
  // parent page — same behaviour as before this fix, so no regression.
  const [hash, setHash] = useState("")
  useEffect(() => {
    const sync = () => setHash(window.location.hash || "")
    sync()
    window.addEventListener("hashchange", sync)
    return () => window.removeEventListener("hashchange", sync)
  }, [])

  const tItem = (i18nKey: string | undefined, fallback: string) => {
    if (!i18nKey) return fallback
    try {
      return tSidebar(`items.${i18nKey}`)
    } catch {
      return fallback
    }
  }

  const flattenSidebarItems = (): FlatPage[] => {
    const flatItems: FlatPage[] = []

    sidebarItems.forEach((item) => {
      if (item.href) {
        flatItems.push({ title: item.title, i18nKey: item.i18nKey, href: item.href })
      }

      if (item.submenu) {
        walkSubmenu(item.submenu as SubMenuItem[], item.title, item.i18nKey, flatItems)
      }
    })

    return flatItems
  }

  // Dedupe consecutive entries with the same href. Several sidebar
  // sections (Post-Install, GPUs, Create VM, Disk Manager, …) have a
  // parent whose href equals its first child's "Overview" href, so the
  // flat sequence contains the same page twice in a row. Without dedup,
  // Previous/Next on the parent would point to itself.
  const rawPages = flattenSidebarItems()
  const allPages: FlatPage[] = []
  for (const p of rawPages) {
    if (allPages.length > 0 && allPages[allPages.length - 1].href === p.href) continue
    allPages.push(p)
  }

  // Normalize trailing slashes before comparing. Next.js is configured
  // with `trailingSlash: true` (so GitHub Pages serves `/foo/` as
  // `foo/index.html`), which means usePathname() returns
  // `/docs/.../page/` while sidebarItems declares hrefs as
  // `/docs/.../page` (no trailing slash). Without this normalization
  // findIndex always returned -1 → prevPage was null and nextPage was
  // allPages[0] (Introduction) on every page, so the bottom Previous/Next
  // bar showed "Next: Introduction" everywhere regardless of the route.
  const stripTrailingSlash = (s: string) => (s !== "/" ? s.replace(/\/+$/, "") : s)
  const normalizedPathname = stripTrailingSlash(pathname)

  // Match attempt order:
  //   1. pathname + hash (e.g. /docs/storage-share#host)  — exact match
  //      against sidebar items that intentionally point to an in-page
  //      anchor as the "current location" for navigation purposes.
  //   2. pathname alone — the regular case, no anchor in the URL.
  //
  // Without step 1, every anchor visit collapsed to the parent page
  // and Next/Previous walked from there — so on /docs/storage-share#host
  // the bottom bar offered the same #host as Next (no movement) and on
  // /docs/storage-share/lxc-mount-points/ Next pointed back at #host
  // because the entire flat list got indexed from position 0.
  const effectivePath = normalizedPathname + hash
  let currentPageIndex = -1
  if (hash) {
    currentPageIndex = allPages.findIndex(
      (page) => stripTrailingSlash(page.href) === effectivePath,
    )
  }
  if (currentPageIndex === -1) {
    currentPageIndex = allPages.findIndex(
      (page) => stripTrailingSlash(page.href) === normalizedPathname,
    )
  }

  const prevPage = currentPageIndex > 0 ? allPages[currentPageIndex - 1] : null
  const nextPage = currentPageIndex < allPages.length - 1 ? allPages[currentPageIndex + 1] : null

  if (!prevPage && !nextPage) return null

  return (
    <div className={`mt-16 ${className || ""}`}>

      <div className="w-full h-0.5 bg-gray-300 mb-8"></div>

      <div className="flex flex-col sm:flex-row justify-between gap-4">
        {prevPage ? (
          <Link
            href={prevPage.href}
            className="flex items-center p-4 border-2 border-gray-300 rounded-lg hover:border-blue-500 hover:bg-blue-50 transition-all duration-200 group w-full sm:w-[calc(50%-0.5rem)] sm:max-w-[calc(50%-0.5rem)]"
          >
            <ChevronLeft className="h-5 w-5 mr-2 text-gray-500 group-hover:text-blue-500 flex-shrink-0" />
            <div className="min-w-0 overflow-hidden">
              <div className="text-sm text-gray-500 group-hover:text-blue-600 truncate">
                {prevPage.section ? `${tItem(prevPage.sectionI18nKey, prevPage.section)}: ` : ""}
                {tNav("previous")}
              </div>
              <div className="font-medium group-hover:text-blue-700 truncate">
                {tItem(prevPage.i18nKey, prevPage.title)}
              </div>
            </div>
          </Link>
        ) : (
          <div className="hidden sm:block sm:w-[calc(50%-0.5rem)]"></div>
        )}

        {nextPage ? (
          <Link
            href={nextPage.href}
            className="flex items-center justify-end p-4 border-2 border-gray-300 rounded-lg hover:border-blue-500 hover:bg-blue-50 transition-all duration-200 group sm:text-right w-full sm:w-[calc(50%-0.5rem)] sm:max-w-[calc(50%-0.5rem)] ml-auto"
          >
            <div className="min-w-0 overflow-hidden">
              <div className="text-sm text-gray-500 group-hover:text-blue-600 truncate">
                {nextPage.section ? `${tItem(nextPage.sectionI18nKey, nextPage.section)}: ` : ""}
                {tNav("next")}
              </div>
              <div className="font-medium group-hover:text-blue-700 truncate">
                {tItem(nextPage.i18nKey, nextPage.title)}
              </div>
            </div>
            <ChevronRight className="h-5 w-5 ml-2 text-gray-500 group-hover:text-blue-500 flex-shrink-0" />
          </Link>
        ) : (
          <div className="hidden sm:block sm:w-[calc(50%-0.5rem)]"></div>
        )}
      </div>
    </div>
  )
}
