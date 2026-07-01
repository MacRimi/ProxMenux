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

// Trim the visible slider range to a window around the saved +
// recommended values so the track has usable resolution (e.g. CPU
// 60–100 instead of the backend's 0–100). Derived from stable inputs
// so the range does NOT shift under an active drag.
function computeVisualRange(
  values: number[],
  backendMin: number,
  backendMax: number,
  step: number,
): { min: number; max: number } {
  const totalRange = Math.max(1, backendMax - backendMin)
  // Margin ≈ 25% of total range, clamped to at least 5 steps so tiny
  // step sizes (e.g. step=1 on 0–100) still get a usable window.
  const rawMargin = Math.max(step * 5, Math.round(totalRange * 0.25))
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const snap = (n: number) => Math.round(n / step) * step
  let visMin = Math.max(backendMin, snap(lo - rawMargin))
  let visMax = Math.min(backendMax, snap(hi + rawMargin))
  // Ensure the window is at least 4 steps wide so the slider has
  // room to move even if all inputs collapse to one value.
  if (visMax - visMin < step * 4) {
    const mid = (visMax + visMin) / 2
    visMin = Math.max(backendMin, snap(mid - step * 2))
    visMax = Math.min(backendMax, snap(mid + step * 2))
  }
  return { min: visMin, max: visMax }
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
    // Kept for single-value leaves that don't have a warn/crit pair
    // (e.g. Memory's swap_critical). The pair-cases route to
    // renderThresholdRange below.
    const leaf = getLeaf(tree, path)
    if (!leaf) return null
    const key = pathKey(path)
    const editingValue = pending[key] ?? String(leaf.value)
    const last = path[path.length - 1] || ""
    const isCritical = last.toLowerCase().includes("critical")
    const isWarning = last.toLowerCase().includes("warning")
    const severityClass = isCritical
      ? "border-red-500/70 bg-red-500/10 focus-visible:border-red-500"
      : isWarning
        ? "border-amber-500/70 bg-amber-500/10 focus-visible:border-amber-500"
        : "border-input"
    const isCustomised = leaf.customised && !(key in pending)
    const customisedClass = "border-blue-500 bg-blue-500/10 focus-visible:border-blue-500"
    const fieldClass = isCustomised ? customisedClass : severityClass
    const recommendedTooltip = `Recommended: ${leaf.recommended}${leaf.unit}`
    return (
      <div key={key} className="flex items-center justify-between gap-2 py-1.5 px-1">
        <span className="text-xs sm:text-sm text-foreground/90 min-w-0">
          {label}
        </span>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Input
            type="number"
            min={leaf.min}
            max={leaf.max}
            step={leaf.step}
            disabled={!editMode}
            value={editingValue}
            title={recommendedTooltip}
            onChange={(e) =>
              setPending((p) => ({ ...p, [key]: e.target.value }))
            }
            className={`w-20 h-7 text-xs text-right tabular-nums border ${fieldClass} ${
              !editMode ? "disabled:opacity-100 disabled:cursor-default" : ""
            }`}
          />
          <span className="text-[11px] text-muted-foreground w-6">{leaf.unit}</span>
        </div>
      </div>
    )
  }

  // Single-handle slider for thresholds that don't have a warn/crit
  // pair (only Memory's swap_critical today). Same visual language as
  // the dual-handle: red handle, value above, OK / CRIT zones below
  // — so the operator doesn't read it as a different control.
  const renderSingleThresholdSlider = (path: string[], severity: "warning" | "critical" = "critical") => {
    const leaf = getLeaf(tree, path)
    if (!leaf) return null
    const key = pathKey(path)
    const val = Number(pending[key] ?? leaf.value)
    const step = leaf.step || 1
    const unit = leaf.unit || ""
    const { min, max } = computeVisualRange(
      [leaf.value, leaf.recommended],
      leaf.min,
      leaf.max,
      step,
    )
    const pct = ((Math.max(min, Math.min(max, val)) - min) / (max - min)) * 100
    const custom = leaf.customised && !(key in pending)
    const color = severity === "critical" ? "red" : "amber"
    const handleClass = severity === "critical"
      ? "[&::-webkit-slider-thumb]:bg-red-500 [&::-moz-range-thumb]:bg-red-500"
      : "[&::-webkit-slider-thumb]:bg-amber-500 [&::-moz-range-thumb]:bg-amber-500"
    const numberColor = custom
      ? "text-blue-400"
      : severity === "critical"
        ? "text-red-500"
        : "text-amber-500"
    const fillColor = severity === "critical" ? "bg-red-500/30" : "bg-amber-500/30"

    return (
      <div className="px-1 py-3">
        <div className="relative h-6 sm:h-5 mb-1 select-none">
          <span
            className={`absolute -translate-x-1/2 text-xs font-semibold tabular-nums ${numberColor}`}
            style={{ left: `${pct}%` }}
          >
            {val}{unit}
          </span>
        </div>
        <div className="relative h-9 sm:h-6">
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-muted" />
          <div
            className={`absolute top-1/2 -translate-y-1/2 h-1.5 rounded-r-full ${fillColor}`}
            style={{ left: `${pct}%`, right: 0 }}
          />
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            disabled={!editMode}
            value={val}
            onChange={(e) => setPending((p) => ({ ...p, [key]: e.target.value }))}
            className={`absolute inset-0 w-full appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-8 [&::-webkit-slider-thumb]:w-8 sm:[&::-webkit-slider-thumb]:h-4 sm:[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background [&::-webkit-slider-thumb]:shadow [&::-moz-range-thumb]:h-8 [&::-moz-range-thumb]:w-8 sm:[&::-moz-range-thumb]:h-4 sm:[&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-background ${handleClass}`}
            title={`Recommended: ${leaf.recommended}${unit}`}
          />
        </div>
        <div className="grid grid-cols-2 gap-2 mt-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
          <span>OK &lt; {val}{unit}</span>
          <span className="text-right">{severity === "critical" ? "CRIT" : "WARN"} &gt; {val}{unit}</span>
        </div>
      </div>
    )
  }

  // Dual-handle range slider replacing the two stacked number inputs
  // for warn/crit pairs. Visual model: a horizontal track split into
  // three zones — OK (left of warning, muted), WARN→CRIT (between
  // handles, amber-to-red gradient), and OVER-CRIT (right of critical,
  // dark red overlay). The handles themselves stay coloured (amber for
  // warning, red for critical) so the operator reads the same severity
  // mapping they're used to from the old inputs. Numbers ride above
  // each handle and double as a click-to-edit affordance — clicking a
  // number swaps it for a tight `<Input type="number">` so precise
  // values are still keyboard-friendly. Customised values surface as a
  // small blue dot on the affected handle (same signal as the old blue
  // ring, less visual weight).
  const renderThresholdRange = (
    basePath: string[],
    options?: { hideLabels?: boolean }
  ) => {
    const wPath = [...basePath, "warning"]
    const cPath = [...basePath, "critical"]
    const wLeaf = getLeaf(tree, wPath)
    const cLeaf = getLeaf(tree, cPath)
    if (!wLeaf || !cLeaf) return null

    const wKey = pathKey(wPath)
    const cKey = pathKey(cPath)
    const wVal = Number(pending[wKey] ?? wLeaf.value)
    const cVal = Number(pending[cKey] ?? cLeaf.value)

    // Backend validates warning <= critical on save.
    const step = Math.max(wLeaf.step, cLeaf.step) || 1
    const backendMin = Math.min(wLeaf.min, cLeaf.min)
    const backendMax = Math.max(wLeaf.max, cLeaf.max)
    const { min, max } = computeVisualRange(
      [wLeaf.value, cLeaf.value, wLeaf.recommended, cLeaf.recommended],
      backendMin,
      backendMax,
      step,
    )
    const pct = (v: number) => ((Math.max(min, Math.min(max, v)) - min) / (max - min)) * 100
    const wPct = pct(wVal)
    const cPct = pct(cVal)
    const unit = wLeaf.unit || cLeaf.unit || ""

    const wCustom = wLeaf.customised && !(wKey in pending)
    const cCustom = cLeaf.customised && !(cKey in pending)

    const setVal = (key: string, value: number, peer: number, isWarn: boolean) => {
      // Clamp on the fly: warning can't cross critical and vice-versa,
      // matching the backend invariant so the user can't drag into an
      // invalid state.
      let v = value
      if (isWarn && v >= peer) v = peer - step
      if (!isWarn && v <= peer) v = peer + step
      setPending((p) => ({ ...p, [key]: String(v) }))
    }

    return (
      <div className="px-1 py-3">
        {/* Numeric labels above each handle, positioned absolutely so
            they ride above the corresponding thumb regardless of the
            slider width. Pointer events disabled so they don't steal
            clicks from the underlying range inputs. */}
        <div className="relative h-6 sm:h-5 mb-1 select-none">
          <span
            className={`absolute -translate-x-1/2 text-xs font-semibold tabular-nums ${wCustom ? "text-blue-400" : "text-amber-500"}`}
            style={{ left: `${wPct}%` }}
          >
            {wVal}{unit}
          </span>
          <span
            className={`absolute -translate-x-1/2 text-xs font-semibold tabular-nums ${cCustom ? "text-blue-400" : "text-red-500"}`}
            style={{ left: `${cPct}%` }}
          >
            {cVal}{unit}
          </span>
        </div>

        {/* Two range inputs stacked. Mobile track box is taller so the
            enlarged thumbs (h-7) have room to sit without clipping. */}
        <div className="relative h-9 sm:h-6">
          {/* Background track: OK zone (muted) running the full width */}
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-muted" />
          {/* Warn-to-Crit gradient between the two handles */}
          <div
            className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full"
            style={{
              left: `${wPct}%`,
              width: `${Math.max(0, cPct - wPct)}%`,
              background: "linear-gradient(90deg, rgb(245 158 11), rgb(239 68 68))",
            }}
          />
          {/* OVER-CRIT zone (right of critical) — solid red dim */}
          <div
            className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-r-full bg-red-500/30"
            style={{ left: `${cPct}%`, right: 0 }}
          />
          {/* Two superposed range inputs. Pointer-events on the thumb
              only, so the inert track bar above stays visible. */}
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            disabled={!editMode}
            value={wVal}
            onChange={(e) => setVal(wKey, Number(e.target.value), cVal, true)}
            className="absolute inset-0 w-full appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-8 [&::-webkit-slider-thumb]:w-8 sm:[&::-webkit-slider-thumb]:h-4 sm:[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-amber-500 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background [&::-webkit-slider-thumb]:shadow [&::-moz-range-thumb]:h-8 [&::-moz-range-thumb]:w-8 sm:[&::-moz-range-thumb]:h-4 sm:[&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-amber-500 [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-background"
            title={`Warning (recommended: ${wLeaf.recommended}${unit})`}
          />
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            disabled={!editMode}
            value={cVal}
            onChange={(e) => setVal(cKey, Number(e.target.value), wVal, false)}
            className="absolute inset-0 w-full appearance-none bg-transparent pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-8 [&::-webkit-slider-thumb]:w-8 sm:[&::-webkit-slider-thumb]:h-4 sm:[&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-red-500 [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background [&::-webkit-slider-thumb]:shadow [&::-moz-range-thumb]:h-8 [&::-moz-range-thumb]:w-8 sm:[&::-moz-range-thumb]:h-4 sm:[&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-red-500 [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-background"
            title={`Critical (recommended: ${cLeaf.recommended}${unit})`}
          />
        </div>

        {/* Zone labels — explicit ranges so the operator knows where
            "warn" starts and ends without having to read the handles. */}
        {!options?.hideLabels && (
          <div className="grid grid-cols-3 gap-2 mt-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            <span>OK &lt; {wVal}{unit}</span>
            <span className="text-center">WARN {wVal}–{cVal}{unit}</span>
            <span className="text-right">CRIT &gt; {cVal}{unit}</span>
          </div>
        )}
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
          Drag the amber handle to set the warning level and the red handle to set the
          critical level. Values that differ from the recommended default appear in blue —
          hover a handle to see the recommendation, or use Reset to restore it.
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
          <div>
            {error && (
              <div className="mb-4 flex items-start gap-2 p-2.5 rounded-md bg-red-500/10 border border-red-500/30 text-red-500 text-xs">
                <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <div className="flex-1">{error}</div>
              </div>
            )}

            {/*
              Masonry-style flow via CSS columns: cards keep their natural
              height (CPU = 2 rows, Disk temperature = 8 rows) and the
              browser packs them top-to-bottom into 1/2/3 columns based on
              viewport. `break-inside-avoid` keeps each card whole.
              Mobile (<md) stays single-column as today.
            */}
            <div className="columns-1 md:columns-2 2xl:columns-3 gap-4 space-y-4 [&>*]:break-inside-avoid">
            {SECTIONS.map((section) => {
              const Icon = section.icon
              return (
                <div key={section.id} className="rounded-md border border-border/50 px-3 py-2">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <h4 className="text-sm font-medium">{section.title}</h4>
                    </div>
                    {editMode && (
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
                  <div>
                    {section.rowGroups ? (
                      // Per-class disk temperature: one slider per row
                      // (HDD / SSD / NVMe / SAS). Group label sits on
                      // top of each slider so the operator scans the
                      // column from top down without losing context.
                      section.rowGroups.map((group) => (
                        <div key={group.subKey} className="py-1.5 border-b border-border/40 last:border-b-0">
                          <div className="text-[11px] uppercase tracking-wider text-muted-foreground px-1">
                            {group.label}
                          </div>
                          {renderThresholdRange([section.id, group.subKey])}
                        </div>
                      ))
                    ) : section.id === "memory" ? (
                      // Memory & Swap is special: warn/crit pair for
                      // RAM, plus a single Swap threshold that has no
                      // companion (it's a "critical only" metric).
                      // Both use sliders so the section reads as one
                      // visual language end to end.
                      <>
                        <div className="text-[11px] uppercase tracking-wider text-muted-foreground px-1">
                          RAM
                        </div>
                        {renderThresholdRange(["memory"])}
                        <div className="border-t border-border/40">
                          <div className="text-[11px] uppercase tracking-wider text-muted-foreground px-1 pt-1.5">
                            Swap (critical only)
                          </div>
                          {renderSingleThresholdSlider(["memory", "swap_critical"], "critical")}
                        </div>
                      </>
                    ) : section.fields.length === 2 &&
                      section.fields[0].path[section.fields[0].path.length - 1] === "warning" &&
                      section.fields[1].path[section.fields[1].path.length - 1] === "critical" ? (
                      // Generic warn+crit pair (CPU, CPU temp, storage
                      // capacities …) → single slider.
                      renderThresholdRange([section.id])
                    ) : (
                      // Fallback for any future section shape — keep
                      // the original per-field number inputs.
                      <div className="divide-y divide-border/40">
                        {section.fields.map((f) => renderField(f.path, f.label))}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
