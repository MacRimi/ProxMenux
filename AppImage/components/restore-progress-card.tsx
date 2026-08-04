"use client"

// Live inline card + detail modal for the post-boot restore.
//
// apply_cluster_postboot.sh writes /var/lib/proxmenux/restore-state.json
// as it works through the milestones (apply cluster config, initramfs,
// grub, per-component reinstalls, sanity check, finalize). The Flask
// endpoints /api/host-backups/restore/{status,dismiss,history,log}
// expose that state to this component. While the restore is running we
// poll every 2s; once it's terminal (complete|failed) we back off to
// 30s so the card can still be re-opened as a summary. Once the
// operator hits Dismiss the card collapses and the History button
// keeps the run browsable.

import { useMemo, useState } from "react"
import useSWR from "swr"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "./ui/dialog"
import { ScrollArea } from "./ui/scroll-area"
import {
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  History,
  RotateCcw,
  ChevronRight,
  Cpu,
  FileText,
  ArrowDownAZ,
  Filter,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

// ── Shape contracts with the backend ──────────────────────────

interface RestoreComponent {
  name: string
  status: "installing" | "ok" | "failed"
  log: string
  exit_code?: string
}

interface RestoreSummary {
  hostname: string
  guests: string
  stubs: string
  stale_nodes: string
  components: string
  duration: string
}

interface RestoreRollback {
  vms_to_remove?: string[]
  lxcs_to_remove?: string[]
  components_to_uninstall?: string[]
}

interface DataPoolsImport {
  ok: string[]
  forced: string[]
  partial: string[]
  missing: string[]
  failed: string[]
  finished_at?: string
  log_path?: string
}

interface RestoreState {
  status: "running" | "complete" | "failed"
  started_at: string
  finished_at: string | null
  current_step: string
  steps_done: number
  steps_total: number
  log_path: string
  components: RestoreComponent[]
  rollback_delta: RestoreRollback
  sanity_warnings: string[]
  summary: RestoreSummary | null
  acknowledged: boolean
  duration?: string
  data_pools_import?: DataPoolsImport
}

interface HistoryEntry {
  file: string
  mtime: number
  status: string
  started_at: string | null
  finished_at: string | null
  duration: string | null
}

const fetcher = (url: string) => fetchApi(url)

const COMPONENT_LABEL: Record<string, string> = {
  nvidia_driver: "NVIDIA driver",
  amdgpu_top: "amdgpu_top",
  intel_gpu_tools: "Intel GPU tools",
  coral_driver: "Google Coral TPU driver",
}

const formatComponent = (name: string) => COMPONENT_LABEL[name] ?? name

const formatIso = (iso: string | null | undefined) => {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

type Translator = ReturnType<typeof useT>

const formatRelative = (iso: string, t: Translator) => {
  try {
    const then = new Date(iso).getTime()
    const now = Date.now()
    const diff = Math.max(0, Math.round((now - then) / 1000))
    if (diff < 60) return t("restoreProgress.time.secondsAgo", { count: diff })
    if (diff < 3600) return t("restoreProgress.time.minutesAgo", { count: Math.round(diff / 60) })
    if (diff < 86400) return t("restoreProgress.time.hoursAgo", { count: Math.round(diff / 3600) })
    return t("restoreProgress.time.daysAgo", { count: Math.round(diff / 86400) })
  } catch {
    return iso
  }
}

// Rough time-remaining estimate derived from steps_done + elapsed.
// Best-effort: at step 0 there's no data yet, so it returns
// "estimating time…". After the run is terminal, "—". The output is
// a full phrase so the caller doesn't have to add suffix words that
// only make sense on some branches.
const computeEta = (state: RestoreState, t: Translator): string => {
  if (state.status !== "running") return "—"
  if (!state.steps_done || state.steps_done <= 0) return t("restoreProgress.time.estimating")
  const elapsedSec = Math.max(1, Math.round((Date.now() - new Date(state.started_at).getTime()) / 1000))
  const perStep = elapsedSec / state.steps_done
  const remaining = Math.max(0, state.steps_total - state.steps_done)
  const eta = Math.round(perStep * remaining)
  if (eta < 60) return t("restoreProgress.time.secondsLeft", { count: eta })
  if (eta < 3600) return t("restoreProgress.time.minutesLeft", { count: Math.round(eta / 60) })
  return t("restoreProgress.time.hoursLeft", { count: Math.round(eta / 3600) })
}

// ── Small building blocks ─────────────────────────────────────

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const t = useT()
  if (status === "running")
    return (
      <Badge className="bg-blue-500/10 border-blue-500/40 text-blue-300 gap-1">
        <Loader2 className="h-3 w-3 animate-spin" />
        {t("restoreProgress.status.running")}
      </Badge>
    )
  if (status === "complete")
    return (
      <Badge className="bg-emerald-500/10 border-emerald-500/40 text-emerald-400 gap-1">
        <CheckCircle2 className="h-3 w-3" />
        {t("restoreProgress.status.complete")}
      </Badge>
    )
  if (status === "failed")
    return (
      <Badge className="bg-red-500/10 border-red-500/40 text-red-400 gap-1">
        <XCircle className="h-3 w-3" />
        {t("restoreProgress.status.failed")}
      </Badge>
    )
  return <Badge variant="outline">{status}</Badge>
}

const ComponentStatusIcon: React.FC<{ status: string }> = ({ status }) => {
  if (status === "installing")
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />
  if (status === "ok")
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
  return <XCircle className="h-3.5 w-3.5 text-red-400" />
}

// ── Log viewer ────────────────────────────────────────────────

const LogViewer: React.FC<{ path: string | null; historyOnly?: boolean }> = ({ path, historyOnly }) => {
  const t = useT()
  const [filter, setFilter] = useState<"all" | "issues">("all")
  const swrKey = path
    ? `/api/host-backups/restore/log?filter=${filter}&tail=600${historyOnly ? `&path=${encodeURIComponent(path)}` : ""}`
    : null
  const { data, isLoading } = useSWR<{ lines: string[]; total_lines: number; path: string | null }>(
    swrKey,
    fetcher,
    { refreshInterval: historyOnly ? 0 : 4000 },
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1 text-muted-foreground">
          <FileText className="h-3.5 w-3.5" />
          {path ?? t("restoreProgress.log.noLog")}
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant={filter === "all" ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => setFilter("all")}
          >
            <ArrowDownAZ className="h-3 w-3 mr-1" />
            {t("restoreProgress.log.full")}
          </Button>
          <Button
            size="sm"
            variant={filter === "issues" ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => setFilter("issues")}
          >
            <Filter className="h-3 w-3 mr-1" />
            {t("restoreProgress.log.issuesOnly")}
          </Button>
        </div>
      </div>
      <ScrollArea className="h-72 rounded-md border border-border bg-black/40">
        <pre className="p-3 text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed">
          {isLoading ? t("app.loading") : (data?.lines?.join("\n") || t("restoreProgress.log.noOutput"))}
        </pre>
      </ScrollArea>
    </div>
  )
}

// ── Rollback delta widget ─────────────────────────────────────

const RollbackDelta: React.FC<{ delta: RestoreRollback | undefined }> = ({ delta }) => {
  const t = useT()
  const vms = delta?.vms_to_remove ?? []
  const lxcs = delta?.lxcs_to_remove ?? []
  const comps = delta?.components_to_uninstall ?? []
  if (!vms.length && !lxcs.length && !comps.length) {
    return (
      <div className="text-xs text-muted-foreground">
        {t("restoreProgress.rollback.empty")}
      </div>
    )
  }
  const Row: React.FC<{ label: string; items: string[]; cmd: (id: string) => string }> = ({ label, items, cmd }) =>
    items.length === 0 ? null : (
      <div className="space-y-1">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className="flex flex-wrap gap-1.5">
          {items.map((id) => (
            <Badge key={id} variant="outline" className="font-mono text-xs">
              {id}
            </Badge>
          ))}
        </div>
        {items.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              {t("restoreProgress.rollback.showCleanup")}
            </summary>
            <pre className="mt-1 p-2 rounded-md bg-black/40 text-xs text-muted-foreground font-mono">
              {items.map(cmd).join("\n")}
            </pre>
          </details>
        )}
      </div>
    )

  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        {t("restoreProgress.rollback.description")}
      </div>
      <Row
        label={t("restoreProgress.rollback.vms")}
        items={vms}
        cmd={(id) => `qm stop ${id} 2>/dev/null; qm destroy ${id} --purge`}
      />
      <Row
        label={t("restoreProgress.rollback.lxcs")}
        items={lxcs}
        cmd={(id) => `pct stop ${id} 2>/dev/null; pct destroy ${id} --purge`}
      />
      <Row
        label={t("restoreProgress.rollback.components")}
        items={comps}
        cmd={(name) => t("restoreProgress.rollback.uninstallComponentCommand", { name })}
      />
    </div>
  )
}

// ── Detail modal ──────────────────────────────────────────────

const RestoreDetailModal: React.FC<{
  open: boolean
  onClose: () => void
  state: RestoreState
  historyMode?: boolean
}> = ({ open, onClose, state, historyMode }) => {
  const t = useT()
  const progressPct = state.steps_total > 0 ? Math.round((state.steps_done / state.steps_total) * 100) : 0

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5 text-blue-500" />
            {t("restoreProgress.title")}
            <StatusBadge status={state.status} />
          </DialogTitle>
          <DialogDescription>
            {t("restoreProgress.startedAt", { time: formatIso(state.started_at) })}
            {state.finished_at ? ` · ${t("restoreProgress.finishedAt", { time: formatIso(state.finished_at) })}` : ""}
            {state.summary?.duration ? ` · ${state.summary.duration}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{state.current_step || "—"}</span>
              <span>
                {t("restoreProgress.steps", { done: state.steps_done, total: state.steps_total })}
                {state.status === "running" && ` · ${computeEta(state, t)}`}
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  state.status === "failed" ? "bg-red-500" : state.status === "complete" ? "bg-emerald-500" : "bg-blue-500"
                }`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          {state.components.length > 0 && (
            <div className="space-y-2">
              <div className="text-sm font-medium flex items-center gap-2">
                <Cpu className="h-4 w-4" />
                {t("restoreProgress.sections.components")}
              </div>
              <div className="space-y-1.5">
                {state.components.map((c) => (
                  <div
                    key={c.name}
                    className="flex items-center justify-between rounded-md border border-border bg-muted/30 px-3 py-2 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <ComponentStatusIcon status={c.status} />
                      <span className="font-medium">{formatComponent(c.name)}</span>
                      <span className="text-muted-foreground">{t(`restoreProgress.componentStatus.${c.status}`)}</span>
                      {c.exit_code && <span className="text-red-400">{t("restoreProgress.exitCode", { code: c.exit_code })}</span>}
                    </div>
                    {c.log && <span className="text-muted-foreground font-mono">{c.log}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {state.sanity_warnings.length > 0 && (
            <div className="space-y-2">
              <div className="text-sm font-medium flex items-center gap-2 text-amber-400">
                <AlertTriangle className="h-4 w-4" />
                {t("restoreProgress.sections.bootWarnings")}
              </div>
              <ul className="list-disc list-inside text-xs text-muted-foreground space-y-1">
                {state.sanity_warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {state.data_pools_import && <DataPoolsBlock section={state.data_pools_import} />}

          <div className="space-y-2">
            <div className="text-sm font-medium">{t("restoreProgress.sections.rollbackDelta")}</div>
            <RollbackDelta delta={state.rollback_delta} />
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium">{t("restoreProgress.sections.log")}</div>
            <LogViewer path={state.log_path} historyOnly={historyMode} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("actions.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Rendered inside RestoreDetailModal — one row per outcome category
// (imported / forced / partial skip / missing skip / failed).
const DataPoolsBlock: React.FC<{ section: DataPoolsImport }> = ({ section }) => {
  const t = useT()
  const total =
    section.ok.length +
    section.forced.length +
    section.partial.length +
    section.missing.length +
    section.failed.length
  if (total === 0) return null

  const Row: React.FC<{
    label: string
    tone: "ok" | "warn" | "info" | "error"
    items: string[]
    help?: string
  }> = ({ label, tone, items, help }) => {
    if (items.length === 0) return null
    const toneClass =
      tone === "ok"
        ? "text-emerald-400"
        : tone === "warn"
          ? "text-amber-400"
          : tone === "error"
            ? "text-red-400"
            : "text-blue-400"
    return (
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
        <div className={`font-medium ${toneClass} flex items-center gap-2`}>
          {tone === "ok" && <CheckCircle2 className="h-3.5 w-3.5" />}
          {tone === "warn" && <AlertTriangle className="h-3.5 w-3.5" />}
          {tone === "error" && <XCircle className="h-3.5 w-3.5" />}
          {tone === "info" && <CheckCircle2 className="h-3.5 w-3.5" />}
          <span>{label}</span>
          <span className="text-muted-foreground">({items.length})</span>
        </div>
        <div className="mt-1 font-mono text-muted-foreground break-all">{items.join(", ")}</div>
        {help && <div className="mt-1 text-muted-foreground">{help}</div>}
      </div>
    )
  }

  return (
      <div className="space-y-2">
      <div className="text-sm font-medium flex items-center gap-2">
        <Cpu className="h-4 w-4" />
        {t("restoreProgress.dataPools.title")}
      </div>
      <div className="space-y-1.5">
        <Row label={t("restoreProgress.dataPools.imported")} tone="ok" items={section.ok} />
        <Row
          label={t("restoreProgress.dataPools.importedForced")}
          tone="info"
          items={section.forced}
          help={t("restoreProgress.dataPools.importedForcedHelp")}
        />
        <Row
          label={t("restoreProgress.dataPools.skippedPartial")}
          tone="warn"
          items={section.partial}
          help={t("restoreProgress.dataPools.skippedPartialHelp")}
        />
        <Row
          label={t("restoreProgress.dataPools.skippedMissing")}
          tone="warn"
          items={section.missing}
          help={t("restoreProgress.dataPools.skippedMissingHelp")}
        />
        <Row
          label={t("restoreProgress.dataPools.importFailed")}
          tone="error"
          items={section.failed}
          help={t("restoreProgress.dataPools.importFailedHelp")}
        />
      </div>
      {section.log_path && (
        <div className="text-xs text-muted-foreground font-mono">{t("restoreProgress.dataPools.logPath", { path: section.log_path })}</div>
      )}
    </div>
  )
}

// ── History browser modal ─────────────────────────────────────

const RestoreHistoryModal: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const t = useT()
  const { data } = useSWR<{ entries: HistoryEntry[] }>(open ? "/api/host-backups/restore/history" : null, fetcher)
  const [detailFile, setDetailFile] = useState<string | null>(null)
  const { data: detailResp } = useSWR<{ state: RestoreState }>(
    detailFile ? `/api/host-backups/restore/history?file=${encodeURIComponent(detailFile)}` : null,
    fetcher,
  )

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <History className="h-5 w-5" />
              {t("restoreProgress.history.title")}
            </DialogTitle>
            <DialogDescription>
              {t("restoreProgress.history.description")}
            </DialogDescription>
          </DialogHeader>

          <ScrollArea className="h-96">
            <div className="space-y-1.5">
              {(data?.entries ?? []).length === 0 ? (
                <div className="text-sm text-muted-foreground py-6 text-center">{t("restoreProgress.history.empty")}</div>
              ) : (
                (data?.entries ?? []).map((e) => (
                  <button
                    key={e.file}
                    onClick={() => setDetailFile(e.file)}
                    className="w-full flex items-center justify-between rounded-md border border-border bg-muted/30 hover:bg-muted px-3 py-2 text-xs text-left"
                  >
                    <div className="flex items-center gap-2">
                      <StatusBadge status={e.status} />
                      <span className="text-muted-foreground">
                        {e.started_at ? formatIso(e.started_at) : formatIso(new Date(e.mtime * 1000).toISOString())}
                      </span>
                      {e.duration && <span className="text-muted-foreground">· {e.duration}</span>}
                    </div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </button>
                ))
              )}
            </div>
          </ScrollArea>

          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              {t("actions.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {detailFile && detailResp?.state && (
        <RestoreDetailModal
          open={!!detailFile}
          onClose={() => setDetailFile(null)}
          state={detailResp.state}
          historyMode
        />
      )}
    </>
  )
}

// ── Main inline card ──────────────────────────────────────────

export const RestoreProgressCard: React.FC = () => {
  const t = useT()
  const { data, mutate } = useSWR<{ state: RestoreState | null }>(
    "/api/host-backups/restore/status",
    fetcher,
    {
      refreshInterval: (latest) => (latest?.state?.status === "running" ? 2000 : 30000),
      revalidateOnFocus: true,
    },
  )
  const [detailOpen, setDetailOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [dismissing, setDismissing] = useState(false)

  const state = data?.state ?? null
  const progressPct = useMemo(() => {
    if (!state || state.steps_total <= 0) return 0
    return Math.round((state.steps_done / state.steps_total) * 100)
  }, [state])

  const dismiss = async () => {
    if (!state) return
    setDismissing(true)
    try {
      await fetchApi("/api/host-backups/restore/dismiss", { method: "POST" })
      await mutate()
    } finally {
      setDismissing(false)
    }
  }

  // Hidden entirely when: no restore run has ever happened, OR the
  // last run is terminal AND acknowledged. History button is still
  // reachable from the main card header (rendered elsewhere).
  if (!state) return null
  if (state.status !== "running" && state.acknowledged) {
    return (
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={() => setHistoryOpen(true)}>
          <History className="h-3.5 w-3.5 mr-1" />
          {t("restoreProgress.history.title")}
        </Button>
        <RestoreHistoryModal open={historyOpen} onClose={() => setHistoryOpen(false)} />
      </div>
    )
  }

  const hasWarnings = state.sanity_warnings.length > 0
  const pools = state.data_pools_import
  const poolCount =
    (pools?.ok.length ?? 0) +
    (pools?.forced.length ?? 0) +
    (pools?.partial.length ?? 0) +
    (pools?.missing.length ?? 0) +
    (pools?.failed.length ?? 0)
  const poolWarnings = (pools?.partial.length ?? 0) + (pools?.missing.length ?? 0) + (pools?.failed.length ?? 0)
  const barColor =
    state.status === "failed" ? "bg-red-500" : state.status === "complete" ? "bg-emerald-500" : "bg-blue-500"

  return (
    <>
      <Card className="bg-card border-border">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <RotateCcw
                className={`h-5 w-5 ${state.status === "running" ? "text-blue-500 animate-spin" : "text-blue-500"}`}
              />
              {t("restoreProgress.title")}
              <StatusBadge status={state.status} />
              {hasWarnings && (
                <Badge variant="outline" className="text-amber-400 border-amber-500/40 bg-amber-500/10 gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {t("restoreProgress.badges.bootWarnings", { count: state.sanity_warnings.length })}
                </Badge>
              )}
              {poolCount > 0 && (
                <Badge
                  variant="outline"
                  className={
                    poolWarnings > 0
                      ? "text-amber-400 border-amber-500/40 bg-amber-500/10 gap-1"
                      : "text-emerald-400 border-emerald-500/40 bg-emerald-500/10 gap-1"
                  }
                >
                  <Cpu className="h-3 w-3" />
                  {t("restoreProgress.badges.zfsPools", { count: poolCount })}
                  {poolWarnings > 0 && ` · ${t("restoreProgress.badges.needAttention", { count: poolWarnings })}`}
                </Badge>
              )}
            </CardTitle>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setDetailOpen(true)}>
                {t("restoreProgress.actions.details")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setHistoryOpen(true)}>
                <History className="h-3.5 w-3.5 mr-1" />
                {t("restoreProgress.actions.history")}
              </Button>
              {state.status !== "running" && (
                <Button size="sm" onClick={dismiss} disabled={dismissing}>
                  {dismissing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t("restoreProgress.actions.dismiss")}
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span className="truncate">
                {state.current_step || "—"} · {t("restoreProgress.startedRelative", { time: formatRelative(state.started_at, t) })}
              </span>
              <span>
                {t("restoreProgress.steps", { done: state.steps_done, total: state.steps_total })}
                {state.status === "running" && ` · ${computeEta(state, t)}`}
                {state.summary?.duration && state.status !== "running" && ` · ${state.summary.duration}`}
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div className={`h-full transition-all duration-500 ${barColor}`} style={{ width: `${progressPct}%` }} />
            </div>
          </div>

          {state.summary && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">{t("restoreProgress.summary.guests")}</div>
                <div className="font-medium">{state.summary.guests}</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">{t("restoreProgress.summary.bindMountStubs")}</div>
                <div className="font-medium">{state.summary.stubs}</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">{t("restoreProgress.summary.staleNodesCleaned")}</div>
                <div className="font-medium">{state.summary.stale_nodes}</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">{t("restoreProgress.summary.components")}</div>
                <div className="font-medium">{state.summary.components}</div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <RestoreDetailModal open={detailOpen} onClose={() => setDetailOpen(false)} state={state} />
      <RestoreHistoryModal open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </>
  )
}

export default RestoreProgressCard
