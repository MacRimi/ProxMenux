"use client"

import { useCallback, useEffect, useState } from "react"
import { Check, HardDrive, Info, Loader2, Settings2 } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Switch } from "./ui/switch"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface DiskEntry {
  name: string
  key: string
  model: string
  serial: string
  size_bytes: number
  transport: string
  rotational: boolean
  excluded: boolean
  excluded_at: string | null
  idle: boolean
  present: boolean
}

function formatSize(bytes: number): string {
  if (!bytes) return ""
  const units = ["B", "KB", "MB", "GB", "TB", "PB"]
  let value = bytes
  let i = 0
  while (value >= 1000 && i < units.length - 1) {
    value /= 1000
    i++
  }
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

// Disks the user wants left alone. An excluded disk is never read on a
// schedule — no temperature, no SMART refresh, not even a power-mode query —
// so it can spin down on its own timer. Rotational disks with no I/O are
// already left alone automatically; this is for the ones that should never
// be touched at all, such as a drive handed whole to a VM.
export function DiskExclusions() {
  const t = useT()
  const [disks, setDisks] = useState<DiskEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [editMode, setEditMode] = useState(false)
  const [pending, setPending] = useState<Map<string, boolean>>(new Map())
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      const data = await fetchApi<{ disks: DiskEntry[] }>("/api/health/disks")
      setDisks(data.disks || [])
    } catch {
      setDisks([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const cancel = () => {
    setPending(new Map())
    setError("")
    setEditMode(false)
  }

  const save = async () => {
    if (pending.size === 0) {
      setEditMode(false)
      return
    }
    setSaving(true)
    setError("")
    try {
      for (const [key, excluded] of pending.entries()) {
        const disk = disks.find((d) => d.key === key)
        if (!disk) continue
        if (excluded) {
          await fetchApi("/api/health/disk-exclusions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              disk_key: disk.key,
              disk_name: disk.name,
              model: disk.model,
              serial: disk.serial,
            }),
          })
        } else {
          await fetchApi(`/api/health/disk-exclusions/${encodeURIComponent(disk.key)}`, {
            method: "DELETE",
          })
        }
      }
      setPending(new Map())
      setEditMode(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      await load()
    } catch {
      setError(t("settings.diskExclusions.saveFailed"))
    } finally {
      setSaving(false)
    }
  }

  const transportLabel = (disk: DiskEntry) => {
    const tr = disk.transport.toLowerCase()
    if (tr === "usb") return "USB"
    if (tr === "nvme") return "NVMe"
    if (tr === "sata" || tr === "ata") return disk.rotational ? "HDD" : "SSD"
    if (tr) return tr.toUpperCase()
    return disk.rotational ? "HDD" : "SSD"
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-amber-500" />
            <CardTitle>{t("settings.diskExclusions.title")}</CardTitle>
          </div>
          {!loading && disks.length > 0 && (
            <div className="flex items-center gap-2">
              {saved && (
                <span className="flex items-center gap-1 text-xs text-green-500">
                  <Check className="h-3.5 w-3.5" />
                  {t("status.saved")}
                </span>
              )}
              {editMode ? (
                <>
                  <button
                    className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground"
                    onClick={cancel}
                    disabled={saving}
                  >
                    {t("actions.cancel")}
                  </button>
                  <button
                    className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                    onClick={save}
                    disabled={saving || pending.size === 0}
                  >
                    {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                    {t("actions.save")}
                  </button>
                </>
              ) : (
                <button
                  className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5"
                  onClick={() => setEditMode(true)}
                >
                  <Settings2 className="h-3 w-3" />
                  {t("actions.edit")}
                </button>
              )}
            </div>
          )}
        </div>
        <CardDescription>{t("settings.diskExclusions.description")}</CardDescription>
      </CardHeader>
      <CardContent className={editMode ? "bg-accent" : undefined}>
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
          </div>
        ) : disks.length === 0 ? (
          <div className="text-center py-8">
            <HardDrive className="h-12 w-12 text-muted-foreground mx-auto mb-3 opacity-50" />
            <p className="text-muted-foreground">{t("settings.diskExclusions.empty")}</p>
          </div>
        ) : (
          <div className="space-y-0">
            <div className="grid grid-cols-[1fr_auto] gap-4 pb-2 mb-1 border-b border-border">
              <span className="text-xs font-medium text-muted-foreground">
                {t("settings.diskExclusions.disk")}
              </span>
              <span className="text-xs font-medium text-muted-foreground text-center w-24">
                {t("settings.diskExclusions.periodicReads")}
              </span>
            </div>

            <div className="max-h-[360px] overflow-y-auto divide-y divide-border/50">
              {disks.map((disk) => {
                const excluded = pending.has(disk.key) ? pending.get(disk.key)! : disk.excluded
                return (
                  <div key={disk.key} className="grid grid-cols-[1fr_auto] gap-4 py-3 items-center">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`font-medium ${excluded ? "text-muted-foreground" : ""}`}>
                          {disk.name || "—"}
                        </span>
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {transportLabel(disk)}
                        </Badge>
                        {excluded && (
                          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 bg-blue-500/10 text-blue-400">
                            {t("settings.diskExclusions.excluded")}
                          </Badge>
                        )}
                        {!excluded && disk.idle && (
                          <Badge
                            variant="secondary"
                            className="text-[10px] px-1.5 py-0 bg-muted text-muted-foreground"
                            title={t("storage.idleTitle")}
                          >
                            {t("storage.idle")}
                          </Badge>
                        )}
                        {!disk.present && (
                          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 bg-muted text-muted-foreground">
                            {t("settings.diskExclusions.notConnected")}
                          </Badge>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground break-all">
                        {[disk.model, formatSize(disk.size_bytes), disk.serial].filter(Boolean).join(" · ")}
                      </span>
                    </div>

                    <div className="flex justify-center w-24">
                      <Switch
                        checked={!excluded}
                        disabled={!editMode || saving}
                        onCheckedChange={(checked) => {
                          setPending((m) => {
                            const next = new Map(m)
                            if (!checked === disk.excluded) next.delete(disk.key)
                            else next.set(disk.key, !checked)
                            return next
                          })
                        }}
                        className={`data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border ${!editMode ? "opacity-60" : ""}`}
                      />
                    </div>
                  </div>
                )
              })}
            </div>

            {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

            <div className="flex items-start gap-2 mt-3 pt-3 border-t border-border">
              <Info className="h-3.5 w-3.5 text-blue-400 shrink-0 mt-0.5" />
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {t("settings.diskExclusions.help")}
                <br />
                {t("settings.diskExclusions.idleHelp")}
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
