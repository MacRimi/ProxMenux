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

const formatRelative = (iso: string) => {
  try {
    const then = new Date(iso).getTime()
    const now = Date.now()
    const diff = Math.max(0, Math.round((now - then) / 1000))
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
    return `${Math.round(diff / 86400)}d ago`
  } catch {
    return iso
  }
}

// Rough time-remaining estimate derived from steps_done + elapsed.
// Best-effort: at step 0 there's no data yet, so it returns
// "estimating time…". After the run is terminal, "—". The output is
// a full phrase so the caller doesn't have to add suffix words that
// only make sense on some branches.
const computeEta = (state: RestoreState): string => {
  if (state.status !== "running") return "—"
  if (!state.steps_done || state.steps_done <= 0) return "estimating time…"
  const elapsedSec = Math.max(1, Math.round((Date.now() - new Date(state.started_at).getTime()) / 1000))
  const perStep = elapsedSec / state.steps_done
  const remaining = Math.max(0, state.steps_total - state.steps_done)
  const eta = Math.round(perStep * remaining)
  if (eta < 60) return `~${eta}s left`
  if (eta < 3600) return `~${Math.round(eta / 60)}m left`
  return `~${Math.round(eta / 3600)}h left`
}

// ── Small building blocks ─────────────────────────────────────

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  if (status === "running")
    return (
      <Badge className="bg-blue-500/10 border-blue-500/40 text-blue-300 gap-1">
        <Loader2 className="h-3 w-3 animate-spin" />
        Restore in progress
      </Badge>
    )
  if (status === "complete")
    return (
      <Badge className="bg-emerald-500/10 border-emerald-500/40 text-emerald-400 gap-1">
        <CheckCircle2 className="h-3 w-3" />
        Restore complete
      </Badge>
    )
  if (status === "failed")
    return (
      <Badge className="bg-red-500/10 border-red-500/40 text-red-400 gap-1">
        <XCircle className="h-3 w-3" />
        Restore failed
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
          {path ?? "no log yet"}
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant={filter === "all" ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => setFilter("all")}
          >
            <ArrowDownAZ className="h-3 w-3 mr-1" />
            Full
          </Button>
          <Button
            size="sm"
            variant={filter === "issues" ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => setFilter("issues")}
          >
            <Filter className="h-3 w-3 mr-1" />
            Issues only
          </Button>
        </div>
      </div>
      <ScrollArea className="h-72 rounded-md border border-border bg-black/40">
        <pre className="p-3 text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed">
          {isLoading ? "Loading…" : (data?.lines?.join("\n") || "(no output)")}
        </pre>
      </ScrollArea>
    </div>
  )
}

// ── Rollback delta widget ─────────────────────────────────────

const RollbackDelta: React.FC<{ delta: RestoreRollback | undefined }> = ({ delta }) => {
  const vms = delta?.vms_to_remove ?? []
  const lxcs = delta?.lxcs_to_remove ?? []
  const comps = delta?.components_to_uninstall ?? []
  if (!vms.length && !lxcs.length && !comps.length) {
    return (
      <div className="text-xs text-muted-foreground">
        No entries exist on this host that weren't in the restored backup.
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
              Show manual cleanup commands
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
        These entries exist on this host but were NOT in the restored backup. Review before removing.
      </div>
      <Row
        label="VMs created after the backup"
        items={vms}
        cmd={(id) => `qm stop ${id} 2>/dev/null; qm destroy ${id} --purge`}
      />
      <Row
        label="LXCs created after the backup"
        items={lxcs}
        cmd={(id) => `pct stop ${id} 2>/dev/null; pct destroy ${id} --purge`}
      />
      <Row
        label="Components installed after the backup"
        items={comps}
        cmd={(name) => `# uninstall ${name} manually via ProxMenux → Hardware & GPU`}
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
  const progressPct = state.steps_total > 0 ? Math.round((state.steps_done / state.steps_total) * 100) : 0

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5 text-blue-500" />
            Post-restore progress
            <StatusBadge status={state.status} />
          </DialogTitle>
          <DialogDescription>
            Started {formatIso(state.started_at)}
            {state.finished_at ? ` · finished ${formatIso(state.finished_at)}` : ""}
            {state.summary?.duration ? ` · ${state.summary.duration}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{state.current_step || "—"}</span>
              <span>
                {state.steps_done}/{state.steps_total} steps
                {state.status === "running" && ` · ${computeEta(state)}`}
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
                Components
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
                      <span className="text-muted-foreground">{c.status}</span>
                      {c.exit_code && <span className="text-red-400">exit {c.exit_code}</span>}
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
                Boot sanity warnings
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
            <div className="text-sm font-medium">Rollback delta</div>
            <RollbackDelta delta={state.rollback_delta} />
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium">Log</div>
            <LogViewer path={state.log_path} historyOnly={historyMode} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Rendered inside RestoreDetailModal — one row per outcome category
// (imported / forced / partial skip / missing skip / failed).
const DataPoolsBlock: React.FC<{ section: DataPoolsImport }> = ({ section }) => {
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
        ZFS data pools — auto-import
      </div>
      <div className="space-y-1.5">
        <Row label="Imported" tone="ok" items={section.ok} />
        <Row
          label="Imported (forced, foreign hostid)"
          tone="info"
          items={section.forced}
          help="New hostid grabbed onto the pool label — next boot imports clean."
        />
        <Row
          label="Skipped (some disks missing)"
          tone="warn"
          items={section.partial}
          help="Some vdev disks weren't found by /dev/disk/by-id. Pool NOT imported to avoid a degraded auto-import. Fix the disks or import manually with zpool import."
        />
        <Row
          label="Skipped (no disks present)"
          tone="warn"
          items={section.missing}
          help="None of the pool's disks are on this host. Move the disks over or import from a different host."
        />
        <Row
          label="Import failed"
          tone="error"
          items={section.failed}
          help="ZFS rejected the import even with -f. Inspect with `zpool import` and the log below."
        />
      </div>
      {section.log_path && (
        <div className="text-xs text-muted-foreground font-mono">Log: {section.log_path}</div>
      )}
    </div>
  )
}

// ── History browser modal ─────────────────────────────────────

const RestoreHistoryModal: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
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
              Past restores
            </DialogTitle>
            <DialogDescription>
              Restores archived by the post-boot dispatcher. The latest 20 are kept.
            </DialogDescription>
          </DialogHeader>

          <ScrollArea className="h-96">
            <div className="space-y-1.5">
              {(data?.entries ?? []).length === 0 ? (
                <div className="text-sm text-muted-foreground py-6 text-center">No past restores recorded.</div>
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
              Close
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
          Past restores
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
              Post-restore progress
              <StatusBadge status={state.status} />
              {hasWarnings && (
                <Badge variant="outline" className="text-amber-400 border-amber-500/40 bg-amber-500/10 gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {state.sanity_warnings.length} boot warning{state.sanity_warnings.length === 1 ? "" : "s"}
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
                  {poolCount} ZFS pool{poolCount === 1 ? "" : "s"}
                  {poolWarnings > 0 && ` · ${poolWarnings} need attention`}
                </Badge>
              )}
            </CardTitle>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setDetailOpen(true)}>
                Details
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setHistoryOpen(true)}>
                <History className="h-3.5 w-3.5 mr-1" />
                History
              </Button>
              {state.status !== "running" && (
                <Button size="sm" onClick={dismiss} disabled={dismissing}>
                  {dismissing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Dismiss"}
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span className="truncate">
                {state.current_step || "—"} · started {formatRelative(state.started_at)}
              </span>
              <span>
                {state.steps_done}/{state.steps_total} steps
                {state.status === "running" && ` · ${computeEta(state)}`}
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
                <div className="text-muted-foreground">Guests</div>
                <div className="font-medium">{state.summary.guests}</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">Bind-mount stubs</div>
                <div className="font-medium">{state.summary.stubs}</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">Stale nodes cleaned</div>
                <div className="font-medium">{state.summary.stale_nodes}</div>
              </div>
              <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                <div className="text-muted-foreground">Components</div>
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
