"use client"

import { useI18n } from "../lib/i18n/provider"

export function MetricsCacheNotice({ lastChecked }: { lastChecked: number | null }) {
  const { language, t } = useI18n()
  if (lastChecked === null) return null

  return (
    <p role="status" className="text-xs text-amber-600 dark:text-amber-400 mb-2">
      {t("overview.metricsCachedWarning", {
        time: new Date(lastChecked * 1000).toLocaleString(language),
      })}
    </p>
  )
}
