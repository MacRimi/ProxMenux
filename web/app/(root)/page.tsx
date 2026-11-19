import { routing } from "@/i18n/routing"

/**
 * Root index — sends `/` to the default locale.
 *
 * With `output: "export"` we can't run a middleware that detects the
 * browser's preferred locale and redirects accordingly. Instead the
 * root URL renders a minimal HTML stub that points the browser at
 * `/<defaultLocale>/` through three layers, in order of reliability:
 *
 *   1. `<meta http-equiv="refresh">` — works even without JavaScript,
 *      respected by every browser and most crawlers (Google honours
 *      it as a 301-equivalent when delay is 0).
 *   2. `<link rel="canonical">` — tells search engines that the
 *      localized URL is the canonical one.
 *   3. An inline `<script>` doing `location.replace(...)` — kicks in
 *      faster than the meta refresh when JS is enabled, and survives
 *      the rare browser that ignores the meta tag.
 */
export default function RootPage() {
  const target = `/${routing.defaultLocale}/`
  return (
    <>
      <meta httpEquiv="refresh" content={`0; url=${target}`} />
      <link rel="canonical" href={target} />
      <script
        dangerouslySetInnerHTML={{
          __html: `if (location.pathname === '/') { location.replace(${JSON.stringify(target)}); }`,
        }}
      />
      <noscript>
        <p style={{ fontFamily: "system-ui, sans-serif", textAlign: "center", marginTop: "2rem" }}>
          Redirecting to <a href={target}>{target}</a>…
        </p>
      </noscript>
    </>
  )
}
