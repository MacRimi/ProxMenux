"use client"

import type React from "react"

import { useState, useMemo, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog"
import { Server, Play, Square, Cpu, MemoryStick, HardDrive, Network, Power, RotateCcw, StopCircle, Container, ChevronDown, ChevronUp, ChevronRight, Terminal, Archive, Plus, Loader2, Clock, Database, Shield, Bell, FileText, Settings2, Activity, Package, RefreshCw, EthernetPort, ArrowUpCircle, Info, CheckCircle2, EyeOff, Eye, Pencil, Trash2, Check, AlertTriangle } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Checkbox } from "./ui/checkbox"
import { Switch } from "./ui/switch"
import { Textarea } from "./ui/textarea"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import useSWR from "swr"
import { MetricsView } from "./metrics-dialog"
import { LxcTerminalModal } from "./lxc-terminal-modal"
import { ScriptTerminalModal } from "./script-terminal-modal"
import { LxcAppPanel } from "./lxc-app-panel"
import { formatStorage } from "../lib/utils"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"
import { fetchApi } from "../lib/api-config"
import DOMPurify from "dompurify"
import { marked } from "marked"
import { useT } from "@/lib/i18n/provider"

// Sent by /api/vms only for LXC rows, only when the user has enabled
// `lxc_updates_available` notifications. The Monitor populates this
// from managed_installs registry → frontend uses it to render the
// inline update badge + the modal's "Pending updates" section.
interface LxcPackageUpdate {
  name: string
  current: string
  latest: string
  security: boolean
}
interface LxcUpdateCheck {
  available: boolean
  count: number
  security_count: number
  last_check: string | null
  latest: string | null
  error: string | null
  packages: LxcPackageUpdate[]
  // Added Phase 2a/b — surfaced by managed_installs when the CT
  // originates from an OCI image (apt/apk detection is suppressed
  // for those) or when the community-scripts convention
  // /usr/bin/update is present in the CT.
  is_oci_lxc?: boolean
  app_updater_present?: boolean
  // ProxMenux-managed OCI app id (e.g. "secure-gateway") — when set,
  // this CT is driven by the OCI dashboard's own updater and the
  // Updates modal redirects there instead of running our apt flow.
  managed_oci_app?: string | null
  // Community-scripts identity + updateable-known flag. Backed by the
  // ProxMenux helpers_cache (46 apps flagged updateable:false at
  // last count). The modal renders three shapes:
  //   • helper_updateable_known=true + app_updater_present=true → Apply button
  //   • helper_updateable_known=true + app_updater_present=false → "not updateable" note
  //   • helper_updateable_known=false → neutral hint (unknown/unlisted app)
  helper_slug?: string | null
  helper_app_name?: string | null
  helper_updateable_known?: boolean
  os_family?: string | null
}

// Summary attached to LXC rows in /api/vms when the user has
// registered an application watch for the CT. Populates the header
// badge + the Updates modal "App upstream" row.
interface LxcAppPort {
  port: number
  description?: string
  scheme?: "http" | "https"
  web_path?: string
}
interface LxcAppWatch {
  id: string
  name: string | null
  installed_via?: string | null
  ports?: LxcAppPort[]
  health_path?: string | null
  installed_version: string | null
  latest_version: string | null
  update_available: boolean | null
  error: string | null
  checked_at: string | null
  has_repo?: boolean
  // Set for the synthetic entry that represents a ProxMenux-managed
  // OCI app (Secure Gateway). The frontend renders it read-only +
  // wires the Update action to /api/oci/installed/<id>/update.
  managed_oci_app_id?: string | null
  packages?: Array<{ name: string; current?: string; latest?: string }>
  // Updates tab: freeform bash the user wired up as the app's own
  // update method. When set, the Updates tab renders an "Apply {app}"
  // button that runs `pct exec vmid -- sh -c "$update_command"`.
  update_command?: string
  // Updates tab: per-app dismiss for the "no update method defined"
  // notice. Only hides the notice — the App tab still shows purple ⬆
  // when an update is available upstream.
  hide_no_updater_notice?: boolean
  // Community-scripts slug set by the App tab Register flow. Lets the
  // Updates tab helper-scripts section find its matching registered
  // app to pull installed/upstream version data from.
  helper_slug?: string
}

interface VMData {
  vmid: number
  name: string
  status: string
  type: string
  cpu: number
  maxcpu?: number
  mem: number
  maxmem: number
  disk: number
  maxdisk: number
  uptime: number
  netin?: number
  netout?: number
  diskread?: number
  diskwrite?: number
  ip?: string
  update_check?: LxcUpdateCheck
  // List of registered apps (0..N). Managed entries (Secure Gateway)
  // always come first when present.
  app_watches?: LxcAppWatch[]
}

interface VMConfig {
  cores?: number
  memory?: number
  swap?: number
  rootfs?: string
  net0?: string
  net1?: string
  net2?: string
  nameserver?: string
  searchdomain?: string
  onboot?: number
  unprivileged?: number
  features?: string
  ostype?: string
  arch?: string
  hostname?: string
  // VM specific
  sockets?: number
  scsi0?: string
  ide0?: string
  boot?: string
  description?: string // Added for notes
  // Hardware specific
  numa?: boolean
  bios?: string
  machine?: string
  vga?: string
  agent?: boolean
  tablet?: boolean
  localtime?: boolean
  // Storage specific
  scsihw?: string
  efidisk0?: string
  tpmstate0?: string
  // Mount points for LXC
  mp0?: string
  mp1?: string
  mp2?: string
  mp3?: string
  mp4?: string
  mp5?: string
  // PCI Passthrough
  hostpci0?: string
  hostpci1?: string
  hostpci2?: string
  hostpci3?: string
  hostpci4?: string
  hostpci5?: string
  // USB Devices
  usb0?: string
  usb1?: string
  usb2?: string
  // Serial Devices
  serial0?: string
  serial1?: string
  // Advanced
  vmgenid?: string
  smbios1?: string
  meta?: string
  // CPU
  cpu?: string
  [key: string]: any
}

interface VMDetails extends VMData {
  config?: VMConfig
  node?: string
  vm_type?: string
  os_info?: {
    id?: string
    version_id?: string
    name?: string
    pretty_name?: string
  }
  hardware_info?: {
    privileged?: boolean | null
    gpu_passthrough?: string[]
    devices?: string[]
  }
  lxc_ip_info?: {
    all_ips: string[]
    real_ips: string[]
    docker_ips: string[]
    primary_ip: string
  }
}

interface BackupStorage {
  storage: string
  type: string
  content: string
  total: number
  used: number
  avail: number
  total_human?: string
  used_human?: string
  avail_human?: string
}

interface VMBackup {
  volid: string
  storage: string
  type: string
  size: number
  size_human: string
  timestamp: number
  date: string
  notes?: string
}

// Sprint 13.29: shape returned by /api/lxc/<vmid>/mount-points. Lives
// next to VMBackup since both are LXC-modal data structures.
interface LxcMountPoint {
  mp_index: string  // "mp0", "mp1", "" for ad-hoc
  source: string
  target: string
  type: "pve_volume" | "pve_storage_bind" | "host_bind" | "ad_hoc"
  origin_storage: string
  origin_storage_type: string
  origin_label: string
  config_options: Record<string, string>
  config_flags: string[]
  total_bytes: number | null
  used_bytes: number | null
  available_bytes: number | null
  runtime_mounted?: boolean | null
  runtime_source?: string
  runtime_fstype?: string
  runtime_options?: string
  runtime_readonly?: boolean
  runtime_reachable?: boolean
  runtime_error?: string | null
  // Sprint 14.x: host-side bind source state. Detects the case where the
  // CT still reports a bind as mounted even though the host already
  // umounted the source (Ignacio Seijo 11/05). Null = N/A (PVE volume,
  // not a host path).
  host_source_exists?: boolean | null
  host_source_is_mountpoint?: boolean | null
}

const fetcher = async (url: string) => {
  return fetchApi(url)
}

const formatBytes = (bytes: number | undefined, isNetwork: boolean = false): string => {
  if (!bytes || bytes === 0) return isNetwork ? "0 B/s" : "0 B"
  
  if (isNetwork) {
    const networkUnit = getNetworkUnit()
    return formatNetworkTraffic(bytes, networkUnit, 2)
  }
  
  // For non-network (disk), use standard bytes
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const formatUptime = (seconds: number, t: (key: string, params?: Record<string, string | number>) => string) => {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return t("vmLxc.duration.dhm", { days, hours, minutes })
}

const extractIPFromConfig = (config?: VMConfig, lxcIPInfo?: VMDetails["lxc_ip_info"]): string => {
  // Use primary IP from lxc-info if available
  if (lxcIPInfo?.primary_ip) {
    return lxcIPInfo.primary_ip
  }

  if (!config) return "DHCP"

  // Check net0, net1, net2, etc.
  for (let i = 0; i < 10; i++) {
    const netKey = `net${i}`
    const netConfig = config[netKey]

    if (netConfig && typeof netConfig === "string") {
      // Look for ip=x.x.x.x/xx or ip=x.x.x.x pattern
      const ipMatch = netConfig.match(/ip=([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/)
      if (ipMatch) {
        return ipMatch[1] // Return just the IP without CIDR
      }

      // Check if it's explicitly DHCP
      if (netConfig.includes("ip=dhcp")) {
        return "DHCP"
      }
    }
  }

  return "DHCP"
}

// const formatStorage = (sizeInGB: number): string => {
//   if (sizeInGB < 1) {
//     // Less than 1 GB, show in MB
//     return `${(sizeInGB * 1024).toFixed(1)} MB`
//   } else if (sizeInGB < 1024) {
//     // Less than 1024 GB, show in GB
//     return `${sizeInGB.toFixed(1)} GB`
//   } else {
//     // 1024 GB or more, show in TB
//     return `${(sizeInGB / 1024).toFixed(1)} TB`
//   }
// }

const getUsageColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-foreground"
}

// Generate consistent color for storage names
const storageColors = [
  { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
  { bg: "bg-emerald-500/20", text: "text-emerald-400", border: "border-emerald-500/30" },
  { bg: "bg-purple-500/20", text: "text-purple-400", border: "border-purple-500/30" },
  { bg: "bg-amber-500/20", text: "text-amber-400", border: "border-amber-500/30" },
  { bg: "bg-pink-500/20", text: "text-pink-400", border: "border-pink-500/30" },
  { bg: "bg-cyan-500/20", text: "text-cyan-400", border: "border-cyan-500/30" },
  { bg: "bg-rose-500/20", text: "text-rose-400", border: "border-rose-500/30" },
  { bg: "bg-indigo-500/20", text: "text-indigo-400", border: "border-indigo-500/30" },
]

const getStorageColor = (storageName: string) => {
  // Generate a consistent hash from storage name
  let hash = 0
  for (let i = 0; i < storageName.length; i++) {
    hash = storageName.charCodeAt(i) + ((hash << 5) - hash)
  }
  const index = Math.abs(hash) % storageColors.length
  return storageColors[index]
}

const getIconColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-green-500"
}

const getProgressColor = (percent: number): string => {
  if (percent >= 95) return "[&>div]:bg-red-500"
  if (percent >= 86) return "[&>div]:bg-orange-500"
  if (percent >= 71) return "[&>div]:bg-yellow-500"
  return "[&>div]:bg-blue-500"
}

const getModalProgressColor = (percent: number): string => {
  if (percent >= 95) return "[&>div]:bg-red-500"
  if (percent >= 86) return "[&>div]:bg-orange-500"
  if (percent >= 71) return "[&>div]:bg-yellow-500"
  return "[&>div]:bg-blue-500"
}

const getOSIcon = (osInfo: VMDetails["os_info"] | undefined, vmType: string): React.ReactNode => {
  if (vmType !== "lxc" || !osInfo?.id) {
    return null
  }

  const osId = osInfo.id.toLowerCase()

  switch (osId) {
    case "debian":
      return <img src="/icons/debian.svg" alt="Debian" className="h-16 w-16" />
    case "ubuntu":
      return <img src="/icons/ubuntu.svg" alt="Ubuntu" className="h-16 w-16" />
    case "alpine":
      return <img src="/icons/alpine.svg" alt="Alpine" className="h-16 w-16" />
    case "arch":
      return <img src="/icons/arch.svg" alt="Arch" className="h-16 w-16" />
    default:
      return null
  }
}

// Sprint 13.29: render a single LXC mount point row.
// Lifted out of the main component so the Mount Points tab renders
// uniformly for both configured mpX entries and ad-hoc inside-CT
// remote mounts. Capacity displays whatever the backend resolved —
// PVE storage stats, `df` of host path, or n/a for ad-hoc.
function MountPointCard({ mp }: { mp: LxcMountPoint }) {
  const t = useT()
  const isStale = mp.runtime_reachable === false
  const isReadonly = !isStale && mp.runtime_readonly === true
  const isDivergent = mp.runtime_mounted === false  // configured but not actually mounted
  // "Zombie bind": the host removed the source (e.g. USB pulled, manual
  // umount) but the CT mount namespace still shows the bind as mounted.
  // Reported by Ignacio Seijo (11/05). Only flag host_bind /
  // pve_storage_bind sources — PVE volume sources have no host path
  // and `host_source_exists` comes back null for them.
  const isHostDetached =
    mp.runtime_mounted === true &&
    (mp.type === "host_bind" || mp.type === "pve_storage_bind") &&
    mp.host_source_exists === false
  const cardClasses = isStale
    ? "border-red-500/50 bg-red-500/5"
    : isDivergent || isHostDetached
      ? "border-amber-500/40 bg-amber-500/5"
      : isReadonly
        ? "border-amber-500/30 bg-amber-500/5"
        : "border border-white/10 sm:border-border bg-white/5 sm:bg-card"

  const typeBadgeClass: Record<LxcMountPoint["type"], string> = {
    pve_volume: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    pve_storage_bind: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    host_bind: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    ad_hoc: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  }
  const typeLabel: Record<LxcMountPoint["type"], string> = {
    pve_volume: t("vmLxc.details.mountTypes.pveVolume"),
    pve_storage_bind: t("vmLxc.details.mountTypes.pveStorageBind"),
    host_bind: t("vmLxc.details.mountTypes.hostBind"),
    ad_hoc: t("vmLxc.details.mountTypes.adHoc"),
  }

  const fmtBytes = (b: number | null | undefined) => {
    if (b == null) return "—"
    const gb = b / 1024 ** 3
    if (gb < 1) return `${(gb * 1024).toFixed(1)} MB`
    if (gb >= 1000) return `${(gb / 1024).toFixed(2)} TB`
    return `${gb.toFixed(2)} GB`
  }
  const usedPct =
    mp.total_bytes && mp.used_bytes != null && mp.total_bytes > 0
      ? Math.round((mp.used_bytes / mp.total_bytes) * 100)
      : null

  // Parse mount options (runtime if available, else config flags) into
  // flag chips + key=value pairs. Same UX as the Remote Mounts modal.
  const optsString = mp.runtime_options || (mp.config_flags || []).join(",")
  const optsEntries = (optsString || "")
    .split(",")
    .filter(Boolean)
    .map((o) => {
      const eq = o.indexOf("=")
      return eq === -1
        ? { key: o, value: null as string | null }
        : { key: o.slice(0, eq), value: o.slice(eq + 1) }
    })
  const flags = optsEntries.filter((o) => o.value === null).map((o) => o.key)
  const keyValues = optsEntries.filter((o) => o.value !== null) as Array<{ key: string; value: string }>

  return (
    <div className={`rounded-lg p-4 ${cardClasses}`}>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              isStale ? "bg-red-500" : isDivergent ? "bg-amber-500" : "bg-green-500"
            }`}
          />
          <h3 className="font-mono font-semibold truncate">{mp.target}</h3>
          {mp.mp_index && (
            <Badge variant="outline" className="font-mono">
              {mp.mp_index}
            </Badge>
          )}
          <Badge className={typeBadgeClass[mp.type]}>{typeLabel[mp.type]}</Badge>
          {mp.runtime_fstype && (
            <Badge variant="outline" className="font-mono">
              {mp.runtime_fstype}
            </Badge>
          )}
        </div>
        <Badge
          className={
            isStale
              ? "bg-red-500/10 text-red-500 border-red-500/20"
              : isDivergent || isHostDetached
                ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                : isReadonly
                  ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                  : mp.runtime_mounted === null
                    ? "bg-gray-500/10 text-gray-400 border-gray-500/20"
                    : "bg-green-500/10 text-green-500 border-green-500/20"
          }
        >
          {isStale
            ? t("vmLxc.details.mountStatus.stale")
            : isDivergent
              ? t("vmLxc.details.mountStatus.notMounted")
              : isHostDetached
                ? t("vmLxc.details.mountStatus.hostDetached")
                : isReadonly
                  ? t("vmLxc.details.mountStatus.readOnly")
                  : mp.runtime_mounted === null
                    ? t("vmLxc.details.mountStatus.stopped")
                    : t("vmLxc.details.mountStatus.mounted")}
        </Badge>
      </div>

      {/* Source / Mounted-at info — what host resource backs the
          mount, and where it shows up inside the CT. The header
          already shows the target but it's worth surfacing the
          source/target relationship explicitly here so the user
          gets the full host→container path at a glance. */}
      <div className="text-sm space-y-1">
        <div>
          <span className="text-muted-foreground">{t("vmLxc.details.sourceHost")}:</span>{" "}
          <span className="font-mono">{mp.origin_label || mp.source}</span>
          {mp.origin_storage && mp.origin_storage_type && (
            <span className="text-muted-foreground ml-2">
              ({t("vmLxc.details.storageType", { type: mp.origin_storage_type })})
            </span>
          )}
        </div>
        <div>
          <span className="text-muted-foreground">{t("vmLxc.details.mountedAtCt")}:</span>{" "}
          <span className="font-mono">{mp.target}</span>
        </div>
      </div>

      {/* Capacity — total/used/available with progress bar. Available
          even when CT is stopped because numbers come from the host. */}
      {mp.total_bytes != null && (
        <div className="mt-3 space-y-2">
          <Progress
            value={usedPct ?? 0}
            className={`h-2 ${
              (usedPct ?? 0) > 90
                ? "[&>div]:bg-red-500"
                : (usedPct ?? 0) > 75
                  ? "[&>div]:bg-yellow-500"
                  : "[&>div]:bg-blue-500"
            }`}
          />
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">{t("vmLxc.details.total")}</p>
              <p className="font-medium">{fmtBytes(mp.total_bytes)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("vmLxc.details.used")}</p>
              <p className="font-medium">
                {fmtBytes(mp.used_bytes)} {usedPct != null && `(${usedPct}%)`}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("vmLxc.details.available")}</p>
              <p className="font-medium">{fmtBytes(mp.available_bytes)}</p>
            </div>
          </div>
        </div>
      )}

      {/* Mount attributes — config_options/flags from the mpX line in
          the LXC config (backup=0, shared=1, ro, replicate, etc.).
          Hidden when there's nothing to show. */}
      {(() => {
        const configEntries: Array<{ key: string; value: string | null }> = []
        for (const k of Object.keys(mp.config_options || {})) {
          configEntries.push({ key: k, value: mp.config_options[k] })
        }
        for (const f of mp.config_flags || []) {
          configEntries.push({ key: f, value: null })
        }
        if (configEntries.length === 0) return null
        return (
          <div className="mt-3">
            <p className="text-xs text-muted-foreground mb-1.5">
              {t("vmLxc.details.mountAttributes")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {configEntries.map((e) => (
                <Badge key={e.key} variant="outline" className="font-mono text-xs">
                  {e.key}{e.value !== null ? `=${e.value}` : ""}
                </Badge>
              ))}
            </div>
          </div>
        )
      })()}

      {/* Runtime mount options — what the kernel actually uses
          (vers, rsize, hard, sec, ...). Only meaningful when the CT
          is running; for stopped CTs we hide this section because
          the values would just repeat the config flags above.

          Sprint 13.29 detail: we already render the runtime fstype
          as a badge in the header, so it's fine to leave this
          unlabelled-for-state — only show "(declared)" suffix in
          the rare case where there's no runtime data but flags do
          exist. */}
      {(mp.runtime_mounted === true) && (keyValues.length > 0 || flags.length > 0) && (
        <div className="mt-3">
          <p className="text-xs text-muted-foreground mb-1.5">
            {t("vmLxc.details.runtimeMountOptions")}
          </p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {flags.map((f) => (
              <Badge key={f} variant="outline" className="font-mono text-xs">
                {f}
              </Badge>
            ))}
          </div>
          {keyValues.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-sm">
              {keyValues.map((kv) => (
                <div key={kv.key} className="min-w-0">
                  <span className="font-mono text-muted-foreground">{kv.key}</span>
                  <span className="font-mono text-foreground"> = {kv.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error / divergence note. */}
      {mp.runtime_error && (
        <p
          className={`mt-3 text-sm ${
            isStale ? "text-red-400" : "text-amber-400"
          }`}
        >
          {mp.runtime_error}
        </p>
      )}
    </div>
  )
}

export function VirtualMachines() {
  const t = useT()
  const {
    data: vmData,
    error,
    isLoading,
    mutate,
  } = useSWR<VMData[]>("/api/vms", fetcher, {
    refreshInterval: 2500,
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    dedupingInterval: 1000,
    errorRetryCount: 2,
  })

  const [selectedVM, setSelectedVM] = useState<VMData | null>(null)
  const [vmDetails, setVMDetails] = useState<VMDetails | null>(null)
  const [controlLoading, setControlLoading] = useState(false)
  // Destructive control confirmation. `Force Stop` and `Reboot` skip the OS
  // shutdown sequence and can corrupt running guests; gate them behind a
  // typed-VMID match prompt to prevent misclicks. See audit Tier 2 #17.
  const [confirmDestructive, setConfirmDestructive] = useState<{
    action: "stop" | "reboot"
    vmid: number
    vmName: string
  } | null>(null)
  const [confirmDestructiveTyped, setConfirmDestructiveTyped] = useState("")
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [terminalOpen, setTerminalOpen] = useState(false)
  const [terminalVmid, setTerminalVmid] = useState<number | null>(null)
  const [terminalVmName, setTerminalVmName] = useState<string>("")
  const [vmConfigs, setVmConfigs] = useState<Record<number, string>>({})
  const [currentView, setCurrentView] = useState<"main" | "metrics">("main")
  const [showAdditionalInfo, setShowAdditionalInfo] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [isEditingNotes, setIsEditingNotes] = useState(false)
  const [editedNotes, setEditedNotes] = useState("")
  const [savingNotes, setSavingNotes] = useState(false)
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null)
  const [ipsLoaded, setIpsLoaded] = useState(false)
  const [loadingIPs, setLoadingIPs] = useState(false)
  const [networkUnit, setNetworkUnit] = useState<"Bytes" | "Bits">("Bytes")
  
  // Backup states
  const [vmBackups, setVmBackups] = useState<VMBackup[]>([])
  const [backupStorages, setBackupStorages] = useState<BackupStorage[]>([])
  const [selectedBackupStorage, setSelectedBackupStorage] = useState<string>("")
  const [loadingBackups, setLoadingBackups] = useState(false)
  const [creatingBackup, setCreatingBackup] = useState(false)
  
  // Backup modal states
  const [showBackupModal, setShowBackupModal] = useState(false)
  const [backupMode, setBackupMode] = useState<string>("snapshot")
  const [backupProtected, setBackupProtected] = useState(false)
  const [backupNotification, setBackupNotification] = useState<string>("auto")
  const [backupNotes, setBackupNotes] = useState<string>("{{guestname}}")
  const [backupPbsChangeMode, setBackupPbsChangeMode] = useState<string>("default")
  
  // Tab state for modal
  const [activeModalTab, setActiveModalTab] = useState<"status" | "mounts" | "backups" | "app" | "updates" | "firewall">("status")

  // Firewall log state — fetched only when the operator opens that tab
  // so a CT/VM without firewall use doesn't pay the pvesh cost on every
  // modal open. Issue #14554 from the helper-scripts discussions.
  interface FirewallLogEntry { n: number; t: string }
  const [firewallLogs, setFirewallLogs] = useState<FirewallLogEntry[]>([])
  const [loadingFirewallLog, setLoadingFirewallLog] = useState(false)
  const [firewallEnabled, setFirewallEnabled] = useState<boolean>(true)
  const [firewallLogError, setFirewallLogError] = useState<string | null>(null)
  // Sprint 13.29: per-LXC mount points lazy-loaded when the user opens
  // the LXC modal. We fetch alongside backups (one-shot) so switching
  // tabs is instantaneous; the cost is small (parses one config file
  // + pvesm status which the kernel already caches).
  const [mountPoints, setMountPoints] = useState<LxcMountPoint[]>([])
  const [adHocMounts, setAdHocMounts] = useState<LxcMountPoint[]>([])
  const [loadingMounts, setLoadingMounts] = useState(false)
  
  // Detect standalone mode (webapp vs browser)
  const [isStandalone, setIsStandalone] = useState(false)
  
  useEffect(() => {
    const checkStandalone = () => {
      const standalone = window.matchMedia('(display-mode: standalone)').matches ||
                        (window.navigator as Navigator & { standalone?: boolean }).standalone === true
      setIsStandalone(standalone)
    }
    checkStandalone()
    
    const mediaQuery = window.matchMedia('(display-mode: standalone)')
    mediaQuery.addEventListener('change', checkStandalone)
    return () => mediaQuery.removeEventListener('change', checkStandalone)
  }, [])

  useEffect(() => {
    // `cancelled` short-circuits setState calls if the component unmounts
    // mid-fetch (user navigates away while we're still iterating LXCs in
    // batches). Without it, React logs "state update on unmounted
    // component" and we leak the closure that holds the configs map.
    let cancelled = false

    const fetchLXCIPs = async () => {
      if (!vmData || ipsLoaded || loadingIPs) return

      const lxcs = vmData.filter((vm) => vm.type === "lxc")

      if (lxcs.length === 0) {
        if (!cancelled) setIpsLoaded(true)
        return
      }

      setLoadingIPs(true)
      const configs: Record<number, string> = {}

      const batchSize = 5
      for (let i = 0; i < lxcs.length; i += batchSize) {
        if (cancelled) return
        const batch = lxcs.slice(i, i + batchSize)

        await Promise.all(
          batch.map(async (lxc) => {
            try {
              const controller = new AbortController()
              const timeoutId = setTimeout(() => controller.abort(), 10000)

              const details = await fetchApi(`/api/vms/${lxc.vmid}`)

              clearTimeout(timeoutId)

              if (details.lxc_ip_info?.primary_ip) {
                configs[lxc.vmid] = details.lxc_ip_info.primary_ip
              } else if (details.config) {
                configs[lxc.vmid] = extractIPFromConfig(details.config, details.lxc_ip_info)
              }
            } catch (error) {
              console.log(`Could not fetch IP for LXC ${lxc.vmid}`)
              configs[lxc.vmid] = "N/A"
            }
          }),
        )

        if (cancelled) return
        setVmConfigs((prev) => ({ ...prev, ...configs }))
      }

      if (cancelled) return
      setLoadingIPs(false)
      setIpsLoaded(true)
    }

    fetchLXCIPs()
    return () => {
      cancelled = true
    }
  }, [vmData, ipsLoaded, loadingIPs])

  // Load initial network unit and listen for changes
  useEffect(() => {
    setNetworkUnit(getNetworkUnit())

    const handleNetworkUnitChange = () => {
      setNetworkUnit(getNetworkUnit())
    }

    window.addEventListener("networkUnitChanged", handleNetworkUnitChange)
    window.addEventListener("storage", handleNetworkUnitChange)

    return () => {
      window.removeEventListener("networkUnitChanged", handleNetworkUnitChange)
      window.removeEventListener("storage", handleNetworkUnitChange)
    }
  }, [])

  // Keep the open modal's VM in sync with the /api/vms poll so CPU/RAM/I-O values
  // don't stay frozen at click-time. Single data source (/cluster/resources) shared
  // with the list — no source mismatch, no flicker.
  useEffect(() => {
    if (!selectedVM || !vmData) return
    const updated = vmData.find((v) => v.vmid === selectedVM.vmid)
    if (!updated || updated === selectedVM) return
    setSelectedVM(updated)
  }, [vmData])

  const handleVMClick = async (vm: VMData) => {
    setSelectedVM(vm)
    setCurrentView("main")
    setShowAdditionalInfo(false)
    setShowNotes(false)
    setIsEditingNotes(false)
    setEditedNotes("")
    setDetailsLoading(true)
    setActiveModalTab("status")
    // Reset Sprint 13.29 mount-points state from any previous selection
    // so the new modal doesn't briefly flash data from another LXC.
    setMountPoints([])
    setAdHocMounts([])
    // Reset firewall log state — fetched lazily when the user opens
    // that tab, since most operators won't visit it on every modal open.
    setFirewallLogs([])
    setFirewallLogError(null)
    setFirewallEnabled(true)

    // Load backups immediately (independent of config)
    fetchBackupStorages()
    fetchVmBackups(vm.vmid)

    // Sprint 13.29: load LXC mount points alongside backups so
    // switching to that tab is instant. Only LXCs have mpX entries —
    // qemu VMs use disks, not mount points, so we skip the request
    // and simply hide the tab below.
    if (vm.type === "lxc") {
      fetchMountPoints(vm.vmid)
    }

    try {
      const details = await fetchApi(`/api/vms/${vm.vmid}`)
      setVMDetails(details)
    } catch (error) {
      console.error("Error fetching VM details:", error)
    } finally {
      setDetailsLoading(false)
    }
  }

  const fetchMountPoints = async (vmid: number) => {
    setLoadingMounts(true)
    try {
      const response = await fetchApi<{
        ok: boolean
        running: boolean
        mount_points: LxcMountPoint[]
        ad_hoc: LxcMountPoint[]
      }>(`/api/lxc/${vmid}/mount-points`)
      if (response?.ok) {
        setMountPoints(response.mount_points || [])
        setAdHocMounts(response.ad_hoc || [])
      } else {
        setMountPoints([])
        setAdHocMounts([])
      }
    } catch (error) {
      console.error("Error fetching LXC mount points:", error)
      setMountPoints([])
      setAdHocMounts([])
    } finally {
      setLoadingMounts(false)
    }
  }

  const handleMetricsClick = () => {
    setCurrentView("metrics")
  }

  const handleBackToMain = () => {
    setCurrentView("main")
  }

  // Backup functions
  const fetchBackupStorages = async () => {
    try {
      const response = await fetchApi("/api/backup-storages")
      if (response.storages) {
        setBackupStorages(response.storages)
        if (response.storages.length > 0 && !selectedBackupStorage) {
          setSelectedBackupStorage(response.storages[0].storage)
        }
      }
    } catch (error) {
      console.error("Error fetching backup storages:", error)
    }
  }

  const fetchVmBackups = async (vmid: number) => {
    setLoadingBackups(true)
    try {
      const response = await fetchApi(`/api/vms/${vmid}/backups`)
      if (response.backups) {
        setVmBackups(response.backups)
      }
    } catch (error) {
      console.error("Error fetching VM backups:", error)
      setVmBackups([])
    } finally {
      setLoadingBackups(false)
    }
  }

  // Firewall log fetcher — proxies the PVE per-VM/CT firewall log
  // endpoint. The backend returns `firewall_enabled: false` when PVE
  // says the firewall is OFF for that guest; in that case we render
  // a callout instead of an empty viewer.
  const fetchFirewallLog = async (vmid: number) => {
    setLoadingFirewallLog(true)
    setFirewallLogError(null)
    try {
      const response = await fetchApi<{
        logs?: FirewallLogEntry[]
        firewall_enabled?: boolean
        error?: string
      }>(`/api/vms/${vmid}/firewall/log?limit=500`)
      setFirewallEnabled(response.firewall_enabled !== false)
      setFirewallLogs(Array.isArray(response.logs) ? response.logs : [])
      if (response.error && response.firewall_enabled !== false) {
        setFirewallLogError(response.error)
      }
    } catch (error) {
      setFirewallEnabled(true)
      setFirewallLogs([])
      setFirewallLogError(error instanceof Error ? error.message : String(error))
    } finally {
      setLoadingFirewallLog(false)
    }
  }

  const openBackupModal = () => {
    // Reset modal to defaults
    setBackupMode("snapshot")
    setBackupProtected(false)
    setBackupNotification("auto")
    setBackupNotes("{{guestname}}")
    setBackupPbsChangeMode("default")
    // Auto-select first storage if none selected
    if (!selectedBackupStorage && backupStorages.length > 0) {
      setSelectedBackupStorage(backupStorages[0].storage)
    }
    setShowBackupModal(true)
  }

  const handleCreateBackup = async () => {
    if (!selectedVM || !selectedBackupStorage) return
    
    setCreatingBackup(true)
    setShowBackupModal(false)
    
    try {
      await fetchApi(`/api/vms/${selectedVM.vmid}/backup`, {
        method: "POST",
        body: JSON.stringify({
          storage: selectedBackupStorage,
          mode: backupMode,
          compress: "zstd",
          protected: backupProtected,
          notification: backupNotification,
          notes: backupNotes,
          pbs_change_detection: backupPbsChangeMode
        }),
      })
      setTimeout(() => fetchVmBackups(selectedVM.vmid), 2000)
    } catch (error) {
      console.error("Error creating backup:", error)
      // Surface the failure to the user. Previous behaviour silently swallowed
      // backend errors so the user thought the backup started fine; in reality
      // the request had 4xx/5xx'd and nothing was scheduled.
      const msg = error instanceof Error ? error.message : t("vmLxc.errors.unknown")
      alert(t("vmLxc.errors.backupStartFailed", { message: msg }))
    } finally {
      setCreatingBackup(false)
    }
  }

  const handleVMControl = async (vmid: number, action: string) => {
    setControlLoading(true)
    try {
      await fetchApi(`/api/vms/${vmid}/control`, {
        method: "POST",
        body: JSON.stringify({ action }),
      })

      mutate()
      setSelectedVM(null)
      setVMDetails(null)
    } catch (error) {
      console.error(`Failed to ${action} VM ${vmid}:`, error)
      // Same UX issue as handleCreateBackup: a silent console.error left the
      // user looking at a "Stop"/"Start" button that just never reacted.
      const msg = error instanceof Error ? error.message : t("vmLxc.errors.unknown")
      alert(t("vmLxc.errors.controlFailed", { action, vmid, message: msg }))
    } finally {
      setControlLoading(false)
    }
  }

  // Open terminal for LXC container
  const openLxcTerminal = (vmid: number, vmName: string) => {
    setTerminalVmid(vmid)
    setTerminalVmName(vmName)
    setTerminalOpen(true)
  }
  
const handleDownloadLogs = async (vmid: number, vmName: string) => {
    try {
      const data = await fetchApi(`/api/vms/${vmid}/logs`)

      // Format logs as plain text
      let logText = `=== ${t("vmLxc.logs.header", { name: vmName, vmid })} ===\n`
      logText += `${t("vmLxc.logs.node")}: ${data.node}\n`
      logText += `${t("vmLxc.logs.type")}: ${data.type}\n`
      logText += `${t("vmLxc.logs.totalLines")}: ${data.log_lines}\n`
      logText += `${t("vmLxc.logs.generated")}: ${new Date().toISOString()}\n`
      logText += `\n${"=".repeat(80)}\n\n`

      if (data.logs && Array.isArray(data.logs)) {
        data.logs.forEach((log: any) => {
          if (typeof log === "object" && log.t) {
            logText += `${log.t}\n`
          } else if (typeof log === "string") {
            logText += `${log}\n`
          }
        })
      }

      const blob = new Blob([logText], { type: "text/plain" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `${vmName}-${vmid}-logs.txt`
      a.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Error downloading logs:", error)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case "running":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      case "stopped":
        return "bg-red-500/10 text-red-500 border-red-500/20"
      default:
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "running":
        return <Play className="h-3 w-3" />
      case "stopped":
        return <Square className="h-3 w-3" />
      default:
        return null
    }
  }

  const getStatusLabel = (status: string, uppercase = true) => {
    const label =
      status === "running"
        ? t("vmLxc.running")
        : status === "stopped"
        ? t("vmLxc.stopped")
        : status
    return uppercase ? label.toUpperCase() : label
  }

  const getTypeBadge = (type: string) => {
    if (type === "lxc") {
      return {
        color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
        label: "LXC",
        icon: <Container className="h-3 w-3 mr-1" />,
      }
    }
    return {
      color: "bg-purple-500/10 text-purple-500 border-purple-500/20",
      label: "VM",
      icon: <Server className="h-3 w-3 mr-1" />,
    }
  }

  // Ensure vmData is always an array (backend may return object on error)
  const safeVMData = Array.isArray(vmData) ? vmData : []

  // Status filter for the "Virtual Machines & Containers" list. Persisted
  // to localStorage so a reload keeps the operator's last view.
  const [statusFilter, setStatusFilter] = useState<"all" | "running" | "stopped">(() => {
    if (typeof window === "undefined") return "all"
    const stored = window.localStorage.getItem("proxmenux.vmListFilter")
    return stored === "running" || stored === "stopped" ? stored : "all"
  })
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("proxmenux.vmListFilter", statusFilter)
    }
  }, [statusFilter])

  const statusCounts = useMemo(() => ({
    all: safeVMData.length,
    running: safeVMData.filter((vm) => vm.status === "running").length,
    stopped: safeVMData.filter((vm) => vm.status === "stopped").length,
  }), [safeVMData])

  const filteredVMs = useMemo(() => {
    if (statusFilter === "all") return safeVMData
    return safeVMData.filter((vm) => vm.status === statusFilter)
  }, [safeVMData, statusFilter])

  // ── LXC update apply flow (Phase 2a/b) ────────────────────────────
  // Users pick a target (OS, App, both) + backup / restart options,
  // click Apply, and the ScriptTerminalModal streams the apply run.
  // On successful close, POST /api/lxc-updates/<vmid>/applied fires
  // the notification and forces a badge recheck.
  const [applyOpen, setApplyOpen] = useState(false)
  const [applyVmid, setApplyVmid] = useState<number | null>(null)
  const [applyTarget, setApplyTarget] = useState<"os" | "app" | "both">("os")
  const [applyBackup, setApplyBackup] = useState(true)
  const [applyBackupStorage, setApplyBackupStorage] = useState<string>("")
  const [applyRestart, setApplyRestart] = useState(false)
  const [applyStartedAt, setApplyStartedAt] = useState<number>(0)
  // Extra state carried alongside applyTarget when the App branch is
  // driven by a user-defined `update_command` on a specific registered
  // app (not the CT-wide /usr/bin/update). Passed to the terminal
  // script as UPDATE_COMMAND env var; the script uses it in preference
  // to /usr/bin/update when present.
  const [applyUpdateCommand, setApplyUpdateCommand] = useState<string>("")
  const [applyAppName, setApplyAppName] = useState<string>("")

  // Updates tab — inline custom-command editor state. Keyed on app.id
  // so the user can open one editor at a time; opening a second closes
  // the first (kept in localState because there's never a need to edit
  // two at once). `showHiddenNotices` opts back into displaying the
  // Case-3a "no method" cards the user previously dismissed.
  const [customCmdEditingApp, setCustomCmdEditingApp] = useState<string | null>(null)
  const [customCmdDraft, setCustomCmdDraft] = useState<string>("")
  const [customCmdSaving, setCustomCmdSaving] = useState(false)
  const [showHiddenNotices, setShowHiddenNotices] = useState(false)

  const openCustomCmdEditor = (app: LxcAppWatch) => {
    setCustomCmdEditingApp(app.id)
    setCustomCmdDraft(app.update_command || "")
  }

  // ── Options card unified state ──────────────────────────────────
  // Single source of truth for apply preferences (backup + restart)
  // used by BOTH the manual "Apply update" buttons AND the scheduled
  // runs — persisted per-CT in the sidecar's schedule object. Also
  // holds the schedule config itself and any external host cron
  // detected via the community-scripts pattern. All loaded once when
  // the user opens the Updates tab of a specific LXC.
  const [scheduleLoaded, setScheduleLoaded] = useState<number | null>(null)
  const [scheduleEnabled, setScheduleEnabled] = useState(false)
  const [scheduleCron, setScheduleCron] = useState("0 3 * * *")
  const [schedulePreset, setSchedulePreset] = useState<string>("daily-3am")
  const [scheduleTarget, setScheduleTarget] = useState<"os" | "app" | "both">("both")
  const [scheduleLastRunAt, setScheduleLastRunAt] = useState<string | null>(null)
  const [scheduleLastRunStatus, setScheduleLastRunStatus] = useState<string | null>(null)
  const [scheduleSaving, setScheduleSaving] = useState(false)
  const [scheduleError, setScheduleError] = useState<string | null>(null)
  const [externalCron, setExternalCron] = useState<{
    source: string
    cron_line: string
    cron: string
    human_schedule: string
    type: string
    variant?: string
    scope?: string
  } | null>(null)
  // True when the server returned a schedule with a non-empty `cron`
  // field — lets the view mode distinguish "configured but disabled"
  // (Switch is off but a schedule exists) from "nothing scheduled".
  const [scheduleConfigured, setScheduleConfigured] = useState(false)
  // Options card edit-mode toggle. View mode shows persisted config
  // read-only; edit mode swaps to the sunken-input pattern per the
  // global card-contrast rule (see project memory).
  const [optionsEditMode, setOptionsEditMode] = useState(false)
  // Snapshot of state at the moment Edit is entered so Cancel can
  // fully restore. Save wipes it after PUTting.
  const [optionsSnapshot, setOptionsSnapshot] = useState<any>(null)

  // Cron presets — every entry maps a friendly label to a real
  // 5-field cron expression the backend parser accepts. Order + slugs
  // stable so the Select value round-trips a saved schedule.
  const CRON_PRESETS: { value: string; label: string; cron: string }[] = [
    { value: "hourly", label: t("vmLxc.cronPresets.hourly"), cron: "0 * * * *" },
    { value: "daily-3am", label: t("vmLxc.cronPresets.dailyAt3"), cron: "0 3 * * *" },
    { value: "daily-noon", label: t("vmLxc.cronPresets.dailyAtNoon"), cron: "0 12 * * *" },
    { value: "weekly-sun-3am", label: t("vmLxc.cronPresets.weeklySun3"), cron: "0 3 * * 0" },
    { value: "monthly-1st-3am", label: t("vmLxc.cronPresets.monthly1st3"), cron: "0 3 1 * *" },
    { value: "custom", label: t("vmLxc.cronPresets.custom"), cron: "" },
  ]

  const loadSchedule = async (vmid: number) => {
    setScheduleError(null)
    try {
      const s: any = await fetchApi(`/api/vms/${vmid}/schedule`)
      if (s && typeof s === "object") {
        setScheduleEnabled(!!s.enabled)
        setScheduleConfigured(!!s.cron)
        const cron = s.cron || "0 3 * * *"
        setScheduleCron(cron)
        const matched = CRON_PRESETS.find((p) => p.value !== "custom" && p.cron === cron)
        setSchedulePreset(matched ? matched.value : "custom")
        setScheduleTarget(s.target || "both")
        // Unified apply options — backup/restart/storage feed BOTH
        // manual applies and scheduled runs. Values live in the
        // schedule object even when enabled=false so preferences
        // survive toggling the schedule off.
        if (s.backup !== undefined) setApplyBackup(!!s.backup)
        if (s.backup_storage) setApplyBackupStorage(s.backup_storage)
        if (s.restart !== undefined) setApplyRestart(!!s.restart)
        setScheduleLastRunAt(s.last_run_at || null)
        setScheduleLastRunStatus(s.last_run_status || null)
        setExternalCron(s.external_cron || null)
      }
    } catch (e: any) {
      setScheduleError(e?.message || "Could not load schedule")
    } finally {
      setScheduleLoaded(vmid)
    }
  }

  const saveSchedule = async (vmid: number) => {
    setScheduleSaving(true)
    setScheduleError(null)
    // Only persist a cron when the user actually wants a schedule.
    // Prevents the delete-then-save recreation bug: after Delete we
    // leave scheduleConfigured=false and Save PUTs cron="" so the
    // backend doesn't resurrect the schedule.
    const cronToSave = scheduleEnabled || scheduleConfigured ? scheduleCron : ""
    try {
      await fetchApi(`/api/vms/${vmid}/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: scheduleEnabled,
          cron: cronToSave,
          target: scheduleTarget,
          backup: applyBackup,
          backup_storage: applyBackupStorage || selectedBackupStorage || "",
          restart: applyRestart,
        }),
      })
      if (cronToSave.trim()) setScheduleConfigured(true)
    } catch (e: any) {
      setScheduleError(e?.message || "Save failed")
    } finally {
      setScheduleSaving(false)
    }
  }

  const enterOptionsEdit = () => {
    setOptionsSnapshot({
      backup: applyBackup,
      backup_storage: applyBackupStorage,
      restart: applyRestart,
      scheduleEnabled: scheduleEnabled,
      scheduleCron: scheduleCron,
      schedulePreset: schedulePreset,
      scheduleTarget: scheduleTarget,
    })
    setOptionsEditMode(true)
  }
  const cancelOptionsEdit = () => {
    if (optionsSnapshot) {
      setApplyBackup(optionsSnapshot.backup)
      setApplyBackupStorage(optionsSnapshot.backup_storage)
      setApplyRestart(optionsSnapshot.restart)
      setScheduleEnabled(optionsSnapshot.scheduleEnabled)
      setScheduleCron(optionsSnapshot.scheduleCron)
      setSchedulePreset(optionsSnapshot.schedulePreset)
      setScheduleTarget(optionsSnapshot.scheduleTarget)
    }
    setOptionsSnapshot(null)
    setOptionsEditMode(false)
  }
  const saveOptionsEdit = async () => {
    if (!selectedVM) return
    await saveSchedule(selectedVM.vmid)
    setOptionsSnapshot(null)
    setOptionsEditMode(false)
  }
  const deleteScheduleFromOptions = async () => {
    if (!selectedVM) return
    if (!confirm(t("vmLxc.scheduled.deleteConfirm"))) return
    setScheduleSaving(true)
    try {
      await fetchApi(`/api/vms/${selectedVM.vmid}/schedule`, { method: "DELETE" })
      setScheduleEnabled(false)
      setScheduleConfigured(false)
      setScheduleCron("0 3 * * *")
      setSchedulePreset("daily-3am")
      setScheduleLastRunAt(null)
      setScheduleLastRunStatus(null)
    } catch (e: any) {
      setScheduleError(e?.message || "Delete failed")
    } finally {
      setScheduleSaving(false)
    }
  }

  // Turn a 5-field cron into a plain-English label — mirrors the
  // backend's _humanise_cron so view mode matches the picker's
  // preset labels.
  const humanCron = (expr: string): string => {
    if (!expr) return ""
    const parts = expr.trim().split(/\s+/)
    if (parts.length !== 5) return expr
    const [m, h, d, mo, w] = parts
    const hhmm = () => {
      const hn = parseInt(h, 10), mn = parseInt(m, 10)
      if (isNaN(hn) || isNaN(mn)) return `${h}:${m}`
      return `${String(hn).padStart(2, "0")}:${String(mn).padStart(2, "0")}`
    }
    if (d === "*" && mo === "*" && w === "*" && /^\d+$/.test(m) && /^\d+$/.test(h)) return `Daily at ${hhmm()}`
    if (d === "*" && mo === "*" && /^\d+$/.test(w) && /^\d+$/.test(m) && /^\d+$/.test(h)) {
      const wdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
      const wn = parseInt(w, 10)
      const wname = (wn >= 0 && wn <= 6) ? wdays[wn] : w
      return `Weekly (${wname} ${hhmm()})`
    }
    if (mo === "*" && w === "*" && /^\d+$/.test(d) && /^\d+$/.test(m) && /^\d+$/.test(h)) return `Monthly (day ${parseInt(d, 10)} at ${hhmm()})`
    if (h === "*" && d === "*" && mo === "*" && w === "*" && m === "0") return "Hourly"
    return expr
  }

  // Load the schedule once whenever the user opens the Updates tab
  // of a specific LXC. Keying on vmid keeps us from re-fetching on
  // every render but also refetches after switching CTs.
  useEffect(() => {
    if (activeModalTab !== "updates") return
    if (!selectedVM || selectedVM.type !== "lxc") return
    if (scheduleLoaded === selectedVM.vmid) return
    loadSchedule(selectedVM.vmid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeModalTab, selectedVM?.vmid])
  const closeCustomCmdEditor = () => {
    setCustomCmdEditingApp(null)
    setCustomCmdDraft("")
  }
  // Persists a partial update to /api/vms/<vmid>/apps/<app_id>. The
  // update_app validator on the backend performs a full-config
  // replace, so we hydrate the current app payload with the patch
  // before PUTting to preserve every other field the user set.
  const patchAppWatch = async (
    vmid: number,
    app: LxcAppWatch,
    patch: Record<string, any>,
  ) => {
    // Fetch the full current config for this app so we can echo it
    // back with the patch applied — the backend replaces the whole
    // record and would drop any field we omitted.
    const full: any = await fetchApi(`/api/vms/${vmid}/apps`)
    const current = (full?.apps || []).find((a: any) => a.id === app.id)
    if (!current) throw new Error("app not found in sidecar")
    const { id: _id, state: _state, created_at: _created, ...rest } = current
    const payload = { ...rest, ...patch }
    await fetchApi(`/api/vms/${vmid}/apps/${app.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
    mutate()
  }
  const saveCustomCommand = async (vmid: number, app: LxcAppWatch) => {
    setCustomCmdSaving(true)
    try {
      await patchAppWatch(vmid, app, {
        update_command: customCmdDraft.trim(),
        // Saving a command implicitly re-enables the notice (moot —
        // the notice only shows when there is no command).
        hide_no_updater_notice: false,
      })
      closeCustomCmdEditor()
    } catch (e) {
      alert(`Could not save custom command: ${(e as any)?.message || e}`)
    } finally {
      setCustomCmdSaving(false)
    }
  }
  const removeCustomCommand = async (vmid: number, app: LxcAppWatch) => {
    if (!confirm(`Remove the custom update command for "${app.name}"?`)) return
    setCustomCmdSaving(true)
    try {
      await patchAppWatch(vmid, app, { update_command: "" })
      closeCustomCmdEditor()
    } catch (e) {
      alert(`Could not remove custom command: ${(e as any)?.message || e}`)
    } finally {
      setCustomCmdSaving(false)
    }
  }
  const hideNoUpdaterNotice = async (vmid: number, app: LxcAppWatch) => {
    try {
      await patchAppWatch(vmid, app, { hide_no_updater_notice: true })
    } catch (e) {
      alert(`Could not hide notice: ${(e as any)?.message || e}`)
    }
  }

  const openApplyTerminal = (
    vmid: number,
    target: "os" | "app" | "both",
    opts?: { updateCommand?: string; appName?: string },
  ) => {
    setApplyVmid(vmid)
    setApplyTarget(target)
    setApplyUpdateCommand(opts?.updateCommand || "")
    setApplyAppName(opts?.appName || "")
    // Default storage to the same one the manual backup modal picked
    // (already resolved to the first vzdump-capable storage).
    if (!applyBackupStorage && selectedBackupStorage) {
      setApplyBackupStorage(selectedBackupStorage)
    } else if (!applyBackupStorage && backupStorages.length > 0) {
      setApplyBackupStorage(backupStorages[0].storage)
    }
    setApplyStartedAt(Date.now())
    setApplyOpen(true)
  }
  const handleApplyComplete = async () => {
    if (applyVmid == null) return
    const duration = Math.max(0, Math.round((Date.now() - applyStartedAt) / 1000))
    // The modal fires onComplete on any WS close (success or user cancel);
    // we always report the attempt so the notification records it and
    // the badge is force-refreshed. success=true is optimistic — the
    // script's own exit code is the ground truth surfaced in the log
    // the user just watched.
    try {
      await fetchApi(`/api/lxc-updates/${applyVmid}/applied`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          success: true,
          target: applyTarget,
          duration_seconds: duration,
          ct_name: selectedVM?.name || `CT-${applyVmid}`,
        }),
      })
    } catch {
      // Non-fatal — the notification is a nice-to-have.
    }
    // Backend's POST /applied handler already force-refreshes the
    // managed_installs snapshot, so the next natural /api/vms poll
    // (every 2.5s via SWR refreshInterval) picks up the post-update
    // counts on its own. We deliberately avoid mutate() or explicit
    // fetch here — those trigger re-render cascades that can close
    // the parent modal.
  }

  // Render the "📦 N updates / 🛡 N security" badge next to an LXC in
  // the dashboard list. Used ONLY in the card row alongside Uptime —
  // the modal surfaces the same info via a dedicated tab instead of
  // duplicating a badge in its header.
  //
  // Sizing matches the sibling "Uptime: …" text (text-sm + h-4 icon)
  // so the row reads as a single visual unit. Colour is violet, the
  // shared accent for "managed updates" across notifications and UI
  // (mirrors the Secure Gateway visual treatment). Security count
  // stays red because it's still an urgency cue independent of the
  // update theme.
  const renderLxcUpdateBadge = (
    uc?: LxcUpdateCheck,
    compact = false,
    onClick?: () => void,
  ) => {
    if (!uc?.available || !uc.count || uc.count <= 0) return null
    const last = uc.last_check
      ? new Date(uc.last_check).toLocaleString()
      : "—"
    const topNames = (uc.packages || [])
      .slice(0, 5)
      .map((p) => p.name)
      .join(", ")
    const secHint =
      uc.security_count > 0 ? ` · ${uc.security_count} ${t("vmLxc.updatesPanel.security")}` : ""
    // Tooltip leads with the action when the badge is clickable so the
    // affordance is explicit on hover — the chevron at the end of the
    // badge reinforces the same signal visually for users who don't
    // hover (mobile).
    const tooltipPrefix = onClick ? `${t("vmLxc.updatesPanel.clickToView")} · ` : ""
    const tooltip = `${tooltipPrefix}${t("vmLxc.updatesPanel.lastChecked")} ${last}${secHint}${topNames ? ` · ${topNames}` : ""}`
    // Compact = mobile card; matches the surrounding 10-12px chrome
    // (ID line, type badge) so the count doesn't visually dominate.
    // Non-compact = desktop card row, sized to match "Uptime: ..." text.
    const sizing = compact
      ? "text-[11px] gap-1 px-1.5 py-0"
      : "text-sm gap-1.5 px-2 py-0.5"
    const iconSize = compact ? "h-3 w-3" : "h-4 w-4"
    // Only soften the bg on hover — no border change, no focus ring.
    // The chevron at the end of the badge carries the "open this"
    // affordance on its own. The Badge component's CVA base adds a
    // `focus:ring-2 focus:ring-ring focus:ring-offset-2` (the white
    // double border we kept seeing on tap/click) — explicitly cancel
    // every piece of it here.
    const clickable = onClick
      ? "cursor-pointer hover:bg-violet-500/20 transition-colors focus:outline-none focus:ring-0 focus:ring-offset-0 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
      : ""
    return (
      <Badge
        variant="outline"
        className={`bg-violet-500/10 text-violet-400 border-violet-500/30 flex items-center flex-shrink-0 ${sizing} ${clickable}`}
        title={tooltip}
        onClick={onClick}
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        <Package className={iconSize} />
        {uc.count} {compact ? "" : (uc.count === 1 ? t("vmLxc.updatesPanel.updateSingular") : t("vmLxc.updatesPanel.updatePlural"))}
        {/* Chevron only when the badge is wired up as a clickable
            shortcut — its absence on the dashboard card avoids
            implying interactivity where there isn't any (the whole
            row is the click target there). */}
        {onClick && <ChevronRight className={`${iconSize} -mr-0.5 opacity-80`} />}
      </Badge>
    )
  }

  // App Watch badge (Phase 2c) — shown next to the update badge in
  // the header, and inline on the desktop card row. Three states:
  //   • up-to-date (installed==latest) → green filled
  //   • update available               → orange filled
  //   • no upstream check / no version → neutral outline
  // Clicking always opens the App tab.
  const renderLxcAppBadge = (
    aw?: LxcAppWatch | null,
    compact = false,
    onClick?: () => void,
  ) => {
    if (!aw?.name) return null
    const installed = aw.installed_version
    const hasUpdate = aw.update_available === true
    const upToDate = aw.update_available === false && !!installed
    const color = hasUpdate
      ? "bg-purple-600/15 text-purple-300 border-purple-500/40"
      : upToDate
        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
        : "bg-muted text-muted-foreground border-border"
    const sizing = compact
      ? "text-[11px] gap-1 px-1.5 py-0"
      : "text-sm gap-1.5 px-2 py-0.5"
    const iconSize = compact ? "h-3 w-3" : "h-4 w-4"
    const clickable = onClick
      ? "cursor-pointer hover:brightness-125 transition-all focus:outline-none focus:ring-0"
      : ""
    const tooltipParts: string[] = []
    if (installed) tooltipParts.push(`Installed: ${installed}`)
    if (aw.latest_version) tooltipParts.push(`Latest: ${aw.latest_version}`)
    if (aw.checked_at) tooltipParts.push(`Checked: ${new Date(aw.checked_at).toLocaleString()}`)
    if (aw.error) tooltipParts.push(`Note: ${aw.error}`)
    const tooltip = (onClick ? "Click to open App tab · " : "") + tooltipParts.join(" · ")
    return (
      <Badge
        variant="outline"
        className={`flex items-center flex-shrink-0 ${sizing} ${color} ${clickable}`}
        title={tooltip}
        onClick={onClick}
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        <Package className={iconSize} />
        <span className="truncate max-w-[180px]">{aw.name}</span>
        {installed && <span className="font-mono opacity-80">{installed}</span>}
      </Badge>
    )
  }

  // Total allocated RAM for ALL VMs/LXCs (running + stopped)
  const totalAllocatedMemoryGB = useMemo(() => {
    return (safeVMData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  // Allocated RAM only for RUNNING VMs/LXCs (this is what actually matters for overcommit)
  const runningAllocatedMemoryGB = useMemo(() => {
    return (safeVMData
      .filter((vm) => vm.status === "running")
      .reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  const { data: systemData } = useSWR<{ memory_total: number; memory_used: number; memory_usage: number; cpu_cores?: number; cpu_threads?: number }>(
    "/api/system",
    fetcher,
    {
      refreshInterval: 37000,
      revalidateOnFocus: false,
    },
  )

  const physicalMemoryGB = systemData?.memory_total ?? null
  const usedMemoryGB = systemData?.memory_used ?? null
  const memoryUsagePercent = systemData?.memory_usage ?? null
  const allocatedMemoryGB = Number.parseFloat(totalAllocatedMemoryGB)
  const runningAllocatedGB = Number.parseFloat(runningAllocatedMemoryGB)
  // Overcommit warning should be based on RUNNING VMs allocation, not total
  const isMemoryOvercommit = physicalMemoryGB !== null && runningAllocatedGB > physicalMemoryGB

  const getMemoryUsageColor = (percent: number | null) => {
    if (percent === null) return "bg-blue-500"
    if (percent >= 95) return "bg-red-500"
    if (percent >= 86) return "bg-orange-500"
    if (percent >= 71) return "bg-yellow-500"
    return "bg-blue-500"
  }

  const getMemoryPercentTextColor = (percent: number | null) => {
    if (percent === null) return "text-muted-foreground"
    if (percent >= 95) return "text-red-500"
    if (percent >= 86) return "text-orange-500"
    if (percent >= 71) return "text-yellow-500"
    return "text-green-500"
  }

  const formatCoreCount = (count: number) => {
    const key = count === 1 ? "one" : count >= 2 && count <= 4 ? "few" : "many"
    return t(`vmLxc.coreCount.${key}`, { count })
  }

  const displayedFirewallLogs = useMemo(() => {
    return firewallLogs.filter((entry) => {
      const text = (entry.t || "").trim().toLowerCase()
      return text.length > 0 && text !== "no content"
    })
  }, [firewallLogs])

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-2 border-muted"></div>
          <div className="absolute inset-0 h-12 w-12 rounded-full border-2 border-transparent border-t-primary animate-spin"></div>
        </div>
        <div className="text-sm font-medium text-foreground">{t("vmLxc.loadingTitle")}</div>
        <p className="text-xs text-muted-foreground">{t("vmLxc.loadingDescription")}</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8 text-red-500">{t("vmLxc.loadingError", { error: error.message })}</div>
      </div>
    )
  }

  // Single-pass decode. Proxmox URL-encodes notes exactly once when storing
  // them in `config.description`, so a single `decodeURIComponent` is the
  // correct round-trip. The previous loop decoded up to 5 times, which made
  // it possible to ship a payload like `%253Cscript%253E` past one-pass
  // filters (`%25` → `%` → second decode produces `<script>`). With the
  // dangerouslySetInnerHTML render path already removed (Sprint 4.1) the
  // immediate XSS is gone, but keeping the loop on the editor path keeps
  // the same evasion vector available for future use sites.
  const decodeRecursively = (str: string): string => {
    try {
      return decodeURIComponent(str.replace(/%0A/g, "\n"))
    } catch {
      return str
    }
  }

  const handleEditNotes = () => {
    if (vmDetails?.config?.description) {
      const decoded = decodeRecursively(vmDetails.config.description)
      setEditedNotes(decoded)
    } else {
      setEditedNotes("") // Ensure editedNotes is empty if no description exists
    }
    setIsEditingNotes(true)
  }

  const handleSaveNotes = async () => {
    if (!selectedVM || !vmDetails) return

    setSavingNotes(true)
    try {
      await fetchApi(`/api/vms/${selectedVM.vmid}/description`, {
        method: "PUT",
        body: JSON.stringify({
          description: editedNotes, // Send as-is, pvesh will handle encoding
        }),
      })

      setVMDetails({
        ...vmDetails,
        config: {
          ...vmDetails.config,
          description: editedNotes, // Store unencoded
        },
      })
      setIsEditingNotes(false)
    } catch (error) {
      console.error("Error saving notes:", error)
      alert(t("vmLxc.errors.saveNotesFailed"))
    } finally {
      setSavingNotes(false)
    }
  }

  const handleCancelEditNotes = () => {
    setIsEditingNotes(false)
    setEditedNotes("")
  }

  return (
    <div className="space-y-6">
      {/*
        styled-jsx is scoped by default — it adds a hash class to
        selectors so they only match elements rendered by this
        component. Content injected via `dangerouslySetInnerHTML`
        does NOT get the hash, so descendant selectors like
        `div[align="center"]` never matched the helper-script HTML
        and notes rendered left-aligned. Wrapping the descendant
        selectors in `:global(...)` keeps the parent class scoped
        but lets the inner rules apply to the injected HTML.
      */}
      <style jsx>{`
        .proxmenux-notes {
          all: revert;
        }
        .proxmenux-notes :global(a) {
          display: inline-block;
          margin-right: 4px;
          text-decoration: none;
        }
        .proxmenux-notes :global(img) {
          display: inline-block;
          vertical-align: middle;
        }
        .proxmenux-notes :global(p) {
          margin: 0.5rem 0;
        }
        .proxmenux-notes :global(table) {
          width: auto !important;
          margin: 0 auto;
        }
        .proxmenux-notes :global(div[align="center"]) {
          text-align: center;
        }
        .proxmenux-notes :global(table td:nth-child(2)) {
          text-align: left;
          padding-left: 16px;
        }
        .proxmenux-notes :global(table td:nth-child(2) h1) {
          text-align: left;
          font-size: 2rem;
          font-weight: bold;
          line-height: 1.2;
        }
        .proxmenux-notes :global(table td:nth-child(2) p) {
          text-align: left;
        }
        .proxmenux-notes :global(table + p) {
          margin-top: 1rem;
          padding-top: 1rem;
          border-top: 1px solid rgba(255, 255, 255, 0.1);
        }
        .proxmenux-notes-plaintext {
          white-space: pre-wrap;
          font-family: monospace;
        }
      `}</style>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6">
        {/* ── Total VMs & LXCs (preview restyle: B-headline + pills, matching Overview) ── */}
        {(() => {
          const running = safeVMData.filter((vm) => vm.status === "running").length
          const stopped = safeVMData.filter((vm) => vm.status === "stopped").length
          const total = safeVMData.length
          const vms = safeVMData.filter((vm) => vm.type === "qemu" || vm.type === "vm").length
          const lxc = safeVMData.filter((vm) => vm.type === "lxc").length
          return (
            <Card className="bg-card border-border">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{t("vmLxc.totalVmLxc")}</CardTitle>
                <Server className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="flex items-end justify-between">
                  <div>
                    <span className="text-4xl font-bold leading-none text-foreground">{running}</span>
                    <span className="text-lg font-medium ml-1 text-muted-foreground">/ {total}</span>
                  </div>
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    {running} {t("vmLxc.running")}
                  </Badge>
                </div>
                <div className="mt-3 flex gap-1 flex-wrap">
                  {vms > 0 && (
                    <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                      {vms} {t("vmLxc.vms")}
                    </Badge>
                  )}
                  {lxc > 0 && (
                    <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">{lxc} LXC</Badge>
                  )}
                  {stopped > 0 && (
                    <Badge variant="outline" className="bg-muted text-muted-foreground border-border">
                      {stopped} {t("vmLxc.stopped")}
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          )
        })()}

        {/* ── Total CPU Allocated (preview restyle: donut + Used/Configured/In use) ── */}
        {(() => {
          const allocPct = safeVMData.reduce((sum, vm) => sum + (vm.cpu || 0), 0) * 100
          const configuredVCPU = safeVMData.reduce((sum, vm) => sum + (vm.maxcpu || 0), 0)
          const inUseVCPU = safeVMData
            .filter((vm) => vm.status === "running")
            .reduce((sum, vm) => sum + (vm.maxcpu || 0), 0)
          const hostThreads = systemData?.cpu_threads ?? systemData?.cpu_cores ?? 0
          const stroke = allocPct >= 90 ? '#ef4444' : allocPct >= 75 ? '#f59e0b' : '#3b82f6'
          return (
            <Card className="bg-card border-border">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{t("vmLxc.totalCpuAllocated")}</CardTitle>
                <Cpu className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <svg viewBox="0 0 36 36" className="w-[72px] h-[72px] flex-shrink-0">
                    <circle cx="18" cy="18" r="15.9155" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth="3"/>
                    <circle cx="18" cy="18" r="15.9155" fill="none" stroke={stroke} strokeWidth="3"
                            strokeDasharray={`${Math.min(100, allocPct)} 100`} strokeLinecap="round"
                            style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}/>
                    <text x="18" y="19.5" textAnchor="middle" fontSize="10" fontWeight="700" fill="currentColor">{Math.round(allocPct)}%</text>
                  </svg>
                  <div className="flex-1 space-y-2">
                    <div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">{t("vmLxc.used")}</span>
                        <span className="font-medium font-mono whitespace-nowrap">{Math.round(allocPct)}%</span>
                      </div>
                      <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, allocPct)}%`, background: stroke }}/>
                      </div>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{t("vmLxc.configured")}</span>
                      <span className="font-medium font-mono whitespace-nowrap">{configuredVCPU || '—'}{hostThreads ? ` / ${hostThreads}` : ''} vCPU</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{t("vmLxc.inUse")}</span>
                      <span className="font-medium font-mono whitespace-nowrap">{inUseVCPU || '—'}{hostThreads ? ` / ${hostThreads}` : ''} vCPU</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })()}

        {/* ── Total Memory (preview restyle: donut + mini-bars Used/Allocated) ── */}
        {(() => {
          const usedPct = memoryUsagePercent ?? 0
          const usedGB = usedMemoryGB ?? 0
          const totalGB = physicalMemoryGB ?? 0
          const allocPct = totalGB > 0 ? (allocatedMemoryGB / totalGB) * 100 : 0
          const stroke = usedPct >= 90 ? '#ef4444' : usedPct >= 75 ? '#f59e0b' : '#3b82f6'
          return (
            <Card className="bg-card border-border">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{t("vmLxc.totalMemory")}</CardTitle>
                <MemoryStick className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <svg viewBox="0 0 36 36" className="w-[72px] h-[72px] flex-shrink-0">
                    <circle cx="18" cy="18" r="15.9155" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth="3"/>
                    <circle cx="18" cy="18" r="15.9155" fill="none" stroke={stroke} strokeWidth="3"
                            strokeDasharray={`${usedPct} 100`} strokeLinecap="round"
                            style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}/>
                    <text x="18" y="19.5" textAnchor="middle" fontSize="10" fontWeight="700" fill="currentColor">{Math.round(usedPct)}%</text>
                  </svg>
                  <div className="flex-1 space-y-2">
                    <div>
                      <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{t("vmLxc.used")}</span>
                      <span className="font-medium font-mono whitespace-nowrap">{usedGB.toFixed(1)}</span>
                      </div>
                      <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${usedPct}%`, background: stroke }}/>
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{t("vmLxc.allocated")}</span>
                      <span className="font-medium font-mono whitespace-nowrap">{allocatedMemoryGB.toFixed(1)}</span>
                      </div>
                      <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, allocPct)}%`, background: isMemoryOvercommit ? '#f59e0b' : 'rgba(99,102,241,0.55)' }}/>
                      </div>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{t("vmLxc.total")}</span>
                      <span className="font-medium font-mono whitespace-nowrap">{totalGB.toFixed(0)} GB</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })()}

        {/* ── Total Disk (preview restyle: headline + 2-segment stacked bar Used/Alloc-not-Used) ── */}
        {(() => {
          const usedGB = safeVMData.reduce((sum, vm) => sum + (vm.disk || 0), 0) / 1024 ** 3
          const allocGB = safeVMData.reduce((sum, vm) => sum + (vm.maxdisk || 0), 0) / 1024 ** 3
          const utilPct = allocGB > 0 ? (usedGB / allocGB) * 100 : 0
          const idleGB = Math.max(0, allocGB - usedGB)
          const stroke = utilPct >= 90 ? '#ef4444' : utilPct >= 75 ? '#f59e0b' : '#3b82f6'
          const usedSeg = allocGB > 0 ? (usedGB / allocGB) * 100 : 0
          return (
            <Card className="bg-card border-border">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{t("vmLxc.totalDisk")}</CardTitle>
                <HardDrive className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="flex items-end justify-between mb-3">
                  <div>
                    <span className="text-xl lg:text-2xl font-bold leading-none">{formatStorage(usedGB)}</span>
                    <span className="text-sm font-medium ml-1 text-muted-foreground">{t("vmLxc.used").toLowerCase()}</span>
                  </div>
                  <Badge variant="outline" className="bg-muted text-muted-foreground border-border">
                    {Math.round(utilPct)}% {t("vmLxc.utilization")}
                  </Badge>
                </div>
                <div className="flex h-1.5 rounded-full overflow-hidden gap-[2px]">
                  <div style={{ width: `${usedSeg}%`, background: stroke }} title={`${t("vmLxc.used")} ${formatStorage(usedGB)}`}></div>
                  <div style={{ flex: 1, background: 'rgba(168,85,247,0.45)' }} title={`${t("vmLxc.idle")} ${formatStorage(idleGB)}`}></div>
                </div>
                <div className="mt-2 flex justify-between text-sm text-muted-foreground">
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full" style={{ background: stroke }}></span>{t("vmLxc.used")} {formatStorage(usedGB)}</span>
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full" style={{ background: 'rgba(168,85,247,0.55)' }}></span>{t("vmLxc.allocated")} {formatStorage(allocGB)}</span>
                </div>
              </CardContent>
            </Card>
          )
        })()}
      </div>

      <Card className="bg-card border-border">
        <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-xl lg:text-2xl font-bold text-foreground">
            <Server className="h-6 w-6" />
            {t("vmLxc.listTitle")}
          </CardTitle>
          <div
            role="tablist"
            aria-label="Filter by status"
            className="inline-flex w-full sm:w-auto rounded-lg border border-border bg-muted/40 p-1 gap-1"
          >
            {(["all", "running", "stopped"] as const).map((key) => {
              const active = statusFilter === key
              const label = key === "all" ? "All" : key === "running" ? "Running" : "Stopped"
              // Icon color: white when the tab is active (over the blue fill);
              // green / red on inactive tabs so the state mapping stays legible
              // before selection. The black-text variant was tested and dropped
              // — white reads cleaner alongside the sidebar/nav blue treatment.
              const iconClass = active
                ? "h-3.5 w-3.5 text-white"
                : key === "running"
                  ? "h-3.5 w-3.5 text-green-500 fill-green-500/25"
                  : "h-3.5 w-3.5 text-red-500 fill-red-500/25"
              return (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setStatusFilter(key)}
                  className={`flex-1 sm:flex-none inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    active
                      ? "bg-blue-500 text-white shadow-sm"
                      : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                  }`}
                >
                  {key === "running" && <Play className={iconClass} />}
                  {key === "stopped" && <Square className={iconClass} />}
                  <span>{label}</span>
                  <span className={`ml-0.5 text-xs tabular-nums ${active ? "text-white/80" : "opacity-70"}`}>
                    {statusCounts[key]}
                  </span>
                </button>
              )
            })}
          </div>
        </CardHeader>
        <CardContent>
          {safeVMData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">{t("vmLxc.empty")}</div>
          ) : filteredVMs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No {statusFilter === "running" ? "running" : "stopped"} virtual machines
            </div>
          ) : (
            <div className="space-y-3">
              {filteredVMs.map((vm) => {
                const cpuPercent = (vm.cpu * 100).toFixed(1)
                const memPercent = vm.maxmem > 0 ? ((vm.mem / vm.maxmem) * 100).toFixed(1) : "0"
                const memGB = (vm.mem / 1024 ** 3).toFixed(1)
                const maxMemGB = (vm.maxmem / 1024 ** 3).toFixed(1)
                const diskPercent = vm.maxdisk > 0 ? ((vm.disk / vm.maxdisk) * 100).toFixed(1) : "0"
                const diskGB = (vm.disk / 1024 ** 3).toFixed(1)
                const maxDiskGB = (vm.maxdisk / 1024 ** 3).toFixed(1)
                const typeBadge = getTypeBadge(vm.type)
                const lxcIP = vm.type === "lxc" ? vmConfigs[vm.vmid] : null

                return (
                  <div key={vm.vmid}>
                    <div
                      className="hidden sm:block p-4 rounded-lg border border-border bg-card hover:bg-black/5 dark:hover:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => handleVMClick(vm)}
                    >
                      <div className="flex items-center gap-2 flex-wrap mb-3">
                        <Badge variant="outline" className={`flex-shrink-0 ${getStatusColor(vm.status)}`}>
                          {getStatusIcon(vm.status)}
                          {getStatusLabel(vm.status)}
                        </Badge>
                        <Badge variant="outline" className={`flex-shrink-0 ${typeBadge.color}`}>
                          {typeBadge.icon}
                          {typeBadge.label}
                        </Badge>
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-foreground truncate">
                            {vm.name}
                            <span className="hidden lg:inline text-sm text-muted-foreground ml-2">ID: {vm.vmid}</span>
                          </div>
                          <div className="text-[10px] text-muted-foreground lg:hidden">ID: {vm.vmid}</div>
                        </div>
                        {lxcIP && (
                          <span className={`text-sm ${lxcIP === "DHCP" ? "text-yellow-500" : "text-green-500"}`}>
                            IP: {lxcIP}
                          </span>
                        )}
                        <span className="text-sm text-muted-foreground ml-auto">
                          {t("vmLxc.uptime", { uptime: formatUptime(vm.uptime, t) })}
                        </span>
                        {vm.type === "lxc" && renderLxcUpdateBadge(vm.update_check)}
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.cpuUsage")}</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("cpu") // undeclared variable fix
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(cpuPercent))}`}
                            >
                              {cpuPercent}%
                            </div>
                            <Progress
                              value={Number.parseFloat(cpuPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(cpuPercent))}`}
                            />
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.memory")}</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("memory")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(memPercent))}`}
                            >
                              {memGB} / {maxMemGB} GB
                            </div>
                            <Progress
                              value={Number.parseFloat(memPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(memPercent))}`}
                            />
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.diskUsage")}</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("disk")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(diskPercent))}`}
                            >
                              {diskGB} / {maxDiskGB} GB
                            </div>
                            <Progress
                              value={Number.parseFloat(diskPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(diskPercent))}`}
                            />
                          </div>
                        </div>

                        <div className="hidden md:block">
                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.diskIo")}</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.diskread, false)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.diskwrite, false)}</span>
                            </div>
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.networkIo")}</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.netin, true)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.netout, true)}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div
                      className="sm:hidden p-4 rounded-lg border border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => handleVMClick(vm)}
                    >
                      <div className="flex items-center gap-3">
                        {vm.status === "running" ? (
                          <Play className="h-5 w-5 text-green-500 fill-current flex-shrink-0" />
                        ) : (
                          <Square className="h-5 w-5 text-red-500 fill-current flex-shrink-0" />
                        )}

                        <Badge variant="outline" className={`${getTypeBadge(vm.type).color} flex-shrink-0`}>
                          {getTypeBadge(vm.type).label}
                        </Badge>

                        {/* Name and ID */}
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-foreground truncate flex items-center gap-1.5">
                            <span className="truncate">{vm.name}</span>
                            {vm.type === "lxc" && renderLxcUpdateBadge(vm.update_check, true)}
                          </div>
                          <div className="text-[10px] text-muted-foreground">ID: {vm.vmid}</div>
                        </div>

                        <div className="flex items-center gap-3 flex-shrink-0">
                          {/* CPU icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{cpuPercent}%</span>
                            )}
                            <Cpu
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getUsageColor(Number.parseFloat(cpuPercent))
                              }`}
                            />
                          </div>

                          {/* Memory icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{memPercent}%</span>
                            )}
                            <MemoryStick
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getUsageColor(Number.parseFloat(memPercent))
                              }`}
                            />
                          </div>

                          {/* Disk icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{diskPercent}%</span>
                            )}
                            <HardDrive
                              className={`h-4 w-4 ${
                                vm.status === "stopped"
                                  ? "text-gray-500"
                                  : getUsageColor(Number.parseFloat(diskPercent))
                              }`}
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={!!selectedVM}
        onOpenChange={() => {
          setSelectedVM(null)
          setVMDetails(null)
          setCurrentView("main")
          setSelectedMetric(null)
          setShowAdditionalInfo(false)
          setShowNotes(false)
          setIsEditingNotes(false)
          setEditedNotes("")
          setActiveModalTab("status")
        }}
      >
        <DialogContent
          className={`max-w-4xl flex flex-col p-0 overflow-hidden ${
            isStandalone 
              ? "h-[95vh] sm:h-[90vh]" 
              : "h-[85vh] sm:h-[85vh] max-h-[calc(100dvh-env(safe-area-inset-top)-env(safe-area-inset-bottom)-40px)]"
          }`}
          key={selectedVM?.vmid || "no-vm"}
        >
          {currentView === "main" ? (
            <>
              <DialogHeader className="pb-4 border-b border-border px-6 pt-6">
                <DialogTitle className="flex flex-col gap-3">
                  {/* Desktop layout: Uptime now appears after status badge */}
                  <div className="hidden sm:flex items-center gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 flex-shrink-0" />
                      <span className="text-lg truncate">{selectedVM?.name}</span>
                      {selectedVM && <span className="text-sm text-muted-foreground">ID: {selectedVM.vmid}</span>}
                    </div>
                    {selectedVM && (
                      <>
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                            {getTypeBadge(selectedVM.type).icon}
                            {getTypeBadge(selectedVM.type).label}
                          </Badge>
                          <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                            {getStatusLabel(selectedVM.status)}
                          </Badge>
                          {selectedVM.status === "running" && (
                            <span className="text-sm text-muted-foreground">
                              {t("vmLxc.uptime", { uptime: formatUptime(selectedVM.uptime, t) })}
                            </span>
                          )}
                          {/* Clickable badge — the sole entry point to
                              the Updates panel now that the tab is no
                              longer in the nav. Full-size so it reads
                              at the same weight as the surrounding
                              Uptime / Type / Status chips. */}
                          {selectedVM.type === "lxc" &&
                            renderLxcUpdateBadge(
                              selectedVM.update_check,
                              false,
                              () => setActiveModalTab("updates"),
                            )}
                          {/* Header badges — one per user-registered
                              app (skip managed entries; those surface
                              from Security → Secure Gateway). Docker
                              apps have no version to show but still
                              render as a name chip so users see them
                              at a glance. Capped at 3 to keep the
                              row honest on narrow viewports. */}
                          {selectedVM.type === "lxc" &&
                            (selectedVM.app_watches || [])
                              .filter((a) => !a.managed_oci_app_id)
                              .slice(0, 3)
                              .map((a) => (
                                <span key={a.id}>
                                  {renderLxcAppBadge(a, false, () => setActiveModalTab("app"))}
                                </span>
                              ))}
                        </div>
                      </>
                    )}
                  </div>
                  {/* Mobile layout unchanged */}
                  <div className="sm:hidden flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 flex-shrink-0" />
                      <span className="text-lg truncate">{selectedVM?.name}</span>
                      {selectedVM && <span className="text-sm text-muted-foreground">ID: {selectedVM.vmid}</span>}
                    </div>
                    {selectedVM && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                          {getTypeBadge(selectedVM.type).icon}
                          {getTypeBadge(selectedVM.type).label}
                        </Badge>
                        <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                          {getStatusLabel(selectedVM.status)}
                        </Badge>
                        {selectedVM.status === "running" && (
                          <span className="text-sm text-muted-foreground">
                            {t("vmLxc.uptime", { uptime: formatUptime(selectedVM.uptime, t) })}
                          </span>
                        )}
                        {selectedVM.type === "lxc" &&
                          renderLxcUpdateBadge(
                            selectedVM.update_check,
                            false,
                            () => setActiveModalTab("updates"),
                          )}
                      </div>
                    )}
                  </div>
                </DialogTitle>
              </DialogHeader>

              {/* Tab Navigation.
                  Mobile UX:
                   • Only the active tab shows its label; the rest
                     collapse to icon-only so 4-5 tabs fit on a phone.
                   • Per-tab padding + gap shrink on narrow viewports
                     (`px-2.5 sm:px-4`, `gap-1.5 sm:gap-2`) so even with
                     two badges showing counts the row doesn't overflow.
                   • Container has `overflow-x-auto` as a safety net —
                     a CT with all tabs active (Mounts + Backups +
                     Updates + Firewall) on a very narrow phone can
                     still horizontally scroll the row instead of
                     clipping the last tab off-screen.
                   • Badges stay visible in both states so the user
                     still sees "9 backups" at a glance even when that
                     tab isn't active. */}
              <div className="flex border-b border-border px-3 sm:px-6 shrink-0 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
                <button
                  onClick={() => setActiveModalTab("status")}
                  className={`flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap shrink-0 ${
                    activeModalTab === "status"
                      ? "border-cyan-500 text-cyan-500"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Activity className="h-4 w-4" />
                  <span className={activeModalTab === "status" ? "" : "hidden sm:inline"}>
                    {t("vmLxc.tabs.status")}
                  </span>
                </button>
                {/* App tab — user-registered application metadata +
                    upstream version watch. Placed right after Status so
                    the operator's mental flow is "state → what's inside
                    → what needs updating → mounts/backups/firewall". */}
                {selectedVM?.type === "lxc" && (
                  <button
                    onClick={() => setActiveModalTab("app")}
                    className={`flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap shrink-0 ${
                      activeModalTab === "app"
                        ? "border-emerald-500 text-emerald-500"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Package className="h-4 w-4" />
                    <span className={activeModalTab === "app" ? "" : "hidden sm:inline"}>
                      App
                    </span>
                    {(selectedVM.app_watches || []).some(
                      (a) => a.update_available && !a.managed_oci_app_id,
                    ) && (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 ml-0.5" title="Update available" />
                    )}
                  </button>
                )}
                {/* Updates tab — LXC only, always visible so users can
                    trigger a check-now anytime; empty state renders
                    inside. Mobile UX collapses inactive tabs to
                    icon-only so the row doesn't overflow. */}
                {selectedVM?.type === "lxc" && (
                  <button
                    onClick={() => setActiveModalTab("updates")}
                    className={`flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap shrink-0 ${
                      activeModalTab === "updates"
                        ? "border-purple-500 text-purple-500"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <RefreshCw className="h-4 w-4" />
                    <span className={activeModalTab === "updates" ? "" : "hidden sm:inline"}>
                      {t("vmLxc.tabs.updates")}
                    </span>
                    {typeof selectedVM.update_check?.count === "number" && selectedVM.update_check.count > 0 && (
                      <Badge variant="secondary" className="text-xs h-5 ml-0.5 sm:ml-1">
                        {selectedVM.update_check.count}
                      </Badge>
                    )}
                  </button>
                )}
                {/* Sprint 13.29: Mount Points tab — LXC only, and only
                    when at least one mp / ad-hoc remote mount exists. */}
                {selectedVM?.type === "lxc" && (mountPoints.length > 0 || adHocMounts.length > 0) && (
                  <button
                    onClick={() => setActiveModalTab("mounts")}
                    className={`flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap shrink-0 ${
                      activeModalTab === "mounts"
                        ? "border-blue-500 text-blue-500"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <HardDrive className="h-4 w-4" />
                    <span className={activeModalTab === "mounts" ? "" : "hidden sm:inline"}>
                      {t("vmLxc.tabs.mounts")}
                    </span>
                    <Badge variant="secondary" className="text-xs h-5 ml-0.5 sm:ml-1">
                      {mountPoints.length + adHocMounts.length}
                    </Badge>
                  </button>
                )}
                <button
                  onClick={() => setActiveModalTab("backups")}
                  className={`flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap shrink-0 ${
                    activeModalTab === "backups"
                      ? "border-amber-500 text-amber-500"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Archive className="h-4 w-4" />
                  <span className={activeModalTab === "backups" ? "" : "hidden sm:inline"}>
                    {t("vmLxc.tabs.backups")}
                  </span>
                  {vmBackups.length > 0 && (
                    <Badge variant="secondary" className="text-xs h-5 ml-0.5 sm:ml-1">{vmBackups.length}</Badge>
                  )}
                </button>
                {/* Firewall tab — issue #14554 from the helper-scripts
                    discussions ("view individual VM/CT firewall logs").
                    Always rendered for VMs and CTs; if the guest doesn't
                    have firewall enabled in PVE, the panel shows a
                    callout explaining how to turn it on. Log fetched
                    lazily on first click to avoid hitting pvesh on
                    every modal open. */}
                {selectedVM && (
                  <button
                    onClick={() => {
                      setActiveModalTab("firewall")
                      fetchFirewallLog(selectedVM.vmid)
                    }}
                    className={`flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap shrink-0 ${
                      activeModalTab === "firewall"
                        ? "border-orange-500 text-orange-500"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Shield className="h-4 w-4" />
                    <span className={activeModalTab === "firewall" ? "" : "hidden sm:inline"}>
                      {t("vmLxc.tabs.firewall")}
                    </span>
                  </button>
                )}
              </div>

              <div className="flex-1 overflow-y-auto px-6 py-4 min-h-0">
                {/* Status Tab */}
                {activeModalTab === "status" && (
                <div className="space-y-4">
                  {selectedVM && (
                    <>
                      <div key={`metrics-${selectedVM.vmid}`}>
                        <Card
                          className="cursor-pointer rounded-lg border border-black/10 dark:border-white/10 sm:border-border max-sm:bg-black/5 max-sm:dark:bg-white/5 sm:bg-card sm:hover:bg-black/5 sm:dark:hover:bg-white/5 transition-colors group"
                          onClick={handleMetricsClick}
                        >
                          <CardContent className="p-4">
                            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                              {/* CPU Usage */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <Cpu className="h-3.5 w-3.5" />
                                  <span>{t("vmLxc.cpuUsage")}</span>
                                  {vmDetails?.config?.cores && (
                                    <span className="text-muted-foreground/60">
                                      ({formatCoreCount(Number(vmDetails.config.cores))})
                                    </span>
                                  )}
                                </div>
                                <div className={`text-base font-semibold mb-2 ${getUsageColor(selectedVM.cpu * 100)}`}>
                                  {(selectedVM.cpu * 100).toFixed(1)}%
                                </div>
                                <Progress
                                  value={selectedVM.cpu * 100}
                                  className={`h-2 max-sm:bg-background sm:group-hover:bg-background/50 transition-colors ${getModalProgressColor(selectedVM.cpu * 100)}`}
                                />
                              </div>

                              {/* Memory */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <MemoryStick className="h-3.5 w-3.5" />
                                  <span>{t("vmLxc.memory")}</span>
                                </div>
                                <div
                                  className={`text-base font-semibold mb-2 ${getUsageColor((selectedVM.mem / selectedVM.maxmem) * 100)}`}
                                >
                                  {(selectedVM.mem / 1024 ** 3).toFixed(1)} /{" "}
                                  {(selectedVM.maxmem / 1024 ** 3).toFixed(1)} GB
                                </div>
                                <Progress
                                  value={(selectedVM.mem / selectedVM.maxmem) * 100}
                                  className={`h-2 max-sm:bg-background sm:group-hover:bg-background/50 transition-colors ${getModalProgressColor((selectedVM.mem / selectedVM.maxmem) * 100)}`}
                                />
                              </div>

                              {/* Disk */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <HardDrive className="h-3.5 w-3.5" />
                                  <span>{t("vmLxc.disk")}</span>
                                </div>
                                <div
                                  className={`text-base font-semibold mb-2 ${getUsageColor((selectedVM.disk / selectedVM.maxdisk) * 100)}`}
                                >
                                  {(selectedVM.disk / 1024 ** 3).toFixed(1)} /{" "}
                                  {(selectedVM.maxdisk / 1024 ** 3).toFixed(1)} GB
                                </div>
                                <Progress
                                  value={(selectedVM.disk / selectedVM.maxdisk) * 100}
                                  className={`h-2 max-sm:bg-background sm:group-hover:bg-background/50 transition-colors ${getModalProgressColor((selectedVM.disk / selectedVM.maxdisk) * 100)}`}
                                />
                              </div>

                              {/* Disk I/O — cumulative counters from Proxmox
                                  API: bytes read/written since the VM/LXC
                                  was last started, not a per-period rate. */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <HardDrive className="h-3.5 w-3.5" />
                                  <span>{t("vmLxc.diskIo")} <span className="text-[10px] opacity-70">({t("vmLxc.sinceBoot")})</span></span>
                                </div>
                                <div className="space-y-1">
                                  <div className="text-sm text-green-500 flex items-center gap-1">
                                    <span>↓</span>
                                    <span>{((selectedVM.diskread || 0) / 1024 ** 2).toFixed(2)} MB</span>
                                  </div>
                                  <div className="text-sm text-blue-500 flex items-center gap-1">
                                    <span>↑</span>
                                    <span>{((selectedVM.diskwrite || 0) / 1024 ** 2).toFixed(2)} MB</span>
                                  </div>
                                </div>
                              </div>

                              {/* Network I/O — cumulative counters from
                                  Proxmox API: bytes in/out since the VM/LXC
                                  was last started. */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <Network className="h-3.5 w-3.5" />
                                  <span>{t("vmLxc.networkIo")} <span className="text-[10px] opacity-70">({t("vmLxc.sinceBoot")})</span></span>
                                </div>
                                <div className="space-y-1">
                                  <div className="text-sm text-green-500 flex items-center gap-1">
                                    <span>↓</span>
                                    <span>{formatNetworkTraffic(selectedVM.netin || 0, networkUnit)}</span>
                                  </div>
                                  <div className="text-sm text-blue-500 flex items-center gap-1">
                                    <span>↑</span>
                                    <span>{formatNetworkTraffic(selectedVM.netout || 0, networkUnit)}</span>
                                  </div>
                                </div>
                              </div>

                              <div className="flex items-center justify-center">
                                {getOSIcon(vmDetails?.os_info, selectedVM.type)}
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      </div>

                      {detailsLoading ? (
                        <div className="text-center py-8 text-muted-foreground">{t("vmLxc.loadingConfiguration")}</div>
                      ) : vmDetails?.config ? (
                        <>
                          <Card className="border border-border bg-card/50" key={`config-${selectedVM.vmid}`}>
                            <CardContent className="p-4">
                              <div className="flex items-center justify-between mb-4">
                                <div className="flex items-center gap-2">
                                  <div className="p-1.5 rounded-md bg-blue-500/10">
                                    <Cpu className="h-4 w-4 text-blue-500" />
                                  </div>
                                  <h3 className="text-sm font-semibold text-foreground">{t("vmLxc.resources")}</h3>
                                </div>
                                <div className="flex gap-2">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowNotes(!showNotes)}
                                    className="text-xs max-sm:bg-black/5 max-sm:dark:bg-white/5 sm:bg-transparent sm:hover:bg-black/5 sm:dark:hover:bg-white/5"
                                  >
                                    {showNotes ? (
                                      <>
                                        <ChevronUp className="h-3 w-3 mr-1" />
                                        {t("vmLxc.hideNotes")}
                                      </>
                                    ) : (
                                      <>
                                        <ChevronDown className="h-3 w-3 mr-1" />
                                        {t("vmLxc.notes")}
                                      </>
                                    )}
                                  </Button>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowAdditionalInfo(!showAdditionalInfo)}
                                    className="text-xs max-sm:bg-black/5 max-sm:dark:bg-white/5 sm:bg-transparent sm:hover:bg-black/5 sm:dark:hover:bg-white/5"
                                  >
                                    {showAdditionalInfo ? (
                                      <>
                                        <ChevronUp className="h-3 w-3 mr-1" />
                                        {t("vmLxc.lessInfo")}
                                      </>
                                    ) : (
                                      <>
                                        <ChevronDown className="h-3 w-3 mr-1" />
                                        + {t("vmLxc.info")}
                                      </>
                                    )}
                                  </Button>
                                </div>
                              </div>

                              <div className="grid grid-cols-3 lg:grid-cols-4 gap-3 lg:gap-4">
                                {vmDetails.config.cores && (
                                  <div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                                      <Cpu className="h-3.5 w-3.5" />
                                      <span>{t("vmLxc.cpuCores")}</span>
                                    </div>
                                    <div className="font-semibold text-blue-500">{vmDetails.config.cores}</div>
                                  </div>
                                )}
                                {vmDetails.config.memory && (
                                  <div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                                      <MemoryStick className="h-3.5 w-3.5" />
                                      <span>{t("vmLxc.memory")}</span>
                                    </div>
                                    <div className="font-semibold text-blue-500">{vmDetails.config.memory} MB</div>
                                  </div>
                                )}
                                {vmDetails.config.swap !== undefined && (
                                  <div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                                      <RotateCcw className="h-3.5 w-3.5" />
                                      <span>{t("vmLxc.details.swap")}</span>
                                    </div>
                                    <div className="font-semibold text-foreground">{vmDetails.config.swap} MB</div>
                                  </div>
                                )}
                              </div>

                              {/* IP Addresses with proper keys */}
                              {selectedVM?.type === "lxc" && vmDetails?.lxc_ip_info && (
                                <div className="mt-4 lg:mt-6 pt-4 lg:pt-6 border-t border-border">
                                  <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                    <Network className="h-4 w-4" />
                                    {t("vmLxc.ipAddresses")}
                                  </h4>
                                  <div className="flex flex-wrap gap-2">
                                    {vmDetails.lxc_ip_info.real_ips.map((ip, index) => (
                                      <Badge
                                        key={`real-ip-${selectedVM.vmid}-${ip.replace(/[.:/]/g, "-")}-${index}`}
                                        variant="outline"
                                        className="bg-green-500/10 text-green-500 border-green-500/20"
                                      >
                                        {ip}
                                      </Badge>
                                    ))}
                                    {vmDetails.lxc_ip_info.docker_ips.map((ip, index) => (
                                      <Badge
                                        key={`docker-ip-${selectedVM.vmid}-${ip.replace(/[.:/]/g, "-")}-${index}`}
                                        variant="outline"
                                        className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                      >
                                        {ip} ({t("vmLxc.details.bridge")})
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {showNotes && (
                                <div className="mt-6 pt-6 border-t border-border">
                                  <div className="flex items-center justify-between mb-3">
                                    <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                                      {t("vmLxc.notes")}
                                    </h4>
                                    {!isEditingNotes && (
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={handleEditNotes}
                                        className="text-xs bg-transparent"
                                      >
                                        {t("vmLxc.editNotes")}
                                      </Button>
                                    )}
                                  </div>
                                  <div className="bg-muted/50 p-4 rounded-lg">
                                    {isEditingNotes ? (
                                      <div className="space-y-3">
                                        <textarea
                                          value={editedNotes}
                                          onChange={(e) => setEditedNotes(e.target.value)}
                                          className="w-full min-h-[200px] p-3 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                                          placeholder={t("vmLxc.enterNotes")}
                                        />
                                        <div className="flex gap-2 justify-end">
                                          <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={handleCancelEditNotes}
                                            disabled={savingNotes}
                                          >
                                            {t("actions.cancel")}
                                          </Button>
                                          <Button
                                            size="sm"
                                            onClick={handleSaveNotes}
                                            disabled={savingNotes}
                                            className="bg-blue-600 hover:bg-blue-700 text-white"
                                          >
                                            {savingNotes ? t("vmLxc.savingNotes") : t("actions.save")}
                                          </Button>
                                        </div>
                                      </div>
                                    ) : vmDetails.config.description ? (
                                      <>
                                        {(() => {
                                          // VM/CT notes come in two flavours and we mirror the way
                                          // the PVE web UI handles each:
                                          //   • HTML (ProxMenux/community-script helper output with
                                          //     <div align='center'>, tables, logos) → render the
                                          //     HTML verbatim. The stable `main` branch did exactly
                                          //     this with dangerouslySetInnerHTML — we keep that
                                          //     behaviour but pipe through DOMPurify so the audit
                                          //     Tier 2 #13 XSS sink stays closed.
                                          //   • Plain text / markdown (e.g. qBittorrent's
                                          //     `## qBittorrent LXC`) → marked turns it into
                                          //     headings + autolinks + line breaks, matching PVE.
                                          // Mixing the two paths breaks the HTML one because marked
                                          // collapses indentation / wraps inline runs and the
                                          // browser then ignores `align="center"`.
                                          let decoded: string
                                          try {
                                            decoded = decodeRecursively(vmDetails.config.description)
                                          } catch {
                                            return (
                                              <div className="text-sm text-red-500">
                                                {t("vmLxc.notesDecodeError")}
                                              </div>
                                            )
                                          }
                                          const looksLikeHtml = /<\/?[a-z][\s\S]*?>/i.test(decoded)
                                          let html: string
                                          if (looksLikeHtml) {
                                            html = decoded
                                          } else {
                                            try {
                                              html = marked.parse(decoded, {
                                                breaks: true,
                                                gfm: true,
                                                async: false,
                                              }) as string
                                            } catch {
                                              html = decoded.replace(/\n/g, "<br>")
                                            }
                                          }
                                          // Promote legacy `align` HTML attribute to a real inline
                                          // `style="text-align: …"` rule. Tailwind / parent CSS,
                                          // styled-jsx scoping quirks and Safari's UA stylesheet
                                          // can all swallow the bare `align` attribute on `<div>`
                                          // (it's HTML4 obsolete syntax). An inline style is
                                          // bullet-proof: highest specificity, no scope hash needed.
                                          DOMPurify.removeHook("afterSanitizeAttributes")
                                          DOMPurify.addHook("afterSanitizeAttributes", (node: Element) => {
                                            const a = node.getAttribute?.("align")
                                            if (a && /^(center|left|right)$/i.test(a)) {
                                              const cur = node.getAttribute("style") || ""
                                              const sep = cur && !cur.trim().endsWith(";") ? "; " : ""
                                              node.setAttribute(
                                                "style",
                                                `${cur}${sep}text-align: ${a.toLowerCase()}`,
                                              )
                                            }
                                            // Force `target=_blank` links to open in a new tab
                                            // safely (noopener prevents reverse-tabnabbing).
                                            if (node.tagName === "A" && node.getAttribute("target") === "_blank") {
                                              node.setAttribute("rel", "noopener noreferrer")
                                            }
                                          })
                                          const cleanHtml = DOMPurify.sanitize(html, {
                                            ALLOWED_TAGS: [
                                              "a", "p", "br", "div", "span",
                                              "h1", "h2", "h3", "h4", "h5", "h6",
                                              "img",
                                              "table", "thead", "tbody", "tr", "th", "td",
                                              "ul", "ol", "li",
                                              "strong", "em", "b", "i", "u", "code", "pre",
                                              "blockquote", "hr",
                                              "small", "sub", "sup",
                                            ],
                                            ALLOWED_ATTR: [
                                              "href", "src", "alt", "title", "target",
                                              "rel", "style", "class",
                                              "align", "width", "height",
                                              "colspan", "rowspan",
                                            ],
                                            ALLOWED_URI_REGEXP:
                                              /^(?:(?:https?|mailto|data:image\/(?:png|jpeg|jpg|gif|svg\+xml|webp)):|\/|#)/i,
                                            ADD_ATTR: ["target"],
                                          })
                                          return (
                                            <div
                                              className="text-sm text-foreground proxmenux-notes break-words"
                                              // eslint-disable-next-line react/no-danger
                                              dangerouslySetInnerHTML={{ __html: cleanHtml }}
                                            />
                                          )
                                        })()}
                                      </>
                                    ) : (
                                      <div className="text-sm text-muted-foreground italic">
                                        {t("vmLxc.noNotes")}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}

                              {showAdditionalInfo && (
                                <div className="mt-6 pt-6 border-t border-border space-y-6">
                                  {selectedVM?.type === "lxc" && vmDetails?.hardware_info && (
                                    <div>
                                      <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        <Container className="h-4 w-4" />
                                        {t("vmLxc.containerConfiguration")}
                                      </h4>
                                      <div className="space-y-4">
                                        {/* Privileged Status */}
                                        {vmDetails.hardware_info.privileged !== null &&
                                          vmDetails.hardware_info.privileged !== undefined && (
                                            <div>
                                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                                <Shield className="h-3.5 w-3.5" />
                                                <span>{t("vmLxc.details.privilegeLevel")}</span>
                                              </div>
                                              <Badge
                                                variant="outline"
                                                className={
                                                  vmDetails.hardware_info.privileged
                                                    ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                                    : "bg-green-500/10 text-green-500 border-green-500/20"
                                                }
                                              >
                                                {vmDetails.hardware_info.privileged ? t("vmLxc.details.privileged") : t("vmLxc.details.unprivileged")}
                                              </Badge>
                                            </div>
                                          )}

                                        {/* GPU Passthrough with proper keys */}
                                        {vmDetails.hardware_info.gpu_passthrough &&
                                          vmDetails.hardware_info.gpu_passthrough.length > 0 && (
                                            <div>
                                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                                <Cpu className="h-3.5 w-3.5" />
                                                <span>{t("vmLxc.details.gpuPassthrough")}</span>
                                              </div>
                                              <div className="flex flex-wrap gap-2">
                                                {vmDetails.hardware_info.gpu_passthrough.map((gpu, index) => (
                                                  <Badge
                                                    key={`gpu-${selectedVM.vmid}-${index}-${gpu.replace(/[^a-zA-Z0-9]/g, "-").substring(0, 30)}`}
                                                    variant="outline"
                                                    className={
                                                      gpu.includes("NVIDIA")
                                                        ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                        : "bg-purple-500/10 text-purple-500 border-purple-500/20"
                                                    }
                                                  >
                                                    {gpu}
                                                  </Badge>
                                                ))}
                                              </div>
                                            </div>
                                          )}

                                        {/* Hardware Devices with proper keys */}
                                        {vmDetails.hardware_info.devices &&
                                          vmDetails.hardware_info.devices.length > 0 && (
                                            <div>
                                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                                <Server className="h-3.5 w-3.5" />
                                                <span>{t("vmLxc.details.hardwareDevices")}</span>
                                              </div>
                                              <div className="flex flex-wrap gap-2">
                                                {vmDetails.hardware_info.devices.map((device, index) => (
                                                  <Badge
                                                    key={`device-${selectedVM.vmid}-${index}-${device.replace(/[^a-zA-Z0-9]/g, "-").substring(0, 30)}`}
                                                    variant="outline"
                                                    className="bg-blue-500/10 text-blue-500 border-blue-500/20"
                                                  >
                                                    {device}
                                                  </Badge>
                                                ))}
                                              </div>
                                            </div>
                                          )}
                                      </div>
                                    </div>
                                  )}

                                  {/* Hardware Section */}
                                  <div>
                                    <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      <Settings2 className="h-4 w-4" />
                                      {t("vmLxc.details.hardware")}
                                    </h4>
                                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                                      {vmDetails.config.sockets && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.cpuSockets")}</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.sockets}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.cpu && (
                                        <div className="col-span-2">
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.cpuType")}</div>
                                          <div className="font-medium text-foreground text-sm font-mono">
                                            {vmDetails.config.cpu}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.numa !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.numa")}</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.numa
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.numa ? t("vmLxc.details.enabled") : t("vmLxc.details.disabled")}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.bios && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.bios")}</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.bios}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.machine && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.machineType")}</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.machine}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.vga && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.vga")}</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.vga}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.agent !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.qemuAgent")}</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.agent
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.agent ? t("vmLxc.details.enabled") : t("vmLxc.details.disabled")}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.tablet !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.tabletPointer")}</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.tablet
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.tablet ? t("vmLxc.details.enabled") : t("vmLxc.details.disabled")}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.localtime !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.localTime")}</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.localtime
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.localtime ? t("vmLxc.details.enabled") : t("vmLxc.details.disabled")}
                                          </Badge>
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  {/* Storage Section — human-readable breakdown
                                      per disk plus the raw config string in a
                                      collapsible details block, mirroring the
                                      Network section. */}
                                  {(() => {
                                    // Parse a Proxmox disk config string into
                                    //   { storage, volume, path, options }
                                    // Handles both LVM-style volumes
                                    // "local-lvm:vm-101-disk-0,size=6G" and
                                    // passthrough paths "/dev/disk/by-id/...".
                                    const parseDisk = (raw: string) => {
                                      const parts = raw.split(",")
                                      const first = parts[0] || ""
                                      const options: Record<string, string> = {}
                                      parts.slice(1).forEach((p) => {
                                        const eq = p.indexOf("=")
                                        if (eq > 0) {
                                          options[p.slice(0, eq).trim()] = p.slice(eq + 1).trim()
                                        }
                                      })
                                      let storage = "", volume = "", path = ""
                                      if (first.startsWith("/")) {
                                        path = first
                                      } else if (first.includes(":")) {
                                        const [s, v] = first.split(":")
                                        storage = s
                                        volume = v
                                      } else {
                                        volume = first
                                      }
                                      return { storage, volume, path, options }
                                    }
                                    // Convert Proxmox size strings ("6G",
                                    // "3907018584K", "40G", "4M") to a
                                    // consistent GB/TB display.
                                    const humanSize = (s: string): string => {
                                      if (!s) return ""
                                      const m = s.match(/^(\d+(?:\.\d+)?)([KMGT])?$/i)
                                      if (!m) return s
                                      const n = parseFloat(m[1])
                                      const unit = (m[2] || "").toUpperCase()
                                      const bytes =
                                        unit === "K" ? n * 1024 :
                                        unit === "M" ? n * 1024 ** 2 :
                                        unit === "G" ? n * 1024 ** 3 :
                                        unit === "T" ? n * 1024 ** 4 : n
                                      if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(2)} TB`
                                      if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(bytes < 10 * 1024 ** 3 ? 1 : 0)} GB`
                                      if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
                                      return s
                                    }
                                    const DField = ({ label, value, mono, className }:
                                      { label: string; value: string; mono?: boolean; className?: string }) => (
                                      <div className="flex flex-col gap-0.5">
                                        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
                                        <span className={`text-foreground ${mono ? "font-mono text-xs" : "text-sm"} ${className || ""}`}>{value}</span>
                                      </div>
                                    )
                                    const renderDisk = (label: string, raw: string, keyId: string) => {
                                      const d = parseDisk(raw)
                                      return (
                                        <div key={keyId} className="bg-muted/30 rounded-md p-3 space-y-3">
                                          <div className="flex items-center gap-2 flex-wrap">
                                            <HardDrive className="h-4 w-4 text-purple-500 flex-shrink-0" />
                                            <span className="text-sm font-semibold text-foreground">{label}</span>
                                            {d.storage && (
                                              <span className="text-xs text-orange-500 font-mono">
                                                {d.storage}
                                              </span>
                                            )}
                                            {d.options.size && (
                                              <span className="text-xs text-cyan-500 font-mono">
                                                {humanSize(d.options.size)}
                                              </span>
                                            )}
                                          </div>
                                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
                                            {d.volume && <DField label={t("vmLxc.details.volume")} value={d.volume} mono />}
                                            {d.path && <DField label={t("vmLxc.details.path")} value={d.path} mono className="break-all" />}
                                            {d.options.ssd === "1" && <DField label={t("vmLxc.details.media")} value="SSD" />}
                                            {d.options.discard && <DField label={t("vmLxc.details.discard")} value={d.options.discard} />}
                                            {d.options.iothread === "1" && <DField label="IOThread" value={t("vmLxc.details.on")} />}
                                            {d.options.cache && <DField label={t("vmLxc.details.cache")} value={d.options.cache} />}
                                            {d.options.aio && <DField label="AIO" value={d.options.aio} />}
                                            {d.options.backup === "0" && <DField label={t("vmLxc.details.backup")} value={t("vmLxc.details.excluded")} className="text-red-500" />}
                                            {d.options.backup === "1" && <DField label={t("vmLxc.details.backup")} value={t("vmLxc.details.included")} />}
                                            {d.options.replicate === "0" && <DField label={t("vmLxc.details.replicate")} value={t("vmLxc.details.off")} />}
                                            {d.options.efitype && <DField label={t("vmLxc.details.efiType")} value={d.options.efitype} />}
                                            {d.options.pre_enrolled_keys && <DField label={t("vmLxc.details.preEnrolledKeys")} value={d.options.pre_enrolled_keys} />}
                                            {d.options.serial && <DField label={t("vmLxc.details.serial")} value={d.options.serial} mono />}
                                            {d.options.mp && <DField label={t("vmLxc.details.mountPoint")} value={d.options.mp} mono />}
                                            {d.options.acl && <DField label="ACL" value={d.options.acl} />}
                                          </div>
                                          <details className="text-xs">
                                            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("vmLxc.details.rawConfig")}</summary>
                                            <div className="mt-1 font-mono text-foreground break-all bg-background/50 p-2 rounded">
                                              {raw}
                                            </div>
                                          </details>
                                        </div>
                                      )
                                    }
                                    return (
                                      <div>
                                        <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                          <HardDrive className="h-4 w-4" />
                                          {t("vmLxc.details.storage")}
                                        </h4>
                                        <div className="space-y-3">
                                          {vmDetails.config.scsihw && (
                                            <div className="flex items-center gap-2 text-sm">
                                              <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("vmLxc.details.scsiController")}:</span>
                                              <span className="font-mono text-foreground">{vmDetails.config.scsihw}</span>
                                            </div>
                                          )}
                                          {vmDetails.config.rootfs && renderDisk(t("vmLxc.details.rootFilesystem"), vmDetails.config.rootfs as string, "rootfs")}
                                          {Object.keys(vmDetails.config)
                                            .filter((key) => key.match(/^(scsi|sata|ide|virtio)\d+$/))
                                            .sort()
                                            .map((diskKey) => renderDisk(
                                              diskKey.toUpperCase().replace(/(\d+)/, " $1"),
                                              vmDetails.config[diskKey] as string,
                                              `disk-${selectedVM.vmid}-${diskKey}`,
                                            ))}
                                          {vmDetails.config.efidisk0 && renderDisk(t("vmLxc.details.efiDisk"), vmDetails.config.efidisk0 as string, "efidisk0")}
                                          {vmDetails.config.tpmstate0 && renderDisk(t("vmLxc.details.tpmState"), vmDetails.config.tpmstate0 as string, "tpmstate0")}
                                          {Object.keys(vmDetails.config)
                                            .filter((key) => key.match(/^mp\d+$/))
                                            .sort()
                                            .map((mpKey) => renderDisk(
                                              t("vmLxc.details.mountPointIndexed", { index: mpKey.replace("mp", "") }),
                                              vmDetails.config[mpKey] as string,
                                              `mp-${selectedVM.vmid}-${mpKey}`,
                                            ))}
                                        </div>
                                      </div>
                                    )
                                  })()}

                                  {/* Network Section */}
                                  <div>
                                    <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      <Network className="h-4 w-4" />
                                      {t("vmLxc.details.network")}
                                    </h4>
                                    <div className="space-y-3">
                                      {/* Network Interfaces with proper keys.
                                          Renders BOTH a human-readable
                                          breakdown (bridge, IP, gw, MAC,
                                          host iface) AND the raw config
                                          string so power users still see
                                          the underlying Proxmox config. */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^net\d+$/))
                                        .map((netKey) => {
                                          const raw = vmDetails.config[netKey] as string
                                          // Parse "name=eth0,bridge=vmbr0,gw=1.2.3.4,..."
                                          const parsed: Record<string, string> = {}
                                          raw.split(",").forEach((pair) => {
                                            const eq = pair.indexOf("=")
                                            if (eq > 0) {
                                              parsed[pair.slice(0, eq).trim()] =
                                                pair.slice(eq + 1).trim()
                                            } else if (pair && !parsed.model) {
                                              // bare "virtio" / "e1000" → NIC model
                                              parsed.model = pair.trim()
                                            }
                                          })
                                          const idx = netKey.replace("net", "")
                                          // For VMs, the host-side iface is
                                          // tap<vmid>i<idx>; for LXC it's
                                          // veth<vmid>i<idx>. Surface it so
                                          // users can correlate with the
                                          // "VM & LXC Network Interfaces"
                                          // card on the network page.
                                          const hostIface = selectedVM.type === "lxc"
                                            ? `veth${selectedVM.vmid}i${idx}`
                                            : `tap${selectedVM.vmid}i${idx}`
                                          const Field = ({ label, value, mono }:
                                            { label: string; value: string; mono?: boolean }) => (
                                            <div className="flex flex-col gap-0.5">
                                              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
                                              <span className={`text-foreground ${mono ? "font-mono text-xs" : "text-sm"}`}>{value}</span>
                                            </div>
                                          )
                                          return (
                                            <div key={`net-${selectedVM.vmid}-${netKey}`}
                                                 className="bg-muted/30 rounded-md p-3 space-y-3">
                                              <div className="flex items-center gap-2 flex-wrap">
                                                <EthernetPort className="h-4 w-4 text-green-500 flex-shrink-0" />
                                                <span className="text-sm font-semibold text-foreground">
                                                  {t("vmLxc.details.networkInterface", { index: idx })}
                                                </span>
                                                {parsed.name && (
                                                  <span className="text-xs text-muted-foreground font-mono">
                                                    ({parsed.name})
                                                  </span>
                                                )}
                                                <span className="text-xs text-orange-500 font-mono">
                                                  {t("vmLxc.details.hostInterface", { interface: hostIface })}
                                                </span>
                                              </div>
                                              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
                                                {parsed.bridge && <Field label={t("vmLxc.details.bridge")} value={parsed.bridge} mono />}
                                                {parsed.ip && <Field label="IP" value={parsed.ip} mono />}
                                                {parsed.ip6 && <Field label="IPv6" value={parsed.ip6} mono />}
                                                {parsed.gw && <Field label={t("vmLxc.details.gateway")} value={parsed.gw} mono />}
                                                {parsed.gw6 && <Field label={t("vmLxc.details.gatewayV6")} value={parsed.gw6} mono />}
                                                {parsed.hwaddr && <Field label="MAC" value={parsed.hwaddr.toUpperCase()} mono />}
                                                {parsed.virtio && <Field label="MAC" value={parsed.virtio.toUpperCase()} mono />}
                                                {parsed.e1000 && <Field label="MAC" value={parsed.e1000.toUpperCase()} mono />}
                                                {parsed.type && <Field label={t("vmLxc.details.type")} value={parsed.type} mono />}
                                                {parsed.tag && <Field label="VLAN" value={parsed.tag} mono />}
                                                {parsed.mtu && <Field label="MTU" value={parsed.mtu} mono />}
                                                {parsed.rate && <Field label={t("vmLxc.details.rateLimit")} value={`${parsed.rate} MB/s`} mono />}
                                                {parsed.firewall === "1" && <Field label={t("vmLxc.details.firewall")} value={t("vmLxc.details.enabled")} />}
                                              </div>
                                              <details className="text-xs">
                                                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("vmLxc.details.rawConfig")}</summary>
                                                <div className="mt-1 font-mono text-green-500 break-all bg-background/50 p-2 rounded">
                                                  {raw}
                                                </div>
                                              </details>
                                            </div>
                                          )
                                        })}
                                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                        {vmDetails.config.nameserver && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.dnsNameserver")}</div>
                                            <div className="font-medium text-foreground font-mono">
                                              {vmDetails.config.nameserver}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.searchdomain && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.searchDomain")}</div>
                                            <div className="font-medium text-foreground">
                                              {vmDetails.config.searchdomain}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.hostname && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">{t("vmLxc.details.hostname")}</div>
                                            <div className="font-medium text-foreground">
                                              {vmDetails.config.hostname}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  </div>

                                  {/* PCI Devices with proper keys */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^hostpci\d+$/)) && (
                                    <div>
                                      <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        <Cpu className="h-4 w-4" />
                                        {t("vmLxc.details.pciPassthrough")}
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^hostpci\d+$/))
                                          .map((pciKey) => (
                                            <div key={`pci-${selectedVM.vmid}-${pciKey}`}>
                                              <div className="text-xs text-muted-foreground mb-1">
                                                {pciKey.toUpperCase().replace(/(\d+)/, " $1")}
                                              </div>
                                              <div className="font-medium text-purple-500 text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                                {vmDetails.config[pciKey]}
                                              </div>
                                            </div>
                                          ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* USB Devices with proper keys */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^usb\d+$/)) && (
                                    <div>
                                      <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        <Server className="h-4 w-4" />
                                        {t("vmLxc.details.usbDevices")}
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^usb\d+$/))
                                          .map((usbKey) => (
                                            <div key={`usb-${selectedVM.vmid}-${usbKey}`}>
                                              <div className="text-xs text-muted-foreground mb-1">
                                                {usbKey.toUpperCase().replace(/(\d+)/, " $1")}
                                              </div>
                                              <div className="font-medium text-blue-500 text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                                {vmDetails.config[usbKey]}
                                              </div>
                                            </div>
                                          ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* Serial Ports with proper keys */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^serial\d+$/)) && (
                                    <div>
                                      <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        <Terminal className="h-4 w-4" />
                                        {t("vmLxc.details.serialPorts")}
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^serial\d+$/))
                                          .map((serialKey) => (
                                            <div key={`serial-${selectedVM.vmid}-${serialKey}`}>
                                              <div className="text-xs text-muted-foreground mb-1">
                                                {serialKey.toUpperCase().replace(/(\d+)/, " $1")}
                                              </div>
                                              <div className="font-medium text-foreground font-mono">
                                                {vmDetails.config[serialKey]}
                                              </div>
                                            </div>
                                          ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </CardContent>
                          </Card>
                        </>
                      ) : null}
                    </>
                  )}
                </div>
                )}

                {/* Updates Tab — LXC only. Three render branches:
                     (1) OCI-image CT      → immutable-image info panel
                     (2) OS packages       → pending list + Apply
                     (3) Helper-scripts app → Apply /usr/bin/update
                    Options row (backup + restart + storage) sits at the
                    bottom and gates both Apply buttons. */}
                {/* App Tab — user-registered application watch. Its own
                    self-contained component so this file stays sane;
                    calls the parent's mutate() on save/delete so the
                    header badge + Updates tab pick up the new state. */}
                {activeModalTab === "app" && selectedVM?.type === "lxc" && (() => {
                  const managedEntry = (selectedVM.app_watches || []).find(
                    (a) => a.managed_oci_app_id,
                  )
                  // Prefer vmDetails.lxc_ip_info (loaded per-modal, always
                  // up to date) over the bulk-fetched vmConfigs which may
                  // still be pending on first open. Fallback chain
                  // guarantees the panel gets an IP whenever the modal
                  // itself can display one in the header.
                  const ctIp =
                    (vmDetails as any)?.lxc_ip_info?.primary_ip ||
                    (vmDetails as any)?.lxc_ip_info?.real_ips?.[0] ||
                    vmConfigs[selectedVM.vmid] ||
                    null
                  return (
                    <LxcAppPanel
                      vmid={selectedVM.vmid}
                      ctIp={ctIp}
                      onChange={() => mutate()}
                      managed={
                        managedEntry
                          ? {
                              managed_oci_app_id: managedEntry.managed_oci_app_id!,
                              name: managedEntry.name || "Managed app",
                              installed_version: managedEntry.installed_version,
                              latest_version: managedEntry.latest_version,
                              update_available: managedEntry.update_available,
                              checked_at: managedEntry.checked_at,
                              error: managedEntry.error,
                            }
                          : null
                      }
                    />
                  )
                })()}

                {activeModalTab === "updates" && selectedVM?.type === "lxc" && (
                  <div className="space-y-4" key={`updates-${selectedVM.vmid}`}>
                    {/* Branch 0 — ProxMenux-managed OCI app (Secure Gateway).
                        Same state + Update button as the App tab so
                        the two panels never disagree, and either
                        origin (this tab / the App tab / Security →
                        Secure Gateway) triggers the same underlying
                        oci_manager action. */}
                    {/* Managed OCI-app updates — matches the Security →
                        Secure Gateway panel exactly (same layout, same
                        translucent purple button, same version
                        strings). Update triggered from either place
                        calls /api/oci/installed/<app_id>/update. Uses
                        `latest_version` (anchored to Tailscale by
                        oci_manager) so the button text agrees with
                        Security instead of drifting to alpine-base or
                        any other package that happens to be first
                        alphabetically. */}
                    {selectedVM.update_check?.managed_oci_app && (() => {
                      const aw = (selectedVM.app_watches || []).find(
                        (a) => a.managed_oci_app_id,
                      )
                      const appId = selectedVM.update_check.managed_oci_app
                      const hasUpdate = aw?.update_available === true
                      const upToDate = aw?.update_available === false && !!aw?.installed_version
                      const pkgCount = aw?.packages?.length || 0
                      const others = pkgCount > 1 ? pkgCount - 1 : 0
                      const lastChecked = aw?.checked_at
                        ? new Date(aw.checked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                        : "—"
                      return (
                        <Card className="border border-border bg-card/50">
                          <CardContent className="p-4 space-y-3">
                            <div className="flex items-center justify-between flex-wrap gap-2">
                              <div className="flex items-center gap-2">
                                <div className="p-1.5 rounded-md bg-emerald-500/10">
                                  <Shield className="h-4 w-4 text-emerald-400" />
                                </div>
                                <h3 className="text-sm font-semibold text-foreground">
                                  {aw?.name || "Managed app"}
                                </h3>
                              </div>
                              <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-400 border-emerald-500/30">
                                managed
                              </Badge>
                            </div>
                            {hasUpdate ? (
                              <>
                                <div className="text-xs text-muted-foreground">
                                  Last checked: {lastChecked} ·{" "}
                                  <span className="text-purple-400 font-medium">
                                    Tailscale v{aw?.latest_version} available
                                  </span>
                                </div>
                                <div>
                                  <Button
                                    size="sm"
                                    onClick={async () => {
                                      try {
                                        await fetchApi(`/api/oci/installed/${appId}/update`, { method: "POST" })
                                        mutate()
                                      } catch { /* opening the App tab surfaces the error */ }
                                    }}
                                    className="bg-purple-600/15 hover:bg-purple-600/25 border border-purple-500/40 text-purple-300 hover:text-purple-200"
                                  >
                                    <ArrowUpCircle className="h-4 w-4 mr-1.5" />
                                    Update to v{aw?.latest_version}
                                  </Button>
                                </div>
                                {others > 0 && (
                                  <div className="text-[11px] text-muted-foreground">
                                    +{others} other package{others === 1 ? "" : "s"} pending in the container
                                  </div>
                                )}
                              </>
                            ) : upToDate ? (
                              <div className="text-xs text-muted-foreground">
                                Last checked: {lastChecked}
                                {aw?.installed_version && <> · Tailscale v{aw.installed_version}</>}
                                {" · "}<span className="text-emerald-400/90">{t("vmLxc.updates.noUpdatesAvailableChip")}</span>
                              </div>
                            ) : (
                              <div className="text-xs text-muted-foreground">
                                No update information yet — check from Security → Secure Gateway.
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      )
                    })()}

                    {/* Branch 1 — OCI-image container */}
                    {!selectedVM.update_check?.managed_oci_app &&
                      selectedVM.update_check?.is_oci_lxc && (
                      <Card className="border border-border bg-card/50">
                        <CardContent className="p-4 space-y-2">
                          <div className="flex items-center gap-2 mb-1">
                            <div className="p-1.5 rounded-md bg-blue-500/10">
                              <Container className="h-4 w-4 text-blue-400" />
                            </div>
                            <h3 className="text-sm font-semibold text-foreground">
                              OCI image container
                            </h3>
                          </div>
                          <p className="text-sm text-muted-foreground leading-relaxed">
                            This container was created from an OCI (Docker) image.
                            Update management for OCI containers is coming with
                            the upcoming OCI install feature — updates will
                            rebuild the container from a newer image tag rather
                            than patching packages inside.
                          </p>
                        </CardContent>
                      </Card>
                    )}

                    {/* Unified Updates card + Options card. When the CT
                        is a regular (non-OCI, non-managed-OCI) LXC, ALL
                        update paths live inside a single card so section
                        styling and the button footer stay uniform. The
                        Options card below carries manual toggles
                        (backup, restart) + a placeholder for the
                        upcoming scheduled-updates (cron) feature.

                        Button state → color:
                          • Purple  = updates pending  (Apply X, arrow icon)
                          • Green   = up to date       (X, no icon, no "Apply")
                        Combined button surfaces only when exactly ONE
                        app method (helper /usr/bin/update OR a single
                        registered app with `update_command`) is present.
                        With zero the button makes no sense; with N > 1
                        we can't know which app to invoke, so the user
                        picks individually via section-level buttons. */}
                    {!selectedVM.update_check?.managed_oci_app &&
                      !selectedVM.update_check?.is_oci_lxc && (() => {
                        const uc = selectedVM.update_check
                        const hasOsUpdates = !!uc?.available
                        const helperExists = !!uc?.app_updater_present
                        const helperName = uc?.helper_app_name || null
                        const helperKnownNotUpdateable = !helperExists && !!uc?.helper_slug && !!uc?.helper_updateable_known
                        const helperUnlisted = !helperExists && !!uc?.helper_slug && !uc?.helper_updateable_known
                        const trackedApps = (selectedVM.app_watches || []).filter(
                          (a) => !a.managed_oci_app_id && !!a.installed_via,
                        )
                        const customCmdApps = trackedApps.filter(
                          (a) => !!(a.update_command && a.update_command.trim()),
                        )
                        // Apps eligible for a section in the unified
                        // card. Rules:
                        //  • Any app with a `update_command` gets its
                        //    own section (always).
                        //  • Any other app gets its own section UNLESS:
                        //    - it is the specific app the CT-wide
                        //      helper section is already covering
                        //      (matched by helper_slug), OR
                        //    - its install method is dpkg/apk — those
                        //      packages are already updated as part
                        //      of the OS section's `apt/apk upgrade`
                        //      run, so a dedicated "no method" notice
                        //      is misleading (Redis, PostgreSQL, etc).
                        //      The App-tab purple ⬆ still surfaces the
                        //      version delta; user just clicks Apply
                        //      OS update to pick it up.
                        const appSections = trackedApps.filter((a) => {
                          const hasCmd = !!(a.update_command && a.update_command.trim())
                          if (hasCmd) return true
                          const isHelperOwnedApp = helperExists && !!a.helper_slug && a.helper_slug === uc?.helper_slug
                          if (isHelperOwnedApp) return false
                          if (a.installed_via === "dpkg" || a.installed_via === "apk") return false
                          return true
                        })
                        const anyAppPending =
                          (helperExists && trackedApps.some((a) => a.update_available === true))
                          || customCmdApps.some((a) => a.update_available === true)
                        const singleAppMethod = (helperExists ? 1 : 0) + customCmdApps.length === 1
                        const combinedApp: { name: string; cmd: string; isHelper: boolean } | null = helperExists
                          ? { name: helperName || "application", cmd: "", isHelper: true }
                          : customCmdApps.length === 1
                            ? { name: customCmdApps[0].name || "application", cmd: customCmdApps[0].update_command!, isHelper: false }
                            : null
                        const pendingBtnCls = "bg-purple-600/15 hover:bg-purple-600/25 border border-purple-500/40 text-purple-300 hover:text-purple-200"
                        const upToDateBtnCls = "bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 text-green-400 hover:text-green-300"
                        return (
                          <>
                            <Card className="border border-border bg-card/50">
                              <CardContent className="p-4 divide-y divide-border/50">
                                {/* OS section */}
                                <div className="pb-4">
                                  <div className="flex items-center gap-2 mb-3">
                                    <Package className="h-4 w-4 text-muted-foreground" />
                                    <h3 className="text-sm font-semibold text-foreground">{t("vmLxc.updates.osPackagesTitle")}</h3>
                                  </div>
                                  <div className="text-xs text-muted-foreground mb-3 leading-relaxed">
                                    {t("vmLxc.updates.lastCheckedPrefix")}{" "}
                                    {uc?.last_check ? new Date(uc.last_check).toLocaleString() : "—"}
                                    {uc?.os_family && (
                                      <> · {t("vmLxc.updates.familyLabel")} <code className="text-foreground/80">{uc.os_family}</code></>
                                    )}
                                  </div>
                                  {hasOsUpdates ? (() => {
                                    const stored = uc!.packages?.length || 0
                                    const total = uc!.count || 0
                                    const sec = uc!.security_count || 0
                                    const truncated = total > stored
                                    if (!truncated && stored > 0) {
                                      return (
                                        <div className="divide-y divide-border/50">
                                          {uc!.packages.map((p) => (
                                            <div key={p.name} className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-0.5 sm:gap-2 py-2 text-sm">
                                              <span className="font-mono text-foreground/90 flex items-center gap-2 min-w-0">
                                                {p.security && (
                                                  <Shield className="h-4 w-4 text-green-500 flex-shrink-0" aria-label={t("vmLxc.updates.securityUpdateAria")} />
                                                )}
                                                <span className="truncate">{p.name}</span>
                                              </span>
                                              <span className="flex items-center gap-1.5 text-muted-foreground flex-shrink-0 font-mono text-xs sm:text-sm">
                                                <span>{p.current || "—"}</span>
                                                <span>→</span>
                                                <span className="text-foreground">{p.latest}</span>
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      )
                                    }
                                    return (
                                      <div className="space-y-2 text-sm">
                                        <div className="flex items-center gap-2">
                                          <Package className="h-4 w-4 text-purple-300 flex-shrink-0" />
                                          <span><span className="font-semibold">{total}</span> {t(total === 1 ? "vmLxc.updates.packagePendingLabel" : "vmLxc.updates.packagesPendingLabel")}</span>
                                        </div>
                                        {sec > 0 && (
                                          <div className="flex items-center gap-2">
                                            <Shield className="h-4 w-4 text-green-500 flex-shrink-0" />
                                            <span><span className="font-semibold">{sec}</span> {t(sec === 1 ? "vmLxc.updates.securityUpdateLabel" : "vmLxc.updates.securityUpdatesLabel")}</span>
                                          </div>
                                        )}
                                      </div>
                                    )
                                  })() : (
                                    <div className="text-sm text-muted-foreground flex items-center gap-2">
                                      <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                                      {t("vmLxc.updates.noOsUpdatesPending")}
                                    </div>
                                  )}
                                  <div className="mt-3 flex justify-end">
                                    <Button
                                      size="sm"
                                      onClick={() => openApplyTerminal(selectedVM.vmid, "os")}
                                      className={hasOsUpdates ? pendingBtnCls : upToDateBtnCls}
                                    >
                                      {hasOsUpdates && <ArrowUpCircle className="h-4 w-4 mr-1.5" />}
                                      {hasOsUpdates ? t("vmLxc.updates.applyOsUpdate") : t("vmLxc.updates.osUpToDate")}
                                    </Button>
                                  </div>
                                </div>

                                {/* Helper-scripts section — reuses the
                                    same header + body pattern as the
                                    custom-command app sections below so
                                    the two look homogeneous. Gated on
                                    the presence of a REGISTERED App
                                    Watch entry with matching helper_slug
                                    — we don't surface helper info for
                                    apps the user hasn't explicitly
                                    opted into. This keeps Updates tab
                                    honest: an unregistered auto-detected
                                    app has zero action here. When the
                                    matching entry exists, we render
                                    installed/upstream versions and the
                                    Apply button. Non-updateable and
                                    unlisted variants are also gated on
                                    registration so they don't nag about
                                    apps the user chose not to manage. */}
                                {(helperExists || helperKnownNotUpdateable || helperUnlisted) && (() => {
                                  const matchApp = trackedApps.find(
                                    (a) => a.helper_slug === uc?.helper_slug && !a.update_command
                                  ) || null
                                  if (!matchApp) return null
                                  const hasUpd = helperExists && matchApp.update_available === true
                                  const upToD = helperExists && matchApp.update_available === false && !!matchApp.installed_version
                                  return (
                                    <div className="py-4">
                                      <div className="flex items-center gap-2 mb-3 min-w-0">
                                        <Package className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                        <h3 className="text-sm font-semibold text-foreground truncate">
                                          {helperName || t("vmLxc.updates.applicationDefaultName")}
                                        </h3>
                                      </div>
                                      {matchApp?.checked_at && (
                                        <div className="text-xs text-muted-foreground mb-3 leading-relaxed">
                                          {t("vmLxc.updates.lastCheckedPrefix")} {new Date(matchApp.checked_at).toLocaleString()}
                                        </div>
                                      )}
                                      {/* Educational note — apps installed via
                                          Proxmox community-scripts (helper
                                          scripts) update through the built-in
                                          `/usr/bin/update` script that each
                                          helper drops on install. Surface the
                                          origin so the user knows why the
                                          Apply button here doesn't invoke
                                          apt/apk/custom_command flows. Only in
                                          the Updates tab — the App tab is
                                          about registration, not update
                                          plumbing. */}
                                      {helperExists && (
                                        <div className="mb-3 flex items-start gap-2.5">
                                          <img
                                            src="https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/proxmox-helper-scripts.webp"
                                            alt=""
                                            className="h-7 w-7 rounded-sm object-contain flex-shrink-0"
                                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
                                          />
                                          <span className="text-xs text-muted-foreground leading-relaxed">
                                            {t("vmLxc.updates.installedByHelperPrefix")} <span className="text-foreground/80">{t("vmLxc.updates.helperScriptsName")}</span>
                                            {" "}{t("vmLxc.updates.helperUpdatesRun")}
                                          </span>
                                        </div>
                                      )}
                                      {hasUpd ? (
                                        <div className="space-y-2 text-sm">
                                          <div className="flex items-center gap-2">
                                            <Package className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                            <span>{t("vmLxc.updates.installedLabel")} <code className="text-foreground/80">{matchApp!.installed_version}</code></span>
                                          </div>
                                          <div className="flex items-center gap-2">
                                            <ArrowUpCircle className="h-4 w-4 text-purple-400 flex-shrink-0" />
                                            <span>upstream <code className="text-purple-300">{matchApp!.latest_version}</code> available</span>
                                          </div>
                                        </div>
                                      ) : upToD ? (
                                        <div className="text-sm text-muted-foreground flex items-center gap-2">
                                          <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                                          <span>{t("vmLxc.updates.upToDateAtLabel")} <code className="text-foreground/80">{matchApp!.installed_version}</code></span>
                                        </div>
                                      ) : helperExists ? (
                                        <p className="text-xs text-muted-foreground leading-relaxed">
                                          {t("vmLxc.updates.versionTrackingPending")}
                                        </p>
                                      ) : null}
                                      {helperExists && (() => {
                                        // Button state uses the matched
                                        // App Watch entry when present.
                                        // Without it we DON'T know the
                                        // version delta — showing "Up to
                                        // date" would be a false claim,
                                        // and "Apply update" implies a
                                        // pending upgrade we can't
                                        // confirm. Fall back to a neutral
                                        // "Run updater" so the user can
                                        // still force the helper's own
                                        // update script.
                                        const noState = !hasUpd && !upToD
                                        const neutralBtnCls = "bg-muted/40 hover:bg-muted/60 border border-border text-foreground/80 hover:text-foreground"
                                        const cls = hasUpd ? pendingBtnCls : upToD ? upToDateBtnCls : neutralBtnCls
                                        const label = hasUpd ? t("vmLxc.updates.applyUpdate") : upToD ? t("vmLxc.updates.upToDate") : t("vmLxc.updates.runUpdater")
                                        return (
                                          <div className="mt-3 flex justify-end">
                                            <Button size="sm" onClick={() => openApplyTerminal(selectedVM.vmid, "app")} className={cls}>
                                              {hasUpd && <ArrowUpCircle className="h-4 w-4 mr-1.5" />}
                                              {noState && <RefreshCw className="h-4 w-4 mr-1.5" />}
                                              {label}
                                            </Button>
                                          </div>
                                        )
                                      })()}
                                      {!helperExists && (
                                        helperKnownNotUpdateable ? (
                                          <p className="text-xs text-amber-400/90 leading-relaxed">
                                            The community-scripts registry marks this app as not updateable
                                            in place. Apply updates manually or reinstall with a newer
                                            helper-script.
                                          </p>
                                        ) : (
                                          <p className="text-xs text-muted-foreground leading-relaxed">
                                            Detected a helper-scripts updater
                                            (<code className="text-foreground/80">{uc?.helper_slug}</code>)
                                            but it isn't listed in the ProxMenux helpers catalogue.
                                            Applying manually is safest.
                                          </p>
                                        )
                                      )}
                                    </div>
                                  )
                                })()}

                                {/* Registered-app sections — one per app
                                    that either has a custom_command wired
                                    up (Case 3b) or has no update method at
                                    all when the CT lacks a helper updater
                                    (Case 3a). Same header pattern; the
                                    body swaps between an info line + Edit
                                    link, a "no method + Add" prompt, or an
                                    inline editor form when adding /
                                    editing. */}
                                {appSections.map((aw) => {
                                  const hasCmd = !!(aw.update_command && aw.update_command.trim())
                                  const editing = customCmdEditingApp === aw.id
                                  const hasUpdate = aw.update_available === true
                                  const upToDate = aw.update_available === false && !!aw.installed_version
                                  return (
                                    <div key={`app-${aw.id}`} className={editing ? "py-4 -mx-4 px-4 bg-card" : "py-4"}>
                                      <div className="flex items-center gap-2 mb-3 min-w-0">
                                        <Package className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                        <h3 className="text-sm font-semibold text-foreground truncate">
                                          {aw.name}
                                        </h3>
                                      </div>
                                      {aw.checked_at && !editing && (
                                        <div className="text-xs text-muted-foreground mb-3 leading-relaxed">
                                          {t("vmLxc.updates.lastCheckedPrefix")} {new Date(aw.checked_at).toLocaleString()}
                                        </div>
                                      )}
                                      {editing ? (
                                        <div className="space-y-3">
                                          <div>
                                            <Label className="text-xs uppercase tracking-wider text-muted-foreground">
                                              {t("vmLxc.updates.customCommandLabel")}
                                            </Label>
                                            <Textarea
                                              value={customCmdDraft}
                                              onChange={(e) => setCustomCmdDraft(e.target.value)}
                                              placeholder={t("vmLxc.updates.customCommandPlaceholder")}
                                              className="font-mono text-xs mt-2 min-h-[100px]"
                                              maxLength={4096}
                                            />
                                          </div>
                                          <div className="flex items-center justify-between gap-2">
                                            <div>
                                              {hasCmd && (
                                                <button
                                                  type="button"
                                                  onClick={() => removeCustomCommand(selectedVM.vmid, aw)}
                                                  disabled={customCmdSaving}
                                                  className="h-8 px-3 text-xs rounded-md border border-red-500/30 bg-red-500/10 hover:bg-red-500/20 text-red-400 transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                                                >
                                                  <Trash2 className="h-3.5 w-3.5" />
                                                  {t("vmLxc.updates.removeButton")}
                                                </button>
                                              )}
                                            </div>
                                            <div className="flex items-center gap-2">
                                              <button
                                                type="button"
                                                onClick={closeCustomCmdEditor}
                                                disabled={customCmdSaving}
                                                className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                                              >
                                                {t("vmLxc.updates.cancelButton")}
                                              </button>
                                              <button
                                                type="button"
                                                onClick={() => saveCustomCommand(selectedVM.vmid, aw)}
                                                disabled={customCmdSaving || !customCmdDraft.trim() || customCmdDraft.trim() === (aw.update_command || "").trim()}
                                                className="h-8 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
                                              >
                                                {customCmdSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                                                {t("vmLxc.updates.saveButton")}
                                              </button>
                                            </div>
                                          </div>
                                        </div>
                                      ) : hasCmd ? (
                                        <>
                                          {hasUpdate ? (
                                            <div className="space-y-2 text-sm">
                                              <div className="flex items-center gap-2">
                                                <Package className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                                <span>{t("vmLxc.updates.installedLabel")} <code className="text-foreground/80">{aw.installed_version}</code></span>
                                              </div>
                                              <div className="flex items-center gap-2">
                                                <ArrowUpCircle className="h-4 w-4 text-purple-400 flex-shrink-0" />
                                                <span>upstream <code className="text-purple-300">{aw.latest_version}</code> available</span>
                                              </div>
                                            </div>
                                          ) : upToDate ? (
                                            <div className="text-sm text-muted-foreground flex items-center gap-2">
                                              <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                                              <span>{t("vmLxc.updates.upToDateAtLabel")} <code className="text-foreground/80">{aw.installed_version}</code></span>
                                            </div>
                                          ) : (
                                            <div className="text-sm text-muted-foreground">
                                              {t("vmLxc.updates.versionTrackingPendingShort")}
                                            </div>
                                          )}
                                          {/* Buttons stacked bottom-right:
                                              primary Apply on top, secondary
                                              Edit below. Keeps Apply position
                                              consistent with the helper and
                                              OS sections (also right-aligned
                                              inline buttons) and never wraps
                                              awkwardly with the info block. */}
                                          <div className="mt-3 flex flex-col items-end gap-2">
                                            <Button
                                              size="sm"
                                              onClick={() => openApplyTerminal(
                                                selectedVM.vmid,
                                                "app",
                                                { updateCommand: aw.update_command!, appName: aw.name || "" },
                                              )}
                                              className={hasUpdate ? pendingBtnCls : upToDateBtnCls}
                                            >
                                              {hasUpdate && <ArrowUpCircle className="h-4 w-4 mr-1.5" />}
                                              {hasUpdate ? t("vmLxc.updates.applyUpdate") : t("vmLxc.updates.upToDate")}
                                            </Button>
                                            <button
                                              type="button"
                                              onClick={() => openCustomCmdEditor(aw)}
                                              className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5"
                                            >
                                              <Pencil className="h-3.5 w-3.5" />
                                              {t("vmLxc.updates.editCommandButton")}
                                            </button>
                                          </div>
                                        </>
                                      ) : (
                                        <div className="flex items-center justify-between flex-wrap gap-2">
                                          <p className="text-xs text-muted-foreground leading-relaxed min-w-0">
                                            {t("vmLxc.updates.noMethodBody")}
                                          </p>
                                          <button
                                            type="button"
                                            onClick={() => openCustomCmdEditor(aw)}
                                            className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5 flex-shrink-0"
                                          >
                                            <Plus className="h-3.5 w-3.5" />
                                            {t("vmLxc.updates.wireUpCommandButton")}
                                          </button>
                                        </div>
                                      )}
                                    </div>
                                  )
                                })}

                                {/* Footer actions — up to 3 buttons: OS,
                                    Combined only. Individual Apply buttons
                                    live inside each section above (Option
                                    A pattern): OS section owns its OS
                                    button, each app section owns its own
                                    Apply. Footer's sole role is the "run
                                    everything in one shot" convenience:
                                      • Single method  → "OS + {name}"
                                      • Multi custom-only → "OS + Apps"
                                        (concatenate customs via `;`, run
                                        as one sh -c invocation)
                                      • Mixed helper + custom → hidden
                                        for now (needs backend chain, M5).
                                    Purple when any part pending; green
                                    when everything up to date. */}
                                {(() => {
                                  const hasAnyAppMethod = helperExists || customCmdApps.length > 0
                                  if (!hasAnyAppMethod) return null
                                  // Single method — reuse the existing
                                  // TARGET=both path so the script picks
                                  // the right updater. Helper case has
                                  // NO UPDATE_COMMAND (script falls
                                  // through to /usr/bin/update); custom
                                  // case passes its command directly.
                                  if (singleAppMethod && combinedApp) {
                                    return (
                                      <div className="pt-4 flex justify-end">
                                        <Button
                                          size="sm"
                                          onClick={() => openApplyTerminal(
                                            selectedVM.vmid,
                                            "both",
                                            combinedApp.isHelper ? undefined : { updateCommand: combinedApp.cmd, appName: combinedApp.name },
                                          )}
                                          className={(hasOsUpdates || anyAppPending) ? pendingBtnCls : upToDateBtnCls}
                                        >
                                          {(hasOsUpdates || anyAppPending) && <ArrowUpCircle className="h-4 w-4 mr-1.5" />}
                                          {(hasOsUpdates || anyAppPending) ? t("vmLxc.updates.applyOsAppsFooter", { appName: combinedApp.name }) : t("vmLxc.updates.osAppsFooter", { appName: combinedApp.name })}
                                        </Button>
                                      </div>
                                    )
                                  }
                                  // Multi-app case — build a single
                                  // UPDATE_COMMAND that chains every app
                                  // method with `;`. Helper (if present)
                                  // goes first as its full invocation
                                  // (PHS_SILENT=1 bash /usr/bin/update),
                                  // then each custom_command. Runs as
                                  // one `pct exec sh -c` — no backend
                                  // script change needed.
                                  const parts: string[] = []
                                  if (helperExists) {
                                    parts.push("PHS_SILENT=1 bash /usr/bin/update")
                                  }
                                  for (const a of customCmdApps) {
                                    parts.push(a.update_command!.trim())
                                  }
                                  const chained = parts.join("; ")
                                  return (
                                    <div className="pt-4 flex justify-end">
                                      <Button
                                        size="sm"
                                        onClick={() => openApplyTerminal(
                                          selectedVM.vmid,
                                          "both",
                                          { updateCommand: chained, appName: "Apps" },
                                        )}
                                        className={(hasOsUpdates || anyAppPending) ? pendingBtnCls : upToDateBtnCls}
                                      >
                                        {(hasOsUpdates || anyAppPending) && <ArrowUpCircle className="h-4 w-4 mr-1.5" />}
                                        {(hasOsUpdates || anyAppPending) ? t("vmLxc.updates.applyOsAppsFooterPlural") : t("vmLxc.updates.osAppsFooterPlural")}
                                      </Button>
                                    </div>
                                  )
                                })()}
                              </CardContent>
                            </Card>

                            {/* Options card — unified apply preferences
                                + scheduled updates. Backup/restart live
                                in ONE place and drive both manual clicks
                                and scheduled cron runs (no duplicated
                                config).
                                View mode: read-only summary + Edit btn.
                                Edit mode: card opaque `bg-card` + inputs
                                sunken (project-wide card-contrast rule
                                per feedback_card_contrast_edit_mode.md).
                                Scheduled section shows one of four
                                states: not scheduled, external-only
                                (community-scripts host cron), ProxMenux
                                only, or both (external + ProxMenux). */}
                            <Card className={optionsEditMode ? "border border-border bg-card" : "border border-border bg-card/50"}>
                              <CardContent className="p-4 space-y-4">
                                <h3 className="text-sm font-semibold text-foreground">
                                  {t("vmLxc.options.title")}
                                </h3>

                                {/* Two-mode rendering — VIEW mode is a
                                    compact scannable summary (green ✓
                                    for enabled, hollow ○ for disabled +
                                    a plain-English label). EDIT mode
                                    shows the actual checkboxes and
                                    inputs so the user can change values.
                                    Users saw both variants and preferred
                                    the icon+text view: it reads faster,
                                    doesn't look like "broken" disabled
                                    checkboxes, and clearly differentiates
                                    "reading current state" from "editing
                                    the form". */}
                                {!optionsEditMode ? (
                                  <div className="text-sm space-y-2">
                                    <div className="flex items-center gap-2">
                                      {applyBackup ? (
                                        <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                                      ) : (
                                        <div className="h-4 w-4 rounded-full border border-muted-foreground/40 flex-shrink-0" />
                                      )}
                                      <span>
                                        {applyBackup
                                          ? <>{t("vmLxc.options.snapshotBefore")} <span className="text-muted-foreground">— on <code className="text-foreground/80">{applyBackupStorage || selectedBackupStorage || t("vmLxc.options.storageAuto")}</code></span></>
                                          : <span className="text-muted-foreground">{t("vmLxc.options.noSnapshot")}</span>}
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      {applyRestart ? (
                                        <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                                      ) : (
                                        <div className="h-4 w-4 rounded-full border border-muted-foreground/40 flex-shrink-0" />
                                      )}
                                      <span>
                                        {applyRestart
                                          ? t("vmLxc.options.restartAfter")
                                          : <span className="text-muted-foreground">{t("vmLxc.options.noRestart")}</span>}
                                      </span>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="space-y-3">
                                    <div className="flex items-start gap-2 text-sm">
                                      <Checkbox
                                        id="apply-backup"
                                        checked={applyBackup}
                                        onCheckedChange={(v) => setApplyBackup(Boolean(v))}
                                        className="mt-0.5"
                                      />
                                      <Label htmlFor="apply-backup" className="leading-tight cursor-pointer">
                                        <span>{t("vmLxc.options.snapshotLabel")}</span>
                                        <div className="text-xs text-muted-foreground mt-0.5">
                                          {t("vmLxc.options.appliesToBoth")}
                                        </div>
                                      </Label>
                                    </div>
                                    {applyBackup && backupStorages.length > 0 && (
                                      <div className="pl-6">
                                        <Label className="text-xs text-muted-foreground">{t("vmLxc.options.backupStorage")}</Label>
                                        <Select
                                          value={applyBackupStorage || selectedBackupStorage}
                                          onValueChange={setApplyBackupStorage}
                                        >
                                          <SelectTrigger className="h-8 text-sm mt-1 max-w-xs">
                                            <SelectValue placeholder={t("vmLxc.options.pickStorage")} />
                                          </SelectTrigger>
                                          <SelectContent>
                                            {backupStorages.map((s) => (
                                              <SelectItem key={s.storage} value={s.storage}>
                                                {s.storage}
                                              </SelectItem>
                                            ))}
                                          </SelectContent>
                                        </Select>
                                      </div>
                                    )}
                                    <div className="flex items-start gap-2 text-sm">
                                      <Checkbox
                                        id="apply-restart"
                                        checked={applyRestart}
                                        onCheckedChange={(v) => setApplyRestart(Boolean(v))}
                                        className="mt-0.5"
                                      />
                                      <Label htmlFor="apply-restart" className="leading-tight cursor-pointer">
                                        <span>{t("vmLxc.options.restartAfter")}</span>
                                        <div className="text-xs text-muted-foreground mt-0.5">
                                          {t("vmLxc.options.appliesToBoth")}
                                        </div>
                                      </Label>
                                    </div>
                                  </div>
                                )}

                                <div className="pt-4 border-t border-border/50 space-y-3">
                                  {/* Scheduled updates header. Switch
                                      is visible ANY time a cron config
                                      exists (view or edit mode) so the
                                      user always sees whether it's on
                                      or off; interactive only in edit
                                      mode. Trash lives next to it in
                                      edit mode when a cron exists.
                                      In edit mode with NO cron yet we
                                      still show the Switch (it flips
                                      the form open so the user can fill
                                      in the cron + save). */}
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                      <div className="text-sm font-medium text-foreground">
                                        {t("vmLxc.scheduled.title")}
                                      </div>
                                      {optionsEditMode && (
                                        <div className="text-xs text-muted-foreground mt-0.5">
                                          {scheduleEnabled
                                            ? t("vmLxc.scheduled.enabledHelper")
                                            : t("vmLxc.scheduled.disabledHelper")}
                                        </div>
                                      )}
                                    </div>
                                    <Switch
                                      checked={scheduleEnabled}
                                      onCheckedChange={(v) => { if (optionsEditMode) setScheduleEnabled(v) }}
                                      disabled={!optionsEditMode}
                                      className="data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border"
                                    />
                                  </div>

                                  {/* View mode — compact chip line only.
                                      NO form fields, NO raw cron string:
                                      user sees the human label + target +
                                      last run and stops there. Three
                                      chip states based on config +
                                      enabled: active / disabled-but-
                                      configured / nothing (falls through
                                      to external chip or "Not scheduled"
                                      below). */}
                                  {!optionsEditMode && scheduleConfigured && (
                                    <div className="text-sm space-y-1.5">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <span className={"h-2 w-2 rounded-full flex-shrink-0 " + (scheduleEnabled ? "bg-green-500" : "bg-muted-foreground/40")} />
                                        <span className={scheduleEnabled ? "" : "text-muted-foreground"}>
                                          <span className="text-foreground/80">{t("vmLxc.scheduled.chipLabel")}</span> — {humanCron(scheduleCron)}
                                          {!scheduleEnabled && <span className="text-muted-foreground"> {t("vmLxc.scheduled.disabledSuffix")}</span>}
                                        </span>
                                      </div>
                                      <div className="text-xs text-muted-foreground pl-4">
                                        {t("vmLxc.scheduled.whatLabel")} {scheduleTarget === "os" ? t("vmLxc.scheduled.targetOs") : scheduleTarget === "app" ? t("vmLxc.scheduled.targetApp") : t("vmLxc.scheduled.targetBoth")}
                                      </div>
                                      {scheduleLastRunAt && (
                                        <div className="text-xs text-muted-foreground pl-4">
                                          {t("vmLxc.scheduled.lastRun", { date: new Date(scheduleLastRunAt).toLocaleString() })}
                                          {scheduleLastRunStatus && (
                                            <> · <span className={scheduleLastRunStatus === "success" ? "text-green-400" : "text-red-400"}>
                                              {scheduleLastRunStatus === "success" ? t("vmLxc.scheduled.runSuccess") : t("vmLxc.scheduled.runFailed")}
                                            </span></>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                  {!optionsEditMode && !scheduleConfigured && !externalCron && (
                                    <div className="text-sm flex items-center gap-2 text-muted-foreground">
                                      <div className="h-4 w-4 rounded-full border border-muted-foreground/40 flex-shrink-0" />
                                      <span>{t("vmLxc.scheduled.notScheduled")}</span>
                                    </div>
                                  )}

                                  {/* External helper cron chip — shown
                                      in BOTH view + edit modes when
                                      detected. Includes the helper-
                                      scripts logo per the user's ask. */}
                                  {externalCron && optionsEditMode && (() => {
                                    const variantLabel = externalCron.variant === "tteck-legacy"
                                      ? t("vmLxc.cronChip.variantTteck")
                                      : externalCron.variant === "unknown"
                                        ? t("vmLxc.cronChip.variantCustom")
                                        : t("vmLxc.cronChip.variantCommunityScripts")
                                    const scopeText = externalCron.scope === "os"
                                      ? t("vmLxc.cronChip.scopeAptApk")
                                      : t("vmLxc.cronChip.scopeUnknown")
                                    return (
                                      <div className="flex items-start gap-2 text-xs text-muted-foreground p-2 rounded-md bg-muted/40 border border-border/50">
                                        <img
                                          src="https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/proxmox-helper-scripts.webp"
                                          alt=""
                                          className="h-5 w-5 rounded-sm object-contain flex-shrink-0 mt-0.5"
                                          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
                                        />
                                        <div className="flex-1 min-w-0">
                                          <div className="text-foreground">
                                            <span className="text-foreground/80">{variantLabel}</span> {t("vmLxc.cronChip.detected")}
                                          </div>
                                          <div className="mt-0.5">
                                            {externalCron.human_schedule} — {scopeText}
                                          </div>
                                        </div>
                                      </div>
                                    )
                                  })()}

                                  {/* Form fields — edit mode only.
                                      In view mode the compact chip
                                      above already summarises the
                                      config; the raw dropdowns / cron
                                      input would just be noise. */}
                                  {optionsEditMode && scheduleEnabled && (
                                    <div className="space-y-3">
                                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        <div>
                                          <Label className="text-xs text-muted-foreground">{t("vmLxc.scheduled.frequency")}</Label>
                                          <Select
                                            value={schedulePreset}
                                            onValueChange={(v) => {
                                              setSchedulePreset(v)
                                              const preset = CRON_PRESETS.find((p) => p.value === v)
                                              if (preset && preset.cron) setScheduleCron(preset.cron)
                                            }}
                                            disabled={!optionsEditMode}
                                          >
                                            <SelectTrigger className="h-8 text-sm mt-1">
                                              <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                              {CRON_PRESETS.map((p) => (
                                                <SelectItem key={p.value} value={p.value}>
                                                  {p.label}
                                                </SelectItem>
                                              ))}
                                            </SelectContent>
                                          </Select>
                                        </div>
                                        <div>
                                          <Label className="text-xs text-muted-foreground">{t("vmLxc.scheduled.cronExpression")}</Label>
                                          <Input
                                            value={scheduleCron}
                                            onChange={(e) => {
                                              setScheduleCron(e.target.value)
                                              setSchedulePreset("custom")
                                            }}
                                            disabled={!optionsEditMode}
                                            placeholder={t("vmLxc.scheduled.cronPlaceholder")}
                                            className="h-8 text-sm mt-1 font-mono"
                                          />
                                        </div>
                                      </div>
                                      <div>
                                        <Label className="text-xs text-muted-foreground">{t("vmLxc.scheduled.whatToUpdate")}</Label>
                                        <Select
                                          value={scheduleTarget}
                                          onValueChange={(v) => setScheduleTarget(v as any)}
                                          disabled={!optionsEditMode}
                                        >
                                          <SelectTrigger className="h-8 text-sm mt-1 max-w-xs">
                                            <SelectValue />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="os">{t("vmLxc.scheduled.targetOptionOs")}</SelectItem>
                                            <SelectItem value="app">{t("vmLxc.scheduled.targetOptionApp")}</SelectItem>
                                            <SelectItem value="both">{t("vmLxc.scheduled.targetOptionBoth")}</SelectItem>
                                          </SelectContent>
                                        </Select>
                                      </div>
                                      {scheduleLastRunAt && (
                                        <div className="text-xs text-muted-foreground">
                                          Last run: {new Date(scheduleLastRunAt).toLocaleString()}
                                          {scheduleLastRunStatus && (
                                            <> · <span className={scheduleLastRunStatus === "success" ? "text-green-400" : "text-red-400"}>
                                              {scheduleLastRunStatus === "success" ? "✓ success" : "✗ failed"}
                                            </span></>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )}

                                  {optionsEditMode && scheduleConfigured && (
                                    <div className="flex justify-end">
                                      <button
                                        type="button"
                                        onClick={deleteScheduleFromOptions}
                                        disabled={scheduleSaving}
                                        className="h-8 px-3 text-xs rounded-md border border-red-500/30 bg-red-500/10 hover:bg-red-500/20 text-red-400 transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                        {t("vmLxc.scheduled.deleteButton")}
                                      </button>
                                    </div>
                                  )}


                                  {scheduleError && (
                                    <div className="text-xs text-red-400">{scheduleError}</div>
                                  )}
                                </div>

                                {/* Footer — Edit (view) or Cancel + Save
                                    (edit). Delete schedule lives next
                                    to the Switch above, not here. */}
                                <div className="pt-4 border-t border-border/50 flex items-center justify-end gap-2">
                                  {!optionsEditMode ? (
                                    <button
                                      type="button"
                                      onClick={enterOptionsEdit}
                                      className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5"
                                    >
                                      <Settings2 className="h-3.5 w-3.5" />
                                      {t("vmLxc.options.editButton")}
                                    </button>
                                  ) : (
                                    <>
                                      <button
                                        type="button"
                                        onClick={cancelOptionsEdit}
                                        disabled={scheduleSaving}
                                        className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                                      >
                                        {t("vmLxc.options.cancelButton")}
                                      </button>
                                      <button
                                        type="button"
                                        onClick={saveOptionsEdit}
                                        disabled={scheduleSaving}
                                        className="h-8 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-40 inline-flex items-center gap-1.5"
                                      >
                                        {scheduleSaving
                                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                          : <Check className="h-3.5 w-3.5" />}
                                        {t("vmLxc.options.saveButton")}
                                      </button>
                                    </>
                                  )}
                                </div>
                              </CardContent>
                            </Card>
                          </>
                        )
                      })()}
                  </div>
                )}

                {/* Sprint 13.29: Mount Points Tab — LXC only.
                    Renders configured mpX entries first, then any
                    ad-hoc NFS/CIFS/SMB mounts found inside the
                    container. Capacity comes from the host-side
                    source (PVE storage or `df`) so it's available
                    even when the CT is stopped. */}
                {activeModalTab === "mounts" && selectedVM?.type === "lxc" && (
                  <div className="space-y-4">
                    {loadingMounts ? (
                      <div className="flex items-center justify-center py-12 text-muted-foreground">
                        <Loader2 className="h-5 w-5 animate-spin mr-2" />
                        {t("vmLxc.updatesPanel.loadingMountPoints")}
                      </div>
                    ) : (
                      <>
                        {mountPoints.map((mp) => (
                          <MountPointCard key={mp.mp_index || mp.target} mp={mp} />
                        ))}
                        {adHocMounts.length > 0 && (
                          <>
                            <div className="text-sm font-semibold text-muted-foreground pt-2 border-t border-border">
                              {t("vmLxc.mountedFromContainer")}
                            </div>
                            {adHocMounts.map((mp) => (
                              <MountPointCard key={`adhoc-${mp.target}`} mp={mp} />
                            ))}
                          </>
                        )}
                      </>
                    )}
                  </div>
                )}

                {/* Backups Tab */}
                {activeModalTab === "backups" && (
                  <div className="space-y-4">
                    <Card className="border border-border bg-card/50">
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-4">
                          <div className="flex items-center gap-2">
                            <div className="p-1.5 rounded-md bg-amber-500/10">
                              <Archive className="h-4 w-4 text-amber-500" />
                            </div>
                            <h3 className="text-sm font-semibold text-foreground">{t("vmLxc.backups.title")}</h3>
                          </div>
                          <Button 
                            size="sm"
                            className="h-7 text-xs bg-amber-600/20 border border-amber-600/50 text-amber-400 hover:bg-amber-600/30 gap-1"
                            onClick={openBackupModal}
                            disabled={creatingBackup}
                          >
                            {creatingBackup ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Plus className="h-3 w-3" />
                            )}
                            <span>{t("vmLxc.backups.create")}</span>
                          </Button>
                        </div>
                        
                        {/* Divider */}
                        <div className="border-t border-border/50 mb-4" />
                        
                        {/* Backup List */}
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-xs text-muted-foreground">{t("vmLxc.backups.available")}</span>
                          <Badge variant="secondary" className="text-xs h-5">{vmBackups.length}</Badge>
                        </div>
                        
                        {loadingBackups ? (
                          <div className="flex items-center justify-center py-6 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                            <span className="text-sm">{t("vmLxc.backups.loading")}</span>
                          </div>
                        ) : vmBackups.length === 0 ? (
                          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                            <Archive className="h-12 w-12 mb-3 opacity-30" />
                            <span className="text-sm">{t("vmLxc.backups.empty")}</span>
                            <span className="text-xs mt-1">{t("vmLxc.backups.emptyHint")}</span>
                          </div>
                        ) : (
                          <div className="space-y-2">
                            {vmBackups.map((backup, index) => (
                              <div 
                                key={`backup-${backup.volid}-${index}`}
                                className="flex items-center justify-between p-3 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors"
                              >
                                <div className="flex items-center gap-2 flex-1 min-w-0">
                                  <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
                                  <Clock className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                  <span className="text-sm text-foreground">{backup.date}</span>
                                  <Badge 
                                    variant="outline" 
                                    className={`text-xs ml-auto flex-shrink-0 ${getStorageColor(backup.storage).bg} ${getStorageColor(backup.storage).text} ${getStorageColor(backup.storage).border}`}
                                  >
                                    {backup.storage}
                                  </Badge>
                                </div>
                                <Badge variant="outline" className="font-mono ml-2 flex-shrink-0">
                                  {backup.size_human}
                                </Badge>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                )}

                {/* Firewall Logs Tab — issue #14554. Reads the per-VM/CT
                    log filtered by PVE directly (no host-wide log
                    grep). Loading is lazy and triggered by the tab
                    button's onClick. */}
                {activeModalTab === "firewall" && (
                  <div className="space-y-4">
                    <Card className="border border-border bg-card/50">
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
                          <div className="flex items-center gap-2">
                            <div className="p-1.5 rounded-md bg-orange-500/10">
                              <Shield className="h-4 w-4 text-orange-500" />
                            </div>
                            <h3 className="text-sm font-semibold text-foreground">{t("vmLxc.firewall.title")}</h3>
                            {firewallEnabled && displayedFirewallLogs.length > 0 && (
                              <Badge variant="secondary" className="text-xs h-5 ml-1">
                                {displayedFirewallLogs.length}
                              </Badge>
                            )}
                          </div>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs gap-1"
                            onClick={() => selectedVM && fetchFirewallLog(selectedVM.vmid)}
                            disabled={loadingFirewallLog}
                          >
                            {loadingFirewallLog ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <RefreshCw className="h-3 w-3" />
                            )}
                            <span>{t("vmLxc.firewall.refresh")}</span>
                          </Button>
                        </div>

                        <div className="border-t border-border/50 mb-4" />

                        {loadingFirewallLog ? (
                          <div className="flex items-center justify-center py-6 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                            <span className="text-sm">{t("vmLxc.firewall.loading")}</span>
                          </div>
                        ) : !firewallEnabled ? (
                          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
                            <div className="flex items-start gap-2">
                              <Shield className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                              <div className="space-y-2">
                                <p className="font-medium text-amber-500">
                                  {t("vmLxc.firewall.disabledTitle", {
                                    type: selectedVM?.type === "lxc" ? t("vmLxc.guestTypes.container") : t("vmLxc.guestTypes.vm"),
                                  })}
                                </p>
                                <p className="text-xs text-muted-foreground leading-relaxed">
                                  {t("vmLxc.firewall.disabledHint", {
                                    type: selectedVM?.type === "lxc" ? t("vmLxc.guestTypes.containerUi") : t("vmLxc.guestTypes.vm"),
                                  })}
                                </p>
                              </div>
                            </div>
                          </div>
                        ) : firewallLogError ? (
                          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 text-sm">
                            <div className="flex items-start gap-2">
                              <Shield className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                              <div>
                                <p className="font-medium text-red-500 mb-1">{t("vmLxc.firewall.readFailed")}</p>
                                <p className="text-xs text-muted-foreground break-all">{firewallLogError}</p>
                              </div>
                            </div>
                          </div>
                        ) : displayedFirewallLogs.length === 0 ? (
                          <div className="text-center py-6 text-sm text-muted-foreground">
                            {t("vmLxc.firewall.empty")}
                            <div className="text-xs mt-1">
                              {t("vmLxc.firewall.emptyHint")}
                            </div>
                          </div>
                        ) : (
                          <div className="rounded-md border border-border bg-background/50 max-h-[480px] overflow-y-auto">
                            <pre className="text-[11px] font-mono leading-snug whitespace-pre-wrap break-all p-3">
                              {displayedFirewallLogs.map((entry, idx) => {
                                const text = entry.t || ""
                                // Light colour-coding by the action keyword
                                // PVE emits in the line itself — purely
                                // visual, parsing stays line-by-line so
                                // a malformed entry still renders fine.
                                let actionClass = "text-foreground/90"
                                if (/\bDROP\b/i.test(text)) actionClass = "text-red-400"
                                else if (/\bREJECT\b/i.test(text)) actionClass = "text-orange-400"
                                else if (/\bACCEPT\b/i.test(text)) actionClass = "text-green-400"
                                return (
                                  <div key={`${entry.n}-${idx}`} className={actionClass}>
                                    {text}
                                  </div>
                                )
                              })}
                            </pre>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                )}
              </div>

              <div className="border-t border-border bg-background px-6 py-4 mt-auto shrink-0">
                {/* Terminal button for LXC containers - only when running */}
                {selectedVM?.type === "lxc" && selectedVM?.status === "running" && (
                  <div className="mb-3">
                    <Button
                      className="w-full bg-zinc-600/20 border border-zinc-600/50 text-zinc-300 hover:bg-zinc-600/30"
                      onClick={() => selectedVM && openLxcTerminal(selectedVM.vmid, selectedVM.name)}
                    >
                      <Terminal className="h-4 w-4 mr-2" />
                      {t("vmLxc.openTerminal")}
                    </Button>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    className="w-full bg-green-600/20 border border-green-600/50 text-green-400 hover:bg-green-600/30"
                    disabled={selectedVM?.status === "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "start")}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    {t("vmLxc.actions.start")}
                  </Button>
                  <Button
                    className="w-full bg-blue-600/20 border border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "shutdown")}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    {t("vmLxc.actions.shutdown")}
                  </Button>
                  <Button
                    className="w-full bg-blue-600/20 border border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && setConfirmDestructive({
                      action: "reboot",
                      vmid: selectedVM.vmid,
                      vmName: selectedVM.name,
                    })}
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    {t("vmLxc.actions.reboot")}
                  </Button>
                  <Button
                    className="w-full bg-red-600/20 border border-red-600/50 text-red-400 hover:bg-red-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && setConfirmDestructive({
                      action: "stop",
                      vmid: selectedVM.vmid,
                      vmName: selectedVM.name,
                    })}
                  >
                    <StopCircle className="h-4 w-4 mr-2" />
                    {t("vmLxc.actions.forceStop")}
                  </Button>
                </div>
              </div>
            </>
          ) : (
            selectedVM && (
              <MetricsView
                vmid={selectedVM.vmid}
                vmName={selectedVM.name}
                vmType={selectedVM.type as "qemu" | "lxc"}
                onBack={handleBackToMain}
              />
            )
          )}
        </DialogContent>
      </Dialog>

      {/* Destructive control confirmation (Force Stop / Reboot) */}
      <Dialog
        open={confirmDestructive !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmDestructive(null)
            setConfirmDestructiveTyped("")
          }
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-500">
              <StopCircle className="h-5 w-5" />
              {confirmDestructive?.action === "stop" ? t("vmLxc.confirm.forceStopTitle") : t("vmLxc.confirm.rebootTitle")}{" "}
              VMID {confirmDestructive?.vmid}
            </DialogTitle>
            <DialogDescription>
              {confirmDestructive?.action === "stop"
                ? t("vmLxc.confirm.forceStopDescription")
                : t("vmLxc.confirm.rebootDescription")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-sm">
              {t("vmLxc.confirm.typeToConfirm", { vmid: confirmDestructive?.vmid ?? "" })}
            </p>
            <input
              type="text"
              autoFocus
              autoComplete="off"
              inputMode="numeric"
              value={confirmDestructiveTyped}
              onChange={(e) => setConfirmDestructiveTyped(e.target.value)}
              placeholder={String(confirmDestructive?.vmid ?? "")}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-red-500"
            />
            <p className="text-xs text-muted-foreground">
              {t("vmLxc.confirm.guest")} <span className="font-medium">{confirmDestructive?.vmName}</span>
            </p>
          </div>
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setConfirmDestructive(null)
                setConfirmDestructiveTyped("")
              }}
              disabled={controlLoading}
            >
              {t("actions.cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={
                controlLoading ||
                !confirmDestructive ||
                confirmDestructiveTyped.trim() !== String(confirmDestructive.vmid)
              }
              onClick={async () => {
                if (!confirmDestructive) return
                const { vmid, action } = confirmDestructive
                setConfirmDestructive(null)
                setConfirmDestructiveTyped("")
                await handleVMControl(vmid, action)
              }}
            >
              {controlLoading
                ? t("vmLxc.actions.working")
                : confirmDestructive?.action === "stop"
                ? t("vmLxc.actions.forceStop")
                : t("vmLxc.actions.reboot")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Backup Configuration Modal */}
      <Dialog open={showBackupModal} onOpenChange={setShowBackupModal}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-500">
              <Archive className="h-5 w-5" />
              {t("vmLxc.backupModal.title", {
                type: selectedVM?.type?.toUpperCase() ?? "",
                vmid: selectedVM?.vmid ?? "",
                name: selectedVM?.name ?? "",
              })}
            </DialogTitle>
            <DialogDescription>
              {t("vmLxc.backupModal.description", {
                type: selectedVM?.type === "lxc"
                  ? t("vmLxc.backupModal.typeContainer")
                  : t("vmLxc.backupModal.typeVirtualMachine"),
              })}
            </DialogDescription>
          </DialogHeader>
          
          <div className="grid gap-4 py-4">
            {/* Storage & Mode Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5" />
                  {t("vmLxc.backupModal.storage")}
                </Label>
                <Select value={selectedBackupStorage} onValueChange={setSelectedBackupStorage}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("vmLxc.backupModal.selectStorage")} />
                  </SelectTrigger>
                  <SelectContent>
                    {backupStorages.map((storage) => (
                      <SelectItem key={`modal-storage-${storage.storage}`} value={storage.storage}>
                        {storage.storage} ({storage.avail_human} {t("vmLxc.backupModal.free")})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Settings2 className="h-3.5 w-3.5" />
                  {t("vmLxc.backupModal.mode")}
                </Label>
                <Select value={backupMode} onValueChange={setBackupMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="snapshot">{t("vmLxc.backupModal.modes.snapshot")}</SelectItem>
                    <SelectItem value="suspend">{t("vmLxc.backupModal.modes.suspend")}</SelectItem>
                    <SelectItem value="stop">{t("vmLxc.backupModal.modes.stop")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            {/* Notification Row */}
            <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Bell className="h-3.5 w-3.5" />
                  {t("vmLxc.backupModal.notification")}
                </Label>
              <Select value={backupNotification} onValueChange={setBackupNotification}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">{t("vmLxc.backupModal.useGlobalSettings")}</SelectItem>
                  <SelectItem value="always">{t("vmLxc.backupModal.alwaysNotify")}</SelectItem>
                  <SelectItem value="failure">{t("vmLxc.backupModal.notifyOnFailure")}</SelectItem>
                  <SelectItem value="never">{t("vmLxc.backupModal.neverNotify")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            {/* Protected Checkbox */}
            <div className="flex items-center space-x-2">
              <Checkbox 
                id="backup-protected" 
                checked={backupProtected}
                onCheckedChange={(checked) => setBackupProtected(checked === true)}
              />
              <Label htmlFor="backup-protected" className="text-sm flex items-center gap-1.5 cursor-pointer">
                <Shield className="h-3.5 w-3.5" />
                {t("vmLxc.backupModal.protected")}
              </Label>
            </div>
            
            {/* PBS Change Detection Mode (only for LXC) */}
            {selectedVM?.type === 'lxc' && (
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Settings2 className="h-3.5 w-3.5" />
                  {t("vmLxc.backupModal.pbsChangeMode")}
                  <span className="text-xs text-muted-foreground ml-1">({t("vmLxc.backupModal.forPbsStorage")})</span>
                </Label>
                <Select value={backupPbsChangeMode} onValueChange={setBackupPbsChangeMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">{t("vmLxc.backupModal.changeModes.default")}</SelectItem>
                    <SelectItem value="legacy">{t("vmLxc.backupModal.changeModes.legacy")}</SelectItem>
                    <SelectItem value="data">{t("vmLxc.backupModal.changeModes.data")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            
            {/* Notes */}
            <div className="space-y-2">
              <Label className="text-sm flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                {t("vmLxc.backupModal.notes")}
              </Label>
              <Textarea 
                value={backupNotes}
                onChange={(e) => setBackupNotes(e.target.value)}
                placeholder="{{guestname}}"
                className="min-h-[80px] resize-none"
              />
              <p className="text-xs text-muted-foreground">
                {t("vmLxc.backupModal.variables")}
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 pt-4">
            <Button 
              variant="outline" 
              onClick={() => setShowBackupModal(false)}
              className="flex-1 bg-zinc-800/50 border-zinc-700 text-zinc-300 hover:bg-zinc-700/50"
            >
              {t("actions.cancel")}
            </Button>
            <Button 
              onClick={handleCreateBackup}
              disabled={creatingBackup || !selectedBackupStorage}
              className="flex-1 bg-amber-600/20 border border-amber-600/50 text-amber-400 hover:bg-amber-600/30"
            >
              {creatingBackup ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  {t("vmLxc.backupModal.creating")}
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4 mr-2" />
                  {t("vmLxc.backupModal.submit")}
                </>
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* LXC Terminal Modal */}
      {terminalVmid !== null && (
        <LxcTerminalModal
          open={terminalOpen}
          onClose={() => {
            setTerminalOpen(false)
            setTerminalVmid(null)
            setTerminalVmName("")
          }}
          vmid={terminalVmid}
          vmName={terminalVmName}
        />
      )}

      {/* LXC Update Apply Terminal — streams the apply_updates.sh
          script over WS/PTY (same wiring as the hardware installers).
          On modal close we POST /applied so the notification fires
          and the badge is force-refreshed without waiting 24 h. */}
      {applyVmid !== null && (
        <ScriptTerminalModal
          open={applyOpen}
          onClose={() => {
            setApplyOpen(false)
            setApplyVmid(null)
          }}
          onComplete={handleApplyComplete}
          scriptPath="/usr/local/share/proxmenux/scripts/lxc/apply_updates.sh"
          scriptName="lxc_apply_updates"
          title={`Apply updates — CT ${applyVmid}`}
          description={
            applyTarget === "os"
              ? "Applying OS package updates inside the container..."
              : applyTarget === "app"
                ? "Running the application updater inside the container..."
                : "Applying OS package + application updates inside the container..."
          }
          params={{
            VMID: String(applyVmid),
            TARGET: applyTarget,
            BACKUP: applyBackup ? "1" : "0",
            BACKUP_STORAGE: applyBackupStorage || selectedBackupStorage || "",
            RESTART: applyRestart ? "1" : "0",
            UPDATE_COMMAND: applyUpdateCommand || "",
            APP_NAME: applyAppName || "",
            HELPER_SLUG: selectedVM?.update_check?.helper_slug || "",
          }}
        />
      )}
    </div>
  )
}
