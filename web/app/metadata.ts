import type { Metadata } from "next"

const description =
  "A menu-driven script for Proxmox VE management, designed to simplify and streamline the execution of commands and tasks."

export const metadata: Metadata = {
  title: "ProxMenux",
  description,
  generator: "Next.js",
  applicationName: "ProxMenux",
  referrer: "origin-when-cross-origin",
  keywords: ["Proxmox VE", "VE", "ProxMenux", "MacRimi", "menu-driven", "menu", "scripts", "virtualization"],
  authors: [{ name: "MacRimi" }],
  creator: "MacRimi",
  publisher: "MacRimi",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  metadataBase: new URL(`https://proxmenux.com`),
  openGraph: {
    title: "ProxMenux",
    description,
    url: `https://proxmenux.com`,
    siteName: "ProxMenux",
    images: [
      {
        url: `https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png`,
        width: 1363,
        height: 735,
      },
    ],
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ProxMenux",
    description,
    images: [`https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png`],
  },
  icons: {
    icon: [
      { url: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/favicon.ico", sizes: "any" },
      { url: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/icon.svg", type: "image/svg+xml" },
    ],
    apple: [{ url: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public//apple-touch-icon.png" }],
  },
}
