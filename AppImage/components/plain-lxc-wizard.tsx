"use client"

import { useEffect, useImperativeHandle, useRef, useState, type ComponentProps, type FormEvent, type ReactNode, type Ref } from "react"
import { ArrowLeft, ArrowRight, Check, ChevronDown, ChevronRight, Circle, ClipboardCheck, Download, HardDrive, Info, KeyRound, Network, Loader2, Plus, Server, SquareTerminal, TriangleAlert, X } from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { Button } from "./ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Switch } from "./ui/switch"
import { Progress } from "./ui/progress"
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
const primary = "bg-blue-500 hover:bg-blue-600 text-white"
const switchClass = "data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border"
// The Monitor's select. An empty choice, which the list itself cannot hold,
// travels as NONE.
const NONE = "__none__"
function Choice({ value, onChange, options, placeholder, empty, label }: {
  value: string
  onChange: (value: string) => void
  options: { value: string; label?: string }[]
  placeholder?: string
  empty?: string
  label?: string
}) {
  const known = value === "" ? (empty ? NONE : "") : options.some(option => option.value === value) ? value : ""
  return <Select value={known} onValueChange={next => onChange(next === NONE ? "" : next)}>
    <SelectTrigger className="w-full min-w-0 [&>span]:truncate" aria-label={label}><SelectValue placeholder={placeholder} /></SelectTrigger>
    <SelectContent>
      {empty && <SelectItem value={NONE}>{empty}</SelectItem>}
      {options.map(option => <SelectItem key={option.value} value={option.value}>{option.label ?? option.value}</SelectItem>)}
    </SelectContent>
  </Select>
}
const finalStates = new Set(["succeeded", "failed", "partial", "not_submitted"])
const rejected = new Set(["confirmation_required", "plan_changed", "warnings_unaccepted", "invalid_field",
  "invalid_ssh_key", "architecture_unsupported", "bridge_unavailable", "catalog_unavailable",
  "disk_space_insufficient", "node_capacity_exceeded", "node_not_local", "request_conflict",
  "storage_unavailable", "target_operation_pending", "template_architecture_mismatch",
  "template_already_present", "template_checksum_mismatch", "template_unverified", "vmid_in_use",
  "resource_unavailable", "resource_unsupported", "resource_in_use"])

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
  capabilities: { mount_points: number; devices: number }
  hardware: Hardware[]
  hardware_errors: boolean
  defaults: {
    cpu: { cores: number }; memory: { ram_mib: number; swap_mib: number }
    rootfs: { size_gib: number }; nesting: boolean; onboot: boolean
    start_after_create: boolean; prepare_system: boolean
  }
}
type Hardware = { id: string; profile: string; name: string; paths: string[] }
type Mount = {
  type: "volume" | "bind"; storage: string; size: string; source: string; path: string
  read_only: boolean; backup: boolean
}
type Draft = {
  vmid: string; hostname: string; template: string; access: Access; keys: string
  storage: string; disk: string; cores: string; ram: string; swap: string
  bridge: string; vlan: string; staticIp: boolean; cidr: string; gateway: string; dns: string; domains: string
  nesting: boolean; onboot: boolean; start: boolean; prepare: boolean
  mounts: Mount[]; hardware: string[]
}
type Summary = {
  node: string; vmid: number; hostname: string; template: { volume_id: string }
  access: { mode: Access }; rootfs: { storage: string; size_gib: number }; cpu: { cores: number }
  memory: { ram_mib: number; swap_mib: number }
  network: null | { bridge: string; vlan_tag?: number; ipv4: { mode: string; cidr?: string; gateway?: string } }
  dns: { nameservers: string[]; search_domains: string[] }
  nesting: boolean; onboot: boolean; start_after_create: boolean; prepare_system: boolean
  mounts: { type: "volume" | "bind"; storage?: string; size_gib?: number; source?: string; path: string; read_only: boolean }[]
  hardware: string[]
}
type Checked = { check: string; receipt: string }
type Plan = Checked & { summary: Summary; warnings: string[] }
type Action = "create" | "download_template"
// What is being made travels with the receipt, so a reopened view still names it.
type Receipt = { ticket: string; action: Action; title?: string; detail?: string }
type Operation = ({ action: "create"; vmid: number } | { action: "download_template"; volume_id: string }) &
  { status: string; phase: string; reason?: string; task_warnings: boolean; progress?: number | null
    steps?: string[]; preparing?: boolean; warned?: string[]; warning_lines?: Record<string, string[]> }
type WizardHandle = { dismissSuccessfulCreate: () => void }

function initialDraft(context: Context): Draft {
  const defaults = context.defaults
  return {
    vmid: String(context.next_vmid), hostname: "", template: "", access: "password", keys: "",
    storage: context.storages[0] ?? "", disk: String(defaults.rootfs.size_gib),
    cores: String(defaults.cpu.cores), ram: String(defaults.memory.ram_mib), swap: String(defaults.memory.swap_mib),
    bridge: "", vlan: "", staticIp: false, cidr: "", gateway: "", dns: "", domains: "",
    nesting: defaults.nesting, onboot: defaults.onboot, start: defaults.start_after_create, prepare: defaults.prepare_system,
    mounts: [], hardware: [],
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
    mounts: draft.mounts.map(mount => mount.type === "volume"
      ? { type: "volume", storage: mount.storage, size_gib: Number(mount.size), path: mount.path.trim(),
        read_only: mount.read_only, backup: mount.backup }
      : { type: "bind", source: mount.source.trim(), path: mount.path.trim(), read_only: mount.read_only, backup: false }),
    hardware: draft.hardware.flatMap(id => {
      const item = context.hardware.find(candidate => candidate.id === id)
      return item ? [{ profile: item.profile, selection_id: item.id }] : []
    }),
  }
}

// Mount points, as the console wizard offers them: a new volume on a
// container storage, or an existing host directory.
function MountPoints({ context, mounts, onChange, t }: {
  context: Context; mounts: Mount[]; onChange: (mounts: Mount[]) => void; t: (key: string) => string
}) {
  const blank = (): Mount => ({ type: "volume", storage: context.storages[0] ?? "", size: "8", source: "", path: "/data",
    read_only: false, backup: true })
  const [adding, setAdding] = useState<Mount | null>(null)
  const full = mounts.length >= context.capabilities.mount_points
  const valid = adding && adding.path.trim().startsWith("/") && (adding.type === "bind"
    ? adding.source.trim().startsWith("/") : Boolean(adding.storage) && Number(adding.size) >= 1)
  const edit = (patch: Partial<Mount>) => setAdding(current => current && { ...current, ...patch })

  return <section className="space-y-2">
    <h3 className="text-sm font-semibold">{t("mounts")}</h3>
    {mounts.map((mount, index) => <div key={index} className="flex items-center justify-between gap-2 rounded-md border bg-card p-2 text-sm">
      <span className="min-w-0 [overflow-wrap:anywhere]">
        {mount.type === "volume" ? `${mount.storage} · ${mount.size} GiB` : mount.source} → {mount.path}
        {mount.read_only && <span className="text-muted-foreground"> · {t("readOnly")}</span>}
      </span>
      <Button type="button" size="sm" variant="ghost" onClick={() => onChange(mounts.filter((_, other) => other !== index))}>
        {t("remove")}
      </Button>
    </div>)}
    {adding ? <div className="space-y-3 rounded-md border bg-card p-3">
      <label className="block space-y-1 text-sm"><span>{t("mountType")}</span>
        <Choice value={adding.type} label={t("mountType")} onChange={value => edit(value === "bind"
          ? { type: "bind", read_only: true, backup: false } : { type: "volume", read_only: false, backup: true })}
          options={[{ value: "volume", label: t("mountVolume") }, { value: "bind", label: t("mountBind") }]} />
      </label>
      {adding.type === "volume"
        ? <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1 text-sm"><span>{t("mountStorage")}</span>
            <Choice value={adding.storage} label={t("mountStorage")} onChange={value => edit({ storage: value })}
              options={context.storages.map(storage => ({ value: storage }))} />
          </label>
          <label className="block space-y-1 text-sm"><span>{t("mountSize")}</span>
            <Input type="number" min={1} max={65536} value={adding.size} onChange={event => edit({ size: event.target.value })} />
          </label>
        </div>
        : <label className="block space-y-1 text-sm"><span>{t("mountSource")}</span>
          <Input value={adding.source} placeholder="/mnt/data" onChange={event => edit({ source: event.target.value })} />
        </label>}
      <label className="block space-y-1 text-sm"><span>{t("mountPath")}</span>
        <Input value={adding.path} onChange={event => edit({ path: event.target.value })} />
      </label>
      <label className="flex items-center gap-3 text-sm">
        <Switch className={switchClass} checked={adding.read_only} onCheckedChange={checked => edit({ read_only: checked })} />{t("readOnly")}
      </label>
      {adding.type === "volume" && <label className="flex items-center gap-3 text-sm">
        <Switch className={switchClass} checked={adding.backup} onCheckedChange={checked => edit({ backup: checked })} />{t("backupVolume")}
      </label>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => setAdding(null)}>{t("cancel")}</Button>
        <Button type="button" className={primary} disabled={!valid}
          onClick={() => { onChange([...mounts, adding]); setAdding(null) }}>{t("add")}</Button>
      </div>
    </div>
      : <Button type="button" variant="outline" size="sm" disabled={full} onClick={() => setAdding(blank())}>
        <Plus className="mr-1.5 h-4 w-4" aria-hidden="true" />{t("addMount")}
      </Button>}
  </section>
}

// The verified devices of the host. Two choices that share a device node,
// as a GPU and its ROCm profile, cannot be taken together.
function HardwareChoice({ context, selected, onChange, t }: {
  context: Context; selected: string[]; onChange: (selected: string[]) => void; t: (key: string) => string
}) {
  // The AMD compute interface is shared by every AMD GPU.
  const taken = new Set(context.hardware.filter(item => selected.includes(item.id)).flatMap(item => item.paths)
    .filter(path => path !== "/dev/kfd"))
  const chosen = context.hardware.filter(item => selected.includes(item.id))
  return <section className="space-y-2">
    <h3 className="text-sm font-semibold">{t("hardware")}</h3>
    {context.hardware_errors && <p className="text-sm text-muted-foreground">{t("hardwareErrors")}</p>}
    {!context.hardware.length
      ? <p className="text-sm text-muted-foreground">{t("noHardware")}</p>
      : context.hardware.map(item => {
        const on = selected.includes(item.id)
        const blocked = !on && (item.paths.some(path => taken.has(path)) || selected.length >= context.capabilities.devices)
        return <label key={item.id} className={`flex items-center gap-3 rounded-md border bg-card p-2 text-sm ${blocked ? "opacity-50" : ""}`}>
          <Switch className={switchClass} checked={on} disabled={blocked}
            onCheckedChange={checked => onChange(checked ? [...selected, item.id] : selected.filter(id => id !== item.id))} />
          <span className="min-w-0 [overflow-wrap:anywhere]">{item.name}</span>
        </label>
      })}
    {chosen.some(item => item.profile === "nvidia-runtime") && <p className="text-sm text-muted-foreground">{t("nvidiaNote")}</p>}
    {chosen.some(item => item.paths.some(path => /^\/dev\/(bus\/usb\/|ttyUSB|ttyACM)/.test(path))) &&
      <p className="text-sm text-muted-foreground">{t("usbNote")}</p>}
  </section>
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
      {/* The search narrows this list; a template is chosen from it. */}
      <div className="space-y-1 text-sm">
        <span id="official-templates">{t("officialTemplate")}</span>
        {available.length
          ? <div role="listbox" aria-labelledby="official-templates" className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border p-1">
            {available.map(name => <button key={name} type="button" role="option" aria-selected={name === template}
              onClick={() => setTemplate(name)}
              className={`block w-full rounded px-2 py-1.5 text-left [overflow-wrap:anywhere] ${name === template
                ? "border border-blue-500 bg-blue-500/10 text-blue-600 dark:text-blue-400" : "border border-transparent bg-card hover:bg-muted"}`}>
              {name}
            </button>)}
          </div>
          : <p className="text-muted-foreground">{t("noMatchingTemplates")}</p>}
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 space-y-1 text-sm">
          <span>{t("templateStorage")}</span>
          <Choice value={storage} onChange={setStorage} label={t("templateStorage")}
            options={context.template_storages.map(name => ({ value: name }))} />
        </label>
        <Button type="button" className={primary} disabled={busy || !storage || !available.includes(template)}
          onClick={() => onDownload(template, storage)}>
          <Download className="mr-2 h-4 w-4" aria-hidden="true" />{t("confirmDownload")}
        </Button>
      </div>
    </div>}
  </div>
}

type StepState = "pending" | "running" | "done" | "warned" | "failed" | "uncertain"
// The engine reports these while a created container waits for its next task.
const AWAITING_NEXT = new Set(["awaiting_start", "awaiting_preparation"])
const NEXT_NOT_SENT = new Set(["start_not_submitted", "preparation_not_submitted"])
const LOGGED = new Set(["create", "prepare", "start"])

// Each native task of the request, and where it stands.
function stepStates(operation: Operation | null, action: Action): { phase: string; state: StepState }[] {
  const status = operation?.status ?? "awaiting"
  const sent: StepState = status === "awaiting" ? "running" : status === "not_submitted" ? "failed" : "done"
  if (!operation || sent !== "done") {
    return [{ phase: "submit", state: sent }, { phase: action === "create" ? "create" : "download", state: "pending" }]
  }
  const steps = operation.steps?.length ? operation.steps : [operation.phase]
  let current = Math.max(0, steps.indexOf(operation.phase))
  let state: StepState = status === "succeeded" ? "done" : status === "running" ? "running"
    : status === "unknown" ? "uncertain" : "failed"
  if (status === "running" && AWAITING_NEXT.has(operation.reason ?? "")) current += 1
  if (status === "partial" && NEXT_NOT_SENT.has(operation.reason ?? "")) {
    current += 1
    state = "failed"
  }
  return [{ phase: "submit", state: "done" }, ...steps.map((phase, index) => {
    const finished: StepState = operation.warned?.includes(phase) ? "warned" : "done"
    if (index < current) return { phase, state: finished }
    if (index > current) return { phase, state: "pending" as StepState }
    return { phase, state: state === "done" ? finished : state }
  })]
}

function clock(ms: number) {
  const seconds = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
}

// The native Proxmox task log of one step, followed while the step runs.
function TaskLog({ ticket, phase, live, t }: { ticket: string; phase: string; live: boolean; t: (key: string) => string }) {
  const [lines, setLines] = useState<string[]>([])
  const [missing, setMissing] = useState(false)
  const view = useRef<HTMLPreElement>(null)
  // Lines already shown; a step that finishes goes on from there.
  const shown = useRef(0)
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function read() {
      try {
        for (;;) {
          const page = await fetchApi<{ lines: string[]; next_offset: number | null }>(
            `${API}/log?phase=${phase}&offset=${shown.current}`,
            { headers: { "X-ProxMenux-LXC-Receipt": ticket }, signal: controller.signal })
          if (controller.signal.aborted) return
          shown.current += page.lines.length
          if (page.lines.length) setLines(current => [...current, ...page.lines])
          setMissing(false)
          if (page.next_offset === null) break
        }
      } catch {
        if (controller.signal.aborted) return
        setMissing(true)
      }
      if (live) timer = setTimeout(read, 2000)
    }
    void read()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [ticket, phase, live])
  useEffect(() => {
    if (view.current) view.current.scrollTop = view.current.scrollHeight
  }, [lines])
  if (!lines.length) return missing || !live
    ? <p className="text-xs text-muted-foreground">{t("logUnavailable")}</p>
    : <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" aria-hidden="true" />
  return <pre ref={view} className="max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-background p-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
    {lines.join("\n")}
  </pre>
}

function OperationProgress({ receipt, operation, t }: {
  receipt: Receipt; operation: Operation | null; t: (key: string) => string
}) {
  const steps = stepStates(operation, receipt.action)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [now, setNow] = useState(() => Date.now())
  // When this view saw each step start and end; steps already finished when
  // it opened carry no time.
  const times = useRef<Record<string, { from?: number; to?: number }>>({})
  const seen = Date.now()
  for (const { phase, state } of steps) {
    const time = times.current[phase] ??= {}
    if (state === "running" && time.from === undefined) time.from = seen
    if (state !== "running" && state !== "pending" && time.from !== undefined && time.to === undefined) time.to = seen
  }
  const running = steps.some(step => step.state === "running")
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const label = (phase: string) => t("phase." + (phase === "start" && operation?.preparing ? "prepareStart" : phase))
  const icon = (state: StepState) => ({
    pending: <Circle className="h-4 w-4 text-muted-foreground/50" />,
    running: <Loader2 className="h-4 w-4 animate-spin text-blue-500" />,
    uncertain: <Loader2 className="h-4 w-4 animate-spin text-amber-500" />,
    done: <Check className="h-4 w-4 text-green-500" />,
    warned: <TriangleAlert className="h-4 w-4 text-amber-500" />,
    failed: <X className="h-4 w-4 text-destructive" />,
  })[state]
  return <ol className="space-y-1" aria-label={t("steps")}>
    {steps.map(({ phase, state }) => {
      const time = times.current[phase]
      const elapsed = time?.from !== undefined ? clock((time.to ?? now) - time.from) : ""
      const logged = LOGGED.has(phase) && state !== "pending" && operation?.action === "create"
      const shown = open[phase] ?? state === "failed"
      return <li key={phase} className="rounded-md px-2 py-1.5">
        <div className="flex items-center gap-3">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center" aria-hidden="true">{icon(state)}</span>
          <span className={`min-w-0 flex-1 text-sm ${state === "pending" ? "text-muted-foreground" : state === "failed" ? "text-destructive" : ""}`}>
            {label(phase)}
          </span>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{elapsed}</span>
        </div>
        {phase === "download" && state === "running" && <div className="ml-8 mt-2 flex items-center gap-3">
          {typeof operation?.progress === "number"
            ? <Progress value={operation.progress} className="h-2 [&>div]:bg-blue-500" aria-label={label(phase)} />
            : <div className="h-2 w-full overflow-hidden rounded-full bg-secondary" aria-hidden="true">
              <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-500" />
            </div>}
          <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
            {typeof operation?.progress === "number" ? `${operation.progress}%` : ""}
          </span>
        </div>}
        {state === "warned" && operation?.warning_lines?.[phase]?.map(line =>
          <p key={line} className="ml-8 mt-1 text-xs text-amber-600 [overflow-wrap:anywhere] dark:text-amber-400">{line}</p>)}
        {logged && <div className="ml-8 mt-1 space-y-1">
          <button type="button" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            aria-expanded={shown} onClick={() => setOpen(current => ({ ...current, [phase]: !shown }))}>
            {shown ? <ChevronDown className="h-3 w-3" aria-hidden="true" /> : <ChevronRight className="h-3 w-3" aria-hidden="true" />}
            {t(shown ? "hideLog" : "showLog")}
          </button>
          {shown && <TaskLog ticket={receipt.ticket} phase={phase} live={state === "running" || state === "uncertain"} t={t} />}
        </div>}
      </li>
    })}
  </ol>
}

// Opened by its own button, or by a caller that holds `open` (the Catalog tab).
export function PlainLxcCreate({ onCreated, open: held, onOpenChange, onOpenTerminal }: {
  onCreated: () => void; open?: boolean; onOpenChange?: (open: boolean) => void
  onOpenTerminal?: (vmid: number, name: string) => void
}) {
  const t = useT()
  const [own, setOwn] = useState(false)
  const [editing, setEditing] = useState(false)
  const open = held ?? own
  const wizard = useRef<WizardHandle>(null)

  function changeOpen(nextOpen: boolean) {
    if (!nextOpen) wizard.current?.dismissSuccessfulCreate()
    if (held === undefined) setOwn(nextOpen)
    onOpenChange?.(nextOpen)
  }

  return <Dialog open={open} onOpenChange={changeOpen}>
    {held === undefined && <DialogTrigger asChild>
      <Button className="w-full shrink-0 sm:w-auto" size="sm" variant="secondary">
        <Plus className="mr-1.5 h-4 w-4" aria-hidden="true" />{t("plainLxc.create")}
      </Button>
    </DialogTrigger>}
    {/* Until Review the dialog is a form being edited: brighter behind, the
        fields sunken (the project's edit-mode contrast). */}
    <DialogContent className={`max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-2xl overflow-y-auto p-4 sm:p-6 ${editing
      ? "bg-accent [&_input:not([readonly])]:bg-background [&_textarea]:bg-background [&_[role=combobox]]:bg-background" : ""}`}>
      <DialogHeader className="pr-6">
        <DialogTitle className="flex items-center gap-2">
          <Server className="h-5 w-5 shrink-0 text-blue-500" aria-hidden="true" />{t("plainLxc.create")}
        </DialogTitle>
        <DialogDescription>{t("plainLxc.description")}</DialogDescription>
      </DialogHeader>
      {open && <PlainLxcWizard ref={wizard} onCreated={onCreated} onEditing={setEditing}
        onOpenTerminal={onOpenTerminal && ((vmid, name) => { changeOpen(false); onOpenTerminal(vmid, name) })} />}
    </DialogContent>
  </Dialog>
}

function PlainLxcWizard({ ref, onCreated, onEditing, onOpenTerminal }: {
  ref: Ref<WizardHandle>; onCreated: () => void; onEditing?: (editing: boolean) => void
  onOpenTerminal?: (vmid: number, name: string) => void
}) {
  const translate = useT()
  const t = (key: string) => translate("plainLxc." + key)
  const [context, setContext] = useState<Context | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [step, setStep] = useState(0)
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [plan, setPlan] = useState<Plan | null>(null)
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
  const lastPlan = useRef<Plan | null>(null)
  if (plan) lastPlan.current = plan
  const editing = Boolean(context && draft && !receipt && step < 4)
  useEffect(() => { onEditing?.(editing) }, [editing, onEditing])
  useEffect(() => {
    if (step === 4 && !plan && !busy && !error && !receipt && context && draft) void checkPlan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, plan, busy, error, receipt, context, draft])
  useImperativeHandle(ref, () => ({
    dismissSuccessfulCreate() {
      if (operation?.action === "create" && state === "succeeded") {
        sessionStorage.removeItem(RECEIPT)
      }
    },
  }), [operation?.action, state])

  useEffect(() => {
    // The request stays open while Proxmox works; each step, and the share of
    // a download, is read meanwhile.
    if (!receipt || (state && finalStates.has(state))) return
    const { ticket, action } = receipt
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
        if (!finalStates.has(data.status)) timer = setTimeout(status, action === "download_template" ? 1000 : 1500)
      } catch (error) {
        if (controller.signal.aborted) return
        const code = errorCode(error)
        setError(code)
        if (code !== "receipt_invalid") timer = setTimeout(status, 5000)
      }
    }
    void status()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [receipt, state])

  // A template downloaded here is the one wanted: back to System with it chosen.
  useEffect(() => {
    if (operation?.action === "download_template" && state === "succeeded") void returnFromDownload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operation?.action, state])

  useEffect(() => {
    if (operation?.action === "create" && (state === "succeeded" || state === "partial") && !notified.current) {
      notified.current = true
      onCreatedRef.current()
    }
  }, [operation?.action, state])

  function invalidate() {
    draftRevision.current++
    setPlan(null)
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
    if ((step === 0 && !draft.template) || (step === 2 && !draft.storage)) {
      setError("invalid_field")
      return
    }
    if (step < 4) {
      setError("")
      setStep(step + 1)
      return
    }
    await checkPlan()
  }

  // Review shows the checked plan as soon as it opens, and again after any
  // change made there.
  async function checkPlan() {
    if (busy || !context || !draft) return
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

  async function submit(action: Action, prepare: () => Promise<{ ticket: string; body: unknown; label?: { title: string; detail: string } }>,
    present?: () => void) {
    if (busy || submitting.current) return
    submitting.current = true
    setBusy(true)
    setError("")
    try {
      const { ticket, body, label } = await prepare()
      if (!mounted.current) return
      const pending: Receipt = { ticket, action, ...label }
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
      if (code === "template_already_present" && present) {
        sessionStorage.removeItem(RECEIPT)
        setReceipt(null)
        present()
        return
      }
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
    if (!plan) return
    const summary = plan.summary
    const label = {
      title: `LXC ${summary.vmid} · ${summary.hostname}`,
      detail: [summary.template.volume_id.split("/").pop(), `${summary.rootfs.storage} · ${summary.rootfs.size_gib} GiB`,
        `${summary.cpu.cores} CPU · ${summary.memory.ram_mib} MiB`, ...summary.hardware].join(" · "),
    }
    void submit("create", async () => ({
      ticket: plan.receipt, label,
      body: { check: plan.check, confirmed: true, accepted_warnings: plan.warnings,
        ...(plan.summary.access.mode !== "ssh_key" && { password }) },
    }))
  }

  // Choose a template that is on the node, reading the node again when this
  // view does not list it yet.
  async function chooseTemplate(volume: string) {
    if (context?.templates.includes(volume)) {
      update(selectTemplate(draft!, volume))
      return
    }
    try {
      const fresh = await fetchApi<Context>(API + "/context")
      setContext(fresh)
      if (fresh.templates.includes(volume)) setDraft(current => current && selectTemplate(current, volume))
      else setError("template_unverified")
    } catch (error) {
      setError(errorCode(error))
    }
  }

  function download(template: string, storage: string) {
    if (!context) return
    const volume = `${storage}:vztmpl/${template}`
    if (context.templates.includes(volume)) {
      void chooseTemplate(volume)
      return
    }
    void submit("download_template", async () => {
      const checked = await fetchApi<Checked>(API + "/download/plan", {
        method: "POST", body: JSON.stringify({ node: context.node, catalog_id: template, template_storage: storage }),
      })
      return { ticket: checked.receipt, body: { check: checked.check, confirmed: true } }
    }, () => void chooseTemplate(volume))
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
      "template_already_present", "storage_unavailable", "resource_unavailable", "resource_unsupported",
      "resource_in_use"].includes(error) ? "error." + error : "error.unavailable")}
  </p>
  const downloading = receipt?.action === "download_template"
  if (receipt) {
    const created = operation?.action === "create" ? operation : null
    const final = Boolean(state && finalStates.has(state))
    const outcome = state && state !== "running" && state !== "awaiting" && (operation?.reason && !AWAITING_NEXT.has(operation.reason)
      && ["create_failed", "start_failed", "preparation_failed", "start_not_submitted", "preparation_not_submitted",
        "download_failed", "template_checksum_mismatch"].includes(operation.reason)
      ? t("reason." + operation.reason) : t((downloading ? "downloadStatus." : "status.") + state))
    const tone = state === "succeeded" ? "border-green-500/40 text-green-600 dark:text-green-400"
      : state === "failed" || state === "not_submitted" ? "border-destructive/40 text-destructive"
        : state === "partial" ? "border-amber-500/40 text-amber-600 dark:text-amber-400" : "border-border text-muted-foreground"
    const title = receipt.title ?? (created ? `LXC ${created.vmid}` : operation?.action === "download_template" ? operation.volume_id : "")
    return <div className="space-y-3">
      <div className="rounded-lg border border-border bg-card p-3 sm:p-4">
        {title && <div className="mb-3 border-b border-border pb-3">
          <p className="break-all font-semibold">{title}</p>
          {receipt.detail && <p className="text-xs text-muted-foreground">
            {receipt.detail.split(" · ").map((part, index) => <span key={index}>
              {index > 0 && " · "}<span className="inline-block max-w-full break-all align-bottom">{part}</span>
            </span>)}
          </p>}
        </div>}
        <OperationProgress receipt={receipt} operation={operation} t={t} />
      </div>
      {outcome && <p role="status" className={`rounded-md border p-2 text-sm ${tone}`}>{outcome}</p>}
      {operation?.task_warnings && <p className="text-sm text-muted-foreground">{t("taskWarnings")}</p>}
      {!downloading && state === "partial" && <p className="text-sm text-muted-foreground">{t("partialHelp")}</p>}
      {errorMessage}
      <div className="flex flex-wrap justify-end gap-2">
        <DialogClose asChild><Button type="button" variant="outline">{t("close")}</Button></DialogClose>
        {created && state === "succeeded" && created.steps?.includes("start") && onOpenTerminal &&
          <Button type="button" variant="outline" onClick={() => {
            sessionStorage.removeItem(RECEIPT)
            onOpenTerminal(created.vmid, receipt.title?.split(" · ")[1] ?? `LXC ${created.vmid}`)
          }}>
            <SquareTerminal className="mr-1.5 h-4 w-4" aria-hidden="true" />{t("openTerminal")}
          </Button>}
        {(final || error === "receipt_invalid") && (downloading
          ? <Button type="button" className={primary} disabled={busy} onClick={() => void returnFromDownload()}>
            {t(state === "succeeded" ? "useTemplate" : "returnToSystem")}
          </Button>
          : <Button type="button" className={primary} onClick={clearResult}>{t("newDraft")}</Button>)}
      </div>
    </div>
  }

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
    <label className="flex items-center gap-3 text-sm">
      <Switch className={switchClass} checked={draft[key]} onCheckedChange={checked => update({ [key]: checked })} />
      {t(label)}
    </label>
  const number = (min: number, max: number) => ({ type: "number", min, max, step: 1, required: true })
  // While Review checks again, the last result stays in view, dimmed.
  const shown = plan ?? (busy ? lastPlan.current : null)
  const summary = shown?.summary
  const yesNo = (enabled: boolean) => t(enabled ? "yes" : "no")
  const rows = summary ? [
    [t("system"), `${summary.node} · LXC ${summary.vmid} · ${summary.hostname}`, summary.template.volume_id,
      `${t("nesting")} · ${yesNo(summary.nesting)} / ${t("onboot")} · ${yesNo(summary.onboot)}`,
      `${t("start")} · ${yesNo(summary.start_after_create)} / ${t("prepare")} · ${yesNo(summary.prepare_system)}`],
    [t("access"), t("access_" + summary.access.mode)],
    [t("resources"), `${summary.rootfs.storage} · ${summary.rootfs.size_gib} GiB`,
      `${t("cores")} · ${summary.cpu.cores} / RAM · ${summary.memory.ram_mib} MiB / Swap · ${summary.memory.swap_mib} MiB`,
      ...summary.mounts.map(mount => `${t("mounts")} · ${mount.type === "volume" ? `${mount.storage} · ${mount.size_gib} GiB` : mount.source} → ${mount.path}${mount.read_only ? ` · ${t("readOnly")}` : ""}`),
      ...summary.hardware.map(name => `${t("hardware")} · ${name}`)],
    [t("network"), summary.network ? [summary.network.bridge, summary.network.vlan_tag && `VLAN ${summary.network.vlan_tag}`,
      summary.network.ipv4.cidr ?? "DHCP", summary.network.ipv4.gateway].filter(Boolean).join(" · ") : t("noNetwork"),
      ...(summary.network ? [`DNS · ${summary.dns.nameservers.join(", ") || t("hostDns")}`, summary.dns.search_domains.join(", ")] : [])],
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
          {field("template", <Choice value={draft.template} onChange={value => update(selectTemplate(draft, value))}
            label={t("template")} placeholder={t("selectTemplate")} options={context.templates.map(template => ({ value: template }))} />)}
          {!context.templates.length && <p role="status" className="text-sm text-muted-foreground">{t("noTemplates")}</p>}
          <TemplateDownload key={draft.template} context={context} busy={busy} onDownload={download} t={t} />
          {input("hostname", "hostname", { required: true, maxLength: 253 })}
          <div className="space-y-2">
            {check("nesting", "nesting")}{check("onboot", "onboot")}{check("start", "start")}{check("prepare", "prepare")}
            <p className="pl-12 text-xs text-muted-foreground">{t("prepareHelp")}</p>
          </div>
        </>}
        {step === 1 && <>
          {field("access", <Choice value={draft.access} label={t("access")} onChange={value => {
            setPassword("")
            setConfirmation("")
            update({ access: value as Access })
          }} options={(["password", "ssh_key", "both"] as const).map(mode => ({ value: mode, label: t("access_" + mode) }))} />)}
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
          {field("storage", <Choice value={draft.storage} onChange={value => update({ storage: value })} label={t("storage")}
            placeholder={t("selectStorage")} options={context.storages.map(storage => ({ value: storage }))} />)}
          {input("disk", "disk", number(1, 65536))}
          {input("cores", "cores", number(1, Math.min(8192, context.limits.cores)))}
          {input("ram", "ram", number(16, Math.min(4194304, context.limits.ram_mib)))}
          {input("swap", "swap", number(0, 4194304))}
          <div className="space-y-4 border-t pt-3 sm:col-span-2">
            <MountPoints context={context} mounts={draft.mounts} onChange={mounts => update({ mounts })} t={t} />
            <HardwareChoice context={context} selected={draft.hardware} onChange={hardware => update({ hardware })} t={t} />
          </div>
        </div>}
        {step === 3 && <>
          {field("bridge", <Choice value={draft.bridge} onChange={value => update({ bridge: value, vlan: "" })} label={t("bridge")}
            empty={t("noNetwork")} options={Object.keys(context.bridges).map(bridge => ({ value: bridge }))} />)}
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
          {!summary && busy && <p role="status" className="flex items-center gap-2 rounded-md border bg-card p-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />{t("checking")}
          </p>}
          {summary && shown && <div className={`space-y-2 transition-opacity ${plan ? "" : "opacity-60"}`}>
            {rows.map(([label, ...values], index) => <section key={label} className="rounded-md border p-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{label}</h3>
                {index < 4 && <Button type="button" size="sm" variant="ghost"
                  onClick={() => { invalidate(); setStep(index) }}>{t("edit")}</Button>}
              </div>
              {values.filter(Boolean).map((value, valueIndex) => <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]" key={valueIndex}>{value}</p>)}
            </section>)}
            {shown.warnings.map(warning => <p key={warning} role="note"
              className="flex items-start gap-2 rounded-md border border-blue-500/40 bg-blue-500/10 p-2 text-sm text-blue-700 dark:text-blue-300">
              <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{t("warning." + warning)}
            </p>)}
          </div>}
        </>}
      </fieldset>
      {errorMessage}
      <div className="flex flex-wrap justify-between gap-2 border-t pt-3">
        <DialogClose asChild><Button type="button" variant="outline">{t("cancel")}</Button></DialogClose>
        <div className="flex flex-wrap justify-end gap-2">
          {step > 0 && <Button type="button" variant="outline" disabled={busy}
            onClick={() => { invalidate(); setStep(step - 1) }}><ArrowLeft className="mr-1 h-4 w-4" />{t("back")}</Button>}
          {step < 4 && <Button type="submit" className={primary} disabled={busy || (step === 0 && !context.templates.length)}>
            {t("next")}<ArrowRight className="ml-1 h-4 w-4" />
          </Button>}
          {step === 4 && !plan && <Button type="submit" className={primary} disabled={busy}>{t(busy ? "checking" : "check")}</Button>}
          {step === 4 && plan && <Button type="button" className={primary} disabled={busy}
            onClick={() => void create()}>{t("confirmCreate")}</Button>}
        </div>
      </div>
    </form>
  </>
}
