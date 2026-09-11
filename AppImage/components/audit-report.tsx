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
  FileText, HelpCircle, Info, Loader2, MinusCircle, Play, RotateCcw,
  ShieldOff, XCircle,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { AuditPolicy } from "./audit-policy"
import { AuditChanges } from "./audit-changes"
import { AuditComparison } from "./audit-comparison"
import { Label } from "./ui/label"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "./ui/select"
import { unreadSources } from "../lib/audit-presentation"
import { openAuditDocument, openReportWindow } from "../lib/audit-document"
import { AuditEvidence } from "./audit-evidence"
import { AuditFindingData } from "./audit-finding-data"
import { affectedDescription, resultBreakdown } from "../lib/audit-presentation"
import { useI18n } from "../lib/i18n/provider"

interface Finding {
  check_id: string
  area: string
  severity: string
  classification: string
  decision?: string
  summary_key: string | null
  summary_params: Record<string, string | number>
  affected: Array<Record<string, unknown>>
  evidence: string | null
  remediable_by: string | null
  incomplete?: boolean
  collected_at?: number
  check_version?: number
  sources?: Array<{ source: string; collected_at: number; error?: string }>
  exception?: { reason: string; accepted_by: string; accepted_at: number; expires_at?: number | null } | null
}

interface Run {
  run_id: string
  profile: string
  started_at: number
  finished_at: number | null
  status: string
  checks_total: number
  checks_expected: number
  error?: string | null
  is_baseline?: number | boolean
  // Recorded by the engine: the sources it read and the declaration it
  // judged against. The document states the latter in its scope.
  metadata?: { policy?: {
    declared?: boolean; guests_declared?: number
    storages_declared?: number; thresholds_declared?: string[]
  } } | null
}

// Findings are ordered by how much they demand attention, not by area.
// Someone triaging wants the worst thing first regardless of where it
// lives; grouping by area is the reading order of the printed document.
//
// One scale, worst first. There is no second ordering by severity any
// more: gravity is the classification, so a finding cannot be a critical
// observation or an informational failure.
const CLASS_RANK: Record<string, number> = {
  critical: 0, warning: 1, observation: 2, unverified: 3,
  accepted: 4, conformant: 5, not_applicable: 6,
}

// Only the first two are problems. An observation is drawn in a neutral
// tone on purpose: colouring planning information like a fault is what
// made ordinary configurations read as defects.
const CLASS_STYLE: Record<string, { chip: string; Icon: typeof XCircle }> = {
  critical: { chip: "bg-red-500/10 text-red-500 border-red-500/20", Icon: XCircle },
  warning: { chip: "bg-amber-500/10 text-amber-500 border-amber-500/20", Icon: AlertTriangle },
  observation: { chip: "bg-blue-500/10 text-blue-400 border-blue-400/20", Icon: Info },
  unverified: { chip: "bg-muted text-muted-foreground border-border", Icon: HelpCircle },
  accepted: { chip: "bg-indigo-500/10 text-indigo-400 border-indigo-400/20", Icon: ShieldOff },
  conformant: { chip: "bg-green-500/10 text-green-500 border-green-500/20", Icon: CheckCircle2 },
  not_applicable: { chip: "bg-muted text-muted-foreground border-border", Icon: MinusCircle },
}

/** What a finding reads as once the reader's decision is applied. */
function shownAs(f: { classification: string; decision?: string }): string {
  return f.decision === "accepted" ? "accepted" : f.classification
}

// An assessment older than this stops describing the current system, so
// the age is surfaced before any count rather than as a footnote.
const STALE_AFTER_DAYS = 30
const SUMMARY_BADGE_CLASS = "h-6 gap-1.5 whitespace-nowrap px-2.5 py-0 text-xs"

export function AuditReport() {
  const t = useT()
  const { language } = useI18n()
  // Assessment and inventory answer different questions and are
  // read differently: one is triaged, the other is read through.
  const [view, setView] = useState<"assessment" | "changes" | "policy">("assessment")
  const [running, setRunning] = useState(false)
  const [latest, setLatest] = useState<Run | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [summary, setSummary] = useState<Record<string, number>>({})
  const [areaFilter, setAreaFilter] = useState<string>("all")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [accepting, setAccepting] = useState<Finding | null>(null)
  const [reason, setReason] = useState("")
  const [expiryDays, setExpiryDays] = useState<string>("")
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState({ completed: 0, total: 0 })
  // The profile decides which question the page answers, so it governs
  // both what an assessment runs and what the inventory documents.
  const [profile, setProfile] = useState("full")
  const [profiles, setProfiles] = useState<Array<{ id: string; runs_checks: boolean; areas: string[] | null; include: string[] }>>([])
  // Set when a Lynis-bearing assessment is about to run and the stored
  // report is missing or stale: the user decides whether to run Lynis now.
  const [lynisPrompt, setLynisPrompt] = useState<null | { ageDays: number | null; stale: boolean }>(null)
  const [building, setBuilding] = useState(false)

  const loadRun = useCallback(async (runId: string) => {
    try {
      const data: any = await fetchApi(`/api/audit/runs/${runId}?effective=1`)
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
      setProgress({ completed: data.progress?.completed || 0, total: data.progress?.total || 0 })
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

  useEffect(() => {
    fetchApi("/api/audit/profiles")
      .then((d: any) => { if (d?.success) setProfiles(d.profiles || []) })
      .catch(() => { /* the page works on the default profile */ })
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Expiry changes a decision, not the assessment. One local timer and
  // a focus refresh keep it current without periodic scans or idle polling.
  useEffect(() => {
    const expiry = findings.flatMap((f) => f.exception?.expires_at ? [f.exception.expires_at] : [])
    if (!expiry.length) return
    const delay = Math.max(100, Math.min(2147483647, Math.min(...expiry) * 1000 - Date.now() + 100))
    const id = setTimeout(refresh, delay)
    return () => clearTimeout(id)
  }, [findings, refresh])
  useEffect(() => {
    const onFocus = () => { void refresh() }
    window.addEventListener("focus", onFocus)
    return () => window.removeEventListener("focus", onFocus)
  }, [refresh])

  // While an assessment is in flight the page polls; once it settles the
  // interval is dropped so an idle tab does not keep waking the backend.
  useEffect(() => {
    if (!running) return
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [running, refresh])

  const doRun = async (runLynis: boolean) => {
    setLynisPrompt(null)
    setError(null)
    try {
      const data: any = await fetchApi("/api/audit/run", {
        method: "POST",
        body: JSON.stringify({ profile, run_lynis: runLynis }),
      })
      if (data?.success) setRunning(true)
      else setError(data?.message || t("audit.errors.runFailed"))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // A profile that includes the Lynis check asks the user before running,
  // since producing a fresh Lynis report takes a few minutes. When a
  // recent report already exists — or Lynis is not installed — the run
  // starts straight away and reuses it.
  const startRun = async () => {
    setError(null)
    const spec = profiles.find((p) => p.id === profile)
    const runsLynis = !!spec && (spec.areas === null || spec.areas.includes("security"))
    if (runsLynis) {
      try {
        const r: any = await fetchApi("/api/audit/lynis-readiness")
        if (r?.success && r.installed && (!r.has_report || r.stale)) {
          setLynisPrompt({ ageDays: r.age_days ?? null, stale: !!r.stale })
          return
        }
      } catch {
        /* Readiness is advisory; on failure run without Lynis rather than block. */
      }
    }
    doRun(false)
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
        run_id: latest?.run_id,
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

  // Every check is listed, worst first. Hiding what passed made the
  // reader guess whether a check was clean or had not run, which is
  // exactly the distinction this page exists to keep.
  const visible = useMemo(() =>
    findings
      .filter((f) => areaFilter === "all" || f.area === areaFilter)
      .sort((a, b) =>
        (CLASS_RANK[shownAs(a)] ?? 9) - (CLASS_RANK[shownAs(b)] ?? 9) ||
        a.check_id.localeCompare(b.check_id)),
    [findings, areaFilter])

  const acceptedCount = summary.accepted || 0
  const unverifiedChecks = findings.filter(
    (f) => f.classification === "unverified" || f.incomplete)
  const ageDays = latest?.finished_at
    ? Math.floor((Date.now() / 1000 - latest.finished_at) / 86400)
    : null
  const stale = ageDays !== null && ageDays >= STALE_AFTER_DAYS

  // The backend stores which sentence applies and its numbers, not the
  // sentence itself, so a finding recorded under one language still reads
  // correctly under another. A check that failed to evaluate has no
  // per-check entry, hence the shared fallback.
  const summaryOf = (f: Finding) => {
    if (f.check_id === "backup.last_backup_age" && f.affected.length) return resultBreakdown(f, t)
    if (!f.summary_key) return ""
    const params = Object.fromEntries(
      Object.entries(f.summary_params || {}).map(([k, v]) => [k, String(v)]),
    )
    const key = `audit.checks.${f.check_id}.summary.${f.summary_key}`
    const text = t(key, params)
    return text === key ? t("audit.summaryFallback") : text
  }

  const notApplicableText = (f: Finding) => {
    if (f.summary_key) return ""
    return f.classification === "not_applicable" ? t("audit.notApplicableScope") : ""
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

  // The document carries both halves, so the inventory is fetched at the
  // moment it is produced rather than kept in memory for a button that
  // may never be pressed.
  const generateDocument = async () => {
    // The window is opened on the click itself, before the inventory is
    // fetched, so the popup blocker sees the user gesture. It shows a
    // spinner while the document is composed.
    const target = openReportWindow(t("audit.document.building"))
    setBuilding(true)
    try {
      const inv: any = await fetchApi(
        `/api/audit/inventory?profile=${encodeURIComponent(profile)}`)
      // A focused report shows only the checks its profile runs, even
      // when the findings on screen came from a full assessment: the
      // report is scoped to its question, not to whichever run produced
      // the data. `areas: null` (full, diagnostic) keeps everything.
      const spec = profiles.find((p) => p.id === profile)
      const scopedFindings = !spec || spec.areas === null
        ? findings
        : findings.filter((f) => spec.areas!.includes(f.area) || spec.include.includes(f.check_id))
      openAuditDocument({
        profile,
        run: latest,
        findings: scopedFindings,
        inventory: inv?.success ? inv.inventory : null,
        t,
        locale: language,
      }, target)
    } catch (e) {
      target?.close()
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBuilding(false)
    }
  }

  const documentButton = (
    <Button
      variant="outline"
      size="sm"
      onClick={generateDocument}
      disabled={building}
      // Related to running an assessment, and secondary to it: the same
      // hue as that button, at the translucent weight the chips use.
      // Green is taken — here it means a conformant result, and this
      // report may be full of critical ones.
      className="shrink-0 border-blue-500/20 bg-blue-500/10 text-blue-500
                 hover:bg-blue-500/20 hover:text-blue-500"
    >
      {building
        ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
        : <FileText className="h-4 w-4 mr-2" />}
      {/* The icon carries the meaning where the width is short. */}
      <span className="sm:hidden">{t("audit.document.actionShort")}</span>
      <span className="hidden sm:inline">{t("audit.document.action")}</span>
    </Button>
  )

  const profilePicker = profiles.length > 0 ? (
    <div className="flex min-w-0 flex-1 items-center gap-2 text-sm sm:w-auto sm:flex-none">
      <Label htmlFor="audit-profile" className="hidden shrink-0 text-muted-foreground sm:inline">
        {t("audit.profile.label")}
      </Label>
      <Select value={profile} onValueChange={setProfile}>
        <SelectTrigger id="audit-profile" className="min-w-0 flex-1 sm:w-56 sm:flex-none">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {profiles.map((p) => (
            <SelectItem key={p.id} value={p.id}>{t(`audit.profile.${p.id}`)}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  ) : null

  const viewTabs = (
    <div
      role="group"
      aria-label={t("audit.viewSwitch.ariaLabel")}
      className="flex w-full rounded-lg border border-border bg-muted/40 p-1 gap-1
                 sm:inline-flex sm:w-auto"
    >
      {(["assessment", "changes", "policy"] as const).map((key) => (
        <button
          key={key}
          type="button"
          aria-pressed={view === key}
          onClick={() => setView(key)}
          className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors sm:flex-none ${
            view === key
              ? "bg-blue-500 text-white shadow-sm"
              : "text-muted-foreground hover:text-foreground hover:bg-background/60"
          }`}
        >
          {t(`audit.viewSwitch.${key}`)}
        </button>
      ))}
    </div>
  )

  // Changes and policy carry no profile: one is what was done to this
  // host, the other what is expected of it, and neither narrows by report.
  if (view === "changes") {
    return (
      <div className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-6 w-6 shrink-0 text-foreground" />
            <h2 className="text-xl lg:text-2xl font-bold text-foreground">{t("audit.title")}</h2>
          </div>
          <div className="flex flex-col gap-2 sm:ml-auto sm:flex-row sm:flex-wrap
                          sm:items-center sm:gap-3">
            {viewTabs}
          </div>
        </div>
        <AuditChanges />
      </div>
    )
  }

  if (view === "policy") {
    return (
      <div className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-6 w-6 shrink-0 text-foreground" />
            <h2 className="text-xl lg:text-2xl font-bold text-foreground">{t("audit.title")}</h2>
          </div>
          <div className="flex flex-col gap-2 sm:ml-auto sm:flex-row sm:flex-wrap
                          sm:items-center sm:gap-3">
            {viewTabs}
          </div>
        </div>
        <AuditPolicy />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="h-6 w-6 shrink-0 text-foreground" />
          <h2 className="text-xl lg:text-2xl font-bold text-foreground">{t("audit.title")}</h2>
        </div>
        <div className="flex flex-col gap-2 sm:ml-auto sm:flex-row sm:flex-wrap
                        sm:items-center sm:gap-3">
          <div className="flex items-center gap-2 sm:contents">
            {profilePicker}{documentButton}
          </div>
          {viewTabs}
        </div>
      </div>
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
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
            {running && <p role="status" className="text-sm text-muted-foreground">
              {t("audit.progress", { completed: String(progress.completed), total: String(progress.total) })}
            </p>}
            {/* A reading that could not be taken is information, not an
                alarm: it says the report is narrower than usual, and
                colouring it like a finding puts it above warnings the
                reader has to act on. A run that failed outright is the
                one thing here that does interrupt. */}
            {latest && (latest.status === "partial" || latest.status === "failed") && (
              <div
                {...(latest.status === "failed" ? { role: "alert" as const } : {})}
                className={`space-y-1 text-sm ${
                  latest.status === "failed" ? "text-amber-500" : "text-muted-foreground"
                }`}
              >
                <p>{t(`audit.runStates.${latest.status}`)}</p>
                {unverifiedChecks.length > 0 && <p className="text-xs">
                  {t("audit.unverifiedChecks", { checks: unverifiedChecks
                    .map((f) => t(`audit.checks.${f.check_id}.title`)).join(" · ") })}
                </p>}
              </div>
            )}
            {latest?.error && <p className="text-xs text-amber-500">{latest.error}</p>}
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
            {/* One row of counters on one scale. Gravity is the
                classification itself, so there is nothing left to
                reconcile between two sets of numbers. */}
            <div role="group" aria-label={t("audit.results")}
                 className="flex max-w-full flex-wrap items-center gap-2">
              {(["critical", "warning", "observation", "unverified",
                 "accepted", "conformant", "not_applicable"] as const)
                .filter((c) => summary[c])
                .map((c) => {
                  const { chip, Icon } = CLASS_STYLE[c]
                  return (
                    <Badge key={c} variant="outline" className={`${SUMMARY_BADGE_CLASS} ${chip}`}>
                      <Icon className="h-3.5 w-3.5" />
                      {t(`audit.classifications.${c}`)}
                      <span className="tabular-nums font-semibold">{summary[c]}</span>
                    </Badge>
                  )
                })}
            </div>

            {/* What changed since a reference run: context for the
                assessment being read, not a place of its own. */}
            <AuditComparison
              runId={latest.run_id}
              isBaseline={Boolean(latest.is_baseline)}
              onBaselineSet={refresh}
            />

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
          const shown = shownAs(f)
          const { chip, Icon } = CLASS_STYLE[shown] || CLASS_STYLE.not_applicable
          const open = expanded.has(f.check_id)
          const muted = shown === "accepted" || shown === "not_applicable"
          return (
            <Card
              key={f.check_id}
              className={`bg-card border-border ${muted ? "opacity-70" : ""}`}
            >
              <button
                type="button"
                onClick={() => toggle(f.check_id)}
                aria-expanded={open}
                className="w-full text-left p-4 flex items-start gap-3 rounded-lg hover:bg-white/5 transition-colors cursor-pointer"
              >
                {open
                  ? <ChevronDown className="h-4 w-4 mt-1 shrink-0 text-muted-foreground" />
                  : <ChevronRight className="h-4 w-4 mt-1 shrink-0 text-muted-foreground" />}
                <Badge variant="outline" className={`${chip} gap-1.5 shrink-0`}>
                  <Icon className="h-3.5 w-3.5" />
                  {t(`audit.classifications.${shown}`)}
                </Badge>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-foreground">
                      {t(`audit.checks.${f.check_id}.title`)}
                    </span>
                    <Badge variant="outline" className="text-xs">
                      {t(`audit.areas.${f.area}`)}
                    </Badge>
                    {f.incomplete && <Badge variant="outline" className="text-xs text-amber-500">
                      {t("audit.incomplete")}
                    </Badge>}
                    {f.affected.length > 0 && (
                      <Badge variant="outline" className="text-xs tabular-nums">
                        {affectedDescription(f, t)}
                      </Badge>
                    )}
                  </div>

                  {(f.summary_key || notApplicableText(f)) && (
                    <p className="text-sm text-muted-foreground mt-1">
                      {f.summary_key ? summaryOf(f) : notApplicableText(f)}
                    </p>
                  )}
                  {/* "Could not be evaluated" describes the assessment, not
                      the host. What could not be read is recorded against
                      each source, and belongs here rather than two
                      collapsed panels below. */}
                  {unreadSources(f.sources, t) && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {unreadSources(f.sources, t)}
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
                        {f.exception.expires_at && <> · {t("audit.expires", {
                          when: new Date(f.exception.expires_at * 1000).toLocaleString(),
                        })}</>}
                      </p>
                    </div>
                  )}

                  {/* Some checks carry a useful, structured positive reading
                      in their evidence even when nothing is affected. The
                      presenter returns no groups for checks without such a
                      view, so rendering it unconditionally does not create
                      empty space. */}
                  <AuditFindingData finding={f} t={t} locale={language} />

                  {f.evidence && (
                    <details className="text-sm">
                      <summary className="cursor-pointer text-muted-foreground mb-2">
                        {t("audit.presentation.technical")}
                      </summary>
                      <AuditEvidence evidence={f.evidence} locale={language} />
                    </details>
                  )}
                  {f.sources && f.sources.length > 0 && <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer">{t("audit.detail.sources")}</summary>
                    <ul className="mt-2 space-y-1">
                      {f.sources.map((source) => <li key={source.source} className="break-all">
                        {source.source} · {new Date(source.collected_at * 1000).toLocaleString()}
                        {source.error && <span className="text-amber-500"> · {source.error}</span>}
                      </li>)}
                    </ul>
                  </details>}

                  {/* Only an active finding can be accepted, and only an
                      accepted one can be returned to the active set. */}
                  {(f.classification === "critical" || f.classification === "warning")
                    && !f.decision && !f.incomplete && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => { setAccepting(f); setReason(""); setExpiryDays("") }}
                    >
                      <ShieldOff className="h-4 w-4 mr-2" />
                      {t("audit.acceptRisk.action")}
                    </Button>
                  )}
                  {f.decision === "accepted" && (
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

      <Dialog open={lynisPrompt !== null} onOpenChange={(o) => !o && setLynisPrompt(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("audit.lynis.title")}</DialogTitle>
            <DialogDescription>
              {lynisPrompt?.stale
                ? t("audit.lynis.bodyStale", { days: String(lynisPrompt?.ageDays ?? "") })
                : t("audit.lynis.bodyNotRun")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="outline" onClick={() => setLynisPrompt(null)}>
              {t("audit.lynis.cancel")}
            </Button>
            <Button variant="outline" onClick={() => doRun(false)}>
              {t("audit.lynis.withoutLynis")}
            </Button>
            <Button onClick={() => doRun(true)}>
              {t("audit.lynis.withLynis")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
              <Select value={expiryDays || "none"}
                      onValueChange={(v) => setExpiryDays(v === "none" ? "" : v)}>
                <SelectTrigger id="audit-expiry" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                    <SelectItem value="none">{t("audit.acceptRisk.expiryNever")}</SelectItem>
                    <SelectItem value="90">{t("audit.acceptRisk.expiry90")}</SelectItem>
                    <SelectItem value="180">{t("audit.acceptRisk.expiry180")}</SelectItem>
                    <SelectItem value="365">{t("audit.acceptRisk.expiry365")}</SelectItem>
                </SelectContent>
              </Select>
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
