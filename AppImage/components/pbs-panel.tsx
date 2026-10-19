"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"
import {
  Activity, ArchiveRestore, Database, DatabaseBackup, Download, ListChecks,
  RefreshCw, Scissors, Server, Settings2, ShieldCheck, Terminal, Trash2,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { PBSDatastoreCard, type PBSDatastore } from "./pbs-datastore-usage"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface Connection { id: string; name: string; url: string; token_id: string; fingerprint: string; has_token: boolean }
interface Detected { name: string; url: string; fingerprint: string }
interface Connections { local_available: boolean; servers: Connection[]; detected?: Detected[] }
interface Task { upid: string; worker_type?: string; worker_id?: string; starttime?: number; endtime?: number; status?: string }
interface Job { id: string; store?: string; schedule?: string; "last-run-state"?: string }
interface PBSStatus {
  name: string; version: string | null; fetched_at: number; services: Record<string, string>;
  datastores: PBSDatastore[] | null; tasks: Task[] | null;
  sync: Job[] | null; verify: Job[] | null; prune: Job[] | null; errors: Record<string, string>;
}

const emptyForm = { id: "", name: "", url: "", token_id: "", fingerprint: "", token_secret: "" }
const NEW_CONNECTION = "__new__"
const badgeTone = {
  ok: "bg-green-500/10 text-green-500 border-green-500/20",
  warn: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  error: "bg-red-500/10 text-red-500 border-red-500/20",
  running: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  muted: "bg-muted text-muted-foreground border-border",
}

const TASK_ICONS: Record<string, typeof Activity> = {
  backup: DatabaseBackup, reader: ArchiveRestore, verify: ShieldCheck, verificationjob: ShieldCheck,
  verify_group: ShieldCheck, verify_snapshot: ShieldCheck, prune: Scissors, prunejob: Scissors,
  garbage_collection: Trash2, sync: RefreshCw, syncjob: RefreshCw, aptupdate: Download,
  termproxy: Terminal, dircreate: Database, "create-datastore": Database,
}

// PBS reports "OK", "WARNINGS: n" or the error text; a task without one is still running.
function taskState(task: Task): keyof typeof badgeTone {
  if (!task.status) return task.endtime ? "muted" : "running"
  if (task.status === "OK") return "ok"
  if (task.status.startsWith("WARNINGS")) return "warn"
  return "error"
}

function jobState(state?: string): keyof typeof badgeTone {
  if (!state) return "muted"
  if (state === "ok") return "ok"
  if (state.toLowerCase().startsWith("warn")) return "warn"
  return "error"
}

function formatDuration(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—"
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}d ${hours % 24}h`
}

// `localOnly` is the PBS host's own Monitor: no connection picker, the
// header Refresh already reloads the page data.
export function PBSPanel({ localOnly = false }: { localOnly?: boolean } = {}) {
  const t = useT()
  const { data: connections, error: connectionError, mutate: reloadConnections } = useSWR<Connections>(
    "/api/pbs/servers", url => fetchApi<Connections>(url), { revalidateOnFocus: false })
  const [selected, setSelected] = useState("")
  const [manage, setManage] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")
  const { data, error: statusError, isLoading, mutate } = useSWR<PBSStatus>(
    selected ? `/api/pbs/status?server=${encodeURIComponent(selected)}` : null,
    url => fetchApi<PBSStatus>(url), { refreshInterval: 30000, revalidateOnFocus: false })

  useEffect(() => {
    if (!connections) return
    if (selected === "local" && connections.local_available) return
    if (connections.servers.some(row => row.id === selected)) return
    setSelected(connections.local_available ? "local" : connections.servers[0]?.id || "")
  }, [connections, selected])

  const save = async () => {
    setBusy(true); setError(""); setMessage("")
    try {
      const result = await fetchApi<{ id: string }>("/api/pbs/servers", { method: "POST", body: JSON.stringify({
        ...form, id: form.id || undefined, token_secret: form.token_secret || undefined,
      }) })
      await reloadConnections()
      setSelected(result.id)
      setForm(emptyForm)
      setMessage(t("pbs.saved"))
    } catch (err) { setError(err instanceof Error ? err.message : t("pbs.saveFailed")) }
    finally { setBusy(false) }
  }

  const remove = async () => {
    if (!form.id || !window.confirm(t("pbs.removeConfirm"))) return
    setBusy(true); setError(""); setMessage("")
    try {
      await fetchApi(`/api/pbs/servers/${encodeURIComponent(form.id)}`, { method: "DELETE" })
      setForm(emptyForm)
      await reloadConnections()
    } catch (err) { setError(err instanceof Error ? err.message : t("pbs.saveFailed")) }
    finally { setBusy(false) }
  }
  const now = Date.now() / 1000

  return <div className="space-y-4 md:space-y-6">
    {!localOnly && <div className="flex flex-wrap items-center gap-3">
      <h2 className="flex items-center text-2xl font-semibold text-foreground"><Server className="mr-2 h-5 w-5" />{t("pbs.title")}</h2>
      <Select value={selected || undefined} onValueChange={setSelected}>
        <SelectTrigger aria-label={t("pbs.server")} className="w-full sm:ml-auto sm:w-56"><SelectValue placeholder={t("pbs.chooseServer")} /></SelectTrigger>
        <SelectContent>
          {connections?.local_available && <SelectItem value="local">{t("pbs.thisNode")}</SelectItem>}
          {connections?.servers.map(row => <SelectItem key={row.id} value={row.id}>{row.name}</SelectItem>)}
        </SelectContent>
      </Select>
      <Button variant="outline" size="sm" disabled={isLoading || !selected} onClick={() => mutate()}>
        <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />{t("pbs.refresh")}
      </Button>
      <Button variant="outline" size="sm" onClick={() => setManage(!manage)}>
        <Settings2 className="mr-2 h-4 w-4" />{t("pbs.manage")}
      </Button>
    </div>}
    {(connectionError || statusError) && <p role="alert" className="text-sm text-red-500">
      {String((connectionError || statusError)?.message || t("pbs.loadFailed"))}</p>}
    {isLoading && <p role="status" className="text-sm text-muted-foreground">{t("pbs.loading")}</p>}
    {!selected && !connectionError && connections && <p className="text-sm text-muted-foreground">{t("pbs.noServer")}</p>}
    {!localOnly && !manage && (connections?.detected?.length || 0) > 0 && <Card className="bg-card border-border">
      <CardHeader><CardTitle className="flex items-center text-foreground"><DatabaseBackup className="mr-2 h-5 w-5" />{t("pbs.detectedTitle")}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{t("pbs.detectedHelp")}</p>
        {connections?.detected?.map(row => <div key={row.url} className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-foreground">{row.name}</span>
            <span className="block break-all font-mono text-xs text-muted-foreground">{row.url}</span>
          </span>
          <Button size="sm" className="bg-blue-600 text-white hover:bg-blue-700" onClick={() => {
            setForm({ ...emptyForm, name: row.name, url: row.url, fingerprint: row.fingerprint })
            setError(""); setMessage(""); setManage(true)
          }}>{t("pbs.connect")}</Button>
        </div>)}
      </CardContent>
    </Card>}
    {manage && !localOnly && <Card>
      <CardHeader><CardTitle>{t("pbs.manage")}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{t("pbs.permissionsHelp")}</p>
        <Select value={form.id || NEW_CONNECTION} onValueChange={value => {
          const row = connections?.servers.find(item => item.id === value)
          setForm(row ? { ...row, token_secret: "" } : emptyForm)
        }}>
          <SelectTrigger aria-label={t("pbs.editConnection")} className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={NEW_CONNECTION}>{t("pbs.add")}</SelectItem>
            {connections?.servers.map(row => <SelectItem key={row.id} value={row.id}>{row.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <div className="grid gap-4 md:grid-cols-2">
          {(["name", "url", "token_id", "token_secret", "fingerprint"] as const).map(field =>
            <div key={field} className="space-y-2">
              <Label htmlFor={`pbs-${field}`}>{t(`pbs.${field}`)}</Label>
              <Input id={`pbs-${field}`} disabled={busy} type={field === "token_secret" ? "password" : field === "url" ? "url" : "text"}
                autoComplete={field === "token_secret" ? "new-password" : "off"}
                value={form[field]} onChange={event => setForm({ ...form, [field]: event.target.value })} />
            </div>)}
        </div>
        <p className="text-xs text-muted-foreground">{t("pbs.tlsHelp")}</p>
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        {message && <p role="status" className="text-sm text-green-500">{message}</p>}
        <div className="flex gap-2">
          <Button disabled={busy} onClick={save}>{busy ? t("pbs.testing") : t("pbs.save")}</Button>
          {form.id && <Button variant="destructive" disabled={busy} onClick={remove}>{t("pbs.remove")}</Button>}
        </div>
      </CardContent>
    </Card>}
    {data && <>
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>{data.name} · PBS {data.version || "—"} · {t("pbs.updatedAt", { time: new Date(data.fetched_at * 1000).toLocaleTimeString() })}</span>
        {Object.keys(data.services).length > 0 && Object.values(data.services).every(state => state === "active")
          ? <Badge variant="outline" className={badgeTone.ok}>{t("pbs.servicesActive")}</Badge>
          : Object.entries(data.services).filter(([, state]) => state !== "active").map(([service, state]) =>
            <Badge key={service} variant="outline" className={badgeTone.error}>{service}: {state}</Badge>)}
      </div>
      {Object.entries(data.errors).map(([section, detail]) => <p key={section} role="alert" className="text-sm text-amber-500">{t(`pbs.${section}`)}: {detail}</p>)}

      <Card className="bg-card border-border">
        <CardHeader><CardTitle className="flex items-center text-foreground"><Database className="mr-2 h-5 w-5" />{t("pbs.datastores")}</CardTitle></CardHeader>
        <CardContent>
          {data.datastores?.length === 0 && <p className="text-sm text-muted-foreground">{t("pbs.noDatastores")}</p>}
          {data.datastores && data.datastores.length > 0 && <div className="space-y-4">
            {data.datastores.map(store => <PBSDatastoreCard key={store.name} store={store} />)}
          </div>}
        </CardContent>
      </Card>

      <Card className="bg-card border-border">
        <CardHeader><CardTitle className="flex items-center text-foreground"><Activity className="mr-2 h-5 w-5" />{t("pbs.tasks")}</CardTitle></CardHeader>
        <CardContent>
          {data.tasks?.length === 0 && <p className="text-sm text-muted-foreground">{t("pbs.noTasks")}</p>}
          {data.tasks && data.tasks.length > 0 && <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="py-2 pr-3 font-medium">{t("pbs.task")}</th>
              <th className="py-2 pr-3 font-medium">{t("pbs.started")}</th>
              <th className="py-2 pr-3 font-medium">{t("pbs.duration")}</th>
              <th className="py-2 font-medium">{t("pbs.status")}</th>
            </tr></thead>
            <tbody>{data.tasks.map(row => {
              const Icon = TASK_ICONS[row.worker_type || ""] || Activity
              const state = taskState(row)
              const end = row.endtime ?? (state === "running" ? now : undefined)
              return <tr key={row.upid} className="border-b border-border/60 last:border-0">
                <td className="py-2 pr-3"><span className="flex items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="text-foreground">{row.worker_type}</span>
                  {row.worker_id && <span className="truncate text-muted-foreground">{row.worker_id}</span>}
                </span></td>
                <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-muted-foreground">{row.starttime ? new Date(row.starttime * 1000).toLocaleString() : "—"}</td>
                <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-muted-foreground">{row.starttime && end ? formatDuration(end - row.starttime) : "—"}</td>
                <td className="py-2"><Badge variant="outline" className={`${badgeTone[state]} max-w-[16rem] truncate`} title={row.status}>
                  {state === "running" ? t("pbs.running") : row.status || "—"}
                </Badge></td>
              </tr>
            })}</tbody>
          </table></div>}
        </CardContent>
      </Card>

      <Card className="bg-card border-border">
        <CardHeader><CardTitle className="flex items-center text-foreground"><ListChecks className="mr-2 h-5 w-5" />{t("pbs.jobs")}</CardTitle></CardHeader>
        <CardContent>
          {(() => {
            const jobs = (["sync", "verify", "prune"] as const).flatMap(kind => (data[kind] || []).map(row => ({ kind, row })))
            if (jobs.length === 0) return <p className="text-sm text-muted-foreground">{t("pbs.noJobs")}</p>
            return <div className="overflow-x-auto"><table className="w-full text-sm">
              <thead><tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-medium">{t("pbs.job")}</th>
                <th className="py-2 pr-3 font-medium">{t("pbs.datastores")}</th>
                <th className="py-2 pr-3 font-medium">{t("pbs.schedule")}</th>
                <th className="py-2 font-medium">{t("pbs.status")}</th>
              </tr></thead>
              <tbody>{jobs.map(({ kind, row }) => <tr key={`${kind}-${row.id}`} className="border-b border-border/60 last:border-0">
                <td className="py-2 pr-3"><span className="text-foreground">{t(`pbs.${kind}`)}</span> <span className="text-muted-foreground">· {row.id}</span></td>
                <td className="py-2 pr-3 text-muted-foreground">{row.store || "—"}</td>
                <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">{row.schedule || "—"}</td>
                <td className="py-2"><Badge variant="outline" className={badgeTone[jobState(row["last-run-state"])]}>{row["last-run-state"] || "—"}</Badge></td>
              </tr>)}</tbody>
            </table></div>
          })()}
        </CardContent>
      </Card>
    </>}
  </div>
}
