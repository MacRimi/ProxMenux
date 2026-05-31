"use client"

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useRouter } from "next/navigation"
import { Search, X } from "lucide-react"
import { cn } from "@/lib/utils"

declare global {
  interface Window {
    PagefindUI?: new (options: Record<string, unknown>) => unknown
  }
}

export function SearchDialog() {
  const [isOpen, setIsOpen] = useState(false)
  const [isReady, setIsReady] = useState(false)
  const [loadError, setLoadError] = useState(false)
  // Track when the component has hydrated so we know it's safe to use document.body
  // for the portal target — avoids React hydration mismatch warnings.
  const [mounted, setMounted] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const router = useRouter()

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setIsOpen((v) => !v)
      }
      if (e.key === "Escape" && isOpen) {
        setIsOpen(false)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) {
      // Reset readiness on close so the next open shows the loading state
      // until Pagefind UI mounts again into the new container ref.
      setIsReady(false)
      return
    }

    // Inject Pagefind UI CSS once across the page lifetime.
    const cssId = "pagefind-ui-css"
    if (!document.getElementById(cssId)) {
      const link = document.createElement("link")
      link.id = cssId
      link.rel = "stylesheet"
      link.href = "/pagefind/pagefind-ui.css"
      document.head.appendChild(link)
    }

    const init = () => {
      if (!containerRef.current) return
      if (typeof window.PagefindUI !== "function") {
        setLoadError(true)
        return
      }
      // Wipe any prior UI instance — the container is a fresh DOM node every open,
      // but this also handles the unlikely case of a partial mount.
      containerRef.current.innerHTML = ""
      new window.PagefindUI({
        element: containerRef.current,
        showSubResults: true,
        showImages: false,
        resetStyles: false,
        autofocus: true,
        // Append ?pagefind-search=<term> to result URLs so the destination page can highlight
        // the matched terms via /pagefind/pagefind-highlight.js (loaded in the root layout).
        highlightParam: "pagefind-search",
        // Note: we intentionally do NOT use Pagefind's `processResult` to rewrite URLs.
        // Pagefind UI versions differ in which field they bind to the rendered <a href>
        // (some use `meta.url`, some `url`, some keep raw_url internally), and mutating
        // the result object can also break sub-result rendering. Instead, we intercept
        // the click event below and clean the URL at click time — see onClickCapture
        // on the result container.
        translations: {
          placeholder: "Search documentation…",
          clear_search: "Clear",
          load_more: "Load more results",
          search_label: "Search this site",
          filters_label: "Filters",
          zero_results: "No results for [SEARCH_TERM]",
          many_results: "[COUNT] results for [SEARCH_TERM]",
          one_result: "[COUNT] result for [SEARCH_TERM]",
          alt_search: "No results for [SEARCH_TERM]. Showing results for [DIFFERENT_TERM] instead",
          search_suggestion: "No results for [SEARCH_TERM]. Try one of the following searches:",
          searching: "Searching for [SEARCH_TERM]…",
        },
      })
      setIsReady(true)
    }

    // If Pagefind UI is already loaded (we've opened the dialog before in this session),
    // re-init directly into the new container ref.
    if (typeof window.PagefindUI === "function") {
      init()
      return
    }

    // First time: load the script and init on load.
    const scriptId = "pagefind-ui-js"
    let script = document.getElementById(scriptId) as HTMLScriptElement | null
    if (!script) {
      script = document.createElement("script")
      script.id = scriptId
      script.src = "/pagefind/pagefind-ui.js"
      script.defer = true
      script.onerror = () => setLoadError(true)
      document.head.appendChild(script)
    }
    script.addEventListener("load", init, { once: true })
  }, [isOpen])

  return (
    <>
      {/* Trigger button — icon only on mobile/tablet, full button with text + kbd on lg+ */}
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className={cn(
          "flex items-center rounded-md text-zinc-400 transition-colors hover:text-zinc-100",
          // Mobile/tablet: just the icon, no border/bg
          "p-2 lg:p-0",
          // Desktop (lg+): full button with grey background for contrast against the dark navbar
          "lg:gap-2 lg:rounded-md lg:border lg:border-zinc-700 lg:bg-zinc-800 lg:px-3 lg:py-1.5 lg:text-sm lg:hover:bg-zinc-700 lg:hover:border-zinc-600",
        )}
        aria-label="Search documentation"
      >
        <Search className="h-5 w-5 lg:h-4 lg:w-4" />
        <span className="hidden lg:inline">Search…</span>
        <kbd className="hidden lg:inline-flex items-center gap-0.5 rounded border border-zinc-600 bg-zinc-900 px-1.5 py-0.5 text-[10px] font-mono text-zinc-300">
          <span className="text-xs">⌘</span>K
        </kbd>
      </button>

      {/*
        Render the modal in a portal to document.body so it escapes the Navbar's
        fixed/z-50 stacking context. Otherwise z-[1000] is bounded by the parent
        context and the mobile "Documentation" bar (also z-50, later in the DOM)
        paints on top, hiding the close button.
      */}
      {mounted && isOpen && createPortal(
        <div
          className="fixed inset-0 z-[1000] flex items-start justify-center bg-black/60 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsOpen(false)
          }}
          role="dialog"
          aria-modal="true"
          aria-label="Search"
        >
          <div
            className={cn(
              "relative mt-4 sm:mt-16 w-full max-w-2xl rounded-lg border border-gray-200 bg-white shadow-2xl mx-4",
              "max-h-[90vh] sm:max-h-[80vh] overflow-hidden flex flex-col",
            )}
          >
            {/* Header bar — close button. Esc hint is desktop-only (no keyboard on mobile). */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50">
              <span className="hidden sm:inline text-xs text-gray-500">
                Press <kbd className="rounded border border-gray-300 bg-white px-1 py-0.5 text-[10px] font-mono">Esc</kbd> to close
              </span>
              {/* Spacer so the X stays right-aligned even when the Esc hint is hidden */}
              <span className="sm:hidden" aria-hidden />
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded p-1 text-gray-500 hover:bg-gray-200 hover:text-gray-900 transition-colors"
                aria-label="Close search"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto flex-1">
              {loadError ? (
                <div className="p-6 text-center text-sm text-gray-600">
                  <p className="font-medium text-gray-900 mb-2">Search index not available</p>
                  <p>
                    Search is generated during the production build. Run{" "}
                    <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">npm run build</code> to
                    generate the index locally, or wait for the next deploy.
                  </p>
                </div>
              ) : (
                <>
                  {!isReady && (
                    <div className="p-6 text-center text-sm text-gray-500">Loading search…</div>
                  )}
                  {/*
                    Click interception: Pagefind indexes the static export (.html files), so
                    result links carry hrefs like "/docs/foo.html?pagefind-search=term". In dev
                    mode and on hosts that don't serve .html, those URLs 404. We intercept the
                    click here, strip .html / /index.html, and route via Next.js for SPA nav.
                    Capture phase runs before any Pagefind handlers; modifier-key clicks fall
                    through to the browser so cmd/ctrl-click still opens in a new tab.
                  */}
                  <div
                    ref={containerRef}
                    className="pagefind-root"
                    onClickCapture={(e) => {
                      const target = e.target as HTMLElement
                      const anchor = target.closest("a") as HTMLAnchorElement | null
                      if (!anchor) return
                      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
                      const raw = anchor.getAttribute("href")
                      if (!raw || /^(https?:)?\/\//i.test(raw) || raw.startsWith("mailto:")) return
                      const cleaned = raw
                        .replace(/\/index\.html(?=[?#]|$)/g, "/")
                        .replace(/\.html(?=[?#]|$)/g, "")
                      e.preventDefault()
                      setIsOpen(false)
                      router.push(cleaned)
                    }}
                  />
                </>
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
