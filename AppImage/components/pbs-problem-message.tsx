"use client"

import { pbsErrorText } from "../lib/pbs-messages"
import { useT } from "../lib/i18n/provider"

// Keep PBS's original diagnostic available without making it the UI message.
export function PBSProblemMessage({ problem, raw, fallback, className = "" }: {
  problem?: unknown; raw?: string; fallback?: string; className?: string
}) {
  const t = useT()
  return <div className={`min-w-0 space-y-1 ${className}`}>
    <p>{pbsErrorText(problem, t, fallback)}</p>
    {raw && <details className="text-xs">
      <summary className="cursor-pointer">{t("pbs.technicalDetails")}</summary>
      <pre className="mt-1 whitespace-pre-wrap break-words font-mono">{raw}</pre>
    </details>}
  </div>
}
