"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { Wifi, Activity, Network, Router, AlertCircle, Zap, Timer, EthernetPort, ArrowDown, ArrowUp, Box, ChevronRight } from 'lucide-react'
import useSWR from "swr"
import { NetworkTrafficChart } from "./network-traffic-chart"
import { NetworkFlow, type NetworkFlowData } from "./network-flow"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"
import { LatencyDetailModal } from "./latency-detail-modal"
import { AreaChart, Area, LineChart, Line, ResponsiveContainer, YAxis } from "recharts"
import { useT } from "../lib/i18n/provider"

type TFunction = (key: string, params?: Record<string, string | number>) => string

interface NetworkData {
  interfaces: NetworkInterface[]
  physical_interfaces?: NetworkInterface[]
  bridge_interfaces?: NetworkInterface[]
  // Bond masters. Also present inside `interfaces` for backward
  // compatibility; this list is what the topology diagram consumes.
  bond_interfaces?: NetworkInterface[]
  vm_lxc_interfaces?: NetworkInterface[]
  traffic: {
    bytes_sent: number
    bytes_recv: number
    packets_sent?: number
    packets_recv?: number
    packet_loss_in?: number
    packet_loss_out?: number
    dropin?: number
    dropout?: number
    errin?: number
    errout?: number
  }
  active_count?: number
  total_count?: number
  physical_active_count?: number
  physical_total_count?: number
  bridge_active_count?: number
  bridge_total_count?: number
  vm_lxc_active_count?: number
  vm_lxc_total_count?: number
  hostname?: string
  domain?: string
  dns_servers?: string[]
}

interface NetworkInterface {
  name: string
  type: string
  status: string
  speed: number
  duplex: string
  mtu: number
  mac_address: string | null
  addresses: Array<{
    ip: string
    netmask: string
  }>
  bytes_sent?: number
  bytes_recv?: number
  packets_sent?: number
  packets_recv?: number
  errors_in?: number
  errors_out?: number
  drops_in?: number
  drops_out?: number
  // Live rate (bytes/sec) computed by the backend as the delta
  // between this poll and the previous one. Present from the second
  // /api/network response onward; absent on the first call after the
  // service starts or after a long pause.
  rx_Bps?: number
  tx_Bps?: number
  // Hardware ceiling parsed from ethtool's "Supported link modes".
  // The card shows "(max N Gbps)" next to the negotiated speed when
  // the link is auto-negotiated below the NIC's max.
  max_speed?: number
  // Bridges that have this physical NIC as their underlying interface
  // (directly, or as a bond slave). Surfaced in the card so the
  // operator can see "this NIC → vmbr0" at a glance.
  used_by_bridges?: string[]
  bond_mode?: string
  // Kernel's human-readable mode, e.g. "fault-tolerance (active-backup)".
  // bond_mode holds the short form ("active-backup") that matches
  // /etc/network/interfaces and the Proxmox UI.
  bond_mode_detail?: string | null
  bond_slaves?: string[]
  bond_active_slave?: string | null
  // True only for modes where a slave really sits idle (active-backup).
  bond_supports_failover?: boolean
  bond_slave_status?: Record<string, string>
  // Set on a physical NIC that is enslaved to a bond.
  bond_master?: string
  bond_role?: "active" | "standby" | "member"
  bond_link?: string
  // Master device resolved from /sys/class/net/<iface>/master — the
  // bridge for a guest tap, the bond for a slave NIC.
  bridge_owner?: string
  bridge_members?: string[]
  bridge_physical_interface?: string
  bridge_bond_slaves?: string[]
  bridge_vlan_interface?: string | null
  packet_loss_in?: number
  packet_loss_out?: number
  vmid?: number
  vm_name?: string
  vm_type?: string
  vm_status?: string
}

// Same dot-prefix tone the Storage cards use, so a "no errors" /
// "errors present" cue reads identically across pages.
const NetStatusDot = ({ tone }: { tone: "ok" | "warn" | "fail" }) => {
  const cls =
    tone === "ok" ? "bg-green-500" : tone === "warn" ? "bg-yellow-500" : "bg-red-500"
  return <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${cls}`} aria-hidden />
}
const netCounterTone = (n: number | null | undefined): "ok" | "warn" | "fail" => {
  if (!n || n <= 0) return "ok"
  if (n < 10) return "warn"
  return "fail"
}

// Icon picker — defaults to the actual port type rather than a Wi-Fi
// glyph for everything. Wireless interfaces (wl*/wifi*) keep the Wi-Fi
// glyph; wired NICs use EthernetPort; bonds/bridges/vlans get more
// specific icons so the operator can tell them apart at a glance.
function getInterfaceIcon(iface: NetworkInterface): React.ComponentType<{ className?: string }> {
  const name = (iface.name || "").toLowerCase()
  const type = (iface.type || "").toLowerCase()
  if (name.startsWith("wl") || name.startsWith("wifi")) return Wifi
  if (type === "bridge") return Network
  if (type === "bond") return Router
  if (type === "vlan") return Activity
  if (type === "vm_lxc" || type === "virtual") return Box
  // Physical wired NIC (eth0, enp*, ens*, eno*, nic0, …) → ethernet port.
  return EthernetPort
}

// Match the dark blue badge tone the Storage card uses for the disk
// type chip, but mapped to the actual interface class.
function getInterfaceTypeLabel(type: string, t: TFunction) {
  switch ((type || "").toLowerCase()) {
    case "physical":
      return t("network.interfaceTypes.physical")
    case "bridge":
      return t("network.interfaceTypes.bridge")
    case "bond":
      return t("network.interfaceTypes.bond")
    case "vlan":
      return t("network.interfaceTypes.vlan")
    case "vm_lxc":
    case "virtual":
      return t("network.interfaceTypes.virtual")
    default:
      return type || t("common.unknown")
  }
}

function getInterfaceTypeChip(type: string, t: TFunction) {
  switch ((type || "").toLowerCase()) {
    case "physical":
      return { className: "bg-blue-500/10 text-blue-400 border-blue-500/20", label: getInterfaceTypeLabel(type, t) }
    case "bridge":
      return { className: "bg-green-500/10 text-green-400 border-green-500/20", label: getInterfaceTypeLabel(type, t) }
    case "bond":
      return { className: "bg-purple-500/10 text-purple-400 border-purple-500/20", label: getInterfaceTypeLabel(type, t) }
    case "vlan":
      return { className: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20", label: getInterfaceTypeLabel(type, t) }
    case "vm_lxc":
    case "virtual":
      return { className: "bg-orange-500/10 text-orange-400 border-orange-500/20", label: getInterfaceTypeLabel(type, t) }
    default:
      return { className: "bg-gray-500/10 text-gray-400 border-gray-500/20", label: type || t("common.unknown") }
  }
}

const formatInterfaceStatus = (status: string | undefined, t: TFunction): string => {
  const normalized = (status || "").toLowerCase()
  if (normalized === "up") return t("network.status.up")
  if (normalized === "down") return t("network.status.down")
  return status || t("common.unknown")
}

const formatDuplex = (duplex: string | undefined, t: TFunction): string => {
  const normalized = (duplex || "").toLowerCase()
  if (normalized === "full") return t("network.duplex.full")
  if (normalized === "half") return t("network.duplex.half")
  if (!duplex || normalized === "unknown") return t("common.unknown")
  return duplex
}

// Per-interface card matching the Storage page's "Physical Disks"
// pattern: 2-line header (identity / live state), horizontal divider,
// vertical key→value stat block, footer with serial + arrow CTA.
// Replaces the row-style block that was unchanged since 1.0.0.
function renderPhysicalInterfaceCardV2(
  iface: NetworkInterface,
  onOpen: (iface: NetworkInterface) => void,
  t: TFunction,
) {
  const Icon = getInterfaceIcon(iface)
  const chip = getInterfaceTypeChip(iface.type, t)
  const isUp = (iface.status || "").toLowerCase() === "up"
  const firstAddr = iface.addresses?.[0]?.ip || ""
  const extraAddrs = Math.max(0, (iface.addresses?.length || 0) - 1)
  const speedStr = formatSpeed(iface.speed, t("common.notAvailable"))
  // Hardware max in Mbps from ethtool. Show only when it's different
  // from the negotiated speed (avoids "1 Gbps (max 1 Gbps)" noise).
  const maxSpeedStr =
    iface.max_speed && iface.max_speed !== iface.speed
      ? formatSpeed(iface.max_speed, t("common.notAvailable"))
      : ""
  const bridgesUsing = iface.used_by_bridges || []
  const errIn = iface.errors_in ?? 0
  const errOut = iface.errors_out ?? 0
  const dropIn = iface.drops_in ?? 0
  const dropOut = iface.drops_out ?? 0
  const totalErrors = errIn + errOut
  const totalDrops = dropIn + dropOut

  return (
    <div
      key={iface.name}
      className="border border-white/10 rounded-lg p-5 cursor-pointer bg-card hover:bg-white/5 transition-colors flex flex-col"
      onClick={() => onOpen(iface)}
    >
      {/* Header L1: identity (icon + name + type) | status. */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <Icon className="h-5 w-5 text-muted-foreground shrink-0" />
          <h3 className="font-mono font-bold text-base break-all">{iface.name}</h3>
          <Badge variant="outline" className={chip.className}>{chip.label}</Badge>
        </div>
        <span
          className={`flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide shrink-0 ${
            isUp ? "text-green-500" : "text-red-400"
          }`}
        >
          <NetStatusDot tone={isUp ? "ok" : "fail"} />
          {formatInterfaceStatus(iface.status, t)}
        </span>
      </div>

      {/* Header L2: speed + max (when negotiated < hw) | duplex. */}
      <div className="flex items-center justify-between gap-3 mt-1 text-sm text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5" />
          {speedStr}
          {maxSpeedStr && (
            <span className="text-[11px] text-muted-foreground/70">
              · {t("network.labels.maxSpeed", { speed: maxSpeedStr })}
            </span>
          )}
        </span>
        <span>{formatDuplex(iface.duplex, t)}</span>
      </div>

      {/* Separator. */}
      <div className="border-t border-border/60 my-3" />

      {/* Stats: key uppercase left · value right. */}
      <div className="space-y-2 text-sm">
        {firstAddr && (
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground shrink-0">
              IP
            </span>
            <span className="font-medium text-right truncate font-mono text-xs">
              {firstAddr}{extraAddrs > 0 ? ` (+${extraAddrs})` : ""}
            </span>
          </div>
        )}
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">MTU</span>
          <span className="font-medium">{iface.mtu || "—"}</span>
        </div>
        {bridgesUsing.length > 0 && (
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground shrink-0">
              {t("network.interfaceTypes.bridge")}
            </span>
            <span className="font-medium text-right truncate font-mono text-xs text-cyan-400">
              {bridgesUsing.map((b) => `→ ${b}`).join("  ")}
            </span>
          </div>
        )}
        {/* Live RX/TX rate. Same wording the Network Traffic chart
            uses ("Received" / "Sent") and the same canonical colours
            (green for Received, blue for Sent). Falls back to "—"
            until the backend has a delta — first poll after start
            has no previous sample to compute against. */}
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
            <ArrowDown className="h-3 w-3 text-green-500" /> {t("network.labels.received")}
          </span>
          <span className="font-medium text-green-500 tabular-nums">
            {iface.rx_Bps !== undefined ? formatRate(iface.rx_Bps) : "—"}
          </span>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
            <ArrowUp className="h-3 w-3 text-blue-400" /> {t("network.labels.sent")}
          </span>
          <span className="font-medium text-blue-400 tabular-nums">
            {iface.tx_Bps !== undefined ? formatRate(iface.tx_Bps) : "—"}
          </span>
        </div>
        {(totalErrors > 0 || totalDrops > 0) && (
          <>
            {totalErrors > 0 && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("network.labels.errors")}</span>
                <span
                  className={`font-medium flex items-center gap-1.5 ${
                    netCounterTone(totalErrors) === "ok"
                      ? "text-green-500"
                      : netCounterTone(totalErrors) === "warn"
                        ? "text-yellow-500"
                        : "text-red-500"
                  }`}
                >
                  <NetStatusDot tone={netCounterTone(totalErrors)} />
                  {totalErrors.toLocaleString()}
                </span>
              </div>
            )}
            {totalDrops > 0 && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{t("network.labels.drops")}</span>
                <span
                  className={`font-medium flex items-center gap-1.5 ${
                    netCounterTone(totalDrops) === "ok"
                      ? "text-green-500"
                      : netCounterTone(totalDrops) === "warn"
                        ? "text-yellow-500"
                        : "text-red-500"
                  }`}
                >
                  <NetStatusDot tone={netCounterTone(totalDrops)} />
                  {totalDrops.toLocaleString()}
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer: MAC (left, mono) + arrow CTA (right). */}
      <div className="border-t border-border/60 mt-auto pt-3 flex items-center justify-between gap-3">
        {iface.mac_address ? (
          <span className="text-[11px] text-foreground font-mono truncate min-w-0">
            <span className="text-muted-foreground">MAC:</span> {iface.mac_address}
          </span>
        ) : (
          <span />
        )}
        <span
          className="text-blue-400 hover:text-blue-300 transition-colors text-base leading-none shrink-0"
          aria-label={t("network.actions.viewDetails")}
        >
          →
        </span>
      </div>
    </div>
  )
}


const getInterfaceTypeBadge = (type: string, t: TFunction) => {
  switch (type) {
    case "physical":
      return { color: "bg-blue-500/10 text-blue-500 border-blue-500/20", label: t("network.interfaceTypes.physical") }
    case "bridge":
      return { color: "bg-green-500/10 text-green-500 border-green-500/20", label: t("network.interfaceTypes.bridge") }
    case "bond":
      return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: t("network.interfaceTypes.bond") }
    case "vlan":
      return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: t("network.interfaceTypes.vlan") }
    case "vm_lxc":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: t("network.interfaceTypes.virtual") }
    case "virtual":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: t("network.interfaceTypes.virtual") }
    default:
      return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: t("common.unknown") }
  }
}

const getVMTypeBadge = (vmType: string | undefined, t: TFunction) => {
  if (vmType === "lxc") {
    return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: "LXC" }
  } else if (vmType === "vm") {
    return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: "VM" }
  }
  return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: t("common.unknown") }
}

// Format bytes/sec into the canonical network unit ladder.
// Matches the convention used by the Network Traffic chart so the
// rates on the per-interface cards and the chart read the same way.
const formatRate = (bps: number | undefined): string => {
  if (bps === undefined || bps === null || !Number.isFinite(bps)) return "—"
  if (bps < 1) return "0 B/s"
  const k = 1024
  const sizes = ["B/s", "KB/s", "MB/s", "GB/s"]
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bps) / Math.log(k)))
  const v = bps / Math.pow(k, i)
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(v >= 10 ? 1 : 2)} ${sizes[i]}`
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const formatStorage = (bytes: number): string => {
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB", "PB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  const value = bytes / Math.pow(k, i)

  // Use 1 decimal place for values >= 10, 2 decimal places for values < 10
  const decimals = value >= 10 ? 1 : 2
  return `${value.toFixed(decimals)} ${sizes[i]}`
}

const formatSpeed = (speed: number, unavailable = "N/A"): string => {
  if (speed === 0) return unavailable
  if (speed >= 1000) return `${(speed / 1000).toFixed(1)} Gbps`
  return `${speed} Mbps`
}

const fetcher = async (url: string): Promise<NetworkData> => {
  return fetchApi<NetworkData>(url)
}


export function NetworkMetrics() {
  const t = useT()
  const {
    data: networkData,
    error,
    isLoading,
  } = useSWR<NetworkData>("/api/network", fetcher, {
    // Was 15 s — too long for the Network Flow's pulse animation
    // which needs near-live rates. 3 s gives the dashboard responsive
    // updates without hammering the backend.
    refreshInterval: 3000,
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
  })

  const [selectedInterface, setSelectedInterface] = useState<NetworkInterface | null>(null)
  const [timeframe, setTimeframe] = useState<"hour" | "day" | "week" | "month" | "year">("day")
  const [modalTimeframe, setModalTimeframe] = useState<"hour" | "day" | "week" | "month" | "year">("day")
  const [networkTotals, setNetworkTotals] = useState<{ received: number; sent: number }>({ received: 0, sent: 0 })
  const [interfaceTotals, setInterfaceTotals] = useState<{ received: number; sent: number }>({ received: 0, sent: 0 })
  const [latencyModalOpen, setLatencyModalOpen] = useState(false)

  const [networkUnit, setNetworkUnit] = useState<"Bytes" | "Bits">(() => getNetworkUnit())
  
  // Latency history for sparkline (last hour)
  const { data: latencyData } = useSWR<{
    data: Array<{ timestamp: number; value: number }>
    stats: { min: number; max: number; avg: number; current: number }
    target: string
  }>("/api/network/latency/history?target=gateway&timeframe=hour", 
    (url: string) => fetchApi(url), 
    { refreshInterval: 60000, revalidateOnFocus: false }
  )

  useEffect(() => {
    setNetworkUnit(getNetworkUnit())

    const handleUnitChange = (e: CustomEvent) => {
      setNetworkUnit(e.detail === "Bits" ? "Bits" : "Bytes")
    }

    window.addEventListener("networkUnitChanged" as any, handleUnitChange)
    return () => window.removeEventListener("networkUnitChanged" as any, handleUnitChange)
  }, [])

  const { data: modalNetworkData } = useSWR<NetworkData>(selectedInterface ? "/api/network" : null, fetcher, {
    refreshInterval: 17000,
    revalidateOnFocus: false,
    revalidateOnReconnect: true,
  })

  const { data: interfaceHistoricalData } = useSWR<any>(`/api/node/metrics?timeframe=${timeframe}`, fetcher, {
    refreshInterval: 29000,
    revalidateOnFocus: false,
  })

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-2 border-muted"></div>
          <div className="absolute inset-0 h-12 w-12 rounded-full border-2 border-transparent border-t-primary animate-spin"></div>
        </div>
        <div className="text-sm font-medium text-foreground">{t("network.loading.title")}</div>
        <p className="text-xs text-muted-foreground">{t("network.loading.description")}</p>
      </div>
    )
  }

  if (error || !networkData) {
    return (
      <div className="space-y-6">
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-6">
            <div className="flex items-center gap-3 text-red-600">
              <AlertCircle className="h-6 w-6" />
              <div>
                <div className="font-semibold text-lg mb-1">{t("network.errors.serverUnavailableTitle")}</div>
                <div className="text-sm">
                  {error?.message ||
                    t("network.errors.serverUnavailableDescription")}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const trafficInFormatted = formatNetworkTraffic(
    networkTotals.received * 1024 ** 3,
    networkUnit,
    2
  )
  const trafficOutFormatted = formatNetworkTraffic(
    networkTotals.sent * 1024 ** 3,
    networkUnit,
    2
  )
  const packetsRecvK = networkData.traffic.packets_recv ? (networkData.traffic.packets_recv / 1000).toFixed(0) : "0"

  const totalErrors = (networkData.traffic.errin || 0) + (networkData.traffic.errout || 0)
  const packetLossIn = networkData.traffic.packet_loss_in || 0
  const packetLossOut = networkData.traffic.packet_loss_out || 0
  const avgPacketLoss = ((packetLossIn + packetLossOut) / 2).toFixed(2)

  // Determine health status
  let healthStatusKey = "network.status.healthy"
  let healthColor = "bg-green-500/10 text-green-500 border-green-500/20"

  if (Number.parseFloat(avgPacketLoss) > 5 || totalErrors > 1000) {
    healthStatusKey = "network.status.critical"
    healthColor = "bg-red-500/10 text-red-500 border-red-500/20"
  } else if (Number.parseFloat(avgPacketLoss) >= 1 || totalErrors >= 100) {
    healthStatusKey = "network.status.warning"
    healthColor = "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
  }

  const allInterfaces = [
    ...(networkData.physical_interfaces || []),
    ...(networkData.bond_interfaces || []),
    ...(networkData.bridge_interfaces || []),
    ...(networkData.vm_lxc_interfaces || []),
  ]

  const vmLxcInterfaces = (networkData.vm_lxc_interfaces || []).sort((a, b) => {
    const vmidA = a.vmid ?? Number.MAX_SAFE_INTEGER
    const vmidB = b.vmid ?? Number.MAX_SAFE_INTEGER
    return vmidA - vmidB
  })

  const topInterface =
    vmLxcInterfaces.length > 0
      ? vmLxcInterfaces.reduce((top, iface) => {
          const ifaceTraffic = (iface.bytes_recv || 0) + (iface.bytes_sent || 0)
          const topTraffic = (top.bytes_recv || 0) + (top.bytes_sent || 0)
          return ifaceTraffic > topTraffic ? iface : top
        }, vmLxcInterfaces[0])
      : { name: t("network.empty.noVmLxc"), type: "unknown", bytes_recv: 0, bytes_sent: 0, vm_name: t("common.notAvailable") }

  const topInterfaceTraffic = (topInterface.bytes_recv || 0) + (topInterface.bytes_sent || 0)

  const getTimeframeLabel = () => {
    switch (timeframe) {
      case "hour":
        return t("network.timeframes.hour")
      case "day":
        return t("network.timeframes.day")
      case "week":
        return t("network.timeframes.week")
      case "month":
        return t("network.timeframes.month")
      case "year":
        return t("network.timeframes.year")
      default:
        return t("network.timeframes.day")
    }
  }

  // Compact form for inline header use. The full "24 Hours" gets noisy
  // next to the title; "Past 24 h" keeps the same meaning in less space.
  const getTimeframeShortLabel = () => {
    switch (timeframe) {
      case "hour":
        return t("network.timeframes.short.hour")
      case "day":
        return t("network.timeframes.short.day")
      case "week":
        return t("network.timeframes.short.week")
      case "month":
        return t("network.timeframes.short.month")
      case "year":
        return t("network.timeframes.short.year")
      default:
        return t("network.timeframes.short.day")
    }
  }

  const getLastTimeframeLabel = (value: "hour" | "day" | "week" | "month" | "year") => {
    switch (value) {
      case "hour":
        return t("network.timeframes.last.hour")
      case "day":
        return t("network.timeframes.last.day")
      case "week":
        return t("network.timeframes.last.week")
      case "month":
        return t("network.timeframes.last.month")
      case "year":
        return t("network.timeframes.last.year")
      default:
        return t("network.timeframes.last.day")
    }
  }

  const hostname = networkData.hostname || t("common.notAvailable")
  const domain = networkData.domain || t("common.notAvailable")
  const dnsServers = networkData.dns_servers || []
  const primaryDNS = dnsServers[0] || t("common.notAvailable")
  const secondaryDNS = dnsServers[1] || t("common.notAvailable")

  return (
    <div className="space-y-6">
      {/* Network Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 xl:gap-6">
        {/* ── Network Traffic (preview restyle: Down/Up dual headline + stacked bar) ── */}
        {(() => {
          const downBytes = networkData.traffic.bytes_recv || 0
          const upBytes = networkData.traffic.bytes_sent || 0
          const totalBytes = downBytes + upBytes
          const downPct = totalBytes > 0 ? (downBytes / totalBytes) * 100 : 50
          const upPct = totalBytes > 0 ? (upBytes / totalBytes) * 100 : 50
          return (
            <Card className="bg-card border-border">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <CardTitle className="text-sm font-medium text-muted-foreground">{t("network.cards.traffic")}</CardTitle>
                  <span className="text-[10px] text-muted-foreground/70 font-normal">{getTimeframeShortLabel()}</span>
                </div>
                <Activity className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">
                      <span className="text-green-500">↓</span> {t("network.labels.down")}
                    </div>
                    <div className="text-xl lg:text-2xl font-bold leading-tight text-green-500">{trafficInFormatted}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">
                      <span className="text-blue-500">↑</span> {t("network.labels.up")}
                    </div>
                    <div className="text-xl lg:text-2xl font-bold leading-tight text-blue-500">{trafficOutFormatted}</div>
                  </div>
                </div>
                <div className="flex h-1.5 rounded-full overflow-hidden gap-[2px]">
                  <div style={{ width: `${downPct}%`, background: '#22c55e' }}></div>
                  <div style={{ width: `${upPct}%`, background: '#3b82f6' }}></div>
                </div>
                <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-green-500"></span>{t("network.labels.down")} {Math.round(downPct)}%</span>
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-500"></span>{t("network.labels.up")} {Math.round(upPct)}%</span>
                </div>
              </CardContent>
            </Card>
          )
        })()}

        {/* ── Active Interfaces (preview restyle v2: revertido al original con title uppercase) ── */}
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t("network.cards.activeInterfaces")}</CardTitle>
            <Network className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {(networkData.physical_active_count ?? 0) + (networkData.bridge_active_count ?? 0)}
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
                {t("network.interfaceTypes.physical")}: {networkData.physical_active_count ?? 0}/{networkData.physical_total_count ?? 0}
              </Badge>
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                {t("network.interfaceTypes.bridges")}: {networkData.bridge_active_count ?? 0}/{networkData.bridge_total_count ?? 0}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              {t("network.summary.totalInterfaces", {
                count: (networkData.physical_total_count ?? 0) + (networkData.bridge_total_count ?? 0),
              })}
            </p>
          </CardContent>
        </Card>

        {/* ── Network Status (preview restyle: packet-loss highlight + 2x2 grid) ── */}
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t("network.cards.status")}</CardTitle>
            <Badge variant="outline" className={`${healthColor}`}>{healthStatusKey === "network.status.healthy" ? "✓ " : ""}{t(healthStatusKey)}</Badge>
          </CardHeader>
          <CardContent>
            {(() => {
              const lossPct = Number.parseFloat(avgPacketLoss) || 0
              const lossColor =
                lossPct >= 5 ? 'text-red-500' :
                lossPct >= 1 ? 'text-orange-500' :
                lossPct > 0  ? 'text-yellow-500' :
                               'text-blue-500'
              return (
                <div className={`mb-3 text-xl lg:text-2xl font-bold ${lossColor} leading-none`}>
                  {avgPacketLoss}<span className="text-sm font-normal text-muted-foreground">% </span>
                  <span className="text-sm font-normal text-muted-foreground">{t("network.labels.packetLoss")}</span>
                </div>
              )
            })()}
            <div className="grid grid-cols-2 gap-x-3 gap-y-3 pt-3 border-t border-border/50 text-sm">
              <div className="min-w-0">
                <div className="text-muted-foreground">{t("network.labels.hostname")}:</div>
                <div className="font-medium font-mono truncate">{hostname}</div>
              </div>
              <div className="min-w-0">
                <div className="text-muted-foreground">DNS:</div>
                <div className="font-medium font-mono truncate">{primaryDNS}</div>
              </div>
              <div className="min-w-0">
                <div className="text-muted-foreground">{t("network.labels.errors")}:</div>
                <div className="font-medium font-mono">{totalErrors}</div>
              </div>
              <div className="min-w-0">
                <div className="text-muted-foreground">{t("network.labels.domain")}:</div>
                <div className="font-medium font-mono truncate">{domain}</div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Latency Card with Sparkline */}
        <Card
          className="bg-card border-border cursor-pointer hover:bg-white/5 transition-colors"
          onClick={() => setLatencyModalOpen(true)}
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{t("network.cards.latency")}</CardTitle>
            <div className="flex items-center gap-1 text-muted-foreground">
              <Timer className="h-4 w-4" />
              <ChevronRight className="h-4 w-4 opacity-60" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xl lg:text-2xl font-bold text-foreground">
                {latencyData?.stats?.current ?? 0} <span className="text-sm font-normal text-muted-foreground">ms</span>
              </div>
              <Badge 
                variant="outline" 
                className={
                  (latencyData?.stats?.current ?? 0) < 50 
                    ? "bg-green-500/10 text-green-500 border-green-500/20"
                    : (latencyData?.stats?.current ?? 0) < 100
                    ? "bg-green-500/10 text-green-500 border-green-500/20"
                    : (latencyData?.stats?.current ?? 0) < 200
                    ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                    : "bg-red-500/10 text-red-500 border-red-500/20"
                }
              >
                {(latencyData?.stats?.current ?? 0) < 50 ? t("network.latency.status.excellent") :
                 (latencyData?.stats?.current ?? 0) < 100 ? t("network.latency.status.good") :
                 (latencyData?.stats?.current ?? 0) < 200 ? t("network.latency.status.fair") : t("network.latency.status.poor")}
              </Badge>
            </div>
            {/* Sparkline */}
            {latencyData?.data && latencyData.data.length > 0 && (
              <div className="h-[40px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={latencyData.data.slice(-30)} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="latencySparkGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.4} />
                        <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke="#3b82f6"
                      strokeWidth={1.5}
                      fill="url(#latencySparkGradient)"
                      dot={false}
                      isAnimationActive={false}
                      baseValue="dataMin"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              {t("network.labels.avg")}: {latencyData?.stats?.avg ?? 0}ms | {t("network.labels.max")}: {latencyData?.stats?.max ?? 0}ms
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Timeframe Selector */}
      <div className="flex justify-end">
        <Select value={timeframe} onValueChange={(value: any) => setTimeframe(value)}>
          <SelectTrigger className="w-[180px] bg-card border-border">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="hour">{t("network.timeframes.hour")}</SelectItem>
            <SelectItem value="day">{t("network.timeframes.day")}</SelectItem>
            <SelectItem value="week">{t("network.timeframes.week")}</SelectItem>
            <SelectItem value="month">{t("network.timeframes.month")}</SelectItem>
            <SelectItem value="year">{t("network.timeframes.year")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Network Traffic Card with Chart */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-foreground flex items-center">
            <Activity className="h-5 w-5 mr-2" />
            {t("network.cards.traffic")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <NetworkTrafficChart timeframe={timeframe} onTotalsCalculated={setNetworkTotals} networkUnit={networkUnit} />
        </CardContent>
      </Card>

      {/* Network Flow — proof of concept. Lives next to Network Traffic
          while the design is validated on a real host. Once approved,
          this card replaces (or pairs with) the chart above. */}
      {(() => {
        const toMBps = (bps?: number) => (bps || 0) / (1024 * 1024)
        const allIfaces = [
          ...(networkData.physical_interfaces || []),
          ...(networkData.bond_interfaces || []),
          ...(networkData.bridge_interfaces || []),
          ...(networkData.vm_lxc_interfaces || []),
        ]
        const flowData: NetworkFlowData = {
          nics: (networkData.physical_interfaces || []).map((p) => ({
            id: p.name,
            link: formatSpeed(p.speed),
            rx: toMBps(p.rx_Bps),
            tx: toMBps(p.tx_Bps),
            // A slave whose MII status is down has no carrier even though
            // the interface itself stays administratively up — the bond
            // driver's view is the accurate one here.
            status:
              p.bond_link === "down"
                ? "down"
                : (p.status || "").toLowerCase() === "up"
                  ? "up"
                  : "down",
            bond: p.bond_master,
            role: p.bond_role,
          })),
          bonds: (networkData.bond_interfaces || []).map((b) => ({
            id: b.name,
            mode: b.bond_mode && b.bond_mode !== "unknown" ? b.bond_mode : undefined,
            rx: toMBps(b.rx_Bps),
            tx: toMBps(b.tx_Bps),
            status: (b.status || "").toLowerCase() === "up" ? "up" : "down",
          })),
          bridges: (networkData.bridge_interfaces || []).map((b) => ({
            id: b.name,
            parent: b.bridge_physical_interface,
          })),
          consumers: [
            (() => {
              // PROXMOX node = sum of every running guest's rate.
              // This stays consistent with each bridge's own label
              // (which sums the same guest rates), and with the
              // total trunk flow — no discrepancy between the host's
              // displayed rate and the sum of its bridges.
              const runningGuests = (networkData.vm_lxc_interfaces || []).filter(
                (v) => v.vm_status !== "stopped"
              )
              return {
                id: "host",
                label: "host",
                kind: "host" as const,
                bridge: (networkData.bridge_interfaces?.[0]?.name) || "",
                rx: runningGuests.reduce((a, v) => a + toMBps(v.rx_Bps), 0),
                tx: runningGuests.reduce((a, v) => a + toMBps(v.tx_Bps), 0),
              }
            })(),
            ...(networkData.vm_lxc_interfaces || []).map((v) => {
              // Authoritative bridge from the kernel (read by the
              // backend from /sys/class/net/<iface>/master). Fallback
              // to bridge_members scan, then first bridge as last
              // resort so we never silently drop a guest.
              const ownerName =
                (v as any).bridge_owner ||
                (networkData.bridge_interfaces || []).find((b) =>
                  (b.bridge_members || []).includes(v.name)
                )?.name ||
                (networkData.bridge_interfaces?.[0]?.name || "")
              return {
                id: v.name,
                label: v.vm_name || v.name,
                kind: (v.vm_type === "vm" ? "vm" : "lxc") as "vm" | "lxc",
                bridge: ownerName,
                rx: toMBps(v.rx_Bps),
                tx: toMBps(v.tx_Bps),
                offline: v.vm_status === "stopped",
              }
            }),
          ],
        }
        return (
          <NetworkFlow
            data={flowData}
            onNodeClick={(name) => {
              // Map the clicked node back to a NetworkInterface and
              // open the same details modal the cards below use. The
              // virtual "host" id never matches a real interface, so
              // it's a no-op — tapping the PROXMOX circle does nothing
              // (there's no host-level modal in this view).
              if (name === "host") return
              const match = allIfaces.find((iface) => iface.name === name)
              if (match) setSelectedInterface(match)
            }}
          />
        )
      })()}

      {/* Physical Interfaces section */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Router className="h-5 w-5 mr-2" />
            {t("network.sections.physicalInterfaces")}
            <Badge variant="outline" className="ml-3 bg-blue-500/10 text-blue-500 border-blue-500/20">
              {t("network.summary.activeCount", {
                active: networkData.physical_active_count ?? 0,
                total: networkData.physical_total_count ?? 0,
              })}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {/* Same responsive grid as the Storage page: 3 cols desktop,
              2 cols tablet, 1 col mobile. Cards self-size so a row of
              long interface names won't push others off-screen. */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {networkData.physical_interfaces.map((iface) =>
              renderPhysicalInterfaceCardV2(iface, setSelectedInterface, t),
            )}
          </div>
        </CardContent>
      </Card>

      {networkData.bridge_interfaces && networkData.bridge_interfaces.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Network className="h-5 w-5 mr-2" />
              {t("network.sections.bridgeInterfaces")}
              <Badge variant="outline" className="ml-3 bg-green-500/10 text-green-500 border-green-500/20">
                {t("network.summary.activeCount", {
                  active: networkData.bridge_active_count ?? 0,
                  total: networkData.bridge_total_count ?? 0,
                })}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {networkData.bridge_interfaces.map((interface_, index) => {
                const typeBadge = getInterfaceTypeBadge(interface_.type, t)

                return (
                  <div
                    key={index}
                    className="flex flex-col gap-3 p-4 rounded-lg border border-white/10 bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer"
                    onClick={() => setSelectedInterface(interface_)}
                  >
                    {/* First row: Icon, Name, Type Badge, Physical Interface (responsive), Status */}
                    <div className="flex items-center gap-3 flex-wrap">
                      <Network className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                      <div className="flex items-center gap-2 min-w-0 flex-1 flex-wrap">
                        <div className="font-medium text-foreground">{interface_.name}</div>
                        <Badge variant="outline" className={typeBadge.color}>
                          {typeBadge.label}
                        </Badge>
                        {interface_.bridge_physical_interface && (
                          <div className="text-sm text-blue-500 font-medium flex items-center gap-1 flex-wrap break-all">
                            → {interface_.bridge_physical_interface}
                            {interface_.bridge_bond_slaves && interface_.bridge_bond_slaves.length > 0 && (
                              <span className="text-muted-foreground text-xs break-all">
                                ({interface_.bridge_bond_slaves.join(", ")})
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          interface_.status === "up"
                            ? "bg-green-500/10 text-green-500 border-green-500/20"
                            : "bg-red-500/10 text-red-500 border-red-500/20"
                        }
                      >
                        {formatInterfaceStatus(interface_.status, t)}
                      </Badge>
                    </div>

                    {/* Second row: Details - Responsive layout */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-muted-foreground text-xs">{t("network.labels.ipAddress")}</div>
                        <div className="font-medium text-foreground font-mono text-sm truncate">
                          {interface_.addresses.length > 0 ? interface_.addresses[0].ip : t("common.notAvailable")}
                        </div>
                      </div>

                      <div>
                        <div className="text-muted-foreground text-xs">{t("network.labels.speed")}</div>
                        <div className="font-medium text-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" />
                          {formatSpeed(interface_.speed, t("common.notAvailable"))}
                        </div>
                      </div>

                      <div>
                        <div className="text-muted-foreground text-xs">{t("network.labels.duplex")}</div>
                        <div className="font-medium text-foreground text-xs">{formatDuplex(interface_.duplex, t)}</div>
                      </div>

                      <div>
                        <div className="text-muted-foreground text-xs">MTU</div>
                        <div className="font-medium text-foreground text-xs">{interface_.mtu}</div>
                      </div>

                      {interface_.mac_address && (
                        <div className="col-span-2 md:col-span-4">
                          <div className="text-muted-foreground text-xs">MAC</div>
                          <div className="font-medium text-foreground font-mono text-xs truncate">
                            {interface_.mac_address}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* VM & LXC Network Interfaces section */}
      {networkData.vm_lxc_interfaces && networkData.vm_lxc_interfaces.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Network className="h-5 w-5 mr-2" />
              {t("network.sections.vmLxcInterfaces")}
              <Badge variant="outline" className="ml-3 bg-orange-500/10 text-orange-500 border-orange-500/20">
                {t("network.summary.activeCount", {
                  active: networkData.vm_lxc_active_count ?? 0,
                  total: networkData.vm_lxc_total_count ?? 0,
                })}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {vmLxcInterfaces.map((interface_, index) => {
                const vmTypeBadge = getVMTypeBadge(interface_.vm_type, t)

                return (
                  <div
                    key={index}
                    className="flex flex-col gap-3 p-4 rounded-lg border border-white/10 bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer"
                    onClick={() => setSelectedInterface(interface_)}
                  >
                    {/* First row: Icon, Name, VM/LXC Badge, VM Name, Status */}
                    <div className="flex items-center gap-3 flex-wrap">
                      <EthernetPort className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                      <div className="flex items-center gap-2 min-w-0 flex-1 flex-wrap">
                        <div className="font-medium text-foreground">{interface_.name}</div>
                        <Badge variant="outline" className={vmTypeBadge.color}>
                          {vmTypeBadge.label}
                        </Badge>
                        {interface_.vm_name && (
                          <div className="text-sm text-orange-500 truncate">→ {interface_.vm_name}</div>
                        )}
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          interface_.status === "up"
                            ? "bg-green-500/10 text-green-500 border-green-500/20"
                            : "bg-red-500/10 text-red-500 border-red-500/20"
                        }
                      >
                        {formatInterfaceStatus(interface_.status, t)}
                      </Badge>
                    </div>

                    {/* Second row: Details - Responsive layout */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-sm text-muted-foreground">VMID</div>
                          <div className="font-medium">{interface_.vmid ?? t("common.notAvailable")}</div>
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground">{t("network.labels.speed")}</div>
                        <div className="font-medium text-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" />
                          {formatSpeed(interface_.speed, t("common.notAvailable"))}
                        </div>
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground">{t("network.labels.duplex")}</div>
                        <div className="font-medium text-foreground text-xs">{formatDuplex(interface_.duplex, t)}</div>
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground">MTU</div>
                        <div className="font-medium text-foreground text-xs">{interface_.mtu}</div>
                      </div>

                      {interface_.mac_address && (
                        <div className="col-span-2 md:col-span-4">
                          <div className="text-sm text-muted-foreground">MAC</div>
                          <div className="font-medium text-foreground font-mono text-xs truncate">
                            {interface_.mac_address}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Interface Details Modal */}
      <Dialog open={!!selectedInterface} onOpenChange={() => setSelectedInterface(null)}>
        <DialogContent className="max-w-4xl w-[calc(100vw-1rem)] sm:w-[95vw] max-h-[calc(100dvh-2rem)] sm:max-h-[90vh] overflow-y-auto overflow-x-hidden p-4 sm:p-6">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Router className="h-5 w-5" />
              {selectedInterface?.name} - {t("network.interfaceDetails.title")}
            </DialogTitle>
            <DialogDescription>
              {t("network.interfaceDetails.description")}
            </DialogDescription>
            {selectedInterface?.status.toLowerCase() === "up" && selectedInterface?.vm_type !== "vm" && (
              <div className="flex justify-end pt-2">
                <Select value={modalTimeframe} onValueChange={(value: any) => setModalTimeframe(value)}>
                  <SelectTrigger className="w-[140px] bg-card border-border">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hour">{t("network.timeframes.hour")}</SelectItem>
                    <SelectItem value="day">{t("network.timeframes.day")}</SelectItem>
                    <SelectItem value="week">{t("network.timeframes.week")}</SelectItem>
                    <SelectItem value="month">{t("network.timeframes.month")}</SelectItem>
                    <SelectItem value="year">{t("network.timeframes.year")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </DialogHeader>

          {selectedInterface && (
            <div className="space-y-6">
              {(() => {
                // Find the current interface data from modalNetworkData if available
                const currentInterfaceData = modalNetworkData
                  ? [
                      ...(modalNetworkData.physical_interfaces || []),
                      ...(modalNetworkData.bond_interfaces || []),
                      ...(modalNetworkData.bridge_interfaces || []),
                      ...(modalNetworkData.vm_lxc_interfaces || []),
                    ].find((iface) => iface.name === selectedInterface.name)
                  : selectedInterface

                const displayInterface = currentInterfaceData || selectedInterface

                return (
                  <>
                    {/* Basic Information */}
                    <div>
                      <h3 className="text-sm font-semibold text-muted-foreground mb-3">{t("network.interfaceDetails.basicInformation")}</h3>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="text-sm text-muted-foreground">{t("network.labels.interfaceName")}</div>
                          <div className="font-medium">{displayInterface.name}</div>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">{t("network.labels.type")}</div>
                          <Badge variant="outline" className={getInterfaceTypeBadge(displayInterface.type, t).color}>
                            {getInterfaceTypeBadge(displayInterface.type, t).label}
                          </Badge>
                        </div>
                        {displayInterface.type === "bridge" && displayInterface.bridge_physical_interface && (
                          <div className="col-span-2">
                            <div className="text-sm text-muted-foreground">{t("network.labels.physicalInterface")}</div>
                            <div className="font-medium text-blue-500 text-lg break-all">
                              {displayInterface.bridge_physical_interface}
                            </div>
                            {/* Slaves come from the bridge's own payload
                                (bridge_bond_slaves); the bond master is not
                                part of physical_interfaces, so looking it up
                                there never matched. */}
                            {displayInterface.bridge_bond_slaves && displayInterface.bridge_bond_slaves.length > 0 && (
                              <div className="mt-2">
                                <div className="text-sm text-muted-foreground mb-2">{t("network.labels.bondMembers")}</div>
                                <div className="flex flex-wrap gap-2">
                                  {displayInterface.bridge_bond_slaves.map((slave, idx) => (
                                    <Badge
                                      key={idx}
                                      variant="outline"
                                      className="bg-purple-500/10 text-purple-500 border-purple-500/20"
                                    >
                                      {slave}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                        {displayInterface.type === "vm_lxc" && displayInterface.vm_name && (
                          <div className="col-span-2">
                            <div className="text-sm text-muted-foreground">{t("network.labels.vmLxcName")}</div>
                            <div className="font-medium text-orange-500 text-lg flex items-center gap-2">
                              {displayInterface.vm_name}
                              {displayInterface.vm_type && (
                                <Badge variant="outline" className={getVMTypeBadge(displayInterface.vm_type, t).color}>
                                  {getVMTypeBadge(displayInterface.vm_type, t).label}
                                </Badge>
                              )}
                            </div>
                          </div>
                        )}
                        <div>
                          <div className="text-sm text-muted-foreground">{t("network.labels.status")}</div>
                          <Badge
                            variant="outline"
                            className={
                              displayInterface.status === "up"
                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                : "bg-red-500/10 text-red-500 border-red-500/20"
                            }
                          >
                            {formatInterfaceStatus(displayInterface.status, t)}
                          </Badge>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">{t("network.labels.speed")}</div>
                          <div className="font-medium">{formatSpeed(displayInterface.speed, t("common.notAvailable"))}</div>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">{t("network.labels.duplex")}</div>
                          <div className="font-medium">{formatDuplex(displayInterface.duplex, t)}</div>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">MTU</div>
                          <div className="font-medium">{displayInterface.mtu}</div>
                        </div>
                        {displayInterface.mac_address && (
                          <div className="col-span-2">
                            <div className="text-sm text-muted-foreground">{t("network.labels.macAddress")}</div>
                            <div className="font-medium font-mono">{displayInterface.mac_address}</div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* IP Addresses */}
                    {displayInterface.addresses.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3">{t("network.interfaceDetails.ipAddresses")}</h3>
                        <div className="space-y-2">
                          {displayInterface.addresses.map((addr, idx) => (
                            <div key={idx} className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                              <div>
                                <div className="font-medium font-mono">{addr.ip}</div>
                                <div className="text-sm text-muted-foreground">{t("network.labels.netmask")}: {addr.netmask}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Network Traffic Statistics - Only show if interface is UP and NOT a VM interface */}
                    {displayInterface.status.toLowerCase() === "up" && displayInterface.vm_type !== "vm" ? (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-4">
                          {t("network.interfaceDetails.trafficStatistics", {
                            timeframe: getLastTimeframeLabel(modalTimeframe),
                          })}
                        </h3>
                        <div className="space-y-4">
                          <div className="grid grid-cols-2 gap-4">
                            <div>
                              <div className="text-sm text-muted-foreground">
                                {networkUnit === "Bits" ? t("network.labels.bitsReceived") : t("network.labels.bytesReceived")}
                              </div>
                              <div className="font-medium text-green-500 text-lg">
                                {formatNetworkTraffic(
                                  interfaceTotals.received * 1024 ** 3,
                                  networkUnit,
                                  2
                                )}
                              </div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">
                                {networkUnit === "Bits" ? t("network.labels.bitsSent") : t("network.labels.bytesSent")}
                              </div>
                              <div className="font-medium text-blue-500 text-lg">
                                {formatNetworkTraffic(
                                  interfaceTotals.sent * 1024 ** 3,
                                  networkUnit,
                                  2
                                )}
                              </div>
                            </div>
                          </div>

                          <div className="bg-muted/30 rounded-lg p-4">
                            <NetworkTrafficChart
                              timeframe={modalTimeframe}
                              interfaceName={displayInterface.name}
                              onTotalsCalculated={setInterfaceTotals}
                              refreshInterval={60000}
                              networkUnit={networkUnit}
                            />
                          </div>

                          <div className="grid grid-cols-2 gap-4 pt-4 border-t border-border">
                            <div>
                              <div className="text-sm text-muted-foreground">{t("network.labels.packetsReceived")}</div>
                              <div className="font-medium">
                                {displayInterface.packets_recv?.toLocaleString() || t("common.notAvailable")}
                              </div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">{t("network.labels.packetsSent")}</div>
                              <div className="font-medium">
                                {displayInterface.packets_sent?.toLocaleString() || t("common.notAvailable")}
                              </div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">{t("network.labels.errorsIn")}</div>
                              <div className="font-medium text-red-500">{displayInterface.errors_in || 0}</div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">{t("network.labels.errorsOut")}</div>
                              <div className="font-medium text-red-500">{displayInterface.errors_out || 0}</div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">{t("network.labels.dropsIn")}</div>
                              <div className="font-medium text-yellow-500">{displayInterface.drops_in || 0}</div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">{t("network.labels.dropsOut")}</div>
                              <div className="font-medium text-yellow-500">{displayInterface.drops_out || 0}</div>
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : displayInterface.status.toLowerCase() === "up" && displayInterface.vm_type === "vm" ? (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-4">{t("network.interfaceDetails.trafficSinceBoot")}</h3>
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <div className="text-sm text-muted-foreground">
                              {networkUnit === "Bits" ? t("network.labels.bitsReceived") : t("network.labels.bytesReceived")}
                            </div>
                            <div className="font-medium text-green-500 text-lg">
                              {formatNetworkTraffic(displayInterface.bytes_recv || 0, networkUnit)}
                            </div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">
                              {networkUnit === "Bits" ? t("network.labels.bitsSent") : t("network.labels.bytesSent")}
                            </div>
                            <div className="font-medium text-blue-500 text-lg">
                              {formatNetworkTraffic(displayInterface.bytes_sent || 0, networkUnit)}
                            </div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.packetsReceived")}</div>
                            <div className="font-medium">
                              {displayInterface.packets_recv?.toLocaleString() || t("common.notAvailable")}
                            </div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.packetsSent")}</div>
                            <div className="font-medium">
                              {displayInterface.packets_sent?.toLocaleString() || t("common.notAvailable")}
                            </div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.errorsIn")}</div>
                            <div className="font-medium text-red-500">{displayInterface.errors_in || 0}</div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.errorsOut")}</div>
                            <div className="font-medium text-red-500">{displayInterface.errors_out || 0}</div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.dropsIn")}</div>
                            <div className="font-medium text-yellow-500">{displayInterface.drops_in || 0}</div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.dropsOut")}</div>
                            <div className="font-medium text-yellow-500">{displayInterface.drops_out || 0}</div>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="bg-muted/30 rounded-lg p-6 text-center">
                        <AlertCircle className="h-12 w-12 text-muted-foreground mx-auto mb-3" />
                        <h3 className="text-lg font-semibold text-foreground mb-2">{t("network.interfaceDetails.inactiveTitle")}</h3>
                        <p className="text-sm text-muted-foreground">
                          {t("network.interfaceDetails.inactiveDescription")}
                        </p>
                      </div>
                    )}

                    {/* Bond Information */}
                    {displayInterface.type === "bond" && displayInterface.bond_slaves && (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3">{t("network.interfaceDetails.bondConfiguration")}</h3>
                        <div className="space-y-3">
                          <div>
                            <div className="text-sm text-muted-foreground">{t("network.labels.bondingMode")}</div>
                            <div className="font-medium">
                              {displayInterface.bond_mode || t("common.unknown")}
                              {displayInterface.bond_mode_detail &&
                                displayInterface.bond_mode_detail !== displayInterface.bond_mode && (
                                  <span className="text-muted-foreground font-normal">
                                    {" "}
                                    ({displayInterface.bond_mode_detail})
                                  </span>
                                )}
                            </div>
                          </div>
                          {displayInterface.bond_active_slave && (
                            <div>
                              <div className="text-sm text-muted-foreground">
                                {displayInterface.bond_supports_failover ? t("network.labels.activeSlave") : t("network.labels.primarySlave")}
                              </div>
                              <div className="font-medium">{displayInterface.bond_active_slave}</div>
                            </div>
                          )}
                          <div>
                            <div className="text-sm text-muted-foreground mb-2">{t("network.labels.slaveInterfaces")}</div>
                            <div className="flex flex-wrap gap-2">
                              {displayInterface.bond_slaves.map((slave, idx) => {
                                // Only active-backup has a real standby. In every
                                // other mode all slaves transmit, so we just show
                                // the link state.
                                const link = displayInterface.bond_slave_status?.[slave]
                                const isDown = link === "down"
                                const role = isDown
                                  ? "down"
                                  : displayInterface.bond_supports_failover
                                    ? slave === displayInterface.bond_active_slave
                                      ? "active"
                                      : "standby"
                                    : null
                                const tone = isDown
                                  ? "bg-red-500/10 text-red-500 border-red-500/20"
                                  : role === "standby"
                                    ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                    : "bg-purple-500/10 text-purple-500 border-purple-500/20"
                                return (
                                  <Badge key={idx} variant="outline" className={tone}>
                                    {slave}
                                    {role && <span className="ml-1 opacity-70">· {t(`network.roles.${role}`)}</span>}
                                  </Badge>
                                )
                              })}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Bridge Information */}
                    {displayInterface.type === "bridge" && displayInterface.bridge_members && (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3">{t("network.interfaceDetails.bridgeConfiguration")}</h3>
                        <div>
                          <div className="text-sm text-muted-foreground mb-2">{t("network.labels.virtualMemberInterfaces")}</div>
                          <div className="flex flex-wrap gap-2">
                            {displayInterface.bridge_members.length > 0 ? (
                              displayInterface.bridge_members
                                .filter(
                                  (member) =>
                                    !member.startsWith("enp") &&
                                    !member.startsWith("eth") &&
                                    !member.startsWith("eno") &&
                                    !member.startsWith("ens") &&
                                    !member.startsWith("wlan") &&
                                    !member.startsWith("wlp"),
                                )
                                .map((member, idx) => (
                                  <Badge
                                    key={idx}
                                    variant="outline"
                                    className="bg-green-500/10 text-green-500 border-green-500/20"
                                  >
                                    {member}
                                  </Badge>
                                ))
                            ) : (
                              <div className="text-sm text-muted-foreground">{t("network.empty.noVirtualMembers")}</div>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Latency Detail Modal */}
      <LatencyDetailModal
        open={latencyModalOpen}
        onOpenChange={setLatencyModalOpen}
      />
    </div>
  )
}
