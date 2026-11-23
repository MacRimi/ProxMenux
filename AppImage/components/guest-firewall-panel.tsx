"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import { ArrowDown, ArrowDownLeft, ArrowDownToLine, ArrowUp, ArrowUpDown, ArrowUpRight, ArrowUpToLine, Check, ChevronRight, GripVertical, Loader2, Pencil, Plus, Power, RefreshCw, Settings2, Shield, Trash2 } from "lucide-react"
import { FIREWALL_LOG_LEVELS, FirewallRuleForm, type FirewallRuleDraft } from "./firewall-rule-form"
import { GuestFirewallSettings, type FirewallGuest, type FirewallSettingsMode } from "./guest-firewall-settings"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { fetchApi } from "@/lib/api-config"
import { useT } from "@/lib/i18n/provider"

type Section = "status" | "rules" | "log"
type Coverage = "configured" | "disabled" | "unknown"
type Guest = FirewallGuest
type Interface = {
  name: string
  flag: boolean | null
  coverage: Coverage | "absent"
  pending: "add" | "change" | "remove" | null
  pending_flag: boolean | null
}
type Status = {
  status: Coverage | "partial" | "noInterfaces"
  cluster_enabled: boolean | null
  guest_enabled: boolean | null
  backend: "iptables" | "nftables" | null
  service: "running" | "stopped" | "unavailable" | "unknown"
  interfaces: Interface[] | null
  log_levels: Record<"in" | "out", string>
  can_configure: boolean
}

const ruleFields = ["iface", "macro", "proto", "source", "sport", "dest", "dport", "icmp-type", "ipversion", "log"] as const
type Rule = {
  pos: number
  enabled: boolean | null
  type: string
  action: string
  comment?: string
} & Partial<Record<(typeof ruleFields)[number], string>>

function draftFromRule(rule: Rule): FirewallRuleDraft {
  return {
    direction: rule.type.toUpperCase(), action: rule.action, protocol: rule.proto ?? "",
    dport: rule.dport ?? "", source: rule.source ?? "", iface: rule.iface ?? "", comment: rule.comment ?? "",
    log: rule.log ?? "nolog",
  }
}

function ruleHasChanges(draft: FirewallRuleDraft, rule: Rule) {
  const original = draftFromRule(rule)
  return (Object.keys(original) as (keyof FirewallRuleDraft)[]).some(key => original[key]?.trim() !== draft[key]?.trim())
}

type Logs = { logs: { n: number; t: string }[] }
type Rules = { rules: Rule[]; add_rule_revision: string | null; editable_rule_positions: number[]; writable_rule_positions: number[] }
type RuleWriteResult = Guest & { created?: boolean; updated?: boolean; deleted?: boolean; moved?: boolean; rules_snapshot?: Rules }
type RuleAction = "enable" | "disable" | "delete"
type RuleConfirmation = { rule: Rule; revision: string } & ({ action: RuleAction } | { action: "move"; to: number })
const ruleActions = {
  enable: { label: "enableRule", title: "confirmEnableRule", success: "ruleEnabled" },
  disable: { label: "disableRule", title: "confirmDisableRule", success: "ruleDisabled" },
  delete: { label: "deleteRule", title: "confirmDeleteRule", success: "ruleDeleted" },
  move: { label: "moveRule", title: "confirmMoveRule", success: "ruleMoved" },
}
type ReadError = "guestChanged" | "denied" | "readError"
type Reading<T> = { data?: T; error?: ReadError; loading: boolean }

const scope = "vmLxc.firewall"
const feedbackDurationMs = 2500
const flagKey = (flag: boolean | null) => flag === true ? "on" : flag === false ? "off" : "unknown"
const flagCoverage = (flag: boolean | null): Coverage => flag === true ? "configured" : flag === false ? "disabled" : "unknown"
const coverageTone: Record<Status["status"], string> = {
  configured: "border-emerald-500/25 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400",
  disabled: "border-border bg-muted/40 text-foreground",
  partial: "border-amber-500/25 bg-amber-500/5 text-amber-700 dark:text-amber-400",
  noInterfaces: "border-border bg-muted/40 text-foreground",
  unknown: "border-amber-500/25 bg-amber-500/5 text-amber-700 dark:text-amber-400",
}
const emptyStateClass = "rounded-lg border border-dashed border-border px-4 py-5 text-center"
const ruleButtonClass = "h-7 shrink-0 gap-1.5 whitespace-nowrap text-xs max-sm:size-8 max-sm:px-0"

function useFirewallRead<T>(guest: Guest, section: Section, active: boolean) {
  const { vmid, node, type } = guest
  const [version, setVersion] = useState(0)
  const [reading, setReading] = useState<Reading<T>>({ loading: true })
  const readRequest = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    readRequest.current = controller
    const query = new URLSearchParams({ node, type })
    setReading(previous => ({ data: previous.data, loading: true }))
    fetchApi<Guest & T>(`/api/vms/${vmid}/firewall/${section}?${query}`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return
        if (data?.vmid !== vmid || data.node !== node || data.type !== type) {
          setReading({ error: "guestChanged", loading: false })
          return
        }
        setReading({ data, loading: false })
      })
      .catch((error: { body?: { error?: string }; status?: number }) => {
        if (controller.signal.aborted) return
        const reason = error.body?.error === "guest_changed" ? "guestChanged"
          : error.status === 403 ? "denied" : "readError"
        setReading(previous => ({
          data: reason === "readError" ? previous.data : undefined,
          error: reason,
          loading: false,
        }))
      })
    return () => controller.abort()
  }, [active, node, section, type, version, vmid])

  return {
    ...reading,
    refresh: () => setVersion(previous => previous + 1),
    replace: (data: T) => {
      readRequest.current?.abort()
      setReading({ data, loading: false })
    },
  }
}

function firewallBlocker(data: Status) {
  if (data.cluster_enabled === false) return "clusterDisabled"
  if (data.guest_enabled === false) return "guestDisabled"
  if (data.service === "stopped") return "serviceStopped"
  if (data.interfaces?.every(nic => nic.coverage === "absent")) return "coverage.noInterfaces"
  if (data.status === "disabled") return "noProtectedInterfaces"
}

function FirewallStatus({ data, onAddInterface, onClusterFirewall }: {
  data: Status
  onAddInterface?: () => void
  onClusterFirewall?: () => void
}) {
  const t = useT()
  const blocker = firewallBlocker(data)
  return (
    <div className="space-y-4">
      <div className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5 ${coverageTone[data.status]}`}>
        <Shield aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <div className="space-y-0.5">
          <p className="text-sm font-semibold">
            {t(`${scope}.${blocker ?? `coverage.${data.status}`}`)}
          </p>
          <p className="text-xs text-muted-foreground">{t(`${scope}.configurationHint`)}</p>
        </div>
      </div>
      <dl className="grid auto-rows-fr gap-2 sm:grid-cols-3">
        <div className="rounded-lg border bg-card p-2.5">
          <dt className="text-xs text-muted-foreground">{t(`${scope}.cluster`)}</dt>
          <dd className="text-sm font-medium">{t(`${scope}.flag.${flagKey(data.cluster_enabled)}`)}</dd>
          {data.cluster_enabled === false && onClusterFirewall && <Button variant="link" size="sm"
            className="mt-1 h-auto whitespace-normal p-0 text-left text-xs" onClick={onClusterFirewall}>
            {t(`${scope}.openClusterFirewall`)}
          </Button>}
        </div>
        <div className="rounded-lg border bg-card p-2.5">
          <dt className="text-xs text-muted-foreground">{t(`${scope}.guest`)}</dt>
          <dd className="text-sm font-medium">{t(`${scope}.flag.${flagKey(data.guest_enabled)}`)}</dd>
        </div>
        <div className="rounded-lg border bg-card p-2.5">
          <dt className="text-xs text-muted-foreground">{t(`${scope}.nodeService`)}</dt>
          <dd className="text-sm font-medium">
            {data.backend && <span>{data.backend} · </span>}{t(`${scope}.service.${data.service}`)}
          </dd>
        </div>
      </dl>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">{t(`${scope}.interfaces`)}</h3>
          {onAddInterface && <Button variant="outline" size="sm" className="gap-1.5" onClick={onAddInterface}>
            <Plus className="size-3.5" />{t(`${scope}.addInterface`)}
          </Button>}
        </div>
        {data.interfaces === null || data.interfaces.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t(`${scope}.${data.interfaces === null ? "interfacesUnknown" : "interfacesEmpty"}`)}
          </p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {data.interfaces.map(nic => (
              <li className="space-y-1 p-3 text-sm" key={nic.name}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono font-medium">{nic.name}</span>
                  <Badge variant="outline">{t(`${scope}.coverage.${nic.coverage}`)}</Badge>
                </div>
                {nic.coverage !== "absent" && nic.coverage !== flagCoverage(nic.flag) && (
                  <p className="text-xs text-muted-foreground">
                    {t(`${scope}.interfaceFlag`, { state: t(`${scope}.flag.${flagKey(nic.flag)}`) })}
                  </p>
                )}
                {nic.pending && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">
                    {t(`${scope}.pending.${nic.pending}`, { state: t(`${scope}.flag.${flagKey(nic.pending_flag)}`) })}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

const ruleColumns = "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 sm:grid-cols-[minmax(9rem,1.3fr)_minmax(3rem,0.45fr)_minmax(3rem,0.6fr)_minmax(5rem,1fr)_auto_1rem]"
const ruleActionTone: Record<string, string> = {
  ACCEPT: "border-transparent bg-green-500/10 text-green-700 dark:text-green-400",
  DROP: "border-transparent bg-red-500/10 text-red-700 dark:text-red-400",
  REJECT: "border-transparent bg-orange-500/10 text-orange-700 dark:text-orange-400",
}

function FirewallRules({ rules, expanded, onExpand, editable, writable, onAction, onEdit, editing, editor, saving,
  moveRevision, onMove }: {
  rules: Rule[]
  expanded?: number
  onExpand: (position?: number) => void
  editable: number[]
  writable: number[]
  onAction: (rule: Rule, action: RuleAction) => void
  onEdit: (rule: Rule) => void
  editing?: number
  editor?: ReactNode
  saving: boolean
  moveRevision?: string | null
  onMove: (rule: Rule, to: number) => void
}) {
  const t = useT()
  const dragged = useRef<{ rule: Rule; revision: string } | null>(null)
  const [drop, setDrop] = useState<{ position: number; after: boolean }>()
  const clearDrag = () => {
    dragged.current = null
    setDrop(undefined)
  }
  const allPositionsKnown = rules.every((rule, index) => rule.pos === index)
  const showMove = Boolean(moveRevision && writable.length && rules.length > 1 && allPositionsKnown)
  if (!rules.length) return <p className={`${emptyStateClass} text-sm font-medium`}>{t(`${scope}.rulesEmpty`)}</p>
  return (
    <div className="rounded-lg border">
      <div className={`${ruleColumns} hidden border-b px-3 py-2 text-[10px] font-medium uppercase text-muted-foreground sm:grid ${showMove ? "sm:pl-10" : ""}`}>
        <span>{t("securityPage.firewall.fields.action")}</span>
        {(["proto", "dport", "source"] as const).map(field => <span key={field}>{t(`${scope}.field.${field}`)}</span>)}
        <span>{t(`${scope}.ruleState`)}</span>
      </div>
      <ol className="divide-y">
        {rules.map(rule => {
          const open = expanded === rule.pos
          const direction = ["in", "out", "group"].includes(rule.type) ? t(`${scope}.direction.${rule.type}`) : rule.type
          const action = rule.type !== "group" && ruleActionTone[rule.action] ? t(`${scope}.action.${rule.action}`) : rule.action
          const state = t(`${scope}.${rule.enabled === null ? "flag.unknown" : rule.enabled ? "ruleOn" : "ruleOff"}`)
          const detail = t("securityPage.firewall.anyLower")
          const canMove = showMove && writable.includes(rule.pos)
          return (
            <li key={rule.pos}>
              <div className="relative flex items-stretch"
                onDragOver={event => {
                  if (!moveRevision || dragged.current?.revision !== moveRevision) return
                  event.preventDefault()
                  event.dataTransfer.dropEffect = "move"
                  const row = event.currentTarget.getBoundingClientRect()
                  const after = event.clientY >= row.top + row.height / 2
                  setDrop(current => current?.position === rule.pos && current.after === after ? current : { position: rule.pos, after })
                }}
                onDragLeave={event => {
                  if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return
                  setDrop(current => current?.position === rule.pos ? undefined : current)
                }}
                onDrop={event => {
                  const source = dragged.current
                  if (!source || source.revision !== moveRevision || !moveRevision) return
                  event.preventDefault()
                  const row = event.currentTarget.getBoundingClientRect()
                  const slot = rule.pos + Number(event.clientY >= row.top + row.height / 2)
                  const to = slot - Number(source.rule.pos < slot)
                  clearDrag()
                  if (to !== source.rule.pos) onMove(source.rule, to)
                }}>
                {drop?.position === rule.pos && dragged.current?.revision === moveRevision && <span aria-hidden
                  className={`pointer-events-none absolute inset-x-0 z-10 h-0.5 bg-blue-500 ${drop.after ? "bottom-0" : "top-0"}`} />}
                {showMove && <div className="hidden w-7 shrink-0 place-items-center sm:grid">
                  {canMove && <button type="button" draggable
                    className="grid size-7 cursor-grab place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-ring active:cursor-grabbing"
                    aria-label={t(`${scope}.dragRule`, { position: rule.pos + 1 })}
                    title={t(`${scope}.dragRule`, { position: rule.pos + 1 })}
                    onClick={() => onExpand(rule.pos)}
                    onDragStart={event => {
                      if (!moveRevision) return
                      dragged.current = { rule, revision: moveRevision }
                      event.dataTransfer.setData("text/plain", String(rule.pos))
                      event.dataTransfer.effectAllowed = "move"
                    }} onDragEnd={clearDrag}>
                    <GripVertical aria-hidden className="size-4" />
                  </button>}
                </div>}
                <button type="button" aria-expanded={open}
                className={`${ruleColumns} min-w-0 flex-1 px-3 py-2.5 text-left text-xs hover:bg-muted/50 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring ${open ? "bg-muted/40" : ""}`}
                onClick={() => onExpand(open ? undefined : rule.pos)}>
                <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="text-muted-foreground tabular-nums">{rule.pos + 1}.</span>
                  {rule.type === "in" && <ArrowDownLeft className="size-3.5 shrink-0 text-blue-500" aria-hidden />}
                  {rule.type === "out" && <ArrowUpRight className="size-3.5 shrink-0 text-amber-500" aria-hidden />}
                  <span>{direction}</span>
                  <Badge variant="outline" className={`max-w-full break-all ${rule.type !== "group" ? ruleActionTone[rule.action] ?? "" : ""}`}>{action}</Badge>
                </span>
                <span className="hidden font-mono text-blue-600 dark:text-blue-400 sm:block">{rule.proto ?? "—"}</span>
                <span className="hidden break-all font-mono sm:block">{rule.dport ?? "—"}</span>
                <span className="hidden break-all font-mono text-muted-foreground sm:block">{rule.source ?? detail}</span>
                <Badge variant="outline" className={`justify-self-start ${rule.enabled
                  ? "border-green-500/25 text-green-700 dark:text-green-400" : "text-muted-foreground"}`}>{state}</Badge>
                <ChevronRight className={`size-4 justify-self-end text-muted-foreground ${open ? "rotate-90" : ""}`} aria-hidden />
                </button>
              </div>
              {open && (
                <div className="space-y-3 border-t bg-muted/15 p-3">
                  {editing === rule.pos ? editor : <>
                    <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                      {ruleFields.filter(field => rule[field]).map(field => (
                        <div className="min-w-0" key={field}>
                          <dt className="mb-0.5 text-muted-foreground">{t(`${scope}.field.${field}`)}</dt>
                          <dd className="break-all font-mono">{rule[field]}</dd>
                        </div>
                      ))}
                      {rule.comment && (
                        <div className="col-span-2 min-w-0">
                          <dt className="mb-0.5 text-muted-foreground">{t("securityPage.firewall.fields.comment")}</dt>
                          <dd className="break-words">{rule.comment}</dd>
                        </div>
                      )}
                    </dl>
                    {writable.includes(rule.pos) && (
                      <div className="flex flex-nowrap justify-end gap-2 border-t pt-2">
                        {canMove && <DropdownMenu modal={false}>
                          <DropdownMenuTrigger asChild>
                            <Button size="sm" variant="outline" className={ruleButtonClass}
                              aria-label={t(`${scope}.moveMenu`)} title={t(`${scope}.moveMenu`)}>
                              <ArrowUpDown aria-hidden className="size-3.5" />
                              <span className="hidden sm:inline">{t(`${scope}.moveMenu`)}</span>
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" collisionPadding={8} className="whitespace-nowrap !animate-none">
                            {([
                              ["moveRuleFirst", ArrowUpToLine, 0],
                              ["moveRuleUp", ArrowUp, rule.pos - 1],
                              ["moveRuleDown", ArrowDown, rule.pos + 1],
                              ["moveRuleLast", ArrowDownToLine, rules.length - 1],
                            ] as const).map(([label, Icon, to]) => {
                              const unavailable = to === rule.pos || to < 0 || to >= rules.length
                              return <DropdownMenuItem key={label} asChild disabled={unavailable} onSelect={() => onMove(rule, to)}>
                                <button type="button" className="w-full max-sm:min-h-11" disabled={unavailable}>
                                  <Icon aria-hidden />{t(`${scope}.${label}`)}
                                </button>
                              </DropdownMenuItem>
                            })}
                          </DropdownMenuContent>
                        </DropdownMenu>}
                        {editable.includes(rule.pos) && <Button size="sm" variant="outline" disabled={saving} onClick={() => onEdit(rule)}
                          aria-label={t("actions.edit")} title={t("actions.edit")}
                          className={`${ruleButtonClass} border-blue-500/30 text-blue-700 hover:bg-blue-500/10 dark:text-blue-400`}>
                          <Pencil aria-hidden className="size-3.5" /><span className="hidden sm:inline">{t("actions.edit")}</span>
                        </Button>}
                        {rule.enabled !== null && <Button size="sm" variant="outline" disabled={saving}
                          onClick={() => onAction(rule, rule.enabled ? "disable" : "enable")} className={ruleButtonClass}
                          aria-label={t(`${scope}.${rule.enabled ? "disableRule" : "enableRule"}`)}
                          title={t(`${scope}.${rule.enabled ? "disableRule" : "enableRule"}`)}>
                          <Power aria-hidden className="size-3.5" />
                          <span className="hidden sm:inline">{t(`${scope}.${rule.enabled ? "disableRule" : "enableRule"}`)}</span>
                        </Button>}
                        <Button size="sm" variant="outline" disabled={saving} onClick={() => onAction(rule, "delete")}
                          aria-label={t(`${scope}.deleteRule`)} title={t(`${scope}.deleteRule`)}
                          className={`${ruleButtonClass} border-red-500/30 text-red-700 hover:bg-red-500/10 dark:text-red-400`}>
                          <Trash2 aria-hidden className="size-3.5" /><span className="hidden sm:inline">{t(`${scope}.deleteRule`)}</span>
                        </Button>
                      </div>
                    )}
                  </>}
                </div>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function FirewallLogs({ logs, status }: { logs: Logs["logs"]; status?: Status }) {
  const t = useT()
  const [selectedLevels, setSelectedLevels] = useState<(typeof FIREWALL_LOG_LEVELS)[number][]>([])
  const visibleLogs = selectedLevels.length === 0 ? logs : logs.filter(({ t: line }) => {
    const logId = /^\d+\s+([0-7])\s+\S+\s/.exec(line)?.[1]
    return logId !== undefined && selectedLevels.includes(FIREWALL_LOG_LEVELS[Number(logId)])
  })
  const blocker = status && firewallBlocker(status)
  const loggingHint = status?.cluster_enabled === false || status?.guest_enabled === false
    ? "loggingDisabled"
    : blocker ?? (status?.log_levels.in === "nolog" && status.log_levels.out === "nolog" ? "policyLoggingDisabled" : null)
  return (
    <div className="space-y-2">
      {status && <dl className="grid gap-2 rounded-md border p-3 text-xs sm:grid-cols-2">
        {(["in", "out"] as const).map(direction => <div key={direction} className="flex flex-wrap items-center gap-x-2">
          <dt className="text-muted-foreground">{t(`${scope}.setting.log_level_${direction}`)}</dt>
          <dd className="font-medium">{status.log_levels[direction] === "nolog"
            ? t(`${scope}.noLog`) : status.log_levels[direction]}</dd>
        </div>)}
      </dl>}
      {logs.length ? (
        <>
          {loggingHint && <p className="text-xs text-muted-foreground">{t(`${scope}.${loggingHint}`)}</p>}
          <p className="text-xs text-muted-foreground">{t(`${scope}.logIdentityHint`)}</p>
          <div className="flex flex-wrap items-center gap-2">
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline">
                  {t(`${scope}.logLevelFilter`)}
                  {selectedLevels.length > 0 && <Badge variant="secondary">{selectedLevels.length}</Badge>}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onSelect={() => setSelectedLevels([])}>
                  {t(`${scope}.allLogLevels`)}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {FIREWALL_LOG_LEVELS.map(level => (
                  <DropdownMenuCheckboxItem key={level} checked={selectedLevels.includes(level)}
                    onSelect={event => event.preventDefault()}
                    onCheckedChange={checked => setSelectedLevels(current => checked ? [...current, level] : current.filter(value => value !== level))}>
                    {level}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {visibleLogs.length === 0 ? <p role="status" className={emptyStateClass}>{t(`${scope}.noMatchingLogLevels`)}</p> :
          <pre className="whitespace-pre-wrap break-all rounded-md border bg-background/50 p-3 font-mono text-xs leading-snug">
            {visibleLogs.map(({ n, t: line }) => (
              <span className={/\bDROP\b/i.test(line) ? "text-red-500"
                : /\bREJECT\b/i.test(line) ? "text-orange-500"
                : /\bACCEPT\b/i.test(line) ? "text-green-600 dark:text-green-400" : undefined}
                key={n}>{line}{"\n"}</span>
            ))}
          </pre>}
        </>
      ) : (
        <div className={`${emptyStateClass} space-y-1`}>
          <p className="text-sm font-medium">{t(`${scope}.empty`)}</p>
          {loggingHint && <p className="text-xs text-muted-foreground">{t(`${scope}.${loggingHint}`)}</p>}
        </div>
      )}
    </div>
  )
}

export function GuestFirewallPanel({ guest, onClusterFirewall }: { guest: Guest; onClusterFirewall?: () => void }) {
  const t = useT()
  const [section, setSection] = useState<Section>("status")
  const status = useFirewallRead<Status>(guest, "status", true)
  const rules = useFirewallRead<Rules>(guest, "rules", section === "rules")
  const log = useFirewallRead<Logs>(guest, "log", section === "log")
  const active = { status, rules, log }[section]
  const scrollRegion = useRef<HTMLDivElement>(null)
  const [ruleForm, setRuleForm] = useState<{ draft: FirewallRuleDraft; revision: string; original?: Rule }>()
  const [expandedRule, setExpandedRule] = useState<number>()
  const [confirmation, setConfirmation] = useState<RuleConfirmation>()
  const [saving, setSaving] = useState(false)
  const [ruleFeedback, setRuleFeedback] = useState<{ key: string; success: boolean }>()
  const [settingsMode, setSettingsMode] = useState<FirewallSettingsMode>()
  const [settingsFeedback, setSettingsFeedback] = useState<{ message: string; pending: boolean }>()
  const submitting = useRef(false)
  const revision = !rules.error && !rules.loading ? rules.data?.add_rule_revision : null
  const canConfigure = !status.error && !status.loading && status.data?.can_configure

  useEffect(() => {
    if (!ruleFeedback?.success) return
    const timeout = window.setTimeout(() => {
      setRuleFeedback(current => current === ruleFeedback ? undefined : current)
    }, feedbackDurationMs)
    return () => window.clearTimeout(timeout)
  }, [ruleFeedback])

  useEffect(() => {
    if (!settingsFeedback || settingsFeedback.pending) return
    const timeout = window.setTimeout(() => setSettingsFeedback(undefined), feedbackDurationMs)
    return () => window.clearTimeout(timeout)
  }, [settingsFeedback])

  const openSettings = (mode: FirewallSettingsMode) => {
    setSettingsFeedback(undefined)
    setSettingsMode(mode)
  }

  const writeRule = async (
    method: "POST" | "PUT" | "PATCH" | "DELETE",
    startRevision: string,
    payload: { pos?: number; to?: number; rule?: FirewallRuleDraft; enabled?: boolean },
    success: string,
  ) => {
    if (revision !== startRevision || submitting.current) return
    const { vmid, node, type } = guest
    submitting.current = true
    setSaving(true)
    setRuleFeedback(undefined)
    try {
      const data = await fetchApi<RuleWriteResult>(`/api/vms/${vmid}/firewall/rules`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node, type, revision, ...payload }),
      })
      const resultKey = payload.to !== undefined ? "moved" : method === "POST" ? "created" : method === "DELETE" ? "deleted" : "updated"
      const verified = data?.[resultKey] && data.vmid === vmid && data.node === node && data.type === type
      setRuleFeedback({ key: verified ? success : "ruleSaveUncertain", success: Boolean(verified) })
      setRuleForm(undefined)
      if (method === "DELETE" || payload.to !== undefined) setExpandedRule(undefined)
      if (verified && resultKey === "moved" && data.rules_snapshot) {
        rules.replace(data.rules_snapshot)
      } else {
        rules.refresh()
      }
    } catch (error) {
      const failure = error as { status?: number; body?: { error?: string } }
      const code = failure.body?.error
      if (code === "firewall_rule_invalid") {
        setRuleFeedback({ key: "ruleInvalid", success: false })
      } else {
        const key = code === "guest_changed" ? "guestChanged" : code === "firewall_rules_changed" ? "rulesChanged"
          : code === "firewall_rule_not_editable" ? "ruleNotEditable"
          : failure.status === 401 || failure.status === 403 ? "denied" : "ruleSaveUncertain"
        setRuleFeedback({ key, success: false })
        setRuleForm(undefined)
        rules.refresh()
      }
    } finally {
      setConfirmation(undefined)
      submitting.current = false
      setSaving(false)
    }
  }

  if ([status.error, rules.error, log.error].includes("guestChanged")) {
    return <p className="text-sm text-muted-foreground" role="status">{t(`${scope}.guestChanged`)}</p>
  }

  const usableInterfaces = (status.data?.interfaces ?? []).filter(item => item.coverage !== "absent")
    .map(item => ({ value: item.name, label: item.name }))
  if (ruleForm?.original?.iface && !usableInterfaces.some(item => item.value === ruleForm.original?.iface)) {
    usableInterfaces.push({ value: ruleForm.original.iface, label: ruleForm.original.iface })
  }
  const editor = ruleForm && (
    <FirewallRuleForm
      draft={ruleForm.draft}
      onChange={draft => setRuleForm({ ...ruleForm, draft })}
      onCancel={() => {
        if (submitting.current) return
        setRuleForm(undefined)
        setRuleFeedback(undefined)
      }}
      onSubmit={() => void writeRule(ruleForm.original ? "PUT" : "POST", ruleForm.revision, {
        rule: ruleForm.draft, ...(ruleForm.original ? { pos: ruleForm.original.pos } : { enabled: true }),
      }, ruleForm.original ? "ruleUpdated" : "activeRuleSaved")}
      saving={saving}
      interfaces={usableInterfaces}
      description={<p className="text-sm text-muted-foreground">{t(`${scope}.${
        ruleForm.original ? ruleForm.original.enabled ? "activeEditHelp" : "inactiveEditHelp" : "activeRuleHelp"
      }`)}</p>}
      submitDisabled={revision !== ruleForm.revision ||
        (ruleForm.original !== undefined && !ruleHasChanges(ruleForm.draft, ruleForm.original)) ||
        (ruleForm.draft.protocol !== "icmp" && !ruleForm.draft.dport.trim() && !ruleForm.draft.source.trim())}
      hideIcmpPort
      editing={Boolean(ruleForm.original)}
      submitLabel={ruleForm.original ? t("securityPage.firewall.saveChanges") : undefined}
    />
  )

  return (
    <Tabs className="flex min-h-0 flex-1 flex-col" value={section} onValueChange={value => {
      setSection(value as Section)
      if (scrollRegion.current) scrollRegion.current.scrollTop = 0
    }}>
      <div className="space-y-2 pb-2">
        <TabsList className="grid h-auto w-full grid-cols-3 items-stretch gap-1" aria-label={t("vmLxc.tabs.firewall")}>
          {(["status", "rules", "log"] as const).map(tab => (
            <TabsTrigger
              className="min-h-10 min-w-0 whitespace-normal rounded border border-transparent px-1 text-center leading-tight data-[state=active]:border-orange-500/25 data-[state=active]:bg-orange-500/10 data-[state=active]:text-orange-700 dark:data-[state=active]:text-orange-400"
              key={tab}
              value={tab}
            >
              {t(`${scope}.section.${tab}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="flex flex-wrap justify-end gap-2">
          {section === "status" && canConfigure && (
            <Button className="gap-2 border-orange-500/30 text-orange-700 hover:bg-orange-500/10 dark:text-orange-400"
              size="sm" variant="outline" onClick={() => openSettings("settings")}>
              <Settings2 className="size-3.5" />{t(`${scope}.configure`)}
            </Button>
          )}
          {section === "rules" && revision && !ruleForm && (
            <Button className="gap-2 border-orange-500/30 text-orange-700 hover:bg-orange-500/10 dark:text-orange-400"
              size="sm" variant="outline" disabled={saving} onClick={() => {
                setRuleFeedback(undefined)
                setExpandedRule(undefined)
                setRuleForm({ revision, draft: {
                  direction: "IN", action: "ACCEPT", protocol: "tcp", dport: "", source: "", iface: "", comment: "",
                  log: "nolog",
                } })
              }}>
              <Plus className="size-3.5" />{t("securityPage.firewall.addRule")}
            </Button>
          )}
          <Button className="gap-2" size="sm" variant="outline" disabled={active.loading || saving} onClick={() => {
            if (section === "rules") setRuleForm(undefined)
            active.refresh()
            if (section === "log") status.refresh()
          }}>
            {active.loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            {t(`${scope}.refresh`)}
          </Button>
        </div>
      </div>
      <div ref={scrollRegion} className="min-h-0 flex-1 overflow-y-auto px-1 pb-1">
        {active.loading && <p className="mb-2 text-sm text-muted-foreground" role="status">{t(`${scope}.reading`)}</p>}
        {active.error && (
          <p className="mb-2 rounded-md border border-amber-500/30 p-2 text-sm" role="status">
            {t(`${scope}.${active.error}`)} {active.data && t(`${scope}.stale`)}
          </p>
        )}
        <TabsContent className="mt-0 space-y-3" value="status">
          {settingsFeedback && <p className="flex items-center gap-2 rounded-md border p-2 text-sm" role="status">
            <Check className="size-4 text-green-600 dark:text-green-400" aria-hidden />{settingsFeedback.message}
          </p>}
          {status.data && <FirewallStatus data={status.data}
            onClusterFirewall={onClusterFirewall}
            onAddInterface={canConfigure ? () => openSettings("network") : undefined} />}
        </TabsContent>
        <TabsContent className="mt-0 space-y-3" value="rules">
          {status.data && !status.loading && !status.error && firewallBlocker(status.data) && (
            <div className="flex flex-wrap items-center justify-between gap-1 rounded-md border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs">
              <p>{t(`${scope}.rulesInactive`, { reason: t(`${scope}.${firewallBlocker(status.data)}`) })}</p>
              <Button type="button" variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => {
                setSection("status")
                if (scrollRegion.current) scrollRegion.current.scrollTop = 0
              }}>{t(`${scope}.section.status`)}</Button>
            </div>
          )}
          {ruleFeedback && (
            <p className="flex items-center gap-2 rounded-md border border-border p-2 text-sm" role="status">
              {ruleFeedback.success && <Check className="size-4 text-green-600 dark:text-green-400" aria-hidden />}
              {t(`${scope}.${ruleFeedback.key}`)}
            </p>
          )}
          {!ruleForm?.original && editor}
          {rules.data && (!ruleForm || ruleForm.original || rules.data.rules.length > 0) && <FirewallRules
            rules={rules.data.rules}
            expanded={expandedRule}
            onExpand={position => {
              if (submitting.current) return
              if (ruleForm?.original) setRuleForm(undefined)
              setExpandedRule(position)
            }}
            editable={revision && !ruleForm ? rules.data.editable_rule_positions ?? [] : []}
            writable={revision && !ruleForm ? rules.data.writable_rule_positions ?? [] : []}
            moveRevision={!ruleForm && !saving ? revision : null}
            onMove={(rule, to) => {
              if (revision && !submitting.current && !ruleForm && to !== rule.pos && to >= 0 && to < (rules.data?.rules.length ?? 0)) {
                setConfirmation({ rule, to, action: "move", revision })
              }
            }}
            onAction={(rule, action) => {
              if (revision && !submitting.current) setConfirmation({ rule, action, revision })
            }}
            onEdit={rule => {
              if (!revision || submitting.current) return
              setRuleFeedback(undefined)
              setRuleForm({ revision, original: rule, draft: draftFromRule(rule) })
            }}
            editing={ruleForm?.original?.pos}
            editor={editor}
            saving={saving}
          />}
        </TabsContent>
        <TabsContent className="mt-0" value="log">{log.data && (
          <FirewallLogs logs={log.data.logs} status={!status.loading && !status.error ? status.data : undefined} />
        )}</TabsContent>
      </div>
      <Dialog open={Boolean(confirmation)} onOpenChange={open => {
        if (!open && !submitting.current) setConfirmation(undefined)
      }}>
        {confirmation && <DialogContent className="w-[calc(100%-2rem)] max-w-md" hideClose overlayClassName="bg-black/40">
          <DialogHeader>
            <DialogTitle>{t(`${scope}.${ruleActions[confirmation.action].title}`)}</DialogTitle>
            <DialogDescription>
              {t(`${scope}.confirmRuleTarget`, {
                guest: `${guest.type === "lxc" ? "LXC" : "VM"} ${guest.vmid}`,
                position: confirmation.rule.pos + 1,
                rule: [confirmation.rule.type.toUpperCase(), confirmation.rule.action, confirmation.rule.proto,
                  confirmation.rule.dport, confirmation.rule.source].filter(Boolean).join(" · "),
              })}
              {confirmation.action === "move" && (
                <> {t(`${scope}.confirmMovePosition`, { from: confirmation.rule.pos + 1, to: confirmation.to + 1 })}</>
              )}
              {(confirmation.rule.enabled || confirmation.action === "enable" || confirmation.action === "move") && (
                <> {t(`${scope}.ruleTrafficImpact`)}</>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" disabled={saving} onClick={() => setConfirmation(undefined)}>{t("actions.cancel")}</Button>
            <Button variant={confirmation.action === "delete" ? "destructive" : "default"}
              disabled={saving || confirmation.revision !== revision} onClick={() => {
                const { rule, action, revision: startRevision } = confirmation
                if (confirmation.action === "move") {
                  void writeRule("PATCH", startRevision, { pos: rule.pos, to: confirmation.to }, ruleActions.move.success)
                  return
                }
                void writeRule(action === "delete" ? "DELETE" : "PATCH", startRevision, {
                  pos: rule.pos, ...(action === "delete" ? {} : { enabled: action === "enable" }),
                }, ruleActions[action].success)
              }}>
              {saving && confirmation.action === "move" ? <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                {t(`${scope}.movingRule`)}
              </> : t(`${scope}.${ruleActions[confirmation.action].label}`)}
            </Button>
          </DialogFooter>
        </DialogContent>}
      </Dialog>
      {settingsMode && <GuestFirewallSettings guest={guest} mode={settingsMode}
        missingPrerequisite={status.data?.cluster_enabled !== true || status.data?.service !== "running"}
        onClose={() => setSettingsMode(undefined)}
        onSaved={result => {
          setSettingsMode(undefined)
          const pending = result.pending.length > 0
          setSettingsFeedback({
            pending,
            message: t(`${scope}.${pending ? "settingsPending" : result.interface ? "interfaceAdded" : "settingsSaved"}`,
              { interfaces: result.pending.join(", "), interface: result.interface ?? "" }),
          })
          status.refresh()
        }}
        onUncertain={status.refresh}
      />}
    </Tabs>
  )
}
