import "../globals.css"
import { Inter } from "next/font/google"
import type React from "react"

const inter = Inter({ subsets: ["latin"] })

// Root layout for the bare `/` redirect only. The site's root layout lives in
// app/[locale], which makes `locale` a root parameter (see i18n/request.ts).
// It keeps the site's dark background so the redirect does not flash white.
export default function RootRedirectLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-background text-foreground antialiased`}>{children}</body>
    </html>
  )
}
