import type React from "react"
import DocSidebar from "@/components/DocSidebar"
import Footer from "@/components/footer"
import { DocNavigation } from "@/components/ui/doc-navigation"
import { DocBreadcrumb } from "@/components/DocBreadcrumb"
import { DocTableOfContents } from "@/components/DocTableOfContents"

/**
 * Docs layout — three-column shell matching the Hermes / Docusaurus
 * pattern the user asked for:
 *
 *   ┌─────────┬───────────────────────┬─────────┐
 *   │ Sidebar │ Breadcrumb + Article  │ ToC     │
 *   │ (fixed) │ (scrollable)          │ (sticky)│
 *   └─────────┴───────────────────────┴─────────┘
 *
 * - Sidebar: 18 rem, fixed left on lg+, slide-down drawer on mobile.
 * - Main: max width capped at ~980 px for comfortable line length.
 * - ToC: 14 rem, sticky right rail, only shown on xl+ where there is
 *   enough horizontal room to display it without crowding the article.
 */
export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen bg-white text-gray-900">
      <DocSidebar />
      <div className="flex flex-col flex-1 pt-16 lg:pt-0 lg:pl-72">
        <div className="flex flex-1">
          <main className="flex-1 min-w-0 p-4 lg:p-6 pt-6 lg:pt-6">
            <div className="max-w-3xl mx-auto" style={{ maxWidth: "980px" }}>
              <DocBreadcrumb />
              {children}
              <DocNavigation />
            </div>
          </main>
          <aside className="hidden xl:block w-56 shrink-0 py-6 pr-6">
            <DocTableOfContents />
          </aside>
        </div>
        <Footer />
      </div>
    </div>
  )
}
