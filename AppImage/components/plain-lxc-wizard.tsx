"use client"

import { useEffect, useImperativeHandle, useRef, useState, type ComponentProps, type FormEvent, type ReactNode, type Ref } from "react"
import { ArrowLeft, ArrowRight, ClipboardCheck, Download, HardDrive, KeyRound, Network, Plus, Server } from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { Button } from "./ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog"
import { Input } from "./ui/input"
import { Textarea } from "./ui/textarea"

const API = "/api/plain-lxc/v1"
const RECEIPT = "proxmenux.plainLxc.operation.v1"
const groups = [
  { key: "system", icon: Server },
  { key: "access", icon: KeyRound },
  { key: "resources", icon: HardDrive },
  { key: "network", icon: Network },
  { key: "review", icon: ClipboardCheck },
]
const selectClass = "min-h-9 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm"
const finalStates = new Set(["succeeded", "failed", "partial", "not_submitted"])
const rejected = new Set(["confirmation_required", "plan_changed", "warnings_unaccepted", "invalid_field",
  "invalid_ssh_key", "architecture_unsupported", "bridge_unavailable", "catalog_unavailable",
  "disk_space_insufficient", "node_capacity_exceeded", "node_not_local", "request_conflict",
  "storage_unavailable", "target_operation_pending", "template_architecture_mismatch",
  "template_already_present", "template_checksum_mismatch", "template_unverified", "vmid_in_use"])

type Access = "password" | "ssh_key" | "both"
type Context = {
  node: string
  architecture: string
  next_vmid: number
  templates: string[]
  catalog: string[]
  catalog_state: "available" | "empty" | "unavailable"
  template_storages: string[]
  storages: string[]
  bridges: Record<string, { vlan_supported: boolean }>
  limits: { cores: number; ram_mib: number }
  defaults: {
    cpu: { cores: number }; memory: { ram_mib: number; swap_mib: number }
    rootfs: { size_gib: number }; nesting: boolean; onboot: boolean
    start_after_create: boolean; prepare_system: boolean
  }
}
type Draft = {
  vmid: string; hostname: string; template: string; access: Access; keys: string
  storage: string; disk: string; cores: string; ram: string; swap: string
  bridge: string; vlan: string; staticIp: boolean; cidr: string; gateway: string; dns: string; domains: string
  nesting: boolean; onboot: boolean; start: boolean; prepare: boolean
}
type Summary = {
  node: string; vmid: number; hostname: string; template: { volume_id: string }
  access: { mode: Access }; rootfs: { storage: string; size_gib: number }; cpu: { cores: number }
  memory: { ram_mib: number; swap_mib: number }
  network: null | { bridge: string; vlan_tag?: number; ipv4: { mode: string; cidr?: string; gateway?: string } }
  dns: { nameservers: string[]; search_domains: string[] }
  nesting: boolean; onboot: boolean; start_after_create: boolean; prepare_system: boolean
}
type Checked = { check: string; receipt: string }
type Plan = Checked & { summary: Summary; warnings: string[] }
type Action = "create" | "download_template"
type Receipt = { ticket: string; action: Action }
type Operation = ({ action: "create"; vmid: number } | { action: "download_template"; volume_id: string }) &
  { status: string; phase: string; reason?: string; task_warnings: boolean }
type WizardHandle = { dismissSuccessfulCreate: () => void }

function initialDraft(context: Context): Draft {
  const defaults = context.defaults
  return {
    vmid: String(context.next_vmid), hostname: "", template: "", access: "password", keys: "",
    storage: context.storages[0] ?? "", disk: String(defaults.rootfs.size_gib),
    cores: String(defaults.cpu.cores), ram: String(defaults.memory.ram_mib), swap: String(defaults.memory.swap_mib),
    bridge: "", vlan: "", staticIp: false, cidr: "", gateway: "", dns: "", domains: "",
    nesting: defaults.nesting, onboot: defaults.onboot, start: defaults.start_after_create, prepare: defaults.prepare_system,
  }
}

function suggestedHostname(template: string) {
  return template.split("/").at(-1)?.split(/[_-]/)[0]?.toLowerCase() ?? ""
}

function specFor(context: Context, draft: Draft) {
  return {
    node: context.node, vmid: Number(draft.vmid), hostname: draft.hostname.trim(),
    template: { volume_id: draft.template },
    access: { mode: draft.access, ssh_public_keys: draft.access === "password" ? [] : draft.keys.split(/\r?\n/).map(key => key.trim()).filter(Boolean) },
    rootfs: { storage: draft.storage, size_gib: Number(draft.disk) }, cpu: { cores: Number(draft.cores) },
    memory: { ram_mib: Number(draft.ram), swap_mib: Number(draft.swap) },
    network: draft.bridge ? {
      bridge: draft.bridge, ...(draft.vlan && { vlan_tag: Number(draft.vlan) }),
      ipv4: draft.staticIp ? { mode: "static", cidr: draft.cidr.trim(), ...(draft.gateway.trim() && { gateway: draft.gateway.trim() }) } : { mode: "dhcp" },
    } : null,
    dns: draft.bridge ? { nameservers: draft.dns.split(/\s+/).filter(Boolean), search_domains: draft.domains.split(/\s+/).filter(Boolean) } : {},
    nesting: draft.nesting, onboot: draft.onboot, start_after_create: draft.start, prepare_system: draft.prepare,
  }
}

function errorCode(error: unknown) {
  return (error as { body?: { error?: string } })?.body?.error ?? "unavailable"
}

function selectTemplate(draft: Draft, template: string): Draft {
  return { ...draft, template, hostname: !draft.hostname || draft.hostname === suggestedHostname(draft.template)
    ? suggestedHostname(template) : draft.hostname }
}

function TemplateDownload({ context, onDownload, busy, t }: {
  context: Context
  onDownload: (template: string, storage: string) => void
  busy: boolean
  t: (key: string) => string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [template, setTemplate] = useState("")
  const [storage, setStorage] = useState(context.template_storages[0] ?? "")
  const available = context.catalog.filter(name => name.toLowerCase().includes(query.trim().toLowerCase()))

  if (context.catalog_state === "unavailable") {
    return <p className="text-sm text-muted-foreground">{t("error.catalog_unavailable")}</p>
  }
  if (!context.catalog.length) return null
  if (!context.template_storages.length) {
    return <p className="text-sm text-muted-foreground">{t("noTemplateStorage")}</p>
  }

  return <div className="rounded-lg border border-border bg-card p-3">
    <Button variant="ghost" type="button" size="sm" className="h-auto whitespace-normal px-1 py-1 text-start"
      aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <Download className="mr-2 h-4 w-4 shrink-0" aria-hidden="true" />{t("downloadTemplate")}
    </Button>
    {open && <div className="mt-3 space-y-3">
      <Input type="search" value={query} aria-label={t("searchTemplates")} placeholder={t("searchTemplates")}
        onChange={event => setQuery(event.target.value)} />
      <label className="block space-y-1 text-sm">
        <span>{t("officialTemplate")}</span>
        <select className={selectClass} value={available.includes(template) ? template : ""}
          onChange={event => setTemplate(event.target.value)}>
          <option value="">{t(available.length ? "selectTemplate" : "noMatchingTemplates")}</option>
          {available.map(name => <option key={name}>{name}</option>)}
        </select>
      </label>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 space-y-1 text-sm">
          <span>{t("templateStorage")}</span>
          <select className={selectClass} value={storage} onChange={event => setStorage(event.target.value)}>
            {context.template_storages.map(name => <option key={name}>{name}</option>)}
          </select>
        </label>
        <Button type="button" disabled={busy || !storage || !available.includes(template)}
          onClick={() => onDownload(template, storage)}>
          <Download className="mr-2 h-4 w-4" aria-hidden="true" />{t("confirmDownload")}
        </Button>
      </div>
    </div>}
  </div>
}

export function PlainLxcCreate({ onCreated }: { onCreated: () => void }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const wizard = useRef<WizardHandle>(null)

  function changeOpen(nextOpen: boolean) {
    if (!nextOpen) wizard.current?.dismissSuccessfulCreate()
    setOpen(nextOpen)
  }

  return <Dialog open={open} onOpenChange={changeOpen}>
    <DialogTrigger asChild>
      <Button className="w-full shrink-0 sm:w-auto" size="sm" variant="secondary">
        <Plus className="mr-1.5 h-4 w-4" aria-hidden="true" />{t("plainLxc.create")}
      </Button>
    </DialogTrigger>
    <DialogContent className="max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-2xl overflow-y-auto p-4 sm:p-6">
      <DialogHeader className="pr-6">
        <DialogTitle className="flex items-center gap-2">
          <Server className="h-5 w-5 shrink-0 text-blue-500" aria-hidden="true" />{t("plainLxc.create")}
        </DialogTitle>
        <DialogDescription>{t("plainLxc.description")}</DialogDescription>
      </DialogHeader>
      {open && <PlainLxcWizard ref={wizard} onCreated={onCreated} />}
    </DialogContent>
  </Dialog>
}

function PlainLxcWizard({ ref, onCreated }: { ref: Ref<WizardHandle>; onCreated: () => void }) {
  const translate = useT()
  const t = (key: string) => translate("plainLxc." + key)
  const [context, setContext] = useState<Context | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [step, setStep] = useState(0)
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [plan, setPlan] = useState<Plan | null>(null)
  const [accepted, setAccepted] = useState<string[]>([])
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [operation, setOperation] = useState<Operation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)
  const draftRevision = useRef(0)
  const submitting = useRef(false)
  const mounted = useRef(false)
  const notified = useRef(false)
  const onCreatedRef = useRef(onCreated)
  onCreatedRef.current = onCreated

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    try {
      const saved = sessionStorage.getItem(RECEIPT)
      if (saved) {
        setReceipt(saved.startsWith("{") ? JSON.parse(saved) as Receipt : { ticket: saved, action: "create" })
        return
      }
    } catch {
      setError("storage_unavailable_browser")
      return
    }
    fetchApi<Context>(API + "/context", { signal: controller.signal }).then(data => {
      setContext(data)
      setDraft(initialDraft(data))
    }).catch(error => { if (!controller.signal.aborted) setError(errorCode(error)) })
    return () => controller.abort()
  }, [refresh])

  const state = operation?.status
  useImperativeHandle(ref, () => ({
    dismissSuccessfulCreate() {
      if (operation?.action === "create" && state === "succeeded") {
        sessionStorage.removeItem(RECEIPT)
      }
    },
  }), [operation?.action, state])

  useEffect(() => {
    if (!receipt || busy || (state && finalStates.has(state))) return
    const { ticket } = receipt
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function status() {
      try {
        const data = await fetchApi<Operation>(API + "/status", {
          headers: { "X-ProxMenux-LXC-Receipt": ticket }, signal: controller.signal,
        })
        if (controller.signal.aborted) return
        setOperation(data)
        setError("")
        if (!finalStates.has(data.status)) timer = setTimeout(status, 2500)
      } catch (error) {
        if (controller.signal.aborted) return
        const code = errorCode(error)
        setError(code)
        if (code !== "receipt_invalid") timer = setTimeout(status, 5000)
      }
    }
    void status()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [receipt, busy, state])

  useEffect(() => {
    if (operation?.action === "create" && (state === "succeeded" || state === "partial") && !notified.current) {
      notified.current = true
      onCreatedRef.current()
    }
  }, [operation?.action, state])

  function invalidate() {
    draftRevision.current++
    setPlan(null)
    setAccepted([])
    setError("")
  }

  function update(patch: Partial<Draft>) {
    invalidate()
    setDraft(current => current && { ...current, ...patch })
  }

  async function next(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !context || !draft) return
    if (draft.access !== "ssh_key" && (step === 1 || step === 4)) {
      if (password.length < 5 || password !== confirmation) {
        setStep(1)
        setError(password.length < 5 ? "invalid_field" : "password_mismatch")
        return
      }
    }
    if (step === 1 && draft.access !== "password" && /PRIVATE KEY/.test(draft.keys)) {
      setError("invalid_ssh_key")
      return
    }
    if (step < 4) {
      setError("")
      setStep(step + 1)
      return
    }
    invalidate()
    const revision = draftRevision.current
    setBusy(true)
    try {
      const result = await fetchApi<Plan>(API + "/plan", {
        method: "POST", body: JSON.stringify({ spec: specFor(context, draft) }),
      })
      if (revision === draftRevision.current) setPlan(result)
    } catch (error) {
      setError(errorCode(error))
    } finally {
      setBusy(false)
    }
  }

  async function submit(action: Action, prepare: () => Promise<{ ticket: string; body: unknown }>) {
    if (busy || submitting.current) return
    submitting.current = true
    setBusy(true)
    setError("")
    try {
      const { ticket, body } = await prepare()
      if (!mounted.current) return
      const pending = { ticket, action }
      try {
        sessionStorage.setItem(RECEIPT, JSON.stringify(pending))
      } catch {
        setError("storage_unavailable_browser")
        return
      }
      setReceipt(pending)
      setOperation(await fetchApi<Operation>(API + (action === "create" ? "/create" : "/download"), {
        method: "POST", body: JSON.stringify(body),
      }))
    } catch (error) {
      if (!mounted.current) return
      const code = errorCode(error)
      if (rejected.has(code)) {
        sessionStorage.removeItem(RECEIPT)
        setReceipt(null)
        if (action === "create") setPlan(null)
      }
      setError(code)
    } finally {
      if (action === "create") {
        setPassword("")
        setConfirmation("")
      }
      setBusy(false)
      submitting.current = false
    }
  }

  function create() {
    if (!plan || !plan.warnings.every(warning => accepted.includes(warning))) return
    void submit("create", async () => ({
      ticket: plan.receipt,
      body: { check: plan.check, confirmed: true, accepted_warnings: plan.warnings,
        ...(plan.summary.access.mode !== "ssh_key" && { password }) },
    }))
  }

  function download(template: string, storage: string) {
    if (!context) return
    void submit("download_template", async () => {
      const checked = await fetchApi<Checked>(API + "/download/plan", {
        method: "POST", body: JSON.stringify({ node: context.node, catalog_id: template, template_storage: storage }),
      })
      return { ticket: checked.receipt, body: { check: checked.check, confirmed: true } }
    })
  }

  async function returnFromDownload() {
    if (busy) return
    setBusy(true)
    setError("")
    try {
      const fresh = await fetchApi<Context>(API + "/context")
      const volume = operation?.action === "download_template" && state === "succeeded" ? operation.volume_id : null
      const selected = volume && fresh.templates.includes(volume) ? volume : ""
      sessionStorage.removeItem(RECEIPT)
      invalidate()
      setContext(fresh)
      setDraft(current => {
        const next = current ?? initialDraft(fresh)
        return selected ? selectTemplate(next, selected) : next
      })
      if (volume && !selected) setError("template_unverified")
      setOperation(null)
      setReceipt(null)
    } catch (error) {
      setError(errorCode(error))
    } finally {
      setBusy(false)
    }
  }

  async function loadKey(file: File | undefined) {
    if (!file) return
    const revision = draftRevision.current
    try {
      if (file.size > 32768) throw new Error()
      const key = (await file.text()).trim()
      if (revision !== draftRevision.current) return
      if (!key || /PRIVATE KEY/.test(key)) throw new Error()
      invalidate()
      setDraft(current => current && { ...current, keys: [current.keys.trim(), key].filter(Boolean).join("\n") })
    } catch {
      setError("invalid_ssh_key")
    }
  }

  function clearResult() {
    sessionStorage.removeItem(RECEIPT)
    setOperation(null)
    setReceipt(null)
    setContext(null)
    setDraft(null)
    setStep(0)
    invalidate()
    notified.current = false
    setRefresh(value => value + 1)
  }

  const errorMessage = error && <p role="alert" className="rounded-md border border-destructive/40 p-2 text-sm text-destructive">
    {t(["password_mismatch", "plan_changed", "vmid_in_use", "template_unverified", "template_checksum_mismatch",
      "disk_space_insufficient", "bridge_unavailable", "storage_unavailable_browser", "receipt_invalid",
      "target_operation_pending", "invalid_field", "invalid_ssh_key", "catalog_unavailable",
      "template_already_present", "storage_unavailable"].includes(error) ? "error." + error : "error.unavailable")}
  </p>
  const downloading = receipt?.action === "download_template"
  if (receipt) return <div className="space-y-3">
    <div className="rounded-lg border border-border bg-card p-4">
      {operation?.action === "download_template" &&
        <p className="mb-1 break-all text-sm text-muted-foreground">{operation.volume_id}</p>}
      <p role="status" className="font-semibold">
        {operation?.action === "create" && `LXC ${operation.vmid} · `}
        {t((downloading ? "downloadStatus." : "status.") + (state ?? "awaiting"))}
      </p>
    </div>
    {operation?.task_warnings && <p className="text-sm text-muted-foreground">{t("taskWarnings")}</p>}
    {!downloading && operation?.status === "partial" && <p className="text-sm text-muted-foreground">{t("partialHelp")}</p>}
    {errorMessage}
    <div className="flex flex-wrap justify-end gap-2">
      <DialogClose asChild><Button type="button" variant="outline">{t("close")}</Button></DialogClose>
      {((state && finalStates.has(state)) || error === "receipt_invalid") && (downloading
        ? <Button type="button" disabled={busy} onClick={() => void returnFromDownload()}>
          {t(state === "succeeded" ? "useTemplate" : "returnToSystem")}
        </Button>
        : <Button type="button" onClick={clearResult}>{t("newDraft")}</Button>)}
    </div>
  </div>

  if (!context || !draft) return <div className="space-y-3">
    {errorMessage || <p role="status" className="text-sm text-muted-foreground">{t("loading")}</p>}
    {error && <Button type="button" variant="outline" onClick={() => { setError(""); setRefresh(value => value + 1) }}>{t("retry")}</Button>}
  </div>

  const field = (key: string, child: ReactNode) => <label className="block space-y-1 text-sm">
    <span>{t(key)}</span>{child}
  </label>
  const input = (name: "hostname" | "vmid" | "disk" | "cores" | "ram" | "swap" | "vlan" | "cidr" | "gateway" | "dns" | "domains",
    label: string, options: ComponentProps<typeof Input> = {}) =>
    field(label, <Input value={draft[name]} onChange={event => update({ [name]: event.target.value })} {...options} />)
  const check = (key: "nesting" | "onboot" | "start" | "prepare" | "staticIp", label: string) =>
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={draft[key]} onChange={event => update({ [key]: event.target.checked })} />
      {t(label)}
    </label>
  const number = (min: number, max: number) => ({ type: "number", min, max, step: 1, required: true })
  const summary = plan?.summary
  const yesNo = (enabled: boolean) => t(enabled ? "yes" : "no")
  const rows = summary ? [
    [t("system"), `${summary.node} · LXC ${summary.vmid} · ${summary.hostname}`, summary.template.volume_id,
      `${t("nesting")} · ${yesNo(summary.nesting)} / ${t("onboot")} · ${yesNo(summary.onboot)}`],
    [t("access"), t("access_" + summary.access.mode)],
    [t("resources"), `${summary.rootfs.storage} · ${summary.rootfs.size_gib} GiB`,
      `${t("cores")} · ${summary.cpu.cores} / RAM · ${summary.memory.ram_mib} MiB / Swap · ${summary.memory.swap_mib} MiB`],
    [t("network"), summary.network ? [summary.network.bridge, summary.network.vlan_tag && `VLAN ${summary.network.vlan_tag}`,
      summary.network.ipv4.cidr ?? "DHCP", summary.network.ipv4.gateway].filter(Boolean).join(" · ") : t("noNetwork"),
      ...(summary.network ? [`DNS · ${summary.dns.nameservers.join(", ") || t("hostDns")}`, summary.dns.search_domains.join(", ")] : [])],
    [t("review"), `${t("start")} · ${yesNo(summary.start_after_create)} / ${t("prepare")} · ${yesNo(summary.prepare_system)}`],
  ] : []

  return <>
    <ol className="grid grid-cols-5 gap-1" aria-label={t("steps")}>
      {groups.map(({ key, icon: Icon }, index) => <li key={key} aria-current={index === step ? "step" : undefined}
        className={`flex min-w-0 flex-col items-center gap-1 rounded-md px-0.5 py-2 text-center text-[10px] sm:px-1 sm:text-xs ${step === index ? "bg-blue-500/10 font-medium text-blue-600 dark:text-blue-400" : "text-muted-foreground"}`}>
        <Icon className="h-4 w-4" aria-hidden="true" />{t(key)}
      </li>)}
    </ol>
    <form className="space-y-3" onSubmit={next}>
      <fieldset disabled={busy} className="space-y-3">
        {step === 0 && <>
          <div className="grid gap-3 sm:grid-cols-2">
            {field("node", <Input readOnly value={context.node} />)}
            {input("vmid", "vmid", number(100, 999999999))}
          </div>
          {field("template", <select className={selectClass} required value={draft.template} onChange={event => {
            const value = event.target.value
            update(selectTemplate(draft, value))
          }}>
            <option value="">{t("selectTemplate")}</option>
            {context.templates.map(template => <option key={template}>{template}</option>)}
          </select>)}
          {!context.templates.length && <p role="status" className="text-sm text-muted-foreground">{t("noTemplates")}</p>}
          <TemplateDownload context={context} busy={busy} onDownload={download} t={t} />
          {input("hostname", "hostname", { required: true, maxLength: 253 })}
          <details><summary className="cursor-pointer text-sm">{t("advanced")}</summary>
            <div className="mt-2 space-y-2">{check("nesting", "nesting")}{check("onboot", "onboot")}</div>
          </details>
        </>}
        {step === 1 && <>
          {field("access", <select className={selectClass} value={draft.access} onChange={event => {
            setPassword("")
            setConfirmation("")
            update({ access: event.target.value as Access })
          }}>{(["password", "ssh_key", "both"] as const).map(mode => <option key={mode} value={mode}>{t("access_" + mode)}</option>)}</select>)}
          {draft.access !== "ssh_key" && <div className="grid gap-3 sm:grid-cols-2">
            {field("password", <Input type="password" autoComplete="new-password" required minLength={5} maxLength={256}
              value={password} onChange={event => { invalidate(); setPassword(event.target.value) }} />)}
            {field("confirmPassword", <Input type="password" autoComplete="new-password" required maxLength={256}
              value={confirmation} onChange={event => { invalidate(); setConfirmation(event.target.value) }} />)}
          </div>}
          {draft.access !== "password" && <>
            {field("publicKeys", <Textarea required maxLength={32768}
              value={draft.keys} onChange={event => update({ keys: event.target.value })} />)}
            {field("keyFile", <Input type="file" accept=".pub,.txt" onChange={event => {
              void loadKey(event.target.files?.[0])
              event.target.value = ""
            }} />)}
          </>}
        </>}
        {step === 2 && <div className="grid gap-3 sm:grid-cols-2">
          {field("storage", <select className={selectClass} required value={draft.storage} onChange={event => update({ storage: event.target.value })}>
            <option value="">{t("selectStorage")}</option>
            {context.storages.map(storage => <option key={storage}>{storage}</option>)}
          </select>)}
          {input("disk", "disk", number(1, 65536))}
          {input("cores", "cores", number(1, Math.min(8192, context.limits.cores)))}
          {input("ram", "ram", number(16, Math.min(4194304, context.limits.ram_mib)))}
          {input("swap", "swap", number(0, 4194304))}
        </div>}
        {step === 3 && <>
          {field("bridge", <select className={selectClass} value={draft.bridge}
            onChange={event => update({ bridge: event.target.value, vlan: "" })}>
            <option value="">{t("noNetwork")}</option>
            {Object.keys(context.bridges).map(bridge => <option key={bridge}>{bridge}</option>)}
          </select>)}
          {draft.bridge && <>
            {context.bridges[draft.bridge]?.vlan_supported && input("vlan", "vlan", { ...number(1, 4094), required: false })}
            {check("staticIp", "staticIp")}
            {draft.staticIp && <div className="grid gap-3 sm:grid-cols-2">
              {input("cidr", "cidr", { required: true, placeholder: "192.0.2.10/24" })}
              {input("gateway", "gateway")}
            </div>}
            <div className="grid gap-3 sm:grid-cols-2">
              {input("dns", "dns", { placeholder: t("hostDns") })}
              {input("domains", "domains", { placeholder: t("hostDns") })}
            </div>
          </>}
        </>}
        {step === 4 && <>
          {check("start", "start")}{check("prepare", "prepare")}
          {summary && <div className="space-y-2">
            {rows.map(([label, ...values], index) => <section key={label} className="rounded-md border p-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{label}</h3>
                {index < 4 && <Button type="button" size="sm" variant="ghost"
                  onClick={() => { invalidate(); setStep(index) }}>{t("edit")}</Button>}
              </div>
              {values.filter(Boolean).map((value, valueIndex) => <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]" key={valueIndex}>{value}</p>)}
            </section>)}
            {plan.warnings.map(warning => <label key={warning} className="flex items-start gap-2 rounded-md border p-2 text-sm">
              <input type="checkbox" className="mt-1" checked={accepted.includes(warning)}
                onChange={event => setAccepted(current => event.target.checked ? [...current, warning] : current.filter(value => value !== warning))} />
              {t("warning." + warning)}
            </label>)}
          </div>}
        </>}
      </fieldset>
      {errorMessage}
      <div className="flex flex-wrap justify-between gap-2 border-t pt-3">
        <DialogClose asChild><Button type="button" variant="outline">{t("cancel")}</Button></DialogClose>
        <div className="flex flex-wrap justify-end gap-2">
          {step > 0 && <Button type="button" variant="outline" disabled={busy}
            onClick={() => { invalidate(); setStep(step - 1) }}><ArrowLeft className="mr-1 h-4 w-4" />{t("back")}</Button>}
          {step < 4 && <Button type="submit" disabled={busy || (step === 0 && !context.templates.length)}>
            {t("next")}<ArrowRight className="ml-1 h-4 w-4" />
          </Button>}
          {step === 4 && !plan && <Button type="submit" disabled={busy}>{t(busy ? "checking" : "check")}</Button>}
          {step === 4 && plan && <Button type="button" disabled={busy || !plan.warnings.every(warning => accepted.includes(warning))}
            onClick={() => void create()}>{t("confirmCreate")}</Button>}
        </div>
      </div>
    </form>
  </>
}
