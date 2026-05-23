"use client"

import type React from "react"

import { useState, useMemo, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog"
import { Server, Play, Square, Cpu, MemoryStick, HardDrive, Network, Power, RotateCcw, StopCircle, Container, ChevronDown, ChevronUp, ChevronRight, Terminal, Archive, Plus, Loader2, Clock, Database, Shield, Bell, FileText, Settings2, Activity, Package, RefreshCw } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Checkbox } from "./ui/checkbox"
import { Textarea } from "./ui/textarea"
import { Label } from "./ui/label"
import useSWR from "swr"
import { MetricsView } from "./metrics-dialog"
import { LxcTerminalModal } from "./lxc-terminal-modal"
import { formatStorage } from "../lib/utils"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"
import { fetchApi } from "../lib/api-config"
import DOMPurify from "dompurify"
import { marked } from "marked"

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
}

interface VMData {
  vmid: number
  name: string
  status: string
  type: string
  cpu: number
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

const formatUptime = (seconds: number) => {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${days}d ${hours}h ${minutes}m`
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
    pve_volume: "PVE volume",
    pve_storage_bind: "bind from PVE storage",
    host_bind: "bind from host",
    ad_hoc: "ad-hoc inside CT",
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
            <Badge variant="outline" className="font-mono text-xs">
              {mp.mp_index}
            </Badge>
          )}
          <Badge className={typeBadgeClass[mp.type]}>{typeLabel[mp.type]}</Badge>
          {mp.runtime_fstype && (
            <Badge variant="outline" className="font-mono text-xs">
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
            ? "stale"
            : isDivergent
              ? "not mounted"
              : isHostDetached
                ? "host detached"
                : isReadonly
                  ? "read-only"
                  : mp.runtime_mounted === null
                    ? "stopped"
                    : "mounted"}
        </Badge>
      </div>

      {/* Source / Mounted-at info — what host resource backs the
          mount, and where it shows up inside the CT. The header
          already shows the target but it's worth surfacing the
          source/target relationship explicitly here so the user
          gets the full host→container path at a glance. */}
      <div className="text-sm space-y-1">
        <div>
          <span className="text-muted-foreground">Source (host):</span>{" "}
          <span className="font-mono">{mp.origin_label || mp.source}</span>
          {mp.origin_storage && mp.origin_storage_type && (
            <span className="text-muted-foreground ml-2">
              ({mp.origin_storage_type} storage)
            </span>
          )}
        </div>
        <div>
          <span className="text-muted-foreground">Mounted at (CT):</span>{" "}
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
              <p className="text-xs text-muted-foreground">Total</p>
              <p className="font-medium">{fmtBytes(mp.total_bytes)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Used</p>
              <p className="font-medium">
                {fmtBytes(mp.used_bytes)} {usedPct != null && `(${usedPct}%)`}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Available</p>
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
            <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">
              Mount attributes (LXC config)
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
          <p className="text-xs uppercase tracking-wider text-muted-foreground mb-1.5">
            Runtime mount options
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
  const [activeModalTab, setActiveModalTab] = useState<"status" | "mounts" | "backups" | "updates" | "firewall">("status")

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
              console.log(`[v0] Could not fetch IP for LXC ${lxc.vmid}`)
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
      const msg = error instanceof Error ? error.message : "Unknown error"
      alert(`Failed to start backup: ${msg}`)
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
      const msg = error instanceof Error ? error.message : "Unknown error"
      alert(`Failed to ${action} VM ${vmid}: ${msg}`)
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
      let logText = `=== Logs for ${vmName} (VMID: ${vmid}) ===\n`
      logText += `Node: ${data.node}\n`
      logText += `Type: ${data.type}\n`
      logText += `Total lines: ${data.log_lines}\n`
      logText += `Generated: ${new Date().toISOString()}\n`
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
      uc.security_count > 0 ? ` · ${uc.security_count} security` : ""
    // Tooltip leads with the action when the badge is clickable so the
    // affordance is explicit on hover — the chevron at the end of the
    // badge reinforces the same signal visually for users who don't
    // hover (mobile).
    const tooltipPrefix = onClick ? "Click to view pending packages · " : ""
    const tooltip = `${tooltipPrefix}Last checked: ${last}${secHint}${topNames ? ` · ${topNames}` : ""}`
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
        {uc.count} {compact ? "" : (uc.count === 1 ? "update" : "updates")}
        {/* Chevron only when the badge is wired up as a clickable
            shortcut — its absence on the dashboard card avoids
            implying interactivity where there isn't any (the whole
            row is the click target there). */}
        {onClick && <ChevronRight className={`${iconSize} -mr-0.5 opacity-80`} />}
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

  const { data: systemData } = useSWR<{ memory_total: number; memory_used: number; memory_usage: number }>(
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

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-2 border-muted"></div>
          <div className="absolute inset-0 h-12 w-12 rounded-full border-2 border-transparent border-t-primary animate-spin"></div>
        </div>
        <div className="text-sm font-medium text-foreground">Loading virtual machines...</div>
        <p className="text-xs text-muted-foreground">Fetching VM and LXC container status</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8 text-red-500">Error loading virtual machines: {error.message}</div>
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
      alert("Error saving notes. Please try again.")
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

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs & LXCs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">{safeVMData.length}</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {safeVMData.filter((vm) => vm.status === "running").length} Running
              </Badge>
              <Badge variant="outline" className="vm-badge bg-red-500/10 text-red-500 border-red-500/20">
                {safeVMData.filter((vm) => vm.status === "stopped").length} Stopped
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2 hidden lg:block">Virtual machines configured</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total CPU</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {(safeVMData.reduce((sum, vm) => sum + (vm.cpu || 0), 0) * 100).toFixed(0)}%
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated CPU usage</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Memory Usage (current) */}
            {physicalMemoryGB !== null && usedMemoryGB !== null && memoryUsagePercent !== null ? (
              <div>
                <div className="text-xl lg:text-2xl font-bold text-foreground">{usedMemoryGB.toFixed(1)} GB</div>
                <div className="text-xs text-muted-foreground mt-1">
                  <span className={getMemoryPercentTextColor(memoryUsagePercent)}>
                    {memoryUsagePercent.toFixed(1)}%
                  </span>{" "}
                  of {physicalMemoryGB.toFixed(1)} GB
                </div>
                <Progress value={memoryUsagePercent} className="h-2 [&>div]:bg-blue-500" />
              </div>
            ) : (
              <div>
                <div className="text-xl lg:text-2xl font-bold text-muted-foreground">--</div>
                <div className="text-xs text-muted-foreground mt-1">Loading memory usage...</div>
              </div>
            )}

            {/* Allocated RAM (configured) - Split into Running and Total */}
            <div className="pt-3 border-t border-border">
              {/* Layout para desktop */}
              <div className="hidden lg:flex items-center justify-between">
                <div className="flex gap-6">
                  {/* Running allocation - most important */}
                  <div>
                    <div className="text-lg font-semibold text-foreground">{runningAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Running Allocated</div>
                  </div>
                  {/* Total allocation */}
                  <div>
                    <div className="text-lg font-semibold text-muted-foreground">{totalAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Total Allocated</div>
                  </div>
                </div>
                {physicalMemoryGB !== null && (
                  <div>
                    {isMemoryOvercommit ? (
                      <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                        Exceeds Physical
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                        Within Limits
                      </Badge>
                    )}
                  </div>
                )}
              </div>

              {/* Layout para movil */}
              <div className="lg:hidden space-y-2">
                <div className="flex gap-4">
                  {/* Running allocation */}
                  <div>
                    <div className="text-lg font-semibold text-foreground">{runningAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Running</div>
                  </div>
                  {/* Total allocation */}
                  <div>
                    <div className="text-lg font-semibold text-muted-foreground">{totalAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Total</div>
                  </div>
                </div>
                {physicalMemoryGB !== null && (
                  <div>
                    {isMemoryOvercommit ? (
                      <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                        Exceeds Physical
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                        Within Limits
                      </Badge>
                    )}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Disk</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {formatStorage(safeVMData.reduce((sum, vm) => sum + (vm.maxdisk || 0), 0) / 1024 ** 3)}
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated disk space</p>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-xl lg:text-2xl font-bold text-foreground">
            <Server className="h-6 w-6" />
            Virtual Machines & Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          {safeVMData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No virtual machines found</div>
          ) : (
            <div className="space-y-3">
              {safeVMData.map((vm) => {
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
                        <Badge variant="outline" className={`text-xs flex-shrink-0 ${getStatusColor(vm.status)}`}>
                          {getStatusIcon(vm.status)}
                          {vm.status.toUpperCase()}
                        </Badge>
                        <Badge variant="outline" className={`text-xs flex-shrink-0 ${typeBadge.color}`}>
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
                        <span className="text-sm text-muted-foreground ml-auto">Uptime: {formatUptime(vm.uptime)}</span>
                        {vm.type === "lxc" && renderLxcUpdateBadge(vm.update_check)}
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">CPU Usage</div>
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
                          <div className="text-xs text-muted-foreground mb-1">Memory</div>
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
                          <div className="text-xs text-muted-foreground mb-1">Disk Usage</div>
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
                          <div className="text-xs text-muted-foreground mb-1">Disk I/O</div>
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
                          <div className="text-xs text-muted-foreground mb-1">Network I/O</div>
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
                            {selectedVM.status.toUpperCase()}
                          </Badge>
                          {selectedVM.status === "running" && (
                            <span className="text-sm text-muted-foreground">
                              Uptime: {formatUptime(selectedVM.uptime)}
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
                          {selectedVM.status.toUpperCase()}
                        </Badge>
                        {selectedVM.status === "running" && (
                          <span className="text-sm text-muted-foreground">
                            Uptime: {formatUptime(selectedVM.uptime)}
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
                    Status
                  </span>
                </button>
                {/* Sprint 13.29: Mount Points tab — LXC only, and only
                    when at least one mp / ad-hoc remote mount exists.
                    A CT without mounts gets no empty tab. */}
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
                      Mounts
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
                    Backups
                  </span>
                  {vmBackups.length > 0 && (
                    <Badge variant="secondary" className="text-xs h-5 ml-0.5 sm:ml-1">{vmBackups.length}</Badge>
                  )}
                </button>
                {/* Updates tab — re-added as a first-class nav entry now
                    that the mobile UX collapses inactive tabs to
                    icon-only (so the row no longer overflows on narrow
                    viewports the way it did before v1.2.1.3). LXC only,
                    rendered only when the managed-installs registry has
                    flagged pending updates for this CT, so a CT with
                    nothing pending doesn't get an empty tab. The violet
                    badge in the header stays as a complementary entry
                    point — both routes lead to the same `updates` panel
                    below. */}
                {selectedVM?.type === "lxc" && selectedVM?.update_check?.available && (
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
                      Updates
                    </span>
                    {typeof selectedVM.update_check?.count === "number" && selectedVM.update_check.count > 0 && (
                      <Badge variant="secondary" className="text-xs h-5 ml-0.5 sm:ml-1">
                        {selectedVM.update_check.count}
                      </Badge>
                    )}
                  </button>
                )}
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
                      Firewall
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
                                  <span>CPU Usage</span>
                                  {vmDetails?.config?.cores && (
                                    <span className="text-muted-foreground/60">({vmDetails.config.cores} cores)</span>
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
                                  <span>Memory</span>
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
                                  <span>Disk</span>
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

                              {/* Disk I/O */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <HardDrive className="h-3.5 w-3.5" />
                                  <span>Disk I/O</span>
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

                              {/* Network I/O */}
                              <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                  <Network className="h-3.5 w-3.5" />
                                  <span>Network I/O</span>
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
                        <div className="text-center py-8 text-muted-foreground">Loading configuration...</div>
                      ) : vmDetails?.config ? (
                        <>
                          <Card className="border border-border bg-card/50" key={`config-${selectedVM.vmid}`}>
                            <CardContent className="p-4">
                              <div className="flex items-center justify-between mb-4">
                                <div className="flex items-center gap-2">
                                  <div className="p-1.5 rounded-md bg-blue-500/10">
                                    <Cpu className="h-4 w-4 text-blue-500" />
                                  </div>
                                  <h3 className="text-sm font-semibold text-foreground">Resources</h3>
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
                                        Hide Notes
                                      </>
                                    ) : (
                                      <>
                                        <ChevronDown className="h-3 w-3 mr-1" />
                                        Notes
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
                                        Less Info
                                      </>
                                    ) : (
                                      <>
                                        <ChevronDown className="h-3 w-3 mr-1" />
                                        + Info
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
                                      <span>CPU Cores</span>
                                    </div>
                                    <div className="font-semibold text-blue-500">{vmDetails.config.cores}</div>
                                  </div>
                                )}
                                {vmDetails.config.memory && (
                                  <div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                                      <MemoryStick className="h-3.5 w-3.5" />
                                      <span>Memory</span>
                                    </div>
                                    <div className="font-semibold text-blue-500">{vmDetails.config.memory} MB</div>
                                  </div>
                                )}
                                {vmDetails.config.swap !== undefined && (
                                  <div>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                                      <RotateCcw className="h-3.5 w-3.5" />
                                      <span>Swap</span>
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
                                    IP Addresses
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
                                        {ip} (Bridge)
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {showNotes && (
                                <div className="mt-6 pt-6 border-t border-border">
                                  <div className="flex items-center justify-between mb-3">
                                    <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                                      Notes
                                    </h4>
                                    {!isEditingNotes && (
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={handleEditNotes}
                                        className="text-xs bg-transparent"
                                      >
                                        Edit
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
                                          placeholder="Enter notes here..."
                                        />
                                        <div className="flex gap-2 justify-end">
                                          <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={handleCancelEditNotes}
                                            disabled={savingNotes}
                                          >
                                            Cancel
                                          </Button>
                                          <Button
                                            size="sm"
                                            onClick={handleSaveNotes}
                                            disabled={savingNotes}
                                            className="bg-blue-600 hover:bg-blue-700 text-white"
                                          >
                                            {savingNotes ? "Saving..." : "Save"}
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
                                                Error decoding notes. Please edit to fix.
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
                                        No notes yet. Click Edit to add notes.
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
                                        Container Configuration
                                      </h4>
                                      <div className="space-y-4">
                                        {/* Privileged Status */}
                                        {vmDetails.hardware_info.privileged !== null &&
                                          vmDetails.hardware_info.privileged !== undefined && (
                                            <div>
                                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                                <Shield className="h-3.5 w-3.5" />
                                                <span>Privilege Level</span>
                                              </div>
                                              <Badge
                                                variant="outline"
                                                className={
                                                  vmDetails.hardware_info.privileged
                                                    ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                                    : "bg-green-500/10 text-green-500 border-green-500/20"
                                                }
                                              >
                                                {vmDetails.hardware_info.privileged ? "Privileged" : "Unprivileged"}
                                              </Badge>
                                            </div>
                                          )}

                                        {/* GPU Passthrough with proper keys */}
                                        {vmDetails.hardware_info.gpu_passthrough &&
                                          vmDetails.hardware_info.gpu_passthrough.length > 0 && (
                                            <div>
                                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
                                                <Cpu className="h-3.5 w-3.5" />
                                                <span>GPU Passthrough</span>
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
                                                <span>Hardware Devices</span>
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
                                      Hardware
                                    </h4>
                                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                                      {vmDetails.config.sockets && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">CPU Sockets</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.sockets}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.cpu && (
                                        <div className="col-span-2">
                                          <div className="text-xs text-muted-foreground mb-1">CPU Type</div>
                                          <div className="font-medium text-foreground text-sm font-mono">
                                            {vmDetails.config.cpu}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.numa !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">NUMA</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.numa
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.numa ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.bios && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">BIOS</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.bios}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.machine && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Machine Type</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.machine}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.vga && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">VGA</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.vga}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.agent !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">QEMU Agent</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.agent
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.agent ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.tablet !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Tablet Pointer</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.tablet
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.tablet ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.localtime !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Local Time</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.localtime
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.localtime ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  {/* Storage Section */}
                                  <div>
                                    <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      <HardDrive className="h-4 w-4" />
                                      Storage
                                    </h4>
                                    <div className="space-y-3">
                                      {vmDetails.config.rootfs && (
                                        <div key="rootfs">
                                          <div className="text-xs text-muted-foreground mb-1">Root Filesystem</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.rootfs}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.scsihw && (
                                        <div key="scsihw">
                                          <div className="text-xs text-muted-foreground mb-1">SCSI Controller</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.scsihw}</div>
                                        </div>
                                      )}
                                      {/* Disk Storage with proper keys */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^(scsi|sata|ide|virtio)\d+$/))
                                        .map((diskKey) => (
                                          <div key={`disk-${selectedVM.vmid}-${diskKey}`}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              {diskKey.toUpperCase().replace(/(\d+)/, " $1")}
                                            </div>
                                            <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[diskKey]}
                                            </div>
                                          </div>
                                        ))}
                                      {vmDetails.config.efidisk0 && (
                                        <div key="efidisk0">
                                          <div className="text-xs text-muted-foreground mb-1">EFI Disk</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.efidisk0}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.tpmstate0 && (
                                        <div key="tpmstate0">
                                          <div className="text-xs text-muted-foreground mb-1">TPM State</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.tpmstate0}
                                          </div>
                                        </div>
                                      )}
                                      {/* Mount Points with proper keys */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^mp\d+$/))
                                        .map((mpKey) => (
                                          <div key={`mp-${selectedVM.vmid}-${mpKey}`}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              Mount Point {mpKey.replace("mp", "")}
                                            </div>
                                            <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[mpKey]}
                                            </div>
                                          </div>
                                        ))}
                                    </div>
                                  </div>

                                  {/* Network Section */}
                                  <div>
                                    <h4 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      <Network className="h-4 w-4" />
                                      Network
                                    </h4>
                                    <div className="space-y-3">
                                      {/* Network Interfaces with proper keys */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^net\d+$/))
                                        .map((netKey) => (
                                          <div key={`net-${selectedVM.vmid}-${netKey}`}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              Network Interface {netKey.replace("net", "")}
                                            </div>
                                            <div className="font-medium text-green-500 text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[netKey]}
                                            </div>
                                          </div>
                                        ))}
                                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                        {vmDetails.config.nameserver && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">DNS Nameserver</div>
                                            <div className="font-medium text-foreground font-mono">
                                              {vmDetails.config.nameserver}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.searchdomain && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">Search Domain</div>
                                            <div className="font-medium text-foreground">
                                              {vmDetails.config.searchdomain}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.hostname && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">Hostname</div>
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
                                        PCI Passthrough
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
                                        USB Devices
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
                                        Serial Ports
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

                {/* Updates Tab — LXC only, conditionally rendered.
                    Lives in its own tab so the per-package list (up to
                    30 rows) doesn't blow up the Status tab on mobile.
                    Violet matches the shared "managed updates" theme. */}
                {activeModalTab === "updates" &&
                  selectedVM?.type === "lxc" &&
                  selectedVM?.update_check?.available && (
                    <div className="space-y-4" key={`updates-${selectedVM.vmid}`}>
                      <Card className="border border-border bg-card/50">
                        <CardContent className="p-4">
                          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                            <div className="flex items-center gap-2">
                              <div className="p-1.5 rounded-md bg-violet-500/10">
                                <Package className="h-4 w-4 text-violet-400" />
                              </div>
                              <h3 className="text-sm font-semibold text-foreground">
                                Pending package updates
                              </h3>
                            </div>
                            <Badge
                              variant="outline"
                              className="text-xs bg-violet-500/10 text-violet-400 border-violet-500/30"
                            >
                              {selectedVM.update_check.count} total
                            </Badge>
                          </div>
                          <div className="text-xs text-muted-foreground mb-3 leading-relaxed">
                            Last checked:{" "}
                            {selectedVM.update_check.last_check
                              ? new Date(selectedVM.update_check.last_check).toLocaleString()
                              : "—"}
                            {" · "}Apply with{" "}
                            <code className="text-foreground/80">pct enter {selectedVM.vmid}</code>
                            {" → "}
                            <code className="text-foreground/80">apt update &amp;&amp; apt upgrade</code>
                          </div>
                          {/* Two render modes:
                              • Full list when every pending package fits
                                (registry cap is 30 packages per CT — so
                                CTs with ≤30 updates show every row).
                              • Summary when the CT has more pending than
                                the registry stored. Showing 30 random
                                rows out of 139 misleads the user — a
                                count + security count + "inspect inside"
                                hint is honester. */}
                          {(() => {
                            const stored = selectedVM.update_check.packages?.length || 0
                            const total = selectedVM.update_check.count || 0
                            const sec = selectedVM.update_check.security_count || 0
                            const truncated = total > stored
                            if (!truncated && stored > 0) {
                              return (
                                <div className="border-t border-border divide-y divide-border/50">
                                  {selectedVM.update_check.packages.map((p) => (
                                    <div
                                      key={p.name}
                                      className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-0.5 sm:gap-2 py-2 text-sm"
                                    >
                                      <span className="font-mono text-foreground/90 flex items-center gap-2 min-w-0">
                                        {p.security && (
                                          <Shield
                                            className="h-4 w-4 text-green-500 flex-shrink-0"
                                            aria-label="Security update"
                                          />
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
                            // Truncated OR no per-package detail — render a summary.
                            return (
                              <div className="border-t border-border pt-3 space-y-2 text-sm">
                                <div className="flex items-center gap-2">
                                  <Package className="h-4 w-4 text-violet-400 flex-shrink-0" />
                                  <span>
                                    <span className="font-semibold">{total}</span> package
                                    {total === 1 ? "" : "s"} pending
                                  </span>
                                </div>
                                {sec > 0 && (
                                  <div className="flex items-center gap-2">
                                    <Shield className="h-4 w-4 text-green-500 flex-shrink-0" />
                                    <span>
                                      <span className="font-semibold">{sec}</span> security update
                                      {sec === 1 ? "" : "s"}
                                    </span>
                                  </div>
                                )}
                                <div className="text-xs text-muted-foreground pt-1 leading-relaxed">
                                  Full list available inside the container:{" "}
                                  <code className="text-foreground/80">
                                    pct enter {selectedVM.vmid}
                                  </code>{" "}
                                  →{" "}
                                  <code className="text-foreground/80">apt list --upgradable</code>
                                </div>
                              </div>
                            )
                          })()}
                        </CardContent>
                      </Card>
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
                        Loading mount points…
                      </div>
                    ) : (
                      <>
                        {mountPoints.map((mp) => (
                          <MountPointCard key={mp.mp_index || mp.target} mp={mp} />
                        ))}
                        {adHocMounts.length > 0 && (
                          <>
                            <div className="text-sm font-semibold text-muted-foreground pt-2 border-t border-border">
                              Mounted from inside the container
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
                            <h3 className="text-sm font-semibold text-foreground">Backups</h3>
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
                            <span>Create Backup</span>
                          </Button>
                        </div>
                        
                        {/* Divider */}
                        <div className="border-t border-border/50 mb-4" />
                        
                        {/* Backup List */}
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-xs text-muted-foreground">Available backups</span>
                          <Badge variant="secondary" className="text-xs h-5">{vmBackups.length}</Badge>
                        </div>
                        
                        {loadingBackups ? (
                          <div className="flex items-center justify-center py-6 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                            <span className="text-sm">Loading backups...</span>
                          </div>
                        ) : vmBackups.length === 0 ? (
                          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                            <Archive className="h-12 w-12 mb-3 opacity-30" />
                            <span className="text-sm">No backups found</span>
                            <span className="text-xs mt-1">Create your first backup using the button above</span>
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
                                <Badge variant="outline" className="text-xs font-mono ml-2 flex-shrink-0">
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
                            <h3 className="text-sm font-semibold text-foreground">Firewall Logs</h3>
                            {firewallEnabled && firewallLogs.length > 0 && (
                              <Badge variant="secondary" className="text-xs h-5 ml-1">
                                {firewallLogs.length}
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
                            <span>Refresh</span>
                          </Button>
                        </div>

                        <div className="border-t border-border/50 mb-4" />

                        {loadingFirewallLog ? (
                          <div className="flex items-center justify-center py-6 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                            <span className="text-sm">Loading firewall log…</span>
                          </div>
                        ) : !firewallEnabled ? (
                          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
                            <div className="flex items-start gap-2">
                              <Shield className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                              <div className="space-y-2">
                                <p className="font-medium text-amber-500">
                                  Firewall is not enabled for this {selectedVM?.type === "lxc" ? "container" : "VM"}
                                </p>
                                <p className="text-xs text-muted-foreground leading-relaxed">
                                  Enable it in the Proxmox UI under{" "}
                                  <strong>
                                    {selectedVM?.type === "lxc" ? "Container" : "VM"} → Firewall → Options
                                  </strong>{" "}
                                  and add at least one rule with <code>log: info</code> (or higher) so packets start
                                  being recorded. New entries will appear here automatically on the next refresh.
                                </p>
                              </div>
                            </div>
                          </div>
                        ) : firewallLogError ? (
                          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 text-sm">
                            <div className="flex items-start gap-2">
                              <Shield className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                              <div>
                                <p className="font-medium text-red-500 mb-1">Failed to read firewall log</p>
                                <p className="text-xs text-muted-foreground break-all">{firewallLogError}</p>
                              </div>
                            </div>
                          </div>
                        ) : firewallLogs.length === 0 ? (
                          <div className="text-center py-6 text-sm text-muted-foreground">
                            No firewall events recorded yet.
                            <div className="text-xs mt-1">
                              Rules with <code>log: info</code> (or higher) will populate this view as packets arrive.
                            </div>
                          </div>
                        ) : (
                          <div className="rounded-md border border-border bg-background/50 max-h-[480px] overflow-y-auto">
                            <pre className="text-[11px] font-mono leading-snug whitespace-pre-wrap break-all p-3">
                              {firewallLogs.map((entry, idx) => {
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
                      Open Terminal
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
                    Start
                  </Button>
                  <Button
                    className="w-full bg-blue-600/20 border border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "shutdown")}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    Shutdown
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
                    Reboot
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
                    Force Stop
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
              {confirmDestructive?.action === "stop" ? "Force Stop" : "Reboot"}{" "}
              VMID {confirmDestructive?.vmid}
            </DialogTitle>
            <DialogDescription>
              {confirmDestructive?.action === "stop"
                ? "This skips the guest OS shutdown sequence and can corrupt running databases or filesystems. The guest is killed immediately."
                : "This forces a reboot without waiting for the guest OS to flush pending writes. Use a graceful Shutdown when possible."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-sm">
              Type <span className="font-mono font-bold">{confirmDestructive?.vmid}</span> to confirm:
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
              Guest: <span className="font-medium">{confirmDestructive?.vmName}</span>
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
              Cancel
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
                ? "Working..."
                : confirmDestructive?.action === "stop"
                ? "Force Stop"
                : "Reboot"}
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
              Backup {selectedVM?.type?.toUpperCase()} {selectedVM?.vmid} ({selectedVM?.name})
            </DialogTitle>
            <DialogDescription>
              Configure backup options for this {selectedVM?.type === 'lxc' ? 'container' : 'virtual machine'}
            </DialogDescription>
          </DialogHeader>
          
          <div className="grid gap-4 py-4">
            {/* Storage & Mode Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5" />
                  Storage
                </Label>
                <Select value={selectedBackupStorage} onValueChange={setSelectedBackupStorage}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select storage" />
                  </SelectTrigger>
                  <SelectContent>
                    {backupStorages.map((storage) => (
                      <SelectItem key={`modal-storage-${storage.storage}`} value={storage.storage}>
                        {storage.storage} ({storage.avail_human} free)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Settings2 className="h-3.5 w-3.5" />
                  Mode
                </Label>
                <Select value={backupMode} onValueChange={setBackupMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="snapshot">Snapshot</SelectItem>
                    <SelectItem value="suspend">Suspend</SelectItem>
                    <SelectItem value="stop">Stop</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            {/* Notification Row */}
            <div className="space-y-2">
              <Label className="text-sm flex items-center gap-1.5">
                <Bell className="h-3.5 w-3.5" />
                Notification
              </Label>
              <Select value={backupNotification} onValueChange={setBackupNotification}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Use global settings</SelectItem>
                  <SelectItem value="always">Always notify</SelectItem>
                  <SelectItem value="failure">Notify on failure</SelectItem>
                  <SelectItem value="never">Never notify</SelectItem>
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
                Protected (prevent accidental deletion)
              </Label>
            </div>
            
            {/* PBS Change Detection Mode (only for LXC) */}
            {selectedVM?.type === 'lxc' && (
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Settings2 className="h-3.5 w-3.5" />
                  PBS change detection mode
                  <span className="text-xs text-muted-foreground ml-1">(for PBS storage)</span>
                </Label>
                <Select value={backupPbsChangeMode} onValueChange={setBackupPbsChangeMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Default</SelectItem>
                    <SelectItem value="legacy">Legacy</SelectItem>
                    <SelectItem value="data">Data</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            
            {/* Notes */}
            <div className="space-y-2">
              <Label className="text-sm flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Notes
              </Label>
              <Textarea 
                value={backupNotes}
                onChange={(e) => setBackupNotes(e.target.value)}
                placeholder="{{guestname}}"
                className="min-h-[80px] resize-none"
              />
              <p className="text-xs text-muted-foreground">
                {'Variables: {{cluster}}, {{guestname}}, {{node}}, {{vmid}}'}
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 pt-4">
            <Button 
              variant="outline" 
              onClick={() => setShowBackupModal(false)}
              className="flex-1 bg-zinc-800/50 border-zinc-700 text-zinc-300 hover:bg-zinc-700/50"
            >
              Cancel
            </Button>
            <Button 
              onClick={handleCreateBackup}
              disabled={creatingBackup || !selectedBackupStorage}
              className="flex-1 bg-amber-600/20 border border-amber-600/50 text-amber-400 hover:bg-amber-600/30"
            >
              {creatingBackup ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Creating...
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4 mr-2" />
                  Backup
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
    </div>
  )
}
