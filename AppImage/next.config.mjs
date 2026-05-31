/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  experimental: {
    esmExternals: 'loose',
  },
  // Strip every `console.*` call in production builds except `error` and
  // `warn` (we still want operators to see real errors in DevTools). Audit
  // residual: ~50 leftover `console.log("[v0] ...")` from the v0.dev
  // prototype were leaking object dumps to the browser console in production.
  compiler: {
    removeConsole: {
      exclude: ['error', 'warn'],
    },
  },
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
      };
    }
    return config;
  },
};

export default nextConfig;
