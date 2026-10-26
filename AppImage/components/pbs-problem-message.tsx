"use client"

import { pbsErrorText, pbsIsKnownError } from "../lib/pbs-messages"
import { useT } from "../lib/i18n/provider"

// Known application messages are already explained in the active language.
// Preserve unrecognized external diagnostics as escaped technical details.
export function PBSProblemMessage({ problem, raw, fallback, className = "" }: {
  problem?: unknown; raw?: string; fallback?: string; className?: string
}) {
  const t = useT()
  return <div className={`min-w-0 space-y-1 ${className}`}>
    <p>{pbsErrorText(problem, t, fallback)}</p>
    {raw && !pbsIsKnownError(problem) && <details className="text-xs">
      <summary className="cursor-pointer">{t("pbs.technicalDetails")}</summary>
      <pre className="mt-1 whitespace-pre-wrap break-words font-mono">{raw}</pre>
    </details>}
  </div>
}
