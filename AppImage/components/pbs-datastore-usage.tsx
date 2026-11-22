"use client"

import { CalendarClock, Database } from "lucide-react"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { formatStorage } from "../lib/utils"
import { useT, useI18n } from "../lib/i18n/provider"
import { PBSProblemMessage } from "./pbs-problem-message"

export interface PBSDatastore {
  name: string
  path?: string
  total?: number | null
  used?: number | null
  avail?: number | null
  error?: string
  error_code?: string
  "backend-type"?: string
  "estimated-full-date"?: number
  "gc-status"?: { upid?: string | null; "removed-bytes"?: number; "pending-bytes"?: number }
}

export function datastorePercent(store: PBSDatastore): number | null {
  if (store.total == null || store.used == null || store.total <= 0) return null
  return (store.used / store.total) * 100
}

// Same thresholds and colours as the PVE storage cards.
export function usageTone(percent: number): { bar: string; text: string; used: string } {
  if (percent > 90) return { bar: "[&>div]:bg-red-500", text: "text-red-500", used: "text-red-400" }
  if (percent > 75) return { bar: "[&>div]:bg-yellow-500", text: "text-yellow-500", used: "text-yellow-400" }
  return { bar: "[&>div]:bg-blue-500", text: "text-muted-foreground", used: "text-blue-400" }
}

const gib = (bytes: number) => formatStorage(bytes / 1024 ** 3)

// A datastore without a readable capacity keeps its message: it is never shown as empty.
export function DatastoreUsageRow({ store, compact = false }: { store: PBSDatastore; compact?: boolean }) {
  const t = useT()
  const percent = datastorePercent(store)
  if (percent == null) {
    return <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="font-medium text-foreground truncate">{store.name}</span>
        <span className="text-xs text-muted-foreground">—</span>
      </div>
      <PBSProblemMessage className="text-xs text-amber-500" problem={{ code: store.error_code }} raw={store.error} fallback="pbs.capacityUnavailable" />
    </div>
  }
  const tone = usageTone(percent)
  return <div className="space-y-1">
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="font-medium text-foreground truncate">{store.name}</span>
      <span className={`text-xs font-semibold tabular-nums ${tone.text}`}>{percent.toFixed(1)}%</span>
    </div>
    <Progress value={percent} className={`${compact ? "h-1.5" : "h-2"} ${tone.bar}`} />
    {!compact && <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
      <span>{gib(store.used!)} / {gib(store.total!)}</span>
      <span>{t("pbs.free")}: <span className="font-semibold text-green-500">{gib(store.avail ?? store.total! - store.used!)}</span></span>
    </div>}
  </div>
}

// Same layout as the "Proxmox storage" cards of the PVE Monitor.
export function PBSDatastoreCard({ store }: { store: PBSDatastore }) {
  const t = useT()
  const { language } = useI18n()
  const percent = datastorePercent(store)
  const tone = percent == null ? null : usageTone(percent)
  const fullDate = store["estimated-full-date"]
  const type = store["backend-type"] || t("pbs.datastoreType")
  return <div className={`border rounded-lg p-4 ${store.error ? "border-red-500/50 bg-red-500/5" : ""}`}>
    <div className="flex items-center justify-between gap-2 mb-3">
      <div className="flex items-center gap-2 md:gap-3 min-w-0">
        <Database className="h-5 w-5 text-muted-foreground flex-shrink-0" />
        <h3 className="font-semibold text-base md:text-lg truncate">{store.name}</h3>
        <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">{type}</Badge>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <Badge className={store.error ? "bg-red-500/10 text-red-500 border-red-500/20" : "bg-green-500/10 text-green-500 border-green-500/20"}>
          {store.error ? t("storage.status.error") : t("storage.status.active")}
        </Badge>
        {percent != null && <span className="text-sm font-medium">{percent.toFixed(2)}%</span>}
      </div>
    </div>
    {percent != null && tone ? (
      <div className="space-y-2">
        <Progress value={percent} className={`h-2 ${tone.bar}`} />
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">{t("storage.total")}</p>
            <p className="font-medium">{gib(store.total!)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">{t("storage.used")}</p>
            <p className={`font-medium ${tone.used}`}>{gib(store.used!)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">{t("storage.available")}</p>
            <p className="font-medium text-green-400">{gib(store.avail ?? store.total! - store.used!)}</p>
          </div>
        </div>
      </div>
    ) : (
      <PBSProblemMessage className="text-sm text-muted-foreground" problem={{ code: store.error_code }} raw={store.error} fallback="pbs.capacityUnavailable" />
    )}
    {(store.path || fullDate !== undefined) && <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {store.path && <span className="font-mono truncate" title={store.path}>{store.path}</span>}
      {fullDate !== undefined && <span className="flex items-center">
        <CalendarClock className="mr-1.5 h-3.5 w-3.5" />{t("pbs.estimatedFull")}:
        <span className="ml-1 font-medium text-foreground">{fullDate > 0 ? new Date(fullDate * 1000).toLocaleDateString(language) : t("pbs.estimatedFullUnknown")}</span>
      </span>}
    </div>}
  </div>
}
