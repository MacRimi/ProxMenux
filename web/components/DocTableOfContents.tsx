"use client"

import { useEffect, useState } from "react"
import { usePathname } from "next/navigation"
import { useTranslations } from "next-intl"

type Heading = { id: string; text: string; level: 2 | 3 }

/**
 * Right-rail table of contents for docs pages.
 *
 * On mount it walks every <h2> and <h3> inside `<main>` (the docs
 * container), assigns each one an `id` derived from its text if it
 * doesn't already have one, and renders a sticky list of anchors.
 *
 * Why client-side and not server-rendered? Most docs pages emit
 * headings as plain JSX without ids — extracting them at build time
 * would require either touching all ~107 pages or a custom MDX
 * pipeline. A 15-line useEffect avoids both.
 *
 * Scroll-spy: an IntersectionObserver highlights the entry whose
 * heading is currently in the upper half of the viewport, so the user
 * can see where they are as they scroll.
 *
 * Only renders on xl+ screens (the layout reserves the right gutter
 * there); on smaller viewports the ToC stays hidden so the article
 * keeps full width.
 */
export function DocTableOfContents() {
  const pathname = usePathname()
  const t = useTranslations("tocPanel")
  const [headings, setHeadings] = useState<Heading[]>([])
  const [activeId, setActiveId] = useState<string>("")

  // Re-scan whenever the route changes (so navigating between docs
  // pages refreshes the ToC).
  useEffect(() => {
    const main = document.querySelector("main")
    if (!main) {
      setHeadings([])
      return
    }
    const nodes = Array.from(main.querySelectorAll("h2, h3")) as HTMLHeadingElement[]
    const used = new Set<string>()
    const collected: Heading[] = nodes
      .map((node) => {
        const text = (node.textContent || "").trim()
        if (!text) return null
        // Always dedupe: if a heading carries an explicit id that already
        // appeared (e.g. a card <h3>VM</h3> auto-slugged to "vm" before a
        // <h2 id="vm"> later in the page), append -2, -3, ... so React
        // keys stay unique. The scroll-anchor still works for the first
        // occurrence; subsequent ones get their own anchor.
        let base = node.id || slugify(text)
        let id = base
        let n = 1
        while (used.has(id)) {
          n += 1
          id = `${base}-${n}`
        }
        if (!node.id || node.id !== id) {
          node.id = id
        }
        used.add(id)
        return { id, text, level: node.tagName === "H3" ? 3 : 2 } as Heading
      })
      .filter((h): h is Heading => h !== null)
    setHeadings(collected)
  }, [pathname])

  // Scroll-spy: highlight the heading currently in the upper half of
  // the viewport. Using rootMargin pushes the trigger zone toward the
  // top so the active entry changes as you scroll, not only when the
  // heading is dead-centre.
  useEffect(() => {
    if (headings.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length > 0) {
          // First visible entry from the top of the viewport.
          visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
          setActiveId(visible[0].target.id)
        }
      },
      { rootMargin: "-80px 0px -70% 0px", threshold: 0 },
    )
    headings.forEach((h) => {
      const el = document.getElementById(h.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [headings])

  if (headings.length === 0) return null

  return (
    <nav
      aria-label={t("onThisPage")}
      className="text-sm sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto pl-4"
    >
      <p className="font-semibold text-gray-900 mb-3 uppercase tracking-wide text-xs">{t("onThisPage")}</p>
      <ul className="space-y-1.5 border-l border-gray-200">
        {headings.map((h) => (
          <li key={h.id} className={h.level === 3 ? "ml-3" : ""}>
            <a
              href={`#${h.id}`}
              className={`-ml-px block border-l-2 pl-3 py-0.5 transition-colors ${
                activeId === h.id
                  ? "border-blue-500 text-blue-600 font-medium"
                  : "border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300"
              }`}
            >
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 80)
}
