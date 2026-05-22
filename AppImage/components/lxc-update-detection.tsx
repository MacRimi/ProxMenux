"use client"

import { useEffect, useState } from "react"
import { Boxes, Info, Loader2, Settings2, CheckCircle2 } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { fetchApi } from "../lib/api-config"

interface DetectionResponse {
  success: boolean
  enabled?: boolean
  message?: string
  purged?: number
}

export function LxcUpdateDetection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [enabled, setEnabled] = useState<boolean>(true)
  const [pending, setPending] = useState<boolean>(true)
  const [editMode, setEditMode] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [lastPurged, setLastPurged] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchApi<DetectionResponse>("/api/lxc-updates/detection")
      .then(data => {
        if (cancelled) return
        if (data.success && typeof data.enabled === "boolean") {
          setEnabled(data.enabled)
          setPending(data.enabled)
        } else {
          setError(data.message || "Failed to load setting")
        }
      })
      .catch(e => {
        if (!cancelled) setError(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const hasChanges = pending !== enabled

  function handleEdit() {
    setEditMode(true)
    setError(null)
    setSaved(false)
    setLastPurged(null)
  }

  function handleCancel() {
    setPending(enabled)
    setEditMode(false)
    setError(null)
    setLastPurged(null)
  }

  async function handleSave() {
    if (!hasChanges) {
      setEditMode(false)
      return
    }
    setSaving(true)
    setError(null)
    setSaved(false)
    setLastPurged(null)
    try {
      const data = await fetchApi<DetectionResponse>("/api/lxc-updates/detection", {
        method: "POST",
        body: JSON.stringify({ enabled: pending }),
      })
      if (!data.success) {
        setError(data.message || "Failed to save setting")
        return
      }
      setEnabled(pending)
      setEditMode(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      if (!pending && typeof data.purged === "number" && data.purged > 0) {
        setLastPurged(data.purged)
      }
      // Notify the Notifications section so it hides/shows the
      // lxc_updates_available toggle in real time.
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("proxmenux:lxc-detection-changed", { detail: { enabled: pending } }),
        )
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Boxes className="h-5 w-5 text-purple-500" />
            <CardTitle>LXC Update Detection</CardTitle>
            {enabled ? (
              <Badge variant="outline" className="text-[10px] border-green-500/30 text-green-500">
                Active
              </Badge>
            ) : (
              <Badge variant="outline" className="text-[10px] border-muted-foreground/30 text-muted-foreground">
                Disabled
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-xs text-green-500">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Saved
              </span>
            )}
            {error && !editMode && (
              <span
                className="flex items-center gap-1 text-xs text-red-500 max-w-[40ch] truncate"
                title={error}
              >
                Save failed: {error}
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
                  disabled={saving || !hasChanges}
                >
                  {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                  Save
                </button>
              </>
            ) : (
              <button
                className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5"
                onClick={handleEdit}
                disabled={loading}
              >
                <Settings2 className="h-3 w-3" />
                Edit
              </button>
            )}
          </div>
        </div>
        <CardDescription>
          Periodically check running Debian/Ubuntu/Alpine LXC containers for pending package updates
          (<code>apt list --upgradable</code> / <code>apk list -u</code>) and surface them on the dashboard. The
          corresponding notification toggle in <strong>Notifications → Services</strong> appears only while detection
          is enabled.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* ── Enable/Disable ── */}
        <div className="flex items-center justify-between py-2 px-1">
          <div className="flex items-center gap-2">
            <Boxes
              className={`h-4 w-4 ${pending ? "text-purple-500" : "text-muted-foreground"}`}
            />
            <div>
              <span className="text-sm font-medium">Enable LXC update detection</span>
              <p className="text-[11px] text-muted-foreground">
                When OFF, ProxMenux stops scanning your CTs (no <code>pct exec</code> calls), removes existing LXC
                entries from the managed-installs registry, and hides the related notification toggle. Default is
                ON.
              </p>
            </div>
          </div>
          <button
            className={`relative w-10 h-5 rounded-full transition-colors ${
              pending ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
            } ${!editMode ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
            onClick={() => editMode && setPending(p => !p)}
            disabled={!editMode || saving}
            role="switch"
            aria-checked={pending}
            aria-label="Enable LXC update detection"
          >
            <span
              className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                pending ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {lastPurged !== null && lastPurged > 0 && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-muted/50 border border-border">
            <Info className="h-3.5 w-3.5 text-blue-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {lastPurged} LXC entries removed from the registry. Re-enabling detection will repopulate them on the
              next scan cycle.
            </p>
          </div>
        )}

        {error && editMode && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <Info className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-amber-500 leading-relaxed break-all">{error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
