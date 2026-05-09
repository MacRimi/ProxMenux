"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import {
  SlidersHorizontal,
  Cpu,
  MemoryStick,
  HardDrive,
  Server,
  Thermometer,
  Settings2,
  Check,
  Loader2,
  RotateCcw,
  AlertCircle,
  FolderOpen,
  Database,
  Waves,
} from "lucide-react"
import { getApiUrl, getAuthToken } from "../lib/api-config"

// Local fetch wrapper that *preserves* the JSON body on non-2xx
// responses so we can surface backend validation messages
// (e.g. "critical must be >= warning") to the user. The shared
// `fetchApi` throws a generic "API request failed: 400" on any
// non-OK response, eating the body.
async function fetchJson<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  }
  if (token) headers["Authorization"] = `Bearer ${token}`
  const res = await fetch(getApiUrl(endpoint), {
    ...init,
    headers,
    cache: "no-store",
  })
  let data: any = null
  try {
    data = await res.json()
  } catch {
    // empty body — fall through with raw status
  }
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      try {
        localStorage.removeItem("proxmenux-auth-token")
      } catch {}
      const path = window.location.pathname
      if (!path.startsWith("/auth") && !path.startsWith("/login")) {
        window.location.assign("/")
      }
    }
    const msg =
      (data && (data.message || data.error)) ||
      `${res.status} ${res.statusText}`
    throw new Error(msg)
  }
  return data as T
}

// ─── Types ───────────────────────────────────────────────────────────────────
//
// The backend returns a tree of leaves. Each leaf carries the metadata
// the UI needs to render an input + the recommended/customised flags.
// We mirror the shape rather than hand-coding it to keep the contract
// in one place — the backend is the source of truth.
interface ThresholdLeaf {
  value: number
  recommended: number
  customised: boolean
  unit: string
  min: number
  max: number
  step: number
}

interface ThresholdsTree {
  cpu: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  memory: { warning: ThresholdLeaf; critical: ThresholdLeaf; swap_critical: ThresholdLeaf }
  host_storage: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  lxc_rootfs: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  cpu_temperature: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  disk_temperature: {
    hdd: { warning: ThresholdLeaf; critical: ThresholdLeaf }
    ssd: { warning: ThresholdLeaf; critical: ThresholdLeaf }
    nvme: { warning: ThresholdLeaf; critical: ThresholdLeaf }
    sas: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  }
  // Phase 3 additions
  lxc_mount: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  pve_storage: { warning: ThresholdLeaf; critical: ThresholdLeaf }
  zfs_pool: { warning: ThresholdLeaf; critical: ThresholdLeaf }
}

// Pending edits: { "section/key" : "76" } — kept as raw strings while
// the user types so partial input ("8" mid-type) doesn't fail the
// numeric coercion. Coerced + validated on Save.
type PendingEdits = Record<string, string>

// ─── Section descriptors ─────────────────────────────────────────────────────
//
// Drives both the render order and the labels. Keeping it data-only
// means adding a new section later (Phase 4) is one entry, not a JSX
// surgery.
interface SectionField {
  // Path in the thresholds tree, e.g. ["cpu", "warning"] or
  // ["disk_temperature", "nvme", "critical"].
  path: string[]
  label: string
}

interface SectionDef {
  id: string         // Backend section key — used by the reset endpoint
  title: string
  icon: React.ComponentType<{ className?: string }>
  description?: string
  fields: SectionField[]
  // For tabular sections (disk temperature) we group by sub-key. When
  // present, fields are rendered in a 2-column grid (warning, critical)
  // labelled by sub-key (HDD / SSD / NVMe / SAS).
  rowGroups?: Array<{ subKey: string; label: string }>
}

// Order: compute → heat → storage capacity. Reading top-to-bottom
// flows naturally with no domain jumps:
//   • Compute (CPU usage, RAM/Swap)
//   • Heat (CPU temp, then disk temp — both °C)
//   • Storage capacity (host → LXC rootfs → LXC mounts → PVE → ZFS,
//     i.e. concrete to abstract)
const SECTIONS: SectionDef[] = [
  // ── Compute ─────────────────────────────────────────────────────
  {
    id: "cpu",
    title: "CPU usage",
    icon: Cpu,
    fields: [
      { path: ["cpu", "warning"], label: "Warning" },
      { path: ["cpu", "critical"], label: "Critical" },
    ],
  },
  {
    id: "memory",
    title: "Memory & Swap",
    icon: MemoryStick,
    fields: [
      { path: ["memory", "warning"], label: "Memory warning" },
      { path: ["memory", "critical"], label: "Memory critical" },
      { path: ["memory", "swap_critical"], label: "Swap critical" },
    ],
  },
  // ── Heat ────────────────────────────────────────────────────────
  {
    id: "cpu_temperature",
    title: "CPU temperature",
    icon: Thermometer,
    fields: [
      { path: ["cpu_temperature", "warning"], label: "Warning" },
      { path: ["cpu_temperature", "critical"], label: "Critical" },
    ],
  },
  {
    id: "disk_temperature",
    title: "Disk temperature",
    icon: Thermometer,
    description:
      "Per-class thresholds. Same units (°C) — different defaults because each class tolerates a different envelope.",
    rowGroups: [
      { subKey: "hdd", label: "HDD" },
      { subKey: "ssd", label: "SSD" },
      { subKey: "nvme", label: "NVMe" },
      { subKey: "sas", label: "SAS" },
    ],
    // For row-group sections, `fields` is unused — we generate per-row
    // path lookups from the rowGroups + a hardcoded ["warning","critical"].
    fields: [],
  },
  // ── Storage capacity ────────────────────────────────────────────
  {
    id: "host_storage",
    title: "Disk space — host",
    icon: HardDrive,
    description: "Applies to / and every mountpoint under /var/lib/vz, /mnt/* etc.",
    fields: [
      { path: ["host_storage", "warning"], label: "Warning" },
      { path: ["host_storage", "critical"], label: "Critical" },
    ],
  },
  {
    id: "lxc_rootfs",
    title: "Disk space — LXC rootfs",
    icon: Server,
    description: "Per-container root disk, evaluated against the rootfs size from PVE.",
    fields: [
      { path: ["lxc_rootfs", "warning"], label: "Warning" },
      { path: ["lxc_rootfs", "critical"], label: "Critical" },
    ],
  },
  {
    id: "lxc_mount",
    title: "LXC mount points",
    icon: FolderOpen,
    description:
      "Capacity of mountpoints inside running CTs (mp0, mp1, NFS, bind mounts). Excludes the rootfs — that's covered above.",
    fields: [
      { path: ["lxc_mount", "warning"], label: "Warning" },
      { path: ["lxc_mount", "critical"], label: "Critical" },
    ],
  },
  {
    id: "pve_storage",
    title: "PVE storage capacity",
    icon: Database,
    description:
      "Block-style PVE storages: LVM, LVM-thin, ZFS-pool, RBD/Ceph, PBS. Filesystem-style (dir/nfs/cifs) is already covered by host disk thresholds.",
    fields: [
      { path: ["pve_storage", "warning"], label: "Warning" },
      { path: ["pve_storage", "critical"], label: "Critical" },
    ],
  },
  {
    id: "zfs_pool",
    title: "ZFS pool capacity",
    icon: Waves,
    description:
      "ZFS pools at the host level — independent of PVE registration so rpool and dedicated backup pools are also monitored.",
    fields: [
      { path: ["zfs_pool", "warning"], label: "Warning" },
      { path: ["zfs_pool", "critical"], label: "Critical" },
    ],
  },
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getLeaf(tree: ThresholdsTree | null, path: string[]): ThresholdLeaf | null {
  if (!tree) return null
  let node: any = tree
  for (const p of path) {
    if (node == null || typeof node !== "object") return null
    node = node[p]
  }
  return node as ThresholdLeaf | null
}

function pathKey(path: string[]): string {
  return path.join("/")
}

// ─── Component ───────────────────────────────────────────────────────────────

export function HealthThresholds() {
  const [tree, setTree] = useState<ThresholdsTree | null>(null)
  const [loading, setLoading] = useState(true)
  const [editMode, setEditMode] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingEdits>({})

  // Load on mount + auto-refresh after each save
  const fetchTree = async () => {
    try {
      setLoading(true)
      const res = await fetchJson<{ success: boolean; thresholds: ThresholdsTree }>(
        "/api/health/thresholds",
      )
      if (res?.success && res.thresholds) setTree(res.thresholds)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load thresholds")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTree()
  }, [])

  const hasPendingChanges = Object.keys(pending).length > 0

  // Build the partial payload from pending. Any blank or unparseable
  // entry is skipped — the backend will reject anything malformed
  // anyway, but we want to fail fast on the UI side too.
  const buildPayload = (): Record<string, any> | null => {
    const payload: Record<string, any> = {}
    for (const [key, raw] of Object.entries(pending)) {
      const parts = key.split("/")
      const trimmed = raw.trim()
      if (trimmed === "") continue
      const num = Number(trimmed)
      if (!isFinite(num)) {
        setError(`Invalid value for ${key}: must be a number`)
        return null
      }
      // Walk into payload mirroring the path
      let cur: any = payload
      for (let i = 0; i < parts.length - 1; i++) {
        cur[parts[i]] = cur[parts[i]] || {}
        cur = cur[parts[i]]
      }
      cur[parts[parts.length - 1]] = num
    }
    return payload
  }

  const handleEdit = () => {
    setEditMode(true)
    setError(null)
  }

  const handleCancel = () => {
    setEditMode(false)
    setPending({})
    setError(null)
  }

  const handleSave = async () => {
    const payload = buildPayload()
    if (payload === null) return
    if (Object.keys(payload).length === 0) {
      setEditMode(false)
      return
    }
    try {
      setSaving(true)
      setError(null)
      const data = await fetchJson<{ success: boolean; thresholds: ThresholdsTree; message?: string }>(
        "/api/health/thresholds",
        { method: "PUT", body: JSON.stringify(payload) },
      )
      if (!data.success || !data.thresholds) {
        setError(data.message || "Save failed")
        return
      }
      setTree(data.thresholds)
      setPending({})
      setEditMode(false)
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Network error while saving")
    } finally {
      setSaving(false)
    }
  }

  const handleResetSection = async (sectionId: string) => {
    if (!confirm(`Reset all "${SECTIONS.find((s) => s.id === sectionId)?.title}" thresholds to recommended values?`))
      return
    try {
      const data = await fetchJson<{ success: boolean; thresholds: ThresholdsTree; message?: string }>(
        `/api/health/thresholds/reset?section=${encodeURIComponent(sectionId)}`,
        { method: "POST" },
      )
      if (!data.success || !data.thresholds) {
        setError(data.message || "Reset failed")
        return
      }
      setTree(data.thresholds)
      // Drop any pending edits within this section so the UI stays
      // consistent — the values were just reset on the server.
      setPending((p) => {
        const next: PendingEdits = {}
        for (const [k, v] of Object.entries(p)) {
          if (!k.startsWith(sectionId + "/")) next[k] = v
        }
        return next
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Network error while resetting")
    }
  }

  const handleResetAll = async () => {
    if (!confirm("Reset ALL thresholds to recommended values? This affects every section.")) return
    try {
      const data = await fetchJson<{ success: boolean; thresholds: ThresholdsTree; message?: string }>(
        "/api/health/thresholds/reset",
        { method: "POST" },
      )
      if (!data.success || !data.thresholds) {
        setError(data.message || "Reset failed")
        return
      }
      setTree(data.thresholds)
      setPending({})
    } catch (err) {
      setError(err instanceof Error ? err.message : "Network error while resetting")
    }
  }

  const renderField = (path: string[], label: string) => {
    const leaf = getLeaf(tree, path)
    if (!leaf) return null
    const key = pathKey(path)
    const editingValue = pending[key] ?? String(leaf.value)
    // Pick the badge palette from the leaf name so warning rows render
    // amber and critical rows render red. `swap_critical` and any other
    // *_critical key fall into the red bucket via the substring check.
    const last = path[path.length - 1] || ""
    const isCritical = last.toLowerCase().includes("critical")
    const isWarning = last.toLowerCase().includes("warning")
    const badgeClasses = isCritical
      ? "bg-red-500/10 text-red-500 border-red-500/30"
      : isWarning
        ? "bg-amber-500/10 text-amber-500 border-amber-500/30"
        : "bg-muted text-muted-foreground border-border"
    return (
      <div key={key} className="flex items-center justify-between gap-2 py-1.5 px-1">
        <span className="text-xs sm:text-sm text-foreground/90 min-w-0 flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-blue-500 flex-shrink-0" aria-hidden="true" />
          {label}
        </span>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span
            className={`inline-flex items-center justify-center h-6 px-2 rounded-md border text-[11px] font-mono tabular-nums ${badgeClasses}`}
            title="Recommended default value"
          >
            {leaf.recommended}
            {leaf.unit}
          </span>
          <Input
            type="number"
            min={leaf.min}
            max={leaf.max}
            step={leaf.step}
            disabled={!editMode}
            value={editingValue}
            onChange={(e) =>
              setPending((p) => ({ ...p, [key]: e.target.value }))
            }
            className={`w-20 h-7 text-xs text-right tabular-nums ${
              !editMode ? "opacity-70" : ""
            } ${
              leaf.customised && !(key in pending) ? "border-blue-500/40" : ""
            }`}
          />
          <span className="text-[11px] text-muted-foreground w-6">{leaf.unit}</span>
        </div>
      </div>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <SlidersHorizontal className="h-5 w-5 text-amber-500" />
            <CardTitle>Health Monitor Thresholds</CardTitle>
          </div>
          {!loading && (
            <div className="flex items-center gap-2">
              {savedFlash && (
                <span className="flex items-center gap-1 text-xs text-green-500">
                  <Check className="h-3.5 w-3.5" />
                  Saved
                </span>
              )}
              {editMode ? (
                <>
                  <button
                    className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground"
                    onClick={handleCancel}
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    onClick={handleSave}
                    disabled={saving || !hasPendingChanges}
                  >
                    {saving ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Check className="h-3 w-3" />
                    )}
                    Save
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground flex items-center gap-1.5"
                    onClick={handleResetAll}
                    title="Reset every threshold to its recommended value"
                  >
                    <RotateCcw className="h-3 w-3" />
                    Reset all
                  </button>
                  <button
                    className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5"
                    onClick={handleEdit}
                  >
                    <Settings2 className="h-3 w-3" />
                    Edit
                  </button>
                </>
              )}
            </div>
          )}
        </div>
        <CardDescription>
          The Health Monitor and notifications fire when these thresholds are crossed.
          Recommended values are shown with their reference color (amber for warning,
          red for critical); your edits override them. Leave a value unchanged to keep
          the recommended.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !tree ? (
          <div className="text-sm text-muted-foreground">Failed to load thresholds.</div>
        ) : (
          <div className="space-y-4">
            {error && (
              <div className="flex items-start gap-2 p-2.5 rounded-md bg-red-500/10 border border-red-500/30 text-red-500 text-xs">
                <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <div className="flex-1">{error}</div>
              </div>
            )}

            {SECTIONS.map((section) => {
              const Icon = section.icon
              return (
                <div key={section.id} className="rounded-md border border-border/50 px-3 py-2">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <h4 className="text-sm font-medium">{section.title}</h4>
                    </div>
                    {!editMode && (
                      <button
                        className="h-6 w-6 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors flex items-center justify-center"
                        onClick={() => handleResetSection(section.id)}
                        title="Reset this section to recommended"
                      >
                        <RotateCcw className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                  {section.description && (
                    <p className="text-[11px] text-muted-foreground mb-1.5 leading-snug">
                      {section.description}
                    </p>
                  )}
                  <div className="divide-y divide-border/40">
                    {section.rowGroups
                      ? section.rowGroups.map((group) => (
                          <div key={group.subKey} className="py-1.5">
                            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-0.5 px-1">
                              {group.label}
                            </div>
                            {renderField([section.id, group.subKey, "warning"], "Warning")}
                            {renderField([section.id, group.subKey, "critical"], "Critical")}
                          </div>
                        ))
                      : section.fields.map((f) => renderField(f.path, f.label))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
