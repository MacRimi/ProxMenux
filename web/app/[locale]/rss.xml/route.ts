import { NextResponse } from "next/server"
import fs from "fs"
import path from "path"
import { routing } from "@/i18n/routing"

export const dynamic = "force-static"

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

interface ChangelogEntry {
  version: string
  date: string
  content: string
  url: string
  title: string
  image?: string
}

// Per-locale RSS feed. Mirrors /app/rss.xml/route.ts (which stays the
// canonical English feed at the root for backwards compatibility with
// existing subscribers) but reads the localized CHANGELOG at
// <repo>/lang/<locale>/CHANGELOG.md. Falls back to the English source
// when the localized file doesn't exist yet so partial translations
// still produce a valid feed.

const DEFAULT_CHANNEL_IMAGE =
  "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png"

type LocaleStrings = {
  lang: string
  channelTitle: string
  channelDescription: string
  itemTitlePrefix: string  // "ProxMenux" — used as `${prefix} ${version}` for versioned releases
  itemUpdatePrefix: string // "ProxMenux Update" — used as `${prefix} ${date}` for dated releases
  category: string
}

const STRINGS: Record<string, LocaleStrings> = {
  en: {
    lang: "en-US",
    channelTitle: "ProxMenux Changelog",
    channelDescription:
      "Release notes and changes in ProxMenux — an open-source interactive menu and web dashboard for Proxmox VE management.",
    itemTitlePrefix: "ProxMenux",
    itemUpdatePrefix: "ProxMenux Update",
    category: "Changelog",
  },
  es: {
    lang: "es-ES",
    channelTitle: "Changelog de ProxMenux",
    channelDescription:
      "Notas de release y cambios en ProxMenux — un menú interactivo y panel web open-source para gestionar Proxmox VE.",
    itemTitlePrefix: "ProxMenux",
    itemUpdatePrefix: "Actualización ProxMenux",
    category: "Changelog",
  },
}

function resolveChangelogPath(locale: string): string {
  const repoRoot = path.join(process.cwd(), "..")
  if (locale && locale !== "en") {
    const localized = path.join(repoRoot, "lang", locale, "CHANGELOG.md")
    if (fs.existsSync(localized)) return localized
  }
  return path.join(repoRoot, "CHANGELOG.md")
}

function extractFirstImage(rawContent: string): string | null {
  const match = rawContent.match(/!\[[^\]]*\]\(([^)]+)\)/)
  if (!match) return null
  const url = match[1]
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return url.replace(
      "https://macrimi.github.io/ProxMenux",
      "https://proxmenux.com",
    )
  }
  if (url.startsWith("/")) return `https://proxmenux.com${url}`
  return `https://proxmenux.com/${url}`
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;")
}

function formatContentForRSS(content: string): string {
  return content
    .replace(/https:\/\/macrimi\.github\.io\/ProxMenux/g, "https://proxmenux.com")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match, alt, url) => {
      let absoluteUrl = url
      if (url.startsWith("/")) {
        absoluteUrl = `https://proxmenux.com${url}`
      } else if (!url.startsWith("http://") && !url.startsWith("https://")) {
        absoluteUrl = `https://proxmenux.com/${url}`
      }
      return `<div style="margin: 1.5em 0; text-align: center;">
        <img src="${absoluteUrl}" alt="${alt}" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" />
      </div>`
    })
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/```[\s\S]*?```/g, (match) => {
      const code = match.replace(/```/g, "").trim()
      return `<pre><code>${code}</code></pre>`
    })
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*?<\/li>\s*)+/g, (match) => `<ul>${match}</ul>`)
    .replace(/^---$/gm, '<hr style="border: none; border-top: 2px solid #eee; margin: 2em 0;" />')
    .replace(/\n/g, "<br/>")
    .replace(/\s+/g, " ")
    .trim()
}

async function parseChangelog(locale: string, strings: LocaleStrings): Promise<ChangelogEntry[]> {
  try {
    const changelogPath = resolveChangelogPath(locale)
    if (!fs.existsSync(changelogPath)) return []

    const fileContents = fs.readFileSync(changelogPath, "utf8")
    const entries: ChangelogEntry[] = []

    const lines = fileContents.split("\n")
    let currentEntry: Partial<ChangelogEntry> | null = null
    let contentLines: string[] = []

    for (const line of lines) {
      const versionMatch = line.match(/^##\s+\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})/)
      const dateMatch = line.match(/^##\s+(\d{4}-\d{2}-\d{2})$/)

      if (versionMatch || dateMatch) {
        if (currentEntry && contentLines.length > 0) {
          const rawContent = contentLines.join("\n").trim()
          const firstImage = extractFirstImage(rawContent)
          if (firstImage) currentEntry.image = firstImage
          currentEntry.content = formatContentForRSS(rawContent)
          if (currentEntry.version && currentEntry.date && currentEntry.title) {
            entries.push(currentEntry as ChangelogEntry)
          }
        }

        if (versionMatch) {
          const version = versionMatch[1]
          const date = versionMatch[2]
          currentEntry = {
            version,
            date,
            url: `https://proxmenux.com/${locale}/changelog#${version}`,
            title: `${strings.itemTitlePrefix} ${version}`,
          }
        } else if (dateMatch) {
          const date = dateMatch[1]
          currentEntry = {
            version: date,
            date,
            url: `https://proxmenux.com/${locale}/changelog#${date}`,
            title: `${strings.itemUpdatePrefix} ${date}`,
          }
        }

        contentLines = []
      } else if (currentEntry && line.trim()) {
        if (contentLines.length > 0 || line.trim() !== "") {
          contentLines.push(line)
        }
      }
    }

    if (currentEntry && contentLines.length > 0) {
      const rawContent = contentLines.join("\n").trim()
      const firstImage = extractFirstImage(rawContent)
      if (firstImage) currentEntry.image = firstImage
      currentEntry.content = formatContentForRSS(rawContent)
      if (currentEntry.version && currentEntry.date && currentEntry.title) {
        entries.push(currentEntry as ChangelogEntry)
      }
    }

    return entries.slice(0, 20)
  } catch (error) {
    console.error("Error parsing changelog:", error)
    return []
  }
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string }> },
) {
  const { locale } = await params
  const strings = STRINGS[locale] ?? STRINGS.en
  const entries = await parseChangelog(locale, strings)
  const siteUrl = "https://proxmenux.com"
  const channelImage = entries.find((e) => e.image)?.image ?? DEFAULT_CHANNEL_IMAGE
  const feedUrl = `${siteUrl}/${locale}/rss.xml`
  const changelogUrl = `${siteUrl}/${locale}/changelog`

  const rssXml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>${escapeXml(strings.channelTitle)}</title>
    <description>${escapeXml(strings.channelDescription)}</description>
    <link>${changelogUrl}</link>
    <atom:link href="${feedUrl}" rel="self" type="application/rss+xml"/>
    <language>${strings.lang}</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <generator>ProxMenux RSS Generator</generator>
    <ttl>60</ttl>
    <image>
      <url>${escapeXml(channelImage)}</url>
      <title>${escapeXml(strings.channelTitle)}</title>
      <link>${changelogUrl}</link>
    </image>

    ${entries
      .map(
        (entry) => `
    <item>
      <title>${escapeXml(entry.title)}</title>
      <description>${escapeXml(entry.content.replace(/<[^>]*>/g, "").substring(0, 200))}...</description>
      <content:encoded><![CDATA[${entry.content}]]></content:encoded>
      <link>${entry.url}</link>
      <guid isPermaLink="true">${entry.url}</guid>
      <pubDate>${new Date(entry.date).toUTCString()}</pubDate>
      <category>${escapeXml(strings.category)}</category>${entry.image ? `
      <media:thumbnail url="${escapeXml(entry.image)}"/>
      <media:content url="${escapeXml(entry.image)}" medium="image"/>
      <enclosure url="${escapeXml(entry.image)}" type="image/png" length="0"/>` : ""}
    </item>`,
      )
      .join("")}
  </channel>
</rss>`

  return new NextResponse(rssXml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  })
}
