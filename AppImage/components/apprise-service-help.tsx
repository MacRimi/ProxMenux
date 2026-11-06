"use client"

import { ExternalLink } from "lucide-react"
import { useT } from "../lib/i18n/provider"

// These are examples, never defaults: opening help must not replace a saved
// destination or put placeholder credentials into the notification settings.
export function AppriseServiceHelp() {
  const t = useT()
  return <details className="rounded-md border border-border bg-muted/20 p-2 text-xs">
    <summary className="cursor-pointer font-medium">{t("settings.notifications.ui.appriseServiceHelp")}</summary>
    <div className="grid gap-3 pt-3 sm:grid-cols-2">
      <div className="space-y-1.5 min-w-0">
        <h4 className="font-medium">Slack</h4>
        <p className="text-muted-foreground">{t("settings.notifications.ui.appriseSlackSteps")}</p>
        <code className="block break-all rounded bg-background p-2 text-[10px]">https://hooks.slack.com/services/TOKEN_A/TOKEN_B/TOKEN_C</code>
        <a href="https://appriseit.com/services/slack/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-cyan-500 hover:underline">
          {t("settings.notifications.ui.appriseSlackDocs")} <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <div className="space-y-1.5 min-w-0">
        <h4 className="font-medium">Matrix</h4>
        <p className="text-muted-foreground">{t("settings.notifications.ui.appriseMatrixSteps")}</p>
        <code className="block break-all rounded bg-background p-2 text-[10px]">matrixs://USER:PASSWORD@matrix.example.com/!ROOM_ID:matrix.example.com</code>
        <a href="https://appriseit.com/services/matrix/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-cyan-500 hover:underline">
          {t("settings.notifications.ui.appriseMatrixDocs")} <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
    <p className="mt-3 text-muted-foreground">{t("settings.notifications.ui.appriseServiceFinish")}</p>
  </details>
}
