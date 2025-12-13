import { NextResponse } from "next/server"
import fs from "fs"
import path from "path"

interface ChangelogEntry {
  version: string
  date: string
  content: string
  url: string
  title: string
}

// Function to clean and format markdown content for RSS
function formatContentForRSS(content: string): string {
  return (
    content
      // Convert ### headers to bold text
      .replace(/^### (.+)$/gm, "**$1**")
      // Convert ** bold ** to simple bold
      .replace(/\*\*(.*?)\*\*/g, "$1")
      // Clean code blocks - remove ``` and format nicely
      .replace(/```[\s\S]*?```/g, (match) => {
        const code = match.replace(/```/g, "").trim()
        return `\n${code}\n`
      })
      // Convert - bullet points to •
      .replace(/^- /gm, "• ")
      // Clean up multiple newlines
      .replace(/\n{3,}/g, "\n\n")
      // Remove backslashes used for line breaks
      .replace(/\\\s*$/gm, "")
      // Clean up extra spaces
      .replace(/\s+/g, " ")
      .trim()
  )
}

async function parseChangelog(): Promise<ChangelogEntry[]> {
  try {
    const changelogPath = path.join(process.cwd(), "..", "CHANGELOG.md")

    if (!fs.existsSync(changelogPath)) {
      return []
    }

    const fileContents = fs.readFileSync(changelogPath, "utf8")
    const entries: ChangelogEntry[] = []

    // Split by ## headers (both versions and dates)
    const lines = fileContents.split("\n")
    let currentEntry: Partial<ChangelogEntry> | null = null
    let contentLines: string[] = []

    for (const line of lines) {
      // Check for version header: ## [1.1.1] - 2025-03-21
      const versionMatch = line.match(/^##\s+\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})/)

      // Check for date-only header: ## 2025-05-13
      const dateMatch = line.match(/^##\s+(\d{4}-\d{2}-\d{2})$/)

      if (versionMatch || dateMatch) {
        // Save previous entry if exists
        if (currentEntry && contentLines.length > 0) {
          const rawContent = contentLines.join("\n").trim()
          currentEntry.content = formatContentForRSS(rawContent)
          if (currentEntry.version && currentEntry.date && currentEntry.title) {
            entries.push(currentEntry as ChangelogEntry)
          }
        }

        // Start new entry
        if (versionMatch) {
          const version = versionMatch[1]
          const date = versionMatch[2]
          currentEntry = {
            version,
            date,
            url: `https://macrimi.github.io/ProxMenux/changelog#${version}`,
            title: `ProxMenux ${version}`,
          }
        } else if (dateMatch) {
          const date = dateMatch[1]
          currentEntry = {
            version: date,
            date,
            url: `https://macrimi.github.io/ProxMenux/changelog#${date}`,
            title: `ProxMenux Update ${date}`,
          }
        }

        contentLines = []
      } else if (currentEntry && line.trim()) {
        // Add content lines (skip empty lines at the beginning)
        if (contentLines.length > 0 || line.trim() !== "") {
          contentLines.push(line)
        }
      }
    }

    // Don't forget the last entry
    if (currentEntry && contentLines.length > 0) {
      const rawContent = contentLines.join("\n").trim()
      currentEntry.content = formatContentForRSS(rawContent)
      if (currentEntry.version && currentEntry.date && currentEntry.title) {
        entries.push(currentEntry as ChangelogEntry)
      }
    }

    return entries.slice(0, 20) // Latest 20 entries
  } catch (error) {
    console.error("Error parsing changelog:", error)
    return []
  }
}

export async function GET() {
  const entries = await parseChangelog()
  const siteUrl = "https://macrimi.github.io/ProxMenux"

  const rssXml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>ProxMenux Changelog</title>
    <description>Latest updates and changes in ProxMenux</description>
    <link>${siteUrl}/changelog</link>
    <atom:link href="${siteUrl}/rss.xml" rel="self" type="application/rss+xml"/>
    <language>en-US</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <generator>ProxMenux RSS Generator</generator>
    <ttl>60</ttl>
    
    ${entries
      .map(
        (entry) => `
    <item>
      <title>${entry.title}</title>
      <description><![CDATA[${entry.content.length > 1000 ? entry.content.substring(0, 1000) + "..." : entry.content}]]></description>
      <link>${entry.url}</link>
      <guid isPermaLink="true">${entry.url}</guid>
      <pubDate>${new Date(entry.date).toUTCString()}</pubDate>
      <category>Changelog</category>
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
