import type { MetadataRoute } from "next"
import fs from "fs"
import path from "path"

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
      routes.push(baseRoute || "/")
    }
  }

  return routes
}

export default function sitemap(): MetadataRoute.Sitemap {
  const appDir = path.join(process.cwd(), "app")
  const discovered = walkDocsRoutes(appDir, "")
    .filter((r) => !r.includes("/api/"))
    .map((r) => (r === "" ? "/" : r))

  const unique = Array.from(new Set(discovered))
  const now = new Date()

  return unique.map((route) => ({
    url: `${SITE_URL}${route}`,
    lastModified: now,
    changeFrequency: route.startsWith("/docs") ? "weekly" : "monthly",
    priority: route === "/" ? 1.0 : route.startsWith("/docs") ? 0.8 : 0.6,
  }))
}
