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

function escapeXml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function formatContentForRSS(content: string): string {
  return (
    content
      .replace(/https:\/\/macrimi\.github\.io\/ProxMenux/g, "https://proxmenux.com")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
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

    const lines = fileContents.split("\n")
    let currentEntry: Partial<ChangelogEntry> | null = null
    let contentLines: string[] = []

    for (const line of lines) {
      const versionMatch = line.match(/^##\s+\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})/)
      const dateMatch = line.match(/^##\s+(\d{4}-\d{2}-\d{2})$/)

      if (versionMatch || dateMatch) {
        if (currentEntry && contentLines.length > 0) {
          const rawContent = contentLines.join("\n").trim()
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
            url: `https://proxmenux.com/changelog#${version}`,
            title: `ProxMenux ${version}`,
          }
        } else if (dateMatch) {
          const date = dateMatch[1]
          currentEntry = {
            version: date,
            date,
            url: `https://proxmenux.com/changelog#${date}`,
            title: `ProxMenux Update ${date}`,
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

export async function GET() {
  const entries = await parseChangelog()
  const siteUrl = "https://proxmenux.com"

  const rssXml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>ProxMenux Changelog</title>
    <description>Latest updates and changes in ProxMenux - An Interactive Menu for Proxmox VE Management</description>
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
      <title>${escapeXml(entry.title)}</title>
      <description>${escapeXml(entry.content.replace(/<[^>]*>/g, '').substring(0, 200))}...</description>
      <content:encoded><![CDATA[${entry.content}]]></content:encoded>
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