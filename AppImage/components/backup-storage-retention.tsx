"use client"

import { useState } from "react"
import useSWR from "swr"
import { HardDrive, Loader2, Pencil, RefreshCw } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Checkbox } from "./ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { fetchApi } from "../lib/api-config"
import { buildRetention, parseRetention, RETENTION } from "../lib/backup-retention"
import { useT } from "../lib/i18n/provider"

interface StorageRetention { id: string; type: string; prune_backups: string; digest: string }
const fetcher = (url: string) => fetchApi<{ storages: StorageRetention[] }>(url)

export function BackupStorageRetention() {
  const t = useT()
  const { data, error, mutate, isValidating } = useSWR("/api/vm-backup-storages", fetcher)
  const [editing, setEditing] = useState<StorageRetention | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [keepAll, setKeepAll] = useState(false)
  const [useDefault, setUseDefault] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [saveError, setSaveError] = useState("")

  function edit(storage: StorageRetention) {
    const policy = parseRetention(storage.prune_backups)
    setFields(policy.fields)
    setKeepAll(policy.keepAll)
    setUseDefault(!storage.prune_backups)
    setSaveError("")
    setMessage("")
    setEditing(storage)
  }

  async function save() {
    if (!editing || busy) return
    const prune = useDefault ? "" : buildRetention(fields, keepAll)
    if (!useDefault && !prune) return setSaveError(t("backup.storageRetention.choosePolicy"))
    setBusy(true)
    setSaveError("")
    try {
      await fetchApi(`/api/vm-backup-storages/${encodeURIComponent(editing.id)}`, {
        method: "PUT", body: JSON.stringify({ digest: editing.digest, prune_backups: prune }),
      })
      setMessage(t("backup.storageRetention.saved"))
      setEditing(null)
      await mutate()
    } catch (error) {
      setSaveError(`${t("backup.storageRetention.saveFailed")} ${error instanceof Error ? error.message : ""}`)
    } finally { setBusy(false) }
  }

  return <Card className="border-border bg-card/50">
    <CardHeader className="pb-3 flex-row items-center justify-between gap-2">
      <CardTitle className="text-base flex items-center gap-2"><HardDrive className="h-4 w-4" />{t("backup.storageRetention.title")}</CardTitle>
      <Button variant="ghost" size="sm" disabled={isValidating} onClick={() => { void mutate().catch(() => {}) }}>
        <RefreshCw className={`h-4 w-4 mr-2 ${isValidating ? "animate-spin" : ""}`} />{t("backup.storageRetention.refresh")}
      </Button>
    </CardHeader>
    <CardContent className="space-y-3">
      <p className="text-xs text-muted-foreground">{t("backup.storageRetention.description")}</p>
      {message && <p role="status" className="text-xs text-emerald-500">{message}</p>}
      {error ? <p role="alert" className="text-xs text-destructive">{t("backup.storageRetention.loadFailed")}</p> : !data ?
        <Loader2 className="h-4 w-4 animate-spin" /> : !data.storages.length ?
        <p className="text-xs text-muted-foreground">{t("backup.storageRetention.empty")}</p> :
        data.storages.map(storage => <div key={storage.id} className="flex flex-wrap gap-2 items-center border rounded-lg p-3">
          <span className="font-medium text-sm">{storage.id}</span><Badge variant="outline">{storage.type}</Badge>
          <span className="text-xs font-mono text-muted-foreground break-all">{storage.prune_backups || t("backup.storageRetention.default")}</span>
          <Button variant="outline" size="sm" className="ml-auto gap-1" onClick={() => edit(storage)} disabled={!storage.digest || busy}>
            <Pencil className="h-3 w-3" />{t("backup.storageRetention.edit")}
          </Button>
        </div>)}
    </CardContent>
    <Dialog open={!!editing} onOpenChange={open => { if (!open && !busy) setEditing(null) }}>
      <DialogContent className="bg-accent [&_input]:bg-background">
        <DialogHeader><DialogTitle>{t("backup.storageRetention.editTitle", { storage: editing?.id ?? "" })}</DialogTitle>
          <DialogDescription>{t("backup.storageRetention.effect")}</DialogDescription></DialogHeader>
        <Label className="flex items-center gap-2"><Checkbox checked={useDefault} disabled={busy} onCheckedChange={checked => {
          setUseDefault(checked === true)
          if (checked) { setKeepAll(false); setFields({}) }
        }} />{t("backup.storageRetention.useDefault")}</Label>
        <Label className="flex items-center gap-2"><Checkbox checked={keepAll} disabled={useDefault || busy} onCheckedChange={checked => {
          setKeepAll(checked === true)
          if (checked) setFields({})
        }} />{t("backup.storageRetention.keepAll")}</Label>
        <div className="grid grid-cols-2 gap-3">
          {RETENTION.map(key => <div key={key} className="space-y-1">
            <Label htmlFor={`storage-retention-${key}`}>{t(`backup.retention.keep${key[0].toUpperCase()}${key.slice(1)}`)}</Label>
            <Input id={`storage-retention-${key}`} type="number" min={1} max={99999} step={1} disabled={useDefault || keepAll || busy}
              value={fields[key] ?? ""} onChange={event => setFields(previous => ({ ...previous, [key]: event.target.value }))} />
          </div>)}
        </div>
        {saveError && <p role="alert" className="text-xs text-destructive break-words">{saveError}</p>}
        <DialogFooter><Button variant="outline" disabled={busy} onClick={() => setEditing(null)}>{t("backup.storageRetention.cancel")}</Button>
          <Button disabled={busy} onClick={save}>{busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}{t("backup.storageRetention.save")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </Card>
}
