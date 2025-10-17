"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { HardDrive, Database, AlertTriangle, CheckCircle2, XCircle, Square, Thermometer } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

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
}

interface ProxmoxStorageData {
  storage: ProxmoxStorage[]
  error?: string
}

const formatStorage = (sizeInGB: number): string => {
  if (sizeInGB < 1) {
    // Less than 1 GB, show in MB
    return `${(sizeInGB * 1024).toFixed(1)} MB`
  } else if (sizeInGB < 1024) {
    // Less than 1024 GB, show in GB
    return `${sizeInGB.toFixed(1)} GB`
  } else {
    // 1024 GB or more, show in TB
    return `${(sizeInGB / 1024).toFixed(1)} TB`
  }
}

export function StorageOverview() {
  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [proxmoxStorage, setProxmoxStorage] = useState<ProxmoxStorageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedDisk, setSelectedDisk] = useState<DiskInfo | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)

  const fetchStorageData = async () => {
    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""

      const [storageResponse, proxmoxResponse] = await Promise.all([
        fetch(`${baseUrl}/api/storage`),
        fetch(`${baseUrl}/api/proxmox-storage`),
      ])

      const data = await storageResponse.json()
      const proxmoxData = await proxmoxResponse.json()

      console.log("[v0] Storage data received:", data)
      console.log("[v0] Proxmox storage data received:", proxmoxData)

      setStorageData(data)
      setProxmoxStorage(proxmoxData)
    } catch (error) {
      console.error("Error fetching storage data:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStorageData()
    const interval = setInterval(fetchStorageData, 60000)
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

    // Determinar el tipo de disco
    let diskType = "HDD" // Por defecto
    if (diskName) {
      if (diskName.startsWith("nvme")) {
        diskType = "NVMe"
      } else if (!rotationRate || rotationRate === 0) {
        diskType = "SSD"
      }
    }

    // Aplicar rangos de temperatura según el tipo
    switch (diskType) {
      case "NVMe":
        // NVMe: ≤70°C verde, 71-80°C amarillo, >80°C rojo
        if (temp <= 70) return "text-green-500"
        if (temp <= 80) return "text-yellow-500"
        return "text-red-500"

      case "SSD":
        // SSD: ≤59°C verde, 60-70°C amarillo, >70°C rojo
        if (temp <= 59) return "text-green-500"
        if (temp <= 70) return "text-yellow-500"
        return "text-red-500"

      case "HDD":
      default:
        // HDD: ≤45°C verde, 46-55°C amarillo, >55°C rojo
        if (temp <= 45) return "text-green-500"
        if (temp <= 55) return "text-yellow-500"
        return "text-red-500"
    }
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

  const handleDiskClick = (disk: DiskInfo) => {
    setSelectedDisk(disk)
    setDetailsOpen(true)
  }

  const getStorageTypeBadge = (type: string) => {
    const typeColors: Record<string, string> = {
      pbs: "bg-purple-500/10 text-purple-500 border-purple-500/20",
      dir: "bg-blue-500/10 text-blue-500 border-blue-500/20",
      lvmthin: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
      zfspool: "bg-green-500/10 text-green-500 border-green-500/20",
      nfs: "bg-orange-500/10 text-orange-500 border-orange-500/20",
      cifs: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    }
    return typeColors[type.toLowerCase()] || "bg-gray-500/10 text-gray-500 border-gray-500/20"
  }

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case "active":
      case "online":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
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

    // Si el desgaste es 0, no podemos calcular
    if (wearPercent === 0) {
      return "N/A"
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
        // Si no hay temperatura, considerarlo normal
        normal++
        return
      }

      const diskType = getDiskType(disk.name, disk.rotation_rate)

      switch (diskType) {
        case "NVMe":
          if (disk.temperature <= 70) normal++
          else if (disk.temperature <= 80) warning++
          else critical++
          break
        case "SSD":
          if (disk.temperature <= 59) normal++
          else if (disk.temperature <= 70) warning++
          else critical++
          break
        case "HDD":
        default:
          if (disk.temperature <= 45) normal++
          else if (disk.temperature <= 55) warning++
          else critical++
          break
      }
    })

    return { normal, warning, critical }
  }

  const getDiskTypesBreakdown = () => {
    if (!storageData || !storageData.disks) {
      return { nvme: 0, ssd: 0, hdd: 0 }
    }

    let nvme = 0
    let ssd = 0
    let hdd = 0

    storageData.disks.forEach((disk) => {
      const diskType = getDiskType(disk.name, disk.rotation_rate)
      if (diskType === "NVMe") nvme++
      else if (diskType === "SSD") ssd++
      else if (diskType === "HDD") hdd++
    })

    return { nvme, ssd, hdd }
  }

  const getWearProgressColor = (wearPercent: number): string => {
    if (wearPercent < 70) return "[&>div]:bg-blue-500"
    if (wearPercent < 85) return "[&>div]:bg-yellow-500"
    return "[&>div]:bg-red-500"
  }

  const diskHealthBreakdown = getDiskHealthBreakdown()
  const diskTypesBreakdown = getDiskTypesBreakdown()

  const totalProxmoxUsed =
    proxmoxStorage && proxmoxStorage.storage
      ? proxmoxStorage.storage
          .filter(
            (storage) => storage && storage.total > 0 && storage.status && storage.status.toLowerCase() === "active",
          )
          .reduce((sum, storage) => sum + storage.used, 0)
      : 0

  const usagePercent =
    storageData && storageData.total > 0 ? ((totalProxmoxUsed / (storageData.total * 1024)) * 100).toFixed(2) : "0.00"

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading storage information...</div>
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
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.total.toFixed(1)} TB</div>
            <p className="text-xs text-muted-foreground mt-1">{storageData.disk_count} physical disks</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Used Storage</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatStorage(totalProxmoxUsed)}</div>
            <p className="text-xs text-muted-foreground mt-1">{usagePercent}% used</p>
          </CardContent>
        </Card>

        {/* Disk Health */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Disk Health</CardTitle>
            <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.disk_count} disks</div>
            <p className="text-xs mt-1">
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
          </CardContent>
        </Card>

        {/* Disk Types */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Disk Types</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.disk_count} disks</div>
            <p className="text-xs mt-1">
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
            </p>
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
                .filter((storage) => storage && storage.name && storage.total > 0)
                .map((storage) => (
                  <div key={storage.name} className="border rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      {/* Desktop: Icon + Name + Badge tipo alineados horizontalmente */}
                      <div className="hidden md:flex items-center gap-3">
                        <Database className="h-5 w-5 text-muted-foreground" />
                        <h3 className="font-semibold text-lg">{storage.name}</h3>
                        <Badge className={getStorageTypeBadge(storage.type)}>{storage.type}</Badge>
                      </div>

                      <div className="flex md:hidden items-center gap-2 flex-1">
                        <Database className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                        <Badge className={getStorageTypeBadge(storage.type)}>{storage.type}</Badge>
                        <h3 className="font-semibold text-base flex-1 min-w-0 truncate">{storage.name}</h3>
                        {getStatusIcon(storage.status)}
                      </div>

                      {/* Desktop: Badge active + Porcentaje */}
                      <div className="hidden md:flex items-center gap-2">
                        <Badge
                          className={
                            storage.status === "active"
                              ? "bg-green-500/10 text-green-500 border-green-500/20"
                              : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                          }
                        >
                          {storage.status}
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
                          <p className="font-medium">{storage.total.toLocaleString()} GB</p>
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
                            {storage.used.toLocaleString()} GB
                          </p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Available</p>
                          <p className="font-medium text-green-400">{storage.available.toLocaleString()} GB</p>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

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
                      <p className="text-muted-foreground">Size</p>
                      <p className="font-medium">{pool.size}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Allocated</p>
                      <p className="font-medium">{pool.allocated}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Free</p>
                      <p className="font-medium">{pool.free}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Physical Disks */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="h-5 w-5" />
            Physical Disks & SMART Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {storageData.disks.map((disk) => (
              <div
                key={disk.name}
                className="border-2 border-accent/20 rounded-lg p-4 cursor-pointer bg-accent/10 hover:bg-accent/20 transition-colors"
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
                      {getHealthBadge(disk.health)}
                    </div>
                  </div>
                </div>

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
                      <p className="font-medium text-xs">{disk.serial}</p>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Disk Details Dialog */}
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              Disk Details: /dev/{selectedDisk?.name}
            </DialogTitle>
            <DialogDescription>Complete SMART information and health status</DialogDescription>
          </DialogHeader>
          {selectedDisk && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Model</p>
                  <p className="font-medium">{selectedDisk.model}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Serial Number</p>
                  <p className="font-medium">{selectedDisk.serial}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Capacity</p>
                  <p className="font-medium">{selectedDisk.size_formatted}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Health Status</p>
                  <div className="mt-1">{getHealthBadge(selectedDisk.health)}</div>
                </div>
              </div>

              {/* Wear & Lifetime Section */}
              {getWearIndicator(selectedDisk) && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">Wear & Lifetime</h4>
                  <div className="space-y-3">
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-sm text-muted-foreground">{getWearIndicator(selectedDisk)!.label}</p>
                        <p className={`font-medium ${getWearColor(getWearIndicator(selectedDisk)!.value)}`}>
                          {getWearIndicator(selectedDisk)!.value}%
                        </p>
                      </div>
                      <Progress
                        value={getWearIndicator(selectedDisk)!.value}
                        className={`h-2 ${getWearProgressColor(getWearIndicator(selectedDisk)!.value)}`}
                      />
                    </div>
                    {getEstimatedLifeRemaining(selectedDisk) && (
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-sm text-muted-foreground">Estimated Life Remaining</p>
                          <p className="font-medium">{getEstimatedLifeRemaining(selectedDisk)}</p>
                        </div>
                        {selectedDisk.total_lbas_written && selectedDisk.total_lbas_written > 0 && (
                          <div>
                            <p className="text-sm text-muted-foreground">Total Data Written</p>
                            <p className="font-medium">
                              {selectedDisk.total_lbas_written >= 1024
                                ? `${(selectedDisk.total_lbas_written / 1024).toFixed(2)} TB`
                                : `${selectedDisk.total_lbas_written.toFixed(2)} GB`}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">SMART Attributes</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Temperature</p>
                    <p
                      className={`font-medium ${getTempColor(selectedDisk.temperature, selectedDisk.name, selectedDisk.rotation_rate)}`}
                    >
                      {selectedDisk.temperature > 0 ? `${selectedDisk.temperature}°C` : "N/A"}
                    </p>
                  </div>
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
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
