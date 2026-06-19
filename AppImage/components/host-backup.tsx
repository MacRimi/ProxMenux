"use client"

import { useState, useEffect, useRef } from "react"
import useSWR from "swr"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Checkbox } from "./ui/checkbox"
import { ScrollArea } from "./ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import {
  DatabaseBackup,
  Clock,
  HardDrive,
  Server,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  PlayCircle,
  Archive,
  FileSearch,
  Calendar,
  Trash2,
  Plus,
  ChevronRight,
  ChevronLeft,
  Pencil,
  Save,
  Download,
  FileText,
  Power,
  RefreshCw,
} from "lucide-react"
import { fetchApi, getApiUrl } from "../lib/api-config"
import { formatStorage } from "../lib/utils"

// ── Shape contracts with the backend (flask_server.py: api_host_backups_*) ──

interface BackupJob {
  id: string
  destination: string
  method: string                 // "pbs" | "borg" | "local" | "unknown"
  on_calendar: string            // "OnCalendar=..." for timer jobs, "attached → storage:X" for attached
  retention: string              // "last=5, daily=7, ..."
  timer_enabled: boolean         // legacy — only meaningful for non-attached jobs
  enabled: boolean               // unified state (timer for non-attached, ENABLED= for attached)
  attached: boolean              // PVE vzdump-attached: no own timer, trigger from hook
  pve_storage: string | null     // storage id the attached job listens for
  profile_mode: string           // "default" | "custom"
  manual: boolean                // MANUAL_RUN=1 — one-shot, no schedule, won't re-fire
  last_status: string | null
  next_run: string | null
}

// Sprint H — remote backups (PBS + Borg). Listing is cheap (metadata
// only); the heavy lifting happens on demand when the operator clicks
// Download. Same shape for both backends so the UI renders them
// uniformly — `backend` is the only switch.
interface RemoteSnapshot {
  backend: "pbs" | "borg"
  repo_name: string
  repo_repository: string
  snapshot: string             // canonical id used to extract / restore
  backup_type: string
  backup_id: string
  backup_time: number          // unix seconds
  size_bytes: number           // 0 for Borg (omitted by `borg list`)
  owner: string | null
  protected: boolean
  files: Array<{ filename: string; size: number }>
  fingerprint: string | null
  borg_id?: string             // Borg-only fields when available
  borg_start_iso?: string
}

interface RemoteArchivesResp {
  snapshots: RemoteSnapshot[]
  errors: Array<{ backend: string; repo_name: string; error: string }>
}

interface ExportTask {
  task_id: string
  backend: string
  repo_name: string
  snapshot: string
  state: "queued" | "restoring" | "packing" | "completed" | "failed"
  message: string
  size_bytes: number
  output_path: string | null
  error: string | null
}

// Unified archive descriptor — local .tar.zst files and remote PBS /
// Borg snapshots share the same row layout; `source` decides which
// code paths apply (inline download vs export-then-download, manifest
// available vs not, etc.).
interface UnifiedArchive {
  source: "local" | "pbs" | "borg"
  display_id: string           // what shows in mono in the row
  size_bytes: number
  created_at: number           // unix seconds
  source_label: string         // "/var/lib/vz/dump" or "PBS my-pbs" or "Borg my-borg"
  // One of the two is populated depending on `source`.
  local?: BackupArchive
  remote?: RemoteSnapshot      // for both pbs and borg
}

interface BackupArchive {
  id: string                     // basename of the .tar file (also the URL slug)
  path: string                   // absolute path on host
  size_bytes: number
  mtime: number                  // unix seconds
  // From the backend identifier — see _identify_host_backup() in flask_server.py.
  // kind: "manual" / "scheduled" when we know; "legacy" when only the in-tar
  //       marker confirmed it's a ProxMenux backup (no sidecar, no name match).
  job_id: string | null
  kind: "manual" | "scheduled" | "legacy"
  profile: string | null
  source_hostname: string | null
  // Which detection path identified this archive. Surfaced as a small tooltip
  // hint so the operator knows whether the metadata is authoritative
  // (sidecar) or inferred (filename / tar-peek).
  detected_via: "sidecar" | "job_id_match" | "hostcfg_prefix" | "tar_peek"
}

interface ManifestSourceHost {
  hostname: string
  pve_version: string | null
  roles: string[]
  kernel: string
  boot_mode: string
  cpu_model: string
  memory_kb: number
}

interface PreflightCheck {
  id: string
  severity: "pass" | "warn" | "fail"
  message: string
  details: Record<string, unknown> | null
}

interface PreflightReport {
  source_host_at_backup: ManifestSourceHost
  selected_mode: {
    mode: string
    paths_include: string[]
    paths_exclude: string[]
    components_include: string[]
    storage_apply: boolean
    network_apply: boolean
  }
  preflight: {
    checks: PreflightCheck[]
    summary: { pass: number; warn: number; fail: number }
  }
  storage: {
    zfs: Array<{ name: string; action: string; present: string[]; missing: string[] }>
    lvm: Array<{ name: string; action: string }>
    pve_storage: Array<{ id: string; type: string; action: string; note: string | null }>
    in_selected_mode: boolean
  }
  network: {
    keep: Array<{ ifname: string; mac: string }>
    remap: Array<{ source_ifname: string; destination_ifname: string; mac: string }>
    orphan: Array<{ source_ifname: string; source_mac: string }>
    new: Array<{ ifname: string; mac: string }>
    in_selected_mode: boolean
  }
  driver_reinstall: {
    plan: Array<{
      component_id: string
      type: string
      version: string
      installer: string | null
      action: string
      reason: string
    }>
  }
  abort_reason: string | null
}

const fetcher = async (url: string) => fetchApi(url)

const formatMtime = (mtime: number) =>
  new Date(mtime * 1000).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })

const formatNext = (iso: string | null) => {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// Best-effort human form of systemd OnCalendar expressions. Whatever
// we don't recognise falls back to "<raw> (systemd OnCalendar)" so the
// operator at least knows what kind of string they're looking at.
// Handles the patterns the host-backup wizard can emit ("hourly",
// "daily", "weekly", "monthly", "*-*-* HH:MM:SS", "Mon..Sun *-*-* …").
const humanizeOnCalendar = (raw: string | null | undefined): string => {
  if (!raw) return "—"
  const s = raw.trim()
  if (!s) return "—"
  const lower = s.toLowerCase()
  if (lower === "hourly") return "Every hour (at minute 0)"
  if (lower === "daily") return "Every day at 00:00"
  if (lower === "weekly") return "Every Monday at 00:00"
  if (lower === "monthly") return "On the 1st of every month at 00:00"
  if (lower === "yearly" || lower === "annually") return "On Jan 1st at 00:00"
  if (lower === "minutely") return "Every minute"
  // *-*-* HH:MM[:SS]  → "Every day at HH:MM"
  let m = s.match(/^\*-\*-\*\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (m) return `Every day at ${m[1].padStart(2, "0")}:${m[2]}`
  // *-*-* *:MM:SS    → "Every hour at minute MM"
  m = s.match(/^\*-\*-\*\s+\*:(\d{2})(?::(\d{2}))?$/)
  if (m) return `Every hour at minute ${m[1]}`
  // Mon,Tue *-*-* HH:MM:SS   →  "<weekdays> at HH:MM"
  m = s.match(/^([A-Za-z,.\s]+)\s+\*-\*-\*\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (m) {
    const expandWeekdays = (chunk: string): string => {
      const days: Record<string, string> = {
        mon: "Monday", tue: "Tuesday", wed: "Wednesday",
        thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
      }
      const rangeMatch = chunk.match(/^([A-Za-z]+)\.\.([A-Za-z]+)$/)
      if (rangeMatch) {
        const order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        const start = order.indexOf(rangeMatch[1].slice(0, 3).toLowerCase())
        const end = order.indexOf(rangeMatch[2].slice(0, 3).toLowerCase())
        if (start >= 0 && end >= 0 && start <= end) {
          return order.slice(start, end + 1).map((d) => days[d]).join(", ")
        }
      }
      return chunk
        .split(",")
        .map((d) => days[d.trim().slice(0, 3).toLowerCase()] || d.trim())
        .join(", ")
    }
    return `${expandWeekdays(m[1])} at ${m[2].padStart(2, "0")}:${m[3]}`
  }
  return `${s} (systemd OnCalendar)`
}

// last_status is the raw RUN_AT=..., RESULT=..., LOG_FILE=... blob the
// scheduler runner persists. We only care about RESULT + RUN_AT for the
// UI; everything else is noise the operator doesn't need on a list view.
function parseJobStatus(raw: string | null): { result: string | null; runAt: string | null; logFile: string | null } | null {
  if (!raw) return null
  const map: Record<string, string> = {}
  for (const line of raw.split("\n")) {
    const m = line.match(/^([A-Z_]+)=(.*)$/)
    if (m) map[m[1]] = m[2]
  }
  return {
    result: map["RESULT"] || null,
    runAt: map["RUN_AT"] || null,
    logFile: map["LOG_FILE"] || null,
  }
}

// Backend-method color scheme, mirrored exactly from storage-overview.tsx
// (line 414 et al.) so a PBS job badge here looks identical to a PBS
// snapshot badge on the Storage page.
const methodBadgeCls = (m: string | undefined): string => {
  switch ((m || "").toLowerCase()) {
    case "pbs":
      return "bg-purple-500/10 text-purple-400 border-purple-500/20"
    case "borg":
      return "bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20"
    case "local":
    default:
      return "bg-blue-500/10 text-blue-400 border-blue-500/20"
  }
}

// formatStorage() in lib/utils.ts expects GIGABYTES as input — it's
// the storage layer's native unit. For raw log file sizes coming from
// os.path.getsize() we need a byte-aware formatter; passing N bytes to
// formatStorage() rendered "442 GB" for a 442-byte log. Tiny inline.
const formatBytes = (n: number): string => {
  if (!Number.isFinite(n) || n < 0) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

const formatRunAt = (iso: string | null) => {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

export function HostBackup() {
  const { data: jobsResp, error: jobsErr, mutate: mutateJobs } = useSWR<{ jobs: BackupJob[] }>(
    "/api/host-backups/jobs",
    fetcher,
    { refreshInterval: 30000 },
  )
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [jobToDelete, setJobToDelete] = useState<BackupJob | null>(null)
  const [creatingJob, setCreatingJob] = useState<boolean>(false)
  const [editingJobId, setEditingJobId] = useState<string | null>(null)
  const [viewingJobId, setViewingJobId] = useState<string | null>(null)
  const [runningManual, setRunningManual] = useState<boolean>(false)

  async function confirmDeleteJob() {
    if (!jobToDelete) return
    const id = jobToDelete.id
    setBusyJobId(id)
    setActionError(null)
    try {
      await fetchApi(`/api/host-backups/jobs/${encodeURIComponent(id)}`, { method: "DELETE" })
      mutateJobs()
      setJobToDelete(null)
    } catch (e) {
      setActionError(`Failed to delete "${id}": ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyJobId(null)
    }
  }
  const { data: destinationsResp, mutate: mutateDestinations } = useSWR<DestinationsResp>(
    "/api/host-backups/destinations",
    fetcher,
    { refreshInterval: 60000 },
  )
  const { data: remoteArchivesResp, error: remoteArchivesErr, mutate: mutateRemoteArchives } = useSWR<RemoteArchivesResp>(
    "/api/host-backups/remote-archives",
    fetcher,
    { refreshInterval: 60000 },
  )
  const { data: archivesResp, error: archivesErr, mutate: mutateArchives } = useSWR<{ archives: BackupArchive[] }>(
    "/api/host-backups/archives",
    fetcher,
    { refreshInterval: 30000 },
  )

  const [inspectingArchive, setInspectingArchive] = useState<UnifiedArchive | null>(null)

  // Merge local archives + remote snapshots (PBS + Borg) into a single
  // sorted list. Newest first, regardless of source — operators care
  // about "the most recent backup", not "the most recent local backup".
  const unifiedArchives: UnifiedArchive[] = (() => {
    const out: UnifiedArchive[] = []
    if (archivesResp?.archives) {
      for (const a of archivesResp.archives) {
        out.push({
          source: "local",
          display_id: a.id,
          size_bytes: a.size_bytes,
          created_at: a.mtime,
          source_label: a.path.replace(/\/[^/]+$/, "") || "/",
          local: a,
        })
      }
    }
    if (remoteArchivesResp?.snapshots) {
      for (const s of remoteArchivesResp.snapshots) {
        out.push({
          source: s.backend,
          display_id: s.snapshot,
          size_bytes: s.size_bytes,
          created_at: s.backup_time,
          source_label: `${s.backend.toUpperCase()} ${s.repo_name}`,
          remote: s,
        })
      }
    }
    out.sort((a, b) => b.created_at - a.created_at)
    return out
  })()

  return (
    <div className="space-y-4 md:space-y-6">
      {/* ── Scheduled jobs ───────────────────────────────── */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-blue-500" />
            <CardTitle className="text-base font-semibold">Scheduled Backup Jobs</CardTitle>
            <Badge variant="outline" className="ml-1">
              {jobsResp?.jobs?.filter((j) => !j.manual).length ?? 0}
            </Badge>
          </div>
          <Button
            size="sm"
            className="h-8 px-3 bg-blue-500 hover:bg-blue-600 text-white"
            onClick={() => setCreatingJob(true)}
          >
            <Plus className="h-4 w-4 mr-1" />
            Create job
          </Button>
        </CardHeader>
        <CardContent>
          {jobsErr ? (
            <div className="text-sm text-red-500 py-4">Failed to load jobs</div>
          ) : !jobsResp ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading...
            </div>
          ) : jobsResp.jobs.filter((j) => !j.manual).length === 0 ? null : (
            <div className="space-y-2">
              {actionError && (
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
                  {actionError}
                </div>
              )}
              {jobsResp.jobs.filter((j) => !j.manual).map((j) => {
                const status = parseJobStatus(j.last_status)
                const statusBadge = status?.result === "ok"
                  ? { label: "ok", cls: "bg-emerald-500/10 border-emerald-500/40 text-emerald-400" }
                  : status?.result
                    ? { label: status.result, cls: "bg-red-500/10 border-red-500/40 text-red-400" }
                    : null
                const lastRunWhen = formatRunAt(status?.runAt ?? null)
                return (
                  <button
                    key={j.id}
                    type="button"
                    onClick={() => setViewingJobId(j.id)}
                    className="w-full text-left flex items-start gap-3 p-3 rounded-md border border-border bg-card hover:bg-white/5 transition-colors group"
                    title="Click to open this job"
                  >
                    <div className="min-w-0 flex-1 w-full">
                      {/* Title row */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-base truncate" title={j.id}>{j.id}</span>
                        <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(j.method)}`}>
                          {j.method}
                        </Badge>
                        {j.manual && (
                          <Badge variant="outline" className="text-[10px] text-purple-400 border-purple-400/40 bg-purple-500/5">
                            manual
                          </Badge>
                        )}
                        {j.attached && (
                          <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-400/40 bg-blue-500/5">
                            attached
                          </Badge>
                        )}
                        {!j.enabled && !j.manual && (
                          <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/40 bg-amber-500/5">
                            disabled
                          </Badge>
                        )}
                      </div>

                      {/* Destination */}
                      <div className="mt-1 text-sm font-mono text-muted-foreground truncate" title={j.destination}>
                        {j.destination || "—"}
                      </div>

                      {/* Stats row — icons in green, values in foreground
                          white to match the rest of the dashboard. */}
                      <div className="mt-2 text-xs text-foreground flex items-center gap-x-4 gap-y-1 flex-wrap">
                        <span className="inline-flex items-center gap-1" title={j.on_calendar}>
                          <Calendar className="h-3.5 w-3.5 text-green-500" />
                          <span>{humanizeOnCalendar(j.on_calendar)}</span>
                        </span>
                        {j.retention && (
                          <span className="inline-flex items-center gap-1.5 flex-wrap" title="Retention policy">
                            <Archive className="h-3.5 w-3.5 text-green-500" />
                            {(() => {
                              // Backend returns retention as "last=7, daily=7, …".
                              // Parse and render as labelled chips so the row
                              // matches the visual style of the modal.
                              const pairs = j.retention
                                .split(",")
                                .map((s) => s.trim())
                                .map((s) => {
                                  const m = s.match(/^([a-z]+)=(\d+)$/i)
                                  return m && Number(m[2]) > 0 ? { label: m[1], value: m[2] } : null
                                })
                                .filter((x): x is { label: string; value: string } => x !== null)
                              if (pairs.length === 0) {
                                return <span>{j.retention}</span>
                              }
                              return pairs.map((p) => (
                                <span
                                  key={p.label}
                                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-border bg-background/60"
                                >
                                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{p.label}</span>
                                  <span className="font-mono text-xs text-foreground">{p.value}</span>
                                </span>
                              ))
                            })()}
                          </span>
                        )}
                        {!j.attached && j.next_run && (
                          <span className="inline-flex items-center gap-1" title="Next scheduled run">
                            <Clock className="h-3.5 w-3.5 text-green-500" />
                            <span>next: {formatNext(j.next_run)}</span>
                          </span>
                        )}
                        {(statusBadge || lastRunWhen) && (
                          <span className="inline-flex items-center gap-1" title={status?.logFile ?? ""}>
                            <Clock className="h-3.5 w-3.5 text-green-500" />
                            <span>last:</span>
                            {statusBadge && (
                              <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide border ${statusBadge.cls}`}>
                                {statusBadge.label}
                              </span>
                            )}
                            {lastRunWhen && <span>{lastRunWhen}</span>}
                          </span>
                        )}
                        {!status && (
                          <span className="inline-flex items-center gap-1 text-muted-foreground">
                            <Clock className="h-3.5 w-3.5 text-green-500" />
                            <span>never run</span>
                          </span>
                        )}
                      </div>
                    </div>

                    <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-blue-400 transition-colors shrink-0 mt-1" />
                  </button>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Backup configuration (destinations + custom paths) ── */}
      <BackupConfigurationCard
        destinations={destinationsResp}
        onDestChanged={() => mutateDestinations()}
      />

      {/* ── Manual backups (entry point) ──────────────────── */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex items-center gap-2">
            <PlayCircle className="h-5 w-5 text-purple-400" />
            <CardTitle className="text-base font-semibold">Manual backups</CardTitle>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-8 px-3"
            onClick={() => setRunningManual(true)}
          >
            <PlayCircle className="h-4 w-4 mr-1" />
            Run manual backup
          </Button>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            Manual backups run once and stop — no schedule, no retention. Use this when you want a one-off copy without committing to a recurring job. The resulting archive shows up in <span className="font-medium text-foreground">Available Archives</span> below (for local backends; PBS / Borg manual backups go to their respective storage).
          </p>
        </CardContent>
      </Card>

      {/* ── Available archives ─────────────────────────────── */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex items-center gap-2">
            <Archive className="h-5 w-5 text-blue-500" />
            <CardTitle className="text-base font-semibold">Available Archives</CardTitle>
          </div>
          <Badge variant="outline">{unifiedArchives.length}</Badge>
        </CardHeader>
        <CardContent>
          <p className="text-[11px] text-muted-foreground mb-3">
            All backups visible from this host — local <code className="font-mono">.tar.zst</code> files (PVE default dump dir, configured local target, USB mountpoints, scheduled jobs' destinations) and PBS snapshots from every configured datastore. Click an entry to inspect, restore or download it — downloads of PBS snapshots are extracted on-demand only when you request them.
          </p>
          {remoteArchivesResp?.errors && remoteArchivesResp.errors.length > 0 && (
            <div className="text-[11px] text-amber-500 mb-3 px-3 py-2 rounded-md border border-amber-500/30 bg-amber-500/5 space-y-1">
              <div className="font-medium">Some remote backends couldn't be queried:</div>
              {remoteArchivesResp.errors.map((e, i) => (
                <div key={i} className="font-mono break-all">
                  {e.backend}/{e.repo_name}: {e.error}
                </div>
              ))}
            </div>
          )}
          {archivesErr && remoteArchivesErr ? (
            <div className="text-sm text-red-500 py-4">Failed to load archives</div>
          ) : !archivesResp && !remoteArchivesResp ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading...
            </div>
          ) : unifiedArchives.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4">
              No backups found yet. Use <span className="font-medium">Run manual backup</span> above, configure a scheduled job, or check that the configured PBS / Borg destinations have snapshots.
            </div>
          ) : (
            <div className="space-y-2">
              {unifiedArchives.map((u) => {
                const localKind = u.local?.kind
                const localJobId = u.local?.job_id
                const localHost = u.local?.source_hostname
                const localPath = u.local?.path
                const sourceBadgeCls =
                  u.source === "pbs"
                    ? "text-purple-300 border-purple-400/40 bg-purple-500/5"
                    : u.source === "borg"
                      ? "text-cyan-300 border-cyan-400/40 bg-cyan-500/5"
                      : "text-emerald-300 border-emerald-400/40 bg-emerald-500/5"
                return (
                  <button
                    key={`${u.source}:${u.display_id}`}
                    type="button"
                    onClick={() => setInspectingArchive(u)}
                    className="w-full text-left flex items-center justify-between gap-3 p-3 rounded-md border border-border bg-background/40 hover:bg-white/5 hover:border-blue-500/40 transition-colors group"
                    title="Click to inspect, restore or download this backup"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-xs truncate group-hover:text-blue-400 transition-colors" title={localPath || u.display_id}>
                        {u.display_id}
                      </div>
                      <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-3 flex-wrap">
                        <span className={`uppercase tracking-wide text-[10px] px-1.5 py-0.5 rounded border ${sourceBadgeCls}`}>
                          {u.source}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatMtime(u.created_at)}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <HardDrive className="h-3 w-3" />
                          {formatStorage(u.size_bytes)}
                        </span>
                        <span title={u.source_label}>
                          at: <code className="font-mono">{u.source_label}</code>
                        </span>
                        {u.source === "local" && localKind === "scheduled" && localJobId ? (
                          <span>job: <code className="font-mono">{localJobId}</code></span>
                        ) : u.source === "local" && localKind === "legacy" ? (
                          <span className="uppercase tracking-wide text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/40 text-amber-400">
                            legacy
                          </span>
                        ) : u.source === "local" && localKind === "manual" ? (
                          <span className="uppercase tracking-wide text-[10px] px-1.5 py-0.5 rounded bg-white/5 border border-border">
                            manual
                          </span>
                        ) : null}
                        {(u.source === "pbs" || u.source === "borg") && u.remote?.backup_id && (
                          <span>{u.source === "pbs" ? "group" : "archive"}: <code className="font-mono">{u.remote.backup_id}</code></span>
                        )}
                        {u.source === "local" && localHost && (
                          <span>host: <code className="font-mono">{localHost}</code></span>
                        )}
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-blue-400 transition-colors shrink-0" />
                  </button>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Inspect / preflight modal ──────────────────────── */}
      <InspectModal
        archive={inspectingArchive}
        onClose={() => setInspectingArchive(null)}
        onDeleted={() => {
          setInspectingArchive(null)
          mutateArchives()
        }}
      />

      {/* ── Create / Edit job wizard ─────────────────────── */}
      <CreateJobDialog
        open={creatingJob}
        onClose={() => setCreatingJob(false)}
        onCreated={() => {
          setCreatingJob(false)
          mutateJobs()
        }}
      />
      <CreateJobDialog
        open={editingJobId !== null}
        editingJobId={editingJobId}
        onClose={() => setEditingJobId(null)}
        onCreated={() => {
          setEditingJobId(null)
          mutateJobs()
        }}
      />

      {/* ── One-shot manual backup ─────────────────────── */}
      <ManualBackupDialog
        open={runningManual}
        onClose={() => setRunningManual(false)}
        onLaunched={() => {
          setRunningManual(false)
          mutateJobs()
          // Refresh archives a few seconds after launch so the new
          // tar.zst (if it's a local backend) appears in the list
          // without waiting for the next 30s SWR tick.
          setTimeout(() => mutateArchives(), 5000)
        }}
      />

      {/* ── Job detail / actions modal ─────────────────────────── */}
      <JobDetailModal
        jobId={viewingJobId}
        onClose={() => setViewingJobId(null)}
        onEdit={(id) => {
          setViewingJobId(null)
          setEditingJobId(id)
        }}
        onRequestDelete={(id) => {
          const job = jobsResp?.jobs.find((j) => j.id === id)
          if (job) {
            setViewingJobId(null)
            setJobToDelete(job)
          }
        }}
        onChanged={() => mutateJobs()}
      />

      {/* ── Delete confirmation ────────────────────────────── */}
      <Dialog open={jobToDelete !== null} onOpenChange={(v) => { if (!v) setJobToDelete(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              Delete backup job?
            </DialogTitle>
            <DialogDescription>
              This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {jobToDelete && (
            <div className="space-y-3 text-sm">
              <div className="rounded-md border border-border bg-background/50 p-3 space-y-1">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Job ID</div>
                <div className="font-mono text-sm">{jobToDelete.id}</div>
                {jobToDelete.attached && jobToDelete.pve_storage && (
                  <>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-2">Type</div>
                    <div className="text-xs">attached to PVE storage <span className="font-mono">{jobToDelete.pve_storage}</span></div>
                  </>
                )}
              </div>
              {jobToDelete.attached ? (
                <p className="text-xs text-muted-foreground">
                  Only the ProxMenux host backup hook is removed.
                  PVE vzdump jobs targeting this storage stay intact and keep running.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  The systemd timer and service for this job will be stopped, disabled and removed.
                  Existing backup archives on disk are NOT deleted.
                </p>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2 mt-2">
            <Button
              variant="ghost"
              onClick={() => setJobToDelete(null)}
              disabled={busyJobId === jobToDelete?.id}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={confirmDeleteJob}
              disabled={busyJobId === jobToDelete?.id}
            >
              {busyJobId === jobToDelete?.id ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Inspect modal — shows manifest summary + lets the operator pick
// a restore mode and run the dry-run preflight + plan against this
// host. No mutating actions; --apply stays on the CLI for 1.3.0.
// ──────────────────────────────────────────────────────────────
function InspectModal({
  archive,
  onClose,
  onDeleted,
}: {
  archive: UnifiedArchive | null
  onClose: () => void
  onDeleted?: () => void
}) {
  const open = archive !== null
  // Aliases to the source-specific payloads — saves on `.local!` /
  // `.remote!` repetition later. PBS and Borg share the same shape.
  const localArc = archive?.source === "local" ? archive.local : undefined
  const remoteArc = archive && archive.source !== "local" ? archive.remote : undefined
  const isRemote = archive?.source === "pbs" || archive?.source === "borg"
  const backendLabel = archive?.source === "pbs" ? "PBS" : archive?.source === "borg" ? "Borg" : "Local"
  const [mode, setMode] = useState<string>("full")
  const [report, setReport] = useState<PreflightReport | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [instructions, setInstructions] = useState<{
    archive_basename: string
    mode_label: string
    shell_command: string
    menu_path: string[]
    reboot_required: boolean
    notes: string[]
  } | null>(null)
  const [fetchingInstructions, setFetchingInstructions] = useState(false)
  const [downloading, setDownloading] = useState(false)
  // Per-archive runner log — only available for local archives, where
  // the runner writes `<stem>.log` next to the `<stem>.tar.zst` in
  // /var/log/proxmenux/backup-jobs/. PBS / Borg snapshots don't have
  // a co-located run log on this host.
  const { data: archiveLog } = useSWR<{
    log_path: string | null
    size: number
    content: string
    tail: string[]
  }>(
    open && archive?.source === "local" && localArc?.id
      ? `/api/host-backups/archives/${encodeURIComponent(localArc.id)}/log`
      : null,
    fetcher,
  )
  const [showArchiveFullLog, setShowArchiveFullLog] = useState(false)
  const [showDeleteArchiveConfirm, setShowDeleteArchiveConfirm] = useState(false)
  const [deletingArchive, setDeletingArchive] = useState(false)
  const [archiveDeleteResult, setArchiveDeleteResult] = useState<string[] | null>(null)

  // Local download — direct file streamed straight from the server.
  const downloadLocalArchive = async () => {
    if (!localArc) return
    setDownloading(true)
    setError(null)
    try {
      const token = typeof window !== "undefined"
        ? localStorage.getItem("proxmenux-auth-token") || ""
        : ""
      const r = await fetch(
        getApiUrl(`/api/host-backups/archives/${encodeURIComponent(localArc.id)}/download`),
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = localArc.id
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      setError(`Download failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setDownloading(false)
    }
  }

  // Remote export-then-download (PBS or Borg) — kicks off the
  // server-side extract + pack, polls until the .tar.zst is ready,
  // then streams it like the local case. Stage feedback (queued /
  // restoring / packing) goes into `exportTask.state` so the modal
  // can show what's happening live.
  const [exportTask, setExportTask] = useState<ExportTask | null>(null)
  const downloadRemoteArchive = async () => {
    if (!remoteArc) return
    setDownloading(true)
    setError(null)
    setExportTask({
      task_id: "",
      backend: remoteArc.backend,
      repo_name: remoteArc.repo_name,
      snapshot: remoteArc.snapshot,
      state: "queued",
      message: "Starting export…",
      size_bytes: 0,
      output_path: null,
      error: null,
    })
    try {
      const started = await fetchApi<{ task_id: string; state: string }>(
        "/api/host-backups/remote-archives/export",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            backend: remoteArc.backend,
            repo_name: remoteArc.repo_name,
            snapshot: remoteArc.snapshot,
          }),
        },
      )
      // Poll until done. The export can take from seconds (small host
      // config) to minutes (multi-GB pxar) — poll every 1.5s so the
      // UI feels responsive without DoS-ing Flask.
      let task: ExportTask | null = null
      while (true) {
        await new Promise((res) => setTimeout(res, 1500))
        task = await fetchApi<ExportTask>(
          `/api/host-backups/remote-archives/export/${encodeURIComponent(started.task_id)}`,
        )
        setExportTask(task)
        if (task.state === "completed" || task.state === "failed") break
      }
      if (!task || task.state !== "completed") {
        throw new Error(task?.error || "export did not complete")
      }
      // Stream the resulting .tar.zst. Server cleans the file up
      // automatically once the response finishes.
      const token = typeof window !== "undefined"
        ? localStorage.getItem("proxmenux-auth-token") || ""
        : ""
      const r = await fetch(
        getApiUrl(`/api/host-backups/remote-archives/export/${encodeURIComponent(started.task_id)}/download`),
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      )
      if (!r.ok) throw new Error(`download HTTP ${r.status}`)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      const safeSnap = remoteArc.snapshot.replace(/\//g, "_")
      a.download = `${remoteArc.backend}-${remoteArc.repo_name}-${safeSnap}.tar.zst`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setExportTask(null)
    } catch (e) {
      setError(`Download failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setDownloading(false)
    }
  }

  const downloadArchive = () => {
    if (isRemote) return downloadRemoteArchive()
    return downloadLocalArchive()
  }

  // Local archive deletion. The backend purges the .tar.zst, the
  // .proxmenux.json sidecar and the matching <stem>.log so the
  // /var/log/proxmenux directory stays in sync with the archive list.
  // Remote archives (PBS / Borg) are not deletable from here — those
  // belong to their own datastore prune policy.
  const deleteLocalArchive = async () => {
    if (!localArc) return
    setDeletingArchive(true)
    setError(null)
    try {
      const resp = await fetchApi<{ status: string; removed: string[] }>(
        `/api/host-backups/archives/${encodeURIComponent(localArc.id)}`,
        { method: "DELETE" },
      )
      setArchiveDeleteResult(resp.removed || [])
      setShowDeleteArchiveConfirm(false)
      if (onDeleted) onDeleted(); else onClose()
    } catch (e) {
      setError(`Failed to delete: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setDeletingArchive(false)
    }
  }

  // Reset instructions when archive or mode changes — the previous
  // command is no longer relevant.
  useEffect(() => {
    setInstructions(null)
  }, [archive, mode])

  const fetchInstructions = async () => {
    if (!localArc) return
    setFetchingInstructions(true)
    setError(null)
    try {
      const res = await fetchApi<typeof instructions extends infer T ? T : never>(
        `/api/host-backups/archives/${encodeURIComponent(localArc.id)}/prepare-restore`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode }),
        }
      ) as NonNullable<typeof instructions>
      setInstructions(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setFetchingInstructions(false)
    }
  }

  const { data: manifest, error: manifestErr } = useSWR<{
    source_host: ManifestSourceHost
    proxmenux_installed_components: Array<{ id: string; version_at_backup: string | null }>
    vms_lxcs_at_backup: { vms: unknown[]; lxcs: unknown[] }
    storage_inventory?: { zfs_pools?: unknown[]; lvm?: { vgs?: unknown[] } }
  }>(
    localArc ? `/api/host-backups/archives/${encodeURIComponent(localArc.id)}/manifest` : null,
    fetcher,
  )

  const runPreflight = async () => {
    if (!localArc) return
    setRunning(true)
    setError(null)
    setReport(null)
    try {
      const res = await fetchApi<PreflightReport>(
        `/api/host-backups/archives/${encodeURIComponent(localArc.id)}/preflight`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode }),
        },
      )
      setReport(res)
    } catch (e: any) {
      setError(e?.message || "Preflight failed")
    } finally {
      setRunning(false)
    }
  }

  // Reset state when archive changes — the key= prop on DialogContent
  // forces React to unmount + remount so all useState() values are
  // discarded automatically. Cleaner than manually tracking each.
  const archiveKey = archive ? `${archive.source}:${archive.display_id}` : ""

  return (
    <>
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent key={archiveKey} className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <DatabaseBackup className="h-5 w-5 text-blue-500" />
            <span className="font-mono text-sm truncate">{archive?.display_id}</span>
            {archive && (
              <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${
                archive.source === "pbs"
                  ? "text-purple-300 border-purple-400/40"
                  : archive.source === "borg"
                    ? "text-cyan-300 border-cyan-400/40"
                    : "text-emerald-300 border-emerald-400/40"
              }`}>
                {archive.source}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {isRemote
              ? `Inspect the ${backendLabel} snapshot metadata and download it as a .tar.zst — the server extracts it on demand only when you click Download.`
              : "Pick a restore mode, optionally run the preflight check, then get the exact shell command to apply the restore. Nothing on this host is changed from here — the apply step happens from a terminal."}
          </DialogDescription>
        </DialogHeader>

        {/* ── Remote snapshot view (PBS or Borg) — info card + on-demand export-then-download. */}
        {isRemote && remoteArc && (
          <div className="space-y-3">
            <div className="rounded-md border border-border bg-background/40 p-3 space-y-1 text-xs">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{backendLabel} snapshot</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
                <div><span className="text-muted-foreground">Repository:</span> <code className="font-mono">{remoteArc.repo_repository}</code></div>
                <div><span className="text-muted-foreground">Repo name:</span> <code className="font-mono">{remoteArc.repo_name}</code></div>
                <div>
                  <span className="text-muted-foreground">{remoteArc.backend === "pbs" ? "Backup group:" : "Archive name:"}</span>{" "}
                  <code className="font-mono">{remoteArc.backend === "pbs" ? `${remoteArc.backup_type}/${remoteArc.backup_id}` : remoteArc.backup_id}</code>
                </div>
                <div><span className="text-muted-foreground">Snapshot time:</span> {formatMtime(remoteArc.backup_time)}</div>
                {remoteArc.size_bytes > 0 && <div><span className="text-muted-foreground">Size:</span> {formatStorage(remoteArc.size_bytes)}</div>}
                {remoteArc.owner && <div><span className="text-muted-foreground">Owner:</span> <code className="font-mono">{remoteArc.owner}</code></div>}
                {remoteArc.borg_id && <div className="sm:col-span-2"><span className="text-muted-foreground">Borg id:</span> <code className="font-mono text-[10px] break-all">{remoteArc.borg_id}</code></div>}
              </div>
              {remoteArc.files.length > 0 && (
                <div className="pt-1 mt-1 border-t border-border/50">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Files in this snapshot</div>
                  <ul className="space-y-0.5">
                    {remoteArc.files.map((f) => (
                      <li key={f.filename} className="font-mono text-[11px] flex items-center justify-between gap-2">
                        <span>{f.filename}</span>
                        <span className="text-muted-foreground">{formatStorage(f.size)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            <div className="rounded-md border border-border bg-background/40 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <h3 className="text-sm font-medium">Download this snapshot</h3>
                  <p className="text-[11px] text-muted-foreground">
                    The server will {remoteArc.backend === "pbs" ? "restore the snapshot from PBS" : "borg-extract the archive"} and pack it as a <code className="font-mono">.tar.zst</code>, then stream it to your browser. The extraction only starts when you click Download.
                  </p>
                </div>
                <Button onClick={downloadArchive} disabled={downloading}>
                  {downloading ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4 mr-2" />
                  )}
                  Download
                </Button>
              </div>

              {exportTask && (
                <div className="text-[11px] space-y-1 pt-2 border-t border-border/50">
                  <div className="flex items-center gap-2">
                    <Loader2 className={`h-3.5 w-3.5 ${exportTask.state === "completed" || exportTask.state === "failed" ? "" : "animate-spin"}`} />
                    <span className="font-medium capitalize">{exportTask.state}</span>
                    <span className="text-muted-foreground">— {exportTask.message}</span>
                  </div>
                  {exportTask.state === "failed" && exportTask.error && (
                    <div className="text-red-500 mt-1">{exportTask.error}</div>
                  )}
                  {exportTask.state === "completed" && exportTask.size_bytes > 0 && (
                    <div className="text-emerald-400">Packed size: {formatStorage(exportTask.size_bytes)}</div>
                  )}
                </div>
              )}

              {error && (
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
                  {error}
                </div>
              )}
            </div>

            <p className="text-[11px] text-muted-foreground italic">
              {remoteArc.backend === "pbs"
                ? "Restore-to-this-host for PBS snapshots is best done from the PBS side with proxmox-backup-client restore. Use Download to pull the snapshot to your computer for off-host inspection or cross-host transfer."
                : "Restore-to-this-host for Borg archives is best done with borg extract. Use Download to pull the archive to your computer for off-host inspection or cross-host transfer."}
            </p>
          </div>
        )}

        {/* ── Local archive view — full restore wizard (manifest + preflight + apply instructions). */}
        {archive?.source === "local" && (<>
        {/* Manifest summary — optional. If the archive has no manifest
            (older backup format), we just skip it instead of blocking
            the operator from continuing with the restore. */}
        {manifestErr ? (
          <div className="text-xs text-muted-foreground py-2 italic">
            This archive doesn't carry a manifest snapshot — you can still pick a restore mode and get the instructions below.
          </div>
        ) : !manifest ? (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Reading manifest...
          </div>
        ) : (
          <ManifestSummary manifest={manifest} />
        )}

        {/* ── Run log — what the scheduler wrote for THIS archive ── */}
        {archiveLog && archiveLog.log_path && archiveLog.tail.length > 0 && (
          <section className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-green-500">
              <FileText className="h-3.5 w-3.5" /> Run log
            </h4>
            <div className="rounded-md border border-border bg-background/60 p-2">
              <pre className="text-[11px] font-mono whitespace-pre-wrap break-all max-h-48 overflow-auto text-foreground/90">
{archiveLog.tail.join("\n")}
              </pre>
              <div className="flex items-center justify-between mt-2">
                <span className="text-[10px] text-muted-foreground inline-flex items-center gap-2">
                  <span>tail · {formatBytes(archiveLog.size)}</span>
                  <span className="font-mono break-all">{archiveLog.log_path}</span>
                </span>
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setShowArchiveFullLog(true)}>
                  <FileText className="h-3.5 w-3.5 mr-1" />
                  Open full log
                </Button>
              </div>
            </div>
          </section>
        )}

        {/* Mode selector + main "Restore" action */}
        <div className="border-t border-border pt-4 space-y-3">
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-muted-foreground block mb-1.5">
                Restore mode
              </label>
              <Select value={mode} onValueChange={setMode}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="full">Full — apply everything</SelectItem>
                  <SelectItem value="base">Base — everything except network</SelectItem>
                  <SelectItem value="storage_only">Storage only</SelectItem>
                  <SelectItem value="network_only">Network only</SelectItem>
                  <SelectItem value="custom">Custom — paths picked manually</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button
              variant="outline"
              onClick={downloadArchive}
              disabled={downloading}
              title="Download the .tar.zst archive to your computer for off-host storage"
            >
              {downloading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Download className="h-4 w-4 mr-2" />
              )}
              Download
            </Button>
            <Button
              variant="outline"
              className="bg-red-500/10 border-red-500/40 !text-red-400 hover:bg-red-500/20 hover:!text-red-300"
              onClick={() => setShowDeleteArchiveConfirm(true)}
              disabled={deletingArchive}
              title="Permanently delete this archive, its sidecar and its run log"
            >
              {deletingArchive ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Delete
            </Button>
            <Button
              variant="outline"
              onClick={runPreflight}
              disabled={running}
              title="Optional: dry-run a preflight check against this host before restoring"
            >
              {running ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <PlayCircle className="h-4 w-4 mr-2" />
              )}
              Preflight check
            </Button>
            <Button
              onClick={fetchInstructions}
              disabled={fetchingInstructions}
              title="Get the shell command to apply this restore"
            >
              {fetchingInstructions ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <DatabaseBackup className="h-4 w-4 mr-2" />
              )}
              Restore
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            The archive downloads as a <code className="font-mono">.tar.zst</code> file. To extract:
            {" "}<code className="font-mono">tar -I zstd -xf {localArc?.id || "&lt;file&gt;"}</code>
            {" "}(Linux/macOS with <code className="font-mono">zstd</code> installed). On Windows, 7-Zip 21.0+ opens it natively. Double-click won't work — no OS opens <code className="font-mono">.zst</code> out of the box.
          </p>

          {error && (
            <div className="text-sm text-red-500 p-2 rounded-md border border-red-500/30 bg-red-500/10">
              {error}
            </div>
          )}

          {report && <PreflightReportView report={report} />}

          {/* Restore instructions — appear whenever the operator clicks
              "Restore" (with or without a preflight beforehand). */}
          {instructions && (
            <div className="space-y-2 pt-2 border-t border-border">
              <h3 className="text-sm font-medium">Apply this restore</h3>
              <div className="space-y-2 rounded-md border border-border bg-background/40 p-3 text-xs">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-sm font-medium">{instructions.archive_basename}</span>
                  <Badge variant="outline" className="text-[10px]">{instructions.mode_label}</Badge>
                  {instructions.reboot_required && (
                    <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/40">
                      reboot required after
                    </Badge>
                  )}
                </div>

                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Run this from a terminal:</div>
                  <code
                    className="block font-mono text-xs px-3 py-2 rounded bg-muted border border-border cursor-text select-all"
                    onClick={(e) => {
                      const sel = window.getSelection()
                      if (sel) {
                        sel.removeAllRanges()
                        const range = document.createRange()
                        range.selectNodeContents(e.currentTarget)
                        sel.addRange(range)
                      }
                    }}
                  >
                    {instructions.shell_command}
                  </code>
                </div>

                {instructions.menu_path.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Then:</div>
                    <ol className="space-y-0.5">
                      {instructions.menu_path.map((step, i) => (
                        <li key={i} className="font-mono text-[11px] whitespace-pre">{step}</li>
                      ))}
                    </ol>
                  </div>
                )}

                {instructions.notes.length > 0 && (
                  <div className="space-y-1 pt-1 border-t border-border/50">
                    {instructions.notes.map((note, i) => (
                      <p key={i} className="text-[11px] text-amber-500 flex items-start gap-1.5">
                        <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                        <span>{note}</span>
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        </>)}
      </DialogContent>
    </Dialog>

    {/* ── Confirm archive deletion ───────────────────────────── */}
    <Dialog open={showDeleteArchiveConfirm} onOpenChange={setShowDeleteArchiveConfirm}>
      <DialogContent className="max-w-md bg-card border-border">
        <DialogHeader>
          <DialogTitle className="text-base flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-red-500" />
            Delete archive
          </DialogTitle>
          <DialogDescription className="text-xs">
            Removes the archive, its sidecar JSON and the matching run log. The action is permanent — restore needs an off-host copy.
          </DialogDescription>
        </DialogHeader>
        <div className="text-sm font-mono px-3 py-2 rounded-md border border-border bg-background/40 break-all">
          {localArc?.id}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setShowDeleteArchiveConfirm(false)} disabled={deletingArchive}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={deleteLocalArchive} disabled={deletingArchive}>
            {deletingArchive ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4 mr-2" />
            )}
            Delete archive
          </Button>
        </div>
      </DialogContent>
    </Dialog>

    {/* ── Full run log viewer ─────────────────────────────────── */}
    <Dialog open={showArchiveFullLog} onOpenChange={setShowArchiveFullLog}>
      <DialogContent className="max-w-4xl bg-card border-border">
        <DialogHeader>
          <DialogTitle className="text-base flex items-center gap-2">
            <FileText className="h-5 w-5 text-blue-500" />
            Run log
          </DialogTitle>
          <DialogDescription className="text-xs font-mono break-all">
            {archiveLog?.log_path}
          </DialogDescription>
        </DialogHeader>
        <pre className="text-[11px] font-mono whitespace-pre-wrap break-all max-h-[60vh] overflow-auto rounded-md border border-border bg-background/60 p-3 text-foreground/90">
{archiveLog?.content ?? ""}
        </pre>
        <div className="flex justify-end">
          <Button variant="ghost" onClick={() => setShowArchiveFullLog(false)}>Close</Button>
        </div>
      </DialogContent>
    </Dialog>
    </>
  )
}

// ── Manifest summary panel ───────────────────────────────────
function ManifestSummary({
  manifest,
}: {
  manifest: {
    source_host: ManifestSourceHost
    proxmenux_installed_components: Array<{ id: string; version_at_backup: string | null }>
    vms_lxcs_at_backup: { vms: unknown[]; lxcs: unknown[] }
    storage_inventory?: { zfs_pools?: unknown[]; lvm?: { vgs?: unknown[] } }
  }
}) {
  const sh = manifest.source_host
  const zfsCount = manifest.storage_inventory?.zfs_pools?.length ?? 0
  const lvmCount = manifest.storage_inventory?.lvm?.vgs?.length ?? 0
  return (
    <div className="space-y-3 py-2">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
        <Field icon={<Server className="h-3.5 w-3.5" />} label="Source host" value={sh.hostname} />
        <Field label="PVE version" value={sh.pve_version || "—"} />
        <Field label="Roles" value={sh.roles.join(", ")} />
        <Field label="Kernel" value={sh.kernel} mono />
        <Field label="Boot mode" value={sh.boot_mode} />
        <Field label="Memory" value={`${Math.round(sh.memory_kb / 1024)} MB`} />
        <Field label="ZFS pools" value={String(zfsCount)} />
        <Field label="LVM VGs" value={String(lvmCount)} />
        <Field label="VMs / LXCs" value={`${manifest.vms_lxcs_at_backup.vms.length} VM / ${manifest.vms_lxcs_at_backup.lxcs.length} LXC`} />
      </div>
      {manifest.proxmenux_installed_components.length > 0 && (
        <div className="text-xs">
          <div className="text-muted-foreground mb-1">ProxMenux components at backup time:</div>
          <div className="flex flex-wrap gap-1.5">
            {manifest.proxmenux_installed_components.map((c) => (
              <Badge key={c.id} variant="outline" className="font-mono text-[10px]">
                {c.id}{c.version_at_backup ? ` @ ${c.version_at_backup}` : ""}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ icon, label, value, mono, labelClassName }: { icon?: React.ReactNode; label: string; value: string; mono?: boolean; labelClassName?: string }) {
  return (
    <div className="min-w-0">
      <div className={`text-[10px] uppercase tracking-wider flex items-center gap-1 ${labelClassName ?? "text-muted-foreground"}`}>
        {icon}
        {label}
      </div>
      <div className={`${mono ? "font-mono break-all" : "break-words"}`} title={value}>
        {value}
      </div>
    </div>
  )
}

// Renders the retention policy as a row of labeled badges. The runner's
// .env stores six discrete keys (KEEP_LAST / HOURLY / DAILY / WEEKLY /
// MONTHLY / YEARLY); the original UI dumped them as a comma-separated
// `key=val, key=val…` string which read like a config file. This view
// drops zero-valued entries and presents what survives as ordered chips.
function RetentionDisplay({ retention }: { retention: Record<string, string | undefined> }) {
  const order: Array<[string, string]> = [
    ["keep_last", "last"],
    ["keep_hourly", "hourly"],
    ["keep_daily", "daily"],
    ["keep_weekly", "weekly"],
    ["keep_monthly", "monthly"],
    ["keep_yearly", "yearly"],
  ]
  const items = order
    .map(([k, lbl]) => {
      const v = (retention[k] || "").trim()
      const n = Number.parseInt(v, 10)
      if (!v || !Number.isFinite(n) || n <= 0) return null
      return { label: lbl, value: n }
    })
    .filter((x): x is { label: string; value: number } => x !== null)

  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider flex items-center gap-1 text-green-500/90">
        <Archive className="h-3 w-3 text-green-500/80" /> retention
      </div>
      {items.length === 0 ? (
        <div className="text-muted-foreground italic text-xs mt-1">No retention rules — backups will accumulate.</div>
      ) : (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {items.map((it) => (
            <span
              key={it.label}
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-border bg-background/60"
            >
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{it.label}</span>
              <span className="font-mono text-xs text-foreground">{it.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// Renders the backup profile paths as a 2-column grid of monospaced
// rows instead of a single ` · `-separated line. With ~30 paths the
// old layout forced a horizontal scroll on the dialog because the
// line couldn't be wrapped without breaking the path identifiers.
function PathsDisplay({ paths }: { paths: string[] }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider flex items-center gap-1 text-green-500/90">
        <HardDrive className="h-3 w-3 text-green-500/80" /> paths
        <span className="ml-1 text-muted-foreground normal-case">({paths.length})</span>
      </div>
      <div className="mt-1 grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-0.5">
        {paths.map((p) => (
          <code
            key={p}
            className="font-mono text-[11px] text-foreground/90 truncate"
            title={p}
          >
            {p}
          </code>
        ))}
      </div>
    </div>
  )
}

// ── Preflight report view ────────────────────────────────────
function PreflightReportView({ report }: { report: PreflightReport }) {
  const { summary, checks } = report.preflight
  const passColor = "text-emerald-500"
  const warnColor = "text-amber-500"
  const failColor = "text-red-500"

  return (
    <div className="space-y-3 border border-border rounded-md p-3 bg-muted/30">
      {/* Summary line */}
      <div className="flex items-center gap-4 text-sm">
        <span className={`inline-flex items-center gap-1 ${passColor}`}>
          <CheckCircle2 className="h-4 w-4" />
          {summary.pass} pass
        </span>
        <span className={`inline-flex items-center gap-1 ${warnColor}`}>
          <AlertTriangle className="h-4 w-4" />
          {summary.warn} warn
        </span>
        <span className={`inline-flex items-center gap-1 ${failColor}`}>
          <XCircle className="h-4 w-4" />
          {summary.fail} fail
        </span>
        {summary.fail > 0 && (
          <span className="ml-auto text-xs text-red-500">
            --apply would be refused
          </span>
        )}
      </div>

      {/* Per-check list */}
      <div className="space-y-1.5">
        {checks.map((c) => {
          const color =
            c.severity === "pass" ? passColor :
            c.severity === "warn" ? warnColor :
            failColor
          const Icon =
            c.severity === "pass" ? CheckCircle2 :
            c.severity === "warn" ? AlertTriangle :
            XCircle
          return (
            <div key={c.id} className="flex items-start gap-2 text-xs">
              <Icon className={`h-3.5 w-3.5 ${color} flex-shrink-0 mt-0.5`} />
              <div className="flex-1 min-w-0">
                <span className={`font-mono ${color}`}>{c.id}</span>
                <span className="text-muted-foreground ml-2">{c.message}</span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Storage / network counts */}
      <div className="grid grid-cols-2 gap-3 text-xs pt-2 border-t border-border/40">
        <div>
          <div className="text-muted-foreground mb-1">Storage [in mode: {String(report.storage.in_selected_mode)}]</div>
          <div>
            {report.storage.zfs.length} ZFS pool(s) ·
            {" "}{report.storage.lvm.length} LVM VG(s) ·
            {" "}{report.storage.pve_storage.length} PVE storage(s)
          </div>
        </div>
        <div>
          <div className="text-muted-foreground mb-1">Network [in mode: {String(report.network.in_selected_mode)}]</div>
          <div>
            {report.network.keep.length} keep ·
            {" "}{report.network.remap.length} remap ·
            {" "}{report.network.orphan.length} orphan ·
            {" "}{report.network.new.length} new
          </div>
        </div>
      </div>

      {/* Driver plan */}
      {report.driver_reinstall.plan.length > 0 && (
        <div className="text-xs pt-2 border-t border-border/40">
          <div className="text-muted-foreground mb-1.5">Driver reinstall plan ({report.driver_reinstall.plan.length})</div>
          <div className="space-y-1">
            {report.driver_reinstall.plan.map((p) => (
              <div key={p.component_id} className="flex items-center justify-between gap-2">
                <span className="font-mono">{p.component_id}</span>
                <Badge variant="outline" className="text-[10px]">{p.action}</Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Abort reason (if --apply would have been refused) */}
      {report.abort_reason && (
        <div className="text-xs text-red-500 p-2 border border-red-500/30 rounded-md bg-red-500/10">
          {report.abort_reason}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Create job wizard (A3.1 — attached jobs only).
//
// Pre-loads three things in parallel so the form can render selects
// the moment the operator opens it:
//   - PVE vzdump jobs (filtered by backend once they pick one)
//   - Pre-configured destinations (PBS repos, Borg targets, local)
//   - Default profile path list (used when profile_mode === "default"
//     and also as the pool the custom checklist is populated from)
// ──────────────────────────────────────────────────────────────

interface PveVzdumpJob {
  id: string
  storage: string | null
  storage_type: string | null
  schedule: string | null
  prune: string | null
  enabled: boolean
}

interface PbsRepo {
  name: string
  repository: string
  fingerprint: string | null
  source: "proxmox" | "manual"
}

interface BorgRepo {
  name: string
  repository: string
  ssh_key_path?: string
}

interface LocalTargetEntry {
  path: string
  source: "default" | "custom"
  removable: boolean
}

interface LocalTarget {
  configured: string | null
  default: string
  effective: string
  // Multi-path layout: the default plus any custom paths stacked on
  // top. Present on every recent backend; older deployments without
  // this field fall back to the single configured/effective accessors.
  entries?: LocalTargetEntry[]
}

interface DestinationsResp {
  pbs: PbsRepo[]
  borg: BorgRepo[]
  local: LocalTarget
}

interface JobDetail {
  id: string
  attached: boolean
  enabled: boolean
  manual: boolean
  method: string
  destination: string
  on_calendar: string             // human-formatted ("attached → storage:pbs" or "*-*-* 02:00")
  next_run: string | null
  pve_storage: string | null
  pve_parent_job_id: string | null
  profile_mode: string
  paths: string[]
  on_calendar_raw: string | null
  retention: Record<string, string | undefined>
  pbs_repository: string | null
  pbs_backup_id: string | null
  pbs_fingerprint: string | null
  has_pbs_password: boolean
  local_dest_dir: string | null
  local_archive_ext: string | null
  borg_repo: string | null
  borg_encrypt_mode: string
  has_borg_passphrase: boolean
  // Log fields from Sprint Pulido P1
  last_result: string | null      // "ok" / "failed" / etc.
  last_run_at: string | null      // ISO-8601
  last_log_path: string | null
  last_log_size: number
  last_log_tail: string[]
}

function CreateJobDialog({
  open,
  onClose,
  onCreated,
  editingJobId,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
  editingJobId?: string | null
}) {
  const isEdit = !!editingJobId
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1)
  const [jobId, setJobId] = useState("")
  const [backend, setBackend] = useState<"pbs" | "local" | "borg">("pbs")
  const [mode, setMode] = useState<"new" | "attach">("new")
  const [pveJobId, setPveJobId] = useState<string>("")
  const [profileMode, setProfileMode] = useState<"default" | "custom">("default")
  const [customPaths, setCustomPaths] = useState<Set<string>>(new Set())

  // New (timer-based) mode fields — onCalendar is computed from the
  // builder controls below; the raw expression is only directly edited
  // when scheduleType === "advanced".
  const [scheduleType, setScheduleType] = useState<"daily" | "hourly" | "weekly" | "monthly" | "advanced">("daily")
  const [scheduleTime, setScheduleTime] = useState<string>("02:00")
  const [scheduleMinute, setScheduleMinute] = useState<string>("0")
  const [scheduleWeekdays, setScheduleWeekdays] = useState<Set<string>>(new Set(["Sun"]))
  const [scheduleDayOfMonth, setScheduleDayOfMonth] = useState<string>("1")
  const [scheduleAdvanced, setScheduleAdvanced] = useState<string>("daily")
  const [keepLast, setKeepLast] = useState<string>("7")
  const [keepHourly, setKeepHourly] = useState<string>("0")
  const [keepDaily, setKeepDaily] = useState<string>("7")
  const [keepWeekly, setKeepWeekly] = useState<string>("4")
  const [keepMonthly, setKeepMonthly] = useState<string>("3")
  const [keepYearly, setKeepYearly] = useState<string>("0")

  // Backend-specific fields
  const [pbsRepository, setPbsRepository] = useState<string>("")
  const [pbsBackupId, setPbsBackupId] = useState<string>("")
  const [localDestDir, setLocalDestDir] = useState<string>("")
  const [borgRepoSelected, setBorgRepoSelected] = useState<string>("")
  const [borgPassphrase, setBorgPassphrase] = useState<string>("")
  const [borgEncryptMode, setBorgEncryptMode] = useState<"none" | "repokey" | "keyfile" | "authenticated">("repokey")

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Build the canonical OnCalendar string from the builder controls.
  // The dropdown plus the small sub-inputs are friendlier than asking
  // the operator to remember the systemd Calendar Events grammar.
  const padHH = (s: string) => {
    const [hh = "00", mm = "00"] = s.split(":")
    return `${hh.padStart(2, "0")}:${mm.padStart(2, "0")}:00`
  }
  let onCalendar = "daily"
  if (scheduleType === "daily") {
    onCalendar = `*-*-* ${padHH(scheduleTime)}`
  } else if (scheduleType === "hourly") {
    const m = Math.max(0, Math.min(59, Number(scheduleMinute) || 0))
    onCalendar = `*-*-* *:${String(m).padStart(2, "0")}:00`
  } else if (scheduleType === "weekly") {
    const days = Array.from(scheduleWeekdays)
    onCalendar = days.length > 0
      ? `${days.join(",")} *-*-* ${padHH(scheduleTime)}`
      : `*-*-* ${padHH(scheduleTime)}`
  } else if (scheduleType === "monthly") {
    const d = Math.max(1, Math.min(31, Number(scheduleDayOfMonth) || 1))
    onCalendar = `*-*-${String(d).padStart(2, "0")} ${padHH(scheduleTime)}`
  } else if (scheduleType === "advanced") {
    onCalendar = scheduleAdvanced.trim()
  }

  // Edit mode: fetch the full job (paths, retention, backend-specific) once
  // the dialog opens, then pre-populate the form fields on arrival.
  const { data: jobDetail } = useSWR<JobDetail>(
    open && isEdit ? `/api/host-backups/jobs/${encodeURIComponent(editingJobId || "")}` : null,
    fetcher,
  )

  const [editPreloaded, setEditPreloaded] = useState(false)
  // Snapshot of the job's backend/mode at the moment we entered edit
  // mode, so Step 5 can call out a change explicitly ("you're now
  // configuring a Borg destination" etc.) instead of just dropping the
  // operator into an unfamiliar set of fields.
  const [originalBackend, setOriginalBackend] = useState<"pbs" | "local" | "borg" | null>(null)
  const [originalMode, setOriginalMode] = useState<"new" | "attach" | null>(null)
  useEffect(() => {
    if (!isEdit || !jobDetail || editPreloaded) return
    setJobId(jobDetail.id)
    setBackend((jobDetail.method as "pbs" | "local" | "borg") || "pbs")
    setMode(jobDetail.attached ? "attach" : "new")
    setOriginalBackend((jobDetail.method as "pbs" | "local" | "borg") || "pbs")
    setOriginalMode(jobDetail.attached ? "attach" : "new")
    setProfileMode((jobDetail.profile_mode as "default" | "custom") || "default")
    if (jobDetail.profile_mode === "custom") {
      setCustomPaths(new Set(jobDetail.paths))
    }
    if (!jobDetail.attached && jobDetail.on_calendar_raw) {
      setScheduleType("advanced")
      setScheduleAdvanced(jobDetail.on_calendar_raw)
    }
    if (jobDetail.attached && jobDetail.pve_parent_job_id) {
      setPveJobId(jobDetail.pve_parent_job_id)
    }
    const r = jobDetail.retention || {}
    if (r.keep_last !== undefined) setKeepLast(String(r.keep_last))
    if (r.keep_hourly !== undefined) setKeepHourly(String(r.keep_hourly))
    if (r.keep_daily !== undefined) setKeepDaily(String(r.keep_daily))
    if (r.keep_weekly !== undefined) setKeepWeekly(String(r.keep_weekly))
    if (r.keep_monthly !== undefined) setKeepMonthly(String(r.keep_monthly))
    if (r.keep_yearly !== undefined) setKeepYearly(String(r.keep_yearly))
    if (jobDetail.pbs_repository) setPbsRepository(jobDetail.pbs_repository)
    if (jobDetail.pbs_backup_id) setPbsBackupId(jobDetail.pbs_backup_id)
    if (jobDetail.local_dest_dir) setLocalDestDir(jobDetail.local_dest_dir)
    if (jobDetail.borg_repo) setBorgRepoSelected(jobDetail.borg_repo)
    if (jobDetail.borg_encrypt_mode) {
      setBorgEncryptMode(jobDetail.borg_encrypt_mode as "none" | "repokey" | "keyfile" | "authenticated")
    }
    setEditPreloaded(true)
  }, [isEdit, jobDetail, editPreloaded])

  // Reset the preload flag whenever the dialog closes so the next open
  // (potentially for a different job) re-populates fresh.
  useEffect(() => {
    if (!open) {
      setEditPreloaded(false)
      setOriginalBackend(null)
      setOriginalMode(null)
    }
  }, [open])

  const { data: pveJobsResp } = useSWR<{ jobs: PveVzdumpJob[] }>(
    open && mode === "attach" && backend !== "borg" ? `/api/host-backups/pve-vzdump-jobs?backend=${backend}` : null,
    fetcher,
  )

  // Live calendar preview — only fetch when we're actually on Step 3 in
  // "new" mode, otherwise the request is noise.
  const calendarPreviewKey = open && mode === "new" && step === 3 && onCalendar.trim().length > 0
    ? `calendar-preview::${onCalendar}`
    : null
  const { data: calendarPreview } = useSWR<{
    valid: boolean
    error?: string
    normalized?: string
    next_elapse?: string
    from_now?: string
  }>(
    calendarPreviewKey,
    () =>
      fetchApi("/api/host-backups/calendar-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expr: onCalendar }),
      }),
    { dedupingInterval: 400 },
  )
  const { data: destResp, mutate: mutateDest } = useSWR<DestinationsResp>(
    open ? "/api/host-backups/destinations" : null,
    fetcher,
  )
  const { data: pathsResp } = useSWR<{ paths: string[] }>(
    open ? "/api/host-backups/default-paths" : null,
    fetcher,
  )
  // The wizard can spawn AddDestinationDialog inline so the operator
  // configures a PBS / Borg destination without leaving the flow.
  // When AddDestinationDialog saves, we capture the new repository
  // string and auto-select it on the next destResp refresh — saves the
  // operator from picking what they just configured from the dropdown.
  const [addingDestType, setAddingDestType] = useState<"pbs" | "borg" | "local" | null>(null)
  const [pendingAutoSelectDest, setPendingAutoSelectDest] = useState<{ kind: "pbs" | "borg"; repository: string } | null>(null)

  // When the destinations load, auto-pick the first PBS repo + fill in
  // the fingerprint reference so the operator doesn't have to navigate
  // away just to copy it. Same convenience for the backup-id.
  const selectedPbs: PbsRepo | undefined =
    destResp?.pbs?.find((r) => r.repository === pbsRepository) ?? destResp?.pbs?.[0]

  // Reset state on open / backend change
  useEffect(() => {
    if (!open) {
      setStep(1)
      setJobId("")
      setBackend("pbs")
      setMode("new")
      setPveJobId("")
      setProfileMode("default")
      setCustomPaths(new Set())
      setScheduleType("daily")
      setScheduleTime("02:00")
      setScheduleMinute("0")
      setScheduleWeekdays(new Set(["Sun"]))
      setScheduleDayOfMonth("1")
      setScheduleAdvanced("daily")
      setKeepLast("7")
      setKeepHourly("0")
      setKeepDaily("7")
      setKeepWeekly("4")
      setKeepMonthly("3")
      setKeepYearly("0")
      setPbsRepository("")
      setPbsBackupId("")
      setLocalDestDir("")
      setBorgRepoSelected("")
      setBorgPassphrase("")
      setBorgEncryptMode("repokey")
      setError(null)
      setSubmitting(false)
    }
  }, [open])

  // Borg can only be timer-based; coerce mode back to "new" if the
  // operator picks borg after having selected attach.
  useEffect(() => {
    if (backend === "borg" && mode === "attach") {
      setMode("new")
    }
  }, [backend, mode])

  useEffect(() => {
    setPveJobId("")
  }, [backend, mode])

  useEffect(() => {
    if (backend === "pbs" && !pbsRepository && destResp?.pbs?.length) {
      setPbsRepository(destResp.pbs[0].repository)
    }
    if (backend === "borg" && !borgRepoSelected && destResp?.borg?.length) {
      setBorgRepoSelected(destResp.borg[0].repository)
    }
  }, [backend, destResp, pbsRepository, borgRepoSelected])

  useEffect(() => {
    if (!pendingAutoSelectDest || !destResp) return
    if (pendingAutoSelectDest.kind === "pbs") {
      const hit = destResp.pbs?.find((r) => r.repository === pendingAutoSelectDest.repository)
      if (hit) {
        setPbsRepository(hit.repository)
        setPendingAutoSelectDest(null)
      }
    } else {
      const hit = destResp.borg?.find((r) => r.repository === pendingAutoSelectDest.repository)
      if (hit) {
        setBorgRepoSelected(hit.repository)
        setPendingAutoSelectDest(null)
      }
    }
  }, [destResp, pendingAutoSelectDest])

  const togglePath = (path: string) => {
    setCustomPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const selectedPveJob: PveVzdumpJob | undefined = pveJobsResp?.jobs?.find((j) => j.id === pveJobId)
  const selectedBorgRepo: BorgRepo | undefined = destResp?.borg?.find((r) => r.repository === borgRepoSelected)

  // ── Step validation gates ──
  const idValid = /^[a-zA-Z0-9_-]+$/.test(jobId) && jobId.length > 0
  const canAdvanceFrom1 = idValid
  const canAdvanceFrom2 = true   // selecting New/Attach is always possible

  // Step 3 depends on mode. For "new" we additionally block advancing
  // if the live calendar preview already came back invalid, or if
  // weekly was picked without any day selected.
  const canAdvanceFrom3 =
    mode === "attach"
      ? !!pveJobId
      : onCalendar.trim().length > 0
        && (calendarPreview === undefined || calendarPreview.valid !== false)
        && (scheduleType !== "weekly" || scheduleWeekdays.size > 0)

  // Step 4: profile
  const canAdvanceFrom4 =
    profileMode === "default" || (profileMode === "custom" && customPaths.size > 0)

  // Step 5 (submit) — backend-specific requirements
  const backendValid =
    backend === "pbs"
      ? !!pbsRepository
      : backend === "local"
        ? true
        : /* borg */ !!borgRepoSelected && (borgEncryptMode === "none" || !!borgPassphrase)

  const canSubmit =
    canAdvanceFrom1 && canAdvanceFrom2 && canAdvanceFrom3 && canAdvanceFrom4 && backendValid

  async function handleCreate() {
    if (!canSubmit) return
    if (mode === "attach" && !selectedPveJob) return
    setSubmitting(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        id: jobId,
        backend,
        attached: mode === "attach",
        profile_mode: profileMode,
        enabled: true,
      }
      if (mode === "attach" && selectedPveJob) {
        body.pve_storage = selectedPveJob.storage
        body.pve_parent_job_id = selectedPveJob.id
      } else {
        body.on_calendar = onCalendar.trim()
        body.retention = {
          keep_last: Number(keepLast) || 0,
          keep_hourly: Number(keepHourly) || 0,
          keep_daily: Number(keepDaily) || 0,
          keep_weekly: Number(keepWeekly) || 0,
          keep_monthly: Number(keepMonthly) || 0,
          keep_yearly: Number(keepYearly) || 0,
        }
      }
      if (profileMode === "custom") {
        body.paths = Array.from(customPaths)
      }
      if (backend === "pbs") {
        body.pbs_repository = pbsRepository
        body.pbs_password = ""
        if (pbsBackupId) body.pbs_backup_id = pbsBackupId
        if (selectedPbs?.fingerprint) body.pbs_fingerprint = selectedPbs.fingerprint
      } else if (backend === "local") {
        if (localDestDir.trim()) body.local_dest_dir = localDestDir.trim()
      } else if (backend === "borg") {
        body.borg_repo = borgRepoSelected
        body.borg_passphrase = borgPassphrase
        body.borg_encrypt_mode = borgEncryptMode
      }
      // fetchApi returns the parsed JSON and throws (with the backend's
      // error message in `error.message` when the body was JSON) on any
      // non-2xx status — no need to inspect .ok or call .json() ourselves.
      const url = isEdit
        ? `/api/host-backups/jobs/${encodeURIComponent(editingJobId || "")}`
        : "/api/host-backups/jobs"
      await fetchApi(url, {
        method: isEdit ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const compatibleJobs = pveJobsResp?.jobs ?? []
  const defaultPaths = pathsResp?.paths ?? []

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {isEdit ? (
              <Pencil className="h-5 w-5 text-blue-500" />
            ) : (
              <Plus className="h-5 w-5 text-blue-500" />
            )}
            {isEdit ? "Edit scheduled backup job" : "Create scheduled backup job"}
          </DialogTitle>
          <DialogDescription>
            Step {step} of 5 · {mode === "attach" ? "Attached to PVE vzdump" : "Standalone scheduled job"}
          </DialogDescription>
        </DialogHeader>

        {/* Step progress bar */}
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <div
              key={n}
              className={`h-1 flex-1 rounded-full ${n <= step ? "bg-blue-500" : "bg-border"}`}
            />
          ))}
        </div>

        <div className="overflow-y-auto pr-2 -mr-2 space-y-4 flex-1">
          {/* ── Step 1: ID + Backend ─────────────────────── */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <Label htmlFor="jobId">Job name</Label>
                <Input
                  id="jobId"
                  value={jobId}
                  onChange={(e) => setJobId(e.target.value)}
                  disabled={isEdit}
                  className="font-mono mt-1"
                  placeholder="my-host-backup"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  {isEdit
                    ? "The job name can't be changed. Delete and recreate the job if you want to rename it."
                    : <>A short name to identify this job in the list, logs, and shell menu. Letters, digits, <code className="font-mono">_</code> and <code className="font-mono">-</code> only (no spaces or accents).</>}
                </p>
                {!idValid && jobId.length > 0 && !isEdit && (
                  <p className="text-xs text-red-500 mt-1">Invalid characters. Use letters, digits, _ or -.</p>
                )}
              </div>

              <div>
                <Label>Backend</Label>
                {isEdit && (
                  <p className="text-xs text-muted-foreground mb-2">
                    You can change where the backup is sent. The destination of the new option is set on Step 5.
                  </p>
                )}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-1">
                  {(["pbs", "local", "borg"] as const).map((b) => {
                    const Icon = b === "pbs" ? Server : b === "local" ? HardDrive : Archive
                    const desc = b === "pbs"
                      ? "Proxmox Backup Server. Incremental, encrypted, dedup."
                      : b === "local"
                        ? "tar.zst archive into a local directory or mounted disk."
                        : "Borg repo over SSH or on a local/USB disk (timer only)."
                    return (
                      <button
                        key={b}
                        type="button"
                        onClick={() => setBackend(b)}
                        className={`text-left p-3 rounded-md border transition-colors ${
                          backend === b ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"
                        } hover:bg-white/5`}
                      >
                        <div className="flex items-center gap-2 font-medium text-sm">
                          <Icon className="h-4 w-4" />
                          {b.toUpperCase()}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{desc}</div>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ── Step 2: How to schedule ──────────────────── */}
          {step === 2 && (
            <div className="space-y-3">
              <div>
                <Label>How to schedule</Label>
                <p className="text-xs text-muted-foreground mb-2">
                  {backend === "borg"
                    ? "Borg backups only run on their own timer — they're not produced by PVE vzdump."
                    : "Either run on a schedule you define here, or hook into an existing PVE vzdump job and inherit its schedule + retention."}
                </p>
              </div>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setMode("new")}
                  className={`w-full text-left p-3 rounded-md border transition-colors ${mode === "new" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5`}
                >
                  <div className="text-sm font-medium flex items-center gap-2">
                    <Calendar className="h-4 w-4" />
                    New scheduled job
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Own systemd timer with the OnCalendar and retention policy you pick on the next steps.
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => backend !== "borg" && setMode("attach")}
                  disabled={backend === "borg"}
                  className={`w-full text-left p-3 rounded-md border transition-colors ${
                    mode === "attach" && backend !== "borg"
                      ? "border-blue-500 bg-blue-500/5"
                      : "border-border bg-background/40"
                  } ${backend === "borg" ? "opacity-60 cursor-not-allowed" : "hover:bg-white/5"}`}
                >
                  <div className="text-sm font-medium flex items-center gap-2">
                    <Server className="h-4 w-4" />
                    Attach to existing PVE vzdump job
                    {backend === "borg" && (
                      <Badge variant="outline" className="text-[10px] text-muted-foreground">
                        not available for borg
                      </Badge>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Fires on every <code className="font-mono">job-end</code> of a PVE vzdump job that writes to a <code className="font-mono">{backend}</code> storage. Inherits schedule + retention.
                  </div>
                </button>
              </div>
            </div>
          )}

          {/* ── Step 3: branches by mode ─────────────────── */}
          {step === 3 && mode === "attach" && (
            <div className="space-y-3">
              <div>
                <Label>Pick the parent PVE vzdump job</Label>
                <p className="text-xs text-muted-foreground mb-2">
                  The host config backup will fire on every <code className="font-mono">job-end</code> of this job.
                </p>
              </div>
              {compatibleJobs.length === 0 ? (
                <div className="p-4 rounded-md border border-amber-500/40 bg-amber-500/5 text-sm">
                  <div className="flex items-center gap-2 text-amber-500 font-medium">
                    <AlertTriangle className="h-4 w-4" />
                    No compatible PVE vzdump job
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    No PVE vzdump job currently uses a <span className="font-mono">{backend}</span> storage. Create one in <span className="font-medium">Datacenter → Backup</span> first, then come back here to attach.
                  </p>
                </div>
              ) : (
                <div className="space-y-1">
                  {compatibleJobs.map((j) => (
                    <button
                      key={j.id}
                      type="button"
                      onClick={() => setPveJobId(j.id)}
                      className={`w-full text-left p-3 rounded-md border ${pveJobId === j.id ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                    >
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <span className="font-mono text-xs">{j.id}</span>
                        {!j.enabled && (
                          <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/40">
                            disabled
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground flex items-center gap-x-3 gap-y-1 flex-wrap">
                        <span>storage: <code className="font-mono">{j.storage}</code></span>
                        <span>schedule: <code className="font-mono">{j.schedule || "—"}</code></span>
                        <span>retention: <code className="font-mono">{j.prune || "—"}</code></span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {step === 3 && mode === "new" && (
            <div className="space-y-4">
              <div>
                <Label>Schedule</Label>
                <p className="text-xs text-muted-foreground mb-2">
                  Pick how often this backup runs. The expression is built and validated for you.
                </p>
                <Select
                  value={scheduleType}
                  onValueChange={(v) => setScheduleType(v as typeof scheduleType)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="daily">Daily — every day at a specific time</SelectItem>
                    <SelectItem value="hourly">Hourly — every hour at a specific minute</SelectItem>
                    <SelectItem value="weekly">Weekly — on specific weekdays at a time</SelectItem>
                    <SelectItem value="monthly">Monthly — on a specific day of the month</SelectItem>
                    <SelectItem value="advanced">Advanced — type the OnCalendar expression myself</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {scheduleType === "daily" && (
                <div>
                  <Label htmlFor="schedTime">Time of day</Label>
                  <Input
                    id="schedTime"
                    type="time"
                    value={scheduleTime}
                    onChange={(e) => setScheduleTime(e.target.value)}
                    className="font-mono mt-1 max-w-[140px]"
                  />
                </div>
              )}

              {scheduleType === "hourly" && (
                <div>
                  <Label htmlFor="schedMinute">Minute of the hour (0–59)</Label>
                  <Input
                    id="schedMinute"
                    type="number"
                    min="0"
                    max="59"
                    value={scheduleMinute}
                    onChange={(e) => setScheduleMinute(e.target.value)}
                    className="font-mono mt-1 max-w-[120px]"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    The job fires every hour at this minute. <code className="font-mono">0</code> = on the hour, <code className="font-mono">30</code> = half past, etc.
                  </p>
                </div>
              )}

              {scheduleType === "weekly" && (
                <div className="space-y-3">
                  <div>
                    <Label>Days of the week</Label>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => {
                        const active = scheduleWeekdays.has(d)
                        return (
                          <button
                            key={d}
                            type="button"
                            onClick={() => {
                              setScheduleWeekdays((prev) => {
                                const next = new Set(prev)
                                if (next.has(d)) next.delete(d)
                                else next.add(d)
                                return next
                              })
                            }}
                            className={`px-3 py-1.5 rounded-md text-xs font-mono border transition-colors ${
                              active
                                ? "border-blue-500 bg-blue-500/10 text-blue-400"
                                : "border-border bg-background/40 text-muted-foreground hover:bg-white/5"
                            }`}
                          >
                            {d}
                          </button>
                        )
                      })}
                    </div>
                    {scheduleWeekdays.size === 0 && (
                      <p className="text-xs text-amber-500 mt-1">Pick at least one day.</p>
                    )}
                  </div>
                  <div>
                    <Label htmlFor="schedTimeW">Time of day</Label>
                    <Input
                      id="schedTimeW"
                      type="time"
                      value={scheduleTime}
                      onChange={(e) => setScheduleTime(e.target.value)}
                      className="font-mono mt-1 max-w-[140px]"
                    />
                  </div>
                </div>
              )}

              {scheduleType === "monthly" && (
                <div className="space-y-3">
                  <div>
                    <Label htmlFor="schedDay">Day of the month (1–31)</Label>
                    <Input
                      id="schedDay"
                      type="number"
                      min="1"
                      max="31"
                      value={scheduleDayOfMonth}
                      onChange={(e) => setScheduleDayOfMonth(e.target.value)}
                      className="font-mono mt-1 max-w-[120px]"
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      If the chosen day doesn't exist in a given month (e.g. 31 in February), systemd skips that month.
                    </p>
                  </div>
                  <div>
                    <Label htmlFor="schedTimeM">Time of day</Label>
                    <Input
                      id="schedTimeM"
                      type="time"
                      value={scheduleTime}
                      onChange={(e) => setScheduleTime(e.target.value)}
                      className="font-mono mt-1 max-w-[140px]"
                    />
                  </div>
                </div>
              )}

              {scheduleType === "advanced" && (
                <div>
                  <Label htmlFor="schedAdv">OnCalendar expression</Label>
                  <Input
                    id="schedAdv"
                    value={scheduleAdvanced}
                    onChange={(e) => setScheduleAdvanced(e.target.value)}
                    className="font-mono mt-1"
                    placeholder="*-*-* 02:00, Mon..Fri *-*-* 04:00, daily, ..."
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Any expression accepted by <code className="font-mono">systemd-analyze calendar</code>. See <span className="font-mono">man systemd.time</span> for the full grammar.
                  </p>
                </div>
              )}

              {/* Live preview from the backend */}
              <div className="rounded-md border border-border bg-background/40 p-3 space-y-1 text-xs">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Preview</div>
                <div className="flex items-baseline gap-2">
                  <span className="text-muted-foreground">Expression:</span>
                  <code className="font-mono">{onCalendar}</code>
                </div>
                {calendarPreview ? (
                  calendarPreview.valid ? (
                    <>
                      {calendarPreview.normalized && calendarPreview.normalized !== onCalendar && (
                        <div className="flex items-baseline gap-2">
                          <span className="text-muted-foreground">Normalized:</span>
                          <code className="font-mono">{calendarPreview.normalized}</code>
                        </div>
                      )}
                      {calendarPreview.next_elapse && (
                        <div className="flex items-baseline gap-2">
                          <span className="text-muted-foreground">Next run:</span>
                          <span className="text-emerald-400">{calendarPreview.next_elapse}</span>
                          {calendarPreview.from_now && (
                            <span className="text-muted-foreground">({calendarPreview.from_now})</span>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-red-500">
                      <span className="font-medium">Invalid:</span> {calendarPreview.error}
                    </div>
                  )
                ) : (
                  <div className="text-muted-foreground italic">checking…</div>
                )}
              </div>

              <div>
                <Label>Retention</Label>
                <p className="text-xs text-muted-foreground mb-2">Zero disables that bucket.</p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {[
                    { id: "keep-last", lbl: "keep-last", v: keepLast, set: setKeepLast },
                    { id: "keep-hourly", lbl: "keep-hourly", v: keepHourly, set: setKeepHourly },
                    { id: "keep-daily", lbl: "keep-daily", v: keepDaily, set: setKeepDaily },
                    { id: "keep-weekly", lbl: "keep-weekly", v: keepWeekly, set: setKeepWeekly },
                    { id: "keep-monthly", lbl: "keep-monthly", v: keepMonthly, set: setKeepMonthly },
                    { id: "keep-yearly", lbl: "keep-yearly", v: keepYearly, set: setKeepYearly },
                  ].map((row) => (
                    <div key={row.id}>
                      <Label htmlFor={row.id} className="text-xs">{row.lbl}</Label>
                      <Input
                        id={row.id}
                        type="number"
                        min="0"
                        value={row.v}
                        onChange={(e) => row.set(e.target.value)}
                        className="font-mono mt-1"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Step 4: Profile + paths ──────────────────── */}
          {step === 4 && (
            <div className="space-y-4">
              <div>
                <Label>Backup profile</Label>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <button
                    type="button"
                    onClick={() => setProfileMode("default")}
                    className={`text-left p-3 rounded-md border ${profileMode === "default" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                  >
                    <div className="text-sm font-medium">Default</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Critical config paths ({defaultPaths.length} entries): /etc/pve, /etc/network, /root, /usr/local, etc.
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setProfileMode("custom")}
                    className={`text-left p-3 rounded-md border ${profileMode === "custom" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                  >
                    <div className="text-sm font-medium">Custom</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Pick from the default list which paths to include. At least one is required.
                    </div>
                  </button>
                </div>
              </div>
              {profileMode === "custom" && (
                <div>
                  <Label>Paths to include ({customPaths.size}/{defaultPaths.length})</Label>
                  <ScrollArea className="h-64 mt-1 rounded-md border border-border p-2">
                    {defaultPaths.map((p) => (
                      <label
                        key={p}
                        className="flex items-center gap-2 py-1 px-1 hover:bg-white/5 rounded text-xs cursor-pointer"
                      >
                        <Checkbox
                          checked={customPaths.has(p)}
                          onCheckedChange={() => togglePath(p)}
                        />
                        <span className="font-mono">{p}</span>
                      </label>
                    ))}
                  </ScrollArea>
                </div>
              )}
            </div>
          )}

          {/* ── Step 5: Backend-specific + summary ──────── */}
          {step === 5 && (
            <div className="space-y-4">
              {backend === "pbs" && (
                <>
                  <div>
                    <Label>PBS repository</Label>
                    {destResp?.pbs?.length ? (
                      <div className="mt-1 flex items-center gap-2">
                        <Select value={pbsRepository} onValueChange={setPbsRepository}>
                          <SelectTrigger className="flex-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {destResp.pbs.map((r) => (
                              <SelectItem key={`${r.name}-${r.repository}`} value={r.repository}>
                                <span className="font-mono">{r.name}</span>
                                <span className="text-muted-foreground ml-2">— {r.repository}</span>
                                {r.source === "proxmox" && (
                                  <Badge variant="outline" className="ml-2 text-[10px]">proxmox</Badge>
                                )}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="shrink-0 bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                          onClick={() => setAddingDestType("pbs")}
                          title="Save another PBS repository"
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add another
                        </Button>
                      </div>
                    ) : (
                      <div className="mt-1 p-3 rounded-md border border-amber-500/40 bg-amber-500/5 text-xs space-y-2">
                        <div>No PBS repository configured yet. You can add one without leaving this wizard.</div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                          onClick={() => setAddingDestType("pbs")}
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add PBS repository
                        </Button>
                      </div>
                    )}
                  </div>
                  <div>
                    <Label htmlFor="pbsBackupId">Group name in PBS</Label>
                    <Input
                      id="pbsBackupId"
                      value={pbsBackupId}
                      onChange={(e) => setPbsBackupId(e.target.value)}
                      placeholder="Leave blank for the default"
                      className="font-mono mt-1"
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      PBS organises backups into named groups, each with its own retention. Leave blank to use the automatic default for this host (recommended).
                    </p>
                  </div>
                </>
              )}
              {backend === "local" && (
                <div className="space-y-2">
                  <Label htmlFor="localDest">Destination directory</Label>
                  {mode === "attach" ? (
                    <>
                      <Input
                        id="localDest"
                        value={localDestDir}
                        onChange={(e) => setLocalDestDir(e.target.value)}
                        placeholder="Auto (derived from the PVE storage path)"
                        className="font-mono"
                      />
                      <p className="text-xs text-muted-foreground">
                        Leave blank to derive automatically from the parent PVE job's storage at backup time. Default is the storage's <code className="font-mono">/dump</code> subdir, falling back to <code className="font-mono">/var/lib/vz/dump</code>.
                      </p>
                    </>
                  ) : (
                    <>
                      <Input
                        id="localDest"
                        value={localDestDir}
                        onChange={(e) => setLocalDestDir(e.target.value)}
                        placeholder={destResp?.local?.effective || "/var/lib/vz/dump"}
                        className="font-mono"
                      />
                      <p className="text-xs text-muted-foreground">
                        Where the <code className="font-mono">tar.zst</code> archive is written.
                        {" "}
                        Leave blank to use the configured local target
                        {" "}
                        (<span className="font-mono">{destResp?.local?.effective || "/var/lib/vz/dump"}</span>
                        {destResp?.local?.configured ? "" : " — default"}).
                      </p>
                    </>
                  )}
                </div>
              )}
              {backend === "borg" && (
                <>
                  <div>
                    <Label>Borg repository</Label>
                    {destResp?.borg?.length ? (
                      <div className="mt-1 flex items-center gap-2">
                        <Select value={borgRepoSelected} onValueChange={setBorgRepoSelected}>
                          <SelectTrigger className="flex-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {destResp.borg.map((r) => (
                              <SelectItem key={`${r.name}-${r.repository}`} value={r.repository}>
                                <span className="font-mono">{r.name}</span>
                                <span className="text-muted-foreground ml-2">— {r.repository}</span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="shrink-0 bg-fuchsia-500/10 border-fuchsia-500/40 !text-fuchsia-400 hover:bg-fuchsia-500/20 hover:!text-fuchsia-300"
                          onClick={() => setAddingDestType("borg")}
                          title="Save another Borg repository"
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add another
                        </Button>
                      </div>
                    ) : (
                      <div className="mt-1 p-3 rounded-md border border-amber-500/40 bg-amber-500/5 text-xs space-y-2">
                        <div>No Borg repository configured yet. You can add one without leaving this wizard (SSH or local/USB path supported).</div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="bg-fuchsia-500/10 border-fuchsia-500/40 !text-fuchsia-400 hover:bg-fuchsia-500/20 hover:!text-fuchsia-300"
                          onClick={() => setAddingDestType("borg")}
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add Borg repository
                        </Button>
                      </div>
                    )}
                  </div>
                  <div>
                    <Label htmlFor="borgEncrypt">Encryption mode</Label>
                    <Select
                      value={borgEncryptMode}
                      onValueChange={(v) => setBorgEncryptMode(v as "none" | "repokey" | "keyfile" | "authenticated")}
                    >
                      <SelectTrigger className="mt-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="repokey">repokey (recommended)</SelectItem>
                        <SelectItem value="keyfile">keyfile</SelectItem>
                        <SelectItem value="authenticated">authenticated (no encryption, just integrity)</SelectItem>
                        <SelectItem value="none">none (NOT recommended)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {borgEncryptMode !== "none" && (
                    <div>
                      <Label htmlFor="borgPass">Passphrase</Label>
                      <Input
                        id="borgPass"
                        type="password"
                        value={borgPassphrase}
                        onChange={(e) => setBorgPassphrase(e.target.value)}
                        className="font-mono mt-1"
                        placeholder={isEdit && jobDetail?.has_borg_passphrase
                          ? "(unchanged — type to replace)"
                          : "Passphrase used to decrypt repo at restore time"}
                      />
                      <p className="text-xs text-muted-foreground mt-1">
                        {isEdit && jobDetail?.has_borg_passphrase
                          ? "Leave blank to keep the current passphrase."
                          : "Stored in the .env (mode 0600). If the repo is new it will be initialised with this passphrase."}
                      </p>
                    </div>
                  )}
                </>
              )}

              {/* Summary preview — mirrors the JobDetailModal styling so
                  what the operator sees at Create time is what they'll
                  see when they open the job later. */}
              {(() => {
                const retentionPairs: Array<[string, string]> = [
                  ["last", String(keepLast || "")],
                  ["hourly", String(keepHourly || "")],
                  ["daily", String(keepDaily || "")],
                  ["weekly", String(keepWeekly || "")],
                  ["monthly", String(keepMonthly || "")],
                  ["yearly", String(keepYearly || "")],
                ].filter(([, v]) => Number(v) > 0) as Array<[string, string]>
                return (
                  <div className="rounded-md border border-border bg-background/40 p-3 space-y-2 text-xs">
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Summary</div>
                    <div><span className="text-muted-foreground">Name:</span> <span className="font-mono text-foreground">{jobId}</span></div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-muted-foreground">Backend:</span>
                      <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(backend)}`}>
                        {backend}
                      </Badge>
                      <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-400/40 bg-blue-500/5">
                        {mode === "attach" ? "attached" : "scheduled"}
                      </Badge>
                    </div>
                    {mode === "attach" && selectedPveJob && (
                      <>
                        <div><span className="text-muted-foreground">PVE job:</span> <span className="font-mono text-foreground">{selectedPveJob.id}</span></div>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Calendar className="h-3 w-3 text-green-500/80" />
                          <span className="text-green-500/90 uppercase tracking-wider text-[10px]">inherited schedule:</span>
                          <span className="text-foreground">{humanizeOnCalendar(selectedPveJob.schedule)}</span>
                        </div>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Archive className="h-3 w-3 text-green-500/80" />
                          <span className="text-green-500/90 uppercase tracking-wider text-[10px]">inherited retention:</span>
                          <span className="font-mono text-foreground">{selectedPveJob.prune}</span>
                        </div>
                      </>
                    )}
                    {mode === "new" && (
                      <>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Calendar className="h-3 w-3 text-green-500/80" />
                          <span className="text-green-500/90 uppercase tracking-wider text-[10px]">when:</span>
                          <span className="text-foreground">{humanizeOnCalendar(onCalendar)}</span>
                        </div>
                        <div className="flex items-start gap-1.5 flex-wrap">
                          <span className="text-green-500/90 uppercase tracking-wider text-[10px] inline-flex items-center gap-1 pt-0.5">
                            <Archive className="h-3 w-3 text-green-500/80" /> retention:
                          </span>
                          {retentionPairs.length === 0 ? (
                            <span className="text-muted-foreground italic">No retention rules</span>
                          ) : (
                            <div className="flex flex-wrap gap-1.5">
                              {retentionPairs.map(([k, v]) => (
                                <span key={k} className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-border bg-background/60">
                                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{k}</span>
                                  <span className="font-mono text-xs text-foreground">{v}</span>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </>
                    )}
                    <div className="inline-flex items-center gap-1.5">
                      <FileSearch className="h-3 w-3 text-green-500/80" />
                      <span className="text-green-500/90 uppercase tracking-wider text-[10px]">profile:</span>
                      <span className="text-foreground">{profileMode}</span>
                      <span className="text-muted-foreground">({profileMode === "default" ? defaultPaths.length : customPaths.size} paths)</span>
                    </div>
                  </div>
                )
              })()}

              {error && (
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
                  {error}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer navigation */}
        <div className="flex items-center justify-between gap-2 pt-3 border-t border-border">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <div className="flex items-center gap-2">
            {step > 1 && (
              <Button
                variant="outline"
                onClick={() => setStep((s) => (s - 1) as 1 | 2 | 3 | 4 | 5)}
                disabled={submitting}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Back
              </Button>
            )}
            {step < 5 ? (
              <Button
                onClick={() => setStep((s) => (s + 1) as 1 | 2 | 3 | 4 | 5)}
                disabled={
                  (step === 1 && !canAdvanceFrom1) ||
                  (step === 2 && !canAdvanceFrom2) ||
                  (step === 3 && !canAdvanceFrom3) ||
                  (step === 4 && !canAdvanceFrom4)
                }
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button
                onClick={handleCreate}
                disabled={!canSubmit || submitting}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : isEdit ? (
                  <Save className="h-4 w-4 mr-2" />
                ) : (
                  <Plus className="h-4 w-4 mr-2" />
                )}
                {isEdit ? "Save changes" : "Create job"}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>

      {/* AddDestinationDialog spawned from inside the wizard. When the
          operator saves a new PBS or Borg destination we refresh the
          dest list and queue the freshly-saved repository so the next
          destResp render auto-selects it in the dropdown. */}
      <AddDestinationDialog
        type={addingDestType}
        onClose={() => setAddingDestType(null)}
        onSaved={(repo) => {
          if (repo && (addingDestType === "pbs" || addingDestType === "borg")) {
            setPendingAutoSelectDest({ kind: addingDestType, repository: repo })
          }
          setAddingDestType(null)
          mutateDest()
        }}
      />
    </Dialog>
  )
}

// ──────────────────────────────────────────────────────────────
// Manual backup dialog (Sprint B).
//
// One-shot version of CreateJobDialog: same backends + profile + paths
// + backend-specific config, but NO schedule, NO retention, NO timer.
// Writes a `manual-<ts>` .env with ENABLED=0 + MANUAL_RUN=1 and fires
// the runner in the background. The resulting job appears in the
// scheduler list with a "manual" badge and can be deleted when the
// operator wants to clean up.
// ──────────────────────────────────────────────────────────────

function ManualBackupDialog({
  open,
  onClose,
  onLaunched,
}: {
  open: boolean
  onClose: () => void
  onLaunched: () => void
}) {
  const [step, setStep] = useState<1 | 2>(1)
  const [backend, setBackend] = useState<"pbs" | "local" | "borg">("local")
  const [profileMode, setProfileMode] = useState<"default" | "custom">("default")
  const [customPaths, setCustomPaths] = useState<Set<string>>(new Set())

  const [pbsRepository, setPbsRepository] = useState<string>("")
  const [pbsBackupId, setPbsBackupId] = useState<string>("")
  const [localDestDir, setLocalDestDir] = useState<string>("")
  const [borgRepoSelected, setBorgRepoSelected] = useState<string>("")
  const [borgPassphrase, setBorgPassphrase] = useState<string>("")
  const [borgEncryptMode, setBorgEncryptMode] = useState<"none" | "repokey" | "keyfile" | "authenticated">("repokey")

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: destResp, mutate: mutateDest } = useSWR<DestinationsResp>(
    open ? "/api/host-backups/destinations" : null,
    fetcher,
  )
  const { data: pathsResp } = useSWR<{ paths: string[] }>(
    open ? "/api/host-backups/default-paths" : null,
    fetcher,
  )
  // Same inline AddDestinationDialog flow as the scheduled CreateJobDialog.
  const [addingDestType, setAddingDestType] = useState<"pbs" | "borg" | "local" | null>(null)
  const [pendingAutoSelectDest, setPendingAutoSelectDest] = useState<{ kind: "pbs" | "borg"; repository: string } | null>(null)
  useEffect(() => {
    if (!pendingAutoSelectDest || !destResp) return
    if (pendingAutoSelectDest.kind === "pbs") {
      const hit = destResp.pbs?.find((r) => r.repository === pendingAutoSelectDest.repository)
      if (hit) {
        setPbsRepository(hit.repository)
        setPendingAutoSelectDest(null)
      }
    } else {
      const hit = destResp.borg?.find((r) => r.repository === pendingAutoSelectDest.repository)
      if (hit) {
        setBorgRepoSelected(hit.repository)
        setPendingAutoSelectDest(null)
      }
    }
  }, [destResp, pendingAutoSelectDest])

  const selectedPbs = destResp?.pbs?.find((r) => r.repository === pbsRepository) ?? destResp?.pbs?.[0]

  useEffect(() => {
    if (!open) {
      setStep(1)
      setBackend("local")
      setProfileMode("default")
      setCustomPaths(new Set())
      setPbsRepository("")
      setPbsBackupId("")
      setLocalDestDir("")
      setBorgRepoSelected("")
      setBorgPassphrase("")
      setBorgEncryptMode("repokey")
      setError(null)
      setSubmitting(false)
    }
  }, [open])

  useEffect(() => {
    if (backend === "pbs" && !pbsRepository && destResp?.pbs?.length) {
      setPbsRepository(destResp.pbs[0].repository)
    }
    if (backend === "borg" && !borgRepoSelected && destResp?.borg?.length) {
      setBorgRepoSelected(destResp.borg[0].repository)
    }
  }, [backend, destResp, pbsRepository, borgRepoSelected])

  const togglePath = (path: string) => {
    setCustomPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const defaultPaths = pathsResp?.paths ?? []
  const canAdvanceFrom1 = profileMode === "default" || (profileMode === "custom" && customPaths.size > 0)
  const backendValid =
    backend === "pbs"
      ? !!pbsRepository
      : backend === "local"
        ? true
        : !!borgRepoSelected && (borgEncryptMode === "none" || !!borgPassphrase)
  const canSubmit = canAdvanceFrom1 && backendValid

  async function handleRun() {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        backend,
        profile_mode: profileMode,
      }
      if (profileMode === "custom") {
        body.paths = Array.from(customPaths)
      }
      if (backend === "pbs") {
        body.pbs_repository = pbsRepository
        body.pbs_password = ""
        if (pbsBackupId) body.pbs_backup_id = pbsBackupId
        if (selectedPbs?.fingerprint) body.pbs_fingerprint = selectedPbs.fingerprint
      } else if (backend === "local") {
        if (localDestDir.trim()) body.local_dest_dir = localDestDir.trim()
      } else if (backend === "borg") {
        body.borg_repo = borgRepoSelected
        body.borg_passphrase = borgPassphrase
        body.borg_encrypt_mode = borgEncryptMode
      }
      await fetchApi("/api/host-backups/manual-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      onLaunched()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <PlayCircle className="h-5 w-5 text-blue-500" />
            Run a one-shot backup
          </DialogTitle>
          <DialogDescription>
            Step {step} of 2 · The backup runs once. It appears in the list with a "manual" badge and won't fire again.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-1">
          {[1, 2].map((n) => (
            <div
              key={n}
              className={`h-1 flex-1 rounded-full ${n <= step ? "bg-blue-500" : "bg-border"}`}
            />
          ))}
        </div>

        <div className="overflow-y-auto pr-2 -mr-2 space-y-4 flex-1">
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <Label>Backend</Label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-1">
                  {(["pbs", "local", "borg"] as const).map((b) => {
                    const Icon = b === "pbs" ? Server : b === "local" ? HardDrive : Archive
                    const desc = b === "pbs"
                      ? "Proxmox Backup Server."
                      : b === "local"
                        ? "tar.zst archive into a local directory."
                        : "Borg repo (SSH or local/USB disk)."
                    return (
                      <button
                        key={b}
                        type="button"
                        onClick={() => setBackend(b)}
                        className={`text-left p-3 rounded-md border ${backend === b ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                      >
                        <div className="flex items-center gap-2 font-medium text-sm">
                          <Icon className="h-4 w-4" />
                          {b.toUpperCase()}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{desc}</div>
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <Label>Backup profile</Label>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <button
                    type="button"
                    onClick={() => setProfileMode("default")}
                    className={`text-left p-3 rounded-md border ${profileMode === "default" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                  >
                    <div className="text-sm font-medium">Default</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Critical config paths ({defaultPaths.length} entries).
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setProfileMode("custom")}
                    className={`text-left p-3 rounded-md border ${profileMode === "custom" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                  >
                    <div className="text-sm font-medium">Custom</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      Pick which paths to include.
                    </div>
                  </button>
                </div>
              </div>

              {profileMode === "custom" && (
                <div>
                  <Label>Paths to include ({customPaths.size}/{defaultPaths.length})</Label>
                  <ScrollArea className="h-48 mt-1 rounded-md border border-border p-2">
                    {defaultPaths.map((p) => (
                      <label
                        key={p}
                        className="flex items-center gap-2 py-1 px-1 hover:bg-white/5 rounded text-xs cursor-pointer"
                      >
                        <Checkbox
                          checked={customPaths.has(p)}
                          onCheckedChange={() => togglePath(p)}
                        />
                        <span className="font-mono">{p}</span>
                      </label>
                    ))}
                  </ScrollArea>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              {backend === "pbs" && (
                <>
                  <div>
                    <Label>PBS repository</Label>
                    {destResp?.pbs?.length ? (
                      <div className="mt-1 flex items-center gap-2">
                        <Select value={pbsRepository} onValueChange={setPbsRepository}>
                          <SelectTrigger className="flex-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {destResp.pbs.map((r) => (
                              <SelectItem key={`${r.name}-${r.repository}`} value={r.repository}>
                                <span className="font-mono">{r.name}</span>
                                <span className="text-muted-foreground ml-2">— {r.repository}</span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="shrink-0 bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                          onClick={() => setAddingDestType("pbs")}
                          title="Save another PBS repository"
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add another
                        </Button>
                      </div>
                    ) : (
                      <div className="mt-1 p-3 rounded-md border border-amber-500/40 bg-amber-500/5 text-xs space-y-2">
                        <div>No PBS repository configured yet. You can add one without leaving this dialog.</div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                          onClick={() => setAddingDestType("pbs")}
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add PBS repository
                        </Button>
                      </div>
                    )}
                  </div>
                  <div>
                    <Label htmlFor="manualPbsBackupId">Group name in PBS</Label>
                    <Input
                      id="manualPbsBackupId"
                      value={pbsBackupId}
                      onChange={(e) => setPbsBackupId(e.target.value)}
                      placeholder="Leave blank for the default"
                      className="font-mono mt-1"
                    />
                  </div>
                </>
              )}
              {backend === "local" && (
                <div className="space-y-2">
                  <Label htmlFor="manualLocalDest">Destination directory</Label>
                  <Input
                    id="manualLocalDest"
                    value={localDestDir}
                    onChange={(e) => setLocalDestDir(e.target.value)}
                    placeholder={destResp?.local?.effective || "/var/lib/vz/dump"}
                    className="font-mono"
                  />
                  <p className="text-xs text-muted-foreground">
                    Where the <code className="font-mono">tar.zst</code> archive is written.
                    {" "}Leave blank to use the configured local target
                    {" "}(<span className="font-mono">{destResp?.local?.effective || "/var/lib/vz/dump"}</span>).
                  </p>
                </div>
              )}
              {backend === "borg" && (
                <>
                  <div>
                    <Label>Borg repository</Label>
                    {destResp?.borg?.length ? (
                      <div className="mt-1 flex items-center gap-2">
                        <Select value={borgRepoSelected} onValueChange={setBorgRepoSelected}>
                          <SelectTrigger className="flex-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {destResp.borg.map((r) => (
                              <SelectItem key={`${r.name}-${r.repository}`} value={r.repository}>
                                <span className="font-mono">{r.name}</span>
                                <span className="text-muted-foreground ml-2">— {r.repository}</span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="shrink-0 bg-fuchsia-500/10 border-fuchsia-500/40 !text-fuchsia-400 hover:bg-fuchsia-500/20 hover:!text-fuchsia-300"
                          onClick={() => setAddingDestType("borg")}
                          title="Save another Borg repository"
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add another
                        </Button>
                      </div>
                    ) : (
                      <div className="mt-1 p-3 rounded-md border border-amber-500/40 bg-amber-500/5 text-xs space-y-2">
                        <div>No Borg repository configured yet. You can add one without leaving this dialog (SSH or local/USB path supported).</div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="bg-fuchsia-500/10 border-fuchsia-500/40 !text-fuchsia-400 hover:bg-fuchsia-500/20 hover:!text-fuchsia-300"
                          onClick={() => setAddingDestType("borg")}
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" />
                          Add Borg repository
                        </Button>
                      </div>
                    )}
                  </div>
                  <div>
                    <Label htmlFor="manualBorgEnc">Encryption mode</Label>
                    <Select
                      value={borgEncryptMode}
                      onValueChange={(v) => setBorgEncryptMode(v as "none" | "repokey" | "keyfile" | "authenticated")}
                    >
                      <SelectTrigger className="mt-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="repokey">repokey (recommended)</SelectItem>
                        <SelectItem value="keyfile">keyfile</SelectItem>
                        <SelectItem value="authenticated">authenticated</SelectItem>
                        <SelectItem value="none">none (NOT recommended)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {borgEncryptMode !== "none" && (
                    <div>
                      <Label htmlFor="manualBorgPass">Passphrase</Label>
                      <Input
                        id="manualBorgPass"
                        type="password"
                        value={borgPassphrase}
                        onChange={(e) => setBorgPassphrase(e.target.value)}
                        className="font-mono mt-1"
                        placeholder="Passphrase used to decrypt repo at restore time"
                      />
                    </div>
                  )}
                </>
              )}

              {/* Summary — mirrors the styling of the JobDetailModal. */}
              <div className="rounded-md border border-border bg-background/40 p-3 space-y-2 text-xs">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Summary</div>
                <div className="inline-flex items-center gap-2 flex-wrap">
                  <span className="text-muted-foreground">Backend:</span>
                  <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(backend)}`}>
                    {backend}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] text-purple-400 border-purple-400/40 bg-purple-500/5">
                    manual / one-shot
                  </Badge>
                </div>
                <div className="inline-flex items-center gap-1.5">
                  <FileSearch className="h-3 w-3 text-green-500/80" />
                  <span className="text-green-500/90 uppercase tracking-wider text-[10px]">profile:</span>
                  <span className="text-foreground">{profileMode}</span>
                  <span className="text-muted-foreground">({profileMode === "default" ? defaultPaths.length : customPaths.size} paths)</span>
                </div>
              </div>

              {error && (
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
                  {error}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 pt-3 border-t border-border">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <div className="flex items-center gap-2">
            {step > 1 && (
              <Button
                variant="outline"
                onClick={() => setStep((s) => (s - 1) as 1 | 2)}
                disabled={submitting}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Back
              </Button>
            )}
            {step < 2 ? (
              <Button
                onClick={() => setStep(2)}
                disabled={!canAdvanceFrom1}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button
                onClick={handleRun}
                disabled={!canSubmit || submitting}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <PlayCircle className="h-4 w-4 mr-2" />
                )}
                Run backup
              </Button>
            )}
          </div>
        </div>
      </DialogContent>

      {/* AddDestinationDialog spawned from inside the manual-backup
          dialog. Same auto-select-on-save behavior as the wizard. */}
      <AddDestinationDialog
        type={addingDestType}
        onClose={() => setAddingDestType(null)}
        onSaved={(repo) => {
          if (repo && (addingDestType === "pbs" || addingDestType === "borg")) {
            setPendingAutoSelectDest({ kind: addingDestType, repository: repo })
          }
          setAddingDestType(null)
          mutateDest()
        }}
      />
    </Dialog>
  )
}

// ──────────────────────────────────────────────────────────────
// Backup destinations CRUD (Sprint D).
//
// Three persistence files live in $HB_STATE_DIR (= /usr/local/share/proxmenux/):
//   - pbs-manual-configs.txt  (manual PBS configs the shell also reads)
//   - borg-targets.txt        (Borg repos saved by the shell)
//   - local-target.conf       (single local target — default or override)
//
// Auto-discovered PBS storages from /etc/pve/storage.cfg show with a
// "proxmox" badge and are NOT deletable here (PVE owns those).
// ──────────────────────────────────────────────────────────────

// One entry in the unified destinations list. PBS / Borg / Local all
// flatten into this shape so the row component doesn't need to know
// which backend a given destination targets — only the color, the
// label and the action set.
type UnifiedDest =
  | { id: string; kind: "local"; path: string; source: "default" | "custom"; removable: boolean }
  | {
      id: string; kind: "pbs"; name: string; repository: string;
      source: "proxmox" | "manual"; fingerprint?: string; removable: boolean
    }
  | {
      id: string; kind: "borg"; name: string; repository: string;
      isSsh: boolean; ssh?: { user: string; host: string; remotePath: string };
      sshKeyPath?: string; removable: boolean
    }

interface CapacityInfo {
  id: string
  total?: number
  available?: number
  used?: number
  is_usb?: boolean
  remote?: boolean
  error?: string
}

// Parse a Borg repository string into {user, host, remotePath} when
// it's an SSH URL — used for the capacity probe over ssh.
function parseBorgSsh(repo: string): { user: string; host: string; remotePath: string } | null {
  const m = repo.match(/^ssh:\/\/([^@]+)@([^/]+)\/(.+)$/)
  if (!m) return null
  return { user: m[1], host: m[2], remotePath: `/${m[3]}` }
}

function DestinationsSection({
  destinations,
  onChanged,
}: {
  destinations?: DestinationsResp
  onChanged: () => void
}) {
  const [configuring, setConfiguring] = useState<boolean>(false)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Flatten PBS + Borg + Local into one list. Order: locals first
  // (default always on top), then PBS, then Borg — matches the
  // mental model of "what's already on this machine" before any
  // remote target.
  const items: UnifiedDest[] = (() => {
    const out: UnifiedDest[] = []
    for (const e of destinations?.local?.entries || []) {
      out.push({
        id: `local:${e.path}`,
        kind: "local",
        path: e.path,
        source: e.source as "default" | "custom",
        removable: e.removable,
      })
    }
    for (const r of destinations?.pbs || []) {
      out.push({
        id: `pbs:${r.name}:${r.repository}`,
        kind: "pbs",
        name: r.name,
        repository: r.repository,
        source: r.source as "proxmox" | "manual",
        fingerprint: r.fingerprint || undefined,
        removable: r.source === "manual",
      })
    }
    for (const r of destinations?.borg || []) {
      const ssh = parseBorgSsh(r.repository)
      out.push({
        id: `borg:${r.name}`,
        kind: "borg",
        name: r.name,
        repository: r.repository,
        isSsh: !!ssh,
        ssh: ssh ?? undefined,
        sshKeyPath: (r as { ssh_key_path?: string }).ssh_key_path,
        removable: true,
      })
    }
    return out
  })()

  // Build the capacity-probe payload + key for SWR. The key includes
  // every destination's id so SWR re-fetches when the list changes
  // (add / remove). 30 s refresh keeps the bars roughly live without
  // hammering ssh / pbs every render.
  const capacityTargets = items.map((it) => {
    if (it.kind === "local") return { id: it.id, kind: "local", path: it.path }
    if (it.kind === "pbs") return { id: it.id, kind: "pbs", name: it.name, repository: it.repository }
    if (it.isSsh && it.ssh) {
      return {
        id: it.id, kind: "borg-ssh",
        host: it.ssh.host, user: it.ssh.user,
        remote_path: it.ssh.remotePath,
        key_path: it.sshKeyPath || "",
      }
    }
    return { id: it.id, kind: "borg-local", path: it.repository }
  })
  const capacityKey = items.length
    ? `/api/host-backups/destinations/capacity?keys=${items.map((i) => i.id).join(",")}`
    : null
  const { data: capacityResp } = useSWR<{ results: CapacityInfo[] }>(
    capacityKey,
    () =>
      fetchApi("/api/host-backups/destinations/capacity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets: capacityTargets }),
      }),
    { refreshInterval: 30_000, revalidateOnFocus: false },
  )
  const capByEdid = new Map<string, CapacityInfo>(
    (capacityResp?.results || []).map((r) => [r.id, r] as const),
  )

  async function removePbs(name: string) {
    setBusyKey(`pbs:${name}`)
    setError(null)
    try {
      await fetchApi(`/api/host-backups/destinations/pbs/${encodeURIComponent(name)}`, { method: "DELETE" })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }
  async function removeBorg(name: string) {
    setBusyKey(`borg:${name}`)
    setError(null)
    try {
      await fetchApi(`/api/host-backups/destinations/borg/${encodeURIComponent(name)}`, { method: "DELETE" })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }
  async function removeLocal(path: string) {
    setBusyKey(`local:${path}`)
    setError(null)
    try {
      await fetchApi(
        `/api/host-backups/destinations/local?path=${encodeURIComponent(path)}`,
        { method: "DELETE" },
      )
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }
  // Detach a USB drive — only the filesystem is unmounted; the path
  // stays in local-target.conf so re-plugging the same disk picks it
  // up again without re-adding the destination.
  async function unmountUsb(mountpoint: string) {
    setBusyKey(`umount:${mountpoint}`)
    setError(null)
    try {
      await fetchApi("/api/host-backups/usb-drives/unmount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mountpoint }),
      })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Pre-configure backup destinations so wizards and manual backups can pick from them without re-typing credentials each time. Each entry is colored by backend: PBS purple, Local blue, Borg fuchsia.
        </p>
        <Button
          size="sm"
          className="h-8 px-3 shrink-0 bg-blue-500 hover:bg-blue-600 text-white"
          onClick={() => setConfiguring(true)}
        >
          <Plus className="h-4 w-4 mr-1" />
          Configure destination
        </Button>
      </div>
      {error && (
        <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
          {error}
        </div>
      )}
      <div className="space-y-2">
        {items.map((it) => {
          const cap = capByEdid.get(it.id)
          const busy = busyKey === it.id ||
            (it.kind === "pbs" && busyKey === `pbs:${it.name}`) ||
            (it.kind === "borg" && busyKey === `borg:${it.name}`) ||
            (it.kind === "local" && busyKey === `local:${it.path}`)
          const unmountBusy = it.kind === "local" && busyKey === `umount:${it.path}`
          return (
            <DestinationRow
              key={it.id}
              item={it}
              capacity={cap}
              busy={busy}
              unmountBusy={unmountBusy}
              onDelete={() => {
                if (it.kind === "pbs") return removePbs(it.name)
                if (it.kind === "borg") return removeBorg(it.name)
                if (it.kind === "local") return removeLocal(it.path)
              }}
              onUnmount={
                it.kind === "local" && cap?.is_usb
                  ? () => unmountUsb(it.path)
                  : undefined
              }
            />
          )
        })}
      </div>
      <ConfigureDestinationWizard
        open={configuring}
        onClose={() => setConfiguring(false)}
        onSaved={() => {
          setConfiguring(false)
          onChanged()
        }}
      />
    </div>
  )
}

// Single row in the unified destinations list. Layout mirrors the
// disk-card chrome from storage-overview.tsx: icon + headline + all
// badges + actions on ONE top row, capacity bar in storage-page blue,
// stats grid below. No hover effect — these rows are inert (no modal
// behind them), so the contrast change would only confuse the eye.
function DestinationRow({
  item,
  capacity,
  busy,
  unmountBusy,
  onDelete,
  onUnmount,
}: {
  item: UnifiedDest
  capacity?: CapacityInfo
  busy: boolean
  unmountBusy: boolean
  onDelete: () => void
  onUnmount?: () => void
}) {
  const accent =
    item.kind === "pbs" ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
    : item.kind === "borg" ? "bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20"
    : "bg-blue-500/10 text-blue-400 border-blue-500/20"
  const iconColor =
    item.kind === "pbs" ? "text-purple-400"
    : item.kind === "borg" ? "text-fuchsia-400"
    : "text-blue-400"
  const Icon = item.kind === "pbs" ? Server : item.kind === "borg" ? Archive : HardDrive
  const headline =
    item.kind === "pbs" ? item.name
    : item.kind === "borg" ? item.name
    : item.path
  const subline =
    item.kind === "pbs" ? item.repository
    : item.kind === "borg" ? item.repository
    : null
  const isUsb = !!capacity?.is_usb || (item.kind === "borg" && !item.isSsh && /\/(?:mnt|media)\//.test(item.repository))
  const sourceLabel =
    item.kind === "local" ? (item.source === "default" ? "built-in default" : "manually added")
    : item.kind === "pbs" ? (item.source === "proxmox" ? "Datacenter → Storage" : "manually added")
    : item.isSsh ? "remote (SSH)" : "local path"

  const pct = capacity?.total && capacity.available !== undefined
    ? Math.min(100, Math.round(((capacity.total - capacity.available) / capacity.total) * 100))
    : null

  return (
    <div className="rounded-lg border border-white/10 bg-card p-4">
      {/* Top row: icon + headline + all badges, then actions on the right */}
      <div className="space-y-2 mb-3">
        <div className="flex items-start gap-2 flex-wrap">
          <Icon className={`h-5 w-5 flex-shrink-0 ${iconColor} mt-0.5`} />
          <h3 className="font-mono font-semibold text-sm break-all">{headline}</h3>
          <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${accent}`}>
            {item.kind}
          </Badge>
          {item.kind === "pbs" && item.source === "proxmox" && (
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-border text-muted-foreground">
              proxmox
            </Badge>
          )}
          {item.kind === "local" && item.source === "default" && (
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-border text-muted-foreground">
              default
            </Badge>
          )}
          {item.kind === "borg" && (
            <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${item.isSsh ? "border-cyan-500/40 text-cyan-400 bg-cyan-500/5" : "border-amber-500/40 text-amber-400 bg-amber-500/5"}`}>
              {item.isSsh ? "ssh" : "local"}
            </Badge>
          )}
          {isUsb && (
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-orange-500/40 text-orange-400 bg-orange-500/5 gap-1">
              <HardDrive className="h-2.5 w-2.5" />
              USB
            </Badge>
          )}
          {/* Spacer pushes actions to the right end of the row */}
          <div className="flex-1 min-w-0" />
          {onUnmount && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-amber-500 hover:text-amber-400 hover:bg-amber-500/10"
              disabled={unmountBusy || busy}
              onClick={onUnmount}
              title="Detach the USB filesystem (config stays so re-plugging re-discovers it)"
            >
              {unmountBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Power className="h-3.5 w-3.5" />}
              <span className="ml-1 text-xs">Unmount</span>
            </Button>
          )}
          {item.removable ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-red-500 hover:text-red-400 hover:bg-red-500/10"
              disabled={busy || unmountBusy}
              onClick={onDelete}
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              <span className="ml-1 text-xs">Remove</span>
            </Button>
          ) : (
            <span className="text-[10px] text-muted-foreground italic self-center px-2">
              {item.kind === "local" ? "built-in" : "managed by PVE"}
            </span>
          )}
        </div>
        {subline && (
          <p className="text-xs font-mono text-muted-foreground break-all pl-7" title={subline}>
            {subline}
          </p>
        )}
      </div>

      {/* Capacity bar — matches the height of the <Progress> component
          used on the Storage page (h-2). bg-muted track + solid blue
          fill, no border. */}
      {capacity?.total && capacity.available !== undefined && (
        <div className="mb-3 h-2 bg-muted rounded-full overflow-hidden">
          <div className="h-full rounded-full bg-blue-500" style={{ width: `${pct}%` }} />
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        {capacity?.total !== undefined && (
          <div>
            <p className="text-sm text-muted-foreground">Size</p>
            <p className="font-medium">{formatBytes(capacity.total)}</p>
          </div>
        )}
        {capacity?.used !== undefined && capacity.total !== undefined && (
          <div>
            <p className="text-sm text-muted-foreground">Used</p>
            <p className="font-medium">
              {formatBytes(capacity.used)}
              {pct !== null && <span className="text-muted-foreground"> ({pct}%)</span>}
            </p>
          </div>
        )}
        {capacity?.available !== undefined && (
          <div>
            <p className="text-sm text-muted-foreground">Free</p>
            <p className={`font-medium ${pct !== null && pct > 90 ? "text-red-400" : pct !== null && pct > 75 ? "text-amber-400" : ""}`}>
              {formatBytes(capacity.available)}
            </p>
          </div>
        )}
        <div>
          <p className="text-sm text-muted-foreground">Source</p>
          <p className="font-medium text-xs">{sourceLabel}</p>
        </div>
      </div>

      {capacity?.error && (
        <p className="mt-3 text-[11px] text-muted-foreground italic">
          Capacity unavailable: {capacity.error}
        </p>
      )}
      {!capacity && (
        <p className="mt-3 text-[11px] text-muted-foreground italic flex items-center gap-1.5">
          <Loader2 className="h-3 w-3 animate-spin" /> Probing capacity…
        </p>
      )}
    </div>
  )
}

// Single-button wizard that replaces the old per-backend Add buttons.
// Step 1 lets the operator pick the backend; Step 2 hands off to the
// existing AddDestinationDialog with that backend pre-selected, so we
// don't duplicate the per-backend forms.
function ConfigureDestinationWizard({
  open,
  onClose,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const [picked, setPicked] = useState<"pbs" | "local" | "borg" | null>(null)
  useEffect(() => {
    if (!open) setPicked(null)
  }, [open])

  if (picked) {
    // Hand off to the existing form. Closing or saving collapses the
    // whole wizard so the operator lands back in the destinations list.
    return (
      <AddDestinationDialog
        type={picked}
        onClose={() => { setPicked(null); onClose() }}
        onSaved={() => { setPicked(null); onSaved() }}
      />
    )
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-2xl bg-card border-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus className="h-5 w-5 text-blue-500" />
            Configure destination
          </DialogTitle>
          <DialogDescription className="text-xs">
            Pick the backend you want to add. The next step has the credentials and path fields for that backend only.
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {([
            { type: "pbs",   label: "PBS",   accent: "border-purple-500/40 hover:border-purple-400 text-purple-400",   blurb: "Proxmox Backup Server. Incremental, encrypted, dedup." },
            { type: "local", label: "Local", accent: "border-blue-500/40 hover:border-blue-400 text-blue-400",         blurb: "tar.zst archive into a local directory or mounted disk." },
            { type: "borg",  label: "Borg",  accent: "border-fuchsia-500/40 hover:border-fuchsia-400 text-fuchsia-400", blurb: "Borg repo over SSH or on a local / USB disk." },
          ] as const).map((opt) => (
            <button
              key={opt.type}
              type="button"
              onClick={() => setPicked(opt.type)}
              className={`text-left rounded-lg border-2 p-4 transition-colors bg-background/40 hover:bg-white/5 ${opt.accent}`}
            >
              <div className="flex items-center gap-2 mb-1">
                {opt.type === "pbs" ? <Server className="h-4 w-4" /> :
                 opt.type === "local" ? <HardDrive className="h-4 w-4" /> :
                 <Archive className="h-4 w-4" />}
                <span className="font-semibold uppercase">{opt.label}</span>
              </div>
              <p className="text-xs text-muted-foreground">{opt.blurb}</p>
            </button>
          ))}
        </div>
        <div className="flex justify-end">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// One dialog handles all three Add flows — the form is small enough
// that branching by type keeps it cleaner than three separate components.
function AddDestinationDialog({
  type,
  onClose,
  onSaved,
}: {
  type: "pbs" | "borg" | "local" | null
  onClose: () => void
  // The repository string of the just-saved destination, so callers
  // can auto-select it in a dropdown (the wizard does this when an
  // operator adds a PBS / Borg repo inline). Undefined for `local`
  // and for the legacy callers that don't care.
  onSaved: (repository?: string) => void
}) {
  const [name, setName] = useState("")
  // PBS fields
  const [server, setServer] = useState("")
  const [datastore, setDatastore] = useState("")
  const [username, setUsername] = useState("root@pam")
  const [password, setPassword] = useState("")
  const [fingerprint, setFingerprint] = useState("")
  // Borg fields (local mode)
  const [borgRepo, setBorgRepo] = useState("")
  // Borg SSH mode
  const [borgMode, setBorgMode] = useState<"local" | "ssh">("local")
  const [borgSshUser, setBorgSshUser] = useState("borg")
  const [borgSshHost, setBorgSshHost] = useState("")
  const [borgSshRemotePath, setBorgSshRemotePath] = useState("")
  const [borgSshKeyPath, setBorgSshKeyPath] = useState("/root/.ssh/proxmenux_borg")
  const [generatedKey, setGeneratedKey] = useState<{ public_key: string; authorized_keys_line: string } | null>(null)
  const [generatingKey, setGeneratingKey] = useState(false)
  // Local field
  const [localPath, setLocalPath] = useState("")

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (type === null) {
      setName("")
      setServer("")
      setDatastore("")
      setUsername("root@pam")
      setPassword("")
      setFingerprint("")
      setBorgRepo("")
      setBorgMode("local")
      setBorgSshUser("borg")
      setBorgSshHost("")
      setBorgSshRemotePath("")
      setBorgSshKeyPath("/root/.ssh/proxmenux_borg")
      setGeneratedKey(null)
      setGeneratingKey(false)
      setLocalPath("")
      setError(null)
      setSubmitting(false)
    }
  }, [type])

  const nameValid = /^[a-zA-Z0-9_-]+$/.test(name)
  const borgValid =
    borgMode === "local"
      ? !!borgRepo.trim()
      : !!(borgSshUser.trim() && borgSshHost.trim() && borgSshRemotePath.trim())
  const canSubmit =
    type === "pbs"
      ? nameValid && server.trim() && datastore.trim() && password
      : type === "borg"
        ? nameValid && borgValid
        : type === "local"
          ? localPath.trim().startsWith("/")
          : false

  async function generateBorgKey() {
    setGeneratingKey(true)
    setError(null)
    try {
      const resp = await fetchApi<{ public_key: string; authorized_keys_line: string }>(
        "/api/host-backups/ssh-keys/generate",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key_path: borgSshKeyPath.trim() || "/root/.ssh/proxmenux_borg",
            remote_path: borgSshRemotePath.trim(),
          }),
        }
      )
      setGeneratedKey(resp)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGeneratingKey(false)
    }
  }

  async function handleSave() {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      let savedRepo: string | undefined
      if (type === "pbs") {
        const resp = await fetchApi<{ repository?: string }>("/api/host-backups/destinations/pbs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            server: server.trim(),
            datastore: datastore.trim(),
            username: username.trim() || "root@pam",
            password,
            fingerprint: fingerprint.trim() || undefined,
          }),
        })
        savedRepo = resp?.repository
      } else if (type === "borg") {
        const body: Record<string, unknown> = { name, mode: borgMode }
        if (borgMode === "local") {
          body.repo = borgRepo.trim()
        } else {
          body.ssh_user = borgSshUser.trim()
          body.ssh_host = borgSshHost.trim()
          body.ssh_remote_path = borgSshRemotePath.trim()
          if (borgSshKeyPath.trim()) body.ssh_key_path = borgSshKeyPath.trim()
        }
        const resp = await fetchApi<{ repo?: string }>("/api/host-backups/destinations/borg", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
        savedRepo = resp?.repo
      } else if (type === "local") {
        await fetchApi("/api/host-backups/destinations/local", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: localPath.trim() }),
        })
      }
      onSaved(savedRepo)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={type !== null} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-lg max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus className="h-5 w-5 text-blue-500" />
            Add {type === "pbs" ? "PBS" : type === "borg" ? "Borg" : "local"} destination
          </DialogTitle>
        </DialogHeader>
        <div className="overflow-y-auto -mr-2 pr-2 space-y-3">
          {type === "pbs" && (
            <>
              <div>
                <Label htmlFor="pbsName">Name</Label>
                <Input id="pbsName" value={name} onChange={(e) => setName(e.target.value)} className="font-mono mt-1" placeholder="my-pbs" />
                <p className="text-xs text-muted-foreground mt-1">A short identifier. Letters, digits, _ or -.</p>
              </div>
              <div>
                <Label htmlFor="pbsServer">Server (host or IP)</Label>
                <Input id="pbsServer" value={server} onChange={(e) => setServer(e.target.value)} className="font-mono mt-1" placeholder="192.168.1.10" />
              </div>
              <div>
                <Label htmlFor="pbsDatastore">Datastore</Label>
                <Input id="pbsDatastore" value={datastore} onChange={(e) => setDatastore(e.target.value)} className="font-mono mt-1" placeholder="pbs" />
              </div>
              <div>
                <Label htmlFor="pbsUser">Username</Label>
                <Input id="pbsUser" value={username} onChange={(e) => setUsername(e.target.value)} className="font-mono mt-1" />
                <p className="text-xs text-muted-foreground mt-1">User that runs <code className="font-mono">proxmox-backup-client</code>. Default <code className="font-mono">root@pam</code>.</p>
              </div>
              <div>
                <Label htmlFor="pbsPass">Password</Label>
                <Input id="pbsPass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="font-mono mt-1" />
              </div>
              <div>
                <Label htmlFor="pbsFp">Fingerprint (optional)</Label>
                <Input id="pbsFp" value={fingerprint} onChange={(e) => setFingerprint(e.target.value)} className="font-mono mt-1" placeholder="aa:bb:cc:…" />
                <p className="text-xs text-muted-foreground mt-1">Required only if the PBS uses a self-signed certificate.</p>
              </div>
            </>
          )}
          {type === "borg" && (
            <>
              <div>
                <Label htmlFor="borgName">Name</Label>
                <Input id="borgName" value={name} onChange={(e) => setName(e.target.value)} className="font-mono mt-1" placeholder="usb-borg or remote-borg" />
              </div>

              <div>
                <Label>Where is the Borg repository?</Label>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  <button
                    type="button"
                    onClick={() => setBorgMode("local")}
                    className={`text-left p-2.5 rounded-md border text-sm ${borgMode === "local" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                  >
                    <div className="font-medium flex items-center gap-1"><HardDrive className="h-3.5 w-3.5" /> Local / USB</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">Path on this host (mounted USB, local dir).</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setBorgMode("ssh")}
                    className={`text-left p-2.5 rounded-md border text-sm ${borgMode === "ssh" ? "border-blue-500 bg-blue-500/5" : "border-border bg-background/40"} hover:bg-white/5 transition-colors`}
                  >
                    <div className="font-medium flex items-center gap-1"><Server className="h-3.5 w-3.5" /> Remote (SSH)</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">Borg repo on another host over SSH.</div>
                  </button>
                </div>
              </div>

              {borgMode === "local" ? (
                <div className="space-y-3">
                  <div>
                    <Label htmlFor="borgRepoIn">Repository path</Label>
                    <Input id="borgRepoIn" value={borgRepo} onChange={(e) => setBorgRepo(e.target.value)} className="font-mono mt-1" placeholder="/mnt/usb-disk/borgbackup" />
                    <p className="text-xs text-muted-foreground mt-1">
                      Absolute path on this host. Pick a USB drive below to auto-fill, or type the path manually.
                    </p>
                  </div>
                  <UsbPicker onPick={(p) => setBorgRepo(p)} />
                </div>
              ) : (
                <>
                  <div>
                    <Label htmlFor="borgSshUser">SSH user</Label>
                    <Input id="borgSshUser" value={borgSshUser} onChange={(e) => setBorgSshUser(e.target.value)} className="font-mono mt-1" placeholder="borg" />
                    <p className="text-xs text-muted-foreground mt-1">
                      User on the remote host that runs <code className="font-mono">borg serve</code>. Conventionally <code className="font-mono">borg</code>, not <code className="font-mono">root</code>.
                    </p>
                  </div>
                  <div>
                    <Label htmlFor="borgSshHost">SSH host or IP</Label>
                    <Input id="borgSshHost" value={borgSshHost} onChange={(e) => setBorgSshHost(e.target.value)} className="font-mono mt-1" placeholder="backup.example.com" />
                  </div>
                  <div>
                    <Label htmlFor="borgSshPath">Remote repository path</Label>
                    <Input id="borgSshPath" value={borgSshRemotePath} onChange={(e) => setBorgSshRemotePath(e.target.value)} className="font-mono mt-1" placeholder="/backup/borgbackup" />
                  </div>
                  <div>
                    <Label htmlFor="borgKeyPath">SSH key path (on this host)</Label>
                    <Input id="borgKeyPath" value={borgSshKeyPath} onChange={(e) => setBorgSshKeyPath(e.target.value)} className="font-mono mt-1" />
                    <p className="text-xs text-muted-foreground mt-1">
                      If you already have an SSH key registered with the server, point to it here.
                      Otherwise click <span className="font-medium text-foreground">Generate key</span> below and paste the line shown into the server's authorized_keys.
                    </p>
                  </div>

                  <div className="rounded-md border border-border bg-background/40 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium">Generate a new SSH key</span>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7"
                        disabled={generatingKey || !borgSshKeyPath.trim()}
                        onClick={generateBorgKey}
                      >
                        {generatingKey ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Plus className="h-3.5 w-3.5 mr-1" />}
                        {generatedKey ? "Regenerate" : "Generate key"}
                      </Button>
                    </div>
                    {generatedKey ? (
                      <>
                        <p className="text-[11px] text-muted-foreground">
                          On the Borg server, append this single line to <code className="font-mono">~{borgSshUser}/.ssh/authorized_keys</code>:
                        </p>
                        <textarea
                          readOnly
                          value={generatedKey.authorized_keys_line}
                          className="w-full text-[11px] font-mono p-2 rounded border border-border bg-background h-24 resize-none"
                          onFocus={(e) => e.currentTarget.select()}
                        />
                      </>
                    ) : (
                      <p className="text-[11px] text-muted-foreground">
                        Creates an ed25519 key (no passphrase) at the path above if one isn't there already. The public half — restricted to <code className="font-mono">borg serve</code> for the remote path — will appear here for you to copy.
                      </p>
                    )}
                  </div>
                </>
              )}
            </>
          )}
          {type === "local" && (
            <div className="space-y-3">
              <div>
                <Label htmlFor="localPath">Directory path</Label>
                <Input id="localPath" value={localPath} onChange={(e) => setLocalPath(e.target.value)} className="font-mono mt-1" placeholder="/var/lib/vz/dump" />
                <p className="text-xs text-muted-foreground mt-1">
                  Where scheduled / manual local backups write the <code className="font-mono">tar.zst</code> archive. Pick a USB drive below to auto-fill, or type the path manually.
                </p>
              </div>
              <UsbPicker onPick={(p) => setLocalPath(p)} />
            </div>
          )}
          {error && (
            <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
              {error}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-3 border-t border-border">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>Cancel</Button>
          <Button onClick={handleSave} disabled={!canSubmit || submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
            Save
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ──────────────────────────────────────────────────────────────
// UsbPicker — inline picker for mounted / unmounted / empty USB
// drives. Used inside AddDestinationDialog for Local and Borg-local
// so the operator can mount + format USB media without leaving the
// "configure destination" flow.
// ──────────────────────────────────────────────────────────────
function UsbPicker({ onPick }: { onPick: (path: string) => void }) {
  const { data, mutate, isLoading } = useSWR<{ drives: UsbDrive[] }>(
    "/api/host-backups/usb-drives",
    fetcher,
    { refreshInterval: 0 },
  )
  const drives = data?.drives ?? []
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [formatTarget, setFormatTarget] = useState<UsbDrive | null>(null)
  const [formatTyped, setFormatTyped] = useState("")

  async function mountAndUse(d: UsbDrive) {
    setBusyKey(d.path_or_device)
    setError(null)
    try {
      const resp = await fetchApi<{ mountpoint: string }>(
        "/api/host-backups/usb-drives/mount",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            device: d.path_or_device,
            label: d.label,
            uuid: d.uuid,
          }),
        },
      )
      mutate()
      if (resp?.mountpoint) onPick(resp.mountpoint)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  async function doFormat() {
    if (!formatTarget) return
    if (formatTyped !== formatTarget.path_or_device) return
    setBusyKey(formatTarget.path_or_device)
    setError(null)
    try {
      const resp = await fetchApi<{ mountpoint?: string }>(
        "/api/host-backups/usb-drives/format",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            device: formatTarget.path_or_device,
            confirm_device: formatTyped,
          }),
        },
      )
      mutate()
      setFormatTarget(null)
      setFormatTyped("")
      if (resp?.mountpoint) onPick(resp.mountpoint)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <>
      <div className="rounded-md border border-border bg-background/40 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-medium">
            <HardDrive className="h-3.5 w-3.5 text-orange-400" />
            USB drives detected
            {drives.length > 0 && (
              <Badge variant="outline" className="text-[10px]">{drives.length}</Badge>
            )}
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 text-xs"
            onClick={() => mutate()}
            disabled={isLoading}
          >
            {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            <span className="ml-1">Refresh</span>
          </Button>
        </div>
        {error && (
          <div className="text-xs text-red-500 px-2 py-1 rounded border border-red-500/30 bg-red-500/10">
            {error}
          </div>
        )}
        {isLoading ? (
          <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> Scanning…
          </div>
        ) : drives.length === 0 ? (
          <p className="text-[11px] text-muted-foreground italic">
            No USB drives detected. Plug a USB stick and click Refresh.
          </p>
        ) : (
          <div className="space-y-1.5">
            {drives.map((d) => {
              const busy = busyKey === d.path_or_device
              const stateBadge =
                d.state === "mounted"
                  ? { label: "mounted", cls: "border-green-500/40 text-green-400 bg-green-500/5" }
                  : d.state === "unmounted"
                    ? { label: "unmounted", cls: "border-amber-500/40 text-amber-400 bg-amber-500/5" }
                    : { label: "unformatted", cls: "border-red-500/40 text-red-400 bg-red-500/5" }
              return (
                <div
                  key={d.uuid || d.path_or_device}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-2 rounded border border-border bg-background"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <code className="font-mono text-xs text-foreground">{d.path_or_device}</code>
                      <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${stateBadge.cls}`}>
                        {stateBadge.label}
                      </Badge>
                      {d.size && (
                        <span className="text-[10px] text-muted-foreground">{d.size}</span>
                      )}
                      {d.fstype && (
                        <span className="text-[10px] text-muted-foreground font-mono">{d.fstype}</span>
                      )}
                      {d.label && (
                        <span className="text-[10px] text-muted-foreground italic">"{d.label}"</span>
                      )}
                    </div>
                  </div>
                  <div className="shrink-0 flex items-center gap-1">
                    {d.state === "mounted" && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                        onClick={() => onPick(d.path_or_device)}
                      >
                        Use
                      </Button>
                    )}
                    {d.state === "unmounted" && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                        disabled={busy}
                        onClick={() => mountAndUse(d)}
                      >
                        {busy ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
                        Mount and use
                      </Button>
                    )}
                    {d.state === "empty" && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs bg-red-500/10 border-red-500/40 !text-red-400 hover:bg-red-500/20 hover:!text-red-300"
                        disabled={busy}
                        onClick={() => { setFormatTarget(d); setFormatTyped("") }}
                      >
                        Format & use
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Type-to-confirm format dialog — destructive op. */}
      <Dialog open={formatTarget !== null} onOpenChange={(v) => { if (!v) { setFormatTarget(null); setFormatTyped("") } }}>
        <DialogContent className="max-w-md bg-card border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-5 w-5 text-red-500" />
              Format USB drive
            </DialogTitle>
            <DialogDescription className="text-xs">
              This will partition the disk (GPT + a single ext4), then mount it. Everything on this device will be permanently lost.
            </DialogDescription>
          </DialogHeader>
          {formatTarget && (
            <div className="space-y-2">
              <div className="text-xs font-mono px-3 py-2 rounded-md border border-border bg-background/40 break-all">
                {formatTarget.path_or_device}
                {formatTarget.size && <span className="text-muted-foreground"> · {formatTarget.size}</span>}
              </div>
              <Label htmlFor="formatConfirmInput" className="text-xs">
                Type the device path exactly to confirm:
              </Label>
              <Input
                id="formatConfirmInput"
                value={formatTyped}
                onChange={(e) => setFormatTyped(e.target.value)}
                placeholder={formatTarget.path_or_device}
                className="font-mono"
              />
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => { setFormatTarget(null); setFormatTyped("") }}
              disabled={busyKey === formatTarget?.path_or_device}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={formatTyped !== formatTarget?.path_or_device || busyKey === formatTarget?.path_or_device}
              onClick={doFormat}
            >
              {busyKey === formatTarget?.path_or_device ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <AlertTriangle className="h-4 w-4 mr-2" />
              )}
              Wipe and format
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ──────────────────────────────────────────────────────────────
// Custom backup paths (Sprint C).
//
// Persisted at $HB_STATE_DIR/backup-extra-paths.txt (one path per line).
// The runner merges this list into every backup — manual or scheduled,
// default or custom profile.
// ──────────────────────────────────────────────────────────────

interface ExtraPathEntry {
  path: string
  exists: boolean
}

function ExtraPathsSection() {
  const { data, mutate } = useSWR<{ paths: ExtraPathEntry[] }>(
    "/api/host-backups/extra-paths",
    fetcher,
    { refreshInterval: 60000 },
  )

  const [newPath, setNewPath] = useState("")
  const [busyPath, setBusyPath] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const paths = data?.paths ?? []

  async function addPath() {
    if (!newPath.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await fetchApi("/api/host-backups/extra-paths", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: newPath.trim() }),
      })
      setNewPath("")
      mutate()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  async function removePath(p: string) {
    setBusyPath(p)
    setError(null)
    try {
      await fetchApi(`/api/host-backups/extra-paths?path=${encodeURIComponent(p)}`, { method: "DELETE" })
      mutate()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyPath(null)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Paths added here are included in <span className="font-medium text-foreground">every backup</span> (manual or scheduled, default or custom profile) on top of the default profile list. Useful for application data, custom config dirs, etc. ({paths.length} configured)
      </p>

        <div className="flex flex-col sm:flex-row gap-2">
          <Input
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            placeholder="/root/my-folder, /srv/myapp/data, /etc/cron.d ..."
            className="font-mono"
            onKeyDown={(e) => { if (e.key === "Enter" && newPath.trim()) addPath() }}
          />
          <Button
            onClick={addPath}
            disabled={!newPath.trim() || submitting}
            className="shrink-0 bg-blue-500 hover:bg-blue-600 text-white"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
            Add path
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Use the full absolute path. <code className="font-mono">/hola</code> is not the same as <code className="font-mono">/root/hola</code> — the path has to exist on this host exactly as you type it.
        </p>

        {error && (
          <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
            {error}
          </div>
        )}

        {paths.length === 0 ? (
          <div className="text-xs text-muted-foreground py-3 text-center">
            No custom paths yet — backups use the default profile only.
          </div>
        ) : (
          <div className="space-y-1">
            {paths.map((p) => (
              <div
                key={p.path}
                className="flex items-center justify-between gap-3 p-2 rounded-md border border-border bg-background/40"
              >
                <div className="min-w-0 flex-1 flex items-center gap-2">
                  <span className="font-mono text-xs truncate" title={p.path}>{p.path}</span>
                  {!p.exists && (
                    <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/40">
                      missing on disk
                    </Badge>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-red-500 hover:text-red-400 hover:bg-red-500/10 shrink-0"
                  disabled={busyPath === p.path}
                  onClick={() => removePath(p.path)}
                  title="Remove this custom path"
                >
                  {busyPath === p.path ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                </Button>
              </div>
            ))}
          </div>
        )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Backup configuration wrapper (Sprint D.2.a).
//
// Single card hosting Destinations + Custom paths via top-level tabs.
// Future tabs (USB drives, ...) plug in here too.
// ──────────────────────────────────────────────────────────────
function BackupConfigurationCard({
  destinations,
  onDestChanged,
}: {
  destinations?: DestinationsResp
  onDestChanged: () => void
}) {
  return (
    <Card className="bg-card border-border">
      <CardHeader className="space-y-0 pb-3">
        <div className="flex items-center gap-2">
          <Server className="h-5 w-5 text-blue-500" />
          <CardTitle className="text-base font-semibold">Backup configuration</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Destinations — list + add/remove of PBS / Borg / Local targets.
            USB drives are no longer a separate section: they surface in
            this list when mounted, and the add-destination wizard can
            mount / format them inline. */}
        <section className="space-y-2">
          <h3 className="text-sm font-medium">Destinations</h3>
          <DestinationsSection destinations={destinations} onChanged={onDestChanged} />
        </section>

        <div className="h-px bg-border" />

        {/* Custom paths — extra absolute paths included in every backup */}
        <section className="space-y-2">
          <h3 className="text-sm font-medium">Custom paths</h3>
          <ExtraPathsSection />
        </section>
      </CardContent>
    </Card>
  )
}

// ──────────────────────────────────────────────────────────────
// USB drives section (Sprint D.2.b).
//
// Thin Monitor UI around the shell helpers hb_list_usb_partitions,
// hb_mount_usb_partition, hb_format_usb_disk. Mount / unmount are
// safe-ish; format is destructive and gated by a typed-confirmation
// dialog (the operator must re-type the device path) so a misclick
// can't wipe an attached disk.
// ──────────────────────────────────────────────────────────────

interface UsbDrive {
  state: "mounted" | "unmounted" | "empty"
  path_or_device: string
  label: string
  size: string
  fstype: string
  uuid: string
}

function UsbDrivesSection() {
  const { data, mutate, isLoading } = useSWR<{ drives: UsbDrive[] }>(
    "/api/host-backups/usb-drives",
    fetcher,
    { refreshInterval: 30000 },
  )
  const drives = data?.drives ?? []
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [formatTarget, setFormatTarget] = useState<UsbDrive | null>(null)
  const [formatTyped, setFormatTyped] = useState("")

  async function mountDrive(d: UsbDrive) {
    setBusyKey(d.path_or_device)
    setError(null)
    try {
      await fetchApi("/api/host-backups/usb-drives/mount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device: d.path_or_device,
          label: d.label,
          uuid: d.uuid,
        }),
      })
      mutate()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  async function unmountDrive(d: UsbDrive) {
    if (!confirm(`Unmount ${d.path_or_device}? Any backup job pointing at this path will fail until you remount it.`)) return
    setBusyKey(d.path_or_device)
    setError(null)
    try {
      await fetchApi("/api/host-backups/usb-drives/unmount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mountpoint: d.path_or_device }),
      })
      mutate()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  async function doFormat() {
    if (!formatTarget) return
    if (formatTyped !== formatTarget.path_or_device) return
    setBusyKey(formatTarget.path_or_device)
    setError(null)
    try {
      await fetchApi("/api/host-backups/usb-drives/format", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device: formatTarget.path_or_device,
          confirm_device: formatTyped,
        }),
      })
      mutate()
      setFormatTarget(null)
      setFormatTyped("")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Mount USB drives so they can be picked as a local or Borg target. Drives that already had a filesystem can be remounted as-is; raw drives (no partition table) can be wiped and formatted to <code className="font-mono">ext4</code>.
      </p>

      {error && (
        <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="text-xs text-muted-foreground py-3 text-center">
          <Loader2 className="h-4 w-4 animate-spin inline mr-2" />
          Scanning USB drives…
        </div>
      ) : drives.length === 0 ? (
        <div className="text-xs text-muted-foreground py-3 text-center">
          No USB drives detected. Plug one in and refresh — Monitor scans for them automatically every 30s.
        </div>
      ) : (
        <div className="space-y-2">
          {drives.map((d) => {
            const isBusy = busyKey === d.path_or_device
            const stateBadge =
              d.state === "mounted"
                ? { label: "mounted", cls: "text-emerald-400 border-emerald-400/40" }
                : d.state === "unmounted"
                  ? { label: "not mounted", cls: "text-amber-500 border-amber-500/40" }
                  : { label: "no filesystem", cls: "text-red-400 border-red-400/40" }
            return (
              <div
                key={`${d.state}-${d.path_or_device}-${d.uuid}`}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 p-3 rounded-md border border-border bg-background/40"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-sm font-medium">{d.path_or_device}</span>
                    <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${stateBadge.cls}`}>
                      {stateBadge.label}
                    </Badge>
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground flex items-center gap-x-3 gap-y-1 flex-wrap">
                    {d.label && <span><span className="text-muted-foreground/70">label:</span> <code className="font-mono">{d.label}</code></span>}
                    {d.size && <span><span className="text-muted-foreground/70">size:</span> <code className="font-mono">{d.size}</code></span>}
                    {d.fstype && <span><span className="text-muted-foreground/70">fs:</span> <code className="font-mono">{d.fstype}</code></span>}
                    {d.uuid && <span className="hidden sm:inline" title={`uuid: ${d.uuid}`}><span className="text-muted-foreground/70">uuid:</span> <code className="font-mono">{d.uuid.substring(0, 8)}…</code></span>}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {d.state === "mounted" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-2"
                      disabled={isBusy}
                      onClick={() => unmountDrive(d)}
                    >
                      {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                      <span className="ml-1 text-xs">Unmount</span>
                    </Button>
                  )}
                  {d.state === "unmounted" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-2"
                      disabled={isBusy}
                      onClick={() => mountDrive(d)}
                    >
                      {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                      <span className="ml-1 text-xs">Mount</span>
                    </Button>
                  )}
                  {d.state === "empty" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-2 text-red-500 hover:text-red-400 hover:bg-red-500/10"
                      disabled={isBusy}
                      onClick={() => { setFormatTarget(d); setFormatTyped("") }}
                      title="Wipe + format this disk as ext4"
                    >
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span className="ml-1 text-xs">Format</span>
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Format confirmation dialog */}
      <Dialog open={formatTarget !== null} onOpenChange={(v) => { if (!v) { setFormatTarget(null); setFormatTyped("") } }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-500" />
              Wipe and format this disk?
            </DialogTitle>
            <DialogDescription>
              Everything on the disk will be destroyed. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {formatTarget && (
            <div className="space-y-3 text-sm">
              <div className="rounded-md border border-red-500/40 bg-red-500/5 p-3 space-y-1">
                <div className="text-[10px] uppercase tracking-wider text-red-400">Target</div>
                <div className="font-mono text-base">{formatTarget.path_or_device}</div>
                <div className="text-xs text-muted-foreground">Size: {formatTarget.size || "?"}</div>
              </div>
              <div>
                <Label htmlFor="formatConfirm">Type the device path EXACTLY to confirm:</Label>
                <Input
                  id="formatConfirm"
                  value={formatTyped}
                  onChange={(e) => setFormatTyped(e.target.value)}
                  className="font-mono mt-1"
                  placeholder={formatTarget.path_or_device}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                The disk will be re-partitioned (GPT + single ext4 partition) and mounted automatically.
              </p>
            </div>
          )}
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="ghost" onClick={() => { setFormatTarget(null); setFormatTyped("") }} disabled={busyKey === formatTarget?.path_or_device}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={doFormat}
              disabled={formatTyped !== formatTarget?.path_or_device || busyKey === formatTarget?.path_or_device}
            >
              {busyKey === formatTarget?.path_or_device ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <AlertTriangle className="h-4 w-4 mr-2" />
              )}
              Wipe and format
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// JobDetailModal
// ──────────────────────────────────────────────────────────────────────
// Opens when the user clicks a job row. Everything about the job lives
// inside this modal: schedule, retention, profile, destination, the tail
// of the most recent log, and the action buttons (Run / Enable·Disable /
// Edit / Delete). Run polls the job detail every 2s so the user sees the
// result of the manual trigger without having to close-reopen.
// ──────────────────────────────────────────────────────────────────────
function JobDetailModal({
  jobId,
  onClose,
  onEdit,
  onRequestDelete,
  onChanged,
}: {
  jobId: string | null
  onClose: () => void
  onEdit: (id: string) => void
  onRequestDelete: (id: string) => void
  onChanged: () => void
}) {
  const open = jobId !== null
  const [running, setRunning] = useState(false)
  const [runBaseline, setRunBaseline] = useState<string | null>(null)
  const [runBaselineLogPath, setRunBaselineLogPath] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<"" | "toggle">("")
  const [showDisableConfirm, setShowDisableConfirm] = useState(false)

  const { data: detail, mutate: refetch, isLoading } = useSWR<JobDetail>(
    open ? `/api/host-backups/jobs/${encodeURIComponent(jobId!)}` : null,
    fetcher,
    { refreshInterval: running ? 2000 : 0 },
  )

  // While the job is actively running, poll the full log every 1.5 s so
  // the modal shows the runner's output in real time — same UX the
  // "Run manual backup" dialog provides. SWR is disabled when not
  // running, so this only fires during an active trigger.
  const { data: liveLog } = useSWR<{ content: string; log_path: string | null; size: number }>(
    open && running ? `/api/host-backups/jobs/${encodeURIComponent(jobId!)}/log` : null,
    fetcher,
    { refreshInterval: 1500 },
  )

  // Auto-scroll the live log <pre> to the bottom as new lines arrive,
  // otherwise the operator has to manually scroll on every poll cycle.
  const liveLogRef = useRef<HTMLPreElement | null>(null)
  useEffect(() => {
    if (running && liveLogRef.current) {
      liveLogRef.current.scrollTop = liveLogRef.current.scrollHeight
    }
  }, [liveLog, running])

  // The runner truncates the .status file at start (writing RUN_AT
  // only) and appends RESULT= at finish. So during a run we'll see:
  //
  //   last_run_at  = NEW timestamp (advanced past baseline)
  //   last_result  = null
  //
  // and only when it really finishes:
  //
  //   last_run_at  = NEW timestamp
  //   last_result  = "ok" | "failed" | ...
  //
  // Requiring BOTH conditions keeps the live log streaming visible
  // for the whole duration of the run — the previous version exited
  // streaming mode as soon as the runner wrote the new RUN_AT.
  useEffect(() => {
    if (!running || !detail) return
    if (
      detail.last_run_at &&
      detail.last_run_at !== runBaseline &&
      detail.last_result
    ) {
      setRunning(false)
      setRunBaseline(null)
      setRunBaselineLogPath(null)
      onChanged()
    }
  }, [detail, running, runBaseline, onChanged])

  // Reset on close.
  useEffect(() => {
    if (!open) {
      setRunning(false)
      setRunBaseline(null)
      setRunBaselineLogPath(null)
      setActionError(null)
      setBusy("")
      setShowDisableConfirm(false)
    }
  }, [open])

  async function handleRun() {
    if (!detail) return
    setActionError(null)
    setRunBaseline(detail.last_run_at ?? "")
    // Remember the previous run's log path so the streaming view can
    // tell "the runner hasn't created its log yet" (we'd see the OLD
    // path) from "the runner is writing now" (path advanced).
    setRunBaselineLogPath(detail.last_log_path ?? null)
    setRunning(true)
    try {
      await fetchApi(`/api/host-backups/jobs/${encodeURIComponent(detail.id)}/run`, { method: "POST" })
      setTimeout(() => refetch(), 800)
    } catch (e) {
      setRunning(false)
      setRunBaseline(null)
      setRunBaselineLogPath(null)
      setActionError(`Failed to run: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function handleToggle() {
    if (!detail) return
    setActionError(null)
    setBusy("toggle")
    setShowDisableConfirm(false)
    try {
      await fetchApi(`/api/host-backups/jobs/${encodeURIComponent(detail.id)}/toggle`, { method: "POST" })
      await refetch()
      onChanged()
    } catch (e) {
      setActionError(`Failed to toggle: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy("")
    }
  }

  const lastResult = detail?.last_result ?? null
  const lastRunWhen = formatRunAt(detail?.last_run_at ?? null)
  const resultBadge = running
    ? { label: "running", cls: "bg-blue-500/10 border-blue-500/40 text-blue-300" }
    : lastResult === "ok"
      ? { label: "ok", cls: "bg-emerald-500/10 border-emerald-500/40 text-emerald-300" }
      : lastResult
        ? { label: lastResult, cls: "bg-red-500/10 border-red-500/40 text-red-300" }
        : null

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
        {/* Sized down to 3xl now that the log tail lives in the
            archive's inspect modal — the job dialog only needs to fit
            the schedule, retention chips, paths grid and destination.
            overflow-hidden + the inner ScrollArea keep any long repo
            or path string from forcing a horizontal scrollbar. */}
        <DialogContent className="max-w-3xl bg-card border-border overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 flex-wrap text-base">
              <DatabaseBackup className="h-5 w-5 text-blue-500" />
              <span className="font-mono break-all">{detail?.id ?? jobId}</span>
              {detail && (
                <>
                  <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(detail.method)}`}>
                    {detail.method}
                  </Badge>
                  {detail.attached && (
                    <Badge variant="outline" className="text-[10px] text-blue-400 border-blue-400/40 bg-blue-500/5">
                      attached
                    </Badge>
                  )}
                  {!detail.enabled && (
                    <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/40 bg-amber-500/5">
                      disabled
                    </Badge>
                  )}
                </>
              )}
            </DialogTitle>
            <DialogDescription className="text-xs">
              Schedule, profile, destination and last run for this job.
            </DialogDescription>
          </DialogHeader>

          {actionError && (
            <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
              {actionError}
            </div>
          )}

          {isLoading || !detail ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading job…
            </div>
          ) : (
            <ScrollArea className="max-h-[60vh] pr-2">
              {(() => {
                // One accent color per section. The destination color is
                // bound to the job's backend (purple/blue/fuchsia) so the
                // section feels like a continuation of the method badge in
                // the title; the other sections use neutral accent colors
                // that match their semantic (time → amber, content → emerald).
                const destAccent =
                  detail.method === "pbs"
                    ? "text-purple-400"
                    : detail.method === "borg"
                      ? "text-fuchsia-400"
                      : "text-blue-400"
                return (
                  <div className="space-y-4 text-sm">
                    {/* ─── Last run ─────────────────────────── */}
                    {/* The job modal shows only the verdict + timestamp.
                        The actual log lives in the archive's inspect
                        modal where it belongs (one log per .tar.zst). */}
                    <section className="space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-green-500">
                        <Clock className="h-3.5 w-3.5" /> Last run
                      </h4>
                      <div className="flex items-center gap-2 flex-wrap text-xs">
                        {resultBadge ? (
                          <span className={`px-2 py-0.5 rounded text-[10px] uppercase tracking-wide border inline-flex items-center gap-1 ${resultBadge.cls}`}>
                            {running && <Loader2 className="h-3 w-3 animate-spin" />}
                            {resultBadge.label}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">never run</span>
                        )}
                        {lastRunWhen && <span className="text-muted-foreground">{lastRunWhen}</span>}
                      </div>
                      {running && (
                        // Live mode — poll /log every 1.5 s and auto-scroll
                        // so the operator watches the runner output as it
                        // happens. The archive isn't on disk yet, so this
                        // is the only place to surface the running log.
                        // Suppressed once the run finishes.
                        (() => {
                          const sameOldLog =
                            !!liveLog?.log_path &&
                            !!runBaselineLogPath &&
                            liveLog.log_path === runBaselineLogPath
                          const showContent = liveLog?.content && !sameOldLog
                          return (
                            <div className="rounded-md border border-blue-500/40 bg-blue-500/5 p-2">
                              <pre
                                ref={liveLogRef}
                                className="text-[11px] font-mono whitespace-pre-wrap break-all max-h-64 overflow-auto text-foreground/90"
                              >
{showContent ? liveLog!.content : "Waiting for runner to start…"}
                              </pre>
                              <div className="flex items-center justify-between mt-2">
                                <span className="text-[10px] text-blue-300 inline-flex items-center gap-1.5">
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  {showContent
                                    ? `live · ${formatBytes(liveLog?.size ?? 0)}`
                                    : "starting…"}
                                </span>
                                {showContent && liveLog?.log_path && (
                                  <span className="text-[10px] text-muted-foreground font-mono break-all">
                                    {liveLog.log_path}
                                  </span>
                                )}
                              </div>
                            </div>
                          )
                        })()
                      )}
                    </section>

                    {/* ─── Schedule + retention ─────────────── */}
                    <section className="space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-green-500">
                        <Calendar className="h-3.5 w-3.5" /> Schedule
                      </h4>
                      <Field
                        icon={<Calendar className="h-3 w-3 text-green-500/80" />}
                        label="when"
                        value={humanizeOnCalendar(detail.on_calendar)}
                        labelClassName="text-green-500/90"
                      />
                      {detail.next_run && (
                        <Field
                          icon={<Clock className="h-3 w-3 text-green-500/80" />}
                          label="next run"
                          value={formatNext(detail.next_run)}
                          labelClassName="text-green-500/90"
                        />
                      )}
                      <RetentionDisplay retention={detail.retention || {}} />
                    </section>

                    {/* ─── Profile + paths ──────────────────── */}
                    <section className="space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-green-500">
                        <FileSearch className="h-3.5 w-3.5" /> Profile
                      </h4>
                      <Field
                        icon={<Server className="h-3 w-3 text-green-500/80" />}
                        label="mode"
                        value={detail.profile_mode || "—"}
                        mono
                        labelClassName="text-green-500/90"
                      />
                      {detail.paths && detail.paths.length > 0 && (
                        <PathsDisplay paths={detail.paths} />
                      )}
                    </section>

                    {/* ─── Destination ──────────────────────── */}
                    <section className="space-y-1">
                      <h4 className={`text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 ${destAccent}`}>
                        <HardDrive className="h-3.5 w-3.5" /> Destination
                      </h4>
                      <Field icon={<HardDrive className={`h-3 w-3 ${destAccent} opacity-80`} />} label="target" value={detail.destination || "—"} mono />
                      {detail.method === "pbs" && (
                        <>
                          {detail.pbs_repository && (
                            <Field icon={<Server className={`h-3 w-3 ${destAccent} opacity-80`} />} label="repository" value={detail.pbs_repository} mono />
                          )}
                          {detail.pbs_backup_id && (
                            <Field icon={<Archive className={`h-3 w-3 ${destAccent} opacity-80`} />} label="backup-id" value={detail.pbs_backup_id} mono />
                          )}
                        </>
                      )}
                      {detail.method === "borg" && (
                        <>
                          {detail.borg_repo && (
                            <Field icon={<Server className={`h-3 w-3 ${destAccent} opacity-80`} />} label="repo" value={detail.borg_repo} mono />
                          )}
                          <Field icon={<FileSearch className={`h-3 w-3 ${destAccent} opacity-80`} />} label="encryption" value={detail.borg_encrypt_mode} mono />
                        </>
                      )}
                      {detail.method === "local" && detail.local_dest_dir && (
                        <Field icon={<HardDrive className={`h-3 w-3 ${destAccent} opacity-80`} />} label="dir" value={detail.local_dest_dir} mono />
                      )}
                      {detail.pve_storage && (
                        <Field icon={<DatabaseBackup className={`h-3 w-3 ${destAccent} opacity-80`} />} label="pve storage" value={detail.pve_storage} mono />
                      )}
                    </section>
                  </div>
                )
              })()}
            </ScrollArea>
          )}

          {detail && (
            <div className="border-t border-border pt-3 flex flex-wrap gap-2 justify-end">
              <Button
                size="sm"
                onClick={handleRun}
                disabled={running || busy !== ""}
                variant="outline"
                // Button's outline variant sets `hover:text-accent-foreground`,
                // which washes the accent color to near-white on hover. The
                // `!` modifier on `text-*` keeps our accent color across both
                // states so the buttons read as Run / Disable / Edit / Delete
                // at a glance instead of four near-white outlines.
                className="bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                title={detail.attached
                  ? "Trigger an ad-hoc run now (the PVE timer keeps its own schedule)"
                  : "Trigger this job now"}
              >
                {running ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                ) : (
                  <PlayCircle className="h-3.5 w-3.5 mr-1" />
                )}
                {running ? "Running…" : "Run now"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={running || busy !== ""}
                className={detail.enabled
                  ? "bg-amber-500/10 border-amber-500/40 !text-amber-400 hover:bg-amber-500/20 hover:!text-amber-300"
                  : "bg-emerald-500/10 border-emerald-500/40 !text-emerald-400 hover:bg-emerald-500/20 hover:!text-emerald-300"}
                onClick={() => {
                  if (detail.enabled) setShowDisableConfirm(true)
                  else handleToggle()
                }}
              >
                {busy === "toggle" ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                ) : detail.enabled ? (
                  <Power className="h-3.5 w-3.5 mr-1" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                )}
                {detail.enabled ? "Disable" : "Enable"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={running || busy !== ""}
                className="bg-emerald-500/10 border-emerald-500/40 !text-emerald-400 hover:bg-emerald-500/20 hover:!text-emerald-300"
                onClick={() => onEdit(detail.id)}
              >
                <Pencil className="h-3.5 w-3.5 mr-1" />
                Edit
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={running || busy !== ""}
                className="bg-red-500/10 border-red-500/40 !text-red-400 hover:bg-red-500/20 hover:!text-red-300"
                onClick={() => onRequestDelete(detail.id)}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ─── Confirm Disable ──────────────────────────────────── */}
      <Dialog open={showDisableConfirm} onOpenChange={setShowDisableConfirm}>
        <DialogContent className="max-w-md bg-card border-border">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <Power className="h-5 w-5 text-amber-500" />
              Disable job
            </DialogTitle>
            <DialogDescription className="text-xs">
              The systemd timer will be stopped — no further automatic runs. You can re-enable it later from this same dialog.
            </DialogDescription>
          </DialogHeader>
          <div className="text-sm font-mono px-3 py-2 rounded-md border border-border bg-background/40 break-all">
            {detail?.id}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowDisableConfirm(false)}>
              Cancel
            </Button>
            <Button
              variant="outline"
              className="bg-amber-500/10 border-amber-500/40 !text-amber-400 hover:bg-amber-500/20 hover:!text-amber-300"
              onClick={handleToggle}
            >
              <Power className="h-3.5 w-3.5 mr-1" />
              Disable
            </Button>
          </div>
        </DialogContent>
      </Dialog>

    </>
  )
}
