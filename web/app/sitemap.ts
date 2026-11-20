import type { MetadataRoute } from "next"
import fs from "fs"
import path from "path"
import { routing } from "@/i18n/routing"

export const dynamic = "force-static"

const SITE_URL = "https://proxmenux.com"

function walkDocsRoutes(dir: string, baseRoute: string): string[] {
  const routes: string[] = []
  if (!fs.existsSync(dir)) return routes

  const entries = fs.readdirSync(dir, { withFileTypes: true })

  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      routes.push(...walkDocsRoutes(full, `${baseRoute}/${entry.name}`))
    } else if (entry.name === "page.tsx" || entry.name === "page.mdx") {
      routes.push(baseRoute)
    }
  }

  return routes
}

export default function sitemap(): MetadataRoute.Sitemap {
  // Every page lives under app/[locale] and is exported once per locale.
  const routes = Array.from(new Set(walkDocsRoutes(path.join(process.cwd(), "app", "[locale]"), "")))
  const now = new Date()

  return routing.locales.flatMap((locale) =>
    routes.map((route) => ({
      // Trailing slash: the export serves each page as <route>/index.html.
      url: `${SITE_URL}/${locale}${route}/`,
      lastModified: now,
      changeFrequency: route.startsWith("/docs") ? ("weekly" as const) : ("monthly" as const),
      priority: route === "" ? 1.0 : route.startsWith("/docs") ? 0.8 : 0.6,
    })),
  )
}
