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
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import { PBSDatastoreCard, type PBSDatastore } from "./pbs-datastore-usage"
import { PBSProblemMessage } from "./pbs-problem-message"
import { pbsDiagnostic, pbsResultText, pbsServiceState, pbsTaskType, formatPBSDuration } from "../lib/pbs-messages"
import { fetchApi } from "../lib/api-config"
import { useT, useI18n } from "../lib/i18n/provider"

interface Connection { id: string; name: string; url: string; token_id: string; fingerprint: string; has_token: boolean }
interface Detected { name: string; url: string; fingerprint: string }
interface Connections { local_available: boolean; servers: Connection[]; detected?: Detected[] }
interface Task { upid: string; worker_type?: string; worker_id?: string; starttime?: number; endtime?: number; status?: string }
interface Job { id: string; store?: string; schedule?: string; "last-run-state"?: string }
interface PBSStatus {
  name: string; version: string | null; fetched_at: number; services: Record<string, string>;
  datastores: PBSDatastore[] | null; tasks: Task[] | null;
  sync: Job[] | null; verify: Job[] | null; prune: Job[] | null; errors: Record<string, string>;
  error_details?: Record<string, { code: string; params?: Record<string, unknown> }>;
}

const emptyForm = { id: "", name: "", url: "", token_id: "", fingerprint: "", token_secret: "", username: "", password: "" }
type Method = "password" | "token"
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

// PBS reports "unknown", "OK", "WARNINGS: n" or an error; no state is still running.
function taskState(task: Task): keyof typeof badgeTone {
  if (!task.status) return task.endtime ? "muted" : "running"
  if (task.status === "unknown") return "muted"
  if (task.status === "OK") return "ok"
  if (task.status.startsWith("WARNINGS")) return "warn"
  return "error"
}

// PBS reports "OK", "WARNINGS: n" or the error text of the last run.
function jobState(state?: string): keyof typeof badgeTone {
  if (!state || state === "unknown") return "muted"
  if (state.toLowerCase() === "ok") return "ok"
  if (state.toLowerCase().startsWith("warn")) return "warn"
  return "error"
}

// `localOnly` is the PBS host's own Monitor: no connection picker, the
// header Refresh already reloads the page data. Its tabs show one `view` each.
export function PBSPanel({ localOnly = false, view = "all" }: { localOnly?: boolean; view?: "all" | "datastores" | "tasks" } = {}) {
  const showStores = view !== "tasks"
  const showTasks = view !== "datastores"
  const t = useT()
  const { language } = useI18n()
  const { data: connections, error: connectionError, mutate: reloadConnections } = useSWR<Connections>(
    "/api/pbs/servers", url => fetchApi<Connections>(url), { revalidateOnFocus: false })
  const [selected, setSelected] = useState("")
  const [manage, setManage] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [method, setMethod] = useState<Method>("password")
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState<unknown>(null)
  const [errorFallback, setErrorFallback] = useState("pbs.saveFailed")
  const { data, error: statusError, isLoading, mutate } = useSWR<PBSStatus>(
    selected ? `/api/pbs/status?server=${encodeURIComponent(selected)}` : null,
    url => fetchApi<PBSStatus>(url), { refreshInterval: 30000, revalidateOnFocus: false })

  useEffect(() => {
    if (!connections) return
    if (selected === "local" && connections.local_available) return
    if (connections.servers.some(row => row.id === selected)) return
    setSelected(connections.local_available ? "local" : connections.servers[0]?.id || "")
  }, [connections, selected])

  const openManage = (next = emptyForm) => {
    setForm(next); setMethod(next.id ? "token" : "password"); setError(""); setMessage(""); setManage(true)
  }

  const save = async () => {
    setErrorFallback("pbs.saveFailed")
    setBusy(true); setError(""); setMessage("")
    let saved = false
    try {
      // A password is sent once to create a read-only token; only the token is kept.
      const { username, password, ...connection } = form
      const result = !form.id && method === "password"
        ? await fetchApi<{ id: string }>("/api/pbs/servers/login", { method: "POST", body: JSON.stringify({
          name: form.name, url: form.url, fingerprint: form.fingerprint, username, password,
        }) })
        : await fetchApi<{ id: string }>("/api/pbs/servers", { method: "POST", body: JSON.stringify({
          ...connection, id: form.id || undefined, token_secret: form.token_secret || undefined,
        }) })
      saved = true
      await reloadConnections()
      setSelected(result.id)
      setForm(emptyForm)
      setManage(false)
    } catch (err) { setError(saved ? { body: { code: "pbs_saved_refresh_failed" }, message: pbsDiagnostic(err) } : err) }
    finally { setBusy(false) }
  }

  const remove = async () => {
    if (!form.id || !window.confirm(t("pbs.removeConfirm"))) return
    setErrorFallback("pbs.removeFailed")
    setBusy(true); setError(""); setMessage("")
    let removed = false
    try {
      await fetchApi(`/api/pbs/servers/${encodeURIComponent(form.id)}`, { method: "DELETE" })
      removed = true
      setForm(emptyForm)
      await reloadConnections()
    } catch (err) { setError(removed ? { body: { code: "pbs_removed_refresh_failed" }, message: pbsDiagnostic(err) } : err) }
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
      <Button variant="outline" size="sm" onClick={() => openManage()}>
        <Settings2 className="mr-2 h-4 w-4" />{t("pbs.manage")}
      </Button>
    </div>}
    {(connectionError || statusError) && <div role="alert" className="text-sm text-red-500">
      <PBSProblemMessage problem={connectionError || statusError} raw={pbsDiagnostic(connectionError || statusError)} />
    </div>}
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
          <Button size="sm" className="bg-blue-600 text-white hover:bg-blue-700"
            onClick={() => openManage({ ...emptyForm, name: row.name, url: row.url, fingerprint: row.fingerprint })}>
            {t("pbs.connect")}
          </Button>
        </div>)}
      </CardContent>
    </Card>}
    {!localOnly && <Dialog open={manage} onOpenChange={open => { if (!busy) setManage(open) }}>
      <DialogContent className="grid-cols-1 max-w-2xl max-h-[85vh] overflow-y-auto bg-accent [&_input]:bg-background [&_[role=combobox]]:bg-background">
        <DialogHeader>
          <DialogTitle>{t("pbs.manage")}</DialogTitle>
          <DialogDescription>{method === "password" && !form.id ? t("pbs.passwordHelp") : t("pbs.permissionsHelp")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>{t("pbs.editConnection")}</Label>
            <Select value={form.id || NEW_CONNECTION} disabled={busy} onValueChange={value => {
              const row = connections?.servers.find(item => item.id === value)
              setForm(row ? { ...emptyForm, ...row, token_secret: "" } : emptyForm)
              setMethod(row ? "token" : "password"); setError("")
            }}>
              <SelectTrigger aria-label={t("pbs.editConnection")} className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={NEW_CONNECTION}>{t("pbs.add")}</SelectItem>
                {connections?.servers.map(row => <SelectItem key={row.id} value={row.id}>{row.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {!form.id && <div className="space-y-2">
            <Label>{t("pbs.signInWith")}</Label>
            <div className="grid grid-cols-2 gap-2">
              {(["password", "token"] as const).map(option =>
                <Button key={option} type="button" variant="outline" disabled={busy} onClick={() => { setMethod(option); setError("") }}
                  className={method === option ? "border-blue-600 bg-blue-600/15 text-foreground hover:bg-blue-600/20" : "bg-background"}>
                  {t(option === "password" ? "pbs.methodPassword" : "pbs.methodToken")}
                </Button>)}
            </div>
          </div>}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {(["name", "url", ...(method === "password" && !form.id ? ["username", "password"] : ["token_id", "token_secret"]), "fingerprint"] as const).map(field => {
              const secret = field === "token_secret" || field === "password"
              const help = field === "url" ? "pbs.urlHelp" : field === "username" ? "pbs.usernameHelp"
                : field === "token_id" ? "pbs.tokenIdHelp" : field === "token_secret"
                  ? form.id ? "pbs.tokenSecretKeepHelp" : "pbs.tokenSecretHelp" : undefined
              return <div key={field} className="min-w-0 space-y-2">
                <Label htmlFor={`pbs-${field}`} className="block leading-5">{t(`pbs.${field}`)}</Label>
                <Input id={`pbs-${field}`} disabled={busy} type={secret ? "password" : field === "url" ? "url" : "text"}
                  aria-describedby={help ? `pbs-${field}-help` : undefined}
                  autoComplete={secret ? "new-password" : "off"} placeholder={field === "username" ? "root@pam" : undefined}
                  value={form[field as keyof typeof form]} onChange={event => setForm({ ...form, [field]: event.target.value })} />
                {help && <p id={`pbs-${field}-help`} className="text-xs text-muted-foreground">{t(help)}</p>}
              </div>
            })}
          </div>
          <p className="text-xs text-muted-foreground">{t("pbs.tlsHelp")}</p>
          {!!error && <div role="alert" className="text-sm text-red-500">
            <PBSProblemMessage problem={error} raw={pbsDiagnostic(error)} fallback={errorFallback} />
          </div>}
          {message && <p role="status" className="text-sm text-green-500">{message}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            {form.id && <Button variant="outline" disabled={busy} className="mr-auto text-red-500 hover:text-red-500" onClick={remove}>
              <Trash2 className="mr-2 h-4 w-4" />{t("pbs.remove")}
            </Button>}
            <Button variant="outline" disabled={busy} onClick={() => setManage(false)}>{t("pbs.cancel")}</Button>
            <Button className="bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-600/50 disabled:text-white disabled:opacity-100"
              disabled={busy || !form.url.trim() || !form.name.trim()} onClick={save}>
              {busy ? t("pbs.testing") : t("pbs.save")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>}
    {data && <>
      {!localOnly && <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>{data.name} · PBS {data.version || "—"} · {t("pbs.updatedAt", { time: new Date(data.fetched_at * 1000).toLocaleTimeString(language) })}</span>
        {Object.keys(data.services).length > 0 && Object.values(data.services).every(state => state === "active")
          ? <Badge variant="outline" className={badgeTone.ok}>{t("pbs.servicesActive")}</Badge>
          : Object.entries(data.services).filter(([, state]) => state !== "active").map(([service, state]) =>
            <Badge key={service} variant="outline" className={badgeTone.error}>{service}: {pbsServiceState(state, t)}</Badge>)}
      </div>}
      {Object.entries(data.errors).filter(([section]) => section === "datastores" ? showStores : showTasks)
        .map(([section, detail]) => <div key={section} role="alert" className="text-sm text-amber-500">
          <p className="font-medium">{t(`pbs.${["datastores", "tasks", "sync", "verify", "prune"].includes(section) ? section : "title"}`)}</p>
          <PBSProblemMessage problem={data.error_details?.[section]} raw={detail} />
        </div>)}

      {showStores && <Card className="bg-card border-border">
        <CardHeader><CardTitle className="flex items-center text-foreground"><Database className="mr-2 h-5 w-5" />{t("pbs.datastores")}</CardTitle></CardHeader>
        <CardContent>
          {data.datastores?.length === 0 && <p className="text-sm text-muted-foreground">{t("pbs.noDatastores")}</p>}
          {data.datastores && data.datastores.length > 0 && <div className="space-y-4">
            {data.datastores.map(store => <PBSDatastoreCard key={store.name} store={store} />)}
          </div>}
        </CardContent>
      </Card>}

      {showTasks && <>
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
                  <span className="text-foreground" title={row.worker_type}>{pbsTaskType(row.worker_type, t)}</span>
                  {row.worker_id && <span className="truncate text-muted-foreground">{row.worker_id}</span>}
                </span></td>
                <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-muted-foreground">{row.starttime ? new Date(row.starttime * 1000).toLocaleString(language) : "—"}</td>
                <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-muted-foreground">{row.starttime && end ? formatPBSDuration(end - row.starttime, t) : "—"}</td>
                <td className="py-2">
                  <PBSResultBadge status={row.status} running={state === "running"} tone={badgeTone[state]} />
                </td>
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
                <td className="py-2"><PBSResultBadge status={row["last-run-state"]} tone={badgeTone[jobState(row["last-run-state"])]} /></td>
              </tr>)}</tbody>
            </table></div>
          })()}
        </CardContent>
      </Card>
      </>}
    </>}
  </div>
}

function PBSResultBadge({ status, running = false, tone }: { status?: string; running?: boolean; tone: string }) {
  const t = useT()
  const badge = <Badge variant="outline" className={`${tone} max-w-[16rem] truncate`}>
    {running ? t("pbs.running") : pbsResultText(status, t)}
  </Badge>
  if (running || !status || status === "unknown" || /^ok$/i.test(status) || /^WARNINGS:\s*\d+\s*$/i.test(status)) return badge
  return <details className="max-w-xs">
    <summary className="cursor-pointer" aria-label={t("pbs.technicalDetails")}>{badge}</summary>
    <pre className="mt-1 whitespace-pre-wrap break-words text-xs text-muted-foreground">{status}</pre>
  </details>
}
