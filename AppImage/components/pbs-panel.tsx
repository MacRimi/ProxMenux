"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { fetchApi } from "../lib/api-config"
import { formatBytes } from "../lib/utils"
import { useT } from "../lib/i18n/provider"

interface Connection { id: string; name: string; url: string; token_id: string; fingerprint: string; has_token: boolean }
interface Connections { local_available: boolean; servers: Connection[] }
interface Datastore { name: string; path?: string; total?: number | null; used?: number | null; avail?: number | null; error?: string }
interface Task { upid: string; worker_type?: string; worker_id?: string; starttime?: number; endtime?: number; status?: string }
interface Job { id: string; store?: string; schedule?: string; "last-run-state"?: string }
interface PBSStatus {
  name: string; version: string | null; fetched_at: number; services: Record<string, string>;
  datastores: Datastore[] | null; tasks: Task[] | null;
  sync: Job[] | null; verify: Job[] | null; prune: Job[] | null; errors: Record<string, string>;
}

const emptyForm = { id: "", name: "", url: "", token_id: "", fingerprint: "", token_secret: "" }
const selectClass = "h-10 rounded-md border bg-background px-3 text-sm"

export function PBSPanel() {
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
  const capacity = (value?: number | null) => value == null ? "—" : formatBytes(value)

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-3">
      <h2 className="text-xl font-semibold">{t("pbs.title")}</h2>
      <select aria-label={t("pbs.server")} className={`${selectClass} sm:ml-auto`} value={selected}
        onChange={event => setSelected(event.target.value)}>
        {!selected && <option value="">{t("pbs.chooseServer")}</option>}
        {connections?.local_available && <option value="local">{t("pbs.local")}</option>}
        {connections?.servers.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
      </select>
      <Button variant="outline" disabled={isLoading || !selected} onClick={() => mutate()}>{t("pbs.refresh")}</Button>
      <Button variant="outline" onClick={() => setManage(!manage)}>{t("pbs.manage")}</Button>
    </div>
    {(connectionError || statusError) && <p role="alert" className="text-sm text-red-500">
      {String((connectionError || statusError)?.message || t("pbs.loadFailed"))}</p>}
    {isLoading && <p role="status" className="text-sm text-muted-foreground">{t("pbs.loading")}</p>}
    {!selected && !connectionError && connections && <p className="text-sm text-muted-foreground">{t("pbs.noServer")}</p>}
    {manage && <Card>
      <CardHeader><CardTitle>{t("pbs.manage")}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{t("pbs.permissionsHelp")}</p>
        <select aria-label={t("pbs.editConnection")} className={`${selectClass} w-full`} value={form.id}
          onChange={event => {
            const row = connections?.servers.find(item => item.id === event.target.value)
            setForm(row ? { ...row, token_secret: "" } : emptyForm)
          }}>
          <option value="">{t("pbs.add")}</option>
          {connections?.servers.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select>
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
      <p className="text-sm text-muted-foreground">{data.name} · PBS {data.version || "—"} · {t("pbs.sampled")} {new Date(data.fetched_at * 1000).toLocaleTimeString()}</p>
      {Object.keys(data.services).length > 0 && <div className="flex flex-wrap gap-3 text-sm">
        {Object.entries(data.services).map(([service, state]) => <span key={service} className={state === "active" ? "text-green-500" : "text-red-500"}>{service}: {state}</span>)}
      </div>}
      {Object.entries(data.errors).map(([section, detail]) => <p key={section} role="alert" className="text-sm text-amber-500">{t(`pbs.${section}`)}: {detail}</p>)}
      <Card><CardHeader><CardTitle>{t("pbs.datastores")}</CardTitle></CardHeader><CardContent>
        {data.datastores?.length === 0 && <p className="text-sm text-muted-foreground">{t("pbs.noDatastores")}</p>}
        {data.datastores && data.datastores.length > 0 && <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="border-b text-left"><th className="p-2">{t("pbs.name")}</th><th>{t("pbs.total")}</th><th>{t("pbs.used")}</th><th>{t("pbs.free")}</th></tr></thead>
          <tbody>{data.datastores.map(row => <tr key={row.name} className="border-b"><td className="p-2 font-medium">{row.name}{row.error && <p className="font-normal text-xs text-amber-500">{row.error}</p>}</td><td>{capacity(row.total)}</td><td>{capacity(row.used)}</td><td>{capacity(row.avail)}</td></tr>)}</tbody>
        </table></div>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>{t("pbs.tasks")}</CardTitle></CardHeader><CardContent>
        {data.tasks?.length === 0 && <p className="text-sm text-muted-foreground">{t("pbs.noTasks")}</p>}
        {data.tasks && data.tasks.length > 0 && <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="border-b text-left"><th className="p-2">{t("pbs.task")}</th><th>{t("pbs.started")}</th><th>{t("pbs.status")}</th></tr></thead>
          <tbody>{data.tasks.map(row => <tr key={row.upid} className="border-b"><td className="p-2">{row.worker_type} {row.worker_id}</td><td>{row.starttime ? new Date(row.starttime * 1000).toLocaleString() : "—"}</td><td>{row.status || (row.endtime ? "—" : t("pbs.running"))}</td></tr>)}</tbody>
        </table></div>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>{t("pbs.jobs")}</CardTitle></CardHeader><CardContent>
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="border-b text-left"><th className="p-2">{t("pbs.job")}</th><th>{t("pbs.datastores")}</th><th>{t("pbs.schedule")}</th><th>{t("pbs.status")}</th></tr></thead>
          <tbody>{(["sync", "verify", "prune"] as const).flatMap(kind => (data[kind] || []).map(row =>
            <tr key={`${kind}-${row.id}`} className="border-b"><td className="p-2">{t(`pbs.${kind}`)} · {row.id}</td><td>{row.store || "—"}</td><td>{row.schedule || "—"}</td><td>{row["last-run-state"] || "—"}</td></tr>))}</tbody>
        </table></div>
      </CardContent></Card>
    </>}
  </div>
}
