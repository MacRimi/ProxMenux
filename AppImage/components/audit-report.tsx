"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle,
} from "./ui/dialog"
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, ClipboardCheck,
  Loader2, MinusCircle, Play, RotateCcw, ShieldOff, XCircle,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface Finding {
  check_id: string
  area: string
  severity: string
  state: string
  summary_key: string | null
  summary_params: Record<string, string | number>
  affected: Array<Record<string, unknown>>
  evidence: string | null
  remediable_by: string | null
  exception?: { reason: string; accepted_by: string; accepted_at: number } | null
}

interface Run {
  run_id: string
  profile: string
  started_at: number
  finished_at: number | null
  status: string
  checks_total: number
}

// Findings are ordered by how much they demand attention, not by area.
// Someone triaging wants the worst thing first regardless of where it
// lives; grouping by area is the reading order of the printed document.
const STATE_RANK: Record<string, number> = {
  fail: 0, warn: 1, accepted: 2, pass: 3, not_applicable: 4,
}

const STATE_STYLE: Record<string, { chip: string; Icon: typeof XCircle }> = {
  fail: { chip: "bg-red-500/10 text-red-500 border-red-500/20", Icon: XCircle },
  warn: { chip: "bg-amber-500/10 text-amber-500 border-amber-500/20", Icon: AlertTriangle },
  accepted: { chip: "bg-muted text-muted-foreground border-border", Icon: ShieldOff },
  pass: { chip: "bg-green-500/10 text-green-500 border-green-500/20", Icon: CheckCircle2 },
  not_applicable: { chip: "bg-muted text-muted-foreground border-border", Icon: MinusCircle },
}

// An assessment older than this stops describing the current system, so
// the age is surfaced before any count rather than as a footnote.
const STALE_AFTER_DAYS = 30

export function AuditReport() {
  const t = useT()
  const [running, setRunning] = useState(false)
  const [latest, setLatest] = useState<Run | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [summary, setSummary] = useState<Record<string, number>>({})
  const [areaFilter, setAreaFilter] = useState<string>("all")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [showResolved, setShowResolved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [accepting, setAccepting] = useState<Finding | null>(null)
  const [reason, setReason] = useState("")
  const [expiryDays, setExpiryDays] = useState<string>("")
  const [saving, setSaving] = useState(false)

  const loadRun = useCallback(async (runId: string) => {
    try {
      const data: any = await fetchApi(`/api/audit/runs/${runId}`)
      if (data?.success) setFindings(data.findings || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const data: any = await fetchApi("/api/audit/status")
      if (!data?.success) return
      setRunning(Boolean(data.running))
      setSummary(data.summary || {})
      setLatest(data.latest || null)
      if (data.latest?.run_id) await loadRun(data.latest.run_id)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [loadRun])

  useEffect(() => { refresh() }, [refresh])

  // While an assessment is in flight the page polls; once it settles the
  // interval is dropped so an idle tab does not keep waking the backend.
  useEffect(() => {
    if (!running) return
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [running, refresh])

  const startRun = async () => {
    setError(null)
    try {
      const data: any = await fetchApi("/api/audit/run", {
        method: "POST",
        body: JSON.stringify({ profile: "full" }),
      })
      if (data?.success) setRunning(true)
      else setError(data?.message || t("audit.errors.runFailed"))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // Accepting or revoking changes which findings are active, so the run
  // is re-read afterwards rather than patched in place: the stored
  // finding is what the next report will show.
  const submitAcceptance = async () => {
    if (!accepting || !reason.trim()) return
    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        check_id: accepting.check_id,
        reason: reason.trim(),
      }
      if (expiryDays) body.expires_in_days = Number(expiryDays)
      const data: any = await fetchApi("/api/audit/exceptions", {
        method: "POST",
        body: JSON.stringify(body),
      })
      if (!data?.success) throw new Error(data?.message || "")
      setAccepting(null)
      setReason("")
      setExpiryDays("")
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const revokeAcceptance = async (checkId: string) => {
    try {
      await fetchApi(`/api/audit/exceptions/${checkId}`, { method: "DELETE" })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const areas = useMemo(
    () => Array.from(new Set(findings.map((f) => f.area))).sort(),
    [findings],
  )

  const visible = useMemo(() => {
    const quiet = new Set(["pass", "not_applicable"])
    return findings
      .filter((f) => areaFilter === "all" || f.area === areaFilter)
      .filter((f) => showResolved || !quiet.has(f.state))
      .sort((a, b) =>
        (STATE_RANK[a.state] ?? 9) - (STATE_RANK[b.state] ?? 9) ||
        a.check_id.localeCompare(b.check_id))
  }, [findings, areaFilter, showResolved])

  const acceptedCount = summary.accepted || 0
  const ageDays = latest?.finished_at
    ? Math.floor((Date.now() / 1000 - latest.finished_at) / 86400)
    : null
  const stale = ageDays !== null && ageDays >= STALE_AFTER_DAYS

  // The backend stores which sentence applies and its numbers, not the
  // sentence itself, so a finding recorded under one language still reads
  // correctly under another. A check that failed to evaluate has no
  // per-check entry, hence the shared fallback.
  const summaryOf = (f: Finding) => {
    if (!f.summary_key) return ""
    const params = Object.fromEntries(
      Object.entries(f.summary_params || {}).map(([k, v]) => [k, String(v)]),
    )
    const key = `audit.checks.${f.check_id}.summary.${f.summary_key}`
    const text = t(key, params)
    return text === key ? t("audit.summaryFallback") : text
  }

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        {t("audit.loading")}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-xl lg:text-2xl font-bold text-foreground">
              <ClipboardCheck className="h-6 w-6" />
              {t("audit.title")}
            </CardTitle>
            {/* Stated before any count: an assessment nobody has run, or
                one run months ago, does not describe this host today. */}
            {!latest ? (
              <p className="text-sm text-muted-foreground">{t("audit.neverRun")}</p>
            ) : (
              <p className={`text-sm ${stale ? "text-amber-500" : "text-muted-foreground"}`}>
                {t("audit.lastRun", {
                  when: new Date((latest.finished_at || latest.started_at) * 1000)
                    .toLocaleString(),
                })}
                {stale && ` — ${t("audit.stale", { days: String(ageDays) })}`}
              </p>
            )}
            <p className="text-xs text-muted-foreground">{t("audit.readOnlyNotice")}</p>
          </div>

          <Button
            onClick={startRun}
            disabled={running}
            className="shrink-0 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-60"
          >
            {running
              ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />{t("audit.running")}</>
              : <><Play className="h-4 w-4 mr-2" />{t("audit.run")}</>}
          </Button>
        </CardHeader>

        {latest && (
          <CardContent className="pt-0 space-y-3">
            <div className="flex flex-wrap gap-2">
              {(["fail", "warn", "accepted", "pass", "not_applicable"] as const)
                .filter((s) => summary[s])
                .map((s) => {
                  const { chip, Icon } = STATE_STYLE[s]
                  return (
                    <Badge key={s} variant="outline" className={`${chip} gap-1.5`}>
                      <Icon className="h-3.5 w-3.5" />
                      {t(`audit.states.${s}`)}
                      <span className="tabular-nums font-semibold">{summary[s]}</span>
                    </Badge>
                  )
                })}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setAreaFilter("all")}
                className={`px-3 py-1 rounded-md text-sm transition-colors ${
                  areaFilter === "all"
                    ? "bg-blue-500 text-white"
                    : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                }`}
              >
                {t("audit.areas.all")}
              </button>
              {areas.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAreaFilter(a)}
                  className={`px-3 py-1 rounded-md text-sm transition-colors ${
                    areaFilter === a
                      ? "bg-blue-500 text-white"
                      : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                  }`}
                >
                  {t(`audit.areas.${a}`)}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setShowResolved((v) => !v)}
                className="ml-auto text-sm text-muted-foreground hover:text-foreground underline underline-offset-2"
              >
                {showResolved ? t("audit.hidePassing") : t("audit.showPassing")}
              </button>
            </div>

            {/* The count of accepted risks stays visible even when the
                findings themselves are filtered out of the list, so a
                decision to live with something is never silently lost. */}
            {acceptedCount > 0 && (
              <p className="text-xs text-muted-foreground">
                {t("audit.acceptedNotice", { count: String(acceptedCount) })}
              </p>
            )}
          </CardContent>
        )}
      </Card>

      {error && (
        <p className="text-sm text-red-400 px-1">{error}</p>
      )}

      {latest && visible.length === 0 && (
        <Card className="bg-card border-border">
          <CardContent className="py-10 text-center text-muted-foreground">
            {t("audit.noFindings")}
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {visible.map((f) => {
          const { chip, Icon } = STATE_STYLE[f.state] || STATE_STYLE.not_applicable
          const open = expanded.has(f.check_id)
          const muted = f.state === "accepted" || f.state === "not_applicable"
          return (
            <Card
              key={f.check_id}
              className={`bg-card border-border ${muted ? "opacity-70" : ""}`}
            >
              <button
                type="button"
                onClick={() => toggle(f.check_id)}
                aria-expanded={open}
                className="w-full text-left p-4 flex items-start gap-3 hover:bg-background/40 transition-colors rounded-lg"
              >
                {open
                  ? <ChevronDown className="h-4 w-4 mt-1 shrink-0 text-muted-foreground" />
                  : <ChevronRight className="h-4 w-4 mt-1 shrink-0 text-muted-foreground" />}
                <Badge variant="outline" className={`${chip} gap-1.5 shrink-0`}>
                  <Icon className="h-3.5 w-3.5" />
                  {t(`audit.states.${f.state}`)}
                </Badge>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-foreground">
                      {t(`audit.checks.${f.check_id}.title`)}
                    </span>
                    <Badge variant="outline" className="text-xs">
                      {t(`audit.areas.${f.area}`)}
                    </Badge>
                    {f.affected.length > 0 && (
                      <Badge variant="outline" className="text-xs tabular-nums">
                        {t("audit.affectedCount", { count: String(f.affected.length) })}
                      </Badge>
                    )}
                  </div>
                  {f.summary_key && (
                    <p className="text-sm text-muted-foreground mt-1">
                      {summaryOf(f)}
                    </p>
                  )}
                </div>
              </button>

              {open && (
                <CardContent className="pt-0 pl-11 space-y-4">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-1">
                      {t("audit.detail.why")}
                    </p>
                    <p className="text-sm text-foreground">
                      {t(`audit.checks.${f.check_id}.rationale`)}
                    </p>
                  </div>

                  {f.exception && (
                    <div className="rounded-md border border-border bg-background p-3">
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t("audit.detail.acceptedRisk")}
                      </p>
                      <p className="text-sm text-foreground">{f.exception.reason}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {f.exception.accepted_by} ·{" "}
                        {new Date(f.exception.accepted_at * 1000).toLocaleDateString()}
                      </p>
                    </div>
                  )}

                  {f.affected.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t("audit.detail.affected")}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {f.affected.map((o, i) => (
                          <Badge key={i} variant="outline" className="text-xs font-mono">
                            {Object.values(o).filter(Boolean).join(" · ")}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {f.evidence && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground mb-1">
                        {t("audit.detail.evidence")}
                      </p>
                      {/* Wide command output scrolls inside its own box so
                          the page itself never scrolls sideways. */}
                      <pre className="text-xs font-mono bg-background border border-border rounded-md p-3 overflow-x-auto whitespace-pre">
                        {f.evidence}
                      </pre>
                    </div>
                  )}

                  {/* Only an active finding can be accepted, and only an
                      accepted one can be returned to the active set. */}
                  {(f.state === "fail" || f.state === "warn") && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => { setAccepting(f); setReason(""); setExpiryDays("") }}
                    >
                      <ShieldOff className="h-4 w-4 mr-2" />
                      {t("audit.acceptRisk.action")}
                    </Button>
                  )}
                  {f.state === "accepted" && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => revokeAcceptance(f.check_id)}
                    >
                      <RotateCcw className="h-4 w-4 mr-2" />
                      {t("audit.acceptRisk.revoke")}
                    </Button>
                  )}
                </CardContent>
              )}
            </Card>
          )
        })}
      </div>

      <Dialog open={accepting !== null} onOpenChange={(o) => !o && setAccepting(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("audit.acceptRisk.title")}</DialogTitle>
            <DialogDescription>
              {accepting && t(`audit.checks.${accepting.check_id}.title`)}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <label htmlFor="audit-reason" className="text-sm font-medium text-foreground">
                {t("audit.acceptRisk.reasonLabel")}
              </label>
              {/* The reason is required, not encouraged. An acceptance
                  without one cannot be told apart later from having
                  silenced the check. */}
              <p className="text-xs text-muted-foreground mt-0.5 mb-2">
                {t("audit.acceptRisk.reasonHelp")}
              </p>
              <textarea
                id="audit-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                className="w-full rounded-md border border-border bg-background p-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder={t("audit.acceptRisk.reasonPlaceholder")}
              />
            </div>

            <div>
              <label htmlFor="audit-expiry" className="text-sm font-medium text-foreground">
                {t("audit.acceptRisk.expiryLabel")}
              </label>
              <p className="text-xs text-muted-foreground mt-0.5 mb-2">
                {t("audit.acceptRisk.expiryHelp")}
              </p>
              <select
                id="audit-expiry"
                value={expiryDays}
                onChange={(e) => setExpiryDays(e.target.value)}
                className="w-full rounded-md border border-border bg-background p-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">{t("audit.acceptRisk.expiryNever")}</option>
                <option value="90">{t("audit.acceptRisk.expiry90")}</option>
                <option value="180">{t("audit.acceptRisk.expiry180")}</option>
                <option value="365">{t("audit.acceptRisk.expiry365")}</option>
              </select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAccepting(null)}>
              {t("audit.acceptRisk.cancel")}
            </Button>
            <Button
              onClick={submitAcceptance}
              disabled={!reason.trim() || saving}
              className="bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-60"
            >
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t("audit.acceptRisk.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
