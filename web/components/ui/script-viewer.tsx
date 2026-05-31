import { ExternalLink } from "lucide-react"
import { cn } from "@/lib/utils"

interface ScriptViewerProps {
  scriptPath: string
  githubRepo?: string
  githubBranch?: string
  className?: string
}

const DEFAULT_REPO = "MacRimi/ProxMenux"
const DEFAULT_BRANCH = "main"

// Top-level repo directories. When a `scriptPath` starts with any of
// these, we treat it as already-relative-to-repo-root and skip the
// implicit `scripts/` prefix. Bash scripts under `scripts/` (the
// majority of doc pages) keep working as before — they don't start
// with one of these prefixes.
const REPO_ROOTS = ["AppImage/", "web/", "menu", "json/", "guides/", "lang/", "images/"]

function buildScriptHref(scriptPath: string, repo: string, branch: string): string {
  const isRepoAbsolute = REPO_ROOTS.some((r) => scriptPath.startsWith(r))
  const path = isRepoAbsolute ? scriptPath : `scripts/${scriptPath}`
  return `https://github.com/${repo}/blob/${branch}/${path}`
}

export function ScriptViewer({
  scriptPath,
  githubRepo = DEFAULT_REPO,
  githubBranch = DEFAULT_BRANCH,
  className,
}: ScriptViewerProps) {
  const filename = scriptPath.split("/").pop() || scriptPath
  const githubUrl = buildScriptHref(scriptPath, githubRepo, githubBranch)
  const isRepoAbsolute = REPO_ROOTS.some((r) => scriptPath.startsWith(r))
  const titlePath = isRepoAbsolute ? scriptPath : `scripts/${scriptPath}`

  return (
    <a
      href={githubUrl}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-800 transition-colors hover:border-emerald-400 hover:bg-emerald-100",
        className,
      )}
      aria-label={`View ${filename} on GitHub (opens in a new tab)`}
      title={`${titlePath} — opens on GitHub in a new tab`}
    >
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      View script
    </a>
  )
}
