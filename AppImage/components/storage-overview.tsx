"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { HardDrive, Database, AlertTriangle, CheckCircle2, XCircle, Square, Thermometer, Archive, Info, Clock, Usb, Server, Activity, FileText, Play, Loader2, Download, Plus, Trash2, Settings } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { fetchApi } from "../lib/api-config"
import { DiskTemperatureDetailModal } from "./disk-temperature-detail-modal"
import { DiskTemperatureCard } from "./disk-temperature-card"
import {
  useDiskTempThresholds,
  loadDiskTempThresholds,
  getDiskTempThresholdsSync,
  type DiskTempMap,
} from "../lib/health-thresholds"

interface DiskInfo {
  name: string
  size?: number // Changed from string to number (KB) for formatMemory()
  size_formatted?: string // Added formatted size string for display
  temperature: number
  health: string
  power_on_hours?: number
  smart_status?: string
  model?: string
  serial?: string
  mountpoint?: string
  fstype?: string
  total?: number
  used?: number
  available?: number
  usage_percent?: number
  reallocated_sectors?: number
  pending_sectors?: number
  crc_errors?: number
  rotation_rate?: number
  power_cycles?: number
  percentage_used?: number // NVMe: Percentage Used (0-100)
  media_wearout_indicator?: number // SSD: Media Wearout Indicator
  wear_leveling_count?: number // SSD: Wear Leveling Count
  total_lbas_written?: number // SSD/NVMe: Total LBAs Written (GB)
  ssd_life_left?: number // SSD: SSD Life Left percentage
  io_errors?: {
    count: number
    severity: string
    sample: string
    reason: string
    error_type?: string  // 'io' | 'filesystem'
  }
  observations_count?: number
  connection_type?: 'usb' | 'sata' | 'nvme' | 'sas' | 'internal' | 'unknown'
  removable?: boolean
  is_system_disk?: boolean
  system_usage?: string[]
}

interface DiskObservation {
  id: number
  error_type: string
  error_signature: string
  first_occurrence: string
  last_occurrence: string
  occurrence_count: number
  raw_message: string
  severity: string
  dismissed: boolean
  device_name: string
  serial: string
  model: string
}

interface ZFSPool {
  name: string
  size: string
  allocated: string
  free: string
  health: string
}

interface StorageData {
  total: number
  used: number
  available: number
  disks: DiskInfo[]
  zfs_pools: ZFSPool[]
  disk_count: number
  healthy_disks: number
  warning_disks: number
  critical_disks: number
  error?: string
}

interface ProxmoxStorage {
  name: string
  type: string
  status: string
  total: number
  used: number
  available: number
  percent: number
  node: string // Added node property for detailed debug logging
}

interface ProxmoxStorageData {
  storage: ProxmoxStorage[]
  error?: string
}

// Sprint 13: shape returned by /api/mounts. Lists every NFS/CIFS/SMB
// mount on the host with a per-mount health status — complements the
// PVE-storage list above with arbitrary mounts done outside PVE
// (fstab, manual `mount` commands).
interface RemoteMount {
  source: string
  target: string
  fstype: string
  options: string
  readonly: boolean
  reachable: boolean
  error?: string | null
  status: "ok" | "stale" | "readonly"
  // Sprint 13.16: extra fields the modal renders. Backend fills them
  // when the mount is reachable; nullable when df couldn't run (stale).
  proxmox_managed?: boolean
  total_bytes?: number | null
  used_bytes?: number | null
  available_bytes?: number | null
  // Sprint 13.24: present only on LXC-internal mounts.
  lxc_id?: string
  lxc_name?: string
  lxc_pid?: string
}

interface RemoteMountsData {
  mounts: RemoteMount[]
  lxc_mounts?: RemoteMount[]
  available: boolean
  error?: string
}

const formatStorage = (sizeInGB: number): string => {
  if (sizeInGB < 1) {
    // Less than 1 GB, show in MB
    return `${(sizeInGB * 1024).toFixed(1)} MB`
  } else if (sizeInGB > 999) {
    return `${(sizeInGB / 1024).toFixed(2)} TB`
  } else {
    // Between 1 and 999 GB, show in GB
    return `${sizeInGB.toFixed(2)} GB`
  }
}

// Translate the short ATA/SCSI error codes that appear inside `{ ... }`
// in a raw kernel observation (e.g. `error: { IDNF }`) into a one-line
// human description. Mirrors `_translate_ata_error` in
// notification_events.py — kept here so both the dialog and the printable
// SMART report can render a friendlier line under the raw message
// without round-tripping to the backend. Returns null when no recognised
// code is present, so the caller hides the extra line for non-ATA rows.
function translateAtaError(raw: string): string | null {
  if (!raw) return null
  const ATA_CODES: Record<string, string> = {
    IDNF: 'Sector address not found — possible bad sector or cable issue',
    UNC: 'Uncorrectable read error — bad sector',
    ABRT: 'Command aborted by drive',
    AMNF: 'Address mark not found — surface damage',
    TK0NF: 'Track 0 not found — drive hardware failure',
    BBK: 'Bad block detected',
    ICRC: 'Interface CRC error — cable or connector issue',
    MC: 'Media changed',
    MCR: 'Media change requested',
    WP: 'Write protected',
  }
  const m = raw.match(/\{\s*([A-Z0-9 ]+)\s*\}/)
  if (!m) return null
  const codes = m[1].split(/\s+/).filter(Boolean)
  const seen = new Set<string>()
  const out: string[] = []
  for (const c of codes) {
    const desc = ATA_CODES[c]
    if (desc && !seen.has(c)) {
      seen.add(c)
      out.push(desc)
    }
  }
  return out.length ? out.join('; ') : null
}

export function StorageOverview() {
  // User-configurable disk temperature thresholds (Settings → Health
  // Monitor Thresholds). Until the API responds the hook returns
  // sensible defaults from `lib/health-thresholds`, so first paint
  // never blocks on the network.
  const dtThresholds = useDiskTempThresholds()

  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [proxmoxStorage, setProxmoxStorage] = useState<ProxmoxStorageData | null>(null)
  const [remoteMounts, setRemoteMounts] = useState<RemoteMount[]>([])
  // Sprint 13.19: detail modal for a single remote mount. Tracks the
  // mount object itself rather than just an id so a stale data fetch
  // can't leave the modal showing nothing.
  const [mountDetail, setMountDetail] = useState<RemoteMount | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedDisk, setSelectedDisk] = useState<DiskInfo | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [diskObservations, setDiskObservations] = useState<DiskObservation[]>([])
  const [loadingObservations, setLoadingObservations] = useState(false)
  const [activeModalTab, setActiveModalTab] = useState<"overview" | "smart" | "history" | "schedule">("overview")
  const [smartJsonData, setSmartJsonData] = useState<{
    has_data: boolean
    data?: Record<string, unknown>
    timestamp?: string
    test_type?: string
    history?: Array<{ filename: string; timestamp: string; test_type: string; date_readable: string }>
  } | null>(null)
  const [loadingSmartJson, setLoadingSmartJson] = useState(false)
  const [tempHistoryDisk, setTempHistoryDisk] = useState<DiskInfo | null>(null)

  const fetchStorageData = async () => {
    try {
      const [data, proxmoxData, mountsData] = await Promise.all([
        fetchApi<StorageData>("/api/storage"),
        fetchApi<ProxmoxStorageData>("/api/proxmox-storage"),
        // Sprint 13 — host-level NFS/CIFS/SMB mounts. Wrapped in catch
        // so a failure here doesn't blank the whole storage tab.
        fetchApi<RemoteMountsData>("/api/mounts").catch(() => ({ mounts: [], available: false } as RemoteMountsData)),
      ])

      setStorageData(data)
      setProxmoxStorage(proxmoxData)
      setRemoteMounts(mountsData?.mounts || [])
    } catch (error) {
      console.error("Error fetching storage data:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStorageData()
    const interval = setInterval(fetchStorageData, 30000)
    return () => clearInterval(interval)
  }, [])

  const getHealthIcon = (health: string) => {
    switch (health.toLowerCase()) {
      case "healthy":
      case "passed":
      case "online":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case "warning":
        return <AlertTriangle className="h-5 w-5 text-yellow-500" />
      case "critical":
      case "failed":
      case "degraded":
        return <XCircle className="h-5 w-5 text-red-500" />
      default:
        return <AlertTriangle className="h-5 w-5 text-gray-500" />
    }
  }

  const getHealthBadge = (health: string) => {
    switch (health.toLowerCase()) {
      case "healthy":
      case "passed":
      case "online":
        return <Badge className="bg-green-500/10 text-green-500 border-green-500/20">Healthy</Badge>
      case "warning":
        return <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">Warning</Badge>
      case "critical":
      case "failed":
      case "degraded":
        return <Badge className="bg-red-500/10 text-red-500 border-red-500/20">Critical</Badge>
      default:
        return <Badge className="bg-gray-500/10 text-gray-500 border-gray-500/20">Unknown</Badge>
    }
  }

  const getTempColor = (temp: number, diskName?: string, rotationRate?: number) => {
    if (temp === 0) return "text-gray-500"

    // Resolve disk class → threshold pair from the user-configurable
    // backend (single source of truth). The semantics: temp BELOW warn
    // is green, between warn and hot is amber, hot or above is red.
    let cls: keyof DiskTempMap = "HDD"
    if (diskName?.startsWith("nvme")) {
      cls = "NVMe"
    } else if (!rotationRate || rotationRate === 0) {
      cls = "SSD"
    }
    const t = dtThresholds[cls]
    if (temp >= t.hot) return "text-red-500"
    if (temp >= t.warn) return "text-yellow-500"
    return "text-green-500"
  }

  const formatHours = (hours: number) => {
    if (hours === 0) return "N/A"
    const years = Math.floor(hours / 8760)
    const days = Math.floor((hours % 8760) / 24)
    if (years > 0) {
      return `${years}y ${days}d`
    }
    return `${days}d`
  }

  const formatRotationRate = (rpm: number | undefined) => {
    if (!rpm || rpm === 0) return "SSD"
    return `${rpm.toLocaleString()} RPM`
  }

  const getDiskType = (diskName: string, rotationRate: number | undefined): string => {
    if (diskName.startsWith("nvme")) {
      return "NVMe"
    }
    // rotation_rate = -1 means HDD but RPM is unknown (detected via kernel rotational flag)
    // rotation_rate = 0 or undefined means SSD
    // rotation_rate > 0 means HDD with known RPM
    if (rotationRate === -1) {
      return "HDD"
    }
    if (!rotationRate || rotationRate === 0) {
      return "SSD"
    }
    return "HDD"
  }

  const getDiskTypeBadge = (diskName: string, rotationRate: number | undefined) => {
    const diskType = getDiskType(diskName, rotationRate)
    const badgeStyles: Record<string, { className: string; label: string }> = {
      NVMe: {
        className: "bg-purple-500/10 text-purple-500 border-purple-500/20",
        label: "NVMe",
      },
      SSD: {
        className: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
        label: "SSD",
      },
      HDD: {
        className: "bg-blue-500/10 text-blue-500 border-blue-500/20",
        label: "HDD",
      },
    }
    return badgeStyles[diskType]
  }

  const handleDiskClick = async (disk: DiskInfo) => {
    setSelectedDisk(disk)
    setDetailsOpen(true)
    setDiskObservations([])
    setSmartJsonData(null)

    // Fetch observations and SMART JSON data in parallel
    setLoadingObservations(true)
    setLoadingSmartJson(true)
    
    // Fetch observations
    const fetchObservations = async () => {
      try {
        const params = new URLSearchParams()
        if (disk.name) params.set('device', disk.name)
        if (disk.serial && disk.serial !== 'Unknown') params.set('serial', disk.serial)
        const data = await fetchApi<{ observations: DiskObservation[] }>(`/api/storage/observations?${params.toString()}`)
        setDiskObservations(data.observations || [])
      } catch {
        setDiskObservations([])
      } finally {
        setLoadingObservations(false)
      }
    }
    
    // Fetch SMART JSON data from real test if available
    const fetchSmartJson = async () => {
      try {
        const data = await fetchApi<{
          has_data: boolean
          data?: Record<string, unknown>
          timestamp?: string
          test_type?: string
        }>(`/api/storage/smart/${disk.name}/latest`)
        setSmartJsonData(data)
      } catch {
        setSmartJsonData({ has_data: false })
      } finally {
        setLoadingSmartJson(false)
      }
    }
    
    // Run both in parallel
    await Promise.all([fetchObservations(), fetchSmartJson()])
  }

  const formatObsDate = (iso: string) => {
    if (!iso) return 'N/A'
    try {
      const d = new Date(iso)
      const day = d.getDate().toString().padStart(2, '0')
      const month = (d.getMonth() + 1).toString().padStart(2, '0')
      const year = d.getFullYear()
      const hours = d.getHours().toString().padStart(2, '0')
      const mins = d.getMinutes().toString().padStart(2, '0')
      return `${day}/${month}/${year} ${hours}:${mins}`
    } catch { return iso }
  }

  const obsTypeLabel = (t: string) =>
    ({ smart_error: 'SMART Error', io_error: 'I/O Error', filesystem_error: 'Filesystem Error', zfs_pool_error: 'ZFS Pool Error', connection_error: 'Connection Error' }[t] || t)

  const getStorageTypeBadge = (type: string) => {
    const typeColors: Record<string, string> = {
      pbs: "bg-purple-500/10 text-purple-500 border-purple-500/20",
      dir: "bg-blue-500/10 text-blue-500 border-blue-500/20",
      lvmthin: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
      zfspool: "bg-green-500/10 text-green-500 border-green-500/20",
      nfs: "bg-orange-500/10 text-orange-500 border-orange-500/20",
      cifs: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    }
    // Sprint 13: /proc/mounts reports `nfs4`, `cifs2`, `smb3`, `smbfs`,
    // etc. PVE storage types are clean (`nfs`, `cifs`) but the kernel
    // mount types carry version suffixes. Match the family so the
    // Remote Mounts list shows the same colour as the matching PVE
    // storage row instead of falling through to the grey default.
    const lower = type.toLowerCase()
    if (typeColors[lower]) return typeColors[lower]
    if (lower.startsWith("nfs")) return typeColors.nfs
    if (lower.startsWith("cifs") || lower.startsWith("smb")) return typeColors.cifs
    return "bg-gray-500/10 text-gray-500 border-gray-500/20"
  }

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case "active":
      case "online":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case "namespace_restricted":
        return <CheckCircle2 className="h-5 w-5 text-blue-400" />
      case "inactive":
      case "offline":
        return <Square className="h-5 w-5 text-gray-500" />
      case "error":
      case "failed":
        return <AlertTriangle className="h-5 w-5 text-red-500" />
      default:
        return <CheckCircle2 className="h-5 w-5 text-gray-500" />
    }
  }

  const getWearIndicator = (disk: DiskInfo): { value: number; label: string } | null => {
    const diskType = getDiskType(disk.name, disk.rotation_rate)

    if (diskType === "NVMe" && disk.percentage_used !== undefined && disk.percentage_used !== null) {
      return { value: disk.percentage_used, label: "Percentage Used" }
    }

    if (diskType === "SSD") {
      // Prioridad: Media Wearout Indicator > Wear Leveling Count > SSD Life Left
      if (disk.media_wearout_indicator !== undefined && disk.media_wearout_indicator !== null) {
        return { value: disk.media_wearout_indicator, label: "Media Wearout" }
      }
      if (disk.wear_leveling_count !== undefined && disk.wear_leveling_count !== null) {
        return { value: disk.wear_leveling_count, label: "Wear Level" }
      }
      if (disk.ssd_life_left !== undefined && disk.ssd_life_left !== null) {
        return { value: 100 - disk.ssd_life_left, label: "Life Used" }
      }
    }

    return null
  }

  const getWearColor = (wearPercent: number): string => {
    if (wearPercent <= 50) return "text-green-500"
    if (wearPercent <= 80) return "text-yellow-500"
    return "text-red-500"
  }

  const getEstimatedLifeRemaining = (disk: DiskInfo): string | null => {
    const wearIndicator = getWearIndicator(disk)
    if (!wearIndicator || !disk.power_on_hours || disk.power_on_hours === 0) {
      return null
    }

    const wearPercent = wearIndicator.value
    const hoursUsed = disk.power_on_hours

    // If the drive reports zero wear we cannot extrapolate (division by zero).
    // The drive is alive and healthy — return a friendlier label than "N/A",
    // which users mistook for "the monitor is broken". A new drive can sit at
    // 0% wear for hundreds of hours before the first measurable tick.
    if (wearPercent === 0) {
      return "No wear detected yet"
    }

    // Calcular horas totales estimadas: hoursUsed / (wearPercent / 100)
    const totalEstimatedHours = hoursUsed / (wearPercent / 100)
    const remainingHours = totalEstimatedHours - hoursUsed

    // Convertir a años
    const remainingYears = remainingHours / 8760 // 8760 horas en un año

    if (remainingYears < 1) {
      const remainingMonths = Math.round(remainingYears * 12)
      return `~${remainingMonths} months`
    }

    return `~${remainingYears.toFixed(1)} years`
  }

  const getDiskHealthBreakdown = () => {
    if (!storageData || !storageData.disks) {
      return { normal: 0, warning: 0, critical: 0 }
    }

    let normal = 0
    let warning = 0
    let critical = 0

    storageData.disks.forEach((disk) => {
      if (disk.temperature === 0) {
        // No temperature reading available — count as normal so a
        // missing sensor doesn't inflate the warning count.
        normal++
        return
      }

      // Reuse the exact threshold lookup that the per-disk badge
      // (`getTempColor`) uses, so the green / amber / red colour in
      // the disk card and the "X normal, Y warning, Z critical" tally
      // at the top of the page always agree.
      //
      // Previously this breakdown carried its own hardcoded ladder
      // (HDD ≤45 normal, ≤55 warning, …) which was far stricter than
      // the configurable defaults from `useDiskTempThresholds`
      // (HDD warn 60, hot 65). A disk at 48 °C therefore showed a
      // green badge but was counted as "warning" in the summary —
      // exactly the case the user reported. Driving both from the
      // same source (`dtThresholds`) means the user-tunable values
      // under Settings → Health Monitor Thresholds → Disk temperature
      // now apply to the breakdown as well, and the displayed colour
      // is always the source of truth.
      const diskType = getDiskType(disk.name, disk.rotation_rate)
      const cls: keyof DiskTempMap =
        diskType === "NVMe" ? "NVMe" : diskType === "SSD" ? "SSD" : "HDD"
      const t = dtThresholds[cls]
      if (disk.temperature >= t.hot) critical++
      else if (disk.temperature >= t.warn) warning++
      else normal++
    })

    return { normal, warning, critical }
  }

  const getDiskTypesBreakdown = () => {
    if (!storageData || !storageData.disks) {
      return { nvme: 0, ssd: 0, hdd: 0, usb: 0 }
    }

    let nvme = 0
    let ssd = 0
    let hdd = 0
    let usb = 0

    storageData.disks.forEach((disk) => {
      if (disk.connection_type === 'usb') {
        usb++
        return
      }
      const diskType = getDiskType(disk.name, disk.rotation_rate)
      if (diskType === "NVMe") nvme++
      else if (diskType === "SSD") ssd++
      else if (diskType === "HDD") hdd++
    })

    return { nvme, ssd, hdd, usb }
  }

  const getWearProgressColor = (wearPercent: number): string => {
    if (wearPercent < 70) return "[&>div]:bg-blue-500"
    if (wearPercent < 85) return "[&>div]:bg-yellow-500"
    return "[&>div]:bg-red-500"
  }

  const getUsageColor = (percent: number): string => {
    if (percent < 70) return "text-blue-500"
    if (percent < 85) return "text-yellow-500"
    if (percent < 95) return "text-orange-500"
    return "text-red-500"
  }

  const diskHealthBreakdown = getDiskHealthBreakdown()
  const diskTypesBreakdown = getDiskTypesBreakdown()

  const localStorageTypes = ["dir", "lvmthin", "lvm", "zfspool", "btrfs"]
  const remoteStorageTypes = ["pbs", "nfs", "cifs", "smb", "glusterfs", "iscsi", "iscsidirect", "rbd", "cephfs"]

  const totalLocalUsed =
    proxmoxStorage?.storage
      .filter(
        (storage) =>
          storage &&
          storage.name &&
          storage.status === "active" &&
          storage.total > 0 &&
          storage.used >= 0 &&
          storage.available >= 0 &&
          localStorageTypes.includes(storage.type.toLowerCase()),
      )
      .reduce((sum, storage) => sum + storage.used, 0) || 0

  const totalLocalCapacity =
    proxmoxStorage?.storage
      .filter(
        (storage) =>
          storage &&
          storage.name &&
          storage.status === "active" &&
          storage.total > 0 &&
          storage.used >= 0 &&
          storage.available >= 0 &&
          localStorageTypes.includes(storage.type.toLowerCase()),
      )
      .reduce((sum, storage) => sum + storage.total, 0) || 0

  const localUsagePercent = totalLocalCapacity > 0 ? ((totalLocalUsed / totalLocalCapacity) * 100).toFixed(2) : "0.00"

  const totalRemoteUsed =
    proxmoxStorage?.storage
      .filter(
        (storage) =>
          storage &&
          storage.name &&
          storage.status === "active" &&
          storage.total > 0 &&
          storage.used >= 0 &&
          storage.available >= 0 &&
          remoteStorageTypes.includes(storage.type.toLowerCase()),
      )
      .reduce((sum, storage) => sum + storage.used, 0) || 0

  const totalRemoteCapacity =
    proxmoxStorage?.storage
      .filter(
        (storage) =>
          storage &&
          storage.name &&
          storage.status === "active" &&
          storage.total > 0 &&
          storage.used >= 0 &&
          storage.available >= 0 &&
          remoteStorageTypes.includes(storage.type.toLowerCase()),
      )
      .reduce((sum, storage) => sum + storage.total, 0) || 0

  const remoteUsagePercent =
    totalRemoteCapacity > 0 ? ((totalRemoteUsed / totalRemoteCapacity) * 100).toFixed(2) : "0.00"

  const remoteStorageCount =
    proxmoxStorage?.storage.filter(
      (storage) =>
        storage &&
        storage.name &&
        storage.status === "active" &&
        remoteStorageTypes.includes(storage.type.toLowerCase()),
    ).length || 0

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-2 border-muted"></div>
          <div className="absolute inset-0 h-12 w-12 rounded-full border-2 border-transparent border-t-primary animate-spin"></div>
        </div>
        <div className="text-sm font-medium text-foreground">Loading storage data...</div>
        <p className="text-xs text-muted-foreground">Scanning disks, partitions and storage pools</p>
      </div>
    )
  }

  if (!storageData || storageData.error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-500">Error loading storage data: {storageData?.error || "Unknown error"}</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Storage Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold">{storageData.total.toFixed(1)} TB</div>
            <p className="text-xs text-muted-foreground mt-1">{storageData.disk_count} physical disks</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Local Used</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold">{formatStorage(totalLocalUsed)}</div>
            <p className="text-xs mt-1">
              <span className={getUsageColor(Number.parseFloat(localUsagePercent))}>{localUsagePercent}%</span>
              <span className="text-muted-foreground"> of </span>
              <span className="text-green-500">{formatStorage(totalLocalCapacity)}</span>
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Remote Used</CardTitle>
            <Archive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold">
              {remoteStorageCount > 0 ? formatStorage(totalRemoteUsed) : "None"}
            </div>
            <p className="text-xs mt-1">
              {remoteStorageCount > 0 ? (
                <>
                  <span className={getUsageColor(Number.parseFloat(remoteUsagePercent))}>{remoteUsagePercent}%</span>
                  <span className="text-muted-foreground"> of </span>
                  <span className="text-green-500">{formatStorage(totalRemoteCapacity)}</span>
                </>
              ) : (
                <span className="text-muted-foreground">No remote storage</span>
              )}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Physical Disks</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold">{storageData.disk_count} disks</div>
            <div className="space-y-1 mt-1">
              <p className="text-xs">
                {diskTypesBreakdown.nvme > 0 && <span className="text-purple-500">{diskTypesBreakdown.nvme} NVMe</span>}
                {diskTypesBreakdown.ssd > 0 && (
                  <>
                    {diskTypesBreakdown.nvme > 0 && ", "}
                    <span className="text-cyan-500">{diskTypesBreakdown.ssd} SSD</span>
                  </>
                )}
                {diskTypesBreakdown.hdd > 0 && (
                  <>
                    {(diskTypesBreakdown.nvme > 0 || diskTypesBreakdown.ssd > 0) && ", "}
                    <span className="text-blue-500">{diskTypesBreakdown.hdd} HDD</span>
                  </>
                )}
                {diskTypesBreakdown.usb > 0 && (
                  <>
                    {(diskTypesBreakdown.nvme > 0 || diskTypesBreakdown.ssd > 0 || diskTypesBreakdown.hdd > 0) && ", "}
                    <span className="text-orange-400">{diskTypesBreakdown.usb} USB</span>
                  </>
                )}
              </p>
              <p className="text-xs">
                <span className="text-green-500">{diskHealthBreakdown.normal} normal</span>
                {diskHealthBreakdown.warning > 0 && (
                  <>
                    {", "}
                    <span className="text-yellow-500">{diskHealthBreakdown.warning} warning</span>
                  </>
                )}
                {diskHealthBreakdown.critical > 0 && (
                  <>
                    {", "}
                    <span className="text-red-500">{diskHealthBreakdown.critical} critical</span>
                  </>
                )}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {proxmoxStorage && proxmoxStorage.storage && proxmoxStorage.storage.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Proxmox Storage
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {proxmoxStorage.storage
                .filter((storage) => storage && storage.name && storage.used >= 0 && storage.available >= 0)
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((storage) => {
                  // Check if storage is excluded from monitoring
                  const isExcluded = storage.excluded === true
                  const hasError = storage.status === "error" && !isExcluded
                  
                  return (
                  <div
                    key={storage.name}
                    className={`border rounded-lg p-4 ${
                      hasError 
                        ? "border-red-500/50 bg-red-500/5" 
                        : isExcluded 
                          ? "border-purple-500/30 bg-purple-500/5 opacity-75" 
                          : ""
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      {/* Desktop: Icon + Name + Badge tipo alineados horizontalmente */}
                      <div className="hidden md:flex items-center gap-3">
                        <Database className="h-5 w-5 text-muted-foreground" />
                        <h3 className="font-semibold text-lg">{storage.name}</h3>
                        <Badge className={getStorageTypeBadge(storage.type)}>{storage.type}</Badge>
                        {/* Sprint 13: hint that this PVE storage also
                            shows up below in Remote Mounts where the
                            user can inspect mount options + health.
                            Uses the default Badge size to match the
                            adjacent type / status badges — earlier
                            versions used text-[10px] which looked
                            shrunken next to them. */}
                        {/^(nfs|cifs|smb)/i.test(storage.type) && (
                          <Badge className="bg-cyan-500/10 text-cyan-400 border-cyan-500/20">
                            remote mount
                          </Badge>
                        )}
                        {isExcluded && (
                          <Badge className="bg-purple-500/10 text-purple-400 border-purple-500/20">
                            excluded
                          </Badge>
                        )}
                      </div>

                      <div className="flex md:hidden items-center gap-2 flex-1">
                        <Database className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                        <Badge className={getStorageTypeBadge(storage.type)}>{storage.type}</Badge>
                        {/^(nfs|cifs|smb)/i.test(storage.type) && (
                          <Badge className="bg-cyan-500/10 text-cyan-400 border-cyan-500/20">
                            remote
                          </Badge>
                        )}
                        <h3 className="font-semibold text-base flex-1 min-w-0 truncate">{storage.name}</h3>
                        {isExcluded ? (
                          <Badge className="bg-purple-500/10 text-purple-400 border-purple-500/20 text-[10px]">
                            excluded
                          </Badge>
                        ) : (
                          getStatusIcon(storage.status)
                        )}
                      </div>

                      {/* Desktop: Badge active + Porcentaje */}
                      <div className="hidden md:flex items-center gap-2">
                        <Badge
                          className={
                            isExcluded
                              ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                              : storage.status === "active"
                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                : storage.status === "namespace_restricted"
                                  ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                                  : storage.status === "error"
                                    ? "bg-red-500/10 text-red-500 border-red-500/20"
                                    : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                          }
                          title={
                            storage.status === "namespace_restricted"
                              ? "Storage reachable; datastore size hidden by ACL (e.g. PBS DatastoreAdmin on a single namespace)"
                              : undefined
                          }
                        >
                          {isExcluded
                            ? "not monitored"
                            : storage.status === "namespace_restricted"
                              ? "namespace-restricted"
                              : storage.status}
                        </Badge>
                        <span className="text-sm font-medium">{storage.percent}%</span>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <Progress
                        value={storage.percent}
                        className={`h-2 ${
                          storage.percent > 90
                            ? "[&>div]:bg-red-500"
                            : storage.percent > 75
                              ? "[&>div]:bg-yellow-500"
                              : "[&>div]:bg-blue-500"
                        }`}
                      />
                      <div className="grid grid-cols-3 gap-4 text-sm">
                        <div>
                          <p className="text-muted-foreground">Total</p>
                          <p className="font-medium">{formatStorage(storage.total)}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Used</p>
                          <p
                            className={`font-medium ${
                              storage.percent > 90
                                ? "text-red-400"
                                : storage.percent > 75
                                  ? "text-yellow-400"
                                  : "text-blue-400"
                            }`}
                          >
                            {formatStorage(storage.used)}
                          </p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Available</p>
                          <p className="font-medium text-green-400">{formatStorage(storage.available)}</p>
                        </div>
                      </div>
                    </div>
                  </div>
                  )
                })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sprint 13 — Remote Mounts (NFS/CIFS/SMB) detected on the
          host. Renders only when at least one is present so a
          standalone host with no shares doesn't see an empty card.
          Stale mounts get a red bg + critical icon; read-only get
          amber; healthy get a green dot. */}
      {remoteMounts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Remote Mounts
              <Badge variant="outline" className="ml-2 text-[10px]">
                {remoteMounts.length}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {remoteMounts
                .slice()
                .sort((a, b) => a.target.localeCompare(b.target))
                .map((mount) => {
                  const isStale = mount.status === "stale"
                  const isReadonly = mount.status === "readonly"
                  const cardClasses = isStale
                    ? "border-red-500/50 bg-red-500/5 sm:hover:bg-red-500/10"
                    : isReadonly
                      ? "border-amber-500/40 bg-amber-500/5 sm:hover:bg-amber-500/10"
                      : "border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5"
                  return (
                    <div
                      key={mount.target}
                      onClick={() => setMountDetail(mount)}
                      className={`cursor-pointer border rounded-lg p-3 transition-colors ${cardClasses}`}
                    >
                      <div className="flex items-center justify-between gap-3 flex-wrap">
                        <div className="flex items-center gap-2 min-w-0">
                          <div
                            className={`w-2 h-2 rounded-full flex-shrink-0 ${
                              isStale ? "bg-red-500" : isReadonly ? "bg-amber-500" : "bg-green-500"
                            }`}
                          />
                          <h3 className="font-mono text-sm truncate">{mount.target}</h3>
                          <Badge className={getStorageTypeBadge(mount.fstype)}>{mount.fstype}</Badge>
                          {/* Sprint 13.18: makes it explicit that the
                              row corresponds to an entry already in the
                              Proxmox Storage card above. Default size
                              keeps it visually consistent with the
                              adjacent type badge. */}
                          {mount.proxmox_managed && (
                            <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">
                              managed by Proxmox
                            </Badge>
                          )}
                          {mount.readonly && (
                            <Badge className="bg-amber-500/10 text-amber-500 border-amber-500/20">
                              ro
                            </Badge>
                          )}
                        </div>
                        <Badge
                          className={
                            isStale
                              ? "bg-red-500/10 text-red-500 border-red-500/20"
                              : isReadonly
                                ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                                : "bg-green-500/10 text-green-500 border-green-500/20"
                          }
                        >
                          {isStale ? "stale" : isReadonly ? "read-only" : "reachable"}
                        </Badge>
                      </div>
                      <div className="text-xs text-muted-foreground mt-2 truncate">
                        <span className="font-medium text-foreground">Source:</span>{" "}
                        <span className="font-mono">{mount.source || "—"}</span>
                      </div>
                      {isStale && mount.error && (
                        <p className="text-xs text-red-400 mt-2">{mount.error}</p>
                      )}
                    </div>
                  )
                })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sprint 13.29: the "Remote Mounts (LXC)" card that previously
          lived here was removed because the information was redundant
          with the host card (the same NAS shows up twice) and a
          Storage page is the wrong scope for per-CT details anyway.
          LXC mount-points are now surfaced inside the LXC modal
          (VMs & LXCs tab) where they belong contextually. The
          backend helper `mount_monitor.scan_lxc_mounts()` is kept so
          the health monitor can still alert on stale mounts inside
          containers in the background. */}

      {/* Sprint 13.19: remote mount detail modal.
          Uses shadcn Dialog for the same typography (DialogTitle =
          text-lg, DialogDescription = text-sm muted) and behaviour as
          the disk details modal — earlier version was a hand-rolled
          overlay with text-xs/text-[10px] all over and looked
          shrunken next to the rest of the modals. */}
      <Dialog open={!!mountDetail} onOpenChange={(open) => { if (!open) setMountDetail(null) }}>
        <DialogContent className="max-w-2xl max-h-[80vh] sm:max-h-[85vh] overflow-hidden flex flex-col p-0">
          {mountDetail && (() => {
            const m = mountDetail
            const isStale = m.status === "stale"
            const isReadonly = m.status === "readonly"
            const optionEntries = (m.options || "")
              .split(",")
              .filter(Boolean)
              .map((opt) => {
                const eq = opt.indexOf("=")
                if (eq === -1) return { key: opt, value: null as string | null }
                return { key: opt.slice(0, eq), value: opt.slice(eq + 1) }
              })
            const flags = optionEntries.filter((o) => o.value === null).map((o) => o.key)
            const keyValues = optionEntries.filter((o) => o.value !== null) as Array<{ key: string; value: string }>
            const fmtBytes = (b: number | null | undefined) => {
              if (b == null) return "—"
              const gb = b / 1024 ** 3
              return formatStorage(gb)
            }
            const usedPct =
              m.total_bytes && m.used_bytes != null && m.total_bytes > 0
                ? Math.round((m.used_bytes / m.total_bytes) * 100)
                : null
            return (
              <>
                <DialogHeader className="px-6 pt-6 pb-2">
                  <DialogTitle className="flex items-center gap-2 flex-wrap">
                    <Database className="h-5 w-5 text-cyan-500" />
                    <span className="font-mono">{m.target}</span>
                    <Badge
                      className={
                        isStale
                          ? "bg-red-500/10 text-red-500 border-red-500/20"
                          : isReadonly
                            ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                            : "bg-green-500/10 text-green-500 border-green-500/20"
                      }
                    >
                      {isStale ? "stale" : isReadonly ? "read-only" : "reachable"}
                    </Badge>
                  </DialogTitle>
                  <DialogDescription>
                    <span className="font-mono">{m.source || "—"}</span>
                  </DialogDescription>
                </DialogHeader>

                <div className="px-6 pb-6 overflow-auto space-y-5">
                  {/* Type + tags */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className={getStorageTypeBadge(m.fstype)}>{m.fstype}</Badge>
                    {m.proxmox_managed && (
                      <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">
                        managed by Proxmox
                      </Badge>
                    )}
                    {m.lxc_id && (
                      <Badge className="bg-purple-500/10 text-purple-400 border-purple-500/20">
                        CT {m.lxc_id}{m.lxc_name ? `: ${m.lxc_name}` : ""}
                      </Badge>
                    )}
                    {flags.map((f) => (
                      <Badge key={f} variant="outline" className="font-mono">
                        {f}
                      </Badge>
                    ))}
                  </div>

                  {/* Capacity. df can hang on stale NFS so the backend
                      skips it and we render n/a here. Headers use the
                      same `<h4 className="font-semibold">` shape as
                      the disk-details modal in this same file (no
                      explicit text-sm override) so the typography
                      lines up — the body inherits text-base from the
                      Dialog content, not text-sm. */}
                  <div>
                    <h4 className="font-semibold mb-3">Capacity</h4>
                    {m.reachable && m.total_bytes ? (
                      <div className="space-y-2">
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
                        <div className="grid grid-cols-3 gap-4">
                          <div>
                            <p className="text-sm text-muted-foreground">Total</p>
                            <p className="font-medium">{fmtBytes(m.total_bytes)}</p>
                          </div>
                          <div>
                            <p className="text-sm text-muted-foreground">Used</p>
                            <p className="font-medium">
                              {fmtBytes(m.used_bytes)} {usedPct != null && `(${usedPct}%)`}
                            </p>
                          </div>
                          <div>
                            <p className="text-sm text-muted-foreground">Available</p>
                            <p className="font-medium">{fmtBytes(m.available_bytes)}</p>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <p className="text-muted-foreground">
                        {isStale ? "df skipped: mount is stale." : "n/a"}
                      </p>
                    )}
                  </div>

                  {/* Mount options grid — readable parse of the
                      key=value list from /proc/mounts so the user
                      doesn't have to scan a 200-char string. */}
                  {keyValues.length > 0 && (
                    <div>
                      <h4 className="font-semibold mb-3">Mount options</h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
                        {keyValues.map((kv) => (
                          <div key={kv.key} className="flex items-baseline gap-2 min-w-0">
                            <span className="font-mono text-muted-foreground truncate">{kv.key}</span>
                            <span className="font-mono text-foreground truncate">= {kv.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Error — only renders when something is wrong. */}
                  {m.error && (
                    <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                      <h4 className="font-semibold text-red-400 mb-2">Error</h4>
                      <p className="text-red-300 font-mono whitespace-pre-wrap break-all">
                        {m.error}
                      </p>
                    </div>
                  )}
                </div>
              </>
            )
          })()}
        </DialogContent>
      </Dialog>

      {/* ZFS Pools */}
      {storageData.zfs_pools && storageData.zfs_pools.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              ZFS Pools
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {storageData.zfs_pools.map((pool) => (
                <div key={pool.name} className="border rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <h3 className="font-semibold text-lg">{pool.name}</h3>
                      {getHealthBadge(pool.health)}
                    </div>
                    {getHealthIcon(pool.health)}
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div>
                      <p className="text-sm text-muted-foreground">Size</p>
                      <p className="font-medium">{pool.size}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Allocated</p>
                      <p className="font-medium">{pool.allocated}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Free</p>
                      <p className="font-medium">{pool.free}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Physical Disks (internal only) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="h-5 w-5" />
            Physical Disks & SMART Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {storageData.disks.filter(d => d.connection_type !== 'usb').map((disk) => (
              <div key={disk.name}>
                <div
                  className="sm:hidden border border-white/10 rounded-lg p-4 cursor-pointer bg-white/5 transition-colors"
                  onClick={() => handleDiskClick(disk)}
                >
                  <div className="space-y-2 mb-3">
                    {/* Row 1: Device name and type badge */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <HardDrive className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                      <h3 className="font-semibold">/dev/{disk.name}</h3>
                      <Badge className={getDiskTypeBadge(disk.name, disk.rotation_rate).className}>
                        {getDiskTypeBadge(disk.name, disk.rotation_rate).label}
                      </Badge>
                      {disk.is_system_disk && (
                        <Badge className="bg-orange-500/10 text-orange-500 border-orange-500/20 gap-1">
                          <Server className="h-3 w-3" />
                          System
                        </Badge>
                      )}
                    </div>

                    {/* Row 2: Model, temperature, and health status */}
                    <div className="flex items-center justify-between gap-3 pl-7">
                      {disk.model && disk.model !== "Unknown" && (
                        <p className="text-sm text-muted-foreground truncate flex-1 min-w-0">{disk.model}</p>
                      )}
                      <div className="flex items-center gap-3 flex-shrink-0">
                        {disk.temperature > 0 && (
                          <div className="flex items-center gap-1">
                            <Thermometer
                              className={`h-4 w-4 ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`}
                            />
                            <span
                              className={`text-sm font-medium ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`}
                            >
                              {disk.temperature}°C
                            </span>
                          </div>
                        )}
                        {(disk.observations_count ?? 0) > 0 && (
                          <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 gap-1">
                            <Info className="h-3 w-3" />
                            {disk.observations_count} obs.
                          </Badge>
                        )}
                        {getHealthBadge(disk.health)}
                      </div>
                    </div>
                  </div>

                    {disk.io_errors && disk.io_errors.count > 0 && (
                    <div className={`flex items-start gap-2 p-2 rounded text-xs ${
                      disk.io_errors.severity === 'CRITICAL'
                        ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                        : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                    }`}>
                      <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                      <span>
                        {disk.io_errors.error_type === 'filesystem'
                          ? `Filesystem corruption detected`
                          : `${disk.io_errors.count} I/O error${disk.io_errors.count !== 1 ? 's' : ''} in 5 min`}
                      </span>
                    </div>
                    )}
                    
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      {disk.size_formatted && (
                      <div>
                        <p className="text-sm text-muted-foreground">Size</p>
                        <p className="font-medium">{disk.size_formatted}</p>
                      </div>
                    )}
                    {disk.smart_status && disk.smart_status !== "unknown" && (
                      <div>
                        <p className="text-sm text-muted-foreground">SMART Status</p>
                        <p className="font-medium capitalize">{disk.smart_status}</p>
                      </div>
                    )}
                    {disk.power_on_hours !== undefined && disk.power_on_hours > 0 && (
                      <div>
                        <p className="text-sm text-muted-foreground">Power On Time</p>
                        <p className="font-medium">{formatHours(disk.power_on_hours)}</p>
                      </div>
                    )}
                    {disk.serial && disk.serial !== "Unknown" && (
                      <div>
                        <p className="text-sm text-muted-foreground">Serial</p>
                        <p className="font-medium text-xs">{disk.serial}</p>
                      </div>
                    )}
                  </div>
                </div>

                <div
                  className="hidden sm:block border border-white/10 rounded-lg p-4 cursor-pointer bg-card hover:bg-white/5 transition-colors"
                  onClick={() => handleDiskClick(disk)}
                >
                  <div className="space-y-2 mb-3">
                    {/* Row 1: Device name and type badge */}
                    <div className="flex items-center gap-2">
                      <HardDrive className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                      <h3 className="font-semibold">/dev/{disk.name}</h3>
                      <Badge className={getDiskTypeBadge(disk.name, disk.rotation_rate).className}>
                        {getDiskTypeBadge(disk.name, disk.rotation_rate).label}
                      </Badge>
                      {disk.is_system_disk && (
                        <Badge className="bg-orange-500/10 text-orange-500 border-orange-500/20 gap-1">
                          <Server className="h-3 w-3" />
                          System
                        </Badge>
                      )}
                    </div>

                    {/* Row 2: Model, temperature, and health status */}
                    <div className="flex items-center justify-between gap-3 pl-7">
                      {disk.model && disk.model !== "Unknown" && (
                        <p className="text-sm text-muted-foreground truncate flex-1 min-w-0">{disk.model}</p>
                      )}
                      <div className="flex items-center gap-3 flex-shrink-0">
                        {disk.temperature > 0 && (
                          <div className="flex items-center gap-1">
                            <Thermometer
                              className={`h-4 w-4 ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`}
                            />
                            <span
                              className={`text-sm font-medium ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`}
                            >
                              {disk.temperature}°C
                            </span>
                          </div>
                        )}
                        {(disk.observations_count ?? 0) > 0 && (
                          <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 gap-1">
                            <Info className="h-3 w-3" />
                            {disk.observations_count} obs.
                          </Badge>
                        )}
                        {getHealthBadge(disk.health)}
                      </div>
                    </div>
                  </div>

                  {disk.io_errors && disk.io_errors.count > 0 && (
                    <div className={`flex items-start gap-2 p-2 rounded text-xs ${
                      disk.io_errors.severity === 'CRITICAL'
                        ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                        : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                    }`}>
                      <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                      <div>
                        {disk.io_errors.error_type === 'filesystem' ? (
                          <>
                            <span className="font-medium">Filesystem corruption detected</span>
                            {disk.io_errors.reason && (
                              <p className="mt-0.5 opacity-90 whitespace-pre-line">{disk.io_errors.reason}</p>
                            )}
                          </>
                        ) : (
                          <>
                            <span className="font-medium">{disk.io_errors.count} I/O error{disk.io_errors.count !== 1 ? 's' : ''} in 5 min</span>
                            {disk.io_errors.sample && (
                              <p className="mt-0.5 opacity-80 font-mono truncate max-w-md">{disk.io_errors.sample}</p>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    {disk.size_formatted && (
                      <div>
                        <p className="text-sm text-muted-foreground">Size</p>
                        <p className="font-medium">{disk.size_formatted}</p>
                      </div>
                    )}
                    {disk.smart_status && disk.smart_status !== "unknown" && (
                      <div>
                        <p className="text-sm text-muted-foreground">SMART Status</p>
                        <p className="font-medium capitalize">{disk.smart_status}</p>
                      </div>
                    )}
                    {disk.power_on_hours !== undefined && disk.power_on_hours > 0 && (
                      <div>
                        <p className="text-sm text-muted-foreground">Power On Time</p>
                        <p className="font-medium">{formatHours(disk.power_on_hours)}</p>
                      </div>
                    )}
                    {disk.serial && disk.serial !== "Unknown" && (
                      <div>
                        <p className="text-sm text-muted-foreground">Serial</p>
                        <p className="font-medium text-xs">{disk.serial.replace(/\\x[0-9a-fA-F]{2}/g, '')}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* External Storage (USB) */}
      {storageData.disks.filter(d => d.connection_type === 'usb').length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Usb className="h-5 w-5" />
              External Storage (USB)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {storageData.disks.filter(d => d.connection_type === 'usb').map((disk) => (
                <div key={disk.name}>
                  {/* Mobile card */}
                  <div
                    className="sm:hidden border border-white/10 rounded-lg p-4 cursor-pointer bg-white/5 transition-colors"
                    onClick={() => handleDiskClick(disk)}
                  >
                    <div className="space-y-2 mb-3">
                      <div className="flex items-center gap-2">
                        <Usb className="h-5 w-5 text-orange-400 flex-shrink-0" />
                        <h3 className="font-semibold">/dev/{disk.name}</h3>
                        <Badge className="bg-orange-500/10 text-orange-400 border-orange-500/20 text-[10px] px-1.5">USB</Badge>
                      </div>
                      <div className="flex items-center justify-between gap-3 pl-7">
                        {disk.model && disk.model !== "Unknown" && (
                          <p className="text-sm text-muted-foreground truncate flex-1 min-w-0">{disk.model}</p>
                        )}
                        <div className="flex items-center gap-3 flex-shrink-0">
                          {disk.temperature > 0 && (
                            <div className="flex items-center gap-1">
                              <Thermometer className={`h-4 w-4 ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`} />
                              <span className={`text-sm font-medium ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`}>
                                {disk.temperature}°C
                              </span>
                            </div>
                          )}
                          {(disk.observations_count ?? 0) > 0 && (
                            <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 gap-1 text-[10px] px-1.5 py-0">
                              <Info className="h-3 w-3" />
                              {disk.observations_count}
                            </Badge>
                          )}
                          {getHealthBadge(disk.health)}
                        </div>
                      </div>
                    </div>
                    
                    {/* USB Mobile: Size, SMART, Serial grid */}
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      {disk.size_formatted && (
                        <div>
                          <p className="text-sm text-muted-foreground">Size</p>
                          <p className="font-medium">{disk.size_formatted}</p>
                        </div>
                      )}
                      {disk.smart_status && disk.smart_status !== "unknown" && (
                        <div>
                          <p className="text-sm text-muted-foreground">SMART Status</p>
                          <p className="font-medium capitalize">{disk.smart_status}</p>
                        </div>
                      )}
{disk.serial && disk.serial !== "Unknown" && (
                      <div>
                        <p className="text-sm text-muted-foreground">Serial</p>
                        <p className="font-medium text-xs">{disk.serial.replace(/\\x[0-9a-fA-F]{2}/g, '')}</p>
                      </div>
                    )}
                    </div>
                </div>

                {/* Desktop */}
                <div
                  className="hidden sm:block border border-white/10 rounded-lg p-4 cursor-pointer hover:bg-white/5 transition-colors"
                  onClick={() => handleDiskClick(disk)}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Usb className="h-5 w-5 text-orange-400" />
                        <h3 className="font-semibold">/dev/{disk.name}</h3>
                        <Badge className="bg-orange-500/10 text-orange-400 border-orange-500/20 text-[10px] px-1.5">USB</Badge>
                      </div>
                      <div className="flex items-center gap-3">
                        {disk.temperature > 0 && (
                          <div className="flex items-center gap-1">
                            <Thermometer className={`h-4 w-4 ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`} />
                            <span className={`text-sm font-medium ${getTempColor(disk.temperature, disk.name, disk.rotation_rate)}`}>
                              {disk.temperature}°C
                            </span>
                          </div>
                        )}
                        {getHealthBadge(disk.health)}
                        {(disk.observations_count ?? 0) > 0 && (
                          <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 gap-1">
                            <Info className="h-3 w-3" />
                            {disk.observations_count} obs.
                          </Badge>
                        )}
                      </div>
                    </div>
                    {disk.model && disk.model !== "Unknown" && (
                      <p className="text-sm text-muted-foreground mb-3 ml-7">{disk.model}</p>
                    )}

                    {disk.io_errors && disk.io_errors.count > 0 && (
                      <div className={`flex items-start gap-2 p-2 rounded text-xs mb-3 ${
                        disk.io_errors.severity === 'CRITICAL'
                          ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                          : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                      }`}>
                        <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                        <div>
                          {disk.io_errors.error_type === 'filesystem' ? (
                            <>
                              <span className="font-medium">Filesystem corruption detected</span>
                              {disk.io_errors.reason && (
                                <p className="mt-0.5 opacity-90 whitespace-pre-line">{disk.io_errors.reason}</p>
                              )}
                            </>
                          ) : (
                            <>
                              <span className="font-medium">{disk.io_errors.count} I/O error{disk.io_errors.count !== 1 ? 's' : ''} in 5 min</span>
                              {disk.io_errors.sample && (
                                <p className="mt-0.5 opacity-80 font-mono truncate max-w-md">{disk.io_errors.sample}</p>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    )}

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      {disk.size_formatted && (
                        <div>
                          <p className="text-sm text-muted-foreground">Size</p>
                          <p className="font-medium">{disk.size_formatted}</p>
                        </div>
                      )}
                      {disk.smart_status && disk.smart_status !== "unknown" && (
                        <div>
                          <p className="text-sm text-muted-foreground">SMART Status</p>
                          <p className="font-medium capitalize">{disk.smart_status}</p>
                        </div>
                      )}
                      {disk.power_on_hours !== undefined && disk.power_on_hours > 0 && (
                        <div>
                          <p className="text-sm text-muted-foreground">Power On Time</p>
                          <p className="font-medium">{formatHours(disk.power_on_hours)}</p>
                        </div>
                      )}
                      {disk.serial && disk.serial !== "Unknown" && (
                        <div>
                          <p className="text-sm text-muted-foreground">Serial</p>
                          <p className="font-medium text-xs">{disk.serial.replace(/\\x[0-9a-fA-F]{2}/g, '')}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Disk Details Dialog */}
      <Dialog open={detailsOpen} onOpenChange={(open) => {
        setDetailsOpen(open)
        if (!open) {
          setActiveModalTab("overview")
          setSmartJsonData(null)
        }
      }}>
        <DialogContent className="max-w-2xl max-h-[80vh] sm:max-h-[85vh] overflow-hidden flex flex-col p-0">
          <DialogHeader className="px-6 pt-6 pb-0">
            <DialogTitle className="flex items-center gap-2">
              {selectedDisk?.connection_type === 'usb' ? (
                <Usb className="h-5 w-5 text-orange-400" />
              ) : (
                <HardDrive className="h-5 w-5" />
              )}
              Disk Details: /dev/{selectedDisk?.name}
              {selectedDisk?.connection_type === 'usb' && (
                <Badge className="bg-orange-500/10 text-orange-400 border-orange-500/20 text-[10px] px-1.5">USB</Badge>
              )}
              {selectedDisk?.is_system_disk && (
                <Badge className="bg-orange-500/10 text-orange-500 border-orange-500/20 gap-1">
                  <Server className="h-3 w-3" />
                  System
                </Badge>
              )}
            </DialogTitle>
            <DialogDescription>
              {selectedDisk?.model !== "Unknown" ? selectedDisk?.model : "Physical disk"} - {selectedDisk?.size_formatted}
            </DialogDescription>
          </DialogHeader>
          
          {/* Tab Navigation */}
          <div className="flex border-b border-border px-6 overflow-x-auto">
            <button
              onClick={() => setActiveModalTab("overview")}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                activeModalTab === "overview"
                  ? "border-blue-500 text-blue-500"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Info className="h-4 w-4" />
              Overview
            </button>
            <button
              onClick={() => setActiveModalTab("smart")}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                activeModalTab === "smart"
                  ? "border-green-500 text-green-500"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Activity className="h-4 w-4" />
              SMART
            </button>
            <button
              onClick={() => setActiveModalTab("history")}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                activeModalTab === "history"
                  ? "border-orange-500 text-orange-500"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Archive className="h-4 w-4" />
              History
            </button>
            <button
              onClick={() => setActiveModalTab("schedule")}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${
                activeModalTab === "schedule"
                  ? "border-purple-500 text-purple-500"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Clock className="h-4 w-4" />
              Schedule
            </button>
          </div>
          
          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto px-6 py-4 min-h-0">
          {selectedDisk && activeModalTab === "overview" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Model</p>
                  <p className="font-medium">{selectedDisk.model}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Serial Number</p>
                  <p className="font-medium">{selectedDisk.serial?.replace(/\\x[0-9a-fA-F]{2}/g, '') || 'Unknown'}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Capacity</p>
                  <p className="font-medium">{selectedDisk.size_formatted}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Health Status</p>
                  <div className="flex items-center gap-2 mt-1">
                    {getHealthBadge(selectedDisk.health)}
                    {(selectedDisk.observations_count ?? 0) > 0 && (
<Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 gap-1">
                      <Info className="h-3 w-3" />
                      {selectedDisk.observations_count} obs.
                    </Badge>
                    )}
                  </div>
                </div>
              </div>

              {/* Wear & Lifetime — DiskInfo (real-time, 60s refresh) for NVMe + SSD. SMART JSON as fallback. HDD: hidden. */}
              {(() => {
                let wearUsed: number | null = null
                let lifeRemaining: number | null = null
                let estimatedLife = ''
                let dataWritten = ''
                let spare: number | undefined

                // --- Step 1: DiskInfo = primary source (refreshed every 60s, always fresh) ---
                // Works for NVMe (percentage_used) and SSD (media_wearout_indicator, ssd_life_left)
                const wi = getWearIndicator(selectedDisk)
                if (wi) {
                  wearUsed = wi.value
                  lifeRemaining = 100 - wearUsed
                  estimatedLife = getEstimatedLifeRemaining(selectedDisk) || ''
                  if (selectedDisk.total_lbas_written && selectedDisk.total_lbas_written > 0) {
                    const tb = selectedDisk.total_lbas_written / 1024
                    dataWritten = tb >= 1 ? `${tb.toFixed(2)} TB` : `${selectedDisk.total_lbas_written.toFixed(2)} GB`
                  }
                }

                // --- Step 2: SMART test JSON — primary for SSD, supplement for NVMe ---
                if (smartJsonData?.has_data && smartJsonData.data) {
                  const data = smartJsonData.data as Record<string, unknown>
                  const nvmeHealth = (data?.nvme_smart_health_information_log || data) as Record<string, unknown>

                  // Available spare (only from SMART/NVMe data)
                  if (spare === undefined) {
                    spare = (nvmeHealth?.avail_spare ?? nvmeHealth?.available_spare) as number | undefined
                  }

                  // Data written — use SMART JSON if DiskInfo didn't provide it
                  if (!dataWritten) {
                    const ataAttrs = data?.ata_smart_attributes as { table?: Array<{ id: number; name: string; value: number; raw?: { value: number } }> }
                    const table = ataAttrs?.table || []
                    const lbasAttr = table.find(a =>
                      a.name?.toLowerCase().includes('total_lbas_written') ||
                      a.name?.toLowerCase().includes('writes_gib') ||
                      a.name?.toLowerCase().includes('lifetime_writes') ||
                      a.id === 241
                    )
                    if (lbasAttr && lbasAttr.raw?.value) {
                      const n = (lbasAttr.name || '').toLowerCase()
                      const tb = (n.includes('gib') || n.includes('_gb') || n.includes('writes_gib'))
                        ? lbasAttr.raw.value / 1024
                        : (lbasAttr.raw.value * 512) / (1024 ** 4)
                      dataWritten = tb >= 1 ? `${tb.toFixed(2)} TB` : `${(tb * 1024).toFixed(2)} GB`
                    } else if (nvmeHealth?.data_units_written) {
                      const tb = ((nvmeHealth.data_units_written as number) * 512000) / (1024 ** 4)
                      dataWritten = tb >= 1 ? `${tb.toFixed(2)} TB` : `${(tb * 1024).toFixed(2)} GB`
                    }
                  }

                  // Wear/life — use SMART JSON only if DiskInfo didn't provide it (SSD without backend support)
                  if (lifeRemaining === null) {
                    const ataAttrs = data?.ata_smart_attributes as { table?: Array<{ id: number; name: string; value: number; raw?: { value: number } }> }
                    const table = ataAttrs?.table || []
                    const wearAttr = table.find(a =>
                      a.name?.toLowerCase().includes('wear_leveling') ||
                      a.name?.toLowerCase().includes('media_wearout') ||
                      a.name?.toLowerCase().includes('ssd_life_left') ||
                      a.id === 177 || a.id === 231
                    )
                    const nvmeIsPresent = nvmeHealth?.percent_used !== undefined || nvmeHealth?.percentage_used !== undefined

                    if (wearAttr) {
                      lifeRemaining = (wearAttr.id === 230) ? (100 - wearAttr.value) : wearAttr.value
                    } else if (nvmeIsPresent) {
                      lifeRemaining = 100 - ((nvmeHealth.percent_used ?? nvmeHealth.percentage_used ?? 0) as number)
                    }

                    if (lifeRemaining !== null) {
                      wearUsed = 100 - lifeRemaining
                      const poh = selectedDisk.power_on_hours || 0
                      if (lifeRemaining > 0 && lifeRemaining < 100 && poh > 0) {
                        const used = 100 - lifeRemaining
                        if (used > 0) {
                          const ry = ((poh / (used / 100)) - poh) / (24 * 365)
                          estimatedLife = ry >= 1 ? `~${ry.toFixed(1)} years` : `~${(ry * 12).toFixed(0)} months`
                        }
                      }
                    }
                  }
                }

                // --- Only render if we have meaningful wear data ---
                if (wearUsed === null && lifeRemaining === null) return null

                // Sprint 14 honest-data fix: a `percent_used == 0` from
                // firmwares like the WD CL SN720 isn't real wear data —
                // the drive simply hasn't started ticking. We don't want
                // to assert "100% life remaining" in that case. Show
                // only Data Written, since that's the one number we
                // know we can trust for these drives.
                const hasReportedWear = (wearUsed !== null && wearUsed > 0)

                if (!hasReportedWear) {
                  if (!dataWritten) return null
                  return (
                    <div className="border-t pt-4">
                      <h4 className="font-semibold mb-3 flex items-center gap-2">
                        Wear & Lifetime
                      </h4>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <p className="text-xs text-muted-foreground">Data Written</p>
                          <p className="text-sm font-medium">{dataWritten}</p>
                        </div>
                      </div>
                    </div>
                  )
                }

                const lifeColor = lifeRemaining !== null
                  ? (lifeRemaining >= 50 ? '#22c55e' : lifeRemaining >= 20 ? '#eab308' : '#ef4444')
                  : '#6b7280'

                return (
                  <div className="border-t pt-4">
                    <h4 className="font-semibold mb-3 flex items-center gap-2">
                      Wear & Lifetime
                      {smartJsonData?.has_data && !wi && (
                        <Badge className="bg-green-500/10 text-green-400 border-green-500/20 text-[10px] px-1.5">Real Test</Badge>
                      )}
                    </h4>
                    <div className="flex gap-5 items-start">
                      {lifeRemaining !== null && (
                        <div className="flex flex-col items-center gap-1 flex-shrink-0">
                          <svg width="88" height="88" viewBox="0 0 88 88">
                            <circle cx="44" cy="44" r="35" fill="none" stroke={lifeColor} strokeWidth="6"
                              strokeDasharray={`${lifeRemaining * 2.199} 219.9`}
                              strokeLinecap="round" transform="rotate(-90 44 44)" />
                            <text x="44" y="40" textAnchor="middle" fill={lifeColor} fontSize="20" fontWeight="700">{lifeRemaining}%</text>
                            <text x="44" y="56" textAnchor="middle" fill="currentColor" fontSize="12" className="text-muted-foreground">life</text>
                          </svg>
                        </div>
                      )}
                      <div className="flex-1 space-y-3 min-w-0">
                        {/*
                          Hide the "Wear" bar and "Est. Life" entirely when the
                          drive firmware reports zero wear (some NVMe families
                          like the WD SN720 don't tick percentage_used until
                          significant wear is reached). The 100% life ring + the
                          Avail. Spare and Data Written numbers are enough to
                          convey "drive is healthy without any reportable wear
                          data" — repeating "0%" three times is just visual noise.
                        */}
                        {wearUsed !== null && wearUsed > 0 && (
                          <div>
                            <div className="flex items-center justify-between mb-1.5">
                              <p className="text-xs text-muted-foreground">Wear</p>
                              <p className="text-sm font-medium text-blue-400">{wearUsed}%</p>
                            </div>
                            <Progress value={wearUsed} className="h-2 [&>div]:bg-blue-500" />
                          </div>
                        )}
                        <div className="grid grid-cols-2 gap-3">
                          {estimatedLife && wearUsed !== null && wearUsed > 0 && (
                            <div>
                              <p className="text-xs text-muted-foreground">Est. Life</p>
                              <p className="text-sm font-medium">{estimatedLife}</p>
                            </div>
                          )}
                          {dataWritten && (
                            <div>
                              <p className="text-xs text-muted-foreground">Data Written</p>
                              <p className="text-sm font-medium">{dataWritten}</p>
                            </div>
                          )}
                          {spare !== undefined && (
                            <div>
                              <p className="text-xs text-muted-foreground">Avail. Spare</p>
                              <p className={`text-sm font-medium ${spare < 20 ? 'text-red-400' : 'text-blue-400'}`}>{spare}%</p>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })()}

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">SMART Attributes</h4>
                {/*
                  Sprint 14: temperature lives in its own full-width card
                  with an inline 1-hour mini chart. The remaining attributes
                  flow below in the same 2-col grid as before.
                */}
                {selectedDisk.connection_type !== 'usb' && (
                  <div className="mb-4">
                    <DiskTemperatureCard
                      diskName={selectedDisk.name}
                      liveTemperature={selectedDisk.temperature}
                      diskType={getDiskTypeBadge(selectedDisk.name, selectedDisk.rotation_rate).label}
                      onOpenDetail={selectedDisk.temperature > 0 ? () => setTempHistoryDisk(selectedDisk) : undefined}
                    />
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Power On Hours</p>
                    <p className="font-medium">
                      {selectedDisk.power_on_hours && selectedDisk.power_on_hours > 0
                        ? `${selectedDisk.power_on_hours.toLocaleString()}h (${formatHours(selectedDisk.power_on_hours)})`
                        : "N/A"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Rotation Rate</p>
                    <p className="font-medium">{formatRotationRate(selectedDisk.rotation_rate)}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Power Cycles</p>
                    <p className="font-medium">
                      {selectedDisk.power_cycles && selectedDisk.power_cycles > 0
                        ? selectedDisk.power_cycles.toLocaleString()
                        : "N/A"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">SMART Status</p>
                    <p className="font-medium capitalize">{selectedDisk.smart_status}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Reallocated Sectors</p>
                    <p
                      className={`font-medium ${selectedDisk.reallocated_sectors && selectedDisk.reallocated_sectors > 0 ? "text-yellow-500" : ""}`}
                    >
                      {selectedDisk.reallocated_sectors ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Pending Sectors</p>
                    <p
                      className={`font-medium ${selectedDisk.pending_sectors && selectedDisk.pending_sectors > 0 ? "text-yellow-500" : ""}`}
                    >
                      {selectedDisk.pending_sectors ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">CRC Errors</p>
                    <p
                      className={`font-medium ${selectedDisk.crc_errors && selectedDisk.crc_errors > 0 ? "text-yellow-500" : ""}`}
                    >
                      {selectedDisk.crc_errors ?? 0}
                    </p>
                  </div>
                  {/* USB drives lose the chart card; show plain temperature here. */}
                  {selectedDisk.connection_type === 'usb' && (
                    <div>
                      <p className="text-sm text-muted-foreground">Temperature</p>
                      <p className={`font-medium ${getTempColor(selectedDisk.temperature, selectedDisk.name, selectedDisk.rotation_rate)}`}>
                        {selectedDisk.temperature > 0 ? `${selectedDisk.temperature}°C` : "N/A"}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {/* OLD SMART Test Data section removed — now unified in Wear & Lifetime above */}
              {false && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3 flex items-center gap-2">
                    <Activity className="h-4 w-4 text-green-400" />
                    {(() => {
                      // Check if this is SSD without Proxmox wear data - show as "Wear & Lifetime"
                      const isNvme = selectedDisk.name?.includes('nvme')
                      const hasProxmoxWear = getWearIndicator(selectedDisk) !== null
                      if (!isNvme && !hasProxmoxWear && smartJsonData?.has_data) {
                        return 'Wear & Lifetime'
                      }
                      return 'SMART Test Data'
                    })()}
                    {smartJsonData?.has_data && (
                      <Badge className="bg-green-500/10 text-green-400 border-green-500/20 text-[10px] px-1.5">
                        Real Test
                      </Badge>
                    )}
                  </h4>
                  {loadingSmartJson ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                      <div className="h-4 w-4 rounded-full border-2 border-transparent border-t-green-400 animate-spin" />
                      Loading SMART test data...
                    </div>
                  ) : smartJsonData?.has_data && smartJsonData.data ? (
                    <div className="space-y-3">
                      {/* SSD/NVMe Life Estimation from JSON - Uniform style */}
                      {(() => {
                        const data = smartJsonData.data as Record<string, unknown>
                        const ataAttrs = data?.ata_smart_attributes as { table?: Array<{ id: number; name: string; value: number; raw?: { value: number } }> }
                        const table = ataAttrs?.table || []
                        
                        // Look for wear-related attributes for SSD
                        const wearAttr = table.find(a => 
                          a.name?.toLowerCase().includes('wear_leveling') ||
                          a.name?.toLowerCase().includes('media_wearout') ||
                          a.name?.toLowerCase().includes('percent_lifetime') ||
                          a.name?.toLowerCase().includes('ssd_life_left') ||
                          a.id === 177 || a.id === 231 || a.id === 233
                        )
                        
                        // Look for total LBAs written
                        const lbasAttr = table.find(a => 
                          a.name?.toLowerCase().includes('total_lbas_written') ||
                          a.id === 241
                        )
                        
                        // Look for power on hours from SMART data
                        const pohAttr = table.find(a => 
                          a.name?.toLowerCase().includes('power_on_hours') ||
                          a.id === 9
                        )
                        
                        // For NVMe, check nvme_smart_health_information_log
                        const nvmeHealth = data?.nvme_smart_health_information_log as Record<string, unknown>
                        
                        // Calculate data written
                        let dataWrittenTB = 0
                        let dataWrittenLabel = ''
                        if (lbasAttr && lbasAttr.raw?.value) {
                          dataWrittenTB = (lbasAttr.raw.value * 512) / (1024 ** 4)
                          dataWrittenLabel = dataWrittenTB >= 1 
                            ? `${dataWrittenTB.toFixed(2)} TB`
                            : `${(dataWrittenTB * 1024).toFixed(2)} GB`
                        } else if (nvmeHealth?.data_units_written) {
                          const units = nvmeHealth.data_units_written as number
                          dataWrittenTB = (units * 512000) / (1024 ** 4)
                          dataWrittenLabel = dataWrittenTB >= 1 
                            ? `${dataWrittenTB.toFixed(2)} TB`
                            : `${(dataWrittenTB * 1024).toFixed(2)} GB`
                        }
                        
                        // Get wear percentage (life remaining %)
                        let wearPercent: number | null = null
                        let wearLabel = 'Life Remaining'
                        if (wearAttr) {
                          if (wearAttr.id === 230) {
                            // Media_Wearout_Indicator (WD/SanDisk): value = endurance used %
                            wearPercent = 100 - wearAttr.value
                          } else {
                            // Standard: value = normalized life remaining %
                            wearPercent = wearAttr.value
                          }
                          wearLabel = 'Life Remaining'
                        } else if (nvmeHealth?.percentage_used !== undefined) {
                          wearPercent = 100 - (nvmeHealth.percentage_used as number)
                          wearLabel = 'Life Remaining'
                        }
                        
                        // Calculate estimated life remaining
                        let estimatedLife = ''
                        const powerOnHours = pohAttr?.raw?.value || selectedDisk.power_on_hours || 0
                        if (wearPercent !== null && wearPercent > 0 && wearPercent < 100 && powerOnHours > 0) {
                          const usedPercent = 100 - wearPercent
                          if (usedPercent > 0) {
                            const totalEstimatedHours = powerOnHours / (usedPercent / 100)
                            const remainingHours = totalEstimatedHours - powerOnHours
                            const remainingYears = remainingHours / (24 * 365)
                            if (remainingYears >= 1) {
                              estimatedLife = `~${remainingYears.toFixed(1)} years`
                            } else {
                              const remainingMonths = remainingYears * 12
                              estimatedLife = `~${remainingMonths.toFixed(0)} months`
                            }
                          }
                        }
                        
                        // Available spare for NVMe
                        const availableSpare = nvmeHealth?.available_spare as number | undefined
                        
                        if (wearPercent !== null || dataWrittenLabel) {
                          return (
                            <>
                              {/* Wear Progress Bar - Blue style matching NVMe */}
                              {wearPercent !== null && (
                                <div>
                                  <div className="flex items-center justify-between mb-2">
                                    <p className="text-sm text-muted-foreground">{wearLabel}</p>
                                    <p className="font-medium text-blue-400">
                                      {wearPercent}%
                                    </p>
                                  </div>
                                  <Progress
                                    value={wearPercent}
                                    className={`h-2 ${wearPercent < 20 ? '[&>div]:bg-red-500' : '[&>div]:bg-blue-500'}`}
                                  />
                                </div>
                              )}
                              
                              {/* Stats Grid - Same layout as NVMe Wear & Lifetime */}
                              <div className="grid grid-cols-2 gap-4">
                                {estimatedLife && (
                                  <div>
                                    <p className="text-sm text-muted-foreground">Estimated Life Remaining</p>
                                    <p className="font-medium">{estimatedLife}</p>
                                  </div>
                                )}
                                {dataWrittenLabel && (
                                  <div>
                                    <p className="text-sm text-muted-foreground">Total Data Written</p>
                                    <p className="font-medium">{dataWrittenLabel}</p>
                                  </div>
                                )}
                                {availableSpare !== undefined && (
                                  <div>
                                    <p className="text-sm text-muted-foreground">Available Spare</p>
                                    <p className={`font-medium ${availableSpare < 20 ? 'text-red-400' : availableSpare < 50 ? 'text-yellow-400' : 'text-green-400'}`}>
                                      {availableSpare}%
                                    </p>
                                  </div>
                                )}
                              </div>
                            </>
                          )
                        }
                        return null
                      })()}
                      
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      <p>No SMART test data available for this disk.</p>
                      <p className="text-xs mt-1">Run a SMART test in the SMART Test tab to get detailed health information.</p>
                    </div>
                  )}
                </div>
              )}

              {/* Observations Section */}
              {(diskObservations.length > 0 || loadingObservations) && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-2 flex items-center gap-2">
                    <Info className="h-4 w-4 text-blue-400" />
                    Observations
                    <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20 text-[10px] px-1.5 py-0">
                      {diskObservations.length}
                    </Badge>
                  </h4>
                  <p className="text-xs text-muted-foreground mb-3">
                    The following observations have been recorded for this disk:
                  </p>
                  {loadingObservations ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                      <div className="h-4 w-4 rounded-full border-2 border-transparent border-t-blue-400 animate-spin" />
                      Loading observations...
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {diskObservations.map((obs) => (
                        <div
                          key={obs.id}
                          className="rounded-lg border p-3 text-sm bg-blue-500/5 border-blue-500/20"
                        >
                          {/* Header with type badge — always blue.
                              The earlier red/blue split-by-severity was
                              confusing here because the Observations
                              panel is a *history* view, not a live
                              alert; the severity already reaches the
                              user through the notification channels.
                              The card just records what happened. */}
                          <div className="flex items-center gap-2 flex-wrap mb-2">
                            <Badge className="text-[10px] px-1.5 py-0 bg-blue-500/10 text-blue-400 border-blue-500/20">
                              {obsTypeLabel(obs.error_type)}
                            </Badge>
                          </div>
                          
                          {/* Error message - responsive text wrap */}
                          <p className="text-xs whitespace-pre-wrap break-words opacity-90 font-mono leading-relaxed mb-1">
                            {obs.raw_message}
                          </p>
                          {translateAtaError(obs.raw_message) && (
                            <p className="text-xs italic opacity-75 mb-3 break-words">
                              ↳ {translateAtaError(obs.raw_message)}
                            </p>
                          )}
                          
                          {/* Dates - stacked on mobile, inline on desktop */}
                          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3 text-[10px] text-muted-foreground border-t border-white/5 pt-2">
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3 flex-shrink-0" />
                              <span className="break-words">First: {formatObsDate(obs.first_occurrence)}</span>
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3 flex-shrink-0" />
                              <span className="break-words">Last: {formatObsDate(obs.last_occurrence)}</span>
                            </span>
                          </div>
                          
                          {/* Occurrences count */}
                          <div className="text-[10px] text-muted-foreground mt-1">
                            Occurrences: <span className="font-medium text-foreground">{obs.occurrence_count}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          
          {/* SMART Test Tab */}
          {selectedDisk && activeModalTab === "smart" && (
            <SmartTestTab disk={selectedDisk} observations={diskObservations} lastTestDate={smartJsonData?.timestamp || undefined} />
          )}
          
          {/* History Tab */}
          {selectedDisk && activeModalTab === "history" && (
            <HistoryTab disk={selectedDisk} />
          )}

          {/* Schedule Tab */}
          {selectedDisk && activeModalTab === "schedule" && (
            <ScheduleTab disk={selectedDisk} />
          )}
          </div>
        </DialogContent>
      </Dialog>

      {tempHistoryDisk && (
        <DiskTemperatureDetailModal
          open={!!tempHistoryDisk}
          onOpenChange={(o) => { if (!o) setTempHistoryDisk(null) }}
          diskName={tempHistoryDisk.name}
          diskModel={tempHistoryDisk.model}
          liveTemperature={tempHistoryDisk.temperature}
          diskType={getDiskTypeBadge(tempHistoryDisk.name, tempHistoryDisk.rotation_rate).label}
        />
      )}
    </div>
  )
}

// Generate SMART Report HTML and open in new window (same pattern as Lynis/Latency reports)
interface DiskTempHistoryPoint { timestamp: number; value: number; min?: number; max?: number }
interface DiskTempHistoryPayload { data: DiskTempHistoryPoint[]; stats: { min: number; max: number; avg: number; current: number } }

// The report wants the broadest temperature history possible, but the
// `month` bucket (2h granularity) returns <2 points on freshly-deployed
// hosts where data only spans ~1 hour. Cascade through coarser → finer
// timeframes and use the first one that yields a renderable chart.
async function fetchTempHistoryForReport(diskName: string): Promise<DiskTempHistoryPayload | undefined> {
  for (const tf of ['month', 'week', 'day', 'hour']) {
    try {
      const result = await fetchApi<DiskTempHistoryPayload>(
        `/api/disk/${encodeURIComponent(diskName)}/temperature/history?timeframe=${tf}`,
      )
      if (result?.data && result.data.length >= 2) return result
    } catch {
      /* try next */
    }
  }
  return undefined
}

function openSmartReport(disk: DiskInfo, testStatus: SmartTestStatus, smartAttributes: SmartAttribute[], observations: DiskObservation[] = [], lastTestDate?: string, targetWindow?: Window, isHistorical = false, tempHistory?: DiskTempHistoryPayload) {
  const now = new Date().toLocaleString()
  const logoUrl = `${window.location.origin}/images/proxmenux-logo.png`
  const reportId = `SMART-${Date.now().toString(36).toUpperCase()}`

  // --- Enriched device fields from smart_data ---
  const sd = testStatus.smart_data
  const modelFamily   = sd?.model_family   || ''
  const formFactor    = sd?.form_factor    || ''
  const physBlockSize = sd?.physical_block_size ?? 512
  const trimSupported = sd?.trim_supported ?? false
  const sataVersion   = sd?.sata_version   || ''
  const ifaceSpeed    = sd?.interface_speed || ''
  const pollingShort  = sd?.polling_minutes_short
  const pollingExt    = sd?.polling_minutes_extended
  const errorLogCount = sd?.error_log_count ?? 0
  const selfTestHistory = sd?.self_test_history || []

  // SMR detection (WD Red without Plus, known SMR families)
  const isSMR = modelFamily.toLowerCase().includes('smr') ||
    /WD (Red|Blue|Green) \d/.test(modelFamily) ||
    /WDC WD\d{4}[EZ]/.test(disk.model || '')

  // Seagate proprietary Raw_Read_Error_Rate detection
  const isSeagate = modelFamily.toLowerCase().includes('seagate') ||
    modelFamily.toLowerCase().includes('barracuda') ||
    modelFamily.toLowerCase().includes('ironwolf') ||
    (disk.model || '').startsWith('ST')

  // Test age warning
  let testAgeDays = 0
  let testAgeWarning = ''
  if (lastTestDate) {
    const testDate = new Date(lastTestDate)
    testAgeDays = Math.floor((Date.now() - testDate.getTime()) / (1000 * 60 * 60 * 24))
    if (testAgeDays > 90) {
      testAgeWarning = `This report is based on a SMART test performed ${testAgeDays} days ago (${testDate.toLocaleDateString()}). Disk health may have changed since then. We recommend running a new SMART test for up-to-date results.`
    }
  }

  // Determine disk type (SAS detected via backend flag or connection_type)
  const isSasDisk = sd?.is_sas === true || disk.connection_type === 'sas'
  let diskType = "HDD"
  if (disk.name.startsWith("nvme")) {
    diskType = "NVMe"
  } else if (isSasDisk) {
    diskType = "SAS"
  } else if (!disk.rotation_rate || disk.rotation_rate === 0) {
    diskType = "SSD"
  }
  
  // Health status styling
  const healthStatus = testStatus.smart_status || (testStatus.smart_data?.smart_status) || 'unknown'
  const isHealthy = healthStatus.toLowerCase() === 'passed'
  const healthColor = isHealthy ? '#16a34a' : healthStatus.toLowerCase() === 'failed' ? '#dc2626' : '#ca8a04'
  const healthLabel = isHealthy ? 'PASSED' : healthStatus.toUpperCase()
  
  // Format power on time — force 'en' locale for consistent comma separator
  const fmtNum = (n: number) => n.toLocaleString('en-US')
  const powerOnHours = disk.power_on_hours || testStatus.smart_data?.power_on_hours || 0
  const powerOnDays = Math.round(powerOnHours / 24)
  const powerOnYears = Math.floor(powerOnHours / 8760)
  const powerOnRemainingDays = Math.floor((powerOnHours % 8760) / 24)
  const powerOnFormatted = powerOnYears > 0
    ? `${powerOnYears}y ${powerOnRemainingDays}d (${fmtNum(powerOnHours)}h)`
    : `${powerOnDays}d (${fmtNum(powerOnHours)}h)`
  
  // Build attributes table - format differs for NVMe vs SATA
  const isNvmeForTable = diskType === 'NVMe'
  
  // Explanations for NVMe metrics
  const nvmeExplanations: Record<string, string> = {
    'Critical Warning': 'Active alert flags from the NVMe controller. Any non-zero value requires immediate investigation.',
    'Temperature': 'Composite temperature reported by the controller. Sustained high temps cause thermal throttling and reduce NAND lifespan.',
    'Temperature Sensor 1': 'Primary temperature sensor, usually the NAND flash. Most representative of flash health.',
    'Temperature Sensor 2': 'Secondary sensor, often the controller die. Typically runs hotter than Sensor 1.',
    'Temperature Sensor 3': 'Tertiary sensor, if present. Location varies by manufacturer.',
    'Available Spare': 'Percentage of spare NAND blocks remaining for bad-block replacement. Alert triggers below threshold.',
    'Available Spare Threshold': 'Manufacturer-set minimum for Available Spare. Below this, the drive flags a critical warning.',
    'Percentage Used': "Drive's own estimate of endurance consumed based on actual vs. rated write cycles. 100% = rated TBW reached; drive may continue working beyond this.",
    'Percent Used': "Drive's own estimate of endurance consumed based on actual vs. rated write cycles. 100% = rated TBW reached; drive may continue working beyond this.",
    'Media Errors': 'Unrecoverable read/write errors on the NAND flash. Any non-zero value indicates permanent cell damage. Growing count = replace soon.',
    'Media and Data Integrity Errors': 'Unrecoverable errors detected by the controller. Non-zero means data corruption risk.',
    'Unsafe Shutdowns': 'Power losses without proper flush/shutdown. Very high counts risk metadata corruption and firmware issues.',
    'Power Cycles': 'Total on/off cycles. Frequent cycling increases connector and capacitor wear.',
    'Power On Hours': 'Total cumulative hours the drive has been powered on since manufacture.',
    'Data Units Read': 'Total data read in 512KB units. Multiply by 512,000 for bytes. Useful for calculating daily read workload.',
    'Data Units Written': 'Total data written in 512KB units. Compare with TBW rating to estimate remaining endurance.',
    'Host Read Commands': 'Total read commands issued by the host. High ratio vs. write commands indicates read-heavy workload.',
    'Host Write Commands': 'Total write commands issued by the host. Includes filesystem metadata writes.',
    'Controller Busy Time': 'Total minutes the controller spent processing I/O commands. High values indicate sustained heavy workload.',
    'Error Log Entries': 'Number of entries in the error information log. Often includes benign self-test artifacts; cross-check with Media Errors.',
    'Error Information Log Entries': 'Number of entries in the error information log. Often includes benign self-test artifacts.',
    'Warning Temp Time': 'Total minutes spent above the warning temperature threshold. Causes performance throttling. Zero is ideal.',
    'Critical Temp Time': 'Total minutes spent above the critical temperature threshold. Drive may shut down to prevent damage. Should always be zero.',
    'Warning Composite Temperature Time': 'Total minutes the composite temperature exceeded the warning threshold.',
    'Critical Composite Temperature Time': 'Total minutes the composite temperature exceeded the critical threshold. Must be zero.',
    'Thermal Management T1 Trans Count': 'Number of times the drive entered light thermal throttling (T1). Indicates cooling issues.',
    'Thermal Management T2 Trans Count': 'Number of times the drive entered heavy thermal throttling (T2). Significant performance impact.',
    'Thermal Management T1 Total Time': 'Total seconds spent in light thermal throttling. Indicates sustained cooling problems.',
    'Thermal Management T2 Total Time': 'Total seconds spent in heavy thermal throttling. Severe performance degradation.',
  }
  
  // Explanations for SATA/SSD attributes — covers HDD, SSD, and mixed-use attributes
  const sataExplanations: Record<string, string> = {
    // === Read/Write Errors ===
    'Raw Read Error Rate': 'Hardware read errors detected. High raw values on Seagate/Samsung drives are normal (proprietary formula where VALUE, not raw, matters).',
    'Write Error Rate': 'Errors encountered during write operations. Growing count may indicate head or media issues.',
    'Multi Zone Error Rate': 'Errors when writing to multi-zone regions. Manufacturer-specific; rising trend is concerning.',
    'Soft Read Error Rate': 'Read errors corrected by firmware without data loss. High values may indicate degrading media.',
    'Read Error Retry Rate': 'Number of read retries needed. Occasional retries are normal; persistent growth indicates wear.',
    'Reported Uncorrect': 'Errors that ECC could not correct. Any non-zero value means data was lost or unreadable.',
    'Reported Uncorrectable Errors': 'Errors that ECC could not correct. Non-zero = data loss risk.',

    // === Reallocated / Pending / Offline ===
    'Reallocated Sector Ct': 'Bad sectors replaced by spare sectors from the reserve pool. Growing count = drive degradation.',
    'Reallocated Sector Count': 'Bad sectors replaced by spare sectors. Growing count indicates drive degradation.',
    'Reallocated Sectors': 'Bad sectors replaced by spare sectors. Growing count indicates drive degradation.',
    'Retired Block Count': 'NAND blocks retired due to wear or failure (SSD). Similar to Reallocated Sector Count for HDDs.',
    'Reallocated Event Count': 'Number of remap operations performed. Each event means a bad sector was replaced.',
    'Current Pending Sector': 'Unstable sectors waiting to be remapped on next write. May resolve or become permanently reallocated.',
    'Current Pending Sector Count': 'Unstable sectors waiting to be remapped on next write. Non-zero warrants monitoring.',
    'Pending Sectors': 'Sectors waiting to be remapped. May resolve or become reallocated.',
    'Offline Uncorrectable': 'Sectors that failed during offline scan and could not be corrected. Indicates potential data loss.',
    'Offline Uncorrectable Sector Count': 'Uncorrectable sectors found during background scan. Data on these sectors is lost.',

    // === Temperature ===
    'Temperature': 'Current drive temperature. Sustained high temps accelerate wear and reduce lifespan.',
    'Temperature Celsius': 'Current drive temperature in Celsius. HDDs: keep below 45°C; SSDs: below 60°C.',
    'Airflow Temperature Cel': 'Temperature measured by the airflow sensor. Usually slightly lower than the main temp sensor.',
    'Temperature Case': 'Temperature of the drive casing. Useful for monitoring enclosure ventilation.',
    'Temperature Internal': 'Internal temperature sensor. May read higher than case temperature.',

    // === Power & Uptime ===
    'Power On Hours': 'Total cumulative hours the drive has been powered on. Used to estimate age and plan replacements.',
    'Power On Hours and Msec': 'Total powered-on time with millisecond precision.',
    'Power Cycle Count': 'Total number of complete power on/off cycles. Frequent cycling stresses electronics.',
    'Power Off Retract Count': 'Times the heads were retracted due to power loss (HDD). High values indicate unstable power supply.',
    'Unexpected Power Loss Ct': 'Unexpected power losses (SSD). Can cause metadata corruption if write-cache was active.',
    'Unsafe Shutdown Count': 'Power losses without proper shutdown (SSD). High values risk firmware corruption.',
    'Start Stop Count': 'Spindle motor start/stop cycles (HDD). Each cycle causes mechanical wear.',

    // === Mechanical (HDD-specific) ===
    'Spin Up Time': 'Time for platters to reach full operating speed (HDD). Increasing values may indicate motor bearing wear.',
    'Spin Retry Count': 'Failed attempts to spin up the motor (HDD). Non-zero usually indicates power supply or motor issues.',
    'Calibration Retry Count': 'Number of head calibration retries (HDD). Non-zero may indicate mechanical issues.',
    'Seek Error Rate': 'Errors during head positioning (HDD). High raw values on Seagate are often normal (proprietary formula).',
    'Seek Time Performance': 'Average seek operation performance (HDD). Declining values suggest mechanical degradation.',
    'Load Cycle Count': 'Head load/unload cycles (HDD). Rated for 300K-600K cycles on most drives.',
    'Load Unload Cycle Count': 'Head load/unload cycles (HDD). Each cycle causes micro-wear on the ramp mechanism.',
    'Head Flying Hours': 'Hours the read/write heads have been positioned over the platters (HDD).',
    'High Fly Writes': 'Writes where the head flew higher than expected (HDD). Data may not be written correctly.',
    'G Sense Error Rate': 'Shock/vibration events detected by the accelerometer (HDD). High values indicate physical disturbance.',
    'Disk Shift': 'Distance the disk has shifted from its original position (HDD). Temperature or shock-related.',
    'Loaded Hours': 'Hours spent with heads loaded over the platters (HDD).',
    'Load In Time': 'Time of the head loading process. Manufacturer-specific diagnostic metric.',
    'Torque Amplification Count': 'Times the drive needed extra torque to spin up. May indicate stiction or motor issues.',
    'Flying Height': 'Head-to-platter distance during operation (HDD). Critical for read/write reliability.',
    'Load Friction': 'Friction detected during head loading (HDD). Increasing values suggest ramp mechanism wear.',
    'Load Unload Retry Count': 'Failed head load/unload attempts (HDD). Non-zero indicates mechanical issues.',

    // === Interface Errors ===
    'UDMA CRC Error Count': 'Data transfer checksum errors on the SATA cable. Usually caused by a bad cable, loose connection, or port issue.',
    'CRC Errors': 'Interface communication errors. Usually caused by cable or connection issues.',
    'CRC Error Count': 'Data transfer checksum errors. Replace the SATA cable if this value grows.',
    'Command Timeout': 'Commands that took too long and timed out. May indicate controller or connection issues.',
    'Interface CRC Error Count': 'CRC errors on the interface link. Cable or connector problem.',

    // === ECC & Data Integrity ===
    'Hardware ECC Recovered': 'Read errors corrected by hardware ECC. Non-zero is normal; rapid growth warrants attention.',
    'ECC Error Rate': 'Rate of ECC-corrected errors. Proprietary formula; VALUE matters more than raw count.',
    'End to End Error': 'Data corruption detected between the controller cache and host interface. Should always be zero.',
    'End to End Error Detection Count': 'Number of parity errors in the data path. Non-zero indicates controller issues.',

    // === SSD Wear & Endurance ===
    'Wear Leveling Count': 'Average erase cycles per NAND block (SSD). Lower VALUE = more wear consumed.',
    'Wear Range Delta': 'Difference between most-worn and least-worn blocks (SSD). High values indicate uneven wear.',
    'Media Wearout Indicator': 'Intel SSD life remaining estimate. Starts at 100, decreases to 0 as endurance is consumed.',
    'SSD Life Left': 'Estimated remaining SSD lifespan percentage based on NAND wear.',
    'Percent Lifetime Remain': 'Estimated remaining lifespan percentage. 100 = new; 0 = end of rated life.',
    'Percent Lifetime Used': 'Percentage of rated endurance consumed. Inverse of Percent Lifetime Remain.',
    'Available Reservd Space': 'Remaining spare blocks as a percentage of total reserves (SSD). Similar to NVMe Available Spare.',
    'Available Reserved Space': 'Remaining spare blocks as a percentage (SSD). Low values reduce the drive\'s ability to handle bad blocks.',
    'Used Rsvd Blk Cnt Tot': 'Total reserve blocks consumed for bad-block replacement (SSD). Growing = aging.',
    'Used Reserved Block Count': 'Number of reserve blocks used for bad-block replacement (SSD).',
    'Unused Rsvd Blk Cnt Tot': 'Remaining reserve blocks available (SSD). Zero = no more bad-block replacement possible.',
    'Unused Reserve Block Count': 'Reserve blocks still available for bad-block replacement (SSD).',
    'Program Fail Cnt Total': 'Total NAND program (write) failures (SSD). Non-zero indicates flash cell degradation.',
    'Program Fail Count': 'NAND write failures (SSD). Growing count means flash cells are wearing out.',
    'Program Fail Count Chip': 'Program failures at chip level (SSD). Non-zero indicates NAND degradation.',
    'Erase Fail Count': 'NAND erase operation failures (SSD). Non-zero indicates severe flash wear.',
    'Erase Fail Count Total': 'Total NAND erase failures (SSD). Combined with Program Fail Count shows overall NAND health.',
    'Erase Fail Count Chip': 'Erase failures at chip level (SSD). Non-zero = NAND degradation.',
    'Runtime Bad Block': 'Bad blocks discovered during normal operation (SSD). Different from factory-mapped bad blocks.',
    'Runtime Bad Blocks': 'Blocks that failed during use (SSD). Growing count = flash wearing out.',

    // === Data Volume ===
    'Total LBAs Written': 'Total logical block addresses written. Multiply by 512 bytes for total data volume.',
    'Total LBAs Read': 'Total logical block addresses read. Useful for calculating daily workload.',
    'Lifetime Writes GiB': 'Total data written in GiB over the drive\'s lifetime.',
    'Lifetime Reads GiB': 'Total data read in GiB over the drive\'s lifetime.',
    'Total Writes GiB': 'Total data written in GiB. Compare with TBW rating for endurance estimate.',
    'Total Reads GiB': 'Total data read in GiB.',
    'NAND Writes GiB': 'Raw NAND writes in GiB. Higher than host writes due to write amplification.',
    'Host Writes 32MiB': 'Total data written by the host in 32MiB units.',
    'Host Reads 32MiB': 'Total data read by the host in 32MiB units.',
    'Host Writes MiB': 'Total data written by the host in MiB.',
    'Host Reads MiB': 'Total data read by the host in MiB.',
    'NAND GB Written TLC': 'Total data written to TLC NAND cells in GB. Includes write amplification overhead.',
    'NAND GiB Written': 'Total NAND writes in GiB. Higher than host writes due to write amplification and garbage collection.',

    // === SSD-Specific Advanced ===
    'Ave Block Erase Count': 'Average number of erase cycles per NAND block (SSD). Drives are typically rated for 3K-100K cycles.',
    'Average Erase Count': 'Average erase cycles per block. Compare with rated endurance for remaining life estimate.',
    'Max Erase Count': 'Maximum erase cycles on any single block. Large gap with average indicates uneven wear.',
    'Total Erase Count': 'Sum of all erase cycles across all blocks. Overall NAND write volume indicator.',
    'Power Loss Cap Test': 'Result of the power-loss protection capacitor self-test (SSD). Failed = risk of data loss on power failure.',
    'Power Loss Protection': 'Status of the power-loss protection mechanism. Enterprise SSDs use capacitors to flush cache on power loss.',
    'Successful RAIN Recov Cnt': 'Successful recoveries using RAIN (Redundant Array of Independent NAND). Shows NAND parity is working.',
    'SSD Erase Fail Count': 'Total erase failures across the SSD. Indicates overall NAND degradation.',
    'SSD Program Fail Count': 'Total write failures across the SSD. Indicates flash cell reliability issues.',

    // === Throughput ===
    'Throughput Performance': 'Overall throughput performance rating (HDD). Declining values indicate degradation.',

    // === Other / Vendor-specific ===
    'Unknown Attribute': 'Vendor-specific attribute not defined in the SMART standard. Check manufacturer documentation.',
    'Free Fall Sensor': 'Free-fall events detected (laptop HDD). The heads are parked to prevent damage during drops.',
  }
  
  // Explanations for SAS/SCSI metrics
  const sasExplanations: Record<string, string> = {
    'Grown Defect List': 'Sectors remapped due to defects found during operation. Equivalent to Reallocated Sectors on SATA. Growing count = drive degradation.',
    'Read Errors Corrected': 'Read errors corrected by ECC. Normal for enterprise drives under heavy workload — only uncorrected errors are critical.',
    'Read ECC Fast': 'Errors corrected by fast (on-the-fly) ECC during read operations. Normal in SAS drives.',
    'Read ECC Delayed': 'Errors requiring delayed (offline) ECC correction during reads. Non-zero is acceptable but should not grow rapidly.',
    'Read Uncorrected Errors': 'Read errors that ECC could not correct. Non-zero means data was lost or unreadable. Critical metric.',
    'Read Data Processed': 'Total data read by the drive. Useful for calculating daily workload.',
    'Write Errors Corrected': 'Write errors corrected by ECC. Normal for enterprise drives.',
    'Write Uncorrected Errors': 'Write errors that ECC could not correct. Non-zero = potential data loss. Critical.',
    'Write Data Processed': 'Total data written to the drive. Useful for workload analysis.',
    'Verify Errors Corrected': 'Verification errors corrected during background verify operations.',
    'Verify Uncorrected Errors': 'Verify errors that could not be corrected. Non-zero indicates media degradation.',
    'Non-Medium Errors': 'Controller/bus errors not related to the media itself. High count may indicate backplane or cable issues.',
    'Temperature': 'Current drive temperature. Enterprise SAS drives tolerate up to 55-60°C under sustained load.',
    'Power On Hours': 'Total hours the drive has been powered on. Enterprise drives are rated for 24/7 operation.',
    'Start-Stop Cycles': 'Motor start/stop cycles. Enterprise SAS drives are rated for 50,000+ cycles.',
    'Load-Unload Cycles': 'Head load/unload cycles. Enterprise drives are rated for 600,000+ cycles.',
    'Background Scan Status': 'Status of the SCSI background media scan. Runs continuously to detect surface defects.',
  }

  const getAttrExplanation = (name: string, diskKind: string): string => {
    const cleanName = name.replace(/_/g, ' ')
    if (diskKind === 'NVMe') {
      return nvmeExplanations[cleanName] || nvmeExplanations[name] || ''
    }
    if (diskKind === 'SAS') {
      return sasExplanations[cleanName] || sasExplanations[name] || ''
    }
    return sataExplanations[cleanName] || sataExplanations[name] || ''
  }

  // SAS and NVMe use simplified table format (Metric | Value | Status)
  const useSimpleTable = isNvmeForTable || isSasDisk

  const attributeRows = smartAttributes.map((attr, i) => {
  const statusColor = attr.status === 'ok' ? '#16a34a' : attr.status === 'warning' ? '#ca8a04' : '#dc2626'
  const statusBg = attr.status === 'ok' ? '#16a34a15' : attr.status === 'warning' ? '#ca8a0415' : '#dc262615'
  const explanation = getAttrExplanation(attr.name, diskType)
  const explainRow = explanation
    ? `<tr class="attr-explain-row"><td colspan="${useSimpleTable ? '3' : '7'}" style="padding:0 4px 8px;border-bottom:1px solid #f1f5f9;"><div style="font-size:10px;color:#64748b;line-height:1.4;">${explanation}</div></td></tr>`
    : ''

  if (useSimpleTable) {
    // NVMe/SAS format: Metric | Value | Status
    const displayValue = isSasDisk ? attr.raw_value : attr.value
    return `
    <tr>
      <td class="col-name" style="font-weight:500;${explanation ? 'border-bottom:none;padding-bottom:2px;' : ''}">${attr.name}</td>
      <td style="text-align:center;font-family:monospace;${explanation ? 'border-bottom:none;' : ''}">${displayValue}</td>
      <td style="${explanation ? 'border-bottom:none;' : ''}"><span class="f-tag" style="background:${statusBg};color:${statusColor}">${attr.status === 'ok' ? 'OK' : attr.status.toUpperCase()}</span></td>
    </tr>
    ${explainRow}`
  } else {
    // SATA format: ID | Attribute | Val | Worst | Thr | Raw | Status
    return `
    <tr>
      <td style="font-weight:600;${explanation ? 'border-bottom:none;padding-bottom:2px;' : ''}">${attr.id}</td>
      <td class="col-name" style="font-weight:500;${explanation ? 'border-bottom:none;padding-bottom:2px;' : ''}">${attr.name.replace(/_/g, ' ')}</td>
      <td style="text-align:center;${explanation ? 'border-bottom:none;' : ''}">${attr.value}</td>
      <td style="text-align:center;${explanation ? 'border-bottom:none;' : ''}">${attr.worst}</td>
      <td style="text-align:center;${explanation ? 'border-bottom:none;' : ''}">${attr.threshold}</td>
      <td class="col-raw" style="${explanation ? 'border-bottom:none;' : ''}">${attr.raw_value}</td>
      <td style="${explanation ? 'border-bottom:none;' : ''}"><span class="f-tag" style="background:${statusBg};color:${statusColor}">${attr.status === 'ok' ? 'OK' : attr.status.toUpperCase()}</span></td>
    </tr>
    ${explainRow}`
  }
  }).join('')
  
  // Critical attributes to highlight
  const criticalAttrs = smartAttributes.filter(a => a.status !== 'ok')
  const hasCritical = criticalAttrs.length > 0
  
  // Temperature color and threshold strings for the printable report —
  // both pulled from the user-configurable backend cache so the report
  // prints whatever the operator set in Settings.
  const _reportThresholds = getDiskTempThresholdsSync(diskType)
  const getTempColorForReport = (temp: number): string => {
    if (temp <= 0) return '#94a3b8' // gray for N/A
    if (temp >= _reportThresholds.hot) return '#dc2626'
    if (temp >= _reportThresholds.warn) return '#ca8a04'
    return '#16a34a'
  }

  // Temperature thresholds for display
  const tempThresholds = {
    optimal: `<${_reportThresholds.warn}°C`,
    warning: `${_reportThresholds.warn}-${_reportThresholds.hot - 1}°C`,
    critical: `≥${_reportThresholds.hot}°C`,
  }
  const isNvmeDisk = diskType === 'NVMe'

  // NVMe Wear & Lifetime data. Sprint 14 fix: the previous code used
  // `?? 0` / `?? 100` as fallbacks, which made the report invent
  // "100% Life Remaining" + "100% Available Spare" for drives that
  // simply don't report those metrics (some early WDC SN720, some
  // Samsung OEM, etc.). The dashboard modal already hides its wear
  // section in that case — we mirror the same gating here so the
  // printable report doesn't lie.
  const nvmePercentUsedRaw = testStatus.smart_data?.nvme_raw?.percent_used ?? disk.percentage_used
  const nvmeAvailSpareRaw = testStatus.smart_data?.nvme_raw?.avail_spare
  // Sprint 14 honest-data fix (refined): only render the full Wear &
  // Lifetime block when the firmware has actually started ticking
  // percent_used. Drives like the WD CL SN720 expose `percent_used: 0`
  // until significant wear is reached — treating that as "100% life
  // remaining" is misleading. In that case we fall back to a minimal
  // Data-Written-only block (handled separately below).
  const hasNvmeWearData = (
    typeof nvmePercentUsedRaw === 'number' && nvmePercentUsedRaw > 0
  )
  const nvmePercentUsed = nvmePercentUsedRaw ?? 0
  const nvmeAvailSpare = nvmeAvailSpareRaw ?? 100
  const nvmeDataWritten = testStatus.smart_data?.nvme_raw?.data_units_written ?? 0
  // Data units are in 512KB blocks, convert to TB
  const nvmeDataWrittenTB = (nvmeDataWritten * 512 * 1024) / (1024 * 1024 * 1024 * 1024)
  
  // Calculate estimated life remaining for NVMe
  let nvmeEstimatedLife = 'N/A'
  if (nvmePercentUsed > 0 && disk.power_on_hours && disk.power_on_hours > 0) {
    const totalEstimatedHours = disk.power_on_hours / (nvmePercentUsed / 100)
    const remainingHours = totalEstimatedHours - disk.power_on_hours
    const remainingYears = remainingHours / (24 * 365)
    if (remainingYears >= 1) {
      nvmeEstimatedLife = `~${remainingYears.toFixed(1)} years`
    } else if (remainingHours >= 24) {
      nvmeEstimatedLife = `~${Math.floor(remainingHours / 24)} days`
    } else {
      nvmeEstimatedLife = `~${Math.floor(remainingHours)} hours`
    }
  } else if (nvmePercentUsed === 0) {
    nvmeEstimatedLife = 'Excellent'
  }
  
  // Wear color based on percentage
  const getWearColorHex = (pct: number): string => {
    if (pct <= 50) return '#16a34a' // green
    if (pct <= 80) return '#ca8a04' // yellow
    return '#dc2626' // red
  }
  
  // Life remaining color (inverse)
  const getLifeColorHex = (pct: number): string => {
    const remaining = 100 - pct
    if (remaining >= 50) return '#16a34a' // green
    if (remaining >= 20) return '#ca8a04' // yellow
    return '#dc2626' // red
  }
  
  // Build recommendations
  const recommendations: string[] = []
  if (isHealthy) {
    recommendations.push('<div class="rec-item rec-ok"><div class="rec-icon">&#10003;</div><div><strong>Disk is Healthy</strong><p>All SMART attributes are within normal ranges. Continue regular monitoring.</p></div></div>')
  } else {
    recommendations.push('<div class="rec-item rec-critical"><div class="rec-icon">&#10007;</div><div><strong>Critical: Disk Health Issue Detected</strong><p>SMART has reported a health issue. Backup all data immediately and plan for disk replacement.</p></div></div>')
  }
  
  if ((disk.reallocated_sectors ?? 0) > 0) {
    recommendations.push(`<div class="rec-item rec-warn"><div class="rec-icon">&#9888;</div><div><strong>Reallocated Sectors Detected (${disk.reallocated_sectors})</strong><p>The disk has bad sectors that have been remapped. Monitor closely and consider replacement if count increases.</p></div></div>`)
  }
  
  if ((disk.pending_sectors ?? 0) > 0) {
    recommendations.push(`<div class="rec-item rec-warn"><div class="rec-icon">&#9888;</div><div><strong>Pending Sectors (${disk.pending_sectors})</strong><p>There are sectors waiting to be reallocated. This may indicate impending failure.</p></div></div>`)
  }
  
  if (disk.temperature > 55 && diskType === 'HDD') {
    recommendations.push(`<div class="rec-item rec-warn"><div class="rec-icon">&#9888;</div><div><strong>High Temperature (${disk.temperature}°C)</strong><p>HDD is running hot. Improve case airflow or add cooling.</p></div></div>`)
  } else if (disk.temperature > 70 && diskType === 'SSD') {
    recommendations.push(`<div class="rec-item rec-warn"><div class="rec-icon">&#9888;</div><div><strong>High Temperature (${disk.temperature}°C)</strong><p>SSD is running hot. Check airflow around the drive.</p></div></div>`)
  } else if (disk.temperature > 80 && diskType === 'NVMe') {
    recommendations.push(`<div class="rec-item rec-warn"><div class="rec-icon">&#9888;</div><div><strong>High Temperature (${disk.temperature}°C)</strong><p>NVMe is overheating. Consider adding a heatsink or improving case airflow.</p></div></div>`)
  }
  
  // NVMe critical warning
  if (diskType === 'NVMe') {
    const critWarnVal = testStatus.smart_data?.nvme_raw?.critical_warning ?? 0
    const mediaErrVal = testStatus.smart_data?.nvme_raw?.media_errors ?? 0
    const unsafeVal   = testStatus.smart_data?.nvme_raw?.unsafe_shutdowns ?? 0
    if (critWarnVal !== 0) {
      recommendations.push(`<div class="rec-item rec-critical"><div class="rec-icon">&#10007;</div><div><strong>NVMe Critical Warning Active (0x${critWarnVal.toString(16).toUpperCase()})</strong><p>The NVMe controller has raised an alert flag. Back up data immediately and investigate further.</p></div></div>`)
    }
    if (mediaErrVal > 0) {
      recommendations.push(`<div class="rec-item rec-critical"><div class="rec-icon">&#10007;</div><div><strong>NVMe Media Errors Detected (${mediaErrVal})</strong><p>Unrecoverable errors in NAND flash cells. Any non-zero value indicates physical flash damage. Back up data and plan for replacement.</p></div></div>`)
    }
    if (unsafeVal > 200) {
      recommendations.push(`<div class="rec-item rec-warn"><div class="rec-icon">&#9888;</div><div><strong>High Unsafe Shutdown Count (${unsafeVal})</strong><p>Frequent power losses without proper shutdown increase the risk of firmware corruption. Ensure stable power supply or use a UPS.</p></div></div>`)
    }
  }

  // Seagate Raw_Read_Error_Rate note
  if (isSeagate) {
    const hasRawReadAttr = smartAttributes.some(a => a.name === 'Raw_Read_Error_Rate' || a.id === 1)
    if (hasRawReadAttr) {
      recommendations.push('<div class="rec-item rec-info"><div class="rec-icon">&#9432;</div><div><strong>Seagate Raw_Read_Error_Rate — Normal Behavior</strong><p>Seagate drives report very large raw values for attribute #1 (Raw_Read_Error_Rate). This is expected and uses a proprietary formula — a high raw number does NOT indicate errors. Only the normalized value (column Val) matters, and it should remain at 100.</p></div></div>')
    }
  }

  // SMR disk note
  if (isSMR) {
    recommendations.push('<div class="rec-item rec-info"><div class="rec-icon">&#9432;</div><div><strong>SMR Drive Detected — Write Limitations</strong><p>This appears to be a Shingled Magnetic Recording (SMR) disk. SMR drives have slower random-write performance and may stall during heavy mixed workloads. They are suitable for sequential workloads (backups, archives) but not recommended as primary Proxmox storage or ZFS vdevs.</p></div></div>')
  }

  if (recommendations.length === 1 && isHealthy) {
    recommendations.push('<div class="rec-item rec-info"><div class="rec-icon">&#9432;</div><div><strong>Regular Maintenance</strong><p>Schedule periodic extended SMART tests (monthly) to catch issues early.</p></div></div>')
    recommendations.push('<div class="rec-item rec-info"><div class="rec-icon">&#9432;</div><div><strong>Backup Strategy</strong><p>Ensure critical data is backed up regularly regardless of disk health status.</p></div></div>')
  }
  
  // Build observations HTML separately to avoid nested template literal issues
  let observationsHtml = ''
  if (observations.length > 0) {
    const totalOccurrences = observations.reduce((sum, o) => sum + o.occurrence_count, 0)
    
    // Group observations by error type
    const groupedObs: Record<string, DiskObservation[]> = {}
    observations.forEach(obs => {
      const type = obs.error_type || 'unknown'
      if (!groupedObs[type]) groupedObs[type] = []
      groupedObs[type].push(obs)
    })
    
    let groupsHtml = ''
    Object.entries(groupedObs).forEach(([type, obsList]) => {
      const typeLabel = type === 'io_error' ? 'I/O Errors' : type === 'smart_error' ? 'SMART Errors' : type === 'filesystem_error' ? 'Filesystem Errors' : type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
      const groupOccurrences = obsList.reduce((sum, o) => sum + o.occurrence_count, 0)
      
      let obsItemsHtml = ''
      obsList.forEach(obs => {
        // Use blue (info) as base color for all observations
        const infoColor = '#3b82f6'
        const infoBg = '#3b82f615'
        // Severity badge color based on actual severity
        const severityBadgeColor = obs.severity === 'critical' ? '#dc2626' : obs.severity === 'warning' ? '#ca8a04' : '#3b82f6'
        const severityLabel = obs.severity ? obs.severity.charAt(0).toUpperCase() + obs.severity.slice(1) : 'Info'
        const firstDate = obs.first_occurrence ? new Date(obs.first_occurrence).toLocaleString() : 'N/A'
        const lastDate = obs.last_occurrence ? new Date(obs.last_occurrence).toLocaleString() : 'N/A'
        const dismissedBadge = obs.dismissed ? '<span style="background:#16a34a20;color:#16a34a;padding:2px 6px;border-radius:4px;font-size:10px;margin-left:4px;">Dismissed</span>' : ''
        const errorTypeLabel = type === 'io_error' ? 'I/O Error' : type === 'smart_error' ? 'SMART Error' : type === 'filesystem_error' ? 'Filesystem Error' : type.replace(/_/g, ' ')
        
        obsItemsHtml += `
        <div style="background:${infoBg};border:1px solid ${infoColor}30;border-radius:8px;padding:16px;">
          <div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:10px;">
            <span style="background:${infoColor}20;color:${infoColor};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">${errorTypeLabel}</span>
            <span style="background:${severityBadgeColor}20;color:${severityBadgeColor};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">${severityLabel}</span>
            <span style="background:#64748b20;color:#475569;padding:2px 8px;border-radius:4px;font-size:11px;">ID: #${obs.id}</span>
            <span style="background:#64748b20;color:#475569;padding:2px 8px;border-radius:4px;font-size:11px;">Occurrences: <strong>${obs.occurrence_count}</strong></span>
            ${dismissedBadge}
          </div>
          
          <div style="margin-bottom:10px;">
            <div style="font-size:10px;color:#475569;margin-bottom:4px;">Error Signature:</div>
            <div style="font-family:monospace;font-size:11px;color:#1e293b;background:#f1f5f9;padding:8px;border-radius:4px;word-break:break-all;">${obs.error_signature}</div>
          </div>
          
          <div style="margin-bottom:12px;">
            <div style="font-size:10px;color:#475569;margin-bottom:4px;">Raw Message:</div>
            <div style="font-family:monospace;font-size:11px;color:#1e293b;background:#f8fafc;padding:10px;border-radius:4px;white-space:pre-wrap;word-break:break-all;max-height:120px;overflow-y:auto;">${obs.raw_message || 'N/A'}</div>
            ${translateAtaError(obs.raw_message || '') ? `<div style="font-size:11px;color:#475569;font-style:italic;margin-top:6px;padding-left:4px;">↳ ${translateAtaError(obs.raw_message || '')}</div>` : ''}
          </div>
          
          <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));gap:10px;font-size:11px;padding-top:10px;border-top:1px solid ${infoColor}20;">
            <div>
              <span style="color:#475569;">Device:</span>
              <strong style="color:#1e293b;margin-left:4px;">${obs.device_name || disk.name}</strong>
            </div>
            <div>
              <span style="color:#475569;">Serial:</span>
              <strong style="color:#1e293b;margin-left:4px;">${obs.serial || disk.serial || 'N/A'}</strong>
            </div>
            <div>
              <span style="color:#475569;">Model:</span>
              <strong style="color:#1e293b;margin-left:4px;">${obs.model || disk.model || 'N/A'}</strong>
            </div>
            <div>
              <span style="color:#475569;">First Seen:</span>
              <strong style="color:#1e293b;margin-left:4px;">${firstDate}</strong>
            </div>
            <div>
              <span style="color:#475569;">Last Seen:</span>
              <strong style="color:#1e293b;margin-left:4px;">${lastDate}</strong>
            </div>
          </div>
        </div>
        `
      })
      
      groupsHtml += `
      <div style="margin-bottom:20px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #e2e8f0;">
          <span style="font-weight:600;color:#1e293b;">${typeLabel}</span>
          <span style="background:#64748b15;color:#475569;padding:2px 8px;border-radius:4px;font-size:11px;">${obsList.length} unique, ${groupOccurrences} total</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:12px;">
          ${obsItemsHtml}
        </div>
      </div>
      `
    })
    
  const obsSecNum = isNvmeDisk ? '6' : '5'
  observationsHtml = `
  <!-- ${obsSecNum}. Observations & Events -->
  <div class="section">
  <div class="section-title">${obsSecNum}. Observations & Events (${observations.length} recorded, ${totalOccurrences} total occurrences)</div>
      <p style="color:#475569;font-size:12px;margin-bottom:16px;">The following events have been detected and logged for this disk. These observations may indicate potential issues that require attention.</p>
      ${groupsHtml}
    </div>
    `
  }

  // Per-disk temperature history chart (Sprint 14). Rendered as inline
  // SVG so it survives the print-to-PDF path. Only emits markup when the
  // backend has actually sampled this disk; otherwise the section is
  // omitted entirely (no point printing an empty card).
  let temperatureChartHtml = ''
  if (tempHistory && tempHistory.data && tempHistory.data.length >= 2) {
    const points = tempHistory.data
    const stats = tempHistory.stats
    const W = 720, H = 200
    const padL = 38, padR = 14, padT = 16, padB = 28
    const innerW = W - padL - padR
    const innerH = H - padT - padB

    const ts0 = points[0].timestamp
    const ts1 = points[points.length - 1].timestamp
    const span = Math.max(1, ts1 - ts0)
    const vals = points.map(p => p.value)
    const dataMin = Math.min(...vals)
    const dataMax = Math.max(...vals)
    // Pad the y-domain a couple of degrees on each side so the line
    // doesn't sit flush against the chart border.
    const yMin = Math.max(0, Math.floor(dataMin - 3))
    const yMax = Math.ceil(dataMax + 3)
    const yRange = Math.max(1, yMax - yMin)

    const xFor = (t: number) => padL + ((t - ts0) / span) * innerW
    const yFor = (v: number) => padT + (1 - (v - yMin) / yRange) * innerH

    // Threshold reference lines pulled from the user-configurable
    // backend cache. `getDiskTempThresholdsSync` reads the in-memory
    // map populated by `useDiskTempThresholds` mounted on the parent
    // component — no extra fetch in the print flow.
    const _dt = getDiskTempThresholdsSync(diskType)
    const warnAt = _dt.warn
    const hotAt = _dt.hot

    const linePath = points.map((p, i) => {
      const cmd = i === 0 ? 'M' : 'L'
      return `${cmd}${xFor(p.timestamp).toFixed(1)},${yFor(p.value).toFixed(1)}`
    }).join(' ')

    // Area fill below the line (closing back along the bottom).
    const areaPath = `${linePath} L${xFor(ts1).toFixed(1)},${(padT + innerH).toFixed(1)} L${xFor(ts0).toFixed(1)},${(padT + innerH).toFixed(1)} Z`

    const formatXLabel = (ts: number) => {
      const d = new Date(ts * 1000)
      if (span <= 86400 * 2) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
    }

    // Y axis ticks — 4 evenly spaced labels.
    const yTicks: number[] = []
    for (let i = 0; i <= 4; i++) {
      yTicks.push(yMin + (yRange * i) / 4)
    }

    // X axis ticks — start, mid, end.
    const xTicks = [ts0, ts0 + span / 2, ts1]

    // Per the user's preference the report chart is blue rather than
    // colour-coded. Threshold bands and reference lines below still use
    // the warn/hot palette so a hot stretch is visible without changing
    // the line itself.
    const lineColor = '#2563eb'
    const samples = points.length

    // Threshold band y-coords (clamped to chart area).
    const yWarnBand = Math.max(padT, yFor(hotAt))
    const yHotTop = padT
    const yHotHeight = Math.max(0, yWarnBand - yHotTop)
    const yMidTop = Math.max(padT, yFor(hotAt))
    const yMidBottom = Math.min(padT + innerH, yFor(warnAt))
    const yMidHeight = Math.max(0, yMidBottom - yMidTop)

    temperatureChartHtml = `
  <div style="margin-top:14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
      <div>
        <div style="font-size:11px;font-weight:700;color:#0f172a;text-transform:uppercase;letter-spacing:0.04em;">Temperature history</div>
        <div style="font-size:10px;color:#64748b;margin-top:2px;">${samples} samples · ${formatXLabel(ts0)} → ${formatXLabel(ts1)}</div>
      </div>
      <div style="display:flex;gap:14px;font-size:11px;">
        <div><span style="color:#64748b;">Min</span> <strong style="color:#16a34a;">${stats.min}°C</strong></div>
        <div><span style="color:#64748b;">Avg</span> <strong style="color:#1e293b;">${stats.avg}°C</strong></div>
        <div><span style="color:#64748b;">Max</span> <strong style="color:#dc2626;">${stats.max}°C</strong></div>
      </div>
    </div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" style="display:block;max-height:200px;">
      <!-- threshold bands -->
      ${yHotHeight > 0 ? `<rect x="${padL}" y="${yHotTop}" width="${innerW}" height="${yHotHeight}" fill="#fee2e2" opacity="0.55"/>` : ''}
      ${yMidHeight > 0 ? `<rect x="${padL}" y="${yMidTop}" width="${innerW}" height="${yMidHeight}" fill="#fef3c7" opacity="0.55"/>` : ''}
      <!-- chart frame -->
      <rect x="${padL}" y="${padT}" width="${innerW}" height="${innerH}" fill="none" stroke="#cbd5e1" stroke-width="1"/>
      <!-- y grid + labels -->
      ${yTicks.map(t => {
        const y = yFor(t).toFixed(1)
        return `<line x1="${padL}" y1="${y}" x2="${padL + innerW}" y2="${y}" stroke="#e2e8f0" stroke-width="0.6" stroke-dasharray="2,3"/>` +
               `<text x="${padL - 5}" y="${y}" text-anchor="end" dominant-baseline="middle" font-size="9" fill="#64748b">${Math.round(t)}°</text>`
      }).join('')}
      <!-- x labels -->
      ${xTicks.map(t => {
        const x = xFor(t).toFixed(1)
        return `<text x="${x}" y="${(padT + innerH + 16).toFixed(1)}" text-anchor="middle" font-size="9" fill="#64748b">${formatXLabel(t)}</text>`
      }).join('')}
      <!-- threshold reference lines -->
      ${warnAt > yMin && warnAt < yMax ? `<line x1="${padL}" y1="${yFor(warnAt).toFixed(1)}" x2="${padL + innerW}" y2="${yFor(warnAt).toFixed(1)}" stroke="#ca8a04" stroke-width="0.7" stroke-dasharray="3,2"/>` : ''}
      ${hotAt > yMin && hotAt < yMax ? `<line x1="${padL}" y1="${yFor(hotAt).toFixed(1)}" x2="${padL + innerW}" y2="${yFor(hotAt).toFixed(1)}" stroke="#dc2626" stroke-width="0.7" stroke-dasharray="3,2"/>` : ''}
      <!-- area + line -->
      <path d="${areaPath}" fill="${lineColor}" fill-opacity="0.12"/>
      <path d="${linePath}" fill="none" stroke="${lineColor}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>
    <div style="font-size:9px;color:#94a3b8;margin-top:4px;">Bands: amber = warn (≥${warnAt}°C), red = critical (≥${hotAt}°C). Sampled every 60s.</div>
  </div>`
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMART Health Report - /dev/${disk.name}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a2e; background: #fff; font-size: 13px; line-height: 1.5; }
  @page { margin: 10mm; size: A4; }

  /* === SCREEN: responsive layout === */
  @media screen {
    body { max-width: 1000px; margin: 0 auto; padding: 24px 32px; padding-top: 64px; overflow-x: hidden; }
  }
  @media screen and (max-width: 640px) {
    body { padding: 16px; padding-top: 64px; }
    .grid-4 { grid-template-columns: 1fr 1fr; }
    .grid-3 { grid-template-columns: 1fr 1fr; }
    .rpt-header { flex-direction: column; gap: 12px; align-items: flex-start; }
    .rpt-header-right { text-align: left; }
    .exec-box { flex-wrap: wrap; }
    .card-c .card-value { font-size: 16px; }
  }

  /* === PRINT: force desktop A4 layout from any device === */
  @media print {
    html, body { margin: 0 !important; padding: 0 !important; width: 100% !important; max-width: none !important; }
    .no-print { display: none !important; }
    .top-bar { display: none !important; }
    .page-break { page-break-before: always; }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    body { font-size: 11px; padding-top: 0 !important; }
    /* Force desktop grid layout regardless of viewport */
    .grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr !important; }
    .grid-3 { grid-template-columns: 1fr 1fr 1fr !important; }
    .grid-2 { grid-template-columns: 1fr 1fr !important; }
    .rpt-header { flex-direction: row !important; align-items: center !important; }
    .rpt-header-right { text-align: right !important; }
    .exec-box { flex-wrap: nowrap !important; }
    .card-c .card-value { font-size: 20px !important; }
    /* Page break control */
    .section { page-break-inside: avoid; break-inside: avoid; margin-bottom: 15px; }
    .exec-box { page-break-inside: avoid; break-inside: avoid; }
    .card { page-break-inside: avoid; break-inside: avoid; }
    .grid-2, .grid-3, .grid-4 { page-break-inside: avoid; break-inside: avoid; }
    .section-title { page-break-after: avoid; break-after: avoid; }
    .attr-tbl tr { page-break-inside: avoid; break-inside: avoid; }
    .attr-tbl thead { display: table-header-group; }
    .rpt-footer { page-break-inside: avoid; break-inside: avoid; margin-top: 20px; }
    svg { max-width: 100%; height: auto; }
    /* Darken light grays for PDF readability */
    .rpt-header-left p, .rpt-header-right { color: #374151; }
    .rpt-header-right .rid { color: #4b5563; }
    .exec-text p { color: #374151; }
    .card-label { color: #4b5563; }
    .rpt-footer { color: #4b5563; }
    [style*="color:#64748b"] { color: #374151 !important; }
    [style*="color:#94a3b8"] { color: #4b5563 !important; }
    [style*="color: #64748b"] { color: #374151 !important; }
    [style*="color: #94a3b8"] { color: #4b5563 !important; }
    [style*="color:#16a34a"], [style*="color: #16a34a"] { color: #16a34a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="color:#dc2626"] { color: #dc2626 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="color:#ca8a04"] { color: #ca8a04 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .health-ring, .card-value, .f-tag { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }

  /* Top bar for screen only */
  .top-bar {
    position: fixed; top: 0; left: 0; right: 0; background: #0f172a; color: #e2e8f0;
    padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; z-index: 100;
    font-size: 13px;
  }
  .top-bar-left { display: flex; align-items: center; gap: 12px; }
  .top-bar-title { font-weight: 600; }
  .top-bar-subtitle { font-size: 11px; color: #94a3b8; }
  .top-bar button {
    background: #06b6d4; color: #fff; border: none; padding: 10px 20px; border-radius: 6px;
    font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .top-bar button:hover { background: #0891b2; }

  /* Header */
  .rpt-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 0; border-bottom: 3px solid #0f172a; margin-bottom: 22px;
  }
  .rpt-header-left { display: flex; align-items: center; gap: 14px; }
  .rpt-header-left img { height: 44px; width: auto; }
  .rpt-header-left h1 { font-size: 22px; font-weight: 700; color: #0f172a; }
  .rpt-header-left p { font-size: 11px; color: #64748b; }
  .rpt-header-right { text-align: right; font-size: 11px; color: #64748b; line-height: 1.6; }
  .rpt-header-right .rid { font-family: monospace; font-size: 10px; color: #94a3b8; }

  /* Sections */
  .section { margin-bottom: 22px; }
  .section-title {
    font-size: 14px; font-weight: 700; color: #0f172a; text-transform: uppercase;
    letter-spacing: 0.05em; padding-bottom: 5px; border-bottom: 2px solid #e2e8f0; margin-bottom: 12px;
  }

  /* Executive summary */
  .exec-box {
    display: flex; align-items: flex-start; gap: 20px; padding: 20px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 16px;
  }
  .health-ring {
    width: 96px; height: 96px; border-radius: 50%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; border: 4px solid; flex-shrink: 0;
  }
  .health-icon { font-size: 32px; line-height: 1; }
  .health-lbl { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; margin-top: 4px; }
  .exec-text { flex: 1; min-width: 200px; }
  .exec-text h3 { font-size: 16px; margin-bottom: 4px; }
  .exec-text p { font-size: 12px; color: #64748b; line-height: 1.5; }

  /* Grids */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .card { padding: 10px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
  .card-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .card-value { font-size: 13px; font-weight: 600; color: #0f172a; }
  .card-c { text-align: center; }
  .card-c .card-value { font-size: 20px; font-weight: 800; }

  /* Tags */
  .f-tag { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }

  /* Tables */
  .attr-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
  .attr-tbl th { text-align: left; padding: 6px 4px; font-size: 10px; color: #64748b; font-weight: 600; border-bottom: 2px solid #e2e8f0; background: #f1f5f9; }
  .attr-tbl td { padding: 5px 4px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
  .attr-tbl tr:hover { background: #f8fafc; }
  .attr-tbl .col-name { word-break: break-word; }
  .attr-tbl .col-raw { font-family: monospace; font-size: 10px; }

  /* Attribute explanation rows: full-width below the data row */
  .attr-explain-row td { padding-top: 0 !important; }
  .attr-explain-row:hover { background: transparent; }

  /* Recommendations */
  .rec-item { display: flex; align-items: flex-start; gap: 12px; padding: 12px; border-radius: 6px; margin-bottom: 8px; }
  .rec-icon { font-size: 18px; flex-shrink: 0; width: 24px; text-align: center; }
  .rec-item strong { display: block; margin-bottom: 2px; }
  .rec-item p { font-size: 12px; color: #64748b; margin: 0; }
  .rec-ok { background: #dcfce7; border: 1px solid #86efac; }
  .rec-ok .rec-icon { color: #16a34a; }
  .rec-warn { background: #fef3c7; border: 1px solid #fcd34d; }
  .rec-warn .rec-icon { color: #ca8a04; }
  .rec-critical { background: #fee2e2; border: 1px solid #fca5a5; }
  .rec-critical .rec-icon { color: #dc2626; }
  .rec-info { background: #e0f2fe; border: 1px solid #7dd3fc; }
  .rec-info .rec-icon { color: #0284c7; }

  /* Footer */
  .rpt-footer {
    margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;
  }

  /* NOTE: No mobile-specific layout overrides — print layout is always A4/desktop
     regardless of the device generating the PDF. The @media print block above
     handles all necessary print adjustments. */
</style>
</head>
<body>

<script>
function pmxPrint(){
  try { window.print(); }
  catch(e) {
    var isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    var el = document.getElementById('pmx-print-hint');
    if(el) el.textContent = isMac ? 'Use Cmd+P to save as PDF' : 'Use Ctrl+P to save as PDF';
  }
}
</script>

<!-- Top bar (screen only) -->
<div class="top-bar no-print">
  <div style="display:flex;align-items:center;gap:12px;">
    <strong>SMART Health Report</strong>
    <span id="pmx-print-hint" style="font-size:11px;opacity:0.7;">/dev/${disk.name}</span>
  </div>
  <button onclick="pmxPrint()">Print / Save as PDF</button>
</div>

<!-- Header -->
<div class="rpt-header">
  <div class="rpt-header-left">
    <img src="${logoUrl}" alt="ProxMenux" onerror="this.style.display='none'">
    <div>
      <h1>SMART Health Report</h1>
      <p>ProxMenux Monitor - Disk Health Analysis</p>
    </div>
  </div>
  <div class="rpt-header-right">
    <div>Date: ${now}</div>
    <div>Device: /dev/${disk.name}</div>
    <div class="rid">ID: ${reportId}</div>
  </div>
</div>

<!-- 1. Executive Summary -->
<div class="section">
  <div class="section-title">1. Executive Summary</div>
  <div class="exec-box">
    <div style="display:flex;flex-direction:column;align-items:center;gap:4px;">
      <div class="health-ring" style="border-color:${healthColor};color:${healthColor}">
        <div class="health-icon">${isHealthy ? '&#10003;' : '&#10007;'}</div>
        <div class="health-lbl">${healthLabel}</div>
      </div>
      <div style="font-size:10px;color:#475569;font-weight:600;">SMART Status</div>
    </div>
    <div class="exec-text">
      <h3>Disk Health Assessment</h3>
      <p>
        ${isHealthy 
          ? `This disk is operating within normal parameters. All SMART attributes are within acceptable thresholds. The disk has been powered on for approximately ${powerOnFormatted} and is currently operating at ${disk.temperature > 0 ? disk.temperature + '°C' : 'N/A'}. ${(disk.reallocated_sectors ?? 0) === 0 ? 'No bad sectors have been detected.' : `${disk.reallocated_sectors} reallocated sector(s) detected - monitor closely.`}`
          : `This disk has reported a SMART health failure. Immediate action is required. Backup all critical data and plan for disk replacement.`
        }
      </p>
    </div>
  </div>
  
  <!-- Simple Explanation for Non-Technical Users -->
  <div style="background:${isHealthy ? '#dcfce7' : (hasCritical ? '#fee2e2' : '#fef3c7')};border:1px solid ${isHealthy ? '#86efac' : (hasCritical ? '#fca5a5' : '#fcd34d')};border-radius:8px;padding:16px;margin-top:12px;">
    <div style="font-weight:700;font-size:14px;color:${isHealthy ? '#166534' : (hasCritical ? '#991b1b' : '#92400e')};margin-bottom:8px;">
      ${isHealthy ? 'What does this mean? Your disk is healthy!' : (hasCritical ? 'ATTENTION REQUIRED: Problems detected' : 'Some issues need monitoring')}
    </div>
    <p style="color:${isHealthy ? '#166534' : (hasCritical ? '#991b1b' : '#92400e')};font-size:12px;margin:0 0 8px 0;">
      ${isHealthy 
        ? 'In simple terms: This disk is working properly. You can continue using it normally. We recommend running periodic SMART tests (monthly) to catch any issues early.'
        : (hasCritical 
          ? 'In simple terms: This disk has problems that could cause data loss. You should back up your important files immediately and consider replacing the disk soon.'
          : 'In simple terms: The disk is working but shows some signs of wear. It is not critical yet, but you should monitor it closely and ensure your backups are up to date.'
        )
      }
    </p>
    ${!isHealthy && criticalAttrs.length > 0 ? `
    <div style="margin-top:8px;padding-top:8px;border-top:1px solid ${hasCritical ? '#fca5a5' : '#fcd34d'};">
      <div style="font-size:11px;font-weight:600;color:#475569;margin-bottom:4px;">Issues found:</div>
      <ul style="margin:0;padding-left:20px;font-size:11px;color:${hasCritical ? '#991b1b' : '#92400e'};">
        ${criticalAttrs.slice(0, 3).map(a => `<li>${a.name.replace(/_/g, ' ')}: ${a.status === 'critical' ? 'Critical - requires immediate attention' : 'Warning - should be monitored'}</li>`).join('')}
        ${criticalAttrs.length > 3 ? `<li>...and ${criticalAttrs.length - 3} more issues (see details below)</li>` : ''}
      </ul>
    </div>
    ` : ''}
  </div>
  
  <!-- Test Information -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));gap:8px;margin-top:12px;">
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 12px;">
      <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;">Report Generated</div>
      <div style="font-size:12px;font-weight:600;color:#1e293b;">${now}</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 12px;">
      <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;">${isHistorical ? 'Test Type' : 'Last Test Type'}</div>
      <div style="font-size:12px;font-weight:600;color:#1e293b;">${testStatus.last_test?.type || 'N/A'}</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 12px;">
      <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;">Test Result</div>
      <div style="font-size:12px;font-weight:600;color:${testStatus.last_test?.status?.toLowerCase() === 'passed' ? '#16a34a' : testStatus.last_test?.status?.toLowerCase() === 'failed' ? '#dc2626' : '#64748b'};">${testStatus.last_test?.status || 'N/A'}</div>
    </div>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 12px;">
      <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;">Attributes Checked</div>
      <div style="font-size:12px;font-weight:600;color:#1e293b;">${smartAttributes.length}</div>
    </div>
  </div>
  ${testAgeWarning ? `
  <div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:12px 16px;margin-top:12px;display:flex;align-items:flex-start;gap:10px;">
    <span style="font-size:18px;flex-shrink:0;">&#9888;</span>
    <div>
      <div style="font-weight:700;font-size:12px;color:#92400e;margin-bottom:4px;">Outdated Test Data (${testAgeDays} days old)</div>
      <p style="font-size:11px;color:#92400e;margin:0;">${testAgeWarning}</p>
    </div>
  </div>
  ` : ''}
</div>

<!-- 2. Disk Information -->
<div class="section">
  <div class="section-title">2. Disk Information</div>
  <div class="grid-4">
    <div class="card">
      <div class="card-label">Model</div>
      <div class="card-value" style="font-size:11px;">${disk.model || sd?.model || 'Unknown'}</div>
    </div>
    <div class="card">
      <div class="card-label">Serial</div>
      <div class="card-value" style="font-size:11px;font-family:monospace;">${disk.serial || sd?.serial || 'Unknown'}</div>
    </div>
    <div class="card">
      <div class="card-label">Capacity</div>
      <div class="card-value" style="font-size:11px;">${disk.size_formatted || 'Unknown'}</div>
    </div>
    <div class="card">
      <div class="card-label">Type</div>
      <div class="card-value" style="font-size:11px;">${diskType === 'SAS' ? (disk.rotation_rate ? `SAS ${disk.rotation_rate} RPM` : 'SAS SSD') : diskType === 'HDD' && disk.rotation_rate ? `HDD ${disk.rotation_rate} RPM` : diskType}</div>
    </div>
  </div>
  ${(modelFamily || formFactor || sataVersion || ifaceSpeed) ? `
  <div class="grid-4" style="margin-top:8px;">
    ${modelFamily ? `<div class="card"><div class="card-label">Family</div><div class="card-value" style="font-size:11px;">${modelFamily}</div></div>` : ''}
    ${formFactor ? `<div class="card"><div class="card-label">Form Factor</div><div class="card-value" style="font-size:11px;">${formFactor}</div></div>` : ''}
    ${sataVersion ? `<div class="card"><div class="card-label">Interface</div><div class="card-value" style="font-size:11px;">${sataVersion}${ifaceSpeed ? ` · ${ifaceSpeed}` : ''}</div></div>` : (ifaceSpeed ? `<div class="card"><div class="card-label">${isSasDisk ? 'Transport' : 'Link Speed'}</div><div class="card-value" style="font-size:11px;">${ifaceSpeed}</div></div>` : '')}
    ${!isNvmeDisk && !isSasDisk ? `<div class="card"><div class="card-label">TRIM</div><div class="card-value" style="font-size:11px;color:${trimSupported ? '#16a34a' : '#94a3b8'};">${trimSupported ? 'Supported' : 'Not supported'}${physBlockSize === 4096 ? ' · 4K AF' : ''}</div></div>` : ''}
    ${isSasDisk && sd?.logical_block_size ? `<div class="card"><div class="card-label">Block Size</div><div class="card-value" style="font-size:11px;">${sd.logical_block_size} bytes</div></div>` : ''}
  </div>
  ` : ''}
  <div class="grid-4">
    <div class="card card-c">
      <div class="card-value" style="color:${getTempColorForReport(disk.temperature)}">${disk.temperature > 0 ? disk.temperature + '°C' : 'N/A'}</div>
      <div class="card-label">Temperature</div>
      <div style="font-size:9px;color:#475569;margin-top:2px;">Optimal: ${tempThresholds.optimal}</div>
    </div>
    <div class="card card-c">
      <div class="card-value">${fmtNum(powerOnHours)}h</div>
      <div class="card-label">Power On Time</div>
      <div style="font-size:9px;color:#475569;margin-top:2px;">${powerOnYears}y ${powerOnRemainingDays}d</div>
    </div>
    <div class="card card-c">
      <div class="card-value">${fmtNum(disk.power_cycles ?? 0)}</div>
      <div class="card-label">Power Cycles</div>
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:${disk.smart_status?.toLowerCase() === 'passed' ? '#16a34a' : (disk.smart_status?.toLowerCase() === 'failed' ? '#dc2626' : '#64748b')}">${disk.smart_status || 'N/A'}</div>
      <div class="card-label">SMART Status</div>
    </div>
  </div>
  ${!isNvmeDisk ? `
  <div class="grid-3" style="margin-top:8px;">
    <div class="card card-c">
      <div class="card-value" style="color:${(disk.pending_sectors ?? 0) > 0 ? '#dc2626' : '#16a34a'}">${disk.pending_sectors ?? 0}</div>
      <div class="card-label">${isSasDisk ? 'Uncorrected Errors' : 'Pending Sectors'}</div>
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:${isSasDisk ? '#94a3b8' : (disk.crc_errors ?? 0) > 0 ? '#ca8a04' : '#16a34a'}">${isSasDisk ? 'N/A' : (disk.crc_errors ?? 0)}</div>
      <div class="card-label">CRC Errors</div>
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:${(disk.reallocated_sectors ?? 0) > 0 ? '#dc2626' : '#16a34a'}">${disk.reallocated_sectors ?? 0}</div>
      <div class="card-label">${isSasDisk ? 'Grown Defects' : 'Reallocated Sectors'}</div>
    </div>
  </div>
  ` : ''}
  ${temperatureChartHtml}
</div>



${isNvmeDisk && hasNvmeWearData ? `
<!-- NVMe Wear & Lifetime (Special Section) -->
<div class="section">
  <div class="section-title">3. NVMe Wear & Lifetime</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
    <!-- Life Remaining Gauge -->
    <div style="background:linear-gradient(135deg,#f8fafc 0%,#f1f5f9 100%);border:1px solid #e2e8f0;border-radius:12px;padding:20px;text-align:center;">
      <div style="font-size:12px;color:#475569;margin-bottom:8px;font-weight:600;">LIFE REMAINING</div>
      <div style="position:relative;width:120px;height:120px;margin:0 auto;">
        <svg viewBox="0 0 120 120" style="transform:rotate(-90deg);">
          <circle cx="60" cy="60" r="50" fill="none" stroke="#e2e8f0" stroke-width="12"/>
          <circle cx="60" cy="60" r="50" fill="none" stroke="${getLifeColorHex(nvmePercentUsed)}" stroke-width="12" 
            stroke-dasharray="${(100 - nvmePercentUsed) * 3.14} 314" stroke-linecap="round"/>
        </svg>
        <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;">
          <div style="font-size:28px;font-weight:700;color:${getLifeColorHex(nvmePercentUsed)};">${100 - nvmePercentUsed}%</div>
        </div>
      </div>
      <div style="margin-top:12px;font-size:13px;color:#475569;">Estimated: <strong>${nvmeEstimatedLife}</strong></div>
    </div>
    
    <!-- Usage Statistics -->
    <div style="background:linear-gradient(135deg,#f8fafc 0%,#f1f5f9 100%);border:1px solid #e2e8f0;border-radius:12px;padding:20px;">
      <div style="font-size:12px;color:#475569;margin-bottom:12px;font-weight:600;">USAGE STATISTICS</div>
      
      <div style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
          <span style="font-size:12px;color:#475569;">Percentage Used</span>
          <span style="font-size:14px;font-weight:600;color:#3b82f6;">${nvmePercentUsed}%</span>
        </div>
        <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;">
          <div style="background:#3b82f6;height:100%;width:${Math.min(nvmePercentUsed, 100)}%;border-radius:4px;"></div>
        </div>
      </div>
      
      <div style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
          <span style="font-size:12px;color:#475569;">Available Spare</span>
          <span style="font-size:14px;font-weight:600;color:${nvmeAvailSpare >= 50 ? '#16a34a' : nvmeAvailSpare >= 20 ? '#ca8a04' : '#dc2626'};">${nvmeAvailSpare}%</span>
        </div>
        <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;">
          <div style="background:${nvmeAvailSpare >= 50 ? '#16a34a' : nvmeAvailSpare >= 20 ? '#ca8a04' : '#dc2626'};height:100%;width:${nvmeAvailSpare}%;border-radius:4px;"></div>
        </div>
      </div>
      
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;padding-top:12px;border-top:1px solid #e2e8f0;">
        <div>
          <div style="font-size:11px;color:#475569;">Data Written</div>
          <div style="font-size:15px;font-weight:600;color:#1e293b;">${nvmeDataWrittenTB >= 1 ? nvmeDataWrittenTB.toFixed(2) + ' TB' : (nvmeDataWrittenTB * 1024).toFixed(1) + ' GB'}</div>
        </div>
        <div>
          <div style="font-size:11px;color:#475569;">Power Cycles</div>
          <div style="font-size:15px;font-weight:600;color:#1e293b;">${testStatus.smart_data?.nvme_raw?.power_cycles != null ? fmtNum(testStatus.smart_data.nvme_raw.power_cycles) : (disk.power_cycles ? fmtNum(disk.power_cycles) : 'N/A')}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- NVMe Extended Health Metrics -->
  ${(() => {
    const nr = testStatus.smart_data?.nvme_raw
    if (!nr) return ''
    const mediaErr = nr.media_errors ?? 0
    const unsafeSd = nr.unsafe_shutdowns ?? 0
    const critWarn = nr.critical_warning ?? 0
    const warnTempMin = nr.warning_temp_time ?? 0
    const critTempMin = nr.critical_comp_time ?? 0
    const ctrlBusy = nr.controller_busy_time ?? 0
    const errLog = nr.num_err_log_entries ?? 0
    const dataReadTB = ((nr.data_units_read ?? 0) * 512 * 1024) / (1024 ** 4)
    const hostReads = nr.host_read_commands ?? 0
    const hostWrites = nr.host_write_commands ?? 0
    const endGrpWarn = nr.endurance_grp_critical_warning_summary ?? 0
    const sensors = (nr.temperature_sensors ?? []).filter((s: number | null) => s !== null) as number[]

    const metricCard = (label: string, value: string, colorHex: string, note?: string) =>
      `<div class="card"><div class="card-label">${label}</div><div class="card-value" style="font-size:12px;color:${colorHex};">${value}</div>${note ? `<div style="font-size:9px;color:#64748b;margin-top:2px;">${note}</div>` : ''}</div>`

    return `
    <div style="margin-top:16px;padding-top:16px;border-top:1px solid #e2e8f0;">
      <div style="font-size:11px;font-weight:600;color:#475569;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:10px;">Extended NVMe Health</div>
      <div class="grid-4">
        ${metricCard('Critical Warning', critWarn === 0 ? 'None' : `0x${critWarn.toString(16).toUpperCase()}`, critWarn === 0 ? '#16a34a' : '#dc2626', 'Controller alert flags')}
        ${metricCard('Media Errors', fmtNum(mediaErr), mediaErr === 0 ? '#16a34a' : '#dc2626', 'Flash cell damage')}
        ${metricCard('Unsafe Shutdowns', fmtNum(unsafeSd), unsafeSd < 50 ? '#16a34a' : unsafeSd < 200 ? '#ca8a04' : '#dc2626', 'Power loss without flush')}
        ${metricCard('Endurance Warning', endGrpWarn === 0 ? 'None' : `0x${endGrpWarn.toString(16).toUpperCase()}`, endGrpWarn === 0 ? '#16a34a' : '#ca8a04', 'Group endurance alert')}
      </div>
      <div class="grid-4" style="margin-top:8px;">
        ${metricCard('Controller Busy', `${fmtNum(ctrlBusy)} min`, '#1e293b', 'Total busy time')}
        ${metricCard('Error Log Entries', fmtNum(errLog), errLog === 0 ? '#16a34a' : '#ca8a04', 'May include benign artifacts')}
        ${metricCard('Warning Temp Time', `${fmtNum(warnTempMin)} min`, warnTempMin === 0 ? '#16a34a' : '#ca8a04', 'Minutes in warning range')}
        ${metricCard('Critical Temp Time', `${fmtNum(critTempMin)} min`, critTempMin === 0 ? '#16a34a' : '#dc2626', 'Minutes in critical range')}
      </div>
      <div class="grid-4" style="margin-top:8px;">
        ${metricCard('Data Read', dataReadTB >= 1 ? dataReadTB.toFixed(2) + ' TB' : (dataReadTB * 1024).toFixed(1) + ' GB', '#1e293b', 'Total host reads')}
        ${metricCard('Host Read Cmds', fmtNum(hostReads), '#1e293b', 'Total read commands')}
        ${metricCard('Host Write Cmds', fmtNum(hostWrites), '#1e293b', 'Total write commands')}
        ${sensors.length >= 2 ? metricCard('Hotspot Temp', `${sensors[1]}°C`, sensors[1] > 80 ? '#dc2626' : sensors[1] > 70 ? '#ca8a04' : '#16a34a', 'Sensor[1] hotspot') : '<div class="card"><div class="card-label">Sensors</div><div class="card-value" style="font-size:11px;color:#94a3b8;">N/A</div></div>'}
      </div>
    </div>`
  })()}
</div>
` : ''}

${isNvmeDisk && !hasNvmeWearData ? (() => {
  // Fallback for NVMe drives whose firmware does not tick percent_used
  // (e.g. WD CL SN720). Skip the misleading "100% Life Remaining /
  // Excellent" gauge and only print the data we trust: total written.
  const dwUnits = testStatus.smart_data?.nvme_raw?.data_units_written ?? 0
  if (!dwUnits) return ''
  const dwTB = (dwUnits * 512 * 1024) / (1024 ** 4)
  const dwLabel = dwTB >= 1 ? dwTB.toFixed(2) + ' TB' : (dwTB * 1024).toFixed(1) + ' GB'
  const pCycles = testStatus.smart_data?.nvme_raw?.power_cycles ?? disk.power_cycles ?? null
  return `
<!-- NVMe wear-not-reported fallback -->
<div class="section">
  <div class="section-title">3. NVMe Wear &amp; Lifetime</div>
  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div>
        <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Data Written</div>
        <div style="font-size:18px;font-weight:700;color:#1e293b;margin-top:4px;">${dwLabel}</div>
      </div>
      ${pCycles !== null ? `<div>
        <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Power Cycles</div>
        <div style="font-size:18px;font-weight:700;color:#1e293b;margin-top:4px;">${fmtNum(pCycles as number)}</div>
      </div>` : ''}
    </div>
  </div>
</div>
`
})() : ''}

${!isNvmeDisk && diskType === 'SSD' ? (() => {
  // Try to find SSD wear indicators from SMART attributes
  const wearAttr = smartAttributes.find(a => 
    a.name?.toLowerCase().includes('wear_leveling') ||
    a.name?.toLowerCase().includes('media_wearout') ||
    a.name?.toLowerCase().includes('percent_lifetime') ||
    a.name?.toLowerCase().includes('ssd_life_left') ||
    a.id === 177 || a.id === 231 || a.id === 233
  )
  
  const lbasWrittenAttr = smartAttributes.find(a => 
    a.name?.toLowerCase().includes('total_lbas_written') ||
    a.id === 241
  )
  
  // Also check disk properties — cast to number since SmartAttribute.value is number | string
  const wearRaw = (wearAttr?.value !== undefined ? Number(wearAttr.value) : undefined) ?? disk.wear_leveling_count ?? disk.ssd_life_left

  if (wearRaw !== undefined && wearRaw !== null) {
    // ID 230 (Media_Wearout_Indicator on WD/SanDisk): value = endurance used %
    // All others (ID 177, 231, etc.): value = life remaining %
    const lifeRemaining = (wearAttr?.id === 230) ? (100 - wearRaw) : wearRaw
    const lifeUsed = 100 - lifeRemaining
    
    // Calculate data written — detect unit from attribute name
    let dataWrittenTB = 0
    if (lbasWrittenAttr?.raw_value) {
      const rawValue = parseInt(lbasWrittenAttr.raw_value.replace(/[^0-9]/g, ''))
      if (!isNaN(rawValue)) {
        const attrName = (lbasWrittenAttr.name || '').toLowerCase()
        if (attrName.includes('gib') || attrName.includes('_gb')) {
          // Raw value already in GiB (WD Blue, Kingston, etc.)
          dataWrittenTB = rawValue / 1024
        } else {
          // Raw value in LBAs — multiply by 512 bytes (Seagate, standard)
          dataWrittenTB = (rawValue * 512) / (1024 ** 4)
        }
      }
    } else if (disk.total_lbas_written) {
      dataWrittenTB = disk.total_lbas_written / 1024 // Already in GB from backend
    }
    
    return `
<!-- SSD Wear & Lifetime -->
<div class="section">
  <div class="section-title">3. SSD Wear & Lifetime</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
    <!-- Life Remaining Gauge -->
    <div style="background:linear-gradient(135deg,#f8fafc 0%,#f1f5f9 100%);border:1px solid #e2e8f0;border-radius:12px;padding:20px;text-align:center;">
      <div style="font-size:12px;color:#475569;margin-bottom:8px;font-weight:600;">LIFE REMAINING</div>
      <div style="position:relative;width:120px;height:120px;margin:0 auto;">
        <svg viewBox="0 0 120 120" style="transform:rotate(-90deg);">
          <circle cx="60" cy="60" r="50" fill="none" stroke="#e2e8f0" stroke-width="12"/>
          <circle cx="60" cy="60" r="50" fill="none" stroke="${getLifeColorHex(lifeUsed)}" stroke-width="12" 
            stroke-dasharray="${lifeRemaining * 3.14} 314" stroke-linecap="round"/>
        </svg>
        <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;">
          <div style="font-size:28px;font-weight:700;color:${getLifeColorHex(lifeUsed)};">${lifeRemaining}%</div>
        </div>
      </div>
      <div style="margin-top:12px;font-size:11px;color:#475569;">
        Source: ${wearAttr?.name?.replace(/_/g, ' ') || 'SSD Life Indicator'}
      </div>
    </div>
    
    <!-- Usage Statistics -->
    <div style="background:linear-gradient(135deg,#f8fafc 0%,#f1f5f9 100%);border:1px solid #e2e8f0;border-radius:12px;padding:20px;">
      <div style="font-size:12px;color:#475569;margin-bottom:12px;font-weight:600;">USAGE STATISTICS</div>
      
      <div style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
          <span style="font-size:12px;color:#475569;">Wear Level</span>
          <span style="font-size:14px;font-weight:600;color:#3b82f6;">${lifeUsed}%</span>
        </div>
        <div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;">
          <div style="background:#3b82f6;height:100%;width:${Math.min(lifeUsed, 100)}%;border-radius:4px;"></div>
        </div>
      </div>
      
      ${dataWrittenTB > 0 ? `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;padding-top:12px;border-top:1px solid #e2e8f0;">
        <div>
          <div style="font-size:11px;color:#475569;">Data Written</div>
          <div style="font-size:15px;font-weight:600;color:#1e293b;">${dataWrittenTB >= 1 ? dataWrittenTB.toFixed(2) + ' TB' : (dataWrittenTB * 1024).toFixed(1) + ' GB'}</div>
        </div>
        <div>
          <div style="font-size:11px;color:#475569;">Power On Hours</div>
          <div style="font-size:15px;font-weight:600;color:#1e293b;">${fmtNum(powerOnHours)}h</div>
        </div>
      </div>
      ` : ''}
      
      <div style="margin-top:12px;padding:8px;background:#f1f5f9;border-radius:6px;font-size:11px;color:#475569;">
        <strong>Note:</strong> SSD life estimates are based on manufacturer-reported wear indicators. 
        Actual lifespan may vary based on workload and usage patterns.
      </div>
    </div>
  </div>
</div>
`
  }
  return ''
})() : ''}

<!-- SMART Attributes / NVMe Health Metrics / SAS Error Counters -->
<div class="section">
  <div class="section-title">${isNvmeDisk ? '4' : (diskType === 'SSD' && (disk.wear_leveling_count !== undefined || disk.ssd_life_left !== undefined || smartAttributes.some(a => a.name?.toLowerCase().includes('wear'))) ? '4' : '3')}. ${isNvmeDisk ? 'NVMe Health Metrics' : isSasDisk ? 'SAS/SCSI Health Metrics' : 'SMART Attributes'} (${smartAttributes.length} total${hasCritical ? `, ${criticalAttrs.length} warning(s)` : ''})</div>
  <table class="attr-tbl">
    <thead>
      <tr>
        ${useSimpleTable ? '' : '<th style="width:28px;">ID</th>'}
        <th class="col-name">${isNvmeDisk ? 'Metric' : isSasDisk ? 'Metric' : 'Attribute'}</th>
        <th style="text-align:center;width:${useSimpleTable ? '80px' : '40px'};">Value</th>
        ${useSimpleTable ? '' : '<th style="text-align:center;width:40px;">Worst</th>'}
        ${useSimpleTable ? '' : '<th style="text-align:center;width:40px;">Thr</th>'}
        ${useSimpleTable ? '' : '<th class="col-raw" style="width:60px;">Raw</th>'}
        <th style="width:36px;"></th>
      </tr>
    </thead>
    <tbody>
      ${attributeRows || '<tr><td colspan="' + (useSimpleTable ? '3' : '7') + '" style="text-align:center;color:#64748b;padding:20px;">No ' + (isNvmeDisk ? 'NVMe metrics' : isSasDisk ? 'SAS metrics' : 'SMART attributes') + ' available</td></tr>'}
    </tbody>
  </table>
</div>
  
  <!-- 5. Last Test Result -->
<div class="section">
  <div class="section-title">${isNvmeDisk ? '5' : '4'}. ${isHistorical ? 'Self-Test Result' : 'Last Self-Test Result'}</div>
  ${testStatus.last_test ? `
    <div class="grid-4">
      <div class="card">
        <div class="card-label">Test Type</div>
        <div class="card-value" style="text-transform:capitalize;">${testStatus.last_test.type}</div>
      </div>
      <div class="card">
        <div class="card-label">Result</div>
        <div class="card-value" style="color:${testStatus.last_test.status === 'passed' ? '#16a34a' : '#dc2626'};text-transform:capitalize;">${testStatus.last_test.status}</div>
      </div>
      <div class="card">
        <div class="card-label">Completed</div>
        <div class="card-value" style="font-size:11px;">${testStatus.last_test.timestamp || 'N/A'}</div>
      </div>
      <div class="card">
        <div class="card-label">At Power-On Hours</div>
        <div class="card-value">${testStatus.last_test.lifetime_hours ? fmtNum(testStatus.last_test.lifetime_hours) + 'h' : 'N/A'}</div>
      </div>
    </div>
    ${(pollingShort || pollingExt) ? `
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
      ${pollingShort ? `<div style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:6px 12px;font-size:11px;color:#475569;"><strong>Short test:</strong> ~${pollingShort} min</div>` : ''}
      ${pollingExt ? `<div style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:6px 12px;font-size:11px;color:#475569;"><strong>Extended test:</strong> ~${pollingExt} min</div>` : ''}
      ${errorLogCount > 0 ? `<div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:6px 12px;font-size:11px;color:#92400e;"><strong>ATA error log:</strong> ${errorLogCount} entr${errorLogCount === 1 ? 'y' : 'ies'}</div>` : ''}
    </div>` : ''}
    ${selfTestHistory.length > 1 ? `
    <div style="margin-top:14px;">
      <div style="font-size:11px;font-weight:600;color:#475569;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">Full Self-Test History (${selfTestHistory.length} entries)</div>
      <table class="attr-tbl">
        <thead>
          <tr>
            <th>#</th>
            <th>Type</th>
            <th>Status</th>
            <th>At POH</th>
          </tr>
        </thead>
        <tbody>
          ${selfTestHistory.map((e, i) => `
          <tr>
            <td style="color:#94a3b8;">${i + 1}</td>
            <td style="text-transform:capitalize;">${e.type_str || e.type}</td>
            <td><span class="f-tag" style="background:${e.status === 'passed' ? '#16a34a15' : '#dc262615'};color:${e.status === 'passed' ? '#16a34a' : '#dc2626'};">${e.status_str || e.status}</span></td>
            <td style="font-family:monospace;">${e.lifetime_hours != null ? fmtNum(e.lifetime_hours) + 'h' : 'N/A'}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>` : ''}
  ` : lastTestDate ? `
    <div class="grid-4">
      <div class="card">
        <div class="card-label">${isHistorical ? 'Test Type' : 'Last Test Type'}</div>
        <div class="card-value" style="text-transform:capitalize;">${testStatus.test_type || 'Extended'}</div>
      </div>
      <div class="card">
        <div class="card-label">Result</div>
        <div class="card-value" style="color:#16a34a;">Passed</div>
      </div>
      <div class="card">
        <div class="card-label">Date</div>
        <div class="card-value" style="font-size:11px;">${new Date(lastTestDate).toLocaleString()}</div>
      </div>
      <div class="card">
        <div class="card-label">At Power-On Hours</div>
        <div class="card-value">${fmtNum(powerOnHours)}h</div>
      </div>
    </div>
    <div style="margin-top:8px;padding:8px 12px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;font-size:11px;color:#475569;">
      <strong>Note:</strong> This disk's firmware does not maintain an internal self-test log. Test results are tracked by ProxMenux Monitor.
    </div>
  ` : `
    <div style="text-align:center;padding:20px;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;">
      No self-test history available. Run a SMART self-test to see results here.
    </div>
  `}
</div>

${observationsHtml}

<!-- Recommendations -->
<div class="section">
  <div class="section-title">${observations.length > 0 ? (isNvmeDisk ? '7' : '6') : (isNvmeDisk ? '6' : '5')}. Recommendations</div>
  ${recommendations.join('')}
</div>
  
  <!-- Footer -->
<div class="rpt-footer">
  <div>Report generated by ProxMenux Monitor</div>
  <div>ProxMenux Monitor v1.2.2</div>
</div>

</body>
</html>`

  const blob = new Blob([html], { type: "text/html" })
  const url = URL.createObjectURL(blob)
  if (targetWindow && !targetWindow.closed) {
    // Navigate the already-open window to the blob URL (proper navigation with back/close in webapp)
    targetWindow.location.href = url
  } else {
    window.open(url, "_blank")
  }
}

// SMART Test Tab Component
interface SmartTestTabProps {
  disk: DiskInfo
  observations?: DiskObservation[]
  lastTestDate?: string
}

interface SmartSelfTestEntry {
  type: 'short' | 'long' | 'other'
  type_str: string
  status: 'passed' | 'failed'
  status_str: string
  lifetime_hours: number | null
}

interface SmartAttribute {
  id: number
  name: string
  value: number | string
  worst: number | string
  threshold: number | string
  raw_value: string
  status: 'ok' | 'warning' | 'critical'
  prefailure?: boolean
  flags?: string
}

interface NvmeRaw {
  critical_warning: number
  temperature: number
  avail_spare: number
  spare_thresh: number
  percent_used: number
  endurance_grp_critical_warning_summary: number
  data_units_read: number
  data_units_written: number
  host_read_commands: number
  host_write_commands: number
  controller_busy_time: number
  power_cycles: number
  power_on_hours: number
  unsafe_shutdowns: number
  media_errors: number
  num_err_log_entries: number
  warning_temp_time: number
  critical_comp_time: number
  temperature_sensors: (number | null)[]
}

interface SmartTestStatus {
  status: 'idle' | 'running' | 'completed' | 'failed'
  test_type?: string
  progress?: number
  result?: string
  supports_progress_reporting?: boolean
  supports_self_test?: boolean
  last_test?: {
    type: string
    status: string
    timestamp: string
    duration?: string
    lifetime_hours?: number
  }
  smart_data?: {
    device: string
    model: string
    model_family?: string
    serial: string
    firmware: string
    nvme_version?: string
    smart_status: string
    temperature: number
    temperature_sensors?: (number | null)[]
    power_on_hours: number
    power_cycles?: number
    rotation_rate?: number
    form_factor?: string
    physical_block_size?: number
    trim_supported?: boolean
    sata_version?: string
    interface_speed?: string
    polling_minutes_short?: number
    polling_minutes_extended?: number
    supports_progress_reporting?: boolean
    error_log_count?: number
    self_test_history?: SmartSelfTestEntry[]
    attributes: SmartAttribute[]
    nvme_raw?: NvmeRaw
    is_sas?: boolean
    logical_block_size?: number
  }
  tools_installed?: {
    smartctl: boolean
    nvme: boolean
  }
}

function SmartTestTab({ disk, observations = [], lastTestDate }: SmartTestTabProps) {
  const [testStatus, setTestStatus] = useState<SmartTestStatus>({ status: 'idle' })
  const [loading, setLoading] = useState(true)
  const [runningTest, setRunningTest] = useState<'short' | 'long' | null>(null)
  
  // Extract SMART attributes from testStatus for the report
  const smartAttributes = testStatus.smart_data?.attributes || []
  
  const fetchSmartStatus = async () => {
  try {
  setLoading(true)
  const data = await fetchApi<SmartTestStatus>(`/api/storage/smart/${disk.name}`)
  setTestStatus(data)
  return data
  } catch {
  setTestStatus({ status: 'idle' })
  return { status: 'idle' }
  } finally {
  setLoading(false)
  }
  }
  
  // Fetch current SMART status on mount and start polling if test is running
  useEffect(() => {
  let pollInterval: NodeJS.Timeout | null = null
  
  const checkAndPoll = async () => {
  const data = await fetchSmartStatus()
  // If a test is already running, start polling
  if (data.status === 'running') {
  pollInterval = setInterval(async () => {
  try {
    const status = await fetchApi<SmartTestStatus>(`/api/storage/smart/${disk.name}`)
    setTestStatus(status)
    if (status.status !== 'running' && pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  } catch {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }
  }, 5000)
  }
  }
  
  checkAndPoll()
  
  return () => {
  if (pollInterval) clearInterval(pollInterval)
  }
  }, [disk.name])
  
  const [testError, setTestError] = useState<string | null>(null)
  const [installing, setInstalling] = useState(false)
  
  // Check if required tools are installed for this disk type
  const isNvme = disk.name.includes('nvme')
  const toolsAvailable = testStatus.tools_installed 
    ? (isNvme ? testStatus.tools_installed.nvme : testStatus.tools_installed.smartctl)
    : true // Assume true until we get the status
  
  const installSmartTools = async () => {
    try {
      setInstalling(true)
      setTestError(null)
      const data = await fetchApi<{ success: boolean; error?: string }>('/api/storage/smart/tools/install', {
        method: 'POST',
        body: JSON.stringify({ install_all: true })
      })
      if (data.success) {
        fetchSmartStatus()
      } else {
        setTestError(data.error || 'Installation failed. Try manually: apt-get install smartmontools nvme-cli')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to install tools'
      setTestError(`${message}. Try manually: apt-get install smartmontools nvme-cli`)
    } finally {
      setInstalling(false)
    }
  }
  
  const runSmartTest = async (testType: 'short' | 'long') => {
    try {
      setRunningTest(testType)
      setTestError(null)
      
      await fetchApi(`/api/storage/smart/${disk.name}/test`, {
        method: 'POST',
        body: JSON.stringify({ test_type: testType })
      })
      
      // Immediately fetch status to show progress bar
      fetchSmartStatus()
      
      // Poll for status updates
      // For disks that don't report progress, we keep polling but show an indeterminate progress bar
      let pollCount = 0
      const maxPolls = testType === 'short' ? 36 : 720 // 3 min for short, 1 hour for long (at 5s intervals)
      
      const pollInterval = setInterval(async () => {
        pollCount++
        try {
          const statusData = await fetchApi<SmartTestStatus>(`/api/storage/smart/${disk.name}`)
          setTestStatus(statusData)
          
          // Only clear runningTest when we get a definitive "not running" status
          if (statusData.status !== 'running') {
            clearInterval(pollInterval)
            setRunningTest(null)
            // Refresh SMART JSON data to get new test results
            fetchSmartStatus()
          }
        } catch {
          // Don't clear on error - keep showing progress
        }
        
        // Safety timeout: stop polling after max duration
        if (pollCount >= maxPolls) {
          clearInterval(pollInterval)
          setRunningTest(null)
          // Refresh status one more time to get final result
          fetchSmartStatus()
        }
      }, 5000)
      
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to start test'
      setTestError(message)
      setRunningTest(null)
    }
  }
  
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Loading SMART data...</p>
      </div>
    )
  }
  
  // If tools not available, show install button only
  if (!toolsAvailable && !loading) {
    return (
      <div className="space-y-6">
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-4 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="font-medium text-amber-500">SMART Tools Not Installed</p>
              <p className="text-sm text-muted-foreground mt-1">
                {isNvme 
                  ? 'nvme-cli is required to run SMART tests on NVMe disks.'
                  : 'smartmontools is required to run SMART tests on this disk.'}
              </p>
            </div>
          </div>
          
          <Button
            onClick={installSmartTools}
            disabled={installing}
            className="w-full gap-2 bg-[#4A9BA8] hover:bg-[#3d8591] text-white border-0"
          >
            {installing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {installing ? 'Installing SMART Tools...' : 'Install SMART Tools'}
          </Button>
          
          {testError && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400">
              <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium">Installation Failed</p>
                <p className="text-xs opacity-80">{testError}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }
  
  return (
    <div className="space-y-6">
      {/* Quick Actions */}
      <div className="space-y-3">
        <h4 className="font-semibold flex items-center gap-2">
          <Play className="h-4 w-4" />
          Run SMART Test
        </h4>
        
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => runSmartTest('short')}
            disabled={runningTest !== null || testStatus.status === 'running'}
            className="gap-2 bg-blue-500/10 border-blue-500/30 text-blue-500 hover:bg-blue-500/20 hover:text-blue-400"
          >
            {runningTest === 'short' || (testStatus.status === 'running' && testStatus.test_type === 'short') ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Activity className="h-4 w-4" />
            )}
            Short Test (~2 min)
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => runSmartTest('long')}
            disabled={runningTest !== null || testStatus.status === 'running'}
            className="gap-2 bg-blue-500/10 border-blue-500/30 text-blue-500 hover:bg-blue-500/20 hover:text-blue-400"
          >
            {runningTest === 'long' || (testStatus.status === 'running' && testStatus.test_type === 'long') ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Activity className="h-4 w-4" />
            )}
            Extended Test (background)
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Short test takes ~2 minutes. Extended test runs in the background and can take several hours for large disks.
          You will receive a notification when the test completes.
        </p>
        
        {/* Error Message */}
        {testError && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400">
            <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-medium">Failed to start test</p>
              <p className="text-xs opacity-80">{testError}</p>
            </div>
          </div>
        )}
      </div>
      
      {/* Test Progress - Show when API reports running OR when we just started a test */}
      {(testStatus.status === 'running' || runningTest !== null) && (
        <div className="border rounded-lg p-4 bg-blue-500/5 border-blue-500/20">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
            <div className="flex-1">
              <p className="font-medium text-blue-500">
                {(runningTest || testStatus.test_type) === 'short' ? 'Short' : 'Extended'} test in progress
              </p>
              <p className="text-xs text-muted-foreground">
                Please wait while the test completes. Buttons will unlock when it finishes.
              </p>
            </div>
          </div>
          {/* Progress bar if disk reports percentage */}
          {testStatus.progress !== undefined ? (
            <Progress value={testStatus.progress} className="h-2 mt-3 [&>div]:bg-blue-500" />
          ) : (
            <>
              <div className="h-2 mt-3 rounded-full bg-blue-500/20 overflow-hidden">
                <div className="h-full w-1/3 bg-blue-500 rounded-full animate-[indeterminate_1.5s_ease-in-out_infinite]"
                  style={{ animation: 'indeterminate 1.5s ease-in-out infinite' }} />
              </div>
              <p className="text-[11px] text-muted-foreground mt-2 flex items-center gap-1">
                <Info className="h-3 w-3 flex-shrink-0" />
                This disk&apos;s firmware does not support progress reporting. The test is running in the background.
              </p>
            </>
          )}
        </div>
      )}
      
      {/* Last Test Result — only show if a test was executed from ProxMenux (lastTestDate exists)
           or if currently running/just completed a test. Tests from the drive's internal log
           (e.g. factory tests) are only shown in the full SMART report. */}
      {testStatus.last_test && lastTestDate && (
        <div className="flex items-center gap-3 flex-wrap">
          {testStatus.last_test.status === 'passed' ? (
            <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
          )}
          <span className="text-sm font-medium">
            Last Test: {testStatus.last_test.type === 'short' ? 'Short' : 'Extended'}
          </span>
          <Badge className={testStatus.last_test.status === 'passed'
            ? 'bg-green-500/10 text-green-500 border-green-500/20'
            : 'bg-red-500/10 text-red-500 border-red-500/20'
          }>
            {testStatus.last_test.status}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {new Date(lastTestDate).toLocaleString()}
          </span>
        </div>
      )}
      
      {/* SMART Attributes Summary */}
      {testStatus.smart_data?.attributes && testStatus.smart_data.attributes.length > 0 && (
        <div className="space-y-3">
          <h4 className="font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4" />
            {isNvme ? 'NVMe Health Metrics' : testStatus.smart_data?.is_sas ? 'SAS/SCSI Health Metrics' : 'SMART Attributes'}
          </h4>
          <div className="border rounded-lg overflow-hidden">
            <div className={`grid ${(isNvme || testStatus.smart_data?.is_sas) ? 'grid-cols-10' : 'grid-cols-12'} gap-2 p-3 bg-muted/30 text-xs font-medium text-muted-foreground`}>
              {!isNvme && !testStatus.smart_data?.is_sas && <div className="col-span-1">ID</div>}
              <div className={(isNvme || testStatus.smart_data?.is_sas) ? 'col-span-5' : 'col-span-5'}>Attribute</div>
              <div className={(isNvme || testStatus.smart_data?.is_sas) ? 'col-span-3 text-center' : 'col-span-2 text-center'}>Value</div>
              {!isNvme && !testStatus.smart_data?.is_sas && <div className="col-span-2 text-center">Worst</div>}
              <div className="col-span-2 text-center">Status</div>
            </div>
            <div className="divide-y divide-border max-h-[200px] overflow-y-auto">
              {testStatus.smart_data.attributes.slice(0, 15).map((attr) => (
                <div key={attr.id} className={`grid ${(isNvme || testStatus.smart_data?.is_sas) ? 'grid-cols-10' : 'grid-cols-12'} gap-2 p-3 text-sm items-center`}>
                  {!isNvme && !testStatus.smart_data?.is_sas && <div className="col-span-1 text-muted-foreground">{attr.id}</div>}
                  <div className={`${(isNvme || testStatus.smart_data?.is_sas) ? 'col-span-5' : 'col-span-5'} truncate`} title={attr.name}>{attr.name}</div>
                  <div className={`${(isNvme || testStatus.smart_data?.is_sas) ? 'col-span-3' : 'col-span-2'} text-center font-mono`}>{testStatus.smart_data?.is_sas ? attr.raw_value : attr.value}</div>
                  {!isNvme && !testStatus.smart_data?.is_sas && <div className="col-span-2 text-center font-mono text-muted-foreground">{attr.worst}</div>}
                  <div className="col-span-2 text-center">
                    {attr.status === 'ok' ? (
                      <CheckCircle2 className="h-4 w-4 text-green-500 mx-auto" />
                    ) : attr.status === 'warning' ? (
                      <AlertTriangle className="h-4 w-4 text-yellow-500 mx-auto" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-500 mx-auto" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      
      {/* View Full Report Button */}
      <div className="pt-4 border-t">
        <Button
          variant="outline"
          className="w-full gap-2 bg-blue-500/10 border-blue-500/30 text-blue-500 hover:bg-blue-500/20 hover:text-blue-400"
          onClick={async () => {
            // Open placeholder window synchronously so the popup blocker
            // sees the user gesture; then fetch temp history and hand
            // the populated tempHistory + targetWindow to openSmartReport.
            const reportWindow = window.open('about:blank', '_blank')
            if (reportWindow) {
              reportWindow.document.write('<html><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><div style="border:3px solid transparent;border-top-color:#06b6d4;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:0 auto"></div><p style="margin-top:16px">Loading report...</p><style>@keyframes spin{to{transform:rotate(360deg)}}</style></div></body></html>')
            }
            // Warm the disk-temp threshold cache in parallel with the
            // history fetch so openSmartReport's sync read picks up
            // the user's customised values instead of stale defaults.
            const [tempHistory] = await Promise.all([
              fetchTempHistoryForReport(disk.name),
              loadDiskTempThresholds(),
            ])
            openSmartReport(disk, testStatus, smartAttributes, observations, lastTestDate, reportWindow || undefined, false, tempHistory)
          }}
        >
          <FileText className="h-4 w-4" />
          View Full SMART Report
        </Button>
        <p className="text-xs text-muted-foreground text-center mt-2">
          Generate a comprehensive professional report with detailed analysis and recommendations.
        </p>
      </div>
      

    </div>
  )
}

// ─── History Tab Component ──────────────────────────────────────────────────────

interface SmartHistoryEntry {
  filename: string
  path: string
  timestamp: string
  test_type: string
  date_readable: string
}

function HistoryTab({ disk }: { disk: DiskInfo }) {
  const [history, setHistory] = useState<SmartHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [viewingReport, setViewingReport] = useState<string | null>(null)

  const fetchHistory = async () => {
    try {
      setLoading(true)
      const data = await fetchApi<{ history: SmartHistoryEntry[] }>(`/api/storage/smart/${disk.name}/history?limit=50`)
      setHistory(data.history || [])
    } catch {
      setHistory([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchHistory() }, [disk.name])

  const handleDelete = async (filename: string) => {
    try {
      setDeleting(filename)
      await fetchApi(`/api/storage/smart/${disk.name}/history/${filename}`, { method: 'DELETE' })
      setHistory(prev => prev.filter(h => h.filename !== filename))
    } catch {
      // Silently fail
    } finally {
      setDeleting(null)
    }
  }

  const handleDownload = async (filename: string) => {
    try {
      const response = await fetchApi<Record<string, unknown>>(`/api/storage/smart/${disk.name}/history/${filename}`)
      const blob = new Blob([JSON.stringify(response, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${disk.name}_${filename}`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // Silently fail
    }
  }

  const handleViewReport = async (entry: SmartHistoryEntry) => {
    // Open window IMMEDIATELY on user click (before async) to avoid popup blocker
    const reportWindow = window.open('about:blank', '_blank')
    if (reportWindow) {
      reportWindow.document.write('<html><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><div style="border:3px solid transparent;border-top-color:#06b6d4;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:0 auto"></div><p style="margin-top:16px">Loading report...</p><style>@keyframes spin{to{transform:rotate(360deg)}}</style></div></body></html>')
    }

    try {
      setViewingReport(entry.filename)
      // Fetch full SMART status from backend (same data as SMART tab uses)
      const fullStatus = await fetchApi<SmartTestStatus>(`/api/storage/smart/${disk.name}`)
      const attrs = fullStatus.smart_data?.attributes || []

      const [tempHistory] = await Promise.all([
        fetchTempHistoryForReport(disk.name),
        loadDiskTempThresholds(),
      ])

      openSmartReport(disk, fullStatus, attrs, [], entry.timestamp, reportWindow || undefined, true, tempHistory)
    } catch {
      if (reportWindow && !reportWindow.closed) {
        reportWindow.document.body.innerHTML = '<p style="color:#ef4444;text-align:center;margin-top:40vh">Failed to load report data.</p>'
      }
    } finally {
      setViewingReport(null)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Loading test history...</p>
      </div>
    )
  }

  if (history.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <Archive className="h-12 w-12 mb-3 opacity-30" />
        <span className="text-sm">No test history</span>
        <span className="text-xs mt-1">Run a SMART test to start building history for this disk.</span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="font-semibold flex items-center gap-2">
          <Archive className="h-4 w-4" />
          Test History
          <Badge className="bg-orange-500/10 text-orange-400 border-orange-500/20 text-[10px] px-1.5">
            {history.length}
          </Badge>
        </h4>
      </div>

      <div className="space-y-2">
        {history.map((entry, i) => {
          const isLatest = i === 0
          const testDate = new Date(entry.timestamp)
          const ageDays = Math.floor((Date.now() - testDate.getTime()) / (1000 * 60 * 60 * 24))
          const isDeleting = deleting === entry.filename
          const isViewing = viewingReport === entry.filename

          return (
            <div
              key={entry.filename}
              onClick={() => !isDeleting && handleViewReport(entry)}
              className={`border rounded-lg p-3 flex items-center gap-3 transition-colors cursor-pointer hover:bg-white/5 ${
                isLatest ? 'border-orange-500/30' : 'border-border'
              } ${isDeleting ? 'opacity-50 pointer-events-none' : ''} ${isViewing ? 'opacity-70' : ''}`}
            >
              {isViewing ? (
                <Loader2 className="h-4 w-4 animate-spin text-orange-400 flex-shrink-0" />
              ) : (
                <Badge className={`text-[10px] px-1.5 flex-shrink-0 ${
                  entry.test_type === 'long'
                    ? 'bg-orange-500/10 text-orange-400 border-orange-500/20'
                    : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
                }`}>
                  {entry.test_type === 'long' ? 'Extended' : 'Short'}
                </Badge>
              )}

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">
                  {testDate.toLocaleString()}
                  {isLatest && <span className="text-[10px] text-orange-400 ml-2">latest</span>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {ageDays === 0 ? 'Today' : ageDays === 1 ? 'Yesterday' : `${ageDays} days ago`}
                </p>
              </div>

              <div className="flex items-center gap-1 flex-shrink-0">
                <Button
                  variant="ghost" size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-blue-400"
                  onClick={(e: unknown) => { (e as MouseEvent).stopPropagation(); handleDownload(entry.filename) }}
                  title="Download JSON"
                >
                  <Download className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost" size="sm"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-red-400"
                  onClick={(e: unknown) => { (e as MouseEvent).stopPropagation(); if (confirm('Delete this test record?')) handleDelete(entry.filename) }}
                  disabled={isDeleting}
                  title="Delete"
                >
                  {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                </Button>
              </div>
            </div>
          )
        })}
      </div>

      <p className="text-xs text-muted-foreground text-center pt-2">
        Test results are stored locally and used to generate detailed SMART reports.
      </p>
    </div>
  )
}

// ─── Schedule Tab Component ─────────────────────────────────────────────────────

interface SmartSchedule {
  id: string
  active: boolean
  test_type: 'short' | 'long'
  frequency: 'daily' | 'weekly' | 'monthly'
  hour: number
  minute: number
  day_of_week: number
  day_of_month: number
  disks: string[]
  retention: number
  notify_on_complete: boolean
  notify_only_on_failure: boolean
}

interface ScheduleConfig {
  enabled: boolean
  schedules: SmartSchedule[]
}

function ScheduleTab({ disk }: { disk: DiskInfo }) {
  const [config, setConfig] = useState<ScheduleConfig>({ enabled: true, schedules: [] })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [editingSchedule, setEditingSchedule] = useState<SmartSchedule | null>(null)
  
  // Form state
  const [formData, setFormData] = useState<Partial<SmartSchedule>>({
    test_type: 'short',
    frequency: 'weekly',
    hour: 3,
    minute: 0,
    day_of_week: 0,
    day_of_month: 1,
    disks: [disk.name],
    retention: 10,
    active: true,
    notify_on_complete: true,
    notify_only_on_failure: false
  })

  const fetchSchedules = async () => {
    try {
      setLoading(true)
      const data = await fetchApi<ScheduleConfig>('/api/storage/smart/schedules')
      setConfig(data)
    } catch {
      console.error('Failed to load schedules')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSchedules()
  }, [])

  const handleToggleGlobal = async () => {
    try {
      setSaving(true)
      await fetchApi('/api/storage/smart/schedules/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !config.enabled })
      })
      setConfig(prev => ({ ...prev, enabled: !prev.enabled }))
    } catch {
      console.error('Failed to toggle schedules')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveSchedule = async () => {
    try {
      setSaving(true)
      const scheduleData = {
        ...formData,
        id: editingSchedule?.id || undefined
      }
      
      await fetchApi('/api/storage/smart/schedules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scheduleData)
      })
      
      await fetchSchedules()
      setShowForm(false)
      setEditingSchedule(null)
      resetForm()
    } catch {
      console.error('Failed to save schedule')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteSchedule = async (id: string) => {
    try {
      setSaving(true)
      await fetchApi(`/api/storage/smart/schedules/${id}`, {
        method: 'DELETE'
      })
      await fetchSchedules()
    } catch {
      console.error('Failed to delete schedule')
    } finally {
      setSaving(false)
    }
  }

  const resetForm = () => {
    setFormData({
      test_type: 'short',
      frequency: 'weekly',
      hour: 3,
      minute: 0,
      day_of_week: 0,
      day_of_month: 1,
      disks: [disk.name],
      retention: 10,
      active: true,
      notify_on_complete: true,
      notify_only_on_failure: false
    })
  }

  const editSchedule = (schedule: SmartSchedule) => {
    setEditingSchedule(schedule)
    setFormData(schedule)
    setShowForm(true)
  }

  const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
  
  const formatScheduleTime = (schedule: SmartSchedule) => {
    const time = `${schedule.hour.toString().padStart(2, '0')}:${schedule.minute.toString().padStart(2, '0')}`
    if (schedule.frequency === 'daily') return `Daily at ${time}`
    if (schedule.frequency === 'weekly') return `${dayNames[schedule.day_of_week]}s at ${time}`
    return `Day ${schedule.day_of_month} of month at ${time}`
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="h-6 w-6 rounded-full border-2 border-transparent border-t-purple-400 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading schedules...</span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Global Toggle */}
      <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
        <div>
          <p className="font-medium">Automatic SMART Tests</p>
          <p className="text-xs text-muted-foreground">Enable or disable all scheduled tests</p>
        </div>
        <Button
          variant={config.enabled ? "default" : "outline"}
          size="sm"
          onClick={handleToggleGlobal}
          disabled={saving}
          className={config.enabled ? "bg-purple-600 hover:bg-purple-700" : ""}
        >
          {config.enabled ? 'Enabled' : 'Disabled'}
        </Button>
      </div>

      {/* Schedules List */}
      {config.schedules.length > 0 ? (
        <div className="space-y-2">
          <h4 className="font-semibold text-sm">Configured Schedules</h4>
          {config.schedules.map(schedule => (
            <div 
              key={schedule.id}
              className={`border rounded-lg p-3 ${schedule.active ? 'border-purple-500/30 bg-purple-500/5' : 'border-muted opacity-60'}`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Badge className={schedule.test_type === 'long' ? 'bg-orange-500/10 text-orange-400 border-orange-500/20' : 'bg-blue-500/10 text-blue-400 border-blue-500/20'}>
                      {schedule.test_type}
                    </Badge>
                    <span className="text-sm font-medium">{formatScheduleTime(schedule)}</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Disks: {schedule.disks.includes('all') ? 'All disks' : schedule.disks.join(', ')} | 
                    Keep {schedule.retention} results
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => editSchedule(schedule)}
                    className="h-8 w-8 p-0"
                  >
                    <Settings className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDeleteSchedule(schedule.id)}
                    className="h-8 w-8 p-0 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                    disabled={saving}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-6 text-muted-foreground">
          <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p>No scheduled tests configured</p>
          <p className="text-xs mt-1">Create a schedule to automatically run SMART tests</p>
        </div>
      )}

      {/* Add/Edit Form */}
      {showForm ? (
        <div className="border rounded-lg p-4 space-y-4">
          <h4 className="font-semibold">{editingSchedule ? 'Edit Schedule' : 'New Schedule'}</h4>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-muted-foreground">Test Type</label>
              <select
                value={formData.test_type}
                onChange={e => setFormData(prev => ({ ...prev, test_type: e.target.value as 'short' | 'long' }))}
                className="w-full mt-1 p-2 rounded-md bg-background border border-input text-sm"
              >
                <option value="short">Short Test (~2 min)</option>
                <option value="long">Long Test (1-4 hours)</option>
              </select>
            </div>
            
            <div>
              <label className="text-sm text-muted-foreground">Frequency</label>
              <select
                value={formData.frequency}
                onChange={e => setFormData(prev => ({ ...prev, frequency: e.target.value as 'daily' | 'weekly' | 'monthly' }))}
                className="w-full mt-1 p-2 rounded-md bg-background border border-input text-sm"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            
            {formData.frequency === 'weekly' && (
              <div>
                <label className="text-sm text-muted-foreground">Day of Week</label>
                <select
                  value={formData.day_of_week}
                  onChange={e => setFormData(prev => ({ ...prev, day_of_week: parseInt(e.target.value) }))}
                  className="w-full mt-1 p-2 rounded-md bg-background border border-input text-sm"
                >
                  {dayNames.map((day, i) => (
                    <option key={day} value={i}>{day}</option>
                  ))}
                </select>
              </div>
            )}
            
            {formData.frequency === 'monthly' && (
              <div>
                <label className="text-sm text-muted-foreground">Day of Month</label>
                <select
                  value={formData.day_of_month}
                  onChange={e => setFormData(prev => ({ ...prev, day_of_month: parseInt(e.target.value) }))}
                  className="w-full mt-1 p-2 rounded-md bg-background border border-input text-sm"
                >
                  {Array.from({ length: 28 }, (_, i) => i + 1).map(day => (
                    <option key={day} value={day}>{day}</option>
                  ))}
                </select>
              </div>
            )}
            
            <div>
              <label className="text-sm text-muted-foreground">Time (Hour)</label>
              <select
                value={formData.hour}
                onChange={e => setFormData(prev => ({ ...prev, hour: parseInt(e.target.value) }))}
                className="w-full mt-1 p-2 rounded-md bg-background border border-input text-sm"
              >
                {Array.from({ length: 24 }, (_, i) => (
                  <option key={i} value={i}>{i.toString().padStart(2, '0')}:00</option>
                ))}
              </select>
            </div>
            
            <div>
              <label className="text-sm text-muted-foreground">Keep Results</label>
              <select
                value={formData.retention}
                onChange={e => setFormData(prev => ({ ...prev, retention: parseInt(e.target.value) }))}
                className="w-full mt-1 p-2 rounded-md bg-background border border-input text-sm"
              >
                <option value={5}>Last 5</option>
                <option value={10}>Last 10</option>
                <option value={20}>Last 20</option>
                <option value={50}>Last 50</option>
                <option value={0}>Keep All</option>
              </select>
            </div>
          </div>
          
          <div className="flex items-center gap-2 pt-2">
            <Button
              onClick={handleSaveSchedule}
              disabled={saving}
              className="bg-purple-600 hover:bg-purple-700 text-white"
            >
              {saving ? 'Saving...' : 'Save Schedule'}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setShowForm(false)
                setEditingSchedule(null)
                resetForm()
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button
          onClick={() => setShowForm(true)}
          variant="outline"
          className="w-full"
        >
          <Plus className="h-4 w-4 mr-2" />
          Add Schedule
        </Button>
      )}
      
      <p className="text-xs text-muted-foreground text-center">
        Scheduled tests run automatically via cron. Results are saved to the SMART history.
      </p>
    </div>
  )
}
