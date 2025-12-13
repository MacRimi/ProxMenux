import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)


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

export default nextConfig
