"use client"

import { useEffect } from "react"
import { usePathname, useSearchParams } from "next/navigation"

declare global {
  interface Window {
    PagefindHighlight?: new (options: { highlightParam?: string; addStyles?: boolean }) => unknown
  }
}

/*
  Pagefind term highlighter.

  pagefind-highlight.js only attaches the `PagefindHighlight` class to window — it does
  NOT auto-run. We instantiate it here on every route change so that:
    1. Initial page load: runs after the script loads.
    2. SPA navigation from search results (router.push from search-dialog.tsx): re-runs
       so highlights apply on the new page even though the page wasn't fully reloaded.

  We pass `highlightParam: "pagefind-search"` to match what the search dialog appends.
*/
export function PagefindHighlighter() {
  const pathname = usePathname()
  const searchParams = useSearchParams()

  useEffect(() => {
    if (!searchParams?.get("pagefind-search")) return

    const run = () => {
      if (typeof window.PagefindHighlight !== "function") return false
      try {
        new window.PagefindHighlight({ highlightParam: "pagefind-search" })
      } catch {
        // Highlighter constructor throws if mark.js can't find any text nodes — harmless.
      }
      return true
    }

    if (run()) return

    // Script may not have loaded yet on first paint; poll briefly.
    const id = window.setInterval(() => {
      if (run()) window.clearInterval(id)
    }, 100)
    const timeout = window.setTimeout(() => window.clearInterval(id), 5000)
    return () => {
      window.clearInterval(id)
      window.clearTimeout(timeout)
    }
  }, [pathname, searchParams])

  return null
}
