"use client"

import { useCallback, useEffect, useState } from "react"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import {
  ChevronDown, ChevronRight, Flag, Loader2, MinusCircle,
  PlusCircle, ShieldOff, TrendingUp,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT, useI18n } from "../lib/i18n/provider"

/**
 * How this assessment differs from an earlier one.
 *
 * A single run says what the host is like now. It cannot say whether
 * that is better or worse than last week, which is the question anyone
 * maintaining a machine actually asks — and the one that turns an audit
 * from a snapshot into a record.
 *
 * The distinction the engine draws and this view keeps: a finding that
 * stopped being reported because the host was fixed is not the same as
 * one that stopped because somebody accepted it. Both leave the list;
 * only the first is progress, and merging them would tell the reader a
 * problem went away when the decision was to live with it.
 *
 * It sits inside the assessment rather than in a view of its own,
 * because "what changed since last time" is context for the run being
 * read, not a separate place to visit.
 */

interface Finding {
  check_id: string
  area: string
  classification: string
}

interface Comparison {
  from: string
  to: string
  new: Finding[]
  resolved: Finding[]
  accepted: Finding[]
  unchanged: Finding[]
  retired: Finding[]
  unverified: Finding[]
}

const GROUPS = [
  { key: "new", Icon: PlusCircle, tone: "text-amber-500" },
  { key: "resolved", Icon: MinusCircle, tone: "text-green-500" },
  { key: "accepted", Icon: ShieldOff, tone: "text-indigo-400" },
  { key: "retired", Icon: Flag, tone: "text-muted-foreground" },
] as const

export function AuditComparison({ runId, isBaseline, onBaselineSet }: {
  runId: string
  isBaseline: boolean
  onBaselineSet: () => void
}) {
  const t = useT()
  const { language } = useI18n()
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [baseline, setBaseline] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // fetchApi turns a non-2xx response into an Error whose message is the
  // backend's own English prose and whose `body` carries the parsed
  // payload. Both paths therefore go through here: only the reason code
  // crosses into a view that exists in eight languages.
  const reason = (source: any): string => {
    const code = String(source?.reason ?? source?.body?.reason ?? "")
    const key = `audit.comparison.reasons.${code}`
    const translated = t(key)
    return translated !== key ? translated : t("audit.comparison.failed")
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      // Asked for separately: a host with a single run answers the
      // comparison with an error, and inside a Promise.all that error
      // takes the status with it — leaving no way to tell a first
      // assessment from a comparison that genuinely failed, which is
      // how "two runs are required" reached a reader who had simply
      // never chosen a reference.
      const status: any = await fetchApi("/api/audit/status").catch(() => null)
      setBaseline(status?.baseline || null)

      // With no reference chosen there is nothing to compare against,
      // and asking anyway answered 400 — an error in the browser console
      // for the ordinary state of a host assessed for the first time.
      let diff: any = null
      let failure: unknown = null
      if (status?.baseline) {
        try {
          diff = await fetchApi(`/api/audit/compare?to=${encodeURIComponent(runId)}`)
        } catch (e) {
          failure = e
        }
      }
      setComparison(diff?.success ? diff : null)
      // Having no reference run yet is the ordinary state of a host
      // assessed for the first time, and the view already says so.
      const failed = failure ?? (diff?.success === false ? diff : null)
      setError(failed && status?.baseline ? reason(failed) : null)
    } finally {
      setLoading(false)
    }
  }, [runId])

  useEffect(() => { load() }, [load])

  const markBaseline = async () => {
    setSaving(true)
    try {
      const res: any = await fetchApi("/api/audit/baseline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId }),
      })
      if (res?.success) { onBaselineSet(); await load() }
      else setError(reason(res))
    } catch (e) {
      setError(reason(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("audit.comparison.loading")}
      </p>
    )
  }

  const counts = comparison
    ? GROUPS.map((g) => ({ ...g, n: (comparison[g.key] || []).length }))
        .filter((g) => g.n > 0)
    : []
  const comparable = comparison && comparison.from !== comparison.to

  return (
    <div className="space-y-2">
      {error && <p className="text-xs text-red-400">{error}</p>}

      {!comparable ? (
        <p className="text-xs text-muted-foreground">
          {baseline ? t("audit.comparison.isBaseline") : t("audit.comparison.noBaseline")}
        </p>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex w-full flex-wrap items-center gap-2 rounded-md -mx-2 px-2 py-1
                       text-left hover:bg-white/5 transition-colors cursor-pointer"
          >
            {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
            <TrendingUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">
              {t("audit.comparison.since", {
                date: baseline?.started_at
                  ? new Date(baseline.started_at * 1000).toLocaleDateString(language)
                  : t("audit.comparison.previousRun"),
              })}
            </span>
            {counts.length === 0 ? (
              <Badge variant="outline" className="text-xs">
                {t("audit.comparison.noChange")}
              </Badge>
            ) : counts.map(({ key, Icon, tone, n }) => (
              <Badge key={key} variant="outline" className={`text-xs gap-1.5 ${tone}`}>
                <Icon className="h-3 w-3" />
                {t(`audit.comparison.${key}`)}
                <span className="tabular-nums font-semibold">{n}</span>
              </Badge>
            ))}
          </button>

          {open && (
            <div className="space-y-3 pl-6">
              {GROUPS.filter((g) => (comparison[g.key] || []).length > 0).map(
                ({ key, Icon, tone }) => (
                  <div key={key}>
                    <p className={`flex items-center gap-1.5 text-xs font-medium mb-1 ${tone}`}>
                      <Icon className="h-3.5 w-3.5" />
                      {t(`audit.comparison.${key}`)}
                      <span className="font-normal text-muted-foreground">
                        — {t(`audit.comparison.${key}Note`)}
                      </span>
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {(comparison[key] || []).map((f) => (
                        <Badge key={f.check_id} variant="outline" className="text-xs">
                          {t(`audit.checks.${f.check_id}.title`)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ),
              )}
              {(comparison.unchanged || []).length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {t("audit.comparison.unchanged", {
                    count: String(comparison.unchanged.length),
                  })}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {/* Choosing a reference is what makes every later run comparable,
          so the action lives beside the comparison it enables. */}
      {!isBaseline && (
        <Button
          variant="outline"
          size="sm"
          onClick={markBaseline}
          disabled={saving}
          className="h-7 text-xs"
        >
          {saving
            ? <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
            : <Flag className="h-3 w-3 mr-1.5" />}
          {t("audit.comparison.setBaseline")}
        </Button>
      )}
    </div>
  )
}
