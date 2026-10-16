"use client"

import { useEffect, useRef, useState } from "react"
import { Archive, Clock, Loader2, LockKeyhole, RefreshCw, Trash2 } from "lucide-react"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Checkbox } from "./ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { useT } from "@/lib/i18n/provider"
import { deleteGuestBackups, type GuestBackup } from "../lib/guest-backup-archives"

export function GuestBackupList({ vmid, backups, loading, onRefresh }: {
  vmid: number
  backups: GuestBackup[]
  loading: boolean
  onRefresh: () => Promise<void>
}) {
  const t = useT()
  const [selected, setSelected] = useState<string[]>([])
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  // A fresh list can remove a selection or reveal a newly protected archive.
  useEffect(() => {
    setSelected(previous => previous.filter(volid => backups.some(backup => backup.volid === volid && !backup.protected)))
  }, [backups])

  const chosen = backups.filter(backup => selected.includes(backup.volid) && !backup.protected)
  const selectable = backups.filter(backup => !backup.protected)
  const disabled = loading || busy || refreshing

  async function refresh() {
    setRefreshing(true)
    setError("")
    try { await onRefresh() } catch { if (mounted.current) setError(t("vmLxc.backups.refreshFailed")) }
    finally { if (mounted.current) setRefreshing(false) }
  }

  async function remove() {
    if (!chosen.length || busy) return
    setBusy(true)
    setError("")
    setMessage("")
    try {
      const results = await deleteGuestBackups(vmid, chosen)
      if (!mounted.current) return
      const deleted = results.filter(result => result.status === "deleted").length
      const unconfirmed = results.length - deleted
      setMessage(t("vmLxc.backups.deletedCount", { count: deleted }))
      if (unconfirmed) setError(t("vmLxc.backups.unconfirmedCount", { count: unconfirmed }))
      setSelected([])
    } catch (error) {
      if (mounted.current) setError(`${t("vmLxc.backups.deleteFailed")} ${error instanceof Error ? error.message : ""}`)
    } finally {
      // A timeout can hide a successful native task. Always bypass both caches.
      try { await onRefresh() } catch { if (mounted.current) setError(t("vmLxc.backups.refreshFailed")) }
      if (mounted.current) { setBusy(false); setConfirm(false) }
    }
  }

  return <>
    <div className="flex items-center justify-between gap-2 mb-3 shrink-0 flex-wrap">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">{t("vmLxc.backups.available")}</span>
        <Badge variant="secondary" className="text-xs h-5">{backups.length}</Badge>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" className="h-7 text-xs gap-1" disabled={disabled} onClick={refresh}>
          <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />{t("vmLxc.backups.refresh")}
        </Button>
        <Button size="sm" variant="destructive" className="h-7 text-xs gap-1" disabled={disabled || !chosen.length} onClick={() => setConfirm(true)}>
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
          {t("vmLxc.backups.deleteSelected", { count: chosen.length })}
        </Button>
      </div>
    </div>
    {message && <p role="status" className="text-xs text-muted-foreground mb-2">{message}</p>}
    {error && <p role="alert" className="text-xs text-destructive mb-2 break-words">{error}</p>}
    {loading ? <div className="flex-1 flex items-center justify-center text-muted-foreground min-h-0">
      <Loader2 className="h-4 w-4 animate-spin mr-2" /><span className="text-sm">{t("vmLxc.backups.loading")}</span>
    </div> : backups.length === 0 ? <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground min-h-0">
      <Archive className="h-12 w-12 mb-3 opacity-30" /><span className="text-sm">{t("vmLxc.backups.empty")}</span>
      <span className="text-xs mt-1">{t("vmLxc.backups.emptyHint")}</span>
    </div> : <>
      <label className="flex items-center gap-2 mb-3 text-xs text-muted-foreground">
        <Checkbox checked={selectable.length > 0 && chosen.length === Math.min(20, selectable.length)} disabled={disabled || !selectable.length}
          onCheckedChange={checked => setSelected(checked ? selectable.slice(0, 20).map(backup => backup.volid) : [])} />
        {t("vmLxc.backups.selectHint")}
      </label>
      <div className="space-y-2 flex-1 overflow-y-auto min-h-0 pr-1 -mr-1">
        {backups.map(backup => <label key={backup.volid} className="flex items-center gap-2 p-3 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors">
          <Checkbox aria-label={`${t("vmLxc.backups.selectBackup")} ${backup.date} ${backup.storage}`} checked={selected.includes(backup.volid)}
            disabled={disabled || !!backup.protected || (chosen.length >= 20 && !selected.includes(backup.volid))}
            onCheckedChange={checked => setSelected(previous => checked ? [...previous, backup.volid] : previous.filter(id => id !== backup.volid))} />
          <Clock className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm min-w-0 truncate" title={backup.volid}>{backup.date}</span>
          {backup.protected && <Badge variant="secondary" className="gap-1 text-xs"><LockKeyhole className="h-3 w-3" />{t("vmLxc.backups.protected")}</Badge>}
          <Badge variant="outline" className="text-xs ml-auto shrink-0">{backup.storage}</Badge>
          <Badge variant="outline" className="font-mono shrink-0">{backup.size_human}</Badge>
        </label>)}
      </div>
    </>}
    <Dialog open={confirm} onOpenChange={value => { if (!busy) setConfirm(value) }}>
      <DialogContent onEscapeKeyDown={event => { if (busy) event.preventDefault() }} onPointerDownOutside={event => { if (busy) event.preventDefault() }}>
        <DialogHeader>
          <DialogTitle>{t("vmLxc.backups.confirmTitle", { count: chosen.length })}</DialogTitle>
          <DialogDescription>{t("vmLxc.backups.confirmDescription", { vmid })}</DialogDescription>
        </DialogHeader>
        <ul className="max-h-48 overflow-auto text-xs space-y-2 break-all">
          {chosen.map(backup => <li key={backup.volid}>{backup.volid}</li>)}
        </ul>
        {busy && <p role="status" className="text-sm text-muted-foreground">{t("vmLxc.backups.deleting")}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => setConfirm(false)}>{t("vmLxc.backups.cancel")}</Button>
          <Button variant="destructive" disabled={busy || !chosen.length} onClick={remove}>
            {busy && <Loader2 className="h-4 w-4 animate-spin mr-2" />}{t("vmLxc.backups.confirmDelete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
