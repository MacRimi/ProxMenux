"use client"

import { usePathname } from "@/i18n/navigation"
import { Link } from "@/i18n/navigation"
import { Home, ChevronRight } from "lucide-react"

/**
 * Breadcrumb shown above the docs content.
 *
 * Reads the current pathname (after the locale prefix has been
 * stripped by next-intl) and turns each segment into a clickable
 * crumb. Segments are humanized — `access-auth` → "Access Auth".
 * Intermediate links go to their parent docs section; the last
 * segment is the current page and renders as plain text.
 *
 * Skips itself entirely on the docs root (`/docs`) where the
 * breadcrumb would just be "Docs" with nothing meaningful before it.
 */
export function DocBreadcrumb() {
  const pathname = usePathname()
  const segments = pathname.split("/").filter(Boolean)

  // Need at least `docs/<section>` to show something useful.
  if (segments.length < 2 || segments[0] !== "docs") return null

  const crumbs = segments.map((seg, i) => {
    const href = "/" + segments.slice(0, i + 1).join("/")
    const label = humanize(seg)
    const isLast = i === segments.length - 1
    return { href, label, isLast }
  })

  return (
    <nav aria-label="Breadcrumb" className="mb-6 text-sm">
      <ol className="flex items-center flex-wrap gap-1 text-gray-500">
        <li className="flex items-center">
          <Link href="/" className="flex items-center hover:text-gray-900 transition-colors" aria-label="Home">
            <Home className="h-4 w-4" />
          </Link>
        </li>
        {crumbs.map((c) => (
          <li key={c.href} className="flex items-center gap-1">
            <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
            {c.isLast ? (
              <span className="text-gray-900 font-medium">{c.label}</span>
            ) : (
              <Link href={c.href} className="hover:text-gray-900 transition-colors">
                {c.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}

function humanize(slug: string): string {
  return slug
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
