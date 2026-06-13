"use client"

import { useState } from "react"
import useSWR from "swr"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
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
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
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
  last_status: string | null
  next_run: string | null
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

export function HostBackup() {
  const { data: jobsResp, error: jobsErr, mutate: mutateJobs } = useSWR<{ jobs: BackupJob[] }>(
    "/api/host-backups/jobs",
    fetcher,
    { refreshInterval: 30000 },
  )
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function runJob(id: string) {
    setBusyJobId(id)
    setActionError(null)
    try {
      const r = await fetchApi(`/api/host-backups/jobs/${encodeURIComponent(id)}/run`, { method: "POST" })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      mutateJobs()
    } catch (e) {
      setActionError(`Failed to run "${id}": ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyJobId(null)
    }
  }

  async function toggleJob(id: string) {
    setBusyJobId(id)
    setActionError(null)
    try {
      const r = await fetchApi(`/api/host-backups/jobs/${encodeURIComponent(id)}/toggle`, { method: "POST" })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      mutateJobs()
    } catch (e) {
      setActionError(`Failed to toggle "${id}": ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyJobId(null)
    }
  }
  const { data: archivesResp, error: archivesErr } = useSWR<{ archives: BackupArchive[] }>(
    "/api/host-backups/archives",
    fetcher,
    { refreshInterval: 30000 },
  )

  const [inspectingArchive, setInspectingArchive] = useState<BackupArchive | null>(null)

  return (
    <div className="space-y-4 md:space-y-6">
      {/* ── Scheduled jobs ───────────────────────────────── */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-blue-500" />
            <CardTitle className="text-base font-semibold">Scheduled Backup Jobs</CardTitle>
          </div>
          <Badge variant="outline">{jobsResp?.jobs?.length ?? 0}</Badge>
        </CardHeader>
        <CardContent>
          {jobsErr ? (
            <div className="text-sm text-red-500 py-4">Failed to load jobs</div>
          ) : !jobsResp ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading...
            </div>
          ) : jobsResp.jobs.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4 space-y-2">
              <p>No scheduled backup jobs configured yet.</p>
              <p>
                For a <span className="font-medium text-foreground">one-shot manual backup</span>{" "}
                or to create a scheduled job, run:
              </p>
              <code className="block mt-1 px-3 py-2 rounded-md bg-muted text-xs font-mono">
                bash /usr/local/share/proxmenux/scripts/backup_restore/backup_host.sh
              </code>
              <p className="text-xs">
                Menu options 1-6 are manual backups (default or custom paths, to PBS, Borg, or local tar). Option 7 opens the scheduler if you want a recurring job.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              {actionError && (
                <div className="mb-2 text-xs text-red-500 px-2 py-1 rounded bg-red-500/10 border border-red-500/20">
                  {actionError}
                </div>
              )}
              <table className="w-full text-sm">
                <thead className="text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <tr>
                    <th className="text-left px-2 py-2">ID</th>
                    <th className="text-left px-2 py-2">Destination</th>
                    <th className="text-left px-2 py-2">Method</th>
                    <th className="text-left px-2 py-2">Schedule</th>
                    <th className="text-left px-2 py-2">Last status</th>
                    <th className="text-left px-2 py-2">Next run</th>
                    <th className="text-right px-2 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {jobsResp.jobs.map((j) => {
                    const isBusy = busyJobId === j.id
                    return (
                    <tr key={j.id} className="text-xs">
                      <td className="px-2 py-2 font-mono">{j.id}</td>
                      <td className="px-2 py-2 font-mono truncate max-w-[260px]" title={j.destination}>
                        {j.destination || "—"}
                      </td>
                      <td className="px-2 py-2 uppercase">{j.method}</td>
                      <td className="px-2 py-2 font-mono">
                        {j.on_calendar}
                        {j.attached && (
                          <Badge variant="outline" className="ml-2 text-blue-400 border-blue-400/30">
                            attached
                          </Badge>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        {j.last_status ? (
                          <span className="text-xs">{j.last_status}</span>
                        ) : (
                          <span className="text-muted-foreground">never</span>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <span className="text-xs">{j.attached ? "—" : formatNext(j.next_run)}</span>
                        {!j.enabled && (
                          <Badge variant="outline" className="ml-2 text-amber-500 border-amber-500/30">
                            disabled
                          </Badge>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            disabled={isBusy}
                            onClick={() => runJob(j.id)}
                            title="Run this backup job now"
                          >
                            {isBusy ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <PlayCircle className="h-3.5 w-3.5" />
                            )}
                            <span className="ml-1">Run</span>
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            disabled={isBusy}
                            onClick={() => toggleJob(j.id)}
                            title={j.enabled ? "Disable this job" : "Enable this job"}
                          >
                            {isBusy ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : j.enabled ? (
                              <XCircle className="h-3.5 w-3.5" />
                            ) : (
                              <CheckCircle2 className="h-3.5 w-3.5" />
                            )}
                            <span className="ml-1">{j.enabled ? "Disable" : "Enable"}</span>
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )})}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Available archives ─────────────────────────────── */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex items-center gap-2">
            <Archive className="h-5 w-5 text-blue-500" />
            <CardTitle className="text-base font-semibold">Available Archives</CardTitle>
          </div>
          <Badge variant="outline">{archivesResp?.archives?.length ?? 0}</Badge>
        </CardHeader>
        <CardContent>
          {archivesErr ? (
            <div className="text-sm text-red-500 py-4">Failed to load archives</div>
          ) : !archivesResp ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading...
            </div>
          ) : archivesResp.archives.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4">
              No backup archives found on this host. We scan <code className="font-mono">/var/lib/vz/dump</code> and any custom destination from a scheduled job, looking for files named <code className="font-mono">hostcfg-&lt;hostname&gt;-*.tar.zst</code> (manual backups) or <code className="font-mono">&lt;job_id&gt;-*.tar.*</code> (scheduled). PBS and Borg backups aren't surfaced in the UI yet.
            </div>
          ) : (
            <div className="space-y-2">
              {archivesResp.archives.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between gap-3 p-3 rounded-md border border-border bg-background/40 hover:bg-white/5 transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-xs truncate" title={a.path}>
                      {a.id}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-3 flex-wrap">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatMtime(a.mtime)}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <HardDrive className="h-3 w-3" />
                        {formatStorage(a.size_bytes)}
                      </span>
                      {a.kind === "scheduled" && a.job_id ? (
                        <span title={`identified via ${a.detected_via}`}>job: <code className="font-mono">{a.job_id}</code></span>
                      ) : a.kind === "legacy" ? (
                        <span
                          title={`identified via ${a.detected_via} — no sidecar metadata`}
                          className="uppercase tracking-wide text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/40 text-amber-400"
                        >
                          legacy
                        </span>
                      ) : (
                        <span
                          title={`identified via ${a.detected_via}`}
                          className="uppercase tracking-wide text-[10px] px-1.5 py-0.5 rounded bg-white/5 border border-border"
                        >
                          manual
                        </span>
                      )}
                      {a.source_hostname && a.source_hostname !== "" && (
                        <span>host: <code className="font-mono">{a.source_hostname}</code></span>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setInspectingArchive(a)}
                    className="flex-shrink-0"
                  >
                    <FileSearch className="h-3.5 w-3.5 mr-1.5" />
                    Inspect
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Inspect / preflight modal ──────────────────────── */}
      <InspectModal
        archive={inspectingArchive}
        onClose={() => setInspectingArchive(null)}
      />
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
}: {
  archive: BackupArchive | null
  onClose: () => void
}) {
  const open = archive !== null
  const [mode, setMode] = useState<string>("full")
  const [report, setReport] = useState<PreflightReport | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: manifest, error: manifestErr } = useSWR<{
    source_host: ManifestSourceHost
    proxmenux_installed_components: Array<{ id: string; version_at_backup: string | null }>
    vms_lxcs_at_backup: { vms: unknown[]; lxcs: unknown[] }
    storage_inventory?: { zfs_pools?: unknown[]; lvm?: { vgs?: unknown[] } }
  }>(
    archive ? `/api/host-backups/archives/${encodeURIComponent(archive.id)}/manifest` : null,
    fetcher,
  )

  const runPreflight = async () => {
    if (!archive) return
    setRunning(true)
    setError(null)
    setReport(null)
    try {
      const res = await fetchApi<PreflightReport>(
        `/api/host-backups/archives/${encodeURIComponent(archive.id)}/preflight`,
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

  // Reset state when archive changes
  const archiveId = archive?.id
  // Note: this useEffect-like cleanup happens via key={archiveId} on the
  // Dialog content so React unmounts and remounts; state resets naturally.

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent key={archiveId} className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <DatabaseBackup className="h-5 w-5 text-blue-500" />
            <span className="font-mono text-sm truncate">{archive?.id}</span>
          </DialogTitle>
          <DialogDescription className="text-xs">
            Inspect the manifest snapshot taken at backup time, then dry-run the restore plan for a chosen mode. Read-only; nothing on this host is changed.
          </DialogDescription>
        </DialogHeader>

        {/* Manifest summary */}
        {manifestErr ? (
          <div className="text-sm text-red-500 py-2">
            Couldn't read the manifest from this archive — it may have been created before the manifest format was added.
          </div>
        ) : !manifest ? (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Reading manifest...
          </div>
        ) : (
          <ManifestSummary manifest={manifest} />
        )}

        {/* Preflight controls */}
        <div className="border-t border-border pt-4 space-y-3">
          <div className="flex items-end gap-3">
            <div className="flex-1">
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
            <Button onClick={runPreflight} disabled={running || !manifest}>
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <PlayCircle className="h-4 w-4 mr-2" />
                  Run preflight
                </>
              )}
            </Button>
          </div>

          {error && (
            <div className="text-sm text-red-500 p-2 rounded-md border border-red-500/30 bg-red-500/10">
              {error}
            </div>
          )}

          {report && <PreflightReportView report={report} />}
        </div>
      </DialogContent>
    </Dialog>
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

function Field({ icon, label, value, mono }: { icon?: React.ReactNode; label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
        {icon}
        {label}
      </div>
      <div className={`${mono ? "font-mono" : ""} truncate`} title={value}>
        {value}
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
