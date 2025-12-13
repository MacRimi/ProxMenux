import type React from "react"
import DocSidebar from "@/components/DocSidebar"
import Footer from "@/components/footer"
import { DocNavigation } from "@/components/ui/doc-navigation"

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen bg-white text-gray-900">
      <div className="flex flex-col lg:flex-row flex-1 pt-16 lg:pt-0">
        <DocSidebar />
        <main className="flex-1 p-4 lg:p-6 pt-6 lg:pt-6 overflow-y-auto">
          <div className="max-w-3xl mx-auto" style={{ maxWidth: "980px" }}>
            {children}
            <DocNavigation />
          </div>
        </main>
      </div>
      <Footer />
    </div>
  )
}
