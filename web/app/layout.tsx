import "./globals.css"
import { Inter } from "next/font/google"
import type React from "react"

const inter = Inter({ subsets: ["latin"] })

/**
 * Minimal root layout — the localized layout under [locale]/ does the
 * real work (provider, navbar, etc.) but cannot own <html>/<body> tags
 * because Next.js requires those at the root level. Lang is set to the
 * default locale here and refined client-side from inside the locale
 * layout so the page still renders correctly with JS disabled (defaults
 * to English) and switches to the active locale once hydrated.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-background text-foreground antialiased`}>
        {children}
      </body>
    </html>
  )
}
