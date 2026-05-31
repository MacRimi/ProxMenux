import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import createNextIntlPlugin from 'next-intl/plugin'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

// Wires the next-intl request config at ./i18n/request.ts into the
// Next.js build. Every page rendered under /[locale]/... gets the
// per-request messages and locale resolution from there.
const withNextIntl = createNextIntlPlugin('./i18n/request.ts')

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  // GitHub Pages serves a directory URL `/foo/` by looking for
  // `out/foo/index.html`. Next.js's default static export with
  // `trailingSlash: false` emits `out/foo.html` instead, which Pages
  // only serves for the bare URL `/foo` (no trailing slash). The
  // i18n root redirect points users at `/<defaultLocale>/` (with
  // slash) — so every visitor would land on a 404. Enabling
  // trailingSlash makes Next.js emit `out/<route>/index.html` for
  // every page, including `out/en/index.html` and `out/es/index.html`
  // so the locale roots load correctly. Internal `<Link>` URLs from
  // next-intl already include the trailing slash, so this aligns
  // export, runtime navigation and Pages serving.
  trailingSlash: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
    remotePatterns: [
      {
        protocol: "https",
        hostname: "raw.githubusercontent.com",
        pathname: "/MacRimi/ProxMenux/main/images/**",
      },
    ],
  },
  staticPageGenerationTimeout: 180,
  webpack: (config, { isServer }) => {
    config.resolve.alias["@guides"] = join(__dirname, "..", "guides")
    config.resolve.alias["@changelog"] = join(__dirname, "..", "CHANGELOG.md")
    return config
  },
}

export default withNextIntl(nextConfig)
