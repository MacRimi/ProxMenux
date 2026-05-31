import { Suspense } from "react"
import Navbar from "@/components/navbar"
import MouseMoveEffect from "@/components/mouse-move-effect"
import { PagefindHighlighter } from "@/components/pagefind-highlighter"
import { LocaleHtmlSync } from "@/components/locale-html-sync"
import type React from "react"
import { notFound } from "next/navigation"
import { NextIntlClientProvider, hasLocale } from "next-intl"
import { setRequestLocale } from "next-intl/server"
import { routing } from "@/i18n/routing"

/**
 * Tell Next.js which locales to pre-render under [locale]. Required
 * for `output: "export"` — without this, the static build can't enumerate
 * the dynamic segment and falls back to ISR (which static export doesn't
 * support).
 */
export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

/**
 * Force every nested page to render statically. Without this Next.js
 * treats pages that don't explicitly call `setRequestLocale()` as
 * dynamic (because next-intl's `getRequestConfig` reads
 * `requestLocale` which internally falls back to `headers()`),
 * breaking the `output: "export"` build with
 * `StaticGenBailoutError: dynamic = "error" couldn't be rendered
 * statically because it used 'headers'`. Marking force-static here
 * spares us from adding `setRequestLocale(locale)` to all 100+ docs
 * pages individually — the locale comes from the [locale] segment of
 * the URL, which is part of `generateStaticParams`, so each combination
 * is pre-rendered without ever needing request headers.
 */
export const dynamic = "force-static"

export const metadata = {
  title: "ProxMenux — Interactive Menu and Web Dashboard for Proxmox VE",
  generator: "Next.js",
  applicationName: "ProxMenux",
  referrer: "origin-when-cross-origin",
  keywords: [
    "Proxmox VE",
    "Proxmox",
    "PVE",
    "ProxMenux",
    "MacRimi",
    "proxmox menu",
    "proxmox tui",
    "proxmox dashboard",
    "proxmox web dashboard",
    "proxmox monitor",
    "proxmox open source",
    "proxmox community",
    "proxmox helper script",
    "proxmox automation",
    "menu-driven",
    "self-hosted",
    "virtualization",
    "VM management",
    "LXC management",
    "container management",
  ],
  authors: [{ name: "MacRimi", url: "https://github.com/MacRimi" }],
  creator: "MacRimi",
  publisher: "MacRimi",
  description:
    "ProxMenux is an open-source, menu-driven tool for Proxmox VE management with a self-hosted web dashboard. Run post-install tweaks, create VMs and LXC containers, manage GPU passthrough, disks, network and storage from an interactive terminal menu — and watch host health, metrics and notifications from a browser.",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  metadataBase: new URL("https://proxmenux.com"),
  alternates: {
    canonical: "https://proxmenux.com",
    types: {
      "application/rss+xml": "https://proxmenux.com/rss.xml",
    },
  },
  openGraph: {
    title: "ProxMenux — Interactive Menu and Web Dashboard for Proxmox VE",
    description:
      "Open-source CLI/TUI plus a self-hosted web dashboard for Proxmox VE management. Run scripts and wizards from a terminal menu, or watch host health and notifications from a browser.",
    url: "https://proxmenux.com",
    siteName: "ProxMenux",
    images: [
      {
        url: "https://proxmenux.com/main.png",
        width: 1363,
        height: 735,
        alt: "ProxMenux — Interactive Menu and Web Dashboard for Proxmox VE",
      },
    ],
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux — Interactive Menu and Web Dashboard for Proxmox VE",
    description:
      "Open-source CLI/TUI + self-hosted web dashboard for Proxmox VE management.",
    images: ["https://proxmenux.com/main.png"],
    creator: "@MacRimi",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params

  if (!hasLocale(routing.locales, locale)) {
    notFound()
  }

  setRequestLocale(locale)

  return (
    <NextIntlClientProvider>
      {/* LocaleHtmlSync writes `document.documentElement.lang = locale`
          after hydration so the active language is reflected in <html lang>
          for accessibility tools and SEO crawlers that execute JS. The
          static root layout always serves lang="en" as the fallback for
          users with JavaScript disabled. */}
      <LocaleHtmlSync locale={locale} />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            name: "ProxMenux",
            description:
              "Open-source, menu-driven tool for Proxmox VE management with a self-hosted web dashboard. Includes post-install tweaks, VM and LXC creation, GPU and Coral TPU passthrough, disk, storage and network workflows, plus a Health Monitor with notifications and a REST API.",
            applicationCategory: "DeveloperApplication",
            operatingSystem: "Linux",
            offers: {
              "@type": "Offer",
              price: "0",
              priceCurrency: "USD",
            },
            author: {
              "@type": "Person",
              name: "MacRimi",
              url: "https://github.com/MacRimi",
            },
            license: "https://github.com/MacRimi/ProxMenux/blob/main/LICENSE",
            codeRepository: "https://github.com/MacRimi/ProxMenux",
            url: "https://proxmenux.com",
            image: "https://proxmenux.com/main.png",
          }),
        }}
      />
      <Navbar />
      <MouseMoveEffect />
      <div className="pt-16 md:pt-16">{children}</div>
      <script src="/pagefind/pagefind-highlight.js" type="module" defer />
      <Suspense fallback={null}>
        <PagefindHighlighter />
      </Suspense>
    </NextIntlClientProvider>
  )
}
