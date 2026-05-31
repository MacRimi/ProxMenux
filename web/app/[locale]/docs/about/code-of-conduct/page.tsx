import type { Metadata } from "next"
import { getTranslations, setRequestLocale } from "next-intl/server"
import fs from "fs"
import path from "path"
import { remark } from "remark"
import html from "remark-html"
import * as gfm from "remark-gfm"
import React from "react"
import parse from "html-react-parser"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.about.codeOfConduct.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/about/code-of-conduct",
    },
  }
}

async function getCodeOfConductContent(notFoundMsg: string, loadFailedMsg: string) {
  try {
    const codeOfConductPath = path.join(process.cwd(), "..", "CODE_OF_CONDUCT.md")

    if (!fs.existsSync(codeOfConductPath)) {
      console.error("CODE_OF_CONDUCT.md file not found.")
      return `<p class='text-red-600'>${notFoundMsg}</p>`
    }

    const fileContents = fs.readFileSync(codeOfConductPath, "utf8")

    const result = await remark()
      .use(gfm.default || gfm)
      .use(html)
      .process(fileContents)

    return result.toString()
  } catch (error) {
    console.error("Error reading the CODE_OF_CONDUCT.md file", error)
    return `<p class='text-red-600'>${loadFailedMsg}</p>`
  }
}

function cleanInlineCode(content: string) {
  return content.replace(/<code>(.*?)<\/code>/g, (_, codeContent) => {
    return `<code class="bg-gray-200 text-gray-900 px-1 rounded">${codeContent.replace(/^`|`$/g, "")}</code>`
  })
}

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

export default async function CodeOfConductPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.about.codeOfConduct" })
  const codeOfConductContent = await getCodeOfConductContent(t("errors.notFound"), t("errors.loadFailed"))
  const cleanedInlineCode = cleanInlineCode(codeOfConductContent)
  const parsedContent = wrapCodeBlocksWithCopyable(cleanedInlineCode)

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <div className="container mx-auto px-4 py-16" style={{ maxWidth: "980px" }}>
        <div className="prose max-w-none text-[16px]">{parsedContent}</div>
      </div>
    </div>
  )
}
