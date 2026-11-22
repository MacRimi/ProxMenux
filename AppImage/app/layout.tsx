import type React from "react"
import type { Metadata, Viewport } from "next"
import { GeistSans } from "geist/font/sans"
import { GeistMono } from "geist/font/mono"
import { ThemeProvider } from "../components/theme-provider"
import { PwaRegister } from "../components/pwa-register"
import { PwaInstallPrompt } from "../components/pwa-install-prompt"
import { I18nProvider } from "../lib/i18n/provider"
import { Suspense } from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import "./globals.css"

// iOS saves the home screen icon in a download of its own, which does not
// take the certificate exception granted to the page (Proxmox's own
// certificate over HTTPS). The icon travels inside the page instead.
const appleTouchIcon = `data:image/png;base64,${readFileSync(
  path.join(process.cwd(), "public", "apple-touch-icon.png"),
).toString("base64")}`

export const metadata: Metadata = {
  title: "ProxMenux Monitor",
  description: "Proxmox System Dashboard and Monitor",
  generator: "v0.app",
  manifest: "/manifest.json",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon.png", type: "image/png", sizes: "32x32" },
    ],
    shortcut: "/favicon.ico",
    apple: [{ url: appleTouchIcon, sizes: "180x180", type: "image/png" }],
  },
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#2b2f36" },
  ],
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${GeistSans.variable} ${GeistMono.variable} antialiased bg-background text-foreground`}>
        <Suspense fallback={null}>
          <I18nProvider>
            <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
              {children}
            </ThemeProvider>
            <PwaInstallPrompt />
          </I18nProvider>
        </Suspense>
        <PwaRegister />
      </body>
    </html>
  )
}
