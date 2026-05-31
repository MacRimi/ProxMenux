import { codeToHtml } from "shiki"
import { cn } from "@/lib/utils"
import { CopyButton } from "./CopyButton"

interface CopyableCodeProps {
  code: string
  language?: string
  className?: string
}

/**
 * Server-rendered code block with Shiki syntax highlighting.
 *
 * Shiki runs at build time (Next.js static export pre-renders every
 * page) so the resulting HTML carries pre-coloured `<span>` elements
 * and the client doesn't have to load any highlighter JS. The copy
 * button is the only interactive bit and lives in CopyButton, a tiny
 * client component.
 *
 * Default theme is `github-dark` — matches the Hermes/Docusaurus look
 * the user asked us to emulate. Default language is bash because most
 * snippets in the docs are shell commands.
 *
 * Defensive fallback: if Shiki can't tokenize the requested language
 * (unknown alias, unsupported grammar) we fall back to a plain
 * dark-background <pre> so the page never crashes.
 */
const CopyableCode = async ({ code, language = "bash", className }: CopyableCodeProps) => {
  let html: string
  try {
    html = await codeToHtml(code, {
      lang: language,
      theme: "github-dark",
    })
  } catch {
    // Unknown lang or grammar error → render as plain text on a dark
    // background to preserve the visual style without colour.
    const escaped = code
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
    html = `<pre class="shiki" style="background-color:#24292e;color:#e1e4e8"><code>${escaped}</code></pre>`
  }

  return (
    <div className={cn("relative w-full my-4", className)}>
      <div
        className={cn(
          "rounded-md overflow-hidden",
          "[&_pre]:p-4 [&_pre]:overflow-x-auto [&_pre]:text-sm [&_pre]:leading-relaxed",
          "[&_code]:font-mono",
        )}
        dangerouslySetInnerHTML={{ __html: html }}
      />
      <CopyButton text={code} />
    </div>
  )
}

export default CopyableCode
