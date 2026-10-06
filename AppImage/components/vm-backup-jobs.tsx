"use client"

// The backup jobs of Proxmox for VMs and CTs (Datacenter > Backup).
// Based on the contribution of MattiaC46 (PR #421).

import { useState } from "react"
import useSWR from "swr"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Checkbox } from "./ui/checkbox"
import { ScrollArea } from "./ui/scroll-area"
import {
  AlertTriangle, Archive, Calendar, CalendarClock, CheckCircle2, ChevronRight, DatabaseBackup, FileText, HardDrive,
  Layers, Loader2, Pencil, PlayCircle, Plus, Power, Server, Trash2,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { cancelButtonClass } from "../lib/utils"
import { useT } from "../lib/i18n/provider"

interface VmBackupJob {
  id: string
  enabled?: number | boolean | string
  schedule?: string
  storage?: string
  mode?: string
  compress?: string | number
  all?: number | boolean | string
  vmid?: string
  node?: string
  "prune-backups"?: string
  "notes-template"?: string
  host_backups?: string[]
}

interface Guest { vmid: number; name: string; type: string; node?: string }
interface Options { storages: { id: string; type: string }[]; guests: Guest[] }
interface RunResult { tasks: { node: string; upid: string }[]; failures: { node: string; error: string }[] }

interface FormState {
  id?: string
  name: string
  allGuests: boolean
  vmids: string[]
  storage: string
  originalStorage: string
  schedule: string
  mode: string
  compress: string
  retention: Record<string, string>
  keepAll: boolean
  notes: string
  attached: string[]
}

const PRESETS = [
  { key: "daily02", value: "02:00" },
  { key: "daily03", value: "03:00" },
  { key: "sunday02", value: "sun 02:00" },
  { key: "every6h", value: "00/6:00" },
  { key: "hourly", value: "hourly" },
]

const EMPTY_FORM: FormState = {
  name: "", allGuests: true, vmids: [], storage: "", originalStorage: "", schedule: "02:00",
  mode: "snapshot", compress: "zstd", retention: {}, keepAll: false, notes: "{{guestname}}", attached: [],
}

// The limits a job can keep, in the order Proxmox lists them.
const RETENTION = ["last", "hourly", "daily", "weekly", "monthly", "yearly"] as const

const parseRetention = (prune: string) => {
  const fields: Record<string, string> = {}
  let keepAll = false
  for (const part of prune.split(",")) {
    const [key, value] = part.trim().split("=")
    if (key === "keep-all") keepAll = value === "1"
    else if (key?.startsWith("keep-") && Number(value) > 0) fields[key.slice(5)] = String(Number(value))
  }
  return { fields, keepAll }
}

const buildRetention = (fields: Record<string, string>, keepAll: boolean) => {
  const parts = RETENTION.filter((key) => Number(fields[key]) > 0).map((key) => `keep-${key}=${Number(fields[key])}`)
  return parts.length ? parts.join(",") : keepAll ? "keep-all=1" : ""
}

const isOn = (value: unknown) => value === 1 || value === true || value === "1"
const jobEnabled = (job: VmBackupJob) => job.enabled === undefined || isOn(job.enabled)
const guestIds = (job: VmBackupJob) => String(job.vmid ?? "").split(",").map((id) => id.trim()).filter(Boolean)

const fetcher = async (url: string) => fetchApi<any>(url)

async function call(path: string, method: string, body?: unknown) {
  return fetchApi<any>(path, { method, body: body ? JSON.stringify(body) : undefined })
}

export function VmBackupJobs() {
  const t = useT()
  const { data, error, mutate } = useSWR<{ jobs: VmBackupJob[] }>("/api/vm-backup-jobs", fetcher, { refreshInterval: 30000 })
  const { data: options } = useSWR<Options>("/api/vm-backup-jobs/options", fetcher, { refreshInterval: 60000 })
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<VmBackupJob | null>(null)
  const [running, setRunning] = useState<VmBackupJob | null>(null)
  const [disabling, setDisabling] = useState<VmBackupJob | null>(null)
  const [viewingId, setViewingId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const jobs = data?.jobs ?? []
  const viewing = jobs.find((job) => job.id === viewingId) ?? null
  const guests = options?.guests ?? []
  const storages = options?.storages ?? []

  const describeGuests = (job: VmBackupJob) => {
    if (isOn(job.all)) return t("backup.vmJobs.allGuests")
    const ids = guestIds(job)
    if (ids.length === 0) return t("backup.vmJobs.noGuests")
    return ids.map((id) => {
      const guest = guests.find((item) => String(item.vmid) === id)
      return guest ? `${id} (${guest.name})` : id
    }).join(", ")
  }

  const openEdit = (job: VmBackupJob) => {
    setFormError(null)
    setForm({
      id: job.id,
      name: job.id,
      allGuests: isOn(job.all),
      vmids: guestIds(job),
      storage: job.storage ?? "",
      originalStorage: job.storage ?? "",
      schedule: job.schedule ?? "02:00",
      mode: job.mode ?? "snapshot",
      compress: String(job.compress ?? "zstd"),
      retention: parseRetention(job["prune-backups"] ?? "").fields,
      keepAll: parseRetention(job["prune-backups"] ?? "").keepAll,
      notes: job["notes-template"] ?? "",
      attached: job.host_backups ?? [],
    })
  }

  const save = async () => {
    if (!form) return
    if (!form.storage) return setFormError(t("backup.vmJobs.needStorage"))
    if (!form.allGuests && form.vmids.length === 0) return setFormError(t("backup.vmJobs.needGuests"))
    setBusy("save")
    setFormError(null)
    const payload: Record<string, unknown> = {
      all: form.allGuests ? 1 : 0,
      vmid: form.allGuests ? "" : form.vmids.join(","),
      storage: form.storage,
      schedule: form.schedule.trim(),
      mode: form.mode,
      compress: form.compress,
      prune_backups: buildRetention(form.retention, form.keepAll),
      notes_template: form.notes.trim(),
    }
    if (!form.id && form.name.trim()) payload.id = form.name.trim()
    try {
      if (form.id) await call(`/api/vm-backup-jobs/${encodeURIComponent(form.id)}`, "PUT", payload)
      else await call("/api/vm-backup-jobs", "POST", payload)
      setMessage({ ok: true, text: form.id ? t("backup.vmJobs.updated") : t("backup.vmJobs.created") })
      setForm(null)
      mutate()
    } catch (problem) {
      setFormError(problem instanceof Error && problem.message ? problem.message : t("backup.vmJobs.saveFailed"))
    } finally {
      setBusy(null)
    }
  }

  const toggle = async (job: VmBackupJob) => {
    setBusy(job.id)
    try {
      const result = await call(`/api/vm-backup-jobs/${encodeURIComponent(job.id)}/toggle`, "POST")
      setMessage({ ok: true, text: t(result?.enabled ? "backup.vmJobs.toggledOn" : "backup.vmJobs.toggledOff", { id: job.id }) })
      mutate()
    } catch (problem) {
      setMessage({ ok: false, text: problem instanceof Error && problem.message ? problem.message : t("backup.vmJobs.actionFailed") })
    } finally {
      setBusy(null)
      setDisabling(null)
    }
  }

  const runNow = async () => {
    if (!running) return
    const job = running
    setBusy(job.id)
    try {
      const result: RunResult = await call(`/api/vm-backup-jobs/${encodeURIComponent(job.id)}/run`, "POST")
      let text = t("backup.vmJobs.started", { id: job.id, nodes: (result.tasks ?? []).map((task) => task.node).join(", ") })
      if (result.failures?.length) {
        text += " " + t("backup.vmJobs.startedPartial", { nodes: result.failures.map((failure) => failure.node).join(", ") })
      }
      setMessage({ ok: !result.failures?.length, text })
    } catch (problem) {
      setMessage({ ok: false, text: problem instanceof Error && problem.message ? problem.message : t("backup.vmJobs.actionFailed") })
    } finally {
      setBusy(null)
      setRunning(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    const job = deleting
    setBusy(job.id)
    try {
      await call(`/api/vm-backup-jobs/${encodeURIComponent(job.id)}`, "DELETE")
      setMessage({ ok: true, text: t("backup.vmJobs.deleted", { id: job.id }) })
      setViewingId(null)
      mutate()
    } catch (problem) {
      setMessage({ ok: false, text: problem instanceof Error && problem.message ? problem.message : t("backup.vmJobs.actionFailed") })
    } finally {
      setBusy(null)
      setDeleting(null)
    }
  }

  const toggleGuest = (vmid: string) =>
    setForm((current) => current && ({
      ...current,
      vmids: current.vmids.includes(vmid) ? current.vmids.filter((id) => id !== vmid) : [...current.vmids, vmid],
    }))

  const preset = form && PRESETS.some((item) => item.value === form.schedule) ? form.schedule : "custom"
  const retentionOf = (job: VmBackupJob) => (job["prune-backups"] ?? "").split(",").map((part) => part.trim()).filter(Boolean)
  const compressionOf = (job: VmBackupJob) =>
    String(job.compress ?? "zstd") === "0" ? t("backup.vmJobs.compressNone") : String(job.compress ?? "zstd")

  const retentionChips = (job: VmBackupJob) => {
    const parts = retentionOf(job)
    if (parts.length === 0) return <span className="text-muted-foreground">{t("backup.vmJobs.storageDefault")}</span>
    return parts.map((part) => {
      const [label, value] = part.split("=")
      const name = label.replace(/^keep-/, "")
      return (
        <span key={part} className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-border bg-background/60">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {(RETENTION as readonly string[]).includes(name) ? t(`backup.retention.${name}`) : name}
          </span>
          <span className="font-mono text-xs text-foreground">{value}</span>
        </span>
      )
    })
  }

  const badges = (job: VmBackupJob) => (
    <>
      {!jobEnabled(job) && (
        <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/40 bg-amber-500/5">
          {t("status.disabled")}
        </Badge>
      )}
      {(job.host_backups ?? []).length > 0 && (
        <Badge
          variant="outline"
          className="text-[10px] text-blue-400 border-blue-400/40 bg-blue-500/5"
          title={t("backup.vmJobs.attachedHost", { ids: (job.host_backups ?? []).join(", ") })}
        >
          {t("backup.vmJobs.hostBackup")}
        </Badge>
      )}
    </>
  )

  return (
    <>
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex items-center gap-2 min-w-0">
            <CalendarClock className="h-5 w-5 text-blue-500 shrink-0" />
            <CardTitle className="text-base font-semibold truncate">{t("backup.vmJobs.title")}</CardTitle>
            <Badge variant="outline" className="ml-1">{jobs.length}</Badge>
          </div>
          <Button
            size="sm"
            className="h-8 px-3 bg-blue-500 hover:bg-blue-600 text-white shrink-0"
            onClick={() => { setFormError(null); setForm({ ...EMPTY_FORM, storage: storages[0]?.id ?? "" }) }}
          >
            <Plus className="h-4 w-4 mr-1" />
            {t("backup.vmJobs.newJob")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">{t("backup.vmJobs.subtitle")}</p>

          {message && !viewing && (
            <div
              role="status"
              className={`text-xs px-3 py-2 rounded-md border whitespace-pre-wrap break-words ${
                message.ok ? "text-green-500 border-green-500/30 bg-green-500/10" : "text-red-500 border-red-500/30 bg-red-500/10"
              }`}
            >
              {message.text}
            </div>
          )}

          {error ? (
            <div className="text-sm text-red-500 py-4">{t("backup.vmJobs.loadFailed")}</div>
          ) : !data ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("backup.common.loading")}
            </div>
          ) : jobs.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4">{t("backup.vmJobs.empty")}</div>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => { setMessage(null); setViewingId(job.id) }}
                  className="w-full text-left flex items-start gap-3 p-3 rounded-md border border-border bg-card hover:bg-white/5 transition-colors group"
                  title={t("backup.jobs.openJobTitle")}
                >
                  <div className="min-w-0 flex-1 w-full">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-base truncate" title={job.id}>{job.id}</span>
                      {badges(job)}
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground line-clamp-2 break-words">{describeGuests(job)}</div>
                    <div className="mt-2 text-xs text-foreground flex items-center gap-x-4 gap-y-1 flex-wrap">
                      <span className="inline-flex items-center gap-1" title={t("backup.vmJobs.labelSchedule")}>
                        <Calendar className="h-3.5 w-3.5 text-green-500" />
                        <span className="font-mono">{job.schedule || "—"}</span>
                      </span>
                      <span className="inline-flex items-center gap-1" title={t("backup.vmJobs.labelStorage")}>
                        <HardDrive className="h-3.5 w-3.5 text-green-500" />
                        <span>{job.storage || "—"}</span>
                      </span>
                      <span className="inline-flex items-center gap-1" title={t("backup.vmJobs.labelMode")}>
                        <Layers className="h-3.5 w-3.5 text-green-500" />
                        <span>{job.mode ?? "snapshot"} · {compressionOf(job)}</span>
                      </span>
                      <span className="inline-flex items-center gap-1.5 flex-wrap" title={t("backup.vmJobs.labelRetention")}>
                        <Archive className="h-3.5 w-3.5 text-green-500" />
                        {retentionChips(job)}
                      </span>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-blue-400 transition-colors shrink-0 mt-1" />
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Job detail */}
      <Dialog open={!!viewing} onOpenChange={(open) => { if (!open) { setViewingId(null); setMessage(null) } }}>
        <DialogContent className="max-w-3xl bg-card border-border overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 flex-wrap text-base pr-8">
              <DatabaseBackup className="h-5 w-5 text-blue-500" />
              <span className="font-mono break-all">{viewing?.id}</span>
              {viewing && badges(viewing)}
            </DialogTitle>
            <DialogDescription className="text-xs">{t("backup.vmJobs.subtitle")}</DialogDescription>
          </DialogHeader>

          {message && (
            <div
              role="status"
              className={`text-xs px-3 py-2 rounded-md border whitespace-pre-wrap break-words ${
                message.ok ? "text-green-500 border-green-500/30 bg-green-500/10" : "text-red-500 border-red-500/30 bg-red-500/10"
              }`}
            >
              {message.text}
            </div>
          )}

          {viewing && (
            <ScrollArea className="max-h-[60vh] pr-2">
              <div className="space-y-4 text-sm">
                <section className="space-y-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-emerald-400">
                    <Server className="h-3.5 w-3.5" /> {t("backup.vmJobs.fieldGuests")}
                  </h4>
                  <div className="break-words">{describeGuests(viewing)}</div>
                </section>

                <section className="space-y-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-amber-400">
                    <Calendar className="h-3.5 w-3.5" /> {t("backup.vmJobs.labelSchedule")}
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("backup.vmJobs.labelSchedule")}</div>
                      <div className="font-mono break-all">{viewing.schedule || "—"}</div>
                    </div>
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("backup.vmJobs.labelRetention")}</div>
                      <div className="flex items-center gap-1.5 flex-wrap">{retentionChips(viewing)}</div>
                    </div>
                  </div>
                </section>

                <section className="space-y-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-blue-400">
                    <HardDrive className="h-3.5 w-3.5" /> {t("backup.vmJobs.labelStorage")}
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("backup.vmJobs.labelStorage")}</div>
                      <div className="break-words">{viewing.storage || "—"}</div>
                    </div>
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("backup.vmJobs.labelMode")}</div>
                      <div>{viewing.mode ?? "snapshot"}</div>
                    </div>
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("backup.vmJobs.fieldCompress")}</div>
                      <div>{compressionOf(viewing)}</div>
                    </div>
                  </div>
                </section>

                {viewing["notes-template"] && (
                  <section className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wide flex items-center gap-1.5 text-muted-foreground">
                      <FileText className="h-3.5 w-3.5" /> {t("backup.vmJobs.fieldNotes")}
                    </h4>
                    <div className="font-mono break-all">{viewing["notes-template"]}</div>
                  </section>
                )}

                {(viewing.host_backups ?? []).length > 0 && (
                  <div className="rounded-md border border-blue-500/40 bg-blue-500/5 p-2 text-xs">
                    {t("backup.vmJobs.attachedHost", { ids: (viewing.host_backups ?? []).join(", ") })}
                  </div>
                )}
              </div>
            </ScrollArea>
          )}

          {viewing && (
            <div className="border-t border-border pt-3 flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  size="sm"
                  disabled={busy !== null}
                  className="bg-green-600 hover:bg-green-700 text-white"
                  onClick={() => setRunning(viewing)}
                >
                  {busy === viewing.id && running ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <PlayCircle className="h-3.5 w-3.5 mr-1" />
                  )}
                  {t("backup.actions.runNow")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  className="bg-blue-500/10 border-blue-500/40 !text-blue-400 hover:bg-blue-500/20 hover:!text-blue-300"
                  onClick={() => { const job = viewing; setViewingId(null); setMessage(null); openEdit(job) }}
                >
                  <Pencil className="h-3.5 w-3.5 mr-1" />
                  {t("backup.actions.edit")}
                </Button>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  className={jobEnabled(viewing)
                    ? "bg-amber-500/10 border-amber-500/40 !text-amber-400 hover:bg-amber-500/20 hover:!text-amber-300"
                    : "bg-emerald-500/10 border-emerald-500/40 !text-emerald-400 hover:bg-emerald-500/20 hover:!text-emerald-300"}
                  onClick={() => (jobEnabled(viewing) ? setDisabling(viewing) : toggle(viewing))}
                >
                  {busy === viewing.id && !running && !deleting ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : jobEnabled(viewing) ? (
                    <Power className="h-3.5 w-3.5 mr-1" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                  )}
                  {jobEnabled(viewing) ? t("backup.actions.disable") : t("backup.actions.enable")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  className="bg-red-500/10 border-red-500/40 !text-red-400 hover:bg-red-500/20 hover:!text-red-300"
                  onClick={() => setDeleting(viewing)}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                  {t("backup.actions.delete")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Create / edit: edit mode, the editable fields sunken */}
      <Dialog open={!!form} onOpenChange={(open) => !open && setForm(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col bg-accent [&_input]:bg-background [&_textarea]:bg-background [&_[role=combobox]]:bg-background">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <CalendarClock className="h-5 w-5 text-blue-500" />
              {form?.id ? t("backup.vmJobs.dialogEdit", { id: form.id }) : t("backup.vmJobs.dialogNew")}
            </DialogTitle>
            <DialogDescription className="text-xs">{t("backup.vmJobs.subtitle")}</DialogDescription>
          </DialogHeader>
          {form && (
            <div className="flex-1 overflow-y-auto pr-1 space-y-4 text-sm">
              {!form.id && (
                <div className="space-y-1">
                  <Label htmlFor="vm-job-name">{t("backup.vmJobs.fieldName")}</Label>
                  <Input id="vm-job-name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
                  <p className="text-xs text-muted-foreground">{t("backup.vmJobs.fieldNameHint")}</p>
                </div>
              )}

              <div className="space-y-2">
                <Label>{t("backup.vmJobs.fieldGuests")}</Label>
                <label className="flex items-center gap-2">
                  <Checkbox checked={form.allGuests} onCheckedChange={(checked) => setForm({ ...form, allGuests: checked === true })} />
                  {t("backup.vmJobs.fieldAll")}
                </label>
                {!form.allGuests && (
                  <div className="max-h-56 overflow-y-auto rounded-md border border-border bg-background p-2 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
                    {guests.map((guest) => (
                      <label key={guest.vmid} className="flex items-center gap-2 min-w-0">
                        <Checkbox checked={form.vmids.includes(String(guest.vmid))} onCheckedChange={() => toggleGuest(String(guest.vmid))} />
                        <span className="truncate">{guest.vmid} · {guest.name}</span>
                        <span className="text-muted-foreground shrink-0">({guest.type === "qemu" ? "VM" : "LXC"})</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-1">
                <Label>{t("backup.vmJobs.fieldStorage")}</Label>
                {storages.length === 0 ? (
                  <p className="text-xs text-amber-500">{t("backup.vmJobs.noStorage")}</p>
                ) : (
                  <Select value={form.storage} onValueChange={(value) => setForm({ ...form, storage: value })}>
                    <SelectTrigger><SelectValue placeholder={t("backup.vmJobs.selectStorage")} /></SelectTrigger>
                    <SelectContent>
                      {storages.map((storage) => (
                        <SelectItem key={storage.id} value={storage.id}>{storage.id} ({storage.type})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                {form.attached.length > 0 && form.storage !== form.originalStorage && (
                  <p className="text-xs text-amber-500 flex items-start gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                    <span>{t("backup.vmJobs.storageAttached", { ids: form.attached.join(", ") })}</span>
                  </p>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>{t("backup.vmJobs.fieldSchedule")}</Label>
                  <Select value={preset} onValueChange={(value) => value !== "custom" && setForm({ ...form, schedule: value })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PRESETS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>{t(`backup.vmJobs.presets.${item.key}`)}</SelectItem>
                      ))}
                      <SelectItem value="custom">{t("backup.vmJobs.scheduleCustom")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="vm-job-schedule">{t("backup.vmJobs.scheduleCustom")}</Label>
                  <Input
                    id="vm-job-schedule"
                    className="font-mono"
                    value={form.schedule}
                    onChange={(event) => setForm({ ...form, schedule: event.target.value })}
                    placeholder={t("backup.vmJobs.schedulePlaceholder")}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>{t("backup.vmJobs.fieldMode")}</Label>
                  <Select value={form.mode} onValueChange={(value) => setForm({ ...form, mode: value })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="snapshot">{t("backup.vmJobs.modeSnapshot")}</SelectItem>
                      <SelectItem value="suspend">{t("backup.vmJobs.modeSuspend")}</SelectItem>
                      <SelectItem value="stop">{t("backup.vmJobs.modeStop")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t("backup.vmJobs.fieldCompress")}</Label>
                  <Select value={form.compress} onValueChange={(value) => setForm({ ...form, compress: value })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="zstd">zstd</SelectItem>
                      <SelectItem value="gzip">gzip</SelectItem>
                      <SelectItem value="lzo">lzo</SelectItem>
                      <SelectItem value="0">{t("backup.vmJobs.compressNone")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <Label>{t("backup.retention.title")}</Label>
                <p className="text-xs text-muted-foreground mb-2">{t("backup.retention.zeroDisables")}</p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {RETENTION.map((key) => (
                    <div key={key}>
                      <Label htmlFor={`vm-job-keep-${key}`} className="text-xs">
                        {t(`backup.retention.keep${key[0].toUpperCase()}${key.slice(1)}`)}
                      </Label>
                      <Input
                        id={`vm-job-keep-${key}`}
                        type="number"
                        min="0"
                        value={form.retention[key] ?? ""}
                        onChange={(event) => setForm({ ...form, retention: { ...form.retention, [key]: event.target.value } })}
                        className="font-mono mt-1"
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <Label htmlFor="vm-job-notes">{t("backup.vmJobs.fieldNotes")}</Label>
                <Input id="vm-job-notes" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
              </div>

              {formError && (
                <div className="text-xs text-red-500 px-3 py-2 rounded-md border border-red-500/30 bg-red-500/10 whitespace-pre-wrap break-words">
                  {formError}
                </div>
              )}
            </div>
          )}
          <div className="flex items-center justify-between gap-2 pt-3 border-t border-border">
            <Button
              variant="outline"
              className={cancelButtonClass}
              onClick={() => setForm(null)}
              disabled={busy === "save"}
            >
              {t("backup.vmJobs.cancel")}
            </Button>
            <Button className="bg-blue-500 hover:bg-blue-600 text-white" disabled={busy === "save"} onClick={save}>
              {busy === "save" && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {busy === "save" ? t("backup.vmJobs.saving") : t("backup.vmJobs.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Run now */}
      <Dialog open={!!running} onOpenChange={(open) => !open && setRunning(null)}>
        <DialogContent className="max-w-md bg-card border-border">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <PlayCircle className="h-5 w-5 text-green-500" />
              {t("backup.vmJobs.runTitle", { id: running?.id ?? "" })}
            </DialogTitle>
            <DialogDescription className="text-xs">{t("backup.vmJobs.runBody")}</DialogDescription>
          </DialogHeader>
          {running?.mode === "stop" && (
            <p className="text-xs text-amber-500 flex items-start gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{t("backup.vmJobs.runStop")}</span>
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" className={cancelButtonClass} onClick={() => setRunning(null)}>{t("backup.vmJobs.cancel")}</Button>
            <Button className="bg-green-600 hover:bg-green-700 text-white" disabled={busy !== null} onClick={runNow}>
              {t("backup.actions.runNow")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Disable */}
      <Dialog open={!!disabling} onOpenChange={(open) => !open && setDisabling(null)}>
        <DialogContent className="max-w-md bg-card border-border">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <Power className="h-5 w-5 text-amber-500" />
              {t("backup.vmJobs.disableTitle", { id: disabling?.id ?? "" })}
            </DialogTitle>
            <DialogDescription className="text-xs">{t("backup.vmJobs.disableBody")}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" className={cancelButtonClass} onClick={() => setDisabling(null)}>{t("backup.vmJobs.cancel")}</Button>
            <Button
              className="bg-amber-500/10 border border-amber-500/40 !text-amber-400 hover:bg-amber-500/20 hover:!text-amber-300"
              disabled={busy !== null}
              onClick={() => disabling && toggle(disabling)}
            >
              {t("backup.actions.disable")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete */}
      <Dialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="max-w-md bg-card border-border">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <Trash2 className="h-5 w-5 text-red-500" />
              {t("backup.vmJobs.deleteTitle", { id: deleting?.id ?? "" })}
            </DialogTitle>
            <DialogDescription className="text-xs">{t("backup.vmJobs.deleteBody")}</DialogDescription>
          </DialogHeader>
          {(deleting?.host_backups?.length ?? 0) > 0 && (
            <p className="text-xs text-amber-500 flex items-start gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{t("backup.vmJobs.deleteAttached", { ids: (deleting?.host_backups ?? []).join(", ") })}</span>
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" className={cancelButtonClass} onClick={() => setDeleting(null)}>{t("backup.vmJobs.cancel")}</Button>
            <Button className="bg-red-600 hover:bg-red-700 text-white" disabled={busy !== null} onClick={confirmDelete}>
              {t("backup.vmJobs.deleteConfirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
