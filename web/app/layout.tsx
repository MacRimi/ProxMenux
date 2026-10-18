import "./globals.css"
import { Inter } from "next/font/google"
import type React from "react"

const inter = Inter({ subsets: ["latin"] })

/**
 * Minimal root layout — the localized layout under [locale]/ does the
 * real work (provider, navbar, etc.) but cannot own <html>/<body> tags
 * because Next.js requires those at the root level. Lang is set to the
 * default locale here; scripts/localize-export.mjs sets the exported
 * document's language before search indexing, and LocaleHtmlSync keeps
 * it in sync during client navigation. The root-only hydration suppression
 * allows that intentional lang attribute change in the static export.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${inter.className} bg-background text-foreground antialiased`}>
        {children}
      </body>
    </html>
  )
}
