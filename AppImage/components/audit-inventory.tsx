"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import {
  Activity, Boxes, ChevronDown, ChevronRight, CircuitBoard, Cpu, HardDrive,
  Loader2, MemoryStick, Network, Package, Plug, Server, Share2, Wrench,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT, useI18n } from "../lib/i18n/provider"
import { subscriptionLabel } from "../lib/audit-presentation"

interface UplinkHop { kind: string; id: string; mode?: string; role?: string }
interface GuestDisk {
  slot: string; storage: string | null; volume: string
  size: string; passthrough?: boolean
}
interface GuestNic {
  slot: string; name: string; bridge: string; mac: string; vlan: string
  uplink: UplinkHop[] | null
}
interface GuestBackup { job: string; storage: string; schedule: string; retention: string }
interface Guest {
  vmid: number; type: string; name: string; cores: string; memory: string
  ostype: string; onboot: boolean; tags: string; protected: boolean
  unprivileged: boolean | null; features: string | null
  agent: boolean | null; cpu: string | null
  disks: GuestDisk[]; interfaces: GuestNic[]; backups: GuestBackup[]
}
interface Inventory {
  collected_at: number
  node: string
  unavailable: Record<string, string>
  sections: {
    identity?: Record<string, string | null>
    cluster?: any
    hardware?: any
    storages?: any[]
    guests?: Guest[]
    passthrough?: any[]
    applications?: any[]
    custom_links?: any[]
    proxmenux?: { optimizations: any[]; pending_updates: any[] }
    network?: { bridges: Record<string, any> } | null
    latency?: { window: string; targets: any[] } | null
  }
}

const GiB = 1024 ** 3

function bytes(value: number | null | undefined): string {
  if (!value || value <= 0) return "—"
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
  let n = value, i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n >= 100 || i < 2 ? Math.round(n) : n.toFixed(1)} ${units[i]}`
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === "") return null
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm text-foreground break-words">{value}</p>
    </div>
  )
}

/**
 * One table shape for the whole view.
 *
 * The inventory is read across as much as down — a disk's model beside
 * its bus beside its wear — so the sections that enumerate things share
 * a single table rather than each inventing its own row layout.
 *
 * On a narrow screen the same rows are stacked instead. A disk table is
 * eight columns wide; sideways scrolling technically fits it on a phone,
 * but reading a row then means dragging back and forth to pair each
 * value with its heading. Stacked, the heading travels with the value.
 */
function DataTable({ columns, rows }: {
  columns: string[]
  rows: React.ReactNode[][]
}) {
  if (rows.length === 0) return null
  return (
    <>
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              {columns.map((c, i) => (
                <th key={i} className="pb-2 pr-4 font-medium whitespace-nowrap">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-t border-border">
                {row.map((cell, j) => (
                  <td key={j} className="py-2 pr-4 align-top tabular-nums">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sm:hidden space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="rounded-md border border-border p-2.5 space-y-1">
            {row.map((cell, j) => {
              // A cell with nothing in it would leave a heading standing
              // alone, which reads as missing data rather than as absent.
              if (cell === null || cell === undefined || cell === "" || cell === "—") return null
              return (
                <div key={j} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-xs text-muted-foreground shrink-0">{columns[j]}</span>
                  <span className="text-sm text-foreground tabular-nums break-words min-w-0">
                    {cell}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </>
  )
}

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-xs text-muted-foreground">{children}</span>
}

function Section({
  icon, title, count, children, note,
}: {
  icon: React.ReactNode; title: string; count?: number
  children: React.ReactNode; note?: string
}) {
  const [open, setOpen] = useState(true)
  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-center gap-2 rounded-md -mx-2 -my-1 px-2 py-1
                     text-left hover:bg-white/5 transition-colors cursor-pointer"
        >
          {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
                : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          <CardTitle className="flex min-w-0 items-center gap-2 text-base font-semibold text-foreground">
            {icon}<span className="min-w-0 break-words">{title}</span>
          </CardTitle>
          {count !== undefined && (
            <Badge variant="outline" className="ml-auto shrink-0 text-xs tabular-nums">{count}</Badge>
          )}
        </button>
      </CardHeader>
      {open && (
        <CardContent className="pt-0 space-y-3">
          {note && <p className="text-xs text-muted-foreground">{note}</p>}
          {children}
        </CardContent>
      )}
    </Card>
  )
}

/** A heading inside a section, matching the printed document's. */
function Sub({ icon, title, note }: {
  icon: React.ReactNode; title: string; note?: string
}) {
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-foreground mt-4 mb-1 first:mt-0">
      {icon}{title}
      {note && <span className="font-normal text-muted-foreground">— {note}</span>}
    </p>
  )
}

// The uplink is the point of the network section: a bridge on its own
// says nothing, the path from it to the wire is what an operator needs.
function Uplink({ hops }: { hops: UplinkHop[] | null }) {
  const t = useT()
  if (hops === null) {
    return <span className="text-xs text-muted-foreground italic">{t("audit.inventory.unresolved")}</span>
  }
  if (hops.length === 0) {
    return <span className="text-xs text-muted-foreground">{t("audit.inventory.noUplink")}</span>
  }
  return (
    <span className="flex flex-wrap items-center gap-1 text-xs">
      {hops.map((h, i) => (
        <span key={`${h.id}-${i}`} className="flex items-center gap-1">
          {i > 0 && <span className="text-muted-foreground">→</span>}
          <Badge variant="outline" className="font-mono text-xs">
            {h.id}{h.mode ? ` · ${h.mode}` : ""}
          </Badge>
        </span>
      ))}
    </span>
  )
}

export function AuditInventory({ profile = "full" }: { profile?: string }) {
  const t = useT()
  const { language } = useI18n()
  const [data, setData] = useState<Inventory | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openGuest, setOpenGuest] = useState<Set<number>>(new Set())

  const load = useCallback(async () => {
    try {
      const res: any = await fetchApi(
        `/api/audit/inventory?profile=${encodeURIComponent(profile)}`)
      if (res?.success) { setData(res.inventory); setError(null) }
      else setError(res?.message || t("audit.inventory.failed"))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setLoading(false) }
  }, [t, profile])

  useEffect(() => { load() }, [load])

  const apps = useMemo(() => {
    const byGuest = new Map<number, any[]>()
    for (const a of data?.sections.applications || []) {
      if (!byGuest.has(a.vmid)) byGuest.set(a.vmid, [])
      byGuest.get(a.vmid)!.push(a)
    }
    return byGuest
  }, [data])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />{t("audit.inventory.loading")}
      </div>
    )
  }
  if (error) return <p className="text-sm text-red-400 px-1">{error}</p>
  if (!data) return null

  const s = data.sections
  const hw = s.hardware || {}
  const mem = hw.memory || {}
  const when = (value: number | string | null | undefined) => {
    if (!value) return "—"
    const date = typeof value === "number"
      ? new Date(value * 1000)
      : new Date(/[Z+]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(language)
  }
  const toggle = (vmid: number) => setOpenGuest((prev) => {
    const next = new Set(prev)
    next.has(vmid) ? next.delete(vmid) : next.add(vmid)
    return next
  })

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground px-1">
        {t("audit.inventory.collectedAt", {
          when: new Date(data.collected_at * 1000).toLocaleString(language),
        })}
      </p>

      {/* Sections that could not be read are named, so an empty list is
          never mistaken for a section that was read and found nothing. */}
      {Object.keys(data.unavailable || {}).length > 0 && (
        <Card className="bg-card border-border">
          <CardContent className="py-3 space-y-1">
            <p className="text-xs font-medium text-muted-foreground">
              {t("audit.inventory.unavailable")}
            </p>
            {Object.entries(data.unavailable).map(([k, v]) => (
              <p key={k} className="text-xs text-muted-foreground">
                <span className="font-mono">{k}</span> — {v}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {s.identity && (
      <Section icon={<Server className="h-4 w-4 text-blue-500" />} title={t("audit.inventory.identity")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("audit.inventory.node")} value={s.identity?.node} />
          <Field label={t("audit.inventory.pveVersion")} value={s.identity?.pve_version} />
          <Field label={t("audit.inventory.kernel")} value={s.identity?.kernel} />
          <Field label={t("audit.inventory.subscription")} value={subscriptionLabel(t, s.identity?.subscription)} />
          <Field label={t("audit.inventory.cluster")}
                 value={s.identity?.cluster || t("audit.inventory.standalone")} />
          <Field label={t("audit.document.system")}
                 value={[hw.system?.manufacturer, hw.system?.product].filter(Boolean).join(" ")} />
        </div>
      </Section>
      )}

      {"cluster" in s && (
      <Section icon={<Share2 className="h-4 w-4 text-cyan-500" />} title={t("audit.document.cluster")}
               count={s.cluster ? (s.cluster.nodes || []).length : undefined}
               note={s.cluster ? undefined : t("audit.document.standaloneNote")}>
        {s.cluster && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("audit.inventory.cluster")} value={s.cluster.name} />
              <Field label={t("audit.document.quorum")}
                     value={s.cluster.quorate == null ? "—" : (
                       <Badge variant="outline" className={s.cluster.quorate
                         ? "bg-green-500/10 text-green-500 border-green-500/20"
                         : "bg-red-500/10 text-red-500 border-red-500/20"}>
                         {t(s.cluster.quorate ? "audit.document.quorate"
                                              : "audit.document.inquorate")}
                       </Badge>
                     )} />
              <Field label={t("audit.document.votes")}
                     value={`${s.cluster.total_votes ?? "—"} / ${s.cluster.expected_votes ?? "—"}`} />
            </div>
            <DataTable
              columns={[t("audit.document.nodeName"), "nodeid", "ring0", "ring1",
                        t("audit.document.state")]}
              rows={(s.cluster.nodes || []).map((n: any) => [
                <span className="font-medium text-foreground">
                  {n.name}
                  {n.local && <span className="text-muted-foreground">
                    {" "}({t("audit.document.thisNode")})</span>}
                </span>,
                <Mono>{n.nodeid || "—"}</Mono>,
                <Mono>{n.ring0_addr || "—"}</Mono>,
                <Mono>{n.ring1_addr || "—"}</Mono>,
                n.online === false
                  ? <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20">
                      {t("audit.document.unreachable")}</Badge>
                  : n.online === true
                    ? <Badge variant="outline">{t("audit.document.member")}</Badge>
                    : "—",
              ])}
            />
          </>
        )}
      </Section>
      )}

      {s.hardware && (
      <Section icon={<Cpu className="h-4 w-4 text-indigo-500" />} title={t("audit.document.architecture")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("audit.inventory.cpu")} value={hw.cpu?.model} />
          <Field label={t("audit.inventory.topology")}
                 value={hw.cpu ? t("audit.inventory.cpuLayout", {
                   sockets: String(hw.cpu.sockets), cores: String(hw.cpu.cores_per_socket),
                   threads: String(hw.cpu.threads),
                 }) : ""} />
          <Field label={t("audit.inventory.memory")}
                 value={hw.memory_bytes ? `${(hw.memory_bytes / GiB).toFixed(0)} GiB` : ""} />
          <Field label={t("audit.inventory.virtualisation")} value={hw.cpu?.virtualisation} />
          <Field label={t("audit.inventory.serial")} value={hw.system?.serial} />
          <Field label={t("audit.document.board")}
                 value={[hw.board?.manufacturer, hw.board?.product].filter(Boolean).join(" ")} />
          <Field label={t("audit.inventory.bios")}
                 value={[hw.bios?.vendor, hw.bios?.version, hw.bios?.date].filter(Boolean).join(" · ")} />
          <Field label={t("audit.inventory.iommuGroups")} value={hw.iommu_groups} />
        </div>

        {(mem.modules || []).length > 0 && (
          <>
            <Sub icon={<MemoryStick className="h-3.5 w-3.5 text-muted-foreground" />}
                 title={t("audit.document.memoryModules")}
                 note={t("audit.document.slotsFilled", {
                   used: String(mem.populated ?? 0),
                   total: String(mem.slots ?? mem.populated ?? 0),
                 })} />
            <DataTable
              columns={[t("audit.document.slot"), t("audit.document.size"),
                        t("audit.document.type"), t("audit.document.formFactor"),
                        t("audit.document.speed"), t("audit.document.manufacturer")]}
              rows={(mem.modules || []).map((m: any) => [
                <Mono>{m.locator || "—"}</Mono>, m.size || "—", m.type || "—",
                m.form_factor || "—", m.speed || "—",
                [m.manufacturer, m.part_number].filter(Boolean).join(" · ") || "—",
              ])}
            />
          </>
        )}

        {(hw.controllers || []).length > 0 && (
          <>
            <Sub icon={<CircuitBoard className="h-3.5 w-3.5 text-muted-foreground" />}
                 title={t("audit.document.controllers")} />
            <DataTable
              columns={["PCI", t("audit.document.class"), t("audit.document.device")]}
              rows={(hw.controllers || []).map((c: any) => [
                <Mono>{c.slot}</Mono>, c.class, c.name,
              ])}
            />
          </>
        )}
      </Section>
      )}

      {(hw.disks || []).length > 0 && (
      <Section icon={<HardDrive className="h-4 w-4 text-amber-500" />} title={t("audit.document.storageDevices")}
               count={(hw.disks || []).length}>
        <DataTable
          columns={[t("audit.document.device"), t("audit.document.model"),
                    t("audit.document.serial"), t("audit.document.size"),
                    t("audit.document.bus"), "SMART", t("audit.document.serviceLife"),
                    t("audit.document.events")]}
          rows={(hw.disks || []).map((d: any) => {
            const ok = ["passed", "healthy", "ok"].includes(String(d.health).toLowerCase())
            return [
              <span className="font-medium text-foreground">{d.name}</span>,
              d.model || "—",
              <Mono>{d.serial || "—"}</Mono>,
              bytes(d.size_bytes),
              `${(d.bus || "—").toUpperCase()} · ${d.rotational ? "HDD" : "SSD"}`,
              ok
                ? <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    {t("audit.document.healthy")}</Badge>
                : d.health && d.health !== "unknown"
                  ? <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20">
                      {d.health}</Badge>
                  : "—",
              typeof d.power_on_hours === "number" && d.power_on_hours > 0
                ? t("audit.document.years", { years: (d.power_on_hours / 8760).toFixed(1) })
                : "—",
              (d.observations || []).length
                ? <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20 tabular-nums">
                    {d.observations.length}</Badge>
                : <span className="text-muted-foreground">—</span>,
            ]
          })}
        />

        {(hw.disks || []).some((d: any) => (d.observations || []).length > 0) && (
          <>
            <Sub icon={<Activity className="h-3.5 w-3.5 text-muted-foreground" />}
                 title={t("audit.document.observations")}
                 note={t("audit.document.observationsNote")} />
            {(hw.disks || []).filter((d: any) => (d.observations || []).length).map((d: any) => (
              <div key={d.name} className="mt-2">
                <p className="text-xs font-medium text-foreground mb-1">
                  {d.name} <span className="font-normal text-muted-foreground">{d.model}</span>
                </p>
                <DataTable
                  columns={[t("audit.document.event"), t("audit.document.severity"),
                            t("audit.document.occurrences"), t("audit.document.firstSeen"),
                            t("audit.document.lastSeen"), t("audit.document.detail")]}
                  rows={d.observations.map((o: any) => [
                    o.type || "—",
                    <Badge variant="outline" className={o.severity === "critical"
                      ? "bg-red-500/10 text-red-500 border-red-500/20"
                      : "bg-amber-500/10 text-amber-500 border-amber-500/20"}>
                      {o.severity
                        ? t(`audit.classifications.${
                            o.severity === "critical" ? "critical" : "warning"}`)
                        : "—"}</Badge>,
                    String(o.count ?? "—"),
                    when(o.first_seen), when(o.last_seen),
                    <span className="text-muted-foreground break-words">{o.message || ""}</span>,
                  ])}
                />
              </div>
            ))}
          </>
        )}
      </Section>
      )}

      {(s.network || (hw.adapters || []).length > 0) && (
      <Section icon={<Network className="h-4 w-4 text-green-500" />} title={t("audit.inventory.network")}
               count={Object.keys(s.network?.bridges || {}).length || undefined}>
        {(hw.adapters || []).length > 0 && (
          <>
            <Sub icon={<Plug className="h-3.5 w-3.5 text-muted-foreground" />}
                 title={t("audit.document.physicalAdapters")} />
            <DataTable
              columns={[t("audit.document.interface"), t("audit.document.state"),
                        t("audit.document.speed"), "MAC", t("audit.document.driver"), "PCI"]}
              rows={(hw.adapters || []).map((a: any) => [
                <span className="font-medium text-foreground">{a.name}</span>,
                a.state === "up"
                  ? <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                      {a.state}</Badge>
                  : <Badge variant="outline">{a.state || "—"}</Badge>,
                a.speed_mbps
                  ? (a.speed_mbps >= 1000 ? `${a.speed_mbps / 1000} Gb/s` : `${a.speed_mbps} Mb/s`)
                  : "—",
                <Mono>{a.mac || "—"}</Mono>, a.driver || "—", <Mono>{a.pci || "—"}</Mono>,
              ])}
            />
          </>
        )}
        {s.network && (
          <>
            <Sub icon={<Network className="h-3.5 w-3.5 text-muted-foreground" />}
                 title={t("audit.document.bridges")} />
            <div className="space-y-2">
              {Object.entries(s.network.bridges || {}).map(([id, b]: [string, any]) => (
                <div key={id} className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge variant="outline" className="font-mono">{id}</Badge>
                  <span className="text-muted-foreground">→</span>
                  <Uplink hops={b.uplink} />
                  {b.vlan_interface && (
                    <Badge variant="outline" className="text-xs">VLAN {b.vlan_interface}</Badge>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                    {(s.guests || []).filter((g) =>
                      (g.interfaces || []).some((n) => n.bridge === id)).length}
                    {" "}{t("audit.inventory.guests").toLowerCase()}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </Section>
      )}

      {s.latency?.targets?.length ? (
      <Section icon={<Activity className="h-4 w-4 text-sky-500" />} title={t("audit.document.latency")}
               note={t("audit.document.latencyNote")}>
        <DataTable
          columns={[t("audit.document.target.label"), t("audit.document.minimum"),
                    t("audit.document.average"), t("audit.document.maximum"),
                    t("audit.document.packetLoss"), t("audit.document.samples")]}
          rows={s.latency.targets.map((target: any) => [
            <span className="font-medium text-foreground">
              {t(`audit.document.target.${target.target}`)}</span>,
            target.min_ms != null ? `${target.min_ms} ms` : "—",
            target.avg_ms != null ? `${target.avg_ms} ms` : "—",
            target.max_ms != null ? `${target.max_ms} ms` : "—",
            target.packet_loss != null ? `${target.packet_loss} %` : "—",
            String(target.samples),
          ])}
        />
      </Section>
      ) : null}

      {s.storages && (
      <Section icon={<HardDrive className="h-4 w-4 text-purple-500" />} title={t("audit.inventory.storage")}
               count={(s.storages || []).length}>
        <DataTable
          columns={[t("audit.inventory.name"), t("audit.inventory.type"),
                    t("audit.inventory.content"), t("audit.inventory.shared"),
                    t("audit.document.location"), t("audit.inventory.guests")]}
          rows={(s.storages || []).map((st: any) => [
            <Mono>{st.id}</Mono>, st.type,
            <span className="text-muted-foreground text-xs">{st.content}</span>,
            st.shared
              ? <Badge variant="outline">{t("audit.inventory.yes")}</Badge>
              : <span className="text-muted-foreground">—</span>,
            <span className="text-muted-foreground text-xs break-all">
              {st.server || st.path || "—"}</span>,
            String((s.guests || []).filter((g) =>
              (g.disks || []).some((d) => d.storage === st.id)).length),
          ])}
        />
      </Section>
      )}

      {s.guests && (
      <Section icon={<Boxes className="h-4 w-4 text-emerald-500" />} title={t("audit.inventory.guests")}
               count={(s.guests || []).length}>
        <div className="space-y-2">
          {(s.guests || []).map((g) => {
            const open = openGuest.has(g.vmid)
            const guestApps = apps.get(g.vmid) || []
            return (
              <div key={g.vmid} className="rounded-md border border-border">
                <button
                  type="button"
                  onClick={() => toggle(g.vmid)}
                  aria-expanded={open}
                  className="flex w-full flex-wrap items-center gap-2 rounded-md p-3 text-left hover:bg-white/5 transition-colors cursor-pointer"
                >
                  {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                        : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
                  <Badge variant="outline" className="font-mono text-xs">{g.vmid}</Badge>
                  <span className="font-medium text-foreground">{g.name || "—"}</span>
                  <Badge variant="outline" className="text-xs uppercase">{g.type}</Badge>
                  {/* Whether a guest needs a backup is not visible from
                      here, so its absence is stated, not flagged. */}
                  {g.backups.length === 0 && (
                    <Badge variant="outline" className="text-xs">
                      {t("audit.inventory.noBackup")}
                    </Badge>
                  )}
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
                    {g.cores}c · {g.memory}MB
                  </span>
                </button>

                {open && (
                  <div className="border-t border-border p-3 space-y-4">
                    <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
                      <Field label={t("audit.inventory.ostype")} value={g.ostype} />
                      <Field label={t("audit.inventory.onboot")}
                             value={g.onboot ? t("audit.inventory.yes") : t("audit.inventory.no")} />
                      <Field label={t("audit.inventory.tags")} value={g.tags} />
                      {g.type === "lxc" && (
                        <Field label={t("audit.inventory.privilege")}
                               value={g.unprivileged ? t("audit.inventory.unprivileged")
                                                     : t("audit.inventory.privileged")} />
                      )}
                      {g.type === "lxc" && <Field label={t("audit.inventory.features")} value={g.features} />}
                      {g.type === "qemu" && (
                        <Field label={t("audit.inventory.agent")}
                               value={g.agent ? t("audit.inventory.yes") : t("audit.inventory.no")} />
                      )}
                      {g.type === "qemu" && <Field label={t("audit.inventory.cpuModel")} value={g.cpu} />}
                    </div>

                    {g.disks.length > 0 && (
                      <div>
                        <Sub icon={<HardDrive className="h-3.5 w-3.5 text-muted-foreground" />}
                             title={t("audit.inventory.disks")} />
                        <DataTable
                          columns={[t("audit.document.slot"), t("audit.document.storage"),
                                    t("audit.inventory.name"), t("audit.document.size")]}
                          rows={g.disks.map((d) => [
                            <Mono>{d.slot}</Mono>,
                            d.storage
                              ? <Badge variant="outline" className="font-mono text-xs">{d.storage}</Badge>
                              : <Badge variant="outline" className="text-xs">
                                  {t("audit.inventory.passthrough")}</Badge>,
                            <span className="font-mono text-xs break-all">{d.volume}</span>,
                            d.size || "—",
                          ])}
                        />
                      </div>
                    )}

                    {g.interfaces.length > 0 && (
                      <div>
                        <Sub icon={<Network className="h-3.5 w-3.5 text-muted-foreground" />}
                             title={t("audit.inventory.interfaces")} />
                        <div className="space-y-1">
                          {g.interfaces.map((n) => (
                            <div key={n.slot} className="flex flex-wrap items-center gap-1.5 text-xs">
                              <Badge variant="outline" className="font-mono">{n.slot}</Badge>
                              <span className="text-muted-foreground">→</span>
                              <Badge variant="outline" className="font-mono">{n.bridge}</Badge>
                              <span className="text-muted-foreground">→</span>
                              <Uplink hops={n.uplink} />
                              {n.vlan && <Badge variant="outline">VLAN {n.vlan}</Badge>}
                              {n.mac && <Mono>{n.mac}</Mono>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div>
                      <Sub icon={<Package className="h-3.5 w-3.5 text-muted-foreground" />}
                           title={t("audit.inventory.protection")} />
                      {g.backups.length === 0 ? (
                        <p className="text-xs text-muted-foreground">
                          {t("audit.inventory.noBackupDetail")}</p>
                      ) : (
                        <DataTable
                          columns={[t("audit.document.backup"), t("audit.document.storage"),
                                    t("audit.inventory.type"), t("audit.document.content")]}
                          rows={g.backups.map((b) => [
                            <Mono>{b.job}</Mono>,
                            <Badge variant="outline" className="font-mono text-xs">{b.storage}</Badge>,
                            b.schedule || "—", b.retention || "—",
                          ])}
                        />
                      )}
                    </div>

                    {guestApps.length > 0 && (
                      <div>
                        <Sub icon={<Wrench className="h-3.5 w-3.5 text-muted-foreground" />}
                             title={t("audit.inventory.applications")} />
                        <div className="space-y-1">
                          {guestApps.map((a: any, i: number) => (
                            <div key={`${a.slug}-${i}`} className="flex flex-wrap items-center gap-1.5 text-xs">
                              <span className="text-foreground">{a.name}</span>
                              <Mono>{a.version || t("audit.inventory.versionUnknown")}</Mono>
                              {a.update_available && (
                                <Badge variant="outline" className="bg-purple-600/15 text-purple-400 border-purple-500/20">
                                  {a.available}
                                </Badge>
                              )}
                              {(a.ports || []).map((p: any, j: number) => (
                                <Badge key={j} variant="outline" className="font-mono">
                                  {p.scheme}:{p.port}{p.path}
                                </Badge>
                              ))}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </Section>
      )}

      {(s.passthrough || []).length > 0 && (
      <Section icon={<Plug className="h-4 w-4 text-violet-500" />} title={t("audit.inventory.passthroughTitle")}
               count={(s.passthrough || []).length}>
        <DataTable
          columns={[t("audit.document.vmid"), t("audit.document.name"),
                    t("audit.document.slot"), t("audit.document.device"),
                    t("audit.document.iommuGroup"), t("audit.inventory.sharedGroup")]}
          rows={(s.passthrough || []).map((p: any) => [
            <Mono>{p.vmid}</Mono>,
            p.guest || "—",
            <Mono>{p.slot || "—"}</Mono>,
            <Mono>{p.address || "—"}</Mono>,
            (p.iommu_groups || []).join(", ") || "—",
            // Everything in a group moves together, so a shared group is
            // what decides whether the passthrough is possible.
            (p.shared_group_devices || []).length
              ? <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20 tabular-nums">
                  {p.shared_group_devices.length}</Badge>
              : <span className="text-muted-foreground">—</span>,
          ])}
        />
      </Section>
      )}

      {s.proxmenux && (
      <Section icon={<Wrench className="h-4 w-4 text-orange-500" />} title={t("audit.inventory.proxmenux")}
               count={(s.proxmenux.optimizations || []).length}>
        <DataTable
          columns={[t("audit.document.name"), t("audit.document.version"),
                    t("audit.document.state")]}
          rows={(s.proxmenux.optimizations || []).map((o: any) => {
            const pending = (s.proxmenux!.pending_updates || [])
              .find((u: any) => u.key === o.key)
            return [
              <Mono>{o.key}</Mono>,
              o.version || "—",
              pending
                ? <Badge variant="outline" className="bg-purple-600/15 text-purple-400 border-purple-500/20">
                    {t("audit.document.updateAvailable", { version: String(pending.available) })}
                  </Badge>
                : <Badge variant="outline">{t("audit.document.current")}</Badge>,
            ]
          })}
        />
      </Section>
      )}
    </div>
  )
}
