"use client"

import { useEffect, useRef, useState, type FormEvent } from "react"
import { Loader2, Plus } from "lucide-react"
import { SWITCH_CLASS } from "./edit-controls"
import { FIREWALL_ADD_CLASS, FIREWALL_LOG_LEVELS, FIREWALL_SAVE_CLASS } from "./firewall-rule-form"
import { OptionSelect } from "./option-select"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Switch } from "./ui/switch"
import { fetchApi } from "@/lib/api-config"
import { useT } from "@/lib/i18n/provider"

export type FirewallGuest = { vmid: number; node: string; type: string }
export type FirewallSettingsMode = "settings" | "network"
type FirewallOptions = {
  enabled: boolean
  policy_in: string
  policy_out: string
  log_level_in: string
  log_level_out: string
}
type Snapshot = FirewallGuest & {
  settings: FirewallOptions
  interfaces: { name: string; flag: boolean | null; pending: string | null }[]
  bridges: string[]
  revision: string
}
type Draft = { options: FirewallOptions; interfaces: Record<string, boolean> }
type SettingsDraft = { snapshot: Snapshot; draft: Draft }
type SaveResult = FirewallGuest & { saved: boolean; pending: string[]; interface: string | null }

const scope = "vmLxc.firewall"
const policies = ["ACCEPT", "DROP", "REJECT"]
const logLevels = ["nolog", ...FIREWALL_LOG_LEVELS]
const models = ["virtio", "e1000", "e1000e", "rtl8139", "vmxnet3"]
const options = (values: string[]) => values.map(value => ({ value, label: value }))

function FirewallSwitch({ checked, onCheckedChange }: {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  const t = useT()
  return (
    <span className="flex shrink-0 items-center gap-2">
      <span aria-hidden="true" className={`text-xs ${checked ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground"}`}>
        {t(`${scope}.flag.${checked ? "on" : "off"}`)}
      </span>
      <Switch className={SWITCH_CLASS} checked={checked} onCheckedChange={onCheckedChange} />
    </span>
  )
}

export function GuestFirewallSettings({ guest, mode, missingPrerequisite, onClose, onSaved, onUncertain }: {
  guest: FirewallGuest
  mode: FirewallSettingsMode
  missingPrerequisite: boolean
  onClose: () => void
  onSaved: (result: SaveResult) => void
  onUncertain: () => void
}) {
  const t = useT()
  const { vmid, node, type } = guest
  const url = `/api/vms/${vmid}/firewall/settings`
  const [settingsDraft, setSettingsDraft] = useState<SettingsDraft>()
  const [adding, setAdding] = useState(mode === "network")
  const lxc = type === "lxc"
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [draft, setDraft] = useState<Draft>()
  const [error, setError] = useState<string>()
  const [saving, setSaving] = useState(false)
  const [readRequest, setReadRequest] = useState<{ network: boolean } | null>({ network: adding })
  const [bridge, setBridge] = useState("")
  const [vlan, setVlan] = useState("")
  const [model, setModel] = useState("virtio")
  const [ipMode, setIpMode] = useState("dhcp")
  const [ip, setIp] = useState("")
  const [gateway, setGateway] = useState("")
  const [protect, setProtect] = useState(true)
  const [enableGuest, setEnableGuest] = useState(false)
  const submitting = useRef(false)
  const title = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (!readRequest) return
    const controller = new AbortController()
    const query = new URLSearchParams({ node, type, ...(readRequest.network ? { network: "1" } : {}) })
    fetchApi<Snapshot>(`${url}?${query}`, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return
      if (data?.vmid !== vmid || data.node !== node || data.type !== type) {
        setError("guestChanged")
        return
      }
      setSnapshot(data)
      setDraft({
        options: data.settings,
        interfaces: Object.fromEntries(data.interfaces.flatMap(nic =>
          !nic.pending && nic.flag !== null ? [[nic.name, nic.flag]] : [])),
      })
    }).catch((failure: { status?: number; body?: { error?: string } }) => {
      if (!controller.signal.aborted) setError(failure.body?.error === "guest_changed" ? "guestChanged"
        : failure.status === 401 || failure.status === 403 ? "denied" : "readError")
    })
    return () => controller.abort()
  }, [node, type, url, readRequest, vmid])

  const openNetwork = () => {
    if (!snapshot || !draft) return
    setSettingsDraft({ snapshot, draft })
    setAdding(true)
    setSnapshot(undefined)
    setDraft(undefined)
    setError(undefined)
    setBridge("")
    setVlan("")
    setModel("virtio")
    setIpMode("dhcp")
    setIp("")
    setGateway("")
    setProtect(true)
    setEnableGuest(false)
    setReadRequest({ network: true })
    title.current?.focus()
  }

  const close = () => {
    if (submitting.current) return
    if (!settingsDraft) {
      onClose()
      return
    }
    setSettingsDraft(undefined)
    setAdding(false)
    setSnapshot(settingsDraft.snapshot)
    setDraft(settingsDraft.draft)
    setError(undefined)
    setReadRequest(null)
    title.current?.focus()
  }

  const optionChanges = Object.fromEntries(Object.entries(draft?.options ?? {}).filter(([key, value]) =>
    snapshot?.settings[key as keyof FirewallOptions] !== value))
  const flagChanges = Object.fromEntries((snapshot?.interfaces ?? []).flatMap(nic => {
    const flag = draft?.interfaces[nic.name]
    return flag !== undefined && flag !== nic.flag ? [[nic.name, flag]] : []
  }))
  const networkValid = !!snapshot?.bridges.includes(bridge) &&
    (!vlan || (/^[0-9]+$/.test(vlan) && Number(vlan) >= 1 && Number(vlan) <= 4094)) &&
    (!lxc || ipMode === "dhcp" || ip.trim().includes("/"))
  const ready = draft && snapshot && (adding ? networkValid
    : Object.keys(optionChanges).length > 0 || Object.keys(flagChanges).length > 0)
  const canSave = Boolean(ready && !saving)
  const enabling = adding ? protect && enableGuest : optionChanges.enabled === true

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!ready || submitting.current) return
    submitting.current = true
    setSaving(true)
    setError(undefined)
    const detail = { bridge, vlan: vlan ? Number(vlan) : null, firewall: protect,
      ...(lxc ? { mode: ipMode, ip: ipMode === "static" ? ip.trim() : "", gateway: ipMode === "static" ? gateway.trim() : "" } : { model }) }
    try {
      const data = await fetchApi<SaveResult>(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          node, type, revision: snapshot.revision,
          ...(adding ? { network: detail, options: enabling ? { enabled: true } : {} }
            : { options: optionChanges, interfaces: flagChanges }),
        }),
      })
      if (!data?.saved || data.vmid !== vmid || data.node !== node || data.type !== type) {
        throw new Error("Unexpected firewall settings response")
      }
      onSaved(data)
    } catch (error) {
      const failure = error as { status?: number; body?: { error?: string; applied?: string[] } }
      const code = failure.body?.error
      const key = failure.body?.applied?.length ? "settingsPartial"
        : code === "guest_changed" ? "guestChanged"
        : code === "firewall_settings_changed" ? "settingsChanged"
        : code === "firewall_no_interface_slot" ? "settingsNoSlot"
        : code === "firewall_settings_invalid" ? "settingsInvalid"
        : failure.status === 401 || failure.status === 403 ? "denied" : "settingsUncertain"
      setError(key)
      if (key !== "settingsInvalid") {
        setSnapshot(undefined)
        setDraft(undefined)
        if (settingsDraft) setSettingsDraft(undefined)
        onUncertain()
      }
    } finally {
      submitting.current = false
      setSaving(false)
    }
  }
  const setOption = <K extends keyof FirewallOptions>(key: K, value: FirewallOptions[K]) => {
    setDraft(current => current && { ...current, options: { ...current.options, [key]: value } })
  }
  const names = ["policy_in", "policy_out", "log_level_in", "log_level_out"] as const

  return (
    <Dialog open onOpenChange={open => { if (!open) close() }}>
      <DialogContent className="max-h-[90dvh] w-[calc(100%-1.25rem)] max-w-lg overflow-y-auto p-4 sm:p-5"
        hideClose overlayClassName="bg-black/40">
        <DialogHeader>
          <DialogTitle ref={title} tabIndex={-1}>{t(`${scope}.${adding ? "addInterface" : "configure"}`)}</DialogTitle>
          <DialogDescription>{t(`${scope}.${adding ? "addInterfaceDescription" : "settingsDescription"}`,
            { guest: `${lxc ? "LXC" : "VM"} ${vmid}`, node })}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={save}>
          {!snapshot && !error && <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="size-4 animate-spin" />{t(`${scope}.reading`)}
          </p>}
          {error && <p role="alert" className="rounded-md border border-amber-500/30 p-2 text-sm">{t(`${scope}.${error}`)}</p>}
          <fieldset className="space-y-3 disabled:opacity-60" disabled={saving}>
            {draft && !adding && <>
              <label className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm font-medium">
                {t(`${scope}.guest`)}
                <FirewallSwitch checked={draft.options.enabled} onCheckedChange={value => setOption("enabled", value)} />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                {names.map(name => <div className="space-y-1.5" key={name}>
                  <p className="text-xs font-medium text-muted-foreground">{t(`${scope}.setting.${name}`)}</p>
                  <OptionSelect value={draft.options[name]} onChange={value => setOption(name, value)}
                    ariaLabel={t(`${scope}.setting.${name}`)}
                    options={name.startsWith("policy") ? policies.map(value => ({ value, label: `${value} · ${t(`${scope}.action.${value}`)}` }))
                      : logLevels.map(value => ({ value, label: value === "nolog" ? t(`${scope}.noLog`) : value }))} />
                </div>)}
              </div>
              <div>
                <p className="mb-1.5 text-sm font-medium">{t(`${scope}.interfaces`)}</p>
                {snapshot?.interfaces.length ? <ul className="divide-y rounded-md border">
                  {snapshot.interfaces.map(nic => <li key={nic.name} className="flex justify-between gap-2 px-3 py-2 text-sm">
                    <label className="flex w-full items-center justify-between gap-2">
                      <span className="font-mono">{nic.name}</span>
                      {nic.pending || nic.flag === null
                        ? <span className="text-xs text-muted-foreground">{t(`${scope}.${nic.pending ? "settingsNicPending" : "interfacesUnknown"}`)}</span>
                        : <FirewallSwitch checked={draft.interfaces[nic.name]} onCheckedChange={flag => setDraft(current =>
                          current && { ...current, interfaces: { ...current.interfaces, [nic.name]: flag } })} />}
                    </label>
                  </li>)}
                </ul> : <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-muted-foreground">{t(`${scope}.interfacesEmpty`)}</p>
                  <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={openNetwork}>
                    <Plus className="size-3.5" aria-hidden />{t(`${scope}.addInterface`)}
                  </Button>
                </div>}
              </div>
            </>}
            {snapshot && adding && (snapshot.bridges.length ? <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">{t(`${scope}.bridge`)}</p>
                  <OptionSelect value={bridge} ariaLabel={t(`${scope}.bridge`)} onChange={setBridge}
                    options={[{ value: "", label: t(`${scope}.chooseBridge`) }, ...options(snapshot.bridges)]} />
                </div>
                <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
                  <span>{t(`${scope}.vlan`)}</span>
                  <Input className="h-9" value={vlan} onChange={event => setVlan(event.target.value)} inputMode="numeric"
                    maxLength={4} placeholder="1–4094" />
                </label>
              </div>
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">{t(`${scope}.${lxc ? "ipv4Mode" : "nicModel"}`)}</p>
                <OptionSelect value={lxc ? ipMode : model} onChange={lxc ? setIpMode : setModel}
                  ariaLabel={t(`${scope}.${lxc ? "ipv4Mode" : "nicModel"}`)}
                  options={lxc ? [{ value: "dhcp", label: "DHCP" }, { value: "static", label: t(`${scope}.staticIp`) }] : options(models)} />
              </div>
              {lxc && ipMode === "static" && <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
                  <span>{t(`${scope}.ipCidr`)}</span>
                  <Input className="h-9" required value={ip} onChange={event => setIp(event.target.value)} placeholder="192.0.2.10/24" />
                </label>
                <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
                  <span>{t(`${scope}.gateway`)}</span>
                  <Input className="h-9" value={gateway} onChange={event => setGateway(event.target.value)} placeholder="192.0.2.1" />
                </label>
              </div>}
              <label className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm font-medium">
                {t(`${scope}.protectNic`)}<FirewallSwitch checked={protect} onCheckedChange={setProtect} />
              </label>
              {!snapshot.settings.enabled && protect && <label className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm font-medium">
                {t(`${scope}.enableGuest`)}<FirewallSwitch checked={enableGuest} onCheckedChange={setEnableGuest} />
              </label>}
              {bridge && <p className="break-words text-xs text-muted-foreground">
                {t(`${scope}.attachPreview`, { bridge, mode: lxc ? (ipMode === "dhcp" ? "DHCP" : ip.trim() || "IPv4/CIDR") : model })}
                {vlan && <> · VLAN {vlan}</>}
              </p>}
            </> : <p className="text-sm text-muted-foreground">{t(`${scope}.noBridges`)}</p>)}
          </fieldset>
          {ready && <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-foreground">
            {t(`${scope}.${adding ? "networkImpact" : "settingsImpact"}`)}
            {enabling && <> {t(`${scope}.enableImpact`)}</>}
            {enabling && missingPrerequisite && <> {t(`${scope}.settingsPrerequisite`)}</>}
          </p>}
          <DialogFooter className="gap-2 sm:space-x-0">
            <Button type="button" variant="outline" disabled={saving} onClick={close}>{t("actions.cancel")}</Button>
            {!snapshot && error && error !== "guestChanged" && error !== "denied"
              ? <Button type="button" onClick={() => { setError(undefined); setReadRequest({ network: adding }) }}>{t(`${scope}.refresh`)}</Button>
              : <Button type="submit" disabled={!canSave} variant={canSave && !adding ? "outline" : "default"}
                className={`gap-2 ${canSave ? (adding ? FIREWALL_ADD_CLASS : FIREWALL_SAVE_CLASS) : "bg-muted text-muted-foreground"}`}>
                {saving && <Loader2 className="size-4 animate-spin" />}
                {t(adding ? `${scope}.addInterface` : "actions.save")}
              </Button>}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
