"use client"

import { useState, useEffect, useRef } from "react"
import useSWR from "swr"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog"
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
  Lock,
  Eye,
  Network,
  Cpu,
  Package,
  ShieldCheck,
  Info,
  ListTree,
  History,
} from "lucide-react"
import { ScriptTerminalModal } from "./script-terminal-modal"
import { RestoreProgressCard } from "./restore-progress-card"
import { fetchApi, getApiUrl } from "../lib/api-config"
import { fetchTerminalTicket } from "../lib/terminal-ws"
import { formatStorage, formatBytes } from "../lib/utils"
import { getStorageUsageColor } from "../lib/storage-usage-color"

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
  // True when this job ships encrypted backups — PBS_KEYFILE set for
  // PBS, or BORG_ENCRYPT_MODE != "none" for Borg. Drives the lock
  // badge in the row + the toggle's initial state in Edit.
  encrypted?: boolean
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
  // Whether THIS snapshot is encrypted. For PBS it's derived from
  // any file having crypt-mode != "none"; for Borg it follows the
  // target's encrypt_mode.
  encrypted?: boolean
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

// A job is "running" when its .status file has RUN_AT (runner started)
// but no RESULT yet (runner hasn't written the verdict). Lets the UI
// flag in-progress runs both inline (badge in the row) and from the
// Manual backups card so an operator who closes the dialog can re-open
// the live stream.
function isJobRunning(j: BackupJob | null | undefined): boolean {
  if (!j?.last_status) return false
  const s = parseJobStatus(j.last_status)
  return !!(s?.runAt && !s?.result)
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

// ── PBS keyfile management (shared between CreateJob + ManualBackup) ──
//
// Rendered inside the encryption section when a keyfile is already
// installed. Replaces the older static info box that pointed to a
// non-existent "Settings → Host backup" panel: the operator now has
// concrete actions (download keyfile, update stored passphrase,
// change recovery model, remove keyfile) with destructive-confirmation
// modals that call the /api/host-backups/pbs-encryption/* endpoints
// and mutate pbsRecoveryStatus so the parent dialog re-renders on
// success. There is no "Replace keyfile" action any more — replacing
// the key would silently orphan every encrypted backup that used it.
// The operator instead uses Remove + set up again via the normal flow
// (Generate a new keyfile / Use an existing keyfile), which surfaces
// the source picker properly.
// ──────────────────────────────────────────────────────────────
// PbsKeyfileActions — the trimmed action set the operator sees
// inside every PBS destination row: Download, Upload (import a new
// keyfile), Delete. No stored-passphrase rotation, no escrow toggle
// — those live in the setup dialogs where the operator makes the
// initial call. Placing these three next to the destination they
// belong to matches "the key is a PBS thing" without dragging in
// the fuller management surface.
// ──────────────────────────────────────────────────────────────
function PbsKeyfileActions() {
  const { data: info, mutate: mutateInfo } = useSWR<{
    installed: boolean
    fingerprint?: string
    path: string
    escrow_mode?: "none" | "local" | "full"
  }>("/api/host-backups/pbs-encryption/keyfile-info", fetcher)

  const [uploadOpen, setUploadOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPath, setImportPath] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const closeUpload = () => {
    setUploadOpen(false)
    setImportFile(null)
    setImportPath("")
    setBusy(false)
    setErr(null)
  }
  const closeDelete = () => {
    setDeleteOpen(false)
    setBusy(false)
    setErr(null)
  }

  const download = () => {
    // Same plain-<a>-download trick used elsewhere: bypasses fetch so
    // an ad-blocker or a stale SWR cache can't intervene.
    const a = document.createElement("a")
    a.href = "/api/host-backups/pbs-encryption/download-keyfile"
    a.download = "pbs-key.conf"
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const runUpload = async () => {
    if (!importFile && !importPath.trim()) {
      setErr("Pick a keyfile file or enter an absolute path on this host.")
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const body: Record<string, unknown> = { escrow_mode: "none" }
      if (importFile) {
        const buf = new Uint8Array(await importFile.arrayBuffer())
        let bin = ""
        for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i])
        body.source = "content"
        body.content_b64 = btoa(bin)
      } else {
        body.source = "path"
        body.keyfile_path = importPath.trim()
      }
      await fetchApi("/api/host-backups/pbs-encryption/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      await mutateInfo()
      closeUpload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const runDelete = async () => {
    setBusy(true)
    setErr(null)
    try {
      await fetchApi("/api/host-backups/pbs-encryption/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
      await mutateInfo()
      closeDelete()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const installed = !!info?.installed

  return (
    <div className="mt-2 border-t border-white/10 pt-2 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="text-xs min-w-0 flex-1 flex items-center gap-1.5">
          <span className="font-medium text-muted-foreground">Encryption keyfile:</span>{" "}
          {installed ? (
            <span
              className="inline-flex items-center gap-1 text-emerald-400 font-medium"
              title={info?.fingerprint ? `Keyfile fingerprint: ${info.fingerprint}` : undefined}
            >
              <CheckCircle2 className="h-4 w-4" />
              installed
            </span>
          ) : (
            <span className="text-blue-400 font-medium">not installed on this host</span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {installed && (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 text-[11px] !text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/10"
                onClick={download}
                title="Download the keyfile as pbs-key.conf"
              >
                <Download className="h-3.5 w-3.5 mr-1" />
                Download
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 text-[11px] !text-red-400 border-red-500/40 hover:bg-red-500/10"
                onClick={() => setDeleteOpen(true)}
                title="Remove the local keyfile"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete
              </Button>
            </>
          )}
          {!installed && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-[11px] !text-blue-400 border-blue-500/40 hover:bg-blue-500/10"
              onClick={() => setUploadOpen(true)}
              title="Import a keyfile you already have"
            >
              <Lock className="h-3.5 w-3.5 mr-1" />
              Upload
            </Button>
          )}
        </div>
      </div>

      <Dialog open={uploadOpen} onOpenChange={(v) => !v && closeUpload()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload PBS keyfile</DialogTitle>
            <DialogDescription>
              Import a keyfile you already have. It lands at <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code> and every subsequent encrypted backup reuses it. Recovery escrow stays off — use the setup wizard if you want to enable it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="pbsKfUploadFile" className="text-xs">Upload from your machine</Label>
              <Input
                id="pbsKfUploadFile"
                type="file"
                accept=".conf,.key,application/json,text/plain"
                onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                disabled={busy || !!importPath.trim()}
                className="h-9 mt-1"
              />
            </div>
            <div className="text-[10px] text-center text-muted-foreground">— or —</div>
            <div>
              <Label htmlFor="pbsKfUploadPath" className="text-xs">Absolute path on this host</Label>
              <Input
                id="pbsKfUploadPath"
                type="text"
                value={importPath}
                onChange={(e) => setImportPath(e.target.value)}
                disabled={busy || !!importFile}
                placeholder="/usr/local/share/proxmenux/pbs-key.conf"
                className="h-9 mt-1 font-mono text-xs"
              />
            </div>
            {err && (
              <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">{err}</div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeUpload} disabled={busy}>Cancel</Button>
            <Button
              onClick={runUpload}
              disabled={busy || (!importFile && !importPath.trim())}
              className="!bg-blue-500 hover:!bg-blue-600 !text-white"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Import"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={(v) => !v && closeDelete()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-400" />
              Delete keyfile
            </DialogTitle>
            <DialogDescription>
              Backups already stored on PBS were encrypted with the current keyfile. After this action:
            </DialogDescription>
          </DialogHeader>
          <ul className="text-xs text-muted-foreground list-disc list-inside space-y-1 pl-2">
            <li>New backups will use no encryption on this host until a new keyfile is set up.</li>
            <li>Downloading pre-existing encrypted backups from this host <strong className="text-red-400">will fail</strong> unless you kept a copy of the current key.</li>
            <li>Existing recovery blobs on PBS stay intact — they still recover the old key with its original passphrase.</li>
          </ul>
          {err && (
            <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">{err}</div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={closeDelete} disabled={busy}>Cancel</Button>
            <Button onClick={runDelete} disabled={busy} className="!bg-red-500 hover:!bg-red-600 !text-white">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function KeyfileActionsBar({
  mutateStatus,
  escrowMode,
}: {
  mutateStatus: () => Promise<unknown>
  escrowMode?: "none" | "local" | "full"
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [pass1, setPass1] = useState("")
  const [pass2, setPass2] = useState("")
  // Pending radio state — reflects the operator's intended mode after
  // Apply. Seeded from the current mode so a No-op click on Apply is
  // rejected. Binary UX ('none' vs 'full') matches the setup wizard.
  const currentIsFull = escrowMode === "full"
  const [pendingMode, setPendingMode] = useState<"none" | "full">(currentIsFull ? "full" : "none")

  const runApply = async () => {
    // Yes → passphrase required + match. No → passphrase ignored.
    if (pendingMode === "full") {
      if (!pass1) {
        setErr("Recovery passphrase is required.")
        return
      }
      if (pass1 !== pass2) {
        setErr("Passphrases do not match.")
        return
      }
    }
    setBusy(true)
    setErr(null)
    try {
      const body: Record<string, unknown> = { escrow_mode: pendingMode }
      if (pendingMode === "full") body.escrow_passphrase = pass1
      await fetchApi("/api/host-backups/pbs-encryption/set-escrow-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      await mutateStatus()
      setPass1("")
      setPass2("")
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // Contextual Apply-button label. Three transitions:
  //   No → Yes            → "Start uploading"
  //   Yes → No            → "Stop uploading"
  //   Yes → Yes (new pw)  → "Update passphrase" (rewraps envelope)
  const applyLabel =
    pendingMode === "full" && !currentIsFull
      ? "Start uploading"
      : pendingMode === "none" && currentIsFull
        ? "Stop uploading"
        : pendingMode === "full" && currentIsFull
          ? "Update passphrase"
          : "Apply"

  // Apply is enabled when there is a real change to commit.
  const canApply = (
    (pendingMode !== (currentIsFull ? "full" : "none")) ||        // mode change
    (pendingMode === "full" && !!pass1 && pass1 === pass2)        // passphrase update
  )

  const download = () => {
    const a = document.createElement("a")
    a.href = "/api/host-backups/pbs-encryption/download-keyfile"
    a.download = "pbs-key.conf"
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <div className="space-y-3">
      <div className="text-[11px] font-medium text-foreground">Manage installed keyfile</div>

      {/* Current status — icon + colour by state, no truncated fp. */}
      {escrowMode !== undefined && (
        <div className="flex items-center gap-2 text-xs bg-background/40 border border-white/10 rounded px-2.5 py-1.5">
          <span className="font-medium text-foreground">Upload to PBS:</span>
          {currentIsFull ? (
            <span className="inline-flex items-center gap-1 text-emerald-400 font-medium">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Yes — envelope uploaded on every backup
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-blue-400 font-medium">
              No — kept only on this host
            </span>
          )}
        </div>
      )}

      {/* Change mode + passphrase — one integrated form, no popover.
          Radio picks the intent; the passphrase pair unfolds when the
          intent is Yes (both for a first-time upload and for a
          passphrase rotation while already in Yes). */}
      <div className="space-y-2 rounded-md border border-blue-500/30 bg-blue-500/5 p-3">
        <div className="text-[11px] font-medium text-foreground">Upload key to PBS?</div>
        <div className="grid gap-1.5">
          <label className="flex items-start gap-2 cursor-pointer text-[11px]">
            <input
              type="radio"
              name="pendingModeChange"
              checked={pendingMode === "none"}
              onChange={() => { setPendingMode("none"); setPass1(""); setPass2("") }}
              className="mt-1"
            />
            <div className="flex-1">
              <div className="font-medium">No, keep local only</div>
              <div className="text-muted-foreground">Keyfile stays at <code className="font-mono text-[10.5px]">/usr/local/share/proxmenux/pbs-key.conf</code>. You handle the offsite copy — use <em>Download keyfile</em> below.</div>
            </div>
          </label>
          <label className="flex items-start gap-2 cursor-pointer text-[11px]">
            <input
              type="radio"
              name="pendingModeChange"
              checked={pendingMode === "full"}
              onChange={() => setPendingMode("full")}
              className="mt-1"
            />
            <div className="flex-1">
              <div className="font-medium">Yes, upload</div>
              <div className="text-muted-foreground">A passphrase-wrapped copy of the keyfile is uploaded to PBS with every backup. Fill the passphrase pair below to enable — or to rotate the current one.</div>
            </div>
          </label>
        </div>
        {pendingMode === "full" && (
          <div className="space-y-2 pt-2 border-t border-blue-500/20">
            <div>
              <Label htmlFor="mgmtPass1" className="text-[11px]">
                {currentIsFull ? "New recovery passphrase" : "Recovery passphrase"}
              </Label>
              <Input
                id="mgmtPass1"
                type="password"
                value={pass1}
                onChange={(e) => setPass1(e.target.value)}
                placeholder={currentIsFull ? "Type a new passphrase to rotate" : "Long random string — write it down somewhere safe"}
                className="font-mono mt-1 h-8 text-xs"
              />
            </div>
            <div>
              <Label htmlFor="mgmtPass2" className="text-[11px]">Confirm passphrase</Label>
              <Input
                id="mgmtPass2"
                type="password"
                value={pass2}
                onChange={(e) => setPass2(e.target.value)}
                placeholder="Type it again"
                className="font-mono mt-1 h-8 text-xs"
              />
              {pass1 && pass2 && pass1 !== pass2 && (
                <p className="text-[11px] text-red-400 mt-1">Passphrases don&apos;t match.</p>
              )}
            </div>
          </div>
        )}
        {err && (
          <div className="text-[11px] text-red-500 px-2 py-1.5 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">{err}</div>
        )}
        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            onClick={runApply}
            disabled={busy || !canApply}
            className="!bg-blue-500 hover:!bg-blue-600 !text-white disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : applyLabel}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 text-[11px] !text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/10"
          onClick={download}
        >
          <Download className="h-3.5 w-3.5 mr-1" />
          Download keyfile
        </Button>
      </div>

      {/* Deletion lives inside the PBS destination row (PbsKeyfileActions);
          setup menus of Create Job / Manual Backup never surface it. */}
    </div>
  )
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
  const [watchingManualId, setWatchingManualId] = useState<string | null>(null)
  const [runningManual, setRunningManual] = useState<boolean>(false)
  // Independent tracker for the most recent manual backup that's still
  // running. Survives the operator closing the ManualJobWatchModal —
  // the modal only drives auto-refresh while it's OPEN, so if the
  // operator dismisses it before the job finishes, the archive lists
  // would only refresh on the next SWR tick (30-60 s). Polling the
  // job status here at 3 s and calling mutate once we see the run
  // transition to completed closes that gap regardless of modal
  // state. Set = single slot per launch; a fresh manual replaces the
  // slot (the previous one falls back to the periodic SWR tick).
  const [pendingManualJobId, setPendingManualJobId] = useState<string | null>(null)

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

  // Background poll for the pending manual backup, independent of the
  // watch modal being open. Fires mutateArchives/mutateRemoteArchives
  // as soon as the run flips to done so the operator sees the new
  // entry in Available Archives without a manual refresh.
  const { data: pendingManualPoll } = useSWR<JobDetail>(
    pendingManualJobId ? `/api/host-backups/jobs/${encodeURIComponent(pendingManualJobId)}` : null,
    fetcher,
    { refreshInterval: 3000 },
  )
  useEffect(() => {
    const d = pendingManualPoll as JobDetail | undefined
    if (pendingManualJobId && d?.last_run_at && d?.last_result) {
      mutateJobs()
      mutateArchives()
      mutateRemoteArchives()
      setPendingManualJobId(null)
    }
  }, [pendingManualPoll, pendingManualJobId, mutateJobs, mutateArchives, mutateRemoteArchives])

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
      {/* ── Post-restore progress card ────────────────────
          Renders only while a restore is running or its
          summary hasn't been acknowledged. Once dismissed,
          it collapses to a "Past restores" ghost button. */}
      <RestoreProgressCard />

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
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
                  {actionError}
                </div>
              )}
              {jobsResp.jobs.filter((j) => !j.manual).map((j) => {
                const status = parseJobStatus(j.last_status)
                const running = isJobRunning(j)
                // While running we override the ok/failed pill with a
                // running spinner — same way the modal does. Clicking
                // the row re-opens JobDetailModal which auto-detects
                // the in-progress state and resumes streaming.
                const statusBadge = running
                  ? { label: "running", cls: "bg-blue-500/10 border-blue-500/40 text-blue-300" }
                  : status?.result === "ok"
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
                        {j.encrypted && (
                          <Badge
                            variant="outline"
                            className="text-[10px] uppercase tracking-wide border-emerald-500/40 text-emerald-400 bg-emerald-500/5"
                            title="Encrypted backups (client-side keyfile / borg repokey)"
                          >
                            <Lock className="h-3.5 w-3.5" />
                          </Badge>
                        )}
                        {/* Surface the profile mode at row level so the
                            operator can tell at a glance whether the
                            job ships the default path set or a custom
                            list — without having to open the detail
                            modal. Same wording the modal uses. */}
                        <Badge
                          variant="outline"
                          className={`text-[10px] uppercase tracking-wide ${
                            j.profile_mode === "custom"
                              ? "border-cyan-500/40 text-cyan-400 bg-cyan-500/5"
                              : "border-border text-muted-foreground bg-background/40"
                          }`}
                          title={
                            j.profile_mode === "custom"
                              ? "Custom path list — only the paths the operator picked"
                              : "Default path list — ProxMenux's recommended host config set"
                          }
                        >
                          {j.profile_mode === "custom" ? "custom" : "default"}
                        </Badge>
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
                              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide border ${statusBadge.cls}`}>
                                {running && <Loader2 className="h-2.5 w-2.5 animate-spin" />}
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
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <PlayCircle className="h-5 w-5 text-purple-400" />
            <CardTitle className="text-base font-semibold">Manual backups</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Manual backups run once and stop — no schedule.
          </p>
          <Button
            className="w-full sm:w-auto bg-purple-500 hover:bg-purple-600 text-white"
            onClick={() => setRunningManual(true)}
          >
            <PlayCircle className="h-4 w-4 mr-2" />
            Run manual backup
          </Button>
          {/* In-progress manual jobs. If the operator closed the
              ManualBackupDialog before the runner finished, this
              banner is the way back into the live log — clicking
              opens the JobDetailModal which automatically resumes
              the streaming view for any in-progress job. */}
          {jobsResp?.jobs
            ?.filter((j) => j.manual && isJobRunning(j))
            .map((j) => (
              <button
                key={j.id}
                type="button"
                onClick={() => setWatchingManualId(j.id)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-md border border-blue-500/40 bg-blue-500/5 hover:bg-blue-500/10 transition-colors text-left"
                title="Click to re-open the live log"
              >
                <Loader2 className="h-4 w-4 animate-spin text-blue-400 shrink-0" />
                <span className="text-sm min-w-0 flex-1 truncate">
                  Manual backup in progress — <span className="font-mono">{j.id}</span>
                </span>
                <span className="text-xs text-blue-300 shrink-0">View progress</span>
              </button>
            ))}
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
            All backups visible from this host — local <code className="font-mono">.tar.zst</code> files (PVE default dump dir, configured local target, USB mountpoints, scheduled jobs' destinations) and PBS backups from every configured datastore. Click an entry to inspect, restore or download it — downloads of PBS backups are extracted on-demand only when you request them.
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
              No backups found yet. Use <span className="font-medium">Run manual backup</span> above, configure a scheduled job, or check that the configured PBS / Borg destinations have backups.
            </div>
          ) : (
            <div className="space-y-2">
              {unifiedArchives.map((u) => {
                const localKind = u.local?.kind
                const localJobId = u.local?.job_id
                const localHost = u.local?.source_hostname
                const localPath = u.local?.path
                // Same palette as the DestinationRow accents so each
                // backend reads identically across the two cards.
                const sourceBadgeCls =
                  u.source === "pbs"
                    ? "text-purple-400 border-purple-500/20 bg-purple-500/10"
                    : u.source === "borg"
                      ? "text-fuchsia-400 border-fuchsia-500/20 bg-fuchsia-500/10"
                      : "text-blue-400 border-blue-500/20 bg-blue-500/10"
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
                        {u.remote?.encrypted && (
                          <span
                            className="uppercase tracking-wide text-[10px] px-1.5 py-0.5 rounded border border-emerald-500/40 text-emerald-400 bg-emerald-500/5 inline-flex items-center"
                            title="Encrypted backup"
                          >
                            <Lock className="h-3.5 w-3.5" />
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatMtime(u.created_at)}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <HardDrive className="h-3 w-3" />
                          {formatBytes(u.size_bytes)}
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
          // Refresh both lists — a deleted item might have been local
          // or remote (PBS/Borg). Cheap enough to revalidate both.
          mutateArchives()
          mutateRemoteArchives()
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
        onLaunched={(jobId) => {
          // Hand off straight to the live-progress modal so the
          // operator never has to chase the "View progress" banner
          // after pressing Run. Mutate jobs first so the new manual
          // entry is in cache when the watch modal opens.
          setRunningManual(false)
          mutateJobs()
          setWatchingManualId(jobId)
          // Register the job with the modal-independent background
          // poller so the Available Archives list refreshes the
          // instant the run finishes, even if the operator closes
          // the watch modal before then. Replaces the old fire-and-
          // forget 5 s mutate that used to miss slow backups.
          setPendingManualJobId(jobId)
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
        onChanged={() => {
          mutateJobs()
          mutateArchives()
          mutateRemoteArchives()
        }}
      />

      {/* Manual jobs use their own modal — no Schedule/Retention/
          Profile, no Edit/Run/Disable. Only the live log; the modal
          is closed with the dialog's own X (no extra footer). */}
      <ManualJobWatchModal
        jobId={watchingManualId}
        onClose={() => setWatchingManualId(null)}
        onChanged={() => {
          // The watch modal fires onChanged when a tracked run
          // finishes (last_result transitions from null → ok/failed).
          // Refresh jobs (status badge), local archives (new tar.zst)
          // and remote archives (Borg/PBS snapshots) so the operator
          // sees the new backup without waiting for the next tick.
          mutateJobs()
          mutateArchives()
          mutateRemoteArchives()
        }}
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
  const [viewingContents, setViewingContents] = useState(false)
  // Restore flow state:
  //   restorePreparing  — extract running (blocking spinner overlay)
  //   restoreOptions    — modal open after prepare succeeded
  //   restoreTerminal   — ScriptTerminalModal open with monitor_apply.sh
  // The extract happens BEFORE the options modal so the custom
  // checklist can be filled from `components_available` (what's
  // actually inside this backup) instead of a hardcoded list.
  const [restorePreparing, setRestorePreparing] = useState(false)
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [restoreOptions, setRestoreOptions] = useState<{
    stagingPath: string
    pathsAvailable: string[]
    rollbackPlan?: RollbackPlan
    // Cross-kernel awareness passed through to RestoreOptionsModal:
    // when direction === "bk_older" the modal shows the safe-subset
    // banner and grays out any path prefixed by anything in
    // blockedPaths. "bk_newer" and "same" pass through as no-ops.
    crossKernel?: {
      direction: "same" | "bk_older" | "bk_newer"
      backupKernel: string
      targetKernel: string
      blockedPaths: string[]
    }
    // Kernel-agnostic hydration preview (bk_older only): what the
    // restore will re-apply to the target via merge instead of
    // whole-file copy — IOMMU cmdline tokens, VFIO modules,
    // operator's GRUB keys, whitelisted vfio/nvidia files.
    hydration?: {
      applies: boolean
      actions: string[]
    }
  } | null>(null)
  const [restoreTerminal, setRestoreTerminal] = useState<{
    stagingPath: string
    mode: "full" | "custom"
    paths: string[]
    rollbackExecute?: boolean
  } | null>(null)

  // ── Keyfile-required inline import ────────────────────────────
  // When this modal opens on an encrypted PBS backup and the local
  // keyfile is missing at /usr/local/share/proxmenux/pbs-key.conf,
  // Restore / Download / View contents would all fail with
  // "missing key". We block the buttons and offer an inline Import
  // panel that reuses /api/host-backups/pbs-encryption/import with
  // source=content + escrow_mode=none — same endpoint as the setup
  // flow, so the imported keyfile lands at the canonical path and is
  // reused by every subsequent backup + restore.
  const { data: keyfileInfo, mutate: mutateKeyfileInfo } = useSWR<{
    installed: boolean
    fingerprint?: string
    path: string
  }>(
    open && remoteArc?.encrypted ? "/api/host-backups/pbs-encryption/keyfile-info" : null,
    fetcher,
  )
  const needsKeyfile = !!(remoteArc?.encrypted && keyfileInfo && !keyfileInfo.installed)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPath, setImportPath] = useState<string>("")
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)

  const runImportKeyfile = async () => {
    // Either a file upload OR a typed absolute path on this host —
    // both land at /usr/local/share/proxmenux/pbs-key.conf with
    // escrow_mode='none'. When both are provided the file wins.
    if (!importFile && !importPath.trim()) {
      setImportError("Pick a keyfile file or enter an absolute path on this host.")
      return
    }
    setImporting(true)
    setImportError(null)
    try {
      const body: Record<string, unknown> = { escrow_mode: "none" }
      if (importFile) {
        const buf = new Uint8Array(await importFile.arrayBuffer())
        let bin = ""
        for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i])
        body.source = "content"
        body.content_b64 = btoa(bin)
      } else {
        body.source = "path"
        body.keyfile_path = importPath.trim()
      }
      await fetchApi("/api/host-backups/pbs-encryption/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      await mutateKeyfileInfo()
      setImportFile(null)
      setImportPath("")
    } catch (e) {
      setImportError(e instanceof Error ? e.message : String(e))
    } finally {
      setImporting(false)
    }
  }

  const beginRestore = async () => {
    if (!archive) return
    setRestoreError(null)
    setRestorePreparing(true)
    const body: Record<string, string> = { source: archive.source }
    if (archive.source === "local") {
      if (!localArc?.path) { setRestoreError("Local archive path missing"); setRestorePreparing(false); return }
      body.path = localArc.path
    } else if (remoteArc) {
      body.repo_name = remoteArc.repo_name
      body.snapshot = remoteArc.snapshot
    } else {
      setRestoreError("Snapshot info missing")
      setRestorePreparing(false)
      return
    }
    try {
      const r: any = await fetchApi("/api/host-backups/restore/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!r?.staging_path) throw new Error("backend did not return a staging path")
      const ck = r.cross_kernel || {}
      const hyd = r.hydration || {}
      setRestoreOptions({
        stagingPath: r.staging_path,
        pathsAvailable: Array.isArray(r.paths_available) ? r.paths_available : [],
        rollbackPlan: r.rollback_plan,
        crossKernel: ck.direction
          ? {
              direction: ck.direction,
              backupKernel: ck.backup_kernel || "",
              targetKernel: ck.target_kernel || "",
              blockedPaths: Array.isArray(ck.blocked_paths) ? ck.blocked_paths : [],
            }
          : undefined,
        hydration: hyd.applies
          ? {
              applies: true,
              actions: Array.isArray(hyd.actions) ? hyd.actions : [],
            }
          : undefined,
      })
    } catch (e) {
      setRestoreError(e instanceof Error ? e.message : String(e))
    } finally {
      setRestorePreparing(false)
    }
  }
  const [deletingArchive, setDeletingArchive] = useState(false)
  const [archiveDeleteResult, setArchiveDeleteResult] = useState<string[] | null>(null)

  // Local download. Uses a single-use ticket appended to the URL +
  // `<a download>` instead of fetch+blob — the previous fetch+blob
  // approach loaded the whole archive into the browser's RAM via
  // URL.createObjectURL(), which broke around 2 GB on most browsers.
  // With the ticket-on-URL approach the browser streams the response
  // straight to disk, so archive size is bounded only by free space.
  const downloadLocalArchive = async () => {
    if (!localArc) return
    setDownloading(true)
    setError(null)
    try {
      const ticket = await fetchTerminalTicket()
      let url = getApiUrl(`/api/host-backups/archives/${encodeURIComponent(localArc.id)}/download`)
      if (ticket) url += `?ticket=${encodeURIComponent(ticket)}`
      const a = document.createElement("a")
      a.href = url
      a.download = localArc.id
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } catch (e) {
      setError(`Download failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      // The download itself runs in the browser's network stack;
      // we just initiated it. Clear the spinner immediately.
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
      // Stream the resulting .tar.zst with a ticketed URL + <a download>.
      // Same rationale as downloadLocalArchive: bypass fetch+blob to
      // avoid the ~2 GB browser-RAM limit; the browser writes
      // straight to disk.
      const ticket = await fetchTerminalTicket()
      let url = getApiUrl(`/api/host-backups/remote-archives/export/${encodeURIComponent(started.task_id)}/download`)
      if (ticket) url += `?ticket=${encodeURIComponent(ticket)}`
      const safeSnap = remoteArc.snapshot.replace(/\//g, "_")
      const a = document.createElement("a")
      a.href = url
      a.download = `${remoteArc.backend}-${remoteArc.repo_name}-${safeSnap}.tar.zst`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
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

  // Archive deletion — works for local, PBS and Borg backends.
  //   • local: DELETE /archives/<id> → removes .tar.zst + sidecar + run log.
  //   • pbs:   DELETE /remote-archives → `proxmox-backup-client snapshot forget`.
  //   • borg:  DELETE /remote-archives → `borg delete <repo>::<archive>`.
  // PBS-protected snapshots come back as 409 with the original message so
  // the operator can decide whether to lift the protection first.
  const deleteArchive = async () => {
    if (!archive) return
    setDeletingArchive(true)
    setError(null)
    try {
      let removed: string[] = []
      if (archive.source === "local" && localArc) {
        const resp = await fetchApi<{ status: string; removed: string[] }>(
          `/api/host-backups/archives/${encodeURIComponent(localArc.id)}`,
          { method: "DELETE" },
        )
        removed = resp.removed || []
      } else if (remoteArc) {
        const resp = await fetchApi<{ status: string; removed: string }>(
          `/api/host-backups/remote-archives`,
          {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              backend: remoteArc.backend,
              repo_name: remoteArc.repo_name,
              snapshot: remoteArc.snapshot,
            }),
          },
        )
        removed = resp.removed ? [resp.removed] : []
      }
      setArchiveDeleteResult(removed)
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
      <DialogContent key={archiveKey} className="max-w-3xl bg-card border-border p-0 flex flex-col gap-0 max-h-[90vh]">
        <DialogHeader className="px-4 sm:px-6 pt-4 pb-3 shrink-0 border-b border-border">
          <DialogTitle className="flex items-center gap-2 flex-wrap text-base pr-8">
            <DatabaseBackup className="h-5 w-5 text-blue-500 shrink-0" />
            <span className="font-mono text-xs sm:text-sm break-all flex-1 min-w-0">{archive?.display_id}</span>
          </DialogTitle>
        </DialogHeader>

        {/* ── Body: same shape for the 3 backends ─────────────── */}
        <ScrollArea className="flex-1 min-h-0">
          <div className="px-4 sm:px-6 py-4 space-y-4">
            {/* Backup info — uniform grid, with backend-specific
                rows mixed in only when they carry data. Backend +
                encryption badges live here (instead of the header,
                where they used to overlap the close button). */}
            <section className="rounded-md border border-border bg-background/40 p-3 space-y-1 text-xs">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Backup</div>
                <div className="flex items-center gap-1.5">
                  {archive && (
                    <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${
                      archive.source === "pbs"
                        ? "text-purple-400 border-purple-500/40 bg-purple-500/10"
                        : archive.source === "borg"
                          ? "text-fuchsia-400 border-fuchsia-500/40 bg-fuchsia-500/10"
                          : "text-blue-400 border-blue-500/40 bg-blue-500/10"
                    }`}>
                      {archive.source}
                    </Badge>
                  )}
                  {remoteArc?.encrypted && (
                    <Badge
                      variant="outline"
                      className="text-emerald-400 border-emerald-500/40 bg-emerald-500/10"
                      title="Encrypted"
                    >
                      <Lock className="h-3.5 w-3.5" />
                    </Badge>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
                {/* Time + size — present for every backend. */}
                {archive && (archive.source === "pbs" || archive.source === "borg") && remoteArc ? (
                  <>
                    <div><span className="text-muted-foreground">Backup time:</span> {formatMtime(remoteArc.backup_time)}</div>
                    {remoteArc.size_bytes > 0 && <div><span className="text-muted-foreground">Size:</span> {formatBytes(remoteArc.size_bytes)}</div>}
                    <div><span className="text-muted-foreground">Repository:</span> <code className="font-mono break-all">{remoteArc.repo_repository}</code></div>
                    <div><span className="text-muted-foreground">Repo name:</span> <code className="font-mono">{remoteArc.repo_name}</code></div>
                    <div>
                      <span className="text-muted-foreground">{remoteArc.backend === "pbs" ? "Backup group:" : "Archive name:"}</span>{" "}
                      <code className="font-mono break-all">{remoteArc.backend === "pbs" ? `${remoteArc.backup_type}/${remoteArc.backup_id}` : remoteArc.backup_id}</code>
                    </div>
                    {remoteArc.owner && <div><span className="text-muted-foreground">Owner:</span> <code className="font-mono">{remoteArc.owner}</code></div>}
                    {remoteArc.borg_id && <div className="sm:col-span-2"><span className="text-muted-foreground">Borg id:</span> <code className="font-mono text-[10px] break-all">{remoteArc.borg_id}</code></div>}
                  </>
                ) : localArc ? (
                  <>
                    <div><span className="text-muted-foreground">Created:</span> {formatMtime(localArc.mtime)}</div>
                    <div><span className="text-muted-foreground">Size:</span> {formatBytes(localArc.size_bytes)}</div>
                    <div className="sm:col-span-2"><span className="text-muted-foreground">Path:</span> <code className="font-mono break-all">{localArc.path}</code></div>
                    {localArc.job_id && <div><span className="text-muted-foreground">Job id:</span> <code className="font-mono">{localArc.job_id}</code></div>}
                    {localArc.profile && <div><span className="text-muted-foreground">Profile:</span> <code className="font-mono">{localArc.profile}</code></div>}
                    {localArc.source_hostname && <div><span className="text-muted-foreground">Source host:</span> <code className="font-mono">{localArc.source_hostname}</code></div>}
                    <div><span className="text-muted-foreground">Detected via:</span> <code className="font-mono text-[10px]">{localArc.detected_via}</code></div>
                  </>
                ) : null}
              </div>
              {/* PBS pxar files list — only PBS exposes this. */}
              {remoteArc?.files && remoteArc.files.length > 0 && (
                <div className="pt-2 mt-2 border-t border-border/50">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Files in this backup</div>
                  <ul className="space-y-0.5">
                    {remoteArc.files.map((f) => (
                      <li key={f.filename} className="font-mono text-[11px] flex items-center justify-between gap-2">
                        <span>{f.filename}</span>
                        <span className="text-muted-foreground">{formatBytes(f.size)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            {/* Run log — only Local has a co-located <stem>.log. */}
            {archive?.source === "local" && archiveLog && archiveLog.log_path && archiveLog.tail.length > 0 && (
              <section className="space-y-2">
                <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-green-500">
                  <FileText className="h-3.5 w-3.5" /> Run log
                </h4>
                <div className="rounded-md border border-border bg-background/60 p-2">
                  <pre className="text-[11px] font-mono whitespace-pre-wrap break-all max-h-48 overflow-auto text-foreground/90">
{archiveLog.tail.join("\n")}
                  </pre>
                  <div className="flex items-center justify-between mt-2 gap-2 flex-wrap">
                    <span className="text-[10px] text-muted-foreground inline-flex items-center gap-2 min-w-0">
                      <span>tail · {formatBytes(archiveLog.size)}</span>
                      <span className="font-mono break-all">{archiveLog.log_path}</span>
                    </span>
                    <Button size="sm" variant="ghost" className="h-7 text-xs shrink-0" onClick={() => setShowArchiveFullLog(true)}>
                      <FileText className="h-3.5 w-3.5 mr-1" />
                      Open full log
                    </Button>
                  </div>
                </div>
              </section>
            )}

            {/* In-flight export task feedback (Download for PBS/Borg). */}
            {exportTask && (
              <div className="text-[11px] space-y-1 px-3 py-2 rounded-md border border-border bg-background/40">
                <div className="flex items-center gap-2">
                  <Loader2 className={`h-3.5 w-3.5 ${exportTask.state === "completed" || exportTask.state === "failed" ? "" : "animate-spin"}`} />
                  <span className="font-medium capitalize">{exportTask.state}</span>
                  <span className="text-muted-foreground">— {exportTask.message}</span>
                </div>
                {exportTask.state === "failed" && exportTask.error && (
                  <div className="text-red-500 mt-1">{exportTask.error}</div>
                )}
                {exportTask.state === "completed" && exportTask.size_bytes > 0 && (
                  <div className="text-emerald-400">Packed size: {formatBytes(exportTask.size_bytes)}</div>
                )}
              </div>
            )}

            {error && (
              <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
                {error}
              </div>
            )}

            {/* Encrypted-backup gate: no local keyfile → block the
                three actions until the operator imports the key. The
                import lands at the canonical path with escrow_mode=
                'none', so subsequent runs reuse it silently. */}
            {needsKeyfile && (
              <section className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 space-y-2 text-xs">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
                  <div className="flex-1 space-y-1">
                    <div className="font-semibold text-amber-300">Encrypted backup — keyfile required</div>
                    <div className="text-muted-foreground leading-relaxed">
                      This snapshot is encrypted but no local keyfile is installed at
                      {" "}<code className="font-mono text-[10.5px]">/usr/local/share/proxmenux/pbs-key.conf</code>.
                      Import the keyfile that was used at backup time to continue.
                    </div>
                  </div>
                </div>
                <div className="space-y-1.5 pt-1 border-t border-amber-500/30">
                  <Label htmlFor="keyfileImport" className="text-[11px] font-medium">Upload from your machine</Label>
                  <Input
                    id="keyfileImport"
                    type="file"
                    accept=".conf,.key,application/json,text/plain"
                    onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                    disabled={importing || !!importPath.trim()}
                    className="h-8 text-[11px]"
                  />
                </div>
                <div className="text-[10px] text-center text-muted-foreground">— or —</div>
                <div className="space-y-1.5">
                  <Label htmlFor="keyfileImportPath" className="text-[11px] font-medium">Absolute path on this host</Label>
                  <Input
                    id="keyfileImportPath"
                    type="text"
                    value={importPath}
                    onChange={(e) => setImportPath(e.target.value)}
                    disabled={importing || !!importFile}
                    placeholder="/usr/local/share/proxmenux/pbs-key.conf"
                    className="h-8 text-[11px] font-mono"
                  />
                </div>
                {importError && (
                  <div className="text-red-500 px-2 py-1.5 rounded border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
                    {importError}
                  </div>
                )}
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={runImportKeyfile}
                    disabled={importing || (!importFile && !importPath.trim())}
                    className="bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30"
                    variant="outline"
                  >
                    {importing ? (
                      <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    ) : (
                      <Lock className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    Import keyfile
                  </Button>
                </div>
              </section>
            )}
          </div>
        </ScrollArea>

        {/* ── Footer: same 4 buttons for the 3 backends ─────────
            Restore (green) · Download (blue) · View contents (blue)
            on the left · Delete (red) on the right. On mobile only
            Restore keeps its label — the others are icon-only to fit
            the narrower viewport without wrapping. */}
        <div className="px-4 sm:px-6 py-3 border-t border-border shrink-0 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              onClick={beginRestore}
              disabled={restorePreparing || needsKeyfile}
              className="bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
              title={needsKeyfile ? "Import the encryption keyfile above to enable Restore" : "Restore this snapshot to the current host (Complete or Custom by paths)"}
            >
              {restorePreparing ? (
                <Loader2 className="h-4 w-4 sm:mr-2 animate-spin" />
              ) : (
                <DatabaseBackup className="h-4 w-4 sm:mr-2" />
              )}
              <span>Restore</span>
            </Button>
            <Button
              onClick={downloadArchive}
              disabled={downloading || needsKeyfile}
              className="bg-blue-500/10 border border-blue-500/40 text-blue-400 hover:bg-blue-500/20 hover:text-blue-300 disabled:opacity-50"
              variant="outline"
              title={needsKeyfile ? "Import the encryption keyfile above to enable Download" : "Download the snapshot as a .tar.zst"}
            >
              {downloading ? (
                <Loader2 className="h-4 w-4 sm:mr-2 animate-spin" />
              ) : (
                <Download className="h-4 w-4 sm:mr-2" />
              )}
              <span className="hidden sm:inline">Download</span>
            </Button>
            <Button
              onClick={() => setViewingContents(true)}
              disabled={needsKeyfile}
              className="bg-blue-500/10 border border-blue-500/40 text-blue-400 hover:bg-blue-500/20 hover:text-blue-300 disabled:opacity-50"
              variant="outline"
              title={needsKeyfile ? "Import the encryption keyfile above to enable View contents" : "Extract + show manifest, plan, files, metadata as HTML"}
            >
              <Eye className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">View contents</span>
            </Button>
          </div>
          <Button
            onClick={() => setShowDeleteArchiveConfirm(true)}
            disabled={deletingArchive}
            className="bg-red-500/10 border border-red-500/40 text-red-400 hover:bg-red-500/20 hover:text-red-300"
            variant="outline"
            title={
              archive?.source === "local"
                ? "Permanently delete this archive (.tar.zst + sidecar + log)"
                : archive?.source === "pbs"
                ? "Permanently forget this PBS snapshot (proxmox-backup-client snapshot forget)"
                : "Permanently delete this Borg archive (borg delete)"
            }
          >
            {deletingArchive ? (
              <Loader2 className="h-4 w-4 sm:mr-2 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4 sm:mr-2" />
            )}
            <span className="hidden sm:inline">Delete</span>
          </Button>
        </div>
      </DialogContent>
    </Dialog>

    {/* ── View contents — extract + parse the snapshot, show HTML ──── */}
    <ArchiveContentsModal
      open={viewingContents}
      onClose={() => setViewingContents(false)}
      source={(archive?.source as "pbs" | "borg" | "local" | null) ?? null}
      repo_name={remoteArc?.repo_name}
      snapshot={remoteArc?.snapshot}
      path={localArc?.path}
      display_id={archive?.display_id}
    />

    {/* ── Restore error toast (prepare failed) ─────────────────── */}
    {restoreError && (
      <Dialog open={true} onOpenChange={() => setRestoreError(null)}>
        <DialogContent className="max-w-md bg-card border-border">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-500" />
              Restore preparation failed
            </DialogTitle>
            <DialogDescription className="text-xs text-red-400 break-all">
              {restoreError}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end">
            <Button variant="ghost" onClick={() => setRestoreError(null)}>Close</Button>
          </div>
        </DialogContent>
      </Dialog>
    )}

    {/* ── Restore options modal: opens only AFTER the prepare step,
        so the Custom checklist already knows what's inside. ──── */}
    <RestoreOptionsModal
      open={restoreOptions !== null}
      stagingPath={restoreOptions?.stagingPath ?? ""}
      pathsAvailable={restoreOptions?.pathsAvailable ?? []}
      rollbackPlan={restoreOptions?.rollbackPlan}
      crossKernel={restoreOptions?.crossKernel}
      hydration={restoreOptions?.hydration}
      display_id={archive?.display_id}
      onClose={() => {
        const sp = restoreOptions?.stagingPath
        setRestoreOptions(null)
        if (sp) {
          fetchApi("/api/host-backups/restore/cleanup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ staging_path: sp }),
          }).catch(() => undefined)
        }
      }}
      onLaunch={(mode, paths, rollbackExecute) => {
        if (!restoreOptions) return
        const sp = restoreOptions.stagingPath
        setRestoreOptions(null)
        setRestoreTerminal({ stagingPath: sp, mode, paths, rollbackExecute })
      }}
    />

    {/* ── Restore terminal — uses the canonical ScriptTerminalModal
        (the same component Hardware/Security/Settings use to run
        their scripts). Stable `key` per stagingPath so each restore
        session is a fresh terminal. */}
    {restoreTerminal && (
      <ScriptTerminalModal
        key={restoreTerminal.stagingPath}
        open={true}
        onClose={() => {
          const sp = restoreTerminal.stagingPath
          fetchApi("/api/host-backups/restore/cleanup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ staging_path: sp }),
          }).catch(() => undefined)
          setRestoreTerminal(null)
        }}
        // Auto-dismiss when the script's PTY closes (i.e. the bash
        // wrapper exited cleanly — the operator pressed Enter at the
        // "Press Enter to close" prompt). Without this the operator
        // would have to click Close manually after each restore.
        onComplete={() => {
          const sp = restoreTerminal.stagingPath
          fetchApi("/api/host-backups/restore/cleanup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ staging_path: sp }),
          }).catch(() => undefined)
          setRestoreTerminal(null)
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/backup_restore/restore/monitor_apply.sh"
        scriptName="monitor_apply"
        title={`Restore — ${restoreTerminal.mode === "full" ? "Complete" : "Custom by paths"}`}
        description={
          restoreTerminal.mode === "custom"
            ? `${restoreTerminal.paths.length} path(s) selected`
            : "Complete restore — applies the whole backup"
        }
        params={{
          EXECUTION_MODE: "web",
          STAGING: restoreTerminal.stagingPath,
          MODE: restoreTerminal.mode,
          ...(restoreTerminal.mode === "custom" && restoreTerminal.paths.length > 0
            ? { PATHS: restoreTerminal.paths.join(",") }
            : {}),
          ...(restoreTerminal.rollbackExecute ? { ROLLBACK_EXECUTE: "1" } : {}),
        }}
      />
    )}

    {/* ── Confirm archive deletion ───────────────────────────── */}
    <Dialog open={showDeleteArchiveConfirm} onOpenChange={setShowDeleteArchiveConfirm}>
      <DialogContent className="max-w-md bg-card border-border">
        <DialogHeader>
          <DialogTitle className="text-base flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-red-500" />
            Delete {backendLabel} backup
          </DialogTitle>
          <DialogDescription className="text-xs">
            {archive?.source === "local"
              ? "Removes the archive, its sidecar JSON and the matching run log. The action is permanent — restore needs an off-host copy."
              : archive?.source === "pbs"
              ? `Forgets this snapshot from the PBS repository "${remoteArc?.repo_name ?? ""}". The action is permanent — PBS GC may reclaim the underlying chunks at the next garbage-collection run.`
              : `Deletes this archive from the Borg repository "${remoteArc?.repo_name ?? ""}". The action is permanent — Borg compacts the freed space at the next prune.`}
          </DialogDescription>
        </DialogHeader>
        <div className="text-sm font-mono px-3 py-2 rounded-md border border-border bg-background/40 break-all">
          {archive?.source === "local" ? localArc?.id : remoteArc?.snapshot}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setShowDeleteArchiveConfirm(false)} disabled={deletingArchive}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={deleteArchive} disabled={deletingArchive}>
            {deletingArchive ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4 mr-2" />
            )}
            Delete
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

// All Destination shapes carry `jobs_using`: list of job_ids that
// currently depend on the destination. Surfaced in the Delete-
// destination confirm flow so the operator sees the cascade impact
// before agreeing.

interface PbsRepo {
  name: string
  repository: string
  fingerprint: string | null
  source: "proxmox" | "manual"
  jobs_using?: string[]
}

interface BorgRepo {
  name: string
  repository: string
  ssh_key_path?: string
  // Encryption + saved-passphrase metadata. Newer backends ship these;
  // older deployments without the fields default to "repokey" (the
  // shell installer's historical default) and unknown-passphrase.
  encrypt_mode?: "none" | "repokey" | "keyfile" | "authenticated"
  has_passphrase?: boolean
  jobs_using?: string[]
}

interface LocalTargetEntry {
  path: string
  source: "default" | "custom"
  removable: boolean
  jobs_using?: string[]
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
  // Legacy — kept for backend responses that only track the on/off
  // toggle. Newer builds also send pbs_encrypt_mode ("none" | "new"
  // | "existing"); loadFromJobDetail prefers that when present.
  pbs_encrypt: boolean
  pbs_encrypt_mode?: "none" | "new" | "existing"
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
  // Client-side PBS encryption mode. Three modes match the shell wizard:
  //   - "none"     — plain backup, no --keyfile
  //   - "new"      — backend generates a fresh per-host keyfile (default)
  //   - "existing" — operator uploads their own keyfile (shared across
  //                  hosts). The upload happens via a dedicated endpoint
  //                  BEFORE the job create call — see handleCreate below.
  const [pbsEncryptMode, setPbsEncryptMode] = useState<"none" | "new" | "existing">("none")
  // File picked in the "existing" mode. Kept in a ref-like state so a
  // stale reference doesn't linger across modal opens.
  const [pbsImportFile, setPbsImportFile] = useState<File | null>(null)
  // Absolute-path alternative to the file upload — mirrors the shell
  // wizard's `_hb_pbs_import_dialog` when there is no PVE .enc match.
  const [pbsImportPath, setPbsImportPath] = useState<string>("")
  const [pbsImportBusy, setPbsImportBusy] = useState<boolean>(false)
  // Legacy alias for the many recovery / gating checks below — a truthy
  // value means "the operator wants an encrypted backup" regardless of
  // whether that keyfile came from a fresh generate or from an import.
  const pbsEncrypt = pbsEncryptMode !== "none"
  // Optional recovery passphrase. When set, the backend encrypts the
  // keyfile with openssl and the runner uploads that blob to PBS with
  // every backup so the keyfile can be rebuilt on a fresh host with
  // only the passphrase. Mirrors hb_pbs_setup_recovery from the shell.
  const [pbsRecoveryPass, setPbsRecoveryPass] = useState<string>("")
  const [pbsRecoveryPass2, setPbsRecoveryPass2] = useState<string>("")
  // Operator opted to replace an already-configured recovery escrow.
  // Default behavior matches the shell: don't prompt for the
  // passphrase if one is already saved — only show the inputs when
  // there's no escrow yet OR the operator explicitly asks to change.
  const [pbsRecoveryChange, setPbsRecoveryChange] = useState<boolean>(false)
  // Binary "upload key to PBS?" toggle. `true` maps to escrow_mode='full'
  // (passphrase required, envelope uploaded on every backup); `false`
  // maps to escrow_mode='none' (keyfile stays local, operator handles
  // the offsite copy). Defaults to 'No' — the keyfile is always
  // downloadable from the Monitor, so the operator can grab it and
  // save it offsite themselves without leaving a passphrase-wrapped
  // copy on the PBS server.
  const [pbsUploadToPbs, setPbsUploadToPbs] = useState<boolean>(false)
  // Whether the host already has an escrow blob configured. When
  // present, the passphrase input becomes optional ("leave blank to
  // keep saved"). Refreshed after a successful setup call.
  const { data: pbsRecoveryStatus, mutate: mutatePbsRecovery } = useSWR<{
    has_keyfile: boolean; has_recovery: boolean; has_keyfile_passphrase?: boolean; escrow_mode?: "none" | "local" | "full"
  }>(
    open && backend === "pbs" ? "/api/host-backups/pbs-recovery/status" : null,
    fetcher,
  )
  // Auto-discover a PVE-managed keyfile for the currently selected
  // PBS repository. When one is found, the "Use an existing keyfile"
  // radio uses it silently (matches the shell wizard's PVE auto-detect
  // path — the operator doesn't have to upload the same file twice).
  const { data: pbsPveDiscover } = useSWR<{
    entries: Array<{ name: string; server: string; datastore: string; path: string; matches_repository: boolean }>
  }>(
    open && backend === "pbs" && pbsRepository && !pbsRecoveryStatus?.has_keyfile
      ? `/api/host-backups/pbs-encryption/discover-pve-keyfiles?repository=${encodeURIComponent(pbsRepository)}`
      : null,
    fetcher,
  )
  const pbsPveMatch = pbsPveDiscover?.entries?.find((e) => e.matches_repository)
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
    // Prefer the new pbs_encrypt_mode string when the backend sends it;
    // fall back to the legacy bool for older `.env` layouts that only
    // remember the on/off toggle.
    const jd = jobDetail as unknown as { pbs_encrypt_mode?: string; pbs_encrypt?: boolean }
    if (jd.pbs_encrypt_mode === "new" || jd.pbs_encrypt_mode === "existing" || jd.pbs_encrypt_mode === "none") {
      setPbsEncryptMode(jd.pbs_encrypt_mode)
    } else {
      setPbsEncryptMode(jd.pbs_encrypt ? "new" : "none")
    }
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
      setPbsEncryptMode("none")
      setPbsImportFile(null)
      setPbsImportPath("")
      setPbsImportBusy(false)
      setPbsRecoveryPass("")
      setPbsRecoveryPass2("")
      setPbsRecoveryChange(false)
      setPbsUploadToPbs(false)
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
        : /* borg */ !!borgRepoSelected

  // PBS encryption gate — choosing "Encrypt" makes the recovery
  // passphrase mandatory. The button stays disabled until a matching
  // passphrase pair is entered (or an already-saved escrow is reused).
  // There is no opt-out: encrypting without recovery would leave the
  // keyfile only on this host, and a reinstall would render every
  // encrypted backup unrecoverable.
  // Passphrase requirement only kicks in when: encryption is on AND
  // there's no keyfile installed yet (fresh setup) AND the operator
  // opted to upload the key to PBS. Every other case (reuse existing
  // keyfile, or "no upload" mode) doesn't need a passphrase.
  const pbsRecoveryOk = !(backend === "pbs" && pbsEncrypt) ||
    pbsRecoveryStatus?.has_keyfile ||
    !pbsUploadToPbs ||
    (pbsRecoveryPass !== "" && pbsRecoveryPass === pbsRecoveryPass2)

  const canSubmit =
    canAdvanceFrom1 && canAdvanceFrom2 && canAdvanceFrom3 && canAdvanceFrom4 && backendValid && pbsRecoveryOk

  async function handleCreate() {
    if (!canSubmit) return
    if (mode === "attach" && !selectedPveJob) return
    setSubmitting(true)
    setError(null)
    // Encryption submit paths:
    //   • enabled + keyfile already on disk → mode = "existing", no upload
    //     (backend reuses the canonical file at _PBS_KEYFILE_PATH).
    //   • enabled + no keyfile + Generate    → mode = "new", backend creates it.
    //   • enabled + no keyfile + Import      → upload the file first, then
    //     mode = "existing" so the backend uses the freshly-installed key.
    //
    // Only the third branch actually needs to POST to
    // /api/host-backups/pbs-encryption/import — the second is handled
    // server-side, and the first has nothing to upload.
    // Unified encryption setup: one atomic call to /pbs-encryption/import
    // covers keyfile install + escrow setup, whether the operator picked
    // "generate a new keyfile" or "import an existing one", and whether
    // they opted to upload the envelope to PBS or keep the key local.
    const needsInstall =
      backend === "pbs" &&
      pbsEncrypt &&
      !pbsRecoveryStatus?.has_keyfile
    if (needsInstall) {
      // Existing + no PVE auto-detect requires either a file upload
      // or a typed absolute path — mirrors the shell wizard.
      // Existing + PVE auto-detect uses source=pve-storage.
      if (pbsEncryptMode === "existing" && !pbsPveMatch && !pbsImportFile && !pbsImportPath.trim()) {
        setError("Pick a keyfile file or enter an absolute path on this host.")
        setSubmitting(false)
        return
      }
      if (pbsUploadToPbs && pbsRecoveryPass !== pbsRecoveryPass2) {
        setError("Recovery passphrases don't match.")
        setSubmitting(false)
        return
      }
      setPbsImportBusy(true)
      try {
        // Source picker mirrors the shell wizard's dispatch:
        //   generate       → new keyfile via proxmox-backup-client
        //   pve-storage    → reuse /etc/pve/priv/storage/<name>.enc
        //   content        → upload a file the operator picked
        //   path           → read a file at an absolute path
        let source: "generate" | "pve-storage" | "content" | "path"
        if (pbsEncryptMode === "new") source = "generate"
        else if (pbsPveMatch) source = "pve-storage"
        else if (pbsImportFile) source = "content"
        else source = "path"
        const body: Record<string, unknown> = {
          source,
          escrow_mode: pbsUploadToPbs ? "full" : "none",
        }
        if (pbsUploadToPbs) body.escrow_passphrase = pbsRecoveryPass
        if (source === "pve-storage") {
          body.pve_storage_name = pbsPveMatch!.name
        } else if (source === "content") {
          const buf = new Uint8Array(await pbsImportFile!.arrayBuffer())
          let bin = ""
          for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i])
          body.content_b64 = btoa(bin)
        } else if (source === "path") {
          body.keyfile_path = pbsImportPath.trim()
        }
        await fetchApi("/api/host-backups/pbs-encryption/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
        mutatePbsRecovery()
      } catch (e) {
        const err = e as Error & { body?: { tool_output?: string; tool_exit_code?: number } }
        const detail = err.body?.tool_output
          ? `${err.message}\n\nproxmox-backup-client output:\n${err.body.tool_output}`
          : err.message
        setError(`Encryption setup failed: ${detail || String(e)}`)
        setPbsImportBusy(false)
        setSubmitting(false)
        return
      }
      setPbsImportBusy(false)
    }
    // NOTE: recovery escrow is now bundled into the /pbs-encryption/import
    // call above. No separate /pbs-recovery/setup pass is needed.
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
        body.pbs_encrypt_mode = pbsEncryptMode
      } else if (backend === "local") {
        if (localDestDir.trim()) body.local_dest_dir = localDestDir.trim()
      } else if (backend === "borg") {
        // Passphrase + encrypt_mode are inherited from the destination
        // (the runner reads borg-pass-<name>.txt + the 4th field of
        // borg-targets.txt). Only send overrides when the operator
        // really typed a new one in an edit flow.
        body.borg_repo = borgRepoSelected
        if (isEdit && borgPassphrase) body.borg_passphrase = borgPassphrase
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
                          <SelectTrigger className="flex-1 min-w-0">
                            {/* Manual render: SelectValue's default mode
                                duplicates the item children and cuts
                                them in the middle on mobile. We render
                                "name — repository" ourselves with a
                                proper trailing ellipsis. */}
                            {(() => {
                              const sel = destResp.pbs.find((r) => r.repository === pbsRepository)
                              if (!sel) {
                                return <span className="truncate text-muted-foreground">Pick a PBS repository</span>
                              }
                              return (
                                <span className="truncate font-mono text-left">
                                  {sel.name}
                                  <span className="text-muted-foreground"> — {sel.repository}</span>
                                </span>
                              )
                            })()}
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
                  {/* PBS client-side encryption — mirrors the shell wizard:
                      step 1 is a plain yes/no, step 2 only appears when
                      no keyfile is installed yet. Once a keyfile exists,
                      every future encrypted job silently reuses it. */}
                  <div className="pt-2 border-t border-border space-y-3">
                    <label className="flex items-start gap-2 cursor-pointer">
                      <Checkbox
                        checked={pbsEncrypt}
                        onCheckedChange={(v) => {
                          const checked = !!v
                          if (!checked) {
                            setPbsEncryptMode("none")
                          } else {
                            // Yes → if the host already has a keyfile, submit
                            // "existing" (reuse it silently). If not, default
                            // to "new" (Generate) — the operator can flip to
                            // "existing" (Import) via the radio below.
                            setPbsEncryptMode(pbsRecoveryStatus?.has_keyfile ? "existing" : "new")
                          }
                        }}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        <div className="inline-flex items-center gap-1.5 text-sm">
                          <Lock className="h-3.5 w-3.5 text-emerald-400" />
                          Encrypt backups (client-side keyfile)
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          Adds <code className="font-mono">--keyfile</code> to <code className="font-mono">proxmox-backup-client backup</code>. Encryption happens before upload so chunks land on PBS already ciphered. The keyfile is installed at <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code> (chmod 0600) and reused by every encrypted PBS job on this host.
                        </p>
                      </div>
                    </label>


                    {pbsEncrypt && !pbsRecoveryStatus?.has_keyfile && (
                      <div className="space-y-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
                        <div className="text-[11px] font-medium">
                          No encryption key is stored on this host. Choose how to set one up:
                        </div>
                        <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                          <input
                            type="radio"
                            name="pbsEncryptSetupCreate"
                            checked={pbsEncryptMode === "new"}
                            onChange={() => setPbsEncryptMode("new")}
                            className="mt-1"
                          />
                          <div className="flex-1">
                            <div className="font-medium">Generate a new keyfile (per host — safest isolation)</div>
                            <div className="text-muted-foreground">Creates a fresh keyfile at <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code>. Backup up the recovery passphrase (below) to survive host loss.</div>
                          </div>
                        </label>
                        <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                          <input
                            type="radio"
                            name="pbsEncryptSetupCreate"
                            checked={pbsEncryptMode === "existing"}
                            onChange={() => setPbsEncryptMode("existing")}
                            className="mt-1"
                          />
                          <div className="flex-1">
                            <div className="font-medium">Import an existing keyfile (shared across hosts)</div>
                            <div className="text-muted-foreground">Use the same keyfile another host already has — enables cross-host restore of encrypted backups.</div>
                          </div>
                        </label>
                        {pbsEncryptMode === "existing" && pbsPveMatch && (
                          <div className="pt-1 rounded-md border border-emerald-500/40 bg-emerald-500/5 p-2.5 text-[11px] space-y-1">
                            <div className="flex items-start gap-1.5">
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 shrink-0" />
                              <div className="flex-1">
                                <div className="font-medium text-foreground">Auto-detected from PVE storage &apos;{pbsPveMatch.name}&apos;</div>
                                <div className="text-muted-foreground mt-0.5">
                                  Existing key at <code className="font-mono text-[10.5px]">{pbsPveMatch.path}</code>
                                </div>
                                <div className="text-muted-foreground mt-0.5">Will be copied to the ProxMenux state directory. No file upload needed.</div>
                              </div>
                            </div>
                          </div>
                        )}
                        {pbsEncryptMode === "existing" && !pbsPveMatch && (
                          <div className="space-y-2 pt-1">
                            <div className="space-y-1.5">
                              <Label htmlFor="pbsImportFile" className="text-[11px] font-medium">
                                Upload from your machine
                              </Label>
                              <Input
                                id="pbsImportFile"
                                type="file"
                                accept=".conf,.key,application/json,text/plain"
                                onChange={(e) => setPbsImportFile(e.target.files?.[0] ?? null)}
                                disabled={pbsImportBusy || !!pbsImportPath.trim()}
                                className="h-8 text-[11px]"
                              />
                            </div>
                            <div className="text-[10px] text-center text-muted-foreground">— or —</div>
                            <div className="space-y-1.5">
                              <Label htmlFor="pbsImportPath" className="text-[11px] font-medium">
                                Absolute path on this host
                              </Label>
                              <Input
                                id="pbsImportPath"
                                type="text"
                                value={pbsImportPath}
                                onChange={(e) => setPbsImportPath(e.target.value)}
                                disabled={pbsImportBusy || !!pbsImportFile}
                                placeholder="/usr/local/share/proxmenux/pbs-key.conf"
                                className="h-8 text-[11px] font-mono"
                              />
                              <p className="text-[10px] text-muted-foreground">
                                Either option works. The file lands at <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code> and every subsequent encrypted backup reuses it.
                              </p>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {pbsEncrypt && (
                      <div className="pl-7 space-y-3 rounded-md border border-blue-500/30 bg-blue-500/5 p-3">
                        {pbsRecoveryStatus?.has_keyfile && !pbsRecoveryChange && (
                          <div className="flex items-start gap-2 text-[11px]">
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 shrink-0" />
                            <div className="flex-1">
                              <div className="text-foreground">Keyfile installed. Backups reuse it silently.</div>
                              <div className="text-muted-foreground mt-0.5">The current PBS-upload setting stays in effect.</div>
                            </div>
                            <button
                              type="button"
                              onClick={() => setPbsRecoveryChange(true)}
                              className="text-blue-400 hover:text-blue-300 underline underline-offset-2 shrink-0"
                            >
                              Change
                            </button>
                          </div>
                        )}
                        {pbsRecoveryStatus?.has_keyfile && pbsRecoveryChange && (
                          <>
                            <KeyfileActionsBar
                              mutateStatus={mutatePbsRecovery}
                              escrowMode={pbsRecoveryStatus?.escrow_mode}
                            />
                            <button
                              type="button"
                              onClick={() => setPbsRecoveryChange(false)}
                              className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2"
                            >
                              Done — hide keyfile options
                            </button>
                          </>
                        )}
                        {!pbsRecoveryStatus?.has_keyfile && (
                          <>
                            <div>
                              <div className="text-[11px] font-medium text-foreground mb-2">Upload key to PBS?</div>
                              <div className="grid gap-1.5">
                                <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                                  <input
                                    type="radio"
                                    name="pbsUploadToPbsCreate"
                                    checked={!pbsUploadToPbs}
                                    onChange={() => setPbsUploadToPbs(false)}
                                    className="mt-1"
                                  />
                                  <div className="flex-1">
                                    <div className="font-medium">No, keep local only</div>
                                    <div className="text-muted-foreground">Keyfile stays only at <code className="font-mono text-[10.5px]">/usr/local/share/proxmenux/pbs-key.conf</code>. You are responsible for keeping an offsite copy — losing it makes every encrypted backup unreadable.</div>
                                  </div>
                                </label>
                                <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                                  <input
                                    type="radio"
                                    name="pbsUploadToPbsCreate"
                                    checked={pbsUploadToPbs}
                                    onChange={() => setPbsUploadToPbs(true)}
                                    className="mt-1"
                                  />
                                  <div className="flex-1">
                                    <div className="font-medium">Yes, upload</div>
                                    <div className="text-muted-foreground">Set a recovery passphrase now. ProxMenux uploads a passphrase-wrapped copy of the keyfile to PBS with every backup so you can recover it on a reinstalled host with just the passphrase.</div>
                                  </div>
                                </label>
                              </div>
                            </div>
                            {pbsUploadToPbs ? (
                              <div className="space-y-2 pt-1 border-t border-blue-500/20">
                                <div>
                                  <Label htmlFor="pbsRecPass" className="text-[11px]">Recovery passphrase</Label>
                                  <Input
                                    id="pbsRecPass"
                                    type="password"
                                    value={pbsRecoveryPass}
                                    onChange={(e) => setPbsRecoveryPass(e.target.value)}
                                    placeholder="Long random string — write it down somewhere safe"
                                    className="font-mono mt-1 h-8 text-xs"
                                  />
                                </div>
                                <div>
                                  <Label htmlFor="pbsRecPass2" className="text-[11px]">Confirm passphrase</Label>
                                  <Input
                                    id="pbsRecPass2"
                                    type="password"
                                    value={pbsRecoveryPass2}
                                    onChange={(e) => setPbsRecoveryPass2(e.target.value)}
                                    placeholder="Type it again"
                                    className="font-mono mt-1 h-8 text-xs"
                                  />
                                  {pbsRecoveryPass && pbsRecoveryPass2 && pbsRecoveryPass !== pbsRecoveryPass2 && (
                                    <p className="text-[11px] text-red-400 mt-1">Passphrases don't match.</p>
                                  )}
                                </div>
                              </div>
                            ) : (
                              <div className="pt-1 border-t border-blue-500/20 text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-3 py-2 leading-relaxed space-y-1">
                                <div className="font-semibold">Keep an offsite copy of the keyfile.</div>
                                <div>After the job is created, copy <code className="font-mono text-[10.5px] bg-amber-500/20 rounded px-1">/usr/local/share/proxmenux/pbs-key.conf</code> to an external medium (USB, password manager, another host).</div>
                                <div>Without that copy, losing this host makes every encrypted backup on PBS unreadable.</div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
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
                      {(destResp?.local?.entries?.length ?? 0) > 0 && (
                        <div className="flex items-center gap-2">
                          <Select
                            value={localDestDir || (destResp?.local?.effective ?? "")}
                            onValueChange={(v) => setLocalDestDir(v)}
                          >
                            <SelectTrigger className="flex-1">
                              <SelectValue placeholder="Pick a configured local destination" />
                            </SelectTrigger>
                            <SelectContent>
                              {destResp?.local?.entries?.map((e) => (
                                <SelectItem key={e.path} value={e.path}>
                                  <span className="font-mono">{e.path}</span>
                                  {e.source === "default" && (
                                    <span className="text-muted-foreground ml-2 text-[10px] uppercase">default</span>
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
                            onClick={() => setAddingDestType("local")}
                            title="Save another local destination"
                          >
                            <Plus className="h-3.5 w-3.5 mr-1" />
                            Add another
                          </Button>
                        </div>
                      )}
                      <Input
                        id="localDest"
                        value={localDestDir}
                        onChange={(e) => setLocalDestDir(e.target.value)}
                        placeholder={destResp?.local?.effective || "/var/lib/vz/dump"}
                        className="font-mono"
                      />
                      <p className="text-xs text-muted-foreground">
                        Pick a configured destination above, or type a custom directory path. Empty input falls back to <span className="font-mono">{destResp?.local?.effective || "/var/lib/vz/dump"}</span>.
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
                          <SelectTrigger className="flex-1 min-w-0">
                            {(() => {
                              const sel = destResp.borg.find((r) => r.repository === borgRepoSelected)
                              if (!sel) {
                                return <span className="truncate text-muted-foreground">Pick a Borg repository</span>
                              }
                              return (
                                <span className="truncate font-mono text-left">
                                  {sel.name}
                                  <span className="text-muted-foreground"> — {sel.repository}</span>
                                </span>
                              )
                            })()}
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
                  {/* Encryption + passphrase aren't asked here — they
                      live on the borg destination. The runner reads
                      the saved sidecar at run time. */}
                  {(() => {
                    const dest = destResp?.borg?.find((r) => r.repository === borgRepoSelected)
                    if (!dest) return null
                    const mode = dest.encrypt_mode || "repokey"
                    return (
                      <p className="text-[11px] text-muted-foreground">
                        Encryption + passphrase are taken from the destination ({mode === "none" ? "no encryption" : mode}). Edit the destination if you need to change them.
                      </p>
                    )
                  })()}
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
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
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
                className="bg-blue-600 hover:bg-blue-700 text-white"
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
  // The job_id of the just-launched manual run. The caller uses it to
  // transition straight into the live-progress modal so the operator
  // never has to chase a banner after pressing Run.
  onLaunched: (jobId: string) => void
}) {
  const [step, setStep] = useState<1 | 2>(1)
  const [backend, setBackend] = useState<"pbs" | "local" | "borg">("local")
  const [profileMode, setProfileMode] = useState<"default" | "custom">("default")
  const [customPaths, setCustomPaths] = useState<Set<string>>(new Set())

  const [pbsRepository, setPbsRepository] = useState<string>("")
  const [pbsBackupId, setPbsBackupId] = useState<string>("")
  // Encryption mode. See CreateJobDialog above for the full comment
  // block — the three modes and the import flow are identical here.
  const [pbsEncryptMode, setPbsEncryptMode] = useState<"none" | "new" | "existing">("none")
  const [pbsImportFile, setPbsImportFile] = useState<File | null>(null)
  // Absolute-path alternative to the file upload — mirrors the shell
  // wizard's `_hb_pbs_import_dialog` when there is no PVE .enc match.
  const [pbsImportPath, setPbsImportPath] = useState<string>("")
  const [pbsImportBusy, setPbsImportBusy] = useState<boolean>(false)
  const pbsEncrypt = pbsEncryptMode !== "none"
  const [pbsRecoveryPass, setPbsRecoveryPass] = useState<string>("")
  const [pbsRecoveryPass2, setPbsRecoveryPass2] = useState<string>("")
  // Operator opted to replace an already-configured recovery escrow.
  // Default behavior matches the shell: don't prompt for the
  // passphrase if one is already saved — only show the inputs when
  // there's no escrow yet OR the operator explicitly asks to change.
  const [pbsRecoveryChange, setPbsRecoveryChange] = useState<boolean>(false)
  // Binary "upload key to PBS?" toggle. `true` maps to escrow_mode='full'
  // (passphrase required, envelope uploaded on every backup); `false`
  // maps to escrow_mode='none' (keyfile stays local, operator handles
  // the offsite copy). Defaults to 'No' — the keyfile is always
  // downloadable from the Monitor, so the operator can grab it and
  // save it offsite themselves without leaving a passphrase-wrapped
  // copy on the PBS server.
  const [pbsUploadToPbs, setPbsUploadToPbs] = useState<boolean>(false)
  // Whether the host already has an escrow blob configured. When
  // present, the passphrase input becomes optional ("leave blank to
  // keep saved"). Refreshed after a successful setup call.
  const { data: pbsRecoveryStatus, mutate: mutatePbsRecovery } = useSWR<{
    has_keyfile: boolean; has_recovery: boolean; has_keyfile_passphrase?: boolean; escrow_mode?: "none" | "local" | "full"
  }>(
    open && backend === "pbs" ? "/api/host-backups/pbs-recovery/status" : null,
    fetcher,
  )
  // Auto-discover a PVE-managed keyfile for the currently selected
  // PBS repository. When one is found, the "Use an existing keyfile"
  // radio uses it silently (matches the shell wizard's PVE auto-detect
  // path — the operator doesn't have to upload the same file twice).
  const { data: pbsPveDiscover } = useSWR<{
    entries: Array<{ name: string; server: string; datastore: string; path: string; matches_repository: boolean }>
  }>(
    open && backend === "pbs" && pbsRepository && !pbsRecoveryStatus?.has_keyfile
      ? `/api/host-backups/pbs-encryption/discover-pve-keyfiles?repository=${encodeURIComponent(pbsRepository)}`
      : null,
    fetcher,
  )
  const pbsPveMatch = pbsPveDiscover?.entries?.find((e) => e.matches_repository)
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
      setPbsEncryptMode("none")
      setPbsImportFile(null)
      setPbsImportPath("")
      setPbsImportBusy(false)
      setPbsRecoveryPass("")
      setPbsRecoveryPass2("")
      setPbsRecoveryChange(false)
      setPbsUploadToPbs(false)
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
        // Borg destination carries its own passphrase + encryption.
        // No need to gate on local state — the wizard no longer asks.
        : !!borgRepoSelected
  // Recovery gate for PBS encryption. Choosing "Encrypt" makes the
  // recovery passphrase mandatory — same as the CLI. The "Run backup"
  // button stays disabled until a matching passphrase pair is entered
  // (or an already-saved escrow is reused). No accept-risk escape:
  // encrypting without recovery would leave the keyfile only on this
  // host, and a reinstall would render every encrypted backup
  // unrecoverable.
  // Passphrase requirement only kicks in when: encryption is on AND
  // there's no keyfile installed yet (fresh setup) AND the operator
  // opted to upload the key to PBS. Every other case (reuse existing
  // keyfile, or "no upload" mode) doesn't need a passphrase.
  const pbsRecoveryOk = !(backend === "pbs" && pbsEncrypt) ||
    pbsRecoveryStatus?.has_keyfile ||
    !pbsUploadToPbs ||
    (pbsRecoveryPass !== "" && pbsRecoveryPass === pbsRecoveryPass2)
  const canSubmit = canAdvanceFrom1 && backendValid && pbsRecoveryOk

  async function handleRun() {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    // Unified encryption setup — mirrors CreateJobDialog. One atomic
    // /pbs-encryption/import call covers keyfile install + escrow
    // setup with source picked from what the operator provided.
    const needsInstall =
      backend === "pbs" &&
      pbsEncrypt &&
      !pbsRecoveryStatus?.has_keyfile
    if (needsInstall) {
      if (pbsEncryptMode === "existing" && !pbsPveMatch && !pbsImportFile && !pbsImportPath.trim()) {
        setError("Pick a keyfile file or enter an absolute path on this host.")
        setSubmitting(false)
        return
      }
      if (pbsUploadToPbs && pbsRecoveryPass !== pbsRecoveryPass2) {
        setError("Recovery passphrases don't match.")
        setSubmitting(false)
        return
      }
      setPbsImportBusy(true)
      try {
        let source: "generate" | "pve-storage" | "content" | "path"
        if (pbsEncryptMode === "new") source = "generate"
        else if (pbsPveMatch) source = "pve-storage"
        else if (pbsImportFile) source = "content"
        else source = "path"
        const body: Record<string, unknown> = {
          source,
          escrow_mode: pbsUploadToPbs ? "full" : "none",
        }
        if (pbsUploadToPbs) body.escrow_passphrase = pbsRecoveryPass
        if (source === "pve-storage") {
          body.pve_storage_name = pbsPveMatch!.name
        } else if (source === "content") {
          const buf = new Uint8Array(await pbsImportFile!.arrayBuffer())
          let bin = ""
          for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i])
          body.content_b64 = btoa(bin)
        } else if (source === "path") {
          body.keyfile_path = pbsImportPath.trim()
        }
        await fetchApi("/api/host-backups/pbs-encryption/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
        mutatePbsRecovery()
      } catch (e) {
        const err = e as Error & { body?: { tool_output?: string; tool_exit_code?: number } }
        const detail = err.body?.tool_output
          ? `${err.message}\n\nproxmox-backup-client output:\n${err.body.tool_output}`
          : err.message
        setError(`Encryption setup failed: ${detail || String(e)}`)
        setPbsImportBusy(false)
        setSubmitting(false)
        return
      }
      setPbsImportBusy(false)
    }
    // NOTE: recovery escrow is now bundled into the /pbs-encryption/import
    // call above. No separate /pbs-recovery/setup pass is needed.
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
        body.pbs_encrypt_mode = pbsEncryptMode
      } else if (backend === "local") {
        if (localDestDir.trim()) body.local_dest_dir = localDestDir.trim()
      } else if (backend === "borg") {
        // Passphrase + encrypt_mode are inherited from the destination
        // (borg-pass-<name>.txt sidecar + 4th field of borg-targets.txt).
        body.borg_repo = borgRepoSelected
      }
      const resp = await fetchApi<{ status: string; job_id: string }>(
        "/api/host-backups/manual-run",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      )
      onLaunched(resp.job_id)
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
                          <SelectTrigger className="flex-1 min-w-0">
                            {/* Manual render: SelectValue's default mode
                                duplicates the item children and cuts
                                them in the middle on mobile. We render
                                "name — repository" ourselves with a
                                proper trailing ellipsis. */}
                            {(() => {
                              const sel = destResp.pbs.find((r) => r.repository === pbsRepository)
                              if (!sel) {
                                return <span className="truncate text-muted-foreground">Pick a PBS repository</span>
                              }
                              return (
                                <span className="truncate font-mono text-left">
                                  {sel.name}
                                  <span className="text-muted-foreground"> — {sel.repository}</span>
                                </span>
                              )
                            })()}
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
                  <div className="pt-2 border-t border-border space-y-3">
                    <label className="flex items-start gap-2 cursor-pointer">
                      <Checkbox
                        checked={pbsEncrypt}
                        onCheckedChange={(v) => {
                          const checked = !!v
                          if (!checked) {
                            setPbsEncryptMode("none")
                          } else {
                            setPbsEncryptMode(pbsRecoveryStatus?.has_keyfile ? "existing" : "new")
                          }
                        }}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        <div className="inline-flex items-center gap-1.5 text-sm">
                          <Lock className="h-3.5 w-3.5 text-emerald-400" />
                          Encrypt this backup (client-side keyfile)
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          Uses the shared keyfile at <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code>.
                        </p>
                      </div>
                    </label>


                    {pbsEncrypt && !pbsRecoveryStatus?.has_keyfile && (
                      <div className="space-y-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
                        <div className="text-[11px] font-medium">
                          No encryption key is stored on this host. Choose how to set one up:
                        </div>
                        <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                          <input
                            type="radio"
                            name="manualPbsEncryptSetup"
                            checked={pbsEncryptMode === "new"}
                            onChange={() => setPbsEncryptMode("new")}
                            className="mt-1"
                          />
                          <div className="flex-1">
                            <div className="font-medium">Generate a new keyfile (per host — safest isolation)</div>
                            <div className="text-muted-foreground">Creates a fresh keyfile. Set a recovery passphrase (below) to survive host loss.</div>
                          </div>
                        </label>
                        <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                          <input
                            type="radio"
                            name="manualPbsEncryptSetup"
                            checked={pbsEncryptMode === "existing"}
                            onChange={() => setPbsEncryptMode("existing")}
                            className="mt-1"
                          />
                          <div className="flex-1">
                            <div className="font-medium">Import an existing keyfile (shared across hosts)</div>
                            <div className="text-muted-foreground">Reuse the same keyfile another host already has.</div>
                          </div>
                        </label>
                        {pbsEncryptMode === "existing" && pbsPveMatch && (
                          <div className="pt-1 rounded-md border border-emerald-500/40 bg-emerald-500/5 p-2.5 text-[11px] space-y-1">
                            <div className="flex items-start gap-1.5">
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 shrink-0" />
                              <div className="flex-1">
                                <div className="font-medium text-foreground">Auto-detected from PVE storage &apos;{pbsPveMatch.name}&apos;</div>
                                <div className="text-muted-foreground mt-0.5">
                                  Existing key at <code className="font-mono text-[10.5px]">{pbsPveMatch.path}</code>
                                </div>
                                <div className="text-muted-foreground mt-0.5">Will be copied to the ProxMenux state directory. No file upload needed.</div>
                              </div>
                            </div>
                          </div>
                        )}
                        {pbsEncryptMode === "existing" && !pbsPveMatch && (
                          <div className="space-y-2 pt-1">
                            <div className="space-y-1.5">
                              <Label htmlFor="manualPbsImportFile" className="text-[11px] font-medium">
                                Upload from your machine
                              </Label>
                              <Input
                                id="manualPbsImportFile"
                                type="file"
                                accept=".conf,.key,application/json,text/plain"
                                onChange={(e) => setPbsImportFile(e.target.files?.[0] ?? null)}
                                disabled={pbsImportBusy || !!pbsImportPath.trim()}
                                className="h-8 text-[11px]"
                              />
                            </div>
                            <div className="text-[10px] text-center text-muted-foreground">— or —</div>
                            <div className="space-y-1.5">
                              <Label htmlFor="manualPbsImportPath" className="text-[11px] font-medium">
                                Absolute path on this host
                              </Label>
                              <Input
                                id="manualPbsImportPath"
                                type="text"
                                value={pbsImportPath}
                                onChange={(e) => setPbsImportPath(e.target.value)}
                                disabled={pbsImportBusy || !!pbsImportFile}
                                placeholder="/usr/local/share/proxmenux/pbs-key.conf"
                                className="h-8 text-[11px] font-mono"
                              />
                              <p className="text-[10px] text-muted-foreground">
                                Either option works. The file lands at <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code> and every subsequent encrypted backup reuses it.
                              </p>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {pbsEncrypt && (
                      <div className="pl-7 space-y-3 rounded-md border border-blue-500/30 bg-blue-500/5 p-3">
                        {pbsRecoveryStatus?.has_keyfile && !pbsRecoveryChange && (
                          <div className="flex items-start gap-2 text-[11px]">
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 shrink-0" />
                            <div className="flex-1">
                              <div className="text-foreground">Keyfile installed. This backup reuses it silently.</div>
                              <div className="text-muted-foreground mt-0.5">The current PBS-upload setting stays in effect.</div>
                            </div>
                            <button
                              type="button"
                              onClick={() => setPbsRecoveryChange(true)}
                              className="text-blue-400 hover:text-blue-300 underline underline-offset-2 shrink-0"
                            >
                              Change
                            </button>
                          </div>
                        )}
                        {pbsRecoveryStatus?.has_keyfile && pbsRecoveryChange && (
                          <>
                            <KeyfileActionsBar
                              mutateStatus={mutatePbsRecovery}
                              escrowMode={pbsRecoveryStatus?.escrow_mode}
                            />
                            <button
                              type="button"
                              onClick={() => setPbsRecoveryChange(false)}
                              className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2"
                            >
                              Done — hide keyfile options
                            </button>
                          </>
                        )}
                        {!pbsRecoveryStatus?.has_keyfile && (
                          <>
                            <div>
                              <div className="text-[11px] font-medium text-foreground mb-2">Upload key to PBS?</div>
                              <div className="grid gap-1.5">
                                <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                                  <input
                                    type="radio"
                                    name="pbsUploadToPbsManual"
                                    checked={!pbsUploadToPbs}
                                    onChange={() => setPbsUploadToPbs(false)}
                                    className="mt-1"
                                  />
                                  <div className="flex-1">
                                    <div className="font-medium">No, keep local only</div>
                                    <div className="text-muted-foreground">Keyfile stays only at <code className="font-mono text-[10.5px]">/usr/local/share/proxmenux/pbs-key.conf</code>. You are responsible for keeping an offsite copy — losing it makes every encrypted backup unreadable.</div>
                                  </div>
                                </label>
                                <label className="flex items-start gap-2 cursor-pointer text-[11px]">
                                  <input
                                    type="radio"
                                    name="pbsUploadToPbsManual"
                                    checked={pbsUploadToPbs}
                                    onChange={() => setPbsUploadToPbs(true)}
                                    className="mt-1"
                                  />
                                  <div className="flex-1">
                                    <div className="font-medium">Yes, upload</div>
                                    <div className="text-muted-foreground">Set a recovery passphrase now. ProxMenux uploads a passphrase-wrapped copy of the keyfile to PBS with every backup so you can recover it on a reinstalled host with just the passphrase.</div>
                                  </div>
                                </label>
                              </div>
                            </div>
                            {pbsUploadToPbs ? (
                              <div className="space-y-2 pt-1 border-t border-blue-500/20">
                                <div>
                                  <Label htmlFor="manualPbsRecPass" className="text-[11px]">Recovery passphrase</Label>
                                  <Input
                                    id="manualPbsRecPass"
                                    type="password"
                                    value={pbsRecoveryPass}
                                    onChange={(e) => setPbsRecoveryPass(e.target.value)}
                                    placeholder="Long random string — write it down somewhere safe"
                                    className="font-mono mt-1 h-8 text-xs"
                                  />
                                </div>
                                <div>
                                  <Label htmlFor="manualPbsRecPass2" className="text-[11px]">Confirm passphrase</Label>
                                  <Input
                                    id="manualPbsRecPass2"
                                    type="password"
                                    value={pbsRecoveryPass2}
                                    onChange={(e) => setPbsRecoveryPass2(e.target.value)}
                                    placeholder="Type it again"
                                    className="font-mono mt-1 h-8 text-xs"
                                  />
                                  {pbsRecoveryPass && pbsRecoveryPass2 && pbsRecoveryPass !== pbsRecoveryPass2 && (
                                    <p className="text-[11px] text-red-400 mt-1">Passphrases don't match.</p>
                                  )}
                                </div>
                              </div>
                            ) : (
                              <div className="pt-1 border-t border-blue-500/20 text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-3 py-2 leading-relaxed space-y-1">
                                <div className="font-semibold">Keep an offsite copy of the keyfile.</div>
                                <div>After this backup, copy <code className="font-mono text-[10.5px] bg-amber-500/20 rounded px-1">/usr/local/share/proxmenux/pbs-key.conf</code> to an external medium (USB, password manager, another host).</div>
                                <div>Without that copy, losing this host makes every encrypted backup on PBS unreadable.</div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
              {backend === "local" && (
                <div className="space-y-2">
                  <Label>Local destination</Label>
                  {(destResp?.local?.entries?.length ?? 0) > 0 && (
                    <div className="flex items-center gap-2">
                      <Select
                        value={localDestDir || (destResp?.local?.effective ?? "")}
                        onValueChange={(v) => setLocalDestDir(v)}
                      >
                        <SelectTrigger className="flex-1">
                          <SelectValue placeholder="Pick a configured local destination" />
                        </SelectTrigger>
                        <SelectContent>
                          {destResp?.local?.entries?.map((e) => (
                            <SelectItem key={e.path} value={e.path}>
                              <span className="font-mono">{e.path}</span>
                              {e.source === "default" && (
                                <span className="text-muted-foreground ml-2 text-[10px] uppercase">default</span>
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
                        onClick={() => setAddingDestType("local")}
                        title="Save another local destination"
                      >
                        <Plus className="h-3.5 w-3.5 mr-1" />
                        Add another
                      </Button>
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Pick one of the configured local destinations, or type a custom directory path below. Empty input falls back to the selected destination above.
                  </p>
                  <Input
                    id="manualLocalDest"
                    value={localDestDir}
                    onChange={(e) => setLocalDestDir(e.target.value)}
                    placeholder={destResp?.local?.effective || "/var/lib/vz/dump"}
                    className="font-mono"
                  />
                </div>
              )}
              {backend === "borg" && (
                <>
                  <div>
                    <Label>Borg repository</Label>
                    {destResp?.borg?.length ? (
                      <div className="mt-1 flex items-center gap-2">
                        <Select value={borgRepoSelected} onValueChange={setBorgRepoSelected}>
                          <SelectTrigger className="flex-1 min-w-0">
                            {(() => {
                              const sel = destResp.borg.find((r) => r.repository === borgRepoSelected)
                              if (!sel) {
                                return <span className="truncate text-muted-foreground">Pick a Borg repository</span>
                              }
                              return (
                                <span className="truncate font-mono text-left">
                                  {sel.name}
                                  <span className="text-muted-foreground"> — {sel.repository}</span>
                                </span>
                              )
                            })()}
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
                  {(() => {
                    const dest = destResp?.borg?.find((r) => r.repository === borgRepoSelected)
                    if (!dest) return null
                    const mode = dest.encrypt_mode || "repokey"
                    return (
                      <p className="text-[11px] text-muted-foreground">
                        Encryption + passphrase are taken from the destination ({mode === "none" ? "no encryption" : mode}). Edit the destination if you need to change them.
                      </p>
                    )
                  })()}
                </>
              )}

              {/* Summary — mirrors the styling of the JobDetailModal. */}
              <div className="rounded-md border border-border bg-background/40 p-3 space-y-2 text-xs">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Summary</div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-muted-foreground">Backend:</span>
                  <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(backend)}`}>
                    {backend}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] text-purple-400 border-purple-400/40 bg-purple-500/5">
                    manual / one-shot
                  </Badge>
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  <FileSearch className="h-3 w-3 text-green-500/80" />
                  <span className="text-green-500/90 uppercase tracking-wider text-[10px]">profile:</span>
                  <span className="text-foreground">{profileMode}</span>
                  <span className="text-muted-foreground">({profileMode === "default" ? defaultPaths.length : customPaths.size} paths)</span>
                </div>
              </div>

              {error && (
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
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
                className="bg-purple-500 hover:bg-purple-600 text-white"
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
  | { id: string; kind: "local"; path: string; source: "default" | "custom"; removable: boolean; jobsUsing: string[] }
  | {
      id: string; kind: "pbs"; name: string; repository: string;
      source: "proxmox" | "manual"; fingerprint?: string; removable: boolean
      jobsUsing: string[]
    }
  | {
      id: string; kind: "borg"; name: string; repository: string;
      isSsh: boolean; ssh?: { user: string; host: string; remotePath: string };
      sshKeyPath?: string;
      // The destination's encryption mode + whether a passphrase is
      // saved server-side; used to render a Lock / Unlock badge so the
      // operator sees at a glance which Borg repos are encrypted.
      encryptMode?: "none" | "repokey" | "keyfile" | "authenticated"
      hasPassphrase?: boolean
      removable: boolean
      jobsUsing: string[]
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
  const [editingDest, setEditingDest] = useState<EditingDest | null>(null)
  const [confirmingDest, setConfirmingDest] = useState<UnifiedDest | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Used by the Delete-destination confirm to tell the operator how
  // many backups already live on this target (they're kept after the
  // destination + jobs cascade, so the warning is informational).
  const { data: localArchivesResp } = useSWR<{ archives: BackupArchive[] }>(
    "/api/host-backups/archives",
    fetcher,
    { refreshInterval: 60_000, revalidateOnFocus: false },
  )
  const { data: remoteArchivesResp } = useSWR<RemoteArchivesResp>(
    "/api/host-backups/remote-archives",
    fetcher,
    { refreshInterval: 60_000, revalidateOnFocus: false },
  )
  // Recovery state — only needed when at least one PBS destination
  // exists. Drives the "Recover keyfile" banner and the "PBS encryption
  // key" management block.
  const hasPbs = (destinations?.pbs?.length ?? 0) > 0
  const { data: pbsRecoveryStatus, mutate: mutatePbsRecovery } = useSWR<{
    has_keyfile: boolean; has_recovery: boolean; has_keyfile_passphrase?: boolean; escrow_mode?: "none" | "local" | "full"; keyfile_fingerprint?: string
  }>(hasPbs ? "/api/host-backups/pbs-recovery/status" : null, fetcher)
  const { data: pbsRecoveryAvailable } = useSWR<{
    snapshots: Array<{ repo_name: string; repo_repository: string; backup_id: string; source_host: string; backup_time: number; snapshot: string }>
    errors: Array<{ repo_name: string; error: string }>
  }>(
    hasPbs && pbsRecoveryStatus && !pbsRecoveryStatus.has_keyfile
      ? "/api/host-backups/pbs-recovery/available"
      : null,
    fetcher,
  )
  const [recoveringKeyfile, setRecoveringKeyfile] = useState<boolean>(false)
  const backupsCountFor = (it: UnifiedDest): number => {
    if (it.kind === "local") {
      const root = it.path.replace(/\/+$/, "") + "/"
      return (localArchivesResp?.archives || []).filter(
        (a) => (a.path || "").startsWith(root),
      ).length
    }
    const name = it.kind === "pbs" ? it.name : it.kind === "borg" ? it.name : ""
    return (remoteArchivesResp?.snapshots || []).filter(
      (s) => s.backend === it.kind && s.repo_name === name,
    ).length
  }

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
        jobsUsing: e.jobs_using || [],
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
        jobsUsing: r.jobs_using || [],
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
        encryptMode: r.encrypt_mode,
        hasPassphrase: r.has_passphrase,
        removable: true,
        jobsUsing: r.jobs_using || [],
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

  async function removePbs(name: string, force = false) {
    setBusyKey(`pbs:${name}`)
    setError(null)
    try {
      await fetchApi(`/api/host-backups/destinations/pbs/${encodeURIComponent(name)}${force ? "?force=true" : ""}`, { method: "DELETE" })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }
  async function removeBorg(name: string, force = false) {
    setBusyKey(`borg:${name}`)
    setError(null)
    try {
      await fetchApi(`/api/host-backups/destinations/borg/${encodeURIComponent(name)}${force ? "?force=true" : ""}`, { method: "DELETE" })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }
  async function removeLocal(path: string, force = false) {
    setBusyKey(`local:${path}`)
    setError(null)
    try {
      const params = new URLSearchParams({ path })
      if (force) params.set("force", "true")
      await fetchApi(
        `/api/host-backups/destinations/local?${params.toString()}`,
        { method: "DELETE" },
      )
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }
  async function confirmDeleteDest() {
    const it = confirmingDest
    if (!it) return
    const force = it.jobsUsing.length > 0
    setConfirmingDest(null)
    if (it.kind === "pbs") return removePbs(it.name, force)
    if (it.kind === "borg") return removeBorg(it.name, force)
    if (it.kind === "local") return removeLocal(it.path, force)
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
      <div className="flex justify-end">
        <Button
          size="sm"
          className="h-8 px-3 bg-blue-500 hover:bg-blue-600 text-white"
          onClick={() => setConfiguring(true)}
        >
          <Plus className="h-4 w-4 mr-1" />
          Configure destination
        </Button>
      </div>
      {error && (
        <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
          {error}
        </div>
      )}
      {/* Recovery banner: only when there's no local keyfile AND at
          least one escrow blob was found on a configured PBS. Click
          opens a passphrase dialog and the keyfile is rebuilt from
          the blob. Equivalent to hb_pbs_try_keyfile_recovery in the
          shell — what runs after a fresh PVE install when the
          operator points the new host at the same PBS. */}
      {hasPbs && pbsRecoveryStatus && !pbsRecoveryStatus.has_keyfile && (pbsRecoveryAvailable?.snapshots?.length ?? 0) > 0 && (
        <button
          type="button"
          onClick={() => setRecoveringKeyfile(true)}
          className="w-full flex items-start gap-2 px-3 py-2.5 rounded-md border border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10 transition-colors text-left"
          title="A recovery copy of the PBS keyfile was found on this PBS server"
        >
          <Lock className="h-4 w-4 mt-0.5 text-emerald-400 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-foreground">
              PBS keyfile is missing — recover it from PBS
            </div>
            <div className="text-[11px] text-muted-foreground mt-0.5">
              An encrypted recovery copy of the keyfile is available ({pbsRecoveryAvailable!.snapshots.length} backup{pbsRecoveryAvailable!.snapshots.length === 1 ? "" : "s"}). Click to rebuild the keyfile using your recovery passphrase.
            </div>
          </div>
          <span className="text-xs text-emerald-300 shrink-0 self-center">Recover →</span>
        </button>
      )}

      <div className="space-y-2">
        {items.map((it) => {
          const cap = capByEdid.get(it.id)
          const busy = busyKey === it.id ||
            (it.kind === "pbs" && busyKey === `pbs:${it.name}`) ||
            (it.kind === "borg" && busyKey === `borg:${it.name}`) ||
            (it.kind === "local" && busyKey === `local:${it.path}`)
          // Borg local-mode repos sit on top of a path — the same
          // /mnt/proxmenux-backup-disk-* USB mountpoint a Local target
          // would use. Expose Unmount for them too so the operator
          // doesn't have to remember which destination type is on the
          // disk they want to detach.
          const borgLocalUsbPath = it.kind === "borg" && !it.isSsh && cap?.is_usb
            ? it.repository
            : null
          const umountTarget = it.kind === "local" ? it.path : borgLocalUsbPath
          const unmountBusy = !!umountTarget && busyKey === `umount:${umountTarget}`
          return (
            <DestinationRow
              key={it.id}
              item={it}
              capacity={cap}
              busy={busy}
              unmountBusy={unmountBusy}
              onDelete={() => setConfirmingDest(it)}
              onUnmount={
                umountTarget && cap?.is_usb
                  ? () => unmountUsb(umountTarget)
                  : undefined
              }
              onEdit={
                // Only PBS-manual and Borg are editable from the UI.
                // PBS-proxmox is managed by Datacenter → Storage and
                // local destinations have no fields beyond the path.
                it.kind === "pbs" && it.source === "manual"
                  ? () => {
                      const [user, rest] = it.repository.includes("@")
                        ? [it.repository.split("@").slice(0, -1).join("@"), it.repository.split("@").pop() || ""]
                        : ["root@pam", it.repository]
                      const [server, datastore] = rest.includes(":")
                        ? [rest.split(":").slice(0, -1).join(":"), rest.split(":").pop() || ""]
                        : [rest, ""]
                      setEditingDest({
                        kind: "pbs",
                        name: it.name,
                        username: user,
                        server,
                        datastore,
                        fingerprint: it.fingerprint,
                        has_password: true,
                      })
                    }
                  : it.kind === "borg"
                    ? () => setEditingDest({
                        kind: "borg",
                        name: it.name,
                        repository: it.repository,
                        ssh_key_path: it.sshKeyPath,
                        encrypt_mode: (destinations?.borg?.find((b) => b.name === it.name)?.encrypt_mode) || "repokey",
                        has_passphrase: !!destinations?.borg?.find((b) => b.name === it.name)?.has_passphrase,
                      })
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
      {/* Edit-an-existing-destination dialog. Uses the same form as
          Add, just hydrated with the saved values and with `name`
          locked. The POST endpoint is upsert-by-name on the backend
          so no separate route is needed. */}
      <AddDestinationDialog
        type={editingDest?.kind ?? null}
        editing={editingDest}
        onClose={() => setEditingDest(null)}
        onSaved={() => {
          setEditingDest(null)
          onChanged()
        }}
      />
      <PbsKeyfileRecoveryDialog
        open={recoveringKeyfile}
        snapshots={pbsRecoveryAvailable?.snapshots || []}
        onClose={() => setRecoveringKeyfile(false)}
        onRecovered={() => {
          setRecoveringKeyfile(false)
          mutatePbsRecovery()
        }}
      />
      {/* Delete-destination confirm. Always opens (uniform UX) but
          the body adapts: a plain "Remove?" when no jobs/backups
          depend on the destination, or a warning summarizing the
          cascade (jobs go, backups stay) when there's something at
          stake. The destination + its sidecars are removed; backups
          on disk / on the remote stay untouched so the operator can
          decide what to do with them later. */}
      {confirmingDest && (() => {
        const it = confirmingDest
        const jobs = it.jobsUsing
        const backups = backupsCountFor(it)
        const headline =
          it.kind === "local" ? it.path
          : it.kind === "pbs" ? `${it.name} — ${it.repository}`
          : `${it.name} — ${it.repository}`
        return (
          <Dialog open={true} onOpenChange={(v) => { if (!v) setConfirmingDest(null) }}>
            <DialogContent className="max-w-md bg-card border-border">
              <DialogHeader>
                <DialogTitle className="text-base flex items-center gap-2">
                  <AlertTriangle className={`h-5 w-5 ${jobs.length > 0 ? "text-amber-500" : "text-red-500"}`} />
                  Remove destination
                </DialogTitle>
                <DialogDescription className="text-xs">
                  {jobs.length === 0 && backups === 0
                    ? "Removes the destination from the list. Nothing else depends on it."
                    : "The destination + its saved credentials will be removed. Backups already stored stay where they are — you decide what to do with them later."}
                </DialogDescription>
              </DialogHeader>
              <div className="text-sm font-mono px-3 py-2 rounded-md border border-border bg-background/40 break-all">
                {headline}
              </div>
              {(jobs.length > 0 || backups > 0) && (
                <div className="text-xs space-y-1.5 text-foreground">
                  {jobs.length > 0 && (
                    <div className="px-3 py-2 rounded-md border border-amber-500/40 bg-amber-500/5">
                      <div className="font-medium text-amber-400">
                        {jobs.length} job{jobs.length === 1 ? "" : "s"} will be deleted (cascade):
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {jobs.map((j) => (
                          <span key={j} className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-background/60 border border-border">
                            {j}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {backups > 0 && (
                    <div className="px-3 py-2 rounded-md border border-blue-500/40 bg-blue-500/5">
                      <span className="font-medium text-blue-400">{backups}</span> backup{backups === 1 ? "" : "s"} already at this destination — they are <span className="font-medium">kept</span>.
                    </div>
                  )}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setConfirmingDest(null)}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={confirmDeleteDest}>
                  <Trash2 className="h-4 w-4 mr-2" />
                  {jobs.length > 0 ? "Remove + delete jobs" : "Remove destination"}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )
      })()}
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
  onEdit,
}: {
  item: UnifiedDest
  capacity?: CapacityInfo
  busy: boolean
  unmountBusy: boolean
  onDelete: () => void
  onUnmount?: () => void
  onEdit?: () => void
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
    // Borg targets are always operator-configured (no Datacenter
    // auto-discovery path), so they all share the "manually added"
    // wording for visual consistency with the Local custom row.
    : "manually added"

  const pct = capacity?.total && capacity.available !== undefined
    ? Math.min(100, Math.round(((capacity.total - capacity.available) / capacity.total) * 100))
    : null

  return (
    <div className="rounded-lg border border-white/10 bg-card p-4">
      {/* Top row split in two: a wrappable left side (icon + headline +
          badges) and a fixed right side (Unmount + Remove). The right
          side never falls to a new line even if `headline` is long,
          because the outer container is a non-wrapping flex. */}
      <div className="space-y-2 mb-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1 flex items-start gap-2 flex-wrap">
            <Icon className={`h-5 w-5 flex-shrink-0 ${iconColor} mt-0.5`} />
            <h3 className="font-mono font-semibold text-sm break-all">{headline}</h3>
            <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${accent}`}>
              {item.kind}
            </Badge>
          {item.kind === "local" && item.source === "default" && (
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-border text-muted-foreground">
              default
            </Badge>
          )}
          {item.kind === "borg" ? (
            // For Borg the sub-type is one of three (mutually exclusive):
            //   ssh    → remote repo
            //   usb    → local repo whose path lives on a USB mount
            //   local  → local repo on an internal disk / regular dir
            // Previously we showed BORG + LOCAL + USB which read like
            // three orthogonal facets and confused the badge with the
            // Local destination kind. Collapsing to a single sub-type
            // badge avoids the overlap.
            <>
              {item.isSsh ? (
                <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-cyan-500/40 text-cyan-400 bg-cyan-500/5">
                  ssh
                </Badge>
              ) : isUsb ? (
                <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-orange-500/40 text-orange-400 bg-orange-500/5 gap-1">
                  <HardDrive className="h-2.5 w-2.5" />
                  USB
                </Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-amber-500/40 text-amber-400 bg-amber-500/5">
                  local
                </Badge>
              )}
              {/* Encryption indicator — icon-only chip for encrypted
                  repos. Plaintext repos get no chip (visually quiet
                  for the common case). The tooltip carries the mode +
                  saved-passphrase state for hover detail. */}
              {item.encryptMode && item.encryptMode !== "none" && (
                <Badge
                  variant="outline"
                  className="text-[10px] uppercase tracking-wide border-emerald-500/40 text-emerald-400 bg-emerald-500/5"
                  title={`Encrypted (${item.encryptMode})${item.hasPassphrase ? " · passphrase saved" : " · passphrase NOT saved"}`}
                >
                  {/* Icon sized to roughly the text-[10px] line-box of
                      the neighbouring text badges (BORG, USB, …) so the
                      pill itself ends up the same height — matching
                      visual weight without adding a label. */}
                  <Lock className="h-3.5 w-3.5" />
                </Badge>
              )}
            </>
          ) : isUsb && (
            // PBS / Local destinations: USB badge is additive (the kind
            // badge alone doesn't say where the path lives).
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide border-orange-500/40 text-orange-400 bg-orange-500/5 gap-1">
              <HardDrive className="h-2.5 w-2.5" />
              USB
            </Badge>
          )}
          </div>
          {/* Action chips — always pinned to the right, never wrap.
              The outer flex container has no flex-wrap so even a very
              long headline keeps these two buttons in place. Chip
              style (square border + tinted bg) makes them read as
              actionable rather than decorative icons. */}
          <div className="shrink-0 flex items-start gap-1.5">
            {onEdit && (
              <button
                type="button"
                disabled={busy || unmountBusy}
                onClick={onEdit}
                title="Edit destination — update credentials, encryption, repository path"
                className="inline-flex items-center justify-center h-7 w-7 rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {onUnmount && (
              <button
                type="button"
                disabled={unmountBusy || busy}
                onClick={onUnmount}
                title="Unmount — detach the USB filesystem only. The destination stays in the list so re-plugging the disk picks it up again."
                className="inline-flex items-center justify-center h-7 w-7 rounded-md border border-amber-500/40 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 hover:text-amber-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {unmountBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Power className="h-3.5 w-3.5" />}
              </button>
            )}
            {item.removable ? (
              <button
                type="button"
                disabled={busy || unmountBusy}
                onClick={onDelete}
                title="Remove from the destinations list — the filesystem on disk is left untouched"
                className="inline-flex items-center justify-center h-7 w-7 rounded-md border border-red-500/40 bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </button>
            ) : (
              <span className="text-[10px] text-muted-foreground italic self-center px-2 whitespace-nowrap">
                {item.kind === "local" ? "built-in" : "managed by PVE"}
              </span>
            )}
          </div>
        </div>
        {subline && (
          <p className="text-xs font-mono text-muted-foreground break-all pl-7" title={subline}>
            {subline}
          </p>
        )}
      </div>

      {/* Capacity bar — matches the height of the <Progress> component
          used on the Storage page (h-2). Bar colour comes from the
          shared storage palette so a 100% PBS datastore flags red
          here too, not just on the Storage page. */}
      {capacity?.total && capacity.available !== undefined && (
        <div className="mb-3 h-2 bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${getStorageUsageColor(pct ?? 0).bgClass}`}
            style={{ width: `${pct}%` }}
          />
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
            <p
              className={`font-medium ${
                pct === null ? "" : getStorageUsageColor(pct).textClass
              }`}
            >
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
      {/* Keyfile actions live inside each PBS row — the encryption key
          is host-wide but conceptually belongs to PBS usage, so the
          Download / Upload / Delete controls sit next to the
          destination(s) they support. */}
      {item.kind === "pbs" && <PbsKeyfileActions />}
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
// Pre-fill payload for editing an existing destination. `name` stays
// fixed (it's the key the sidecar / state files are scoped to);
// everything else can be re-typed. PBS password and Borg passphrase
// can be left blank to keep the saved one.
interface EditingDest {
  kind: "pbs" | "borg"
  name: string
  // PBS fields
  server?: string
  datastore?: string
  username?: string
  fingerprint?: string
  has_password?: boolean
  // Borg fields
  repository?: string
  ssh_key_path?: string
  encrypt_mode?: "none" | "repokey" | "keyfile" | "authenticated"
  has_passphrase?: boolean
}

function AddDestinationDialog({
  type,
  editing,
  onClose,
  onSaved,
}: {
  type: "pbs" | "borg" | "local" | null
  editing?: EditingDest | null
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
  // Borg encryption + passphrase live on the destination, not on each
  // job. Two-mode UI: encrypted (repokey, the default) or none. Other
  // borg modes (keyfile / authenticated) stay supported by the backend
  // for legacy shell-created configs.
  const [borgEncryptionEnabled, setBorgEncryptionEnabled] = useState(true)
  const [borgPassphrase, setBorgPassphraseLocal] = useState("")
  const [borgPassphrase2, setBorgPassphrase2] = useState("")
  // Local field
  const [localPath, setLocalPath] = useState("")

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Read the current destinations so the UsbPicker can hide any USB
  // mountpoint already in use as a Local or Borg-local destination —
  // no point offering the same disk twice.
  const { data: existingDest } = useSWR<DestinationsResp>(
    type !== null ? "/api/host-backups/destinations" : null,
    fetcher,
  )
  const usedPaths: string[] = (() => {
    const out: string[] = []
    for (const e of existingDest?.local?.entries || []) {
      if (e.source === "custom") out.push(e.path)
    }
    for (const r of existingDest?.borg || []) {
      // Borg local-mode: the `repository` IS the path. SSH repos
      // start with `ssh://` and are excluded automatically.
      if (!r.repository.startsWith("ssh://")) out.push(r.repository)
    }
    return out
  })()

  // Reset every time the dialog OPENS — not just on close. If we're
  // opening in edit mode, hydrate the form from the saved destination
  // so the operator only has to change what they want. Name stays
  // read-only in edit mode (it's the key for sidecars / state files).
  useEffect(() => {
    setError(null)
    setSubmitting(false)
    setGeneratedKey(null)
    setGeneratingKey(false)
    setPassword("")
    setBorgPassphraseLocal("")
    setBorgPassphrase2("")
    if (editing && editing.kind === "pbs") {
      setName(editing.name)
      setServer(editing.server || "")
      setDatastore(editing.datastore || "")
      setUsername(editing.username || "root@pam")
      setFingerprint(editing.fingerprint || "")
      setBorgRepo(""); setBorgMode("local"); setBorgSshUser("borg")
      setBorgSshHost(""); setBorgSshRemotePath("")
      setBorgSshKeyPath("/root/.ssh/proxmenux_borg")
      setBorgEncryptionEnabled(true); setLocalPath("")
      return
    }
    if (editing && editing.kind === "borg") {
      const repo = editing.repository || ""
      const ssh = repo.match(/^ssh:\/\/([^@]+)@([^/]+)\/(.+)$/)
      setName(editing.name)
      if (ssh) {
        setBorgMode("ssh")
        setBorgSshUser(ssh[1])
        setBorgSshHost(ssh[2])
        setBorgSshRemotePath(`/${ssh[3]}`)
        setBorgSshKeyPath(editing.ssh_key_path || "/root/.ssh/proxmenux_borg")
        setBorgRepo("")
      } else {
        setBorgMode("local")
        setBorgRepo(repo)
        setBorgSshUser("borg"); setBorgSshHost(""); setBorgSshRemotePath("")
        setBorgSshKeyPath("/root/.ssh/proxmenux_borg")
      }
      const mode = editing.encrypt_mode || "repokey"
      setBorgEncryptionEnabled(mode !== "none")
      setServer(""); setDatastore(""); setUsername("root@pam"); setFingerprint("")
      setLocalPath("")
      return
    }
    // Add-new path: full reset.
    setName("")
    setServer("")
    setDatastore("")
    setUsername("root@pam")
    setFingerprint("")
    setBorgRepo("")
    setBorgMode("local")
    setBorgSshUser("borg")
    setBorgSshHost("")
    setBorgSshRemotePath("")
    setBorgSshKeyPath("/root/.ssh/proxmenux_borg")
    setBorgEncryptionEnabled(true)
    setLocalPath("")
  }, [type, editing])

  const isEditing = !!editing
  const nameValid = /^[a-zA-Z0-9_-]+$/.test(name)
  const borgPathValid =
    borgMode === "local"
      ? !!borgRepo.trim()
      : !!(borgSshUser.trim() && borgSshHost.trim() && borgSshRemotePath.trim())
  // In edit mode the saved passphrase / password is reused when the
  // operator leaves the inputs blank, so validation relaxes.
  const borgPassphraseValid =
    !borgEncryptionEnabled
    || (isEditing && !borgPassphrase && editing?.has_passphrase)
    || (borgPassphrase.length > 0 && borgPassphrase === borgPassphrase2)
  const borgValid = borgPathValid && borgPassphraseValid
  const canSubmit =
    type === "pbs"
      ? nameValid && server.trim() && datastore.trim() &&
          (!!password || (isEditing && !!editing?.has_password))
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
        const body: Record<string, unknown> = {
          name,
          mode: borgMode,
          encrypt_mode: borgEncryptionEnabled ? "repokey" : "none",
        }
        if (borgEncryptionEnabled) {
          body.passphrase = borgPassphrase
        }
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
            {isEditing ? (
              <Pencil className="h-5 w-5 text-emerald-400" />
            ) : (
              <Plus className="h-5 w-5 text-blue-500" />
            )}
            {isEditing ? "Edit" : "Add"} {type === "pbs" ? "PBS" : type === "borg" ? "Borg" : "local"} destination
          </DialogTitle>
        </DialogHeader>
        <div className="overflow-y-auto -mr-2 pr-2 space-y-3">
          {type === "pbs" && (
            <>
              <div>
                <Label htmlFor="pbsName">Name</Label>
                <Input id="pbsName" value={name} onChange={(e) => setName(e.target.value)} className="font-mono mt-1" placeholder="my-pbs" disabled={isEditing} />
                <p className="text-xs text-muted-foreground mt-1">
                  {isEditing ? "Name is the key for saved credentials and can't be changed." : "A short identifier. Letters, digits, _ or -."}
                </p>
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
                <Input
                  id="pbsPass"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="font-mono mt-1"
                  placeholder={isEditing && editing?.has_password ? "(unchanged — type to replace)" : ""}
                />
                {isEditing && editing?.has_password && (
                  <p className="text-xs text-muted-foreground mt-1">Leave blank to keep the saved password.</p>
                )}
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
                <Input id="borgName" value={name} onChange={(e) => setName(e.target.value)} className="font-mono mt-1" placeholder="usb-borg or remote-borg" disabled={isEditing} />
                {isEditing && (
                  <p className="text-xs text-muted-foreground mt-1">Name is the key for the saved passphrase and can't be changed.</p>
                )}
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
                  <UsbPicker onPick={(p) => setBorgRepo(p)} excludePaths={usedPaths} />
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

              {/* Encryption + passphrase live on the destination, not on
                  each job. Two-mode UI: encrypted (repokey, the borg
                  recommended default) or none. The other borg modes
                  (keyfile, authenticated) are still honored by the
                  backend for legacy shell-created configs but not
                  exposed here. */}
              <div className="space-y-2 pt-2 border-t border-border">
                <Label>Encryption</Label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setBorgEncryptionEnabled(true)}
                    className={`text-left p-2.5 rounded-md border text-sm transition-colors ${borgEncryptionEnabled ? "border-fuchsia-500 bg-fuchsia-500/5" : "border-border bg-background/40 hover:bg-white/5"}`}
                  >
                    <div className="font-medium">Encrypted (repokey)</div>
                    <div className="text-[11px] text-muted-foreground">AES-256 + HMAC. Passphrase required to read the repo.</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setBorgEncryptionEnabled(false)}
                    className={`text-left p-2.5 rounded-md border text-sm transition-colors ${!borgEncryptionEnabled ? "border-amber-500 bg-amber-500/5" : "border-border bg-background/40 hover:bg-white/5"}`}
                  >
                    <div className="font-medium">No encryption</div>
                    <div className="text-[11px] text-muted-foreground">Faster but data and checksums are in plain.</div>
                  </button>
                </div>
                {borgEncryptionEnabled && (
                  <div className="space-y-2 pt-1">
                    <div>
                      <Label htmlFor="borgPass">Passphrase</Label>
                      <Input
                        id="borgPass"
                        type="password"
                        value={borgPassphrase}
                        onChange={(e) => setBorgPassphraseLocal(e.target.value)}
                        placeholder={isEditing && editing?.has_passphrase
                          ? "(unchanged — type to replace)"
                          : "Long random string — store it somewhere safe"}
                        className="font-mono mt-1"
                      />
                      {isEditing && editing?.has_passphrase && (
                        <p className="text-[11px] text-muted-foreground mt-1">Leave blank to keep the saved passphrase.</p>
                      )}
                    </div>
                    <div>
                      <Label htmlFor="borgPass2">Confirm passphrase</Label>
                      <Input
                        id="borgPass2"
                        type="password"
                        value={borgPassphrase2}
                        onChange={(e) => setBorgPassphrase2(e.target.value)}
                        placeholder="Type it again"
                        className="font-mono mt-1"
                      />
                      {borgPassphrase && borgPassphrase2 && borgPassphrase !== borgPassphrase2 && (
                        <p className="text-[11px] text-red-400 mt-1">Passphrases don't match.</p>
                      )}
                    </div>
                    <div className="mt-1 rounded-md border border-red-500/40 bg-red-500/10 p-2.5">
                      <div className="flex items-start gap-1.5 text-[11px] text-red-300">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                        <div className="space-y-1">
                          <p>
                            <span className="font-medium">This passphrase is the ONLY way to access encrypted Borg backups.</span> It's saved server-side at <code className="font-mono">borg-pass-{name || "&lt;name&gt;"}.txt</code> (chmod 0600) so jobs can use it transparently.
                          </p>
                          <p>
                            If you lose or reinstall this host without a copy of the passphrase somewhere else (password manager, offline note, another host, USB stick...), every encrypted archive in this repository becomes <span className="font-semibold">UNRECOVERABLE</span>.
                          </p>
                          <p className="font-medium">Save the passphrase somewhere safe NOW, before continuing.</p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
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
              <UsbPicker onPick={(p) => setLocalPath(p)} excludePaths={usedPaths} />
            </div>
          )}
          {error && (
            <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
              {error}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-3 border-t border-border">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>Cancel</Button>
          <Button
            onClick={handleSave}
            disabled={!canSubmit || submitting}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Save className="h-4 w-4 mr-2" />}
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
function UsbPicker({
  onPick,
  excludePaths = [],
}: {
  onPick: (path: string) => void
  // Hide a USB drive ONLY when an existing destination already targets
  // its mountpoint root verbatim. Subdirectory uses don't claim the
  // whole disk — both Local and Borg can share the same USB by
  // pointing at different subdirs (`/mnt/usbX/borgbackup` for Borg,
  // `/mnt/usbX/local-dump` for Local). The previous prefix-based
  // filter was too greedy and made it impossible to add a second
  // destination type once any one of them landed on the disk.
  excludePaths?: string[]
}) {
  const { data, mutate, isLoading } = useSWR<{ drives: UsbDrive[] }>(
    "/api/host-backups/usb-drives",
    fetcher,
    { refreshInterval: 0 },
  )
  const normalized = new Set((excludePaths || []).map((p) => p.replace(/\/+$/, "")))
  const drives = (data?.drives ?? []).filter((d) => {
    const mp = (d.path_or_device || "").replace(/\/+$/, "")
    return !mp || !normalized.has(mp)
  })
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
          <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
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
                <button
                  type="button"
                  disabled={busyPath === p.path}
                  onClick={() => removePath(p.path)}
                  title="Remove this custom path"
                  className="shrink-0 inline-flex items-center justify-center h-7 w-7 rounded-md border border-red-500/40 bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {busyPath === p.path ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                </button>
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
        <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
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

  // When the modal opens onto a job that's already running (last_run_at
  // set but last_result still null), jump straight into streaming mode
  // so the operator can resume watching from anywhere — including the
  // "Manual backup in progress" banner on the Manual backups card and
  // a click on a scheduled job row that's currently mid-run.
  useEffect(() => {
    if (!open || running || !detail) return
    if (detail.last_run_at && !detail.last_result) {
      // Baseline = empty so the exit condition still fires (any
      // non-empty last_run_at + a non-null last_result will trip it).
      setRunBaseline("")
      setRunBaselineLogPath(detail.last_log_path ?? null)
      setRunning(true)
    }
  }, [open, running, detail])

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
            <DialogTitle className="flex items-center gap-2 flex-wrap text-base pr-8">
              <DatabaseBackup className="h-5 w-5 text-blue-500" />
              <span className="font-mono break-all">{detail?.id ?? jobId}</span>
              {detail && (
                <>
                  <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(detail.method)}`}>
                    {detail.method}
                  </Badge>
                  {/* Encryption badge — mirrors the InspectModal one
                      so the operator sees the lock in both the summary
                      list and the job detail view. */}
                  {(detail.pbs_encrypt || (detail.borg_encrypt_mode && detail.borg_encrypt_mode !== "none")) && (
                    <Badge
                      variant="outline"
                      className="text-emerald-400 border-emerald-500/40 bg-emerald-500/10"
                      title="Encrypted"
                    >
                      <Lock className="h-3.5 w-3.5" />
                    </Badge>
                  )}
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
            <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
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
            // Layout mirrors the InspectModal footer: primary action on
            // the left in solid green (Run, matches Restore), secondary
            // Edit next to it in blue outline, then state-changers on
            // the right (Disable / Delete) — both outlined to read as
            // less prominent than Run.
            <div className="border-t border-border pt-3 flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  size="sm"
                  onClick={handleRun}
                  disabled={running || busy !== ""}
                  className="bg-green-600 hover:bg-green-700 text-white"
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
                  className="bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                  onClick={() => onEdit(detail.id)}
                >
                  <Pencil className="h-3.5 w-3.5 mr-1" />
                  Edit
                </Button>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
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
                  className="bg-red-500/10 border-red-500/40 !text-red-400 hover:bg-red-500/20 hover:!text-red-300"
                  onClick={() => onRequestDelete(detail.id)}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                  Delete
                </Button>
              </div>
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

// ──────────────────────────────────────────────────────────────
// ManualJobWatchModal
// ──────────────────────────────────────────────────────────────
// Sibling of JobDetailModal but tailored to manual / one-shot jobs.
// A manual job has no schedule, no retention, no profile picker — and
// once it has run it can't be re-run or edited (it's a frozen
// snapshot of one trigger). So the modal collapses to:
//   - the live log when the job is in flight
//   - the destination details (only the fields that matter for the
//     picked backend)
//   - Close + Delete actions (Edit / Run / Disable don't apply)
// ──────────────────────────────────────────────────────────────
function ManualJobWatchModal({
  jobId,
  onClose,
  onChanged,
}: {
  jobId: string | null
  onClose: () => void
  onChanged: () => void
}) {
  const open = jobId !== null
  const [running, setRunning] = useState(false)
  const [runBaselineLogPath, setRunBaselineLogPath] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const { data: detail, mutate: refetch, isLoading } = useSWR<JobDetail>(
    open ? `/api/host-backups/jobs/${encodeURIComponent(jobId!)}` : null,
    fetcher,
    { refreshInterval: running ? 2000 : 0 },
  )
  const { data: liveLog } = useSWR<{ content: string; log_path: string | null; size: number }>(
    open && running ? `/api/host-backups/jobs/${encodeURIComponent(jobId!)}/log` : null,
    fetcher,
    { refreshInterval: 1500 },
  )
  const liveLogRef = useRef<HTMLPreElement | null>(null)
  useEffect(() => {
    if (running && liveLogRef.current) {
      liveLogRef.current.scrollTop = liveLogRef.current.scrollHeight
    }
  }, [liveLog, running])

  // Auto-detect in-progress runs (RUN_AT set but RESULT not yet
  // persisted) and enter streaming mode on open.
  useEffect(() => {
    if (!open || running || !detail) return
    if (detail.last_run_at && !detail.last_result) {
      setRunBaselineLogPath(detail.last_log_path ?? null)
      setRunning(true)
    }
  }, [open, running, detail])

  // Exit streaming when both RUN_AT and RESULT are set.
  useEffect(() => {
    if (!running || !detail) return
    if (detail.last_run_at && detail.last_result) {
      setRunning(false)
      setRunBaselineLogPath(null)
      onChanged()
    }
  }, [detail, running, onChanged])

  useEffect(() => {
    if (!open) {
      setRunning(false)
      setRunBaselineLogPath(null)
      setActionError(null)
    }
  }, [open])

  const resultBadge = running
    ? { label: "running", cls: "bg-blue-500/10 border-blue-500/40 text-blue-300" }
    : detail?.last_result === "ok"
      ? { label: "ok", cls: "bg-emerald-500/10 border-emerald-500/40 text-emerald-300" }
      : detail?.last_result
        ? { label: detail.last_result, cls: "bg-red-500/10 border-red-500/40 text-red-300" }
        : null
  const lastRunWhen = formatRunAt(detail?.last_run_at ?? null)
  const destAccent =
    detail?.method === "pbs" ? "text-purple-400"
    : detail?.method === "borg" ? "text-fuchsia-400"
    : "text-blue-400"

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
        <DialogContent className="max-w-3xl bg-card border-border overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 flex-wrap text-base">
              <PlayCircle className="h-5 w-5 text-purple-400" />
              <span className="font-mono break-all">{detail?.id ?? jobId}</span>
              {detail && (
                <>
                  <Badge variant="outline" className={`text-[10px] uppercase tracking-wide ${methodBadgeCls(detail.method)}`}>
                    {detail.method}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] text-purple-400 border-purple-400/40 bg-purple-500/5">
                    manual / one-shot
                  </Badge>
                </>
              )}
            </DialogTitle>
            <DialogDescription className="text-xs">
              One-shot backup — captured at the time of the trigger. Cannot be re-run or edited.
            </DialogDescription>
          </DialogHeader>

          {actionError && (
            <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
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
              <div className="space-y-4 text-sm">
                {/* Status + live log — manual one-shot has no concept
                    of "last run" (the modal IS the run), so we use a
                    neutral "Status" header here. */}
                <section className="space-y-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-green-500">
                    <Clock className="h-3.5 w-3.5" /> Status
                  </h4>
                  <div className="flex items-center gap-2 flex-wrap text-xs">
                    {resultBadge ? (
                      <span className={`px-2 py-0.5 rounded text-[10px] uppercase tracking-wide border inline-flex items-center gap-1 ${resultBadge.cls}`}>
                        {running && <Loader2 className="h-3 w-3 animate-spin" />}
                        {resultBadge.label}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">starting…</span>
                    )}
                    {lastRunWhen && <span className="text-muted-foreground">{lastRunWhen}</span>}
                  </div>
                  {running ? (
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
                              {showContent ? `live · ${formatBytes(liveLog?.size ?? 0)}` : "starting…"}
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
                  ) : detail.last_log_tail && detail.last_log_tail.length > 0 ? (
                    <div className="rounded-md border border-border bg-background/60 p-2">
                      <pre className="text-[11px] font-mono whitespace-pre-wrap break-all max-h-48 overflow-auto text-foreground/90">
{detail.last_log_tail.join("\n")}
                      </pre>
                      <div className="text-[10px] text-muted-foreground mt-2">
                        tail · {detail.last_log_size > 0 ? formatBytes(detail.last_log_size) : "—"}
                      </div>
                    </div>
                  ) : null}
                </section>

                {/* Destination — only the fields that apply to the
                    picked backend. No Schedule/Retention/Profile here
                    because manual jobs don't carry those. */}
                <section className="space-y-1">
                  <h4 className={`text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 ${destAccent}`}>
                    <HardDrive className="h-3.5 w-3.5" /> Destination
                  </h4>
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
                </section>
              </div>
            </ScrollArea>
          )}

        </DialogContent>
      </Dialog>
    </>
  )
}

// ──────────────────────────────────────────────────────────────
// PbsKeyfileRecoveryDialog
// ──────────────────────────────────────────────────────────────
// Drops the missing PBS keyfile back onto disk by pulling the escrow
// blob from a keyrecovery backup and decrypting it with the operator's
// recovery passphrase. Mirrors the shell's hb_pbs_try_keyfile_recovery
// flow. Triggered from the banner in DestinationsSection when the
// local keyfile is missing but at least one escrow backup is present
// on a configured PBS. The backend endpoint surfaces both the current
// `hostcfg-<host>-keyrecovery` and the legacy
// `proxmenux-keyrecovery-<host>` naming, so pre-1.2.2.2 escrow blobs
// stay recoverable without manual migration.
// ──────────────────────────────────────────────────────────────
function PbsKeyfileRecoveryDialog({
  open,
  snapshots,
  onClose,
  onRecovered,
}: {
  open: boolean
  snapshots: Array<{ repo_name: string; repo_repository: string; backup_id: string; source_host: string; backup_time: number; snapshot: string }>
  onClose: () => void
  onRecovered: () => void
}) {
  const [selectedKey, setSelectedKey] = useState<string>("")
  const [passphrase, setPassphrase] = useState<string>("")
  const [busy, setBusy] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setSelectedKey("")
      setPassphrase("")
      setBusy(false)
      setError(null)
      return
    }
    if (snapshots.length >= 1 && !selectedKey) {
      setSelectedKey(`${snapshots[0].repo_name}::${snapshots[0].snapshot}`)
    }
  }, [open, snapshots])

  const selected = snapshots.find((s) => `${s.repo_name}::${s.snapshot}` === selectedKey) || null

  async function handleRecover() {
    if (!selected || !passphrase) return
    setBusy(true)
    setError(null)
    try {
      await fetchApi("/api/host-backups/pbs-recovery/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_name: selected.repo_name,
          snapshot: selected.snapshot,
          passphrase,
        }),
      })
      onRecovered()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && !busy) onClose() }}>
      <DialogContent className="max-w-lg bg-card border-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Lock className="h-5 w-5 text-emerald-400" />
            Recover PBS keyfile
          </DialogTitle>
          <DialogDescription className="text-xs">
            The encrypted keyfile blob is downloaded from PBS and decrypted with your recovery passphrase. The resulting key is written to <code className="font-mono">/usr/local/share/proxmenux/pbs-key.conf</code>.
          </DialogDescription>
        </DialogHeader>

        {snapshots.length > 1 && (
          <div className="space-y-1">
            <Label className="text-xs">Recovery snapshot</Label>
            <Select value={selectedKey} onValueChange={setSelectedKey}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {snapshots.map((s) => {
                  let when: string
                  try { when = new Date(s.backup_time * 1000).toLocaleString() }
                  catch { when = String(s.backup_time) }
                  return (
                    <SelectItem key={`${s.repo_name}::${s.snapshot}`} value={`${s.repo_name}::${s.snapshot}`}>
                      <span className="font-mono">{s.source_host}</span>
                      <span className="text-muted-foreground ml-2">— {s.repo_name} · {when}</span>
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">
              Pick the source host whose passphrase you remember — each install uploads its own escrow.
            </p>
          </div>
        )}

        {selected && (
          <div className="text-xs space-y-1 px-3 py-2 rounded-md border border-border bg-background/40">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Source host:</span>
              <span className="font-mono">{selected.source_host}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">PBS:</span>
              <span className="font-mono break-all">{selected.repo_repository}</span>
            </div>
          </div>
        )}

        <div>
          <Label htmlFor="recoveryPass" className="text-xs">Recovery passphrase</Label>
          <Input
            id="recoveryPass"
            type="password"
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            placeholder="The passphrase set when the keyfile was created"
            className="font-mono mt-1"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && passphrase && !busy) handleRecover()
            }}
          />
        </div>

        {error && (
          <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            className="bg-green-600 hover:bg-green-700 text-white"
            disabled={!selected || !passphrase || busy}
            onClick={handleRecover}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Lock className="h-4 w-4 mr-2" />
            )}
            Recover keyfile
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ──────────────────────────────────────────────────────────────
// ArchiveContentsModal
// ──────────────────────────────────────────────────────────────
// "View contents" of any backup snapshot. Calls /inspect-archive
// (extract to staging + parse_manifest + run_restore dry-run +
// walk rootfs + cleanup) and renders the JSON as a HTML report.
// Same shape regardless of backend so the operator gets a
// consistent view across PBS, Borg and local.
// ──────────────────────────────────────────────────────────────

interface InspectResponse {
  manifest?: any
  manifest_error?: string
  manifest_missing?: boolean
  plan?: any
  plan_error?: string
  plan_raw_stderr?: string
  files?: Array<{ path: string; size: number }>
  files_truncated?: boolean
  files_total_count?: number
  metadata_files?: Record<string, string>
  rollback_plan?: RollbackPlan
}

interface RollbackPlan {
  backup_time?: string
  vms_in_backup: number[]
  vms_in_host: number[]
  vms_to_remove: number[]
  vms_to_restore: number[]
  lxcs_in_backup: number[]
  lxcs_in_host: number[]
  lxcs_to_remove: number[]
  lxcs_to_restore: number[]
  components_to_uninstall: string[]
  components_to_reinstall: string[]
}

function ArchiveContentsModal({
  open,
  onClose,
  source,
  repo_name,
  snapshot,
  path,
  display_id,
}: {
  open: boolean
  onClose: () => void
  source: "pbs" | "borg" | "local" | null
  repo_name?: string
  snapshot?: string
  path?: string
  display_id?: string
}) {
  const [data, setData] = useState<InspectResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !source) {
      setData(null)
      setError(null)
      setLoading(false)
      return
    }
    const body: Record<string, string> = { source }
    if (source === "local") {
      if (!path) { setError("Local archive path missing"); return }
      body.path = path
    } else {
      if (!repo_name || !snapshot) { setError("repo_name and snapshot required"); return }
      body.repo_name = repo_name
      body.snapshot = snapshot
    }
    setLoading(true)
    setError(null)
    fetchApi("/api/host-backups/inspect-archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r: any) => setData(r))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [open, source, repo_name, snapshot, path])

  const manifest = data?.manifest
  const plan = data?.plan
  const files = data?.files

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-4xl bg-card border-border h-[85vh] flex flex-col p-0">
        <DialogHeader className="px-6 pt-6 pb-3 shrink-0">
          <DialogTitle className="flex items-center gap-2 text-base">
            <Eye className="h-5 w-5 text-blue-400" />
            Backup contents
          </DialogTitle>
          <DialogDescription className="text-xs font-mono break-all">
            {display_id}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center gap-3 py-12 justify-center text-sm text-muted-foreground px-6">
            <Loader2 className="h-5 w-5 animate-spin" />
            Extracting snapshot and analyzing — this may take a minute on large backups…
          </div>
        )}

        {error && !loading && (
          <div className="text-sm text-red-400 px-3 py-3 mx-6 rounded-md border border-red-500/30 bg-red-500/10">
            {error}
          </div>
        )}

        {data && !loading && (
          <ScrollArea className="flex-1 min-h-0 px-6">
            <div className="space-y-4 pr-2">
              <ContentsSection icon={Info} title="Manifest" iconColor="text-blue-400">
                {manifest ? (
                  <ManifestGrid manifest={manifest} />
                ) : data.manifest_missing ? (
                  <div className="text-xs text-muted-foreground italic">
                    This backup doesn't include a manifest.json. Manifest is generated by the collectors pipeline (not yet wired into the backup runner). The Metadata files below carry the equivalent info: <code className="font-mono">run_info.env</code>, <code className="font-mono">pveversion.txt</code>, <code className="font-mono">selected_paths.txt</code>.
                  </div>
                ) : data.manifest_error ? (
                  <div className="text-xs text-amber-400">{data.manifest_error}</div>
                ) : (
                  <div className="text-xs text-muted-foreground italic">No manifest in this archive.</div>
                )}
              </ContentsSection>

              {(() => {
                // Only render plan/storage/network/drivers sections
                // when they actually carry information — otherwise
                // they read as "Unknown / No entries reported / No
                // changes planned" walls of noise.
                const blockers = plan?.preflight?.blockers || plan?.blockers || []
                const warnings = plan?.preflight?.warnings || plan?.warnings || []
                const planStatus = plan?.status || plan?.preflight?.status
                const planHasInfo = blockers.length > 0 || warnings.length > 0
                  || (planStatus && planStatus !== "unknown")
                const storageEntries = (plan?.storage?.entries || plan?.storage?.storages || [])
                const networkIfaces = (plan?.network?.interfaces || plan?.network?.remap || [])
                const driverList = (plan?.drivers?.plan || plan?.drivers?.components || plan?.drivers?.entries || [])
                return (
                  <>
                    {planHasInfo && (
                      <ContentsSection icon={ListTree} title="Restore plan" iconColor="text-emerald-400">
                        <PlanSummary plan={plan} />
                      </ContentsSection>
                    )}
                    {storageEntries.length > 0 && (
                      <ContentsSection icon={HardDrive} title="Storage" iconColor="text-amber-400">
                        <StorageSection storage={plan.storage} />
                      </ContentsSection>
                    )}
                    {networkIfaces.length > 0 && (
                      <ContentsSection icon={Network} title="Network" iconColor="text-purple-400">
                        <NetworkSection network={plan.network} />
                      </ContentsSection>
                    )}
                    {driverList.length > 0 && (
                      <ContentsSection icon={Cpu} title="Drivers to reinstall" iconColor="text-cyan-400">
                        <DriversSection drivers={plan.drivers} />
                      </ContentsSection>
                    )}
                  </>
                )
              })()}

              {data.rollback_plan && (
                <ContentsSection icon={History} title="Rollback plan" iconColor="text-blue-400">
                  <RollbackPlanView plan={data.rollback_plan} />
                </ContentsSection>
              )}

              {files && files.length > 0 && (
                <ContentsSection
                  icon={Package}
                  title={`Files (${data.files_total_count ?? files.length}${data.files_truncated ? "+" : ""})`}
                  iconColor="text-fuchsia-400"
                >
                  <FilesTree files={files} truncated={data.files_truncated} />
                </ContentsSection>
              )}

              {data.metadata_files && Object.keys(data.metadata_files).length > 0 && (
                <ContentsSection icon={FileText} title="Metadata files" iconColor="text-muted-foreground">
                  <div className="space-y-3">
                    {Object.entries(data.metadata_files).map(([fname, content]) => (
                      <div key={fname}>
                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 font-mono">{fname}</div>
                        <pre className="text-[11px] font-mono whitespace-pre-wrap break-all max-h-40 overflow-auto rounded border border-border bg-background/40 p-2 text-foreground/80">
                          {content}
                        </pre>
                      </div>
                    ))}
                  </div>
                </ContentsSection>
              )}

              {data.plan_error && !data.manifest_missing && (
                <div className="text-[11px] text-amber-400 italic">
                  Restore plan unavailable: {data.plan_error}
                </div>
              )}
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  )
}

function ContentsSection({
  icon: Icon,
  iconColor,
  title,
  children,
}: {
  icon: any
  iconColor?: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-md border border-border bg-background/40 p-3 space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
        <Icon className={`h-3.5 w-3.5 ${iconColor || "text-muted-foreground"}`} />
        {title}
      </h3>
      {children}
    </section>
  )
}

function ManifestGrid({ manifest }: { manifest: any }) {
  // The manifest follows the proxmenux_backup_manifest schema:
  //   {source_host: {hostname, pve_version, kernel, boot_mode, cpu_model, memory_kb, roles},
  //    hardware_inventory: {gpu, tpu, nic, wireless},
  //    storage_inventory: {zfs_pools, lvm, physical_disks, pve_storage_cfg, mounts},
  //    proxmenux_installed_components: [...],
  //    kernel_params: {...},
  //    vms_lxcs_at_backup: {vms, lxcs},
  //    backup_metadata: {paths_archived, encrypted, compression, ...},
  //    created_at, created_by}
  // So .source_host is an OBJECT — passing it raw to String() gave
  // the dreaded "[object Object]".
  const src = manifest.source_host || {}
  const meta = manifest.backup_metadata || {}
  const hw = manifest.hardware_inventory || {}
  const guests = manifest.vms_lxcs_at_backup || {}
  const rows: Array<[string, any]> = []
  const push = (k: string, v: any) => {
    if (v === undefined || v === null || v === "") return
    rows.push([k, v])
  }
  push("Source host", src.hostname || manifest.hostname)
  push("Created at", manifest.created_at || meta.created_at)
  push("Kernel", src.kernel || manifest.kernel)
  push("Proxmox version", src.pve_version || manifest.pve_version)
  push("Boot mode", src.boot_mode)
  push("CPU", src.cpu_model)
  push("Memory", src.memory_kb ? `${(src.memory_kb / 1024 / 1024).toFixed(1)} GB` : undefined)
  push("Roles", Array.isArray(src.roles) && src.roles.length ? src.roles.join(", ") : undefined)
  push("GPUs", Array.isArray(hw.gpu) && hw.gpu.length ? `${hw.gpu.length} device(s)` : undefined)
  push("NICs", Array.isArray(hw.nic) && hw.nic.length ? `${hw.nic.length} interface(s)` : undefined)
  push("VMs at backup", Array.isArray(guests.vms) ? guests.vms.length : undefined)
  push("LXCs at backup", Array.isArray(guests.lxcs) ? guests.lxcs.length : undefined)
  push("Compression", meta.compression)
  push("Encrypted", meta.encrypted === true ? "yes" : meta.encrypted === false ? "no" : undefined)
  push("Paths archived", Array.isArray(meta.paths_archived) ? `${meta.paths_archived.length} paths` : undefined)
  push("Built by", manifest.created_by)
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k}>
          <span className="text-muted-foreground">{k}:</span>{" "}
          <code className="font-mono text-foreground/90 break-all">{String(v)}</code>
        </div>
      ))}
    </div>
  )
}

function PlanSummary({ plan }: { plan: any }) {
  const status = plan.status || plan.preflight?.status || "unknown"
  const blockers: any[] = plan.preflight?.blockers || plan.blockers || []
  const warnings: any[] = plan.preflight?.warnings || plan.warnings || []
  const StatusIcon = status === "ok" ? CheckCircle2 : status === "warn" ? AlertTriangle : XCircle
  const statusColor = status === "ok" ? "text-emerald-400" : status === "warn" ? "text-amber-400" : "text-red-400"
  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <StatusIcon className={`h-4 w-4 ${statusColor}`} />
        <span className="font-medium capitalize">{status}</span>
      </div>
      {blockers.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-red-400 mb-1">Blockers</div>
          <ul className="space-y-0.5 ml-4 list-disc">
            {blockers.map((b, i) => (
              <li key={i} className="text-red-400">{typeof b === "string" ? b : (b.message || JSON.stringify(b))}</li>
            ))}
          </ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-amber-400 mb-1">Warnings</div>
          <ul className="space-y-0.5 ml-4 list-disc">
            {warnings.map((w, i) => (
              <li key={i} className="text-amber-400">{typeof w === "string" ? w : (w.message || JSON.stringify(w))}</li>
            ))}
          </ul>
        </div>
      )}
      {blockers.length === 0 && warnings.length === 0 && (
        <div className="text-muted-foreground italic">No blockers or warnings detected.</div>
      )}
    </div>
  )
}

function StorageSection({ storage }: { storage: any }) {
  const entries: any[] = storage.entries || storage.storages || []
  if (entries.length === 0) {
    return <div className="text-xs text-muted-foreground italic">No storage entries reported.</div>
  }
  return (
    <ul className="space-y-1 text-xs">
      {entries.map((e: any, i: number) => {
        const ok = e.status === "ok" || e.matches
        const Icon = ok ? CheckCircle2 : AlertTriangle
        const color = ok ? "text-emerald-400" : "text-amber-400"
        return (
          <li key={i} className="flex items-start gap-2">
            <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${color}`} />
            <div className="min-w-0 flex-1">
              <code className="font-mono">{e.name || e.storage || `entry ${i}`}</code>
              {e.type && <span className="text-muted-foreground ml-2">{e.type}</span>}
              {e.message && <div className="text-muted-foreground text-[11px]">{e.message}</div>}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function NetworkSection({ network }: { network: any }) {
  const ifaces: any[] = network.interfaces || network.remap || []
  if (ifaces.length === 0) {
    return <div className="text-xs text-muted-foreground italic">No interface changes planned.</div>
  }
  return (
    <ul className="space-y-1 text-xs">
      {ifaces.map((nic: any, i: number) => (
        <li key={i} className="flex items-start gap-2">
          <Network className="h-3.5 w-3.5 mt-0.5 shrink-0 text-purple-400" />
          <div className="min-w-0 flex-1">
            <code className="font-mono">{nic.source || nic.from || "?"}</code>
            <span className="text-muted-foreground mx-2">→</span>
            <code className="font-mono">{nic.target || nic.to || "?"}</code>
            {nic.action && <span className="text-[10px] text-muted-foreground ml-2">{nic.action}</span>}
          </div>
        </li>
      ))}
    </ul>
  )
}

function DriversSection({ drivers }: { drivers: any }) {
  const list: any[] = drivers.plan || drivers.components || drivers.entries || []
  if (list.length === 0) {
    return <div className="text-xs text-muted-foreground italic">No drivers to reinstall.</div>
  }
  return (
    <ul className="space-y-1 text-xs">
      {list.map((d: any, i: number) => (
        <li key={i} className="flex items-start gap-2">
          <Cpu className="h-3.5 w-3.5 mt-0.5 shrink-0 text-cyan-400" />
          <div className="min-w-0 flex-1">
            <code className="font-mono">{d.name || d.id || `driver ${i}`}</code>
            {d.action && <span className="text-muted-foreground ml-2">{d.action}</span>}
            {d.detail && <div className="text-muted-foreground text-[11px]">{d.detail}</div>}
          </div>
        </li>
      ))}
    </ul>
  )
}

function FilesTree({ files, truncated }: { files: Array<{ path: string; size: number }>; truncated?: boolean }) {
  const [query, setQuery] = useState("")
  const filtered = query
    ? files.filter((f) => f.path.toLowerCase().includes(query.toLowerCase()))
    : files
  return (
    <div className="space-y-2">
      <Input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter paths…"
        className="h-8 text-xs"
      />
      <div className="max-h-72 overflow-auto rounded border border-border bg-background/40">
        <ul className="text-[11px] font-mono divide-y divide-border/30">
          {filtered.slice(0, 2000).map((f) => (
            <li key={f.path} className="flex items-center justify-between gap-3 px-2 py-1 hover:bg-white/5">
              <span className="truncate" title={f.path}>{f.path}</span>
              <span className="text-muted-foreground shrink-0">{formatBytes(f.size)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="text-[10px] text-muted-foreground flex items-center gap-2">
        Showing {Math.min(filtered.length, 2000)} of {filtered.length}{query ? " filtered" : ""}{filtered.length !== files.length ? ` (total ${files.length})` : ""}
        {truncated && <span className="text-amber-400">· list truncated at 5000 — open the snapshot manually to see the rest</span>}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// RollbackPlanView
// ──────────────────────────────────────────────────────────────
// Visualizes what a "restore to backup state" would do — surfaces
// the irreversible parts (VMs/LXCs to delete, components to
// uninstall) in red, the safe re-apply parts in green. Drives the
// operator confirmation in the Complete restore flow.
// ──────────────────────────────────────────────────────────────
function RollbackPlanView({ plan }: { plan: RollbackPlan }) {
  // The destructive "Not in backup — will be deleted on rollback"
  // block was removed: operators read it as an action ProxMenux
  // would take silently. We only show the "Configurations included
  // in backup" section now, which is purely informative.
  const hasRollback = (plan.vms_to_restore?.length || 0) > 0
    || (plan.lxcs_to_restore?.length || 0) > 0
    || (plan.components_to_reinstall?.length || 0) > 0

  if (!hasRollback) {
    return (
      <div className="text-xs text-muted-foreground italic">
        No host-state differences detected — the backup state matches the current host (or the backup didn't include /etc/pve).
      </div>
    )
  }

  // Pill renders inline with proper flex wrapping so dozens of VM
  // IDs don't overflow the modal on mobile (previous version used
  // raw spaces between pills and any value past the viewport got
  // clipped).
  const Pill = ({ children }: { children: any }) => (
    <code className="font-mono px-1.5 py-0.5 rounded border bg-emerald-500/10 border-emerald-500/30 text-emerald-300 text-[11px]">
      {children}
    </code>
  )
  // Each pill is a direct flex child of the row (no inner wrapper)
  // so flex-wrap can break a long list of IDs mid-row on mobile.
  // The previous nested `<div className="flex flex-wrap">` wouldn't
  // wrap because its width was capped by the parent's flex layout,
  // and the whole block would overflow the modal instead.
  const Row = ({ label, items }: { label: string; items: (string | number)[] }) => (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1.5">
      <span className="text-muted-foreground shrink-0">{label}</span>
      {items.map((id) => <Pill key={id}>{id}</Pill>)}
    </div>
  )

  return (
    <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 space-y-2 text-xs">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
        Configurations included in backup
      </div>
      {plan.vms_to_restore.length > 0 && (
        <Row label="VM configs:" items={plan.vms_to_restore} />
      )}
      {plan.lxcs_to_restore.length > 0 && (
        <Row label="LXC configs:" items={plan.lxcs_to_restore} />
      )}
      {plan.components_to_reinstall.length > 0 && (
        <Row label="Components:" items={plan.components_to_reinstall} />
      )}
      <div className="text-[10px] text-muted-foreground pt-1">
        Only the /etc/pve config is restored — disk images stay where they live.
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// RestoreOptionsModal
// ──────────────────────────────────────────────────────────────
// Two-step UI for restoring a snapshot:
//   Step 1 — pick Complete restore vs Custom by paths.
//   Step 2 — if Custom, tick the paths to restore.
// `pathsAvailable` is what the backend's list_paths.sh detected
// in this specific backup (default profile + operator extras).
// Perfect parity with the TUI's _rs_select_component_paths after
// the paths-not-components refactor.
// ──────────────────────────────────────────────────────────────

function RestoreOptionsModal({
  open,
  onClose,
  stagingPath,
  pathsAvailable,
  rollbackPlan,
  crossKernel,
  hydration,
  display_id,
  onLaunch,
}: {
  open: boolean
  onClose: () => void
  stagingPath: string
  pathsAvailable: string[]
  rollbackPlan?: RollbackPlan
  crossKernel?: {
    direction: "same" | "bk_older" | "bk_newer"
    backupKernel: string
    targetKernel: string
    blockedPaths: string[]
  }
  hydration?: {
    applies: boolean
    actions: string[]
  }
  display_id?: string
  onLaunch: (mode: "full" | "custom", paths: string[], rollbackExecute?: boolean) => void
}) {
  // When direction === "bk_older" the CLI-side filter (RS_SKIP_PATHS)
  // will drop these prefixes from any restore. We mirror that
  // behavior in the picker so the operator can see what will be
  // skipped rather than being surprised at run time.
  const isBkOlder = crossKernel?.direction === "bk_older"
  const blockedPrefixes = isBkOlder ? (crossKernel?.blockedPaths ?? []) : []
  const isPathBlocked = (p: string) =>
    blockedPrefixes.some((b) => p === b || p.startsWith(b.endsWith("/") ? b : `${b}/`))
  const [step, setStep] = useState<"choose" | "custom">("choose")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>("")
  const [destructiveAck, setDestructiveAck] = useState<boolean>(false)

  // A Complete restore on a host that has VMs/LXCs/components NOT
  // present in the backup is destructive (those entries get removed
  // at next boot by apply_cluster_postboot.sh's rollback step). We
  // force the operator to tick an explicit "I understand" checkbox
  // before enabling the launch button.
  const hasDestructive = !!rollbackPlan && (
    (rollbackPlan.vms_to_remove?.length || 0) > 0
    || (rollbackPlan.lxcs_to_remove?.length || 0) > 0
    || (rollbackPlan.components_to_uninstall?.length || 0) > 0
  )

  useEffect(() => {
    if (!open) {
      setStep("choose")
      setSelected(new Set())
      setError(null)
      setFilter("")
      setDestructiveAck(false)
    }
  }, [open])

  const togglePath = (p: string) => {
    if (isPathBlocked(p)) return
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })
  }

  const toggleAll = () => {
    const selectable = filteredPaths.filter((p) => !isPathBlocked(p))
    if (selected.size === selectable.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(selectable))
    }
  }

  const filteredPaths = filter
    ? pathsAvailable.filter((p) => p.toLowerCase().includes(filter.toLowerCase()))
    : pathsAvailable
  const selectableCount = filteredPaths.filter((p) => !isPathBlocked(p)).length

  const launch = (mode: "full" | "custom") => {
    if (mode === "custom" && selected.size === 0) {
      setError("Pick at least one path to continue.")
      return
    }
    setError(null)
    onLaunch(mode, Array.from(selected), mode === "full" && hasDestructive && destructiveAck)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && step !== "preparing") onClose() }}>
      <DialogContent className="max-w-2xl bg-card border-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <DatabaseBackup className="h-5 w-5 text-emerald-400" />
            Restore — choose mode
          </DialogTitle>
          <DialogDescription className="text-xs font-mono break-all">
            {display_id}
          </DialogDescription>
        </DialogHeader>

        {step === "choose" && (
          <div className="space-y-3">
            {/* Post-restore Monitor hint — the Backups tab renders a live
                progress card driven by /var/lib/proxmenux/restore-state.json,
                so the operator has a place to watch component reinstalls,
                sanity warnings, and the rollback delta after the reboot. */}
            <div className="rounded-md border border-blue-500/40 bg-blue-500/5 p-3 text-[11px] text-muted-foreground flex items-start gap-2">
              <History className="h-3.5 w-3.5 text-blue-400 shrink-0 mt-0.5" />
              <div>
                After the reboot, this Backups tab will show a live post-restore progress card with estimated time, per-component status, log tail and rollback delta. If Telegram/Discord/ntfy notifications are configured, you'll also receive the "Host restore finished" event.
              </div>
            </div>

            {isBkOlder && (
              <div className="rounded-md border border-amber-500/50 bg-amber-500/5 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Cross-kernel restore — safe subset only
                </div>
                <div className="text-[11px] text-muted-foreground mt-2 space-y-1.5">
                  <div>
                    Backup kernel <code className="font-mono">{crossKernel?.backupKernel}</code> is older than target kernel <code className="font-mono">{crossKernel?.targetKernel}</code>.
                  </div>
                  <div>
                    Both Complete and Custom restore will automatically skip kernel/boot-tied paths to avoid a kernel panic on next boot. Everything else (VMs, LXCs, network, components, custom paths) restores normally.
                  </div>
                  {blockedPrefixes.length > 0 && (
                    <details className="mt-1.5">
                      <summary className="cursor-pointer text-amber-400/90 hover:text-amber-300">
                        Paths that will be skipped ({blockedPrefixes.length})
                      </summary>
                      <ul className="mt-1.5 pl-3 space-y-0.5 max-h-40 overflow-auto">
                        {blockedPrefixes.map((p) => (
                          <li key={p} className="font-mono text-[10.5px] text-muted-foreground/80 break-all">{p}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              </div>
            )}

            {isBkOlder && hydration?.applies && hydration.actions.length > 0 && (
              <div className="rounded-md border border-emerald-500/50 bg-emerald-500/5 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Operator config re-applied via kernel-agnostic merge
                </div>
                <div className="text-[11px] text-muted-foreground mt-2 space-y-1.5">
                  <div>
                    The following operator-authored settings will be merged into the target automatically, without touching kernel-tied defaults. Runs on both Complete and Custom restore.
                  </div>
                  <ul className="mt-1.5 pl-3 space-y-0.5 max-h-40 overflow-auto">
                    {hydration.actions.map((a, i) => (
                      <li key={`${a}-${i}`} className="text-[10.5px] text-emerald-300/90 break-all">
                        <span className="text-emerald-500 mr-1">•</span>{a}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {/* Surface destructive deltas BEFORE the operator picks
                Complete. Custom-by-paths can't trigger these
                (paths-only restore doesn't touch the guest list or
                components_status.json), so the warning lives here. */}
            {rollbackPlan && hasDestructive && (
              <div className="rounded-md border border-red-500/50 bg-red-500/5 p-3 space-y-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-red-400 flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Complete restore will REMOVE the following (created after the backup)
                </div>
                <RollbackPlanView plan={rollbackPlan} />
                <label className="flex items-start gap-2 cursor-pointer text-xs">
                  <Checkbox
                    checked={destructiveAck}
                    onCheckedChange={(v) => setDestructiveAck(!!v)}
                    className="mt-0.5"
                  />
                  <span className="text-foreground">
                    I understand that Complete restore will <strong className="text-red-400">permanently delete</strong> the VMs, LXCs and components listed above. This is irreversible.
                  </span>
                </label>
              </div>
            )}

            <button
              type="button"
              onClick={() => launch("full")}
              disabled={hasDestructive && !destructiveAck}
              className="w-full text-left p-4 rounded-md border border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div className="flex items-start gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">Complete restore</div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    Replays everything in the backup. Equivalent to picking <em>"Complete restore"</em> in the shell TUI menu. The terminal that opens next will still ask you to confirm safe-only vs safe+reboot vs all-at-once before touching the host.
                    {hasDestructive && !destructiveAck && (
                      <span className="block mt-1 text-red-400">Tick the acknowledgement above to enable.</span>
                    )}
                  </div>
                </div>
              </div>
            </button>

            <button
              type="button"
              onClick={() => setStep("custom")}
              disabled={pathsAvailable.length === 0}
              className="w-full text-left p-4 rounded-md border border-blue-500/40 bg-blue-500/5 hover:bg-blue-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div className="flex items-start gap-3">
                <ListTree className="h-5 w-5 text-blue-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">
                    Custom restore by paths
                    {pathsAvailable.length > 0 && (
                      <span className="ml-2 text-[10px] text-muted-foreground font-normal">
                        ({pathsAvailable.length} paths in backup)
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    {pathsAvailable.length === 0
                      ? "This backup carries no restorable paths — only Complete restore is meaningful here."
                      : "Pick exactly which paths to restore. Lists what's actually in this backup (default profile + your custom paths)."}
                  </div>
                </div>
              </div>
            </button>

            {error && (
              <div className="text-xs text-red-400 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
                {error}
              </div>
            )}
          </div>
        )}

        {step === "custom" && (
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground">
              Pick the paths to restore. Your selection feeds <code className="font-mono">_rs_run_custom_restore</code> via the <code className="font-mono">HB_PRESELECTED_PATHS</code> env var — same downstream code as the TUI. Reboot-required paths (kernel, modules, fstab, …) will be detected by the bash flow and you can schedule them for next boot from there.
            </p>
            <div className="flex items-center gap-2">
              <Input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter paths…"
                className="h-8 text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={toggleAll}
                className="h-8 text-xs whitespace-nowrap"
              >
                {selected.size === selectableCount && selectableCount > 0 ? "Clear" : "All"}
              </Button>
            </div>
            {isBkOlder && (
              <div className="text-[10.5px] text-amber-400/90 px-2 py-1.5 rounded border border-amber-500/30 bg-amber-500/5">
                Kernel/boot-tied paths are grayed out and cannot be selected — target runs a newer kernel.
              </div>
            )}
            <div className="rounded-md border border-border bg-background/40 p-1 max-h-72 overflow-auto">
              <ul className="divide-y divide-border/40">
                {filteredPaths.map((p) => {
                  const blocked = isPathBlocked(p)
                  return (
                    <li key={p}>
                      <label
                        className={`flex items-center gap-2 px-2 py-1 ${blocked ? "opacity-40 cursor-not-allowed" : "hover:bg-white/5 cursor-pointer"}`}
                        title={blocked ? "Skipped: kernel-tied path, target runs a newer kernel" : undefined}
                      >
                        <Checkbox
                          checked={!blocked && selected.has(p)}
                          disabled={blocked}
                          onCheckedChange={() => togglePath(p)}
                        />
                        <code className={`font-mono text-xs break-all flex-1 ${blocked ? "line-through" : ""}`}>{p}</code>
                        {blocked && (
                          <span className="text-[10px] text-amber-400/80 font-normal shrink-0">skipped</span>
                        )}
                      </label>
                    </li>
                  )
                })}
                {filteredPaths.length === 0 && (
                  <li className="text-[11px] text-muted-foreground italic px-2 py-2">No paths match the filter.</li>
                )}
              </ul>
            </div>
            <div className="text-[11px] text-muted-foreground">
              Selected: {selected.size} / {isBkOlder ? selectableCount : pathsAvailable.length}{filter && filteredPaths.length !== pathsAvailable.length ? ` (${filteredPaths.length} shown)` : ""}
            </div>
            {error && (
              <div className="text-xs text-red-400 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10">
                {error}
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2 border-t border-border">
          {step === "custom" && (
            <Button variant="ghost" onClick={() => setStep("choose")}>
              Back
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {step === "custom" && (
            <Button
              onClick={() => launch("custom")}
              disabled={selected.size === 0}
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              <DatabaseBackup className="h-4 w-4 mr-2" />
              Restore selected
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
