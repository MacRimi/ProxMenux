"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import {
  ChevronDown, ChevronRight, FileCode, HelpCircle, Loader2, Package,
  Play, Settings2,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT, useI18n } from "../lib/i18n/provider"

/**
 * What ProxMenux changed on this host.
 *
 * The complaint this answers is not that the tool changes things: it is
 * that afterwards nobody can say what it changed. Showing the script
 * does not answer it either — a function of four hundred lines may alter
 * two values, and the reader cannot tell which two. So what is shown
 * here is the difference and nothing else.
 *
 * Two distinctions are kept in front of the reader, because both bear on
 * what they can do about what they are looking at: whether ProxMenux
 * authored the change or merely ran something the user asked for, and
 * how much of the previous state is actually known.
 */

interface Change {
  id: number
  recorded_at: number
  class: string
  operation: string
  source: string
  function: string
  function_version: string
  target: string
  before_ref: string
  after_ref: string
  capture: string
  revert: string
  exactness: string
  result: string
  recoverable: boolean
  detail: Record<string, unknown>
  diff?: {
    available: boolean; reason?: string
    added?: number; removed?: number; truncated?: boolean; hunks?: string[]
  } | null
}

interface Summary {
  total: number
  by_class: Record<string, number>
  functions: Array<{
    function: string; source: string; version: string
    changes: number; last_change: number; first_change: number
  }>
  journal_started: number | null
}

const CLASS_STYLE: Record<string, { chip: string; Icon: typeof Settings2 }> = {
  configuration: { chip: "bg-blue-500/10 text-blue-400 border-blue-400/20", Icon: Settings2 },
  installation: { chip: "bg-green-500/10 text-green-500 border-green-500/20", Icon: Package },
  execution: { chip: "bg-muted text-muted-foreground border-border", Icon: Play },
  registration: { chip: "bg-muted text-muted-foreground border-border", Icon: HelpCircle },
}

export function AuditChanges() {
  const t = useT()
  const { language } = useI18n()
  const [changes, setChanges] = useState<Change[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [filter, setFilter] = useState<string>("all")

  const load = useCallback(async () => {
    try {
      const res: any = await fetchApi("/api/audit/changes?limit=500")
      if (res?.success) {
        setChanges(res.changes || [])
        setSummary(res.summary || null)
        setError(null)
      } else {
        setError(res?.message || t("audit.changes.failed"))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])

  const toggle = (id: number) => setOpen((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const visible = useMemo(
    () => changes.filter((c) => filter === "all" || c.class === filter),
    [changes, filter],
  )

  const when = (epoch: number) => new Date(epoch * 1000).toLocaleString(language)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />{t("audit.changes.loading")}
      </div>
    )
  }
  if (error) return <p className="text-sm text-red-400 px-1">{error}</p>

  return (
    <div className="space-y-4">
      <Card className="bg-card border-border">
        <CardContent className="py-4 space-y-3">
          <p className="text-sm text-muted-foreground">{t("audit.changes.intro")}</p>
          {/* A host with nothing recorded should say why, rather than
              looking like a host nothing has touched. */}
          {summary && summary.total === 0 && (
            <p className="text-sm text-muted-foreground">{t("audit.changes.empty")}</p>
          )}
          {summary && summary.journal_started && (
            <p className="text-xs text-muted-foreground">
              {t("audit.changes.since", { date: when(summary.journal_started) })}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {(["all", "configuration", "installation", "execution", "registration"] as const)
              .filter((key) => key === "all" || summary?.by_class?.[key])
              .map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setFilter(key)}
                  className={`px-3 py-1 rounded-md text-sm transition-colors ${
                    filter === key
                      ? "bg-blue-500 text-white"
                      : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                  }`}
                >
                  {t(`audit.changes.class.${key}`)}
                  {key !== "all" && summary?.by_class?.[key] !== undefined && (
                    <span className="ml-1.5 tabular-nums">{summary.by_class[key]}</span>
                  )}
                </button>
              ))}
          </div>
        </CardContent>
      </Card>

      {summary && summary.functions.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <FileCode className="h-4 w-4" />{t("audit.changes.byFunction")}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 space-y-2">
            {summary.functions.map((fn) => (
              <button
                key={fn.function}
                type="button"
                onClick={() => setFilter("all")}
                className="flex w-full flex-wrap items-center gap-2 rounded-md border
                           border-border p-2.5 text-left hover:bg-white/5
                           transition-colors cursor-pointer"
              >
                <span className="font-mono text-sm text-foreground">{fn.function}</span>
                {fn.version && (
                  <Badge variant="outline" className="text-xs">v{fn.version}</Badge>
                )}
                <Badge variant="outline" className="text-xs tabular-nums">
                  {t("audit.changes.count", { count: String(fn.changes) })}
                </Badge>
                <span className="ml-auto text-xs text-muted-foreground">
                  {when(fn.last_change)}
                </span>
              </button>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {visible.map((change) => {
          const style = CLASS_STYLE[change.class] || CLASS_STYLE.registration
          const Icon = style.Icon
          const expanded = open.has(change.id)
          const installed = String(change.detail?.installed || "")
          return (
            <Card key={change.id} className="bg-card border-border">
              <button
                type="button"
                onClick={() => toggle(change.id)}
                aria-expanded={expanded}
                className="w-full text-left p-3 flex flex-wrap items-center gap-2
                           rounded-lg hover:bg-white/5 transition-colors cursor-pointer"
              >
                {expanded
                  ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
                <Badge variant="outline" className={`${style.chip} gap-1.5 shrink-0`}>
                  <Icon className="h-3.5 w-3.5" />
                  {t(`audit.changes.operation.${change.operation}`)}
                </Badge>
                <span className="min-w-0 font-mono text-sm text-foreground break-all">
                  {change.target}
                </span>
                {change.diff?.available && (
                  <Badge variant="outline" className="text-xs tabular-nums shrink-0">
                    +{change.diff.added} −{change.diff.removed}
                  </Badge>
                )}
                {/* Whether the previous state is known is what decides
                    if undoing this is even discussable. */}
                {change.capture === "unknown" && (
                  <Badge variant="outline" className="text-xs shrink-0">
                    {t("audit.changes.capture.unknown")}
                  </Badge>
                )}
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                  {when(change.recorded_at)}
                </span>
              </button>

              {expanded && (
                <CardContent className="pt-0 pl-10 space-y-3">
                  <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                    <span>{t("audit.changes.function")}:{" "}
                      <span className="font-mono text-foreground">{change.function || "—"}</span>
                      {change.function_version && ` v${change.function_version}`}
                    </span>
                    <span>{t("audit.changes.source")}:{" "}
                      <span className="font-mono">{change.source || "—"}</span></span>
                    <span>{t("audit.changes.reversibility")}:{" "}
                      {t(`audit.changes.exactness.${change.exactness}`)}</span>
                  </div>

                  {installed && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t("audit.changes.packagesAdded")}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {installed.split(/\s+/).filter(Boolean).map((pkg) => (
                          <Badge key={pkg} variant="outline" className="font-mono text-xs">
                            {pkg}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {change.class === "execution" && Boolean(change.detail?.command) && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t("audit.changes.commandRun")}
                      </p>
                      <pre className="text-xs font-mono bg-background border border-border
                                      rounded-md p-2.5 overflow-x-auto">
                        {String(change.detail.command)}
                      </pre>
                      <p className="text-xs text-muted-foreground mt-1">
                        {t("audit.changes.executionNote")}
                      </p>
                    </div>
                  )}

                  {change.diff && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t("audit.changes.difference")}
                      </p>
                      {change.diff.available ? (
                        <>
                          <pre className="text-xs font-mono bg-background border border-border
                                          rounded-md p-2.5 overflow-x-auto">
                            {(change.diff.hunks || []).map((line: string, i: number) => (
                              <div key={i} className={
                                line.startsWith("+") ? "text-green-500"
                                : line.startsWith("-") ? "text-red-400"
                                : line.startsWith("@@") ? "text-blue-400" : ""
                              }>{line}</div>
                            ))}
                          </pre>
                          {change.diff.truncated && (
                            <p className="text-xs text-muted-foreground mt-1">
                              {t("audit.changes.diffTruncated")}
                            </p>
                          )}
                        </>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          {t("audit.changes.diffUnavailable")}
                        </p>
                      )}
                    </div>
                  )}

                  {change.capture === "unknown" && (
                    <p className="text-xs text-muted-foreground">
                      {t("audit.changes.unknownNote")}
                    </p>
                  )}
                </CardContent>
              )}
            </Card>
          )
        })}
        {visible.length === 0 && summary && summary.total > 0 && (
          <p className="text-sm text-muted-foreground px-1">{t("audit.changes.noneInFilter")}</p>
        )}
      </div>
    </div>
  )
}
