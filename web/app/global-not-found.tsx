import "./globals.css"
import { Inter } from "next/font/google"
import type { Metadata } from "next"
import { routing } from "@/i18n/routing"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Page not found | ProxMenux",
}

// Rendered for URLs that match no route. The root layout lives under
// app/[locale], so there is no single layout to inherit and this file owns the
// whole document. The export serves it as 404.html for every broken URL,
// whatever its locale, hence the English copy.
export default function GlobalNotFound() {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-background text-foreground antialiased`}>
        <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
          <p className="text-6xl font-extrabold">404</p>
          <h1 className="text-xl font-semibold">This page could not be found.</h1>
          <a href={`/${routing.defaultLocale}/`} className="text-blue-400 underline hover:text-blue-300">
            Go to the ProxMenux home page
          </a>
        </main>
      </body>
    </html>
  )
}
