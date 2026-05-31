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
