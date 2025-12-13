import fs from "fs"
import path from "path"
import { remark } from "remark"
import html from "remark-html"
import * as gfm from "remark-gfm"
import dynamic from "next/dynamic"
import React from "react"
import parse from "html-react-parser"

const CopyableCode = dynamic(() => import("@/components/CopyableCode"), { ssr: false })

async function getCodeOfConductContent() {
  try {
    const codeOfConductPath = path.join(process.cwd(), "..", "CODE_OF_CONDUCT.md")

  if (!fs.existsSync(codeOfConductPath)) {
    console.error("CODE_OF_CONDUCT.md file not found.");
    return "<p class='text-red-600'>Error: CODE_OF_CONDUCT.md file not found.</p>";
  }
  
  const fileContents = fs.readFileSync(codeOfConductPath, "utf8");
  
  const result = await remark()
    .use(gfm.default || gfm)
    .use(html)
    .process(fileContents);
  
  return result.toString();
  } catch (error) {
    console.error("Error reading the CODE_OF_CONDUCT.md file", error);
    return "<p class='text-red-600'>Error: Unable to load the Code of Conduct content.</p>";
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
    }
  })
}

export default async function CodeOfConductPage() {
  const codeOfConductContent = await getCodeOfConductContent()
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
