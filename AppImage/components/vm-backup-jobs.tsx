"use client"

import { useCallback, useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { fetchApi } from "../lib/api-config"
import { CalendarClock, Pencil, Play, Plus, RefreshCw, Trash2, Power } from "lucide-react"

interface BackupJob {
  id: string
  enabled?: number | boolean
  schedule?: string
  storage?: string
  mode?: string
  compress?: string
  all?: number | boolean
  vmid?: string
  "prune-backups"?: string | Record<string, string | number>
  "notes-template"?: string
}

interface Guest { vmid: number; name: string; type: string }
interface Options { storages: { id: string; type: string }[]; guests: Guest[] }

interface FormState {
  id?: string
  allGuests: boolean
  vmids: string[]
  storage: string
  schedule: string
  mode: string
  compress: string
  prune: string
  notes: string
}

const SCHEDULE_PRESETS = [
  { label: "Ogni giorno alle 02:00", value: "02:00" },
  { label: "Ogni giorno alle 03:00", value: "03:00" },
  { label: "Ogni domenica alle 02:00", value: "sun 02:00" },
  { label: "Ogni 6 ore", value: "00/6:00" },
  { label: "Ogni ora", value: "hourly" },
]

const EMPTY_FORM: FormState = {
  allGuests: true, vmids: [], storage: "", schedule: "02:00",
  mode: "snapshot", compress: "zstd", prune: "", notes: "{{guestname}}",
}

const isOn = (v: unknown) => v === 1 || v === true || v === "1"

// pvesh può restituire la retention come stringa ("keep-last=3") oppure come oggetto ({"keep-last": 3})
const pruneToString = (v: unknown): string => {
  if (!v) return ""
  if (typeof v === "string") return v
  if (typeof v === "object")
    return Object.entries(v as Record<string, unknown>).map(([k, val]) => `${k}=${val}`).join(",")
  return String(v)
}

const fieldClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"

async function api(path: string, method = "GET", body?: unknown) {
  // NB: adatta alla firma reale di fetchApi della tua versione (vedi note di integrazione)
  return fetchApi(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
}

export function VmBackupJobs() {
  const [jobs, setJobs] = useState<BackupJob[]>([])
  const [options, setOptions] = useState<Options>({ storages: [], guests: [] })
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [deleting, setDeleting] = useState<BackupJob | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const [j, o] = await Promise.all([api("/api/vm-backup-jobs"), api("/api/vm-backup-jobs/options")])
      setJobs(Array.isArray(j?.jobs) ? j.jobs : [])
      if (o?.success) setOptions({ storages: Array.isArray(o.storages) ? o.storages : [], guests: Array.isArray(o.guests) ? o.guests : [] })
    } catch (e) {
      setMessage({ ok: false, text: "Impossibile leggere i job di backup" })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const notify = (ok: boolean, text: string) => setMessage({ ok, text })

  const describeTarget = (j: BackupJob) => {
    if (isOn(j.all)) return "Tutte le VM/CT"
    const ids = String(j.vmid ?? "").split(",").filter(Boolean)
    return ids.length ? ids.map((id) => {
      const g = options.guests.find((x) => String(x.vmid) === id)
      return g ? `${id} (${g.name})` : id
    }).join(", ") : "Nessuna selezione"
  }

  const openEdit = (j: BackupJob) =>
    setForm({
      id: j.id,
      allGuests: isOn(j.all),
      vmids: String(j.vmid ?? "").split(",").filter(Boolean),
      storage: j.storage ?? "",
      schedule: j.schedule ?? "02:00",
      mode: j.mode ?? "snapshot",
      compress: j.compress ?? "zstd",
      prune: pruneToString(j["prune-backups"]),
      notes: j["notes-template"] ?? "",
    })

  const save = async () => {
    if (!form) return
    if (!form.storage) return notify(false, "Scegli lo storage di destinazione")
    if (!form.allGuests && form.vmids.length === 0) return notify(false, "Seleziona almeno una VM/CT")
    setSaving(true)
    const payload = {
      all: form.allGuests ? 1 : 0,
      vmid: form.allGuests ? "" : form.vmids.join(","),
      storage: form.storage,
      schedule: form.schedule,
      mode: form.mode,
      compress: form.compress,
      prune_backups: form.prune,
      notes_template: form.notes,
    }
    try {
      const res = form.id
        ? await api(`/api/vm-backup-jobs/${form.id}`, "PUT", payload)
        : await api("/api/vm-backup-jobs", "POST", payload)
      if (res?.success) {
        notify(true, form.id ? "Job aggiornato" : "Job creato")
        setForm(null)
        load()
      } else notify(false, res?.error ?? "Salvataggio non riuscito")
    } catch {
      notify(false, "Salvataggio non riuscito")
    } finally {
      setSaving(false)
    }
  }

  const act = async (job: BackupJob, action: "toggle" | "run") => {
    try {
      const res = await api(`/api/vm-backup-jobs/${job.id}/${action}`, "POST")
      if (res?.success) {
        notify(true, action === "run" ? `Backup di ${job.id} avviato in background` : `Job ${job.id} aggiornato`)
        load()
      } else notify(false, res?.error ?? "Operazione non riuscita")
    } catch {
      notify(false, "Operazione non riuscita")
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    try {
      const res = await api(`/api/vm-backup-jobs/${deleting.id}`, "DELETE")
      notify(!!res?.success, res?.success ? `Job ${deleting.id} eliminato` : res?.error ?? "Eliminazione non riuscita")
    } catch {
      notify(false, "Eliminazione non riuscita")
    }
    setDeleting(null)
    load()
  }

  const toggleGuest = (vmid: string) =>
    setForm((f) => f && ({ ...f, vmids: f.vmids.includes(vmid) ? f.vmids.filter((v) => v !== vmid) : [...f.vmids, vmid] }))

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold text-foreground">VM Backups</h2>
          <p className="text-sm text-muted-foreground">Job pianificati, come in Datacenter &gt; Backup</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => { setLoading(true); load() }}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} /> Aggiorna
          </Button>
          <Button size="sm" className="bg-blue-500 hover:bg-blue-600 text-white" onClick={() => setForm({ ...EMPTY_FORM, storage: options.storages[0]?.id ?? "" })}>
            <Plus className="h-4 w-4 mr-2" /> Nuovo job
          </Button>
        </div>
      </div>

      {message && (
        <div
          role="status"
          className={`rounded-md border px-4 py-2 text-sm ${message.ok ? "border-green-500/20 bg-green-500/10 text-green-500" : "border-red-500/20 bg-red-500/10 text-red-500"}`}
        >
          {message.text}
        </div>
      )}

      {!loading && jobs.length === 0 && (
        <Card className="bg-card border-border">
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Nessun job di backup. Crea il primo con “Nuovo job”.
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {jobs.map((job) => {
          const enabled = job.enabled === undefined ? true : isOn(job.enabled)
          return (
            <Card key={job.id} className="bg-card border-border">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <CalendarClock className="h-4 w-4 text-muted-foreground" />
                    <span className="truncate">{job.id}</span>
                  </CardTitle>
                  <Badge variant="outline" className={enabled ? "bg-green-500/10 text-green-500 border-green-500/20" : "bg-muted text-muted-foreground"}>
                    {enabled ? "Attivo" : "Disattivato"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <dl className="grid grid-cols-[110px_1fr] gap-y-1">
                  <dt className="text-muted-foreground">Schedule</dt><dd className="font-mono">{String(job.schedule ?? "-")}</dd>
                  <dt className="text-muted-foreground">Storage</dt><dd>{job.storage ?? "-"}</dd>
                  <dt className="text-muted-foreground">Guest</dt><dd className="break-words">{describeTarget(job)}</dd>
                  <dt className="text-muted-foreground">Modalità</dt><dd>{job.mode ?? "snapshot"} · {job.compress ?? "zstd"}</dd>
                  <dt className="text-muted-foreground">Retention</dt><dd className="font-mono break-all">{pruneToString(job["prune-backups"]) || "predefinita dello storage"}</dd>
                </dl>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button variant="outline" size="sm" onClick={() => act(job, "run")}><Play className="h-4 w-4 mr-1" />Esegui ora</Button>
                  <Button variant="outline" size="sm" onClick={() => openEdit(job)}><Pencil className="h-4 w-4 mr-1" />Modifica</Button>
                  <Button variant="outline" size="sm" onClick={() => act(job, "toggle")}><Power className="h-4 w-4 mr-1" />{enabled ? "Disattiva" : "Attiva"}</Button>
                  <Button variant="outline" size="sm" className="text-red-500" onClick={() => setDeleting(job)}><Trash2 className="h-4 w-4 mr-1" />Elimina</Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Crea / modifica */}
      <Dialog open={!!form} onOpenChange={(o) => !o && setForm(null)}>
        <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{form?.id ? `Modifica job ${form.id}` : "Nuovo job di backup"}</DialogTitle>
          </DialogHeader>
          {form && (
            <div className="space-y-4 text-sm">
              <div className="space-y-2">
                <span className="font-medium">Guest da salvare</span>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={form.allGuests} onChange={(e) => setForm({ ...form, allGuests: e.target.checked })} />
                  Tutte le VM e i container
                </label>
                {!form.allGuests && (
                  <div className="max-h-40 overflow-y-auto rounded-md border border-border p-2 space-y-1">
                    {options.guests.map((g) => (
                      <label key={g.vmid} className="flex items-center gap-2">
                        <input type="checkbox" checked={form.vmids.includes(String(g.vmid))} onChange={() => toggleGuest(String(g.vmid))} />
                        {g.vmid} · {g.name} <span className="text-muted-foreground">({g.type === "qemu" ? "VM" : "LXC"})</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <label className="block space-y-1">
                <span className="font-medium">Storage di destinazione</span>
                <select className={fieldClass} value={form.storage} onChange={(e) => setForm({ ...form, storage: e.target.value })}>
                  <option value="">Seleziona…</option>
                  {options.storages.map((s) => <option key={s.id} value={s.id}>{s.id} ({s.type})</option>)}
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium">Schedule</span>
                <select
                  className={fieldClass}
                  value={SCHEDULE_PRESETS.some((p) => p.value === form.schedule) ? form.schedule : "custom"}
                  onChange={(e) => e.target.value !== "custom" && setForm({ ...form, schedule: e.target.value })}
                >
                  {SCHEDULE_PRESETS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                  <option value="custom">Personalizzato</option>
                </select>
                <input className={`${fieldClass} font-mono`} value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} placeholder="es. mon..fri 01:30" />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="block space-y-1">
                  <span className="font-medium">Modalità</span>
                  <select className={fieldClass} value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
                    <option value="snapshot">snapshot</option>
                    <option value="suspend">suspend</option>
                    <option value="stop">stop</option>
                  </select>
                </label>
                <label className="block space-y-1">
                  <span className="font-medium">Compressione</span>
                  <select className={fieldClass} value={form.compress} onChange={(e) => setForm({ ...form, compress: e.target.value })}>
                    <option value="zstd">zstd</option>
                    <option value="gzip">gzip</option>
                    <option value="lzo">lzo</option>
                    <option value="0">nessuna</option>
                  </select>
                </label>
              </div>

              <label className="block space-y-1">
                <span className="font-medium">Retention</span>
                <input className={`${fieldClass} font-mono`} value={form.prune} onChange={(e) => setForm({ ...form, prune: e.target.value })} placeholder="keep-last=3,keep-weekly=2 (vuoto = predefinita)" />
              </label>

              <label className="block space-y-1">
                <span className="font-medium">Note dei backup</span>
                <input className={fieldClass} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </label>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setForm(null)}>Annulla</Button>
            <Button className="bg-blue-500 hover:bg-blue-600 text-white" disabled={saving} onClick={save}>
              {saving ? "Salvataggio…" : "Salva"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Conferma eliminazione */}
      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Elimina job {deleting?.id}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">Viene rimossa solo la pianificazione. Gli archivi di backup già creati restano sullo storage.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>Annulla</Button>
            <Button className="bg-red-500 hover:bg-red-600 text-white" onClick={confirmDelete}>Elimina job</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
