import type { Metadata } from "next"
import fs from "fs"
import path from "path"
import { remark } from "remark"
import html from "remark-html"
import * as gfm from "remark-gfm"
import parse from "html-react-parser"
import { getTranslations, setRequestLocale } from "next-intl/server"
import Footer from "@/components/footer"
import RSSLink from "@/components/rss-link"
import CopyableCode from "@/components/CopyableCode"

// Resolve which CHANGELOG.md to read for the given locale. The canonical
// English file lives at the repo root (so GitHub displays it as-is and
// existing RSS / external consumers don't break). Localized versions
// sit under <repo>/lang/<locale>/CHANGELOG.md. Falls back to English if
// the localized file doesn't exist yet — so a partially-translated
// changelog still renders (in EN) instead of 404'ing.
function resolveChangelogPath(locale: string): string {
  const repoRoot = path.join(process.cwd(), "..")
  if (locale && locale !== "en") {
    const localized = path.join(repoRoot, "lang", locale, "CHANGELOG.md")
    if (fs.existsSync(localized)) return localized
  }
  return path.join(repoRoot, "CHANGELOG.md")
}

// Surface the latest changelog entry in the metadata so social previews and
// SERP snippets reflect what was actually shipped. The CHANGELOG.md mixes two
// formats — `## [x.y.z] - YYYY-MM-DD` (older releases) and `## YYYY-MM-DD`
// (newer dated updates). The most recent entry is always the first `##` line
// from the top of the file, regardless of which format it uses. We also try
// to extract a version-looking suffix from the first body paragraph so dated
// updates like `## 2026-04-20` followed by `### New version ProxMenux v1.2.1`
// can still surface the version number.
function readLatestChangelogVersion(locale: string): { version: string; date: string } | null {
  try {
    const changelogPath = resolveChangelogPath(locale)
    if (!fs.existsSync(changelogPath)) return null
    const text = fs.readFileSync(changelogPath, "utf8")

    const firstHeading = text.match(/^##\s+(.+?)\s*$/m)
    if (!firstHeading) return null
    const headingText = firstHeading[1].trim()

    // Format A: ## [1.1.1] - 2025-03-21
    const bracketMatch = headingText.match(/^\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})$/)
    if (bracketMatch) return { version: bracketMatch[1], date: bracketMatch[2] }

    // Format B: ## 2026-04-20  (use the date and try to find a v-tag in the body)
    const dateMatch = headingText.match(/^(\d{4}-\d{2}-\d{2})$/)
    if (dateMatch) {
      const date = dateMatch[1]
      const headingIdx = text.indexOf(firstHeading[0])
      const nextHeadingIdx = text.indexOf("\n## ", headingIdx + 1)
      const body =
        nextHeadingIdx === -1
          ? text.slice(headingIdx)
          : text.slice(headingIdx, nextHeadingIdx)
      const vMatch = body.match(/\bProxMenux\s+v?(\d+(?:\.\d+){1,2})\b/i)
      return { version: vMatch ? `v${vMatch[1]}` : date, date }
    }

    return null
  } catch {
    return null
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "changelog.meta" })
  const latest = readLatestChangelogVersion(locale)
  const versionTag = latest?.version ?? ""
  const dateTag = latest?.date ?? ""

  const titleSuffix = versionTag ? ` — ${t("latest")}: ${versionTag}` : ""
  const descriptionSuffix = versionTag
    ? `${t("mostRecent")}: ${versionTag}${dateTag && dateTag !== versionTag ? ` (${dateTag})` : ""}.`
    : ""

  return {
    title: `${t("title")}${titleSuffix} | ${t("titleSuffix")}`,
    description: `${t("description")} ${descriptionSuffix} ${t("descriptionTail")}`.trim(),
    keywords: [
      "proxmenux changelog",
      "proxmenux release notes",
      "proxmenux updates",
      "proxmenux versions",
      "proxmox script changelog",
      "proxmenux history",
      "proxmenux roadmap",
    ],
    alternates: {
      canonical: `https://proxmenux.com/${locale}/changelog`,
      types: {
        "application/rss+xml":
          locale === "en"
            ? "https://proxmenux.com/rss.xml"
            : `https://proxmenux.com/${locale}/rss.xml`,
      },
    },
    openGraph: {
      title: `${t("title")}${titleSuffix}`,
      description: `${t("ogDescription")} ${descriptionSuffix} ${t("ogTail")}`.trim(),
      type: "article",
      url: "https://proxmenux.com/changelog",
      siteName: "ProxMenux",
      images: [
        {
          url: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png",
          width: 1363,
          height: 735,
          alt: "ProxMenux — Interactive Menu and Web Dashboard for Proxmox VE",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: `${t("title")}${titleSuffix}`,
      description: `${t("ogDescription")} ${descriptionSuffix}`.trim(),
      images: [
        "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png",
      ],
    },
  }
}

async function getChangelogContent(locale: string) {
  try {
    const changelogPath = resolveChangelogPath(locale)

    if (!fs.existsSync(changelogPath)) {
      console.error("❌ CHANGELOG.md file not found.")
      return "<p class='text-red-600'>Error: CHANGELOG.md file not found</p>"
    }

    const fileContents = fs.readFileSync(changelogPath, "utf8")

    // Add remark-gfm to support images, tables and other advanced Markdown elements
    const result = await remark()
      .use(gfm.default || gfm) // Safe handling of remark-gfm
      .use(html)
      .process(fileContents)

    return result.toString()
  } catch (error) {
    console.error("❌ Error reading CHANGELOG.md file", error)
    return "<p class='text-red-600'>Error: Could not load changelog content.</p>"
  }
}

// Clean backticks in inline code fragments
function cleanInlineCode(content: string) {
  return content.replace(/<code>(.*?)<\/code>/g, (_, codeContent) => {
    return `<code class="bg-gray-200 text-gray-900 px-1 rounded">${codeContent.replace(/^`|`$/g, "")}</code>`
  })
}

// Wrap code blocks with CopyableCode component
function wrapCodeBlocksWithCopyable(content: string) {
  return parse(content, {
    replace: (domNode: any) => {
      if (domNode.name === "pre" && domNode.children.length > 0) {
        const codeElement = domNode.children.find((child: any) => child.name === "code")
        if (codeElement) {
          const codeContent = codeElement.children[0]?.data?.trim() || ""
          return <CopyableCode code={codeContent} />
        }
      }
    },
  })
}

export default async function ChangelogPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "changelog" })
  const changelogContent = await getChangelogContent(locale)
  const cleanedInlineCode = cleanInlineCode(changelogContent)
  const parsedContent = wrapCodeBlocksWithCopyable(cleanedInlineCode)

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <div className="container mx-auto px-4 py-16" style={{ maxWidth: "980px" }}>
        <h1 className="text-4xl font-bold mb-8">{t("pageTitle")}</h1>
        <RSSLink />
        <div className="prose max-w-none text-[16px]">{parsedContent}</div>
      </div>
      <Footer />
    </div>
  )
}
